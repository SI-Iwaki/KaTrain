"""Unit tests for lambdago paper-derived metrics in katrain_debug.batch_eval.

All tests are pure-Python (no KataGo, no humanSL model) and operate on
dict literals shaped like KataGo candidate output and move_results rows.
"""
import pytest

from katrain.core.constants import ADDITIONAL_MOVE_ORDER
from katrain_debug.batch_eval import (
    _winrate_for_player,
    _candidate_median_loss,
    _aggregate_lambdago_metrics,
)


class TestWinrateForPlayer:
    def test_black_perspective_passthrough(self):
        # wr_black = 0.7 → B sees 0.7
        assert _winrate_for_player(0.7, "B") == pytest.approx(0.7)

    def test_white_perspective_inverted(self):
        # wr_black = 0.7 → W sees 0.3
        assert _winrate_for_player(0.7, "W") == pytest.approx(0.3)

    def test_white_at_98_percent(self):
        # wr_black = 0.02 → W is at 98%
        assert _winrate_for_player(0.02, "W") == pytest.approx(0.98)


class TestCandidateMedianLoss:
    def _c(self, points_lost, order=0, prior=0.1):
        d = {"pointsLost": points_lost, "order": order}
        if prior is not None:
            d["prior"] = prior
        return d

    def test_basic_three_candidates(self):
        # losses [0.0, 1.0, 3.0] → median 1.0
        cands = [self._c(0.0), self._c(1.0, order=1), self._c(3.0, order=2)]
        assert _candidate_median_loss(cands) == pytest.approx(1.0)

    def test_excludes_raw_policy_candidates(self):
        # order >= ADDITIONAL_MOVE_ORDER must be filtered out
        cands = [
            self._c(0.0, order=0),
            self._c(1.0, order=1),
            self._c(99.0, order=ADDITIONAL_MOVE_ORDER),       # excluded
            self._c(99.0, order=ADDITIONAL_MOVE_ORDER + 5),   # excluded
        ]
        # Remaining losses [0.0, 1.0] → median 0.5
        assert _candidate_median_loss(cands) == pytest.approx(0.5)

    def test_excludes_candidates_without_prior(self):
        cands = [
            self._c(0.0, order=0, prior=None),  # no prior → excluded
            self._c(2.0, order=1),
            self._c(4.0, order=2),
        ]
        # Remaining losses [2.0, 4.0] → median 3.0
        assert _candidate_median_loss(cands) == pytest.approx(3.0)

    def test_returns_none_when_no_eligible_candidates(self):
        cands = [self._c(0.0, order=ADDITIONAL_MOVE_ORDER + 1)]
        assert _candidate_median_loss(cands) is None

    def test_no_clamping_negative_loss_preserved(self):
        # Negative pointsLost (player surprised KataGo by playing better than top)
        # must be preserved, not clamped to 0.
        cands = [self._c(-0.5), self._c(0.0, order=1), self._c(2.0, order=2)]
        # Median of [-0.5, 0.0, 2.0] = 0.0
        assert _candidate_median_loss(cands) == pytest.approx(0.0)


def _row(player="B", point_loss_raw=0.0, cand_median_loss=0.0,
         point_loss=None, winrate_player=None):
    """Minimal move_result shorthand for lambdago aggregation tests."""
    return {
        "player": player,
        "point_loss_raw": point_loss_raw,
        "cand_median_loss": cand_median_loss,
        "point_loss": point_loss if point_loss is not None else max(0.0, point_loss_raw),
        "winrate_player": winrate_player,
        "move_num": 1,
    }


class TestAggregateChoiceVsMedian:
    def test_empty_input_returns_empty_dict(self):
        result = _aggregate_lambdago_metrics([])
        assert result == {}

    def test_overall_mean_basic(self):
        # gaps: -1.0, -0.5, 0.0 → mean -0.5
        rows = [
            _row(point_loss_raw=0.0, cand_median_loss=1.0),  # gap -1.0
            _row(point_loss_raw=0.5, cand_median_loss=1.0),  # gap -0.5
            _row(point_loss_raw=1.0, cand_median_loss=1.0),  # gap  0.0
        ]
        result = _aggregate_lambdago_metrics(rows)
        cvm = result["choice_vs_median"]
        assert cvm["overall"]["count"] == 3
        assert cvm["overall"]["mean"] == pytest.approx(-0.5)

    def test_negative_ratio_threshold(self):
        # gaps: -0.6 (counts), -0.4 (does not), -1.0 (counts), 0.5 (does not)
        # Threshold is gap < -0.5
        rows = [
            _row(point_loss_raw=0.0, cand_median_loss=0.6),   # gap -0.6 ✓
            _row(point_loss_raw=0.6, cand_median_loss=1.0),   # gap -0.4 ✗
            _row(point_loss_raw=0.0, cand_median_loss=1.0),   # gap -1.0 ✓
            _row(point_loss_raw=1.5, cand_median_loss=1.0),   # gap +0.5 ✗
        ]
        result = _aggregate_lambdago_metrics(rows)
        assert result["choice_vs_median"]["overall"]["negative_ratio"] == pytest.approx(0.5)

    def test_b_w_split(self):
        rows = [
            _row(player="B", point_loss_raw=0.0, cand_median_loss=2.0),  # B gap -2.0
            _row(player="B", point_loss_raw=0.0, cand_median_loss=2.0),  # B gap -2.0
            _row(player="W", point_loss_raw=1.0, cand_median_loss=1.0),  # W gap  0.0
        ]
        result = _aggregate_lambdago_metrics(rows)
        cvm = result["choice_vs_median"]
        assert cvm["B"]["count"] == 2
        assert cvm["B"]["mean"] == pytest.approx(-2.0)
        assert cvm["W"]["count"] == 1
        assert cvm["W"]["mean"] == pytest.approx(0.0)

    def test_skips_rows_with_missing_data(self):
        # Rows where cand_median_loss is None (e.g. no eligible candidates) are skipped.
        rows = [
            _row(point_loss_raw=0.0, cand_median_loss=None),
            _row(point_loss_raw=0.0, cand_median_loss=1.0),  # gap -1.0
        ]
        result = _aggregate_lambdago_metrics(rows)
        assert result["choice_vs_median"]["overall"]["count"] == 1
        assert result["choice_vs_median"]["overall"]["mean"] == pytest.approx(-1.0)

    def test_reference_block_included(self):
        rows = [_row(point_loss_raw=0.0, cand_median_loss=1.0)]
        result = _aggregate_lambdago_metrics(rows)
        assert result["reference"] == {
            "human_amateur_loss": 0.65,
            "ai_suspect_loss": 0.25,
        }
