"""Stage 4 output: still deskew-frame (§4.5) - assemble.py does the one conversion."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..document.model import Content, LogProb


@dataclass(frozen=True)
class RecognizedBox:
    category: str  # "text" | "table"
    bbox: tuple[int, int, int, int]  # deskew frame
    layout_score: float | None
    content: Content | None
    rec_score: float | None
    logprob: LogProb | None
    flags: list[str] = field(default_factory=list)
