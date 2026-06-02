import pytest

from ocr_core.config import Config, ConfigError, PIPELINES, load


def test_legal_default_is_markdown():
    cfg = PIPELINES["legal"]
    assert cfg.mode == "markdown"
    cfg.validate()


def test_unknown_mode_rejected():
    with pytest.raises(ConfigError):
        Config(mode="bogus").validate()


def test_text_mode_removed():
    with pytest.raises(ConfigError):
        Config(mode="text").validate()


def test_precedence_cli_over_base():
    cfg = load(None, {"lang": "eng"}, base=PIPELINES["legal"])
    assert cfg.lang == "eng" and cfg.mode == "markdown"
