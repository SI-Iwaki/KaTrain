# tests/test_jigo9.py
"""Jigo9Strategy の FORCED_SETTINGS / _jigo_get 無効化機構のユニットテスト"""
from katrain.core.ai import JigoStrategy


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
