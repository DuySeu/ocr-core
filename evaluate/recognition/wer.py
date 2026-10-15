"""Word error rate for the Recognition tier, with image markers as wildcards.

A ``<!-- image -->`` marker in the GT stands for text the engine may read out of a
picture that the GT chose not to transcribe. For WER the marker matches any run of
consecutive predicted words, the empty run included, at cost 0, and every word it
absorbs is counted in ``ignored``. A marker never absorbs a GT word: only predicted
words with no counterpart in the GT can be skipped.

The alignment runs in two passes. A global Levenshtein alignment finds runs of at
least ``ANCHOR_MIN_WORDS`` matching words; runs are cut at every marker, so an anchor
never spans one. Each gap between anchors that holds a marker is then realigned
exactly by dynamic programming. A gap with no marker, and a document with no marker
at all, uses plain Levenshtein, so markers change nothing where there are none.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz.distance import Levenshtein

from . import normalize

# Shorter matches are not anchors, so a word inside an image that happens to equal a
# nearby GT word does not split the image region in two.
ANCHOR_MIN_WORDS = 3


@dataclass(frozen=True)
class WerScore:
    """Word errors over GT words, plus the predicted words image markers skipped."""

    errors: int
    n_words: int  # GT words, markers excluded; the WER denominator
    ignored: int

    @property
    def wer(self) -> float:
        return self.errors / self.n_words


# Score one predicted document against its GT, or None when the GT has no words.
def score_wer(predicted: str, gold: str) -> WerScore | None:
    predicted_words = normalize.strict(predicted).split()
    gold_tokens = normalize.strict(normalize.mark_images(gold)).split()

    # Index of each real GT word within the token stream that still holds the markers
    word_positions = [
        index for index, token in enumerate(gold_tokens) if token != normalize.IMAGE_PLACEHOLDER
    ]
    gold_words = [gold_tokens[index] for index in word_positions]

    # Nothing to divide by: an empty GT, or one holding nothing but markers
    if not gold_words:
        return None

    if len(gold_words) == len(gold_tokens):
        return WerScore(
            errors=Levenshtein.distance(predicted_words, gold_words),
            n_words=len(gold_words),
            ignored=0,
        )

    errors = 0
    ignored = 0
    predicted_start = gold_start = 0
    anchors = _anchors(predicted_words, gold_words, word_positions)
    for anchor_predicted, anchor_gold, length in [*anchors, (len(predicted_words), len(gold_words), 0)]:
        # The gap's GT tokens run from just after the previous anchor to just before this one
        token_start = word_positions[gold_start - 1] + 1 if gold_start else 0
        token_end = word_positions[anchor_gold] if anchor_gold < len(gold_words) else len(gold_tokens)

        gap_errors, gap_ignored = align_with_wildcards(
            predicted_words[predicted_start:anchor_predicted], gold_tokens[token_start:token_end]
        )
        errors += gap_errors
        ignored += gap_ignored
        predicted_start, gold_start = anchor_predicted + length, anchor_gold + length

    return WerScore(errors=errors, n_words=len(gold_words), ignored=ignored)


# Pool documents corpus-level: total errors over total GT words, not a mean of rates.
def pool_wer(scores: Sequence[WerScore]) -> WerScore | None:
    if not scores:
        return None

    return WerScore(
        errors=sum(s.errors for s in scores),
        n_words=sum(s.n_words for s in scores),
        ignored=sum(s.ignored for s in scores),
    )


# Align predicted words to GT tokens, markers as zero-cost wildcards: (errors, ignored).
def align_with_wildcards(predicted: Sequence[str], gold: Sequence[str]) -> tuple[int, int]:
    if normalize.IMAGE_PLACEHOLDER not in gold:
        return Levenshtein.distance(predicted, gold), 0

    # Cost is errors * scale + ignored, so comparing ints compares (errors, ignored)
    # lexicographically: fewest errors first, then fewest skipped words
    scale = len(predicted) + 1

    # ponytail: pure-Python O(n*m) DP; a gap of 10k words on each side takes minutes
    previous = [i * scale for i in range(len(predicted) + 1)]
    for token in gold:
        current = [0] * (len(predicted) + 1)
        if token == normalize.IMAGE_PLACEHOLDER:
            # The wildcard either stops here or absorbs one more predicted word
            current[0] = previous[0]
            for i in range(1, len(predicted) + 1):
                current[i] = min(previous[i], current[i - 1] + 1)
        else:
            current[0] = previous[0] + scale
            for i in range(1, len(predicted) + 1):
                substitution = previous[i - 1] + (0 if predicted[i - 1] == token else scale)
                current[i] = min(substitution, previous[i] + scale, current[i - 1] + scale)
        previous = current

    return divmod(previous[-1], scale)


# Find matching runs of at least ANCHOR_MIN_WORDS words that span no marker.
def _anchors(
    predicted: Sequence[str], gold_words: Sequence[str], word_positions: Sequence[int]
) -> list[tuple[int, int, int]]:
    anchors: list[tuple[int, int, int]] = []
    for op in Levenshtein.opcodes(predicted, gold_words):
        if op.tag != "equal":
            continue

        # Cut the run wherever a marker sits between two consecutive GT words
        run_start = 0
        length = op.src_end - op.src_start
        for offset in range(1, length + 1):
            at_marker = (
                offset < length
                and word_positions[op.dest_start + offset] - word_positions[op.dest_start + offset - 1] > 1
            )
            if offset < length and not at_marker:
                continue
            if offset - run_start >= ANCHOR_MIN_WORDS:
                anchors.append(
                    (op.src_start + run_start, op.dest_start + run_start, offset - run_start)
                )
            run_start = offset

    return anchors
