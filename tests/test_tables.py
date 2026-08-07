import cv2
import numpy as np

from core.tables import detect_tables


def _grid_with_merge():
    """3x3 grid; col0 merges rows 0-1 (skip the y=100 segment over col0)."""
    img = np.full((300, 400), 255, np.uint8)
    for x in (20, 150, 260, 380):          # cột: 3 cột
        cv2.line(img, (x, 20), (x, 280), 0, 2)
    for y in (20, 190, 280):               # hàng đầy đủ
        cv2.line(img, (20, y), (380, y), 0, 2)
    cv2.line(img, (150, 100), (380, 100), 0, 2)  # phân hàng 0/1 chỉ ở cột 1-2
    return img


def test_detect_grid_dims_and_merged_span():
    tables = detect_tables(_grid_with_merge())
    assert len(tables) == 1
    t = tables[0]
    assert (t.n_rows, t.n_cols) == (3, 3)
    # ô gộp dọc ở cột 0, trải hàng 0->2
    assert any(c.r0 == 0 and c.r1 == 2 and c.c0 == 0 and c.c1 == 1 for c in t.cells)


def test_no_lines_no_table():
    blank = np.full((200, 200), 255, np.uint8)
    assert detect_tables(blank) == []
