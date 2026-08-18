"""Align OCR TextLines with ground-truth page text to produce .gt.txt labels."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from core.document import serde
from core.document.model import TextContent, TextLine
from evaluate.ground_truth import discover_text
from evaluate.ground_truth import load as load_ground_truth

from finetune.guards import DATA_DIR

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.7
PAGE_MARKER = re.compile(r"<!--\s*page:\s*(\d+)\s*-->", re.IGNORECASE)
TABLE_BLOCK = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
HTML_TAG = re.compile(r"<[^>]+>")
BULLET_PREFIX = re.compile(r"^[\-\*\+]\s+")


class AlignError(Exception):
    """Raised when alignment cannot start (missing inputs)."""


@dataclass(frozen=True)
class AlignReport:
    """How many labels one align run wrote or rejected."""

    written: int
    rejected: int
    skipped_docs: tuple[str, ...]


# Align every cut line under data/<sha>/ against matching ground truth.
def align(
    artifacts_dir: Path,
    doc_sha256: str,
    pipeline_version: str,
    ground_truth_dir: Path,
    source_stem: str | None = None,
    data_dir: Path | None = None,
) -> AlignReport:
    root = artifacts_dir / doc_sha256[:12] / pipeline_version
    pages_dir = root / "pages"
    if not pages_dir.is_dir():
        raise AlignError(f"pages directory not found: {pages_dir}")

    gt_index = discover_text(ground_truth_dir)
    stem = source_stem or _stem_from_meta(root)
    if stem is None or stem not in gt_index:
        reason = stem or doc_sha256[:12]
        logger.warning("no ground truth for stem %r; skipping", reason)
        return AlignReport(written=0, rejected=0, skipped_docs=(reason,))

    dest = data_dir or (DATA_DIR / doc_sha256[:12])
    dest.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rejected_log = DATA_DIR / "rejected.log"

    gt_text = load_ground_truth(gt_index[stem])
    written = 0
    rejected = 0

    for page_path in sorted(pages_dir.glob("p*.json")):
        data = json.loads(page_path.read_text(encoding="utf-8"))
        geom, elements = serde.page_from_dict(data)
        lines = _collect_text_lines(elements)
        if not lines:
            continue

        page_gt = _page_ground_truth(gt_text, geom.page)
        labels = _align_page(lines, page_gt)
        for index, (label, reason) in enumerate(labels):
            out_png = dest / f"p{geom.page:04d}_l{index:03d}.png"
            if not out_png.is_file():
                continue
            if label is None:
                rejected += 1
                _append_rejected(rejected_log, f"{out_png.name}: {reason}")
                continue
            out_png.with_suffix(".gt.txt").write_text(
                label + "\n", encoding="utf-8"
            )
            written += 1

    logger.info(
        "aligned %d label(s), rejected %d for %s", written, rejected, stem
    )
    return AlignReport(written=written, rejected=rejected, skipped_docs=())


# Prepare GT text: drop tables, strip tags/bullets, NFC (public for tests).
def prepare_ground_truth(text: str) -> str:
    return _prepare_ground_truth(text)


# Align one page's lines to prepared GT (public for tests).
def align_page_lines(
    lines: list[TextLine], page_gt: str
) -> list[tuple[str | None, str | None]]:
    return _align_page(lines, page_gt)


# Read the source stem from meta.json when the caller did not pass one.
def _stem_from_meta(root: Path) -> str | None:
    meta_path = root / "meta.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source = meta.get("source")
    if not source:
        return None
    return Path(source).stem


# Collect TextLines in reading order from text elements only.
def _collect_text_lines(elements: list) -> list[TextLine]:
    ordered = sorted(elements, key=lambda e: e.reading_order)
    lines: list[TextLine] = []
    for element in ordered:
        if element.category != "text":
            continue
        if not isinstance(element.content, TextContent):
            continue
        lines.extend(element.content.lines)
    return lines


# Slice ground truth for one page using <!-- page: N --> markers.
def _page_ground_truth(full_text: str, page: int) -> str:
    markers = list(PAGE_MARKER.finditer(full_text))
    if not markers:
        return full_text
    for i, match in enumerate(markers):
        if int(match.group(1)) != page:
            continue
        start = match.end()
        end = (
            markers[i + 1].start()
            if i + 1 < len(markers)
            else len(full_text)
        )
        return full_text[start:end]
    return ""


# Align OCR lines to GT; return [(label|None, reason|None), ...] per line.
def _align_page(
    lines: list[TextLine], page_gt: str
) -> list[tuple[str | None, str | None]]:
    cleaned = _prepare_ground_truth(page_gt)
    ocr_parts = [line.text_ocr for line in lines]
    # Join with newline so line boundaries match prepared GT line breaks
    ocr_joined = "\n".join(ocr_parts)

    boundaries: list[tuple[int, int]] = []
    cursor = 0
    for i, part in enumerate(ocr_parts):
        boundaries.append((cursor, cursor + len(part)))
        cursor += len(part)
        if i < len(ocr_parts) - 1:
            cursor += 1  # account for the joining "\n"

    if not ocr_joined.strip() or not cleaned.strip():
        return [(None, "empty ocr or ground truth") for _ in lines]

    opcodes = Levenshtein.opcodes(ocr_joined, cleaned)
    mapping = _ocr_to_gt_index(opcodes, len(ocr_joined), len(cleaned))

    results: list[tuple[str | None, str | None]] = []
    for start, end in boundaries:
        g_start = mapping[start]
        g_end = mapping[end]
        if g_end < g_start:
            g_start, g_end = g_end, g_start
        gt_slice = cleaned[g_start:g_end]
        ocr_slice = ocr_joined[start:end]
        if not gt_slice:
            results.append((None, "empty gt span"))
            continue
        similarity = Levenshtein.normalized_similarity(ocr_slice, gt_slice)
        if similarity < SIMILARITY_THRESHOLD:
            results.append(
                (
                    None,
                    f"similarity {similarity:.3f} < {SIMILARITY_THRESHOLD}",
                )
            )
            continue
        results.append((gt_slice, None))
    return results


# Strip tables, remaining tags, markdown bullets; NFC-normalize.
def _prepare_ground_truth(text: str) -> str:
    # Remove table blocks before stripping any other tags
    without_tables = TABLE_BLOCK.sub("", text)
    without_tags = HTML_TAG.sub("", without_tables)
    lines_out = [
        BULLET_PREFIX.sub("", raw_line)
        for raw_line in without_tags.splitlines()
    ]
    return unicodedata.normalize("NFC", "\n".join(lines_out))


# Map each OCR offset (0..ocr_len inclusive) to a GT offset.
def _ocr_to_gt_index(
    opcodes: list, ocr_len: int, gt_len: int
) -> list[int]:
    mapping = [0] * (ocr_len + 1)
    for tag, i1, i2, j1, j2 in opcodes:
        if tag in ("equal", "replace"):
            span = i2 - i1
            for k in range(span):
                if span == 0:
                    mapping[i1 + k] = j1
                else:
                    mapping[i1 + k] = j1 + int(
                        round((j2 - j1) * k / span)
                    )
            mapping[i2] = j2
        elif tag == "delete":
            for k in range(i1, i2 + 1):
                mapping[k] = j1
        elif tag == "insert":
            mapping[i1] = j1
            # End of insert advances GT cursor for the next opcode
            if i1 <= ocr_len:
                mapping[i1] = j2
    mapping[ocr_len] = gt_len
    return mapping


# Append one rejection reason to rejected.log.
def _append_rejected(path: Path, message: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(message + "\n")
