# -*- coding: utf-8 -*-
"""余裕外しの「次の手番の罠」への影響を、同じ局面の 2 分岐で直接比べる反実仮想（2026-11-16・KataGo 起動あり）。

    PYTHONPATH=. python docs/superpowers/specs/calibration-data/enigma-relax/relax_branch_cf.py \
        experiments/selfplay/<dir> [--list] [--out branch_cf.json] [--horizon 4]
    python relax_branch_cf.py --report branch_cf.json      # 保存した結果の再集計（KataGo 不要）

自己対局 A/B の対の差は run 間ノイズに埋もれ、発動した対だけを見るのは結果で選別した標本になる（relax_ab_split.py）。
そこで、余裕外しが発動した局面（test アームの実発動）と、発動したはずの局面（base アームのログの Score 行に
実関数 enigma9_relax_pick を当てたもの）について、

    局面 P → 最善手 X → 相手の KataGo 最善応手 → 難解＋（余裕外し OFF）を実行
    局面 P → 外す手 R → 相手の KataGo 最善応手 → 難解＋（余裕外し OFF）を実行

の 2 分岐を同じエンジンで走らせ、次の AI 手番が罠を打つか・その E・候補プールの大きさを対で比べる。
実戦中の KaTrain と同時に走らせないこと。標準出力は ASCII のみ。
"""

import argparse
import json
import os
import re
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from relax_ab_report import load_jsonl, mean, se  # noqa: E402

RE_SCORE = re.compile(
    r"Score (\S+): vloss=([-\d.]+) \(raw ([-\d.]+)\) wr=([\d.]+)% E=([-\d.]+) cov=([-\d.]+) "
    r"find_hp=([-\d.]+) own_hp=([-\d.]+) .*net=([-\d.]+)"
)
RE_LEAD = re.compile(r"(?:Spend|Endgame budget): lead[=~]([-\d.]+)")
RE_POOL = re.compile(r"Pool: cap=([-\d.]+) min_wr=\d+% admissible=(\d+)")
RE_RELAX = re.compile(r"Relax: played (\S+) .* instead of (\S+) ")
RE_DEV = re.compile(r"Deviate: played (\S+) \(net=([-\d.]+), vloss=([-\d.]+), E=([-\d.]+)")
RE_GAMBLE = re.compile(r"Gamble: played (\S+) \(dE=([-+\d.]+), vloss=([-\d.]+)")
RE_OVER = re.compile(r"Overdraft: played (\S+) .*vloss=([-\d.]+), E=([-\d.]+)")
FLOOR, MAX_LOSS, MIN_HP, MAX_E_DROP = 12.0, 1.0, 0.1, 0.5


def summarize_turn(lines):
    """1 手番ぶんの戦略ログ → {kind, lead, admissible, scores, trap_e, relax}。"""
    t = {"kind": "other", "lead": None, "admissible": None, "scores": [], "trap_e": 0.0, "relax": None, "played": None}
    for line in lines:
        m = RE_LEAD.search(line)
        if m:
            t["lead"] = float(m.group(1))
        m = RE_POOL.search(line)
        if m:
            t["admissible"] = int(m.group(2))
            if t["admissible"] == 0:
                t["kind"] = "no_pool"
        m = RE_SCORE.search(line)
        if m:
            t["scores"].append(
                {
                    "gtp": m.group(1),
                    "loss": float(m.group(2)),
                    "wr_after": float(m.group(4)) / 100.0,
                    "e": float(m.group(5)),
                    "own_hp": float(m.group(8)),
                    "net": float(m.group(9)),
                }
            )
        m = RE_DEV.search(line)
        if m:
            t.update(kind="deviate", played=m.group(1), trap_e=float(m.group(4)))
        m = RE_GAMBLE.search(line)
        if m:
            t.update(kind="gamble", played=m.group(1))
        m = RE_OVER.search(line)
        if m:
            t.update(kind="overdraft", played=m.group(1), trap_e=float(m.group(3)))
        m = RE_RELAX.search(line)
        if m:
            t.update(kind="relax", relax=(m.group(1), m.group(2)))
        if "Opening handoff" in line:
            t["kind"] = "opening9d"
        if "Best move wins the confusion race" in line:
            t["kind"] = "best_race"
    return t


def log_turns(path):
    turns, cur = [], []
    with open(path, "rb") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace")
            if "Strategy] " not in line:
                continue
            cur.append(line)
            if "着手決定に" in line:
                turns.append(summarize_turn(cur))
                cur = []
    return turns


def collect_positions(d, base, test):
    """(arm, seed, color, depth, best X, relax R, source) の一覧。"""
    from relax_pick import enigma9_relax_pick

    games = {(g["arm"], g["seed"]): g for g in load_jsonl(os.path.join(d, "games.jsonl")) if not g.get("error")}
    ai = {}
    for m in load_jsonl(os.path.join(d, "moves.jsonl")):
        if m.get("is_ai") and not m.get("trailing_pass"):
            ai.setdefault((m["arm"], m["seed"]), []).append(m)
    out = []
    for (arm, seed), g in sorted(games.items()):
        if arm not in (base, test):
            continue
        mv = sorted(ai[(arm, seed)], key=lambda m: m["depth"])
        turns = log_turns(os.path.join(d, "logs", f"{arm}_{seed}_{g['ai_color']}.log"))
        if len(turns) != len(mv):
            raise SystemExit(f"log / moves misaligned: {arm} {seed}")
        for t, m in zip(turns, mv):
            row = None
            if arm == test and t["kind"] == "relax":
                row = {"best": t["relax"][1], "relax": t["relax"][0], "source": "fired"}
            elif arm == base and t["kind"] == "best_race" and t["scores"] and t["lead"] is not None:
                best = t["scores"][0]["gtp"]
                # ログに着手後リードは出ないので、着手前リードで近似する（最善手の検証済み損失は 0）
                pick, _ = enigma9_relax_pick(t["scores"], best, t["lead"], FLOOR, MAX_LOSS, MIN_HP, MAX_E_DROP)
                if t["lead"] >= FLOOR and pick is not None:
                    row = {"best": best, "relax": pick["gtp"], "source": "would_fire"}
            if row:
                row.update(arm=arm, seed=seed, color=g["ai_color"], depth=m["depth"], played=m["move"], lead=t["lead"])
                out.append(row)
    return out


def report(results, horizon):
    """対の集計: 分岐の後の AI 手番を h 手番ぶん累積して relax - best を出す。T=罠（数字は E）、b=最善手。"""
    print("\npaired (after relax - after best), AI turns after the branch move, relax OFF in both branches")
    for group, rows in (
        ("all", results),
        ("fired", [r for r in results if r["source"] == "fired"]),
        ("would_fire", [r for r in results if r["source"] == "would_fire"]),
    ):
        if not rows:
            continue
        print(f" {group} (n={len(rows)})")
        for h in range(1, horizon + 1):
            ok = [r for r in rows if len(r["best_turns"]) >= h and len(r["relax_turns"]) >= h]
            if not ok:
                continue
            for label, key in (
                ("traps played", "trap"),
                ("traps with E>=1", "trap_e1"),
                ("sum E of traps", "trap_e"),
            ):
                xs = [sum(t[key] for t in r["best_turns"][:h]) for r in ok]
                ys = [sum(t[key] for t in r["relax_turns"][:h]) for r in ok]
                ds = [y - x for x, y in zip(xs, ys)]
                m, s = mean(ds), se(ds)
                z = m / s if s and s > 0 else float("nan")
                print(
                    f"   first {h} turn(s) {label:<18} best {mean(xs):6.3f}  relax {mean(ys):6.3f}  "
                    f"diff {m:+.3f} (se {s:.3f}, z {z:+.2f}, n {len(ok)})"
                )
            # 一致の会計: 分岐の手そのもの（最善手=一致 1・外し=0）＋ その後 h 手番の「罠でない手番」
            ds = [
                (0 + sum(1 - t["trap"] for t in r["relax_turns"][:h]))
                - (1 + sum(1 - t["trap"] for t in r["best_turns"][:h]))
                for r in ok
            ]
            print(f"   first {h} turn(s) best-move turns incl. the branch move: diff {mean(ds):+.3f} (se {se(ds):.3f})")
        for h in range(1, horizon + 1):
            ok = [r for r in rows if len(r["best_turns"]) >= h and len(r["relax_turns"]) >= h]
            if ok:
                print(
                    f"   turn {h} alone: trap rate best {mean([r['best_turns'][h - 1]['trap'] for r in ok]):.3f}  "
                    f"relax {mean([r['relax_turns'][h - 1]['trap'] for r in ok]):.3f}  (n {len(ok)})"
                )

    # 原因の切り分け: 外す先と最善手の距離、先送りした最善手の打ち直し
    def cheb(r):
        cols = "ABCDEFGHJKLMNOPQRST"
        (a, b), (c, d) = [(cols.index(g[0]), int(g[1:])) for g in (r["best"], r["relax"])]
        return max(abs(a - c), abs(b - d))

    print(" by distance between the best move and the relax move (Chebyshev)")
    for name, rows in (
        ("near (<=2)", [r for r in results if cheb(r) <= 2]),
        ("far (>=3)", [r for r in results if cheb(r) >= 3]),
    ):
        for h in (2, horizon):
            dt = [sum(t["trap"] for t in r["relax_turns"][:h]) - sum(t["trap"] for t in r["best_turns"][:h]) for r in rows]
            de = [
                sum(t["trap_e"] for t in r["relax_turns"][:h]) - sum(t["trap_e"] for t in r["best_turns"][:h])
                for r in rows
            ]
            print(
                f"   {name:<10} n={len(rows)} first {h} turn(s): traps {mean(dt):+.2f} (se {se(dt):.2f})  "
                f"sum E {mean(de):+.2f} (se {se(de):.2f})"
            )
    nxt = sum(1 for r in results if r["relax_turns"] and r["relax_turns"][0]["move"] == r["best"])
    within = sum(1 for r in results if any(t["move"] == r["best"] for t in r["relax_turns"][:horizon]))
    print(
        f" deferred best move replayed in the relax branch: next turn {nxt}/{len(results)}, "
        f"within {horizon} turns {within}/{len(results)}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--report", default=None, help="保存済み JSON を再集計する")
    ap.add_argument("--base", default="A")
    ap.add_argument("--test", default="B")
    ap.add_argument("--list", action="store_true", help="局面の一覧だけ出す（KataGo を起動しない）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--horizon", type=int, default=4, help="分岐の後に追う AI の手番数")
    args = ap.parse_args()
    if args.report:
        with open(args.report, encoding="utf-8") as f:
            res = json.load(f)
        report(res, max(len(r["best_turns"]) for r in res))
        return

    pos = collect_positions(args.dir, args.base, args.test)
    print(
        f"positions: {len(pos)} (fired {sum(p['source'] == 'fired' for p in pos)}, "
        f"would_fire {sum(p['source'] == 'would_fire' for p in pos)})"
    )
    if args.list:
        for p in pos:
            print(
                f"  {p['source']:<10} {p['arm']} seed {p['seed']} move {p['depth']:3d} lead {p['lead']:.1f}: "
                f"{p['best']} -> {p['relax']} (played {p['played']})"
            )
        return

    from katrain.core.ai import STRATEGY_REGISTRY
    from katrain.core.constants import AI_ENIGMA_13_PLUS, DATA_FOLDER
    from katrain.core.engine import KataGoEngine
    from katrain.core.sgf_parser import Move
    from katrain_debug.katrain_stub import KaTrainStub
    from katrain_debug.runner import DebugGame, load_sgf_to_move

    stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=1, quiet=True)
    settings = dict(stub.config(f"ai/{AI_ENIGMA_13_PLUS}") or {})
    settings["enigma13plus_relax_min_lead"] = 0.0  # 両分岐とも余裕外し OFF＝従来の罠の選択だけを測る
    engine = KataGoEngine(stub, stub.config("engine"))

    def wait(node):
        node.analyze(engine)
        t0 = time.time()
        while not node.analysis_complete:
            time.sleep(0.05)
            engine.check_alive(exception_if_dead=True)
            if time.time() - t0 > 120:
                raise SystemExit("analysis timeout")

    results = []
    try:
        for i, p in enumerate(pos):
            sgf = os.path.join(args.dir, "sgf", f"{p['arm']}_{p['seed']}_{p['color']}.sgf")
            node = load_sgf_to_move(sgf, p["depth"] - 1)
            actual = node.children[0].move.gtp() if node.children else None
            if actual != p["played"]:
                print(f"  skip {p['arm']} {p['seed']} move {p['depth']}: sgf has {actual}, record has {p['played']}")
                continue
            root = node
            while root.parent:
                root = root.parent
            rec = dict(p)
            for label in ("best", "relax"):
                turns = []
                game = DebugGame(katrain=stub, engine=engine, move_tree=root)
                game.set_current_node(node)
                stub.game = game
                cur = game.play(Move.from_gtp(p[label], player=node.next_player))
                for _h in range(args.horizon):
                    wait(cur)
                    reply = cur.candidate_moves[0]["move"]
                    nxt = game.play(Move.from_gtp(reply, player=cur.next_player))
                    wait(nxt)
                    del stub.logs[:]
                    strategy = STRATEGY_REGISTRY[AI_ENIGMA_13_PLUS](game, settings)
                    move, _expl = strategy.generate_move()
                    t = summarize_turn([msg for msg, _lvl in stub.logs if "Strategy] " in msg])
                    best_e = t["scores"][0]["e"] if t["scores"] else None
                    is_trap = t["kind"] in ("deviate", "gamble", "overdraft")
                    turns.append(
                        {
                            "reply": reply,
                            "move": move.gtp(),
                            "kind": t["kind"],
                            "trap": 1.0 if is_trap else 0.0,
                            "trap_e": t["trap_e"],
                            "trap_e1": 1.0 if is_trap and t["trap_e"] >= 1.0 else 0.0,
                            "played_e": t["trap_e"] if t["kind"] in ("deviate", "overdraft") else best_e,
                            "admissible": t["admissible"],
                            "lead": t["lead"],
                        }
                    )
                    if move.gtp() == "pass" or reply == "pass":
                        break
                    cur = game.play(move)
                rec[label + "_turns"] = turns
            results.append(rec)

            def seq(turns):
                return " ".join(f"T{x['trap_e']:.1f}" if x["trap"] else "b" for x in turns)

            print(
                f"[{i + 1}/{len(pos)}] {p['source']:<10} {p['arm']} {p['seed']} move {p['depth']:3d} lead {p['lead']:.1f} "
                f"{p['best']}->{p['relax']} | after best: {seq(rec['best_turns'])} | after relax: {seq(rec['relax_turns'])}",
                flush=True,
            )
    finally:
        engine.shutdown(finish=False)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=True, indent=1)

    report(results, args.horizon)


if __name__ == "__main__":
    main()
