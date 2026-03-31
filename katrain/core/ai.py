from abc import ABC, abstractmethod
import heapq
import math
import random
import time
from typing import Dict, List, Optional, Tuple

from katrain.core.constants import (
    AI_DEFAULT, AI_HANDICAP, AI_INFLUENCE, AI_INFLUENCE_ELO_GRID, AI_JIGO,
    AI_ANTIMIRROR, AI_LOCAL, AI_LOCAL_ELO_GRID, AI_PICK, AI_PICK_ELO_GRID,
    AI_POLICY, AI_RANK, AI_SCORELOSS, AI_SCORELOSS_ELO, AI_SETTLE_STONES,
    AI_SIMPLE_OWNERSHIP, AI_STRENGTH,
    AI_TENUKI, AI_TENUKI_ELO_GRID, AI_TERRITORY, AI_TERRITORY_ELO_GRID,
    AI_FIGHTING, AI_FIGHTING_SCORELOSS_ELO,
    AI_WEIGHTED, AI_WEIGHTED_ELO, CALIBRATED_RANK_ELO, OUTPUT_DEBUG,
    OUTPUT_ERROR, OUTPUT_INFO, PRIORITY_EXTRA_AI_QUERY, ADDITIONAL_MOVE_ORDER, AI_HUMAN, AI_PRO
)
from katrain.core.game import Game, GameNode, Move
from katrain.core.utils import var_to_grid, weighted_selection_without_replacement, evaluation_class

# Decorator pattern for adding classes to the registry
STRATEGY_REGISTRY = {}

def register_strategy(strategy_name):
    def decorator(strategy_class):
        STRATEGY_REGISTRY[strategy_name] = strategy_class
        return strategy_class
    return decorator

def interp_ix(lst, x):
    i = 0
    while i + 1 < len(lst) - 1 and lst[i + 1] < x:
        i += 1
    t = max(0, min(1, (x - lst[i]) / (lst[i + 1] - lst[i])))
    return i, t

def interp1d(lst, x):
    xs, ys = zip(*lst)
    i, t = interp_ix(xs, x)
    return (1 - t) * ys[i] + t * ys[i + 1]

def interp2d(gridspec, x, y):
    xs, ys, matrix = gridspec
    i, t = interp_ix(xs, x)
    j, s = interp_ix(ys, y)
    return (
        matrix[j][i] * (1 - t) * (1 - s)
        + matrix[j][i + 1] * t * (1 - s)
        + matrix[j + 1][i] * (1 - t) * s
        + matrix[j + 1][i + 1] * t * s
    )

def ai_rank_estimation(strategy, settings) -> int:
    if strategy in [AI_DEFAULT, AI_HANDICAP, AI_JIGO, AI_PRO]:
        return 9
    if strategy == AI_RANK:
        return 1 - settings["kyu_rank"]
    if strategy == AI_HUMAN:
        return 1 - settings["human_kyu_rank"]

    if strategy in [AI_WEIGHTED, AI_SCORELOSS, AI_LOCAL, AI_TENUKI, AI_TERRITORY, AI_INFLUENCE, AI_FIGHTING, AI_PICK]:
        if strategy == AI_WEIGHTED:
            elo = interp1d(AI_WEIGHTED_ELO, settings["weaken_fac"])
        if strategy == AI_SCORELOSS:
            elo = interp1d(AI_SCORELOSS_ELO, settings["strength"])
        if strategy == AI_PICK:
            elo = interp2d(AI_PICK_ELO_GRID, settings["pick_frac"], settings["pick_n"])
        if strategy == AI_LOCAL:
            elo = interp2d(AI_LOCAL_ELO_GRID, settings["pick_frac"], settings["pick_n"])
        if strategy == AI_TENUKI:
            elo = interp2d(AI_TENUKI_ELO_GRID, settings["pick_frac"], settings["pick_n"])
        if strategy == AI_TERRITORY:
            elo = interp2d(AI_TERRITORY_ELO_GRID, settings["pick_frac"], settings["pick_n"])
        if strategy == AI_INFLUENCE:
            elo = interp2d(AI_INFLUENCE_ELO_GRID, settings["pick_frac"], settings["pick_n"])
        if strategy == AI_FIGHTING:
            fighting_mode = settings.get("fighting_mode", "classic")
            if fighting_mode == "human":
                elo = 1700  # 9-dan humanSL + score filtering
            elif fighting_mode == "scoreloss":
                elo = interp1d(AI_FIGHTING_SCORELOSS_ELO, settings.get("fighting_max_loss", 3.0))
            else:  # classic
                elo = interp2d(AI_PICK_ELO_GRID, settings["pick_frac"], settings["pick_n"])

        kyu = interp1d(CALIBRATED_RANK_ELO, elo)
        return 1 - kyu
    else:
        return AI_STRENGTH[strategy]

def game_report(game, thresholds, depth_filter=None):
    cn = game.current_node
    nodes = cn.nodes_from_root
    while cn.children:  # main branch
        cn = cn.children[0]
        nodes.append(cn)

    x, y = game.board_size
    depth_filter = [math.ceil(board_frac * x * y) for board_frac in depth_filter or (0, 1e9)]
    nodes = [n for n in nodes if n.move and not n.is_root and depth_filter[0] <= n.depth < depth_filter[1]]
    histogram = [{"B": 0, "W": 0} for _ in thresholds]
    ai_top_move_count = {"B": 0, "W": 0}
    ai_approved_move_count = {"B": 0, "W": 0}
    player_ptloss = {"B": [], "W": []}
    weights = {"B": [], "W": []}

    for n in nodes:
        points_lost = n.points_lost
        if n.points_lost is None:
            continue
        else:
            points_lost = max(0, points_lost)
        bucket = len(thresholds) - 1 - evaluation_class(points_lost, thresholds)
        player_ptloss[n.player].append(points_lost)
        histogram[bucket][n.player] += 1
        cands = n.parent.candidate_moves
        filtered_cands = [d for d in cands if d["order"] < ADDITIONAL_MOVE_ORDER and "prior" in d]
        weight = min(
            1.0,
            sum([max(d["pointsLost"], 0) * d["prior"] for d in filtered_cands])
            / (sum(d["prior"] for d in filtered_cands) or 1e-6),
        )  # complexity capped at 1
        # adj_weight between 0.05 - 1, dependent on difficulty and points lost
        adj_weight = max(0.05, min(1.0, max(weight, points_lost / 4)))
        weights[n.player].append((weight, adj_weight))
        if n.parent.analysis_complete:
            ai_top_move_count[n.player] += int(cands[0]["move"] == n.move.gtp())
            ai_approved_move_count[n.player] += int(
                n.move.gtp()
                in [d["move"] for d in filtered_cands if d["order"] == 0 or (d["pointsLost"] < 0.5 and d["order"] < 5)]
            )

    wt_loss = {
        bw: sum(s * aw for s, (w, aw) in zip(player_ptloss[bw], weights[bw]))
        / (sum(aw for _, aw in weights[bw]) or 1e-6)
        for bw in "BW"
    }
    sum_stats = {
        bw: (
            {
                "accuracy": 100 * 0.75 ** wt_loss[bw],
                "complexity": sum(w for w, aw in weights[bw]) / len(player_ptloss[bw]),
                "mean_ptloss": sum(player_ptloss[bw]) / len(player_ptloss[bw]),
                "weighted_ptloss": wt_loss[bw],
                "ai_top_move": ai_top_move_count[bw] / len(player_ptloss[bw]),
                "ai_top5_move": ai_approved_move_count[bw] / len(player_ptloss[bw]),
            }
            if len(player_ptloss[bw]) > 0
            else {}
        )
        for bw in "BW"
    }
    return sum_stats, histogram, player_ptloss

def fmt_moves(moves: List[Tuple[float, Move]]):
    return ", ".join(f"{mv.gtp()} ({p:.2%})" for p, mv in moves)

# Utility functions from the original code
def policy_weighted_move(policy_moves, lower_bound, weaken_fac):
    lower_bound, weaken_fac = max(0, lower_bound), max(0.01, weaken_fac)
    weighted_coords = [
        (pv, pv ** (1 / weaken_fac), move) for pv, move in policy_moves if pv > lower_bound and not move.is_pass
    ]
    if weighted_coords:
        top = weighted_selection_without_replacement(weighted_coords, 1)[0]
        move = top[2]
        ai_thoughts = f"Playing policy-weighted random move {move.gtp()} ({top[0]:.1%}) from {len(weighted_coords)} moves above lower_bound of {lower_bound:.1%}."
    else:
        move = policy_moves[0][1]
        ai_thoughts = f"Playing top policy move because no non-pass move > above lower_bound of {lower_bound:.1%}."
    return move, ai_thoughts

def generate_influence_territory_weights(ai_mode, ai_settings, policy_grid, size):
    thr_line = ai_settings["threshold"] - 1  # zero-based
    if ai_mode == AI_INFLUENCE:
        weight = lambda x, y: (1 / ai_settings["line_weight"]) ** (  # noqa E731
            max(0, thr_line - min(size[0] - 1 - x, x)) + max(0, thr_line - min(size[1] - 1 - y, y))
        )  # noqa E731
    else:
        weight = lambda x, y: (1 / ai_settings["line_weight"]) ** (  # noqa E731
            max(0, min(size[0] - 1 - x, x, size[1] - 1 - y, y) - thr_line)
        )
    weighted_coords = [
        (policy_grid[y][x] * weight(x, y), weight(x, y), x, y)
        for x in range(size[0])
        for y in range(size[1])
        if policy_grid[y][x] > 0
    ]
    ai_thoughts = f"Generated weights for {ai_mode} according to weight factor {ai_settings['line_weight']} and distance from {thr_line + 1}th line. "
    return weighted_coords, ai_thoughts

def generate_local_tenuki_weights(ai_mode, ai_settings, policy_grid, cn, size):
    var = ai_settings["stddev"] ** 2
    mx, my = cn.move.coords
    weighted_coords = [
        (policy_grid[y][x], math.exp(-0.5 * ((x - mx) ** 2 + (y - my) ** 2) / var), x, y)
        for x in range(size[0])
        for y in range(size[1])
        if policy_grid[y][x] > 0
    ]
    ai_thoughts = f"Generated weights based on one minus gaussian with variance {var} around coordinates {mx},{my}. "
    if ai_mode == AI_TENUKI:
        weighted_coords = [(p, 1 - w, x, y) for p, w, x, y in weighted_coords]
        ai_thoughts = (
            f"Generated weights based on one minus gaussian with variance {var} around coordinates {mx},{my}. "
        )
    return weighted_coords, ai_thoughts

def generate_fighting_weights(ai_settings, policy_grid, game, cn, size):
    unsettled_power = ai_settings.get("unsettled_power", 2.0)
    prox_stddev = ai_settings.get("proximity_stddev", 3.0)
    prox_var = prox_stddev ** 2

    # Build opponent stone positions
    next_player = cn.next_player
    opponent_coords = [s.coords for s in game.stones if s.player != next_player]

    # Build ownership grid if available
    ownership_grid = None
    if cn.ownership:
        ownership_grid = var_to_grid(cn.ownership, size)

    weighted_coords = []
    for x in range(size[0]):
        for y in range(size[1]):
            if policy_grid[y][x] <= 0:
                continue

            # Unsettledness weight
            if ownership_grid is not None:
                unsettled = (1.0 - abs(ownership_grid[y][x])) ** unsettled_power
            else:
                unsettled = 1.0

            # Proximity to opponent stones weight
            if opponent_coords:
                min_dist_sq = min((x - ox) ** 2 + (y - oy) ** 2 for ox, oy in opponent_coords)
                prox_weight = math.exp(-0.5 * min_dist_sq / prox_var)
            else:
                prox_weight = 1.0

            weight = max(unsettled * prox_weight, 1e-6)
            weighted_coords.append((policy_grid[y][x], weight, x, y))

    ai_thoughts = (
        f"Generated fighting weights with unsettled_power={unsettled_power}, "
        f"proximity_stddev={prox_stddev}, "
        f"opponent_stones={len(opponent_coords)}. "
    )
    return weighted_coords, ai_thoughts

class AIStrategy(ABC):
    """Base strategy class for AI move generation"""
    
    def __init__(self, game: Game, ai_settings: Dict):
        self.game = game
        self.settings = ai_settings
        self.cn = game.current_node
        self.strategy_name = self.__class__.__name__
        self.game.katrain.log(f"Initializing {self.strategy_name} with settings: {self.settings}", OUTPUT_DEBUG)
        
    @abstractmethod
    def generate_move(self) -> Tuple[Move, str]:
        """Generate a move and explanation"""
        pass
    
    def request_analysis(self, extra_settings: Dict) -> Optional[Dict]:
        """Helper to request additional analysis with custom settings"""
        self.game.katrain.log(f"[{self.strategy_name}] Requesting analysis with settings: {extra_settings}", OUTPUT_DEBUG)
        error = False
        analysis = None

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a
                self.game.katrain.log(f"[{self.strategy_name}] Analysis received", OUTPUT_DEBUG)

        def set_error(a):
            nonlocal error
            self.game.katrain.log(f"[{self.strategy_name}] Error in additional analysis query: {a}", OUTPUT_ERROR)
            error = True

        engine = self.game.engines[self.cn.player]
        engine.request_analysis(
            self.cn,
            callback=set_analysis,
            error_callback=set_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            ownership=False,
            extra_settings=extra_settings,
        )
        self.game.katrain.log(f"[{self.strategy_name}] Waiting for analysis to complete...", OUTPUT_DEBUG)
        while not (error or analysis):
            time.sleep(0.01)  # TODO: prevent deadlock if esc, check node in queries?
            engine.check_alive(exception_if_dead=True)
        
        if analysis:
            self.game.katrain.log(f"[{self.strategy_name}] Analysis completed successfully", OUTPUT_DEBUG)
        return analysis
    
    def wait_for_analysis(self):
        """Wait for the analysis to complete"""
        self.game.katrain.log(f"[{self.strategy_name}] Waiting for regular analysis to complete...", OUTPUT_DEBUG)
        while not self.cn.analysis_complete:
            time.sleep(0.01)
            self.game.engines[self.cn.next_player].check_alive(exception_if_dead=True)
        self.game.katrain.log(f"[{self.strategy_name}] Regular analysis completed", OUTPUT_DEBUG)
    
    def should_play_top_move(self, policy_moves, top_5_pass, override=0.0, overridetwo=1.0):
        """Check if we should play the top policy move, regardless of strategy"""
        top_policy_move = policy_moves[0][1]
        self.game.katrain.log(f"[{self.strategy_name}] Checking if should play top move. Top move: {top_policy_move.gtp()} ({policy_moves[0][0]:.2%})", OUTPUT_DEBUG)
        self.game.katrain.log(f"[{self.strategy_name}] Override thresholds: single={override:.2%}, combined={overridetwo:.2%}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[{self.strategy_name}] Top 5 pass: {top_5_pass}", OUTPUT_DEBUG)
        
        if top_5_pass:
            self.game.katrain.log(f"[{self.strategy_name}] Playing top move because pass is in top 5", OUTPUT_DEBUG)
            return top_policy_move, "Playing top one because one of them is pass."
        
        if policy_moves[0][0] > override:
            self.game.katrain.log(f"[{self.strategy_name}] Playing top move because weight {policy_moves[0][0]:.2%} > override {override:.2%}", OUTPUT_DEBUG)
            return top_policy_move, f"Top policy move has weight > {override:.1%}, so overriding other strategies."
            
        if policy_moves[0][0] + policy_moves[1][0] > overridetwo:
            combined = policy_moves[0][0] + policy_moves[1][0]
            self.game.katrain.log(f"[{self.strategy_name}] Playing top move because combined weight {combined:.2%} > overridetwo {overridetwo:.2%}", OUTPUT_DEBUG)
            return top_policy_move, f"Top two policy moves have cumulative weight > {overridetwo:.1%}, so overriding other strategies."
        
        self.game.katrain.log(f"[{self.strategy_name}] No override condition met, continuing with strategy", OUTPUT_DEBUG)    
        return None, ""

@register_strategy(AI_DEFAULT)
class DefaultStrategy(AIStrategy):
    """Default strategy - simply plays the top move from the engine"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[DefaultStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()
        
        candidate_moves = self.cn.candidate_moves
        self.game.katrain.log(f"[DefaultStrategy] Analysis found {len(candidate_moves)} candidate moves", OUTPUT_DEBUG)
        
        if not candidate_moves:
            self.game.katrain.log(f"[DefaultStrategy] No candidate moves found, will play pass", OUTPUT_DEBUG)
            top_cand = Move(is_pass=True, player=self.cn.next_player)
        else:
            top_move_data = candidate_moves[0]
            top_cand = Move.from_gtp(top_move_data["move"], player=self.cn.next_player)
            self.game.katrain.log(f"[DefaultStrategy] Top move: {top_cand.gtp()} with stats: {top_move_data}", OUTPUT_DEBUG)
        
        ai_thoughts = f"Default strategy found {len(candidate_moves)} moves returned from the engine and chose {top_cand.gtp()} as top move"
        self.game.katrain.log(f"[DefaultStrategy] Final decision: {top_cand.gtp()}", OUTPUT_DEBUG)
        
        return top_cand, ai_thoughts

@register_strategy(AI_HANDICAP)
class HandicapStrategy(AIStrategy):
    """Handicap strategy - uses playoutDoublingAdvantage to analyze the position"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[HandicapStrategy] Starting move generation", OUTPUT_DEBUG)
        
        # Calculate PDA (Playout Doubling Advantage)
        pda = self.settings["pda"]
        self.game.katrain.log(f"[HandicapStrategy] Initial PDA from settings: {pda}", OUTPUT_DEBUG)
        
        if self.settings["automatic"]:
            n_handicaps = len(self.game.root.get_list_property("AB", []))
            MOVE_VALUE = 14  # could be rules dependent
            b_stones_advantage = max(n_handicaps - 1, 0) - (self.cn.komi - MOVE_VALUE / 2) / MOVE_VALUE
            pda = min(3, max(-3, -b_stones_advantage * (3 / 8)))  # max PDA at 8 stone adv, normal 9 stone game is 8.46
            
            self.game.katrain.log(f"[HandicapStrategy] Automatic PDA calculation:", OUTPUT_DEBUG)
            self.game.katrain.log(f"[HandicapStrategy] - Handicap stones: {n_handicaps}", OUTPUT_DEBUG)
            self.game.katrain.log(f"[HandicapStrategy] - Komi: {self.cn.komi}", OUTPUT_DEBUG)
            self.game.katrain.log(f"[HandicapStrategy] - Stone advantage: {b_stones_advantage}", OUTPUT_DEBUG)
            self.game.katrain.log(f"[HandicapStrategy] - Calculated PDA: {pda}", OUTPUT_DEBUG)
        
        # Request additional analysis with PDA
        self.game.katrain.log(f"[HandicapStrategy] Requesting analysis with PDA={pda}", OUTPUT_DEBUG)
        handicap_analysis = self.request_analysis(
            {"playoutDoublingAdvantage": pda, "playoutDoublingAdvantagePla": "BLACK"}
        )
        
        if not handicap_analysis:
            self.game.katrain.log("[HandicapStrategy] Error getting handicap-based move, falling back to DefaultStrategy", OUTPUT_ERROR)
            return DefaultStrategy(self.game, self.settings).generate_move()
        
        self.wait_for_analysis()
        
        candidate_moves = handicap_analysis["moveInfos"]
        self.game.katrain.log(f"[HandicapStrategy] Analysis returned {len(candidate_moves)} candidate moves", OUTPUT_DEBUG)
        
        # Get top candidate move
        top_move_data = candidate_moves[0]
        top_cand = Move.from_gtp(top_move_data["move"], player=self.cn.next_player)
        
        # Log details about the top move
        self.game.katrain.log(f"[HandicapStrategy] Top move: {top_cand.gtp()}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[HandicapStrategy] Score lead: {handicap_analysis['rootInfo']['scoreLead']}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[HandicapStrategy] Win rate: {handicap_analysis['rootInfo']['winrate']}", OUTPUT_DEBUG)
        
        ai_thoughts = f"Handicap strategy found {len(candidate_moves)} moves returned from the engine and chose {top_cand.gtp()} as top move. PDA based score {self.cn.format_score(handicap_analysis['rootInfo']['scoreLead'])} and win rate {self.cn.format_winrate(handicap_analysis['rootInfo']['winrate'])}"
        
        self.game.katrain.log(f"[HandicapStrategy] Final decision: {top_cand.gtp()}", OUTPUT_DEBUG)
        return top_cand, ai_thoughts

@register_strategy(AI_ANTIMIRROR)
class AntimirrorStrategy(AIStrategy):
    """Antimirror strategy - uses antiMirror to analyze the position"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[AntimirrorStrategy] Starting move generation", OUTPUT_DEBUG)
        
        # Request analysis with antimirror option
        self.game.katrain.log(f"[AntimirrorStrategy] Requesting analysis with antiMirror=True", OUTPUT_DEBUG)
        antimirror_analysis = self.request_analysis({"antiMirror": True})
        
        if not antimirror_analysis:
            self.game.katrain.log("[AntimirrorStrategy] Error getting antimirror move, falling back to DefaultStrategy", OUTPUT_ERROR)
            return DefaultStrategy(self.game, self.settings).generate_move()
        
        self.wait_for_analysis()
        
        candidate_moves = antimirror_analysis["moveInfos"]
        self.game.katrain.log(f"[AntimirrorStrategy] Analysis returned {len(candidate_moves)} candidate moves", OUTPUT_DEBUG)
        
        # Get top candidate move
        top_move_data = candidate_moves[0]
        top_cand = Move.from_gtp(top_move_data["move"], player=self.cn.next_player)
        
        # Log details about the top move
        self.game.katrain.log(f"[AntimirrorStrategy] Top move: {top_cand.gtp()}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[AntimirrorStrategy] Score lead: {antimirror_analysis['rootInfo']['scoreLead']}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[AntimirrorStrategy] Win rate: {antimirror_analysis['rootInfo']['winrate']}", OUTPUT_DEBUG)
        
        # Log the top 3 moves for comparison
        for i, move_data in enumerate(candidate_moves[:3]):
            move = Move.from_gtp(move_data["move"], player=self.cn.next_player)
            self.game.katrain.log(f"[AntimirrorStrategy] Move #{i+1}: {move.gtp()} - visits: {move_data.get('visits', 'N/A')}, points lost: {move_data.get('pointsLost', 'N/A')}", OUTPUT_DEBUG)
        
        ai_thoughts = f"AntiMirror strategy found {len(candidate_moves)} moves returned from the engine and chose {top_cand.gtp()} as top move. antiMirror based score {self.cn.format_score(antimirror_analysis['rootInfo']['scoreLead'])} and win rate {self.cn.format_winrate(antimirror_analysis['rootInfo']['winrate'])}"
        
        self.game.katrain.log(f"[AntimirrorStrategy] Final decision: {top_cand.gtp()}", OUTPUT_DEBUG)
        return top_cand, ai_thoughts

@register_strategy(AI_JIGO)
class JigoStrategy(AIStrategy):
    """Jigo strategy - aims for a specific score difference"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[JigoStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()
        
        candidate_moves = self.cn.candidate_moves
        self.game.katrain.log(f"[JigoStrategy] Analysis found {len(candidate_moves)} candidate moves", OUTPUT_DEBUG)
        
        if not candidate_moves:
            self.game.katrain.log(f"[JigoStrategy] No candidate moves found, will play pass", OUTPUT_DEBUG)
            return Move(is_pass=True, player=self.cn.next_player), "No candidate moves found, passing"
        
        # Get top engine move for reference
        top_cand = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
        self.game.katrain.log(f"[JigoStrategy] Top engine move would be: {top_cand.gtp()}", OUTPUT_DEBUG)
        
        # Calculate player sign (1 for black, -1 for white)
        sign = self.cn.player_sign(self.cn.next_player)
        self.game.katrain.log(f"[JigoStrategy] Player sign: {sign}", OUTPUT_DEBUG)
        
        # Get target score from settings
        target_score = self.settings["target_score"]
        self.game.katrain.log(f"[JigoStrategy] Target score: {target_score}", OUTPUT_DEBUG)
        
        # Log score leads before selecting jigo move
        self.game.katrain.log("[JigoStrategy] Candidate move score leads:", OUTPUT_DEBUG)
        for i, move_data in enumerate(candidate_moves[:5]):
            move = Move.from_gtp(move_data["move"], player=self.cn.next_player)
            score_diff = abs(sign * move_data["scoreLead"] - target_score)
            self.game.katrain.log(f"[JigoStrategy] - {move.gtp()}: scoreLead={move_data['scoreLead']}, diff from target={score_diff}", OUTPUT_DEBUG)
        
        # Find the move that gives a score closest to the target
        jigo_move = min(
            candidate_moves, 
            key=lambda move: abs(sign * move["scoreLead"] - target_score)
        )
        
        aimove = Move.from_gtp(jigo_move["move"], player=self.cn.next_player)
        jigo_score_diff = abs(sign * jigo_move["scoreLead"] - target_score)
        
        self.game.katrain.log(f"[JigoStrategy] Selected move: {aimove.gtp()}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[JigoStrategy] Selected move score lead: {jigo_move['scoreLead']}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[JigoStrategy] Distance from target: {jigo_score_diff}", OUTPUT_DEBUG)
        
        ai_thoughts = f"Jigo strategy found {len(candidate_moves)} candidate moves (best {top_cand.gtp()}) and chose {aimove.gtp()} as closest to 0.5 point win"
        
        self.game.katrain.log(f"[JigoStrategy] Final decision: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

@register_strategy(AI_SCORELOSS)
class ScoreLossStrategy(AIStrategy):
    """ScoreLoss strategy - weights moves based on point loss"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[ScoreLossStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()
        
        candidate_moves = self.cn.candidate_moves
        self.game.katrain.log(f"[ScoreLossStrategy] Analysis found {len(candidate_moves)} candidate moves", OUTPUT_DEBUG)
        
        if not candidate_moves:
            self.game.katrain.log(f"[ScoreLossStrategy] No candidate moves found, will play pass", OUTPUT_DEBUG)
            return Move(is_pass=True, player=self.cn.next_player), "No candidate moves found, passing"
        
        top_cand = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
        self.game.katrain.log(f"[ScoreLossStrategy] Top engine move would be: {top_cand.gtp()}", OUTPUT_DEBUG)
        
        # Check if top move is pass
        if top_cand.is_pass:
            self.game.katrain.log(f"[ScoreLossStrategy] Top move is pass, so passing regardless of strategy", OUTPUT_DEBUG)
            return top_cand, "Top move is pass, so passing regardless of strategy."
        
        # Get strength parameter
        c = self.settings["strength"]
        self.game.katrain.log(f"[ScoreLossStrategy] Strength parameter: {c}", OUTPUT_DEBUG)
        
        # Calculate weights for moves based on point loss
        self.game.katrain.log(f"[ScoreLossStrategy] Calculating weights for candidate moves", OUTPUT_DEBUG)
        
        moves = []
        for i, d in enumerate(candidate_moves):
            move = Move.from_gtp(d["move"], player=self.cn.next_player)
            points_lost = d["pointsLost"]
            weight = math.exp(min(200, -c * max(0, points_lost)))
            
            self.game.katrain.log(f"[ScoreLossStrategy] Move {i+1}: {move.gtp()} - Points lost: {points_lost:.2f}, Weight: {weight:.6f}", OUTPUT_DEBUG)
            moves.append((points_lost, weight, move))
        
        # Select move based on weights
        self.game.katrain.log(f"[ScoreLossStrategy] Selecting move with weighted selection", OUTPUT_DEBUG)
        topmove = weighted_selection_without_replacement(moves, 1)[0]
        aimove = topmove[2]
        
        self.game.katrain.log(f"[ScoreLossStrategy] Selected move: {aimove.gtp()}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[ScoreLossStrategy] Selected move points lost: {topmove[0]:.2f}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[ScoreLossStrategy] Selected move weight: {topmove[1]:.6f}", OUTPUT_DEBUG)
        
        ai_thoughts = f"ScoreLoss strategy found {len(candidate_moves)} candidate moves (best {top_cand.gtp()}) and chose {aimove.gtp()} (weight {topmove[1]:.3f}, point loss {topmove[0]:.1f}) based on score weights."
        
        self.game.katrain.log(f"[ScoreLossStrategy] Final decision: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

class OwnershipBaseStrategy(AIStrategy):
    """Base class for ownership-based strategies"""
    
    def settledness(self, d, player_sign, player):
        """Calculate settledness for Simple Ownership strategy"""
        ownership_sum = sum([abs(o) for o in d["ownership"] if player_sign * o > 0])
        self.game.katrain.log(f"[{self.strategy_name}] Calculating settledness for {player}, sign={player_sign}: {ownership_sum:.2f}", OUTPUT_DEBUG)
        return ownership_sum
    
    def is_attachment(self, move):
        """Check if a move is an attachment"""
        if move.is_pass:
            return False
            
        stones_with_player = {(*s.coords, s.player) for s in self.game.stones}
        
        attach_opponent_stones = sum(
            (move.coords[0] + dx, move.coords[1] + dy, self.cn.player) in stones_with_player
            for dx in [-1, 0, 1]
            for dy in [-1, 0, 1]
            if abs(dx) + abs(dy) == 1
        )
        
        nearby_own_stones = sum(
            (move.coords[0] + dx, move.coords[1] + dy, self.cn.next_player) in stones_with_player
            for dx in [-2, 0, 1, 2]
            for dy in [-2 - 1, 0, 1, 2]
            if abs(dx) + abs(dy) <= 2  # allows clamps/jumps
        )
        
        is_attach = attach_opponent_stones >= 1 and nearby_own_stones == 0
        self.game.katrain.log(f"[{self.strategy_name}] Is move {move.gtp()} an attachment? {is_attach} (opponent stones: {attach_opponent_stones}, own stones: {nearby_own_stones})", OUTPUT_DEBUG)
        return is_attach
    
    def is_tenuki(self, move):
        """Check if a move is a tenuki (far from previous moves)"""
        if move.is_pass:
            return False
            
        result = not any(
            not node
            or not node.move
            or node.move.is_pass
            or max(abs(last_c - cand_c) for last_c, cand_c in zip(node.move.coords, move.coords)) < 5
            for node in [self.cn, self.cn.parent]
        )
        
        distances = []
        for node in [self.cn, self.cn.parent]:
            if node and node.move and not node.move.is_pass:
                dist = max(abs(last_c - cand_c) for last_c, cand_c in zip(node.move.coords, move.coords))
                distances.append(dist)
                
        if distances:
            self.game.katrain.log(f"[{self.strategy_name}] Is move {move.gtp()} a tenuki? {result} (distances: {distances})", OUTPUT_DEBUG)
        else:
            self.game.katrain.log(f"[{self.strategy_name}] Is move {move.gtp()} a tenuki? {result} (no valid previous moves)", OUTPUT_DEBUG)
            
        return result
    
    def get_moves_with_settledness(self):
        """Get moves with ownership and settledness information"""
        self.game.katrain.log(f"[{self.strategy_name}] Getting moves with settledness information", OUTPUT_DEBUG)
        
        next_player_sign = self.cn.player_sign(self.cn.next_player)
        candidate_moves = self.cn.candidate_moves
        
        self.game.katrain.log(f"[{self.strategy_name}] Processing {len(candidate_moves)} candidate moves", OUTPUT_DEBUG)
        self.game.katrain.log(f"[{self.strategy_name}] Settings: max_points_lost={self.settings['max_points_lost']}, min_visits={self.settings.get('min_visits', 1)}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[{self.strategy_name}] Penalties: attach={self.settings['attach_penalty']}, tenuki={self.settings['tenuki_penalty']}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[{self.strategy_name}] Weights: settled={self.settings['settled_weight']}, opponent_fac={self.settings['opponent_fac']}", OUTPUT_DEBUG)
        
        moves_data = []
        for d in candidate_moves:
            # Check basic filtering conditions
            if "pointsLost" not in d:
                self.game.katrain.log(f"[{self.strategy_name}] Move {d['move']} has no pointsLost, skipping", OUTPUT_DEBUG)
                continue
                
            if d["pointsLost"] >= self.settings["max_points_lost"]:
                self.game.katrain.log(f"[{self.strategy_name}] Move {d['move']} has pointsLost={d['pointsLost']}, which exceeds max_points_lost={self.settings['max_points_lost']}, skipping", OUTPUT_DEBUG)
                continue
                
            if "ownership" not in d:
                self.game.katrain.log(f"[{self.strategy_name}] Move {d['move']} has no ownership data, skipping", OUTPUT_DEBUG)
                continue
                
            if not (d["order"] <= 1 or d["visits"] >= self.settings.get("min_visits", 1)):
                self.game.katrain.log(f"[{self.strategy_name}] Move {d['move']} has order={d['order']} and visits={d.get('visits', 'N/A')}, doesn't meet criteria, skipping", OUTPUT_DEBUG)
                continue
            
            move = Move.from_gtp(d["move"], player=self.cn.next_player)
            if move.is_pass and d["pointsLost"] > 0.75:
                self.game.katrain.log(f"[{self.strategy_name}] Move {move.gtp()} is pass with high point loss ({d['pointsLost']}), skipping", OUTPUT_DEBUG)
                continue
            
            # Calculate metrics
            own_settledness = self.settledness(d, next_player_sign, self.cn.next_player)
            opp_settledness = self.settledness(d, -next_player_sign, self.cn.player)
            is_attach = self.is_attachment(move)
            is_tenuki = self.is_tenuki(move)
            
            # Calculate total score for sorting
            score = (d["pointsLost"] 
                    + self.settings["attach_penalty"] * is_attach 
                    + self.settings["tenuki_penalty"] * is_tenuki
                    - self.settings["settled_weight"] * (own_settledness + self.settings["opponent_fac"] * opp_settledness))
            
            self.game.katrain.log(f"[{self.strategy_name}] Move {move.gtp()}: points_lost={d['pointsLost']:.2f}, own_settled={own_settledness:.2f}, opp_settled={opp_settledness:.2f}, attach={is_attach}, tenuki={is_tenuki}, score={score:.2f}", OUTPUT_DEBUG)
            
            moves_data.append((
                move,
                own_settledness,
                opp_settledness,
                is_attach,
                is_tenuki,
                d,
                score  # Store the score for debugging
            ))
        
        # Sort moves by score
        sorted_moves = sorted(
            moves_data,
            key=lambda t: t[6]  # Sort by the precalculated score
        )
        
        self.game.katrain.log(f"[{self.strategy_name}] Found {len(sorted_moves)} valid moves with settledness data", OUTPUT_DEBUG)
        if sorted_moves:
            self.game.katrain.log(f"[{self.strategy_name}] Top move after sorting: {sorted_moves[0][0].gtp()} with score {sorted_moves[0][6]:.2f}", OUTPUT_DEBUG)
        
        # Return all data except the score which was just for debugging
        return [(move, own_settled, opp_settled, is_attach, is_tenuki, d) for move, own_settled, opp_settled, is_attach, is_tenuki, d, _ in sorted_moves]

@register_strategy(AI_SIMPLE_OWNERSHIP)
class SimpleOwnershipStrategy(OwnershipBaseStrategy):
    """Simple Ownership strategy - weights moves based on territory control"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[SimpleOwnershipStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()
        
        candidate_moves = self.cn.candidate_moves
        self.game.katrain.log(f"[SimpleOwnershipStrategy] Analysis found {len(candidate_moves)} candidate moves", OUTPUT_DEBUG)
        
        if not candidate_moves:
            self.game.katrain.log(f"[SimpleOwnershipStrategy] No candidate moves found, will play pass", OUTPUT_DEBUG)
            return Move(is_pass=True, player=self.cn.next_player), "No candidate moves found, passing"
        
        top_cand = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
        self.game.katrain.log(f"[SimpleOwnershipStrategy] Top engine move would be: {top_cand.gtp()}", OUTPUT_DEBUG)
        
        # Check if top move is pass
        if top_cand.is_pass:
            self.game.katrain.log(f"[SimpleOwnershipStrategy] Top move is pass, so passing regardless of strategy", OUTPUT_DEBUG)
            return top_cand, "Top move is pass, so passing regardless of strategy."
        
        # Get moves sorted by settledness criteria
        self.game.katrain.log(f"[SimpleOwnershipStrategy] Getting moves with settledness info", OUTPUT_DEBUG)
        moves_with_settledness = self.get_moves_with_settledness()
        
        if moves_with_settledness:
            self.game.katrain.log(f"[SimpleOwnershipStrategy] Found {len(moves_with_settledness)} moves with settledness info", OUTPUT_DEBUG)
            
            # Log top 5 candidates in detail
            self.game.katrain.log(f"[SimpleOwnershipStrategy] Top 5 candidates:", OUTPUT_DEBUG)
            for i, (move, settled, oppsettled, isattach, istenuki, d) in enumerate(moves_with_settledness[:5]):
                self.game.katrain.log(f"[SimpleOwnershipStrategy] #{i+1}: {move.gtp()} - pt_lost: {d['pointsLost']:.1f}, visits: {d.get('visits', 'N/A')}, settledness: {settled:.1f}, opp_settled: {oppsettled:.1f}, attach: {isattach}, tenuki: {istenuki}", OUTPUT_DEBUG)
            
            # Format candidate moves for ai_thoughts
            cands = [
                f"{move.gtp()} ({d['pointsLost']:.1f} pt lost, {d.get('visits', 'N/A')} visits, {settled:.1f} settledness, {oppsettled:.1f} opponent settledness{', attachment' if isattach else ''}{', tenuki' if istenuki else ''})"
                for move, settled, oppsettled, isattach, istenuki, d in moves_with_settledness[:5]
            ]
            
            ai_thoughts = f"{AI_SIMPLE_OWNERSHIP} strategy. Top 5 Candidates {', '.join(cands)} "
            aimove = moves_with_settledness[0][0]
            
            self.game.katrain.log(f"[SimpleOwnershipStrategy] Selected move: {aimove.gtp()}", OUTPUT_DEBUG)
        else:
            error_msg = "No moves found - are you using an older KataGo with no per-move ownership info?"
            self.game.katrain.log(f"[SimpleOwnershipStrategy] Error: {error_msg}", OUTPUT_ERROR)
            raise Exception(error_msg)
        
        self.game.katrain.log(f"[SimpleOwnershipStrategy] Final decision: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

@register_strategy(AI_SETTLE_STONES)
class SettleStonesStrategy(OwnershipBaseStrategy):
    """Settle Stones strategy - focuses on settled stones"""
    
    def settledness(self, d, player_sign, player):
        """Calculate settledness for Settle Stones strategy"""
        board_size_x, board_size_y = self.game.board_size
        ownership_grid = var_to_grid(d["ownership"], (board_size_x, board_size_y))
        
        # Sum the absolute ownership values of existing stones
        stone_ownership_values = [abs(ownership_grid[s.coords[0]][s.coords[1]]) for s in self.game.stones if s.player == player]
        total_settledness = sum(stone_ownership_values)
        
        self.game.katrain.log(f"[SettleStonesStrategy] Calculating settledness for {player}, sign={player_sign}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[SettleStonesStrategy] Number of stones considered: {len(stone_ownership_values)}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[SettleStonesStrategy] Total settledness: {total_settledness:.2f}", OUTPUT_DEBUG)
        
        if stone_ownership_values:
            self.game.katrain.log(f"[SettleStonesStrategy] Min stone ownership: {min(stone_ownership_values):.2f}", OUTPUT_DEBUG)
            self.game.katrain.log(f"[SettleStonesStrategy] Max stone ownership: {max(stone_ownership_values):.2f}", OUTPUT_DEBUG)
            self.game.katrain.log(f"[SettleStonesStrategy] Avg stone ownership: {total_settledness / len(stone_ownership_values):.2f}", OUTPUT_DEBUG)
        
        return total_settledness
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[SettleStonesStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()
        
        candidate_moves = self.cn.candidate_moves
        self.game.katrain.log(f"[SettleStonesStrategy] Analysis found {len(candidate_moves)} candidate moves", OUTPUT_DEBUG)
        
        if not candidate_moves:
            self.game.katrain.log(f"[SettleStonesStrategy] No candidate moves found, will play pass", OUTPUT_DEBUG)
            return Move(is_pass=True, player=self.cn.next_player), "No candidate moves found, passing"
        
        top_cand = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
        self.game.katrain.log(f"[SettleStonesStrategy] Top engine move would be: {top_cand.gtp()}", OUTPUT_DEBUG)
        
        # Check if top move is pass
        if top_cand.is_pass:
            self.game.katrain.log(f"[SettleStonesStrategy] Top move is pass, so passing regardless of strategy", OUTPUT_DEBUG)
            return top_cand, "Top move is pass, so passing regardless of strategy."
        
        # Log the number of stones on the board
        black_stones = sum(1 for s in self.game.stones if s.player == "B")
        white_stones = sum(1 for s in self.game.stones if s.player == "W")
        self.game.katrain.log(f"[SettleStonesStrategy] Stones on board: B={black_stones}, W={white_stones}", OUTPUT_DEBUG)
        
        # Get moves sorted by settledness criteria
        self.game.katrain.log(f"[SettleStonesStrategy] Getting moves with settledness info", OUTPUT_DEBUG)
        moves_with_settledness = self.get_moves_with_settledness()
        
        if moves_with_settledness:
            self.game.katrain.log(f"[SettleStonesStrategy] Found {len(moves_with_settledness)} moves with settledness info", OUTPUT_DEBUG)
            
            # Log top 5 candidates in detail
            self.game.katrain.log(f"[SettleStonesStrategy] Top 5 candidates:", OUTPUT_DEBUG)
            for i, (move, settled, oppsettled, isattach, istenuki, d) in enumerate(moves_with_settledness[:5]):
                self.game.katrain.log(f"[SettleStonesStrategy] #{i+1}: {move.gtp()} - pt_lost: {d['pointsLost']:.1f}, visits: {d.get('visits', 'N/A')}, settledness: {settled:.1f}, opp_settled: {oppsettled:.1f}, attach: {isattach}, tenuki: {istenuki}", OUTPUT_DEBUG)
            
            # Format candidate moves for ai_thoughts
            cands = [
                f"{move.gtp()} ({d['pointsLost']:.1f} pt lost, {d.get('visits', 'N/A')} visits, {settled:.1f} settledness, {oppsettled:.1f} opponent settledness{', attachment' if isattach else ''}{', tenuki' if istenuki else ''})"
                for move, settled, oppsettled, isattach, istenuki, d in moves_with_settledness[:5]
            ]
            
            ai_thoughts = f"{AI_SETTLE_STONES} strategy. Top 5 Candidates {', '.join(cands)} "
            aimove = moves_with_settledness[0][0]
            
            self.game.katrain.log(f"[SettleStonesStrategy] Selected move: {aimove.gtp()}", OUTPUT_DEBUG)
        else:
            error_msg = "No moves found - are you using an older KataGo with no per-move ownership info?"
            self.game.katrain.log(f"[SettleStonesStrategy] Error: {error_msg}", OUTPUT_ERROR)
            raise Exception(error_msg)
        
        self.game.katrain.log(f"[SettleStonesStrategy] Final decision: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

@register_strategy(AI_POLICY)
class PolicyStrategy(AIStrategy):
    """Policy strategy - plays the top move suggested by policy network"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[PolicyStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()
        
        # Ensure policy is available
        if not self.cn.policy:
            self.game.katrain.log(f"[PolicyStrategy] No policy data available, falling back to DefaultStrategy", OUTPUT_DEBUG)
            return DefaultStrategy(self.game, self.settings).generate_move()
        
        policy_moves = self.cn.policy_ranking
        pass_policy = self.cn.policy[-1]
        
        self.game.katrain.log(f"[PolicyStrategy] Got {len(policy_moves)} policy moves", OUTPUT_DEBUG)
        self.game.katrain.log(f"[PolicyStrategy] Current move depth: {self.cn.depth}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[PolicyStrategy] Opening moves setting: {self.settings.get('opening_moves', 0)}", OUTPUT_DEBUG)
        
        # Log top 5 policy moves
        self.game.katrain.log(f"[PolicyStrategy] Top 5 policy moves:", OUTPUT_DEBUG)
        for i, (prob, move) in enumerate(policy_moves[:5]):
            self.game.katrain.log(f"[PolicyStrategy] #{i+1}: {move.gtp()} - {prob:.2%}", OUTPUT_DEBUG)
        
        self.game.katrain.log(f"[PolicyStrategy] Pass policy: {pass_policy:.2%}", OUTPUT_DEBUG)
        
        # Check for pass in top 5
        top_5_pass = any([polmove[1].is_pass for polmove in policy_moves[:5]])
        self.game.katrain.log(f"[PolicyStrategy] Pass in top 5: {top_5_pass}", OUTPUT_DEBUG)
        
        # Handle opening moves override
        if self.cn.depth <= self.settings.get("opening_moves", 0):
            self.game.katrain.log(f"[PolicyStrategy] In opening phase, using WeightedStrategy instead", OUTPUT_DEBUG)
            weighted_settings = {
                "pick_override": 0.9, 
                "weaken_fac": 1, 
                "lower_bound": 0.02
            }
            self.game.katrain.log(f"[PolicyStrategy] Weighted settings: {weighted_settings}", OUTPUT_DEBUG)
            return WeightedStrategy(self.game, weighted_settings).generate_move()
        
        # Check for pass in top 5
        if top_5_pass:
            aimove = policy_moves[0][1]
            self.game.katrain.log(f"[PolicyStrategy] Playing top move {aimove.gtp()} because pass in top 5", OUTPUT_DEBUG)
            ai_thoughts = "Playing top one because one of them is pass."
            return aimove, ai_thoughts
        
        # Otherwise play top policy move
        aimove = policy_moves[0][1]
        self.game.katrain.log(f"[PolicyStrategy] Playing top policy move {aimove.gtp()} with probability {policy_moves[0][0]:.2%}", OUTPUT_DEBUG)
        ai_thoughts = f"Playing top policy move {aimove.gtp()}."
        
        self.game.katrain.log(f"[PolicyStrategy] Final decision: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

@register_strategy(AI_WEIGHTED)
class WeightedStrategy(AIStrategy):
    """Weighted strategy - weights moves based on policy and a weakening factor"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[WeightedStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()
        
        # Ensure policy is available
        if not self.cn.policy:
            self.game.katrain.log(f"[WeightedStrategy] No policy data available, falling back to DefaultStrategy", OUTPUT_DEBUG)
            return DefaultStrategy(self.game, self.settings).generate_move()
        
        policy_moves = self.cn.policy_ranking
        pass_policy = self.cn.policy[-1]
        
        self.game.katrain.log(f"[WeightedStrategy] Got {len(policy_moves)} policy moves", OUTPUT_DEBUG)
        
        # Log top 5 policy moves
        self.game.katrain.log(f"[WeightedStrategy] Top 5 policy moves:", OUTPUT_DEBUG)
        for i, (prob, move) in enumerate(policy_moves[:5]):
            self.game.katrain.log(f"[WeightedStrategy] #{i+1}: {move.gtp()} - {prob:.2%}", OUTPUT_DEBUG)
        
        self.game.katrain.log(f"[WeightedStrategy] Pass policy: {pass_policy:.2%}", OUTPUT_DEBUG)
        
        # Check for pass in top 5
        top_5_pass = any([polmove[1].is_pass for polmove in policy_moves[:5]])
        self.game.katrain.log(f"[WeightedStrategy] Pass in top 5: {top_5_pass}", OUTPUT_DEBUG)
        
        # Get override threshold
        override = self.settings.get("pick_override", 0.0)
        self.game.katrain.log(f"[WeightedStrategy] Override threshold: {override:.2%}", OUTPUT_DEBUG)
        
        # Check if we should override with top move
        override_move, override_thoughts = self.should_play_top_move(
            policy_moves, 
            top_5_pass,
            override=override
        )
        
        if override_move:
            self.game.katrain.log(f"[WeightedStrategy] Using override move: {override_move.gtp()}", OUTPUT_DEBUG)
            return override_move, override_thoughts
        
        # Apply weighted policy move selection
        lower_bound = self.settings.get("lower_bound", 0.02)
        weaken_fac = self.settings.get("weaken_fac", 1.0)
        
        self.game.katrain.log(f"[WeightedStrategy] Using weighted selection with lower_bound={lower_bound:.2%}, weaken_fac={weaken_fac}", OUTPUT_DEBUG)
        
        # Generate list of weighted coordinates
        weighted_coords = [
            (pv, pv ** (1 / weaken_fac), move) for pv, move in policy_moves if pv > lower_bound and not move.is_pass
        ]
        
        self.game.katrain.log(f"[WeightedStrategy] Found {len(weighted_coords)} moves above lower bound", OUTPUT_DEBUG)
        
        if weighted_coords:
            self.game.katrain.log(f"[WeightedStrategy] Performing weighted selection", OUTPUT_DEBUG)
            top = weighted_selection_without_replacement(weighted_coords, 1)[0]
            move = top[2]
            prob = top[0]
            
            self.game.katrain.log(f"[WeightedStrategy] Selected move {move.gtp()} with probability {prob:.2%}", OUTPUT_DEBUG)
            ai_thoughts = f"Playing policy-weighted random move {move.gtp()} ({prob:.1%}) from {len(weighted_coords)} moves above lower_bound of {lower_bound:.1%}."
        else:
            move = policy_moves[0][1]
            self.game.katrain.log(f"[WeightedStrategy] No moves above lower bound, playing top policy move {move.gtp()}", OUTPUT_DEBUG)
            ai_thoughts = f"Playing top policy move because no non-pass move > above lower_bound of {lower_bound:.1%}."
        
        self.game.katrain.log(f"[WeightedStrategy] Final decision: {move.gtp()}", OUTPUT_DEBUG)
        return move, ai_thoughts

class PickBasedStrategy(AIStrategy):
    """Base class for pick-based strategies"""
    
    def get_n_moves(self, legal_policy_moves):
        """Calculate the number of moves to consider"""
        board_squares = self.game.board_size[0] * self.game.board_size[1]
        
        if self.settings.get("pick_frac") is not None:
            n_moves = max(1, int(self.settings["pick_frac"] * len(legal_policy_moves) + self.settings["pick_n"]))
            self.game.katrain.log(f"[{self.strategy_name}] Calculated n_moves={n_moves} from pick_frac={self.settings['pick_frac']}, pick_n={self.settings['pick_n']}, legal_moves={len(legal_policy_moves)}", OUTPUT_DEBUG)
        else:
            n_moves = 1  # Default
            self.game.katrain.log(f"[{self.strategy_name}] Using default n_moves={n_moves} (no pick_frac in settings)", OUTPUT_DEBUG)
            
        return n_moves
    
    def generate_weighted_coords(self, legal_policy_moves, policy_grid, size):
        """Generate weighted coordinates for selection"""
        self.game.katrain.log(f"[{self.strategy_name}] Generating weighted coordinates (default equal weights implementation)", OUTPUT_DEBUG)
        
        # Default implementation for AI_PICK - equal weights
        weighted_coords = [
            (policy_grid[y][x], 1, x, y)
            for x in range(size[0])
            for y in range(size[1])
            if policy_grid[y][x] > 0
        ]
        
        self.game.katrain.log(f"[{self.strategy_name}] Generated {len(weighted_coords)} weighted coordinates", OUTPUT_DEBUG)
        
        if weighted_coords:
            top5 = heapq.nlargest(5, weighted_coords, key=lambda t: t[0])
            self.game.katrain.log(f"[{self.strategy_name}] Top 5 weighted coordinates by policy value:", OUTPUT_DEBUG)
            for i, (pol, wt, x, y) in enumerate(top5):
                self.game.katrain.log(f"[{self.strategy_name}] #{i+1}: ({x},{y}) - policy={pol:.2%}, weight={wt}", OUTPUT_DEBUG)
                
        return weighted_coords, "Generated equal weights for all moves. "
    
    def handle_endgame(self, legal_policy_moves, policy_grid, size):
        """Handle special endgame case"""
        board_squares = size[0] * size[1]
        endgame_threshold = self.settings.get("endgame", 0.75) * board_squares
        
        self.game.katrain.log(f"[{self.strategy_name}] Checking endgame condition: move depth {self.cn.depth} vs threshold {endgame_threshold}", OUTPUT_DEBUG)
        
        if self.cn.depth > endgame_threshold:
            self.game.katrain.log(f"[{self.strategy_name}] In endgame phase (move {self.cn.depth} > {endgame_threshold})", OUTPUT_DEBUG)
            
            weighted_coords = [(pol, 1, *mv.coords) for pol, mv in legal_policy_moves]
            ai_thoughts = f"Generated equal weights as move number >= {self.settings['endgame'] * size[0] * size[1]}. "
            
            n_moves = int(max(self.get_n_moves(legal_policy_moves), len(legal_policy_moves) // 2))
            self.game.katrain.log(f"[{self.strategy_name}] Using endgame n_moves={n_moves}", OUTPUT_DEBUG)
            
            self.game.katrain.log(f"[{self.strategy_name}] Generated {len(weighted_coords)} weighted coordinates for endgame", OUTPUT_DEBUG)
            
            return weighted_coords, ai_thoughts, n_moves, True
            
        self.game.katrain.log(f"[{self.strategy_name}] Not in endgame phase yet", OUTPUT_DEBUG)
        return None, "", None, False
    
    def select_from_weighted_coords(self, weighted_coords, n_moves, pass_policy):
        """Select moves from weighted coordinates"""
        self.game.katrain.log(f"[{self.strategy_name}] Selecting from {len(weighted_coords)} weighted coordinates, n_moves={n_moves}", OUTPUT_DEBUG)
        
        # Perform weighted selection
        pick_moves = weighted_selection_without_replacement(weighted_coords, n_moves)
        self.game.katrain.log(f"[{self.strategy_name}] Picked {len(pick_moves)} moves", OUTPUT_DEBUG)
        
        if pick_moves:
            # Get top 5 from picked moves
            top_picked = heapq.nlargest(5, pick_moves)
            self.game.katrain.log(f"[{self.strategy_name}] Top 5 after selection:", OUTPUT_DEBUG)
            for i, (p, wt, x, y) in enumerate(top_picked):
                self.game.katrain.log(f"[{self.strategy_name}] #{i+1}: ({x},{y}) - policy={p:.2%}, weight={wt}", OUTPUT_DEBUG)
            
            # Convert to move objects
            new_top = [
                (p, Move((x, y), player=self.cn.next_player)) for p, wt, x, y in top_picked
            ]
            
            aimove = new_top[0][1]
            ai_thoughts = f"Top 5 among these were {fmt_moves(new_top)} and picked top {aimove.gtp()}. "
            
            self.game.katrain.log(f"[{self.strategy_name}] Top picked move: {aimove.gtp()} ({new_top[0][0]:.2%})", OUTPUT_DEBUG)
            self.game.katrain.log(f"[{self.strategy_name}] Pass policy: {pass_policy:.2%}", OUTPUT_DEBUG)
            
            # Check if pass is better
            if new_top[0][0] < pass_policy:
                self.game.katrain.log(f"[{self.strategy_name}] Pass policy {pass_policy:.2%} is better than top move {aimove.gtp()} ({new_top[0][0]:.2%}), switching to top policy move", OUTPUT_DEBUG)
                
                policy_moves = self.cn.policy_ranking
                top_policy_move = policy_moves[0][1]
                
                ai_thoughts += f"But found pass ({pass_policy:.2%} to be higher rated than {aimove.gtp()} ({new_top[0][0]:.2%}) so will play top policy move instead."
                aimove = top_policy_move
                
                self.game.katrain.log(f"[{self.strategy_name}] Final move (after pass check): {aimove.gtp()}", OUTPUT_DEBUG)
            else:
                self.game.katrain.log(f"[{self.strategy_name}] Top move is better than pass, keeping it", OUTPUT_DEBUG)
        else:
            self.game.katrain.log(f"[{self.strategy_name}] No moves selected, falling back to top policy move", OUTPUT_DEBUG)
            
            policy_moves = self.cn.policy_ranking
            top_policy_move = policy_moves[0][1]
            aimove = top_policy_move
            
            ai_thoughts = f"Pick policy strategy failed to find legal moves, so is playing top policy move {aimove.gtp()}."
            
            self.game.katrain.log(f"[{self.strategy_name}] Final move (fallback): {aimove.gtp()}", OUTPUT_DEBUG)
            
        return aimove, ai_thoughts
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[{self.strategy_name}] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()
        
        # Ensure policy is available
        if not self.cn.policy:
            self.game.katrain.log(f"[{self.strategy_name}] No policy data available, falling back to DefaultStrategy", OUTPUT_DEBUG)
            return DefaultStrategy(self.game, self.settings).generate_move()
        
        policy_moves = self.cn.policy_ranking
        pass_policy = self.cn.policy[-1]
        
        self.game.katrain.log(f"[{self.strategy_name}] Got {len(policy_moves)} policy moves", OUTPUT_DEBUG)
        
        # Log top 5 policy moves
        self.game.katrain.log(f"[{self.strategy_name}] Top 5 policy moves:", OUTPUT_DEBUG)
        for i, (prob, move) in enumerate(policy_moves[:5]):
            self.game.katrain.log(f"[{self.strategy_name}] #{i+1}: {move.gtp()} - {prob:.2%}", OUTPUT_DEBUG)
        
        self.game.katrain.log(f"[{self.strategy_name}] Pass policy: {pass_policy:.2%}", OUTPUT_DEBUG)
        
        # Check for pass in top 5
        top_5_pass = any([polmove[1].is_pass for polmove in policy_moves[:5]])
        self.game.katrain.log(f"[{self.strategy_name}] Pass in top 5: {top_5_pass}", OUTPUT_DEBUG)
        
        # Get override settings
        override = self.settings.get("pick_override", 0.0)
        overridetwo = self.settings.get("pick_override_two", 1.0)
        self.game.katrain.log(f"[{self.strategy_name}] Override settings: single={override:.2%}, combined={overridetwo:.2%}", OUTPUT_DEBUG)
        
        # Check if we should override with top move
        override_move, override_thoughts = self.should_play_top_move(
            policy_moves, 
            top_5_pass,
            override=override,
            overridetwo=overridetwo
        )
        
        if override_move:
            self.game.katrain.log(f"[{self.strategy_name}] Using override move: {override_move.gtp()}", OUTPUT_DEBUG)
            return override_move, override_thoughts
        
        # Get legal policy moves
        legal_policy_moves = [(pol, mv) for pol, mv in policy_moves if not mv.is_pass and pol > 0]
        self.game.katrain.log(f"[{self.strategy_name}] Found {len(legal_policy_moves)} legal non-pass policy moves", OUTPUT_DEBUG)
        
        # Create policy grid
# Create policy grid
        size = self.game.board_size
        self.game.katrain.log(f"[{self.strategy_name}] Board size: {size}", OUTPUT_DEBUG)
        policy_grid = var_to_grid(self.cn.policy, size)
        
        # Check for endgame
        end_coords, end_thoughts, end_n_moves, is_endgame = self.handle_endgame(legal_policy_moves, policy_grid, size)
        
        if is_endgame:
            self.game.katrain.log(f"[{self.strategy_name}] Using endgame logic", OUTPUT_DEBUG)
            return self.select_from_weighted_coords(end_coords, end_n_moves, pass_policy)
        
        # Get weighted coordinates
        self.game.katrain.log(f"[{self.strategy_name}] Generating weighted coordinates", OUTPUT_DEBUG)
        weighted_coords, weight_thoughts = self.generate_weighted_coords(legal_policy_moves, policy_grid, size)
        
        # Get number of moves to consider
        n_moves = self.get_n_moves(legal_policy_moves)
        self.game.katrain.log(f"[{self.strategy_name}] Using n_moves={n_moves}", OUTPUT_DEBUG)
        
        ai_thoughts = weight_thoughts + f"Picked {min(n_moves, len(weighted_coords))} random moves according to weights. "
        
        # Select and return move
        self.game.katrain.log(f"[{self.strategy_name}] Selecting move from weighted coordinates", OUTPUT_DEBUG)
        move, thoughts = self.select_from_weighted_coords(weighted_coords, n_moves, pass_policy)
        
        self.game.katrain.log(f"[{self.strategy_name}] Final decision: {move.gtp()}", OUTPUT_DEBUG)
        return move, ai_thoughts + thoughts

@register_strategy(AI_PICK)
class PickStrategy(PickBasedStrategy):
    """Pick strategy - picks a move from a subset of legal moves"""
    
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[PickStrategy] Starting move generation using base PickBasedStrategy implementation", OUTPUT_DEBUG)
        return super().generate_move()

    def handle_endgame(self, legal_policy_moves, policy_grid, size):
        return None, "", None, False

@register_strategy(AI_RANK)
class RankStrategy(PickBasedStrategy):
    """Rank strategy - similar to Pick but calibrated based on rank"""
    
    def get_n_moves(self, legal_policy_moves):
        """Calculate n_moves based on rank"""
        self.game.katrain.log(f"[RankStrategy] Calculating n_moves based on rank", OUTPUT_DEBUG)
        
        size = self.game.board_size
        board_squares = size[0] * size[1]
        norm_leg_moves = len(legal_policy_moves) / board_squares
        
        self.game.katrain.log(f"[RankStrategy] Board squares: {board_squares}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[RankStrategy] Legal moves: {len(legal_policy_moves)}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[RankStrategy] Normalized legal moves: {norm_leg_moves:.4f}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[RankStrategy] Kyu rank: {self.settings['kyu_rank']}", OUTPUT_DEBUG)
        
        # Calculate n_moves using the rank formula
        orig_calib_avemodrank = 0.063015 + 0.7624 * board_squares / (
            10 ** (-0.05737 * self.settings["kyu_rank"] + 1.9482)
        )
        
        self.game.katrain.log(f"[RankStrategy] Original calibrated average mod rank: {orig_calib_avemodrank:.4f}", OUTPUT_DEBUG)
        
        exponent_term = (
            3.002 * norm_leg_moves * norm_leg_moves
            - norm_leg_moves
            - 0.034889 * self.settings["kyu_rank"]
            - 0.5097
        )
        self.game.katrain.log(f"[RankStrategy] Exponent term: {exponent_term:.4f}", OUTPUT_DEBUG)
        
        modified_calib_avemodrank = (
            0.3931
            + 0.6559
            * norm_leg_moves
            * math.exp(-1 * exponent_term ** 2)
            - 0.01093 * self.settings["kyu_rank"]
        ) * orig_calib_avemodrank
        
        self.game.katrain.log(f"[RankStrategy] Modified calibrated average mod rank: {modified_calib_avemodrank:.4f}", OUTPUT_DEBUG)
        
        denominator = 1.31165 * (modified_calib_avemodrank + 1) - 0.082653
        self.game.katrain.log(f"[RankStrategy] Denominator: {denominator:.4f}", OUTPUT_DEBUG)
        
        n_moves = board_squares * norm_leg_moves / denominator
        n_moves = max(1, round(n_moves))
        
        self.game.katrain.log(f"[RankStrategy] Calculated n_moves: {n_moves}", OUTPUT_DEBUG)
        
        return n_moves
    
    def should_play_top_move(self, policy_moves, top_5_pass, override=0.0, overridetwo=1.0):
        """Special override logic for rank-based"""
        self.game.katrain.log(f"[RankStrategy] Calculating special override thresholds based on rank", OUTPUT_DEBUG)
        
        size = self.game.board_size
        board_squares = size[0] * size[1]
        legal_policy_moves = [(pol, mv) for pol, mv in policy_moves if not mv.is_pass and pol > 0]
        
        # Parameters for calculating the overrides
        self.game.katrain.log(f"[RankStrategy] Board squares: {board_squares}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[RankStrategy] Legal non-pass moves: {len(legal_policy_moves)}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[RankStrategy] Kyu rank: {self.settings['kyu_rank']}", OUTPUT_DEBUG)
        
        # Calibrated override based on board filling
        ratio = (board_squares - len(legal_policy_moves)) / board_squares
        override = 0.8 * (1 - 0.5 * ratio)
        self.game.katrain.log(f"[RankStrategy] Calculated override: {override:.2%} (from board filling ratio {ratio:.2f})", OUTPUT_DEBUG)
        
        overridetwo = 0.85 + max(0, 0.02 * (self.settings["kyu_rank"] - 8))
        self.game.katrain.log(f"[RankStrategy] Calculated overridetwo: {overridetwo:.2%} (from kyu rank adjustment)", OUTPUT_DEBUG)
        
        # Call the parent class method with calculated overrides
        return super().should_play_top_move(policy_moves, top_5_pass, override, overridetwo)

    def handle_endgame(self, legal_policy_moves, policy_grid, size):
        return None, "", None, False

@register_strategy(AI_INFLUENCE)
class InfluenceStrategy(PickBasedStrategy):
    """Influence strategy - weights moves based on influence (distance from edge)"""
    
    def generate_weighted_coords(self, legal_policy_moves, policy_grid, size):
        """Generate influence-based weights"""
        self.game.katrain.log(f"[InfluenceStrategy] Generating influence-based weights", OUTPUT_DEBUG)
        self.game.katrain.log(f"[InfluenceStrategy] Settings: threshold={self.settings['threshold']}, line_weight={self.settings['line_weight']}", OUTPUT_DEBUG)
        weighted_coords, ai_thoughts = generate_influence_territory_weights(
            AI_INFLUENCE, 
            self.settings, 
            policy_grid, 
            size
        )
        self.game.katrain.log(f"[InfluenceStrategy] Generated {len(weighted_coords)} weighted coordinates", OUTPUT_DEBUG)
        if weighted_coords:
            top5 = heapq.nlargest(5, weighted_coords, key=lambda t: t[0] * t[1])
            self.game.katrain.log(f"[InfluenceStrategy] Top 5 weighted coordinates (by policy*weight):", OUTPUT_DEBUG)
            for i, (pol, wt, x, y) in enumerate(top5):
                self.game.katrain.log(f"[InfluenceStrategy] #{i+1}: ({x},{y}) - policy={pol:.2%}, weight={wt}, combined={pol*wt:.2%}", OUTPUT_DEBUG)
        return weighted_coords, ai_thoughts

@register_strategy(AI_TERRITORY)
class TerritoryStrategy(PickBasedStrategy):
    """Territory strategy - weights moves based on territory (distance from center)"""
    
    def generate_weighted_coords(self, legal_policy_moves, policy_grid, size):
        """Generate territory-based weights"""
        self.game.katrain.log(f"[TerritoryStrategy] Generating territory-based weights", OUTPUT_DEBUG)
        self.game.katrain.log(f"[TerritoryStrategy] Settings: threshold={self.settings['threshold']}, line_weight={self.settings['line_weight']}", OUTPUT_DEBUG)
        weighted_coords, ai_thoughts = generate_influence_territory_weights(
            AI_TERRITORY, 
            self.settings, 
            policy_grid, 
            size
        )
        self.game.katrain.log(f"[TerritoryStrategy] Generated {len(weighted_coords)} weighted coordinates", OUTPUT_DEBUG)
        if weighted_coords:
            top5 = heapq.nlargest(5, weighted_coords, key=lambda t: t[0] * t[1])
            self.game.katrain.log(f"[TerritoryStrategy] Top 5 weighted coordinates (by policy*weight):", OUTPUT_DEBUG)
            for i, (pol, wt, x, y) in enumerate(top5):
                self.game.katrain.log(f"[TerritoryStrategy] #{i+1}: ({x},{y}) - policy={pol:.2%}, weight={wt}, combined={pol*wt:.2%}", OUTPUT_DEBUG)
        return weighted_coords, ai_thoughts

@register_strategy(AI_LOCAL)
class LocalStrategy(PickBasedStrategy):
    """Local strategy - weights moves based on proximity to the last move"""
    
    def generate_move(self) -> Tuple[Move, str]:
        # Handle the case where there's no previous move
        if not (self.cn.move and self.cn.move.coords):
            self.game.katrain.log(f"[LocalStrategy] No previous move with valid coordinates found, falling back to WeightedStrategy", OUTPUT_DEBUG)
            self.game.katrain.log(f"[LocalStrategy] Using default weighted settings: pick_override=0.9, weaken_fac=1, lower_bound=0.02", OUTPUT_DEBUG)
            return WeightedStrategy(self.game, {
                "pick_override": 0.9, 
                "weaken_fac": 1, 
                "lower_bound": 0.02
            }).generate_move()
        
        return super().generate_move()
    
    def generate_weighted_coords(self, legal_policy_moves, policy_grid, size):
        """Generate local-based weights"""
        self.game.katrain.log(f"[LocalStrategy] Generating local-based weights around previous move", OUTPUT_DEBUG)
        self.game.katrain.log(f"[LocalStrategy] Previous move: {self.cn.move.gtp()}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[LocalStrategy] Variance setting: {self.settings['stddev']}", OUTPUT_DEBUG)
        weighted_coords, ai_thoughts = generate_local_tenuki_weights(
            AI_LOCAL, 
            self.settings, 
            policy_grid, 
            self.cn, 
            size
        )
        self.game.katrain.log(f"[LocalStrategy] Generated {len(weighted_coords)} weighted coordinates", OUTPUT_DEBUG)
        if weighted_coords:
            top5 = heapq.nlargest(5, weighted_coords, key=lambda t: t[0] * t[1])
            self.game.katrain.log(f"[LocalStrategy] Top 5 weighted coordinates (by policy*weight):", OUTPUT_DEBUG)
            for i, (pol, wt, x, y) in enumerate(top5):
                self.game.katrain.log(f"[LocalStrategy] #{i+1}: ({x},{y}) - policy={pol:.2%}, weight={wt}, combined={pol*wt:.2%}", OUTPUT_DEBUG)
        return weighted_coords, ai_thoughts

@register_strategy(AI_TENUKI)
class TenukiStrategy(PickBasedStrategy):
    """Tenuki strategy - weights moves based on distance from the last move"""
    
    def generate_move(self) -> Tuple[Move, str]:
        # Handle the case where there's no previous move
        if not (self.cn.move and self.cn.move.coords):
            self.game.katrain.log(f"[TenukiStrategy] No previous move with valid coordinates found, falling back to WeightedStrategy", OUTPUT_DEBUG)
            self.game.katrain.log(f"[TenukiStrategy] Using default weighted settings: pick_override=0.9, weaken_fac=1, lower_bound=0.02", OUTPUT_DEBUG)
            return WeightedStrategy(self.game, {
                "pick_override": 0.9, 
                "weaken_fac": 1, 
                "lower_bound": 0.02
            }).generate_move()
        
        return super().generate_move()
    
    def generate_weighted_coords(self, legal_policy_moves, policy_grid, size):
        """Generate tenuki-based weights"""
        self.game.katrain.log(f"[TenukiStrategy] Generating tenuki-based weights (far from previous move)", OUTPUT_DEBUG)
        self.game.katrain.log(f"[TenukiStrategy] Previous move: {self.cn.move.gtp()}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[TenukiStrategy] Variance setting: {self.settings['stddev']}", OUTPUT_DEBUG)
        weighted_coords, ai_thoughts = generate_local_tenuki_weights(
            AI_TENUKI, 
            self.settings, 
            policy_grid, 
            self.cn, 
            size
        )
        self.game.katrain.log(f"[TenukiStrategy] Generated {len(weighted_coords)} weighted coordinates", OUTPUT_DEBUG)
        if weighted_coords:
            top5 = heapq.nlargest(5, weighted_coords, key=lambda t: t[0] * t[1])
            self.game.katrain.log(f"[TenukiStrategy] Top 5 weighted coordinates (by policy*weight):", OUTPUT_DEBUG)
            for i, (pol, wt, x, y) in enumerate(top5):
                self.game.katrain.log(f"[TenukiStrategy] #{i+1}: ({x},{y}) - policy={pol:.2%}, weight={wt}, combined={pol*wt:.2%}", OUTPUT_DEBUG)
        return weighted_coords, ai_thoughts

@register_strategy(AI_FIGHTING)
class FightingStrategy(PickBasedStrategy):
    """Fighting strategy - weights moves toward unsettled areas near opponent stones"""

    def generate_move(self) -> Tuple[Move, str]:
        mode = self.settings.get("fighting_mode", "classic")
        self.game.katrain.log(f"[FightingStrategy] Mode: {mode}", OUTPUT_DEBUG)
        if mode == "scoreloss":
            return self._generate_scoreloss()
        elif mode == "human":
            return self._generate_human()
        else:
            return self._generate_classic()

    def _generate_classic(self) -> Tuple[Move, str]:
        # Need at least a few opponent stones for fighting weights to be meaningful
        opponent_stones = [s for s in self.game.stones if s.player != self.cn.next_player]
        if len(opponent_stones) < 2:
            self.game.katrain.log(
                f"[FightingStrategy] Too few opponent stones ({len(opponent_stones)}), falling back to WeightedStrategy",
                OUTPUT_DEBUG,
            )
            return WeightedStrategy(self.game, {
                "pick_override": 0.9,
                "weaken_fac": 1,
                "lower_bound": 0.02,
            }).generate_move()
        return super().generate_move()

    def _build_fighting_weight_dict(self):
        """力戦重みの辞書 {(x,y): weight} を返す"""
        size = self.game.board_size
        ownership_grid = var_to_grid(self.cn.ownership, size) if self.cn.ownership else None
        opponent_coords = [s.coords for s in self.game.stones if s.player != self.cn.next_player]
        unsettled_power = self.settings.get("unsettled_power", 2.0)
        prox_var = self.settings.get("proximity_stddev", 3.0) ** 2
        weights = {}
        for x in range(size[0]):
            for y in range(size[1]):
                unsettled = (1.0 - abs(ownership_grid[y][x])) ** unsettled_power if ownership_grid else 1.0
                if opponent_coords:
                    min_dist_sq = min((x - ox) ** 2 + (y - oy) ** 2 for ox, oy in opponent_coords)
                    prox = math.exp(-0.5 * min_dist_sq / prox_var)
                else:
                    prox = 1.0
                weights[(x, y)] = max(unsettled * prox, 1e-6)
        return weights

    def _generate_scoreloss(self) -> Tuple[Move, str]:
        """案A: ScoreLoss系フィルタ + 力戦重みで着手選択"""
        self.game.katrain.log(f"[FightingStrategy:scoreloss] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()

        candidate_moves = self.cn.candidate_moves
        if not candidate_moves:
            self.game.katrain.log(f"[FightingStrategy:scoreloss] No candidate moves, passing", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "No candidate moves found, passing."

        # パスが最善なら強制パス
        top_cand = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
        if top_cand.is_pass:
            self.game.katrain.log(f"[FightingStrategy:scoreloss] Top move is pass, forcing pass", OUTPUT_DEBUG)
            return top_cand, "Top move is pass, forcing pass."

        # 損失フィルタ
        fighting_max_loss = self.settings.get("fighting_max_loss", 3.0)
        good_moves = [d for d in candidate_moves if d["pointsLost"] < fighting_max_loss and not Move.from_gtp(d["move"], player=self.cn.next_player).is_pass]
        self.game.katrain.log(
            f"[FightingStrategy:scoreloss] {len(good_moves)}/{len(candidate_moves)} moves pass loss filter (max_loss={fighting_max_loss})",
            OUTPUT_DEBUG,
        )

        if not good_moves:
            self.game.katrain.log(f"[FightingStrategy:scoreloss] No moves pass filter, using best move", OUTPUT_DEBUG)
            return top_cand, "All moves exceed loss threshold, playing best move."

        # 力戦重み
        opponent_stones = [s for s in self.game.stones if s.player != self.cn.next_player]
        if len(opponent_stones) >= 2:
            fighting_weights = self._build_fighting_weight_dict()
        else:
            fighting_weights = {}

        # 損失重み × 力戦重み
        weighted_moves = []
        for d in good_moves:
            move = Move.from_gtp(d["move"], player=self.cn.next_player)
            points_lost = d["pointsLost"]
            score_weight = math.exp(min(200, -5 * max(0, points_lost)))
            fight_weight = fighting_weights.get(move.coords, 1e-6) if move.coords and fighting_weights else 1.0
            combined = score_weight * fight_weight
            weighted_moves.append((points_lost, combined, move))

        # デバッグ: 上位5手表示
        top5 = heapq.nlargest(5, weighted_moves, key=lambda t: t[1])
        self.game.katrain.log(f"[FightingStrategy:scoreloss] Top 5 weighted moves:", OUTPUT_DEBUG)
        for i, (pl, w, m) in enumerate(top5):
            self.game.katrain.log(f"  #{i+1}: {m.gtp()} loss={pl:.2f} weight={w:.4f}", OUTPUT_DEBUG)

        # 重み付き選択
        selected = weighted_selection_without_replacement(weighted_moves, 1)[0]
        aimove = selected[2]
        ai_thoughts = (
            f"ScoreLoss+Fighting: {len(good_moves)} moves within {fighting_max_loss}pt loss. "
            f"Selected {aimove.gtp()} (loss={selected[0]:.1f}, weight={selected[1]:.3f})."
        )
        self.game.katrain.log(f"[FightingStrategy:scoreloss] Selected: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

    def _generate_human(self) -> Tuple[Move, str]:
        """案B: HumanStyleStrategy拡張 + 力戦重みで着���選択"""
        self.game.katrain.log(f"[FightingStrategy:human] Starting move generation", OUTPUT_DEBUG)

        # 標準解析を待つ（ownership取得のため）
        self.wait_for_analysis()

        # --- Stage 1: humanSLProfile付きクエリ（9段固定） ---
        human_profile = "rank_9d"
        override_settings = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 800,
        }
        self.game.katrain.log(f"[FightingStrategy:human] Stage 1: requesting humanSL analysis ({human_profile})", OUTPUT_DEBUG)

        analysis = None
        error = False

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[FightingStrategy:human] Error in Stage 1: {a}", OUTPUT_ERROR)

        engine = self.game.engines[self.cn.player]
        engine.request_analysis(
            self.cn,
            callback=set_analysis,
            error_callback=set_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=True,
            extra_settings=override_settings,
        )

        while not (error or analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if error or not analysis or "humanPolicy" not in analysis:
            self.game.katrain.log(f"[FightingStrategy:human] Stage 1 failed, falling back to scoreloss mode", OUTPUT_DEBUG)
            return self._generate_scoreloss()

        board_size = self.game.board_size
        human_policy = analysis["humanPolicy"]

        # --- Stage 2: クリーンクエリ（正確なスコア取得） ---
        clean_override_settings = {
            "ignorePreRootHistory": False,
            "maxVisits": 600,
            "wideRootNoise": 0.0,
        }
        clean_analysis = None
        clean_error = False

        def set_clean_analysis(a, partial_result):
            nonlocal clean_analysis
            if not partial_result:
                clean_analysis = a

        def set_clean_error(a):
            nonlocal clean_error
            clean_error = True
            self.game.katrain.log(f"[FightingStrategy:human] Error in Stage 2: {a}", OUTPUT_ERROR)

        self.game.katrain.log(f"[FightingStrategy:human] Stage 2: requesting clean analysis", OUTPUT_DEBUG)
        engine.request_analysis(
            self.cn,
            callback=set_clean_analysis,
            error_callback=set_clean_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=False,
            extra_settings=clean_override_settings,
        )

        while not (clean_error or clean_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        # --- 悪手フィ��タ ---
        bx, by = board_size
        opening_boundary = math.ceil(0.14 * bx * by)
        if bx == 9 and by == 9:
            OPENING_THRESHOLD = 0.5
            NORMAL_THRESHOLD = 3.3
        else:
            OPENING_THRESHOLD = 2.8
            NORMAL_THRESHOLD = 5.6
        current_move = self.cn.depth
        BAD_MOVE_THRESHOLD = OPENING_THRESHOLD if current_move < opening_boundary else NORMAL_THRESHOLD

        if clean_analysis and not clean_error:
            move_infos = clean_analysis.get("moveInfos", [])
            self.game.katrain.log(f"[FightingStrategy:human] Using clean moveInfos ({len(move_infos)} moves)", OUTPUT_DEBUG)
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log(f"[FightingStrategy:human] Clean query failed, using biased moveInfos", OUTPUT_DEBUG)

        good_moves = set()
        best_gtp_by_score = None
        if move_infos:
            player_sign = 1 if self.cn.next_player == "B" else -1
            best_score = max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
            best_gtp_by_score = max(
                move_infos, key=lambda mi: mi.get("scoreLead", 0) * player_sign
            ).get("move", "")

            if best_gtp_by_score == "pass":
                self.game.katrain.log(f"[FightingStrategy:human] Best move is pass, forcing pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."

            self.game.katrain.log(
                f"[FightingStrategy:human] Move {current_move}: threshold={BAD_MOVE_THRESHOLD}, best_score={best_score:.1f}",
                OUTPUT_DEBUG,
            )
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss < BAD_MOVE_THRESHOLD:
                    good_moves.add(gtp_move)
            self.game.katrain.log(
                f"[FightingStrategy:human] {len(good_moves)} moves pass score filter",
                OUTPUT_DEBUG,
            )

            # --- 安全弁クロスバリデーション用ヘルパー ---
            def _safety_valve_cross_check(forced_gtp, candidate_gtp, p_sign, label="v1"):
                """安全弁の強制手をRegular分析でクロスチェック。安全ならTrue。"""
                _CROSS_CHECK_MAX_LOSS = 2.0
                _reg_moves = self.cn.analysis.get("moves", {})
                _reg_forced = _reg_moves.get(forced_gtp)
                _reg_candidate = _reg_moves.get(candidate_gtp)
                if _reg_forced is None:
                    self.game.katrain.log(
                        f"[FightingStrategy:human] Safety {label}: {forced_gtp} not in regular analysis, skipping force",
                        OUTPUT_DEBUG,
                    )
                    return False
                if _reg_candidate is None:
                    return True
                reg_forced_score = _reg_forced.get("scoreLead", 0)
                reg_cand_score = _reg_candidate.get("scoreLead", 0)
                reg_loss = p_sign * (reg_cand_score - reg_forced_score)
                if reg_loss > _CROSS_CHECK_MAX_LOSS:
                    self.game.katrain.log(
                        f"[FightingStrategy:human] Safety {label} cross-check FAILED: "
                        f"{forced_gtp} loses {reg_loss:.2f}pt vs {candidate_gtp} in regular analysis",
                        OUTPUT_DEBUG,
                    )
                    return False
                return True

            # 安全弁: 最多探索手のlossが閾値以上なら最善スコア手を確定選択（力戦特性を無視）
            _SAFETY_LOSS_THRESHOLD = 3.4
            max_visit_mi = max(move_infos, key=lambda mi: mi.get("visits", 0))
            max_visit_gtp = max_visit_mi.get("move", "")
            max_visit_score = max_visit_mi.get("scoreLead", 0)
            max_visit_loss = player_sign * (best_score - max_visit_score)
            if max_visit_loss >= _SAFETY_LOSS_THRESHOLD and best_gtp_by_score and best_gtp_by_score != max_visit_gtp:
                if _safety_valve_cross_check(best_gtp_by_score, max_visit_gtp, player_sign, "v1"):
                    self.game.katrain.log(
                        f"[FightingStrategy:human] Safety valve: max-visit move {max_visit_gtp} "
                        f"loss={max_visit_loss:.2f} >= {_SAFETY_LOSS_THRESHOLD}, "
                        f"forcing best-score move {best_gtp_by_score}",
                        OUTPUT_DEBUG,
                    )
                    if best_gtp_by_score == "pass":
                        return Move(None, player=self.cn.next_player), "Safety valve: best move is pass."
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                        f"Safety valve: max-visit {max_visit_gtp} had loss={max_visit_loss:.2f}, "
                        f"forced best-score move {best_gtp_by_score}."
                    )

        # --- humanPolicy × fighting_weight で候補構築 ---
        opponent_stones = [s for s in self.game.stones if s.player != self.cn.next_player]
        if len(opponent_stones) >= 2:
            fighting_weights = self._build_fighting_weight_dict()
        else:
            fighting_weights = {}

        moves = []
        filtered_count = 0
        has_filter = len(good_moves) > 0
        for x in range(board_size[0]):
            for y in range(board_size[1]):
                idx = (board_size[1] - y - 1) * board_size[0] + x
                if idx < len(human_policy) and human_policy[idx] > 0:
                    m = Move((x, y), player=self.cn.next_player)
                    if has_filter and m.gtp() not in good_moves:
                        filtered_count += 1
                    else:
                        hp_weight = human_policy[idx]
                        fight_weight = fighting_weights.get((x, y), 1e-6) if fighting_weights else 1.0
                        combined = hp_weight * fight_weight
                        moves.append((m, combined))

        # Add pass move if it has positive probability and is acceptable
        if len(human_policy) > board_size[0] * board_size[1] and human_policy[-1] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[-1]))

        self.game.katrain.log(
            f"[FightingStrategy:human] {len(moves)} candidate moves ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )

        # 安全弁v2: 最高重み候補のlossが閾値以上なら最善スコア手を確定選択
        # 安全弁v1はmove_infosの最多探索手を対象とするが、実際に選ばれる手は
        # humanPolicy×fighting_weightで決まるため、v2でその手を直接チェックする
        if moves and move_infos and best_gtp_by_score:
            _score_by_gtp_v2 = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
            top_move_v2, _ = max(moves, key=lambda x: x[1])
            top_gtp_v2 = top_move_v2.gtp()
            if top_gtp_v2 in _score_by_gtp_v2 and top_gtp_v2 != best_gtp_by_score:
                top_loss_v2 = player_sign * (best_score - _score_by_gtp_v2[top_gtp_v2])
                self.game.katrain.log(
                    f"[FightingStrategy:human] Safety v2: top weighted move {top_gtp_v2} loss={top_loss_v2:.2f}",
                    OUTPUT_DEBUG,
                )
                if top_loss_v2 >= _SAFETY_LOSS_THRESHOLD:
                    if _safety_valve_cross_check(best_gtp_by_score, top_gtp_v2, player_sign, "v2"):
                        self.game.katrain.log(
                            f"[FightingStrategy:human] Safety valve v2: top weighted {top_gtp_v2} "
                            f"loss={top_loss_v2:.2f} >= {_SAFETY_LOSS_THRESHOLD}, "
                            f"forcing best-score move {best_gtp_by_score}",
                            OUTPUT_DEBUG,
                        )
                        if best_gtp_by_score == "pass":
                            return Move(None, player=self.cn.next_player), "Safety valve v2: best move is pass."
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                            f"Safety valve v2: top weighted {top_gtp_v2} had loss={top_loss_v2:.2f}, "
                            f"forced best-score move {best_gtp_by_score}."
                        )

        # 全手フィルタ時のフォールバック
        if not moves:
            self.game.katrain.log(f"[FightingStrategy:human] All moves filtered, using best search move", OUTPUT_DEBUG)
            if move_infos:
                if (bx == 9 and by == 9 or bx == 13 and by == 13) and best_gtp_by_score:
                    best_gtp = best_gtp_by_score
                else:
                    best_gtp = move_infos[0].get("move", "pass")
                if best_gtp == "pass":
                    return Move(None, player=self.cn.next_player), "All human moves filtered, playing best move."
                else:
                    coords = Move.from_gtp(best_gtp, player=self.cn.next_player)
                    return coords, "All human moves filtered, playing best move."
            return Move(None, player=self.cn.next_player), "No valid moves found."

        # パスが候補にあれば強制パス
        if any(m.is_pass for m, _ in moves):
            self.game.katrain.log(f"[FightingStrategy:human] Pass is among candidates, forcing pass", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "Pass is in candidates, forcing pass."

        # 終局時: humanPolicy最上位手（力戦重み無視）
        endgame_threshold = 32 if (bx == 9 and by == 9) else math.ceil(bx * by * 0.5)
        if current_move >= endgame_threshold:
            # 終局は力戦重みなしのhumanPolicyで選択
            endgame_moves = []
            for x in range(board_size[0]):
                for y in range(board_size[1]):
                    idx = (board_size[1] - y - 1) * board_size[0] + x
                    if idx < len(human_policy) and human_policy[idx] > 0:
                        m = Move((x, y), player=self.cn.next_player)
                        if not has_filter or m.gtp() in good_moves:
                            endgame_moves.append((m, human_policy[idx]))
            if endgame_moves:
                top_move = max(endgame_moves, key=lambda x: x[1])
                self.game.katrain.log(
                    f"[FightingStrategy:human] Endgame: playing top humanPolicy move {top_move[0].gtp()}",
                    OUTPUT_DEBUG,
                )
                return top_move[0], f"Endgame: played top humanPolicy move {top_move[0].gtp()}."

        # デバッグ: 上位5手表示
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
        top_str = "\n".join([f"#{i+1}: {m.gtp()} weight={w:.4f}" for i, (m, w) in enumerate(top5)])
        self.game.katrain.log(f"[FightingStrategy:human] Top 5:\n{top_str}", OUTPUT_DEBUG)

        # 拮抗タイブレーク: 以下いずれかで発動 → スコア差2目以上なら高スコア手を確定選択
        # 1. humanPolicy比が5%以内（humanPolicy拮抗）
        # 2. Stage2 visitsがtop2 > top1 × 2.0（visits逆転: MCTSがhumanPolicy2位を実際には1位と判断）
        # 3. top2 visits ≥ top1 visits（visits同数・MCTSがtop1を優遇していない）
        _TIEBREAK_WEIGHT_RATIO = 1.05
        _TIEBREAK_VISITS_REVERSAL_RATIO = 2.0
        _TIEBREAK_SCORE_DIFF = 2.0
        if len(top5) >= 2 and move_infos:
            _player_sign = 1 if self.cn.next_player == "B" else -1
            _score_by_gtp = {mi.get("move", ""): mi.get("scoreLead", 0) * _player_sign for mi in move_infos}
            _visits_by_gtp = {mi.get("move", ""): mi.get("visits", 0) for mi in move_infos}
            top1_move, top1_w = top5[0]
            top2_move, top2_w = top5[1]
            top1_visits = _visits_by_gtp.get(top1_move.gtp(), 0)
            top2_visits = _visits_by_gtp.get(top2_move.gtp(), 0)
            is_policy_close = top2_w > 0 and top1_w / top2_w < _TIEBREAK_WEIGHT_RATIO
            is_visits_reversal = top2_visits > top1_visits * _TIEBREAK_VISITS_REVERSAL_RATIO
            is_mcts_nonprefer = top1_visits > 0 and top2_visits >= top1_visits
            if is_policy_close or is_visits_reversal or is_mcts_nonprefer:
                s1 = _score_by_gtp.get(top1_move.gtp())
                s2 = _score_by_gtp.get(top2_move.gtp())
                if s1 is not None and s2 is not None and abs(s1 - s2) >= _TIEBREAK_SCORE_DIFF:
                    winner = top1_move if s1 > s2 else top2_move
                    loser = top2_move if s1 > s2 else top1_move
                    trigger = "policy" if is_policy_close else ("visits_reversal" if is_visits_reversal else "mcts_nonprefer")
                    self.game.katrain.log(
                        f"[FightingStrategy:human] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt, "
                        f"policy_ratio={top1_w/top2_w:.3f}, visits={top1_visits}/{top2_visits})",
                        OUTPUT_DEBUG,
                    )
                    return winner, (
                        f"\n{top_str}\n\nScore tiebreak({trigger}): played {winner.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt). ({filtered_count} filtered)"
                    )

        # 重み付き選択
        selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]
        self.game.katrain.log(f"[FightingStrategy:human] Selected: {move.gtp()}", OUTPUT_DEBUG)

        ai_thoughts = (
            f"\n{top_str}\n\nHuman+Fighting: played {move.gtp()} "
            f"({filtered_count} bad moves filtered)"
        )
        return move, ai_thoughts

    def generate_weighted_coords(self, legal_policy_moves, policy_grid, size):
        self.game.katrain.log(f"[FightingStrategy] Generating fighting-based weights", OUTPUT_DEBUG)
        weighted_coords, ai_thoughts = generate_fighting_weights(
            self.settings, policy_grid, self.game, self.cn, size
        )
        self.game.katrain.log(
            f"[FightingStrategy] Generated {len(weighted_coords)} weighted coordinates",
            OUTPUT_DEBUG,
        )
        if weighted_coords:
            top5 = heapq.nlargest(5, weighted_coords, key=lambda t: t[0] * t[1])
            self.game.katrain.log(f"[FightingStrategy] Top 5 weighted coordinates (by policy*weight):", OUTPUT_DEBUG)
            for i, (pol, wt, x, y) in enumerate(top5):
                self.game.katrain.log(
                    f"[FightingStrategy] #{i+1}: ({x},{y}) - policy={pol:.2%}, weight={wt:.4f}, combined={pol*wt:.4f}",
                    OUTPUT_DEBUG,
                )
        return weighted_coords, ai_thoughts

def _get_corner_star_points(board_size):
    """盤面サイズに応じた隅の星点（4-4点相当）の集合を返す"""
    bx, by = board_size
    near_x = 3 if bx >= 13 else min(2, bx - 1)
    near_y = 3 if by >= 13 else min(2, by - 1)
    far_x = bx - 1 - near_x
    far_y = by - 1 - near_y
    return {(near_x, near_y), (far_x, near_y), (near_x, far_y), (far_x, far_y)}


def _diagonal_star(corner, corner_stars):
    """4隅星点の中から、指定した隅の対角線上にある星点を返す（両座標が異なる点）"""
    for c in corner_stars:
        if c[0] != corner[0] and c[1] != corner[1]:
            return c
    return None


@register_strategy(AI_HUMAN)
@register_strategy(AI_PRO)
class HumanStyleStrategy(AIStrategy):
    """Strategy that imitates human play at various skill levels"""
    
    def __init__(self, game: Game, ai_settings: Dict):
        super().__init__(game, ai_settings)
        self.game.katrain.log(f"[HumanStyleStrategy] Initializing HumanStyleStrategy", OUTPUT_DEBUG)
        self.game.katrain.log(f"[HumanStyleStrategy] AI settings: {ai_settings}", OUTPUT_DEBUG)
        
    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[HumanStyleStrategy] Starting move generation", OUTPUT_DEBUG)
        
        if "human_kyu_rank" in self.settings:
            human_kyu_rank = round(self.settings["human_kyu_rank"])
            human_style = "rank" if self.settings["modern_style"] else "preaz"

            if human_kyu_rank <= 0:  # dan ranks
                rank_text = f"{1-human_kyu_rank}d"
            else:  # kyu ranks
                rank_text = f"{human_kyu_rank}k"

            human_profile = f"{human_style}_{rank_text}"
        else:
            pro_year = round(self.settings["pro_year"])
            human_profile = f"proyear_{pro_year}"
        
        self.game.katrain.log(f"[HumanStyleStrategy] Human profile string: {human_profile}", OUTPUT_DEBUG)
        
        # Define override settings (separate from includePolicy)
        # maxVisits should match analysis setting (800) for consistent score evaluation
        override_settings = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 800,
        }
        self.game.katrain.log(f"[HumanStyleStrategy] Override settings for engine: {override_settings}", OUTPUT_DEBUG)
        
        # Request analysis from engine - note includePolicy is a direct parameter
        analysis = None
        
        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                self.game.katrain.log(f"[HumanStyleStrategy] Full analysis results received", OUTPUT_DEBUG)
                analysis = a
                # Log some analysis stats for debugging
                if a:
                    self.game.katrain.log(f"[HumanStyleStrategy] Analysis contains humanPolicy: {'humanPolicy' in a}", OUTPUT_DEBUG)
                    self.game.katrain.log(f"[HumanStyleStrategy] Analysis contains moveInfos: {len(a.get('moveInfos', []))} moves", OUTPUT_DEBUG)
                    if 'humanPolicy' in a:
                        policy_sum = sum(a['humanPolicy'])
                        policy_max = max(a['humanPolicy'])
                        self.game.katrain.log(f"[HumanStyleStrategy] Human policy sum: {policy_sum}, max: {policy_max}", OUTPUT_DEBUG)
            else:
                self.game.katrain.log(f"[HumanStyleStrategy] Received partial analysis results - ignoring", OUTPUT_DEBUG)

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[HumanStyleStrategy] Error in human analysis query: {a}", OUTPUT_ERROR)
            self.game.katrain.log(f"[HumanStyleStrategy] Will attempt to fall back to policy move", OUTPUT_DEBUG)
            
        error = False
        self.game.katrain.log(f"[HumanStyleStrategy] Getting engine for player", OUTPUT_DEBUG)
        engine = self.game.engines[self.cn.player]
        self.game.katrain.log(f"[HumanStyleStrategy] Using engine for player {self.cn.player}", OUTPUT_DEBUG)
        
        self.game.katrain.log(f"[HumanStyleStrategy] Requesting analysis with human profile settings", OUTPUT_DEBUG)
        engine.request_analysis(
            self.cn,
            callback=set_analysis,
            error_callback=set_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=True,
            extra_settings=override_settings
        )
        self.game.katrain.log(f"[HumanStyleStrategy] Analysis request sent, waiting for results", OUTPUT_DEBUG)
        
        # Wait for analysis to complete
        wait_count = 0
        while not (error or analysis):
            import time
            time.sleep(0.01)
            wait_count += 1
            if wait_count % 100 == 0:  # Log every 1 second
                self.game.katrain.log(f"[HumanStyleStrategy] Still waiting for analysis results ({wait_count/100:.1f}s)", OUTPUT_DEBUG)
            engine.check_alive(exception_if_dead=True)
        
        self.game.katrain.log(f"[HumanStyleStrategy] Finished waiting for analysis, error={error}, analysis received={analysis is not None}", OUTPUT_DEBUG)
            
        if error or not analysis:
            self.game.katrain.log(f"[HumanStyleStrategy] Analysis failed or returned empty", OUTPUT_DEBUG)
            # Fall back to policy
            policy_move = self.cn.policy_ranking[0][1] if self.cn.policy_ranking else None
            if policy_move:
                self.game.katrain.log(f"[HumanStyleStrategy] Falling back to top policy move: {policy_move.gtp()}", OUTPUT_DEBUG)
                return policy_move, "Falling back to policy move due to error in human analysis."
            else:
                self.game.katrain.log(f"[HumanStyleStrategy] No policy moves available for fallback - will return pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "No valid moves found."
        
        # Check if human policy is available
        self.game.katrain.log(f"[HumanStyleStrategy] Processing analysis results", OUTPUT_DEBUG)
        if "humanPolicy" not in analysis:
            error_msg = "humanPolicy not found in analysis—have you downloaded and configured your human model yet?"
            raise Exception(error_msg)

        self.game.katrain.log(f"[HumanStyleStrategy] Human policy found in analysis", OUTPUT_DEBUG)
        board_size = self.game.board_size
        human_policy = analysis["humanPolicy"]

        # --- Stage 2: Unbiased score query (no humanSLProfile) ---
        # humanSLProfile付きクエリのscoreLeadはバイアスされるため、
        # 正確なスコアでフィルタリングするためにクリーンクエリを送信
        clean_override_settings = {
            "ignorePreRootHistory": False,
            "maxVisits": 600,
            "wideRootNoise": 0.0,
        }

        clean_analysis = None
        clean_error = False

        def set_clean_analysis(a, partial_result):
            nonlocal clean_analysis
            if not partial_result:
                self.game.katrain.log(f"[HumanStyleStrategy] Clean analysis results received", OUTPUT_DEBUG)
                clean_analysis = a

        def set_clean_error(a):
            nonlocal clean_error
            clean_error = True
            self.game.katrain.log(f"[HumanStyleStrategy] Error in clean analysis query: {a}", OUTPUT_ERROR)

        self.game.katrain.log(f"[HumanStyleStrategy] Requesting clean analysis (no humanSLProfile)", OUTPUT_DEBUG)
        engine.request_analysis(
            self.cn,
            callback=set_clean_analysis,
            error_callback=set_clean_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=False,
            extra_settings=clean_override_settings
        )

        wait_count = 0
        while not (clean_error or clean_analysis):
            import time
            time.sleep(0.01)
            wait_count += 1
            if wait_count % 100 == 0:
                self.game.katrain.log(
                    f"[HumanStyleStrategy] Waiting for clean analysis ({wait_count/100:.1f}s)",
                    OUTPUT_DEBUG
                )
            engine.check_alive(exception_if_dead=True)

        # Build set of acceptable moves using moveInfos from KataGo search
        # Phase-based threshold: stricter in opening to avoid large blunders early
        # Opening boundary matches the game report definition (depth < 0.14 * board_squares)
        bx, by = self.game.board_size
        opening_boundary = math.ceil(0.14 * bx * by)  # e.g. 51 for 19x19, 24 for 13x13, 12 for 9x9
        if bx == 9 and by == 9:
            OPENING_THRESHOLD = 0.5   # 9路盤序盤: 0.5目以上の損失手は打たない
            NORMAL_THRESHOLD = 3.3    # 9路盤中盤・終盤: 3.3目以上の損失手は打たない
        else:
            OPENING_THRESHOLD = 2.8   # Stricter threshold in opening (3pt loss max)
            NORMAL_THRESHOLD = 5.6    # Normal threshold for mid/endgame
        current_move = self.cn.depth  # Move number (both players combined)
        BAD_MOVE_THRESHOLD = OPENING_THRESHOLD if current_move < opening_boundary else NORMAL_THRESHOLD
        # クリーンクエリのmoveInfosを優先使用（正確なスコア）、失敗時はバイアス付きにフォールバック
        if clean_analysis and not clean_error:
            move_infos = clean_analysis.get("moveInfos", [])
            self.game.katrain.log(
                f"[HumanStyleStrategy] Using CLEAN moveInfos ({len(move_infos)} moves) for score filter",
                OUTPUT_DEBUG
            )
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log(
                f"[HumanStyleStrategy] Clean query failed, falling back to biased moveInfos ({len(move_infos)} moves)",
                OUTPUT_DEBUG
            )
        good_moves = set()  # Only moves evaluated by KataGo and within threshold
        best_gtp_by_score = None  # 大差フィルター用（現在プレイヤーにとっての最善手GTP）
        if move_infos:
            # player_sign: Black=+1, White=-1 (scoreLead is always from Black's perspective)
            player_sign = 1 if self.cn.next_player == "B" else -1
            # Use the best scoreLead for the current player (max for Black, min for White)
            best_score = max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
            # 大差フィルター用: 現在プレイヤーにとっての最善手GTEを記録
            best_gtp_by_score = max(
                move_infos, key=lambda mi: mi.get("scoreLead", 0) * player_sign
            ).get("move", "")
            # 最善手がパスの場合は強制的にパス（9段がパスタイミングを間違えることはない）
            if best_gtp_by_score == "pass":
                self.game.katrain.log(f"[HumanStyleStrategy] Best move is pass, forcing pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."
            self.game.katrain.log(f"[HumanStyleStrategy] Move {current_move}: phase={'opening' if current_move < opening_boundary else 'normal'}, threshold={BAD_MOVE_THRESHOLD} (boundary={opening_boundary})", OUTPUT_DEBUG)
            self.game.katrain.log(f"[HumanStyleStrategy] Best move score: {best_score:.1f} (player={self.cn.next_player}), filtering moves losing {BAD_MOVE_THRESHOLD}+ pts", OUTPUT_DEBUG)
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)  # Correct sign for both Black and White
                if loss < BAD_MOVE_THRESHOLD:
                    good_moves.add(gtp_move)
            self.game.katrain.log(f"[HumanStyleStrategy] {len(good_moves)} moves pass score filter out of {len(move_infos)} searched", OUTPUT_DEBUG)

        # Create a list of moves with their human policy weights
        # Only include moves that KataGo evaluated as acceptable (in good_moves)
        moves = []
        filtered_count = 0
        has_filter = len(good_moves) > 0
        for x in range(board_size[0]):
            for y in range(board_size[1]):
                idx = (board_size[1] - y - 1) * board_size[0] + x
                if idx < len(human_policy) and human_policy[idx] > 0:
                    m = Move((x, y), player=self.cn.next_player)
                    if has_filter and m.gtp() not in good_moves:
                        filtered_count += 1
                    else:
                        moves.append((m, human_policy[idx]))

        # Add pass move if it has positive probability and is acceptable
        if len(human_policy) > board_size[0] * board_size[1] and human_policy[-1] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[-1]))

        self.game.katrain.log(f"[HumanStyleStrategy] {len(moves)} candidate moves ({filtered_count} filtered out)", OUTPUT_DEBUG)

        # If all moves were filtered, fall back to the best move from search
        if not moves:
            self.game.katrain.log(f"[HumanStyleStrategy] All human moves filtered, using best search move", OUTPUT_DEBUG)
            if move_infos:
                # 9路・13路盤: best_gtp_by_score（スコア最善手）を優先
                # humanSLProfileの影響で最多探索手≠スコア最善手になる場合があるため
                # 19路盤: move_infos[0]（最多探索手）のままとする（デフォルト動作を維持）
                if (bx == 9 and by == 9 or bx == 13 and by == 13) and best_gtp_by_score:
                    best_gtp = best_gtp_by_score
                else:
                    best_gtp = move_infos[0].get("move", "pass")
                if best_gtp == "pass":
                    return Move(None, player=self.cn.next_player), "All human moves filtered, playing best move."
                else:
                    coords = Move.from_gtp(best_gtp, player=self.cn.next_player)
                    return coords, "All human moves filtered, playing best move."
            return Move(None, player=self.cn.next_player), "No valid moves found."

        # 2連星（序盤星打ち強制）フィルタ
        if self.settings.get("force_star_opening", False) and moves:
            corner_stars = _get_corner_star_points(board_size)
            stones_by_pos = {m.coords: m.player for m in self.game.stones}
            ai_player = self.cn.next_player
            opponent_player = "W" if ai_player == "B" else "B"

            ai_stars_played = [c for c in corner_stars if stones_by_pos.get(c) == ai_player]
            opp_stars_played = [c for c in corner_stars if stones_by_pos.get(c) == opponent_player]
            empty_stars = {c for c in corner_stars if c not in stones_by_pos}

            target_stars = set()

            if len(ai_stars_played) == 0 and empty_stars:
                if opp_stars_played:
                    # 相手が星を打っていたら対角線上に打つ（白番の対角戦略）
                    diag = _diagonal_star(opp_stars_played[0], corner_stars)
                    target_stars = {diag} if diag and diag in empty_stars else empty_stars
                else:
                    # 相手がまだ星に打っていない（黒番の1手目等）→ 任意の隅
                    target_stars = empty_stars
            elif len(ai_stars_played) == 1 and empty_stars:
                # 自分の1手目と同じ辺の星点に限定（2連星を完成させる）
                first = ai_stars_played[0]
                same_side = {c for c in corner_stars if c[0] == first[0] or c[1] == first[1]} - {first}
                target_stars = same_side & empty_stars
            # len(ai_stars_played) >= 2 → 強制しない（target_stars = {} のまま）

            if target_stars:
                # まず既存のmovesの中から星点候補を探す
                star_moves = [(m, w) for m, w in moves if m.coords in target_stars]
                if not star_moves:
                    # humanPolicyが0またはフィルタで除外されていた場合、直接Moveを生成して強制
                    for (sx, sy) in target_stars:
                        if 0 <= sx < board_size[0] and 0 <= sy < board_size[1]:
                            if self.game.board[sy][sx] == -1:  # 空きマスのみ
                                idx = (board_size[1] - sy - 1) * board_size[0] + sx
                                weight = human_policy[idx] if idx < len(human_policy) and human_policy[idx] > 0 else 1.0
                                star_moves.append((Move((sx, sy), player=self.cn.next_player), weight))
                if star_moves:
                    moves = star_moves
                    self.game.katrain.log(
                        f"[HumanStyleStrategy] force_star_opening: ai_stars={len(ai_stars_played)}, "
                        f"opp_stars={len(opp_stars_played)}, "
                        f"targets={[f'({c[0]},{c[1]})' for c in target_stars]}",
                        OUTPUT_DEBUG,
                    )

        # 終局閾値（big-win フィルター内の relax 判定にも使用）
        endgame_threshold = 32 if (bx == 9 and by == 9) else math.ceil(bx * by * 0.5)

        # passが候補手に含まれていたら強制的にパス
        # （passが候補に上がった＝他の手を打つと損するため）
        if any(m.is_pass for m, _ in moves):
            self.game.katrain.log(f"[HumanStyleStrategy] Pass is among candidates, forcing pass", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "Pass is in candidates, forcing pass."

        # 終局時はhumanPolicy最上位手を選択（9段はヨセを間違えない）
        if current_move >= endgame_threshold:
            top_moves_sorted = sorted(moves, key=lambda x: -x[1])
            top_moves_str = "\n".join([f"#{i+1}: {m.gtp()} - {p:.1%}" for i, (m, p) in enumerate(top_moves_sorted[:5])])
            self.game.katrain.log(f"[HumanStyleStrategy] Endgame (move {current_move} >= {endgame_threshold}): playing top humanPolicy move", OUTPUT_DEBUG)
            self.game.katrain.log(f"[HumanStyleStrategy] Top 5 moves:\n{top_moves_str}", OUTPUT_DEBUG)
            move = top_moves_sorted[0][0]
            prob = top_moves_sorted[0][1]
            ai_thoughts = f"\n{top_moves_str}\n\nEndgame: played top move {move.gtp()} ({prob:.1%}). ({filtered_count} bad moves filtered)"
            return move, ai_thoughts

        top_moves = sorted(moves, key=lambda x: -x[1])
        top_moves_str = "\n".join([f"#{i+1}: {move.gtp()} - {prob:.1%}" for i, (move, prob) in enumerate(top_moves[:5])])
        self.game.katrain.log(f"[HumanStyleStrategy] Top 5 moves:\n{top_moves_str}", OUTPUT_DEBUG)

        # 拮抗タイブレーク用スコア・訪問数マップ（現プレイヤー視点・Stage2クリーン値）
        score_by_gtp = {}
        visits_by_gtp = {}
        if move_infos:
            for mi in move_infos:
                gtp = mi.get("move", "")
                score_by_gtp[gtp] = mi.get("scoreLead", 0) * player_sign
                visits_by_gtp[gtp] = mi.get("visits", 0)

        # First-impression deviation（全盤面）:
        # 第一感上位3位で損失0.5〜上限目の手を確定選択
        # 損失上限: 9路=1.5目、13路・19路=2.0目
        if (self.settings.get("first_impression_deviation", False)
                and (self.settings.get("first_impression_deviation_opening", False) or current_move >= opening_boundary)
                and top_moves and move_infos):
            loss_by_gtp = {}
            for mi in move_infos:
                score = mi.get("scoreLead", 0)
                loss_by_gtp[mi.get("move", "")] = player_sign * (best_score - score)

            dev_loss_max = 1.5 if (bx == 9 and by == 9) else 2.0
            deviation_candidates = []
            for m, w in top_moves[:3]:
                loss = loss_by_gtp.get(m.gtp(), 0.0)
                if 0.5 <= loss < dev_loss_max:
                    deviation_candidates.append((m, loss))

            # green_blend: 第一感1位が緑(0<loss<0.5)かつ非最善 → green_ratioで緑手or偏差手
            if (self.settings.get("first_impression_green_blend", False)
                    and deviation_candidates and top_moves):
                top1_move, top1_w = top_moves[0]
                top1_loss = loss_by_gtp.get(top1_move.gtp(), 0.0)
                if 0 < top1_loss < 0.5:
                    best_dev = min(deviation_candidates, key=lambda x: x[1])
                    green_ratio = self.settings.get("green_blend_green_ratio", 0.5)
                    if random.random() < green_ratio:
                        chosen_move, chosen_loss = top1_move, top1_loss
                        blend_label = "green"
                    else:
                        chosen_move, chosen_loss = best_dev
                        blend_label = "dev"
                    self.game.katrain.log(
                        f"[HumanStyleStrategy] First-impression green-blend({blend_label}): "
                        f"{chosen_move.gtp()} (loss={chosen_loss:.1f})",
                        OUTPUT_DEBUG
                    )
                    ai_thoughts = (
                        f"\n{top_moves_str}\n\nFirst-impression green-blend({blend_label}): "
                        f"played {chosen_move.gtp()} (loss={chosen_loss:.1f}). "
                        f"({filtered_count} bad moves filtered)"
                    )
                    return chosen_move, ai_thoughts

            if deviation_candidates:
                best_dev = min(deviation_candidates, key=lambda x: x[1])
                self.game.katrain.log(
                    f"[HumanStyleStrategy] First-impression deviation: {best_dev[0].gtp()} "
                    f"(loss={best_dev[1]:.1f})",
                    OUTPUT_DEBUG
                )
                ai_thoughts = (
                    f"\n{top_moves_str}\n\nFirst-impression deviation: played {best_dev[0].gtp()} "
                    f"(loss={best_dev[1]:.1f}). ({filtered_count} bad moves filtered)"
                )
                return best_dev[0], ai_thoughts

        # 拮抗タイブレーク: 以下いずれかで発動 → スコア差2目以上なら高スコア手を確定選択
        # 1. humanPolicy比が5%以内（humanPolicy拮抗）
        # 2. Stage2 visitsがtop2 > top1 × 2.0（visits逆転: MCTSがhumanPolicy2位を実際には1位と判断）
        # 3. top2 visits ≥ top1 visits（visits同数・MCTSがtop1を優遇していない）
        _TIEBREAK_WEIGHT_RATIO = 1.05
        _TIEBREAK_VISITS_REVERSAL_RATIO = 2.0
        _TIEBREAK_SCORE_DIFF = 2.0
        if len(top_moves) >= 2 and score_by_gtp:
            top1_move, top1_w = top_moves[0]
            top2_move, top2_w = top_moves[1]
            top1_visits = visits_by_gtp.get(top1_move.gtp(), 0)
            top2_visits = visits_by_gtp.get(top2_move.gtp(), 0)
            is_policy_close = top2_w > 0 and top1_w / top2_w < _TIEBREAK_WEIGHT_RATIO
            is_visits_reversal = top2_visits > top1_visits * _TIEBREAK_VISITS_REVERSAL_RATIO
            is_mcts_nonprefer = top1_visits > 0 and top2_visits >= top1_visits
            if is_policy_close or is_visits_reversal or is_mcts_nonprefer:
                s1 = score_by_gtp.get(top1_move.gtp())
                s2 = score_by_gtp.get(top2_move.gtp())
                if s1 is not None and s2 is not None and abs(s1 - s2) >= _TIEBREAK_SCORE_DIFF:
                    winner = top1_move if s1 > s2 else top2_move
                    loser = top2_move if s1 > s2 else top1_move
                    trigger = "policy" if is_policy_close else ("visits_reversal" if is_visits_reversal else "mcts_nonprefer")
                    self.game.katrain.log(
                        f"[HumanStyleStrategy] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt, "
                        f"policy_ratio={top1_w/top2_w:.3f}, visits={top1_visits}/{top2_visits})",
                        OUTPUT_DEBUG,
                    )
                    ai_thoughts = (
                        f"\n{top_moves_str}\n\nScore tiebreak({trigger}): played {winner.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt). ({filtered_count} bad moves filtered)"
                    )
                    return winner, ai_thoughts

        selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]
        prob = selected[1]

        selected_rank = next((i+1 for i, (m, _) in enumerate(top_moves) if m.gtp() == move.gtp()), "?")

        self.game.katrain.log(f"[HumanStyleStrategy] Selected move {move.gtp()} (prob={prob:.4f})", OUTPUT_DEBUG)
        ai_thoughts = f"\n{top_moves_str}\n\nPlayed move {move.gtp()} ({prob:.1%}) as the #{selected_rank} top move. ({filtered_count} bad moves filtered)"
        return move, ai_thoughts

def generate_ai_move(game: Game, ai_mode: str, ai_settings: Dict) -> Tuple[Move, GameNode]:
    """Generate a move using the selected AI strategy"""
    game.katrain.log(f"Generate AI move called with mode: {ai_mode}", OUTPUT_DEBUG)
    
    # Create the appropriate strategy based on mode

    strategy = STRATEGY_REGISTRY[ai_mode](game, ai_settings)
    
    # Generate the move
    game.katrain.log(f"Generating move using {strategy.__class__.__name__}", OUTPUT_DEBUG)
    move, ai_thoughts = strategy.generate_move()
    
    # Play the move and return
    game.katrain.log(f"Playing move {move.gtp()} and creating game node", OUTPUT_DEBUG)
    played_node = game.play(move)
    game.katrain.log(f"AI thoughts: {ai_thoughts}", OUTPUT_DEBUG)
    played_node.ai_thoughts = ai_thoughts
    
    game.katrain.log(f"Move generation complete: {move.gtp()}", OUTPUT_DEBUG)
    return move, played_node