# -*- coding: utf-8 -*-
"""難解＋の余裕外し（relax）の自己対局 A/B の集計（2026-11-16）。

    python relax_ab_report.py experiments/selfplay/<dir> [<dir2> ...] [--base A] [--test B] [--big-lead 12]

games.jsonl（局ごとのレポート）・moves.jsonl（1手1行）・logs/<arm>_<seed>_<color>.log（戦略の [XxxStrategy] 行）から、
アームごとに 勝敗・一致率・損失・罠（Deviate / Gamble / Overdraft）の回数と E・余裕外し（Relax）の回数と中身を並べ、
同じ seed の対の差（test − base）を出す。標準出力は ASCII のみ。
"""

import argparse
import json
import math
import os
import re
from collections import defaultdict

RE_DEV = re.compile(r"Deviate: played (\S+) \(net=([-\d.]+), vloss=([-\d.]+), E=([-\d.]+)")
RE_GAMBLE = re.compile(r"Gamble: played (\S+) \(dE=([-+\d.]+), vloss=([-\d.]+)")
RE_OVER = re.compile(r"Overdraft: played (\S+) .*vloss=([-\d.]+), E=([-\d.]+)")
RE_RELAX = re.compile(
    r"Relax: played (\S+) \(vloss=([-\d.]+), own_hp=([-\d.]+), E=([-\d.]+), dE=([-+\d.]+), wr=([\d.]+)%\) "
    r"instead of (\S+) \(best own_hp=([-\d.]+), E=([-\d.]+)\)"
)
RE_SCORE_BEST = re.compile(r"Score (\S+): vloss=0\.00 .* E=([-\d.]+) ")


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_log(path):
    """1 局のログ → AI の手番ごとの {kind, gtp, vloss, e, ...}（着手決定の行で区切る）。"""
    turns, cur = [], {"kind": "best"}
    with open(path, "rb") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace")
            if "Strategy] " not in line:
                continue
            m = RE_DEV.search(line)
            if m:
                cur = {"kind": "deviate", "gtp": m.group(1), "vloss": float(m.group(3)), "e": float(m.group(4))}
            m = RE_GAMBLE.search(line)
            if m:
                cur = {"kind": "gamble", "gtp": m.group(1), "vloss": float(m.group(3)), "e": None}
            m = RE_OVER.search(line)
            if m:
                cur = {"kind": "overdraft", "gtp": m.group(1), "vloss": float(m.group(2)), "e": float(m.group(3))}
            m = RE_RELAX.search(line)
            if m:
                cur = {
                    "kind": "relax",
                    "gtp": m.group(1),
                    "vloss": float(m.group(2)),
                    "own_hp": float(m.group(3)),
                    "e": float(m.group(4)),
                    "de": float(m.group(5)),
                    "best": m.group(7),
                    "best_hp": float(m.group(8)),
                }
            if "Opening handoff" in line:
                cur = {"kind": "opening9d"}
            if "Best move wins the confusion race" in line:
                cur = {"kind": "best_race"}
            if "着手決定に" in line:  # 着手決定に
                turns.append(cur)
                cur = {"kind": "best"}
    return turns


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def se(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1) / len(xs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--base", default="A")
    ap.add_argument("--test", default="B")
    ap.add_argument("--big-lead", type=float, default=12.0)
    args = ap.parse_args()

    games, moves, logs = [], defaultdict(list), {}
    for d in args.dirs:
        for g in load_jsonl(os.path.join(d, "games.jsonl")):
            if g.get("error"):
                continue
            games.append(g)
            p = os.path.join(d, "logs", f"{g['arm']}_{g['seed']}_{g['ai_color']}.log")
            logs[(g["arm"], g["seed"])] = parse_log(p) if os.path.exists(p) else []
        for m in load_jsonl(os.path.join(d, "moves.jsonl")):
            if m.get("is_ai") and not m.get("trailing_pass"):
                moves[(m["arm"], m["seed"])].append(m)

    per = defaultdict(dict)  # arm -> seed -> stats
    relax_rows = []
    for g in games:
        key = (g["arm"], g["seed"])
        mv = sorted(moves[key], key=lambda m: m["depth"])
        turns = logs[key]
        aligned = len(turns) == len(mv)
        big = [m for m in mv if m.get("lead_before_ai") is not None and m["lead_before_ai"] >= args.big_lead]
        traps = [t for t in turns if t["kind"] in ("deviate", "gamble", "overdraft")]
        relax = [t for t in turns if t["kind"] == "relax"]
        st = {
            "win": 1.0 if g["result"] == "win" else 0.0,
            "final_lead": g.get("final_lead"),
            "n": len(mv),
            "top1": mean([1.0 if m["match"] else 0.0 for m in mv]),
            "loss": mean([max(0.0, m["loss"]) for m in mv]),
            "opp_top1": g.get("opp_top1"),
            "opp_loss": g.get("opp_mean_ptloss"),
            "big_n": len(big),
            "big_top1": mean([1.0 if m["match"] else 0.0 for m in big]) if big else None,
            "big_match": sum(1 for m in big if m["match"]),
            "big_loss": mean([max(0.0, m["loss"]) for m in big]) if big else None,
            "traps": len(traps),
            "trap_e": sum(t["e"] for t in traps if t.get("e") is not None),
            "trap_vloss": sum(max(0.0, t["vloss"]) for t in traps),
            "deviate": sum(1 for t in turns if t["kind"] == "deviate"),
            "relax": len(relax),
            "relax_vloss": sum(max(0.0, t["vloss"]) for t in relax),
            "hp_dev_median": g.get("hp_dev_median"),
            "hp_dev_lt5": g.get("hp_dev_lt5"),
            "aligned": aligned,
        }
        per[g["arm"]][g["seed"]] = st
        if aligned:
            for t, m in zip(turns, mv):
                if t["kind"] == "relax":
                    relax_rows.append((g["arm"], g["seed"], m["depth"], t, m))

    def line(label, key, fmt="{:.3f}", arms=(args.base, args.test)):
        vals = []
        for a in arms:
            xs = [s[key] for s in per[a].values()]
            vals.append((mean(xs), se(xs)))
        seeds = sorted(set(per[arms[0]]) & set(per[arms[1]]))
        diffs = [
            per[arms[1]][s][key] - per[arms[0]][s][key]
            for s in seeds
            if per[arms[0]][s][key] is not None and per[arms[1]][s][key] is not None
        ]
        d, dse = mean(diffs), se(diffs)
        z = d / dse if dse and not math.isnan(dse) and dse > 0 else float("nan")
        cells = "  ".join((fmt + " (se " + fmt + ")").format(v, e) for v, e in vals)
        print(f"{label:<34} {cells}   paired diff {fmt.format(d)} (se {fmt.format(dse)}, z {z:+.2f}, n {len(diffs)})")

    print(f"arms: base={args.base} ({len(per[args.base])} games)  test={args.test} ({len(per[args.test])} games)")
    print(f"aligned logs: {sum(s['aligned'] for a in per for s in per[a].values())}/{len(games)}")
    print(f"{'metric':<34} {args.base:<22} {args.test:<22}")
    line("win rate", "win")
    line("final lead", "final_lead", "{:.2f}")
    line("AI moves / game", "n", "{:.1f}")
    line("AI top1 (per game)", "top1")
    line("AI mean loss / move", "loss")
    line("opp top1 (per game)", "opp_top1")
    line("opp mean loss / move", "opp_loss")
    line(f"AI moves at lead>={args.big_lead:g} / game", "big_n", "{:.1f}")
    line(f"AI top1 at lead>={args.big_lead:g} (per game)", "big_top1")
    line(f"AI loss at lead>={args.big_lead:g} / move", "big_loss")
    line("traps / game (dev+gamble+over)", "traps", "{:.2f}")
    line("deviate / game", "deviate", "{:.2f}")
    line("trap sum E / game", "trap_e", "{:.2f}")
    line("trap sum vloss / game", "trap_vloss", "{:.2f}")
    line("relax / game", "relax", "{:.2f}")
    line("relax sum vloss / game", "relax_vloss", "{:.2f}")
    line("hp of deviations: median", "hp_dev_median")
    line("hp of deviations: share < 5%", "hp_dev_lt5")

    for a in (args.base, args.test):
        tot = sum(s["big_n"] for s in per[a].values())
        hit = sum(s["big_match"] for s in per[a].values())
        print(f"pooled top1 at lead>={args.big_lead:g}: arm {a} {hit}/{tot} = {100.0 * hit / max(1, tot):.1f}%")

    print(f"\nrelax moves: {len(relax_rows)}")
    if relax_rows:
        nonmatch = sum(1 for *_, m in relax_rows if not m["match"])
        print(
            f"  counted as non-match in the report: {nonmatch}/{len(relax_rows)}"
            f"  mean verified loss {mean([max(0.0, t['vloss']) for _, _, _, t, _ in relax_rows]):.2f}"
            f"  mean report loss {mean([max(0.0, m['loss']) for *_, m in relax_rows]):.2f}"
            f"  mean own_hp {mean([t['own_hp'] for _, _, _, t, _ in relax_rows]):.3f}"
            f"  mean best_hp {mean([t['best_hp'] for _, _, _, t, _ in relax_rows]):.3f}"
            f"  mean dE {mean([t['de'] for _, _, _, t, _ in relax_rows]):+.2f}"
        )
        for arm, seed, depth, t, m in relax_rows:
            print(
                f"  {arm} seed {seed} move {depth:3d}: {t['best']}({t['best_hp']:.2f}) -> {t['gtp']}({t['own_hp']:.2f}) "
                f"vloss {t['vloss']:+.2f} report_loss {m['loss']:+.2f} dE {t['de']:+.2f} "
                f"lead {m.get('lead_before_ai', float('nan')):.1f} match={m['match']} report_best={m.get('best')}"
            )


if __name__ == "__main__":
    main()
