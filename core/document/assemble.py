"""Stage 5, first step: RecognizedBox -> Element, canonical geometry assigned.

The one place bbox/polygon convert from the deskew frame to the canonical
frame (§4.5): detectors and recognizers all ran on the deskewed image, but an
Element's geometry has to be comparable across pages that deskewed by
different angles, and `TextLine`s get the identical treatment starting from
their own deskew-frame bbox.
"""

from __future__ import annotations

from dataclasses import replace

from .model import Element, TableContent, TextContent, TextLine, element_id, render_mode
from ..geometry import PageGeometry, bounding_box, corners, to_canonical


# Turn one page's recognized boxes into Elements: canonical geometry, stable
# per-page ids, reading_order left at -1 (assigned at document scope, §4.1).
def assemble_page(recognized: list, geom: PageGeometry) -> list[Element]:
    ordered = sorted(recognized, key=lambda box: (box.bbox[1], box.bbox[0]))
    elements = []
    for index, box in enumerate(ordered):
        polygon = to_canonical(corners(box.bbox), geom)
        elements.append(
            Element(
                id=element_id(geom.page, index),
                page=geom.page,
                category=box.category,
                bbox=bounding_box(polygon),
                reading_order=-1,
                render=render_mode(box.category, is_linked_caption=False, continues_from=None),
                polygon=polygon,
                layout_score=box.layout_score,
                content=_to_canonical_content(box.content, geom),
                logprob=box.logprob,
                rec_score=box.rec_score,
                flags=list(box.flags),
            )
        )
    return elements


def _to_canonical_content(content, geom: PageGeometry):
    if isinstance(content, TextContent):
        return TextContent(
            text=content.text, lines=[_to_canonical_line(line, geom) for line in content.lines]
        )
    if isinstance(content, TableContent):
        canonical_boxes = [
            bounding_box(to_canonical(corners(box), geom)) for box in content.cell_boxes
        ]
        return replace(content, cell_boxes=canonical_boxes)
    return content


def _to_canonical_line(line: TextLine, geom: PageGeometry) -> TextLine:
    polygon = to_canonical(corners(line.bbox), geom)
    return TextLine(
        text=line.text,
        text_ocr=line.text_ocr,
        polygon=polygon,
        bbox=bounding_box(polygon),
        confidence=line.confidence,
    )
