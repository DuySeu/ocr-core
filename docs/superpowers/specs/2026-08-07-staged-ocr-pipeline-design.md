# Refactor `ocr-core` — pipeline OCR 6 stage, một lần chạy hai output

Ngày: 2026-08-07
Trạng thái: Design — chờ duyệt để lập kế hoạch implement
Phạm vi: `core/` trên một máy. **Không** bao gồm orchestration 2M trang (§2.5 của tài liệu yêu cầu).
Tài liệu nguồn:
[2026-08-06-ocr-2m-pages-requirements-analysis.md](../../2026-08-06-ocr-2m-pages-requirements-analysis.md) ·
[2026-08-07-chandra-pipeline-spec.md](../../2026-08-07-chandra-pipeline-spec.md)

Mọi tham chiếu dạng `§x.y` trong tài liệu này trỏ tới **tài liệu yêu cầu 2026-08-06**, trừ khi ghi rõ khác.

---

## 1 · Vấn đề

`core/extract.py:17` rẽ nhánh `mode: data | markdown` ngay từ tầng extract. Nhánh `markdown`
gọi `engine.recognize_text()` trên từng băng ảnh và chỉ giữ lại chuỗi text — **bbox bị vứt đi tại chỗ**.
Nhánh `data` giữ bbox nhưng không có khái niệm bảng, hình, công thức hay thứ tự đọc.

Hệ quả: không thể sinh `.md` và `.json` COCO từ **cùng một lần OCR**. §3.1 gọi đây là lỗi kiến trúc gốc.

Bốn thiếu sót đi kèm:

| Thiếu | Vị trí hiện tại |
| --- | --- |
| Không có tầng phát hiện & gán nhãn đối tượng | Chỉ có `core/tables.py:81`, thuần hình học OpenCV, chỉ nhận bảng **kẻ khung** |
| Không có công thức, không có crop hình figure | Không tồn tại |
| Không có thứ tự đọc thật | `core/extract.py:45` sort theo `y` — vỡ ở layout nhiều cột |
| Không có hệ toạ độ trang | Không ghi `width/height/dpi` ở đâu; bbox nằm trong không gian ảnh **đã deskew**, không map ngược được về PDF. §2.1 gọi đây là **blocker của COCO** |

## 2 · Quyết định

Dựng lại `core/` thành **6 stage, mỗi stage một interface**, và một provider được phép cài đặt nhiều stage.

Đây là điểm dung hoà có ý thức giữa hai tài liệu nguồn:
`2026-08-07-chandra-pipeline-spec.md` chốt đi Chandra một pass và **bác bỏ** việc tự dựng tầng layout
cùng các recognizer chuyên biệt. Tài liệu này giữ lại **kiến trúc** phân tầng đó, nhưng ở dạng interface
rỗng — nên một provider one-pass (Chandra, PaddleOCR-VL) vẫn cài được nhiều stage cùng lúc mà không phải
sửa pipeline. Đúng tinh thần §5.4 "giữ cửa mở cho VLM bằng interface, không phải bằng code thêm".

Cái được: đường CPU chạy được ngay hôm nay để đo CER trên `evaluate/dataset/`; và text recognizer
thay riêng được — điều kiện để nâng cấp lên STT 1 ⭐ (PP-StructureV3 + VietOCR), lựa chọn dựa-trên-bằng-chứng
duy nhất trong §1.3.2.

Cái mất: đường classic phải **tự XY-cut** thứ tự đọc. Chấp nhận, xem §9 điểm 2.

### Phạm vi v1

| Hạng mục | v1 |
| --- | --- |
| Đường classic CPU, đủ 4 nhãn text / table / picture / formula | **Chạy thật, end-to-end** |
| Adapter Chandra / PaddleOCR-VL | Chỉ có interface. **Không** viết trong v1 |
| Đọc thẳng text layer của PDF không-scan (§2.2) | **Ngoài phạm vi v1** — xem §2.1 dưới đây |
| Orchestration: page job, checkpoint, DLQ, dedup, backpressure (§2.5) | **Ngoài phạm vi** — sub-project riêng |
| QA gating & hàng đợi review (§3.7) | Chỉ sinh `flags` trên element. Tầng gating riêng nằm ngoài phạm vi |
| Post-processing sửa text bằng LLM | **Xoá hẳn** — xem §8 |

### 2.1 Vì sao bỏ text-layer shortcut khỏi v1

§2.2 đề xuất phát hiện trang PDF đã có text layer rồi đọc thẳng text + bbox, bỏ qua OCR — "phần miễn phí"
của corpus. Nó bị loại khỏi v1 vì tạo ra **một đường thứ hai, hình dạng khác**, đi xuyên qua stage 3–6:
trang đó không qua detector nên không có `layout_score`, không có category thật, và rơi vào bậc 3 của §5.2.
Định nghĩa đầy đủ cho nó tốn gần bằng một stage nữa, trong khi giá trị của nó là **tiết kiệm GPU ở quy mô
2M trang** — đúng phạm vi của sub-project orchestration, không phải của v1. Ghi lại ở đây để không bị quên.

---

## 3 · Luồng

```
run_document(path, cfg) -> Document

 1 Load        loader.py       PDF/ảnh -> PageImage[] + PageGeometry (pypdfium2, 300 DPI)
 2 Preprocess  preprocess.py   orientation -> deskew (GIỮ ma trận affine) -> denoise
 3 Layout      layout/         LayoutDetector.detect(page) -> LayoutBox[]
                               (category thuộc 11 class DocLayNet, layout_score, bbox)
 4 Recognize   recognize/      Router định tuyến theo category:
                 text · title · section-header · list-item · caption ·
                 footnote · page-header · page-footer  -> TextRecognizer    -> TextContent
                 table                                 -> TableRecognizer   -> TableContent
                 formula                               -> FormulaRecognizer -> FormulaContent
                 picture                               -> FigureExtractor   -> FigureContent
 5 Assemble    document/       link caption -> link bảng tràn trang -> đặt render ->
                               reading order -> gán id -> validate -> Document
 6 Serialize   serialize/      markdown.py -> .md    +    coco.py -> .coco.json
```

Stage 6 đọc **cùng một** `Document`. Một lần OCR, hai output.

Ánh xạ sang yêu cầu gốc: tiền xử lý = stage 2 · detect object + labeling = stage 3 ·
handle OCR theo từng label = stage 4 · transfer output thành định dạng tương ứng = các
`*Content` ở stage 4 · reorder = stage 5 · xuất `.md`/`.json` COCO = stage 6.

---

## 4 · Cây module

```
core/
  __init__.py        API công khai: run_document, run_to_files, Document
  config.py          Config (BỎ mode/postprocess, THÊM dpi/layout/table/formula/outputs) + validate + PIPELINES
  pipeline.py        điều phối 6 stage; tạo output/<stem>/; best-effort theo trang
  loader.py          pypdfium2: PDF/ảnh -> PageImage + PageGeometry
  geometry.py        PageGeometry · to_canonical/from_canonical · px_to_pdf_point        (§2.1)
  preprocess.py      registry STEPS: orientation · deskew · denoise · grayscale · binarize
  layout/
    base.py          LayoutDetector (ABC) · LayoutBox · DOCLAYNET_CLASSES (11 hằng)
    ppdoclayout.py   PP-DocLayout_plus-L; bảng map class -> 11; class lạ -> "text" + log
    whole_page.py    fallback "none": mỗi trang = một element `text` phủ cả trang
    __init__.py      registry get_layout_detector()
  recognize/
    base.py          TextRecognizer · TableRecognizer · FormulaRecognizer · FigureExtractor (ABC)
                     (các *Content được import từ document/model.py, KHÔNG định nghĩa ở đây)
    router.py        category -> recognizer; bắt lỗi từng element (§7)
    text.py          gọi engines/.recognize_words(); reflow dòng ngắt mềm; tính score
    table_pp.py      PP-TableRecognitionV2 -> HTML + cell_box_list
    table_cv.py      core/tables.py -> HTML có rowspan/colspan   (fallback, không tải model)
    formula_pp.py    PP-FormulaNet-M -> LaTeX
    figure.py        crop bbox + padding 2% -> ghi WebP vào <out_dir>/images/
    __init__.py      registry
  engines/           KHÔNG SỬA — tesseract.py · paddle.py · easyocr.py · base.py
  tables.py          GIỮ — phát hiện lưới ô thuần OpenCV; consumer đổi sang recognize/table_cv.py
  document/
    model.py         Element · Document · PageError · LogProb · các *Content · FLAGS
                     (import PageGeometry từ geometry.py, không định nghĩa lại)
    assemble.py      link caption -> link bảng tràn trang -> đặt render ->
                     gọi reading_order -> gán Element.id -> gọi validate -> dựng Document
    reading_order.py XY-cut đệ quy + rule văn bản hành chính VN (thuần sắp xếp)
    link.py          liên kết caption↔picture/table; liên kết bảng tràn trang (thuần tìm quan hệ)
    validate.py      lxml cho HTML bảng; pylatexenc cho LaTeX; đối chiếu số ô (thuần gắn flag)
  serialize/
    __init__.py      write_document(doc, out_dir, outputs) — điểm vào duy nhất của stage 6
    markdown.py      Element[] -> .md, kèm anchor <!-- ann:N -->
    coco.py          -> COCO 11 category + field mở rộng
tests/
```

**Xoá:** `core/extract.py` · `core/postprocess.py` · `pipeline.to_markdown()` ·
`Config.mode` · `Config.postprocess` · `VALID_MODES` · `.env.example`.

`extract._prose_bands()` biến mất cùng `extract.py`: LayoutDetector thay thế nó hoàn toàn.
`extract._split_paragraphs()` chuyển sang `recognize/text.py` — reflow dòng ngắt mềm vẫn cần
cho mọi element chứa văn xuôi.

### 4.1 Bốn ranh giới dễ nhầm, chốt ở đây

**Các `*Content` chỉ có một chủ sở hữu: `document/model.py`.** `recognize/base.py` import chúng.
Chiều ngược lại không tồn tại — `document/` không được import `recognize/`. Nếu để `recognize/base.py`
định nghĩa chúng thì `Element.content` phải import ngược lên và thành vòng lặp import.

**`recognize/text.py` gọi `recognize_words()`, không gọi `recognize_text()`.** Đây là điều kiện
để có tín hiệu bất định: `OCREngine.recognize_text()` (`core/engines/base.py:28`) trả về `str` trần,
không mang confidence. `recognize_words()` trả `Word` có `confidence`, nên `text.py` gom word thành
dòng theo `line_key`, reflow, rồi lấy `mean(w.confidence) / 100` làm `Element.rec_score`.
`recognize_text(psm=6)` vẫn còn trong ABC vì `table_cv.py` dùng nó để OCR từng ô — hệ quả là ô bảng
của đường `cv` **không có** tín hiệu bất định, tức bậc 3. Ghi rõ, không giấu.

**Ai tạo thư mục và ai đặt tên file ảnh.** `pipeline.run_to_files()` tạo `output/<stem>/images/`
**trước** stage 4 và truyền đường dẫn đó vào `FigureExtractor`. File ảnh đặt tên
`p{page:04d}_{sha1(crop_bytes)[:12]}.webp` — theo **hash nội dung**, không theo `Element.id`,
vì id mãi tới stage 5 mới có. `serialize/__init__.py::write_document()` là điểm vào duy nhất
của stage 6 và không tự tạo thư mục nào.

**`Word.line_key` có ngữ nghĩa khác nhau giữa các engine — đừng "sửa" nó.** Tesseract dùng
`(block, par, line)` do chính Tesseract trả về; paddle (`core/engines/paddle.py:32`) và easyocr
(`core/engines/easyocr.py:31`) dùng `(round(y / 10), x)`. Gom nhóm theo `line_key` vẫn đúng cho cả ba,
nhưng vì lý do khác nhau: hai engine sau vốn detect **cả dòng**, không detect từng từ, nên mỗi
`Word` của chúng đã là một dòng. `recognize/text.py` chỉ được dựa vào một tính chất duy nhất:
`line_key` bằng nhau nghĩa là cùng một dòng, và thứ tự sort của nó là thứ tự đọc trong khối.

---

## 5 · Document Model

```python
DOCLAYNET_CLASSES = (
    "caption", "footnote", "formula", "list-item", "page-footer",
    "page-header", "picture", "section-header", "table", "text", "title",
)

FLAGS = (
    "recognize_failed",      # recognizer ném lỗi, content=None
    "provider_disabled",     # provider bị tắt bằng config, content=None — KHÔNG phải lỗi
    "invalid_html",          # lxml không parse được TableContent.html
    "invalid_latex",         # pylatexenc không parse được FormulaContent.latex
    "cell_count_mismatch",   # số <td>/<th> lệch với len(cell_boxes)
    "table_continues",       # bảng này nối sang trang sau
)


@dataclass(frozen=True)
class PageGeometry:
    page: int                         # số trang thật, 1-based — KHÔNG phải index trong list
    width_px: int                     # kích thước ảnh trong hệ chuẩn (§5.1)
    height_px: int
    dpi: int
    rotation_applied: int             # 0 | 90 | 180 | 270
    deskew_angle: float               # độ
    deskew_matrix: tuple              # affine 2x3, nghịch đảo được
    pdf_width_pt: float | None        # None khi nguồn là ảnh
    pdf_height_pt: float | None


@dataclass(frozen=True)
class LogProb:
    sum: float
    mean: float
    min: float
    n_tokens: int


@dataclass(frozen=True)
class TextContent:
    text: str

@dataclass(frozen=True)
class TableContent:
    html: str                         # có rowspan/colspan
    n_rows: int
    n_cols: int
    cell_boxes: list[tuple]           # [x, y, w, h] trong HỆ CHUẨN của trang, không phải toạ độ crop

@dataclass(frozen=True)
class FormulaContent:
    latex: str                        # thất bại thì content=None, không phải latex=None

@dataclass(frozen=True)
class FigureContent:
    path: str                         # tương đối với output/<stem>/, vd "images/p0003_ab12cd34ef56.webp"


@dataclass
class Element:
    id: int                           # page * 10_000 + thứ tự trong trang; ổn định — xem §5.5
    page: int                         # số trang thật, khớp PageGeometry.page
    category: str                     # một trong DOCLAYNET_CLASSES
    bbox: tuple[int, int, int, int]   # [x, y, w, h] px tuyệt đối trong HỆ CHUẨN (§5.1)
    polygon: list[tuple] | None       # tứ giác chính xác sau khi nghịch đảo deskew
    layout_score: float | None        # 0–1, confidence của detector
    render: str                       # "flow" | "aside" | "inlined" — xem §5.5
    reading_order: int                # duy nhất trong TÀI LIỆU, dày đặc, KHÔNG nullable
    content: TextContent | TableContent | FormulaContent | FigureContent | None
    logprob: LogProb | None           # bậc 1
    rec_score: float | None           # bậc 2, 0–1
    caption_id: int | None            # id của element `caption` gắn với element này
    continues_from: int | None        # id của phần bảng ở trang trước
    flags: list[str]


@dataclass
class PageError:
    page: int
    stage: str                        # "load" | "preprocess" | "layout"
    message: str                      # "<Loại lỗi>: <thông điệp>"


@dataclass
class Document:
    source: str
    doc_sha256: str
    pipeline_version: str
    pages: list[PageGeometry]         # CHỈ các trang xử lý thành công
    elements: list[Element]
    errors: list[PageError]
```

`Document.pages` chỉ chứa trang thành công, nên **không được dùng index của nó làm số trang**.
Mọi liên kết đi qua trường `page`, cả ở `PageGeometry` lẫn `Element`. Một PDF 10 trang lỗi trang 4
cho ra `pages` 9 phần tử với `page` = 1,2,3,5,…,10 và một `PageError(page=4)`.

### 5.1 Hệ toạ độ chuẩn

**Hệ chuẩn = pixel của ảnh render ở `dpi` đã ghi, SAU khi áp rotation 0/90/180/270, TRƯỚC deskew.**

Rotation nằm *trong* hệ chuẩn vì nó là phép quay bội số 90° áp ngay lúc render, không mất mát,
và nhờ vậy `width_px`/`height_px` luôn khớp với ảnh mà detector thực sự nhìn thấy.
Deskew nằm *ngoài* hệ chuẩn vì nó là phép quay góc nhỏ có nội suy, mỗi trang một góc khác nhau.

Hai chiều chuyển đổi:

| Hàm | Việc |
| --- | --- |
| `geometry.from_canonical(box, geom)` | hệ chuẩn → khung ảnh đã deskew (cho detector/recognizer) |
| `geometry.to_canonical(box, geom)` | khung đã deskew → hệ chuẩn, bằng nghịch đảo `deskew_matrix` |
| `geometry.px_to_pdf_point(box, geom)` | hệ chuẩn → point của PDF gốc; công thức bên dưới |

`px_to_pdf_point` **chỉ dùng được khi nguồn là PDF**: `pdf_width_pt`/`pdf_height_pt` là `None` khi
nguồn là ảnh, và không có chúng thì không gỡ được rotation. Gặp `None` → raise `ValueError`, không
đoán và không trả về giá trị sai lặng lẽ.

Không dùng khái niệm "quay quanh tâm trang" — với `rotation_applied ∈ {90, 270}` thì tâm ảnh chuẩn
và tâm trang PDF là **hai điểm khác nhau**, nên nói vậy là mơ hồ và sai. Công thức viết thẳng, với
`W = pdf_width_pt`, `H = pdf_height_pt`, `s = 72 / dpi`, và `(x, y, w, h)` là bbox trong hệ chuẩn
(gốc toạ độ ở góc trên-trái, `y` hướng xuống — quy ước ảnh, không phải quy ước PDF).

Hai giả định mà công thức đứng trên, `loader.py` **bắt buộc** phải tôn trọng khi ghi `PageGeometry`:
`rotation_applied` đo **theo chiều kim đồng hồ** (cùng quy ước với `/Rotate` của PDF), và `W`/`H` là
kích thước trang **trước khi xoay**. Sai một trong hai thì test công thức vẫn xanh mà toạ độ vẫn sai
end-to-end, nên `loader.py` phải có test riêng khoá đúng hai ngữ nghĩa này.

| `rotation_applied` | Góc trên-trái của box trong hệ toạ độ trang PDF (vẫn quy ước ảnh) |
| --- | --- |
| `0` | `(s·x, s·y)`, kích thước `(s·w, s·h)` |
| `90` | `(s·y, H − s·(x + w))`, kích thước `(s·h, s·w)` |
| `180` | `(W − s·(x + w), H − s·(y + h))`, kích thước `(s·w, s·h)` |
| `270` | `(W − s·(y + h), s·x)`, kích thước `(s·h, s·w)` |

Với `90` và `270` thì `w` và `h` hoán đổi — đó chính là lý do phải biết `W`/`H`. Bước cuối, nếu
consumer cần quy ước PDF chuẩn (gốc ở góc dưới-trái, `y` hướng lên) thì lật `y_pdf = H − y_img − h`.
Hàm trả về theo quy ước nào phải được ghi trong docstring và test khoá lại.

Detector chạy trên ảnh **đã deskew**, nên bbox axis-aligned ở đó khi map về hệ chuẩn thành một
**tứ giác nghiêng**. Vì vậy element mang cả hai: `polygon` là tứ giác chính xác, `bbox` là hình chữ
nhật bao lồi của nó. `polygon` đi vào `segmentation` của COCO.

`TableContent.cell_boxes` cũng nằm trong hệ chuẩn — cùng một hệ với `Element.bbox`, không phải
toạ độ tương đối trong crop.

### 5.2 Tín hiệu bất định — quy tắc ba bậc

| Bậc | Điều kiện | Field được điền |
| --- | --- | --- |
| 1 | Provider trả per-token log-prob | `logprob = LogProb(...)`, `rec_score = None` |
| 2 | Không có log-prob, có confidence | `rec_score` ∈ [0, 1], `logprob = None` |
| 3 | Không có cả hai | Cả hai `None` — **không ghi field ra COCO**, không điền `0` |

Hai field tên khác nhau vì **thang đo khác nhau** — §3.6 cảnh báo rằng `score` theo convention COCO
là 0–1, còn log-prob thang khác; đặt trùng tên sẽ khiến công cụ đọc COCO chuẩn hiểu nhầm.
`layout_score` là field thứ ba, độc lập: confidence của **detector**, luôn 0–1.

**Chuẩn hoá về 0–1 ở bậc 2: chia 100 cho cả ba engine.** `Word.confidence` trong repo này luôn là
thang 0–100 — tesseract lấy thẳng `data["conf"]` (`core/engines/tesseract.py:34`), còn paddle
(`core/engines/paddle.py:31`) và easyocr (`core/engines/easyocr.py:30`) đều đã nhân sẵn `* 100`
để khớp. `engines/` không bị sửa, việc chia 100 nằm ở `recognize/text.py`.

Bậc nào cho cái gì trên đường classic v1:

| Element | Bậc | Nguồn |
| --- | --- | --- |
| `text` và các category văn xuôi khác | 2 | `mean(Word.confidence) / 100` |
| `table` qua `table_pp` | 2 | rec score của PP-TableRecognitionV2 |
| `table` qua `table_cv` | **3** | `recognize_text()` không trả confidence |
| `formula` | 2 | rec score của PP-FormulaNet-M |
| `picture` | **3** | crop ảnh không có khái niệm confidence nhận dạng |
| Bất kỳ element nào có `content=None` (`recognize_failed` hoặc `provider_disabled`) | **3** | Không có nhận dạng thì không có tín hiệu nhận dạng. `layout_score` vẫn còn |

Log-prob thật (bậc 1) chỉ có khi cắm VLM — xem §9 điểm 1.

Hệ quả cho QA gating: chỉ gate được element **có** tín hiệu. Element ở bậc 3 đi qua không gate,
không flag — không được coi "không có tín hiệu" là "tín hiệu xấu".

### 5.3 Bảng tràn trang: liên kết, không hợp nhất

`document/link.py` phát hiện bảng cuối trang N và đầu trang N+1 có **cùng số cột** và **cùng biên
trái/phải trong sai số 2%** (§3.3). Khi khớp, nó **không** gộp hai element làm một — nó đặt
`flags += ["table_continues"]` lên element trang N và `continues_from = <id trang N>` lên element
trang N+1.

Lý do không hợp nhất: `Element` có đúng một `page` và một `bbox`, còn COCO gắn annotation vào một
`image_id` duy nhất. Một element trải hai trang sẽ phá cả hai thứ. Liên kết giữ được cả quan hệ
lẫn tính hợp lệ của COCO.

Hai serializer đọc quan hệ này khác nhau:

- **Markdown** nối `<tbody>` của element sau vào element trước, xuất **một** bảng HTML với **một**
  anchor là id của element đầu.
- **COCO** giữ **hai** annotation riêng, mỗi cái ở `image_id` của trang nó; quan hệ nằm ở field
  mở rộng `continues_from`.

### 5.4 Caption

`document/link.py` gắn một element `caption` vào một element `picture` hoặc `table` khi:
chồng lấn theo trục ngang ≥ 50% bề rộng của element được chú thích, **và** khoảng cách dọc giữa
hai biên gần nhau nhất ≤ 5% chiều cao trang, **và** cùng trang. Gần nhất thắng nếu có nhiều ứng viên.
Điều kiện cùng trang có **đúng một ngoại lệ**, nêu ở cuối mục này.

Khi gắn được: element được chú thích nhận `caption_id`, và element `caption` nhận **`render = "inlined"`**.
Đó là **fact duy nhất** đánh dấu caption đã bị tiêu thụ — serializer không phải quét `caption_id` của
mọi element khác để suy ra. Caption không gắn được với gì thì giữ `render = "flow"` và render như
đoạn văn bình thường.

**Ngoại lệ duy nhất của điều kiện cùng trang:** caption nằm ở trang N+1 cạnh **phần nối** của một
bảng tràn trang được gắn vào **element đầu chuỗi nối** ở trang N, không phải vào phần nối — vì phần
nối không bao giờ được render thành khối riêng, nên gắn vào đó là mất caption.

### 5.5 `render`, `reading_order`, `id` — ba thứ hay bị lẫn

**`render`** trả lời đúng một câu hỏi: element này xuất hiện ở đâu trong `.md`.
`assemble.py` đặt nó **một lần**, và là nơi duy nhất được đặt:

| Điều kiện | `render` | Nghĩa |
| --- | --- | --- |
| `caption` đã gắn được vào một `picture`/`table` (§5.4) | `"inlined"` | Đã render **bên trong** khối của element cha |
| Phần nối của bảng tràn trang (`continues_from is not None`) | `"inlined"` | Đã nối vào bảng ở đầu chuỗi (§5.3) |
| `category` ∈ {`page-header`, `page-footer`, `footnote`} | `"aside"` | Render ở cuối file |
| còn lại | `"flow"` | Render tại vị trí của nó trong luồng đọc |

Bốn nhánh **loại trừ nhau hoàn toàn**, nên viết bằng if/elif theo thứ tự nào cũng cho cùng kết quả:
`link.py` chỉ đặt `continues_from` lên element `table`, và chỉ gắn caption cho element `caption`
(§5.4) — nên một `footnote` không thể là caption đã gắn, một caption không thể là phần nối bảng,
và một phần nối bảng không thể là header/footer. Nhánh cuối phủ hết phần còn lại.

Vì sao phải là ba trạng thái chứ không phải một cờ nhị phân: "không thuộc luồng chính" và "đã được
render lồng trong element khác" là **hai câu hỏi khác nhau**. Gộp chúng làm một thì caption đã gắn
và phần bảng nối trang sẽ bị render **hai lần** — một lần trong khối cha, một lần nữa ở cuối file.

Không module nào khác được tự suy ra vị trí render của một element. Trước khi có trường này,
`reading_order.py` (đẩy header/footer ra khỏi tập cut), `link.py` (đẩy caption ra) và `markdown.py`
(bỏ qua khi render) mỗi chỗ giữ một mảnh của cùng một sự thật.

**`reading_order`** được gán cho **mọi** element, bất kể `render`, nên nó **không nullable** và
`.md` lẫn COCO đều chỉ cần một khoá sort. Thứ tự:

1. Theo `page` tăng dần.
2. Trong mỗi trang: các element `render == "flow"` theo kết quả XY-cut trước; rồi tới `"inlined"`
   và `"aside"` — gộp làm **một dãy duy nhất** sắp theo `bbox.y` tăng dần, `bbox.x` phá hoà,
   không tách thành hai dãy nối tiếp.
3. Đánh số dày đặc **từ 0** trên toàn tài liệu.

Trang lỗi không đóng góp element nào nên không để lại lỗ hổng. Vì asides của trang N nằm giữa luồng
trang N và luồng trang N+1, lượt render aside ở §6.1 tự nhiên đi theo thứ tự trang.

**`id`** = `page * 10_000 + thứ tự trong trang`, với **thứ tự trong trang đếm từ 0** — nên element
đầu tiên của trang 1 có `id == 10_000`, và không id nào nhỏ hơn `10_000`. Đây không phải số thứ tự
dày đặc toàn tài liệu.

Lý do là **tính ổn định**: anchor `<!-- ann:10001 -->` tồn tại để RAG trích dẫn ngược (§3.5), mà một id
dày đặc toàn tài liệu sẽ khiến việc chạy lại một tài liệu — nay trang 4 OCR thành công, hoặc thêm
một trang — **đánh số lại toàn bộ element phía sau** và làm hỏng mọi trích dẫn đã phát ra.
Với công thức theo trang, thay đổi ở trang 4 chỉ ảnh hưởng id của trang 4.

Ba giới hạn phải nói rõ:

- id **vẫn đổi** nếu layout của chính trang đó đổi (thêm/bớt element). Đây là ổn định **theo trang**,
  không phải ổn định tuyệt đối; ổn định tuyệt đối cần id dẫn xuất từ nội dung, để dành cho lúc có
  nhu cầu thật.
- 10.000 là **trần cứng** số element một trang. Vượt trần thì id trùng nhau, và trùng id nghĩa là
  `annotations[].id` trùng trong COCO — output hỏng mà không có lỗi nào. `assemble.py` phải `assert`
  và ném lỗi, không được để trôi.
- `caption_id` và `continues_from` là **tham chiếu trong một lần chạy**, không phải khoá bền vững.
  Chúng được `link.py` dẫn xuất lại ở mỗi lần chạy từ hình học, nên nếu layout trang 4 đổi thì một
  `continues_from` ở trang 5 trỏ sang element khác — đúng, vì nó vừa được tính lại. Không được lưu
  hai giá trị này ở ngoài rồi đem dùng lại ở lần chạy sau.

---

## 6 · Serialize

`serialize/__init__.py::write_document(doc, out_dir, outputs)` là điểm vào duy nhất; nó gọi
`markdown.py` và/hoặc `coco.py` theo `Config.outputs`. Thư mục `out_dir` đã tồn tại từ stage 4.

### 6.1 Markdown

Hai lượt, cùng một khoá sort `reading_order` (duy nhất toàn tài liệu, không cần tie-break):
lượt một render các element `render == "flow"`; lượt hai dồn các element `render == "aside"` xuống
cuối file dưới một dòng `<!-- ann-aside -->`. Element `render == "inlined"` **không** vào lượt nào —
chúng đã được render bên trong khối của element cha.

**Mỗi element được render đúng một lần, ở đúng một trong ba vị trí.** Hệ quả: số anchor
`<!-- ann:N -->` trong file bằng số element **không** `inlined`, không bằng tổng số element.

| Category | Markdown |
| --- | --- |
| `title` / `section-header` | `#` / `##` |
| `text` | đoạn văn (dòng ngắt mềm đã ghép lại thành câu ở stage 4) |
| `list-item` | `-` |
| `table` | **nhúng HTML thô** — GFM chấp nhận raw HTML, và HTML giữ được merged cell mà GFM table không giữ được. Nếu `flags` chứa `table_continues` thì nối `<tbody>` của các phần sau vào (§5.3) — các phần đó là `inlined` nên không tự render. Nếu có `caption_id` thì render nội dung caption thành một đoạn văn **ngay dưới** bảng |
| `formula` | `$$…$$` |
| `picture` | `![<nội dung caption nếu có caption_id, ngược lại rỗng>](images/p0003_ab12cd34ef56.webp)` |
| `caption` | chỉ tới được lượt một khi `render == "flow"`, tức chưa gắn được vào đâu → render như đoạn văn |
| `page-header` / `page-footer` / `footnote` | luôn `render == "aside"` → lượt hai |

Mỗi block kèm anchor `<!-- ann:10001 -->` khớp `Element.id` — thứ cho phép RAG trace ngược từ chunk
về annotation → bbox → trang gốc (§3.5).

Element có `content is None` render thành `<!-- ann:10001 recognize_failed -->` — mất nội dung
nhưng **không mất vị trí**.

### 6.2 COCO

11 category DocLayNet: `caption, footnote, formula, list-item, page-footer, page-header,
picture, section-header, table, text, title`.

COCO vốn là format cho object detection, không có chỗ cho text/HTML/LaTeX. Mở rộng bằng field
tuỳ biến — quyết định thiết kế có ý thức, phải ghi vào `info.description` để công cụ đọc COCO chuẩn
không hiểu nhầm (§3.6).

`images[]` — **một entry cho mỗi trang xử lý thành công**:

| Field | Giá trị |
| --- | --- |
| `id` | `PageGeometry.page` |
| `width`, `height` | `width_px`, `height_px` trong hệ chuẩn |
| `file_name` | `"<tên file nguồn>#page=<N>"` — **định danh, không phải file tồn tại** |
| `page_geometry` (mở rộng) | `dpi`, `rotation_applied`, `deskew_angle`, `pdf_width_pt`, `pdf_height_pt` |

v1 **không persist ảnh render** (§2.7: 2M trang × ~600 KB ≈ 1,2 TB), nên không có file trang nào để
trỏ tới. `file_name` mang dạng định danh có thể tái tạo được từ `source` + `page` + `dpi`, và việc
này được nói rõ trong `info.description`.

`annotations[]` — **mỗi element sinh đúng một annotation, không có bộ lọc nào.** Kể cả element
`render == "inlined"`: chúng không tự render trong `.md` nhưng vẫn là đối tượng có bbox thật trên
trang, nên COCO phải giữ. Đây là chỗ hai serializer cố tình khác nhau.

| Field | Nguồn |
| --- | --- |
| `id`, `image_id`, `category_id`, `bbox`, `area`, `iscrowd` | chuẩn COCO; `id` = `Element.id`, `image_id` = `Element.page` |
| `segmentation` | `Element.polygon` |
| `score` | `Element.layout_score` — chuẩn COCO, 0–1; bỏ hẳn field nếu `None` |
| `text` / `html` / `latex` / `image_path` | mở rộng, theo loại content; bỏ hẳn nếu `content is None` |
| `rec_score` **hoặc** `logprob` | mở rộng; **bậc 3 thì cả hai đều không xuất hiện** |
| `reading_order`, `render` | mở rộng; luôn có mặt. `render` cho consumer phân biệt được "aside" với "đã render lồng chỗ khác" — hai thứ mà một cờ nhị phân gộp mất |
| `flags`, `caption_id`, `continues_from` | mở rộng; bỏ field nếu `None`/rỗng |

`info`: `description` (nói rõ schema mở rộng và quy ước `file_name`), `doc_sha256`, `pipeline_version`.

`Document.errors` xuất ra `info.page_errors` — trang lỗi không có `images[]` entry, nhưng không được
biến mất không dấu vết.

### 6.3 Bố cục thư mục output

```
output/<stem>/
  <stem>.md
  <stem>.coco.json
  images/p{page:04d}_{sha1[:12]}.webp
```

Đây là bố cục **mới**, không phải convention có sẵn. Thư mục `output/lpbank/` hiện tại do một công cụ
khác sinh ra và có hình dạng khác hẳn: `<stem>.md` + `<stem>.html` + `<stem>_metadata.json` + các file
`<hash>_<n>_img.webp` nằm phẳng cùng cấp. Pipeline này **không** sinh `.html` và **không** sinh
`_metadata.json`; những file cũ đó không bị đụng tới nhưng cũng không được tái tạo.

§2.4 đề xuất `{doc_sha256}/p{page:04d}/{ann_id}.png` — địa chỉ ổn định theo nội dung, cần cho dedup
ở quy mô 2M trang. v1 chọn thư mục theo tên file cho dễ đọc bằng mắt, nhưng tên file ảnh **đã** theo
hash nội dung và `doc_sha256` **đã** nằm trong `info`, nên đổi sang bố cục kia sau này không mất dữ liệu.

---

## 7 · Xử lý lỗi

Nguyên tắc: **không bao giờ mất geometry**. Nội dung hỏng được, vị trí thì không.

| Tầng | Hành vi |
| --- | --- |
| Khởi tạo provider | Provider không nạp được (thiếu thư viện, không tải được model) → `ProviderError` **fail fast**, trước khi chạm vào file nào. Không best-effort: chạy 800 trang rồi mới báo thiếu model là vô ích |
| Load | Lỗi → hỏng cả file, không tạo output. Giữ hành vi hiện tại của `pipeline.load()` |
| Trang | Best-effort — trang lỗi thành `PageError`, các trang khác vẫn xử lý và vẫn xuất. Giữ pattern `core/pipeline.py:71` |
| Element — recognizer lỗi | **Giữ element** với đủ `bbox` + `category` + `layout_score`, đặt `content=None` và `flags=["recognize_failed"]` |
| Element — provider bị tắt | `table="none"` hoặc `formula="none"` mà detector vẫn tìm thấy element loại đó → **giữ element** với đủ geometry, `content=None`, `flags=["provider_disabled"]`. Đây **không phải lỗi**: nó là lựa chọn cấu hình, và phải phân biệt được với `recognize_failed` khi đọc báo cáo |
| Validate | `lxml` không parse được HTML → `flags=["invalid_html"]`. `pylatexenc` không parse được LaTeX → `flags=["invalid_latex"]`. Số `<td>`/`<th>` lệch `len(cell_boxes)` → `flags=["cell_count_mismatch"]` |

Validate **chỉ set `flags`**, không đụng tới `rec_score`/`logprob`. Đây là tín hiệu bất định độc lập
với tín hiệu của model (§3.3); trộn hai thứ vào một con số là mất thông tin.

`config.yaml` sai khoá hoặc sai giá trị → `ConfigError` ngay khi load, trước khi chạm vào file nào.
Giữ hành vi của `core/config.py:92`.

---

## 8 · Bỏ post-processing

`core/postprocess.py` bị **xoá hẳn**, không thay bằng interface nào.

Hai lý do:

1. **Vi phạm M1.** Nó gửi text OCR ra OpenRouter, trong khi M1 là tiêu chí **bắt buộc**:
   "self-host offline hoàn toàn, không gọi API ngoài — 0,4 TB tài liệu không được rời hệ thống".
2. **Chưa từng chạy.** Model đang gọi là `nvidia/nemotron-3.5-content-safety:free` — model phân loại
   an toàn nội dung, không phải instruction-following. §5.3 ghi nhận nó "im lặng fallback về text gốc
   ở mọi trang". `core/postprocess.py:137` bắt mọi exception và trả `None`, nên lỗi này không nổi lên
   ở đâu cả.

Nếu sau này cần sửa lỗi tiếng Việt sau OCR, §5.3 đề xuất Vintern-1B-v3.5 (MIT, self-host,
MTVQA-VI 41,9 — cao hơn GPT-4o 34,2). Đó là quyết định riêng, tài liệu riêng, không phải một cửa
để mở sẵn ở đây.

---

## 9 · Năm điều phải nói thẳng

**1 · Đường classic không có log-prob thật.** Cả ba engine trả confidence của model, không phải
per-token log-probability. Vì vậy v1 tốt nhất chỉ tới bậc 2 của §5.2, và có hai loại element rơi
xuống bậc 3 (bảng qua `table_cv`, và mọi `picture`). Rủi ro #7 (§5.1) — confidence chưa hiệu chỉnh
thì ngưỡng gating vô nghĩa — vẫn còn nguyên.

**2 · Đường classic phải tự XY-cut thứ tự đọc,** đúng thứ mà `2026-08-07-chandra-pipeline-spec.md`
chê là "thay reading order do model dự đoán bằng một rule sort kém hơn". Chấp nhận vì đây là đường
CPU chạy được ngay, không phải đường chính; interface cho phép provider trả sẵn thứ tự thì dùng thẳng.

`reading_order.py` phải xử lý riêng ba thứ (§3.2), theo thứ tự này:

1. Tập cần cut = các element có `render == "flow"`, không hơn không kém. `reading_order.py`
   **không** được tự suy ra điều đó từ `category` — `assemble.py` đã đặt `render` trước khi gọi nó
   (§5.5), và đó là nơi duy nhất biết cả header/footer lẫn caption đã bị tiêu thụ.
2. XY-cut đệ quy trên tập đó: tìm khoảng trắng ngang/dọc lớn nhất, cắt, đệ quy vào từng nửa,
   sắp trên→dưới rồi trái→phải. Xử lý được layout nhiều cột.
3. Rule riêng cho **khối quốc hiệu–tiêu ngữ hai cột** đầu văn bản hành chính VN: hai khối nằm trong
   15% chiều cao đầu trang, không chồng lấn theo trục ngang → ép trái trước phải, không để XY-cut
   tự quyết.

`reading_order.py` chỉ trả về **thứ tự trong một trang** cho tập được đưa vào. Việc đánh số liên tục
toàn tài liệu và chèn các element không-`flow` vào đâu là của `assemble.py`, theo đúng quy tắc ở §5.5.

**3 · Tám thứ chưa kiểm chứng — phải đọc tài liệu/code hoặc đo khi implement, không được đoán từ spec này:**

| Chưa kiểm chứng | Ảnh hưởng nếu sai |
| --- | --- |
| Tên API `pred_html` / `cell_box_list` của PP-TableRecognitionV2 trong `paddleocr` 3.x | Viết lại `table_pp.py` |
| PP-TableRecognitionV2 **có thật sự nhận bảng không kẻ khung** hay không (M11) | Mất lý do chính để nó làm provider bảng mặc định; `table_cv` lên làm mặc định |
| Tên API và tên model `PP-FormulaNet-M` trong `paddleocr` 3.x | Viết lại `formula_pp.py`, hoặc `formula="none"` |
| Tên + số lượng class thật của `PP-DocLayout_plus-L` (§3.1 ghi "~23 class") | Bảng map class chỉ viết được sau khi đọc |
| **`PP-DocLayout_plus-L` không trả reading order, chỉ `PP-DocLayoutV2` mới trả** | Nếu sai theo hướng tốt thì bỏ được toàn bộ XY-cut ở điểm 2 — đây là claim đắt nhất trong spec, phải kiểm tra đầu tiên |
| `pypdfium2` render + đọc `pdf_width_pt`/`pdf_height_pt` bằng API nào | Viết lại `loader.py` |
| `pylatexenc` bắt được những lớp lỗi LaTeX nào (khẳng định "không biết macro có tồn tại hay không" là suy luận, chưa đo) | `validate.check_latex()` có thể vô dụng hoặc báo động giả |
| **PP-OCR có thật sự tốt hơn Tesseract trên chữ in tiếng Việt hay không.** Tài liệu yêu cầu **không** có phép so sánh nào giữa hai engine này — §1.3.3 chỉ có số của VietOCR, MC-OCR và Surya/Marker | Mất lý do đổi engine mặc định ở §10; quay về `tesseract` hoặc đo trên `evaluate/dataset/` rồi chốt |

**4 · Orientation detection chưa có phương án chắc chắn.** `pytesseract.image_to_osd` cần binary
Tesseract — không dùng được nếu người dùng chỉ cài paddle, mà paddle lại là engine mặc định.
Phương án dự phòng: bỏ `orientation` khỏi `preprocess_steps` mặc định và chỉ bật khi có Tesseract.
Cần chốt khi implement bước 1 của §12.

**5 · Validate LaTeX bằng `pylatexenc`, không phải KaTeX.** §3.4 đề xuất KaTeX, nhưng KaTeX cần
Node runtime — một dependency hệ thống mới cho một tính năng phụ. `pylatexenc` là pure Python.
Đánh đổi có ý thức cho v1; đổi sang KaTeX sau chỉ là thay thân hàm `validate.check_latex()`.

---

## 10 · Config

```python
VALID_LAYOUTS  = {"ppdoclayout", "none"}
VALID_TABLES   = {"pp", "cv", "none"}
VALID_FORMULAS = {"ppformulanet", "none"}
VALID_OUTPUTS  = {"markdown", "coco"}
VALID_STEPS    = {"orientation", "deskew", "denoise", "grayscale", "binarize"}
VALID_ENGINES  = {"tesseract", "paddleocr", "easyocr"}
DPI_RANGE      = (72, 600)

@dataclass
class Config:
    dpi: int = 300
    preprocess_steps: list[str] = field(default_factory=lambda: ["deskew", "denoise"])
    layout: str = "ppdoclayout"
    engine: str = "paddleocr"          # text recognizer; giữ tên khoá cũ để config.yaml không vỡ
    lang: str = "vie"
    langs: list[str] | None = None
    table: str = "pp"
    formula: str = "ppformulanet"
    outputs: list[str] = field(default_factory=lambda: ["markdown", "coco"])
    input_dir: str = "./input"
    output_dir: str = "./output"
```

`field(default_factory=…)` chứ không phải literal — dataclass ném `ValueError: mutable default`
với list literal. Giữ đúng dạng đang dùng ở `core/config.py:25`.

`Config.validate()` kiểm mọi trường mới theo các tập trên, cùng kiểu với `VALID_ENGINES` /
`VALID_STEPS` đang có ở `core/config.py:14`. `outputs` rỗng → `ConfigError`.

Bốn thay đổi cần giải thích:

- **`binarize` và `grayscale` bị bỏ khỏi default** (vẫn còn trong registry cho ai muốn bật lại).
  §2.3 và `GUIDELINE.md:309` đều đã ghi nhận binarize **làm giảm** độ chính xác của PaddleOCR,
  nhưng `config.yaml` hiện vẫn đang bật nó.
- **`orientation` và `denoise` chưa tồn tại** trong `core/preprocessing.py:43`. Chúng phải được
  implement, không phải chỉ khai báo — §12 bước 1 chịu trách nhiệm. `orientation` **không** nằm
  trong default vì lý do ở §9 điểm 4.
- **`layout: "none"`** là fallback bắt buộc phải có: đường classic CPU được yêu cầu chạy end-to-end,
  mà `layout` là stage duy nhất không có đường lui nếu không tải được model. Với `none`, mỗi trang
  thành một element `text` phủ cả trang — `.md` và COCO vẫn ra, chỉ mất cấu trúc.
  `table: "none"` và `formula: "none"` **không** phải fallback mà là tắt tính năng; hành vi của
  chúng định nghĩa ở hàng "provider bị tắt" của §7.
- **Engine mặc định đổi từ `tesseract` sang `paddleocr`, và lý do KHÔNG phải là M7.** Tài liệu yêu cầu
  loại **cả hai** qua ngưỡng chữ viết tay: dòng 41 ghi "toàn bộ nhánh recognizer của Tesseract **và
  PP-OCR** bị loại", §IV nhắc lại "Tesseract, PP-OCR mobile, Docling" đều đã bị loại.
  Lý do duy nhất đứng vững là **đồng bộ hệ**: layout, table và formula provider đều là paddle, nên để
  text recognizer cũng là paddle thì chỉ một hệ, một lần tải model, một bộ phụ thuộc. Đây là lý do
  vận hành, **không** phải lý do chất lượng — phép so sánh chất lượng giữa hai engine chưa ai đo,
  xem hàng cuối bảng §9.3. Nếu phép đo trên `evaluate/dataset/` cho kết quả ngược thì đổi lại,
  chi phí bằng một dòng config. Đường đạt M7 không phải đường này — nó là cắm VietOCR vào
  `TextRecognizer` (STT 1 ⭐).

`PIPELINES` giữ hai entry; `mode` không còn là thứ phân biệt chúng:

```python
PIPELINES = {
    "legal":   Config(outputs=["markdown", "coco"]),
    "invoice": Config(outputs=["coco"], formula="none"),
}
```

### 10.1 Dependency delta

| Thêm | Vì sao |
| --- | --- |
| `pypdfium2` | Thay `pdf2image` — nhanh hơn, không cần binary Poppler (§2.2) |
| `lxml` | Validate HTML bảng (§3.3) |
| `pylatexenc` | Validate LaTeX (§9 điểm 5) |

| Bỏ | Vì sao |
| --- | --- |
| `pdf2image` | Consumer duy nhất là `core/pipeline.py:42`, biến mất cùng `loader.py` mới |
| `openrouter`, `python-dotenv` | Chỉ dùng bởi `postprocess.py` (§8) |

`paddleocr` chuyển từ optional sang **bắt buộc** trong `requirements.txt` vì nó là default của cả
`layout`, `engine`, `table`, `formula`. `setup.sh` bỏ cài Poppler, giữ cài Tesseract (vẫn là một
engine hợp lệ).

---

## 11 · Test

`tests/` hiện **đang bị xoá khỏi working tree** (`git status` báo `D` cho cả 9 file). Khôi phục bằng
`git checkout HEAD -- tests/` là bước đầu, nhưng phải nói rõ: **đây là viết lại, không phải port.**
Cả 9 file đều `import ocr_core.*` (vd `tests/test_config.py:3`) trong khi package đã đổi tên thành
`core/` — suite hiện tại không import nổi.

| File cũ | Xử lý |
| --- | --- |
| `test_extract.py`, `test_markdown.py`, `test_postprocess.py` | **Xoá** — module tương ứng biến mất |
| `test_config.py` | Giữ, sửa import, bỏ assert về `mode`, thêm assert cho các tập valid mới |
| `test_engine.py`, `test_paddle.py`, `test_easyocr.py`, `test_tables.py` | Giữ, sửa import; `engines/` và `tables.py` không đổi hành vi |

Test mới. Phần lớn dùng **fake provider**, không tải model, chạy trong vài giây:

| Test | Khẳng định |
| --- | --- |
| `geometry` | `to_canonical(from_canonical(p)) == p` trong sai số 1 px, ở nhiều góc deskew |
| `geometry` | `px_to_pdf_point` đúng cho cả bốn giá trị `rotation_applied`, theo đúng bảng công thức ở §5.1; với 90/270 thì `w`/`h` hoán đổi |
| `geometry` | Quy ước gốc toạ độ mà `px_to_pdf_point` trả về được khoá lại bằng một giá trị cụ thể, không để mơ hồ |
| `geometry` | `pdf_width_pt is None` (nguồn là ảnh) → `px_to_pdf_point` raise `ValueError` |
| `geometry` | `polygon` của một bbox nghiêng có bao lồi đúng bằng `bbox` |
| `loader` | PDF 3 trang → 3 `PageGeometry` với `page` = 1,2,3, `dpi` khớp config, `pdf_width_pt` khác `None` |
| `loader` | Nguồn là `.png` → một `PageGeometry`, `page=1`, `pdf_width_pt is None` |
| `loader` | Đuôi file không hỗ trợ → `UnsupportedFormatError` |
| `loader` | Trang PDF có `/Rotate 90` → `rotation_applied == 90` (**thuận** chiều kim đồng hồ), và `pdf_width_pt`/`pdf_height_pt` là kích thước **trước** khi xoay. Khoá đúng hai giả định mà công thức §5.1 đứng trên — test công thức không bắt được lỗi này |
| `layout` | Class lạ → `"text"` + có dòng log; class biết được → map đúng 1 trong 11 |
| `layout` | `layout="none"` → đúng một element `text` phủ cả trang, `layout_score is None` |
| `table_cv` | Grid có ô gộp → HTML có `rowspan`/`colspan` đúng; `len(cell_boxes)` khớp số `<td>` |
| `table_cv` | Element bảng qua `cv` ở bậc 3 — cả `rec_score` lẫn `logprob` đều `None` |
| `text` | Gom `Word` theo `line_key`, reflow dòng ngắt mềm; `rec_score == mean(conf)/100` và ∈ [0,1] |
| `reading_order` | Layout hai cột: cột trái xong hết mới sang phải |
| `reading_order` | Khối quốc hiệu–tiêu ngữ hai cột đầu trang không bị đảo |
| `reading_order` | Nhận vào tập `render == "flow"` của một trang, trả về thứ tự trong trang đó; không tự lọc theo `category` |
| `assemble` | `reading_order` liên tục từ 0, duy nhất, **không nullable** trên toàn tài liệu nhiều trang — kể cả element `aside` và `inlined` |
| `assemble` | `render` đúng cả bốn nhánh của bảng §5.5: caption đã gắn → `inlined`; phần nối bảng → `inlined`; header/footer/footnote → `aside`; caption lạc lõng → `flow` |
| `assemble` | Aside và inlined trong cùng một trang sắp theo `bbox.y` tăng dần |
| `assemble` | `id == page * 10_000 + thứ tự trong trang` đếm từ 0 → element đầu trang 1 có `id == 10_000`; layout trang 2 đổi thì id trang 1 và 3 **không đổi** |
| `assemble` | Trang có hơn 10.000 element → ném lỗi, **không** để id trùng trôi ra COCO |
| `assemble` | `assemble` gọi `validate` — element có HTML hỏng đi ra khỏi stage 5 đã mang sẵn `invalid_html` |
| `link` | Bảng cuối trang N và đầu trang N+1 cùng số cột, cùng biên ±2% → N có `table_continues`, N+1 có `continues_from`; **vẫn là hai element** |
| `link` | Caption nằm ngay dưới `picture`, chồng ngang 60% → `picture.caption_id` được gán; caption lạc lõng thì không |
| `link` | Caption gắn vào `table` cũng được gán `caption_id` — cùng quy tắc với `picture` |
| `link` | Caption ở trang N+1 cạnh phần nối bảng → gắn vào element **đầu chuỗi** ở trang N, không gắn vào phần nối |
| `validate` | HTML hỏng → `invalid_html`; LaTeX hỏng → `invalid_latex`; số ô lệch → `cell_count_mismatch`; **`rec_score` không đổi trong cả ba** |
| `serialize/markdown` | Mọi block có anchor `<!-- ann:N -->` khớp `Element.id`; bảng nhúng HTML thô; `content=None` vẫn có anchor |
| `serialize/markdown` | Caption gắn vào `picture` vào `![…]()`; caption gắn vào `table` thành đoạn văn ngay dưới bảng; **không cái nào xuất hiện hai lần, cũng không cái nào biến mất** |
| `serialize/markdown` | Bảng tràn trang xuất một bảng, một anchor; phần nối **không** xuất hiện lần thứ hai ở bất kỳ đâu |
| `serialize/markdown` | Mọi element `render == "aside"` nằm sau `<!-- ann-aside -->`; không element `inlined` nào nằm ở đó |
| `serialize/markdown` | **Số anchor bằng số element có `render != "inlined"`** — đây là assertion bắt được lỗi render hai lần |
| `serialize/coco` | Đúng 11 category; bbox nằm trong `[0,width] × [0,height]`; `image_id` khớp số trang thật |
| `serialize/coco` | Element bậc 3 **không có** field `rec_score` lẫn `logprob`; `layout_score is None` thì không có field `score` |
| `serialize/coco` | Bảng tràn trang cho **hai** annotation ở hai `image_id` |
| `router` | Recognizer ném lỗi → element vẫn còn `bbox` + `category`, `content=None`, `flags` chứa `"recognize_failed"` |
| `router` | `table="none"` mà detector tìm thấy bảng → element giữ geometry, `content=None`, `flags` chứa `"provider_disabled"` chứ **không** chứa `"recognize_failed"` |
| `pipeline` | PDF 10 trang lỗi trang 4 → `PageError(page=4)`, `pages` có 9 phần tử, mọi `Element.page` là số trang thật, không có trang nào bị dịch chỉ số |
| `pipeline` | Provider không nạp được → `ProviderError` trước khi mở file đầu tiên |
| `config` | Khoá lạ → `ConfigError`; `mode` (khoá đã xoá) → `ConfigError`; `layout`/`table`/`formula`/`outputs`/`dpi` sai giá trị → `ConfigError` |

Một test tích hợp chạy model thật trên một PDF của `evaluate/dataset/high_quality_printed/`,
đánh dấu `@pytest.mark.slow`, không chạy trong vòng lặp phát triển thường.

---

## 12 · Thứ tự implement

Spec này ở mức trên của một plan. Đề nghị **cắt thành hai plan** ở ranh giới bước 3/4: mọi thứ
trước bước 4 không phụ thuộc provider nào và test được bằng `Document` dựng tay.

**Plan A — nền, không phụ thuộc provider**

1. `geometry.py` + `loader.py` + `preprocess.py` (gồm **implement** `orientation` và `denoise`,
   và chốt phương án orientation theo §9 điểm 4) — tầng toạ độ là blocker của mọi thứ sau
2. `document/model.py` — Document Model thuần dữ liệu
3. `serialize/__init__.py` + `markdown.py` + `coco.py` — test bằng `Document` dựng tay

**Plan B — provider và lắp ráp**

4. Kiểm tra ngay claim đắt nhất ở §9 điểm 3 (PP-DocLayout có trả reading order không), rồi
   `layout/` + `recognize/`
5. `document/reading_order.py` + `link.py` + `assemble.py` + `validate.py`
6. `pipeline.py` + `config.py` + `main.py` — nối lại
7. Dọn: xoá `extract.py`, `postprocess.py`, `.env.example`; cập nhật `requirements.txt` và `setup.sh`
   theo §10.1; viết lại `tests/` theo §11; cập nhật tài liệu theo bảng dưới

### 12.1 Tài liệu phải sửa

| File | Việc |
| --- | --- |
| `README.md` | Xoá mục "Hậu xử lý LLM" (`README.md:65`) và dòng `postprocess` trong ví dụ `config.yaml`; viết lại bảng "Pipeline hiện có" (`mode` không còn); vẽ lại sơ đồ mermaid theo 6 stage; cập nhật "Cấu trúc dự án" |
| `GUIDELINE.md` | **Không có** mục hậu xử lý nào để xoá. Nhưng có **12 dòng** nhắc `mode` (111, 116, 117, 145, 154, 188–190, 200, 210, 213, 217) và cả mục "Cấu trúc đầu ra" (`GUIDELINE.md:122`) mô tả output theo `mode` — phải viết lại. Mục 6 "Tạo pipeline mới" và mục 7 "Thêm OCR engine mới" cũng cần cập nhật theo interface mới |
| `config.yaml` | Xoá `postprocess`, `preprocess_steps` cũ; thêm `dpi`/`layout`/`table`/`formula`/`outputs` |
| `TODO.md` | Hai mục "Build pipeline ocr for RAG workflow -> .md" và "-> .json" được spec này giải quyết |
