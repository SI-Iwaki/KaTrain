"""応手予測（先読みの選手）の的中率プローブ: どの並び順が実際の応手を上位 K に入れるか（enigma spec 追記9）。

Reconstructs board-watch games from ~/.katrain/logs, and for every position after an AI move
(opponent to play) runs the same queries the enigma ponder / board-watch prefetch have at hand:
  clean 500v (probe-equivalent)  / humanSL 8v (rank_9d)  / full 2000v (own-node analysis)
then reports the rank of the reply the app actually played under each ordering.

usage: python ponder_pick_probe.py [game_YYYYMMDD_HHMMSS.log ...]   (既定は 2026-08-27 の13路監視対局3本)
       python ponder_pick_probe.py --summary                          (前回の JSON を集計し直す)
実測 2026-08-27（148局面）: KataGo visits順 top-5 47.3% / humanSL 9d 全盤順 top-5 62.2% / 旧 K1+H2 50.0%
"""

import os, sys, re, json, time, statistics

os.environ["KIVY_NO_ARGS"] = "1"
PROJECT = r"C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1"
sys.path.insert(0, PROJECT)
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame
from katrain.core.engine import KataGoEngine
from katrain.core.sgf_parser import Move
from katrain.core.constants import PRIORITY_EXTRA_AI_QUERY
from katrain.core.ai import enigma9_hp_lookup, ENIGMA9_HUMAN_PROFILE, ENIGMA9_REPLY_MIN_VISITS

LOGDIR = r"C:\Users\iwaki\.katrain\logs"
LOGS = sys.argv[1:] or ["game_20260827_155133.log", "game_20260827_154802.log", "game_20260823_051702.log"]
OUT = os.path.join(os.path.dirname(__file__), "ponder_pick_probe.json")


def parse(path):
    moves, size = [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        if size is None:
            m = re.search(r'"boardXSize": (\d+)', line)
            if m:
                size = int(m.group(1))
        m = re.search(r"Playing move (\w+) and creating", line)
        if m:
            moves.append(("ai", m.group(1)))
            continue
        m = re.search(r"相手の着手 (\w+) を反映", line)
        if m:
            moves.append(("opp", m.group(1)))
    return size, moves


def main():
    stub = KaTrainStub(os.path.expanduser("~/.katrain/config.json"), debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    positions = []  # dicts: log, idx, node, reply
    games = []
    try:
        for log in LOGS:
            size, moves = parse(os.path.join(LOGDIR, log))
            game = DebugGame(stub, engine, game_properties={"SZ": size, "KM": 7.0, "RU": "chinese"})
            games.append(game)
            color = "B"
            for i, (who, gtp) in enumerate(moves):
                node = game.play(Move.from_gtp(gtp, player=color))
                if who == "ai" and i + 1 < len(moves) and moves[i + 1][0] == "opp":
                    positions.append({"log": log, "idx": i, "node": node, "reply": moves[i + 1][1], "size": size})
                color = "W" if color == "B" else "B"
        print(f"positions: {len(positions)}", flush=True)

        results = {}

        def start(key, node, **kw):
            def cb(a, partial):
                if not partial:
                    results[key] = a

            def err(a):
                results[key] = None

            engine.request_analysis(node, callback=cb, error_callback=err, priority=PRIORITY_EXTRA_AI_QUERY, **kw)

        t0 = time.time()
        CHUNK = 10
        for c in range(0, len(positions), CHUNK):
            chunk = positions[c : c + CHUNK]
            for p in chunk:
                k = (p["log"], p["idx"])
                start(
                    (k, "clean"),
                    p["node"],
                    include_policy=False,
                    visits=500,
                    extra_settings={"ignorePreRootHistory": False},
                )
                start(
                    (k, "hp"),
                    p["node"],
                    include_policy=True,
                    visits=8,
                    extra_settings={"humanSLProfile": ENIGMA9_HUMAN_PROFILE, "ignorePreRootHistory": False},
                )
                start((k, "full"), p["node"], include_policy=True)
            want = {((p["log"], p["idx"]), kind) for p in chunk for kind in ("clean", "hp", "full")}
            while not want <= set(results):
                time.sleep(0.05)
                engine.check_alive(exception_if_dead=True)
            print(f"  {c + len(chunk)}/{len(positions)} done ({time.time() - t0:.0f}s)", flush=True)

        out = []
        for p in positions:
            k = (p["log"], p["idx"])
            clean, hp, full = results.get((k, "clean")), results.get((k, "hp")), results.get((k, "full"))
            if not clean or not hp or not full:
                continue
            reply = p["reply"]
            entries = [d for d in clean.get("moveInfos", []) if d.get("move") and d["move"] != "pass"]
            k_order = [d["move"] for d in sorted(entries, key=lambda d: -d.get("visits", 0))]
            hp_of = (
                enigma9_hp_lookup(hp["humanPolicy"], (p["size"], p["size"]))
                if hp.get("humanPolicy")
                else (lambda g: 0.0)
            )
            h_entries = [d for d in entries if d.get("visits", 0) >= ENIGMA9_REPLY_MIN_VISITS]
            h_order = [d["move"] for d in sorted(h_entries, key=lambda d: -hp_of(d["move"]))]
            # humanSL order over the whole board (not restricted to clean moveInfos)
            board = [Move((x, y)).gtp() for x in range(p["size"]) for y in range(p["size"])]
            h_all = sorted(board, key=lambda g: -hp_of(g))
            f_order = [
                d["move"]
                for d in sorted(
                    [d for d in full.get("moveInfos", []) if d.get("move") and d["move"] != "pass"],
                    key=lambda d: -d.get("visits", 0),
                )
            ]
            out.append(
                {
                    "log": p["log"],
                    "idx": p["idx"],
                    "reply": reply,
                    "k": k_order[:10],
                    "h": h_order[:10],
                    "h_all": h_all[:10],
                    "f": f_order[:10],
                    "clean_visits": clean.get("rootInfo", {}).get("visits"),
                }
            )
        json.dump(out, open(OUT, "w"), indent=1)
        summarize(out)
    finally:
        engine.shutdown(finish=False)


def rank(order, reply):
    return order.index(reply) + 1 if reply in order else 99


def summarize(out):
    n = len(out)
    print(f"\nn={n}")

    def hit(policy):
        return sum(1 for r in out if r["reply"] in policy(r)) / n

    def mixed(kn, hn):
        def pol(r):
            picks = list(r["k"][:kn])
            for g in r["h"]:
                if len(picks) >= kn + hn:
                    break
                if g not in picks:
                    picks.append(g)
            return picks

        return pol

    def interleave(total):
        def pol(r):
            picks = []
            ki = hi = 0
            while len(picks) < total and (ki < len(r["k"]) or hi < len(r["h"])):
                if ki < len(r["k"]):
                    g = r["k"][ki]
                    ki += 1
                    if g not in picks:
                        picks.append(g)
                if len(picks) < total and hi < len(r["h"]):
                    g = r["h"][hi]
                    hi += 1
                    if g not in picks:
                        picks.append(g)
            return picks

        return pol

    rows = [("current K1+H2", mixed(1, 2))]
    for k in (1, 2, 3, 4, 5, 6, 8):
        rows.append((f"K{k} (500v)", lambda r, k=k: r["k"][:k]))
    for k in (3, 5, 8):
        rows.append((f"H{k} (hp among clean)", lambda r, k=k: r["h"][:k]))
        rows.append((f"Hall{k} (hp whole board)", lambda r, k=k: r["h_all"][:k]))
        rows.append((f"F{k} (2000v)", lambda r, k=k: r["f"][:k]))
    rows += [
        ("K2+H1", mixed(2, 1)),
        ("K3+H2", mixed(3, 2)),
        ("K4+H1", mixed(4, 1)),
        ("K2+H3", mixed(2, 3)),
        ("interleave3", interleave(3)),
        ("interleave5", interleave(5)),
    ]
    for name, pol in rows:
        print(f"{name:26s} hit {hit(pol):5.1%}")
    ks = [rank(r["k"], r["reply"]) for r in out]
    fs = [rank(r["f"], r["reply"]) for r in out]
    print("median rank in K(500v):", statistics.median(ks), " in F(2000v):", statistics.median(fs))
    by_log = {}
    for r in out:
        by_log.setdefault(r["log"], []).append(r)
    for log, rs in by_log.items():
        print(
            log,
            "n",
            len(rs),
            "K1 %.0f%% K3 %.0f%% K5 %.0f%% cur %.0f%%"
            % (
                100 * sum(r["reply"] in r["k"][:1] for r in rs) / len(rs),
                100 * sum(r["reply"] in r["k"][:3] for r in rs) / len(rs),
                100 * sum(r["reply"] in r["k"][:5] for r in rs) / len(rs),
                100 * sum(r["reply"] in mixed(1, 2)(r) for r in rs) / len(rs),
            ),
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--summary":
        summarize(json.load(open(OUT)))  # 直近の JSON を集計し直すだけ（エンジン不要）
    else:
        main()
