"""HuntStrategy Dead Stone Avoidance judgment tests."""
import pytest

from katrain.core.ai import (
    _DEAD_OWNERSHIP_THRESHOLD,
    _DEAD_LOSS_MIN,
    _DEAD_WEIGHT_FACTOR,
    is_dead_zone_move,
)


def make_grid(size, fills):
    """ownership grid を構築するヘルパ。fills: {(x,y): value}"""
    grid = [[0.0 for _ in range(size)] for _ in range(size)]
    for (x, y), v in fills.items():
        grid[y][x] = v
    return grid


def test_condition_a_candidate_point_strong_opponent_triggers():
    """候補点自体が player_sign 視点で -0.85 未満なら発動。"""
    # 白番 (player_sign=-1), A10=(0,9) の ownership=+0.92 (黒寄り)
    # 白視点: 0.92 * -1 = -0.92 < -0.85 → 発動
    grid = make_grid(19, {(0, 9): 0.92})
    own_coords = set()  # 隣接自石なし
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=own_coords,
        player_sign=-1,
        loss=1.86,
        board_size=(19, 19),
    ) is True


def test_condition_b_dead_neighbor_own_stone_triggers():
    """候補点は中立だが4近傍に死んだ自石があれば発動。"""
    # 白番, 候補A10=(0,9) ownership=0 (中立)
    # 隣 B10=(1,9) は自石, ownership=+0.90 (黒寄り=白視点 -0.90 < -0.85)
    grid = make_grid(19, {(0, 9): 0.0, (1, 9): 0.90})
    own_coords = {(1, 9)}
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=own_coords,
        player_sign=-1,
        loss=1.86,
        board_size=(19, 19),
    ) is True


def test_low_loss_exempts_even_dead_zone():
    """loss <= 0.5 なら死石周辺でも対象外（条件C で除外）。"""
    grid = make_grid(19, {(0, 9): 0.92})
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=-1,
        loss=0.3,
        board_size=(19, 19),
    ) is False


def test_weak_ownership_does_not_trigger():
    """|ownership|<0.85 なら発動しない（閾値厳格）。"""
    grid = make_grid(19, {(0, 9): 0.70})  # 白視点 -0.70 > -0.85
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=-1,
        loss=2.0,
        board_size=(19, 19),
    ) is False


def test_live_own_neighbor_does_not_trigger():
    """隣接自石が生きていれば条件(B)は満たさない。"""
    # 候補点自体は中立、隣の自石も生きている（白視点 +0.5）
    grid = make_grid(19, {(0, 9): 0.0, (1, 9): -0.5})  # -0.5 * -1 = +0.5
    own_coords = {(1, 9)}
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=own_coords,
        player_sign=-1,
        loss=2.0,
        board_size=(19, 19),
    ) is False


def test_pass_move_is_exempt():
    """パス (coords=None) は対象外。"""
    grid = make_grid(19, {})
    assert is_dead_zone_move(
        move_coords=None,
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=-1,
        loss=2.0,
        board_size=(19, 19),
    ) is False


def test_black_player_sign_condition_a():
    """黒番 (player_sign=+1) の場合、ownership=-0.92 (白寄り) で発動。"""
    grid = make_grid(19, {(0, 9): -0.92})  # 黒視点: -0.92 * +1 = -0.92
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=+1,
        loss=2.0,
        board_size=(19, 19),
    ) is True


def test_out_of_bounds_neighbors_ignored():
    """盤外の近傍は無視される（エッジ A10 など）。"""
    # A10 = (0, 9): x=0 なので x=-1 は盤外
    # 候補点自体は中立、盤内の近傍 B10=(1,9) は空（own_coordsに含まれない）
    grid = make_grid(19, {(0, 9): 0.0})
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=-1,
        loss=2.0,
        board_size=(19, 19),
    ) is False


def test_constants_values():
    """ハードコード定数の値が設計通り。"""
    assert _DEAD_OWNERSHIP_THRESHOLD == 0.85
    assert _DEAD_LOSS_MIN == 0.5
    assert _DEAD_WEIGHT_FACTOR == 0.05
