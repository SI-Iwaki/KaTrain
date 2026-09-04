"""候補手の子局面をリージョン解析し、拮抗応手ごとの PV と「どこでコウ形と判定されたか」を出す。
usage: ko_pv_probe.py <sgf> <line_csv> <ply> <region> <moves_csv> <visits> <until_depth> <wrn> <ratio> <runs>
"""
import os, sys, time
os.environ["KIVY_NO_ARGS"] = "1"
from katrain.core.constants import DATA_FOLDER
from katrain.core.engine import KataGoEngine
from katrain.core.game import Move, IllegalMoveException, region_analysis_extra_settings
from katrain.core.ai import (tsumego_simulation_game, tsumego_competitive_replies, tsumego_candidate_reaches_region_ko,
                             tsumego_defender_ko_points, _chain_and_liberties, TSUMEGO_TIE_KO_PLIES)
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, load_sgf_to_move

SGF, LINE, PLY, REGION, MOVES = sys.argv[1], sys.argv[2].split(","), int(sys.argv[3]), [int(v) for v in sys.argv[4].split(",")], sys.argv[5].split(",")
VISITS, UD, WRN, RATIO, RUNS = int(sys.argv[6]), int(sys.argv[7]), float(sys.argv[8]), float(sys.argv[9]), int(sys.argv[10])

def analyze(engine, node, visits, region, ud, wrn, timeout=600):
    result = {}
    engine.request_analysis(node, callback=lambda a, partial: None if partial else result.setdefault("a", a),
                            error_callback=lambda e: result.setdefault("error", e), visits=visits, time_limit=False,
                            ownership=True, priority=0, region_of_interest=region, region_until_depth=ud,
                            extra_settings=region_analysis_extra_settings(visits, wrn))
    dl = time.time() + timeout
    while "a" not in result and "error" not in result and time.time() < dl:
        time.sleep(0.05); engine.check_alive(exception_if_dead=True)
    return result.get("a")

def where_ko(game, node, cand, pv, region):
    """detector1 のコウ点を探す（本番と同じ手順・ログ付き）。見つからなければ None"""
    sim = tsumego_simulation_game(game, node)
    first = node.next_player; defender = "W" if first == "B" else "B"
    seq = [cand] + list(pv)
    inreg = lambda c: region is None or (region[0] <= c[0] <= region[1] and region[2] <= c[1] <= region[3])
    for i, gtp in enumerate(seq[: 1 + TSUMEGO_TIE_KO_PLIES]):
        if gtp == "pass": return None
        mover = first if i % 2 == 0 else defender; opp = "W" if mover == "B" else "B"
        mv = Move.from_gtp(gtp, player=mover)
        try: played = sim.play(mv)
        except IllegalMoveException: return ("illegal", i, gtp)
        chain, libs = _chain_and_liberties(sim, mv.coords)
        if chain is not None and len(chain) == 1 and len(libs) == 1 and inreg(mv.coords):
            try: sim.play(Move(coords=libs[0], player=opp))
            except IllegalMoveException as e:
                if "Ko" in str(e): return ("KO", i, gtp, Move(coords=libs[0]).gtp())
            else: sim.set_current_node(played)
    return None

stub = KaTrainStub(os.path.expanduser(os.path.join(DATA_FOLDER, "config.json")), debug_level=0, quiet=True)
root = load_sgf_to_move(SGF, 0)
engine = KataGoEngine(stub, stub.config("engine"))
try:
    game = DebugGame(katrain=stub, engine=engine, move_tree=root); game.set_current_node(root); stub.game = game
    for gtp in LINE[:PLY]:
        game.play(Move.from_gtp(gtp, player=game.current_node.next_player))
    node = game.current_node; player = node.next_player
    game.region_of_interest = REGION
    print(f"# {os.path.basename(SGF)} ply={PLY} next={player} visits={VISITS} ud={UD} wrn={WRN} ratio={RATIO}")
    for run in range(RUNS):
        print(f"--- run {run+1}")
        for m in MOVES:
            sim = tsumego_simulation_game(game, node)
            child = sim.play(Move.from_gtp(m, player=player))
            a = analyze(engine, child, VISITS, REGION, UD, WRN)
            replies = a.get("moveInfos") or []
            walk = tsumego_competitive_replies(replies, RATIO)
            self_ko = tsumego_candidate_reaches_region_ko(game, node, m, [], REGION)
            print(f"{m:>4} self_ko={self_ko} replies_walked={[r['move'] for r in walk]} (top v{replies[0]['visits'] if replies else 0})")
            for r in walk:
                pv = r.get("pv") or []
                full = tsumego_candidate_reaches_region_ko(game, node, m, pv, REGION)
                first = next((k for k in range(0, len(pv) + 1) if tsumego_candidate_reaches_region_ko(game, node, m, pv[:k], REGION)), None)
                tag = f"KO(first_true after {first} reply plies)" if full else "clean"
                print(f"       {r['move']:>4} v{r.get('visits',0):<5} {tag:<32} pv={' '.join(pv[:9])}")
                if full and first is not None:
                    sim2 = tsumego_simulation_game(game, node); seq = [m] + pv[:first]; pl = player
                    for gtp in seq:
                        sim2.play(Move.from_gtp(gtp, player=pl)); pl = "W" if pl == "B" else "B"
                    last = seq[-1]; last_player = "W" if pl == "B" else "B"
                    singles = []
                    for ch in sim2.chains:
                        if len(ch) == 1:
                            _, libs = _chain_and_liberties(sim2, ch[0].coords)
                            if len(libs) == 1: singles.append(f"{ch[0].player}{Move(coords=ch[0].coords).gtp()}->lib {Move(coords=libs[0]).gtp()}")
                    defender = "W" if player == "B" else "B"
                    dk = tsumego_defender_ko_points(tsumego_simulation_game(game, node) if False else sim2, defender, REGION)
                    print(f"            last={last_player}{last} singles-in-atari={singles} defender_ko_points_now={[Move(coords=c).gtp() for c in sorted(dk)]}")
finally:
    engine.shutdown(finish=False)
