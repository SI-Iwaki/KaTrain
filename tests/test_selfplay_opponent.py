# tests/test_selfplay_opponent.py
"""自己対局ハーネスの相手ボット HumanSLOpponent と待ちループ Waiter（偽エンジン・本物の Game）。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §3
"""

import types

import pytest

from katrain.core.constants import PRIORITY_EXTRA_AI_QUERY
from katrain.core.sgf_parser import Move
from katrain_debug.selfplay_opponent import GameAborted, HumanSLOpponent, Waiter
from tests.selfplay_fakes import FakeEngine, hp_array, make_stub, new_game


def _hp(weights):
    return lambda node, empties: hp_array(node.board_size[0], weights)


class TestWaiter:
    def test_dead_engine_aborts(self):
        engine = FakeEngine()
        engine.alive = False
        with pytest.raises(GameAborted, match="engine died"):
            Waiter(engine, timeout=5).until(lambda: False, "x")

    def test_timeout_aborts(self):
        with pytest.raises(GameAborted, match="timeout"):
            Waiter(FakeEngine(), timeout=0.05).until(lambda: False, "x")

    def test_watchdog_restart_aborts(self):
        dog = types.SimpleNamespace(restarts=0)
        waiter = Waiter(FakeEngine(), timeout=5, watchdog=dog)
        dog.restarts = 1
        with pytest.raises(GameAborted, match="restarted"):
            waiter.until(lambda: False, "x")

    def test_humansl_query_shape(self, tmp_path):
        engine = FakeEngine()
        game = new_game(make_stub(tmp_path), engine)
        analysis = Waiter(engine, timeout=5).humansl(game.current_node, "rank_3k")
        assert "humanPolicy" in analysis
        node, kw = engine.requests[-1]
        assert node is game.current_node
        assert kw["visits"] == 1 and kw["include_policy"] is True and kw["ownership"] is False
        assert kw["priority"] == PRIORITY_EXTRA_AI_QUERY and kw["time_limit"] is False
        assert kw["extra_settings"] == {"humanSLProfile": "rank_3k", "ignorePreRootHistory": False}


class TestHumanSLOpponent:
    def _play(self, tmp_path, engine, opp, moves=()):
        game = new_game(make_stub(tmp_path), engine)
        for player, gtp in moves:
            game.play(Move.from_gtp(gtp, player=player))
        waiter = Waiter(engine, timeout=5)
        node = opp.play(game, waiter)
        return game, node

    def test_plays_the_humansl_sample(self, tmp_path):
        game, node = self._play(tmp_path, FakeEngine(hp_fn=_hp({(8, 8): 1.0})), HumanSLOpponent("rank_3k", seed=1))
        assert node is game.current_node and node.move.coords == (8, 8) and node.move.player == "B"

    def test_pass_is_redrawn_when_katago_has_no_pass_candidate(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=1)
        engine = FakeEngine(hp_fn=_hp({"pass": 0.99, (8, 8): 0.01}), include_pass=False)
        game, node = self._play(tmp_path, engine, opp)
        assert not node.is_pass and node.move.coords == (8, 8)
        assert opp.stats["pass_redraws"] == 1

    def test_passes_when_pass_is_cheap_and_humansl_prefers_it(self, tmp_path):
        engine = FakeEngine(hp_fn=_hp({"pass": 0.9, (8, 8): 0.1}), include_pass=True, pass_loss=0.1)
        game, node = self._play(tmp_path, engine, HumanSLOpponent("rank_3k", seed=0, tau=0.05))
        assert node.is_pass

    def test_costly_pass_is_redrawn(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0, tau=0.05)
        engine = FakeEngine(hp_fn=_hp({"pass": 0.9, (8, 8): 0.1}), include_pass=True, pass_loss=3.0)
        game, node = self._play(tmp_path, engine, opp)
        assert not node.is_pass and opp.stats["pass_redraws"] == 1

    def test_illegal_sample_is_redrawn(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0)
        engine = FakeEngine(hp_fn=_hp({(8, 8): 0.99, (0, 8): 0.01}))
        game, node = self._play(tmp_path, engine, opp, moves=[("B", "J9")])
        assert node.move.coords == (0, 8) and node.move.player == "W"
        assert opp.stats["illegal_redraws"] == 1

    def test_max_loss_keeps_only_cheap_katago_candidates(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0, max_loss=0.2)
        engine = FakeEngine(hp_fn=_hp({(0, 0): 0.2, (1, 0): 0.8}))  # 候補 A1(0目) / B1(0.5目) / C1(1.0目)
        game, node = self._play(tmp_path, engine, opp)
        assert node.move.coords == (0, 0) and opp.stats["fallbacks"] == 0

    def test_max_loss_falls_back_to_the_best_move(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0, max_loss=0.2)
        game, node = self._play(tmp_path, FakeEngine(hp_fn=_hp({(8, 8): 1.0})), opp)
        assert node.move.coords == (0, 0) and opp.stats["fallbacks"] == 1

    def test_same_seed_same_moves(self, tmp_path):
        spread = {(x, 8): 0.1 + 0.05 * x for x in range(9)}
        runs = []
        for _ in range(2):
            engine = FakeEngine(
                hp_fn=lambda node, empties: hp_array(9, {k: v for k, v in spread.items() if k in empties})
            )
            game = new_game(make_stub(tmp_path), engine)
            opp = HumanSLOpponent("rank_3k", seed=42)
            waiter = Waiter(engine, timeout=5)
            seq = []
            for _ in range(4):
                seq.append(opp.play(game, waiter).move.gtp())
            runs.append(seq)
        assert runs[0] == runs[1]
