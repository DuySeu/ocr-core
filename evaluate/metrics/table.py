"""Stage 4 table scoring: TEDS and TEDS-Struct over matched table elements.

Tree edit distance under the PubTabNet cost model. Two normalizations are applied
before comparing, both deliberate: ``<th>`` collapses to ``<td>`` because no table
recognizer here distinguishes header cells reliably, and ``<thead>``/``<tbody>``
are dropped because they carry no structure the metric scores while the
page-spanning table splice would otherwise invent differences.

TEDS is higher-is-better, unlike CER and WER.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apted import APTED, Config
from lxml import etree, html
from rapidfuzz.distance import Levenshtein

from ..matching import MatchResult

TABLE_CATEGORY = "table"

# Wrappers dropped from the tree; their children are lifted into the parent.
SKIP_TAGS = frozenset({"thead", "tbody", "tfoot"})
KEEP_TAGS = frozenset({"tr", "td", "th"})


@dataclass
class TableNode:
    """One node of a table tree: a row, or a cell with its span and content."""

    tag: str
    colspan: int
    rowspan: int
    text: str
    children: list["TableNode"] = field(default_factory=list)


@dataclass(frozen=True)
class TableScore:
    """Table structure quality. Higher is better; 1.0 is an exact match."""

    n_tables: int
    n_unparseable: int  # predictions with missing or unusable HTML, scored 0.0
    teds: float | None
    teds_struct: float | None
    unparseable_ids: list[int]


class TableError(Exception):
    """Raised when ground-truth table HTML is missing or unparseable."""


class TedsConfig(Config):
    """PubTabNet cost model: structural mismatch costs 1, cell text costs its distance."""

    # Cell similarity is fractional, so integer costs would silently truncate it
    valuecls = float

    def __init__(self, structure_only: bool = False) -> None:
        self.structure_only = structure_only

    def rename(self, node1: TableNode, node2: TableNode) -> float:
        if node1.tag != node2.tag:
            return 1.0
        if (node1.colspan, node1.rowspan) != (node2.colspan, node2.rowspan):
            return 1.0
        if self.structure_only or node1.tag != "td" or node1.text == node2.text:
            return 0.0
        return Levenshtein.normalized_distance(node1.text, node2.text)


# Parse table markup into a comparable tree, or None if it holds no usable table.
def parse_table(markup: str) -> TableNode | None:
    if not markup or not markup.strip():
        return None

    try:
        root = html.fromstring(markup)
    except (etree.ParserError, etree.XMLSyntaxError, ValueError):
        return None

    table = root if root.tag == "table" else root.find(".//table")
    if table is None:
        return None

    return TableNode(tag="table", colspan=1, rowspan=1, text="", children=_child_nodes(table))


# Score one predicted table tree against gold, normalized to [0,1].
def teds(predicted: TableNode, gold: TableNode, structure_only: bool = False) -> float:
    distance = APTED(predicted, gold, TedsConfig(structure_only)).compute_edit_distance()

    largest = max(_count_nodes(predicted), _count_nodes(gold))
    return 1.0 - distance / largest if largest else 1.0


# Score every matched table under both the full and structure-only cost models.
def score_tables(results: list[MatchResult]) -> TableScore:
    full: list[float] = []
    structural: list[float] = []
    unparseable_ids: list[int] = []

    for result in results:
        for match in result.matches:
            if match.gold.category != TABLE_CATEGORY:
                continue

            # Broken gold is an annotation defect: fail loudly rather than blame the model
            gold_tree = parse_table(match.gold.html or "")
            if gold_tree is None:
                raise TableError(
                    f"gold table element {match.gold.id} on page {match.gold.page} "
                    "has missing or unparseable html"
                )

            # Missing or unusable predicted HTML scores zero and is named in the report
            predicted_tree = parse_table(match.predicted.html or "")
            if predicted_tree is None:
                unparseable_ids.append(match.predicted.id)
                full.append(0.0)
                structural.append(0.0)
                continue

            full.append(teds(predicted_tree, gold_tree))
            structural.append(teds(predicted_tree, gold_tree, structure_only=True))

    return TableScore(
        n_tables=len(full),
        n_unparseable=len(unparseable_ids),
        teds=sum(full) / len(full) if full else None,
        teds_struct=sum(structural) / len(structural) if structural else None,
        unparseable_ids=unparseable_ids,
    )


# Build child nodes for one element, lifting wrapper tags and folding th into td.
# style: keep — recursive descent over the table tree; it cannot be inlined.
def _child_nodes(element: etree._Element) -> list[TableNode]:
    nodes: list[TableNode] = []
    for child in element:
        # Comments and processing instructions carry a callable tag, not a string
        if not isinstance(child.tag, str):
            continue

        tag = child.tag.lower()
        if tag in SKIP_TAGS:
            nodes.extend(_child_nodes(child))
            continue
        if tag not in KEEP_TAGS:
            continue

        # Rows hold no text of their own; cell text is whitespace-flattened
        text = "" if tag == "tr" else " ".join("".join(child.itertext()).split())
        nodes.append(
            TableNode(
                tag="td" if tag == "th" else tag,
                colspan=_span(child.get("colspan")),
                rowspan=_span(child.get("rowspan")),
                text=text,
                children=_child_nodes(child),
            )
        )

    return nodes


# Count the nodes in a tree, which is the TEDS normalizer.
# style: keep — recursive; called for both trees in teds().
def _count_nodes(node: TableNode) -> int:
    return 1 + sum(_count_nodes(child) for child in node.children)


# Read a span attribute, treating anything non-numeric as the default 1.
# style: keep — called for colspan and rowspan on every cell.
def _span(raw: str | None) -> int:
    try:
        return max(1, int(raw)) if raw is not None else 1
    except ValueError:
        return 1
