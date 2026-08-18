"""Stage 5, cross-page linking.

link_table_continuations is the only half implemented: it needs elements from
two pages at once, so it runs after every page in a document has been
assembled, not inside run_page. Caption-linking is a stub - with only "text"
and "table" categories ever produced by this pipeline, no "caption" element
can exist to link (§4.7); writing the real rule now would be dead code.
"""

from __future__ import annotations

from .model import Element, TableContent

EDGE_TOLERANCE = 0.02  # 2% of the wider of the two tables' widths (§4.7)


# Mark a table that runs from one page into the next: same column count, left
# and right edges matching within 2%. Never merges elements - one Element
# keeps one page/bbox; the relation lives entirely in continues_from/flags.
def link_table_continuations(elements_by_page: dict[int, list[Element]]) -> None:
    pages = sorted(elements_by_page)
    for page, next_page in zip(pages, pages[1:]):
        if next_page != page + 1:
            continue
        head = _last_table(elements_by_page[page])
        tail = _first_table(elements_by_page[next_page])
        if head is not None and tail is not None and _continues(head, tail):
            head.flags.append("table_continues")
            tail.continues_from = head.id
            tail.render = "inlined"


# Caption linking: no-op until a category other than text/table exists (§4.7).
def link_captions(elements_by_page: dict[int, list[Element]]) -> None:
    pass


def _last_table(elements: list[Element]) -> Element | None:
    tables = [e for e in elements if e.category == "table"]
    return tables[-1] if tables else None


def _first_table(elements: list[Element]) -> Element | None:
    tables = [e for e in elements if e.category == "table"]
    return tables[0] if tables else None


def _continues(head: Element, tail: Element) -> bool:
    if not isinstance(head.content, TableContent) or not isinstance(tail.content, TableContent):
        return False
    if head.content.n_cols != tail.content.n_cols:
        return False

    hx0, _, hw, _ = head.bbox
    tx0, _, tw, _ = tail.bbox
    reference = max(hw, tw)
    if reference == 0:
        return False

    left_off = abs(hx0 - tx0) / reference
    right_off = abs((hx0 + hw) - (tx0 + tw)) / reference
    return left_off <= EDGE_TOLERANCE and right_off <= EDGE_TOLERANCE
