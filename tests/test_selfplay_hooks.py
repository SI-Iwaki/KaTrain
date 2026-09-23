# tests/test_selfplay_hooks.py
"""自己対局ハーネスの hp 監査と影判定（katrain_debug/selfplay_hooks.py）。偽エンジン・本物の Game。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §4・§6
"""

import json
import os
import random

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import AIStrategy
from katrain.core.sgf_parser import Move
from katrain_debug import selfplay as CLI
from katrain_debug import selfplay_game as G
from katrain_debug import selfplay_hooks as H
from katrain_debug.selfplay_opponent import HumanSLOpponent, Waiter
from tests.selfplay_fakes import FakeEngine, make_stub, new_game


class _StickyProbe(AIStrategy):
    """影の B: game に sticky な状態を積み、グローバル乱数を消費し、最善手を返す。"""

    def generate_move(self):
        state = dict(getattr(self.game, "_veil_state", None) or {})
        state["B"] = state.get("B", 0) + 1
        self.game._veil_state = state
        self.game.board_watch_probe_warm = True
        random.random()
        self.last_decision_info = {"kind": "free", "n": state["B"]}
        return Move.from_gtp(self.cn.candidate_moves[0]["move"], player=self.cn.next_player), "probe"


@pytest.fixture
def probe_mode(monkeypatch):
    monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_probe", _StickyProbe)
    return G.Arm("B", "x", "ai:test_probe", {}, [], "_StickyProbe", "test")


class TestShadow:
    def test_state_keys(self):
        names = ["_veil_state", "_enigma13plus_endgame", "_mimic13_endgame", "board_watch_probe_warm", "_lock", "root"]
        assert H.shadow_state_keys(names) == [
            "_enigma13plus_endgame",
            "_mimic13_endgame",
            "_veil_state",
            "board_watch_probe_warm",
        ]

    def test_arm_a_state_is_untouched_and_b_keeps_its_own(self, tmp_path, probe_mode):
        game = new_game(make_stub(tmp_path), FakeEngine())
        game._veil_state = {"A": 1}
        before_node = game.current_node
        store = {}
        random.seed(3)
        rng_before = random.getstate()
        first = H.run_shadow(game, probe_mode, store)
        second = H.run_shadow(game, probe_mode, store)
        assert first["move"] == "A1" and first["decision"] == {"kind": "free", "n": 1} and first["vloss"] == 0.0
        assert second["decision"]["n"] == 2  # B の sticky 状態は影の store で持ち続ける
        assert game._veil_state == {"A": 1} and game.board_watch_probe_warm is False
        assert store["_veil_state"] == {"B": 2} and store["board_watch_probe_warm"] is True
        assert random.getstate() == rng_before
        assert game.current_node is before_node and not before_node.children

    def test_shadow_failure_does_not_stop_the_game(self, tmp_path, monkeypatch):
        class Crashes(AIStrategy):
            def generate_move(self):
                raise RuntimeError("shadow bug")

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_shadow_crash", Crashes)
        game = new_game(make_stub(tmp_path), FakeEngine())
        out = H.run_shadow(game, G.Arm("B", "x", "ai:test_shadow_crash", {}, [], "Crashes", "t"), {})
        assert out["move"] is None and "shadow bug" in out["error"]

    def test_shadow_hook_in_a_game(self, tmp_path, probe_mode):
        stub = make_stub(tmp_path)
        h = G.Harness(stub, FakeEngine(), size=9, timeout=5)
        arm_a = G.resolve_arm(stub, "A", "default", [])
        spec = {"index": 0, "seed": 1, "ai_color": "B", "rank": "rank_3k", "opp_seed": 7, "strategy_seed": 11}
        spec["resign_lead"] = None
        opponent = HumanSLOpponent("rank_3k", seed=7)
        res = G.play_game(h, arm_a, spec, opponent, max_moves=6, hooks=[H.ShadowHook(probe_mode)])
        ai_rows = [r for r in res.rows if r["is_ai"]]
        assert [r["shadow"]["decision"]["n"] for r in ai_rows] == [1, 2, 3]
        assert all(r["played"] == r["best_at_decision"] for r in ai_rows)
        assert res.record["shadow"]["n"] == 3 and res.record["shadow"]["same_as_played"] == 1.0
        assert not hasattr(res.game, "_veil_state")  # A（DefaultStrategy）は状態を持たない＝B の状態が漏れていない


class TestHpAudit:
    def test_records_hp_of_the_played_and_best_moves(self, tmp_path):
        engine = FakeEngine()
        stub = make_stub(tmp_path)
        game = new_game(stub, engine)
        move, played, strategy = G._ai_turn(game, "ai:default", {})
        out = H.HpAuditHook("rank_9d").after_ai(game, strategy, move, Waiter(engine, 5))
        assert out == {"hp_played": 0.0, "hp_best": 0.0, "hp_rank": 3}  # 既定の偽 humanSL は右上2点だけ
        node, kw = engine.requests[-1]
        assert node is strategy.cn and kw["visits"] == 1
        assert kw["extra_settings"]["humanSLProfile"] == "rank_9d"

    def test_factory_skips_shadowing_the_arm_itself(self, probe_mode):
        arms = {"A": probe_mode, "B": probe_mode}
        factory = H.make_hooks_factory({"shadow": "B", "hp_audit": "rank_9d"}, arms)
        assert [type(x).__name__ for x in factory("A")] == ["ShadowHook", "HpAuditHook"]
        assert [type(x).__name__ for x in factory("B")] == ["HpAuditHook"]
        assert H.make_hooks_factory({}, arms)("A") == []


class TestCli:
    def _args(self, tmp_path, *extra):
        return [
            "run",
            "--arm",
            "A=default",
            "--arm",
            "B=default:dummy=2",
            "--size",
            "9",
            "--pairs",
            "1",
            "--ranks",
            "rank_3k",
            "--no-resign",
            "--max-moves",
            "4",
            "--timeout",
            "5",
            "--boot",
            "100",
            "--config",
            str(tmp_path / "config.json"),
            "--out-root",
            str(tmp_path / "out"),
            *extra,
        ]

    def test_shadow_and_hp_audit_flags(self, tmp_path, monkeypatch, capsys):
        make_stub(tmp_path, **{"ai:default": {"dummy": 1}})
        monkeypatch.setattr(CLI, "start_engine", lambda stub: FakeEngine())
        monkeypatch.setattr(CLI, "katago_processes", lambda: [])
        CLI.main(self._args(tmp_path, "--shadow", "B", "--hp-audit", "rank_9d"))
        assert "paired diff A - B" in capsys.readouterr().out  # 2アームの run はアーム間の差の表も出す
        run_dir = os.path.join(tmp_path / "out", os.listdir(tmp_path / "out")[0])
        plan = json.load(open(os.path.join(run_dir, "run.json"), encoding="utf-8"))
        assert plan["shadow"] == "B" and plan["hp_audit"] == "rank_9d"
        recs = {r["arm"]: r for r in map(json.loads, open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8"))}
        assert recs["A"]["shadow"]["arm"] == "B" and recs["B"]["shadow"] is None
        moves = [json.loads(x) for x in open(os.path.join(run_dir, "moves.jsonl"), encoding="utf-8")]
        assert all(m["hp_rank"] is not None for m in moves if m["is_ai"])

    def test_unknown_shadow_arm_is_refused(self, tmp_path, monkeypatch):
        make_stub(tmp_path, **{"ai:default": {"dummy": 1}})
        monkeypatch.setattr(CLI, "katago_processes", lambda: [])
        with pytest.raises(SystemExit, match="--shadow C"):
            CLI.main(self._args(tmp_path, "--shadow", "C"))
