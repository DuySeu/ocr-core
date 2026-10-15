import sys
import types

import pytest
from PIL import Image

import core.engines.paddle as paddle_mod
from core.engines.base import EngineError
from core.engines.paddle import PaddleOCREngine


@pytest.fixture(autouse=True)
def _clear_readers():
    paddle_mod._READERS.clear()
    yield
    paddle_mod._READERS.clear()


def _fake_paddle(monkeypatch, lines):
    fake = types.ModuleType("paddleocr")

    class PaddleOCR:
        def __init__(self, **kw):
            pass

        def ocr(self, arr, **kw):
            return [lines]

    fake.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)


def test_recognize_words_mapping(monkeypatch):
    _fake_paddle(
        monkeypatch,
        [[[[10, 20], [60, 20], [60, 40], [10, 40]], ("Hoá", 0.95)]],
    )
    words = PaddleOCREngine().recognize_words(Image.new("RGB", (80, 60)), ["vie"])
    assert len(words) == 1
    w = words[0]
    assert w.text == "Hoá"
    assert w.bbox == (10, 20, 50, 20)
    assert w.confidence == 95.0
    assert w.line_key == (2, 10)


def test_recognize_text_ordering(monkeypatch):
    _fake_paddle(
        monkeypatch,
        [
            [[[0, 50], [10, 50], [10, 60], [0, 60]], ("dưới", 0.9)],
            [[[0, 10], [10, 10], [10, 20], [0, 20]], ("trên", 0.9)],
        ],
    )
    text = PaddleOCREngine().recognize_text(Image.new("RGB", (20, 80)), ["vie"])
    assert text == "trên\ndưới"


def test_recognize_words_v3_format(monkeypatch):
    fake = types.ModuleType("paddleocr")
    result = [
        {
            "rec_polys": [[[10, 20], [60, 20], [60, 40], [10, 40]]],
            "rec_texts": ["Hoá"],
            "rec_scores": [0.95],
        }
    ]

    class PaddleOCR:
        def __init__(self, **kw):
            pass

        def ocr(self, arr, **kw):
            return result

    fake.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    words = PaddleOCREngine().recognize_words(Image.new("RGB", (80, 60)), ["vie"])
    assert len(words) == 1
    assert words[0].text == "Hoá"
    assert words[0].bbox == (10, 20, 50, 20)
    assert words[0].confidence == 95.0


def test_missing_dependency(monkeypatch):
    fake = types.ModuleType("paddleocr")  # no PaddleOCR attr -> ImportError on import
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    with pytest.raises(EngineError, match="paddleocr not installed"):
        PaddleOCREngine().recognize_words(Image.new("RGB", (5, 5)), ["vie"])
