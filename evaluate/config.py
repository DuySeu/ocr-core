"""Reading config.yaml into the paths and thresholds one evaluation run needs.

This does not reuse ``core.config``. That loader rejects any key outside
``Config.__dataclass_fields__`` — which ``ground_truth_dir`` is not — and its
``VALID_ENGINES`` set does not name every engine there is output for. Reading the
file here is also what keeps ``evaluate/`` free of any ``core`` import, so the
evaluator scores whatever wrote the files rather than only what this repo runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_IOU_THRESHOLD = 0.5
DEFAULT_TABLE_THRESHOLD = 0.5
EVALUATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALUATE_DIR.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"

# The keys scoring cannot run without. Everything else in config.yaml belongs to
# the pipeline and is ignored here rather than rejected.
REQUIRED_KEYS = ("engine", "output_dir", "ground_truth_dir")


@dataclass(frozen=True)
class EvalConfig:
    """Which engine's output is scored, against what, and how strictly."""

    engine: str
    output_dir: Path
    ground_truth_dir: Path
    iou_threshold: float = DEFAULT_IOU_THRESHOLD
    table_threshold: float = DEFAULT_TABLE_THRESHOLD

    @property
    def results_dir(self) -> Path:
        return EVALUATE_DIR / "results" / self.engine


class ConfigError(Exception):
    """Raised when config.yaml is missing, malformed, or lacks a key scoring needs."""


# Read config.yaml and resolve its directories against the repo root.
def load_config(
    path: Path = DEFAULT_CONFIG_PATH,
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
    table_threshold: float = DEFAULT_TABLE_THRESHOLD,
) -> EvalConfig:
    if not path.exists():
        raise ConfigError(f"config not found: {path}")

    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ConfigError(f"{path} must contain a mapping, got {type(parsed).__name__}")

    missing = [key for key in REQUIRED_KEYS if not parsed.get(key)]
    if missing:
        raise ConfigError(f"{path} is missing {', '.join(missing)}")

    # Relative paths in config.yaml are written from the repo root, not from cwd
    output_dir = (REPO_ROOT / str(parsed["output_dir"])).resolve()
    ground_truth_dir = (REPO_ROOT / str(parsed["ground_truth_dir"])).resolve()

    # A missing directory here is a config error, not an empty result set
    for label, directory in (("output_dir", output_dir), ("ground_truth_dir", ground_truth_dir)):
        if not directory.is_dir():
            raise ConfigError(f"{path}: {label} is not a directory: {directory}")

    return EvalConfig(
        engine=str(parsed["engine"]),
        output_dir=output_dir,
        ground_truth_dir=ground_truth_dir,
        iou_threshold=iou_threshold,
        table_threshold=table_threshold,
    )
