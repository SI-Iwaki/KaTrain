# tests/test_selfplay_opponent.py
"""自己対局ハーネスの相手ボット HumanSLOpponent と待ちループ Waiter（偽エンジン・本物の Game）。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §3
"""

import types

import pytest

from katrain.core.constants import OUTPUT_ERROR, PRIORITY_EXTRA_AI_QUERY
from katrain.core.sgf_parser import Move
from katrain_debug.selfplay_opponent import BookOpponent, GameAborted, HumanSLOpponent, Waiter
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

    def test_humansl_failure_reason_is_kept(self, tmp_path):
        engine = FakeEngine(hp_errors={"rank_9d": "humanSL model not loaded"})
        game = new_game(make_stub(tmp_path), engine)
        waiter = Waiter(engine, timeout=5)
        assert waiter.humansl(game.current_node, "rank_9d") is None
        assert waiter.humansl_error == "humanSL model not loaded"
        assert "humanPolicy" in waiter.humansl(game.current_node, "rank_3k") and waiter.humansl_error is None
        engine.hp_fn = lambda node, empties: None  # 応答はあるが humanPolicy が無い
        waiter.humansl(game.current_node, "rank_3k")
        assert waiter.humansl_error == "no humanPolicy"

    def test_humansl_error_is_reset_before_the_wait_can_raise(self, tmp_path):
        """until() が例外（タイムアウト等）を投げても、前回の humansl() の stale なエラーが残らない。"""
        engine = FakeEngine(hp_errors={"rank_9d": "boom"})
        game = new_game(make_stub(tmp_path), engine)
        waiter = Waiter(engine, timeout=5)
        waiter.humansl(game.current_node, "rank_9d")
        assert waiter.humansl_error == "boom"

        class _StuckEngine:
            def check_alive(self):
                return True

            def request_analysis(self, node, callback, error_callback=None, **kwargs):
                pass  # 応答しない -> until() がタイムアウトで GameAborted を投げる

        stuck = Waiter(_StuckEngine(), timeout=0.05)
        stuck.humansl_error = "stale"
        with pytest.raises(GameAborted, match="timeout"):
            stuck.humansl(game.current_node, "rank_3k")
        assert stuck.humansl_error is None


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
        assert opp.stats["humansl_errors"] == 0  # humanSL は通っていて、max_loss で候補が空になっただけ

    def test_humansl_error_falls_back_to_the_best_move_and_is_counted_and_logged(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0)
        engine = FakeEngine(hp_errors={"rank_3k": "humanSL model not loaded"})
        game, node = self._play(tmp_path, engine, opp)
        assert node.move.coords == (0, 0)  # KataGo の最善手（左下）で局は続く
        assert opp.stats["humansl_errors"] == 1 and opp.stats["fallbacks"] == 1
        errors = [msg for msg, level in game.katrain.logs if level == OUTPUT_ERROR]
        assert len(errors) == 1 and errors[0].startswith("selfplay: opponent humanSL failed:")
        assert "rank_3k" in errors[0] and "humanSL model not loaded" in errors[0]

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


def _book_position(nodes, depth, next_player, best="E5"):
    """BookOpponent の単体テスト用の局面（stub のノード）。nodes: [(手数, 打った色, points_lost)]（root は足す）。"""
    root = types.SimpleNamespace(depth=0, player="W", points_lost=None)
    path = [root] + [types.SimpleNamespace(depth=d, player=p, points_lost=pl) for d, p, pl in nodes]
    cn = types.SimpleNamespace(
        depth=depth, next_player=next_player, nodes_from_root=path, candidate_moves=[{"move": best}]
    )
    played = []

    def play(move):
        played.append((move.player, move.gtp()))
        return "book-node"

    return types.SimpleNamespace(current_node=cn, play=play), played


class _Inner:
    label = "humanSL:rank_3d"

    def __init__(self):
        self.stats = {"moves": 0, "fallbacks": 0, "humansl_errors": 0}
        self.calls = 0

    def play(self, game, waiter):
        self.calls += 1
        return "inner-node"


_NO_WAIT = types.SimpleNamespace(nodes=lambda nodes, what: None)


class TestBookOpponent:
    """定跡を知る相手（spec 2026-09-23-veil-strategy-design.md §16.2 手順6）。"""

    def test_plays_the_best_move_while_the_ai_stays_in_the_book(self):
        inner = _Inner()
        opp = BookOpponent(inner, book_moves=12, book_loss=0.3)
        # AI は黒（相手＝白の手番）。相手自身の損失（2.0）は見ない
        game, played = _book_position([(1, "B", 0.1), (2, "W", 2.0), (3, "B", 0.3)], depth=3, next_player="W")
        assert opp.play(game, _NO_WAIT) == "book-node" and played == [("W", "E5")] and inner.calls == 0
        assert opp.stats == {
            "moves": 0,
            "fallbacks": 0,
            "humansl_errors": 0,
            "book_played": 1,
            "book_exit_depth": None,
            "book_exit_reason": None,
        }
        assert opp.label == "book12@0.3+humanSL:rank_3d"

    def test_one_ai_move_over_the_limit_leaves_the_book_for_the_rest_of_the_game(self):
        inner = _Inner()
        opp = BookOpponent(inner, book_moves=12, book_loss=0.3)
        game, played = _book_position([(1, "B", 0.31)], depth=1, next_player="W")
        assert opp.play(game, _NO_WAIT) == "inner-node" and played == []
        game, played = _book_position([(1, "B", 0.31), (2, "W", 0.0), (3, "B", 0.0)], depth=3, next_player="W")
        assert opp.play(game, _NO_WAIT) == "inner-node" and played == [] and inner.calls == 2
        assert (opp.stats["book_exit_depth"], opp.stats["book_exit_reason"]) == (1, "ai_loss")

    def test_a_move_without_points_lost_leaves_the_book(self):
        opp = BookOpponent(_Inner(), book_moves=12)
        game, _ = _book_position([(1, "W", None)], depth=1, next_player="B")  # AI は白
        assert opp.play(game, _NO_WAIT) == "inner-node" and opp.stats["book_exit_reason"] == "ai_loss"

    def test_stops_at_the_book_length(self):
        opp = BookOpponent(_Inner(), book_moves=4)
        game, played = _book_position([(1, "B", 0.0), (2, "W", 0.0), (3, "B", 0.0)], depth=3, next_player="W")
        assert opp.play(game, _NO_WAIT) == "book-node"  # 手数 3 < 4
        game, played = _book_position([(d, "BW"[(d - 1) % 2], 0.0) for d in range(1, 6)], depth=5, next_player="W")
        assert opp.play(game, _NO_WAIT) == "inner-node" and played == []
        assert (opp.stats["book_played"], opp.stats["book_exit_depth"], opp.stats["book_exit_reason"]) == (
            1,
            4,
            "limit",
        )

    def test_wraps_the_humansl_opponent_on_a_real_game(self, tmp_path):
        engine = FakeEngine(hp_fn=_hp({(8, 8): 1.0}))  # humanSL は右上（J9）・KataGo の最善手は左下（A1）から
        game = new_game(make_stub(tmp_path), engine)
        opp = BookOpponent(HumanSLOpponent("rank_3k", seed=1), book_moves=1)
        waiter = Waiter(engine, timeout=5)
        first = opp.play(game, waiter)  # 手数 0 < 1: KataGo の最善手
        assert first.move.gtp() == "A1" and first.move.player == "B"
        game.play(Move.from_gtp("B1", player="W"))
        third = opp.play(game, waiter)  # 手数 2 >= 1: 包んだ humanSL
        assert third.move.coords == (8, 8)
        assert opp.stats["book_played"] == 1 and opp.stats["moves"] == 1 and opp.stats["book_exit_reason"] == "limit"
