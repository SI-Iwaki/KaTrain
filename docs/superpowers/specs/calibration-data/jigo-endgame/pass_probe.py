"""パス強制が起きた実戦局面で humanPolicy と clean スコアを実測する。

仮説の検証: _AREA_PASS_MARGIN の 0.5 ゲートを外して humanPolicy の argmax に
委ねた場合、9段モデルは「パス」ではなく「ダメ」を選ぶか？
"""
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"

sys.path.insert(0, r"C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1")

from katrain.core.constants import DATA_FOLDER, PRIORITY_EXTRA_AI_QUERY
from katrain.core.engine import KataGoEngine
from katrain.core.sgf_parser import Move
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF = sys.argv[1]
MOVE_NUMBER = 119

stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
node = load_sgf_to_move(SGF, MOVE_NUMBER)
player = node.next_player
root = node
while root.parent:
    root = root.parent
game = DebugGame(katrain=stub, engine=None, move_tree=root)
engine = KataGoEngine(stub, stub.config("engine"))
game.engines = {"B": engine, "W": engine}
game.set_current_node(node)
stub.game = game


def query(extra, include_policy):
    out = {}
    err = []

    def cb(a, partial):
        if not partial:
            out["a"] = a

    def eb(a):
        err.append(a)

    engine.request_analysis(
        node, callback=cb, error_callback=eb, priority=PRIORITY_EXTRA_AI_QUERY,
        include_policy=include_policy, extra_settings=extra,
    )
    while not (out or err):
        time.sleep(0.01)
        engine.check_alive(exception_if_dead=True)
    if err:
        raise RuntimeError(err)
    return out["a"]


try:
    print("next player:", player, " ruleset:", node.ruleset)
    stage1 = query({"humanSLProfile": "rank_9d", "ignorePreRootHistory": False, "maxVisits": 800}, True)
    stage2 = query({"ignorePreRootHistory": False, "maxVisits": 600, "wideRootNoise": 0.0}, False)

    hp = stage1["humanPolicy"]
    bx, by = game.board_size
    sign = 1 if player == "B" else -1
    mis = stage2["moveInfos"]
    best_score = max(mi.get("scoreLead", 0) * sign for mi in mis) / sign
    loss = {mi["move"]: sign * (best_score - mi.get("scoreLead", 0)) for mi in mis}
    visits = {mi["move"]: mi.get("visits", 0) for mi in mis}

    def hp_of(gtp):
        if gtp == "pass":
            return hp[-1] if len(hp) > bx * by else 0.0
        m = Move.from_gtp(gtp, player=player)
        x, y = m.coords
        return hp[(by - y - 1) * bx + x]

    BAD = 5.6
    cands = [(g, hp_of(g), loss[g], visits[g]) for g in loss if loss[g] < BAD and hp_of(g) > 0]
    cands.sort(key=lambda t: -t[1])

    print()
    print("pass: humanPolicy=%.4f loss=%.2f visits=%d" % (hp_of("pass"), loss.get("pass", 9.99), visits.get("pass", 0)))
    print()
    print("top 8 by humanPolicy (score-filter survivors):")
    for g, w, l, v in cands[:8]:
        print("  %-5s hp=%.4f loss=%+.2f visits=%d" % (g, w, l, v))
    print()
    argmax = cands[0][0] if cands else None
    print("ARGMAX_HUMANPOLICY:", argmax)
    print("PASS_IS_ARGMAX:", argmax == "pass")
finally:
    engine.shutdown(finish=False)
