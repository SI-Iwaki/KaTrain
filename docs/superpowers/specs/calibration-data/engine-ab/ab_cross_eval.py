"""交差評価: 2 腕の難解バッチ JSON の選択手を、指定エンジン（審判）で評価し直す。

usage: python ab_cross_eval.py <sgf> <json_X> <json_Y> [--config <judge config.json>] [--only-diff] [--out <path>]

腕ごとの mean_ptloss は「その腕のエンジンが測った損失」なので腕間で直接比べられない。
審判エンジンを固定して両腕の選択手を同じ物差しで測る（審判 = A なら「新ネットの選択を旧ネットが
どう見るか」、審判 = B ならその逆）。選択手が審判の候補（探索された手）に無ければ None。
"""

import json
import os
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"
sys.path.insert(0, r"c:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1")

from katrain.core.constants import DATA_FOLDER  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import KaTrainSGF  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame  # noqa: E402

args = sys.argv[1:]
sgf, jx, jy = args[:3]
cfg = (
    args[args.index("--config") + 1]
    if "--config" in args
    else os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))
)
only_diff = "--only-diff" in args
out = args[args.index("--out") + 1] if "--out" in args else None


def load(path):
    txt = open(path, encoding="utf-8").read()
    d = json.loads(txt[txt.index("{") :])
    return {m["move_num"]: m for m in d["moves"]}


X, Y = load(jx), load(jy)
stub = KaTrainStub(cfg, debug_level=0, quiet=True)
engine = KataGoEngine(stub, stub.config("engine"))
root = KaTrainSGF.parse_file(sgf)
nodes = []
n = root
while n.children:
    n = n.children[0]
    nodes.append(n)
game = DebugGame(katrain=stub, engine=engine, move_tree=root)
stub.game = game

rows = []
try:
    for move_num in sorted(set(X) & set(Y)):
        sx, sy = X[move_num]["selected"], Y[move_num]["selected"]
        if only_diff and sx == sy:
            continue
        parent = nodes[move_num - 1].parent
        game.set_current_node(parent)
        if not parent.analysis_complete:
            parent.analyze(engine)
            while not parent.analysis_complete:
                time.sleep(0.02)
                engine.check_alive(exception_if_dead=True)
        cands = {c["move"]: c for c in parent.candidate_moves}
        lx = cands[sx]["pointsLost"] if sx in cands else None
        ly = cands[sy]["pointsLost"] if sy in cands else None
        rows.append(
            {
                "move_num": move_num,
                "sel_X": sx,
                "sel_Y": sy,
                "loss_X": lx,
                "loss_Y": ly,
                "judge_top": parent.candidate_moves[0]["move"] if parent.candidate_moves else None,
            }
        )
        print(
            f"#{move_num:>3} X={sx:<4} {('%.2f' % lx) if lx is not None else '  ? ':>6}  Y={sy:<4} {('%.2f' % ly) if ly is not None else '  ? ':>6}  top={rows[-1]['judge_top']}",
            flush=True,
        )
finally:
    engine.shutdown(finish=False)


def mean(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


diff = [r for r in rows if r["sel_X"] != r["sel_Y"]]
print(f"\njudge={cfg}")
print(f"moves={len(rows)} differing={len(diff)}")
for label, rs in (("all", rows), ("differing", diff)):
    print(
        f"  {label:<9} mean loss X={mean([r['loss_X'] for r in rs])} Y={mean([r['loss_Y'] for r in rs])} "
        f"(unknown X={sum(1 for r in rs if r['loss_X'] is None)} Y={sum(1 for r in rs if r['loss_Y'] is None)})"
    )
if out:
    json.dump({"judge": cfg, "sgf": sgf, "X": jx, "Y": jy, "rows": rows}, open(out, "w", encoding="utf-8"), indent=1)
