"""枠あり基板の Problem 盤（fill 込み）で、region に隣接する region 外の連（壁）が region 外の呼吸点を
1つも持たない盤を数える（spec 2026-08-15-tsumego-extraction-expansion-design.md §0.2）。ko_p 両変種。KataGo 不要。
実測 2026-08-15: 49問中 ko_p=False 1 / ko_p=True 4（現行ソルバ経路 134問は 0）。
  PYTHONIOENCODING=utf-8 python framed_wall_liberty_probe.py"""
import json, os, sys
os.environ["KIVY_NO_ARGS"] = "1"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import framed_extraction_census as fc
from katrain.core.tsumego_frame import tsumego_frame_board
from katrain.core.tsumego_problem import extract_problem
from katrain.core.tsumego_solver.board import board_from_stones
from katrain.core.tsumego_solver.model import EMPTY

book = json.load(open(os.path.expanduser("~/.katrain/tsumego_answers.json"), encoding="utf-8"))["entries"]
rows = [json.loads(l) for l in open(os.path.join(ROOT, "docs/superpowers/specs/calibration-data/tsumego/framed-extraction-census.jsonl"), encoding="utf-8")]
targets = [r["key"] for r in rows if r["route"] == "solver_frame"]
for ko_p in (False, True):
    bad = []
    for key in targets:
        entry = book[key]
        grid = fc.entry_to_grid(entry)
        size = entry["size"]
        board, region = tsumego_frame_board(grid, fc.KOMI, True, ko_p=ko_p, margin=fc.MARGIN)
        hint = fc.region_hint(region, size)
        p = extract_problem(grid=board, to_play="B", region_hint=hint)
        b = board_from_stones(p.size, p.black, p.white)
        reg = {b.index(pt) for pt in p.region}
        for stones, libs in b.all_chains():
            if any(s in reg for s in stones):
                continue  # region 内の連
            adj = any(n in reg for s in stones for n in b.neighbors[s])
            if not adj:
                continue
            outside_libs = [l for l in libs if l not in reg]
            if not outside_libs:
                bad.append((key[:10], len(stones), len(libs), b.stones[stones[0]]))
                break
    print(f"ko_p={ko_p}: wall chains with 0 outside libs: {len(bad)}/{len(targets)} ->", bad)
