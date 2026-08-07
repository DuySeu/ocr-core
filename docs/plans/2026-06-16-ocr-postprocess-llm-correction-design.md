# OCR Post-Processing: LLM Text Correction

Date: 2026-06-16
Status: Approved (design)

## Summary

Add a post-processing step that corrects OCR output (spelling, diacritics,
spacing, and obvious recognition errors) for both pipelines using an LLM via
OpenRouter's free model tier. The step sits between extraction and result
collection in `pipeline.run()`, operates per page with a single API call, and
is best-effort: any failure falls back to the original, uncorrected text.

## Decisions

- **Method:** LLM-based correction via OpenRouter (free model).
- **Scope:** Both pipelines — `legal` (markdown: paragraphs + table cells) and
  `invoice` (data: line `text`).
- **Batching:** One request per page (all of the page's text sent together,
  corrections mapped back by index).
- **Integration:** Simple module `core/postprocess.py` called from
  `pipeline.run()`. No corrector registry (YAGNI).
- **Config:** Single `postprocess: bool` field. Model and timeout are module
  constants. API key from `OPENROUTER_API_KEY` in `.env`.
- **Resilience:** No retry. On any error (missing key, network, 429, timeout,
  malformed/length-mismatched response) → keep original text.
- **SDK:** Official `openrouter` Python SDK (`pip install openrouter`).
- **Testing:** Fully offline; monkeypatch the network call.

## Section 1 — Architecture & data flow

New module `core/postprocess.py` performs LLM-based correction per page,
inserted into `pipeline.run()` between extraction and result collection.

Current per-page flow:

```
preprocessing.apply() -> extract.extract() -> blocks -> results.append(...)
```

New per-page flow:

```
preprocessing.apply() -> extract.extract() -> blocks
   -> postprocess.correct_page(blocks, config)   # new, only if config.postprocess
   -> results.append(...)
```

`correct_page` receives the page's `blocks` list and returns a new list with
text fields corrected, same structure/length/order. It is called inside the
existing per-page `try/except`; it also guards internally so a correction
failure keeps the original blocks rather than blanking the page.

### Block shapes handled (from `extract.py`)

- `{"type": "paragraph", "text": str}` — correct `text`.
- `{"type": "table", "rows": [[str, ...]], "header": bool}` — correct each
  non-empty cell string.
- data-mode line `{"text": str, "bbox": [...], "confidence": float}` — correct
  `text` only; **bbox and confidence pass through untouched**.

### Invariant

Correction never changes the number of blocks, the number of table cells, or
any non-text field. Corrections are mapped back by position/index. If the model
returns the wrong count, its output is discarded for that page and originals are
kept.

## Section 2 — Configuration

Add one field to the `Config` dataclass in `config.py`:

```python
postprocess: bool = False
```

Because `_ALLOWED_KEYS` derives from `Config.__dataclass_fields__` and `_merge`
validates against it, adding the field automatically lets `config.yaml` set it.

Pipeline defaults (enabled for both):

```python
PIPELINES = {
    "legal":   Config(mode="markdown", postprocess=True),
    "invoice": Config(mode="data",     postprocess=True),
}
```

`validate()` checks `postprocess` is a bool.

Model and timeout are module-level constants in `postprocess.py`:

```python
MODEL = "meta-llama/llama-3.3-70b-instruct:free"
TIMEOUT = 60  # seconds
```

API key from `.env` via `python-dotenv`:

```python
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")
```

If `API_KEY` is missing: log a warning
(`"OPENROUTER_API_KEY not set; skipping post-processing"`) and skip correction —
`correct_page` returns the original blocks unchanged.

`config.yaml` documents one optional key:

```yaml
postprocess: true
```

`.env` must be added to `.gitignore`; an `.env.example` is provided.

## Section 3 — `postprocess.py` internals

Public entry:

```python
def correct_page(blocks: list[dict], config: Config) -> list[dict]:
```

If `API_KEY` is missing → warn + return `blocks` as-is.

1. **Flatten to an indexed list of strings.** Walk blocks in order, collecting
   every correctable text into a flat list with a back-reference ("slot") so
   corrections can be written back:
   - paragraph → one entry pointing at `block["text"]`
   - table → one entry per non-empty cell, pointing at `(row, col)`
   - data line → one entry pointing at `block["text"]`

   Empty strings are skipped (not sent).

2. **Build one request.** Send the JSON array of strings with a Vietnamese-aware
   system prompt instructing the model to fix OCR/spelling/diacritic/grammar
   errors without translating, reformatting, merging, or dropping items, and to
   return a JSON object with the same number of items in the same order.

3. **Call OpenRouter** via the `openrouter` SDK; parse the reply.

4. **Map back.** If parsing succeeds and `len(items) == len(texts)`, write each
   corrected string into its slot (rebuilding blocks immutably). Otherwise log a
   warning and return the original `blocks`.

No retry: any exception → warn + return originals.

## Section 4 — OpenRouter SDK, prompt, parsing

Dependency: add `openrouter` to `requirements.txt`.

```python
import os, json, logging
from dotenv import load_dotenv
from openrouter import OpenRouter

load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "meta-llama/llama-3.3-70b-instruct:free"

def _call_openrouter(texts: list[str]) -> list[str] | None:
    try:
        with OpenRouter(api_key=API_KEY) as client:
            resp = client.chat.send(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",
                     "content": json.dumps(texts, ensure_ascii=False)},
                ],
            )
        content = resp.choices[0].message.content
        items = json.loads(content)["items"]
        return items if isinstance(items, list) else None
    except Exception as e:
        logger.warning("postprocess call failed: %s: %s", type(e).__name__, e)
        return None
```

Note on params: the SDK mirrors the REST API 1:1, so `temperature=0` and
`response_format={"type": "json_object"}` should pass through. They will be
included at implementation time and verified against the installed SDK; if a
param name differs, the defensive `try/except` still falls back safely. Because
the prompt asks for a JSON object even without `response_format`, parsing stays
robust.

System prompt (intent): fix Vietnamese/English OCR spelling, diacritics,
spacing, and obvious errors; never translate, reorder, merge, split, add, or
drop items; preserve numbers, codes, and punctuation; return ONLY
`{"items": [...]}` with exactly the same number of strings, in the same order.

Fallback: `_call_openrouter` returns `None` on any failure; `correct_page` then
keeps originals. Length mismatch (`len(items) != len(texts)`) is also treated as
failure.

## Section 5 — Testing & rollout

New test file `tests/test_postprocess.py` (pytest, fully offline — monkeypatch
`_call_openrouter`, no real network):

- **Maps corrections back by index** — paragraph + table + data-line blocks in;
  stub returns corrected strings; assert each lands in the right slot, order
  preserved.
- **Preserves non-text fields** — data-mode line keeps identical `bbox` and
  `confidence`; table keeps `header` and shape; block count unchanged.
- **Empty strings skipped** — empty table cells aren't sent and stay empty.
- **Length mismatch → fallback** — stub returns fewer/more items; assert
  original blocks returned unchanged.
- **Call failure → fallback** — stub returns `None`; originals returned.
- **Missing API key → skip** — monkeypatch `API_KEY=None`; `correct_page`
  returns originals and warns (no client call).
- **Flatten/remap unit tests** — verify the flatten step produces the expected
  slot list for mixed blocks.

Existing tests: `PIPELINES` now sets `postprocess=True`; since `correct_page`
no-ops without an API key, existing pipeline tests stay green in CI (no key
present). `test_config.py` / `test_pipeline.py` do not assert exact `Config`
equality, so they remain valid.

Rollout / docs:

- Update `README.md` (post-process feature, `.env` setup, `OPENROUTER_API_KEY`).
- Add `python-dotenv` + `openrouter` to `requirements.txt`.
- Ensure `.env` is in `.gitignore`; add `.env.example`.

## Out of scope (YAGNI)

- Corrector registry / pluggable corrector backends.
- Retry / backoff on rate limits.
- Per-pipeline model or timeout configuration.
- Offline / dictionary-based correction.
