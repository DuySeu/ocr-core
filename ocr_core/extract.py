"""Extract engine output into blocks per page, by mode."""

from __future__ import annotations

import re

import numpy as np

from . import tables as tables_mod
from .engines.base import OCREngine, Word

MIN_BAND = 10  # px: bỏ băng prose quá mỏng giữa các bảng


def extract(engine: OCREngine, image, config) -> list[dict]:
    """Return list of block dicts for one page, driven by config."""
    if config.mode == "data":
        # data mode: word + bbox (x,y,w,h) + confidence + line_key.
        groups: dict[tuple, list[Word]] = {}
        for w in engine.recognize_words(image, config.lang_list()):
            groups.setdefault(w.line_key, []).append(w)

        lines = []
        for key in sorted(groups):
            ws = groups[key]
            text = " ".join(w.text for w in ws)
            x0 = min(w.bbox[0] for w in ws)
            y0 = min(w.bbox[1] for w in ws)
            x1 = max(w.bbox[0] + w.bbox[2] for w in ws)
            y1 = max(w.bbox[1] + w.bbox[3] for w in ws)
            conf = round(sum(w.confidence for w in ws) / len(ws), 1)
            lines.append(
                {"text": text, "bbox": [x0, y0, x1 - x0, y1 - y0], "confidence": conf}
            )
        return lines

    # markdown mode: prose band ngoài bảng, xếp theo thứ tự y.
    tables = tables_mod.detect_tables(np.array(image))
    items = [(t.box[1], _table_block(engine, image, t, config.lang_list())) for t in tables]
    for y, box in _prose_bands(image.size, [t.box for t in tables]):
        text = engine.recognize_text(image.crop(box), config.lang_list())
        items += [
            (y, {"type": "paragraph", "text": p}) for p in _split_paragraphs(text)
        ]
    return [b for _, b in sorted(items, key=lambda it: it[0])]


def _table_block(engine: OCREngine, image, t, langs: list[str]) -> dict:
    grid = [[""] * t.n_cols for _ in range(t.n_rows)]
    section: dict[int, str] = {}
    for cell in t.cells:
        x, y, w, h = cell.box
        txt = " ".join(
            engine.recognize_text(image.crop((x, y, x + w, y + h)), langs, psm=6).split()
        )
        if cell.c1 - cell.c0 == t.n_cols:  # hàng tiêu đề trải hết bảng
            section[cell.r0] = txt
            continue
        for r in range(cell.r0, cell.r1):  # fill ô gộp
            for c in range(cell.c0, cell.c1):
                grid[r][c] = txt
    rows = [[section[i]] if i in section else grid[i] for i in range(t.n_rows)]
    return {"type": "table", "rows": rows, "header": True}


def _prose_bands(size, boxes) -> list[tuple]:
    """Băng ngang ngoài bảng -> (y_top, crop_box); bảng coi như chiếm trọn bề ngang."""
    w, h = size
    spans = sorted((b[1], b[1] + b[3]) for b in boxes)  # (top, bottom)
    bands, y = [], 0
    for top, bot in spans:
        if top - y > MIN_BAND:
            bands.append((y, (0, y, w, top)))
        y = max(y, bot)
    if h - y > MIN_BAND:
        bands.append((y, (0, y, w, h)))
    return bands


_BULLET = re.compile(r"^[-•*+]\s")
_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.|[IVXLC]+\.)\s")
_LABEL = re.compile(r"^\S[^:]{0,30}:\s")  # dòng nhãn ngắn "Nhãn: giá trị"


def _split_paragraphs(text: str) -> list[str]:
    """Reflow OCR lines: join soft-wrapped lines into continuous sentences;
    keep bullets/headings on their own line; a blank line only breaks a
    paragraph when the previous line ends a sentence (drops OCR noise breaks)."""
    lines: list[str] = []
    prev_heading = gap = False
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            gap = True
            continue
        is_head = bool(_HEADING.match(s))
        new = (
            not lines
            or _BULLET.match(s)
            or is_head
            or _LABEL.match(s)
            or prev_heading
            or (gap and lines[-1][-1:] in ".:;?!")
        )
        if new:
            lines.append(s)
        else:
            lines[-1] += " " + s
        prev_heading, gap = is_head, False

    blocks: list[str] = []  # gom các bullet liên tiếp thành một list
    for ln in lines:
        if (
            _BULLET.match(ln)
            and blocks
            and _BULLET.match(blocks[-1].rsplit("\n", 1)[-1])
        ):
            blocks[-1] += "\n" + ln
        else:
            blocks.append(ln)
    return blocks
