# Evaluation — metric theo luồng

Ngày: 2026-08-15. Trạng thái: harness `evaluate/` **đã có** cho output OCR; metric luồng 2 **chưa có**.  
Package: `evaluate/`. **Không import `core/` / `orchestrate/` / `finetune/`** — file vào, file ra.

Chấm chất lượng output của từng luồng. Không nằm trong pipeline OCR; không phải cổng chặn chạy batch.

| Luồng | Input chấm | Metric hiện tại |
| --- | --- | --- |
| [01 OCR](01-ocr.md) | `output/<stem>/*.md` (+ `.coco.json` khi có) vs `ground_truth/` | CER/WER, TEDS (document-level); IoU khi có COCO gold |
| [02 Trích xuất](02-trich-xuat.md) | JSON vs schema gold | **Chưa implement** |
| [03 Fine-tune](03-finetune.md) | Cùng harness OCR, so hai lần chạy (trước/sau `vie_lpbank`) | CER (xem xu hướng) |

## 1 · Chạy trên output OCR

```bash
# Sau main.py (hoặc apply-review) — prediction dưới output/<stem>/
python -m evaluate.run
```

Cặp theo **stem** file: `output/<stem>/<stem>.md` ↔ `ground_truth/lpbank/<stem>.md`.  
Trùng stem → raise. Thiếu prediction / thiếu gold → báo rõ trong report pairing, không im lặng bỏ.

`config.yaml` dùng chung: `output_dir`, `ground_truth_dir`, `engine` (evaluate đọc các key này).

## 2 · Ground truth LPBank

- Thư mục: `ground_truth/lpbank/<stem>.md` (gitignore — có trên máy làm việc).
- Nguồn phase 1: text layer PDF &lt; 20 trang (`<!-- page: N -->`, 1-based).
- Markup `<table>` trong GT là có chủ ý (để TEDS / để finetune bỏ đúng khối bảng khi align).
- Chưa có gold COCO bbox đầy đủ trên corpus; IoU layout chủ yếu trên fixture hoặc khi có annotate.

Finetune cũng dùng cùng GT qua `evaluate.ground_truth.discover_text()` — xem [03](03-finetune.md).

## 3 · Ba metric OCR

### Layout — IoU (stage layout)

Ghép tham lam IoU ≥ 0,5 theo `(trang, category)`. P/R/F1 + mean IoU trên cặp đã ghép.  
**Cần** prediction + gold `.coco.json`. Pipeline hiện tại đã ghi COCO; gold COCO annotated vẫn hạn chế.

### Text — CER / WER

```
CER = Σ levenshtein(pred, gold) / Σ len(gold)   # tổng corpus
```

Báo cáo: CER strict, CER tone-blind, WER strict.  
Chuẩn hoá strict (cả hai phía): NFC → bóc markdown/HTML → quy vị trí dấu thanh kiểu cũ → gộp whitespace.  
Tone-blind = strict + bỏ 5 dấu thanh, giữ `â ê ô ă ơ ư đ`.

Đường **document-level** (đọc `.md`) đang là đường chạy thật chính. CER mức element (COCO) khi có field `text` trên annotation.

### Table — TEDS

Cây HTML (`lxml`) → tree edit distance (PubTabNet). TEDS và TEDS-Struct.  
Đường **document-level**: trích `<table>` / pipe table từ `.md`, ghép cặp theo TEDS-Struct ≥ 0,5, luôn kèm `table_recall`.  
HTML không parse được → TEDS = 0, liệt kê id (không loại khỏi mẫu số).

## 4 · Quy tắc cô lập stage

Gold element không ghép được (layout bỏ sót) → tính vào **recall layout**, **loại khỏi mẫu số** text/table.  
Report in hai khối cạnh nhau: số stage sau là số có điều kiện.

Không chấm: trang trong `page_errors`; lệch hệ toạ độ gold/pred quá lớn → `unscoreable`.

## 5 · Sau fine-tune

1. Chạy evaluate trên output model `vie`.  
2. Train + OCR lại với `vie_lpbank` (artifacts/version mới).  
3. Chạy evaluate lần hai — so CER (và TEDS nếu quan tâm bảng; fine-tune **không** cải thiện layout/TEDS theo thiết kế).

Số in ra để xem; **không** fail CI / không chặn `orchestrate` theo ngưỡng CER.

## 6 · Luồng 2 (dự kiến)

Khi có `extract/`:

| Metric | Ý nghĩa |
| --- | --- |
| Field precision / recall | Giá trị JSON vs gold gán tay |
| Exact match / normalized match | Theo kiểu field (ngày, số tiền, …) |
| Hallucination rate | Giá trị không xuất hiện trong văn bản nguồn (chủ yếu LLM) |

Chưa có module hay CLI — không bịa format report.

## 7 · Cây module

```
evaluate/
  run.py / __main__.py
  config.py · ground_truth.py · normalize.py · matching.py
  table_extract.py
  metrics/layout.py · text.py · table.py
  report.py
```

Dependency: `rapidfuzz`, `apted`, `lxml`, `python-docx`.

## 8 · Giới hạn đã biết

1. Harness chỉ thấy output serialize — lỗi lắp ráp có thể hiện như false negative layout.  
2. Không đo reading order trong v1.  
3. CER document-level là xu hướng, không phải cổng chất lượng.  
4. Tài liệu không có GT → `not scoreable`, khác với “0 bảng đúng”.  
5. Fine-tune LSTM không làm IoU/TEDS tốt hơn theo thiết kế.
