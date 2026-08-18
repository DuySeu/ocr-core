"""Table recognizer: OCRs the cell grid stage 3 already found, never re-detects it.

Detecting the grid twice on one page costs double and can disagree with
itself; the grid rides along on ``LayoutBox.cells`` from ``layout/table_cv.py``.
"""

from __future__ import annotations

from html import escape

from PIL import Image

from .base import RecognizedBox
from ..document.model import TableContent
from ..engines import get_engine


def recognize_table(image: Image.Image, box, cfg) -> RecognizedBox:
    if cfg.table == "none":
        return RecognizedBox(
            category="table",
            bbox=box.bbox,
            layout_score=box.layout_score,
            content=None,
            rec_score=None,
            logprob=None,
            flags=["provider_disabled"],
        )

    engine = get_engine(cfg.engine)
    cells = box.cells or []
    texts = {}
    for cell in cells:
        x, y, w, h = cell.box
        crop = image.crop((x, y, x + w, y + h))
        texts[(cell.r0, cell.c0)] = " ".join(engine.recognize_text(crop, cfg.langs, psm=6).split())

    content = TableContent(
        html=_build_html(cells, texts),
        n_rows=box.n_rows,  # from the detector, never re-derived from cells (§4.3)
        n_cols=box.n_cols,
        cell_boxes=[cell.box for cell in cells],
    )
    return RecognizedBox(
        category="table",
        bbox=box.bbox,
        layout_score=box.layout_score,
        content=content,
        rec_score=None,  # bậc 3: recognize_text() gives back a bare string, no confidence
        logprob=None,
        flags=[],
    )


# Build <table><tbody>...</tbody></table> with rowspan/colspan for merged cells (§4.3).
def _build_html(cells: list, texts: dict[tuple[int, int], str]) -> str:
    ordered = sorted(cells, key=lambda c: (c.r0, c.c0))
    occupied: set[tuple[int, int]] = set()  # (row, col) already covered by an earlier rowspan
    rows: dict[int, list[str]] = {}

    for cell in ordered:
        if (cell.r0, cell.c0) in occupied:
            continue
        rowspan, colspan = cell.r1 - cell.r0, cell.c1 - cell.c0
        attrs = ""
        if rowspan > 1:
            attrs += f' rowspan="{rowspan}"'
        if colspan > 1:
            attrs += f' colspan="{colspan}"'
        text = escape(texts.get((cell.r0, cell.c0), ""))
        rows.setdefault(cell.r0, []).append(f"<td{attrs}>{text}</td>")
        for r in range(cell.r0 + 1, cell.r1):  # mark the rows this cell's rowspan covers
            occupied.add((r, cell.c0))

    body = "".join(f"<tr>{''.join(tds)}</tr>" for _, tds in sorted(rows.items()))
    return f"<table><tbody>{body}</tbody></table>"
