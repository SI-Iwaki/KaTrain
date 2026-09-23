"""From the enigma13plus logs: would Mimic's qualification have accepted each Enigma deviation?

Also: endgame (sticky) turns and how Enigma behaves there. Throwaway spike script.
"""

import json
import os
import re
import sys

LOGDIR = os.path.expanduser("~/.katrain/logs")
HERE = os.path.dirname(os.path.abspath(__file__))
summ = json.load(open(os.path.join(HERE, "recon", "summary.json"), encoding="utf-8"))

RE_GEN = re.compile(r"^Generating move using (\w+)")
RE_DONE = re.compile(r"^Move generation complete: ([A-T][0-9]+|pass) -- (.*)$")
RE_SCORE = re.compile(
    r"\] Score ([A-T][0-9]+|pass): vloss=(-?[0-9.]+) \(raw (-?[0-9.]+)\) wr=([0-9.]+)% E=(-?[0-9.]+) .*?own_hp=([0-9.]+)"
)
RE_DEV = re.compile(r"\] (Deviate|Gamble): played ([A-T][0-9]+|pass) \((.*?)\) instead of ([A-T][0-9]+|pass)")

MIN_HP, NAT_RATIO, TRAP_DE, TRAP_HP, DOM = 0.05, 0.2, 0.5, 0.005, 0.8

tot = dict(
    dev=0,
    nat=0,
    trap=0,
    nat_or_trap=0,
    dom=0,
    price_le0=0,
    price_le03=0,
    price_le1=0,
    price_le2=0,
    endgame_turns=0,
    endgame_dev=0,
    mid_turns=0,
    mid_dev=0,
    dev_hp=[],
)
for s in summ:
    if not s["strategy"].startswith("Enigma"):
        continue
    lines = open(os.path.join(LOGDIR, s["game"] + ".log"), encoding="utf-8", errors="replace").read().splitlines()
    cur = None
    turns = []
    for ln in lines:
        if RE_GEN.match(ln):
            cur = []
            continue
        if cur is None or "QUERY" in ln:
            continue
        cur.append(ln)
        if RE_DONE.match(ln):
            turns.append(cur)
            cur = None
    g = dict(dev=0, nat=0, trap=0, nat_or_trap=0, dom=0, endgame_turns=0, endgame_dev=0)
    for b in turns:
        txt = "\n".join(b)
        endgame = "Endgame budget" in txt
        if endgame:
            tot["endgame_turns"] += 1
            g["endgame_turns"] += 1
        elif "Score " in txt or "Pool:" in txt:
            tot["mid_turns"] += 1
        scores = {}
        for l in b:
            m = RE_SCORE.search(l)
            if m:
                scores[m.group(1)] = dict(vloss=float(m.group(2)), E=float(m.group(5)), hp=float(m.group(6)))
        md = RE_DEV.search(txt)
        if not md:
            continue
        chosen, best = md.group(2), md.group(4)
        if chosen not in scores or best not in scores:
            continue
        c, bst = scores[chosen], scores[best]
        dE = c["E"] - bst["E"]
        price = max(0.0, c["vloss"]) - dE
        floor = max(MIN_HP, NAT_RATIO * max(v["hp"] for v in scores.values()))
        nat = c["hp"] >= floor
        trap = dE >= TRAP_DE and c["hp"] >= TRAP_HP
        dom = bst["hp"] >= DOM
        tot["dev"] += 1
        g["dev"] += 1
        tot["nat"] += nat
        tot["trap"] += trap
        tot["nat_or_trap"] += nat or trap
        tot["dom"] += dom
        tot["price_le0"] += price <= 0
        tot["price_le03"] += price <= 0.3
        tot["price_le1"] += price <= 1.0
        tot["price_le2"] += price <= 2.0
        tot["dev_hp"].append(c["hp"])
        g["nat"] += nat
        g["trap"] += trap
        g["nat_or_trap"] += nat or trap
        g["dom"] += dom
        if endgame:
            tot["endgame_dev"] += 1
            g["endgame_dev"] += 1
        else:
            tot["mid_dev"] += 1
    print(s["game"], g)

n = tot["dev"]
print("\nEnigma13Plus deviations with Score lines:", n)
print("  natural by Mimic rule   : %d (%.0f%%)" % (tot["nat"], 100 * tot["nat"] / n))
print("  trap by Mimic rule      : %d (%.0f%%)" % (tot["trap"], 100 * tot["trap"] / n))
print("  natural or trap         : %d (%.0f%%)" % (tot["nat_or_trap"], 100 * tot["nat_or_trap"] / n))
print("  best hp >= 0.8 (dominant guard would block): %d (%.0f%%)" % (tot["dom"], 100 * tot["dom"] / n))
print(
    "  price <= 0 / 0.3 / 1.0 / 2.0: %d / %d / %d / %d"
    % (tot["price_le0"], tot["price_le03"], tot["price_le1"], tot["price_le2"])
)
hp = sorted(tot["dev_hp"])
print(
    "  chosen hp quartiles: %.3f / %.3f / %.3f ; <0.01: %d ; <0.05: %d"
    % (
        hp[len(hp) // 4],
        hp[len(hp) // 2],
        hp[3 * len(hp) // 4],
        sum(1 for x in hp if x < 0.01),
        sum(1 for x in hp if x < 0.05),
    )
)
print(
    "  endgame(sticky) turns: %d, deviations there: %d ; mid turns %d dev %d"
    % (tot["endgame_turns"], tot["endgame_dev"], tot["mid_turns"], tot["mid_dev"])
)
