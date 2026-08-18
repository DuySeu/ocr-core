"""Stage 3: table_cv then a text detector, text boxes mostly inside a table dropped.

Containment, not IoU (§4.2): a one-line text block sitting inside a table that
covers 30% of the page has an IoU near 0.1 and would survive an IoU filter,
duplicating every table cell into the prose output too. The ratio here is
intersection over the *text* box's own area, so a small block fully inside a
table is caught regardless of how big the table is.
"""

from __future__ import annotations

from PIL import Image

from .base import LayoutBox, LayoutDetector, LayoutError
from .none import NoneDetector
from .table_cv import TableCVDetector
from .tesseract_blocks import TesseractBlockDetector

CONTAINMENT_THRESHOLD = 0.7  # not 1.0, to tolerate a few pixels of disagreement between detectors

_DETECTORS = {"tesseract": TesseractBlockDetector, "none": NoneDetector}

__all__ = ["LayoutBox", "LayoutDetector", "LayoutError", "get_detector", "detect"]


def get_detector(name: str) -> LayoutDetector:
    if name not in _DETECTORS:
        raise LayoutError(f"unknown layout {name!r}; valid: {sorted(_DETECTORS)}")
    return _DETECTORS[name]()


# Stage 3 entrypoint: table_cv always runs, then the configured text detector,
# minus whatever text falls mostly inside a table (§4.2).
def detect(image: Image.Image, cfg) -> list[LayoutBox]:
    table_boxes = TableCVDetector().detect(image, cfg.langs)
    text_boxes = get_detector(cfg.layout).detect(image, cfg.langs)
    kept_text = [tb for tb in text_boxes if _containment(tb, table_boxes) < CONTAINMENT_THRESHOLD]
    return table_boxes + kept_text


# Fraction of a text box's own area covered by the most-overlapping table box.
def _containment(text_box: LayoutBox, table_boxes: list[LayoutBox]) -> float:
    _, _, w, h = text_box.bbox
    text_area = w * h
    if text_area == 0 or not table_boxes:
        return 0.0
    return max(_intersection_area(text_box.bbox, t.bbox) for t in table_boxes) / text_area


def _intersection_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    return max(0, x1 - x0) * max(0, y1 - y0)
