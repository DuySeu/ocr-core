"""Tier 2, Recognition: WER and TEDS of predicted markdown against the GT dataset.

Input is a directory of predicted ``<doc_id>.md`` files from any engine, searched
recursively, and a ground-truth dataset (``ground_truth.load_dataset``). Documents
pair by filename stem. Anything unpaired on either side is named in the report
rather than dropped: a silent drop and a perfect score look identical in a total.
"""

from __future__ import annotations

from pathlib import Path

from .. import ground_truth
from ..table_extract import extract_html_tables
from .report import DocumentResult, RecognitionReport, write_report
from .tables import (
    TableError,
    TableNode,
    pair_tables,
    parse_table,
    pool_tables,
    score_table_pairs,
)
from .wer import pool_wer, score_wer

__all__ = ["PairingError", "TableError", "run", "write_report"]

# Everything below this marker in a core-pipeline .md is an aside block (page header,
# page footer, footnote) that ground-truth prose does not carry.
ASIDE_MARKER = "<!-- ann-aside -->"

NO_GOLD_REASON = "prediction has no ground-truth record"
NO_PREDICTION_REASON = "ground truth has no prediction"


class PairingError(Exception):
    """Raised when two predictions share a stem, making the pairing ambiguous."""


# Score every predicted markdown under pred_dir against the dataset in gt_dir.
def run(
    pred_dir: Path,
    gt_dir: Path,
    label: str,
    table_threshold: float,
    doc_id: str | None = None,
) -> RecognitionReport:
    predictions: dict[str, Path] = {}
    for path in sorted(pred_dir.rglob("*.md")):
        # Two predictions with one stem make the pairing ambiguous, as on the gold side
        if path.stem in predictions:
            raise PairingError(
                f"two predictions share the stem {path.stem!r}: {predictions[path.stem]} and {path}"
            )
        predictions[path.stem] = path

    gold = {doc.doc_id: doc for doc in ground_truth.load_dataset(gt_dir)}
    if doc_id:
        predictions = {k: v for k, v in predictions.items() if k == doc_id}
        gold = {k: v for k, v in gold.items() if k == doc_id}

    documents: list[DocumentResult] = []
    for stem in sorted(predictions.keys() & gold.keys()):
        predicted_text = predictions[stem].read_text(encoding="utf-8").split(ASIDE_MARKER, 1)[0]
        gold_text = gold[stem].text

        predicted_tables = _parse_all(extract_html_tables(predicted_text), "predicted", stem)
        gold_tables = _parse_all(extract_html_tables(gold_text), "gold", stem)
        pairs, note = pair_tables(predicted_tables, gold_tables, table_threshold)

        documents.append(
            DocumentResult(
                doc_id=stem,
                wer=score_wer(predicted_text, gold_text),
                tables=score_table_pairs(pairs, predicted_tables, gold_tables, note),
            )
        )

    unpaired = [(stem, NO_GOLD_REASON) for stem in sorted(predictions.keys() - gold.keys())]
    unpaired += [(stem, NO_PREDICTION_REASON) for stem in sorted(gold.keys() - predictions.keys())]

    return RecognitionReport(
        label=label,
        pred_dir=pred_dir,
        gt_dir=gt_dir,
        table_threshold=table_threshold,
        documents=documents,
        pooled_wer=pool_wer([d.wer for d in documents if d.wer is not None]),
        pooled_tables=pool_tables([d.tables for d in documents]),
        unpaired=sorted(unpaired),
    )


# Parse extracted table markup into trees, refusing to shift the positional indices.
def _parse_all(markup: list[str], side: str, doc_id: str) -> list[TableNode]:
    trees = []
    for index, one in enumerate(markup):
        tree = parse_table(one)

        # Unreachable from the extractors, so a None here is a bug rather than bad data
        if tree is None:
            raise TableError(f"{doc_id}: {side} table {index} was extracted but could not be parsed")
        trees.append(tree)

    return trees
