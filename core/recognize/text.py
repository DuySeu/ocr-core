"""Text recognizer: recognize_words(), not recognize_text() (§4.3) - the plain-

string form throws away per-word confidence and bbox, which both the
uncertainty signal and finetune/cut_lines.py need.
"""

from __future__ import annotations

from PIL import Image

from .base import RecognizedBox
from ..document.model import TextContent, TextLine
from ..engines import get_engine
from ..geometry import corners

CONFIDENCE_SCALE = 100.0  # Word.confidence is 0-100 on every engine (core/engines/base.py)


# Crop to the box, recognize words, group into lines. The one place confidence
# is divided by 100 (§4.3) - everything downstream sees 0..1 or nothing.
def recognize_text(image: Image.Image, box, cfg) -> RecognizedBox:
    x, y, w, h = box.bbox
    words = get_engine(cfg.engine).recognize_words(image.crop((x, y, x + w, y + h)), cfg.langs)

    groups: dict[tuple, list] = {}
    for word in words:
        groups.setdefault(word.line_key, []).append(word)

    lines = []
    for key in sorted(groups):
        line_words = groups[key]
        x0 = x + min(w_.bbox[0] for w_ in line_words)
        y0 = y + min(w_.bbox[1] for w_ in line_words)
        x1 = x + max(w_.bbox[0] + w_.bbox[2] for w_ in line_words)
        y1 = y + max(w_.bbox[1] + w_.bbox[3] for w_ in line_words)
        line_bbox = (x0, y0, x1 - x0, y1 - y0)
        text = " ".join(w_.text for w_ in line_words)
        confidence = sum(w_.confidence for w_ in line_words) / len(line_words) / CONFIDENCE_SCALE
        lines.append(
            TextLine(
                text=text,
                text_ocr=text,
                polygon=corners(line_bbox),  # deskew frame; assemble.py re-derives it canonically
                bbox=line_bbox,
                confidence=confidence,
            )
        )

    scores = [line.confidence for line in lines if line.confidence is not None]
    return RecognizedBox(
        category="text",
        bbox=box.bbox,
        layout_score=box.layout_score,
        content=TextContent(text="\n".join(line.text for line in lines), lines=lines),
        rec_score=sum(scores) / len(scores) if scores else None,
        logprob=None,
        flags=[],
    )
