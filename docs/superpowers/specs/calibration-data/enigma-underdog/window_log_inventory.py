# -*- coding: utf-8 -*-
"""Log-only inventory: Enigma13Plus real games, early window trajectory and trap stock.

Usage: python window_inventory.py [--until 50] [--tag Enigma13PlusStrategy] [--since 20261009]
ASCII output only.
"""

import argparse
import glob
import os
import re
import statistics as st

ap = argparse.ArgumentParser()
ap.add_argument("--until", type=int, default=50)
ap.add_argument("--tag", default="Enigma13PlusStrategy")
ap.add_argument("--since", default="20261009")
ap.add_argument("--dump", action="store_true")
args = ap.parse_args()

LOGS = os.path.expanduser("~/.katrain/logs")
TAG = "[" + args.tag + "] "
RE_SCORE = re.compile(
    r"Score (\S+): vloss=(-?[\d.]+) \(raw (-?[\d.]+)\) wr=([\d.]+)% E=(-?[\d.]+) cov=([\d.]+) "
    r"find_hp=([\d.]+) own_hp=([\d.]+).*net=(-?[\d.]+)"
)
RE_SPEND = re.compile(r"Spend: lead=(-?[\d.]+) budget=(-?[\d.]+) cap=(-?[\d.]+) cost_weight=([\d.]+)")
RE_DEPTH = re.compile(r"(?:Gamble: window depth|Endgame check: depth|Opening handoff: move)=(\d+)")
RE_DEV = re.compile(
    r"Deviate: played (\S+) \(net=(-?[\d.]+), vloss=(-?[\d.]+), E=(-?[\d.]+), find_hp=([\d.]+).*wr=([\d.]+)%\) instead of (\S+)"
)
RE_GAM = re.compile(
    r"Gamble: played (\S+) \(dE=\+?(-?[\d.]+), vloss=(-?[\d.]+), wr=([\d.]+)%, find_hp=([\d.]+).*instead of (\S+)"
)
RE_POOL = re.compile(r"Pool: cap=([\d.]+) min_wr=(\d+)% admissible=(\d+)")


def parse(path):
    turns = []
    cur = None
    settings = None
    with open(path, "rb") as fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace").rstrip()
            if settings is None and line.startswith("Initializing " + args.tag):
                settings = line
            if not line.startswith(TAG):
                continue
            body = line[len(TAG) :]
            if body.startswith("Waiting for regular analysis"):
                cur = {
                    "scores": [],
                    "spend": None,
                    "depth": None,
                    "played": None,
                    "kind": None,
                    "best": None,
                    "pool": None,
                    "yose": False,
                }
                turns.append(cur)
                continue
            if cur is None:
                continue
            m = RE_DEPTH.search(body)
            if m and cur["depth"] is None:
                cur["depth"] = int(m.group(1))
            if "-> yose" in body or body.startswith("Endgame budget"):
                cur["yose"] = True
            m = RE_SPEND.search(body)
            if m:
                cur["spend"] = tuple(float(x) for x in m.groups())
            m = RE_POOL.search(body)
            if m:
                cur["pool"] = (float(m.group(1)), int(m.group(3)))
            m = RE_SCORE.search(body)
            if m:
                g = m.groups()
                cur["scores"].append(
                    {
                        "gtp": g[0],
                        "vloss": float(g[1]),
                        "wr": float(g[3]) / 100,
                        "e": float(g[4]),
                        "find": float(g[6]),
                        "own": float(g[7]),
                        "net": float(g[8]),
                    }
                )
            m = RE_DEV.search(body)
            if m:
                cur["played"], cur["kind"], cur["best"] = m.group(1), "deviate", m.group(7)
            m = RE_GAM.search(body)
            if m:
                cur["played"], cur["kind"], cur["best"] = m.group(1), "gamble", m.group(6)
            if body.startswith("Best move wins"):
                cur["kind"] = "best"
            if body.startswith("Overdraft: played"):
                cur["kind"] = "overdraft"
    # depth: fill from known depths (+2 per turn)
    known = [(i, t["depth"]) for i, t in enumerate(turns) if t["depth"] is not None]
    if not known:
        return settings, []
    i0, d0 = known[0]
    bad = 0
    for i, t in enumerate(turns):
        d = d0 + 2 * (i - i0)
        if t["depth"] is not None and t["depth"] != d:
            bad += 1
        t["depth"] = d if t["depth"] is None else t["depth"]
    return settings, turns, bad


def best_entry(t):
    if not t["scores"]:
        return None
    if t["best"]:
        for s in t["scores"]:
            if s["gtp"] == t["best"]:
                return s
    # best = vloss 0.00 entry (first)
    for s in t["scores"]:
        if abs(s["vloss"]) < 1e-9:
            return s
    return t["scores"][0]


games = []
for p in sorted(glob.glob(os.path.join(LOGS, "game_*.log"))):
    name = os.path.basename(p)
    if name[5:13] < args.since:
        continue
    r = parse(p)
    if not r[0] or len(r) < 3 or not r[1]:
        continue
    games.append((name, r[0], r[1], r[2]))

print("games:", len(games), "tag:", args.tag, "window: depth <", args.until)
tot = {"turns": 0, "scored": 0, "spend": 0}
band = {"<35": 0, "35-45": 0, "45-55": 0, "55-70": 0, ">=70": 0}
kinds = {}
inv = {}
played_behind = []  # played moves that leave wr_after < 45 from wr_best >= 45
rows = []
for name, settings, turns, bad in games:
    color = "B" if turns[0]["depth"] % 2 == 0 else "W"
    w = [t for t in turns if t["depth"] < args.until and not t["yose"]]
    min_wr = None
    n_beh = 0
    n_gam = 0
    n_sp = 0
    for t in w:
        tot["turns"] += 1
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
        if t["kind"] == "gamble":
            n_gam += 1
        if t["spend"]:
            tot["spend"] += 1
            n_sp += 1
        b = best_entry(t)
        if b is None:
            continue
        tot["scored"] += 1
        wr = b["wr"]
        key = (
            "<35" if wr < 0.35 else "35-45" if wr < 0.45 else "45-55" if wr < 0.55 else "55-70" if wr < 0.70 else ">=70"
        )
        band[key] += 1
        if wr < 0.45:
            n_beh += 1
        min_wr = wr if min_wr is None else min(min_wr, wr)
        # inventory of "slightly behind if answered" traps
        for lab, de, fd in (
            ("dE>=0.5 find<=0.25", 0.5, 0.25),
            ("dE>=0.3 find<=0.25", 0.3, 0.25),
            ("dE>=0.5 find<=0.40", 0.5, 0.40),
            ("dE>=0.3 find<=0.40", 0.3, 0.40),
            ("dE>=0.5 any find", 0.5, 9),
            ("dE>=1.0 any find", 1.0, 9),
        ):
            for blab, lo, hi in (
                ("wr_after 25-50", 0.25, 0.50),
                ("wr_after 25-45", 0.25, 0.45),
                ("any wr>=25", 0.25, 2),
            ):
                q = [
                    s
                    for s in t["scores"]
                    if s is not b and s["e"] - b["e"] >= de and s["find"] <= fd and lo <= s["wr"] < hi
                ]
                k = (lab, blab)
                d = inv.setdefault(k, {"turns": 0, "from_even": 0, "ev": []})
                if q:
                    d["turns"] += 1
                    if wr >= 0.45:
                        d["from_even"] += 1
                    top = max(q, key=lambda s: s["e"] - b["e"] - 0.5 * max(0, s["vloss"]))
                    d["ev"].append((top["e"] - b["e"], top["vloss"], top["wr"], wr, t["spend"] is not None))
        if t["played"]:
            pl = next((s for s in t["scores"] if s["gtp"] == t["played"]), None)
            if pl and wr >= 0.45 and pl["wr"] < 0.45:
                played_behind.append((name, t["depth"], t["kind"], pl["vloss"], pl["e"] - b["e"], wr, pl["wr"]))
    rows.append((name, color, len(w), n_sp, n_gam, n_beh, min_wr, bad))

print("\nper game (window turns / spend turns / gamble plays / turns with wr_best<45% / min wr_best):")
for r in rows:
    print(
        "  %s AI=%s turns=%2d spend=%2d gamble=%d behind=%2d min_wr=%s depth_mismatch=%d"
        % (r[0], r[1], r[2], r[3], r[4], r[5], "-" if r[6] is None else "%.0f%%" % (r[6] * 100), r[7])
    )
ng = len(games)
print(
    "\nwindow turns: %d (%.1f/game)  scored: %d  spend-mode: %d (%.0f%%)"
    % (tot["turns"], tot["turns"] / ng, tot["scored"], tot["spend"], 100.0 * tot["spend"] / max(1, tot["turns"]))
)
print("decision kinds:", kinds)
print(
    "wr after best move (AI view) bands:",
    {k: "%d (%.0f%%)" % (v, 100.0 * v / max(1, tot["scored"])) for k, v in band.items()},
)
print(
    "\nplayed moves taking wr from >=45%% to <45%% (if answered correctly): %d (%.2f/game)"
    % (len(played_behind), len(played_behind) / ng)
)
for x in played_behind:
    print(
        "   %s d=%d %s vloss=%.2f dE=%+.2f wr %.0f%% -> %.0f%%" % (x[0], x[1], x[2], x[3], x[4], x[5] * 100, x[6] * 100)
    )
print(
    "\ninventory (turns with >=1 qualifying probed candidate; per game; from wr_best>=45%; median dE / vloss / wr_after of the top one; share in spend mode):"
)
for k in sorted(inv):
    d = inv[k]
    if not d["ev"]:
        print("  %-22s %-16s 0" % k)
        continue
    print(
        "  %-22s %-16s turns=%3d (%.2f/game) from_even=%3d  dE=%.2f vloss=%.2f wr_after=%.0f%% spend=%.0f%%"
        % (
            k[0],
            k[1],
            d["turns"],
            d["turns"] / ng,
            d["from_even"],
            st.median(e[0] for e in d["ev"]),
            st.median(e[1] for e in d["ev"]),
            100 * st.median(e[2] for e in d["ev"]),
            100.0 * sum(1 for e in d["ev"] if e[4]) / len(d["ev"]),
        )
    )
