"""実 TsumegoOwnershipStrategy.generate_move を回す E2E 回帰スクリプト（検証・救済経路込み）。

select_tsumego_move 単体の A/B は generate_move 側の後段（score_best 同深さ検証・救済）を
通らないので、そこで巻き戻される回帰を見逃す（実測 case J: select は N10 を選んだのに
無条件の score_best 検証が却下して N11 に巻き戻し、GUI で誤答が再発した）。
選択則を変えたら select レベルの A/B に加えて必ずこれも回すこと。

usage: python docs/superpowers/specs/calibration-data/tsumego/generate_move_e2e.py <sgf> <moves_csv> <xmin,xmax,ymin,ymax> [repeats] [--line=GTP,GTP,...]
例:    ... case-j-points-tie-20260730.sgf 0,10 6,12,1,12 3
       ... case-d-gain-region-20260730.sgf 0,2,4,6 0,8,0,8 3 --line=C2,B2,D1,B1,A4,C1,B3

`--line` は**正解手順**（SGF root から交互に打つ GTP 列）。SGF の本譜は「実際に打たれた手順」＝
誤答を含む線であることが多く（`children[0]` を辿る既定動作では正解手順を再生できない）、
正解が分岐（variation）側に記録されているケースがある。`--line` を渡すと SGF の着手は無視して
その列を root から打ち直すので、**初手から正解までの各黒番**を1手ずつ回帰できる。
"""
import os
import sys
import time
from collections import Counter

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER
from katrain.core.ai import STRATEGY_REGISTRY
from katrain.core.engine import KataGoEngine
from katrain.core.game import Move, region_analysis_extra_settings
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
LINE_ARG = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--line=")), None)
LINE = [m.strip().upper() for m in LINE_ARG.split(",") if m.strip()] if LINE_ARG else None
SGF = ARGS[0]
MOVES = [int(m) for m in ARGS[1].split(",")]
REGION = [int(v) for v in ARGS[2].split(",")]
REPEATS = int(ARGS[3]) if len(ARGS) > 3 else 3
VISITS = 1800


def build_game(engine, stub, move_n):
    """指定手数まで進めた局面の (game, node) を返す。`--line` があればその手順で打ち直す。"""
    if LINE is None:
        node = load_sgf_to_move(SGF, move_n)
        root = node
        while root.parent:
            root = root.parent
        game = DebugGame(katrain=stub, engine=engine, move_tree=root)
        game.set_current_node(node)
        return game, node
    root = load_sgf_to_move(SGF, 0)
    game = DebugGame(katrain=stub, engine=engine, move_tree=root)
    game.set_current_node(root)
    for gtp in LINE[:move_n]:
        game.play(Move.from_gtp(gtp, player=game.current_node.next_player))
    return game, game.current_node


def analyse(engine, stub, move_n):
    game, node = build_game(engine, stub, move_n)
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
    # `--debug` で戦略の判定ログ（gain順・コウ経路検査・救済・格下げ…）をそのまま出す。
    # 誤答の run とそうでない run で**どの経路が分岐したか**はこれが無いと分からない
    debug = "--debug" in sys.argv
    stub = KaTrainStub(
        os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")),
        debug_level=1 if debug else 0,
        quiet=not debug,
    )
    engine = KataGoEngine(stub, stub.config("engine"))
    settings = dict(stub.config(f"ai/{AI_TSUMEGO}") or {})
    # `--settings k=v k=v` で戦略パラメータを上書き（閾値の A/B を config を触らずに測るため）
    for arg in sys.argv[1:]:
        if not arg.startswith("--settings="):
            continue
        for pair in arg.split("=", 1)[1].split(","):
            key, _, raw = pair.partition(":")
            if not key:
                continue
            try:
                value = int(raw) if raw.lstrip("-").isdigit() else float(raw)
            except ValueError:
                value = {"true": True, "false": False}.get(raw.lower(), raw)
            settings[key.strip()] = value
    print("settings:", settings)
    tally = {}
    timing = {}
    try:
        for rep in range(REPEATS):
            for move_n in MOVES:
                t0 = time.time()
                game, node = analyse(engine, stub, move_n)
                t1 = time.time()
                strategy = STRATEGY_REGISTRY[AI_TSUMEGO](game, settings)
                move, thoughts = strategy.generate_move()
                t2 = time.time()
                gtp_move = move.gtp()
                print(
                    f"run{rep + 1} after {move_n:>2} moves: generate_move -> {gtp_move}  ({thoughts})"
                    f"  [analyse {t1 - t0:.1f}s / generate {t2 - t1:.1f}s]"
                )
                tally.setdefault(move_n, Counter())[gtp_move] += 1
                timing.setdefault(move_n, []).append((t1 - t0, t2 - t1))
    finally:
        engine.shutdown(finish=False)
    print("\n=== tally (real generate_move) ===")
    for move_n in MOVES:
        times = timing.get(move_n, [])
        avg_a = sum(t[0] for t in times) / max(1, len(times))
        avg_g = sum(t[1] for t in times) / max(1, len(times))
        print(f"after {move_n:>2} moves: {dict(tally[move_n])}  [avg analyse {avg_a:.1f}s / generate {avg_g:.1f}s]")


main()
