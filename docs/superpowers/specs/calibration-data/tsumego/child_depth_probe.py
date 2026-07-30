"""root の候補評価と「その手を打った子局面を同深さで測り直した値」を並べる診断スクリプト。

root の movesOwnership / pointsLost は候補ごとに探索の深さが違うので、visits が付かなかった
候補は「NN の生評価1回」でしかない。その候補が本当に悪いのか、単に読まれていないだけなのかは
子局面を独立に解析しないと分からない。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/child_depth_probe.py \
      <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [root_visits] [child_visits] [root_wrn]

出力:
  - root のリージョン解析の候補表（visits / pointsLost / gain / 相手石 ownership 絶対値）
  - moves_csv の各手について子局面を child_visits で解析した scoreLead と相手石 ownership
    （リージョン内の相手石だけを集計する。+n に近いほど「取れている」= 詰碁が成功）
"""
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import DATA_FOLDER, OUTPUT_ERROR
from katrain.core.engine import KataGoEngine
from katrain.core.game import region_analysis_extra_settings
from katrain.core.ai import tsumego_absolute_ownership, tsumego_ownership_gain, tsumego_simulation_game
from katrain.core.sgf_parser import Move
from katrain.core.utils import var_to_grid
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
MOVES = [m.strip().upper() for m in sys.argv[4].split(",") if m.strip() and m.strip() != "-"]
ROOT_VISITS = int(sys.argv[5]) if len(sys.argv) > 5 else 1800
CHILD_VISITS = int(sys.argv[6]) if len(sys.argv) > 6 else 1800
ROOT_WRN = float(sys.argv[7]) if len(sys.argv) > 7 else 0.04


def analyze_region(engine, node, visits, wrn, ownership=True, timeout=600.0):
    """使い捨てノードをリージョン限定で解析し root 情報を返す（ai._analyze_region_root と同型）"""
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
                    "visits": analysis["rootInfo"].get("visits"),
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
        extra_settings=region_analysis_extra_settings(visits, wrn),
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
        opp = "W" if player == "B" else "B"
        in_region = lambda c: REGION[0] <= c[0] <= REGION[1] and REGION[2] <= c[1] <= REGION[3]  # noqa: E731
        target = [s.coords for s in game.stones if s.player == opp and in_region(s.coords)]
        own_core = [s.coords for s in game.stones if s.player == player and in_region(s.coords)]

        print(f"# sgf={SGF} move={MOVE_N} region={REGION} next={player} sign={sign}")
        print(f"# root_visits={ROOT_VISITS} child_visits={CHILD_VISITS} root_wrn={ROOT_WRN}")
        print(f"# target({opp} in region)={len(target)}子 {[Move(c).gtp() for c in sorted(target, key=lambda c:(-c[1],c[0]))]}")
        print(f"# solver({player} in region)={len(own_core)}子")
        print()

        node.analyze(engine, analyze_fast=True)
        deadline = time.time() + 300
        while node.analysis["root"] is None and time.time() < deadline:
            time.sleep(0.05)
            engine.check_alive(exception_if_dead=True)
        node.analyze(
            engine,
            region_of_interest=REGION,
            visits=ROOT_VISITS,
            time_limit=False,
            extra_settings=region_analysis_extra_settings(ROOT_VISITS, ROOT_WRN),
            ownership=True,
        )
        deadline = time.time() + 600
        while not node.analysis.get("region_completed") and time.time() < deadline:
            time.sleep(0.05)
            engine.check_alive(exception_if_dead=True)

        root_own = node.ownership
        print(f"root scoreLead(黒視点)={node.analysis['root']['scoreLead']:+.2f} "
              f"target_own(手番視点合計)={tsumego_absolute_ownership(root_own, target, size, sign):+.2f}"
              f" / {len(target)}子")
        print()
        hdr = (f"{'move':>4} {'visits':>7} {'share':>6} {'prior':>8} {'prRank':>6} "
               f"{'ptsLost':>8} {'lead':>7} {'gainREG':>8} {'tgtOWN':>8}")
        print(hdr)
        print("-" * len(hdr))
        cands = [c for c in node.candidate_moves if c.get("ownership")]
        ref = max((c.get("visits", 0) for c in cands), default=1) or 1
        prior_rank = {c["move"]: i for i, c in enumerate(sorted(cands, key=lambda c: -c.get("prior", 0.0)), 1)}
        for c in sorted(cands, key=lambda c: (-c.get("visits", 0), -c.get("prior", 0.0))):
            g = tsumego_ownership_gain(root_own, c["ownership"], target, size, sign)
            own = tsumego_absolute_ownership(c["ownership"], target, size, sign)
            mark = " <<<" if c["move"] in MOVES else ""
            print(f"{c['move']:>4} {c.get('visits', 0):>7} {c.get('visits', 0)/ref:>6.2f} "
                  f"{c.get('prior', 0.0):>8.5f} {prior_rank[c['move']]:>6} "
                  f"{c['pointsLost']:>+8.2f} {c['scoreLead']:>+7.2f} {g:>+8.2f} {own:>+8.2f}{mark}")

        print()
        print(f"=== 子局面を独立に {CHILD_VISITS}visits で解析（{opp} 番の局面）===")
        chd = f"{'move':>4} {'lead(黒)':>9} {'lead(手番)':>10} {'tgtOWN':>8} {'best replies'}"
        print(chd)
        print("-" * 78)
        for m in MOVES:
            sim = tsumego_simulation_game(game, node)
            if sim is None:
                print(f"{m:>4}  局面を再現できません")
                continue
            try:
                child = sim.play(Move.from_gtp(m, player=player))
            except Exception as e:  # IllegalMove 等
                print(f"{m:>4}  打てません: {e}")
                continue
            info = analyze_region(engine, child, CHILD_VISITS, ROOT_WRN, ownership=True)
            if info is None or info.get("ownership") is None:
                print(f"{m:>4}  解析失敗")
                continue
            own = tsumego_absolute_ownership(info["ownership"], target, size, sign)
            replies = sorted(info.get("moves") or [], key=lambda r: -r.get("visits", 0))[:3]
            rtxt = " ".join(f"{r['move']}(v{r.get('visits',0)})" for r in replies)
            print(f"{m:>4} {info['lead']:>+9.2f} {sign*info['lead']:>+10.2f} {own:>+8.2f}  {rtxt}")
            grid = var_to_grid(info["ownership"], size)
            per = " ".join(
                f"{Move(c).gtp()}{sign*grid[c[1]][c[0]]:+.2f}" for c in sorted(target, key=lambda c: (-c[1], c[0]))
            )
            print(f"       石別: {per}")
    finally:
        engine.shutdown(finish=False)


main()
