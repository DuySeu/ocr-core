"""Configurable, ordered preprocessing steps."""
from __future__ import annotations

import logging

import cv2
import numpy as np
from PIL import Image

from .config import ConfigError

logger = logging.getLogger(__name__)


def _grayscale(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)


def _binarize(img: np.ndarray) -> np.ndarray:
    gray = _grayscale(img)
    _, out = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return out


def _deskew(img: np.ndarray) -> np.ndarray:
    gray = _grayscale(img)
    coords = np.column_stack(np.where(gray < 128))
    if coords.size == 0:
        return img
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.1:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


STEPS = {"grayscale": _grayscale, "deskew": _deskew, "binarize": _binarize}


def apply(image: Image.Image, steps: list[str]) -> Image.Image:
    arr = np.array(image.convert("RGB"))
    for name in steps:
        if name not in STEPS:
            raise ConfigError(f"unknown step {name!r}; valid: {sorted(STEPS)}")
        logger.debug("preprocess step: %s", name)
        arr = STEPS[name](arr)
    return Image.fromarray(arr)
