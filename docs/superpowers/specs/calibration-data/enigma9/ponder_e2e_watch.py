"""enigma13 の監視モード先読み（humanSL 順の選手・レーン・自ノード解析の後回し）の実エンジン E2E（spec 追記9）。

usage: python ponder_e2e_watch.py hit|miss [THINK_SEC]

Mirrors the GUI flow in board-watch mode:
  analyse(N) -> generate_move (ponder fires) -> play -> node_after.analyze(fast only, as Game.play does)
  -> sleep THINK -> reply (hit: ponder pick #1 / miss: a legal move outside the picks)
  -> cancel (as Game.play does on the opponent's move) -> analyse(reply) + generate  (= next AI turn)
"""

import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"
REPO = r"c:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1"
sys.path.insert(0, REPO)

from katrain_debug.runner import DebugGame, load_sgf_to_move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.ai import STRATEGY_REGISTRY  # noqa: E402
from katrain.core.constants import AI_ENIGMA_13, PLAYER_AI, PLAYER_HUMAN  # noqa: E402
from katrain.core.game import Move  # noqa: E402

SGF = os.path.join(REPO, r"docs\superpowers\specs\calibration-data\jigo-speedup\katrain-13ro-20260401-game1.sgf")
CONFIG = os.path.expanduser(r"~\.katrain\config.json")
MOVES = [45, 77]
THINK = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
KIND = sys.argv[1] if len(sys.argv) > 1 else "hit"  # hit | miss


def wait_complete(node, engine):
    t0 = time.monotonic()
    while not node.analysis_complete:
        time.sleep(0.02)
        engine.check_alive(exception_if_dead=True)
    return time.monotonic() - t0


def main():
    stub = KaTrainStub(CONFIG, debug_level=1, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    ai_settings = stub.config(f"ai/{AI_ENIGMA_13}") or {}
    print(f"=== ponder e2e kind={KIND} think={THINK} ===", flush=True)
    try:
        node0 = load_sgf_to_move(SGF, 2)
        root0 = node0
        while root0.parent:
            root0 = root0.parent
        g0 = DebugGame(katrain=stub, engine=engine, move_tree=root0)
        g0.set_current_node(node0)
        stub.game = g0
        node0.analyze(engine)
        wait_complete(node0, engine)

        for mv in MOVES:
            target = load_sgf_to_move(SGF, mv)
            root = target
            while root.parent:
                root = root.parent
            game = DebugGame(katrain=stub, engine=engine, move_tree=root)
            game.set_current_node(target)
            game.board_watch_active = True
            game.board_watch_probe_warm = False
            stub.game = game
            stub.players_info["W"].update(PLAYER_AI)
            stub.players_info["B"].update(PLAYER_HUMAN)

            target.analyze(engine)
            wait_complete(target, engine)
            strategy = STRATEGY_REGISTRY[AI_ENIGMA_13](game, dict(ai_settings))
            t0 = time.monotonic()
            move, _exp = strategy.generate_move()
            t_gen1 = time.monotonic() - t0

            node_after = game.play(move, analyze=False)
            game.set_current_node(node_after)
            fast = game._enigma_ponder_defers_own_analysis(move)
            node_after.analyze(engine, analyze_fast=fast)
            t_play = time.monotonic()
            time.sleep(THINK)
            picks = [n.move.gtp() for n in (getattr(game, "_enigma_ponder", None) or (None, []))[1] if n.move]
            ponder_lines = [l for l in stub.logs if "Ponder:" in l or "ponder error" in l]
            own_visits = (node_after.analysis.get("root") or {}).get("visits")
            n_queries = sum(1 for l in stub.logs if "Sending query" in l)

            if KIND == "hit":
                reply_gtp = picks[0] if picks else None
            else:
                legal = [
                    c["move"]
                    for c in sorted(node_after.candidate_moves, key=lambda c: -c.get("visits", 0))
                    if c["move"] != "pass" and c["move"] not in picks
                ]
                reply_gtp = legal[0] if legal else None
            if reply_gtp is None:
                print(f"mv {mv}: no reply, skip", flush=True)
                continue
            node_r = game.play(Move.from_gtp(reply_gtp, player="B"), analyze=False)
            game.set_current_node(node_r)
            game._cancel_enigma_ponder(node_r.move)  # GUI では Game.play が呼ぶ
            t0 = time.monotonic()
            node_r.analyze(engine)
            wait_complete(node_r, engine)
            t_an2 = time.monotonic() - t0
            strategy2 = STRATEGY_REGISTRY[AI_ENIGMA_13](game, dict(ai_settings))
            t0 = time.monotonic()
            move2, _ = strategy2.generate_move()
            t_gen2 = time.monotonic() - t0
            print(
                f"mv {mv}: my={move.gtp()} fast_only={fast} picks={picks} reply={reply_gtp} "
                f"hit={reply_gtp in picks} own_visits_after_think={own_visits} gen1={t_gen1:.2f}s "
                f"| next: an2={t_an2:.2f}s gen2={t_gen2:.2f}s total={t_an2 + t_gen2:.2f}s -> {move2.gtp()}",
                flush=True,
            )
            for l in ponder_lines[-2:]:
                print("   ", l[:140], flush=True)
    finally:
        engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
