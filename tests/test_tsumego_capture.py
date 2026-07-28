import os

import pytest
from PIL import Image

from katrain.core.tsumego_capture import CaptureError, classify_intersections, detect_board, grid_to_sgf

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


def _empty_grid(size=13):
    return [["." for _ in range(size)] for _ in range(size)]


def test_grid_to_sgf():
    grid = _empty_grid()
    grid[0][1] = "B"  # i=0(上端行), j=1(左から2列目) → SGF座標 "ba"（列j→1文字目, 行i→2文字目）
    grid[12][12] = "W"  # 右下隅 → "mm"
    sgf = grid_to_sgf(grid, komi=6.5)
    assert sgf == "(;GM[1]FF[4]CA[UTF-8]SZ[13]KM[6.5]PL[B]AB[ba]AW[mm])"


def test_grid_to_sgf_empty_board_raises():
    with pytest.raises(CaptureError):
        grid_to_sgf(_empty_grid())


def test_grid_to_sgf_parses_in_katrain():
    # KaTrain 本体のパーサで読めて黒番になることを保証する結合テスト
    from katrain.core.sgf_parser import SGF

    grid = _empty_grid()
    grid[2][3] = "B"
    grid[5][6] = "W"
    root = SGF.parse_sgf(grid_to_sgf(grid))
    assert root.get_property("SZ") == "13"
    assert root.initial_player == "B"
    assert root.get_list_property("AB") == ["dc"]
    assert root.get_list_property("AW") == ["gf"]
