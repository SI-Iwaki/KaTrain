"""E 尺度比較の集計: ab_enigma_e.py の JSON（腕ごと）を突き合わせる。usage: python ab_e_summarize.py out/e_A_g0823.json out/e_B_g0823.json [out/e_B2_g0823.json]"""

import json
import sys
from statistics import mean, pstdev


def load(p):
    d = json.load(open(p, encoding="utf-8"))
    return {r["move_num"]: r for r in d["results"]}


arms = {}
for p in sys.argv[1:]:
    name = p.split("e_")[-1].split("_")[0]
    arms[name] = load(p)

print("=== 腕ごと ===")
for name, R in arms.items():
    dev = [r for r in R.values() if r["deviated"]]
    e_ch = [r["cands"][r["chosen"]]["E"] for r in dev if r["chosen"] in r["cands"]]
    v_ch = [r["cands"][r["chosen"]]["vloss"] for r in dev if r["chosen"] in r["cands"]]
    e_best = [r["cands"][r["best"]]["E"] for r in R.values() if r["best"] in r["cands"]]
    n_c = [len(r["cands"]) for r in R.values()]
    secs = [r["secs"] for r in R.values()]
    print(
        f"{name}: 手番 {len(R)} 外し {len(dev)} | 外した手の E 平均 {mean(e_ch) if e_ch else float('nan'):.2f} vloss 平均 {mean(v_ch) if v_ch else float('nan'):.2f} "
        f"| 最善手の E 平均 {mean(e_best) if e_best else float('nan'):.2f} | 候補数/手 {mean(n_c):.1f} | 着手決定 {mean(secs):.2f}s"
    )

if "A" in arms and "B" in arms:
    A, B = arms["A"], arms["B"]
    common = sorted(set(A) & set(B))
    print("\n=== A vs B（同じ局面） ===")
    print(f"最善手（KataGo）一致: {sum(1 for k in common if A[k]['best'] == B[k]['best'])}/{len(common)}")
    print(f"選択手一致: {sum(1 for k in common if A[k]['chosen'] == B[k]['chosen'])}/{len(common)}")
    print(f"外した手番: A {sum(A[k]['deviated'] for k in common)} / B {sum(B[k]['deviated'] for k in common)} / 両方 {sum(A[k]['deviated'] and B[k]['deviated'] for k in common)}")
    # 両腕がプローブした同じ候補の E / vloss を比べる（尺度のずれ）
    pairs_e, pairs_v = [], []
    for k in common:
        for g in set(A[k]["cands"]) & set(B[k]["cands"]):
            pairs_e.append((A[k]["cands"][g]["E"], B[k]["cands"][g]["E"]))
            pairs_v.append((A[k]["cands"][g]["vloss"], B[k]["cands"][g]["vloss"]))
    if pairs_e:
        ea, eb = zip(*pairs_e)
        va, vb = zip(*pairs_v)
        de = [b - a for a, b in pairs_e]
        dv = [b - a for a, b in pairs_v]

        def corr(x, y):
            mx, my = mean(x), mean(y)
            sx, sy = pstdev(x), pstdev(y)
            return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) * sx * sy) if sx and sy else float("nan")

        print(f"共通候補 {len(pairs_e)} 手: E 平均 A {mean(ea):.2f} / B {mean(eb):.2f}（B−A 平均 {mean(de):+.2f}・相関 {corr(ea, eb):.2f}）")
        print(f"                 vloss 平均 A {mean(va):.2f} / B {mean(vb):.2f}（B−A 平均 {mean(dv):+.2f}・相関 {corr(va, vb):.2f}）")
        big = sorted(((abs(b - a), k, g, a, b) for k in common for g in set(A[k]['cands']) & set(B[k]['cands']) for a, b in [(A[k]['cands'][g]['E'], B[k]['cands'][g]['E'])]), reverse=True)[:8]
        print("  E の食い違いが大きい候補: " + ", ".join(f"#{k} {g} A{a:.2f}/B{b:.2f}" for _, k, g, a, b in big))
    # A が外した手を B はどう見たか（逆も）
    for x, y, lx, ly in ((A, B, "A", "B"), (B, A, "B", "A")):
        rows = []
        for k in common:
            r = x[k]
            if r["deviated"] and r["chosen"] in y[k]["cands"]:
                rows.append((r["cands"][r["chosen"]]["E"], y[k]["cands"][r["chosen"]]["E"], r["cands"][r["chosen"]]["vloss"], y[k]["cands"][r["chosen"]]["vloss"]))
        if rows:
            print(f"{lx} の外し {len(rows)} 手を {ly} の尺度で: E {mean(r[0] for r in rows):.2f}→{mean(r[1] for r in rows):.2f}, vloss {mean(r[2] for r in rows):.2f}→{mean(r[3] for r in rows):.2f}")
        miss = sum(1 for k in common if x[k]["deviated"] and x[k]["chosen"] not in y[k]["cands"])
        print(f"   （{ly} がプローブしていない {lx} の外し: {miss} 手）")
