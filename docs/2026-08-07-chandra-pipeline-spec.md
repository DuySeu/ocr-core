# Chốt luồng OCR — đường A: Chandra một pass

Ngày: 2026-08-07
Trạng thái: Đã chốt kiến trúc — chưa implement
Thay thế cho: workflow 5 model (preprocess → layout → 4 recognizer chuyên biệt → sort → export)
Tài liệu nguồn: [2026-08-06-ocr-2m-pages-requirements-analysis.md](./2026-08-06-ocr-2m-pages-requirements-analysis.md)
Sơ đồ: [chandra-ocr-pipeline.drawio.svg](./chandra-ocr-pipeline.drawio.svg) · [ocr-chandra-aws-vpc.drawio](./ocr-chandra-aws-vpc.drawio)

---

## Quyết định

Dùng **Chandra OCR 2 (4B)** làm một pass duy nhất cho layout + reading order + text + bảng + công thức.
Không tự dựng tầng layout riêng, không tự dựng 4 recognizer chuyên biệt, không tự sắp thứ tự đọc.

Lý do: cả ba việc đó Chandra đã trả sẵn trong cùng một forward pass (`§1.3.1` STT 4, `§3.2`). Tự làm lại
vừa nhân chi phí GPU (`§IV` tính ~192 GPU-giờ cho **một** pass/trang), vừa thay reading order do model dự
đoán bằng một rule sort kém hơn.

Ba tầng chuyên biệt vẫn giữ **interface** theo `§5.4`, nhưng ở vai trò đường dự phòng — xem §7.

---

## Luồng chốt

Bảy bước. Cột "so với workflow gốc" ghi rõ cái gì giữ, cái gì bỏ, cái gì thêm.

### 1 · Ingest & điều phối — CPU


| Việc                                                                          | So với workflow gốc |
| ----------------------------------------------------------------------------- | ------------------- |
| Bóc PDF thành **page job**, khoá `(pdf_sha256, page_index, pipeline_version)` | **THÊM** — `§2.5`   |
| Checkpoint lookup, key đã xong thì skip (idempotent)                          | **THÊM**            |
| Dedup theo page-hash (corpus hành chính nhiều trang bìa/phụ lục trùng)        | **THÊM**            |
| Queue + backpressure — render CPU nhanh hơn OCR GPU                           | **THÊM**            |


Đơn vị công việc là **trang**, không phải file. Một PDF 800 trang lỗi ở trang 700 không được làm mất 699 trang đã xong.

### 2 · Preprocess — CPU


| Việc                                                                                                          | So với workflow gốc                                                |
| ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Phát hiện trang đã có text layer → đọc thẳng text + bbox, **bỏ qua OCR**                                      | **THÊM** — `§2.2`, đây là phần "miễn phí" của corpus               |
| Render `pypdfium2` 300 DPI, **stream in-memory**                                                              | GIỮ (đổi từ `pdf2image`)                                           |
| Orientation 0/90/180/270                                                                                      | GIỮ                                                                |
| Deskew — **giữ ma trận affine** để chuyển đổi hai chiều                                                       | GIỮ + SỬA — `§2.1` gọi thiếu cái này là *"blocker của COCO"*       |
| Denoise                                                                                                       | GIỮ                                                                |
| Ghi `PageGeometry`: `{width_px, height_px, dpi, rotation_applied, deskew_angle, pdf_width_pt, pdf_height_pt}` | **THÊM**                                                           |


Không persist ảnh render: 2M trang × ~600 KB ≈ 1,2 TB. Chỉ crop hình mới ghi ra storage.

### 3 · Chandra — GPU


| Việc                                                                                                                     | So với workflow gốc                                         |
| ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| vLLM, warm-up model 1 lần / process, batch nhiều trang                                                                   | **THÊM**                                                    |
| Một lần suy luận trả về: layout + reading order + text (kể cả viết tay) + bảng HTML + công thức LaTeX + bbox mọi phần tử | **THAY** cho bước 2 + 3 + 4 của workflow gốc                |
| Lấy per-token log-prob, gộp theo block `{sum, mean, min, n_tokens}`                                                      | **THÊM** — Context yêu cầu mọi phần tử có tín hiệu bất định |
| OOM → hạ độ phân giải, thử lại; timeout / trang trắng → DLQ                                                              | **THÊM**                                                    |

### 4 · Adapter → Document Model — CPU

Tầng **duy nhất** biết định dạng riêng của Chandra. Đổi model chỉ sửa ở đây.


| Việc                                                                                                    | So với workflow gốc                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Map class Chandra → **DocLayNet 11 class**                                                              | **SỬA** — workflow gốc chỉ có 4 nhóm; thiếu `title`/`section-header` thì `§3.5` không sinh được `#`/`##`, file `.md` thành khối phẳng và hỏng chunking RAG |
| Chuẩn hoá bbox → px tuyệt đối `[x, y, w, h]`, **nghịch đảo affine deskew** về khung toạ độ trước deskew | **THÊM**                                                                                                                                                   |
| `px_to_pdf_point(bbox, page_meta)` map ngược về toạ độ PDF gốc                                          | **THÊM**                                                                                                                                                   |
| Đóng gói `Element[]`: `id · category · bbox · layout_score · reading_order · content · logprob`         | **SỬA**                                                                                                                                                    |


11 class: `caption, footnote, formula, list-item, page-footer, page-header, picture, section-header, table, text, title`.
Class Chandra trả về mà không map được → gộp vào `text` và ghi log để review.

### 5 · Validate & làm giàu — CPU


| Việc                                                                                               | So với workflow gốc |
| -------------------------------------------------------------------------------------------------- | ------------------- |
| Bảng: parse HTML bằng `lxml`; đối chiếu số ô ↔ bbox cell; parse lỗi → hạ log-prob về 0, đẩy review | **THÊM** — `§3.3`   |
| Công thức: compile thử bằng KaTeX; chuẩn hoá LaTeX; không compile được → tín hiệu bất định         | **THÊM** — `§3.4`   |
| Hình: crop bbox + padding 2%, encode PNG/WebP, `{doc_sha256}/p{page:04d}/{ann_id}.png`             | GIỮ                 |
| Tầng document: ghép bảng tràn trang N → N+1 (cùng số cột, cùng biên trái/phải ±2%)                 | **THÊM** — `§3.3`   |
| Tách `page-header`/`page-footer`/`footnote` khỏi luồng đọc chính                                   | **THÊM**            |




### 6 · Serialize — CPU

Một `Document Model`, hai serializer. **Một lần OCR, hai output** — không OCR hai lần.


| Việc                                                                                                           | So với workflow gốc                                                                                                              |
| -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Markdown: sort theo `reading_order` **do Chandra trả về**, không tự sort                                       | **SỬA** — workflow gốc dùng "trên xuống dưới, trái sang phải", vỡ ở layout nhiều cột và khối quốc hiệu–tiêu ngữ hai cột (`§3.2`) |
| Bảng nhúng **HTML thô** vào Markdown (GFM không giữ được rowspan/colspan)                                      | GIỮ                                                                                                                              |
| Mỗi block kèm anchor `<!-- ann:101 -->`                                                                        | **THÊM** — quyết định RAG có citation chính xác hay không                                                                        |
| COCO: DocLayNet 11 category + field mở rộng `text`/`html`/`latex`/`logprob`, 1 file / tài liệu + manifest tổng | **SỬA**                                                                                                                          |


Lưu ý `§3.6`: `layout_score` và `det_score` theo convention COCO thang 0–1; `logprob` là field mở rộng
thang khác — **phải đặt tên khác** để công cụ đọc COCO chuẩn không hiểu nhầm. Ghi rõ việc mở rộng schema
vào `info.description`.

### 7 · QA gating — CPU


| Việc                                                                                                                    | So với workflow gốc |
| ----------------------------------------------------------------------------------------------------------------------- | ------------------- |
| Áp ngưỡng: `logprob` dưới ngưỡng **hoặc** validate fail (lxml/KaTeX)                                                    | **THÊM** — `§3.7`   |
| Hàng đợi review có thứ tự ưu tiên, tệ nhất trước                                                                        | **THÊM**            |
| Báo cáo: phân bố log-prob, top-N trang tệ nhất, top-N ký tự hay sai                                                     | **THÊM**            |
| **Đường dự phòng** — block `table`/`formula` dưới ngưỡng thì crop ra, đẩy qua model chuyên biệt trước khi đẩy cho người | **THÊM**            |


Đường dự phòng ở dòng cuối là chỗ duy nhất workflow 5 model còn sống: nó chạy trên **crop đã có bbox**,
chỉ cho phần Chandra làm kém, không phải đường chính. Đúng `§5.4` và rủi ro #2 ở `§5.1`.
Ứng viên trọng tài: Vintern-1B-v3.5 (MIT, MTVQA-VI 41,9 — cao hơn GPT-4o 34,2), theo `§5.3`.

---

## Thứ tự làm

Phần II (không phụ thuộc model) làm được ngay, song song với việc đo Chandra.

1. **Tầng toạ độ** (`§2.1`) — blocker của COCO, không có thì mọi thứ sau vô nghĩa
2. **Render + preprocess** (`§2.2`, `§2.3`) — gồm việc bỏ `binarize`/`grayscale` khỏi `config.yaml`
3. **Orchestration 2M trang** (`§2.5`) — page job, checkpoint, dedup, DLQ, backpressure
4. **Document Model + 2 serializer** (`§3.1`, `§3.5`, `§3.6`)
5. **Adapter Chandra** — sau khi đo xong và chốt được format output thật
6. **Validate + QA gating** (`§3.3`, `§3.4`, `§3.7`)
7. **Observability** (`§2.6`)

---

## Điều kiện huỷ quyết định

Ba số liệu chưa có. Đo xong mới được khoá kế hoạch hạ tầng — nếu trượt thì quay lại `§1.3.2` chọn lại model,
và tầng adapter ở bước 4 là chỗ duy nhất phải viết lại.


| Cần đo                                      | Ngưỡng huỷ                          | Ghi chú                                                                                |
| ------------------------------------------- | ----------------------------------- | -------------------------------------------------------------------------------------- |
| CER tiếng Việt của Chandra trên corpus thật | dưới mức chấp nhận được cho tra cứu | `§1.3.3`: **không có bất kỳ số tiếng Việt nào được công bố** cho Chandra               |
| Độ chính xác chữ viết tay                   | < 50% (M7)                          | Chandra qua M7 vì **thiếu dữ liệu**, không phải vì đã vượt ngưỡng — rủi ro #1, mức Cao |
| Throughput trang/s                          | quá chậm so với ngân sách GPU       | Nhà cung cấp benchmark trên H100 + vLLM nhưng **không công bố trang/s**                |


Chưa kiểm chứng thêm: cách lấy per-token log-prob ở bước 3 đang dựa trên khả năng `logprobs` của vLLM,
chưa xác nhận trên API thật của Chandra 2. Phải đọc code trước khi cam kết `§3.7`.

License: OpenRAIL-M, chỉ dùng cho nghiên cứu (rủi ro #13). Đổi mục đích thương mại thì phải chuyển sang
STT 1, 3 hoặc 6 — giữ tầng adapter tách bạch chính là để đổi được.