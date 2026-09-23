"""「韜晦（9/13/19路）」ai:veil9 / ai:veil13 / ai:veil19 の純関数・登録整合・_generate_move 通しテスト。

KataGo / Kivy 不要。設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md
"""

import json
import random
import types

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import (
    game_report,
    veil_allowance,
    veil_free_limit,
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
