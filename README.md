# ocr-core

Pipeline OCR cho tài liệu tiếng Việt: PDF/ảnh -> tiền xử lý -> layout -> nhận dạng -> `.md` (tùy chọn `.coco.json`), trang dưới ngưỡng QA được dump ra để sửa tay. Kèm hai luồng phụ: fine-tune Tesseract (`finetune/`) và chấm điểm theo tầng (`evaluate/`).

## Cài đặt

```bash
./setup.sh                 # tạo data/, cài tesseract (+vie), tạo .venv và cài requirements.txt
source .venv/bin/activate
```

PDF được nạp bằng `pypdfium2`, không cần Poppler. PaddleOCR và EasyOCR là opt-in: `pip install paddleocr paddlepaddle` hoặc `pip install easyocr`.

## Sử dụng

```bash
python -m core data/raw/lpbank/doc.pdf            # OCR -> <output_dir>/doc/ (+ trang yếu -> data/review/doc/)
python -m core data/raw/lpbank/doc.pdf --out data/output/paddleocr/lpbank
python -m core apply-review doc                   # đọc data/review/doc/p*.md, ghi lại <output_dir>/doc/
python -m evaluate recognition --label tesseract  # chấm WER/TEDS, xem evaluate/README.md
python -m finetune pipeline --sha <sha> --version <version>   # xem finetune/README.md
```

Mỗi tài liệu ra `<output_dir>/<stem>/`: `<stem>.md`, `<stem>.document.json`, và `<stem>.coco.json` khi `outputs` có `coco`.

## Cấu hình

`config.yaml` ở gốc repo được đọc mặc định (`--config` để chỉ file khác). Thứ tự ưu tiên: default trong `core/config.py` < file config < cờ CLI.

| Key | Giá trị | Mặc định |
| --- | --- | --- |
| `engine` | `tesseract`, `paddleocr`, `easyocr` | `tesseract` |
| `langs` | danh sách mã ngôn ngữ | `[vie]` |
| `dpi` | độ phân giải render PDF | `300` |
| `preprocess_steps` | `grayscale`, `binarize`, `orientation`, `deskew`, `denoise` | `[orientation, deskew, denoise]` |
| `layout` | `tesseract` (chỉ với engine tesseract), `none` | `tesseract` |
| `table` | `cv`, `none` | `cv` |
| `outputs` | `markdown`, `coco` | `[markdown]` |
| `qa_threshold` | 0..1, trang dưới ngưỡng ra `review_dir` | `0.75` |
| `input_dir`, `output_dir`, `review_dir`, `artifacts_dir`, `ground_truth_dir` | đường dẫn | dưới `data/` |

## Cấu trúc thư mục

```
config.yaml  requirements.txt  setup.sh
core/                 pipeline OCR (CLI: python -m core): loader, preprocess, layout/, recognize/, document/, serialize/, engines/
evaluate/             chấm theo tầng: recognition/ (đã có), layout/, extraction/ (khung)
finetune/             fine-tune Tesseract LSTM -> vie_lpbank.traineddata
tests/                core/, evaluate/, finetune/  (chạy: python -m pytest -q)
docs/                 guides/, specs/, designs/, diagrams/  (mục lục: docs/README.md)
data/                 không commit, chỉ giữ .gitkeep
  raw/<dataset>/[<condition>/]        tài liệu gốc (PDF, ảnh)
  ground_truth/<dataset>/             <doc_id>.json + <doc_id>.md
  output/<engine>/<dataset>/<stem>/   kết quả OCR
  review/<stem>/                      trang dưới ngưỡng QA để sửa tay
  results/<tier>/<label>/<dataset>.md report evaluate
  artifacts/                          artifact theo sha/version cho finetune
  models/finetune/{tessdata,data,work}
```

## Thêm OCR engine

Implement `OCREngine` trong `core/engines/base.py`, thêm class vào `_ENGINES` trong `core/engines/__init__.py`, rồi thêm tên vào `VALID_ENGINES` trong `core/config.py`.

## Kiểm thử

```bash
python -m pytest -q
```

Dùng `python -m pytest` thay vì `pytest`: lệnh `python -m` đặt gốc repo vào `sys.path` để import được `core`, `evaluate`, `finetune`.
