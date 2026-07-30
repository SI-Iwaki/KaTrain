"""同一の解析結果に対して points_epsilon だけを変え、旧(目数最良)/新(同着バンド内 visits 最多)の選択を比較する。

run 間分散を交絡させないため、1回の解析から両方の選択を計算する（gain_region_ab.py と同方式）。
case J (2026-07-30): gain も目数も 0.02 差で並んだ N10/N11 のコイン投げで、解答樹に無い別解
N11 を打って不正解になった。新側は visits 最多（KataGo の本命）に寄せる。

usage: python docs/superpowers/specs/calibration-data/tsumego/points_tie_ab.py <sgf> <moves_csv> <xmin,xmax,ymin,ymax> [repeats]
例:    ... case-j-points-tie-20260730.sgf 0,2,4,6,8,10 6,12,1,12 3
"""
import os
import sys
import time
from collections import Counter

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER
from katrain.core.ai import TSUMEGO_POINTS_EPSILON, select_tsumego_move, tsumego_gain_stones, tsumego_ownership_gain
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
    mpb = settings.get("max_points_behind", 2.0)
    eps = settings.get("gain_epsilon", 0.3)
    mv = settings.get("min_visits", 10)
    ratio = settings.get("gain_min_visit_ratio", 0.5)
    peps = settings.get("points_epsilon", TSUMEGO_POINTS_EPSILON)
    tally = {}
    try:
        for rep in range(REPEATS):
            for move_n in MOVES:
                game, node = analyse(engine, stub, move_n)
                sign = node.player_sign(node.next_player)
                stones = tsumego_gain_stones([s.coords for s in game.stones], REGION)
                args = (node.candidate_moves, node.ownership, stones, game.board_size, sign, mpb, eps, mv, ratio)
                old = select_tsumego_move(*args, points_epsilon=0.0)
                new = select_tsumego_move(*args, points_epsilon=peps)
                o = old["move"] if old else "-"
                n = new["move"] if new else "-"
                top = sorted(
                    (c for c in node.candidate_moves if c.get("ownership")),
                    key=lambda c: c["pointsLost"],
                )[:3]
                detail = " ".join(
                    f"{c['move']}(v{c.get('visits', 0)} pt{c['pointsLost']:+.2f} "
                    f"g{tsumego_ownership_gain(node.ownership, c['ownership'], stones, game.board_size, sign):+.2f})"
                    for c in top
                )
                print(f"run{rep + 1} after {move_n:>2} moves: old={o:>4}  new={n:>4}  | {detail}")
                tally.setdefault(move_n, (Counter(), Counter()))
                tally[move_n][0][o] += 1
                tally[move_n][1][n] += 1
    finally:
        engine.shutdown(finish=False)
    print(f"\n=== tally (points_epsilon: old=0.0 / new={peps}) ===")
    for move_n in MOVES:
        old_c, new_c = tally[move_n]
        print(f"after {move_n:>2} moves: old={dict(old_c)}  new={dict(new_c)}")


main()
