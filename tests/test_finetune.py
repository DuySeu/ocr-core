"""Unit tests for the Tesseract LSTM finetune package (§9.2)."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from core.document.model import Element, TextContent, TextLine
from core.document.serde import page_to_dict
from core.geometry import (
    IDENTITY_MATRIX,
    PageGeometry,
    bounding_box,
    corners,
    from_canonical,
    to_canonical,
)
from finetune import align, cut_lines, guards, lstmf


def _geometry(page=1, deskew_angle=0.0, matrix=IDENTITY_MATRIX):
    return PageGeometry(
        page, 200, 100, 300, 0, deskew_angle, matrix, None, None
    )


def _line(text, text_ocr, polygon, bbox, confidence=0.9):
    return TextLine(text, text_ocr, polygon, bbox, confidence)


def _text_element(page, lines, reading_order=0, eid=None):
    eid = eid if eid is not None else page * 10_000
    text = "\n".join(line.text for line in lines)
    return Element(
        id=eid,
        page=page,
        category="text",
        bbox=(0, 0, 10, 10),
        reading_order=reading_order,
        content=TextContent(text, lines=list(lines)),
    )


# ---------- guards ----------


def test_raises_when_traineddata_is_int_mode(tmp_path, monkeypatch):
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    vie = tessdata / "vie.traineddata"
    vie.write_bytes(b"fake")
    monkeypatch.setattr(guards, "TESSDATA_DIR", tessdata)
    monkeypatch.setattr(guards, "BASE_TRAINEDDATA", vie)

    class _Which:
        @staticmethod
        def which(name):
            return f"/bin/{name}"

    monkeypatch.setattr(guards, "shutil", _Which)

    def fake_run(cmd, capture_output, text, check):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="Version:...\nint_mode=1\n", stderr=""
        )

    monkeypatch.setattr(guards.subprocess, "run", fake_run)

    with pytest.raises(guards.GuardError, match="int_mode"):
        guards.check()


def test_ignores_output_model_when_checking_traineddata(
    tmp_path, monkeypatch
):
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    vie = tessdata / "vie.traineddata"
    vie.write_bytes(b"best")
    # Output model sitting next to base must not be inspected
    (tessdata / "vie_lpbank.traineddata").write_bytes(b"out")
    monkeypatch.setattr(guards, "TESSDATA_DIR", tessdata)
    monkeypatch.setattr(guards, "BASE_TRAINEDDATA", vie)

    class _Which:
        @staticmethod
        def which(name):
            return f"/bin/{name}"

    monkeypatch.setattr(guards, "shutil", _Which)

    seen = []

    def fake_run(cmd, capture_output, text, check):
        seen.append(cmd)
        return subprocess.CompletedProcess(
            cmd, 0, stdout="Version:...\n", stderr=""
        )

    monkeypatch.setattr(guards.subprocess, "run", fake_run)
    guards._require_best_traineddata()

    assert len(seen) == 1
    assert seen[0][-1] == str(vie)
    assert "vie_lpbank" not in seen[0][-1]


# ---------- align ----------


def test_removes_table_block_before_stripping_tags():
    raw = (
        "before\n"
        "<table><tr><th>A</th></tr><tr><td>B</td></tr></table>\n"
        "after <b>ok</b>"
    )
    cleaned = align.prepare_ground_truth(raw)
    assert "A" not in cleaned and "B" not in cleaned
    assert "before" in cleaned and "after" in cleaned
    assert "ok" in cleaned
    assert "<" not in cleaned


def test_preserves_tone_placement_in_label():
    # normalize.strict() would rewrite hoà -> hòa; labels must keep glyphs
    cleaned = align.prepare_ground_truth("hoà bình")
    assert "hoà" in cleaned
    assert "hòa" not in cleaned


def test_strips_markdown_bullet_marker_but_keeps_printed_numbering():
    raw = "- HĐQT;\n* item\n+ more\n1. First\na) letter"
    cleaned = align.prepare_ground_truth(raw)
    assert "HĐQT;" in cleaned
    assert cleaned.splitlines()[0] == "HĐQT;"
    assert "1. First" in cleaned
    assert "a) letter" in cleaned
    assert not cleaned.startswith("*")
    assert "- " not in cleaned
    assert "* " not in cleaned


def test_aligns_gt_line_by_line_from_page_text():
    lines = [
        _line("Hello", "Hello", [(0, 0), (1, 0), (1, 1), (0, 1)], (0, 0, 1, 1)),
        _line("World", "World", [(0, 2), (1, 2), (1, 3), (0, 3)], (0, 2, 1, 1)),
    ]
    labels = align.align_page_lines(lines, "Hello\nWorld")
    assert labels[0][0] == "Hello"
    assert labels[1][0] == "World"


def test_rejects_line_below_similarity_threshold():
    lines = [
        _line(
            "aaaaaaa",
            "aaaaaaa",
            [(0, 0), (1, 0), (1, 1), (0, 1)],
            (0, 0, 1, 1),
        ),
    ]
    labels = align.align_page_lines(lines, "zzzzzzz totally different")
    assert labels[0][0] is None
    assert "similarity" in (labels[0][1] or "")


def test_skips_document_without_matching_ground_truth(tmp_path):
    sha = "a" * 64
    version = "tesseract_vie_tesseract_cv_deadbeef"
    root = tmp_path / "artifacts" / sha[:12] / version
    (root / "pages").mkdir(parents=True)
    geom = _geometry()
    element = _text_element(
        1,
        [
            _line(
                "x", "x", [(0, 0), (1, 0), (1, 1), (0, 1)], (0, 0, 1, 1)
            )
        ],
    )
    (root / "pages" / "p0001.json").write_text(
        json.dumps(page_to_dict(geom, [element])), encoding="utf-8"
    )
    (root / "meta.json").write_text(
        json.dumps({"source": "/data/missing_doc.pdf"}), encoding="utf-8"
    )
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / "other.md").write_text("hello", encoding="utf-8")

    report = align.align(
        tmp_path / "artifacts", sha, version, gt_dir
    )
    assert report.written == 0
    assert report.skipped_docs == ("missing_doc",)


# ---------- cut_lines ----------


def test_crops_line_from_polygon_without_inflating_height(tmp_path):
    # A 0.4-degree deskew: going through bbox twice inflates height;
    # going through polygon once must keep height near the true line height.
    angle = math.radians(0.4)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    # Row-major 2x3 rotation around origin (sufficient for the round-trip test)
    matrix = (cos_a, -sin_a, 0.0, sin_a, cos_a, 0.0)
    geom = _geometry(deskew_angle=0.4, matrix=matrix)

    # Line box in deskew frame: width 100, height 28
    deskew_box = (50, 40, 100, 28)
    canon_poly = to_canonical(corners(deskew_box), geom)
    canon_bbox = bounding_box(canon_poly)
    line = _line("abc", "abc", canon_poly, canon_bbox)

    # Inflated path (what we must NOT do): hull of from_canonical(bbox corners)
    inflated = bounding_box(
        from_canonical(corners(canon_bbox), geom)
    )
    # Correct path: hull of from_canonical(polygon) once
    correct = bounding_box(from_canonical(line.polygon, geom))

    assert correct[3] <= deskew_box[3] + 2  # ~28 px, tiny rounding only
    assert inflated[3] > correct[3]  # bbox round-trip actually inflates

    # And cut_lines uses the correct path when writing a crop
    sha = "b" * 64
    version = "v1"
    root = tmp_path / "artifacts" / sha[:12] / version
    pages = root / "pages"
    images = root / "images"
    pages.mkdir(parents=True)
    images.mkdir()
    element = _text_element(1, [line])
    (pages / "p0001.json").write_text(
        json.dumps(page_to_dict(geom, [element])), encoding="utf-8"
    )
    Image.new("RGB", (200, 100), "white").save(images / "p0001.webp")

    out = tmp_path / "data"
    report = cut_lines.cut_lines(
        tmp_path / "artifacts", sha, version, out_dir=out
    )
    assert report.written == 1
    crop = Image.open(out / "p0001_l000.png")
    assert crop.size[1] == correct[3]


# ---------- lstmf ----------


def test_raises_when_train_list_is_empty(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    # One labelled pair, but tesseract always "fails" so list stays empty
    png = data / "p0001_l000.png"
    Image.new("RGB", (40, 20), "white").save(png)
    png.with_name("p0001_l000.gt.txt").write_text("hi\n", encoding="utf-8")

    def fake_run(cmd, capture_output, text, check):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="fail")

    monkeypatch.setattr(lstmf.subprocess, "run", fake_run)

    with pytest.raises(lstmf.LstmfError, match="at least"):
        lstmf.build_lstmf(
            data_dir=data,
            tessdata_dir=tmp_path / "tessdata",
            list_train=tmp_path / "list.train",
            min_lines=50,
        )
