import sys
import types

from PIL import Image

from ocr_core.engines.tesseract import TesseractEngine


def test_recognize_text_psm(monkeypatch):
    calls = {}
    fake = types.ModuleType("pytesseract")

    def image_to_string(image, lang=None, config=""):
        calls["lang"], calls["config"] = lang, config
        return "hi"

    fake.image_to_string = image_to_string
    fake.Output = types.SimpleNamespace(DICT="dict")
    fake.TesseractNotFoundError = type("TesseractNotFoundError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    out = TesseractEngine().recognize_text(Image.new("RGB", (5, 5)), "vie", psm=6)
    assert out == "hi" and calls == {"lang": "vie", "config": "--psm 6"}
