# -*- coding: utf-8 -*-
"""難解++ の設計前調査: 「1手先の E」の地平線を 2〜3 手先へ伸ばした信号の反実仮想ハーネス（2026-11-16）。

実戦ログから復元した 13 路 18 局（selfplay/recon/*.sgf）の AI 手番（手数 10〜74＝序盤委譲の後・ヨセ前）ごとに、
難解＋が今のユーザー設定で組む挑戦者（最善手＋安い順 7 手＋spread）と実際に打った手について:

  L1  子局面プローブ（難解と同条件 clean 500v + humanSL 9d 8v）＝既存の E・find・vloss ＋ KataGo の生フィールド
  L2  その手に対する応手 r（humanSL 上位 3 手 ∪ 最善応手）ごとに、こちらの継続 m2（r の PV の 2 手目）を
      打った局面の同条件プローブ＝「相手の次の判断」の E・find（＝2 手先の難しさ）
  L3  正解手順（最善応手を続けた線）だけもう 1 段（3 手先）

を記録する。集計は deep_cf_report.py（実現値＝selfplay/recon/report_<game>.json との突き合わせ・在庫）。

実行（リポジトリのルートから・KataGo 起動あり・1 局 5〜8 分。実戦中の KaTrain と同時に走らせない）:
    python docs/superpowers/specs/calibration-data/enigma-deep/deep_cf.py [game ...]

出力は rows/<game>.json（局ごと・既にあれば飛ばす＝再開できる）。標準出力は ASCII のみ。
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
from katrain.core.game import IllegalMoveException, KaTrainSGF, Move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame  # noqa: E402

RECON = os.path.join(HERE, "..", "selfplay", "recon")
GAMES = os.path.join(HERE, "..", "enigma-overdraft", "recon", "games.json")
OUT_DIR = os.path.join(HERE, "rows")

DEPTH_LO, DEPTH_HI = 10, 75
TOP_REPLIES = 3  # L2 で枝を張る応手数（humanSL 順）。最善応手は別枠で必ず入れる
MIN_REPLY_HP = 0.03  # これ未満の応手には枝を張らない
ASYM_OPP = "1d"  # 非対称プロファイル（AI=9d・相手=これ）の humanScoreMean も記録する


def wait_node(node, engine, timeout=180):
    t0 = time.time()
    while not node.analysis_complete:
        time.sleep(0.02)
        engine.check_alive(exception_if_dead=True)
        if time.time() - t0 > timeout:
            return False
    return True


def run_batch(engine, jobs, timeout=300):
    """jobs: [(key, node, kwargs)] を全部発行してから待つ。返り値 {key: analysis|None}。"""
    results = {}

    def issue(key, node, kwargs):
        def cb(a, partial_result):
            if not partial_result:
                results[key] = a

        def err(a):
            results[key] = None

        engine.request_analysis(node, callback=cb, error_callback=err, **kwargs)

    for key, node, kwargs in jobs:
        issue(key, node, kwargs)
    t0 = time.time()
    while len(results) < len(jobs):
        time.sleep(0.01)
        engine.check_alive(exception_if_dead=True)
        if time.time() - t0 > timeout:
            break
    return results


def probe_jobs(key, node, mv, asym=None):
    jobs = [
        (
            (key, "clean"),
            node,
            dict(
                next_move=mv,
                include_policy=False,
                visits=ai.ENIGMA9_CHILD_VISITS,
                extra_settings={"ignorePreRootHistory": False},
            ),
        ),
        (
            (key, "hp"),
            node,
            dict(
                next_move=mv,
                include_policy=True,
                visits=ai.ENIGMA9_HP_CHILD_VISITS,
                extra_settings={"humanSLProfile": ai.ENIGMA9_HUMAN_PROFILE, "ignorePreRootHistory": False},
            ),
        ),
    ]
    if asym:
        jobs.append(
            (
                (key, "hpx"),
                node,
                dict(
                    next_move=mv,
                    include_policy=False,
                    visits=ai.ENIGMA9_HP_CHILD_VISITS,
                    extra_settings={"humanSLProfile": asym, "ignorePreRootHistory": False},
                ),
            )
        )
    return jobs


def extract(clean, hp, player, board_size):
    """子局面（相手番）の解析から E・find・応手表・生フィールドを取り出す。取れなければ None。"""
    if not clean or not clean.get("moveInfos") or not hp or "humanPolicy" not in hp:
        return None
    opponent = "W" if player == "B" else "B"
    sign = 1 if player == "B" else -1
    lead_after, wr_after = ai.enigma9_verified_metrics(clean, player)
    if lead_after is None:
        return None
    replies, best_reply = ai.enigma9_reply_table(clean["moveInfos"], opponent)
    if not replies:
        return None
    hp_of = ai.enigma9_hp_lookup(hp["humanPolicy"], board_size)
    e, cov = ai.enigma9_expected_punish(replies, hp_of)
    find = ai.enigma9_reply_findability(replies, hp_of)
    e_fooled, p_fooled = ai.enigma9_fooled_punish(replies, hp_of)
    info = {d["move"]: d for d in clean["moveInfos"]}
    ri, hri = clean.get("rootInfo") or {}, hp.get("rootInfo") or {}
    table = sorted(
        (
            {
                "gtp": r["gtp"],
                "hp": hp_of(r["gtp"]),
                "loss": r["loss"],
                "v": r["visits"],
                "prior": (info.get(r["gtp"]) or {}).get("prior"),
                "pv": ((info.get(r["gtp"]) or {}).get("pv") or [])[:4],
            }
            for r in replies
        ),
        key=lambda t: -t["hp"],
    )
    n_adequate = sum(1 for r in replies if r["loss"] <= ai.ENIGMA9_ADEQUATE_LOSS)
    return {
        "lead_after": lead_after,
        "wr_after": wr_after,
        "e": e,
        "cov": cov,
        "find": find,
        "e_fooled": e_fooled,
        "p_fooled": p_fooled,
        "best_reply": best_reply,
        "best_reply_hp": hp_of(best_reply),
        "best_reply_prior": (info.get(best_reply) or {}).get("prior"),
        "n_adequate": n_adequate,
        "n_replies": len(replies),
        "raw_lead": None if ri.get("rawLead") is None else sign * ri["rawLead"],
        "raw_st_score_err": ri.get("rawStScoreError"),
        "raw_st_wr_err": ri.get("rawStWrError"),
        "score_stdev": ri.get("scoreStdev"),
        "human_score": None if hri.get("humanScoreMean") is None else sign * hri["humanScoreMean"],
        "human_st_score_err": hri.get("humanStScoreError"),
        "human_score_stdev": hri.get("humanScoreStdev"),
        "replies": [t for t in table if t["hp"] >= 0.005 or t["gtp"] == best_reply][:10],
    }


def pick_branches(m):
    """L2 で枝を張る応手: humanSL 上位 TOP_REPLIES（hp >= MIN_REPLY_HP・PV に継続手あり）∪ 最善応手。"""
    out = []
    for t in m["replies"]:
        if t["gtp"] == "pass" or len(t["pv"]) < 2 or t["pv"][1] == "pass":
            continue
        if t["gtp"] == m["best_reply"] or (
            t["hp"] >= MIN_REPLY_HP and sum(1 for o in out if not o["is_best"]) < TOP_REPLIES
        ):
            out.append(
                {
                    "reply": t["gtp"],
                    "hp": t["hp"],
                    "loss": t["loss"],
                    "m2": t["pv"][1],
                    "is_best": t["gtp"] == m["best_reply"],
                }
            )
    return out


def probe_turn(engine, game, node, settings):
    player = node.next_player
    opponent = "W" if player == "B" else "B"
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
    shortlist = strat._shortlist(pool) if pool else []
    by_gtp = {c["gtp"]: c for c in candidates}
    played = node.children[0].move.gtp() if node.children and node.children[0].move else None
    actual_reply = None
    if node.children and node.children[0].children and node.children[0].children[0].move:
        actual_reply = node.children[0].children[0].move.gtp()
    gtps = [best_gtp] + [c["gtp"] for c in shortlist if c["gtp"] != best_gtp]
    if played and played != "pass" and played not in gtps:
        gtps.append(played)
    asym = ("rank_9d_%s" if player == "B" else "rank_%s_9d") % ASYM_OPP
    if player == "W":
        asym = "rank_%s_9d" % ASYM_OPP

    # ---- L1 ----
    jobs = []
    for g in gtps:
        jobs += probe_jobs(("L1", g), node, Move.from_gtp(g, player=player), asym=asym)
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
    res = run_batch(engine, jobs)
    parent_hp = res.get((None, "parent_hp"))
    if not parent_hp or "humanPolicy" not in parent_hp:
        return None
    own_hp_of = ai.enigma9_hp_lookup(parent_hp["humanPolicy"], bs)
    best_m = extract(res.get((("L1", best_gtp), "clean")), res.get((("L1", best_gtp), "hp")), player, bs)
    if best_m is None:
        return None
    row = {
        "depth": node.depth,
        "player": player,
        "lead": lead,
        "cap": cap,
        "cw": cw,
        "best": best_gtp,
        "played": played,
        "actual_reply": actual_reply,
        "n_pool": len(pool),
        "cands": [],
    }
    l1 = {}
    for g in gtps:
        m = extract(res.get((("L1", g), "clean")), res.get((("L1", g), "hp")), player, bs)
        if m is None:
            continue
        hpx = (res.get((("L1", g), "hpx")) or {}).get("rootInfo") or {}
        m["human_score_asym"] = None if hpx.get("humanScoreMean") is None else sign * hpx["humanScoreMean"]
        m["human_wr_asym"] = (
            None
            if hpx.get("humanWinrate") is None
            else (hpx["humanWinrate"] if player == "B" else 1.0 - hpx["humanWinrate"])
        )
        c = by_gtp.get(g) or {}
        m.update(
            {
                "gtp": g,
                "vloss": best_m["lead_after"] - m["lead_after"],
                "own_hp": own_hp_of(g),
                "raw_loss": c.get("loss"),
                "visits": c.get("visits", 0),
                "in_shortlist": any(s["gtp"] == g for s in shortlist),
                "branches": [],
            }
        )
        l1[g] = m

    # ---- L2: 応手ごとに「こちらの継続を打った後の相手の判断」をプローブ ----
    sim = ai.tsumego_simulation_game(game, node)
    if sim is None:
        row["cands"] = list(l1.values())
        return row
    base = sim.current_node
    jobs, branch_nodes = [], {}
    for g, m in l1.items():
        # 検証で上限・勝率フロアを割った挑戦者には枝を張らない（最善手と実際に打った手は常に張る）
        if g not in (best_gtp, played):
            if m["vloss"] > cap or (m["wr_after"] is not None and m["wr_after"] < min_wr):
                continue
        try:
            sim.set_current_node(base)
            node_m = sim.play(Move.from_gtp(g, player=player), ignore_ko=True)
        except IllegalMoveException:
            continue
        for b in pick_branches(m):
            try:
                sim.set_current_node(node_m)
                node_r = sim.play(Move.from_gtp(b["reply"], player=opponent), ignore_ko=True)
                mv2 = Move.from_gtp(b["m2"], player=player)
            except IllegalMoveException:
                continue
            key = ("L2", g, b["reply"])
            branch_nodes[key] = (node_r, mv2, b)
            jobs += probe_jobs(key, node_r, mv2)
            m["branches"].append(b)
    res2 = run_batch(engine, jobs)
    jobs3, chain_keys = [], {}
    for key, (node_r, mv2, b) in branch_nodes.items():
        q = extract(res2.get((key, "clean")), res2.get((key, "hp")), player, bs)
        if q is None:
            b["q"] = None
            continue
        q.pop("replies_full", None)
        b["q"] = {
            k: q[k]
            for k in (
                "lead_after",
                "wr_after",
                "e",
                "cov",
                "find",
                "e_fooled",
                "p_fooled",
                "best_reply",
                "best_reply_hp",
                "best_reply_prior",
                "n_adequate",
                "raw_st_score_err",
                "human_st_score_err",
                "score_stdev",
            )
        }
        # ---- L3: 正解手順（最善応手の線）だけもう 1 段 ----
        if b["is_best"]:
            top = next((t for t in q["replies"] if t["gtp"] == q["best_reply"]), None)
            if top and len(top["pv"]) >= 2 and top["gtp"] != "pass" and top["pv"][1] != "pass":
                try:
                    sim.set_current_node(node_r)
                    node_m2 = sim.play(mv2, ignore_ko=True)
                    node_r2 = sim.play(Move.from_gtp(top["gtp"], player=opponent), ignore_ko=True)
                    mv3 = Move.from_gtp(top["pv"][1], player=player)
                except IllegalMoveException:
                    continue
                k3 = ("L3", key[1])
                chain_keys[k3] = b
                b["r2"], b["m3"] = top["gtp"], top["pv"][1]
                jobs3 += probe_jobs(k3, node_r2, mv3)
    res3 = run_batch(engine, jobs3)
    for k3, b in chain_keys.items():
        q3 = extract(res3.get((k3, "clean")), res3.get((k3, "hp")), player, bs)
        b["q3"] = None if q3 is None else {k: q3[k] for k in ("lead_after", "e", "find", "best_reply_hp", "n_adequate")}
    row["cands"] = list(l1.values())
    row["n_queries"] = len(jobs) + len(jobs3) + len(gtps) * 3
    return row


def rounded(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, list):
        return [rounded(v) for v in x]
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    return x


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
            n, t0, rows = root, time.time(), []
            while n.children:
                n = n.children[0]
                if n.next_player != ai_color or not (DEPTH_LO <= n.depth < DEPTH_HI) or not n.children:
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
