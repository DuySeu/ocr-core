"""Serialize a Document to COCO, extended with the fields COCO has no room for.

COCO is an object-detection format: it carries boxes, not text, HTML, LaTeX or
uncertainty. Those go in custom fields on each annotation, and `info.description`
says so, so a strict COCO reader is not misled.

`score` keeps its COCO meaning — the detector's 0..1 confidence. Recognition
uncertainty is a differently named field precisely because its scale differs,
and an element with neither signal emits neither field rather than a zero.
"""

from __future__ import annotations

from ..document.model import (
    DOCLAYNET_CLASSES,
    Document,
    Element,
    FigureContent,
    FormulaContent,
    TableContent,
    TextContent,
)

SCHEMA_NOTE = (
    "DocLayNet 11-class document layout. Extended beyond standard COCO: "
    "annotations carry text/html/latex/image_path, reading_order, render, flags, "
    "caption_id and continues_from. 'score' is the layout detector's 0-1 confidence; "
    "recognition uncertainty is 'rec_score' (0-1) or 'logprob' (log scale, different "
    "units) and both are absent when the provider reported neither. "
    "images[].file_name is an identifier of the form '<source>#page=<N>', not a file "
    "on disk: page renders are not persisted."
)
CATEGORY_IDS = {name: index for index, name in enumerate(DOCLAYNET_CLASSES, 1)}


# Build the COCO dict for a document.
def to_coco(doc: Document) -> dict:
    source_name = doc.source.rsplit("/", 1)[-1]
    return {
        "info": {
            "description": SCHEMA_NOTE,
            "source": doc.source,
            "doc_sha256": doc.doc_sha256,
            "pipeline_version": doc.pipeline_version,
            "page_errors": [
                {"page": e.page, "stage": e.stage, "message": e.message} for e in doc.errors
            ],
        },
        "images": [
            {
                "id": page.page,
                "width": page.width_px,
                "height": page.height_px,
                "file_name": f"{source_name}#page={page.page}",
                "page_geometry": {
                    "dpi": page.dpi,
                    "rotation_applied": page.rotation_applied,
                    "deskew_angle": page.deskew_angle,
                    "pdf_width_pt": page.pdf_width_pt,
                    "pdf_height_pt": page.pdf_height_pt,
                },
            }
            for page in doc.pages
        ],
        "categories": [
            {"id": index, "name": name, "supercategory": "layout"}
            for name, index in CATEGORY_IDS.items()
        ],
        "annotations": [_annotation(e) for e in doc.elements],
    }


# Turn one element into one annotation; every element gets one, including inlined.
# style: keep — 47 lines that would push to_coco well past 60, sharing no locals with it.
def _annotation(element: Element) -> dict:
    x, y, w, h = element.bbox
    annotation = {
        "id": element.id,
        "image_id": element.page,
        "category_id": CATEGORY_IDS[element.category],
        "bbox": [x, y, w, h],
        "area": w * h,
        "iscrowd": 0,
        "reading_order": element.reading_order,
        "render": element.render,
    }

    # Optional fields are omitted rather than zeroed, so absence stays readable
    if element.polygon is not None:
        annotation["segmentation"] = [[c for point in element.polygon for c in point]]
    if element.layout_score is not None:
        annotation["score"] = element.layout_score
    if element.logprob is not None:
        annotation["logprob"] = {
            "sum": element.logprob.sum,
            "mean": element.logprob.mean,
            "min": element.logprob.min,
            "n_tokens": element.logprob.n_tokens,
        }
    elif element.rec_score is not None:
        annotation["rec_score"] = element.rec_score
    if element.caption_id is not None:
        annotation["caption_id"] = element.caption_id
    if element.continues_from is not None:
        annotation["continues_from"] = element.continues_from
    if element.flags:
        annotation["flags"] = list(element.flags)

    content = element.content
    if isinstance(content, TextContent):
        annotation["text"] = content.text
    elif isinstance(content, TableContent):
        annotation["html"] = content.html
        annotation["n_rows"] = content.n_rows
        annotation["n_cols"] = content.n_cols
        annotation["cell_boxes"] = [list(box) for box in content.cell_boxes]
    elif isinstance(content, FormulaContent):
        annotation["latex"] = content.latex
    elif isinstance(content, FigureContent):
        annotation["image_path"] = content.path

    return annotation
