"""Configurable, ordered preprocessing steps that keep geometry recoverable.

Every step returns the image plus the geometry it produced, because two of them
move pixels: `orientation` adds a quarter turn (which stays inside the canonical
frame, §5.1) and `deskew` records the affine needed to map detections back out
of the deskewed image.

`binarize` and `grayscale` are still here but are no longer in the default set —
they measurably hurt PaddleOCR, which is now the default engine.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from dataclasses import replace
from PIL import Image

from .geometry import IDENTITY_MATRIX, PageGeometry
from .loader import PageImage

logger = logging.getLogger(__name__)

DESKEW_LIMIT_DEG = 15.0  # beyond this the estimate is noise, not a skew
MIN_DESKEW_DEG = 0.1  # below this a warp costs quality and buys nothing
DENOISE_KERNEL = 3
INK_THRESHOLD = 128


class PreprocessError(Exception):
    """Raised when a preprocessing step is not registered or cannot run."""


# Run the named steps in order over one page.
def apply(page: PageImage, steps: list[str]) -> PageImage:
    for name in steps:
        if name not in STEPS:
            raise PreprocessError(f"unknown step {name!r}; valid: {sorted(STEPS)}")
        logger.debug("page %d: preprocess step %s", page.geometry.page, name)
        page = STEPS[name](page)
    return page


# Rotate a page upright in quarter turns, folding the turn into the canonical frame.
def orientation(page: PageImage) -> PageImage:
    try:
        import pytesseract  # lazy: only this opt-in step needs Tesseract
    except ImportError as e:
        raise PreprocessError(
            "step 'orientation' needs pytesseract: pip install pytesseract"
        ) from e

    # OSD is the only option that tells 90 apart from 270; projection variance
    # cannot, and guessing wrong turns a readable page upside down
    try:
        osd = pytesseract.image_to_osd(page.image, output_type=pytesseract.Output.DICT)
        turns = int(osd["rotate"]) % 360
    except pytesseract.TesseractNotFoundError as e:
        raise PreprocessError(
            "step 'orientation' needs the Tesseract binary: brew install tesseract"
        ) from e
    except pytesseract.TesseractError as e:
        # Too little text to judge — leaving the page alone beats a coin flip
        logger.warning("page %d: orientation undetermined, left as-is (%s)", page.geometry.page, e)
        return page

    if turns == 0:
        return page

    # PIL rotates counter-clockwise; our rotation convention is clockwise
    rotated = page.image.rotate(-turns, expand=True)
    total = (page.geometry.rotation_applied + turns) % 360
    logger.info("page %d: rotated %d deg to %d", page.geometry.page, turns, total)
    return PageImage(
        rotated,
        replace(
            page.geometry,
            width_px=rotated.width,
            height_px=rotated.height,
            rotation_applied=total,
        ),
    )


# Straighten a small skew and record the affine that did it.
def deskew(page: PageImage) -> PageImage:
    # Estimate the skew from the minimum-area box around the ink
    array = np.array(page.image)
    gray = array if array.ndim == 2 else cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    ink = np.column_stack(np.where(gray < INK_THRESHOLD))
    if ink.size == 0:
        return page

    angle = cv2.minAreaRect(ink)[-1]
    angle = -(90 + angle) if angle < -45 else -angle

    # A large estimate means the box latched onto layout, not baselines
    if abs(angle) > DESKEW_LIMIT_DEG or abs(angle) < MIN_DESKEW_DEG:
        return page

    height, width = array.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    warped = cv2.warpAffine(
        array, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    logger.debug("page %d: deskewed %.2f deg", page.geometry.page, angle)
    return PageImage(
        Image.fromarray(warped),
        replace(
            page.geometry,
            deskew_angle=angle,
            deskew_matrix=tuple(float(v) for v in matrix.flatten()),
        ),
    )


# Remove speckle without moving any pixel.
def denoise(page: PageImage) -> PageImage:
    array = cv2.medianBlur(np.array(page.image), DENOISE_KERNEL)
    return PageImage(Image.fromarray(array), page.geometry)


# Drop colour without moving any pixel.
def grayscale(page: PageImage) -> PageImage:
    array = np.array(page.image)
    if array.ndim == 2:
        return page
    return PageImage(Image.fromarray(cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)), page.geometry)


# Threshold to black and white without moving any pixel.
def binarize(page: PageImage) -> PageImage:
    array = np.array(page.image)
    gray = array if array.ndim == 2 else cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    _, thresholded = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return PageImage(Image.fromarray(thresholded), page.geometry)


# Registry has to follow the step functions it points at.
STEPS = {
    "orientation": orientation,
    "deskew": deskew,
    "denoise": denoise,
    "grayscale": grayscale,
    "binarize": binarize,
}
