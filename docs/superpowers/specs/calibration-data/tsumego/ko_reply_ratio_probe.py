"""守り方の応手を**全部**並べ、どの応手がコウ形に到達するかを visits 比つきで出す。

`ko_route_probe.py` は現在の `TSUMEGO_KO_REPLY_RATIO` を通った応手しか見せないので、
「閾値をいくつにすれば実信号（コウを仕掛ける抵抗）を落とさず、doomed な抵抗を拾わないか」を
決められない。ここでは比の外の応手も含めて、応手ごとに visits / 比 / 目数 / コウ到達を出す。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/ko_reply_ratio_probe.py \
      <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [top_n] [wide_root_noise]
  例: ... case-m-capture-gain-ko-20260730.sgf 4 4,12,0,8 M2,K1 800 6 0.0

**必ずプロセスを分けて複数回回すこと**（1プロセス内の再クエリは探索木が再利用されて
独立サンプルにならない）。`wide_root_noise` は既定 0.04（本番と同じ）。root の Dirichlet
ノイズは run ごとに引き直されるので、**応手の visits 比はこれで揺れる**（visits を増やしても
消えない種類の揺れ）。0 との比較用。
"""
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.ai import (
    TSUMEGO_KO_REGION_UNTIL_DEPTH,
    TSUMEGO_KO_REPLY_RATIO,
    tsumego_candidate_reaches_region_ko,
    tsumego_simulation_game,
)
from katrain.core.constants import DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.game import region_analysis_extra_settings
from katrain.core.sgf_parser import Move
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
MOVES = [m.strip().upper() for m in sys.argv[4].split(",") if m.strip()]
VISITS = int(sys.argv[5]) if len(sys.argv) > 5 else 800
TOP_N = int(sys.argv[6]) if len(sys.argv) > 6 else 6
WRN = float(sys.argv[7]) if len(sys.argv) > 7 else 0.04


def analyze_region(engine, node, visits, timeout=600.0):
    result = {}
    engine.request_analysis(
        node,
        callback=lambda analysis, partial_result: (
            None
            if partial_result
            else result.setdefault("root", {"moves": analysis.get("moveInfos")})
        ),
        error_callback=lambda error: result.setdefault("error", error),
        visits=visits,
        time_limit=False,
        ownership=False,
        region_of_interest=REGION,
        region_until_depth=TSUMEGO_KO_REGION_UNTIL_DEPTH,
        extra_settings=region_analysis_extra_settings(visits, WRN),
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
        player = node.next_player
        print(f"# {SGF} move={MOVE_N} region={REGION} next={player} visits={VISITS} wRN={WRN} ratio={TSUMEGO_KO_REPLY_RATIO}")
        for m in MOVES:
            sim = tsumego_simulation_game(game, node)
            if sim is None:
                print(f"\n{m}: 局面を再現できません")
                continue
            if tsumego_candidate_reaches_region_ko(game, node, m, [], REGION):
                print(f"\n{m}: KO(ply0 候補手自身) — 応手解析は不要")
                continue
            child = sim.play(Move.from_gtp(m, player=player))
            info = analyze_region(engine, child, VISITS)
            if info is None:
                print(f"\n{m}: 解析失敗")
                continue
            replies = sorted(info.get("moves") or [], key=lambda r: -r.get("visits", 0))[:TOP_N]
            top = replies[0].get("visits", 0) if replies else 0
            print(f"\n{m}: 応手 top={top}visits")
            ko_ratios = []
            for r in replies:
                v = r.get("visits", 0)
                ratio = v / top if top else 0.0
                hit = tsumego_candidate_reaches_region_ko(game, node, m, r.get("pv") or [], REGION)
                if hit:
                    ko_ratios.append(ratio)
                print(
                    f"   {r.get('move'):>4} v{v:>4} 比{ratio:5.2f} lead{r.get('scoreLead', float('nan')):+7.2f} "
                    f"{'KO ' if hit else '   '} pv={','.join((r.get('pv') or [])[:6])}"
                )
            if ko_ratios:
                print(f"   => コウ到達の最小比 {min(ko_ratios):.2f}（この比以下まで歩けば検出できる）")
            else:
                print("   => コウ到達の応手なし（clean）")
    finally:
        engine.shutdown(finish=False)


main()
