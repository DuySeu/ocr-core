# Cấu phần 7 - Chuẩn bị ground truth LPBank

Nguồn gốc: `superpowers/specs/2026-08-11-lpbank-ground-truth-design.md` (đã xoá, nội dung gộp vào đây).
Trạng thái: đã duyệt để implement (phase 1). Dùng bởi [Cấu phần 6 - bộ đo chất lượng](06-evaluation-harness.md).

## Mục tiêu

Tạo ground truth dạng markdown cho các PDF LPBank để bộ đo ghép cặp prediction theo tên file (stem) với
`ground_truth/lpbank/`.

## Phạm vi (phase 1)

- Nguồn: `dataset/lpbank/*.pdf` (và `.PDF`) có **dưới 20 trang**.
- Output: `ground_truth/lpbank/<stem>.md`.
- Phương pháp: trích **text layer** của PDF bằng PyMuPDF (`fitz`, `page.get_text("text")`) - **không OCR**
  ở phase này.
- Marker mỗi trang: `<!-- page: N -->` (1-based), bị `evaluate/normalize` bóc trước khi tính CER/WER nên
  không ảnh hưởng điểm số.

### 6 file được xử lý

| Số trang | Tên file |
| --- | --- |
| 1 | Cong van 178 gui VPDKDD huong dan DKBPBD |
| 2 | 26675.2024.QĐ-LPBank.KVH |
| 5 | 14190.2025.TB-LPBank.QTRR |
| 8 | 1203.PGV.2026(2) |
| 8 | Phu luc Cong van 178 huong dan DKBPBD |
| 9 | 1202.PGV.2026(1) |

### Bị bỏ qua rõ ràng

| Số trang | Tên file | Lý do |
| --- | --- | --- |
| 2 | CV 261 CĐK&BTNN - thong bao chia se ket noi (1) | Text layer rỗng (bản scan) - để sau |
| ≥20 | 1006, 1201, HD_*, SOL, PDS, ... | Ngoài ngân sách trang của phase 1 |

## Định dạng file

```markdown
<!-- page: 1 -->

<nội dung trang 1>

<!-- page: 2 -->

<nội dung trang 2>
```

Quy tắc: Unicode NFC; strip khoảng trắng cuối mỗi dòng; gộp nhiều dòng trống liên tiếp thành một; giữ
nguyên block chữ ký số/"Người ký" nếu có trong text layer; trang rỗng (nếu có ở file không bị skip) vẫn
sinh marker trang, không có nội dung.

## Ngoài phạm vi

Không tạo ground truth COCO/bbox; không OCR fallback cho PDF scan; không tái cấu trúc markdown mạnh (suy
heading/table từ layout - điều này ngược lại với việc `<table>` markup **là** một yêu cầu ground truth có
chủ ý theo [Cấu phần 6](06-evaluation-harness.md), phase sau cần cập nhật lại điểm này); không đổi gì
trong `evaluate/` harness.

## Tiêu chí thành công

- 6 file `.md` tồn tại dưới `ground_truth/lpbank/` với đúng tên stem.
- Mỗi file bắt đầu bằng `<!-- page: 1 -->` và có một marker mỗi trang PDF.
- Spot-check: 200 ký tự đầu trang 1 khớp text layer của PDF.
- `CV 261` vắng mặt trong thư mục output, được liệt kê là bị bỏ qua trong tóm tắt chạy.

## Phase sau (ngoài phạm vi hiện tại)

PDF ≥20 trang; PDF scan (OCR hoặc chép tay thủ công, bắt đầu từ `CV 261`); cân nhắc bỏ metadata chữ ký nếu
việc đánh giá muốn chỉ tính phần nội dung chính ("body only").
