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
    veil_tally,
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
