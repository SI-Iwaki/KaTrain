"""役割フリップテストの横断検証: 「守り方とされた群の生死が手番に依存するか」で枠の役割を裁定できるか。

詰碁の定義は「先に打つ側が局所の生死を決める」こと。正しい役割の枠では、想定守り方の群の
ownership が攻め方先手（死ぬ）と守り方先手（生きる）で反転するはず。反転した役割の枠では
想定守り方（実際は強い壁）の生死に何も懸かっていないので、手番を入れ替えても動かないはず。

各ケースの保存 SGF からコアを復元し、役割×コウダテの4枠を張って、それぞれ
黒先・白先の2クエリ（region あり・wRN=0・800visits・ownership）で想定守り方の
コア石 1子平均 aliveness（守り方視点: +が生存）を測り、

  delta = aliveness(守り方先手) - aliveness(攻め方先手)

を出す。予想: 正しい役割で delta 大、誤った役割で delta ~0。ASCII output only.
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
    fallback_region,
    get_analysis_region,
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
VISITS = 800

BASE = os.path.dirname(os.path.abspath(__file__))
CASE_X = os.path.join(BASE, "case-x-attacker-role-edge-20260801-inverted.sgf")

# (name, sgf, region, known_role, note)  known_role: 真の black_to_attack
CASES = [
    ("D", f"{BASE}\\case-d-gain-region-20260730.sgf", "0,8,0,8", True, "kill"),
    ("E", f"{BASE}\\case-e-ko-margin-20260730.sgf", "3,12,0,8", True, "kill K1"),
    ("F", f"{BASE}\\case-f-gain-visit-share-20260730.sgf", "4,12,3,12", False, "broken frame"),
    ("G", f"{BASE}\\case-g-frame-role-20260730.sgf", "0,7,3,12", True, "kill A11 ko"),
    ("J", f"{BASE}\\case-j-points-tie-20260730.sgf", "6,12,1,12", None, "unknown"),
    ("K", f"{BASE}\\case-k-ko-route-20260730.sgf", "0,8,3,12", True, "kill"),
    ("L", f"{BASE}\\case-l-immediate-ko-20260730.sgf", "4,12,0,9", True, "kill J6"),
    ("M", f"{BASE}\\case-m-capture-gain-ko-20260730.sgf", "4,12,0,8", False, "black lives"),
    ("O", f"{BASE}\\case-o-all-ko-band-20260731.sgf", "0,8,3,12", True, "kill A11"),
    ("P", f"{BASE}\\case-p-visits-tie-ko-20260731.sgf", "2,12,0,6", True, "kill J1"),
    ("Q", f"{BASE}\\case-q-ko-is-answer-20260731.sgf", "4,12,4,12", True, "kill N9 (engine-blind)"),
    ("S", f"{BASE}\\case-s-attacker-role-tie-20260731.sgf", "5,12,2,12", True, "kill M10"),
    ("T", f"{BASE}\\case-t-defender-seki-20260731.sgf", "2,12,0,6", False, "black lives seki"),
    ("U", f"{BASE}\\case-u-move-order-ko-20260731.sgf", "0,8,0,8", True, "kill C1"),
    ("V", f"{BASE}\\case-v-declass-no-kill-20260731.sgf", "4,12,4,12", True, "kill L12"),
    ("X", CASE_X, "0,6,0,10", True, "THIS BUG kill A4"),
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


def defender_points(core, framed, region, defender):
    """想定守り方の色のコア石（認識盤と枠付き盤の両方に同色で居る点）の (x, y)"""
    size = len(framed)
    if region:
        (imin, imax), (jmin, jmax) = region
    else:
        imin, imax, jmin, jmax = 0, size - 1, 0, size - 1
    return [
        (j, size - 1 - i)
        for i in range(max(0, imin), min(size - 1, imax) + 1)
        for j in range(max(0, jmin), min(size - 1, jmax) + 1)
        if core[i][j] == defender and framed[i][j] == defender
    ]


def analysis_start(engine, board, region, first_player):
    sgf = grid_to_sgf(board, komi=KOMI)
    if first_player == "W":
        sgf = sgf.replace("PL[B]", "PL[W]")
    node = KaTrainSGF.parse_sgf(sgf)
    node.set_property("RU", "chinese")
    kregion = None
    if region:
        (imin, imax), (jmin, jmax) = region
        kregion = [jmin, jmax, len(board) - 1 - imax, len(board) - 1 - imin]
    out = {}
    engine.request_analysis(
        node,
        callback=lambda a, partial: (None if partial else out.setdefault("done", a.get("ownership"))),
        error_callback=lambda e: out.setdefault("err", e),
        visits=VISITS,
        time_limit=False,
        ownership=True,
        region_of_interest=kregion,
        extra_settings=region_analysis_extra_settings(VISITS, 0.0),
    )
    return out


def analysis_wait(engine, out):
    deadline = time.time() + 180
    while "done" not in out and "err" not in out and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    return out.get("done")


def aliveness(ownership, board, pts, defender):
    if ownership is None or not pts:
        return None
    own = var_to_grid(ownership, (len(board[0]), len(board)))
    sign = 1 if defender == BLACK else -1
    return sign * sum(own[y][x] for x, y in pts) / len(pts)


def main():
    stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    print(f"visits={VISITS} wRN=0  aliveness = 想定守り方コア石の1子平均（守り方視点、+が生存）")
    print("case role  ko    | atk_first | def_first | delta | (n_def)  known_role")
    try:
        for name, sgf, region_s, known, note in CASES:
            region = [int(v) for v in region_s.split(",")]
            root = KaTrainSGF.parse_file(sgf)
            size = int(root.get_property("SZ", 19))
            archived = board_from_node(root, size)
            found = recover_core(archived, region, size)
            if found is None:
                print(f"{name:>4} frameless archive -> skip")
                continue
            _n, _walls, arch_role, _ko, core = found
            jobs = []
            for role in (False, True):
                for ko in (False, True):
                    try:
                        board, bregion = build(core, ko, role)
                    except Exception as e:
                        print(f"{name:>4} {role!s:5} {ko!s:5} | build failed: {e}")
                        continue
                    defender = WHITE if role else BLACK
                    pts = defender_points(core, board, bregion, defender)
                    atk_first = "B" if role else "W"
                    def_first = "W" if role else "B"
                    jobs.append(
                        (
                            role,
                            ko,
                            board,
                            pts,
                            defender,
                            analysis_start(engine, board, bregion, atk_first),
                            analysis_start(engine, board, bregion, def_first),
                        )
                    )
            for role, ko, board, pts, defender, out_a, out_d in jobs:
                a_atk = aliveness(analysis_wait(engine, out_a), board, pts, defender)
                a_def = aliveness(analysis_wait(engine, out_d), board, pts, defender)
                if a_atk is None or a_def is None:
                    print(f"{name:>4} {role!s:5} {ko!s:5} | analysis failed (n_def={len(pts)})")
                    continue
                delta = a_def - a_atk
                mark = "<== true" if known is not None and role == known else ""
                print(
                    f"{name:>4} {role!s:5} {ko!s:5} | {a_atk:+9.2f} | {a_def:+9.2f} | {delta:+5.2f} | "
                    f"(n={len(pts):>2})  known={known} arch={arch_role} {mark}"
                )
    finally:
        engine.shutdown(finish=False)


main()
