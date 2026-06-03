"""Entry point: `python main.py <pipeline>` (override qua config.yaml hardcode)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import ocr_core.pipeline as pipeline
from ocr_core import config as config_mod
from ocr_core.config import PIPELINES
from ocr_core.pipeline import SUPPORTED_EXTS

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def _build_config(pipeline_name: str) -> config_mod.Config:
    """Override pipeline default bằng config.yaml nếu file tồn tại và có dữ liệu."""
    path = str(CONFIG_PATH) if CONFIG_PATH.exists() else None
    return config_mod.load(path, base=PIPELINES[pipeline_name])


def cmd_run(args) -> int:
    cfg = _build_config(args.pipeline)
    root = Path(cfg.input_dir)
    targets = sorted(p for p in root.glob("*") if p.suffix.lower() in SUPPORTED_EXTS)
    if not targets:
        print(f"no files to process in {cfg.input_dir}")
        return 0

    ok = failed = 0
    for t in targets:
        try:
            out = pipeline.run_to_file(str(t), cfg)
            print(f"ok   {t} -> {out}")
            ok += 1
        except Exception as e:
            print(f"fail {t}: {type(e).__name__}: {e}")
            failed += 1
    print(f"{ok} ok, {failed} failed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ocr-core")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in PIPELINES:
        p = sub.add_parser(
            name, help=f"OCR every file in input/ with the {name} pipeline"
        )
        p.set_defaults(func=cmd_run, pipeline=name)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except config_mod.ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
