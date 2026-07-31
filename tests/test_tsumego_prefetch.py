"""詰碁キャプチャの先読み（NN キャッシュ温め）の回帰テスト。

守っているのは3点:
1. **先読みクエリは ownership=True で撃つ** — KataGo の NN キャッシュは ownerMap の有無を
   区別するため、ownership なしの先読みは実クエリを1秒も速くしない（実測 2026-08-01
   prefetch_cache_probe.py: ownership なし先読み直後の実クエリ 2.70 秒＝コールド 2.69 秒、
   ownership 付きで温めた対照は 0.10〜0.28 秒）。`request_analysis` の next_move 指定は
   includeOwnership を強制 OFF にするので、使い捨ての複製ゲームの子ノードで撃つこと。
2. 先読みクエリは**複製ゲームの子ノード**に紐づく＝terminate が先読みだけに当たる
   （本譜ノードのクエリや GUI の追加解析を巻き込まない）。
3. 実クエリと同条件（visits・リージョン・低priority）で発行される。
"""

from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN, PRIORITY_REGION_PREFETCH
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
    players_info = {"B": FakeInfo(PLAYER_AI), "W": FakeInfo(PLAYER_HUMAN)}

    def log(self, *args, **kwargs):
        pass


def _prefetch_game():
    katrain = FakeKatrain()
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": 9, "RU": "japanese", "KM": 6.5}))
    base.play(Move.from_gtp("E5", player="B"), ignore_ko=True)  # AI 黒番が着手した直後の想定
    node = base.current_node
    node.analysis["root"] = {"scoreLead": 0.0, "winrate": 0.5, "visits": 100}
    node.analysis["moves"] = {
        gtp: {"move": gtp, "order": i, "scoreLead": 0.0, "winrate": 0.5, "visits": 100 - i, "pv": [gtp]}
        for i, gtp in enumerate(["E3", "C5", "G5"])
    }
    node.analysis["region_completed"] = True

    engine = FakeEngine()
    game = Game.__new__(Game)  # エンジン起動・解析スレッドを伴わない素の Game
    game.katrain = katrain
    game.engines = {"B": engine, "W": engine}
    game.root = base.root
    game.current_node = node
    game.region_of_interest = [2, 6, 2, 6]
    game.region_analysis_visits = 1800
    game.region_analysis_wide_root_noise = 0.04
    game.region_prefetch_replies = 2
    game._region_prefetch_nodes = []
    return game, node, engine


def test_prefetch_fires_ownership_queries_on_throwaway_child_nodes():
    game, node, engine = _prefetch_game()
    game._region_prefetch_worker(node, 2)
    assert len(engine.requests) == 2  # top-K=2 の応手ぶん
    for child, kwargs in engine.requests:
        # ownership を実クエリと揃えないと NN キャッシュが温まらない（docstring の実測参照）
        assert kwargs["ownership"] is True
        assert kwargs["visits"] == 1800
        assert kwargs["region_of_interest"] == [2, 6, 2, 6]
        assert kwargs["priority"] == PRIORITY_REGION_PREFETCH
        # 本譜のノードではなく複製ゲームの子ノに撃つ（terminate の的を分離するため）
        assert child is not node
        assert child.parent is not node
    fired_moves = {child.move.gtp() for child, _ in engine.requests}
    assert fired_moves == {"E3", "C5"}  # visits 降順 top-2


def test_cancel_terminates_exactly_the_prefetch_nodes():
    game, node, engine = _prefetch_game()
    game._region_prefetch_worker(node, 2)
    prefetch_nodes = [child for child, _ in engine.requests]
    assert game._region_prefetch_nodes == prefetch_nodes
    game._cancel_region_prefetch()
    assert engine.terminated == prefetch_nodes  # 本譜ノードは terminate されない
    assert game._region_prefetch_nodes == []
    game._cancel_region_prefetch()
    assert engine.terminated == prefetch_nodes  # 二重 cancel は no-op


def test_prefetch_skips_when_next_player_is_ai():
    game, node, engine = _prefetch_game()
    game.katrain.players_info = {"B": FakeInfo(PLAYER_AI), "W": FakeInfo(PLAYER_AI)}
    game._maybe_region_prefetch(node)  # 次番が AI（人間の考慮時間が無い）なら発火しない
    assert engine.requests == []


def test_prefetch_skips_without_players_info():
    game, node, engine = _prefetch_game()
    game.katrain.players_info = None  # デバッグスタブ相当
    game._maybe_region_prefetch(node)
    assert engine.requests == []
