# Cấu phần 3 - Core pipeline, kiến trúc cũ (đã thay thế)

Nguồn gốc (đã xoá, nội dung gộp/tóm tắt vào đây): `plans/2026-05-29-ocr-core-pipeline-design.md` ·
`plans/2026-06-01-multi-pipeline-refactor-design.md` · `plans/2026-06-02-legal-markdown-table-design.md` ·
`plans/2026-06-16-ocr-postprocess-llm-correction-design.md`.

**Trạng thái: SUPERSEDED.** Toàn bộ kiến trúc mô tả ở đây bị thay thế bởi [Cấu phần 4 - staged pipeline](04-core-pipeline-staged.md) (2026-08-07), vốn xoá hẳn `core/extract.py`, `core/postprocess.py`, `Config.mode`, `Config.postprocess`. Giữ tài liệu này để hiểu **vì sao** kiến trúc đổi hướng, không dùng để implement mới. Engine backend (`tesseract`/`paddleocr`/`easyocr`, `core/tables.py` phát hiện lưới cv thuần) **không** bị xoá - xem [Cấu phần 2](02-ocr-engines.md) và Cấu phần 4 §4 (`table_cv.py` kế thừa `core/tables.py`).

## Dòng thời gian kiến trúc

**1. Pipeline engine gốc (2026-05-29).** `loader → preprocessor → OCR engine (pluggable, Tesseract mặc định) → aggregator → JSON`. Line-level blocks: `{text, bbox, confidence}`. Best-effort per-page và per-file (lỗi ghi vào `error`, không chặn phần còn lại). Đây là bộ khung error-handling và cấu trúc `Config`/`DEFAULTS` mà mọi bản sau kế thừa.

**2. Multi-pipeline refactor (2026-06-01).** Tách một core `run()` dùng chung cho nhiều pipeline khác nhau, phân biệt bằng `Config` trong `PIPELINES` registry - không cần class `Pipeline` riêng:

- `legal` - `mode="text"`, `granularity="paragraph"` (Tesseract `image_to_string`, không bbox).
- `invoice` - `mode="data"`, `granularity="line"` (Tesseract `image_to_data`, có bbox + confidence).

Interface engine tách `recognize_words` (data mode) / `recognize_text` (text mode) - quyết định này **vẫn còn giữ nguyên** ở Cấu phần 2 và Cấu phần 4. `aggregate.py` → `extract.py`. Output file `<stem>.<pipeline>.json` để chạy nhiều pipeline trên cùng input không ghi đè nhau.

**3. Legal → Markdown + trích bảng (2026-06-02).** Đổi `legal` sang `mode="markdown"`, xuất `.md` thuần thay JSON, và trích bảng **có kẻ khung** thành markdown table thay vì bẹp thành văn xuôi. Thành phần mới: `tables.py` (dò lưới ô thuần `cv2` - morphology để tách đường ngang/dọc, suy span ô gộp bằng cách map cạnh ô về index lưới) và `markdown.py` (serialize). Ô gộp → fill (lặp giá trị vào mọi ô logic, vì GFM không hỗ trợ span). Bỏ hẳn mode `text`/`paragraph` vì không còn pipeline nào dùng. **Hạn chế đã biết:** bảng tràn nhiều trang không được merge (mỗi trang dò độc lập); chỉ nhận bảng có khung, bảng borderless rơi về prose.

Đây chính là hai giới hạn mà [Cấu phần 1](01-nghien-cuu-chon-model.md) liệt là yêu cầu M4/M11 và [Cấu phần 4](04-core-pipeline-staged.md) §3.3/§5.3 giải quyết lại từ đầu bằng model layout + link bảng tràn trang ở tầng document.

**4. Hậu xử lý sửa lỗi bằng LLM (2026-06-16).** Thêm bước `postprocess.correct_page()` giữa extract và collect kết quả, gọi OpenRouter (model free `meta-llama/llama-3.3-70b-instruct:free`) để sửa chính tả/dấu tiếng Việt trên toàn bộ text của trang trong một request, map lại theo index, best-effort (lỗi bất kỳ → giữ nguyên bản gốc, không retry).

## Vì sao bị thay thế toàn bộ

Ba lý do chốt ở Cấu phần 4:

1. **Lỗi kiến trúc gốc.** `extract.py` rẽ nhánh `mode: data | markdown` ngay từ tầng extract - nhánh markdown giữ text nhưng **vứt bbox tại chỗ**, nhánh data giữ bbox nhưng không có khái niệm bảng/hình/công thức/reading order thật. Hệ quả: không thể sinh `.md` và `.json` COCO từ **cùng một lần OCR** - vi phạm trực tiếp yêu cầu ở [Cấu phần 1](01-nghien-cuu-chon-model.md).
2. **Không có hệ toạ độ trang.** Không ghi `width/height/dpi` ở đâu; bbox nằm trong không gian ảnh đã deskew, không map ngược về PDF được - được [Cấu phần 1](01-nghien-cuu-chon-model.md) gọi là "blocker của COCO".
3. **`postprocess.py` vi phạm M1** (self-host offline, không gọi API ngoài) - gửi text OCR ra OpenRouter. Đã vậy, model đang gọi (`nvidia/nemotron-3.5-content-safety:free`) là model phân loại an toàn nội dung, **không phải instruction-following**, nên trong thực tế nó **im lặng fallback về text gốc ở mọi trang** mà không ai biết, vì exception bị bắt và trả `None` không log rõ.

`core/postprocess.py` bị **xoá hẳn**, không thay bằng interface nào. Nếu sau này cần sửa lỗi tiếng Việt sau OCR, hướng đề xuất là Vintern-1B-v3.5 (MIT, self-host - xem [Cấu phần 1](01-nghien-cuu-chon-model.md) §5.3), như một quyết định riêng khi có nhu cầu thật, không phải một cửa mở sẵn.

## Di sản còn giữ lại trong kiến trúc mới

- Nguyên tắc best-effort per-page / fail-fast cho lỗi config.
- Interface `recognize_words`/`recognize_text` và `langs: list[str]`.
- `core/tables.py` (dò lưới cv thuần) - trở thành fallback `table_cv.py` không cần tải model, ở bậc tín hiệu bất định thấp nhất (bậc 3) vì `recognize_text()` không trả confidence.
- `_split_paragraphs()` - chuyển sang `recognize/text.py`, vẫn cần để reflow dòng ngắt mềm cho mọi element chứa văn xuôi.
