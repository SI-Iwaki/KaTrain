# -*- coding: utf-8 -*-
"""KataGo が子局面プローブで返す生フィールドと処理速度の確認（難解++ の設計前調査・2026-11-16）。

    python docs/superpowers/specs/calibration-data/enigma-deep/probe_fields.py

標準出力は ASCII のみ。
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core import ai  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import KaTrainSGF, Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame  # noqa: E402

RECON = os.path.join(HERE, "..", "selfplay", "recon")


def query(engine, node, **kw):
    out = {}

    def cb(a, partial_result):
        if not partial_result:
            out["a"] = a

    def err(a):
        out["a"] = None
        print("ERR", str(a)[:300])

    engine.request_analysis(node, callback=cb, error_callback=err, **kw)
    t0 = time.time()
    while "a" not in out:
        time.sleep(0.005)
        engine.check_alive(exception_if_dead=True)
    return out["a"], time.time() - t0


def main():
    stub = KaTrainStub(os.path.expanduser("~/.katrain/config.json"), debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    try:
        root = KaTrainSGF.parse_file(os.path.join(RECON, "game_20260918_004112.sgf"))
        game = DebugGame(katrain=stub, engine=engine, move_tree=root)
        stub.game = game
        n = root
        for _ in range(40):
            n = n.children[0]
        game.set_current_node(n)
        player = n.next_player
        n.analyze(engine)
        while not n.analysis_complete:
            time.sleep(0.02)
        best = n.candidate_moves[0]["move"]
        mv = Move.from_gtp(best, player=player)
        clean, dt = query(
            engine, n, next_move=mv, include_policy=False, visits=500, extra_settings={"ignorePreRootHistory": False}
        )
        print("clean 500v: %.2fs rootInfo keys:" % dt, sorted(clean["rootInfo"].keys()))
        print(" rootInfo:", json.dumps(clean["rootInfo"]))
        print(" moveInfos[0] keys:", sorted(clean["moveInfos"][0].keys()))
        print(" top-level keys:", sorted(clean.keys()))
        for prof in ("rank_9d", "rank_1d", "rank_9d_1d", "rank_1d_9d", "preaz_5k_9d"):
            hp, dt = query(
                engine,
                n,
                next_move=mv,
                include_policy=True,
                visits=8,
                extra_settings={"humanSLProfile": prof, "ignorePreRootHistory": False},
            )
            if hp is None:
                print("profile", prof, "-> error")
                continue
            ri = hp["rootInfo"]
            print(
                "hp %s: %.2fs keys=%s"
                % (prof, dt, sorted(k for k in ri if k.startswith("human") or k.startswith("raw")))
            )
            print("   ", {k: round(v, 3) for k, v in ri.items() if isinstance(v, float)})
            print("    top-level:", sorted(hp.keys()))
        # throughput: 16 child probes in parallel
        cands = [c["move"] for c in n.candidate_moves[:16] if c["move"] != "pass"]
        strat = ai.Enigma13PlusStrategy(game, {})
        t0 = time.time()
        probes, php = strat._probe_children(cands, player, parent_hp=True)
        dt = time.time() - t0
        tot = sum((p["clean"] or {}).get("rootInfo", {}).get("visits", 0) for p in probes.values())
        print("batch %d probes: %.2fs total visits %d -> %.0f v/s" % (len(cands), dt, tot, tot / dt))
        t0 = time.time()
        probes, php = strat._probe_children(cands, player, parent_hp=True)
        print("warm repeat: %.2fs" % (time.time() - t0))
    finally:
        engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
