"""詰碁の手番内投機（温め・結果は捨てる）の回帰テスト。

守っているのは3点:
1. **投機プランは実際に後段が撃つクエリの上位集合**（救済の最終リストは選択手確定後に
   決まるが、温め集合はどの選択結果でもそれを含む＝ミスによる温め漏れが構造的に出ない）
2. 温め条件（untilDepth・wideRootNoise）が実クエリと一致する（条件がずれると NN キャッシュ
   全ミス＝1秒も速くならない。ownership は配管側 Task 2 で担保）
3. 投機は判定に影響しない＝プラン計算は読み取り専用の純関数
"""

from katrain.core.ai import (
    TSUMEGO_GAIN_RESCUE_MARGIN,
    TSUMEGO_KO_REGION_UNTIL_DEPTH,
    TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
    tsumego_gain_contenders,
    tsumego_rescue_candidates,
    tsumego_score_best,
    tsumego_speculation_plan,
)

BOARD = 13
# tsumego_ownership_gain は var_to_grid(ownership, board_size) 経由で盤を読むため、
# board_size は int ではなく (width, height) タプル（katrain 全体で game.board_size がそう）。
# 実装（katrain/core/ai.py 内 game.board_size の使われ方）を読んで確認し、テスト側をこれに合わせる。
BOARD_SIZE = (BOARD, BOARD)


def _cand(move, points_lost, visits, gain_cells):
    """ownership はリージョン石2子 {(3,3),(4,4)} だけ非ゼロの疎な盤で作る。

    `tsumego_ownership_gain` は `katrain.core.utils.var_to_grid` 経由で ownership 配列を
    grid[y][x] に変換する。`var_to_grid` は y=board_size-1 から 0 へ向けて board_size 個ずつ
    詰めるため、配列インデックスは `y*board_size+x` ではなく
    `(board_size-1-y)*board_size+x`（実装を読んで確認・座標系をここに合わせている）。

    gain_cells は {(x,y): value}。tsumego_ownership_gain は
    sum(player_sign * (move_own[i] - root_own[i]) for stones) なので、
    root=0 の盤なら gain = sum(gain_cells の石の値)。
    """
    ownership = [0.0] * (BOARD * BOARD)
    for (x, y), v in gain_cells.items():
        ownership[(BOARD - 1 - y) * BOARD + x] = v
    return {"move": move, "pointsLost": points_lost, "visits": visits, "ownership": ownership}


STONES = [(3, 3), (4, 4)]
ROOT_OWNERSHIP = [0.0] * (BOARD * BOARD)


def _plan_moves(plan):
    return {item["move"] for item in plan}


def test_rescue_superset_covers_all_possible_chosen_outcomes():
    """検証で選択手が目数最善へ巻き戻った場合の救済リストも温め集合に含まれる。

    chosen(gain大) と score_best(gain小) で救済の gain 閾値が変わる:
    実フローの救済は「検証後の選択手」基準なので、score_best が incumbent 勝ちすると
    閾値が下がり救済候補が**増える**。プランは最小 gain のアンカーで計算するので
    どちらの結果でも上位集合になる。
    """
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9, (4, 4): 0.9})  # gain +1.8
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})  # gain +0.1（目数最善・gain 小）
    # 検証が必要になる形: chosen が目数で score_best に 0.1 劣る（points_epsilon=0.25 の外は不要、
    # needs_verify は「バンド外で目数最善でない」ときに立つ。ここでは pointsLost 差 0.1 < 0.25 だと
    # バンド内で検証不要になるため、差を 0.5 にする
    chosen["pointsLost"] = 0.4
    eligible = [chosen, score_best]
    # 非contender: gain +1.3 = score_best 基準(+0.1+1.0=+1.1) は超えるが chosen 基準(+1.8+1.0=+2.8) は超えない
    borderline = _cand("E5", 3.0, 200, {(3, 3): 0.65, (4, 4): 0.65})
    candidate_moves = eligible + [borderline]

    plan = tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    # score_best が incumbent 勝ちしたときの実救済リスト
    real_rescues = tsumego_rescue_candidates(
        candidate_moves, tsumego_gain_contenders(eligible, score_best, 0.5), score_best,
        ROOT_OWNERSHIP, STONES, BOARD_SIZE, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN,
    )
    assert {c["move"] for c in real_rescues} <= _plan_moves(plan)
    assert "E5" in _plan_moves(plan)  # chosen 基準では出ない救済候補も温まっている


def test_ko_screen_targets_are_chosen_and_score_best_with_screen_conditions():
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    chosen["pointsLost"] = 0.4
    eligible = [chosen, score_best]
    plan = tsumego_speculation_plan(
        eligible, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    screen_items = [i for i in plan if i["until_depth"] == TSUMEGO_KO_REGION_UNTIL_DEPTH]
    assert {i["move"] for i in screen_items} == {"C3", "D4"}
    for item in screen_items:
        # 実クエリ（_ko_route_screen）と同一条件でないと NN キャッシュ全ミス
        assert item["wide_root_noise"] == TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE


def test_rescue_items_use_default_conditions():
    """救済の実クエリ（_verified_choice）は untilDepth=既定(None=1)・wRN=既定(None=本譜)"""
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    eligible = [chosen, score_best]
    rescue = _cand("E5", 3.0, 200, {(3, 3): 0.65, (4, 4): 0.65})
    plan = tsumego_speculation_plan(
        eligible + [rescue], eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    rescue_items = [i for i in plan if i["move"] == "E5"]
    assert rescue_items and rescue_items[0]["until_depth"] is None
    assert rescue_items[0]["wide_root_noise"] is None


def test_flags_disable_each_kind():
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    eligible = [chosen, score_best]
    rescue = _cand("E5", 3.0, 200, {(3, 3): 0.65, (4, 4): 0.65})
    args = (eligible + [rescue], eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE)
    kwargs = dict(player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25)
    no_rescue = tsumego_speculation_plan(*args, include_rescue=False, **kwargs)
    assert "E5" not in _plan_moves(no_rescue)
    no_screen = tsumego_speculation_plan(*args, include_ko_screen=False, **kwargs)
    assert all(i["until_depth"] is None for i in no_screen)


def test_empty_when_no_stones_or_no_score_best():
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9})
    assert tsumego_speculation_plan(
        [chosen], [chosen], chosen, None, ROOT_OWNERSHIP, [], BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    ) == []
