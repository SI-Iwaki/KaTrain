# -*- coding: utf-8 -*-
"""overdraft_cf.py の結果を集計する（KataGo 不要・数秒）。標準出力は ASCII のみ。

    python docs/superpowers/specs/calibration-data/enigma-overdraft/overdraft_cf_report.py [rows.json]

資格（spec 2026-09-18-enigma-overdraft-design.md §4.3）:
    着手後リード la が [-D, upper) ・ find_hp <= 0.25 ・ la + E_fooled >= W
    E_fooled = 「十分でない応手（損失 > 0.3）」の humanSL 9d 重みつき平均損失（1 応手 8 目 cap）
"""

import json
import os
import statistics as st
import sys
from collections import Counter, defaultdict
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
_ARGS = [a for a in sys.argv[1:] if not a.startswith("-")]
PATH = _ARGS[0] if _ARGS else os.path.join(HERE, "overdraft-cf-rows-20260918.json")
rows = json.load(open(PATH, encoding="utf-8"))
games = sorted({r["game"] for r in rows})
NG = len(games)
TARGET = 1.0  # 計測時の target_score
MAX_FIND = 0.25


def fooled(p, adequate=0.3, punish_cap=8.0):
    """(E_fooled, p_fooled)。replies は [hp, 応手側の損失]。"""
    reps = p["replies"]
    tot = sum(r[0] for r in reps)
    if tot <= 0:
        return 0.0, 0.0
    bad = [r for r in reps if r[1] > adequate]
    bad_mass = sum(r[0] for r in bad)
    if bad_mass <= 0:
        return 0.0, 0.0
    return sum(r[0] * min(r[1], punish_cap) for r in bad) / bad_mass, bad_mass / tot


def qualifiers(r, deficit, upper, min_fooled):
    out = []
    for p in r["picks"]:
        la = p["lead_after"]
        if p["vloss"] <= r["cap_normal"] or not (-deficit <= la < upper) or p["find"] > MAX_FIND:
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


spend = [r for r in rows if r["cw"] < 1.0]
print(
    "turns=%d (%.1f/game) games=%d | spend-mode turns=%d (%.1f/game)"
    % (len(rows), len(rows) / NG, NG, len(spend), len(spend) / NG)
)

print("\n-- literal traps (answered in [-3,-1), find<=0.25, fooled>=+2) by lead band, all turns, 12 probes")
for lo, hi in [(0, 1), (1, 2), (2, 3.5), (3.5, 5), (5, 7), (7, 10.01)]:
    sub = [r for r in rows if lo < r["lead"] <= hi]
    hits = sum(1 for r in sub if any(p["lead_after"] < -1.0 for p, _, _ in qualifiers(r, 3.0, -1.0, 2.0)))
    print("   lead (%g,%g]: turns=%3d hits=%d" % (lo, hi, len(sub), hits))

print("\n-- frequency in spend-mode turns: expected firings/game and share of games with >=1, by probe count k")
for name, upper in [
    ("mild included [-2.5, target)", TARGET),
    ("negative only [-2.5, 0)", 0.0),
    ("behind >=1   [-2.5, -1)", -1.0),
]:
    for w in (2.0, 3.0):
        cells = []
        for k in (4, 6, 8, 12):
            per_game = defaultdict(list)
            for r in spend:
                per_game[r["game"]].append(p_hit(len(r["picks"]), len(qualifiers(r, 2.5, upper, w)), k))
            exp = sum(sum(v) for v in per_game.values()) / NG
            any_share = 0.0
            for g in games:
                miss = 1.0
                for x in per_game.get(g, []):
                    miss *= 1.0 - x
                any_share += 1.0 - miss
            cells.append("k=%-2d %.2f/g %3.0f%%" % (k, exp, 100 * any_share / NG))
        print("   %-30s W=%.0f | %s" % (name, w, " | ".join(cells)))

print("\n-- pick characteristics (pick = max lead_after + E among qualifiers, 12 probes)")
for name, upper, w in [("mild included", TARGET, 3.0), ("mild included", TARGET, 2.0), ("negative only", 0.0, 2.0)]:
    picks = []
    for r in spend:
        qs = qualifiers(r, 2.5, upper, w)
        if qs:
            picks.append((r, max(qs, key=lambda t: (t[0]["lead_after"] + t[0]["e"], t[0]["lead_after"])), len(qs)))
    if not picks:
        continue
    la = [p["lead_after"] for _, (p, _, _), _ in picks]
    fo = [p["lead_after"] + ef for _, (p, ef, _), _ in picks]
    vs = sorted(p["vloss"] for _, (p, _, _), _ in picks)
    wr = [p["wr_after"] for _, (p, _, _), _ in picks if p["wr_after"] is not None]
    ev = [p["e"] - p["vloss"] for _, (p, _, _), _ in picks]
    print(
        "   %-14s W=%.0f: hit turns=%d (%.2f/game) qualifiers/turn=%s"
        % (name, w, len(picks), len(picks) / NG, sorted(Counter(n for _, _, n in picks).items()))
    )
    print(
        "      lead med %.1f | vloss med %.1f (q25 %.1f q75 %.1f) | answered med %+.2f (<0: %.0f%%) wr med %.0f%% min %.0f%% | "
        "fooled med %+.1f | p_fooled(model) med %.0f%% | E-vloss med %+.2f"
        % (
            st.median(r["lead"] for r, _, _ in picks),
            st.median(vs),
            vs[len(vs) // 4],
            vs[3 * len(vs) // 4],
            st.median(la),
            100 * sum(a < 0 for a in la) / len(la),
            100 * st.median(wr),
            100 * min(wr),
            st.median(fo),
            100 * st.median(pf for _, (_, _, pf), _ in picks),
            st.median(ev),
        )
    )

if "-v" in sys.argv:
    print("\n-- negative-only picks (W=2)")
    for r in spend:
        qs = qualifiers(r, 2.5, 0.0, 2.0)
        if not qs:
            continue
        p, ef, pf = max(qs, key=lambda t: (t[0]["lead_after"] + t[0]["e"], t[0]["lead_after"]))
        print(
            "   %s d=%-3d lead=%5.2f %-4s vloss=%5.2f answered=%+5.2f (wr %2.0f%%) fooled=%+5.2f (p %2.0f%%) find=%.3f raw=%.1f/v%d"
            % (
                r["game"][5:20],
                r["depth"],
                r["lead"],
                p["gtp"],
                p["vloss"],
                p["lead_after"],
                100 * (p["wr_after"] or 0),
                p["lead_after"] + ef,
                100 * pf,
                p["find"],
                p["raw_loss"],
                p["visits"],
            )
        )
