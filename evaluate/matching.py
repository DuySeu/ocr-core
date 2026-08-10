"""One greedy IoU matching pass, shared by all three metrics.

Matching runs per category, so a predicted `text` box covering a gold `caption`
is a false positive of `text` and a false negative of `caption` — two real
errors for a per-category score, visible by comparing the two rows.

Greedy rather than Hungarian: at a 0.5 threshold two predictions can only both
clear the bar against one gold box if they overlap each other heavily, which is
rare, and taking the higher IoU is the right call when it happens. This is also
what COCO eval does.
"""

from __future__ import annotations

from dataclasses import dataclass

from .loader import EvalElement


@dataclass(frozen=True)
class Match:
    """A predicted element paired with the gold element it covers."""

    predicted: EvalElement
    gold: EvalElement
    iou: float


@dataclass(frozen=True)
class MatchResult:
    """The full assignment for one page: pairs, plus what went unpaired."""

    page: int
    matches: list[Match]
    false_positives: list[EvalElement]  # predictions matching no gold box
    false_negatives: list[EvalElement]  # gold boxes no prediction covered


# Compute intersection-over-union for two relative x/y/w/h boxes.
def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b

    overlap_w = min(ax + aw, bx + bw) - max(ax, bx)
    overlap_h = min(ay + ah, by + bh) - max(ay, by)
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0

    intersection = overlap_w * overlap_h
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


# Pair predictions to gold on one page, greedily and within each category.
def match_page(
    page: int,
    predicted: list[EvalElement],
    gold: list[EvalElement],
    threshold: float,
) -> MatchResult:
    # Score every same-category pair that clears the threshold
    candidates: list[tuple[float, EvalElement, EvalElement]] = []
    for prediction in predicted:
        for gold_element in gold:
            if prediction.category != gold_element.category:
                continue
            score = iou(prediction.bbox, gold_element.bbox)
            if score >= threshold:
                candidates.append((score, prediction, gold_element))

    # Take the tightest pairs first; ids break ties so the result is deterministic
    candidates.sort(key=lambda c: (-c[0], c[1].id, c[2].id))

    matches: list[Match] = []
    taken_predictions: set[int] = set()
    taken_gold: set[int] = set()
    for score, prediction, gold_element in candidates:
        if prediction.id in taken_predictions or gold_element.id in taken_gold:
            continue
        matches.append(Match(predicted=prediction, gold=gold_element, iou=score))
        taken_predictions.add(prediction.id)
        taken_gold.add(gold_element.id)

    return MatchResult(
        page=page,
        matches=matches,
        false_positives=[p for p in predicted if p.id not in taken_predictions],
        false_negatives=[g for g in gold if g.id not in taken_gold],
    )
