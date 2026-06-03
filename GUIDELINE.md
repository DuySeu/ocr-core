# ocr-core — Hướng dẫn sử dụng

`ocr-core` là một OCR pipeline có thể cắm/thay thế: nạp ảnh/PDF → tiền xử lý →
nhận dạng bằng engine OCR → xuất JSON. Mọi hành vi được điều khiển bằng `Config`,
và mỗi **pipeline** chỉ là một `Config` đặt sẵn tên.

## Mục lục

- [1. Cài đặt](#1-cài-đặt)
- [2. Sử dụng qua CLI](#2-sử-dụng-qua-cli)
- [3. File cấu hình](#3-file-cấu-hình)
- [4. Cấu trúc JSON đầu ra](#4-cấu-trúc-json-đầu-ra)
- [5. Dùng như thư viện (API)](#5-dùng-như-thư-viện-api)
- [6. Tạo pipeline mới](#6-tạo-pipeline-mới)
- [7. Thêm OCR engine mới](#7-thêm-ocr-engine-mới)
- [8. Thêm bước tiền xử lý mới](#8-thêm-bước-tiền-xử-lý-mới)

---

## 1. Cài đặt

Chạy script để tạo thư mục làm việc, cài binary hệ thống (theo OS) và cài thư
viện Python vào `.venv`:

```bash
./setup.sh
source .venv/bin/activate
```

### Thư viện sử dụng

Binary hệ thống (script tự cài theo brew/apt/dnf):

- **Tesseract** — engine OCR `tesseract` (kèm gói ngôn ngữ `vie`).
- **Poppler** — chuyển PDF → ảnh (dùng bởi `pdf2image`).

Thư viện Python (`requirements.txt`):

| Thư viện | Vai trò |
|----------|---------|
| `pytesseract` | Engine OCR Tesseract |
| `paddleocr` | Engine OCR PaddleOCR (tiếng Việt, opt-in) |
| `pdf2image` | Nạp PDF → ảnh |
| `Pillow` | Xử lý ảnh |
| `numpy` | Tiền xử lý |
| `opencv-python` | Tiền xử lý (deskew, binarize) + phát hiện bảng |
| `PyYAML` | Đọc file cấu hình YAML |

---

## 2. Sử dụng qua CLI

Mỗi pipeline trong registry tạo ra một subcommand cùng tên. Pipeline có sẵn:
`legal` và `invoice`.

```bash
# OCR mọi file trong ./input bằng profile pháp luật (markdown: prose + bảng)
python main.py legal

# OCR mọi file trong ./input bằng profile hoá đơn (data/line, có bbox)
python main.py invoice
```

Lệnh sẽ duyệt toàn bộ file hợp lệ trong `input_dir` (mặc định `./input`) và ghi
mỗi file ra `<output_dir>/<tên_file>.<ext>` (`legal` → `.md`,
`invoice` → `.json`). Định dạng đầu vào hỗ trợ:
`.png .jpg .jpeg .tiff .tif .bmp .pdf`.

### Các cờ override

| Cờ | Ý nghĩa |
|----|---------|
| `-c, --config <file>` | Nạp thêm cấu hình từ file YAML/JSON |
| `-o, --output-dir <dir>` | Thư mục xuất JSON |
| `--lang <mã>` | Ngôn ngữ OCR, ví dụ `vie`, `eng`, `vie+eng` |
| `--log-level <mức>` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` (mặc định `INFO`) |

```bash
python main.py legal -c override.yaml --lang vie -o ./result
```

### Thứ tự ưu tiên cấu hình

```
default của pipeline  <  file (-c)  <  cờ CLI
```

Giá trị `None` (không truyền) không ghi đè lên giá trị có sẵn.

---

## 3. File cấu hình

File YAML hoặc JSON (tự nhận diện). Chỉ chấp nhận các khoá trùng tên trường của
`Config`; khoá lạ → `ConfigError`.

```yaml
# override.yaml
lang: vie
preprocess_steps: [grayscale, binarize]   # bỏ deskew
input_dir: ./input
output_dir: ./out
```

Các trường hợp lệ và giá trị mặc định (xem `ocr_core/config.py`):

| Trường | Mặc định | Giá trị hợp lệ |
|--------|----------|----------------|
| `engine` | `tesseract` | `tesseract` |
| `lang` | `vie` | mã ngôn ngữ Tesseract |
| `mode` | `data` | `markdown` \| `data` |
| `preprocess_steps` | `[grayscale, deskew, binarize]` | tổ hợp các bước hợp lệ |
| `input_dir` | `./input` | đường dẫn |
| `output_dir` | `./out` | đường dẫn |

> **Ràng buộc quan trọng:** `mode="markdown"` → xuất `.md` (prose + bảng);
> `mode="data"` → xuất JSON theo line (có bbox + confidence). Mode lạ → `ConfigError`
> ngay khi load.

---

## 4. Cấu trúc đầu ra

`legal` (markdown) — xuất file `.md`: prose thành đoạn văn, bảng có
khung thành markdown table. Ô gộp được lặp giá trị (markdown không có rowspan);
hàng tiêu đề trải hết bảng render dạng `| **...** |  |  |`:

```markdown
I. CĂN CỨ TRÌNH ...

| STT | Hạng mục | Yêu cầu kỹ thuật |
| --- | --- | --- |
| **I. Yêu cầu Máy chủ AI cá nhân — Số lượng: 04 cái** |  |  |
| 1 | Kiến trúc nền tảng | Thuộc nền tảng AI Supercomputer... |
```

Trang lỗi được chèn `<!-- page N error: ... -->`, các trang khác vẫn xuất.

`invoice` (data / line) — xuất JSON; block có `text`, `bbox` `[x, y, w, h]` và
`confidence`:

```json
{
  "source": "scan.pdf", "engine": "tesseract", "lang": "vie",
  "mode": "data", "page_count": 1,
  "pages": [
    { "page": 1, "blocks": [
        {"text": "Invoice #123", "bbox": [100, 80, 220, 28], "confidence": 96.4} ],
      "error": null }
  ]
}
```

- `run()` luôn trả dict trung gian; `run_to_file()` chọn serializer theo `mode`
  (`markdown` → `.md` qua `markdown.to_markdown`, còn lại → `.json`).
- `error` = `null` khi trang OK; là chuỗi `"<Loại lỗi>: <thông điệp>"` khi trang
  lỗi (best-effort per page; các trang khác vẫn xử lý).
- Lỗi nạp file (định dạng không hỗ trợ, PDF hỏng) làm hỏng cả file đó, không tạo output.

---

## 5. Dùng như thư viện (API)

```python
from ocr_core import load, run, run_to_file
from ocr_core.config import PIPELINES

# Lấy config từ pipeline có sẵn rồi override
cfg = load(overrides={"lang": "eng"}, base=PIPELINES["invoice"])

doc = run("input/scan.png", cfg)        # -> dict
path = run_to_file("input/scan.png", cfg, pipeline="invoice")  # -> ghi file, trả path
```

`run()` trả về dict (không ghi đĩa); `run_to_file()` ghi `<stem>.<pipeline>.json`
vào `cfg.output_dir` và trả về đường dẫn.

---

## 6. Tạo pipeline mới

Pipeline = một entry trong `PIPELINES` (trong `ocr_core/config.py`). Không cần
class riêng, không cần sửa core. Subcommand CLI sinh tự động từ key.

```python
# ocr_core/config.py
PIPELINES: dict[str, "Config"] = {
    "legal":   Config(mode="markdown"),
    "invoice": Config(mode="data"),
    "receipt": Config(mode="data", lang="eng"),  # MỚI
}
```

Sau đó:

```bash
python main.py receipt
```

Chỉ override những trường khác mặc định. Đặt `mode` hợp lệ (`markdown` | `data`),
nếu không sẽ `ConfigError` khi chạy.

---

## 7. Thêm OCR engine mới

Engine phải cài đặt interface `OCREngine` (`ocr_core/engines/base.py`) với hai
phương thức:

- `recognize_words(image, lang) -> list[Word]` — dùng cho `mode="data"`. Mỗi
  `Word` gồm `text`, `bbox=(x, y, w, h)`, `confidence`, và `line_key` (tuple để
  gom các từ cùng một dòng, ví dụ `(block, paragraph, line)`).
- `recognize_text(image, lang, psm=None) -> str` — dùng cho `mode="markdown"`
  (prose band và OCR từng ô bảng; `psm` tùy chọn, ví dụ `6` cho một ô). Trả prose
  thuần; giữ `\n`, các đoạn cách nhau bằng dòng trống.

Một engine chỉ cần hỗ trợ mode bạn định dùng; mode không hỗ trợ có thể raise
`EngineError`.

### Bước 1 — tạo file engine

```python
# ocr_core/engines/easyocr.py
from __future__ import annotations

from PIL import Image

from .base import EngineError, OCREngine, Word


class EasyOCREngine(OCREngine):
    def recognize_words(self, image: Image.Image, lang: str) -> list[Word]:
        reader = self._reader(lang)
        import numpy as np
        words = []
        # easyocr trả [(bbox_4points, text, conf)]; quy về (x, y, w, h)
        for i, (box, text, conf) in enumerate(reader.readtext(np.array(image))):
            xs = [p[0] for p in box]; ys = [p[1] for p in box]
            x, y = int(min(xs)), int(min(ys))
            w, h = int(max(xs) - x), int(max(ys) - y)
            words.append(Word(text=text, bbox=(x, y, w, h),
                              confidence=float(conf) * 100,
                              line_key=(i,)))  # mỗi kết quả là 1 dòng
        return words

    def recognize_text(self, image: Image.Image, lang: str, psm: int | None = None) -> str:
        words = self.recognize_words(image, lang)
        return "\n".join(w.text for w in words)

    @staticmethod
    def _reader(lang: str):
        try:
            import easyocr
        except ImportError as e:
            raise EngineError("easyocr chưa được cài: pip install easyocr") from e
        return easyocr.Reader(lang.split("+"))
```

> Lưu ý: import thư viện nặng theo kiểu **lazy** (bên trong hàm) như engine
> Tesseract, để package vẫn import được khi chưa cài engine đó.

### Bước 2 — đăng ký engine

```python
# ocr_core/engines/__init__.py
from .easyocr import EasyOCREngine

_ENGINES = {
    "tesseract": TesseractEngine,
    "easyocr": EasyOCREngine,   # MỚI
}
```

### Bước 3 — cho phép dùng trong config

```python
# ocr_core/config.py
VALID_ENGINES = {"tesseract", "easyocr"}
```

### Bước 4 — sử dụng

```yaml
# config dùng engine mới
engine: easyocr
```

```bash
python main.py invoice -c easyocr.yaml
```

### Engine có sẵn: `paddleocr` (tiếng Việt, opt-in)

Engine `paddleocr` đã tích hợp sẵn, dùng được cho cả `markdown` và `data`. Phụ
thuộc là **tùy chọn** (không nằm trong `requirements.txt`):

```bash
pip install paddleocr paddlepaddle   # hỗ trợ 2.x & 3.x; lần đầu chạy sẽ tự tải model (cần mạng)
```

Bật bằng config (Tesseract vẫn là mặc định):

```yaml
engine: paddleocr
lang: vie                       # engine tự map vie->vi, eng->en
preprocess_steps: [deskew]      # XEM LƯU Ý bên dưới
```

- **Lưu ý preprocessing:** PaddleOCR học trên ảnh tự nhiên/grayscale, nên
  `binarize` làm **giảm** độ chính xác. Dùng `[deskew]` hoặc `[grayscale]` thay
  cho mặc định `[grayscale, deskew, binarize]`.
- **GPU (tùy chọn):** đặt biến môi trường `PADDLE_USE_GPU=1` và cài bản GPU của
  `paddlepaddle`. Mặc định chạy CPU.
- Thiếu thư viện → `EngineError` kèm hướng dẫn cài. Engine cache reader theo
  `lang` nên model chỉ nạp một lần.

---

## 8. Thêm bước tiền xử lý mới

Mỗi bước là một hàm `np.ndarray -> np.ndarray`, đăng ký vào dict `STEPS`
(`ocr_core/preprocessing.py`) và khai báo hợp lệ trong `VALID_STEPS`
(`ocr_core/config.py`).

```python
# ocr_core/preprocessing.py
def _denoise(img: np.ndarray) -> np.ndarray:
    return cv2.medianBlur(img, 3)

STEPS = {"grayscale": _grayscale, "deskew": _deskew,
         "binarize": _binarize, "denoise": _denoise}   # MỚI
```

```python
# ocr_core/config.py
VALID_STEPS = {"grayscale", "deskew", "binarize", "denoise"}
```

Các bước chạy **đúng theo thứ tự** khai báo trong `preprocess_steps`, nên thứ tự
quan trọng (ví dụ `deskew` trước `binarize`).

```yaml
preprocess_steps: [grayscale, denoise, deskew, binarize]
```
