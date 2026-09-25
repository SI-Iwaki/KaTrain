import argparse, glob, json, math, os, statistics as st, sys
AP = argparse.ArgumentParser(description="校正目標（相手の一致率・損失・区間の形・AI 側の一致率）を recon の事後解析から出す")
AP.add_argument("dir", nargs="?", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon"))
AP.add_argument("--size", type=int, default=13, help="盤サイズ（区間の境目 = ceil(24/169・85/169 × 盤面積)＝13路 24/85・9路 12/41）")
AP.add_argument("--where", default="", help="局を summary（無ければ summary.settings）の値で絞る（k=v,...）")
AP.add_argument("--ai-where", default="", help="AI 側の局平均 ai_mean だけさらに絞る（k=v,...）")
ARGS = AP.parse_args()
D = ARGS.dir
LO, HI = (math.ceil(f * ARGS.size * ARGS.size) for f in (24 / 169, 85 / 169))  # selfplay_stats.calib_bin_moves と同じ


def pick(s, where):
    """summary s が where（k=v,...）をすべて満たすか。キーは summary、無ければ summary.settings。数は数で比べる。"""
    for kv in filter(None, where.split(",")):
        k, v = kv.split("=", 1)
        have = s[k] if k in s else (s.get("settings") or {}).get(k)
        try:
            if float(have) != float(v):
                return False
        except (TypeError, ValueError):
            if str(have) != v:
                return False
    return True


rows_all = []
games = []
summaries = []
for f in sorted(glob.glob(os.path.join(D, "report_game_*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    s = d["summary"]; rows = d["rows"]; ai = s["ai"]
    if not pick(s, ARGS.where):
        continue
    summaries.append(s)
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
    return dict(n=len(rs), match=sum(r["match"] for r in rs) / len(rs), loss=sum(L) / len(L),
                ge2=sum(x >= 2 for x in L) / len(L), ge5=sum(x >= 5 for x in L) / len(L))
T = {}
for who, f in (("opp", lambda r: r["opp"]), ("ai", lambda r: not r["opp"])):
    T[who, "all"] = agg(f, who + " all")
    T[who, "cal_opening"] = agg(lambda r, f=f: f(r) and r["depth"] < LO, who + " opening<%d" % LO)
    T[who, "cal_middle"] = agg(lambda r, f=f: f(r) and LO <= r["depth"] < HI, who + " middle%d-%d" % (LO, HI - 1))
    T[who, "cal_endgame"] = agg(lambda r, f=f: f(r) and r["depth"] >= HI, who + " endgame>=%d" % HI)
# per-game opp rate distribution
print("opp rates", sorted(round(g[7], 2) for g in games), "sd", round(st.pstdev(g[7] for g in games), 3))
print("opp loss", sorted(round(g[8], 2) for g in games))
# 校正目標の形（selfplay_stats.CALIB_TARGETS_<size> にそのまま写す。spec 2026-09-23-veil-strategy-design.md §16.2 手順4）
ai_games = [s for s in summaries if pick(s, ARGS.ai_where)]
opp_rates = [s["opp"]["match"] for s in summaries]
targets = {
    "opp_mean": round(st.fmean(opp_rates), 3),
    "opp_sd": round(st.pstdev(opp_rates), 3),
    "opp_loss": round(st.fmean(s["opp"]["mean_loss"] for s in summaries), 2),
    "opp_ge2": round(T["opp", "all"]["ge2"], 2),
    "opp_ge5": round(T["opp", "all"]["ge5"], 2),
    "ai_mean": round(st.fmean(s["mine"]["match"] for s in ai_games), 3),
    "moves_median": st.median(s["n_moves"] for s in summaries),
    "bins": {n: {"opp_top1": round(T["opp", n]["match"], 3), "opp_loss": round(T["opp", n]["loss"], 2)}
             for n in ("cal_opening", "cal_middle", "cal_endgame")},
}
print("games %d / ai_mean over %d (%s)" % (len(summaries), len(ai_games), ARGS.ai_where or "all"))
print("CALIB_TARGET_GAMES %d/%d" % (len(ai_games), len(summaries)))
print("CALIB_TARGETS " + json.dumps(targets))
