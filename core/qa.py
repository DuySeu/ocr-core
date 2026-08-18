"""Confidence gating: does a page's OCR clear the bar, element by element.

Only elements with a signal are gated (§4.6) - a tier-3 element (no rec_score,
no logprob, e.g. a table recognized through `recognize_text()`) can't fail a
threshold it never reported against, so a table-only page passes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .document.model import Element


@dataclass(frozen=True)
class PageVerdict:
    page: int
    passed: bool
    min_score: float | None  # None when no element on the page carries a signal
    below: list[int]  # Element.id of every element under threshold


# Signal an element reports, on the 0..1 scale, or None if it reports neither.
def _signal(element: Element) -> float | None:
    if element.rec_score is not None:
        return element.rec_score
    if element.logprob is not None:
        return element.logprob.mean
    return None


def gate(elements: list[Element], threshold: float) -> PageVerdict:
    if not elements:
        raise ValueError("gate() needs at least one element to know which page this is")

    signals = [(element.id, _signal(element)) for element in elements]
    scored = [(element_id, signal) for element_id, signal in signals if signal is not None]

    below = [element_id for element_id, signal in scored if signal < threshold]
    min_score = min((signal for _, signal in scored), default=None)

    return PageVerdict(page=elements[0].page, passed=not below, min_score=min_score, below=below)
