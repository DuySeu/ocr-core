import pypdfium2 as pdfium
import pytest
from PIL import Image

from core.geometry import IDENTITY_MATRIX, POINTS_PER_INCH, px_to_pdf_point
from core.loader import (
    SUPPORTED_EXTS,
    UnsupportedFormatError,
    document_sha256,
    load,
)

A4_WIDTH_PT = 595.0
A4_HEIGHT_PT = 842.0


# Write a blank multi-page PDF whose pages carry the given /Rotate values.
def make_pdf(path, rotations=(0,)):
    document = pdfium.PdfDocument.new()
    for rotation in rotations:
        page = document.new_page(A4_WIDTH_PT, A4_HEIGHT_PT)
        page.set_rotation(rotation)
    document.save(str(path))
    return path


def test_load_returns_one_page_per_pdf_page_numbered_from_one(tmp_path):
    pages = load(make_pdf(tmp_path / "three.pdf", (0, 0, 0)), dpi=72)

    assert [p.geometry.page for p in pages] == [1, 2, 3]


def test_load_renders_at_the_requested_dpi(tmp_path):
    pages = load(make_pdf(tmp_path / "one.pdf"), dpi=150)

    scale = 150 / POINTS_PER_INCH
    assert pages[0].image.size == pytest.approx(
        (A4_WIDTH_PT * scale, A4_HEIGHT_PT * scale), abs=2
    )
    assert pages[0].geometry.dpi == 150


def test_load_records_page_size_before_rotation_not_the_displayed_size(tmp_path):
    pages = load(make_pdf(tmp_path / "rot.pdf", (0, 90, 180, 270)), dpi=72)

    for page in pages:
        assert page.geometry.pdf_width_pt == pytest.approx(A4_WIDTH_PT)
        assert page.geometry.pdf_height_pt == pytest.approx(A4_HEIGHT_PT)


def test_load_records_rotation_clockwise_matching_the_pdf_rotate_value(tmp_path):
    pages = load(make_pdf(tmp_path / "rot.pdf", (0, 90, 180, 270)), dpi=72)

    assert [p.geometry.rotation_applied for p in pages] == [0, 90, 180, 270]


def test_a_quarter_turned_page_renders_wider_than_it_is_tall(tmp_path):
    upright, turned = load(make_pdf(tmp_path / "rot.pdf", (0, 90)), dpi=72)

    assert upright.image.height > upright.image.width
    assert turned.image.width > turned.image.height


def test_a_quarter_turned_page_maps_its_full_extent_back_onto_the_page(tmp_path):
    turned = load(make_pdf(tmp_path / "rot.pdf", (90,)), dpi=72)[0]
    geom = turned.geometry

    x, y, w, h = px_to_pdf_point((0, 0, geom.width_px, geom.height_px), geom)

    assert (x, y) == pytest.approx((0.0, 0.0), abs=2)
    assert (x + w, y + h) == pytest.approx((A4_WIDTH_PT, A4_HEIGHT_PT), abs=2)


def test_load_leaves_deskew_untouched_for_preprocess_to_fill_in(tmp_path):
    geom = load(make_pdf(tmp_path / "one.pdf"), dpi=72)[0].geometry

    assert geom.deskew_angle == 0.0
    assert geom.deskew_matrix == IDENTITY_MATRIX


def test_load_treats_an_image_as_a_single_page_with_no_pdf_size(tmp_path):
    path = tmp_path / "scan.png"
    Image.new("RGB", (400, 300), "white").save(path)

    pages = load(path, dpi=300)

    assert len(pages) == 1
    assert pages[0].geometry.page == 1
    assert pages[0].geometry.width_px == 400
    assert pages[0].geometry.pdf_width_pt is None
    assert pages[0].geometry.pdf_height_pt is None


def test_load_converts_a_palette_image_to_rgb(tmp_path):
    path = tmp_path / "palette.png"
    Image.new("P", (40, 30)).save(path)

    assert load(path)[0].image.mode == "RGB"


def test_load_rejects_an_unsupported_extension(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not a scan")

    with pytest.raises(UnsupportedFormatError, match="unsupported format"):
        load(path)


def test_supported_exts_covers_pdf_and_the_common_scan_formats():
    assert {".pdf", ".png", ".jpg", ".tiff"} <= SUPPORTED_EXTS


def test_document_sha256_is_stable_and_content_addressed(tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytes")

    assert document_sha256(first) == document_sha256(second)
    assert len(document_sha256(first)) == 64


def test_document_sha256_changes_when_a_byte_changes(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"before")
    before = document_sha256(path)
    path.write_bytes(b"after")

    assert document_sha256(path) != before
