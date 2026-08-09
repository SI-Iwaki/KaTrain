"""スイープ／検証の結果を集計する（`answer_book_replay.py` / `answer_book_verify.py` の出力）。

ユーザーの2つの仮説を数値で検定するのが主目的:

  仮説1「有力手が候補に出てこない」  -> 不一致手番で正解手が候補プールに居たか、
                                        居たなら visits / policy 順位はどこか
  仮説2「白死の判定が薄れる」        -> 検証パスの own_after_want vs own_after_chosen

usage:
  python docs/superpowers/specs/calibration-data/tsumego/answer_book_summary.py \
      [--in PATH] [--verify PATH]

ASCII output only。
"""
import argparse
import collections
import json
import os


def load(path):
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for raw in f:
            try:
                rows.append(json.loads(raw))
            except Exception:
                pass
    return rows


def pct(a, b):
    return f"{100.0 * a / b:.1f}%" if b else "-"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(here, "answer-book-replay-results.jsonl"))
    ap.add_argument("--verify", default=os.path.join(here, "answer-book-verify-results.jsonl"))
    args = ap.parse_args()

    rows = load(args.inp)
    print(f"=== sweep: {len(rows)} lines replayed ===")
    verdicts = collections.Counter(r.get("verdict") for r in rows)
    for k, v in verdicts.most_common():
        print(f"  {k:16s} {v:4d}  {pct(v, len(rows))}")
    routes = collections.Counter(r.get("route") for r in rows)
    print("  routes:", dict(routes))
    print("\n  route x verdict:")
    cross = collections.Counter((r.get("route"), r.get("verdict")) for r in rows)
    for route in sorted(routes, key=lambda x: str(x)):
        tot = routes[route]
        ok = cross[(route, "correct")]
        print(f"    {str(route):10s} n={tot:4d} correct={ok:4d} ({pct(ok, tot)})")

    mism = [r for r in rows if r.get("verdict") == "mismatch"]
    if mism:
        print(f"\n=== H1: was the recorded move in the candidate pool? (n={len(mism)} mismatched decisions) ===")
        bad = [r["decisions"][-1] for r in mism]
        in_pool = sum(1 for d in bad if d.get("want_in_pool"))
        print(f"  want_in_pool     : {in_pool}/{len(bad)}  ({pct(in_pool, len(bad))})")
        passes = sum(1 for d in bad if d.get("want_passes_min_visits"))
        print(f"  passes min_visits: {passes}/{len(bad)}  ({pct(passes, len(bad))})")
        vr = collections.Counter(
            "not in pool" if d.get("want_visit_rank") is None else _bucket(d["want_visit_rank"]) for d in bad
        )
        pr = collections.Counter(
            "not in pool" if d.get("want_prior_rank") is None else _bucket(d["want_prior_rank"]) for d in bad
        )
        print(f"  recorded move visits rank: {dict(sorted(vr.items()))}")
        print(f"  recorded move policy rank: {dict(sorted(pr.items()))}")
        gaps = [
            d["want_cand"]["pointsLost"] - d["chosen_cand"]["pointsLost"]
            for d in bad
            if isinstance(d.get("want_cand"), dict) and isinstance(d.get("chosen_cand"), dict)
        ]
        if gaps:
            gaps.sort()
            near = sum(1 for g in gaps if abs(g) <= 0.25)
            print(
                f"  pointsLost gap (want-chosen): median {gaps[len(gaps) // 2]:+.2f} / "
                f"|gap|<=0.25: {near}/{len(gaps)} ({pct(near, len(gaps))}) within tie band"
            )
        depths = collections.Counter(d["depth"] for d in bad)
        print(f"  mismatch depth     : {dict(sorted(depths.items()))}")

    ver = load(args.verify)
    if ver:
        print(f"\n=== H2: verify pass, n={len(ver)} (role-stone same-depth ownership) ===")
        classes = collections.Counter(v.get("class") for v in ver)
        for k, n in classes.most_common():
            print(f"  {k:14s} {n:4d}  {pct(n, len(ver))}")
        deltas = [v["delta_want_minus_chosen"] for v in ver if v.get("delta_want_minus_chosen") is not None]
        if deltas:
            deltas.sort()
            pos = sum(1 for d in deltas if d > 0)
            print(
                f"\n  delta = own(want) - own(chosen): n={len(deltas)} median {deltas[len(deltas) // 2]:+.3f}"
                f" / positive {pos}/{len(deltas)} ({pct(pos, len(deltas))})"
            )
            print("  (higher = supports 'the correct move keeps the opponent-dead reading stronger')")
        true_miss = [v for v in ver if v.get("class") == "true_miss"]
        if true_miss:
            print(f"\n  true_miss {len(true_miss)} cases:")
            print("   ", dict(collections.Counter(v.get("route") for v in true_miss)))
            print("    role:", dict(collections.Counter(str(v.get("solver_attacks")) for v in true_miss)))
            ranks = collections.Counter(
                "not in pool" if v.get("want_visit_rank") is None else _bucket(v["want_visit_rank"])
                for v in true_miss
            )
            print("    recorded move visits rank:", dict(sorted(ranks.items())))


def _bucket(rank):
    if rank == 0:
        return "0 (top visits)"
    if rank <= 2:
        return "1-2"
    if rank <= 5:
        return "3-5"
    if rank <= 10:
        return "6-10"
    return "11+"


main()
