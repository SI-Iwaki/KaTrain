"""盤面監視の輪の難易度（board-watch spec 追記11）。判定は親局面の解析と humanSL 9段の humanPolicy だけで
決まる純関数で、手ごとに1回だけ記憶する（3経路から呼ばれても色が変わらない）。"""

import threading
from types import SimpleNamespace

import pytest

from katrain.core.move_difficulty import (
    RING_HARD,
    RING_HP_PROFILE,
    RING_HP_VISITS,
    RING_NORMAL,
    RING_OBVIOUS,
    classify_ring_difficulty,
    current_move_ring_kind,
    format_ring_difficulty,
    ring_difficulty_of,
)
from katrain.core.sgf_parser import Move

SIZE = 9
# (gtp, 手番側から見たスコア, visits)。先頭が KataGo の最善手。次善 D4 は 2目・F6 は 2.5目悪い
ROWS = [("E5", 3.0, 1500), ("D4", 1.0, 200), ("F6", 0.5, 100)]
OBVIOUS_HP = {"E5": 0.9, "D4": 0.05, "F6": 0.05}


def hp_array(values, size=SIZE):
    """{gtp: hp} → humanPolicy のフラット配列（盤点数 + 1・末尾 pass・KataGo と同じ並び）"""
    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def analysis(rows, player="B"):
    """rows → (生 moveInfos〈scoreLead は黒視点〉, candidate_moves〈relativePointsLost は手番側視点〉)"""
    sign = 1 if player == "B" else -1
    move_infos = [{"move": g, "order": i, "scoreLead": sign * s, "visits": v} for i, (g, s, v) in enumerate(rows)]
    best = rows[0][1]
    cands = [{"move": g, "order": i, "visits": v, "relativePointsLost": best - s} for i, (g, s, v) in enumerate(rows)]
    return move_infos, cands


def classify(rows=ROWS, hp=OBVIOUS_HP, chosen="E5", player="B"):
    infos, cands = analysis(rows, player)
    policy = hp_array(hp) if isinstance(hp, dict) else hp
    return classify_ring_difficulty(infos, cands, policy, chosen, player, (SIZE, SIZE))


def test_obvious_when_best_is_the_9d_first_instinct_and_no_close_alternative():
    kind, info = classify()
    assert kind == RING_OBVIOUS
    assert info["top"] == "E5" and info["top_hp"] == pytest.approx(0.9)
    assert info["gap"] == pytest.approx(2.0)


def test_deviation_from_the_obvious_move_is_not_obvious():
    kind, _info = classify(chosen="D4")  # AI が意図して最善手を外した手には「明らか」の色を付けない
    assert kind == RING_NORMAL


def test_close_alternative_blocks_obvious():
    kind, info = classify(rows=[("E5", 3.0, 1500), ("D4", 2.5, 200), ("F6", 0.5, 100)])
    assert info["gap"] == pytest.approx(0.5)
    assert kind == RING_NORMAL


def test_no_alternative_with_enough_visits_counts_as_no_competitor():
    kind, info = classify(rows=[("E5", 3.0, 1500), ("D4", 1.0, 5), ("F6", 0.5, 3)])
    assert info["gap"] is None
    assert kind == RING_OBVIOUS


def test_hard_when_the_9d_expected_loss_is_large():
    kind, info = classify(hp={"E5": 0.3, "D4": 0.35, "F6": 0.35})
    assert info["E"] == pytest.approx(0.35 * 2.0 + 0.35 * 2.5)
    assert kind == RING_HARD


def test_hard_takes_precedence_over_obvious():
    # 9段の第一感は最善手 80%・次善とも 2目差＝明らかの条件を満たすが、残り 20% が 8目損する
    kind, info = classify(rows=[("E5", 3.0, 1500), ("D4", 1.0, 200), ("F6", -5.0, 100)], hp={"E5": 0.8, "F6": 0.2})
    assert info["E"] == pytest.approx(1.6)
    assert kind == RING_HARD


def test_normal_in_between():
    kind, info = classify(hp={"E5": 0.6, "D4": 0.2, "F6": 0.2})
    assert info["E"] == pytest.approx(0.2 * 2.0 + 0.2 * 2.5)
    assert kind == RING_NORMAL


def test_white_to_move_uses_the_white_perspective():
    kind, info = classify(player="W")
    assert kind == RING_OBVIOUS and info["gap"] == pytest.approx(2.0)


def test_missing_or_malformed_human_policy_is_no_judgement():
    assert classify(hp=None) == (None, {"why": "no_hp"})
    assert classify(hp=[0.1] * 10) == (None, {"why": "bad_hp"})  # 盤サイズと長さが合わない


def test_no_analysis_or_pass_is_no_judgement():
    assert classify_ring_difficulty([], [], hp_array(OBVIOUS_HP), "E5", "B", (SIZE, SIZE)) == (
        None,
        {"why": "no_analysis"},
    )
    assert classify(chosen="pass") == (None, {"why": "pass"})
    assert classify(chosen=None) == (None, {"why": "pass"})


def test_ring_hp_query_matches_the_strategies_parent_query():
    """難解・一致率ひかえめの親局面クエリと同条件＝NN キャッシュを共有するだけで判定の分布を変えない"""
    from katrain.core.ai import ENIGMA9_HP_CHILD_VISITS, ENIGMA9_HUMAN_PROFILE

    assert (RING_HP_PROFILE, RING_HP_VISITS) == (ENIGMA9_HUMAN_PROFILE, ENIGMA9_HP_CHILD_VISITS)


def node_pair(hp, gtp="E5"):
    infos, cands = analysis(ROWS)
    parent = SimpleNamespace(
        analysis={"moves": {d["move"]: d for d in infos}},
        candidate_moves=cands,
        ring_human_policy=hp,
        next_player="B",
        board_size=(SIZE, SIZE),
    )
    node = SimpleNamespace(move=Move.from_gtp(gtp, player="B"), parent=parent)
    return parent, node


def test_judgement_is_computed_once_per_move_and_logged_once():
    parent, node = node_pair(hp=None)
    logs = []
    assert ring_difficulty_of(node, log=logs.append)[0] is None  # humanPolicy がまだ無い＝判定なし
    parent.ring_human_policy = hp_array(OBVIOUS_HP)  # 後から届いても
    assert ring_difficulty_of(node, log=logs.append)[0] is None  # 最初の判定のまま＝色が変わらない
    assert len(logs) == 1 and "判定なし" in logs[0]


def test_judgement_is_stable_across_threads():
    _parent, node = node_pair(hp=hp_array(OBVIOUS_HP))
    logs, kinds = [], []
    threads = [
        threading.Thread(target=lambda: kinds.append(ring_difficulty_of(node, log=logs.append)[0])) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert kinds == [RING_OBVIOUS] * 8
    assert len(logs) == 1


def test_unexpected_classification_error_is_no_judgement_not_an_exception():
    """判定が想定外の例外を出しても（数値でない humanPolicy など）、輪は普通の色で出る＝例外を外へ出さず
    判定なしを記憶する（記憶しないと監視スレッドが毎周同じ例外を繰り返し、輪が出ないまま止まる）"""
    _parent, node = node_pair(hp=[None] * (SIZE * SIZE + 1))
    logs = []
    kind, info = ring_difficulty_of(node, log=logs.append)
    assert kind is None and info["why"] == "error"
    assert ring_difficulty_of(node)[0] is None
    assert len(logs) == 1 and "判定なし" in logs[0]


def fake_game(node):
    return SimpleNamespace(current_node=node, board_size=(SIZE, SIZE))


def test_current_move_ring_kind_judges_only_the_last_move():
    _parent, node = node_pair(hp=hp_array(OBVIOUS_HP))  # E5 = coords (4, 4) = グリッド (4, 4)
    assert current_move_ring_kind(fake_game(node), (4, 4)) == RING_OBVIOUS


def test_current_move_ring_kind_mismatch_is_no_judgement_and_leaves_no_memo():
    _parent, node = node_pair(hp=hp_array(OBVIOUS_HP))
    assert current_move_ring_kind(fake_game(node), (4, 5)) is None  # 輪が別の交点＝今の着手ではない
    assert not hasattr(node, "ring_difficulty")
    assert current_move_ring_kind(fake_game(node), None) is None
    assert current_move_ring_kind(None, (4, 4)) is None
    root_like = SimpleNamespace(move=None, parent=None)
    assert current_move_ring_kind(fake_game(root_like), (4, 4)) is None


def test_format_ring_difficulty():
    kind, info = classify()
    text = format_ring_difficulty("E5", kind, info)
    assert "E5" in text and "明らか" in text and "90%" in text and "-2.0目" in text
    kind, info = classify(hp={"E5": 0.3, "D4": 0.35, "F6": 0.35})
    assert "難解" in format_ring_difficulty("E5", kind, info) and "期待損失 1.6目" in format_ring_difficulty(
        "E5", kind, info
    )
    kind, info = classify(rows=[("E5", 3.0, 1500), ("D4", 1.0, 5)])
    assert "他に候補なし" in format_ring_difficulty("E5", kind, info)
    assert "判定なし" in format_ring_difficulty("E5", None, {"why": "no_hp"})
    assert "humanPolicy" in format_ring_difficulty("E5", None, {"why": "no_hp"})
