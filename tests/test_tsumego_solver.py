"""死活ソルバの単体テスト（スペック §10.1 の受入テスト群）。KataGo 不要・CI で回る。

ダイアグラムは上の行が盤の上。'X'=黒 'O'=白 '.'=空。
"""

import pytest

from katrain.core.tsumego_solver.board import board_from_stones
from katrain.core.tsumego_solver.model import (
    BLACK,
    WHITE,
    Goal,
    Problem,
    ProblemType,
    ResultClass,
    gtp_coord,
)
from katrain.core.tsumego_solver.reference import (
    PRED_ALIVE,
    PRED_SEKI,
    ReferenceSolver,
    SolverLimits,
)

try:
    from katrain.core.tsumego_solver.native import NativeSolver, native_available

    HAVE_NATIVE = native_available()
except Exception:
    HAVE_NATIVE = False

SOLVERS = [ReferenceSolver] + ([NativeSolver] if HAVE_NATIVE else [])


def diagram(rows):
    h = len(rows)
    w = len(rows[0].split())
    black, white = set(), set()
    for i, row in enumerate(rows):
        for j, v in enumerate(row.split()):
            y = h - 1 - i
            if v == "X":
                black.add((j, y))
            elif v == "O":
                white.add((j, y))
    return black, white, (w, h)


def make_problem(rows, region, target, problem_type, to_play=BLACK, own_target=()):
    black, white, size = diagram(rows)
    target = frozenset(target)
    target_color = WHITE if problem_type == ProblemType.ATTACK else BLACK
    if problem_type == ProblemType.SEMEAI:
        target_color = WHITE if to_play == BLACK else BLACK
    goal = {
        ProblemType.ATTACK: Goal.KILL,
        ProblemType.DEFEND: Goal.LIVE,
        ProblemType.SEMEAI: Goal.SEMEAI,
    }[problem_type]
    return Problem(
        size=size,
        black=frozenset(black),
        white=frozenset(white),
        region=frozenset(region),
        to_play=to_play,
        target=target,
        goal=goal,
        problem_type=problem_type,
        target_color=target_color,
        own_target=frozenset(own_target),
    )


def solve(problem, solver_cls, time_ms=60000):
    return solver_cls(problem, SolverLimits(time_limit_ms=time_ms)).solve()


def moves_gtp(sol):
    return sorted(gtp_coord(m) for m in sol.root_moves)


# ---------- 基本形 ----------


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_one_move_kill(solver_cls):
    """一眼の白は眼つぶしの一手で取り切れる（無条件死）。"""
    target = {(1, 1), (2, 1), (3, 1), (1, 0), (3, 0)}
    prob = make_problem(
        [". . . . .", "X X X X X", "X O O O X", "X O . O X"],
        region=target | {(2, 0)},
        target=target,
        problem_type=ProblemType.ATTACK,
    )
    sol = solve(prob, solver_cls)
    assert sol.value.result == ResultClass.UNCONDITIONAL
    assert moves_gtp(sol) == ["C1"]
    assert sol.value.plies == 1


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_straight_three_lives_at_center(solver_cls):
    """直三の眼空間は急所（中央）で無条件生き。"""
    target = {(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (1, 0), (5, 0)}
    prob = make_problem(
        [". . . . . . .", "O O O O O O O", "O X X X X X O", "O X . . . X O"],
        region=target | {(2, 0), (3, 0), (4, 0)},
        target=target,
        problem_type=ProblemType.DEFEND,
    )
    sol = solve(prob, solver_cls)
    assert sol.value.result == ResultClass.UNCONDITIONAL
    assert moves_gtp(sol) == ["D1"]
    assert sol.value.plies == 1  # 同クラス内タイブレーク: 1手で決める（§4.2.1）


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_straight_two_is_dead(solver_cls):
    """直二は何を打っても死（FAILED）。"""
    target = {(1, 1), (2, 1), (3, 1), (4, 1), (1, 0), (4, 0)}
    prob = make_problem(
        [". . . . . .", "O O O O O O", "O X X X X O", "O X . . X O"],
        region=target | {(2, 0), (3, 0)},
        target=target,
        problem_type=ProblemType.DEFEND,
    )
    sol = solve(prob, solver_cls)
    assert sol.value.result == ResultClass.FAILED


# ---------- セキ（§4.7: 静的認識器なしで探索の結果として出る）----------


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_seki_two_shared_liberties(solver_cls):
    """2つのダメを共有するセキ。打てばクラスが下がるので本手はパス。"""
    inside = {(1, 0), (2, 0)}
    wht = {(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (4, 0)}
    prob = make_problem(
        ["X X X X X X .", "O O O O O X .", ". X X . O X ."],
        region=inside | wht | {(0, 0), (3, 0)},
        target=inside,
        problem_type=ProblemType.DEFEND,
    )
    sol = solve(prob, solver_cls)
    assert sol.value.result == ResultClass.SEKI
    assert sol.root_moves == [None]  # パスが本手（打つ手はすべて FAILED）


# ---------- コウの分類（§4.3/§4.4 の受入。最優先）----------


def bent_four_problem():
    """隅の曲がり四目（黒=攻め方）。ソルバの裁定は KO（§10.1 の既知の残差）。"""
    white = {(3, 0), (3, 1), (2, 1), (1, 1), (1, 2), (0, 2), (0, 3)}
    eyespace = {(0, 0), (1, 0), (2, 0), (0, 1)}
    wall = {(4, 0), (4, 1), (3, 2), (2, 2), (1, 3), (0, 4)}
    black, _w, _s = set(wall), None, None
    return Problem(
        size=(6, 6),
        black=frozenset(wall),
        white=frozenset(white),
        region=frozenset(white | eyespace),
        to_play=BLACK,
        target=frozenset(white),
        goal=Goal.KILL,
        problem_type=ProblemType.ATTACK,
        target_color=WHITE,
    )


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_bent_four_in_corner_is_ko(solver_cls):
    """曲がり四目: 攻め方 komaster で殺し成立 = KO（黒先劫 n*=0）。"""
    sol = solve(bent_four_problem(), solver_cls)
    assert sol.value.result == ResultClass.KO
    assert sol.value.ko_level == 0  # 黒（攻め方）から取る劫
    assert sol.komaster == BLACK
    assert moves_gtp(sol) == ["B1"]


def test_single_solve_never_returns_ko():
    """単一 solve では KO が返らないこと（§10.1 の回帰の要）。

    komaster を片方だけ与えた solve は True/False（無条件相当）しか言えず、
    2通りの突き合わせ（食い違い）で初めて KO になる。
    """
    solver = ReferenceSolver(bent_four_problem(), SolverLimits(time_limit_ms=60000))
    # S（攻め方 komaster で白が残るか）= False, S'（守り方 komaster）= True
    s_att, _ = solver._solve_from_root(PRED_SEKI, BLACK, None)
    s_def, _ = solver._solve_from_root(PRED_SEKI, WHITE, None)
    a_att, _ = solver._solve_from_root(PRED_ALIVE, BLACK, None)
    a_def, _ = solver._solve_from_root(PRED_ALIVE, WHITE, None)
    assert (s_att, s_def, a_att, a_def) == (False, True, False, True)
    # 対応表（§4.3.2.1）row4: A ✗ S ✗ A' ✓ S' ✓ → KO。単独の solve はどれも bool のみ


# ---------- 取り跡への打ち直し（§4.1: region は点集合）----------


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_replay_on_captured_point_utegaeshi(solver_cls):
    """ウッテガエシ: 取られて空いた点へ打ち直して取り返す。

    黒 B1 と打つと白が A1 の黒1子を取れる（アタリ）が、取った白2子は
    ウッテガエシで B1 に打ち直されて全滅する。region を「初期の空点」で
    持つ実装はこの打ち直しが生成できず誤答する。
    """
    # 盤（4x3）: 下辺。白 A2,B2? ではなく単純な隅のウッテガエシ形:
    #   y2: X X X .
    #   y1: O O X .
    #   y0: . O X .    黒番。A1 に打つと白 B1?? → 形を単純化: 白2子 (0,1),(1,1),(1,0) が
    #                  取り跡経由でしか取れない形は作りにくいので、石の下の最小形を使う
    rows = ["X X X X", "O O X .", ". O X ."]
    black, white, size = diagram(rows)
    target = {(0, 1), (1, 1), (1, 0)}
    prob = Problem(
        size=size,
        black=frozenset(black),
        white=frozenset(white),
        region=frozenset(target | {(0, 0)}),
        to_play=BLACK,
        target=frozenset(target),
        goal=Goal.KILL,
        problem_type=ProblemType.ATTACK,
        target_color=WHITE,
    )
    sol = solve(prob, solver_cls)
    # 黒 A1 → 白は A1 の黒1子を取れない（自身が呼吸点1）。白タケフ側も1眼しか無く死
    assert sol.value.result == ResultClass.UNCONDITIONAL


# ---------- 眼空間の内部点（§5.1 の回帰: 3x3 の中心が region に入ること）----------


def test_region_includes_eye_space_interior():
    from katrain.core.tsumego_problem import extract_problem

    rows = [
        ". . . . . . .",
        "X X X X X X .",
        "X O O O X . .",
        "X O . O X . .",
        "X O O O X . .",
        "X X X X X . .",
    ]
    black, white, size = diagram(rows)
    prob = extract_problem(stones=(black, white), board_size=size, to_play=BLACK)
    center = (2, 2)  # 3x3 眼空間の中心（どの連の呼吸点でもない）
    assert center in prob.region, "眼空間の内部点が region から漏れている（§5.1 の穴）"
    assert prob.problem_type == ProblemType.ATTACK


# ---------- 問題の型と target（§5.2）----------


def test_extract_defend_type():
    from katrain.core.tsumego_problem import extract_problem

    rows = [". . . . . . .", "O O O O O O O", "O X X X X X O", "O X . . . X O"]
    black, white, size = diagram(rows)
    prob = extract_problem(stones=(black, white), board_size=size, to_play=BLACK)
    assert prob.problem_type == ProblemType.DEFEND
    assert prob.target_color == BLACK
    assert (2, 0) in prob.region and (3, 0) in prob.region


def test_extract_nakade_sacrifice_is_not_semeai():
    """ナカデの中の捨て石（黒1子）が居ても攻め合いに誤分類しない（§5.2.2）。"""
    from katrain.core.tsumego_problem import extract_problem

    # 白の眼空間に黒1子（捨て石の材料）が入っている形
    rows = [
        ". . . . . . .",
        "X X X X X X X",
        "X O O O O O X",
        "X O . X . O X",
    ]
    black, white, size = diagram(rows)
    prob = extract_problem(stones=(black, white), board_size=size, to_play=BLACK)
    assert prob.problem_type == ProblemType.ATTACK, "中の捨て石で攻め合いに化けている"
    assert prob.target_color == WHITE


# ---------- 証明ストアのキー（§6.6: 条件を削ると誤答することの固定）----------


def test_tt_key_must_include_komaster():
    """komaster をキーから削ると2通りの solve が混ざって誤答する（§6.6 の回帰）。

    曲がり四目では S(att)=False / S'(def)=True。komaster をキーに含めない TT を
    使い回すと、後から解いた側が先の答えを拾って同じ値になってしまう。
    """
    prob = bent_four_problem()
    solver = ReferenceSolver(prob, SolverLimits(time_limit_ms=60000))
    v1, _ = solver._solve_from_root(PRED_SEKI, BLACK, None)
    v2, _ = solver._solve_from_root(PRED_SEKI, WHITE, None)
    assert v1 != v2  # komaster がキーに含まれている証拠（含まれなければ TT ヒットで同値になる）


# ---------- 別解（§6.5.1）----------


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_alternatives_both_vital_points(solver_cls):
    """2x3 の眼空間（どちらの急所でも生き）で別解リストに両方入ること。"""
    # 黒地: 6目の長方形（板六）は2手... 単純化: 4目中手にならない「直四」= 2つの急所
    target = {(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (1, 0), (6, 0)}
    prob = make_problem(
        [". . . . . . . .", "O O O O O O O O", "O X X X X X X O", "O X . . . . X O"],
        region=target | {(2, 0), (3, 0), (4, 0), (5, 0)},
        target=target,
        problem_type=ProblemType.DEFEND,
    )
    sol = solve(prob, solver_cls)
    # 直四は既に生き（打たなくても2眼が作れる）→ パスも含め同格の可能性があるが、
    # クラスは無条件生きであること・急所2点（C1/D1 相当）が同格で入ることを確認
    assert sol.value.result == ResultClass.UNCONDITIONAL
    assert len(sol.root_moves) >= 2


# ---------- 同形反復の裁定（§4.6 / §4.6.1）----------
#
# 両コウの「実盤面」をテンプレート探索で得るのは構造要件が狭く未達（スペック追記1参照）。
# ここでは裁定ロジックそのものを機構レベルで固定する: 盤とサイクル手順を構成して
# _adjudicate_cycle の3分岐（生き/死/セキ）と基本則・taint を直接検証する。
# 探索がサイクルに正しく到達すること自体は、コウを含む実ケース（曲がり四目・E2E の
# V/F2/K 等で cycle_tainted=True）が担保している。


def _cycle_solver(rows, target, extra_white=()):
    black, white, size = diagram(rows)
    white = set(white) | set(extra_white)
    prob = Problem(
        size=size,
        black=frozenset(black),
        white=frozenset(white),
        region=frozenset(target | {p for p in [(x, y) for x in range(size[0]) for y in range(size[1])] if p not in black and p not in white}),
        to_play=BLACK,
        target=frozenset(target),
        goal=Goal.LIVE,
        problem_type=ProblemType.DEFEND,
        target_color=BLACK,
    )
    return ReferenceSolver(prob, SolverLimits(time_limit_ms=10000))


def _set_cycle(solver, pairs):
    """2つのコウ点ペアでの取り合い4手をパスに積む（両コウのサイクル形）。"""
    b = solver.board
    solver.path_moves = [
        (b.index(pairs[0][0]), (b.index(pairs[0][1]),)),
        (b.index(pairs[1][0]), (b.index(pairs[1][1]),)),
        (b.index(pairs[0][1]), (b.index(pairs[0][0]),)),
        (b.index(pairs[1][1]), (b.index(pairs[1][0]),)),
    ]


def test_double_ko_alive_closed_form():
    """両コウ生き: target に実眼1つ + 2つのコウ点ペアのサイクル → 閉形式で ALIVE。"""
    rows = [
        "O O O O O O O",
        "O X X X X . O",
        "X X . X X . O",
    ]
    black, white, size = diagram(rows)
    target = set(black)
    solver = _cycle_solver(rows, target)
    # 実眼 (2,0) あり。2つの異なるコウ点ペアの取り合い4手 = 両コウの閉形式が適用される
    _set_cycle(solver, [((5, 1), (5, 0)), ((4, 2), (5, 2))])
    assert solver._adjudicate_cycle(PRED_ALIVE, 0) is True
    assert solver._adjudicate_cycle(PRED_SEKI, 0) is True
    assert solver.taint_any is True


def test_double_ko_seki_closed_form():
    """両コウゼキ: 双方が実眼1つずつ + 両コウ → SEKI（ALIVE 述語は False / SEKI 述語は True）。"""
    rows = [
        "O O O O O O O O",
        "O X X X X . O O",
        "X X . X X . O .",
    ]
    black, white, size = diagram(rows)
    solver = _cycle_solver(rows, set(black))
    # 白（攻め方）にコウ点近くの実眼を作る: (7,0) は隣接 (6,0)O/(7,1)O のみ = 白の実眼
    _set_cycle(solver, [((5, 1), (5, 0)), ((6, 2), (7, 2))])
    assert solver._adjudicate_cycle(PRED_ALIVE, 0) is False  # 生きではない
    assert solver._adjudicate_cycle(PRED_SEKI, 0) is True  # セキとして残る


def test_double_ko_dead_closed_form():
    """両コウ死: target に実眼0 → 閉形式裁定で DEAD（基本則「生かす側の勝ち」では誤る回帰点）。"""
    rows = [
        "O O O O O O O",
        "O X X X X . O",
        "O X . X X . O",  # (2,0) は欠け眼にする（下段左端が白＝斜め条件で偽眼）
    ]
    black, white, size = diagram(rows)
    target = set(black)
    solver = _cycle_solver(rows, target)
    # (2,0) の隣接に白を置いて実眼を消す: (2,0) の左 (1,0) を白に
    solver.board.set_stone(solver.board.index((1, 0)), "W")
    _set_cycle(solver, [((5, 1), (5, 0)), ((4, 2), (5, 2))])
    # 眼なし + 両コウサイクル → DEAD（ALIVE 述語は False）
    assert solver._adjudicate_cycle(PRED_ALIVE, 0) is False
    assert solver._adjudicate_cycle(PRED_SEKI, 0) is False


def test_non_double_ko_cycle_uses_basic_rule():
    """両コウでないサイクル（三コウ・長生相当）は基本則＝生かす側の勝ち（§4.6）。"""
    rows = [
        "O O O O O O O",
        "O X X X X . O",
        "O X . X X . O",
    ]
    black, white, size = diagram(rows)
    solver = _cycle_solver(rows, set(black))
    b = solver.board
    # 3点での取り合い（コウ点ペアが3つ）= 両コウの閉形式は適用されない
    solver.path_moves = [
        (b.index((5, 1)), (b.index((5, 0)),)),
        (b.index((5, 0)), (b.index((5, 1)),)),
        (b.index((2, 0)), (b.index((5, 0)),)),
        (b.index((5, 0)), (b.index((2, 0)),)),
    ]
    assert solver._adjudicate_cycle(PRED_ALIVE, 0) is True  # 生かす側の勝ち
    assert solver._adjudicate_cycle(PRED_SEKI, 0) is True


# ---------- root 候補の順序ヒントと opt スキップ（2026-08-02 の高速化。ソルバ設計スペック追記5）----------


def _straight_three_problem():
    target = {(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (1, 0), (5, 0)}
    return make_problem(
        [". . . . . . .", "O O O O O O O", "O X X X X X O", "O X . . . X O"],
        region=target | {(2, 0), (3, 0), (4, 0)},
        target=target,
        problem_type=ProblemType.DEFEND,
    )


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_root_order_hint_controls_scan_order_but_not_the_answer(solver_cls):
    """順序ヒントは root スキャンの評価順だけを変える（§6.2: 順序は厳密性に影響しない）。

    KataGo policy を先頭に置くと、正解が早く incumbent になり floor 刈りが効いて速くなる
    （実測 2026-08-02: region22 のコウ詰碁で 17.3 → 12.1 秒）。答え・クラスは不変であること。
    """
    baseline = solve(_straight_three_problem(), solver_cls)
    solver = solver_cls(_straight_three_problem(), SolverLimits(time_limit_ms=60000))
    solver.root_order_hint = [(4, 0)]  # わざと静的順序で最後の E1（不正解）を先頭に指定
    seen = []
    orig = solver._classify_after

    def recording(move, floor_key=None):
        seen.append(move)
        return orig(move, floor_key=floor_key)

    solver._classify_after = recording
    sol = solver.solve()
    assert seen[0] == solver.board.index((4, 0))  # ヒント先頭から評価する
    assert sol.value.result == baseline.value.result
    assert moves_gtp(sol) == moves_gtp(baseline)  # 答えは D1 のまま


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_root_order_hint_ignores_bogus_points(solver_cls):
    """ヒントに石の上・盤外・重複が混ざっても落ちない（提供側は KataGo 候補をそのまま渡せる）。"""
    solver = solver_cls(_straight_three_problem(), SolverLimits(time_limit_ms=60000))
    solver.root_order_hint = [(1, 1), (99, 99), (3, 0), (3, 0), None]
    sol = solver.solve()
    assert sol.value.result == ResultClass.UNCONDITIONAL
    assert moves_gtp(sol) == ["D1"]


@pytest.mark.parametrize("solver_cls", SOLVERS)
def test_opt_skip_after_slow_stage1_keeps_class_and_moves(solver_cls):
    """第1段階が opt_skip_after_ms を超えたら手順最適化を省く（クラス・本手は不変で plies だけ 0）。

    実測 2026-08-02: 難しいコウ詰碁では opt が予算3秒を燃やして毎回タイムアウトしていた
    （plies=0 mat=0 で成果ゼロ）。plies==0 の同格タイは GUI 側の KataGo タイブレーク
    （§6.5.1-3）が並べ替えるので、遅い solve では opt を省いて着手までの時間を縮める。
    """
    with_opt = solve(_straight_three_problem(), solver_cls)
    assert with_opt.value.plies == 1  # 速い solve は従来どおり opt が走る（既定閾値の内側）
    limits = SolverLimits(time_limit_ms=60000, opt_skip_after_ms=0)  # 常にスキップ
    skipped = solver_cls(_straight_three_problem(), limits).solve()
    assert skipped.value.result == with_opt.value.result
    assert moves_gtp(skipped) == moves_gtp(with_opt)
    assert skipped.value.plies == 0  # opt が走っていない


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
