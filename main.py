"""Entry point: `python main.py <pipeline> [-c cfg] [-o out] [--lang] [--granularity]`."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import ocr_core.pipeline as pipeline
from ocr_core import config as config_mod
from ocr_core.config import PIPELINES
from ocr_core.loaders import SUPPORTED_EXTS


def _build_config(args) -> config_mod.Config:
    overrides = {
        "lang": args.lang,
        "granularity": args.granularity,
        "output_dir": args.output_dir,
    }
    overrides = {k: v for k, v in overrides.items() if v is not None}
    return config_mod.load(args.config, overrides, base=PIPELINES[args.pipeline])


def _targets(cfg: config_mod.Config) -> list[Path]:
    root = Path(cfg.input_dir)
    return sorted(p for p in root.glob("*") if p.suffix.lower() in SUPPORTED_EXTS)


def cmd_run(args) -> int:
    cfg = _build_config(args)
    targets = _targets(cfg)
    if not targets:
        print(f"no files to process in {cfg.input_dir}")
        return 0

    ok = failed = 0
    for t in targets:
        try:
            out = pipeline.run_to_file(str(t), cfg, args.pipeline)
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
        p = sub.add_parser(name, help=f"OCR every file in input/ with the {name} pipeline")
        p.add_argument("-c", "--config", help="config file (YAML or JSON)")
        p.add_argument("-o", "--output-dir", help="output directory")
        p.add_argument("--lang", help="OCR language (e.g. vie, eng)")
        p.add_argument("--granularity", help="page | paragraph | line")
        p.add_argument("--log-level", default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="trace verbosity (default: INFO)")
        p.set_defaults(func=cmd_run, pipeline=name)

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except config_mod.ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
