"""Evaluation harness for the OCR pipeline: config.yaml in, <output_dir>_results.md out."""

from __future__ import annotations

from pathlib import Path

from . import engines, ground_truth
from .config import ConfigError, EvalConfig, load_config
from .engines import PredictionDoc, UnknownEngineError
from .ground_truth import GroundTruthError
from .loader import DESKEW_TOLERANCE_DEG, LoaderError, load_coco
from .matching import match_page
from .metrics import (
    DocumentTableScore,
    TableError,
    TableNode,
    pair_tables,
    parse_table,
    score_layout,
    score_pairs,
    score_plain_text,
    score_table_pairs,
    score_text,
)
from .report import DocumentResult, LayoutResult, Report, write_report
from .table_extract import TableExtractError, extract_docx_tables, extract_html_tables

__all__ = [
    "ConfigError",
    "EvalConfig",
    "GroundTruthError",
    "LoaderError",
    "PairingError",
    "TableError",
    "TableExtractError",
    "UnknownEngineError",
    "evaluate_engine",
    "load_config",
    "write_report",
]

NO_GOLD_TEXT_NOTE = "no ground-truth .md/.docx with this stem: text metrics not scored"
NO_GOLD_BOXES_NOTE = "no ground-truth COCO with this stem: layout metrics not scored"

NO_PREDICTION_REASON = "no document of this name under the output directory"
NO_GOLD_REASON = "no ground-truth .md/.docx of this name"

# Ground-truth suffixes whose tables are read out of the file's text rather than
# through python-docx. Mirrors ground_truth.TEXT_SUFFIXES.
DOCX_SUFFIX = ".docx"


class PairingError(Exception):
    """Raised when two predictions share a stem, making the pairing ambiguous."""


# Score every document one engine wrote against the ground-truth directory.
def evaluate_engine(cfg: EvalConfig, doc_id: str | None = None) -> Report:
    predictions = engines.read_documents(cfg.engine, cfg.output_dir)
    if doc_id:
        predictions = [p for p in predictions if p.doc_id == doc_id]

    # Two predictions with one stem make the pairing ambiguous, as on the gold side
    seen: set[str] = set()
    for prediction in predictions:
        if prediction.doc_id in seen:
            raise PairingError(
                f"two predictions share the stem {prediction.doc_id!r} under "
                f"{cfg.output_dir}: {prediction.markdown_path}"
            )
        seen.add(prediction.doc_id)

    gold_text_files = ground_truth.discover_text(cfg.ground_truth_dir)
    gold_box_files = ground_truth.discover_boxes(cfg.ground_truth_dir)

    documents: list[DocumentResult] = []
    scored_pairs: list[tuple[str, str]] = []
    for prediction in predictions:
        notes: list[str] = []

        # Document-level text: the metric a prediction gets from its markdown alone
        gold_text_path = gold_text_files.get(prediction.doc_id)
        text_score = None
        if gold_text_path is None:
            notes.append(NO_GOLD_TEXT_NOTE)
        else:
            gold_text = ground_truth.load(gold_text_path)
            scored_pairs.append((prediction.text, gold_text))
            text_score = score_plain_text(prediction.text, gold_text)

        layout, layout_note = _score_boxes(
            prediction, gold_box_files.get(prediction.doc_id), cfg.iou_threshold
        )
        if layout_note:
            notes.append(layout_note)

        documents.append(
            DocumentResult(
                doc_id=prediction.doc_id,
                markdown_path=prediction.markdown_path,
                ground_truth_path=gold_text_path,
                text=text_score,
                layout=layout,
                tables=_score_tables(prediction, gold_text_path, cfg.table_threshold),
                notes=notes,
            )
        )

    # Name both directions: a silent drop and a perfect score look identical in a total
    predicted_ids = {p.doc_id for p in predictions}
    unpaired = [(stem, NO_PREDICTION_REASON) for stem in sorted(set(gold_text_files) - predicted_ids)]
    unpaired += [(stem, NO_GOLD_REASON) for stem in sorted(predicted_ids - set(gold_text_files))]

    return Report(
        engine=cfg.engine,
        output_dir=cfg.output_dir,
        ground_truth_dir=cfg.ground_truth_dir,
        iou_threshold=cfg.iou_threshold,
        table_threshold=cfg.table_threshold,
        documents=documents,
        corpus_text=score_pairs(scored_pairs),
        corpus_tables=_pool_tables([d.tables for d in documents]),
        unpaired=sorted(unpaired),
    )


# Pair and score one document's tables, or None when there is no ground truth to pair to.
# style: keep - inlining the two extractions and the suffix dispatch pushes
# evaluate_engine well past 60 lines, and it shares no locals with the text pass.
def _score_tables(  # style: keep
    prediction: PredictionDoc, gold_path: Path | None, threshold: float
) -> DocumentTableScore | None:
    if gold_path is None:
        return None

    # Gold tables come from python-docx for a .docx and out of the text for the rest
    if gold_path.suffix.lower() == DOCX_SUFFIX:
        gold_markup = extract_docx_tables(gold_path)
    else:
        gold_markup = extract_html_tables(gold_path.read_text(encoding="utf-8"))

    predicted_trees = _parse_all(extract_html_tables(prediction.text), "predicted")
    gold_trees = _parse_all(gold_markup, "gold")

    pairs, note = pair_tables(predicted_trees, gold_trees, threshold)
    return score_table_pairs(pairs, predicted_trees, gold_trees, note)


# Pool every document's matched pairs into one corpus row, weighted by match count.
# style: keep - called once from evaluate_engine, but it is the whole corpus
# aggregation and inlining it would bury the weighting inside the Report literal.
def _pool_tables(scores: list[DocumentTableScore | None]) -> DocumentTableScore | None:  # style: keep
    measured = [s for s in scores if s is not None]
    if not measured:
        return None

    matched = sum(s.n_matched for s in measured)
    gold = sum(s.n_gold for s in measured)

    # Weight by matched count so a one-row table does not outweigh a forty-row one
    return DocumentTableScore(
        teds=sum(s.teds * s.n_matched for s in measured if s.teds is not None) / matched
        if matched
        else None,
        teds_struct=sum(
            s.teds_struct * s.n_matched for s in measured if s.teds_struct is not None
        )
        / matched
        if matched
        else None,
        n_matched=matched,
        n_gold=gold,
        n_pred=sum(s.n_pred for s in measured),
        table_recall=matched / gold if gold else None,
        note=None,
    )


# Parse extracted table markup into trees, refusing to shift the positional indices.
# style: keep - called for both sides of every document.
def _parse_all(markup: list[str], side: str) -> list[TableNode]:  # style: keep
    trees = []
    for index, one in enumerate(markup):
        tree = parse_table(one)

        # Unreachable from the extractors, so a None here is a bug rather than bad data
        if tree is None:
            raise TableError(f"{side} table {index} was extracted but could not be parsed")
        trees.append(tree)

    return trees


# Match one document's predicted boxes to gold, or say why it cannot be matched.
# style: keep — inlining the page loop pushes evaluate_engine past 85 lines, and it
# shares no locals with the text pass beyond the prediction it is handed.
def _score_boxes(  # style: keep
    prediction: PredictionDoc, gold_path: Path | None, threshold: float
) -> tuple[LayoutResult | None, str | None]:
    if prediction.boxes is None:
        return None, prediction.boxes_note
    if gold_path is None:
        return None, NO_GOLD_BOXES_NOTE

    gold = load_coco(gold_path)
    match_results = []
    page_notes: list[str] = []

    for page in sorted(gold.frames):
        gold_frame = gold.frames[page]
        predicted_frame = prediction.boxes.frames.get(page)

        # A page the pipeline could not process is not a page the detector missed
        if page in prediction.boxes.page_errors or predicted_frame is None:
            page_notes.append(
                f"page {page}: absent from the prediction or listed in info.page_errors"
            )
            continue

        # Boxes annotated against a different deskew are rotated relative to these
        angle_delta = abs(gold_frame.deskew_angle - predicted_frame.deskew_angle)
        if angle_delta > DESKEW_TOLERANCE_DEG or (
            gold_frame.rotation_applied != predicted_frame.rotation_applied
        ):
            page_notes.append(
                f"page {page}: coordinate frames differ — deskew "
                f"{gold_frame.deskew_angle:.3f} vs {predicted_frame.deskew_angle:.3f}, "
                f"rotation {gold_frame.rotation_applied} vs {predicted_frame.rotation_applied}"
            )
            continue

        match_results.append(
            match_page(
                page=page,
                predicted=prediction.boxes.elements.get(page, []),
                gold=gold.elements.get(page, []),
                threshold=threshold,
            )
        )

    return (
        LayoutResult(
            categories=score_layout(match_results),
            element_text=score_text(match_results),
            pages_scored=len(match_results),
            page_notes=page_notes,
        ),
        None,
    )
