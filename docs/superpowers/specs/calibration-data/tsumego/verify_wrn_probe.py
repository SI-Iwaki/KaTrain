"""同深さ検証（`_verified_choice`）の検証値を wideRootNoise を変えて測る。

`_verified_choice` は「候補を1手進めて `_analyze_region_root(visits, ownership=True)`（untilDepth は
既定=1）→ リージョン石の絶対 ownership」で覆すかどうかを決めるが、このクエリは **wRN=0.04 のまま**で、
コウ経路検査で直したのと同じ「着手選択用のノイズを裁定に流用している」状態にある。

マージン（`gain_verify_margin`=0.3 / `gain_rescue_margin`=1.0）が根拠にしている**分離幅**が
wRN=0 で広がって安定するのか、それとも縮むのかを、コードを変える前に確かめるための計測。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/verify_wrn_probe.py \
      <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [wide_root_noise]
  例: ... case-f-gain-visit-share-20260730.sgf 2 4,12,3,12 N8,N7,N6 800 0.0

先頭の手を incumbent として差分を出す。**必ずプロセスを分けて複数回回すこと**
（1プロセス内の再クエリは探索木が再利用されて独立サンプルにならない）。
"""
import os
import sys

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.ai import STRATEGY_REGISTRY, tsumego_absolute_ownership, tsumego_gain_stones
from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.ai import tsumego_simulation_game
from katrain.core.game import IllegalMoveException
from katrain.core.sgf_parser import Move
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
MOVES = [m.strip().upper() for m in sys.argv[4].split(",") if m.strip()]
VISITS = int(sys.argv[5]) if len(sys.argv) > 5 else 800
WRN = float(sys.argv[6]) if len(sys.argv) > 6 else 0.04


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
        stones = tsumego_gain_stones([s.coords for s in game.stones], REGION)
        sign = node.player_sign(node.next_player)
        strategy = STRATEGY_REGISTRY[AI_TSUMEGO](game, dict(stub.config(f"ai/{AI_TSUMEGO}") or {}))
        sim = tsumego_simulation_game(game, node)
        base = sim.current_node
        print(f"# {os.path.basename(SGF)} move={MOVE_N} region={REGION} visits={VISITS} wRN={WRN} 石{len(stones)}子")
        values = {}
        for m in MOVES:
            sim.set_current_node(base)
            try:
                child = sim.play(Move.from_gtp(m, player=node.next_player))
            except IllegalMoveException:
                print(f"   {m:>4}  打てません")
                continue
            info = strategy._analyze_region_root(child, VISITS, ownership=True, wide_root_noise=WRN)
            if info is None or info.get("ownership") is None:
                print(f"   {m:>4}  解析失敗")
                continue
            values[m] = tsumego_absolute_ownership(info["ownership"], stones, game.board_size, sign)
            print(f"   {m:>4}  検証値{values[m]:+8.2f}  目数{sign * info['lead']:+7.2f}")
        if len(values) >= 2:
            first = MOVES[0]
            if first in values:
                print(f"   -- {first} との差 --")
                for m in MOVES[1:]:
                    if m in values:
                        print(f"   {m:>4}  {values[m] - values[first]:+8.2f}")
    finally:
        engine.shutdown(finish=False)


main()
