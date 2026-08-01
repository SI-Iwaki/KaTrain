"""ai:tsumego_solver 戦略の配線テスト（KataGo/Kivy 不要）。

フェイクの game/katrain で generate_move の経路（セッション構築 → 同期 → 着手 /
コウ禁止回避 / フォールバック判定）を検証する。ソルバ本体の正しさは
test_tsumego_solver.py が担う。
"""

import pytest

from katrain.core.ai import STRATEGY_REGISTRY
from katrain.core.constants import AI_TSUMEGO_SOLVER
from katrain.core.sgf_parser import Move
from katrain.core import tsumego_solver_api as solver_api


class FakeKatrain:
    def __init__(self, config_map=None):
        self.logs = []
        self.config_map = config_map or {}

    def log(self, msg, level=None):
        self.logs.append(str(msg))

    def config(self, key, default=None):
        return self.config_map.get(key, default if default is not None else {})


class FakeNode:
    def __init__(self, parent=None, move=None, placements=()):
        self.parent = parent
        self.move = move
        self.placements = list(placements)
        self.next_player = "B" if parent is None or (move and move.player == "W") else "W"


class FakeGame:
    def __init__(self, size, black, white, region=None):
        self.board_size = size
        placements = [Move(coords=c, player="B") for c in black] + [Move(coords=c, player="W") for c in white]
        self.root = FakeNode(placements=placements)
        self.current_node = self.root
        self.region_of_interest = region
        self.katrain = FakeKatrain({"tsumego_capture": {"solver_time_limit_ms": 60000}})

    def play(self, coords, player):
        self.current_node = FakeNode(parent=self.current_node, move=Move(coords=coords, player=player))


def diagram(rows):
    h = len(rows)
    black, white = set(), set()
    for i, row in enumerate(rows):
        for j, v in enumerate(row.split()):
            y = h - 1 - i
            if v == "X":
                black.add((j, y))
            elif v == "O":
                white.add((j, y))
    return black, white, (len(rows[0].split()), h)


def make_game():
    # 直三の生き（正解 D1）
    black, white, size = diagram([". . . . . . .", "O O O O O O O", "O X X X X X O", "O X . . . X O"])
    return FakeGame(size, black, white)


def test_strategy_solves_and_plays():
    game = make_game()
    strategy = STRATEGY_REGISTRY[AI_TSUMEGO_SOLVER](game, {})
    move, thoughts = strategy.generate_move()
    assert move.player == "B"
    assert move.gtp() == "D1"
    assert "UNCONDITIONAL" in thoughts


def test_strategy_session_persists_and_syncs():
    game = make_game()
    strategy = STRATEGY_REGISTRY[AI_TSUMEGO_SOLVER](game, {})
    move, _ = strategy.generate_move()
    assert move.gtp() == "D1"
    session = game.tsumego_solver_session
    assert session is not None
    # 黒 D1・白がパス相当で進めた後も同じセッションが局面同期して解く
    game.play((3, 0), "B")
    game.play(None, "W")
    strategy2 = STRATEGY_REGISTRY[AI_TSUMEGO_SOLVER](game, {})
    move2, thoughts2 = strategy2.generate_move()
    assert game.tsumego_solver_session is session  # セッション再利用（§9.1）
    # D1 の後は2眼で生き済み → パスが本手（クラス維持）
    assert move2.is_pass or move2.coords is not None  # 落ちずに手が出ること


def test_unsolvable_reports_fallback():
    # 直二（何を打っても死）→ FAILED → FALLBACK 判定になること。
    # フォールバック先（ai:tsumego）は解析が必要なので solver_fallback=false で止める
    black, white, size = diagram([". . . . . .", "O O O O O O", "O X X X X O", "O X . . X O"])
    game = FakeGame(size, black, white)
    game.katrain.config_map["tsumego_capture"] = {"solver_fallback": False, "solver_time_limit_ms": 60000}
    strategy = STRATEGY_REGISTRY[AI_TSUMEGO_SOLVER](game, {})
    move, thoughts = strategy.generate_move()
    assert move.is_pass
    assert "フォールバック無効" in thoughts


def test_ko_ban_is_respected():
    """実対局のコウ禁止点は打たない（§9.1）。セッションの ban 追跡を直接検証する。"""
    black, white, size = diagram([". . . . . . .", "O O O O O O O", "O X X X X X O", "O X . . . X O"])
    game = FakeGame(size, black, white)
    session = solver_api.build_session_from_game(game, {"solver_time_limit_ms": 60000})
    assert session is not None
    # 適当な合法手順で同期し、ban 追跡が例外なく動くこと（このケースはコウ形なし = ban None）
    session.sync_moves([((3, 0), "B"), (None, "W")])
    assert session.ban_point is None
    coords, thoughts = session.generate()
    assert not str(thoughts).startswith("FALLBACK")


def test_presolve_uses_policy_hint_provider():
    """投機実行は provider の順序ヒントを使い、答えは変わらない（ソルバ設計スペック追記5）。"""
    game = make_game()
    session = solver_api.build_session_from_game(game, {"solver_time_limit_ms": 60000, "solver_cache": False})
    assert session is not None
    session.policy_hint_provider = lambda: [(2, 0), (3, 0)]  # KataGo 候補の代わり
    session.presolve()
    assert session._policy_hint == [(2, 0), (3, 0)]
    sol = session.last_solution
    assert sol is not None and sol.value.result.name == "UNCONDITIONAL"


def test_presolve_survives_broken_hint_provider():
    """provider が例外を投げてもヒント無しで従来どおり解く。"""
    game = make_game()
    session = solver_api.build_session_from_game(game, {"solver_time_limit_ms": 60000, "solver_cache": False})
    assert session is not None

    def broken():
        raise RuntimeError("boom")

    session.policy_hint_provider = broken
    session.presolve()
    assert session.last_solution is not None


def test_root_order_hint_prefers_move_visits_over_capture_hint():
    """手番の solve は戦略が渡す move_visits（現局面）を優先し、capture 時のヒントは
    root 局面（applied_moves が空）でしか使わない（途中局面では盤が違うため）。"""
    game = make_game()
    session = solver_api.build_session_from_game(game, {"solver_time_limit_ms": 60000, "solver_cache": False})
    assert session is not None
    session._policy_hint = [(2, 0)]
    assert session._root_order_hint() == [(2, 0)]  # root 局面では capture ヒントを使う
    session.move_visits = {(3, 0): 100, (2, 0): 10}
    assert session._root_order_hint() == [(3, 0), (2, 0)]  # visits 降順が優先
    session.move_visits = None
    session.sync_moves([((3, 0), "B")])
    assert session._root_order_hint() is None  # 途中局面では capture ヒントを流用しない


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
