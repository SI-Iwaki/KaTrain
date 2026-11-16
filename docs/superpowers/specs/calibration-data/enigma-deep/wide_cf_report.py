# -*- coding: utf-8 -*-
"""wide_cf.py の集計: 候補プールの外の罠の在庫と、安いふるい（SCREEN_VISITS）の精度（2026-11-16）。

    python docs/superpowers/specs/calibration-data/enigma-deep/wide_cf_report.py

KataGo は起動しない。標準出力は ASCII のみ。
"""

import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core import ai  # noqa: E402
from katrain.core.game import KaTrainSGF, Move  # noqa: E402

ROWS = os.path.join(HERE, "wide_rows")
RECON = os.path.join(HERE, "..", "selfplay", "recon")
PRE = "enigma13plus_"


def load():
    settings = json.load(open(os.path.join(ROWS, "_settings.json"), encoding="utf-8"))
    out = []
    for path in sorted(glob.glob(os.path.join(ROWS, "game_*.json"))):
        game = os.path.basename(path)[:-5]
        root = KaTrainSGF.parse_file(os.path.join(RECON, game + ".sgf"))
        last, n = {}, root
        while n.children:
            n = n.children[0]
            last[n.depth] = n.move.coords if (n.move and not n.move.is_pass) else None
        for row in json.load(open(path, encoding="utf-8")):
            row["last_coords"] = last.get(row["depth"])
            out.append(row)
    return settings, out


def verified(row, settings, m, cap=None):
    if m["gtp"] == row["best"]:
        return True
    cap = row["cap"] if cap is None else cap
    return m["vloss"] <= cap and (m["wr_after"] is None or m["wr_after"] >= float(settings[PRE + "min_winrate"]))


def choose(row, settings, members, cw=None, w_own=1.0, cap=None):
    """難解＋の選択則（net・dE 床・局所性の同点帯）を members（gtp の集合・最善手は常に含む）に適用。"""
    sd = float(settings[PRE + "locality_stddev"] or 0.0)
    best = row["best"]
    anchors = ai.enigma9_anchors(row["last_coords"], best) if sd > 0 else []
    w = row["cw"] if cw is None else min(row["cw"], cw)
    scored = []
    for m in row["moves"]:
        if m["gtp"] != best and (m["gtp"] not in members or not verified(row, settings, m, cap)):
            continue
        prox = ai.enigma9_locality(Move.from_gtp(m["gtp"]).coords, anchors, sd)
        net = ai.enigma9_net_score(
            m["vloss"], m["e"], m["find"], m["own_hp"], w_own=w_own, cost_weight=w, locality=prox
        )
        scored.append({**m, "loss": m["vloss"], "net": net, "prox": prox})
    if not any(c["gtp"] == best for c in scored):
        return None
    kept, _ = ai.enigma9_delta_e_filter(
        scored, best, float(settings[PRE + "min_delta_e"]), float(settings[PRE + "cheap_loss"])
    )
    chosen, _ = ai.enigma9_choose_local(kept, best, 0.0, float(settings[PRE + "locality_slack"]), sd)
    return chosen if chosen is not None else next(c for c in scored if c["gtp"] == best)


def screen_members(row, settings, n_full, margin=1.0, rank="net"):
    """2 段階の探索: ふるい（40v）で上限 + margin 以内の手を、ふるいの値の順に n_full 手だけ本プローブする想定。"""
    min_wr = float(settings[PRE + "min_winrate"])
    surv = []
    for m in row["moves"]:
        if m["gtp"] == row["best"] or m["in_shortlist"] or m["s_vloss"] is None:
            continue
        if m["s_vloss"] > row["cap"] + margin or (m["s_wr"] is not None and m["s_wr"] < min_wr - 0.05):
            continue
        if rank == "net":
            key = (m["s_e"] or 0.0) - row["cw"] * max(0.0, m["s_vloss"])
        elif rank == "e":
            key = m["s_e"] or 0.0
        elif rank == "find":
            key = -(m["s_find"] if m["s_find"] is not None else 1.0)
        else:
            key = -max(0.0, m["s_vloss"])
        surv.append((key, m["gtp"]))
    surv.sort(reverse=True)
    return {g for _k, g in surv[:n_full]}, len(surv)


def main():
    settings, rows = load()
    games = {r["game"] for r in rows}
    print("turns %d games %d  secs/turn median %.0f" % (len(rows), len(games), np.median([r["secs"] for r in rows])))
    modes = (("close", lambda r: r["cw"] >= 1.0), ("spend", lambda r: r["cw"] < 1.0), ("all", lambda r: True))

    print("\n=== inventory: verified-admissible moves (vloss <= cap, wr >= floor), inside vs outside the pool ===")
    for name, sel in modes:
        rs = [r for r in rows if sel(r)]
        if not rs:
            continue
        ins, outs, big_in, big_out, pos_in, pos_out, nopool, nopool_has = [], [], [], [], [], [], 0, 0
        for r in rs:
            best_e = next((m["e"] for m in r["moves"] if m["gtp"] == r["best"]), 0.0)
            ok = [m for m in r["moves"] if m["gtp"] != r["best"] and verified(r, settings, m)]
            i = [m for m in ok if m["in_pool"]]
            o = [m for m in ok if not m["in_pool"]]
            ins.append(len(i))
            outs.append(len(o))
            big_in.append(sum(1 for m in i if m["e"] >= 2.0))
            big_out.append(sum(1 for m in o if m["e"] >= 2.0))
            pos_in.append(sum(1 for m in i if m["e"] - best_e - max(0.0, m["vloss"]) >= 0.5))
            pos_out.append(sum(1 for m in o if m["e"] - best_e - max(0.0, m["vloss"]) >= 0.5))
            if r["n_pool"] == 0:
                nopool += 1
                nopool_has += bool(o)
        print(
            "  %-5s turns %3d | admissible in-pool %.1f / outside %.1f per turn | E>=2: in %.2f / out %.2f | "
            "dE - vloss >= 0.5: in %.2f / out %.2f | pool-empty turns %d (of which outside has admissible: %d)"
            % (
                name,
                len(rs),
                np.mean(ins),
                np.mean(outs),
                np.mean(big_in),
                np.mean(big_out),
                np.mean(pos_in),
                np.mean(pos_out),
                nopool,
                nopool_has,
            )
        )

    print("\n=== policy table (same selection rule, different candidate sets): per-turn means of the chosen move ===")
    for name, sel in modes:
        rs = [r for r in rows if sel(r)]
        if not rs:
            continue
        variants = [
            ("best move", lambda r: set(), {}),
            ("current (shortlist)", lambda r: {m["gtp"] for m in r["moves"] if m["in_shortlist"]}, {}),
            ("whole pool", lambda r: {m["gtp"] for m in r["moves"] if m["in_pool"]}, {}),
            ("ALL legal", lambda r: {m["gtp"] for m in r["moves"]}, {}),
            ("ALL legal, no own_rare", lambda r: {m["gtp"] for m in r["moves"]}, {"w_own": 0.0}),
            ("ALL legal, cw<=0.5", lambda r: {m["gtp"] for m in r["moves"]}, {"cw": 0.5}),
            ("ALL, cw<=0.5, no own", lambda r: {m["gtp"] for m in r["moves"]}, {"cw": 0.5, "w_own": 0.0}),
        ]
        for n_full in (8, 16, 24, 40):
            for rank in ("net", "e"):
                variants.append(
                    (
                        "shortlist+screen%d(%s)" % (n_full, rank),
                        (
                            lambda r, n_full=n_full, rank=rank: {m["gtp"] for m in r["moves"] if m["in_shortlist"]}
                            | screen_members(r, settings, n_full, rank=rank)[0]
                        ),
                        {"w_own": 0.0},
                    )
                )
        base = None
        for vname, members, kw in variants:
            acc = []
            for r in rs:
                c = choose(r, settings, members(r), **kw)
                if c is None:
                    continue
                acc.append(
                    (
                        c["e"],
                        c["vloss"],
                        c["gtp"] != r["best"],
                        c["find"],
                        c["own_hp"],
                        not c["in_pool"] and c["gtp"] != r["best"],
                        c["e_fooled"] * c["p_fooled"],
                    )
                )
            a = np.array(acc, dtype=float)
            if vname.startswith("current"):
                base = a[:, 0].mean()
            print(
                "  %-5s %-26s n=%3d E1 %.2f%s vloss %.2f dev %.0f%% find %.2f own_hp %.3f picked-outside-pool %.0f%%"
                % (
                    name,
                    vname,
                    len(a),
                    a[:, 0].mean(),
                    "" if base is None else " (%+.0f%%)" % (100.0 * (a[:, 0].mean() / base - 1.0)),
                    a[:, 1].mean(),
                    100 * a[:, 2].mean(),
                    a[:, 3].mean(),
                    a[:, 4].mean(),
                    100 * a[:, 5].mean(),
                )
            )

    print("\n=== screen (40v): survivors per turn and error of the screen loss ===")
    surv = [screen_members(r, settings, 10**6)[1] for r in rows]
    err = [
        m["s_vloss"] - m["vloss"]
        for r in rows
        for m in r["moves"]
        if m["s_vloss"] is not None and m["vloss"] <= r["cap"] + 2
    ]
    print(
        "  survivors (s_vloss <= cap+1, not in shortlist): median %d p75 %d max %d | screen - verified loss: mean %+.2f sd %.2f"
        % (np.median(surv), np.percentile(surv, 75), max(surv), np.mean(err), np.std(err))
    )
    miss = tot = 0
    for r in rows:
        for m in r["moves"]:
            if m["gtp"] != r["best"] and not m["in_shortlist"] and verified(r, settings, m) and m["e"] >= 1.5:
                tot += 1
                miss += m["s_vloss"] is None or m["s_vloss"] > r["cap"] + 1.0
    print("  verified traps (E>=1.5) outside the shortlist: %d, cut by the screen: %d" % (tot, miss))


if __name__ == "__main__":
    main()
