# tests/test_ai_mimic13.py
"""「擬態（13路）」ai:mimic13 の純関数・登録整合・_generate_move 通しテスト（KataGo/Kivy 不要）。

設計: docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md
"""

import types

import pytest

from katrain.core.ai import Enigma9Strategy


def _node(**kw):
    base = dict(next_player="B", player="W", depth=30, move=None, analysis_complete=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


class TestTerminalBandExtraction:
    """基底の終局帯ブロックはメソッドに抽出されている（擬態13路と共有するため）。"""

    def test_returns_none_outside_the_terminal_band(self):
        katrain_ns = types.SimpleNamespace(log=lambda *a, **k: None)
        cands = [
            {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.6},
            {"move": "pass", "pointsLost": 30.0, "relativePointsLost": 30.0, "visits": 5, "winrate": 0.1},
        ]
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=_node(candidate_moves=cands), board_size=(9, 9))
        s = Enigma9Strategy(game, {})
        assert s._terminal_band_move(cands, "B") is None

    def test_opponent_pass_with_cheap_pass_returns_a_pass(self):
        from katrain.core.sgf_parser import Move

        katrain_ns = types.SimpleNamespace(log=lambda *a, **k: None)
        cands = [
            {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.6},
            {"move": "pass", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 50, "winrate": 0.6},
        ]
        node = _node(candidate_moves=cands, move=Move(None, player="W"))
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(9, 9))
        s = Enigma9Strategy(game, {})
        move, reason = s._terminal_band_move(cands, "B")
        assert move.is_pass
