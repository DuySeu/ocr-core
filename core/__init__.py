"""ocr-core: pluggable OCR pipeline engine."""
from .config import Config, ConfigError, DEFAULTS, load
from .pipeline import run, run_to_file

__all__ = ["Config", "ConfigError", "DEFAULTS", "load", "run", "run_to_file"]
