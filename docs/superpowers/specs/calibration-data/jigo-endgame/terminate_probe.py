"""提案する修正則が終局に収束するかを自己対局で実測する。

選択則（提案）:
  1. best_gtp_by_score == "pass" なら強制パス（既存の終局バックストップ）
  2. それ以外は「スコアフィルタ通過候補 + pass」の humanPolicy argmax
     （＝ _AREA_PASS_MARGIN のスコアゲートを humanPolicy 判定に置き換える）

これを両者 AI で回し、パスに収束するか / 何手かかるかを見る。
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
MAX_PLIES = 30
BAD = 5.6

stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
node = load_sgf_to_move(SGF, MOVE_NUMBER)
root = node
while root.parent:
    root = root.parent
game = DebugGame(katrain=stub, engine=None, move_tree=root)
engine = KataGoEngine(stub, stub.config("engine"))
game.engines = {"B": engine, "W": engine}
game.set_current_node(node)
stub.game = game


def query(cn, extra, include_policy):
    out, err = {}, []
    engine.request_analysis(
        cn, callback=lambda a, p: out.setdefault("a", a) if not p else None,
        error_callback=lambda a: err.append(a), priority=PRIORITY_EXTRA_AI_QUERY,
        include_policy=include_policy, extra_settings=extra,
    )
    while not (out or err):
        time.sleep(0.01)
        engine.check_alive(exception_if_dead=True)
    if err:
        raise RuntimeError(err)
    return out["a"]


try:
    bx, by = game.board_size
    consecutive_pass = 0
    for ply in range(MAX_PLIES):
        cn = game.current_node
        player = cn.next_player
        s1 = query(cn, {"humanSLProfile": "rank_9d", "ignorePreRootHistory": False, "maxVisits": 800}, True)
        s2 = query(cn, {"ignorePreRootHistory": False, "maxVisits": 600, "wideRootNoise": 0.0}, False)
        hp = s1["humanPolicy"]
        sign = 1 if player == "B" else -1
        mis = s2["moveInfos"]
        best_score = max(mi.get("scoreLead", 0) * sign for mi in mis) / sign
        best_gtp = max(mis, key=lambda mi: mi.get("scoreLead", 0) * sign).get("move", "")
        loss = {mi["move"]: sign * (best_score - mi.get("scoreLead", 0)) for mi in mis}

        def hp_of(g):
            if g == "pass":
                return hp[-1] if len(hp) > bx * by else 0.0
            m = Move.from_gtp(g, player=player)
            x, y = m.coords
            return hp[(by - y - 1) * bx + x]

        hp_pass = hp_of("pass")
        if best_gtp == "pass":
            chosen, why = "pass", "backstop(best_by_score)"
        else:
            cands = [(g, hp_of(g)) for g in loss if loss[g] < BAD and hp_of(g) > 0]
            if not cands:
                chosen, why = "pass", "no candidates"
            else:
                cands.sort(key=lambda t: -t[1])
                chosen, why = cands[0][0], "argmax hp=%.4f" % cands[0][1]

        print("ply %2d %s: chose %-5s (%s)  hp(pass)=%.4f loss(pass)=%+.2f best=%s"
              % (ply, player, chosen, why, hp_pass, loss.get("pass", 9.99), best_gtp))
        sys.stdout.flush()

        if chosen == "pass":
            consecutive_pass += 1
            if consecutive_pass >= 2:
                print("\nRESULT: TERMINATED after %d plies (two consecutive passes)" % (ply + 1))
                break
            game.play(Move(None, player=player))
        else:
            consecutive_pass = 0
            game.play(Move.from_gtp(chosen, player=player))
    else:
        print("\nRESULT: NOT_TERMINATED within %d plies" % MAX_PLIES)
finally:
    engine.shutdown(finish=False)
