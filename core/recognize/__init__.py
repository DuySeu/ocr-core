"""Stage 4: route a LayoutBox to its recognizer by category.

The try/except boundary lives here, not inside text.py/table.py: any failure
in either becomes a geometry-preserving, content-less box rather than an
exception reaching run_page (§8 - "Recognizer lỗi").
"""

from __future__ import annotations

from PIL import Image

from .base import RecognizedBox
from .table import recognize_table
from .text import recognize_text

__all__ = ["RecognizedBox", "recognize"]


def recognize(image: Image.Image, box, cfg) -> RecognizedBox:
    try:
        if box.category == "table":
            return recognize_table(image, box, cfg)
        return recognize_text(image, box, cfg)
    except Exception:
        return RecognizedBox(
            category=box.category,
            bbox=box.bbox,
            layout_score=box.layout_score,
            content=None,
            rec_score=None,
            logprob=None,
            flags=["recognize_failed"],
        )
