# -*- coding: utf-8 -*-
"""難解++ の go/no-go: 各レバーの「1 局あたりの損得」を実戦の値に換算して並べる（2026-11-16）。

  A. E -> 実戦の相手の損失 の傾きは、人間が打たない手（own_hp が低い）・見つけにくい罠（find が低い）
     でも保たれているか（deep_cf の実着手で層別）。プール外の手は own_hp ~ 0 なので、ここが保たれて
     いなければ「全合法手」の上積みは検証できない外挿。
  B. 統合表: 現行 / 価格だけ（損の割引を強める）/ 候補を広げるだけ / 両方 について、
     相手の予測損失（応手 2 手分・実戦で当てはめた傾き）と自分の損（独立な再測定があればそちら）を
     1 局あたりに直す。E2 はプール外の手で測っていないので入れていない（E1 の項だけ）。

KataGo は起動しない。標準出力は ASCII のみ。

    python docs/superpowers/specs/calibration-data/enigma-deep/frontier.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["KIVY_NO_ARGS"] = "1"

import deep_cf_report as R  # noqa: E402
import wide_cf_noise as N  # noqa: E402
import wide_cf_report as W  # noqa: E402


def slope(xs, ys):
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    if len(xs) < 8 or xs.std() < 1e-9:
        return None
    X = np.column_stack([np.ones(len(xs)), xs])
    beta, *_ = np.linalg.lstsq(X, ys, rcond=None)
    resid = ys - X @ beta
    s2 = float(resid @ resid) / max(1, len(xs) - 2)
    se = np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    return beta[1], beta[1] / se, beta[0]


def part_a(drows):
    print("=== A. does the E -> realized slope hold for moves humans do not play / traps that are hard to find? ===")
    recs = []
    for row in drows:
        p = next((c for c in row["cands"] if c["gtp"] == row["played"]), None)
        if p is None or row["opp"][0] is None:
            continue
        recs.append(
            (
                p["e"],
                R.clip(row["opp"][0]),
                R.clip(row["opp"][1]) if row["opp"][1] is not None else np.nan,
                p["own_hp"],
                p["find"],
                p["vloss"],
                row["played"] != row["best"],
                row["cw"],
            )
        )
    a = np.array(recs, dtype=float)
    print("  played moves with realized reply: %d (deviations %d)" % (len(a), int(a[:, 6].sum())))
    s1 = slope(a[:, 0], a[:, 1])
    ok2 = ~np.isnan(a[:, 2])
    s2 = slope(a[ok2, 0], a[ok2, 2])
    print("  overall: opp1 ~ E slope %.2f (t %.1f) | opp2 ~ E slope %.2f (t %.1f)" % (s1[0], s1[1], s2[0], s2[1]))
    for label, col, edges in (
        ("own_hp", 3, (0.0, 0.005, 0.02, 0.1, 0.3, 1.01)),
        ("find", 4, (0.0, 0.05, 0.15, 0.4, 0.8, 1.01)),
    ):
        for lo, hi in zip(edges[:-1], edges[1:]):
            s = a[(a[:, col] >= lo) & (a[:, col] < hi)]
            if not len(s):
                continue
            sl = slope(s[:, 0], s[:, 1])
            print(
                "  %-6s [%.3f,%.3f) n=%3d  mean E %.2f -> mean opp1 %.2f (ratio %.2f) mean vloss %.2f | slope %s"
                % (
                    label,
                    lo,
                    hi,
                    len(s),
                    s[:, 0].mean(),
                    s[:, 1].mean(),
                    s[:, 1].mean() / max(1e-9, s[:, 0].mean()),
                    s[:, 5].mean(),
                    "n/a" if sl is None else "%.2f (t %.1f)" % (sl[0], sl[1]),
                )
            )
    # 大きく払った外し（プール外の手の典型: vloss 3 目超）
    for label, sel in (
        ("deviation, vloss>=3", (a[:, 6] > 0) & (a[:, 5] >= 3.0)),
        ("deviation, vloss>=3, own_hp<0.02", (a[:, 6] > 0) & (a[:, 5] >= 3.0) & (a[:, 3] < 0.02)),
        ("deviation, own_hp<0.005", (a[:, 6] > 0) & (a[:, 3] < 0.005)),
    ):
        s = a[sel]
        if len(s):
            print(
                "  %-34s n=%3d  E %.2f -> opp1 %.2f (ratio %.2f) | paid vloss %.2f"
                % (label, len(s), s[:, 0].mean(), s[:, 1].mean(), s[:, 1].mean() / s[:, 0].mean(), s[:, 5].mean())
            )
    return s1[0], s2[0]


def part_b(wrows, settings, deep, k1, k2):
    n_games = len({r["game"] for r in wrows})
    print("\n=== B. combined table, per game (AI turns in moves 10-74; sampled every 3rd turn -> x3) ===")
    print(
        "  realized scale: opponent loss over 2 replies = (%.2f + %.2f) * E1   [E2 not measured outside the pool]"
        % (k1, k2)
    )
    print("  own loss: independent re-read (deep_cf) where the pick has one, else the wide_cf value (optimistic)")
    short = lambda r: {m["gtp"] for m in r["moves"] if m["in_shortlist"]}  # noqa: E731
    scr = lambda r: short(r) | W.screen_members(r, settings, 16)[0]  # noqa: E731
    everything = lambda r: {m["gtp"] for m in r["moves"]}  # noqa: E731
    variants = [
        ("best move only", lambda r: set(), {}),
        ("current (nankai+)", short, {}),
        ("price 0.7", short, {"cw": 0.7}),
        ("price 0.5", short, {"cw": 0.5}),
        ("price 0.25", short, {"cw": 0.25}),
        ("wide (screen16)", scr, {}),
        ("wide (all legal)", everything, {}),
        ("wide16 + price 0.7", scr, {"cw": 0.7}),
        ("wide16 + price 0.5", scr, {"cw": 0.5}),
        ("all legal + price 0.5", everything, {"cw": 0.5}),
    ]
    for name, sel in (("close", lambda r: r["cw"] >= 1.0), ("spend", lambda r: r["cw"] < 1.0), ("all", lambda r: True)):
        rs = [r for r in wrows if sel(r)]
        per_game = 3.0 * len(rs) / n_games
        print("  -- %s: %.1f AI turns per game --" % (name, per_game))
        base = None
        for vname, members, kw in variants:
            e, vl, dev, reread, out = [], [], [], 0, 0
            for r in rs:
                c = W.choose(r, settings, members(r), **kw)
                if c is None:
                    continue
                d = (deep.get((r["game"], r["depth"])) or {}).get(c["gtp"])
                is_dev = c["gtp"] != r["best"]
                e.append(c["e"])
                vl.append(max(0.0, d["vloss"] if (d and is_dev) else c["vloss"]) if is_dev else 0.0)
                dev.append(is_dev)
                reread += bool(d and is_dev)
                out += bool(is_dev and not c["in_pool"])
            opp = (k1 + k2) * np.mean(e) * per_game
            own = np.mean(vl) * per_game
            if vname.startswith("current"):
                base = (opp, own)
            delta = (
                ""
                if base is None
                else "  | vs current: opp %+5.1f own %+5.1f net %+5.1f"
                % (
                    opp - base[0],
                    own - base[1],
                    (opp - base[0]) - (own - base[1]),
                )
            )
            print(
                "  %-22s deviations %4.1f/game (outside pool %4.1f, re-read %3d/%3d) | opp loss %5.1f  own loss %5.1f%s"
                % (vname, np.mean(dev) * per_game, 3.0 * out / n_games, reread, int(np.sum(dev)), opp, own, delta)
            )


def main():
    _ds, drows = R.load()
    k1, k2 = part_a(drows)
    settings, wrows = W.load()
    part_b(wrows, settings, N.deep_index(), k1, k2)


if __name__ == "__main__":
    main()
