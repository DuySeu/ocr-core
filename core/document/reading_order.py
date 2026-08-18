"""Stage 5: reading order, dense and unique across the whole document (§4.1).

Per page: `flow` elements are ordered by recursive XY-cut over their canonical
bboxes (so a two-column page reads column 1 top-to-bottom, then column 2, not
row-by-row); `inlined`/`aside` elements follow, sorted by top edge. Pages run
in page order. `run_page` always leaves `reading_order` at -1; this is the
function that sets the real value, called from `run_document` and (in phase 2)
`orchestrate merge`.
"""

from __future__ import annotations

from .model import Document, Element

MIN_GAP_PX = 8  # a whitespace band narrower than this isn't a real column/row gap


def assign_reading_order(doc: Document) -> None:
    order = 0
    for page in sorted({e.page for e in doc.elements}):
        page_elements = [e for e in doc.elements if e.page == page]
        flow = [e for e in page_elements if e.render == "flow"]
        rest = sorted((e for e in page_elements if e.render != "flow"), key=lambda e: e.bbox[1])

        for element in _xy_cut(flow) + rest:
            element.reading_order = order
            order += 1


# Recursively split on the widest clean whitespace gap: a vertical gap first
# (column split, so a full column reads before the next starts), else a
# horizontal gap (row split); no clean gap falls back to top-to-bottom,
# left-to-right.
def _xy_cut(elements: list[Element]) -> list[Element]:
    if len(elements) <= 1:
        return list(elements)

    for axis in (0, 1):  # 0 = x (column split), 1 = y (row split)
        cut = _widest_gap(elements, axis)
        if cut is None:
            continue
        before = [e for e in elements if e.bbox[axis] + e.bbox[axis + 2] <= cut]
        after = [e for e in elements if e.bbox[axis] >= cut]
        if before and after and len(before) + len(after) == len(elements):
            return _xy_cut(before) + _xy_cut(after)

    return sorted(elements, key=lambda e: (e.bbox[1], e.bbox[0]))


# The midpoint of the widest whitespace band that spans every element's extent
# on one axis, or None if no element leaves a clean gap on that axis.
def _widest_gap(elements: list[Element], axis: int) -> int | None:
    spans = sorted((e.bbox[axis], e.bbox[axis] + e.bbox[axis + 2]) for e in elements)
    frontier = spans[0][1]
    best_gap, best_cut = 0, None
    for start, end in spans[1:]:
        gap = start - frontier
        if gap >= MIN_GAP_PX and gap > best_gap:
            best_gap, best_cut = gap, (frontier + start) // 2
        frontier = max(frontier, end)
    return best_cut
