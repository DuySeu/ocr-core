"""Default OCR engine backed by Tesseract via pytesseract."""
from __future__ import annotations

import logging

from PIL import Image

from .base import EngineError, OCREngine, Word

logger = logging.getLogger(__name__)


class TesseractEngine(OCREngine):
    def recognize_words(self, image: Image.Image, lang: str) -> list[Word]:
        pytesseract, Output = self._import()
        from pytesseract import TesseractNotFoundError

        try:
            data = pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)
        except TesseractNotFoundError as e:
            raise EngineError(
                "Tesseract binary not found; install it (e.g. `brew install tesseract`)"
            ) from e

        words = []
        for i, text in enumerate(data["text"]):
            if not text.strip() or float(data["conf"][i]) < 0:
                continue
            words.append(
                Word(
                    text=text,
                    bbox=(data["left"][i], data["top"][i], data["width"][i], data["height"][i]),
                    confidence=float(data["conf"][i]),
                    line_key=(data["block_num"][i], data["par_num"][i], data["line_num"][i]),
                )
            )
        logger.debug("tesseract recognized %d word(s) (lang=%s)", len(words), lang)
        return words

    def recognize_text(self, image: Image.Image, lang: str) -> str:
        pytesseract, _ = self._import()
        from pytesseract import TesseractNotFoundError

        try:
            return pytesseract.image_to_string(image, lang=lang)
        except TesseractNotFoundError as e:
            raise EngineError(
                "Tesseract binary not found; install it (e.g. `brew install tesseract`)"
            ) from e

    @staticmethod
    def _import():
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as e:  # pragma: no cover
            raise EngineError("pytesseract not installed") from e
        return pytesseract, Output
