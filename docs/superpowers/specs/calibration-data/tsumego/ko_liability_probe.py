"""候補手が守り方に「コウの権利」を残しているかを純盤面で判定する（KataGo 不要）。

`_ko_route_screen` は守り方の応手 PV にコウ形が現れるかで判定するので、**KataGo がその
コウを打つ価値なしと読んだ局面では証拠が出ない**（実測 case U: 白のコウ抵抗 C1 は visits比
0.01・lead も白に不利と評価され、どの応手 PV にもコウが現れない）。こちらは探索の好みに
一切依存せず、盤の形だけで

  immediate: 守り方が**今すぐ**打てるコウ取りがあるか（1子取り・取った石が呼吸点1・
             攻め方の取り返しがコウ禁止）
  setup:     守り方が**1手かけて**そのコウ取りを作れるか（攻め方の受けは考えない上界）

を出す。setup は上界なので、単独で「その候補は失格」と結論してはいけない
（攻め方が間に受ければ消える場合がある）。両側の実測を並べるための計測器。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/ko_liability_probe.py \
      <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv>
"""
import os
import sys

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.ai import _chain_and_liberties, tsumego_simulation_game  # noqa: E402
from katrain.core.constants import DATA_FOLDER  # noqa: E402
from katrain.core.game import BaseGame, IllegalMoveException  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import load_sgf_to_move  # noqa: E402

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
MOVES = [m.strip().upper() for m in sys.argv[4].split(",") if m.strip()]


def region_empties(sim):
    size_x, size_y = sim.board_size
    for x in range(max(0, REGION[0]), min(REGION[1], size_x - 1) + 1):
        for y in range(max(0, REGION[2]), min(REGION[3], size_y - 1) + 1):
            if sim.board[y][x] < 0:
                yield (x, y)


def immediate_ko(sim, defender):
    """守り方が今すぐ打てるコウ取り。あれば (取る手, 取り返し点) の GTP 対を返す"""
    attacker = "W" if defender == "B" else "B"
    base = sim.current_node
    for point in list(region_empties(sim)):
        try:
            sim.play(Move(coords=point, player=defender))
        except IllegalMoveException:
            sim.set_current_node(base)
            continue
        hit = None
        chain, liberties = _chain_and_liberties(sim, point)
        if chain is not None and len(chain) == 1 and len(liberties) == 1:
            try:
                sim.play(Move(coords=liberties[0], player=attacker))
            except IllegalMoveException as e:
                if "Ko" in str(e):
                    hit = (Move(coords=point).gtp(), Move(coords=liberties[0]).gtp())
        sim.set_current_node(base)
        if hit:
            return hit
    return None


def ko_setup(sim, defender):
    """守り方が1手かけてコウ取りを作れるか。あれば (仕掛け手, 取る手, 取り返し点)"""
    base = sim.current_node
    for point in list(region_empties(sim)):
        try:
            sim.play(Move(coords=point, player=defender))
        except IllegalMoveException:
            sim.set_current_node(base)
            continue
        hit = immediate_ko(sim, defender)
        sim.set_current_node(base)
        if hit:
            return (Move(coords=point).gtp(),) + hit
    return None


def main():
    stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
    node = load_sgf_to_move(SGF, MOVE_N)
    root = node
    while root.parent:
        root = root.parent
    game = BaseGame(katrain=stub, move_tree=root)
    game.set_current_node(node)
    game.region_of_interest = REGION
    player = node.next_player
    defender = "W" if player == "B" else "B"
    print(f"# {os.path.basename(SGF)} move={MOVE_N} region={REGION} solver={player} defender={defender}")
    base_sim = tsumego_simulation_game(game, node)
    if base_sim is not None:
        pre_imm = immediate_ko(base_sim, defender)
        pre_set = ko_setup(base_sim, defender)
        print(f"#   着手前: immediate={pre_imm} setup={pre_set}")
    for gtp in MOVES:
        sim = tsumego_simulation_game(game, node)
        if sim is None:
            print(f"{gtp:>4}  局面を再現できません")
            continue
        try:
            sim.play(Move.from_gtp(gtp, player=player))
        except IllegalMoveException:
            print(f"{gtp:>4}  着手不能")
            continue
        imm = immediate_ko(sim, defender)
        setup = ko_setup(sim, defender)
        flag = "IMMEDIATE" if imm else ("SETUP" if setup else "clean")
        print(f"{gtp:>4}  {flag:<10} immediate={imm} setup={setup}")


if __name__ == "__main__":
    main()
