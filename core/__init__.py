"""ocr-core: pluggable OCR pipeline engine."""
from .config import Config, ConfigError, DEFAULTS, load
from .pipeline import DocumentRun, run_document, run_page

__all__ = [
    "Config",
    "ConfigError",
    "DEFAULTS",
    "DocumentRun",
    "load",
    "run_document",
    "run_page",
]
