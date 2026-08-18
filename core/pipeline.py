"""Pipeline: run_page and run_document.

Six stages: load -> preprocess -> layout -> recognize -> assemble -> serialize.
Serialize is not called here; `core/serialize/` runs on the Document this
module hands back. `run_page` and `run_document` share `_process_page` (stages
2-5). `run_document` also returns preprocess images so callers can dump pages
that fail QA into a review folder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import layout, preprocess, recognize
from .config import Config, pipeline_version
from .document.assemble import assemble_page
from .document.link import link_table_continuations
from .document.model import Document, Element, PageError
from .document.reading_order import assign_reading_order
from .document.validate import validate_document, validate_page
from .geometry import PageGeometry
from .loader import PageImage, document_sha256, load, load_page

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageResult:
    geometry: PageGeometry | None  # None when the page failed at load
    elements: list[Element]
    image: Image.Image | None  # the image AFTER preprocess - None on error
    error: PageError | None


@dataclass(frozen=True)
class DocumentRun:
    """Whole-document OCR result plus preprocess images keyed by page number."""

    document: Document
    page_images: dict[int, Image.Image]


class _StageError(Exception):
    """Tags which stage inside _process_page raised, for PageError.stage."""

    def __init__(self, stage: str, cause: Exception):
        super().__init__(str(cause))
        self.stage = stage
        self.cause = cause


def run_page(path: str | Path, page: int, cfg: Config) -> PageResult:
    """Run stages 1-5 on one page; never raises (errors become PageResult.error)."""
    try:
        page_image = load_page(path, page, cfg.dpi)
    except Exception as e:
        return PageResult(
            None, [], None, PageError(page, "load", f"{type(e).__name__}: {e}")
        )

    try:
        elements, processed = _process_page(page_image, cfg)
    except _StageError as e:
        message = f"{type(e.cause).__name__}: {e.cause}"
        return PageResult(None, [], None, PageError(page, e.stage, message))

    return PageResult(processed.geometry, elements, processed.image, None)


def run_document(path: str | Path, cfg: Config) -> DocumentRun:
    """Run the full document pipeline and return Document plus page images.

    Args:
        path: PDF or image path.
        cfg: Pipeline config.

    Returns:
        DocumentRun with the assembled Document and a map of page number to
        preprocess image (only for pages that completed stages 2-5).
    """
    pages = load(path, cfg.dpi)

    elements_by_page: dict[int, list[Element]] = {}
    geometries: list[PageGeometry] = []
    page_images: dict[int, Image.Image] = {}
    errors: list[PageError] = []

    for page_image in pages:
        page_number = page_image.geometry.page
        try:
            elements, processed = _process_page(page_image, cfg)
        except _StageError as e:
            message = f"{type(e.cause).__name__}: {e.cause}"
            errors.append(PageError(page_number, e.stage, message))
            continue
        elements_by_page[page_number] = elements
        geometries.append(processed.geometry)
        page_images[page_number] = processed.image

    link_table_continuations(elements_by_page)
    all_elements = [
        element
        for page in sorted(elements_by_page)
        for element in elements_by_page[page]
    ]

    doc = Document(
        source=str(path),
        doc_sha256=document_sha256(path),
        pipeline_version=pipeline_version(cfg),
        pages=geometries,
        elements=all_elements,
        errors=errors,
    )
    assign_reading_order(doc)
    validate_document(doc)
    return DocumentRun(document=doc, page_images=page_images)


def _process_page(
    page_image: PageImage, cfg: Config
) -> tuple[list[Element], PageImage]:
    """Run stages 2-5 on one already-loaded page."""
    try:
        processed = preprocess.apply(page_image, cfg.preprocess_steps)
    except Exception as e:
        raise _StageError("preprocess", e) from e

    try:
        boxes = layout.detect(processed.image, cfg)
    except Exception as e:
        raise _StageError("layout", e) from e

    recognized = [
        recognize.recognize(processed.image, box, cfg) for box in boxes
    ]

    try:
        elements = assemble_page(recognized, processed.geometry)
    except Exception as e:
        raise _StageError("assemble", e) from e

    validate_page(elements)
    return elements, processed
