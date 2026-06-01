"""Pipeline: loader -> preprocess -> extract -> JSON."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import extract, loaders, preprocessing
from .config import Config, DEFAULTS
from .engines import get_engine

logger = logging.getLogger(__name__)


def run(input_path: str, config: Config = DEFAULTS) -> dict:
    """OCR one file. Loader errors propagate; per-page errors are recorded."""
    logger.info("start: %s (engine=%s, lang=%s, mode=%s, granularity=%s)",
                input_path, config.engine, config.lang, config.mode, config.granularity)
    pages = loaders.load(input_path)  # may raise UnsupportedFormatError
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
            results.append({"page": page.page, "blocks": [], "error": f"{type(e).__name__}: {e}"})

    return {
        "source": str(input_path),
        "engine": config.engine,
        "lang": config.lang,
        "mode": config.mode,
        "granularity": config.granularity,
        "page_count": len(pages),
        "pages": results,
    }


def run_to_file(input_path: str, config: Config = DEFAULTS, pipeline: str = "default") -> str:
    """Run and write <stem>.<pipeline>.json into config.output_dir; return its path."""
    doc = run(input_path, config)
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{Path(input_path).stem}.{pipeline}.json"
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    logger.info("wrote %s", out_path)
    return str(out_path)
