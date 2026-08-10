# Evaluation harness

Scores one engine's OCR output against a ground-truth directory. Reads `config.yaml`
at the repo root, writes `evaluate/results/<engine>/result.md`.

Nothing here imports `core`. The evaluator reads the files an engine already wrote,
so it scores any provider that emits markdown — and, where the provider emits boxes,
COCO — without knowing how they were produced.

## Running

```bash
python -m evaluate                            # engine + directories from ./config.yaml
python -m evaluate --doc tonghopdon           # one document, by filename stem
python -m evaluate --iou-threshold 0.75       # stricter box matching (default 0.5)
python -m evaluate --config other.yaml        # a different config file
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

Ground truth is read from `.md`, `.markdown`, `.txt` or `.docx`. In a `.docx` the body
is walked directly, so table cells are read in document order alongside the
paragraphs — `document.paragraphs` skips them, and text in a table is text the OCR was
asked to read.

## Metrics

| Section | Metrics | Needs | Direction |
|---|---|---|---|
| 1 · Text, document-level | CER, CER tone-blind, WER | predicted `.md` + ground-truth text | lower is better |
| 2 · Layout / bbox | P, R, F1, mIoU per category + micro | COCO on **both** sides | higher is better |
| 3 · Text, element-level | CER, CER tone-blind, WER over matched boxes | same as section 2 | lower is better |

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

**Out of scope for this run**: table (TEDS, TEDS-Struct) and picture. `metrics/table.py`
is complete and tested but unwired; the report names both so the absence is on the
record.

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
