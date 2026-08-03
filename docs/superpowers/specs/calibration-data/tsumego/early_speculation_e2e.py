"""段階3（root部分結果からの前倒し投機）の発火経路を GUI と同じ経路で再現するハーネス。

`_maybe_early_speculation`（`katrain/core/game.py`）は `Game.play()` の region 分岐からしか
起動しない。既存の `generate_move_e2e.py` の `analyse()` は `node.analyze()` を直接呼ぶため
`Game.play()` の region 分岐を一切通らず、段階3は構造的に発火しない（発火有無・効果のどちらも
既存ハーネスでは検証できない）。

本ハーネスは GUI 実戦と同じ手順を再現する:
  1. game を作り、`region_of_interest` / `region_analysis_visits`(1800) /
     `region_analysis_wide_root_noise`(0.04) を**先に**設定する
  2. `katrain.players_info` を「黒=AI（strategy=ai:tsumego）／白=人間」に設定する
  3. 目標 ply の直前までの手を `analyze=False`（`DebugGame.play` の既定＝`BaseGame.play` 直呼び）
     で高速に再生し、直前の**白**の手だけ `game.play(move, analyze=True)`
     （＝ `Game.play()` の region 分岐）で打つ ← ここで `_maybe_early_speculation` の
     ウォッチャスレッドが起動する
  4. `node.analysis["region_completed"]` を待つ（実クエリ側の完了。実戦で generate_move が
     呼ばれるタイミングと同じ）
  5. `STRATEGY_REGISTRY[AI_TSUMEGO](game, settings).generate_move()` を呼ぶ
  6. `katrain.logs`（`KaTrainStub.log()` は debug_level・quiet に関係なく `self.logs` に
     全ログを溜める）から「前倒し投機」を含む行を拾って発火有無・発火手を判定する

**ハーネス側の既知の落とし穴**: `katrain_debug.runner.DebugGame.__init__` は
`analyze_all_nodes` の自動起動スレッドを避けるため `Game.__init__` を素通りして
`BaseGame.__init__` を直接呼ぶ。そのため `Game.__init__` が本来設定する
`region_analysis_visits` / `region_analysis_wide_root_noise` / `region_prefetch_replies` /
`_region_prefetch_nodes` / `_early_speculation_nodes` が **DebugGame インスタンスには一切
存在しない**。`Game.play(analyze=True)` は無条件に `self._cancel_region_prefetch()` /
`self._cancel_early_speculation()` を呼び、region 分岐に入れば `self._maybe_region_prefetch()`
（`self.region_prefetch_replies` を読む）も呼ぶため、これらを持たない DebugGame でそのまま
`analyze=True` の play() を呼ぶと `AttributeError` になる。GUI の `Game` はコンストラクタで
これらを必ず初期化するので本体側のバグではなく、CLI ハーネス（DebugGame）が
`Game.__init__` をバイパスしている副作用。本ハーネスは `build_game()` 内でこれらを
`game.play()` を呼ぶ**前に**明示的に初期化することで対処する（本体コードは一切変更しない）。

usage: python docs/superpowers/specs/calibration-data/tsumego/early_speculation_e2e.py <case> <ply> [repeats]
  例:  ... early_speculation_e2e.py M 4 3
       ... early_speculation_e2e.py O 2 3
       ... early_speculation_e2e.py V2 2 3

`<case>` は下の CASES のキー（M/O/V2）。`<ply>` は正解手順 line 上の位置（偶数・2以上＝
直前に白の手がある黒番）。**ply0 は使えない** — ウォッチャは直前の `Game.play()` からしか
起動しないため、盤の初期状態（キャプチャ直後の初手）には構造的に発火しない。
"""
import os
import re
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import AI_TSUMEGO, DATA_FOLDER, PLAYER_AI, PLAYER_HUMAN
from katrain.core.ai import STRATEGY_REGISTRY, TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION
from katrain.core.base_katrain import Player
from katrain.core.engine import KataGoEngine
from katrain.core.game import Move
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

HERE = os.path.dirname(os.path.abspath(__file__))
VISITS = 1800
WIDE_ROOT_NOISE = 0.04
# ai.py の定数をそのまま表示用に使う（ハードコード値だと変更のたびにここが古くなる）
SPECULATION_THRESHOLD_FRACTION = TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION

# e2e_suite.py の CASES から M/O/V2 だけ複製（region はリスト表現・line は正解手順）。
# ply は「直前に白の手がある黒番」（偶数・2以上）を選ぶ: M は expect={4} をそのまま使用、
# O は expect が {0} のみなので line 上の次の偶数 ply=2、V2 は expect={2} をそのまま使用。
CASES = {
    "M": dict(
        sgf="case-m-capture-gain-ko-20260730.sgf",
        region=[4, 12, 0, 8],
        line=["K2", "L4", "L3", "M3", "K1"],
    ),
    "O": dict(
        sgf="case-o-all-ko-band-20260731.sgf",
        region=[0, 8, 3, 12],
        line=["A11", "C10", "C13", "B13", "B12", "A10", "A8", "A13", "B12"],
    ),
    "V2": dict(
        sgf="case-v2-guard-outside-ko-20260731.sgf",
        region=[4, 12, 4, 12],
        line=["L12", "N10", "N13", "N11"],
    ),
}


def build_players_info(stub):
    """黒=AI（strategy=ai:tsumego）・白=人間。_maybe_early_speculation の起動条件そのもの。"""
    stub.players_info["B"] = Player("B", player_type=PLAYER_AI, player_subtype=AI_TSUMEGO)
    stub.players_info["W"] = Player("W", player_type=PLAYER_HUMAN)


def build_game(engine, stub, case, ply):
    """目標 ply の直前の白の手まで進めた (game, node) を返す。

    region 設定・players_info 設定は最初の着手より前に済ませる（GUI はキャプチャ直後に
    リージョンを張ってから対局を進める）。ply-1 手までは analyze=False（BaseGame.play 直呼び、
    Game.play の region 分岐を通らない＝過去の手の再生に相当）で高速に進め、目標 ply の
    直前の白の手だけ analyze=True（Game.play 経由）で打つ。
    """
    sgf = os.path.join(HERE, case["sgf"])
    root = load_sgf_to_move(sgf, 0)
    game = DebugGame(katrain=stub, engine=engine, move_tree=root)
    game.set_current_node(root)
    # DebugGame.__init__ は Game.__init__ をバイパスするため、Game.play() が無条件に読む
    # 属性が存在しない。play() を呼ぶ前に明示的に補う（本体コードは変更しない）
    game.region_of_interest = case["region"]
    game.region_analysis_visits = VISITS
    game.region_analysis_wide_root_noise = WIDE_ROOT_NOISE
    game.region_prefetch_replies = 0  # 本タスクの対象外（次番が人間の先読み）を無効化して焦点を絞る
    game._region_prefetch_nodes = []
    game._early_speculation_nodes = []
    stub.game = game
    build_players_info(stub)

    line = case["line"]
    for gtp in line[: ply - 1]:
        game.play(Move.from_gtp(gtp, player=game.current_node.next_player), analyze=False)
    mover = game.current_node.next_player
    white_move = line[ply - 1]
    node = game.play(Move.from_gtp(white_move, player=mover), analyze=True)
    return game, node, mover, white_move


def wait_region_completed(engine, node, timeout=300):
    """region_completed を待つ。待っている間に観測できた moves visits 合計の最大値も返す
    （ウォッチャが見ていたであろう値の目安。ウォッチャ自身の観測とは独立サンプルだが、
    「閾値に届く前に完了したか」の診断に使える）。
    """
    deadline = time.time() + timeout
    max_visits_seen = 0
    while not node.analysis.get("region_completed") and time.time() < deadline:
        moves = node.analysis.get("moves") or {}
        if moves:
            total = sum(d.get("visits", 0) for d in moves.values())
            max_visits_seen = max(max_visits_seen, total)
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)
    return max_visits_seen


def scan_speculation_logs(log_slice):
    """前倒し投機に関するログ行を拾う（発火＝成功ログ／中止＝例外ログ）。"""
    fired_line = None
    aborted = False
    for message, _level in log_slice:
        if "前倒し投機" not in message:
            continue
        if "時点で発行" in message:
            fired_line = message
        elif "中止" in message:
            aborted = True
    return fired_line, aborted


def summarize_fired(fired_line):
    """発火ログから ASCII セーフなフィールドだけ抜き出す（cp932 端末での print クラッシュ回避、
    CLAUDE.md「やってはいけないこと」節）。"""
    if fired_line is None:
        return None
    moves_m = re.search(r"(\[.*?\])", fired_line)
    visits_m = re.search(r"(\d+)visits", fired_line)
    threshold_m = re.search(r"閾値(\d+)v", fired_line)  # "閾値" の直後の数字
    return {
        "moves": moves_m.group(1) if moves_m else "?",
        "verify_visits": visits_m.group(1) if visits_m else "?",
        "threshold_v": threshold_m.group(1) if threshold_m else "?",
    }


def warmup_engine(engine, stub, case, timeout=120):
    """モデルロード等の固定コスト（実測: 3ケース共通で cold run1 の analyse 36〜38秒の大半）を
    ここで吸収する使い捨てクエリ。**別局面**（root。判定対象の白手後の局面とは異なる）に
    低 visits で撃ち、結果は破棄する。

    GUI 実戦ではキャプチャの時点で（起動直後の最初の1問を除き）既にエンジンが温まっている。
    ここで warmup しないと REPEATS の run1 が「エンジン初回ロード＋着手決定」の合算になり、
    ウォッチャの30秒デッドライン（`_early_speculation_worker`）をロード費用だけで食い潰して
    しまう＝前倒し投機が発火する余地のある「通常の1手」を測れない。root は判定対象の局面と
    盤面が異なるため、NN キャッシュを汚染しない（実クエリはキャッシュミスのまま計測される）。
    """
    sgf = os.path.join(HERE, case["sgf"])
    root = load_sgf_to_move(sgf, 0)
    warm_game = DebugGame(katrain=stub, engine=engine, move_tree=root)
    warm_game.set_current_node(root)
    root.analyze(engine, visits=50, time_limit=False)
    deadline = time.time() + timeout
    while not root.analysis_complete and time.time() < deadline:
        time.sleep(0.05)
        engine.check_alive(exception_if_dead=True)


def run_once(engine, stub, case, case_name, ply, rep):
    start_log_idx = len(stub.logs)
    t0 = time.time()
    game, node, mover, white_move = build_game(engine, stub, case, ply)
    if mover != "W":
        raise AssertionError(
            f"case={case_name} ply={ply}: expected White to move immediately before this ply, "
            f"got mover={mover} (line/ply parity assumption broken)"
        )
    if node.next_player != "B":
        raise AssertionError(
            f"case={case_name} ply={ply}: expected Black (ai:tsumego) to move next, "
            f"got next_player={node.next_player}"
        )
    max_visits_seen = wait_region_completed(engine, node)
    t1 = time.time()
    settings = dict(stub.config(f"ai/{AI_TSUMEGO}") or {})
    strategy = STRATEGY_REGISTRY[AI_TSUMEGO](game, settings)
    move, _thoughts = strategy.generate_move()
    t2 = time.time()

    fired_line, aborted = scan_speculation_logs(stub.logs[start_log_idx:])
    # ワーカースレッドは非同期。region_completed 判定と generate_move の間、あるいは
    # generate_move 実行中に遅れてログを書く可能性があるので少し待ってから確定する
    grace_deadline = time.time() + 3.0
    while fired_line is None and not aborted and time.time() < grace_deadline:
        time.sleep(0.05)
        fired_line, aborted = scan_speculation_logs(stub.logs[start_log_idx:])

    game._cancel_early_speculation()  # 次 repeat の実クエリと GPU を取り合わないよう後始末
    game._cancel_region_prefetch()

    return {
        "rep": rep,
        "move": move.gtp(),
        "white_move": white_move,
        "analyse_s": t1 - t0,
        "generate_s": t2 - t1,
        "max_visits_seen_during_wait": max_visits_seen,
        "fired_line": fired_line,
        "aborted": aborted,
    }


def main():
    if len(sys.argv) < 3:
        print("usage: early_speculation_e2e.py <case:M|O|V2> <ply> [repeats]")
        sys.exit(1)
    case_name = sys.argv[1]
    ply = int(sys.argv[2])
    repeats = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    case = CASES.get(case_name)
    if case is None:
        print(f"unknown case: {case_name} (available: {', '.join(CASES)})")
        sys.exit(1)
    if ply < 2 or ply % 2 != 0:
        print(f"ply must be even and >= 2 (ply0 has no preceding Game.play() to trigger the watcher); got {ply}")
        sys.exit(1)
    if ply > len(case["line"]):
        print(f"ply {ply} exceeds line length {len(case['line'])} for case {case_name}")
        sys.exit(1)

    config_path = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))
    # quiet=True: KaTrainStub.log() は quiet でも self.logs には必ず積むので判定には困らない。
    # print だけ抑制することで、strategy debug ログに含まれる日本語文字の cp932 端末クラッシュを避ける
    stub = KaTrainStub(config_path, debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    print(
        f"case={case_name} ply={ply} repeats={repeats} "
        f"threshold_fraction={SPECULATION_THRESHOLD_FRACTION} region_visits={VISITS}"
    )
    t_warm0 = time.time()
    warmup_engine(engine, stub, case)
    print(f"engine warmup (discarded, separate position): {time.time() - t_warm0:.1f}s")
    results = []
    try:
        for rep in range(1, repeats + 1):
            r = run_once(engine, stub, case, case_name, ply, rep)
            results.append(r)
            fired = summarize_fired(r["fired_line"])
            if fired:
                fired_desc = (
                    f"FIRED moves={fired['moves']} threshold={fired['threshold_v']}v "
                    f"verify_visits={fired['verify_visits']}"
                )
            elif r["aborted"]:
                fired_desc = "ABORTED (exception while computing warm set)"
            else:
                fired_desc = "NOT FIRED"
            print(
                f"run{rep} case={case_name}@{ply} (white played {r['white_move']}): "
                f"move={r['move']} analyse={r['analyse_s']:.2f}s generate={r['generate_s']:.2f}s "
                f"max_visits_seen_during_wait={r['max_visits_seen_during_wait']} speculation={fired_desc}"
            )
    finally:
        engine.shutdown(finish=False)

    print("\n=== summary ===")
    n_fired = sum(1 for r in results if summarize_fired(r["fired_line"]) is not None)
    n_aborted = sum(1 for r in results if r["aborted"])
    print(
        f"{n_fired}/{len(results)} runs fired early speculation for case={case_name}@{ply}"
        + (f"  ({n_aborted} aborted)" if n_aborted else "")
    )


if __name__ == "__main__":
    main()
