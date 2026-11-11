"""Arm comparison for selfplay runs: opening window (depth<=W) and whole-game match rates, leads, kinds/whys, paired diffs.

Usage: arm_report.py DIR [DIR...] [--w 40] [--base cur]
Arms with the same name in several DIRs are kept separate as name@dirindex when they collide.
"""
import json, random, statistics as st, sys
from collections import Counter, defaultdict

argv = sys.argv[1:]
def opt(name, default):
    global argv
    if name in argv:
        i = argv.index(name)
        v = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
        return v
    return default
W = int(opt("--w", 40))
BASE = opt("--base", "cur")
dirs = argv

arms = defaultdict(dict)  # arm -> seed -> rec
names_seen = defaultdict(set)
for di, d in enumerate(dirs):
    meta = {}
    for l in open(f"{d}/games.jsonl", encoding="utf-8"):
        g = json.loads(l)
        meta[(g["arm"], g["seed"])] = g
    local = {a for a, _ in meta}
    rename = {}
    for a in local:
        rename[a] = a if a not in names_seen or not names_seen[a] else f"{a}@{di}"
    for a in local:
        names_seen[a].add(di)
    for l in open(f"{d}/moves.jsonl", encoding="utf-8"):
        m = json.loads(l)
        arm = rename.get(m["arm"], m["arm"])
        rec = arms[arm].setdefault(m["seed"], {"win": [0, 0], "opp_win": [0, 0], "post": [0, 0], "all": [0, 0],
                                               "opp_all": [0, 0], "lead_w": None, "loss_win": 0.0, "loss_all": 0.0,
                                               "kinds_win": Counter(), "why_win": Counter(), "kinds_post": Counter(),
                                               "why_post": Counter(), "below_res_post": [0, 0],
                                               "meta": meta.get((m["arm"], m["seed"]))})
        if m.get("trailing_pass") or m.get("match") is None:
            continue
        inwin = m["depth"] <= W
        if m["is_ai"]:
            mt = int(bool(m["match"]))
            rec["all"][0] += mt; rec["all"][1] += 1
            pl = max(0.0, m.get("points_lost") or 0.0)
            rec["loss_all"] += pl
            k, why = m.get("decision_kind"), m.get("decision_why")
            if inwin:
                rec["win"][0] += mt; rec["win"][1] += 1
                rec["loss_win"] += pl
                rec["kinds_win"][k] += 1
                if k == "best":
                    rec["why_win"][why] += 1
                if m.get("lead_after_ai") is not None:
                    rec["lead_w"] = m["lead_after_ai"]
            else:
                rec["post"][0] += mt; rec["post"][1] += 1
                rec["kinds_post"][k] += 1
                if k == "best":
                    rec["why_post"][why] += 1
                lb, res = m.get("decision_lead"), m.get("decision_reserve")
                if lb is not None and res is not None:
                    rec["below_res_post"][0] += int(lb < res); rec["below_res_post"][1] += 1
        else:
            mt = int(bool(m["match"]))
            rec["opp_all"][0] += mt; rec["opp_all"][1] += 1
            if inwin:
                rec["opp_win"][0] += mt; rec["opp_win"][1] += 1

def r(x):
    return x[0] / x[1] if x[1] else None

def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else float("nan")

def boot_ci(diffs, n=5000, conf=0.95):
    if len(diffs) < 3:
        return (float("nan"), float("nan"))
    rng = random.Random(1)
    ms = sorted(st.mean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    lo = ms[int((1 - conf) / 2 * n)]
    hi = ms[int((1 + conf) / 2 * n) - 1]
    return lo, hi

print(f"W = depth <= {W}; dirs = {dirs}")
hdr = f"{'arm':12s} {'n':>3s} {'own_W':>6s} {'opp_W':>6s} {'own<=opp':>8s} {'leadW':>6s} {'negW':>4s} {'own_post':>8s} {'own_all':>7s} {'opp_all':>7s} {'loss/mvW':>8s} {'loss/mv':>7s} {'wins':>5s} {'below_res_post':>14s}"
print(hdr)
for arm in sorted(arms):
    S = arms[arm]
    recs = list(S.values())
    wins = sum(1 for g in recs if ((g["meta"] or {}).get("final_lead") or 0) > 0 and (g["meta"] or {}).get("end_reason") != "aborted")
    ab = sum(1 for g in recs if (g["meta"] or {}).get("end_reason") == "aborted")
    le = sum(1 for g in recs if g["win"][1] and r(g["win"]) <= r(g["opp_win"]))
    leads = [g["lead_w"] for g in recs if g["lead_w"] is not None]
    br = [0, 0]
    for g in recs:
        br[0] += g["below_res_post"][0]; br[1] += g["below_res_post"][1]
    print(f"{arm:12s} {len(recs):3d} {mean([r(g['win']) for g in recs]):6.1%} {mean([r(g['opp_win']) for g in recs]):6.1%} "
          f"{le:4d}/{len(recs):<3d} {st.median(leads) if leads else float('nan'):+6.2f} {sum(1 for x in leads if x < 0):4d} "
          f"{mean([r(g['post']) for g in recs]):8.1%} {mean([r(g['all']) for g in recs]):7.1%} {mean([r(g['opp_all']) for g in recs]):7.1%} "
          f"{mean([g['loss_win'] / g['win'][1] for g in recs if g['win'][1]]):8.2f} {mean([g['loss_all'] / g['all'][1] for g in recs if g['all'][1]]):7.2f} "
          f"{wins:2d}/{len(recs)}{'' if not ab else f' ab{ab}'} {r(br) if br[1] else float('nan'):14.1%}")
print()
for arm in sorted(arms):
    kw, ww, kp, wp = Counter(), Counter(), Counter(), Counter()
    for g in arms[arm].values():
        kw.update(g["kinds_win"]); ww.update(g["why_win"]); kp.update(g["kinds_post"]); wp.update(g["why_post"])
    print(f"{arm}: WIN kinds {dict(kw.most_common())} best_why {dict(ww.most_common())}")
    print(f"{' ' * len(arm)}  POST kinds {dict(kp.most_common())} best_why {dict(wp.most_common())}")
print()
if BASE in arms:
    for arm in sorted(arms):
        if arm == BASE:
            continue
        common = sorted(set(arms[arm]) & set(arms[BASE]))
        for label, key in (("own_W", "win"), ("own_all", "all"), ("opp_W", "opp_win")):
            d = [r(arms[arm][s][key]) - r(arms[BASE][s][key]) for s in common
                 if r(arms[arm][s][key]) is not None and r(arms[BASE][s][key]) is not None]
            if d:
                lo, hi = boot_ci(d)
                print(f"{arm} - {BASE} [{label}] n={len(d)} mean {st.mean(d):+.1%} 95%CI [{lo:+.1%}, {hi:+.1%}]")
        d = [arms[arm][s]["lead_w"] - arms[BASE][s]["lead_w"] for s in common
             if arms[arm][s]["lead_w"] is not None and arms[BASE][s]["lead_w"] is not None]
        if d:
            lo, hi = boot_ci(d)
            print(f"{arm} - {BASE} [leadW] n={len(d)} mean {st.mean(d):+.2f} 95%CI [{lo:+.2f}, {hi:+.2f}]")
