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
