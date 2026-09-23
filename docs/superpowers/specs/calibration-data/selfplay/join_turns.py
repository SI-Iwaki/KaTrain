"""Join log-side turn kinds with the offline re-analysis; counterfactual 'deviate whenever cheap' rates.

Throwaway spike script (2026-09-18).
"""

import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(HERE, "recon")
summ = json.load(open(os.path.join(RECON, "summary.json"), encoding="utf-8"))
X = [0.1, 0.3, 0.5, 1.0]

by_strat = defaultdict(
    lambda: dict(kind_n=defaultdict(int), kind_match=defaultdict(int), kind_alt=defaultdict(list), turns=[], opp=[])
)
print(
    "game                 strat        | log-kind match rates ... | counterfactual deviate-if-alt<=X: match% (extra loss/turn) | opp match"
)
for s in summ:
    path = os.path.join(RECON, "report_" + s["game"] + ".json")
    if not os.path.exists(path):
        print(s["game"], "no report yet")
        continue
    rep = json.load(open(path, encoding="utf-8"))
    rows = rep["rows"]
    ai = s["ai"]
    ai_rows = [r for r in rows if r["player"] == ai]
    turns = s["turns"]
    if len(ai_rows) != len(turns):
        print("   !! turn count mismatch", s["game"], len(ai_rows), len(turns))
    n = min(len(ai_rows), len(turns))
    S = by_strat[s["strategy"]]
    kinds_here = defaultdict(lambda: [0, 0])
    for r, t in zip(ai_rows[:n], turns[:n]):
        k = t["kind"]
        if k.startswith("?"):
            k = "?"
        S["kind_n"][k] += 1
        S["kind_match"][k] += r["match"]
        kinds_here[k][0] += 1
        kinds_here[k][1] += r["match"]
        if r["match"]:
            S["kind_alt"][k].append(r["alt_min_loss"])
        S["turns"].append(r)
    S["opp"].extend(r for r in rows if r["player"] != ai)
    # counterfactual on this game
    cf = []
    for x in X:
        dev = [r for r in ai_rows if r["alt_min_loss"] is not None and r["alt_min_loss"] <= x]
        keep = [r for r in ai_rows if r not in dev]
        match = sum(r["match"] for r in keep) / len(ai_rows)
        extra = sum(r["alt_min_loss"] for r in dev) / len(ai_rows)
        cf.append("%.0f%%(%.2f)" % (100 * match, extra))
    opp_rows = [r for r in rows if r["player"] != ai and r["ptloss"] is not None]
    opp_match = sum(r["match"] for r in opp_rows) / max(1, len(opp_rows))
    # sanity: log's best move vs offline KataGo top on deviate turns (alignment check)
    agree = [(t.get("best") == r["top"]) for r, t in zip(ai_rows[:n], turns[:n]) if t["kind"] in ("deviate", "gamble") and t.get("best")]
    kinds_txt = " ".join("%s %d/%d" % (k[:8], v[1], v[0]) for k, v in sorted(kinds_here.items()))
    kinds_txt += " | best-agree %d/%d" % (sum(agree), len(agree))
    print("%s %-12s | %s | %s | %.0f%%" % (s["game"], s["strategy"][:12], kinds_txt, " ".join(cf), 100 * opp_match))

for strat, S in by_strat.items():
    print("\n==", strat, "AI turns:", len(S["turns"]))
    for k in sorted(S["kind_n"]):
        alts = [a for a in S["kind_alt"][k] if a is not None]
        cheap = lambda x: sum(1 for a in alts if a <= x)
        print(
            "  %-10s n=%3d offline-match %3.0f%% | matched turns with alt<=0.1/0.3/0.5/1.0: %d/%d/%d/%d of %d"
            % (
                k,
                S["kind_n"][k],
                100 * S["kind_match"][k] / S["kind_n"][k],
                cheap(0.1),
                cheap(0.3),
                cheap(0.5),
                cheap(1.0),
                len(alts),
            )
        )
    T = S["turns"]
    print(
        "  own: match %.0f%% mean loss %.2f | opp: match %.0f%% mean loss %.2f (n=%d)"
        % (
            100 * sum(r["match"] for r in T) / len(T),
            sum(max(0.0, r["ptloss"] or 0.0) for r in T) / len(T),
            100 * sum(r["match"] for r in S["opp"]) / len(S["opp"]),
            sum(max(0.0, r["ptloss"] or 0.0) for r in S["opp"]) / len(S["opp"]),
            len(S["opp"]),
        )
    )
    for x in X:
        dev = [r for r in T if r["alt_min_loss"] is not None and r["alt_min_loss"] <= x]
        keep = [r for r in T if not (r["alt_min_loss"] is not None and r["alt_min_loss"] <= x)]
        print(
            "  counterfactual deviate whenever alt<=%.1f: match %.0f%% (turns with such alt %.0f%%, extra loss %.2f/turn)"
            % (
                x,
                100 * sum(r["match"] for r in keep) / len(T),
                100 * len(dev) / len(T),
                sum(r["alt_min_loss"] for r in dev) / len(T),
            )
        )
    pre = [r for r in T if r["depth"] < 85]
    post = [r for r in T if r["depth"] >= 85]
    for name, part in (("pre85", pre), ("post85", post)):
        if part:
            print(
                "  %s: n=%d match %.0f%% loss %.2f | alt<=0.1: %.0f%% alt<=0.3: %.0f%%"
                % (
                    name,
                    len(part),
                    100 * sum(r["match"] for r in part) / len(part),
                    sum(max(0.0, r["ptloss"] or 0.0) for r in part) / len(part),
                    100
                    * sum(1 for r in part if r["alt_min_loss"] is not None and r["alt_min_loss"] <= 0.1)
                    / len(part),
                    100
                    * sum(1 for r in part if r["alt_min_loss"] is not None and r["alt_min_loss"] <= 0.3)
                    / len(part),
                )
            )
