"""枠の攻め方推定（black_to_attack_p）を強制して A/B し、推定の当否を切り分ける診断スクリプト。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/frame_role_ab.py \
      <sgf> <move_number> <xmin,xmax,ymin,ymax> <期待手csv> [trial_visits] [visits]

`frame_validity_probe.py` は本番と同じ経路（＝`guess_black_to_attack` の推定をそのまま使う）
しか測らないので、「枠が壊れている」と出たときに**推定が反転しているのか、この詰碁では
どちらの役割でも枠が張れないのか**を区別できない。こちらは (攻め方, コウダテ) の4通りを
すべて張り、枠ごとに

  - root lead / バランス距離（`frame_balance_distance`）
  - 手番側の本体石 ownership（1子平均。`frame_destroys_problem` が見る値）
  - その盤で `select_tsumego_move` が選ぶ手

を並べる。実測 case S（殺す詰碁・推定が反転）では role=True の2枠だけが +1.00/子 で正解 M10 を
選び、role=False の2枠は +0.65/+0.08 で誤答 H12 を選んだ。

**この出力を「役割の自動判定」に使ってはいけない**。反転した枠では手番側が「攻め方」になって
壁と連絡するので、生きる詰碁では**誤った役割のほうが solver_core が高く出る**（実測 case M:
誤 +0.99/子 vs 正 +0.72/子）。バランス距離も case S / case M とも誤った役割が最良を出す
（2.5 / 2.7）。役割は測って選べないので、推定そのもの（`guess_black_to_attack` に渡す極値）を
正すのが唯一の手（spec 追記27）。

ASCII output only（cp932 端末で落ちないように）。
"""
import itertools
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.ai import select_tsumego_move, tsumego_gain_stones
from katrain.core.constants import DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.game import KaTrainSGF, region_analysis_extra_settings
from katrain.core.sgf_parser import Move
from katrain.core.tsumego_capture import grid_to_sgf
from katrain.core.tsumego_frame import (
    BLACK,
    FRAME_SOLVER_ALIVE_OWNERSHIP,
    FRAME_VALIDITY_WIDE_ROOT_NOISE,
    WHITE,
    covers_board_p,
    fallback_region,
    frame_balance_distance,
    get_analysis_region,
    ij_sizes,
    mark_core_stones,
    pick_all,
    solver_core_points,
    stones_from_bw_board,
    tsumego_frame_stones,
)
from katrain.core.utils import var_to_grid
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
EXPECTED = sys.argv[4].split(",")
TRIAL_VISITS = int(sys.argv[5]) if len(sys.argv) > 5 else 400
VISITS = int(sys.argv[6]) if len(sys.argv) > 6 else 1800
KOMI = 7.0
MARGIN = 4
SETTINGS = dict(max_points_behind=2.0, gain_epsilon=0.3, min_visits=10, gain_min_visit_ratio=0.5)


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
                continue  # 枠外の充填
            if (
                ("xmin" in walls and x == xmin)
                or ("xmax" in walls and x == xmax)
                or ("ymin" in walls and y == ymin)
                or ("ymax" in walls and y == ymax)
            ):
                continue  # 壁
            core[i][j] = grid[i][j]
    return core


def build(core, ko_p, role):
    """役割を強制して枠を張り (board, region) を返す（region は tsumego_frame の (i,j) 表現）"""
    stones = stones_from_bw_board(core)
    core_bbox = mark_core_stones(stones, KOMI, MARGIN)
    filled = tsumego_frame_stones(stones, KOMI, True, ko_p, MARGIN, drop_non_core=True, black_to_attack_p=role)
    region = get_analysis_region(pick_all(filled, "tsumego_frame_region_mark"))
    if not region or covers_board_p(region, ij_sizes(core)):
        region = fallback_region(core_bbox, ij_sizes(core)) or region
    board = [[(BLACK if h.get("black") else WHITE) if h.get("stone") else "-" for h in row] for row in filled]
    return board, region


def recover_core(framed, region, size):
    """再度枠を張ると元の盤に一致するコアを返す（一致する中で最大のもの）"""
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


def katrain_region(region, board):
    if not region:
        return None
    (imin, imax), (jmin, jmax) = region
    return [jmin, jmax, len(board) - 1 - imax, len(board) - 1 - imin]


def trial(engine, board, region, visits, wide_root_noise):
    node = KaTrainSGF.parse_sgf(grid_to_sgf(board, komi=KOMI))
    node.set_property("RU", "chinese")
    out = {}
    engine.request_analysis(
        node,
        callback=lambda a, partial: (
            None if partial else out.setdefault("done", (a["rootInfo"]["scoreLead"], a.get("ownership")))
        ),
        error_callback=lambda e: out.setdefault("err", e),
        visits=visits,
        time_limit=False,
        ownership=True,
        region_of_interest=katrain_region(region, board),
        extra_settings=region_analysis_extra_settings(visits, wide_root_noise),
    )
    deadline = time.time() + 120
    while "done" not in out and "err" not in out and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    return out.get("done", (None, None))


def selected_move(stub, engine, board, region, prefix):
    """本番と同じ2段解析（全盤fast → リージョン+ownership）の上で select_tsumego_move を回す"""
    node = KaTrainSGF.parse_sgf(grid_to_sgf(board, komi=KOMI))
    node.set_property("RU", "chinese")
    game = DebugGame(katrain=stub, engine=engine, move_tree=node)
    stub.game = game
    game.region_of_interest = list(region) if region else None
    cur = game.current_node
    for player, gtp in prefix:
        cur = game.play(Move.from_gtp(gtp, player=player))
    cur.analyze(engine, analyze_fast=True)
    deadline = time.time() + 300
    while cur.analysis["root"] is None and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    cur.analyze(
        engine,
        region_of_interest=list(region) if region else None,
        visits=VISITS,
        time_limit=False,
        extra_settings=region_analysis_extra_settings(VISITS, 0.04),
        ownership=True,
    )
    deadline = time.time() + 300
    while not cur.analysis.get("region_completed") and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    stones = tsumego_gain_stones([s.coords for s in game.stones], game.region_of_interest)
    picked = select_tsumego_move(
        cur.candidate_moves,
        cur.ownership,
        stones,
        game.board_size,
        cur.player_sign(cur.next_player),
        SETTINGS["max_points_behind"],
        SETTINGS["gain_epsilon"],
        SETTINGS["min_visits"],
        SETTINGS["gain_min_visit_ratio"],
    )
    return picked["move"] if picked else None


def main():
    stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
    node = load_sgf_to_move(SGF, MOVE_N)
    prefix, root = [], node
    while root.parent:
        if root.move:
            prefix.append((root.move.player, root.move.gtp()))
        root = root.parent
    prefix.reverse()
    size = int(root.get_property("SZ", 19))
    archived = board_from_node(root, size)
    found = recover_core(archived, REGION, size)
    if found is None:
        # 枠なしで出題されたキャプチャは保存 SGF が認識盤そのもの（枠が無いので復元できない）
        core = archived
        n_core = sum(row.count(BLACK) + row.count(WHITE) for row in core)
        print(f"core recovery: no frame in the archived board -> treating it as the core ({n_core} stones)")
    else:
        n_stones, walls, guessed_role, guessed_ko, core = found
        print(f"core recovered: {n_stones} stones, walls on {walls or '(none)'}, "
              f"production guess: black_attacks={guessed_role} ko={guessed_ko}")
    print(f"prefix: {' '.join(f'{p}-{g}' for p, g in prefix) or '(none)'}  expected: {'/'.join(EXPECTED)}")

    engine = KataGoEngine(stub, stub.config("engine"))
    try:
        for role in (False, True):
            for ko in (False, True):
                board, region = build(core, ko, role)
                tag = f"black_attacks={str(role):5s} ko={str(ko):5s}"
                pts = solver_core_points(core, board, region)
                for visits, wrn in ((TRIAL_VISITS, 0.04), (VISITS, FRAME_VALIDITY_WIDE_ROOT_NOISE)):
                    lead, ownership = trial(engine, board, region, visits, wrn)
                    own = var_to_grid(ownership, (len(board[0]), len(board))) if ownership else None
                    solver_own = sum(own[y][x] for x, y in pts) if own else None
                    per = None if solver_own is None else solver_own / max(1, len(pts))
                    print(
                        f"  {tag} v{visits}: lead={'n/a' if lead is None else f'{lead:+.2f}'} "
                        f"dist={'n/a' if lead is None else f'{frame_balance_distance(lead):.2f}'} "
                        + ("solver_core=n/a" if per is None else
                           f"solver_core={solver_own:+.2f}/{len(pts)} ({per:+.2f}/stone) "
                           f"{'DESTROYS' if per < FRAME_SOLVER_ALIVE_OWNERSHIP else 'usable'}")
                    )
                try:
                    move = selected_move(stub, engine, board, katrain_region(region, board), prefix)
                except Exception as e:
                    print(f"  {tag} select failed: {e}")
                    continue
                print(f"  {tag} region={katrain_region(region, board)} select_tsumego_move -> {move} "
                      f"{'OK' if move in EXPECTED else 'NG'}")
    finally:
        engine.shutdown(finish=False)


main()
