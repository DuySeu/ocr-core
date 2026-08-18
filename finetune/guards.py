"""Two hard gates that every finetune command runs before cutting a line.

Stops early when the training binaries are missing, when ``vie.traineddata``
is the int-mode (fast) build, or when the ground-truth directory is empty.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from evaluate.ground_truth import discover_text

logger = logging.getLogger(__name__)

FINETUNE_DIR = Path(__file__).resolve().parent
TESSDATA_DIR = FINETUNE_DIR / "tessdata"
DATA_DIR = FINETUNE_DIR / "data"
WORK_DIR = FINETUNE_DIR / "work"

BASE_TRAINEDDATA = TESSDATA_DIR / "vie.traineddata"
OSD_TRAINEDDATA = TESSDATA_DIR / "osd.traineddata"
OUTPUT_TRAINEDDATA = TESSDATA_DIR / "vie_lpbank.traineddata"

REQUIRED_BINARIES = ("lstmtraining", "combine_tessdata")


class GuardError(Exception):
    """Raised when a finetune gate fails before any work starts."""


# Run every gate; raise GuardError on the first failure.
def check(ground_truth_dir: Path | None = None) -> None:
    _require_binaries()
    _require_best_traineddata()
    if ground_truth_dir is not None:
        _require_ground_truth(ground_truth_dir)


# Fail when lstmtraining or combine_tessdata is not on PATH.
def _require_binaries() -> None:
    missing = [name for name in REQUIRED_BINARIES if shutil.which(name) is None]
    if not missing:
        return
    names = ", ".join(missing)
    raise GuardError(
        f"missing training binary: {names}. "
        "Install tesseract training tools "
        "(e.g. `brew install tesseract` on macOS)."
    )


# Fail when vie.traineddata is missing or is the int_mode (fast) build.
def _require_best_traineddata() -> None:
    if not BASE_TRAINEDDATA.is_file():
        raise GuardError(
            f"missing {BASE_TRAINEDDATA}. Download the best build:\n"
            "  mkdir -p finetune/tessdata\n"
            "  curl -L -o finetune/tessdata/vie.traineddata \\\n"
            "    https://github.com/tesseract-ocr/tessdata_best"
            "/raw/main/vie.traineddata"
        )

    # Check only vie.traineddata by name; ignore vie_lpbank next to it
    result = subprocess.run(
        ["combine_tessdata", "-l", str(BASE_TRAINEDDATA)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if "int_mode=1" in output:
        raise GuardError(
            f"{BASE_TRAINEDDATA} is tessdata_fast (int_mode=1). "
            "Replace it with the best build from "
            "tesseract-ocr/tessdata_best."
        )
    if result.returncode != 0:
        raise GuardError(
            f"combine_tessdata -l failed on {BASE_TRAINEDDATA}: "
            f"{output.strip() or result.returncode}"
        )


# Fail when the ground-truth directory has no readable text files.
def _require_ground_truth(directory: Path) -> None:
    if not directory.is_dir():
        raise GuardError(f"ground-truth directory not found: {directory}")
    found = discover_text(directory)
    if not found:
        raise GuardError(
            f"no ground-truth files under {directory}. "
            "Clone or copy LPBank .md files into ground_truth/lpbank/."
        )
    logger.info("ground truth: %d file(s) under %s", len(found), directory)
