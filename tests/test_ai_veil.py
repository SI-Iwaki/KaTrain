"""「韜晦（9/13/19路）」ai:veil9 / ai:veil13 / ai:veil19 の純関数・登録整合・_generate_move 通しテスト。

KataGo / Kivy 不要。設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md
"""

import json
import random
import types

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import (
    VeilCtx,
    game_report,
    veil_allowance,
    veil_choose,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_free_limit,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_urgency,
)
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
