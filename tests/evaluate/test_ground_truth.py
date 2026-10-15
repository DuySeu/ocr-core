import json

import pytest
from docx import Document

from evaluate.ground_truth import GroundTruthError, convert, discover_text, load, load_dataset


# Write one dataset record and its markdown, returning the JSON path.
def write_record(directory, doc_id, text="Bên vay", **overrides):
    (directory / f"{doc_id}.md").write_text(text, encoding="utf-8")
    record = {"doc_id": doc_id, "text_file": f"{doc_id}.md", "pages": [], "fields": {}, **overrides}
    path = directory / f"{doc_id}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_markdown_ground_truth_is_read_verbatim(tmp_path):
    path = tmp_path / "gt.md"
    path.write_text("## Tiêu đề\n", encoding="utf-8")

    assert load(path) == "## Tiêu đề\n"


def test_docx_table_cells_are_read_in_document_order_with_the_paragraphs(tmp_path):
    document = Document()
    document.add_paragraph("Điều 1. Phạm vi")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "An"
    table.rows[0].cells[1].text = "10"
    document.add_paragraph("Điều 2. Giải thích")
    path = tmp_path / "gt.docx"
    document.save(str(path))

    assert load(path).split("\n") == ["Điều 1. Phạm vi", "An", "10", "Điều 2. Giải thích"]


def test_reads_a_vertically_merged_docx_cell_once(tmp_path):
    document = Document()
    table = document.add_table(rows=2, cols=2)
    for row in range(2):
        for column in range(2):
            table.cell(row, column).text = f"r{row}c{column}"
    table.cell(0, 0).merge(table.cell(1, 0))
    path = tmp_path / "gt.docx"
    document.save(str(path))

    # row.cells reports the merged cell once per row it spans, inflating CER and WER
    assert load(path).count("r0c0") == 1


def test_an_unreadable_format_is_named_rather_than_read_as_bytes(tmp_path):
    path = tmp_path / "gt.pdf"
    path.write_bytes(b"%PDF-1.4")

    with pytest.raises(GroundTruthError, match="readable formats"):
        load(path)


def test_discovery_keys_files_by_stem_across_both_formats(tmp_path):
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    Document().save(str(tmp_path / "nested" / "b.docx"))

    assert sorted(discover_text(tmp_path)) == ["a", "b"]


def test_two_ground_truth_files_sharing_a_stem_is_an_error_not_a_silent_pick(tmp_path):
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    Document().save(str(tmp_path / "a.docx"))

    with pytest.raises(GroundTruthError, match="share the stem"):
        discover_text(tmp_path)


def test_a_pdf_beside_the_ground_truth_is_ignored_not_treated_as_a_target(tmp_path):
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "a-scan.pdf").write_bytes(b"%PDF-1.4")

    assert sorted(discover_text(tmp_path)) == ["a"]


def test_a_dataset_reads_each_record_with_the_markdown_beside_it(tmp_path):
    write_record(tmp_path, "b", "chữ b")
    write_record(tmp_path, "a", "chữ a", metadata={"doc_type": "invoice"})

    documents = load_dataset(tmp_path)

    assert [d.doc_id for d in documents] == ["a", "b"]
    assert documents[0].text == "chữ a"
    assert documents[0].metadata == {"doc_type": "invoice"}


def test_a_record_whose_text_file_is_missing_is_named(tmp_path):
    path = write_record(tmp_path, "a")
    (tmp_path / "a.md").unlink()

    with pytest.raises(GroundTruthError, match="not found beside it"):
        load_dataset(tmp_path)
    assert path.exists()


def test_a_text_file_pointing_outside_the_dataset_is_rejected(tmp_path):
    (tmp_path / "outside.md").write_text("x", encoding="utf-8")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "a.json").write_text(json.dumps({"doc_id": "a", "text_file": "../outside.md"}), encoding="utf-8")

    with pytest.raises(GroundTruthError, match="not found beside it"):
        load_dataset(dataset)


def test_a_record_missing_doc_id_says_which_key(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"text_file": "a.md"}), encoding="utf-8")

    with pytest.raises(GroundTruthError, match="missing doc_id"):
        load_dataset(tmp_path)


def test_two_records_sharing_a_doc_id_is_an_error(tmp_path):
    write_record(tmp_path, "a")
    nested = tmp_path / "nested"
    nested.mkdir()
    write_record(nested, "a")

    with pytest.raises(GroundTruthError, match="share the doc_id"):
        load_dataset(tmp_path)


def test_invalid_json_is_named_rather_than_skipped(tmp_path):
    (tmp_path / "a.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(GroundTruthError, match="not valid JSON"):
        load_dataset(tmp_path)


def test_converting_markdown_in_place_adds_a_record_and_keeps_the_text(tmp_path):
    (tmp_path / "a.md").write_text("Bên vay\n<!-- image -->\n", encoding="utf-8")

    convert(tmp_path, tmp_path)

    [document] = load_dataset(tmp_path)
    assert document.text == "Bên vay\n<!-- image -->\n"
    assert json.loads(document.json_path.read_text(encoding="utf-8"))["normalization_version"] == "norm-v1"
    # finetune still finds exactly one file per stem
    assert discover_text(tmp_path) == {"a": tmp_path / "a.md"}


def test_converting_a_docx_writes_paragraphs_and_tables_in_order(tmp_path):
    source, out = tmp_path / "src", tmp_path / "out"
    source.mkdir()
    document = Document()
    document.add_paragraph("Điều 1")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "An"
    table.rows[0].cells[1].text = "10"
    document.add_paragraph("Điều 2")
    document.save(str(source / "a.docx"))

    convert(source, out)

    assert load_dataset(out)[0].text == (
        "Điều 1\n\n<table><tr><td>An</td><td>10</td></tr></table>\n\nĐiều 2\n"
    )


def test_a_docx_cannot_be_converted_in_place(tmp_path):
    Document().save(str(tmp_path / "a.docx"))

    with pytest.raises(GroundTruthError, match="only .md converts in place"):
        convert(tmp_path, tmp_path)


def test_converting_never_overwrites_an_existing_record(tmp_path):
    write_record(tmp_path, "a", fields={"invoice_number": "0001234"})

    assert convert(tmp_path, tmp_path) == []
    assert load_dataset(tmp_path)[0].fields == {"invoice_number": "0001234"}


def test_converting_fills_file_from_the_source_directory(tmp_path):
    gt, originals = tmp_path / "gt", tmp_path / "dataset"
    gt.mkdir()
    originals.mkdir()
    (gt / "a.md").write_text("x", encoding="utf-8")
    (originals / "a.pdf").write_bytes(b"%PDF-1.4")

    [written] = convert(gt, gt, originals)

    assert json.loads(written.read_text(encoding="utf-8"))["file"] == str(originals / "a.pdf")
