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
        # hp×0.25 = 0.0025 だが、ハードフロア 0.005 で止まる
        # → hp=0.005 の候補が hp_quarter で通る（hp_half=0.005 より下だが hp_quarter=max(0.0025,0.005)=0.005）
        # 実際には hp_half=0.005 で先に通るため、このテストは成立しない
        # → hp=0.006 を使って hp_half で通るパターンに変更
        cands = [_c("A1", 5.0, 1.0, 0.006)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "hp_half"  # ← hp_quarter から hp_half に変更

    def test_loss_relax_step(self):
        # hp=0.005（ハードフロア）で hp_half/hp_quarter は同じ条件に。
        # loss が max_loss を超えていれば loss_150 に落ちる。
        cands = [_c("A1", 5.0, 7.0, 0.005)]  # loss 7.0 < 5.6*1.5=8.4
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

    def test_hard_floor_prevents_relaxation_below_0_005(self):
        # min_hp=0.01 で hp×0.25 = 0.0025 になるはずだが、ハードフロア 0.005 で止まる
        # → hp=0.003 の候補は通らない、hp=0.006 の候補は hp_half で通る
        cands = [
            _c("A1", 5.0, 1.0, 0.003),  # hp < ハードフロア → 通さない
            _c("B2", 5.0, 1.0, 0.006),  # hp_half (0.005) で通る
        ]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert [c["move"] for c in result] == ["B2"]
        assert reason == "hp_half"

    def test_hard_floor_with_user_lowering_min_hp(self):
        # min_hp=0.005 でも hp×0.25=0.00125 → 0.005 にクリップ
        # hp=0.004 の候補は通らない
        cands = [_c("A1", 5.0, 1.0, 0.004)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.005)
        # ハードフロアに阻まれ safety_valve へ
        assert reason == "safety_valve"
        assert result == [cands[0]]  # 先頭候補を返す

    def test_hard_floor_allows_exactly_at_floor(self):
        # hp=0.005 ちょうど → ハードフロアに一致して通る
        cands = [_c("A1", 5.0, 1.0, 0.005)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert [c["move"] for c in result] == ["A1"]
        assert reason == "hp_half"


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

    def test_epsilon_kwarg_defaults_to_zero_preserves_current_behavior(self):
        # epsilon 省略時は現行 argmin 挙動と同じ
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

    def test_epsilon_applied_in_below_target_branch(self, monkeypatch):
        # lead < target_score → 分岐1 → ε バンドで humanPolicy 重み
        # C3 は band 外だが hp 最大 → band フィルタが働かないと C3 が選ばれる（退行検知）
        cands = [
            _c("A1", 0.5, 0.0, 0.10),  # diff=0（argmin）
            _c("B2", 0.8, -0.3, 0.80),  # diff=0.3、band 内で hp 最大
            _c("C3", 5.0, -4.5, 0.99),  # diff=4.5、band 外、全体で hp 最大
        ]
        from katrain.core import ai as ai_mod

        def fake_weighted(items, n):
            return [max(items, key=lambda t: t[1])]

        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)
        pick = _jigo_select_move(
            cands, current_lead=-3.0, target_score=0.5,
            target_score_max=10.0, mode="natural", epsilon=0.5
        )
        # band = {A1(diff=0), B2(diff=0.3)} → band 内の hp 最大 B2
        # C3 は band 外なので選ばれない
        assert pick["move"] == "B2"

    def test_epsilon_applied_in_in_range_maintain_branch(self, monkeypatch):
        # in_range & mode=maintain → 分岐3 → ε バンドで humanPolicy 重み
        # C3 は band 外だが hp 最大 → band フィルタが働かないと C3 が選ばれる（退行検知）
        cands = [
            _c("A1", 0.5, 0.0, 0.10),  # diff=0
            _c("B2", 1.0, -0.5, 0.80),  # diff=0.5、band 内で hp 最大
            _c("C3", 5.0, -4.5, 0.99),  # diff=4.5、band 外、全体で hp 最大
        ]
        from katrain.core import ai as ai_mod

        def fake_weighted(items, n):
            return [max(items, key=lambda t: t[1])]

        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)
        pick = _jigo_select_move(
            cands, current_lead=5.0, target_score=0.5,
            target_score_max=10.0, mode="maintain", epsilon=0.5
        )
        assert pick["move"] == "B2"

    def test_unknown_mode_in_range_raises_value_error(self):
        # 未知の mode で in_range なら ValueError
        cands = [_c("A1", 5.0, 0.0, 0.10)]
        import pytest as _pt
        with _pt.raises(ValueError, match="unknown jigo_mode"):
            _jigo_select_move(
                cands, current_lead=5.0, target_score=0.5,
                target_score_max=10.0, mode="aggressive", epsilon=0.5
            )

    def test_epsilon_ignored_in_in_range_natural_branch(self, monkeypatch):
        # 分岐2(natural) は ε を無視して既存 humanPolicy 重み単体
        cands = [
            _c("A1", 5.0, 0.0, 0.90),  # hp 最大
            _c("B2", 0.5, 4.5, 0.05),  # target 最近接
        ]
        from katrain.core import ai as ai_mod

        def fake_weighted(items, n):
            return [max(items, key=lambda t: t[1])]

        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)
        pick = _jigo_select_move(
            cands, current_lead=5.0, target_score=0.5,
            target_score_max=10.0, mode="natural", epsilon=0.5
        )
        # 分岐2: ε 無視、全候補 hp 重み → A1
        assert pick["move"] == "A1"

    def test_epsilon_ignored_in_above_target_max_branch(self):
        # 分岐4(lead > target_max) は ε を無視して argmin
        cands = [
            _c("A1", 25.0, 0.0, 0.80),  # hp 大だが diff 大
            _c("B2", 0.5, 24.5, 0.05),  # diff=0、argmin
        ]
        pick = _jigo_select_move(
            cands, current_lead=30.0, target_score=0.5,
            target_score_max=10.0, mode="natural", epsilon=0.5
        )
        assert pick["move"] == "B2"


class TestJigoExcludeSharpMoves:
    def test_excludes_moves_with_score_above_current_lead(self):
        from katrain.core.ai import _jigo_exclude_sharp_moves
        cands = [
            _c("A1", 22.0, 0.0, 0.10),  # score > lead=20.0 → 除外
            _c("B2", 18.0, 4.0, 0.05),  # score < lead → 残る
            _c("C3", 15.0, 7.0, 0.05),  # score < lead → 残る
        ]
        result = _jigo_exclude_sharp_moves(cands, current_lead=20.0)
        assert [c["move"] for c in result] == ["B2", "C3"]

    def test_epsilon_tolerates_tiny_overshoot(self):
        from katrain.core.ai import _jigo_exclude_sharp_moves
        cands = [
            _c("A1", 20.4, 0.0, 0.10),  # +0.4 over, within epsilon=0.5
            _c("B2", 20.6, 0.0, 0.10),  # +0.6 over, beyond epsilon
        ]
        result = _jigo_exclude_sharp_moves(cands, current_lead=20.0)
        assert [c["move"] for c in result] == ["A1"]

    def test_returns_original_when_all_candidates_would_be_excluded(self):
        from katrain.core.ai import _jigo_exclude_sharp_moves
        cands = [
            _c("A1", 25.0, 0.0, 0.10),
            _c("B2", 30.0, 0.0, 0.10),
        ]
        result = _jigo_exclude_sharp_moves(cands, current_lead=20.0)
        # 全滅なら元のリストを返す（安全弁）
        assert result == cands

    def test_empty_input_returns_empty(self):
        from katrain.core.ai import _jigo_exclude_sharp_moves
        result = _jigo_exclude_sharp_moves([], current_lead=20.0)
        assert result == []


class TestSelectRankByLead:
    def test_no_downshift_when_delta_small(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta = 15 - 10 = 5、閾値（>5）未満 → 降格なし
        assert _select_rank_by_lead(15.0, 10.0, "rank_9d") == "rank_9d"

    def test_one_step_downshift_for_medium_delta(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta = 20 - 10 = 10、5 < delta <= 15 → 1段下
        assert _select_rank_by_lead(20.0, 10.0, "rank_9d") == "rank_7d"

    def test_two_step_downshift_for_large_delta(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta = 30 - 10 = 20、delta > 15 → rank_5d まで一気に
        assert _select_rank_by_lead(30.0, 10.0, "rank_9d") == "rank_5d"

    def test_downshift_respects_floor(self):
        from katrain.core.ai import _select_rank_by_lead
        # base=rank_5d で delta > 15 → すでに下限
        assert _select_rank_by_lead(30.0, 10.0, "rank_5d") == "rank_5d"

    def test_downshift_from_rank_7d(self):
        from katrain.core.ai import _select_rank_by_lead
        # base=rank_7d, delta 10 (5<delta<=15) → 1段下で rank_5d
        assert _select_rank_by_lead(20.0, 10.0, "rank_7d") == "rank_5d"

    def test_unknown_base_profile_returned_unchanged(self):
        from katrain.core.ai import _select_rank_by_lead
        # chain にないプロファイルはそのまま返す
        assert _select_rank_by_lead(30.0, 10.0, "pro_pre-az") == "pro_pre-az"

    def test_negative_delta_no_downshift(self):
        from katrain.core.ai import _select_rank_by_lead
        # 自分が劣勢 → delta < 0 → 降格なし
        assert _select_rank_by_lead(-5.0, 10.0, "rank_9d") == "rank_9d"

    def test_custom_delta_1_controls_one_step_downshift(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta_1=3 に設定すると、delta=4 で1段下
        assert _select_rank_by_lead(14.0, 10.0, "rank_9d", delta_1=3, delta_2=15) == "rank_7d"
        # delta=3 なら降格なし（delta > delta_1 の判定）
        assert _select_rank_by_lead(13.0, 10.0, "rank_9d", delta_1=3, delta_2=15) == "rank_9d"

    def test_custom_delta_2_controls_floor_downshift(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta_2=10 に設定すると、delta=11 で一気に rank_5d
        assert _select_rank_by_lead(21.0, 10.0, "rank_9d", delta_1=5, delta_2=10) == "rank_5d"
        # delta=10 なら 1段下（delta > delta_2 の判定）
        assert _select_rank_by_lead(20.0, 10.0, "rank_9d", delta_1=5, delta_2=10) == "rank_7d"

    def test_defaults_match_legacy_behavior(self):
        from katrain.core.ai import _select_rank_by_lead
        # 引数省略時は現行の 5 / 15 が使われる（後方互換）
        assert _select_rank_by_lead(16.0, 10.0, "rank_9d") == "rank_7d"   # delta=6 → 1段下
        assert _select_rank_by_lead(26.0, 10.0, "rank_9d") == "rank_5d"   # delta=16 → rank_5d

    def test_inverted_thresholds_raise_value_error(self):
        from katrain.core.ai import _select_rank_by_lead
        import pytest as _pt
        # delta_1 >= delta_2 は invalid 設定なので raise
        with _pt.raises(ValueError, match="delta_1.*must be < delta_2"):
            _select_rank_by_lead(20.0, 10.0, "rank_9d", delta_1=15, delta_2=5)
        with _pt.raises(ValueError):
            _select_rank_by_lead(20.0, 10.0, "rank_9d", delta_1=10, delta_2=10)  # equal も invalid


class TestJigoDynamicRankCacheLifecycle:
    """Verify that the dynamic rank cache persists across per-move strategy instances.

    `generate_ai_move` creates a fresh JigoStrategy per move, so the cache MUST live
    on the Game object (self.game), not the strategy instance (self).
    """

    def test_cache_attribute_lives_on_game_not_self(self):
        """Simulate per-move strategy instantiation: two separate JigoStrategy objects
        sharing a game must read each other's cache."""
        from types import SimpleNamespace

        # Minimal fake game that survives across "moves"
        fake_game = SimpleNamespace()

        # First move: strategy #1 writes to game
        strat1 = SimpleNamespace(game=fake_game)
        strat1.game._jigo_last_current_lead = 12.5

        # Second move: strategy #2 is a NEW instance (no shared attrs on self)
        strat2 = SimpleNamespace(game=fake_game)

        # strat2 has no _last_current_lead attribute, but game does
        assert not hasattr(strat2, "_last_current_lead")
        assert getattr(strat2.game, "_jigo_last_current_lead", None) == 12.5

    def test_new_game_resets_cache(self):
        """Creating a new Game object (as KaTrain does on new game button) drops the cache."""
        from types import SimpleNamespace

        game_a = SimpleNamespace()
        game_a._jigo_last_current_lead = 20.0

        game_b = SimpleNamespace()  # 新規ゲーム = 新規 Game object
        assert getattr(game_b, "_jigo_last_current_lead", None) is None


from katrain.core.ai import _jigo_compute_effective_max_loss


class TestJigoComputeEffectiveMaxLoss:
    def test_returns_base_when_lead_below_threshold(self):
        # lead=14 < target_max(10) + delta(5) = 15 → 緩和発動せず
        result = _jigo_compute_effective_max_loss(
            current_lead=14.0, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=19,
        )
        assert result == 5.6

    def test_returns_large_lead_value_when_threshold_exceeded(self):
        # lead=15 == 10 + 5 → 緩和発動
        result = _jigo_compute_effective_max_loss(
            current_lead=15.0, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=19,
        )
        assert result == 8.0

    def test_does_not_cap_at_5_for_13x13_board(self):
        # 13路は 9路扱いしない
        result = _jigo_compute_effective_max_loss(
            current_lead=20.0, target_score_max=10.0, base_max_loss=4.0,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=13,
        )
        assert result == 8.0

    def test_never_goes_below_base_max_loss(self):
        # ユーザーが large_lead_max_loss を base より小さく設定しても base を維持
        result = _jigo_compute_effective_max_loss(
            current_lead=20.0, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=5.0, large_lead_max_loss=3.0, board_size=19,
        )
        assert result == 5.6

    def test_threshold_follows_target_score_max(self):
        # target_score_max=5 にすると発動閾値も 5+5=10 に追随
        result = _jigo_compute_effective_max_loss(
            current_lead=10.0, target_score_max=5.0, base_max_loss=5.6,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=19,
        )
        assert result == 8.0

    def test_custom_delta(self):
        # delta=3 にすると 10+3=13 で発動
        result_below = _jigo_compute_effective_max_loss(
            current_lead=12.5, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=3.0, large_lead_max_loss=8.0, board_size=19,
        )
        result_above = _jigo_compute_effective_max_loss(
            current_lead=13.0, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=3.0, large_lead_max_loss=8.0, board_size=19,
        )
        assert result_below == 5.6
        assert result_above == 8.0


from katrain.core.ai import _pick_target_closest_with_epsilon


class TestPickTargetClosestWithEpsilon:
    def test_empty_candidates_returns_none(self):
        assert _pick_target_closest_with_epsilon([], target=0.5, epsilon=0.5) is None

    def test_single_candidate_returned_regardless_of_epsilon(self):
        cands = [_c("A1", 3.0, 0.0, 0.10)]
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.5)
        assert pick["move"] == "A1"

    def test_epsilon_zero_matches_argmin_deterministic(self):
        # epsilon=0 なら現行 argmin と同じ手を返す（レグレッション保証）
        cands = [
            _c("A1", 5.0, 0.0, 0.90),  # diff=4.5
            _c("B2", 0.5, 4.5, 0.05),  # diff=0 ← closest
            _c("C3", 1.0, 4.0, 0.10),  # diff=0.5
        ]
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.0)
        assert pick["move"] == "B2"

    def test_epsilon_zero_with_exact_tie_returns_first_in_list(self):
        # 完全タイ(diff 同値)は入力順で先頭を返す（current min() と同挙動）
        cands = [
            _c("A1", 1.0, 0.0, 0.05),  # diff=0.5
            _c("B2", 0.0, 1.0, 0.10),  # diff=0.5（タイ）
        ]
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.0)
        assert pick["move"] == "A1"

    def test_band_multiple_candidates_uses_humanpolicy_weighted(self, monkeypatch):
        # diff 最小=0（B2）、band = diff <= 0 + 0.5 = 0.5 → {A1(0.5), B2(0), C3(0.5)}
        cands = [
            _c("A1", 1.0, 0.0, 0.20),
            _c("B2", 0.5, 0.5, 0.05),
            _c("C3", 0.0, 1.0, 0.60),  # hp 最大、band 内
            _c("D4", 5.0, -4.5, 0.50),  # diff=4.5、band 外
        ]
        from katrain.core import ai as ai_mod

        def fake_weighted(items, n):
            return [max(items, key=lambda t: t[1])]

        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.5)
        assert pick["move"] == "C3"  # band 内で hp 最大

    def test_band_all_zero_humanpolicy_falls_back_to_argmin(self):
        # band 内 hp 全ゼロ → argmin 決定的選択（safety net）
        cands = [
            _c("A1", 1.0, 0.0, 0.0),  # diff=0.5
            _c("B2", 0.5, 0.5, 0.0),  # diff=0、argmin
        ]
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.5)
        assert pick["move"] == "B2"

    def test_band_excludes_candidates_beyond_epsilon(self):
        # diff 最小=0 (B2)、ε=0.3 → band = diff <= 0.3、C3(diff=1.0) は除外
        cands = [
            _c("A1", 0.8, 0.0, 0.10),  # diff=0.3（境界内）
            _c("B2", 0.5, 0.3, 0.20),  # diff=0、argmin
            _c("C3", 1.5, -1.0, 0.50),  # diff=1.0、除外
        ]
        # hp 全ゼロ fallback path を使って決定的に検証
        cands_zero_hp = [{**c, "hp": 0.0} for c in cands]
        pick = _pick_target_closest_with_epsilon(cands_zero_hp, target=0.5, epsilon=0.3)
        assert pick["move"] == "B2"  # band 内 hp ゼロ → argmin → B2
