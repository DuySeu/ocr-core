"""core/loader.py's load_page/page_count - not covered by tests/test_loader.py,
which is evaluate/loader.py's test file (a naming coincidence between two
unrelated modules that both happen to be called "loader")."""

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw

from core.loader import UnsupportedFormatError, load_page, page_count


@pytest.fixture
def three_page_pdf(tmp_path):
    path = tmp_path / "doc.pdf"
    pdf = pdfium.PdfDocument.new()
    for i in range(3):
        page = pdf.new_page(200, 300)
        image = Image.new("RGB", (200, 300), "white")
        ImageDraw.Draw(image).text((10, 10), f"page {i + 1}", fill="black")
    pdf.save(str(path))
    return path


def test_counts_pages_without_rendering_them(three_page_pdf):
    assert page_count(three_page_pdf) == 3


def test_renders_only_the_requested_page(three_page_pdf, monkeypatch):
    original_get_page = pdfium.PdfDocument.get_page
    requested_indices = []

    def spy_get_page(self, index):
        requested_indices.append(index)
        return original_get_page(self, index)

    monkeypatch.setattr(pdfium.PdfDocument, "get_page", spy_get_page)

    result = load_page(three_page_pdf, 2, dpi=72)

    assert requested_indices == [1]  # zero-based index of page 2; no other page touched
    assert result.geometry.page == 2


def test_load_page_rejects_a_page_number_beyond_a_single_page_image(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGB", (50, 50), "white").save(path)

    with pytest.raises(UnsupportedFormatError):
        load_page(path, 2, dpi=72)


def test_page_count_of_a_single_page_image_is_one(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGB", (50, 50), "white").save(path)

    assert page_count(path) == 1
