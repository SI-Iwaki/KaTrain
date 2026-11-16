# -*- coding: utf-8 -*-
"""deep_cf.py の集計: (A) 深い信号は実戦の相手の実損失を予測するか (B) 選択が変わる手番の在庫（2026-11-16）。

    python docs/superpowers/specs/calibration-data/enigma-deep/deep_cf_report.py

KataGo は起動しない。実現値は selfplay/recon/report_<game>.json（2500v の事後解析・両者の 1 手ごとの損失）。
標準出力は ASCII のみ。
"""

import glob
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core import ai  # noqa: E402
from katrain.core.game import KaTrainSGF, Move  # noqa: E402

ROWS = os.path.join(HERE, "rows")
RECON = os.path.join(HERE, "..", "selfplay", "recon")
LOSS_CAP = 8.0


def load():
    settings = json.load(open(os.path.join(ROWS, "_settings.json"), encoding="utf-8"))
    out = []
    for path in sorted(glob.glob(os.path.join(ROWS, "game_*.json"))):
        game = os.path.basename(path)[:-5]
        rep = json.load(open(os.path.join(RECON, "report_" + game + ".json"), encoding="utf-8"))
        by_depth = {r["depth"]: r for r in rep["rows"]}
        root = KaTrainSGF.parse_file(os.path.join(RECON, game + ".sgf"))
        last = {}
        n = root
        while n.children:
            n = n.children[0]
            last[n.depth] = n.move.coords if (n.move and not n.move.is_pass) else None
        for row in json.load(open(path, encoding="utf-8")):
            d = row["depth"]
            row["last_coords"] = last.get(d)
            sign = 1 if row["player"] == "B" else -1

            def loss(k):
                r = by_depth.get(d + k)
                return None if r is None or r.get("ptloss") is None else r["ptloss"]

            def lead(k):
                r = by_depth.get(d + k)
                return None if r is None or r.get("score") is None else sign * r["score"]

            row["own_loss"] = loss(1)
            row["opp"] = [loss(2), loss(4), loss(6)]
            row["lead_traj"] = [lead(0), lead(2), lead(4), lead(6)]
            out.append(row)
    return settings, out


def clip(x):
    return None if x is None else max(0.0, min(LOSS_CAP, x))


def e2_branch(c, key="e"):
    """応手分布で重みづけた「相手の次の判断」の E（枝の hp で再正規化）。枝が無ければ None。"""
    bs = [b for b in c.get("branches", []) if b.get("q")]
    tot = sum(b["hp"] for b in bs)
    if not bs or tot <= 0:
        return None
    return sum(b["hp"] * b["q"][key] for b in bs) / tot


def chain(c):
    """正解手順（最善応手の線）: (E2c, find2, E3c, find3)。"""
    b = next((b for b in c.get("branches", []) if b["is_best"] and b.get("q")), None)
    if b is None:
        return None, None, None, None
    q3 = b.get("q3") or {}
    return b["q"]["e"], b["q"]["find"], q3.get("e"), q3.get("find")


def ols(y, cols, names):
    X = np.column_stack([np.ones(len(y))] + cols)
    y = np.asarray(y, dtype=float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(1, len(y) - X.shape[1])
    s2 = float(resid @ resid) / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    r2 = 1.0 - float(resid @ resid) / float(((y - y.mean()) ** 2).sum())
    txt = "  ".join("%s %+.3f (t %+.1f)" % (n, b, b / s) for n, b, s in zip(["const"] + names, beta, se))
    return "n=%d R2=%.3f | %s" % (len(y), r2, txt)


def bins(xs, ys, edges, label):
    print("  %s bins: " % label, end="")
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = [y for x, y in zip(xs, ys) if lo <= x < hi]
        if sel:
            print("[%.1f,%.1f) n=%d mean %.2f | " % (lo, hi, len(sel), sum(sel) / len(sel)), end="")
    print()


def calibration(rows):
    print("=== (A) calibration on played moves (real opponents) ===")
    recs = []
    for row in rows:
        p = next((c for c in row["cands"] if c["gtp"] == row["played"]), None)
        b = next((c for c in row["cands"] if c["gtp"] == row["best"]), None)
        if p is None or b is None or row["opp"][0] is None:
            continue
        e2 = e2_branch(p)
        e2c, f2, e3c, f3 = chain(p)
        ab = next((x for x in p.get("branches", []) if x["reply"] == row["actual_reply"] and x.get("q")), None)
        recs.append(
            {
                "row": row,
                "p": p,
                "b": b,
                "e1": p["e"],
                "e2": e2,
                "e2c": e2c,
                "f2": f2,
                "e3c": e3c,
                "f3": f3,
                "e2_best": e2_branch(b),
                "e1_best": b["e"],
                "e2_actual": None if ab is None else ab["q"]["e"],
                "opp1": clip(row["opp"][0]),
                "opp2": clip(row["opp"][1]),
                "opp3": clip(row["opp"][2]),
            }
        )
    print(
        "played moves with L1:",
        len(recs),
        " with E2:",
        sum(1 for r in recs if r["e2"] is not None),
        " actual reply among branches:",
        sum(1 for r in recs if r["e2_actual"] is not None),
    )
    # opp1 ~ E1 (既存の較正の再確認) と生フィールドの上乗せ
    y = [r["opp1"] for r in recs]
    print("opp1 ~ E1:           ", ols(y, [np.array([r["e1"] for r in recs])], ["E1"]))
    bins([r["e1"] for r in recs], y, [0, 0.3, 0.7, 1.2, 2.0, 3.0, 9], "E1 -> opp1")
    for name, fn in (
        ("raw_st_score_err", lambda r: r["p"]["raw_st_score_err"]),
        ("human_st_score_err", lambda r: r["p"]["human_st_score_err"]),
        ("score_stdev", lambda r: r["p"]["score_stdev"]),
        ("hgap(9d)", lambda r: r["p"]["human_score"] - r["p"]["lead_after"]),
        ("hgap(asym)", lambda r: r["p"]["human_score_asym"] - r["p"]["lead_after"]),
        ("1-best_reply_prior", lambda r: 1.0 - (r["p"]["best_reply_prior"] or 0.0)),
        ("1-find", lambda r: 1.0 - r["p"]["find"]),
        ("p_fooled", lambda r: r["p"]["p_fooled"]),
    ):
        try:
            x = np.array([fn(r) for r in recs], dtype=float)
        except TypeError:
            print("  (missing %s)" % name)
            continue
        print("opp1 ~ E1 + %-18s" % name, ols(y, [np.array([r["e1"] for r in recs]), x], ["E1", name]))
    # opp2 / opp3 ~ 深い信号
    r2 = [r for r in recs if r["e2"] is not None and r["opp2"] is not None and r["e2_best"] is not None]
    y2 = [r["opp2"] for r in r2]
    print("\nopp2 ~ E1:           ", ols(y2, [np.array([r["e1"] for r in r2])], ["E1"]))
    print("opp2 ~ E2:           ", ols(y2, [np.array([r["e2"] for r in r2])], ["E2"]))
    print(
        "opp2 ~ E1 + E2:      ",
        ols(y2, [np.array([r["e1"] for r in r2]), np.array([r["e2"] for r in r2])], ["E1", "E2"]),
    )
    print(
        "opp2 ~ E2best + dE2: ",
        ols(
            y2,
            [np.array([r["e2_best"] for r in r2]), np.array([r["e2"] - r["e2_best"] for r in r2])],
            ["E2best", "dE2"],
        ),
    )
    bins([r["e2"] for r in r2], y2, [0, 0.3, 0.6, 1.0, 1.5, 2.5, 9], "E2 -> opp2")
    ra = [r for r in r2 if r["e2_actual"] is not None]
    if ra:
        ya = [r["opp2"] for r in ra]
        print("opp2 ~ E2(actual br):", ols(ya, [np.array([r["e2_actual"] for r in ra])], ["E2act"]))
        bins([r["e2_actual"] for r in ra], ya, [0, 0.3, 0.6, 1.0, 1.5, 2.5, 9], "E2act -> opp2")
    rc = [r for r in r2 if r["e2c"] is not None]
    yc = [r["opp2"] for r in rc]
    print(
        "opp2 ~ E1 + E2chain: ",
        ols(yc, [np.array([r["e1"] for r in rc]), np.array([r["e2c"] for r in rc])], ["E1", "E2c"]),
    )
    r3 = [r for r in r2 if r["opp3"] is not None]
    y12 = [r["opp1"] + r["opp2"] for r in r2]
    print("\nopp1+opp2 ~ E1:      ", ols(y12, [np.array([r["e1"] for r in r2])], ["E1"]))
    print(
        "opp1+opp2 ~ E1 + E2: ",
        ols(y12, [np.array([r["e1"] for r in r2]), np.array([r["e2"] for r in r2])], ["E1", "E2"]),
    )
    print("opp1+opp2 ~ E1+E2 (sum):", ols(y12, [np.array([r["e1"] + r["e2"] for r in r2])], ["E1+E2"]))
    y123 = [r["opp1"] + r["opp2"] + r["opp3"] for r in r3]
    print(
        "opp1..3 ~ E1 + E2:   ",
        ols(y123, [np.array([r["e1"] for r in r3]), np.array([r["e2"] for r in r3])], ["E1", "E2"]),
    )
    # 選択の効果: 打った手と最善手の差で見る（局面の難しさを差し引く）
    print("\nwithin-position spread of signals across verified candidates:")
    sp1, sp2, corr = [], [], []
    for row in rows:
        cs = [
            c
            for c in row["cands"]
            if e2_branch(c) is not None and (c["vloss"] <= row["cap"] or c["gtp"] == row["best"])
        ]
        if len(cs) < 4:
            continue
        a, b2 = np.array([c["e"] for c in cs]), np.array([e2_branch(c) for c in cs])
        sp1.append(a.std())
        sp2.append(b2.std())
        if a.std() > 1e-6 and b2.std() > 1e-6:
            corr.append(float(np.corrcoef(a, b2)[0, 1]))
    print(
        "  turns %d: sd(E1) median %.2f  sd(E2) median %.2f  corr(E1,E2) median %.2f"
        % (len(sp1), np.median(sp1), np.median(sp2), np.median(corr))
    )
    return recs


def current_pick(row, settings, deep=None, gamma=1.0, floor_on_total=False):
    """難解＋の選択則を再現（deep=None）／深い net に差し替え（deep=関数 c -> 上乗せの E）。"""
    pre = "enigma13plus_"
    min_wr = float(settings[pre + "min_winrate"])
    margin = float(settings[pre + "net_margin"])
    sd = float(settings[pre + "locality_stddev"] or 0.0)
    slack = float(settings[pre + "locality_slack"] or 0.0)
    best = row["best"]
    anchors = ai.enigma9_anchors(row["last_coords"], best) if sd > 0 else []
    scored = []
    for c in row["cands"]:
        if c["gtp"] != best:
            if not c["in_shortlist"] or c["vloss"] > row["cap"]:
                continue
            if c["wr_after"] is not None and c["wr_after"] < min_wr:
                continue
        prox = ai.enigma9_locality(Move.from_gtp(c["gtp"]).coords, anchors, sd)
        extra = 0.0
        if deep is not None:
            x = deep(c)
            if x is None:
                if c["gtp"] != best:
                    continue
                x = 0.0
            extra = gamma * x
        net = (
            ai.enigma9_net_score(
                c["vloss"], c["e"], c["find"], c["own_hp"], w_own=1.0, cost_weight=row["cw"], locality=prox
            )
            + extra
        )
        e_for_floor = c["e"] + (extra if floor_on_total else 0.0)
        scored.append(
            {**c, "loss": c["vloss"], "net": net, "prox": prox, "e": e_for_floor, "e1": c["e"], "extra": extra}
        )
    if not any(c["gtp"] == best for c in scored):
        return None
    until = int(settings.get(pre + "gamble_until_move") or 0)
    if deep is None and row["cw"] >= 1.0 and ai.enigma9_gamble_window(row["depth"], until):
        g_pick, _q = ai.enigma9_gamble_pick(
            scored, best, float(settings[pre + "gamble_min_winrate"]), float(settings[pre + "gamble_min_delta_e"])
        )
        if g_pick is not None:
            return next(c for c in scored if c["gtp"] == g_pick["gtp"])
    kept, _dropped = ai.enigma9_delta_e_filter(
        scored, best, float(settings[pre + "min_delta_e"]), float(settings[pre + "cheap_loss"])
    )
    chosen, _band = ai.enigma9_choose_local(kept, best, margin, slack, sd)
    return chosen if chosen is not None else next(c for c in scored if c["gtp"] == best)


def inventory(rows, settings):
    print("\n=== (B) inventory: how often would a deeper net change the pick ===")
    variants = [
        ("E2 branch (g=1)", lambda c: e2_branch(c), 1.0),
        ("E2 branch (g=0.5)", lambda c: e2_branch(c), 0.5),
        ("E2 chain+E3 chain", lambda c: None if chain(c)[0] is None else chain(c)[0] + (chain(c)[2] or 0.0), 1.0),
    ]
    for name, fn, gamma in variants:
        for mode, sel in (("close (cw=1)", lambda r: r["cw"] >= 1.0), ("spend (cw<1)", lambda r: r["cw"] < 1.0)):
            n = changed = 0
            d1 = d2 = dv = 0.0
            games = set()
            for row in rows:
                if not sel(row):
                    continue
                a = current_pick(row, settings)
                b = current_pick(row, settings, deep=fn, gamma=gamma, floor_on_total=True)
                if a is None or b is None:
                    continue
                n += 1
                games.add(row["game"])
                if a["gtp"] != b["gtp"]:
                    ca = next(c for c in row["cands"] if c["gtp"] == a["gtp"])
                    cb = next(c for c in row["cands"] if c["gtp"] == b["gtp"])
                    xa, xb = fn(ca), fn(cb)
                    if xa is None or xb is None:
                        continue
                    changed += 1
                    d1 += cb["e"] - ca["e"]
                    d2 += xb - xa
                    dv += cb["vloss"] - ca["vloss"]
            if n:
                k = max(1, changed)
                print(
                    "  %-20s %-13s turns %3d (%.1f/game) changed %3d (%.0f%%, %.1f/game) | per change: dE1 %+.2f dDeep %+.2f dvloss %+.2f"
                    % (
                        name,
                        mode,
                        n,
                        n / len(games),
                        changed,
                        100.0 * changed / n,
                        changed / len(games),
                        d1 / k,
                        d2 / k,
                        dv / k,
                    )
                )


def replication(rows, settings):
    n = same = 0
    for row in rows:
        if row["strategy"] != "Enigma13PlusStrategy":
            continue
        a = current_pick(row, settings)
        if a is None:
            continue
        n += 1
        same += a["gtp"] == row["played"]
    print("\nreplicated pick (today's settings) == move played in the game (settings of that day): %d/%d" % (same, n))


def main():
    settings, rows = load()
    print("turns:", len(rows), "games:", len({r["game"] for r in rows}))
    calibration(rows)
    replication(rows, settings)
    inventory(rows, settings)


if __name__ == "__main__":
    main()
