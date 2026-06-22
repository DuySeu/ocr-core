"""Offline tests for postprocess: the OpenRouter call is always mocked."""

import pytest

from ocr_core import postprocess
from ocr_core.config import Config


@pytest.fixture
def with_key(monkeypatch):
    """Pretend an API key is present so correct_page proceeds to the call."""
    monkeypatch.setattr(postprocess, "API_KEY", "test-key")


def _blocks():
    return [
        {"type": "paragraph", "text": "helo wrld"},
        {
            "type": "table",
            "rows": [["Naem", ""], ["a", "b"]],
            "header": True,
        },
        {"text": "lin txt", "bbox": [1, 2, 3, 4], "confidence": 88.5},
    ]


def test_flatten_skips_empty_and_orders():
    texts, slots = postprocess._flatten(_blocks())
    assert texts == ["helo wrld", "Naem", "a", "b", "lin txt"]
    assert slots == [
        ("paragraph", 0),
        ("cell", 1, 0, 0),
        ("cell", 1, 1, 0),
        ("cell", 1, 1, 1),
        ("line", 2),
    ]


def test_maps_corrections_back_by_index(monkeypatch, with_key):
    fixed = ["hello world", "Name", "A", "B", "line text"]
    monkeypatch.setattr(postprocess, "_call_openrouter", lambda texts: fixed)

    out = postprocess.correct_page(_blocks(), Config())

    assert out[0]["text"] == "hello world"
    assert out[1]["rows"] == [["Name", ""], ["A", "B"]]
    assert out[2]["text"] == "line text"


def test_preserves_non_text_fields(monkeypatch, with_key):
    fixed = ["hello world", "Name", "A", "B", "line text"]
    monkeypatch.setattr(postprocess, "_call_openrouter", lambda texts: fixed)

    blocks = _blocks()
    out = postprocess.correct_page(blocks, Config())

    assert out[2]["bbox"] == [1, 2, 3, 4]
    assert out[2]["confidence"] == 88.5
    assert out[1]["header"] is True
    assert len(out) == len(blocks)
    # empty cell stays empty
    assert out[1]["rows"][0][1] == ""
    # originals untouched (immutability)
    assert blocks[0]["text"] == "helo wrld"


def test_length_mismatch_falls_back(monkeypatch, with_key):
    monkeypatch.setattr(postprocess, "_call_openrouter", lambda texts: ["only one"])
    blocks = _blocks()
    assert postprocess.correct_page(blocks, Config()) == blocks


def test_call_failure_falls_back(monkeypatch, with_key):
    monkeypatch.setattr(postprocess, "_call_openrouter", lambda texts: None)
    blocks = _blocks()
    assert postprocess.correct_page(blocks, Config()) == blocks


def test_missing_key_skips(monkeypatch):
    monkeypatch.setattr(postprocess, "API_KEY", None)
    monkeypatch.setattr(postprocess, "_warned_no_key", False)

    def _boom(texts):
        raise AssertionError("should not call the API without a key")

    monkeypatch.setattr(postprocess, "_call_openrouter", _boom)
    blocks = _blocks()
    assert postprocess.correct_page(blocks, Config()) == blocks


def test_no_correctable_text_skips(monkeypatch, with_key):
    def _boom(texts):
        raise AssertionError("should not call the API with no text")

    monkeypatch.setattr(postprocess, "_call_openrouter", _boom)
    blocks = [{"type": "paragraph", "text": ""}]
    assert postprocess.correct_page(blocks, Config()) == blocks
