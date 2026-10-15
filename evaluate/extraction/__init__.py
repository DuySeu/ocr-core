"""Tier 3, Extraction & Structure. Not implemented yet.

Input will be predicted ``<doc_id>.json`` records in the ground-truth schema, scored
against ``fields`` of the dataset, after normalization (docs/specs/benchmark-ocr.md, section 4):

- Field-level precision / recall / F1, exact match.
- Document-level accuracy: every required field matches.
- Null accuracy / hallucinated field rate on fields that are ``null`` in the GT.

A document whose GT has no fields is not scoreable, not a zero.
"""

from __future__ import annotations

from pathlib import Path


# Score predicted field records against the dataset in gt_dir.
def run(pred_dir: Path, gt_dir: Path) -> None:
    raise NotImplementedError("the Extraction & Structure tier is not implemented yet")
