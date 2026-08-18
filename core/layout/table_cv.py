"""Table detector: wraps core.tables (OpenCV, bordered tables only)."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .base import LayoutBox, LayoutDetector
from .. import tables as tables_mod


class TableCVDetector(LayoutDetector):
    def detect(self, image: Image.Image, langs: list[str]) -> list[LayoutBox]:
        tables = tables_mod.detect_tables(np.array(image))
        return [
            LayoutBox(
                category="table",
                bbox=table.box,
                cells=table.cells,
                n_rows=table.n_rows,
                n_cols=table.n_cols,
            )
            for table in tables
        ]
