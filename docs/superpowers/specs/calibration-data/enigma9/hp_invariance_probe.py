"""humanPolicy の visits 非依存性を確認するプローブ。

usage: python hp_invariance_probe.py old|new outfile
  old = 旧クエリ条件（visits=config(1000), ownership=config解決(True)）
  new = 新クエリ条件（visits=8, ownership=False）
別プロセスで両方を実行し（NN キャッシュ独立）、humanPolicy 配列を JSON 保存。
"""
import json
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"
REPO = r"c:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1"
sys.path.insert(0, REPO)

from katrain_debug.runner import DebugGame, load_sgf_to_move  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.constants import PRIORITY_EXTRA_AI_QUERY  # noqa: E402

SGF = os.path.join(REPO, r"docs\superpowers\specs\calibration-data\jigo-speedup\katrain-13ro-20260401-game1.sgf")
CONFIG = os.path.expanduser(r"~\.katrain\config.json")
MOVES = [45, 77]

mode, outfile = sys.argv[1], sys.argv[2]


def main():
    stub = KaTrainStub(CONFIG, debug_level=0, quiet=True)
    engine = KataGoEngine(stub, stub.config("engine"))
    out = {}
    try:
        for mv in MOVES:
            node = load_sgf_to_move(SGF, mv)
            root = node
            while root.parent:
                root = root.parent
            game = DebugGame(katrain=stub, engine=engine, move_tree=root)
            game.set_current_node(node)
            stub.game = game
            # 旧経路と同様、通常解析を先に完了させる（キャッシュ状態も揃える）
            node.analyze(engine)
            while not node.analysis_complete:
                time.sleep(0.02)
                engine.check_alive(exception_if_dead=True)

            result = {}

            def cb(a, partial):
                if not partial:
                    result["a"] = a

            def err(a):
                result["a"] = {"error": str(a)}

            kwargs = dict(
                include_policy=True,
                priority=PRIORITY_EXTRA_AI_QUERY,
                extra_settings={
                    "humanSLProfile": "rank_9d",
                    "ignorePreRootHistory": False,
                },
            )
            if mode == "new":
                kwargs["visits"] = 8
                kwargs["ownership"] = False
            engine.request_analysis(node, callback=cb, error_callback=err, **kwargs)
            while "a" not in result:
                time.sleep(0.01)
                engine.check_alive(exception_if_dead=True)
            hp = result["a"].get("humanPolicy")
            out[str(mv)] = hp
            print(f"mv {mv}: humanPolicy len={None if hp is None else len(hp)}", flush=True)
    finally:
        engine.shutdown(finish=False)
    with open(outfile, "w") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()
