# tests/test_star_opening.py
"""星打ち布石ヘルパー（_get_star_lines / _compute_star_opening_targets / _select_star_target）の純関数テスト。"""
import pytest

from katrain.core.ai import _get_star_lines, _compute_star_opening_targets
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


def _stones(spec):
    """[("B",(3,3)), ("W",(15,15))] 形式から Move リストを生成。"""
    return [Move(coords=c, player=p) for p, c in spec]


class TestComputeStarOpeningTargetsN2:
    """n=2: 既存2連星ロジックの移植（挙動不変）。"""

    def test_black_no_stones_returns_all_corners(self):
        targets = _compute_star_opening_targets((19, 19), _stones([]), "B", 2)
        assert targets == {(3, 3), (15, 3), (3, 15), (15, 15)}

    def test_white_with_opponent_star_plays_diagonal(self):
        # 黒が (3,3) → 白は対角 (15,15)
        stones = _stones([("B", (3, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "W", 2)
        assert targets == {(15, 15)}

    def test_one_ai_star_targets_same_side_corners(self):
        # 黒が (3,3) を持つ → 同辺（同行 or 同列）の隅星
        stones = _stones([("B", (3, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 2)
        assert targets == {(15, 3), (3, 15)}

    def test_two_ai_stars_stops(self):
        stones = _stones([("B", (3, 3)), ("B", (15, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 2)
        assert targets == set()

    def test_n2_works_on_13x13(self):
        # n=2 は隅星のみなので13路でも動作する
        targets = _compute_star_opening_targets((13, 13), _stones([]), "B", 2)
        assert targets == {(3, 3), (9, 3), (3, 9), (9, 9)}


class TestComputeStarOpeningTargetsN3:
    """n=3: 三連星（19路専用）。"""

    def test_black_no_stones_returns_corners_only(self):
        targets = _compute_star_opening_targets((19, 19), _stones([]), "B", 3)
        assert targets == {(3, 3), (15, 3), (3, 15), (15, 15)}

    def test_one_corner_stone_extends_both_lines(self):
        # (3,3) は下辺と左辺に属する → 両ラインの空き星点
        stones = _stones([("B", (3, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == {(9, 3), (15, 3), (3, 9), (3, 15)}

    def test_two_corners_same_side_completes_with_mid(self):
        # 下辺の両隅 → 中辺星 (9,3) で三連星完成
        stones = _stones([("B", (3, 3)), ("B", (15, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == {(9, 3)}

    def test_corner_and_mid_completes_with_far_corner(self):
        # 下辺の隅+中辺星 → 残り隅 (15,3)
        stones = _stones([("B", (3, 3)), ("B", (9, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == {(15, 3)}

    def test_completed_line_stops(self):
        # 下辺3点完成 → 強制停止（空集合）
        stones = _stones([("B", (3, 3)), ("B", (9, 3)), ("B", (15, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == set()

    def test_blocked_line_excluded(self):
        # 黒 (3,3) を持つが、下辺の (15,3) に白 → 下辺は除外、左辺のみ
        stones = _stones([("B", (3, 3)), ("W", (15, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == {(3, 9), (3, 15)}

    def test_n3_returns_empty_on_13x13(self):
        targets = _compute_star_opening_targets((13, 13), _stones([]), "B", 3)
        assert targets == set()
