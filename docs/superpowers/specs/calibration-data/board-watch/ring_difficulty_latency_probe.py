"""輪の難易度（board-watch spec 追記11）の速度ゲート。

相手の手を `Game.play` に入れてから、親局面（AI が打つ局面）の通常解析が終わるまでの秒数を、humanSL の先回り
ON/OFF で比べる。AI の着手生成は解析の完了を待ってから始まる（`__main__._do_update_state` は
`cn.analysis_complete` で `_do_ai_move` を呼ぶ）ので、先回りが着手を遅らせうるのはこの区間の GPU の取り合いだけ。
先回りは解析中に終わる（8visits）ので戦略の区間には残らない（ここで ready 率を数える）。

1 プロセス 1 アーム（同じ局面を同じプロセスで2回測ると NN キャッシュで2回目が速くなる）。ABBA で4回走らせ、
ring_latency_compare.py で局面ごとに対にして比べる。KaTrain で対局していないときに走らせる。

    python ring_difficulty_latency_probe.py --arm off --sgf "experiments/selfplay/20260926_0843_veil9-p1/sgf/*.sgf" --out runs/ring9-off-1.jsonl
"""

import argparse
import glob
import json
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)

from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import Game, KaTrainSGF  # noqa: E402
from katrain.core.move_difficulty import classify_ring_difficulty  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402


def longest_line(root):
    best, stack = [root], [[root]]
    while stack:
        path = stack.pop()
        if not path[-1].children and len(path) > len(best):
            best = path
        stack.extend(path + [child] for child in path[-1].children)
    return best


def positions(paths, every, start, per_file):
    out = []
    for path in paths:
        root = KaTrainSGF.parse_file(path)
        moves = [n.move for n in longest_line(root)[1:] if n.move is not None]
        size = root.board_size[0]
        komi = float(root.get_property("KM", 7.0))
        rules = root.get_property("RU", "chinese")
        picks = [d for d in range(start, len(moves) - 1, every) if not moves[d - 1].is_pass][:per_file]
        for d in picks:
            out.append(
                {
                    "sgf": os.path.basename(path),
                    "depth": d,
                    "size": size,
                    "komi": komi,
                    "rules": rules,
                    "moves": [(m.gtp(), m.player) for m in moves[:d]],
                }
            )
    return out


def wait_until(cond, timeout):
    deadline = time.perf_counter() + timeout
    while not cond():
        if time.perf_counter() > deadline:
            return False
        time.sleep(0.002)
    return True


def measure(stub, engine, pos, arm):
    game = Game(stub, engine, game_properties={"SZ": pos["size"], "KM": pos["komi"], "RU": pos["rules"]})
    stub.game = game
    wait_until(lambda: game.root.analysis_complete, 60.0)
    for gtp, player in pos["moves"][:-1]:
        game.play(Move.from_gtp(gtp, player=player), analyze=False)
    last_gtp, last_player = pos["moves"][-1]
    ai = "W" if last_player == "B" else "B"
    stub.players_info[ai].player_type = PLAYER_AI
    stub.players_info[last_player].player_type = PLAYER_HUMAN
    game.board_watch_active = True
    game.ring_difficulty_active = arm == "on"
    t0 = time.perf_counter()
    node = game.play(Move.from_gtp(last_gtp, player=last_player))  # 通常解析＋（on なら）先回り
    done = wait_until(lambda: node.analysis_complete, 120.0)
    t_analysis = time.perf_counter() - t0
    hp_ready = getattr(node, "ring_human_policy", None) is not None
    row = {
        "sgf": pos["sgf"],
        "depth": pos["depth"],
        "size": pos["size"],
        "arm": arm,
        "t_analysis": t_analysis,
        "complete": done,
        "root_visits": (node.analysis.get("root") or {}).get("visits"),
        "hp_ready": hp_ready,
    }
    if arm == "on":
        wait_until(lambda: getattr(node, "ring_human_policy", None) is not None, 5.0)
        infos = list((node.analysis.get("moves") or {}).values())
        cands = node.candidate_moves if infos else []
        best = cands[0]["move"] if cands else None
        size = (pos["size"], pos["size"])
        kind_hp, info_hp = classify_ring_difficulty(
            infos, cands, getattr(node, "ring_human_policy", None), best, ai, size
        )
        kind_kata, info_kata = classify_ring_difficulty(infos, cands, node.analysis.get("policy"), best, ai, size)
        row.update(
            {
                "kind_hp": kind_hp,
                "E_hp": info_hp.get("E"),
                "top_hp": info_hp.get("top_hp"),
                "gap": info_hp.get("gap"),
                "kind_kata": kind_kata,
                "E_kata": info_kata.get("E"),
                "top_kata": info_kata.get("top_hp"),
            }
        )
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["on", "off"], required=True)
    ap.add_argument("--sgf", required=True, help="glob（リポジトリ直下からの相対でよい）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--files", type=int, default=6)
    ap.add_argument("--every", type=int, default=8)
    ap.add_argument("--start", type=int, default=9)
    ap.add_argument("--per-file", type=int, default=6)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--config", default=os.path.expanduser("~/.katrain/config.json"))
    args = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(REPO, args.sgf)))[: args.files]
    pos = positions(paths, args.every, args.start, args.per_file)
    if not pos:
        raise SystemExit(f"no positions from {args.sgf}")
    warm = [
        {**pos[i % len(pos)], "depth": 3 + i, "moves": pos[i % len(pos)]["moves"][: 3 + i]} for i in range(args.warmup)
    ]
    stub = KaTrainStub(args.config, debug_level=0, quiet=True)
    engine = KataGoEngine(stub, {**stub.config("engine"), "allow_recovery": False})
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            for k, p in enumerate(warm + pos):
                row = measure(stub, engine, p, args.arm)
                row["warmup"] = k < len(warm)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(
                    f"{k + 1}/{len(warm) + len(pos)} {row['sgf']}@{row['depth']} {row['t_analysis']:.3f}s hp_ready={row['hp_ready']}"
                )
    finally:
        engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
