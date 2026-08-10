import pytest

from evaluate.loader import LoaderError, load_coco

TEXT_BOX = {"id": 10001, "category": "text", "bbox": (10, 20, 40, 30), "text": "Điều 1"}


def test_boxes_are_converted_to_relative_coordinates(write_coco):
    document = load_coco(write_coco("gold.coco.json", [TEXT_BOX]))

    # The fixture page is 100x100, so pixels map straight to hundredths
    assert document.elements[1][0].bbox == (0.10, 0.20, 0.40, 0.30)


def test_categories_are_read_by_name_so_two_runs_need_not_agree_on_ids(write_coco):
    gold = load_coco(write_coco("gold.coco.json", [TEXT_BOX], category_offset=1))
    predicted = load_coco(write_coco("pred.coco.json", [TEXT_BOX], category_offset=500))

    assert gold.elements[1][0].category == predicted.elements[1][0].category == "text"


def test_page_errors_are_read_from_info(write_coco):
    document = load_coco(write_coco("g.coco.json", [TEXT_BOX], pages=(1,), page_errors=[2, 3]))

    assert document.page_errors == {2, 3}


def test_deskew_angle_travels_with_the_page_so_the_caller_can_compare_frames(write_coco):
    document = load_coco(write_coco("g.coco.json", [TEXT_BOX], deskew_angle=1.4))

    assert document.frames[1].deskew_angle == pytest.approx(1.4)


def test_unreadable_coco_names_the_file(tmp_path):
    path = tmp_path / "broken.coco.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(LoaderError, match="not valid JSON"):
        load_coco(path)


def test_a_missing_coco_file_names_the_path(tmp_path):
    with pytest.raises(LoaderError, match="not found"):
        load_coco(tmp_path / "absent.coco.json")
