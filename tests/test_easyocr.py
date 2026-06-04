import sys
import types

import pytest
from PIL import Image

import ocr_core.engines.easyocr as easyocr_mod
from ocr_core.engines.base import EngineError
from ocr_core.engines.easyocr import EasyOCREngine


@pytest.fixture(autouse=True)
def _clear_readers():
    easyocr_mod._READERS.clear()
    yield
    easyocr_mod._READERS.clear()


def _fake_easyocr(monkeypatch, results):
    fake = types.ModuleType("easyocr")

    class Reader:
        def __init__(self, langs, gpu=False):
            self.langs = langs

        def readtext(self, arr):
            return results

    fake.Reader = Reader
    monkeypatch.setitem(sys.modules, "easyocr", fake)


def test_recognize_words_mapping(monkeypatch):
    _fake_easyocr(
        monkeypatch,
        [([[10, 20], [60, 20], [60, 40], [10, 40]], "Hoá", 0.95)],
    )
    words = EasyOCREngine().recognize_words(Image.new("RGB", (80, 60)), ["vie", "eng"])
    assert len(words) == 1
    w = words[0]
    assert w.text == "Hoá"
    assert w.bbox == (10, 20, 50, 20)
    assert w.confidence == 95.0
    assert w.line_key == (2, 10)


def test_recognize_text_ordering(monkeypatch):
    _fake_easyocr(
        monkeypatch,
        [
            ([[0, 50], [10, 50], [10, 60], [0, 60]], "dưới", 0.9),
            ([[0, 10], [10, 10], [10, 20], [0, 20]], "trên", 0.9),
        ],
    )
    text = EasyOCREngine().recognize_text(Image.new("RGB", (20, 80)), ["vie", "eng"])
    assert text == "trên\ndưới"


def test_reader_cached_per_langset(monkeypatch):
    _fake_easyocr(monkeypatch, [])
    eng = EasyOCREngine()
    r1 = eng._reader(["vie", "eng"])
    r2 = eng._reader(["vie", "eng"])
    assert r1 is r2
    assert r1.langs == ["vi", "en"]  # mapped codes


def test_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "easyocr", None)  # None -> ImportError on `import easyocr`
    with pytest.raises(EngineError, match="easyocr not installed"):
        EasyOCREngine().recognize_words(Image.new("RGB", (5, 5)), ["vie", "eng"])
