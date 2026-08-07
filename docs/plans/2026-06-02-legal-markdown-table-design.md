# ocr-core — Legal pipeline → Markdown + trích bảng — Design

Date: 2026-06-02
Status: Validated

## Mục tiêu

Đổi pipeline `legal` (giữ nguyên tên command) để xuất **file `.md` thuần** thay vì
JSON, và **trích đúng bảng có kẻ khung** thành markdown table — thay cho hành vi
hiện tại đang bẹp bảng thành văn xuôi (cột dồn vào nhau, nhiều dòng gộp lại).

Tài liệu mẫu (tờ trình) là prose xen bảng đặc tả kỹ thuật **có khung đầy đủ**, 3
cột `STT | Hạng mục | Yêu cầu kỹ thuật`, có **ô gộp** (rowspan cột STT/Hạng mục),
**hàng tiêu đề trải hết bảng** ("I. ...", "II. ..."), **ô nhiều dòng**, và bảng
**tràn qua trang**.

Đồng thời **loại bỏ hẳn mode `text` (granularity `page`/`paragraph`)** vì sau thay
đổi này không còn pipeline nào dùng tới.

## Key Decisions

- **`mode="markdown"` mới**, quyết định cả cách trích xuất lẫn định dạng file ghi
  ra. Không thêm field `output_format` (suy `.md` từ `mode` — YAGNI).
- **Giữ skeleton `run()`**: load → preprocess → `extract` per-page → assemble dict;
  best-effort per-page không đổi. Markdown chỉ là **mode mới + bước serialize cuối**.
- **`run()` luôn trả dict trung gian có cấu trúc**; `run_to_file()` rẽ nhánh
  serializer theo `mode` (markdown → `.md`, còn lại → `.json`). Giữ contract lỗi
  per-page và tách bạch để test.
- **Hình học tách khỏi OCR**: `tables.py` thuần `cv2` (test không cần Tesseract);
  OCR ô nằm ở `extract.py`.
- **Bảng có khung**: dò đường kẻ bằng morphology; suy span của ô gộp bằng cách map
  cạnh ô về index đường lưới.
- **Ô gộp → fill** (lặp giá trị vào mọi ô logic). **Hàng section trải hết bảng →
  giữ trong 1 bảng**, render `| **text** |  |  |` (cách (a), gọn, liền mạch).
- **Loại bỏ mode `text`/`paragraph`** và code liên quan; giữ lại engine method
  `recognize_text` và helper `_split_paragraphs` vì markdown tái dùng chúng.
- **Bỏ qua bảng tràn trang** (YAGNI): mỗi trang dò độc lập.

## Module Layout

```
core/
  config.py        # + mode "markdown"; BỎ mode "text"
  pipeline.py      # run() không đổi; run_to_file() rẽ serializer theo mode
  extract.py       # extract(): nhánh data | markdown (BỎ nhánh text);
                   #   + _extract_layout, _table_block; GIỮ _split_paragraphs
  tables.py        # MỚI: detect_tables() thuần cv2 (geometry, không OCR)
  markdown.py      # MỚI: to_markdown(doc) -> str
  engines/
    base.py        # recognize_text(image, lang, psm=None)
    tesseract.py   # psm -> config="--psm N"
  loaders.py       # không đổi
  preprocessing.py # không đổi
main.py            # KHÔNG đổi (subcommand sinh từ registry; chỉ in path)
```

## Config (`config.py`)

```python
VALID_GRANULARITY = {
    "markdown": {"document"},   # MỚI
    "data":     {"line"},
    # BỎ: "text": {"page", "paragraph"}
}
PIPELINES = {
    "legal":   Config(mode="markdown", granularity="document"),  # ĐỔI
    "invoice": Config(mode="data",     granularity="line"),
}
```

`DEFAULTS = Config()` vẫn `mode="data", granularity="line"`. Validate hiện có tự
kiểm `granularity ∈ VALID_GRANULARITY[mode]` → tổ hợp sai fail-fast như cũ. Sau khi
bỏ `text`, mode hợp lệ chỉ còn `{markdown, data}`.

## Loại bỏ mode text/paragraph

**Xóa:**
- `config.py`: entry `"text": {"page", "paragraph"}` trong `VALID_GRANULARITY`.
- `extract.py`: nhánh `mode == "text"` (gồm logic `page` → 1 block/trang và
  `paragraph` → list paragraph block). Sau khi xóa, `extract()` chỉ còn 2 nhánh.
- `GUIDELINE.md`: các mô tả về `mode=text`, `granularity=page/paragraph`, ví dụ
  output text/paragraph (cập nhật sang markdown).

**Giữ lại (markdown tái dùng):**
- `engines.recognize_text` — dùng để OCR ô bảng và prose band.
- `extract._split_paragraphs` — dùng tách prose band thành paragraph.

`extract()` sau thay đổi:

```python
def extract(engine, image, config) -> list[dict]:
    if config.mode == "data":            # granularity = line
        return _to_lines(engine.recognize_words(image, config.lang))
    return _extract_layout(engine, image, config.lang)   # mode = markdown
```

## Engine interface (`engines/base.py`, `tesseract.py`)

Thêm tham số tùy chọn `psm` (backward-compatible, mặc định giữ hành vi cũ):

```python
def recognize_text(self, image, lang, psm: int | None = None) -> str: ...
```

`TesseractEngine`: `cfg = f"--psm {psm}" if psm else ""`,
`pytesseract.image_to_string(image, lang=lang, config=cfg)`. OCR ô bảng gọi
`psm=6` (single uniform block) cho kết quả sạch hơn auto.

## Dò khung & dựng lưới (`tables.py`, thuần cv2)

```python
@dataclass
class Cell:  r0:int; c0:int; r1:int; c1:int; box:tuple  # span [r0,r1)×[c0,c1), box=(x,y,w,h)
@dataclass
class Table: box:tuple; n_rows:int; n_cols:int; cells:list[Cell]

def detect_tables(img: np.ndarray) -> list[Table]: ...
```

Thuật toán:

1. Nhị phân đảo `THRESH_BINARY_INV + OTSU` → nét/đường thành trắng.
2. Tách đường bằng morphology open: kernel ngang `(w//40, 1)` → `horiz`; kernel dọc
   `(1, h//40)` → `vert`. `grid = horiz | vert`.
3. Vùng bảng = `boundingRect` các contour của `grid`, lọc diện tích lớn **và** có
   ≥2 đường ngang & ≥2 đường dọc (loại đường lẻ / ô chữ ký).
4. Trong mỗi vùng:
   - `Xs` (đường phân cột) / `Ys` (đường phân hàng): chiếu `vert`/`horiz` lên trục,
     cụm vị trí mật độ cao. Lưới logic = `(len(Ys)-1) × (len(Xs)-1)`.
   - Ô thực = contour của `bitwise_not(grid)` trong vùng (vùng trắng khép kín), lọc
     theo diện tích. Ô gộp thiếu đường trong nên ra **một rect lớn**.
   - Map 4 cạnh mỗi ô về index `Ys`/`Xs` gần nhất → `(r0,c0,r1,c1)`; span suy trực
     tiếp từ chênh lệch index.

Hằng số (`//40`, ngưỡng diện tích) đặt đầu file, tinh chỉnh được.

## Trích xuất & data flow (`extract.py`)

Schema block trung gian (chỉ markdown mode dùng `type`; `data` giữ block cũ):

```python
{"type": "paragraph", "text": "..."}
{"type": "table", "rows": [[cell,...], ...], "header": True}
# hàng section trải hết bảng: row là list 1 phần tử [text]
```

```python
def _extract_layout(engine, image, lang) -> list[dict]:
    arr = np.array(image)
    tables = tables_mod.detect_tables(arr)
    items = []  # (y, block)
    for t in tables:
        items.append((t.box[1], _table_block(engine, image, t, lang)))
    for y, box in _prose_bands(image.size, [t.box for t in tables]):
        text = engine.recognize_text(image.crop(box), lang)
        for p in _split_paragraphs(text):
            items.append((y, {"type": "paragraph", "text": p}))
    return [b for _, b in sorted(items, key=lambda it: it[0])]

def _table_block(engine, image, t, lang) -> dict:
    grid = [[""] * t.n_cols for _ in range(t.n_rows)]
    section = {}  # row idx -> text (ô trải hết bảng)
    for cell in t.cells:
        x, y, w, h = cell.box
        txt = " ".join(engine.recognize_text(image.crop((x, y, x + w, y + h)),
                                             lang, psm=6).split())
        if cell.c1 - cell.c0 == t.n_cols:          # hàng section
            section[cell.r0] = txt
            continue
        for r in range(cell.r0, cell.r1):          # fill ô gộp
            for c in range(cell.c0, cell.c1):
                grid[r][c] = txt
    rows = [[section[i]] if i in section else grid[i] for i in range(t.n_rows)]
    return {"type": "table", "rows": rows, "header": True}

def _prose_bands(size, boxes):
    """Băng ngang ngoài bảng -> (y_top, crop_box). Bảng coi như chiếm trọn bề ngang."""
    W, H = size
    spans = sorted((b[1], b[1] + b[3]) for b in boxes)  # (top, bottom)
    bands, y = [], 0
    for top, bot in spans:
        if top - y > MIN_BAND:
            bands.append((y, (0, y, W, top)))
        y = max(y, bot)
    if H - y > MIN_BAND:
        bands.append((y, (0, y, W, H)))
    return bands
```

`run()` không đổi: vẫn gọi `extract.extract(engine, img, config)`, bọc thành
`{"page", "blocks", "error"}`; lỗi 1 trang → `blocks: []` + `error`.

## Markdown serialize (`markdown.py`)

```python
def to_markdown(doc: dict) -> str:
    parts = []
    for pg in doc["pages"]:
        if pg["error"]:
            parts.append(f"<!-- page {pg['page']} error: {pg['error']} -->")
            continue
        for b in pg["blocks"]:
            parts.append(b["text"] if b["type"] == "paragraph" else _table(b))
    return "\n\n".join(parts) + "\n"

def _esc(s): return s.replace("|", "\\|")

def _table(b) -> dict:
    rows, n = b["rows"], max(len(r) for r in b["rows"])
    n = max(n, *(len(r) for r in rows if len(r) != 1))  # số cột thực
    out = []
    for i, r in enumerate(rows):
        cells = r + [""] * (n - len(r)) if len(r) != 1 else [f"**{r[0]}**"] + [""] * (n - 1)
        out.append("| " + " | ".join(_esc(c) for c in cells) + " |")
        if i == 0 and b.get("header"):
            out.append("| " + " | ".join("---" for _ in range(n)) + " |")
    return "\n".join(out)
```

- Hàng đầu là header (`header=True`) → chèn dòng `---`.
- Hàng section (`len(r)==1`) → `| **text** |  |  |`.
- Ký tự `|` trong ô được escape.
- Trang nối nhau bằng `\n\n`; trang lỗi → comment HTML.

## Output / `run_to_file` (`pipeline.py`)

```python
doc = run(input_path, config)
if config.mode == "markdown":
    body, ext = markdown.to_markdown(doc), "md"
else:
    body, ext = json.dumps(doc, indent=2, ensure_ascii=False), "json"
out_path = out_dir / f"{Path(input_path).stem}.{pipeline}.{ext}"
out_path.write_text(body)
```

`legal` → `<stem>.legal.md`; `invoice` → `<stem>.invoice.json` (không đổi).
`main.py` chỉ in path trả về → không cần sửa.

## Error handling

| Tình huống | Hành vi |
|---|---|
| `mode=markdown` + granularity ≠ `document` | `ConfigError` (validate sẵn có) |
| Trang không có đường kẻ | `detect_tables→[]` → cả trang là 1 prose band → như text cũ (fallback tự nhiên) |
| `cv2`/detect lỗi, OCR ô lỗi (1 trang) | bắt per-page trong `run()` → page `error`, trang khác vẫn chạy; serializer chèn `<!-- page N error -->` |
| Tesseract binary thiếu | `EngineError` → rơi vào per-page error |
| File hỏng / format lạ | abort file (loader, không đổi) |

## Testing

`pytest`. Phần lõi chạy không cần Tesseract.

- **`tables.py` (cv2 thuần — test chính):** vẽ ảnh lưới bằng `cv2.line` (3 cột, 1 ô
  gộp dọc + 1 hàng full-width) → assert `n_rows/n_cols` và span `Cell` đúng.
- **`extract._table_block` (mock engine):** `recognize_text` trả text theo crop +
  monkeypatch `detect_tables` trả `Table` đã biết → assert `rows`, hàng section `[text]`.
- **`markdown.to_markdown`:** doc gồm paragraph + table (có hàng section + ô chứa
  `|`) → so khớp markdown chính xác (dòng `---`, ô trống, escape `\|`).
- **`config`:** legal default `mode=markdown` hợp lệ; `markdown`+`line` → `ConfigError`;
  `mode="text"` không còn hợp lệ.
- **`pipeline.run_to_file`:** markdown → `<stem>.legal.md`; data → `.json`.
- **`engine`:** `recognize_text(..., psm=6)` → mock `pytesseract`, assert `--psm 6`.
- **Integration (skip nếu thiếu Tesseract/Poppler):** chạy `legal` trên trang mẫu
  thật → output chứa dấu phân cách bảng `---`.

## Migration checklist

- `config.py`: thêm `markdown` vào `VALID_GRANULARITY`, bỏ `text`; đổi `PIPELINES["legal"]`.
- `extract.py`: bỏ nhánh `text`; thêm `_extract_layout`, `_table_block`, `_prose_bands`;
  giữ `_split_paragraphs`, `_to_lines`.
- `tables.py`: tạo mới (`detect_tables`, `Cell`, `Table`).
- `markdown.py`: tạo mới (`to_markdown`).
- `engines/base.py`, `tesseract.py`: thêm `psm` vào `recognize_text`.
- `pipeline.py`: `run_to_file` rẽ serializer theo `mode`.
- `GUIDELINE.md`: cập nhật mô tả/ví dụ (bỏ text/paragraph, thêm markdown).
- Tests theo mục Testing.

## Known limitations

- **Bảng tràn nhiều trang**: mỗi trang dò độc lập → ra nhiều bảng; hàng nối ở trang
  sau có thể có ô STT/Hạng mục trống. Không merge xuyên trang (YAGNI).
- **Chỉ bảng có khung**: bảng không kẻ khung không được phát hiện → rơi về prose.
- **Span trong markdown**: GFM không hỗ trợ, nên ô gộp bị lặp giá trị (fill).
