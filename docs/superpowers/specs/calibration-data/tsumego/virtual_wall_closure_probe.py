"""仮想境界壁による閉包の実測プローブ（KataGo 不要・CPU のみ・本番コード無変更）。

抽出器拡張プロジェクト（`2026-08-15-tsumego-extraction-expansion-handoff.md` §3 本命案）の設計材料。
回答帳の全 entry のうち、現行 `_Extractor` が「領域が閉じていない」で失敗する盤（398問）を対象に、
認識石の外接矩形の外側に**攻め方の色の仮想壁（1列）**を置いて閉包を試みる。

変種:
  A(k)  全認識石の外接矩形を k 路（1,2,3）外へ広げた矩形の周囲1列。盤外にはみ出す辺は置かない
        （盤端が壁）。既存の石がある点は上書きしない。
  F     本番の枠幾何（tsumego_frame.tsumego_frame_stones の frame_range: コア絞り込み mark_core_stones
        → 端スナップ済み bbox → fit_margin → put_border 相当）を CPU で再現した壁だけ
        （代償地帯 put_outside・コウダテ put_ko_threat は置かない）。本番と同じく非コア石で
        frame_range の内側に無いものは落とす（drop_non_core_stones 相当）。
  攻め方色: guess = tsumego_frame.guess_black_to_attack_for_board（本番の役割推定・極値票）／inverse = その逆。

注入方法（本番コードは変更しない）: `_Extractor` のサブクラス VirtualWallExtractor で
  - 壁石を含む連を `pass_alive` に足す（候補・at_risk から外れる）
  - `_chain_in_hint` を壁連で False にする（`_closure` が hint 外連を「無条件に壁」とする既存経路を借りる。
    壁の外側呼吸点数に依らず壁になる＝盤端沿いの短い壁片も壁）
  - `_reaches_safety` を壁連で True にする（壁は「不可侵・生存」の仮定そのもの）
さらに hole_fix=True の行は HoleFixExtractor（上の注入 + `_near_empties` で「石に接しない空点成分＝穴」を
region に足す）で測る。本番 `_closure` は穴（colors が空）を failed 扱いにして閉包を None にするため、
仮想壁で内側に空間ができた盤ではこれが閉包失敗の主因になる（実測は summary の dominant failure reason）。

各 (entry × 変種 × 色 × hole_fix) を JSONL に1行ずつ書く（399 盤 × 4 変種 × 2 色 × 2 = 6384 行）。
主なフィールド: key(先頭10字) size variant k attacker_choice(guess/inverse) attacker attacker_guess attacker_used
  hole_fix closed error error_code wall_size ring_size n_dropped bbox rect n_lines ms
  閉じた行: type target_color target_size own_target_size region_size region_empties region_stones fill_size gates_ok
           line_inside(全 line の bool) line_hits_wall first_move_inside wall_adjacent_to_region
  閉じない行: seed_reasons(候補連ごとの単独閉包の理由 Counter) union_reason n_candidates
           closed_nocap / error_nocap / region_size_nocap …（region 上限 72 を外した再試行）
  F のみ: frame_range frame_black_to_attack n_core n_all（k は本番の適応 margin）
stdout は ASCII のみ。

usage:
  PYTHONIOENCODING=utf-8 python virtual_wall_closure_probe.py [--book PATH] [--out PATH] [--limit N]
"""
import argparse
import collections
import json
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"  # tsumego_frame → game_node が Kivy を import し argparse を横取りする

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", ".."))

from katrain.core import tsumego_frame as tf  # noqa: E402
from katrain.core.tsumego_answer_book import gtp_to_point  # noqa: E402
from katrain.core.tsumego_problem import (  # noqa: E402
    DEFAULT_MAX_REGION_POINTS,
    FRONTIER_LIBERTIES,
    ProblemError,
    _Extractor,
)
from katrain.core.tsumego_solver.board import board_from_stones  # noqa: E402
from katrain.core.tsumego_solver.model import BLACK, EMPTY, WHITE  # noqa: E402

# 本番のキャプチャ設定（ユーザーローカル config 2026-08-15: game/komi=7.0, tsumego_capture/frame_margin=4）
KOMI = 7.0
FRAME_MARGIN = 4
NOCAP_REGION_POINTS = 10_000  # 「region 上限が原因で閉じないのか」を分けるための再試行用

DEFAULT_BOOK = os.path.expanduser("~/.katrain/tsumego_answers.json")
DEFAULT_OUT = os.path.join(HERE, "virtual-wall-closure-probe.jsonl")


# ---------------------------------------------------------------- 注入
class VirtualWallExtractor(_Extractor):
    """仮想壁の点を「pass-alive な壁」として扱う _Extractor（本番クラスは無変更）。"""

    def __init__(self, board, to_play, region_hint, max_region_points, wall_points):
        super().__init__(board, to_play, region_hint, max_region_points)
        self.wall_points = set(wall_points)
        # 壁石と物理的に連結した同色の実石も同じ連＝壁の一部（枠経路の put_border と同じ扱い）
        self.wall_chains = {self.chain_of[p] for p in self.wall_points if p in self.chain_of}
        for ci in self.wall_chains:
            self.pass_alive.update(self.chains[ci][0])

    def _chain_in_hint(self, ci):
        if ci in self.wall_chains:
            return False  # hint 外の連と同じ経路で「無条件に壁」
        return super()._chain_in_hint(ci)

    def _reaches_safety(self, ci, walls, fill):
        if ci in self.wall_chains:
            return True  # 壁は生存の仮定そのもの
        return super()._reaches_safety(ci, walls, fill)


class HoleFixExtractor(VirtualWallExtractor):
    """`_closure` の遠地帯処理は「石に一切接しない空点成分」（＝region の空点だけに囲われた穴。
    colors が空集合）を `len(colors)==1` でも `inner` でもないので **failed（混色扱い）** にして
    閉包を None にする。閉じた詰碁盤では近傍空点が小成分ごと吸収されて穴が出ないが、
    仮想壁で内側に広い空間ができると depth-2 の近傍球の凹みに穴が生まれ、これが閉包失敗の
    主因になる（実測は本プローブ）。この変種は `_near_empties` の後段で「石に接しない空点成分」を
    region の空点に足して穴を消す（本番 `_closure` を書き換えずに同じ効果を得る注入。
    設計としては `_closure` 側で colors==set() を region に吸収するのが本筋）。"""

    def _near_empties(self, absorbed):
        result = super()._near_empties(absorbed)
        b = self.board
        seen = set(result)
        for start in list(result):
            for n in b.neighbors[start]:
                if b.stones[n] != EMPTY or n in seen:
                    continue
                comp = [n]
                seen.add(n)
                stack = [n]
                touches_stone = False
                while stack:
                    p = stack.pop()
                    for q in b.neighbors[p]:
                        if b.stones[q] != EMPTY:
                            touches_stone = True
                        elif q not in seen:
                            seen.add(q)
                            comp.append(q)
                            stack.append(q)
                if not touches_stone:
                    result.update(comp)
        return result


# ---------------------------------------------------------------- 盤の組み立て
def entry_stones(entry):
    black = {gtp_to_point(s) for s in entry["canonical_black"]}
    white = {gtp_to_point(s) for s in entry["canonical_white"]}
    return black, white


def stones_to_grid(black, white, size):
    """(x, 下origin y) → 認識グリッド grid[i][j]（i は上からの行）。tsumego_frame の bw_board 形式。"""
    grid = [["." for _ in range(size)] for _ in range(size)]
    for x, y in black:
        grid[size - 1 - y][x] = "B"
    for x, y in white:
        grid[size - 1 - y][x] = "W"
    return grid


def baseline_failure(black, white, size, cap=DEFAULT_MAX_REGION_POINTS):
    """現行 _Extractor の結果。('ok', problem) / ('closure', err) / ('other', err)。"""
    board = board_from_stones((size, size), black, white)
    try:
        problem = _Extractor(board, "B", None, cap).extract()
        return "ok", problem
    except ProblemError as err:
        return ("closure" if "閉じ" in str(err) else "other"), str(err)


def stones_bbox(black, white):
    pts = black | white
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))  # (xmin, ymin, xmax, ymax)


def rect_ring(x0, y0, x1, y1, size):
    """矩形 [x0..x1]×[y0..y1] の周囲1列のうち盤内の点。盤外にはみ出す辺は置かない（put_border 相当）。"""
    ring = set()
    for x in range(max(0, x0), min(size - 1, x1) + 1):
        if 0 <= y0 < size:
            ring.add((x, y0))
        if 0 <= y1 < size:
            ring.add((x, y1))
    for y in range(max(0, y0), min(size - 1, y1) + 1):
        if 0 <= x0 < size:
            ring.add((x0, y))
        if 0 <= x1 < size:
            ring.add((x1, y))
    return ring


def variant_a_walls(black, white, size, k):
    xmin, ymin, xmax, ymax = stones_bbox(black, white)
    ring = rect_ring(xmin - k, ymin - k, xmax + k, ymax + k, size)
    return ring, dict(bbox=[xmin, ymin, xmax, ymax], rect=[xmin - k, ymin - k, xmax + k, ymax + k])


def frame_geometry(grid, komi=KOMI, margin=FRAME_MARGIN):
    """本番 tsumego_frame_stones の frame_range 決定を（flip 無しで）再現する。

    返り値: dict(frame_range=[i0,i1,j0,j1], margin, black_to_attack, core_bbox, dropped=[(i,j)], n_core, n_all)
    flip/転置は put_outside/put_ko_threat の標準位置化のためで frame_range 自体は向きに不変（fit_margin は
    面積条件、snap は両端対称）なので元の向きで直接計算してよい。
    """
    sizes = tf.ij_sizes(grid)
    isize, jsize = sizes
    if min(sizes) <= 9:
        margin = min(margin, 2)  # build_frame のクランプ
    stones = tf.stones_from_bw_board(grid)
    tf.mark_core_stones(stones, komi, margin)  # 全石 bbox で枠が張れれば無マーク（=全石がコア扱い）
    all_ijs = [
        {"i": i, "j": j, "black": h.get("black"), "core": h.get("tsumego_core")}
        for i, row in enumerate(stones)
        for j, h in enumerate(row)
        if h.get("stone")
    ]
    ijs = [z for z in all_ijs if z["core"]] or all_ijs
    imin = tf.snap0(min(z["i"] for z in ijs))
    jmin = tf.snap0(min(z["j"] for z in ijs))
    imax = tf.snapS(max(z["i"] for z in ijs), isize)
    jmax = tf.snapS(max(z["j"] for z in ijs), jsize)
    black_to_attack = tf.guess_black_to_attack(tf.extremum_stones(ijs), sizes)
    # キャプチャ経路は drop_non_core=True → occupied=None
    m = tf.fit_margin(sizes, komi, margin, imin, jmin, imax, jmax, occupied=None) or margin
    frame_range = [imin - m, imax + m, jmin - m, jmax + m]
    marked = any(z["core"] for z in all_ijs)
    dropped = []
    if marked:
        dropped = [(z["i"], z["j"]) for z in all_ijs if not z["core"] and not tf.strictly_inside_p(z["i"], z["j"], frame_range)]
    else:
        # 無マーク時は drop_non_core_stones が「全石を非コア」と見る。全石 bbox は frame_range の
        # 内側なので通常は落ちないが、念のため同じ規則で数える
        dropped = [(z["i"], z["j"]) for z in all_ijs if not tf.strictly_inside_p(z["i"], z["j"], frame_range)]
    return dict(
        frame_range=frame_range,
        margin=m,
        black_to_attack=bool(black_to_attack),
        core_bbox=[imin, jmin, imax, jmax],
        dropped=dropped,
        n_core=len(ijs),
        n_all=len(all_ijs),
    )


def variant_f_walls(black, white, size):
    grid = stones_to_grid(black, white, size)
    geo = frame_geometry(grid)
    i0, i1, j0, j1 = geo["frame_range"]
    # put_border: (i0,j),(i1,j) for j in j0..j1 / (i,j0),(i,j1) for i in i0..i1、盤外は skip
    ring_ij = set()
    for j in range(j0, j1 + 1):
        for i in (i0, i1):
            if 0 <= i < size and 0 <= j < size:
                ring_ij.add((i, j))
    for i in range(i0, i1 + 1):
        for j in (j0, j1):
            if 0 <= i < size and 0 <= j < size:
                ring_ij.add((i, j))
    ring = {(j, size - 1 - i) for i, j in ring_ij}
    dropped = {(j, size - 1 - i) for i, j in geo["dropped"]}
    xmin, ymin, xmax, ymax = stones_bbox(black, white)
    # frame_range を (x, y) 矩形に直す（y は下origin なので i が反転）
    rect_xy = [j0, size - 1 - i1, j1, size - 1 - i0]
    return ring, dropped, dict(
        bbox=[xmin, ymin, xmax, ymax],
        rect=rect_xy,
        frame_range=geo["frame_range"],
        margin=geo["margin"],
        frame_black_to_attack=geo["black_to_attack"],
        n_core=geo["n_core"],
        n_all=geo["n_all"],
    )


def make_extractor(black, white, size, ring, attacker, dropped=frozenset(), cap=DEFAULT_MAX_REGION_POINTS, hole_fix=False):
    """壁を置いた盤と、それに対する（仮想壁）Extractor を作る。(extractor, wall_pts, board)。"""
    b = set(black) - set(dropped)
    w = set(white) - set(dropped)
    occupied = b | w
    wall_pts = {p for p in ring if p not in occupied}
    if attacker == BLACK:
        b |= wall_pts
    else:
        w |= wall_pts
    board = board_from_stones((size, size), b, w)
    wall_idx = {board.index(p) for p in wall_pts}
    cls = HoleFixExtractor if hole_fix else VirtualWallExtractor
    return cls(board, "B", None, cap, wall_idx), wall_pts, board


def build_problem(black, white, size, ring, attacker, dropped=frozenset(), cap=DEFAULT_MAX_REGION_POINTS, hole_fix=False):
    """壁を置いた盤で仮想壁 Extractor を走らせる。(problem|None, error|None, wall_pts, board) を返す。"""
    ex, wall_pts, board = make_extractor(black, white, size, ring, attacker, dropped, cap, hole_fix)
    try:
        return ex.extract(), None, wall_pts, board
    except ProblemError as err:
        return None, str(err), wall_pts, board


# ---------------------------------------------------------------- 失敗理由の診断（_closure の診断用コピー）
def _closure_reason(ex, seed_ids, frontier):
    """`_Extractor._closure`（コミット 79e53c6 時点）と同じ手順を辿り、None を返す箇所の理由コードを返す。

    判定は本番の `_closure` が出す（この関数の結果は診断ラベルにしか使わない）。理由コード:
      overflow      … 遠地帯が FILL_CAP を超え、取り込める内側連も無い（盤の広域へ抜ける）
      hole          … 石に一切接しない空点成分（colors=空）が failed 扱いになった
      mixed         … 壁の色が混在する遠地帯（内側連なし）
      wall_unsafe   … 壁が自色の壁/地に到達できない（case AA ガード）
      cap           … region が max_region_points を超えた
      closed        … 閉じた
    """
    b = ex.board
    absorbed = set()
    walls = set()
    r_empty = set()
    pending = list(seed_ids)
    fill = {}
    while True:
        while pending:
            while pending:
                ci = pending.pop()
                if ci in absorbed:
                    continue
                absorbed.add(ci)
                walls.discard(ci)
            r_empty = ex._near_empties(absorbed)
            for p in list(r_empty):
                for n in b.neighbors[p]:
                    if b.stones[n] == EMPTY:
                        continue
                    ci = ex.chain_of[n]
                    if ci in absorbed:
                        continue
                    if not ex._chain_in_hint(ci):
                        walls.add(ci)
                        continue
                    outside = {q for q in ex.chains[ci][1] if q not in r_empty}
                    if len(outside) >= frontier:
                        walls.add(ci)
                    elif ci not in pending:
                        pending.append(ci)
        fill = {}
        discovered = set()
        seen = set(r_empty)
        failed = None
        for start in list(r_empty):
            for n in b.neighbors[start]:
                if b.stones[n] != EMPTY or n in seen:
                    continue
                comp = [n]
                seen.add(n)
                stack = [n]
                colors = set()
                boundary = set()
                overflow = False
                while stack:
                    p = stack.pop()
                    for q in b.neighbors[p]:
                        v = b.stones[q]
                        if v == EMPTY:
                            if q not in seen and q not in r_empty:
                                seen.add(q)
                                comp.append(q)
                                stack.append(q)
                        else:
                            colors.add(v)
                            boundary.add(ex.chain_of[q])
                    if len(comp) > ex.FILL_CAP:
                        overflow = True
                        break
                inner = {ci for ci in boundary if ci not in absorbed and ci not in walls and ex._chain_in_hint(ci)}
                if overflow:
                    if inner:
                        discovered |= inner
                    else:
                        return "overflow"
                elif len(colors) == 1:
                    owner = next(iter(colors))
                    for p in comp:
                        fill[p] = owner
                elif inner:
                    discovered |= inner
                else:
                    failed = "hole" if not colors else "mixed"
        if discovered:
            pending.extend(discovered)
            continue
        if failed:
            return failed
        break
    for ci in walls:
        if not ex._reaches_safety(ci, walls, fill):
            return "wall_unsafe"
    r_stones = set()
    for ci in absorbed:
        r_stones.update(ex.chains[ci][0])
    if len(r_stones) + len(r_empty) > ex.max_region_points:
        return "cap"
    return "closed"


def diagnose(ex):
    """extract() が失敗した Extractor について、候補連ごとの単独閉包の理由と anchors 合併閉包の理由を返す。"""
    candidates = [
        ci
        for ci in range(len(ex.chains))
        if ex._chain_in_hint(ci) and ex.chains[ci][0][0] not in ex.pass_alive
    ]
    candidates = [ci for ci in candidates if not all(p in ex.pass_alive for p in ex.chains[ci][0])]
    seed_reasons = collections.Counter()
    anchors = set()
    for ci in candidates:
        reason = _closure_reason(ex, {ci}, FRONTIER_LIBERTIES)
        if reason == "closed":
            single = ex._closure({ci}, FRONTIER_LIBERTIES)
            if single is not None and ex._reaches_safety(ci, single[3], single[4]):
                reason = "closed_safe"
            else:
                reason = "closed_anchor"
                anchors.add(ci)
        seed_reasons[reason] += 1
    union_reason = _closure_reason(ex, anchors, FRONTIER_LIBERTIES) if anchors else None
    return dict(seed_reasons), union_reason, len(candidates)


def error_code(err):
    """日本語の ProblemError を ASCII の短い分類コードにする（stdout 用。JSONL には生文字列も残す）。"""
    if err is None:
        return None
    if "どの連からも閉じた領域が作れない" in err:
        return "no_anchor_closes"
    if "領域が閉じない/大きすぎる" in err:
        return "anchor_closure_none_or_cap"
    if "target が region 外へ連絡できる" in err:
        return "target_connects_outside"
    if "空点が盤の広域へ抜ける" in err:
        return "closure_overflow"
    if "危険な石が見つからない" in err:
        return "no_candidates"
    if "at_risk が空" in err:
        return "at_risk_empty"
    if "target が使える空間" in err:
        return "predetermined_space"
    if "丸ごとアタリ" in err:
        return "predetermined_atari"
    if "対象群が無い" in err:
        return "no_target_other"
    if "詰碁として成立していない" in err:
        return "predetermined_other"
    return "other:" + "".join(ch if ord(ch) < 128 else "?" for ch in err)[:40]


def problem_metrics(problem, entry, wall_pts):
    region = set(problem.region)
    stones = set(problem.black) | set(problem.white)
    empties = [p for p in region if p not in stones]
    lines = entry["lines"]
    line_inside = []
    line_hits_wall = []
    for line in lines:
        pts = [gtp_to_point(m) for m in line if m != "pass"]
        line_inside.append(all(p in region for p in pts))
        line_hits_wall.append(any(p in wall_pts for p in pts))
    firsts = [gtp_to_point(line[0]) for line in lines if line and line[0] != "pass"]
    first_move_inside = bool(firsts) and all(p in region for p in firsts)
    n_stones_region = len(region) - len(empties)
    return dict(
        type=problem.problem_type.value,
        target_color=problem.target_color,
        target_size=len(problem.target),
        own_target_size=len(problem.own_target),
        region_size=len(region),
        region_empties=len(empties),
        region_stones=n_stones_region,
        fill_size=len(problem.fill_black) + len(problem.fill_white),
        gates_ok=bool(len(region) <= 23 and len(empties) <= 12),
        line_inside=line_inside,
        line_hits_wall=line_hits_wall,
        first_move_inside=first_move_inside,
        wall_adjacent_to_region=sum(1 for p in wall_pts if any(
            (p[0] + dx, p[1] + dy) in region for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )),
    )


VARIANTS = [("A", 1), ("A", 2), ("A", 3), ("F", None)]


def probe_entry(key, entry):
    """1 entry の全変種×両色を試して行のリストを返す。"""
    size = entry["size"]
    black, white = entry_stones(entry)
    grid = stones_to_grid(black, white, size)
    guess_black_attacks = tf.guess_black_to_attack_for_board(grid, KOMI, FRAME_MARGIN)
    guess_color = BLACK if guess_black_attacks else WHITE
    rows = []
    for variant, k in VARIANTS:
        if variant == "A":
            ring, geo = variant_a_walls(black, white, size, k)
            dropped = frozenset()
        else:
            ring, dropped, geo = variant_f_walls(black, white, size)
            k = geo["margin"]
        for choice in ("guess", "inverse"):
            attacker = guess_color if choice == "guess" else (WHITE if guess_color == BLACK else BLACK)
            for hole_fix in (False, True):
                t0 = time.perf_counter()
                problem, err, wall_pts, _board = build_problem(
                    black, white, size, ring, attacker, dropped, hole_fix=hole_fix
                )
                ms = (time.perf_counter() - t0) * 1000.0
                row = dict(
                    key=key[:10],
                    size=size,
                    variant=variant,
                    k=k,
                    attacker_choice=choice,
                    attacker=attacker,
                    attacker_guess=guess_color,
                    attacker_used=attacker,
                    hole_fix=hole_fix,
                    closed=problem is not None,
                    error=err,
                    error_code=error_code(err),
                    wall_size=len(wall_pts),
                    ring_size=len(ring),
                    n_dropped=len(dropped),
                    bbox=geo["bbox"],
                    rect=geo["rect"],
                    n_lines=len(entry["lines"]),
                    ms=round(ms, 2),
                )
                if variant == "F":
                    row["frame_range"] = geo["frame_range"]
                    row["frame_black_to_attack"] = geo["frame_black_to_attack"]
                    row["n_core"] = geo["n_core"]
                    row["n_all"] = geo["n_all"]
                if problem is not None:
                    row.update(problem_metrics(problem, entry, wall_pts))
                else:
                    # 失敗理由の診断（候補連ごとの単独閉包 / anchors 合併閉包）
                    ex, _w, _b = make_extractor(black, white, size, ring, attacker, dropped, hole_fix=hole_fix)
                    seed_reasons, union_reason, n_cand = diagnose(ex)
                    row["seed_reasons"] = seed_reasons
                    row["union_reason"] = union_reason
                    row["n_candidates"] = n_cand
                    # region 上限（72）が原因かを分ける: 上限を外して再試行
                    p2, err2, _w2, _b2 = build_problem(
                        black, white, size, ring, attacker, dropped, cap=NOCAP_REGION_POINTS, hole_fix=hole_fix
                    )
                    row["closed_nocap"] = p2 is not None
                    row["error_nocap"] = err2
                    row["error_code_nocap"] = error_code(err2)
                    if p2 is not None:
                        m2 = problem_metrics(p2, entry, wall_pts)
                        row["region_size_nocap"] = m2["region_size"]
                        row["region_empties_nocap"] = m2["region_empties"]
                        row["type_nocap"] = m2["type"]
                        row["line_inside_nocap"] = m2["line_inside"]
                rows.append(row)
    return rows


def dominant_reason(row):
    """失敗行の主因を1語にする（seed_reasons の多数決。閉じた種があるのに anchors 合併で落ちたら union_*）。"""
    if row["closed"]:
        return "closed"
    sr = row.get("seed_reasons") or {}
    if row.get("union_reason") and row["union_reason"] != "closed":
        return "union_" + row["union_reason"]
    if not sr:
        return row.get("error_code") or "unknown"
    non_closed = {k: v for k, v in sr.items() if not k.startswith("closed")}
    if not non_closed:
        return "all_seeds_safe" if sr.get("closed_safe") else (row.get("error_code") or "unknown")
    return max(non_closed.items(), key=lambda kv: kv[1])[0]


def bucket_empties(n):
    if n <= 9:
        return "<=9"
    if n <= 12:
        return "10-12"
    return ">12"


def group_key(r):
    return (r["variant"], r["k"] if r["variant"] == "A" else "prod", r["attacker_choice"], r["hole_fix"])


def summarize(rows):
    groups = collections.OrderedDict()
    for r in rows:
        groups.setdefault(group_key(r), []).append(r)
    print("")
    print("=== virtual wall closure probe summary ===")
    print("group = (variant, k, attacker, hole_fix) ; n = boards tried ; F k = production adaptive margin (varies)")
    hdr = (
        f"{'var':>3} {'k':>4} {'attacker':>8} {'hole':>5} {'n':>4} {'closed':>6} {'cl%':>5} "
        f"{'e<=9':>4} {'e10-12':>6} {'e>12':>4} {'reg<=23':>7} {'gates':>5} "
        f"{'line_in':>7} {'first_in':>8} {'nocap+':>6} {'attack':>6} {'defend':>6} {'semeai':>6}"
    )
    print(hdr)
    for (variant, k, choice, hole), rs in groups.items():
        closed = [r for r in rs if r["closed"]]
        emp = collections.Counter(bucket_empties(r["region_empties"]) for r in closed)
        reg23 = sum(1 for r in closed if r["region_size"] <= 23)
        gates = sum(1 for r in closed if r["gates_ok"])
        line_in = sum(1 for r in closed if r["line_inside"] and all(r["line_inside"]))
        first_in = sum(1 for r in closed if r["first_move_inside"])
        nocap = sum(1 for r in rs if not r["closed"] and r.get("closed_nocap"))
        types = collections.Counter(r["type"] for r in closed)
        print(
            f"{variant:>3} {str(k):>4} {choice:>8} {str(hole)[0]:>5} {len(rs):>4} {len(closed):>6} "
            f"{100.0 * len(closed) / max(1, len(rs)):>5.1f} "
            f"{emp['<=9']:>4} {emp['10-12']:>6} {emp['>12']:>4} {reg23:>7} {gates:>5} "
            f"{line_in:>7} {first_in:>8} {nocap:>6} {types['attack']:>6} {types['defend']:>6} {types['semeai']:>6}"
        )
    print("")
    print("(nocap+ = not closed at cap 72 but closes with the region cap removed;"
          " gates = region<=23 & empties<=12; line_in = every recorded line entirely inside region)")
    print("")
    print("=== dominant failure reason per group (from the diagnostic closure copy) ===")
    for (variant, k, choice, hole), rs in groups.items():
        reasons = collections.Counter(dominant_reason(r) for r in rs if not r["closed"])
        top = ", ".join(f"{code}={n}" for code, n in reasons.most_common(6))
        print(f"  {variant} k={k} {choice} hole={hole}: {top}")
    print("")
    print("=== solver-envelope candidates: closed AND gates_ok AND all lines inside ===")
    for (variant, k, choice, hole), rs in groups.items():
        both = sum(1 for r in rs if r["closed"] and r["gates_ok"] and r["line_inside"] and all(r["line_inside"]))
        wall_hit = sum(1 for r in rs if r["closed"] and any(r["line_hits_wall"]))
        e12 = sum(1 for r in rs if r["closed"] and r["region_empties"] <= 12 and r["line_inside"] and all(r["line_inside"]))
        print(f"  {variant} k={k} {choice} hole={hole}: gates_ok&line_inside={both}  empties<=12&line_inside={e12}  line_hits_wall={wall_hit}")
    print("")
    print("=== region_empties distribution among closed (per group, 5-point bins) ===")
    for (variant, k, choice, hole), rs in groups.items():
        closed = [r for r in rs if r["closed"]]
        hist = collections.Counter(min(r["region_empties"] // 5 * 5, 40) for r in closed)
        line = " ".join(f"{b}-{b + 4}:{hist[b]}" if b < 40 else f"40+:{hist[b]}" for b in sorted(hist))
        print(f"  {variant} k={k} {choice} hole={hole}: {line}")
    # 盤単位: どれかの変種で閉じた盤の数（guess 色のみ）
    by_key = collections.defaultdict(list)
    for r in rows:
        by_key[r["key"]].append(r)
    for hole in (False, True):
        any_closed = sum(
            1
            for rs in by_key.values()
            if any(r["closed"] for r in rs if r["attacker_choice"] == "guess" and r["hole_fix"] == hole)
        )
        any_env = sum(
            1
            for rs in by_key.values()
            if any(
                r["closed"] and r["gates_ok"] and r["line_inside"] and all(r["line_inside"])
                for r in rs
                if r["attacker_choice"] == "guess" and r["hole_fix"] == hole
            )
        )
        any_e12 = sum(
            1
            for rs in by_key.values()
            if any(
                r["closed"] and r["region_empties"] <= 12 and r["line_inside"] and all(r["line_inside"])
                for r in rs
                if r["attacker_choice"] == "guess" and r["hole_fix"] == hole
            )
        )
        print("")
        print(f"boards: {len(by_key)} ; hole_fix={hole}: closed by any variant (guess color): {any_closed} ; "
              f"gates_ok&line_inside by any variant: {any_env} ; empties<=12&line_inside by any variant: {any_e12}")
    # 役割推定の内訳と F の margin 分布
    guess = collections.Counter(rs[0]["attacker_guess"] for rs in by_key.values())
    print(f"attacker guess (extremum vote): {dict(guess)}")
    print("role consistency among closed (attacker=B -> attack / attacker=W -> defend expected):")
    for (variant, k, choice, hole), rs in groups.items():
        closed = [r for r in rs if r["closed"]]
        ok = sum(
            1
            for r in closed
            if (r["attacker_used"] == BLACK and r["type"] == "attack")
            or (r["attacker_used"] == WHITE and r["type"] == "defend")
        )
        print(f"  {variant} k={k} {choice} hole={hole}: consistent {ok}/{len(closed)}")
    fm = collections.Counter(r["k"] for r in rows if r["variant"] == "F" and r["attacker_choice"] == "guess" and not r["hole_fix"])
    print(f"F production margin distribution: {dict(sorted(fm.items()))}")
    ms = [r["ms"] for r in rows]
    print(f"extract time ms: mean {sum(ms) / max(1, len(ms)):.1f} max {max(ms) if ms else 0:.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=DEFAULT_BOOK)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0, help="target boards to process (0 = all)")
    args = ap.parse_args()
    book = json.load(open(args.book, encoding="utf-8"))["entries"]
    baseline = collections.Counter()
    targets = []
    for key, e in book.items():
        black, white = entry_stones(e)
        kind, _ = baseline_failure(black, white, e["size"])
        baseline[kind] += 1
        if kind == "closure":
            targets.append((key, e))
    print(f"answer book entries: {len(book)} ; baseline: {dict(baseline)}")
    if args.limit:
        targets = targets[: args.limit]
    print(f"target boards (baseline closure failure): {len(targets)}")
    t0 = time.perf_counter()
    rows = []
    with open(args.out, "w", encoding="utf-8") as f:
        for n, (key, e) in enumerate(targets, 1):
            for row in probe_entry(key, e):
                rows.append(row)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n % 50 == 0:
                print(f"  ... {n}/{len(targets)} boards ({time.perf_counter() - t0:.1f}s)", flush=True)
    print(f"done in {time.perf_counter() - t0:.1f}s ; rows: {len(rows)} ; wrote {args.out}")
    summarize(rows)


if __name__ == "__main__":
    main()
