"""JSON <-> Document/PageGeometry/Element, the only owner of the on-disk shape.

JSON does not distinguish a tuple from a list, so every value the model treats
as a tuple (``Element.bbox``, ``TextLine.bbox``, ``PageGeometry.deskew_matrix``,
every point in a ``polygon``/``cell_boxes``) is rebuilt as a tuple on the way
back in - leaving it a list would still pass through ``numpy`` silently and
only fail later at an equality check.

``rec_score``/``logprob`` are omitted together only when both are ``None``
(tier 3, §4.2/§4.6): if either carries a signal, both keys are written, with
the unset one as JSON ``null``.
"""

from __future__ import annotations

from .model import (
    Document,
    DocumentError,
    Element,
    FigureContent,
    FormulaContent,
    LogProb,
    PageError,
    TableContent,
    TextContent,
    TextLine,
)
from ..geometry import PageGeometry

SCHEMA_VERSION = 1


# Serialize one page's geometry and elements.
def page_to_dict(geom: PageGeometry, elements: list[Element]) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "geometry": _geometry_to_dict(geom),
        "elements": [_element_to_dict(e) for e in elements],
    }


# Rebuild one page's geometry and elements from its dict.
def page_from_dict(data: dict) -> tuple[PageGeometry, list[Element]]:
    _check_schema(data)
    geometry = _geometry_from_dict(data["geometry"])
    elements = [_element_from_dict(e) for e in data["elements"]]
    return geometry, elements


# Serialize a whole document (all pages, all elements, all page errors).
def document_to_dict(doc: Document) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "source": doc.source,
        "doc_sha256": doc.doc_sha256,
        "pipeline_version": doc.pipeline_version,
        "pages": [_geometry_to_dict(g) for g in doc.pages],
        "elements": [_element_to_dict(e) for e in doc.elements],
        "errors": [
            {"page": e.page, "stage": e.stage, "message": e.message} for e in doc.errors
        ],
    }


# Rebuild a whole document from its dict.
def document_from_dict(data: dict) -> Document:
    _check_schema(data)
    return Document(
        source=data["source"],
        doc_sha256=data["doc_sha256"],
        pipeline_version=data["pipeline_version"],
        pages=[_geometry_from_dict(g) for g in data["pages"]],
        elements=[_element_from_dict(e) for e in data["elements"]],
        errors=[
            PageError(page=e["page"], stage=e["stage"], message=e["message"])
            for e in data["errors"]
        ],
    )


def _check_schema(data: dict) -> None:
    schema = data.get("schema")
    if schema != SCHEMA_VERSION:
        raise DocumentError(
            f"unsupported schema {schema!r}; this build reads schema {SCHEMA_VERSION}"
        )


def _geometry_to_dict(geom: PageGeometry) -> dict:
    return {
        "page": geom.page,
        "width_px": geom.width_px,
        "height_px": geom.height_px,
        "dpi": geom.dpi,
        "rotation_applied": geom.rotation_applied,
        "deskew_angle": geom.deskew_angle,
        "deskew_matrix": list(geom.deskew_matrix),
        "pdf_width_pt": geom.pdf_width_pt,
        "pdf_height_pt": geom.pdf_height_pt,
    }


def _geometry_from_dict(data: dict) -> PageGeometry:
    return PageGeometry(
        page=data["page"],
        width_px=data["width_px"],
        height_px=data["height_px"],
        dpi=data["dpi"],
        rotation_applied=data["rotation_applied"],
        deskew_angle=data["deskew_angle"],
        deskew_matrix=tuple(data["deskew_matrix"]),
        pdf_width_pt=data["pdf_width_pt"],
        pdf_height_pt=data["pdf_height_pt"],
    ).validate()


def _element_to_dict(element: Element) -> dict:
    out = {
        "id": element.id,
        "page": element.page,
        "category": element.category,
        "bbox": list(element.bbox),
        "polygon": _points_to_list(element.polygon),
        "reading_order": element.reading_order,
        "render": element.render,
        "layout_score": element.layout_score,
        "caption_id": element.caption_id,
        "continues_from": element.continues_from,
        "flags": list(element.flags),
        "content": _content_to_dict(element.content),
    }
    if element.rec_score is not None or element.logprob is not None:
        out["rec_score"] = element.rec_score
        out["logprob"] = _logprob_to_dict(element.logprob)
    return out


def _element_from_dict(data: dict) -> Element:
    return Element(
        id=data["id"],
        page=data["page"],
        category=data["category"],
        bbox=tuple(data["bbox"]),
        polygon=_points_from_list(data.get("polygon")),
        reading_order=data["reading_order"],
        render=data["render"],
        layout_score=data.get("layout_score"),
        content=_content_from_dict(data.get("content")),
        logprob=_logprob_from_dict(data.get("logprob")),
        rec_score=data.get("rec_score"),
        caption_id=data.get("caption_id"),
        continues_from=data.get("continues_from"),
        flags=list(data.get("flags", [])),
    )


def _logprob_to_dict(logprob: LogProb | None) -> dict | None:
    if logprob is None:
        return None
    return {"sum": logprob.sum, "mean": logprob.mean, "min": logprob.min, "n_tokens": logprob.n_tokens}


def _logprob_from_dict(data: dict | None) -> LogProb | None:
    if data is None:
        return None
    return LogProb(sum=data["sum"], mean=data["mean"], min=data["min"], n_tokens=data["n_tokens"])


def _content_to_dict(content) -> dict | None:
    if content is None:
        return None
    if isinstance(content, TextContent):
        return {"kind": "text", "text": content.text, "lines": [_line_to_dict(l) for l in content.lines]}
    if isinstance(content, TableContent):
        return {
            "kind": "table",
            "html": content.html,
            "n_rows": content.n_rows,
            "n_cols": content.n_cols,
            "cell_boxes": [list(box) for box in content.cell_boxes],
        }
    if isinstance(content, FormulaContent):
        return {"kind": "formula", "latex": content.latex}
    if isinstance(content, FigureContent):
        return {"kind": "figure", "path": content.path}
    raise DocumentError(f"unknown content type {type(content).__name__}")


def _content_from_dict(data: dict | None):
    if data is None:
        return None
    kind = data["kind"]
    if kind == "text":
        return TextContent(text=data["text"], lines=[_line_from_dict(l) for l in data["lines"]])
    if kind == "table":
        return TableContent(
            html=data["html"],
            n_rows=data["n_rows"],
            n_cols=data["n_cols"],
            cell_boxes=[tuple(box) for box in data["cell_boxes"]],
        )
    if kind == "formula":
        return FormulaContent(latex=data["latex"])
    if kind == "figure":
        return FigureContent(path=data["path"])
    raise DocumentError(f"unknown content kind {kind!r}")


def _line_to_dict(line: TextLine) -> dict:
    return {
        "text": line.text,
        "text_ocr": line.text_ocr,
        "polygon": _points_to_list(line.polygon),
        "bbox": list(line.bbox),
        "confidence": line.confidence,
    }


def _line_from_dict(data: dict) -> TextLine:
    return TextLine(
        text=data["text"],
        text_ocr=data["text_ocr"],
        polygon=_points_from_list(data["polygon"]),
        bbox=tuple(data["bbox"]),
        confidence=data.get("confidence"),
    )


def _points_to_list(points: list[tuple[float, float]] | None) -> list[list[float]] | None:
    return None if points is None else [list(p) for p in points]


def _points_from_list(data: list[list[float]] | None) -> list[tuple[float, float]] | None:
    return None if data is None else [tuple(p) for p in data]
