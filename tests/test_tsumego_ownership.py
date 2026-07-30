import pytest

from katrain.core.ai import (
    TSUMEGO_GAIN_RESCUE_MARGIN,
    TSUMEGO_GAIN_VERIFY_MARGIN,
    TSUMEGO_KO_MARGIN,
    select_tsumego_move,
    tsumego_absolute_ownership,
    tsumego_already_succeeded,
    tsumego_eligible_candidates,
    tsumego_gain_contenders,
    tsumego_gain_stones,
    tsumego_ko_beats_normal,
    tsumego_override_confirmed,
    tsumego_ownership_gain,
    tsumego_rescue_candidates,
    tsumego_score_best,
)

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
    # visits は深さゲート（gain_min_visit_ratio）とも噛むので、ここでは両手を深さ比較可能
    # （40/50 = 0.80）にして min_visits だけを効かせる
    cands = [
        {"move": "A1", "pointsLost": 1.0, "visits": 50, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.5, "visits": 40, "ownership": _own(x0_y0=0.8)},
    ]
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, min_visits=10)["move"] == "B1"
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, min_visits=45)["move"] == "A1"


# --- gain の深さゲート（探索の浅い候補は目数最善手を覆せない） ---
# 実測（2026-07-30, 13路右上 case F。正解 N8 に対し AI は N7 を選び白が生きた）
# region 1800visits を3 run + 8000visits で深掘りした値:
#   N8(正解) 780-890visits  ptLost -0.60〜-0.79  gain -0.45〜-0.55  → 8000v(2565visits) で -0.04
#   N7(誤答) 214-307visits  ptLost +1.35〜+1.60  gain +2.70〜+9.10  → 8000v( 637visits) で +0.06
#   N6       89- 90visits   ptLost +1.44         gain +11.06〜+11.98 → 8000v( 502visits) で +0.66
# visits を与えると gain が消える＝これは死活の信号ではなく探索解像度の差。root の ownership が
# 飽和（対象の黒石 -10.4/11、リージョン90点中 -87.3）しているため 0 方向への片側ノイズになる


def test_select_ignores_gain_of_undersearched_challenger():
    """探索の浅い候補の gain は目数最善手を覆せない（case F の N7 = 307/890visits, +9.10）"""
    cands = [
        {"move": "N8", "pointsLost": -0.60, "visits": 890, "ownership": ZERO},
        {"move": "N7", "pointsLost": 1.35, "visits": 307, "ownership": _own(x0_y0=1.0, x1_y1=1.0)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0), (1, 1)], SIZE, +1, 2.0)
    assert chosen["move"] == "N8"


def test_select_allows_gain_of_comparably_searched_challenger():
    """同程度に探索された候補なら従来どおり gain が目数に優先する（case D の A4 は最多探索）"""
    cands = [
        {"move": "B3", "pointsLost": -0.16, "visits": 397, "ownership": ZERO},
        {"move": "A4", "pointsLost": -0.07, "visits": 1045, "ownership": _own(x0_y0=1.0)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, gain_epsilon=0.0)
    assert chosen["move"] == "A4"


def test_select_visit_ratio_is_configurable():
    cands = [
        {"move": "A1", "pointsLost": 0.0, "visits": 1000, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.0, "visits": 300, "ownership": _own(x0_y0=1.0)},
    ]
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, gain_min_visit_ratio=0.5)["move"] == "A1"
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, gain_min_visit_ratio=0.2)["move"] == "B1"
    # 0 でゲート無効（従来動作）
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, gain_min_visit_ratio=0.0)["move"] == "B1"


def test_select_does_not_gate_when_no_visit_info():
    # visits が無い解析結果（解析前・テスト等）ではゲートせず従来どおり gain で決める
    cands = [
        {"move": "A1", "pointsLost": 0.0, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.0, "ownership": _own(x0_y0=1.0)},
    ]
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)["move"] == "B1"


def test_absolute_ownership_is_not_root_relative():
    """同深さで測り直した子局面同士は root 差分ではなく絶対値で比べる。

    別クエリの root ownership は「どの探索の平均か」が違うので差分の基準に使えない。
    実測 case F（子局面を各1800visits で解析）: N8 -26.60 > N7 -26.91 で正解が残る
    """
    own = _own(x0_y0=-1.0, x1_y1=0.5)
    assert tsumego_absolute_ownership(own, [(0, 0), (1, 1)], SIZE, +1) == pytest.approx(-0.5)
    assert tsumego_absolute_ownership(own, [(0, 0), (1, 1)], SIZE, -1) == pytest.approx(0.5)


def test_override_confirmed_only_when_better_beyond_margin():
    # case F の実測差 -26.91 - (-26.60) = -0.31 は挑戦者が負けているので却下
    assert not tsumego_override_confirmed(-26.91, -26.60, TSUMEGO_GAIN_VERIFY_MARGIN)
    # 同深さでも本当に有利なら採用（case B / C の実信号は 1.16 / 3.20 でこちら側）
    assert tsumego_override_confirmed(-25.0, -26.60, TSUMEGO_GAIN_VERIFY_MARGIN)
    # margin 未満の差は同着扱い（同深さでも ±0.3 程度は動く。実測 N6 -26.84 / M7 -26.89）
    assert not tsumego_override_confirmed(-26.45, -26.60, TSUMEGO_GAIN_VERIFY_MARGIN)


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

    # 枠外を混ぜると誤答手が勝ってしまう（修正前の挙動）。実測の visits 比 294/857 = 0.34 は
    # 後から入れた深さゲートでも落ちるので、ここでは counterweight の反転だけを見るため無効化する
    assert select_tsumego_move(cands, ZERO, all_stones, SIZE, +1, 2.0, gain_min_visit_ratio=0.0)["move"] == "C3"
    # リージョン内だけで集計すれば正解手が残る
    region_stones = tsumego_gain_stones(all_stones, REGION)
    assert select_tsumego_move(cands, ZERO, region_stones, SIZE, +1, 2.0, gain_min_visit_ratio=0.0)["move"] == "A4"
    # 深さゲートも独立に誤答手を止める（多重防御）
    assert select_tsumego_move(cands, ZERO, all_stones, SIZE, +1, 2.0)["move"] == "A4"


# --- コウ勝ち前提の採用判定 ---
# 実測データ（どちらも 13路・枠あり・region 限定 1800visits）
# case E (2026-07-30): 無条件に殺す K1(1776visits) が +11.44目。L1(1visit) は実際には
#   -34.26目でコウにしかならないが、コウ勝ち前提だと +12.50目。差は +1.06目しかない
# 追記4 (2026-07-30): 正解がコウの問題。通常最善はセキ止まりで -12.3目、コウ勝ち前提 +8.1目
CASE_E_KO_WIN, CASE_E_NORMAL = 12.50, 11.44
KO_ANSWER_KO_WIN, KO_ANSWER_NORMAL = 8.1, -12.3


def test_ko_rejected_when_normal_best_already_succeeds():
    """通常最善が既に無条件で殺しているならコウに持ち込む理由がない。

    コウ勝ち前提のノードは攻め方が1手多く打ち白石を1子取った局面なので、比較は構造的に
    コウ側へ偏る。その「おまけ」分だけで採用されると、無条件の正解を捨ててコウで不正解になる。
    """
    assert not tsumego_ko_beats_normal(CASE_E_KO_WIN, CASE_E_NORMAL, TSUMEGO_KO_MARGIN)


def test_ko_adopted_when_normal_best_fails():
    # 正解がコウの問題では通常最善が失敗（セキ）なので差が桁違いに大きい
    assert tsumego_ko_beats_normal(KO_ANSWER_KO_WIN, KO_ANSWER_NORMAL, TSUMEGO_KO_MARGIN)


def test_ko_margin_separates_both_measured_cases_with_room():
    # 実測2ケースの差は +1.06 と +20.4。既定マージンは両者から十分離れていること
    assert CASE_E_KO_WIN - CASE_E_NORMAL < TSUMEGO_KO_MARGIN < KO_ANSWER_KO_WIN - KO_ANSWER_NORMAL


def test_old_ko_margin_would_have_taken_the_losing_move():
    # 旧既定 0.5 では case E のおまけ分 +1.06 が通ってしまい、-34目の手を打った
    assert tsumego_ko_beats_normal(CASE_E_KO_WIN, CASE_E_NORMAL, 0.5)


def test_already_succeeded_skips_the_ko_route():
    """詰碁の正解順序は「無条件に殺す > コウ > セキ・生き」で、目数はクラス内のタイブレークにすぎない。

    コウ勝ち前提の役目は「正解のコウ手が失敗（セキ等）より悪く見える」局面の救済だけなので、
    通常最善で既に成功しているなら適用してはいけない。枠は成功側が offence_to_win(5)目
    勝つよう調整されるため、手番側から見たスコアの符号がそのまま成否になる。
    """
    assert tsumego_already_succeeded(CASE_E_NORMAL)  # +11.44目: K1 が無条件に殺している
    assert not tsumego_already_succeeded(KO_ANSWER_NORMAL)  # -12.3目: セキ止まり = 失敗


def test_already_succeeded_boundary_is_the_frame_balance_point():
    # 枠は ±offence_to_win を挟むよう調整されるので境界は 0。ちょうど 0 は「成功していない」側
    assert not tsumego_already_succeeded(0.0)
    assert tsumego_already_succeeded(0.01)
    # 閾値は設定で動かせる（枠が偏っている問題向けの逃げ道）
    assert not tsumego_already_succeeded(3.0, threshold=5.0)


# --- 目数ガードの救済（rescue）: case G 2手目（枠なし盤）の実測 2026-07-30 ---
# 枠なし盤では「殺し損ねても外の空き地で取り返せる」ため KataGo の目数差が圧縮され、
# 正解 C13 の pointsLost が 1.56〜2.26 とガード帯（best+2.0）を挟んで揺れる＝コイン投げ。
# 一方 gain はリージョン内の石だけで集計するので汚染されず C13 が +5.79〜+6.60 で断トツ。
#
#   実戦: C13(v276 pt+2.26 g+5.94) 足切り → B13(pt-0.00 g-4.06) を選択して不正解
#   run0: C13(v290 pt+1.69 g+6.60) 足切り → B13   run1: C13(v287 pt+1.56 g+6.25) 通過 → C13
#   run2: C13(v347 pt+1.60 g+5.79) 足切り → B13
#   同深さ検証(800visits)は C13 が +8.81〜+8.88 で3run とも安定して勝つ
#
# そこでガードで足切りされた候補でも、gain が選択手を rescue_margin 超えて上回り、探索の
# 深さが比較でき（visit比）、同深さ検証で確定した場合だけ採用する（検証なしでは採用しない）。

RESCUE_ROOT = ZERO


def _rescue_cands():
    return [
        # 目数最善（ガード内）だが gain は負 = 白を生かす手（B13 相当）
        {"move": "B1", "pointsLost": 0.0, "visits": 266, "ownership": _own(x0_y0=-0.5)},
        # ガード外（pt+2.26 > 2.0）だが gain 断トツ・visits 同等（C13 相当）
        {"move": "C1", "pointsLost": 2.26, "visits": 276, "ownership": _own(x0_y0=0.7, x1_y1=0.6)},
    ]


def _rescue(cands, chosen, min_visits=10, ratio=0.5, margin=TSUMEGO_GAIN_RESCUE_MARGIN):
    eligible = tsumego_eligible_candidates(cands, 2.0, min_visits)
    contenders = tsumego_gain_contenders(eligible, tsumego_score_best(eligible), ratio)
    return tsumego_rescue_candidates(
        cands, contenders, chosen, RESCUE_ROOT, [(0, 0), (1, 1)], SIZE, +1, min_visits, margin
    )


def test_rescue_returns_the_guard_excluded_top_gain_candidate():
    cands = _rescue_cands()
    rescue = _rescue(cands, chosen=cands[0])
    assert [c["move"] for c in rescue] == ["C1"]


def test_rescue_covers_depth_gate_excluded_candidates():
    # case H (2026-07-30): 正解 N4 は目数ガード内（pt+6.1 <= best+2.0）なのに visit比
    # 0.46-0.49 < 0.5 で深さゲートに足切りされ、gain 争いに参加できず誤答 J7 が選ばれた。
    # 救済の対象は「ガード外」ではなく「gain 争いに参加できなかった全候補」（非 contenders）
    cands = [
        {"move": "F1", "pointsLost": 0.0, "visits": 350, "ownership": _own(x0_y0=-0.1)},
        # ガード内（+1.3 < 2.0）・ratio 160/350=0.46 < 0.5 でゲート外・gain 断トツ（N4 相当）
        {"move": "N1", "pointsLost": 1.3, "visits": 160, "ownership": _own(x0_y0=0.9, x1_y1=0.9)},
    ]
    rescue = _rescue(cands, chosen=cands[0])
    assert [c["move"] for c in rescue] == ["N1"]


def test_rescue_does_not_require_comparable_visits():
    # 浅い候補の gain は片側ノイズだが、救済は採用前に必ず同深さ検証（子局面を測り直す）を
    # 通るので、ここで visit比は課さない（実測: 偽 gain N6 は検証で -0.24 と負け、本物の
    # N4/C13 は +4.5/+8.4 で勝つ。比では 0.21 の本物と 0.24-0.36 の偽が分離できない）
    cands = _rescue_cands()
    cands[1]["visits"] = 100  # 100/266 = 0.38 < 0.5 でも検証行きにする
    rescue = _rescue(cands, chosen=cands[0])
    assert [c["move"] for c in rescue] == ["C1"]


def test_rescue_requires_min_visits():
    cands = _rescue_cands()
    cands[1]["visits"] = 5
    assert _rescue(cands, chosen=cands[0]) == []


def test_rescue_requires_clear_gain_margin():
    # gain 差が margin 以下なら救済しない（ノイズで頻繁に同深さ検証を撃たないため）
    cands = _rescue_cands()
    cands[1]["ownership"] = _own(x0_y0=-0.5 + 0.9)  # 差 +0.9 < margin 1.0
    assert _rescue(cands, chosen=cands[0]) == []


def test_rescue_ignores_candidates_already_eligible():
    # ガード内の候補は通常の gain 争いで評価済み。救済の対象はガード外だけ
    cands = _rescue_cands()
    cands[1]["pointsLost"] = 1.0  # ガード内に入る
    assert _rescue(cands, chosen=cands[0]) == []


def test_rescue_skips_candidates_without_ownership():
    cands = _rescue_cands()
    cands[1].pop("ownership")
    assert _rescue(cands, chosen=cands[0]) == []


def test_rescue_skips_visit_gate_without_visit_info():
    # visits 情報の無い解析結果でも壊れない（min_visits=0 なら床もかからない）
    cands = _rescue_cands()
    for c in cands:
        c.pop("visits")
    rescue = _rescue(cands, chosen=cands[0], min_visits=0)
    assert [c["move"] for c in rescue] == ["C1"]


def test_rescue_returns_all_qualifiers_sorted_by_gain():
    # 実測 case F2 (2026-07-30): v10 のノイズ手 N9(g+6.77) が gain 1位に立ち、トップ1だけを
    # 検証する設計では N9 の却下で救済が終わり、2位3位の本物 N11(g+5.41)/M12(g+5.30) が
    # 検証の機会を失って誤答 J11 を打った。救済は gain 降順の複数候補を返し、検証側が
    # 全員を測って最良を採る（検証は毎回正しく序列化する: N9 -26.9 / N11 -17.1 / J11 -19.4）
    cands = _rescue_cands() + [
        {"move": "D1", "pointsLost": 2.5, "visits": 300, "ownership": _own(x0_y0=1.0, x1_y1=1.0)},
    ]
    rescue = _rescue(cands, chosen=cands[0])
    assert [c["move"] for c in rescue] == ["D1", "C1"]


def test_rescue_caps_the_number_of_candidates():
    # 検証は1候補あたり同深さ解析1本のコストがかかるので上限を設ける（既定3）
    cands = [{"move": "B1", "pointsLost": 0.0, "visits": 266, "ownership": _own(x0_y0=-0.5)}]
    for i, col in enumerate("CDEF"):
        cands.append(
            {"move": f"{col}1", "pointsLost": 3.0, "visits": 200,
             "ownership": _own(x0_y0=0.3 + 0.1 * i, x1_y1=0.5)}
        )
    rescue = _rescue(cands, chosen=cands[0])
    assert len(rescue) == 3
    assert [c["move"] for c in rescue] == ["F1", "E1", "D1"]  # gain 降順
