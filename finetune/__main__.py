"""Entry point: `python -m finetune cut|align|lstmf|train|pipeline`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core import config as config_mod
from core.config import Config

from finetune import align as align_mod
from finetune import cut_lines, degrade, lstmf, train as train_mod
from finetune.guards import DATA_DIR, GuardError, check

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def _build_config(args: argparse.Namespace) -> Config:
    path = args.config or (
        str(DEFAULT_CONFIG_PATH) if DEFAULT_CONFIG_PATH.exists() else None
    )
    return config_mod.load(path)


def cmd_cut(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    check(ground_truth_dir=Path(cfg.ground_truth_dir))
    report = cut_lines.cut_lines(
        Path(cfg.artifacts_dir), args.sha, args.version
    )
    print(
        f"cut written={report.written} skipped_small={report.skipped_small} "
        f"pages={report.pages}"
    )
    return 0


def cmd_align(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    check(ground_truth_dir=Path(cfg.ground_truth_dir))
    report = align_mod.align(
        Path(cfg.artifacts_dir),
        args.sha,
        args.version,
        Path(cfg.ground_truth_dir),
        source_stem=args.stem,
    )
    skipped = ", ".join(report.skipped_docs) or "-"
    print(
        f"align written={report.written} rejected={report.rejected} "
        f"skipped={skipped}"
    )
    return 0


def cmd_lstmf(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    check(ground_truth_dir=Path(cfg.ground_truth_dir))
    data_dir = Path(args.data_dir) if args.data_dir else DATA_DIR
    if args.degrade:
        n = degrade.degrade(data_dir)
        print(f"degrade wrote={n}")
    report = lstmf.build_lstmf(data_dir=data_dir)
    print(
        f"lstmf written={report.written} failed={report.failed} "
        f"list={report.list_train}"
    )
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    check(ground_truth_dir=Path(cfg.ground_truth_dir))
    out = train_mod.train(max_iterations=args.max_iterations)
    print(f"traineddata={out}")
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    check(ground_truth_dir=Path(cfg.ground_truth_dir))

    cut_report = cut_lines.cut_lines(
        Path(cfg.artifacts_dir), args.sha, args.version
    )
    print(
        f"cut written={cut_report.written} "
        f"skipped_small={cut_report.skipped_small}"
    )
    align_report = align_mod.align(
        Path(cfg.artifacts_dir),
        args.sha,
        args.version,
        Path(cfg.ground_truth_dir),
        source_stem=args.stem,
    )
    print(
        f"align written={align_report.written} "
        f"rejected={align_report.rejected}"
    )
    if args.degrade:
        n = degrade.degrade(DATA_DIR / args.sha[:12])
        print(f"degrade wrote={n}")
    lstmf_report = lstmf.build_lstmf(data_dir=DATA_DIR)
    print(f"lstmf written={lstmf_report.written}")
    out = train_mod.train(max_iterations=args.max_iterations)
    print(f"traineddata={out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="finetune")
    sub = parser.add_subparsers(dest="command", required=True)

    p_cut = sub.add_parser("cut", help="crop TextLine images from artifacts")
    p_cut.add_argument("--sha", required=True)
    p_cut.add_argument("--version", required=True)
    p_cut.add_argument("--config")
    p_cut.set_defaults(func=cmd_cut)

    p_align = sub.add_parser("align", help="write .gt.txt from ground truth")
    p_align.add_argument("--sha", required=True)
    p_align.add_argument("--version", required=True)
    p_align.add_argument("--stem", help="ground-truth filename stem")
    p_align.add_argument("--config")
    p_align.set_defaults(func=cmd_align)

    p_lstmf = sub.add_parser("lstmf", help="encode png+gt.txt into .lstmf")
    p_lstmf.add_argument("--data-dir")
    p_lstmf.add_argument("--degrade", action="store_true")
    p_lstmf.add_argument("--config")
    p_lstmf.set_defaults(func=cmd_lstmf)

    p_train = sub.add_parser("train", help="run lstmtraining -> traineddata")
    p_train.add_argument(
        "--max-iterations",
        type=int,
        default=train_mod.DEFAULT_MAX_ITERATIONS,
    )
    p_train.add_argument("--config")
    p_train.set_defaults(func=cmd_train)

    p_pipe = sub.add_parser(
        "pipeline", help="cut -> align -> lstmf -> train"
    )
    p_pipe.add_argument("--sha", required=True)
    p_pipe.add_argument("--version", required=True)
    p_pipe.add_argument("--stem")
    p_pipe.add_argument("--degrade", action="store_true")
    p_pipe.add_argument(
        "--max-iterations",
        type=int,
        default=train_mod.DEFAULT_MAX_ITERATIONS,
    )
    p_pipe.add_argument("--config")
    p_pipe.set_defaults(func=cmd_pipeline)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        return args.func(args)
    except (
        GuardError,
        cut_lines.CutError,
        align_mod.AlignError,
        lstmf.LstmfError,
        train_mod.TrainError,
        config_mod.ConfigError,
    ) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
