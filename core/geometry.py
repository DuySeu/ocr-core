"""Page coordinate system: canonical frame, deskew round-trip, PDF mapping.

The canonical frame is pixels of the page rendered at ``dpi``, AFTER the
0/90/180/270 rotation, BEFORE deskew. Rotation is inside the frame because it
is a lossless quarter turn applied at render time, so ``width_px``/``height_px``
match the image a detector actually sees. Deskew is outside because it is a
small interpolating rotation that differs per page.

Every bbox stored on a ``document.model.Element`` lives in this one frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

import numpy as np

VALID_ROTATIONS = (0, 90, 180, 270)
POINTS_PER_INCH = 72.0
IDENTITY_MATRIX = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)  # row-major 2x3


@dataclass(frozen=True)
class PageGeometry:
    """Everything needed to map a page's pixels back to the source document."""

    page: int  # real 1-based page number, never a list index
    width_px: int
    height_px: int
    dpi: int
    rotation_applied: int  # clockwise, same convention as PDF /Rotate
    deskew_angle: float  # degrees
    deskew_matrix: tuple[float, ...]  # row-major 2x3, canonical -> deskewed
    pdf_width_pt: float | None  # page size BEFORE rotation; None for images
    pdf_height_pt: float | None

    def validate(self) -> "PageGeometry":
        if self.rotation_applied not in VALID_ROTATIONS:
            raise GeometryError(
                f"rotation_applied must be one of {VALID_ROTATIONS}, "
                f"got {self.rotation_applied!r}"
            )
        if len(self.deskew_matrix) != 6:
            raise GeometryError(
                f"deskew_matrix must have 6 values, got {len(self.deskew_matrix)}"
            )
        if (self.pdf_width_pt is None) != (self.pdf_height_pt is None):
            raise GeometryError("pdf_width_pt and pdf_height_pt must both be set or both None")
        return self


class GeometryError(Exception):
    """Raised when a coordinate conversion is not defined for a page."""


# Expand a box into its four corner points, clockwise from the top-left.
def corners(box: tuple[int, int, int, int]) -> list[tuple[float, float]]:
    x, y, w, h = box
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


# Collapse any polygon into the smallest integer box that contains it.
def bounding_box(polygon: list[tuple[float, float]]) -> tuple[int, int, int, int]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]

    # Floor the near edges and ceil the far ones so no corner falls outside
    x0, y0 = floor(min(xs)), floor(min(ys))
    x1, y1 = ceil(max(xs)), ceil(max(ys))
    return (x0, y0, x1 - x0, y1 - y0)


# Map a polygon from the canonical frame into the deskewed image.
def from_canonical(
    polygon: list[tuple[float, float]], geom: PageGeometry
) -> list[tuple[float, float]]:
    forward = np.array(geom.deskew_matrix, dtype=float).reshape(2, 3)
    points = np.array([(p[0], p[1], 1.0) for p in polygon], dtype=float)
    return [(float(x), float(y)) for x, y in points @ forward.T]


# Map a polygon from the deskewed image back into the canonical frame.
def to_canonical(
    polygon: list[tuple[float, float]], geom: PageGeometry
) -> list[tuple[float, float]]:
    # Invert the affine in homogeneous form so the round trip is exact
    forward = np.array(geom.deskew_matrix, dtype=float).reshape(2, 3)
    try:
        inverse = np.linalg.inv(np.vstack([forward, [0.0, 0.0, 1.0]]))[:2]
    except np.linalg.LinAlgError as e:
        raise GeometryError(f"deskew_matrix is not invertible: {geom.deskew_matrix}") from e

    points = np.array([(p[0], p[1], 1.0) for p in polygon], dtype=float)
    return [(float(x), float(y)) for x, y in points @ inverse.T]


# Map a canonical-frame box to points on the original PDF page.
def px_to_pdf_point(
    box: tuple[int, int, int, int], geom: PageGeometry
) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) in points, image convention: origin top-left, y down.

    Undoes the render scale and the clockwise page rotation. PDF-only: an image
    source has no page size to rotate against.
    """
    if geom.pdf_width_pt is None or geom.pdf_height_pt is None:
        raise GeometryError(
            f"px_to_pdf_point needs a PDF page size; page {geom.page} came from an image"
        )

    # Scale pixels to points, then undo the quarter turn against the unrotated page
    scale = POINTS_PER_INCH / geom.dpi
    x, y, w, h = (v * scale for v in box)
    page_w, page_h = geom.pdf_width_pt, geom.pdf_height_pt

    if geom.rotation_applied == 0:
        return (x, y, w, h)
    if geom.rotation_applied == 90:
        return (y, page_h - (x + w), h, w)
    if geom.rotation_applied == 180:
        return (page_w - (x + w), page_h - (y + h), w, h)
    return (page_w - (y + h), x, h, w)  # 270
