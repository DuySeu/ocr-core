"""Crop TextLine images from deskewed page artifacts for LSTM training."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from core.document import serde
from core.document.model import TextContent, TextLine
from core.geometry import PageGeometry, bounding_box, from_canonical

from finetune.guards import DATA_DIR

logger = logging.getLogger(__name__)

MIN_LINE_HEIGHT_PX = 8
MIN_LINE_WIDTH_PX = 16


class CutError(Exception):
    """Raised when artifacts cannot be read or no line can be cut."""


@dataclass(frozen=True)
class CutReport:
    """How many line crops one cut run wrote."""

    written: int
    skipped_small: int
    pages: int


# Cut every TextLine from one document's artifacts into finetune/data/<sha>/.
def cut_lines(
    artifacts_dir: Path,
    doc_sha256: str,
    pipeline_version: str,
    out_dir: Path | None = None,
) -> CutReport:
    root = _resolve_artifacts(artifacts_dir, doc_sha256, pipeline_version)
    pages_dir = root / "pages"
    images_dir = root / "images"
    if not pages_dir.is_dir():
        raise CutError(f"pages directory not found: {pages_dir}")

    dest = out_dir or (DATA_DIR / doc_sha256[:12])
    dest.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_small = 0
    page_files = sorted(pages_dir.glob("p*.json"))
    for page_path in page_files:
        page_written, page_skipped = _cut_page(
            page_path, images_dir, dest
        )
        written += page_written
        skipped_small += page_skipped

    if written == 0 and not page_files:
        raise CutError(f"no page json under {pages_dir}")

    logger.info(
        "cut %d line(s), skipped %d small, from %d page(s) -> %s",
        written,
        skipped_small,
        len(page_files),
        dest,
    )
    return CutReport(
        written=written,
        skipped_small=skipped_small,
        pages=len(page_files),
    )


# Resolve artifacts/<sha12>/<version>/, accepting a 12-char prefix or full hash.
def _resolve_artifacts(
    artifacts_dir: Path, doc_sha256: str, pipeline_version: str
) -> Path:
    prefix = doc_sha256[:12]
    path = artifacts_dir / prefix / pipeline_version
    if path.is_dir():
        return path
    raise CutError(
        f"artifacts not found: {path} "
        f"(sha={doc_sha256!r}, version={pipeline_version!r})"
    )


# Cut every text line on one page; return (written, skipped_small).
def _cut_page(
    page_path: Path, images_dir: Path, dest: Path
) -> tuple[int, int]:
    data = json.loads(page_path.read_text(encoding="utf-8"))
    geom, elements = serde.page_from_dict(data)
    image_path = images_dir / f"p{geom.page:04d}.webp"
    if not image_path.is_file():
        raise CutError(f"page image not found: {image_path}")

    image = Image.open(image_path)
    written = 0
    skipped = 0
    line_index = 0
    ordered = sorted(elements, key=lambda e: e.reading_order)
    for element in ordered:
        if element.category != "text":
            continue
        if not isinstance(element.content, TextContent):
            continue
        for line in element.content.lines:
            box = _deskew_box(line, geom)
            x, y, w, h = box
            out_name = f"p{geom.page:04d}_l{line_index:03d}.png"
            line_index += 1
            # Keep the index even when skipping so align can match by name
            if h < MIN_LINE_HEIGHT_PX or w < MIN_LINE_WIDTH_PX:
                skipped += 1
                continue
            crop = image.crop((x, y, x + w, y + h))
            crop.save(dest / out_name)
            written += 1
    return written, skipped


# Map a TextLine polygon back to a deskew-frame crop box once.
def _deskew_box(
    line: TextLine, geom: PageGeometry
) -> tuple[int, int, int, int]:
    deskewed = from_canonical(line.polygon, geom)
    return bounding_box(deskewed)
