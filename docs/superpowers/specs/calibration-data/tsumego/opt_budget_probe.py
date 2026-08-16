"""ソルバ第2段階（plies/material 最適化）が短い予算をどれだけ燃やしているかの実測と A/B（KataGo 不要）。

spec `2026-08-15-tsumego-extraction-expansion-design.md` §0.6-1。

問題: 実効設定は `solver_time_limit_ms=5000`（`katrain/config.json`）／
`solver_opt_skip_after_ms=5000`（`tsumego_solver_api.DEFAULT_SETTINGS`）なので、
「第1段階が遅かったら opt を省く」ゲート（`reference.py` の `allow_opt`）は
**予算と同値＝構造的に発火しない**。さらに `NativeSolver.OPT_TIME_MS` は
`clamp(0.1*budget, 3000, 30000)` なので、5000ms 予算では opt 1本に **3000ms**（＝予算の60%）
まで与えることになる（0.1*5000=500 が下限 3000 に持ち上げられる）。

測ること（route=solver の実問題＝GUI が実際にソルバで出題している 134 問）:
  - 総所要・opt に費やした時間・opt の回数とタイムアウト回数
  - opt を締めたときに **返る手（root_moves）とクラスが変わるか**（＝A/B の破損側）

knob:
  --opt-skip-frac F   opt_skip_after_ms = min(設定値, F * budget)   （F=None で現行）
  --opt-time-frac F   OPT_TIME_MS       = min(現行式,  F * budget)   （F=None で現行）
どちらも **min で締める側にしか動かさない**ので、長い予算（P1 スイートの 60000ms 等）では
現行と同一になる＝校正ランの挙動を変えない。

arm は **1鍵ぶんを続けて**回す（背景に別の実験が走っていても arm 間の比較が歪まないように）。
`base2` は base と同条件の2本目＝同じ負荷条件下の run 間ノイズの物差し。

usage:
  PYTHONIOENCODING=utf-8 python opt_budget_probe.py --arms base,base2,skip50,both50 --out opt-budget.jsonl
  python opt_budget_probe.py --compare opt-budget.jsonl base skip50

ASCII output only。
"""
import argparse
import json
import os
import sys
import time
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.tsumego_problem import DEFAULT_MAX_REGION_POINTS, extract_problem  # noqa: E402
from katrain.core.tsumego_solver import SolverLimits, SolverTimeout  # noqa: E402
from katrain.core.tsumego_solver.native import NativeSolver, native_available  # noqa: E402

import framed_extraction_census as fc  # noqa: E402

BOOK_PATH = os.path.expanduser("~/.katrain/tsumego_answers.json")


class InstrumentedSolver(NativeSolver):
    """opt の所要と回数を数え、OPT_TIME_MS を締められるようにしたネイティブソルバ。"""

    def __init__(self, problem, limits=None, opt_time_frac=None):
        super().__init__(problem, limits)
        self.opt_ms = 0.0
        self.opt_calls = 0
        self.opt_timeouts = 0
        self._opt_time_frac = opt_time_frac

    @property
    def OPT_TIME_MS(self):
        base = NativeSolver.OPT_TIME_MS.fget(self)
        if self._opt_time_frac is None:
            return base
        return min(base, self._opt_time_frac * self.limits.time_limit_ms)

    def _optimize_after(self, move, info):
        t = time.time()
        try:
            return super()._optimize_after(move, info)
        except SolverTimeout:
            self.opt_timeouts += 1
            raise
        finally:
            self.opt_ms += (time.time() - t) * 1000.0
            self.opt_calls += 1


def gtp_of(point):
    if point is None:
        return "pass"
    x, y = point
    return f"{fc.LETTERS[x]}{y + 1}"


def run_one(problem, budget_ms, opt_skip_frac, opt_time_frac, opt_skip_setting=5000.0):
    skip = float(opt_skip_setting)
    if opt_skip_frac is not None:
        skip = min(skip, opt_skip_frac * budget_ms)
    limits = SolverLimits(time_limit_ms=float(budget_ms), opt_skip_after_ms=skip)
    solver = InstrumentedSolver(problem, limits, opt_time_frac=opt_time_frac)
    t0 = time.time()
    out = {"opt_skip_effective": skip}
    try:
        sol = solver.solve()
        out.update(
            status="solved",
            result=sol.value.result.name,
            ko_level=sol.value.ko_level,
            plies=sol.value.plies,
            material=sol.value.material,
            root_moves=[gtp_of(m) for m in sol.root_moves],
            principal=[gtp_of(m) for m in sol.principal_line][:8],
            nodes=sol.nodes,
        )
    except SolverTimeout:
        out.update(status="timeout")
    except Exception as e:
        out.update(status="error", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-600:])
    finally:
        total = (time.time() - t0) * 1000.0
        out.update(
            total_ms=round(total, 1),
            opt_ms=round(solver.opt_ms, 1),
            stage1_ms=round(total - solver.opt_ms, 1),
            opt_calls=solver.opt_calls,
            opt_timeouts=solver.opt_timeouts,
        )
        kernel = getattr(solver, "kernel", None)
        if kernel is not None:
            kernel.close()
    return out


ARMS = {
    # 名前: (opt_skip_frac, opt_time_frac)
    "base": (None, None),  # 現行（opt_skip=5000 は 5000ms 予算では発火しない／opt 1本 3000ms）
    "base2": (None, None),  # 同条件の2本目＝同じ負荷条件下の run 間ノイズ
    "skip50": (0.5, None),  # ゲートだけ締める
    "time50": (None, 0.5),  # opt 1本の上限だけ締める
    "time20": (None, 0.2),
    "time10": (None, 0.1),  # = OPT_TIME_MIN_MS(3000) の下限を外して素の 0.1*budget に戻す
    "both50": (0.5, 0.5),
    "both20": (0.5, 0.2),
    "both33": (0.34, 0.34),
    "time30": (None, 0.3),
}


def cmd_run(args):
    here = os.path.dirname(os.path.abspath(__file__))
    census = [json.loads(l) for l in open(os.path.join(here, "framed-extraction-census.jsonl"), encoding="utf-8")]
    keys = [r["key"] for r in census if r["route"] == args.route]
    book = json.load(open(args.book, encoding="utf-8"))["entries"]
    if args.limit:
        keys = keys[: args.limit]
    arms = [a for a in args.arms.split(",") if a]
    for a in arms:
        if a not in ARMS:
            raise SystemExit(f"unknown arm {a}; known: {sorted(ARMS)}")
    out_path = args.out or os.path.join(here, "opt-budget.jsonl")
    print(
        f"keys {len(keys)}  route={args.route}  budget {args.budget_ms}ms  native={native_available()}"
        f"  arms={arms}  -> {out_path}",
        flush=True,
    )
    done = set()
    if args.resume and os.path.exists(out_path):
        for l in open(out_path, encoding="utf-8"):
            try:
                d = json.loads(l)
                done.add((d["key"], d["arm"]))
            except Exception:
                pass
    tally = {}
    with open(out_path, "a", encoding="utf-8") as out:
        for n, key in enumerate(keys, 1):
            # 1鍵ぶんの全 arm を**続けて**回す（背景負荷が時間で変わっても arm 間の比較が歪まない）
            problem = None
            setup_err = None
            meta = {}
            try:
                grid = fc.entry_to_grid(book[key])
                problem = extract_problem(grid=grid, to_play="B", max_region_points=DEFAULT_MAX_REGION_POINTS)
                n_st = sum(1 for q in problem.region if q in problem.black or q in problem.white)
                meta = dict(region=len(problem.region), empties=len(problem.region) - n_st,
                            type=problem.problem_type.value)
            except Exception as e:
                setup_err = f"{type(e).__name__}: {e}"
            for arm in arms:
                if (key, arm) in done:
                    continue
                row = {"key": key, "arm": arm, **meta}
                if problem is None:
                    row.update(status="setup_error", error=setup_err)
                else:
                    skip_frac, time_frac = ARMS[arm]
                    row.update(run_one(problem, args.budget_ms, skip_frac, time_frac))
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                tally[f"{arm}:{row['status']}"] = tally.get(f"{arm}:{row['status']}", 0) + 1
                print(
                    f"[{n}/{len(keys)}] {key[:8]} {arm} reg={row.get('region')} emp={row.get('empties')}"
                    f" {row['status']} total={row.get('total_ms')} opt={row.get('opt_ms')}"
                    f" calls={row.get('opt_calls')} to={row.get('opt_timeouts')} plies={row.get('plies')}",
                    flush=True,
                )
    print("tally:", dict(sorted(tally.items())))


def cmd_compare(args):
    path, arm_a, arm_b = args.compare
    rows = {}
    for l in open(path, encoding="utf-8"):
        d = json.loads(l)
        rows.setdefault(d["arm"], {})[d["key"]] = d
    a, b = rows.get(arm_a, {}), rows.get(arm_b, {})
    keys = [k for k in a if k in b]
    diff_move, diff_class, diff_plies = [], [], []
    ta = tb = 0.0
    for k in keys:
        ra, rb = a[k], b[k]
        ta += ra.get("total_ms") or 0
        tb += rb.get("total_ms") or 0
        if ra.get("status") != rb.get("status") or ra.get("result") != rb.get("result"):
            diff_class.append(k)
        elif (ra.get("root_moves") or [None])[:1] != (rb.get("root_moves") or [None])[:1]:
            diff_move.append(k)
        elif ra.get("plies") != rb.get("plies") or ra.get("material") != rb.get("material"):
            diff_plies.append(k)
    print(f"compared {len(keys)} keys: {arm_a} vs {arm_b} ({os.path.basename(path)})")
    print(f"  total time  {ta/1000:.1f}s -> {tb/1000:.1f}s  ({(tb-ta)/1000:+.1f}s)")
    print(f"  class/status differs : {len(diff_class)} {[k[:8] for k in diff_class][:12]}")
    print(f"  best move differs    : {len(diff_move)} {[k[:8] for k in diff_move][:12]}")
    print(f"  plies/material only  : {len(diff_plies)} {[k[:8] for k in diff_plies][:12]}")
    for label, src in ((arm_a, a), (arm_b, b)):
        opt = sum(src[k].get("opt_ms") or 0 for k in keys)
        to = sum(src[k].get("opt_timeouts") or 0 for k in keys)
        calls = sum(src[k].get("opt_calls") or 0 for k in keys)
        solved = [k for k in keys if src[k].get("status") == "solved"]
        p0 = sum(1 for k in solved if (src[k].get("plies") or 0) == 0)
        worst = sorted(keys, key=lambda k: -(src[k].get("total_ms") or 0))[:5]
        print(
            f"  [{label}] opt {opt/1000:.1f}s in {calls} calls ({to} timeouts)"
            f"  solved {len(solved)}  of which plies=0: {p0}"
            f"  slowest: {[(k[:8], src[k].get('total_ms')) for k in worst]}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=BOOK_PATH)
    ap.add_argument("--out")
    ap.add_argument("--route", default="solver")
    ap.add_argument("--budget-ms", type=int, default=5000)
    ap.add_argument("--arms", default="base,base2,skip50,both50", help=f"カンマ区切り。既知: {sorted(ARMS)}")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--compare", nargs=3, metavar=("JSONL", "ARM_A", "ARM_B"))
    args = ap.parse_args()
    if args.compare:
        cmd_compare(args)
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
