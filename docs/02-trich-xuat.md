# Luồng 2 · Trích xuất thông tin

Ngày: 2026-08-15. Trạng thái: **nghiên cứu, chưa implement** (`extract/` chưa có trong repo).  
Đầu vào dự kiến: output [luồng 1](01-ocr.md) (`.md` / `Document` qua `serde`).  
Đánh giá sau này: [04-evaluation.md](04-evaluation.md).

Biến văn bản có cấu trúc thành JSON theo schema nghiệp vụ. Đơn vị công việc: một văn bản.

## 1 · Mục tiêu

| | |
| --- | --- |
| Input | `.md` (và về sau `Document` / HTML cấu trúc nếu có) từ artifacts hoặc `output/` |
| Output | JSON đúng schema từng loại văn bản (quy chế, quyết định, thông báo, công văn, …) |
| Ràng buộc | Self-host nếu compliance chặn API; field không đủ tin cậy → để trống + đánh dấu review |

Pipeline OCR hiện tại **không** sinh `.html` (quyết định zone 1). Trích xuất đọc `Document` / `.md`; không phụ thuộc Chandra HTML cũ.

## 2 · Kiến trúc lai theo loại field

Không chọn một công cụ duy nhất. Router giao mỗi field cho nhánh rẻ nhất giải được:

| Nhánh | Việc | Model? |
| --- | --- | --- |
| Cấu trúc tài liệu | Heading, bảng, vị trí khối đã có trong OCR | Không |
| Fuzzy anchor | Tìm nhãn gần đúng (`Số:`, `Ngày ban hành:`) rồi lấy phần theo sau | Không |
| NER / GLiNER (CPU) | Giá trị rời, viết nguyên văn, trong phạm vi đã biết | Encoder |
| LLM structured output | Quan hệ, điều kiện, ngoại lệ, thông tin ẩn | Decoder |
| Merge theo schema | Chuẩn hoá kiểu, chấm tin cậy từng field | Code |

Thứ tự: nhánh rẻ trước; field còn trống mới xuống nhánh đắt hơn.

## 3 · NER vs LLM (tóm tắt)

| | NER (encoder) | LLM (decoder) |
| --- | --- | --- |
| Output | Span + offset + loại nhãn cố định | JSON / chuỗi tự do |
| Bịa giá trị | Không thể | Có thể |
| Quan hệ / điều kiện / thông tin ẩn | **Không làm được** | Làm được |
| Kiểu lỗi điển hình | Gán sai nhãn cho chuỗi có thật | Bịa hoặc suy sai |
| Chi phí biên | Gần 0 sau khi dựng | Token / GPU |

NER phù hợp field “có đúng chuỗi trên giấy”. So chuỗi với văn bản gốc **không** bắt lỗi gán sai nhãn — cần ngưỡng, khoảng cách điểm, và **phạm vi cho phép** trong schema.

GLiNER (Apache-2.0, họ `-v2.1`) đáng thử trước khi fine-tune PhoBERT: nhận danh sách nhãn lúc chạy, không train lại mỗi lần đổi field. Vẫn cần bộ đánh giá gán tay để chọn ngưỡng.

## 4 · Schema và review

- **Business schema** khai báo field + chỗ được phép xuất hiện, trước khi chạy.
- **Document type classifier** chọn schema / tuyến.
- Field dưới ngưỡng → để trống, đẩy **field review queue** — không đoán.

## 5 · Việc chưa làm

1. Package `extract/` và CLI.  
2. Parse / đọc `Document` từ `serde` thay vì giả định `.html` Chandra.  
3. Schema LPBank cụ thể và bộ gold field-level.  
4. Metric field (precision/recall theo field) trong [04-evaluation](04-evaluation.md).  
5. Adapter layout-aware (LiLT/LayoutLM) — cần bbox ổn định; hiện OCR chỉ chắc `text`/`table`.

## 6 · Liên hệ

| Luồng | Quan hệ |
| --- | --- |
| [01 OCR](01-ocr.md) | Cung cấp `.md` / `Document` / artifacts |
| [03 Fine-tune](03-finetune.md) | Không trực tiếp; cải thiện chữ OCR giảm lỗi anchor/NER |
| [04 Evaluation](04-evaluation.md) | Sẽ chấm JSON vs gold schema khi có implement |
