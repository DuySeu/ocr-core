"""Tests for folder-based page review export and apply."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.document.model import Document, Element, TextContent, TextLine
from core.geometry import IDENTITY_MATRIX, PageGeometry
from core.review_io import (
    ReviewError,
    apply_page_texts,
    clear_applied_review_pages,
    export_failing_pages,
    format_page_markdown,
    load_document_json,
    load_review_corrections,
    page_text_lines,
    parse_page_markdown,
    write_document_json,
)


def _line(text: str, ocr: str | None = None) -> TextLine:
    return TextLine(
        text=text,
        text_ocr=ocr if ocr is not None else text,
        polygon=[(0, 0), (1, 0), (1, 1), (0, 1)],
        bbox=(0, 0, 1, 1),
        confidence=0.9,
    )


def _text_element(
    element_id: int,
    page: int,
    order: int,
    lines: list[TextLine],
    rec_score: float | None = 0.9,
) -> Element:
    return Element(
        id=element_id,
        page=page,
        category="text",
        bbox=(0, 0, 10, 10),
        reading_order=order,
        content=TextContent(
            text="\n".join(line.text for line in lines),
            lines=lines,
        ),
        rec_score=rec_score,
    )


def _doc(elements: list[Element]) -> Document:
    pages = sorted({e.page for e in elements})
    geometries = [
        PageGeometry(p, 100, 100, 300, 0, 0.0, IDENTITY_MATRIX, None, None)
        for p in pages
    ]
    return Document(
        source="x.pdf",
        doc_sha256="abc",
        pipeline_version="tesseract_vie_tesseract_cv_deadbeef",
        pages=geometries,
        elements=elements,
        errors=[],
    )


def test_format_and_parse_round_trip_preserves_lines():
    lines = [_line("một"), _line("hai")]
    text = format_page_markdown(3, lines)
    page, body = parse_page_markdown(text)
    assert page == 3
    assert body == ["một", "hai"]


def test_parse_rejects_line_count_mismatch():
    text = "<!-- page: 1 lines: 2 -->\nonly-one\n"
    with pytest.raises(ReviewError, match="lines=2"):
        parse_page_markdown(text)


def test_export_failing_pages_writes_webp_and_md(tmp_path: Path):
    elements = [
        _text_element(10_000, 1, 0, [_line("ok")], rec_score=0.9),
        _text_element(20_000, 2, 1, [_line("bad")], rec_score=0.4),
    ]
    doc = _doc(elements)
    images = {
        1: Image.new("RGB", (8, 8), "white"),
        2: Image.new("RGB", (8, 8), "gray"),
    }
    review_dir = tmp_path / "review" / "doc"
    exported = export_failing_pages(doc, images, review_dir, qa_threshold=0.75)

    assert exported == [2]
    assert (review_dir / "p0002.webp").is_file()
    assert (review_dir / "p0002.md").is_file()
    assert not (review_dir / "p0001.md").exists()
    page, body = parse_page_markdown(
        (review_dir / "p0002.md").read_text(encoding="utf-8")
    )
    assert page == 2 and body == ["bad"]


def test_apply_page_texts_updates_text_keeps_text_ocr():
    lines = [_line("old", ocr="ocr-old"), _line("old2", ocr="ocr-old2")]
    element = _text_element(10_000, 1, 0, lines, rec_score=0.4)
    doc = _doc([element])

    apply_page_texts(doc, {1: ["new", "new2"]})

    updated = page_text_lines(doc.elements, 1)
    assert [line.text for line in updated] == ["new", "new2"]
    assert [line.text_ocr for line in updated] == ["ocr-old", "ocr-old2"]
    assert element.content.text == "new\nnew2"


def test_apply_page_texts_rejects_wrong_line_count():
    element = _text_element(10_000, 1, 0, [_line("a"), _line("b")])
    doc = _doc([element])
    with pytest.raises(ReviewError, match="expected 2"):
        apply_page_texts(doc, {1: ["only-one"]})


def test_document_json_round_trip(tmp_path: Path):
    doc = _doc([_text_element(10_000, 1, 0, [_line("hi")])])
    out_dir = tmp_path / "output" / "stem"
    out_dir.mkdir(parents=True)
    write_document_json(doc, out_dir)
    loaded = load_document_json(out_dir)
    assert loaded.doc_sha256 == doc.doc_sha256
    assert page_text_lines(loaded.elements, 1)[0].text == "hi"


def test_load_and_clear_review_pages(tmp_path: Path):
    review_dir = tmp_path / "review" / "stem"
    review_dir.mkdir(parents=True)
    (review_dir / "p0001.md").write_text(
        format_page_markdown(1, [_line("a")]), encoding="utf-8"
    )
    (review_dir / "p0001.webp").write_bytes(b"fake")

    corrections = load_review_corrections(review_dir)
    assert corrections == {1: ["a"]}

    clear_applied_review_pages(review_dir, [1])
    assert not review_dir.exists()
