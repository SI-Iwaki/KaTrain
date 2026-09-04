"""E2E 全ケースの各黒番で「打つ側／守り方が着手前から打てるコウ取り」を棚卸しする（2026-09-04・KataGo 不要）。
usage: python docs/superpowers/specs/calibration-data/tsumego/preexisting_screen.py
"""
import os, sys, importlib.util
os.environ["KIVY_NO_ARGS"] = "1"
T = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("e2e_suite", os.path.join(T, "e2e_suite.py")); m = importlib.util.module_from_spec(spec)
sys.argv = ["x"]; spec.loader.exec_module(m)  # CASES/KNOWN_LIMITS を借りる
from katrain.core.game import BaseGame, Move
from katrain.core.ai import tsumego_defender_ko_points, tsumego_simulation_game
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import load_sgf_to_move
stub = KaTrainStub(os.path.expanduser("~/.katrain/config.json"), debug_level=0, quiet=True)
table = dict(m.CASES); table.update(m.KNOWN_LIMITS)
for name, case in table.items():
    region = [int(v) for v in case["region"].split(",")]
    root = load_sgf_to_move(os.path.join(T, case["sgf"]), 0)
    game = BaseGame(katrain=stub, move_tree=root); game.set_current_node(root)
    for ply in range(0, len(case["line"])):
        if ply % 2 == 0:
            node = game.current_node; mover = node.next_player; defender = "W" if mover == "B" else "B"
            sim = tsumego_simulation_game(game, node)
            mv = tsumego_defender_ko_points(sim, mover, region); sim = tsumego_simulation_game(game, node)
            dv = tsumego_defender_ko_points(sim, defender, region)
            tag = "EXPECT" if ply in case["expect"] else "line"
            if mv or dv:
                print(f"{name}@{ply} [{tag}] mover({mover}) pre-existing ko: {[Move(c).gtp() for c in sorted(mv)]}  defender pre-existing: {[Move(c).gtp() for c in sorted(dv)]}  answer={case['expect'].get(ply, (case['line'][ply],))}")
        game.play(Move.from_gtp(case["line"][ply], player=game.current_node.next_player))
print("done")
