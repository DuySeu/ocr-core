"""Stage 3 scoring: did the detector find the element, and is the box tight.

``mean_iou`` averages over matched pairs only. A missed box is already paid for
in recall; dragging the IoU mean down with it would charge one failure twice.
The two columns answer different questions and are meant to be read together.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..matching import MatchResult

MICRO_LABEL = "(micro)"


@dataclass(frozen=True)
class CategoryScore:
    """Detection quality for one category, or for all of them micro-averaged.

    ``precision``/``recall``/``f1`` are None when their denominator is zero.
    None means "not applicable" and must not be rendered as 0.0 — averaging a
    fabricated zero drags the headline down with a number nobody measured.
    """

    category: str
    n_gold: int
    n_pred: int
    true_positives: int
    precision: float | None
    recall: float | None
    f1: float | None
    mean_iou: float | None


# Score detection per category across every page, plus a micro-averaged row.
def score_layout(results: list[MatchResult]) -> list[CategoryScore]:
    # Tally hits, misses and spurious boxes per category
    true_positives: dict[str, int] = {}
    gold_totals: dict[str, int] = {}
    pred_totals: dict[str, int] = {}
    iou_sums: dict[str, float] = {}

    for result in results:
        for match in result.matches:
            category = match.gold.category
            true_positives[category] = true_positives.get(category, 0) + 1
            gold_totals[category] = gold_totals.get(category, 0) + 1
            pred_totals[category] = pred_totals.get(category, 0) + 1
            iou_sums[category] = iou_sums.get(category, 0.0) + match.iou
        for element in result.false_negatives:
            gold_totals[element.category] = gold_totals.get(element.category, 0) + 1
        for element in result.false_positives:
            pred_totals[element.category] = pred_totals.get(element.category, 0) + 1

    scores: list[CategoryScore] = []
    for category in sorted(set(gold_totals) | set(pred_totals)):
        hits = true_positives.get(category, 0)
        n_gold = gold_totals.get(category, 0)
        n_pred = pred_totals.get(category, 0)

        # A category absent from both sides has nothing to report
        if n_gold == 0 and n_pred == 0:
            continue

        precision = hits / n_pred if n_pred else None
        recall = hits / n_gold if n_gold else None
        # Both defined but zero is a measured total miss, not an unmeasured value
        f1 = None
        if precision is not None and recall is not None:
            denominator = precision + recall
            f1 = 2 * precision * recall / denominator if denominator else 0.0

        scores.append(
            CategoryScore(
                category=category,
                n_gold=n_gold,
                n_pred=n_pred,
                true_positives=hits,
                precision=precision,
                recall=recall,
                f1=f1,
                mean_iou=iou_sums.get(category, 0.0) / hits if hits else None,
            )
        )

    if not scores:
        return scores

    # Micro-average: totals across categories, so common classes dominate
    hits = sum(s.true_positives for s in scores)
    n_gold = sum(s.n_gold for s in scores)
    n_pred = sum(s.n_pred for s in scores)
    precision = hits / n_pred if n_pred else None
    recall = hits / n_gold if n_gold else None
    f1 = None
    if precision is not None and recall is not None:
        denominator = precision + recall
        f1 = 2 * precision * recall / denominator if denominator else 0.0

    scores.append(
        CategoryScore(
            category=MICRO_LABEL,
            n_gold=n_gold,
            n_pred=n_pred,
            true_positives=hits,
            precision=precision,
            recall=recall,
            f1=f1,
            mean_iou=sum(iou_sums.values()) / hits if hits else None,
        )
    )
    return scores
