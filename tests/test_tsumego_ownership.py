import pytest

from katrain.core.ai import select_tsumego_move, tsumego_gain_stones, tsumego_ownership_gain

# var_to_grid は grid[y][x] を返し、配列は上の行(y降順)から詰まる。
# 3x3 なら array[0:3]=grid[2], array[3:6]=grid[1], array[6:9]=grid[0]
SIZE = (3, 3)
ZERO = [0.0] * 9


def _own(**cells):
    """cells は "x{X}_y{Y}" -> 値。var_to_grid の並びに合わせた配列を作る"""
    arr = [0.0] * 9
    for key, val in cells.items():
        x, y = (int(part[1:]) for part in key.split("_"))
        arr[(SIZE[1] - 1 - y) * SIZE[0] + x] = val
    return arr


def test_gain_sums_ownership_change_over_stones():
    # (0,0) が +1.0、(1,1) が +0.5 動く。黒番(sign=+1)なので合計 +1.5
    move_own = _own(x0_y0=1.0, x1_y1=0.5)
    gain = tsumego_ownership_gain(ZERO, move_own, [(0, 0), (1, 1)], SIZE, +1)
    assert gain == pytest.approx(1.5)


def test_gain_ignores_points_without_stones():
    # 石の無い (2,2) が動いても gain には効かない（空き地の手が沈む理由）
    move_own = _own(x2_y2=1.0)
    gain = tsumego_ownership_gain(ZERO, move_own, [(0, 0), (1, 1)], SIZE, +1)
    assert gain == pytest.approx(0.0)


def test_gain_sign_flips_for_white():
    move_own = _own(x0_y0=1.0)
    assert tsumego_ownership_gain(ZERO, move_own, [(0, 0)], SIZE, +1) == pytest.approx(1.0)
    assert tsumego_ownership_gain(ZERO, move_own, [(0, 0)], SIZE, -1) == pytest.approx(-1.0)


def test_select_prefers_largest_gain():
    cands = [
        {"move": "A1", "pointsLost": 0.0, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.0, "ownership": _own(x0_y0=0.8)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "B1"


def test_select_rejects_move_beyond_points_guard():
    # gain は最大だが目数ガードを超える手は選ばれない（case B の D5 相当）
    cands = [
        {"move": "A1", "pointsLost": 0.0, "ownership": _own(x0_y0=0.3)},
        {"move": "B1", "pointsLost": 5.0, "ownership": _own(x0_y0=1.0)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "A1"


def test_select_guard_is_relative_to_best_not_zero():
    # 最善手自体が損をしている場合でも、そこからの相対で許容する（case C は最善が +1.7 目損）
    cands = [
        {"move": "A1", "pointsLost": 1.7, "ownership": ZERO},
        {"move": "B1", "pointsLost": 3.0, "ownership": _own(x0_y0=0.9)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "B1"


def test_select_tiebreaks_on_points_lost():
    cands = [
        {"move": "A1", "pointsLost": 1.5, "ownership": _own(x0_y0=0.5)},
        {"move": "B1", "pointsLost": 0.5, "ownership": _own(x0_y0=0.5)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "B1"


def test_select_falls_back_to_points_when_gain_is_noise():
    # 実測（2026-07-29 13路詰碁）: root で対象の白石が既に全て死に判定（+0.99）のため
    # 上位手の gain は ±0.03 のノイズしか出ず、run ごとに正解 C12 と誤答 D12 が入れ替わった。
    # gain 差が gain_epsilon 以内なら同着とみなし、安定した目数差（0.6目）で決める
    cands = [
        {"move": "C12", "pointsLost": -0.31, "ownership": _own(x0_y0=-0.001)},
        {"move": "D12", "pointsLost": 0.33, "ownership": _own(x0_y0=0.003)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "C12"


def test_select_keeps_ownership_priority_beyond_epsilon():
    # gain 差が epsilon を超えるなら従来どおり ownership が目数に優先する
    # （設計書の case B / case C の gain 差は 1.16 / 3.20 でこちら側）
    cands = [
        {"move": "A1", "pointsLost": 0.0, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.5, "ownership": _own(x0_y0=1.1)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "B1"


def test_select_gain_epsilon_is_configurable():
    cands = [
        {"move": "A1", "pointsLost": 0.0, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.0, "ownership": _own(x0_y0=0.5)},
    ]
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, gain_epsilon=0.0)["move"] == "B1"
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, gain_epsilon=1.0)["move"] == "A1"


def test_select_returns_none_without_ownership():
    # ownership が取れない場合は None（呼び出し側が candidate_moves[0] にフォールバックする）
    cands = [{"move": "A1", "pointsLost": 0.0}, {"move": "B1", "pointsLost": 1.0}]
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0) is None


def test_select_returns_none_without_root_ownership():
    cands = [{"move": "A1", "pointsLost": 0.0, "ownership": ZERO}]
    assert select_tsumego_move(cands, None, [(0, 0)], SIZE, +1, 2.0) is None


def test_select_returns_none_without_stones():
    cands = [{"move": "A1", "pointsLost": 0.0, "ownership": ZERO}]
    assert select_tsumego_move(cands, ZERO, [], SIZE, +1, 2.0) is None


def test_select_ignores_barely_searched_moves():
    # 実測（2026-07-30）: 1visit の手の ownership は探索結果ではなく NN の生評価1回で、
    # gain が実手の10〜100倍のノイズになる（探索済み +0.00〜+0.06 に対し 1visit は +0.55/+1.19）。
    # これに負けて実戦で -16.5目の手を打った
    cands = [
        {"move": "M7", "pointsLost": 1.25, "visits": 1324, "ownership": _own(x0_y0=0.002)},
        {"move": "M13", "pointsLost": 2.12, "visits": 1, "ownership": _own(x0_y0=1.0)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "M7"


def test_select_min_visits_also_guards_the_points_filter():
    # 1visit の楽観的なスコアが best_loss を押し下げると目数ガードが不当に狭まり、
    # 本命手まで弾かれてしまう。visits フィルタは目数ガードより前に効かせる
    cands = [
        {"move": "M7", "pointsLost": 1.25, "visits": 1324, "ownership": _own(x0_y0=0.002)},
        {"move": "M13", "pointsLost": -5.0, "visits": 1, "ownership": _own(x0_y0=1.0)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen is not None and chosen["move"] == "M7"


def test_select_keeps_all_moves_when_none_are_searched():
    # 解析がほとんど進んでいない局面で候補ゼロにしない（ownership 無しと誤認して
    # 呼び出し側が「ownership が取れない」とログするのを避ける）
    cands = [
        {"move": "A1", "pointsLost": 0.0, "visits": 2, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.0, "visits": 1, "ownership": _own(x0_y0=0.8)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen is not None and chosen["move"] == "B1"


def test_select_min_visits_is_configurable():
    cands = [
        {"move": "A1", "pointsLost": 1.0, "visits": 50, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.5, "visits": 20, "ownership": _own(x0_y0=0.8)},
    ]
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, min_visits=10)["move"] == "B1"
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, min_visits=30)["move"] == "A1"


# --- gain の集計範囲（リージョン外の枠石を除く） ---

REGION = [0, 1, 0, 1]  # 3x3 の左下 2x2。(2,*) と (*,2) は枠外


def test_gain_stones_drops_stones_outside_the_region():
    stones = [(0, 0), (1, 1), (2, 2), (2, 0), (0, 2)]
    assert tsumego_gain_stones(stones, REGION) == [(0, 0), (1, 1)]


def test_gain_stones_keeps_everything_without_a_region():
    # 枠なしモード等でリージョンが無い場合は従来どおり全石で集計する
    stones = [(0, 0), (2, 2)]
    assert tsumego_gain_stones(stones, None) == stones


def test_select_is_not_inverted_by_the_frame_counterweight():
    """枠外の代償地帯の ownership は詰碁の成否と逆相関するので gain に混ぜてはいけない。

    実測（2026-07-30, 13路の詰碁 case D）: 白が生きてしまう C3 はリージョン内 −9.65 で
    正しく最下位なのに、枠外6石が +11.6 動いて合計 +2.90 と最上位に化け、正解 A4（枠内
    +0.33）を押しのけて選ばれた。枠は「リージョン外に守り側の代償地帯を配る」設計
    （tsumego_frame.put_outside）なので、この反転は偶発ではなく構造的に起きる。
    """
    good = {"move": "A4", "pointsLost": 0.06, "visits": 857, "ownership": _own(x0_y0=0.1, x1_y1=0.1)}
    bad = {  # 枠内は大きく損、枠外(2,2)がそれを上回って逆符号に動く
        "move": "C3",
        "pointsLost": 1.91,
        "visits": 294,
        "ownership": _own(x0_y0=-1.0, x1_y1=-1.0, x2_y2=3.0),
    }
    cands = [good, bad]
    all_stones = [(0, 0), (1, 1), (2, 2)]

    # 枠外を混ぜると誤答手が勝ってしまう（修正前の挙動）
    assert select_tsumego_move(cands, ZERO, all_stones, SIZE, +1, 2.0)["move"] == "C3"
    # リージョン内だけで集計すれば正解手が残る
    region_stones = tsumego_gain_stones(all_stones, REGION)
    assert select_tsumego_move(cands, ZERO, region_stones, SIZE, +1, 2.0)["move"] == "A4"
