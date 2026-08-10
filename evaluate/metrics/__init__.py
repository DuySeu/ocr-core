"""The three metrics, each reading the same MatchResult list."""

from .layout import CategoryScore, score_layout
from .table import TableScore, score_tables
from .text import TextScore, score_pairs, score_plain_text, score_text

__all__ = [
    "CategoryScore",
    "TableScore",
    "TextScore",
    "score_layout",
    "score_pairs",
    "score_plain_text",
    "score_tables",
    "score_text",
]
