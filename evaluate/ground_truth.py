"""The ground-truth dataset every tier scores against, and the converter that builds it.

One document is two files side by side in ``ground_truth/<dataset>/``:

- ``<doc_id>.json``: the schema from docs/README.md (``doc_id``, ``file``,
  ``metadata``, ``normalization_version``, ``pages``, ``fields``), with ``full_text``
  replaced by ``text_file``, the name of the markdown beside it.
- ``<doc_id>.md``: the transcription, ``<table>`` markup and ``<!-- image -->``
  markers included. It stays markdown so a reviewer edits text, not JSON strings.

``pages`` and ``fields`` may be empty until a document is annotated; the tier that
needs them reports the document as not scoreable rather than scoring it zero.

``discover_text`` and ``load`` predate the dataset and read loose ``.md``/``.docx``
files by stem. ``finetune/`` still uses them, and on a converted dataset they find
the ``.md`` half of each document.

A ``.docx`` is walked through the body rather than through ``document.paragraphs``,
because the latter skips tables entirely and the text inside a table is text the
OCR was asked to read. Table cells come from ``table_extract.walk_docx_cells``
rather than ``row.cells``, which reports a vertically merged cell once per row it
spans.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from .table_extract import docx_table_html, walk_docx_cells

logger = logging.getLogger(__name__)

# Formats a loose ground-truth document may be written in. Anything else is ignored
# rather than read as text, so a stray .pdf never becomes a comparison target.
TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
DOCX_SUFFIX = ".docx"
MARKDOWN_SUFFIX = ".md"

NORMALIZATION_VERSION = "norm-v1"
REQUIRED_KEYS = ("doc_id", "text_file")

DOCX_PARAGRAPH_TAG = "}p"
DOCX_TABLE_TAG = "}tbl"


@dataclass(frozen=True)
class GroundTruthDoc:
    """One ground-truth document: its JSON record and the markdown it points to."""

    doc_id: str
    json_path: Path
    text_path: Path
    metadata: Mapping[str, Any]
    pages: Sequence[Mapping[str, Any]]
    fields: Mapping[str, Any] | None

    @property
    def text(self) -> str:
        return self.text_path.read_text(encoding="utf-8")


class GroundTruthError(Exception):
    """Raised when a ground-truth file exists but cannot be read, or the dataset is inconsistent."""


# Read every document of a dataset directory, sorted by doc_id.
def load_dataset(directory: Path) -> list[GroundTruthDoc]:
    if not directory.is_dir():
        raise GroundTruthError(f"ground-truth dataset is not a directory: {directory}")

    documents: dict[str, GroundTruthDoc] = {}
    for json_path in sorted(directory.rglob("*.json")):
        try:
            record = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise GroundTruthError(f"{json_path} is not valid JSON: {e}") from e

        if not isinstance(record, dict):
            raise GroundTruthError(f"{json_path} must hold an object, got {type(record).__name__}")
        missing = [key for key in REQUIRED_KEYS if not record.get(key)]
        if missing:
            raise GroundTruthError(f"{json_path} is missing {', '.join(missing)}")

        # text_file is a bare name beside the JSON; anything else could point outside the dataset
        text_name = str(record["text_file"])
        if Path(text_name).name != text_name or not json_path.with_name(text_name).is_file():
            raise GroundTruthError(f"{json_path}: text_file {text_name!r} not found beside it")
        text_path = json_path.with_name(text_name)

        doc_id = str(record["doc_id"])
        if doc_id in documents:
            raise GroundTruthError(
                f"two ground-truth records share the doc_id {doc_id!r}: "
                f"{documents[doc_id].json_path} and {json_path}"
            )

        documents[doc_id] = GroundTruthDoc(
            doc_id=doc_id,
            json_path=json_path,
            text_path=text_path,
            metadata=record.get("metadata") or {},
            pages=record.get("pages") or [],
            fields=record.get("fields"),
        )

    return [documents[doc_id] for doc_id in sorted(documents)]


# Turn loose .md/.txt/.docx ground truth into dataset records; return the JSON paths written.
def convert(source: Path, out: Path, source_dir: Path | None = None) -> list[Path]:
    loose = discover_text(source)

    # A .md written beside its .docx or .txt would give discover_text two files with one stem
    if out.resolve() == source.resolve():
        not_markdown = [p for p in loose.values() if p.suffix.lower() != MARKDOWN_SUFFIX]
        if not_markdown:
            raise GroundTruthError(
                f"{not_markdown[0]}: only .md converts in place; pass --out a different directory"
            )

    out.mkdir(parents=True, exist_ok=True)
    originals = _index_by_stem(source_dir) if source_dir else {}
    written: list[Path] = []
    for stem, path in sorted(loose.items()):
        json_path = out / f"{stem}.json"

        # An existing record may carry annotations; never overwrite it
        if json_path.exists():
            logger.info("kept existing %s", json_path)
            continue

        text_path = out / f"{stem}{MARKDOWN_SUFFIX}"
        if path.resolve() != text_path.resolve():
            markdown = _docx_markdown(path) if path.suffix.lower() == DOCX_SUFFIX else load(path)
            text_path.write_text(markdown, encoding="utf-8")

        original = originals.get(stem)
        record = {
            "doc_id": stem,
            "file": str(original) if original else None,
            "metadata": {},
            "normalization_version": NORMALIZATION_VERSION,
            "text_file": text_path.name,
            "pages": [],
            "fields": {},
        }
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(json_path)

    return written


# Index every readable loose ground-truth text file in a directory by filename stem.
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


# Read one loose ground-truth file as plain text, dispatching on its suffix.
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

    # Paragraphs and table cells as lines, in document order
    chunks: list[str] = []
    for block in _docx_blocks(path):
        if isinstance(block, Table):
            chunks.extend(cell.text for cell in walk_docx_cells(block))
        else:
            chunks.append(block.text)

    return "\n".join(chunks)


# Render a .docx as markdown: one paragraph per block, tables as <table> markup.
def _docx_markdown(path: Path) -> str:
    blocks = [
        docx_table_html(block) if isinstance(block, Table) else block.text
        for block in _docx_blocks(path)
    ]
    return "\n\n".join(block for block in blocks if block.strip()) + "\n"


# Yield the paragraphs and tables of a .docx body in document order.
def _docx_blocks(path: Path) -> Iterator[Paragraph | Table]:
    document = Document(str(path))
    for child in document.element.body.iterchildren():
        if child.tag.endswith(DOCX_PARAGRAPH_TAG):
            yield Paragraph(child, document)
        elif child.tag.endswith(DOCX_TABLE_TAG):
            yield Table(child, document)


# Index the files of a directory by stem, first match wins.
def _index_by_stem(directory: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            found.setdefault(path.stem, path)
    return found


# CLI: python -m evaluate.ground_truth SRC [--out DST] [--source-dir DIR]
def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evaluate.ground_truth",
        description="Convert loose .md/.txt/.docx ground truth into <doc_id>.json + <doc_id>.md.",
    )
    parser.add_argument("source", type=Path, help="directory of loose ground-truth files")
    parser.add_argument("--out", type=Path, help="dataset directory to write (default: source)")
    parser.add_argument(
        "--source-dir", type=Path, help="directory of original documents, to fill each record's file"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        written = convert(args.source, args.out or args.source, args.source_dir)
    except GroundTruthError as e:
        logger.error("conversion failed: %s", e)
        return 1

    logger.info("wrote %d record(s) under %s", len(written), args.out or args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
