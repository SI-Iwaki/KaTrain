# -*- coding: utf-8 -*-
"""wide_cf と deep_cf は同じ (局, 手数, 手) を独立に撃っている = E と vloss の再現性（測定ノイズ）が測れる。

候補を増やして最大を選ぶと、ノイズのぶん予測 E は水増しされる（勝者の呪い）。ここでは
  1. 同じ手の E / vloss の 2 回の測定の相関と差の sd
  2. wide の値で選んだ手を deep の値で評価し直したときの目減り（両方にある手 = shortlist 内のみ）
  3. 選択が変わる手番の数（1 局あたり）と、変わった手番 1 回あたりの dE / dvloss
  4. プール外から選ばれた手の素性
を出す。KataGo は起動しない。標準出力は ASCII のみ。

    python docs/superpowers/specs/calibration-data/enigma-deep/wide_cf_noise.py
"""

import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["KIVY_NO_ARGS"] = "1"

import wide_cf_report as W  # noqa: E402


def deep_index():
    idx = {}
    for path in sorted(glob.glob(os.path.join(HERE, "rows", "game_*.json"))):
        game = os.path.basename(path)[:-5]
        for row in json.load(open(path, encoding="utf-8")):
            idx[(game, row["depth"])] = {c["gtp"]: c for c in row["cands"]}
    return idx


def main():
    settings, rows = W.load()
    deep = deep_index()
    n_games = len({r["game"] for r in rows})

    print("=== 1. test-retest of the same (game, depth, move): wide_cf vs deep_cf ===")
    pe, pv, pf = [], [], []
    for r in rows:
        d = deep.get((r["game"], r["depth"]))
        if not d:
            continue
        for m in r["moves"]:
            c = d.get(m["gtp"])
            if c is None or m["gtp"] == r["best"]:
                continue
            pe.append((m["e"], c["e"]))
            pv.append((m["vloss"], c["vloss"]))
            pf.append((m["find"], c["find"]))
    for name, p in (("E", pe), ("vloss", pv), ("find", pf)):
        a = np.array(p, dtype=float)
        diff = a[:, 0] - a[:, 1]
        print(
            "  %-5s n=%d corr %.3f  sd(diff) %.2f -> single-measurement noise sd %.2f  (sd of value %.2f)"
            % (name, len(a), np.corrcoef(a[:, 0], a[:, 1])[0, 1], diff.std(), diff.std() / np.sqrt(2), a[:, 0].std())
        )
    a = np.array(pe, dtype=float)
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 99)):
        s = a[(a[:, 0] >= lo) & (a[:, 0] < hi)]
        if len(s):
            print(
                "  wide E in [%d,%d): n=%4d  mean wide %.2f -> mean deep %.2f (regression to the mean %.0f%%)"
                % (lo, hi, len(s), s[:, 0].mean(), s[:, 1].mean(), 100 * (1 - s[:, 1].mean() / s[:, 0].mean()))
            )

    print("\n=== 2. winner's curse inside the shortlist: choose on wide values, re-read the pick on deep values ===")
    for name, sel in (("close", lambda r: r["cw"] >= 1.0), ("spend", lambda r: r["cw"] < 1.0), ("all", lambda r: True)):
        acc = []
        for r in rows:
            d = deep.get((r["game"], r["depth"]))
            if not d or not sel(r):
                continue
            c = W.choose(r, settings, {m["gtp"] for m in r["moves"] if m["in_shortlist"]})
            if c is None or c["gtp"] not in d:
                continue
            acc.append((c["e"], d[c["gtp"]]["e"], c["vloss"], d[c["gtp"]]["vloss"], c["gtp"] != r["best"]))
        a = np.array(acc, dtype=float)
        dev = a[a[:, 4] > 0]
        print(
            "  %-5s n=%3d  all picks: E wide %.2f -> deep %.2f | deviations only (n=%d): E wide %.2f -> deep %.2f, vloss wide %.2f -> deep %.2f"
            % (
                name,
                len(a),
                a[:, 0].mean(),
                a[:, 1].mean(),
                len(dev),
                dev[:, 0].mean() if len(dev) else 0,
                dev[:, 1].mean() if len(dev) else 0,
                dev[:, 2].mean() if len(dev) else 0,
                dev[:, 3].mean() if len(dev) else 0,
            )
        )

    print("\n=== 3. how often the pick changes when the candidate set widens (per game: x3 because EVERY=3) ===")
    variants = (
        ("ALL legal", lambda r: {m["gtp"] for m in r["moves"]}, {}),
        (
            "shortlist+screen16",
            lambda r: {m["gtp"] for m in r["moves"] if m["in_shortlist"]} | W.screen_members(r, settings, 16)[0],
            {},
        ),
        ("ALL legal, cw<=0.5", lambda r: {m["gtp"] for m in r["moves"]}, {"cw": 0.5}),
    )
    for name, sel in (("close", lambda r: r["cw"] >= 1.0), ("spend", lambda r: r["cw"] < 1.0)):
        rs = [r for r in rows if sel(r)]
        for vname, members, kw in variants:
            ch = []
            for r in rs:
                cur = W.choose(r, settings, {m["gtp"] for m in r["moves"] if m["in_shortlist"]})
                new = W.choose(r, settings, members(r), **kw)
                if cur is None or new is None or cur["gtp"] == new["gtp"]:
                    continue
                ch.append(
                    (
                        new["e"] - cur["e"],
                        new["vloss"] - cur["vloss"],
                        new["find"] - cur["find"],
                        not new["in_pool"],
                        cur["gtp"] == r["best"],
                    )
                )
            if not ch:
                print("  %-5s %-20s changed 0/%d" % (name, vname, len(rs)))
                continue
            a = np.array(ch, dtype=float)
            print(
                "  %-5s %-20s changed %2d/%3d turns (%.1f per game) | per change: dE %+.2f dvloss %+.2f dfind %+.2f | "
                "new pick outside pool %.0f%% | was best-move turn %.0f%% | dE/dvloss %.2f"
                % (
                    name,
                    vname,
                    len(a),
                    len(rs),
                    3.0 * len(a) / n_games,
                    a[:, 0].mean(),
                    a[:, 1].mean(),
                    a[:, 2].mean(),
                    100 * a[:, 3].mean(),
                    100 * a[:, 4].mean(),
                    a[:, 0].sum() / max(1e-9, a[:, 1].sum()),
                )
            )

    print("\n=== 4. what the outside-pool picks look like (ALL legal) ===")
    shown = 0
    stats = []
    for r in rows:
        cur = W.choose(r, settings, {m["gtp"] for m in r["moves"] if m["in_shortlist"]})
        new = W.choose(r, settings, {m["gtp"] for m in r["moves"]})
        if cur is None or new is None or new["in_pool"] or new["gtp"] == r["best"]:
            continue
        stats.append((new["own_hp"], new["kata_pol"] or 0.0, new["root_visits"], new["cov"], new["find"]))
        if shown < 14:
            shown += 1
            print(
                "  %s d%-2d lead %+5.1f cap %.1f cw %.2f | cur %-3s E %.2f vl %.2f | new %-3s E %.2f vl %.2f find %.2f "
                "own_hp %.3f kata_pol %.4f root_visits %d cov %.2f raw_loss %s"
                % (
                    r["game"][5:],
                    r["depth"],
                    r["lead"],
                    r["cap"],
                    r["cw"],
                    cur["gtp"],
                    cur["e"],
                    cur["vloss"],
                    new["gtp"],
                    new["e"],
                    new["vloss"],
                    new["find"],
                    new["own_hp"],
                    new["kata_pol"] or 0.0,
                    new["root_visits"],
                    new["cov"],
                    new["raw_loss"],
                )
            )
    if stats:
        a = np.array(stats, dtype=float)
        print(
            "  n=%d  median own_hp %.4f  median kata_pol %.5f  root_visits>0: %.0f%%  mean cov %.2f  mean find %.2f"
            % (
                len(a),
                np.median(a[:, 0]),
                np.median(a[:, 1]),
                100 * (a[:, 2] > 0).mean(),
                a[:, 3].mean(),
                a[:, 4].mean(),
            )
        )

    print("\n=== 5. lead distribution: how much of a game is close vs spending ===")
    leads = np.array([r["lead"] for r in rows])
    for lo, hi in ((-99, -3), (-3, 0), (0, 3), (3, 8), (8, 20), (20, 999)):
        s = [r for r in rows if lo <= r["lead"] < hi]
        if s:
            cur = [W.choose(r, settings, {m["gtp"] for m in r["moves"] if m["in_shortlist"]}) for r in s]
            cur = [c for c in cur if c]
            print(
                "  lead [%4d,%4d): turns %3d (%.0f%%)  cap %.1f cw %.2f | current pick E %.2f vloss %.2f"
                % (
                    lo,
                    hi,
                    len(s),
                    100.0 * len(s) / len(rows),
                    np.mean([r["cap"] for r in s]),
                    np.mean([r["cw"] for r in s]),
                    np.mean([c["e"] for c in cur]),
                    np.mean([c["vloss"] for c in cur]),
                )
            )
    print(
        "  lead median %.1f  p25 %.1f  p75 %.1f"
        % (np.median(leads), np.percentile(leads, 25), np.percentile(leads, 75))
    )


if __name__ == "__main__":
    main()
