"""Throwaway timing probe for the self-play harness design (13x13, user config).

Emulates the harness pipeline without any strategy code:
  - "AI" turns wait for the node's normal analysis (2500v, like AI_STRATEGIES_ENGINE) and play the top move
  - "opponent" turns send one humanSL query (visits=1, rank profile) and sample from humanPolicy,
    WITHOUT waiting for the node's normal analysis (it keeps running in the background)
Prints engine start time, per-node analysis wall time, humanSL query time, total.
"""
import os
import random
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))  # リポジトリのルート
sys.path.insert(0, REPO)
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import PRIORITY_EXTRA_AI_QUERY  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import Game  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402

N_MOVES = int(sys.argv[1]) if len(sys.argv) > 1 else 40
PROFILE = sys.argv[2] if len(sys.argv) > 2 else "rank_3k"
random.seed(1)


def humansl_query(engine, node, profile, visits=1):
    out = {}

    def cb(a, partial_result):
        if not partial_result:
            out["a"] = a

    def err(a):
        out["err"] = a

    engine.request_analysis(
        node, callback=cb, error_callback=err, visits=visits, priority=PRIORITY_EXTRA_AI_QUERY,
        ownership=False, include_policy=True, time_limit=False,
        extra_settings={"humanSLProfile": profile, "ignorePreRootHistory": False},
    )
    while "a" not in out and "err" not in out:
        time.sleep(0.005)
        engine.check_alive(exception_if_dead=True)
    return out.get("a")


def main():
    stub = KaTrainStub(os.path.expanduser("~/.katrain/config.json"), debug_level=0, quiet=True)
    t0 = time.time()
    engine = KataGoEngine(stub, stub.config("engine"))
    game = Game(stub, engine, game_properties={"SZ": int(os.environ.get("SZ", "13")), "KM": 7.0, "RU": "chinese"})
    stub.game = game
    while not game.root.analysis_complete:
        time.sleep(0.02)
        engine.check_alive(exception_if_dead=True)
    print(f"engine start + root analysis: {time.time() - t0:.1f}s (root visits {game.root.root_visits})", flush=True)

    ana_waits, hs_times, tstart = [], [], time.time()
    for i in range(N_MOVES):
        cn = game.current_node
        if i % 2 == 0:  # "AI" turn: wait for normal analysis, play top (or 2nd) candidate
            tw = time.time()
            while not cn.analysis_complete:
                time.sleep(0.01)
                engine.check_alive(exception_if_dead=True)
            ana_waits.append(time.time() - tw)
            cands = cn.candidate_moves
            mv = cands[0]["move"] if cands else "pass"
            move = Move.from_gtp(mv, player=cn.next_player)
        else:  # opponent: humanSL 1 visit, sample
            th = time.time()
            a = humansl_query(engine, cn, PROFILE)
            hs_times.append(time.time() - th)
            hp = a.get("humanPolicy") or []
            sx = sy = int(os.environ.get("SZ", "13"))
            pts = []
            for idx, p in enumerate(hp[: sx * sy]):
                if p > 0:
                    y = sy - 1 - idx // sx
                    x = idx % sx
                    pts.append(((x, y), p))
            r, acc, pick = random.random() * sum(p for _, p in pts), 0.0, pts[-1][0]
            for c, p in pts:
                acc += p
                if acc >= r:
                    pick = c
                    break
            move = Move(pick, player=cn.next_player)
        try:
            game.play(move)
        except Exception as e:  # illegal (ko) -> pass
            print("illegal", move.gtp(), e)
            game.play(Move(None, player=cn.next_player))
    tw = time.time()
    nodes = game.current_node.nodes_from_root
    while not all(n.analysis_complete for n in nodes):
        time.sleep(0.02)
    drain = time.time() - tw
    total = time.time() - tstart
    vis = [n.root_visits for n in nodes]
    print(f"moves {N_MOVES}: total {total:.1f}s = {total / N_MOVES:.2f}s/move (drain {drain:.1f}s)")
    print(f"AI-turn analysis wait: mean {sum(ana_waits) / len(ana_waits):.2f}s  max {max(ana_waits):.2f}s")
    print(f"humanSL 1-visit query: mean {sum(hs_times) / len(hs_times):.3f}s  max {max(hs_times):.3f}s")
    print(f"root visits min {min(vis)} max {max(vis)}")
    engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
