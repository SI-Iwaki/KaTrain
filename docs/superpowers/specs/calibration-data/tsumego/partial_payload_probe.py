"""段階3（root部分結果からの前倒し投機）§4-1 の実測プローブ。

`reportDuringSearchEvery=1` で届く region 解析の部分結果（isDuringSearch=True）に
ownership / per-move ownership が乗っているかを1本のクエリで実測する。

`generate_move_e2e.py` の「SGF 読み込み→エンジン起動→リージョン解析発行」を流用し、
callback だけ差し替える（node.analyze は callback を self.set_analysis に固定している
ため、ここでは engine.request_analysis を直接呼ぶ）。着手生成（strategy.generate_move）
までは走らせない。

対象: ケース V（e2e_suite.py の CASES["V"]）。0手目（初期局面、正解 L12）。

usage: python docs/superpowers/specs/calibration-data/tsumego/partial_payload_probe.py
"""
import os
import time

os.environ["KIVY_NO_ARGS"] = "1"

from katrain.core.constants import DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.game import region_analysis_extra_settings
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

HERE = os.path.dirname(os.path.abspath(__file__))

# ケース V（e2e_suite.py CASES["V"]）を転記。0手目＝初期局面。
SGF = os.path.join(HERE, "case-v-declass-no-kill-20260731.sgf")
REGION = [4, 12, 4, 12]
VISITS = 1800

PARTIAL_COUNT = 0
FINAL_SEEN = False


def on_result(analysis_json, partial_result):
    global PARTIAL_COUNT, FINAL_SEEN
    tag = "PARTIAL" if partial_result else "FINAL"
    if partial_result:
        PARTIAL_COUNT += 1
    else:
        FINAL_SEEN = True
    mi = analysis_json.get("moveInfos") or []
    print(
        f"{tag} visits={analysis_json.get('rootInfo', {}).get('visits')} "
        f"n_moves={len(mi)} "
        f"has_root_ownership={analysis_json.get('ownership') is not None} "
        f"first_move_has_ownership={bool(mi and mi[0].get('ownership') is not None)}",
        flush=True,
    )


def main():
    stub = KaTrainStub(
        os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")),
        debug_level=0,
        quiet=True,
    )
    engine = KataGoEngine(stub, stub.config("engine"))
    try:
        node = load_sgf_to_move(SGF, 0)
        root = node
        while root.parent:
            root = root.parent
        game = DebugGame(katrain=stub, engine=engine, move_tree=root)
        game.set_current_node(node)
        stub.game = game
        game.region_of_interest = REGION
        game.region_analysis_visits = VISITS

        # 事前の fast root クエリ（generate_move_e2e.py の analyse() と同じ下準備。
        # region クエリの前提であって、プローブ対象ではない）
        node.analyze(engine, analyze_fast=True)
        deadline = time.time() + 300
        while node.analysis["root"] is None and time.time() < deadline:
            time.sleep(0.05)
            engine.check_alive(exception_if_dead=True)

        # プローブ対象: region 解析クエリを直接発行し、callback だけ on_result に差し替える。
        # node.analyze は callback を self.set_analysis に固定するのでここでは使わない。
        # report_every はここで明示しないと reportDuringSearchEvery が乗らない
        # （node.analyze の既定 REPORT_DT=1 は request_analysis 側では None がデフォルト）。
        engine.request_analysis(
            node,
            callback=on_result,
            visits=VISITS,
            time_limit=False,
            region_of_interest=REGION,
            extra_settings=region_analysis_extra_settings(VISITS, 0.04),
            ownership=True,
            report_every=1,
        )
        deadline = time.time() + 300
        while not FINAL_SEEN and time.time() < deadline:
            time.sleep(0.05)
            engine.check_alive(exception_if_dead=True)
    finally:
        engine.shutdown(finish=False)

    print(f"\n=== summary: PARTIAL={PARTIAL_COUNT} FINAL_SEEN={FINAL_SEEN} ===")


main()
