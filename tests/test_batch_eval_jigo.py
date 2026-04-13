# tests/test_batch_eval_jigo.py
"""batch_eval の Jigo 集計関数のユニットテスト。"""
import pytest

from katrain_debug.batch_eval import _aggregate_jigo_metrics


def _m(score_lead=None, selected_hp=None, rank_used=None, filter_relaxed=False,
       score_lead_biased=False):
    """Minimal move_result shorthand."""
    return {
        "score_lead": score_lead,
        "selected_hp": selected_hp,
        "rank_used": rank_used,
        "filter_relaxed": filter_relaxed,
        "score_lead_biased": score_lead_biased,
    }


class TestAggregateJigoMetrics:
    def test_empty_input_returns_empty_dict(self):
        result = _aggregate_jigo_metrics([], target_score=0.5, target_score_max=10.0)
        assert result == {}

    def test_ignores_moves_with_none_score_lead(self):
        # 非 Jigo 戦略で埋められた行（score_lead=None）は集計から除外
        moves = [_m(score_lead=None), _m(score_lead=5.0, selected_hp=0.3)]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["count"] == 1
        assert result["mean_lead"] == 5.0

    def test_mean_and_max_lead(self):
        moves = [
            _m(score_lead=2.0, selected_hp=0.5),
            _m(score_lead=8.0, selected_hp=0.3),
            _m(score_lead=14.0, selected_hp=0.2),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["mean_lead"] == pytest.approx(8.0)
        assert result["max_lead"] == 14.0

    def test_in_target_and_over_target_ratios(self):
        # target=0.5, target_max=10.0
        # in_target: 0.5 <= lead <= 10.0 → [2.0, 8.0] が該当 (2/3)
        # over_target: lead > 10.0 → [14.0] が該当 (1/3)
        moves = [
            _m(score_lead=2.0, selected_hp=0.5),
            _m(score_lead=8.0, selected_hp=0.3),
            _m(score_lead=14.0, selected_hp=0.2),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["in_target_ratio"] == pytest.approx(2 / 3)
        assert result["over_target_ratio"] == pytest.approx(1 / 3)

    def test_mean_and_p10_selected_hp(self):
        # hp: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        # mean = 0.55, p10（下位10%値）= 0.1
        moves = [_m(score_lead=5.0, selected_hp=hp / 10) for hp in range(1, 11)]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["mean_selected_hp"] == pytest.approx(0.55)
        assert result["p10_selected_hp"] == pytest.approx(0.1, abs=0.01)

    def test_filter_relax_rate(self):
        moves = [
            _m(score_lead=5.0, selected_hp=0.3, filter_relaxed=True),
            _m(score_lead=5.0, selected_hp=0.3, filter_relaxed=False),
            _m(score_lead=5.0, selected_hp=0.3, filter_relaxed=False),
            _m(score_lead=5.0, selected_hp=0.3, filter_relaxed=True),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["filter_relax_rate"] == pytest.approx(0.5)

    def test_rank_downgrade_counts(self):
        moves = [
            _m(score_lead=5.0, selected_hp=0.3, rank_used="rank_9d"),
            _m(score_lead=5.0, selected_hp=0.3, rank_used="rank_9d"),
            _m(score_lead=5.0, selected_hp=0.3, rank_used="rank_7d"),
            _m(score_lead=5.0, selected_hp=0.3, rank_used="rank_5d"),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["rank_downgrade_counts"] == {
            "rank_9d": 2, "rank_7d": 1, "rank_5d": 1
        }

    def test_biased_lead_rate(self):
        # score_lead_biased=True の手番比率（Stage2 失敗率）
        moves = [
            _m(score_lead=5.0, selected_hp=0.3, score_lead_biased=False),
            _m(score_lead=5.0, selected_hp=0.3, score_lead_biased=True),
            _m(score_lead=5.0, selected_hp=0.3, score_lead_biased=False),
            _m(score_lead=5.0, selected_hp=0.3, score_lead_biased=True),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["biased_lead_rate"] == pytest.approx(0.5)
