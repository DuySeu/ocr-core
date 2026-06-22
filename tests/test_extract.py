from ocr_core import extract
from ocr_core.engines.base import Word
from ocr_core.tables import Cell, Table


class _Cropped:
    def __init__(self, tag):
        self.tag = tag


class _Image:
    size = (200, 100)

    def __init__(self, texts):
        self.texts = texts

    def crop(self, box):
        return _Cropped(self.texts.get(box, ""))


class _Engine:
    def recognize_text(self, image, lang, psm=None):
        return image.tag

    def recognize_words(self, image, lang):
        return [Word("a", (0, 0, 10, 10), 90, (1, 1, 1)),
                Word("b", (12, 0, 10, 10), 80, (1, 1, 1))]


def test_extract_layout_table_with_section(monkeypatch):
    t = Table((0, 0, 200, 100), 3, 2, [
        Cell(0, 0, 1, 1, (0, 0, 100, 20)),
        Cell(0, 1, 1, 2, (100, 0, 100, 20)),
        Cell(1, 0, 2, 2, (0, 20, 200, 20)),    # section: trải hết bảng
        Cell(2, 0, 3, 1, (0, 40, 100, 60)),
        Cell(2, 1, 3, 2, (100, 40, 100, 60)),
    ])
    monkeypatch.setattr(extract.tables_mod, "detect_tables", lambda img: [t])
    texts = {(0, 0, 100, 20): "H1", (100, 0, 200, 20): "H2",
             (0, 20, 200, 40): "SEC",
             (0, 40, 100, 100): "A", (100, 40, 200, 100): "B"}

    class Cfg:
        mode, lang = "markdown", "vie"

        def lang_list(self):
            return [self.lang]

    blocks = extract.extract(_Engine(), _Image(texts), Cfg())
    assert blocks == [{"type": "table", "header": True,
                       "rows": [["H1", "H2"], ["SEC"], ["A", "B"]]}]


def test_extract_data_mode_groups_lines():
    class Cfg:
        mode, lang = "data", "vie"

        def lang_list(self):
            return [self.lang]

    out = extract.extract(_Engine(), object(), Cfg())
    assert out == [{"text": "a b", "bbox": [0, 0, 22, 10], "confidence": 85.0}]
