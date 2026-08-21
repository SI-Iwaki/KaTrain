"""盤面監視モードの応手先読み（NN キャッシュ温め）の回帰テスト。

守っているのは4点:
1. **クエリ条件が実クエリと同一** — 通常対局の実クエリは `node.analyze(engine)` の既定
   （visits=None＝config の max_visits、ownership=None＝engine の既定、リージョンなし）。
   条件がずれると NN キャッシュが温まらない（詰碁で ownership を揃えなかったときの実測:
   先読み直後の実クエリ 2.70 秒＝コールドと同一）。
2. 先読みクエリは**複製ゲームの子ノード**に紐づく＝terminate が先読みだけに当たる。
3. 相手（アプリ側＝KaTrain 上の人間）の手番でだけ発火する。AI の手番＝相手は考えていない。
4. 相手の着手が入った瞬間に未消化分を打ち切る。**これを怠ると実クエリと GPU を取り合って
   逆に遅くなる**（難解戦略で 1.6→4.4 秒に悪化した実測がある既知の罠）。

実測の payoff（2026-08-22・9路 2000visits・別プロセス2回）: 相手の着手が入った局面の解析が
先読みなし 1029ms → 的中時 108/113ms。的中率は実対局134局面で top-3 58.2% / top-5 68.7%。
"""

from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN, PRIORITY_BOARD_WATCH_PREFETCH
from katrain.core.game import BaseGame, Game, GameNode
from katrain.core.sgf_parser import Move


class FakeEngine:
    def __init__(self):
        self.requests = []
        self.terminated = []

    def request_analysis(self, node, **kwargs):
        self.requests.append((node, kwargs))

    def terminate_queries(self, only_for_node=None, lock=True):
        self.terminated.append(only_for_node)


class FakeInfo:
    def __init__(self, player_type):
        self.player_type = player_type


class FakeKatrain:
    def __init__(self):
        self.players_info = {"B": FakeInfo(PLAYER_AI), "W": FakeInfo(PLAYER_HUMAN)}
        self.logs = []

    def log(self, msg, *args, **kwargs):
        self.logs.append(msg)


def _watch_game(replies=5, candidates=("E3", "C5", "G5", "F7", "B2", "H8")):
    """KaTrain の AI（黒）が着手し終わり、相手（白＝アプリ）の手番になった直後の局面"""
    katrain = FakeKatrain()
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": 9, "RU": "chinese", "KM": 7.0}))
    base.play(Move.from_gtp("E5", player="B"), ignore_ko=True)
    node = base.current_node
    node.analysis["root"] = {"scoreLead": 0.0, "winrate": 0.5, "visits": 2000}
    node.analysis["moves"] = {
        gtp: {"move": gtp, "order": i, "scoreLead": 0.0, "winrate": 0.5, "visits": 500 - i * 10, "pv": [gtp]}
        for i, gtp in enumerate(candidates)
    }
    node.analysis["completed"] = True

    engine = FakeEngine()
    game = Game.__new__(Game)  # エンジン起動・解析スレッドを伴わない素の Game
    game.katrain = katrain
    game.engines = {"B": engine, "W": engine}
    game.root = base.root
    game.current_node = node
    game.region_of_interest = None
    game.board_watch_prefetch_replies = replies
    game._board_watch_prefetch_nodes = []
    return game, node, engine


def test_prefetch_fires_top_k_children_with_same_settings_as_the_real_query():
    game, node, engine = _watch_game(replies=5)
    game._board_watch_prefetch_worker(node, 5)
    assert len(engine.requests) == 5  # K=5 で打ち切る（限界効率が落ちるため。spec 追記4）
    for child, kwargs in engine.requests:
        # 実クエリ（node.analyze(engine) の既定）と同条件でなければ NN キャッシュが温まらない
        assert kwargs["visits"] is None          # = config の max_visits
        assert kwargs["ownership"] is None       # = engine の既定（_enable_ownership）
        assert kwargs["region_of_interest"] is None
        assert kwargs["priority"] == PRIORITY_BOARD_WATCH_PREFETCH
        # 本譜のノードではなく複製ゲームの子ノードに撃つ（terminate の的を分離するため）
        assert child is not node
        assert child.parent is not node
    assert {child.move.gtp() for child, _ in engine.requests} == {"E3", "C5", "G5", "F7", "B2"}


def test_prefetch_children_are_played_by_the_opponent_color():
    game, node, engine = _watch_game(replies=2)
    game._board_watch_prefetch_worker(node, 2)
    assert {child.move.player for child, _ in engine.requests} == {"W"}


def test_prefetch_respects_the_reply_cap():
    game, node, engine = _watch_game(replies=2)
    game._board_watch_prefetch_worker(node, 2)
    assert {child.move.gtp() for child, _ in engine.requests} == {"E3", "C5"}  # visits 降順 top-2


def test_prefetch_skips_pass():
    game, node, engine = _watch_game(replies=3, candidates=("E3", "pass", "C5", "G5"))
    game._board_watch_prefetch_worker(node, 3)
    assert "pass" not in {child.move.gtp() for child, _ in engine.requests}


def test_cancel_terminates_exactly_the_prefetch_nodes():
    game, node, engine = _watch_game(replies=2)
    game._board_watch_prefetch_worker(node, 2)
    prefetch_nodes = [child for child, _ in engine.requests]
    assert game._board_watch_prefetch_nodes == prefetch_nodes
    game._cancel_board_watch_prefetch()
    assert engine.terminated == prefetch_nodes  # 本譜ノードは terminate されない
    assert game._board_watch_prefetch_nodes == []
    game._cancel_board_watch_prefetch()
    assert engine.terminated == prefetch_nodes  # 二重 cancel は no-op


def test_prefetch_skips_when_next_player_is_ai():
    """相手の着手が入った直後（次番＝KaTrain の AI）は相手が考えていないので温めない"""
    game, node, engine = _watch_game()
    game.katrain.players_info = {"B": FakeInfo(PLAYER_AI), "W": FakeInfo(PLAYER_AI)}
    game._maybe_board_watch_prefetch(node)
    assert engine.requests == []


def test_prefetch_disabled_by_zero_replies():
    game, node, engine = _watch_game(replies=0)
    game._maybe_board_watch_prefetch(node)
    assert engine.requests == []


def test_prefetch_skips_without_players_info():
    game, node, engine = _watch_game()
    game.katrain.players_info = None  # デバッグスタブ相当
    game._maybe_board_watch_prefetch(node)
    assert engine.requests == []


def test_prefetch_skips_when_a_region_is_active():
    """詰碁経路（リージョンあり）は既存の _maybe_region_prefetch の担当。二重発火させない"""
    game, node, engine = _watch_game()
    game.region_of_interest = [2, 6, 2, 6]
    game._maybe_board_watch_prefetch(node)
    assert engine.requests == []


def test_worker_bails_when_opponent_already_moved():
    game, node, engine = _watch_game(replies=3)
    game.current_node = GameNode()  # 先読みを組み立てる前に局面が進んだ
    game._board_watch_prefetch_worker(node, 3)
    assert engine.requests == []
