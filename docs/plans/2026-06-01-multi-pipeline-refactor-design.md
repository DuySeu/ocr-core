# ocr-core Multi-Pipeline Refactor — Design

Date: 2026-06-01
Status: Validated

## Purpose

Tách `ocr-core` để chạy được nhiều pipeline qua các command khác nhau, trong khi
giữ nguyên core logic (`run()`) và engine dùng chung. Mỗi pipeline chỉ khác nhau
ở **config**. Hai use case trước mắt:

1. **`legal`** — OCR văn bản pháp luật: cần text chính xác, **không bbox**, trích
   xuất theo page hoặc theo đoạn (paragraph).
2. **`invoice`** — OCR hoá đơn / form: cần **bbox + confidence**, trích xuất theo
   line (hành vi hiện tại).

Yêu cầu: dễ mở rộng thêm pipeline mới về sau mà không phải sửa core.

## Key Decisions

- **Pipeline = named default `Config` trong registry** (`PIPELINES`), không cần
  class Pipeline riêng. Thêm pipeline mới = thêm 1 entry vào registry.
- **Một core `run()` dùng chung**; subcommand sinh tự động từ registry.
- **Một engine dùng chung, 2 mode do config chọn**:
  - `mode="text"` → `image_to_string` (Tesseract tự phân tích layout, prose
    chính xác cho văn bản pháp luật).
  - `mode="data"` → `image_to_data` (word + bbox + confidence) cho form.
- **Input path cố định** cho mọi pipeline: bỏ tham số `path`, mỗi command xử lý
  toàn bộ file trong `input_dir`.
- **Block schema thống nhất**: mỗi page có list `blocks`; `bbox`/`confidence`
  chỉ xuất hiện ở data mode.
- **Output file**: `<stem>.<pipeline>.json` để chạy nhiều pipeline trên cùng
  file không ghi đè nhau.
- Command `process` cũ bị thay bằng các subcommand theo tên pipeline.

## Module Layout

```
main.py                # launcher: subcommand sinh từ registry, bỏ positional path
ocr_core/
  pipeline.py          # run(): skeleton giữ nguyên; engine+gom -> 1 lời gọi extract
  extract.py           # MỚI (mở rộng từ aggregate.py): gom theo granularity
  engines/
    base.py            # OCREngine: recognize_words + recognize_text; Word dataclass
    tesseract.py       # image_to_data (words) + image_to_string (text)
    __init__.py        # registry engine (giữ nguyên)
  config.py            # Config + mode, granularity + validate tổ hợp + PIPELINES registry
  loaders.py           # giữ nguyên
  preprocessing.py     # giữ nguyên
input/                 # nguồn cố định
out/                   # output JSON
```

## Registry (trong `config.py`)

```python
PIPELINES = {
    "legal":   Config(mode="text", granularity="paragraph", lang="vie", ...),
    "invoice": Config(mode="data", granularity="line",      lang="vie", ...),
}
```

CLI:

```
python main.py legal                      # input/ -> profile pháp luật
python main.py invoice                    # input/ -> profile form
python main.py legal -c override.yaml --granularity page
```

Thêm pipeline mới về sau = thêm 1 entry vào `PIPELINES`; chỉ khi cần logic riêng
mới đụng tới engine/extract. Core `run()` không đổi.

## Config (`config.py`)

```python
@dataclass
class Config:
    engine: str = "tesseract"
    lang: str = "vie"
    mode: str = "data"              # "text" | "data"
    granularity: str = "line"       # "page" | "paragraph" | "line"
    preprocess_steps: list[str] = ...   # ["grayscale", "deskew", "binarize"]
    input_dir: str = "./input"
    output_dir: str = "./out"
```

Validate (fail-fast):
- `mode="text"` → `granularity ∈ {page, paragraph}` (không bbox).
- `mode="data"` → `granularity = line` (có bbox + confidence).
- engine lạ / step lạ / tổ hợp mode↔granularity sai → `ConfigError` liệt kê giá
  trị hợp lệ.

Precedence: **cờ CLI > file `-c` > default của profile trong registry**.

## Engine Interface (`engines/base.py`)

```python
class OCREngine(ABC):
    @abstractmethod
    def recognize_words(self, image, lang) -> list[Word]:
        """data mode: word + bbox (x,y,w,h) + confidence + line_key."""
    @abstractmethod
    def recognize_text(self, image, lang) -> str:
        """text mode: prose thuần (giữ \\n, đoạn cách nhau bằng dòng trống)."""
```

`TesseractEngine`:
- `recognize_words` = logic hiện tại (`image_to_data`, lọc rows conf < 0).
- `recognize_text` = `pytesseract.image_to_string(image, lang=lang)`.
- Thiếu binary → `EngineError` kèm gợi ý cài (giữ nguyên).

Lý do tách 2 method thay vì 1 method có cờ: kiểu trả về khác hẳn
(`list[Word]` vs `str`); engine mới chỉ cần cài method nào nó hỗ trợ.

## Extraction & Data Flow (`extract.py`)

```python
def extract(engine, image, config) -> list[dict]:
    if config.mode == "data":                          # granularity = line
        words = engine.recognize_words(image, config.lang)
        return _to_lines(words)                        # [{text, bbox, confidence}]
    text = engine.recognize_text(image, config.lang)   # mode = text
    if config.granularity == "page":
        return [{"text": text.strip()}] if text.strip() else []
    return [{"text": p} for p in _split_paragraphs(text)]   # paragraph
```

- `_to_lines` = `to_lines` hiện tại (gom theo `line_key`, union bbox, mean conf).
- `_split_paragraphs(text)` = tách theo dòng trống (`\n\s*\n`), trim, bỏ đoạn rỗng.
- Page granularity → đúng 1 block/trang.

`run()` — skeleton giữ nguyên, đổi engine+aggregate thành 1 lời gọi `extract`:

```python
for page in pages:
    try:
        img = preprocessing.apply(page.image, config.preprocess_steps)
        blocks = extract.extract(engine, img, config)
        results.append({"page": page.page, "blocks": blocks, "error": None})
    except Exception as e:                      # best-effort per page (giữ nguyên)
        results.append({"page": page.page, "blocks": [],
                        "error": f"{type(e).__name__}: {e}"})
```

`run_to_file(input, config, pipeline)` thêm tham số `pipeline` để dựng tên file
`<stem>.<pipeline>.json` (config giữ thuần data, không nhét tên pipeline vào).

Key `"lines"` cũ → `"blocks"` (tên trung tính cho cả 3 granularity). Engine khởi
tạo 1 lần trước vòng lặp (như hiện tại).

## Output JSON Schema

`legal` (text/paragraph):

```json
{
  "source": "vbpl.pdf", "engine": "tesseract", "lang": "vie",
  "mode": "text", "granularity": "paragraph", "page_count": 2,
  "pages": [
    { "page": 1, "blocks": [ {"text": "Điều 1. ..."}, {"text": "Điều 2. ..."} ],
      "error": null }
  ]
}
```

`invoice` (data/line):

```json
{
  "source": "scan.pdf", "engine": "tesseract", "lang": "vie",
  "mode": "data", "granularity": "line", "page_count": 1,
  "pages": [
    { "page": 1, "blocks": [
        {"text": "Invoice #123", "bbox": [100,80,220,28], "confidence": 96.4} ],
      "error": null }
  ]
}
```

- Cùng cấu trúc; `bbox`/`confidence` chỉ có ở data mode — consumer đọc theo
  `mode` ở header.
- File output: `<stem>.<pipeline>.json` trong `output_dir`.
- `error` là `null` khi thành công, string khi page lỗi.

## Error Handling

| Error                          | Where               | Behavior                                    |
|--------------------------------|---------------------|---------------------------------------------|
| Unsupported file format        | Loader              | Raise `UnsupportedFormatError` — abort file |
| PDF corrupt / unreadable       | Loader              | Raise — abort file                          |
| Tổ hợp mode↔granularity sai    | Config              | Raise `ConfigError` — abort run             |
| Unknown engine / step          | Config/Preprocessor | Raise `ConfigError` — abort run             |
| Preprocess/OCR fails on a page | Pipeline (per page) | Caught → page `error`, `blocks: []`, tiếp   |
| Tesseract binary missing       | Engine              | Raise `EngineError` kèm gợi ý cài           |

Nguyên tắc giữ nguyên: lỗi setup/config fail-fast; lỗi per-page/per-file là
best-effort, ghi inline. Batch thành công miễn input load được.

## Testing Strategy

Framework: `pytest`. Fixture ảnh in-memory bằng PIL (không cần binary).

**Unit (không cần Tesseract/Poppler):**
- `config`: default mỗi profile từ registry; precedence CLI > file > profile;
  tổ hợp sai (`text`+`line`, engine lạ, step lạ) → `ConfigError`.
- `extract` (mock engine):
  - data/line → `_to_lines`: union bbox, mean confidence (port test cũ).
  - text/page → 1 block/trang, text strip; trang rỗng → `[]`.
  - text/paragraph → `_split_paragraphs` tách đúng theo dòng trống, bỏ đoạn rỗng.

**Engine (mock `pytesseract`):**
- `recognize_words` parse TSV → `Word`.
- `recognize_text` trả `image_to_string`.

**Pipeline (mock engine, per-page error contract):**
- 1 trang OK + 1 trang raise → JSON 1 trang có `blocks`, 1 trang `error` +
  `blocks: []`.

**CLI / registry:**
- Mỗi tên trong `PIPELINES` tạo được subcommand.
- Tên file output = `<stem>.<pipeline>.json`.

**Integration (skip nếu thiếu Tesseract):**
- 1 PNG nhỏ qua cả `legal` và `invoice`.

## Migration Checklist

- `aggregate.py` → `extract.py`; `to_lines` → `_to_lines` (logic giữ nguyên).
- `engines/base.py`: `recognize` → `recognize_words` + thêm `recognize_text`;
  cập nhật `tesseract.py`.
- `config.py`: thêm `mode`, `granularity` + validate tổ hợp.
- `main.py`: bỏ command `process` + positional `path`; sinh subcommand từ registry.
- `pipeline.py`: `lines` → `blocks`; gọi `extract`; `run_to_file` thêm `pipeline`.
- Thêm `PIPELINES` registry vào `ocr_core/config.py` (cùng chỗ với `Config`).
