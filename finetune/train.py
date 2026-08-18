"""Wrapper around combine_tessdata + lstmtraining for vie_lpbank."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from finetune.guards import (
    BASE_TRAINEDDATA,
    DATA_DIR,
    OUTPUT_TRAINEDDATA,
    TESSDATA_DIR,
    WORK_DIR,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 3000
LIST_TRAIN = DATA_DIR / "list.train"


class TrainError(Exception):
    """Raised when a training binary step fails."""


# Extract LSTM, fine-tune, and write vie_lpbank.traineddata.
def train(
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    list_train: Path | None = None,
    tessdata_dir: Path | None = None,
    work_dir: Path | None = None,
) -> Path:
    tessdata = tessdata_dir or TESSDATA_DIR
    work = work_dir or WORK_DIR
    train_list = list_train or LIST_TRAIN
    base = tessdata / BASE_TRAINEDDATA.name
    output = tessdata / OUTPUT_TRAINEDDATA.name

    if not train_list.is_file():
        raise TrainError(f"missing train list: {train_list}")
    if not base.is_file():
        raise TrainError(f"missing base traineddata: {base}")

    work.mkdir(parents=True, exist_ok=True)
    tessdata.mkdir(parents=True, exist_ok=True)
    lstm_path = work / "vie.lstm"
    model_prefix = work / "vie_lpbank"

    # Extract the float LSTM from the best traineddata
    _run(
        [
            "combine_tessdata",
            "-e",
            str(base),
            str(lstm_path),
        ]
    )

    # Fine-tune from the extracted LSTM
    _run(
        [
            "lstmtraining",
            "--continue_from",
            str(lstm_path),
            "--traineddata",
            str(base),
            "--train_listfile",
            str(train_list.resolve()),
            "--model_output",
            str(model_prefix),
            "--max_iterations",
            str(max_iterations),
        ]
    )

    checkpoint = _latest_checkpoint(work, "vie_lpbank")
    if checkpoint is None:
        raise TrainError(
            f"no checkpoint matching vie_lpbank* under {work}"
        )

    # Pack the checkpoint into a shippable .traineddata
    _run(
        [
            "lstmtraining",
            "--stop_training",
            "--continue_from",
            str(checkpoint),
            "--traineddata",
            str(base),
            "--model_output",
            str(output),
        ]
    )

    if not output.is_file():
        raise TrainError(f"traineddata was not written: {output}")
    logger.info("wrote %s", output)
    return output


# Run a training binary; raise TrainError on non-zero exit.
def _run(cmd: list[str]) -> None:
    logger.info("running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    raise TrainError(
        f"command failed ({result.returncode}): {' '.join(cmd)}\n{detail}"
    )


# Pick the newest checkpoint file for a model prefix.
def _latest_checkpoint(work: Path, prefix: str) -> Path | None:
    candidates = sorted(
        work.glob(f"{prefix}_checkpoint*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    # Some builds write prefix_N.checkpoint without the word "checkpoint" alone
    numbered = sorted(
        work.glob(f"{prefix}*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in numbered:
        if path.suffix == ".lstm" and path.name != "vie.lstm":
            return path
        if "checkpoint" in path.name:
            return path
    return None
