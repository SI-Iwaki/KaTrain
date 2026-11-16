# -*- coding: utf-8 -*-
"""余裕外しの自己対局 A/B の読み方を確かめる補助集計（2026-11-16）。

    python relax_ab_split.py experiments/selfplay/<dir> [--base A] [--test B] [--big-lead 12]

KataGo の探索は非決定的なので、同じ seed でも両アームの棋譜は序盤で分かれる（1 節）。したがって対の差は
ほぼ run 間ノイズで、余裕外しの効果（1 局 1 回未満の差し替え）は対の差からは読めない。ここでは次を出す。

  1. 対ごとの分岐点・余裕外しの回数
  2. 「余裕外しが発動した対」と「しなかった対」の差。**発動した対は結果で選別した標本**（余裕外しは最善手に
     倒れた手番＝罠の少ない碁でしか発動しない）なので、発動した対の差を効果と読んではいけない。その検算として
     「最初の余裕外しより前」（両アームが同じコード経路）の差を並べる＝ここに出る差は選別の見かけ
  3. アーム内の直接効果（余裕外しの手を最善手へ戻したときの一致率＝会計上の値）
  4. 手番の種別の内訳
  5. 余裕外しの直後の罠（回数・E）を、**同じ碁**の「余裕外しでない best_race の直後」と比べる（局ごと）。
     全局プールの対照は碁ごとの罠の濃さの違いを拾うので参考値

標準出力は ASCII のみ。
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relax_ab_report import load_jsonl, mean, parse_log, se  # noqa: E402

TRAPS = ("deviate", "gamble", "overdraft")


def after(seq, i, h):
    """seq[i] の直後 h 手番の (手番数, 罠の回数, E の合計, E のある罠の回数)。"""
    nx = seq[i + 1 : i + 1 + h]
    tr = [t for t, _ in nx if t["kind"] in TRAPS]
    es = [t["e"] for t in tr if t.get("e") is not None]
    return len(nx), len(tr), sum(es), len(es)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--base", default="A")
    ap.add_argument("--test", default="B")
    ap.add_argument("--big-lead", type=float, default=12.0)
    args = ap.parse_args()
    d, base, test, big_lead = args.dir, args.base, args.test, args.big_lead

    games = {(g["arm"], g["seed"]): g for g in load_jsonl(os.path.join(d, "games.jsonl")) if not g.get("error")}
    allmoves, aimoves = defaultdict(dict), defaultdict(list)
    for m in load_jsonl(os.path.join(d, "moves.jsonl")):
        allmoves[(m["arm"], m["seed"])][m["depth"]] = m["move"]
        if m.get("is_ai") and not m.get("trailing_pass"):
            aimoves[(m["arm"], m["seed"])].append(m)
    seqs = {}
    for (arm, seed), g in games.items():
        p = os.path.join(d, "logs", f"{arm}_{seed}_{g['ai_color']}.log")
        tn = parse_log(p) if os.path.exists(p) else []
        mv = sorted(aimoves[(arm, seed)], key=lambda m: m["depth"])
        if len(tn) != len(mv):
            raise SystemExit(f"log / moves misaligned: {arm} {seed} ({len(tn)} vs {len(mv)})")
        seqs[(arm, seed)] = list(zip(tn, mv))

    def is_big(m):
        return (m.get("lead_before_ai") if m.get("lead_before_ai") is not None else -99.0) >= big_lead

    def stats(key, lo=0, hi=10**6):
        seq = [(t, m) for t, m in seqs[key] if lo <= m["depth"] < hi]
        big = [m for _, m in seq if is_big(m)]
        tr = [t for t, _ in seq if t["kind"] in TRAPS]
        return {
            "top1": mean([1.0 if m["match"] else 0.0 for _, m in seq]) if seq else None,
            "big_n": len(big),
            "big_top1": mean([1.0 if m["match"] else 0.0 for m in big]) if big else None,
            "traps": len(tr),
            "trap_e": sum(t["e"] for t in tr if t.get("e") is not None),
            "loss": mean([max(0.0, m["loss"]) for _, m in seq]) if seq else None,
        }

    seeds = sorted(s for (a, s) in games if a == base and (test, s) in games)
    first_relax = {s: next((m["depth"] for t, m in seqs[(test, s)] if t["kind"] == "relax"), None) for s in seeds}
    n_relax = {s: sum(1 for t, _ in seqs[(test, s)] if t["kind"] == "relax") for s in seeds}
    fired = [s for s in seeds if n_relax[s]]
    null = [s for s in seeds if not n_relax[s]]

    print("1) pairs")
    print("seed  first_diverge  first_relax  n_relax  top1 base -> test   traps base -> test")
    for s in seeds:
        a, b = allmoves[(base, s)], allmoves[(test, s)]
        div = next((dp for dp in sorted(set(a) | set(b)) if a.get(dp) != b.get(dp)), None)
        sa, sb = stats((base, s)), stats((test, s))
        print(
            f"{s}  {str(div):>13}  {str(first_relax[s]):>11}  {n_relax[s]:>7}  "
            f"{sa['top1']:.3f} -> {sb['top1']:.3f}        {sa['traps']:>3} -> {sb['traps']:>3}"
        )

    def diff(group, key, rng=None):
        xs = []
        for s in group:
            lo, hi = rng(s) if rng else (0, 10**6)
            x, y = stats((test, s), lo, hi)[key], stats((base, s), lo, hi)[key]
            if x is not None and y is not None:
                xs.append(x - y)
        return f"{mean(xs):+8.3f} (se {se(xs):.3f}, n {len(xs)})"

    print(f"\n2) paired diff ({test} - {base}); 'fired' pairs are selected on the outcome -> not an effect estimate")
    print(
        f"{'':<24} {'null pairs (no relax)':<28} {'fired pairs: whole game':<28} {'fired: BEFORE 1st relax':<28} fired: from 1st relax"
    )
    for label, key in (
        ("AI top1", "top1"),
        ("AI mean loss / move", "loss"),
        ("traps / game", "traps"),
        ("trap sum E / game", "trap_e"),
    ):
        print(
            f"{label:<24} {diff(null, key):<28} {diff(fired, key):<28} "
            f"{diff(fired, key, lambda s: (0, first_relax[s])):<28} {diff(fired, key, lambda s: (first_relax[s], 10**6))}"
        )
    print("   (BEFORE 1st relax both arms run the same code path: a diff there is selection, not relax)")

    print(f"\n3) direct effect inside arm {test} (relax moves counted back as matches; accounting, not measured)")
    tot_n = tot_match = tot_relax = 0
    for s in seeds:
        mv = [m for _, m in seqs[(test, s)]]
        n, match, k = len(mv), sum(1 for m in mv if m["match"]), n_relax[s]
        tot_n, tot_match, tot_relax = tot_n + n, tot_match + match, tot_relax + k
        if k:
            nonmatch = sum(1 for t, m in seqs[(test, s)] if t["kind"] == "relax" and not m["match"])
            print(
                f"  seed {s}: {k} relax ({nonmatch} non-match) / {n} AI moves  "
                f"top1 {100.0 * (match + nonmatch) / n:.1f}% -> {100.0 * match / n:.1f}%  ({-100.0 * nonmatch / n:+.1f} pt)"
            )
    fired_n = sum(len(seqs[(test, s)]) for s in fired)
    print(
        f"  pooled: {tot_relax} relax / {tot_n} AI moves ({-100.0 * tot_relax / tot_n:+.2f} pt)   "
        f"games with relax: {len(fired)}/{len(seeds)}, {tot_relax / max(1, len(fired)):.1f} relax/game, "
        f"{-100.0 * tot_relax / max(1, fired_n):+.1f} pt in those games"
    )

    print("\n4) turn kinds")
    for a in (base, test):
        c = Counter(t["kind"] for s in seeds for t, _ in seqs[(a, s)])
        n = sum(c.values())
        print(f"  arm {a} all (n={n}): " + "  ".join(f"{k}={v} ({100.0 * v / n:.1f}%)" for k, v in c.most_common()))
        c = Counter(t["kind"] for s in seeds for t, m in seqs[(a, s)] if is_big(m))
        n = sum(c.values())
        print(
            f"  arm {a} lead>={big_lead:g} (n={n}): "
            + "  ".join(f"{k}={v} ({100.0 * v / max(1, n):.1f}%)" for k, v in c.most_common())
        )

    print(
        f"\n5) traps right after a relax vs after a non-relax best_race at lead>={big_lead:g} in the SAME game (arm {test})"
    )
    for h in (3, 5):
        print(
            f"  horizon {h} AI turns: seed  relax: n turns / traps / sum E   same-game control: per-relax expectation traps / sum E (controls)"
        )
        tot = [0, 0, 0.0, 0.0, 0.0]
        pooled = [0.0, 0.0]
        for s in fired:
            seq = seqs[(test, s)]
            relax_i = [i for i, (t, _) in enumerate(seq) if t["kind"] == "relax"]
            ctrl = [
                i
                for i, (t, m) in enumerate(seq)
                if t["kind"] == "best_race" and is_big(m) and i + h < len(seq)
                # 余裕外しの直後 h 手番に重なる対照は除く（余裕外しの後の局面を対照に混ぜない）
                and not any(r < i + 1 + h and i <= r + h for r in relax_i)
            ]
            rn = rk = 0
            re_ = exp_k = exp_e = 0.0
            for i in relax_i:
                n, k, e, _ = after(seq, i, h)
                rn, rk, re_ = rn + n, rk + k, re_ + e
                if ctrl:
                    cs = [after(seq, j, h) for j in ctrl]
                    cn = sum(c[0] for c in cs)
                    exp_k += n * sum(c[1] for c in cs) / cn
                    exp_e += n * sum(c[2] for c in cs) / cn
                # 参考: 全局プール・深さ +-8 手の best_race（碁ごとの罠の濃さの違いを拾う）
                pn = pk = 0
                pe = 0.0
                dep = seq[i][1]["depth"]
                for q in seqs.values():
                    for j, (t2, m2) in enumerate(q):
                        if t2["kind"] == "best_race" and is_big(m2) and abs(m2["depth"] - dep) <= 8 and j + n < len(q):
                            n2, k2, e2, _ = after(q, j, n)
                            pn, pk, pe = pn + n2, pk + k2, pe + e2
                if pn:
                    pooled[0] += n * pk / pn
                    pooled[1] += n * pe / pn
            print(
                f"    {s}  {len(relax_i)} relax: {rn} / {rk} / {re_:.1f}   "
                + (f"control: {exp_k:.1f} / {exp_e:.1f} ({len(ctrl)})" if ctrl else "control: none")
            )
            if ctrl:
                tot = [tot[0] + rn, tot[1] + rk, tot[2] + re_, tot[3] + exp_k, tot[4] + exp_e]
        print(
            f"    total (games with a control): after relax {tot[1]} traps / sum E {tot[2]:.1f} in {tot[0]} turns   "
            f"same-game expectation {tot[3]:.1f} traps / sum E {tot[4]:.1f}"
        )
        print(f"    reference, all-games depth-matched control: {pooled[0]:.1f} traps / sum E {pooled[1]:.1f}")
        fe = [t["e"] for s in fired for t, _ in seqs[(test, s)] if t["kind"] in TRAPS and t.get("e") is not None]
        ae = [t["e"] for q in seqs.values() for t, _ in q if t["kind"] in TRAPS and t.get("e") is not None]
        print(f"    mean E per trap: fired games (arm {test}) {mean(fe):.2f}   all games {mean(ae):.2f}")


if __name__ == "__main__":
    main()
