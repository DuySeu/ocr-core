"""CLI: python -m evaluate.run [--config PATH] [--doc STEM] [--iou-threshold N]."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import (
    ConfigError,
    GroundTruthError,
    LoaderError,
    PairingError,
    TableError,
    TableExtractError,
    UnknownEngineError,
    evaluate_engine,
    load_config,
    write_report,
)
from .config import DEFAULT_CONFIG_PATH, DEFAULT_IOU_THRESHOLD, DEFAULT_TABLE_THRESHOLD

logger = logging.getLogger("evaluate")


# Parse arguments, score one engine's output, and write its results directory.
def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evaluate.run",
        description="Score one engine's OCR output against the ground-truth directory.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"config.yaml to read engine and directories from (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("--doc", help="score only the document with this filename stem")
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=DEFAULT_IOU_THRESHOLD,
        help=f"IoU at which a box counts as found (default: {DEFAULT_IOU_THRESHOLD})",
    )
    parser.add_argument(
        "--table-threshold",
        type=float,
        default=DEFAULT_TABLE_THRESHOLD,
        help=(
            "TEDS-Struct at which two tables count as the same table "
            f"(default: {DEFAULT_TABLE_THRESHOLD})"
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        config = load_config(
            args.config,
            iou_threshold=args.iou_threshold,
            table_threshold=args.table_threshold,
        )
        report = evaluate_engine(config, doc_id=args.doc)
    except (
        ConfigError,
        GroundTruthError,
        LoaderError,
        PairingError,
        TableError,
        TableExtractError,
        UnknownEngineError,
    ) as e:
        logger.error("evaluation failed: %s", e)
        return 1

    # An empty run is a setup mistake, not a result worth writing to disk
    if not report.documents:
        logger.error(
            "no predicted .md found under %s%s",
            config.output_dir,
            f" for --doc {args.doc}" if args.doc else "",
        )
        return 1

    report_path = write_report(report, config.results_dir)
    logger.info(
        "scored %d document(s) with engine %r", len(report.documents), config.engine
    )
    logger.info("wrote %s", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
