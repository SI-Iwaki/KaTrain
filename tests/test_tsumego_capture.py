import os
import subprocess
import sys

import pytest
from PIL import Image

from katrain.core.tsumego_capture import (
    CaptureError,
    classify_intersections,
    detect_board,
    detect_size_and_classify,
    grid_to_sgf,
)

SAMPLE = os.path.join(os.path.dirname(__file__), "data", "tsumego_app_sample.png")
SAMPLE_9X9 = os.path.join(os.path.dirname(__file__), "data", "tsumego_app_sample_9x9.png")

EXPECTED_WHITE = {(0, 0), (0, 2), (0, 3), (1, 0), (1, 3), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3)}
EXPECTED_BLACK = {(1, 2), (1, 4), (2, 0), (2, 1), (2, 4), (3, 4), (4, 0), (4, 1), (4, 2), (4, 3), (4, 4)}

EXPECTED_BLACK_9X9 = {(5, j) for j in range(9)} | {(6, 2), (6, 6), (7, 2), (7, 6), (8, 4)}
EXPECTED_WHITE_9X9 = {(6, 0), (6, 1), (6, 4), (6, 7), (6, 8), (7, 1), (7, 7), (8, 0), (8, 2), (8, 3), (8, 5), (8, 6), (8, 8)}


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


def test_auto_size_13_sample():
    img = Image.open(SAMPLE)
    size, grid = detect_size_and_classify(img, detect_board(img))
    assert size == 13
    black = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "B"}
    assert black == EXPECTED_BLACK


def test_auto_size_9x9_sample():
    img = Image.open(SAMPLE_9X9)
    size, grid = detect_size_and_classify(img, detect_board(img))
    assert size == 9
    black = {(i, j) for i in range(9) for j in range(9) if grid[i][j] == "B"}
    white = {(i, j) for i in range(9) for j in range(9) if grid[i][j] == "W"}
    assert black == EXPECTED_BLACK_9X9
    assert white == EXPECTED_WHITE_9X9


def test_cross_size_rejection():
    # 誤ったサイズでのサンプリングは曖昧エラーで拒否される（自動サイズ判定の前提）
    img13 = Image.open(SAMPLE)
    rect13 = detect_board(img13)
    img9 = Image.open(SAMPLE_9X9)
    rect9 = detect_board(img9)
    for wrong_size in (9, 19):
        with pytest.raises(CaptureError):
            classify_intersections(img13, rect13, wrong_size)
    for wrong_size in (13, 19):
        with pytest.raises(CaptureError):
            classify_intersections(img9, rect9, wrong_size)


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


def _fake_analysis(moves_visits):
    return {
        "moveInfos": [
            {"move": gtp, "visits": v, "order": i, "scoreLead": 0.0, "winrate": 0.5, "pv": [gtp]}
            for i, (gtp, v) in enumerate(moves_visits)
        ],
        "rootInfo": {"visits": sum(v for _, v in moves_visits), "winrate": 0.5, "scoreLead": 0.0},
    }


def test_region_analysis_prunes_outside_moves():
    # 全盤fast解析→リージョン限定解析の2段構えで、枠外の候補手が残らないこと
    # （詰碁キャプチャで枠外の手が最善手として表示される不具合の回帰テスト）
    from katrain.core.game_node import GameNode

    node = GameNode(properties={"SZ": "13"})
    node.set_analysis(_fake_analysis([("B4", 38), ("A12", 20)]))  # 全盤fast: 枠外B4が最善
    assert "B4" in node.analysis["moves"]
    # リージョン x=0..10, y=4..12（B4 は y=3 で枠外、A12/B11 は枠内）
    node.set_analysis(_fake_analysis([("A12", 335), ("B11", 342)]), region_of_interest=[0, 10, 4, 12])
    assert "B4" not in node.analysis["moves"]
    assert set(node.analysis["moves"]) == {"A12", "B11"}


def test_cli_image_mode():
    result = subprocess.run(
        [sys.executable, "-m", "katrain.core.tsumego_capture", "--image", SAMPLE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "SZ[13]" in result.stdout
    assert "PL[B]" in result.stdout
    # ASCII盤面が13行出力される
    board_lines = [ln for ln in result.stdout.splitlines() if ln and all(c in "BW. " for c in ln)]
    assert len(board_lines) == 13
