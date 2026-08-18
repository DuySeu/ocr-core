"""The one representation both serializers read. Pure data, no provider imports.

Written so `.md` and COCO come from a single OCR pass: every element keeps its
geometry even when recognition produced nothing, and the uncertainty signal
follows a three-tier rule — log-prob if the provider gives one, else a 0..1
confidence, else neither field is emitted at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..geometry import PageGeometry

DOCLAYNET_CLASSES = (
    "caption",
    "footnote",
    "formula",
    "list-item",
    "page-footer",
    "page-header",
    "picture",
    "section-header",
    "table",
    "text",
    "title",
)

ASIDE_CLASSES = frozenset({"page-header", "page-footer", "footnote"})

FLAGS = (
    "recognize_failed",  # recognizer raised; content is None
    "provider_disabled",  # provider switched off by config; not an error
    "invalid_html",  # lxml could not parse TableContent.html
    "invalid_latex",  # the LaTeX parser rejected FormulaContent.latex
    "cell_count_mismatch",  # cells in the HTML disagree with cell_boxes
    "table_continues",  # this table runs on into the next page
)

RENDER_MODES = ("flow", "aside", "inlined")

ELEMENTS_PER_PAGE = 10_000  # hard ceiling: Element.id is page * this + index


@dataclass(frozen=True)
class LogProb:
    """Per-token log-probability, aggregated over one element."""

    sum: float
    mean: float
    min: float
    n_tokens: int


@dataclass(frozen=True)
class TextLine:
    text: str  # current text, edited if a reviewer fixed it
    text_ocr: str  # original OCR text, never overwritten
    polygon: list[tuple[float, float]]  # canonical frame, quadrilateral - source of truth for position
    bbox: tuple[int, int, int, int]  # canonical frame, convex-hull rectangle of polygon
    confidence: float | None  # 0..1, None when the engine reports none


@dataclass(frozen=True)
class TextContent:
    text: str  # joins TextLine.text with "\n"; derived, rebuilt by serde.py on load
    lines: list[TextLine] = field(default_factory=list)


@dataclass(frozen=True)
class TableContent:
    html: str  # carries rowspan/colspan, which GFM tables cannot
    n_rows: int
    n_cols: int
    cell_boxes: list[tuple[int, int, int, int]]  # canonical frame, same as Element.bbox


@dataclass(frozen=True)
class FormulaContent:
    latex: str


@dataclass(frozen=True)
class FigureContent:
    path: str  # relative to the document's output directory


Content = TextContent | TableContent | FormulaContent | FigureContent


@dataclass
class Element:
    """One detected object on one page, with whatever recognition produced."""

    id: int  # page * ELEMENTS_PER_PAGE + index within page; stable per page
    page: int  # real page number, matches PageGeometry.page
    category: str  # one of DOCLAYNET_CLASSES
    bbox: tuple[int, int, int, int]  # canonical frame
    reading_order: int  # dense and unique across the document, never None
    render: str = "flow"  # one of RENDER_MODES
    polygon: list[tuple[float, float]] | None = None
    layout_score: float | None = None  # 0..1, detector confidence
    content: Content | None = None
    logprob: LogProb | None = None  # tier 1
    rec_score: float | None = None  # tier 2, 0..1
    caption_id: int | None = None
    continues_from: int | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class PageError:
    """A page that failed, kept so it cannot vanish without a trace."""

    page: int
    stage: str  # "load" | "preprocess" | "layout" | "assemble"
    message: str  # "<ErrorType>: <message>"


@dataclass
class Document:
    """Everything one source file produced, ready for either serializer."""

    source: str
    doc_sha256: str
    pipeline_version: str
    pages: list[PageGeometry] = field(default_factory=list)  # successful pages only
    elements: list[Element] = field(default_factory=list)
    errors: list[PageError] = field(default_factory=list)


class DocumentError(Exception):
    """Raised when a document cannot be assembled into a valid state."""


# Compute the stable per-page id for the index-th element of a page.
def element_id(page: int, index: int) -> int:
    if not 0 <= index < ELEMENTS_PER_PAGE:
        raise DocumentError(
            f"page {page} has more than {ELEMENTS_PER_PAGE} elements; "
            f"ids would collide and corrupt the COCO annotation ids"
        )
    return page * ELEMENTS_PER_PAGE + index


# Decide where an element is rendered: in the flow, at the end, or inside a parent.
def render_mode(category: str, is_linked_caption: bool, continues_from: int | None) -> str:
    if is_linked_caption:
        return "inlined"
    if continues_from is not None:
        return "inlined"
    if category in ASIDE_CLASSES:
        return "aside"
    return "flow"
