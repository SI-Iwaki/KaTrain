import os

import pytest
from PIL import Image

from katrain.core.tsumego_capture import CaptureError, classify_intersections, detect_board

SAMPLE = os.path.join(os.path.dirname(__file__), "data", "tsumego_app_sample.png")

EXPECTED_WHITE = {(0, 0), (0, 2), (0, 3), (1, 0), (1, 3), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3)}
EXPECTED_BLACK = {(1, 2), (1, 4), (2, 0), (2, 1), (2, 4), (3, 4), (4, 0), (4, 1), (4, 2), (4, 3), (4, 4)}


def test_detect_board_returns_square_bbox():
    img = Image.open(SAMPLE)
    x0, y0, x1, y1 = detect_board(img)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    assert min(w, h) >= 300
    assert 0.9 < w / h < 1.1
    # 盤は画像の中央下寄り: bbox が画像内に収まっている
    assert 0 <= x0 < x1 < img.width
    assert 0 <= y0 < y1 < img.height


def test_detect_board_fails_without_board():
    img = Image.new("RGB", (800, 600), (20, 40, 120))  # 青一色
    with pytest.raises(CaptureError):
        detect_board(img)


def test_classify_sample_image():
    img = Image.open(SAMPLE)
    grid = classify_intersections(img, detect_board(img), 13)
    assert len(grid) == 13 and all(len(row) == 13 for row in grid)
    black = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "B"}
    white = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "W"}
    assert black == EXPECTED_BLACK
    assert white == EXPECTED_WHITE
