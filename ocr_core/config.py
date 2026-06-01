"""Configuration model and defaults."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path


class ConfigError(Exception):
    """Raised for invalid configuration."""


VALID_ENGINES = {"tesseract"}
VALID_STEPS = {"grayscale", "deskew", "binarize"}
# mode -> granularity hợp lệ: text cho prose (không bbox), data cho line (có bbox)
VALID_GRANULARITY = {"text": {"page", "paragraph"}, "data": {"line"}}


@dataclass
class Config:
    engine: str = "tesseract"
    lang: str = "vie" # eng, vie
    mode: str = "data"  # "text" | "data"
    granularity: str = "line"  # "page" | "paragraph" | "line"
    preprocess_steps: list[str] = field(
        default_factory=lambda: ["grayscale", "deskew", "binarize"]
    )
    input_dir: str = "./input"
    output_dir: str = "./out"

    def validate(self) -> "Config":
        if self.engine not in VALID_ENGINES:
            raise ConfigError(
                f"unknown engine {self.engine!r}; valid: {sorted(VALID_ENGINES)}"
            )
        if self.mode not in VALID_GRANULARITY:
            raise ConfigError(
                f"unknown mode {self.mode!r}; valid: {sorted(VALID_GRANULARITY)}"
            )
        if self.granularity not in VALID_GRANULARITY[self.mode]:
            raise ConfigError(
                f"granularity {self.granularity!r} invalid for mode {self.mode!r}; "
                f"valid: {sorted(VALID_GRANULARITY[self.mode])}"
            )
        for step in self.preprocess_steps:
            if step not in VALID_STEPS:
                raise ConfigError(
                    f"unknown step {step!r}; valid: {sorted(VALID_STEPS)}"
                )
        return self


DEFAULTS = Config()

# Pipeline profiles: name -> default Config. New pipeline = add an entry here.
PIPELINES: dict[str, "Config"] = {
    "legal": Config(mode="text", granularity="paragraph"),
    "invoice": Config(mode="data", granularity="line"),
}

_ALLOWED_KEYS = set(Config.__dataclass_fields__)


def load(path: str | None = None, overrides: dict | None = None,
         base: Config = DEFAULTS) -> Config:
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
