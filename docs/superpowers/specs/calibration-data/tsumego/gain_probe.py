"""ai:tsumego の誤答局面を再現し、候補手ごとの gain 内訳を出す診断スクリプト。

usage: python docs/superpowers/specs/calibration-data/tsumego/gain_probe.py <sgf> <move_number> [visits]
"""
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.game import region_analysis_extra_settings
from katrain.core.ai import tsumego_ownership_gain
from katrain.core.sgf_parser import Move
from katrain.core.utils import var_to_grid
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
VISITS = int(sys.argv[3]) if len(sys.argv) > 3 else 1800
REGION = [0, 8, 0, 8]  # A1-J9 on 13x13 (log の avoidMoves と一致)


def gtp(x, y, size_y):
    return Move((x, y)).gtp()


def main():
    stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
    node = load_sgf_to_move(SGF, MOVE_N)
    root = node
    while root.parent:
        root = root.parent
    engine = KataGoEngine(stub, stub.config("engine"))
    try:
        game = DebugGame(katrain=stub, engine=engine, move_tree=root)
        game.set_current_node(node)
        stub.game = game
        game.region_of_interest = REGION
        size = game.board_size

        # 本番 (game.play) と同じ 2 本立て: 先に全盤 fast（root を作る）、次にリージョン+ownership
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

        player = node.next_player
        sign = node.player_sign(player)
        stones = [s.coords for s in game.stones]
        in_region = [
            (x, y) for (x, y) in stones if REGION[0] <= x <= REGION[1] and REGION[2] <= y <= REGION[3]
        ]
        # 詰碁の対象: リージョン内の相手石
        opp = "W" if player == "B" else "B"
        target = [s.coords for s in game.stones if s.player == opp and s.coords in set(in_region)]

        root_grid = var_to_grid(node.ownership, size)
        print(f"next_player={player} sign={sign} root scoreLead={node.analysis['root']['scoreLead']:+.2f}")
        print(f"stones total={len(stones)} in_region={len(in_region)} target({opp} in region)={len(target)}")
        print("target stones root ownership:")
        for (x, y) in sorted(target, key=lambda c: (c[1], c[0])):
            print(f"  {Move((x,y)).gtp():>3}  own={root_grid[y][x]:+.3f}")
        print()

        cands = node.candidate_moves
        hdr = f"{'move':>4} {'visits':>7} {'ptsLost':>8} {'lead':>7} {'gainALL':>8} {'gainREG':>8} {'gainTGT':>8}"
        print(hdr)
        print("-" * len(hdr))
        rows = []
        for c in cands:
            if not c.get("ownership"):
                continue
            g_all = tsumego_ownership_gain(node.ownership, c["ownership"], stones, size, sign)
            g_reg = tsumego_ownership_gain(node.ownership, c["ownership"], in_region, size, sign)
            g_tgt = tsumego_ownership_gain(node.ownership, c["ownership"], target, size, sign)
            rows.append((c["move"], c.get("visits", 0), c["pointsLost"], c["scoreLead"], g_all, g_reg, g_tgt))
        for r in sorted(rows, key=lambda r: -r[4]):
            print(f"{r[0]:>4} {r[1]:>7} {r[2]:>+8.2f} {r[3]:>+7.2f} {r[4]:>+8.2f} {r[5]:>+8.2f} {r[6]:>+8.2f}")

        # 注目手の石別内訳
        focus = [m for m in ("A4", "C3", "B3", "C1") if any(r[0] == m for r in rows)]
        for m in focus:
            c = next(c for c in cands if c["move"] == m)
            mg = var_to_grid(c["ownership"], size)
            print(f"\n--- {m} per-stone delta (|delta| >= 0.15) ---")
            deltas = []
            for (x, y) in stones:
                d = sign * (mg[y][x] - root_grid[y][x])
                if abs(d) >= 0.15:
                    inside = REGION[0] <= x <= REGION[1] and REGION[2] <= y <= REGION[3]
                    deltas.append((d, Move((x, y)).gtp(), inside))
            for d, g, inside in sorted(deltas, key=lambda t: -abs(t[0]))[:25]:
                print(f"  {g:>3} {'in ' if inside else 'OUT'} delta={d:+.3f}")
            print(f"  sum(all)={sum(d for d, _, _ in deltas):+.2f}  "
                  f"n_in={sum(1 for _,_,i in deltas if i)} n_out={sum(1 for _,_,i in deltas if not i)}")
    finally:
        engine.shutdown(finish=False)


main()
