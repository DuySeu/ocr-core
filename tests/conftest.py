import json

import pytest

DOCLAYNET_CATEGORIES = (
    "caption",
    "footnote",
    "formula",
    "list-item",
    "page-footer",
    "page-header",
    "picture",
    "section-header",
    "table",
    "text",
    "title",
)

PAGE_WIDTH = 100
PAGE_HEIGHT = 100


# Register the project's custom pytest markers.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: runs a real model or a real document; skipped by -m 'not slow'"
    )


@pytest.fixture
def write_coco(tmp_path):
    """Factory writing a minimal stage-6 COCO file and returning its path.

    ``category_offset`` shifts the numeric category ids so a test can prove the
    loader matches on category name rather than on id, which two independent runs
    are not required to agree on.
    """

    def _write(
        name,
        annotations,
        pages=(1,),
        page_errors=(),
        deskew_angle=0.0,
        rotation_applied=0,
        category_offset=1,
    ):
        categories = [
            {"id": index + category_offset, "name": category}
            for index, category in enumerate(DOCLAYNET_CATEGORIES)
        ]
        ids = {c["name"]: c["id"] for c in categories}

        payload = {
            "info": {"description": "test fixture", "page_errors": list(page_errors)},
            "images": [
                {
                    "id": page,
                    "width": PAGE_WIDTH,
                    "height": PAGE_HEIGHT,
                    "file_name": f"fixture#page={page}",
                    "page_geometry": {
                        "dpi": 300,
                        "rotation_applied": rotation_applied,
                        "deskew_angle": deskew_angle,
                    },
                }
                for page in pages
            ],
            "categories": categories,
            "annotations": [],
        }

        for a in annotations:
            record = {
                "id": a["id"],
                "image_id": a.get("page", 1),
                "category_id": ids[a["category"]],
                "bbox": list(a["bbox"]),
                "area": a["bbox"][2] * a["bbox"][3],
                "iscrowd": 0,
            }
            for optional in ("text", "html"):
                if optional in a:
                    record[optional] = a[optional]
            payload["annotations"].append(record)

        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return _write
