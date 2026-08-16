"""仮想壁で閉じた問題を native ソルバ（df-pn）で解く実測（KataGo 不要・CPU のみ・本番コード無変更）。

`virtual_wall_closure_probe.py` の出力 JSONL から「closed かつ指定変種・色・hole_fix」の行を拾い、
同じ手順で Problem を再構築して root を解く。結果は JSONL（既定 virtual-wall-solver-probe.jsonl）に
1行ずつ追記し、要約を stdout（ASCII のみ）に出す。

usage:
  PYTHONIOENCODING=utf-8 python virtual_wall_solver_probe.py --variant F --attacker guess [--k 2] [--hole-fix 1]
        [--budget-ms 5000] [--max-empties 12] [--limit N] [--start N] [--resume] [--no-opt]
        [--input virtual-wall-closure-probe.jsonl] [--output virtual-wall-solver-probe.jsonl]

--limit 10 で動作確認だけを想定（全件は設計者が別途バックグラウンドで回す）。
"""
import argparse
import collections
import json
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)

import virtual_wall_closure_probe as vw  # noqa: E402

from katrain.core.tsumego_answer_book import gtp_to_point  # noqa: E402
from katrain.core.tsumego_solver.model import gtp_coord  # noqa: E402
from katrain.core.tsumego_solver.native import NativeSolver, native_available  # noqa: E402
from katrain.core.tsumego_solver.reference import SolverLimits, SolverTimeout  # noqa: E402

DEFAULT_IN = os.path.join(HERE, "virtual-wall-closure-probe.jsonl")
DEFAULT_OUT = os.path.join(HERE, "virtual-wall-solver-probe.jsonl")


def row_matches(r, args):
    if not r["closed"]:
        return False
    if r["variant"] != args.variant:
        return False
    if args.variant == "A" and r["k"] != args.k:
        return False
    if r["attacker_choice"] != args.attacker:
        return False
    if bool(r["hole_fix"]) != bool(args.hole_fix):
        return False
    if args.max_empties is not None and r["region_empties"] > args.max_empties:
        return False
    return True


def rebuild_problem(entry, row):
    size = entry["size"]
    black, white = vw.entry_stones(entry)
    if row["variant"] == "A":
        ring, _geo = vw.variant_a_walls(black, white, size, row["k"])
        dropped = frozenset()
    else:
        ring, dropped, _geo = vw.variant_f_walls(black, white, size)
    problem, err, wall_pts, _board = vw.build_problem(
        black, white, size, ring, row["attacker"], dropped, hole_fix=bool(row["hole_fix"])
    )
    return problem, err


def solve_one(problem, budget_ms, optimize_line=True):
    t0 = time.perf_counter()
    out = dict(outcome=None, ko_level=None, plies=None, first_move=None, root_moves=None, nodes=None,
               cycle_tainted=None, error=None)
    try:
        # optimize_line=False で第2段階（plies/material 最適化。native は最低 3 秒燃やす）を省き
        # 分類だけの所要を測れる（クラス・本手は不変。同格タイの並びだけ変わりうる）
        sol = NativeSolver(problem, SolverLimits(time_limit_ms=float(budget_ms), optimize_line=optimize_line)).solve()
        out.update(
            outcome=sol.value.result.name,
            ko_level=sol.value.ko_level,
            plies=sol.value.plies,
            first_move=gtp_coord(sol.root_moves[0]) if sol.root_moves else None,
            root_moves=[gtp_coord(m) for m in sol.root_moves],
            nodes=sol.nodes,
            cycle_tainted=bool(sol.cycle_tainted),
        )
    except SolverTimeout as e:
        out.update(outcome="TIMEOUT", error=str(e))
    except Exception as e:  # native error 等
        out.update(outcome="ERROR", error=f"{type(e).__name__}: {e}")
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return out


def summarize(results, budget_ms):
    print("")
    print(f"=== virtual wall solver probe summary (budget {budget_ms} ms, n={len(results)}) ===")
    oc = collections.Counter(r["outcome"] for r in results)
    print("outcomes:", dict(oc.most_common()))
    solved = [r for r in results if r["outcome"] in ("UNCONDITIONAL", "KO", "SEKI")]
    print(f"solved (UNCONDITIONAL/KO/SEKI): {len(solved)} ; FAILED: {oc.get('FAILED', 0)} ; "
          f"TIMEOUT: {oc.get('TIMEOUT', 0)} ; ERROR: {oc.get('ERROR', 0)}")
    if solved:
        mf = sum(1 for r in solved if r["match_first"])
        ma = sum(1 for r in solved if r["match_any"])
        print(f"solved: first move matches book first move: {mf}/{len(solved)} ; any root move matches: {ma}/{len(solved)}")
    ms = sorted(r["elapsed_ms"] for r in results)
    if ms:
        print(f"elapsed ms: median {ms[len(ms) // 2]:.0f} p90 {ms[int(len(ms) * 0.9) - 1 if len(ms) > 1 else 0]:.0f} max {ms[-1]:.0f} total {sum(ms) / 1000.0:.1f}s")
    print("by region_empties bucket: n / solved / match_first / timeout")
    buckets = collections.defaultdict(list)
    for r in results:
        e = r["region_empties"]
        b = "<=9" if e <= 9 else ("10-12" if e <= 12 else ("13-16" if e <= 16 else ("17-24" if e <= 24 else ">24")))
        buckets[b].append(r)
    for b in ("<=9", "10-12", "13-16", "17-24", ">24"):
        rs = buckets.get(b, [])
        if not rs:
            continue
        s = [r for r in rs if r["outcome"] in ("UNCONDITIONAL", "KO", "SEKI")]
        print(f"  {b:>6}: {len(rs):>4} / {len(s):>4} / {sum(1 for r in s if r['match_first']):>4} / "
              f"{sum(1 for r in rs if r['outcome'] == 'TIMEOUT'):>4}")
    print("by type: n / solved / match_first")
    bt = collections.defaultdict(list)
    for r in results:
        bt[r["type"]].append(r)
    for t, rs in bt.items():
        s = [r for r in rs if r["outcome"] in ("UNCONDITIONAL", "KO", "SEKI")]
        print(f"  {t:>7}: {len(rs):>4} / {len(s):>4} / {sum(1 for r in s if r['match_first']):>4}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="F", choices=["A", "F"])
    ap.add_argument("--k", type=int, default=2, help="A variant ring distance (ignored for F)")
    ap.add_argument("--attacker", default="guess", choices=["guess", "inverse"])
    ap.add_argument("--hole-fix", type=int, default=1, help="1 = rows built with HoleFixExtractor (default), 0 = plain")
    ap.add_argument("--budget-ms", type=int, default=5000)
    ap.add_argument("--max-empties", type=int, default=None, help="only problems with region_empties <= N")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--no-opt", action="store_true", help="skip the plies/material optimisation stage (pure classification time)")
    ap.add_argument("--input", default=DEFAULT_IN)
    ap.add_argument("--output", default=DEFAULT_OUT)
    ap.add_argument("--book", default=vw.DEFAULT_BOOK)
    args = ap.parse_args()
    if not native_available():
        print("native solver DLL not found")
        sys.exit(2)
    rows = [json.loads(line) for line in open(args.input, encoding="utf-8")]
    targets = [r for r in rows if row_matches(r, args)]
    print(f"closure rows: {len(rows)} ; matching closed rows: {len(targets)} "
          f"(variant={args.variant} k={args.k if args.variant == 'A' else 'prod'} attacker={args.attacker} hole_fix={bool(args.hole_fix)}"
          f"{'' if args.max_empties is None else ' max_empties=' + str(args.max_empties)})")
    targets = targets[args.start:]
    if args.limit:
        targets = targets[: args.limit]
    done = set()
    prior = []
    if args.resume and os.path.exists(args.output):
        for line in open(args.output, encoding="utf-8"):
            r = json.loads(line)
            if (r["variant"], r["k"], r["attacker_choice"], bool(r["hole_fix"]), r["budget_ms"]) == (
                args.variant, args.k if args.variant == "A" else r["k"], args.attacker, bool(args.hole_fix), args.budget_ms
            ):
                done.add(r["key"])
                prior.append(r)
        print(f"resume: {len(done)} keys already done in {args.output}")
    book = json.load(open(args.book, encoding="utf-8"))["entries"]
    by_prefix = {k[:10]: e for k, e in book.items()}
    results = list(prior)
    t_all = time.perf_counter()
    with open(args.output, "a", encoding="utf-8") as f:
        for n, row in enumerate(targets, 1):
            if row["key"] in done:
                continue
            entry = by_prefix[row["key"]]
            problem, err = rebuild_problem(entry, row)
            rec = dict(
                key=row["key"],
                size=row["size"],
                variant=row["variant"],
                k=row["k"],
                attacker_choice=row["attacker_choice"],
                attacker=row["attacker"],
                hole_fix=bool(row["hole_fix"]),
                budget_ms=args.budget_ms,
                type=row.get("type"),
                target_size=row.get("target_size"),
                region_size=row.get("region_size"),
                region_empties=row.get("region_empties"),
                line_inside=row.get("line_inside"),
                n_lines=row.get("n_lines"),
            )
            firsts = sorted({line[0] for line in entry["lines"] if line})
            rec["book_first_moves"] = firsts
            if problem is None:
                rec.update(outcome="REBUILD_FAILED", error=err, elapsed_ms=0.0, match_first=False, match_any=False)
            else:
                rec.update(solve_one(problem, args.budget_ms, optimize_line=not args.no_opt))
                rec["optimize_line"] = not args.no_opt
                rec["match_first"] = rec["first_move"] in firsts if rec.get("first_move") else False
                rec["match_any"] = any(m in firsts for m in (rec.get("root_moves") or []))
            results.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(
                f"  [{n}/{len(targets)}] {rec['key']} type={rec['type']} region={rec['region_size']} "
                f"empties={rec['region_empties']} -> {rec['outcome']} first={rec.get('first_move')} "
                f"book={firsts} match={rec['match_first']} {rec['elapsed_ms']:.0f}ms",
                flush=True,
            )
    print(f"done in {time.perf_counter() - t_all:.1f}s ; wrote {args.output}")
    summarize(results, args.budget_ms)


if __name__ == "__main__":
    main()
