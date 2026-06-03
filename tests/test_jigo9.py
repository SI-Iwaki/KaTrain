# tests/test_jigo9.py
"""Jigo9Strategy の FORCED_SETTINGS / _jigo_get 無効化機構のユニットテスト"""
from katrain.core.ai import JigoStrategy, Jigo9Strategy


def _bare(cls, settings):
    """engine/game なしで _jigo_get だけ検証する軽量インスタンスを作る"""
    obj = cls.__new__(cls)
    obj.settings = settings
    return obj


class TestJigoGetBase:
    """基底 JigoStrategy は FORCED_SETTINGS 空 → settings をそのまま返す"""

    def test_returns_settings_value(self):
        obj = _bare(JigoStrategy, {"jigo_equivalent_epsilon": 0.7})
        assert obj._jigo_get("jigo_equivalent_epsilon", 0.5) == 0.7

    def test_returns_default_when_missing(self):
        obj = _bare(JigoStrategy, {})
        assert obj._jigo_get("jigo_equivalent_epsilon", 0.5) == 0.5

    def test_base_forced_settings_is_empty(self):
        assert JigoStrategy.FORCED_SETTINGS == {}


class TestJigo9Forced:
    """Jigo9Strategy は FORCED_SETTINGS で4設定を無効化値に固定"""

    def test_epsilon_forced_to_zero(self):
        obj = _bare(Jigo9Strategy, {"jigo_equivalent_epsilon": 0.7})
        assert obj._jigo_get("jigo_equivalent_epsilon", 0.5) == 0.0

    def test_large_lead_delta_forced_to_inf(self):
        obj = _bare(Jigo9Strategy, {"jigo_large_lead_delta": 5.0})
        assert obj._jigo_get("jigo_large_lead_delta", 5.0) == float("inf")

    def test_dynamic_rank_forced_false(self):
        obj = _bare(Jigo9Strategy, {"jigo_dynamic_rank": True})
        assert obj._jigo_get("jigo_dynamic_rank", False) is False

    def test_human_profile_forced_9d(self):
        obj = _bare(Jigo9Strategy, {"human_profile": "rank_5d"})
        assert obj._jigo_get("human_profile", "rank_9d") == "rank_9d"

    def test_non_forced_key_passes_through(self):
        obj = _bare(Jigo9Strategy, {"max_loss_per_move": 4.0})
        assert obj._jigo_get("max_loss_per_move", 3.3) == 4.0
