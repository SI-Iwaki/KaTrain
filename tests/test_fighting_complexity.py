# tests/test_fighting_complexity.py
"""力戦派 複雑化モードの純関数テスト（モデル不要）。"""
import pytest

from katrain.core.ai import _count_cut_adjacency
from katrain.core.ai import _apply_cut_boost
from katrain.core.ai import _complexity_relaxed_cap
from katrain.core.ai import _passes_complexity_gate
from katrain.core.game import Move


def _board(width, height, stones):
    """stones: {(x,y): chain_id} から board[y][x] グリッドを作る（未指定は -1）。"""
    board = [[-1 for _ in range(width)] for _ in range(height)]
    for (x, y), cid in stones.items():
        board[y][x] = cid
    return board


class TestCountCutAdjacency:
    def test_two_distinct_opponent_chains_is_cut(self):
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1})
        chains = [[Move(coords=(2, 1), player="W")], [Move(coords=(2, 3), player="W")]]
        assert _count_cut_adjacency(board, chains, (2, 2), "W") == 2

    def test_same_chain_on_two_sides_is_not_cut(self):
        board = _board(5, 5, {(2, 1): 0, (2, 3): 0})
        chains = [[Move(coords=(2, 1), player="W"), Move(coords=(2, 3), player="W")]]
        assert _count_cut_adjacency(board, chains, (2, 2), "W") == 1

    def test_own_stones_are_ignored(self):
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1})
        chains = [[Move(coords=(2, 1), player="B")], [Move(coords=(2, 3), player="B")]]
        assert _count_cut_adjacency(board, chains, (2, 2), "W") == 0

    def test_edge_point_no_out_of_bounds(self):
        board = _board(5, 5, {(1, 0): 0})
        chains = [[Move(coords=(1, 0), player="W")]]
        assert _count_cut_adjacency(board, chains, (0, 0), "W") == 1


class TestApplyCutBoost:
    def test_cut_point_is_boosted(self):
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1})
        chains = [[Move(coords=(2, 1), player="W")], [Move(coords=(2, 3), player="W")]]
        weights = {(2, 2): 1.0, (0, 0): 1.0}
        out = _apply_cut_boost(weights, board, chains, "W", 2.0)
        assert out[(2, 2)] == 2.0
        assert out[(0, 0)] == 1.0

    def test_boost_one_is_noop(self):
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1})
        chains = [[Move(coords=(2, 1), player="W")], [Move(coords=(2, 3), player="W")]]
        weights = {(2, 2): 1.0}
        out = _apply_cut_boost(weights, board, chains, "W", 1.0)
        assert out == weights

    def test_occupied_point_not_boosted(self):
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1, (2, 2): 2})
        chains = [
            [Move(coords=(2, 1), player="W")],
            [Move(coords=(2, 3), player="W")],
            [Move(coords=(2, 2), player="B")],
        ]
        weights = {(2, 2): 1.0}
        out = _apply_cut_boost(weights, board, chains, "W", 2.0)
        assert out[(2, 2)] == 1.0


class TestComplexityRelaxedCap:
    def test_below_threshold_no_relaxation(self):
        assert _complexity_relaxed_cap(10.0, 5.6, 15.0, 10.0) == 5.6

    def test_at_threshold_returns_base(self):
        assert _complexity_relaxed_cap(15.0, 5.6, 15.0, 10.0) == 5.6

    def test_ramps_linearly_to_max(self):
        assert _complexity_relaxed_cap(20.0, 5.6, 15.0, 10.0, ramp=10.0) == pytest.approx(7.8)

    def test_caps_at_max_loss(self):
        assert _complexity_relaxed_cap(100.0, 5.6, 15.0, 10.0, ramp=10.0) == pytest.approx(10.0)

    def test_max_loss_below_base_returns_base(self):
        assert _complexity_relaxed_cap(50.0, 5.6, 15.0, 4.0) == 5.6


class TestPassesComplexityGate:
    BASE = 5.6
    CAP = 10.0

    def test_low_loss_always_passes(self):
        assert _passes_complexity_gate(2.0, self.BASE, self.CAP, None, 3.0, 0.0, 1.0, 0.5) is True

    def test_above_cap_rejected(self):
        assert _passes_complexity_gate(11.0, self.BASE, self.CAP, 9.0, 3.0, 1.0, 1.0, 0.5) is False

    def test_relaxed_band_needs_sharpness(self):
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, 1.0, 3.0, 1.0, 1.0, 0.5) is False

    def test_relaxed_band_needs_complexity(self):
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, 9.0, 3.0, 0.2, 1.0, 0.5) is False

    def test_relaxed_band_passes_both(self):
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, 9.0, 3.0, 0.8, 1.0, 0.5) is True

    def test_missing_stdev_rejected(self):
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, None, 3.0, 1.0, 1.0, 0.5) is False

    def test_zero_max_weight_rejected(self):
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, 9.0, 3.0, 0.0, 0.0, 0.5) is False
