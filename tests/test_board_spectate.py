import pytest

from katrain.core.board_spectate import spectate_sync
from katrain.core.board_watch import apply_move_to_grid


def g(s):
    return [list(r) for r in s.split("/")]


def replay(grid, moves):
    for i, j, c in moves:
        grid = apply_move_to_grid(grid, i, j, c)
        assert grid is not None
    return grid


G0 = g("...../.B.../...../...W./.....")
G0_PLUS_B = g("B..../.B.../...../...W./.....")
G0_PLUS_BW = g("B..../.B.../...../...W./W....")
G0_PLUS_BWB = g("B...B/.B.../...../...W./W....")
G0_PLUS_BB = g("B...B/.B.../...../...W./.....")
G0_MINUS_STONE = g("...../...../...../...W./.....")
G7 = [["."] * 7 for _ in range(7)]

# 白 1 子 (0,0) がアタリ。黒が (1,0) で取る
ATARI = g("WB.../...../...../...../.....")
AFTER_CAPTURE = g(".B.../B..../...../...../.....")

# 黒 (0,0) は、先に黒 (0,2) を置いて白 (0,1) の呼吸点を (0,0) だけにしないと自殺手になる
NEEDS_ORDER = g(".W.../WB.../...../...../.....")
NEEDS_ORDER_AFTER = g("B.B../WB.../...../...../....W")

# コウ形: 白 (1,1) が黒 3 子に囲まれてアタリ。黒 (1,2) で取れる
KO_BEFORE = g(".BW../BW.W./.BW../...../.....")
# 取った (1,2) の黒と、取られたはずの白 (1,1) が同居＝1 手では作れない盤
KO_AFTER_TWO = g(".BW../BWBW./.BW../...../.....")


def test_in_sync():
    assert spectate_sync(G0, G0, "B").kind == "in_sync"


def test_single_move_and_capture():
    v = spectate_sync(ATARI, AFTER_CAPTURE, "B", last_mover="B")
    assert (v.kind, v.moves, v.estimated) == ("moves", ((1, 0, "B"),), False)


def test_three_moves_are_alternated_and_marked_estimated():
    v = spectate_sync(G0, G0_PLUS_BWB, "B", last_mover="B")
    assert v.kind == "moves" and [m[2] for m in v.moves] == ["B", "W", "B"] and v.estimated
    assert replay(G0, v.moves) == G0_PLUS_BWB


def test_order_that_needs_capture_first_is_found():
    v = spectate_sync(NEEDS_ORDER, NEEDS_ORDER_AFTER, "B")
    assert v.kind == "moves" and replay(NEEDS_ORDER, v.moves) == NEEDS_ORDER_AFTER


@pytest.mark.parametrize(
    "tip,obs,kw",
    [
        (G0, G0_PLUS_BB, {}),  # 黒 2 手＝交互にならない
        (KO_BEFORE, KO_AFTER_TWO, {}),  # コウ絡みの説明できない盤
        (G0, G0_MINUS_STONE, {}),  # 石が消えただけ
        (G0, G0_PLUS_B, {"last_mover": "W"}),  # 直前手の印と色が合わない
        (G0, G0_PLUS_B, {"app_move_number": 12, "tip_move_number": 10}),  # 手数が合わない
        (G0, G7, {}),  # 盤サイズ違い
    ],
)
def test_unexplained_diff_reimports(tip, obs, kw):
    assert spectate_sync(tip, obs, "B", **kw).kind == "reimport"


def test_app_showing_earlier_mainline_position_is_behind_not_reimport():  # Review Focus 6
    v = spectate_sync(G0_PLUS_BWB, G0_PLUS_B, "W", ancestor_grids=(G0, G0_PLUS_B, G0_PLUS_BW))
    assert v.kind == "behind"


def test_move_number_check_passes_when_consistent():
    assert spectate_sync(G0, G0_PLUS_B, "B", app_move_number=11, tip_move_number=10).kind == "moves"
