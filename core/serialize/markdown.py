"""Serialize a Document to Markdown for retrieval, with traceable anchors.

One sort key, two positions: `flow` elements where they read, `aside` elements
at the end. `inlined` elements appear in neither — they were already rendered
inside a parent's block. Every element is emitted exactly once, so the anchor
count equals the number of non-inlined elements.
"""

from __future__ import annotations

from ..document.model import Document, Element, FigureContent, FormulaContent, TableContent

ASIDE_MARKER = "<!-- ann-aside -->"
HEADING_PREFIX = {"title": "#", "section-header": "##"}
CLOSING_TBODY = "</tbody>"
CLOSING_TABLE = "</table>"


# Render a document to a Markdown string.
def to_markdown(doc: Document) -> str:
    by_id = {e.id: e for e in doc.elements}
    ordered = sorted(doc.elements, key=lambda e: e.reading_order)

    # Group every continuation part under the head of its chain
    continuations: dict[int, list[Element]] = {}
    for element in ordered:
        if element.continues_from is None:
            continue
        head, seen = element, {element.id}
        while head.continues_from is not None and head.continues_from not in seen:
            seen.add(head.continues_from)
            parent = by_id.get(head.continues_from)
            if parent is None:
                break
            head = parent
        continuations.setdefault(head.id, []).append(element)

    flow, asides = [], []
    for element in ordered:
        if element.render == "flow":
            flow.append(_block(element, by_id, continuations))
        elif element.render == "aside":
            asides.append(_block(element, by_id, continuations))

    blocks = flow + ([ASIDE_MARKER, *asides] if asides else [])
    return "\n\n".join(blocks) + "\n"


# Render one element as an anchored block, absorbing anything inlined into it.
# style: keep — 41 lines that would push to_markdown past 60, sharing no locals with its loop.
def _block(
    element: Element, by_id: dict[int, Element], continuations: dict[int, list[Element]]
) -> str:
    # An element with no content keeps its anchor so its position survives
    if element.content is None:
        reason = next((f for f in element.flags if f.endswith(("_failed", "_disabled"))), "empty")
        return f"<!-- ann:{element.id} {reason} -->"

    # Pull in the linked caption's text, if this element has one
    linked = by_id.get(element.caption_id) if element.caption_id is not None else None
    caption = getattr(linked.content, "text", "") if linked and linked.content else ""

    content = element.content
    if isinstance(content, TableContent):
        # Splice the rows of every continuation part into this table's body
        rows = ""
        for part in continuations.get(element.id, []):
            if not isinstance(part.content, TableContent):
                continue
            start = part.content.html.find("<tr")
            end = part.content.html.rfind("</tr>")
            if start >= 0 and end >= 0:
                rows += part.content.html[start : end + len("</tr>")]

        html = content.html
        if rows:
            closing = CLOSING_TBODY if CLOSING_TBODY in html else CLOSING_TABLE
            html = html.replace(closing, rows + closing, 1)
        body = f"{html}\n\n{caption}" if caption else html

    elif isinstance(content, FigureContent):
        body = f"![{caption}]({content.path})"
    elif isinstance(content, FormulaContent):
        body = f"$$\n{content.latex}\n$$"
    elif element.category in HEADING_PREFIX:
        body = f"{HEADING_PREFIX[element.category]} {content.text}"
    elif element.category == "list-item":
        body = f"- {content.text}"
    else:
        body = content.text

    return f"<!-- ann:{element.id} -->\n{body}"
