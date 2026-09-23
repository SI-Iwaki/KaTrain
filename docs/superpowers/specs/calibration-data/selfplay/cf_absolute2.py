import os
import sys
sys.argv = [sys.argv[0]]
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cf_absolute.py"), encoding="utf-8").read().split("print(list(GAMES")[0])
import statistics as st
# decomposition of matched turns under USER default (lead-corrected)
def decomp(T=0.30, reserve=5.0, max_loss=4.5, yose_max=1.5, dom_max=2.0, rho=0.5, free=0.3, close=3.0, close_free=0.16):
    cats = {}
    tot = 0
    for summ, rows in GAMES:
        ai = summ["ai"]; sg = 1 if ai == "B" else -1
        prev = 0.0; spent = 0.0; actual = 0.0
        for r in rows:
            if r["player"] != ai:
                prev = r["score"] if r["score"] is not None else prev; continue
            lead = prev * sg + (actual - spent)
            yose = r["depth"] >= 85
            dom = (r.get("top_prior") or 0) >= 0.8
            alt = r.get("alt_min_loss")
            F = free
            if abs(lead) < close: F = min(F, close_free)
            if yose and lead < reserve: F = min(F, 0.05)
            S = lead - reserve
            A = 0.0
            if S > 0:
                cap = yose_max if yose else max_loss
                A = min(S, min(cap, max(F, rho * S)))
                if dom: A = min(A, dom_max)
            tot += 1
            if alt is None: c = "no alternative (visits>=10)"
            elif alt <= F: c = "deviable: near-free"
            elif A > 0 and alt <= A: c = "deviable: paid"
            elif S <= 0: c = f"blocked: lead<{reserve:g} (reserve), alt>{F:.2f}"
            else: c = "blocked: alt > allowance"
            cats[c] = cats.get(c, 0) + 1
            if c.startswith("deviable"): spent += alt
            actual += max(0.0, r["ptloss"] or 0.0)
            prev = r["score"] if r["score"] is not None else prev
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {k:45s} {v/tot*100:5.1f}%")
print("DECOMPOSITION (user default, gate always open, q=1):"); decomp()
print("\nSENSITIVITY (lead-corrected, own%, P(<=35%))")
for name, kw in [
    ("user default", {}),
    ("close near-free 0.3 (no close guard)", dict(close_free=0.3)),
    ("close guard off + yose F kept", dict(close=0.0)),
    ("q=1 (every cheapest alt natural)", dict(q=1.0, q_dom=1.0)),
    ("reserve 0 + wide caps (no safety)", dict(reserve=0.0, max_loss=6.0, yose_max=3.0, dom_max=4.0)),
    ("all off: reserve0 cap99 q1 closeoff", dict(reserve=0.0, max_loss=99, yose_max=99, dom_max=99, q=1.0, q_dom=1.0, close=0.0)),
]:
    own, p10, p90, opp, below, band, loss = run(lead_correct=True, **kw)
    print(f"  {name:40s} own {own*100:4.1f}  p10 {p10*100:4.1f}  P(<=35) {band:4.2f}  own<opp {below:4.2f}  loss/mv {loss:4.2f}")
