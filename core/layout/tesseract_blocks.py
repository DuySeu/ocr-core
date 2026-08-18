"""Text-block detector: groups Tesseract's own words by block_num.

Reuses ``engines.tesseract`` rather than calling ``pytesseract`` a second
time, so pytesseract stays the sole property of ``core/engines/``. Only valid
when the recognition engine is Tesseract too - ``Word.line_key`` is
``(block_num, par_num, line_num)`` there and something else entirely on the
other two engines (§4.2).
"""

from __future__ import annotations

from PIL import Image

from .base import LayoutBox, LayoutDetector
from ..engines import get_engine


class TesseractBlockDetector(LayoutDetector):
    def detect(self, image: Image.Image, langs: list[str]) -> list[LayoutBox]:
        words = get_engine("tesseract").recognize_words(image, langs)

        groups: dict[int, list] = {}
        for word in words:
            groups.setdefault(word.line_key[0], []).append(word)

        boxes = []
        for block_num in sorted(groups):
            block_words = groups[block_num]
            x0 = min(w.bbox[0] for w in block_words)
            y0 = min(w.bbox[1] for w in block_words)
            x1 = max(w.bbox[0] + w.bbox[2] for w in block_words)
            y1 = max(w.bbox[1] + w.bbox[3] for w in block_words)
            boxes.append(LayoutBox(category="text", bbox=(x0, y0, x1 - x0, y1 - y0)))
        return boxes
