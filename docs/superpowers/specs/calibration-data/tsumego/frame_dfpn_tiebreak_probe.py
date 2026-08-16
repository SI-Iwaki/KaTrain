"""枠経路の別解手番で「df-pn の順序がアプリの作意手を上に置くか」を測る（KataGo 不要）。

spec `2026-08-15-tsumego-extraction-expansion-design.md` §0.5 の測定。

背景: 回答帳リプレイの不一致 218 のうち true_miss は 5 で、残りは alternative（chosen も
成立＝別解）と undecided。アプリは解答樹に無い別解を不正解にするので、体験を動かすのは
「**成立する複数手からアプリの作意手を当てる**」信号。df-pn の順序
（ResultClass > sub_demotion > ko_level > plies > material）は作意の慣習（無条件優先・
最短手数・石損最小）を部分的に表現している。**枠経路のタイブレーク（visits 本命）に
載せる価値があるかを、載せる前に測る。**

やること: `answer-book-verify-*.jsonl` の route=frame かつ class=alternative の手番について、

  1. 回答帳 entry → 認識グリッド → **枠あり盤**（`tsumego_frame_board`。ko_p は指定）
  2. 記録手順の prefix（depth 手）を盤に打つ（取りは Board.try_play が処理）
  3. 枠リージョンを hint に `extract_problem` → Problem
  4. `NativeSolver.solve()` を1回（**root 全手の分類 `Solution.move_values` が一度に取れる**）
  5. want（アプリの手）と chosen（戦略が打った手）が **同格タイ `root_moves` に入るか**で判定

判定バケット:

  want_only    want だけが df-pn の best タイに入る＝**df-pn タイブレークが直す手番**
  chosen_only  chosen だけが入る＝**df-pn タイブレークが壊す手番**
  both         両方入る（df-pn では同格＝この軸では選び分けられない）
  neither      どちらも入らない（df-pn の best はさらに別の手）

同時に、GUI に載せられるかの実現可能性（solve が予算内に終わるか・所要秒）も測る。
ko_p は枠のコウダテ配分で、本番は KataGo の root スコアで選ぶ（ここでは掛けないので
両変種を回して結論が変種に依存しないかを見る）。

usage:
  PYTHONIOENCODING=utf-8 python frame_dfpn_tiebreak_probe.py [--limit N] [--budget-ms 30000]
      [--ko-p false|true|both] [--out PATH] [--resume] [--route frame] [--class alternative]

ASCII output only（cp932 端末で落ちないように）。
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

from katrain.core.tsumego_frame import tsumego_frame_board  # noqa: E402
from katrain.core.tsumego_problem import (  # noqa: E402
    DEFAULT_MAX_REGION_POINTS,
    extract_problem,
    solver_capture_within_gates,
)
from katrain.core.tsumego_solver import SolverLimits, SolverTimeout  # noqa: E402
from katrain.core.tsumego_solver.board import board_from_stones  # noqa: E402
from katrain.core.tsumego_solver.model import ProblemError  # noqa: E402
from katrain.core.tsumego_solver.native import NativeSolver, native_available  # noqa: E402
from katrain.core.tsumego_solver.reference import ReferenceSolver  # noqa: E402

import framed_extraction_census as fc  # noqa: E402  同じフォルダ（KOMI / MARGIN / entry_to_grid / region_hint）

BOOK_PATH = os.path.expanduser("~/.katrain/tsumego_answers.json")
LETTERS = fc.LETTERS
SETTINGS = fc.SETTINGS


def gtp_of(point):
    if point is None:
        return "pass"
    x, y = point
    return f"{LETTERS[x]}{y + 1}"


def grid_to_stone_sets(grid):
    """認識グリッド（上origin・"B"/"W"/その他=空）→ (黒点集合, 白点集合, size)。"""
    size = len(grid)
    black, white = set(), set()
    for i, row in enumerate(grid):
        for j, c in enumerate(row):
            if c == "B":
                black.add((j, size - 1 - i))
            elif c == "W":
                white.add((j, size - 1 - i))
    return black, white, size


def play_prefix(black, white, size, prefix):
    """記録手順の先頭 len(prefix) 手を打つ（黒番始まり・交互）。取りは Board が処理。"""
    board = board_from_stones((size, size), black, white)
    for idx, g in enumerate(prefix):
        color = "B" if idx % 2 == 0 else "W"
        pt = fc.gtp_to_point(g)
        if pt is None:
            continue  # pass
        if board.try_play(board.index(pt), color) is None:
            raise ValueError(f"illegal prefix move {g} ({color}) at index {idx}")
    b, w = set(), set()
    for p in range(size * size):
        c = board.stones[p]
        if c == "B":
            b.add(board.point(p))
        elif c == "W":
            w.add(board.point(p))
    return b, w


def solve_position(problem, budget_ms):
    # max_alternatives は root_moves の**打ち切り**（既定8）なので、同格タイの大きい局面で
    # 「best に入っているのに載っていない」偽陰性が出る。判定に使うので十分大きくする
    limits = SolverLimits(time_limit_ms=float(budget_ms), max_alternatives=999)
    cls = NativeSolver if native_available() else ReferenceSolver
    solver = cls(problem, limits)
    t0 = time.time()
    try:
        sol = solver.solve()
    except SolverTimeout:
        return None, round(time.time() - t0, 2)
    finally:
        kernel = getattr(solver, "kernel", None)
        if kernel is not None:
            kernel.close()
    return sol, round(time.time() - t0, 2)


def classify_pair(sol, problem, want, chosen):
    """want / chosen が df-pn の同格タイに入るか。返り値は (bucket, 詳細 dict)。

    判定は **`move_values` から作る「クラスキー (class, sub, ko_level) が最良の集合」**（＝第1段階
    だけで決まる集合）。`_classify_after` の floor 刈り WORSE は**厳密に下位**のときだけ返るので
    （reference.py:474,488,495 とも `> floor_key`）、最良クラスの手は必ず `move_values` に載る＝
    この集合は打ち切られない。`root_moves` は plies/material まで含んだより細かいタイだが、
    opt が省かれる/タイムアウトすると全部 plies=0 に潰れて意味が変わるので副指標にする。
    """
    mv = sol.move_values
    ptype = problem.problem_type
    keys = {g: tuple(v.sort_key(ptype)[:3]) for g, v in mv.items()}
    best3 = min(keys.values()) if keys else None
    best_class = {g for g, k in keys.items() if k == best3}
    best_fine = {gtp_of(m) for m in sol.root_moves}
    region_gtp = {gtp_of(pt) for pt in problem.region}

    def info(g):
        v = mv.get(g)
        return {
            "in_best": g in best_class,
            "in_best_fine": g in best_fine,
            "in_region": g in region_gtp,
            "classified": v is not None,  # None = floor 刈りで WORSE（best クラスより確実に下位）
            "key": None if v is None else list(keys[g]),
            "result": None if v is None else v.result.name,
        }

    w, c = info(want), info(chosen)
    if w["in_best"] and not c["in_best"]:
        bucket = "want_only"
    elif c["in_best"] and not w["in_best"]:
        bucket = "chosen_only"
    elif w["in_best"] and c["in_best"]:
        bucket = "both"
    else:
        bucket = "neither"
    return bucket, {
        "want": w,
        "chosen": c,
        "best_key": None if best3 is None else list(best3),
        "best_size": len(best_class),
        "best_fine_size": len(best_fine),
        "n_classified": len(keys),
        "best_moves": sorted(best_class)[:10],
    }


def build_problem(entry, prefix, ko_p, komi=6.5):
    """枠あり盤 + prefix → Problem。

    komi は `fit_margin`/`put_outside` に効くが、**この 115 行では 6.5（リプレイ実値＝
    `~/.katrain/config.json` の game/komi）と 7.0（`framed_extraction_census.py` のハードコード）で
    枠あり盤も region も完全に一致する**（実測 2026-08-16: board 差 0/115・region 差 0/115、
    かつ region はリプレイ記録の region と 115/115 一致）。既定はリプレイ実値の 6.5。
    ko_p も **region の中は変わらない**（枠のコウダテは frame_range の外にしか置かれない）ので
    抽出は壁（region 外の石）経由でしか動かない。
    """
    grid = fc.entry_to_grid(entry)
    size = entry["size"]
    board, region = tsumego_frame_board(grid, komi, True, ko_p=ko_p, margin=fc.MARGIN)
    hint = fc.region_hint(region, size)
    black, white, fsize = grid_to_stone_sets(board)
    black, white = play_prefix(black, white, fsize, prefix)
    problem = extract_problem(
        stones=(black, white),
        board_size=(fsize, fsize),
        to_play="B",
        region_hint=hint,
        max_region_points=DEFAULT_MAX_REGION_POINTS,
    )
    return problem


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", default=os.path.join(here, "answer-book-verify-20260815b.jsonl"))
    ap.add_argument("--replay", default=os.path.join(here, "answer-book-replay-20260815b.jsonl"))
    ap.add_argument("--book", default=BOOK_PATH)
    ap.add_argument("--out", default=os.path.join(here, "frame-dfpn-tiebreak.jsonl"))
    ap.add_argument("--route", default="frame")
    ap.add_argument("--class", dest="klass", default="alternative")
    ap.add_argument("--budget-ms", type=int, default=30000)
    ap.add_argument("--ko-p", default="false", choices=["false", "true", "both"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--max-empties",
        type=int,
        default=20,
        help="region の空点がこれを超える問題は解かずに skipped_big（0 で無効）。30秒予算では"
        "空点16でも解けないので、解ける帯を測るための足切り。落とした数は status に残る",
    )
    ap.add_argument(
        "--control",
        action="store_true",
        help="対照群: リプレイで **一致した**（今日の正解）枠経路の手番を測る。want=chosen=記録手なので "
        "bucket は both（記録手が df-pn の best タイに入る）/ neither（入らない＝タイブレークが壊す側）に潰れる。"
        "処置群だけで測ると『以前失敗していたケースだけの標本』になる（CLAUDE.md）ので必ず対で回す",
    )
    ap.add_argument("--sample", type=int, default=0, help="対照群のサンプル数（決定的・--seed）")
    ap.add_argument("--seed", type=int, default=20260816)
    args = ap.parse_args()

    replay = [json.loads(l) for l in open(args.replay, encoding="utf-8")]
    lines = {(r["key"], r["line_index"]): (r.get("line") or []) for r in replay}
    if args.control:
        rows = []
        for r in replay:
            if r.get("route") != args.route or r.get("verdict") != "correct":
                continue
            for d in r.get("decisions") or []:
                if not d.get("match"):
                    continue
                rows.append(
                    {
                        "key": r["key"],
                        "line_index": r["line_index"],
                        "depth": d["depth"],
                        "want": d["want"],
                        "chosen": d["chosen"],
                        "control": True,
                    }
                )
        if args.sample and args.sample < len(rows):
            import random

            random.Random(args.seed).shuffle(rows)
            rows = rows[: args.sample]
            rows.sort(key=lambda r: (r["key"], r["line_index"], r["depth"]))
    else:
        verify = [json.loads(l) for l in open(args.verify, encoding="utf-8")]
        rows = [r for r in verify if r.get("route") == args.route and r.get("class") == args.klass]
    book = json.load(open(args.book, encoding="utf-8"))["entries"]
    ko_variants = [False] if args.ko_p == "false" else [True] if args.ko_p == "true" else [False, True]

    done = set()
    if args.resume and os.path.exists(args.out):
        for l in open(args.out, encoding="utf-8"):
            try:
                d = json.loads(l)
                done.add((d["key"], d["line_index"], d["ko_p"]))
            except Exception:
                pass
    if args.limit:
        rows = rows[: args.limit]
    print(f"rows {len(rows)}  ko_p {ko_variants}  budget {args.budget_ms}ms  native={native_available()}", flush=True)

    tally = {}
    with open(args.out, "a", encoding="utf-8") as out:
        for n, r in enumerate(rows, 1):
            for ko_p in ko_variants:
                if (r["key"], r["line_index"], ko_p) in done:
                    continue
                t0 = time.time()
                row = {
                    "key": r["key"],
                    "line_index": r["line_index"],
                    "depth": r["depth"],
                    "want": r["want"],
                    "chosen": r["chosen"],
                    "ko_p": ko_p,
                    "control": bool(r.get("control")),
                }
                try:
                    entry = book[r["key"]]
                    line = lines.get((r["key"], r["line_index"]))
                    if line is None:
                        raise KeyError("line not found in replay jsonl")
                    problem = build_problem(entry, line[: r["depth"]], ko_p)
                    gates_ok, gates_detail = solver_capture_within_gates(problem, SETTINGS)
                    n_st = sum(1 for q in problem.region if q in problem.black or q in problem.white)
                    row.update(
                        {
                            "type": problem.problem_type.value,
                            "region": len(problem.region),
                            "empties": len(problem.region) - n_st,
                            "target": len(problem.target),
                            "gates": gates_ok,
                            "gates_detail": gates_detail,
                        }
                    )
                    if args.max_empties and row["empties"] > args.max_empties:
                        # 予算内に終わらないことが実測で分かっている帯は解かずに落とす（silent cap に
                        # しないよう status に残す）。実測 2026-08-16・30秒予算: 空点 16/36/42 は
                        # いずれも timeout、解けたのは 5/8/11
                        row["status"] = "skipped_big"
                        row["sec"] = 0.0
                    else:
                        sol, sec = solve_position(problem, args.budget_ms)
                        row["sec"] = sec
                        if sol is None:
                            row["status"] = "timeout"
                        else:
                            row["status"] = "solved"
                            row["result"] = sol.value.result.name
                            row["nodes"] = sol.nodes
                            bucket, detail = classify_pair(sol, problem, r["want"], r["chosen"])
                            row["bucket"] = bucket
                            row["detail"] = detail
                except ProblemError as e:
                    row["status"] = "extract_failed"
                    row["error"] = str(e)
                    row["sec"] = round(time.time() - t0, 2)
                except Exception as e:
                    row["status"] = "error"
                    row["error"] = f"{type(e).__name__}: {e}"
                    row["trace"] = traceback.format_exc()[-800:]
                    row["sec"] = round(time.time() - t0, 2)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                label = row.get("bucket") or row["status"]
                tally[label] = tally.get(label, 0) + 1
                print(
                    f"[{n}/{len(rows)}] {r['key'][:8]} L{r['line_index']} d{r['depth']} ko={int(ko_p)}"
                    f" want={r['want']} chosen={r['chosen']} reg={row.get('region')}"
                    f" emp={row.get('empties')} -> {label} ({row['sec']}s) {dict(sorted(tally.items()))}",
                    flush=True,
                )
    print("tally:", dict(sorted(tally.items())))


if __name__ == "__main__":
    main()
