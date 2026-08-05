# tests/test_ai_parity9.py
"""9路専用「一致率追随」戦略 ai:parity9 の純関数テスト（KataGo/Kivy 不要）。"""
from types import SimpleNamespace

from katrain.core.ai import parity9_match_tally


class FakeMove:
    def __init__(self, gtp):
        self._gtp = gtp

    def gtp(self):
        return self._gtp


def node(player, gtp, top_gtp, complete=True):
    """一致判定に必要な最小限の属性だけを持つ疑似ノードを作る。

    top_gtp=None で「親の candidate_moves が空」を表す。
    """
    return SimpleNamespace(
        player=player,
        move=FakeMove(gtp),
        is_root=False,
        parent=SimpleNamespace(
            analysis_complete=complete,
            candidate_moves=[{"move": top_gtp}] if top_gtp is not None else [],
        ),
    )


class TestMatchTally:
    def test_empty_history(self):
        assert parity9_match_tally([], "B") == (0, 0, 0)

    def test_black_all_matched(self):
        # B/W が交互に2手ずつ、全員が最善手と一致
        nodes = [
            node("B", "E5", "E5"),
            node("W", "C3", "C3"),
            node("B", "G7", "G7"),
            node("W", "G3", "G3"),
        ]
        assert parity9_match_tally(nodes, "B") == (2, 2, 2)

    def test_black_leads_when_opponent_misses(self):
        nodes = [
            node("B", "E5", "E5"),
            node("W", "C3", "D4"),   # 不一致
            node("B", "G7", "G7"),
            node("W", "G3", "G3"),
        ]
        assert parity9_match_tally(nodes, "B") == (2, 1, 2)

    def test_white_truncates_opponent_extra_move(self):
        # 白の手番直前: B が3手、W が2手。B の3手目は切り捨てる
        nodes = [
            node("B", "E5", "E5"),   # 一致（数える）
            node("W", "C3", "C3"),   # 一致
            node("B", "G7", "G7"),   # 一致（数える）
            node("W", "G3", "D4"),   # 不一致
            node("B", "C7", "C7"),   # 一致だが切り捨て
        ]
        assert parity9_match_tally(nodes, "W") == (1, 2, 2)

    def test_skips_nodes_without_complete_parent_analysis(self):
        nodes = [
            node("B", "E5", "E5"),
            node("W", "C3", "C3"),
            node("B", "G7", "G7", complete=False),   # 両者とも列に入れない
            node("W", "G3", "G3"),
        ]
        # B は1手、W は2手 → opp は先頭1手だけ
        assert parity9_match_tally(nodes, "B") == (1, 1, 1)

    def test_skips_nodes_with_empty_candidate_moves(self):
        nodes = [
            node("B", "E5", None),   # candidate_moves 空
            node("W", "C3", "C3"),
            node("B", "G7", "G7"),
        ]
        assert parity9_match_tally(nodes, "B") == (1, 1, 1)

    def test_pass_is_compared_like_any_move(self):
        nodes = [
            node("B", "pass", "pass"),
            node("W", "C3", "pass"),
        ]
        assert parity9_match_tally(nodes, "B") == (1, 0, 1)

    def test_opponent_sequence_shorter_than_mine_uses_all_of_it(self):
        # 黒番で相手がまだ1手しか打っていない状態
        nodes = [
            node("B", "E5", "E5"),
            node("W", "C3", "C3"),
            node("B", "G7", "G7"),
        ]
        assert parity9_match_tally(nodes, "B") == (2, 1, 2)
