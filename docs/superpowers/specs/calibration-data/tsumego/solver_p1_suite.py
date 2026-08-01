"""P1: 死活ソルバ（参照実装）を既存20ケースに掛けて正答率を測る（KataGo 不要）。

スペック §10.2 / §11。I/Q/R/W が解けるかが方式の是非を決める意思決定点。
e2e_suite.py と同じケース表（SGF・region・正解手順 line・回帰点 expect）を使う。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/solver_p1_suite.py [case...] [--full] [--time MS]
    既定: expect のある手番だけ。--full で line の全黒番。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * 4))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from e2e_suite import CASES, KNOWN_LIMITS  # noqa: E402

from katrain.core.sgf_parser import SGF  # noqa: E402
from katrain.core.tsumego_problem import extract_problem  # noqa: E402
from katrain.core.tsumego_solver.board import board_from_stones  # noqa: E402
from katrain.core.tsumego_solver.model import (  # noqa: E402
    BLACK,
    WHITE,
    EMPTY,
    ProblemError,
    from_gtp_coord,
    gtp_coord,
    problem_with_stones,
)
from katrain.core.tsumego_solver.reference import ReferenceSolver, SolverLimits, SolverTimeout  # noqa: E402
from katrain.core.tsumego_solver.native import NativeSolver, native_available  # noqa: E402

SOLVER_CLASS = ReferenceSolver


def board_at(sgf_path, line, plies):
    root = SGF.parse_file(sgf_path)
    size = root.board_size
    black = {m.coords for m in root.placements if m.player == "B"}
    white = {m.coords for m in root.placements if m.player == "W"}
    board = board_from_stones(size, black, white)
    player = "B"
    for gtp in line[:plies]:
        pt = from_gtp_coord(gtp)
        if pt is not None:
            u = board.try_play(board.index(pt), player)
            assert u is not None, f"illegal move in line: {gtp}"
        player = "W" if player == "B" else "B"
    blk = {board.point(p) for p in range(len(board.stones)) if board.stones[p] == BLACK}
    wht = {board.point(p) for p in range(len(board.stones)) if board.stones[p] == WHITE}
    return blk, wht, size


def run_case(name, case, plies_list, time_ms):
    sgf = os.path.join(HERE, case["sgf"])
    region = [int(v) for v in case["region"].split(",")]
    rows = []
    # 問題コンテキストは出題時（ply 0）に確定し以後引き継ぐ（§9.1）。要求手番が後ろでも抽出は ply 0
    try:
        blk0, wht0, size0 = board_at(sgf, case["line"], 0)
        base_problem = extract_problem(stones=(blk0, wht0), board_size=size0, to_play=BLACK, region_hint=region)
    except ProblemError as e:
        return [(f"{name}@*", "EXTR-ERR", f"err={e}")]
    for k in plies_list:
        blk, wht, size = board_at(sgf, case["line"], k)
        wanted = case["expect"].get(k) or (case["line"][k],)
        t0 = time.time()
        played = [from_gtp_coord(g) for g in case["line"][:k]]
        if any(pt is not None and pt not in base_problem.region for pt in played):
            # 着手が region の外に出た＝戦いが想定より広い → その局面で再抽出（§9.1）
            try:
                prob = extract_problem(stones=(blk, wht), board_size=size, to_play=BLACK, region_hint=region)
            except ProblemError as e:
                rows.append((f"{name}@{k}", "EXTR-ERR", f"expected={'/'.join(wanted)} 再抽出 err={e}"))
                continue
        else:
            prob = problem_with_stones(base_problem, blk, wht)
        t1 = time.time()
        try:
            sol = SOLVER_CLASS(prob, SolverLimits(time_limit_ms=time_ms)).solve()
        except SolverTimeout as e:
            rows.append(
                (
                    f"{name}@{k}",
                    "TIMEOUT",
                    f"expected={'/'.join(wanted)} type={prob.problem_type.value}"
                    f" region={len(prob.region)} target={len(prob.target)} ({e})",
                )
            )
            continue
        t2 = time.time()
        got = [gtp_coord(m) for m in sol.root_moves]
        verdict = "PASS" if any(g in wanted for g in got[:1]) else ("ALT" if any(g in wanted for g in got) else "FAIL")
        rows.append(
            (
                f"{name}@{k}",
                verdict,
                f"expected={'/'.join(wanted)} got={got} class={sol.value.result.name}"
                f"/ko{sol.value.ko_level}/p{sol.value.plies} type={prob.problem_type.value}"
                f" region={len(prob.region)} [extract {t1 - t0:.2f}s solve {t2 - t1:.1f}s nodes={sol.nodes}]",
            )
        )
        print(f"    {rows[-1][0]}: {rows[-1][1]}  {rows[-1][2]}", flush=True)
    return rows


def main():
    global SOLVER_CLASS
    args = list(sys.argv[1:])
    full = "--full" in args
    if "--native" in args:
        assert native_available(), "native DLL not found"
        SOLVER_CLASS = NativeSolver
        print("solver: native (Rust kernel)")
    time_ms = 300_000.0
    if "--time" in args:
        i = args.index("--time")
        time_ms = float(args[i + 1])
        del args[i : i + 2]
    argv = [a for a in args if not a.startswith("--")]
    table = dict(CASES)
    table.update(KNOWN_LIMITS)
    names = argv or list(table)
    all_rows = []
    for nm in names:
        case = table.get(nm)
        if case is None:
            print(f"unknown case: {nm}")
            continue
        plies = sorted(range(0, len(case["line"]), 2)) if full else sorted(case["expect"])
        print(f"--- {nm} ({case['sgf']}) plies={plies}", flush=True)
        all_rows.extend(run_case(nm, case, plies, time_ms))
    print("\n=== P1 solver suite summary ===")
    for label, verdict, detail in all_rows:
        print(f"{verdict:<8} {label:<8} {detail}")
    n_pass = sum(1 for r in all_rows if r[1] == "PASS")
    print(f"\n{n_pass}/{len(all_rows)} PASS")


if __name__ == "__main__":
    main()
