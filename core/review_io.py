"""Export weak OCR pages for manual review and apply corrected page text.

Review files are human-editable: one preprocess image plus one markdown page
blob whose body lines map 1:1 onto TextLine.text in reading order.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from PIL import Image

from core.document.model import Document, Element, TextContent, TextLine
from core.document.serde import document_from_dict, document_to_dict
from core.qa import gate

logger = logging.getLogger(__name__)

HEADER_RE = re.compile(
    r"^<!--\s*page:\s*(\d+)\s+lines:\s*(\d+)\s*-->\s*$"
)


class ReviewError(Exception):
    """Raised when review export/apply cannot proceed safely."""


def document_json_path(out_dir: Path) -> Path:
    """Return the path of the Document snapshot beside other outputs."""
    return out_dir / f"{out_dir.name}.document.json"


def write_document_json(doc: Document, out_dir: Path) -> Path:
    """Write the full Document snapshot used by apply-review."""
    path = document_json_path(out_dir)
    path.write_text(
        json.dumps(document_to_dict(doc), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_document_json(out_dir: Path) -> Document:
    """Load a Document snapshot from output/<stem>/<stem>.document.json."""
    path = document_json_path(out_dir)
    if not path.is_file():
        raise ReviewError(f"missing document snapshot: {path}")
    return document_from_dict(json.loads(path.read_text(encoding="utf-8")))


def page_text_lines(elements: list[Element], page: int) -> list[TextLine]:
    """Collect TextLines on one page in reading_order."""
    page_elements = sorted(
        (e for e in elements if e.page == page),
        key=lambda e: e.reading_order,
    )
    lines: list[TextLine] = []
    for element in page_elements:
        if isinstance(element.content, TextContent):
            lines.extend(element.content.lines)
    return lines


def format_page_markdown(page: int, lines: list[TextLine]) -> str:
    """Build the editable page markdown (header + one line per TextLine)."""
    body = "\n".join(line.text for line in lines)
    header = f"<!-- page: {page} lines: {len(lines)} -->"
    if body:
        return f"{header}\n{body}\n"
    return f"{header}\n"


def parse_page_markdown(text: str) -> tuple[int, list[str]]:
    """Parse a review page markdown into (page_number, body_lines).

    Args:
        text: Full file contents.

    Returns:
        Page number and body lines (may be empty).

    Raises:
        ReviewError: Header missing or malformed.
    """
    if not text:
        raise ReviewError("empty review markdown")
    parts = text.split("\n")
    # File write always ends with \\n; drop that empty segment only
    if text.endswith("\n"):
        parts = parts[:-1]
    if not parts:
        raise ReviewError("empty review markdown")
    match = HEADER_RE.match(parts[0].strip())
    if not match:
        raise ReviewError(f"missing or bad review header: {parts[0]!r}")
    page = int(match.group(1))
    declared = int(match.group(2))
    body = parts[1:]
    if len(body) != declared:
        raise ReviewError(
            f"page {page}: header says lines={declared}, "
            f"body has {len(body)}"
        )
    return page, body


def export_failing_pages(
    doc: Document,
    page_images: dict[int, Image.Image],
    review_stem_dir: Path,
    qa_threshold: float,
) -> list[int]:
    """Dump preprocess image + markdown for each page that fails QA.

    Args:
        doc: Assembled document (full output already written elsewhere).
        page_images: Preprocess images keyed by page number.
        review_stem_dir: review/<stem>/ directory.
        qa_threshold: Confidence gate threshold.

    Returns:
        Page numbers that were exported.
    """
    review_stem_dir.mkdir(parents=True, exist_ok=True)
    exported: list[int] = []

    pages = sorted({e.page for e in doc.elements})
    for page in pages:
        elements = [e for e in doc.elements if e.page == page]
        if not elements:
            continue
        verdict = gate(elements, qa_threshold)
        if verdict.passed:
            continue
        image = page_images.get(page)
        if image is None:
            raise ReviewError(f"no preprocess image for page {page}")
        lines = page_text_lines(doc.elements, page)
        stem = f"p{page:04d}"
        image.save(review_stem_dir / f"{stem}.webp")
        (review_stem_dir / f"{stem}.md").write_text(
            format_page_markdown(page, lines), encoding="utf-8"
        )
        exported.append(page)
        logger.info("review export page %d -> %s", page, review_stem_dir)

    return exported


def apply_page_texts(doc: Document, corrections: dict[int, list[str]]) -> None:
    """Apply corrected body lines onto TextLine.text in place.

    Args:
        doc: Document to mutate.
        corrections: page number -> new line texts (same count as TextLines).

    Raises:
        ReviewError: Line count mismatch for any page.
    """
    for page, new_texts in sorted(corrections.items()):
        lines = page_text_lines(doc.elements, page)
        if len(new_texts) != len(lines):
            raise ReviewError(
                f"page {page}: expected {len(lines)} lines, "
                f"got {len(new_texts)}"
            )
        if not lines:
            continue
        # Rebuild TextContent per element so joins stay consistent
        cursor = 0
        page_elements = sorted(
            (e for e in doc.elements if e.page == page),
            key=lambda e: e.reading_order,
        )
        for element in page_elements:
            if not isinstance(element.content, TextContent):
                continue
            n = len(element.content.lines)
            chunk = new_texts[cursor : cursor + n]
            cursor += n
            new_lines = [
                TextLine(
                    text=chunk[i],
                    text_ocr=old.text_ocr,
                    polygon=old.polygon,
                    bbox=old.bbox,
                    confidence=old.confidence,
                )
                for i, old in enumerate(element.content.lines)
            ]
            element.content = TextContent(
                text="\n".join(line.text for line in new_lines),
                lines=new_lines,
            )


def load_review_corrections(review_stem_dir: Path) -> dict[int, list[str]]:
    """Read every pNNNN.md under a review stem directory.

    Args:
        review_stem_dir: review/<stem>/.

    Returns:
        Map of page number to body lines.

    Raises:
        ReviewError: No markdown pages, or any file fails to parse.
    """
    paths = sorted(review_stem_dir.glob("p*.md"))
    if not paths:
        raise ReviewError(f"no review pages under {review_stem_dir}")
    corrections: dict[int, list[str]] = {}
    for path in paths:
        page, body = parse_page_markdown(path.read_text(encoding="utf-8"))
        corrections[page] = body
    return corrections


def clear_applied_review_pages(
    review_stem_dir: Path, pages: list[int]
) -> None:
    """Remove applied pNNNN.md/.webp files; drop empty stem directory."""
    for page in pages:
        stem = f"p{page:04d}"
        for suffix in (".md", ".webp"):
            path = review_stem_dir / f"{stem}{suffix}"
            if path.exists():
                path.unlink()
    if review_stem_dir.is_dir() and not any(review_stem_dir.iterdir()):
        review_stem_dir.rmdir()
