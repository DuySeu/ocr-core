import numpy as np
import pytest
from PIL import Image, ImageDraw

from core.geometry import IDENTITY_MATRIX, PageGeometry, corners, to_canonical
from core.loader import PageImage
from core.preprocess import STEPS, PreprocessError, apply


# Draw a page of horizontal text-like bars, optionally tilted.
def make_page(width=600, height=800, angle=0.0, rotation=0) -> PageImage:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for y in range(80, height - 80, 40):
        draw.rectangle([80, y, width - 80, y + 12], fill="black")
    if angle:
        image = image.rotate(angle, fillcolor="white")
    geometry = PageGeometry(
        page=1,
        width_px=image.width,
        height_px=image.height,
        dpi=300,
        rotation_applied=rotation,
        deskew_angle=0.0,
        deskew_matrix=IDENTITY_MATRIX,
        pdf_width_pt=None,
        pdf_height_pt=None,
    )
    return PageImage(image, geometry)


def test_apply_runs_steps_in_the_order_given():
    seen = []
    STEPS["_spy_a"] = lambda page: (seen.append("a"), page)[1]
    STEPS["_spy_b"] = lambda page: (seen.append("b"), page)[1]
    try:
        apply(make_page(), ["_spy_b", "_spy_a", "_spy_b"])
    finally:
        del STEPS["_spy_a"], STEPS["_spy_b"]

    assert seen == ["b", "a", "b"]


def test_apply_rejects_an_unregistered_step():
    with pytest.raises(PreprocessError, match="unknown step 'sharpen'"):
        apply(make_page(), ["sharpen"])


def test_apply_with_no_steps_returns_the_page_untouched():
    page = make_page()

    assert apply(page, []) is page


def test_deskew_records_the_angle_it_corrected():
    result = apply(make_page(angle=3.0), ["deskew"])

    assert abs(result.geometry.deskew_angle) > 0.5
    assert result.geometry.deskew_matrix != IDENTITY_MATRIX


def test_deskew_leaves_a_straight_page_alone():
    result = apply(make_page(), ["deskew"])

    assert result.geometry.deskew_angle == 0.0
    assert result.geometry.deskew_matrix == IDENTITY_MATRIX


def test_deskew_matrix_maps_detections_back_onto_the_original_ink():
    page = make_page(angle=4.0)
    deskewed = apply(page, ["deskew"])

    # A point in the deskewed image must land back inside the original page
    restored = to_canonical(corners((100, 100, 50, 20)), deskewed.geometry)

    assert all(0 <= x <= page.geometry.width_px for x, _ in restored)
    assert all(0 <= y <= page.geometry.height_px for _, y in restored)


def test_deskew_ignores_a_blank_page():
    blank = PageImage(Image.new("RGB", (200, 300), "white"), make_page().geometry)

    assert apply(blank, ["deskew"]).geometry.deskew_angle == 0.0


def test_deskew_refuses_an_implausible_angle_rather_than_wrecking_the_page():
    # A single tall bar makes minAreaRect report a near-90 degree angle
    image = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(image).rectangle([190, 20, 210, 380], fill="black")

    result = apply(PageImage(image, make_page().geometry), ["deskew"])

    assert result.geometry.deskew_angle == 0.0


def test_denoise_keeps_the_page_size_and_geometry():
    page = make_page()

    result = apply(page, ["denoise"])

    assert result.image.size == page.image.size
    assert result.geometry == page.geometry


def test_denoise_removes_isolated_speckle():
    image = Image.new("RGB", (100, 100), "white")
    image.putpixel((50, 50), (0, 0, 0))

    result = apply(PageImage(image, make_page().geometry), ["denoise"])

    assert result.image.getpixel((50, 50)) == (255, 255, 255)


def test_grayscale_and_binarize_do_not_move_geometry():
    page = make_page()

    result = apply(page, ["grayscale", "binarize"])

    assert result.geometry == page.geometry


def test_binarize_leaves_only_two_ink_levels():
    result = apply(make_page(), ["binarize"])

    assert set(np.unique(np.array(result.image))) <= {0, 255}


# Make Tesseract's OSD report a fixed quarter turn.
def stub_osd(monkeypatch, rotate):
    import pytesseract

    monkeypatch.setattr(
        pytesseract,
        "image_to_osd",
        lambda image, output_type=None: {"rotate": rotate, "orientation_conf": 9.9},
    )


def test_orientation_folds_its_turn_into_the_recorded_rotation(monkeypatch):
    stub_osd(monkeypatch, 90)
    page = make_page(width=600, height=800, rotation=180)

    result = apply(page, ["orientation"])

    assert result.geometry.rotation_applied == 270
    assert (result.image.width, result.image.height) == (800, 600)
    assert (result.geometry.width_px, result.geometry.height_px) == (800, 600)


def test_orientation_is_a_no_op_when_the_page_is_already_upright(monkeypatch):
    stub_osd(monkeypatch, 0)
    page = make_page()

    assert apply(page, ["orientation"]) is page


def test_orientation_wraps_past_a_full_turn(monkeypatch):
    stub_osd(monkeypatch, 270)

    result = apply(make_page(rotation=180), ["orientation"])

    assert result.geometry.rotation_applied == 90


def test_orientation_reports_a_missing_tesseract_binary_with_install_advice(monkeypatch):
    import pytesseract

    def missing(image, output_type=None):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_osd", missing)

    with pytest.raises(PreprocessError, match="brew install tesseract"):
        apply(make_page(), ["orientation"])


def test_orientation_leaves_the_page_alone_when_osd_cannot_decide():
    import pytesseract

    # A blank page gives Tesseract nothing to judge orientation from
    blank = PageImage(Image.new("RGB", (300, 400), "white"), make_page().geometry)

    assert pytesseract  # the step needs it installed
    assert apply(blank, ["orientation"]).geometry.rotation_applied == 0


@pytest.mark.slow
def test_orientation_detects_every_quarter_turn_on_a_real_page():
    from dataclasses import replace

    from core.loader import load

    upright = load("input/2356-TTr-VCB-KTKHDL-KTKHDL 1.pdf", dpi=200)[0]

    for turn in (0, 90, 180, 270):
        image = upright.image.rotate(-turn, expand=True)
        turned = PageImage(
            image,
            replace(
                upright.geometry,
                rotation_applied=turn,
                width_px=image.width,
                height_px=image.height,
            ),
        )
        assert apply(turned, ["orientation"]).geometry.rotation_applied == 0
