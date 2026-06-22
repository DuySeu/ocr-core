#!/usr/bin/env bash
# Create the working folders the project needs (gitignored, absent after a fresh clone).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p input output invoice legal
echo "ready: input/ output/ invoice/ legal/"

# Pick a Python launcher: python3 on *nix, python on Windows/Git-Bash.
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "error: python not found in PATH" >&2; exit 1
fi

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
elif command -v winget >/dev/null 2>&1; then
  winget install -e --id UB-Mannheim.TesseractOCR || echo "note: cai Tesseract thu cong" >&2
  echo "note (Windows): cai them Vietnamese lang data + poppler thu cong, them poppler/bin vao PATH (https://github.com/oschwartz10612/poppler-windows)" >&2
elif command -v choco >/dev/null 2>&1; then
  choco install -y tesseract poppler || echo "note: cai tesseract/poppler thu cong" >&2
else
  echo "skip system deps: install tesseract (+vie) and poppler manually" >&2
fi

# Python deps: into the active venv if one is already activated, else create .venv.
if [ -n "${VIRTUAL_ENV:-}" ]; then
  "$PY" -m pip install -r requirements.txt
  echo "deps installed into active env: $VIRTUAL_ENV"
else
  "$PY" -m venv .venv
  # venv layout: Scripts/ on Windows, bin/ elsewhere.
  VENV_PY=.venv/bin/python
  [ -x "$VENV_PY" ] || VENV_PY=.venv/Scripts/python.exe
  "$VENV_PY" -m pip install -r requirements.txt
  echo "deps installed into .venv/"
fi
