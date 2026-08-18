"""Fallback detector: no layout model at all, one text box for the whole page."""

from __future__ import annotations

from PIL import Image

from .base import LayoutBox, LayoutDetector


class NoneDetector(LayoutDetector):
    def detect(self, image: Image.Image, langs: list[str]) -> list[LayoutBox]:
        return [LayoutBox(category="text", bbox=(0, 0, image.width, image.height))]
