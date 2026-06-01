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

### Phụ thuộc hệ thống (binary)

Hai thư viện Python cần binary của hệ điều hành:

- **Tesseract** (cho engine `tesseract`):
  ```bash
  brew install tesseract            # macOS
  # sudo apt install tesseract-ocr  # Debian/Ubuntu
  ```
  Cài thêm gói ngôn ngữ tiếng Việt nếu dùng `lang="vie"`:
  ```bash
  brew install tesseract-lang       # macOS (gồm vie)
  # sudo apt install tesseract-ocr-vie
  ```
- **Poppler** (chỉ cần khi xử lý PDF, dùng bởi `pdf2image`):
  ```bash
  brew install poppler              # macOS
  # sudo apt install poppler-utils
  ```

### Phụ thuộc Python

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

## 2. Sử dụng qua CLI

Mỗi pipeline trong registry tạo ra một subcommand cùng tên. Pipeline có sẵn:
`legal` và `invoice`.

```bash
# OCR mọi file trong ./input bằng profile pháp luật (text/paragraph)
python main.py legal

# OCR mọi file trong ./input bằng profile hoá đơn (data/line, có bbox)
python main.py invoice
```

Lệnh sẽ duyệt toàn bộ file hợp lệ trong `input_dir` (mặc định `./input`) và ghi
mỗi file ra `<output_dir>/<tên_file>.<pipeline>.json`. Định dạng hỗ trợ:
`.png .jpg .jpeg .tiff .tif .bmp .pdf`.

### Các cờ override

| Cờ | Ý nghĩa |
|----|---------|
| `-c, --config <file>` | Nạp thêm cấu hình từ file YAML/JSON |
| `-o, --output-dir <dir>` | Thư mục xuất JSON |
| `--lang <mã>` | Ngôn ngữ OCR, ví dụ `vie`, `eng`, `vie+eng` |
| `--granularity <mức>` | `page` \| `paragraph` \| `line` |
| `--log-level <mức>` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` (mặc định `INFO`) |

```bash
python main.py legal -c override.yaml --granularity page --lang vie -o ./result
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
granularity: paragraph
preprocess_steps: [grayscale, binarize]   # bỏ deskew
input_dir: ./input
output_dir: ./out
```

Các trường hợp lệ và giá trị mặc định (xem `ocr_core/config.py`):

| Trường | Mặc định | Giá trị hợp lệ |
|--------|----------|----------------|
| `engine` | `tesseract` | `tesseract` |
| `lang` | `vie` | mã ngôn ngữ Tesseract |
| `mode` | `data` | `text` \| `data` |
| `granularity` | `line` | `text`→`page`/`paragraph`; `data`→`line` |
| `preprocess_steps` | `[grayscale, deskew, binarize]` | tổ hợp các bước hợp lệ |
| `input_dir` | `./input` | đường dẫn |
| `output_dir` | `./out` | đường dẫn |

> **Ràng buộc quan trọng:** `mode="text"` chỉ đi với `granularity` là `page`/`paragraph`
> (không bbox); `mode="data"` chỉ đi với `line` (có bbox + confidence). Sai tổ hợp
> → `ConfigError` ngay khi load.

---

## 4. Cấu trúc JSON đầu ra

Header giống nhau cho mọi pipeline; chỉ khác phần `blocks`.

`legal` (text / paragraph) — block chỉ có `text`:

```json
{
  "source": "vbpl.pdf", "engine": "tesseract", "lang": "vie",
  "mode": "text", "granularity": "paragraph", "page_count": 2,
  "pages": [
    { "page": 1, "blocks": [ {"text": "Điều 1. ..."} ], "error": null }
  ]
}
```

`invoice` (data / line) — block có thêm `bbox` `[x, y, w, h]` và `confidence`:

```json
{
  "source": "scan.pdf", "engine": "tesseract", "lang": "vie",
  "mode": "data", "granularity": "line", "page_count": 1,
  "pages": [
    { "page": 1, "blocks": [
        {"text": "Invoice #123", "bbox": [100, 80, 220, 28], "confidence": 96.4} ],
      "error": null }
  ]
}
```

- `error` = `null` khi trang OK; là chuỗi `"<Loại lỗi>: <thông điệp>"` khi trang
  lỗi (lúc đó `blocks` rỗng, các trang khác vẫn xử lý — best-effort per page).
- Lỗi nạp file (định dạng không hỗ trợ, PDF hỏng) làm hỏng cả file đó, không tạo JSON.

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
    "legal":   Config(mode="text", granularity="paragraph"),
    "invoice": Config(mode="data", granularity="line"),
    "receipt": Config(mode="data", granularity="line", lang="eng"),  # MỚI
}
```

Sau đó:

```bash
python main.py receipt
```

Chỉ override những trường khác mặc định. Đảm bảo tổ hợp `mode`/`granularity` hợp
lệ (mục 3), nếu không sẽ `ConfigError` khi chạy.

---

## 7. Thêm OCR engine mới

Engine phải cài đặt interface `OCREngine` (`ocr_core/engines/base.py`) với hai
phương thức:

- `recognize_words(image, lang) -> list[Word]` — dùng cho `mode="data"`. Mỗi
  `Word` gồm `text`, `bbox=(x, y, w, h)`, `confidence`, và `line_key` (tuple để
  gom các từ cùng một dòng, ví dụ `(block, paragraph, line)`).
- `recognize_text(image, lang) -> str` — dùng cho `mode="text"`. Trả prose thuần;
  giữ `\n`, các đoạn cách nhau bằng dòng trống.

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

    def recognize_text(self, image: Image.Image, lang: str) -> str:
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
