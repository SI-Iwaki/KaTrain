"""Offline KataGo re-analysis of reconstructed games: match rate / point loss for both colours.

Throwaway spike script (2026-09-18). Writes recon/report_<game>.json and prints a table.
"""

import glob
import json
import os
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))  # リポジトリのルート
sys.path.insert(0, REPO)
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.game import KaTrainSGF  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(HERE, "recon")
MIN_VISITS = 10


def analyze_game(stub, engine, sgf_path, timeout=1200):
    root = KaTrainSGF.parse_file(sgf_path)
    game = DebugGame(katrain=stub, engine=engine, move_tree=root)
    stub.game = game
    nodes = []
    n = root
    while n.children:
        n = n.children[0]
        nodes.append(n)
    allnodes = [root] + nodes
    for n in allnodes:
        n.analyze(engine)
    t0 = time.time()
    while not all(n.analysis_complete for n in allnodes):
        time.sleep(0.2)
        engine.check_alive(exception_if_dead=True)
        if time.time() - t0 > timeout:
            print("TIMEOUT", sgf_path, sum(n.analysis_complete for n in allnodes), "/", len(allnodes), flush=True)
            break
    rows = []
    for n in nodes:
        p = n.parent
        cands = p.candidate_moves if p.analysis_complete else []
        top = cands[0]["move"] if cands else None
        # cheapest non-top alternative (relativePointsLost, mover's view) among searched candidates
        alts = [c for c in cands[1:] if c.get("visits", 0) >= MIN_VISITS and "relativePointsLost" in c]
        alt_losses = sorted(max(0.0, c["relativePointsLost"]) for c in alts)
        rows.append(
            dict(
                depth=n.depth,
                player=n.player,
                move=n.move.gtp(),
                top=top,
                match=bool(top and top == n.move.gtp()),
                ptloss=n.points_lost,
                score=n.score,
                parent_visits=p.root_visits,
                n_cands=len(cands),
                alt_min_loss=alt_losses[0] if alt_losses else None,
                alt_le_01=sum(1 for x in alt_losses if x <= 0.1),
                alt_le_03=sum(1 for x in alt_losses if x <= 0.3),
                alt_le_05=sum(1 for x in alt_losses if x <= 0.5),
                alt_le_10=sum(1 for x in alt_losses if x <= 1.0),
                top_prior=cands[0].get("prior") if cands else None,
            )
        )
    return rows, time.time() - t0


def summarize(game, ai, rows):
    def stats(sel):
        rs = [r for r in rows if sel(r) and r["ptloss"] is not None]
        if not rs:
            return None
        return dict(
            n=len(rs),
            match=sum(r["match"] for r in rs) / len(rs),
            mean_loss=sum(max(0.0, r["ptloss"]) for r in rs) / len(rs),
        )

    opp = "W" if ai == "B" else "B"
    return dict(
        game=game,
        ai=ai,
        n_moves=len(rows),
        final_score=rows[-1]["score"] if rows else None,
        mine=stats(lambda r: r["player"] == ai),
        opp=stats(lambda r: r["player"] == opp),
        mine_pre85=stats(lambda r: r["player"] == ai and r["depth"] < 85),
        mine_post85=stats(lambda r: r["player"] == ai and r["depth"] >= 85),
        opp_pre85=stats(lambda r: r["player"] == opp and r["depth"] < 85),
        opp_post85=stats(lambda r: r["player"] == opp and r["depth"] >= 85),
    )


def main():
    summ = json.load(open(os.path.join(RECON, "summary.json"), encoding="utf-8"))
    ai_of = {s["game"]: s["ai"] for s in summ}
    strat_of = {s["game"]: s["strategy"] for s in summ}
    games = sys.argv[1:] or [s["game"] for s in summ]
    stub = KaTrainStub(os.path.expanduser("~/.katrain/config.json"), debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    out = []
    try:
        for g in games:
            sgf = os.path.join(RECON, g + ".sgf")
            rows, secs = analyze_game(stub, engine, sgf)
            s = summarize(g, ai_of[g], rows)
            s["strategy"] = strat_of[g]
            s["secs"] = secs
            json.dump(
                dict(summary=s, rows=rows),
                open(os.path.join(RECON, "report_" + g + ".json"), "w", encoding="utf-8"),
                indent=1,
            )
            out.append(s)
            m, o = s["mine"], s["opp"]
            print(
                "%s %-13s ai=%s moves=%3d final=%7s | mine match %.0f%% loss %.2f | opp match %.0f%% loss %.2f | pre85 mine %s opp %s | post85 mine %s opp %s | %.0fs"
                % (
                    g,
                    s["strategy"][:13],
                    s["ai"],
                    s["n_moves"],
                    ("%.1f" % s["final_score"]) if s["final_score"] is not None else "-",
                    100 * m["match"],
                    m["mean_loss"],
                    100 * o["match"],
                    o["mean_loss"],
                    ("%.0f%%" % (100 * s["mine_pre85"]["match"])) if s["mine_pre85"] else "-",
                    ("%.0f%%" % (100 * s["opp_pre85"]["match"])) if s["opp_pre85"] else "-",
                    (
                        ("%.0f%%/n%d" % (100 * s["mine_post85"]["match"], s["mine_post85"]["n"]))
                        if s["mine_post85"]
                        else "-"
                    ),
                    ("%.0f%%" % (100 * s["opp_post85"]["match"])) if s["opp_post85"] else "-",
                    secs,
                ),
                flush=True,
            )
    finally:
        engine.shutdown(finish=False)
    json.dump(out, open(os.path.join(RECON, "report_all.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
