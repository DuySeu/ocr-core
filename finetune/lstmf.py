"""Turn labelled line crops into .lstmf files and list.train."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from finetune.guards import DATA_DIR, TESSDATA_DIR

logger = logging.getLogger(__name__)

MIN_TRAIN_LINES = 50
LIST_TRAIN = DATA_DIR / "list.train"


class LstmfError(Exception):
    """Raised when no usable .lstmf set can be built."""


@dataclass(frozen=True)
class LstmfReport:
    """How many .lstmf files one build wrote."""

    written: int
    failed: int
    list_train: Path


# Encode every png+.gt.txt pair under data_dir into .lstmf; write list.train.
def build_lstmf(
    data_dir: Path | None = None,
    tessdata_dir: Path | None = None,
    list_train: Path | None = None,
    min_lines: int = MIN_TRAIN_LINES,
) -> LstmfReport:
    root = data_dir or DATA_DIR
    tessdata = tessdata_dir or TESSDATA_DIR
    out_list = list_train or LIST_TRAIN
    out_list.parent.mkdir(parents=True, exist_ok=True)

    pairs = _labelled_pairs(root)
    written_paths: list[Path] = []
    failed = 0

    for png_path, gt_path in pairs:
        lstmf = png_path.with_suffix(".lstmf")
        # tesseract writes <basename>.lstmf next to the image
        cmd = [
            "tesseract",
            str(png_path),
            str(png_path.with_suffix("")),
            "-l",
            "vie",
            "--tessdata-dir",
            str(tessdata.resolve()),
            "--psm",
            "13",
            "lstm.train",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
        if result.returncode != 0 or not lstmf.is_file():
            failed += 1
            logger.warning(
                "lstmf failed for %s: %s",
                png_path.name,
                (result.stderr or result.stdout).strip(),
            )
            continue
        written_paths.append(lstmf.resolve())

    if len(written_paths) < min_lines:
        raise LstmfError(
            f"list.train would have {len(written_paths)} line(s), "
            f"need at least {min_lines}. "
            f"failed={failed}, pairs={len(pairs)}"
        )

    out_list.write_text(
        "\n".join(str(p) for p in written_paths) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "wrote %d .lstmf -> %s (%d failed)",
        len(written_paths),
        out_list,
        failed,
    )
    return LstmfReport(
        written=len(written_paths),
        failed=failed,
        list_train=out_list,
    )


# Find every png that has a sibling .gt.txt under data_dir.
def _labelled_pairs(data_dir: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for gt_path in sorted(data_dir.rglob("*.gt.txt")):
        png_name = gt_path.name[: -len(".gt.txt")] + ".png"
        png_path = gt_path.with_name(png_name)
        if png_path.is_file():
            pairs.append((png_path, gt_path))
    return pairs
