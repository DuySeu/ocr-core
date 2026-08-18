# Folder-based page review (replace UI + SQLite)

Ngày: 2026-08-17. Trạng thái: **đã implement**.
Liên quan: [01-ocr.md](01-ocr.md), [2026-08-15-tesseract-pipeline-refactor-design.md](2026-08-15-tesseract-pipeline-refactor-design.md).

## 1 · Problem

Review hiện tại phụ thuộc FastAPI (`python -m orchestrate.review`) và SQLite
(`artifacts/state.db`: `needs_review` / `reviewed`). Muốn bỏ DB và UI: trang dưới
ngưỡng QA tự dump ra thư mục `review/` để sửa tay; trang/document đạt vẫn nằm ở
`output/`; sau khi sửa chạy một lệnh để ghi đè trang tương ứng trong output.

## 2 · Decisions (locked)

| # | Chốt | Loại |
| --- | --- | --- |
| 1 | Đơn vị QA / review = **trang** | Document-level all-or-nothing |
| 2 | Ngay sau OCR: **full** document luôn ghi `output/`; trang fail **đồng thời** dump `review/` | Partial output; chỉ ghi output sau khi review xong |
| 3 | Mỗi trang review = ảnh preprocess (`.webp`) + **một khối text** (`.md`), không JSON | Sửa từng TextLine có id; chỉ sửa markdown output bỏ COCO |
| 4 | Chỉ **`main.py`** dùng cơ chế này | `orchestrate run` cũng QA/review folder |
| 5 | Bỏ FastAPI **và** SQLite; **gỡ toàn bộ `orchestrate/`** | Giữ stub batch không-DB |
| 6 | Approach: mở rộng `main.py` + `apply-review`; module nhỏ `core/review_io.py` | Shared module nặng; giữ artifacts-first |

## 3 · CLI

```bash
# OCR một file: output đầy đủ + dump trang dưới ngưỡng
python main.py <path> [--config config.yaml] [--out DIR]

# Sau khi sửa tay các pNNNN.md trong review/<stem>/
python main.py apply-review <stem> [--config config.yaml]
```

`<stem>` = tên thư mục dưới `output/` và `review/` (stem của file nguồn).

## 4 · Layout on disk

```
output/<stem>/
  <stem>.md
  <stem>.coco.json
  <stem>.document.json          # snapshot Document (serde); nguồn cho apply-review

review/<stem>/
  p0003.webp                    # ảnh sau preprocess
  p0003.md                      # text trang cần sửa
  …
```

Config: thêm `review_dir: ./review` cạnh `output_dir`.  
`.gitignore`: thêm `review/*` (giữ `.gitkeep` nếu cần).

### 4.1 · `pNNNN.md` format

```markdown
<!-- page: 3 lines: 12 -->
dòng 1
dòng 2
…
```

- Dòng đầu là metadata (không phải nội dung sửa).
- Các dòng sau = đúng `lines:` `TextLine` theo `reading_order` trên trang đó
  (chỉ phần tử `TextContent`; bảng / formula không đưa vào file này).
- Reviewer sửa nội dung; **giữ nguyên số dòng**. Lệch số dòng → `apply-review` fail rõ, không ghi nửa vời.

## 5 · Behaviour

### 5.1 · `python main.py <path>`

1. `pipeline.run_document` (có trả thêm ảnh preprocess theo trang — xem §6).
2. `write_document` → `.md` + `.coco.json` dưới `output/<stem>/`.
3. Ghi `document_to_dict` → `<stem>.document.json`.
4. Với mỗi trang có elements: `qa.gate(elements, qa_threshold)`.
   - Pass / không có signal để fail → không dump.
   - Fail → ghi `review/<stem>/p{page:04d}.webp` + `.md`.
5. Trang không element / empty: giữ hành vi “không fail QA” (không dump).

### 5.2 · `python main.py apply-review <stem>`

1. Load `output/<stem>/<stem>.document.json`.
2. Với mỗi `review/<stem>/pNNNN.md` có mặt:
   - Parse `page` + `lines:` từ header; body split theo `\n`.
   - Nếu số dòng body ≠ số `TextLine` trên trang → raise, dừng (hoặc fail trang đó và không ghi document — **chốt: fail cả lệnh nếu bất kỳ trang nào lệch**).
   - Gán `TextLine.text` mới; **không** đổi `text_ocr`; rebuild `TextContent.text`.
3. `write_document` lại `.md` + `.coco.json`; cập nhật `.document.json`.
4. Xóa các `pNNNN.webp` / `pNNNN.md` đã apply thành công; xóa `review/<stem>/` nếu rỗng.

## 6 · Code changes

| Area | Change |
| --- | --- |
| `core/config.py`, `config.yaml` | `review_dir`; validate path string như các dir khác |
| `core/pipeline.py` | `run_document` trả thêm `dict[int, Image.Image]` (page → ảnh sau preprocess), hoặc dataclass kết quả mới — không đổi semantics Document |
| `core/review_io.py` (mới) | export page md+webp; apply page text; helpers path |
| `core/qa.py` | giữ nguyên `gate` |
| `main.py` | subparser: OCR path (default) + `apply-review`; wire review dump |
| `orchestrate/` | **xóa toàn bộ** package |
| `requirements.txt` | bỏ `fastapi`, `uvicorn`, `jinja2`, `python-multipart` nếu không còn dùng |
| `.gitignore` | `review/*` |
| `docs/01-ocr.md` (và chỗ nhắc review UI / SQLite) | cập nhật cho khớp |
| Tests | xem §7; xóa `tests/test_orchestrate_*` |

`core` vẫn không import evaluate/finetune. Evaluate vẫn chỉ đọc `.md` / `.coco.json` dưới `output/` (bỏ qua `.document.json`).

## 7 · Tests

- Export: số dòng md = số TextLine; header `page` / `lines` đúng.
- Apply: đúng số dòng → `text` đổi, `text_ocr` giữ; markdown output phản ánh text mới.
- Apply: lệch số dòng → lỗi, output không đổi.
- OCR path (integration nhẹ / tmp): trang dưới threshold → có file trong `review/`; trang trên → không.
- Apply xóa file review đã xử lý.
- Không còn test orchestrate review/state/runner.

## 8 · Out of scope / follow-ups

- Finetune hiện phụ thuộc `artifacts/` từ `orchestrate run`. Gỡ `orchestrate/` → finetune mất đường tạo artifact trong repo này cho đến khi có follow-up (vd. `main.py` ghi artifacts, hoặc CLI artifact riêng). Ghi nhận; **không** implement trong spec này.
- Không xây lại web UI.
- Không đổi công thức `qa_threshold` / `pipeline_version`.

## 9 · Risks (accepted)

- Reviewer đổi số dòng → phải sửa lại cho khớp `lines:`.
- Trang fail QA nhưng không có `TextLine` (chỉ bảng / empty text) → vẫn có `.webp`; không có `.md` hữu ích hoặc `.md` rỗng; apply bỏ qua trang không có text lines.
- `.document.json` là snapshot nội bộ; mất file này thì không apply được (phải OCR lại).
