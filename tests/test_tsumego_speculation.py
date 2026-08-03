"""詰碁の手番内投機（温め・結果は捨てる）の回帰テスト。

守っているのは3点:
1. **投機プランは実際に後段が撃つクエリの上位集合**（救済の最終リストは選択手確定後に
   決まるが、温め集合はどの選択結果でもそれを含む＝ミスによる温め漏れが構造的に出ない。
   アンカー選定は chosen・score_best だけでなく `tsumego_score_best_challengers` 経由の
   第3の eligible 候補にも及ぶ＝その候補が検証後の勝者になるケースも塞ぐ）
2. 温め条件（untilDepth・wideRootNoise・**rescue_margin**）が実クエリと一致する（条件が
   ずれると NN キャッシュ全ミス＝1秒も速くならない。特に rescue_margin はユーザー設定
   `gain_rescue_margin` を渡す経路なので既定値決め打ちだと上位集合が破れる。ownership は
   配管側 Task 2 で担保）
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


def test_rescue_superset_covers_challenger_anchor_with_third_eligible_candidate():
    """検証後の勝者が chosen でも score_best でもない第3の eligible 候補になるケースも、
    アンカー選定（gain 最小）に取り込まれて上位集合が保たれる。

    F6 は `tsumego_score_best_challengers` 経由で anchors に入る第3の eligible 候補で、
    gain が chosen・score_best の両方より低い。F6 がアンカーに選ばれて初めて、chosen 基準
    （閾値+2.8）・score_best 基準（閾値+1.1）のどちらでも超えられない救済候補 G7
    （gain+1.08）が温め集合に入る（F6 基準の閾値は+1.05）。
    """
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})  # gain +1.8
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})  # gain +0.1
    # 第3の eligible 候補: gain は score_best よりさらに低く、visits は深さゲート(0.5)を通る
    third = _cand("F6", 0.2, 250, {(3, 3): 0.05})  # gain +0.05
    eligible = [chosen, score_best, third]
    # F6 基準の閾値(+0.05+1.0=+1.05)だけを超え、chosen(+2.8)・score_best(+1.1)基準では超えない
    rescue = _cand("G7", 3.0, 200, {(3, 3): 0.54, (4, 4): 0.54})  # gain +1.08
    candidate_moves = eligible + [rescue]

    plan = tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )

    # (a) chosen・score_best を直接アンカーにした実救済呼び出しでは G7 は救済されない
    # ＝F6 がアンカーになって初めて G7 が温め集合に入ることの裏づけ
    contenders = tsumego_gain_contenders(eligible, score_best, 0.5)
    rescue_with_chosen = tsumego_rescue_candidates(
        candidate_moves, contenders, chosen, ROOT_OWNERSHIP, STONES, BOARD_SIZE, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN
    )
    rescue_with_score_best = tsumego_rescue_candidates(
        candidate_moves, contenders, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN
    )
    assert "G7" not in {c["move"] for c in rescue_with_chosen}
    assert "G7" not in {c["move"] for c in rescue_with_score_best}

    # (b) F6（検証後の勝者）基準の実救済リストは温め集合に包含される
    rescue_with_third = tsumego_rescue_candidates(
        candidate_moves, contenders, third, ROOT_OWNERSHIP, STONES, BOARD_SIZE, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN
    )
    assert {c["move"] for c in rescue_with_third} <= _plan_moves(plan)
    assert "G7" in _plan_moves(plan)  # F6 がアンカーに選ばれて初めて温まる救済候補


def test_rescue_margin_parameter_propagates_to_rescue_threshold():
    """rescue_margin を明示的に渡すと救済の閾値が変わる（実救済のユーザー設定
    `gain_rescue_margin` と揃える経路）。

    既定 margin(1.0) では救済候補 H8(gain +0.9) は score_best 基準の閾値(+0.1+1.0=+1.1)
    を超えられず温まらないが、より狭い margin(0.5) を渡すと閾値(+0.1+0.5=+0.6) を超えて
    温め対象に入る。`tsumego_speculation_plan` が rescue_margin を内部の
    `tsumego_rescue_candidates` 呼び出しに伝播していないと、この2つの呼び出し結果が
    同じになり後半の assert が失敗する。
    """
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})  # gain +1.8
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})  # gain +0.1
    eligible = [chosen, score_best]
    borderline_margin = _cand("H8", 3.0, 200, {(3, 3): 0.45, (4, 4): 0.45})  # gain +0.9
    candidate_moves = eligible + [borderline_margin]

    plan_default = tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    assert "H8" not in _plan_moves(plan_default)

    plan_narrow_margin = tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25, rescue_margin=0.5,
    )
    assert "H8" in _plan_moves(plan_narrow_margin)


def test_empty_when_no_stones_or_no_score_best():
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9})
    assert tsumego_speculation_plan(
        [chosen], [chosen], chosen, None, ROOT_OWNERSHIP, [], BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    ) == []
