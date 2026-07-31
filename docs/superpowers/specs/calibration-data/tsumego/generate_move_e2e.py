"""実 TsumegoOwnershipStrategy.generate_move を回す E2E 回帰スクリプト（検証・救済経路込み）。

select_tsumego_move 単体の A/B は generate_move 側の後段（score_best 同深さ検証・救済）を
通らないので、そこで巻き戻される回帰を見逃す（実測 case J: select は N10 を選んだのに
無条件の score_best 検証が却下して N11 に巻き戻し、GUI で誤答が再発した）。
選択則を変えたら select レベルの A/B に加えて必ずこれも回すこと。

usage: python docs/superpowers/specs/calibration-data/tsumego/generate_move_e2e.py <sgf> <moves_csv> <xmin,xmax,ymin,ymax> [repeats]
例:    ... case-j-points-tie-20260730.sgf 0,10 6,12,1,12 3
"""
import os
import sys
import time
from collections import Counter

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER
from katrain.core.ai import STRATEGY_REGISTRY
from katrain.core.engine import KataGoEngine
from katrain.core.game import region_analysis_extra_settings
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVES = [int(m) for m in sys.argv[2].split(",")]
REGION = [int(v) for v in sys.argv[3].split(",")]
REPEATS = int(sys.argv[4]) if len(sys.argv) > 4 else 3
VISITS = 1800


def analyse(engine, stub, move_n):
    node = load_sgf_to_move(SGF, move_n)
    root = node
    while root.parent:
        root = root.parent
    game = DebugGame(katrain=stub, engine=engine, move_tree=root)
    game.set_current_node(node)
    stub.game = game
    game.region_of_interest = REGION
    game.region_analysis_visits = VISITS
    node.analyze(engine, analyze_fast=True)
    deadline = time.time() + 300
    while node.analysis["root"] is None and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    node.analyze(
        engine,
        region_of_interest=REGION,
        visits=VISITS,
        time_limit=False,
        extra_settings=region_analysis_extra_settings(VISITS, 0.04),
        ownership=True,
    )
    deadline = time.time() + 300
    while not node.analysis.get("region_completed") and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    return game, node


def main():
    stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    settings = stub.config(f"ai/{AI_TSUMEGO}") or {}
    print("settings:", settings)
    tally = {}
    timing = {}
    try:
        for rep in range(REPEATS):
            for move_n in MOVES:
                t0 = time.time()
                game, node = analyse(engine, stub, move_n)
                t1 = time.time()
                strategy = STRATEGY_REGISTRY[AI_TSUMEGO](game, settings)
                move, thoughts = strategy.generate_move()
                t2 = time.time()
                gtp_move = move.gtp()
                print(
                    f"run{rep + 1} after {move_n:>2} moves: generate_move -> {gtp_move}  ({thoughts})"
                    f"  [analyse {t1 - t0:.1f}s / generate {t2 - t1:.1f}s]"
                )
                tally.setdefault(move_n, Counter())[gtp_move] += 1
                timing.setdefault(move_n, []).append((t1 - t0, t2 - t1))
    finally:
        engine.shutdown(finish=False)
    print("\n=== tally (real generate_move) ===")
    for move_n in MOVES:
        times = timing.get(move_n, [])
        avg_a = sum(t[0] for t in times) / max(1, len(times))
        avg_g = sum(t[1] for t in times) / max(1, len(times))
        print(f"after {move_n:>2} moves: {dict(tally[move_n])}  [avg analyse {avg_a:.1f}s / generate {avg_g:.1f}s]")


main()
