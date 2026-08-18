import pytest

from core.document.assemble import assemble_page
from core.document.model import (
    ELEMENTS_PER_PAGE,
    Document,
    DocumentError,
    Element,
    TableContent,
    TextContent,
)
from core.document.reading_order import assign_reading_order
from core.document.validate import validate_document, validate_page
from core.geometry import IDENTITY_MATRIX, PageGeometry, bounding_box, corners, to_canonical
from core.recognize.base import RecognizedBox


def _geometry(deskew_matrix=IDENTITY_MATRIX):
    return PageGeometry(1, 100, 100, 300, 0, 0.0, deskew_matrix, None, None)


def _box(**kwargs):
    kwargs.setdefault("category", "text")
    kwargs.setdefault("bbox", (0, 0, 10, 10))
    kwargs.setdefault("layout_score", None)
    kwargs.setdefault("content", None)
    kwargs.setdefault("rec_score", None)
    kwargs.setdefault("logprob", None)
    kwargs.setdefault("flags", [])
    return RecognizedBox(**kwargs)


# ---------- assemble_page ----------


def test_converts_layout_box_to_canonical_frame_once():
    geom = _geometry(deskew_matrix=(1.0, 0.0, 10.0, 0.0, 1.0, 5.0))  # pure translation
    box = _box(bbox=(0, 0, 20, 30), content=TextContent("hi"), rec_score=0.9)

    elements = assemble_page([box], geom)

    expected_polygon = to_canonical(corners(box.bbox), geom)
    assert elements[0].polygon == expected_polygon
    assert elements[0].bbox == bounding_box(expected_polygon)


def test_a_text_lines_bbox_is_converted_the_same_way_as_the_element(monkeypatch):
    geom = _geometry(deskew_matrix=(1.0, 0.0, 10.0, 0.0, 1.0, 5.0))
    from core.document.model import TextLine

    line = TextLine(text="hi", text_ocr="hi", polygon=corners((0, 0, 5, 5)), bbox=(0, 0, 5, 5), confidence=0.5)
    box = _box(bbox=(0, 0, 20, 30), content=TextContent(text="hi", lines=[line]))

    elements = assemble_page([box], geom)

    expected_polygon = to_canonical(corners(line.bbox), geom)
    assembled_line = elements[0].content.lines[0]
    assert assembled_line.polygon == expected_polygon
    assert assembled_line.bbox == bounding_box(expected_polygon)
    assert assembled_line.text == "hi" and assembled_line.confidence == 0.5


def test_raises_when_page_exceeds_element_limit():
    geom = _geometry()
    boxes = [_box(bbox=(0, i, 1, 1)) for i in range(ELEMENTS_PER_PAGE + 1)]

    with pytest.raises(DocumentError, match="ids would collide"):
        assemble_page(boxes, geom)


def test_run_page_leaves_reading_order_unset():
    geom = _geometry()
    elements = assemble_page([_box()], geom)

    assert elements[0].reading_order == -1


# ---------- reading_order ----------


def test_assigns_reading_order_column_first_on_two_column_page():
    left_top = Element(id=1, page=1, category="text", bbox=(0, 0, 40, 20), reading_order=-1)
    left_bottom = Element(id=2, page=1, category="text", bbox=(0, 30, 40, 20), reading_order=-1)
    right_top = Element(id=3, page=1, category="text", bbox=(60, 0, 40, 20), reading_order=-1)
    right_bottom = Element(id=4, page=1, category="text", bbox=(60, 30, 40, 20), reading_order=-1)
    doc = Document(
        source="x",
        doc_sha256="a" * 64,
        pipeline_version="v1",
        elements=[right_bottom, left_top, right_top, left_bottom],  # scrambled on purpose
    )

    assign_reading_order(doc)

    order = {e.id: e.reading_order for e in doc.elements}
    assert order[1] < order[2] < order[3] < order[4]


def test_reading_order_is_dense_and_starts_at_zero_across_pages():
    elements = [
        Element(id=1, page=1, category="text", bbox=(0, 0, 10, 10), reading_order=-1),
        Element(id=2, page=2, category="text", bbox=(0, 0, 10, 10), reading_order=-1),
    ]
    doc = Document(source="x", doc_sha256="a" * 64, pipeline_version="v1", elements=elements)

    assign_reading_order(doc)

    assert sorted(e.reading_order for e in doc.elements) == [0, 1]


# ---------- validate ----------


def test_validates_page_without_requiring_reading_order():
    element = Element(
        id=1,
        page=1,
        category="table",
        bbox=(0, 0, 1, 1),
        reading_order=-1,
        content=TableContent("<table><tbody><tr><td>a</td></tr></tbody></table>", 1, 1, []),
    )

    validate_page([element])  # must not raise despite reading_order == -1

    assert element.flags == []


def test_flags_invalid_html_when_table_markup_does_not_parse():
    element = Element(
        id=1,
        page=1,
        category="table",
        bbox=(0, 0, 1, 1),
        reading_order=-1,
        content=TableContent("<table><tr><td>unterminated", 1, 1, []),
    )

    validate_page([element])

    assert "invalid_html" in element.flags


def test_flags_cell_count_mismatch_when_covered_slots_disagree_with_grid():
    html = "<table><tbody><tr><td>a</td></tr></tbody></table>"  # 1 cell, grid says 2x2
    element = Element(id=1, page=1, category="table", bbox=(0, 0, 1, 1), reading_order=-1, content=TableContent(html, 2, 2, []))

    validate_page([element])

    assert "cell_count_mismatch" in element.flags


def test_a_merged_cell_does_not_falsely_trip_cell_count_mismatch():
    html = (
        '<table><tbody><tr><td rowspan="2">a</td><td>b</td></tr><tr><td>c</td></tr></tbody></table>'
    )
    element = Element(id=1, page=1, category="table", bbox=(0, 0, 1, 1), reading_order=-1, content=TableContent(html, 2, 2, []))

    validate_page([element])

    assert "cell_count_mismatch" not in element.flags


def test_raises_when_reading_order_has_duplicates():
    elements = [
        Element(id=1, page=1, category="text", bbox=(0, 0, 1, 1), reading_order=0),
        Element(id=2, page=1, category="text", bbox=(0, 0, 1, 1), reading_order=0),
    ]
    doc = Document(source="x", doc_sha256="a" * 64, pipeline_version="v1", elements=elements)

    with pytest.raises(DocumentError, match="duplicate"):
        validate_document(doc)


def test_raises_when_reading_order_was_never_assigned():
    elements = [Element(id=1, page=1, category="text", bbox=(0, 0, 1, 1), reading_order=-1)]
    doc = Document(source="x", doc_sha256="a" * 64, pipeline_version="v1", elements=elements)

    with pytest.raises(DocumentError, match="-1"):
        validate_document(doc)


def test_raises_when_caption_id_points_at_nothing():
    elements = [
        Element(id=1, page=1, category="text", bbox=(0, 0, 1, 1), reading_order=0, caption_id=999)
    ]
    doc = Document(source="x", doc_sha256="a" * 64, pipeline_version="v1", elements=elements)

    with pytest.raises(DocumentError, match="caption_id"):
        validate_document(doc)
