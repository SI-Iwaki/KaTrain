"""盤面監視の複数候補表示（board-watch spec 追記15）。役割（最善手・第一感・人間らしい手）は親局面の解析と
humanSL 9段の humanPolicy だけで決まる純関数。罠かどうかは記憶せず着手ノードの記録から毎回読む。"""

from types import SimpleNamespace

from katrain.core.move_candidates import (
    MARK_ALL,
    MARK_BEST,
    MARK_HUMAN,
    MARK_INSTINCT,
    MARK_TRAP,
    candidate_marks,
    candidate_roles,
    current_move_marks,
    decision_is_trap,
    format_ring_roles,
    ring_roles_of,
    swap_targets,
)
from katrain.core.sgf_parser import Move

SIZE = 9
# (gtp, 最善手からの損失〈目〉, visits)。先頭が KataGo の最善手
ROWS = [("E5", 0.0, 1500), ("D4", 0.8, 200), ("F6", 3.5, 100), ("C3", 0.2, 3)]


def hp_array(values, size=SIZE, pass_hp=0.0):
    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    arr[-1] = pass_hp
    return arr


def cands(rows=ROWS):
    return [{"move": g, "order": i, "visits": v, "relativePointsLost": loss} for i, (g, loss, v) in enumerate(rows)]


def roles(hp, rows=ROWS, max_loss=2.0):
    policy = hp_array(hp) if isinstance(hp, dict) else hp
    return candidate_roles(cands(rows), policy, (SIZE, SIZE), max_loss)


def test_roles_first_instinct_is_the_hp_top_and_human_is_the_same_when_it_is_sound():
    r = roles({"E5": 0.3, "D4": 0.6, "F6": 0.1})
    assert r == {"best": "E5", "instinct": "D4", "human": "D4"}  # D4 は 0.8目損＝悪手でない


def test_roles_human_differs_only_when_the_first_instinct_is_a_bad_move():
    r = roles({"E5": 0.2, "D4": 0.3, "F6": 0.5})  # 第一感 F6 は 3.5目損
    assert r == {"best": "E5", "instinct": "F6", "human": "D4"}


def test_roles_a_shallow_first_instinct_is_not_called_a_bad_move():
    """第一感が浅くしか読まれていないだけ（C3 は 0.2目・3 visits）では悪手と言えない＝人は第一感のまま。

    通常解析は visits を数手に集中させるので、ここで visits の下限を掛けると人が頻繁に別の点へ飛び、
    「第一感は悪手」と読めてしまう"""
    r = roles({"E5": 0.1, "C3": 0.7, "D4": 0.2})
    assert r["instinct"] == "C3" and r["human"] == "C3"


def test_roles_a_shallow_first_instinct_over_the_limit_is_a_bad_move():
    """浅い候補の損失は打つ側に楽観的＝それでも上限を超えるなら悪手。代わりは損失を信用できる候補から選ぶ"""
    rows = [("E5", 0.0, 1500), ("D4", 0.8, 200), ("C3", 2.6, 3), ("B2", 0.1, 4)]
    r = roles({"E5": 0.1, "C3": 0.5, "B2": 0.3, "D4": 0.2}, rows=rows)
    assert r["instinct"] == "C3" and r["human"] == "D4"  # B2 は hp が高いが 4 visits＝代わりには選ばない


def test_roles_unsearched_first_instinct_falls_back_to_the_best_sound_move():
    r = roles({"A1": 0.9, "E5": 0.05})  # 第一感 A1 は KataGo の候補に無い
    assert r == {"best": "E5", "instinct": "A1", "human": "E5"}


def test_roles_without_human_policy_have_only_the_best_move():
    assert roles(None) == {"best": "E5", "instinct": None, "human": None}
    assert roles([0.1] * 5) == {"best": "E5", "instinct": None, "human": None}  # 盤と形が合わない


def test_roles_pass_is_never_a_candidate():
    r = candidate_roles(cands([("pass", 0.0, 900), ("E5", 0.1, 500)]), hp_array({"E5": 0.2}, pass_hp=0.7), (SIZE, SIZE))
    assert r["best"] is None and r["instinct"] is None  # 最善手がパス・9段の第一感もパス
    assert r["human"] == "E5"


def test_marks_all_different_points():
    r = {"best": "E5", "instinct": "F6", "human": "D4"}
    assert candidate_marks(r, "G7", trap=True) == [
        ("G7", MARK_TRAP, True),
        ("E5", MARK_BEST, False),
        ("D4", MARK_HUMAN, False),
        ("F6", MARK_INSTINCT, False),
    ]


def test_marks_human_is_written_only_when_it_differs_from_the_first_instinct():
    r = {"best": "E5", "instinct": "D4", "human": "D4"}
    assert candidate_marks(r, "G7") == [("G7", "", True), ("E5", MARK_BEST, False), ("D4", MARK_INSTINCT, False)]


def test_marks_best_equal_to_first_instinct_collapses_to_one_glyph():
    r = {"best": "E5", "instinct": "E5", "human": "E5"}
    assert candidate_marks(r, "E5") == [("E5", MARK_ALL, True)]  # 明らかな一手＝輪は1つ
    assert candidate_marks(r, "G7", trap=True) == [("G7", MARK_TRAP, True), ("E5", MARK_ALL, False)]


def test_marks_roles_on_the_decision_point_share_its_ring():
    r = {"best": "E5", "instinct": "F6", "human": "E5"}
    assert candidate_marks(r, "E5") == [("E5", MARK_BEST + MARK_HUMAN, True), ("F6", MARK_INSTINCT, False)]
    r = {"best": "E5", "instinct": "D4", "human": "D4"}
    assert candidate_marks(r, "D4", trap=True) == [("D4", MARK_TRAP + MARK_INSTINCT, True), ("E5", MARK_BEST, False)]


def test_marks_never_exceed_two_glyphs_per_point_and_four_rings():
    for best in ("E5", None):
        for instinct in ("E5", "D4", None):
            for human in ("E5", "D4", "F6", None):
                for chosen in ("E5", "D4", "F6", "G7"):
                    marks = candidate_marks({"best": best, "instinct": instinct, "human": human}, chosen, trap=True)
                    assert len(marks) <= 4 and marks[0][0] == chosen and marks[0][2]
                    assert len({gtp for gtp, _t, _d in marks}) == len(marks)


def test_marks_empty_for_pass_or_no_move():
    r = {"best": "E5", "instinct": "D4", "human": "D4"}
    assert candidate_marks(r, "pass") == [] and candidate_marks(r, None) == []


def test_marks_without_roles_is_just_the_decision_ring():
    assert candidate_marks({"best": None, "instinct": None, "human": None}, "E5") == [("E5", "", True)]


def test_decision_is_trap_reads_the_strategy_record():
    assert decision_is_trap({"kind": "gamble", "trap": True})
    assert decision_is_trap({"kind": "trap"})  # 一致率ひかえめの罠の層
    assert not decision_is_trap({"kind": "deviate", "trap": False, "delta_e": 0.1})
    assert not decision_is_trap(None) and not decision_is_trap({}) and not decision_is_trap("trap")


def _node(move="G7", hp=None, rows=ROWS, player="B"):
    parent = SimpleNamespace(
        analysis={"moves": {g: {} for g, _l, _v in rows}},
        candidate_moves=cands(rows),
        ring_human_policy=None if hp is None else hp_array(hp),
        board_size=(SIZE, SIZE),
        next_player=player,
    )
    return SimpleNamespace(move=Move.from_gtp(move, player=player), parent=parent)


def test_ring_roles_are_remembered_once_the_human_policy_is_there():
    node = _node(hp={"E5": 0.3, "D4": 0.6})
    logs = []
    first = ring_roles_of(node, log=logs.append)
    assert first == {"best": "E5", "instinct": "D4", "human": "D4"} and node.ring_roles is first
    node.parent.ring_human_policy = hp_array({"F6": 0.9})  # 後から変わっても記憶した値のまま（輪がちらつかない）
    assert ring_roles_of(node, log=logs.append) is first
    assert len(logs) == 1 and "E5" in logs[0] and "D4" in logs[0]


def test_ring_roles_are_not_remembered_while_the_human_policy_is_missing():
    node = _node(hp=None)
    assert ring_roles_of(node) == {"best": "E5", "instinct": None, "human": None}
    assert getattr(node, "ring_roles", None) is None
    node.parent.ring_human_policy = hp_array({"D4": 0.6, "E5": 0.3})  # 届いた周から全部出る
    assert ring_roles_of(node)["instinct"] == "D4"


def test_ring_roles_without_parent_analysis_are_empty():
    node = _node(hp={"E5": 0.9})
    node.parent.analysis = {}
    assert ring_roles_of(node) == {"best": None, "instinct": None, "human": None}


def test_current_move_marks_reads_the_trap_flag_live_and_records_swap_targets():
    from katrain.core.board_watch import move_to_grid

    node = _node(move="G7", hp={"E5": 0.3, "D4": 0.6})
    game = SimpleNamespace(current_node=node, board_size=(SIZE, SIZE))
    at = lambda gtp: move_to_grid(Move.from_gtp(gtp).coords, SIZE)  # noqa: E731
    marks = current_move_marks(game, at("G7"))
    assert marks == [(at("G7"), "", True), (at("E5"), MARK_BEST, False), (at("D4"), MARK_INSTINCT, False)]
    assert node.watch_swap_auto == {"E5", "D4"} and swap_targets(node) == {"E5", "D4"}
    # 戦略の記録は着手ノードが現局面になった後で付く＝後から付いても次の描画で「罠」になる
    node.ai_decision = {"kind": "deviate", "trap": True}
    assert current_move_marks(game, at("G7"))[0] == (at("G7"), MARK_TRAP, True)
    assert current_move_marks(game, at("A1")) is None  # 輪の指す手が最終手でない＝局面が動いた


def test_swap_targets_include_carried_moves_but_never_the_node_itself():
    node = _node(move="E5")
    node.watch_swap_auto = frozenset({"D4"})
    node.watch_swap_carry = frozenset({"G7", "E5", "pass"})
    assert swap_targets(node) == {"D4", "G7"}
    assert swap_targets(_node(move="E5")) == set()


def test_format_ring_roles_is_one_log_line():
    line = format_ring_roles("G7", {"best": "E5", "instinct": "D4", "human": None})
    assert line == "盤面監視: G7 の候補 最善 E5・第一感 D4・人間らしい手 なし"
