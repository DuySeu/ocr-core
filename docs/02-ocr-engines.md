# Cấu phần 2 - OCR Engines (recognizer backend)

Nguồn gốc: `plans/2026-06-02-paddleocr-vietnamese-engine-design.md` + `plans/2026-06-04-easyocr-multilang-engine-design.md` (cả hai đã xoá, nội dung gộp vào đây).
Trạng thái: **còn hiệu lực** - `core/engines/` không bị đụng tới trong lần refactor staged pipeline ([Cấu phần 4](04-core-pipeline-staged.md) ghi rõ "engines/ KHÔNG SỬA").

## Vai trò

`core/engines/` là tầng adapter mỏng cho các OCR backend nhận dạng ký tự (text recognition), đứng sau interface `OCREngine` chung. Ba engine: `tesseract` (mặc định ban đầu), `paddleocr` (opt-in, tiếng Việt tốt hơn), `easyocr` (opt-in, trộn VI+EN trong cùng tài liệu). Cả ba đều **không đạt tiêu chí M7 chữ viết tay ≥ 50%** ([Cấu phần 1](01-nghien-cuu-chon-model.md)) nên không phải đường chính cho corpus hành chính scan - chúng phục vụ đường CPU/fallback và các pipeline không cần chữ viết tay.

## Interface chung

```python
class OCREngine(ABC):
    def recognize_words(self, image, langs: list[str]) -> list[Word]:
        """data mode: word + bbox (x,y,w,h) + confidence + line_key."""
    def recognize_text(self, image, langs: list[str], psm: int | None = None) -> str:
        """text mode: prose thuần."""
```

`Word` là dataclass `text, bbox, confidence, line_key`. `langs` là **list**, không phải chuỗi đơn - mỗi engine tự thích nghi (Tesseract join bằng `+`, Paddle chỉ dùng `langs[0]`, EasyOCR truyền cả list vào `Reader`). `Word.confidence` luôn thang **0-100** ở cả ba engine (Paddle/EasyOCR tự nhân 100 để khớp Tesseract).

`Word.line_key` có ngữ nghĩa khác nhau giữa các engine - Tesseract dùng `(block, par, line)` do chính nó trả về; Paddle/EasyOCR dùng `(round(y/10), x)` vì hai engine này detect **cả dòng**, không detect từng từ. Tính chất duy nhất được dựa vào: cùng `line_key` = cùng một dòng, thứ tự sort = thứ tự đọc trong khối.

## PaddleOCR (`core/engines/paddle.py`)

- Backend PP-OCR: tự có detector + recognizer + angle classifier, trả box + text + score cho cả hai mode.
- Opt-in qua `engine: paddleocr`; dependency lazy (không có trong `requirements.txt` ban đầu - nay đã thành bắt buộc vì là default của staged pipeline, xem Cấu phần 4 §10.1), thiếu thư viện → `EngineError` kèm hướng dẫn cài.
- Reader cache module-level theo lang đã map: `{"vie": "vi", "eng": "en"}`, mã khác pass-through.
- Mỗi detection của Paddle là một dòng → một `Word`; `line_key` theo vị trí `(round(y/10), x)`.
- GPU opt-in qua env `PADDLE_USE_GPU`, không thêm field vào `Config`.
- Caveat phiên bản: kwargs (`use_gpu`, `show_log`) khác nhau giữa major version - ghim `paddleocr>=2.7,<3` ở thời điểm viết thiết kế; staged pipeline sau này cần xác nhận lại cho `paddleocr` 3.x (PP-TableRecognitionV2, PP-FormulaNet-M - xem Cấu phần 4 §9 mục "chưa kiểm chứng").
- Khuyến nghị preprocessing: bỏ `binarize` khi dùng Paddle (đã ghi nhận làm giảm chính xác).

## EasyOCR (`core/engines/easyocr.py`)

- Backend hỗ trợ nhiều ngôn ngữ trong một lần chạy qua `Reader(['vi', 'en'])`; `vi`+`en` cùng nhóm Latin nên kết hợp hợp lệ.
- Field `Config.langs: list[str] | None` (vd `[vie, eng]`); `None` → fallback `[lang]` (tương thích ngược). Helper `Config.lang_list()`.
- Cùng convention với Paddle: reader cache theo tuple lang, lang map `{"vie": "vi", "eng": "en"}`, GPU opt-in qua `EASYOCR_USE_GPU`, dependency lazy.
- `Reader.readtext()` trả `(box, text, score)` - cùng shape đã chuẩn hoá với Paddle, nên mapping khớp contract `Word` sẵn có.

## Bài học chung khi thêm engine mới

1. Không đổi engine mặc định của pipeline hiện có khi thêm engine mới - opt-in thuần tuý.
2. Không thêm field `Config` riêng cho GPU/model - dùng env var (YAGNI).
3. Test bằng cách inject module giả (`monkeypatch.setitem(sys.modules, "paddleocr", fake)`) - CI không cần cài engine thật.
4. Đổi interface (như `lang: str` → `langs: list[str]`) là thay đổi lan toả: phải sửa cả 3 engine + mọi call site trong `extract.py`/`recognize/text.py` + test tương ứng.

## Việc còn thiếu (chưa triển khai)

STT 1 ⭐ ở [Cấu phần 1](01-nghien-cuu-chon-model.md) - engine đạt M7 thật - là **VietOCR cắm vào `TextRecognizer`**, chưa có engine nào trong `core/engines/` implement việc này. Đây là đường nâng cấp còn mở, không phải một trong ba engine ở trên.
