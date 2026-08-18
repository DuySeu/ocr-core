"""Stage 3 interface: one detector, boxes out. No text recognized here."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from PIL import Image

from ..tables import Cell


class LayoutError(Exception):
    """Raised when a layout/table name is not registered."""


@dataclass(frozen=True)
class LayoutBox:
    category: str  # "text" | "table"
    bbox: tuple[int, int, int, int]  # deskew frame (§4.5), NOT the canonical frame
    layout_score: float | None = None  # always None with both current detectors
    cells: list[Cell] | None = None  # only table_cv fills this in
    n_rows: int | None = None  # from Table.n_rows, never re-derived from cells
    n_cols: int | None = None


class LayoutDetector(ABC):
    @abstractmethod
    def detect(self, image: Image.Image, langs: list[str]) -> list[LayoutBox]:
        """Find boxes on one already-preprocessed page image."""
