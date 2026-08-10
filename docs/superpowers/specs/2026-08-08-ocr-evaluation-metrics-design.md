# Đo chất lượng `ocr-core` — ba metric, ba stage, một lần ghép cặp

Ngày: 2026-08-08
Trạng thái: Design — chờ duyệt để lập kế hoạch implement
Phạm vi: package `evaluate/`. **Không** sửa `core/`.
Tài liệu nguồn:
[staged pipeline design](2026-08-07-staged-ocr-pipeline-design.md) ·
[requirements analysis](../../2026-08-06-ocr-2m-pages-requirements-analysis.md)

Mọi tham chiếu `§x.y` **không** ghi rõ tài liệu là trỏ tới tài liệu này. Tham chiếu tới thiết kế
6 stage được ghi dạng `[staged §x.y]`.

---

## 1 · Vấn đề

`evaluate/main.py` và `evaluate/chandra.py` đang là file rỗng 0 byte. Không có gì để mở rộng.

`evaluate/dataset/` có 24 PDF chia 5 nhóm (`high/low_quality` × `printed/handwritten`, cộng
`lpbank/` 16 file). `evaluate/ground_truth/` có **4 file, toàn văn bản thuần**: 3 `.docx` cho nhóm
printed, 1 `.md` cho nhóm handwritten.

Hệ quả trực tiếp: WER/CER chạy được ngay hôm nay trên 4 tài liệu. **TEDS và IoU không có gì để
đối chiếu** — không tồn tại một annotation bbox nào, không tồn tại một bảng ground truth nào
trong repo.

Thiếu sót thứ hai, nặng hơn: pipeline đang giữa đợt refactor 6 stage. `core/document/model.py`,
`core/geometry.py`, `core/serialize/` đã theo thiết kế mới; `core/layout/` và `core/recognize/`
**chưa tồn tại**. Một harness đo đạc bám vào nội bộ `core/` lúc này sẽ phải viết lại giữa chừng.

---

## 2 · Quyết định

Harness là **file vào, file ra**. `evaluate/` không import `core/`.

Đầu vào là `output/<stem>/<stem>.coco.json` do stage 6 sinh ra, đối chiếu với
`evaluate/gold/<bucket>/<stem>.coco.json`. Điều này chạy được vì [staged §6.2] đã đặt **mọi thứ
ba metric cần** vào đúng một file: `bbox` + `category_id` cho IoU, field mở rộng `text` cho
WER/CER mức element, field mở rộng `html` cho TEDS. File `.md` chỉ đọc cho metric document-level.

Ba hệ quả, đều là lý do chọn:

- Harness **dựng và test được ngay hôm nay** trên fixture COCO viết tay, trong khi `core/layout/`
  và `core/recognize/` chưa có. Số đo thật đến khi hai stage đó xong; code đo thì không phải chờ.
- Nó chấm **bất kỳ hệ nào** phát ra schema đó — kể cả adapter Chandra hay PaddleOCR-VL sau này,
  vốn là cái [staged §2] cố tình giữ cửa mở.
- Gold annotation nằm đúng định dạng serializer đang phát ra, nên chấm điểm là một phép diff
  COCO-với-COCO. Không có schema thứ ba.

Cái mất: harness chỉ nhìn thấy những gì stage 6 đã ghi. Nếu một stage đánh rơi element trong im
lặng, ta thấy triệu chứng chứ không thấy stage nào gây ra. Chấp nhận — xem §13 điểm 1.

### 2.1 Phạm vi v1

| Hạng mục | v1 |
| --- | --- |
| Stage 3 Layout — IoU | **Có** |
| Stage 4 Text — WER/CER | **Có**, mức element (chính) + mức document (phụ) |
| Stage 4 Table — TEDS | **Có** |
| Stage 1 Load, stage 2 Preprocess, stage 6 Serialize | **Không đo** — plumbing tất định, sai thì test đơn vị bắt được, không cần metric |
| Stage 5 Assemble — thứ tự đọc | **Không đo trong v1** — xem §13 điểm 4 |
| Stage 4 Formula — **nội dung LaTeX** | **Không đo** — không nằm trong ba metric được yêu cầu. **Bbox** của `formula` vẫn được chấm IoU như 10 category còn lại; chỉ chuỗi LaTeX là không có metric |
| Gating chất lượng, hàng đợi review | Ngoài phạm vi. Harness sinh số, không sinh quyết định |

---

## 3 · Luồng

```
evaluate_dataset(cfg) -> Report

 0 Resolve  manifest.py    gold/manifest.yaml -> DocEntry[] (nguồn · pred · gold · text GT)
 1 Load     loader.py      pred + gold .coco.json -> EvalElement[]
                           gold .docx/.md + pred .md -> raw text (CHƯA chuẩn hoá)
 2 Match    matching.py    mỗi (trang, category): ghép tham lam theo IoU -> MatchResult
 3 Score    metrics/       layout.py · text.py · table.py  đọc CÙNG MỘT MatchResult
 4 Report   report.py      gộp theo trang -> tài liệu -> bucket -> results.json + results.md
```

Ranh giới `loader.py` / `normalize.py`, chốt ở đây vì dễ nhầm: **`loader.py` đọc file và trả text
thô** (bóc paragraph + ô bảng từ `.docx`, đọc nguyên văn `.md`). **`normalize.py` biến đổi
text → text** — bóc markdown, quy chuẩn dấu thanh, gộp khoảng trắng. Bóc markdown là chuẩn hoá;
đọc `.docx` là I/O. Không module nào làm cả hai.

Một lần ghép cặp, ba metric. Đây không phải tiết kiệm code — nó là điều kiện để §5.2 đứng vững:
ba metric phải nói về **cùng một tập cặp element**, nếu không thì "cô lập stage" không có nghĩa.

---

## 4 · Cây module

```
evaluate/
  __init__.py       API công khai: evaluate_document(), evaluate_dataset()
  __main__.py       CLI: python -m evaluate [--bucket <tên>] [--doc <id>]
  config.py         EvalConfig: gold_dir · output_root · report_dir · iou_threshold=0.5
  manifest.py       đọc gold/manifest.yaml -> DocEntry[]; giải mọi đường dẫn
  loader.py         đọc COCO -> EvalElement[]; đọc .docx/.md -> text thô; kiểm hệ toạ độ
  normalize.py      thang chuẩn hoá tiếng Việt; bóc markdown và anchor
  matching.py       ghép tham lam theo IoU trên từng (trang, category) -> MatchResult
  metrics/
    __init__.py
    layout.py       P/R/F1 @ IoU>=0.5 · mean IoU trên cặp đã ghép
    text.py         WER · CER (strict + tone-blind)
    table.py        TEDS · TEDS-Struct
  report.py         gộp -> results.json (máy đọc) + results.md (người đọc)
  gold/
    manifest.yaml                    ánh xạ nguồn <-> prediction <-> gold <-> text GT
    README.md                        config đã ghim + model tiền annotation
    <bucket>/<id>.coco.json          ground truth người sửa
  results/<run_id>/                  đầu ra
tests/
  test_normalize.py · test_loader.py · test_matching.py
  test_metrics_layout.py · test_metrics_text.py · test_metrics_table.py
```

`evaluate/main.py` và `evaluate/chandra.py` (0 byte) **xoá**. `__main__.py` thay chỗ `main.py`
để `python -m evaluate` chạy được; `chandra.py` không có nội dung nào để giữ và adapter Chandra
không thuộc phạm vi harness — nó thuộc `core/recognize/`.

---

## 5 · Mô hình dữ liệu

```python
@dataclass(frozen=True)
class EvalElement:
    """Một annotation COCO, rút gọn còn đúng những gì việc chấm điểm cần."""
    id: int
    page: int
    category: str                              # tên DocLayNet, không phải id số
    bbox: tuple[float, float, float, float]    # x, y, w, h — TƯƠNG ĐỐI [0,1]
    text: str | None                           # field mở rộng của COCO
    html: str | None                           # field mở rộng của COCO


@dataclass(frozen=True)
class Match:
    predicted: EvalElement
    gold: EvalElement
    iou: float


@dataclass(frozen=True)
class MatchResult:
    page: int
    matches: list[Match]
    false_positives: list[EvalElement]   # prediction không ghép được
    false_negatives: list[EvalElement]   # gold không ghép được
    unscoreable: bool                    # hệ toạ độ lệch — xem §5.1
```

`category` giữ dạng chuỗi chứ không phải `category_id` số, vì hai file COCO do hai lần chạy khác
nhau sinh ra **không đảm bảo đánh số category giống nhau**. `loader.py` map `category_id` qua
`categories[]` của chính file đó rồi mới so sánh bằng tên.

### 5.1 Hệ toạ độ — chuẩn hoá và bẫy

`loader.py` chia mọi bbox cho `images[].width` / `images[].height` của chính file đó, đưa về
toạ độ tương đối `[0,1]`. IoU khi đó **độc lập DPI**: gold vẽ ở 300 DPI vẫn chấm được prediction
render ở 200 DPI.

Bẫy còn lại nguy hiểm hơn nhiều. Cả hai phía đều sống trong *hệ chuẩn* của [staged §5.1], tức
**sau deskew**. Nếu gold được vẽ trên bản render có `deskew_angle = 1.4°` còn lần chạy đánh giá
cho `0.0°` vì `preprocess_steps` đổi, thì mọi bbox bị xoay tương đối với bản đối chiếu của nó và
IoU sụp xuống vì lý do **không liên quan gì tới detector**.

Quy tắc: `loader.py` so `page_geometry.deskew_angle` và `rotation_applied` giữa gold và
prediction. Lệch quá `0.1°` → đánh dấu trang `unscoreable = True`, đếm riêng trong report,
**không chấm**. Chấm sai còn tệ hơn không chấm, vì số sai vẫn trông như số.

Kéo theo một ràng buộc lên quy trình annotation ở §9: **gold được vẽ trên bản render hệ chuẩn**,
không phải trên trang PDF gốc.

### 5.2 Quy tắc cô lập stage

Đây là quyết định chịu lực của cả thiết kế:

> Gold element không ghép được (tức stage 3 bỏ sót) được tính vào **recall** của stage 3, và bị
> **loại khỏi mẫu số** của metric text và table ở stage 4.

Không có quy tắc này, một detector bỏ sót đoạn văn sẽ làm *recognizer* trông tệ, và "metric theo
từng bước" mất hết ý nghĩa — ta thu được một con số trộn lẫn đội ba cái tên. Có nó, mỗi stage
chịu trách nhiệm đúng phần của mình: stage 3 trả lời "có tìm ra không", stage 4 trả lời "đã được
đưa cho rồi thì đọc có đúng không".

Giá phải trả, phải nói rõ: **số của stage 4 là số có điều kiện** — điều kiện là những gì stage 3
tìm ra. CER 2% ở recall 60% **không** tốt hơn CER 5% ở recall 98%. Vì vậy `report.py` in hai khối
cạnh nhau và mọi bảng stage 4 mang chú thích trỏ lên recall của stage 3. Đây là quy ước bắt buộc,
không phải trang trí.

### 5.3 Tài liệu nào ghép với gì, trang nào được chấm

**Tra cứu theo `stem` là hỏng, ở cả hai chiều.** `Thông-tư-103-2026-TT-BTC.pdf` nằm trong **cả**
`high_quality_printed/` lẫn `low_quality_printed/` — hai file khác nhau, cùng tên, nên
`output/<stem>/` của [staged §6.3] va chạm giữa hai bucket. Chiều ngược lại cũng gãy: bản
handwritten chất lượng thấp tên `tonghopdon_lowquality.pdf` trong khi ground truth text của nó tên
`Tổng-hợp-đơn.md` — tra theo tên sẽ không ra.

Cả hai được giải bằng một file duy nhất, `evaluate/gold/manifest.yaml`:

```yaml
- id: tt103-high            # định danh ổn định, do người đặt; là khoá của mọi thứ khác
  bucket: high_quality_printed
  source: dataset/high_quality_printed/Thông-tư-103-2026-TT-BTC.pdf
  prediction: output/high_quality_printed/Thông-tư-103-2026-TT-BTC/
  gold_coco: gold/high_quality_printed/tt103-high.coco.json
  gold_text: ground_truth/printed/Thông-tư-103-2026-TT-BTC.docx
- id: tonghopdon-low
  bucket: low_quality_handwritten
  source: dataset/low_quality_handwritten/tonghopdon_lowquality.pdf
  prediction: output/low_quality_handwritten/tonghopdon_lowquality/
  gold_coco: gold/low_quality_handwritten/tonghopdon-low.coco.json
  gold_text: ground_truth/handwritten/Tổng-hợp-đơn.md      # dùng chung với bản high quality
```

Hệ quả về vận hành: pipeline phải chạy **một lần cho mỗi bucket** với `output_dir` riêng
(`./output/<bucket>`), nếu không thì `prediction` của hai bucket ghi đè lên nhau. Ghi vào
`gold/README.md` cùng config đã ghim.

`gold_text` được phép trùng nhau giữa nhiều entry — bản scan chất lượng cao và thấp của cùng một
văn bản có chung ground truth text, đó là điều làm cặp bucket đó có ý nghĩa so sánh.

**Chỉ chấm những trang có trong gold.** Gold subset là 8 trang **lấy mẫu** từ một tài liệu có thể
dài hàng trăm trang. `matching.py` lấy tập trang `= {images[].id}` của **file gold**, và bỏ qua
hoàn toàn mọi trang prediction ngoài tập đó.

Không có quy tắc này, ~200 trang không được annotate sẽ biến mọi prediction trên chúng thành false
positive, và precision của stage 3 tụt về gần 0 vì một lý do không liên quan gì tới detector. Đây
là kiểu lỗi tạo ra một con số trông hợp lệ và sai hoàn toàn — nguy hiểm hơn hẳn một exception.

**Ba trạng thái bất thường, ba cách xử lý khác nhau — không được gộp:**

| Tình huống | Xử lý |
| --- | --- |
| Thiếu hẳn file prediction cho một entry (pipeline chết trên tài liệu đó) | Entry **fail**, liệt kê trong report với lý do. **Không** im lặng bỏ qua — bỏ qua sẽ làm điểm trung bình đẹp lên nhờ đúng những tài liệu khó nhất |
| Trang có trong gold nhưng nằm trong `info.page_errors` của prediction ([staged §6.2] — pipeline lỗi trang đó, không có entry `images[]`) | Đếm vào cột **`n_page_errors` riêng**, loại khỏi mọi mẫu số. Trang pipeline **không xử lý được** khác về bản chất với trang detector **quét trượt**, và gộp chúng lại là xoá mất phân biệt đó |
| Trang có trong gold, có trong prediction, nhưng lệch hệ toạ độ (§5.1) | `unscoreable = True`, đếm riêng, không chấm |

---

## 6 · Ghép cặp

`matching.py`, trên từng trang, từng category:

1. Tính IoU cho mọi cặp (prediction, gold) cùng trang và cùng category.
2. Sắp giảm dần theo IoU. Duyệt tham lam, nhận cặp khi `IoU >= 0.5` và **cả hai** hộp chưa bị lấy.
3. Prediction còn lại là false positive, gold còn lại là false negative.

Tham lam chứ không phải Hungarian: ở ngưỡng 0.5, hai prediction chỉ cùng đạt `IoU >= 0.5` với một
gold khi chính chúng chồng nhau rất nặng — trường hợp hiếm, và khi đó lấy cái IoU cao hơn là lựa
chọn đúng. Đây cũng là cách COCO eval làm.

Ghép **theo category** nghĩa là: một hộp `text` dự đoán đè lên một hộp `caption` gold sẽ vừa là
false positive của `text`, vừa là false negative của `caption`. Đúng như vậy — đó là hai lỗi thật
đối với một metric per-category, và so hai dòng trong bảng là thấy ngay.

---

## 7 · Ba metric

### 7.1 Stage 3 · Layout — IoU

Trên từng category:

```
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
f1        = 2PR / (P + R)
mean_iou  = trung bình IoU TRÊN CÁC CẶP ĐÃ GHÉP
```

`mean_iou` tính **chỉ trên cặp đã ghép**, có chủ ý: hộp bị bỏ sót đã bị phạt ở `recall`, phạt nó
lần thứ hai bằng cách kéo tụt trung bình IoU là đếm một lỗi hai lần. Hai con số trả lời hai câu
khác nhau — `recall` là "có tìm ra không", `mean_iou` là "hộp có khít không".

Số headline lấy **micro-average** trên toàn bộ category (trọng số theo số element, nên `text` chi
phối — đúng với thực tế). **Không** lấy macro-average: với 2–3 công thức trong cả gold subset,
macro là nhiễu thuần tuý.

Mọi ô đều in kèm `n_gold`.

Mẫu số bằng 0 là chuyện sẽ xảy ra thật — `formula` vắng mặt ở nhóm handwritten là ví dụ. Quy ước:
`n_gold == 0` **và** `n_pred == 0` → **bỏ hẳn dòng đó khỏi bảng** (không có gì để nói). `n_gold == 0`
nhưng `n_pred > 0` → `recall` in `n/a`, `precision` in `0.0`, và dòng vẫn hiện — detector bịa ra một
category không tồn tại trên trang là thông tin đáng giá. Không bao giờ in `0.0` thay cho `n/a`:
hai thứ đó nghĩa khác nhau, và gộp chúng lại sẽ kéo tụt micro-average bằng những số không có thật.

Chiều ngược lại cũng phải giữ, và dễ sai hơn: khi **cả hai** mẫu số đều khác 0 mà không cặp nào
ghép được, `precision` và `recall` đều bằng `0.0` thật, nên `f1` phải in **`0.0`, không phải `n/a`**
(công thức `2PR/(P+R)` rơi vào `0/0`). Đó là một thất bại **đã đo được**, không phải một đại lượng
không đo. `mean_iou` thì vẫn là `n/a` vì không có cặp nào để lấy trung bình — hai ô cạnh nhau, hai
nghĩa khác nhau, đúng như vậy.

### 7.2 Stage 4 · Text — WER/CER

Áp dụng cho **cặp đã ghép** có category thuộc 8 lớp văn bản: `caption`, `footnote`, `list-item`,
`page-footer`, `page-header`, `section-header`, `text`, `title`. Không áp dụng cho `table`,
`picture`, `formula`.

```
CER = Σ levenshtein(pred_chars, gold_chars) / Σ len(gold_chars)
WER = như trên, token tách theo khoảng trắng
```

Tổng trên toàn corpus, **không phải trung bình của các tỉ lệ trên từng element**. Trung bình của
tỉ lệ cho một số trang 3 ký tự sai 1 ký tự (tỉ lệ 33%) trọng số ngang một đoạn văn 2000 ký tự.
Đây là lỗi thống kê thường gặp nhất khi báo cáo CER, và nó luôn làm số trông xấu hơn thực tế.

Báo cáo ba con số: **CER strict**, **CER tone-blind**, **WER strict**. Định nghĩa hai thang chuẩn
hoá ở §8.

Cặp có gold text rỗng bị loại khỏi mẫu số và đếm riêng thành `n_empty_gold` — nếu không thì chia
cho 0.

### 7.3 Stage 4 · Table — TEDS

Áp dụng cho cặp đã ghép có category `table`.

Cả hai chuỗi `html` được lxml parse thành cây node `(tag, colspan, rowspan, text)`. Chi phí theo
mô hình chuẩn của PubTabNet:

| Phép | Chi phí |
| --- | --- |
| Chèn / xoá một node | 1 |
| Đổi tên khi `tag` khác nhau | 1 |
| Đổi tên khi `tag` giống, `(colspan, rowspan)` khác | 1 |
| Đổi tên `<td>` khi `(colspan, rowspan)` khớp | edit distance chuẩn hoá của nội dung ô, trong `[0,1]` |

```
TEDS        = 1 - TED(pred, gold) / max(|pred|, |gold|)      # |·| = số node
TEDS-Struct = như trên, sau khi xoá trắng nội dung mọi ô
```

Hai chuẩn hoá cây trước khi so, cả hai đều là quyết định có chủ ý:

- **`<th>` quy về `<td>`.** Không recognizer bảng nào của pipeline phân biệt ô header một cách
  đáng tin. Phạt sự khác biệt đó là đo một năng lực ta không tuyên bố có.
- **Bỏ node `<thead>` / `<tbody>` khỏi cây.** Chúng không mang thông tin cấu trúc mà metric quan
  tâm, và [staged §5.3] nối `<tbody>` của bảng tràn trang — nếu giữ, phép nối đó tự sinh ra chênh
  lệch giả.

Gộp bằng **trung bình cộng trên các bảng** (TEDS đã chuẩn hoá theo từng bảng; cộng dồn không có
định nghĩa), luôn in kèm `n_tables` để 0.91 trên 4 bảng không bị đọc như một sự thật về corpus.

HTML dự đoán mà lxml từ chối parse → **TEDS = 0.0, liệt kê theo `Element.id` trong report**, không
bị loại bỏ. Loại bỏ chính là thưởng cho recognizer vì đã phát ra rác.

Lưu ý chiều: TEDS **cao là tốt**, CER/WER **thấp là tốt**. `results.md` ghi chiều ở đầu mỗi cột.

### 7.4 Document-level — metric phụ

Chỉ dùng theo dõi xu hướng, **không phải cổng chất lượng**.

- Phía dự đoán: `<stem>.md`, **cắt tại marker `<!-- ann-aside -->`**. Theo [staged §6.1] mọi
  element `render == "aside"` nằm dưới marker đó, nên một phép cắt chuỗi loại đúng và đủ phần
  header/footer chạy trang. Sau đó bóc anchor `<!-- ann:N -->` và cú pháp markdown.
- Phía gold: `.md` bóc markdown; `.docx` đọc bằng `python-docx`, lấy text của paragraph và của ô
  bảng theo thứ tự tài liệu.
- Chấm CER + WER thang strict.

Vì sao chỉ là xu hướng: quy ước tiêu đề và cách xử lý header/footer giữa `.docx` do người soạn và
`.md` do pipeline sinh khác nhau theo cách không phép chuẩn hoá nào xoá được. Con số này bắt được
hồi quy thảm hoạ (sập một bucket, mất nửa tài liệu), không bắt được chênh lệch vài phần trăm.

---

## 8 · Chuẩn hoá văn bản

Hai thang, cùng áp lên **cả hai phía** trước khi so.

**Thang strict** — theo đúng thứ tự:

1. Unicode **NFC**.
2. Bóc markdown: `#` tiêu đề, `-` đầu mục, `*`/`_` nhấn mạnh, comment `<!-- … -->`, thẻ HTML thô.
3. **Quy chuẩn vị trí dấu thanh tiếng Việt.** `hoà` và `hòa` đều là chính tả hợp lệ — kiểu cũ đặt
   dấu trên nguyên âm đầu (`hòa`), kiểu mới trên nguyên âm sau (`hoà`). Phạt một trong hai là đo
   người chép ground truth, không phải đo OCR. **Chiều quy chuẩn: về kiểu cũ** (`hoà` → `hòa`),
   vì đó là kiểu Unicode dựng sẵn và là kiểu đa số bàn phím tiếng Việt phát ra — chọn nó thì phép
   thay thế chạm vào ít ký tự hơn. Chiều nào cũng đúng miễn là **một** chiều; ghi ở đây để không
   ai đổi nửa chừng. Cài bằng một bảng thay thế cố định 15 cặp trên các cụm `oa`, `oe`, `uy`, áp
   sau NFC. Bảng cố định chứ không phải luật sinh — để đọc lại và kiểm được bằng mắt.

   **Hai chốt chặn, thiếu cái nào cũng làm hỏng chính tả đúng:**

   - **Âm tiết mở.** Biến thể chỉ tồn tại khi âm tiết **không có phụ âm cuối**. Có phụ âm cuối thì
     vị trí dấu là duy nhất: `khoản`, `hoạt`, `hoàng` chỉ có một cách viết, và áp bảng thay thế vào
     đó sẽ sinh ra `khỏan`, `họat`, `hòang` — sai hẳn. Điều kiện: cụm không được theo sau bởi một
     chữ cái.
   - **`qu` là phụ âm ghép.** Trong `qu` thì `u` là âm đệm, nên `quý`, `Quỳnh`, `quỵ` đã đúng sẵn ở
     cả hai kiểu. Không có chốt này, `uý → úy` sẽ biến `quý` thành `qúy`.
4. Gộp mọi chuỗi khoảng trắng thành một dấu cách; cắt hai đầu.

**Thang tone-blind** — thang strict, rồi:

5. NFD, **xoá đúng 5 dấu thanh**: U+0300 huyền, U+0301 sắc, U+0303 ngã, U+0309 hỏi, U+0323 nặng.
   **Giữ** U+0302 mũ (â ê ô), U+0306 trăng (ă), U+031B móc (ơ ư). **Giữ** `đ`. NFC lại.

Điểm 5 là lý do metric mang tên **tone-blind** chứ không phải "diacritic-blind": `ă`, `ơ`, `đ`
là **chữ cái khác**, không phải dấu thanh. Xoá chúng sẽ trộn lỗi đọc sai chữ vào lỗi đọc sai
thanh, đúng thứ mà metric này sinh ra để tách. Khoảng cách giữa `CER strict` và `CER tone-blind`
là **tỉ lệ lỗi thuần do dấu thanh** — con số hành động được nhất đối với một corpus tiếng Việt.

---

## 9 · Gold subset

**40 trang, 8 trang mỗi bucket.** Ràng buộc chọn: toàn bộ subset phải phủ `>= 10` bảng và `>= 3`
trang có `picture`. Bảng đến từ nhóm printed và `lpbank`; hai nhóm handwritten thực tế không có
bảng — xem §13 điểm 6.

Quy trình:

1. Chạy pipeline ở **config đã ghim**, **một lần cho mỗi bucket** với `output_dir=./output/<bucket>`
   (§5.3) → `output/<bucket>/<stem>/<stem>.coco.json`. Ghi `dpi`, `preprocess_steps` và model tiền
   annotation vào `evaluate/gold/README.md`.
2. Import COCO đó vào **Label Studio** — cấu hình rectangle label kèm field transcription theo từng
   region. Chọn Label Studio chứ không phải CVAT vì CVAT xử lý text theo từng hộp rất kém, mà ở đây
   text theo hộp chính là ground truth của §7.2.
3. Người sửa: hình học hộp, category, text element, HTML bảng.
4. Export COCO, **xoá các field chỉ có ở phía dự đoán** (`score`, `rec_score`, `logprob`,
   `reading_order`, `render`, `flags`), commit vào `evaluate/gold/<bucket>/`.

Ràng buộc từ §5.1: bước 1 render ở hệ chuẩn (sau deskew) và `page_geometry` của file gold **giữ
nguyên** giá trị của lần chạy đó. Đừng sửa tay.

Chi phí, nói thẳng: 40 trang ≈ 600 element văn bản. Người chỉ **sửa** bản chép của máy chứ không
gõ từ đầu, nên ước lượng 10–15 phút/trang → **8–10 giờ annotation**. Đây là giá thật của IoU và
của WER/CER mức element.

---

## 10 · Report

```
evaluate/results/<run_id>/
  results.json     đầy đủ, tới từng element — máy đọc, diff được giữa hai lần chạy
  results.md       đã gộp — người đọc
```

`run_id` do `__main__.py` truyền vào, không sinh bên trong hàm thuần, để `evaluate_dataset()` là
hàm tất định và test được.

`results.md`:

```
## Stage 3 · Layout            (IoU >= 0.5; P/R/F1/mIoU: cao là tốt)
| bucket | category | P | R | F1 | mIoU | n_gold |

## Stage 4 · Text              (CHỈ trên element đã ghép — đọc kèm recall ở bảng trên; thấp là tốt)
| bucket | CER | CER tone-blind | WER | n_elements | n_chars | n_empty_gold |

## Stage 4 · Table             (TEDS: cao là tốt)
| bucket | TEDS | TEDS-Struct | n_tables | n_unparseable |

## Document-level (phụ — xu hướng, không phải cổng)
| doc | CER | WER |

## Trang và tài liệu không chấm được          (§5.3 — ba loại, không gộp)
| doc | page | loại |     loại ∈ {pred_missing, page_error, coord_mismatch}
```

Khối cuối **luôn in, kể cả khi rỗng** (khi đó in "không có"). Một bảng bị ẩn lúc rỗng sẽ khiến
người đọc không phân biệt được "không có tài liệu nào hỏng" với "phần đó không được kiểm".

---

## 11 · Test

Fixture là **COCO JSON viết tay**, nên toàn bộ suite chạy được hôm nay, không cần `core/layout/`
hay `core/recognize/` tồn tại.

| File | Ca phải có |
| --- | --- |
| `test_normalize.py` | `hoà`/`hòa` quy về cùng một chuỗi · NFD vào ra NFC · bóc anchor + markdown · tone-blind **giữ** `ă ơ đ` và **xoá** 5 dấu thanh |
| `test_manifest.py` | hai entry cùng `stem` khác `bucket` giải ra hai `prediction` khác nhau · hai entry dùng chung một `gold_text` · thiếu file prediction → entry `pred_missing`, **không** bị bỏ qua |
| `test_loader.py` | `category_id` khác nhau giữa hai file vẫn map đúng theo tên · lệch `deskew_angle` → trang `unscoreable`, không chấm · trang trong `info.page_errors` → `page_error`, loại khỏi mẫu số |
| `test_matching.py` | hai prediction cùng phủ một gold ở IoU 0.6/0.7 → lấy 0.7, cái còn lại thành FP · cặp dưới ngưỡng → FP + FN chứ không phải match yếu · **prediction trên trang vắng mặt trong gold bị bỏ qua, không thành FP** (§5.3) |
| `test_metrics_layout.py` | hộp bỏ sót hạ `recall` nhưng **không** hạ `mean_iou` · `n_gold == 0` và `n_pred == 0` → dòng biến mất · `n_gold == 0` và `n_pred > 0` → `recall` là `n/a`, không phải `0.0` |
| `test_metrics_text.py` | CER/WER khớp giá trị tính tay · gộp corpus-level **khác** trung bình-của-tỉ-lệ trên một cặp cố tình lệch |
| `test_metrics_table.py` | bảng giống hệt → TEDS 1.0 · đổi nội dung một ô → TEDS < 1.0 nhưng TEDS-Struct == 1.0 · HTML hỏng → 0.0 và có mặt trong danh sách liệt kê |

---

## 12 · Dependency delta

| Thêm | Vì sao không tránh được |
| --- | --- |
| `rapidfuzz` | Levenshtein cho WER/CER. CER document-level so hai chuỗi ~100k ký tự; DP thuần Python là O(n·m) ≈ 10¹⁰ phép. Bản bit-parallel của rapidfuzz làm trong khoảng một giây |
| `apted` | Tree edit distance cho TEDS. Thuần Python, không kéo theo dependency nào. Tự viết Zhang-Shasha ~150 dòng được, nhưng khi đó TEDS hết so sánh được với số đã công bố — đúng thứ khiến ta chọn TEDS ngay từ đầu |
| `python-docx` | Đọc 3 file ground truth `.docx` |

`lxml` không nằm trong bảng vì [staged §10.1] đã đưa nó vào `core/`.

---

## 13 · Sáu điều phải nói thẳng

1. **Harness chỉ thấy đầu ra stage 6.** Một element bị đánh rơi im lặng ở stage 5 hiện ra thành
   false negative của stage 3. Đây là cái giá đã biết của kiến trúc file-vào-file-ra ở §2, và nó
   được trả bằng việc harness dựng được trước khi refactor xong.

2. **Gold có máy hỗ trợ nên thừa hưởng điểm mù của máy.** Một lỗi hệ thống mà cả model tiền
   annotation lẫn hệ đang đo cùng mắc sẽ được chấm là đúng. Giảm thiểu bằng một ràng buộc cứng:
   **model tiền annotation phải khác hệ đang được đo**. Ghi model đã dùng vào
   `evaluate/gold/README.md`.

3. **40 trang là nhỏ.** `formula` và `caption` sẽ có `n < 20`. Vì thế mọi bảng in kèm `n`, và số
   per-category của lớp hiếm đọc theo hướng chứ không đọc theo giá trị.

4. **Không đo thứ tự đọc trong v1.** [staged §9 điểm 2] tự nhận XY-cut là chỗ yếu nhất của thiết
   kế, và v1 để nó không được đo — có chủ ý, theo phạm vi đã chốt. CER document-level bắt được
   xáo trộn thảm hoạ, không bắt được hai đoạn đảo chỗ.

5. **CER document-level là đường xu hướng, không phải cổng.** Xem §7.4.

6. **Hai bucket handwritten không có bảng**, nên TEDS không nói gì về chữ viết tay. Số TEDS luôn
   thuộc về printed và `lpbank`, và report chia theo bucket chính là để điều đó không bị đọc nhầm
   thành một con số toàn corpus.

---

## 14 · Thứ tự implement

1. `normalize.py` + test — không phụ thuộc gì, chốt được ngay.
2. `manifest.py` + `gold/manifest.yaml` cho 5 entry đầu + test. Làm trước `loader.py` vì mọi đường
   dẫn khác đi qua nó, và vì nó ép phải chạy pipeline theo từng bucket (§5.3) — thứ phải biết
   trước khi sinh prediction, không phải sau.
3. `loader.py` + `matching.py` + test trên fixture COCO viết tay. **Bước này chốt schema gold**;
   annotation ở §9 chỉ được bắt đầu sau khi bước này xong, nếu không sẽ phải annotate lại.
4. `metrics/layout.py` + test.
5. `metrics/text.py` + test.
6. `metrics/table.py` + test.
7. `report.py` + `__main__.py`; xoá `evaluate/main.py` và `evaluate/chandra.py`.
8. Annotation gold subset — chạy song song, khởi động sau bước 3.

Số đo thật đầu tiên xuất hiện khi `core/layout/` và `core/recognize/` của [staged §12] hạ cánh.
Trước đó harness chạy trên fixture và trên gold, và đó đã đủ để khẳng định harness đúng.
