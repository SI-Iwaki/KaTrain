# tests/test_selfplay_runner.py
"""自己対局ハーネスの1局（katrain_debug/selfplay_game.py）。偽エンジン・本物の Game・本物の game_report。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §2・§9
"""

import ast
import inspect
import textwrap
import time
import types

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import AIStrategy, AnalysisDiscardedException, generate_ai_move
from katrain.core.constants import OUTPUT_ERROR
from katrain.core.sgf_parser import Move
from katrain_debug import selfplay_game as G
from katrain_debug.selfplay_opponent import HumanSLOpponent
from tests.selfplay_fakes import FakeEngine, make_stub, new_game


def _body(fn, drop_strategy=False):
    """関数本体（docstring を除く）を ast.unparse で正規化した文のリスト。

    drop_strategy=True なら `return a, b, strategy` を `return a, b` に戻す（_ai_turn の唯一の差分）。
    """
    func = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    body = func.body
    if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if drop_strategy:
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                last = node.value.elts[-1]
                if isinstance(last, ast.Name) and last.id == "strategy":
                    node.value.elts = node.value.elts[:-1]
    return [ast.unparse(stmt) for stmt in body]


class TestAiTurnMirrorsGenerateAiMove:
    def test_body_is_a_line_by_line_copy(self):
        """上流の generate_ai_move が変わったら落ちる（写しが黙ってずれるのを防ぐ・spec §11）。"""
        assert _body(G._ai_turn, drop_strategy=True) == _body(generate_ai_move)

    def test_same_move_and_logs_as_generate_ai_move(self, tmp_path):
        results = []
        for fn in (generate_ai_move, G._ai_turn):
            stub = make_stub(tmp_path)
            game = new_game(stub, FakeEngine())
            out = fn(game, "ai:default", {})
            results.append(
                (
                    out[0].gtp(),
                    out[1] is game.current_node,
                    [m for m, _ in stub.logs if m.startswith(("Generating move using", "Move generation complete"))],
                )
            )
        assert results[0][0] == results[1][0] == "A1"
        assert results[0][1] and results[1][1]
        assert results[0][2] == results[1][2] and len(results[0][2]) == 2

    def test_unknown_mode_falls_back_like_generate_ai_move(self, tmp_path):
        stub = make_stub(tmp_path)
        game = new_game(stub, FakeEngine())
        move, played, strategy = G._ai_turn(game, "ai:nonexistent", {})
        assert type(strategy).__name__ == "DefaultStrategy" and played is not None
        assert any(level == OUTPUT_ERROR and "not found" in msg for msg, level in stub.logs)

    def test_discarded_analysis_returns_no_node(self, tmp_path, monkeypatch):
        class Discards(AIStrategy):
            def generate_move(self):
                raise AnalysisDiscardedException("gone")

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_discard", Discards)
        game = new_game(make_stub(tmp_path), FakeEngine())
        move, played, strategy = G._ai_turn(game, "ai:test_discard", {})
        assert move is None and played is None and isinstance(strategy, Discards)

    def test_moved_position_discards_the_move(self, tmp_path, monkeypatch):
        class MovesTheBoard(AIStrategy):
            def generate_move(self):
                self.game.play(Move.from_gtp("J9", player="B"))
                return Move.from_gtp("A1", player="W"), "late"

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_moved", MovesTheBoard)
        game = new_game(make_stub(tmp_path), FakeEngine())
        move, played, _ = G._ai_turn(game, "ai:test_moved", {})
        assert move.gtp() == "A1" and played is None


class TestResolveArm:
    def test_user_settings_plus_overrides(self, tmp_path):
        stub = make_stub(tmp_path, **{"ai:enigma13plus": {"enigma13plus_max_loss": 3.0}})
        arm = G.resolve_arm(stub, "A", "enigma13plus", ["enigma13plus_max_loss=2.5", "enigma13plus_probe_extra=4"])
        assert arm.mode == "ai:enigma13plus" and arm.strategy_class == "Enigma13PlusStrategy"
        assert arm.settings == {"enigma13plus_max_loss": 2.5, "enigma13plus_probe_extra": 4}
        assert arm.settings_source == "user config"

    def test_typo_is_rejected(self, tmp_path):
        stub = make_stub(tmp_path, **{"ai:enigma13plus": {}})
        with pytest.raises(ValueError, match="enigma13plus_max_los"):
            G.resolve_arm(stub, "A", "enigma13plus", ["enigma13plus_max_los=2.5"])

    def test_unknown_strategy(self, tmp_path):
        with pytest.raises(KeyError):
            G.resolve_arm(make_stub(tmp_path), "A", "nonexistent", [])

    def test_mode_missing_from_user_config_is_flagged(self, tmp_path):
        arm = G.resolve_arm(make_stub(tmp_path), "A", "enigma13", [])
        assert arm.settings == {} and arm.settings_source.startswith("code defaults")


def _spec(ai_color="B", resign_lead=None, seed=1000):
    return {
        "index": 0,
        "seed": seed,
        "ai_color": ai_color,
        "rank": "rank_3k",
        "opp_seed": 7,
        "strategy_seed": 11,
        "resign_lead": resign_lead,
    }


class TestPlayGame:
    def _harness(self, tmp_path, engine=None):
        stub = make_stub(tmp_path)
        return G.Harness(stub, engine or FakeEngine(), size=9, komi=7.0, rules="chinese", timeout=5)

    def test_short_game_reaches_the_move_cap_and_reports_both_sides(self, tmp_path):
        h = self._harness(tmp_path)
        arm = G.resolve_arm(h.stub, "A", "default", [])
        res = G.play_game(h, arm, _spec("B"), HumanSLOpponent("rank_3k", seed=7), max_moves=8)
        rec = res.record
        assert rec["end_reason"] == "move_cap" and rec["n_moves"] == 8 and rec["error"] is None
        assert rec["own_top1"] == 1.0 and rec["opp_top1"] == 0.0  # AI は常に最善手・相手は右上
        assert rec["own_n"] == 4 and rec["opp_n"] == 4
        assert set(rec["reports"]) == {"WATCH", "STRICT"}
        assert set(rec["reports"]["WATCH"]) == {name for name, _ in G.S.REPORT_BINS}
        assert len(res.rows) == 8 and sum(r["is_ai"] for r in res.rows) == 4
        ai_rows = [r for r in res.rows if r["is_ai"]]
        assert all(r["best_at_decision"] == r["played"] for r in ai_rows)
        assert all(r["strategy_s"] >= 0 and r["decision"] is None for r in ai_rows)
        assert rec["opponent"] == "humanSL:rank_3k" and rec["opponent_stats"]["moves"] == 4
        assert rec["opponent_stats"]["humansl_errors"] == 0 and rec["opponent_stats"]["fallbacks"] == 0
        assert rec["hp_audit_errors"] == 0 and rec["shadow_errors"] == 0  # フックなし＝どちらも 0
        assert h.engine.new_games == 1

    def test_ai_as_white_and_komi_shift_against_the_ai(self, tmp_path):
        h = self._harness(tmp_path)
        arm = G.resolve_arm(h.stub, "A", "default", [])
        res = G.play_game(h, arm, _spec("W"), HumanSLOpponent("rank_3k", seed=7), komi_shift=4.0, max_moves=6)
        assert res.record["komi"] == 3.0 and res.game.root.komi == 3.0
        assert res.rows[0]["player"] == "B" and not res.rows[0]["is_ai"]

    def test_no_resignation_below_the_winrate_condition(self, tmp_path):
        h = self._harness(tmp_path, FakeEngine(lead=30.0, winrate=0.6))
        arm = G.resolve_arm(h.stub, "A", "default", [])
        res = G.play_game(h, arm, _spec("B", resign_lead=10.0), HumanSLOpponent("rank_3k", seed=7), max_moves=30)
        assert res.record["end_reason"] == "move_cap"

    def test_resignation_after_two_ai_turns_past_the_start_move(self, tmp_path):
        h = self._harness(tmp_path, FakeEngine(lead=30.0, winrate=0.99))
        arm = G.resolve_arm(h.stub, "A", "default", [])
        res = G.play_game(h, arm, _spec("B", resign_lead=10.0), HumanSLOpponent("rank_3k", seed=7), max_moves=60)
        rec = res.record
        assert rec["end_reason"] == "opp_resign" and rec["result"] == "win"
        assert rec["n_moves"] == 22  # 9路の開始 19 手以降の AI 手番（20・22 手目の局面）で2回続いた
        assert res.game.end_result == "B+R"

    def test_engine_death_aborts_the_game(self, tmp_path):
        engine = FakeEngine()
        h = self._harness(tmp_path, engine)
        arm = G.resolve_arm(h.stub, "A", "default", [])

        class Dies:
            label = "dies"
            stats = {}

            def play(self, game, waiter):
                engine.alive = False
                waiter.until(lambda: False, "a reply that never comes")

        res = G.play_game(h, arm, _spec("W"), Dies(), max_moves=6)
        assert res.record["result"] == "aborted" and "engine died" in res.record["error"]

    def test_opponent_exception_aborts_the_game(self, tmp_path):
        h = self._harness(tmp_path)
        arm = G.resolve_arm(h.stub, "A", "default", [])

        class Crashes:
            label = "crashes"
            stats = {}

            def play(self, game, waiter):
                raise RuntimeError("opp bug")

        res = G.play_game(h, arm, _spec("W"), Crashes(), max_moves=6)
        assert res.record["result"] == "aborted" and "opp bug" in res.record["error"]

    def test_handicap_in_the_config_is_refused(self, tmp_path):
        stub = make_stub(tmp_path)
        stub._config["game"]["handicap"] = 2  # BaseGame は game_properties を渡しても config の置石を置く
        with pytest.raises(SystemExit, match="even games"):
            G.Harness(stub, FakeEngine(), size=9)

    def test_ai_exception_aborts_the_game(self, tmp_path, monkeypatch):
        class Crashes(AIStrategy):
            def generate_move(self):
                raise RuntimeError("bug")

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_crash", Crashes)
        h = self._harness(tmp_path)
        arm = G.Arm("A", "x", "ai:test_crash", {}, [], "Crashes", "test")
        res = G.play_game(h, arm, _spec("B"), HumanSLOpponent("rank_3k", seed=7), max_moves=6)
        assert res.record["result"] == "aborted" and "RuntimeError" in res.record["error"]

    @pytest.mark.parametrize("stage", ["before_ai", "after_ai"])
    def test_hook_exception_aborts_only_the_game(self, tmp_path, stage):
        def crash(*args):
            raise RuntimeError(f"{stage} bug")

        h = self._harness(tmp_path)
        arm = G.resolve_arm(h.stub, "A", "default", [])
        hook = types.SimpleNamespace(**{stage: crash})
        res = G.play_game(h, arm, _spec("B"), HumanSLOpponent("rank_3k", seed=7), max_moves=6, hooks=[hook])
        rec = res.record
        assert rec["result"] == "aborted" and rec["end_reason"] == "aborted"
        assert "RuntimeError" in rec["error"] and f"{stage} bug" in rec["error"]

    def test_hook_with_error_field_but_no_errors_attribute_does_not_raise(self, tmp_path):
        """ERROR_FIELD はあるが errors 属性が無いフックでも、局の終わりの集計で落ちない（getattr の既定値 0）。"""
        h = self._harness(tmp_path)
        arm = G.resolve_arm(h.stub, "A", "default", [])
        hook = types.SimpleNamespace(ERROR_FIELD="hp_audit_errors")  # errors 属性を持たない
        res = G.play_game(h, arm, _spec("B"), HumanSLOpponent("rank_3k", seed=7), max_moves=6, hooks=[hook])
        assert res.record["result"] != "aborted"
        assert res.record["hp_audit_errors"] == 0

    def test_decision_info_is_recorded(self, tmp_path, monkeypatch):
        class Decides(AIStrategy):
            def generate_move(self):
                self.last_decision_info = {"tier": "iii", "kind": "free", "best": "A1", "chosen": "A1", "vloss": 0.0}
                return Move.from_gtp(self.cn.candidate_moves[0]["move"], player=self.cn.next_player), "ok"

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_decides", Decides)
        h = self._harness(tmp_path)
        arm = G.Arm("A", "x", "ai:test_decides", {}, [], "Decides", "test")
        res = G.play_game(h, arm, _spec("B"), HumanSLOpponent("rank_3k", seed=7), max_moves=4)
        assert res.rows[0]["decision"]["kind"] == "free"
        assert res.record["veil"]["tiers"] == {"iii": 2}

    def test_logs_keep_only_strategy_lines(self, tmp_path):
        stub = make_stub(tmp_path)
        stub.log("Sending query QUERY:1", 1)
        stub.log("[0.3][QUERY:1] got 3 moves", 1)
        stub.log("[Veil13Strategy] Decision: {}", 1)
        stub.log("[Enigma13PlusStrategy] board size (9, 9) is not 13x13; playing KataGo best move", 0)
        stub.log("boom", OUTPUT_ERROR)
        assert G.drain_logs(stub) == [
            "[Veil13Strategy] Decision: {}",
            "[Enigma13PlusStrategy] board size (9, 9) is not 13x13; playing KataGo best move",
            "boom",
        ]
        assert stub.logs == []


class TestReportSgf:
    def test_reports_both_colours_from_an_sgf(self, tmp_path):
        path = tmp_path / "g.sgf"
        path.write_text("(;GM[1]FF[4]SZ[9]KM[7]RU[chinese];B[ai];W[ia];B[bi])", encoding="utf-8")
        stub = make_stub(tmp_path)
        out = G.report_sgf(stub, FakeEngine(), str(path), timeout=5)
        watch = out["reports"]["WATCH"]["all"]
        assert out["moves"] == 3
        assert watch["ai"]["top1"] == 1.0 and watch["ai"]["n"] == 2  # 黒 A1・B1 はどちらも左下の最善手
        assert watch["opp"]["top1"] == 0.0 and watch["opp"]["n"] == 1


class TestWatchdog:
    def test_restarts_a_dead_engine(self):
        engine = FakeEngine()
        dog = G.EngineWatchdog(engine, interval=0.01).start()
        engine.alive = False
        started = time.time()
        while dog.restarts == 0 and time.time() - started < 2:
            time.sleep(0.01)
        dog.stop()
        assert dog.restarts >= 1 and engine.restarts >= 1 and engine.alive

    def test_ensure_alive_restarts_only_a_dead_engine(self):
        engine = FakeEngine()
        dog = G.EngineWatchdog(engine)  # start しない（execute_plan が局の前に呼ぶ経路）
        dog.ensure_alive()
        engine.alive = False
        dog.ensure_alive()
        dog.ensure_alive()
        assert dog.restarts == 1 and engine.restarts == 1 and engine.alive
