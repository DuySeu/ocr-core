"""Stage 6: one Document in, the requested output files out."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..document.model import Document
from .coco import to_coco
from .markdown import to_markdown

logger = logging.getLogger(__name__)

VALID_OUTPUTS = frozenset({"markdown", "coco"})
__all__ = ["SerializeError", "to_coco", "to_markdown", "write_document"]


class SerializeError(Exception):
    """Raised when an unknown output format is requested."""


# Write the requested outputs for one document; returns the paths written.
def write_document(doc: Document, out_dir: str | Path, outputs: list[str]) -> list[Path]:
    unknown = set(outputs) - VALID_OUTPUTS
    if unknown:
        raise SerializeError(f"unknown output(s) {sorted(unknown)}; valid: {sorted(VALID_OUTPUTS)}")

    directory = Path(out_dir)
    stem = directory.name
    written = []

    if "markdown" in outputs:
        path = directory / f"{stem}.md"
        path.write_text(to_markdown(doc), encoding="utf-8")
        written.append(path)

    if "coco" in outputs:
        path = directory / f"{stem}.coco.json"
        path.write_text(
            json.dumps(to_coco(doc), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written.append(path)

    logger.info("wrote %s", ", ".join(str(p) for p in written))
    return written
