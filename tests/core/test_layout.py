import pytest
from PIL import Image

from core.config import Config
from core.layout import LayoutError, detect, get_detector
from core.layout.base import LayoutBox
from core.layout.none import NoneDetector
from core.layout.table_cv import TableCVDetector
from core.layout.tesseract_blocks import TesseractBlockDetector


def test_get_detector_rejects_an_unknown_name():
    with pytest.raises(LayoutError):
        get_detector("bogus")


def test_get_detector_maps_tesseract_and_none():
    assert isinstance(get_detector("tesseract"), TesseractBlockDetector)
    assert isinstance(get_detector("none"), NoneDetector)


def test_drops_text_block_contained_in_table_region(monkeypatch):
    table = LayoutBox(category="table", bbox=(0, 0, 100, 100))
    text = LayoutBox(category="text", bbox=(10, 10, 20, 20))  # fully inside the table

    monkeypatch.setattr(TableCVDetector, "detect", lambda self, image, langs: [table])
    monkeypatch.setattr(TesseractBlockDetector, "detect", lambda self, image, langs: [text])

    boxes = detect(Image.new("RGB", (200, 200)), Config(layout="tesseract"))

    assert boxes == [table]


def test_keeps_small_text_block_barely_touching_table(monkeypatch):
    table = LayoutBox(category="table", bbox=(0, 0, 100, 100))
    # 10% of the text box overlaps the table - well under the 0.7 containment threshold
    text = LayoutBox(category="text", bbox=(90, 90, 100, 10))

    monkeypatch.setattr(TableCVDetector, "detect", lambda self, image, langs: [table])
    monkeypatch.setattr(TesseractBlockDetector, "detect", lambda self, image, langs: [text])

    boxes = detect(Image.new("RGB", (200, 200)), Config(layout="tesseract"))

    assert text in boxes


def test_table_cv_always_runs_even_under_layout_none(monkeypatch):
    table = LayoutBox(category="table", bbox=(0, 0, 50, 50))
    monkeypatch.setattr(TableCVDetector, "detect", lambda self, image, langs: [table])

    boxes = detect(Image.new("RGB", (200, 200)), Config(layout="none"))

    assert table in boxes
