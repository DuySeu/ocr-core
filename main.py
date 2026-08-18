"""Entry point: OCR one file, or apply manual review corrections.

OCR::

    python main.py <path> [--config config.yaml] [--out output/]

Writes full ``output/<stem>/`` (md + coco + document.json). Pages under
``qa_threshold`` are also dumped to ``review/<stem>/`` (webp + editable md).

Apply review::

    python main.py apply-review <stem> [--config config.yaml]

Reads corrected ``review/<stem>/pNNNN.md`` and rewrites ``output/<stem>/``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core import config as config_mod
from core import pipeline, review_io
from core.document.model import DocumentError
from core.loader import UnsupportedFormatError
from core.serialize import write_document

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def _build_config(args: argparse.Namespace) -> config_mod.Config:
    path = args.config or (
        str(DEFAULT_CONFIG_PATH) if DEFAULT_CONFIG_PATH.exists() else None
    )
    overrides = {"output_dir": args.out} if getattr(args, "out", None) else None
    return config_mod.load(path, overrides)


def cmd_ocr(args: argparse.Namespace) -> int:
    """Run OCR, write output/, dump failing pages to review/."""
    cfg = _build_config(args)
    run = pipeline.run_document(args.path, cfg)
    doc = run.document

    out_dir = Path(cfg.output_dir) / Path(args.path).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    written = write_document(doc, out_dir, cfg.outputs)
    review_io.write_document_json(doc, out_dir)

    review_stem = Path(cfg.review_dir) / Path(args.path).stem
    exported = review_io.export_failing_pages(
        doc, run.page_images, review_stem, cfg.qa_threshold
    )

    print(f"ok {args.path} -> {', '.join(str(p) for p in written)}")
    if exported:
        pages = ", ".join(str(p) for p in exported)
        print(f"review pages [{pages}] -> {review_stem}")
    return 0


def cmd_apply_review(args: argparse.Namespace) -> int:
    """Apply review/<stem>/ page markdown onto output/<stem>/."""
    cfg = _build_config(args)
    out_dir = Path(cfg.output_dir) / args.stem
    review_stem = Path(cfg.review_dir) / args.stem

    doc = review_io.load_document_json(out_dir)
    corrections = review_io.load_review_corrections(review_stem)
    review_io.apply_page_texts(doc, corrections)
    written = write_document(doc, out_dir, cfg.outputs)
    review_io.write_document_json(doc, out_dir)
    review_io.clear_applied_review_pages(
        review_stem, list(corrections.keys())
    )

    print(
        f"ok apply-review {args.stem} -> "
        f"{', '.join(str(p) for p in written)}"
    )
    return 0


def main() -> int:
    """Dispatch OCR or apply-review from argv."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if len(sys.argv) >= 2 and sys.argv[1] == "apply-review":
        parser = argparse.ArgumentParser(prog="ocr-core apply-review")
        parser.add_argument("stem", help="output/review stem directory name")
        parser.add_argument("--config", help="path to a config.yaml/json")
        args = parser.parse_args(sys.argv[2:])
        try:
            return cmd_apply_review(args)
        except (config_mod.ConfigError, review_io.ReviewError) as e:
            print(f"{type(e).__name__}: {e}", file=sys.stderr)
            return 2

    parser = argparse.ArgumentParser(prog="ocr-core")
    parser.add_argument("path", help="PDF or image to OCR")
    parser.add_argument("--config", help="path to a config.yaml/json")
    parser.add_argument("--out", help="override output_dir")
    args = parser.parse_args()

    try:
        return cmd_ocr(args)
    except (
        config_mod.ConfigError,
        UnsupportedFormatError,
        DocumentError,
        review_io.ReviewError,
    ) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
