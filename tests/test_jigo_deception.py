# tests/test_jigo_deception.py
"""Jigo deception Phase 解決のユニットテスト"""
import pytest

from katrain.core.ai import (
    JIGO_DECEPTION_PHASE_TABLE,
    JIGO_DECEPTION_TARGETS,
    JIGO_DECEPTION_SAFETY_OVERSHOOT,
    _jigo_resolve_phase,
    _jigo_resolve_13path_overrides,  # 新規
)


class TestJigoPhaseBoundaries19:
    """19 路盤の手数ベース phase 境界"""

    def test_move_1_is_phase0(self):
        assert _jigo_resolve_phase(19, 1, None) == "phase0"

    def test_move_29_is_phase0(self):
        assert _jigo_resolve_phase(19, 29, None) == "phase0"

    def test_move_30_is_phase1(self):
        assert _jigo_resolve_phase(19, 30, None) == "phase1"

    def test_move_79_is_phase1(self):
        assert _jigo_resolve_phase(19, 79, None) == "phase1"

    def test_move_80_is_phase2(self):
        assert _jigo_resolve_phase(19, 80, None) == "phase2"

    def test_move_149_is_phase2(self):
        assert _jigo_resolve_phase(19, 149, None) == "phase2"

    def test_move_150_is_phase3(self):
        assert _jigo_resolve_phase(19, 150, None) == "phase3"

    def test_move_250_is_phase3(self):
        assert _jigo_resolve_phase(19, 250, None) == "phase3"


class TestJigoPhaseBoundaries13:
    """13 路盤の手数ベース phase 境界"""

    def test_move_16_is_phase0(self):
        assert _jigo_resolve_phase(13, 16, None) == "phase0"

    def test_move_17_is_phase1(self):
        assert _jigo_resolve_phase(13, 17, None) == "phase1"

    def test_move_44_is_phase2(self):
        assert _jigo_resolve_phase(13, 44, None) == "phase2"

    def test_move_83_is_phase3(self):
        assert _jigo_resolve_phase(13, 83, None) == "phase3"


class TestJigoPhaseBoundaries9:
    """9 路盤の手数ベース phase 境界"""

    def test_move_7_is_phase0(self):
        assert _jigo_resolve_phase(9, 7, None) == "phase0"

    def test_move_8_is_phase1(self):
        assert _jigo_resolve_phase(9, 8, None) == "phase1"

    def test_move_20_is_phase2(self):
        assert _jigo_resolve_phase(9, 20, None) == "phase2"

    def test_move_38_is_phase3(self):
        assert _jigo_resolve_phase(9, 38, None) == "phase3"


class TestJigoSafetyValve:
    """安全弁: ±5 目で phase3 ジャンプ"""

    def test_phase1_overshoot_jumps_to_phase3(self):
        # 19路 phase1 target_max=-2.0、+5 超過 → lead > 3.0 で phase3
        assert _jigo_resolve_phase(19, 30, current_lead=3.5) == "phase3"

    def test_phase1_undershoot_jumps_to_phase3(self):
        # 19路 phase1 target_max=-2.0、-5 不足 → lead < -7.0 で phase3
        assert _jigo_resolve_phase(19, 30, current_lead=-7.5) == "phase3"

    def test_phase1_in_range_stays(self):
        # lead が ±5 目以内なら phase1 維持
        assert _jigo_resolve_phase(19, 30, current_lead=0.0) == "phase1"
        assert _jigo_resolve_phase(19, 30, current_lead=-4.0) == "phase1"

    def test_phase2_overshoot_jumps_to_phase3(self):
        # 19路 phase2 target_max=-0.5、+5 超過 → lead > 4.5 で phase3
        assert _jigo_resolve_phase(19, 80, current_lead=5.0) == "phase3"

    def test_phase2_undershoot_jumps_to_phase3(self):
        # 19路 phase2 target_max=-0.5、-5 不足 → lead < -5.5 で phase3
        assert _jigo_resolve_phase(19, 80, current_lead=-6.0) == "phase3"

    def test_phase0_no_safety_valve(self):
        # phase0 は安全弁発動しない（巨大 lead でも phase0 維持）
        assert _jigo_resolve_phase(19, 10, current_lead=100.0) == "phase0"
        assert _jigo_resolve_phase(19, 10, current_lead=-100.0) == "phase0"

    def test_phase3_no_safety_valve(self):
        # phase3 は終局フェーズ、lead 変動で再ジャンプしない
        assert _jigo_resolve_phase(19, 200, current_lead=100.0) == "phase3"
        assert _jigo_resolve_phase(19, 200, current_lead=-100.0) == "phase3"

    def test_last_lead_none_skips_safety_valve(self):
        # 初手や lead 未取得時は安全弁スキップ
        assert _jigo_resolve_phase(19, 30, current_lead=None) == "phase1"


class TestJigoUnknownBoardSize:
    """未対応盤面サイズは 19 路にフォールバック"""

    def test_board_size_15_falls_back_to_19(self):
        assert _jigo_resolve_phase(15, 30, None) == "phase1"
        assert _jigo_resolve_phase(15, 150, None) == "phase3"

    def test_board_size_7_falls_back_to_19(self):
        # 7 路の 30 手目 → 19 路テーブルで phase1
        assert _jigo_resolve_phase(7, 30, None) == "phase1"


class TestJigoDeceptionTargetsLookup:
    """JIGO_DECEPTION_TARGETS の中身検証"""

    def test_19_phase0_is_none(self):
        assert JIGO_DECEPTION_TARGETS[(19, "phase0")] is None

    def test_19_phase1_targets(self):
        assert JIGO_DECEPTION_TARGETS[(19, "phase1")] == (-3.0, -2.0)

    def test_19_phase2_targets(self):
        assert JIGO_DECEPTION_TARGETS[(19, "phase2")] == (-1.5, -0.5)

    def test_19_phase3_is_none(self):
        assert JIGO_DECEPTION_TARGETS[(19, "phase3")] is None

    def test_13_phase1_targets(self):
        assert JIGO_DECEPTION_TARGETS[(13, "phase1")] == (-2.0, -1.0)

    def test_13_phase2_targets(self):
        assert JIGO_DECEPTION_TARGETS[(13, "phase2")] == (-1.0, 0.0)

    def test_9_phase1_targets(self):
        assert JIGO_DECEPTION_TARGETS[(9, "phase1")] == (-1.5, -0.5)

    def test_9_phase2_targets(self):
        assert JIGO_DECEPTION_TARGETS[(9, "phase2")] == (-0.5, 0.0)

    def test_safety_overshoot_value(self):
        assert JIGO_DECEPTION_SAFETY_OVERSHOOT == 5.0


class TestJigoPhaseTableStructure:
    """JIGO_DECEPTION_PHASE_TABLE の構造検証"""

    def test_19_has_three_phases(self):
        assert len(JIGO_DECEPTION_PHASE_TABLE[19]) == 3

    def test_19_boundaries(self):
        assert JIGO_DECEPTION_PHASE_TABLE[19] == [
            (30, "phase1"), (80, "phase2"), (150, "phase3"),
        ]

    def test_13_boundaries(self):
        assert JIGO_DECEPTION_PHASE_TABLE[13] == [
            (17, "phase1"), (44, "phase2"), (83, "phase3"),
        ]

    def test_9_boundaries(self):
        assert JIGO_DECEPTION_PHASE_TABLE[9] == [
            (8, "phase1"), (20, "phase2"), (38, "phase3"),
        ]


class TestJigoPhaseTableOverride:
    """phase_table_override 引数で境界手数をカスタマイズ"""

    def test_override_replaces_default_table(self):
        # Override で 13路の boundaries を 10/40/100 に変更
        override = [(10, "phase1"), (40, "phase2"), (100, "phase3")]
        # 手数 9 は phase0、10 は phase1
        assert _jigo_resolve_phase(13, 9, None, phase_table_override=override) == "phase0"
        assert _jigo_resolve_phase(13, 10, None, phase_table_override=override) == "phase1"
        # 手数 50 は phase2 (40 <= 50 < 100)
        assert _jigo_resolve_phase(13, 50, None, phase_table_override=override) == "phase2"
        # 手数 100 は phase3
        assert _jigo_resolve_phase(13, 100, None, phase_table_override=override) == "phase3"

    def test_override_none_uses_default_table(self):
        # phase_table_override=None なら既存挙動（17/44/83）
        assert _jigo_resolve_phase(13, 17, None, phase_table_override=None) == "phase1"
        assert _jigo_resolve_phase(13, 44, None, phase_table_override=None) == "phase2"

    def test_order_disorder_no_exception(self):
        # 順序矛盾でも例外なし、ループの「最後にマッチ」が勝つ
        override = [(35, "phase1"), (30, "phase2"), (110, "phase3")]
        # 手数 31: phase1 boundary=35 は False、phase2 boundary=30 は True → phase2
        assert _jigo_resolve_phase(13, 31, None, phase_table_override=override) == "phase2"
        # 手数 36: phase1=True で base=phase1、続けて phase2=True で base=phase2
        assert _jigo_resolve_phase(13, 36, None, phase_table_override=override) == "phase2"


class TestJigoTargetOverrides:
    """target_overrides 引数で安全弁の target_max をカスタマイズ"""

    def test_safety_uses_override_target_max_overshoot(self):
        # Phase 1 で override target_max=-1.0、lead=+5.0 → +5.0 > -1.0 + 5.0 (=4.0)
        # → 過剰優勢で phase3 にジャンプ
        targets = {"phase1": (-2.0, -1.0), "phase2": (-1.0, 0.0)}
        result = _jigo_resolve_phase(13, 20, +5.0, target_overrides=targets)
        assert result == "phase3"

    def test_safety_uses_override_target_max_undershoot(self):
        # Phase 2 で override target_max=0.0、lead=-6.0 → -6.0 < 0.0 - 5.0 (=-5.0)
        # → 過剰劣勢で phase3 にジャンプ
        targets = {"phase1": (-2.0, -1.0), "phase2": (-1.0, 0.0)}
        result = _jigo_resolve_phase(13, 50, -6.0, target_overrides=targets)
        assert result == "phase3"

    def test_safety_within_band_keeps_phase(self):
        # Override target_max=-1.0、lead=+2.0 → 2.0 ≤ -1.0 + 5.0 (=4.0)、phase1 維持
        targets = {"phase1": (-2.0, -1.0), "phase2": (-1.0, 0.0)}
        result = _jigo_resolve_phase(13, 20, +2.0, target_overrides=targets)
        assert result == "phase1"

    def test_target_overrides_none_uses_default_targets(self):
        # target_overrides=None なら既存 JIGO_DECEPTION_TARGETS で判定
        # 13路 phase1 default target_max=-1.0、lead=+5.0 → +5.0 > -1.0+5.0=+4.0 → phase3
        result = _jigo_resolve_phase(13, 17, +5.0, target_overrides=None)
        assert result == "phase3"


class TestJigo13PathOverrides:
    """_jigo_resolve_13path_overrides の挙動"""

    def test_phase0_passthrough(self):
        # phase0 は default をそのまま返す
        result = _jigo_resolve_13path_overrides("phase0", -3.0, -2.0, {})
        assert result == (-3.0, -2.0)

    def test_phase3_passthrough(self):
        # phase3 も default をそのまま返す
        result = _jigo_resolve_13path_overrides("phase3", 0.5, 10.0, {})
        assert result == (0.5, 10.0)

    def test_phase1_uses_setting(self):
        # phase1 で settings から target を読む、target_max は target+1.0
        settings = {"jigo_deception_13_phase1_target": -3.0}
        result = _jigo_resolve_13path_overrides("phase1", 0.0, 0.0, settings)
        assert result == (-3.0, -2.0)

    def test_phase2_uses_setting(self):
        # phase2 で settings から target を読む
        settings = {"jigo_deception_13_phase2_target": -0.5}
        result = _jigo_resolve_13path_overrides("phase2", 0.0, 0.0, settings)
        assert result == (-0.5, 0.5)

    def test_phase1_setting_missing_uses_default(self):
        # settings に該当キーがなければ default 値 -2.0 を使う
        result = _jigo_resolve_13path_overrides("phase1", 0.0, 0.0, {})
        assert result == (-2.0, -1.0)

    def test_phase2_setting_missing_uses_default(self):
        # settings に該当キーがなければ default 値 -1.0 を使う
        result = _jigo_resolve_13path_overrides("phase2", 0.0, 0.0, {})
        assert result == (-1.0, 0.0)
