import pytest

from katrain.core.ai import select_tsumego_move, tsumego_ownership_gain

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
