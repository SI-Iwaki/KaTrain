"""枠あり基板の静的センサス（KataGo 不要・数秒）— 抽出器拡張プロジェクト（spec
`2026-08-15-tsumego-extraction-expansion-design.md`）の封筒見積りと A/B 対象キーの列挙。

回答帳の全 entry について `_do_tsumego_capture_apply` の分岐を KataGo 抜きでなぞる:

  1. 生盤で `extract_problem`（hint なし）→ ゲート → 通れば route=solver（現行・本件の対象外）
  2. それ以外は枠あり盤（`tsumego_frame_board` を本番と同じ引数で。ko_p は抽出に無関係なので固定）
     に **hint=枠リージョン** を渡して `extract_problem` → 閉包モードで閉じた問題だけ →
     ゲート → 役割整合 → 通れば route=solver_frame 候補（枠の採否判定 KataGo は掛けないので上界）
  3. 残りは route=frame（現行のまま）

出力 JSONL（1 entry 1 行）: key / size / route / framed 抽出の型・target・region・空点 / gates /
role_guess / role_consistent / 記録手順の黒手が抽出 region 内か（all_lines_in・first_in・
n_lines・n_black_moves・n_outside・n_on_fill）。手順の外れ方は「fill 点に乗る」を別に数える
（fill は Problem 上だけの石で GUI では空点＝人間もソルバも打てないので、そこが正解手なら
ソルバは打てない）。

    python framed_extraction_census.py [--out framed-extraction-census.jsonl] [--book PATH]
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.tsumego_frame import tsumego_frame_board, guess_black_to_attack_for_board  # noqa: E402
from katrain.core.tsumego_problem import (  # noqa: E402
    DEFAULT_MAX_REGION_POINTS,
    extract_problem,
    solver_capture_within_gates,
)
from katrain.core.tsumego_solver.model import ProblemError, ProblemType  # noqa: E402

# ユーザーローカル設定の実値（`~/.katrain/config.json` tsumego_capture）。KataGo は使わない
KOMI = 7.0
MARGIN = 4
SETTINGS = {"solver_capture_max_region": 23, "solver_capture_max_empties": 12}
LETTERS = "ABCDEFGHJKLMNOPQRST"


def gtp_to_point(g):
    if g is None or g.lower() == "pass":
        return None
    return LETTERS.index(g[0]), int(g[1:]) - 1


def entry_to_grid(entry):
    size = entry["size"]
    grid = [["." for _ in range(size)] for _ in range(size)]
    for s in entry["canonical_black"]:
        x, y = gtp_to_point(s)
        grid[size - 1 - y][x] = "B"
    for s in entry["canonical_white"]:
        x, y = gtp_to_point(s)
        grid[size - 1 - y][x] = "W"
    return grid


def region_hint(region, size):
    """`tsumego_frame_board` の region（上origin）→ region_of_interest [xmin,xmax,ymin,ymax]（下origin）。"""
    if region is None:
        return None
    (imin, imax), (jmin, jmax) = region
    return [jmin, jmax, size - 1 - imax, size - 1 - imin]


def role_consistent(black_to_attack, problem_type):
    """枠の役割仮定（壁の色）と抽出器の型が食い違っていないか。SEMEAI は両様なので不整合にしない。"""
    if problem_type == ProblemType.ATTACK:
        return bool(black_to_attack)
    if problem_type == ProblemType.DEFEND:
        return not black_to_attack
    return True


def line_stats(entry, problem):
    """記録手順の黒手（偶数 index）が抽出 region / fill に対してどう位置するか。"""
    n_lines = 0
    n_black = 0
    n_outside = 0
    n_on_fill = 0
    first_in = True
    all_in = True
    fills = set(problem.fill_black) | set(problem.fill_white)
    for line in entry.get("lines") or []:
        n_lines += 1
        for idx, g in enumerate(line):
            if idx % 2 != 0:
                continue
            p = gtp_to_point(g)
            if p is None:
                continue
            n_black += 1
            if p not in problem.region:
                n_outside += 1
                all_in = False
                if idx == 0:
                    first_in = False
                if p in fills:
                    n_on_fill += 1
    return {
        "n_lines": n_lines,
        "n_black_moves": n_black,
        "n_outside": n_outside,
        "n_on_fill": n_on_fill,
        "first_in": first_in,
        "all_lines_in": all_in,
    }


def census_entry(key, entry):
    grid = entry_to_grid(entry)
    size = entry["size"]
    row = {"key": key, "size": size, "n_lines": len(entry.get("lines") or [])}
    # 1. 生盤（現行のソルバ経路）
    try:
        p0 = extract_problem(grid=grid, to_play="B", max_region_points=DEFAULT_MAX_REGION_POINTS)
        ok, detail = solver_capture_within_gates(p0, SETTINGS)
        row["raw"] = {"ok": True, "gates": ok, "detail": detail}
        if ok:
            row["route"] = "solver"
            return row
    except ProblemError as e:
        row["raw"] = {"ok": False, "error": str(e)}
    except Exception as e:  # pragma: no cover
        row["raw"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    # 2. 枠あり盤 + hint
    try:
        board, region = tsumego_frame_board(grid, KOMI, True, ko_p=False, margin=MARGIN)
    except Exception as e:
        row["framed"] = {"ok": False, "error": f"frame: {e}"}
        row["route"] = "frame"
        return row
    hint = region_hint(region, size)
    role_guess = guess_black_to_attack_for_board(grid, KOMI, MARGIN)
    row["role_guess"] = role_guess
    row["hint"] = hint
    try:
        p = extract_problem(grid=board, to_play="B", region_hint=hint, max_region_points=DEFAULT_MAX_REGION_POINTS)
    except ProblemError as e:
        row["framed"] = {"ok": False, "error": str(e)}
        row["route"] = "frame"
        return row
    n_st = sum(1 for q in p.region if q in p.black or q in p.white)
    n_emp = len(p.region) - n_st
    rect_area = None
    if hint is not None:
        rect_area = (hint[1] - hint[0] + 1) * (hint[3] - hint[2] + 1)
    open_rect = rect_area is not None and len(p.region) == rect_area
    gates_ok, gates_detail = solver_capture_within_gates(p, SETTINGS)
    consistent = role_consistent(role_guess, p.problem_type)
    row["framed"] = {
        "ok": True,
        "mode": "open_rect" if open_rect else "closure",
        "type": p.problem_type.value,
        "target": len(p.target),
        "region": len(p.region),
        "empties": n_emp,
        "fill": len(p.fill_black) + len(p.fill_white),
        "gates": gates_ok,
        "gates_detail": gates_detail,
        "role_consistent": consistent,
        **line_stats(entry, p),
    }
    if not open_rect and gates_ok and consistent:
        row["route"] = "solver_frame"
    else:
        row["route"] = "frame"
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=os.path.expanduser("~/.katrain/tsumego_answers.json"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "framed-extraction-census.jsonl"))
    args = ap.parse_args()
    book = json.load(open(args.book, encoding="utf-8"))["entries"]
    t0 = time.time()
    rows = [census_entry(k, e) for k, e in sorted(book.items())]
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    routes = Counter(r["route"] for r in rows)
    print(f"entries {len(rows)}  elapsed {time.time() - t0:.1f}s  -> {args.out}")
    print("route:", dict(routes))
    framed = [r for r in rows if r.get("framed", {}).get("ok")]
    print(f"framed extract ok {len(framed)} / attempted {sum(1 for r in rows if 'framed' in r)}")
    modes = Counter(r["framed"]["mode"] for r in framed)
    print("framed mode:", dict(modes))
    closure = [r for r in framed if r["framed"]["mode"] == "closure"]
    emp = Counter()
    for r in closure:
        e = r["framed"]["empties"]
        emp["<=9" if e <= 9 else "10-12" if e <= 12 else "13+"] += 1
    print("closure empties:", dict(emp))
    print("closure gates ok:", sum(1 for r in closure if r["framed"]["gates"]))
    print("closure gates ok & role consistent:", sum(1 for r in closure if r["framed"]["gates"] and r["framed"]["role_consistent"]))
    print("closure role inconsistent:", sum(1 for r in closure if not r["framed"]["role_consistent"]))
    sf = [r for r in rows if r["route"] == "solver_frame"]
    print(f"solver_frame candidates {len(sf)}: all_lines_in {sum(1 for r in sf if r['framed']['all_lines_in'])} / "
          f"first_in {sum(1 for r in sf if r['framed']['first_in'])} / lines {sum(r['n_lines'] for r in sf)}")
    print("solver_frame types:", dict(Counter(r["framed"]["type"] for r in sf)))
    print("solver_frame with any black move on fill:", sum(1 for r in sf if r["framed"]["n_on_fill"]))
    # 空点<=12 だが region>23 で落ちる帯（Phase 2 の候補）
    band = [r for r in closure if r["framed"]["empties"] <= 12 and not r["framed"]["gates"] and r["framed"]["role_consistent"]]
    print(f"phase2 band (closure, empties<=12, region>23, role ok): {len(band)}; region max {max((r['framed']['region'] for r in band), default=0)}")
    print("solver_frame keys:", " ".join(r["key"][:10] for r in sf))


if __name__ == "__main__":
    main()
