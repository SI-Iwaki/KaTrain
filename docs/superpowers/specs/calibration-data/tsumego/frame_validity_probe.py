"""枠が詰碁を壊していないかを判定し、枠あり／枠なしの両方で選択手を出す診断スクリプト。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/frame_validity_probe.py \
      <sgf> <move_number> <xmin,xmax,ymin,ymax> <期待手csv> [trial_visits] [visits] [validity_visits]

引数の SGF は**キャプチャで実際に出題された盤**（保存SGFのroot）。枠付きなら本体（コア）石を
そこから復元する: リージョン内から「壁が乗っている辺」を除いたものがコアで、どの辺が壁かは
幾何だけでは決まらない（枠矩形が盤外にはみ出した辺には壁が置かれない）ため、4辺の総当たり×
(攻め方,コウダテ)4通りを再度枠張りして**元の盤に一致する組み合わせ**を採る。復元できない盤は
枠なしで出題されたキャプチャ（＝盤がコアそのもの）として扱う。

出力:
  - 枠候補ごとの root lead / バランス距離 / 手番側の本体石 ownership（1子平均）
  - 枠の採否判定（`frame_validity_verdicts`。+0.5/子 未満＝枠が詰碁を消している。
    浅い読みで死と出た枠は validity_visits で読み直してから裁定する＝本番と同じ手順）
  - 捨てる先である枠なし盤の同じ読み（全枠が壊れ判定なら `frame_over_frameless` で比較する）
  - 枠あり・枠なしそれぞれで `select_tsumego_move` が選ぶ手

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
    FRAME_VALIDITY_VISITS,
    FRAME_VALIDITY_WIDE_ROOT_NOISE,
    WHITE,
    covers_board_p,
    fallback_region,
    frame_balance_distance,
    frame_over_frameless,
    frame_validity_verdicts,
    frameless_region,
    get_analysis_region,
    ij_sizes,
    mark_core_stones,
    pick_all,
    pick_balanced_frame,
    solver_core_points,
    stones_from_bw_board,
    tsumego_frame_board,
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
VALIDITY_VISITS = int(sys.argv[7]) if len(sys.argv) > 7 else FRAME_VALIDITY_VISITS
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


def frame_with_role(grid, ko_p, role):
    stones = stones_from_bw_board(grid)
    core_bbox = mark_core_stones(stones, KOMI, MARGIN)
    filled = tsumego_frame_stones(stones, KOMI, True, ko_p, MARGIN, drop_non_core=True, black_to_attack_p=role)
    region = get_analysis_region(pick_all(filled, "tsumego_frame_region_mark"))
    if not region or covers_board_p(region, ij_sizes(grid)):
        region = fallback_region(core_bbox, ij_sizes(grid)) or region
    return [[(BLACK if h.get("black") else WHITE) if h.get("stone") else "-" for h in row] for row in filled]


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
                        if frame_with_role(core, ko_p, role) == framed:
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


def trial(engine, board, region, visits, wide_root_noise=0.04):
    """枠の採否判定に使う root 解析（lead と ownership）"""
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
        core, framed = archived, None
        n_core = sum(row.count(BLACK) + row.count(WHITE) for row in core)
        print(f"core recovery: no frame in the archived board -> treating it as the core ({n_core} stones)")
    else:
        n_stones, walls, role, ko_p, core = found
        framed = archived
        print(f"core recovered: {n_stones} stones, walls on {walls or '(none)'}, "
              f"re-frames exactly with black_attacks={role} ko={ko_p}")
    print(f"prefix: {' '.join(f'{p}-{g}' for p, g in prefix) or '(none)'}  expected: {'/'.join(EXPECTED)}")

    engine = KataGoEngine(stub, stub.config("engine"))
    try:
        candidates = []
        for ko in (False, True):
            board, region = tsumego_frame_board(core, KOMI, True, ko_p=ko, margin=MARGIN)
            if any(board == prev for _, prev, _ in candidates):
                print(f"  frame ko={ko}: same board as the other candidate (no ko threat placed)")
                continue
            candidates.append((ko, board, region))

        def read(candidate, visits):
            """本番（_choose_tsumego_frame）と同じ読み。深さは frame_validity_verdicts が決める。

            読み直しは wideRootNoise=0（裁定では探索を critical line に集中させる）
            """
            ko, board, region = candidate
            wrn = FRAME_VALIDITY_WIDE_ROOT_NOISE if visits != TRIAL_VISITS else 0.04
            lead, ownership = trial(engine, board, region, visits, wrn)
            pts = solver_core_points(core, board, region)
            own = var_to_grid(ownership, (len(board[0]), len(board))) if ownership else None
            solver_own = sum(own[y][x] for x, y in pts) if own else None
            print(
                f"  frame ko={ko} v{visits}: "
                f"lead={'n/a' if lead is None else f'{lead:+.2f}'} "
                f"dist={'n/a' if lead is None else f'{frame_balance_distance(lead):.2f}'} "
                + (
                    "solver_core=n/a"
                    if solver_own is None
                    else f"solver_core={solver_own:+.2f}/{len(pts)} ({solver_own / max(1, len(pts)):+.2f}/stone)"
                )
            )
            return lead, solver_own, len(pts)

        verdicts = frame_validity_verdicts(candidates, read, TRIAL_VISITS, VALIDITY_VISITS)
        for v in verdicts:
            print(
                f"  frame ko={v.ko_p}: verdict from the v{v.visits} reading -> "
                f"{'DESTROYS the problem' if v.destroys else 'usable'}"
            )
        # 枠を捨てた先（枠なし盤）も同じ読み方で測る。枠なしは安全側のフォールバックではないので
        # 「枠が壊れている」だけでなく「枠なしより壊れているか」を見ないと判断できない
        fl_region = frameless_region(core, 1)
        fl_readings = {}
        for visits in sorted({TRIAL_VISITS, VALIDITY_VISITS}):
            lead, ownership = trial(engine, core, fl_region, visits)
            pts = solver_core_points(core, core, fl_region)
            own = var_to_grid(ownership, (len(core[0]), len(core))) if ownership else None
            solver_own = sum(own[y][x] for x, y in pts) if own else None
            fl_readings[visits] = (solver_own, len(pts))
            print(
                f"  frameless v{visits}: lead={'n/a' if lead is None else f'{lead:+.2f}'} "
                + (
                    "solver_core=n/a"
                    if solver_own is None
                    else f"solver_core={solver_own:+.2f}/{len(pts)} ({solver_own / max(1, len(pts)):+.2f}/stone)"
                )
            )

        scored = [(v.ko_p, v.board, v.region, v.lead) for v in verdicts if not v.destroys]
        if scored:
            ko, board, region = (pick_balanced_frame(scored) or scored[0])[:3]
            print(f"  decision: frame ko={ko}")
        else:
            # 本番は枠なし側を trial の浅い読みで比較する（深さにほぼ不感なので）
            rescued = frame_over_frameless(verdicts, *fl_readings[TRIAL_VISITS])
            if rescued is None:
                board, region = None, None
                print("  decision: FRAMELESS (every frame kills the solver's stones)")
            else:
                board, region = rescued.board, rescued.region
                print(f"  decision: frame ko={rescued.ko_p} (broken, but the frameless board is worse)")

        boards = []
        if framed is not None:
            boards.append(("archived ", framed, REGION))
        if board is not None:
            boards.append(("frame    ", board, katrain_region(region, board)))
        boards.append(("frameless", core, katrain_region(frameless_region(core, 1), core)))
        for tag, b, r in boards:
            try:
                move = selected_move(stub, engine, b, r, prefix)
            except Exception as e:
                print(f"  [{tag}] failed: {e}")
                continue
            print(f"  [{tag}] region={r} select_tsumego_move -> {move} "
                  f"{'OK' if move in EXPECTED else 'NG'}")
    finally:
        engine.shutdown(finish=False)


main()
