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


def test_hopeless_extraction_is_rejected_before_publishing():
    """抽出した問題が「手番側は勝てない（FAILED）」と証明されたら出題してはいけない。

    実測 2026-08-04 の GUI 誤答（13路左下・case AD）。抽出は黒6子 {D7,E5,E6,E7,F5,F7} を
    D〜G × 5〜7 の 10 点の箱に閉じ込めた `type=defend region=10点` を返したが、
    箱の空点 G5/G6/G7 はいずれも白の壁石に接していて黒の眼にならず、F6 の1眼しか作れない
    ＝黒は生きられない（solver: FAILED・0.01s/194nodes）。

    本当の争点は白 {C6,C7,D5,D6}（呼吸点3 = B6/B7/C5）で、記録された正解手順は
    その呼吸点 C5 から始まる。抽出器はこの「取れる白」を不可侵の壁と仮定していた
    （case AA と同型だが、_reaches_safety は広い空き地を歩いて別の白壁へ到達できるため
    発火しない）。出題してしまうと analysis_region が 4x3 の箱に固定され、FAILED で
    現行経路へフォールバックしても KataGo は箱の外（C5）を打てない。

    詰碁は「手番側に正解手がある」問題なので、FAILED と証明できた抽出は間違い＝
    出題せず枠張り経路へ落とす（G5 フォールバック）。
    """
    from katrain.core.tsumego_problem import extract_problem
    from katrain.core.tsumego_solver.model import ProblemType, from_gtp_coord

    b_stones = "C9 C8 D7 E7 F7 E6 E5 F5 C4 D4"
    w_stones = "B12 D12 C11 D10 D8 E8 F8 G8 C7 H7 C6 D6 H6 D5 H5 E4 F4 G4 B3 C2 E2"
    black = {from_gtp_coord(s) for s in b_stones.split()}
    white = {from_gtp_coord(s) for s in w_stones.split()}
    prob = extract_problem(stones=(black, white), board_size=(13, 13), to_play="B")
    assert prob.problem_type == ProblemType.DEFEND and len(prob.region) == 10  # 抽出自体は現状の仕様
    settings = {"solver_cache": False, "solver_verdict_ms": 20000}
    assert solver_api.problem_is_hopeless(prob, settings), "FAILED の抽出を出題してしまう"


def test_solvable_extraction_is_not_rejected():
    """解ける詰碁は当然 hopeless ではない（上の判定が出題そのものを止めないこと）。"""
    from katrain.core.tsumego_problem import extract_problem
    from katrain.core.tsumego_solver.model import from_gtp_coord

    black = {from_gtp_coord(s) for s in "J13 J12 M12 J11 L11 J10 J9 K9 L9 M9 N9".split()}
    white = {from_gtp_coord(s) for s in "K13 K12 K11 M11 K10 L10 M10".split()}
    prob = extract_problem(stones=(black, white), board_size=(13, 13), to_play="B")
    settings = {"solver_cache": False, "solver_verdict_ms": 60000}
    assert not solver_api.problem_is_hopeless(prob, settings)


def test_hopeless_check_is_budget_bounded():
    """予算内に決まらなければ「間違いとは言えない」＝False（従来どおり出題する）。"""
    from katrain.core.tsumego_problem import extract_problem
    from katrain.core.tsumego_solver.model import from_gtp_coord

    black = {from_gtp_coord(s) for s in "J13 J12 M12 J11 L11 J10 J9 K9 L9 M9 N9".split()}
    white = {from_gtp_coord(s) for s in "K13 K12 K11 M11 K10 L10 M10".split()}
    prob = extract_problem(stones=(black, white), board_size=(13, 13), to_play="B")
    assert not solver_api.problem_is_hopeless(prob, {"solver_cache": False, "solver_verdict_ms": 1})


def test_cache_hit_reranks_equal_alternatives_with_katago_order(tmp_path, monkeypatch):
    """実測 2026-08-15 回答帳 13333f79df: E2/C3/D2 が同格の無条件殺しの詰碁で、
    KataGo ランキングを持たないセッション（キャプチャ時の投機実行）が最初に証明できた手を
    キャッシュに焼き付けると、以後の全セッションが §6.5.1-3 タイブレークを素通りして
    アプリの解答樹の本手 D2（KataGo 本命 v1145）ではない手を即答していた。

    CACHE_VERSION 3: 同格別解リストを保存し、ヒット時に現セッションの KataGo 順で
    並べ替える（fresh solve と同じタイブレークの遅延適用）。
    """
    from katrain.core.tsumego_problem import extract_problem
    from katrain.core.tsumego_solver.model import from_gtp_coord

    b_stones = "A2 A3 A4 A5 B2 B5 B6 C6 D6 E5 F1 F5 G2 G3 G4 G5 H2"
    w_stones = "B3 B4 C2 C5 D4 D5 E1 E4 F2 F3 F4"
    black = {from_gtp_coord(s) for s in b_stones.split()}
    white = {from_gtp_coord(s) for s in w_stones.split()}
    prob = extract_problem(stones=(black, white), board_size=(13, 13), to_play="B")
    cache_file = str(tmp_path / "entry.json")
    monkeypatch.setattr(solver_api.TsumegoSolverSession, "_cache_path", lambda self: cache_file)
    settings = {"solver_cache": True, "solver_time_limit_ms": 60000}

    # セッションA: ランキング無し（投機実行相当）。解いて同格別解ごとキャッシュされる
    session_a = solver_api.TsumegoSolverSession(prob, settings)
    coords_a, thoughts_a = session_a.generate()
    assert coords_a is not None, thoughts_a
    import json as _json

    data = _json.load(open(cache_file, encoding="utf-8"))
    alts = {tuple(a) for a in data.get("alternatives") or []}
    assert from_gtp_coord("D2") in alts and coords_a in alts, data

    # セッションB: KataGo ランキングあり（D2 が本命）。キャッシュヒットでも D2 に並べ替わる
    session_b = solver_api.TsumegoSolverSession(prob, settings)
    order = {from_gtp_coord("D2"): 0, from_gtp_coord("C3"): 1, from_gtp_coord("E2"): 2}
    session_b.move_ranker = lambda pt: order.get(pt, 10**6)
    session_b.move_visits = {from_gtp_coord("D2"): 1145, from_gtp_coord("C3"): 249, from_gtp_coord("E2"): 155}
    coords_b, thoughts_b = session_b.generate()
    assert coords_b == from_gtp_coord("D2"), thoughts_b
    assert "キャッシュ" in thoughts_b, thoughts_b  # 解き直しではなくヒット経路で並べ替えたこと

    # セッションC: ランキング無しのヒットは従来どおり保存時の決め手を返す（後方互換）
    session_c = solver_api.TsumegoSolverSession(prob, settings)
    coords_c, thoughts_c = session_c.generate()
    assert coords_c == coords_a, thoughts_c
    assert "キャッシュ" in thoughts_c, thoughts_c
