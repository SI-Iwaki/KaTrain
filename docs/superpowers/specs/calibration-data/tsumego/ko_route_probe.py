"""指定した候補手が「コウ経路か無条件か」を、本番の `_ko_route_screen` と同じ手順で判定する。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/ko_route_probe.py \
      <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [repeats]
"""
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.game import region_analysis_extra_settings
from katrain.core.ai import (
    tsumego_absolute_ownership,
    tsumego_candidate_reaches_region_ko,
    tsumego_competitive_replies,
    tsumego_simulation_game,
)
from katrain.core.sgf_parser import Move
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
MOVES = [m.strip().upper() for m in sys.argv[4].split(",") if m.strip()]
VISITS = int(sys.argv[5]) if len(sys.argv) > 5 else 800
REPEATS = int(sys.argv[6]) if len(sys.argv) > 6 else 1


def analyze_region(engine, node, visits, ownership=False, timeout=600.0):
    result = {}
    engine.request_analysis(
        node,
        callback=lambda analysis, partial_result: (
            None
            if partial_result
            else result.setdefault(
                "root",
                {
                    "lead": analysis["rootInfo"]["scoreLead"],
                    "ownership": analysis.get("ownership"),
                    "moves": analysis.get("moveInfos"),
                },
            )
        ),
        error_callback=lambda error: result.setdefault("error", error),
        visits=visits,
        time_limit=False,
        ownership=ownership,
        region_of_interest=REGION,
        extra_settings=region_analysis_extra_settings(visits, 0.04),
        priority=0,
    )
    deadline = time.time() + timeout
    while "root" not in result and "error" not in result and time.time() < deadline:
        time.sleep(0.02)
        engine.check_alive(exception_if_dead=True)
    return result.get("root")


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
        player = node.next_player
        sign = node.player_sign(player)
        in_region = lambda c: REGION[0] <= c[0] <= REGION[1] and REGION[2] <= c[1] <= REGION[3]  # noqa: E731
        target = [s.coords for s in game.stones if s.player != player and in_region(s.coords)]
        print(f"# {SGF} move={MOVE_N} region={REGION} next={player} visits={VISITS} repeats={REPEATS}")
        print(f"# target={len(target)}子")
        for rep in range(REPEATS):
            print(f"\n--- run {rep + 1} ---")
            for m in MOVES:
                sim = tsumego_simulation_game(game, node)
                if sim is None:
                    print(f"{m:>4}  局面を再現できません")
                    continue
                # ply0: 候補手自身がコウ形か
                if tsumego_candidate_reaches_region_ko(game, node, m, [], REGION):
                    print(f"{m:>4}  KO（候補手自身がリージョン内のコウ形の1子取り）")
                    continue
                child = sim.play(Move.from_gtp(m, player=player))
                info = analyze_region(engine, child, VISITS, ownership=True)
                if info is None:
                    print(f"{m:>4}  解析失敗")
                    continue
                replies = info.get("moves") or []
                walk = tsumego_competitive_replies(replies)
                hits = [
                    r.get("move")
                    for r in walk
                    if tsumego_candidate_reaches_region_ko(game, node, m, r.get("pv") or [], REGION)
                ]
                own = (
                    tsumego_absolute_ownership(info["ownership"], target, size, sign)
                    if info.get("ownership")
                    else float("nan")
                )
                verdict = f"KO（応手 {hits}）" if hits else "無条件(clean)"
                print(
                    f"{m:>4}  {verdict:<28} lead(手番){sign * info['lead']:+7.2f} tgtOWN{own:+7.2f} "
                    f"拮抗応手={[(r.get('move'), r.get('visits')) for r in walk]}"
                )
    finally:
        engine.shutdown(finish=False)


main()
