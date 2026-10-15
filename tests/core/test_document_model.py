import pytest

from core.document.model import (
    DOCLAYNET_CLASSES,
    ELEMENTS_PER_PAGE,
    FLAGS,
    RENDER_MODES,
    Document,
    DocumentError,
    Element,
    FigureContent,
    FormulaContent,
    TableContent,
    TextContent,
    TextLine,
    element_id,
    render_mode,
)


def test_doclaynet_has_the_eleven_classes_coco_categories_are_built_from():
    assert len(DOCLAYNET_CLASSES) == 11
    assert set(DOCLAYNET_CLASSES) == {
        "caption",
        "footnote",
        "formula",
        "list-item",
        "page-footer",
        "page-header",
        "picture",
        "section-header",
        "table",
        "text",
        "title",
    }


def test_flags_distinguishes_a_failure_from_a_switched_off_provider():
    assert "recognize_failed" in FLAGS
    assert "provider_disabled" in FLAGS


def test_render_modes_are_the_three_the_markdown_serializer_branches_on():
    assert RENDER_MODES == ("flow", "aside", "inlined")


def test_element_id_starts_a_page_at_ten_thousand_times_the_page_number():
    assert element_id(1, 0) == 10_000
    assert element_id(1, 7) == 10_007
    assert element_id(42, 0) == 420_000


def test_element_ids_never_collide_across_pages():
    page_two = {element_id(2, i) for i in range(ELEMENTS_PER_PAGE)}
    page_three = {element_id(3, i) for i in range(ELEMENTS_PER_PAGE)}

    assert page_two.isdisjoint(page_three)


def test_no_element_id_can_be_mistaken_for_the_none_sentinel():
    assert element_id(1, 0) > 0


def test_element_id_refuses_to_overflow_a_page_instead_of_colliding():
    with pytest.raises(DocumentError, match="ids would collide"):
        element_id(3, ELEMENTS_PER_PAGE)


def test_a_linked_caption_is_rendered_inside_its_parent():
    assert render_mode("caption", is_linked_caption=True, continues_from=None) == "inlined"


def test_a_table_continuation_is_rendered_inside_the_head_of_its_chain():
    assert render_mode("table", is_linked_caption=False, continues_from=10_005) == "inlined"


@pytest.mark.parametrize("category", ["page-header", "page-footer", "footnote"])
def test_headers_footers_and_footnotes_leave_the_main_flow(category):
    assert render_mode(category, is_linked_caption=False, continues_from=None) == "aside"


@pytest.mark.parametrize("category", ["text", "title", "table", "picture", "formula", "caption"])
def test_everything_else_including_an_unlinked_caption_stays_in_the_flow(category):
    assert render_mode(category, is_linked_caption=False, continues_from=None) == "flow"


def test_render_mode_only_ever_returns_a_known_mode():
    combinations = [
        render_mode(category, linked, continues)
        for category in DOCLAYNET_CLASSES
        for linked in (True, False)
        for continues in (None, 10_001)
    ]

    assert set(combinations) <= set(RENDER_MODES)


def test_an_element_defaults_to_the_flow_with_no_uncertainty_signal():
    element = Element(id=10_000, page=1, category="text", bbox=(0, 0, 10, 10), reading_order=0)

    assert element.render == "flow"
    assert element.logprob is None
    assert element.rec_score is None
    assert element.flags == []


def test_two_elements_do_not_share_one_flags_list():
    first = Element(10_000, 1, "text", (0, 0, 1, 1), 0)
    second = Element(10_001, 1, "text", (0, 0, 1, 1), 1)

    first.flags.append("invalid_html")

    assert second.flags == []


def test_two_documents_do_not_share_one_elements_list():
    first = Document("a.pdf", "sha-a", "v1")
    second = Document("b.pdf", "sha-b", "v1")

    first.elements.append(Element(10_000, 1, "text", (0, 0, 1, 1), 0))

    assert second.elements == []


def test_every_content_type_carries_the_format_its_label_promises():
    assert TextContent("xin chào").text == "xin chào"
    assert TableContent("<table></table>", 2, 3, []).html.startswith("<table")
    assert FormulaContent(r"\frac{a}{b}").latex == r"\frac{a}{b}"
    assert FigureContent("images/p0001_abc.webp").path.endswith(".webp")


def test_table_content_keeps_cell_boxes_alongside_the_html():
    table = TableContent("<table><tr><td>a</td></tr></table>", 1, 1, [(10, 20, 30, 40)])

    assert table.cell_boxes == [(10, 20, 30, 40)]
    assert (table.n_rows, table.n_cols) == (1, 1)


def test_builds_text_content_with_one_positional_argument():
    # Locks the default_factory on `lines` (§4.4) - a required field would turn
    # this and 13 other call sites in tests/ red.
    content = TextContent("xin chào")

    assert content.text == "xin chào"
    assert content.lines == []


def test_two_text_contents_do_not_share_one_lines_list():
    first = TextContent("a")
    second = TextContent("b")

    first.lines.append(
        TextLine(text="x", text_ocr="x", polygon=[(0, 0)], bbox=(0, 0, 1, 1), confidence=None)
    )

    assert second.lines == []


def test_a_text_line_keeps_the_reviewer_edit_separate_from_the_ocr_original():
    line = TextLine(text="hòa", text_ocr="hoà", polygon=[(0, 0)], bbox=(0, 0, 1, 1), confidence=0.5)

    assert line.text == "hòa"
    assert line.text_ocr == "hoà"
