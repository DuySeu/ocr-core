import cv2
import numpy as np
import pytest

from core.geometry import (
    IDENTITY_MATRIX,
    GeometryError,
    PageGeometry,
    bounding_box,
    corners,
    from_canonical,
    px_to_pdf_point,
    to_canonical,
)

A4_WIDTH_PT = 612.0
A4_HEIGHT_PT = 792.0
DPI = 300


# Build a page whose deskew matrix is a real rotation about the image centre.
def page(angle: float = 0.0, rotation: int = 0, from_pdf: bool = True) -> PageGeometry:
    width, height = (2550, 3300) if rotation in (0, 180) else (3300, 2550)
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return PageGeometry(
        page=1,
        width_px=width,
        height_px=height,
        dpi=DPI,
        rotation_applied=rotation,
        deskew_angle=angle,
        deskew_matrix=tuple(matrix.flatten()),
        pdf_width_pt=A4_WIDTH_PT if from_pdf else None,
        pdf_height_pt=A4_HEIGHT_PT if from_pdf else None,
    ).validate()


@pytest.mark.parametrize("angle", [0.0, 0.4, -1.7, 3.0, -5.5])
def test_deskew_round_trip_returns_original_points_within_one_pixel(angle):
    original = corners((120, 340, 900, 260))

    restored = to_canonical(from_canonical(original, page(angle)), page(angle))

    for (x0, y0), (x1, y1) in zip(original, restored):
        assert abs(x0 - x1) < 1.0
        assert abs(y0 - y1) < 1.0


def test_identity_matrix_leaves_points_untouched():
    geom = PageGeometry(1, 100, 200, DPI, 0, 0.0, IDENTITY_MATRIX, None, None).validate()

    assert from_canonical(corners((5, 7, 10, 20)), geom) == corners((5, 7, 10, 20))


def test_bounding_box_of_a_tilted_quad_contains_every_corner():
    tilted = to_canonical(corners((400, 500, 300, 100)), page(angle=6.0))

    x, y, w, h = bounding_box(tilted)

    assert all(x <= px <= x + w for px, _ in tilted)
    assert all(y <= py <= y + h for _, py in tilted)


def test_bounding_box_of_a_straight_box_is_the_box_itself():
    assert bounding_box(corners((12, 34, 56, 78))) == (12, 34, 56, 78)


def test_px_to_pdf_point_scales_by_dpi_when_page_is_upright():
    assert px_to_pdf_point((10, 20, 100, 50), page(rotation=0)) == (2.4, 4.8, 24.0, 12.0)


@pytest.mark.parametrize(
    "rotation,expected",
    [
        (0, (2.4, 4.8, 24.0, 12.0)),
        (90, (4.8, 765.6, 12.0, 24.0)),
        (180, (585.6, 775.2, 24.0, 12.0)),
        (270, (595.2, 2.4, 12.0, 24.0)),
    ],
)
def test_px_to_pdf_point_undoes_every_quarter_turn(rotation, expected):
    result = px_to_pdf_point((10, 20, 100, 50), page(rotation=rotation))

    assert result == pytest.approx(expected)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_px_to_pdf_point_keeps_a_box_inside_the_page(rotation):
    geom = page(rotation=rotation)
    box = (0, 0, geom.width_px, geom.height_px)

    x, y, w, h = px_to_pdf_point(box, geom)

    assert (x, y) == pytest.approx((0.0, 0.0))
    assert (x + w, y + h) == pytest.approx((A4_WIDTH_PT, A4_HEIGHT_PT))


@pytest.mark.parametrize("rotation", [90, 270])
def test_px_to_pdf_point_swaps_width_and_height_on_a_quarter_turn(rotation):
    _, _, w, h = px_to_pdf_point((10, 20, 100, 50), page(rotation=rotation))

    assert (w, h) == pytest.approx((12.0, 24.0))


def test_px_to_pdf_point_refuses_an_image_source_instead_of_guessing():
    with pytest.raises(GeometryError, match="came from an image"):
        px_to_pdf_point((10, 20, 100, 50), page(from_pdf=False))


def test_validate_rejects_an_off_axis_rotation():
    with pytest.raises(GeometryError, match="rotation_applied"):
        PageGeometry(1, 100, 200, DPI, 45, 0.0, IDENTITY_MATRIX, None, None).validate()


def test_validate_rejects_a_matrix_that_is_not_two_by_three():
    with pytest.raises(GeometryError, match="6 values"):
        PageGeometry(1, 100, 200, DPI, 0, 0.0, (1.0, 0.0, 0.0), None, None).validate()


def test_validate_rejects_half_a_pdf_page_size():
    with pytest.raises(GeometryError, match="both be set or both None"):
        PageGeometry(1, 100, 200, DPI, 0, 0.0, IDENTITY_MATRIX, A4_WIDTH_PT, None).validate()


def test_to_canonical_reports_a_singular_matrix_instead_of_crashing():
    geom = PageGeometry(1, 100, 200, DPI, 0, 0.0, (0.0,) * 6, None, None).validate()

    with pytest.raises(GeometryError, match="not invertible"):
        to_canonical(corners((1, 2, 3, 4)), geom)


def test_corners_walks_clockwise_from_the_top_left():
    assert corners((10, 20, 30, 40)) == [(10, 20), (40, 20), (40, 60), (10, 60)]


def test_deskew_matrix_survives_a_numpy_round_trip():
    geom = page(angle=2.0)

    assert np.array(geom.deskew_matrix).reshape(2, 3).shape == (2, 3)
