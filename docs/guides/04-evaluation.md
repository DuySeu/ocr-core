# Evaluation, chấm theo tầng

Ngày: 2026-10-15. Trạng thái: tầng Recognition **đã có**, tầng Detection & Layout và Extraction & Structure **chưa có** (chỉ có khung).
Thiết kế: [2026-10-15-evaluate-by-tier-design.md](../designs/2026-10-15-evaluate-by-tier-design.md). Đặc tả data và metric: [benchmark-ocr.md](../specs/benchmark-ocr.md). Nguyên tắc chấm chi tiết: [evaluate/README.md](../../evaluate/README.md).

Chấm output của bất kỳ engine nào so với một bộ ground truth chuẩn, theo 3 tầng. Package `evaluate/` không import `core/` hay `finetune/`: file vào, file ra. Không nằm trong pipeline OCR, không phải cổng chặn chạy batch.

| Tầng | Input chấm | Metric | Trạng thái |
| --- | --- | --- | --- |
| 1 · Detection & Layout | prediction `.json` vs `pages[].blocks` | Detection P/R/F1 @ IoU 0,5, region classification, reading order | Chưa có |
| 2 · Recognition | prediction `.md` vs `<doc_id>.md` | WER (có marker ảnh), TEDS | Đã có |
| 3 · Extraction & Structure | prediction `.json` vs `fields` | Field P/R/F1, document accuracy, null accuracy | Chưa có |

## 1 · Bộ ground truth

Mỗi tài liệu là `data/ground_truth/<dataset>/<doc_id>.json` (schema trong benchmark-ocr.md, `full_text` thay bằng `text_file`) cộng `<doc_id>.md` nằm cạnh. Chuyển GT `.md`/`.docx` cũ một lần:

```bash
python -m evaluate.ground_truth data/ground_truth/lpbank --source-dir data/raw/lpbank
```

`finetune/` vẫn đọc GT qua `evaluate.ground_truth.discover_text()`, và sau khi chuyển nó vẫn tìm thấy file `.md`. Xem [03](03-finetune.md).

## 2 · Chạy tầng Recognition

```bash
# Sau python -m core (hoặc apply-review), prediction nằm dưới data/output/<engine>/<dataset>/
python -m evaluate recognition --label tesseract
```

Thư mục mặc định lấy từ `output_dir` và `ground_truth_dir` trong `config.yaml`. Report ghi ra `data/results/recognition/<label>/<dataset>.md`. Ghép cặp theo stem. Thiếu một bên thì ghi vào mục `unpaired`, không âm thầm bỏ. Hai prediction trùng stem thì báo lỗi.

## 3 · Sau fine-tune

1. Chạy evaluate trên output model `vie`.
2. Train rồi OCR lại với `vie_lpbank`.
3. Chạy evaluate lần hai với `--label` khác và so WER. Fine-tune **không** cải thiện layout hay TEDS theo thiết kế.

Số in ra để xem; **không** fail CI, không chặn theo ngưỡng.

## 4 · Giới hạn đã biết

1. Harness chỉ thấy output đã serialize.
2. WER chấm cả tài liệu một lần, nên lệch thứ tự đọc thành lỗi xóa cộng chèn.
3. Tài liệu không có GT nằm ở mục `unpaired`, khác với "0 bảng đúng".
4. Fine-tune LSTM không làm IoU hay TEDS tốt hơn theo thiết kế.
