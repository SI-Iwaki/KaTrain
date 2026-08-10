"""候補の曖昧さ判定（`tsumego_decision_is_ambiguous`）の単体テスト。

背景は spec `docs/superpowers/specs/2026-08-10-tsumego-ambiguity-analysis.md`。
これを使うのは `_ko_promotion_choice` の dominant ゲート。KataGo・Kivy 不要。
"""

from katrain.core.ai import (
    TSUMEGO_AMBIGUOUS_POINTS_GAP,
    TSUMEGO_AMBIGUOUS_VISIT_RATIO,
    tsumego_decision_is_ambiguous,
)


def cand(move, visits, points_lost, prior=0.01):
    return {"move": move, "visits": visits, "pointsLost": points_lost, "prior": prior}


class TestAmbiguityPredicate:
    def test_dominant_requires_both_visits_and_points(self):
        """visits も目数も1手に集中しているときだけ dominant。"""
        dominant = [cand("A1", 1700, -0.8), cand("B2", 30, 3.1), cand("C3", 12, 4.0)]
        assert tsumego_decision_is_ambiguous(dominant) is False

    def test_close_visits_alone_makes_it_ambiguous(self):
        """目数が離れていても visits が拮抗していれば ambiguous（片側だけでは切らない）。"""
        moves = [cand("A1", 1000, -0.8), cand("B2", 600, 3.1)]
        assert tsumego_decision_is_ambiguous(moves) is True

    def test_close_points_alone_makes_it_ambiguous(self):
        """visits が集中していても目数が並んでいれば ambiguous。"""
        moves = [cand("A1", 1000, 0.0), cand("B2", 20, 0.3)]
        assert tsumego_decision_is_ambiguous(moves) is True

    def test_single_or_empty_candidate_is_not_ambiguous(self):
        """比べる相手が居ない手番は「拮抗していない」＝深い読みを撃たない。"""
        assert tsumego_decision_is_ambiguous([]) is False
        assert tsumego_decision_is_ambiguous([cand("A1", 100, 0.0)]) is False

    def test_only_top_five_by_visits_are_considered(self):
        """6手目以降は無視する（計測時の集合＝visits 上位5手に合わせる）。

        1visit の手を全部見ると目数の次点が入れ替わり、閾値を校正した集合と別物になる。
        """
        moves = [cand("A1", 1700, -0.8)] + [cand(f"B{i}", 300 - i, 3.0 + i) for i in range(1, 5)]
        moves.append(cand("Z9", 1, -0.7))  # 目数は次点だが visits 最下位＝上位5手の外
        # 上位5手だけなら目数差は 3.1-(-0.8)=3.9 >= 1.0 だが visits 比 299/1700=0.176 >= 0.15
        assert tsumego_decision_is_ambiguous(moves) is True
        # visits を絞れば dominant になる（Z9 が混ざっていないことの確認）
        moves[1:5] = [cand(f"B{i}", 20 - i, 3.0 + i) for i in range(1, 5)]
        assert tsumego_decision_is_ambiguous(moves) is False

    def test_thresholds_are_configurable(self):
        moves = [cand("A1", 1000, 0.0), cand("B2", 100, 2.0)]  # 比 0.10 / 目数差 2.0
        assert tsumego_decision_is_ambiguous(moves) is False  # 既定（0.15 / 1.0）では dominant
        assert tsumego_decision_is_ambiguous(moves, visit_ratio=0.05) is True  # 比を厳しくすれば ambiguous
        assert tsumego_decision_is_ambiguous(moves, points_gap=5.0) is True  # 目数を厳しくしても ambiguous

    def test_defaults_match_the_calibrated_constants(self):
        assert TSUMEGO_AMBIGUOUS_VISIT_RATIO == 0.15
        assert TSUMEGO_AMBIGUOUS_POINTS_GAP == 1.0
