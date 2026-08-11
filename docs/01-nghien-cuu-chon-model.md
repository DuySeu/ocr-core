# Cấu phần 1 - Nghiên cứu & chọn model OCR

Nguồn gốc: `2026-08-06-ocr-2m-pages-requirements-analysis.md` (đã xoá, nội dung gộp vào đây).
Ngày: 2026-08-06. Trạng thái: phân tích yêu cầu, làm nền cho [Cấu phần 4](04-core-pipeline-staged.md) và [Cấu phần 5](05-aws-infrastructure.md).

Mục đích sử dụng: **nghiên cứu**, không thương mại. Kiến trúc cơ sở: OCR cổ điển (layout + detection + recognition + table + formula), có mở cửa cho VLM.

## Bài toán

OCR 2 triệu trang PDF-scan (~0,4 TB) tiếng Việt, self-host, sinh **đồng thời** hai output từ một lần chạy:

| Output | Mục đích |
| --- | --- |
| `.md` | Phục vụ tra cứu / RAG |
| `.json` (COCO) | Trích xuất thông tin, kiểm định, huấn luyện lại |

Bốn loại phần tử phải bóc tách riêng: **text** → text, **ảnh** → bbox + link ảnh, **bảng** → HTML, **công thức** → LaTeX. Mọi phần tử cần bounding box và một tín hiệu bất định đi kèm - dùng **log-probability**, không dùng "confidence score" mơ hồ.

Bài toán chia ba khối: **Phần I** model cần đáp ứng gì · **Phần II** code không phụ thuộc model · **Phần III** code tiêu thụ output model. Chỉ **6 hạng mục phụ thuộc model**, **13 hạng mục là code thuần**.

## Kết luận ngắn

Vì là dự án nghiên cứu, ràng buộc license được nới → mở ra **Marker 2**, **Surya 2**, **Chandra OCR 2** (OpenRAIL-M, miễn phí cho nghiên cứu). Sau khi áp ngưỡng **chữ viết tay ≥ 50% (M7)**, toàn bộ nhánh recognizer của Tesseract và PP-OCR bị loại - đây là lý do engine mặc định của [Cấu phần 2](02-ocr-engines.md) không đạt chuẩn cho đường chính, dù vẫn dùng được cho các mục đích khác.

Còn 6 option, chỉ **STT 1 (VietOCR) có số tiếng Việt đo được**. Đánh đổi cốt lõi: **VietOCR là option duy nhất có bằng chứng tiếng Việt; Marker 2 có ROI kỹ thuật tốt nhất; PaddleOCR-VL 1.6 đáp ứng nhiều tiêu chí mong muốn nhất và là Apache-2.0.** Quyết định triển khai thực tế (dùng Chandra OCR 2, STT 4) được chốt ở [Cấu phần 4](04-core-pipeline-staged.md) - dựa trên ROI kỹ thuật, chấp nhận rủi ro "chưa có số tiếng Việt công bố" nêu ở bảng rủi ro bên dưới.

Hạ tầng: **~192 GPU-giờ** cho toàn bộ 2M trang, dù đi đường PP-StructureV3 (A100, 4 process) hay Marker 2 (B200, 2,9 trang/s).

## Phần I - Tiêu chí chọn model

### Bắt buộc (loại nếu không đạt)

| # | Yêu cầu | Vì sao |
| --- | --- | --- |
| M1 | Self-host offline hoàn toàn, không gọi API ngoài | 0,4 TB không được rời hệ thống |
| M2 | Tiếng Việt có dấu trong charset | Yêu cầu lõi |
| M3 | Trả bounding box cho mọi phần tử | Input của COCO |
| M4 | Bảng → HTML giữ merged cell | GFM table không biểu diễn được rowspan/colspan |
| M5 | Công thức → LaTeX | Yêu cầu lõi |
| M6 | Chạy trên GPU đơn ≤ 24 GB VRAM | Ràng buộc chi phí |
| M7 | Độ chính xác chữ viết tay ≥ 50% | Corpus có chữ ký, bút phê hành chính |

### Mong muốn (chấm điểm, không loại)

M8 license thương mại · M9 truy cập logits/per-token probability · M10 reading order do model dự đoán · M11 bảng borderless · M12 con dấu/chữ ký · M13 fine-tune được · M14 export ONNX/OpenVINO · M15 xử lý ảnh nghiêng/mờ/photocopy.

### Bảng option (mọi option đạt 100% M1-M7)

| STT | Model | CER tiếng Việt | Tiêu chí mong muốn |
| --- | --- | --- | --- |
| 1 ⭐ | PP-StructureV3 + VietOCR (thay recognizer) | Chữ in **98,6%** · viết tay **68,2%** (bên thứ 3) · hoá đơn 70-78% (MC-OCR) | 7/8 (M8 chưa kiểm chứng license VietOCR) |
| 2 ⭐ | Marker 2 (nền Surya 2) | 73,2% pass rate, không tách in/viết tay | 4/8 |
| 3 ⭐⚠ | PaddleOCR-VL 1.6 | Chưa công bố số VI | 7/8, Apache-2.0 |
| 4 ⚠ | **Chandra OCR 2 (4B)** | Chưa công bố số VI, có xử lý chữ viết tay | 4/8 |
| 5 | Surya 2 (trực tiếp) | 73,2% pass rate | 4/8 |
| 6 ⚠ | MinerU 2.5 | Chưa công bố số VI | 5/8, Apache-2.0 |

⚠ = phá ràng buộc "không dùng VLM" ban đầu.

**Đánh đổi giữa 3 ứng viên đầu bảng:** STT 1 có bằng chứng tiếng Việt trực tiếp (CER thật, 3 nguồn độc lập) và là lựa chọn dựa-trên-bằng-chứng duy nhất; STT 2 (Marker 2) đáng chạy song song vì làm sẵn gần hết Phần III và nhanh hơn - nếu số tiếng Việt đạt thì tiết kiệm nhiều công, nếu không vẫn dùng lai (Marker layout/bảng/công thức, VietOCR text); STT 3 (PaddleOCR-VL) tốt nhất nếu chấp nhận VLM, Apache-2.0, ~2 GB VRAM nhưng chưa đo tiếng Việt.

**Giới hạn số liệu:** không nguồn nào đo trên tài liệu hành chính scan tiếng Việt thật. Số 98,6% của VietOCR đo trên PNG tổng hợp; MC-OCR là ảnh chụp hoá đơn bằng điện thoại; Surya/Marker 73,2% là pass rate không phải CER, không so trực tiếp được; 3/6 option không có số tiếng Việt nào kể cả chữ in.

## Phần II - Code không phụ thuộc model

Làm được ngay, song song research. Nội dung chi tiết (hệ toạ độ, render PDF, tiền xử lý, orchestration 2M trang, storage) đã triển khai thành thiết kế cụ thể ở [Cấu phần 4](04-core-pipeline-staged.md) §5.1 (hệ toạ độ chuẩn) và [Cấu phần 5](05-aws-infrastructure.md) (orchestration hạ tầng). Các mốc chính:

- **Hệ toạ độ (ưu tiên cao nhất, blocker của COCO):** mỗi trang mang `{width_px, height_px, dpi, rotation_applied, deskew_angle, pdf_width_pt, pdf_height_pt}`; bbox quy về hệ chuẩn trước deskew; giữ ma trận affine để chuyển đổi hai chiều.
- **Render PDF → ảnh:** `pypdfium2` thay `pdf2image`/Poppler, DPI mặc định 300. Phát hiện trang đã có text layer → đọc thẳng, bỏ qua OCR (phần "miễn phí" của corpus).
- **Tiền xử lý:** orientation, deskew, denoise. **Không binarize** - đã ghi nhận làm giảm độ chính xác PaddleOCR.
- **Orchestration 2M trang:** đơn vị công việc là *trang* không phải *file*; checkpoint/resume idempotent theo `(pdf_sha256, page_index, pipeline_version)`; dead-letter queue; backpressure; không persist ảnh render (~1,2 TB); dedup theo page hash; model warm-up một lần/process.
- **Storage cần lưu:** ~500-560 GB (PDF gốc 400 GB + Markdown/COCO/parquet log-prob/crop hình); ảnh render 300 DPI (~1,2 TB) **không lưu**, chỉ stream.

## Phần III - Code tiêu thụ output model

Phụ thuộc format output, không phụ thuộc chất lượng model. Thiết kế đầy đủ (Document Model, reading order, hậu xử lý bảng/công thức, serialize Markdown/COCO, QA gating) đã chuyển thành kiến trúc cụ thể ở [Cấu phần 4](04-core-pipeline-staged.md) §5-§7. Các nguyên tắc gốc quan trọng nhất được giữ nguyên trong thiết kế đó:

- Category schema dùng **DocLayNet 11 class**.
- COCO mở rộng field tuỳ biến cho text/HTML/LaTeX/log-prob, ghi rõ trong `info.description`.
- `logprob` và `score`/`layout_score` dùng tên khác nhau vì thang đo khác nhau (0-1 vs log-scale).
- Mỗi block Markdown kèm anchor `<!-- ann:N -->` để RAG trace ngược về COCO annotation.

## Phần IV - Ước lượng hạ tầng

| Đường | Cấu hình | trang/s | 2M trang | GPU-giờ |
| --- | --- | --- | --- | --- |
| PP-StructureV3 | 1× A100, 4 process | ~2,8 | ~8 ngày | ~192 |
| PP-StructureV3 | 4× A100, 4 process | ~11 | ~2 ngày | ~192 |
| **Marker 2 balanced** | **1× B200** | **2,9** | **~8 ngày** | **~192** |
| PaddleOCR-VL 1.6 | A100, vLLM | 1,22 | ~19 ngày | ~455 |
| MinerU 2.5 | pipeline backend | 0,54 | ~43 ngày | ~1.030 |

Chandra OCR 2 (STT 4, phương án đã chọn ở Cấu phần 4): benchmark trên H100 80GB + vLLM nhưng **không công bố trang/s** - phải đo trước khi khoá kế hoạch (xem điều kiện huỷ quyết định ở Cấu phần 4).

Chi phí: A100 80G spot ~1,19 USD/giờ → ~230 USD compute cho đường PP-StructureV3; cộng CPU/storage/egress: **300-600 USD** cho 2M trang. So sánh: AWS Textract ~3.000 USD cho cùng khối lượng. Phương án CPU-only **không còn khả thi** sau bộ lọc M7.

## Phần V - Rủi ro chính & bước tiếp theo

| # | Rủi ro | Mức | Xử lý |
| --- | --- | --- | --- |
| 1 | 5/6 option không có số tiếng Việt viết tay công bố - qua M7 vì thiếu dữ liệu, không vì vượt ngưỡng | Cao | Chạy thử trên corpus thật là cách duy nhất biết |
| 2 | Tiếng Việt là điểm yếu của Surya/Marker (73,2% vs TB 87,2%) | Cao | Định tuyến block confidence thấp qua VietOCR (lai) |
| 3 | CER trên ký tự có dấu không đạt ở mọi option | Cao | Fine-tune - có tiền lệ (PP-OCRv5 Hán-Nôm 37,5%→50,0%) |
| 4 | Layout model không quen bố cục hành chính VN | Cao | Rule vị trí (quốc hiệu đầu trang, ký tên cuối trang) trước khi fine-tune |
| 5 | Chưa rõ thay recognizer trong Marker khó đến đâu | Cao | Đọc code Marker trước khi cam kết đường lai |
| 6 | Throughput STT 1 (VietOCR) chưa biết, tự hồi quy khó batch | Cao | Đo sớm |
| 13 | Đổi mục đích thương mại | Thấp | STT 2, 4, 5 vướng OpenRAIL-M → chuyển STT 1/3/6; giữ interface để đổi được |

Bước tiếp theo đã thực hiện: chạy thử Chandra OCR 2 trên corpus thật → dẫn tới quyết định ở [Cấu phần 4](04-core-pipeline-staged.md). Bước "đọc code Marker", "đo throughput VietOCR", "thống kê mẫu %bảng/công thức/hình" vẫn còn mở, chưa triển khai.

### Vai trò dự phòng của Vintern-1B-v3.5

Không vào được bảng option vì trượt M3 (không trả bbox), nhưng là model tiếng Việt chuyên biệt, MIT license, MTVQA-VI đạt 41,9 (cao hơn GPT-4o 34,2). Hai vai trò còn dùng được: **tầng sửa lỗi tiếng Việt sau OCR** (thay `postprocess.py` cũ - xem [Cấu phần 3](03-core-pipeline-legacy.md) §8), và **trọng tài cho vùng confidence thấp** trên crop đã có bbox.

### Giữ cửa mở cho VLM

Kiến trúc cổ điển và VLM không loại trừ nhau. Thiết kế theo mô hình "layout cắt vùng → model chuyên biệt xử lý từng vùng" cho phép sau này thay handler `table`/`formula` bằng VLM 0,9B mà không đụng nhánh text - giữ bằng **interface**, không phải bằng code thêm. Cách hiện thực hoá nguyên tắc này ở [Cấu phần 4](04-core-pipeline-staged.md) §2 (kiến trúc 6-stage).

## Nguồn

- [Benchmark OCR tiếng Việt, đo 2026-05-01 - Neural Research Lab](https://nom-vn.nrl.ai/tasks/ocr)
- [A Survey on Vietnamese Document Analysis and Recognition (arXiv:2506.05061)](https://arxiv.org/html/2506.05061)
- [Surya - benchmark per-language 91 ngôn ngữ](https://github.com/datalab-to/surya)
- [VietOCR - pbcquoc/vietocr](https://github.com/pbcquoc/vietocr)
- [Vintern-1B-v3.5 - 5CD-AI](https://huggingface.co/5CD-AI/Vintern-1B-v3_5)
- [Marker - datalab-to/marker](https://github.com/datalab-to/marker) · [Chandra OCR - datalab-to/chandra](https://github.com/datalab-to/chandra) · [MinerU - opendatalab/MinerU](https://github.com/opendatalab/mineru)
- [PP-StructureV3 - benchmark & usage](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-StructureV3/PP-StructureV3.html)
- [PaddleOCR-VL (arXiv:2510.14528)](https://arxiv.org/html/2510.14528v2)
- [DocLayNet - COCO format, 11 class](https://github.com/DS4SD/DocLayNet)
- [Fine-tuning PaddleOCRv5 cho Hán-Nôm (arXiv:2510.04003)](https://arxiv.org/html/2510.04003v2)
