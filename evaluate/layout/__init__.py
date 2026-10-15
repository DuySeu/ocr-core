"""Tier 1, Detection & Layout. Not implemented yet.

Input will be predicted ``<doc_id>.json`` records in the ground-truth schema, scored
against ``pages[].blocks`` of the dataset (docs/README.md, section 4):

- Detection precision / recall / F1 at IoU >= 0.5 against ``blocks[].bbox``.
- Region classification accuracy against ``blocks[].type``.
- Reading order accuracy against ``blocks[].order``.

A document whose GT has no blocks is not scoreable, not a zero.
"""

from __future__ import annotations

from pathlib import Path


# Score predicted layout records against the dataset in gt_dir.
def run(pred_dir: Path, gt_dir: Path) -> None:
    raise NotImplementedError("the Detection & Layout tier is not implemented yet")
