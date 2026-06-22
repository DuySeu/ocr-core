"""Multi-language OCR engine backed by EasyOCR (opt-in, lazy dependency).

Reads several languages in one pass, e.g. Reader(['vi', 'en']) for invoices
that mix Vietnamese and English.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image

from .base import EngineError, OCREngine, Word

_READERS: dict[tuple, object] = {}  # cache Reader per resolved lang-set
_LANG = {"vie": "vi", "eng": "en"}  # our codes -> EasyOCR codes; else pass-through


class EasyOCREngine(OCREngine):
    def recognize_words(self, image: Image.Image, langs: list[str]) -> list[Word]:
        words = []
        for box, text, score in self._reader(langs).readtext(np.array(image.convert("RGB"))):
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            x, y = min(xs), min(ys)
            words.append(
                Word(
                    text=text,
                    bbox=(x, y, max(xs) - x, max(ys) - y),
                    confidence=float(score) * 100,
                    line_key=(round(y / 10), x),  # sort -> reading order
                )
            )
        return words

    def recognize_text(self, image: Image.Image, langs: list[str], psm: int | None = None) -> str:
        # psm ignored (Tesseract concept); sort detections by y then x.
        items = sorted(
            self._reader(langs).readtext(np.array(image.convert("RGB"))),
            key=lambda it: (it[0][0][1], it[0][0][0]),
        )
        return "\n".join(text for _, text, _ in items)

    @staticmethod
    def _reader(langs: list[str]):
        codes = tuple(_LANG.get(l, l) for l in langs)
        if codes not in _READERS:
            try:
                import easyocr
            except ImportError as e:
                raise EngineError("easyocr not installed: pip install easyocr") from e
            _READERS[codes] = easyocr.Reader(
                list(codes), gpu=bool(os.environ.get("EASYOCR_USE_GPU"))
            )
        return _READERS[codes]
