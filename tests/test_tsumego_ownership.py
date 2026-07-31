from types import SimpleNamespace

import pytest

from katrain.core.ai import (
    TSUMEGO_GAIN_RESCUE_MARGIN,
    TSUMEGO_GAIN_VERIFY_MARGIN,
    TSUMEGO_KO_MARGIN,
    TSUMEGO_KO_REGION_UNTIL_DEPTH,
    TSUMEGO_KO_REPLY_RATIO,
    TSUMEGO_KO_REPLY_RATIO_CHOSEN,
    TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
    TSUMEGO_TIE_KO_PLIES,
    select_tsumego_move,
    tsumego_class_screen_all_ko,
    tsumego_class_screen_pool,
    tsumego_competitive_replies,
    tsumego_declass_choice,
    tsumego_needs_score_best_verify,
    tsumego_selection_band,
    tsumego_absolute_ownership,
    tsumego_already_succeeded,
    tsumego_eligible_candidates,
    tsumego_gain_contenders,
    tsumego_gain_stones,
    tsumego_ko_escape_accepts,
    tsumego_ko_escape_candidates,
    tsumego_ko_beats_normal,
    tsumego_override_confirmed,
    tsumego_ownership_gain,
    tsumego_rescue_candidates,
    tsumego_region_stones_by_player,
    tsumego_score_best,
    tsumego_success_ownership,
)
from katrain.core.engine import REGION_AVOID_UNTIL_DEPTH, region_avoid_moves
from katrain.core.game import REGION_ANALYSIS_WIDE_ROOT_NOISE

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


def test_select_points_tie_prefers_most_searched():
    """gain も目数もノイズ同着なら visits 最多（KataGo の本命）を採る。

    実測 case J (2026-07-30, 13路詰碁 11手目): 正解 N10(v1175 pt-0.05 g+0.00) と
    別解 N11(v616 pt-0.07 g-0.02) が gain・目数とも 0.02 差の完全同着になり、
    目数タイブレークがノイズで N11 を選んでアプリの解答樹に無い別解を打った。
    両手とも白を殺せている（8000visits でも lead +5.5 / 白11子全滅で分離不能、
    同深さ検証も +43.97 vs +43.92 で margin 0.3 に遠く及ばない）ので、
    解答樹の本線と一致しやすい principal variation（visits 最多手）に寄せる。
    この対局の正解10手はすべて visits 最多手だった。
    """
    cands = [
        {"move": "N10", "pointsLost": -0.05, "visits": 1175, "ownership": ZERO},
        {"move": "N11", "pointsLost": -0.07, "visits": 616, "ownership": _own(x0_y0=-0.02)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "N10"


def test_select_real_points_gap_still_decides_by_points():
    # 目数差が points_epsilon を超える実信号（2026-07-29 の C12/D12 は 0.64 目差）なら
    # visits が少なくても従来どおり目数で決める
    cands = [
        {"move": "C12", "pointsLost": -0.31, "visits": 600, "ownership": ZERO},
        {"move": "D12", "pointsLost": 0.33, "visits": 1100, "ownership": _own(x0_y0=0.003)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "C12"


def test_select_points_epsilon_is_configurable():
    cands = [
        {"move": "N10", "pointsLost": -0.05, "visits": 1175, "ownership": ZERO},
        {"move": "N11", "pointsLost": -0.07, "visits": 616, "ownership": _own(x0_y0=-0.02)},
    ]
    # 0 で現行動作（目数最良のみ。同着バンドなし）
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, points_epsilon=0.0)["move"] == "N11"
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0, points_epsilon=0.25)["move"] == "N10"


def test_declass_demotes_ko_route_choice_to_clean_rival():
    """選択手がコウ経路で clean な対抗馬がいれば、そちら（visits 最多）に格下げする。

    実測 case K (2026-07-30, 13路左上): コウで殺す A12(v822 pt+0.02) と無条件の
    C13(v585 pt-0.05) が gain・目数とも同着になり、visits タイブレークがコウ側の
    A12 を選んで不正解（KataGo はコウも黒勝ちと読むのでスコアでは区別できない。
    差 0.02〜0.13 は 4/4 観測で C13 側に符号一貫＝無条件のわずかな期待値優位）。
    詰碁の正解順序 無条件 > コウ の適用。ko_routes は呼び出し側がリージョン
    子局面解析＋PV コウ検出で計算して渡す。
    """
    a12 = {"move": "A12", "pointsLost": 0.02, "visits": 822, "ownership": ZERO}
    c13 = {"move": "C13", "pointsLost": -0.05, "visits": 585, "ownership": _own(x0_y0=0.001)}
    pool = [a12, c13]
    # コウ経路情報が無ければ選択手のまま
    assert tsumego_declass_choice(a12, pool, frozenset())["move"] == "A12"
    # A12 がコウ経路なら無条件の C13 が勝つ
    assert tsumego_declass_choice(a12, pool, frozenset({"A12"}))["move"] == "C13"


def test_declass_keeps_choice_when_all_pool_moves_are_ko_routes():
    # 全員コウ経路（＝クラスが同じ）なら選択手を維持する
    a12 = {"move": "A12", "pointsLost": 0.02, "visits": 822, "ownership": ZERO}
    c13 = {"move": "C13", "pointsLost": -0.05, "visits": 585, "ownership": _own(x0_y0=0.001)}
    chosen = tsumego_declass_choice(a12, [a12, c13], frozenset({"A12", "C13"}))
    assert chosen["move"] == "A12"


def test_declass_covers_gain_separated_ko_choice():
    """コウ検査は同着バンドに限らず、成功クラス（目数ガード内）全体を対象にする。

    実測 case M (2026-07-30, 13路右下): コウ経路の M2 は L2/M3 の白石を「コウに
    勝つ前提」で取り切るため gain +1.76〜1.92 の**実信号**が出て、gain_epsilon の
    同着から抜け出しバンドが形成されず、旧検査（バンド2手以上が条件）が走らなかった。
    同深さ検証も +1.29 で M2 を追認する（クラス差はスコア系メトリックに現れない）ので、
    検証・救済のどの経路で選ばれても最後にクラスで裁定する。構造検出は 2/2 run 安定:
    M2 の子局面の白最善応手は K1 で、その PV の B M4（1子取り）がコウ形。K1 は clean。
    """
    m2 = {"move": "M2", "pointsLost": 0.56, "visits": 470, "ownership": _own(x0_y0=0.9)}
    k1 = {"move": "K1", "pointsLost": -0.06, "visits": 1316, "ownership": ZERO}
    chosen = tsumego_declass_choice(m2, [m2, k1], frozenset({"M2"}))
    assert chosen["move"] == "K1"


def test_declass_does_not_demote_to_a_score_inferior_clean_rival():
    """クラス裁定は同着の裁定であって、実測の目数差を覆す権限は無い。

    実測 case R (2026-07-31, 13路上辺・**枠なし**・初手): 正解は G13 → 白 J12 → 黒 J13 で
    コウにする問題で、G13 は目数最善（pt+0.03 v1345）。旧実装はコウ経路検査が G13 を
    正しくコウと判定した上で、詰碁と無関係な clean 手 D8（pt+0.55 v288）へ格下げして誤答した。

    **「無条件」は「何も起きないので自明に clean」でも成立してしまう**のに、格下げ先が本当に
    成功しているかは ply1 では測れない。実測（`class_screen_probe.py` 2run・同深さ800visits）:

        G13(正解/コウ) value +0.86/+0.97   自石 +0.71/+0.72  相手石 -0.70/-0.71
        D8 (誤答/clean) value +1.32/+2.34   自石 +0.76/+0.79  相手石 -0.72/-0.68

    ＝ownership は**誤答のほうが高く**、相手石は全候補で −0.55〜−0.72（どの手でも白は生きて
    いる＝答えがコウの問題では ply1 に成否が現れない）。`_ko_escape_choice` の採用検査
    （`tsumego_ko_escape_accepts`）をこちらに流用しても D8 は素通りする。

    唯一符号が一貫しているのは目数で、格下げが正しかった実測4ケースでは格下げ先が例外なく
    目数で**優る**（K −0.05 / L −0.11 / M −0.57 / P −0.03）のに対し case R の D8 は +0.52 劣る。
    同着バンド幅 `points_epsilon` を超えて劣る手には格下げしない（両側 0.26 以上の余裕）。
    """
    g13 = {"move": "G13", "pointsLost": 0.03, "visits": 1345, "ownership": ZERO}
    d8 = {"move": "D8", "pointsLost": 0.55, "visits": 288, "ownership": ZERO}
    j13 = {"move": "J13", "pointsLost": 0.93, "visits": 53, "ownership": ZERO}
    chosen = tsumego_declass_choice(g13, [g13, d8, j13], frozenset({"G13"}), points_epsilon=0.25)
    assert chosen["move"] == "G13"


def test_declass_points_tolerance_boundary():
    # 同着バンド（points_epsilon）以内なら従来どおり格下げする
    ko = {"move": "A1", "pointsLost": 0.0, "visits": 100, "ownership": ZERO}
    inside = {"move": "B1", "pointsLost": 0.25, "visits": 50, "ownership": ZERO}
    outside = {"move": "C1", "pointsLost": 0.26, "visits": 50, "ownership": ZERO}
    assert tsumego_declass_choice(ko, [ko, inside], frozenset({"A1"}), 0.25)["move"] == "B1"
    assert tsumego_declass_choice(ko, [ko, outside], frozenset({"A1"}), 0.25)["move"] == "A1"


def test_class_screen_all_ko_is_the_escape_trigger():
    """コウ脱出のトリガーは「pool が全員コウ」であって「格下げしなかった」ではない。

    脱出（`_ko_escape_choice`）の前提は「到達できる手が全部コウ＝無条件の正解はプールの外」。
    目数で劣る clean 手が**居る**のに脱出すると、前提が偽のまま root policy 上位を
    同深さ ownership で拾うことになり、case R のように ownership が成否と無関係な局面では
    でたらめな手に飛ぶ。格下げを断った理由（クラスが同じ／目数で劣る）を区別する。
    """
    ko1 = {"move": "A1", "pointsLost": 0.0, "visits": 100}
    ko2 = {"move": "B1", "pointsLost": 0.1, "visits": 50}
    clean = {"move": "C1", "pointsLost": 0.9, "visits": 50}
    assert tsumego_class_screen_all_ko([ko1, ko2], frozenset({"A1", "B1"}))
    assert not tsumego_class_screen_all_ko([ko1, clean], frozenset({"A1"}))


def test_class_screen_pool_is_choice_plus_guard_rivals_by_visits():
    """検査対象 = 選択手 + 目数ガードを通った対抗馬（visits 降順、計4手まで）。

    case M の実測値: eligible が {M2, K1} のとき、どちらが選択手でも pool は2手になる。
    """
    m2 = {"move": "M2", "pointsLost": 0.56, "visits": 470, "ownership": _own(x0_y0=0.9)}
    k1 = {"move": "K1", "pointsLost": -0.06, "visits": 1316, "ownership": ZERO}
    assert [c["move"] for c in tsumego_class_screen_pool(m2, [k1, m2])] == ["M2", "K1"]
    assert [c["move"] for c in tsumego_class_screen_pool(k1, [k1, m2])] == ["K1", "M2"]


def test_class_screen_pool_skips_outside_guard_choice():
    """目数ガード外から救済で採用した手はコウ経路検査にかけない（pool は選択手のみ）。

    実測 case F2 (2026-07-30): 枠なし盤の救済採用手 N11(pt+3.85、ガード外) は正解だが、
    子局面解析の応手が N9 に振れた run（3run 中 1）だけ PV にコウ形が出て格下げされ、
    ガード内の clean な J10 — 同深さ検証 -18.8 で N11 -17.0 に負けている**失敗手** — に
    差し替わった。クラス裁定（無条件 > コウ）が意味を持つのは「スコアが同じ成功と見なす
    帯（目数ガード）」の中だけ。帯の外から ownership 検証で拾った手は、スコアが嘘をつく
    枠なし局面（case G2 の圧縮）であり、帯内の clean な対抗馬は成功していない手でありうる。
    検証の実測をスコアの嘘で上書きしないため、pool を選択手だけにして検査を成立させない。
    """
    n11 = {"move": "N11", "pointsLost": 3.85, "visits": 124, "ownership": ZERO}
    j10 = {"move": "J10", "pointsLost": 0.23, "visits": 403, "ownership": ZERO}
    j11 = {"move": "J11", "pointsLost": 0.35, "visits": 300, "ownership": ZERO}
    assert [c["move"] for c in tsumego_class_screen_pool(n11, [j10, j11])] == ["N11"]


def test_competitive_replies_walks_all_contested_defenses():
    """コウ経路検査は「拮抗している応手」を全部歩く（top 1本だけでは応手分散で素通りする）。

    実測 case M (2026-07-30): B M2 の子局面の白応手は K1（コウ仕掛け）と M4（穏健）が
    v144 vs v103 で拮抗し、800visits の解析では top がどちらにも振れる。top 1本だけを
    歩く旧実装は M4 が top の run（3run 中 2）でコウを見逃した。守り方が選べる競争力の
    ある抵抗の中にコウがあるなら、その手はコウ経路（doomed な抵抗は visits 比で沈む）。
    """
    k1 = {"move": "K1", "visits": 144, "pv": ["K1", "M4"]}
    m4 = {"move": "M4", "visits": 103, "pv": ["M4"]}
    assert tsumego_competitive_replies([m4, k1]) == [k1, m4]
    # 支配的な応手が1本なら従来どおり1本だけ（K1 の子局面: M4 v230 vs M2 v27 = 比 0.12）
    m4d = {"move": "M4", "visits": 230, "pv": ["M4"]}
    m2 = {"move": "M2", "visits": 27, "pv": ["M2"]}
    assert tsumego_competitive_replies([m2, m4d]) == [m4d]
    # 上限3本（visits 降順）
    replies = [{"move": f"A{i}", "visits": 100 + i} for i in range(5)]
    assert [r["move"] for r in tsumego_competitive_replies(replies)] == ["A4", "A3", "A2"]
    assert tsumego_competitive_replies([]) == []


def test_ko_screen_reply_gate_is_asymmetric_between_choice_and_rivals():
    """選択手は敏感側の比、格下げ先候補は保守側の比で検査する。

    実測 case M（wRN=0・800visits・4 trial で不動）: M2 の子局面の応手は
    `M4 v663 / K1 v100 / 残り全部 v1` で、コウを仕掛ける K1 の比は **0.15**。
    保守側 0.5 では K1 が落ちて M2 が clean と読まれ、クラス裁定が丸ごと no-op になる
    （＝コウ手 M2 がそのまま打たれる。本番フロー 3/6 の誤答）。敏感側 0.05 なら拾える。

    逆に格下げ先まで 0.05 で検査すると case R の J13(0.10〜0.16)・D8(0.04〜0.05) が
    全部コウになり、全員コウ→脱出の誤爆になる（脱出の前提が偽）。単一の閾値では
    分離できない — 検出すべき最小比 0.09（case K A12）と、clean のままにすべき
    最大比 0.16（case R J13）が逆転しているため。
    """
    assert TSUMEGO_KO_REPLY_RATIO_CHOSEN < TSUMEGO_KO_REPLY_RATIO
    m4 = {"move": "M4", "visits": 663, "pv": ["M4", "K1"]}
    k1 = {"move": "K1", "visits": 100, "pv": ["K1", "M4", "M3"]}
    noise = [{"move": f"X{i}", "visits": 1, "pv": [f"X{i}"]} for i in range(3)]
    replies = noise + [k1, m4]
    assert [r["move"] for r in tsumego_competitive_replies(replies, TSUMEGO_KO_REPLY_RATIO)] == ["M4"]
    assert [r["move"] for r in tsumego_competitive_replies(replies, TSUMEGO_KO_REPLY_RATIO_CHOSEN)] == ["M4", "K1"]
    # 敏感側でも v1 のノイズ応手（比 0.0015）は拾わない
    assert all(r["visits"] > 1 for r in tsumego_competitive_replies(replies, TSUMEGO_KO_REPLY_RATIO_CHOSEN))


def test_ko_screen_turns_off_wide_root_noise():
    """応手の並びを証拠に使う検査では root ノイズを切る（比が run ごとに揺れるため）。

    wRN は着手選択で候補を広げるための設定で、1回の探索の間ずっと同じノイズが root policy に
    乗るので **visits を増やしても消えない**種類の揺れを作る。実測 case M（M2 の子局面）:
    wRN=0.04 で K1 の比が 0.44〜0.88 とばらつき本番フローで 3/6 検出漏れ、wRN=0 で 0.15 が
    4/4 不動。既存の `FRAME_VALIDITY_WIDE_ROOT_NOISE`（枠の生死裁定）と同じ判断。
    """
    assert TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE == 0.0
    assert REGION_ANALYSIS_WIDE_ROOT_NOISE > TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE  # 本譜の解析は従来どおり


def test_ko_screen_constrains_the_region_for_every_ply_it_walks():
    """コウ経路検査の子局面解析は、歩く深さぶんリージョン外を禁じて撃つ。

    既定のリージョン解析（untilDepth=1）が縛るのは root の着手選択だけで、**PV は ply2 以降
    枠へ自由に出ていける**。詰碁を読み切った KataGo にとって負けている側の局所の抵抗は枠の
    一点と同値なので、守り方の PV は肝心のコウを打たずに枠へ手抜きし、検査の証拠が消える。
    実測 case P (2026-07-31): 黒 H1 の子局面で白の最善応手 J1 の PV が untilDepth=1 では
    `J1,L2,J12`（ply3 で枠外）でコウ検出 1/4、untilDepth=6 では `J1,L2,G1` で 4/4。
    無条件の正解 J1 はどちらでも 4/4 clean（深く縛っても偽陽性は増えない）。
    """
    assert TSUMEGO_KO_REGION_UNTIL_DEPTH == TSUMEGO_TIE_KO_PLIES
    assert TSUMEGO_KO_REGION_UNTIL_DEPTH > REGION_AVOID_UNTIL_DEPTH
    region = [1, 2, 1, 2]  # 3x3 盤の右上 2x2 だけを残す
    avoid = region_avoid_moves(SIZE, region, TSUMEGO_KO_REGION_UNTIL_DEPTH)
    assert [entry["player"] for entry in avoid] == ["B", "W"]  # 両者を縛らないと守り方が枠へ逃げる
    for entry in avoid:
        assert entry["untilDepth"] == TSUMEGO_KO_REGION_UNTIL_DEPTH
        assert sorted(entry["moves"]) == ["A1", "A2", "A3", "B1", "C1"]
        assert "pass" not in entry["moves"]  # 局所で打つ手が無い側は pass できる（着手強制はしない）
    # 既定は upstream どおり untilDepth=1（本譜の候補評価の条件を変えない）
    assert all(entry["untilDepth"] == 1 for entry in region_avoid_moves(SIZE, region))


def test_class_screen_pool_caps_rivals():
    # 対抗馬は visits 降順で、選択手込み計4手（TSUMEGO_TIE_KO_MAX_CANDIDATES）まで
    eligible = [
        {"move": f"A{i}", "pointsLost": 0.1 * i, "visits": 100 * i, "ownership": ZERO} for i in range(1, 6)
    ]
    pool = tsumego_class_screen_pool(eligible[0], eligible)
    assert [c["move"] for c in pool] == ["A1", "A5", "A4", "A3"]


def test_selection_band_returns_the_tie_members():
    # generate_move 側がコウ検査の対象（同着バンド）を知るための入口
    cands = [
        {"move": "A12", "pointsLost": 0.02, "visits": 822, "ownership": ZERO},
        {"move": "C13", "pointsLost": -0.05, "visits": 585, "ownership": _own(x0_y0=0.001)},
        {"move": "A11", "pointsLost": 21.13, "visits": 6, "ownership": _own(x0_y0=-1.0)},
    ]
    band = tsumego_selection_band(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert sorted(c["move"] for c in band) == ["A12", "C13"]


def test_no_verify_inside_the_points_tie_band():
    """同着バンド内の選択（visits タイブレーク）は同深さ検証にかけない。

    実測 case J 再発 (2026-07-30 GUI): select_tsumego_move は N10 を選んだが、
    「選択手 ≠ 目数最善」の無条件検証が発動し、等価な2手は margin 0.3 で
    分離できない（実測差 +0.05）ため必ず却下 → 目数最善 N11 に巻き戻り、
    同着タイブレークが丸ごと無効化された。バンド内の選択は「gain が良いから
    覆す」ではなく「等価なので PV に寄せる」なので検証の対象外とする。
    """
    score_best = {"move": "N11", "pointsLost": -0.03}
    chosen = {"move": "N10", "pointsLost": 0.01}  # 差 0.04 <= 0.25: 同着バンド内
    assert not tsumego_needs_score_best_verify(chosen, score_best, 0.25)


def test_verify_still_required_for_real_gain_overrides():
    # 目数を本当に犠牲にする gain 覆し（case B/C/F 系）は従来どおり検証必須
    score_best = {"move": "A1", "pointsLost": 0.0}
    chosen = {"move": "B1", "pointsLost": 1.5}
    assert tsumego_needs_score_best_verify(chosen, score_best, 0.25)
    # 境界: ちょうど points_epsilon は同着側（バンドの <= と揃える）
    assert not tsumego_needs_score_best_verify({"move": "B1", "pointsLost": 0.25}, score_best, 0.25)


def test_select_points_tie_without_visit_info_keeps_points_order():
    # visits の無い解析結果（テスト等）ではバンド内でも従来どおり目数で決める
    cands = [
        {"move": "A1", "pointsLost": 0.1, "ownership": ZERO},
        {"move": "B1", "pointsLost": 0.0, "ownership": _own(x0_y0=0.01)},
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


# --- 目数だけでは成否を判定できない（実測 2026-07-31、既存16ケースの横断計測）---
# 枠の代償地帯が未決着だとスコアが詰碁の成否から切り離される。実測の食い違い2件はどちらも
# 「目数は成功と言うが関係石は生きている」方向:
#
#   case Q  枠あり  +10.45目  相手石 -0.99/子（12子すべて生存）  ← 全盤最善手が枠の充填部 B9
#   case H  枠なし  +27.69目  相手石 -0.15/子
#
# 成功している局面（D/E/J/K/L/M/O/P）は +0.94〜+1.00 なので、境界には 1.09 の空白がある。
CASE_Q_LEAD, CASE_Q_OPP_OWN = 10.45, -0.99
CASE_H_LEAD, CASE_H_OPP_OWN = 27.69, -0.15
SOLVED_OPP_OWN = 1.00


def test_success_ownership_takes_the_stricter_side():
    """自石・相手石の 1子平均のうち小さいほうを採る（どちらの詰碁か戦略に渡っていないため）。"""
    # 黒番。自石 (0,0) は生きている(+1)、相手石 (1,1) も相手のもの(-1)=殺せていない
    own = _own(x0_y0=1.0, x1_y1=-1.0)
    assert tsumego_success_ownership(own, [(0, 0)], [(1, 1)], SIZE, +1) == pytest.approx(-1.0)
    # 相手石も取り切っていれば両方 +1
    own = _own(x0_y0=1.0, x1_y1=1.0)
    assert tsumego_success_ownership(own, [(0, 0)], [(1, 1)], SIZE, +1) == pytest.approx(1.0)
    # 白番は符号が反転する
    own = _own(x0_y0=-1.0, x1_y1=-1.0)
    assert tsumego_success_ownership(own, [(0, 0)], [(1, 1)], SIZE, -1) == pytest.approx(1.0)


def test_success_ownership_is_none_without_stones():
    # 判定材料が無ければ None（呼び出し側は ownership の条件を課さない）
    assert tsumego_success_ownership(ZERO, [], [], SIZE, +1) is None


def test_success_ownership_is_none_without_ownership():
    # _enable_ownership=false 等で ownership が取れない経路。ここで落ちると最善手
    # フォールバックごと壊れるので、判定材料なしとして None を返す
    assert tsumego_success_ownership(None, [(0, 0)], [(1, 1)], SIZE, +1) is None
    assert tsumego_success_ownership([], [(0, 0)], [(1, 1)], SIZE, +1) is None
    # そのぶん振り分けは従来どおり目数だけになる
    assert tsumego_already_succeeded(CASE_Q_LEAD, success_ownership=None)


def test_success_ownership_averages_per_stone():
    # 石数で割るので、石数の違う問題どうしで同じ閾値が使える
    own = _own(x0_y0=1.0, x1_y1=0.0)
    assert tsumego_success_ownership(own, [(0, 0), (1, 1)], [], SIZE, +1) == pytest.approx(0.5)


def test_score_alone_would_skip_the_ko_route_on_unsolved_positions():
    """実測の食い違い3件: 目数だけ見ると「既に成功」と誤判定する。"""
    assert tsumego_already_succeeded(CASE_Q_LEAD)  # 目数だけなら成功扱い
    assert tsumego_already_succeeded(CASE_H_LEAD)
    # ownership を渡すと成功扱いされない＝コウ機構をスキップしない
    assert not tsumego_already_succeeded(CASE_Q_LEAD, success_ownership=CASE_Q_OPP_OWN)
    assert not tsumego_already_succeeded(CASE_H_LEAD, success_ownership=CASE_H_OPP_OWN)


def test_solved_positions_still_skip_the_ko_route():
    # 本当に成功している局面（相手石が飽和）はこれまでどおりスキップする
    assert tsumego_already_succeeded(CASE_Q_LEAD, success_ownership=SOLVED_OPP_OWN)


def test_ownership_check_only_tightens_the_gate():
    """ownership が成功と言っても、目数が失敗ならスキップしない（判定は厳しくなる方向だけ）。"""
    assert not tsumego_already_succeeded(-1.0, success_ownership=SOLVED_OPP_OWN)


def test_region_stones_split_by_player():
    stones = [
        SimpleNamespace(player="B", coords=(0, 0)),
        SimpleNamespace(player="W", coords=(1, 1)),
        SimpleNamespace(player="B", coords=(2, 2)),  # リージョン外
    ]
    own, opp = tsumego_region_stones_by_player(stones, [0, 1, 0, 1], "B")
    assert own == [(0, 0)]
    assert opp == [(1, 1)]
    # リージョンが無ければ全石
    own, opp = tsumego_region_stones_by_player(stones, None, "B")
    assert own == [(0, 0), (2, 2)]
    assert opp == [(1, 1)]


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


# --- コウ一色バンドからの脱出（case O 2026-07-31） -------------------------------------
# 実測: 13路左上、黒番初手。root 1800visits の visit 配分は B12 1172 / C10 622 で、残り46手は
# すべて v1。正解 A11 は 12000visits でも v1 のまま（1visit 評価は pt+28.74 / 白石 own -7.03 =
# 生き だが、子局面を独立に 1800visits で測ると +11.53目 / 白10子すべて +0.99 = 全滅）。
# 目数ガード内の B12/C10 はどちらもコウ経路なので、既存のコウ経路検査は「clean な対抗馬なし」で
# 維持を選ぶしかなかった。正解は pool の外＝root policy の上位にいる。
CASE_O_PRIORS = [
    {"move": "B12", "prior": 0.68056, "visits": 1172},
    {"move": "C10", "prior": 0.22802, "visits": 622},
    {"move": "B13", "prior": 0.05466, "visits": 1},
    {"move": "C13", "prior": 0.01247, "visits": 1},
    {"move": "A11", "prior": 0.00914, "visits": 1},  # 正解
    {"move": "A8", "prior": 0.00089, "visits": 1},
    {"move": "H5", "prior": 0.00011, "visits": 1},
    {"move": "H13", "prior": 0.00010, "visits": 1},
    {"move": "pass", "prior": 0.00010, "visits": 1},
]


def test_ko_escape_shortlist_is_the_unscreened_policy_top():
    # 検査済み（コウ経路と分かっている）B12/C10 を除いた policy 上位を返す。
    # A11 は prior 5位（2/2 run で固定）なので、上限4なら確実に入る
    out = tsumego_ko_escape_candidates(CASE_O_PRIORS, {"B12", "C10"}, min_prior=0.001, max_candidates=4)
    assert [c["move"] for c in out] == ["B13", "C13", "A11"]


def test_ko_escape_shortlist_drops_the_policy_floor():
    # 48手中42手が prior 0.0001（NN の下限）に張り付く。A11(0.0091) と A8(0.00089) の間に
    # 10倍の崖があるので、下限を切れば「NN が読む価値を認めた手」だけが残る
    out = tsumego_ko_escape_candidates(CASE_O_PRIORS, set(), min_prior=0.001, max_candidates=99)
    assert [c["move"] for c in out] == ["B12", "C10", "B13", "C13", "A11"]


def test_ko_escape_shortlist_never_returns_pass():
    out = tsumego_ko_escape_candidates(
        [{"move": "pass", "prior": 0.9, "visits": 1}], set(), min_prior=0.0, max_candidates=4
    )
    assert out == []


def test_ko_escape_shortlist_caps_the_number_of_candidates():
    # 候補ごとに同深さ解析1本のコストがかかるので上限を設ける
    out = tsumego_ko_escape_candidates(CASE_O_PRIORS, set(), min_prior=0.0, max_candidates=2)
    assert [c["move"] for c in out] == ["B12", "C10"]


def test_ko_escape_accepts_a_clean_move_that_does_not_outscore_the_ko():
    # **この不等号の向きがこの修正の要**。コウ手のスコアは「コウに勝った前提」で出るので
    # 無条件の正解よりわずかに高い（実測 同深さ800visits: B12 +9.95 / A11 +9.91）。
    # 既存の覆し（gain_verify_margin=0.3 超えで上回ること）を使うと正解が却下される
    assert tsumego_ko_escape_accepts(9.91, 9.95, tolerance=0.5)


def test_ko_escape_rejects_a_clean_move_that_fails_to_kill():
    # clean でも詰碁が成立していない手は落とす。実測 case O: 失敗する clean 手 C13 -9.98 /
    # B13 -9.99 / A8 -10.00 に対し正解 A11 +9.91 で差 20 なので、tolerance 0.5 で十分分離できる
    assert not tsumego_ko_escape_accepts(-9.98, 9.95, tolerance=0.5)
    assert not tsumego_ko_escape_accepts(-9.99, 9.95, tolerance=0.5)


def test_ko_escape_tolerance_boundary():
    assert tsumego_ko_escape_accepts(9.45, 9.95, tolerance=0.5)
    assert not tsumego_ko_escape_accepts(9.44, 9.95, tolerance=0.5)
