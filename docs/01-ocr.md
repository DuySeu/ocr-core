# Luồng 1 · OCR

Ngày: 2026-08-17. Trạng thái: **đã implement**.  
Thiết kế pipeline: [2026-08-15-tesseract-pipeline-refactor-design.md](2026-08-15-tesseract-pipeline-refactor-design.md).  
Review folder (thay UI/SQLite): [2026-08-17-folder-review-design.md](2026-08-17-folder-review-design.md).  
Sơ đồ tổng: [kien-truc-trien-khai.md](kien-truc-trien-khai.md).

Biến PDF/ảnh thành văn bản có cấu trúc (`.md` + `.coco.json`), QA theo ngưỡng, trang dưới ngưỡng dump ra `review/` để sửa tay. Package: `core/` (+ `main.py`).

Luồng liên quan: [02 trích xuất](02-trich-xuat.md) · [03 fine-tune](03-finetune.md) · [04 evaluation](04-evaluation.md).

## 1 · Quyết định

| # | Đã chốt | Bị loại |
| --- | --- | --- |
| 1 | Engine mặc định **Tesseract 5**; layout = block Tesseract + `table_cv` | Chandra one-pass; PP-DocLayout |
| 2 | QA theo trang; **không** `.html`, **không** searchable PDF | Làm cả bốn |
| 3 | Review = folder `review/` + `apply-review` (không FastAPI / SQLite) | Redis/Celery; review UI |
| 4 | Giữ `core/engines/` và `core/tables.py`; xoá extract/postprocess cũ | Hai đường chạy song song |

Tiêu chí thành công: **luồng chạy end-to-end và sinh đúng output**, không phải một mức CER cố định.

## 2 · Package

```
core/     load → preprocess → layout → recognize → assemble → serialize
main.py   CLI: OCR một file + apply-review
```

`core` không import `finetune` / `evaluate`.

| Lệnh | Việc |
| --- | --- |
| `python main.py <path> [--out]` | OCR → `output/<stem>/` (+ dump trang yếu → `review/<stem>/`) |
| `python main.py apply-review <stem>` | Đọc `review/<stem>/p*.md` → ghi đè lại `output/<stem>/` |

Output luôn dưới `<out>/<stem nguồn>/`.

Engines (`tesseract` / `paddleocr` / `easyocr`) nằm ở `core/engines/`. Layout `tesseract` **bắt buộc** `engine=tesseract`.

## 3 · Sáu stage

```
run_document(path, cfg) -> DocumentRun   # Document + page_images
run_page(path, page, cfg) -> PageResult

 1 Load        loader.py       load_page / page_count (pypdfium2, 300 DPI)
 2 Preprocess  preprocess.py   orientation → deskew (giữ affine) → denoise
 3 Layout      layout/         table_cv rồi tesseract_blocks, trừ nhau
 4 Recognize   recognize/      text | table
 5 Assemble    document/       to_canonical → link → reading order → id → validate
 6 Serialize   serialize/      .md + .coco.json (+ .document.json từ main)
```

`reading_order` từ `run_page` = `-1`; `run_document` gán lại.  
`DocumentRun.page_images` = ảnh sau preprocess (để dump review).

### Layout

1. `table_cv` trước (bọc `tables.py`) → `LayoutBox(table, cells, n_rows, n_cols)`.
2. `tesseract_blocks` → `LayoutBox(text)` theo `block_num`.
3. Bỏ text khi diện tích giao / diện tích box ≥ **0,7** (bao chứa, không IoU).

Chỉ sinh `text` và `table`. `layout=none`: một element text phủ trang.

### Recognize

| Category | Module | Cách |
| --- | --- | --- |
| text | `recognize/text.py` | `recognize_words` → `TextLine` → `TextContent` |
| table | `recognize/table.py` | Dùng `cells` sẵn; ô qua `recognize_text(psm=6)` |

Điểm chia confidence duy nhất: `Word` 0–100 → `TextLine` 0–1 trong `recognize/text.py`.  
Bảng bậc 3 (`rec_score=None`) — QA không gate bảng.

### Assemble

- `assemble.py`: `to_canonical` **một lần** mỗi hộp.
- `reading_order.py`: XY-cut, số dày đặc toàn tài liệu.
- `link.py`: bảng tràn trang; caption = stub.
- `validate_page` → `flags`; `validate_document` → raise nếu bất biến cấu trúc vỡ.

## 4 · Document model

```python
TextLine: text, text_ocr, polygon, bbox, confidence   # text_ocr không ghi đè
TextContent: text, lines=[]
TableContent: html, n_rows, n_cols, cell_boxes
Element / Document / PageError / PageGeometry
```

| Đối tượng | Khung |
| --- | --- |
| LayoutBox, Cell, Word | deskew |
| Element, TextLine, cell_boxes | hệ chuẩn (sau rotation, trước deskew) |

`polygon` = nguồn sự thật; `bbox` = bao lồi.

## 5 · QA và review folder

```python
gate(elements, threshold) -> PageVerdict  # qa_threshold mặc định 0.75
```

Sau OCR, `main.py` luôn ghi full document vào `output/<stem>/` (kể cả trang yếu), đồng thời:

```
review/<stem>/
  p0003.webp    # ảnh sau preprocess
  p0003.md      # <!-- page: N lines: K --> + K dòng TextLine
```

Sửa tay `pNNNN.md` (giữ đúng số dòng), rồi:

```bash
python main.py apply-review <stem>
```

Apply cập nhật `TextLine.text` (giữ `text_ocr`), ghi lại `.md` / `.coco.json` / `.document.json`, xóa các trang đã apply trong `review/`.

## 6 · Config

```python
dpi=300, preprocess_steps=[orientation, deskew, denoise],
layout=tesseract, table=cv, engine=tesseract, langs=[vie],
outputs=[markdown, coco], qa_threshold=0.75,
input_dir, output_dir, review_dir, ground_truth_dir, artifacts_dir
```

## 7 · Hạn chế

1. COCO chỉ 2/11 category DocLayNet.
2. Bảng bậc 3 — không gate.
3. Chỉ bảng kẻ khung.
4. Không `.html`, searchable PDF, công thức.
5. `qa_threshold=0.75` chưa đo trên corpus thật.
6. Fine-tune vẫn cần `artifacts/` — đường tạo artifact (orchestrate) đã gỡ; follow-up riêng.
