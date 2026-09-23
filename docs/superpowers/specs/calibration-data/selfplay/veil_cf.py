"""Counterfactual replay of the proposed Veil13 controller on the 18 recon games (KataGo-free).

Rows come from offline_report.py (2500v re-analysis, visits>=10 alternatives, raw relativePointsLost).
For every AI turn we decide: forced best / dominance-closed best / near-free deviation / paid deviation,
using the running report-identical tally of the simulated own matches and the opponent's actual matches.
Loss of a deviation = alt_min_loss (raw, optimistic). Positions are the actually played ones (no trajectory).
"""
import glob
import json
import math
import os
import sys

RECON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon") + os.sep


def opp_estimate(opp, n, prior, k):
    return (opp + prior * k) / (n + k)


def target(opp_hat, delta, lo, hi):
    return min(hi, max(lo, opp_hat - delta))


def run(cfg, q_natural=1.0, verbose=False, lead_correct=False):
    tot = dict(n=0, match=0, loss=0.0, dev_free=0, dev_paid=0, dev_dom=0, forced=0, domclosed=0, gateclosed_paid=0)
    per_phase = {"open": [0, 0], "mid": [0, 0], "end": [0, 0]}
    games = []
    import random
    rng = random.Random(1)
    for f in sorted(glob.glob(RECON + "report_game_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        ai = d["summary"]["ai"]
        sign = 1 if ai == "B" else -1
        rows = d["rows"]
        mine = n_mine = opp = n_opp = 0
        spent = 0.0
        prev_score = None
        g = dict(n=0, match=0, loss=0.0)
        prev_T = None
        actual_spent = 0.0
        for r in rows:
            if r["player"] != ai:
                if r["top"] is not None:
                    opp += int(r["match"])
                    n_opp += 1
                prev_score = r["score"]
                continue
            lead = (prev_score if prev_score is not None else 0.0) * sign
            if lead_correct:
                lead += actual_spent - spent  # give back what the recorded AI actually lost, charge the simulated spend
            opp_hat = opp_estimate(opp, n_opp, cfg["prior"], cfg["k"])
            T = target(opp_hat, cfg["delta"], cfg["lo"], cfg["hi"])
            if prev_T is not None and abs(T - prev_T) < cfg["deadband"]:
                T = prev_T
            prev_T = T
            gate = (mine + 1) / (n_mine + 1) > T
            free = cfg["free"] if lead >= cfg["behind"] else cfg["free_behind"]
            surplus = lead - cfg["reserve"]
            paid = min(cfg["max_paid"], cfg["spend"] * surplus) if (gate and surplus > 0) else 0.0
            alt = r["alt_min_loss"]
            dom = (r["top_prior"] or 0) >= cfg["dom"]
            depth = r["depth"]
            phase = "open" if depth < 24 else ("mid" if depth < 85 else "end")
            dev = False
            cost = 0.0
            natural = rng.random() < q_natural
            if alt is None or not natural:
                tot["forced"] += 1
            elif dom and not gate:
                tot["domclosed"] += 1
            elif alt <= free:
                dev, cost = True, alt
                tot["dev_dom" if dom else "dev_free"] += 1
            elif paid > 0 and alt <= paid and (dom is False or alt <= cfg["dom_max"]):
                dev, cost = True, alt
                tot["dev_dom" if dom else "dev_paid"] += 1
            else:
                if not gate and alt is not None and alt <= cfg["max_paid"]:
                    tot["gateclosed_paid"] += 1
                tot["forced"] += 0
            m = 0 if dev else 1
            mine += m
            n_mine += 1
            spent += cost
            actual_spent += max(0.0, r["ptloss"] or 0.0)
            g["n"] += 1
            g["match"] += m
            g["loss"] += cost
            per_phase[phase][0] += 1
            per_phase[phase][1] += m
            prev_score = r["score"]
        opp_rate = opp / n_opp if n_opp else float("nan")
        games.append((d["summary"]["game"], d["summary"]["final_score"] * sign + ((actual_spent - spent) if lead_correct else 0.0), g["match"] / g["n"], opp_rate, g["loss"], g["n"]))
        tot["n"] += g["n"]
        tot["match"] += g["match"]
        tot["loss"] += g["loss"]
    below = sum(1 for _, _, m, o, _, _ in games if m < o)
    band = sum(1 for _, _, m, o, _, _ in games if 0.15 <= m <= 0.35)
    out = dict(
        rate=tot["match"] / tot["n"], loss_per_move=tot["loss"] / tot["n"], below_opp=below, in_band=band, games=len(games),
        dev_free=tot["dev_free"], dev_paid=tot["dev_paid"], dev_dom=tot["dev_dom"], forced=tot["forced"],
        domclosed=tot["domclosed"], n=tot["n"],
        phase={k: round(v[1] / v[0], 3) if v[0] else None for k, v in per_phase.items()},
    )
    if verbose:
        for gname, final, m, o, loss, n in games:
            print(f"  {gname} final_ai={final:+6.1f} mine={m:.2f} opp={o:.2f} spent={loss:5.1f} n={n}")
    return out


BASE = dict(prior=0.23, k=20, delta=0.05, lo=0.15, hi=0.35, deadband=0.02, free=0.25, free_behind=0.1, behind=-1.0,
            reserve=5.0, spend=0.25, max_paid=2.5, dom=0.8, dom_max=2.5)

if __name__ == "__main__":
    variants = {
        "base": {},
        "free_only(paid off)": dict(max_paid=0.0),
        "free0.1": dict(free=0.1),
        "free0.3": dict(free=0.3),
        "reserve3": dict(reserve=3.0),
        "spend0.5": dict(spend=0.5),
        "max_paid4": dict(max_paid=4.0),
        "dom_max1.0": dict(dom_max=1.0),
        "no_gate(T=0)": dict(lo=0.0, hi=0.0, delta=1.0),
        "hi0.30": dict(hi=0.30),
    }
    for name, over in variants.items():
        for q in (1.0, 0.7):
            cfg = {**BASE, **over}
            r = run(cfg, q_natural=q)
            print(f"{name:22s} q={q:.1f} rate={r['rate']:.3f} loss/mv={r['loss_per_move']:.3f} below_opp={r['below_opp']}/{r['games']} "
                  f"in15-35={r['in_band']} free={r['dev_free']} paid={r['dev_paid']} dom={r['dev_dom']} forced={r['forced']} "
                  f"domclosed={r['domclosed']} phase={r['phase']}")
    print("per-game (base, q=1.0):")
    run(BASE, 1.0, verbose=True)
    print("per-game (base, q=0.7):")
    run(BASE, 0.7, verbose=True)
