"""Per-arm opening-window stats from selfplay moves.jsonl (depth <= W). Usage: win_stats.py DIR [DIR...] [--w 40]"""
import json, sys, statistics as st
from collections import defaultdict

W = 40
argv = sys.argv[1:]
if "--w" in argv:
    i = argv.index("--w")
    W = int(argv[i + 1])
    argv = argv[:i] + argv[i + 2:]
args = argv

games = defaultdict(lambda: defaultdict(dict))  # arm -> seed -> data
for d in args:
    meta = {}
    for l in open(f"{d}/games.jsonl", encoding="utf-8"):
        g = json.loads(l)
        meta[(g["arm"], g["seed"])] = g
    for l in open(f"{d}/moves.jsonl", encoding="utf-8"):
        m = json.loads(l)
        key = (m["arm"], m["seed"])
        g = games[m["arm"]].setdefault(m["seed"], {"own": [0, 0], "opp": [0, 0], "own_all": [0, 0], "opp_all": [0, 0],
                                                    "lead_w": None, "loss_own": 0.0, "loss_opp": 0.0, "meta": meta.get(key)})
        if m.get("trailing_pass") or m.get("match") is None:
            continue
        side = "own" if m["is_ai"] else "opp"
        g[side + "_all"][0] += int(bool(m["match"]))
        g[side + "_all"][1] += 1
        if m["depth"] <= W:
            g[side][0] += int(bool(m["match"]))
            g[side][1] += 1
            pl = m.get("points_lost")
            if pl is not None:
                g["loss_" + side] += max(0.0, pl)
            if m["is_ai"] and m.get("lead_after_ai") is not None:
                g["lead_w"] = m["lead_after_ai"]

def rate(x):
    return x[0] / x[1] if x[1] else float("nan")

print(f"window depth <= {W}")
for arm, seeds in games.items():
    own = [rate(g["own"]) for g in seeds.values() if g["own"][1]]
    opp = [rate(g["opp"]) for g in seeds.values() if g["opp"][1]]
    own_all = [rate(g["own_all"]) for g in seeds.values() if g["own_all"][1]]
    opp_all = [rate(g["opp_all"]) for g in seeds.values() if g["opp_all"][1]]
    leads = [g["lead_w"] for g in seeds.values() if g["lead_w"] is not None]
    lo = [g["loss_opp"] / max(1, g["opp"][1]) for g in seeds.values()]
    la = [g["loss_own"] / max(1, g["own"][1]) for g in seeds.values()]
    le = sum(1 for g in seeds.values() if g["own"][1] and rate(g["own"]) <= rate(g["opp"]))
    res = defaultdict(int)
    for g in seeds.values():
        mt = g["meta"] or {}
        fl = mt.get("final_lead")
        res["win" if (fl or 0) > 0 else "loss"] += 1
    bycol = defaultdict(list)
    for g in seeds.values():
        c = (g["meta"] or {}).get("ai_color")
        if g["own"][1]:
            bycol[c].append((rate(g["own"]), rate(g["opp"]), g["lead_w"]))
    print(f"[{arm}] n={len(seeds)} win: own {st.mean(own):.1%} opp {st.mean(opp):.1%} | own<=opp {le}/{len(own)}"
          f" | lead@W med {st.median(leads):+.2f} mean {st.mean(leads):+.2f} neg {sum(1 for x in leads if x < 0)}"
          f" | loss/move own {st.mean(la):.2f} opp {st.mean(lo):.2f} | all: own {st.mean(own_all):.1%} opp {st.mean(opp_all):.1%}"
          f" | final_lead>0 {res['win']}/{len(seeds)}")
    for c, v in sorted(bycol.items(), key=lambda kv: str(kv[0])):
        print(f"    {c}: n={len(v)} own {st.mean(x[0] for x in v):.1%} opp {st.mean(x[1] for x in v):.1%} "
              f"lead@W med {st.median([x[2] for x in v if x[2] is not None]):+.2f}")
