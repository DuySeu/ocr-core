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

from .metrics import CategoryScore, TextScore

# Metrics deliberately outside this run, named in the report so their absence is
# a decision on the record rather than something the reader has to notice.
SKIPPED_METRICS = (
    (
        "Table — TEDS, TEDS-Struct",
        "out of scope for this run; metrics/table.py is unwired",
    ),
    ("Picture — detection, caption", "out of scope for this run"),
)


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
    notes: list[str]


@dataclass(frozen=True)
class Report:
    """One evaluation run, ready to render."""

    engine: str
    output_dir: Path
    ground_truth_dir: Path
    iou_threshold: float
    documents: list[DocumentResult]
    corpus_text: TextScore  # every scored pair pooled, not an average of the rows
    unpaired_ground_truth: list[str]


# Write result.md into the engine's results directory.
def write_report(report: Report, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)

    (results_dir / "result.md").write_text(render_markdown(report), encoding="utf-8")
    return results_dir


# Render the human-readable report, every section present whether scored or not.
def render_markdown(report: Report) -> str:
    scored_text = sum(1 for d in report.documents if d.text)
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
        f"| scored for text | {scored_text} |",
        f"| scored for layout | {scored_layout} |",
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

    # 4 — everything that did not get measured, split by cause
    lines += ["## 4 · Not measured", "", "### 4.1 Per document", ""]
    document_notes = [(d.doc_id, note) for d in report.documents for note in d.notes]
    if not document_notes:
        lines.append("None — every document was scored on every metric in scope.")
    else:
        lines += ["| doc | what is missing |", "| --- | --- |"]
        lines += [f"| {doc_id} | {note} |" for doc_id, note in document_notes]

    lines += ["", "### 4.2 Per page", ""]
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

    lines += ["", "### 4.3 Metrics out of scope for this run", ""]
    lines += ["| metric | why |", "| --- | --- |"]
    lines += [f"| {metric} | {reason} |" for metric, reason in SKIPPED_METRICS]

    lines += ["", "### 4.4 Ground truth with no prediction", ""]
    if not report.unpaired_ground_truth:
        lines.append("None — every ground-truth file was paired.")
    else:
        lines += ["| stem | |", "| --- | --- |"]
        lines += [
            f"| {stem} | no document of this name under `{report.output_dir}` |"
            for stem in report.unpaired_ground_truth
        ]

    return "\n".join(lines) + "\n"


# Format a metric for a table cell, keeping "not applicable" distinct from zero.
def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"
