from evaluate.loader import EvalElement
from evaluate.matching import match_page
from evaluate.metrics.layout import MICRO_LABEL, score_layout

BOX = (0.0, 0.0, 0.10, 0.10)
ELSEWHERE = (0.5, 0.5, 0.10, 0.10)


# Build a bare element carrying only what layout scoring reads.
def element(element_id, bbox, category="text"):
    return EvalElement(id=element_id, page=1, category=category, bbox=bbox, text=None, html=None)


# Index score rows by category name for assertion.
def by_category(scores):
    return {s.category: s for s in scores}


def test_a_missed_box_lowers_recall_without_dragging_down_mean_iou():
    gold = [element(1, BOX), element(2, ELSEWHERE)]
    predicted = [element(101, BOX)]

    scores = by_category(score_layout([match_page(1, predicted, gold, 0.5)]))

    assert scores["text"].recall == 0.5
    assert scores["text"].precision == 1.0
    assert scores["text"].mean_iou == 1.0


def test_a_category_absent_from_both_sides_is_omitted_entirely():
    scores = by_category(score_layout([match_page(1, [element(101, BOX)], [element(1, BOX)], 0.5)]))

    assert "formula" not in scores
    assert "table" not in scores


def test_a_category_the_detector_invented_reports_na_recall_not_zero():
    gold = [element(1, BOX)]
    predicted = [element(101, BOX), element(102, ELSEWHERE, category="formula")]

    scores = by_category(score_layout([match_page(1, predicted, gold, 0.5)]))

    # No formula exists in gold, so recall is undefined rather than zero
    assert scores["formula"].recall is None
    assert scores["formula"].precision == 0.0
    assert scores["formula"].f1 is None


def test_a_total_miss_reports_f1_zero_not_na():
    gold = [element(1, BOX, category="picture")]
    predicted = [element(101, ELSEWHERE, category="picture")]

    scores = by_category(score_layout([match_page(1, predicted, gold, 0.5)]))

    # Both sides have a box and none of them paired: measured failure, not unmeasured
    assert scores["picture"].precision == 0.0
    assert scores["picture"].recall == 0.0
    assert scores["picture"].f1 == 0.0
    assert scores["picture"].mean_iou is None


def test_micro_average_pools_counts_across_categories():
    gold = [element(1, BOX), element(2, ELSEWHERE, category="table")]
    predicted = [element(101, BOX), element(102, ELSEWHERE, category="table")]

    scores = by_category(score_layout([match_page(1, predicted, gold, 0.5)]))

    assert scores[MICRO_LABEL].n_gold == 2
    assert scores[MICRO_LABEL].true_positives == 2
    assert scores[MICRO_LABEL].precision == 1.0


def test_no_pages_scored_yields_no_rows_at_all():
    assert score_layout([]) == []
