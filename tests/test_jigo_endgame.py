# tests/test_jigo_endgame.py
"""持碁モードのヨセ段階 HumanStyle 9段委譲のテスト（KataGo/Kivy 不要）。"""
import pytest

from katrain.core.ai import _jigo_endgame_handoff, _jigo_endgame_threshold


def _s(**kw):
    """チェックボックス ON の settings を作る。"""
    d = {"jigo_endgame_humanstyle": True}
    d.update(kw)
    return d


class TestEndgameThreshold:
    def test_19x19_uses_its_own_key(self):
        assert _jigo_endgame_threshold(19, {"jigo_endgame_move": 170}) == 170

    def test_13x13_uses_its_own_key(self):
        assert _jigo_endgame_threshold(13, {"jigo_endgame_move_13": 70}) == 70

    def test_9x9_uses_its_own_key(self):
        assert _jigo_endgame_threshold(9, {"jigo9_endgame_move": 26}) == 26

    def test_defaults_when_key_absent(self):
        assert _jigo_endgame_threshold(19, {}) == 150
        assert _jigo_endgame_threshold(13, {}) == 85
        assert _jigo_endgame_threshold(9, {}) == 30

    def test_float_slider_value_is_coerced_to_int(self):
        # GUI スライダーは float で保存される（~/.katrain/config.json 実測: 18.0 等）
        assert _jigo_endgame_threshold(19, {"jigo_endgame_move": 160.0}) == 160

    def test_unknown_board_falls_back_to_half_board_convention(self):
        # 他戦略と同じ ceil(0.5 x 盤面マス数)
        assert _jigo_endgame_threshold(15, {}) == 113


class TestEndgameHandoff:
    def test_disabled_never_hands_off(self):
        s = {"jigo_endgame_humanstyle": False, "jigo_endgame_move": 150}
        assert _jigo_endgame_handoff(19, 200, 10.0, 0.5, s) is False

    def test_disabled_ignores_sticky(self):
        s = {"jigo_endgame_humanstyle": False}
        assert _jigo_endgame_handoff(19, 200, 10.0, 0.5, s, sticky=True) is False

    def test_one_move_before_threshold_is_false(self):
        assert _jigo_endgame_handoff(19, 149, 5.0, 0.5, _s(jigo_endgame_move=150)) is False

    def test_exactly_at_threshold_is_true(self):
        assert _jigo_endgame_handoff(19, 150, 5.0, 0.5, _s(jigo_endgame_move=150)) is True

    def test_no_cached_lead_is_false(self):
        assert _jigo_endgame_handoff(19, 200, None, 0.5, _s(jigo_endgame_move=150)) is False

    def test_lead_below_target_is_false(self):
        assert _jigo_endgame_handoff(19, 200, 0.4, 0.5, _s(jigo_endgame_move=150)) is False

    def test_lead_equal_to_target_is_true(self):
        assert _jigo_endgame_handoff(19, 200, 0.5, 0.5, _s(jigo_endgame_move=150)) is True

    def test_sticky_ignores_move_number_and_lead(self):
        s = _s(jigo_endgame_move=150)
        assert _jigo_endgame_handoff(19, 10, -30.0, 0.5, s, sticky=True) is True

    def test_9x9_board_uses_9x9_key(self):
        s = _s(jigo9_endgame_move=30, jigo_endgame_move=150)
        assert _jigo_endgame_handoff(9, 29, 2.0, 0.5, s) is False
        assert _jigo_endgame_handoff(9, 30, 2.0, 0.5, s) is True
