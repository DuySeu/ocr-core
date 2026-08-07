# ocr-core Pipeline Engine — Design

Date: 2026-05-29
Status: Validated

## Purpose

`ocr-core` is an OCR pipeline engine. It takes image or PDF scans and produces
a JSON file per input containing per-page, line-level text with bounding boxes
and confidence scores. The design is API-first: a Python core does the work, a
thin launcher (`main.py`) wraps it, and an optional config file makes runs
reproducible.

## High-Level Flow

```
input (image/PDF)
   → Loader        (PDF → images, or load image)
   → Preprocessor  (ordered, toggleable steps per page)
   → OCR Engine    (pluggable; Tesseract default)
   → Aggregator    (group words → lines, assemble JSON)
   → JSON output
```

## Key Decisions

- **Pluggable engine** behind an `OCREngine` interface, with `TesseractEngine`
  as the default. Adding EasyOCR / PaddleOCR / cloud later needs no pipeline
  changes.
- **Configurable preprocessing**: an ordered list of named steps
  (`grayscale`, `deskew`, `binarize`), each toggleable.
- **Best-effort per page**: a failed page is recorded with an `error` field and
  empty `lines`, and processing continues.
- **Best-effort per file (batch)**: a file that fails to load is recorded and
  the batch continues.
- **Line-level blocks**: words from the engine are grouped into lines, each with
  text, bbox, and average confidence.
- **Defaults live in `config.py`**; an optional config file and CLI flags
  override them.
- **Default source is `input/`**: running with no path processes every file in
  `input/`.

## Module Layout

```
main.py                # launcher: python main.py <function>
core/
  pipeline.py          # orchestrates loader → preprocess → engine → aggregate
  loaders.py           # PDF/image → list of page images
  preprocessing.py     # named, toggleable steps
  engines/
    base.py            # OCREngine interface + Word dataclass
    tesseract.py       # default engine
  aggregate.py         # words → lines → page JSON
  config.py            # Config model, DEFAULTS, file loading
  cli.py               # arg parsing, batch handling, calls pipeline
input/                 # default source directory for scans
out/                   # default output directory for JSON
```

## Components & Interfaces

### Loader (`loaders.py`)
- `load(path) -> list[PageImage]`; `PageImage` wraps a PIL image + page number.
- Images (`.png/.jpg/.tiff`) → single-page list. PDFs → one image per page via
  `pdf2image` (needs Poppler).
- Unknown extension → `UnsupportedFormatError`.

### Preprocessor (`preprocessing.py`)
- Each step is `(image) -> image`, registered by name in a `STEPS` dict:
  `grayscale`, `deskew`, `binarize`.
- `apply(image, steps: list[str]) -> image` runs named steps in order.
- Unknown step name → `ConfigError`.

### OCR Engine (`engines/base.py`)
```python
class OCREngine(ABC):
    @abstractmethod
    def recognize(self, image, lang: str) -> list[Word]:
        """Return words with text, bbox (x, y, w, h), confidence."""
```
- `Word` is a dataclass: `text, bbox, confidence`.
- `TesseractEngine` calls `pytesseract.image_to_data`, parses the TSV, and emits
  `Word` objects (filtering empty rows). Missing binary → `EngineError` with an
  install hint.

### Aggregator (`aggregate.py`)
- Groups `Word`s into lines using Tesseract's `block_num/par_num/line_num` keys.
- Each line → `{text, bbox, confidence}`: bbox is the union of word boxes,
  confidence is the mean of word confidences.

### Config (`config.py`)
```python
DEFAULTS = Config(
    engine="tesseract",
    lang="eng",
    preprocess_steps=["grayscale", "deskew", "binarize"],
    input_dir="./input",
    output_dir="./out",
)
```
- No config file → `DEFAULTS` used directly.
- `load(path)` reads YAML/JSON and overrides only specified fields.
- Precedence: **CLI flag > config file > `DEFAULTS`**.
- Unknown engine or step → `ConfigError` listing valid options.

## Data Flow

```
run(input_path, config) -> dict
  1. pages = loaders.load(input_path)          # may raise UnsupportedFormatError
  2. for each page:
       try:
         img   = preprocessing.apply(page.image, config.preprocess_steps)
         words = engine.recognize(img, config.lang)
         lines = aggregate.to_lines(words)
         → page result with lines
       except Exception as e:
         → page result with "error": str(e), "lines": []
  3. assemble document dict, write JSON to output_dir
```

## Output JSON Schema

```json
{
  "source": "scan.pdf",
  "engine": "tesseract",
  "lang": "eng",
  "page_count": 2,
  "pages": [
    {
      "page": 1,
      "lines": [
        { "text": "Invoice #12345", "bbox": [100, 80, 220, 28], "confidence": 96.4 }
      ],
      "error": null
    },
    {
      "page": 2,
      "lines": [],
      "error": "TesseractError: ..."
    }
  ]
}
```

- `bbox` is `[x, y, width, height]` in pixels of the preprocessed page image.
- `confidence` is 0–100 (Tesseract's native scale), mean of the line's words.
- `error` is `null` on success, a string on per-page failure.
- Output file is `<input-stem>.json` in `output_dir`.

## Error Handling

| Error                         | Where               | Behavior                                   |
|-------------------------------|---------------------|--------------------------------------------|
| Unsupported file format       | Loader              | Raise `UnsupportedFormatError` — abort file |
| PDF corrupt / unreadable      | Loader              | Raise — abort file                          |
| Unknown step / bad config     | Config/Preprocessor | Raise `ConfigError` — abort run             |
| Preprocessing fails on a page | Pipeline (per page) | Caught → page `error`, `lines: []`, continue |
| OCR fails on a page           | Pipeline (per page) | Caught → page `error`, `lines: []`, continue |
| Tesseract binary missing      | Engine init         | Raise `EngineError` with install hint       |

Principle: setup/config errors fail fast; per-page and per-file processing
errors are best-effort and recorded inline. The run succeeds as long as the
input loaded — the JSON tells the full story.

## CLI & Launcher

`main.py` is a thin launcher invoked with a short command:

```
python main.py process                 # batch: every file in input/ → out/
python main.py process some/scan.pdf    # single explicit file
python main.py process -c my.yaml       # with config overrides
```

- `main.py` calls `core.cli.main()`.
- `process` is the subcommand; room to add more later (e.g. `version`).
- With no path, all files in `input/` are processed (per-file best-effort).
- CLI prints a short summary (e.g. `3 ok, 1 failed`).
- Exit code `0` when the batch ran; non-zero only on fail-fast errors
  (bad config, missing binary).

## Testing Strategy

Framework: `pytest`. Fixture images generated in-memory with PIL (no binary
test assets).

**Unit (no Tesseract/Poppler needed):**
- `aggregate.to_lines` — synthetic `Word` lists → line grouping, union bbox,
  mean confidence.
- `preprocessing.apply` — step ordering; unknown step → `ConfigError`.
- `config.load` — defaults, file parsing, CLI-override precedence, invalid
  values → `ConfigError`.
- Loader dispatch — unsupported extension → `UnsupportedFormatError`.

**Engine (mocked):**
- `TesseractEngine.recognize` — mock `pytesseract.image_to_data` with sample
  TSV, assert `Word` parsing.

**Pipeline (per-page error contract):**
- Mock engine: one page returns words, one raises → JSON has one good page and
  one with `error` set and `lines: []`.

**Batch (per-file error contract):**
- Mix of a good file and an unsupported file → summary reports `1 ok, 1 failed`,
  good file still produces JSON.

**Integration (optional, skipped if binaries absent):**
- One real small PNG through the full pipeline,
  `@pytest.mark.skipif(tesseract not installed)`.
