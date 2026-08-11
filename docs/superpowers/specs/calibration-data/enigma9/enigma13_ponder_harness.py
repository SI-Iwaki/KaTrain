"""enigma13 の着手後先読み（ponder）の効果測定ハーネス。

GUI の実フローを模す:
  1. 局面 N（白番=AI）を通常解析 → generate_move（ON 条件ではここで先読み発火）
  2. 着手を本譜に打ち、その局面の通常解析を GUI 同様に発行（非ブロック）
  3. 相手の考慮時間 THINK 秒を sleep（先読みクエリはこの間に消化される）
  4. 応手 R = 着手後局面の解析の visits 最多手（両条件共通の機械的ルール）を打つ
  5. 応手後局面の analyze + generate を計測（= 次の AI 手番の体感時間）

usage: python enigma13_ponder_harness.py on|off label
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
THINK = 8.0

mode, label = sys.argv[1], sys.argv[2]


def wait_complete(node, engine):
    t0 = time.monotonic()
    while not node.analysis_complete:
        time.sleep(0.02)
        engine.check_alive(exception_if_dead=True)
    return time.monotonic() - t0


def cancel_ponder(game):
    """Game.play の _cancel_enigma_ponder 相当（DebugGame は Game.play を経ないため）。

    gen を進める＝ワーカーがまだ発行前でも自己回収させる（本体フックと同じ）。
    """
    game._enigma_ponder_owner = None
    game._enigma_ponder_gen = getattr(game, "_enigma_ponder_gen", 0) + 1
    state = getattr(game, "_enigma_ponder", None)
    if not state:
        return
    game._enigma_ponder = None
    for n in state[1]:
        state[0].terminate_queries(only_for_node=n)


def main():
    stub = KaTrainStub(CONFIG, debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    ai_settings = stub.config(f"ai/{AI_ENIGMA_13}") or {}
    print(f"=== ponder harness mode={mode} [{label}] ===", flush=True)
    try:
        # warmup（エンジン起動を分離）
        node0 = load_sgf_to_move(SGF, 2)
        root0 = node0
        while root0.parent:
            root0 = root0.parent
        g0 = DebugGame(katrain=stub, engine=engine, move_tree=root0)
        g0.set_current_node(node0)
        stub.game = g0
        t0 = time.monotonic()
        node0.analyze(engine)
        wait_complete(node0, engine)
        print(f"warmup: {time.monotonic()-t0:.2f}s", flush=True)

        for mv in MOVES:
            target = load_sgf_to_move(SGF, mv)
            root = target
            while root.parent:
                root = root.parent
            game = DebugGame(katrain=stub, engine=engine, move_tree=root)
            game.set_current_node(target)
            stub.game = game
            if mode == "on":
                stub.players_info["W"].update(PLAYER_AI)
                stub.players_info["B"].update(PLAYER_HUMAN)
            else:
                stub.players_info["W"].update(PLAYER_HUMAN)
                stub.players_info["B"].update(PLAYER_HUMAN)

            t0 = time.monotonic()
            target.analyze(engine)
            wait_complete(target, engine)
            t_an1 = time.monotonic() - t0

            strategy = STRATEGY_REGISTRY[AI_ENIGMA_13](game, dict(ai_settings))
            t0 = time.monotonic()
            move, _exp = strategy.generate_move()
            t_gen1 = time.monotonic() - t0

            # 本譜に着手し、GUI 同様に着手後局面の解析を発行（非ブロック）
            node_after = game.play(move, analyze=False)
            game.set_current_node(node_after)
            node_after.analyze(engine)

            time.sleep(THINK)  # 相手の考慮時間（先読みはこの間に消化）
            wait_complete(node_after, engine)

            picks = []
            state = getattr(game, "_enigma_ponder", None)
            if state:
                picks = [n.move.gtp() for n in state[1] if n.move]

            cands = node_after.candidate_moves
            reply_gtp = next(
                (c["move"] for c in sorted(cands, key=lambda c: -c.get("visits", 0))
                 if c["move"] != "pass"),
                None,
            )
            if reply_gtp is None:
                print(f"mv {mv}: no reply candidate, skip", flush=True)
                continue
            node_r = game.play(Move.from_gtp(reply_gtp, player="B"), analyze=False)
            game.set_current_node(node_r)
            cancel_ponder(game)  # GUI では Game.play の _cancel_enigma_ponder が担う

            t0 = time.monotonic()
            node_r.analyze(engine)
            wait_complete(node_r, engine)
            t_an2 = time.monotonic() - t0

            strategy2 = STRATEGY_REGISTRY[AI_ENIGMA_13](game, dict(ai_settings))
            t0 = time.monotonic()
            move2, _exp2 = strategy2.generate_move()
            t_gen2 = time.monotonic() - t0

            hit = reply_gtp in picks
            print(
                f"mv {mv}: my={move.gtp()} reply={reply_gtp} "
                f"picks={picks} hit={hit} | an1={t_an1:.2f} gen1={t_gen1:.2f} "
                f"| NEXT an2={t_an2:.2f} gen2={t_gen2:.2f} next_my={move2.gtp()}",
                flush=True,
            )
            cancel_ponder(game)  # 次の局面ブロックへ残骸を持ち込まない
    finally:
        engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
