"""Pipeline: load -> preprocess -> extract -> JSON/Markdown."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import extract, preprocessing
from .config import Config, DEFAULTS
from .engines import get_engine

logger = logging.getLogger(__name__)


class UnsupportedFormatError(Exception):
    """Raised when a file extension is not supported."""


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = IMAGE_EXTS | PDF_EXTS


@dataclass
class PageImage:
    page: int
    image: Image.Image


def load(path: str) -> list[PageImage]:
    """Input loading: image/PDF -> page images."""
    ext = Path(path).suffix.lower()
    logger.debug("load %s (ext=%s)", path, ext)
    if ext in IMAGE_EXTS:
        return [PageImage(1, Image.open(path))]
    if ext in PDF_EXTS:
        from pdf2image import convert_from_path  # lazy: needs Poppler

        logger.debug("converting PDF pages: %s", path)
        return [PageImage(i, img) for i, img in enumerate(convert_from_path(path), 1)]
    raise UnsupportedFormatError(f"unsupported format {ext!r} for {path}")


def run(input_path: str, config: Config = DEFAULTS) -> dict:
    """OCR one file. Loader errors propagate; per-page errors are recorded."""
    logger.info(
        "start: %s (engine=%s, lang=%s, mode=%s)",
        input_path,
        config.engine,
        config.lang,
        config.mode,
    )
    pages = load(input_path)  # may raise UnsupportedFormatError
    logger.info("loaded %d page(s) from %s", len(pages), input_path)
    engine = get_engine(config.engine)

    results = []
    for page in pages:
        try:
            img = preprocessing.apply(page.image, config.preprocess_steps)
            blocks = extract.extract(engine, img, config)
            logger.info("page %d: %d block(s)", page.page, len(blocks))
            results.append({"page": page.page, "blocks": blocks, "error": None})
        except Exception as e:  # best-effort per page
            logger.warning("page %d failed: %s: %s", page.page, type(e).__name__, e)
            results.append(
                {"page": page.page, "blocks": [], "error": f"{type(e).__name__}: {e}"}
            )

    return {
        "source": str(input_path),
        "engine": config.engine,
        "lang": config.lang,
        "mode": config.mode,
        "page_count": len(pages),
        "pages": results,
    }


def run_to_file(input_path: str, config: Config = DEFAULTS) -> str:
    """Run and write <stem>.<ext> into config.output_dir; return its path."""
    doc = run(input_path, config)
    if config.mode == "markdown":
        body, ext = to_markdown(doc), "md"
    else:
        body, ext = json.dumps(doc, indent=2, ensure_ascii=False), "json"
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{Path(input_path).stem}.{ext}"
    out_path.write_text(body)
    logger.info("wrote %s", out_path)
    return str(out_path)


def to_markdown(doc: dict) -> str:
    """Serialize a run() doc into a Markdown document."""
    parts = []
    for pg in doc["pages"]:
        if pg["error"]:
            parts.append(f"<!-- page {pg['page']} error: {pg['error']} -->")
            continue
        for b in pg["blocks"]:
            if b["type"] == "paragraph":
                parts.append(b["text"])
                continue
            rows = b["rows"]
            widths = [len(r) for r in rows if len(r) != 1]
            n = max(widths) if widths else 1
            out = []
            for i, r in enumerate(rows):
                if len(r) == 1 and n > 1:  # hàng tiêu đề trải hết bảng
                    head = r[0].replace("|", "\\|")
                    cells = [f"**{head}**"] + [""] * (n - 1)
                else:
                    cells = [c.replace("|", "\\|") for c in r] + [""] * (n - len(r))
                out.append("| " + " | ".join(cells) + " |")
                if i == 0 and b.get("header"):
                    out.append("| " + " | ".join(["---"] * n) + " |")
            parts.append("\n".join(out))
    return "\n\n".join(parts) + "\n"
