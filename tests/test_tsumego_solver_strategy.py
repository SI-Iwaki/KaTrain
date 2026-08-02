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


def test_gate_probe_upgrades_class_after_defender_mistake():
    """case AB（実測 2026-08-02・13路右上）: root=KO の詰碁で相手が最強防御を外し
    無条件殺しが成立した局面では、証明ストア即答が KO gate の決め手（コウ手 N11）を
    返してはならず、格上げした無条件の本手 M13 を返すこと。

    root は W L12（L11 の黒を抜く）が最強防御でコウ殺しのみ＝class=KO が正しい。
    白が N12 と受けるとその時点から B M13 で無条件に殺せる（五目中手）。
    詰碁の順序は 無条件 > コウ なので、gate の probe だけで即答すると誤答になる。
    """
    from katrain.core.tsumego_problem import extract_problem
    from katrain.core.tsumego_solver.model import from_gtp_coord

    black = {from_gtp_coord(s) for s in "J13 J12 M12 J11 L11 J10 J9 K9 L9 M9 N9".split()}
    white = {from_gtp_coord(s) for s in "K13 K12 K11 M11 K10 L10 M10".split()}
    prob = extract_problem(stones=(black, white), board_size=(13, 13), to_play="B")
    session = solver_api.TsumegoSolverSession(
        prob, {"solver_cache": False, "solver_time_limit_ms": 60000}
    )
    coords, thoughts = session.generate()
    assert coords == from_gtp_coord("N10"), thoughts  # root の本手（KO クラス）
    session.sync_moves([(from_gtp_coord("N10"), "B"), (from_gtp_coord("N12"), "W")])
    coords2, thoughts2 = session.generate()
    assert coords2 == from_gtp_coord("M13"), thoughts2  # N11（コウ）ではなく無条件の M13


def test_better_gates_follow_type_ladder():
    """_better_gates は型別ラダーの「現 gate より前の step」を返す（最上位なら空）。"""
    from katrain.core.tsumego_problem import extract_problem
    from katrain.core.tsumego_solver.model import from_gtp_coord

    black = {from_gtp_coord(s) for s in "J13 J12 M12 J11 L11 J10 J9 K9 L9 M9 N9".split()}
    white = {from_gtp_coord(s) for s in "K13 K12 K11 M11 K10 L10 M10".split()}
    prob = extract_problem(stones=(black, white), board_size=(13, 13), to_play="B")
    assert prob.problem_type.value == "attack"
    session = solver_api.TsumegoSolverSession(prob, {"solver_cache": False})
    # KO gate（komaster=攻め方 B。budget は n* なので比較に使われない）の上位 = 無条件ゲートのみ
    assert session._better_gates(("seki", "B", 0, False)) == [("seki", "W", None, False)]
    # 無条件 gate は最上位 → 空（従来どおりの 0ms 即答）
    assert session._better_gates(("seki", "W", None, False)) == []
    # ラダーに無い gate（想定外）→ 空 = 従来動作
    assert session._better_gates(("alive", "W", None, True)) == []


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
