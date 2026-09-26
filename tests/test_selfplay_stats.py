# tests/test_selfplay_stats.py
"""自己対局ハーネスの純関数（katrain_debug/selfplay_stats.py）。KataGo 不要。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md
"""

import random
import threading
import types

import pytest

from katrain.core.ai import enigma9_hp_lookup, game_report
from katrain.core.game_node import GameNode
from katrain.core.sgf_parser import Move
from katrain_debug import selfplay_stats as S

THRESHOLDS = [12, 6, 3, 1.5, 0.5, 0]


# ---- 盤サイズ・座標 ----
class TestBoardConstants:
    def test_move_cap_and_resign_start(self):
        assert [S.move_cap(n) for n in (9, 13, 19)] == [120, 250, 400]
        assert [S.resign_start_move(n) for n in (9, 13, 19)] == [19, 40, 85]

    def test_calibration_bins_match_game_report_boundaries(self):
        assert S.depth_bin(23, 13) == "cal_opening"
        assert S.depth_bin(24, 13) == "cal_middle"
        assert S.depth_bin(84, 13) == "cal_middle"
        assert S.depth_bin(85, 13) == "cal_endgame"
        assert S.depth_bin(11, 9) == "cal_opening" and S.depth_bin(12, 9) == "cal_middle"

    def test_calibration_bin_moves_by_board_size(self):
        """spec 2026-09-23-veil-strategy-design.md §16.2 手順3: 13路の境目は変えない・9路は 12 / 41 手。"""
        assert S.calib_bin_moves(13) == (24, 85)
        assert S.calib_bin_moves(9) == (12, 41)
        assert S.calib_bin_moves(19) == (52, 182)
        for size in (9, 13, 19):
            lo, hi = S.calib_bin_moves(size)
            for depth in range(1, size * size + 1):
                want = "cal_opening" if depth < lo else "cal_middle" if depth < hi else "cal_endgame"
                assert S.depth_bin(depth, size) == want

    def test_calibration_targets_by_board_size(self):
        assert S.calib_targets_for(13) is S.CALIB_TARGETS_13 and S.CALIB_TARGET_GAMES[13] == "16/18"
        assert S.calib_targets_for(19) is None  # 目標の無い盤は calibrate がプールを選ばない
        assert S.CALIB_TARGETS_13 == {  # 13路の目標は変えない
            "opp_mean": 0.231,
            "opp_sd": 0.065,
            "opp_loss": 1.77,
            "opp_ge2": 0.28,
            "opp_ge5": 0.10,
            "ai_mean": 0.533,
            "moves_median": 78.5,
            "bins": {
                "cal_opening": {"opp_top1": 0.267, "opp_loss": 0.56},
                "cal_middle": {"opp_top1": 0.182, "opp_loss": 2.43},
                "cal_endgame": {"opp_top1": 0.291, "opp_loss": 0.96},
            },
        }

    def test_calibration_targets_9_have_the_shape_of_13(self):
        """計測の準備（C3）: 9路の目標は recon_9 から（spec §16.2 手順4）。形は 13路と同じ。"""
        assert S.calib_targets_for(9) is S.CALIB_TARGETS_9 and S.CALIB_TARGET_GAMES[9] == "7/16"
        assert S.CALIB_TARGETS_9 == {  # 9路の目標は変えない（recon_9 から。C3）
            "opp_mean": 0.308,
            "opp_sd": 0.166,
            "opp_loss": 1.88,
            "opp_ge2": 0.23,
            "opp_ge5": 0.1,
            "ai_mean": 0.628,
            "moves_median": 48.0,
            "bins": {
                "cal_opening": {"opp_top1": 0.233, "opp_loss": 0.77},
                "cal_middle": {"opp_top1": 0.332, "opp_loss": 2.4},
                "cal_endgame": {"opp_top1": 0.355, "opp_loss": 0.78},
            },
        }
        assert set(S.CALIB_TARGETS_9) == set(S.CALIB_TARGETS_13)
        assert all(set(S.CALIB_TARGETS_9["bins"][b]) == {"opp_top1", "opp_loss"} for b in S.CALIB_TARGETS_13["bins"])
        assert S.CALIB_TARGETS_9["moves_median"] == 48

    def test_gtp_keys_match_move(self):
        for gtp in ("A1", "D4", "N13", "T19", "J9"):
            assert S.gtp_to_key(gtp) == Move.from_gtp(gtp).coords
            assert S.key_to_gtp(S.gtp_to_key(gtp)) == gtp
        assert S.gtp_to_key("pass") == "pass" and S.key_to_gtp("pass") == "pass"

    def test_hp_index_matches_enigma9_hp_lookup(self):
        hp = [i / 1000 for i in range(13 * 13 + 1)]
        lookup = enigma9_hp_lookup(hp, (13, 13))
        for gtp in ("A1", "N13", "G7", "C11", "pass"):
            assert hp[S.hp_index(S.gtp_to_key(gtp), 13)] == lookup(gtp)

    def test_hp_to_cands_drops_illegal_and_zero_and_keeps_pass(self):
        hp = [0.0] * 82
        hp[S.hp_index((2, 2), 9)] = 0.5
        hp[S.hp_index((4, 4), 9)] = -1.0
        hp[81] = 0.2
        assert S.hp_to_cands(hp, 9) == [((2, 2), 0.5), ("pass", 0.2)]

    def test_hp_audit_values(self):
        hp = [0.0] * 82
        hp[S.hp_index(S.gtp_to_key("C3"), 9)] = 0.6
        hp[S.hp_index(S.gtp_to_key("D4"), 9)] = 0.3
        hp[81] = 0.1
        assert S.hp_audit_values(hp, 9, "D4", "C3") == {"hp_played": 0.3, "hp_best": 0.6, "hp_rank": 2}
        assert S.hp_audit_values(hp, 9, "E5", "C3")["hp_rank"] == 4


# ---- 日程 ----
class TestSchedule:
    def test_same_seed_gives_same_conditions(self):
        a = S.selfplay_schedule(12, ["rank_3k", "rank_1d"], 1000, resign_leads=[3.9, 28.9, 52.5])
        b = S.selfplay_schedule(12, ["rank_3k", "rank_1d"], 1000, resign_leads=[3.9, 28.9, 52.5])
        assert a == b
        assert [s["seed"] for s in a] == list(range(1000, 1012))

    def test_colors_alternate_and_ranks_are_stratified_by_color(self):
        ranks = ["rank_8k", "rank_5k", "rank_3k", "rank_1k", "rank_1d", "rank_3d"]
        sched = S.selfplay_schedule(48, ranks, 7)
        assert [s["ai_color"] for s in sched[:4]] == ["B", "W", "B", "W"]
        for rank in ranks:
            games = [s for s in sched if s["rank"] == rank]
            assert len(games) == 8
            assert sum(s["ai_color"] == "B" for s in games) == 4

    def test_resign_threshold_sources(self):
        pool = [3.9, 28.9, 52.5]
        assert all(s["resign_lead"] in pool for s in S.selfplay_schedule(20, ["r"], 1, resign_leads=pool))
        assert all(8 <= s["resign_lead"] <= 40 for s in S.selfplay_schedule(20, ["r"], 1, resign_range=(8, 40)))
        assert all(
            s["resign_lead"] is None for s in S.selfplay_schedule(5, ["r"], 1, resign_leads=pool, no_resign=True)
        )

    def test_length_model_draws_a_target_length_per_seed(self):
        lens = [59, 79, 123]
        a = S.selfplay_schedule(12, ["rank_3k", "rank_1d"], 1000, resign_lens=lens)
        assert a == S.selfplay_schedule(12, ["rank_3k", "rank_1d"], 1000, resign_lens=lens)  # seed ごとに決まる
        assert all(s["resign_len"] in lens and s["resign_lead"] is None for s in a)
        assert len({s["resign_len"] for s in a}) > 1  # 局ごとに引き直す
        lead = S.selfplay_schedule(12, ["rank_3k", "rank_1d"], 1000, resign_leads=[3.9, 28.9])
        assert [(s["opp_seed"], s["strategy_seed"]) for s in a] == [(s["opp_seed"], s["strategy_seed"]) for s in lead]
        assert all(s["resign_len"] is None for s in lead)
        assert all(
            s["resign_len"] is None and s["resign_lead"] is None
            for s in S.selfplay_schedule(4, ["r"], 1, resign_lens=lens, no_resign=True)
        )

    def test_unbalanced_strata_are_warned(self):
        ranks = ["rank_3k", "rank_1k", "rank_1d"]
        warn = S.schedule_balance_warning(S.selfplay_schedule(20, ranks, 1), ranks)
        assert "8/6/6" in warn and "multiple of 6" in warn
        assert S.schedule_balance_warning(S.selfplay_schedule(12, ranks, 1), ranks) is None

    def test_empty_ranks_is_an_error(self):
        with pytest.raises(ValueError):
            S.selfplay_schedule(2, [], 1)

    def test_abba_order(self):
        order = S.abba_order(["A", "B"], 20)
        assert order[:10] == [("A", i) for i in range(10)]
        assert order[10:20] == [("B", i) for i in range(10)]
        assert order[20:30] == [("B", i) for i in range(10, 20)]
        assert order[30:] == [("A", i) for i in range(10, 20)]


# ---- 相手ボットの1手 ----
class TestOpponentPick:
    CANDS = [((0, 0), 0.5), ((1, 1), 0.3), ("pass", 0.2)]

    def test_same_rng_seed_gives_same_pick(self):
        picks = [
            S.selfplay_opponent_pick(self.CANDS, random.Random(5), 1.0, lambda k: k, lambda: True)[0] for _ in range(3)
        ]
        assert len(set(picks)) == 1

    def test_illegal_move_is_dropped_and_redrawn(self):
        tried = []

        def try_move(key):
            tried.append(key)
            return None if key == (0, 0) else "played"

        key, res = S.selfplay_opponent_pick([((0, 0), 0.99), ((1, 1), 0.01)], random.Random(0), 1.0, try_move, None)
        assert tried[0] == (0, 0) and key == (1, 1) and res == "played"

    def test_pass_redrawn_when_not_allowed_and_asked_once(self):
        asked = []

        def pass_ok():
            asked.append(1)
            return False

        for seed in range(20):
            asked.clear()
            key, _ = S.selfplay_opponent_pick(
                [("pass", 0.9), ((1, 1), 0.1)], random.Random(seed), 1.0, lambda k: k, pass_ok
            )
            assert key == (1, 1)
            assert len(asked) <= 1

    def test_pass_played_when_allowed(self):
        key, res = S.selfplay_opponent_pick([("pass", 1.0)], random.Random(0), 1.0, lambda k: "node", lambda: True)
        assert key == "pass" and res == "node"

    def test_exhausted_candidates(self):
        assert S.selfplay_opponent_pick([((0, 0), 1.0)], random.Random(0), 1.0, lambda k: None, None) == (None, None)

    def test_low_temperature_concentrates_on_the_top_move(self):
        cands = [((0, 0), 0.6), ((1, 1), 0.4)]
        rng = random.Random(1)
        picks = [S.selfplay_opponent_pick(cands, rng, 0.05, lambda k: k, None)[0] for _ in range(200)]
        assert picks.count((0, 0)) >= 199


# ---- 投了・勝敗 ----
class TestResignAndOutcome:
    def test_needs_two_consecutive_ai_turns_after_the_start_move(self):
        assert S.selfplay_should_resign(39, 20.0, 0.99, 1, 10.0, 13) == (False, 0)
        ok, streak = S.selfplay_should_resign(40, 20.0, 0.99, 0, 10.0, 13)
        assert (ok, streak) == (False, 1)
        assert S.selfplay_should_resign(42, 20.0, 0.99, streak, 10.0, 13) == (True, 2)

    def test_winrate_and_lead_conditions_reset_the_streak(self):
        assert S.selfplay_should_resign(50, 20.0, 0.90, 1, 10.0, 13) == (False, 0)
        assert S.selfplay_should_resign(50, 9.0, 0.99, 1, 10.0, 13) == (False, 0)

    def test_no_resign(self):
        assert S.selfplay_should_resign(100, 50.0, 1.0, 5, None, 13) == (False, 0)

    def test_outcome(self):
        assert S.selfplay_outcome("opp_resign", -3.0) == "win"
        assert S.selfplay_outcome("aborted", 10.0) == "aborted"
        assert S.selfplay_outcome("double_pass", 0.6) == "win"
        assert S.selfplay_outcome("move_cap", -0.8) == "loss"
        assert S.selfplay_outcome("double_pass", 0.2) == "jigo"
        assert S.selfplay_outcome("double_pass", None) == "unknown"

    def test_resign_pool_from_real_game_summaries(self):
        summaries = [
            {"ai": "W", "n_moves": 123, "final_score": -3.9},
            {"ai": "B", "n_moves": 59, "final_score": 28.9},
            {"ai": "W", "n_moves": 31, "final_score": -2.7},  # 開始手数 40 より前に終わった局は除く
        ]
        assert S.resign_pool_from_summaries(summaries, 13) == [3.9, 28.9]
        assert S.resign_pool_from_summaries(summaries, 9) == [round(3.9 * 81 / 169, 2), round(28.9 * 81 / 169, 2)]

    def test_resign_pool_keeps_the_board_of_the_summary(self):
        """final-fix finding 5: resign_pool_from_summaries も resign_lengths_from_summaries と同じく board_size を見る
        （9路の実戦は9路の開始手数〈19〉で判定し、目標盤に合わせて比例させる。13路は今まで通り）。"""
        summaries = [
            {"ai": "B", "n_moves": 48, "final_score": 5.0, "board_size": 9},
            {"ai": "W", "n_moves": 15, "final_score": -2.0, "board_size": 9},  # 9路の開始手数 19 より前 → 除く
        ]
        assert S.resign_pool_from_summaries(summaries, 9) == [5.0]
        assert S.resign_pool_from_summaries(summaries, 13) == [round(5.0 * 169 / 81, 2)]

    def test_resign_lengths_from_real_game_summaries(self):
        summaries = [
            {"ai": "W", "n_moves": 123, "final_score": -3.9},
            {"ai": "W", "n_moves": 31, "final_score": -2.7},  # 長さのモデルは短い局も含める（実戦の手数の分布そのもの）
            {"ai": "B", "final_score": 1.0},  # 手数の無い summary は捨てる
        ]
        assert S.resign_lengths_from_summaries(summaries, 13) == [123, 31]
        assert S.resign_lengths_from_summaries(summaries, 9) == [round(123 * 81 / 169), round(31 * 81 / 169)]
        assert S.resign_lengths_from_summaries(summaries, 19) == [round(123 * 361 / 169), round(31 * 361 / 169)]

    def test_resign_lengths_keep_the_board_of_the_summary(self):
        """spec §16.2 手順5: 9路の実戦（recon_9・summary.board_size 9）は 9路で縮めない。"""
        summaries = [{"ai": "B", "n_moves": 48, "board_size": 9}, {"ai": "W", "n_moves": 31, "board_size": 9}]
        assert S.resign_lengths_from_summaries(summaries, 9) == [48, 31]
        assert S.resign_lengths_from_summaries(summaries, 13) == [round(48 * 169 / 81), round(31 * 169 / 81)]
        assert S.scale_moves(78, 13) == 78 and S.scale_moves(40, 9) == 19 and S.scale_moves_13(40, 9) == 19

    def test_length_model_resigns_at_or_after_the_target_length_when_clearly_winning(self):
        assert S.selfplay_should_resign_at_length(59, 20.0, 0.99, 1, 60) == (False, 0)  # L より前は数えない
        ok, streak = S.selfplay_should_resign_at_length(60, 2.5, 0.90, 0, 60)
        assert (ok, streak) == (False, 1)
        assert S.selfplay_should_resign_at_length(62, 2.5, 0.90, streak, 60) == (True, 2)

    def test_length_model_keeps_checking_after_the_target_length(self):
        assert S.selfplay_should_resign_at_length(70, 2.4, 0.99, 1, 60) == (False, 0)  # リード 2.5 未満
        assert S.selfplay_should_resign_at_length(72, 20.0, 0.89, 1, 60) == (False, 0)  # 勝率 0.90 未満
        ok, streak = S.selfplay_should_resign_at_length(90, 8.0, 0.97, 0, 60)
        assert S.selfplay_should_resign_at_length(92, 8.0, 0.97, streak, 60) == (True, 2)
        assert S.selfplay_should_resign_at_length(92, None, 0.97, 1, 60) == (False, 0)
        assert S.selfplay_should_resign_at_length(200, 50.0, 1.0, 5, None) == (False, 0)

    def test_resign_check_dispatches_on_the_scheduled_model(self):
        length = {"resign_len": 60, "resign_lead": None}
        lead = {"resign_lead": 10.0}  # 長さの列の無い古い日程（run.json）も lead として読む
        assert S.resign_model_of(length) == "length" and S.resign_model_of(lead) == "lead"
        assert S.resign_model_of({"resign_len": None, "resign_lead": None}) == "none"
        assert S.selfplay_resign_check(length, 60, 3.0, 0.91, 1, 13) == (True, 2)
        assert S.selfplay_resign_check(lead, 60, 3.0, 0.91, 1, 13) == (False, 0)  # lead は R 10 と勝率 0.95
        assert S.selfplay_resign_check(lead, 60, 12.0, 0.96, 1, 13) == (True, 2)

    def test_book_exit_depth(self):
        """spec §16.2 手順6: AI の手の points_lost が X を超えた（または無い）最初の手の手数。"""
        assert S.book_exit_depth([(1, 0.1), (3, 0.3), (5, -0.2)], 0.3) is None
        assert S.book_exit_depth([(1, 0.1), (3, 0.31), (5, 2.0)], 0.3) == 3
        assert S.book_exit_depth([(2, None)], 0.3) == 2
        assert S.book_exit_depth([], 0.3) is None and S.BOOK_LOSS == 0.3

    def test_ai_view(self):
        assert S.ai_view_lead(3.0, "W") == -3.0 and S.ai_view_winrate(0.8, "W") == pytest.approx(0.2)


# ---- WATCH 木と1手1行（本物の GameNode と game_report）----
def _analyze(node, lead, moves, complete=True, visits=500):
    """moves: [(gtp, 黒視点 scoreLead)]（order 順）。"""
    node.analysis["root"] = {"scoreLead": lead, "winrate": 0.5 + lead / 100, "visits": visits}
    node.analysis["moves"] = {
        g: {"move": g, "order": i, "scoreLead": s, "winrate": 0.5 + s / 100, "visits": 100, "prior": 0.2, "pv": [g]}
        for i, (g, s) in enumerate(moves)
    }
    node.analysis["completed"] = complete


def _game_with_trailing_passes():
    """B C3(一致) W G7(一致) B D4(外し・1.5目損) W pass(外し) B pass(一致) の 9路。"""
    root = GameNode(properties={"SZ": 9, "KM": 7.0, "RU": "chinese"})
    nodes = [root]
    for player, gtp in (("B", "C3"), ("W", "G7"), ("B", "D4"), ("W", "pass"), ("B", "pass")):
        nodes.append(nodes[-1].play(Move.from_gtp(gtp, player=player)))
    _analyze(nodes[0], 0.5, [("C3", 0.5), ("E5", 0.3)])
    _analyze(nodes[1], 0.5, [("G7", 0.5), ("C7", 0.8)])
    _analyze(nodes[2], 0.5, [("E5", 0.5), ("D4", -1.0)])
    _analyze(nodes[3], -1.0, [("F6", -1.0), ("pass", -0.5)])
    _analyze(nodes[4], -1.0, [("pass", -1.0), ("A1", -1.2)])
    _analyze(nodes[5], -1.0, [])
    game = types.SimpleNamespace(current_node=nodes[5], board_size=(9, 9), _lock=threading.RLock())
    return game, nodes


class TestWatchPrune:
    def test_watch_excludes_trailing_passes_even_when_current_node_is_the_last_pass(self):
        game, nodes = _game_with_trailing_passes()
        strict, _, strict_loss = game_report(game, THRESHOLDS)
        assert strict["B"]["ai_top_move"] == pytest.approx(2 / 3) and strict["W"]["ai_top_move"] == 0.5
        with S.watch_prune(game) as last:
            assert last is nodes[3] and game.current_node is nodes[3]
            watch, _, watch_loss = game_report(game, THRESHOLDS)
        assert watch["B"]["ai_top_move"] == 0.5 and watch["W"]["ai_top_move"] == 1.0
        assert len(watch_loss["B"]) == 2 and len(watch_loss["W"]) == 1
        assert nodes[3].children == [nodes[4]] and game.current_node is nodes[5]

    def test_restores_on_exception(self):
        game, nodes = _game_with_trailing_passes()
        with pytest.raises(RuntimeError):
            with S.watch_prune(game):
                raise RuntimeError("boom")
        assert nodes[3].children == [nodes[4]] and game.current_node is nodes[5]

    def test_report_block(self):
        game, _ = _game_with_trailing_passes()
        sum_stats, _, ptloss = game_report(game, THRESHOLDS)
        block = S.report_block(sum_stats, ptloss, "B")
        assert block["n"] == 3 and block["top1"] == pytest.approx(2 / 3) and block["mean_ptloss"] == pytest.approx(0.5)
        assert S.report_block({"B": {}, "W": {}}, {"B": [], "W": []}, "W") == {
            "top1": None,
            "top5": None,
            "mean_ptloss": None,
            "n": 0,
        }


class TestMoveRows:
    def test_rows_follow_the_report_definition(self):
        _, nodes = _game_with_trailing_passes()
        rows = S.selfplay_move_rows(nodes[1:], "B", 9, max_visits=600)
        assert [r["match"] for r in rows] == [True, True, False, False, True]
        assert rows[2]["points_lost"] == pytest.approx(1.5) and rows[2]["loss"] == pytest.approx(1.5)
        assert [r["trailing_pass"] for r in rows] == [False, False, False, True, True]
        assert rows[2]["run_own_rate"] == 0.5 and rows[4]["run_own_rate"] == pytest.approx(2 / 3)
        assert rows[1]["run_opp_rate"] == 1.0
        assert rows[0]["visits_low"] is True  # 500 < 0.9 * 600
        assert rows[2]["lead_before_ai"] == 0.5 and rows[2]["lead_after_ai"] == -1.0
        assert rows[0]["bin"] == "cal_opening"

    def test_flat_row(self):
        row = {"depth": 3, "decision": {"kind": "free", "vloss": 0.1}, "shadow": {"move": "D4"}}
        assert S.flat_row(row) == {"depth": 3, "decision_kind": "free", "decision_vloss": 0.1, "shadow_move": "D4"}
        assert S.flat_row({"depth": 1, "decision": None}) == {"depth": 1}

    def test_merge_turns_only_touches_ai_rows(self):
        rows = [{"depth": 1, "is_ai": True}, {"depth": 2, "is_ai": False}]
        S.merge_turns(rows, [{"depth": 1, "strategy_s": 0.5}, {"depth": 2, "strategy_s": 9.9}])
        assert rows[0]["strategy_s"] == 0.5 and "strategy_s" not in rows[1]


# ---- 1局の要約 ----
def _row(depth, is_ai, match, loss, **kw):
    base = {
        "depth": depth,
        "is_ai": is_ai,
        "match": match,
        "best": "C3",
        "move": "C3" if match else "D4",
        "points_lost": loss,
        "loss": None if loss is None else max(0.0, loss),
        "lead_after_ai": 5.0,
        "wr_before_ai": 0.8,
        "wr_after_ai": 0.8,
        "visits_low": False,
    }
    base.update(kw)
    return base


def _reports(own, opp, own_n=10, opp_n=10):
    block = {"ai": {"top1": own, "top5": 0.9, "mean_ptloss": 0.4, "n": own_n}}
    block["opp"] = {"top1": opp, "top5": 0.5, "mean_ptloss": 1.8, "n": opp_n}
    return {"WATCH": {"all": block}, "STRICT": {"all": block}}


META = {"arm": "A", "seed": 1000, "rank": "rank_3k", "ai_color": "B", "end_reason": "opp_resign"}


class TestGameSummary:
    def test_rates_flags_tails_and_flips(self):
        rows = [
            _row(1, True, True, 0.0),
            _row(2, False, False, 5.5),
            _row(3, True, False, 6.2, wr_before_ai=0.55, wr_after_ai=0.40),
            _row(4, False, True, 2.0),
            _row(5, True, False, 1.1),
        ]
        rec = S.selfplay_game_summary(META, _reports(0.32, 0.25), rows, target=0.30, wall_s=12.0)
        assert rec["result"] == "win" and rec["n_moves"] == 5
        assert rec["own_minus_opp"] == pytest.approx(0.07) and rec["own_lt_opp"] is False
        assert rec["own_le_target_plus5"] is True and rec["own_lt_floor"] is False
        assert rec["ai_tail"] == {"ge1": 2, "ge2": 1, "ge3": 1, "ge6": 1}
        assert rec["opp_tail"] == {"n": 2, "ge2": 2, "ge5": 1}
        assert rec["flip_moves"] == 1
        assert rec["veil"] is None and rec["shadow"] is None
        assert rec["wall_s"] == 12.0

    def test_hp_audit_and_intent_mismatch(self):
        rows = [
            _row(1, True, False, 0.3, hp_played=0.02, best_at_decision="C3", played="D4"),
            _row(3, True, False, 0.2, hp_played=0.30, best_at_decision="C3", played="D4"),
            _row(5, True, True, 0.0, hp_played=0.90, best_at_decision="E5", played="C3"),
        ]
        rec = S.selfplay_game_summary(META, _reports(0.33, 0.2), rows, target=0.30)
        assert rec["hp_dev_list"] == [0.02, 0.3] and rec["hp_dev_median"] == pytest.approx(0.16)
        assert rec["hp_dev_lt5"] == 0.5
        assert rec["intent_report_mismatch"] == 1  # 外したつもり（E5 ではなく C3）がレポートでは一致

    def test_decision_metrics_only_for_strategies_with_decision_info(self):
        rows = [
            _row(
                1,
                True,
                False,
                0.2,
                decision={"tier": "iii", "kind": "free", "best": "C3", "chosen": "D4", "vloss": 0.2, "lead": 2.0},
            ),
            _row(2, False, False, 3.0),
            _row(
                3,
                True,
                False,
                1.0,
                decision={"tier": "iii", "kind": "paid", "best": "C3", "chosen": "D4", "vloss": 1.0, "lead": 9.0},
            ),
            _row(
                5,
                True,
                False,
                0.5,
                decision={
                    "tier": "iii",
                    "kind": "trap",
                    "best": "C3",
                    "chosen": "D4",
                    "vloss": 0.5,
                    "lead": 8.0,
                    "E": 2.0,
                },
            ),
            _row(6, False, False, 3.0),
            _row(
                7,
                True,
                True,
                0.0,
                decision={"tier": "ii", "kind": "best", "best": "C3", "chosen": "C3", "vloss": 0.0, "lead": 4.0},
            ),
        ]
        ledger = [(0, "C3", "D4", "free"), (6, "C3", "E5", "free")]
        rec = S.selfplay_game_summary(META, _reports(0.25, 0.2), rows, target=0.30, reserve=5.0, ledger=ledger)
        veil = rec["veil"]
        assert veil["tiers"] == {"iii": 3, "ii": 1}
        assert veil["kinds"] == {"free": 1, "paid": 1, "trap": 1, "best": 1}
        assert veil["paid_vloss_sum"] == pytest.approx(1.7)
        assert veil["vloss_by_kind"]["paid"] == pytest.approx(1.0)
        assert veil["report_loss_by_kind"]["paid"] == pytest.approx(1.0)
        assert veil["curse_by_kind"]["trap"] == pytest.approx(0.0)
        assert veil["nonfree_below_reserve"] == 0
        assert veil["close_free_vloss"] == pytest.approx(0.2)  # lead 2.0 < reserve 5.0
        assert veil["trap_next_loss_over_E"] == pytest.approx(1.5)  # 次の相手手 3.0 / E 2.0
        assert veil["ledger_mismatch"] == 1  # depth 6 の外しが depth 7 でレポート一致

    def test_nonfree_below_reserve_ignores_the_terminal_band(self):
        # 終局帯（tier terminal）のパス・ダメ詰めの入れ替え・9段の締めの手は、リード < reserve でも支払う外しではない
        def dec(tier, kind, chosen, lead):
            return {"tier": tier, "kind": kind, "best": "C3", "chosen": chosen, "vloss": 0.0, "lead": lead}

        rows = [
            _row(1, True, False, 0.0, move="pass", decision=dec("terminal", "pass", "pass", 1.0)),
            _row(3, True, False, 0.04, decision=dec("terminal", "swap", "D4", 1.0)),
            _row(5, True, False, 0.02, move="E5", decision=dec("terminal", "finish", "E5", 2.0)),
            _row(7, True, False, 1.0, decision=dec("iii", "paid", "D4", 4.0)),
        ]
        veil = S.selfplay_game_summary(META, _reports(0.25, 0.2), rows, target=0.30, reserve=5.0)["veil"]
        assert veil["kinds"] == {"pass": 1, "swap": 1, "finish": 1, "paid": 1}
        assert veil["nonfree_below_reserve"] == 1  # 数えるのは lead 4.0 の paid だけ

    def test_opening_window_turns_are_summarised_apart(self):
        """序盤の研究外し（韜晦 spec §15.4）: 窓の手（tier opening）は lead < reserve でも nonfree_below_reserve に
        入れず、要約の opening に出す。vloss を持たない kind（opening）の vloss_by_kind・curse_by_kind は None。"""

        def dec(kind, chosen, open_, index, tier="opening", **kw):
            d = {"tier": tier, "kind": kind, "best": "C3", "chosen": chosen, "open": open_, "open_index": index}
            return {**d, **kw}

        exception = {"tier": "failsafe", "kind": "best", "best": "C3", "chosen": "C3", "why": "exception"}
        paid = {"tier": "iii", "kind": "paid", "best": "C3", "chosen": "D4", "vloss": 1.0, "lead": 4.0}
        rows = [
            _row(1, True, False, 2.5, decision=dec("opening", "D4", "played", 0, lead=0.5, open_in_cands=True)),
            _row(3, True, True, 0.0, decision=dec("best", "C3", "played", 2, lead=0.4, open_in_cands=True)),
            _row(5, True, False, 7.0, move="J9", decision=dec("opening", "J9", "played", 4, open_in_cands=False)),
            _row(7, True, True, 0.0, decision=dec("best", "C3", "invariant", 6, why="invariant")),
            _row(9, True, True, 0.0, decision=dec("best", "C3", "gate", 8, tier="i", why="no_pool", lead=0.3)),
            _row(11, True, True, 0.0, decision={**exception, "open_index": 10}),
            _row(13, True, False, 1.0, decision=paid),
        ]
        veil = S.selfplay_game_summary(META, _reports(0.25, 0.2), rows, target=0.30, reserve=5.0)["veil"]
        assert veil["nonfree_below_reserve"] == 1  # lead 4.0 の paid だけ（窓の手は lead 0.5 でも数えない）
        assert veil["opening"] == {
            "turns": 4,
            "opening": 2,
            "report_loss": pytest.approx(9.5),
            "ge2": 2,
            "ge6": 1,
            "not_in_cands": 1,
            "gate": 1,
            "invariant": 1,
            "errors": 1,
        }
        assert veil["vloss_by_kind"]["opening"] is None and veil["curse_by_kind"]["opening"] is None
        assert veil["report_loss_by_kind"]["opening"] == pytest.approx(9.5)
        assert veil["vloss_by_kind"]["best"] == pytest.approx(0.0)  # opening 以外の kind は今と同じ値
        assert veil["vloss_by_kind"]["paid"] == pytest.approx(1.0)
        assert veil["curse_by_kind"]["paid"] == pytest.approx(0.0)
        assert veil["paid_vloss_sum"] == pytest.approx(1.0)

    def test_opening_block_is_none_without_window_records(self):
        paid = {"tier": "iii", "kind": "paid", "best": "C3", "chosen": "D4", "vloss": 1.0, "lead": 9.0}
        rows = [_row(1, True, False, 1.0, decision=paid)]
        veil = S.selfplay_game_summary(META, _reports(0.25, 0.2), rows, target=0.30, reserve=5.0)["veil"]
        assert veil["opening"] is None
        assert veil["vloss_by_kind"] == {"paid": pytest.approx(1.0)}

    def test_shadow_metrics(self):
        rows = [
            _row(1, True, True, 0.0, move="C3", shadow={"arm": "B", "move": "D4", "vloss": 0.8, "secs": 0.4}),
            _row(3, True, True, 0.0, move="C3", shadow={"arm": "B", "move": "C3", "vloss": 0.0, "secs": 0.6}),
        ]
        sh = S.selfplay_game_summary(META, _reports(1.0, 0.2), rows, target=0.30)["shadow"]
        assert sh["arm"] == "B" and sh["n"] == 2 and sh["dev_rate"] == 0.5 and sh["same_as_played"] == 0.5
        assert sh["vloss_mean"] == pytest.approx(0.4) and sh["played_loss_mean"] == 0.0


# ---- 統計 ----
class TestStatistics:
    def test_wilson(self):
        lo, hi = S.wilson(10, 10)
        assert lo == pytest.approx(0.72246, abs=1e-4) and hi == 1.0
        assert S.wilson(0, 0) == (None, None)

    def test_t_quantiles(self):
        assert S.t_ppf(0.975, 19) == pytest.approx(2.093024, abs=1e-5)
        assert S.t_ppf(0.975, 1) == pytest.approx(12.706205, abs=1e-4)
        assert S.t_ppf(0.9875, 19) == pytest.approx(2.433440, abs=1e-5)

    def test_wilcoxon_exact(self):
        assert S.wilcoxon_signed_rank([1, 2, 3, 4, 5]) == pytest.approx(0.0625)
        assert S.wilcoxon_signed_rank([1, -2, 3, 4, 5, 6, 7, 8]) == pytest.approx(6 / 256)
        assert S.wilcoxon_signed_rank([0, 0]) is None

    def test_bootstrap_is_deterministic_for_a_seed(self):
        vals = [0.1, 0.4, 0.2, 0.5, 0.3]
        a = S.cluster_bootstrap(vals, lambda s: sum(s) / len(s), 2000, seed=3)
        b = S.cluster_bootstrap(vals, lambda s: sum(s) / len(s), 2000, seed=3)
        assert a == b and a[0] < 0.3 < a[1]

    def test_stop_rule(self):
        assert S.selfplay_stop_rule(-0.05, 0.01) == "extend"
        assert S.selfplay_stop_rule(0.01, 0.05) == "extend"
        assert S.selfplay_stop_rule(-0.02, 0.02) == "within"
        assert S.selfplay_stop_rule(0.04, 0.09) == "higher"
        assert S.selfplay_stop_rule(-0.09, -0.04) == "lower"
        assert S.selfplay_stop_rule(None, None) == "insufficient"


def _rec(arm, seed, own, opp, result="win", **kw):
    base = {
        "arm": arm,
        "seed": seed,
        "rank": "rank_3k",
        "ai_color": "B" if seed % 2 == 0 else "W",
        "result": result,
        "own_top1": own,
        "opp_top1": opp,
        "own_n": 40,
        "opp_n": 40,
        "own_mean_ptloss": 0.5,
        "opp_mean_ptloss": 1.7,
        "own_minus_opp": None if own is None else own - opp,
        "own_lt_opp": None if own is None else own < opp,
        "own_le_target_plus5": None if own is None else own <= 0.35,
        "own_lt_floor": None if own is None else own < 0.15,
        "ai_tail": {"ge6": 0},
        "flip_moves": 0,
        "final_lead": 10.0,
        "n_moves": 80,
        "reports": {"WATCH": {"all": {"ai": {"top1": own, "n": 40}}}},
        "hp_dev_list": [0.1, 0.2],
        "strategy_times": [0.5, 1.0],
        "visits_low": 0,
    }
    base.update(kw)
    return base


class TestArmSummary:
    def test_counts_rates_and_fractions(self):
        recs = [
            _rec("A", 0, 0.30, 0.20),
            _rec("A", 1, 0.50, 0.25, own_n=20),
            _rec("A", 2, 0.10, 0.30, result="loss"),
            _rec("A", 3, None, None, result="aborted"),
        ]
        s = S.selfplay_arm_summary(recs, n_boot=500)
        assert (s["games"], s["aborted"], s["wins"], s["losses"]) == (4, 1, 2, 1)
        assert s["own_top1_mean"] == pytest.approx(0.30)
        assert s["own_top1_pooled"] == pytest.approx((0.30 * 40 + 0.50 * 20 + 0.10 * 40) / 100)
        assert s["p_own_lt_opp"] == pytest.approx(1 / 3)
        assert s["p_own_le_target_plus5"] == pytest.approx(2 / 3)
        assert s["p_own_lt_floor"] == pytest.approx(1 / 3)
        assert s["hp_dev_median"] == pytest.approx(0.15) and s["hp_dev_n"] == 6
        assert s["own_top1_by_bin"]["all"] is not None

    def test_integrity_totals_count_every_game(self):
        recs = [
            _rec(
                "A", 0, 0.3, 0.2, opponent_stats={"moves": 40, "fallbacks": 2, "humansl_errors": 1}, hp_audit_errors=3
            ),
            _rec("A", 1, None, None, result="aborted", opponent_stats={"fallbacks": 1}, shadow_errors=2),
            _rec("A", 2, 0.3, 0.2),  # この修正の前の games.jsonl（フィールドなし）は 0 と数える
        ]
        s = S.selfplay_arm_summary(recs, n_boot=100)
        assert s["integrity"] == {"fallbacks": 3, "humansl_errors": 1, "hp_audit_errors": 3, "shadow_errors": 2}

    def test_summarize_groups_by_arm_and_stratum(self):
        recs = [_rec("A", 0, 0.3, 0.2), _rec("A", 1, 0.4, 0.2), _rec("B", 0, 0.5, 0.2)]
        out = S.selfplay_summarize(recs, n_boot=100)
        assert set(out["arms"]) == {"A", "B"}
        assert set(out["strata"]) == {"A|rank_3k|B", "A|rank_3k|W", "B|rank_3k|B"}

    def test_paired_diff_matches_seeds(self):
        a = [_rec("A", s, 0.30 + 0.01 * s + (0.02 if s % 2 else 0.0), 0.2) for s in range(10)]
        b = [_rec("B", s, 0.40 + 0.01 * s, 0.2) for s in range(1, 11)]
        d = S.selfplay_paired_diff(a, b, "own_top1", n_boot=500)
        assert d["n"] == 9 and d["mean"] == pytest.approx(-0.8 / 9)
        assert d["t_ci"][1] < -0.03 and d["verdict"] == "lower"
        d2 = S.selfplay_paired_diff(a, a, "win", n_boot=100)
        assert d2["n"] == 10 and d2["mean"] == 0.0

    def test_verdict_only_for_rate_metrics(self):
        a = [_rec("A", s, 0.30, 0.2, flip_moves=s % 3) for s in range(6)]
        b = [_rec("B", s, 0.40, 0.2, flip_moves=0) for s in range(6)]
        assert S.selfplay_paired_diff(a, b, "own_top1", n_boot=100)["verdict"] == "lower"
        for metric in ("flip_moves", "win", "own_mean_ptloss", "ge6"):  # 率でない指標に ±3pt の判定線は無意味
            assert S.selfplay_paired_diff(a, b, metric, n_boot=100)["verdict"] is None


class TestArmsAndParsing:
    def test_null_guard_detects_identical_resolved_settings(self):
        arms = [
            {"name": "A", "mode": "ai:veil13", "settings": {"veil13_trap_mode": False}},
            {"name": "B", "mode": "ai:veil13", "settings": {"veil13_trap_mode": False}},
            {"name": "C", "mode": "ai:veil13", "settings": {"veil13_trap_mode": True}},
        ]
        assert S.arms_null_guard(arms) == [("A", "B")]
        assert S.settings_fingerprint("ai:x", {"a": 1, "b": 2}) == S.settings_fingerprint("ai:x", {"b": 2, "a": 1})

    def test_effective_settings_overlay_code_defaults_and_normalise_numbers(self):
        settings = {"veil13_reserve": 4, "other": 2, "flag": True}
        eff = S.effective_settings(settings, "veil13", {"reserve": 3.0, "tau": 1})
        assert eff == {"veil13_reserve": 4.0, "veil13_tau": 1.0, "other": 2.0, "flag": True}
        assert type(eff["flag"]) is bool and type(eff["other"]) is float  # bool は数値にしない
        assert S.effective_settings({"a": 6}) == {"a": 6.0}
        arms = [
            {"name": "A", "mode": "ai:x", "settings": {"k": 6}, "effective_settings": {"k": 6, "d": 1.0}},
            {"name": "B", "mode": "ai:x", "settings": {"k": 6.0, "d": 1}, "effective_settings": {"k": 6.0, "d": 1}},
        ]
        assert S.arms_null_guard(arms) == [("A", "B")]

    def test_unknown_override_keys(self):
        assert S.unknown_override_keys({"veil13_reserv": 4}, {"veil13_reserve": 5}, {"veil13_trap_mode"}) == [
            "veil13_reserv"
        ]
        assert S.unknown_override_keys({"veil13_trap_mode": True}, {}, {"veil13_trap_mode"}) == []

    def test_humansl_profiles_are_stripped_and_validated(self):
        assert S.parse_profiles(" rank_3k, rank_1d ,") == ["rank_3k", "rank_1d"]
        good = ["rank_20k", "rank_1k", "rank_9d", "preaz_5k", "preaz_2d", "proyear_1990"]
        assert S.invalid_humansl_profiles(good) == []
        bad = ["rank3k", "rank_3x", "9d", "rank_3k ", "proyear_90", "strategy:x"]
        assert S.invalid_humansl_profiles(good + bad) == bad

    def test_parse_arm_and_range(self):
        assert S.parse_arm("A=veil13") == ("A", "veil13", [])
        assert S.parse_arm("B=veil13:veil13_trap_mode=true,veil13_reserve=4.0") == (
            "B",
            "veil13",
            ["veil13_trap_mode=true", "veil13_reserve=4.0"],
        )
        with pytest.raises(ValueError):
            S.parse_arm("veil13")
        assert S.parse_range("8:40") == (8.0, 40.0)
        with pytest.raises(ValueError):
            S.parse_range("40:8")


class TestCalibration:
    def _recs(self, rank, rates, loss=1.8):
        out = []
        for i, r in enumerate(rates):
            rec = _rec("calib", i, 0.5, r, rank=rank, opp_mean_ptloss=loss)
            rec["opp_tail"] = {"n": 40, "ge2": 10, "ge5": 4}
            rec["reports"]["WATCH"]["cal_middle"] = {"opp": {"top1": r, "mean_ptloss": 2.0, "n": 20}}
            out.append(rec)
        return out

    def test_rank_stats(self):
        st = S.calibration_rank_stats(self._recs("rank_3k", [0.2, 0.3]))["rank_3k"]
        assert st["games"] == 2 and st["opp_mean"] == pytest.approx(0.25) and st["opp_sd"] == pytest.approx(0.05)
        assert st["opp_ge2"] == 0.25 and st["opp_ge5"] == 0.1
        assert st["bins"]["cal_middle"]["opp_top1"] == pytest.approx(0.25)
        assert st["bins"]["cal_opening"]["opp_top1"] is None

    def test_pool_choice_prefers_the_combo_nearest_the_targets(self):
        recs = (
            self._recs("rank_8k", [0.10, 0.12], loss=3.0)
            + self._recs("rank_3k", [0.20, 0.26], loss=1.8)
            + self._recs("rank_1d", [0.22, 0.30], loss=1.6)
            + self._recs("rank_3d", [0.40, 0.44], loss=0.9)
        )
        choices = S.selfplay_pool_choice(S.calibration_rank_stats(recs))
        assert len(choices) == 4
        assert choices[0]["ranks"] == ["rank_8k", "rank_3k", "rank_1d"]
        assert choices[0]["opp_mean"] == pytest.approx(0.20) and choices[0]["opp_loss"] == pytest.approx(6.4 / 3)
        assert [c["score"] for c in choices] == sorted(c["score"] for c in choices)
        assert choices[0]["bins"]["cal_middle"]["opp_top1"] == pytest.approx((0.11 + 0.23 + 0.26) / 3)
        assert choices[0]["bins"]["cal_opening"]["opp_top1"] is None
