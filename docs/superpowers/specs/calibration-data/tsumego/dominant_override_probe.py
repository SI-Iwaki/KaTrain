"""dominant 局面で戦略が KataGo 最善手から外れた判断について、
「捨てた手（incumbent）」と「選んだ手（chosen）」の役割石・同深さ ownership を両方測る。

問い: 「incumbent が既に成立しているなら上書きしない」というゲートは、
       正しい上書き（case O 型＝最善手が実は間違っている局面）を壊さないか？

第2パス（answer_book_verify.py）は不一致ケースしか測らないので、
**一致した上書き**（＝ゲートが壊してはいけないもの）の値が無い。ここを埋める。

usage:
  python dominant_override_probe.py --targets dom_targets.json [--only-matched] [--out probe.jsonl]
"""
import argparse
import json
import os
import time

os.environ["KIVY_NO_ARGS"] = "1"

from kivy.config import Config as _KivyConfig

_KivyConfig.set("graphics", "window_state", "hidden")

import katrain.__main__ as gui_main  # noqa: E402,F401

from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.ai import STRATEGY_REGISTRY  # noqa: E402
from katrain.core.tsumego_answer_book import DEFAULT_PATH as BOOK_PATH  # noqa: E402

from answer_book_replay import ReplayHost, analyse, build_game, choose_board, entry_to_grid, region4  # noqa: E402
from answer_book_verify import measure  # noqa: E402


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True)
    ap.add_argument("--out", default=os.path.join(here, "dominant-override-probe.jsonl"))
    ap.add_argument("--only-matched", action="store_true", help="一致した上書きだけ測る")
    ap.add_argument("--tag", default="run1")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    targets = json.load(open(args.targets, encoding="utf-8"))
    if args.only_matched:
        targets = [t for t in targets if t.get("match")]
    print(f"targets: {len(targets)}")

    config_path = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))
    host = ReplayHost(config_path, debug_level=1, quiet=not args.debug)
    settings = dict(host.config("tsumego_capture") or {})
    ai_settings = dict(host.config(f"ai/{AI_TSUMEGO}") or {})
    komi = host.config("game/komi", 6.5)
    verify_visits = int(ai_settings.get("gain_verify_visits", 800))
    threshold = float(ai_settings.get("ko_success_ownership", 0.5))
    entries = json.load(open(BOOK_PATH, encoding="utf-8"))["entries"]
    engine = KataGoEngine(host, host.config("engine"))
    host.engine = engine

    try:
        with open(args.out, "a", encoding="utf-8") as out:
            for n, t in enumerate(targets, 1):
                t0 = time.time()
                rec = dict(tag=args.tag, **{k: t[k] for k in ("key", "line_index", "depth", "chosen", "incumbent", "want", "match", "decider", "route")})
                try:
                    entry = entries[t["key"]]
                    grid = entry_to_grid(entry)
                    board, analysis_region, solver_problem, route = choose_board(
                        host, grid, komi, settings,
                        ko=settings.get("frame_ko", False),
                        margin=int(settings.get("frame_margin", 4)),
                    )
                    region = region4(analysis_region, entry["size"])
                    game = build_game(
                        host, engine, board, komi, region,
                        int(settings.get("analysis_visits", 1800)) or None,
                        float(settings.get("region_wide_root_noise", 0.04)),
                        solver_problem,
                        t["line"][: t["depth"]],
                    )
                    analyse(engine, game)
                    strategy = STRATEGY_REGISTRY[AI_TSUMEGO](game, ai_settings)
                    own_chosen, role, _ = measure(strategy, game, t["chosen"], verify_visits)
                    own_inc, _r2, _ = measure(strategy, game, t["incumbent"], verify_visits)
                    rec.update(
                        own_chosen=own_chosen, own_incumbent=own_inc, solver_attacks=role,
                        threshold=threshold, board_route=route,
                        delta=(None if (own_chosen is None or own_inc is None) else round(own_chosen - own_inc, 4)),
                        incumbent_succeeds=(None if own_inc is None else own_inc >= threshold),
                    )
                except Exception as e:  # noqa: BLE001
                    rec["error"] = f"{type(e).__name__}: {e}"
                rec["sec"] = round(time.time() - t0, 1)
                out.write(json.dumps(rec) + "\n")
                out.flush()
                d = rec.get("delta")
                print(
                    "[%d/%d] %s d%s %s %s chosen=%s(%s) inc=%s(%s) delta=%s  %.1fs"
                    % (n, len(targets), t["key"][:10], t["depth"], t["decider"],
                       "MATCH" if t["match"] else "wrong",
                       t["chosen"], _fmt(rec.get("own_chosen")), t["incumbent"], _fmt(rec.get("own_incumbent")),
                       ("%+.2f" % d) if d is not None else "n/a", rec["sec"])
                )
    finally:
        engine.shutdown(finish=False)


def _fmt(v):
    return "n/a" if v is None else "%+.2f" % v


if __name__ == "__main__":
    main()
