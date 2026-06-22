"""LLM-based post-processing: correct OCR text via OpenRouter.

Best-effort and per page: one request carries all of a page's text; on any
failure (missing key, network, malformed/length-mismatched response) the
original blocks are returned unchanged.
"""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")

MODEL = "nvidia/nemotron-3.5-content-safety:free"
TIMEOUT = 60  # seconds

SYSTEM_PROMPT = (
    "You are an OCR text corrector for Vietnamese and English documents. "
    "Fix spelling, diacritics, spacing, and obvious OCR recognition errors. "
    "Do NOT translate, summarize, reorder, merge, split, add, or remove items. "
    "Preserve numbers, codes, and punctuation. "
    "You receive a JSON array of strings. Return ONLY a JSON object of the form "
    '{"items": [...]} whose array has exactly the same number of strings, in '
    "the same order, each being the corrected version of the input at that index."
)

_warned_no_key = False


def correct_page(blocks: list[dict], config) -> list[dict]:
    """Return blocks with text fields corrected by the LLM, or originals on failure.

    Structure, block count, table shape, and non-text fields (bbox, confidence,
    header) are always preserved.
    """
    if not API_KEY:
        global _warned_no_key
        if not _warned_no_key:
            logger.warning("OPENROUTER_API_KEY not set; skipping post-processing")
            _warned_no_key = True
        return blocks

    texts, slots = _flatten(blocks)
    if not texts:
        return blocks

    items = _call_openrouter(texts)
    if items is None or len(items) != len(texts):
        if items is not None:
            logger.warning(
                "postprocess length mismatch (%d != %d); keeping original",
                len(items),
                len(texts),
            )
        return blocks

    return _remap(blocks, slots, items)


def _flatten(blocks: list[dict]) -> tuple[list[str], list[tuple]]:
    """Collect correctable strings in order with back-references (slots).

    Slot kinds:
      ("paragraph", block_index)
      ("line",      block_index)         # data mode
      ("cell",      block_index, r, c)   # table cell
    Empty strings are skipped.
    """
    texts: list[str] = []
    slots: list[tuple] = []
    for i, b in enumerate(blocks):
        kind = b.get("type")
        if kind == "table":
            for r, row in enumerate(b.get("rows", [])):
                for c, cell in enumerate(row):
                    if cell:
                        texts.append(cell)
                        slots.append(("cell", i, r, c))
        elif kind == "paragraph":
            if b.get("text"):
                texts.append(b["text"])
                slots.append(("paragraph", i))
        elif "text" in b:  # data-mode line
            if b["text"]:
                texts.append(b["text"])
                slots.append(("line", i))
    return texts, slots


def _remap(blocks: list[dict], slots: list[tuple], items: list[str]) -> list[dict]:
    """Write corrected strings back into a deep-enough copy of blocks."""
    out = [dict(b) for b in blocks]
    # copy table rows so we don't mutate the originals
    for b in out:
        if b.get("type") == "table":
            b["rows"] = [list(row) for row in b["rows"]]

    for slot, value in zip(slots, items):
        if not isinstance(value, str):
            value = str(value)
        if slot[0] == "cell":
            _, i, r, c = slot
            out[i]["rows"][r][c] = value
        else:  # paragraph | line
            out[slot[1]]["text"] = value
    return out


def _call_openrouter(texts: list[str]) -> list[str] | None:
    """Send one correction request; return the items list or None on any failure."""
    try:
        from openrouter import OpenRouter

        with OpenRouter(api_key=API_KEY) as client:
            resp = client.chat.send(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(texts, ensure_ascii=False),
                    },
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
        content = resp.choices[0].message.content
        items = json.loads(content)["items"]
        return items if isinstance(items, list) else None
    except Exception as e:  # best-effort: any failure -> fall back to originals
        logger.warning("postprocess call failed: %s: %s", type(e).__name__, e)
        return None
