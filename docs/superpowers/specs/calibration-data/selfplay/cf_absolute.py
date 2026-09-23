"""Counterfactual for the user's chosen direction: absolute target + widened per-move loss cap.
Same data/assumptions as judge/unified_cf.py (18 recon 13x13 games, raw alt_min_loss visits>=10,
naturalness prob q, close-game near-free guard). Safety kept: reserve 5, (winrate floor approximated by reserve).
"""
import glob, json, os, random, statistics as st, sys
sys.stdout.reconfigure(encoding="utf-8")
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon")
GAMES = []
for f in sorted(glob.glob(os.path.join(R, "report_game_*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    GAMES.append((d["summary"], d["rows"]))

def run(T=0.30, reserve=5.0, max_loss=4.5, yose_max=1.5, dom_max=2.0, rho=0.5, free=0.3,
        q=0.85, q_dom=0.6, close=3.0, close_free=0.16, lead_correct=True, reps=60, seed=7):
    rng = random.Random(seed)
    out = []
    for rep in range(reps):
        for summ, rows in GAMES:
            ai = summ["ai"]; sg = 1 if ai == "B" else -1
            mine = n = opp = n_opp = 0
            prev = 0.0; spent = 0.0; actual = 0.0; loss = 0.0
            for r in rows:
                if r["player"] != ai:
                    n_opp += 1; opp += int(bool(r["match"]))
                    prev = r["score"] if r["score"] is not None else prev
                    continue
                lead = prev * sg + ((actual - spent) if lead_correct else 0.0)
                p = (mine + 1) / (n + 1)
                gate = p > T
                u = min(1.0, max(0.0, (p - T) / 0.10))
                yose = r["depth"] >= 85
                dom = (r.get("top_prior") or 0) >= 0.8
                alt = r.get("alt_min_loss")
                F = free
                if abs(lead) < close:
                    F = min(F, close_free)
                if yose and lead < reserve:
                    F = min(F, 0.05)
                S = lead - reserve
                A = 0.0
                if gate and S > 0:
                    cap = yose_max if yose else max_loss
                    a_lead = min(cap, max(F, rho * S))
                    A = min(S, F + u * (a_lead - F))
                    if dom:
                        A = min(A, dom_max)
                dev = False; cost = 0.0
                if alt is not None and not (dom and not gate):
                    keep = q_dom if dom else q
                    if alt <= F and rng.random() < keep:
                        dev, cost = True, alt
                    elif A > 0 and alt <= A and rng.random() < keep:
                        dev, cost = True, alt
                n += 1
                if dev:
                    loss += max(0.0, cost); spent += max(0.0, cost)
                else:
                    mine += 1
                actual += max(0.0, r["ptloss"] or 0.0)
                prev = r["score"] if r["score"] is not None else prev
            out.append(dict(g=summ["game"], own=mine / n, opp=opp / max(1, n_opp), loss=loss / n,
                            final=summ.get("final_lead") or summ.get("final")))
    own = [x["own"] for x in out]
    return (st.mean(own), st.quantiles(own, n=10)[0], st.quantiles(own, n=10)[-1],
            st.mean(x["opp"] for x in out), st.mean(x["own"] < x["opp"] for x in out),
            st.mean(0.15 <= x["own"] <= 0.35 for x in out), st.mean(x["loss"] for x in out))

print(list(GAMES[0][0].keys()))
print("config                                   lead_corr  own  p10  p90  opp  P(own<opp) P(<=35%) loss/mv")
CONF = [
    ("mimic-like ref: cap2.5 dom1 (final.md dflt)", dict(max_loss=2.5, yose_max=1.0, dom_max=1.0, T=0.30)),
    ("USER: cap4.5 yose1.5 dom2.0 T.30",            dict()),
    ("USER: cap4.5 yose1.5 dom2.0 T.25",            dict(T=0.25)),
    ("USER: cap6 yose2 dom3 T.30",                  dict(max_loss=6.0, yose_max=2.0, dom_max=3.0)),
    ("USER: cap4.5 rho1.0 T.30",                    dict(rho=1.0)),
    ("ref: reserve3 cap4.5 (safety relaxed)",       dict(reserve=3.0)),
]
for lc in (False, True):
    for name, kw in CONF:
        own, p10, p90, opp, below, band, loss = run(lead_correct=lc, **kw)
        print(f"{name:42s} {str(lc):5s}  {own*100:4.1f} {p10*100:4.1f} {p90*100:4.1f} {opp*100:4.1f}   {below:5.2f}     {band:5.2f}   {loss:4.2f}")
