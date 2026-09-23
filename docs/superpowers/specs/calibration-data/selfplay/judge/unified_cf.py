"""Judge: one counterfactual for all three designs on equal footing (13x13 recon rows, 18 games).
Adds what the design CFs omitted: near-free winrate-drop guard in close positions (slope ~0.183 wr/pt measured
from Enigma+ logs -> 0.03 cap ~= 0.16 pt when |lead| < close), and reports with and without lead-trajectory
correction. Raw alt_min_loss (visits>=10) is used as cost (optimistic by ~+0.07 mean, see raw_vs_vloss.py).
"""
import glob, json, os, random, statistics as st, sys
sys.stdout.reconfigure(encoding="utf-8")
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "recon")
GAMES = []
for f in sorted(glob.glob(os.path.join(R, "report_game_*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    GAMES.append((d["summary"], d["rows"]))

def paid_cap(design, lead, S, u, yose):
    if S <= 0 or lead < -1:
        return 0.0
    if design == "probe":
        F, cap = 0.3, (1.5 if yose else 3.0)
        a_lead = min(cap, max(F, 0.5 * S))
        return min(S, F + u * (a_lead - F)) if u > 0 else 0.0
    if design == "jigo":
        lam = min(2.5, max(0.3, 0.5 * S), S)
        return min(lam, 1.0) if yose else lam
    if design == "light":
        return min(2.5, 0.25 * S)

FREE = {"probe": 0.3, "jigo": 0.3, "light": 0.25}

def run(design, q=0.85, q_dom=0.6, close=3.0, close_free=0.16, lead_correct=False, reps=60, seed=7):
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
                opp_hat = (opp + 16 * 0.23) / (n_opp + 16)
                T = min(0.35, max(0.15, opp_hat - 0.05))
                p = (mine + 1) / (n + 1)
                gate = p > T
                u = min(1.0, max(0.0, (p - T) / 0.10))
                yose = r["depth"] >= 85
                dom = (r.get("top_prior") or 0) >= 0.8
                alt = r.get("alt_min_loss")
                F = FREE[design]
                if lead < -1 and design == "light":
                    F = 0.1
                if abs(lead) < close:
                    F = min(F, close_free)
                if yose and design == "probe" and lead < 5.0:
                    F = min(F, 0.05)   # yose wr-drop 0.01 unless lead_after>=reserve
                S = lead - 5.0
                A = paid_cap(design, lead, S, u, yose) if gate else 0.0
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
            out.append(dict(g=summ["game"], own=mine / n, opp=opp / max(1, n_opp), loss=loss / n))
    own = st.mean(x["own"] for x in out); oppm = st.mean(x["opp"] for x in out)
    below = st.mean(x["own"] < x["opp"] for x in out); band = st.mean(0.15 <= x["own"] <= 0.35 for x in out)
    return own, oppm, below, band, st.mean(x["loss"] for x in out)

print("design lead_corr close_guard  own    opp   P(own<opp) P(15-35)  rawloss/mv")
for lc in (False, True):
    for guard in (False, True):
        for dsg in ("probe", "jigo", "light"):
            o, op, b, bd, l = run(dsg, lead_correct=lc, close=(3.0 if guard else -1.0))
            print(f"{dsg:6s} {str(lc):5s} {str(guard):5s}  {o:.3f}  {op:.3f}  {b:.2f}  {bd:.2f}  {l:.3f}")
print("-- upper bound (q=1,q_dom=1, guard, lead_corr)")
for dsg in ("probe", "jigo", "light"):
    o, op, b, bd, l = run(dsg, q=1.0, q_dom=1.0, lead_correct=True, close=3.0)
    print(f"{dsg:6s} own {o:.3f} P(own<opp) {b:.2f} P(15-35) {bd:.2f} loss {l:.3f}")
