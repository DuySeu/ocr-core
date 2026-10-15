# Tài liệu

## Hướng dẫn theo luồng

- [Kiến trúc triển khai](guides/kien-truc-trien-khai.md): vai trò từng cấu phần, sơ đồ tổng.
- [01 OCR](guides/01-ocr.md): `core/` và `main.py`, QA, review folder.
- [02 Trích xuất](guides/02-trich-xuat.md): luồng trích xuất thông tin (chưa implement).
- [03 Fine-tune](guides/03-finetune.md): `finetune/`, train `vie_lpbank`.
- [04 Evaluation](guides/04-evaluation.md): `evaluate/`, chấm theo tầng.

## Đặc tả

- [Benchmark OCR](specs/benchmark-ocr.md): data, ground truth, các tầng đánh giá và metric.

## Thiết kế

Bản ghi quyết định, giữ nguyên như lúc viết; đường dẫn bên trong có thể là của cấu trúc cũ.

- [2026-08-15 Refactor pipeline Tesseract](designs/2026-08-15-tesseract-pipeline-refactor-design.md)
- [2026-10-15 Evaluate theo tầng](designs/2026-10-15-evaluate-by-tier-design.md)

## Sơ đồ

- [kien-truc-trien-khai.drawio.svg](diagrams/kien-truc-trien-khai.drawio.svg)
- [Parser&Chunking.drawio.png](diagrams/Parser&Chunking.drawio.png)
