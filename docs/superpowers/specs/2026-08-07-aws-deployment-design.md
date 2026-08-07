# Thiết kế triển khai AWS — pipeline OCR Chandra

Ngày: 2026-08-07
Trạng thái: Đã chốt thiết kế — chưa dựng
Phạm vi: **service AWS và cách chúng nối với nhau.** Không bao gồm cấu trúc code.
Tài liệu nguồn: [requirements analysis](../../2026-08-06-ocr-2m-pages-requirements-analysis.md) ·
[spec đường A](../../2026-08-07-chandra-pipeline-spec.md) ·
[sơ đồ hợp đồng logic](../../ocr-highlevel-contract.drawio.svg)

---

## Ràng buộc đã chốt

| Ràng buộc | Hệ quả lên thiết kế |
|---|---|
| Phục vụ **cả thử nghiệm lẫn lần chạy chính** | Hạ tầng phải rẻ khi nhàn rỗi, bung được khi cần |
| **1–2 người, không chuyên hạ tầng** | Loại EKS, loại ECS, loại SageMaker. Càng ít thứ phải vận hành càng tốt |
| **Chưa có dữ liệu thật** (mới có mẫu trong `evaluate/`) | Dựng đường thử nghiệm trước, tầng ingest để sau |
| **Vòng lặp dev tính bằng giây** | Cần GPU instance sống lâu, model nằm sẵn trong VRAM |
| M1 — offline, không gọi API ngoài | Dữ liệu không đi ra Internet: VPC endpoint cho mọi service |
| M6 — GPU ≤ 24 GB VRAM | Dòng g5 (A10G 24GB) |

**Phương án đã chọn: một EC2 GPU duy nhất.**

Đánh đổi đã biết và đã chấp nhận: một GPU chạy 2M trang mất **~23 ngày wall-clock** thay vì ~8 ngày.
`§IV` của tài liệu requirements đã có sẵn điểm này trên đường cong ("1× A100, 1 process → ~21 ngày").
Chi phí vẫn nằm trong ngân sách ~200–550 USD. Thứ đánh đổi là thời gian, không phải tiền.

Thiết kế vẫn dùng SQS + DynamoDB thay vì hàng đợi local, để việc scale sau này là đổi số lượng
instance chứ không phải viết lại tầng job. Ở quy mô thử nghiệm hai service này tốn vài xu.

---

## Danh sách service — 15 cái

### Compute

| Service | Cấu hình | Vai trò |
|---|---|---|
| **EC2** `g5.2xlarge` | A10G 24GB · 8 vCPU · 32GB RAM · gp3 200GB · private subnet · không public IP | Một container worker làm trọn bước 1→6 của sơ đồ hợp đồng. Cũng là máy dev. |
| **Lambda** `ocr-fanout` | Container image (cần `pypdfium2`) · trong VPC · 2GB · timeout 60s | Bóc PDF thành N page job. Chạy một lần cho mỗi PDF. |
| **Lambda** `ocr-idle-stop` | Zip · 128MB · timeout 30s | Tắt EC2 khi hết giờ, có hai chốt an toàn. Xem mục Tự tắt. |

Chọn `g5.2xlarge` chứ không phải `.xlarge`: render 300 DPI ngốn CPU và RAM, 8 vCPU đủ để vài luồng
render giữ cho GPU không đói. Chọn dòng g5 (A10G) chứ không phải g6 (L4) vì băng thông bộ nhớ gấp đôi
(~600 vs ~300 GB/s), mà sinh token tự hồi quy bị chặn bởi băng thông.

### Lưu trữ

| Service | Tên | Nội dung |
|---|---|---|
| **S3** | `ocr-raw` | PDF gốc. Lifecycle → Glacier IR sau khi xử lý xong. |
| **S3** | `ocr-artifacts` | `.md` · COCO `.json` · parquet log-prob · `figures/{doc_sha256}/p{page:04d}/{ann_id}.png` · `qa-report/` |
| **DynamoDB** | `ocr-checkpoint` | PK `pdf_sha256#page_index#pipeline_version` → status, output_key, logprob, error_class. On-demand billing. |
| **DynamoDB** | `ocr-pagehash` | PK `page_sha256` → output key đã có. Dedup theo `§2.5`. |

Hai bucket chứ không phải ba: lifecycle của raw và artifacts khác nhau, còn figures với output thì giống
nhau nên để chung prefix.

### Hàng đợi

| Service | Cấu hình |
|---|---|
| **SQS** `ocr-pagejobs` | Standard · visibility timeout 300s · `maxReceiveCount=3` |
| **SQS** `ocr-dlq` | Dead-letter. Phân loại lỗi: PDF hỏng · trang trắng · OOM · timeout |

Visibility timeout **chính là** cơ chế resume. Worker chết giữa trang thì message tự quay lại queue sau
5 phút và được nhặt lại. Cộng với checkpoint idempotent trong DynamoDB, mất tối đa một trang đang dở.
Không cần cơ chế retry nào khác.

### Vận hành & bảo mật

| Service | Vai trò |
|---|---|
| **CloudWatch Logs + Metrics (EMF)** | pages/s theo thời gian · latency từng bước · error rate theo loại · phân bố log-prob · tỉ lệ vào review |
| **CloudWatch Dashboard + Alarms** | queue depth · DLQ > 0 · worker đứng im · GPU utilisation |
| **ECR** | Image worker, bake sẵn model weights |
| **KMS** | SSE-KMS cho cả hai bucket và cả hai bảng DynamoDB |
| **SSM Session Manager** | Truy cập dev — không bastion, không SSH key, không public IP |
| **EventBridge Scheduler** | `cron(0 20 * * ? *)` · timezone `Asia/Ho_Chi_Minh` — bắn `ocr-idle-stop` 20:00 **mỗi ngày, kể cả cuối tuần** |

CloudWatch EMF thay cho Prometheus + Grafana: cùng số liệu, không thêm service phải nuôi.

### Tự tắt instance

EC2 trong thiết kế này vừa là máy dev vừa là worker, nên lịch tắt **không được phép giết một run đang
chạy**. EventBridge Scheduler không làm được điều kiện — universal target chỉ gọi được một API duy nhất —
nên nó bắn vào Lambda `ocr-idle-stop`, và Lambda đó tắt máy trừ khi một trong hai chốt bật:

| Chốt | Ý nghĩa |
|---|---|
| `ocr-pagejobs` còn message (visible + not visible > 0) | Đang có việc chạy dở, không tắt |
| Instance có tag `KeepAlive=true` | Cố ý giữ máy — phiên dev dài hoặc lần chạy chính |

Hai chốt này khiến lịch tắt an toàn để bật vĩnh viễn, mà đó mới là mục đích: nó phải hoạt động lúc bạn
**quên**, chứ không phải lúc bạn nhớ bật nó.

Nếu bị tắt nhầm giữa run thì cũng không mất dữ liệu — message quay lại queue, checkpoint chặn xử lý
trùng. Cái mất là thời gian wall-clock, và đó là lý do có chốt thứ hai.

Không đặt lịch **bật** máy: bật là hành động có chủ đích, tự bật chỉ tạo ra hoá đơn cho những ngày không
ai dùng.

### Mạng

VPC `10.0.0.0/16`, hai subnet:

- **Public subnet** — NAT Gateway. Chỉ dùng để pull image và vá OS.
- **Private subnet** — EC2 GPU, ENI của Lambda.

VPC Endpoints:

- **Gateway**: S3, DynamoDB
- **Interface**: SQS, ECR api, ECR dkr, CloudWatch Logs, SSM, SSMMessages, EC2Messages

Dữ liệu không đi ra Internet ở bất kỳ đường nào — đây là cách thoả M1 khi chạy trên cloud.
Security group của EC2: không có inbound, egress tới endpoint và NAT.

---

## Các kết nối

| # | Từ | Tới | Nhãn | Kiểu |
|---|---|---|---|---|
| 1 | Người dùng (`aws s3 sync`) | S3 `ocr-raw` | upload PDF | liền |
| 2 | S3 `ocr-raw` | Lambda `ocr-fanout` | S3 event `ObjectCreated` | liền |
| 3 | Lambda `ocr-fanout` | S3 `ocr-raw` | đọc, đếm trang, tính sha256 | liền |
| 4 | Lambda `ocr-fanout` | DynamoDB `ocr-checkpoint` | bỏ qua trang đã xong | đứt |
| 5 | Lambda `ocr-fanout` | SQS `ocr-pagejobs` | N page job | liền |
| 6 | EC2 worker | SQS `ocr-pagejobs` | long-poll, nhận batch 8 | liền |
| 7 | EC2 worker | S3 `ocr-raw` | đọc bytes trang | liền |
| 8 | EC2 worker | S3 `ocr-artifacts` | `.md` + COCO + parquet + crop hình | liền |
| 9 | EC2 worker | DynamoDB `ocr-checkpoint` | ghi checkpoint | đứt |
| 10 | EC2 worker | DynamoDB `ocr-pagehash` | ghi / tra dedup | đứt |
| 11 | EC2 worker | SQS `ocr-pagejobs` | `DeleteMessage` khi xong | đứt |
| 12 | SQS `ocr-pagejobs` | SQS `ocr-dlq` | fail 3 lần | đứt |
| 13 | EC2 worker | CloudWatch | log + EMF metric | đứt |
| 14 | ECR | EC2 worker | pull image | đứt |
| 15 | Người dùng | EC2 worker | SSM Session Manager (dev) | đứt |
| 16 | EventBridge Scheduler | Lambda `ocr-idle-stop` | 20:00 `Asia/Ho_Chi_Minh` | đứt |
| 17 | Lambda `ocr-idle-stop` | SQS `ocr-pagejobs` | đọc queue depth (chốt 1) | đứt |
| 18 | Lambda `ocr-idle-stop` | EC2 worker | đọc tag `KeepAlive`, gọi `StopInstances` | đứt |

**Không có cạnh nào giữa preprocess và OCR.** Chúng nằm trong cùng một process, ảnh 300 DPI không rời
RAM. `§2.5` cấm persist ảnh render — tách chúng thành hai service thì đúng 1,2 TB ảnh trung gian phải đi
qua mạng hoặc S3, tức là mất chính thứ thiết kế đang tránh.

---

## Vòng đời một page job

1. PDF vào `ocr-raw` → S3 event bắn Lambda `ocr-fanout`.
2. Lambda đọc PDF, tính `pdf_sha256`, đếm số trang, tra `ocr-checkpoint` để bỏ trang đã xong,
   đẩy phần còn lại vào `ocr-pagejobs`. Mỗi message = `{pdf_sha256, s3_key, page_index, pipeline_version}`.
3. Worker long-poll, nhận batch 8 message.
4. Với mỗi trang: phát hiện text layer → render 300 DPI in-memory → orientation, deskew (giữ affine),
   denoise. Tính `page_sha256`, tra `ocr-pagehash` — trùng thì tái dùng output cũ, bỏ qua GPU.
5. Cả batch đi vào Chandra một lần. Ra: bbox + nhãn + text/HTML/LaTeX + reading order + log-prob.
6. Adapter chuẩn hoá về Document Model, validate lxml + KaTeX, crop hình lên `ocr-artifacts`,
   serialize `.md` + COCO, áp ngưỡng QA.
7. Ghi `ocr-checkpoint`, ghi `ocr-pagehash`, `DeleteMessage`.
8. Cuối run: DuckDB đọc parquet log-prob trên S3, sinh báo cáo QA vào `ocr-artifacts/qa-report/`.

---

## Xử lý lỗi

| Loại lỗi | Cách xử lý |
|---|---|
| Worker chết / instance bị thu hồi | Message hết visibility timeout, quay lại queue, nhặt lại. Checkpoint idempotent nên không xử lý trùng. |
| Trang lỗi lặp lại 3 lần | Vào `ocr-dlq` kèm `error_class`. Không chặn 1.999.999 trang còn lại. |
| OOM trên GPU | Hạ độ phân giải, thử lại trong process. Vẫn OOM thì đẩy DLQ. |
| PDF hỏng | Lambda fanout bắt được ngay, ghi thẳng DLQ, không tạo page job. |
| Trang trắng | Không phải lỗi — ghi checkpoint với output rỗng. |
| Bảng không parse được / LaTeX không compile | Không phải lỗi hạ tầng. Hạ log-prob về 0, đẩy vào review queue. |

Đơn vị công việc là **trang**, không phải file. Một PDF 800 trang lỗi ở trang 700 không làm mất 699
trang đã xong.

---

## Những gì đã cân nhắc rồi loại

| Loại | Lý do |
|---|---|
| **EKS** | Sai với "1–2 người không chuyên hạ tầng". Chi phí học không đổi lấy được gì ở workload một loại worker. |
| **ECS on EC2** | 5 khái niệm thay vì 3. Giá trị của ECS là xếp nhiều service lên chung instance — ở đây chỉ có một worker và nó chiếm trọn GPU. |
| **AWS Batch** | Hợp lý (3 khái niệm, chạy trên chính ECS) nhưng ASG/EC2 trực tiếp cho phép instance dev và instance chạy thật dùng chung một cấu hình. Cùng container chạy trên Batch không sửa dòng nào nếu sau này đổi ý. |
| **Lambda cho bước OCR** | **Lambda không có GPU.** Chỉ dùng được cho fan-out. |
| **Fargate** | Không có GPU. |
| **SageMaker** | Bắt học một tập khái niệm riêng (Estimator, Processing, serving contract) để đổi lấy thứ không cần — nó không cho backpressure hay page-level checkpoint sẵn. |
| **Athena + Glue** | Parquet log-prob chỉ ~1–3 GB (`§2.7`). DuckDB đọc thẳng từ S3 làm cùng việc trong vài giây, là một dependency Python chứ không phải service. Bỏ được Glue catalog, crawler, một IAM role và một schema phải giữ đồng bộ. |
| **AMP + Managed Grafana** | CloudWatch EMF cho cùng số liệu mà không thêm service phải nuôi. |
| **RDS / Aurora** | Không có nhu cầu quan hệ, và là chi phí luôn chạy. |
| **EFS / FSx** | Model weights bake thẳng vào image. Chỉ có một instance nên không có gì để chia sẻ. |

---

## Để sau, không dựng bây giờ

- **Auto Scaling Group** — khi cần nhiều hơn một instance. Launch template đã sẵn, chỉ đổi `desired capacity`.
- **SNS** — gửi cảnh báo DLQ qua email.
- **Tầng ingest** (DataSync / Direct Connect) — khi có corpus thật.
- **Athena / QuickSight** — khi có người ngoài team cần tự truy vấn báo cáo QA.

---

## Chưa kiểm chứng

| Việc | Ảnh hưởng nếu sai |
|---|---|
| Thông số và giá `g5.2xlarge` | Chỉ đổi loại instance, kiến trúc không đổi. Cần tra lại giá hiện hành. |
| Chandra 2 có implementation tương thích vLLM hay không | Nếu không thì chạy HF `transformers` thẳng trong cùng container. Kiến trúc AWS không đổi. |
| Cách lấy per-token log-prob của Chandra 2 | Ảnh hưởng bước QA gating, không ảnh hưởng service nào. |
| Throughput thật của Chandra (chưa ai công bố trang/s) | Đổi ước tính 23 ngày. Phải đo trước khi khoá kế hoạch chạy chính. |

---

## Bước tiếp theo

Vẽ sơ đồ triển khai bằng skill `drawio-aws` từ danh sách service và bảng kết nối ở trên.

**Gợi ý bố cục**: trái = upload + Lambda `ocr-fanout` · giữa = VPC với một private subnet chứa EC2 GPU
(kèm ossBox `Chandra OCR 2 · vLLM` cạnh nó) · phải = S3 `ocr-artifacts` · dải dưới = CloudWatch, ECR,
KMS, SSM, EventBridge Scheduler + Lambda `ocr-idle-stop`. Gộp 8 VPC endpoint thành một icon `Endpoints`
để đỡ rối.
