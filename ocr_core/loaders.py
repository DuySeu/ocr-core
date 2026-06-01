"""Input loading: image/PDF -> page images."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


class UnsupportedFormatError(Exception):
    """Raised when a file extension is not supported."""


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = IMAGE_EXTS | PDF_EXTS


@dataclass
class PageImage:
    page: int
    image: Image.Image


def load(path: str) -> list[PageImage]:
    ext = Path(path).suffix.lower()
    logger.debug("load %s (ext=%s)", path, ext)
    if ext in IMAGE_EXTS:
        return [PageImage(1, Image.open(path))]
    if ext in PDF_EXTS:
        from pdf2image import convert_from_path  # lazy: needs Poppler

        logger.debug("converting PDF pages: %s", path)
        return [PageImage(i, img) for i, img in enumerate(convert_from_path(path), 1)]
    raise UnsupportedFormatError(f"unsupported format {ext!r} for {path}")
