"""What one run measured, and the file it writes.

Every section renders whether or not it has numbers. A metric that could not be
computed prints the reason it could not, in the row where its number would have
been — a section that disappears when it is empty reads as "this was checked and
was fine", which is the opposite of what an empty section means.

``None`` is rendered ``n/a`` and never ``0.0``. Nought is a measurement; not
applicable is the absence of one, and averaging the two together is how a headline
score ends up describing something nobody ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .metrics import CategoryScore, DocumentTableScore, TextScore

# Metrics deliberately outside this run, named in the report so their absence is
# a decision on the record rather than something the reader has to notice.
SKIPPED_METRICS = (("Picture - detection, caption", "out of scope for this run"),)

# A document with no table on either side. Rendered apart from ``n/a``, which claims
# a score was attempted; there is nothing here to attempt.
NO_TABLES_CELL = "-"


@dataclass(frozen=True)
class LayoutResult:
    """Box scoring for one document, plus the pages that dropped out of it."""

    categories: list[CategoryScore]
    element_text: TextScore
    pages_scored: int
    page_notes: list[str]  # pages excluded from matching, and why


@dataclass(frozen=True)
class DocumentResult:
    """Everything measured for one prediction, and what could not be measured."""

    doc_id: str
    markdown_path: Path
    ground_truth_path: Path | None
    text: TextScore | None  # None when the document has no ground-truth text
    layout: LayoutResult | None  # None when either side has no boxes
    tables: DocumentTableScore | None  # None when there is no ground-truth file at all
    notes: list[str]


@dataclass(frozen=True)
class Report:
    """One evaluation run, ready to render."""

    engine: str
    output_dir: Path
    ground_truth_dir: Path
    iou_threshold: float
    table_threshold: float
    documents: list[DocumentResult]
    corpus_text: TextScore  # every scored pair pooled, not an average of the rows
    corpus_tables: DocumentTableScore | None  # every matched pair pooled, likewise
    unpaired: list[tuple[str, str]]  # stem, and which side it is missing


# Write <output_dir name>_results.md into the engine's results directory.
def write_report(report: Report, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)

    report_path = results_dir / f"{report.output_dir.name}_results.md"
    report_path.write_text(render_markdown(report), encoding="utf-8")
    return report_path


# Render the human-readable report, every section present whether scored or not.
def render_markdown(report: Report) -> str:
    scored_layout = sum(1 for d in report.documents if d.layout)
    lines = [
        f"# OCR evaluation — {report.engine}",
        "",
        "| | |",
        "| --- | --- |",
        f"| engine | `{report.engine}` |",
        f"| output_dir | `{report.output_dir}` |",
        f"| ground_truth_dir | `{report.ground_truth_dir}` |",
        f"| IoU threshold | {report.iou_threshold} |",
        f"| documents found | {len(report.documents)} |",
        "",
    ]

    # 1 — document-level text, the metric every paired document has
    lines += [
        "## 1 · Text, document-level  (predicted .md vs ground truth; lower is better)",
        "",
        "| doc | CER | CER tone-blind | WER | n_chars | n_empty_gold | ground truth |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for document in report.documents:
        score = document.text
        source = (
            document.ground_truth_path.name
            if document.ground_truth_path
            else "**missing**"
        )
        lines.append(
            f"| {document.doc_id} | {_num(score.cer if score else None)} | "
            f"{_num(score.cer_tone_blind if score else None)} | {_num(score.wer if score else None)} | "
            f"{score.n_chars if score else 0} | {score.n_empty_gold if score else 0} | {source} |"
        )
    corpus = report.corpus_text
    lines += [
        (
            f"| **all documents pooled** | **{_num(corpus.cer)}** | **{_num(corpus.cer_tone_blind)}** | "
            f"**{_num(corpus.wer)}** | **{corpus.n_chars}** | **{corpus.n_empty_gold}** | — |"
        ),
        "",
    ]

    # 2 — layout, per category, or the reason there is nothing to score
    lines += [
        f"## 2 · Layout / bbox  (IoU >= {report.iou_threshold}; higher is better)",
        "",
    ]
    if scored_layout == 0:
        lines += ["Not scored for any document. Per-document reason:", ""]
        lines += ["| doc | reason |", "| --- | --- |"]
        lines += [
            f"| {d.doc_id} | {'; '.join(d.notes) if d.notes else 'no reason recorded'} |"
            for d in report.documents
        ]
        lines.append("")
    else:
        lines += [
            "| doc | category | P | R | F1 | mIoU | TP | n_gold | n_pred |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for document in report.documents:
            if document.layout is None:
                lines.append(
                    f"| {document.doc_id} | _not scored_ | n/a | n/a | n/a | n/a | 0 | 0 | 0 |"
                )
                continue
            for score in document.layout.categories:
                lines.append(
                    f"| {document.doc_id} | {score.category} | {_num(score.precision)} | "
                    f"{_num(score.recall)} | {_num(score.f1)} | {_num(score.mean_iou)} | "
                    f"{score.true_positives} | {score.n_gold} | {score.n_pred} |"
                )
        lines.append("")

    # 3 — element-level text, conditional on layout recall and read next to it
    lines += [
        "## 3 · Text, element-level  (matched boxes only — read next to layout recall above)",
        "",
        "| doc | CER | CER tone-blind | WER | n_elements | n_chars |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for document in report.documents:
        if document.layout is None:
            lines.append(f"| {document.doc_id} | n/a | n/a | n/a | 0 | 0 |")
            continue
        score = document.layout.element_text
        lines.append(
            f"| {document.doc_id} | {_num(score.cer)} | {_num(score.cer_tone_blind)} | "
            f"{_num(score.wer)} | {score.n_elements} | {score.n_chars} |"
        )
    lines.append("")

    # 4 - tables, paired by content rather than by box
    lines += [
        f"## 4 · Tables  (pairing floor >= {report.table_threshold}; higher is better)",
        "",
        "| doc | TEDS | TEDS-Struct | matched | n_gold | n_pred | recall | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for document in report.documents:
        lines.append(_table_row(document.doc_id, document.tables))
    if report.corpus_tables:
        lines.append(_table_row("**all documents pooled**", report.corpus_tables))
    lines.append("")

    # 5 - everything that did not get measured, split by cause
    lines += ["## 5 · Not measured", "", "### 5.1 Per document", ""]
    document_notes = [(d.doc_id, note) for d in report.documents for note in d.notes]
    if not document_notes:
        lines.append("None — every document was scored on every metric in scope.")
    else:
        lines += ["| doc | what is missing |", "| --- | --- |"]
        lines += [f"| {doc_id} | {note} |" for doc_id, note in document_notes]

    lines += ["", "### 5.2 Per page", ""]
    page_notes = [
        (d.doc_id, note)
        for d in report.documents
        if d.layout
        for note in d.layout.page_notes
    ]
    if not page_notes:
        lines.append("None.")
    else:
        lines += ["| doc | page and reason |", "| --- | --- |"]
        lines += [f"| {doc_id} | {note} |" for doc_id, note in page_notes]

    lines += ["", "### 5.3 Metrics out of scope for this run", ""]
    lines += ["| metric | why |", "| --- | --- |"]
    lines += [f"| {metric} | {reason} |" for metric, reason in SKIPPED_METRICS]

    lines += ["", "### 5.4 Documents that did not pair", ""]
    if not report.unpaired:
        lines.append("None - every document paired on both sides.")
    else:
        lines += ["| stem | what is missing |", "| --- | --- |"]
        lines += [f"| {stem} | {reason} |" for stem, reason in report.unpaired]

    return "\n".join(lines) + "\n"


# Format a metric for a table cell, keeping "not applicable" distinct from zero.
def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


# Render one table-section row, keeping "no tables" distinct from "not scored".
# style: keep - called for every document row and for the pooled row.
def _table_row(label: str, score: DocumentTableScore | None) -> str:  # style: keep
    # No ground-truth file at all: nothing was paired, and nothing could have been
    if score is None:
        return f"| {label} | n/a | n/a | 0 | 0 | 0 | n/a | not scoreable - no ground truth |"

    # Neither side has a table, which is a finding rather than a failed measurement
    if score.n_gold == 0 and score.n_pred == 0:
        cell = NO_TABLES_CELL
        return f"| {label} | {cell} | {cell} | 0 | 0 | 0 | {cell} | |"

    return (
        f"| {label} | {_num(score.teds)} | {_num(score.teds_struct)} | {score.n_matched} | "
        f"{score.n_gold} | {score.n_pred} | {_num(score.table_recall)} | {score.note or ''} |"
    )
