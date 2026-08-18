# Luồng 3 · Fine-tune

Ngày: 2026-08-15. Trạng thái: **đã implement**.  
Thiết kế: [2026-08-15-tesseract-pipeline-refactor-design.md](2026-08-15-tesseract-pipeline-refactor-design.md) §6.  
Phụ thuộc: [01 OCR](01-ocr.md) (`TextLine`, artifacts), [04 evaluation](04-evaluation.md) (GT + CER sau train).

Cắt dòng từ artifact → gióng nhãn với ground truth → `.lstmf` → `lstmtraining` → `vie_lpbank.traineddata` → chạy lại OCR với model mới. Package: `finetune/`.

## 1 · Vòng khép kín

```
artifacts/<sha>/<version>/pages + images   # follow-up: tạo artifact
        ↓
finetune cut / align / lstmf / train
        ↓
finetune/tessdata/vie_lpbank.traineddata
        ↓
langs=[vie_lpbank] + TESSDATA_PREFIX=finetune/tessdata
        ↓
python main.py <path>
        ↓
python -m evaluate.run   # CER để xem, không phải cổng chặn
```

`finetune → core + evaluate`. Mọi lệnh gọi `guards` trước.
Đường `orchestrate` tạo `artifacts/` đã gỡ — xem [folder-review design](2026-08-17-folder-review-design.md) §8.

## 2 · Cổng chặn

| Điều kiện | Kiểm | Nếu trượt |
| --- | --- | --- |
| Binary | `lstmtraining`, `combine_tessdata` trên PATH | Dừng |
| `vie.traineddata` bản **best** | `combine_tessdata -l` không có `int_mode=1` | Dừng + tải tessdata_best |
| Có GT | `discover_text(ground_truth_dir)` > 0 | Dừng |

Chỉ check đúng tên `vie.traineddata` — bỏ qua `vie_lpbank.traineddata` cạnh đó.

```
finetune/tessdata/vie.traineddata        # tải tay (gitignore)
finetune/tessdata/osd.traineddata        # copy hệ thống (orientation)
finetune/tessdata/vie_lpbank.traineddata # sản phẩm train
```

```bash
mkdir -p finetune/tessdata
curl -L -o finetune/tessdata/vie.traineddata \
  https://github.com/tesseract-ocr/tessdata_best/raw/main/vie.traineddata
cp /opt/homebrew/share/tessdata/osd.traineddata finetune/tessdata/
```

## 3 · Lệnh

```bash
python -m finetune cut      --sha <sha> --version <pipeline_version>
python -m finetune align    --sha <...> --version <...> [--stem]
python -m finetune lstmf    [--degrade]
python -m finetune train    [--max-iterations 3000]
python -m finetune pipeline --sha <...> --version <...> [--degrade]
```

| Bước | Input | Output |
| --- | --- | --- |
| cut | `pages/*.json` + `images/*.webp` | `data/<sha12>/p0007_l003.png` |
| align | crops + GT cùng stem | `.gt.txt`; `rejected.log` |
| degrade | png đã có gt (opt-in) | `_blur` / `_noise` / `_jpeg` |
| lstmf | png + gt.txt | `.lstmf` + `list.train` (≥ 50 dòng) |
| train | list.train + vie.traineddata | `vie_lpbank.traineddata` |

## 4 · Cắt dòng và gióng nhãn

**Cut:** với mỗi `TextLine` của element `text`, crop bằng  
`bounding_box(from_canonical(polygon, geom))` — một lần, qua polygon. Bỏ dòng &lt; 8 px cao / &lt; 16 px rộng. Không cắt ô bảng.

**Align** (không model):

1. Tách trang `<!-- page: N -->`.
2. Xoá `<table>…</table>` **trước** khi bóc thẻ khác.
3. Bóc thẻ còn lại; bóc bullet markdown (`- `/`* `/`+ `); giữ số thứ tự in; NFC.
4. **Không** dùng `normalize.strict()` (sai vị trí dấu thanh trên nhãn).
5. Levenshtein opcodes OCR↔GT; similarity &lt; 0,7 → `rejected.log`.

## 5 · Train

```
tesseract <line>.png <line> -l vie --tessdata-dir finetune/tessdata --psm 13 lstm.train
combine_tessdata -e …/vie.traineddata finetune/work/vie.lstm
lstmtraining --continue_from … --max_iterations 3000 …
lstmtraining --stop_training … --model_output …/vie_lpbank.traineddata
```

CPU, không GPU. `--max_iterations 3000` chưa đo trên corpus.

## 6 · Đóng vòng

```bash
# config.yaml: langs: [vie_lpbank]
TESSDATA_PREFIX=finetune/tessdata python main.py path/to/doc.pdf
python -m evaluate.run
```

So CER qua [04](04-evaluation.md). Artifact batch (cũ: orchestrate) là follow-up.

## 7 · Hạn chế

1. `vie.traineddata` best tải tay lần đầu.  
2. Bảng không thành mẫu train.  
3. `degrade` tắt mặc định — PDF digital-born → model gần bản gốc.  
4. Chỉ vá nhận chữ; layout Tesseract không học được.  
5. `ground_truth/` gitignore — clone trống thì guards chặn.
