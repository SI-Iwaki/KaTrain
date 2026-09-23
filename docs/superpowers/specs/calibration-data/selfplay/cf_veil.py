"""Static counterfactual of the proposed 'Veil' rule on the 18 recon games (13x13, 2500v re-analysis rows).

Rows: depth, player, top, match, ptloss, score (black-persp lead at that node), alt_min_loss (raw relPointsLost of
cheapest non-best with visits>=10), alt_le_01/03/05/10 (counts), top_prior (KataGo prior of top move).
Limits: no humanPolicy of alternatives (natural floor applied as a haircut), no trajectory feedback (lead path is the
Enigma+/Mimic path), no child-probe verification (raw losses are slightly optimistic), terminal band not modelled.
"""
import glob
import json
import os
import sys

RECON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon")


def alt_within(r, x):
    m = r.get("alt_min_loss")
    return m is not None and m <= x + 1e-9


def run(params, verbose=False):
    F = params["F"]
    R = params["R"]
    rho = params["rho"]
    A_max = params["A_max"]
    A_yose = params["A_yose"]
    dom = params["dom"]
    p0, k, delta = params["p0"], params["k"], params["delta"]
    Tmin, Tmax, w_u = params["Tmin"], params["Tmax"], params["w_u"]
    natural_keep = params["natural_keep"]  # fraction of alternatives that pass hp floor + safety (haircut)
    free_always = params.get("free_always", True)
    yose_d = params.get("yose_depth", 85)
    tot = {"n": 0, "match": 0, "loss": 0.0, "opp_n": 0, "opp_match": 0, "below": 0, "games": 0,
           "free": 0, "paid": 0, "dom_dev": 0, "phase": {}}
    per_game = []
    for f in sorted(glob.glob(os.path.join(RECON, "report_game_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        ai = d["summary"]["ai"]
        sign = 1 if ai == "B" else -1
        rows = d["rows"]
        mine = n_mine = opp = n_opp = 0
        loss = 0.0
        prev_score = 0.0
        g_free = g_paid = 0
        import random
        rnd = random.Random(hash(f) & 0xFFFF)
        for r in rows:
            if r["player"] != ai:
                n_opp += 1
                opp += int(bool(r["match"]))
                prev_score = r["score"] if r["score"] is not None else prev_score
                continue
            lead = prev_score * sign
            opp_hat = (opp + k * p0) / (n_opp + k)
            T = min(Tmax, max(Tmin, opp_hat - delta))
            p_match = (mine + 1) / (n_mine + 1)
            u = min(1.0, max(0.0, (p_match - T) / w_u))
            S = lead - R
            in_yose = r["depth"] >= yose_d
            dominant = (r.get("top_prior") or 0) >= dom
            f_eff = F if p_match > Tmin else min(F, 0.1)
            deviate, cost, kind = False, 0.0, None
            # near-free (tier iii only)
            if not dominant and free_always and alt_within(r, f_eff) and rnd.random() < natural_keep:
                deviate, cost, kind = True, r["alt_min_loss"], "free"
            elif u > 0 and S > 0:
                a_lead = min(A_yose if in_yose else A_max, max(F, rho * S))
                A = F + u * (a_lead - F)
                A = min(A, S)  # reserve kept
                if alt_within(r, A) and rnd.random() < (params["dom_keep"] if dominant else natural_keep):
                    deviate, cost, kind = True, r["alt_min_loss"], ("dom" if dominant else "paid")
            n_mine += 1
            if deviate:
                loss += max(0.0, cost)
                if kind == "free":
                    g_free += 1
                else:
                    g_paid += 1
                    if kind == "dom":
                        tot["dom_dev"] += 1
            else:
                mine += 1
            ph = "open" if r["depth"] < 24 else ("mid" if r["depth"] < 68 else "end")
            pp = tot["phase"].setdefault(ph, [0, 0])
            pp[0] += 1
            pp[1] += 0 if deviate else 1
            prev_score = r["score"] if r["score"] is not None else prev_score
        tot["n"] += n_mine
        tot["match"] += mine
        tot["loss"] += loss
        tot["opp_n"] += n_opp
        tot["opp_match"] += opp
        tot["games"] += 1
        tot["free"] += g_free
        tot["paid"] += g_paid
        my_rate = mine / max(1, n_mine)
        opp_rate = opp / max(1, n_opp)
        tot["below"] += int(my_rate < opp_rate)
        per_game.append((os.path.basename(f)[12:27], d["summary"]["strategy"][:6], round(my_rate, 3), round(opp_rate, 3),
                         round(loss / max(1, n_mine), 2), round(d["summary"]["final_score"] * sign, 1), g_free, g_paid))
    out = {
        "own_rate": round(tot["match"] / tot["n"], 3),
        "opp_rate": round(tot["opp_match"] / tot["opp_n"], 3),
        "loss_per_move": round(tot["loss"] / tot["n"], 3),
        "games_below_opp": f"{tot['below']}/{tot['games']}",
        "free_dev_per_game": round(tot["free"] / tot["games"], 1),
        "paid_dev_per_game": round(tot["paid"] / tot["games"], 1),
        "dom_dev_per_game": round(tot["dom_dev"] / tot["games"], 1),
        "phase_rate": {k: round(v[1] / v[0], 3) for k, v in tot["phase"].items()},
    }
    if verbose:
        for g in per_game:
            print(g)
    return out


BASE = dict(F=0.3, R=5.0, rho=0.3, A_max=2.5, A_yose=1.0, dom=0.8, p0=0.23, k=16, delta=0.05,
            Tmin=0.15, Tmax=0.35, w_u=0.10, natural_keep=0.85, dom_keep=0.6)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("BASE", run(BASE, verbose=True))
    for name, over in [
        ("upper_bound_keep1", dict(natural_keep=1.0, dom_keep=1.0)),
        ("free_only(no paid)", dict(rho=0.0, A_max=0.3, A_yose=0.3)),
        ("F=0.1", dict(F=0.1)),
        ("R=3", dict(R=3.0)),
        ("R=8", dict(R=8.0)),
        ("A_max=1.5", dict(A_max=1.5)),
        ("A_max=4", dict(A_max=4.0)),
        ("no_dom_relax", dict(dom_keep=0.0)),
        ("keep0.7", dict(natural_keep=0.7, dom_keep=0.5)),
        ("Tmin=0.20", dict(Tmin=0.20)),
        ("delta=0", dict(delta=0.0)),
    ]:
        p = dict(BASE)
        p.update(over)
        print(name, run(p))
