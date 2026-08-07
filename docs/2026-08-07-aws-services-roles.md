# Vai trò từng service AWS — pipeline OCR Chandra

Ngày: 2026-08-07
Phạm vi: **mỗi service làm gì, vì sao nó có mặt, nó nối với ai, và bỏ nó thì mất gì.**
Không bao gồm cấu trúc code, không bao gồm IaC.

Tài liệu nguồn: [thiết kế triển khai AWS](superpowers/specs/2026-08-07-aws-deployment-design.md) ·
[requirements analysis](2026-08-06-ocr-2m-pages-requirements-analysis.md) ·
[spec đường A](2026-08-07-chandra-pipeline-spec.md) ·
sơ đồ: `[2026-08-07-aws-deployment.drawio](2026-08-07-aws-deployment.drawio)`

---

## Đọc trong 30 giây

Kiến trúc này là **một hàng đợi và một worker**. Mọi thứ còn lại chỉ tồn tại để phục vụ hai thứ đó:

```
PDF → S3 ocr-raw → Lambda bóc trang → SQS (2M message) → EC2 GPU rút từng batch
                                                        → S3 ocr-artifacts + DynamoDB checkpoint
```

Đơn vị công việc là **một trang**, không phải một file. Đó là quyết định gốc — nó quyết định vì sao có SQS (hàng đợi 2M phần tử), vì sao có DynamoDB (checkpoint mức trang), và vì sao không cần orchestrator nào cả.

**13 service.** Chia theo lý do tồn tại:


| Nhóm       | Service                         | Lý do tồn tại trong một câu                                         |
| ---------- | ------------------------------- | ------------------------------------------------------------------- |
| Làm việc   | EC2 `g5.2xlarge`                | Chỗ duy nhất có GPU để chạy Chandra                                 |
| Làm việc   | Lambda `ocr-fanout`             | Biến 1 file thành N đơn vị công việc                                |
| Điều phối  | SQS `ocr-pagejobs`              | Giữ danh sách việc + cơ chế retry + backpressure, miễn phí vận hành |
| Điều phối  | SQS `ocr-dlq`                   | Chỗ đổ trang chết để nó không chặn 1.999.999 trang còn lại          |
| Dữ liệu    | S3 `ocr-raw`                    | Nguồn sự thật của input                                             |
| Dữ liệu    | S3 `ocr-artifacts`              | Nguồn sự thật của output                                            |
| Trạng thái | DynamoDB `ocr-checkpoint`       | Biết trang nào xong để chạy lại không tính lại                      |
| Trạng thái | DynamoDB `ocr-pagehash`         | Biết trang nào trùng để không đốt GPU hai lần                       |
| Vận hành   | CloudWatch Logs + Metrics (EMF) | Biết pipeline đang nhanh/chậm/sai ở đâu                             |
| Vận hành   | CloudWatch Dashboard + Alarms   | Biết **khi nào** phải nhìn vào, không phải nhìn liên tục            |
| Vận hành   | ECR                             | Chỗ đặt image có sẵn model weights                                  |
| Bảo mật    | KMS                             | Khoá cho dữ liệu nằm yên (at rest)                                  |
| Bảo mật    | SSM Session Manager             | Vào được máy mà không mở cửa nào                                    |


> **Tầng mạng riêng đã được lược bỏ** — không VPC riêng, không subnet, không NAT, không VPC Endpoint.
> Xem mục [Mạng — đã lược bỏ khỏi kiến trúc](#mạng--đã-lược-bỏ-khỏi-kiến-trúc) để biết đánh đổi.
> Tài liệu thiết kế gốc đếm 15 service (có thêm EventBridge Scheduler + Lambda `ocr-idle-stop`); cả hai
> cũng đã bỏ.

---



## Compute



### EC2 `g5.2xlarge` — worker và máy dev, cùng một máy


|              |                                                                                                                         |
| ------------ | ----------------------------------------------------------------------------------------------------------------------- |
| **Vai trò**  | Chạy trọn bước 1→6 của một page job: phát hiện text layer → render 300 DPI → tiền xử lý → Chandra → adapter → QA gating |
| **Cấu hình** | A10G 24GB VRAM · 8 vCPU · 32GB RAM · gp3 200GB · default VPC · có public IP                                             |
| **Nhận từ**  | SQS `ocr-pagejobs` (long-poll, batch 8) · S3 `ocr-raw` (bytes trang) · ECR (image)                                      |
| **Ghi tới**  | S3 `ocr-artifacts` · DynamoDB `ocr-checkpoint` · DynamoDB `ocr-pagehash` · CloudWatch · `DeleteMessage` về SQS          |


**Vì sao là EC2 chứ không phải gì khác.** Lambda và Fargate không có GPU — hết lựa chọn ngay ở đó. EKS và ECS thì thêm 2–5 khái niệm phải học để đổi lấy khả năng xếp nhiều service lên chung một instance, mà ở đây chỉ có một loại worker và nó chiếm trọn GPU. SageMaker bắt học Estimator/Processing/ serving contract để đổi lấy thứ nó không cho: backpressure và checkpoint mức trang.

**Vì sao** `.2xlarge` **chứ không** `.xlarge`**.** Render 300 DPI ngốn CPU và RAM. 8 vCPU đủ để vài luồng render chạy song song giữ cho GPU không đói — nếu CPU là cổ chai thì mua GPU to hơn cũng vô nghĩa.

**Vì sao dòng g5 (A10G) chứ không g6 (L4).** Băng thông bộ nhớ gấp đôi (~600 vs ~300 GB/s). Sinh token tự hồi quy bị chặn bởi băng thông bộ nhớ, không phải bởi FLOPS.

**Vì sao một instance.** 2M trang trên một GPU mất ~23 ngày wall-clock thay vì ~8 ngày. Đó là đánh đổi thời gian, không phải tiền — chi phí vẫn trong ngân sách ~200–550 USD. Khi cần nhanh hơn thì thêm instance, không phải viết lại tầng job.

**Nó vừa là worker vừa là máy dev** — đây là lựa chọn có chủ đích, để vòng lặp dev tính bằng giây:
model đã nằm trong VRAM, không phải nạp lại mỗi lần thử.

**Bỏ nó thì sao:** không còn kiến trúc. Đây là service duy nhất không thay thế được.

### Lambda `ocr-fanout` — biến 1 file thành N đơn vị công việc


|                     |                                                                                                     |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| **Vai trò**         | Đọc PDF, tính `pdf_sha256`, đếm số trang, tra checkpoint bỏ trang đã xong, đẩy phần còn lại vào SQS |
| **Cấu hình**        | Container image (cần `pypdfium2`) · ngoài VPC · 2GB RAM · timeout 60s                               |
| **Kích hoạt bởi**   | S3 event `ObjectCreated` trên `ocr-raw` — chạy một lần cho mỗi PDF                                  |
| **Message sinh ra** | `{pdf_sha256, s3_key, page_index, pipeline_version}`                                                |


**Vì sao đây là Lambda mà bước OCR thì không.** Fan-out là việc ngắn, thưa, không cần GPU, chạy đúng một lần cho mỗi file upload. Trả tiền theo lần gọi hợp hơn nuôi một process ngồi chờ. Bước OCR ngược lại: Lambda không có GPU, hết chuyện.

**Vì sao container image chứ không zip.** `pypdfium2` là native binary; đóng gói bằng image dễ hơn vật lộn với Lambda layer.

**Vì sao ngoài VPC.** Thiết kế gốc đặt nó trong VPC để đọc S3 qua gateway endpoint (yêu cầu M1). Khi tầng mạng riêng bị bỏ thì lý do đó mất, và chạy ngoài VPC lợi hơn: không phải cấp ENI nên cold start ngắn hơn, và không có hạn mức ENI nào phải lo khi nhiều PDF upload cùng lúc.

**Nó cũng là chốt phát hiện PDF hỏng.** Bắt được lỗi ngay lúc bóc trang, ghi thẳng DLQ, không tạo page job nào — rẻ hơn nhiều so với để worker phát hiện sau khi đã rút message.

**Bỏ nó thì sao:** worker phải tự bóc PDF, và mất tính chất "đơn vị công việc là trang" — một PDF 800 trang lỗi ở trang 700 lại làm mất 699 trang đã xong.

---



## Điều phối — hàng đợi



### SQS `ocr-pagejobs` — danh sách việc, cơ chế retry, và backpressure, trong một service


|                |                                                                            |
| -------------- | -------------------------------------------------------------------------- |
| **Vai trò**    | Giữ N page job đang chờ. Worker rút ra bằng long-poll                      |
| **Cấu hình**   | Standard queue · visibility timeout 300s · `maxReceiveCount=3` → `ocr-dlq` |
| **Nhận từ**    | Lambda `ocr-fanout`                                                        |
| **Bị đọc bởi** | EC2 worker (long-poll, batch 8)                                            |


**Đây là service làm nhiều việc nhất so với công sức cấu hình.** Ba thứ miễn phí đi kèm:

1. **Resume.** Visibility timeout *chính là* cơ chế resume. Worker chết giữa trang → message hết hạn ẩn
  sau 5 phút → tự quay lại queue → được nhặt lại. Không cần code retry, không cần state machine.
2. **Retry có giới hạn.** `maxReceiveCount=3` tự đẩy trang chết sang DLQ sau 3 lần. Không cần đếm tay.
3. **Backpressure.** Worker rút theo nhịp của chính nó. Không có ai đẩy việc vào nhanh hơn mức xử lý được.

**Vì sao 300s.** Phải dài hơn thời gian xử lý một batch 8 trang, đủ biên an toàn. Ngắn quá thì message quay lại queue khi worker vẫn đang làm → xử lý trùng (checkpoint chặn được, nhưng đốt GPU vô ích). Dài quá thì worker chết phải chờ lâu mới có ai nhặt lại việc.

**Vì sao Standard chứ không FIFO.** Không cần thứ tự — mỗi trang độc lập. Standard cho throughput không giới hạn và rẻ hơn. Nhược điểm là at-least-once delivery, nhưng checkpoint idempotent trong DynamoDB đã xử lý chuyện đó.

**Vì sao SQS chứ không hàng đợi local ở quy mô thử nghiệm.** Ở quy mô này SQS tốn vài xu. Cái nó mua được là: sau này scale = đổi số lượng instance, không phải viết lại tầng job.

**Bỏ nó thì sao:** mất cả resume, retry và backpressure. Phải tự viết ba thứ đó — và đó chính là ba thứ dễ viết sai nhất trong một job chạy 23 ngày.

### SQS `ocr-dlq` — chỗ đổ trang chết


|                   |                                                                                          |
| ----------------- | ---------------------------------------------------------------------------------------- |
| **Vai trò**       | Nhận message đã fail 3 lần, kèm `error_class` để phân loại                               |
| **Nhận từ**       | `ocr-pagejobs` (tự động, qua redrive policy) · Lambda `ocr-fanout` (PDF hỏng, ghi thẳng) |
| **Phân loại lỗi** | PDF hỏng · trang trắng · OOM · timeout                                                   |


**Vai trò thật của nó là *không chặn*.** Một trang không xử lý được không được phép làm dừng
1.999.999 trang còn lại. DLQ là cách biến "lỗi chặn pipeline" thành "một dòng trong danh sách phải
xem lại sau".

Lưu ý: **trang trắng không phải lỗi** — nó được ghi checkpoint với output rỗng, không vào DLQ. Bảng không parse được hay LaTeX không compile cũng không phải lỗi hạ tầng — chúng bị hạ log-prob về 0 và đẩy vào review queue.

**Bỏ nó thì sao:** message fail sẽ quay lại queue vô hạn, worker đốt GPU lặp lại trên đúng những trang không bao giờ xong.

---

## Dữ liệu — lưu trữ

### S3 `ocr-raw` — nguồn sự thật của input


|                |                                                                         |
| -------------- | ----------------------------------------------------------------------- |
| **Nội dung**   | PDF gốc, y như lúc upload                                               |
| **Lifecycle**  | → Glacier Instant Retrieval sau khi xử lý xong                          |
| **Nhận từ**    | Người dùng (`aws s3 sync`)                                              |
| **Bị đọc bởi** | Lambda `ocr-fanout` (đếm trang, sha256) · EC2 worker (bytes từng trang) |
| **Kích hoạt**  | S3 event `ObjectCreated` → Lambda `ocr-fanout`                          |


**S3 event là thứ làm pipeline tự chạy.** Không có scheduler, không có ai bấm nút: upload xong là pipeline bắt đầu. Đây là lý do không cần Step Functions hay Airflow.

**Vì sao Glacier IR chứ không Deep Archive.** Instant Retrieval vẫn cho đọc ngay (không chờ hàng giờ) — cần thiết vì có thể phải chạy lại một PDF với `pipeline_version` mới.

### S3 `ocr-artifacts` — nguồn sự thật của output


|                |                                                                                                          |
| -------------- | -------------------------------------------------------------------------------------------------------- |
| **Nội dung**   | `.md` · COCO `.json` · parquet log-prob · `figures/{doc_sha256}/p{page:04d}/{ann_id}.png` · `qa-report/` |
| **Nhận từ**    | EC2 worker                                                                                               |
| **Bị đọc bởi** | DuckDB (cuối run, đọc parquet log-prob sinh báo cáo QA)                                                  |


**Vì sao hai bucket chứ không ba.** Lifecycle của raw và artifacts khác nhau (raw đóng băng được, artifacts thì không) nên phải tách. Còn `figures/` với output text thì lifecycle giống nhau, để chung một bucket khác prefix là đủ.

**Vì sao parquet cho log-prob.** Chỉ ~1–3 GB tổng. DuckDB đọc thẳng từ S3 xong trong vài giây. Không cần Athena + Glue — bỏ được Glue catalog, crawler, một IAM role và một schema phải giữ đồng bộ, đổi lấy một dependency Python.

**Vì sao không có bucket cho ảnh render 300 DPI.** Vì `§2.5` cấm persist chúng. 2M trang ảnh 300 DPI là ~1,2 TB — nếu tách preprocess và OCR thành hai service thì đúng 1,2 TB đó phải đi qua mạng hoặc S3. Đây là lý do **không có cạnh nào giữa preprocess và OCR trong sơ đồ**: chúng nằm trong cùng một process, ảnh không rời RAM.

### DynamoDB `ocr-checkpoint` — biết trang nào đã xong


|                |                                                    |
| -------------- | -------------------------------------------------- |
| **Khoá chính** | `pdf_sha256#page_index#pipeline_version`           |
| **Giá trị**    | `status`, `output_key`, `logprob`, `error_class`   |
| **Billing**    | On-demand                                          |
| **Ghi bởi**    | EC2 worker (sau mỗi trang)                         |
| **Đọc bởi**    | Lambda `ocr-fanout` (bỏ trang đã xong khi fan-out) |


**Nó làm cho việc chạy lại trở nên rẻ.** Chạy lại một PDF 800 trang đã xong 700 trang thì chỉ tốn 100 trang GPU, không phải 800.

**Nó cũng là thứ làm at-least-once của SQS trở nên vô hại.** Message bị nhận hai lần → worker thấy checkpoint đã có → bỏ qua. Đây là lý do không cần FIFO queue và không cần exactly-once ở bất kỳ đâu.

**Vì sao** `pipeline_version` **nằm trong khoá.** Đổi version pipeline = một tập checkpoint mới, output cũ không bị nhầm là đã xong. Không có nó thì mọi lần nâng cấp model đều phải xoá bảng.

**Vì sao on-demand.** Traffic là từng đợt (chạy rồi nghỉ). Provisioned capacity là hoá đơn cho những ngày không ai chạy gì.

**Vì sao DynamoDB chứ không RDS/Aurora.** Không có nhu cầu quan hệ nào — chỉ là key → value. Và RDS là chi phí luôn chạy.

### DynamoDB `ocr-pagehash` — biết trang nào trùng


|                 |                                                                |
| --------------- | -------------------------------------------------------------- |
| **Khoá chính**  | `page_sha256`                                                  |
| **Giá trị**     | Output key đã có                                               |
| **Đọc/ghi bởi** | EC2 worker, sau khi render + tiền xử lý, **trước khi** gọi GPU |


**Đây là service tiết kiệm tiền trực tiếp.** Trang trùng (bìa, trang trắng có watermark, phụ lục lặp, cùng một file upload hai lần) tái dùng output cũ và **bỏ qua GPU hoàn toàn**. Ở corpus 2M trang, tỉ lệ trùng vài phần trăm cũng là vài ngày wall-clock.

Khác `ocr-checkpoint` ở chỗ: checkpoint theo *vị trí* (file nào, trang nào), pagehash theo *nội dung*.
Hai trang khác file mà giống nội dung thì checkpoint không biết, pagehash biết.

---



## Mạng — đã lược bỏ khỏi kiến trúc

Đây chỉ là một OCR pipeline, không phải một hệ thống nhận request từ ngoài. Nên tầng mạng riêng đã
được bỏ: **không VPC riêng, không subnet, không NAT Gateway, không Internet Gateway, không VPC Endpoint,
không security group tự định nghĩa.**

Cấu hình còn lại:

| | |
|---|---|
| **EC2** | Default VPC, subnet mặc định, **có public IP** |
| **Lambda `ocr-fanout`** | Chạy ngoài VPC — không ENI, cold start ngắn hơn |
| **Đường tới S3 / DynamoDB / SQS / ECR / CloudWatch / SSM** | Public endpoint của AWS, qua TLS |

**Cái mua được.** Bỏ được 11 thứ phải dựng và giữ đúng (VPC, 2 subnet, route table, IGW, NAT, 8 endpoint,
SG) — với 1–2 người không chuyên hạ tầng thì đây là phần dễ cấu hình sai nhất và cũng là phần khó debug
nhất: triệu chứng của một endpoint thiếu là "kết nối treo", không phải một lỗi đọc được. Bỏ NAT Gateway
cũng bỏ luôn một khoản phí theo giờ cộng phí mỗi GB.

**Cái mất — cần biết rõ.**

| | |
|---|---|
| **M1 không còn được thoả ở mức mạng** | M1 nói dữ liệu không đi ra Internet. Traffic tới S3/DynamoDB/SQS giờ đi qua public endpoint của AWS. Vẫn TLS, vẫn trong hạ tầng AWS, nhưng **không còn là một bảo đảm về topology** — nó là một bảo đảm về cấu hình IAM và transport |
| **EC2 có public IP** | Bề mặt tấn công từ Internet, dù security group mặc định không mở inbound nào |
| **Không có ranh giới mạng để dựa vào** | Toàn bộ việc cách ly giờ nằm ở IAM: bucket policy, table policy, instance profile. Sai một policy là mất cách ly, không có lớp thứ hai chặn lại |

**SSM vẫn hoạt động** — SSM Agent *gọi ra* tới public endpoint của SSM qua Internet egress, không cần
interface endpoint. Vẫn không cần inbound rule, không cần bastion, không cần SSH key.

**Dựng lại khi nào.** Khi có dữ liệu thật (không phải mẫu trong `evaluate/`), M1 quay lại thành ràng buộc
thật và tầng mạng phải dựng lại. Việc dựng lại **không sửa gì trong pipeline** — cùng image, cùng code,
cùng IAM role; chỉ là đặt instance vào private subnet và thêm 8 endpoint. Đó là lý do bỏ nó bây giờ
không phải là nợ kỹ thuật, chỉ là hoãn.

---



## Vận hành



### CloudWatch Logs + Metrics (EMF) — nhìn thấy pipeline


|             |                                                                                                         |
| ----------- | ------------------------------------------------------------------------------------------------------- |
| **Nhận từ** | EC2 worker (log + embedded metric)                                                                      |
| **Số liệu** | pages/s theo thời gian · latency từng bước · error rate theo loại · phân bố log-prob · tỉ lệ vào review |


**EMF (Embedded Metric Format) là mẹo ở đây:** worker ghi metric *nhúng trong dòng log JSON*, CloudWatch tự bóc ra thành metric. Nghĩa là một đường ghi duy nhất cho cả log và metric — không cần StatsD, không cần sidecar, không cần Prometheus scrape endpoint.

**Vì sao không phải Prometheus + Grafana (hoặc AMP + Managed Grafana).** Cùng số liệu, nhưng thêm service phải nuôi. Với 1–2 người không chuyên hạ tầng, mỗi service thêm vào là một thứ có thể hỏng lúc 2 giờ sáng ngày thứ 19 của một run 23 ngày.

**Phân bố log-prob là số liệu quan trọng nhất ở đây** — nó là thứ quyết định trang nào vào review.
Không đo nó thì không biết chất lượng output cho tới khi có người đọc tay.

### CloudWatch Dashboard + Alarms — biết *khi nào* phải nhìn


| Alarm           | Nó phát hiện                                           |
| --------------- | ------------------------------------------------------ |
| Queue depth     | Pipeline nhanh/chậm hơn dự kiến, hoặc fan-out chạy sai |
| DLQ > 0         | Có trang chết — cần xem `error_class`                  |
| Worker đứng im  | Process treo, GPU hang, hoặc instance bị thu hồi       |
| GPU utilisation | GPU đói (CPU là cổ chai) hoặc GPU nghẽn (batch quá to) |


**Đây là service tách "có số liệu" khỏi "biết mình cần nhìn vào".** Trong một run 23 ngày, không ai mở dashboard mỗi giờ. "Worker đứng im" là alarm đáng giá nhất: nó biến 18 tiếng mất trắng thành 10 phút.

### ECR — image có sẵn model weights


|                 |                                                          |
| --------------- | -------------------------------------------------------- |
| **Nội dung**    | Image worker, **bake sẵn model weights vào trong image** |
| **Bị pull bởi** | EC2 worker (qua public endpoint của ECR)                 |


**Bake weights vào image là quyết định thay thế cho EFS/FSx.** Chỉ có một instance nên không có gì để chia sẻ giữa các máy. Weights nằm trong image nghĩa là: image chạy được là model chạy được, không có bước "tải weights" nào có thể fail lúc khởi động.

**Cùng image đó chạy được trên AWS Batch không sửa dòng nào** — đây là lý do tài liệu thiết kế loại Batch mà vẫn giữ đường lùi: nếu sau này đổi ý, container không phải viết lại.

### KMS — khoá cho dữ liệu nằm yên


|             |                                                      |
| ----------- | ---------------------------------------------------- |
| **Vai trò** | SSE-KMS cho cả hai bucket S3 và cả hai bảng DynamoDB |


Không phải service "làm gì" trong luồng dữ liệu — nó là điều kiện để dữ liệu ở trạng thái nghỉ được mã hoá bằng khoá mình kiểm soát, thay vì khoá do AWS quản lý hoàn toàn. Đánh đổi là mỗi lời gọi `GetObject`/`GetItem` kéo theo một lời gọi KMS ở phía service.

### SSM Session Manager — vào máy mà không mở cửa nào


|               |                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------ |
| **Vai trò**   | Đường truy cập dev duy nhất vào EC2                                                                    |
| **Điều kiện** | SSM Agent trên instance · instance profile có quyền SSM · Internet egress (không cần VPC endpoint) |


**Nó thay thế hai thứ:** không bastion host (một instance nữa phải vá), không SSH key (một secret nữa phải giữ). Thứ thứ ba — "không public IP" — đã mất khi bỏ tầng mạng: instance giờ có public IP để egress ra được.

Cơ chế: SSM Agent *gọi ra* tới endpoint của SSM, phiên đi ngược qua kênh đó. Nên **instance vẫn không cần một inbound rule nào** — đây là điểm còn giữ được: có public IP không có nghĩa là có cổng mở. Security group mặc định không cho inbound, và không cần sửa nó.

**Phụ phẩm miễn phí:** mọi phiên đều audit được qua CloudTrail. SSH thì không.

---

## Ai gọi ai — 16 kết nối

| # | Từ | Tới | Nhãn | Kiểu |
|---|---|---|---|---|
| 1 | Người dùng (`aws s3 sync`) | S3 `ocr-raw` | upload PDF | liền |
| 2 | S3 `ocr-raw` | Lambda `ocr-fanout` | S3 event `ObjectCreated` | liền |
| 3 | Lambda `ocr-fanout` | SQS `ocr-pagejobs` | N page job | liền |
| 4 | SQS `ocr-pagejobs` | EC2 worker | long-poll, batch 8 | liền |
| 5 | EC2 worker | S3 `ocr-artifacts` | artifacts + crop hình | liền |
| 6 | Lambda `ocr-fanout` | S3 `ocr-raw` | đọc PDF, đếm trang, sha256 | đứt |
| 7 | Lambda `ocr-fanout` | DynamoDB `ocr-checkpoint` | bỏ trang đã xong | đứt |
| 8 | EC2 worker | S3 `ocr-raw` | đọc bytes trang | đứt |
| 9 | EC2 worker | DynamoDB `ocr-checkpoint` | ghi checkpoint | đứt |
| 10 | EC2 worker | DynamoDB `ocr-pagehash` | tra / ghi dedup | đứt |
| 11 | EC2 worker | SQS `ocr-pagejobs` | `DeleteMessage` khi xong | đứt |
| 12 | SQS `ocr-pagejobs` | SQS `ocr-dlq` | fail 3 lần | đứt |
| 13 | EC2 worker | CloudWatch | log + EMF metric | đứt |
| 14 | ECR | EC2 worker | pull image | đứt |
| 15 | SSM Session Manager | EC2 worker | phiên dev | đứt |
| 16 | KMS | S3 + DynamoDB | SSE-KMS | đứt |

**Liền = luồng chính của một page job. Đứt = đọc/ghi phụ, vận hành, hoặc chính sách.**

Điều đáng chú ý là **cái không có trong bảng**: không có cạnh nào giữa preprocess và OCR. Chúng ở cùng
một process. Tách ra thành hai service là ném 1,2 TB ảnh trung gian qua mạng.

---

## Đã cân nhắc rồi loại

| Loại | Lý do một câu |
|---|---|
| **EKS** | Chi phí học không đổi lấy được gì ở workload một loại worker |
| **ECS on EC2** | 5 khái niệm thay vì 3, để đổi lấy khả năng xếp nhiều service lên chung instance — ở đây chỉ có một |
| **AWS Batch** | Hợp lý, nhưng EC2 trực tiếp cho phép instance dev và instance chạy thật dùng chung cấu hình |
| **Lambda cho bước OCR** | Lambda không có GPU |
| **Fargate** | Không có GPU |
| **SageMaker** | Bắt học Estimator/Processing/serving contract, không cho backpressure hay page-level checkpoint |
| **Athena + Glue** | Parquet chỉ 1–3 GB; DuckDB làm cùng việc và là một dependency, không phải một service |
| **AMP + Managed Grafana** | CloudWatch EMF cho cùng số liệu mà không thêm service phải nuôi |
| **RDS / Aurora** | Không có nhu cầu quan hệ, và là chi phí luôn chạy |
| **EFS / FSx** | Weights bake vào image; chỉ có một instance nên không có gì để chia sẻ |
| **Step Functions / Airflow** | S3 event + SQS đã làm hết việc điều phối; visibility timeout đã là retry |
| **VPC riêng + 8 endpoint** | Xem mục Mạng — bỏ vì đây chỉ là một OCR pipeline, không nhận request từ ngoài |

---

## Hai thứ đã bỏ so với thiết kế gốc

Tài liệu thiết kế có 15 service. Kiến trúc hiện tại có 13, và không có tầng mạng riêng.

### 1. Tự tắt instance — EventBridge Scheduler + Lambda `ocr-idle-stop`

Cơ chế cũ: bắn lúc 20:00 hằng ngày, tắt EC2 **trừ khi** một trong hai chốt bật — queue còn message, hoặc
instance có tag `KeepAlive=true`.

| | |
|---|---|
| **Việc phải làm tay** | Tắt EC2 sau mỗi phiên dev. `g5.2xlarge` chạy 24/7 là chi phí lớn nhất của kiến trúc này — và nó phát sinh chính xác vào những ngày không ai dùng |
| **Rủi ro** | Quên tắt một cuối tuần là một hoá đơn không đổi lấy được gì |
| **Không mất dữ liệu** | Nếu bị tắt giữa run: message quay lại queue sau 300s, checkpoint chặn xử lý trùng. Mất tối đa một trang đang dở |
| **Đường lùi** | Chỉ là 2 service và 3 kết nối — dựng lại được bất cứ lúc nào mà không sửa gì trong pipeline |

### 2. Tầng mạng riêng — VPC, subnet, NAT, IGW, 8 endpoint, security group

Chi tiết ở mục [Mạng](#mạng--đã-lược-bỏ-khỏi-kiến-trúc). Tóm lại: bớt 11 thứ phải dựng đúng, đổi lấy
việc M1 không còn là bảo đảm về topology và EC2 có public IP.

**Điểm chung của hai lần bỏ này:** cả hai đều bỏ được mà không sửa một dòng nào trong pipeline. Đó là
tiêu chí để một thứ được xếp vào "hoãn" chứ không phải "nợ kỹ thuật".

---

## Để sau, không dựng bây giờ

| Service | Khi nào cần |
|---|---|
| **Tầng mạng riêng** | Khi có dữ liệu thật — M1 quay lại thành ràng buộc thật |
| **EventBridge Scheduler + Lambda tự tắt** | Khi hoá đơn EC2 nhắc bạn rằng bạn hay quên |
| **Auto Scaling Group** | Khi cần nhiều hơn một instance. Launch template đã sẵn, chỉ đổi `desired capacity` |
| **SNS** | Khi muốn alarm DLQ gửi email thay vì chỉ hiện trên dashboard |
| **Tầng ingest** (DataSync / Direct Connect) | Khi có corpus thật, không phải mẫu trong `evaluate/` |
| **Athena / QuickSight** | Khi có người ngoài team cần tự truy vấn báo cáo QA |

---

## Chưa kiểm chứng

Từ tài liệu thiết kế — mỗi dòng đều là "đổi con số, không đổi kiến trúc":

| Việc | Ảnh hưởng nếu sai |
|---|---|
| Thông số và giá `g5.2xlarge` | Chỉ đổi loại instance |
| Chandra 2 có implementation tương thích vLLM hay không | Nếu không thì chạy HF `transformers` trong cùng container |
| Cách lấy per-token log-prob của Chandra 2 | Ảnh hưởng bước QA gating, không ảnh hưởng service nào |
| Throughput thật của Chandra (chưa ai công bố trang/s) | Đổi ước tính 23 ngày — phải đo trước khi khoá kế hoạch chạy chính |

Bốn điểm phát sinh khi viết tài liệu này, **chưa có trong thiết kế, cần chốt lúc dựng**:

| Việc | Vì sao cần quyết |
|---|---|
| **Schema `ocr-checkpoint`** | Khoá phẳng `pdf_sha256#page_index#pipeline_version` chỉ `GetItem` được một trang; muốn biết "PDF này đang ở trang nào" phải `Scan`. Cần đổi sang composite `pk = DOC#{sha}#v{ver}` + `sk = PAGE#{index:06d}` cộng một item `sk = META` giữ counter tiến độ |
| **Giới hạn tồn đọng trong SQS** | Message SQS hết hạn sau 4 ngày (mặc định), tối đa 14. Một run 23 ngày không thể đẩy hết 2M message một lúc — phải đặt `MessageRetentionPeriod` lên tối đa và fan-out theo đợt |
| **Mã hoá volume gp3** | Thiết kế chỉ nói KMS cho S3 và DynamoDB. Model weights và log tạm nằm trên volume này |
| **IAM là ranh giới duy nhất** | Sau khi bỏ tầng mạng, không còn lớp thứ hai chặn lại nếu một bucket policy hay instance profile sai. Cần review IAM chặt hơn mức bình thường |

Hai điểm đầu là điểm đáng chú ý nhất — chúng có thể là lỗi thiết kế thật, không chỉ là chi tiết cấu hình.
