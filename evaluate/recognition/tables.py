"""Table scoring for the Recognition tier: TEDS over tables paired by content.

Tree edit distance under the PubTabNet cost model. Two normalizations are applied
before comparing, both deliberate: ``<th>`` collapses to ``<td>`` because no table
recognizer here distinguishes header cells reliably, and ``<thead>``/``<tbody>``
are dropped because they carry no structure the metric scores while the
page-spanning table splice would otherwise invent differences. Cell text goes
through ``normalize.strip_figures`` only, so an image or ``[hình: ...]`` in a cell
is dropped but tone placement is not canonicalized.

There are no boxes on either side, so tables are paired by content: greedily on
TEDS-Struct, then on full TEDS, then on index. TEDS is higher-is-better.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apted import APTED, Config
from lxml import etree, html
from rapidfuzz.distance import Levenshtein

from . import normalize

# Wrappers dropped from the tree; their children are lifted into the parent.
SKIP_TAGS = frozenset({"thead", "tbody", "tfoot"})
KEEP_TAGS = frozenset({"tr", "td", "th"})

# Candidate matrix size above which document-level pairing declines to run. A tree
# edit per candidate is affordable at the sizes real documents reach; a document with
# hundreds of tables on both sides is not, and a silent cap would read as a score.
MAX_PAIR_CANDIDATES = 2000


@dataclass
class TableNode:
    """One node of a table tree: a row, or a cell with its span and content."""

    tag: str
    colspan: int
    rowspan: int
    text: str
    children: list["TableNode"] = field(default_factory=list)


@dataclass(frozen=True)
class TablePair:
    """A predicted table matched to a gold table, with both scores that judged it."""

    predicted_index: int
    gold_index: int
    teds_struct: float
    teds: float


@dataclass(frozen=True)
class DocumentTableScore:
    """Table quality for one document, paired without boxes. Higher is better."""

    teds: float | None  # mean over matched pairs; None when none matched
    teds_struct: float | None
    n_matched: int
    n_gold: int
    n_pred: int
    table_recall: float | None  # n_matched / n_gold; None when there is nothing to divide
    note: str | None  # why pairing was skipped, when it was


class TableError(Exception):
    """Raised when an extracted table cannot be parsed, which the extractors never produce."""


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

    # An optimal path preferring insert+delete over rename can cost more than the
    # larger tree has nodes, so the raw ratio is clamped rather than left negative
    largest = max(_count_nodes(predicted), _count_nodes(gold))
    return max(0.0, 1.0 - distance / largest) if largest else 1.0


# Pair predicted tables to gold greedily, by structure and then by full score.
def pair_tables(
    predicted: list[TableNode], gold: list[TableNode], threshold: float
) -> tuple[list[TablePair], str | None]:
    # Decline rather than hang, and say so, when the candidate matrix is too large
    if len(predicted) * len(gold) > MAX_PAIR_CANDIDATES:
        return [], (
            f"pairing skipped: {len(predicted)} predicted x {len(gold)} gold tables "
            f"exceeds the {MAX_PAIR_CANDIDATES}-candidate cap"
        )

    # Score every candidate under both cost models before choosing any
    candidates = [
        TablePair(
            predicted_index=predicted_index,
            gold_index=gold_index,
            teds_struct=teds(predicted_tree, gold_tree, structure_only=True),
            teds=teds(predicted_tree, gold_tree),
        )
        for predicted_index, predicted_tree in enumerate(predicted)
        for gold_index, gold_tree in enumerate(gold)
    ]

    # Structure says which table is which; the full score separates same-shape tables,
    # which structure alone scores 1.0 for. Indices break what is left, so runs repeat.
    candidates.sort(
        key=lambda c: (-c.teds_struct, -c.teds, c.predicted_index, c.gold_index)
    )

    pairs: list[TablePair] = []
    taken_predicted: set[int] = set()
    taken_gold: set[int] = set()
    for candidate in candidates:
        # Sorted descending, so the first candidate under the floor ends the pass
        if candidate.teds_struct < threshold:
            break
        if candidate.predicted_index in taken_predicted:
            continue
        if candidate.gold_index in taken_gold:
            continue

        pairs.append(candidate)
        taken_predicted.add(candidate.predicted_index)
        taken_gold.add(candidate.gold_index)

    return pairs, None


# Score matched table pairs, carrying the counts that make the mean readable.
def score_table_pairs(
    pairs: list[TablePair],
    predicted: list[TableNode],
    gold: list[TableNode],
    note: str | None,
) -> DocumentTableScore:
    n_matched = len(pairs)

    # A pass that never ran measured nothing, and 0/n would read as a measured miss
    recall = n_matched / len(gold) if gold and note is None else None

    return DocumentTableScore(
        teds=sum(p.teds for p in pairs) / n_matched if n_matched else None,
        teds_struct=sum(p.teds_struct for p in pairs) / n_matched if n_matched else None,
        n_matched=n_matched,
        n_gold=len(gold),
        n_pred=len(predicted),
        table_recall=recall,
        note=note,
    )


# Pool every document's matched pairs into one corpus row, weighted by match count.
def pool_tables(scores: list[DocumentTableScore]) -> DocumentTableScore | None:
    if not scores:
        return None

    matched = sum(s.n_matched for s in scores)
    gold = sum(s.n_gold for s in scores)

    # Weight by matched count so a document with one table does not outweigh one with forty
    return DocumentTableScore(
        teds=sum(s.teds * s.n_matched for s in scores if s.teds is not None) / matched
        if matched
        else None,
        teds_struct=sum(s.teds_struct * s.n_matched for s in scores if s.teds_struct is not None)
        / matched
        if matched
        else None,
        n_matched=matched,
        n_gold=gold,
        n_pred=sum(s.n_pred for s in scores),
        table_recall=matched / gold if gold else None,
        note=None,
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
        text = "" if tag == "tr" else " ".join(normalize.strip_figures("".join(child.itertext())).split())
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
