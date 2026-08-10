import pytest

from evaluate.loader import EvalElement
from evaluate.matching import iou, match_page

GOLD_BOX = (0.0, 0.0, 0.10, 0.10)
OVERLAP_80 = (0.0, 0.0, 0.10, 0.08)
OVERLAP_60 = (0.0, 0.0, 0.10, 0.06)
OVERLAP_40 = (0.0, 0.0, 0.10, 0.04)


# Build a bare element carrying only what matching reads.
def element(element_id, bbox, category="text", page=1):
    return EvalElement(
        id=element_id, page=page, category=category, bbox=bbox, text=None, html=None
    )


def test_iou_of_identical_boxes_is_one():
    assert iou(GOLD_BOX, GOLD_BOX) == pytest.approx(1.0)


def test_iou_of_disjoint_boxes_is_zero():
    assert iou(GOLD_BOX, (0.5, 0.5, 0.1, 0.1)) == 0.0


def test_the_tighter_of_two_overlapping_predictions_wins_and_the_other_is_spurious():
    gold = [element(1, GOLD_BOX)]
    predicted = [element(101, OVERLAP_60), element(102, OVERLAP_80)]

    result = match_page(1, predicted, gold, threshold=0.5)

    assert [m.predicted.id for m in result.matches] == [102]
    assert [e.id for e in result.false_positives] == [101]
    assert result.false_negatives == []


def test_a_pair_below_the_threshold_becomes_a_miss_and_a_spurious_box_not_a_weak_match():
    result = match_page(1, [element(101, OVERLAP_40)], [element(1, GOLD_BOX)], threshold=0.5)

    assert result.matches == []
    assert [e.id for e in result.false_positives] == [101]
    assert [e.id for e in result.false_negatives] == [1]


def test_boxes_of_different_categories_never_pair():
    gold = [element(1, GOLD_BOX, category="caption")]
    predicted = [element(101, GOLD_BOX, category="text")]

    result = match_page(1, predicted, gold, threshold=0.5)

    assert result.matches == []
    assert len(result.false_positives) == len(result.false_negatives) == 1


def test_ties_are_broken_by_id_so_the_same_input_always_matches_the_same_way():
    gold = [element(1, GOLD_BOX), element(2, GOLD_BOX)]
    predicted = [element(102, GOLD_BOX), element(101, GOLD_BOX)]

    first = match_page(1, predicted, gold, threshold=0.5)
    second = match_page(1, list(reversed(predicted)), gold, threshold=0.5)

    assert [(m.predicted.id, m.gold.id) for m in first.matches] == [(101, 1), (102, 2)]
    assert [(m.predicted.id, m.gold.id) for m in second.matches] == [(101, 1), (102, 2)]
