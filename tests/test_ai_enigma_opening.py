# tests/test_ai_enigma_opening.py
"""難解（9/13/19路・難解＋）の序盤 HumanStyle 9段委譲 `enigma*_opening_humanstyle_moves` のテスト（KataGo/Kivy 不要）。

対局の手数 `cn.depth` がスライダー値未満の手番は難解さの選択パイプラインに入らず、
HumanStyle 9段（rank_9d・modern_style）としてそのまま打つ。0 で OFF。9路は既定 OFF。
"""

import types

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import (
    Enigma9Strategy,
    Enigma13Strategy,
    Enigma19Strategy,
    Enigma9PlusStrategy,
    Enigma13PlusStrategy,
    Enigma19PlusStrategy,
    enigma9_opening_handoff,
)
from katrain.core.sgf_parser import Move


class TestOpeningHandoffRule:
    def test_off_when_zero(self):
        assert enigma9_opening_handoff(0, 0) is False
        assert enigma9_opening_handoff(5, 0) is False

    def test_hands_off_while_depth_is_below_the_slider(self):
        assert enigma9_opening_handoff(0, 20) is True
        assert enigma9_opening_handoff(19, 20) is True

    def test_returns_to_enigma_at_the_slider_value(self):
        # 「20 手まで」＝対局の最初の 20 手（depth 0〜19）が 9 段。depth 20 からは難解
        assert enigma9_opening_handoff(20, 20) is False
        assert enigma9_opening_handoff(45, 20) is False

    def test_float_slider_value_is_coerced(self):
        assert enigma9_opening_handoff(19, 20.0) is True
        assert enigma9_opening_handoff(20, 20.0) is False


class TestDefaults:
    def test_9x9_is_off_and_13_19_default_to_20_moves(self):
        assert Enigma9Strategy.SETTING_DEFAULTS["opening_humanstyle_moves"] == 0
        assert Enigma13Strategy.SETTING_DEFAULTS["opening_humanstyle_moves"] == 20
        assert Enigma19Strategy.SETTING_DEFAULTS["opening_humanstyle_moves"] == 20

    def test_plus_mirrors_the_base(self):
        for plus, base in (
            (Enigma9PlusStrategy, Enigma9Strategy),
            (Enigma13PlusStrategy, Enigma13Strategy),
            (Enigma19PlusStrategy, Enigma19Strategy),
        ):
            assert (
                plus.SETTING_DEFAULTS["opening_humanstyle_moves"] == base.SETTING_DEFAULTS["opening_humanstyle_moves"]
            )


class _FakeHumanStyle:
    """HumanStyleStrategy の代役: 受け取った設定を記録し、固定の手を返す。"""

    instances = []

    def __init__(self, game, ai_settings):
        self.game = game
        self.settings = ai_settings
        _FakeHumanStyle.instances.append(self)

    def generate_move(self):
        return Move.from_gtp("D4", player=self.game.current_node.next_player), "human 9d move"


def _strategy(cls, *, depth, board_len, settings=None):
    logs = []
    katrain = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
    node = types.SimpleNamespace(
        next_player="W",
        player="B",
        depth=depth,
        move=None,
        analysis_complete=True,
        analysis={"root": {"scoreLead": -3.0}},
        candidate_moves=[
            {"move": "K10", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.55},
            {"move": "C3", "pointsLost": 0.5, "relativePointsLost": 0.5, "visits": 40, "winrate": 0.54},
        ],
    )
    game = types.SimpleNamespace(
        katrain=katrain,
        current_node=node,
        board_size=(board_len, board_len),
        board_watch_active=False,
    )
    s = cls(game, dict(settings or {}))
    s.queries = []
    s._run_query = lambda label, **kw: s.queries.append(label)
    s.probe_calls = []

    def probe(gtps, player, parent_hp=False):
        s.probe_calls.append(list(gtps))
        return {}, None  # humanSL 不在 → 最善手で終了

    s._probe_children = probe
    return s, logs


@pytest.fixture
def fake_humanstyle(monkeypatch):
    _FakeHumanStyle.instances = []
    monkeypatch.setattr(ai_module, "HumanStyleStrategy", _FakeHumanStyle)
    return _FakeHumanStyle


class TestOpeningHandoffEndToEnd:
    """_generate_move が序盤で本当に HumanStyle へ委譲する（呼び出し側の接続テスト）。"""

    def test_13x13_opening_move_is_played_by_humanstyle_9d(self, fake_humanstyle):
        s, logs = _strategy(Enigma13Strategy, depth=5, board_len=13)
        move, reason = s.generate_move()
        assert move.gtp() == "D4"
        assert reason.startswith("[Enigma13→9d opening]")
        assert len(fake_humanstyle.instances) == 1
        assert fake_humanstyle.instances[0].settings == {"human_kyu_rank": -8, "modern_style": True}
        assert s.probe_calls == []  # 難解さの採点に入らない
        assert s.queries == []
        assert any("Opening handoff" in m for m in logs)

    def test_plus_inherits_the_handoff(self, fake_humanstyle):
        s, logs = _strategy(Enigma13PlusStrategy, depth=19, board_len=13)
        move, reason = s.generate_move()
        assert move.gtp() == "D4"
        assert reason.startswith("[Enigma13Plus→9d opening]")

    def test_19x19_opening_move_is_played_by_humanstyle_9d(self, fake_humanstyle):
        s, logs = _strategy(Enigma19Strategy, depth=0, board_len=19)
        move, reason = s.generate_move()
        assert move.gtp() == "D4"
        assert len(fake_humanstyle.instances) == 1

    def test_at_the_slider_value_enigma_takes_over(self, fake_humanstyle):
        s, logs = _strategy(Enigma13Strategy, depth=20, board_len=13)
        move, reason = s.generate_move()
        assert fake_humanstyle.instances == []
        assert move.gtp() == "K10"  # 通常パイプライン（humanSL 不在 → 最善手）
        assert not any("Opening handoff" in m for m in logs)

    def test_slider_value_from_settings_overrides_the_default(self, fake_humanstyle):
        s, logs = _strategy(
            Enigma13Strategy, depth=25, board_len=13, settings={"enigma13_opening_humanstyle_moves": 30}
        )
        move, reason = s.generate_move()
        assert move.gtp() == "D4"
        assert len(fake_humanstyle.instances) == 1

    def test_zero_disables_the_handoff(self, fake_humanstyle):
        s, logs = _strategy(Enigma13Strategy, depth=0, board_len=13, settings={"enigma13_opening_humanstyle_moves": 0})
        move, reason = s.generate_move()
        assert fake_humanstyle.instances == []
        assert move.gtp() == "K10"

    def test_9x9_default_is_off(self, fake_humanstyle):
        s, logs = _strategy(Enigma9Strategy, depth=0, board_len=9)
        move, reason = s.generate_move()
        assert fake_humanstyle.instances == []
        assert move.gtp() == "K10"

    def test_wrong_board_size_still_plays_best_move_without_delegating(self, fake_humanstyle):
        # 盤サイズゲートが先＝13路版を 19 路で使っても 9 段には委譲せず従来どおり最善手
        s, logs = _strategy(Enigma13Strategy, depth=3, board_len=19)
        move, reason = s.generate_move()
        assert fake_humanstyle.instances == []
        assert move.gtp() == "K10"
