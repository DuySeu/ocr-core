# Evaluation harness

Scores one engine's OCR output against a ground-truth directory. Reads `config.yaml`
at the repo root, writes `evaluate/results/<engine>/<output_dir name>_results.md` —
e.g. `output_dir: ./output/high_quality_handwritten` writes
`evaluate/results/chandra/high_quality_handwritten_results.md`.

Nothing here imports `core`. The evaluator reads the files an engine already wrote,
so it scores any provider that emits markdown — and, where the provider emits boxes,
COCO — without knowing how they were produced.

## Running

```bash
python -m evaluate.run                            # engine + directories from ./config.yaml
python -m evaluate.run --doc tonghopdon           # one document, by filename stem
python -m evaluate.run --iou-threshold 0.75       # stricter box matching (default 0.5)
python -m evaluate.run --table-threshold 0.7      # stricter table pairing (default 0.5)
python -m evaluate.run --config other.yaml        # a different config file
```

The three keys read from `config.yaml` are `engine`, `output_dir` and
`ground_truth_dir`. Everything else in that file belongs to the pipeline and is
ignored here rather than rejected.

## Pairing

A prediction is paired with the ground truth of the same **filename stem**. Anything
unpaired on either side is named in the report rather than dropped — a silent drop
and a perfect score look identical in a total.

```
output_dir/        tonghopdon.md      tonghopdon_metadata.json
ground_truth_dir/  tonghopdon.md   or tonghopdon.docx   [+ tonghopdon.coco.json]
```

Two predictions sharing a stem is an error, not a silent pick, the same rule the
ground-truth side already had.

Ground truth is read from `.md`, `.markdown`, `.txt` or `.docx`. In a `.docx` the body
is walked directly, so table cells are read in document order alongside the
paragraphs — `document.paragraphs` skips them, and text in a table is text the OCR was
asked to read. Cells come from `table_extract.walk_docx_cells` rather than `row.cells`,
which reports a vertically merged cell once per row it spans; a cell counted twice in
gold is a cell the engine is charged for twice.

## Metrics

| Section | Metrics | Needs | Direction |
|---|---|---|---|
| 1 · Text, document-level | CER, CER tone-blind, WER | predicted `.md` + ground-truth text | lower is better |
| 2 · Layout / bbox | P, R, F1, mIoU per category + micro | COCO on **both** sides | higher is better |
| 3 · Text, element-level | CER, CER tone-blind, WER over matched boxes | same as section 2 | lower is better |
| 4 · Tables | TEDS, TEDS-Struct, recall | tables on **both** sides; no boxes needed | higher is better |

Two normalization ladders run on both sides. `strict` is the reporting default;
`tone_blind` strips only the five Vietnamese tone marks and keeps the vowel-quality
marks (ă â ê ô ơ ư) and `đ`, which are different letters rather than tones. Tone
placement is canonicalized toward the traditional style (`hoà` → `hòa`) so scoring one
correct spelling against the other measures the transcriber, not the OCR.

Images are dropped whole, alt text included. A caption an engine wrote for a figure is
the engine describing the page, not transcribing it, and ground truth carries no
counterpart.

Rates aggregate corpus-level — total edit distance over total gold characters — not as
the mean of per-document rates. Mean-of-rates gives a three-character page number the
same weight as a two-thousand-character paragraph.

**Out of scope for this run**: picture detection and captioning. The report names it so
the absence is on the record.

## Tables

Tables are paired **by content, not by box**, so a markdown or HTML document with no
COCO on either side still gets a table score. Three source forms converge to HTML in
`table_extract.py` before anything is compared: `<table>` markup embedded in markdown,
markdown pipe tables, and real `.docx` tables. Predictions and ground truth for one
stem routinely use different forms: `tonghopdon` gold is pipe and its prediction is
`<table>`, so comparing the raw forms would measure the writing style, not the engine.

Pairing is greedy on TEDS-Struct, then on full TEDS, then on index. The second key is
load-bearing rather than a refinement: same-shape tables all score TEDS-Struct 1.0, so
structure alone cannot tell them apart and the pairing would depend on input order.

`recall` is printed beside every TEDS and never alone. A mean over matched pairs is
gameable without it: emit one perfect table, drop the rest, score 1.0.

A document with no ground-truth file reads `not scoreable - no ground truth`, which is
a different state from a gold file that happens to contain no tables. A document with no
table on either side reads `-` rather than `n/a`, because nothing was attempted.

`metrics/table.py` keeps its box-paired entry point, `score_tables`, for when a COCO
producer exists. Nothing in this repo writes one yet.

## Adding an engine

One module per engine in `engines/`, exposing `read_documents(output_dir) -> list[PredictionDoc]`,
plus one line in `ADAPTERS` in `engines/__init__.py`. An engine absent from that table
fails by name rather than falling back to a guess.

An adapter that finds no boxes sets `boxes_note` to say *why* — "no boxes" and "boxes
this format cannot express" are different findings, and the report prints both. Chandra
is the second case: its `<stem>_metadata.json` carries `page_box` and token counts only,
with no per-element bbox, so layout metrics cannot be computed from it.

`tesseract`, `paddleocr` and `easyocr` all go through `core/serialize`, so they share
one reader in `engines/base.py`. Their per-engine modules exist so an engine that later
diverges has a place to diverge in.

## Annotating ground-truth boxes

Layout metrics need a COCO file next to the ground-truth text, named `<stem>.coco.json`.
None exist yet.

Gold boxes live in the canonical post-deskew frame. Boxes annotated against a render
produced with different settings are rotated relative to the prediction, and the
evaluator refuses to score those pages rather than score them wrong — it compares
`page_geometry.deskew_angle` and `rotation_applied`, with a tolerance of 0.1°. Leave
`page_geometry` on each image exactly as the pipeline wrote it.

1. Render and run the pipeline, recording dpi, `preprocess_steps` and pipeline version.
2. Import the resulting COCO into Label Studio — rectangle labels plus a per-region
   transcription field. CVAT handles per-box text poorly, and per-box text is exactly
   what element-level CER/WER needs.
3. Correct box geometry, category and element text.
4. Export COCO and strip the prediction-only fields: `score`, `rec_score`, `logprob`,
   `reading_order`, `render`, `flags`.
5. Commit to `<ground_truth_dir>/<stem>.coco.json`.

The pre-annotation model **must differ from the system being measured**. Gold seeded by
the same model inherits its blind spots, and any error the two share scores as correct.
