"""難解13路の E 尺度比較: 指定局面ごとに戦略を走らせ、Score 行（候補ごとの vloss / E / find_hp / own_hp / net）と
Deviate / Best 行を JSON に残す。エンジンは 1 回だけ起動。

usage: python ab_enigma_e.py <sgf> <config.json> <out.json> [--moves 2,4,...]（省略で白番全手）
"""

import json
import os
import re
import sys
import time

os.environ["KIVY_NO_ARGS"] = "1"
sys.path.insert(0, r"c:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1")

from katrain.core.ai import STRATEGY_REGISTRY  # noqa: E402
from katrain.core.constants import AI_ENIGMA_13  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import KaTrainSGF  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.runner import DebugGame  # noqa: E402

sgf, cfg, out = sys.argv[1:4]
only = None
if "--moves" in sys.argv:
    only = {int(x) for x in sys.argv[sys.argv.index("--moves") + 1].split(",")}

SCORE = re.compile(
    r"Score (\S+): vloss=([-\d.]+) \(raw ([-\d.]+)\) wr=(\S+) E=([-\d.]+) cov=([-\d.]+) find_hp=([-\d.]+) "
    r"own_hp=([-\d.]+) \(w_own=([-\d.]+)\) prox=([-\d.]+) reply=(\S+) net=([-\d.]+)"
)
DEVIATE = re.compile(r"Deviate: played (\S+) .* instead of (\S+)")

stub = KaTrainStub(cfg, debug_level=1, quiet=True)
engine = KataGoEngine(stub, stub.config("engine"))
settings = stub.config(f"ai/{AI_ENIGMA_13}") or {}
root = KaTrainSGF.parse_file(sgf)
nodes = []
n = root
while n.children:
    n = n.children[0]
    nodes.append(n)
game = DebugGame(katrain=stub, engine=engine, move_tree=root)
stub.game = game

results = []
try:
    for idx, node in enumerate(nodes, start=1):
        parent = node.parent
        if parent.next_player != "W" or (only and idx not in only):
            continue
        game.set_current_node(parent)
        if not parent.analysis_complete:
            parent.analyze(engine)
            while not parent.analysis_complete:
                time.sleep(0.02)
                engine.check_alive(exception_if_dead=True)
        mark = len(stub.logs)
        t0 = time.time()
        strategy = STRATEGY_REGISTRY[AI_ENIGMA_13](game, settings)
        move, explanation = strategy.generate_move()
        lines = [m for m, _ in stub.logs[mark:] if isinstance(m, str)]  # EXTRA_DEBUG は dict を渡すことがある
        cands = {}
        best = None
        chosen = move.gtp()
        for ln in lines:
            m = SCORE.search(ln)
            if m:
                g = m.group(1)
                cands[g] = dict(
                    vloss=float(m.group(2)),
                    raw=float(m.group(3)),
                    wr=m.group(4),
                    E=float(m.group(5)),
                    cov=float(m.group(6)),
                    find_hp=float(m.group(7)),
                    own_hp=float(m.group(8)),
                    prox=float(m.group(10)),
                    reply=m.group(11),
                    net=float(m.group(12)),
                )
            m = DEVIATE.search(ln)
            if m:
                best = m.group(2)
        deviated = best is not None
        if best is None:
            best = chosen  # 最善手を打った（Best move wins / admissible なし / ヨセ等）
        extra = [ln for ln in lines if re.search(r"cap|budget|Spend|Endgame|admissible|Best move wins|Drop ", ln)]
        results.append(
            dict(
                move_num=idx,
                chosen=chosen,
                best=best,
                deviated=deviated,
                cands=cands,
                secs=round(time.time() - t0, 2),
                explanation=explanation.split("\n")[0][:200],
                notes=[e[:200] for e in extra[:8]],
            )
        )
        print(
            f"#{idx:>3} chosen={chosen:<4} best={best:<4} dev={int(deviated)} cands={len(cands)} "
            f"E_chosen={cands.get(chosen, {}).get('E')} vloss={cands.get(chosen, {}).get('vloss')} {results[-1]['secs']}s",
            flush=True,
        )
finally:
    engine.shutdown(finish=False)

json.dump({"sgf": sgf, "config": cfg, "results": results}, open(out, "w", encoding="utf-8"), indent=1)
print(f"wrote {out}: {len(results)} positions, deviated {sum(r['deviated'] for r in results)}")
