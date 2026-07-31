"""応手 PV を歩きながら「守り方が“今すぐ”打てるコウ取りを持ったか」を見る（案Aの最小テスト）。

現行 `tsumego_pv_reaches_region_ko` は **PV が実際にコウを打つ**ことを要求する。KataGo が
「そのコウは守り方の損」と読んだ局面では PV がコウを打たないので証拠が出ない（実測 case U:
白のコウ抵抗はどの応手 PV にも現れない）。こちらは同じ PV を歩きつつ、**守り方の手番になる
たびに「今すぐ取れるコウがあるか」を盤で調べる**＝コウを打たなくても権利の発生を捕まえる。

出力: PLAYED = 現行判定（PV がコウ形に到達）/ AVAIL = 新判定（守り方がコウ取りを持った ply）

usage:
  python docs/superpowers/specs/calibration-data/tsumego/ko_available_probe.py \
      <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [ratio] [repeats]
"""
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.ai import (  # noqa: E402
    TSUMEGO_KO_REGION_UNTIL_DEPTH,
    TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
    TSUMEGO_TIE_KO_PLIES,
    _chain_and_liberties,
    tsumego_candidate_reaches_region_ko,
    tsumego_competitive_replies,
    tsumego_simulation_game,
)
from katrain.core.constants import DATA_FOLDER  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import IllegalMoveException, region_analysis_extra_settings  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame, load_sgf_to_move  # noqa: E402

SGF = sys.argv[1]
MOVE_N = int(sys.argv[2])
REGION = [int(v) for v in sys.argv[3].split(",")]
MOVES = [m.strip().upper() for m in sys.argv[4].split(",") if m.strip()]
VISITS = int(sys.argv[5]) if len(sys.argv) > 5 else 800
RATIO = float(sys.argv[6]) if len(sys.argv) > 6 else 0.05
REPEATS = int(sys.argv[7]) if len(sys.argv) > 7 else 1


def in_region(coords):
    return REGION[0] <= coords[0] <= REGION[1] and REGION[2] <= coords[1] <= REGION[3]


def region_empties(sim):
    size_x, size_y = sim.board_size
    for x in range(max(0, REGION[0]), min(REGION[1], size_x - 1) + 1):
        for y in range(max(0, REGION[2]), min(REGION[3], size_y - 1) + 1):
            if sim.board[y][x] < 0:
                yield (x, y)


def immediate_ko(sim, defender):
    """守り方が今すぐ打てるコウ取り（1子取り・取った石が呼吸点1・取り返しがコウ禁止）"""
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
                    hit = Move(coords=point).gtp()
        sim.set_current_node(base)
        if hit:
            return hit
    return None


def walk_for_available_ko(game, node, candidate_gtp, reply_pv):
    """[候補手]+応手PV を歩き、守り方の手番になるたびにコウ取りの有無を調べる"""
    sim = tsumego_simulation_game(game, node)
    if sim is None:
        return None
    attacker = node.next_player
    defender = "W" if attacker == "B" else "B"
    pv = [candidate_gtp] + list(reply_pv or [])
    hits = []
    for i, gtp in enumerate(pv[: 1 + TSUMEGO_TIE_KO_PLIES]):
        if gtp == "pass":
            break
        mover = attacker if i % 2 == 0 else defender
        try:
            sim.play(Move.from_gtp(gtp, player=mover))
        except IllegalMoveException:
            break
        if mover == attacker:  # 守り方の手番になった -> 今すぐ取れるコウがあるか
            hit = immediate_ko(sim, defender)
            if hit:
                hits.append(f"ply{i + 1}:{hit}")
    return ",".join(hits) or None


def analyze_region(engine, node, visits, timeout=600.0):
    result = {}
    engine.request_analysis(
        node,
        callback=lambda analysis, partial_result: (
            None if partial_result else result.setdefault("root", {"moves": analysis.get("moveInfos")})
        ),
        error_callback=lambda error: result.setdefault("error", error),
        visits=visits,
        time_limit=False,
        ownership=False,
        region_of_interest=REGION,
        region_until_depth=TSUMEGO_KO_REGION_UNTIL_DEPTH,
        extra_settings=region_analysis_extra_settings(visits, TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE),
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
        print(f"# {os.path.basename(SGF)} move={MOVE_N} region={REGION} solver={player} visits={VISITS} ratio={RATIO}")
        for rep in range(REPEATS):
            print(f"--- run {rep + 1} ---")
            for gtp in MOVES:
                sim = tsumego_simulation_game(game, node)
                if sim is None:
                    print(f"{gtp:>4}  局面を再現できません")
                    continue
                try:
                    child = sim.play(Move.from_gtp(gtp, player=player))
                except IllegalMoveException:
                    print(f"{gtp:>4}  着手不能")
                    continue
                info = analyze_region(engine, child, VISITS)
                replies = (info or {}).get("moves") or []
                walk = tsumego_competitive_replies(replies, RATIO)
                played = [
                    r.get("move")
                    for r in walk
                    if tsumego_candidate_reaches_region_ko(game, node, gtp, r.get("pv") or [], REGION)
                ]
                avail = {}
                for r in walk:
                    hit = walk_for_available_ko(game, node, gtp, r.get("pv") or [])
                    if hit:
                        avail[r.get("move")] = hit
                print(
                    f"{gtp:>4}  PLAYED={'KO' if played else 'clean':<5} {played} | "
                    f"AVAIL={'KO' if avail else 'clean':<5} {avail} | "
                    f"walk={[(r.get('move'), r.get('visits')) for r in walk]}"
                )
    finally:
        engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
