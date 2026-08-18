"""Configuration model and defaults."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path


class ConfigError(Exception):
    """Raised for invalid configuration."""


VALID_ENGINES = {"tesseract", "paddleocr", "easyocr"}
VALID_STEPS = {"grayscale", "binarize", "orientation", "deskew", "denoise"}
VALID_LAYOUTS = {"tesseract", "none"}
VALID_TABLE = {"cv", "none"}
VALID_OUTPUTS = {"markdown", "coco"}

# Config fields excluded from the pipeline_version hash: they name where files
# live, not how a page is produced, so moving output/ shouldn't invalidate a
# checkpoint (§5.1).
_PATH_FIELDS = frozenset(
    {"input_dir", "output_dir", "review_dir", "artifacts_dir", "ground_truth_dir"}
)


@dataclass
class Config:
    engine: str = "tesseract"
    langs: list[str] = field(default_factory=lambda: ["vie"])
    dpi: int = 300
    preprocess_steps: list[str] = field(
        default_factory=lambda: ["orientation", "deskew", "denoise"]
    )
    layout: str = "tesseract"
    table: str = "cv"
    outputs: list[str] = field(default_factory=lambda: ["markdown", "coco"])
    qa_threshold: float = 0.75
    input_dir: str = "./dataset/lpbank"
    output_dir: str = "./output"
    review_dir: str = "./review"
    ground_truth_dir: str = "./ground_truth/lpbank"
    artifacts_dir: str = "./artifacts"

    def validate(self) -> "Config":
        if self.engine not in VALID_ENGINES:
            raise ConfigError(f"unknown engine {self.engine!r}; valid: {sorted(VALID_ENGINES)}")
        if not isinstance(self.langs, list) or not self.langs or not all(
            isinstance(x, str) for x in self.langs
        ):
            raise ConfigError(f"langs must be a non-empty list of strings, got {self.langs!r}")
        for step in self.preprocess_steps:
            if step not in VALID_STEPS:
                raise ConfigError(f"unknown step {step!r}; valid: {sorted(VALID_STEPS)}")
        if self.layout not in VALID_LAYOUTS:
            raise ConfigError(f"unknown layout {self.layout!r}; valid: {sorted(VALID_LAYOUTS)}")
        if self.table not in VALID_TABLE:
            raise ConfigError(f"unknown table {self.table!r}; valid: {sorted(VALID_TABLE)}")
        unknown_outputs = set(self.outputs) - VALID_OUTPUTS
        if unknown_outputs:
            raise ConfigError(f"unknown output(s) {sorted(unknown_outputs)}; valid: {sorted(VALID_OUTPUTS)}")
        if self.layout == "tesseract" and self.engine != "tesseract":
            raise ConfigError(
                "layout='tesseract' groups words by Tesseract's block_num, which no "
                f"other engine reports; engine must be 'tesseract', got {self.engine!r}"
            )
        if not 0 <= self.qa_threshold <= 1:
            raise ConfigError(f"qa_threshold must be in [0, 1], got {self.qa_threshold!r}")
        return self


DEFAULTS = Config()

_ALLOWED_KEYS = set(Config.__dataclass_fields__)


def load(
    path: str | None = None, overrides: dict | None = None, base: Config = DEFAULTS
) -> Config:
    """Build config: base < file < overrides (CLI flags)."""
    cfg = base
    if path:
        text = Path(path).read_text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            import yaml  # lazy: only needed for YAML files

            data = yaml.safe_load(text)
        cfg = _merge(cfg, data or {})
    if overrides:
        cfg = _merge(cfg, overrides)
    return cfg.validate()


def _merge(cfg: Config, data: dict) -> Config:
    bad = set(data) - _ALLOWED_KEYS
    if bad:
        raise ConfigError(f"unknown config keys: {sorted(bad)}")
    return replace(cfg, **{k: v for k, v in data.items() if v is not None})


# Fingerprint the parts of Config that change a page's pixels or content, so
# a checkpoint keyed on this string is invalidated exactly when it should be.
def pipeline_version(cfg: Config) -> str:
    hashed = {k: v for k, v in vars(cfg).items() if k not in _PATH_FIELDS}
    digest = hashlib.sha256(json.dumps(hashed, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    return f"{cfg.engine}_{'+'.join(cfg.langs)}_{cfg.layout}_{cfg.table}_{digest}"
