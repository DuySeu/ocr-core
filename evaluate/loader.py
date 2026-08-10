"""Reading COCO box annotations into the one shape scoring works on.

Boxes are converted to relative [0,1] coordinates here, which makes IoU
independent of render DPI. What it does not make them independent of is deskew:
both sides live in the canonical post-deskew frame, so gold annotated against a
different deskew angle than the prediction is rotated relative to it and would
score badly for a reason that has nothing to do with the detector. The angle
therefore travels with the page and the caller compares it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Deskew angles further apart than this put the two sides in different frames.
DESKEW_TOLERANCE_DEG = 0.1


@dataclass(frozen=True)
class EvalElement:
    """One COCO annotation, reduced to what the metrics need."""

    id: int
    page: int
    category: str  # DocLayNet name, never the numeric id
    bbox: tuple[float, float, float, float]  # x, y, w, h — relative [0,1]
    text: str | None
    html: str | None


@dataclass(frozen=True)
class PageFrame:
    """The canonical frame a page's boxes are expressed in."""

    page: int
    width: int
    height: int
    deskew_angle: float
    rotation_applied: int


@dataclass(frozen=True)
class CocoDocument:
    """One parsed COCO file, indexed by page."""

    elements: dict[int, list[EvalElement]]
    frames: dict[int, PageFrame]
    page_errors: set[int]  # pages the pipeline could not process at all


class LoaderError(Exception):
    """Raised when a file cannot be read as the schema the evaluator expects."""


# Parse a COCO file into per-page elements and frames, with boxes made relative.
def load_coco(path: Path) -> CocoDocument:
    if not path.exists():
        raise LoaderError(f"COCO file not found: {path}")

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LoaderError(f"{path} is not valid JSON: {e}") from e

    # Index the category table of this file; two runs may number categories differently
    names = {c["id"]: c["name"] for c in parsed.get("categories", [])}

    frames: dict[int, PageFrame] = {}
    for image in parsed.get("images", []):
        width, height = int(image["width"]), int(image["height"])
        if width <= 0 or height <= 0:
            raise LoaderError(f"{path} image {image['id']} has a non-positive size")

        geometry = image.get("page_geometry", {})
        frames[int(image["id"])] = PageFrame(
            page=int(image["id"]),
            width=width,
            height=height,
            deskew_angle=float(geometry.get("deskew_angle", 0.0)),
            rotation_applied=int(geometry.get("rotation_applied", 0)),
        )

    elements: dict[int, list[EvalElement]] = {page: [] for page in frames}
    for annotation in parsed.get("annotations", []):
        page = int(annotation["image_id"])
        frame = frames.get(page)
        if frame is None:
            raise LoaderError(f"{path} annotation {annotation['id']} points at unknown page {page}")

        category_id = annotation["category_id"]
        if category_id not in names:
            raise LoaderError(f"{path} annotation {annotation['id']} has unknown category id")

        x, y, w, h = (float(v) for v in annotation["bbox"])
        elements[page].append(
            EvalElement(
                id=int(annotation["id"]),
                page=page,
                category=names[category_id],
                bbox=(x / frame.width, y / frame.height, w / frame.width, h / frame.height),
                text=annotation.get("text"),
                html=annotation.get("html"),
            )
        )

    # page_errors is written as bare page numbers or as records carrying one
    raw_errors = parsed.get("info", {}).get("page_errors", [])
    page_errors = {int(e["page"]) if isinstance(e, dict) else int(e) for e in raw_errors}

    return CocoDocument(elements=elements, frames=frames, page_errors=page_errors)
