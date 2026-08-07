import json

import pytest

from core.document.model import (
    DOCLAYNET_CLASSES,
    Document,
    Element,
    FigureContent,
    FormulaContent,
    LogProb,
    PageError,
    TableContent,
    TextContent,
)
from core.geometry import IDENTITY_MATRIX, PageGeometry
from core.serialize import SerializeError, to_coco, to_markdown, write_document

TABLE_HTML = "<table><tbody><tr><td>a</td></tr></tbody></table>"
PART_HTML = "<table><tbody><tr><td>b</td></tr></tbody></table>"


def geometry(page=1, rotation=0):
    return PageGeometry(page, 2550, 3300, 300, rotation, 0.0, IDENTITY_MATRIX, 612.0, 792.0)


def element(id, category="text", order=0, **kwargs):
    kwargs.setdefault("content", TextContent(f"body {id}"))
    return Element(
        id=id,
        page=id // 10_000,
        category=category,
        bbox=(10, 20, 30, 40),
        reading_order=order,
        **kwargs,
    )


def document(elements, pages=None, errors=None):
    return Document(
        source="input/scan.pdf",
        doc_sha256="a" * 64,
        pipeline_version="v1",
        pages=pages if pages is not None else [geometry()],
        elements=elements,
        errors=errors or [],
    )


# ---------- markdown ----------


def test_markdown_orders_blocks_by_reading_order_not_by_list_order():
    doc = document([element(10_002, order=2), element(10_000, order=0)])

    body = to_markdown(doc)

    assert body.index("body 10000") < body.index("body 10002")


def test_every_rendered_block_carries_an_anchor_matching_its_id():
    doc = document([element(10_000, order=0), element(10_001, "title", 1)])

    body = to_markdown(doc)

    assert "<!-- ann:10000 -->" in body
    assert "<!-- ann:10001 -->" in body


def test_anchor_count_equals_the_number_of_non_inlined_elements():
    doc = document(
        [
            element(10_000, "table", 0, content=TableContent(TABLE_HTML, 1, 1, []), caption_id=10_002),
            element(10_001, "footnote", 1, render="aside"),
            element(10_002, "caption", 2, render="inlined", content=TextContent("Bang 1")),
        ]
    )

    body = to_markdown(doc)

    assert body.count("<!-- ann:") == 2


def test_a_linked_caption_appears_once_under_its_table_and_not_in_the_asides():
    doc = document(
        [
            element(10_000, "table", 0, content=TableContent(TABLE_HTML, 1, 1, []), caption_id=10_001),
            element(10_001, "caption", 1, render="inlined", content=TextContent("Bang 1")),
        ]
    )

    body = to_markdown(doc)

    assert body.count("Bang 1") == 1
    assert "ann-aside" not in body


def test_a_linked_caption_becomes_the_alt_text_of_its_picture():
    doc = document(
        [
            element(10_000, "picture", 0, content=FigureContent("images/p0001_ab.webp"), caption_id=10_001),
            element(10_001, "caption", 1, render="inlined", content=TextContent("Hinh 1")),
        ]
    )

    assert "![Hinh 1](images/p0001_ab.webp)" in to_markdown(doc)


def test_an_unlinked_caption_still_renders_as_a_paragraph():
    doc = document([element(10_000, "caption", 0, content=TextContent("Hinh mo coi"))])

    assert "Hinh mo coi" in to_markdown(doc)


def test_a_continued_table_renders_once_with_the_later_rows_spliced_in():
    doc = document(
        [
            element(10_000, "table", 0, content=TableContent(TABLE_HTML, 1, 1, []), flags=["table_continues"]),
            element(20_000, "table", 1, render="inlined", content=TableContent(PART_HTML, 1, 1, []), continues_from=10_000),
        ]
    )

    body = to_markdown(doc)

    assert body.count("<table>") == 1
    assert body.count("<!-- ann:") == 1
    assert "<td>a</td>" in body and "<td>b</td>" in body


def test_a_three_page_table_splices_every_part_in_order():
    doc = document(
        [
            element(10_000, "table", 0, content=TableContent(TABLE_HTML, 1, 1, []), flags=["table_continues"]),
            element(20_000, "table", 1, render="inlined", content=TableContent("<table><tbody><tr><td>b</td></tr></tbody></table>", 1, 1, []), continues_from=10_000),
            element(30_000, "table", 2, render="inlined", content=TableContent("<table><tbody><tr><td>c</td></tr></tbody></table>", 1, 1, []), continues_from=20_000),
        ]
    )

    body = to_markdown(doc)

    assert body.count("<table>") == 1
    assert body.index("<td>b</td>") < body.index("<td>c</td>")


def test_asides_go_after_the_marker_and_inlined_elements_never_do():
    doc = document(
        [
            element(10_000, "text", 0),
            element(10_001, "page-footer", 1, render="aside", content=TextContent("trang 1")),
            element(10_002, "caption", 2, render="inlined", content=TextContent("khong duoc o day")),
        ]
    )

    body = to_markdown(doc)
    marker = body.index("<!-- ann-aside -->")

    assert body.index("trang 1") > marker
    assert "khong duoc o day" not in body


def test_no_aside_marker_appears_when_there_are_no_asides():
    assert "<!-- ann-aside -->" not in to_markdown(document([element(10_000)]))


def test_headings_and_list_items_use_their_markdown_syntax():
    doc = document(
        [
            element(10_000, "title", 0, content=TextContent("Quy dinh")),
            element(10_001, "section-header", 1, content=TextContent("Pham vi")),
            element(10_002, "list-item", 2, content=TextContent("Muc mot")),
        ]
    )

    body = to_markdown(doc)

    assert "# Quy dinh" in body
    assert "## Pham vi" in body
    assert "- Muc mot" in body


def test_a_formula_renders_as_a_display_block():
    doc = document([element(10_000, "formula", 0, content=FormulaContent(r"E = mc^2"))])

    assert "$$\nE = mc^2\n$$" in to_markdown(doc)


def test_a_table_embeds_raw_html_because_gfm_cannot_hold_merged_cells():
    merged = '<table><tbody><tr><td rowspan="2">a</td></tr></tbody></table>'
    doc = document([element(10_000, "table", 0, content=TableContent(merged, 2, 1, []))])

    assert 'rowspan="2"' in to_markdown(doc)


def test_an_element_that_failed_recognition_keeps_its_anchor_and_says_why():
    doc = document([element(10_000, content=None, flags=["recognize_failed"])])

    assert "<!-- ann:10000 recognize_failed -->" in to_markdown(doc)


def test_a_disabled_provider_reads_differently_from_a_failure():
    doc = document([element(10_000, "formula", 0, content=None, flags=["provider_disabled"])])

    assert "<!-- ann:10000 provider_disabled -->" in to_markdown(doc)


def test_markdown_of_an_empty_document_is_not_an_error():
    assert to_markdown(document([])) == "\n"


# ---------- coco ----------


def test_coco_declares_all_eleven_doclaynet_categories():
    names = [c["name"] for c in to_coco(document([]))["categories"]]

    assert names == list(DOCLAYNET_CLASSES)


def test_coco_records_one_image_per_successful_page_keyed_by_real_page_number():
    doc = document([], pages=[geometry(1), geometry(3)])

    images = to_coco(doc)["images"]

    assert [i["id"] for i in images] == [1, 3]


def test_coco_file_name_is_an_identifier_not_a_path_on_disk():
    assert to_coco(document([]))["images"][0]["file_name"] == "scan.pdf#page=1"


def test_coco_image_carries_the_geometry_needed_to_map_back_to_the_pdf():
    page_geometry = to_coco(document([], pages=[geometry(1, rotation=90)]))["images"][0]

    assert page_geometry["page_geometry"]["rotation_applied"] == 90
    assert page_geometry["page_geometry"]["pdf_width_pt"] == 612.0


def test_every_bbox_lands_inside_its_page():
    coco = to_coco(document([element(10_000)]))
    image = coco["images"][0]
    x, y, w, h = coco["annotations"][0]["bbox"]

    assert 0 <= x and x + w <= image["width"]
    assert 0 <= y and y + h <= image["height"]


def test_a_tier_three_element_emits_neither_uncertainty_field():
    annotation = to_coco(document([element(10_000)]))["annotations"][0]

    assert "rec_score" not in annotation
    assert "logprob" not in annotation


def test_a_tier_two_element_emits_rec_score_only():
    annotation = to_coco(document([element(10_000, rec_score=0.87)]))["annotations"][0]

    assert annotation["rec_score"] == 0.87
    assert "logprob" not in annotation


def test_a_tier_one_element_emits_logprob_and_suppresses_rec_score():
    doc = document([element(10_000, logprob=LogProb(-4.0, -0.5, -1.2, 8), rec_score=0.9)])

    annotation = to_coco(doc)["annotations"][0]

    assert annotation["logprob"]["n_tokens"] == 8
    assert "rec_score" not in annotation


def test_layout_score_maps_to_the_standard_coco_score_field():
    assert to_coco(document([element(10_000, layout_score=0.42)]))["annotations"][0]["score"] == 0.42


def test_a_missing_layout_score_omits_the_field_rather_than_writing_zero():
    assert "score" not in to_coco(document([element(10_000)]))["annotations"][0]


def test_a_continued_table_stays_two_annotations_on_two_images():
    doc = document(
        [
            element(10_000, "table", 0, content=TableContent(TABLE_HTML, 1, 1, []), flags=["table_continues"]),
            element(20_000, "table", 1, render="inlined", content=TableContent(PART_HTML, 1, 1, []), continues_from=10_000),
        ],
        pages=[geometry(1), geometry(2)],
    )

    annotations = to_coco(doc)["annotations"]

    assert len(annotations) == 2
    assert [a["image_id"] for a in annotations] == [1, 2]
    assert annotations[1]["continues_from"] == 10_000


def test_an_inlined_element_still_gets_its_own_annotation():
    doc = document([element(10_000, "caption", 0, render="inlined", content=TextContent("Bang 1"))])

    annotations = to_coco(doc)["annotations"]

    assert len(annotations) == 1
    assert annotations[0]["render"] == "inlined"


def test_each_content_type_lands_in_its_own_extended_field():
    doc = document(
        [
            element(10_000, "text", 0, content=TextContent("chu")),
            element(10_001, "table", 1, content=TableContent(TABLE_HTML, 1, 1, [(1, 2, 3, 4)])),
            element(10_002, "formula", 2, content=FormulaContent("x^2")),
            element(10_003, "picture", 3, content=FigureContent("images/a.webp")),
        ]
    )

    text, table, formula, picture = to_coco(doc)["annotations"]

    assert text["text"] == "chu"
    assert table["html"] == TABLE_HTML and table["cell_boxes"] == [[1, 2, 3, 4]]
    assert formula["latex"] == "x^2"
    assert picture["image_path"] == "images/a.webp"


def test_an_element_with_no_content_carries_no_content_field():
    annotation = to_coco(document([element(10_000, content=None, flags=["recognize_failed"])]))[
        "annotations"
    ][0]

    assert not {"text", "html", "latex", "image_path"} & set(annotation)
    assert annotation["flags"] == ["recognize_failed"]


def test_polygon_becomes_a_flat_coco_segmentation_ring():
    doc = document([element(10_000, polygon=[(0.0, 0.0), (10.0, 1.0), (10.0, 5.0), (0.0, 4.0)])])

    assert to_coco(doc)["annotations"][0]["segmentation"] == [[0.0, 0.0, 10.0, 1.0, 10.0, 5.0, 0.0, 4.0]]


def test_info_declares_the_schema_extension_so_readers_are_not_misled():
    info = to_coco(document([]))["info"]

    assert "Extended beyond standard COCO" in info["description"]
    assert info["doc_sha256"] == "a" * 64


def test_a_failed_page_is_reported_in_info_rather_than_vanishing():
    doc = document([], errors=[PageError(4, "layout", "RuntimeError: boom")])

    assert to_coco(doc)["info"]["page_errors"] == [
        {"page": 4, "stage": "layout", "message": "RuntimeError: boom"}
    ]


# ---------- write_document ----------


def test_write_document_names_both_files_after_the_output_directory(tmp_path):
    out = tmp_path / "scan"
    out.mkdir()

    written = write_document(document([element(10_000)]), out, ["markdown", "coco"])

    assert [p.name for p in written] == ["scan.md", "scan.coco.json"]
    assert json.loads((out / "scan.coco.json").read_text())["annotations"][0]["id"] == 10_000


def test_write_document_writes_only_what_was_asked_for(tmp_path):
    out = tmp_path / "scan"
    out.mkdir()

    write_document(document([element(10_000)]), out, ["coco"])

    assert not (out / "scan.md").exists()
    assert (out / "scan.coco.json").exists()


def test_write_document_keeps_vietnamese_diacritics_readable(tmp_path):
    out = tmp_path / "scan"
    out.mkdir()
    doc = document([element(10_000, content=TextContent("Nghị định số 284"))])

    write_document(doc, out, ["markdown", "coco"])

    assert "Nghị định" in (out / "scan.md").read_text(encoding="utf-8")
    assert "Nghị định" in (out / "scan.coco.json").read_text(encoding="utf-8")


def test_write_document_rejects_an_unknown_output_format(tmp_path):
    out = tmp_path / "scan"
    out.mkdir()

    with pytest.raises(SerializeError, match="unknown output"):
        write_document(document([]), out, ["markdown", "pdf"])
