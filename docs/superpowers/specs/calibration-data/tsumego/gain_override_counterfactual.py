"""debug_capture の出力から各黒番の gain順/目数順/Final decision を抜き、chosen と visits 最多手の gain 差を出す。
usage: parse_gain_logs.py <dbg_dir> <sweep.jsonl>
gain順/目数順は上位5手しか出ないので、載っていない手の gain は「5位以下」＝上界として扱う（lb フラグ）。"""
import json, os, re, sys, glob, collections
D, SWEEP = sys.argv[1], sys.argv[2]
sweep = {}
for l in open(SWEEP, encoding="utf-8"):
    if l.strip():
        r = json.loads(l); sweep[r["key"][:10]] = r
CAND = re.compile(r"([A-T][0-9]{1,2})\(v(\d+)/([0-9.]+) pt([+-][0-9.]+) g([+-][0-9.]+)\)")
GAINL = re.compile(r"\] gain[^:\n]{0,6}: (.*)$")
PTSL = re.compile(r"\] [^\[\]\n]{0,6}: ([A-T][0-9]{1,2}\(v\d+/[0-9.]+ pt[+-][0-9.]+ g[+-][0-9.]+\).*)$")
FINAL = re.compile(r"Final decision: ([A-T][0-9]{1,2}|pass) \((.*?)\)")
out = []
for f in sorted(glob.glob(os.path.join(D, "*.txt"))):
    key = os.path.basename(f)[:10]; r = sweep.get(key)
    if not r: continue
    cands = {}; blocks = []
    for line in open(f, encoding="utf-8", errors="replace"):
        m = GAINL.search(line) or PTSL.search(line)
        if m and "(v" in line and "Final decision" not in line:
            for c in CAND.findall(m.group(1)):
                cands.setdefault(c[0], dict(v=int(c[1]), pt=float(c[3]), g=float(c[4])))
            continue
        m = FINAL.search(line)
        if m:
            blocks.append((cands, m.group(1), m.group(2))); cands = {}
    decs = r["decisions"]
    for i, (cands, final_move, inside) in enumerate(blocks):
        if i >= len(decs): break
        d = decs[i]
        if final_move != d["chosen"] or d.get("decider") != "gain" or d.get("chosen_visit_rank") == 0: continue
        top = (d.get("top_by_visits") or [{}])[0].get("move")
        ci, ti = cands.get(d["chosen"]), cands.get(top)
        fifth = min((c["g"] for c in cands.values()), default=None)
        out.append(dict(key=key, depth=d["depth"], want=d["want"], chosen=d["chosen"], top=top, match=d["match"], want_rank=d.get("want_visit_rank"),
                        g_chosen=ci["g"] if ci else None, g_top=ti["g"] if ti else None, g_top_ub=fifth if (ti is None and fifth is not None) else None,
                        pt_chosen=ci["pt"] if ci else None, pt_top=ti["pt"] if ti else None, inside=inside[:40]))
hurt = [o for o in out if not o["match"] and o["want_rank"] == 0]; help_ = [o for o in out if o["match"]]
print(f"override gain decisions parsed: {len(out)}  HURT {len(hurt)} / help {len(help_)} / other-miss {len(out)-len(hurt)-len(help_)}")
def dg(o):
    if o["g_chosen"] is None: return None, ""
    if o["g_top"] is not None: return o["g_chosen"] - o["g_top"], ""
    if o["g_top_ub"] is not None: return o["g_chosen"] - o["g_top_ub"], ">="
    return None, ""
for tag, lst in (("HURT", hurt), ("HELP", help_)):
    print(f"\n=== {tag}")
    for o in lst:
        v, lb = dg(o)
        print(f"{o['key']} d{o['depth']} want={o['want']} chosen={o['chosen']} top={o['top']} dGain(chosen-top)={lb}{'?' if v is None else round(v,2)} g_chosen={o['g_chosen']} pt_chosen={o['pt_chosen']} pt_top={o['pt_top']} [{o['inside']}]")
print("\n=== counterfactual: gain_epsilon=E なら chosen が top を E 以内しか上回らない判断は top へ戻る（下界つきは最小値で判定）")
for E in (0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0):
    fh = sum(1 for o in hurt if (dg(o)[0] is not None) and 0 < dg(o)[0] <= E)
    fl = sum(1 for o in help_ if (dg(o)[0] is not None) and 0 < dg(o)[0] <= E)
    print(f"  E={E}: HURT flipped back {fh:>3}  help lost {fl:>3}  net {fh-fl:+d}")

print("\n=== counterfactual: points_epsilon=P（gain 同着 |dGain|<=0.3 のとき、chosen の目数優位 (pt_top-pt_chosen) が P 以内なら visits 最多手へ戻る）")
def pt_adv(o):
    if o["pt_chosen"] is None or o["pt_top"] is None: return None
    return o["pt_top"] - o["pt_chosen"]
for P in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
    def flips(lst):
        n = 0
        for o in lst:
            v, _ = dg(o); a = pt_adv(o)
            if v is None or a is None: continue
            if abs(v) <= 0.3 and 0 < a <= P: n += 1
        return n
    fh, fl = flips(hurt), flips(help_)
    print(f"  P={P}: HURT flipped back {fh:>3}  help lost {fl:>3}  net {fh-fl:+d}")
n_gt = sum(1 for o in hurt if dg(o)[0] is not None and pt_adv(o) is not None and abs(dg(o)[0]) <= 0.3 and pt_adv(o) > 0)
print(f"HURT with gain-tie and chosen better by points: {n_gt}/{len(hurt)}; help same: {sum(1 for o in help_ if dg(o)[0] is not None and pt_adv(o) is not None and abs(dg(o)[0]) <= 0.3 and pt_adv(o) > 0)}/{len(help_)}")
