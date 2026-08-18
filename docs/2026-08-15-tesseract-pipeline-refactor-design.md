# Refactor ocr-core theo kiến trúc triển khai, model Tesseract - phase 1-3

Ngày: 2026-08-15. Trạng thái: đã duyệt thiết kế, chờ viết plan.

Phạm vi: zone 1 (OCR) và zone 3 (fine-tune) của `[kien-truc-trien-khai.md](../../kien-truc-trien-khai.md)`. Zone 2 (trích xuất thông tin) là spec riêng, viết sau khi phase 1 chốt được hình dạng `Document` thật.

## 1 · Mục tiêu và bối cảnh

Dựng lại repo thành một vòng khép kín chạy được trên một máy: OCR một tập PDF ra `.md` + `.coco.json`, chấm ngưỡng tin cậy, cho người sửa trang dưới ngưỡng qua web UI, lấy chính những trang đó làm dữ liệu fine-tune Tesseract, rồi chạy lại với model mới.

Đây là môi trường thử nghiệm cá nhân, không phải bản giao cho khách hàng. Tiêu chí thành công là **luồng chạy thông end-to-end và sinh đúng artifact ở mỗi bước**, không phải một mức CER cụ thể. `evaluate/` vẫn chạy và in số ra, nhưng không phải cổng chặn.

Model đổi từ Chandra OCR 2 sang Tesseract 5. Hệ quả trực tiếp: hộp `Chandra OCR 2` trong sơ đồ vỡ thành nhiều cấu phần vì Tesseract chỉ nhận chữ, không trả nhãn bố cục, không đọc bảng, không đọc công thức, và không có log-prob.

## 2 · Quyết định thiết kế đã chốt

| # | Quyết định | Phương án bị loại |
| --- | --- | --- |
| 1 | Layout = block của Tesseract + `table_cv` (OpenCV, bảng kẻ khung) | Thuần Tesseract (mất hẳn bảng); Tesseract + PP-DocLayout (kéo PaddlePaddle vào, phần layout lại không fine-tune được) |
| 2 | Nhãn mức dòng cho fine-tune sinh **tự động** bằng cách gióng OCR với text layer trong `ground_truth/lpbank/` | Người sửa từng dòng (tốn giờ); synthetic `text2image` (không giống ảnh thật) |
| 3 | Zone 1 làm QA gating + page orchestration + review UI; **không** làm `.html`, **không** làm searchable PDF | Làm cả bốn |
| 4 | Review là web UI FastAPI, checkpoint là SQLite | Sửa bằng editor trên file; hàng đợi Redis/Celery |
| 5 | Xoá `core/extract.py`, `core/postprocess.py`, `core/preprocessing.py`, `core/pipeline.py` cũ; giữ `core/tables.py` | Giữ song song hai đường chạy |
| 6 | Xoá `finetune/bootstrap.py`, `finetune/build_dataset.py`, viết lại toàn bộ package | Sửa dần từ code Chandra |

## 3 · Cây package

```
core/         zone 1 - OCR một trang -> Document -> .md + .coco.json
orchestrate/  zone 1 - hàng đợi trang, checkpoint, review UI
finetune/     zone 3 - cắt dòng -> gióng nhãn -> lstmtraining -> .traineddata
evaluate/     đo chất lượng, KHÔNG đụng tới
extract/      zone 2 - spec riêng, chưa làm
```

Chiều phụ thuộc một chiều: `orchestrate -> core`, `finetune -> core + evaluate`. `core` không import hai package kia. Điều kiện kiểm chứng: `python main.py <pdf>` chạy được khi `orchestrate/` và `finetune/` bị xoá khỏi đĩa.

### 3.1 `core/`

| Đường dẫn | Trạng thái | Việc |
| --- | --- | --- |
| `geometry.py` `preprocess.py` | không sửa | dùng lại nguyên vẹn |
| `serialize/__init__.py` `serialize/markdown.py` `serialize/coco.py` | không sửa | |
| `engines/` | không sửa | `01-ocr.md` (engines) ghi rõ |
| `tables.py` | không sửa | được gọi từ `layout/table_cv.py`; `recognize/table.py` **không** gọi lại (§4.3) |
| `loader.py` | **sửa** | thêm `load_page(path, page, dpi)` và `page_count(path)`; `load()` hiện render cả tài liệu, mỗi worker gọi nó để lấy một trang là render lại toàn bộ PDF (§5.3) |
| `document/model.py` | **sửa** | thêm `TextLine`, đổi `TextContent` (§4.4) |
| `document/serde.py` | mới | `Document`/`PageGeometry`/`Element` <-> dict JSON (§5.2) |
| `layout/base.py` | mới | `LayoutDetector` ABC, `LayoutBox` |
| `layout/tesseract_blocks.py` | mới | gom `image_to_data` theo `block_num` |
| `layout/table_cv.py` | mới | bọc `core/tables.py` thành `LayoutDetector`, mang theo lưới ô |
| `layout/none.py` | mới | fallback: một element `text` phủ cả trang |
| `layout/__init__.py` | mới | `get_detector(name)`, quy tắc trừ nhau (§4.2) |
| `recognize/base.py` `recognize/text.py` `recognize/table.py` `recognize/__init__.py` | mới | stage 4 |
| `document/reading_order.py` `document/link.py` `document/assemble.py` `document/validate.py` | mới | stage 5 |
| `pipeline.py` | viết lại | `run_page()` và `run_document()` |
| `config.py` | viết lại | bỏ `mode` và `PIPELINES` |
| `qa.py` | mới | chấm ngưỡng, trả `PageVerdict` |
| `extract.py` `postprocess.py` `preprocessing.py` | **xoá** | |
| `main.py` (gốc repo) | **viết lại** | hiện nhận tên pipeline, phải nhận đường dẫn file (§3.4) |

### 3.2 `orchestrate/`

| Đường dẫn | Việc |
| --- | --- |
| `state.py` | SQLite `page_state`, API ở §5.1 |
| `runner.py` | CLI `run` / `merge` / `retry-failed`, pool worker |
| `review/app.py` | FastAPI, 3 route ở §5.4 |
| `review/templates/index.html` `review/templates/page.html` | Jinja2 |
| `__main__.py` | `python -m orchestrate <lệnh>` |

### 3.3 `finetune/`

| Đường dẫn | Việc |
| --- | --- |
| `guards.py` | Hai cổng chặn ở §6.1 |
| `cut_lines.py` | `TextLine` -> ảnh dòng + `.gt.txt` chờ nhãn |
| `align.py` | gióng dòng OCR với ground truth -> `.gt.txt` |
| `degrade.py` | blur / nhiễu / JPEG, opt-in |
| `lstmf.py` | cặp `png` + `gt.txt` -> `.lstmf` + `list.train` |
| `train.py` | wrapper gọi `lstmtraining`, `combine_tessdata` |
| `README.md` | viết lại |
| `bootstrap.py` `build_dataset.py` | **xoá** |

### 3.4 `main.py`

`main.py` hiện tại nhận **tên pipeline** (`python main.py legal`), import `PIPELINES` và `core.pipeline.SUPPORTED_EXTS`, cả hai đều biến mất. Bản mới:

```
python main.py <path> [--config config.yaml] [--out output/]
```

Một file, một `Document`, ghi `.md` + `.coco.json`. Đây là đường chạy `core` một mình, không đụng SQLite và không đụng `artifacts/`. `orchestrate` là đường chạy hàng loạt có checkpoint. Hai đường tồn tại song song vì `main.py` là cách kiểm chứng `core` độc lập theo ràng buộc ở §3.

**Thư mục output phải là `<--out>/<stem của file nguồn>/`, không phải `<--out>/`.** `write_document` lấy tên file output từ **tên thư mục** (`stem = directory.name`, `core/serialize/__init__.py:30`), nên truyền thẳng `output/` sẽ ghi `output/output.md` cho mọi tài liệu, cái sau đè cái trước. `evaluate/` lại ghép prediction với ground truth theo stem và raise khi trùng stem, nên tiêu chí nghiệm thu phase 1 (`python -m evaluate.run` trên 7 PDF) hỏng ngay từ tài liệu thứ hai. Ràng buộc này áp cho cả `main.py` lẫn `orchestrate merge`.

## 4 · Zone 1 - luồng OCR

### 4.1 Sáu stage

```
run_document(path, cfg) -> Document
run_page(path, page, cfg) -> PageResult

 1 Load        loader.py       PDF/ảnh -> PageImage + PageGeometry (pypdfium2, 300 DPI)
 2 Preprocess  preprocess.py   orientation -> deskew (giữ ma trận affine) -> denoise
 3 Layout      layout/         table_cv rồi tesseract_blocks, trừ nhau -> LayoutBox[]
 4 Recognize   recognize/      text -> TextRecognizer ; table -> TableRecognizer
 5 Assemble    document/       to_canonical -> link -> reading order -> gán id -> validate
 6 Serialize   serialize/      markdown.py -> .md  +  coco.py -> .coco.json
```

Stage 1, 2, 6 dùng lại code đã có. Stage 3, 4, 5 viết mới.

`run_page` là interface `orchestrate -> core`, và là hàm duy nhất `orchestrate` được phép gọi trong `core.pipeline`:

```python
@dataclass(frozen=True)
class PageResult:
    geometry: PageGeometry | None       # None khi lỗi ở stage 1
    elements: list[Element]
    image: Image.Image | None           # ảnh SAU preprocess, để orchestrate ghi .webp
    error: PageError | None

def run_page(path: str | Path, page: int, cfg: Config) -> PageResult
```

`run_page` nhận **đường dẫn và số trang**, không nhận ảnh: worker của `orchestrate` chỉ có `(path, page)` và không có gì để dựng `PageGeometry`. Bên trong nó gọi `loader.load_page(path, page, cfg.dpi)` - hàm mới, vì `loader.load()` hiện render **cả tài liệu** và gọi nó một lần cho mỗi worker sẽ render lại toàn bộ PDF cho từng trang.

`loader.page_count(path)` là hàm mới thứ hai, và cũng bắt buộc: `orchestrate run` phải chèn hàng `pending` cho từng trang **trước khi** xử lý trang nào, còn `run_document` phải biết lặp tới đâu. Không có nó thì cách duy nhất để đếm trang là render cả PDF ở 300 DPI - đúng chi phí mà `load_page` sinh ra để tránh.

`PageResult.image` là ảnh sau preprocess, trả ra ngoài vì đây là ảnh duy nhất mà bbox trong `elements` gióng đúng (§4.5), và nó chỉ tồn tại trong bộ nhớ ở bước này. `orchestrate/runner.py` là bên ghi nó ra `images/p{n}.webp`; `main.py` bỏ qua. `core` không tự ghi ảnh, đúng ràng buộc `core` không biết `artifacts/` tồn tại.

`reading_order` chỉ gán được ở mức tài liệu nên `run_page` để `-1`; `run_document` và `orchestrate merge` gán lại. Đây là chỗ duy nhất field đó tạm thời không hợp lệ.

Lỗi trong `run_page` không ném ra ngoài: trả `PageResult(None, [], None, PageError(...))`.

### 4.2 Stage 3 - hai detector nối tiếp rồi trừ nhau

Đây là chỗ lệch xa nhất so với bản staged Chandra (2026-08-07, đã thay), vốn giả định một `LayoutDetector` trả thẳng 11 class DocLayNet. Tesseract không gán nhãn cho block nó tìm được, nên stage 3 ghép hai nguồn.

```python
@dataclass(frozen=True)
class LayoutBox:
    category: str                        # "text" | "table"
    bbox: tuple[int, int, int, int]      # KHUNG DESKEW, không phải hệ chuẩn (§4.5)
    layout_score: float | None = None    # luôn None với cả hai detector
    cells: list[Cell] | None = None      # chỉ table_cv điền, kiểu Cell của core/tables.py
    n_rows: int | None = None            # từ Table.n_rows, không suy lại (§4.3)
    n_cols: int | None = None
```

1. `table_cv.detect(page)` chạy trước, dùng `core/tables.py` dò đường kẻ ngang-dọc, trả `LayoutBox(category="table", cells=...)`. Lưới ô đi kèm trong `cells` để stage 4 không phải dò lại.
2. `tesseract_blocks.detect(page)` gọi `pytesseract.image_to_data`, gom `Word` theo `block_num` thành `LayoutBox(category="text")` với bbox bao các từ trong block.
3. Box `text` bị **bỏ** khi `diện tích giao với một vùng table / diện tích của chính box text >= 0.7`.

Bước 3 dùng **tỉ lệ bao chứa**, không phải IoU. IoU sai ở đây: một block text một dòng nằm gọn trong bảng chiếm 30% trang cho IoU khoảng 0,1 và sẽ được giữ lại, khiến mọi ô bảng xuất hiện hai lần trong `.md` - đúng thứ bước này sinh ra để chặn. Ngưỡng 0,7 (không phải 1,0) để chịu được sai lệch vài pixel giữa hai detector. Hằng số nằm ở `layout/__init__.py`, không rải rác.

Chỉ hai category được sinh ra. `picture`, `formula`, `title`, `section-header`, `list-item`, `caption`, `footnote`, `page-header`, `page-footer` không bao giờ xuất hiện với cấu hình này. Hằng `DOCLAYNET_CLASSES` giữ nguyên đủ 11 giá trị vì nó là bộ class chuẩn của COCO, không phải danh sách những gì detector hiện tại làm được.

`layout="none"` giữ vai trò fallback bắt buộc: mỗi trang thành một element `text` phủ cả trang.

**Ràng buộc cặp đôi:** `layout="tesseract"` gom theo `block_num`, thứ chỉ Tesseract trả về. `01-ocr.md` (engines) ghi rõ Paddle và EasyOCR đặt `line_key = (round(y/10), x)` vì chúng detect cả dòng. Nên `config.validate()` phải **raise** khi `layout == "tesseract"` mà `engine != "tesseract"`, thay vì sinh kết quả rác trong im lặng.

### 4.3 Stage 4 - router theo category

| Category | Recognizer | Cách làm |
| --- | --- | --- |
| `text` | `recognize/text.py` | `engines.recognize_words()` trên vùng crop, gom `Word` theo `line_key` thành `TextLine`, nối thành `TextContent` |
| `table` | `recognize/table.py` | Dùng `LayoutBox.cells` **đã có từ stage 3**, mỗi ô gọi `engines.recognize_text(psm=6)`, dựng `TableContent` |

`recognize/table.py` **không** gọi lại `core/tables.py`. Dò hai lần trên cùng một trang tốn gấp đôi và cho phép hai kết quả bất đồng; lưới ô đi theo `LayoutBox.cells` từ stage 3.

Dựng `TableContent.html` từ `list[Cell]`: sắp ô theo `(r0, c0)`, mỗi giá trị `r0` là một `<tr>`, mỗi ô là một `<td>` với `rowspan = r1 - r0` và `colspan = c1 - c0` (chỉ ghi thuộc tính khi lớn hơn 1). Ô có `r0` trùng một hàng đã bị ô khác chiếm bởi `rowspan` thì bỏ qua vị trí đó, không chèn `<td>` rỗng. Không có `<thead>`: `core/tables.py` không phân biệt hàng tiêu đề.

`n_rows`/`n_cols` lấy thẳng từ `Table.n_rows`/`Table.n_cols` của `core/tables.py:101`, **không** suy lại bằng `max(r1)`/`max(c1)`. Hai cách cho kết quả khác nhau khi `_cells()` lọc mất một ô vì diện tích nhỏ; `validate.py` so số ô với `n_rows * n_cols` để đặt cờ `cell_count_mismatch`, nên chọn sai nguồn là làm cờ đó bật giả trên mọi bảng có ô bị lọc. `LayoutBox` vì vậy mang cả `n_rows`/`n_cols` bên cạnh `cells`.

`recognize/text.py` gọi `recognize_words()` chứ không phải `recognize_text()`, vì `recognize_text()` trả `str` trần và mất confidence lẫn bbox mức dòng. Đây là điều kiện cho cả tín hiệu bất định lẫn `finetune/cut_lines.py`.

`recognize/text.py` là **điểm chia 100 duy nhất**: `Word.confidence` ở thang 0-100 trên cả ba engine (`core/engines/base.py:18`, `01-ocr.md`), `TextLine.confidence` ở thang 0-1. Chia ở đúng một chỗ, giống cách `assemble.py` là điểm chuyển hệ toạ độ duy nhất ở §4.5, vì đây cùng một loại lỗi.

### 4.4 Sửa `document/model.py`

Hai thay đổi, và đây là ngoại lệ duy nhất với nguyên tắc "không đụng `document/model.py`":

```python
@dataclass(frozen=True)
class TextLine:
    text: str                             # bản hiện hành, đã sửa nếu có người sửa
    text_ocr: str                         # bản OCR gốc, KHÔNG BAO GIỜ ghi đè
    polygon: list[tuple[float, float]]    # hệ chuẩn, tứ giác - nguồn sự thật về vị trí
    bbox: tuple[int, int, int, int]       # hệ chuẩn, hình chữ nhật bao lồi của polygon
    confidence: float | None              # 0..1, None khi engine không trả

@dataclass(frozen=True)
class TextContent:
    text: str                                        # nối TextLine.text bằng "\n"
    lines: list[TextLine] = field(default_factory=list)
```

**`lines` phải có `default_factory`, không phải trường bắt buộc.** `TextContent` đang được dựng bằng một tham số vị trí ở 14 chỗ trong `tests/`, trong đó có factory dùng chung `tests/test_serialize.py:28`. Trường bắt buộc làm cả hai file test đỏ với `TypeError`, và phản ứng tự nhiên khi thấy suite đỏ là sửa test - đúng thứ không được làm. Có default thì §9.1 giữ nguyên: `test_serialize` không phải đụng tới.

Lý do phải sửa, cả ba đều bắt buộc và không cái nào thay thế được cái nào:

- `finetune/cut_lines.py` cần vị trí **mức dòng**; `Element.bbox` là mức khối, cắt theo nó ra ảnh cả đoạn, `lstmtraining` không nhận.
- Review UI sửa theo dòng; giữ `text_ocr` cạnh `text` là cách duy nhất để `finetune` biết dòng nào thật sự sai. Dòng không đổi không phải mẫu lỗi và trộn vào tập train chỉ làm loãng tín hiệu.
- `Element.rec_score` = trung bình `TextLine.confidence` của các dòng có confidence; `None` khi không dòng nào có.

**`polygon` là nguồn sự thật, `bbox` là trường tiện dụng.** Lý do ở §4.5: phép biến đổi affine deskew là chính xác trên tứ giác nhưng **không** chính xác trên hình chữ nhật, và `cut_lines.py` phải đi ngược lại khung deskew. Mỗi lần thu tứ giác nghiêng về hình chữ nhật bao lồi làm chiều cao nở thêm `w · sin θ`; đi hai chiều bằng `bbox` thì một dòng cao 28 px thành khung cắt 44 px ở góc nghiêng 0,4 độ và 92 px ở 2 độ, tức ảnh dòng nào cũng dính mực của dòng trên và dòng dưới. Đó đúng là loại mẫu `lstmtraining` không học được, và bộ lọc chiều cao tối thiểu ở §6.2 không bắt được vì nó lọc dòng quá nhỏ chứ không lọc dòng quá to. Giữ `polygon` thì vòng đi-về chỉ thu về hình chữ nhật đúng một lần, ở đúng lúc cắt.

`TextContent.text` là trường suy ra, không phải nguồn sự thật. Ai sửa `lines` phải dựng lại `text`; `serde.py` là chỗ duy nhất làm việc đó khi đọc lại từ JSON.

Ba consumer **đọc** `TextContent.text` (`serialize/markdown.py:86`, `serialize/coco.py:111`, `evaluate/`) không phải sửa vì trường đó vẫn còn và vẫn mang đúng nghĩa cũ.

### 4.5 Hệ toạ độ - một điểm chuyển duy nhất

Detector và recognizer đều chạy trên **ảnh đã deskew**, vì đó là ảnh nằm trong bộ nhớ sau stage 2. Nên:

| Đối tượng | Khung |
| --- | --- |
| `LayoutBox.bbox`, `Cell.box`, `Word.bbox` | **khung deskew** |
| `Element.bbox`, `Element.polygon`, `TextLine.bbox`, `TextLine.polygon`, `TableContent.cell_boxes` | **hệ chuẩn** (sau rotation, trước deskew) |

`assemble.py` là **điểm chuyển duy nhất**, và nó chuyển đúng một lần cho mỗi hộp:

```python
polygon = geometry.to_canonical(geometry.corners(lb.bbox), geom)
bbox = geometry.bounding_box(polygon)
```

`geometry.corners()` là tên hàm thật ở `core/geometry.py:58` - hộp thành bốn góc. `polygon` giữ tứ giác nghiêng chính xác, `bbox` là hình chữ nhật bao lồi, đúng bản staged Chandra (2026-08-07, đã thay) §4.1. Cùng phép này áp cho `TextLine`, từ bbox của dòng trong khung deskew.

Không module nào khác được gọi `to_canonical`/`from_canonical`, trừ một ngoại lệ dưới đây; test phải khoá điều này.

**Chiều ngược lại có đúng một consumer:** `finetune/cut_lines.py` crop từ `images/p{n}.webp`, là ảnh **đã deskew**, nên nó gọi `from_canonical(line.polygon, geom)` rồi `bounding_box()` **một lần**. Đi qua `polygon` chứ không qua `bbox` là bắt buộc: `to_canonical`/`from_canonical` (`core/geometry.py:75-95`) chính xác trên tứ giác, nhưng thu về hình chữ nhật ở giữa đường thì mỗi chặng nở thêm `w · sin θ` và ảnh dòng cắt ra dính mực dòng bên cạnh (§4.4). `geom` đọc từ `pages/p{n}.json`, trong đó `deskew_matrix` đã được `serde.py` ghi.

### 4.6 Tín hiệu bất định

| Loại element | Bậc | Nguồn |
| --- | --- | --- |
| `text` | 2 | trung bình `TextLine.confidence`, thang 0-1, ghi vào `rec_score` |
| `table` | **3** | `recognize_text()` trả `str` trần, cả `rec_score` lẫn `logprob` đều `None` |

Bậc 1 (log-prob) không tồn tại với Tesseract.

Hệ quả phải chấp nhận: **QA gating chặn được văn xuôi nhưng không chặn được bảng.** Element bậc 3 đi qua cổng không bị gate, không bị flag, đúng quy tắc "chỉ gate element có tín hiệu" ở bản staged Chandra (2026-08-07, đã thay) §4.2. Muốn gate cả bảng thì phải đổi `recognize/table.py` sang gọi `recognize_words()` cho từng ô rồi tự ghép - ngoài phạm vi phase này.

### 4.7 Stage 5 - assemble

- `assemble.py`: chuyển hệ toạ độ (§4.5), đặt `render` đúng một lần, gán id bằng `document.model.element_id(page, index)` - hàm đã có, đã tự raise `DocumentError` khi vượt trần 10.000, không tự viết lại phép nhân.
- `reading_order.py`: XY-cut trên các element `flow`, gán `reading_order` dày đặc toàn tài liệu, không nullable.
- `link.py`: **chỉ viết nửa nối bảng tràn trang** (cùng số cột + cùng biên trái/phải sai số 2% -> `flags += ["table_continues"]` ở trang N, `continues_from` ở trang N+1). Nửa gắn caption là **hàm rỗng có docstring ghi lại quy tắc**, vì với hai category hiện có thì không có `caption` nào để gắn - viết đủ logic bây giờ là code chết ngay lúc giao.
- `validate.py`: **hai hàm, hai loại kết quả.**

  `validate_page(elements)` chạy trong `run_page` và kiểm **chất lượng nội dung**: parse HTML bảng bằng `lxml` (`invalid_html`), đếm ô so với `n_rows * n_cols` (`cell_count_mismatch`). Chỉ **set `flags`**, không đụng `rec_score`. Hai cờ này đã có sẵn trong `FLAGS` ở `core/document/model.py:31-38`.

  `validate_document(doc)` chạy trong `run_document` và trong `orchestrate merge`, sau khi `reading_order` đã gán, và kiểm **bất biến cấu trúc**: `reading_order` khác `-1`, dày đặc và duy nhất; `caption_id`/`continues_from` trỏ tới `Element.id` có thật. Những cái này **raise `DocumentError`**, không set cờ. Lý do: chúng không phải khiếm khuyết của tài liệu nguồn mà là lỗi lắp ráp của chính pipeline; một `reading_order` trùng nhau là bug trong `reading_order.py`, gắn cờ lên element và ghi ra `.md` là giấu bug vào output. Đây cũng là cách `FLAGS` giữ nguyên sáu giá trị và `model.py` giữ đúng hai thay đổi ở §4.4.

  **Không** kiểm `bbox` nằm trong khung trang. Một hộp chạm mép trang trong khung deskew, qua `to_canonical`, thành tứ giác nghiêng có bao lồi vượt biên trang - đó là hình học bình thường theo §4.5, không phải khiếm khuyết.

  Gộp hai hàm làm một thì `run_page` trượt chính kiểm tra của nó trên mọi trang, vì `reading_order` lúc đó cố ý bằng `-1` (§4.1).

### 4.8 `core/qa.py`

```python
@dataclass(frozen=True)
class PageVerdict:
    page: int
    passed: bool
    min_score: float | None      # None khi không element nào có tín hiệu
    below: list[int]             # Element.id dưới ngưỡng

def gate(elements: list[Element], threshold: float) -> PageVerdict
```

Trang đạt khi mọi element **có** tín hiệu đều `rec_score >= threshold`. Trang không có element nào mang tín hiệu (ví dụ trang chỉ có bảng) thì `passed = True`, `min_score = None`. Đây là hành vi có chủ ý theo §4.6, không phải sót.

`qa_threshold` mặc định 0,75. Con số này chưa đo, đặt để luồng chạy được; `kien-truc-trien-khai.md` nói rõ ngưỡng thật chỉ chốt sau khi có số đo trên corpus thật.

## 5 · Zone 1 - orchestration

### 5.1 State

```sql
CREATE TABLE page_state (
  doc_sha256 TEXT, pipeline_version TEXT, page INTEGER,
  source TEXT, status TEXT,
  rec_score REAL, attempt INTEGER DEFAULT 0, error TEXT, updated_at TEXT,
  PRIMARY KEY (doc_sha256, pipeline_version, page)
);
-- status: pending | running | done | needs_review | reviewed | failed
```

```python
def claim_pending(conn, limit: int) -> list[PageKey]      # pending -> running
def finish(conn, key: PageKey, status: str, rec_score, error) -> None
def reset_stale_running(conn, started_at: str) -> int
def counts(conn, doc_sha256, pipeline_version) -> dict[str, int]
```

`pipeline_version` **nằm trong khoá chính**, không phải một cột thường. Đây là điều kiện để §6.6 đóng được vòng: đổi sang `vie_lpbank` là đổi `pipeline_version`, mọi trang trở lại `pending` và được OCR lại. Không có nó thì mọi trang đã `done` và vòng phản hồi không bao giờ chạy lần hai. Đây cũng đúng bất biến của `kien-truc-trien-khai.md` §1: `pipeline_version` là một phần khoá checkpoint.

`pipeline_version` = `f"{engine}_{'+'.join(langs)}_{layout}_{table}_{h}"`, trong đó `h` là 8 ký tự đầu của SHA-256 trên JSON đã sắp khoá của **toàn bộ** `Config` trừ các trường đường dẫn (`input_dir`, `output_dir`, `artifacts_dir`, `ground_truth_dir`). Ví dụ: `tesseract_vie+eng_tesseract_cv_9f3a1c07`.

Bốn trường đầu để đọc bằng mắt, `h` để đúng. Chỉ ghép bốn trường thì đổi `dpi: 300 -> 200` hoặc bỏ `deskew` sẽ cho ra pixel khác, bbox khác, ảnh dòng khác, mà lại ghi đè vào **cùng** thư mục artifacts lên những hàng vẫn đang `done` - và làm sai luôn lập luận ở §5.4 rằng đổi config là đổi `pipeline_version`. Dùng `_` làm dấu phân tách vì mã ngôn ngữ có thể chứa `-`, còn `+` trong `langs` an toàn trên POSIX lẫn APFS.

`attempt` tăng mỗi lần `claim_pending` lấy một trang; `retry-failed` bỏ qua trang có `attempt >= 3` và in ra số trang bị bỏ qua. Không có cột đếm thì `retry-failed` lặp vô hạn trên một trang hỏng vĩnh viễn.

### 5.2 Artifacts và định dạng `pages/p{n}.json`

```
artifacts/<doc_sha256[:12]>/<pipeline_version>/
  meta.json          source, doc_sha256, pipeline_version, page_count, config đã dùng
  pages/p0007.json   một trang
  images/p0007.webp  ảnh 300 DPI SAU preprocess
```

Ghi **theo trang**: sửa trang 7 rồi chạy lại thì chỉ trang 7 bị ghi đè. Thư mục lồng theo `pipeline_version` để hai lần chạy với hai model khác nhau không đè lên nhau - cần cho việc so kết quả trước và sau fine-tune.

`core/document/serde.py` là **chủ sở hữu duy nhất** của định dạng này. Không module nào khác được đọc hay ghi các file đó bằng `json` trực tiếp.

```python
def page_to_dict(geom: PageGeometry, elements: list[Element]) -> dict
def page_from_dict(data: dict) -> tuple[PageGeometry, list[Element]]
def document_to_dict(doc: Document) -> dict
def document_from_dict(data: dict) -> Document
```

```json
{
  "schema": 1,
  "geometry": {"page": 7, "width_px": 2480, "height_px": 3508, "dpi": 300,
               "rotation_applied": 0, "deskew_angle": -0.4,
               "deskew_matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
               "pdf_width_pt": 595.3, "pdf_height_pt": 841.9},
  "elements": [
    {"id": 70000, "page": 7, "category": "text", "bbox": [120, 334, 901, 66],
     "polygon": [[120.0, 340.3], [1020.0, 334.0], [1021.0, 394.0], [121.0, 400.3]],
     "reading_order": -1, "render": "flow",
     "layout_score": null, "rec_score": 0.91, "logprob": null,
     "caption_id": null, "continues_from": null, "flags": [],
     "content": {"kind": "text", "text": "Kính gửi: ...",
                 "lines": [{"text": "Kính gửi: ...", "text_ocr": "Kinh gui: ...",
                            "polygon": [[120.0, 340.3], [1020.0, 334.0],
                                        [1020.2, 362.0], [120.2, 368.3]],
                            "bbox": [120, 334, 901, 35], "confidence": 0.91}]}}
  ]
}
```

`deskew_angle` khác 0 nên `polygon` phải là tứ giác nghiêng thật, không phải `null`; `bbox` là hình chữ nhật bao lồi của nó và luôn lớn hơn tứ giác (§4.5).

`content.kind` phân biệt bốn `*Content`. `schema: 1` để `page_from_dict` raise rõ ràng khi gặp bản cũ thay vì hỏng ngầm. `page_to_dict` không ghi `rec_score`/`logprob` khi cả hai `None` - đúng quy tắc bậc 3 "không điền 0" của bản staged Chandra (2026-08-07, đã thay) §4.2.

**`page_from_dict` phải dựng lại `tuple`, không để nguyên `list`.** JSON không phân biệt hai kiểu, còn `Element.bbox`, `TextLine.bbox`, `PageGeometry.deskew_matrix` (`core/geometry.py:34`) và các phần tử của `polygon` đều là tuple trong model. Không dựng lại thì `round_trips_page_through_serde_unchanged` so bằng `==` sẽ đỏ, và tệ hơn là `deskew_matrix` dạng list vẫn chạy qua `numpy` nên lỗi chỉ lộ ra ở chỗ so sánh chứ không ở chỗ dùng.

`images/` là chỗ lệch có chủ ý khỏi bản staged Chandra (2026-08-07, đã thay) §5 ("v1 không persist ảnh render"). Hai chỗ cần đúng ảnh đó chứ không phải ảnh dựng lại: review UI phải hiển thị đúng thứ máy đã đọc, và `finetune/cut_lines.py` cắt dòng trong khung deskew của chính ảnh đó (§4.5). Đường thay thế là dựng lại bằng cùng tham số preprocess, nhưng nó phụ thuộc vào deskew tái lập bit-exact.

`serialize/coco.py` giữ nguyên `file_name = "<source>#page=<N>"`. Ảnh trong `artifacts/` là ảnh sau preprocess, không phải trang nguồn, nên trỏ COCO vào đó sẽ sai ngữ nghĩa. Không sửa `serialize/`.

### 5.3 CLI

| Lệnh | Việc |
| --- | --- |
| `python -m orchestrate run --input ./dataset/lpbank` | Liệt kê PDF, chèn hàng `pending` cho từng trang, xử lý các trang `pending` |
| `python -m orchestrate merge <sha>` | Đọc `pages/*.json` qua `serde`, dựng `Document`, gán `reading_order` toàn tài liệu, gọi `core.serialize.write_document()` ra `output/` |
| `python -m orchestrate retry-failed` | Chạy lại trang `failed` có `attempt < 3` |
| `python -m orchestrate.review` | uvicorn cho review UI |

Song song bằng `multiprocessing.Pool`, mặc định `cpu_count() - 2` worker. Worker nhận `(path, page)` và làm đúng bốn việc:

1. `result = core.pipeline.run_page(path, page, cfg)`.
2. `result.error` khác `None` thì trả ngay `(page, "failed", None, result.error)` và dừng. Kiểm lỗi **trước** cổng QA: lúc đó `elements` rỗng và `verdict.min_score` không tồn tại, chấm ngưỡng trên tập rỗng là vô nghĩa.
3. `verdict = core.qa.gate(result.elements, cfg.qa_threshold)` - **đây là chỗ duy nhất cổng QA cắm vào pipeline.** `verdict.passed` thành `status = "done"`, ngược lại `"needs_review"`.
4. Ghi `images/p{n}.webp` từ `PageResult.image` và `pages/p{n}.json` qua `serde.page_to_dict`.
5. Trả về `(page, status, verdict.min_score, None)` - không trả `Element` qua ranh giới tiến trình, và không trả ảnh.

Mọi nhánh đều phải **trả về tiến trình cha**, kể cả nhánh lỗi: cha là bên duy nhất ghi SQLite, nên một worker thoát sớm mà không trả gì thì trang đó không bao giờ được ghi nhận là `failed` và sẽ mắc kẹt ở `running`.

**Mọi ghi SQLite đi qua tiến trình cha.** Đây không phải tối ưu sớm mà là tránh `database is locked`, thứ chắc chắn xảy ra nếu mỗi worker tự mở connection. Ghi file thì worker tự làm được vì mỗi worker sở hữu độc quyền một `(sha, version, page)`.

Khôi phục sau crash: lúc khởi động gọi `reset_stale_running(started_at)`, đặt lại `pending` cho mọi hàng `running` có `updated_at` cũ hơn thời điểm start.

### 5.4 Review UI

| Route | Việc |
| --- | --- |
| `GET /` | Danh sách `(doc_sha256, pipeline_version)`, số trang theo từng `status` |
| `GET /page/{sha}/{version}/{page}` | Ảnh trang bên trái; bên phải mỗi `TextLine` một `<input>`, nhóm theo `Element`, sắp theo `reading_order`; element `table` hiển thị HTML **chỉ đọc** |
| `POST /page/{sha}/{version}/{page}` | Ghi bản sửa, `status = reviewed` |
| `GET /image/{sha}/{version}/{page}` | Trả `images/p{n}.webp` |

Khi lưu: `TextLine.text` nhận bản đã sửa, `TextLine.text_ocr` **không đụng tới**, `TextContent.text` dựng lại từ `lines`, `rec_score` giữ nguyên giá trị OCR gốc (nó là tín hiệu của model, không phải của người sửa). Ghi qua `serde.page_to_dict`.

Bảng chỉ đọc: sửa `TableContent.html` bằng tay trong `<textarea>` là đường ngắn nhất tới HTML hỏng, và bảng không sinh ra mẫu huấn luyện nào (§6.2) nên sửa nó không nuôi vòng phản hồi.

Bản sửa **không** cần cơ chế vô hiệu hoá khi config đổi, vì `pipeline_version` (§5.1) bao cả hash của `Config`: đổi bất kỳ tham số nào là một thư mục artifacts khác và một bộ hàng `page_state` khác, nên bản sửa cũ đơn giản là không được mang sang.

Mặt trái đã biết và **cố ý chấp nhận**: hash quét cả những trường không đổi pixel, nên đổi `qa_threshold` hay đổi `outputs` từ `["markdown", "coco"]` thành `["markdown"]` cũng làm mất hết bản sửa, dù `outputs` chỉ được đọc ở stage 6 mà `orchestrate run` không bao giờ chạy (chỉ `merge` chạy). Đây là vô hiệu hoá thừa, không phải sót; đánh đổi lấy một quy tắc duy nhất "config đổi là chạy lại" thay vì một danh sách trường nào tính trường nào không.

Dependency mới: `fastapi`, `uvicorn`, `jinja2`, `python-multipart` (FastAPI cần nó cho form POST, thiếu là lỗi ngay lúc import route).

**Ngoài phạm vi, ghi rõ để không tưởng là sót:** không xử lý hai người sửa cùng một trang; không có trạng thái "vẫn sai, cần xem lại".

## 6 · Zone 3 - fine-tune

### 6.1 Hai cổng chặn, kiểm trước khi cắt dòng nào

`finetune/guards.py` chạy đầu tiên trong mọi lệnh của package:

| Điều kiện | Cách kiểm | Nếu trượt |
| --- | --- | --- |
| Binary training có mặt | `shutil.which("lstmtraining")` và `which("combine_tessdata")` | Dừng, in hướng dẫn cài |
| `finetune/tessdata/vie.traineddata` tồn tại và là bản `best` | Chạy `combine_tessdata -l <file>`, output **không** được chứa `int_mode=1` | Dừng, in lệnh tải từ `tesseract-ocr/tessdata_best` |

**`finetune/tessdata/` là thư mục tessdata riêng của luồng fine-tune**, không dùng `/opt/homebrew/share/tessdata`. Nó chứa:

```
finetune/tessdata/vie.traineddata        bản best, người dùng tải về (gitignore)
finetune/tessdata/osd.traineddata        copy từ tessdata hệ thống
finetune/tessdata/vie_lpbank.traineddata sinh ra bởi train.py
```

Mọi lệnh `tesseract` và `lstmtraining` trong package trỏ vào thư mục này bằng đường dẫn tuyệt đối (`--tessdata-dir` cho `tesseract`, `--traineddata` cho `lstmtraining`), không dựa vào biến môi trường. Không có thư mục riêng thì §6.5 sẽ lặng lẽ nạp lại đúng bản `int_mode` mà cổng chặn vừa từ chối.

`osd.traineddata` phải có mặt vì `core/preprocess.py` gọi `pytesseract.image_to_osd` cho bước `orientation`; thiếu nó thì bước OCR lại ở §6.6 raise `PreprocessError`.

Cổng chặn kiểm **đúng tên `vie.traineddata`**, không quét cả thư mục. `vie_lpbank.traineddata` do `train.py` ghi ra nằm ngay cạnh và là sản phẩm của chính luồng này; quét cả thư mục sẽ khiến lần chạy thứ hai tự chặn mình.

**Kiểm chứng trên máy hiện tại (2026-08-15):** `lstmtraining`, `text2image`, `unicharset_extractor`, `combine_tessdata` đã có ở `/opt/homebrew/bin`, tesseract 5.5.3. `/opt/homebrew/share/tessdata/vie.traineddata` trỏ vào `tesseract-lang` 4.1.0 và `combine_tessdata -l` in `int_mode=1`, tức bản `tessdata_fast`. Cổng chặn thứ hai **chắc chắn trượt ở lần chạy đầu**; đó là hành vi đúng.

### 6.2 Cắt dòng

`cut_lines.py` đọc `artifacts/<sha>/<version>/pages/p{n}.json` và `images/p{n}.webp`. Với mỗi `TextLine` của mỗi element `text`: `bounding_box(from_canonical(line.polygon, geom))` cho hộp cắt trong khung deskew, crop, ghi `finetune/data/<sha>/p0007_l003.png`.

Đi qua `polygon` chứ không qua `bbox`, và thu về hình chữ nhật **đúng một lần** ở cuối. Lý do ở §4.4 và §4.5: đi ngược bằng `bbox` làm khung cắt nở theo góc nghiêng và ảnh dòng dính mực dòng bên cạnh. `from_canonical` cũng nhận danh sách điểm chứ không nhận 4-tuple (`core/geometry.py:75`).

Chỉ cắt từ element `text`. Ô bảng đi qua `recognize_text()` không có `Word` nên không có `TextLine` và không có bbox mức dòng.

Bỏ dòng có chiều cao dưới 8 px hoặc chiều rộng dưới 16 px: `lstmtraining` không học được gì từ chúng và chúng thường là nhiễu của detector.

### 6.3 Gióng nhãn - phần khó thật sự

`align.py` không dùng model nào. Đầu vào: các `TextLine` của một trang, và chuỗi ground truth của **đúng trang đó**.

1. **Tách trang.** Cắt GT theo marker `<!-- page: N -->`, lấy đoạn của đúng trang đang xử lý.
2. **Bỏ hẳn khối bảng, trên markup còn nguyên.** Xoá mọi đoạn từ `<table` tới `</table>` **trước** khi bóc thẻ - làm ngược lại thì bước bóc thẻ đã ăn mất cặp `<table>` và không còn gì để tìm. Bỏ hẳn nội dung chứ không chỉ bóc thẻ: §4.2 đã gỡ mọi block text nằm trong vùng bảng nên phía OCR không có nội dung bảng, giữ nó ở phía GT sẽ làm lệch offset của mọi dòng sau đó và bộ lọc 0,7 loại cả những dòng tốt. `ground_truth/lpbank/1202.PGV.2026(1).md` mở đầu trang 1 bằng nguyên một khối `<table><tr><th>...`, và `04-evaluation.md` cho biết markup bảng là một yêu cầu ground truth có chủ ý.
3. **Bóc thẻ còn lại, bóc dấu đầu dòng markdown, chuẩn hoá NFC.** Đúng ba việc đó, không hơn.

   Viết một hàm riêng trong `align.py`, **không** dùng `evaluate/normalize.strict()`, vì hai lý do độc lập: hàm bóc thẻ không tồn tại tách rời (`evaluate/normalize.py` chỉ có `strict()` và `tone_blind()`, phần `re.sub` bóc thẻ nằm kẹp giữa các bước khác), và bản thân `strict()` **làm hỏng nhãn** - nó viết lại vị trí dấu `hoà -> hòa`. Phép đó đúng khi chấm điểm vì cả hai phía cùng bị áp, và sai khi làm `.gt.txt`: nhãn phải là đúng chuỗi glyph in trên ảnh, dạy LSTM xuất `hòa` cho pixel đọc ra `hoà` là huấn luyện theo người chép chứ không theo trang giấy.

   Nguyên tắc "đúng glyph in trên giấy" cắt cả hai chiều, và chiều còn lại là dấu đầu dòng. GT mang **5 tới 35 dòng bullet mỗi file** trên cả bảy file, trộn `-` và `*` ở các mức lồng khác nhau trong cùng một tài liệu (`ground_truth/lpbank/14190.2025.TB-LPBank.QTRR.md`). `*` là quy ước markdown của người chép, không phải dấu sao in trên trang. Nên **bóc dấu dẫn đầu dòng `- `, `* `, `+ `**, và **giữ** số thứ tự in thật như `1.`, `a)`.

   Cách hỏng nếu bỏ qua bước này bất đối xứng và đáng nói trước: trên dòng bullet dài, dấu chiếm dưới 2% chuỗi nên bộ lọc 0,7 cho qua và nhãn mang theo một `*` không có thật; trên dòng ngắn như `- HĐQT;` thì dấu chiếm một phần tư chuỗi và dòng bị loại thẳng. Tức là mất dòng ngắn và nhiễm độc dòng dài cùng lúc. `04-evaluation.md` không ràng buộc gì về bullet nên không có bảo đảm nào để dựa vào.
4. **Gióng.** Nối các `TextLine` của trang theo `reading_order` thành một chuỗi, nhớ offset biên từng dòng. `rapidfuzz.distance.Levenshtein.opcodes(chuoi_ocr, chuoi_gt)` cho dãy phép biến đổi; backtrace ra đoạn GT ứng với từng biên dòng.
5. **Lọc.** Dòng có similarity dưới 0,7 thì loại, ghi lý do vào `finetune/data/rejected.log`. Nhãn gióng sai độc hơn là không có nhãn.

`rapidfuzz` đã nằm trong `requirements.txt` cho `evaluate/`, không thêm dependency. `evaluate/` không bị sửa gì.

**Nguồn GT và điều kiện tiên quyết:** `ground_truth/lpbank/*.md`, hiện có **7 file** trên đĩa (`04-evaluation.md` liệt kê 6; file thứ bảy `CV 261 CĐK&BTNN...` được thêm sau khi viết tài liệu đó). Cả `ground_truth/` lẫn `dataset/` đều nằm trong `.gitignore`, nên đây là điều kiện **cục bộ theo máy**: một bản clone mới không có file nào và `align.py` sẽ sinh ra tập train rỗng. `guards.py` phải đếm số file GS khớp stem và dừng với thông báo rõ khi bằng 0.

Tài liệu nào không có file GT cùng stem thì bỏ qua, ghi vào log, không báo lỗi. Việc lập chỉ mục thư mục GT theo stem dùng lại `evaluate.ground_truth.discover_text()` (`evaluate/ground_truth.py:44`, đã có và đã raise khi trùng stem) thay vì viết bản thứ hai; `finetune -> evaluate` là chiều import đã được §3 cho phép.

### 6.4 Suy giảm ảnh

`degrade.py` **mặc định tắt**, bật bằng `--degrade`. Sinh thêm bản blur / thêm nhiễu Gauss / nén JPEG chất lượng thấp của cùng một dòng, dùng chung một `.gt.txt`.

Lý do phải nói trước: PDF LPBank là digital-born, Tesseract đọc gần đúng, nên tập train sẽ ít mẫu lỗi và `.traineddata` sinh ra gần như trùng model gốc. Đó là kết quả đúng của dữ liệu, không phải code hỏng.

### 6.5 Sinh `.lstmf` và train

`lstmf.py` chạy cho từng cặp:

```
tesseract <line>.png <line> -l vie --tessdata-dir finetune/tessdata --psm 13 lstm.train
```

`-l vie` và `--tessdata-dir` đều **bắt buộc**. Thiếu `-l` thì Tesseract nạp `eng`, và `.lstmf` mã hoá `.gt.txt` theo unicharset của model được nạp: ký tự tiếng Việt không có trong unicharset `eng` nên mọi dòng hỏng lúc mã hoá. Cộng với quy tắc "dòng nào không sinh được `.lstmf` thì bỏ", run sẽ lặng lẽ cho ra `list.train` rỗng. Thiếu `--tessdata-dir` thì nó nạp bản `int_mode` của hệ thống mà §6.1 vừa từ chối.

Sau đó ghi `finetune/data/list.train` (đường dẫn tuyệt đối tới từng `.lstmf`). `lstmf.py` phải **dừng với lỗi** khi `list.train` rỗng hoặc dưới 50 dòng, thay vì để `lstmtraining` chạy trên tập rỗng.

`train.py` là wrapper gọi binary, không có logic học:

```
combine_tessdata -e finetune/tessdata/vie.traineddata finetune/work/vie.lstm

lstmtraining --continue_from finetune/work/vie.lstm \
             --traineddata finetune/tessdata/vie.traineddata \
             --train_listfile finetune/data/list.train \
             --model_output finetune/work/vie_lpbank --max_iterations 3000

lstmtraining --stop_training \
             --continue_from finetune/work/vie_lpbank_checkpoint \
             --traineddata finetune/tessdata/vie.traineddata \
             --model_output finetune/tessdata/vie_lpbank.traineddata
```

Chạy trên CPU, không cần GPU. `--max_iterations 3000` là điểm khởi đầu, không phải con số đã đo.

### 6.6 Đóng vòng

```
config.yaml: langs: [vie_lpbank]
TESSDATA_PREFIX=finetune/tessdata python -m orchestrate run --input ./dataset/lpbank
python -m orchestrate merge <sha>
python -m evaluate.run
```

`TESSDATA_PREFIX` trỏ vào `finetune/tessdata/`, thư mục đã chứa cả `vie.traineddata` (best), `osd.traineddata` và `vie_lpbank.traineddata` theo §6.1 - nên `orientation` vẫn chạy và fallback về `langs: [vie]` vẫn hợp lệ.

`langs` đổi làm `pipeline_version` đổi, nên mọi trang trở lại `pending` và được OCR lại vào một thư mục artifacts mới, đứng cạnh kết quả cũ để so.

Số CER in ra để xem, không phải cổng chặn theo tiêu chí đã chốt ở §1.

## 7 · Config

```python
Config: dpi=300, preprocess_steps=["orientation", "deskew", "denoise"],
        layout="tesseract", table="cv", engine="tesseract", langs=["vie"],
        outputs=["markdown", "coco"], qa_threshold=0.75,
        input_dir="./dataset/lpbank", output_dir="./output",
        ground_truth_dir="./ground_truth/lpbank", artifacts_dir="./artifacts"
```

Thay đổi so với `core/config.py` hiện tại: bỏ `mode`, `postprocess`, `lang`, `PIPELINES`, `VALID_MODES`; thêm `dpi`, `layout`, `table`, `outputs`, `qa_threshold`, `artifacts_dir`, `ground_truth_dir`; `VALID_STEPS` sửa thành `{"grayscale", "binarize", "orientation", "deskew", "denoise"}` - hiện nó thiếu `orientation` và `denoise` dù `core/preprocess.py` đã cài đặt cả hai.

**`config.yaml` trên đĩa cũng phải sửa, không chỉ `config.py`.** File hiện tại giữ `engine: chandra` (chưa bao giờ nằm trong `VALID_ENGINES`), `langs: [vie, eng]`, `preprocess_steps: [grayscale, deskew, binarize]`, `output_dir: ./output/low_quality_handwritten`, `ground_truth_dir: ./ground_truth/handwritten`. Không sửa thì lần chạy `main.py` đầu tiên sau phase 1 raise `ConfigError` ngay ở dòng đọc config. Giá trị mới: `engine: tesseract`, `langs: [vie]`, `preprocess_steps: [orientation, deskew, denoise]`, `input_dir: ./dataset/lpbank`, `output_dir: ./output`, `ground_truth_dir: ./ground_truth/lpbank`, cộng `layout`, `table`, `dpi`, `qa_threshold`, `artifacts_dir`.

**`ground_truth_dir` phải nằm trong `Config` dù `core` không dùng nó.** `evaluate/config.py` đọc cùng file `config.yaml` và bắt buộc có `engine`, `output_dir`, `ground_truth_dir`; `core.config._merge` thì raise với mọi key ngoài `Config.__dataclass_fields__`. Hôm nay `config.load('config.yaml')` đã raise `ConfigError: unknown config keys: ['ground_truth_dir']`. Hai loader đọc chung một file nên tập key phải là hợp của hai bên. `evaluate/` không sửa gì.

`binarize` ra khỏi mặc định vì Tesseract đã tự nhị phân hoá bằng Otsu bên trong; thêm một lớp nữa thường chỉ mất thông tin. Bước vẫn còn trong `preprocess.py`, chỉ không bật sẵn.

`orientation` **vào** mặc định. bản staged Chandra cũ loại nó vì engine mặc định lúc đó là Paddle và `image_to_osd` cần binary Tesseract; ở đây Tesseract là engine chính nên lý do đó không còn.

`validate()` thêm hai luật: `layout == "tesseract"` bắt buộc `engine == "tesseract"` (§4.2); `qa_threshold` phải trong `[0, 1]`.

## 8 · Xử lý lỗi

Nguyên tắc của `core/` giữ nguyên theo bản staged Chandra (2026-08-07, đã thay) §6: không bao giờ mất geometry, nội dung hỏng được nhưng vị trí thì không.

| Tầng | Hành vi |
| --- | --- |
| Khởi tạo provider | Fail fast, `ProviderError`, trước khi chạm file nào |
| Load | Lỗi thì hỏng cả file |
| Trang trong `core` | `run_page` trả `PageError`, không ném; trang khác vẫn xử lý và xuất |
| Recognizer lỗi | Giữ element đủ geometry, `content=None`, `flags=["recognize_failed"]` |
| Provider bị tắt (`table="none"`) | Giữ element đủ geometry, `content=None`, `flags=["provider_disabled"]`, không phải lỗi |
| `validate_page` | Chỉ set `flags` (`invalid_html`, `cell_count_mismatch`), không đụng `rec_score`. Không bao giờ ném |
| `validate_document` | Raise `DocumentError` khi bất biến cấu trúc vỡ (§4.7). Trong `run_document` là hỏng cả tài liệu, tức `main.py` thoát với lỗi; trong `orchestrate merge` là hỏng lần merge đó, `page_state` không bị đụng nên các trang vẫn `done` và merge lại được sau khi sửa code. Cả hai đều đúng: đây là bug lắp ráp, không phải khiếm khuyết của trang giấy |
| `serde.page_from_dict` gặp `schema` lạ | Raise `DocumentError` kèm số schema, không đoán |
| `orchestrate` - trang lỗi | `status=failed` + `error` + `attempt += 1`, worker khác chạy tiếp |
| `orchestrate` - crash tiến trình | `done` giữ nguyên; `running` cũ hơn thời điểm start trở lại `pending` |
| `finetune` - cổng chặn trượt | Dừng ngay, chưa cắt dòng nào |
| `finetune` - một dòng gióng hỏng | Bỏ dòng, ghi `rejected.log`, không dừng run |
| `finetune` - `list.train` dưới 50 dòng | Dừng với lỗi, không gọi `lstmtraining` |

## 9 · Test

### 9.1 Test hiện có

| File | Việc |
| --- | --- |
| `tests/test_finetune.py` | **Xoá** - `import chandra.prompts`, không tồn tại sau khi bỏ Chandra |
| `tests/test_config.py` | Viết lại - đang import `PIPELINES` |
| `tests/test_pipeline.py` | Viết lại theo `run_page` / `run_document` |
| `tests/test_document_model.py` | Bổ sung cho `TextLine` / `TextContent` mới; phần cũ giữ nguyên |
| `tests/test_loader.py` | Bổ sung cho `load_page`; phần cũ giữ nguyên |
| `test_engine` `test_paddle` `test_easyocr` `test_tables` `test_geometry` `test_serialize` `test_preprocess` `test_metrics_*` `test_evaluate` `test_matching` `test_normalize` `test_ground_truth` `test_table_extract` | Không đụng |

`test_serialize` và `test_document_model` dựng `TextContent` bằng một tham số vị trí ở 14 chỗ. Chúng chỉ ở lại cột "không đụng" nhờ `lines` có `default_factory` (§4.4). Nếu lúc implement thấy hai file này đỏ, **lỗi nằm ở `model.py`, không nằm ở test** - không sửa test để suite xanh.

### 9.2 Test mới

Mỗi test nhắm đúng một chỗ đã biết là dễ sai:

**Loader** (phase 1, nhưng là hai hàm mới nên tách riêng)

- `renders_only_the_requested_page` - `load_page`, không render cả PDF
- `counts_pages_without_rendering_them` - `loader.page_count`

**Stage 3-5**

- `drops_text_block_contained_in_table_region` - tỉ lệ bao chứa, chỗ sinh ra ô bảng lặp hai lần nếu sai
- `keeps_small_text_block_barely_touching_table` - biên của ngưỡng 0,7
- `rejects_config_pairing_tesseract_layout_with_paddle_engine`
- `builds_table_html_with_rowspan_from_merged_cells`
- `converts_layout_box_to_canonical_frame_once` - khoá điểm chuyển duy nhất ở §4.5
- `divides_word_confidence_by_hundred_once` - điểm chia duy nhất ở §4.3
- `takes_table_dimensions_from_detector_not_from_cells`
- `assigns_reading_order_column_first_on_two_column_page`
- `raises_when_page_exceeds_element_limit` - qua `element_id()`
- `leaves_reading_order_unset_from_run_page`
- `validates_page_without_requiring_reading_order` - hai nửa `validate` ở §4.7
- `raises_when_reading_order_has_duplicates` - bất biến cấu trúc raise chứ không gắn cờ
- `builds_text_content_with_one_positional_argument` - khoá `default_factory` của `lines` (§4.4)
- `writes_output_under_directory_named_after_source_stem` - §3.4

**QA và serde**

- `flags_page_when_any_element_below_threshold`
- `passes_page_with_only_table_elements` - element bậc 3 không bị gate, hành vi có chủ ý
- `omits_rec_score_from_json_when_signal_absent`
- `round_trips_page_through_serde_unchanged`
- `raises_on_unknown_page_schema_version`

**Orchestrate**

- `skips_pages_already_done_on_rerun`
- `reprocesses_pages_when_pipeline_version_changes` - test khoá vòng phản hồi
- `changes_pipeline_version_when_dpi_changes` - phần hash của §5.1
- `maps_qa_verdict_to_needs_review_status` - chỗ cổng QA cắm vào, §5.3
- `returns_failed_status_without_calling_qa_gate` - thứ tự bước 2 trước bước 3, §5.3
- `resets_in_flight_pages_to_pending_after_crash`
- `skips_failed_page_after_max_attempts`
- `keeps_original_text_when_reviewer_saves_correction` - `text_ocr` không bị ghi đè

**Finetune**

- `raises_when_traineddata_is_int_mode`
- `ignores_output_model_when_checking_traineddata` - cổng chặn kiểm theo tên, §6.1
- `removes_table_block_before_stripping_tags` - thứ tự bước 2 trước bước 3, §6.3
- `preserves_tone_placement_in_label` - không dùng `normalize.strict()`
- `strips_markdown_bullet_marker_but_keeps_printed_numbering`
- `aligns_gt_line_by_line_from_page_text`
- `rejects_line_below_similarity_threshold`
- `crops_line_from_polygon_without_inflating_height` - vòng đi-về qua `polygon`, §4.4
- `raises_when_train_list_is_empty`
- `skips_document_without_matching_ground_truth`

Test dùng module giả bằng `monkeypatch.setitem(sys.modules, ...)` theo đúng pattern `tests/test_paddle.py`, và `monkeypatch` cho `subprocess.run` ở phần `finetune`, để CI không cần binary thật.

### 9.3 `requirements.txt`

Đang lệch với code: `core/loader.py` import `pypdfium2` nhưng file chỉ liệt kê `pdf2image` (của `pipeline.py` cũ sắp xoá).

- Thêm: `pypdfium2`, `fastapi`, `uvicorn`, `jinja2`, `python-multipart`
- Bỏ: `pdf2image`, `openrouter`, `python-dotenv` - consumer duy nhất của hai cái sau là `core/postprocess.py`, bị xoá ở quyết định 5. Zone 2 sẽ thêm lại khi cần, mang theo dependency cho một package chưa viết là nợ không có lý do
- Giữ: `pytesseract`, `paddleocr`, `easyocr`, `Pillow`, `numpy`, `opencv-python`, `PyYAML`, `rapidfuzz`, `apted`, `lxml`, `python-docx`

## 10 · Thứ tự triển khai - ba plan, không phải một

Ba phase dưới đây là **ba hệ con độc lập**: một bản viết lại tầng stage trong `core/`, một orchestrator có trạng thái kèm web UI, và một wrapper cho toolchain training bên ngoài. Mỗi phase có tiêu chí nghiệm thu riêng và không chia sẻ interface nào ngoài `run_page` và `serde`. Viết **ba plan riêng**, chạy xong plan trước rồi mới viết plan sau - hình dạng `TextLine` và `pages/p{n}.json` phải chạy thật ở phase 1 trước khi phase 2 xây lên trên.

| Phase | Nội dung | Nghiệm thu |
| --- | --- | --- |
| 1 | `document/model.py` (`TextLine`) + `document/serde.py` + `layout/` + `recognize/` + `document/` + `pipeline.py` + `config.py` + `main.py`, xoá 3 file legacy | `python main.py <pdf>` ra `.md` + `.coco.json`; chạy trên 7 PDF LPBank có ground truth và `python -m evaluate.run` in ra số CER, bất kể số đó là bao nhiêu |
| 2 | `core/qa.py` + `orchestrate/` | Giết tiến trình giữa chừng rồi chạy lại: số trang xử lý lần hai đúng bằng số trang chưa xong. Sửa một dòng trên web, đọc lại `pages/p{n}.json` thấy `text` đổi và `text_ocr` không đổi |
| 3 | `finetune/` viết lại, xoá 2 file Chandra | `finetune/tessdata/vie_lpbank.traineddata` tồn tại; `tesseract --list-langs --tessdata-dir finetune/tessdata` thấy nó; chạy lại `orchestrate run` với `langs: [vie_lpbank]` sinh ra thư mục artifacts thứ hai |

## 11 · Hạn chế đã biết

1. COCO chỉ có 2 trong 11 category DocLayNet. `picture`, `formula`, `title`, `section-header` không bao giờ xuất hiện.
2. Bảng ở bậc 3 nên QA gating không chặn được. Bảng sai đi thẳng ra kết quả.
3. Chỉ nhận được bảng kẻ khung. `core/tables.py` dò theo đường kẻ, bảng không kẻ khung thành các block `text` rời.
4. Fine-tune LSTM chỉ vá tầng nhận chữ. Layout analysis của Tesseract là thuật toán viết tay, không học được; IoU layout và TEDS bảng đứng yên theo thiết kế.
5. `vie.traineddata` bản `tessdata_best` phải tải tay vào `finetune/tessdata/` ở lần chạy đầu.
6. Nội dung bảng bị loại khỏi cả hai phía khi gióng nhãn (§6.3), nên không dòng nào trong bảng trở thành mẫu huấn luyện.
7. `degrade` tắt mặc định nên `.traineddata` đầu tiên sẽ gần trùng model gốc.
8. Không có `.html`, không có searchable PDF, không có công thức.
9. `qa_threshold = 0.75` và `--max_iterations 3000` là số đặt để luồng chạy, chưa đo trên corpus thật.
10. Review UI không xử lý đồng thời, không có trạng thái "vẫn sai" (§5.4).

## 12 · Ngoài phạm vi

- Zone 2 (trích xuất thông tin ra JSON) - spec riêng, viết sau khi phase 1 chốt hình dạng `Document`.
- Searchable PDF - PyMuPDF là AGPL-3.0, và không cần cho mục tiêu thử luồng.
- Serialize `.html` - zone 2 đọc thẳng `Document` qua `serde`, không cần parse HTML ngược lại.
- Hàng đợi phân tán (Redis, Celery, SQS) - `multiprocessing.Pool` đủ cho một máy.
- Đọc thẳng text layer PDF không-scan như một đường OCR thứ hai.
- Ngưỡng QA đo thật và chốt theo số liệu.
- Gate bảng bằng cách đọc từng ô qua `recognize_words()`.
