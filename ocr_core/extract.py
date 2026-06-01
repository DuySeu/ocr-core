"""Extract engine output into blocks per page, by mode/granularity."""
from __future__ import annotations

import re

from .engines.base import OCREngine, Word


def extract(engine: OCREngine, image, config) -> list[dict]:
    """Return list of block dicts for one page, driven by config."""
    if config.mode == "data":  # granularity = line
        return _to_lines(engine.recognize_words(image, config.lang))
    text = engine.recognize_text(image, config.lang)  # mode = text
    if config.granularity == "page":
        return [{"text": text.strip()}] if text.strip() else []
    return [{"text": p} for p in _split_paragraphs(text)]


def _to_lines(words: list[Word]) -> list[dict]:
    """Group words by line key into ordered {text, bbox, confidence} dicts."""
    groups: dict[tuple, list[Word]] = {}
    for w in words:
        groups.setdefault(w.line_key, []).append(w)

    lines = []
    for key in sorted(groups):
        ws = groups[key]
        text = " ".join(w.text for w in ws)
        x0 = min(w.bbox[0] for w in ws)
        y0 = min(w.bbox[1] for w in ws)
        x1 = max(w.bbox[0] + w.bbox[2] for w in ws)
        y1 = max(w.bbox[1] + w.bbox[3] for w in ws)
        conf = round(sum(w.confidence for w in ws) / len(ws), 1)
        lines.append({"text": text, "bbox": [x0, y0, x1 - x0, y1 - y0], "confidence": conf})
    return lines


def _split_paragraphs(text: str) -> list[str]:
    """Split prose into paragraphs on blank lines; trim, drop empties."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
