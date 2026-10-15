"""Resolving which prediction and ground-truth directories one evaluation run reads.

Directories given on the command line win and resolve against the working
directory. A directory left out falls back to ``output_dir`` / ``ground_truth_dir``
in config.yaml, resolved against the repo root. Everything else in that file belongs
to the pipeline and is ignored here.

This does not reuse ``core.config``: that loader rejects ``ground_truth_dir``, and
reading the file here keeps ``evaluate/`` free of any ``core`` import, so the
evaluator scores whatever wrote the files rather than only what this repo runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_TABLE_THRESHOLD = 0.5
EVALUATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALUATE_DIR.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"
RESULTS_DIR = REPO_ROOT / "data" / "results"

# config.yaml key each directory falls back to
PRED_KEY = "output_dir"
GT_KEY = "ground_truth_dir"


@dataclass(frozen=True)
class EvalConfig:
    """The two directories a tier compares."""

    pred_dir: Path
    gt_dir: Path


class ConfigError(Exception):
    """Raised when a directory is missing, or config.yaml cannot supply one."""


# Resolve both directories from the CLI, falling back to config.yaml for any left out.
def load_config(
    path: Path = DEFAULT_CONFIG_PATH,
    pred_dir: Path | None = None,
    gt_dir: Path | None = None,
) -> EvalConfig:
    parsed: dict = {}
    if pred_dir is None or gt_dir is None:
        if not path.exists():
            raise ConfigError(f"config not found: {path}")
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ConfigError(f"{path} must contain a mapping, got {type(loaded).__name__}")
        parsed = loaded

    resolved: dict[str, Path] = {}
    for key, given in ((PRED_KEY, pred_dir), (GT_KEY, gt_dir)):
        if given is not None:
            directory = given.resolve()
        elif parsed.get(key):
            # Relative paths in config.yaml are written from the repo root, not from cwd
            directory = (REPO_ROOT / str(parsed[key])).resolve()
        else:
            raise ConfigError(f"{path} is missing {key} and no directory was given for it")

        # A missing directory here is a config error, not an empty result set
        if not directory.is_dir():
            raise ConfigError(f"{key} is not a directory: {directory}")
        resolved[key] = directory

    return EvalConfig(pred_dir=resolved[PRED_KEY], gt_dir=resolved[GT_KEY])
