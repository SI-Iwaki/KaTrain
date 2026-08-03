"""段階3（root部分結果からの前倒し投機）ウォッチャの回帰テスト。

守っているのは4点:
1. 発火は次番が AI かつ strategy が ai:tsumego のときだけ（人間番の先読み prefetch と鏡像）
2. 温めクエリは実クエリと同一条件（ownership=True・gain_verify_visits・優先度500・複製ゲームの子ノード）
3. 掃除（_cancel_early_speculation）はウォッチャの子ノードだけを terminate する
4. region 完了済み・閾値未達では発火しない
"""
import threading
import time

from katrain.core.constants import AI_TSUMEGO, PLAYER_AI, PLAYER_HUMAN, PRIORITY_TSUMEGO_SPECULATION
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
    def __init__(self, player_type, strategy=None):
        self.player_type = player_type
        self.strategy = strategy


class FakeKatrain:
    players_info = {"B": FakeInfo(PLAYER_AI, AI_TSUMEGO), "W": FakeInfo(PLAYER_HUMAN)}

    def __init__(self, ai_settings=None):
        self._ai_settings = ai_settings or {}

    def config(self, path, default=None):
        if path == f"ai/{AI_TSUMEGO}":
            return self._ai_settings
        return default

    def log(self, *args, **kwargs):
        pass


BOARD = 13


def _own(cells):
    grid = [0.0] * (BOARD * BOARD)
    for (x, y), v in cells.items():
        grid[(BOARD - 1 - y) * BOARD + x] = v
    return grid


def _early_game(visits_now=1500, region_completed=False):
    """白が打った直後・黒(AI)番のノードに、閾値相当の部分解析が載った状態を作る"""
    katrain = FakeKatrain()
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": BOARD, "RU": "japanese", "KM": 6.5}))
    base.play(Move.from_gtp("D4", player="W"), ignore_ko=True)
    node = base.current_node  # 次番 = B = AI
    node.analysis["root"] = {"scoreLead": 0.0, "winrate": 0.5, "visits": 300}
    node.analysis["moves"] = {
        gtp: {
            "move": gtp, "order": i, "scoreLead": [0.0, -0.1][i], "winrate": 0.5,
            "visits": [visits_now - 400, 400][i], "pv": [gtp],
            "ownership": _own({(3, 3): [0.9, 0.1][i]}),
        }
        for i, gtp in enumerate(["C3", "E5"])
    }
    node.analysis["ownership"] = _own({})
    node.analysis["region_completed"] = region_completed

    engine = FakeEngine()
    game = Game.__new__(Game)  # エンジン起動・解析スレッドを伴わない素の Game
    game.katrain = katrain
    game.engines = {"B": engine, "W": engine}
    game.root = base.root
    game.current_node = node
    game.region_of_interest = [2, 6, 2, 6]
    game.region_analysis_visits = 1800
    game.region_analysis_wide_root_noise = 0.04
    # Game.__new__(Game) は BaseGame.__init__ を経由しないため、self.stones プロパティ
    # （_early_speculation_worker が使う）が要求する _lock / chains を持たない。
    # 既にD4を打った base の実ゲームからそのまま借用する（本体側は変えない）
    game._lock = base._lock
    game.chains = base.chains
    game._early_speculation_nodes = []
    return game, node, engine


def test_worker_fires_exact_conditions_at_threshold():
    game, node, engine = _early_game(visits_now=1500)  # 1500 >= 0.35*1800=630
    game._early_speculation_worker(node)
    assert engine.requests, "閾値到達で発火するはず"
    for child, kw in engine.requests:
        assert kw["ownership"] is True
        assert kw["visits"] == 800  # gain_verify_visits 既定
        assert kw["region_of_interest"] == [2, 6, 2, 6]
        assert kw["priority"] == PRIORITY_TSUMEGO_SPECULATION
        assert child is not node and child.parent is not node  # 複製ゲームの子ノード
    fired = {child.move.gtp() for child, _ in engine.requests}
    assert "C3" in fired  # 仮 chosen の検証バッチ温めが含まれる
    assert game._early_speculation_nodes == [c for c, _ in engine.requests]


def test_worker_does_not_fire_when_region_completed():
    game, node, engine = _early_game(visits_now=1500, region_completed=True)
    game._early_speculation_worker(node)
    assert engine.requests == []  # 完了済み＝段階1+2に委ねる


def test_worker_does_not_fire_below_threshold():
    """閾値未達では発火しないことを、ワーカーを実際に待たせて検証する。

    旧テストは `game2.current_node = None` を呼んでから worker を呼んでいたため、ワーカーが
    ループ先頭の `self.current_node is not node` チェックで即 return し、閾値判定
    （`sum(visits) >= threshold`）に一度も到達しない vacuous なテストだった（実装中に
    0.67→0.55→0.35 と3回変わった値の回帰網が存在しない状態）。ここではワーカーを別スレッドで
    起動し、閾値未達のまま待たせてから何も発火していないことを確認する（ゲートを消すと
    最初のループで即発火して落ちる）。
    """
    game, node, engine = _early_game(visits_now=600)  # 600 < 0.35*1800=630
    th = threading.Thread(target=game._early_speculation_worker, args=(node,), daemon=True)
    th.start()
    time.sleep(0.3)
    assert engine.requests == []  # 閾値未達で発火しない（ゲートを消すと落ちる）
    game.current_node = None  # ワーカーを bail させて後片付け
    th.join(timeout=2)


def test_maybe_skips_human_and_non_tsumego_ai():
    game, node, engine = _early_game()
    game.katrain.players_info = {"B": FakeInfo(PLAYER_HUMAN), "W": FakeInfo(PLAYER_AI, AI_TSUMEGO)}
    game._maybe_early_speculation(node)  # 次番が人間 → 発火しない（スレッドも起動しない想定で即検査）
    time.sleep(0.15)
    assert engine.requests == []
    game.katrain.players_info = {"B": FakeInfo(PLAYER_AI, "ai:default"), "W": FakeInfo(PLAYER_HUMAN)}
    game._maybe_early_speculation(node)
    time.sleep(0.15)
    assert engine.requests == []


def test_cancel_terminates_exactly_the_speculative_nodes():
    game, node, engine = _early_game()
    game._early_speculation_worker(node)
    fired = list(game._early_speculation_nodes)
    assert fired
    game._cancel_early_speculation()
    assert engine.terminated == fired
    assert game._early_speculation_nodes == []
    game._cancel_early_speculation()
    assert engine.terminated == fired  # 二重 cancel は no-op
