# tests/test_star_opening.py
"""星打ち布石ヘルパー（_get_star_lines / _compute_star_opening_targets / _select_star_target）の純関数テスト。"""
import pytest

from katrain.core.ai import _get_star_lines
from katrain.core.game import Move


class TestGetStarLines:
    def test_19x19_returns_four_three_point_lines(self):
        lines = _get_star_lines((19, 19))
        assert len(lines) == 4
        for line in lines:
            assert len(line) == 3
        # 各ラインがコリニア（行または列が一定）
        for line in lines:
            xs = {p[0] for p in line}
            ys = {p[1] for p in line}
            assert len(xs) == 1 or len(ys) == 1

    def test_19x19_contains_expected_hoshi(self):
        lines = _get_star_lines((19, 19))
        all_points = {p for line in lines for p in line}
        # 隅4 + 中辺4 = 8点（隅は2ラインで共有されるため集合では8点）
        expected = {
            (3, 3), (9, 3), (15, 3),   # 下辺
            (3, 15), (9, 15), (15, 15),  # 上辺
            (3, 9), (15, 9),           # 左右の中辺星
        }
        assert all_points == expected

    def test_13x13_returns_empty(self):
        assert _get_star_lines((13, 13)) == []

    def test_9x9_returns_empty(self):
        assert _get_star_lines((9, 9)) == []
