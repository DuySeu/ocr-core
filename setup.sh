#!/usr/bin/env bash
# Create the working folders the project needs (gitignored, absent after a fresh clone).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p input output invoice legal
echo "ready: input/ output/ invoice/ legal/"

# System binaries (tesseract + vie lang, poppler) — pick command per OS.
if command -v brew >/dev/null 2>&1; then
  brew install tesseract tesseract-lang poppler
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y tesseract-ocr tesseract-ocr-vie poppler-utils libgl1
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y poppler-utils mesa-libGL
  command -v tesseract >/dev/null 2>&1 || \
    echo "note: tesseract khong co trong repo AL2023/Fedora mac dinh — dung engine paddleocr (da cai qua pip) hoac build tesseract tu nguon" >&2
else
  echo "skip system deps: install tesseract (+vie) and poppler manually" >&2
fi

# Python deps: into the active venv if one is already activated, else create .venv.
if [ -n "${VIRTUAL_ENV:-}" ]; then
  python -m pip install -r requirements.txt
  echo "deps installed into active env: $VIRTUAL_ENV"
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
  echo "deps installed into .venv/"
fi
