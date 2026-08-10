import pytest

from evaluate.loader import EvalElement
from evaluate.matching import Match, MatchResult
from evaluate.metrics.text import score_plain_text, score_text

BOX = (0.0, 0.0, 0.10, 0.10)


# Build one matched prediction/gold pair carrying the two texts.
def pair(predicted_text, gold_text, category="text", element_id=1):
    def side(offset, text):
        return EvalElement(
            id=element_id + offset, page=1, category=category, bbox=BOX, text=text, html=None
        )

    return Match(predicted=side(100, predicted_text), gold=side(0, gold_text), iou=1.0)


# Wrap matches into a single page result with nothing unmatched.
def page(*matches):
    return MatchResult(page=1, matches=list(matches), false_positives=[], false_negatives=[])


def test_cer_counts_characters_against_total_gold_length():
    score = score_text([page(pair("abd", "abc"))])

    assert score.cer == pytest.approx(1 / 3)
    assert score.n_chars == 3


def test_wer_counts_whole_word_substitutions():
    score = score_text([page(pair("một hai bốn", "một hai ba"))])

    assert score.wer == pytest.approx(1 / 3)


def test_aggregation_is_corpus_level_not_the_mean_of_per_element_rates():
    short = pair("abd", "abc", element_id=1)  # 1 error over 3 chars
    long = pair("x" * 100, "x" * 100, element_id=2)  # perfect, 100 chars

    score = score_text([page(short, long)])

    # Corpus-level: one error over 103 characters, not the 0.1667 mean of rates
    assert score.cer == pytest.approx(1 / 103)
    assert score.cer != pytest.approx((1 / 3 + 0.0) / 2)


def test_empty_gold_elements_are_excluded_from_the_denominator_and_counted():
    score = score_text([page(pair("gì đó", "", element_id=1), pair("abc", "abc", element_id=2))])

    assert score.n_empty_gold == 1
    assert score.n_elements == 1
    assert score.cer == 0.0


def test_tone_blind_cer_is_lower_when_only_the_tone_marks_are_wrong():
    score = score_text([page(pair("hoa binh", "hòa bình"))])

    assert score.cer > 0
    assert score.cer_tone_blind == 0.0


def test_tone_blind_cer_still_penalizes_a_wrong_letter():
    score = score_text([page(pair("hla", "hoa"))])

    assert score.cer_tone_blind > 0


def test_non_text_categories_are_not_scored_as_text():
    score = score_text([page(pair("<table/>", "<table><tr><td>x</td></tr></table>", "table"))])

    assert score.n_elements == 0
    assert score.cer is None


def test_document_level_scoring_normalizes_both_sides_before_comparing():
    score = score_plain_text("<!-- ann:1 -->\n## Hoà bình\n", "Hòa bình")

    assert score.cer == 0.0
