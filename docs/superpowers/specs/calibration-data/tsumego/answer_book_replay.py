"""回答帳の問題を「回答帳なし」で解かせ直し、記録手順と突き合わせるスイープ・ハーネス。

回答帳（`~/.katrain/tsumego_answers.json`）の entry は
`size` / `canonical_black` / `canonical_white` / `lines` を持つので、**盤面と正解手順は
回答帳だけで完全に再現できる**（実測: 464 entry すべてで grid 復元の往復が一致）。
そこで各 entry について

  1. 正規化された盤（canonical 向き）から認識グリッドを復元し、
  2. **本番と同じ経路**で出題盤を決め（ソルバゲート → 枠張り → 枠なし）、
  3. `tsumego_book_entry` を**設定しない**＝回答帳の再生を無効にしたまま、
  4. 記録手順の白の応手を打ち込みながら、各黒番で実 `generate_move` を呼び、
  5. 記録手と一致したかを判定する（最初の不一致で打ち切り）

を回す。本番コードは一切変更せず、`katrain.__main__` を非表示ウィンドウで import して
`KaTrainGui` の枠張りメソッドをスタブに束縛して呼ぶ（枠張りを写経すると本番と乖離し、
「別物を測る」危険がある。実測でその失敗は繰り返し起きている）。

注意（この計測の限界）:
- **不一致 = 誤答とは限らない**。詰碁には別解があり、回答帳はユーザーがアプリで見た
  1本しか持たない。不一致ケースは第2パス（`--verify`）で「選択手も詰碁を解いているか」を
  役割石の同深さ ownership で確かめること。
- 盤は canonical 向きに正規化されている（元のキャプチャの向きではない）。KataGo は
  厳密には回転不変ではないので、元の対局と1手単位で一致する保証はない。
- 単発 run は手選択が run 間で変動する（`e2e_suite.py` が3run回すのはこのため）。
  このスイープは**トリアージ用の1run**で、不一致ケースだけ後から複数runで確認する。

usage:
  python docs/superpowers/specs/calibration-data/tsumego/answer_book_replay.py \
      [--out PATH] [--limit N] [--min-line 5] [--route all|frame|solver] \
      [--keys k1,k2] [--start N] [--resume] [--debug] [--no-solver-cache]

`--keys` は entry キーの**前方一致**（`--keys 25d208df` でよい）。`--repeats` は無い＝
A/B の 3run は**ケースごとに新規プロセス**で回すこと（1プロセス反復だと KataGo の NN
キャッシュとソルバ永続キャッシュの両方が run2 以降に効いて独立標本にならない。
`2026-08-03-tsumego-stage3-early-speculation-design.md` と同じ運用）。

出力は JSONL（1行 = 1手順）。1件ごとに flush するので、走行中でも集計できる。
ASCII output only（cp932 端末で落ちないように）。
"""
import argparse
import json
import os
import time
import traceback

os.environ["KIVY_NO_ARGS"] = "1"

from kivy.config import Config as _KivyConfig

_KivyConfig.set("graphics", "window_state", "hidden")  # 実ウィンドウを出さない（sdl2 provider は要る）

import katrain.__main__ as gui_main  # noqa: E402  KaTrainGui の実メソッドを借りるためだけに import

from katrain.core.ai import STRATEGY_REGISTRY, tsumego_gain_stones, tsumego_solver_attacks  # noqa: E402
from katrain.core.constants import AI_TSUMEGO, AI_TSUMEGO_SOLVER, DATA_FOLDER, OUTPUT_INFO  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import KaTrainSGF, region_analysis_extra_settings  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain.core.tsumego_answer_book import DEFAULT_PATH as BOOK_PATH, gtp_to_point  # noqa: E402
from katrain.core.tsumego_capture import capture_settings_for_frame_mode, grid_to_sgf  # noqa: E402
from katrain.core.tsumego_problem import (  # noqa: E402
    DEFAULT_MAX_REGION_POINTS,
    extract_problem,
    solver_capture_within_gates,
)
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame  # noqa: E402

# KaTrainGui から借りる枠張り経路（GUI 依存ゼロ。self.log / self.config / self.engine しか使わない）
BORROWED = [
    "_choose_tsumego_frame",
    "_tsumego_frame_beats_frameless",
    "_tsumego_frame_solver_reading",
    "_tsumego_frame_solver_reading_start",
    "_tsumego_frame_solver_reading_finish",
    "_tsumego_frame_trial_start",
    "_tsumego_frame_trial_wait",
    "_tsumego_frameless_board",
    "_tsumego_region_wide_root_noise",
]


class ReplayHost(KaTrainStub):
    """KaTrainGui の枠張りメソッドを載せる宿主。engine 以外は KaTrainStub のまま。

    `KaTrainStub.log` はメッセージを無制限に溜めるので、数百問を1プロセスで回すと
    メモリが伸び続ける。直近だけ保持し、手番ごとに呼び出し側が clear する
    （不一致の手番ではこのバッファから戦略の判定ログを切り出して結果に残す）。
    """

    LOG_BUFFER = 4000

    def __init__(self, config_path, engine=None, debug_level=0, quiet=True):
        super().__init__(config_path, debug_level=debug_level, quiet=quiet)
        self.engine = engine

    def log(self, message, level=OUTPUT_INFO):
        super().log(message, level)
        if len(self.logs) > self.LOG_BUFFER:
            del self.logs[: len(self.logs) - self.LOG_BUFFER]


for _name in BORROWED:
    setattr(ReplayHost, _name, getattr(gui_main.KaTrainGui, _name))


def stones_to_grid(black, white, size):
    """(x, 下origin y) の石集合 → 認識グリッド grid[i][j]（i は上からの行）。"""
    grid = [["." for _ in range(size)] for _ in range(size)]
    for x, y in black:
        grid[size - 1 - y][x] = "B"
    for x, y in white:
        grid[size - 1 - y][x] = "W"
    return grid


def entry_to_grid(entry):
    size = entry["size"]
    black = {gtp_to_point(s) for s in entry["canonical_black"]}
    white = {gtp_to_point(s) for s in entry["canonical_white"]}
    return stones_to_grid(black, white, size)


def choose_board(host, grid, komi, settings, ko, margin, black_to_attack=None, frameless=False):
    """`_do_tsumego_capture_apply` の出題盤の決め方をそのままなぞる（重い部分は本番メソッド）。

    返り値: (board, analysis_region, solver_problem, route)
    """
    from katrain.core import tsumego_solver_api as solver_api

    settings = capture_settings_for_frame_mode(settings, frameless)
    board, analysis_region, solver_problem = None, None, None
    if settings.get("solver_enabled", True):
        try:
            solver_problem = extract_problem(
                grid=grid,
                to_play="B",
                max_region_points=int(settings.get("solver_max_region_points", DEFAULT_MAX_REGION_POINTS)),
            )
        except Exception:
            solver_problem = None
        if solver_problem is not None:
            gates_ok, _detail = solver_capture_within_gates(solver_problem, settings)
            if not gates_ok:
                solver_problem = None
        if solver_problem is not None and solver_api.problem_is_hopeless(
            solver_problem, settings, lambda msg, level=None: host.log(msg, OUTPUT_INFO)
        ):
            solver_problem = None  # 抽出が別物（case AD）。枠張り経路へ譲る
        if solver_problem is not None:
            board = grid
            _board, analysis_region = host._tsumego_frameless_board(grid, settings, quiet=True)
            return board, analysis_region, solver_problem, "solver"
    if settings.get("use_frame", False):
        chosen = host._choose_tsumego_frame(grid, komi, ko, margin, settings, black_to_attack_p=black_to_attack)
        if chosen is not None:
            board, analysis_region = chosen
            return board, analysis_region, None, "frame"
    board, analysis_region = host._tsumego_frameless_board(grid, settings)
    return board, analysis_region, None, "frameless"


def static_solver_eligible(grid, settings):
    """KataGo を回さずに「ソルバ経路に乗りうるか」を判定（`--route` の事前フィルタ用）。

    実際の経路は `problem_is_hopeless` の検算まで回さないと決まらないので、これは上界。
    実測（464 entry）: solver 110 / too_big 42 / 抽出失敗 312。
    """
    try:
        p = extract_problem(
            grid=grid,
            to_play="B",
            max_region_points=int(settings.get("solver_max_region_points", DEFAULT_MAX_REGION_POINTS)),
        )
    except Exception:
        return False
    if p is None:
        return False
    return solver_capture_within_gates(p, settings)[0]


def warm_up_engine(host, engine, entry, komi, timeout=300.0):
    """モデルをロードさせてから本編に入る（**枠試算の前に必ず呼ぶ**）。

    `_tsumego_frame_solver_reading_finish` の待ちは **30秒固定**（`_tsumego_frame_trial_wait`
    の既定 timeout）なのに、TensorRT の初回モデルロードは実測 35.6 秒かかる。冷えたまま
    1件目が枠経路だと枠試算が『root=解析失敗』になり、しかも**解析が取れなかった枠は
    「壊れていない」扱いで素通りする**（`frame_solver_verdict` が own=None で返す）ので、
    検証されていない枠が黙って採用される＝誤った成功に見える。
    """
    grid = entry_to_grid(entry)
    root = KaTrainSGF.parse_sgf(grid_to_sgf(grid, komi=komi))
    game = DebugGame(katrain=host, engine=engine, move_tree=root)
    game.set_current_node(root)
    node = game.current_node
    node.analyze(engine, analyze_fast=True)
    deadline = time.time() + timeout
    while node.analysis["root"] is None and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    return node.analysis["root"] is not None


def region4(analysis_region, board_size):
    """`_apply_tsumego_region` と同じ変換（上origin i → 下origin y）。"""
    if not analysis_region:
        return None
    (imin, imax), (jmin, jmax) = analysis_region
    return [jmin, jmax, board_size - 1 - imax, board_size - 1 - imin]


def build_game(host, engine, board, komi, region, deep_visits, wrn, solver_problem, prefix, solver_disabled=False):
    """出題盤を作り、記録手順の prefix まで打ち進めた game を返す（回答帳は設定しない）。

    `solver_disabled` は GUI の sticky 挙動の再現用。GUI では game が手番をまたいで生き続けるので、
    戦略が `game.tsumego_solver_session = False` を立てるとその問題の残り全部でソルバが止まる。
    ハーネスは判断ごとに game を作り直すため、明示的に引き継がないと**毎手ソルバを解き直して
    しまい、GUI では起きない 30 秒タイムアウトを何度も踏む**（実測: 1問 100.8 秒 → GUI 相当なら
    フォールバック1回ぶん）。
    """
    root = KaTrainSGF.parse_sgf(grid_to_sgf(board, komi=komi))
    game = DebugGame(katrain=host, engine=engine, move_tree=root)
    game.set_current_node(root)
    game.region_of_interest = region
    game.region_analysis_visits = deep_visits
    game.region_analysis_wide_root_noise = wrn
    game.region_prefetch_replies = 0  # 先読みは判定に影響しないので切る（1プロセスで大量に回すため）
    game.tsumego_solver_problem = solver_problem
    if solver_disabled:
        game.tsumego_solver_session = False
    # tsumego_book_entry / _transforms は**設定しない** = tsumego_book_next_move が (False, None)
    for gtp in prefix:
        game.play(Move.from_gtp(gtp, player=game.current_node.next_player))
    return game


def analyse(engine, game, timeout=300.0):
    """`_apply_tsumego_region` と同じ2段解析（全盤fast → リージョン限定 + ownership）。"""
    node = game.current_node
    node.analyze(engine, analyze_fast=True)
    deadline = time.time() + timeout
    while node.analysis["root"] is None and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    if not game.region_of_interest:
        return node
    node.analyze(
        engine,
        region_of_interest=game.region_of_interest,
        visits=game.region_analysis_visits,
        time_limit=game.region_analysis_visits is None,
        extra_settings=region_analysis_extra_settings(
            game.region_analysis_visits, game.region_analysis_wide_root_noise
        ),
        ownership=True if game.region_analysis_visits else None,
    )
    deadline = time.time() + timeout
    while not node.analysis.get("region_completed") and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    return node


CAND_KEYS = ("move", "visits", "prior", "order", "pointsLost", "scoreLead", "winrate", "utility")

# 最終決定を出した機構（`Final decision: <手> (<ここ>...)`）。正解手番と不一致手番で分布を比べたいので
# **全手番**で取る（不一致だけだと「誤答に多い経路」なのか「もともと多い経路」なのか分からない）
_DECIDERS = (
    ("class_promotion", "クラス格上げ"),
    ("ko_escape", "コウ脱出"),
    ("declass", "格下げ"),
    ("rescue", "救済"),
    ("verified", "同深さ検証"),
    ("tie_band", "同着"),
    ("gain", "gain="),
)


def decision_paths(logs):
    """戦略ログから「どの機構が決めたか」と「root で既に成功と読まれていたか」を抜く。"""
    lines = [m for m, _lvl in logs if isinstance(m, str) and m.startswith("[Tsumego")]
    joined = "\n".join(lines)
    final = next((ln for ln in lines if "Final decision:" in ln), None)
    decider = "solver_or_book" if final is None else "unknown"
    if final:
        inside = final.split("(", 1)[1] if "(" in final else ""
        for tag, needle in _DECIDERS:
            if needle in inside:
                decider = tag
                break
    return {
        "decider": decider,
        "root_already_succeeded": "既に成功" in joined,
        "role_logged": ("attack" if "攻め方（相手を殺す）" in joined else "defend" if "守り方" in joined else None),
        "n_log_lines": len(lines),
    }


def candidate_row(cand):
    return {k: cand.get(k) for k in CAND_KEYS if k in cand}


def decision_diagnostics(game, node, want_gtp, chosen_gtp, settings):
    """「正解手が候補プールに居たか」を中心にした1手ぶんの診断。解析クエリは撃たない。"""
    cands = node.candidate_moves or []
    by_move = {c.get("move"): c for c in cands}
    want = by_move.get(want_gtp)
    chosen = by_move.get(chosen_gtp)
    ranked_by_visits = sorted(cands, key=lambda c: -(c.get("visits") or 0))
    ranked_by_prior = sorted(cands, key=lambda c: -(c.get("prior") or 0.0))
    min_visits = int(settings.get("min_visits", 10))
    region_stones = tsumego_gain_stones([s.coords for s in game.stones], game.region_of_interest)
    solver_attacks = tsumego_solver_attacks(
        game.stones, game.region_of_interest, game.board_size, node.next_player
    )
    return {
        "n_candidates": len(cands),
        "min_visits": min_visits,
        "solver_attacks": solver_attacks,
        "n_region_stones": len(region_stones),
        "want_in_pool": want is not None,
        # キー名を `want` / `chosen` にしない: 呼び出し側の record が持つ GTP 文字列を
        # `**diag` で上書きしてしまい、候補プールに無い手（ソルバ経路の着手など）で
        # 打った手そのものが None になって失われる
        "want_cand": candidate_row(want) if want else None,
        "want_visit_rank": next((i for i, c in enumerate(ranked_by_visits) if c.get("move") == want_gtp), None),
        "want_prior_rank": next((i for i, c in enumerate(ranked_by_prior) if c.get("move") == want_gtp), None),
        "want_passes_min_visits": bool(want and (want.get("visits") or 0) >= min_visits),
        "chosen_cand": candidate_row(chosen) if chosen else None,
        "chosen_visit_rank": next((i for i, c in enumerate(ranked_by_visits) if c.get("move") == chosen_gtp), None),
        "top_by_visits": [candidate_row(c) for c in ranked_by_visits[:5]],
        "top_by_prior": [candidate_row(c) for c in ranked_by_prior[:5]],
    }


def replay_line(host, engine, entry, line, settings, ai_settings, komi, debug=False):
    """1手順ぶんを回す。最初の黒番の不一致で打ち切る。"""
    grid = entry_to_grid(entry)
    size = entry["size"]
    t0 = time.time()
    host.logs.clear()
    try:
        board, analysis_region, solver_problem, route = choose_board(
            host,
            grid,
            komi,
            settings,
            ko=settings.get("frame_ko", False),
            margin=int(settings.get("frame_margin", 4)),
        )
    except Exception as e:  # 候補が1つも作れない盤は tsumego_frame_board の例外が素通しで出る
        return {"verdict": "frame_error", "error": f"{type(e).__name__}: {e}", "decisions": []}
    # 枠試算の解析が取れなかった枠は「壊れていない」扱いで素通りする＝検証されていない枠が
    # 黙って採用される。後から結果を疑えるように記録しておく
    frame_read_failed = any("枠バランス試算" in m and "解析失敗" in m for m, _lvl in host.logs if isinstance(m, str))
    region = region4(analysis_region, size)
    t_frame = time.time() - t0
    subtype = AI_TSUMEGO_SOLVER if solver_problem is not None else AI_TSUMEGO
    deep_visits = int(settings.get("analysis_visits", 1800)) or None
    wrn = float(settings.get("region_wide_root_noise", 0.04))

    decisions = []
    verdict = "correct"
    solver_disabled = False  # GUI の sticky 却下を再現する（`build_game` の docstring 参照）
    for i in range(0, len(line), 2):  # 黒番は偶数 index（line は黒から始まる）
        want_gtp = line[i]
        prefix = line[:i]
        try:
            game = build_game(
                host, engine, board, komi, region, deep_visits, wrn, solver_problem, prefix, solver_disabled
            )
        except Exception as e:
            verdict = "prefix_illegal"
            decisions.append({"depth": i, "error": f"{type(e).__name__}: {e}"})
            break
        # 記録手そのものが今の出題盤で打てるか（枠の壁が正解手を潰す case AG 等）
        legal = True
        if want_gtp.lower() != "pass":
            want_coords = Move.from_gtp(want_gtp).coords
            if any(s.coords == want_coords for s in game.stones):
                legal = False
        if not legal:
            verdict = "answer_blocked"
            decisions.append({"depth": i, "want": want_gtp, "note": "記録手の点が出題盤で占有されている"})
            break
        host.logs.clear()  # この手番の戦略ログだけを切り出せるようにする
        ta = time.time()
        try:
            node = analyse(engine, game)
        except Exception as e:
            verdict = "analysis_error"
            decisions.append({"depth": i, "want": want_gtp, "error": f"{type(e).__name__}: {e}"})
            break
        tb = time.time()
        try:
            strategy = STRATEGY_REGISTRY[subtype](game, ai_settings)
            move, thoughts = strategy.generate_move()
        except Exception as e:
            verdict = "generate_error"
            decisions.append(
                {"depth": i, "want": want_gtp, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
            )
            break
        tc = time.time()
        chosen_gtp = move.gtp()
        try:
            diag = decision_diagnostics(game, node, want_gtp, chosen_gtp, ai_settings)
        except Exception as e:
            diag = {"diag_error": f"{type(e).__name__}: {e}"}
        record = {
            "depth": i,
            "want": want_gtp,
            "chosen": chosen_gtp,
            "match": chosen_gtp.upper() == want_gtp.upper(),
            "thoughts": thoughts if debug else (thoughts or "")[:300],
            "sec_analyse": round(tb - ta, 2),
            "sec_generate": round(tc - tb, 2),
            **decision_paths(host.logs),
            **diag,
        }
        if getattr(game, "tsumego_solver_session", None) is False:
            solver_disabled = True  # 突き合わせが却下した＝以降この問題ではソルバを使わない
        record["solver_disabled_after"] = solver_disabled
        decisions.append(record)
        if not record["match"]:
            verdict = "mismatch"
            # どの経路が選んだのかは戦略の判定ログでしか分からない（CLAUDE.md の調査手順）
            record["strategy_log"] = [
                m for m, _lvl in host.logs if isinstance(m, str) and m.startswith("[Tsumego")
            ][-150:]
            break
    return {
        "route": route,
        "subtype": subtype,
        "size": size,
        "region": region,
        "frame_read_failed": frame_read_failed,
        "sec_frame": round(t_frame, 2),
        "verdict": verdict,
        "n_black_decisions": (len(line) + 1) // 2,
        "n_evaluated": len(decisions),
        "decisions": decisions,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="JSONL 出力先（既定: このスクリプトの隣に日付つきで作る）")
    ap.add_argument("--book", default=BOOK_PATH)
    ap.add_argument("--limit", type=int, default=0, help="処理する手順の上限（0=全部）")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--min-line", type=int, default=5, help="この手数未満の記録手順は飛ばす")
    ap.add_argument("--route", choices=["all", "frame", "solver"], default="all", help="静的ゲートでの事前フィルタ")
    ap.add_argument("--keys", default=None, help="カンマ区切りの entry キー（前方一致。ログの key[:8] をそのまま渡せる）")
    ap.add_argument("--resume", action="store_true", help="--out に既にある (key,line) を飛ばす")
    ap.add_argument("--debug", action="store_true", help="戦略の判定ログを出す")
    ap.add_argument(
        "--no-solver-cache",
        action="store_true",
        help="ソルバの永続キャッシュを使わない（過去の誤答が焼き付いていないかの A/B。case AB）",
    )
    ap.add_argument("--no-solver", action="store_true", help="ソルバ経路を使わず全部 KataGo 経路で出題する")
    ap.add_argument(
        "--capture-settings",
        default=None,
        help="tsumego_capture 設定の上書き（例: solver_time_limit_ms=5000,frame_margin=3）",
    )
    args = ap.parse_args()

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "answer-book-replay-results.jsonl"
    )
    done = set()
    if args.resume and os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for row in f:
                try:
                    r = json.loads(row)
                    done.add((r["key"], r["line_index"]))
                except Exception:
                    pass
        print(f"resume: {len(done)} already done")

    config_path = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))
    # debug_level=1 は「戦略の判定ログを**捨てずに**バッファへ入れる」ため（不一致の手番で
    # 経路を切り出す）。quiet=True なら画面には出さないので、既定の走行は静かなまま
    host = ReplayHost(config_path, debug_level=1, quiet=not args.debug)
    settings = dict(host.config("tsumego_capture") or {})
    ai_settings = dict(host.config(f"ai/{AI_TSUMEGO}") or {})
    komi = host.config("game/komi", 6.5)
    if args.no_solver_cache:
        settings["solver_cache"] = False
    if args.no_solver:
        settings["solver_enabled"] = False
    if args.no_solver_cache or args.no_solver:
        # **戦略側にも届かせる**（下の --capture-settings :503 とまったく同じ理由）。
        # `TsumegoSolverStrategy._solver_settings`（ai.py:4803-4810）は
        # `katrain.config("tsumego_capture")` を自分で引き直すので、ローカルの settings dict を
        # 書き換えるだけでは **choose_board の板選択にしか効かない**。--no-solver-cache は
        # 出題前検算（problem_is_hopeless）だけを cold にして、**手番ごとの solve は永続
        # キャッシュを引いたまま**だった＝「cold で測った」と記録した過去の A/B は手番側が warm。
        # --no-solver は solver_problem が None になり subtype が ai:tsumego に落ちるので
        # 実害は無いが、同じ取りこぼしを繰り返さないよう対称に伝播させる
        capture_cfg = host._config.setdefault("tsumego_capture", {})
        for flag, requested in (("solver_cache", args.no_solver_cache), ("solver_enabled", args.no_solver)):
            if requested:
                capture_cfg[flag] = False
                print(f"override: {flag}=False")
    for pair in (args.capture_settings or "").split(","):
        key, _, raw = pair.partition("=")
        if not key.strip():
            continue
        try:
            value = int(raw) if raw.lstrip("-").isdigit() else float(raw)
        except ValueError:
            value = {"true": True, "false": False}.get(raw.lower(), raw)
        settings[key.strip()] = value
        # **戦略側にも届かせる**: `TsumegoSolverStrategy._solver_settings` は
        # `katrain.config("tsumego_capture")` を自分で引き直すので、ローカルの settings dict を
        # 書き換えるだけでは板選択にしか効かない（実測 2026-08-09: solver_time_limit_ms=5000 の
        # A/B が実質ノーオペで、30 秒タイムアウトがそのまま残っていた）
        host._config.setdefault("tsumego_capture", {})[key.strip()] = value
        print(f"override: {key.strip()}={value!r}")

    entries = json.load(open(args.book, encoding="utf-8"))["entries"]
    # 前方一致で受ける（進捗ログ・結果集計はどちらも key[:8] を出すので、その形のまま
    # 投げ返せないと 40 桁を回答帳から引き直す羽目になる）。完全一致キーもそのまま通る
    wanted_keys = [k.strip() for k in args.keys.split(",") if k.strip()] if args.keys else None
    cases = []
    for key, entry in entries.items():
        if wanted_keys and not any(key.startswith(w) for w in wanted_keys):
            continue
        lines = [ln for ln in (entry.get("lines") or []) if len(ln) >= args.min_line]
        if not lines:
            continue
        if args.route != "all":
            eligible = static_solver_eligible(entry_to_grid(entry), settings)
            if (args.route == "solver") != eligible:
                continue
        for li, line in enumerate(entry.get("lines") or []):
            if len(line) < args.min_line:
                continue
            cases.append((key, li, line))
    cases = cases[args.start :]
    if args.limit:
        cases = cases[: args.limit]
    print(f"cases: {len(cases)} (min_line={args.min_line}, route filter={args.route})")

    engine = KataGoEngine(host, host.config("engine"))
    host.engine = engine
    print(f"komi={komi} rules={host.config('game/rules')} visits={settings.get('analysis_visits')}")
    if cases:
        t_warm = time.time()
        ok = warm_up_engine(host, engine, entries[cases[0][0]], komi)
        print(f"engine warm-up: {'ok' if ok else 'FAILED'} ({time.time() - t_warm:.1f}s)", flush=True)

    tally = {}
    t_start = time.time()
    written = 0
    try:
        with open(out_path, "a", encoding="utf-8") as out:
            for n, (key, li, line) in enumerate(cases, 1):
                if (key, li) in done:
                    continue
                t0 = time.time()
                try:
                    result = replay_line(host, engine, entries[key], line, settings, ai_settings, komi, args.debug)
                except Exception as e:
                    result = {"verdict": "harness_error", "error": f"{type(e).__name__}: {e}",
                              "trace": traceback.format_exc()[-1500:]}
                row = {"key": key, "line_index": li, "line": line, "sec": round(time.time() - t0, 1), **result}
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                written += 1
                tally[result["verdict"]] = tally.get(result["verdict"], 0) + 1
                rate = (time.time() - t_start) / max(1, written)
                print(
                    f"[{n}/{len(cases)}] {key[:8]} line{li} {len(line)}moves"
                    f" route={result.get('route')} -> {result['verdict']}"
                    f" ({row['sec']}s, avg {rate:.1f}s, ETA {(len(cases) - n) * rate / 60:.0f}min)"
                    f"  {dict(sorted(tally.items()))}",
                    flush=True,
                )
    finally:
        engine.shutdown(finish=False)
    print(f"\nwrote {written} rows -> {out_path}")
    print("tally:", dict(sorted(tally.items())))


if __name__ == "__main__":  # 第2パス `answer_book_verify.py` がヘルパーを import するのでガードする
    main()
