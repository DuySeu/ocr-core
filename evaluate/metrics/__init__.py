"""The metrics: layout, text and table, the first two reading the same MatchResult list."""

from .layout import CategoryScore, score_layout
from .table import (
    DocumentTableScore,
    TableError,
    TableNode,
    TablePair,
    TableScore,
    pair_tables,
    parse_table,
    score_table_pairs,
    score_tables,
)
from .text import TextScore, score_pairs, score_plain_text, score_text

__all__ = [
    "CategoryScore",
    "DocumentTableScore",
    "TableError",
    "TableNode",
    "TablePair",
    "TableScore",
    "TextScore",
    "pair_tables",
    "parse_table",
    "score_layout",
    "score_pairs",
    "score_plain_text",
    "score_table_pairs",
    "score_tables",
    "score_text",
]
