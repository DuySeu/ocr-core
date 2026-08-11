# Cấu phần 4 - Core pipeline, kiến trúc hiện tại (staged, 6 stage)

Nguồn gốc (đã xoá, nội dung gộp vào đây): `2026-08-07-chandra-pipeline-spec.md` (quyết định one-pass Chandra) +
`superpowers/specs/2026-08-07-staged-ocr-pipeline-design.md` (kiến trúc 6-stage triển khai thật, cùng ngày,
dung hoà lại quyết định trên). Đây là **kiến trúc `core/` đang được implement**.
Phạm vi: `core/` trên một máy - **không** bao gồm orchestration 2M trang (xem [Cấu phần 5](05-aws-infrastructure.md)).
Nền tảng quyết định model: [Cấu phần 1](01-nghien-cuu-chon-model.md).

## 1 · Hai quyết định, một ngày, dung hoà với nhau

**Quyết định gốc (chandra-pipeline-spec):** dùng **Chandra OCR 2 (4B)** làm một pass duy nhất cho layout +
reading order + text + bảng + công thức, thay cho workflow 5 model (preprocess → layout → 4 recognizer
chuyên biệt → sort → export). Lý do: Chandra trả sẵn cả ba thứ đó trong cùng một forward pass, tự làm lại
vừa nhân chi phí GPU vừa thay reading order do model dự đoán bằng rule sort kém hơn.

**Quyết định triển khai (staged-ocr-pipeline-design, viết ngay sau):** thay vì viết thẳng adapter Chandra,
dựng lại `core/` thành **6 stage, mỗi stage một interface**, cho phép một provider one-pass (Chandra,
PaddleOCR-VL) cài đặt nhiều stage cùng lúc mà không sửa pipeline - đúng tinh thần "giữ cửa mở cho VLM bằng
interface, không phải bằng code thêm" ([Cấu phần 1](01-nghien-cuu-chon-model.md) §5.4).

**Hệ quả quan trọng nhất, phải nói rõ:** **v1 không dùng Chandra.** V1 chạy đường **classic CPU** (PP-DocLayout
cho layout, `core/engines/` cho text, PP-TableRecognitionV2/`table_cv` cho bảng, PP-FormulaNet cho công thức)
end-to-end, đủ để đo CER trên `evaluate/dataset/` ngay. Adapter Chandra/PaddleOCR-VL **chỉ có interface**,
chưa viết. Đường classic phải tự XY-cut thứ tự đọc - đúng thứ mà chandra-pipeline-spec chê là "rule sort kém
hơn model dự đoán" - chấp nhận vì đây là đường chạy ngay, không phải đường chính dài hạn.

### Phạm vi v1

| Hạng mục | v1 |
| --- | --- |
| Đường classic CPU, đủ 4 nhãn text/table/picture/formula | **Chạy thật, end-to-end** |
| Adapter Chandra / PaddleOCR-VL | Chỉ interface, **không viết** |
| Đọc thẳng text layer PDF không-scan | **Ngoài phạm vi** - tạo đường thứ hai hình dạng khác, để dành cho sub-project orchestration |
| Orchestration 2M trang | **Ngoài phạm vi** - [Cấu phần 5](05-aws-infrastructure.md) |
| QA gating & hàng đợi review | Chỉ sinh `flags` trên element; tầng gating riêng ngoài phạm vi |
| Post-processing sửa text bằng LLM | **Xoá hẳn** - xem [Cấu phần 3](03-core-pipeline-legacy.md) §"Vì sao bị thay thế" |

### Điều kiện huỷ quyết định Chandra (đo trước khi khoá kế hoạch hạ tầng chính)

| Cần đo | Ngưỡng huỷ |
| --- | --- |
| CER tiếng Việt của Chandra trên corpus thật | Dưới mức chấp nhận được cho tra cứu - **chưa có số nào công bố** |
| Độ chính xác chữ viết tay | < 50% (M7) - Chandra qua M7 vì thiếu dữ liệu, không phải vì đã vượt |
| Throughput trang/s | Quá chậm so với ngân sách GPU - nhà cung cấp không công bố trang/s |

Nếu trượt, quay lại [Cấu phần 1](01-nghien-cuu-chon-model.md) §1.3.2 chọn lại model; tầng adapter (stage 3-4
ở dưới) là chỗ duy nhất phải viết lại. Đường dự phòng: block `table`/`formula` dưới ngưỡng crop ra, đẩy qua
Vintern-1B-v3.5 (MIT, MTVQA-VI 41,9) làm trọng tài, trước khi đẩy cho người review.

## 2 · Vấn đề của kiến trúc cũ

Xem [Cấu phần 3](03-core-pipeline-legacy.md) - tóm tắt: `extract.py` rẽ nhánh mode ngay từ tầng extract nên
không sinh được `.md` + COCO từ cùng một lần OCR; không có hệ toạ độ trang; reading order chỉ sort theo `y`
(vỡ ở layout nhiều cột); không có tầng phát hiện & gán nhãn đối tượng thật (chỉ có `tables.py` cv thuần, chỉ
nhận bảng kẻ khung).

## 3 · Luồng 6 stage

```
run_document(path, cfg) -> Document

 1 Load        loader.py       PDF/ảnh -> PageImage[] + PageGeometry (pypdfium2, 300 DPI)
 2 Preprocess  preprocess.py   orientation -> deskew (GIỮ ma trận affine) -> denoise
 3 Layout      layout/         LayoutDetector.detect(page) -> LayoutBox[] (11 class DocLayNet, layout_score, bbox)
 4 Recognize   recognize/      Router theo category:
                 text/title/section-header/list-item/caption/footnote/page-header/page-footer -> TextRecognizer
                 table    -> TableRecognizer   -> TableContent
                 formula  -> FormulaRecognizer -> FormulaContent
                 picture  -> FigureExtractor   -> FigureContent
 5 Assemble    document/       link caption -> link bảng tràn trang -> đặt render ->
                               reading order -> gán id -> validate -> Document
 6 Serialize   serialize/      markdown.py -> .md    +    coco.py -> .coco.json
```

Stage 6 đọc **cùng một** `Document` - một lần OCR, hai output. Cây module đầy đủ (`core/geometry.py`,
`core/layout/`, `core/recognize/`, `core/document/`, `core/serialize/`) theo đúng ranh giới stage này;
`core/engines/` và `core/tables.py` ([Cấu phần 2](02-ocr-engines.md)) **không sửa**, chỉ được gọi từ
`recognize/text.py` và `recognize/table_cv.py`.

**Bốn ranh giới dễ nhầm:** (1) các `*Content` chỉ thuộc `document/model.py`, `recognize/` import chúng chứ
không ngược lại. (2) `recognize/text.py` gọi `recognize_words()` chứ không phải `recognize_text()` - đây là
điều kiện để có tín hiệu bất định (`recognize_text` trả `str` trần, không confidence); hệ quả là ô bảng qua
`table_cv.py` (dùng `recognize_text(psm=6)`) **không có** tín hiệu bất định. (3) `pipeline.run_to_files()`
tạo `output/<stem>/images/` trước stage 4, file ảnh đặt tên theo **hash nội dung** `p{page:04d}_{sha1[:12]}.webp`
vì `Element.id` mãi tới stage 5 mới có. (4) `Word.line_key` có ngữ nghĩa khác nhau giữa engine - xem
[Cấu phần 2](02-ocr-engines.md); gom nhóm theo nó vẫn đúng cho cả ba nhưng vì lý do khác nhau.

## 4 · Document Model (rút gọn)

```python
DOCLAYNET_CLASSES = ("caption","footnote","formula","list-item","page-footer",
    "page-header","picture","section-header","table","text","title")

FLAGS = ("recognize_failed", "provider_disabled", "invalid_html",
         "invalid_latex", "cell_count_mismatch", "table_continues")

PageGeometry: page, width_px, height_px, dpi, rotation_applied, deskew_angle,
              deskew_matrix, pdf_width_pt | None, pdf_height_pt | None

LogProb: sum, mean, min, n_tokens

TextContent(text) · TableContent(html, n_rows, n_cols, cell_boxes) ·
FormulaContent(latex) · FigureContent(path)

Element: id, page, category, bbox, polygon, layout_score, render,
         reading_order, content, logprob, rec_score, caption_id,
         continues_from, flags

PageError: page, stage, message
Document: source, doc_sha256, pipeline_version, pages, elements, errors
```

`Document.pages` chỉ chứa trang **thành công** - không dùng index của nó làm số trang, mọi liên kết đi qua
field `page`. Một PDF 10 trang lỗi trang 4 → `pages` 9 phần tử (`page` = 1,2,3,5...10) + một `PageError(page=4)`.

### 4.1 Hệ toạ độ chuẩn

**Hệ chuẩn = pixel ảnh render ở `dpi` đã ghi, SAU rotation 0/90/180/270, TRƯỚC deskew.** Rotation nằm trong
hệ chuẩn (không mất mát, khớp ảnh detector nhìn thấy); deskew nằm ngoài (góc nhỏ, có nội suy, mỗi trang khác
nhau). Ba hàm chuyển đổi: `from_canonical` (hệ chuẩn → khung deskew, cho detector), `to_canonical` (nghịch
đảo `deskew_matrix`), `px_to_pdf_point` (hệ chuẩn → point PDF gốc - chỉ dùng được khi nguồn là PDF, `None`
→ raise `ValueError`, không đoán).

Công thức `px_to_pdf_point` với `W,H = pdf_width_pt/height_pt`, `s = 72/dpi`:

| `rotation_applied` | Góc trên-trái trong hệ toạ độ trang PDF (quy ước ảnh) |
| --- | --- |
| 0 | `(s·x, s·y)`, kích thước `(s·w, s·h)` |
| 90 | `(s·y, H - s·(x+w))`, kích thước `(s·h, s·w)` |
| 180 | `(W - s·(x+w), H - s·(y+h))`, kích thước `(s·w, s·h)` |
| 270 | `(W - s·(y+h), s·x)`, kích thước `(s·h, s·w)` |

`rotation_applied` đo **theo chiều kim đồng hồ** (cùng quy ước `/Rotate` của PDF); `W`/`H` là kích thước
trang **trước khi xoay** - `loader.py` phải tôn trọng đúng hai giả định này, cần test riêng vì sai một
trong hai thì test công thức vẫn xanh mà toạ độ sai end-to-end. Detector chạy trên ảnh đã deskew nên bbox
axis-aligned map về hệ chuẩn thành tứ giác nghiêng: `polygon` giữ tứ giác chính xác, `bbox` là hình chữ nhật
bao lồi (đi vào `segmentation` của COCO). `TableContent.cell_boxes` cũng nằm trong hệ chuẩn.

### 4.2 Tín hiệu bất định - ba bậc

| Bậc | Điều kiện | Field |
| --- | --- | --- |
| 1 | Provider trả per-token log-prob | `logprob` set, `rec_score = None` |
| 2 | Không log-prob, có confidence | `rec_score ∈ [0,1]`, `logprob = None` |
| 3 | Không có cả hai | Cả hai `None` - **không ghi field ra COCO**, không điền `0` |

Chuẩn hoá về 0-1 ở bậc 2: chia 100 (`Word.confidence` luôn thang 0-100 ở cả 3 engine). `layout_score` là
field độc lập thứ ba - confidence của detector, luôn 0-1. Trên đường classic v1: `text` và văn xuôi → bậc 2;
`table` qua `table_pp` → bậc 2; `table` qua `table_cv` → **bậc 3**; `formula` → bậc 2; `picture` → **bậc 3**
(crop ảnh không có khái niệm confidence nhận dạng); log-prob thật (bậc 1) chỉ có khi cắm VLM. QA gating chỉ
gate được element **có** tín hiệu - bậc 3 đi qua không gate, không flag.

### 4.3 Bảng tràn trang, caption, render/reading_order/id

**Bảng tràn trang:** phát hiện bằng cùng số cột + cùng biên trái/phải (sai số 2%). Khi khớp: **không** gộp
element - đặt `flags += ["table_continues"]` ở trang N, `continues_from = <id trang N>` ở trang N+1 (một
`Element` chỉ có một `page`/`bbox`, gộp sẽ phá cả hai và phá tính hợp lệ COCO). Markdown nối `<tbody>` thành
một bảng; COCO giữ hai annotation riêng, quan hệ nằm ở field mở rộng `continues_from`.

**Caption:** gắn vào `picture`/`table` khi chồng lấn ngang ≥50% bề rộng, cách dọc ≤5% chiều cao trang, cùng
trang (ngoại lệ duy nhất: caption cạnh phần nối bảng tràn trang gắn vào **element đầu chuỗi**, không gắn vào
phần nối). Khi gắn được: element được chú thích nhận `caption_id`, caption nhận `render = "inlined"`.

**`render`** (đặt đúng một lần ở `assemble.py`): `"inlined"` (caption đã gắn, hoặc phần nối bảng) ·
`"aside"` (page-header/footer/footnote, render cuối file) · `"flow"` (còn lại, vị trí tự nhiên). Ba trạng
thái chứ không phải cờ nhị phân - gộp "không thuộc luồng chính" với "đã render lồng chỗ khác" sẽ khiến
element bị render **hai lần**.

**`reading_order`** gán cho **mọi** element (không nullable): theo `page` tăng dần; trong trang, `flow` theo
XY-cut trước, rồi `inlined`+`aside` gộp một dãy sắp theo `bbox.y`; đánh số dày đặc từ 0 toàn tài liệu.

**`id`** = `page * 10_000 + thứ tự trong trang (đếm từ 0)` - ổn định **theo trang**, không phải dày đặc toàn
tài liệu, để chạy lại một trang không đánh số lại (và không phá) anchor citation của các trang khác. 10.000
là trần cứng số element/trang - vượt trần phải `assert` và raise, không để trôi ra COCO trùng id.

## 5 · Serialize

`serialize/__init__.py::write_document(doc, out_dir, outputs)` là điểm vào duy nhất.

**Markdown:** hai lượt theo `reading_order` - lượt 1 render `flow`, lượt 2 dồn `aside` xuống dưới
`<!-- ann-aside -->`. `inlined` không vào lượt nào (đã render trong khối cha). `table`/`title`/`text`/
`list-item`/`formula`/`picture` render theo class chuẩn (bảng nhúng HTML thô để giữ merged cell - GFM
không giữ được). Mỗi block kèm anchor `<!-- ann:N -->` khớp `Element.id` - điều kiện để RAG trace ngược
về bbox/trang gốc. Số anchor bằng số element **không** `inlined`.

**COCO:** 11 category DocLayNet; mở rộng field tuỳ biến, ghi rõ vào `info.description` để công cụ đọc COCO
chuẩn không hiểu nhầm. `annotations[]` sinh **đúng một** cho mỗi element, kể cả `inlined` (COCO không lọc
theo render vì đó vẫn là đối tượng có bbox thật). v1 **không persist ảnh render** nên `images[].file_name`
là định danh `"<nguồn>#page=<N>"`, không phải file tồn tại. Bảng tràn trang cho **hai** annotation riêng
biệt ở hai `image_id`.

## 6 · Xử lý lỗi

Nguyên tắc: **không bao giờ mất geometry** - nội dung hỏng được, vị trí thì không.

| Tầng | Hành vi |
| --- | --- |
| Khởi tạo provider | Fail fast, `ProviderError`, trước khi chạm file nào |
| Load | Lỗi → hỏng cả file |
| Trang | Best-effort → `PageError`, trang khác vẫn xử lý và xuất |
| Recognizer lỗi | Giữ element đủ geometry, `content=None`, `flags=["recognize_failed"]` |
| Provider bị tắt (`table="none"`) | Giữ element đủ geometry, `content=None`, `flags=["provider_disabled"]` - **không phải lỗi** |
| Validate (lxml/pylatexenc/đếm ô) | Chỉ set `flags`, không đụng `rec_score`/`logprob` - tín hiệu độc lập |

## 7 · Config

```python
Config: dpi=300, preprocess_steps=[deskew,denoise], layout="ppdoclayout",
        engine="paddleocr", lang="vie", table="pp", formula="ppformulanet",
        outputs=[markdown, coco]
```

Bốn thay đổi cần nhớ so với kiến trúc cũ ([Cấu phần 3](03-core-pipeline-legacy.md)): `binarize`/`grayscale`
bỏ khỏi default (làm giảm chính xác PaddleOCR); `orientation`/`denoise` cần **implement mới**, chưa tồn tại;
`layout="none"` là fallback bắt buộc (mỗi trang thành 1 element `text` phủ cả trang, không mất `.md`/COCO);
engine mặc định đổi `tesseract` → `paddleocr` - lý do là **đồng bộ hệ** (layout/table/formula đều paddle),
**không phải** vì chất lượng (chưa ai đo Paddle vs Tesseract trên tiếng Việt).

## 8 · Điều chưa kiểm chứng (đọc code/đo khi implement, không đoán)

- Tên API `pred_html`/`cell_box_list` của PP-TableRecognitionV2 và `PP-FormulaNet-M` trong `paddleocr` 3.x.
- PP-TableRecognitionV2 có thật nhận bảng borderless không (M11) - nếu không thì `table_cv` lên mặc định.
- **`PP-DocLayout_plus-L` có trả reading order hay chỉ `PP-DocLayoutV2` mới trả** - claim đắt nhất trong spec, kiểm tra đầu tiên; nếu đúng theo hướng tốt thì bỏ được toàn bộ XY-cut.
- Orientation detection cần binary Tesseract (`pytesseract.image_to_osd`) - không dùng được nếu chỉ cài paddle (default engine). Phương án dự phòng: bỏ `orientation` khỏi default, chỉ bật khi có Tesseract.
- Validate LaTeX dùng `pylatexenc` (pure Python) thay vì KaTeX (cần Node runtime) - đánh đổi có ý thức cho v1.

## 9 · Thứ tự implement

**Plan A - nền, không phụ thuộc provider:** `geometry.py` + `loader.py` + `preprocess.py` → `document/model.py`
→ `serialize/` (test bằng `Document` dựng tay).

**Plan B - provider và lắp ráp:** kiểm tra claim đắt nhất (PP-DocLayout reading order) → `layout/` +
`recognize/` → `document/reading_order.py` + `link.py` + `assemble.py` + `validate.py` → `pipeline.py` +
`config.py` + `main.py` → dọn (xoá `extract.py`, `postprocess.py`; cập nhật `requirements.txt`, `tests/`,
`README.md`, `GUIDELINE.md`).
