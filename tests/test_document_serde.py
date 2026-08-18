import pytest

from core.document.model import (
    DocumentError,
    Element,
    LogProb,
    TableContent,
    TextContent,
    TextLine,
)
from core.document.serde import page_from_dict, page_to_dict
from core.geometry import IDENTITY_MATRIX, PageGeometry


def _geometry():
    return PageGeometry(
        page=7,
        width_px=2480,
        height_px=3508,
        dpi=300,
        rotation_applied=0,
        deskew_angle=-0.4,
        deskew_matrix=(0.9998, -0.0175, 1.2, 0.0175, 0.9998, -0.6),
        pdf_width_pt=595.3,
        pdf_height_pt=841.9,
    )


def test_round_trips_page_through_serde_unchanged():
    line = TextLine(
        text="Kính gửi",
        text_ocr="Kinh gui",
        polygon=[(120.0, 340.3), (1020.0, 334.0), (1020.2, 362.0), (120.2, 368.3)],
        bbox=(120, 334, 901, 35),
        confidence=0.91,
    )
    element = Element(
        id=70_000,
        page=7,
        category="text",
        bbox=(120, 334, 901, 66),
        reading_order=-1,
        polygon=[(120.0, 340.3), (1020.0, 334.0), (1021.0, 394.0), (121.0, 400.3)],
        content=TextContent(text="Kính gửi", lines=[line]),
        rec_score=0.91,
    )
    geom = _geometry()

    data = page_to_dict(geom, [element])
    round_tripped_geom, round_tripped_elements = page_from_dict(data)

    assert round_tripped_geom == geom
    assert round_tripped_elements == [element]
    # every tuple survives as a tuple, not a list - JSON does not distinguish them
    assert isinstance(round_tripped_elements[0].bbox, tuple)
    assert isinstance(round_tripped_geom.deskew_matrix, tuple)
    assert isinstance(round_tripped_elements[0].content.lines[0].bbox, tuple)
    assert all(isinstance(p, tuple) for p in round_tripped_elements[0].polygon)


def test_round_trips_a_table_element_with_logprob():
    element = Element(
        id=1,
        page=1,
        category="table",
        bbox=(0, 0, 10, 10),
        reading_order=2,
        content=TableContent("<table><tbody><tr><td>a</td></tr></tbody></table>", 1, 1, [(1, 2, 3, 4)]),
        logprob=LogProb(sum=-4.0, mean=-0.5, min=-1.2, n_tokens=8),
        caption_id=5,
        continues_from=3,
        flags=["table_continues"],
    )
    geom = _geometry()

    _, (round_tripped,) = page_from_dict(page_to_dict(geom, [element]))

    assert round_tripped == element
    assert isinstance(round_tripped.content.cell_boxes[0], tuple)


def test_omits_rec_score_from_json_when_signal_absent():
    element = Element(id=1, page=1, category="text", bbox=(0, 0, 1, 1), reading_order=0)

    data = page_to_dict(_geometry(), [element])

    assert "rec_score" not in data["elements"][0]
    assert "logprob" not in data["elements"][0]


def test_writes_rec_score_and_a_null_logprob_when_only_rec_score_is_set():
    element = Element(id=1, page=1, category="text", bbox=(0, 0, 1, 1), reading_order=0, rec_score=0.5)

    data = page_to_dict(_geometry(), [element])

    assert data["elements"][0]["rec_score"] == 0.5
    assert data["elements"][0]["logprob"] is None


def test_an_element_with_no_content_round_trips_as_none():
    element = Element(
        id=1, page=1, category="text", bbox=(0, 0, 1, 1), reading_order=0,
        content=None, flags=["recognize_failed"],
    )

    _, (round_tripped,) = page_from_dict(page_to_dict(_geometry(), [element]))

    assert round_tripped.content is None and round_tripped.flags == ["recognize_failed"]


def test_raises_on_unknown_page_schema_version():
    with pytest.raises(DocumentError, match="schema"):
        page_from_dict({"schema": 99, "geometry": {}, "elements": []})
