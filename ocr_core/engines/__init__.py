"""Pluggable engine registry."""
from __future__ import annotations

from .base import EngineError, OCREngine, Word
from .tesseract import TesseractEngine

_ENGINES = {"tesseract": TesseractEngine}


def get_engine(name: str) -> OCREngine:
    if name not in _ENGINES:
        raise EngineError(f"unknown engine {name!r}; valid: {sorted(_ENGINES)}")
    return _ENGINES[name]()


__all__ = ["EngineError", "OCREngine", "Word", "get_engine"]
