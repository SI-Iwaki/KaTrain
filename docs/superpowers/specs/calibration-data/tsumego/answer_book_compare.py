"""2本の answer-book replay JSONL を (key,line_index) で対にして 回復/破損 を数える（ASCII出力）。
usage: compare_replays.py <base.jsonl> <new.jsonl> [--list]
"""
import json, sys, collections
def load(p):
    d = {}
    for l in open(p, encoding="utf-8"):
        if not l.strip(): continue
        r = json.loads(l); d[(r["key"], r.get("line_index", 0))] = r
    return d
base, new = load(sys.argv[1]), load(sys.argv[2])
common = sorted(set(base) & set(new))
c = collections.Counter()
broken, recovered = [], []
for k in common:
    b, n = base[k]["verdict"] == "correct", new[k]["verdict"] == "correct"
    c[("base_ok" if b else "base_ng", "new_ok" if n else "new_ng")] += 1
    if b and not n: broken.append(k)
    if n and not b: recovered.append(k)
print(f"paired lines: {len(common)}  (base total {len(base)} / new total {len(new)})")
print(f"base correct {sum(1 for k in common if base[k]['verdict']=='correct')}  new correct {sum(1 for k in common if new[k]['verdict']=='correct')}")
for kk, v in sorted(c.items()): print("  ", kk, v)
print(f"broken (base ok -> new ng): {len(broken)}   recovered (base ng -> new ok): {len(recovered)}")
by_route = collections.Counter((new[k]["route"], "broken") for k in broken) + collections.Counter((new[k]["route"], "recovered") for k in recovered)
print("  by route:", dict(by_route))
def first_miss(r):
    for d in r.get("decisions", []):
        if not d.get("match"):
            return d
    return None
if "--list" in sys.argv:
    for tag, lst in (("BROKEN", broken), ("RECOVERED", recovered)):
        print(f"\n=== {tag} ({len(lst)})")
        for k in lst:
            r = new[k] if tag == "BROKEN" else base[k]
            d = first_miss(r) or {}
            wc = d.get("want_cand") or {}; cc = d.get("chosen_cand") or {}
            print(f"{k[0][:10]} l{k[1]} route={new[k]['route']:<9} d{d.get('depth')} want={d.get('want')}(v{wc.get('visits')},pt{(wc.get('pointsLost') or 0):+.1f}) chosen={d.get('chosen')}(v{cc.get('visits')},pt{(cc.get('pointsLost') or 0):+.1f}) decider={d.get('decider')} n_black={r.get('n_black_decisions')}")
