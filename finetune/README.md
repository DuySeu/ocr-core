# Fine-tune Tesseract LSTM (zone 3)

Builds `vie_lpbank.traineddata` from OCR artifacts and LPBank ground truth.
Labels are produced automatically by aligning page OCR with
`ground_truth/lpbank/*.md` — no per-line human transcription.

## Prerequisites

1. Training binaries on PATH: `lstmtraining`, `combine_tessdata`
   (Homebrew: `brew install tesseract`).
2. Best (float) `vie.traineddata` in this package's tessdata dir — **not**
   the system `tessdata_fast` build:

```bash
mkdir -p finetune/tessdata
curl -L -o finetune/tessdata/vie.traineddata \
  https://github.com/tesseract-ocr/tessdata_best/raw/main/vie.traineddata
cp /opt/homebrew/share/tessdata/osd.traineddata finetune/tessdata/
```

3. Artifacts from a prior batch run under `artifacts/` (pages + deskewed
   webp images). **Note:** `orchestrate` was removed; producing those
   artifacts is a follow-up (see folder-review design §8).
4. Matching ground truth under `ground_truth/lpbank/` (same stems as PDFs).

Every command runs the gates in `guards.py` first and stops before cutting
any line if a gate fails.

## Commands

```bash
# Crop lines for one document/version
python -m finetune cut --sha <doc_sha256> --version <pipeline_version>

# Write .gt.txt next to each crop (skips docs with no matching GT stem)
python -m finetune align --sha <doc_sha256> --version <pipeline_version>

# Optional: blur / noise / JPEG copies of labelled lines
python -m finetune lstmf --degrade

# Or without degrade
python -m finetune lstmf

# Fine-tune (CPU, default 3000 iterations)
python -m finetune train

# All steps
python -m finetune pipeline --sha <doc_sha256> --version <pipeline_version>
```

Layout:

```
finetune/tessdata/vie.traineddata          # best, downloaded by you
finetune/tessdata/osd.traineddata          # copy from system tessdata
finetune/tessdata/vie_lpbank.traineddata   # written by train
finetune/data/<sha12>/p0007_l003.png
finetune/data/<sha12>/p0007_l003.gt.txt
finetune/data/list.train
finetune/data/rejected.log
finetune/work/                             # checkpoints
```

## Close the loop

After `vie_lpbank.traineddata` exists:

```bash
# config.yaml: langs: [vie_lpbank]
TESSDATA_PREFIX=finetune/tessdata python main.py path/to/doc.pdf
python -m evaluate.run
```

Changing `langs` changes OCR behaviour for the next `main.py` run.

## Notes

- `--degrade` is off by default. LPBank PDFs are digital-born; without
  degradation the first traineddata will be close to the base model.
- Table cells are never training samples (no line-level boxes from
  `recognize_text`).
- Similarity below 0.7 rejects a line into `rejected.log` rather than
  poisoning the set.
