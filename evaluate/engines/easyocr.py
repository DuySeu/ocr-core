"""EasyOCR output as the evaluator's shape.

Written by ``core/serialize``, so the reading is the one in ``base``. This module
exists so an easyocr-specific quirk has somewhere to live without touching the
other two engines that share that writer today.
"""

from __future__ import annotations

from pathlib import Path

from .base import PredictionDoc, read_core_documents


# Read every document the easyocr pipeline wrote under an output directory.
def read_documents(output_dir: Path) -> list[PredictionDoc]:
    return read_core_documents(output_dir)
