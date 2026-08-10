"""Evaluation harness for the OCR pipeline: config.yaml in, result.md out"""

from __future__ import annotations

from pathlib import Path

from . import engines, ground_truth
from .config import ConfigError, EvalConfig, load_config
from .engines import PredictionDoc, UnknownEngineError
from .ground_truth import GroundTruthError
from .loader import DESKEW_TOLERANCE_DEG, LoaderError, load_coco
from .matching import match_page
from .metrics import score_layout, score_pairs, score_plain_text, score_text
from .report import DocumentResult, LayoutResult, Report, write_report

__all__ = [
    "ConfigError",
    "EvalConfig",
    "GroundTruthError",
    "LoaderError",
    "UnknownEngineError",
    "evaluate_engine",
    "load_config",
    "write_report",
]

NO_GOLD_TEXT_NOTE = "no ground-truth .md/.docx with this stem: text metrics not scored"
NO_GOLD_BOXES_NOTE = "no ground-truth COCO with this stem: layout metrics not scored"


# Score every document one engine wrote against the ground-truth directory.
def evaluate_engine(cfg: EvalConfig, doc_id: str | None = None) -> Report:
    predictions = engines.read_documents(cfg.engine, cfg.output_dir)
    if doc_id:
        predictions = [p for p in predictions if p.doc_id == doc_id]

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
                notes=notes,
            )
        )

    predicted_ids = {p.doc_id for p in predictions}
    return Report(
        engine=cfg.engine,
        output_dir=cfg.output_dir,
        ground_truth_dir=cfg.ground_truth_dir,
        iou_threshold=cfg.iou_threshold,
        documents=documents,
        corpus_text=score_pairs(scored_pairs),
        unpaired_ground_truth=sorted(set(gold_text_files) - predicted_ids),
    )


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
