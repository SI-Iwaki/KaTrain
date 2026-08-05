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


# ---------------------------------------------------------------------------
# 委譲の配線テスト（フェイクの game/katrain。KataGo エンジンは起動しない）
# ---------------------------------------------------------------------------


class _ReachedStage1(Exception):
    """委譲されずに通常経路（Stage1 クエリ）へ進んだことを示すセンチネル。"""


class _NoEngines(dict):
    def __getitem__(self, key):
        raise _ReachedStage1(key)


class FakeKatrain:
    def __init__(self):
        self.logs = []

    def log(self, msg, level=None):
        self.logs.append(str(msg))


class FakeNode:
    def __init__(self, depth):
        self.depth = depth
        self.analysis_complete = True
        self.next_player = "B"
        self.player = "W"

    def player_sign(self, player):
        # GameNode.player_sign と同じ規約。委譲されなかった経路が
        # self.game.engines に触れるところまで進めるために必要
        return 1 if player == "B" else -1


class FakeGame:
    def __init__(self, depth, board_size=(19, 19)):
        self.board_size = board_size
        self.current_node = FakeNode(depth)
        self.katrain = FakeKatrain()
        self.engines = _NoEngines()


def _patch_humanstyle(monkeypatch, captured):
    """HumanStyleStrategy.generate_move を差し替えてエンジン呼び出しを避ける。"""
    from katrain.core import ai as ai_mod
    from katrain.core.sgf_parser import Move

    def fake_generate(self):
        captured["settings"] = self.settings
        return Move((3, 3), player="B"), "stub thoughts"

    monkeypatch.setattr(ai_mod.HumanStyleStrategy, "generate_move", fake_generate)
    return ai_mod


def test_generate_move_delegates_to_humanstyle_9d(monkeypatch):
    captured = {}
    ai_mod = _patch_humanstyle(monkeypatch, captured)

    game = FakeGame(depth=200)
    game._jigo_last_current_lead = 2.0
    settings = {"jigo_endgame_humanstyle": True, "jigo_endgame_move": 150, "target_score": 0.5}
    strategy = ai_mod.JigoStrategy(game, settings)

    move, thoughts = strategy.generate_move()

    assert move.gtp() == "D4"
    assert thoughts.startswith("[Jigo→9d yose]")
    assert captured["settings"] == {"human_kyu_rank": -8, "modern_style": True}
    assert game._jigo_endgame_handoff is True
    assert strategy.last_decision_info["endgame_handoff"] is True
    assert strategy.last_decision_info["rank_used"] == "rank_9d"
    assert any("Endgame handoff" in line for line in game.katrain.logs)


def test_generate_move_stays_in_jigo_while_behind(monkeypatch):
    captured = {}
    ai_mod = _patch_humanstyle(monkeypatch, captured)

    game = FakeGame(depth=200)
    game._jigo_last_current_lead = -1.0  # target 未到達
    settings = {"jigo_endgame_humanstyle": True, "jigo_endgame_move": 150, "target_score": 0.5}
    strategy = ai_mod.JigoStrategy(game, settings)

    # 委譲されず通常経路へ進み、エンジン参照でセンチネルが飛ぶ
    with pytest.raises(_ReachedStage1):
        strategy.generate_move()

    assert "settings" not in captured
    assert getattr(game, "_jigo_endgame_handoff", False) is False
    assert any("Endgame pending" in line for line in game.katrain.logs)


def test_generate_move_sticky_delegates_even_before_threshold(monkeypatch):
    captured = {}
    ai_mod = _patch_humanstyle(monkeypatch, captured)

    game = FakeGame(depth=20)
    game._jigo_last_current_lead = -30.0
    game._jigo_endgame_handoff = True  # 既に委譲済み
    settings = {"jigo_endgame_humanstyle": True, "jigo_endgame_move": 150, "target_score": 0.5}
    strategy = ai_mod.JigoStrategy(game, settings)

    move, thoughts = strategy.generate_move()

    assert thoughts.startswith("[Jigo→9d yose]")
    assert any("sticky" in line for line in game.katrain.logs)


def test_generate_move_ignores_option_when_disabled(monkeypatch):
    captured = {}
    ai_mod = _patch_humanstyle(monkeypatch, captured)

    game = FakeGame(depth=250)
    game._jigo_last_current_lead = 30.0
    settings = {"jigo_endgame_humanstyle": False, "target_score": 0.5}
    strategy = ai_mod.JigoStrategy(game, settings)

    with pytest.raises(_ReachedStage1):
        strategy.generate_move()

    assert "settings" not in captured
    assert not any("Endgame" in line for line in game.katrain.logs)
