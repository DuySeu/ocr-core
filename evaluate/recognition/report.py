"""The Recognition tier report: one markdown file per (label, dataset) run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .tables import DocumentTableScore
from .wer import WerScore


@dataclass(frozen=True)
class DocumentResult:
    """One paired document's scores. None means the metric had nothing to score."""

    doc_id: str
    wer: WerScore | None  # None when the GT is empty after normalization
    tables: DocumentTableScore


@dataclass(frozen=True)
class RecognitionReport:
    """Every paired document, the pooled rows, and what could not be paired."""

    label: str
    pred_dir: Path
    gt_dir: Path
    table_threshold: float
    documents: list[DocumentResult]
    pooled_wer: WerScore | None
    pooled_tables: DocumentTableScore | None
    unpaired: list[tuple[str, str]]  # (doc_id, reason)


# Render the report as markdown.
def render_markdown(report: RecognitionReport) -> str:
    lines = [
        f"# Recognition: {report.label} on {report.gt_dir.name}",
        "",
        f"- pred_dir: `{report.pred_dir}`",
        f"- gt_dir: `{report.gt_dir}`",
        f"- documents paired: {len(report.documents)}",
        "",
        "## WER (lower is better)",
        "",
        "| doc | WER | n_words | ignored |",
        "| --- | --- | --- | --- |",
    ]
    for document in report.documents:
        lines.append(_wer_row(document.doc_id, document.wer))
    lines.append(_wer_row("**pooled**", report.pooled_wer))

    lines += [
        "",
        f"## TEDS (higher is better, pairing floor {report.table_threshold})",
        "",
        "| doc | TEDS | matched | n_gold | n_pred | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for document in report.documents:
        lines.append(_tables_row(document.doc_id, document.tables))
    if report.pooled_tables:
        lines.append(_tables_row("**pooled**", report.pooled_tables))

    lines += ["", "## Unpaired", ""]
    lines += [f"- `{doc_id}`: {reason}" for doc_id, reason in report.unpaired] or ["None."]

    return "\n".join(lines) + "\n"


# Write the report under results_dir/<label>/<dataset>.md and return its path.
def write_report(report: RecognitionReport, results_dir: Path) -> Path:
    path = results_dir / report.label / f"{report.gt_dir.name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


# Render one WER row; an empty GT reads n/a rather than a rate.
def _wer_row(label: str, score: WerScore | None) -> str:
    if score is None:
        return f"| {label} | n/a | 0 | 0 |"
    return f"| {label} | {score.wer:.4f} | {score.n_words} | {score.ignored} |"


# Render one TEDS row; no table on either side reads "-", nothing matched reads n/a.
def _tables_row(label: str, score: DocumentTableScore) -> str:
    if score.n_gold == 0 and score.n_pred == 0:
        return f"| {label} | - | 0 | 0 | 0 | |"

    teds = f"{score.teds:.4f}" if score.teds is not None else "n/a"
    return (
        f"| {label} | {teds} | {score.n_matched} | {score.n_gold} | {score.n_pred} | "
        f"{score.note or ''} |"
    )
