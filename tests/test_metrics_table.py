import pytest

from evaluate.loader import EvalElement
from evaluate.matching import Match, MatchResult
from evaluate.metrics.table import TableError, parse_table, score_tables, teds

BOX = (0.0, 0.0, 0.10, 0.10)

GOLD_HTML = (
    "<table><thead><tr><th>Tên</th><th>Số</th></tr></thead>"
    "<tbody><tr><td>An</td><td>10</td></tr></tbody></table>"
)
SAME_STRUCTURE = "<table><tr><td>Tên</td><td>Số</td></tr><tr><td>An</td><td>10</td></tr></table>"
ONE_CELL_WRONG = "<table><tr><td>Tên</td><td>Số</td></tr><tr><td>Ann</td><td>10</td></tr></table>"
MISSING_CELL = "<table><tr><td>Tên</td><td>Số</td></tr><tr><td>An</td></tr></table>"


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
