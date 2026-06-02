"""OCR engine interface and shared types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from PIL import Image


class EngineError(Exception):
    """Raised when an engine cannot be initialized or run."""


@dataclass
class Word:
    text: str
    bbox: tuple[int, int, int, int]  # x, y, w, h
    confidence: float
    line_key: tuple  # groups words into a line (e.g. block/par/line)


class OCREngine(ABC):
    @abstractmethod
    def recognize_words(self, image: Image.Image, lang: str) -> list[Word]:
        """data mode: words with text, bbox, confidence, line_key."""

    @abstractmethod
    def recognize_text(self, image: Image.Image, lang: str, psm: int | None = None) -> str:
        """markdown mode: prose thuần (psm tùy chọn cho OCR ô bảng)."""
