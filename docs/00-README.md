# Mục lục cấu phần - ocr-core

Thư mục này gộp và thu gọn toàn bộ tài liệu design cũ nằm rải rác ở `docs/`, `docs/plans/`,
`docs/superpowers/specs/`, `docs/superpowers/plans/` (tính đến 2026-08-11) theo **từng cấu phần** của dự
án, thay vì theo ngày viết. Các file nguồn đã bị xoá sau khi gộp vào đây - lịch sử chi tiết (bao gồm mọi
số liệu, bảng, code mẫu đầy đủ) vẫn xem được qua `git log -- docs/`.

| # | Cấu phần | Trạng thái | Tóm tắt |
| --- | --- | --- | --- |
| [01](01-nghien-cuu-chon-model.md) | Nghiên cứu & chọn model OCR | Nền tảng, còn hiệu lực | Tiêu chí bắt buộc/mong muốn cho model OCR tiếng Việt, bảng so sánh 6 option, ước lượng hạ tầng |
| [02](02-ocr-engines.md) | OCR Engines (recognizer backend) | Còn hiệu lực, không bị đụng bởi refactor | `core/engines/`: Tesseract, PaddleOCR, EasyOCR - interface `OCREngine` dùng chung |
| [03](03-core-pipeline-legacy.md) | Core pipeline - kiến trúc cũ | **Đã thay thế (superseded)** | Dòng thời gian 4 bản thiết kế cũ (pipeline engine gốc → multi-pipeline → markdown+bảng → LLM postprocess) và lý do bị thay hoàn toàn |
| [04](04-core-pipeline-staged.md) | Core pipeline - kiến trúc hiện tại | **Đang implement** | Kiến trúc 6-stage; quyết định Chandra OCR 2 và cách nó được dung hoà lại thành interface phân tầng; Document Model, hệ toạ độ, tín hiệu bất định, serialize |
| [05](05-aws-infrastructure.md) | Hạ tầng AWS | Đang chạy (môi trường thử nghiệm) | 13 service, một EC2 GPU + một hàng đợi; đã bỏ tầng mạng riêng và tự động tắt máy so với thiết kế gốc 15 service |
| [06](06-evaluation-harness.md) | Bộ đo chất lượng (`evaluate/`) | Đang implement | Ba metric (IoU/WER-CER/TEDS) qua COCO, cộng đường chấm bảng document-level vì chưa có bộ sinh COCO nào chạy thật |
| [07](07-ground-truth-lpbank.md) | Chuẩn bị ground truth LPBank | Phase 1 đã duyệt | Trích text layer PDF LPBank thành `.md` ground truth cho bộ đo ở #06 |

## Cách đọc

Cấu phần 1 là nền cho mọi quyết định model ở cấu phần 4. Cấu phần 3 chỉ để hiểu lý do đổi hướng - đừng
dùng để implement mới. Cấu phần 4 là tài liệu quan trọng nhất hiện tại: mọi `§x.y` trong các cấu phần khác
khi nói "xem Cấu phần 4" là trỏ vào kiến trúc `core/` đang được xây. Cấu phần 5 phụ thuộc trực tiếp vào các
quyết định ở cấu phần 1 và 4 (GPU, orchestration theo trang). Cấu phần 6 và 7 độc lập với nhau về mã nguồn
nhưng 7 sinh dữ liệu đầu vào cho 6.
