"""One adapter module per engine, dispatched by the ``engine`` key in config.yaml.

Adding an engine is adding ``<engine>.py`` with a ``read_documents`` function and
one line in ``ADAPTERS``. An engine absent from that table fails by name rather
than falling back to a guess, because a guessed reader scores the wrong files and
reports a number as if it meant something.
"""

from __future__ import annotations

from pathlib import Path

from . import chandra, easyocr, paddleocr, tesseract
from .base import PredictionDoc

ADAPTERS = {
    "chandra": chandra.read_documents,
    "tesseract": tesseract.read_documents,
    "paddleocr": paddleocr.read_documents,
    "easyocr": easyocr.read_documents,
}

__all__ = ["ADAPTERS", "PredictionDoc", "UnknownEngineError", "read_documents"]


class UnknownEngineError(Exception):
    """Raised when config.yaml names an engine no adapter can read."""


# Read every document an engine wrote, dispatching on the engine name.
def read_documents(engine: str, output_dir: Path) -> list[PredictionDoc]:
    adapter = ADAPTERS.get(engine)
    if adapter is None:
        raise UnknownEngineError(
            f"no adapter for engine {engine!r}; add evaluate/engines/{engine}.py "
            f"or pick one of {sorted(ADAPTERS)}"
        )

    return adapter(output_dir)
