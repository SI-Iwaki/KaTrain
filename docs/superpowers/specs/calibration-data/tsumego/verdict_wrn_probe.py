# 残る true_miss 2件の関係手について、子局面 verdict（役割石1子平均）を
# wRN=0 / wRN=0.04 の両条件で測る。**プロセス間分散を見るため1回の実行で1サンプル**。
# usage: python verdict_wrn_probe.py <key10> <wrn> <move1,move2,...>
import argparse
import json
import os
import sys

os.environ["KIVY_NO_ARGS"] = "1"
from kivy.config import Config as _KivyConfig

_KivyConfig.set("graphics", "window_state", "hidden")

HERE = r"C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1\docs\superpowers\specs\calibration-data\tsumego"
sys.path.insert(0, HERE)

import katrain.__main__  # noqa: F401,E402

from katrain.core.ai import (  # noqa: E402
    STRATEGY_REGISTRY,
    tsumego_region_stones_by_player,
    tsumego_role_stones,
    tsumego_solver_attacks,
    tsumego_success_ownership,
)
from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402

from answer_book_replay import ReplayHost, analyse, build_game, choose_board, entry_to_grid, region4  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("key10")
ap.add_argument("wrn", type=float)
ap.add_argument("moves")
ap.add_argument("--prefix", default="", help="カンマ区切りの手順 prefix（d2 以降の判断を測るとき）")
args = ap.parse_args()

book = json.load(open(os.path.expanduser("~/.katrain/tsumego_answers.json"), encoding="utf-8"))["entries"]
key = [k for k in book if k.startswith(args.key10)][0]
entry = book[key]

config_path = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))
host = ReplayHost(config_path, debug_level=0, quiet=True)
settings = dict(host.config("tsumego_capture") or {})
ai_settings = dict(host.config(f"ai/{AI_TSUMEGO}") or {})
komi = host.config("game/komi", 6.5)
engine = KataGoEngine(host, host.config("engine"))
host.engine = engine
try:
    grid = entry_to_grid(entry)
    board, analysis_region, solver_problem, route = choose_board(
        host, grid, komi, settings,
        ko=settings.get("frame_ko", False), margin=int(settings.get("frame_margin", 4)),
    )
    region = region4(analysis_region, entry["size"])
    prefix = [g for g in args.prefix.split(",") if g.strip()]
    game = build_game(
        host, engine, board, komi, region,
        int(settings.get("analysis_visits", 1800)) or None,
        float(settings.get("region_wide_root_noise", 0.04)),
        solver_problem, prefix,
    )
    analyse(engine, game)
    cn = game.current_node
    strategy = STRATEGY_REGISTRY[AI_TSUMEGO](game, ai_settings)
    player_sign = cn.player_sign(cn.next_player)
    own_stones, opponent_stones = tsumego_region_stones_by_player(
        game.stones, game.region_of_interest, cn.next_player
    )
    solver_attacks = tsumego_solver_attacks(game.stones, game.region_of_interest, game.board_size, cn.next_player)
    role_stones = tsumego_role_stones(own_stones, opponent_stones, solver_attacks)
    visits = int(ai_settings.get("gain_verify_visits", 800))
    out = {"key": args.key10, "wrn": args.wrn, "route": route, "solver_attacks": solver_attacks}
    for mv in args.moves.split(","):
        verdict = strategy._region_child_verdict(mv, role_stones, player_sign, visits, wide_root_noise=args.wrn)
        if verdict is None or verdict.get("ownership") is None:
            out[mv] = None
            continue
        per = tsumego_success_ownership(
            verdict["ownership"], own_stones, opponent_stones, game.board_size, player_sign, solver_attacks
        )
        role_per = verdict["value"] / len(role_stones) if role_stones else None
        out[mv] = {"hedge": round(per, 3) if per is not None else None,
                   "role": round(role_per, 3) if role_per is not None else None,
                   "ko": verdict.get("ko")}
    print("RESULT " + json.dumps(out, ensure_ascii=False), flush=True)
finally:
    engine.shutdown(finish=False)
