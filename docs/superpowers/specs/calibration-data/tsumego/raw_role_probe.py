"""生盤（枠を張る前の認識盤そのもの）の KataGo ownership で攻め方を導出できるかの横断検証。

各ケースの保存 SGF から枠を剥がしてコアを復元（枠なし保存はそのまま）し、生盤を
黒番・full board・wideRootNoise=0・1800visits で解析。色別に石の1子平均 aliveness
（黒石: +own / 白石: -own）を取り、

  白が死に決定的（<= -DEAD）かつ黒が生き（>= +ALIVE） -> black_to_attack=True
  黒が死に決定的（<= -DEAD）かつ白が生き（>= +ALIVE） -> black_to_attack=False
  それ以外 -> None（幾何推定 guess_black_to_attack を維持）

を導出して、幾何推定・本番当時の推定・既知の正解役割と並べる。ASCII output only.
"""
import itertools
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"


from katrain.core.constants import DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.game import KaTrainSGF, region_analysis_extra_settings
from katrain.core.sgf_parser import Move
from katrain.core.tsumego_capture import grid_to_sgf
from katrain.core.tsumego_frame import (
    BLACK,
    WHITE,
    covers_board_p,
    extremum_stones,
    fallback_region,
    get_analysis_region,
    guess_black_to_attack,
    ij_sizes,
    mark_core_stones,
    pick_all,
    stones_from_bw_board,
    tsumego_frame_stones,
)
from katrain.core.utils import var_to_grid
from katrain_debug.katrain_stub import KaTrainStub

KOMI = 7.0
MARGIN = 4
VISITS = 1800
DEAD = 0.5
ALIVE = 0.5

BASE = os.path.dirname(os.path.abspath(__file__))
CASE_X = os.path.join(BASE, "case-x-attacker-role-edge-20260801-inverted.sgf")

# (name, sgf, region(xmin,xmax,ymin,ymax), known_role or None, note)
CASES = [
    ("D", f"{BASE}\\case-d-gain-region-20260730.sgf", "0,8,0,8", True, "presumed kill"),
    ("E", f"{BASE}\\case-e-ko-margin-20260730.sgf", "3,12,0,8", True, "presumed kill (K1 uncond)"),
    ("F", f"{BASE}\\case-f-gain-visit-share-20260730.sgf", "4,12,3,12", False, "broken frame; truth defends"),
    ("G", f"{BASE}\\case-g-frame-role-20260730.sgf", "0,7,3,12", True, "documented: black attacks"),
    ("J", f"{BASE}\\case-j-points-tie-20260730.sgf", "6,12,1,12", None, "unknown"),
    ("K", f"{BASE}\\case-k-ko-route-20260730.sgf", "0,8,3,12", True, "presumed kill"),
    ("L", f"{BASE}\\case-l-immediate-ko-20260730.sgf", "4,12,0,9", True, "presumed kill"),
    ("M", f"{BASE}\\case-m-capture-gain-ko-20260730.sgf", "4,12,0,8", False, "documented: black lives"),
    ("O", f"{BASE}\\case-o-all-ko-band-20260731.sgf", "0,8,3,12", True, "documented kill (A11)"),
    ("P", f"{BASE}\\case-p-visits-tie-ko-20260731.sgf", "2,12,0,6", True, "presumed kill (white=defender)"),
    ("Q", f"{BASE}\\case-q-ko-is-answer-20260731.sgf", "4,12,4,12", True, "documented: frame role correct"),
    ("S", f"{BASE}\\case-s-attacker-role-tie-20260731.sgf", "5,12,2,12", True, "documented: black attacks"),
    ("T", f"{BASE}\\case-t-defender-seki-20260731.sgf", "2,12,0,6", False, "documented: black defends (seki)"),
    ("U", f"{BASE}\\case-u-move-order-ko-20260731.sgf", "0,8,0,8", True, "documented kill (C1)"),
    ("V", f"{BASE}\\case-v-declass-no-kill-20260731.sgf", "4,12,4,12", True, "documented: black attacks"),
    ("X", CASE_X, "0,6,0,10", True, "THIS BUG: black kills (A4)"),
    # 枠なし保存（認識盤そのもの）。修正対象外だが参考値として測る
    ("G2", f"{BASE}\\case-g2-frameless-guard-20260730.sgf", "0,7,3,12", None, "frameless"),
    ("H", f"{BASE}\\case-h-gate-cliff-20260730.sgf", "5,12,0,6", None, "frameless"),
    ("N", f"{BASE}\\case-n-live-frame-drop-20260730.sgf", "0,5,0,9", False, "frameless; live problem"),
    ("R", f"{BASE}\\case-r-declass-nonsolution-20260731.sgf", "0,12,7,12", None, "frameless"),
    ("W", f"{BASE}\\case-w-frameless-declass-20260801.sgf", "6,12,0,6", False, "frameless; black lives (H1 ko)"),
]


def board_from_node(node, size):
    grid = [["-"] * size for _ in range(size)]
    for prop, mark in (("AB", BLACK), ("AW", WHITE)):
        for sgf in node.get_list_property(prop, []):
            x, y = Move.from_sgf(sgf, (size, size)).coords
            grid[size - 1 - y][x] = mark
    return grid


def strip_frame(grid, region, walls, size):
    xmin, xmax, ymin, ymax = region
    core = [["-"] * size for _ in range(size)]
    for i in range(size):
        for j in range(size):
            x, y = j, size - 1 - i
            if not (xmin <= x <= xmax and ymin <= y <= ymax):
                continue
            if (
                ("xmin" in walls and x == xmin)
                or ("xmax" in walls and x == xmax)
                or ("ymin" in walls and y == ymin)
                or ("ymax" in walls and y == ymax)
            ):
                continue
            core[i][j] = grid[i][j]
    return core


def build(core, ko_p, role):
    stones = stones_from_bw_board(core)
    core_bbox = mark_core_stones(stones, KOMI, MARGIN)
    filled = tsumego_frame_stones(stones, KOMI, True, ko_p, MARGIN, drop_non_core=True, black_to_attack_p=role)
    region = get_analysis_region(pick_all(filled, "tsumego_frame_region_mark"))
    if not region or covers_board_p(region, ij_sizes(core)):
        region = fallback_region(core_bbox, ij_sizes(core)) or region
    board = [[(BLACK if h.get("black") else WHITE) if h.get("stone") else "-" for h in row] for row in filled]
    return board, region


def recover_core(framed, region, size):
    hits = []
    sides = ("xmin", "xmax", "ymin", "ymax")
    for n in range(len(sides) + 1):
        for walls in itertools.combinations(sides, n):
            core = strip_frame(framed, region, walls, size)
            if not any(BLACK in row or WHITE in row for row in core):
                continue
            for role in (False, True):
                for ko_p in (False, True):
                    try:
                        if build(core, ko_p, role)[0] == framed:
                            n_stones = sum(row.count(BLACK) + row.count(WHITE) for row in core)
                            hits.append((n_stones, walls, role, ko_p, core))
                    except Exception:
                        continue
    return max(hits) if hits else None


def geometric_guess(core):
    stones = stones_from_bw_board(core)
    ijs = [
        {"i": i, "j": j, "black": h.get("black")}
        for i, row in enumerate(stones)
        for j, h in enumerate(row)
        if h.get("stone")
    ]
    if not ijs:
        return None
    return guess_black_to_attack(extremum_stones(ijs), ij_sizes(stones))


def raw_ownership(engine, core):
    node = KaTrainSGF.parse_sgf(grid_to_sgf(core, komi=KOMI))
    node.set_property("RU", "chinese")
    out = {}
    engine.request_analysis(
        node,
        callback=lambda a, partial: (
            None if partial else out.setdefault("done", (a["rootInfo"]["scoreLead"], a.get("ownership")))
        ),
        error_callback=lambda e: out.setdefault("err", e),
        visits=VISITS,
        time_limit=False,
        ownership=True,
        extra_settings=region_analysis_extra_settings(VISITS, 0.0),
    )
    deadline = time.time() + 180
    while "done" not in out and "err" not in out and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    if "done" not in out:
        return None, None
    return out["done"]


def derive(core, own_grid):
    size = len(core)
    sums = {BLACK: [0.0, 0], WHITE: [0.0, 0]}
    for i in range(size):
        for j in range(size):
            c = core[i][j]
            if c not in (BLACK, WHITE):
                continue
            x, y = j, size - 1 - i
            own = own_grid[y][x]
            alive = own if c == BLACK else -own
            sums[c][0] += alive
            sums[c][1] += 1
    ab = sums[BLACK][0] / max(1, sums[BLACK][1])
    aw = sums[WHITE][0] / max(1, sums[WHITE][1])
    if aw <= -DEAD and ab >= ALIVE:
        derived = True
    elif ab <= -DEAD and aw >= ALIVE:
        derived = False
    else:
        derived = None
    return ab, sums[BLACK][1], aw, sums[WHITE][1], derived


def main():
    stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    print(f"visits={VISITS} wRN=0 gates: dead<=-{DEAD} alive>=+{ALIVE}")
    print("case | archived_guess | geom | own_black | own_white | derived | final | known | verdict")
    try:
        for name, sgf, region_s, known, note in CASES:
            region = [int(v) for v in region_s.split(",")]
            root = KaTrainSGF.parse_file(sgf)
            size = int(root.get_property("SZ", 19))
            archived = board_from_node(root, size)
            found = recover_core(archived, region, size)
            if found is None:
                core, prod = archived, "frameless"
            else:
                _n, _walls, role, ko, core = found
                prod = f"attacks={role}"
            geom = geometric_guess(core)
            lead, ownership = raw_ownership(engine, core)
            if ownership is None:
                print(f"{name:>4} | {prod:>14} | {str(geom):>5} | analysis failed")
                continue
            own_grid = var_to_grid(ownership, (size, size))
            ab, nb, aw, nw, derived = derive(core, own_grid)
            final = derived if derived is not None else geom
            if known is None:
                verdict = "n/a"
            else:
                verdict = "OK" if final == known else "NG"
                if derived is not None and derived != known:
                    verdict = "NG-OVERRIDE"  # プローブが積極的に誤らせた（最悪）
            print(
                f"{name:>4} | {prod:>14} | {str(geom):>5} | {ab:+.2f}/{nb:>2} | {aw:+.2f}/{nw:>2} "
                f"| {str(derived):>5} | {str(final):>5} | {str(known):>5} | {verdict}  ({note}, lead={lead:+.1f})"
            )
    finally:
        engine.shutdown(finish=False)


main()
