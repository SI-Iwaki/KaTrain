"""A/B 結果の集計: E2E の PASS 表（腕ごと）と難解バッチ JSON（腕 × 局 × run）の比較。

usage: python ab_summarize.py <out_dir>
"""

import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

OUT = sys.argv[1]


def e2e_table(arm):
    path = os.path.join(OUT, f"e2e_{arm}.txt")
    if not os.path.exists(path):
        return None
    rows = {}
    summary = ""
    in_summary = False
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("=== E2E suite summary"):
            in_summary = True
            continue
        if in_summary:
            m = re.match(r"^(PASS|PART|FAIL|DIFF|ERROR)\s+(\S+)\s+(\d+)/(\d+)", ln)
            if m:
                rows[m.group(2)] = (m.group(1), int(m.group(3)), int(m.group(4)))
            elif "PASS" in ln and "/" in ln:
                summary = ln.strip()
    return rows, summary


print("=== 詰碁 E2E ===")
tables = {arm: e2e_table(arm) for arm in ("A", "B", "B2")}
arms = [a for a, t in tables.items() if t]
if arms:
    keys = sorted(
        {k for a in arms for k in tables[a][0]},
        key=lambda s: (s.split("@")[0], int(s.split("@")[1]) if "@" in s else 0),
    )
    print("case      " + "".join(f"{a:>14}" for a in arms))
    for k in keys:
        cells = []
        for a in arms:
            v = tables[a][0].get(k)
            cells.append(f"{v[0]} {v[1]}/{v[2]}" if v else "-")
        flag = (
            "  <-- differs"
            if len({c.split(" ")[0] for c in cells if c != "-"}) > 1 or len({c for c in cells if c != "-"}) > 1
            else ""
        )
        print(f"{k:<10}" + "".join(f"{c:>14}" for c in cells) + flag)
    for a in arms:
        print(f"{a}: {tables[a][1]}")

print("\n=== 難解13路バッチ ===")
runs = defaultdict(list)  # (arm, game) -> [json]
for path in sorted(glob.glob(os.path.join(OUT, "enigma_*_r*.json"))):
    m = re.match(r"enigma_(\w+?)_(g\d+)_r(\d+)\.json", os.path.basename(path))
    if not m:
        continue
    try:
        txt = open(path, encoding="utf-8").read()
        data = json.loads(txt[txt.index("{") :])
    except Exception as e:
        print(f"  {os.path.basename(path)}: unreadable ({e})")
        continue
    runs[(m.group(1), m.group(2))].append(data)

games = sorted({g for _, g in runs})
for g in games:
    print(f"\n--- {g} ---")
    per_arm_sel = {}
    for arm in ("A", "B", "B2"):
        ds = runs.get((arm, g))
        if not ds:
            continue
        ov = [d["stats"]["overall"] for d in ds]
        n = len(ov)
        mean = lambda k: sum(o[k] for o in ov) / n
        print(
            f"{arm}: runs={n} moves={ov[0].get('total', len(ds[0]['moves']))} "
            f"Top1={mean('ai_top_move'):.3f} Top5={mean('ai_top5_move'):.3f} "
            f"mean_ptloss={mean('mean_ptloss'):.3f} accuracy={mean('accuracy'):.2f}"
        )
        # 手ごとの最頻選択（run 間）
        sel = defaultdict(Counter)
        for d in ds:
            for mv in d["moves"]:
                sel[mv["move_num"]][mv["selected"]] += 1
        per_arm_sel[arm] = {k: v.most_common(1)[0][0] for k, v in sel.items()}
        stable = sum(1 for v in sel.values() if len(v) == 1)
        print(f"   run 間で選択が安定した手番: {stable}/{len(sel)}")
    if "A" in per_arm_sel and "B" in per_arm_sel:
        common = sorted(set(per_arm_sel["A"]) & set(per_arm_sel["B"]))
        agree = sum(1 for k in common if per_arm_sel["A"][k] == per_arm_sel["B"][k])
        print(f"   A vs B 最頻選択の一致: {agree}/{len(common)}")
        diffs = [
            (k, per_arm_sel["A"][k], per_arm_sel["B"][k]) for k in common if per_arm_sel["A"][k] != per_arm_sel["B"][k]
        ]
        if diffs:
            print("   不一致: " + ", ".join(f"#{k}:{a}/{b}" for k, a, b in diffs))
    if "A" in per_arm_sel and "B2" in per_arm_sel:
        common = sorted(set(per_arm_sel["A"]) & set(per_arm_sel["B2"]))
        agree = sum(1 for k in common if per_arm_sel["A"][k] == per_arm_sel["B2"][k])
        print(f"   A vs B2 最頻選択の一致: {agree}/{len(common)}")

print("\n=== 所要時間（run.log の STEP done） ===")
logp = os.path.join(os.path.dirname(OUT), "run.log")
if os.path.exists(logp):
    for ln in open(logp, encoding="utf-8"):
        m = re.search(r"STEP (\S+) done rc=(-?\d+) in (\d+)s", ln)
        if m:
            print(f"  {m.group(1):<28} rc={m.group(2):>3} {int(m.group(3)) / 60:6.1f} min")
