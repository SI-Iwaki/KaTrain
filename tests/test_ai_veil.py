"""「韜晦（9/13/19路）」ai:veil9 / ai:veil13 / ai:veil19 の純関数・登録整合・_generate_move 通しテスト。

KataGo / Kivy 不要。設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md
"""

import json
import random
import re
import types
from pathlib import Path

import pytest

import katrain
import katrain.core.ai as ai_module
from katrain.core.ai import (
    STRATEGY_REGISTRY,
    VEIL_TERMINAL_MIN_VISITS,
    AnalysisDiscardedException,
    Enigma9Strategy,
    Veil9Strategy,
    Veil13Strategy,
    Veil19Strategy,
    VeilCtx,
    game_report,
    veil_allowance,
    veil_choose,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_decision_record,
    veil_free_limit,
    veil_invariant_ok,
    veil_merge_trap,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_terminal_capped,
    veil_terminal_limit,
    veil_terminal_swap,
    veil_trap_ok,
    veil_trap_price,
    veil_urgency,
)
from katrain.core.constants import AI_VEIL_9, AI_VEIL_13, AI_VEIL_19, OUTPUT_ERROR
from katrain.core.game_node import GameNode
from katrain.core.sgf_parser import Move

THRESHOLDS = [12, 6, 3, 1.5, 0.5, 0]


def _analyze(node, best, complete=True):
    """通常解析を模す。best が candidate_moves[0]（order 0）、A1/B2/C3 のうち best 以外がその後ろ。"""
    others = [g for g in ("A1", "B2", "C3") if g != best]
    node.analysis["moves"] = {
        gtp: {"move": gtp, "order": order, "scoreLead": 0.0, "winrate": 0.5, "prior": 0.1, "visits": 100}
        for order, gtp in enumerate([best, *others])
    }
    node.analysis["root"] = {"scoreLead": 0.0, "winrate": 0.5, "visits": 100}
    node.analysis["completed"] = complete


def _tree(moves, analyses):
    """13路の木（本物の GameNode）。moves: [(player, gtp)]。analyses: root から順に各局面の
    (best, complete) か None（未解析＝その局面へ打った手の points_lost が None になる）。"""
    nodes = [GameNode(properties={"SZ": 13})]
    for player, gtp in moves:
        nodes.append(GameNode(parent=nodes[-1], move=Move.from_gtp(gtp, player=player)))
    for node, a in zip(nodes, analyses):
        if a is not None:
            _analyze(node, *a)
    return nodes


def _report_counts(last):
    """本物の game_report から (一致数, 分母) を色ごとに取り出す。"""
    game = types.SimpleNamespace(current_node=last, board_size=(13, 13))
    stats, _histogram, ptloss = game_report(game, THRESHOLDS)
    out = {}
    for bw in "BW":
        n = len(ptloss[bw])
        out[bw] = (round(stats[bw]["ai_top_move"] * n) if n else 0, n)
    return out


class TestTally:
    def test_matches_game_report_with_pass_incomplete_parent_and_unanalyzed_node(self):
        moves = [("B", "D4"), ("W", "K10"), ("B", "C3"), ("W", "L11"), ("B", "pass"), ("W", "D10")]
        analyses = [("D4", True), ("K10", True), ("C4", True), ("L11", False), ("pass", True), ("D10", True), None]
        nodes = _tree(moves, analyses)
        # 黒: D4 一致・C3 不一致・pass 一致 → 2/3。白: K10 一致・L11 は親が未完了（分母だけ）・
        # D10 は打った後の局面が未解析（points_lost None＝数えない）→ 1/2
        assert veil_tally(nodes[-1].nodes_from_root, "B") == (2, 3, 1, 2)
        report = _report_counts(nodes[-1])
        assert report == {"B": (2, 3), "W": (1, 2)}

    def test_white_ai_opponent_has_one_more_move_and_is_not_truncated(self):
        moves = [("B", "D4"), ("W", "K10"), ("B", "C3"), ("W", "L11"), ("B", "E5")]
        analyses = [("D4", True), ("K10", True), ("C3", True), ("A1", True), ("E5", True), ("A1", True)]
        nodes = _tree(moves, analyses)
        mine, n_mine, opp, n_opp = veil_tally(nodes[-1].nodes_from_root, "W")
        assert (mine, n_mine, opp, n_opp) == (1, 2, 3, 3)
        report = _report_counts(nodes[-1])
        assert (mine, n_mine) == report["W"] and (opp, n_opp) == report["B"]

    def test_random_trees_match_game_report_exactly(self):
        rng = random.Random(20260923)
        gtps = ["D4", "K10", "C3", "L11", "E5", "pass", "A1", "B2"]
        for _ in range(40):
            length = rng.randint(1, 30)
            moves = [("B" if i % 2 == 0 else "W", rng.choice(gtps)) for i in range(length)]
            analyses = []
            for i in range(length + 1):
                if rng.random() < 0.15:
                    analyses.append(None)
                else:
                    best = moves[i][1] if i < length and rng.random() < 0.5 else rng.choice(gtps)
                    analyses.append((best, rng.random() < 0.85))
            nodes = _tree(moves, analyses)
            report = _report_counts(nodes[-1])
            for ai in "BW":
                opp = "W" if ai == "B" else "B"
                assert veil_tally(nodes[-1].nodes_from_root, ai) == (*report[ai], *report[opp])

    def test_root_only_is_empty(self):
        root = GameNode(properties={"SZ": 13})
        assert veil_tally(root.nodes_from_root, "B") == (0, 0, 0, 0)


class TestUrgency:
    def test_empty_history_is_fully_urgent(self):
        assert veil_urgency(0, 0, 0.30) == (1.0, 1.0)

    @pytest.mark.parametrize(
        "mine,n,expected_p,expected_u",
        [
            (3, 9, 0.40, 1.0),  # 目標を 10pt 超過 → 全開
            (6, 19, 0.35, 0.5),  # 5pt 超過 → 半分
            (2, 9, 0.30, 0.0),  # ちょうど目標 → 閉
            (4, 19, 0.25, 0.0),  # 目標未満 → 閉
        ],
    )
    def test_linear_ramp_over_ten_points(self, mine, n, expected_p, expected_u):
        p_match, u = veil_urgency(mine, n, 0.30)
        assert p_match == pytest.approx(expected_p)
        assert u == pytest.approx(expected_u)

    def test_at_or_below_the_floor_is_closed_even_for_a_lower_target(self):
        assert veil_urgency(2, 19, 0.10)[1] == 0.0  # p_match = 0.15（床ちょうど）
        assert veil_urgency(3, 19, 0.10)[1] == pytest.approx(1.0)  # p_match = 0.20


class TestFreeLimit:
    def test_normal_position_uses_free_loss(self):
        assert veil_free_limit(0.3, 0.5, 0.40) == 0.3
        assert veil_free_limit(0.3, -1.0, 0.40) == 0.3  # ちょうど −1 はまだ劣勢でない

    def test_behind_or_low_rate_is_strict(self):
        assert veil_free_limit(0.3, -1.5, 0.40) == pytest.approx(0.1)
        assert veil_free_limit(0.3, 5.0, 0.15) == pytest.approx(0.1)

    def test_strict_never_raises_a_smaller_free_loss(self):
        assert veil_free_limit(0.0, -3.0, 0.10) == 0.0


class TestAllowance:
    """spec §6 の目安（13路・reserve 5・spend_rate 0.5・F_eff 0.3・u = 1）。"""

    @pytest.mark.parametrize("lead,expected", [(5.0, 0.0), (7.0, 1.0), (10.0, 2.5), (14.0, 4.5), (20.0, 4.5)])
    def test_before_yose_cap_4_5(self, lead, expected):
        a_t, surplus = veil_allowance(lead, 5.0, 0.5, 0.3, 4.5, 1.0)
        assert a_t == pytest.approx(expected)
        assert surplus == pytest.approx(lead - 5.0)

    @pytest.mark.parametrize("lead,expected", [(5.0, 0.0), (6.5, 0.75), (8.0, 1.5), (12.0, 1.5)])
    def test_in_yose_cap_1_5(self, lead, expected):
        assert veil_allowance(lead, 5.0, 0.5, 0.3, 1.5, 1.0)[0] == pytest.approx(expected)

    def test_closed_gate_pays_nothing(self):
        assert veil_allowance(20.0, 5.0, 0.5, 0.3, 4.5, 0.0) == (0.0, 15.0)

    def test_partial_urgency_interpolates_from_free(self):
        assert veil_allowance(10.0, 5.0, 0.5, 0.3, 4.5, 0.5)[0] == pytest.approx(0.3 + 0.5 * (2.5 - 0.3))

    def test_small_surplus_gives_the_smaller_of_free_and_surplus(self):
        assert veil_allowance(5.2, 5.0, 0.5, 0.3, 4.5, 1.0)[0] == pytest.approx(0.2)

    @pytest.mark.parametrize("u", [0.25, 0.5, 1.0])
    def test_cap_below_free_does_not_shrink_with_urgency(self, u):
        assert veil_allowance(8.0, 5.0, 0.5, 0.3, 0.0, u)[0] == pytest.approx(0.3)

    def test_never_exceeds_the_surplus(self):
        for lead in [5.05, 5.1, 5.3, 6.0, 9.0, 15.0, 40.0]:
            for u in [0.1, 0.5, 1.0]:
                a_t, surplus = veil_allowance(lead, 5.0, 1.0, 0.3, 6.0, u)
                assert a_t <= surplus + 1e-12


def cand(gtp, loss, visits=100):
    return {"gtp": gtp, "loss": loss, "visits": visits, "wr": 0.5}


def hp_table(values):
    return lambda gtp: values.get(gtp, 0.0)


class TestNaturalFloor:
    def test_relative_floor_applies_when_not_dominant(self):
        assert veil_natural_floor(0.40, 0.05, 0.2, dominant=False) == pytest.approx(0.08)
        assert veil_natural_floor(0.10, 0.05, 0.2, dominant=False) == pytest.approx(0.05)

    def test_dominant_uses_only_the_absolute_floor(self):
        assert veil_natural_floor(0.90, 0.05, 0.2, dominant=True) == pytest.approx(0.05)


class TestPrefilter:
    def test_keeps_moves_within_the_raw_cap_and_drops_pass(self):
        pool0 = [cand("D4", 0.2), cand("K10", 0.61), cand("pass", 0.0), cand("C3", 0.6)]
        assert [c["gtp"] for c in veil_prefilter(pool0, 0.6)] == ["D4", "C3"]


class TestShortlist:
    def test_hp_top_then_cheapest_of_the_rest_within_the_band(self):
        naturals = [cand("A", 0.9), cand("B", 0.1), cand("C", 0.5), cand("D", 0.3), cand("E", 0.2), cand("F", 2.0)]
        hp = hp_table({"A": 0.30, "B": 0.10, "C": 0.25, "D": 0.20, "E": 0.09, "F": 0.50})
        nat, traps = veil_shortlist(naturals, [], hp, 1.0, 3, 2, 0)
        # F は帯（1.0）の外。hp 上位 A/C/D → 残り B(0.1)・E(0.2) を安い順
        assert [c["gtp"] for c in nat] == ["A", "C", "D", "B", "E"]
        assert traps == []

    def test_cheap_slots_can_be_zero(self):
        naturals = [cand("A", 0.2), cand("B", 0.1)]
        nat, _ = veil_shortlist(naturals, [], hp_table({"A": 0.3, "B": 0.2}), 1.0, 1, 0, 0)
        assert [c["gtp"] for c in nat] == ["A"]

    def test_trap_slots_are_spread_over_the_rest_and_never_change_the_natural_slots(self):
        naturals = [cand("A", 0.2), cand("B", 0.4)]
        trap_cands = [
            cand("A", 0.2),
            cand("T1", 0.5),
            cand("T2", 1.0),
            cand("T3", 1.5),
            cand("T4", 2.0),
            cand("T5", 2.5),
        ]
        hp = hp_table({"A": 0.3, "B": 0.2, "T1": 0.03, "T2": 0.03, "T3": 0.03, "T4": 0.03, "T5": 0.03})
        nat_off, traps_off = veil_shortlist(naturals, trap_cands, hp, 1.0, 3, 2, 0)
        nat_on, traps_on = veil_shortlist(naturals, trap_cands, hp, 1.0, 3, 2, 3)
        assert [c["gtp"] for c in nat_on] == [c["gtp"] for c in nat_off] == ["A", "B"]
        assert traps_off == []
        # 自然枠に入った A は罠枠に出ない。残り5手から loss の範囲に等間隔（両端込み）
        assert [c["gtp"] for c in traps_on] == ["T1", "T3", "T5"]


def ctx(**kw):
    """13路の既定に近い判定コンテキスト（lead 12・u 1・A_t' 3.5・ヨセ前・接戦でない）。"""
    base = dict(
        lead=12.0,
        reserve=5.0,
        surplus=7.0,
        urgency=1.0,
        p_match=0.5,
        f_eff=0.3,
        allowance=3.5,
        trap_cap=4.5,
        min_winrate=0.85,
        free_wr_drop=0.03,
        in_yose=False,
        close=False,
        close_drift=0.0,
        close_drift_cap=0.0,
        trap_min_delta_e=0.5,
    )
    base.update(kw)
    return VeilCtx(**base)


def row(cons, vloss=None, wr_drop=0.01, wr_after=0.93, lead_after=11.0):
    vloss = cons if vloss is None else vloss
    return {"cons": cons, "vloss": vloss, "wr_drop": wr_drop, "wr_after": wr_after, "lead_after": lead_after}


class TestConsLoss:
    def test_trusted_candidate_also_counts_the_raw_loss(self):
        assert veil_cons_loss(0.1, 0.25, visits=200, trusted=50) == 0.25
        assert veil_cons_loss(0.4, 0.25, visits=200, trusted=50) == 0.4

    def test_shallow_candidate_uses_only_the_verified_loss(self):
        assert veil_cons_loss(0.1, 0.9, visits=12, trusted=50) == 0.1


class TestNearFree:
    def test_cheap_with_small_winrate_drop_is_free(self):
        assert veil_near_free_ok(0.3, 0.03, 0.60, 0.2, ctx())

    def test_too_expensive_or_too_large_a_drop_is_not(self):
        assert not veil_near_free_ok(0.31, 0.0, 0.60, 0.2, ctx())
        assert not veil_near_free_ok(0.1, 0.05, 0.60, 0.2, ctx())

    def test_decided_winrate_waives_the_drop(self):
        assert veil_near_free_ok(0.1, 0.05, 0.975, 20.0, ctx())

    def test_missing_winrate_is_not_free(self):
        assert not veil_near_free_ok(0.1, None, None, 0.2, ctx())

    def test_yose_guard_below_reserve_needs_a_one_percent_drop(self):
        yose = ctx(in_yose=True)
        assert not veil_near_free_ok(0.1, 0.02, 0.88, 4.9, yose)
        assert veil_near_free_ok(0.1, 0.01, 0.88, 4.9, yose)
        assert veil_near_free_ok(0.1, 0.02, 0.88, 5.0, yose)  # reserve を保つなら通常の条件


class TestPaid:
    def test_within_allowance_reserve_and_winrate_floor(self):
        assert veil_paid_ok(3.5, 0.85, ctx())

    def test_rejections(self):
        assert not veil_paid_ok(3.6, 0.95, ctx())  # A_t' 超
        assert not veil_paid_ok(1.0, 0.84, ctx())  # 勝率フロア
        assert not veil_paid_ok(1.0, None, ctx())
        assert not veil_paid_ok(1.0, 0.95, ctx(urgency=0.0))  # ゲート閉
        assert not veil_paid_ok(0.2, 0.95, ctx(lead=5.0, surplus=0.0, allowance=0.0))  # 余剰なし
        assert not veil_paid_ok(2.0, 0.95, ctx(lead=6.0, surplus=1.0, allowance=3.0))  # reserve を割る


class TestCloseDrift:
    def test_off_or_not_close_is_unlimited(self):
        assert veil_close_drift_ok(True, 5.0, 1.0, 0.0)
        assert veil_close_drift_ok(False, 5.0, 1.0, 1.0)

    def test_cap_counts_only_positive_losses(self):
        assert veil_close_drift_ok(True, 0.9, 0.1, 1.0)
        assert not veil_close_drift_ok(True, 0.95, 0.1, 1.0)
        assert veil_close_drift_ok(True, 1.0, -0.2, 1.0)


class TestClassify:
    def test_free_beats_paid_and_cost_is_clamped_at_zero(self):
        assert veil_classify(row(-0.2), ctx()) == ("free", 0.0)
        assert veil_classify(row(0.25), ctx()) == ("free", 0.25)

    def test_paid_when_not_free_but_within_budget(self):
        assert veil_classify(row(1.5), ctx()) == ("paid", 1.5)

    def test_free_is_independent_of_the_gate(self):
        closed = ctx(urgency=0.0, allowance=0.0, lead=0.5, surplus=-4.5, close=True)
        assert veil_classify(row(0.2, wr_after=0.55, lead_after=0.4), closed) == ("free", 0.2)
        assert veil_classify(row(1.0, wr_after=0.55, lead_after=0.4), closed) == (None, 1.0)

    def test_close_drift_cap_turns_free_into_paid_or_nothing(self):
        capped = ctx(close=True, close_drift=0.25, close_drift_cap=0.3)
        assert veil_classify(row(0.1), capped) == ("paid", 0.1)
        closed = ctx(close=True, close_drift=0.25, close_drift_cap=0.3, urgency=0.0, allowance=0.0)
        assert veil_classify(row(0.1), closed) == (None, 0.1)


def pick(gtp, cost, hp, wr_after=0.9, kind="free"):
    return {"gtp": gtp, "kind": kind, "cost": cost, "hp": hp, "wr_after": wr_after}


class TestChoose:
    def test_none_without_a_qualifying_move(self):
        assert veil_choose([], 0.3, prefer_safe=False) is None
        assert veil_choose([pick("D4", 0.1, 0.3, kind=None)], 0.3, prefer_safe=False) is None

    def test_most_human_move_inside_the_cheapest_band(self):
        scored = [pick("A", 0.0, 0.10), pick("B", 0.3, 0.40), pick("C", 0.31, 0.90, kind="paid")]
        assert veil_choose(scored, 0.3, prefer_safe=False)["gtp"] == "B"  # C は帯（0.0〜0.3）の外

    def test_zero_slack_is_the_cheapest(self):
        scored = [pick("A", 0.2, 0.10), pick("B", 0.1, 0.05)]
        assert veil_choose(scored, 0.0, prefer_safe=False)["gtp"] == "B"

    def test_exact_hp_tie_breaks_on_cost_then_gtp(self):
        scored = [pick("K10", 0.2, 0.3), pick("D4", 0.2, 0.3), pick("C3", 0.1, 0.3)]
        assert veil_choose(scored, 0.3, prefer_safe=False)["gtp"] == "C3"
        scored = [pick("K10", 0.2, 0.3), pick("D4", 0.2, 0.3)]
        assert veil_choose(scored, 0.3, prefer_safe=False)["gtp"] == "D4"

    def test_with_surplus_near_tied_hp_prefers_the_safer_move(self):
        scored = [pick("A", 0.1, 0.30, wr_after=0.90), pick("B", 0.2, 0.29, wr_after=0.95), pick("C", 0.0, 0.20)]
        assert veil_choose(scored, 0.3, prefer_safe=True)["gtp"] == "B"
        assert veil_choose(scored, 0.3, prefer_safe=False)["gtp"] == "A"

    def test_with_surplus_a_clearly_more_human_move_still_wins(self):
        scored = [pick("A", 0.1, 0.30, wr_after=0.90), pick("B", 0.2, 0.27, wr_after=0.99)]
        assert veil_choose(scored, 0.3, prefer_safe=True)["gtp"] == "A"


def trap(vloss=1.0, d_e=2.0, find=0.1, hp=0.03, wr_after=0.93, gtp="T"):
    return {"gtp": gtp, "vloss": vloss, "d_e": d_e, "find": find, "hp": hp, "wr_after": wr_after}


class TestTrap:
    def test_price_discounts_half_of_delta_e_and_clamps_the_loss(self):
        assert veil_trap_price(1.0, 2.0) == pytest.approx(0.0)
        assert veil_trap_price(-0.4, 1.0) == pytest.approx(-0.5)

    def test_open_gate_accepts_within_the_allowance(self):
        assert veil_trap_ok(trap(vloss=3.0, d_e=1.0), ctx()) == (True, pytest.approx(2.5))
        assert veil_trap_ok(trap(vloss=4.2, d_e=1.0), ctx())[0] is False  # price 3.7 > A_t' 3.5

    def test_qualification(self):
        assert veil_trap_ok(trap(d_e=0.4), ctx())[0] is False  # ΔE 不足
        assert veil_trap_ok(trap(find=0.3), ctx())[0] is False  # 正しい応手が本の手
        assert veil_trap_ok(trap(hp=0.019), ctx())[0] is False  # NN の床に張り付いた手
        assert veil_trap_ok(trap(d_e=None), ctx()) == (False, None)

    def test_safety_is_judged_on_the_raw_verified_loss(self):
        # 値段は負でも、vloss が罠の上限（ヨセなら yose_max_loss）を超えたら不可
        assert veil_trap_ok(trap(vloss=1.6, d_e=6.0), ctx(trap_cap=1.5))[0] is False
        assert veil_trap_ok(trap(vloss=1.5, d_e=6.0), ctx(trap_cap=1.5))[0] is True
        assert veil_trap_ok(trap(vloss=2.0, d_e=6.0), ctx(lead=6.5, surplus=1.5))[0] is False  # reserve を割る
        assert veil_trap_ok(trap(wr_after=0.80), ctx())[0] is False

    def test_closed_gate_needs_a_non_positive_price_within_free_and_a_rate_above_the_floor(self):
        closed = ctx(urgency=0.0, allowance=0.0)
        assert veil_trap_ok(trap(vloss=0.3, d_e=0.6), closed) == (True, pytest.approx(0.0))
        assert veil_trap_ok(trap(vloss=0.3, d_e=0.5), closed)[0] is False  # price 0.05 > 0
        assert veil_trap_ok(trap(vloss=0.4, d_e=2.0), closed)[0] is False  # vloss > F_eff
        assert veil_trap_ok(trap(vloss=0.3, d_e=0.6), ctx(urgency=0.0, allowance=0.0, p_match=0.15))[0] is False

    def test_merge_keeps_the_plain_move_unless_the_trap_is_clearly_cheaper(self):
        plain = {"gtp": "D4", "kind": "free", "cost": 0.2}
        dear = {"gtp": "C3", "kind": "trap", "price": -0.05, "hp": 0.03}
        cheap = {"gtp": "F2", "kind": "trap", "price": -0.1, "hp": 0.03}
        assert veil_merge_trap(plain, [dear])["gtp"] == "D4"
        assert veil_merge_trap(plain, [dear, cheap])["gtp"] == "F2"
        assert veil_merge_trap(plain, [])["gtp"] == "D4"
        assert veil_merge_trap(None, [dear, cheap])["gtp"] == "F2"
        assert veil_merge_trap(None, []) is None

    def test_merge_breaks_price_ties_on_hp_then_gtp(self):
        a = {"gtp": "B2", "kind": "trap", "price": -1.0, "hp": 0.03}
        b = {"gtp": "A1", "kind": "trap", "price": -1.0, "hp": 0.05}
        c = {"gtp": "A2", "kind": "trap", "price": -1.0, "hp": 0.05}
        assert veil_merge_trap(None, [a, b, c])["gtp"] == "A1"


class TestTerminalSwap:
    CANDS = [cand("E5", 0.0, 900), cand("D4", 0.04, 50), cand("C3", 0.08, 40), cand("F6", 0.2, 30), cand("G7", 0.0, 5)]
    CANDS.append(cand("pass", 0.1, 60))
    HP = staticmethod(hp_table({"D4": 0.10, "C3": 0.30, "F6": 0.60, "G7": 0.70, "pass": 0.9}))

    def test_limit_depends_on_the_lead(self):
        assert veil_terminal_limit(2.9) == pytest.approx(0.05)
        assert veil_terminal_limit(-2.9) == pytest.approx(0.05)
        assert veil_terminal_limit(3.0) == pytest.approx(0.10)

    def test_close_drift_cap_applies_only_when_set_and_the_game_is_close(self):
        assert veil_terminal_capped(2.9, 0.1) and veil_terminal_capped(-2.9, 0.1)
        assert not veil_terminal_capped(3.0, 0.1) and not veil_terminal_capped(-3.0, 0.1)
        assert not veil_terminal_capped(1.0, 0.0)  # 上限 0 は「上限なし」

    def test_clear_lead_allows_up_to_0_10_and_picks_the_most_human(self):
        swap = veil_terminal_swap(self.CANDS, "E5", self.HP, 0.05, lead=10.0, dominant=False, urgency=0.0)
        assert swap["gtp"] == "C3" and swap["hp"] == pytest.approx(0.30)  # F6 は 0.2 目・G7 は visits 5・pass は除外

    def test_close_game_allows_only_0_05(self):
        swap = veil_terminal_swap(self.CANDS, "E5", self.HP, 0.05, lead=1.0, dominant=False, urgency=0.0)
        assert swap["gtp"] == "D4"

    def test_natural_floor_applies(self):
        assert veil_terminal_swap(self.CANDS, "E5", self.HP, 0.2, lead=1.0, dominant=False, urgency=1.0) is None

    def test_dominant_needs_an_open_gate(self):
        assert veil_terminal_swap(self.CANDS, "E5", self.HP, 0.05, lead=10.0, dominant=True, urgency=0.0) is None
        assert veil_terminal_swap(self.CANDS, "E5", self.HP, 0.05, lead=10.0, dominant=True, urgency=0.5) is not None

    def test_close_drift_cap_in_close_games(self):
        args = (self.CANDS, "E5", self.HP, 0.05)
        assert veil_terminal_swap(*args, lead=1.0, dominant=False, urgency=0.0, close_drift=0.96, close_drift_cap=1.0)
        blocked = veil_terminal_swap(
            *args, lead=1.0, dominant=False, urgency=0.0, close_drift=0.97, close_drift_cap=1.0
        )
        assert blocked is None
        free = veil_terminal_swap(*args, lead=10.0, dominant=False, urgency=0.0, close_drift=5.0, close_drift_cap=1.0)
        assert free["gtp"] == "C3"  # |lead| >= 3 では累計を見ない


class TestInvariant:
    GTPS = {"E5", "D4", "C3", "pass"}

    def test_common_rules(self):
        free = {"cost": 0.1, "f_eff": 0.3}
        assert veil_invariant_ok("D4", "E5", self.GTPS, "free", free)
        assert not veil_invariant_ok("E5", "E5", self.GTPS, "free", free)  # 最善手
        assert not veil_invariant_ok("pass", "E5", self.GTPS, "free", free)
        assert not veil_invariant_ok("Q16", "E5", self.GTPS, "free", free)  # 候補に無い
        assert not veil_invariant_ok(None, "E5", self.GTPS, "free", free)

    def test_bounds_per_kind(self):
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "decided", {"cost": 0.31, "f_eff": 0.3})
        paid = {"cost": 2.0, "allowance": 2.0, "lead": 7.0, "reserve": 5.0}
        assert veil_invariant_ok("D4", "E5", self.GTPS, "paid", paid)
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "paid", {**paid, "allowance": 1.9})
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "paid", {**paid, "lead": 6.9})
        trap_b = {"price": -0.5, "allow": 0.0, "vloss": 1.5, "trap_cap": 1.5, "lead": 8.0, "reserve": 5.0}
        assert veil_invariant_ok("C3", "E5", self.GTPS, "trap", trap_b)
        assert not veil_invariant_ok("C3", "E5", self.GTPS, "trap", {**trap_b, "vloss": 1.6})
        assert not veil_invariant_ok("C3", "E5", self.GTPS, "trap", {**trap_b, "price": 0.1})
        assert veil_invariant_ok("D4", "E5", self.GTPS, "terminal", {"raw": 0.05, "limit": 0.05})
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "terminal", {"raw": 0.06, "limit": 0.05})

    def test_unknown_kind_or_missing_bounds_fail(self):
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "mystery", {"cost": 0.0, "f_eff": 1.0})
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "paid", {"cost": 0.1})


class TestDecisionRecord:
    def test_json_is_ascii_sorted_and_rounded(self):
        text = veil_decision_record(
            tier="iii", kind="free", vloss=0.123456, lead=float("nan"), ledger=(1, "D4"), ok=True
        )
        assert text == '{"kind": "free", "lead": null, "ledger": [1, "D4"], "ok": true, "tier": "iii", "vloss": 0.123}'
        assert text.isascii()
        assert json.loads(text)["vloss"] == 0.123


# spec §6.1 の既定値（凍結）。通しテストはこの値を明示の設定として渡す＝校正で既定値を変えてもテストの前提は動かない
SPEC_DEFAULTS = {
    9: {
        "target_rate": 0.40,
        "reserve": 3.0,
        "min_winrate": 0.85,
        "free_loss": 0.2,
        "free_wr_drop": 0.03,
        "close_drift_cap": 0.0,
        "spend_rate": 0.5,
        "max_loss": 3.0,
        "yose_max_loss": 1.0,
        "dominant_hp": 0.8,
        "dominant_max_loss": 1.5,
        "min_human_policy": 0.05,
        "natural_ratio": 0.2,
        "cost_slack": 0.3,
        "trap_mode": False,
        "trap_min_delta_e": 0.5,
    },
    13: {
        "target_rate": 0.30,
        "reserve": 5.0,
        "min_winrate": 0.85,
        "free_loss": 0.3,
        "free_wr_drop": 0.03,
        "close_drift_cap": 0.0,
        "spend_rate": 0.5,
        "max_loss": 4.5,
        "yose_max_loss": 1.5,
        "dominant_hp": 0.8,
        "dominant_max_loss": 2.0,
        "min_human_policy": 0.05,
        "natural_ratio": 0.2,
        "cost_slack": 0.3,
        "trap_mode": False,
        "trap_min_delta_e": 0.5,
    },
    19: {
        "target_rate": 0.30,
        "reserve": 7.0,
        "min_winrate": 0.85,
        "free_loss": 0.3,
        "free_wr_drop": 0.03,
        "close_drift_cap": 0.0,
        "spend_rate": 0.5,
        "max_loss": 6.0,
        "yose_max_loss": 2.0,
        "dominant_hp": 0.8,
        "dominant_max_loss": 3.0,
        "min_human_policy": 0.05,
        "natural_ratio": 0.2,
        "cost_slack": 0.3,
        "trap_mode": False,
        "trap_min_delta_e": 0.7,
    },
}
# 校正（Task 17）で選んだ既定値の差分。apply_veil_defaults.py が書き換える（空なら spec のまま）
CALIBRATED_DEFAULTS = {9: {}, 13: {}, 19: {}}
# コードとパッケージ config の既定値＝spec ＋ 校正の差分
EXPECTED_DEFAULTS = {size: {**SPEC_DEFAULTS[size], **CALIBRATED_DEFAULTS[size]} for size in SPEC_DEFAULTS}
# 勝ちの安全条件（要件1）。変えてよいのはユーザーが要件1を再決定したときだけ（apply_veil_defaults.py --safety-redecided）
SAFETY_DEFAULTS = {
    9: {"reserve": 3.0, "min_winrate": 0.85},
    13: {"reserve": 5.0, "min_winrate": 0.85},
    19: {"reserve": 7.0, "min_winrate": 0.85},
}


# ===== _generate_move の通しテスト（Veil9Strategy・9路・KataGo なし）=====


def _hp_array(size, values):
    """{gtp: hp} → KataGo の humanPolicy フラット配列（末尾 pass）"""
    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        if gtp == "pass":
            arr[-1] = v
            continue
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def _child(lead, wr, punish=0.0, size=9):
    """黒番の AI が候補を打った後の子局面プローブ（scoreLead / winrate は黒視点）。

    白の応手は A9（人間の本命）と J1。punish > 0 なら本命 A9 が punish 目損する罠の形
    （hp A9 0.9 / J1 0.1 → E = 0.9 × punish、正解 J1 の hp 0.1＝find_hp）。punish 0 なら E = 0。
    """
    replies = [("A9", lead + punish, 300), ("J1", lead, 200)]
    reply_hp = {"A9": 0.9, "J1": 0.1} if punish > 0 else {"A9": 0.5, "J1": 0.5}
    clean = {
        "rootInfo": {"scoreLead": lead, "winrate": wr},
        "moveInfos": [{"move": g, "scoreLead": s, "visits": v} for g, s, v in replies],
    }
    return {"clean": clean, "hp": {"humanPolicy": _hp_array(size, reply_hp)}}


def _hist(ai_player, mine, n_mine, opp=0, n_opp=0):
    """一致率の履歴（veil_tally / parity9_match_tally が読む属性だけの疑似ノード列・root 込み）。"""
    nodes = [types.SimpleNamespace(move=None, is_root=True, parent=None, player="W")]
    opp_player = "W" if ai_player == "B" else "B"
    for player, matched, total in ((ai_player, mine, n_mine), (opp_player, opp, n_opp)):
        for i in range(total):
            parent = types.SimpleNamespace(
                analysis_complete=True, candidate_moves=[{"move": "A1" if i < matched else "B2"}]
            )
            move = Move.from_gtp("A1", player=player)
            nodes.append(types.SimpleNamespace(move=move, is_root=False, parent=parent, player=player, points_lost=0.0))
    return nodes


class _Harness:
    """_generate_move の通しテスト用スタブ（エンジンなし）。黒番・最善手 E5。
    名前が Test で始まらないので pytest には収集されない（継承した側だけが走る）。"""

    CLS = Veil9Strategy
    SIZE = 9
    CANDS = [
        {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.62},
        {"move": "D4", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 300, "winrate": 0.61},
        {"move": "F6", "pointsLost": 0.8, "relativePointsLost": 0.8, "visits": 150, "winrate": 0.58},
        {"move": "C7", "pointsLost": 2.0, "relativePointsLost": 2.0, "visits": 60, "winrate": 0.50},
        {"move": "G3", "pointsLost": 3.8, "relativePointsLost": 3.8, "visits": 40, "winrate": 0.45},
        {"move": "A1", "pointsLost": 9.0, "relativePointsLost": 9.0, "visits": 3, "winrate": 0.20},
    ]
    # 床 = max(0.05, 0.2 × 0.40) = 0.08 → 自然な候補は D4 / F6、C7 / G3 は罠の資格（hp >= 0.02）だけ
    HP = {"E5": 0.40, "D4": 0.30, "F6": 0.15, "C7": 0.03, "G3": 0.04}

    def _strategy(
        self,
        *,
        lead=10.0,
        wr=0.95,
        depth=12,
        cands=None,
        hp=None,
        hp_ok=True,
        probes=None,
        settings=None,
        hist=None,
        last_move=None,
        ownership=None,
        size=None,
        **game_attrs,
    ):
        size = size or self.SIZE
        logs = []
        katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
        node = types.SimpleNamespace(
            next_player="B",
            player="W",
            depth=depth,
            move=last_move,
            is_root=False,
            analysis_complete=True,
            analysis={"root": {"scoreLead": lead, "winrate": wr}},
            candidate_moves=[dict(c) for c in (self.CANDS if cands is None else cands)],
            nodes_from_root=[] if hist is None else hist,
            policy_ranking=[],
        )
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(size, size), **game_attrs)
        spec = {f"{self.CLS.KEY_PREFIX}_{k}": v for k, v in SPEC_DEFAULTS[self.CLS.BOARD_LEN].items()}
        s = self.CLS(game, {**spec, **(settings or {})})
        s.queries, s.probe_calls, s.ponders = [], [], []
        hp_values = self.HP if hp is None else hp

        def run_query(label, **kw):
            s.queries.append(label)
            if label == "parent hp":
                return {"humanPolicy": _hp_array(size, hp_values)} if hp_ok else None
            return None if ownership is None else {"ownership": ownership, "rootInfo": {"scoreLead": lead}}

        def probe_children(gtps, player, parent_hp=False):
            s.probe_calls.append(list(gtps))
            return {g: (probes or {}).get(g) for g in gtps}, None

        s._run_query = run_query
        s._probe_children = probe_children
        s._start_ponder = lambda *a, **k: s.ponders.append(a)
        return s, logs


EVEN = dict(lead=0.5, wr=0.55)  # 互角・目標ちょうど（9路 T 0.40 → u = 0）の手番に _hist("B", 3, 9) と組む


class TestStrategyClass:
    def test_registered_as_a_9x9_enigma_subclass(self):
        assert AI_VEIL_9 == "ai:veil9"
        assert STRATEGY_REGISTRY[AI_VEIL_9] is Veil9Strategy
        assert issubclass(Veil9Strategy, Enigma9Strategy)
        assert (Veil9Strategy.BOARD_LEN, Veil9Strategy.KEY_PREFIX, Veil9Strategy.LABEL) == (9, "veil9", "Veil9")

    def test_defaults_match_the_spec(self):
        assert Veil9Strategy.SETTING_DEFAULTS == EXPECTED_DEFAULTS[9]
        assert Veil9Strategy.VEIL_BOARD == {
            "endgame_move": 30,
            "unsettled_max": 8,
            "trusted_visits": 100,
            "probe_hp": 3,
            "probe_cheap": 2,
        }

    def test_only_the_flow_is_overridden(self):
        assert Veil9Strategy.generate_move is Enigma9Strategy.generate_move  # 時間ログのラッパーは共有
        assert Veil9Strategy._generate_move is not Enigma9Strategy._generate_move
        assert Veil9Strategy._terminal_band_move is Enigma9Strategy._terminal_band_move


class TestTiers(_Harness):
    def test_tier_i_only_the_best_move_needs_no_query(self):
        s, logs = self._strategy(cands=[self.CANDS[0], self.CANDS[-1]])
        move, _ = s.generate_move()
        assert move.gtp() == "E5"
        assert s.queries == [] and s.probe_calls == []
        assert s.last_decision_info["tier"] == "i"

    def test_tier_ii_closed_at_target_costs_one_query(self):
        s, logs = self._strategy(**EVEN, hist=_hist("B", 3, 9), hp={**self.HP, "E5": 0.85})
        move, _ = s.generate_move()
        assert move.gtp() == "E5"
        assert s.queries == ["parent hp"] and s.probe_calls == []
        assert (s.last_decision_info["tier"], s.last_decision_info["why"]) == ("ii", "dominant_closed")


class TestFailSafes(_Harness):
    def test_wrong_board_size(self):
        s, logs = self._strategy(size=13)
        assert s.generate_move()[0].gtp() == "E5"
        assert s.queries == [] and any("is not 9x9" in m for m in logs)

    def test_no_candidates(self):
        s, _ = self._strategy(cands=[])
        assert s.generate_move()[0].is_pass
        assert s.last_decision_info["why"] == "no_cands"

    def test_no_lead(self):
        s, _ = self._strategy(lead=None)
        assert s.generate_move()[0].gtp() == "E5" and s.queries == []

    def test_humansl_failure(self):
        s, _ = self._strategy(hp_ok=False)
        assert s.generate_move()[0].gtp() == "E5" and s.queries == ["parent hp"] and s.probe_calls == []

    def test_unexpected_exception_plays_the_best_move(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(ai_module, "veil_allowance", boom)
        s, _ = self._strategy()
        records = []
        s.game.katrain.log = lambda msg, level=None, *a, **k: records.append((str(msg), level))
        assert s.generate_move()[0].gtp() == "E5"
        assert any(lv == OUTPUT_ERROR and "error RuntimeError: boom -> best move" in m for m, lv in records)
        # ほかの出口と同じ最小の記録: last_decision_info・`Decision:` 行 1 行・ledger 1 件
        expected = ("failsafe", "best", "exception", "E5", "E5")
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["why"], info["best"], info["chosen"]) == expected
        decisions = [m for m, _lv in records if m.startswith("[Veil9Strategy] Decision: {")]
        assert len(decisions) == 1
        record = json.loads(decisions[0].split("Decision: ", 1)[1])
        assert (record["tier"], record["kind"], record["why"], record["best"], record["chosen"]) == expected
        assert (record["depth"], record["error"]) == (12, "RuntimeError('boom')")
        assert s.game._veil_state["veil9"]["ledger"] == [(12, "E5", "E5", "best")]

    def test_an_error_turn_whose_record_fails_still_plays_the_best_move(self):
        # 壊れた sticky 状態（キーが無い）: S6 で KeyError → S0 の記録の ledger でも KeyError → それでも最善手
        s, _ = self._strategy(_veil_state={"veil9": {}})
        records = []
        s.game.katrain.log = lambda msg, level=None, *a, **k: records.append((str(msg), level))
        assert s.generate_move()[0].gtp() == "E5"
        errors = [m for m, lv in records if lv == OUTPUT_ERROR]
        assert len(errors) == 2
        assert "error KeyError" in errors[0] and "could not record the error turn: KeyError" in errors[1]
        assert not any("Decision: " in m for m, _lv in records)

    def test_discarded_analysis_is_not_swallowed(self, monkeypatch):
        def discarded(*a, **k):
            raise AnalysisDiscardedException("new game")

        monkeypatch.setattr(ai_module, "veil_allowance", discarded)
        s, _ = self._strategy()
        with pytest.raises(AnalysisDiscardedException):
            s.generate_move()


class TestTiersDeviating(_Harness):
    """段(ii) 開と決着局面の即決（S13 以降を通る手番）。"""

    def test_tier_ii_open_pays_only_up_to_dominant_max_loss(self):
        hp = {"E5": 0.85, "D4": 0.01, "F6": 0.06, "C7": 0.03, "G3": 0.04}  # 明らかな一手 → 床は 0.05 だけ
        ok, _ = self._strategy(hp=hp, probes={"E5": _child(10.0, 0.95), "F6": _child(8.8, 0.93)})
        move, _ = ok.generate_move()
        assert move.gtp() == "F6"
        assert ok.probe_calls == [["E5", "F6"]]  # C7（生 2.0）は絞った足切り 1.5 + 0.3 の外
        assert (ok.last_decision_info["tier"], ok.last_decision_info["kind"]) == ("ii", "paid")
        dear, _ = self._strategy(hp=hp, probes={"E5": _child(10.0, 0.95), "F6": _child(8.2, 0.93)})
        assert dear.generate_move()[0].gtp() == "E5"  # vloss 1.8 > dominant_max_loss 1.5

    def test_decided_position_deviates_without_probes(self):
        s, logs = self._strategy(lead=7.0, wr=0.98)
        move, _ = s.generate_move()
        assert move.gtp() == "D4"
        assert s.queries == ["parent hp"] and s.probe_calls == []
        assert s.last_decision_info["kind"] == "decided"


class TestFreeAndPaid(_Harness):
    def test_near_free_deviation_even_at_target(self):
        probes = {"E5": _child(0.5, 0.55), "D4": _child(0.45, 0.545)}
        s, logs = self._strategy(**EVEN, hist=_hist("B", 3, 9), probes=probes, board_watch_probe_warm=True)
        move, reason = s.generate_move()
        assert move.gtp() == "D4"
        assert s.probe_calls == [["E5", "D4"]]
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["best"], info["chosen"]) == ("iii", "free", "E5", "D4")
        assert (info["mine"], info["n"], info["u"], info["queries"]) == (3, 9, 0.0, 5)
        assert s.game._veil_state["veil9"]["ledger"] == [(12, "E5", "D4", "free")]
        assert any(m.startswith("[Veil9Strategy] Decision: {") for m in logs)
        assert any(m.startswith("[Veil9Strategy] Rate: mine=3/9") for m in logs)
        assert s.game.board_watch_probe_warm is False
        assert s.ponders == []

    def test_near_free_needs_a_small_winrate_drop(self):
        probes = {"E5": _child(0.5, 0.55), "D4": _child(0.45, 0.50)}
        s, _ = self._strategy(**EVEN, hist=_hist("B", 3, 9), probes=probes)
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["why"] == "none_qualified"

    def test_paid_deviation_from_surplus_when_above_target(self):
        hp = {**self.HP, "D4": 0.01, "F6": 0.30}
        s, _ = self._strategy(hp=hp, probes={"E5": _child(10.0, 0.95), "F6": _child(9.0, 0.93)})
        move, _ = s.generate_move()
        assert move.gtp() == "F6"
        assert s.last_decision_info["kind"] == "paid"
        assert s.last_decision_info["cost"] == pytest.approx(1.0)

    def test_winrate_floor_rejects_a_paid_deviation(self):
        hp = {**self.HP, "D4": 0.01, "F6": 0.30}
        s, _ = self._strategy(hp=hp, probes={"E5": _child(10.0, 0.95), "F6": _child(9.0, 0.80)})
        assert s.generate_move()[0].gtp() == "E5"

    def test_small_surplus_cannot_pay_below_the_reserve(self):
        cands = [dict(c) for c in self.CANDS]
        cands[2]["relativePointsLost"] = 0.3  # F6 を足切りの内側へ
        hp = {**self.HP, "D4": 0.01, "F6": 0.30}
        s, _ = self._strategy(
            lead=3.5, wr=0.9, cands=cands, hp=hp, probes={"E5": _child(3.5, 0.9), "F6": _child(2.5, 0.88)}
        )
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["A_t"] == pytest.approx(0.25)

    def test_the_rate_line_counts_the_opponent_like_the_report(self):
        s, logs = self._strategy(**EVEN, hist=_hist("B", 3, 9, opp=2, n_opp=10), probes={})
        s.generate_move()
        assert (s.last_decision_info["opp"], s.last_decision_info["n_opp"]) == (2, 10)


class TestYoseAndCloseGames(_Harness):
    def test_yose_guard_needs_a_one_percent_drop_below_the_reserve(self):
        strict, _ = self._strategy(
            lead=2.5, wr=0.9, depth=32, probes={"E5": _child(2.5, 0.90), "D4": _child(2.45, 0.88)}
        )
        assert strict.generate_move()[0].gtp() == "E5"
        assert strict.game._veil_state["veil9"]["endgame"] is True  # 手数だけでヨセ（ownership なし）
        ok, _ = self._strategy(lead=2.5, wr=0.9, depth=32, probes={"E5": _child(2.5, 0.90), "D4": _child(2.45, 0.895)})
        assert ok.generate_move()[0].gtp() == "D4"

    def test_yose_is_sticky(self):
        state = {"veil9": {"endgame": True, "close_drift": 0.0, "ledger": []}}
        s, _ = self._strategy(depth=20, probes={}, _veil_state=state)
        s.generate_move()
        assert s.last_decision_info["in_yose"] is True
        assert s.last_decision_info["cap"] == pytest.approx(1.0)  # yose_max_loss

    @pytest.mark.parametrize(
        "cap,drift,expected,drift_after", [(0.0, 0.08, "D4", 0.08), (0.1, 0.08, "E5", 0.08), (0.2, 0.08, "D4", 0.13)]
    )
    def test_close_drift_cap(self, cap, drift, expected, drift_after):
        state = {"veil9": {"endgame": False, "close_drift": drift, "ledger": []}}
        probes = {"E5": _child(0.5, 0.55), "D4": _child(0.45, 0.545)}
        s, _ = self._strategy(
            **EVEN, hist=_hist("B", 3, 9), probes=probes, settings={"veil9_close_drift_cap": cap}, _veil_state=state
        )
        assert s.generate_move()[0].gtp() == expected
        assert state["veil9"]["close_drift"] == pytest.approx(drift_after)


class TestFailSafesDeviating(_Harness):
    """best プローブの欠落と不変条件違反（S15〜S19）。"""

    def test_missing_best_probe(self):
        s, _ = self._strategy(probes={"D4": _child(9.95, 0.948)})
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["why"] == "no_best_probe"

    def test_invariant_violation_plays_the_best_move(self, monkeypatch):
        bogus = {"gtp": "J9", "kind": "free", "cost": 0.0, "vloss": 0.0, "hp": 0.5, "raw": 0.0, "cons": 0.0}
        monkeypatch.setattr(ai_module, "veil_choose", lambda *a, **k: dict(bogus))
        probes = {"E5": _child(0.5, 0.55), "D4": _child(0.45, 0.545)}
        s, logs = self._strategy(**EVEN, hist=_hist("B", 3, 9), probes=probes)
        assert s.generate_move()[0].gtp() == "E5"
        assert any("Invariant violated: chosen=J9" in m for m in logs)
        assert s.last_decision_info["why"] == "invariant"
        assert s.ponders == []


class TestTrapLayer(_Harness):
    PROBES = {"E5": _child(10.0, 0.95), "D4": _child(9.95, 0.948), "F6": _child(9.2, 0.93)}

    def test_trap_mode_only_adds_trap_slots_to_the_probe_batch(self):
        off, _ = self._strategy(probes=self.PROBES)
        on, _ = self._strategy(probes=self.PROBES, settings={"veil9_trap_mode": True})
        assert off.generate_move()[0].gtp() == on.generate_move()[0].gtp() == "D4"
        assert off.queries == on.queries == ["parent hp"]
        assert off.probe_calls == [["E5", "D4", "F6"]]
        assert on.probe_calls == [["E5", "D4", "F6", "C7", "G3"]]

    def test_a_plain_deviation_is_not_lost_to_a_dearer_trap(self):
        probes = {**self.PROBES, "C7": _child(8.4, 0.90, punish=3.0)}  # 値段 1.6 − 0.5 × 2.7 = 0.25
        s, _ = self._strategy(probes=probes, settings={"veil9_trap_mode": True})
        assert s.generate_move()[0].gtp() == "D4"
        assert s.last_decision_info["kind"] == "free"

    def test_a_clearly_cheaper_trap_replaces_the_plain_deviation(self):
        probes = {**self.PROBES, "C7": _child(9.6, 0.94, punish=3.0)}  # 値段 0.4 − 1.35 = −0.95
        s, _ = self._strategy(probes=probes, settings={"veil9_trap_mode": True})
        assert s.generate_move()[0].gtp() == "C7"
        assert s.last_decision_info["kind"] == "trap"
        assert s.last_decision_info["price"] == pytest.approx(-0.95)
        assert s.last_decision_info["E"] == pytest.approx(2.7)  # ハーネスが罠の実損 / E に使うキー

    def test_trap_off_only_logs_the_trap_it_could_have_used(self):
        hp = {**self.HP, "D4": 0.30}
        probes = {"E5": _child(10.0, 0.95), "D4": _child(9.9, 0.94, punish=3.0), "F6": _child(9.2, 0.93)}
        s, _ = self._strategy(hp=hp, probes=probes)
        assert s.generate_move()[0].gtp() == "D4"
        assert s.last_decision_info["trap_shadow"] == 1

    def test_yose_trap_never_exceeds_yose_max_loss(self):
        hp = {"E5": 0.40, "D4": 0.01, "F6": 0.01, "C7": 0.03, "G3": 0.04}
        probes = {"E5": _child(10.0, 0.95), "C7": _child(8.8, 0.93, punish=3.0)}  # vloss 1.2・値段 −0.15
        yose, _ = self._strategy(depth=32, hp=hp, probes=probes, settings={"veil9_trap_mode": True})
        assert yose.generate_move()[0].gtp() == "E5"  # ヨセの上限 yose_max_loss 1.0 < 1.2
        mid, _ = self._strategy(depth=12, hp=hp, probes=probes, settings={"veil9_trap_mode": True})
        assert mid.generate_move()[0].gtp() == "C7"

    def test_dominant_trap_never_exceeds_dominant_max_loss(self):
        hp = {"E5": 0.85, "D4": 0.01, "F6": 0.01, "C7": 0.03, "G3": 0.04}
        dear = {"E5": _child(10.0, 0.95), "C7": _child(8.2, 0.93, punish=3.0)}  # vloss 1.8 > 1.5
        s, _ = self._strategy(hp=hp, probes=dear, settings={"veil9_trap_mode": True})
        assert s.generate_move()[0].gtp() == "E5"
        cheap = {"E5": _child(10.0, 0.95), "C7": _child(8.8, 0.93, punish=3.0)}
        s, _ = self._strategy(hp=hp, probes=cheap, settings={"veil9_trap_mode": True})
        assert s.generate_move()[0].gtp() == "C7"
        assert s.last_decision_info["tier"] == "ii"


class TestTerminal(_Harness):
    """S7（相手の直前パス）と S8（終局帯）。9路・黒番・最善手 E5。"""

    END = [
        {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.9},
        {"move": "D4", "pointsLost": 0.04, "relativePointsLost": 0.04, "visits": 50, "winrate": 0.9},
        {"move": "C3", "pointsLost": 0.08, "relativePointsLost": 0.08, "visits": 40, "winrate": 0.9},
        {"move": "F6", "pointsLost": 0.3, "relativePointsLost": 0.3, "visits": 30, "winrate": 0.9},
        {"move": "G7", "pointsLost": 0.02, "relativePointsLost": 0.02, "visits": 5, "winrate": 0.9},
        {"move": "pass", "pointsLost": 0.2, "relativePointsLost": 0.2, "visits": 60, "winrate": 0.9},
    ]
    # 盤上の第一感 G7 0.45 → 床 = max(0.05, 0.2 × 0.45) = 0.09
    END_HP = {"E5": 0.30, "D4": 0.10, "C3": 0.25, "F6": 0.40, "G7": 0.45, "pass": 0.0}

    def _end(self, pass_loss=0.2, **kw):
        cands = [dict(c) for c in self.END]
        cands[-1]["relativePointsLost"] = cands[-1]["pointsLost"] = pass_loss
        kw.setdefault("hp", self.END_HP)
        return self._strategy(cands=cands, **kw)

    def test_opponent_pass_with_an_expensive_pass_never_deviates(self):
        s, _ = self._end(pass_loss=3.0, lead=10.0, last_move=Move(None, player="W"), ownership=[0.1] * 81)
        move, _ = s.generate_move()
        assert move.gtp() == "E5"
        assert s.queries == ["Probe"] and s.probe_calls == []
        info = s.last_decision_info
        assert (info["tier"], info["why"], info["queries"]) == ("terminal", "opp_pass", 1)

    def test_opponent_pass_on_a_settled_board_passes(self):
        s, _ = self._end(pass_loss=3.0, last_move=Move(None, player="W"), ownership=[0.95] * 81)
        assert s.generate_move()[0].is_pass
        assert s.queries == ["Probe"]

    def test_opponent_pass_with_a_cheap_pass_passes_without_queries(self):
        s, _ = self._end(pass_loss=0.2, last_move=Move(None, player="W"))
        assert s.generate_move()[0].is_pass
        assert s.queries == [] and s.last_decision_info["kind"] == "pass"

    def test_terminal_band_passes_when_a_9d_would(self):
        s, _ = self._end(hp={**self.END_HP, "pass": 0.6})
        assert s.generate_move()[0].is_pass
        assert s.queries == ["parent hp"] and s.probe_calls == []

    def test_swap_allows_0_10_with_a_clear_lead_and_0_05_in_a_close_game(self):
        clear, _ = self._end(lead=10.0)
        move, _ = clear.generate_move()
        assert move.gtp() == "C3"  # hp 0.25・0.08 目（F6 は 0.3 目、G7 は visits 5）
        assert clear.last_decision_info["kind"] == "swap" and clear.probe_calls == []
        close, _ = self._end(lead=1.0)
        assert close.generate_move()[0].gtp() == "D4"  # 0.05 目以内は D4 だけ

    def test_swap_failing_the_invariant_plays_the_best_move(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ai_module, "veil_invariant_ok", lambda *a: calls.append(a) or False)
        s, logs = self._end(lead=10.0)
        assert s.generate_move()[0].gtp() == "E5"
        assert calls == [("C3", "E5", {c["move"] for c in self.END}, "terminal", {"raw": 0.08, "limit": 0.10})]
        assert any("Invariant violated: chosen=C3 kind=terminal" in m for m in logs)
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["why"]) == ("failsafe", "best", "invariant")

    def test_swap_needs_an_open_gate_for_an_obvious_move(self):
        hp = {**self.END_HP, "E5": 0.85, "G7": 0.05}
        s, logs = self._end(lead=10.0, hist=_hist("B", 3, 9), hp=hp)
        move, _ = s.generate_move()
        assert move.gtp() == "E5"  # 9段の最上位 E5＝最善手（(d)）
        info = s.last_decision_info
        # S12 の dominant_closed（tier "ii"）ではなく S8 の (d) で決まった
        assert (info["tier"], info["kind"], info["why"]) == ("terminal", "best", "terminal")
        assert any("Terminal: humanSL top E5" in m for m in logs)

    # 盤上の第一感 G7 0.04 < 床 0.05 → (c) の候補は無く、(d) の 9段の最上位 G7（最善手ではない）だけが残る
    FLAT_HP = {"E5": 0.03, "D4": 0.01, "C3": 0.01, "F6": 0.02, "G7": 0.04}

    def _finish(self, g7_loss=0.02, g7_visits=50, **kw):
        """(d) の手 G7 の生の loss と visits を差し替えた終局帯（pass 0.2 目・hp は FLAT_HP）。"""
        cands = [dict(c) for c in self.END]
        cands[4].update(pointsLost=g7_loss, relativePointsLost=g7_loss, visits=g7_visits)
        kw.setdefault("hp", self.FLAT_HP)
        return self._strategy(cands=cands, **kw)

    REJECTED = "Terminal: finishing move G7 rejected by the swap conditions"

    def test_finishing_move_needs_the_swap_visits_and_loss_limit(self):
        hp = {"E5": 0.30, "D4": 0.01, "C3": 0.01, "F6": 0.02, "G7": 0.45}
        shallow, logs = self._end(lead=1.0, hp=hp)
        assert shallow.generate_move()[0].gtp() == "E5"  # G7 は 0.02 目でも visits 5 < 10
        info = shallow.last_decision_info
        assert (info["tier"], info["kind"], info["why"]) == ("terminal", "best", "terminal_finish_rejected")
        assert any(self.REJECTED + " (visits 5," in m for m in logs)
        assert any("Terminal: no cheap natural finishing move" in m for m in logs)  # (e) の行も残る
        dear, logs = self._finish(g7_loss=0.3, lead=1.0)
        assert dear.generate_move()[0].gtp() == "E5"  # 0.3 目 > 0.05（margin 0.5 未満でも打たない）
        info = dear.last_decision_info
        assert (info["tier"], info["kind"], info["why"]) == ("terminal", "best", "terminal_finish_rejected")
        assert any(self.REJECTED in m and "loss 0.30, limit 0.05" in m for m in logs)

    def test_no_finishing_move_keeps_why_terminal(self):
        # 9段の最上位 A9 は KataGo の候補に無い＝(d) の手そのものが無い（却下とは区別する）
        s, logs = self._finish(lead=1.0, hp={**self.FLAT_HP, "A9": 0.045})
        assert s.generate_move()[0].gtp() == "E5"
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["why"]) == ("terminal", "best", "terminal")
        assert not any("rejected by the swap conditions" in m for m in logs)

    def test_finishing_move_needs_an_open_gate_when_the_best_move_is_obvious(self):
        # dominant_hp を 0.03 に下げる → 最善手 E5（hp 0.03）が明らかな一手。9段の最上位 G7（0.04）は最善手ではない
        settings = {"veil9_dominant_hp": 0.03}
        closed, logs = self._finish(lead=1.0, hist=_hist("B", 3, 9), settings=settings)  # p_match 0.40 = T → u 0
        assert closed.generate_move()[0].gtp() == "E5"
        info = closed.last_decision_info
        assert (info["tier"], info["kind"], info["why"]) == ("terminal", "best", "terminal_finish_rejected")
        assert info["dominant"] is True and info["u"] == 0.0
        assert any(self.REJECTED in m and "dominant True, u 0.00" in m for m in logs)
        opened, _ = self._finish(lead=1.0, settings=settings)  # 履歴なし → u 1＝ゲートが開く
        assert opened.generate_move()[0].gtp() == "G7"
        assert opened.last_decision_info["kind"] == "finish"

    def test_finishing_move_with_a_clear_lead_ignores_the_close_drift_cap(self):
        state = {"veil9": {"endgame": False, "close_drift": 0.5, "ledger": []}}
        s, _ = self._finish(lead=10.0, settings={"veil9_close_drift_cap": 0.1}, _veil_state=state)
        assert s.generate_move()[0].gtp() == "G7"  # |lead| >= 3 では累計（0.5 > 上限 0.1）を見ない
        assert s.last_decision_info["kind"] == "finish"
        assert state["veil9"]["close_drift"] == pytest.approx(0.5)  # 累計にも足さない

    @pytest.mark.parametrize("visits,move", [(VEIL_TERMINAL_MIN_VISITS - 1, "E5"), (VEIL_TERMINAL_MIN_VISITS, "G7")])
    def test_finishing_move_visits_floor_is_inclusive(self, visits, move):
        s, _ = self._finish(g7_visits=visits, lead=1.0)
        assert s.generate_move()[0].gtp() == move

    @pytest.mark.parametrize("lead,move", [(1.0, "E5"), (10.0, "G7")])
    def test_finishing_move_loss_limit_depends_on_the_lead(self, lead, move):
        s, _ = self._finish(g7_loss=0.08, lead=lead)
        assert s.generate_move()[0].gtp() == move  # 0.08 目は接戦の上限 0.05 を超え、明確なリードの上限 0.10 以内

    def test_finishing_move_within_the_swap_conditions_is_played(self):
        s, _ = self._finish(lead=1.0)
        assert s.generate_move()[0].gtp() == "G7"  # visits 50 >= 10・0.02 目 <= 0.05・累計上限なし
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["raw"]) == ("terminal", "finish", pytest.approx(0.02))
        assert s.probe_calls == [] and s.queries == ["parent hp"]
        assert s.game._veil_state["veil9"]["close_drift"] == 0.0  # 上限 0（既定）なら累計に足さない

    @pytest.mark.parametrize(
        "cap,move,kind,drift_after", [(0.0, "D4", "swap", 0.08), (0.2, "D4", "swap", 0.12), (0.1, "E5", "best", 0.08)]
    )
    def test_close_drift_cap_limits_the_swap_and_the_finishing_move(self, cap, move, kind, drift_after):
        # 上限 0.1 では 0.08 + 0.04 > 0.1 で (c) の D4 も (d) の D4（9段の最上位）も打てない → 最善手
        hp = {"E5": 0.20, "D4": 0.30, "C3": 0.25, "F6": 0.0, "G7": 0.0}
        state = {"veil9": {"endgame": False, "close_drift": 0.08, "ledger": []}}
        s, _ = self._end(lead=1.0, hp=hp, settings={"veil9_close_drift_cap": cap}, _veil_state=state)
        assert s.generate_move()[0].gtp() == move
        assert s.last_decision_info["kind"] == kind
        assert state["veil9"]["close_drift"] == pytest.approx(drift_after)

    def test_finishing_move_in_a_close_game_adds_to_the_close_drift(self):
        state = {"veil9": {"endgame": False, "close_drift": 0.05, "ledger": []}}
        s, _ = self._finish(lead=1.0, settings={"veil9_close_drift_cap": 0.1}, _veil_state=state)
        assert s.generate_move()[0].gtp() == "G7"  # 0.05 + 0.02 <= 0.1
        assert s.last_decision_info["kind"] == "finish"
        assert state["veil9"]["close_drift"] == pytest.approx(0.07)

    def test_finishing_move_failing_the_invariant_plays_the_best_move(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ai_module, "veil_invariant_ok", lambda *a: calls.append(a) or False)
        state = {"veil9": {"endgame": False, "close_drift": 0.05, "ledger": []}}
        s, _ = self._finish(lead=1.0, settings={"veil9_close_drift_cap": 0.1}, _veil_state=state)
        records = []
        s.game.katrain.log = lambda msg, level=None, *a, **k: records.append((str(msg), level))
        assert s.generate_move()[0].gtp() == "E5"
        gtps = {c["move"] for c in self.END}
        assert calls == [("G7", "E5", gtps, "terminal", {"raw": 0.02, "limit": 0.05})]
        assert any(lv == OUTPUT_ERROR and "Invariant violated: chosen=G7 kind=terminal" in m for m, lv in records)
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["why"]) == ("failsafe", "best", "invariant")
        assert state["veil9"]["close_drift"] == pytest.approx(0.05)  # 打たなかった手は累計に足さない

    def test_terminal_humansl_failure_plays_the_best_move(self):
        s, logs = self._end(hp_ok=False)
        assert s.generate_move()[0].gtp() == "E5"
        info = s.last_decision_info
        # S11 の humanSL 失敗ではなく S8 (a) で決まった（pass_loss が載り、S9 の予算は出していない）
        assert (info["tier"], info["kind"], info["why"]) == ("failsafe", "best", "no_hp")
        assert info["pass_loss"] == pytest.approx(0.2) and "A_t" not in info
        assert any("Terminal: pass loses 0.20 but humanSL unavailable" in m for m in logs)


# (クラス, 盤, 設定接頭辞, ai キー, 定数)
VEILS = [
    (Veil9Strategy, 9, "veil9", "ai:veil9", AI_VEIL_9),
    (Veil13Strategy, 13, "veil13", "ai:veil13", AI_VEIL_13),
    (Veil19Strategy, 19, "veil19", "ai:veil19", AI_VEIL_19),
]
VEIL_IDS = [v[2] for v in VEILS]


class TestBoardFamily:
    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_registered_with_board_prefix_and_label(self, cls, size, prefix, ai_key, const):
        assert const == ai_key
        assert STRATEGY_REGISTRY[const] is cls
        assert issubclass(cls, Veil9Strategy)
        assert (cls.BOARD_LEN, cls.KEY_PREFIX, cls.LABEL) == (size, prefix, f"Veil{size}")

    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_defaults_match_the_spec_table(self, cls, size, prefix, ai_key, const):
        assert cls.SETTING_DEFAULTS == EXPECTED_DEFAULTS[size]
        for key, value in SAFETY_DEFAULTS[size].items():
            assert cls.SETTING_DEFAULTS[key] == value, key

    def test_board_constants(self):
        assert Veil13Strategy.VEIL_BOARD == {
            "endgame_move": 85,
            "unsettled_max": 16,
            "trusted_visits": 50,
            "probe_hp": 3,
            "probe_cheap": 2,
        }
        assert Veil19Strategy.VEIL_BOARD == {
            "endgame_move": 150,
            "unsettled_max": 36,
            "trusted_visits": 50,
            "probe_hp": 3,
            "probe_cheap": 1,
        }

    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS[1:], ids=VEIL_IDS[1:])
    def test_the_flow_is_shared(self, cls, size, prefix, ai_key, const):
        assert cls._generate_move is Veil9Strategy._generate_move
        assert cls.generate_move is Enigma9Strategy.generate_move


class _Harness13(_Harness):
    CLS = Veil13Strategy
    SIZE = 13
    CANDS = [
        {"move": "G7", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.62},
        {"move": "D4", "pointsLost": 0.2, "relativePointsLost": 0.2, "visits": 80, "winrate": 0.61},
        {"move": "K10", "pointsLost": 1.0, "relativePointsLost": 1.0, "visits": 120, "winrate": 0.58},
        {"move": "A1", "pointsLost": 9.0, "relativePointsLost": 9.0, "visits": 3, "winrate": 0.20},
    ]
    HP = {"G7": 0.40, "D4": 0.30, "K10": 0.15}


class TestVeil13Flow(_Harness13):
    def test_budget_follows_the_spec_example(self):
        # 13路・u = 1・lead +7 → S = 2・A_t = 1.0（spec §6 の目安）
        s, logs = self._strategy(lead=7.0, wr=0.9, probes={})
        s.generate_move()
        assert s.last_decision_info["A_t"] == pytest.approx(1.0)
        assert any("Budget: lead=7.00 reserve=5.0 S=2.00 F=0.30 cap=4.50 A_t=1.00" in m for m in logs)

    def test_state_is_kept_per_board_prefix(self):
        probes = {"G7": _child(0.5, 0.55, size=13), "D4": _child(0.45, 0.545, size=13)}
        s, _ = self._strategy(lead=0.5, wr=0.55, hist=_hist("B", 2, 9), probes=probes)
        move, _ = s.generate_move()
        # u = 0（p_match 0.30 = 目標）・D4 は visits 80 >= trusted 50 → cons = max(0.05, 0.2) = 0.2 <= 0.3
        assert move.gtp() == "D4" and s.last_decision_info["kind"] == "free"
        assert list(s.game._veil_state) == ["veil13"]

    def test_endgame_threshold_is_85_moves(self):
        s, _ = self._strategy(depth=84, probes={})
        s.generate_move()
        assert s.last_decision_info["in_yose"] is False
        s, _ = self._strategy(depth=85, probes={})
        s.generate_move()
        assert s.last_decision_info["in_yose"] is True

    def test_wrong_board_plays_the_best_move(self):
        s, logs = self._strategy(size=9, cands=[dict(c) for c in _Harness.CANDS])
        assert s.generate_move()[0].gtp() == "E5"
        assert any("is not 13x13" in m for m in logs)


class TestRegistration:
    """戦略リスト・AI_OPTION_VALUES / AI_OPTION_ORDER・パッケージ config.json・i18n・デバッグ CLI の整合。"""

    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_listed_everywhere(self, cls, size, prefix, ai_key, const):
        from katrain.core.constants import (
            AI_STRATEGIES,
            AI_STRATEGIES_ENGINE,
            AI_STRATEGIES_RECOMMENDED_ORDER,
            AI_STRENGTH,
        )

        assert const in AI_STRATEGIES_ENGINE and const in AI_STRATEGIES
        assert const in AI_STRATEGIES_RECOMMENDED_ORDER and const in AI_STRENGTH

    def test_recommended_order_puts_the_family_right_after_mimic(self):
        from katrain.core.constants import AI_MIMIC_13, AI_STRATEGIES_RECOMMENDED_ORDER

        i = AI_STRATEGIES_RECOMMENDED_ORDER.index(AI_MIMIC_13)
        assert AI_STRATEGIES_RECOMMENDED_ORDER[i + 1 : i + 4] == [AI_VEIL_9, AI_VEIL_13, AI_VEIL_19]

    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_defaults_in_gui_options_and_package_config(self, cls, size, prefix, ai_key, const):
        from katrain.core.constants import AI_OPTION_ORDER, AI_OPTION_VALUES

        with open(Path(katrain.__file__).parent / "config.json", encoding="utf-8") as f:
            package_ai_conf = json.load(f)["ai"][ai_key]
        assert set(package_ai_conf) == {f"{prefix}_{suffix}" for suffix in cls.SETTING_DEFAULTS}
        for order, (suffix, default) in enumerate(cls.SETTING_DEFAULTS.items()):
            key = f"{prefix}_{suffix}"
            assert package_ai_conf[key] == default, key
            assert AI_OPTION_ORDER[key] == order, key  # SETTING_DEFAULTS の並び＝画面の並び
            if AI_OPTION_VALUES[key] == "bool":
                assert isinstance(default, bool), key
                continue
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]
            assert default in plain, key

    @pytest.mark.parametrize("size", [9, 13, 19])
    def test_target_rate_range_and_off_values(self, size):
        from katrain.core.constants import AI_OPTION_VALUES

        rates = [v for v, _label in AI_OPTION_VALUES[f"veil{size}_target_rate"]]
        assert min(rates) == pytest.approx(0.15) and max(rates) == pytest.approx(0.50)
        assert (0.0, "OFF") in AI_OPTION_VALUES[f"veil{size}_close_drift_cap"]
        assert (1.01, "OFF") in AI_OPTION_VALUES[f"veil{size}_dominant_hp"]

    def test_attack_preset_is_selectable_on_13x13(self):
        from katrain.core.constants import AI_OPTION_VALUES

        preset = {"reserve": 3.0, "min_winrate": 0.75, "max_loss": 6.0, "spend_rate": 1.0}
        preset.update({"dominant_max_loss": 3.0, "yose_max_loss": 2.0})
        for suffix, value in preset.items():
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[f"veil13_{suffix}"]]
            assert value in plain, suffix

    def test_debug_cli_names(self):
        from katrain_debug.runner import STRATEGY_NAME_MAP

        for cls, size, prefix, ai_key, const in VEILS:
            assert STRATEGY_NAME_MAP[prefix] == const

    @pytest.mark.parametrize("lang", ["jp", "en"])
    def test_i18n_has_names_and_overviews(self, lang):
        po = (Path(katrain.__file__).parent / "i18n" / "locales" / lang / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        for cls, size, prefix, ai_key, const in VEILS:
            assert f'msgid "{ai_key}"' in po and f'msgid "aihelp:{prefix}"' in po, (lang, prefix)

    def test_jp_explains_every_slider_once_for_the_family(self):
        po = (Path(katrain.__file__).parent / "i18n" / "locales" / "jp" / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        for suffix in Veil9Strategy.SETTING_DEFAULTS:
            assert po.count(f'msgid "aiopt:veil*_{suffix}"') == 1, suffix

    def test_en_overview_has_one_bullet_per_slider(self):
        po = (Path(katrain.__file__).parent / "i18n" / "locales" / "en" / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        for cls, size, prefix, ai_key, const in VEILS:
            m = re.search(rf'msgid "aihelp:{prefix}"\s*\nmsgstr "(.*)"', po)
            assert m, prefix
            bullets = [line for line in m.group(1).split("\\n") if line.startswith("* ")]
            assert len(bullets) == len(cls.SETTING_DEFAULTS), prefix
