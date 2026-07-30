"""同一の解析結果に対して gain の集計範囲だけを変え、旧(全石)/新(リージョン内)の選択を比較する。

run 間分散を交絡させないため、1回の解析から両方の選択を計算する。
usage: python docs/superpowers/specs/calibration-data/tsumego/gain_region_ab.py <sgf> <moves_csv> [repeats]
"""
import os
import sys
import time
from collections import Counter

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER
from katrain.core.ai import select_tsumego_move, tsumego_gain_stones
from katrain.core.engine import KataGoEngine
from katrain.core.game import region_analysis_extra_settings
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVES = [int(m) for m in sys.argv[2].split(",")]
REPEATS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
REGION = [0, 8, 0, 8]
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
    mpb = settings.get("max_points_behind", 2.0)
    eps = settings.get("gain_epsilon", 0.3)
    mv = settings.get("min_visits", 10)
    tally = {}
    try:
        for rep in range(REPEATS):
            for move_n in MOVES:
                game, node = analyse(engine, stub, move_n)
                sign = node.player_sign(node.next_player)
                all_stones = [s.coords for s in game.stones]
                reg_stones = tsumego_gain_stones(all_stones, REGION)
                old = select_tsumego_move(node.candidate_moves, node.ownership, all_stones, game.board_size, sign, mpb, eps, mv)
                new = select_tsumego_move(node.candidate_moves, node.ownership, reg_stones, game.board_size, sign, mpb, eps, mv)
                o = old["move"] if old else "-"
                n = new["move"] if new else "-"
                print(f"run{rep+1} after {move_n:>2} moves: old(all stones)={o:>4}  new(region only)={n:>4}")
                tally.setdefault(move_n, (Counter(), Counter()))
                tally[move_n][0][o] += 1
                tally[move_n][1][n] += 1
    finally:
        engine.shutdown(finish=False)
    print("\n=== tally (move_n: old -> new) ===")
    for move_n in MOVES:
        old_c, new_c = tally[move_n]
        print(f"after {move_n:>2} moves: old={dict(old_c)}  new={dict(new_c)}")


main()
