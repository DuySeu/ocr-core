"""Stage 4 text scoring: WER and CER over matched elements.

Aggregation is corpus-level — total edit distance over total gold length — not
the mean of per-element rates. Mean-of-rates gives a three-character page number
with one bad character the same weight as a two-thousand-character paragraph,
which is the most common way a reported CER ends up wrong.

Gold elements that stage 3 never found are not here at all: they were counted in
layout recall and are deliberately outside this denominator, so these numbers
measure recognition alone. They are conditional on what stage 3 found and must
be read next to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz.distance import Levenshtein

from .. import normalize
from ..matching import MatchResult

# The eight DocLayNet classes whose content is prose. Excludes table, picture, formula.
TEXT_CATEGORIES = frozenset(
    {
        "caption",
        "footnote",
        "list-item",
        "page-footer",
        "page-header",
        "section-header",
        "text",
        "title",
    }
)


@dataclass(frozen=True)
class TextScore:
    """Recognition error over a set of text pairs. Lower is better."""

    n_elements: int
    n_chars: int  # gold characters, the CER denominator
    n_empty_gold: int  # pairs excluded because gold text was empty
    cer: float | None
    cer_tone_blind: float | None
    wer: float | None


# Score matched text elements corpus-level under both normalization ladders.
def score_text(results: list[MatchResult]) -> TextScore:
    return score_pairs(
        [
            (match.predicted.text or "", match.gold.text or "")
            for result in results
            for match in result.matches
            if match.gold.category in TEXT_CATEGORIES
        ]
    )


# Score one predicted document against one ground-truth document as flat text.
def score_plain_text(predicted: str, gold: str) -> TextScore:
    return score_pairs([(predicted, gold)])


# Accumulate edit distances and gold lengths across pairs under both ladders.
def score_pairs(pairs: list[tuple[str, str]]) -> TextScore:
    char_errors = 0
    char_total = 0
    tone_blind_errors = 0
    tone_blind_total = 0
    word_errors = 0
    word_total = 0
    scored = 0
    empty_gold = 0

    for raw_predicted, raw_gold in pairs:
        strict_predicted = normalize.strict(raw_predicted)
        strict_gold = normalize.strict(raw_gold)

        # An empty gold string contributes no denominator, so it cannot be scored
        if not strict_gold:
            empty_gold += 1
            continue

        scored += 1
        char_errors += Levenshtein.distance(strict_predicted, strict_gold)
        char_total += len(strict_gold)

        blind_predicted = normalize.tone_blind(raw_predicted)
        blind_gold = normalize.tone_blind(raw_gold)
        tone_blind_errors += Levenshtein.distance(blind_predicted, blind_gold)
        tone_blind_total += len(blind_gold)

        gold_words = strict_gold.split(" ")
        word_errors += Levenshtein.distance(strict_predicted.split(" "), gold_words)
        word_total += len(gold_words)

    return TextScore(
        n_elements=scored,
        n_chars=char_total,
        n_empty_gold=empty_gold,
        cer=char_errors / char_total if char_total else None,
        cer_tone_blind=tone_blind_errors / tone_blind_total if tone_blind_total else None,
        wer=word_errors / word_total if word_total else None,
    )
