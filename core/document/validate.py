"""Stage 5, last step: two checks with two different failure modes (§4.7).

validate_page runs inside run_page and only ever appends to `flags` - a
malformed table is a defect of the source page, not of this pipeline.
validate_document runs after reading_order is assigned (run_document,
orchestrate merge) and raises DocumentError - a duplicate reading_order or a
dangling caption_id/continues_from is a bug in this pipeline's own assembly,
not something to silently flag and ship.
"""

from __future__ import annotations

from lxml import etree

from .model import Document, DocumentError, Element, TableContent


def validate_page(elements: list[Element]) -> None:
    for element in elements:
        if isinstance(element.content, TableContent):
            _validate_table(element)


def _validate_table(element: Element) -> None:
    content = element.content
    try:
        tree = etree.fromstring(f"<root>{content.html}</root>")
    except etree.XMLSyntaxError:
        element.flags.append("invalid_html")
        return

    # Grid slots actually covered, counting a merged cell's rowspan*colspan -
    # comparing raw <td> count to n_rows*n_cols would flag every merged table
    # as a false mismatch.
    covered = sum(
        int(td.get("rowspan", 1)) * int(td.get("colspan", 1)) for td in tree.findall(".//td")
    )
    if covered != content.n_rows * content.n_cols:
        element.flags.append("cell_count_mismatch")


def validate_document(doc: Document) -> None:
    orders = [e.reading_order for e in doc.elements]
    if any(order == -1 for order in orders):
        raise DocumentError("reading_order is still -1 on at least one element")
    if len(set(orders)) != len(orders):
        raise DocumentError("reading_order has duplicate values")
    if sorted(orders) != list(range(len(orders))):
        raise DocumentError("reading_order is not dense over 0..n-1")

    ids = {e.id for e in doc.elements}
    for element in doc.elements:
        if element.caption_id is not None and element.caption_id not in ids:
            raise DocumentError(
                f"element {element.id} has caption_id {element.caption_id}, no such element"
            )
        if element.continues_from is not None and element.continues_from not in ids:
            raise DocumentError(
                f"element {element.id} has continues_from {element.continues_from}, no such element"
            )
