import pytest

from evaluate.loader import EvalElement
from evaluate.matching import Match, MatchResult
from evaluate.metrics.table import (
    TableError,
    pair_tables,
    parse_table,
    score_table_pairs,
    score_tables,
    teds,
)

BOX = (0.0, 0.0, 0.10, 0.10)

GOLD_HTML = (
    "<table><thead><tr><th>Tên</th><th>Số</th></tr></thead>"
    "<tbody><tr><td>An</td><td>10</td></tr></tbody></table>"
)
SAME_STRUCTURE = "<table><tr><td>Tên</td><td>Số</td></tr><tr><td>An</td><td>10</td></tr></table>"
ONE_CELL_WRONG = "<table><tr><td>Tên</td><td>Số</td></tr><tr><td>Ann</td><td>10</td></tr></table>"
MISSING_CELL = "<table><tr><td>Tên</td><td>Số</td></tr><tr><td>An</td></tr></table>"

# The real pair whose APTED distance (16.6549) exceeds its node count (16), taken
# verbatim from ground_truth/lpbank/1202.PGV.2026(1).md table 0 and the predicted
# table 1 of the same stem. Every attempt at a smaller synthetic pair stayed
# non-negative, so the case that produced the bug is the case pinned here.
COST_EXCEEDS_NODE_COUNT_GOLD = """<table>
<tr><th>STT</th><th>Người ký</th><th>Đơn vị</th><th>Thời gian ký</th><th>Ý kiến</th><th>Kiểm tra chữ ký</th></tr>
<tr>
<td>1</td>
<td>VŨ QUỐC KHÁNH</td>
<td>Tổng Giám Đốc - Ban Điều hành - Hội sở - Hội sở chính LPB</td>
<td>15/06/2026 08:45:07</td>
<td></td>
<td>15/06/2026 14:00:58 Chữ ký số hợp lệ</td>
</tr>
</table>"""

COST_EXCEEDS_NODE_COUNT_PREDICTED = (
    '<table><thead><tr><th>Tên văn bản</th><th>Số hiệu</th><th>Ngày ban hành</th></tr></thead>'
    "<tbody><tr><td>Luật các Tổ chức tín dụng</td><td>32/2024/QH15</td><td>18/01/2024</td></tr>"
    '<tr><td rowspan="2">Thông tư quy định về hệ thống kiểm soát nội bộ của ngân hàng '
    "thương mại, chi nhánh ngân hàng nước ngoài</td><td>13/2018/TT-NHNN</td>"
    "<td>18/05/2018<br/>(hiệu lực đến 30/06/2026)</td></tr>"
    "<tr><td>83/2025/TT-NHNN</td><td>31/12/2025<br/>(hiệu lực từ 01/07/2026)</td></tr>"
    "</tbody></table>"
)


# Build one matched table pair carrying the two HTML strings.
def pair(predicted_html, gold_html, element_id=1):
    def side(offset, html):
        return EvalElement(
            id=element_id + offset, page=1, category="table", bbox=BOX, text=None, html=html
        )

    return Match(predicted=side(100, predicted_html), gold=side(0, gold_html), iou=1.0)


# Wrap matches into a single page result with nothing unmatched.
def page(*matches):
    return MatchResult(page=1, matches=list(matches), false_positives=[], false_negatives=[])


def test_th_and_tbody_wrappers_do_not_count_as_structural_differences():
    assert teds(parse_table(SAME_STRUCTURE), parse_table(GOLD_HTML)) == pytest.approx(1.0)


def test_teds_is_never_negative():
    predicted = parse_table(COST_EXCEEDS_NODE_COUNT_PREDICTED)
    gold = parse_table(COST_EXCEEDS_NODE_COUNT_GOLD)

    assert teds(predicted, gold) == 0.0
    assert teds(predicted, gold, structure_only=True) >= 0.0


def test_a_misread_cell_lowers_teds_but_leaves_the_structure_score_perfect():
    score = score_tables([page(pair(ONE_CELL_WRONG, GOLD_HTML))])

    assert score.teds < 1.0
    assert score.teds_struct == pytest.approx(1.0)


def test_a_missing_cell_lowers_both_scores():
    score = score_tables([page(pair(MISSING_CELL, GOLD_HTML))])

    assert score.teds < 1.0
    assert score.teds_struct < 1.0


def test_a_differing_colspan_is_a_structural_error():
    spanned = '<table><tr><td colspan="2">Tên</td></tr><tr><td>An</td><td>10</td></tr></table>'

    assert teds(parse_table(spanned), parse_table(GOLD_HTML), structure_only=True) < 1.0


@pytest.mark.parametrize("markup", ["", "   ", "not markup at all", "<p>no table here</p>"])
def test_unusable_predicted_html_scores_zero_and_is_named(markup):
    score = score_tables([page(pair(markup, GOLD_HTML))])

    assert score.teds == 0.0
    assert score.n_tables == 1
    assert score.unparseable_ids == [101]


def test_a_recognizer_that_produced_nothing_is_scored_not_dropped():
    score = score_tables([page(pair(None, GOLD_HTML))])

    assert score.n_tables == 1
    assert score.n_unparseable == 1


def test_broken_ground_truth_raises_instead_of_blaming_the_model():
    with pytest.raises(TableError, match="unparseable html"):
        score_tables([page(pair(SAME_STRUCTURE, "<p>not a table</p>"))])


def test_tables_are_averaged_per_table_with_the_count_reported():
    score = score_tables(
        [page(pair(SAME_STRUCTURE, GOLD_HTML, 1), pair(ONE_CELL_WRONG, GOLD_HTML, 2))]
    )

    assert score.n_tables == 2
    assert 0.0 < score.teds < 1.0


def test_no_tables_reports_none_rather_than_a_perfect_score():
    assert score_tables([]).teds is None


# ---------- document-level pairing ----------


# Build a table tree from row tuples, so shape and text are readable at the call site.
def tree(*rows):
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return parse_table(f"<table>{body}</table>")


def test_pairs_two_identical_tables_with_teds_struct_one():
    pairs, note = pair_tables([tree(("a", "b"))], [tree(("a", "b"))], 0.5)

    assert note is None
    assert len(pairs) == 1
    assert pairs[0].teds_struct == pytest.approx(1.0)
    assert pairs[0].teds == pytest.approx(1.0)


def test_leaves_both_unmatched_when_no_pair_clears_the_floor():
    pairs, _ = pair_tables([tree(("a",))], [tree(("x", "y"), ("z", "w"))], 0.95)

    assert pairs == []


def test_accepts_a_pair_scoring_exactly_the_floor():
    predicted, gold = [tree(("a",), ("b",))], [tree(("a",), ("b",), ("c",), ("d",))]
    exact = pair_tables(predicted, gold, 0.0)[0][0].teds_struct

    assert pair_tables(predicted, gold, exact)[0] != []


def test_pairs_greedily_from_the_highest_score_down():
    # Predicted 1 matches gold 0 exactly; predicted 0 only approximately
    predicted = [tree(("a", "b"), ("c", "d")), tree(("x", "y"))]
    pairs, _ = pair_tables(predicted, [tree(("x", "y"))], 0.5)

    assert [(p.predicted_index, p.gold_index) for p in pairs] == [(1, 0)]


def test_uses_full_teds_to_break_a_tie_between_equal_structure_scores():
    # Same shape everywhere, so TEDS-Struct is 1.0 for all four candidates
    predicted = [tree(("aa", "bb")), tree(("xx", "yy"))]
    gold = [tree(("xx", "yy")), tree(("aa", "bb"))]

    pairs, _ = pair_tables(predicted, gold, 0.5)

    assert all(p.teds_struct == pytest.approx(1.0) for p in pairs)
    assert sorted((p.predicted_index, p.gold_index) for p in pairs) == [(0, 1), (1, 0)]


def test_breaks_a_remaining_tie_deterministically_by_index():
    identical = [tree(("a",)), tree(("a",))]

    first = pair_tables(identical, [tree(("a",)), tree(("a",))], 0.5)[0]
    second = pair_tables(identical, [tree(("a",)), tree(("a",))], 0.5)[0]

    assert [(p.predicted_index, p.gold_index) for p in first] == [(0, 0), (1, 1)]
    assert [(p.predicted_index, p.gold_index) for p in second] == [(0, 0), (1, 1)]


def test_reports_a_pair_that_clears_the_struct_floor_but_scores_zero_on_full_teds():
    predicted = [parse_table(COST_EXCEEDS_NODE_COUNT_PREDICTED)]
    gold = [parse_table(COST_EXCEEDS_NODE_COUNT_GOLD)]

    pairs, _ = pair_tables(predicted, gold, 0.5)

    assert len(pairs) == 1
    assert pairs[0].teds_struct >= 0.5
    assert pairs[0].teds == 0.0


def test_pairs_three_predictions_against_one_gold_and_leaves_two_unmatched():
    predicted = [tree(("a", "b")), tree(("a", "b")), tree(("a", "b"))]

    score = score_table_pairs(*_scored(predicted, [tree(("a", "b"))]))

    assert score.n_matched == 1
    assert score.n_pred == 3
    assert score.n_gold == 1
    assert score.table_recall == pytest.approx(1.0)


def test_table_recall_is_matched_over_gold():
    gold = [tree(("a", "b")), tree(("x", "y", "z"), ("1", "2", "3"))]

    score = score_table_pairs(*_scored([tree(("a", "b"))], gold))

    assert score.table_recall == pytest.approx(0.5)


def test_table_recall_is_none_when_gold_has_no_tables():
    score = score_table_pairs(*_scored([tree(("a",))], []))

    assert score.table_recall is None
    assert score.n_pred == 1


def test_table_recall_is_zero_when_gold_has_tables_and_the_engine_found_none():
    score = score_table_pairs(*_scored([], [tree(("a",))]))

    assert score.table_recall == 0.0
    assert score.teds is None


def test_table_recall_is_none_rather_than_zero_when_pairing_was_skipped_by_the_cap():
    score = score_table_pairs([], [tree(("a",))], [tree(("a",))], "pairing skipped: too big")

    assert score.table_recall is None
    assert score.note.startswith("pairing skipped")


def test_scores_none_rather_than_zero_when_nothing_matched():
    score = score_table_pairs(*_scored([tree(("a",))], [tree(("x", "y"), ("z", "w"))], 0.95))

    assert score.teds is None
    assert score.teds_struct is None


def test_returns_a_note_and_no_pairs_when_the_pair_count_exceeds_the_cap():
    many = [tree(("a",))] * 60

    pairs, note = pair_tables(many, many, 0.5)

    assert pairs == []
    assert "exceeds the 2000-candidate cap" in note


# Pair two table lists and lay the result out as score_table_pairs takes it.
# style: keep - called from six tests in this file.
def _scored(predicted, gold, threshold=0.5):  # style: keep
    pairs, note = pair_tables(predicted, gold, threshold)
    return pairs, predicted, gold, note
