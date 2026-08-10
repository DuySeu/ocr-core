"""Chandra output as the evaluator's shape.

Chandra writes ``<stem>.md``, ``<stem>.html``, ``<stem>_metadata.json`` and the
page images, either flat into the output directory or into a ``<stem>/``
subdirectory depending on how the run was invoked. Both layouts are found by
recursing, and the markdown is what identifies a document either way.

The metadata JSON carries ``page_box`` — the size of each page — and per-page token
and chunk counts. It carries no per-element bounding box, so there is nothing here
for IoU to score and the adapter says so instead of returning an empty page.
"""

from __future__ import annotations

from pathlib import Path

from .base import PredictionDoc

METADATA_SUFFIX = "_metadata.json"

NO_ELEMENT_BOXES_NOTE = (
    "chandra <stem>_metadata.json carries page_box and token counts only, "
    "no per-element bbox: layout metrics cannot be computed from it"
)
NO_METADATA_NOTE = "no <stem>_metadata.json beside the markdown"


# Read every document chandra wrote under an output directory.
def read_documents(output_dir: Path) -> list[PredictionDoc]:
    documents: list[PredictionDoc] = []
    for markdown_path in sorted(output_dir.rglob("*.md")):
        metadata_path = markdown_path.with_name(f"{markdown_path.stem}{METADATA_SUFFIX}")

        documents.append(
            PredictionDoc(
                doc_id=markdown_path.stem,
                markdown_path=markdown_path,
                text=markdown_path.read_text(encoding="utf-8"),
                boxes=None,
                boxes_note=(
                    NO_ELEMENT_BOXES_NOTE if metadata_path.exists() else NO_METADATA_NOTE
                ),
            )
        )

    return documents
