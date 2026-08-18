import pytest
from PIL import Image

import core.recognize.table as table_mod
import core.recognize.text as text_mod
from core.config import Config
from core.engines.base import Word
from core.layout.base import LayoutBox
from core.recognize import recognize
from core.tables import Cell


class _FakeEngine:
    def __init__(self, words=None, cell_text=""):
        self._words = words or []
        self._cell_text = cell_text

    def recognize_words(self, image, langs):
        return self._words

    def recognize_text(self, image, langs, psm=None):
        return self._cell_text


def test_divides_word_confidence_by_hundred_once(monkeypatch):
    words = [Word(text="hi", bbox=(0, 0, 5, 5), confidence=80.0, line_key=(1, 1, 1))]
    monkeypatch.setattr(text_mod, "get_engine", lambda name: _FakeEngine(words=words))

    box = LayoutBox(category="text", bbox=(0, 0, 10, 10))
    result = text_mod.recognize_text(Image.new("RGB", (20, 20)), box, Config())

    assert result.content.lines[0].confidence == pytest.approx(0.8)
    assert result.rec_score == pytest.approx(0.8)


def test_groups_words_into_lines_by_line_key(monkeypatch):
    words = [
        Word(text="a", bbox=(0, 0, 5, 5), confidence=90.0, line_key=(1, 1, 1)),
        Word(text="b", bbox=(6, 0, 5, 5), confidence=90.0, line_key=(1, 1, 1)),
        Word(text="c", bbox=(0, 20, 5, 5), confidence=90.0, line_key=(1, 1, 2)),
    ]
    monkeypatch.setattr(text_mod, "get_engine", lambda name: _FakeEngine(words=words))

    box = LayoutBox(category="text", bbox=(0, 0, 30, 30))
    result = text_mod.recognize_text(Image.new("RGB", (40, 40)), box, Config())

    assert len(result.content.lines) == 2
    assert result.content.lines[0].text == "a b"


def test_text_recognizer_reports_no_signal_when_the_crop_has_no_words(monkeypatch):
    monkeypatch.setattr(text_mod, "get_engine", lambda name: _FakeEngine(words=[]))

    box = LayoutBox(category="text", bbox=(0, 0, 10, 10))
    result = text_mod.recognize_text(Image.new("RGB", (10, 10)), box, Config())

    assert result.content.lines == [] and result.rec_score is None


def test_takes_table_dimensions_from_detector_not_from_cells(monkeypatch):
    monkeypatch.setattr(table_mod, "get_engine", lambda name: _FakeEngine(cell_text="x"))
    cells = [Cell(0, 0, 1, 1, (0, 0, 10, 10))]  # only one cell, detector says the grid is 3x3
    box = LayoutBox(category="table", bbox=(0, 0, 30, 30), cells=cells, n_rows=3, n_cols=3)

    result = table_mod.recognize_table(Image.new("RGB", (30, 30)), box, Config())

    assert (result.content.n_rows, result.content.n_cols) == (3, 3)
    assert result.rec_score is None  # tier 3: recognize_text() gives a bare string, no confidence


def test_builds_table_html_with_rowspan_from_merged_cells(monkeypatch):
    monkeypatch.setattr(table_mod, "get_engine", lambda name: _FakeEngine(cell_text="v"))
    cells = [
        Cell(0, 0, 2, 1, (0, 0, 10, 20)),  # spans rows 0-1 in column 0 (rowspan=2)
        Cell(0, 1, 1, 2, (10, 0, 10, 10)),  # row 0, col 1
        Cell(1, 1, 2, 2, (10, 10, 10, 10)),  # row 1, col 1
        Cell(1, 0, 2, 1, (0, 10, 10, 10)),  # phantom duplicate at a slot the rowspan already covers
    ]
    box = LayoutBox(category="table", bbox=(0, 0, 20, 20), cells=cells, n_rows=2, n_cols=2)

    result = table_mod.recognize_table(Image.new("RGB", (20, 20)), box, Config())

    assert 'rowspan="2"' in result.content.html
    assert result.content.html.count("<td") == 3  # the phantom (1,0) cell is skipped, not an empty <td>


def test_table_disabled_by_config_keeps_geometry_and_flags_provider_disabled():
    box = LayoutBox(category="table", bbox=(0, 0, 10, 10), cells=[], n_rows=1, n_cols=1)

    result = table_mod.recognize_table(Image.new("RGB", (10, 10)), box, Config(table="none"))

    assert result.content is None and result.flags == ["provider_disabled"]
    assert result.bbox == (0, 0, 10, 10)  # geometry survives even though recognition didn't run


def test_recognize_router_turns_a_recognizer_exception_into_a_flagged_box():
    box = LayoutBox(category="text", bbox=(0, 0, 10, 10))
    broken_cfg = Config(engine="tesseract")
    broken_cfg.engine = "does-not-exist"  # bypass validate(); exercise the failure path directly

    result = recognize(Image.new("RGB", (10, 10)), box, broken_cfg)

    assert result.content is None and result.flags == ["recognize_failed"]
