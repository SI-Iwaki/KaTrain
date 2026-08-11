"""enigma13 の1手の着手時間をフェーズ別に計測するハーネス（判定コード無変更）。

GUI の実経路を模す: 対象ノードの通常解析(root, config visits) を待ってから
generate_move() を呼ぶ。フェーズ別時間は Enigma9Strategy._run_query /
_probe_children を monkeypatch して計測する（クエリ内容・判定は不変）。

usage: python enigma13_timing_harness.py [label]
output: ASCII のみ（cp932 対策）
"""
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

REPO = r"c:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1"
sys.path.insert(0, REPO)

from katrain_debug.runner import DebugGame, load_sgf_to_move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core import ai as ai_mod  # noqa: E402
from katrain.core.ai import STRATEGY_REGISTRY  # noqa: E402
from katrain.core.constants import AI_ENIGMA_13  # noqa: E402

SGF = os.path.join(REPO, r"docs\superpowers\specs\calibration-data\jigo-speedup\katrain-13ro-20260401-game1.sgf")
CONFIG = os.path.expanduser(r"~\.katrain\config.json")
MOVES = [41, 43, 45, 49, 53, 61, 77, 79]

label = sys.argv[1] if len(sys.argv) > 1 else "run"

# ---- フェーズ計測の monkeypatch（挙動不変・時間だけ記録） ----
phase_times = []  # (name, seconds)

_orig_run_query = ai_mod.Enigma9Strategy._run_query


def timed_run_query(self, qlabel, **kwargs):
    t0 = time.monotonic()
    r = _orig_run_query(self, qlabel, **kwargs)
    phase_times.append((f"query:{qlabel}", time.monotonic() - t0))
    return r


_orig_probe = ai_mod.Enigma9Strategy._probe_children


def timed_probe(self, gtps, player, *args, **kwargs):
    t0 = time.monotonic()
    r = _orig_probe(self, gtps, player, *args, **kwargs)
    phase_times.append((f"probe_batch[{len(gtps)}]", time.monotonic() - t0))
    return r


ai_mod.Enigma9Strategy._run_query = timed_run_query
ai_mod.Enigma9Strategy._probe_children = timed_probe


def asc(s):
    return str(s).encode("ascii", "replace").decode()


def main():
    stub = KaTrainStub(CONFIG, debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    ai_settings = stub.config(f"ai/{AI_ENIGMA_13}") or {}
    print(f"=== enigma13 timing [{label}] settings={ai_settings} ===", flush=True)

    try:
        # エンジン起動を per-move 計測から分離するためのウォームアップ1本
        t0 = time.monotonic()
        node0 = load_sgf_to_move(SGF, 2)
        root0 = node0
        while root0.parent:
            root0 = root0.parent
        g0 = DebugGame(katrain=stub, engine=engine, move_tree=root0)
        g0.set_current_node(node0)
        stub.game = g0
        node0.analyze(engine)
        while not node0.analysis_complete:
            time.sleep(0.05)
            engine.check_alive(exception_if_dead=True)
        print(f"warmup(engine start + first analysis): {time.monotonic()-t0:.2f}s", flush=True)

        for mv in MOVES:
            target = load_sgf_to_move(SGF, mv)
            root = target
            while root.parent:
                root = root.parent
            game = DebugGame(katrain=stub, engine=engine, move_tree=root)
            game.set_current_node(target)
            stub.game = game

            t0 = time.monotonic()
            target.analyze(engine)
            while not target.analysis_complete:
                time.sleep(0.02)
                engine.check_alive(exception_if_dead=True)
            t_analyze = time.monotonic() - t0

            phase_times.clear()
            n_logs = len(stub.logs)
            strategy = STRATEGY_REGISTRY[AI_ENIGMA_13](game, dict(ai_settings))
            t0 = time.monotonic()
            move, explanation = strategy.generate_move()
            t_gen = time.monotonic() - t0

            print(f"--- move {mv} (next={target.next_player}) ---", flush=True)
            print(f"analyze: {t_analyze:.2f}s  generate: {t_gen:.2f}s  -> {move.gtp()}", flush=True)
            for name, sec in phase_times:
                print(f"  phase {name}: {sec:.2f}s", flush=True)
            for msg, _lv in stub.logs[n_logs:]:
                if "Strategy]" in msg:
                    print(f"  log {asc(msg)}", flush=True)
    finally:
        engine.shutdown(finish=False)


if __name__ == "__main__":
    main()
