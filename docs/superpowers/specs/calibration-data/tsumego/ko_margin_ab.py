"""ko_win_assumption 修正の検証。指定局面で戦略を走らせ、選択手とコウ判定ログだけ出す。

usage: python docs/superpowers/specs/calibration-data/tsumego/ko_margin_ab.py <sgf> <move_number> <xmin,xmax,ymin,ymax> <expect> [repeats]
"""
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER
from katrain.core.ai import STRATEGY_REGISTRY
from katrain.core.engine import KataGoEngine
from katrain.core.game import region_analysis_extra_settings
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF, MOVE_N = sys.argv[1], int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
EXPECT = sys.argv[4].split("|")
REPEATS = int(sys.argv[5]) if len(sys.argv) > 5 else 3
VISITS = 1800


def run(engine, stub, override=None):
    node = load_sgf_to_move(SGF, MOVE_N)
    root = node
    while root.parent:
        root = root.parent
    game = DebugGame(katrain=stub, engine=engine, move_tree=root)
    game.set_current_node(node)
    stub.game = game
    game.region_of_interest = REGION
    game.region_analysis_visits = VISITS
    node.analyze(engine, analyze_fast=True)
    dl = time.time() + 300
    while node.analysis["root"] is None and time.time() < dl:
        time.sleep(0.05)
    node.analyze(engine, region_of_interest=REGION, visits=VISITS, time_limit=False,
                 extra_settings=region_analysis_extra_settings(VISITS, 0.04), ownership=True)
    dl = time.time() + 300
    while not node.analysis.get("region_completed") and time.time() < dl:
        time.sleep(0.05)
    settings = dict(stub.config(f"ai/{AI_TSUMEGO}") or {})
    if override:
        settings.update(override)
    n_logs = len(stub.logs)
    move, _ = STRATEGY_REGISTRY[AI_TSUMEGO](game, settings).generate_move()
    ko_lines = [str(m) for m, _lvl in stub.logs[n_logs:] if "コウ判定" in str(m) or "Final decision" in str(m)]
    return move.gtp(), ko_lines


def main():
    stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=1, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    fails = 0
    try:
        for i in range(REPEATS):
            got, lines = run(engine, stub)
            ok = got in EXPECT
            fails += 0 if ok else 1
            print(f"run{i+1} new(ko_win_margin=default): {got:>3}  expect {'|'.join(EXPECT):<6} {'OK' if ok else 'FAIL'}")
            for line in lines:
                print("      " + line.replace("[TsumegoOwnershipStrategy] ", ""))
        got, lines = run(engine, stub, {"ko_win_margin": 0.5})
        print(f"\nold(ko_win_margin=0.5): {got}  <- 旧既定の再現")
        for line in lines:
            print("      " + line.replace("[TsumegoOwnershipStrategy] ", ""))
    finally:
        engine.shutdown(finish=False)
    print(f"\n{'ALL OK' if fails == 0 else str(fails) + ' FAIL'}")


main()
