import pytest

from core.document.model import Element, LogProb
from core.qa import gate


def _element(id, rec_score=None, logprob=None):
    return Element(
        id=id, page=3, category="text", bbox=(0, 0, 1, 1), reading_order=0,
        rec_score=rec_score, logprob=logprob,
    )


def test_flags_page_when_any_element_below_threshold():
    elements = [_element(1, rec_score=0.9), _element(2, rec_score=0.5)]

    verdict = gate(elements, threshold=0.75)

    assert verdict.passed is False
    assert verdict.below == [2]
    assert verdict.min_score == 0.5


def test_passes_page_with_only_table_elements():
    elements = [_element(1, rec_score=None, logprob=None)]  # tier 3: no signal at all

    verdict = gate(elements, threshold=0.75)

    assert verdict.passed is True
    assert verdict.min_score is None
    assert verdict.below == []


def test_passes_when_every_signal_clears_the_threshold():
    elements = [_element(1, rec_score=0.9), _element(2, rec_score=0.8)]

    verdict = gate(elements, threshold=0.75)

    assert verdict.passed is True
    assert verdict.min_score == 0.8


def test_logprob_mean_is_the_signal_when_rec_score_is_absent():
    elements = [_element(1, logprob=LogProb(sum=-4.0, mean=0.6, min=-1.2, n_tokens=8))]

    verdict = gate(elements, threshold=0.75)

    assert verdict.passed is False and verdict.below == [1]


def test_verdict_reports_the_page_number_from_its_elements():
    verdict = gate([_element(1, rec_score=0.9)], threshold=0.75)

    assert verdict.page == 3


def test_raises_on_an_empty_element_list():
    with pytest.raises(ValueError):
        gate([], threshold=0.75)
