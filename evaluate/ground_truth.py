"""Loading ground truth, whichever of its two formats a document was written in.

A ``.docx`` is walked through the body rather than through ``document.paragraphs``,
because the latter skips tables entirely and the text inside a table is text the
OCR was asked to read. Walking the body also keeps paragraphs and tables in the
order they appear on the page, which is the order the prediction is in.

Table cells come from ``table_extract.walk_docx_cells`` rather than ``row.cells``,
which reports a vertically merged cell once per row it spans. A cell counted twice
in gold is a cell the engine is charged for twice, so CER and WER read high for a
reason that has nothing to do with the engine.

Files are keyed by filename stem: that is what pairs a ground-truth file with the
prediction of the same name, and the only pairing rule this module knows.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from .table_extract import walk_docx_cells

# Formats a ground-truth document may be written in. Anything else is ignored
# rather than read as text, so a stray .pdf never becomes a comparison target.
TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
DOCX_SUFFIX = ".docx"

# COCO box annotations, if a document has been annotated. Matched by stem too.
BOX_SUFFIXES = (".coco.json", ".json")

DOCX_PARAGRAPH_TAG = "}p"
DOCX_TABLE_TAG = "}tbl"


class GroundTruthError(Exception):
    """Raised when a ground-truth file exists but cannot be read as text."""


# Index every readable ground-truth text file in a directory by filename stem.
def discover_text(directory: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(directory.rglob("*")):
        suffix = path.suffix.lower()
        if not path.is_file() or suffix not in TEXT_SUFFIXES | {DOCX_SUFFIX}:
            continue

        # Two ground-truth files with one stem make the pairing ambiguous
        if path.stem in found:
            raise GroundTruthError(
                f"two ground-truth files share the stem {path.stem!r}: "
                f"{found[path.stem]} and {path}"
            )
        found[path.stem] = path

    return found


# Index every ground-truth COCO box file in a directory by filename stem.
def discover_boxes(directory: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(directory.rglob("*.json")):
        if not path.is_file():
            continue

        # Strip the compound .coco.json suffix so it keys the same stem as the text
        stem = path.name[: -len(".coco.json")] if path.name.endswith(".coco.json") else path.stem
        found.setdefault(stem, path)

    return found


# Read one ground-truth file as plain text, dispatching on its suffix.
def load(path: Path) -> str:
    if not path.exists():
        raise GroundTruthError(f"ground truth not found: {path}")

    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")

    if suffix != DOCX_SUFFIX:
        raise GroundTruthError(
            f"{path} has suffix {suffix!r}; readable formats are "
            f"{sorted(TEXT_SUFFIXES | {DOCX_SUFFIX})}"
        )

    # Walk the body directly so paragraphs and table cells stay in document order
    document = Document(str(path))
    chunks: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith(DOCX_PARAGRAPH_TAG):
            chunks.append(Paragraph(child, document).text)
        elif child.tag.endswith(DOCX_TABLE_TAG):
            table = Table(child, document)
            chunks.extend(cell.text for cell in walk_docx_cells(table))

    return "\n".join(chunks)
