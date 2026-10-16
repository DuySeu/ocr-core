# Đặc tả Benchmark Data: OCR

> Mục tiêu: định nghĩa **data**, **ground truth**, **các tầng đánh giá** và **metrics** cho từng cấu phần, để kết quả benchmark vừa cho biết hệ thống tốt đến đâu, vừa chỉ ra lỗi nằm ở tầng nào.

---

## OCR

### 1 Data

- File tài liệu gốc (ảnh/PDF), đúng như hệ thống nhận trên production: input cho cả 3 tầng (Detection & Layout, Recognition, Extraction & Structure)
- Schema trường cần trích xuất (tên field, kiểu dữ liệu, bắt buộc hay không): đánh giá tầng Extraction & Structure (Field P/R/F1, Document-level accuracy, Null accuracy)
- Quy tắc chuẩn hóa (ngày, số tiền, khoảng trắng, hoa/thường): áp dụng cho cả output và GT trước khi chấm CER/WER và field exact match
- Metadata (loại tài liệu, điều kiện ảnh): không dùng tính metric, dùng để chia nhóm khi báo cáo

### 2 Ground truth đề xuất

**JSON mẫu (1 tài liệu)**

```json
{
  "doc_id": "doc_001",
  "file": "docs/doc_001.jpg",
  "metadata": {"doc_type": "invoice", "source": "mobile_photo", "conditions": ["skewed", "stamp"]},
  "normalization_version": "norm-v1",
  "pages": [
    {
      "page": 1,
      "width": 1240,
      "height": 1754,
      "blocks": [
        {"block_id": "b1", "order": 1, "type": "text", "bbox": [80, 180, 600, 220], "content": "Số hóa đơn: 0001234"},
        {"block_id": "b2", "order": 2, "type": "table", "bbox": [80, 600, 1160, 980], "content": "<table><tr><td>...</td></tr></table>"}
      ],
      "full_text": "..."
    }
  ],
  "fields": {
    "invoice_number": "0001234",
    "issue_date": "2026-03-05",
    "total_amount": 1250000,
    "buyer_tax_code": null
  }
}
```

| Trường | Dùng cho metric |
|---|---|
| `blocks[].bbox` | Detection P/R/F1 |
| `blocks[].type`, `blocks[].order` | Region classification accuracy, Reading order accuracy |
| `blocks[].content` (vùng `type = text`), `full_text` | CER, WER |
| `blocks[].content` (vùng `type = table`, dạng HTML) | TEDS |
| `fields` (đã chuẩn hóa, `null` nếu tài liệu không có) | Field-level P/R/F1, Document-level accuracy, Null accuracy |
| `metadata` | Chia nhóm khi báo cáo |

**Cách xây dựng GT**

1. **Pre-label bằng model:** chạy một VLM mạnh (ví dụ Claude, GPT, Gemini) hoặc engine phân tích tài liệu (PaddleOCR, Docling, Azure Document Intelligence, Google Document AI) để sinh bbox, text, bảng HTML và `fields` theo schema. Dùng model khác với model đang được đánh giá.
2. **Người review:** import kết quả vào công cụ gán nhãn (Label Studio, CVAT) để sửa bbox, text, giá trị field. Sửa nhanh hơn nhiều so với gán từ đầu.
3. **Tài liệu tổng hợp (tùy chọn):** render tài liệu từ template + dữ liệu đã biết trước, thêm nhiễu (nghiêng, mờ, con dấu). Cách này có GT chính xác 100%, tham khảo SynthDoG (đi kèm paper Donut). Không thay thế hoàn toàn ảnh thật.
4. **Kiểm soát chất lượng:** 10–20% mẫu cho 2 người review độc lập để đo độ đồng thuận.

### 3 Các tầng đánh giá

| Tầng | Câu hỏi cần trả lời | Ghi chú |
|---|---|---|
| **1. Detection & Layout** | Có tìm đủ và đúng vùng chữ không? Phân loại vùng (tiêu đề, đoạn văn, bảng, con dấu) đúng không? Thứ tự đọc đúng không? | Không đo được nếu dùng model end-to-end (VLM đọc thẳng ra JSON), vì không có output trung gian |
| **2. Recognition** | Đọc đúng ký tự, đúng dấu tiếng Việt không? | Có thể cô lập bằng cách cắt ảnh theo bbox gold rồi cho model đọc |
| **3. Extraction & Structure** | Đưa đúng giá trị vào đúng trường không? Dựng lại bảng đúng không? Chuẩn hóa đúng không? | Đây là tầng gần với giá trị nghiệp vụ nhất |

### 4 Metrics đề xuất theo tầng

#### Tầng 1: Detection & Layout

| Metric | Ý nghĩa | Cách đánh giá |
|---|---|---|
| **Detection Precision / Recall / F1 @ IoU ≥ 0.5** | Recall: tìm được bao nhiêu % vùng chữ thật. Precision: bao nhiêu % vùng tìm được là vùng thật | So bbox dự đoán với `blocks[].bbox`. Một vùng tính là khớp khi IoU (diện tích giao / diện tích hợp) ≥ 0.5 |

#### Tầng 2: Recognition

| Metric | Ý nghĩa | Cách đánh giá |
|---|---|---|
| **CER (Character Error Rate)** | Tỷ lệ ký tự bị sai | So text dự đoán với `blocks[].content` / `full_text`: (S + D + I) / N, với S = thay thế, D = xóa, I = chèn, N = số ký tự trong GT |
| **WER (Word Error Rate)** | Tỷ lệ từ bị sai | Như CER nhưng tính theo từ |
| **TEDS (Tree Edit Distance based Similarity)** | Mức giống nhau giữa bảng dự đoán và bảng GT, tính cả cấu trúc lẫn nội dung ô | So HTML bảng dự đoán với `blocks[].content` (vùng `type = table`): TEDS = 1 − (tree edit distance / số node của cây lớn hơn), giá trị từ 0 đến 1 |

> Báo cáo CER/WER cả hai chế độ: **trước** và **sau** chuẩn hóa (theo `normalization_version`), để không phạt các khác biệt không quan trọng.

#### Tầng 3: Extraction & Structure

| Metric | Ý nghĩa | Cách đánh giá |
|---|---|---|
| **Field-level Precision / Recall / F1** | Precision: các trường đã trích ra đúng bao nhiêu %. Recall: các trường cần có trích được bao nhiêu % | So từng field output (sau chuẩn hóa) với `fields`, exact match |
| **Document-level accuracy** (tất cả trường đúng) | Bao nhiêu % tài liệu đúng hoàn toàn, không cần người sửa | Một tài liệu tính đúng khi mọi field bắt buộc đều khớp `fields` |
| **Null accuracy / Hallucinated field rate** | Khi tài liệu không có trường đó, model có trả về `null` không hay tự bịa | Trên các field có giá trị `null` trong `fields`, tính tỷ lệ output trả về giá trị khác `null` |

### 5 Các metrics khác có thể dùng thêm

| Metric | Ý nghĩa (khía cạnh khác) | Khi nào nên dùng |
|---|---|---|
| **Region classification accuracy** | Phân loại vùng (text/table/stamp…) đúng bao nhiêu %, so với `blocks[].type` | Khi tầng sau xử lý khác nhau theo loại vùng (ví dụ vùng bảng được đưa vào bước dựng bảng riêng) |
| **Reading order accuracy** (Kendall's tau hoặc edit distance trên chuỗi thứ tự) | Thứ tự đọc có giống người đọc không, so với `blocks[].order` | Tài liệu nhiều cột hoặc bố cục phức tạp, nhất là khi output OCR được đưa vào RAG |
| **Confidence calibration (ECE)** | Độ tin cậy model báo ra có khớp với tỷ lệ đúng thật không | Khi dùng confidence để quyết định chuyển người kiểm tra (human review) |
| **Latency / Cost per page, Throughput** | Thời gian và chi phí xử lý mỗi trang, số trang/phút | Luôn nên báo cáo kèm, để so sánh giữa các giải pháp |
