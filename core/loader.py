"""Input loading: image/PDF -> page images in the canonical coordinate frame.

Renders with pypdfium2 rather than pdf2image so there is no Poppler binary to
install. pdfium applies the page's /Rotate itself, both when reporting a page
size and when rendering, so the rendered pixels already are the canonical frame
(§5.1) — apart from deskew, which `preprocess` adds later.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from .geometry import IDENTITY_MATRIX, POINTS_PER_INCH, PageGeometry

logger = logging.getLogger(__name__)

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"})
PDF_EXTS = frozenset({".pdf"})
SUPPORTED_EXTS = IMAGE_EXTS | PDF_EXTS
QUARTER_TURNS = (90, 270)
SHA_CHUNK = 1 << 20  # 1 MiB


@dataclass(frozen=True)
class PageImage:
    """One rendered page plus the geometry needed to map it back to the source."""

    image: Image.Image
    geometry: PageGeometry


class UnsupportedFormatError(Exception):
    """Raised when a file extension is not one we can load."""


# Load an image or PDF into one rendered page per source page.
def load(path: str | Path, dpi: int = 300) -> list[PageImage]:
    source = Path(path)
    ext = source.suffix.lower()
    logger.debug("load %s (ext=%s, dpi=%d)", source, ext, dpi)

    # Collect (image, rotation, displayed page size) before building any geometry
    if ext in IMAGE_EXTS:
        rendered = [(Image.open(source).convert("RGB"), 0, None)]
    elif ext in PDF_EXTS:
        rendered = [
            (
                page.render(scale=dpi / POINTS_PER_INCH).to_pil().convert("RGB"),
                page.get_rotation(),
                page.get_size(),
            )
            for page in pdfium.PdfDocument(source)
        ]
    else:
        raise UnsupportedFormatError(f"unsupported format {ext!r} for {source}")

    pages = []
    for index, (image, rotation, displayed_pt) in enumerate(rendered, 1):
        # pdfium reports the displayed size, so swap back to the unrotated page
        if displayed_pt is None:
            width_pt = height_pt = None
        elif rotation in QUARTER_TURNS:
            height_pt, width_pt = displayed_pt
        else:
            width_pt, height_pt = displayed_pt

        geometry = PageGeometry(
            page=index,
            width_px=image.width,
            height_px=image.height,
            dpi=dpi,
            rotation_applied=rotation,
            deskew_angle=0.0,
            deskew_matrix=IDENTITY_MATRIX,
            pdf_width_pt=width_pt,
            pdf_height_pt=height_pt,
        ).validate()
        pages.append(PageImage(image, geometry))

    logger.info("loaded %d page(s) from %s", len(pages), source)
    return pages


# Render exactly one page, so a worker that only has (path, page) never re-renders
# the whole document to get it (§4.1 - the cost load_page exists to avoid).
def load_page(path: str | Path, page: int, dpi: int = 300) -> PageImage:
    source = Path(path)
    ext = source.suffix.lower()

    if ext in IMAGE_EXTS:
        if page != 1:
            raise UnsupportedFormatError(f"{source} is a single-page image; got page={page}")
        image, rotation, displayed_pt = Image.open(source).convert("RGB"), 0, None
    elif ext in PDF_EXTS:
        pdf = pdfium.PdfDocument(source)
        pdf_page = pdf[page - 1]
        image = pdf_page.render(scale=dpi / POINTS_PER_INCH).to_pil().convert("RGB")
        rotation, displayed_pt = pdf_page.get_rotation(), pdf_page.get_size()
    else:
        raise UnsupportedFormatError(f"unsupported format {ext!r} for {source}")

    if displayed_pt is None:
        width_pt = height_pt = None
    elif rotation in QUARTER_TURNS:
        height_pt, width_pt = displayed_pt
    else:
        width_pt, height_pt = displayed_pt

    geometry = PageGeometry(
        page=page,
        width_px=image.width,
        height_px=image.height,
        dpi=dpi,
        rotation_applied=rotation,
        deskew_angle=0.0,
        deskew_matrix=IDENTITY_MATRIX,
        pdf_width_pt=width_pt,
        pdf_height_pt=height_pt,
    ).validate()
    return PageImage(image, geometry)


# Count pages without rendering any of them (§4.1 - orchestrate needs this before
# it can queue per-page work, and rendering at 300 DPI just to count is the
# exact cost load_page/page_count exist to avoid).
def page_count(path: str | Path) -> int:
    source = Path(path)
    ext = source.suffix.lower()
    if ext in IMAGE_EXTS:
        return 1
    if ext in PDF_EXTS:
        return len(pdfium.PdfDocument(source))
    raise UnsupportedFormatError(f"unsupported format {ext!r} for {source}")


# Hash a source file so its outputs can be addressed by content.
def document_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(SHA_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
