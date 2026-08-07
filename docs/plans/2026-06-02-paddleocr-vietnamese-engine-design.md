# ocr-core — Engine PaddleOCR (tiếng Việt) — Design

Date: 2026-06-02
Status: Validated

## Mục tiêu

Thêm engine OCR `paddleocr` (opt-in) nhận dạng tiếng Việt tốt hơn Tesseract, phục
vụ **cả hai mode** `data` và `markdown`. Engine là plugin thuần sau interface
`OCREngine` hiện có; **không đổi** `pipeline.py`, `extract.py`, `preprocessing.py`,
`tables.py`. Tesseract vẫn là engine mặc định — không phá vỡ hành vi/CI hiện tại.

## Key Decisions

- **Backend = PaddleOCR (PP-OCR)**: offline sau khi tải model, tự có detector +
  recognizer + angle classifier nên trả box + text + score cho cả hai mode.
- **Opt-in**: bật bằng `engine: paddleocr` trong config/`PIPELINES`. Không đổi
  `PIPELINES` mặc định (`legal`/`invoice` vẫn Tesseract).
- **Dependency lazy/optional**: KHÔNG thêm vào `requirements.txt`; import trong
  engine, thiếu → `EngineError` kèm hướng dẫn cài. Giống convention Tesseract.
- **Reader cache** ở mức module, key theo lang đã map — model nạp một lần, dùng
  chung mọi file/trang trong tiến trình.
- **Lang map** `{"vie": "vi", "eng": "en"}`, mã khác pass-through. Giữ default
  `lang="vie"` chạy được khi đổi engine.
- **Mỗi detection của Paddle là một dòng** → một `Word`; `line_key` theo vị trí
  để sort ra đúng thứ tự đọc. `extract.py` không phải sửa.
- **GPU opt-in** qua env `PADDLE_USE_GPU`; không thêm field vào `Config` (YAGNI).
- **Preprocessing**: chỉ khuyến nghị trong docs (bỏ `binarize` khi dùng Paddle),
  không thêm logic per-engine.

## Module Layout

| File | Thay đổi | Cỡ |
| --- | --- | --- |
| `core/engines/paddle.py` | **Mới.** `PaddleOCREngine` + lang map + reader cache. | ~60 dòng |
| `core/engines/__init__.py` | Thêm `"paddleocr": PaddleOCREngine` vào `_ENGINES`. | 2 dòng |
| `core/config.py` | Thêm `"paddleocr"` vào `VALID_ENGINES`. | 1 dòng |
| `tests/test_paddle.py` | **Mới.** Mock `paddleocr`, assert mapping. | ~40 dòng |
| `GUIDELINE.md` / `README.md` | Tài liệu cài đặt, cách bật, lưu ý preprocessing. | docs |

**KHÔNG đổi:** `requirements.txt`, `PIPELINES` mặc định, schema `Config`, mọi code
pipeline/extract/preprocessing.

## Luồng dữ liệu (không đổi)

`pipeline.run` → `get_engine("paddleocr")` → mỗi trang `extract.extract` →
`data` gọi `recognize_words`, `markdown` gọi `recognize_text`. Engine gọi
`PaddleOCR` đã cache và dịch kết quả line-level sang contract `Word`/text.

## Engine: result mapping

PaddleOCR cổ điển `reader.ocr(np_img)` trả một entry/ảnh; `result[0]` là list
`[box, (text, score)]`, `box` gồm 4 điểm `[x, y]`.

### `recognize_words(image, lang) -> list[Word]` (mode `data`)

```python
lines = reader.ocr(np.array(image))[0] or []   # guard None khi trang trắng
for box, (text, score) in lines:
    xs = [p[0] for p in box]; ys = [p[1] for p in box]
    x, y = int(min(xs)), int(min(ys))
    w, h = int(max(xs)) - x, int(max(ys)) - y
    Word(text=text, bbox=(x, y, w, h),
         confidence=float(score) * 100,
         line_key=(round(y / 10), x))            # sort => thứ tự đọc
```

Mỗi detection là một dòng → một `Word`. `extract.extract` gom theo `line_key`
(theo vị trí) nên ra đúng thứ tự trên→dưới, trái→phải; union bbox/confidence của
mỗi dòng trùng chính nó. Không sửa `extract.py`.

### `recognize_text(image, lang, psm=None) -> str` (mode `markdown`)

```python
lines = reader.ocr(np.array(image))[0] or []
lines.sort(key=lambda L: (L[0][0][1], L[0][0][0]))   # theo y rồi x
return "\n".join(text for _, (text, _) in lines)
```

`psm` nhận nhưng bỏ qua (khái niệm của Tesseract). Prose band → đưa vào
`_split_paragraphs` không đổi; ô bảng (`_table_block`) → OCR crop ô rồi join dòng.
Kết quả rỗng → `""`.

## Reader lifecycle / lang / GPU / errors

```python
_READERS: dict[str, "PaddleOCR"] = {}
_LANG = {"vie": "vi", "eng": "en"}   # pass-through nếu khác

def _reader(self, lang: str):
    code = _LANG.get(lang, lang)
    if code not in _READERS:
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise EngineError(
                "paddleocr not installed: pip install paddleocr paddlepaddle"
            ) from e
        _READERS[code] = PaddleOCR(
            use_angle_cls=True, lang=code, show_log=False,
            use_gpu=bool(os.environ.get("PADDLE_USE_GPU")),
        )
    return _READERS[code]
```

- **Thiếu dependency** → `EngineError` kèm hướng dẫn cài (giống Tesseract).
- **Lần đầu tải model** cần mạng; lỗi → exception nổi lên, `pipeline.run` ghi vào
  `error` per-page (best-effort đã có sẵn).
- **Trang trắng / `None`** → `[]` hoặc `""`, không crash.
- **Caveat phiên bản:** kwargs (`use_gpu`, `show_log`) khác nhau giữa các major
  của PaddleOCR (3.x đổi tên). Ghim hướng dẫn ở `paddleocr>=2.7,<3`.

## Registration & wiring

```python
# core/engines/__init__.py
from .paddle import PaddleOCREngine
_ENGINES = {"tesseract": TesseractEngine, "paddleocr": PaddleOCREngine}

# core/config.py
VALID_ENGINES = {"tesseract", "paddleocr"}
```

Dùng: `engine: paddleocr` trong `config.yaml`, hoặc thêm entry `PIPELINES` nếu
muốn profile có tên. Subcommand CLI không bị ảnh hưởng (sinh từ `PIPELINES`).

## Testing (`tests/test_paddle.py`)

Theo style `test_engine.py`: inject module `paddleocr` giả → CI không cần Paddle/Torch.

```python
def _fake_paddle(monkeypatch, lines):
    fake = types.ModuleType("paddleocr")
    class PaddleOCR:
        def __init__(self, **kw): pass
        def ocr(self, arr, **kw): return [lines]
    fake.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
```

1. **`recognize_words` mapping** — 1 detection `[[[10,20],[60,20],[60,40],[10,40]], ("Hoá", 0.95)]`
   → `bbox == (10,20,50,20)`, `confidence == 95.0`, `line_key` sort theo vị trí.
2. **`recognize_text` ordering** — 2 detection lệch thứ tự → output join trên→dưới bằng `\n`.
3. **Thiếu dependency** — clear `_READERS`, đảm bảo `paddleocr` vắng trong
   `sys.modules` → `EngineError` kèm hướng dẫn cài.

Fixture clear `_READERS` giữa các test để không rò reader giả. Test Tesseract giữ nguyên.

## Documentation

- **`GUIDELINE.md`** (song song mục 7 EasyOCR): cài
  `pip install "paddleocr>=2.7,<3" paddlepaddle`; lần đầu tải model (cần mạng);
  bật bằng `engine: paddleocr`; **lưu ý preprocessing** — bỏ `binarize`, dùng
  `preprocess_steps: [deskew]` hoặc `[grayscale]`; GPU đặt `PADDLE_USE_GPU=1` +
  bản GPU của `paddlepaddle`; giữ `lang: vie` (engine tự map sang `vi`).
- **`README.md`** — thêm dòng bảng engine:
  `| paddleocr | PaddleOCR (PP-OCR) | Tiếng Việt mạnh, offline; opt-in. |`

## Out of scope (YAGNI)

- Không đổi engine mặc định của `legal`/`invoice`.
- Không thêm field `Config` cho GPU/model; dùng env.
- Không thêm logic preprocessing per-engine.
- Không xử lý bảng tràn trang hay đổi `extract.py`.
