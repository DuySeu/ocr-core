# Đặc tả yêu cầu — Hệ thống OCR self-host 2 triệu trang tài liệu tiếng Việt

Ngày: 2026-08-06
Trạng thái: Phân tích yêu cầu — chưa implement
Mục đích sử dụng: **nghiên cứu**, không thương mại
Kiến trúc cơ sở: OCR cổ điển (layout + detection + recognition + table + formula). §1.3 có thêm option phá ràng buộc này, đã đánh dấu rõ.

---

## Context

Cần OCR 2 triệu trang PDF-scan (~0,4 TB) tiếng Việt, self-host, sinh **đồng thời** hai output từ một lần chạy:


| Output         | Mục đích                                        |
| -------------- | ----------------------------------------------- |
| `.md`          | Phục vụ tra cứu                                 |
| `.json` (COCO) | Trích xuất thông tin, kiểm định, huấn luyện lại |


Bốn loại phần tử phải bóc tách riêng: **text** → text, **ảnh** → bbox + link ảnh, **bảng** → HTML, **công thức** → LaTeX. Mọi phần tử cần bounding box và một tín hiệu bất định đi kèm.

Tín hiệu bất định dùng **log-probability**, không dùng "confidence score".

Tài liệu này chia bài toán thành ba khối:

- **Phần I** — Model OCR cần đáp ứng những gì (tiêu chí lựa chọn + số liệu benchmark)
- **Phần II** — Phần code **không phụ thuộc** model (làm được ngay, song song với research)
- **Phần III** — Phần code **tiêu thụ output** của model (phụ thuộc format, nhưng không phụ thuộc chất lượng model)

---



## Kết luận ngắn

Chỉ **6 hạng mục phụ thuộc model**, **13 hạng mục là code**.

Vì đây là dự án nghiên cứu, ràng buộc license được nới → mở ra **Marker 2**, **Surya 2**, **Chandra OCR 2** (OpenRAIL-M, miễn phí cho nghiên cứu) vốn trước đây bị loại. Marker 2 đã sinh sẵn Markdown + JSON kèm bbox, confidence, LaTeX, bảng, ảnh — tức làm gần hết Phần III.

Sau khi áp ngưỡng **chữ viết tay ≥ 50% (M7)**, toàn bộ nhánh recognizer của Tesseract và PP-OCR bị loại. Còn **6 option**, trong đó chỉ **STT 1 (VietOCR) có số tiếng Việt đo được**; 5 option còn lại chưa ai công bố số tiếng Việt — xem cảnh báo ở §1.3.1.

Đánh đổi cốt lõi: **VietOCR là option duy nhất có bằng chứng tiếng Việt; Marker 2 có ROI kỹ thuật tốt nhất; PaddleOCR-VL 1.6 đáp ứng nhiều tiêu chí mong muốn nhất và là Apache-2.0.**

Hạ tầng: **~192 GPU-giờ** cho toàn bộ 2M trang, dù đi đường PP-StructureV3 (A100, 4 process) hay Marker 2 (B200, 2,9 trang/s).

---



# PHẦN I — Model OCR cần đáp ứng những yêu cầu gì



## 1.1 Tiêu chí BẮT BUỘC (loại nếu không đạt)


| #   | Yêu cầu                                              | Vì sao bắt buộc                                                | Cách kiểm chứng                     |
| --- | ---------------------------------------------------- | -------------------------------------------------------------- | ----------------------------------- |
| M1  | **Self-host offline hoàn toàn**, không gọi API ngoài | 0,4 TB tài liệu không được rời hệ thống                        | Chạy thử với network disabled       |
| M2  | **Tiếng Việt có dấu** trong tập ký tự huấn luyện     | Yêu cầu lõi                                                    | Số liệu benchmark ở §1.3.3          |
| M3  | **Trả bounding box** cho mọi phần tử                 | Yêu cầu lõi + là input của COCO                                | Kiểm tra field output               |
| M4  | **Bảng → HTML** giữ được merged cell                 | GFM table không biểu diễn được rowspan/colspan                 | Test trên bảng có ô gộp             |
| M5  | **Công thức → LaTeX**                                | Yêu cầu lõi                                                    | Test compile bằng KaTeX             |
| M6  | **Chạy được trên GPU đơn ≤ 24 GB VRAM**              | Ràng buộc chi phí ở quy mô 2M trang                            | Đo VRAM đỉnh                        |
| M7  | **Độ chính xác chữ viết tay ≥ 50%**                  | Corpus có chữ ký, ghi chú tay, bút phê trên văn bản hành chính | CER viết tay từ benchmark bên thứ 3 |




## 1.2 Tiêu chí MONG MUỐN (chấm điểm, không loại)


| #   | Yêu cầu                                          | Giá trị                                                                                                                       |
| --- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| M8  | **License cho phép dùng thương mại**             | Là mong muốn vì dự án dùng cho nghiên cứu. Vẫn nên ưu tiên license permissive để không khoá đường nếu sau này đổi mục đích    |
| M9  | **Truy cập được logits / per-token probability** | Là mong muốn vì một số model đã trả sẵn per-token probability tổng hợp (Surya, Marker) — đủ dùng mà không cần patch inference |
| M10 | Reading order do model dự đoán                   | Đỡ phải viết rule XY-cut; rule sai trên layout nhiều cột                                                                      |
| M11 | Nhận dạng bảng **không kẻ khung** (borderless)   | Tài liệu hành chính VN dùng nhiều                                                                                             |
| M12 | Nhận dạng con dấu / chữ ký                       | Đặc thù văn bản hành chính VN                                                                                                 |
| M13 | Fine-tune được với chi phí hợp lý                | Kế hoạch dự phòng nếu CER không đạt                                                                                           |
| M14 | Có export ONNX / OpenVINO                        | Mở đường chạy CPU khi thiếu GPU                                                                                               |
| M15 | Xử lý được ảnh nghiêng, mờ, photocopy            | Chất lượng scan thực tế                                                                                                       |




## 1.3 Bảng option

**Mọi option dưới đây đạt 100% tiêu chí bắt buộc M1–M7.**

⚠ = phá ràng buộc "không dùng VLM" ở đầu tài liệu.

### 1.3.1 Các option đạt chuẩn


| STT  | Tên model                                      | Độ chính xác OCR tiếng Việt (%)                                                                        | Tiêu chí mong muốn đạt được                                               |
| ---- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| 1 ⭐  | **PP-StructureV3 + VietOCR** (thay recognizer) | Chữ in **98,6%** · viết tay **68,2%** *(bên thứ 3, 2026-05-01)* Hoá đơn **70–78%** *(MC-OCR hạng 1–4)* | M9, M10, M11, M12, M13, M14, M15 *(M8 chưa kiểm chứng — license VietOCR)* |
| 2 ⭐  | **Marker 2** (nền Surya 2)                     | **73,2%** pass rate, không tách chữ in / viết tay *(nhà cung cấp, per-language, 32.055 test)*          | M9, M10, M11, M15                                                         |
| 3 ⭐⚠ | **PaddleOCR-VL 1.6**                           | **Chưa công bố số VI** VI xác nhận trong 109 ngôn ngữ (nhóm Latin), có hỗ trợ chữ viết tay             | M8, M9, M10, M11, M12, M13, M15                                           |
| 4 ⚠  | **Chandra OCR 2** (4B)                         | **Chưa công bố số VI** Nhà cung cấp nêu rõ có xử lý chữ viết tay                                       | M9, M10, M11, M15                                                         |
| 5    | **Surya 2** (dùng trực tiếp)                   | **73,2%** pass rate, không tách chữ in / viết tay *(nhà cung cấp, per-language)*                       | M9, M10, M11, M15                                                         |
| 6 ⚠  | **MinerU 2.5**                                 | **Chưa công bố số VI** VI nằm trong 84 ngôn ngữ                                                        | M8, M9, M10, M11, M15                                                     |


### 1.3.2 Đánh đổi giữa ba ứng viên đầu bảng


|                       | **1** - PP-StructureV3 + VietOCR                                                                                                                                                                | **2** - Marker 2                                 | **3** - PaddleOCR-VL 1.6                      |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | --------------------------------------------- |
| Bằng chứng tiếng Việt | **Trực tiếp, CER thật, 3 nguồn độc lập**                                                                                                                                                        | 73,2% pass rate, thấp hơn TB 91 ngôn ngữ 14 điểm | Không có số VI; chỉ xác nhận VI trong charset |
| Chữ viết tay          | **68,2% - đo được**                                                                                                                                                                             | Chưa ai đo                                       | Chưa ai đo                                    |
| Tiêu chí mong muốn    | 7/8                                                                                                                                                                                             | 4/8                                              | **7/8**                                       |
| License               | Paddle Apache-2.0; VietOCR chưa rõ                                                                                                                                                              | OpenRAIL-M (chỉ nghiên cứu)                      | **Apache-2.0**                                |
| Output cần build      | Toàn bộ Phần IIIọc M7 nó là option duy nhất có số tiếng Việt đo được ở cả chữ in và viết tay, và nó thoả 7/8 tiêu chí mong muốn. Đây là lựa chọn dựa trên bằng chứng, không dựa trên suy luận. |                                                  |                                               |


**STT 2 (Marker 2) đáng chạy song song** vì nó làm sẵn gần hết Phần III và nhanh hơn. Nếu số tiếng Việt thực tế của nó đạt yêu cầu thì tiết kiệm được rất nhiều công. Nếu không đạt, vẫn dùng được ở dạng lai: Marker cho layout/bảng/công thức, VietOCR cho text — định tuyến bằng confidence per-block mà Marker trả sẵn.

**STT 3 (PaddleOCR-VL 1.6) là lựa chọn tốt nhất nếu chấp nhận VLM**: Apache-2.0, 7/8 tiêu chí mong muốn, chỉ ~2 GB VRAM. Nhưng phải tự đo tiếng Việt.

Cảnh báo: chưa kiểm chứng được việc **thay recognizer bên trong Marker** dễ hay khó — phải đọc code Marker trước khi cam kết đường lai.

### 1.3.3 Số liệu benchmark tiếng Việt của các option

**STT 1 - VietOCR** · benchmark bên thứ 3, đo 2026-05-01


| Tập test                                              | Kết quả                |
| ----------------------------------------------------- | ---------------------- |
| Chữ in - 40-70 ảnh PNG **tổng hợp**                   | CER 1,41% → **98,6%**  |
| Viết tay - 200 ảnh `brianhuster/VietnameseOCRdataset` | CER 31,82% → **68,2%** |
| Tốc độ                                                | 240 ms/dòng            |


**STT 1 — VietOCR** · MC-OCR Challenge, hoá đơn tiếng Việt, bảng xếp hạng thi đấu


| Hạng | Team          | CER  | Kiến trúc                                   |
| ---- | ------------- | ---- | ------------------------------------------- |
| 1    | DataMining VC | 0,22 | Yolov5 + **VietOCR**                        |
| 2    | SDSV AICR     | 0,23 | PaddleOCR + MobileNetv3 + **VietOCR** + GCN |
| 3    | SUN-AI        | 0,26 | CRAFT + **VietOCR**                         |
| 4    | UIT CS AIClub | 0,30 | PAN + **VietOCR**                           |


Bốn đội đầu bảng đều dùng VietOCR làm recognizer, khác nhau chỉ ở detector. Đội hạng 2 dùng đúng mô hình lai của STT 1: PaddleOCR cho detection, VietOCR cho recognition.

**STT 2, 5 — Marker 2 / Surya 2** · benchmark nhà cung cấp, per-language, 32.055 test, 91 ngôn ngữ

Tiếng Việt đạt **73,2%** pass rate, so với trung bình 91 ngôn ngữ là **87,2%** — thấp hơn 14 điểm, gần đáy bảng (chỉ trên Thái 76,4% và một vài ngôn ngữ khác). Marker 2 dùng chung model recognition này nên thừa hưởng đúng con số. **Không tách riêng chữ in và viết tay.**

**STT 3, 4, 6 — PaddleOCR-VL 1.6 / Chandra OCR 2 / MinerU 2.5**

**Không có bất kỳ số liệu tiếng Việt nào được công bố.** Các benchmark mà ba model này báo cáo (olmOCR-bench, OmniDocBench) đều không có thành phần tiếng Việt, nên không đưa vào đây.

### 1.3.4 Giới hạn của các số liệu này

**Không nguồn nào đo trên tài liệu hành chính scan tiếng Việt** — đúng loại corpus của dự án. Cụ thể:

- Số chữ in 98,6% của VietOCR đo trên ảnh PNG **tổng hợp**, không phải scan thật. Số viết tay 68,2% mới là số gần thực tế nhất trong toàn bộ tài liệu này.
- MC-OCR là **ảnh chụp hoá đơn bằng điện thoại**, không phải scan A4.
- Surya/Marker 73,2% là **pass rate** trên benchmark hỗn hợp, không phải CER — không so trực tiếp với cột CER của STT 1.
- **Ba trong sáu option (STT 3, 4, 6) không có số tiếng Việt nào** — kể cả chữ in.

Dữ liệu đủ để chọn STT 1 dựa trên bằng chứng, **không** đủ để xếp hạng STT 2–6 với nhau. Bước 1 và 3 ở §5.2 giải quyết đúng khoảng trống đó với chi phí thấp.

---

# PHẦN II — Code KHÔNG phụ thuộc model

Làm được ngay, song song với research ở Phần I. Đây là phần chiếm khối lượng công việc lớn nhất — **trừ khi chọn STT 2**, khi đó Marker 2 đã làm sẵn §2.2 và phần lớn Phần III.

## 2.1 Quản lý hệ toạ độ — ưu tiên cao nhất

**Đây là blocker của COCO.** Repo `ocr-core` hiện tại không ghi page width/height/DPI ở bất kỳ đâu trong output, và bbox nằm trong không gian pixel của ảnh **đã deskew** — tức đã xoay so với ảnh gốc, không map ngược về PDF được.

Thiết kế:

- Mỗi trang mang `{width_px, height_px, dpi, rotation_applied, deskew_angle, pdf_width_pt, pdf_height_pt}`.
- Mọi bbox quy về **một hệ chuẩn duy nhất**: pixel của ảnh render ở DPI đã ghi, **trước** deskew.
- Giữ ma trận affine của phép deskew để chuyển đổi hai chiều.
- Hàm `px_to_pdf_point(bbox, page_meta)` để map ngược về toạ độ PDF gốc.

Lưu ý nếu chọn STT 6 (MinerU): bbox được **normalize về thang 0–1000**, phải đổi về pixel tuyệt đối cho COCO.

Không có tầng này thì COCO vô nghĩa và không highlight được vùng nguồn trong RAG.

## 2.2 Render PDF → ảnh

`pypdfium2` thay cho `pdf2image` + Poppler: nhanh hơn, không phụ thuộc binary hệ thống, quan trọng ở quy mô 2M trang. DPI mặc định 300.

Phát hiện trang PDF vốn đã có text layer (không phải scan) → bỏ qua OCR, đọc thẳng text + bbox từ PDF. Corpus 0,4 TB gần như chắc chắn có lẫn loại này, và đó là phần "miễn phí".

## 2.3 Tiền xử lý ảnh

Orientation detection (0/90/180/270), deskew, denoise. **Không binarize** — tài liệu design của chính repo này đã ghi nhận binarize làm giảm độ chính xác của PaddleOCR, nhưng `config.yaml` hiện vẫn đang bật nó mặc định.

## 2.4 Trích xuất & lưu ảnh figure

Crop theo bbox layout (nới padding ~2%), encode PNG/WebP, đặt tên `{doc_sha256}/p{page:04d}/{ann_id}.png`, upload storage, trả URL vào cả `image_url` (COCO) và `![caption](url)` (Markdown).

## 2.5 Orchestration 2M trang

Phần dễ bị đánh giá thấp nhất. Ở quy mô này, những thứ sau **bắt buộc** phải có:


| Yêu cầu                                                                               | Vì sao                                                                                          |
| ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| **Đơn vị công việc là trang, không phải file**                                        | Một PDF 800 trang lỗi ở trang 700 không được làm mất 699 trang đã xong                          |
| **Checkpoint & resume idempotent**, khoá `(pdf_sha256, page_index, pipeline_version)` | Chạy lại phải skip được phần đã xong                                                            |
| **Dead-letter queue** + phân loại lỗi                                                 | PDF hỏng / trang trắng / OOM / timeout là các lỗi khác nhau, xử lý khác nhau                    |
| **Backpressure**                                                                      | Render PDF ở CPU nhanh hơn OCR ở GPU rất nhiều — không giới hạn hàng đợi sẽ tràn RAM/disk       |
| **Không persist ảnh render**                                                          | 2M trang × ~600 KB ≈ **1,2 TB** ảnh trung gian. Stream thẳng vào inference, chỉ giữ crop figure |
| **Dedup theo page hash**                                                              | Corpus hành chính có rất nhiều trang bìa/phụ lục trùng nhau                                     |
| **Model warm-up một lần / process**                                                   | Reuse qua toàn bộ trang. Repo hiện tại đã làm đúng với `_READERS` cache — giữ pattern này       |




## 2.6 Observability

pages/s theo thời gian, error rate theo loại, latency theo từng stage (render / preprocess / layout / rec / table / formula / serialize), phân bố confidence, tỉ lệ vào hàng đợi review. Không có cái này thì không biết chạy 8 ngày có đang hỏng hay không.

## 2.7 Storage & manifest


| Hạng mục                                           | Dung lượng      | Lưu?     |
| -------------------------------------------------- | --------------- | -------- |
| PDF gốc                                            | 400 GB          | ✔        |
| Ảnh render 300 DPI                                 | ~1,2 TB         | ✘ stream |
| Output Markdown                                    | ~8–16 GB        | ✔        |
| Output COCO JSON                                   | ~30–90 GB       | ✔        |
| Parquet per-token log-prob (chỉ block dưới ngưỡng) | ~1–3 GB         | ✔        |
| Crop figure (giả định 15% trang có hình)           | ~45 GB          | ✔        |
| **Tổng cần lưu**                                   | **~500–560 GB** |          |


---



# PHẦN III — Code tiêu thụ output của OCR

Phụ thuộc **format** output của model, không phụ thuộc **chất lượng** model. Viết được ngay sau khi chốt model.

**Nếu chọn STT 2 (Marker 2):** đã sinh sẵn Markdown và JSON kèm bbox, confidence, element hierarchy, bảng và LaTeX. Phần III thu lại còn: map schema của Marker sang COCO (§3.6), ghép figure ra storage (§2.4), và QA gating (§3.7). Các mục §3.2–3.5 gần như không cần viết.

## 3.1 Chuẩn hoá output model → Document Model

Tầng adapter duy nhất biết đến định dạng riêng của model. Mọi tầng phía sau chỉ thấy Document Model.

Việc phải làm:

1. **Map class layout.** `PP-DocLayout_plus-L` có ~23 class; DocLayNet có 11. Viết bảng map, class không map được thì gộp vào `text` và ghi log để review.
2. **Chuẩn hoá bbox** — quy hết về `[x, y, w, h]` int pixel tuyệt đối, kèm polygon gốc nếu cần.
3. **Ghép detection với recognition** nếu dùng STT 1 hoặc lai 2+1 — crop theo polygon rồi đưa qua VietOCR. Đây là ranh giới giữa hai framework, và là nơi dễ lệch toạ độ nhất.
4. **Trích log-prob** từ decoder, đóng gói thành `{sum, mean, min, n_tokens}`.

**Document Model** — một representation duy nhất, hai serializer:

```python
@dataclass
class Element:
    id: int
    category: str              # DocLayNet 11 class
    bbox: tuple[int, int, int, int]
    layout_score: float
    reading_order: int
    content: TextContent | TableContent | FormulaContent | FigureContent
    logprob: LogProb | None    # None cho figure
```

Repo hiện tại tách `mode: data | markdown` ngay từ tầng extract nên markdown mất sạch geometry. Đó là lỗi kiến trúc gốc — yêu cầu mới cần cả `.md` và `.json` **từ cùng một lần chạy OCR**, không được OCR hai lần.

## 3.2 Khôi phục reading order

Cả 6 option đều trả reading order sẵn (Surya/Marker, Chandra, PaddleOCR-VL, MinerU, `PP-DocLayoutV2`) → dùng thẳng. Đó là lý do M10 xuất hiện ở mọi dòng trong §1.3.1.

Nếu vì lý do nào đó phải tự làm: **XY-cut đệ quy** — cắt theo khoảng trắng ngang/dọc lớn nhất, đệ quy vào từng nửa, sắp trên→dưới trái→phải. Cần xử lý riêng: `page-header` / `page-footer` luôn đẩy ra khỏi luồng chính; layout nhiều cột; khối quốc hiệu–tiêu ngữ hai cột đầu trang văn bản hành chính VN.

## 3.3 Hậu xử lý bảng

- **Validate HTML** — parse bằng `lxml`. Không parse được → hạ confidence về 0, đẩy vào review.
- **Đối chiếu số ô** giữa HTML và danh sách bbox cell. Lệch → tín hiệu bất định độc lập với log-prob.
- **Ghép text vào cell** — crop từng cell, đưa qua recognizer, gán vào đúng `(row, col)`, giữ log-prob riêng từng cell.
- **Bảng tràn trang** — ghép ở tầng document sau OCR: bảng cuối trang N và đầu trang N+1 có cùng số cột và cùng biên trái/phải (sai số ~2%) → nối. Đây là hạn chế đã biết của repo hiện tại.

Lưu ý theo option: **Surya 2 (STT 2, 5) chỉ trả** `rowspan`**/**`colspan` **qua** `predict_full()` — API `table_rec` cấp cell đã bỏ `is_header`/`colspan`/`rowspan` từ bản 2, chỉ còn rows/columns và cell suy ra từ giao điểm. Dùng sai API là mất ô gộp mà không có lỗi báo. Marker xử lý bảng scan bằng cách fallback sang VLM cho vùng khó — với corpus toàn scan thì đường bảng của Marker thực chất là VLM.

## 3.4 Hậu xử lý công thức

Validate bằng cách compile LaTeX với **KaTeX** (nhanh, chạy được headless). Không compile được → tín hiệu bất định, đẩy vào review. Chuẩn hoá LaTeX (bỏ khoảng trắng thừa, thống nhất `\frac` vs `\dfrac`) trước khi so sánh hoặc lưu.

Lưu ý theo option: Surya 2 trả công thức inline trong `<math>...</math>` bằng LaTeX tương thích KaTeX, không có pass LaTeX riêng. Marker tự nhận **không convert 100% công thức** — inline math cần bật `--ocr_inline_math` hoặc balanced mode.

## 3.5 Serialize Markdown

Sort theo `reading_order`, render theo class:


| Class                                      | Markdown                                                                                                |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `title` / `section-header`                 | `#` / `##`                                                                                              |
| `text`                                     | đoạn văn (ghép dòng bị ngắt mềm lại thành câu)                                                          |
| `list-item`                                | `-`                                                                                                     |
| `table`                                    | **nhúng thẳng HTML** — GFM chấp nhận raw HTML, và HTML giữ được merged cell mà GFM table không giữ được |
| `formula`                                  | `$$...$$` (display) hoặc `$...$` (inline)                                                               |
| `picture`                                  | `![caption](url)`                                                                                       |
| `page-header` / `page-footer` / `footnote` | tách ra khỏi luồng chính, đưa xuống cuối hoặc bỏ tuỳ cấu hình RAG                                       |


**Mỗi block kèm anchor comment** `<!-- ann:101 -->`**.** Đây là chi tiết nhỏ nhưng quyết định việc RAG có citation chính xác hay không — nó cho phép trace ngược từ chunk trong RAG về đúng `annotation` trong COCO, từ đó ra bbox và trang gốc.

## 3.6 Serialize COCO

Category schema dùng **DocLayNet 11 class** (`caption, footnote, formula, list-item, page-footer, page-header, picture, section-header, table, text, title`) — chuẩn COCO cho document layout đã phổ biến. Ba việc cần lưu ý:

- **COCO vốn là format cho object detection** — không có chỗ cho text/HTML/LaTeX/log-prob. Phải mở rộng bằng field tuỳ biến trong `annotations`. Đây là quyết định thiết kế có ý thức, cần ghi vào `info.description` để công cụ đọc COCO chuẩn không hiểu nhầm.
- **Confidence trong COCO theo convention là thang 0–1** (`score`). `layout_score` và `det_score` theo đúng convention, còn `logprob` là field mở rộng thang khác — phải đặt tên khác để không nhầm.
- **Chia file theo tài liệu** + một manifest tổng. Một file cho cả 2M trang sẽ ~30–90 GB, không load nổi.



## 3.7 QA gating & hàng đợi review

Áp ngưỡng gating, sinh ra:

- Hàng đợi review có thứ tự ưu tiên (tệ nhất trước)
- Báo cáo tổng: phân bố confidence, top-N trang tệ nhất, top-N ký tự hay sai (để biết có nên fine-tune không và fine-tune cái gì)

Nếu đi đường lai **2 + 1**: đây cũng chính là tầng định tuyến — block nào dưới ngưỡng thì gửi lại qua VietOCR thay vì đẩy cho người review.

---



# PHẦN IV — Ước lượng hạ tầng



## Đường PP-StructureV3 (STT 1)

Số gốc từ benchmark chính thức PaddleOCR (15 PDF, 925 trang, `PP-StructureV3-default`, không bật chart):


| GPU  | Cấu hình                                     | s/trang  | trang/s  | VRAM đỉnh   |
| ---- | -------------------------------------------- | -------- | -------- | ----------- |
| A100 | Server OCR + FormulaNet-L                    | 1,12     | 0,89     | 21,8 GB     |
| A100 | **Mobile OCR + FormulaNet-M**                | **0,89** | **1,12** | **11,4 GB** |
| A100 | Mobile + FormulaNet-M, `max_side_limit=1200` | 0,64     | 1,56     | 11,4 GB     |
| V100 | Mobile OCR + FormulaNet-M                    | 1,15     | 0,87     | 8,4 GB      |


VRAM 11,4 GB cho phép ~4 instance song song trên A100 80 GB; scaling không tuyến tính (preprocess bám CPU), ước tính thực tế ~2,5×:


| Cấu hình           | trang/s | 2M trang    | GPU-giờ |
| ------------------ | ------- | ----------- | ------- |
| 1× A100, 1 process | 1,12    | ~21 ngày    | ~496    |
| 1× A100, 4 process | ~2,8    | **~8 ngày** | ~192    |
| 4× A100, 4 process | ~11     | **~2 ngày** | ~192    |
| 8× A100, 4 process | ~22     | **~1 ngày** | ~192    |


**Cảnh báo với STT 1:** các con số trên đo với recognizer CTC của Paddle — chính là recognizer đã bị loại vì M7. VietOCR vgg_transformer chậm hơn đáng kể (240 ms/dòng), và là mô hình tự hồi quy nên không batch hiệu quả bằng CTC. **Throughput thực của STT 1 phải đo lại** — có thể đội lên 1,5–2×. Đây là cái giá phải trả cho việc vượt ngưỡng chữ viết tay.

## Đường document parser (STT 2, 3, 6)


| Model                           | trang/s | 2M trang    | GPU-giờ  |
| ------------------------------- | ------- | ----------- | -------- |
| **Marker 2 balanced (1× B200)** | **2,9** | **~8 ngày** | **~192** |
| PaddleOCR-VL 1.6 (A100, vLLM)   | 1,22    | ~19 ngày    | ~455     |
| MinerU 2.5 pipeline backend     | 0,54    | ~43 ngày    | ~1.030   |


Chandra OCR 2 (STT 4): benchmark chạy trên H100 80GB với vLLM nhưng **không công bố trang/s**.

Trùng hợp đáng chú ý: **đường PP-StructureV3 (A100 ×4 process) và Marker 2 (B200 ×1) đều rơi vào ~192 GPU-giờ.** Marker đạt được bằng một process nên đơn giản hơn về vận hành.

## Chi phí & lưu trữ

A100 80G spot ~1,19 USD/giờ → **~230 USD** compute cho đường PP-StructureV3. Cộng CPU + storage + egress: **300–600 USD**. Khớp với benchmark độc lập ~141–697 USD/triệu trang trên H100. So sánh: AWS Textract ở mức 1,50 USD/1.000 trang = **~3.000 USD** cho cùng khối lượng.

*Giá thuê B200 chưa kiểm chứng*, nên chi phí đường Marker chưa quy ra USD được — chỉ biết là cùng ~192 GPU-giờ.

**Overhead của log-prob:** giữ per-token log-prob của token được chọn là một float mỗi ký tự — không đáng kể. Với STT 2 và 5 thì bằng 0, vì `confidence` đã được model trả sẵn.

**Phương án CPU-only:** không còn khả thi sau bộ lọc M7. Các ứng viên chạy CPU tốt (Tesseract, PP-OCR mobile, Docling) đều đã bị loại vì chữ viết tay dưới 50%. STT 1 vẫn export ONNX được (M14) nhưng VietOCR trên CPU sẽ rất chậm.

---



# PHẦN V — Rủi ro & bước tiếp theo



## 5.1 Bảng rủi ro


| #   | Rủi ro                                                                                              | Mức        | Xử lý                                                                                               |
| --- | --------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------- |
| 1   | **5/6 option không có số tiếng Việt viết tay; chúng qua M7 vì thiếu dữ liệu, không vì vượt ngưỡng** | **Cao**    | Bước 1 và 3 ở §5.2 — chạy thử trên corpus thật là cách duy nhất                                     |
| 2   | **Tiếng Việt là điểm yếu của Surya/Marker** (73,2% vs TB 87,2%)                                     | **Cao**    | Định tuyến block confidence thấp qua VietOCR (lai 2 + 1)                                            |
| 3   | CER trên ký tự có dấu không đạt ở mọi option                                                        | **Cao**    | Fine-tune VietOCR — có tiền lệ: fine-tune PP-OCRv5 cho Hán-Nôm nâng exact accuracy 37,5% → 50,0%    |
| 4   | Layout model không quen bố cục hành chính VN                                                        | **Cao**    | Bù bằng rule vị trí (khối quốc hiệu đầu trang, khối ký tên cuối trang) trước khi tính đến fine-tune |
| 5   | **Chưa rõ thay recognizer trong Marker khó đến đâu**                                                | **Cao**    | Đọc code Marker trước khi cam kết đường lai; nếu quá khó thì quay về STT 1 thuần                    |
| 6   | **Throughput STT 1 chưa biết** — VietOCR tự hồi quy, khó batch, và không còn fallback CPU sau M7    | **Cao**    | Đo sớm. Nếu quá chậm thì buộc phải nới M7 hoặc tăng GPU                                             |
| 7   | Confidence chưa hiệu chỉnh ⇒ ngưỡng gating vô nghĩa                                                 | Trung bình | Temperature scaling + ECE. Ở mức Trung bình vì M9 chỉ là mong muốn                                  |
| 8   | Ghép detection ↔ recognition lệch toạ độ                                                            | Trung bình | Test riêng ranh giới hai framework (§3.1)                                                           |
| 9   | Marker không convert 100% công thức sang LaTeX                                                      | Trung bình | Bật `--ocr_inline_math`; validate bằng KaTeX (§3.4)                                                 |
| 10  | Surya 2 bỏ `rowspan`/`colspan` khỏi API cell-level                                                  | Trung bình | Bắt buộc dùng `predict_full()` để lấy HTML có spanning cell (§3.3)                                  |
| 11  | Bảng tràn trang                                                                                     | Trung bình | Ghép bằng code ở tầng document (§3.3)                                                               |
| 12  | 2M trang lộ lỗi hiếm mà mẫu nhỏ không thấy                                                          | Trung bình | Dead-letter queue + chạy thử 10k trang trước                                                        |
| 13  | Nếu sau này đổi sang mục đích thương mại                                                            | Thấp       | STT 2, 4, 5 vướng OpenRAIL-M → phải chuyển sang STT 1, 3 hoặc 6. Giữ interface để đổi được          |




## 5.2 Bước tiếp theo

1. **Chạy STT 2 (Marker 2) và STT 3 (PaddleOCR-VL 1.6) trên vài chục trang thật của corpus, có cả trang có chữ ký / bút phê tay** — rẻ nhất, nhanh nhất, và là cách duy nhất biết chúng có thật sự vượt M7 hay không.
2. **Đọc code Marker** xem tầng recognition có tách ra được để thay VietOCR không. Đây là điều kiện của đường lai (rủi ro #5).
3. **Chạy STT 1 (VietOCR) trên cùng vài chục trang đó** để có mốc so sánh trực tiếp trên cùng dữ liệu — thứ mà không benchmark công khai nào cho được.
4. **Đo throughput thực của STT 1** — rủi ro #6, và sau bộ lọc M7 thì không còn phương án CPU dự phòng.
5. **Kiểm tra license VietOCR** — rẻ và nhanh, dù mục đích nghiên cứu gần như chắc chắn không vướng.
6. **Thống kê mẫu**: bao nhiêu % trang có bảng / công thức / hình / chữ viết tay → quyết định bật tắt module nào, tính lại throughput theo tỉ lệ thật.
7. **Chạy thử 5.000 trang end-to-end** trên phần cứng thật.

**Phần II (code không phụ thuộc model) làm song song ngay từ bây giờ.**

## 5.3 Dùng Vintern-1B-v3.5 ở vai trò khác

Vintern-1B-v3.5 không vào được bảng option vì trượt M3 (không trả bounding box — là MLLM hỏi-đáp, không có tầng layout), nhưng nó là model tiếng Việt chuyên biệt, **MIT license**, và trên MTVQA subset tiếng Việt nó đạt 41,9 — cao hơn GPT-4o (34,2). Hai vai trò nó vẫn dùng được vì không cần tự sinh bbox:

- **Tầng sửa lỗi tiếng Việt sau OCR** — thay cho `postprocess.py` hiện tại, vốn đang gọi `nvidia/nemotron-3.5-content-safety:free` (một model phân loại an toàn nội dung, không phải instruction-following) nên im lặng fallback về text gốc ở mọi trang.
- **Trọng tài cho vùng confidence thấp** — chạy trên crop đã có bbox từ tầng layout.



## 5.4 Giữ cửa mở cho VLM

Kiến trúc cổ điển và VLM **không loại trừ nhau**. Nếu thiết kế theo mô hình "layout cắt vùng → model chuyên biệt xử lý từng vùng", thì sau này chỉ cần thay handler của `table`/`formula` bằng một VLM 0,9B (PaddleOCR-VL-1.6, Apache-2.0, ~2 GB VRAM) chạy trên crop, mà **không đụng** nhánh text.

Giữ cửa này mở ngay từ đầu bằng **interface**, không phải bằng code thêm.

---



## Nguồn

**Benchmark tiếng Việt**

- [Benchmark OCR tiếng Việt, đo 2026-05-01 — Neural Research Lab](https://nom-vn.nrl.ai/tasks/ocr)
- [A Survey on Vietnamese Document Analysis and Recognition (arXiv:2506.05061)](https://arxiv.org/html/2506.05061) — bảng MC-OCR
- [Surya — benchmark per-language 91 ngôn ngữ](https://github.com/datalab-to/surya)
- [VietOCR — pbcquoc/vietocr](https://github.com/pbcquoc/vietocr)
- [MTVQA (arXiv:2405.11985)](https://arxiv.org/html/2405.11985v2) — subset VI, dùng cho §5.3
- [Vintern-1B-v3.5 — 5CD-AI](https://huggingface.co/5CD-AI/Vintern-1B-v3_5) — §5.3

**Option trong bảng**

- [Marker — datalab-to/marker](https://github.com/datalab-to/marker)
- [Chandra OCR — datalab-to/chandra](https://github.com/datalab-to/chandra)
- [MinerU — opendatalab/MinerU](https://github.com/opendatalab/mineru)
- [PP-StructureV3 — benchmark V100/A100](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-StructureV3/PP-StructureV3.html)
- [PP-StructureV3 — usage & JSON output fields](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PP-StructureV3.html)
- [Table Recognition V2 —](https://paddlepaddle.github.io/PaddleX/3.3/en/pipeline_usage/tutorials/ocr_pipelines/table_recognition_v2.html) `pred_html`[,](https://paddlepaddle.github.io/PaddleX/3.3/en/pipeline_usage/tutorials/ocr_pipelines/table_recognition_v2.html) `cell_box_list`
- [PaddleOCR-VL (arXiv:2510.14528) — bảng 109 ngôn ngữ, VI thuộc nhóm Latin](https://arxiv.org/html/2510.14528v2)
- [Marker v2 vs MinerU, Docling — throughput trang/s](https://www.marktechpost.com/2026/07/24/datalab-marker-v2-vs-mineru-docling-and-liteparse-benchmark-breakdown/)

**Log-prob & calibration**

- [PaddleOCR — Recognition Confidence metric (discussion #11352, chưa có câu trả lời chính thức)](https://github.com/PaddlePaddle/PaddleOCR/discussions/11352)
- [Connectionist Temporal Classification — Wikipedia](https://en.wikipedia.org/wiki/Connectionist_temporal_classification)
- [Towards Deployable OCR models for Indic languages (arXiv:2205.06740)](https://arxiv.org/pdf/2205.06740)
- [Expected Calibration Error & Temperature Scaling](https://deepwiki.com/gpleiss/temperature_scaling/2.1-expected-calibration-error)
- [Quantile-Adaptive Temperature Scaling (arXiv:2606.21749)](https://arxiv.org/html/2606.21749)

**Format**

- [DocLayNet — COCO format, 11 class](https://github.com/DS4SD/DocLayNet)
- [Fine-tuning PaddleOCRv5 cho Hán-Nôm (arXiv:2510.04003)](https://arxiv.org/html/2510.04003v2)

