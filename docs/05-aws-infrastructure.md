# Cấu phần 5 - Hạ tầng AWS

Nguồn gốc (đã xoá, nội dung gộp vào đây): `superpowers/specs/2026-08-07-aws-deployment-design.md` (thiết kế
gốc, 15 service, có VPC riêng) + `2026-08-07-aws-services-roles.md` (bản đang chạy thật, 13 service, đã bỏ
tầng mạng riêng - viết sau, dựa trên bản gốc). Tài liệu này trình bày **trạng thái đang dùng** trước, phần
đã bỏ và điều kiện dựng lại ở cuối.
Tài liệu nguồn: [Cấu phần 1](01-nghien-cuu-chon-model.md) · [Cấu phần 4](04-core-pipeline-staged.md).

## Ràng buộc đã chốt

| Ràng buộc | Hệ quả lên thiết kế |
| --- | --- |
| Phục vụ cả thử nghiệm lẫn lần chạy chính | Hạ tầng phải rẻ khi nhàn rỗi, bung được khi cần |
| 1-2 người, không chuyên hạ tầng | Loại EKS, ECS, SageMaker |
| Chưa có dữ liệu thật (mới có mẫu trong `evaluate/`) | Dựng đường thử nghiệm trước, tầng ingest để sau |
| Vòng lặp dev tính bằng giây | GPU instance sống lâu, model nằm sẵn trong VRAM |
| M6 - GPU ≤ 24 GB VRAM | Dòng g5 (A10G 24GB) |

**Phương án: một EC2 GPU duy nhất, và một hàng đợi.** Đánh đổi đã chấp nhận: 2M trang trên một GPU mất
~23 ngày wall-clock thay vì ~8 ngày ([Cấu phần 1](01-nghien-cuu-chon-model.md) §IV) - đây là đánh đổi
**thời gian, không phải tiền** (chi phí vẫn trong ngân sách ~200-550 USD). Vẫn dùng SQS + DynamoDB thay vì
hàng đợi local, để scale sau này là đổi số lượng instance, không phải viết lại tầng job.

## Đọc trong 30 giây

```
PDF → S3 ocr-raw → Lambda bóc trang → SQS (2M message) → EC2 GPU rút từng batch
                                                        → S3 ocr-artifacts + DynamoDB checkpoint
```

Đơn vị công việc là **một trang**, không phải một file. Quyết định gốc này quyết định vì sao có SQS (hàng
đợi 2M phần tử), vì sao có DynamoDB (checkpoint mức trang), và vì sao không cần orchestrator nào cả (không
Step Functions, không Airflow).

## Danh sách 13 service (trạng thái đang chạy)

| Nhóm | Service | Lý do tồn tại |
| --- | --- | --- |
| Làm việc | EC2 `g5.2xlarge` | Chỗ duy nhất có GPU để chạy model OCR - cũng là máy dev, để vòng lặp dev tính bằng giây |
| Làm việc | Lambda `ocr-fanout` | Biến 1 file thành N page job |
| Điều phối | SQS `ocr-pagejobs` | Danh sách việc + retry + backpressure, gần như miễn phí vận hành |
| Điều phối | SQS `ocr-dlq` | Chỗ đổ trang chết, không chặn 1.999.999 trang còn lại |
| Dữ liệu | S3 `ocr-raw` | Nguồn sự thật input |
| Dữ liệu | S3 `ocr-artifacts` | Nguồn sự thật output |
| Trạng thái | DynamoDB `ocr-checkpoint` | Biết trang nào xong để chạy lại không tính lại |
| Trạng thái | DynamoDB `ocr-pagehash` | Biết trang nào trùng để không đốt GPU hai lần |
| Vận hành | CloudWatch Logs + Metrics (EMF) | Biết pipeline nhanh/chậm/sai ở đâu |
| Vận hành | CloudWatch Dashboard + Alarms | Biết **khi nào** phải nhìn, không phải nhìn liên tục |
| Vận hành | ECR | Image có sẵn model weights |
| Bảo mật | KMS | Khoá cho dữ liệu nằm yên |
| Bảo mật | SSM Session Manager | Vào máy mà không mở cổng nào |

### EC2 `g5.2xlarge` - không thay thế được

A10G 24GB · 8 vCPU · 32GB RAM · gp3 200GB · default VPC · có public IP. Chạy trọn bước 1→6 của một page
job. Lambda/Fargate không có GPU; EKS/ECS/SageMaker thêm nhiều khái niệm phải học để đổi lấy khả năng
(xếp nhiều service, backpressure có sẵn) mà workload một loại worker này không cần. `.2xlarge` chứ không
`.xlarge` vì render 300 DPI ngốn CPU/RAM. Dòng g5 (A10G) chứ không g6 (L4) vì băng thông bộ nhớ gấp đôi
(~600 vs ~300 GB/s) - sinh token tự hồi quy bị chặn bởi băng thông, không phải FLOPS. **Bỏ nó thì không còn
kiến trúc** - service duy nhất không thay thế được.

### Lambda `ocr-fanout`

Đọc PDF, tính `pdf_sha256`, đếm trang, tra checkpoint bỏ trang đã xong, đẩy phần còn lại vào SQS. Kích hoạt
bởi S3 event `ObjectCreated` - chạy đúng một lần/PDF. Container image (cần `pypdfium2`, native binary).
Cũng là chốt phát hiện PDF hỏng: bắt lỗi ngay lúc bóc trang, ghi thẳng DLQ, không tạo page job nào.

### SQS `ocr-pagejobs` - ba thứ miễn phí trong một service

Standard queue · visibility timeout 300s · `maxReceiveCount=3` → DLQ. Ba cơ chế đi kèm không cần viết code
riêng: **resume** (visibility timeout hết hạn = message tự quay lại queue, cộng checkpoint idempotent =
resume đúng nghĩa), **retry giới hạn** (`maxReceiveCount`), **backpressure** (worker rút theo nhịp của
chính nó). Standard chứ không FIFO vì mỗi trang độc lập, không cần thứ tự; at-least-once được checkpoint
DynamoDB xử lý.

### S3 `ocr-raw` / `ocr-artifacts`

Hai bucket vì lifecycle khác nhau: raw đóng băng được (→ Glacier Instant Retrieval sau xử lý), artifacts
thì không. `ocr-artifacts` chứa `.md` · COCO `.json` · parquet log-prob · `figures/{doc_sha256}/p{page:04d}/{ann_id}.png`
· `qa-report/`. **Không có bucket cho ảnh render 300 DPI** - cấm persist ([Cấu phần 1](01-nghien-cuu-chon-model.md)
§2.5 cấm, vì 2M trang ≈ 1,2 TB); đây cũng là lý do **không có cạnh nào giữa preprocess và OCR** trong sơ đồ
kết nối - chúng nằm trong cùng một process, ảnh không rời RAM.

### DynamoDB `ocr-checkpoint` / `ocr-pagehash`

`ocr-checkpoint`: khoá `pdf_sha256#page_index#pipeline_version` → làm cho chạy lại rẻ (chỉ trả tiền phần
chưa xong) và làm at-least-once của SQS trở nên vô hại. `pipeline_version` nằm trong khoá để đổi model
không phải xoá bảng. `ocr-pagehash`: khoá `page_sha256` → trang trùng (bìa, phụ lục lặp) tái dùng output cũ,
**bỏ qua GPU hoàn toàn**. Khác nhau ở chỗ: checkpoint theo *vị trí*, pagehash theo *nội dung*. Cả hai
on-demand billing (traffic từng đợt); DynamoDB chứ không RDS vì không có nhu cầu quan hệ.

### Vận hành & bảo mật

CloudWatch EMF (metric nhúng trong log JSON) thay Prometheus/Grafana - cùng số liệu, không thêm service
phải nuôi. Alarm quan trọng nhất: **worker đứng im** - biến 18 tiếng mất trắng thành 10 phút phát hiện.
ECR bake sẵn model weights vào image (thay EFS/FSx - chỉ một instance nên không có gì để chia sẻ). KMS
SSE-KMS cho cả hai bucket + cả hai bảng. SSM Session Manager thay bastion + SSH key - instance vẫn không
cần inbound rule nào (SSM Agent gọi ra), mọi phiên audit qua CloudTrail.

## Vòng đời một page job

1. PDF vào `ocr-raw` → S3 event bắn `ocr-fanout`.
2. Lambda tính `pdf_sha256`, đếm trang, tra checkpoint bỏ trang xong, đẩy `{pdf_sha256, s3_key, page_index, pipeline_version}` vào `ocr-pagejobs`.
3. Worker long-poll batch 8.
4. Mỗi trang: phát hiện text layer → render 300 DPI in-memory → orientation/deskew (giữ affine)/denoise. Tính `page_sha256`, tra pagehash - trùng thì tái dùng, bỏ qua GPU.
5. Cả batch vào model OCR một lần → bbox + nhãn + text/HTML/LaTeX + reading order + log-prob.
6. Adapter chuẩn hoá Document Model ([Cấu phần 4](04-core-pipeline-staged.md)), validate lxml+KaTeX/pylatexenc, crop hình lên `ocr-artifacts`, serialize `.md`+COCO, áp ngưỡng QA.
7. Ghi checkpoint, ghi pagehash, `DeleteMessage`.
8. Cuối run: DuckDB đọc parquet log-prob trên S3 → báo cáo QA.

## Xử lý lỗi

| Loại lỗi | Xử lý |
| --- | --- |
| Worker chết / instance bị thu hồi | Message hết visibility timeout, quay lại queue, checkpoint chặn xử lý trùng |
| Trang lỗi lặp 3 lần | Vào DLQ kèm `error_class`, không chặn phần còn lại |
| OOM trên GPU | Hạ độ phân giải, thử lại; vẫn OOM → DLQ |
| PDF hỏng | Lambda fanout bắt ngay, ghi thẳng DLQ, không tạo page job |
| Trang trắng | Không phải lỗi - checkpoint với output rỗng |
| Bảng/LaTeX không parse được | Không phải lỗi hạ tầng - hạ log-prob về 0, đẩy review queue |

## Những gì đã cân nhắc rồi loại

| Loại | Lý do |
| --- | --- |
| EKS / ECS on EC2 | Chi phí học không đổi lấy được gì ở workload một loại worker |
| AWS Batch | Hợp lý, nhưng EC2 trực tiếp cho phép instance dev và instance thật dùng chung cấu hình |
| Lambda / Fargate cho bước OCR | Không có GPU |
| SageMaker | Bắt học Estimator/Processing/serving contract, không cho backpressure hay page-level checkpoint |
| Athena + Glue | Parquet chỉ 1-3 GB; DuckDB đọc thẳng S3 là một dependency Python, không phải service |
| AMP + Managed Grafana | CloudWatch EMF cho cùng số liệu, không thêm service phải nuôi |
| RDS / Aurora, EFS / FSx | Không có nhu cầu quan hệ / không có gì để chia sẻ giữa nhiều instance |
| Step Functions / Airflow | S3 event + SQS đã làm hết việc điều phối; visibility timeout đã là retry |

## Hai thứ đã bỏ so với thiết kế gốc (15 service)

### 1. Tầng mạng riêng - VPC, subnet, NAT, IGW, 8 VPC endpoint, security group

Thiết kế gốc: VPC `10.0.0.0/16`, public subnet (NAT) + private subnet (EC2 GPU, ENI Lambda), gateway
endpoint cho S3/DynamoDB, interface endpoint cho SQS/ECR/CloudWatch/SSM - để M1 (offline, không gọi API
ngoài) được thoả cả ở mức mạng khi chạy trên cloud.

**Trạng thái hiện tại: đã bỏ.** Không VPC riêng, không NAT, không VPC Endpoint. EC2 chạy default VPC, **có
public IP**; Lambda chạy ngoài VPC (cold start ngắn hơn, không giới hạn ENI); mọi đường tới S3/DynamoDB/SQS/
ECR/CloudWatch/SSM đi qua public endpoint AWS, qua TLS.

**Cái mua được:** bớt 11 thứ phải dựng đúng (VPC, 2 subnet, route table, IGW, NAT, 8 endpoint, SG) - với
1-2 người không chuyên hạ tầng đây là phần dễ cấu hình sai và khó debug nhất (triệu chứng của endpoint
thiếu là "kết nối treo", không phải lỗi đọc được).

**Cái mất - cần biết rõ:** M1 **không còn** là bảo đảm về topology mạng, chỉ còn là bảo đảm về cấu hình IAM
+ transport (vẫn TLS, vẫn trong AWS). EC2 có public IP = có bề mặt tấn công từ Internet (dù SG mặc định
không mở inbound). **IAM trở thành ranh giới cách ly duy nhất** - sai một bucket policy hay instance profile
là mất cách ly, không có lớp thứ hai chặn lại.

**Dựng lại khi nào:** khi có dữ liệu thật (không phải mẫu `evaluate/`), M1 quay lại thành ràng buộc thật.
Dựng lại **không sửa gì trong pipeline** - cùng image, cùng code, cùng IAM role, chỉ đặt instance vào
private subnet + thêm 8 endpoint. Đây là lý do bỏ bây giờ là **hoãn**, không phải nợ kỹ thuật.

### 2. Tự tắt instance - EventBridge Scheduler + Lambda `ocr-idle-stop`

Thiết kế gốc: `cron(0 20 * * ? *)` giờ VN, bắn Lambda tắt EC2 **trừ khi** một trong hai chốt bật: queue còn
message, hoặc instance có tag `KeepAlive=true`. Hai chốt này khiến lịch tắt an toàn để bật vĩnh viễn - mục
đích là hoạt động lúc bạn **quên**, không phải lúc bạn nhớ bật nó.

**Trạng thái hiện tại: đã bỏ**, tắt EC2 sau mỗi phiên dev phải làm tay. `g5.2xlarge` chạy 24/7 là chi phí
lớn nhất của kiến trúc này. Rủi ro: quên tắt một cuối tuần là một hoá đơn không đổi lấy được gì. Không mất
dữ liệu nếu bị tắt giữa run (message quay lại queue, checkpoint chặn trùng) - mất tối đa một trang đang dở.
Đường lùi chỉ 2 service + 3 kết nối, dựng lại được bất cứ lúc nào mà không sửa gì trong pipeline.

## Để sau, không dựng bây giờ

- **Tầng mạng riêng** - khi có dữ liệu thật.
- **EventBridge Scheduler + Lambda tự tắt** - khi hoá đơn EC2 nhắc bạn hay quên.
- **Auto Scaling Group** - khi cần nhiều hơn một instance; launch template đã sẵn, chỉ đổi `desired capacity`.
- **SNS** - khi muốn alarm DLQ gửi email.
- **Tầng ingest** (DataSync/Direct Connect) - khi có corpus thật.
- **Athena/QuickSight** - khi có người ngoài team cần tự truy vấn báo cáo QA.

## Chưa kiểm chứng

| Việc | Ảnh hưởng nếu sai |
| --- | --- |
| Thông số và giá `g5.2xlarge` hiện hành | Chỉ đổi loại instance, kiến trúc không đổi |
| Model OCR có implementation tương thích vLLM hay không | Nếu không thì chạy HF `transformers` trong cùng container |
| Cách lấy per-token log-prob thật của model | Ảnh hưởng QA gating, không ảnh hưởng service nào |
| Throughput thật (chưa ai công bố trang/s) | Đổi ước tính 23 ngày - phải đo trước khi khoá kế hoạch chạy chính |
| **Schema `ocr-checkpoint`** - khoá phẳng chỉ `GetItem` được một trang, muốn biết "PDF này đang ở trang nào" phải `Scan` | Có thể là lỗi thiết kế thật - cân nhắc composite `pk=DOC#{sha}#v{ver}` + `sk=PAGE#{index:06d}` + item `sk=META` giữ counter |
| **Giới hạn tồn đọng SQS** - message hết hạn tối đa 14 ngày, một run 23 ngày không đẩy hết 2M message một lúc | Phải đặt `MessageRetentionPeriod` tối đa và fan-out theo đợt |
| Mã hoá volume gp3 | Thiết kế chỉ nói KMS cho S3/DynamoDB, chưa nói volume chứa model weights + log tạm |

Hai điểm "chưa kiểm chứng" cuối (schema checkpoint, giới hạn SQS) là điểm đáng chú ý nhất - có thể là lỗi
thiết kế thật, không chỉ chi tiết cấu hình, cần chốt trước khi chạy run chính.
