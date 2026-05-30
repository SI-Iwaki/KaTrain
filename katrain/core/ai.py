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
    OUTPUT_ERROR, OUTPUT_INFO, PRIORITY_EXTRA_AI_QUERY, ADDITIONAL_MOVE_ORDER, AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE
)
from katrain.core.engine import KataGoEngine
from katrain.core.game import Game, GameNode, Move
from katrain.core.utils import var_to_grid, weighted_selection_without_replacement, evaluation_class

# Decorator pattern for adding classes to the registry
STRATEGY_REGISTRY = {}

def register_strategy(strategy_name):
    def decorator(strategy_class):
        STRATEGY_REGISTRY[strategy_name] = strategy_class
        return strategy_class
    return decorator


# --- Hunt Dead Stone Avoidance 定数 ---
_DEAD_OWNERSHIP_THRESHOLD = 0.85  # |ownership * player_sign| > 0.85 で死と判定
_DEAD_LOSS_MIN = 0.5              # loss > 0.5 でなければ対象外
_DEAD_WEIGHT_FACTOR = 0.05        # 検出時のweight減衰係数


def is_dead_zone_move(move_coords, ownership_grid, own_stone_coords, player_sign, loss, board_size):
    """候補手が『死んだ自石の周辺の無駄手』かを判定する。

    Args:
        move_coords: (x, y) タプル、またはパスの場合 None
        ownership_grid: 2次元配列 [y][x] → [-1, +1] の KataGo ownership
        own_stone_coords: 現プレイヤー自石の座標 set {(x, y), ...}
        player_sign: +1 (Black) or -1 (White)
        loss: 候補手の損失（目数、正=損）
        board_size: (bx, by) タプル

    Returns:
        bool: True なら減衰対象
    """
    if move_coords is None:
        return False
    if loss <= _DEAD_LOSS_MIN:
        return False

    x, y = move_coords
    bx, by = board_size

    # 条件(A): 候補点自体が強く相手地
    own_xy = ownership_grid[y][x] * player_sign
    if own_xy < -_DEAD_OWNERSHIP_THRESHOLD:
        return True

    # 条件(B): 4近傍に死んだ自石
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nx, ny = x + dx, y + dy
        if not (0 <= nx < bx and 0 <= ny < by):
            continue
        if (nx, ny) not in own_stone_coords:
            continue
        own_neighbor = ownership_grid[ny][nx] * player_sign
        if own_neighbor < -_DEAD_OWNERSHIP_THRESHOLD:
            return True

    return False


def find_connected_groups(stones: set) -> list:
    """石の座標集合を連結グループに分類する。上下左右の隣接で接続判定。

    Args:
        stones: {(x, y), ...} 形式の座標集合
    Returns:
        [set((x,y), ...), ...] 形式のグループリスト
    """
    remaining = set(stones)
    groups = []
    while remaining:
        start = next(iter(remaining))
        group = set()
        queue = [start]
        while queue:
            coord = queue.pop()
            if coord in remaining:
                remaining.discard(coord)
                group.add(coord)
                x, y = coord
                for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                    neighbor = (x + dx, y + dy)
                    if neighbor in remaining:
                        queue.append(neighbor)
        groups.append(group)
    return groups


def count_group_liberties(board, group_coords, board_size):
    """石群のリバティ数（呼吸点＝隣接する空点の数）を算出する。

    Args:
        board: 2D list [y][x] of chain IDs (-1 = empty)
        group_coords: set of (x, y) coordinates of the group
        board_size: (width, height)
    Returns:
        int: number of unique liberties
    """
    bx, by = board_size
    liberties = set()
    for x, y in group_coords:
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < bx and 0 <= ny < by and board[ny][nx] == -1:
                liberties.add((nx, ny))
    return len(liberties)


def evaluate_pursuit_targets(
    previous_targets,
    opponent_move_coords,
    current_opponent_coords,
    board,
    board_size,
    ownership_grid,
    player_sign,
    pursue_proximity,
    pursue_min_liberties,
    pursue_ownership_threshold,
):
    """前手番のターゲットに対して追撃すべきかを判定する。

    Args:
        previous_targets: list of dicts with "coords" (list of (x,y)) and "size" (int)
        opponent_move_coords: (x, y) of opponent's last move, or None
        current_opponent_coords: set of (x, y) of current opponent stones on board
        board: 2D list [y][x] of chain IDs (-1 = empty)
        board_size: (width, height)
        ownership_grid: 2D list [y][x] of ownership values, or None
        player_sign: 1 for Black, -1 for White
        pursue_proximity: max Chebyshev distance for "near target" detection
        pursue_min_liberties: liberty count threshold for unconditional pursuit
        pursue_ownership_threshold: base ownership threshold for pursuit decision
    Returns:
        list of (target_score, instability, group_coords_set) to inject into targets
    """
    if not previous_targets or opponent_move_coords is None:
        return []

    pursuit_targets = []
    ox, oy = opponent_move_coords

    for prev_target in previous_targets:
        prev_coords = set(tuple(c) for c in prev_target["coords"])
        prev_size = prev_target["size"]

        # Check proximity: is opponent's move near this previous target?
        min_dist = min(
            max(abs(ox - cx), abs(oy - cy))  # Chebyshev distance
            for cx, cy in prev_coords
        )
        if min_dist > pursue_proximity:
            continue

        # Step 1: Are stones still on the board?
        surviving_coords = prev_coords & current_opponent_coords
        if not surviving_coords:
            continue

        # Re-group surviving stones (some may have been captured)
        groups = find_connected_groups(surviving_coords)
        for group in groups:
            group_size = len(group)

            # Step 2: Liberty check
            liberties = count_group_liberties(board, group, board_size)
            if liberties >= pursue_min_liberties:
                # Unconditional pursuit
                instability = max(0.2, min(1.0, liberties * 0.1))
                target_score = group_size * instability
                pursuit_targets.append((target_score, instability, group))
                continue

            # Step 3: Ownership check
            if ownership_grid is not None:
                total_ownership = sum(ownership_grid[y][x] for x, y in group)
                avg_ownership = total_ownership / group_size
                abs_ownership = abs(avg_ownership)

                # Adjust threshold by group size
                threshold = pursue_ownership_threshold
                if group_size >= 15:
                    threshold += 0.10
                elif group_size >= 10:
                    threshold += 0.05

                if abs_ownership < threshold:
                    # Ownership not confirmed enough — pursue
                    instability = max(0.2, 1.0 - abs_ownership)
                    target_score = group_size * instability
                    pursuit_targets.append((target_score, instability, group))

    return pursuit_targets


def find_targets(game, cn, min_group_size, instability_min):
    """ターゲットとなる不安定な相手石群を特定する（共有関数）。

    Args:
        game: Game オブジェクト（stones, board_size, katrain.log にアクセス）
        cn: GameNode オブジェクト（ownership, next_player にアクセス）
        min_group_size: ターゲットとする最小グループサイズ
        instability_min: ターゲット判定の最小不安定度
    Returns:
        [(target_score, instability, group_coords_set), ...] スコア降順
    """
    board_size = game.board_size
    ownership = cn.ownership
    if not ownership:
        game.katrain.log("[find_targets] No ownership data available", OUTPUT_DEBUG)
        return []

    ownership_grid = var_to_grid(ownership, board_size)

    opponent_coords = set()
    for s in game.stones:
        if s.player != cn.next_player and s.coords:
            opponent_coords.add(s.coords)

    if not opponent_coords:
        return []

    groups = find_connected_groups(opponent_coords)

    targets = []
    for group in groups:
        if len(group) < min_group_size:
            continue

        total_ownership = 0.0
        for x, y in group:
            total_ownership += ownership_grid[y][x]
        avg_ownership = total_ownership / len(group)

        instability = 1.0 - abs(avg_ownership)
        if instability < instability_min:
            continue

        target_score = len(group) * instability
        targets.append((target_score, instability, group))

    targets.sort(key=lambda t: t[0], reverse=True)

    if targets:
        top = targets[0]
        game.katrain.log(
            f"[find_targets] Primary target: size={len(top[2])}, instability={top[1]:.2f}, score={top[0]:.2f}",
            OUTPUT_DEBUG,
        )

    return targets


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
    if strategy == AI_DIVERGE:
        return 1 - settings.get("human_kyu_rank", -8)

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


# ==============================================================================
# JigoStrategy pure-function helpers
# ==============================================================================
def _jigo_filter_candidates(candidates, max_loss, min_hp):
    """フィルタ通過手のみを返す。各候補は {move, score, loss, hp} を持つ dict。"""
    return [c for c in candidates if c["loss"] <= max_loss and c["hp"] >= min_hp]


# humanPolicy ハードフロア（これ以下には絶対に緩和しない）
MIN_HP_HARD_FLOOR = 0.005


def _jigo_relax_filters(candidates, max_loss, min_hp, hard_floor=MIN_HP_HARD_FLOOR):
    """両フィルタ不通過時の段階緩和。

    返り値: (filtered_list, reason) — reason は "hp_half" / "hp_quarter" / "loss_150" / "safety_valve"。
    hp×0.5 → hp×0.25 → loss×1.5 → safety valve。

    各段階で hp 閾値は max(min_hp × factor, hard_floor) でクリップされる。
    """
    reason_map = [("hp_half", 0.5), ("hp_quarter", 0.25)]
    for reason, hp_factor in reason_map:
        threshold = max(min_hp * hp_factor, hard_floor)
        f = [c for c in candidates
             if c["loss"] <= max_loss and c["hp"] >= threshold]
        if f:
            return f, reason
    threshold = max(min_hp * 0.25, hard_floor)
    f = [c for c in candidates
         if c["loss"] <= max_loss * 1.5 and c["hp"] >= threshold]
    if f:
        return f, "loss_150"
    # Safety valve: 先頭候補（呼び出し側で KataGo 最善手が先頭に来るよう渡す前提）
    return ([candidates[0]] if candidates else []), "safety_valve"


# 鋭手除外用バッファ（KataGo scoreLead の微細ノイズを許容）
SHARP_EPSILON = 0.5


def _jigo_exclude_sharp_moves(candidates, current_lead, epsilon=SHARP_EPSILON):
    """圧勝時に「現在リードをさらに広げる手」を除外する。

    score > current_lead + epsilon の候補を落とす。
    除外結果が空になる場合は元のリストを返す（安全弁）。
    """
    non_sharp = [c for c in candidates if c["score"] <= current_lead + epsilon]
    return non_sharp if non_sharp else candidates


# 動的 rank 降格の chain（下位 → 上位）
_JIGO_RANK_CHAIN = ["rank_5d", "rank_7d", "rank_9d"]


def _select_rank_by_lead(current_lead, target_score_max, base_profile,
                          delta_1=5, delta_2=15):
    """リードが target_max を超えた度合いに応じて humanSL rank を降格する。

    - delta ≤ delta_1           : base_profile そのまま
    - delta_1 < delta ≤ delta_2 : base_profile より 1段下（9d→7d, 7d→5d, 5d→5d）
    - delta > delta_2           : 一気に rank_5d まで下げる

    base_profile が _JIGO_RANK_CHAIN に含まれない場合はそのまま返す。
    delta_1 / delta_2 は校正実験で調整可能（デフォルトは校正前の初期値）。
    """
    if delta_1 >= delta_2:
        raise ValueError(f"delta_1 ({delta_1}) must be < delta_2 ({delta_2})")
    if base_profile not in _JIGO_RANK_CHAIN:
        return base_profile
    delta = current_lead - target_score_max
    idx = _JIGO_RANK_CHAIN.index(base_profile)
    if delta > delta_2:
        new_idx = 0  # rank_5d 固定
    elif delta > delta_1:
        new_idx = max(0, idx - 1)
    else:
        new_idx = idx
    return _JIGO_RANK_CHAIN[new_idx]


# 9路盤での圧勝時 max_loss 上限（9路は HumanStyle NORMAL_THRESHOLD=3.3 のため緩和を控えめにする）
JIGO_LARGE_LEAD_9X9_CAP = 5.0


# ----------------------------------------------------------------
# Jigo deception Phase 機構
# ----------------------------------------------------------------
# 手数ベースの phase 境界（盤面サイズ → [(境界手数, phase 名), ...]）
JIGO_DECEPTION_PHASE_TABLE = {
    19: [(30, "phase1"), (80, "phase2"), (150, "phase3")],
    13: [(17, "phase1"), (44, "phase2"), (83, "phase3")],
    9:  [(8,  "phase1"), (20, "phase2"), (38, "phase3")],
}

# (board_size, phase) → (target_score, target_score_max) または None
# None は「ユーザ設定 target_score / target_score_max をそのまま使用」を意味
JIGO_DECEPTION_TARGETS = {
    (19, "phase0"): None,
    (19, "phase1"): (-3.0, -2.0),
    (19, "phase2"): (-1.5, -0.5),
    (19, "phase3"): None,
    (13, "phase0"): None,
    (13, "phase1"): (-2.0, -1.0),
    (13, "phase2"): (-1.0,  0.0),
    (13, "phase3"): None,
    (9,  "phase0"): None,
    (9,  "phase1"): (-1.5, -0.5),
    (9,  "phase2"): (-0.5,  0.0),
    (9,  "phase3"): None,
}

# 過剰優勢/過剰劣勢の安全弁閾値（目数）
JIGO_DECEPTION_SAFETY_OVERSHOOT = 5.0


def _jigo_resolve_phase(board_size, move_num, current_lead,
                        phase_table_override=None, target_overrides=None):
    """手数 + 安全弁から有効 phase を返す。

    Args:
        board_size: 19/13/9 等。テーブル未登録なら 19 路にフォールバック
        move_num: 1-indexed の現在手数（self.cn.depth 相当）
        current_lead: 前ターンの current_lead（None なら安全弁スキップ）
        phase_table_override: 指定すると JIGO_DECEPTION_PHASE_TABLE の代わりに
            このリスト [(境界手数, phase 名), ...] を使う。13路スライダー用。
        target_overrides: 指定すると JIGO_DECEPTION_TARGETS の代わりに
            このdict {"phase1": (target, target_max), "phase2": (...)} で
            安全弁の target_max を判定する。13路スライダー用。

    Returns:
        "phase0" | "phase1" | "phase2" | "phase3"
    """
    table = phase_table_override if phase_table_override is not None else \
        JIGO_DECEPTION_PHASE_TABLE.get(board_size, JIGO_DECEPTION_PHASE_TABLE[19])
    base_phase = "phase0"
    for boundary, phase in table:
        if move_num >= boundary:
            base_phase = phase

    # 安全弁は phase1/phase2 のみ
    if base_phase in ("phase1", "phase2") and current_lead is not None:
        base_target_max = None
        if target_overrides is not None and base_phase in target_overrides:
            _, base_target_max = target_overrides[base_phase]
        else:
            targets = JIGO_DECEPTION_TARGETS.get((board_size, base_phase))
            if targets is None:
                targets = JIGO_DECEPTION_TARGETS.get((19, base_phase))
            if targets is not None:
                _, base_target_max = targets
        if base_target_max is not None:
            if current_lead > base_target_max + JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"
            if current_lead < base_target_max - JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"

    return base_phase


def _jigo_resolve_13path_overrides(phase, default_target, default_target_max, settings):
    """13路盤の deception 有効時、Phase 1/2 で eff_target/eff_target_max を
    settings (スライダー値) に置換して返す。

    Phase 0/3 は default をそのまま返す（既存挙動）。
    target_max は target + 1.0 で自動算出（既存 1.0 目幅維持）。

    Args:
        phase: "phase0" | "phase1" | "phase2" | "phase3"
        default_target: phase0/phase3 用フォールバック値
        default_target_max: phase0/phase3 用フォールバック値
        settings: JigoStrategy.settings 相当の dict-like

    Returns:
        (eff_target, eff_target_max)
    """
    if phase == "phase1":
        t = settings.get("jigo_deception_13_phase1_target", -2.0)
        return t, t + 1.0
    if phase == "phase2":
        t = settings.get("jigo_deception_13_phase2_target", -1.0)
        return t, t + 1.0
    return default_target, default_target_max


def _jigo_compute_effective_max_loss(
    current_lead, target_score_max, base_max_loss,
    large_lead_delta, large_lead_max_loss, board_size,
):
    """current_lead が target_score_max + large_lead_delta を超えた場合のみ max_loss を緩和する。

    9路盤 (board_size <= 9) では effective 値を JIGO_LARGE_LEAD_9X9_CAP (5.0) にキャップする。
    緩和発動しない場合・large_lead_max_loss が base より小さい場合は base_max_loss を返す。
    """
    threshold = target_score_max + large_lead_delta
    if current_lead < threshold:
        return base_max_loss
    effective = large_lead_max_loss
    if board_size <= 9:
        effective = min(effective, JIGO_LARGE_LEAD_9X9_CAP)
    return max(base_max_loss, effective)


def _pick_target_closest_with_epsilon(candidates, target, epsilon):
    """target に近い候補群を同点扱いし、humanPolicy 重みで選択する。

    - epsilon <= 0 または候補1個 → argmin と同じ手を返す（band[0]）
    - candidates 空 → None
    - バンド内 hp 全ゼロ → argmin 決定的選択（safety net）
    """
    if not candidates:
        return None
    diffs = [(c, abs(c["score"] - target)) for c in candidates]
    min_diff = min(d for _, d in diffs)
    band = [c for c, d in diffs if d <= min_diff + epsilon]
    if epsilon <= 0 or len(band) <= 1:
        return band[0]
    total_hp = sum(c["hp"] for c in band)
    if total_hp <= 0:
        return min(band, key=lambda c: abs(c["score"] - target))
    weighted = [(c, c["hp"]) for c in band]
    return weighted_selection_without_replacement(weighted, 1)[0][0]


def _jigo_select_move(candidates, current_lead, target_score, target_score_max, mode, epsilon=0.0):
    """現在リード × Mode × ε で着手を選択。
    - 分岐1: current_lead < target_score → target 近傍 ε バンド + humanPolicy 重み
    - 分岐2: in_range & natural → humanPolicy 重み単体（ε 無視）
    - 分岐3: in_range & maintain → target 近傍 ε バンド + humanPolicy 重み
    - 分岐4: lead > target_max → argmin(|score-target|) 決定的（ε 無視、削り意図を保つ）

    in_range かつ未知 mode は ValueError。
    """
    # 分岐1: 負け〜互角
    if current_lead < target_score:
        return _pick_target_closest_with_epsilon(candidates, target_score, epsilon)

    # 分岐4: 圧勝（ε 無視、鋭手除外後の決定的選択）
    if current_lead > target_score_max:
        return min(candidates, key=lambda c: abs(c["score"] - target_score))

    # in_range 確定後の mode 分岐
    if mode == "natural":
        # 分岐2: humanPolicy 重み単体（ε 無視）
        weighted = [(c, c["hp"]) for c in candidates]
        selected = weighted_selection_without_replacement(weighted, 1)[0]
        return selected[0]
    if mode == "maintain":
        # 分岐3: target 近傍 ε バンド + humanPolicy 重み
        return _pick_target_closest_with_epsilon(candidates, target_score, epsilon)

    raise ValueError(f"unknown jigo_mode: {mode!r}")


@register_strategy(AI_JIGO)
class JigoStrategy(AIStrategy):
    """Jigo strategy - target を狙いつつ大差時も人間らしさを維持する戦略。

    ロジック:
        1. Stage 1 (humanSL 9段固定) で humanPolicy を取得
        2. Stage 2 (clean) で正確な scoreLead を取得
        3. loss <= max_loss_per_move AND hp >= min_human_policy でフィルタ
        4. current_lead × jigo_mode で選択ロジック分岐
        5. 候補ゼロ時は段階緩和 → 最終的に KataGo 最善手へフォールバック
    """

    def generate_move(self) -> Tuple[Move, str]:
        import time
        self.last_decision_info = {
            "rank_used": None,
            "selected_hp": None,
            "selected_score": None,
            "filter_relaxed": False,  # bool, not None — absence means "no fallback", not "unknown"
            "score_lead": None,
            "score_lead_biased": False,  # True when Stage2 failed and Stage1 (biased) was used
        }
        self.game.katrain.log(f"[JigoStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()

        # ---- 設定読み込み ----
        target_score     = self.settings.get("target_score", 0.5)
        target_score_max = self.settings.get("target_score_max", 10.0)
        max_loss         = self.settings.get("max_loss_per_move", 5.6)
        min_hp           = self.settings.get("min_human_policy", 0.02)
        mode             = self.settings.get("jigo_mode", "natural")
        base_profile     = self.settings.get("human_profile", "rank_9d")
        dynamic_rank     = self.settings.get("jigo_dynamic_rank", False)
        large_lead_delta    = self.settings.get("jigo_large_lead_delta", 5.0)
        large_lead_max_loss = self.settings.get("jigo_large_lead_max_loss", 8.0)
        equivalent_epsilon  = self.settings.get("jigo_equivalent_epsilon", 0.5)
        deception_enabled = self.settings.get("jigo_deception", False)
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}, "
            f"profile={base_profile}, dynamic_rank={dynamic_rank}, "
            f"large_lead_delta={large_lead_delta}, large_lead_max_loss={large_lead_max_loss}, "
            f"equivalent_epsilon={equivalent_epsilon}, deception={deception_enabled}",
            OUTPUT_DEBUG,
        )

        # ---- Phase 解決（jigo_deception=True 時のみ有効値を上書き） ----
        eff_target = target_score
        eff_target_max = target_score_max
        eff_mode = mode
        eff_large_lead_delta = large_lead_delta
        phase = "phase0"
        if deception_enabled:
            # board_size は既存呼び出し規約に合わせ max(width, height) を採用
            board_size_for_phase = max(self.game.board_size)
            move_num = self.cn.depth
            last_lead = getattr(self.game, "_jigo_last_current_lead", None)

            # 13路盤限定: スライダー値で phase 境界と target_overrides を構築
            phase_table_override = None
            target_overrides = None
            if board_size_for_phase == 13:
                phase_table_override = [
                    (self.settings.get("jigo_deception_13_phase1_start", 17), "phase1"),
                    (self.settings.get("jigo_deception_13_phase2_start", 44), "phase2"),
                    (self.settings.get("jigo_deception_13_phase3_start", 83), "phase3"),
                ]
                p1_target = self.settings.get("jigo_deception_13_phase1_target", -2.0)
                p2_target = self.settings.get("jigo_deception_13_phase2_target", -1.0)
                target_overrides = {
                    "phase1": (p1_target, p1_target + 1.0),
                    "phase2": (p2_target, p2_target + 1.0),
                }

            phase = _jigo_resolve_phase(
                board_size_for_phase, move_num, last_lead,
                phase_table_override=phase_table_override,
                target_overrides=target_overrides,
            )

            # Phase 1/2 の eff_target/eff_target_max を決定
            if board_size_for_phase == 13:
                eff_target, eff_target_max = _jigo_resolve_13path_overrides(
                    phase, target_score, target_score_max, self.settings
                )
            else:
                overrides = JIGO_DECEPTION_TARGETS.get((board_size_for_phase, phase))
                if overrides is None:
                    overrides = JIGO_DECEPTION_TARGETS.get((19, phase))
                if overrides is not None:
                    eff_target, eff_target_max = overrides

            # Phase 1/2 中は mode を maintain に固定（natural だと in_range で target に寄らない）
            if phase in ("phase1", "phase2"):
                eff_mode = "maintain"
                # Phase 1/2 中は large_lead 緩和を無効化（小さい eff_target_max で誤発動を防ぐ）
                eff_large_lead_delta = float("inf")
            self.game.katrain.log(
                f"[JigoStrategy] Deception: move={move_num}, phase={phase}, "
                f"eff_target={eff_target}, eff_target_max={eff_target_max}, "
                f"eff_mode={eff_mode}, last_lead={last_lead}, "
                f"board={board_size_for_phase}, sliders={target_overrides is not None}",
                OUTPUT_DEBUG,
            )

        sign = self.cn.player_sign(self.cn.next_player)
        engine = self.game.engines[self.cn.player]

        # ---- Stage 1 用 humanSL rank 決定 ----
        # キャッシュは self.game に保存（strategy インスタンスは毎手破棄されるため）
        last_lead = getattr(self.game, "_jigo_last_current_lead", None)
        if dynamic_rank and last_lead is not None:
            delta_1 = self.settings.get("jigo_rank_delta_1", 5)
            delta_2 = self.settings.get("jigo_rank_delta_2", 15)
            human_profile = _select_rank_by_lead(
                last_lead, eff_target_max, base_profile,
                delta_1=delta_1, delta_2=delta_2,
            )
            if human_profile != base_profile:
                self.game.katrain.log(
                    f"[JigoStrategy] Dynamic rank: base={base_profile}, "
                    f"last_lead={last_lead:.2f}, "
                    f"delta={last_lead - eff_target_max:.2f} → {human_profile} "
                    f"(delta_1={delta_1}, delta_2={delta_2})",
                    OUTPUT_DEBUG,
                )
        else:
            human_profile = base_profile
        stage1_override = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 1,
        }
        self.last_decision_info["rank_used"] = human_profile
        stage1_analysis = None
        stage1_error = False

        def _set_stage1(a, partial):
            nonlocal stage1_analysis
            if not partial:
                stage1_analysis = a

        def _err_stage1(a):
            nonlocal stage1_error
            stage1_error = True
            self.game.katrain.log(f"[JigoStrategy] Stage1 error: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=_set_stage1, error_callback=_err_stage1,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=True,
            extra_settings=stage1_override,
        )
        while not (stage1_error or stage1_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if stage1_error or not stage1_analysis or "humanPolicy" not in stage1_analysis:
            self.game.katrain.log(
                "[JigoStrategy] Stage1 failed, falling back to KataGo top move", OUTPUT_DEBUG
            )
            candidate_moves = self.cn.candidate_moves
            if not candidate_moves:
                return Move(None, player=self.cn.next_player), "Stage1 failed, no candidates"
            top = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
            return top, "Stage1 failed — using KataGo top move"

        human_policy = stage1_analysis["humanPolicy"]
        self.game.katrain.log(
            f"[JigoStrategy] Stage1 query complete (humanPolicy len={len(human_policy)})",
            OUTPUT_DEBUG,
        )

        # ---- 星打ち強制（19路盤・序盤のみ。黒=三連星 / 白=2連星） ----
        if self.settings.get("jigo_force_sanrensei", False) and \
                self.game.board_size[0] == 19 and self.game.board_size[1] == 19:
            n_star = 3 if self.cn.next_player == "B" else 2
            target_stars = _compute_star_opening_targets(
                self.game.board_size, self.game.stones, self.cn.next_player, n_star
            )
            if target_stars:
                coords = _select_star_target(target_stars, human_policy, self.game.board_size)
                aimove = Move(coords, player=self.cn.next_player)
                self.game.katrain.log(
                    f"[JigoStrategy] force_sanrensei: n={n_star}, "
                    f"targets={sorted(target_stars)}, chose={coords}",
                    OUTPUT_DEBUG,
                )
                return aimove, f"Jigo force star opening (n={n_star}): {aimove.gtp()}"

        # ---- Stage 2: クリーンクエリ（scoreLead 用） ----
        stage2_override = {
            "ignorePreRootHistory": False,
            "maxVisits": 600,
            "wideRootNoise": 0.0,
        }
        stage2_analysis = None
        stage2_error = False

        def _set_stage2(a, partial):
            nonlocal stage2_analysis
            if not partial:
                stage2_analysis = a

        def _err_stage2(a):
            nonlocal stage2_error
            stage2_error = True
            self.game.katrain.log(f"[JigoStrategy] Stage2 error: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=_set_stage2, error_callback=_err_stage2,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=False,
            extra_settings=stage2_override,
        )
        while not (stage2_error or stage2_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        # Stage 2 失敗時は Stage 1 にフォールバック
        if stage2_error or not stage2_analysis:
            self.last_decision_info["score_lead_biased"] = True
            self.game.katrain.log(
                "[JigoStrategy] Stage2 failed, using Stage1 moveInfos (biased)", OUTPUT_DEBUG
            )
            score_analysis = stage1_analysis
        else:
            score_analysis = stage2_analysis
        move_infos = score_analysis.get("moveInfos", [])
        if not move_infos:
            self.game.katrain.log("[JigoStrategy] No moveInfos, passing", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "No moveInfos, passing"

        # current_lead を前倒し計算（effective max_loss 判定のため）
        current_lead = score_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign

        # ---- 候補リスト構築（すべて自分視点 = sign を掛けた値） ----
        scores_player = [mi.get("scoreLead", 0) * sign for mi in move_infos]
        best_score = max(scores_player)  # 自分視点の最善スコア

        # Stage 1 のhumanPolicy をフラット配列から gtp → value のルックアップに変換
        bx, by = self.game.board_size
        def _hp_for_gtp(gtp):
            if gtp == "pass":
                return human_policy[-1] if len(human_policy) > bx * by else 0.0
            try:
                m = Move.from_gtp(gtp, player=self.cn.next_player)
                if m.coords is None:
                    return 0.0
                x, y = m.coords
                idx = (by - y - 1) * bx + x
                return human_policy[idx] if 0 <= idx < len(human_policy) else 0.0
            except Exception:
                return 0.0

        candidates = []
        for mi, score in zip(move_infos, scores_player):
            gtp = mi.get("move", "")
            candidates.append({
                "move": gtp,
                "score": score,           # 自分視点
                "loss": best_score - score,
                "hp": _hp_for_gtp(gtp),
            })
        self.game.katrain.log(
            f"[JigoStrategy] Stage2 query complete ({len(candidates)} candidates, "
            f"best_score={best_score:.2f})", OUTPUT_DEBUG
        )

        # ---- 圧勝時の max_loss 動的緩和 ----
        board_size = max(self.game.board_size)
        effective_max_loss = _jigo_compute_effective_max_loss(
            current_lead=current_lead,
            target_score_max=eff_target_max,
            base_max_loss=max_loss,
            large_lead_delta=eff_large_lead_delta,
            large_lead_max_loss=large_lead_max_loss,
            board_size=board_size,
        )
        if effective_max_loss != max_loss:
            self.game.katrain.log(
                f"[JigoStrategy] Large lead expansion: lead={current_lead:.2f} ≥ "
                f"eff_target_max+{eff_large_lead_delta} = {eff_target_max + eff_large_lead_delta:.2f}, "
                f"max_loss: {max_loss} → {effective_max_loss}",
                OUTPUT_DEBUG,
            )

        # ---- フィルタ適用 ----
        filtered = _jigo_filter_candidates(candidates, effective_max_loss, min_hp)
        passed = len(filtered)
        self.game.katrain.log(
            f"[JigoStrategy] Filter: {len(candidates)} → {passed} passed "
            f"(loss<={effective_max_loss}, hp>={min_hp})", OUTPUT_DEBUG
        )

        # ---- フォールバック段階緩和 ----
        if not filtered:
            filtered, reason = _jigo_relax_filters(candidates, effective_max_loss, min_hp)
            self.last_decision_info["filter_relaxed"] = True
            self.game.katrain.log(
                f"[JigoStrategy] Fallback triggered: reason={reason}, {len(filtered)} candidates",
                OUTPUT_DEBUG
            )
            if reason == "safety_valve":
                self.game.katrain.log(
                    "[JigoStrategy] Safety valve: using KataGo top move", OUTPUT_ERROR
                )

        # ---- 現在リード & 選択分岐 ----
        in_range = eff_target <= current_lead <= eff_target_max
        self.game.katrain.log(
            f"[JigoStrategy] Mode: {eff_mode}, lead={current_lead:.2f}, in_range={in_range}",
            OUTPUT_DEBUG,
        )

        # ---- 鋭手除外（圧勝時のみ） ----
        if current_lead > eff_target_max:
            before_exclude = len(filtered)
            filtered = _jigo_exclude_sharp_moves(filtered, current_lead)
            self.game.katrain.log(
                f"[JigoStrategy] Sharp-move exclusion: {before_exclude} → {len(filtered)} "
                f"(lead={current_lead:.2f} > eff_target_max={eff_target_max})",
                OUTPUT_DEBUG,
            )

        pick = _jigo_select_move(filtered, current_lead, eff_target, eff_target_max, eff_mode, equivalent_epsilon)

        # ---- 結果 ----
        if pick["move"] == "pass":
            aimove = Move(None, player=self.cn.next_player)
        else:
            aimove = Move.from_gtp(pick["move"], player=self.cn.next_player)
        ai_thoughts = (
            f"Jigo (mode={eff_mode}, phase={phase}, lead={current_lead:.1f}): chose {pick['move']} "
            f"(loss={pick['loss']:.2f}, hp={pick['hp']:.3f}, score={pick['score']:.2f})"
        )
        self.game.katrain.log(
            f"[JigoStrategy] Selected: {pick['move']} "
            f"(loss={pick['loss']:.2f}, hp={pick['hp']:.3f}, score={pick['score']:.2f})",
            OUTPUT_DEBUG,
        )

        # ---- 選択情報を batch_eval から参照できるよう露出 ----
        self.last_decision_info.update({
            "selected_hp": pick["hp"],
            "selected_score": pick["score"],
            "score_lead": current_lead,
        })

        # ---- 次ターンの動的 rank 判定用にキャッシュ（game インスタンスに保存、新規ゲームで自動リセット） ----
        self.game._jigo_last_current_lead = current_lead

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

        if self.settings.get("force_tengen_opening", False) and self.cn.next_player == "B" and len(self.game.stones) == 0:
            tx, ty = self.game.board_size[0] // 2, self.game.board_size[1] // 2
            self.game.katrain.log(f"[FightingStrategy] Force Tengen opening: playing B ({tx},{ty})", OUTPUT_DEBUG)
            return Move((tx, ty), player="B"), "Force Tengen opening."

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
        
        invasion_bonus = self.settings.get("fighting_invasion_bonus", 1.0)
        contact_boost = self.settings.get("fighting_contact_boost", 1.0)
        player_sign = 1 if self.cn.next_player == "B" else -1
        
        weights = {}
        for x in range(size[0]):
            for y in range(size[1]):
                o = ownership_grid[y][x] if ownership_grid else 0.0
                unsettled = (1.0 - abs(o)) ** unsettled_power
                
                min_dist_sq = 1000
                if opponent_coords:
                    min_dist_sq = min((x - ox) ** 2 + (y - oy) ** 2 for ox, oy in opponent_coords)
                    prox = math.exp(-0.5 * min_dist_sq / prox_var)
                else:
                    prox = 1.0
                
                w = unsettled * prox
                
                if min_dist_sq == 1:
                    w *= contact_boost
                    
                if (player_sign * o) < -0.5 and min_dist_sq <= 2:
                    w *= invasion_bonus
                    
                weights[(x, y)] = max(w, 1e-6)
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

        # area scoringルール判定（中国・AGA・Tromp-Taylor・NZ・石計算）
        _ruleset = self.cn.ruleset
        _rules = KataGoEngine.get_rules(_ruleset)
        is_area_scoring = (
            (isinstance(_rules, str) and _rules.lower() in ["chinese", "aga", "tromp-taylor", "new zealand", "stone_scoring"])
            or (isinstance(_rules, dict) and _rules.get("scoring", "").lower() == "area")
        )

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
            
            chaos_relax = self.settings.get("fighting_chaos_relax", 0.0)
            ownership_grid = var_to_grid(self.cn.ownership, board_size) if self.cn.ownership else None
            opponent_coords = [s.coords for s in self.game.stones if s.player != self.cn.next_player]

            def _filter_moves(move_infos, threshold_base, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score):
                """指定閾値で悪手フィルタを実行し、通過した手のsetを返す。"""
                result = set()
                for mi in move_infos:
                    gtp_move = mi.get("move", "")
                    score = mi.get("scoreLead", 0)
                    loss = player_sign * (best_score - score)

                    threshold = threshold_base
                    if chaos_relax > 0.0 and gtp_move != "pass":
                        mx, my = Move.from_gtp(gtp_move, player=self.cn.next_player).coords
                        o = ownership_grid[my][mx] if ownership_grid else 0.0
                        is_opponent_terr = (player_sign * o) < -0.5

                        min_dist_sq = 1000
                        if opponent_coords:
                            min_dist_sq = min((mx - ox) ** 2 + (my - oy) ** 2 for ox, oy in opponent_coords)

                        if is_opponent_terr and min_dist_sq == 1:
                            threshold += chaos_relax

                    if loss < threshold:
                        result.add(gtp_move)
                return result

            good_moves = _filter_moves(move_infos, BAD_MOVE_THRESHOLD, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score)
            # --- 段階的閾値緩和フェイルセーフ ---
            _FILTER_RELAXATION_STEPS = [1.5, 2.0]
            _FILTER_ABSOLUTE_CAP = 9.0
            if not good_moves:
                original_threshold = BAD_MOVE_THRESHOLD
                for multiplier in _FILTER_RELAXATION_STEPS:
                    relaxed_threshold = original_threshold * multiplier
                    good_moves = _filter_moves(move_infos, relaxed_threshold, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score)
                    if good_moves:
                        self.game.katrain.log(
                            f"[FightingStrategy:human] Filter relaxed: threshold {original_threshold} -> {relaxed_threshold:.1f}, found {len(good_moves)} moves",
                            OUTPUT_DEBUG,
                        )
                        break
                if not good_moves:
                    good_moves = _filter_moves(move_infos, _FILTER_ABSOLUTE_CAP, 0.0, ownership_grid, opponent_coords, player_sign, best_score)
                    if good_moves:
                        self.game.katrain.log(
                            f"[FightingStrategy:human] Filter relaxed: threshold {original_threshold} -> {_FILTER_ABSOLUTE_CAP} (absolute cap), found {len(good_moves)} moves",
                            OUTPUT_DEBUG,
                        )
                if not good_moves and best_gtp_by_score:
                    self.game.katrain.log(
                        f"[FightingStrategy:human] Filter failsafe: no moves passed even at {_FILTER_ABSOLUTE_CAP}pt cap, forcing best-score move {best_gtp_by_score}",
                        OUTPUT_DEBUG,
                    )
                    if best_gtp_by_score == "pass":
                        return Move(None, player=self.cn.next_player), "Filter failsafe: best move is pass."
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                        f"Filter failsafe: no moves within {_FILTER_ABSOLUTE_CAP}pt, forced {best_gtp_by_score}."
                    )
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
            _SAFETY_LOSS_THRESHOLD = 4.0
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

        # passが候補手に含まれているかチェック
        if any(m.is_pass for m, _ in moves):
            if is_area_scoring:
                # area scoring（中国ルール等）ではpassは最善手の場合のみ選択する
                # best_gtp_by_score == "pass" は既に上で処理済み → passを候補から除外して続行
                # ただし、passと最善手のスコア差が小さい場合は強制パス（ダメ点程度の差なら打つ価値なし）
                _AREA_PASS_MARGIN = 0.5
                pass_mi = next((mi for mi in (move_infos or []) if mi.get("move") == "pass"), None)
                if pass_mi is not None:
                    pass_score_lead = pass_mi.get("scoreLead", best_score)
                    pass_loss = player_sign * (best_score - pass_score_lead)
                    if pass_loss < _AREA_PASS_MARGIN:
                        self.game.katrain.log(
                            f"[FightingStrategy:human] Area scoring: pass within {_AREA_PASS_MARGIN}pt of best "
                            f"(loss={pass_loss:.2f}), forcing pass", OUTPUT_DEBUG
                        )
                        return Move(None, player=self.cn.next_player), "Area scoring: pass near-optimal, forcing pass."
                moves_without_pass = [(m, w) for m, w in moves if not m.is_pass]
                if moves_without_pass:
                    moves = moves_without_pass
                    self.game.katrain.log(
                        f"[FightingStrategy:human] Area scoring: pass removed from candidates "
                        f"(better non-pass moves exist, best={best_gtp_by_score})", OUTPUT_DEBUG
                    )
                    # fall through to normal selection
                else:
                    if best_gtp_by_score and best_gtp_by_score != "pass":
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), \
                            "Area scoring: playing best non-pass move."
                    return Move(None, player=self.cn.next_player), "Area scoring: no non-pass candidates."
            else:
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

_COMPLEXITY_WEIGHT_FRAC = 0.5
_COMPLEXITY_RAMP = 10.0


def _count_cut_adjacency(board, chains, coord, opponent_player):
    """coord (x,y) の4近傍に接する『異なる相手 chain』の数を返す。

    board: List[List[int]]  # board[y][x] = chain id（-1=空）
    chains: List[List[Move]]
    opponent_player: "B" or "W"
    戻り値が 2 以上なら『切り/楔』とみなせる。
    """
    x, y = coord
    height = len(board)
    width = len(board[0]) if height else 0
    opp_chain_ids = set()
    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
        if 0 <= nx < width and 0 <= ny < height:
            c = board[ny][nx]
            if c >= 0 and chains[c] and chains[c][0].player == opponent_player:
                opp_chain_ids.add(c)
    return len(opp_chain_ids)


def _apply_cut_boost(weights, board, chains, opponent_player, cut_boost):
    """weights {(x,y): w} の空点かつ切り点に cut_boost を乗算した新 dict を返す。"""
    if cut_boost == 1.0:
        return dict(weights)
    boosted = {}
    for (x, y), w in weights.items():
        if board[y][x] == -1 and _count_cut_adjacency(board, chains, (x, y), opponent_player) >= 2:
            boosted[(x, y)] = w * cut_boost
        else:
            boosted[(x, y)] = w
    return boosted


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


def _get_star_lines(board_size):
    """19路盤の4辺それぞれの星点ライン（隅2 + 中辺星1 の3点コリニア集合）を返す。

    中辺の星が存在しない盤面（13/9路等）では空リストを返す（= n=3 三連星は19路専用）。
    """
    bx, by = board_size
    if not (bx == 19 and by == 19):
        return []
    near_x, far_x = 3, bx - 4   # 3, 15
    near_y, far_y = 3, by - 4   # 3, 15
    mid_x, mid_y = bx // 2, by // 2  # 9, 9
    bottom = [(near_x, near_y), (mid_x, near_y), (far_x, near_y)]
    top    = [(near_x, far_y),  (mid_x, far_y),  (far_x, far_y)]
    left   = [(near_x, near_y), (near_x, mid_y), (near_x, far_y)]
    right  = [(far_x, near_y),  (far_x, mid_y),  (far_x, far_y)]
    return [bottom, top, left, right]


def _compute_star_opening_targets(board_size, stones, ai_player, n):
    """星打ち布石で次に打つべき星点座標の集合を返す。

    n=2: 隅4星のみを使う2連星ロジック（HumanStyle 既存挙動の移植）。
    n=3: 側辺ライン（隅2+中辺星）を使う三連星ロジック（19路専用）。
    強制不要・完成済み・盤面非対応なら空集合を返す。
    """
    opp = "W" if ai_player == "B" else "B"
    stones_by_pos = {m.coords: m.player for m in stones if m.coords is not None}
    corner_stars = _get_corner_star_points(board_size)

    if n == 2:
        ai_stars = [c for c in corner_stars if stones_by_pos.get(c) == ai_player]
        opp_stars = [c for c in corner_stars if stones_by_pos.get(c) == opp]
        empty = {c for c in corner_stars if c not in stones_by_pos}
        if len(ai_stars) == 0 and empty:
            if opp_stars:
                diag = _diagonal_star(opp_stars[0], corner_stars)
                return {diag} if diag and diag in empty else set(empty)
            return set(empty)
        if len(ai_stars) == 1 and empty:
            first = ai_stars[0]
            same_side = {c for c in corner_stars if c[0] == first[0] or c[1] == first[1]} - {first}
            return same_side & empty
        return set()

    if n == 3:
        lines = _get_star_lines(board_size)
        if not lines:
            return set()
        # 各ラインの AI石数・相手石数・空点を集計
        line_stats = []  # (ai_count, opp_count, empty_points)
        for line in lines:
            ai_count = sum(1 for p in line if stones_by_pos.get(p) == ai_player)
            opp_count = sum(1 for p in line if stones_by_pos.get(p) == opp)
            empty_pts = {p for p in line if p not in stones_by_pos}
            line_stats.append((ai_count, opp_count, empty_pts))
        # いずれかのラインが既に完成していれば強制終了
        if any(ai_count >= 3 for ai_count, _, _ in line_stats):
            return set()
        max_ai = max(ai_count for ai_count, _, _ in line_stats)
        if max_ai == 0:
            # AI 石ゼロ（初手）→ 相手石が無いラインの空き隅星から開始（中辺星は最初に出さない）
            starts = set()
            for ai_count, opp_count, empty_pts in line_stats:
                if opp_count == 0:
                    starts |= {p for p in empty_pts if p in corner_stars}
            return starts
        # AI が最も石を置いた「コミット済みライン」のみを対象にする。
        # コミット済みラインが相手に妨害されていなければ、その空点で続行（完成を目指す）。
        committed_viable = [
            empty_pts for ai_count, opp_count, empty_pts in line_stats
            if ai_count == max_ai and opp_count == 0
        ]
        if committed_viable:
            targets = set()
            for empty_pts in committed_viable:
                targets |= empty_pts
            return targets
        # コミット済みラインがすべて相手に妨害された → 三連星は崩れたとみなし強制終了。
        # （別ラインへ pivot せず通常 jigo に戻す）
        return set()

    return set()


def _select_star_target(target_stars, human_policy, board_size):
    """target_stars の中から humanPolicy 最大の座標を返す。同値は座標昇順で決定的に選ぶ。

    humanPolicy が全て 0（modern_style で星点に 0 が返るケース）でも強制するため、
    hp による足切りは行わず最小座標を返す。
    """
    bx, by = board_size

    def hp(coord):
        x, y = coord
        idx = (by - y - 1) * bx + x
        return human_policy[idx] if 0 <= idx < len(human_policy) else 0.0

    # 座標昇順で走査し max を取る → 同値時は最小座標が選ばれる（決定的）
    return max(sorted(target_stars), key=hp)


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
        # area scoringルール判定（中国・AGA・Tromp-Taylor・NZ・石計算）
        # territory scoring（日本・韓国）と異なり、ダメは1点の価値があるためパス判断に影響する
        _ruleset = self.cn.ruleset
        _rules = KataGoEngine.get_rules(_ruleset)
        is_area_scoring = (
            (isinstance(_rules, str) and _rules.lower() in ["chinese", "aga", "tromp-taylor", "new zealand", "stone_scoring"])
            or (isinstance(_rules, dict) and _rules.get("scoring", "").lower() == "area")
        )

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
            target_stars = _compute_star_opening_targets(
                board_size, self.game.stones, self.cn.next_player, 2
            )

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
                        f"[HumanStyleStrategy] force_star_opening: "
                        f"targets={[f'({c[0]},{c[1]})' for c in target_stars]}",
                        OUTPUT_DEBUG,
                    )

        # 終局閾値（big-win フィルター内の relax 判定にも使用）
        endgame_threshold = 32 if (bx == 9 and by == 9) else math.ceil(bx * by * 0.5)

        # passが候補手に含まれているかチェック
        if any(m.is_pass for m, _ in moves):
            if is_area_scoring:
                # area scoring（中国ルール等）では、ダメは1点の価値があるためpassは最善手の場合のみ選択する
                # best_gtp_by_score == "pass" の場合は既に上で処理済み（強制パス済み）
                # ただし、passと最善手のスコア差が小さい場合は強制パス（ダメ点程度の差なら打つ価値なし）
                _AREA_PASS_MARGIN = 0.5
                pass_mi = next((mi for mi in (move_infos or []) if mi.get("move") == "pass"), None)
                if pass_mi is not None:
                    pass_score_lead = pass_mi.get("scoreLead", best_score)
                    pass_loss = player_sign * (best_score - pass_score_lead)
                    if pass_loss < _AREA_PASS_MARGIN:
                        self.game.katrain.log(
                            f"[HumanStyleStrategy] Area scoring: pass within {_AREA_PASS_MARGIN}pt of best "
                            f"(loss={pass_loss:.2f}), forcing pass", OUTPUT_DEBUG
                        )
                        return Move(None, player=self.cn.next_player), "Area scoring: pass near-optimal, forcing pass."
                # ここに来た = KataGoはpassを最善と判断していない → passを候補から除外して続行
                moves_without_pass = [(m, w) for m, w in moves if not m.is_pass]
                if moves_without_pass:
                    moves = moves_without_pass
                    self.game.katrain.log(
                        f"[HumanStyleStrategy] Area scoring: pass removed from candidates "
                        f"(better non-pass moves exist, best={best_gtp_by_score})", OUTPUT_DEBUG
                    )
                    # fall through to normal selection
                else:
                    # passのみ候補にある（理論上ここには来ないはずだが安全弁）
                    if best_gtp_by_score and best_gtp_by_score != "pass":
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), \
                            "Area scoring: playing best non-pass move."
                    return Move(None, player=self.cn.next_player), "Area scoring: no non-pass candidates."
            else:
                # territory scoring（日本・韓国ルール等）: 従来通り強制パス
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
            _DEV_MIN_POLICY = 0.05  # humanPolicy < 5%の手はdeviation候補から除外
            deviation_candidates = []
            for m, w in top_moves[:3]:
                if w < _DEV_MIN_POLICY:
                    continue
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


@register_strategy(AI_DIVERGE)
class DivergenceStrategy(AIStrategy):
    """Strategy that reduces AI move match rate while maintaining strength.

    Algorithm:
      Stage 1: humanSL query → humanPolicy[]
      Stage 2: clean query   → moveInfos[] with accurate scoreLead
      Score:   divergence_score[i] = humanPolicy[i] * (order[i] + 1)^divergence_power
      Filter:  loss > diverge_score_filter を除外
      Fallback: 候補 ≤ 3 の場合は humanPolicy のみ使用（divergence 無効化）
    """

    def __init__(self, game: Game, ai_settings: Dict):
        super().__init__(game, ai_settings)
        self.game.katrain.log(
            f"[DivergenceStrategy] Initializing with settings: {ai_settings}",
            OUTPUT_DEBUG,
        )

    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[DivergenceStrategy] Starting move generation", OUTPUT_DEBUG)

        human_kyu_rank = round(self.settings.get("human_kyu_rank", -8))
        if human_kyu_rank <= 0:
            rank_text = f"{1 - human_kyu_rank}d"
        else:
            rank_text = f"{human_kyu_rank}k"
        human_profile = f"rank_{rank_text}"

        divergence_power = float(self.settings.get("divergence_power", 0.5))
        score_filter = float(self.settings.get("diverge_score_filter", 2.5))

        self.game.katrain.log(
            f"[DivergenceStrategy] profile={human_profile}, "
            f"divergence_power={divergence_power}, score_filter={score_filter}",
            OUTPUT_DEBUG,
        )

        # --- Stage 1: humanSL クエリ（humanPolicy 取得） ---
        analysis = None
        error = False

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[DivergenceStrategy] Stage1 error: {a}", OUTPUT_ERROR)

        engine = self.game.engines[self.cn.player]
        engine.request_analysis(
            self.cn,
            callback=set_analysis,
            error_callback=set_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=True,
            extra_settings={
                "humanSLProfile": human_profile,
                "ignorePreRootHistory": False,
                "maxVisits": 800,
            },
        )

        while not (error or analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if error or not analysis or "humanPolicy" not in analysis:
            self.game.katrain.log(
                f"[DivergenceStrategy] Stage1 failed, falling back to policy", OUTPUT_DEBUG
            )
            policy_move = self.cn.policy_ranking[0][1] if self.cn.policy_ranking else None
            if policy_move:
                return policy_move, "DivergenceStrategy: fallback to policy (Stage1 error)."
            return Move(None, player=self.cn.next_player), "DivergenceStrategy: no valid moves."

        human_policy = analysis["humanPolicy"]
        bx, by = self.game.board_size

        # --- Stage 2: クリーンクエリ（正確な scoreLead 取得） ---
        # humanSLProfile 付きクエリの scoreLead はバイアスされるため、
        # Stage2 のクリーン値を損失フィルタ判定に使用する
        clean_analysis = None
        clean_error = False

        def set_clean_analysis(a, partial_result):
            nonlocal clean_analysis
            if not partial_result:
                clean_analysis = a

        def set_clean_error(a):
            nonlocal clean_error
            clean_error = True
            self.game.katrain.log(f"[DivergenceStrategy] Stage2 error: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn,
            callback=set_clean_analysis,
            error_callback=set_clean_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=False,
            extra_settings={
                "ignorePreRootHistory": False,
                "maxVisits": 600,
                "wideRootNoise": 0.0,
            },
        )

        while not (clean_error or clean_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if clean_analysis and not clean_error:
            move_infos = clean_analysis.get("moveInfos", [])
            self.game.katrain.log(
                f"[DivergenceStrategy] Using clean moveInfos ({len(move_infos)} moves)",
                OUTPUT_DEBUG,
            )
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log(
                f"[DivergenceStrategy] Stage2 failed, using biased moveInfos "
                f"({len(move_infos)} moves)",
                OUTPUT_DEBUG,
            )

        # moveInfos が空の場合は humanPolicy 最上位手を返す
        if not move_infos:
            self.game.katrain.log(
                f"[DivergenceStrategy] No moveInfos, using top humanPolicy", OUTPUT_DEBUG
            )
            top_idx = max(range(len(human_policy)), key=lambda i: human_policy[i])
            x = top_idx % bx
            y = by - 1 - (top_idx // bx)
            return Move((x, y), player=self.cn.next_player), "No moveInfos available."

        # player_sign: Black=+1, White=-1（scoreLead は常に Black 視点）
        player_sign = 1 if self.cn.next_player == "B" else -1

        # best_score: 現在プレイヤー視点での最善スコア（Black=max, White=min scoreLead）
        best_score = (
            max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
        )

        # order=0 の手がパスなら強制パス
        order0_mi = next(
            (mi for mi in move_infos if mi.get("order", 999) == 0), move_infos[0]
        )
        if order0_mi.get("move") == "pass":
            return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."

        # 候補手の divergence スコアを計算
        # divergence_score[i] = humanPolicy[i] × (order[i] + 1)^divergence_power
        # order が大きい（AI が低く評価）ほどブーストが大きくなる
        candidates = []  # [(Move, divergence_score, humanPolicy, order, loss)]
        for i, mi in enumerate(move_infos):
            gtp = mi.get("move", "")
            if not gtp or gtp == "pass":
                continue
            order = mi.get("order", i)
            score = mi.get("scoreLead", 0)
            loss = player_sign * (best_score - score)  # 正値 = 現在プレイヤーにとって損

            if loss > score_filter:
                continue  # スコアフィルタ: 損失過大な手を除外

            try:
                m = Move.from_gtp(gtp, player=self.cn.next_player)
            except Exception:
                continue
            if m.coords is None:
                continue
            x, y = m.coords
            idx = (by - y - 1) * bx + x
            if idx < 0 or idx >= len(human_policy):
                continue

            hp = human_policy[idx]
            if hp <= 0:
                continue  # humanPolicy=0 の手は選択候補から除外
            div_score = hp * ((order + 1) ** divergence_power)
            candidates.append((m, div_score, hp, order, loss))

        self.game.katrain.log(
            f"[DivergenceStrategy] {len(candidates)} candidates after score filter "
            f"(filter={score_filter})",
            OUTPUT_DEBUG,
        )

        # フォールバック: スコアフィルタ後に候補が0の場合、フィルタを解除して再構築
        if not candidates:
            self.game.katrain.log(
                f"[DivergenceStrategy] No candidates after filter, relaxing to all moveInfos",
                OUTPUT_DEBUG,
            )
            for i, mi in enumerate(move_infos):
                gtp = mi.get("move", "")
                if not gtp or gtp == "pass":
                    continue
                try:
                    m = Move.from_gtp(gtp, player=self.cn.next_player)
                except Exception:
                    continue
                if m.coords is None:
                    continue
                x, y = m.coords
                idx = (by - y - 1) * bx + x
                if idx < 0 or idx >= len(human_policy):
                    continue
                hp = human_policy[idx]
                candidates.append((m, hp, hp, mi.get("order", i), 999.0))

        # それでも候補が無ければ AI 最善手を返す
        if not candidates:
            best_gtp = move_infos[0].get("move", "pass")
            if best_gtp == "pass":
                return Move(None, player=self.cn.next_player), "Fallback: pass."
            return Move.from_gtp(best_gtp, player=self.cn.next_player), "Fallback: best AI move."

        # 候補が ≤3 手の場合は divergence を無効化（humanPolicy のみで選択）
        # → 「ほぼ1択」局面でも自然な手を打てる
        if len(candidates) <= 3:
            self.game.katrain.log(
                f"[DivergenceStrategy] ≤3 candidates, disabling divergence (humanPolicy only)",
                OUTPUT_DEBUG,
            )
            weighted_moves = [(m, hp) for m, _, hp, _, _ in candidates]
        else:
            weighted_moves = [(m, div_score) for m, div_score, _, _, _ in candidates]

        # 重み付き確率選択（weighted_selection_without_replacement は item[1] を重みとして使用）
        selected = weighted_selection_without_replacement(weighted_moves, 1)[0]
        move = selected[0]

        top5_sorted = sorted(candidates, key=lambda c: -c[1])[:5]
        top5_str = "\n".join(
            f"#{j+1}: {m.gtp()} (div={ds:.4f}, hp={hp:.3f}, order={ord_}, loss={ls:.2f})"
            for j, (m, ds, hp, ord_, ls) in enumerate(top5_sorted)
        )
        chosen_order = next(
            (ord_ for m2, _, _, ord_, _ in candidates if m2.gtp() == move.gtp()), "?"
        )
        ai_thoughts = (
            f"\n{top5_str}\n\n"
            f"DivergenceStrategy: played {move.gtp()} "
            f"(power={divergence_power}, filter={score_filter}, AI_order={chosen_order})"
        )

        self.game.katrain.log(
            f"[DivergenceStrategy] Selected {move.gtp()} (AI order={chosen_order})",
            OUTPUT_DEBUG,
        )
        return move, ai_thoughts


@register_strategy(AI_SIEGE)
class SiegeStrategy(AIStrategy):
    """攻城戦略 — 序盤は地を譲り、中盤以降に大石を攻めて逆転を狙う"""

    BOARD_PARAMS = {
        19: {"transition_move": 40, "min_group_size": 5, "concede_max_loss": 4.0, "max_loss": 5.0, "proximity_stddev": 3.0},
        13: {"transition_move": 25, "min_group_size": 4, "concede_max_loss": 3.0, "max_loss": 4.0, "proximity_stddev": 2.5},
    }

    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[SiegeStrategy] Starting move generation", OUTPUT_DEBUG)

        self.wait_for_analysis()

        board_size = self.game.board_size
        bx = board_size[0]
        params = self.BOARD_PARAMS.get(bx, self.BOARD_PARAMS[19])

        transition_move = self.settings.get("siege_transition_move", params["transition_move"])
        min_group_size = self.settings.get("siege_min_group_size", params["min_group_size"])
        concede_max_loss = self.settings.get("concede_max_loss", params["concede_max_loss"])
        max_loss = self.settings.get("siege_max_loss", params["max_loss"])
        proximity_stddev = self.settings.get("siege_proximity_stddev", params["proximity_stddev"])
        instability_min = self.settings.get("siege_instability_min", 0.3)

        self.game.katrain.log(
            f"[SiegeStrategy] Settings: transition={transition_move}, min_group={min_group_size}, "
            f"concede_loss={concede_max_loss}, max_loss={max_loss}, prox_std={proximity_stddev}, instab_min={instability_min}",
            OUTPUT_DEBUG,
        )

        # --- Stage 1: humanSLProfile付きクエリ（9段固定） ---
        human_profile = "rank_9d"
        override_settings = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 800,
        }
        self.game.katrain.log(f"[SiegeStrategy] Stage 1: requesting humanSL analysis ({human_profile})", OUTPUT_DEBUG)

        analysis = None
        error = False

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[SiegeStrategy] Error in Stage 1: {a}", OUTPUT_ERROR)

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
            self.game.katrain.log(f"[SiegeStrategy] Stage 1 failed, falling back to standard policy", OUTPUT_DEBUG)
            candidate_moves = self.cn.candidate_moves
            if not candidate_moves:
                return Move(None, player=self.cn.next_player), "No candidate moves found, passing."
            top_move = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
            if top_move.is_pass:
                return top_move, "Top move is pass."
            current_move = self.cn.depth
            total_moves = bx * board_size[1]
            force_transition = current_move >= int(total_moves * 0.6)
            targets = find_targets(self.game, self.cn, min_group_size, instability_min)
            has_target = len(targets) > 0
            in_attack_phase = (current_move >= transition_move and has_target) or force_transition
            if in_attack_phase:
                return self._generate_attack_fallback(candidate_moves, targets, max_loss, proximity_stddev)
            else:
                return self._generate_concede_fallback(candidate_moves, concede_max_loss)

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
            self.game.katrain.log(f"[SiegeStrategy] Error in Stage 2: {a}", OUTPUT_ERROR)

        self.game.katrain.log(f"[SiegeStrategy] Stage 2: requesting clean analysis", OUTPUT_DEBUG)
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

        if clean_analysis and not clean_error:
            move_infos = clean_analysis.get("moveInfos", [])
            self.game.katrain.log(f"[SiegeStrategy] Using clean moveInfos ({len(move_infos)} moves)", OUTPUT_DEBUG)
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log(f"[SiegeStrategy] Clean query failed, using Stage 1 moveInfos", OUTPUT_DEBUG)

        # --- スコア計算の前処理 ---
        player_sign = 1 if self.cn.next_player == "B" else -1
        best_score = None
        best_gtp_by_score = None
        if move_infos:
            best_score = max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
            best_gtp_by_score = max(
                move_infos, key=lambda mi: mi.get("scoreLead", 0) * player_sign
            ).get("move", "")

            if best_gtp_by_score == "pass":
                self.game.katrain.log(f"[SiegeStrategy] Best move is pass, forcing pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."

        # area scoringルール判定
        _ruleset = self.cn.ruleset
        _rules = KataGoEngine.get_rules(_ruleset)
        is_area_scoring = (
            (isinstance(_rules, str) and _rules.lower() in ["chinese", "aga", "tromp-taylor", "new zealand", "stone_scoring"])
            or (isinstance(_rules, dict) and _rules.get("scoring", "").lower() == "area")
        )

        current_move = self.cn.depth
        total_moves = bx * board_size[1]
        force_transition = current_move >= int(total_moves * 0.6)

        targets = find_targets(self.game, self.cn, min_group_size, instability_min)
        has_target = len(targets) > 0
        in_attack_phase = (current_move >= transition_move and has_target) or force_transition

        if in_attack_phase:
            phase = "attack (forced)" if force_transition and not has_target else "attack"
            self.game.katrain.log(f"[SiegeStrategy] Phase: {phase}, move={current_move}, targets={len(targets)}", OUTPUT_DEBUG)
            return self._generate_attack(
                human_policy, move_infos, targets, max_loss, proximity_stddev,
                player_sign, best_score, best_gtp_by_score, is_area_scoring,
            )
        else:
            self.game.katrain.log(f"[SiegeStrategy] Phase: concede, move={current_move}", OUTPUT_DEBUG)
            return self._generate_concede(
                human_policy, move_infos, concede_max_loss,
                player_sign, best_score, best_gtp_by_score, is_area_scoring,
            )

    def _generate_concede(self, human_policy, move_infos, concede_max_loss,
                          player_sign, best_score, best_gtp_by_score, is_area_scoring):
        """序盤フェーズ: humanPolicy × concede_score で地を譲る手を選択する。"""
        board_size = self.game.board_size
        bx, by = board_size

        # --- Stage 2 moveInfosで悪手フィルタ ---
        good_moves = set()
        if move_infos and best_score is not None:
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss <= concede_max_loss:
                    good_moves.add(gtp_move)

            self.game.katrain.log(
                f"[SiegeStrategy:concede] {len(good_moves)} moves pass score filter out of {len(move_infos)} "
                f"(threshold={concede_max_loss})",
                OUTPUT_DEBUG,
            )

        # --- スコア情報をdict化 ---
        score_by_gtp = {}
        if move_infos:
            for mi in move_infos:
                score_by_gtp[mi.get("move", "")] = mi.get("scoreLead", 0)

        # --- humanPolicy × concede_score で候補構築 ---
        has_filter = len(good_moves) > 0
        moves = []
        filtered_count = 0
        for x in range(bx):
            for y in range(by):
                idx = (by - y - 1) * bx + x
                if idx < len(human_policy) and human_policy[idx] > 0:
                    m = Move((x, y), player=self.cn.next_player)
                    if has_filter and m.gtp() not in good_moves:
                        filtered_count += 1
                        continue

                    hp_weight = human_policy[idx]

                    # concede_score: 損失が大きいほど高い重み（地を譲る手を優先）
                    gtp = m.gtp()
                    if gtp in score_by_gtp and best_score is not None:
                        score = score_by_gtp[gtp]
                        loss = player_sign * (best_score - score)
                        concede_score = min(max(loss, 0), concede_max_loss) / concede_max_loss
                        concede_score = max(concede_score, 0.05)
                    else:
                        concede_score = 0.5  # スコア不明の手はデフォルト中間値

                    weight = hp_weight * concede_score
                    moves.append((m, weight))

        # passが候補に含まれるか確認
        pass_idx = bx * by
        if pass_idx < len(human_policy) and human_policy[pass_idx] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[pass_idx]))

        self.game.katrain.log(
            f"[SiegeStrategy:concede] {len(moves)} candidate moves ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )

        # フォールバック
        if not moves:
            self.game.katrain.log(f"[SiegeStrategy:concede] No valid moves, playing best move", OUTPUT_DEBUG)
            if best_gtp_by_score and best_gtp_by_score != "pass":
                return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), "Concede fallback: no valid moves."
            if move_infos:
                fb = move_infos[0].get("move", "pass")
                if fb == "pass":
                    return Move(None, player=self.cn.next_player), "Concede fallback: pass."
                return Move.from_gtp(fb, player=self.cn.next_player), "Concede fallback: best search move."
            return Move(None, player=self.cn.next_player), "Concede fallback: no moves."

        # --- pass処理（area scoring） ---
        if any(m.is_pass for m, _ in moves):
            if is_area_scoring:
                _AREA_PASS_MARGIN = 0.5
                pass_mi = next((mi for mi in (move_infos or []) if mi.get("move") == "pass"), None)
                if pass_mi is not None and best_score is not None:
                    pass_loss = player_sign * (best_score - pass_mi.get("scoreLead", best_score))
                    if pass_loss < _AREA_PASS_MARGIN:
                        self.game.katrain.log(
                            f"[SiegeStrategy:concede] Area scoring: pass near-optimal (loss={pass_loss:.2f}), forcing pass",
                            OUTPUT_DEBUG,
                        )
                        return Move(None, player=self.cn.next_player), "Area scoring: pass near-optimal, forcing pass."
                moves_no_pass = [(m, w) for m, w in moves if not m.is_pass]
                if moves_no_pass:
                    moves = moves_no_pass
                else:
                    if best_gtp_by_score and best_gtp_by_score != "pass":
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), \
                            "Area scoring: playing best non-pass move."
                    return Move(None, player=self.cn.next_player), "Area scoring: no non-pass candidates."
            else:
                return Move(None, player=self.cn.next_player), "Pass is in candidates, forcing pass."

        # --- 安全弁: 最高重み候補のlossが閾値以上なら最善スコア手に強制切替 ---
        _SAFETY_LOSS_THRESHOLD = 4.0
        if moves and move_infos and best_gtp_by_score:
            top_move_candidate, _ = max(moves, key=lambda x: x[1])
            top_gtp = top_move_candidate.gtp()
            if top_gtp in score_by_gtp and top_gtp != best_gtp_by_score:
                top_loss = player_sign * (best_score - score_by_gtp[top_gtp])
                if top_loss >= _SAFETY_LOSS_THRESHOLD:
                    self.game.katrain.log(
                        f"[SiegeStrategy:concede] Safety valve: top weighted {top_gtp} "
                        f"loss={top_loss:.2f} >= {_SAFETY_LOSS_THRESHOLD}, "
                        f"forcing best-score move {best_gtp_by_score}",
                        OUTPUT_DEBUG,
                    )
                    if best_gtp_by_score == "pass":
                        return Move(None, player=self.cn.next_player), "Safety valve: best move is pass."
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                        f"Safety valve: top weighted {top_gtp} had loss={top_loss:.2f}, "
                        f"forced best-score move {best_gtp_by_score}."
                    )

        # --- エンドゲーム: 戦略重みを無視してtop humanPolicy ---
        endgame_threshold = 32 if (bx == 9 and by == 9) else math.ceil(bx * by * 0.5)
        current_move = self.cn.depth
        if current_move >= endgame_threshold:
            endgame_moves = []
            for x in range(bx):
                for y in range(by):
                    idx = (by - y - 1) * bx + x
                    if idx < len(human_policy) and human_policy[idx] > 0:
                        m = Move((x, y), player=self.cn.next_player)
                        if not has_filter or m.gtp() in good_moves:
                            endgame_moves.append((m, human_policy[idx]))
            if endgame_moves:
                top_move = max(endgame_moves, key=lambda x: x[1])
                self.game.katrain.log(
                    f"[SiegeStrategy:concede] Endgame: playing top humanPolicy move {top_move[0].gtp()}",
                    OUTPUT_DEBUG,
                )
                return top_move[0], f"Endgame: played top humanPolicy move {top_move[0].gtp()}."

        # --- タイブレーク ---
        _TIEBREAK_WEIGHT_RATIO = 1.05
        _TIEBREAK_SCORE_DIFF = 2.0
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
        if len(top5) >= 2 and move_infos:
            _score_by_gtp_tb = {mi.get("move", ""): mi.get("scoreLead", 0) * player_sign for mi in move_infos}
            _visits_by_gtp = {mi.get("move", ""): mi.get("visits", 0) for mi in move_infos}
            top1_move, top1_w = top5[0]
            top2_move, top2_w = top5[1]
            top1_visits = _visits_by_gtp.get(top1_move.gtp(), 0)
            top2_visits = _visits_by_gtp.get(top2_move.gtp(), 0)
            is_policy_close = top2_w > 0 and top1_w / top2_w < _TIEBREAK_WEIGHT_RATIO
            is_visits_reversal = top2_visits > top1_visits * 2.0
            is_mcts_nonprefer = top1_visits > 0 and top2_visits >= top1_visits
            if is_policy_close or is_visits_reversal or is_mcts_nonprefer:
                s1 = _score_by_gtp_tb.get(top1_move.gtp())
                s2 = _score_by_gtp_tb.get(top2_move.gtp())
                if s1 is not None and s2 is not None and abs(s1 - s2) >= _TIEBREAK_SCORE_DIFF:
                    winner = top1_move if s1 > s2 else top2_move
                    loser = top2_move if s1 > s2 else top1_move
                    trigger = "policy" if is_policy_close else ("visits_reversal" if is_visits_reversal else "mcts_nonprefer")
                    self.game.katrain.log(
                        f"[SiegeStrategy:concede] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt)",
                        OUTPUT_DEBUG,
                    )
                    return winner, f"Siege[concede] tiebreak({trigger}): played {winner.gtp()} (score diff={abs(s1-s2):.1f}pt)."

        # --- デバッグ: 上位5手表示 ---
        top_str = "\n".join([f"#{i+1}: {m.gtp()} weight={w:.4f}" for i, (m, w) in enumerate(top5)])
        self.game.katrain.log(f"[SiegeStrategy:concede] Top 5:\n{top_str}", OUTPUT_DEBUG)

        # --- 重み付き選択 ---
        selected = weighted_selection_without_replacement(moves, 1)[0]
        aimove = selected[0]
        ai_thoughts = (
            f"Siege[concede]: {len(moves)} candidates within {concede_max_loss}pt. "
            f"Selected {aimove.gtp()} (weight={selected[1]:.4f}). ({filtered_count} filtered)"
        )
        self.game.katrain.log(f"[SiegeStrategy:concede] Selected: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

    def _generate_concede_fallback(self, candidate_moves, concede_max_loss):
        """序盤フェーズ: 最善手を避けつつ地を譲る手を選択する。"""
        player_sign = 1 if self.cn.next_player == "B" else -1
        best_score = max(player_sign * mi["scoreLead"] for mi in candidate_moves)

        policy = self.cn.policy
        board_size = self.game.board_size
        policy_grid = var_to_grid(policy, board_size) if policy else None

        weighted_moves = []
        for mi in candidate_moves:
            gtp_move = mi.get("move", "")
            if gtp_move == "pass":
                continue
            score = mi.get("scoreLead", 0)
            loss = player_sign * (best_score - player_sign * score)

            if loss > concede_max_loss:
                continue

            move = Move.from_gtp(gtp_move, player=self.cn.next_player)
            if move.coords is None:
                continue

            x, y = move.coords
            if policy_grid:
                pol = policy_grid[y][x]
            else:
                pol = mi.get("prior", 0.01)
            pol = max(pol, 1e-6)

            concede_score = min(loss, concede_max_loss) / concede_max_loss
            concede_score = max(concede_score, 0.05)

            weight = pol * concede_score
            weighted_moves.append((loss, weight, move))

        if not weighted_moves:
            self.game.katrain.log(f"[SiegeStrategy:concede] No valid moves, playing best move", OUTPUT_DEBUG)
            return Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player), "Concede fallback: no valid moves."

        top5 = heapq.nlargest(5, weighted_moves, key=lambda t: t[1])
        self.game.katrain.log(f"[SiegeStrategy:concede] Top 5 weighted moves:", OUTPUT_DEBUG)
        for i, (l, w, m) in enumerate(top5):
            self.game.katrain.log(f"  #{i+1}: {m.gtp()} loss={l:.2f} weight={w:.4f}", OUTPUT_DEBUG)

        selected = weighted_selection_without_replacement(weighted_moves, 1)[0]
        aimove = selected[2]
        ai_thoughts = (
            f"Siege[concede]: {len(weighted_moves)} candidates within {concede_max_loss}pt. "
            f"Selected {aimove.gtp()} (loss={selected[0]:.1f})."
        )
        self.game.katrain.log(f"[SiegeStrategy:concede] Selected: {aimove.gtp()} loss={selected[0]:.2f}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

    def _generate_attack(self, human_policy, move_infos, targets, max_loss, proximity_stddev,
                         player_sign, best_score, best_gtp_by_score, is_area_scoring):
        """攻撃フェーズ: humanPolicy × proximity × instability で着手選択する。"""
        board_size = self.game.board_size
        bx, by = board_size
        prox_var = proximity_stddev ** 2

        # ターゲット情報
        if targets:
            primary_target = targets[0]
            target_instability = primary_target[1]
            target_coords = primary_target[2]
            if len(targets) > 1:
                target_coords = target_coords | targets[1][2]
        else:
            target_instability = 0.5
            target_coords = set()
            for s in self.game.stones:
                if s.player != self.cn.next_player and s.coords:
                    target_coords.add(s.coords)
            if not target_coords:
                if best_gtp_by_score and best_gtp_by_score != "pass":
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), "Attack: no opponent stones."
                return Move(None, player=self.cn.next_player), "Attack: no opponent stones, passing."

        # --- Stage 2 moveInfosで悪手フィルタ ---
        good_moves = set()
        if move_infos and best_score is not None:
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss <= max_loss:
                    good_moves.add(gtp_move)

            self.game.katrain.log(
                f"[SiegeStrategy:attack] {len(good_moves)} moves pass score filter out of {len(move_infos)} "
                f"(threshold={max_loss})",
                OUTPUT_DEBUG,
            )

        # --- スコア情報をdict化 ---
        score_by_gtp = {}
        if move_infos:
            for mi in move_infos:
                score_by_gtp[mi.get("move", "")] = mi.get("scoreLead", 0)

        # --- humanPolicy × proximity × instability で候補構築 ---
        has_filter = len(good_moves) > 0
        moves = []
        filtered_count = 0
        for x in range(bx):
            for y in range(by):
                idx = (by - y - 1) * bx + x
                if idx < len(human_policy) and human_policy[idx] > 0:
                    m = Move((x, y), player=self.cn.next_player)
                    if has_filter and m.gtp() not in good_moves:
                        filtered_count += 1
                        continue

                    hp_weight = human_policy[idx]

                    # ターゲットへの近接度
                    min_dist_sq = min((x - tx) ** 2 + (y - ty) ** 2 for tx, ty in target_coords)
                    proximity = math.exp(-0.5 * min_dist_sq / prox_var) if prox_var > 0 else 1.0

                    weight = hp_weight * proximity * target_instability
                    moves.append((m, weight))

        # passが候補に含まれるか確認
        pass_idx = bx * by
        if pass_idx < len(human_policy) and human_policy[pass_idx] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[pass_idx]))

        self.game.katrain.log(
            f"[SiegeStrategy:attack] Targets: {len(targets)}, candidates: {len(moves)} ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )

        # フォールバック
        if not moves:
            self.game.katrain.log(f"[SiegeStrategy:attack] No valid moves within {max_loss}pt, playing best", OUTPUT_DEBUG)
            if best_gtp_by_score and best_gtp_by_score != "pass":
                return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), "Attack fallback: no moves within threshold."
            if move_infos:
                fb = move_infos[0].get("move", "pass")
                if fb == "pass":
                    return Move(None, player=self.cn.next_player), "Attack fallback: pass."
                return Move.from_gtp(fb, player=self.cn.next_player), "Attack fallback: best search move."
            return Move(None, player=self.cn.next_player), "Attack fallback: no moves."

        # --- pass処理（area scoring） ---
        if any(m.is_pass for m, _ in moves):
            if is_area_scoring:
                _AREA_PASS_MARGIN = 0.5
                pass_mi = next((mi for mi in (move_infos or []) if mi.get("move") == "pass"), None)
                if pass_mi is not None and best_score is not None:
                    pass_loss = player_sign * (best_score - pass_mi.get("scoreLead", best_score))
                    if pass_loss < _AREA_PASS_MARGIN:
                        self.game.katrain.log(
                            f"[SiegeStrategy:attack] Area scoring: pass near-optimal (loss={pass_loss:.2f}), forcing pass",
                            OUTPUT_DEBUG,
                        )
                        return Move(None, player=self.cn.next_player), "Area scoring: pass near-optimal, forcing pass."
                moves_no_pass = [(m, w) for m, w in moves if not m.is_pass]
                if moves_no_pass:
                    moves = moves_no_pass
                else:
                    if best_gtp_by_score and best_gtp_by_score != "pass":
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), \
                            "Area scoring: playing best non-pass move."
                    return Move(None, player=self.cn.next_player), "Area scoring: no non-pass candidates."
            else:
                return Move(None, player=self.cn.next_player), "Pass is in candidates, forcing pass."

        # --- 安全弁: 最高重み候補のlossが閾値以上なら最善スコア手に強制切替 ---
        _SAFETY_LOSS_THRESHOLD = 4.0
        if moves and move_infos and best_gtp_by_score:
            top_move_candidate, _ = max(moves, key=lambda x: x[1])
            top_gtp = top_move_candidate.gtp()
            if top_gtp in score_by_gtp and top_gtp != best_gtp_by_score:
                top_loss = player_sign * (best_score - score_by_gtp[top_gtp])
                if top_loss >= _SAFETY_LOSS_THRESHOLD:
                    self.game.katrain.log(
                        f"[SiegeStrategy:attack] Safety valve: top weighted {top_gtp} "
                        f"loss={top_loss:.2f} >= {_SAFETY_LOSS_THRESHOLD}, "
                        f"forcing best-score move {best_gtp_by_score}",
                        OUTPUT_DEBUG,
                    )
                    if best_gtp_by_score == "pass":
                        return Move(None, player=self.cn.next_player), "Safety valve: best move is pass."
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                        f"Safety valve: top weighted {top_gtp} had loss={top_loss:.2f}, "
                        f"forced best-score move {best_gtp_by_score}."
                    )

        # --- エンドゲーム: 戦略重みを無視してtop humanPolicy ---
        endgame_threshold = 32 if (bx == 9 and by == 9) else math.ceil(bx * by * 0.5)
        current_move = self.cn.depth
        if current_move >= endgame_threshold:
            endgame_moves = []
            for x in range(bx):
                for y in range(by):
                    idx = (by - y - 1) * bx + x
                    if idx < len(human_policy) and human_policy[idx] > 0:
                        m = Move((x, y), player=self.cn.next_player)
                        if not has_filter or m.gtp() in good_moves:
                            endgame_moves.append((m, human_policy[idx]))
            if endgame_moves:
                top_move = max(endgame_moves, key=lambda x: x[1])
                self.game.katrain.log(
                    f"[SiegeStrategy:attack] Endgame: playing top humanPolicy move {top_move[0].gtp()}",
                    OUTPUT_DEBUG,
                )
                return top_move[0], f"Endgame: played top humanPolicy move {top_move[0].gtp()}."

        # --- タイブレーク ---
        _TIEBREAK_WEIGHT_RATIO = 1.05
        _TIEBREAK_SCORE_DIFF = 2.0
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
        if len(top5) >= 2 and move_infos:
            _score_by_gtp_tb = {mi.get("move", ""): mi.get("scoreLead", 0) * player_sign for mi in move_infos}
            _visits_by_gtp = {mi.get("move", ""): mi.get("visits", 0) for mi in move_infos}
            top1_move, top1_w = top5[0]
            top2_move, top2_w = top5[1]
            top1_visits = _visits_by_gtp.get(top1_move.gtp(), 0)
            top2_visits = _visits_by_gtp.get(top2_move.gtp(), 0)
            is_policy_close = top2_w > 0 and top1_w / top2_w < _TIEBREAK_WEIGHT_RATIO
            is_visits_reversal = top2_visits > top1_visits * 2.0
            is_mcts_nonprefer = top1_visits > 0 and top2_visits >= top1_visits
            if is_policy_close or is_visits_reversal or is_mcts_nonprefer:
                s1 = _score_by_gtp_tb.get(top1_move.gtp())
                s2 = _score_by_gtp_tb.get(top2_move.gtp())
                if s1 is not None and s2 is not None and abs(s1 - s2) >= _TIEBREAK_SCORE_DIFF:
                    winner = top1_move if s1 > s2 else top2_move
                    loser = top2_move if s1 > s2 else top1_move
                    trigger = "policy" if is_policy_close else ("visits_reversal" if is_visits_reversal else "mcts_nonprefer")
                    self.game.katrain.log(
                        f"[SiegeStrategy:attack] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt)",
                        OUTPUT_DEBUG,
                    )
                    return winner, (
                        f"Siege[attack] tiebreak({trigger}): played {winner.gtp()} (score diff={abs(s1-s2):.1f}pt). "
                        f"({filtered_count} filtered)"
                    )

        # --- デバッグ: 上位5手表示 ---
        top_str = "\n".join([f"#{i+1}: {m.gtp()} weight={w:.4f}" for i, (m, w) in enumerate(top5)])
        self.game.katrain.log(f"[SiegeStrategy:attack] Top 5:\n{top_str}", OUTPUT_DEBUG)

        # --- 重み付き選択 ---
        selected = weighted_selection_without_replacement(moves, 1)[0]
        aimove = selected[0]
        target_info = f"primary_size={len(targets[0][2])}" if targets else "pressure_mode"
        ai_thoughts = (
            f"Siege[attack]: {target_info}, {len(moves)} candidates within {max_loss}pt. "
            f"Selected {aimove.gtp()} (weight={selected[1]:.4f}). ({filtered_count} filtered)"
        )
        self.game.katrain.log(f"[SiegeStrategy:attack] Selected: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

    def _generate_attack_fallback(self, candidate_moves, targets, max_loss, proximity_stddev):
        """攻撃フェーズ: ターゲットの大石群に近い手を重み付けして選択する。"""
        player_sign = 1 if self.cn.next_player == "B" else -1
        best_score = max(player_sign * mi["scoreLead"] for mi in candidate_moves)
        board_size = self.game.board_size
        prox_var = proximity_stddev ** 2

        policy = self.cn.policy
        policy_grid = var_to_grid(policy, board_size) if policy else None

        if targets:
            primary_target = targets[0]
            target_instability = primary_target[1]
            target_coords = primary_target[2]
            if len(targets) > 1:
                target_coords = target_coords | targets[1][2]
        else:
            target_instability = 0.5
            target_coords = set()
            for s in self.game.stones:
                if s.player != self.cn.next_player and s.coords:
                    target_coords.add(s.coords)
            if not target_coords:
                return Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player), "Attack: no opponent stones."

        weighted_moves = []
        for mi in candidate_moves:
            gtp_move = mi.get("move", "")
            if gtp_move == "pass":
                continue

            score = mi.get("scoreLead", 0)
            loss = player_sign * (best_score - player_sign * score)

            if loss > max_loss:
                continue

            move = Move.from_gtp(gtp_move, player=self.cn.next_player)
            if move.coords is None:
                continue

            mx, my = move.coords

            if policy_grid:
                pol = policy_grid[my][mx]
            else:
                pol = mi.get("prior", 0.01)
            pol = max(pol, 1e-6)

            min_dist_sq = min((mx - tx) ** 2 + (my - ty) ** 2 for tx, ty in target_coords)
            proximity = math.exp(-0.5 * min_dist_sq / prox_var) if prox_var > 0 else 1.0

            weight = pol * proximity * target_instability
            weighted_moves.append((loss, weight, move))

        if not weighted_moves:
            self.game.katrain.log(f"[SiegeStrategy:attack] No valid moves within {max_loss}pt, playing best", OUTPUT_DEBUG)
            return Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player), "Attack fallback: no moves within threshold."

        top5 = heapq.nlargest(5, weighted_moves, key=lambda t: t[1])
        self.game.katrain.log(f"[SiegeStrategy:attack] Targets: {len(targets)}, candidates: {len(weighted_moves)}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[SiegeStrategy:attack] Top 5 weighted moves:", OUTPUT_DEBUG)
        for i, (l, w, m) in enumerate(top5):
            self.game.katrain.log(f"  #{i+1}: {m.gtp()} loss={l:.2f} weight={w:.4f}", OUTPUT_DEBUG)

        selected = weighted_selection_without_replacement(weighted_moves, 1)[0]
        aimove = selected[2]
        target_info = f"primary_size={len(targets[0][2])}" if targets else "pressure_mode"
        ai_thoughts = (
            f"Siege[attack]: {target_info}, {len(weighted_moves)} candidates within {max_loss}pt. "
            f"Selected {aimove.gtp()} (loss={selected[0]:.1f}, weight={selected[1]:.4f})."
        )
        self.game.katrain.log(f"[SiegeStrategy:attack] Selected: {aimove.gtp()} loss={selected[0]:.2f}", OUTPUT_DEBUG)
        return aimove, ai_thoughts


@register_strategy(AI_HUNT)
class HuntStrategy(AIStrategy):
    """狩猟戦略 — 弱い石群を見つけて集中攻撃する"""

    def _try_tiebreak(self, top5, move_infos, player_sign, filtered_count, top_str):
        """タイブレーク判定。発動した場合は (Move, ai_thoughts) を返し、しなければ None を返す。"""
        _TIEBREAK_WEIGHT_RATIO = 1.05
        _TIEBREAK_VISITS_REVERSAL_RATIO = 2.0
        _TIEBREAK_SCORE_DIFF = 2.0
        if len(top5) >= 2 and move_infos:
            _score_by_gtp = {mi.get("move", ""): mi.get("scoreLead", 0) * player_sign for mi in move_infos}
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
                        f"[{self.__class__.__name__}] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt, "
                        f"policy_ratio={top1_w/top2_w:.3f}, visits={top1_visits}/{top2_visits})",
                        OUTPUT_DEBUG,
                    )
                    return winner, (
                        f"\n{top_str}\n\nScore tiebreak({trigger}): played {winner.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt). ({filtered_count} filtered)"
                    )
        return None

    def _select_final_move(self, moves, phase_name, move_infos, best_score,
                           best_gtp_by_score, player_sign, hunt_max_loss,
                           filtered_count, top_str, human_policy):
        """最終的な手の選択。子クラスでオーバーライド可能。"""
        hunt_invasion_temperature = self.settings.get("hunt_invasion_temperature", 1.5)

        # 重み付き選択（Invadeフェーズは温度で分布を平坦化）
        if phase_name == "Invade" and hunt_invasion_temperature != 1.0:
            inv_temp = 1.0 / hunt_invasion_temperature
            temp_moves = [(m, w ** inv_temp) for m, w in moves]
            selected = weighted_selection_without_replacement(temp_moves, 1)[0]
            # 温度選択後の安全チェック
            if move_infos and best_gtp_by_score:
                _sel_gtp = selected[0].gtp()
                _pt_score_map = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
                if _sel_gtp in _pt_score_map and _sel_gtp != best_gtp_by_score:
                    _sel_loss = player_sign * (best_score - _pt_score_map[_sel_gtp])
                    if _sel_loss >= hunt_max_loss:
                        _top_w_move = max(moves, key=lambda x: x[1])[0]
                        self.game.katrain.log(
                            f"[{self.__class__.__name__}] Post-temp safety: {_sel_gtp} loss={_sel_loss:.2f} >= {hunt_max_loss}, "
                            f"fallback to top weighted {_top_w_move.gtp()}",
                            OUTPUT_DEBUG,
                        )
                        selected = (_top_w_move, 0)
        else:
            selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]
        self.game.katrain.log(f"[{self.__class__.__name__}] Selected: {move.gtp()} ({phase_name})", OUTPUT_DEBUG)

        ai_thoughts = (
            f"\n{top_str}\n\n{phase_name}: played {move.gtp()} "
            f"({filtered_count} bad moves filtered)"
        )
        return move, ai_thoughts

    def generate_move(self) -> Tuple[Move, str]:
        board_size = self.game.board_size
        bx, by = board_size

        # 9路非対応
        if bx == 9 and by == 9:
            self.game.katrain.log(
                "[HuntStrategy] Not supported on 9x9, playing as default",
                OUTPUT_DEBUG,
            )
            return Move(None, player=self.cn.next_player), "Hunt not supported on 9x9."

        # 盤面サイズ別デフォルト
        if bx <= 13:
            default_max_loss = 4.0
            default_min_group = 4
            default_prox_stddev = 2.5
            default_invasion_max_loss = 6.0
            default_invasion_prox_stddev = 3.0
            default_focus_stddev = 5.0
        else:
            default_max_loss = 6.0
            default_min_group = 5
            default_prox_stddev = 3.0
            default_invasion_max_loss = 8.0
            default_invasion_prox_stddev = 3.0
            default_focus_stddev = 7.0

        hunt_max_loss = self.settings.get("hunt_max_loss", default_max_loss)
        hunt_min_group_size = self.settings.get("hunt_min_group_size", default_min_group)
        hunt_proximity_stddev = self.settings.get("hunt_proximity_stddev", default_prox_stddev)
        hunt_instability_min = self.settings.get("hunt_instability_min", 0.3)
        hunt_invasion_max_loss = self.settings.get("hunt_invasion_max_loss", default_invasion_max_loss)
        hunt_invasion_min = self.settings.get("hunt_invasion_min", 0.2)
        hunt_invasion_max = self.settings.get("hunt_invasion_max", 0.7)
        hunt_invasion_prox_stddev = self.settings.get("hunt_invasion_proximity_stddev", default_invasion_prox_stddev)
        hunt_invasion_temperature = self.settings.get("hunt_invasion_temperature", 1.5)
        hunt_focus_stddev = self.settings.get("hunt_focus_stddev", default_focus_stddev)
        hunt_pursue_enabled = self.settings.get("hunt_pursue_enabled", True)
        hunt_pursue_proximity = self.settings.get("hunt_pursue_proximity", 2)
        hunt_pursue_min_liberties = self.settings.get("hunt_pursue_min_liberties", 3)
        hunt_pursue_ownership_threshold = self.settings.get("hunt_pursue_ownership_threshold", 0.85)

        # スコア適応型損失制御の定数
        _LOSING_THRESHOLD = -6.0  # この値未満で劣勢と判定
        _LOSING_MAX_LOSS = 4.0    # 劣勢時の損失上限
        _WINNING_THRESHOLD = 15.0   # この値超で勝勢と判定
        _WINNING_SUPPRESS_FACTOR = 0.3  # 最善手のweight抑制係数
        hunt_winning_suppress = self.settings.get("hunt_winning_suppress_enabled", False)
        hunt_dead_stone_avoid = self.settings.get("hunt_dead_stone_avoid_enabled", True)

        self.game.katrain.log(
            f"[HuntStrategy] Starting move generation "
            f"(max_loss={hunt_max_loss}, min_group={hunt_min_group_size}, "
            f"prox_stddev={hunt_proximity_stddev}, instability_min={hunt_instability_min}, "
            f"inv_max_loss={hunt_invasion_max_loss}, inv_min={hunt_invasion_min}, "
            f"inv_max={hunt_invasion_max}, inv_prox_stddev={hunt_invasion_prox_stddev}, "
            f"inv_temperature={hunt_invasion_temperature}, focus_stddev={hunt_focus_stddev}, "
            f"pursue_enabled={hunt_pursue_enabled})",
            OUTPUT_DEBUG,
        )

        # 標準解析を待つ（ownership取得のため）
        self.wait_for_analysis()

        # --- Stage 1: humanSLProfile付きクエリ（9段固定） ---
        human_profile = "rank_9d"
        override_settings = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 800,
        }
        self.game.katrain.log(
            f"[HuntStrategy] Stage 1: requesting humanSL analysis ({human_profile})",
            OUTPUT_DEBUG,
        )

        analysis = None
        error = False

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[HuntStrategy] Error in Stage 1: {a}", OUTPUT_ERROR)

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
            self.game.katrain.log("[HuntStrategy] Stage 1 failed, passing", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "Stage 1 failed."

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
            self.game.katrain.log(f"[HuntStrategy] Error in Stage 2: {a}", OUTPUT_ERROR)

        self.game.katrain.log("[HuntStrategy] Stage 2: requesting clean analysis", OUTPUT_DEBUG)
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

        if clean_analysis and not clean_error:
            move_infos = clean_analysis.get("moveInfos", [])
            self.game.katrain.log(
                f"[HuntStrategy] Using clean moveInfos ({len(move_infos)} moves)", OUTPUT_DEBUG
            )
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log("[HuntStrategy] Clean query failed, using biased moveInfos", OUTPUT_DEBUG)

        # --- 基本情報 ---
        _ruleset = self.cn.ruleset
        _rules = KataGoEngine.get_rules(_ruleset)
        is_area_scoring = (
            (isinstance(_rules, str) and _rules.lower() in ["chinese", "aga", "tromp-taylor", "new zealand", "stone_scoring"])
            or (isinstance(_rules, dict) and _rules.get("scoring", "").lower() == "area")
        )

        player_sign = 1 if self.cn.next_player == "B" else -1
        current_move = self.cn.depth

        good_moves = set()
        best_gtp_by_score = None
        best_score = None

        if move_infos:
            best_score = max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
            best_gtp_by_score = max(
                move_infos, key=lambda mi: mi.get("scoreLead", 0) * player_sign
            ).get("move", "")

            if best_gtp_by_score == "pass":
                self.game.katrain.log("[HuntStrategy] Best move is pass, forcing pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."

            # --- 劣勢時の損失制限 ---
            score_lead = best_score * player_sign  # 正=自分が有利, 負=自分が不利
            if score_lead < _LOSING_THRESHOLD:
                original_hunt_max_loss = hunt_max_loss
                original_invasion_max_loss = hunt_invasion_max_loss
                hunt_max_loss = min(hunt_max_loss, _LOSING_MAX_LOSS)
                hunt_invasion_max_loss = min(hunt_invasion_max_loss, _LOSING_MAX_LOSS)
                self.game.katrain.log(
                    f"[HuntStrategy] Losing restrict: score_lead={score_lead:.1f}, "
                    f"max_loss {original_hunt_max_loss} -> {hunt_max_loss}, "
                    f"invasion_max_loss {original_invasion_max_loss} -> {hunt_invasion_max_loss}",
                    OUTPUT_DEBUG,
                )

            # --- 悪手フィルタ（hunt_max_loss 統一閾値） ---
            self.game.katrain.log(
                f"[HuntStrategy] Move {current_move}: threshold={hunt_max_loss}, best_score={best_score:.1f}",
                OUTPUT_DEBUG,
            )

            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss <= hunt_max_loss:
                    good_moves.add(gtp_move)

            total_candidates = len([mi for mi in move_infos if mi.get("move", "") != "pass"])
            self.game.katrain.log(
                f"[HuntStrategy] {len(good_moves)} moves pass score filter out of {total_candidates} "
                f"(threshold={hunt_max_loss})",
                OUTPUT_DEBUG,
            )

            # 段階的緩和
            if not good_moves:
                original_threshold = hunt_max_loss
                for relaxed in [hunt_max_loss * 1.5, hunt_max_loss * 2.0, 9.0]:
                    for mi in move_infos:
                        gtp_move = mi.get("move", "")
                        score = mi.get("scoreLead", 0)
                        loss = player_sign * (best_score - score)
                        if loss <= relaxed:
                            good_moves.add(gtp_move)
                    if good_moves:
                        self.game.katrain.log(
                            f"[HuntStrategy] Filter relaxed: threshold {original_threshold} -> {relaxed:.1f}, "
                            f"found {len(good_moves)} moves",
                            OUTPUT_DEBUG,
                        )
                        break

            # 最終フォールバック
            if not good_moves and best_gtp_by_score:
                good_moves.add(best_gtp_by_score)
                self.game.katrain.log(
                    f"[HuntStrategy] Filter failsafe: forcing best-score move {best_gtp_by_score}",
                    OUTPUT_DEBUG,
                )
                if best_gtp_by_score == "pass":
                    return Move(None, player=self.cn.next_player), "Filter failsafe: best move is pass."
                return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                    f"Filter failsafe: no moves within cap, forced {best_gtp_by_score}."
                )

            # --- 安全弁クロスバリデーション用ヘルパー ---
            def _safety_valve_cross_check(forced_gtp, candidate_gtp, p_sign, label="v1"):
                _CROSS_CHECK_MAX_LOSS = 2.0
                _reg_moves = self.cn.analysis.get("moves", {})
                _reg_forced = _reg_moves.get(forced_gtp)
                _reg_candidate = _reg_moves.get(candidate_gtp)
                if _reg_forced is None:
                    self.game.katrain.log(
                        f"[HuntStrategy] Safety {label}: {forced_gtp} not in regular analysis, skipping force",
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
                        f"[HuntStrategy] Safety {label} cross-check FAILED: "
                        f"{forced_gtp} loses {reg_loss:.2f}pt vs {candidate_gtp} in regular analysis",
                        OUTPUT_DEBUG,
                    )
                    return False
                return True

            # 安全弁v1
            _SAFETY_LOSS_THRESHOLD = 4.0
            max_visit_mi = max(move_infos, key=lambda mi: mi.get("visits", 0))
            max_visit_gtp = max_visit_mi.get("move", "")
            max_visit_score = max_visit_mi.get("scoreLead", 0)
            max_visit_loss = player_sign * (best_score - max_visit_score)
            if max_visit_loss >= _SAFETY_LOSS_THRESHOLD and best_gtp_by_score and best_gtp_by_score != max_visit_gtp:
                if _safety_valve_cross_check(best_gtp_by_score, max_visit_gtp, player_sign, "v1"):
                    self.game.katrain.log(
                        f"[HuntStrategy] Safety valve: max-visit move {max_visit_gtp} "
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

        # --- ターゲット検出 ---
        targets = find_targets(self.game, self.cn, hunt_min_group_size, hunt_instability_min)
        has_group_targets = len(targets) > 0

        # --- 攻め合い追撃判定 ---
        if hunt_pursue_enabled and not has_group_targets:
            if bx >= 19 and by >= 19:
                _endgame_threshold = int(self.settings.get("hunt_endgame_move", 200))
            else:
                _endgame_threshold = math.ceil(bx * by * 0.5)

            if current_move < _endgame_threshold:
                prev_node = self.cn.parent
                prev_prev_node = prev_node.parent if prev_node else None
                prev_targets = getattr(prev_prev_node, "hunt_previous_targets", None) if prev_prev_node else None

                if prev_targets and self.cn.move and self.cn.move.coords:
                    opponent_move_coords = self.cn.move.coords

                    current_opponent_coords = set()
                    for s in self.game.stones:
                        if s.player != self.cn.next_player and s.coords:
                            current_opponent_coords.add(s.coords)

                    _ownership = self.cn.ownership
                    _ownership_grid = var_to_grid(_ownership, board_size) if _ownership else None

                    pursuit_results = evaluate_pursuit_targets(
                        previous_targets=prev_targets,
                        opponent_move_coords=opponent_move_coords,
                        current_opponent_coords=current_opponent_coords,
                        board=self.game.board,
                        board_size=board_size,
                        ownership_grid=_ownership_grid,
                        player_sign=player_sign,
                        pursue_proximity=hunt_pursue_proximity,
                        pursue_min_liberties=hunt_pursue_min_liberties,
                        pursue_ownership_threshold=hunt_pursue_ownership_threshold,
                    )

                    if pursuit_results:
                        for score, instab, group in pursuit_results:
                            targets.append((score, instab, group))
                            liberties = count_group_liberties(self.game.board, group, board_size)
                            if _ownership_grid:
                                avg_own = sum(_ownership_grid[y][x] for x, y in group) / len(group)
                            else:
                                avg_own = 0.0
                            self.game.katrain.log(
                                f"[HuntStrategy] Pursue: opponent played "
                                f"[{Move(opponent_move_coords, player=self.cn.next_player).gtp()}] "
                                f"near previous target (size={len(group)}, liberties={liberties}, "
                                f"ownership={abs(avg_own):.2f}) → re-targeting",
                                OUTPUT_DEBUG,
                            )
                        targets.sort(key=lambda t: t[0], reverse=True)
                        has_group_targets = True
                    else:
                        for prev_target in prev_targets:
                            prev_coords = set(tuple(c) for c in prev_target["coords"])
                            ox, oy = opponent_move_coords
                            min_dist = min(
                                (max(abs(ox - cx), abs(oy - cy)) for cx, cy in prev_coords),
                                default=999,
                            )
                            if min_dist <= hunt_pursue_proximity:
                                self.game.katrain.log(
                                    f"[HuntStrategy] Pursue: opponent played "
                                    f"[{Move(opponent_move_coords, player=self.cn.next_player).gtp()}] "
                                    f"near previous target but stones confirmed dead → no pursuit",
                                    OUTPUT_DEBUG,
                                )

        # --- 侵入対象の検出（ownershipベース） ---
        # player_sign は 3585行付近で定義済み (1=Black, -1=White)
        invasion_coords = set()
        opp_strength_map = {}
        ownership = self.cn.ownership
        if ownership:
            ownership_grid = var_to_grid(ownership, board_size)
            for ix in range(bx):
                for iy in range(by):
                    own_val = ownership_grid[iy][ix] * player_sign
                    opp_strength = max(0.0, -own_val)
                    if hunt_invasion_min <= opp_strength <= hunt_invasion_max:
                        invasion_coords.add((ix, iy))
                        opp_strength_map[(ix, iy)] = opp_strength

        has_invasion = len(invasion_coords) > 0

        # グループターゲット座標の構築
        group_coords = set()
        target_instability = 0.0
        if has_group_targets:
            primary_target = targets[0]
            target_instability = primary_target[1]
            group_coords = set(primary_target[2])
            if len(targets) > 1:
                group_coords = group_coords | targets[1][2]

        # 統合ターゲット
        all_target_coords = invasion_coords | group_coords
        has_targets = len(all_target_coords) > 0

        # --- 注意フォーカスアンカーの算出 ---
        _FOCUS_FLOOR = 0.05
        focus_var = hunt_focus_stddev ** 2
        focus_anchors = []  # list of (x, y) anchor points

        if has_targets and hunt_focus_stddev > 0 and focus_var > 0:
            # (1) 直前着手の座標を取得
            if self.cn.move and self.cn.move.coords:
                focus_anchors.append(self.cn.move.coords)

            # (2) 最も不安定なターゲットの重心を取得
            if has_group_targets:
                primary_coords = targets[0][2]  # set of (x, y)
                if primary_coords:
                    uc_x = sum(c[0] for c in primary_coords) / len(primary_coords)
                    uc_y = sum(c[1] for c in primary_coords) / len(primary_coords)
                    focus_anchors.append((uc_x, uc_y))
            else:
                # Invadeフェーズ: opp_strength_mapで最大強度の侵入座標
                if opp_strength_map:
                    max_coord = max(opp_strength_map, key=opp_strength_map.get)
                    focus_anchors.append((float(max_coord[0]), float(max_coord[1])))

            if focus_anchors:
                anchor_strs = []
                for i, (ax, ay) in enumerate(focus_anchors):
                    if i == 0 and self.cn.move and self.cn.move.coords:
                        anchor_strs.append(f"last_move({Move(self.cn.move.coords, player=self.cn.next_player).gtp()})")
                    else:
                        anchor_strs.append(
                            f"unstable({'group' if has_group_targets else 'invasion'}"
                            f"({ax:.0f},{ay:.0f}))"
                        )
                self.game.katrain.log(
                    f"[HuntStrategy] Focus: anchors=[{','.join(anchor_strs)}] "
                    f"stddev={hunt_focus_stddev}",
                    OUTPUT_DEBUG,
                )

        # フェーズ判定とログ
        if has_group_targets:
            phase_name = "Hunt"
            self.game.katrain.log(
                f"[HuntStrategy] Phase: Hunt (invasion_targets={len(invasion_coords)}, "
                f"group_targets={len(targets)}, primary: size={len(targets[0][2])}, "
                f"instability={target_instability:.2f})",
                OUTPUT_DEBUG,
            )
        elif has_invasion:
            phase_name = "Invade"
            self.game.katrain.log(
                f"[HuntStrategy] Phase: Invade (invasion_targets={len(invasion_coords)}, "
                f"no group targets)",
                OUTPUT_DEBUG,
            )
        else:
            phase_name = "Hunt(9-dan)"
            self.game.katrain.log(
                "[HuntStrategy] Phase: No targets and no invasion, playing as 9-dan",
                OUTPUT_DEBUG,
            )

        # --- 侵入フェーズ時は悪手フィルタを再計算 ---
        if not has_group_targets and has_invasion and hunt_invasion_max_loss != hunt_max_loss:
            good_moves = set()
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss <= hunt_invasion_max_loss:
                    good_moves.add(gtp_move)
            total_candidates = len([mi for mi in move_infos if mi.get("move", "") != "pass"])
            self.game.katrain.log(
                f"[HuntStrategy] Invasion filter: {len(good_moves)} moves pass score filter "
                f"out of {total_candidates} (threshold={hunt_invasion_max_loss})",
                OUTPUT_DEBUG,
            )
            # 段階的緩和
            if not good_moves:
                for relaxed in [hunt_invasion_max_loss * 1.5, hunt_invasion_max_loss * 2.0, 9.0]:
                    for mi in move_infos:
                        gtp_move = mi.get("move", "")
                        score = mi.get("scoreLead", 0)
                        loss = player_sign * (best_score - score)
                        if loss <= relaxed:
                            good_moves.add(gtp_move)
                    if good_moves:
                        self.game.katrain.log(
                            f"[HuntStrategy] Invasion filter relaxed: "
                            f"threshold {hunt_invasion_max_loss} -> {relaxed:.1f}, "
                            f"found {len(good_moves)} moves",
                            OUTPUT_DEBUG,
                        )
                        break
            # 最終フォールバック
            if not good_moves and best_gtp_by_score:
                good_moves.add(best_gtp_by_score)

        # --- humanPolicy × proximity × intensity × territory_avoid で候補構築 ---
        prox_var = hunt_proximity_stddev ** 2
        inv_prox_var = hunt_invasion_prox_stddev ** 2
        has_ownership_grid = bool(ownership)
        moves = []
        filtered_count = 0
        has_filter = len(good_moves) > 0

        for x in range(bx):
            for y in range(by):
                idx = (by - y - 1) * bx + x
                if idx < len(human_policy) and human_policy[idx] > 0:
                    m = Move((x, y), player=self.cn.next_player)
                    if has_filter and m.gtp() not in good_moves:
                        filtered_count += 1
                    else:
                        hp_weight = human_policy[idx]

                        # 自陣回避ペナルティ: 自分の地ほど重みを下げる
                        if has_ownership_grid:
                            own_val = ownership_grid[y][x] * player_sign
                            territory_avoid = max(0.1, 1.0 - max(0.0, own_val))
                        else:
                            territory_avoid = 1.0

                        if has_targets:
                            # 最近接ターゲット座標を探し、由来で stddev を切替
                            min_dist_sq = float("inf")
                            nearest_type = None
                            nearest_coord = None
                            for tx, ty in all_target_coords:
                                dist_sq = (x - tx) ** 2 + (y - ty) ** 2
                                if dist_sq < min_dist_sq:
                                    min_dist_sq = dist_sq
                                    nearest_coord = (tx, ty)
                                    nearest_type = "group" if (tx, ty) in group_coords else "invasion"

                            if nearest_type == "group":
                                proximity = math.exp(-0.5 * min_dist_sq / prox_var)
                                intensity = target_instability
                            else:
                                proximity = math.exp(-0.5 * min_dist_sq / inv_prox_var)
                                intensity = opp_strength_map.get(nearest_coord, 0.3)

                            combined = hp_weight * proximity * intensity * territory_avoid
                        else:
                            combined = hp_weight * territory_avoid

                        # 注意フォーカスペナルティ（どちらかのアンカーに近ければOK）
                        if focus_anchors:
                            best_penalty = _FOCUS_FLOOR
                            for ax, ay in focus_anchors:
                                dist_sq = (x - ax) ** 2 + (y - ay) ** 2
                                penalty = math.exp(-0.5 * dist_sq / focus_var)
                                if penalty > best_penalty:
                                    best_penalty = penalty
                            combined *= best_penalty

                        moves.append((m, combined))

        # パス候補
        if len(human_policy) > bx * by and human_policy[-1] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[-1]))

        self.game.katrain.log(
            f"[HuntStrategy] {len(moves)} candidate moves ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )

        # --- 死石周辺の無駄手抑制 (Dead Stone Avoidance) ---
        if hunt_dead_stone_avoid and moves and move_infos and self.cn.ownership:
            _ownership_grid_dsa = var_to_grid(self.cn.ownership, board_size)
            _own_stone_coords_dsa = {
                s.coords for s in self.game.stones
                if s.player == self.cn.next_player and s.coords
            }
            _score_by_gtp_dsa = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
            _penalized_count = 0
            _evaluated_count = 0
            for i, (m, w) in enumerate(moves):
                gtp = m.gtp()
                if gtp not in _score_by_gtp_dsa or best_score is None:
                    continue
                _evaluated_count += 1
                loss_m = player_sign * (best_score - _score_by_gtp_dsa[gtp])
                if is_dead_zone_move(
                    move_coords=m.coords,
                    ownership_grid=_ownership_grid_dsa,
                    own_stone_coords=_own_stone_coords_dsa,
                    player_sign=player_sign,
                    loss=loss_m,
                    board_size=board_size,
                ):
                    own_val = (
                        _ownership_grid_dsa[m.coords[1]][m.coords[0]] * player_sign
                        if m.coords else 0.0
                    )
                    new_w = w * _DEAD_WEIGHT_FACTOR
                    moves[i] = (m, new_w)
                    _penalized_count += 1
                    self.game.katrain.log(
                        f"[HuntStrategy] Dead stone avoid: {gtp} "
                        f"(own={own_val:.2f}, loss={loss_m:.2f}) "
                        f"weight {w:.4f} -> {new_w:.4f}",
                        OUTPUT_DEBUG,
                    )
            if _penalized_count > 0:
                self.game.katrain.log(
                    f"[HuntStrategy] Dead stone avoid: {_penalized_count} moves penalized "
                    f"(evaluated {_evaluated_count}/{len(moves)} candidates)",
                    OUTPUT_DEBUG,
                )
        elif hunt_dead_stone_avoid and (not self.cn.ownership or not move_infos):
            self.game.katrain.log(
                "[HuntStrategy] Dead stone avoid: skipped (no ownership/move_infos data)",
                OUTPUT_DEBUG,
            )

        # --- 勝勢時の最善手weight抑制 ---
        if hunt_winning_suppress and moves and best_gtp_by_score and best_score is not None:
            score_lead_for_suppress = best_score * player_sign
            if score_lead_for_suppress > _WINNING_THRESHOLD:
                for i, (m, w) in enumerate(moves):
                    if m.gtp() == best_gtp_by_score:
                        original_w = w
                        suppressed_w = w * _WINNING_SUPPRESS_FACTOR
                        moves[i] = (m, suppressed_w)
                        self.game.katrain.log(
                            f"[HuntStrategy] Winning suppress: score_lead={score_lead_for_suppress:.1f}, "
                            f"best_move={best_gtp_by_score} weight {original_w:.4f} -> {suppressed_w:.4f}",
                            OUTPUT_DEBUG,
                        )
                        break

        # 安全弁v2
        _SAFETY_LOSS_THRESHOLD = 4.0
        if moves and move_infos and best_gtp_by_score:
            _score_by_gtp_v2 = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
            top_move_v2, _ = max(moves, key=lambda x: x[1])
            top_gtp_v2 = top_move_v2.gtp()
            if top_gtp_v2 in _score_by_gtp_v2 and top_gtp_v2 != best_gtp_by_score:
                top_loss_v2 = player_sign * (best_score - _score_by_gtp_v2[top_gtp_v2])
                self.game.katrain.log(
                    f"[HuntStrategy] Safety v2: top weighted move {top_gtp_v2} loss={top_loss_v2:.2f}",
                    OUTPUT_DEBUG,
                )
                if top_loss_v2 >= _SAFETY_LOSS_THRESHOLD:
                    if _safety_valve_cross_check(best_gtp_by_score, top_gtp_v2, player_sign, "v2"):
                        self.game.katrain.log(
                            f"[HuntStrategy] Safety valve v2: top weighted {top_gtp_v2} "
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
            self.game.katrain.log("[HuntStrategy] All moves filtered, using best search move", OUTPUT_DEBUG)
            if move_infos:
                best_gtp = best_gtp_by_score if best_gtp_by_score else move_infos[0].get("move", "pass")
                if best_gtp == "pass":
                    return Move(None, player=self.cn.next_player), "All moves filtered, playing best move."
                return Move.from_gtp(best_gtp, player=self.cn.next_player), "All moves filtered, playing best move."
            return Move(None, player=self.cn.next_player), "No valid moves found."

        # パス処理
        if any(m.is_pass for m, _ in moves):
            if is_area_scoring:
                _AREA_PASS_MARGIN = 0.5
                pass_mi = next((mi for mi in (move_infos or []) if mi.get("move") == "pass"), None)
                if pass_mi is not None:
                    pass_score_lead = pass_mi.get("scoreLead", best_score)
                    pass_loss = player_sign * (best_score - pass_score_lead)
                    if pass_loss < _AREA_PASS_MARGIN:
                        self.game.katrain.log(
                            f"[HuntStrategy] Area scoring: pass within {_AREA_PASS_MARGIN}pt of best "
                            f"(loss={pass_loss:.2f}), forcing pass",
                            OUTPUT_DEBUG,
                        )
                        return Move(None, player=self.cn.next_player), "Area scoring: pass near-optimal, forcing pass."
                moves_without_pass = [(m, w) for m, w in moves if not m.is_pass]
                if moves_without_pass:
                    moves = moves_without_pass
                    self.game.katrain.log("[HuntStrategy] Area scoring: pass removed from candidates", OUTPUT_DEBUG)
                else:
                    if best_gtp_by_score and best_gtp_by_score != "pass":
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), \
                            "Area scoring: playing best non-pass move."
                    return Move(None, player=self.cn.next_player), "Area scoring: no non-pass candidates."
            else:
                self.game.katrain.log("[HuntStrategy] Pass is among candidates, forcing pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "Pass is in candidates, forcing pass."

        # エンドゲーム: humanPolicy最上位手（ターゲット重み無視）
        if bx >= 19 and by >= 19:
            endgame_threshold = int(self.settings.get("hunt_endgame_move", 200))
        else:
            endgame_threshold = math.ceil(bx * by * 0.5)
        if current_move >= endgame_threshold:
            endgame_moves = []
            for x in range(bx):
                for y in range(by):
                    idx = (by - y - 1) * bx + x
                    if idx < len(human_policy) and human_policy[idx] > 0:
                        m = Move((x, y), player=self.cn.next_player)
                        if not has_filter or m.gtp() in good_moves:
                            endgame_moves.append((m, human_policy[idx]))
            if endgame_moves:
                top_move = max(endgame_moves, key=lambda x: x[1])
                self.game.katrain.log(
                    f"[HuntStrategy] Endgame: playing top humanPolicy move {top_move[0].gtp()}",
                    OUTPUT_DEBUG,
                )
                return top_move[0], f"Endgame: played top humanPolicy move {top_move[0].gtp()}."

        # --- ターゲット記憶保存 ---
        if hunt_pursue_enabled:
            self.cn.hunt_previous_targets = [
                {
                    "coords": list(group),
                    "size": len(group),
                }
                for _, _, group in targets
            ]

        # デバッグ: 上位5手表示
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
        top_str = "\n".join([f"#{i+1}: {m.gtp()} weight={w:.4f}" for i, (m, w) in enumerate(top5)])
        self.game.katrain.log(f"[{self.__class__.__name__}] Top 5:\n{top_str}", OUTPUT_DEBUG)

        # タイブレーク
        tiebreak_result = self._try_tiebreak(top5, move_infos, player_sign, filtered_count, top_str)
        if tiebreak_result:
            return tiebreak_result

        # 最終選択（子クラスでオーバーライド可能）
        return self._select_final_move(moves, phase_name, move_infos, best_score,
                                       best_gtp_by_score, player_sign, hunt_max_loss,
                                       filtered_count, top_str, human_policy)


@register_strategy(AI_HUNT_DIVERGE)
class HuntDivergenceStrategy(HuntStrategy):
    """狩猟戦略（一致率低減版） — HuntStrategyの棋風を維持しつつAI最善手一致率を低減する"""

    def _select_final_move(self, moves, phase_name, move_infos, best_score,
                           best_gtp_by_score, player_sign, hunt_max_loss,
                           filtered_count, top_str, human_policy):
        """温度なしのweighted selection + Best-move dodge。"""
        # 通常のweighted selection（温度なし）
        selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]

        # Best-move dodge: 選ばれた手がKataGo最善手なら、僅差+humanPolicy上位の代替手に差し替え
        if move_infos and best_gtp_by_score and move.gtp() == best_gtp_by_score:
            dodge_max_loss = self.settings.get("hunt_dodge_max_loss", 1.0)
            dodge_top_n = int(self.settings.get("hunt_dodge_top_n", 3))

            # 候補手プール内でのcombined weight順位を算出（proximity/intensity込みで棋風を維持）
            weight_by_gtp = {m.gtp(): w for m, w in moves if m.coords}
            sorted_by_weight = sorted(weight_by_gtp.items(), key=lambda x: -x[1])
            top_n_gtps = {gtp for gtp, _ in sorted_by_weight[:dodge_top_n]}

            # スコアマップ
            score_map = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}

            # 代替候補: スコア僅差 + humanPolicy上位N + 非最善手
            alternatives = []
            for m, w in moves:
                gtp = m.gtp()
                if gtp == best_gtp_by_score or gtp not in top_n_gtps or gtp not in score_map:
                    continue
                loss = player_sign * (best_score - score_map[gtp])
                if loss <= dodge_max_loss:
                    w_rank = next(i for i, (g, _) in enumerate(sorted_by_weight) if g == gtp) + 1
                    alternatives.append((m, loss, w_rank))

            if alternatives:
                best_alt = min(alternatives, key=lambda x: x[1])
                alt_move, alt_loss, alt_rank = best_alt
                self.game.katrain.log(
                    f"[HuntDivergenceStrategy] Best-move dodge: {best_gtp_by_score} -> {alt_move.gtp()} "
                    f"(loss={alt_loss:.2f}, weight rank={alt_rank}/{len(sorted_by_weight)})",
                    OUTPUT_DEBUG,
                )
                move = alt_move
            else:
                self.game.katrain.log(
                    f"[HuntDivergenceStrategy] Best-move dodge: no alternative "
                    f"(best={best_gtp_by_score}, candidates checked={len(moves)-1})",
                    OUTPUT_DEBUG,
                )

        self.game.katrain.log(f"[HuntDivergenceStrategy] Selected: {move.gtp()} ({phase_name})", OUTPUT_DEBUG)

        ai_thoughts = (
            f"\n{top_str}\n\n{phase_name}: played {move.gtp()} "
            f"({filtered_count} bad moves filtered)"
        )
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