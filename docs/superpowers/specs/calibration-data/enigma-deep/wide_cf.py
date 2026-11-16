# -*- coding: utf-8 -*-
"""難解++ の設計前調査 2: 候補プールの外（KataGo の root 探索が 1 回も読まなかった手）に罠はあるか（2026-11-16）。

難解＋の挑戦者は「通常解析で visits >= 1 かつ生 loss が上限以下」の手だけ（13路の実戦で中央値 5 手）。
ここでは 18 局の AI 手番（手数 10〜74）を 3 手番おきに取り、**合法手すべて**について難解と同条件の子局面
プローブ（clean 500v + humanSL 9d 8v）と、安いふるい（clean SCREEN_VISITS）を撃って記録する。
集計は wide_cf_report.py（プール外の罠の在庫・ふるいの精度）。

実行（リポジトリのルートから・KataGo 起動あり・約 1 時間。実戦中の KaTrain と同時に走らせない）:
    python docs/superpowers/specs/calibration-data/enigma-deep/wide_cf.py [game ...]

出力は wide_rows/<game>.json（局ごと・既にあれば飛ばす）。標準出力は ASCII のみ。
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)
os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core import ai  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import KaTrainSGF, Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame  # noqa: E402

from deep_cf import GAMES, RECON, extract, rounded, run_batch, wait_node  # noqa: E402

OUT_DIR = os.path.join(HERE, "wide_rows")
DEPTH_LO, DEPTH_HI = 10, 75
EVERY = 3
SCREEN_VISITS = 40


def probe_turn(engine, game, node, settings):
    player = node.next_player
    sign = 1 if player == "B" else -1
    bs = game.board_size
    game.set_current_node(node)
    node.analyze(engine)
    if not wait_node(node, engine):
        return None
    root_lead = (node.analysis.get("root") or {}).get("scoreLead")
    cands = node.candidate_moves
    if root_lead is None or not cands or cands[0]["move"] == "pass":
        return None
    lead = sign * root_lead
    best_gtp = cands[0]["move"]
    strat = ai.Enigma13PlusStrategy(game, settings)
    max_loss = float(strat._setting("max_loss"))
    large = float(strat._setting("large_lead_max_loss"))
    min_wr = float(strat._setting("min_winrate"))
    target = float(strat._setting("target_score"))
    cap, cw, _budget = ai.enigma9_spending_plan(lead, target, max_loss, large)
    candidates, _n = ai.parity9_build_candidates(cands, player=player, min_visits=ai.ENIGMA9_POOL_MIN_VISITS)
    pool = ai.enigma9_admissible(candidates, best_gtp, cap, min_wr)
    shortlist = {c["gtp"] for c in (strat._shortlist(pool) if pool else [])}
    by_gtp = {c["gtp"]: c for c in candidates}
    kata = {c["move"]: c for c in cands}
    played = node.children[0].move.gtp() if node.children and node.children[0].move else None

    stones = {m.coords for m in game.stones}
    gtps = []
    for x in range(bs[0]):
        for y in range(bs[1]):
            if (x, y) not in stones:
                gtps.append(Move((x, y), player=player).gtp())
    jobs = []
    for g in gtps:
        mv = Move.from_gtp(g, player=player)
        jobs.append(
            (
                (g, "screen"),
                node,
                dict(
                    next_move=mv,
                    include_policy=False,
                    visits=SCREEN_VISITS,
                    extra_settings={"ignorePreRootHistory": False},
                ),
            )
        )
        jobs.append(
            (
                (g, "clean"),
                node,
                dict(
                    next_move=mv,
                    include_policy=False,
                    visits=ai.ENIGMA9_CHILD_VISITS,
                    extra_settings={"ignorePreRootHistory": False},
                ),
            )
        )
        jobs.append(
            (
                (g, "hp"),
                node,
                dict(
                    next_move=mv,
                    include_policy=True,
                    visits=ai.ENIGMA9_HP_CHILD_VISITS,
                    extra_settings={"humanSLProfile": ai.ENIGMA9_HUMAN_PROFILE, "ignorePreRootHistory": False},
                ),
            )
        )
    jobs.append(
        (
            (None, "parent_hp"),
            node,
            dict(
                include_policy=True,
                ownership=False,
                visits=ai.ENIGMA9_HP_CHILD_VISITS,
                extra_settings={"humanSLProfile": ai.ENIGMA9_HUMAN_PROFILE, "ignorePreRootHistory": False},
            ),
        )
    )
    t0 = time.time()
    res = run_batch(engine, jobs, timeout=600)
    secs = time.time() - t0
    parent_hp = res.get((None, "parent_hp"))
    if not parent_hp or "humanPolicy" not in parent_hp:
        return None
    own_hp_of = ai.enigma9_hp_lookup(parent_hp["humanPolicy"], bs)
    kata_pol_of = ai.enigma9_hp_lookup(parent_hp["policy"], bs) if parent_hp.get("policy") else (lambda g: None)
    best_m = extract(res.get((best_gtp, "clean")), res.get((best_gtp, "hp")), player, bs)
    best_s = extract(res.get((best_gtp, "screen")), res.get((best_gtp, "hp")), player, bs)
    if best_m is None or best_s is None:
        return None
    row = {
        "depth": node.depth,
        "player": player,
        "lead": lead,
        "cap": cap,
        "cw": cw,
        "best": best_gtp,
        "played": played,
        "n_pool": len(pool),
        "n_legal": len(gtps),
        "secs": secs,
        "moves": [],
    }
    for g in gtps:
        m = extract(res.get((g, "clean")), res.get((g, "hp")), player, bs)
        if m is None:
            continue  # 着手禁止点・プローブ失敗
        s = extract(res.get((g, "screen")), res.get((g, "hp")), player, bs)
        c = by_gtp.get(g) or {}
        row["moves"].append(
            {
                "gtp": g,
                "vloss": best_m["lead_after"] - m["lead_after"],
                "wr_after": m["wr_after"],
                "e": m["e"],
                "find": m["find"],
                "e_fooled": m["e_fooled"],
                "p_fooled": m["p_fooled"],
                "cov": m["cov"],
                "own_hp": own_hp_of(g),
                "kata_pol": kata_pol_of(g),
                "root_visits": (kata.get(g) or {}).get("visits", 0),
                "raw_loss": c.get("loss"),
                "in_pool": any(p["gtp"] == g for p in pool),
                "in_shortlist": g in shortlist,
                "best_reply": m["best_reply"],
                "best_reply_hp": m["best_reply_hp"],
                "s_vloss": None if s is None else best_s["lead_after"] - s["lead_after"],
                "s_wr": None if s is None else s["wr_after"],
                "s_e": None if s is None else s["e"],
                "s_find": None if s is None else s["find"],
                "s_cov": None if s is None else s["cov"],
            }
        )
    return row


def main():
    games = json.load(open(GAMES, encoding="utf-8"))
    only = sys.argv[1:]
    os.makedirs(OUT_DIR, exist_ok=True)
    cfg_path = os.path.expanduser("~/.katrain/config.json")
    settings = json.load(open(cfg_path, encoding="utf-8"))["ai"]["ai:enigma13plus"]
    json.dump(settings, open(os.path.join(OUT_DIR, "_settings.json"), "w", encoding="utf-8"), indent=1)
    stub = KaTrainStub(cfg_path, debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    t_all = time.time()
    try:
        for s in games:
            g, ai_color = s["game"], s["ai"]
            out_path = os.path.join(OUT_DIR, g + ".json")
            if (only and g not in only) or os.path.exists(out_path):
                continue
            root = KaTrainSGF.parse_file(os.path.join(RECON, g + ".sgf"))
            game = DebugGame(katrain=stub, engine=engine, move_tree=root)
            stub.game = game
            n, t0, rows, k = root, time.time(), [], 0
            while n.children:
                n = n.children[0]
                if n.next_player != ai_color or not (DEPTH_LO <= n.depth < DEPTH_HI) or not n.children:
                    continue
                k += 1
                if k % EVERY != 1:
                    continue
                row = probe_turn(engine, game, n, settings)
                if row is None:
                    continue
                row.update({"game": g, "strategy": s["strategy"]})
                rows.append(row)
            json.dump(rounded(rows), open(out_path, "w", encoding="utf-8"), separators=(",", ":"))
            print("%s ai=%s turns=%d %.0fs" % (g, ai_color, len(rows), time.time() - t0), flush=True)
    finally:
        engine.shutdown(finish=False)
    print("done in %.0fs" % (time.time() - t_all), flush=True)


if __name__ == "__main__":
    main()
