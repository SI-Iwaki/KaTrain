"""輪の難易度（board-watch spec 追記11）のための humanSL 先回り。守っているのは:
1. 条件が難解の親局面クエリと同一（9段・8visits・ownership なし）＝NN キャッシュを共有するだけ
2. 色分け ON × 監視中 × 次番が AI × リージョンなし のときだけ撃つ（どれかが偽ならクエリ 0 本＝従来とビット同一）
3. 同じノードには1本だけ（監視開始・新規対局・設定変更で何度呼ばれても）
4. 失敗・humanPolicy の無い応答でも例外を出さず、判定なし（普通の色）に倒れる
"""

import types

import pytest

from katrain.core.board_watch import apply_game_watch_flags, clear_game_watch_flags, ring_difficulty_enabled
from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN, PRIORITY_EXTRA_AI_QUERY
from katrain.core.game import BaseGame, Game, GameNode
from katrain.core.move_difficulty import RING_HP_PROFILE, RING_HP_VISITS
from katrain.core.sgf_parser import Move


class FakeEngine:
    def __init__(self):
        self.requests = []
        self.terminated = []

    def request_analysis(self, node, **kwargs):
        self.requests.append((node, kwargs))

    def terminate_queries(self, only_for_node=None, lock=True):
        self.terminated.append(only_for_node)


class FakeKatrain:
    def __init__(self, ai):
        human = "W" if ai == "B" else "B"
        self.players_info = {
            ai: types.SimpleNamespace(player_type=PLAYER_AI),
            human: types.SimpleNamespace(player_type=PLAYER_HUMAN),
        }

    def log(self, *args, **kwargs):
        pass


def _game(ai="W", ring=True, watch=True):
    """Game.play() を通せる素の Game（エンジン起動・解析スレッドなし）。ai は KaTrain の AI の色"""
    katrain = FakeKatrain(ai)
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": 9, "RU": "chinese", "KM": 7.0}))
    engine = FakeEngine()
    game = Game.__new__(Game)
    game.__dict__.update(base.__dict__)
    game.engines = {"B": engine, "W": engine}
    game.region_of_interest = None
    game.board_watch_active = watch
    game.ring_difficulty_active = ring
    game.board_watch_prefetch_replies = 0
    game.board_watch_probe_warm = False
    game._board_watch_prefetch_nodes = []
    game._region_prefetch_nodes = []
    game._early_speculation_nodes = []
    game._enigma_ponder_owner = None
    return game, engine


def ring_requests(engine):
    return [(n, kw) for n, kw in engine.requests if (kw.get("extra_settings") or {}).get("humanSLProfile")]


def test_opponent_move_fires_one_9d_humansl_query_for_the_ai_position():
    game, engine = _game(ai="W")
    node = game.play(Move.from_gtp("E5", player="B"))  # 相手（黒＝アプリ）の手 → 次番は AI（白）
    rings = ring_requests(engine)
    assert len(rings) == 1 and rings[0][0] is node
    kwargs = rings[0][1]
    assert kwargs["visits"] == RING_HP_VISITS and kwargs["include_policy"] is True and kwargs["ownership"] is False
    assert kwargs["extra_settings"] == {"humanSLProfile": RING_HP_PROFILE, "ignorePreRootHistory": False}
    assert kwargs["priority"] == PRIORITY_EXTRA_AI_QUERY
    assert len(engine.requests) == 2  # 通常解析はそのまま1本


def test_callback_stores_the_human_policy_and_tolerates_errors():
    game, engine = _game(ai="W")
    node = game.play(Move.from_gtp("E5", player="B"))
    kwargs = ring_requests(engine)[0][1]
    kwargs["error_callback"]({"error": "humanSL model missing"})  # 失敗しても例外にしない
    kwargs["callback"]({"rootInfo": {}}, False)  # humanPolicy の無い応答
    assert getattr(node, "ring_human_policy", None) is None
    kwargs["callback"]({"humanPolicy": [0.5] * 82}, True)  # 途中経過は使わない
    assert getattr(node, "ring_human_policy", None) is None
    kwargs["callback"]({"humanPolicy": [0.5] * 82}, False)
    assert node.ring_human_policy == [0.5] * 82


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ai": "W", "ring": False},  # 色分け OFF
        {"ai": "W", "watch": False},  # 監視していない
        {"ai": "B"},  # 次番（白）は人間＝AI の手番ではない
    ],
)
def test_no_query_unless_ring_on_and_watching_and_ai_to_move(kwargs):
    game, engine = _game(**kwargs)
    game.play(Move.from_gtp("E5", player="B"))
    assert ring_requests(engine) == []
    assert len(engine.requests) == 1  # 通常解析だけ＝従来どおり


def test_no_query_on_the_tsumego_region_path():
    game, engine = _game(ai="B")  # root は黒番＝AI の手番。止める理由がリージョンだけになるようにする
    game.region_of_interest = [0, 4, 0, 4]
    game._maybe_ring_hp_prefetch(game.current_node)
    assert ring_requests(engine) == []


def test_prefetch_is_idempotent_per_node():
    game, engine = _game(ai="B")  # root は黒番＝AI の手番
    game._maybe_ring_hp_prefetch(game.current_node)
    game._maybe_ring_hp_prefetch(game.current_node)
    assert len(ring_requests(engine)) == 1
    game2, engine2 = _game(ai="B")
    game2.current_node.ring_human_policy = [0.0] * 82  # 既に持っている
    game2._maybe_ring_hp_prefetch(game2.current_node)
    assert ring_requests(engine2) == []


def test_apply_game_watch_flags_turns_the_ring_on_and_fires_for_the_current_position_once():
    game, engine = _game(ai="B", ring=False)
    cfg = {"highlight_difficulty": True, "highlight_color": "magenta"}
    apply_game_watch_flags(game, cfg)
    apply_game_watch_flags(game, cfg)  # 監視開始のあと設定変更でも呼ばれる
    assert game.ring_difficulty_active is True
    assert len(ring_requests(engine)) == 1  # AI 黒番の初手（root）を拾う・同じノードに2本目は撃たない
    clear_game_watch_flags(game)
    assert game.ring_difficulty_active is False


def test_apply_game_watch_flags_keeps_the_ring_off_when_the_ring_is_hidden():
    game, engine = _game(ai="B", ring=False)
    apply_game_watch_flags(game, {"highlight_difficulty": True, "highlight_color": "off"})
    assert game.ring_difficulty_active is False and ring_requests(engine) == []


def test_ring_difficulty_enabled():
    assert ring_difficulty_enabled({"highlight_difficulty": True, "highlight_color": "cyan"}) is True
    assert ring_difficulty_enabled({"highlight_difficulty": True}) is True  # 色が無い＝既定の色で輪は出る
    assert ring_difficulty_enabled({"highlight_difficulty": True, "highlight_color": "off"}) is False
    assert ring_difficulty_enabled({"highlight_color": "cyan"}) is False
    assert ring_difficulty_enabled(None) is False
