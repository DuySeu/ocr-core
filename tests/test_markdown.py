from ocr_core.pipeline import to_markdown


def test_table_paragraph_section_escape():
    doc = {"pages": [{"page": 1, "error": None, "blocks": [
        {"type": "paragraph", "text": "Xin chào"},
        {"type": "table", "header": True, "rows": [
            ["STT", "Hạng mục", "Yêu cầu"],
            ["I. Phần A"],                       # hàng section (len 1)
            ["1", "CPU", "Tối thiểu | 20 nhân"],  # ô chứa |
        ]},
    ]}]}
    md = to_markdown(doc)
    assert "Xin chào" in md
    assert "| STT | Hạng mục | Yêu cầu |" in md
    assert "| --- | --- | --- |" in md
    assert "| **I. Phần A** |  |  |" in md
    assert "Tối thiểu \\| 20 nhân" in md


def test_page_error_comment():
    doc = {"pages": [{"page": 2, "error": "X: boom", "blocks": []}]}
    assert "<!-- page 2 error: X: boom -->" in to_markdown(doc)
