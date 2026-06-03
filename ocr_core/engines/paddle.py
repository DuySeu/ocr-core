"""Vietnamese-strong OCR engine backed by PaddleOCR (opt-in, lazy dependency).

Supports both PaddleOCR 2.x ([[box, (text, score)], ...]) and 3.x
(OCRResult dict with parallel rec_polys/rec_texts/rec_scores).
"""
from __future__ import annotations

import inspect
import os

import numpy as np
from PIL import Image

from .base import EngineError, OCREngine, Word

_READERS: dict[str, object] = {}  # cache reader per resolved lang code
_LANG = {"vie": "vi", "eng": "en"}  # Tesseract -> Paddle codes; else pass-through


class PaddleOCREngine(OCREngine):
    def recognize_words(self, image: Image.Image, lang: str) -> list[Word]:
        words = []
        for box, text, score in self._ocr(image, lang):
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

    def recognize_text(self, image: Image.Image, lang: str, psm: int | None = None) -> str:
        # psm ignored (Tesseract concept); sort detections by y then x.
        items = sorted(self._ocr(image, lang), key=lambda it: (it[0][0][1], it[0][0][0]))
        return "\n".join(text for _, text, _ in items)

    def _ocr(self, image: Image.Image, lang: str) -> list:
        """Normalize PaddleOCR output to [(box, text, score), ...]."""
        res = self._reader(lang).ocr(np.array(image.convert("RGB")))  # 3ch: Paddle needs HxWx3
        if not res:
            return []
        r0 = res[0]
        if isinstance(r0, dict):  # 3.x OCRResult
            return list(zip(r0["rec_polys"], r0["rec_texts"], r0["rec_scores"]))
        return [(box, text, score) for box, (text, score) in (r0 or [])]  # 2.x

    @staticmethod
    def _reader(lang: str):
        code = _LANG.get(lang, lang)
        if code not in _READERS:
            try:
                from paddleocr import PaddleOCR
            except ImportError as e:
                raise EngineError(
                    "paddleocr not installed: pip install paddleocr paddlepaddle"
                ) from e
            params = inspect.signature(PaddleOCR.__init__).parameters
            kw = {"lang": code, "enable_mkldnn": False}  # oneDNN PIR breaks PP-OCRv5 on paddle 3.x
            if "show_log" in params:
                kw["show_log"] = False
            if "use_angle_cls" in params:  # 2.x
                kw["use_angle_cls"] = True
            elif "use_textline_orientation" in params:  # 3.x
                kw["use_textline_orientation"] = True
            for k in ("use_doc_orientation_classify", "use_doc_unwarping"):
                if k in params:  # 3.x: skip heavy doc preprocessing (we deskew already)
                    kw[k] = False
            if "text_det_limit_side_len" in params:  # 3.x: cap detector input to fit CPU RAM
                kw["text_det_limit_type"] = "max"
                kw["text_det_limit_side_len"] = 960
            if os.environ.get("PADDLE_USE_GPU"):
                if "use_gpu" in params:  # 2.x
                    kw["use_gpu"] = True
                else:  # 3.x
                    kw["device"] = "gpu"
            _READERS[code] = PaddleOCR(**kw)
        return _READERS[code]
