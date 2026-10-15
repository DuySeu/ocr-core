"""CLI: python -m evaluate <tier> [--pred DIR] [--gt DIR] [--config PATH] ..."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import extraction, layout, recognition
from .config import DEFAULT_CONFIG_PATH, DEFAULT_TABLE_THRESHOLD, RESULTS_DIR, ConfigError, load_config
from .ground_truth import GroundTruthError
from .table_extract import TableExtractError

logger = logging.getLogger("evaluate")

TIERS = ("layout", "recognition", "extraction")


# Parse arguments, run one tier, and write its report.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evaluate",
        description="Score predictions against the ground-truth dataset, one tier at a time.",
    )
    parser.add_argument("tier", choices=TIERS)
    parser.add_argument("--pred", type=Path, help="prediction directory (default: output_dir)")
    parser.add_argument("--gt", type=Path, help="ground-truth dataset (default: ground_truth_dir)")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"config.yaml supplying the default directories (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("--label", help="name of this run in the report path (default: pred dir name)")
    parser.add_argument("--doc", help="score only the document with this doc_id")
    parser.add_argument(
        "--table-threshold",
        type=float,
        default=DEFAULT_TABLE_THRESHOLD,
        help=f"TEDS-Struct at which two tables count as the same (default: {DEFAULT_TABLE_THRESHOLD})",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        config = load_config(args.config, args.pred, args.gt)
        if args.tier == "layout":
            layout.run(config.pred_dir, config.gt_dir)
        if args.tier == "extraction":
            extraction.run(config.pred_dir, config.gt_dir)

        report = recognition.run(
            config.pred_dir,
            config.gt_dir,
            label=args.label or config.pred_dir.name,
            table_threshold=args.table_threshold,
            doc_id=args.doc,
        )
    except NotImplementedError as e:
        logger.error("%s", e)
        return 1
    except (
        ConfigError,
        GroundTruthError,
        recognition.PairingError,
        recognition.TableError,
        TableExtractError,
    ) as e:
        logger.error("evaluation failed: %s", e)
        return 1

    # An empty run is a setup mistake, not a result worth writing to disk
    if not report.documents:
        logger.error(
            "no prediction under %s pairs with the dataset in %s", config.pred_dir, config.gt_dir
        )
        return 1

    path = recognition.write_report(report, RESULTS_DIR / args.tier)
    logger.info("scored %d document(s)", len(report.documents))
    logger.info("wrote %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
