"""The shape every engine adapter produces, and the reader the core engines share.

An adapter answers two questions about one document: what text did the engine
write, and what boxes did it write. When it wrote no boxes the adapter says why in
``boxes_note`` rather than returning an empty list silently — "no boxes" and "boxes
this format cannot express" are different findings and the report prints both.

``tesseract``, ``paddleocr`` and ``easyocr`` all go through ``core/serialize``, so
they share one reader here. Their per-engine modules exist so an engine that later
diverges has a place to diverge in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..loader import CocoDocument, load_coco

# Everything below this marker in a predicted .md is an aside block (page header,
# page footer, footnote) that ground-truth prose does not carry.
ASIDE_MARKER = "<!-- ann-aside -->"

CORE_BOXES_NOTE = "no COCO file beside the markdown: layout metrics need <stem>.coco.json"


@dataclass(frozen=True)
class PredictionDoc:
    """One document an engine produced, normalized for scoring."""

    doc_id: str  # filename stem; what pairs it with a ground-truth file
    markdown_path: Path
    text: str
    boxes: CocoDocument | None
    boxes_note: str | None  # why ``boxes`` is None, when it is


# Read every document a core-pipeline engine wrote under an output directory.
def read_core_documents(output_dir: Path) -> list[PredictionDoc]:
    documents: list[PredictionDoc] = []
    for markdown_path in sorted(output_dir.rglob("*.md")):
        # Aside blocks are gathered below the marker and have no ground-truth counterpart
        text = markdown_path.read_text(encoding="utf-8").split(ASIDE_MARKER, 1)[0]

        coco_path = markdown_path.with_name(f"{markdown_path.stem}.coco.json")
        has_boxes = coco_path.exists()
        documents.append(
            PredictionDoc(
                doc_id=markdown_path.stem,
                markdown_path=markdown_path,
                text=text,
                boxes=load_coco(coco_path) if has_boxes else None,
                boxes_note=None if has_boxes else CORE_BOXES_NOTE,
            )
        )

    return documents
