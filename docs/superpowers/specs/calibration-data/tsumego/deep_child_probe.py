"""子局面を全盤・無拘束で深く解析し「その手で本当に相手が死ぬか」を測る真偽プローブ。
usage: deep_probe.py <sgf> <line_csv> <ply> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [--region-ud N]
  --region-ud N を付けると全盤ではなくリージョン拘束 untilDepth=N（wRN 0.04）で撃つ
"""
import os, sys, time
os.environ["KIVY_NO_ARGS"] = "1"
from katrain.core.constants import DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.game import Move, region_analysis_extra_settings
from katrain.core.ai import tsumego_simulation_game, tsumego_absolute_ownership
from katrain.core.utils import var_to_grid
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SGF, LINE, PLY, REGION, MOVES = ARGS[0], ARGS[1].split(","), int(ARGS[2]), [int(v) for v in ARGS[3].split(",")], ARGS[4].split(",")
VISITS = int(ARGS[5]) if len(ARGS) > 5 else 3000
UD = next((int(a.split("=")[1]) for a in sys.argv[1:] if a.startswith("--region-ud=")), None)

def analyze(engine, node, visits, region=None, ud=None, timeout=900):
    result = {}
    kw = {}
    if region is not None:
        kw.update(region_of_interest=region, region_until_depth=ud, extra_settings=region_analysis_extra_settings(visits, 0.04))
    engine.request_analysis(node, callback=lambda a, partial: None if partial else result.setdefault("a", a),
                            error_callback=lambda e: result.setdefault("error", e), visits=visits, time_limit=False,
                            ownership=True, priority=0, **kw)
    dl = time.time() + timeout
    while "a" not in result and "error" not in result and time.time() < dl:
        time.sleep(0.05); engine.check_alive(exception_if_dead=True)
    return result.get("a")

stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
root = load_sgf_to_move(SGF, 0)
engine = KataGoEngine(stub, stub.config("engine"))
try:
    game = DebugGame(katrain=stub, engine=engine, move_tree=root); game.set_current_node(root); stub.game = game
    for gtp in LINE[:PLY]:
        game.play(Move.from_gtp(gtp, player=game.current_node.next_player))
    node = game.current_node; player = node.next_player; sign = node.player_sign(player); opp = "W" if player == "B" else "B"
    size = game.board_size
    inreg = lambda c: REGION[0] <= c[0] <= REGION[1] and REGION[2] <= c[1] <= REGION[3]
    opp_st = [s.coords for s in game.stones if s.player == opp and inreg(s.coords)]
    own_st = [s.coords for s in game.stones if s.player == player and inreg(s.coords)]
    mode = f"region ud={UD} wRN0.04" if UD else "full-board (no avoidMoves)"
    print(f"# {os.path.basename(SGF)} ply={PLY} next={player} visits={VISITS} mode={mode} opp={len(opp_st)}子 own={len(own_st)}子")
    for m in MOVES:
        sim = tsumego_simulation_game(game, node)
        child = sim.play(Move.from_gtp(m, player=player))
        a = analyze(engine, child, VISITS, REGION if UD else None, UD)
        if not a: print(m, "解析失敗"); continue
        grid = var_to_grid(a["ownership"], size)
        oppo = tsumego_absolute_ownership(a["ownership"], opp_st, size, sign) / max(1, len(opp_st))
        owno = tsumego_absolute_ownership(a["ownership"], own_st, size, sign) / max(1, len(own_st))
        lead = sign * a["rootInfo"]["scoreLead"]
        reps = sorted(a.get("moveInfos") or [], key=lambda r: -r.get("visits", 0))[:4]
        print(f"{m:>4} lead(手番){lead:+7.2f} 相手石{oppo:+5.2f}/子 自石{owno:+5.2f}/子 visits={a['rootInfo'].get('visits')}")
        for r in reps:
            print(f"      reply {r['move']:>4} v{r.get('visits',0):<5} pv={' '.join(r.get('pv',[])[:10])}")
        per = " ".join(f"{Move(c).gtp()}{sign*grid[c[1]][c[0]]:+.2f}" for c in sorted(opp_st, key=lambda c:(-c[1],c[0])))
        print(f"      相手石別: {per}")
finally:
    engine.shutdown(finish=False)
