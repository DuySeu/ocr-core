import unicodedata

import pytest

from evaluate.normalize import strict, tone_blind


@pytest.mark.parametrize(
    "modern,traditional",
    [
        ("hoà bình", "hòa bình"),
        ("thuý", "thúy"),
        ("hoè", "hòe"),
        ("Hoà", "Hòa"),
        ("HOÀ", "HÒA"),
    ],
)
def test_tone_placement_variants_collapse_to_one_spelling(modern, traditional):
    assert strict(modern) == strict(traditional) == traditional


@pytest.mark.parametrize("word", ["quý khách", "Quỳnh", "quỵ ngã"])
def test_qu_glide_keeps_its_tone_on_the_second_vowel(word):
    assert strict(word) == word


@pytest.mark.parametrize(
    "word", ["khoản", "hoạt động", "hoàng hôn", "khoẻn", "thuyền", "chuyển"]
)
def test_closed_syllables_have_only_one_spelling_and_are_left_alone(word):
    # The oa/oe/uy variation exists only in open syllables; a final consonant
    # fixes the tone position, so rewriting here would corrupt correct text
    assert strict(word) == word


def test_decomposed_input_normalizes_to_the_same_string_as_composed():
    composed = "Điều 1. Phạm vi điều chỉnh"

    assert strict(unicodedata.normalize("NFD", composed)) == strict(composed)


def test_anchors_and_markdown_syntax_are_stripped():
    source = "<!-- ann:10001 -->\n## Điều 2\n\n- khoản một\n\n**đậm**"

    assert strict(source) == "Điều 2 khoản một đậm"


def test_images_are_dropped_whole_including_their_alt_text():
    # The alt text is the engine describing a figure; ground truth has no counterpart
    assert strict("![Bảng 1](images/p0003_ab12cd34.webp)") == ""
    assert strict("trước ![con dấu đỏ](a_12_img.webp) sau") == "trước sau"


def test_raw_html_tables_are_reduced_to_their_cell_text():
    assert strict("<table><tr><td>An</td><td>10</td></tr></table>") == "An 10"


def test_inline_tags_close_up_instead_of_splitting_a_word():
    # m<sup>2</sup> is one token; a space here would invent a character error
    assert strict("diện tích 15 m<sup>2</sup> hiện") == "diện tích 15 m2 hiện"
    assert strict("H<sub>2</sub>O") == "H2O"
    assert strict("<b>đậm</b>nối") == "đậmnối"


def test_tone_blind_removes_tones_but_keeps_vowel_quality_marks_and_d():
    # ơ and đ are different letters, not tones, so only the tone may go
    assert tone_blind("đường") == "đương"
    assert tone_blind("phở") == "phơ"
    assert tone_blind("ăn") == "ăn"


def test_tone_blind_collapses_words_differing_only_by_tone():
    assert tone_blind("hòa") == tone_blind("hoa") == "hoa"


def test_tone_blind_still_separates_words_differing_by_a_letter():
    assert tone_blind("đá") != tone_blind("da")
