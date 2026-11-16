# -*- coding: utf-8 -*-
"""難解「劣勢演出の罠（underdog）」の在庫を、捨て身の罠の反実仮想データの再集計で数える（KataGo 不要・数秒）。

    python docs/superpowers/specs/calibration-data/enigma-underdog/underdog_cf_reslice.py [rows.json] [-v]

入力は `../enigma-overdraft/overdraft-cf-rows-20260918.json`（13路 18 局・手数 10〜84・リード 0〜10 目の
AI 293 手番・1 手番あたり「通常上限 − 1.5 〜 リード + 4.5」の生 loss の帯から最大 12 手を子局面プローブ）。
資格（spec 2026-11-17-enigma-underdog-design.md §4.3）:
    リード > 0 ・ リード − 天井 < 0 ・ 応じられた後のリード la が [−D, 0) ・ find_hp <= 0.25 ・
    検証済み損失 <= 天井 ・ E − 最善手の E >= 0.5 ・ la + E_fooled >= 1.0
標準出力は ASCII のみ（cp932 端末対策）。
"""

import json
import os
import statistics as st
import sys
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
_ARGS = [a for a in sys.argv[1:] if not a.startswith("-")]
PATH = _ARGS[0] if _ARGS else os.path.join(HERE, "..", "enigma-overdraft", "overdraft-cf-rows-20260918.json")
rows = json.load(open(PATH, encoding="utf-8"))
NG = len({r["game"] for r in rows})
MAX_FIND, UPPER, MIN_FOOLED, MIN_DE = 0.25, 0.0, 1.0, 0.5


def fooled(p, adequate=0.3, punish_cap=8.0):
    """(E_fooled, p_fooled)。replies は [hp, 応手側の損失]。"""
    reps = p["replies"]
    tot = sum(r[0] for r in reps)
    bad = [r for r in reps if r[1] > adequate]
    bad_mass = sum(r[0] for r in bad)
    if tot <= 0 or bad_mass <= 0:
        return 0.0, 0.0
    return sum(r[0] * min(r[1], punish_cap) for r in bad) / bad_mass, bad_mass / tot


def quals(r, deficit, ceiling, min_fooled=MIN_FOOLED, min_de=MIN_DE, upper=UPPER):
    best_e = (r.get("best_m") or {}).get("e", 0.0)
    if r["lead"] <= upper or r["lead"] - ceiling >= upper:
        return []
    out = []
    for p in r["picks"]:
        la = p["lead_after"]
        if not (-deficit <= la < upper) or p["find"] > MAX_FIND or p["vloss"] > ceiling:
            continue
        if min_de is not None and p["e"] - best_e < min_de:
            continue
        ef, pf = fooled(p)
        if la + ef >= min_fooled:
            out.append((p, ef, pf))
    return out


def p_hit(n, q, k):
    """n 手のうち q 手が資格ありのとき、無作為に k 手プローブして 1 手以上当たる確率。"""
    if q <= 0 or n <= 0:
        return 0.0
    k = min(k, n)
    return 1.0 - (comb(n - q, k) / comb(n, k) if n - q >= k else 0.0)


def top(qs):
    return max(qs, key=lambda t: (t[0]["lead_after"] + t[0]["e"], t[0]["lead_after"]))


def line(label, sub, deficit, ceiling, **kw):
    hits = [(r, top(quals(r, deficit, ceiling, **kw))) for r in sub if quals(r, deficit, ceiling, **kw)]
    ks = {k: sum(p_hit(len(r["picks"]), len(quals(r, deficit, ceiling, **kw)), k) for r in sub) / NG for k in (4, 6, 8)}
    s = "   %-34s turns=%3d hit12=%2d (%.2f/g, games %2d/%d) k4=%.2f k6=%.2f k8=%.2f" % (
        label,
        len(sub),
        len(hits),
        len(hits) / NG,
        len({r["game"] for r, _ in hits}),
        NG,
        ks[4],
        ks[6],
        ks[8],
    )
    if hits:
        vs = [h[0]["vloss"] for _, h in hits]
        s += (
            " | lead med %.1f vloss med %.1f max %.1f | answered med %+.2f fooled med %+.1f p_fooled med %.0f%% | E med %.2f E-vloss med %+.2f | own_hp<0.01 %d/%d"
            % (
                st.median(r["lead"] for r, _ in hits),
                st.median(vs),
                max(vs),
                st.median(h[0]["lead_after"] for _, h in hits),
                st.median(h[0]["lead_after"] + h[1] for _, h in hits),
                100 * st.median(h[2] for _, h in hits),
                st.median(h[0]["e"] for _, h in hits),
                st.median(h[0]["e"] - h[0]["vloss"] for _, h in hits),
                sum(1 for _, h in hits if h[0]["own_hp"] < 0.01),
                len(hits),
            )
        )
    print(s)
    return hits


print("rows=%d games=%d (13x13, depth 10..84, lead 0..10, up to 12 probes/turn)" % (len(rows), NG))

print("\n-- final rule by move window, one-move price ceiling (= large_lead_max_loss) and deficit D")
for until in (30, 40, 50, 60):
    for ceiling in (8.0, 10.0):
        for deficit in (1.5, 2.0, 3.0):
            line(
                "until<%d ceil=%g D=%.1f" % (until, ceiling, deficit),
                [r for r in rows if r["depth"] < until],
                deficit,
                ceiling,
            )

print("\n-- by lead zone (until<50, ceil=10, D=2): where the stock sits")
for lo, hi in [(0, 1), (1, 3), (3, 5), (5, 10.01)]:
    line("lead (%g,%g]" % (lo, hi), [r for r in rows if r["depth"] < 50 and lo < r["lead"] <= hi], 2.0, 10.0)

print("\n-- qualification variants (until<50, ceil=10, D=2)")
sub50 = [r for r in rows if r["depth"] < 50]
line("final rule", sub50, 2.0, 10.0)
line("no dE gate", sub50, 2.0, 10.0, min_de=None)
line("fooled lead >= 2", sub50, 2.0, 10.0, min_fooled=2.0)
line("band up to +0.5 (not behind)", sub50, 2.0, 10.0, upper=0.5)
line("ceiling 1.5 x large (15)", sub50, 2.0, 15.0)

print("\n-- raw-loss position of the qualifiers relative to the lead (probe band check)")
qs = []
for r in sub50:
    for p, _, _ in quals(r, 2.0, 10.0):
        qs.append((p["raw_loss"] - r["lead"], p["visits"]))
ds = sorted(d for d, _ in qs)
if ds:
    print(
        "   n=%d raw-lead: min %.2f q10 %.2f med %.2f q90 %.2f max %.2f | visits==1: %d/%d"
        % (
            len(ds),
            ds[0],
            ds[len(ds) // 10],
            st.median(ds),
            ds[9 * len(ds) // 10],
            ds[-1],
            sum(1 for _, v in qs if v <= 1),
            len(qs),
        )
    )
    for lo in (-3.5, -2.5, -1.5, -1.0):
        print("   band (lead%+.1f, lead+3.5]: %d/%d qualifiers" % (lo, sum(1 for d in ds if lo < d <= 3.5), len(ds)))

if "-v" in sys.argv:
    print("\n-- picks (until<50, ceil=10, D=2)")
    for r in sorted(sub50, key=lambda r: (r["game"], r["depth"])):
        q = quals(r, 2.0, 10.0)
        if not q:
            continue
        p, ef, pf = top(q)
        print(
            "   %s d=%-3d lead=%5.2f cw=%.2f %-4s vloss=%5.2f answered=%+5.2f (wr %2.0f%%) fooled=%+5.2f (p %2.0f%%) E=%.2f find=%.3f own_hp=%.3f"
            % (
                r["game"][5:],
                r["depth"],
                r["lead"],
                r["cw"],
                p["gtp"],
                p["vloss"],
                p["lead_after"],
                100 * (p["wr_after"] or 0),
                p["lead_after"] + ef,
                100 * pf,
                p["e"],
                p["find"],
                p["own_hp"],
            )
        )
