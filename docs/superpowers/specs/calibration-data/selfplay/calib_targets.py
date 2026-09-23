import glob, json, os, statistics as st, sys
D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon")
rows_all = []
games = []
for f in sorted(glob.glob(os.path.join(D, "report_game_*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    s = d["summary"]; rows = d["rows"]; ai = s["ai"]
    sign = 1 if ai == "B" else -1
    fs = s["final_score"] * sign if s["final_score"] is not None else None
    # lead (AI view) trajectory
    leads = [r["score"] * sign for r in rows if r["score"] is not None]
    games.append((s["game"], s["strategy"][:8], ai, s["n_moves"], fs, s["secs"], s["mine"]["match"], s["opp"]["match"], s["opp"]["mean_loss"], max(leads) if leads else None))
    for r in rows:
        r = dict(r); r["opp"] = r["player"] != ai; r["game"] = s["game"]; rows_all.append(r)
print("game strat ai n final secs mine opp opploss maxlead")
for g in games:
    print("%s %s %s %3d %7.1f %5.0fs  %.2f %.2f %.2f %6.1f" % g)
print("secs per node:", sum(g[5] for g in games) / sum(g[3] + 1 for g in games))
print("lengths", sorted(g[3] for g in games), "median", st.median(g[3] for g in games))
print("final AI lead", sorted(round(g[4], 1) for g in games))
def agg(sel, label):
    rs = [r for r in rows_all if sel(r) and r["ptloss"] is not None]
    if not rs: return
    L = [max(0, r["ptloss"]) for r in rs]
    print("%-22s n=%4d match=%.3f loss=%.2f med=%.2f >=2:%.2f >=5:%.2f top_prior>=.8:%.2f" % (
        label, len(rs), sum(r["match"] for r in rs) / len(rs), sum(L) / len(L), st.median(L),
        sum(x >= 2 for x in L) / len(L), sum(x >= 5 for x in L) / len(L),
        sum((r["top_prior"] or 0) >= 0.8 for r in rs) / len(rs)))
for who, f in (("opp", lambda r: r["opp"]), ("ai", lambda r: not r["opp"])):
    agg(f, who + " all")
    agg(lambda r, f=f: f(r) and r["depth"] < 24, who + " opening<24")
    agg(lambda r, f=f: f(r) and 24 <= r["depth"] < 85, who + " middle24-84")
    agg(lambda r, f=f: f(r) and r["depth"] >= 85, who + " endgame>=85")
# per-game opp rate distribution
print("opp rates", sorted(round(g[7], 2) for g in games), "sd", round(st.pstdev(g[7] for g in games), 3))
print("opp loss", sorted(round(g[8], 2) for g in games))
