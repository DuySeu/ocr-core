from core import pipeline
from core.config import Config


def test_run_to_file_markdown(tmp_path, monkeypatch):
    doc = {"pages": [{"page": 1, "error": None,
                      "blocks": [{"type": "paragraph", "text": "hi"}]}]}
    monkeypatch.setattr(pipeline, "run", lambda p, c: doc)
    cfg = Config(mode="markdown", output_dir=str(tmp_path))
    out = pipeline.run_to_file("input/foo.pdf", cfg)
    assert out.endswith("foo.md")
    assert "hi" in (tmp_path / "foo.md").read_text()


def test_run_to_file_json(tmp_path, monkeypatch):
    doc = {"pages": [], "mode": "data"}
    monkeypatch.setattr(pipeline, "run", lambda p, c: doc)
    cfg = Config(mode="data", output_dir=str(tmp_path))
    out = pipeline.run_to_file("input/foo.png", cfg)
    assert out.endswith("foo.json")
