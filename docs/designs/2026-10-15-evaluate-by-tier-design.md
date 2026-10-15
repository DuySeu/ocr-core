# Evaluate theo tầng

Ngày: 2026-10-15. Trạng thái: tầng Recognition triển khai, tầng Detection & Layout và Extraction & Structure chỉ có khung.

## Mục tiêu

`evaluate/` không chấm theo engine nữa mà theo 3 tầng trong [docs/specs/benchmark-ocr.md](../specs/benchmark-ocr.md). Một bộ ground truth chuẩn dùng chung cho cả 3 tầng. Mỗi tầng có metric riêng, đọc input riêng, ghi report riêng. Tầng Recognition triển khai đúng principles trong [evaluate/README.md](../../evaluate/README.md): WER có marker ảnh, TEDS, không có chế độ raw, không có CER.

## Bộ ground truth chuẩn

Mỗi tài liệu là hai file nằm cạnh nhau trong `ground_truth/<dataset>/`:

```
<doc_id>.json    doc_id, file, metadata, normalization_version, text_file, pages, fields
<doc_id>.md      text GT, kể cả <table> và <!-- image -->
```

Schema theo docs/specs/benchmark-ocr.md, khác một chỗ: `full_text` được thay bằng `"text_file": "<doc_id>.md"`, để người sửa GT vẫn sửa markdown. `pages` (blocks có bbox, type, order, content) và `fields` được phép rỗng cho tới khi annotate; tầng cần dữ liệu đó mà thấy rỗng thì báo không chấm được, không tính 0.

`ground_truth.load_dataset(dir)` đọc mọi `*.json` trong thư mục. JSON hỏng, thiếu `doc_id` hoặc `text_file`, file `.md` không tồn tại, hai JSON trùng `doc_id`: đều raise `GroundTruthError` và nêu tên file.

Chuyển GT cũ một lần bằng `python -m evaluate.ground_truth SRC [--out DST] [--source-dir DIR]`:

- `.md` / `.markdown` / `.txt`: sinh `<stem>.json` cạnh `<stem>.md` (file `.txt`, `.markdown` được chép thành `.md`).
- `.docx`: sinh `<stem>.md` (đoạn văn theo thứ tự, bảng thành `<table>` qua `walk_docx_cells`) và `<stem>.json`. Không ghi được vào cùng thư mục với `.docx`, vì `discover_text` sẽ thấy hai file trùng stem; phải chỉ `--out` sang thư mục khác.
- `--source-dir`: nếu có file gốc cùng stem thì điền vào `file`, không có thì `null`.
- JSON đã tồn tại thì giữ nguyên, không ghi đè.

`discover_text` và `load` giữ nguyên hành vi vì `finetune/align.py` và `finetune/guards.py` đang dùng. Sau khi chuyển, `discover_text` vẫn trả về `.md` (file `.json` không thuộc đuôi nó đọc).

## Cấu trúc package

```
evaluate/
  __main__.py          python -m evaluate <tier> ...
  config.py            output_dir, ground_truth_dir trong config.yaml làm giá trị mặc định
  ground_truth.py      schema GT, load_dataset, convert, discover_text, load
  table_extract.py     trích bảng từ markdown/HTML/docx, dùng chung cho GT và Recognition
  recognition/
    __init__.py        run() -> RecognitionReport
    normalize.py       mark_images, strip_figures, strict
    wer.py             WER có marker wildcard và ignored
    tables.py          cây bảng, TEDS, ghép bảng
    report.py          render và ghi report
  layout/__init__.py      khung, run() raise NotImplementedError
  extraction/__init__.py  khung, như trên
  results/<tier>/<label>/<dataset>.md
```

`table_extract.py` ở lại gốc package thay vì gộp vào `recognition/tables.py`, vì bước chuyển docx của `ground_truth.py` cũng cần nó; để trong `recognition/` thì phần GT dùng chung phải import một tầng.

Xóa: `engines/`, `loader.py`, `matching.py`, `metrics/`, `report.py`, `run.py`, `normalize.py` gốc (chuyển vào `recognition/`), `__init__.py` cũ cùng các test của chúng. Code IoU/COCO lấy lại từ git khi triển khai tầng 1.

## Tầng Recognition

```bash
python -m evaluate recognition [--pred DIR] [--gt DIR] [--label NAME] [--doc ID] [--table-threshold 0.5] [--config PATH]
```

1. Ghép cặp: đọc GT bằng `load_dataset`, quét `--pred` đệ quy lấy `*.md`, ghép theo `doc_id` bằng stem. Phần sau `<!-- ann-aside -->` ở pred bị bỏ. Hai pred trùng stem thì raise. Thiếu một bên thì ghi vào mục `unpaired`.
2. WER: GT chạy `mark_images` rồi `strict`, pred chạy `strict`, tách từ theo khoảng trắng.
3. TEDS: trích bảng ở cả hai phía bằng `extract_html_tables`, text trong ô qua `strip_figures`, ghép tham lam theo (điểm cấu trúc, TEDS, index).
4. Report ở `evaluate/results/recognition/<label>/<dataset>.md`. `label` mặc định là tên thư mục pred, `dataset` là tên thư mục GT.

### Thuật toán WER có marker

- GT không có marker: Levenshtein trên danh sách từ, như trước.
- GT có marker:
  1. Bỏ marker, căn chỉnh pred với các từ GT bằng `Levenshtein.opcodes`.
  2. Cắt các đoạn `equal` tại vị trí marker, giữ đoạn dài từ 3 từ trở lên làm neo. Neo không bao giờ chứa marker, nên chữ engine đọc từ ảnh không bị một đoạn khớp dài nuốt mất.
  3. Mỗi khoảng giữa hai neo: có marker thì DP với marker là wildcard (tiêu thụ 0 hoặc nhiều từ pred, chi phí 0, mỗi từ cộng 1 vào `ignored`), không có marker thì Levenshtein thường.
  4. DP so chi phí `(lỗi, ignored)` theo thứ tự từ điển, nên khi bằng lỗi thì chọn cách bỏ qua ít từ nhất.
- DP là O(n·m) trên một khoảng, viết bằng Python thuần. Tài liệu có marker mà không có neo nào thì khoảng là toàn văn bản; vài nghìn từ mỗi bên chạy trong vài giây, 10k từ mỗi bên thì cỡ phút.

## Tầng Detection & Layout và Extraction & Structure

Chỉ có module với docstring nêu input (JSON prediction cùng schema với GT), metric dự kiến theo docs/specs/benchmark-ocr.md, và `run()` raise `NotImplementedError`. `python -m evaluate layout` in lỗi "chưa triển khai" và trả mã 1.

## Test

- `test_recognition_wer.py`: 7 ví dụ trong bảng ở evaluate/README.md, pred rỗng, GT rỗng, GT chỉ có marker.
- `test_recognition_normalize.py`: các test chuẩn hóa cũ (bỏ phần tone-blind), thêm marker, `[hình: ...]`, entity.
- `test_recognition_tables.py`: các test TEDS và ghép bảng cũ (bỏ phần chấm theo bbox), thêm ảnh trong ô.
- `test_recognition.py`: ghép cặp, unpaired, trùng stem, dòng pooled, đường dẫn report, CLI tầng chưa có.
- `test_ground_truth.py`: giữ test `load`/`discover_text`, thêm `load_dataset` và `convert`.
