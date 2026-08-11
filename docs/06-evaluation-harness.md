# Cấu phần 6 - Bộ đo chất lượng (`evaluate/`)

Nguồn gốc (đã xoá, nội dung gộp vào đây): `superpowers/specs/2026-08-08-ocr-evaluation-metrics-design.md`
(thiết kế v1, dựa trên COCO) + `superpowers/specs/2026-08-11-evaluate-pairing-and-table-scoring-design.md`
(hoàn thiện pairing report + thêm đường chấm bảng document-level vì COCO chưa tồn tại) +
`superpowers/plans/2026-08-11-evaluate-pairing-and-table-scoring-plan.md` (kế hoạch implement, gộp tắt).
Phạm vi: package `evaluate/`. **Không sửa `core/`.**

## Quyết định nền

Harness là **file vào, file ra** - `evaluate/` không import `core/`. Lý do: pipeline đang giữa đợt refactor
6-stage ([Cấu phần 4](04-core-pipeline-staged.md)); một harness bám nội bộ `core/` lúc này sẽ viết lại giữa
chừng. Input là `output/<stem>/<stem>.coco.json` đối chiếu `evaluate/gold/<bucket>/<stem>.coco.json` (mọi
thứ ba metric cần đều nằm trong file COCO đó: `bbox`+`category_id` cho IoU, field mở rộng `text` cho
WER/CER, field mở rộng `html` cho TEDS).

**Thực tế đo được (2026-08-11): không có file `.coco.json` nào tồn tại trên đĩa, và không công cụ nào ngoài
`tests/` sinh ra nó** - `core/serialize/coco.py` chưa được nối vào entry point nào, code cũ (`core/pipeline.py`)
chỉ ghi `.md` **hoặc** `.json`, không bao giờ cả hai. Vì vậy đường Layout (IoU) và một phần đường Table
(qua COCO) ở thiết kế v1 **chưa chạy được trên dữ liệu thật**, chỉ chạy được trên fixture COCO viết tay. Để
không phải chờ [Cấu phần 4](04-core-pipeline-staged.md) hoàn thành, một đường **document-level** (đọc trực
tiếp `.md`/`.docx`) được thêm song song cho riêng metric Table - đây là đường **đang chạy thật** hôm nay.

## Ba metric, ba stage

| Stage | Metric | Trạng thái |
| --- | --- | --- |
| Stage 3 Layout | IoU (P/R/F1/mIoU) | Thiết kế xong, **chờ COCO producer** - chạy được trên fixture, chưa trên dữ liệu thật |
| Stage 4 Text | WER/CER (strict + tone-blind), mức element (COCO) + mức document (`.md`/`.docx`) | Mức document **đang chạy thật** |
| Stage 4 Table | TEDS/TEDS-Struct, qua COCO (`score_tables`, giữ nguyên không đổi) **hoặc** document-level (`pair_tables`/`score_table_pairs`, mới) | Đường document-level **đang chạy thật** |

Không đo trong v1: stage 1/2/6 (plumbing tất định, test đơn vị bắt lỗi đủ), stage 5 thứ tự đọc (CER
document-level chỉ bắt xáo trộn thảm hoạ, không bắt hai đoạn đảo chỗ), nội dung LaTeX (chỉ bbox `formula`
được chấm IoU như các category khác).

## Quy tắc cô lập stage (chịu lực của cả thiết kế)

> Gold element không ghép được (stage 3 bỏ sót) được tính vào **recall** của stage 3, và bị **loại khỏi
> mẫu số** của metric text/table ở stage 4.

Không có quy tắc này, detector bỏ sót đoạn văn sẽ làm recognizer trông tệ - "metric theo từng bước" mất ý
nghĩa. Cái giá: số của stage 4 là **số có điều kiện** - CER 2% ở recall 60% không tốt hơn CER 5% ở recall
98%. Report luôn in hai khối cạnh nhau và chú thích rõ.

**Trang nào được chấm:** tra cứu theo `stem` là hỏng ở cả hai chiều (một PDF trùng tên nằm ở hai bucket
khác nhau; ground truth text khác tên file nguồn) → giải bằng một `gold/manifest.yaml` ánh xạ
`id ↔ source ↔ prediction ↔ gold_coco ↔ gold_text`. Chỉ chấm những trang **có trong gold** (gold là mẫu 8
trang/bucket, không phải toàn bộ tài liệu) - nếu không, hàng trăm trang chưa annotate sẽ biến mọi prediction
trên chúng thành false positive giả.

Ba trạng thái bất thường, không được gộp: **thiếu hẳn prediction** (entry fail, liệt kê rõ lý do, không im
lặng bỏ qua) · **trang nằm trong `info.page_errors` của prediction** (đếm riêng `n_page_errors`, loại khỏi
mẫu số - khác về bản chất với detector quét trượt) · **lệch hệ toạ độ** (`deskew_angle`/`rotation_applied`
khác giữa gold và prediction quá 0,1° → `unscoreable=True`, không chấm - chấm sai còn tệ hơn không chấm).

## Metric 1 - Layout (IoU)

Ghép tham lam theo IoU trên từng `(trang, category)`: sort giảm dần, nhận cặp khi `IoU >= 0.5` và cả hai
hộp chưa bị lấy (tham lam, không Hungarian - đủ đúng ở ngưỡng 0.5, và là cách COCO eval làm).
`precision/recall/f1` chuẩn; `mean_iou` chỉ tính **trên cặp đã ghép** (phạt hộp bỏ sót ở recall, không phạt
lần hai ở mean_iou). Micro-average trên toàn category (không macro - với 2-3 công thức trong gold subset,
macro là nhiễu thuần). Quy ước mẫu số 0: `n_gold=0 & n_pred=0` → bỏ dòng; `n_gold=0 & n_pred>0` → `recall`
in `n/a` (không phải `0.0`); cả hai mẫu số khác 0 mà không cặp nào ghép được → `precision`/`recall`/`f1`
đều `0.0` thật (không phải `n/a`), riêng `mean_iou` là `n/a`.

## Metric 2 - Text (WER/CER)

Áp dụng cho 8 category văn xuôi (`caption, footnote, list-item, page-footer, page-header, section-header,
text, title`), không áp dụng cho `table`/`picture`/`formula`.

```
CER = Σ levenshtein(pred_chars, gold_chars) / Σ len(gold_chars)   # tổng CORPUS, không phải trung bình tỉ lệ
```

Báo cáo ba con số: CER strict, CER tone-blind, WER strict. Cặp gold text rỗng loại khỏi mẫu số, đếm riêng
`n_empty_gold`.

**Chuẩn hoá strict** (áp cả hai phía, theo thứ tự): NFC → bóc markdown (tiêu đề, đầu mục, nhấn mạnh,
comment, HTML thô) → **quy chuẩn vị trí dấu thanh tiếng Việt về kiểu cũ** (`hoà`→`hòa`, bảng thay thế cố
định 15 cặp trên cụm `oa/oe/uy`, có 2 chốt chặn: chỉ áp khi âm tiết mở - không phụ âm cuối - và không áp
trong `qu` vì `u` là âm đệm) → gộp khoảng trắng. **Chuẩn hoá tone-blind** = strict + NFD, xoá đúng 5 dấu
thanh (huyền/sắc/ngã/hỏi/nặng), **giữ** `â ê ô ă ơ ư đ` (là chữ cái khác, không phải dấu thanh) → NFC lại.
Khoảng cách CER strict - CER tone-blind là tỉ lệ lỗi thuần do dấu thanh.

## Metric 3 - Table (TEDS)

Cả hai chuỗi HTML parse bằng `lxml` thành cây `(tag, colspan, rowspan, text)`. Chi phí theo mô hình
PubTabNet chuẩn (đổi tag = 1, đổi span = 1, đổi nội dung `<td>` cùng span = edit distance chuẩn hoá `[0,1]`).

```
TEDS = 1 - TED(pred, gold) / max(|pred|, |gold|)          # số node
TEDS-Struct = như trên, sau khi xoá trắng nội dung ô
```

Chuẩn hoá cây trước khi so: `<th>` quy về `<td>` (không recognizer nào phân biệt header đáng tin) · bỏ
`<thead>`/`<tbody>` khỏi cây (không mang thông tin cấu trúc, và phép nối bảng tràn trang ở
[Cấu phần 4](04-core-pipeline-staged.md) §4.3 sẽ tự sinh chênh lệch giả nếu giữ). Gộp bằng trung bình cộng
trên các bảng, luôn kèm `n_tables`. HTML không parse được → **TEDS = 0.0, liệt kê theo id**, không bị loại
bỏ (loại bỏ là thưởng cho recognizer vì phát ra rác). TEDS cao là tốt, CER/WER thấp là tốt.

### Bug đã sửa: `teds()` trả giá trị âm

`table.py:96` tính `1.0 - distance/largest`; APTED có thể cho `distance > max_nodes` dưới cost model
PubTabNet, ra kết quả âm - trái với docstring "normalized to `[0,1]`". Đo được trên dữ liệu thật:
`1202.PGV.2026(1)` gold-table-0 vs predicted-table-1 → TEDS = **-0,0409**. Sửa: `max(0.0, 1 - distance/largest) if largest else 1.0`.
Không test nào phụ thuộc giá trị âm, an toàn để clamp.

### Chấm bảng document-level (đường đang chạy thật, không qua COCO)

Module mới `evaluate/table_extract.py`: `extract_html_tables(text)` (đọc cả `<table>` embedded lẫn
markdown pipe table, theo **đúng thứ tự trong tài liệu** - thứ tự này chính là `predicted_index`/`gold_index`
dùng để ghép cặp) và `extract_docx_tables(path)` (qua `walk_docx_cells`, KHÔNG dùng API `row.cells` của
python-docx vì nó trả text của ô gộp dọc **một lần mỗi hàng nó trải qua** - đo được 8/18 vị trí là alias
trên bảng thật; đọc thẳng `tr.tc_lst` + thuộc tính `vMerge_val` mới đúng, `"restart"`=bắt đầu span,
`"continue"`=bỏ qua, `None`=ô thường không gộp).

Pairing (`pair_tables`): tính cả TEDS-Struct và TEDS đầy đủ cho mọi cặp, sort giảm dần theo
**(TEDS-Struct, TEDS đầy đủ, index)** - TEDS đầy đủ làm khoá phụ là **bắt buộc**, không phải tinh chỉnh:
trên `tonghopdon`, ma trận 7×7 TEDS-Struct cho đúng `1.00` ở mọi cặp cùng kích thước (3 bảng 10×5, 4 bảng
4×3), chỉ TEDS đầy đủ (đường chéo 0,97-1,00 vs ngoài đường chéo 0,59-0,85) mới ghép đúng cả 7. Ngưỡng sàn
`>= 0.5` áp trên TEDS-Struct. Một cặp qua sàn vẫn có thể điểm TEDS đầy đủ thấp - **báo cáo, không lọc**:
sàn quyết định "bảng nào khớp bảng nào", điểm đầy đủ sau đó nói "đọc đúng đến đâu".

`table_recall = n_matched / n_gold` - bắt buộc đi kèm `teds` trung bình để không bị "chơi": phát 1 bảng
hoàn hảo, bỏ hết phần còn lại, vẫn ra điểm 1.0 nếu chỉ nhìn TEDS. `table_recall` là `None` (không phải
`0.0`) khi pairing bị bỏ qua vì vượt trần chi phí (`N*M > 2000` cặp APTED). Năm trạng thái `(n_gold, n_pred)`
render khác nhau, kể cả trường hợp **không có file gold** (khác về bản chất với "gold có, không có bảng
nào") - 7/13 tài liệu lpbank rơi vào đúng trường hợp này.

## Hoàn thiện báo cáo pairing (không liên quan bảng)

- Báo cáo tài liệu không ghép được cặp **ở cả hai chiều**: gold không có prediction (đã có) + prediction
  không có gold (trước đây chỉ là ghi chú per-document, nay thành bảng riêng ở section pairing).
- Hai prediction trùng `doc_id` (setting `output_dir` chung khiến `tonghopdon.md` xuất hiện ở cả hai bucket)
  → raise `PairingError` thay vì âm thầm rơi mất một bản - lỗi cấu hình, không phải thứ nên đoán.

## Bug đã sửa: docx gold đếm ô gộp hai lần

`ground_truth.py:91` dùng `row.cells` - cùng cạm bẫy API như trên, một ô gộp dọc bị tính text **hai lần**
(đo được trên `Thông-tư-103-2026-TT-BTC.docx`: hai chuỗi xuất hiện 2 lần dù chỉ có 1 lần trên trang thật).
Sửa bằng `walk_docx_cells` dùng chung với table_extract. **Chưa ảnh hưởng điểm số nào đã báo cáo** - chưa
có prediction nào cho 3 file docx printed, và không config nào trỏ `ground_truth_dir` vào đó - nhưng sửa
ngay vì dùng chung primitive với bug bảng ở trên.

## Cây module

```
evaluate/
  __init__.py       evaluate_document(), evaluate_dataset(), evaluate_engine()
  __main__.py / run.py   CLI
  config.py         EvalConfig: gold_dir, output_root, iou_threshold=0.5, table_threshold=0.5
  manifest.py       gold/manifest.yaml -> DocEntry[]
  ground_truth.py   đọc .docx/.md gold -> text (dùng walk_docx_cells cho docx)
  loader.py         đọc COCO -> EvalElement[]; kiểm hệ toạ độ
  normalize.py      chuẩn hoá strict/tone-blind, bóc markdown/anchor
  matching.py       ghép tham lam IoU theo (trang, category)
  table_extract.py  extract_html_tables, extract_docx_tables, walk_docx_cells
  metrics/
    layout.py       IoU P/R/F1/mIoU
    text.py         WER/CER
    table.py        parse_table, teds(), score_tables() [COCO, giữ nguyên] + pair_tables/score_table_pairs [document-level, mới]
  report.py         results.json (máy đọc) + results.md (người đọc)
  gold/manifest.yaml, gold/<bucket>/<id>.coco.json
tests/
```

`evaluate/main.py` và `evaluate/chandra.py` (0 byte, không có nội dung) - **xoá**, thay bằng `run.py`/`__main__.py`.

## Gold subset

40 trang, 8 trang/bucket, phủ ≥10 bảng và ≥3 trang có `picture`. Quy trình: chạy pipeline ở config đã ghim
→ import COCO vào Label Studio (chọn thay CVAT vì CVAT xử lý text theo hộp rất kém) → người sửa hình
học/category/text/HTML bảng → export, xoá field chỉ có ở phía dự đoán (`score, rec_score, logprob,
reading_order, render, flags`) → commit. **Model tiền annotation phải khác hệ đang được đo** - nếu không,
lỗi hệ thống chung sẽ được chấm là đúng. Ước lượng chi phí: 8-10 giờ annotation cho 40 trang ≈ 600 element.

## Report

```
results/<run_id>/results.json + results.md
## 3 · Layout (IoU)
## 4 · Tables (pairing floor >= <threshold>)
## 5 · Not measured (5.1 per-doc note · ... · 5.4 unpaired cả hai chiều)
## Document-level CER/WER (phụ - xu hướng, không phải cổng)
## Trang/tài liệu không chấm được (pred_missing / page_error / coord_mismatch - luôn in, kể cả rỗng)
```

## Sáu điều phải nói thẳng

1. Harness chỉ thấy đầu ra stage 6 - element bị đánh rơi âm thầm ở stage 5 hiện ra thành false negative của
   stage 3. Cái giá đã biết của kiến trúc file-vào-file-ra, đổi lại harness dựng được trước khi
   [Cấu phần 4](04-core-pipeline-staged.md) xong.
2. Gold có máy hỗ trợ nên thừa hưởng điểm mù của máy - giảm thiểu bằng ràng buộc model tiền annotation khác
   hệ đang đo.
3. 40 trang là nhỏ - `formula`/`caption` sẽ có `n < 20`, mọi bảng in kèm `n`.
4. Không đo thứ tự đọc trong v1 (điểm yếu nhất của [Cấu phần 4](04-core-pipeline-staged.md) §9 điểm 2).
5. CER document-level là đường xu hướng, không phải cổng chất lượng.
6. Hai bucket handwritten không có bảng - TEDS không nói gì về chữ viết tay, report chia theo bucket để
   tránh đọc nhầm thành một con số toàn corpus.
7. **(mới)** 7/13 tài liệu lpbank không có ground truth - 199 bảng của `2001.SOL.2026(1)` không phải 199
   bảng sai, mà là **không chấm được**; báo cáo phải phân biệt rõ `not scoreable - no ground truth` với
   `0 gold tables`.

## Dependency

`rapidfuzz` (Levenshtein bit-parallel cho CER document-level ~100k ký tự) · `apted` (tree edit distance cho
TEDS - thuần Python nhưng đã kiểm chứng khớp số công bố, tự viết Zhang-Shasha sẽ mất khả năng so sánh đó) ·
`python-docx` · `lxml` (khai báo trực tiếp trong `requirements.txt`, trước đây chỉ đến gián tiếp qua
python-docx nên một bản cài "chạy được" là ăn may).

## Thứ tự implement (đã làm / còn lại)

1. `normalize.py` → 2. `manifest.py` (ép chạy pipeline theo từng bucket) → 3. `loader.py` + `matching.py`
(chốt schema gold trước khi annotate) → 4-6. ba module `metrics/` → 7. `report.py`, xoá file rỗng →
8. annotation gold subset (song song). Riêng phần document-level table scoring (2026-08-11): clamp `teds()`
(bug fix, viết test fail trước) → `table_extract.py` → sửa `ground_truth.py` → pairing + scoring → config
threshold → report renumber (section 4→5) → wire `evaluate_engine` → CLI → dependency + docs. Số đo thật
đầu tiên cho Layout/IoU xuất hiện khi `core/layout/` và `core/recognize/` của Cấu phần 4 hạ cánh.
