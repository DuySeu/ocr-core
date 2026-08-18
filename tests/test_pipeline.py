import pytest
from PIL import Image

from core import pipeline
from core.config import Config
from core.document.model import DocumentError, TextContent
from core.geometry import IDENTITY_MATRIX, PageGeometry
from core.layout.base import LayoutBox
from core.loader import PageImage
from core.recognize.base import RecognizedBox


def _geometry(page=1):
    return PageGeometry(page, 100, 100, 300, 0, 0.0, IDENTITY_MATRIX, None, None)


def _page_image(page=1):
    return PageImage(Image.new("RGB", (100, 100), "white"), _geometry(page))


def _recognized(box, **kwargs):
    kwargs.setdefault("content", TextContent("hi"))
    kwargs.setdefault("rec_score", 0.9)
    kwargs.setdefault("logprob", None)
    kwargs.setdefault("flags", [])
    return RecognizedBox(category=box.category, bbox=box.bbox, layout_score=None, **kwargs)


def _stub_stages(monkeypatch):
    """Stub preprocess/layout/recognize so a page needs no real OCR to assemble."""
    monkeypatch.setattr(pipeline.preprocess, "apply", lambda page_image, steps: page_image)
    monkeypatch.setattr(
        pipeline.layout, "detect", lambda image, cfg: [LayoutBox("text", (0, 0, 10, 10))]
    )
    monkeypatch.setattr(pipeline.recognize, "recognize", lambda image, box, cfg: _recognized(box))


def test_run_page_turns_a_load_failure_into_a_page_error(monkeypatch):
    monkeypatch.setattr(
        pipeline, "load_page", lambda path, page, dpi: (_ for _ in ()).throw(FileNotFoundError("nope"))
    )

    result = pipeline.run_page("x.pdf", 1, Config())

    assert result.error.stage == "load"
    assert result.elements == [] and result.geometry is None and result.image is None


def test_run_page_turns_a_preprocess_failure_into_a_page_error(monkeypatch):
    monkeypatch.setattr(pipeline, "load_page", lambda path, page, dpi: _page_image())
    monkeypatch.setattr(
        pipeline.preprocess, "apply", lambda page_image, steps: (_ for _ in ()).throw(RuntimeError("bad"))
    )

    result = pipeline.run_page("x.pdf", 1, Config())

    assert result.error.stage == "preprocess"


def test_run_page_turns_a_layout_failure_into_a_page_error(monkeypatch):
    monkeypatch.setattr(pipeline, "load_page", lambda path, page, dpi: _page_image())
    monkeypatch.setattr(pipeline.preprocess, "apply", lambda page_image, steps: page_image)
    monkeypatch.setattr(
        pipeline.layout, "detect", lambda image, cfg: (_ for _ in ()).throw(RuntimeError("bad"))
    )

    result = pipeline.run_page("x.pdf", 1, Config())

    assert result.error.stage == "layout"


def test_run_page_leaves_reading_order_unset(monkeypatch):
    monkeypatch.setattr(pipeline, "load_page", lambda path, page, dpi: _page_image())
    _stub_stages(monkeypatch)

    result = pipeline.run_page("x.pdf", 1, Config())

    assert result.error is None
    assert result.elements and all(e.reading_order == -1 for e in result.elements)


def test_run_document_assigns_dense_reading_order_and_identity(monkeypatch):
    monkeypatch.setattr(pipeline, "load", lambda path, dpi: [_page_image()])
    monkeypatch.setattr(pipeline, "document_sha256", lambda path: "deadbeef")
    _stub_stages(monkeypatch)

    run = pipeline.run_document("x.pdf", Config())
    doc = run.document

    assert doc.doc_sha256 == "deadbeef"
    assert doc.pipeline_version
    assert [e.reading_order for e in doc.elements] == list(range(len(doc.elements)))
    assert 1 in run.page_images


def test_run_document_collects_a_page_error_and_keeps_processing_the_rest(monkeypatch):
    pages = [_page_image(1), _page_image(2)]
    monkeypatch.setattr(pipeline, "load", lambda path, dpi: pages)
    monkeypatch.setattr(pipeline, "document_sha256", lambda path: "deadbeef")

    def flaky_apply(page_image, steps):
        if page_image.geometry.page == 1:
            raise RuntimeError("page 1 corrupt")
        return page_image

    monkeypatch.setattr(pipeline.preprocess, "apply", flaky_apply)
    monkeypatch.setattr(
        pipeline.layout, "detect", lambda image, cfg: [LayoutBox("text", (0, 0, 10, 10))]
    )
    monkeypatch.setattr(pipeline.recognize, "recognize", lambda image, box, cfg: _recognized(box))

    run = pipeline.run_document("x.pdf", Config())
    doc = run.document

    assert [e.page for e in doc.errors] == [1] and doc.errors[0].stage == "preprocess"
    assert [g.page for g in doc.pages] == [2]
    assert list(run.page_images) == [2]


def test_run_document_raises_when_validate_document_finds_a_broken_invariant(monkeypatch):
    monkeypatch.setattr(pipeline, "load", lambda path, dpi: [_page_image()])
    monkeypatch.setattr(pipeline, "document_sha256", lambda path: "deadbeef")
    _stub_stages(monkeypatch)
    monkeypatch.setattr(
        pipeline, "validate_document", lambda doc: (_ for _ in ()).throw(DocumentError("boom"))
    )

    with pytest.raises(DocumentError):
        pipeline.run_document("x.pdf", Config())
