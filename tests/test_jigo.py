# tests/test_jigo.py
"""JigoStrategy pure-function unit tests."""
import pytest

from katrain.core.ai import (
    _jigo_filter_candidates,
    _jigo_relax_filters,
    _jigo_select_move,
)


def _c(move, score, loss, hp):
    """Build a candidate dict shorthand."""
    return {"move": move, "score": score, "loss": loss, "hp": hp}


class TestJigoFilterCandidates:
    def test_passes_moves_within_both_limits(self):
        cands = [
            _c("A1", 5.0, 0.0, 0.10),
            _c("B2", 4.0, 1.0, 0.05),
        ]
        result = _jigo_filter_candidates(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 2

    def test_rejects_move_exceeding_loss_cap(self):
        cands = [
            _c("A1", 5.0, 0.0, 0.10),
            _c("B2", -2.0, 7.0, 0.05),  # loss 7.0 > 5.6
        ]
        result = _jigo_filter_candidates(cands, max_loss=5.6, min_hp=0.01)
        assert [c["move"] for c in result] == ["A1"]

    def test_rejects_move_below_hp_threshold(self):
        cands = [
            _c("A1", 5.0, 0.0, 0.10),
            _c("B2", 4.0, 1.0, 0.005),  # hp 0.005 < 0.01
        ]
        result = _jigo_filter_candidates(cands, max_loss=5.6, min_hp=0.01)
        assert [c["move"] for c in result] == ["A1"]


class TestJigoRelaxFilters:
    def test_first_relax_step_hp_half(self):
        # all candidates have hp < base_hp but >= base_hp*0.5
        cands = [_c("A1", 5.0, 1.0, 0.006)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "hp_half"

    def test_second_relax_step_hp_quarter(self):
        cands = [_c("A1", 5.0, 1.0, 0.003)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "hp_quarter"

    def test_loss_relax_step(self):
        # hp ok under 0.25*base, but loss is between base and base*1.5
        cands = [_c("A1", 5.0, 7.0, 0.003)]  # loss 7.0 < 5.6*1.5=8.4
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "loss_150"

    def test_safety_valve_returns_top_candidate_when_all_fail(self):
        # hp and loss both too extreme — safety valve falls back to cands[0]
        cands = [
            _c("A1", 5.0, 99.0, 0.0),
            _c("B2", 4.0, 99.0, 0.0),
        ]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert result == [cands[0]]
        assert reason == "safety_valve"


class TestJigoSelectMove:
    """Selection logic is (current_lead × mode) dependent."""

    def test_below_target_picks_closest_to_target(self):
        # current_lead = -3.0, target = 0.5 → natural
        cands = [
            _c("A1", 5.0, 0.0, 0.10),
            _c("B2", 1.0, 4.0, 0.05),
            _c("C3", 0.5, 4.5, 0.05),  # closest to target=0.5
        ]
        pick = _jigo_select_move(
            cands, current_lead=-3.0, target_score=0.5,
            target_score_max=10.0, mode="natural"
        )
        assert pick["move"] == "C3"

    def test_above_max_picks_closest_to_target(self):
        # current_lead = 30.0 (way over 10.0) — both modes act the same
        cands = [
            _c("A1", 25.0, 0.0, 0.10),
            _c("B2", 5.0, 20.0, 0.05),
            _c("C3", 1.0, 24.0, 0.05),  # closest to target=0.5
        ]
        pick = _jigo_select_move(
            cands, current_lead=30.0, target_score=0.5,
            target_score_max=10.0, mode="natural"
        )
        assert pick["move"] == "C3"

    def test_in_range_natural_uses_weighted_choice(self, monkeypatch):
        # in range: natural → weighted_selection_without_replacement path
        cands = [
            _c("A1", 5.0, 0.0, 0.90),
            _c("B2", 3.0, 2.0, 0.05),
        ]

        def fake_weighted(items, n):
            # pick the highest-weight entry deterministically
            return [max(items, key=lambda t: t[1])]

        from katrain.core import ai as ai_mod
        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)

        pick = _jigo_select_move(
            cands, current_lead=5.0, target_score=0.5,
            target_score_max=10.0, mode="natural"
        )
        assert pick["move"] == "A1"

    def test_in_range_maintain_picks_closest_to_target(self):
        cands = [
            _c("A1", 5.0, 0.0, 0.90),
            _c("B2", 1.0, 4.0, 0.05),  # closest to target=0.5
        ]
        pick = _jigo_select_move(
            cands, current_lead=5.0, target_score=0.5,
            target_score_max=10.0, mode="maintain"
        )
        assert pick["move"] == "B2"
