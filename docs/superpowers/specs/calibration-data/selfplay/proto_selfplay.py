"""Throwaway prototype of the headless self-play harness (design validation only).

AI side: the real `generate_ai_move(game, mode, settings)` (same path as GUI `_do_ai_move`) on a real `Game`
(not DebugGame) so `game.play(..., expected_node=...)` works and every played node gets the normal
analysis exactly like the GUI. Opponent: pure humanSL sampler (1-visit humanSL query, humanPolicy-weighted).
At the end, waits for all node analyses and calls the real `game_report` for both colours.

usage: python proto_selfplay.py <ai_mode> <ai_color B|W> <profile> <max_moves> [seed]
"""
import os
import random
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))  # リポジトリのルート
sys.path.insert(0, REPO)
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.ai import game_report, generate_ai_move, parity9_match_tally  # noqa: E402
from katrain.core.constants import PRIORITY_EXTRA_AI_QUERY  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import Game, IllegalMoveException  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402

AI_MODE = sys.argv[1] if len(sys.argv) > 1 else "ai:mimic13"
AI_COLOR = sys.argv[2] if len(sys.argv) > 2 else "W"
PROFILE = sys.argv[3] if len(sys.argv) > 3 else "rank_3k"
MAX_MOVES = int(sys.argv[4]) if len(sys.argv) > 4 else 60
SEED = int(sys.argv[5]) if len(sys.argv) > 5 else 1
rng = random.Random(SEED)


def humansl(engine, node, profile):
    out = {}
    engine.request_analysis(
        node, callback=lambda a, partial_result: (not partial_result) and out.setdefault("a", a),
        error_callback=lambda a: out.setdefault("err", a), visits=1, priority=PRIORITY_EXTRA_AI_QUERY,
        ownership=False, include_policy=True, time_limit=False,
        extra_settings={"humanSLProfile": profile, "ignorePreRootHistory": False},
    )
    while "a" not in out and "err" not in out:
        time.sleep(0.005)
    return out.get("a")


def opp_move(game, engine, profile):
    cn = game.current_node
    a = humansl(engine, cn, profile)
    sx, sy = game.board_size
    hp = (a or {}).get("humanPolicy") or []
    pts = [(Move((i % sx, sy - 1 - i // sx), player=cn.next_player), p) for i, p in enumerate(hp[: sx * sy]) if p > 0]
    if len(hp) > sx * sy and hp[-1] > 0:
        pts.append((Move(None, player=cn.next_player), hp[-1]))
    while pts:
        tot = sum(p for _, p in pts)
        r, acc = rng.random() * tot, 0.0
        for k, (m, p) in enumerate(pts):
            acc += p
            if acc >= r:
                break
        try:
            return game.play(m), m
        except IllegalMoveException:
            pts.pop(k)
    return game.play(Move(None, player=cn.next_player)), Move(None, player=cn.next_player)


def main():
    stub = KaTrainStub(os.path.expanduser("~/.katrain/config.json"), debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    game = Game(stub, engine, game_properties={"SZ": 13, "KM": 7.0, "RU": "chinese"})
    stub.game = game
    settings = stub.config(f"ai/{AI_MODE}")
    ai_times = []
    t0 = time.time()
    passes = 0
    resign_lead = float(os.environ.get("RESIGN_LEAD", "0"))
    over = 0
    term = "cap"
    for i in range(MAX_MOVES):
        cn = game.current_node
        if cn.next_player == AI_COLOR:
            while not cn.analysis_complete:
                time.sleep(0.01)
            lead_now = cn.score * (1 if AI_COLOR == "B" else -1)
            over = over + 1 if (resign_lead and lead_now >= resign_lead and cn.depth >= 40) else 0
            if over >= 2:
                term = "opp_resign"
                break
            t = time.time()
            move, node = generate_ai_move(game, AI_MODE, settings)
            ai_times.append(time.time() - t)
            last = move
        else:
            node, last = opp_move(game, engine, PROFILE)
        passes = passes + 1 if last.is_pass else 0
        if passes >= 2:
            term = "double_pass"
            break
    t_play = time.time() - t0
    nodes = game.current_node.nodes_from_root
    while not all(n.analysis_complete for n in nodes):
        time.sleep(0.05)
    t_all = time.time() - t0
    thresholds = stub.config("trainer/eval_thresholds")
    sum_stats, _, _ = game_report(game, thresholds=thresholds)
    mine, opp, counted = parity9_match_tally([n for n in nodes if n.move and not n.is_root], AI_COLOR)
    oc = "B" if AI_COLOR == "W" else "W"
    lead = game.current_node.score * (1 if AI_COLOR == "B" else -1)
    print(f"{AI_MODE} as {AI_COLOR} vs {PROFILE}: {len(nodes) - 1} moves ({term}), play {t_play:.0f}s, total {t_all:.0f}s")
    print(f"  AI generate_ai_move: mean {sum(ai_times) / len(ai_times):.2f}s max {max(ai_times):.2f}s (incl. waiting for node analysis)")
    for bw, who in ((AI_COLOR, "AI "), (oc, "OPP")):
        s = sum_stats[bw]
        print(f"  {who} report: top1 {s['ai_top_move']:.3f} top5 {s['ai_top5_move']:.3f} mean_ptloss {s['mean_ptloss']:.2f} accuracy {s['accuracy']:.1f}")
    print(f"  tally (opp truncated to AI count): mine {mine}/{counted} opp {opp}/{counted}; final AI lead {lead:+.1f}")
    engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
