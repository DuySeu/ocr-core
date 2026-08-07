# ocr-core — Engine EasyOCR (đa ngôn ngữ VI+EN) — Design

Date: 2026-06-04
Status: Validated

## Mục tiêu

Thêm engine OCR `easyocr` (opt-in) nhận dạng tốt văn bản **lẫn tiếng Việt và
tiếng Anh trong cùng một tài liệu** — phục vụ hóa đơn (`invoice`/mode `data`)
trộn VI+EN mà Tesseract/PaddleOCR cho độ chính xác kém. Chạy **offline** sau khi
tải model. Tesseract vẫn là engine mặc định — không phá vỡ hành vi/CI hiện tại.

## Key Decisions

- **Backend = EasyOCR**: hỗ trợ nhiều ngôn ngữ trong một lần chạy qua
  `Reader(['vi', 'en'])`; trả `(bbox, text, confidence)` cho mỗi detection nên
  hợp cả hai mode. `vi` và `en` cùng nhóm Latin → kết hợp hợp lệ.
- **Cấu hình `langs` (list)**: thêm field `langs: list[str] | None` vào `Config`
  (vd `[vie, eng]`). Người dùng khai báo **danh sách**, không phải gõ chuỗi
  `vie+eng`. `None` → fallback `[lang]` (tương thích ngược).
- **Đổi contract interface sang list**: `recognize_words/recognize_text` nhận
  `langs: list[str]` thay vì `lang: str`. List là hợp đồng chung; **mỗi engine
  tự thích nghi** — không join `+` ở tầng chung.
  - Tesseract: `lang="+".join(langs)` ngay tại chỗ gọi backend (pytesseract hiểu
    `vie+eng` natively).
  - PaddleOCR: đơn ngôn ngữ → dùng `langs[0]` qua map cũ.
  - EasyOCR: map từng mã rồi truyền cả list vào `Reader`.
- **Opt-in / dependency lazy**: KHÔNG thêm vào `requirements.txt`; import trong
  engine, thiếu → `EngineError` kèm hướng dẫn cài. Giống convention Paddle.
- **Reader cache** ở mức module, key theo tuple lang đã map — model nạp một lần,
  dùng chung mọi file/trang trong tiến trình.
- **Lang map** `{"vie": "vi", "eng": "en"}`, mã khác pass-through.
- **GPU opt-in** qua env `EASYOCR_USE_GPU`; không thêm field vào `Config` (YAGNI).

## Module Layout

| File | Thay đổi | Cỡ |
| --- | --- | --- |
| `core/engines/easyocr.py` | **Mới.** `EasyOCREngine` + lang map + reader cache. | ~35 dòng |
| `core/engines/base.py` | Đổi signature `lang: str` → `langs: list[str]`. | 2 dòng |
| `core/engines/tesseract.py` | `lang="+".join(langs)` tại chỗ gọi backend. | ~2 dòng |
| `core/engines/paddle.py` | Dùng `langs[0]` thay `lang`. | ~2 dòng |
| `core/engines/__init__.py` | Thêm `"easyocr": EasyOCREngine` vào `_ENGINES`. | 2 dòng |
| `core/config.py` | Thêm field `langs` + helper `lang_list()` + validate; `"easyocr"` vào `VALID_ENGINES`. | ~8 dòng |
| `core/extract.py` | 3 call site: `config.lang` → `config.lang_list()`. | 3 dòng |
| `tests/test_easyocr.py` | **Mới.** Mock `easyocr`, assert mapping. | ~40 dòng |
| `tests/test_paddle.py`, `tests/test_engine.py` | Cập nhật call site sang list. | vài dòng |
| `README.md` | Thêm dòng engine `easyocr` vào bảng. | docs |

**KHÔNG đổi:** `requirements.txt`, `PIPELINES` mặc định, `pipeline.py`,
`preprocessing.py`, `tables.py`.

## Config & language plumbing

```python
# config.py
langs: list[str] | None = None        # vd [vie, eng]; None -> [lang]

def lang_list(self) -> list[str]:
    return self.langs or [self.lang]
```

`validate()`: nếu `langs` được set thì phải là list không rỗng gồm string.
`VALID_ENGINES` thêm `"easyocr"`.

`extract.py`: ba chỗ gọi engine đổi `config.lang` → `config.lang_list()`.

## Engine: interface đổi sang list

```python
# base.py
def recognize_words(self, image, langs: list[str]) -> list[Word]: ...
def recognize_text(self, image, langs: list[str], psm: int | None = None) -> str: ...
```

- **Tesseract**: `pytesseract.image_to_*(image, lang="+".join(langs), ...)`.
- **Paddle**: `code = _LANG.get(langs[0], langs[0])`.

## Engine: EasyOCR (`engines/easyocr.py`)

`Reader.readtext(np_img)` trả list `(box, text, score)`, `box` gồm 4 điểm `[x, y]`
— cùng shape Paddle đã chuẩn hóa, nên mapping khớp contract `Word` hiện có.

```python
_READERS: dict[tuple, object] = {}          # cache Reader theo tuple lang
_LANG = {"vie": "vi", "eng": "en"}          # mã của ta -> EasyOCR; khác: pass-through

class EasyOCREngine(OCREngine):
    def recognize_words(self, image, langs):
        words = []
        for box, text, score in self._reader(langs).readtext(np.array(image.convert("RGB"))):
            xs = [int(p[0]) for p in box]; ys = [int(p[1]) for p in box]
            x, y = min(xs), min(ys)
            words.append(Word(text, (x, y, max(xs)-x, max(ys)-y),
                              float(score)*100, (round(y/10), x)))
        return words

    def recognize_text(self, image, langs, psm=None):
        items = self._reader(langs).readtext(np.array(image.convert("RGB")))
        items.sort(key=lambda it: (it[0][0][1], it[0][0][0]))   # y rồi x
        return "\n".join(text for _, text, _ in items)

    @staticmethod
    def _reader(langs):
        codes = tuple(_LANG.get(l, l) for l in langs)           # (vi, en)
        if codes not in _READERS:
            try:
                import easyocr
            except ImportError as e:
                raise EngineError("easyocr not installed: pip install easyocr") from e
            _READERS[codes] = easyocr.Reader(list(codes),
                                             gpu=bool(os.environ.get("EASYOCR_USE_GPU")))
        return _READERS[codes]
```

- `confidence*100`, `line_key=(round(y/10), x)` — đồng bộ convention Paddle.
- `psm` bị bỏ qua (khái niệm riêng của Tesseract).

## Luồng dữ liệu (không đổi về cấu trúc)

`pipeline.run` → `get_engine("easyocr")` → mỗi trang `extract.extract` →
`data` gọi `recognize_words(image, config.lang_list())`,
`markdown` gọi `recognize_text(...)`. Engine gọi `Reader` đã cache và dịch kết
quả line-level sang contract `Word`/text.

## Bật engine

`config.yaml` hoặc một entry `PIPELINES`:

```yaml
engine: easyocr
langs: [vie, eng]
```

## Testing

- `tests/test_easyocr.py` (mới): fake module `easyocr` với `Reader.readtext`
  trả tuple `(box, text, score)` dựng sẵn; assert mapping `Word`
  (`bbox`, `confidence*100`, `line_key`) + thứ tự y-rồi-x trong `recognize_text`;
  thêm test thiếu dependency kỳ vọng `EngineError("easyocr not installed")`.
- Cập nhật call site sang list ở `test_paddle.py` (`["vie"]`) và `test_engine.py`
  (`["vie"]`; Tesseract join `["vie"]` → `"vie"` nên assertion cũ vẫn đúng).
- `python -m pytest -q`: toàn bộ suite (đã cập nhật call site) + test EasyOCR
  phải pass **mà không cần cài EasyOCR thật** vì đã mock.

## Out of scope (YAGNI)

- Tự động phát hiện ngôn ngữ.
- Thêm EasyOCR vào `requirements.txt` mặc định.
- Field GPU trong `Config` (dùng env var).
- Đổi `PIPELINES` mặc định sang EasyOCR.
