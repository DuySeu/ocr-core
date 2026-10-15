import pytest

from evaluate.recognition.wer import WerScore, pool_wer, score_wer

MARKED = "Bên vay\n<!-- image -->\ncam kết"


# The seven rows of the image-marker example table in evaluate/README.md.
@pytest.mark.parametrize(
    "predicted,gold,wer,ignored",
    [
        ("Bên vay ![logo](a.png) cam kết", "Bên vay cam kết", 0.0, 0),
        ("Bên vay [hình: Con dấu tròn màu đỏ] cam kết", "Bên vay cam kết", 0.0, 0),
        ("Bên vay\nThe screenshot shows a stamp\ncam kết", "Bên vay cam kết", 1.25, 0),
        ("Bên vay\nThe screenshot shows a stamp\ncam kết", MARKED, 0.0, 5),
        ("Bên vay cam kết", MARKED, 0.0, 0),
        ("Bên vey Con dấu đỏ cam kết", MARKED, 0.25, 3),
        ("Bên vay cam kết Con dấu đỏ", MARKED, 0.5, 3),
    ],
)
def test_readme_image_marker_examples(predicted, gold, wer, ignored):
    score = score_wer(predicted, gold)

    assert score.wer == pytest.approx(wer)
    assert score.ignored == ignored


def test_marker_tokens_are_not_counted_as_gold_words():
    assert score_wer("Bên vay cam kết", MARKED).n_words == 4


def test_an_empty_prediction_scores_one():
    assert score_wer("", "Bên vay cam kết").wer == 1.0


@pytest.mark.parametrize("gold", ["", "   ", "<!-- image -->", "![logo](a.png)"])
def test_a_gold_with_no_words_is_not_scored(gold):
    assert score_wer("Bên vay", gold) is None


def test_image_text_between_long_anchors_is_skipped():
    gold = "một hai ba bốn\n<!-- image -->\nnăm sáu bảy tám"
    predicted = "một hai ba bốn Logo ngân hàng năm sáu bảy tám"

    score = score_wer(predicted, gold)

    assert (score.errors, score.ignored) == (0, 3)


def test_an_error_in_a_gap_without_a_marker_is_still_counted():
    gold = "một hai ba bốn năm sáu\n<!-- image -->\nbảy tám chín"
    predicted = "một hai bà bốn năm sáu Logo bảy tám chín"

    score = score_wer(predicted, gold)

    assert (score.errors, score.ignored) == (1, 1)


def test_a_marker_never_absorbs_a_gold_word():
    # "cam kết" was misread as "Con dấu": two errors whether or not the marker absorbs
    # those words, and the tie goes to the alignment that skips fewer
    score = score_wer("Bên vay Con dấu", MARKED)

    assert (score.errors, score.ignored) == (2, 0)


def test_without_markers_wer_is_plain_word_levenshtein():
    score = score_wer("a b x d", "a b c d e")

    assert (score.errors, score.n_words, score.ignored) == (2, 5, 0)


def test_pooling_sums_errors_and_words_rather_than_averaging_rates():
    pooled = pool_wer([WerScore(errors=1, n_words=2, ignored=0), WerScore(errors=0, n_words=98, ignored=3)])

    assert pooled.wer == pytest.approx(0.01)
    assert pooled.ignored == 3


def test_pooling_nothing_is_none():
    assert pool_wer([]) is None
