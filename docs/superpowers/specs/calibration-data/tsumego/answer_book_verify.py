"""スイープの不一致ケースを第2パスで裁定する（`answer_book_replay.py` の続き）。

スイープの「記録手と違う手を打った」は**誤答とは限らない**。詰碁には別解があり、回答帳は
ユーザーがアプリで見た1本しか持っていない。そこで不一致の手番だけを取り出し、

  - 記録手（want）を打った後
  - 戦略が選んだ手（chosen）を打った後

の**役割石の同深さ ownership**（`_region_child_verdict` + `tsumego_success_ownership`＝
本番の格下げ確認・脱出採否が使っているのと同じ尺度・同じ `TSUMEGO_VERDICT_UNTIL_DEPTH`）を
測って、次の3つに振り分ける:

  alternative  chosen も成立している（>= ko_success_ownership）＝別解。誤答ではない
  true_miss    want は成立、chosen は成立していない＝**本物の誤答**
  undecided    どちらも ply1 では成立と読めない（答えがコウ／セキ等。ownership は成否を運ばない）

同時に、ユーザーの体感「正解手は相手の死judgment を維持または強める／誤答手は薄れる」を
数値で検定できる（`delta = own_after_want - own_after_chosen`）。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/answer_book_verify.py \
      [--in PATH] [--out PATH] [--limit N] [--resume]

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

from katrain.core.ai import (  # noqa: E402
    STRATEGY_REGISTRY,
    tsumego_region_stones_by_player,
    tsumego_role_stones,
    tsumego_solver_attacks,
    tsumego_success_ownership,
)
from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402

from answer_book_replay import (  # noqa: E402  同じフォルダの姉妹スクリプト
    ReplayHost,
    analyse,
    build_game,
    choose_board,
    entry_to_grid,
    region4,
)

BOOK_PATH = os.path.expanduser("~/.katrain/tsumego_answers.json")


def measure(strategy, game, move_gtp, visits):
    """その手を打った後の「成否を担う石」の1子平均 ownership。測れなければ None。"""
    cn = game.current_node
    player_sign = cn.player_sign(cn.next_player)
    own_stones, opponent_stones = tsumego_region_stones_by_player(
        game.stones, game.region_of_interest, cn.next_player
    )
    solver_attacks = tsumego_solver_attacks(
        game.stones, game.region_of_interest, game.board_size, cn.next_player
    )
    role_stones = tsumego_role_stones(own_stones, opponent_stones, solver_attacks)
    verdict = strategy._region_child_verdict(move_gtp, role_stones, player_sign, visits)
    if verdict is None or verdict.get("ownership") is None:
        return None, solver_attacks, verdict
    per_stone = tsumego_success_ownership(
        verdict["ownership"],
        own_stones,
        opponent_stones,
        game.board_size,
        player_sign,
        solver_attacks,
    )
    return per_stone, solver_attacks, verdict


def classify(own_want, own_chosen, threshold):
    if own_want is None or own_chosen is None:
        return "unmeasured"
    if own_chosen >= threshold:
        return "alternative"
    if own_want >= threshold:
        return "true_miss"
    return "undecided"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(here, "answer-book-replay-results.jsonl"))
    ap.add_argument("--out", default=os.path.join(here, "answer-book-verify-results.jsonl"))
    ap.add_argument("--book", default=BOOK_PATH)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    rows = []
    with open(args.inp, encoding="utf-8") as f:
        for raw in f:
            try:
                r = json.loads(raw)
            except Exception:
                continue
            if r.get("verdict") == "mismatch":
                rows.append(r)
    done = set()
    if args.resume and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                    done.add((d["key"], d["line_index"]))
                except Exception:
                    pass
    if args.limit:
        rows = rows[: args.limit]
    print(f"mismatch cases: {len(rows)} (already done: {len(done)})")

    config_path = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))
    host = ReplayHost(config_path, debug_level=1, quiet=not args.debug)
    settings = dict(host.config("tsumego_capture") or {})
    ai_settings = dict(host.config(f"ai/{AI_TSUMEGO}") or {})
    komi = host.config("game/komi", 6.5)
    threshold = float(ai_settings.get("ko_success_ownership", 0.5))
    verify_visits = int(ai_settings.get("gain_verify_visits", 800))
    entries = json.load(open(args.book, encoding="utf-8"))["entries"]
    engine = KataGoEngine(host, host.config("engine"))
    host.engine = engine

    tally = {}
    try:
        with open(args.out, "a", encoding="utf-8") as out:
            for n, r in enumerate(rows, 1):
                if (r["key"], r["line_index"]) in done:
                    continue
                t0 = time.time()
                bad = r["decisions"][-1]
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
                    game = build_game(
                        host,
                        engine,
                        board,
                        komi,
                        region,
                        int(settings.get("analysis_visits", 1800)) or None,
                        float(settings.get("region_wide_root_noise", 0.04)),
                        solver_problem,
                        r["line"][: bad["depth"]],
                    )
                    analyse(engine, game)
                    strategy = STRATEGY_REGISTRY[AI_TSUMEGO](game, ai_settings)
                    own_want, role, _v1 = measure(strategy, game, bad["want"], verify_visits)
                    own_chosen, _role2, _v2 = measure(strategy, game, bad["chosen"], verify_visits)
                    verdict = classify(own_want, own_chosen, threshold)
                    row = {
                        "key": r["key"],
                        "line_index": r["line_index"],
                        "depth": bad["depth"],
                        "want": bad["want"],
                        "chosen": bad["chosen"],
                        "route": route,
                        "solver_attacks": role,
                        "own_after_want": own_want,
                        "own_after_chosen": own_chosen,
                        "delta_want_minus_chosen": (
                            None if own_want is None or own_chosen is None else round(own_want - own_chosen, 4)
                        ),
                        "threshold": threshold,
                        "class": verdict,
                        "want_in_pool": bad.get("want_in_pool"),
                        "want_visit_rank": bad.get("want_visit_rank"),
                        "want_prior_rank": bad.get("want_prior_rank"),
                        "sec": round(time.time() - t0, 1),
                    }
                except Exception as e:
                    row = {
                        "key": r["key"],
                        "line_index": r["line_index"],
                        "class": "error",
                        "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-1200:],
                        "sec": round(time.time() - t0, 1),
                    }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                tally[row["class"]] = tally.get(row["class"], 0) + 1
                print(
                    f"[{n}/{len(rows)}] {r['key'][:8]} d{row.get('depth')}"
                    f" want={row.get('want')} chosen={row.get('chosen')}"
                    f" own_want={row.get('own_after_want')} own_chosen={row.get('own_after_chosen')}"
                    f" -> {row['class']} ({row['sec']}s) {dict(sorted(tally.items()))}",
                    flush=True,
                )
    finally:
        engine.shutdown(finish=False)
    print("tally:", dict(sorted(tally.items())))


main()
