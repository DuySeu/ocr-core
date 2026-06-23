"""Detect bordered tables and their cell grid (geometry only, no OCR)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

HV_SCALE = 40  # line kernel = image_dim // HV_SCALE
MIN_TABLE_AREA = 0.02  # bảng tối thiểu so với diện tích trang
MIN_CELL_AREA = 100  # px, lọc ô nhiễu
LINE_FRAC = 0.5  # ngưỡng nhận đường (so với line dài nhất cùng trục)


@dataclass
class Cell:
    r0: int
    c0: int
    r1: int
    c1: int
    box: tuple  # (x, y, w, h) trên ảnh gốc


@dataclass
class Table:
    box: tuple  # (x, y, w, h)
    n_rows: int
    n_cols: int
    cells: list[Cell]


def _lines(bw: np.ndarray, ksize: tuple) -> np.ndarray:
    k = cv2.getStructuringElement(cv2.MORPH_RECT, ksize)
    return cv2.morphologyEx(bw, cv2.MORPH_OPEN, k)


def _positions(mask: np.ndarray, axis: int) -> list[int]:
    """Tọa độ tâm các đường (cụm chỉ số mật độ cao theo trục)."""
    proj = mask.sum(axis=axis)
    if proj.max() == 0:
        return []
    hits = proj > proj.max() * LINE_FRAC
    pos, i, n = [], 0, len(hits)
    while i < n:
        if hits[i]:
            j = i
            while j < n and hits[j]:
                j += 1
            pos.append((i + j - 1) // 2)
            i = j
        else:
            i += 1
    return pos


def _nearest(positions: list[int], v: int) -> int:
    return min(range(len(positions)), key=lambda i: abs(positions[i] - v))


def _cells(
    gd: np.ndarray, ys: list[int], xs: list[int], ox: int, oy: int
) -> list[Cell]:
    inv = cv2.bitwise_not(gd)
    n, _, stats, _ = cv2.connectedComponentsWithStats(inv, 8)
    H, W = gd.shape
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < MIN_CELL_AREA or area < 0.5 * w * h:  # nhiễu / viền (không đặc)
            continue
        if w >= 0.98 * W and h >= 0.98 * H:  # cả vùng bảng
            continue
        r0, r1 = _nearest(ys, y), _nearest(ys, y + h)
        c0, c1 = _nearest(xs, x), _nearest(xs, x + w)
        if r1 > r0 and c1 > c0:
            out.append(Cell(r0, c0, r1, c1, (x + ox, y + oy, w, h)))
    return out


def detect_tables(img: np.ndarray) -> list[Table]:
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    H, W = bw.shape
    horiz = _lines(bw, (max(W // HV_SCALE, 1), 1))
    vert = _lines(bw, (1, max(H // HV_SCALE, 1)))
    grid = cv2.bitwise_or(horiz, vert)

    tables = []
    cnts = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < MIN_TABLE_AREA * H * W:
            continue
        ys = _positions(horiz[y : y + h, x : x + w], axis=1)
        xs = _positions(vert[y : y + h, x : x + w], axis=0)
        if len(ys) < 3 or len(xs) < 3:  # cần >=2 hàng & >=2 cột
            continue
        cells = _cells(grid[y : y + h, x : x + w], ys, xs, x, y)
        if cells:
            tables.append(Table((x, y, w, h), len(ys) - 1, len(xs) - 1, cells))
    return sorted(tables, key=lambda t: t.box[1])
