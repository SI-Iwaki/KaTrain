"""コウ経路検査の「格下げ先」が本当に詰碁を成立させているかを測る。

`_ko_route_screen` は候補が コウ経路 / 無条件 のどちらかしか出さないので、格下げ先の
clean 手が「詰碁を解いている無条件手」なのか「何も起きないので自明に clean な手」なのかを
区別できない。ここでは本番の `_region_child_verdict`（同じ子局面解析1本でコウ判定と絶対
ownership を同時に取る）をそのまま呼び、さらに同じ解析結果から自石／相手石の1子平均も出す。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/class_screen_probe.py \
      <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [repeats]
  例: ... case-r-declass-nonsolution-20260731.sgf 0 0,12,7,12 G13,D8,J13,C8 800 2
"""
import os
import sys

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.ai import STRATEGY_REGISTRY, tsumego_absolute_ownership, tsumego_gain_stones
from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
MOVES = [m.strip().upper() for m in sys.argv[4].split(",") if m.strip()]
VISITS = int(sys.argv[5]) if len(sys.argv) > 5 else 800
REPEATS = int(sys.argv[6]) if len(sys.argv) > 6 else 1


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
        stones = tsumego_gain_stones([s.coords for s in game.stones], REGION)
        own_stones = [s.coords for s in game.stones if s.player == player and in_region(s.coords)]
        opp_stones = [s.coords for s in game.stones if s.player != player and in_region(s.coords)]

        settings = dict(stub.config(f"ai/{AI_TSUMEGO}") or {})
        strategy = STRATEGY_REGISTRY[AI_TSUMEGO](game, settings)
        # 同じ解析結果から内訳も出したいので `_analyze_region_root` の戻りを覗く
        captured = {}
        original = strategy._analyze_region_root

        def spy(*args, **kwargs):
            result = original(*args, **kwargs)
            captured["root"] = result
            return result

        strategy._analyze_region_root = spy

        print(f"# {SGF} move={MOVE_N} region={REGION} next={player} visits={VISITS} repeats={REPEATS}")
        print(f"# 集計石: 全{len(stones)}子 / 自石{len(own_stones)}子 / 相手石{len(opp_stones)}子")
        print("# value = _region_child_verdict の絶対 ownership（全リージョン石）")
        for rep in range(REPEATS):
            print(f"\n--- run {rep + 1} ---")
            for m in MOVES:
                captured.clear()
                verdict = strategy._region_child_verdict(m, stones, sign, VISITS)
                if verdict is None:
                    print(f"{m:>4}  測れません")
                    continue
                own_grid = (captured.get("root") or {}).get("ownership")
                per = lambda group: (  # noqa: E731
                    tsumego_absolute_ownership(own_grid, group, size, sign) / len(group)
                    if own_grid and group
                    else float("nan")
                )
                cls = f"KO（{verdict['ko_reply']}）" if verdict["ko"] else "無条件(clean)"
                print(
                    f"{m:>4}  {cls:<22} value{verdict['value']:+7.2f}  lead(手番){verdict['lead']:+7.2f}  "
                    f"自石{per(own_stones):+5.2f}/子  相手石{per(opp_stones):+5.2f}/子"
                )
    finally:
        engine.shutdown(finish=False)


main()
