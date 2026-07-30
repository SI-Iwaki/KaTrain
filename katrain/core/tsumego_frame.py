from collections import namedtuple

from katrain.core.game_node import GameNode
from katrain.core.sgf_parser import Move

# tsumego frame ported from lizgoban by kaorahi
# note: coords = (j, i) in katrain

near_to_edge = 2
offence_to_win = 5
cluster_gap = 4  # 主クラスタ判定: この距離(Chebyshev)以内の石を同一クラスタとみなす
CORE_MIN_FRACTION = 0.6  # コア絞り込みで残す最小割合。本体を削りすぎる縮小を却下する

BLACK = "B"
WHITE = "W"


def tsumego_frame_from_katrain_game(game, komi, black_to_play_p, ko_p, margin):
    current_node = game.current_node
    bw_board = [[game.chains[c][0].player if c >= 0 else "-" for c in line] for line in game.board]
    isize, jsize = ij_sizes(bw_board)
    blacks, whites, analysis_region = tsumego_frame(bw_board, komi, black_to_play_p, ko_p, margin)

    # 既存石と重なる枠石は配置しない。占有点への AB/AW は同色でも
    # _validate_move_and_update_chains が "Space occupied" で弾き、
    # _init_chains が Exception に昇格させてゲームが壊れる
    occupied = {(i, j) for i, row in enumerate(bw_board) for j, v in enumerate(row) if v != "-"}
    blacks = [ij for ij in blacks if ij not in occupied]
    whites = [ij for ij in whites if ij not in occupied]

    sgf_blacks = katrain_sgf_from_ijs(blacks, isize, jsize, "B")
    sgf_whites = katrain_sgf_from_ijs(whites, isize, jsize, "W")

    played_node = GameNode(parent=current_node, properties={"AB": sgf_blacks, "AW": sgf_whites})  # this inserts

    katrain_region = analysis_region and (analysis_region[1], analysis_region[0])
    return (played_node, katrain_region)


def katrain_sgf_from_ijs(ijs, isize, jsize, player):
    return [Move((j, i)).sgf((jsize, isize)) for i, j in ijs]


def build_frame(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core):
    """枠を張って (完成した石配列, region) を返す。tsumego_frame / tsumego_frame_board の共通部"""
    sizes = ij_sizes(bw_board)
    # 9路以下では margin=4（13/19路向け）だと枠矩形が盤外にはみ出して壁・充填が置けず、
    # 解析リージョンも全盤（→None正規化→全盤解析）に退化するため、収まる値にクランプする
    if min(sizes) <= 9:
        margin = min(margin, 2)
        # 9路以下では非コア石削除を無効化する。コア絞り込み（gap縮小、mark_core_stones）
        # 自体は枠の幾何成立に必要なので残すが、盤が小さいと詰碁本体でも石同士の
        # Chebyshev距離が容易にgapを超え、「連結ギャップが大きい＝問題と無関係」という
        # 前提が成り立たない（実例: 9路で本体からChebyshev距離2のW石が非コア判定され、
        # drop_non_core_stonesで消去後、put_outsideに別解でBとして再充填される＝盤面が
        # 別問題にすり替わる）。ここで drop_non_core を False に落として呼び出し自体を止める
        drop_non_core = False
    stones = stones_from_bw_board(bw_board)
    core_bbox = mark_core_stones(stones, komi, margin)
    filled_stones = tsumego_frame_stones(stones, komi, black_to_play_p, ko_p, margin, drop_non_core)
    region = get_analysis_region(pick_all(filled_stones, "tsumego_frame_region_mark"))
    if not region or covers_board_p(region, sizes):
        region = fallback_region(core_bbox, sizes) or region
    return (filled_stones, region)


def tsumego_frame(bw_board, komi, black_to_play_p, ko_p, margin):
    filled_stones, region = build_frame(bw_board, komi, black_to_play_p, ko_p, margin, False)
    bw = pick_all(filled_stones, "tsumego_frame")
    blacks = [(i, j) for i, j, black in bw if black]
    whites = [(i, j) for i, j, black in bw if not black]
    return (blacks, whites, region)


def tsumego_frame_board(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core=True):
    """枠適用後の完成した盤グリッド ("B"/"W"/"-") と region を返す。

    キャプチャ経路はこれを単一の AB/AW として SGF 化し新規局にする。既存局面に枠ノードを
    足す方式と違い、非コア石の除去ができ（SGF の AE は engine.py が解析を拒否するため使えない）、
    占有点への重複配置も構造的に起きない。
    """
    filled_stones, region = build_frame(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core)
    board = [
        [(BLACK if h.get("black") else WHITE) if h.get("stone") else "-" for h in row] for row in filled_stones
    ]
    return (board, region)


def frame_balance_distance(root_score_lead):
    """枠バランスの悪さ。0 に近いほど枠が設計どおり働いている。

    枠は「攻め方が成功したら offence_to_win(5) 目勝ち」に調整する設計なので、|lead| が
    そこから離れているほど枠が壊れている（守り側が無条件生きで攻め方に勝ち目がない、
    逆に攻め方が得をしすぎている等）。攻め方がどちらの色かを知らなくて済むよう絶対値で見る。
    """
    return abs(abs(root_score_lead) - offence_to_win)


FRAME_BALANCE_TIE_MARGIN = 2.0  # この差以内は同点とみなし、攻め方コウダテのある枠を採る

# 採用した枠がこの距離を超えていたら警告する。枠は成功／失敗が約10目離れる設計なので、
# その半分を超えるズレは「絶対スコアに依る判定（既に成功・コウ勝ち前提）が信用できない」域。
# 実測 2026-07-30（case F: 13路右上の大型詰碁）: 攻め方×コウダテの4通りとも -25.5/-33.4/
# -48.3/-73.7目で、最良でも距離 20.5。リージョンが盤の53%（90/169点）を占めるとリージョン内の
# 空き地がまるごと片側の地になり、この設計（攻め方成功=5目勝ち）が成立しない
FRAME_BALANCE_WARN_DISTANCE = 8.0


# 枠を採用してよいかの判定。詰碁は「必ず正解手がある」前提の出題なので、開始時点で解く側
# （手番側）の石が相手の地と読まれている枠は、枠が問題そのものを壊している（正解手があるなら
# 開始時点で全滅しているはずがない）。この判定は枠バランスでは代替できない: 枠は「想定した
# 攻め方が成功したら offence_to_win 目勝ち」に調整するので、攻め方の推定が反転していても
# 想定攻め方が実際に成功する＝バランスは完璧に見える（実測 2026-07-30 case G: 距離 2.1 で
# 過去最良なのに黒の攻め石は全滅、19路に置き直しても距離 5.4 で同じ）
# 手番側の本体石はこの ownership（1子平均）以上で「明確に生きている」とみなす。0 ではなく
# 0.5 なのは、実測で正常な枠が +1.00/子（完全生存）に対し壊れた枠の1つが -0.09/子 と 0 付近に
# 来たため（case F の ko=False 枠）。0 だと run ごとに符号が反転して枠採否が入れ替わる
FRAME_SOLVER_ALIVE_OWNERSHIP = 0.5

# 上の判定で「死」と出た枠を捨てる前に読み直すときの visits と wideRootNoise。生き問題では
# 手番側の石そのものが戦いの対象なので、浅い読み・散らした読みでは有効な枠も死と出る。
# 実測 2026-07-30 case N（黒番の生き・有効な枠）の1子平均、**プロセスを分けた独立サンプル**
# （同一プロセスの再クエリは NN キャッシュが効いて独立にならない。engine 起動を挟んで測ること）:
#
#   wRN=0.04（着手選択と同じ設定）
#     400visits   -0.69 / -0.80 / -0.98                          … 全部「死」＝枠を捨てる
#    1800visits   +0.95 +0.93 +0.78 +0.92 +0.42 -0.02 -0.08 -0.23 -0.95  … 二峰性でコイン投げ
#    3000visits   +0.85 / +0.28 / +0.91                          … まだ閾値をまたぐ
#    6000visits   +0.96 / +0.98 / +0.99 / +1.00                  … 生きで安定（1本 4.8〜8.4秒）
#   wRN=0（この判定用）
#    1800visits   +0.97 / +0.97 / +0.96 / +0.96                  … 生きで安定（1本 約1.3秒）
#
# 二峰性の正体は深さ不足ではなく **wideRootNoise による探索の分散**だった。wRN は着手選択で
# 候補リストを広げるための設定で、「手番側が生きているか」という裁定には害しかない（root の
# 探索が critical line に集中できず ownership が決着しない）。wRN=0 なら 1800visits で分離が
# 桁違いに明確になる（case N +0.96 に対し、壊れた枠は case F -0.67/-0.76・case G -0.98）。
FRAME_VALIDITY_VISITS = 1800
FRAME_VALIDITY_WIDE_ROOT_NOISE = 0.0

# 「壊れている」と判定された枠を、それでも枠なしより残すべきかの差（手番側コアの1子平均）。
# 実測 2026-07-30（枠は読み直しの設定、枠なしは trial 400visits。枠は ko の2通り）:
#   case F -0.72 / -0.96  vs 枠なし -0.70   → 枠なしが上（従来どおり枠を捨てる）
#   case G -0.98 / -0.99  vs 枠なし -0.68   → 同上
#   case N +0.96 / -0.99  vs 枠なし -0.75   → 枠が 1.7 上回る（ただし読み直しで usable なので
#                                             この比較には来ない＝深い読みでも死と出る難問の保険）
# 残すべき側（+1.7）と落とすべき側（-0.02〜-0.31）の間で、run 間分散を吸収できる 0.5
FRAME_OVER_FRAMELESS_MARGIN = 0.5


def frame_solver_verdict(readings, stone_count, threshold=FRAME_SOLVER_ALIVE_OWNERSHIP):
    """手番側の本体石の読み [(visits, solver_ownership), ...] から枠の採否を裁定する。

    最も深い読み（visits 最大・同数なら後の読み）だけで判定する。浅い読みは深い読みが
    取れなかったときの保険で、取れているなら混ぜない（平均すると浅いノイズが復活する）。
    ownership が None の読み（解析失敗）は無かったものとして扱うので、深い読み直しに
    失敗した場合は浅い読みの判定＝枠を捨てる（現行動作）に落ちる。

    returns (詰碁を壊しているか, 判定に使った visits, 判定に使った ownership)
    """
    usable = [(visits, own) for visits, own in readings if own is not None]
    if not usable:
        return False, None, None  # 読めていない枠は判定できない（frame_destroys_problem と同じ扱い）
    visits, own = sorted(usable, key=lambda reading: reading[0])[-1]  # 安定ソート＝同 visits なら後の読み
    return frame_destroys_problem(own, stone_count, threshold), visits, own


FrameVerdict = namedtuple("FrameVerdict", "ko_p board region lead destroys visits ownership stone_count readings")


def frame_validity_verdicts(candidates, read, trial_visits, validity_visits=FRAME_VALIDITY_VISITS):
    """枠候補 [(ko_p, board, region), ...] を「詰碁を壊していないか」で裁定して FrameVerdict を返す。

    read(candidate, visits) -> (root_score_lead, solver_ownership, stone_count) は呼び出し側が
    与える（解析とログは呼び出し側の仕事。この関数は解析の深さの使い分けだけを決める）。

    浅い読み（trial_visits）で死と出た枠は**捨てる前に validity_visits で読み直す**。捨てた先の
    枠なしは安全側ではないので、浅いノイズで枠を手放してはいけない（`FRAME_VALIDITY_VISITS`）。
    lead は判定に使った読みの値（深い読みが取れなければ浅い方）。

    読み直しはキャプチャの待ち時間に直接乗る（実測 1本 1.5〜1.9秒）ので本数を絞る:
    生きている枠は読み直さない、読み直しは**浅い読みが生きに近い枠から順に**行い、**有効な枠が
    1つ出た時点で打ち切る**（残りは浅い判定のまま捨てる＝この修正前の動作）。case N の実測では
    生き残る枠 ko=False の浅い読みは -0.69〜-0.98/子 で、落選する ko=True の -0.99/子 より 4/4 で
    上だった。同点・読めなかった枠は候補順（設定の frame_ko が先）。
    """
    verdicts = [None] * len(candidates)
    for i, candidate in enumerate(candidates):
        ko_p, board, region = candidate
        lead, own, n_stones = read(candidate, trial_visits)
        readings = [(trial_visits, own)]
        destroys, visits, used_own = frame_solver_verdict(readings, n_stones)
        verdicts[i] = FrameVerdict(ko_p, board, region, lead, destroys, visits, used_own, n_stones, readings)
    if validity_visits <= trial_visits:
        return verdicts

    def aliveness(i):  # 生きに近い順。読めなかった枠は最後（順位付けできない）
        v = verdicts[i]
        return (0, 0.0) if v.ownership is None or not v.stone_count else (1, v.ownership / v.stone_count)

    for i in sorted((i for i, v in enumerate(verdicts) if v.destroys), key=aliveness, reverse=True):
        if any(not v.destroys for v in verdicts):
            break  # 有効な枠が既にある＝残りを深く読んでも出題する枠は変わらない
        deep_lead, deep_own, n_stones = read(candidates[i], validity_visits)
        readings = verdicts[i].readings + [(validity_visits, deep_own)]
        destroys, visits, used_own = frame_solver_verdict(readings, n_stones)
        lead = verdicts[i].lead if deep_lead is None else deep_lead  # バランス判定も深い読みの方が確か
        verdicts[i] = verdicts[i]._replace(
            lead=lead, destroys=destroys, visits=visits, ownership=used_own, stone_count=n_stones, readings=readings
        )
    return verdicts


def frame_over_frameless(verdicts, frameless_ownership, frameless_stone_count, margin=FRAME_OVER_FRAMELESS_MARGIN):
    """全枠が「壊れている」判定でも、枠なし盤より手番側コアが明確に生きている枠があれば返す。

    枠なしは安全側のフォールバックではない。リージョン外が丸ごと相手の地になるので、枠より
    激しく詰碁を壊すことがある（実測 2026-07-30 case N: 枠なし -0.75/子 に対し有効な枠は
    +0.96/子）。逆に枠が本当に壊れている case F/G は枠 -0.72〜-0.99/子 に対し枠なしが
    -0.68〜-0.70/子 と上回るので、従来どおり枠なしに落ちる。

    比較は1子平均（盤ごとに対象石数が違いうる）。差が margin 未満なら枠を残さない。
    枠なしを読めなかった場合は比較しない＝従来動作（枠を捨てる）に落ちる。

    **枠なし側は浅い読みで足りる**（枠と違って深さにほぼ不感）。実測 400/1800/6000visits の1子平均は
    case N -0.75/-0.79/-0.77、case F -0.70/-0.65/-0.64、case G -0.65/-0.63/-0.68 で最大差 0.06、
    margin 0.5 に対して十分小さい。枠なし盤では手番側の石の生死がリージョン外の地で決まっていて
    読みの深さで動かないため（＝この盤で詰碁が消えているという判断そのもの）。

    `FRAME_VALIDITY_WIDE_ROOT_NOISE` で読み直すようになった後は、この比較が結論を変える実測ケースは
    無い（case N は「生き」で安定して usable 側に出る）。wRN=0.04 で読み直していた時期には
    -0.23/-0.08 と出た run をこれが拾って正解にしていた（3run 中 2）ので、それでも死と出る
    難問への保険として残す。
    """
    if frameless_ownership is None:
        return None
    frameless_average = frameless_ownership / max(1, frameless_stone_count)
    usable = [v for v in verdicts if v.ownership is not None and v.stone_count]
    if not usable:
        return None
    best = max(usable, key=lambda v: v.ownership / v.stone_count)
    return best if best.ownership / best.stone_count - frameless_average > margin else None


def solver_core_points(recognized, framed, region, player=BLACK):
    """枠の壁・充填を除いた「問題本体の手番側の石」の (x, y) 座標列（ownership 添字順）。

    認識盤（枠を張る前）と枠付き盤の両方に同じ色で存在する点だけを採る。壁・充填は認識盤に
    無いので落ち、drop_non_core で消えた石は枠付き盤に無いので落ちる。壁石を混ぜてはいけない
    のは、壁が自明に生きていて判定を埋もれさせるため（実測 case D: 壁込み +25.00/25 で常に
    正常判定、本体だけなら +8.00/8 と本来の値になる）。
    """
    isize, jsize = ij_sizes(framed)
    if region:
        (imin, imax), (jmin, jmax) = region
    else:
        imin, imax, jmin, jmax = 0, isize - 1, 0, jsize - 1
    return [
        (j, isize - 1 - i)
        for i in range(max(0, imin), min(isize - 1, imax) + 1)
        for j in range(max(0, jmin), min(jsize - 1, jmax) + 1)
        if recognized[i][j] == player and framed[i][j] == player
    ]


def frame_destroys_problem(solver_ownership, stone_count, threshold=FRAME_SOLVER_ALIVE_OWNERSHIP):
    """手番側の本体石が平均で生きていると読まれなければ True（この枠では詰碁が解けない）。

    実測 2026-07-30（trial 400visits、リージョン内の本体石のみ、手番=黒。枠は ko の2通り）:

        case D  +8.00/8  +1.00/子 ／ +8.00/8  +1.00/子   正常 → 枠を使う（正解 A4）
        case E +21.98/22 +1.00/子 ／ +21.95/22 +1.00/子  正常 → 枠を使う（正解 K1）
        case F  -0.98/11 -0.09/子 ／ -10.33/11 -0.94/子  壊れ → 枠なしで正解 N8
        case G -10.76/11 -0.98/子 ／ -10.85/11 -0.99/子  壊れ → 枠なしで正解 A11
                                                        （枠ありは誤答 B13＝この判定の動機）

    非対称性に注意: 殺し問題では手番側の攻め石が壁と連絡して自明に +1.00 になるので判定は
    安全だが、生き問題では手番側の石自体が戦いの対象で、この判定は実質「エンジンがその詰碁を
    解けたか」を聞いている。**浅い読みでは必ず死側に倒れる**ので、単発の読みでこの関数の結果を
    信じてはいけない（`frame_validity_verdicts` 経由で `FRAME_VALIDITY_VISITS` の読み直しを通す）。
    2026-07-30 case N はこの偽陽性で有効な枠を捨て、枠なし盤（root -75目・手番側コア -0.75/子）で
    詰碁が消えて誤答した。**枠なしは安全側のフォールバックではない**（`frame_over_frameless`）。
    """
    if not stone_count:
        return False
    return solver_ownership / stone_count < threshold


def pick_balanced_frame(candidates, tie_margin=FRAME_BALANCE_TIE_MARGIN):
    """[(ko_p, board, region, root_score_lead), ...] から採用する枠を返す。選べなければ None。

    正解がコウ止まりの詰碁では、守り側にコウダテ形が渡る枠（ko_p=False）だと
    コウを守り側が勝つ＝守り側の無条件生きになり、攻め方に勝ち目がなくなる
    （実測 2026-07-29: ko_p=False で -24.0、ko_p=True で +1.9）。逆にコウでない問題に
    攻め方コウダテを渡すと今度は攻め方が得をしすぎる（+2.8 → +14.8）。どちらが正しいかは
    問題ごとに違うので、両方の枠を張って root スコアが設計目標に近い方を採る。

    バランス距離が tie_margin 以内で拮抗している場合は **攻め方にコウダテを渡す枠**を採る。
    詰碁はコウダテがあるものとして正解が決まるので、迷ったら攻め方に渡すほうが慣習に近い
    （実測 2026-07-30: 距離 12.36 vs 11.61 の僅差でキャプチャごとに枠が入れ替わり、
    守り側コウダテを引いた回はコウの正解手が無価値になって誤答した）。

    lead が None（解析失敗）の候補は除外する。
    """
    scored = [c for c in candidates if c[3] is not None]
    if not scored:
        return None
    best = min(frame_balance_distance(c[3]) for c in scored)
    finalists = [c for c in scored if frame_balance_distance(c[3]) <= best + tie_margin]
    for candidate in finalists:
        if candidate[0]:  # ko_p=True: 攻め方にコウダテ形が渡る枠
            return candidate
    return finalists[0]


def fit_margin(sizes, komi, margin, imin, jmin, imax, jmax, occupied=None):
    """外側（枠矩形の外）に守り側の代償地帯 defense_area 相当が確保できる最大の margin を返す。

    put_outside は外側セルを守り側に defense_area（約 (盤面積-コミ-5)/2 ）だけ配分する設計
    だが、外側がそれ未満だと配分しきれず枠ゲームが一方的になる。確保できる margin がない
    場合は None を返す（呼び出し側が元の margin にフォールバックする）。

    occupied を渡すと、面積条件を満たす margin のうち境界線に石が乗らないものを優先する
    （壁が既存石を踏むと placement から除外されて壁に穴が空くため）。
    どれも踏む場合は面積条件を満たす最大の margin を返す。
    """
    isize, jsize = sizes
    needed = (isize * jsize - abs(komi) - offence_to_win) / 2
    fits = []
    for m in range(margin, 0, -1):
        i0, i1 = max(0, imin - m), min(isize - 1, imax + m)
        j0, j1 = max(0, jmin - m), min(jsize - 1, jmax + m)
        outside = isize * jsize - (i1 - i0 + 1) * (j1 - j0 + 1)
        if outside >= needed:
            fits.append((m, (i0, i1, j0, j1)))
    if not fits:
        return None
    if occupied:
        for m, (i0, i1, j0, j1) in fits:
            border = {(i, j) for i in (i0, i1) for j in range(j0, j1 + 1)}
            border |= {(i, j) for j in (j0, j1) for i in range(i0, i1 + 1)}
            if not (border & occupied):
                return m
    return fits[0][0]


def snapped_bbox(entries, sizes):
    """(i, j, ...) の列から、端スナップ済みの bbox (imin, jmin, imax, jmax) を返す"""
    isize, jsize = sizes
    return (
        snap0(min(e[0] for e in entries)),
        snap0(min(e[1] for e in entries)),
        snapS(max(e[0] for e in entries), isize),
        snapS(max(e[1] for e in entries), jsize),
    )


def mark_core_stones(stones, komi, margin):
    """詰碁本体（コア）の石に tsumego_core を立て、採用範囲の snap 済み bbox を返す。

    全石の bbox で枠が成立する（fit_margin が margin を返す）なら絞らない＝従来動作。
    成立しないときだけ、近接クラスタの gap を段階的に縮めて本体を切り出す。

    gap を小さくすると最大クラスタは縮み bbox も縮むので外側面積は増える＝面積テストは
    gap に対して単調。よって「降順で最初に通る gap」＝「通る中で最大の gap」であり、
    石対の距離を1回だけ走査して gap 昇順に増分 union すれば O(n^2) 1パスで求まる。

    マークは石の dict に付ける。flip_stones は同じ dict オブジェクトを新しい配列へ移すだけ
    なので、マークは転置・反転を越えて tsumego_frame_stones の再帰の全段で保持される。
    """
    sizes = ij_sizes(stones)
    entries = [(i, j, h) for i, row in enumerate(stones) for j, h in enumerate(row) if h.get("stone")]
    if not entries:
        return (0, 0, 0, 0)
    all_bbox = snapped_bbox(entries, sizes)
    if fit_margin(sizes, komi, margin, *all_bbox) is not None:
        return all_bbox

    n = len(entries)
    edges = [[] for _ in range(cluster_gap + 1)]
    for a in range(n):
        ia, ja, _h = entries[a]
        for b in range(a + 1, n):
            d = max(abs(ia - entries[b][0]), abs(ja - entries[b][1]))
            if d <= cluster_gap:
                edges[d].append((a, b))
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    best = None
    for gap in range(1, cluster_gap + 1):
        for a, b in edges[gap]:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
        groups = {}
        for a in range(n):
            groups.setdefault(find(a), []).append(entries[a])
        # 同数クラスタのタイは bbox が小さい方 → 上 → 左 の順で決定的に選ぶ
        cand = max(groups.values(), key=lambda g: (len(g), -bbox_area(g), -g[0][0], -g[0][1]))
        if len(cand) < n * CORE_MIN_FRACTION:
            continue  # 本体を切り捨てすぎ。全盤に広がる詰碁を1子まで削る事故を防ぐ
        if fit_margin(sizes, komi, margin, *snapped_bbox(cand, sizes)) is not None:
            best = cand  # gap 昇順ループなので、最後に通ったものが「通る中で最大の gap」

    if best is None or len(best) == n:
        return all_bbox
    for _i, _j, h in best:
        h["tsumego_core"] = True
    return snapped_bbox(best, sizes)


def bbox_area(entries):
    i = [e[0] for e in entries]
    j = [e[1] for e in entries]
    return (max(i) - min(i) + 1) * (max(j) - min(j) + 1)


def pick_all(stones, key):
    return [[i, j, s.get("black")] for i, row in enumerate(stones) for j, s in enumerate(row) if s.get(key)]


def get_analysis_region(region_pos):
    if len(region_pos) == 0:
        return None
    ai, aj, dummy = tuple(zip(*region_pos))
    ri = (min(ai), max(ai))
    rj = (min(aj), max(aj))
    return ri[0] < ri[1] and rj[0] < rj[1] and (ri, rj)


def covers_board_p(region, sizes):
    (i0, i1), (j0, j1) = region
    isize, jsize = sizes
    # game.set_region_of_interest が None 正規化する条件と同じ（縦横とも盤以上）
    return i1 - i0 + 1 >= isize and j1 - j0 + 1 >= jsize


def fallback_region(core_bbox, sizes):
    """枠由来のリージョンが盤全体に退化したときの下限。コア bbox + pad を縮めながら試す。

    bbox は snap 済みなので、端に届く詰碁では全 pad が盤全体になり None を返す
    （端の手を候補から外すと正解手を落としかねないため、その場合は全盤解析に委ねる）。
    """
    isize, jsize = sizes
    imin, jmin, imax, jmax = core_bbox
    for pad in (2, 1, 0):
        i0, i1 = max(0, imin - pad), min(isize - 1, imax + pad)
        j0, j1 = max(0, jmin - pad), min(jsize - 1, jmax + pad)
        if i0 >= i1 or j0 >= j1:
            continue  # get_analysis_region と同じく1線に退化した範囲は使わない
        if not covers_board_p(((i0, i1), (j0, j1)), sizes):
            return ((i0, i1), (j0, j1))
    return None


def dense_core_bbox(bw_board):
    """枠なしモード用: 詰碁本体（密なクラスタ）の snap 済み bbox を返す。石が無ければ None。

    mark_core_stones は「枠が張れないときだけ絞る」判定なので、枠を張らない経路では
    基準として機能しない（実例: 全石 bbox のままだとリージョンが空き地まで広がり、
    空き地の手が正解手と競合して勝ってしまう）。ここでは枠の成否ではなく密度を基準にし、
    CORE_MIN_FRACTION 以上の石を保持できる最小の gap の最大クラスタを採る。
    石が2路飛びに並ぶ緩い形は gap=1 で分断されて割合を割るため gap が上がり1塊にまとまる。

    gap を段階的に広げながら union-find でクラスタを併合していく処理は mark_core_stones の
    ループとほぼ同形だが、採用条件・探索方向・石 dict へのマーク付けが異なるため意図的に
    分離している（枠なし経路は A/B 検証後に削除予定で、生き残った場合はこの重複の解消を検討する）。
    """
    sizes = ij_sizes(bw_board)
    entries = [(i, j, v) for i, row in enumerate(bw_board) for j, v in enumerate(row) if v in (BLACK, WHITE)]
    if not entries:
        return None
    n = len(entries)
    edges = [[] for _ in range(cluster_gap + 1)]
    for a in range(n):
        ia, ja, _ca = entries[a]
        for b in range(a + 1, n):
            d = max(abs(ia - entries[b][0]), abs(ja - entries[b][1]))
            if d <= cluster_gap:
                edges[d].append((a, b))
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for gap in range(1, cluster_gap + 1):
        for a, b in edges[gap]:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
        groups = {}
        for a in range(n):
            groups.setdefault(find(a), []).append(entries[a])
        # 同数クラスタのタイは bbox が小さい方 → 上 → 左 の順で決定的に選ぶ
        cand = max(groups.values(), key=lambda g: (len(g), -bbox_area(g), -g[0][0], -g[0][1]))
        # 詰碁は必ず「囲う側」と「攻められる側」の両色を含む。片色だけの密なクラスタを
        # 採用すると、閾値を満たしていても詰碁の対象そのもの（もう一方の色の群）が
        # リージョンから丸ごと落ちてしまう。両色を含まないクラスタは却下し、gapを
        # 上げて広い併合を試す（単色しかない盤は詰碁になり得ないので、最後まで両色の
        # クラスタが見つからなければ下の全石 bbox フォールバックに委ねる）
        bicolour = {colour for _i, _j, colour in cand} == {BLACK, WHITE}
        if len(cand) >= n * CORE_MIN_FRACTION and bicolour:
            return snapped_bbox(cand, sizes)
    return snapped_bbox(entries, sizes)


def frameless_region(bw_board, pad):
    """枠なしモードの解析リージョン ((imin, imax), (jmin, jmax)) を返す。盤全体になるなら None。

    盤面には一切触れない（枠なしモードの要はアプリと完全に同一の盤面を使うこと）。
    """
    core = dense_core_bbox(bw_board)
    if core is None:
        return None
    isize, jsize = ij_sizes(bw_board)
    imin, jmin, imax, jmax = core
    i0, i1 = max(0, imin - pad), min(isize - 1, imax + pad)
    j0, j1 = max(0, jmin - pad), min(jsize - 1, jmax + pad)
    if i0 >= i1 or j0 >= j1:
        return None  # 1線に退化した範囲は get_analysis_region と同じく使わない
    if covers_board_p(((i0, i1), (j0, j1)), (isize, jsize)):
        return None
    return ((i0, i1), (j0, j1))


def tsumego_frame_stones(stones, komi, black_to_play_p, ko_p, margin, drop_non_core=False, black_to_attack_p=None):
    sizes = ij_sizes(stones)
    isize, jsize = sizes
    all_ijs = [
        {"i": i, "j": j, "black": h.get("black"), "core": h.get("tsumego_core")}
        for i, row in enumerate(stones)
        for j, h in enumerate(row)
        if h.get("stone")
    ]

    if len(all_ijs) == 0:
        return []

    # コア石がマークされていればそれだけで範囲を取る。マークは石の dict に付いており
    # flip_stones は同じ dict を移すだけなので、転置・反転を越えて再帰の全段で保持される
    # （これが無いと絞り込みが1段目で失われ、枠が全石の bbox に戻って退化する）
    ijs = [z for z in all_ijs if z["core"]] or all_ijs

    def problem_range(zs):
        top = min_by(zs, "i", +1)
        left = min_by(zs, "j", +1)
        bottom = min_by(zs, "i", -1)
        right = min_by(zs, "j", -1)
        return (
            [top, bottom, left, right],
            snap0(top["i"]),
            snap0(left["j"]),
            snapS(bottom["i"], isize),
            snapS(right["j"], jsize),
        )

    # find range of problem
    extrema, imin, jmin, imax, jmax = problem_range(ijs)
    top, bottom, left, right = extrema
    # 攻め方判定はこの局面固有の性質であり、盤の向き（反転・転置）に依存してはならない。
    # しかし min_by は同座標のタイをこの時点のリスト順（＝現在の向きでの row-major 順）で
    # 崩すため、反転・転置後は同じ石でも extrema の代表点が変わり得て判定が反転しうる
    # （height2 自体は反転・転置不変だが、タイ崩れで extrema の中身が変わるため結果が変わる）。
    # そのためコア石マークと同じパターンで、再帰の最初の呼び出し（black_to_attack_p が
    # 未指定＝元の向き）でのみ一度だけ判定し、以降の反転・転置後の再帰にはその値を
    # そのまま持ち回す（recompute しない）
    if black_to_attack_p is None:
        black_to_attack_p = guess_black_to_attack([top, bottom, left, right], sizes)
    # 適応margin: bbox+margin で外側（守り側の代償地帯）が必要面積を下回る大型詰碁では、
    # 枠ゲームが一方的（±100点級）になり勝率が飽和し、死活より空き地・小さい得が優先される。
    # 外側が確保できるまで margin を縮める。どの margin でも確保できない盤（9路など）は
    # 従来値を維持する（縮めても焼け石に水で、既存挙動を変えないため）
    # drop_non_core=True の経路は非コア石を後で除去するので、壁が石を踏んでも穴が空かず不要
    occupied = None if drop_non_core else {(z["i"], z["j"]) for z in all_ijs if not z["core"]}
    margin = fit_margin(sizes, komi, margin, imin, jmin, imax, jmax, occupied=occupied) or margin
    # flip/rotate for standard position
    # don't mix flip and swap (FF = SS = identity, but SFSF != identity)
    flip_spec = (
        [False, False, True] if imin < jmin else [need_flip_p(imin, imax, isize), need_flip_p(jmin, jmax, jsize), False]
    )
    if True in flip_spec:
        flipped = flip_stones(stones, flip_spec)
        filled = tsumego_frame_stones(flipped, komi, black_to_play_p, ko_p, margin, drop_non_core, black_to_attack_p)
        return flip_stones(filled, flip_spec)
    # put outside stones
    i0 = imin - margin
    i1 = imax + margin
    j0 = jmin - margin
    j1 = jmax + margin
    frame_range = [i0, i1, j0, j1]
    if drop_non_core:
        drop_non_core_stones(stones, sizes, frame_range)
    put_border(stones, sizes, frame_range, black_to_attack_p)
    mark_region_corners(stones, sizes, frame_range)
    put_outside(stones, sizes, frame_range, black_to_attack_p, black_to_play_p, komi)
    put_ko_threat(stones, sizes, frame_range, black_to_attack_p, black_to_play_p, ko_p)
    return stones


# detect corner/edge/center problems
# (avoid putting border stones on the first lines)
def snap(k, to):
    return to if abs(k - to) <= near_to_edge else k


def snap0(k):
    return snap(k, 0)


def snapS(k, size):
    return snap(k, size - 1)


def min_by(ary, key, sign):
    by = [sign * z[key] for z in ary]
    return ary[by.index(min(by))]


def need_flip_p(kmin, kmax, size):
    return kmin < size - kmax - 1


def guess_black_to_attack(extrema, sizes):
    return sum([sign_of_color(z) * height2(z, sizes) for z in extrema]) > 0


def sign_of_color(z):
    return 1 if z["black"] else -1


def height2(z, sizes):
    isize, jsize = sizes
    return height(z["i"], isize) + height(z["j"], jsize)


def height(k, size):
    return size - abs(k - (size - 1) / 2)


######################################
# sub


def mark_region_corners(stones, sizes, frame_range):
    # 枠矩形+marginが盤外にはみ出すと put_stone が境界石ごとマークを捨て、マークが1線に退化して
    # get_analysis_region がリージョンなし（全盤解析）を返す。盤内クランプ済みの4隅を直接マークして
    # リージョン範囲を常に保存する（マークは石でない空セルにも付けられ、flip/転置にもそのまま乗る）
    isize, jsize = sizes
    i0, i1, j0, j1 = frame_range
    for i in (max(0, i0), min(isize - 1, i1)):
        for j in (max(0, j0), min(jsize - 1, j1)):
            stones[i][j]["tsumego_frame_region_mark"] = True


def put_border(stones, sizes, frame_range, is_black):
    i0, i1, j0, j1 = frame_range
    put_twin(stones, sizes, i0, i1, j0, j1, is_black, False)
    put_twin(stones, sizes, j0, j1, i0, i1, is_black, True)


def put_twin(stones, sizes, beg, end, at0, at1, is_black, reverse_p):
    for at in (at0, at1):
        for k in range(beg, end + 1):
            i, j = (at, k) if reverse_p else (k, at)
            put_stone(stones, sizes, i, j, is_black, False, True)


def put_outside(stones, sizes, frame_range, black_to_attack_p, black_to_play_p, komi):
    isize, jsize = sizes
    count = 0
    offense_komi = (+1 if black_to_attack_p else -1) * komi
    defense_area = (isize * jsize - offense_komi - offence_to_win) / 2
    for i in range(isize):
        for j in range(jsize):
            if inside_p(i, j, frame_range):
                continue
            if stones[i][j].get("stone") and not stones[i][j].get("tsumego_frame"):
                continue  # クラスタ外の既存石は残す（上書きするとAB/AWが既存石と衝突する）
            count += 1
            black_p = xor(black_to_attack_p, (count <= defense_area))
            empty_p = (i + j) % 2 == 0 and abs(count - defense_area) > isize
            put_stone(stones, sizes, i, j, black_p, empty_p)


# standard position:
# ? = problem, X = offense, O = defense
# OOOOOOOOOOOOO
# OOOOOOOOOOOOO
# OOOOOOOOOOOOO
# XXXXXXXXXXXXX
# XXXXXXXXXXXXX
# XXXX.........
# XXXX.XXXXXXXX
# XXXX.X???????
# XXXX.X???????

# (pattern, top_p, left_p)
offense_ko_threat = (
    """
....OOOX.
.....XXXX
""",
    True,
    False,
)

defense_ko_threat = (
    """
..
..
X.
XO
OO
.O
""",
    False,
    True,
)


def put_ko_threat(stones, sizes, frame_range, black_to_attack_p, black_to_play_p, ko_p):
    isize, jsize = sizes
    for_offense_p = xor(ko_p, xor(black_to_attack_p, black_to_play_p))
    pattern, top_p, left_p = offense_ko_threat if for_offense_p else defense_ko_threat
    aa = [list(line) for line in pattern.splitlines() if len(line) > 0]
    height, width = ij_sizes(aa)
    for i, row in enumerate(aa):
        for j, ch in enumerate(row):
            ai = i + (0 if top_p else isize - height)
            aj = j + (0 if left_p else jsize - width)
            if inside_p(ai, aj, frame_range):
                return
            if stones[ai][aj].get("stone") and not stones[ai][aj].get("tsumego_frame"):
                return  # クラスタ外の既存石と重なる場合はコウダテ形を置かない
            black = xor(black_to_attack_p, ch == "O")
            empty = ch == "."
            put_stone(stones, sizes, ai, aj, black, empty)


def xor(a, b):
    return bool(a) != bool(b)


######################################
# util


def flip_stones(stones, flip_spec):
    swap_p = flip_spec[2]
    sizes = ij_sizes(stones)
    isize, jsize = sizes
    new_isize, new_jsize = [jsize, isize] if swap_p else [isize, jsize]
    new_stones = [[None for z in range(new_jsize)] for row in range(new_isize)]
    for i, row in enumerate(stones):
        for j, z in enumerate(row):
            new_i, new_j = flip_ij((i, j), sizes, flip_spec)
            new_stones[new_i][new_j] = z
    return new_stones


def put_stone(stones, sizes, i, j, black, empty, tsumego_frame_region_mark=False):
    isize, jsize = sizes
    if i < 0 or isize <= i or j < 0 or jsize <= j:
        return
    stones[i][j] = (
        {}
        if empty
        else {
            "stone": True,
            "tsumego_frame": True,
            "black": black,
            "tsumego_frame_region_mark": tsumego_frame_region_mark,
        }
    )


def inside_p(i, j, region):
    i0, i1, j0, j1 = region
    return i0 <= i and i <= i1 and j0 <= j and j <= j1


def strictly_inside_p(i, j, region):
    i0, i1, j0, j1 = region
    return i0 < i and i < i1 and j0 < j and j < j1


def drop_non_core_stones(stones, sizes, frame_range):
    """枠矩形の境界線上および外側にある非コア石を盤から除く。

    put_border より先に呼ぶことで、put_outside の「既存石を残す」ガードに引っかからなくなり
    充填が穴なしになる（呼ばないと非コア石があった位置だけ埋まらず穴が残る）。
    壁はコア bbox から margin>=1 離れているので、コア石が消えることはない。
    """
    isize, jsize = sizes
    for i in range(isize):
        for j in range(jsize):
            h = stones[i][j]
            if h.get("stone") and not h.get("tsumego_core") and not strictly_inside_p(i, j, frame_range):
                stones[i][j] = {}


def stones_from_bw_board(bw_board):
    return [[stone_from_str(s) for s in row] for row in bw_board]


def stone_from_str(s):
    black = s == BLACK
    white = s == WHITE
    return {"stone": True, "black": black} if (black or white) else {}


def ij_sizes(stones):
    return (len(stones), len(stones[0]))


def flip_ij(ij, sizes, flip_spec):
    i, j = ij
    isize, jsize = sizes
    flip_i, flip_j, swap_ij = flip_spec
    fi = flip1(i, isize, flip_i)
    fj = flip1(j, jsize, flip_j)
    return (fj, fi) if swap_ij else (fi, fj)


def flip1(k, size, flag):
    return size - 1 - k if flag else k
