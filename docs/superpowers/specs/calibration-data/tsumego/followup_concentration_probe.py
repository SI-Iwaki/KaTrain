"""ユーザー仮説「詰碁の正解初手は、次の同色の手の有力候補を1つに収束させる」の実測プローブ。

2026-08-10 の曖昧さ解析（`2026-08-10-tsumego-ambiguity-analysis.md`）は「判断時点で追加クエリ
なしに計算できる 62 指標」を総当たりして別解の選び分けを却下したが、**follow-up 収束度は
子局面・孫局面の解析が要るためその 62 指標に入っていない**。作意（出題者の意図した手順）が
「本手は後続が一本道になる」という形で盤上に痕跡を残すなら、これは別解ペアを分離しうる
唯一の未測定軸である。

各ケース（不一致: want vs chosen ／ 正解コントロール: want vs 目数同着バンド内の対抗馬）で、
候補初手 m ごとに:

  1. m を打つ -> 子局面をリージョン解析（本番と同条件 1800v・wRN=0.04）
     -> 相手の応手分布の集中度（reply_v2_v1・reply_v1_share）と最有力応手 r
  2. r を打つ -> 孫局面を同条件で解析
     -> **次の同色の手の集中度**（fu_v2_v1・fu_pl_gap・fu_v1_share・fu_prior2_prior1、
        および曖昧さ解析と同じ dominant 判定: v2/v1 < 0.15 かつ pl_gap >= 1.0）

を測る。さらに判断時点の親局面で humanSL 9段（8visits）を1本撃ち、各候補初手の
humanPolicy を記録する（8/10 spec §10 の宿題「humanPolicy は作意の情報を持つか」）。

検定は集計側（別スクリプト/インライン）で:
  P(fu_dominant(want) > fu_dominant(chosen)) が 50% から乖離するか（別解ペア n~124）
  正解コントロールで同じ規則が want を維持するか（破損率の事前見積り）

usage:
  python followup_concentration_probe.py [--replay PATH] [--verify PATH]
      [--group alt,miss,undecided,control] [--limit N] [--out PATH] [--resume]

ASCII output only（cp932 端末で落ちないように）。
"""
import argparse
import json
import os
import time
import traceback

os.environ["KIVY_NO_ARGS"] = "1"

from kivy.config import Config as _KivyConfig

_KivyConfig.set("graphics", "window_state", "hidden")

import katrain.__main__  # noqa: F401,E402  ReplayHost が借りる KaTrainGui を読み込む

from katrain.core.ai import enigma9_hp_lookup  # noqa: E402
from katrain.core.constants import DATA_FOLDER  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402

from answer_book_replay import (  # noqa: E402  同じフォルダの姉妹スクリプト
    ReplayHost,
    analyse,
    build_game,
    choose_board,
    entry_to_grid,
    region4,
)

BOOK_PATH = os.path.expanduser("~/.katrain/tsumego_answers.json")
HUMAN_PROFILE = "rank_9d"
POINTS_EPSILON = 0.25  # 本番の目数同着バンド（コントロールの対抗馬の定義）
DOMINANT_V2V1 = 0.15  # 曖昧さ解析と同じ dominant 判定
DOMINANT_PL_GAP = 1.0


def concentration(cands):
    """候補リスト -> 集中度メトリクス（曖昧さ解析 `tsumego_decision_is_ambiguous` と同素材）。"""
    if not cands:
        return None
    by_v = sorted(cands, key=lambda c: -(c.get("visits") or 0))[:5]
    v1 = by_v[0].get("visits") or 0
    v2 = by_v[1].get("visits") if len(by_v) > 1 else 0
    total = sum(c.get("visits") or 0 for c in cands)
    pls = sorted((c.get("pointsLost") if c.get("pointsLost") is not None else 999.0) for c in by_v)
    pl_gap = (pls[1] - pls[0]) if len(pls) > 1 else 99.0
    by_p = sorted(cands, key=lambda c: -(c.get("prior") or 0.0))[:2]
    p1 = by_p[0].get("prior") or 0.0
    p2 = by_p[1].get("prior") if len(by_p) > 1 else 0.0
    v2_v1 = (v2 or 0) / v1 if v1 else 1.0
    return {
        "n": len(cands),
        "v1_move": by_v[0].get("move"),
        "v1": v1,
        "v2_v1": round(v2_v1, 4),
        "v1_share": round(v1 / total, 4) if total else None,
        "pl_gap": round(pl_gap, 3),
        "prior1": round(p1, 4),
        "prior2_prior1": round((p2 or 0.0) / p1, 4) if p1 > 0 else None,
        "dominant": bool(v2_v1 < DOMINANT_V2V1 and pl_gap >= DOMINANT_PL_GAP),
    }


def human_policy_query(engine, node, timeout=60.0):
    """判断時点の humanSL 9段 humanPolicy（8visits・root NN 出力なので visits 非依存）。"""
    box = {}

    def cb(a, partial=False):
        if not partial:
            box["a"] = a

    def err(a):
        box["a"] = None

    engine.request_analysis(
        node,
        callback=cb,
        error_callback=err,
        visits=8,
        include_policy=True,
        ownership=False,
        extra_settings={"humanSLProfile": HUMAN_PROFILE, "ignorePreRootHistory": False},
    )
    deadline = time.time() + timeout
    while "a" not in box and time.time() < deadline:
        time.sleep(0.02)
        engine.check_alive(exception_if_dead=True)
    a = box.get("a")
    return a.get("humanPolicy") if a else None


def measure_followup(host, engine, board, komi, region, deep_visits, wrn, solver_problem, prefix, first_gtp):
    """初手 first_gtp を打った後の応手集中度と、最有力応手後の同色 follow-up 集中度。"""
    game = build_game(host, engine, board, komi, region, deep_visits, wrn, solver_problem, prefix)
    player = game.current_node.next_player
    game.play(Move.from_gtp(first_gtp, player=player))
    node = analyse(engine, game)
    reply_cands = node.candidate_moves or []
    reply_conc = concentration(reply_cands)
    out = {"reply": reply_conc, "followup": None, "reply_move": None}
    if not reply_conc:
        return out
    reply_move = reply_conc["v1_move"]
    out["reply_move"] = reply_move
    if reply_move is None:
        return out
    game.play(Move.from_gtp(reply_move, player=game.current_node.next_player))
    node2 = analyse(engine, game)
    out["followup"] = concentration(node2.candidate_moves or [])
    return out


def control_rival(bad):
    """正解した判断の記録から、目数同着バンド内の対抗馬（visits 次点）を探す。"""
    want = bad.get("want")
    rows = bad.get("top_by_visits") or []
    mine = next((c for c in rows if c.get("move") == want), None)
    if mine is None or mine.get("pointsLost") is None:
        return None, None
    best_pl = min((c.get("pointsLost") for c in rows if c.get("pointsLost") is not None), default=None)
    if best_pl is None:
        return None, None
    rivals = [
        c
        for c in rows
        if c.get("move") not in (want, None, "pass")
        and c.get("pointsLost") is not None
        and c.get("pointsLost") <= best_pl + POINTS_EPSILON
        and (c.get("visits") or 0) >= 10
    ]
    if not rivals:
        return None, None
    rival = max(rivals, key=lambda c: c.get("visits") or 0)
    return rival.get("move"), rival


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", default=os.path.join(here, "answer-book-replay-20260815.jsonl"))
    ap.add_argument("--verify", default=os.path.join(here, "answer-book-verify-20260815.jsonl"))
    ap.add_argument("--book", default=BOOK_PATH)
    ap.add_argument("--group", default="alt,miss,control")
    ap.add_argument("--limit", type=int, default=0, help="グループごとの上限（0=全部）")
    ap.add_argument("--out", default=os.path.join(here, "followup-probe-results.jsonl"))
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    groups = set(args.group.split(","))
    verify = {}
    if os.path.exists(args.verify):
        with open(args.verify, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                    verify[(d["key"], d["line_index"])] = d
                except Exception:
                    pass

    cases = []  # (group, replay_row, decision_record, move_a=want, move_b, rival_info)
    n_ctrl = 0
    with open(args.replay, encoding="utf-8") as f:
        for raw in f:
            try:
                r = json.loads(raw)
            except Exception:
                continue
            if r.get("verdict") == "mismatch" and r.get("decisions"):
                bad = r["decisions"][-1]
                v = verify.get((r["key"], r["line_index"]))
                cls = (v or {}).get("class", "unverified")
                gname = {"alternative": "alt", "true_miss": "miss", "undecided": "undecided"}.get(cls, "unverified")
                if gname in groups and bad.get("want") and bad.get("chosen") and bad["chosen"].lower() != "pass":
                    cases.append((gname, r, bad, bad["want"], bad["chosen"], None))
            elif r.get("verdict") == "correct" and "control" in groups and r.get("decisions"):
                bad = r["decisions"][0]
                rival, rrow = control_rival(bad)
                if rival:
                    cases.append(("control", r, bad, bad["want"], rival, rrow))
                    n_ctrl += 1
    if args.limit:
        by_group = {}
        trimmed = []
        for c in cases:
            by_group.setdefault(c[0], []).append(c)
        for g, rows in by_group.items():
            trimmed.extend(rows[: args.limit])
        cases = trimmed
    print(f"cases: {len(cases)} by group:", {g: sum(1 for c in cases if c[0] == g) for g in set(c[0] for c in cases)})

    done = set()
    if args.resume and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                    done.add((d["key"], d["line_index"], d["depth"]))
                except Exception:
                    pass
        print(f"resume: {len(done)} already done")

    config_path = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))
    host = ReplayHost(config_path, debug_level=0, quiet=True)
    settings = dict(host.config("tsumego_capture") or {})
    komi = host.config("game/komi", 6.5)
    deep_visits = int(settings.get("analysis_visits", 1800)) or None
    wrn = float(settings.get("region_wide_root_noise", 0.04))
    entries = json.load(open(args.book, encoding="utf-8"))["entries"]
    engine = KataGoEngine(host, host.config("engine"))
    host.engine = engine

    tally = {}
    try:
        with open(args.out, "a", encoding="utf-8") as out:
            for n, (gname, r, bad, move_a, move_b, rrow) in enumerate(cases, 1):
                ck = (r["key"], r["line_index"], bad["depth"])
                if ck in done:
                    continue
                t0 = time.time()
                try:
                    entry = entries[r["key"]]
                    grid = entry_to_grid(entry)
                    board, analysis_region, solver_problem, route = choose_board(
                        host,
                        grid,
                        komi,
                        settings,
                        ko=settings.get("frame_ko", False),
                        margin=int(settings.get("frame_margin", 4)),
                    )
                    region = region4(analysis_region, entry["size"])
                    prefix = r["line"][: bad["depth"]]
                    # 判断時点の humanPolicy（1クエリ）
                    game0 = build_game(host, engine, board, komi, region, deep_visits, wrn, solver_problem, prefix)
                    hp_raw = human_policy_query(engine, game0.current_node)
                    hp = enigma9_hp_lookup(hp_raw, game0.board_size) if hp_raw else None
                    row = {
                        "key": r["key"],
                        "line_index": r["line_index"],
                        "depth": bad["depth"],
                        "group": gname,
                        "route": route,
                        "size": entry["size"],
                        "want": move_a,
                        "rival": move_b,
                        "rival_kind": "chosen" if gname != "control" else "tie_band",
                        "recorded_reply": (r["line"][bad["depth"] + 1] if bad["depth"] + 1 < len(r["line"]) else None),
                        "hp_want": round(hp(move_a), 4) if hp else None,
                        "hp_rival": round(hp(move_b), 4) if hp else None,
                        "parent_ambiguous": None,
                    }
                    tb = bad.get("top_by_visits") or []
                    pconc = concentration(tb) if tb else None
                    row["parent_conc"] = pconc
                    if pconc:
                        row["parent_ambiguous"] = not pconc["dominant"]
                    for label, mv in (("want", move_a), ("rival", move_b)):
                        m = measure_followup(
                            host, engine, board, komi, region, deep_visits, wrn, solver_problem, prefix, mv
                        )
                        row[f"{label}_reply"] = m["reply"]
                        row[f"{label}_reply_move"] = m["reply_move"]
                        row[f"{label}_followup"] = m["followup"]
                    row["sec"] = round(time.time() - t0, 1)
                except Exception as e:
                    row = {
                        "key": r["key"],
                        "line_index": r["line_index"],
                        "depth": bad.get("depth"),
                        "group": gname,
                        "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-1000:],
                        "sec": round(time.time() - t0, 1),
                    }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                ok = "error" not in row
                tally[gname] = tally.get(gname, 0) + 1
                print(
                    f"[{n}/{len(cases)}] {gname} {r['key'][:8]} d{bad.get('depth')}"
                    f" want={move_a} rival={move_b} {'ok' if ok else 'ERR'}"
                    f" ({row['sec']}s) {dict(sorted(tally.items()))}",
                    flush=True,
                )
    finally:
        engine.shutdown(finish=False)
    print("done:", dict(sorted(tally.items())))


if __name__ == "__main__":
    main()
