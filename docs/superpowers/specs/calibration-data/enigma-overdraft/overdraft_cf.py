# -*- coding: utf-8 -*-
"""難解「捨て身の罠（overdraft）」の在庫を数える反実仮想ハーネス（2026-09-18）。

ログから復元した 13 路の対局（recon/*.sgf）の AI 手番のうち、ヨセ前（手数 10〜84）でリードが
0〜10 目の局面について、通常の損失上限の外側〜「リード + 4.5 目」の候補（生 loss の帯）から最大 12 手を
等間隔に選び、難解と同条件の子局面プローブ（clean 500visits + humanSL 9d 8visits）で検証する。
結果（検証済み損失・着手後リード・E・find_hp・応手表）は JSON に保存し、集計は overdraft_cf_report.py。

実行（約 18 分・KataGo 起動あり。リポジトリのルートから）:
    python docs/superpowers/specs/calibration-data/enigma-overdraft/overdraft_cf.py [game ...]

標準出力は ASCII のみ（cp932 端末対策）。
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
from katrain.core.game import KaTrainSGF  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame  # noqa: E402

RECON = os.path.join(HERE, "recon")
OUT = os.path.join(HERE, "overdraft-cf-rows.json")

# 計測時のユーザーのローカル設定（enigma13plus）
TARGET, MAX_LOSS, LARGE = 1.0, 1.8, 8.0
DEPTH_LO, DEPTH_HI = 10, 85
LEAD_HI = 10.0
OVER = 4.5  # 生 loss の帯の上端 = lead + OVER（最大ビハインド 3 目 + 生 loss の楽観ぶんの余裕 1.5 目）
RAW_MARGIN = 1.5  # 帯の下端 = 通常上限 - これ
N_PICKS = 12


def wait(node, engine, timeout=120):
    t0 = time.time()
    while not node.analysis_complete:
        time.sleep(0.02)
        engine.check_alive(exception_if_dead=True)
        if time.time() - t0 > timeout:
            return False
    return True


def probe_turn(engine, game, node):
    player = node.next_player
    sign = 1 if player == "B" else -1
    opponent = "W" if player == "B" else "B"
    game.set_current_node(node)
    node.analyze(engine)
    if not wait(node, engine):
        return None
    root_lead = (node.analysis.get("root") or {}).get("scoreLead")
    if root_lead is None:
        return None
    lead = sign * root_lead
    if not (0.0 < lead <= LEAD_HI):
        return None
    cands = node.candidate_moves
    if not cands or cands[0]["move"] == "pass":
        return None
    best_gtp = cands[0]["move"]
    candidates, _ = ai.parity9_build_candidates(cands, player=player, min_visits=1)
    cap_normal, cw, _budget = ai.enigma9_spending_plan(lead, TARGET, MAX_LOSS, LARGE)
    lo, hi = max(0.3, cap_normal - RAW_MARGIN), lead + OVER
    band = [c for c in candidates if c["gtp"] not in (best_gtp, "pass") and lo < c["loss"] <= hi]
    trusted = sorted([c for c in band if c.get("visits", 0) >= 10], key=lambda c: (c["loss"], -c.get("visits", 0)))
    shallow = sorted([c for c in band if c.get("visits", 0) < 10], key=lambda c: (-c.get("visits", 0), c["loss"]))
    picks = ai._enigma9_spread_picks(trusted, N_PICKS)
    if len(picks) < N_PICKS:
        picks += shallow[: N_PICKS - len(picks)]
    row = {
        "lead": lead,
        "cap_normal": cap_normal,
        "cw": cw,
        "best": best_gtp,
        "n_band": len(band),
        "n_trusted": len(trusted),
        "picks": [],
    }
    if not picks:
        return row
    strat = ai.Enigma13PlusStrategy(game, {})
    probes, stage_hp = strat._probe_children([best_gtp] + [c["gtp"] for c in picks], player, parent_hp=True)
    if not stage_hp or "humanPolicy" not in stage_hp:
        return None
    own_hp_of = ai.enigma9_hp_lookup(stage_hp["humanPolicy"], game.board_size)
    best_lead_after, best_wr = ai.enigma9_verified_metrics((probes.get(best_gtp) or {}).get("clean"), player)
    if best_lead_after is None:
        return None
    row["best_lead_after"], row["best_wr"] = best_lead_after, best_wr

    def metrics(gtp):
        pr = probes.get(gtp) or {}
        clean, hp_child = pr.get("clean"), pr.get("hp")
        if not clean or not clean.get("moveInfos") or not hp_child or "humanPolicy" not in hp_child:
            return None
        lead_after, wr_after = ai.enigma9_verified_metrics(clean, player)
        if lead_after is None:
            return None
        replies, best_reply = ai.enigma9_reply_table(clean["moveInfos"], opponent)
        if not replies:
            return None
        hp_of = ai.enigma9_hp_lookup(hp_child["humanPolicy"], game.board_size)
        e, _cov = ai.enigma9_expected_punish(replies, hp_of)
        find = ai.enigma9_reply_findability(replies, hp_of)
        table = sorted(([hp_of(r["gtp"]), r["loss"]] for r in replies), key=lambda t: -t[0])
        return {
            "gtp": gtp,
            "lead_after": lead_after,
            "wr_after": wr_after,
            "vloss": best_lead_after - lead_after,
            "e": e,
            "find": find,
            "own_hp": own_hp_of(gtp),
            "best_reply": best_reply,
            "replies": [t for t in table if t[0] >= 0.005][:12],  # [hp, 応手側の損失]
        }

    row["best_m"] = metrics(best_gtp)
    for c in picks:
        m = metrics(c["gtp"])
        if m is None:
            continue
        m["raw_loss"], m["visits"] = c["loss"], c.get("visits", 0)
        row["picks"].append(m)
    return row


def rounded(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, list):
        return [rounded(v) for v in x]
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    return x


def main():
    games = json.load(open(os.path.join(RECON, "games.json"), encoding="utf-8"))
    only = sys.argv[1:]
    stub = KaTrainStub(os.path.expanduser("~/.katrain/config.json"), debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    out, t_all = [], time.time()
    try:
        for s in games:
            g, ai_color = s["game"], s["ai"]
            if only and g not in only:
                continue
            sign = 1 if ai_color == "B" else -1
            root = KaTrainSGF.parse_file(os.path.join(RECON, g + ".sgf"))
            game = DebugGame(katrain=stub, engine=engine, move_tree=root)
            stub.game = game
            n, t0, done = root, time.time(), 0
            while n.children:
                n = n.children[0]
                if n.next_player != ai_color or not (DEPTH_LO <= n.depth < DEPTH_HI):
                    continue
                # 事前ふるい: 再解析済みの目差（黒視点）でリードの範囲外の手番は解析しない
                sc = s["score_at_depth"].get(str(n.depth))
                if sc is None or not (-0.7 < sign * sc <= LEAD_HI + 0.7):
                    continue
                row = probe_turn(engine, game, n)
                if row is None:
                    continue
                row.update({"game": g, "depth": n.depth, "strategy": s["strategy"]})
                out.append(row)
                done += 1
            print("%s ai=%s turns=%d %.0fs (rows %d)" % (g, ai_color, done, time.time() - t0, len(out)), flush=True)
            json.dump(rounded(out), open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    finally:
        engine.shutdown(finish=False)
    print("done rows=%d in %.0fs -> %s" % (len(out), time.time() - t_all, os.path.basename(OUT)), flush=True)


if __name__ == "__main__":
    main()
