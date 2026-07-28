import pytest

from katrain.core.tsumego_frame import tsumego_frame


def _board(size=13, stones=()):
    board = [["-" for _ in range(size)] for _ in range(size)]
    for i, j, color in stones:
        board[i][j] = color
    return board


def test_partial_board_tsumego_region():
    # 通常ケース: 盤の一部に収まる詰碁 → 枠矩形（bbox+margin）がそのままリージョンになる
    board = _board(
        stones=[(3, 3, "B"), (3, 5, "W"), (5, 3, "W"), (5, 5, "B")]
    )
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=2)
    assert region == ((1, 7), (1, 7))


def test_full_height_tsumego_region_not_degenerate():
    # 回帰テスト: 縦方向ほぼ全域に広がる詰碁（右端寄り）では枠矩形+marginが上下とも盤外に
    # はみ出し、境界マークが縦1線に退化して get_analysis_region が False を返していた
    # （→リージョンなし＝全盤解析になり、AIゲート・枠外刈り取りが全て不活性化する）
    board = _board(
        stones=[(1, 10, "B"), (3, 8, "W"), (5, 12, "B"), (10, 9, "W")]
    )
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # i(行)は端スナップで 0..12 全域、j(列)は 8-4=4 から右端まで
    assert region == ((0, 12), (4, 12))


def test_9x9_margin_clamped_so_frame_fits():
    # 回帰テスト: 9路でmargin=4は枠矩形が全方向で盤外にはみ出し、壁・充填が一切置けず
    # リージョンも全盤（→None正規化→全盤解析）になっていた。9路以下はmarginを2に
    # クランプして壁+リージョンが成立するようにする（左半分を占める詰碁の実例形）
    board = _board(
        size=9,
        stones=[
            (2, 2, "W"), (3, 1, "W"), (4, 0, "B"), (4, 1, "B"), (4, 2, "W"),
            (5, 1, "B"), (5, 3, "W"), (6, 2, "B"), (7, 1, "W"), (7, 5, "W"), (8, 1, "B"),
        ],
    )
    blacks, whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # 縦は端スナップで全域、横は bbox(0..5)+クランプ後margin(2) = 0..7 → 全盤にならずリージョン成立
    assert region == ((0, 8), (0, 7))
    # 壁が盤内（j=7列）に置かれ、枠として機能する
    assert any(j == 7 for _i, j in blacks + whites)


def test_full_board_tsumego_region_covers_board():
    # 詰碁+marginが盤全体を覆う極端ケース: 全盤リージョンを返す
    # （set_region_of_interest 側が全盤リージョンを None に正規化するので実害なし）
    board = _board(
        stones=[(1, 1, "B"), (1, 11, "W"), (11, 1, "W"), (11, 11, "B")]
    )
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    assert region == ((0, 12), (0, 12))
