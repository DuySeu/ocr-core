# Kiến trúc triển khai OCR - vai trò từng cấu phần

Sơ đồ kiến trúc: [`kien-truc-trien-khai.drawio.svg`](kien-truc-trien-khai.drawio.svg)

Tài liệu theo luồng (repo hiện tại):

| File | Nội dung |
| --- | --- |
| [01-ocr.md](01-ocr.md) | Luồng 1 — OCR (`core/` + `orchestrate/`) |
| [02-trich-xuat.md](02-trich-xuat.md) | Luồng 2 — trích xuất → JSON (chưa implement) |
| [03-finetune.md](03-finetune.md) | Luồng 3 — fine-tune Tesseract LSTM |
| [04-evaluation.md](04-evaluation.md) | Metric chấm output các luồng |

Hệ thống gồm ba luồng nối tiếp nhau, mỗi luồng là một zone trên sơ đồ:

| Luồng | Nhiệm vụ | Đơn vị công việc |
| --- | --- | --- |
| 1 · OCR | Biến trang PDF thành văn bản có cấu trúc (`.md`, `.html`, COCO) và PDF tìm kiếm được | Một trang |
| 2 · Trích xuất thông tin | Biến văn bản có cấu trúc thành JSON theo schema nghiệp vụ | Một văn bản |
| 3 · Fine-tune | Đo chất lượng, thu mẫu lỗi, huấn luyện tăng cường, đưa model mới trở lại luồng 1 | Một đợt huấn luyện |

## 1 · Luồng OCR

| Cấu phần | Vai trò trong kiến trúc |
| --- | --- |
| **LPBank PDF** (ECM / MinIO → S3) | Nguồn vào. Tài liệu từ hệ thống quản lý văn bản được đưa vào vùng lưu trữ của pipeline |
| **Page orchestration** | Bóc mỗi PDF thành các job cấp trang, xếp vào hàng đợi, ghi checkpoint từng trang. Đây là cấu phần cho phép chạy lại chỉ phần chưa xong, và bảo đảm một trang không bị xử lý hai lần. Nó không đụng vào nội dung trang: đây là tầng điều khiển chạy trên hàng đợi/CPU, tách khỏi worker GPU - vì vậy nó là hộp hàng đợi trên sơ đồ chứ không phải một bước xử lý |
| **Preprocess (300 DPI, orientation, deskew)** | Ba bước trên cùng một ảnh trang, chạy trong bộ nhớ: dựng ảnh ở 300 DPI, xoay đúng chiều, làm thẳng trang bị nghiêng. Ảnh trung gian không ghi ra đĩa |
| **Chandra OCR 2** (GPU) | Đọc nội dung trang trong một lượt duy nhất: bố cục, thứ tự đọc, chữ, bảng, công thức. Trả kèm độ tin cậy (log-prob) cho từng phần đã đọc. Phiên bản model và hash weights được ghim ngay tại đây, và checkpoint mới từ luồng 3 cũng nạp vào đúng chỗ này - trong kiến trúc AWS nó là `pipeline_version` nằm trong khoá checkpoint (xem [kien-truc-aws.drawio](kien-truc-aws.drawio)), không phải một model registry dựng riêng |
| **Assemble** | Dựng output thô của model thành một `Document` hoàn chỉnh: nối caption vào hình, nối bảng tràn trang, chốt thứ tự đọc, gán id, validate. Bằng code, không có model - xem chi tiết ngay dưới bảng này |
| **Serialize** | Ghi đúng `Document` đó ra file: `.md` cho RAG, COCO cho bbox. Một lần OCR, nhiều định dạng |
| **QA gating** | Cổng chặn theo ngưỡng độ tin cậy. Đạt ngưỡng thì ghi thẳng kết quả; dưới ngưỡng thì chuyển sang đường kiểm tra của người |
| **Page review queue** | Người kiểm tra đọc, sửa và xác nhận những trang dưới ngưỡng. Bản đã sửa được ghi trở lại vào kết quả chung |
| **artifacts** | Vùng lưu trữ đối tượng (S3) chứa kết quả OCR: `.md`, `.html`, COCO, `.pdf` tìm kiếm được, hình đã cắt. Đây là nguồn dữ liệu cho cả luồng 2 và luồng 3 |
| **Build searchable PDF** | Phủ một lớp text vô hình lên ảnh trang, lấy chữ và toạ độ khối từ `artifacts`. Chạy cho **mọi trang đã hoàn tất**, không phân biệt trang tự đạt ngưỡng hay trang người kiểm tra đã sửa - bản sửa được ghi trở lại `artifacts` nên cả hai nhánh đều có mặt ở đó. Cho ra bản PDF nhìn y hệt bản gốc nhưng tra được bằng Ctrl+F trong mọi trình đọc PDF; ghi lại vào `artifacts` rồi đẩy ngược về ECM cho người dùng cuối |

### Assemble và Serialize

Chandra dừng lại ở đúng một chuỗi thô cho mỗi trang: HTML mang `data-bbox` và `data-label`, không hơn. Ba bước dưới đây biến chuỗi đó thành file dùng được, và cả ba đều là code xác định trong `core/` - cùng input cho ra cùng output, không tham số sinh, không tốn GPU. Model không tự làm bước nào trong số này.

| Bước | Việc cụ thể | Stage & module theo [luồng OCR](01-ocr.md) |
| --- | --- | --- |
| Adapter | Dịch output riêng của một provider về dạng chung: mỗi khối thành một element có bbox trong hệ toạ độ trang và nhãn theo bộ class DocLayNet. Đây là chỗ duy nhất phải viết lại nếu đổi sang model khác | stage 3-4, `core/layout/` + `core/recognize/` |
| Assemble | Nối caption vào hình, nối bảng bị cắt qua hai trang, chốt thứ tự đọc, gán id cho từng element, rồi validate bảng và công thức. Validate chỉ gắn cờ lỗi lên element, không sửa nội dung và không đụng vào điểm tin cậy - để QA gating phía sau còn đọc được tín hiệu gốc | stage 5, `core/document/` |
| Serialize | Đọc đúng một `Document` đó và ghi ra nhiều định dạng: `.md` cho RAG, COCO cho bbox. Một lần OCR, nhiều output - không chạy lại model cho mỗi định dạng | stage 6, `core/serialize/` |

Ba bước trên nằm gọn trong hai hộp của sơ đồ: adapter thuộc về hộp **Chandra OCR 2** vì nó là tầng dịch output của chính model đó (stage 3-4, chỗ duy nhất phải viết lại khi đổi model), còn validate là một bước bên trong **Assemble** chứ không phải một tầng riêng. Sơ đồ trước đây gộp cả ba vào một hộp tên "Adapter → Validate → Serialize", đọc lên tưởng ba bước ngang hàng và che mất ranh giới stage; hai hộp `Assemble` và `Serialize` khớp đúng hai stage cuối trong [luồng OCR](01-ocr.md) và tra thẳng ra được `core/document/` với `core/serialize/`.

### Searchable PDF

Cơ chế không có gì phức tạp: giữ nguyên ảnh trang làm phần nhìn thấy, rồi vẽ chữ đã OCR đè lên đúng vị trí của nó ở chế độ text render mode 3 - chế độ mà PDF quy định là "có chữ nhưng không hiển thị". Trang trông y hệt bản scan gốc, không thêm một pixel nào, nhưng Ctrl+F, copy và mọi công cụ đánh chỉ mục đều đọc được.

Trang nào được dựng PDF: **mọi trang trong `artifacts`**, không riêng trang đi qua người kiểm tra. Trang tự đạt ngưỡng QA đi thẳng vào `artifacts`, trang dưới ngưỡng thì người sửa rồi bản sửa cũng được ghi trở lại đó - nên cấu phần dựng PDF chỉ cần đọc `artifacts` và không phải biết trang đó đã đi nhánh nào.

Lớp text này ở **mức khối**, không phải mức từ, vì đó là độ mịn Chandra trả về: mỗi `<div>` một hộp. Hệ quả thực tế cần biết trước: tìm kiếm ra đúng trang và đúng đoạn, nhưng khi trình đọc bôi vàng kết quả thì nó sáng cả đoạn thay vì đúng chữ, và bôi đen chọn text trong một đoạn sẽ lệch. Muốn highlight đúng chữ thì phải có hộp mức từ - tức chạy thêm một engine dò chữ nữa rồi ghép với chữ của Chandra, việc này không nằm trong phạm vi hiện tại.

Ràng buộc quan trọng nhất nằm ở hệ toạ độ: **bbox Chandra trả về thuộc về ảnh đã tiền xử lý, không phải trang PDF gốc.** Ảnh đó đã được xoay đúng chiều và làm thẳng, nên phủ chữ theo toạ độ đó lên trang gốc chưa nắn sẽ lệch hộp. Bước preprocess hiện không ghi ảnh trung gian ra đĩa, nên tới lúc dựng PDF phải chọn một trong hai: giữ lại ảnh 300 DPI trong `artifacts`, hoặc dựng lại đúng ảnh đó bằng cùng tham số tiền xử lý. Không có đường thứ ba.

Phạm vi áp dụng hẹp hơn nhiều người tưởng: chỉ những tài liệu **không có sẵn text layer**. Phần lớn PDF LPBank đã có text layer và đọc thẳng ra chữ được, đúng cách [evaluation](04-evaluation.md) dựng ground truth; chỉ bản scan và tài liệu viết tay mới cần lớp text dựng từ OCR. Chạy lại cả kho là tốn công vô ích, và tệ hơn là ghi đè một text layer chuẩn bằng một lớp OCR kém chính xác hơn.

Về công cụ, PyMuPDF (`fitz`) làm được toàn bộ việc này trong một thư viện. Một điểm cần ghi nhận từ bây giờ để không phát hiện muộn lúc đóng gói: **PyMuPDF phát hành theo AGPL-3.0**, sản phẩm phân phối ra ngoài phải mua license thương mại của Artifex hoặc mở mã nguồn theo cùng giấy phép.

## 2 · Luồng trích xuất thông tin

Bốn nhánh trích xuất **không phải bốn bước của một chuỗi biến đổi dữ liệu**. Cả bốn nhận cùng một đầu vào - cây khối do `Parse HTML` dựng ra - nên chạy độc lập và song song được. Thứ duy nhất đi giữa chúng là **danh sách field chưa lấp được**: nhánh rẻ chạy trước, field nào còn trống mới rơi xuống nhánh đắt hơn. Nhờ vậy phần lớn khối lượng được giải bằng cách rẻ nhất, và model đắt nhất chỉ chạy trên phần còn lại.

| Cấu phần | Vai trò trong kiến trúc |
| --- | --- |
| **Business schema** | Khai báo cần lấy field nào cho từng loại văn bản, và mỗi field được phép xuất hiện ở đâu trong tài liệu. Phải có trước khi trích xuất, không phải sau |
| **Document type classifier** | Nhận diện quy chế / quyết định / thông báo / công văn để chọn đúng schema và đúng tuyến xử lý |
| **Parse HTML** | Dựng `.html` của bước OCR thành cây khối: phân cấp tiêu đề, bảng có `thead`/`tbody`, đoạn văn, kèm offset về văn bản gốc. Đây là đầu vào chung của cả bốn nhánh phía sau, và cũng là thứ quyết định cách cắt đoạn cho hai nhánh model |
| **Router theo field** | Đọc schema rồi giao mỗi field cho nhánh rẻ nhất giải được nó. Đây là nơi quyết định định tuyến, không phải một bước biến đổi dữ liệu |
| **HTML structure lookup** | Lấy field từ phân cấp tiêu đề và từ bảng có sẵn trong kết quả OCR. Không dùng model nào: kết quả cố định, kiểm chứng lại được, chi phí bằng 0. Đây là nơi lấy được các field nằm trong bảng như chữ ký hay phân cấp thẩm quyền |
| **Fuzzy anchor lookup** | Tìm chuỗi nhãn gần đúng (`Số:`, `Ngày ban hành:`, `Đơn vị chủ trì:`) rồi lấy phần theo sau. Chịu được lỗi dấu của OCR, chỗ regex thuần chết. Đây là nhánh duy nhất còn chạy được với công văn không có tiêu đề lẫn bảng |
| **NER zero-shot GLiNER** (CPU) | Trích các giá trị rời trong văn xuôi: tên đơn vị, tên người, số tiền, ngày, mã tham chiếu. Trả kèm vị trí ký tự nên truy vết được về đúng chỗ trong văn bản gốc |
| **LLM structured output** | Xử lý phần còn lại: field cần hiểu quan hệ giữa các giá trị, điều kiện, ngoại lệ, thông tin ẩn. Chỉ nhận đúng đoạn liên quan tới field đang lấy, không nhận cả tài liệu |
| **Merge theo schema** | Gom kết quả của cả bốn nhánh về một JSON, chuẩn hoá kiểu và định dạng (`"5 tỷ"` thành `5000000000`), rồi chấm độ tin cậy từng field. Đây là nơi duy nhất ghi ra kết quả cuối |
| **JSON schema** | Kết quả cuối: JSON đúng theo schema nghiệp vụ đã khai báo |
| **Field review queue** | Field không đủ tin cậy thì để trống và đánh dấu cho người kiểm tra, không đoán. Field trống thì người dùng biết mà xử lý; field sai thì đi thẳng vào quyết định nghiệp vụ |

## 3 · Luồng fine-tune

| Cấu phần | Vai trò trong kiến trúc |
| --- | --- |
| **LPBank ground truth** | Bộ dữ liệu chuẩn dùng làm mốc đối chiếu |
| **Quality metrics** | Chấm điểm kết quả trên ba trục: vị trí khối (IoU), độ chính xác chữ (CER/WER), độ chính xác bảng (TEDS) |
| **Error sampling** | Gom hai nguồn: trang có độ tin cậy thấp, và trang người kiểm tra đã sửa |
| **Labelling + train set** | Chuẩn hoá mẫu lỗi thành tập huấn luyện |
| **Fine-tune LoRA** (GPU) | Huấn luyện tăng cường trên đúng dữ liệu và đúng loại văn bản của đơn vị sử dụng. Áp được cho cả model OCR (Chandra) và model NER ở luồng 2. Checkpoint mới ghim thẳng vào **Chandra OCR 2** và được nạp ở lần chạy kế tiếp - đây là chỗ vòng phản hồi khép lại |

## Cách đọc sơ đồ

Trên sơ đồ, mỗi hộp chỉ ghi **tên cấu phần**. Vai trò và chi tiết của từng cấu phần nằm ở ba bảng phía trên, tra theo đúng tên đó. Ý nghĩa hình và màu:

| Ký hiệu | Nghĩa |
| --- | --- |
| Khung nét đứt | Một luồng (zone). Số 1 · 2 · 3 là thứ tự chạy |
| Nét liền | Luồng dữ liệu chính |
| Nét đứt | Phụ thuộc, phản hồi, hoặc chuyển phần việc còn lại. Ở luồng 2, nét đứt giữa bốn nhánh trích xuất chỉ chuyển **danh sách field chưa lấp được**, không chuyển dữ liệu đã trích |
| Nét đứt đỏ | Vòng phản hồi fine-tune |
| Hình thoi vàng | Cổng chặn theo ngưỡng hoặc điểm định tuyến, có nhiều nhánh ra khác nhau |
| Hình trụ xanh lá | Nơi lưu dữ liệu |
| Hộp tím | Hàng đợi |
| Hộp đỏ nhạt | Cấu phần có model |
| Hộp xanh dương | Cấu phần xử lý, không có model |
| Hộp cam | Nguồn vào từ ngoài hệ thống |

Luồng 1 chảy trái sang phải, luồng 2 chảy phải sang trái, luồng 3 chảy trái sang phải - kết quả của luồng trước rơi thẳng xuống điểm bắt đầu của luồng sau.

## Bốn tính chất then chốt của kiến trúc

**Đơn vị công việc là một trang, không phải một file.** Một trang lỗi không chặn phần còn lại; chạy lại chỉ trả chi phí cho phần chưa xong; thêm máy xử lý là đổi cấu hình, không phải viết lại.

**Hai chốt tin cậy trước khi ghi kết quả:** ngưỡng độ tin cậy, rồi người kiểm tra. Nguyên tắc là không đủ tin cậy thì không tự ý ghi ra kết quả. Chốt ngưỡng đứng trước để lọc bớt: chỉ phần dưới ngưỡng mới đi tới người, nhờ vậy số trang cần người xem giữ ở mức chấp nhận được.

**Chất lượng tăng theo thời gian.** Mỗi trang người kiểm tra sửa vừa là kết quả đúng ngay lập tức, vừa là một mẫu huấn luyện cho vòng fine-tune. Hệ thống dùng càng lâu thì tỉ lệ phải can thiệp tay càng giảm.

**Truy vết được đầu cuối.** Mỗi giá trị trích ra giữ vị trí của nó trong văn bản gốc, và phiên bản model được ghim kèm hash. Một kết quả đã duyệt có thể dựng lại y hệt về sau - điều kiện cần cho kiểm soát nội bộ.

## Triển khai theo giai đoạn

| Giai đoạn | Nội dung | Kết quả nhận được |
| --- | --- | --- |
| 1 | Luồng OCR + bộ đo chất lượng | Kết quả `.md` / `.html` / COCO và số đo chất lượng thật trên tài liệu của đơn vị |
| 2 | Chốt ngưỡng tin cậy + màn hình kiểm tra + searchable PDF | Kết quả có bảo đảm: phần dưới ngưỡng được người xác nhận trước khi dùng, và bản PDF tra cứu được đẩy ngược về ECM |
| 3 | Luồng trích xuất thông tin | JSON theo schema nghiệp vụ cho từng loại văn bản |
| 4 | Luồng fine-tune | Model riêng cho đơn vị, tỉ lệ can thiệp tay giảm dần theo từng đợt |

Hai số cần đo ở giai đoạn 1 vì chúng quyết định khối lượng của giai đoạn 2: **độ chính xác thật trên tài liệu của đơn vị**, và **tỉ lệ trang rơi xuống dưới ngưỡng tin cậy**. Ngưỡng ở QA gating được chốt sau khi có hai số này, không đặt trước.

Searchable PDF nằm ở giai đoạn 2 chứ không phải giai đoạn 1 dù kỹ thuật đã đủ từ sớm, vì đây là thứ đẩy ngược về ECM cho người dùng cuối tra cứu. Một bản PDF mang lớp text chưa qua chốt nào là kết quả tự ý ghi ra, trái với nguyên tắc hai chốt tin cậy ở trên. Khi đã có đủ hai chốt thì mọi trang nằm trong `artifacts` đều đã qua ít nhất một chốt - tự đạt ngưỡng tin cậy, hoặc được người xác nhận - nên dựng PDF cho toàn bộ `artifacts` là an toàn.
