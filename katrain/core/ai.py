from abc import ABC, abstractmethod
import copy
import heapq
import math
import random
import time
from typing import Dict, List, Optional, Tuple

from katrain.core.constants import (
    AI_DEFAULT, AI_HANDICAP, AI_INFLUENCE, AI_INFLUENCE_ELO_GRID, AI_JIGO, AI_JIGO_9,
    AI_ANTIMIRROR, AI_LOCAL, AI_LOCAL_ELO_GRID, AI_PICK, AI_PICK_ELO_GRID,
    AI_POLICY, AI_RANK, AI_SCORELOSS, AI_SCORELOSS_ELO, AI_SETTLE_STONES,
    AI_SIMPLE_OWNERSHIP, AI_STRENGTH, AI_TSUMEGO, AI_TSUMEGO_SOLVER,
    AI_TENUKI, AI_TENUKI_ELO_GRID, AI_TERRITORY, AI_TERRITORY_ELO_GRID,
    AI_FIGHTING, AI_FIGHTING_SCORELOSS_ELO,
    AI_WEIGHTED, AI_WEIGHTED_ELO, CALIBRATED_RANK_ELO, OUTPUT_DEBUG,
    OUTPUT_ERROR, OUTPUT_INFO, PRIORITY_EXTRA_AI_QUERY, PRIORITY_TSUMEGO_SPECULATION, ADDITIONAL_MOVE_ORDER, AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE
)
from katrain.core.engine import KataGoEngine
from katrain.core.game import (
    REGION_ANALYSIS_WIDE_ROOT_NOISE,
    BaseGame,
    Game,
    GameNode,
    IllegalMoveException,
    Move,
    region_analysis_extra_settings,
)
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
    if strategy in [AI_DEFAULT, AI_HANDICAP, AI_JIGO, AI_JIGO_9, AI_PRO]:
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


# ヨセ委譲の盤サイズ別スライダーキー（board_size → (設定キー, 既定手数)）
# 19路150 / 9路30 は deception phase3 開始手数と一致（deception の ON/OFF で
# 切替タイミングが動かない）。13路の phase3 開始 83 はスライダーの5刻みに
# 乗らないので、他戦略と同じ共通規約 ceil(0.5 x 169) = 85 を採る。
_JIGO_ENDGAME_MOVE_KEYS = {
    19: ("jigo_endgame_move", 150),
    13: ("jigo_endgame_move_13", 85),
    9: ("jigo9_endgame_move", 30),
}


def _jigo_endgame_threshold(board_size, settings):
    """ヨセ委譲を開始する手数。

    19/13/9 路は盤サイズ別スライダー、それ以外は他戦略と同じ共通規約
    ceil(0.5 × 盤面マス数) にフォールバックする。
    board_size は max(width, height)（既存の呼び出し規約）。
    GUI スライダーは float で保存されるので int() で丸める。
    """
    key_default = _JIGO_ENDGAME_MOVE_KEYS.get(board_size)
    if key_default is None:
        return math.ceil(0.5 * board_size * board_size)
    key, default = key_default
    return int(settings.get(key, default))


def _jigo_endgame_handoff(board_size, move_num, last_lead, target_score, settings, sticky=False):
    """HumanStyle 9段へ委譲すべきか。

    条件: チェックボックス ON かつ
          （sticky＝既に委譲済み）または
          （手数が閾値以上 かつ last_lead が target_score 以上）

    last_lead は前手のキャッシュ（None なら未到達扱い＝委譲しない）。
    比較対象は**ユーザー設定の target_score** であって deception の eff_target
    ではない。phase1/2 の eff_target は負なので、それと比べると「設計どおり
    劣勢に留まっている状態」を到達とみなして即委譲してしまう。
    """
    if not settings.get("jigo_endgame_humanstyle", False):
        return False
    if sticky:
        return True
    if move_num < _jigo_endgame_threshold(board_size, settings):
        return False
    return last_lead is not None and last_lead >= target_score


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


# ----------------------------------------------------------------
# Jigo deception Phase 機構
# ----------------------------------------------------------------
# 手数ベースの phase 境界（盤面サイズ → [(境界手数, phase 名), ...]）
JIGO_DECEPTION_PHASE_TABLE = {
    19: [(30, "phase1"), (80, "phase2"), (150, "phase3")],
    13: [(17, "phase1"), (44, "phase2"), (83, "phase3")],
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


# key_prefix ごとの「設定キー欠落時」フォールバック target（target_max は +1.0 で自動）
_JIGO_PATH_TARGET_DEFAULTS = {
    "jigo_deception_13": {"phase1": -2.0, "phase2": -1.0},
    "jigo9":             {"phase1": -1.5, "phase2": -0.5},
}


def _jigo_resolve_path_overrides(phase, default_target, default_target_max, settings,
                                 key_prefix="jigo_deception_13"):
    """deception 有効時、Phase 1/2 で eff_target/eff_target_max を
    settings (スライダー値) に置換して返す。盤面別に key_prefix で切替。

    Phase 0/3 は default をそのまま返す（既存挙動）。
    target_max は target + 1.0 で自動算出（1.0 目幅維持）。

    Args:
        phase: "phase0" | "phase1" | "phase2" | "phase3"
        default_target: phase0/phase3 用フォールバック値
        default_target_max: phase0/phase3 用フォールバック値
        settings: Strategy.settings 相当の dict-like
        key_prefix: "jigo_deception_13"（13路）/ "jigo9"（9路）

    Returns:
        (eff_target, eff_target_max)
    """
    fallbacks = _JIGO_PATH_TARGET_DEFAULTS.get(key_prefix)
    if fallbacks is None:
        raise KeyError(
            f"_jigo_resolve_path_overrides: unknown key_prefix {key_prefix!r}. "
            f"Valid: {list(_JIGO_PATH_TARGET_DEFAULTS)}"
        )
    if phase == "phase1":
        t = settings.get(f"{key_prefix}_phase1_target", fallbacks["phase1"])
        return t, t + 1.0
    if phase == "phase2":
        t = settings.get(f"{key_prefix}_phase2_target", fallbacks["phase2"])
        return t, t + 1.0
    return default_target, default_target_max


def _jigo_compute_effective_max_loss(
    current_lead, target_score_max, base_max_loss,
    large_lead_delta, large_lead_max_loss, board_size,
):
    """current_lead が target_score_max + large_lead_delta を超えた場合のみ max_loss を緩和する。

    緩和発動しない場合・large_lead_max_loss が base より小さい場合は base_max_loss を返す。
    board_size は呼び出し側互換のため残す（盤面別の特別扱いは廃止）。
    """
    threshold = target_score_max + large_lead_delta
    if current_lead < threshold:
        return base_max_loss
    return max(base_max_loss, large_lead_max_loss)


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

    # サブクラスで特定設定を強制無効化するための上書きマップ（基底は空）
    FORCED_SETTINGS = {}

    def _jigo_get(self, key, default):
        """FORCED_SETTINGS にあればその値、なければ self.settings.get(key, default)。"""
        if key in self.FORCED_SETTINGS:
            return self.FORCED_SETTINGS[key]
        return self.settings.get(key, default)

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
        base_profile     = self._jigo_get("human_profile", "rank_9d")
        dynamic_rank     = self._jigo_get("jigo_dynamic_rank", False)
        large_lead_delta    = self._jigo_get("jigo_large_lead_delta", 5.0)
        large_lead_max_loss = self.settings.get("jigo_large_lead_max_loss", 8.0)
        equivalent_epsilon  = self._jigo_get("jigo_equivalent_epsilon", 0.5)
        deception_enabled = self.settings.get("jigo_deception", False)
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}, "
            f"profile={base_profile}, dynamic_rank={dynamic_rank}, "
            f"large_lead_delta={large_lead_delta}, large_lead_max_loss={large_lead_max_loss}, "
            f"equivalent_epsilon={equivalent_epsilon}, deception={deception_enabled}",
            OUTPUT_DEBUG,
        )

        # ---- ヨセ段階の HumanStyle 9段委譲 ----
        # ヨセで target に合わせるための手抜きは相手から見て露骨なので、
        # 目差が target 以上になったら以降は素の9段として打つ。
        # 判定は Stage1/Stage2 の前に行い、目差は前手のキャッシュを使う（1手ラグ）。
        if self.settings.get("jigo_endgame_humanstyle", False):
            board_size_for_endgame = max(self.game.board_size)
            endgame_sticky = getattr(self.game, "_jigo_endgame_handoff", False)
            cached_lead = getattr(self.game, "_jigo_last_current_lead", None)
            endgame_threshold = _jigo_endgame_threshold(board_size_for_endgame, self.settings)
            if _jigo_endgame_handoff(
                board_size_for_endgame, self.cn.depth, cached_lead,
                target_score, self.settings, sticky=endgame_sticky,
            ):
                if endgame_sticky:
                    self.game.katrain.log(
                        "[JigoStrategy] Endgame handoff: sticky (already handed off) "
                        "→ HumanStyle rank_9d",
                        OUTPUT_DEBUG,
                    )
                else:
                    self.game.katrain.log(
                        f"[JigoStrategy] Endgame handoff: move={self.cn.depth} >= "
                        f"thr={endgame_threshold}, lead={cached_lead:.2f} >= "
                        f"target={target_score} → HumanStyle rank_9d",
                        OUTPUT_DEBUG,
                    )
                self.game._jigo_endgame_handoff = True
                self.last_decision_info.update({
                    "rank_used": "rank_9d",
                    "score_lead": cached_lead,
                    "endgame_handoff": True,
                })
                delegate = HumanStyleStrategy(
                    self.game, {"human_kyu_rank": -8, "modern_style": True}
                )
                move, thoughts = delegate.generate_move()
                return move, f"[Jigo→9d yose] {thoughts}"
            if self.cn.depth >= endgame_threshold:
                self.game.katrain.log(
                    f"[JigoStrategy] Endgame pending: move={self.cn.depth} >= "
                    f"thr={endgame_threshold} but lead={cached_lead} < target={target_score}",
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
                _defaults_13 = _JIGO_PATH_TARGET_DEFAULTS["jigo_deception_13"]
                p1_target = self.settings.get("jigo_deception_13_phase1_target", _defaults_13["phase1"])
                p2_target = self.settings.get("jigo_deception_13_phase2_target", _defaults_13["phase2"])
                target_overrides = {
                    "phase1": (p1_target, p1_target + 1.0),
                    "phase2": (p2_target, p2_target + 1.0),
                }
            elif board_size_for_phase == 9:
                phase_table_override = [
                    (self.settings.get("jigo9_phase1_start", 6),  "phase1"),
                    (self.settings.get("jigo9_phase2_start", 16), "phase2"),
                    (self.settings.get("jigo9_phase3_start", 30), "phase3"),
                ]
                _defaults_9 = _JIGO_PATH_TARGET_DEFAULTS["jigo9"]
                p1_target = self.settings.get("jigo9_phase1_target", _defaults_9["phase1"])
                p2_target = self.settings.get("jigo9_phase2_target", _defaults_9["phase2"])
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
                eff_target, eff_target_max = _jigo_resolve_path_overrides(
                    phase, target_score, target_score_max, self.settings,
                    key_prefix="jigo_deception_13",
                )
            elif board_size_for_phase == 9:
                eff_target, eff_target_max = _jigo_resolve_path_overrides(
                    phase, target_score, target_score_max, self.settings,
                    key_prefix="jigo9",
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


@register_strategy(AI_JIGO_9)
class Jigo9Strategy(JigoStrategy):
    """持碁（9路）専用モード。JigoStrategy を継承し generate_move を流用。

    9路に無関係な上級設定（human_profile / jigo_dynamic_rank /
    jigo_large_lead_delta / jigo_equivalent_epsilon）は FORCED_SETTINGS で
    無効化値に固定し、GUI 非表示・config 非格納のままコードで確実に無効化する。
    deception は generate_move の board_size==9 分岐で jigo9_* スライダーを読む。
    """

    FORCED_SETTINGS = {
        "jigo_equivalent_epsilon": 0.0,
        "jigo_large_lead_delta": float("inf"),  # large-lead 緩和を無効化
        "jigo_dynamic_rank": False,
        "human_profile": "rank_9d",
    }


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


def tsumego_gain_stones(stones, region_of_interest):
    """gain の集計対象になる石座標。リージョンがあれば枠外の石を落とす。

    枠は「リージョン外を守り側の代償地帯 defense_area と攻め方の地に配る」設計
    （`tsumego_frame.put_outside`）で、その境目は未決着のまま残る。つまり枠外の石の
    ownership は詰碁の成否と**逆相関する counterweight** になっており、gain に混ぜると
    符号が反転する。実測 2026-07-30（13路 case D、正解 A4 を捨てて C3 で白を生かした局面）:

        リージョン内 5石  −9.65（正しく「白が生還した」と出ている）
        枠外の境目 6石   +11.6
        合計             +2.90 ← 候補中最大になり誤答手が選ばれた

    枠内に残る枠石（壁）は堅く生きているので ownership が動かず、集計に混ぜても害はない。
    """
    if not region_of_interest:
        return list(stones)  # 枠なしモード等: 従来どおり全石で集計する
    xmin, xmax, ymin, ymax = region_of_interest
    return [(x, y) for x, y in stones if xmin <= x <= xmax and ymin <= y <= ymax]


def tsumego_ownership_gain(root_ownership, move_ownership, stones, board_size, player_sign):
    """渡された石について、手番側から見て有利な向きの ownership 変化量を合計する。

    石ごとに合計するので大きい連の死活ほど重く効く。石の無い点は数えないので、
    空き地の手は gain がほぼ 0 になり自動的に沈む。集計範囲は `tsumego_gain_stones` が決める。
    """
    root_grid = var_to_grid(root_ownership, board_size)
    move_grid = var_to_grid(move_ownership, board_size)
    return sum(player_sign * (move_grid[y][x] - root_grid[y][x]) for x, y in stones)


def tsumego_absolute_ownership(ownership, stones, board_size, player_sign):
    """渡された石の ownership を手番側視点で合計する（root 差分を取らない絶対値）。

    別々のクエリで測った局面同士を比べるときは gain（root 差分）を使えない。root ownership は
    「その探索の平均」なので基準が揃わないため。同深さで測り直した子局面の比較にはこちらを使う。
    """
    grid = var_to_grid(ownership, board_size)
    return sum(player_sign * grid[y][x] for x, y in stones)


# gain は1本の root 探索の movesOwnership から取るため、候補ごとに探索の深さが違う。探索が浅い
# 候補ほど ownership が未決着側へドリフトし、root が飽和している局面では**片側ノイズ**になる。
# 実測 2026-07-30（13路右上 case F。正解 N8 に対し AI は N7 を選び白が生きた）:
#
#   N8(正解) 780-890visits  ptLost -0.60〜-0.79  gain -0.45〜-0.55  → 8000v(2565visits) で -0.04
#   N7(誤答) 214-307visits  ptLost +1.35〜+1.60  gain +2.70〜+9.10  → 8000v( 637visits) で +0.06
#   N6       89- 90visits   ptLost +1.44         gain +11.06〜+11.98 → 8000v( 502visits) で +0.66
#
# visits を与えると gain が消える＝死活の信号ではない。ノイズ幅（+12）は spec が想定した
# ±0.03 の 400 倍で、case B / C の実信号 1.16 / 3.20 も飲み込むので gain_epsilon では止まらず、
# min_visits=10 も無力（N7 は 214-307visits）。そこで「目数最善手を gain で覆せるのは、その手と
# 探索の深さが比較できる候補だけ」に絞る。実測の比は N7 0.31-0.34 / N6 0.11 に対し case D の
# 正解 A4 は 1.00 なので、0.5 で誤答だけを落とせる
TSUMEGO_GAIN_MIN_VISIT_RATIO = 0.5

# 目数最善手を覆す判断が出たときに両者を測り直す visits と、採用に要求する ownership 差。
# 同深さでも ±0.3 程度は動く（実測 case F: N8 -26.60 / N6 -26.84 / M7 -26.89 / N7 -26.91）
TSUMEGO_GAIN_VERIFY_VISITS = 800
TSUMEGO_GAIN_VERIFY_MARGIN = 0.3

# gain 同着（gain_epsilon 内）の目数タイブレークで、この幅以内の目数差は同着とみなし
# visits 最多の手（KataGo の principal variation）を採る。実測 case J (2026-07-30):
# 正解 N10(v1175 pt-0.05) と別解 N11(v616 pt-0.07) が 0.02 目差で並び、目数タイブレークが
# ノイズで N11 を選んでアプリの解答樹に無い別解を打った（N11 も白を殺せている＝8000visits
# でも分離不能、同深さ検証も差 0.05 で無力）。アプリの解答樹の本線は KataGo の本命手と
# 一致しやすい（case J の正解10手はすべて visits 最多手）。0.25 はノイズ（〜0.07）と
# 目数タイブレークが守るべき最小の実信号（2026-07-29 の C12/D12 = 0.64 目差）の中間
TSUMEGO_POINTS_EPSILON = 0.25


def tsumego_override_confirmed(challenger_value, score_best_value, margin):
    """同深さで測り直した対象石 ownership が、目数最善手を覆す判断を裏づけているか。

    実測 case F: 挑戦者 N7 は -26.91 で目数最善 N8 の -26.60 に負ける（差 -0.31）ので却下。
    一方 gain が本物のケース（case B / C の実信号 1.16 / 3.20）はこの margin を余裕で超える。
    """
    return challenger_value > score_best_value + margin


# コウ判定の上限（解析1本ずつ増えるため）と、通常最善手を上回ったと見なす目数マージン
_TSUMEGO_KO_MAX_CANDIDATES = 3
TSUMEGO_KO_MARGIN = 5.0
_TSUMEGO_KO_MAX_ATARI_STONES = 6  # 打った石以外に調べる自分の1子アタリの数


# 枠は「成功した側が offence_to_win(5)目勝ち」に調整されるので、手番側から見たスコアの
# 符号がそのまま成否になる。境界は 0（攻める詰碁・生きる詰碁のどちらでも player_sign 込みで成立）
TSUMEGO_SUCCESS_LEAD = 0.0


# スコアだけでは「成功している」と判定できないので、ownership でも裏を取る（1子平均）。
# 枠の代償地帯が未決着だとスコアが詰碁の成否から切り離される: 実測 case Q（2026-07-31）は
# 相手石が 12子すべて生存（−0.99/子）なのに手番側 +10.45目で、全盤 20000visits の最善手が
# 枠の充填部（B9 v17448）＝黒はどう打っても勝てる盤になっていた。枠なし盤ではもっと露骨で、
# case H は +27.69目・相手石 −0.15/子。
#
# 既存16ケースの実測（成功＝手番側から見た関係石の 1子平均 ownership）:
#   成功している局面  D/E/J/K/L/M/O/P … +0.94〜+1.00
#   失敗している局面  F/G/G2/H/F2/I/N/Q … −0.15〜−1.00
# 境界は −0.15 と +0.94 の間に 1.09 の空白があり、どこを取っても分離できる。0.5 は
# `tsumego_frame.FRAME_SOLVER_ALIVE_OWNERSHIP` と同じ「その石群は生きているか」の閾値。
TSUMEGO_SUCCESS_OWNERSHIP = 0.5


def tsumego_region_stones_by_player(stones, region_of_interest, player):
    """リージョン内の石を (手番側, 相手側) の座標リストに分ける。リージョンが無ければ全石。"""
    split = lambda mine: tsumego_gain_stones(  # noqa: E731
        [s.coords for s in stones if (s.player == player) == mine], region_of_interest
    )
    return split(True), split(False)


# 枠の壁の色＝攻め方の色。`tsumego_frame.put_border` は frame_range の4辺に**攻め方の色**の石を
# 敷き、`mark_region_corners` が**同じ frame_range** をリージョンにするので、リージョン境界線
# （盤端でない辺）に並ぶ石列がそのまま「どちらが攻め方か」を表している。
#
# 実測 2026-07-31（保存済み19ケースの SGF を境界線で数えた）: 枠ありは全ケースで境界線が
# **単色100%・占有率100%**（case T: x=2 が W7/7 と y=6 が W11/11、case M: W9/9・W9/9、
# case O: B10/10・B9/9）、枠なしは境界線に石が1つも無いか1子だけ（case R: 13点中 B1＝占有率0.08）。
# 0.08 と 1.00 の間は桁で空いているので、占有率と純度の二重ゲートで安全に分離できる。
#
# 枠が壊れている（攻め方推定が反転した）キャプチャでは壁も反転色で敷かれるが、そのとき
# 判定が壁に追随するのは**正しい**: 枠が反転していればスコアも ownership もその枠の役割に
# 従って出るので、盤に書かれている役割こそがその局面の意味論になる（実測 case F/G/S の
# 保存 SGF は反転枠のまま保存されており、この判定も反転側を返す）。役割そのものの是正は
# `tsumego_frame.extremum_stones` 側の仕事。
TSUMEGO_WALL_MIN_OCCUPANCY = 0.7
TSUMEGO_WALL_MIN_PURITY = 0.9


def tsumego_wall_lines(region_of_interest, board_size):
    """枠の壁が乗りうる線＝リージョン境界のうち盤端でない辺の座標列。

    盤端に接している辺には壁が要らない（盤の縁がそのまま壁になる）ので候補から外す。
    """
    if not region_of_interest:
        return []
    xmin, xmax, ymin, ymax = region_of_interest
    size_x, size_y = board_size
    lines = []
    if xmin > 0:
        lines.append([(xmin, y) for y in range(ymin, ymax + 1)])
    if xmax < size_x - 1:
        lines.append([(xmax, y) for y in range(ymin, ymax + 1)])
    if ymin > 0:
        lines.append([(x, ymin) for x in range(xmin, xmax + 1)])
    if ymax < size_y - 1:
        lines.append([(x, ymax) for x in range(xmin, xmax + 1)])
    return lines


def tsumego_solver_attacks(stones, region_of_interest, board_size, player):
    """手番側（解く側）が攻め方かを枠の壁の色から判定する。判定できなければ None。

    **詰碁の正解順序は役割で逆転する**:

        攻め方（殺す）  無条件死 > コウ > セキ（相手が生きた＝失敗）
        守り方（生きる） 無条件生き > **セキ > コウ**（コウダテ次第＝条件付き）

    セキが守り方にとって「コウより上」なのは、盤全体のコウダテという外部条件に頼らず
    無条件に石が助かるから。ところが選択則が使うスカラー（pointsLost・gain・同深さ検証値）は
    どれも「どれだけ得したか」を測るので、守り方のセキ（地は0目・相手も生きる）は
    コウ勝ち（相手を取り切る）より必ず下に出る。**目数ではクラスの順序を表現できない**。

    実測 2026-07-31 case T（13路下辺・黒が守り。正解 L1＝セキ、AI は J2＝コウ生き）:

        root 目数    J2 -0.34 / L1 +4.30   ← 目数ガード(best+2.0)が正解を落とす
        gain         J2 +0.20 / L1 -3.83
        同深さ検証値 J2 -16.66 / L1 -19.79（全リージョン石＝相手33子に支配される）
        **自石だけ**  J2 +0.99/子 / L1 +1.00/子  ← 順序が正しく出る唯一の尺度

    つまり役割が分かって初めて「何を見れば成否か」が決まる（攻め方＝相手石が死んだか、
    守り方＝自石が生きたか）。両方測って厳しいほうを採る従来のヘッジは、守り方では
    「相手が生きている＝失敗」と読んでしまい、セキを必ず失敗側に落とす。

    判定できない（枠なし・壁が読めない）場合は None を返し、呼び出し側は従来の
    役割非依存の挙動を維持する。枠なしケース（G2/F2/H/I/N/R）は全てこの経路。
    """
    lines = tsumego_wall_lines(region_of_interest, board_size)
    if not lines:
        return None
    at = {s.coords: s.player for s in stones}
    colors = set()
    for line in lines:
        placed = [at[c] for c in line if c in at]
        if not line or len(placed) < TSUMEGO_WALL_MIN_OCCUPANCY * len(line):
            continue  # 石がまばらな辺は壁ではない（枠なし盤の境界線）
        top = max(set(placed), key=placed.count)
        if placed.count(top) >= TSUMEGO_WALL_MIN_PURITY * len(placed):
            colors.add(top)
    if len(colors) != 1:
        return None  # 壁が無い、または辺ごとに色が食い違う＝枠として読めない
    return colors.pop() == player


def tsumego_role_stones(own_stones, opponent_stones, solver_attacks):
    """役割から「詰碁の成否を担っている石」を選ぶ。役割不明なら従来どおり両方。

    殺す詰碁では手番側の石は壁と連絡して自明に生きており、生きる詰碁では相手側の石が
    自明に生きている。**自明に生きている側を混ぜると成否の信号が薄まる/反転する**ので、
    役割が分かるときは担っている側だけを見る（`tsumego_solver_attacks` の実測を参照）。
    """
    if solver_attacks is None:
        return list(own_stones) + list(opponent_stones)
    return list(opponent_stones if solver_attacks else own_stones)


def tsumego_success_ownership(
    root_ownership, own_stones, opponent_stones, board_size, player_sign, solver_attacks=None
):
    """手番側が詰碁として成功しているかの ownership 尺度（1子平均）。

    成功の中身は問題の種類で違う（殺す詰碁＝相手石が死ぬ／生きる詰碁＝自石が生きる）が、
    どちらも「手番側がその石を所有している」＝`player_sign * ownership` が正、で表せるので
    符号は共通に取れる。役割が分かるなら**成否を担っている側の石だけ**を見る
    （`tsumego_role_stones`）。

    `solver_attacks=None`（枠なし等で役割が読めない）ときだけ従来どおり両方を測って
    **小さいほう**を採る。min は生きる詰碁で相手（攻め方）の石が生きたまま＝負に出るので、
    成功していても「成功していない」側に倒れる（実測 case M: 自石 +1.00 / 相手石 −0.93）。
    誤ってスキップしないほうが安全側なので役割不明時のヘッジとしては妥当だが、**役割が
    分かるなら使ってはいけない**: 守り方の正解がセキのとき（相手も生きるのが正常）
    「失敗」と読まれ、コウ機構が走ってセキより下のコウを持ち上げてしまう
    （詰碁の順序は守り方では 無条件生き > セキ > コウ。実測 case T）。

    ownership が取れない（`_enable_ownership=false` 等）／石が1つも無ければ None を返す
    ＝判定材料なしとして ownership 側の条件を課さない（従来どおり目数だけで振り分ける）。
    この経路は `select_tsumego_move` が None を返して最善手フォールバックする局面と同じで、
    ここで例外を投げるとフォールバックごと壊れる。
    """
    if not root_ownership:
        return None
    groups = (
        [tsumego_role_stones(own_stones, opponent_stones, solver_attacks)]
        if solver_attacks is not None
        else [own_stones, opponent_stones]
    )
    per_stone = [
        tsumego_absolute_ownership(root_ownership, stones, board_size, player_sign) / len(stones)
        for stones in groups
        if stones
    ]
    return min(per_stone) if per_stone else None


def tsumego_already_succeeded(
    best_normal,
    threshold=TSUMEGO_SUCCESS_LEAD,
    success_ownership=None,
    ownership_threshold=TSUMEGO_SUCCESS_OWNERSHIP,
):
    """通常評価の最善手だけで既に成功しているか（＝コウに持ち込む理由が無い）。

    詰碁の正解は目数ではなく**結果の順序**で決まる: 無条件に殺す（生きる） > コウ > セキ。
    目数はクラス内のタイブレークにすぎず、クラスを跨いだ比較には使えない。ところが
    コウ勝ち前提のノードは攻め方が1手多く打ち相手石を1子取った局面なので、
    **無条件の成功より高い目数が出てしまう**（実測 case E: 無条件死 +11.44目 < コウ勝ち +12.50目）。

    そこで目数で殴り合わせる前に、通常最善が既に成功しているかで振り分ける。コウ勝ち前提の
    役目はもともと「枠の中では攻め方のコウダテが乏しく、正解のコウ手がセキより悪く見える」
    局面の**救済**に限られる（追記4）。既に成功しているならその救済は不要で、
    コウに持ち込むのは慣習上むしろ格下げになる。

    ただし**目数だけでは成否を判定できない**（`TSUMEGO_SUCCESS_OWNERSHIP` 参照。枠の代償地帯が
    未決着だとスコアが詰碁から切り離され、実測 H/Q の2ケースで「成功していないのに成功」と
    出る）。`success_ownership` が渡されたら ownership でも裏を取り、**両方が成功と言うときだけ**
    スキップする。判定を厳しくする方向にしか動かないので、外れても保険（`ko_win_margin`）の
    効いた従来経路に落ちるだけ。
    """
    if best_normal <= threshold:
        return False
    return success_ownership is None or success_ownership >= ownership_threshold


def tsumego_ko_beats_normal(ko_value, best_normal, margin):
    """コウ勝ち前提の評価が「結果を変える」幅で通常最善を上回っているか。

    コウ勝ち前提のノードは（手を打つ → 守り側が取る → 取り返す）と進めた局面なので、
    攻め方が1手多く打ち相手の石を1子取った状態になっている。つまり通常最善との比較は
    構造的に数目ぶんコウ側へ偏っており、素の大小比較だと「通常最善が既に無条件で殺して
    いるのに、おまけの分だけコウが勝つ」ことが起きる。実測 2026-07-30（case E）:

        K1  1776visits  無条件に殺して      +11.44目  ← 正解
        L1     1visit   実際は -34.26目 / コウ勝ち前提 +12.50目（差 +1.06目）← 選ばれた

    一方コウが本当の正解である問題では通常最善はセキ止まり等の失敗なので、差は桁違いに
    大きい（実測: セキ -12.3目 に対しコウ勝ち前提 +8.1目 = 差 +20.4目）。枠は「攻め方成功
    = offence_to_win(5)目勝ち」に調整する設計で成功と失敗は約10目離れるため、その半分を
    要求することで「コウが結果を変えるのか、おまけ分の上積みなのか」を切り分けられる。
    """
    return ko_value > best_normal + margin


def _chain_and_liberties(game, coords):
    """指定座標の連と呼吸点座標を返す。石が無ければ (None, [])"""
    x, y = coords
    chain_id = game.board[y][x]
    if chain_id < 0:
        return None, []
    size_x, size_y = game.board_size
    liberties = set()
    for stone in game.chains[chain_id]:
        sx, sy = stone.coords
        for nx, ny in ((sx + 1, sy), (sx - 1, sy), (sx, sy + 1), (sx, sy - 1)):
            if 0 <= nx < size_x and 0 <= ny < size_y and game.board[ny][nx] < 0:
                liberties.add((nx, ny))
    return game.chains[chain_id], sorted(liberties)


def tsumego_simulation_game(game, node):
    """本譜のツリーを汚さずに読みを進めるための使い捨てゲームを作る。作れなければ None"""
    try:
        sim = BaseGame(katrain=game.katrain, move_tree=GameNode(properties=copy.deepcopy(game.root.properties)))
        for path_node in node.nodes_from_root[1:]:
            if path_node.move is None:
                return None  # 途中に着手以外のノード（追加配置等）がある局面は諦める
            sim.play(path_node.move, ignore_ko=True)
    except Exception:
        return None
    return sim


def tsumego_ko_win_node(game, node, move):
    """コウになる候補手について「攻め方がコウに勝った局面」のノードを返す。コウでなければ None。

    詰碁ではコウダテがあるものとして正解が決まる（コウに持ち込めればそれが最大の成果）。
    一方この枠の中では攻め方のコウダテが乏しく、KataGo は「コウは守り側が勝つ＝無価値」と
    正しく読んでしまうため、殺せないセキ等の劣る手を選ぶ（実測 2026-07-30: 正解のコウ手が
    -21.7目、セキの手が -12.3目。コウを黒が勝った局面は +8.1目）。
    そこでコウの手だけは取り返した後の局面で評価し、詰碁の慣習に合わせる。

    判定は「自分の1子が呼吸点1 → 守り側がそこを取る → 取り返しがコウで禁じられる」という
    形かどうかで、KaTrain 自身の着手判定に委ねる。取られる1子は打った石自身とは限らない
    （殺す詰碁では打った石自身、生きる詰碁では別の自石が取られてコウになる形が普通に出る）。
    """
    sim = tsumego_simulation_game(game, node)
    if sim is None:
        return None
    player = move.player
    opponent = "W" if player == "B" else "B"
    try:
        after_move = sim.play(move)
    except IllegalMoveException:
        return None
    # 打った石自身を最優先で試し、次に他の1子アタリを試す
    others = sorted(
        {
            chain[0].coords
            for chain in sim.chains
            if len(chain) == 1 and chain[0].player == player and chain[0].coords != move.coords
        }
    )
    for coords in [move.coords] + others[:_TSUMEGO_KO_MAX_ATARI_STONES]:
        sim.set_current_node(after_move)
        chain, liberties = _chain_and_liberties(sim, coords)
        if chain is None or len(chain) != 1 or len(liberties) != 1:
            continue
        try:
            sim.play(Move(coords=liberties[0], player=opponent))
        except IllegalMoveException:
            continue
        try:
            sim.play(Move(coords=coords, player=player))
        except IllegalMoveException as e:
            if "Ko" not in str(e):
                continue
        else:
            continue  # 取り返せてしまう＝コウではない
        return sim.play(Move(coords=coords, player=player), ignore_ko=True)
    return None


# 同着バンドのコウ検査: 守り方の最善応手 PV を並べ直す深さと、検査する候補数の上限。
# 実測 case K はコウ形が応手 PV の ply2（B11）に出る。深くするほど詰碁と無関係な
# 偶発コウを拾うリスクが増えるので、リージョン制限とセットで短めに切る
TSUMEGO_TIE_KO_PLIES = 6
TSUMEGO_TIE_KO_MAX_CANDIDATES = 4

# コウ経路検査で歩く応手の「拮抗」閾値と本数上限。守り方の最善応手が1本に読み切られていれば
# その PV だけで足りるが、コウを仕掛ける抵抗と穏健な応手が拮抗する局面では 800visits の解析
# ごとに top が入れ替わる（実測 case M 2026-07-30: B M2 への白応手 K1 v144 vs M4 v103 =
# 比 0.72。top 1本だけを歩く旧実装は M4 が top に振れた run でコウを見逃し 3run 中 2 で
# 素通りした）。守り方が選べる競争力のある抵抗のどれかにコウがあるなら、その候補はコウ経路。
# 比 0.5 未満の応手は doomed な抵抗として無視する（実測 case M の K1 子局面: 白 M2 の
# 取り返しは v27/M4 v230 = 比 0.12 で沈む＝正解 K1 は安定して clean）
TSUMEGO_KO_REPLY_RATIO = 0.5
TSUMEGO_KO_REPLY_MAX = 3

# コウ経路検査の子局面解析だけ wideRootNoise を切る。**応手の visits 比を揺らしていた正体はこれ**。
# wRN は root の policy に Dirichlet ノイズを足して候補リストを広げる設定で、run ごとにノイズを
# 引き直すため「守り方の応手にどう visits が配られるか」が毎回変わる。visits を増やしても消えない
# 種類の揺れ（1回の探索の間ずっと同じノイズが乗る）。既存の「死活の裁定クエリに wRN を効かせない」
# （`FRAME_VALIDITY_WIDE_ROOT_NOISE`）と同じ話で、着手選択の設定を裁定に流用してはいけない。
#
# 実測 case M（2026-07-31、M2 の子局面 800visits・プロセスを分けて4 trial）:
#
#   wRN=0.04  M4 v90〜117 / K1 v58〜75  = 比 0.44〜0.88（**本番フローでは 3/6 で 0.5 を割った**）
#   wRN=0     M4 v663〜666 / K1 v98〜101 = 比 **0.15 が 4/4 で不動**、残りの応手は全部 v1
#
# つまり現行の 0.5 ゲートは「ノイズが本物のコウ応手の取り分を水増ししてくれた時だけ当たる」
# 偶然の産物で、visits を増やすほど真値 0.15 に収束して**外れやすくなる**。
TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE = 0.0

# 選択手を検査するときだけ使う敏感側の比。**検出漏れと誤検出のコストが非対称**なので閾値を分ける:
#
# - 選択手のコウを**見逃す**と、クラス裁定（無条件 > コウ）がそもそも走らず、コウ手がそのまま
#   打たれる（case M の誤答そのもの）。この機構が黙って no-op になる唯一の経路。
# - 対抗馬を**過検出**すると clean な格下げ先が消え、`tsumego_class_screen_all_ko` が真になって
#   前提が偽のままコウ脱出が走る（case R）。対抗馬側は保守的な `TSUMEGO_KO_REPLY_RATIO` のまま。
#
# 値は wRN=0 の実測（同 800visits、コウに到達する応手の最小比）から:
#
#   検出すべき  M A12 0.09/0.13 ・ M M2 0.15(×4) ・ O B12 0.42/0.78 ・ P H1 1.00 ・ R G13 1.00
#   clean のまま K C13 **0.02**(×2) ・ M K1 なし ・ P J1 なし ・ O A11 なし
#
# 0.05 は K C13 の 0.02 と case K A12 の 0.09 の間（両側 2.5倍/1.8倍）。**単一の閾値では分離
# できない**ことも実測済みで、格下げ先まで同じ敏感さで検査すると case R の J13(0.10〜0.16)・
# D8(0.04〜0.05) が全部コウになり、全員コウ→脱出の誤爆に化ける。
TSUMEGO_KO_REPLY_RATIO_CHOSEN = 0.05

# コウ経路検査の子局面解析で、リージョン外の着手を禁じる深さ（avoidMoves の untilDepth）。
# 既定のリージョン解析は untilDepth=1 で root の着手選択だけを枠内に縛るが、**PV は ply2 以降
# 枠へ自由に出ていける**。詰碁を読み切った KataGo にとって負けている側の局所の抵抗は枠の一点と
# 同値なので、守り方の PV は肝心のコウを打たずに枠へ手抜きする＝検査の証拠そのものが消える。
#
# 実測 case P（2026-07-31、13路下辺・黒番3手目。正解 J1 に対し AI は同着バンドの visits
# タイブレークで H1 を選び、白 J1・黒 L2 の後に白 G1 が黒 H1 を1子取ってコウ）: H1 の子局面で
# 白の最善応手 J1（v59〜91 で単独首位＝応手の選択自体は安定）の PV が
#
#   untilDepth=1   `J1,L2,J12,...`  ply3 で枠外(J12)へ手抜き → コウ検出 **1/4**
#   untilDepth=6   `J1,L2,G1,...`   局所に留まりコウに到達   → コウ検出 **4/4**
#
# （プロセスを分けた 4 trial。GUI 実戦は 1/4 の側を外して誤答した）。無条件の正解 J1 は
# どちらの深さでも 4/4 clean なので、深く縛っても偽陽性は増えていない。
# 歩く深さと同じだけ縛るのが自明な整合点（PV を見る範囲＝局所を強制した範囲）。
TSUMEGO_KO_REGION_UNTIL_DEPTH = TSUMEGO_TIE_KO_PLIES

# 同深さ ownership 判定（`_region_child_verdict` / `_child_verdicts`）でリージョン外を禁じる深さ。
# **コウ検出の PV 歩き（`TSUMEGO_TIE_KO_PLIES`）と同じ数字を使ってはいけない** — 上の 6 は
# 「PV を何手ぶん証拠に使うか」で決めた数字で、「その死活が何手で決着するか」とは無関係。
# 判定が「その手で相手が死ぬか」を聞くものである以上、拘束は**局所の攻防が終わるまで**要る。
# 拘束が切れた ply で守り方は枠外へ逃げられ、逃げた＝その群を捨てた局面が評価されるので、
# **失敗手が「相手は死んだ」と読まれる**（詰碁の成否と逆の答えが返る）。
#
# 実測 case Y（2026-08-02、13路左下・枠あり・黒は攻め方。正解 B1＝白 C1・黒 A2 のコウ。
# 実戦は A4 で白の無条件生き＝詰碁アプリも A4 の時点で不正解判定）。A4 の子局面の白6子:
#
#   untilDepth=6    +0.71 / +0.78（800visits）・+0.96（6000visits）  ＝「白は死んだ」で**誤り**
#   untilDepth=10   -0.93 / -0.95     untilDepth=12  -0.95 / -0.97    ＝「白は生きた」で正しい
#
# ud6 の PV は `W A2,B A3,W C3,B A5,W D1,B C1` と進んだあと **ply7 で白が M5（枠外）へ手抜き**し、
# 次の黒 C2 で全部取られている。この詰碁は白が ply7 の A1（コウ取り）で2眼を作って生きる形なので、
# 拘束が ply6 で切れると白の正着がちょうど地平線の外に落ちる。**深さでも visits でも直らない**
# （6000visits にすると +0.96 とむしろ確信が強まる＝探索を増やすほど「逃げる」読みに収束する）。
#
# 12 を採るのは ud10/12/16 が case Y で同じ答え（-0.93〜-0.97）に収束し、かつ校正済みの判定を
# 1つも動かさないから（800visits・各 ud で実測。発火すべき側と発火してはいけない側の両方を測った）:
#
#   発火すべき   K C13 +0.99 / L J6 +0.99〜+0.98 / M K1 +0.99 / P J1 +0.99（格下げ先）
#                O A11 +0.99 / T L1 +1.00〜+0.97（脱出の採用手）
#   発火不可     V K10 -1.00→-0.93 / W J1 -0.24→-0.60（ヘッジ、深いほど安全側）/ Y A4 +0.78→**-0.97**
#
# ＝ ud6 で唯一閾値 0.5 の反対側に居たのが case Y。コウ検出（`_ko_route_screen`）の拘束は 6 の
# ままにする（あちらは PV を 6 手しか歩かないので、深くすると偶発コウを拾う側のリスクだけ増える）。
TSUMEGO_VERDICT_UNTIL_DEPTH = 12

# コウ「権利」の検出（`tsumego_defender_ko_points`）を歩く深さ。PV が実際にコウを打つことを
# 要求する既存判定（`tsumego_pv_reaches_region_ko` の1子取り検査）より**短く**切る。
#
# なぜ第2の判定が要るか: リージョン解析は `untilDepth` で両者を枠内に縛るので、**守り方は
# コウダテを打てない**。するとコウを仕掛けることは守り方にとって純粋な損になり、KataGo は
# それを正しく「打つ価値なし」と読む。ところが詰碁の裁定は逆で、攻め方にとって
# 「コウで殺す」は「無条件に殺す」より下のクラスに落ちる。**コウが問題になる局面ほど
# エンジンはそのコウを打たない**ので、PV を証拠にする判定は肝心なときに黙る。
#
# 実測 case U（2026-07-31、13路左下・黒番初手。正解 C1 に対し AI は A3 を打ち、白 C1 →
# 黒 D1 がアタリ → 白 E1 の1子取りでコウにされて不正解）: 白のコウ抵抗 C1 は
# **visits比 0.01**（v7/617）で敏感側の 0.05 にも届かず、しかも C1 自身の PV
# `C1,A4,D6,E6,D7` にコウ手 E1 が現れない（KataGo は C1 を黒+8.99＝白の損と評価）。
# 応手を比 0.00 まで全部歩いても PV 由来の検出は 0/5 run だった。一方「白がコウ取りを
# 打てる状態になったか」で見ると **5/5 run で ply5 に立つ**（正解 C1 は 5/5 clean）。
#
# 深さを 5 で切る理由は、この証拠が PV より弱いぶん偶発コウを拾いやすいから。実測の
# 内訳（両側・19ケース）:
#
#   検出すべき   U ply5 ・ L ply3 ・ P ply3 ・ F ply3/5 ・ R(D8) ply5
#   clean のまま **G2 の正解 C13 ply7** ・ **R の C8 ply7** ・ K(A10) ply7
#
# ply7 の3件はいずれも詰碁と無関係な偶発コウで、真陽性は ply5 までに収まる。
TSUMEGO_KO_AVAIL_PLIES = 5


def tsumego_defender_ko_points(sim, defender, region_of_interest):
    """守り方が**今すぐ**打てるコウ取りの点（リージョン内）を集合で返す。

    コウ取り＝その一手で相手の1子を取り、取った石自身が呼吸点1になり、相手の取り返しが
    KaTrain の着手判定でコウとして禁じられる形（`tsumego_pv_reaches_region_ko` の判定と同じ）。
    違いは「PV がその手を打つか」を問わないこと — 打たれなくても**打てる**なら、守り方は
    いつでもコウにできるのでその局面はコウのクラスにいる。

    試し打ちする点は先に chains から絞る: KaTrain の Ko 例外は「直前の手がちょうど1子取り」の
    ときしか発火しない（`_validate_move_and_update_chains` の ko_or_snapback）ので、コウ取り点は
    必ず**攻め方の1子連で呼吸点がちょうど1つ**の、その唯一の呼吸点。これは必要条件のフィルタで、
    成立の判定そのものは従来どおり実打ち（KaTrain の着手判定）に委ねる＝返る集合は総当たりと
    同一（等価性は test_tsumego_ko の総当たり参照実装との比較で担保）。
    リージョン内の全空点を試し打ちする総当たりは、`play`/`set_current_node` が盤面全体を
    ゼロから再計算するため1回あたり約0.13秒かかり、コウ詰碁の着手決定の約8割を占めていた
    （実測 2026-08-02: 13路・空点約100点 × 最大3回の全盤再計算 × 87呼び出し ＝ 11.7秒）。

    sim は使い捨ての局面を渡すこと（試し打ちのぶんノードが増える。盤面は毎回戻す）。
    """
    attacker = "W" if defender == "B" else "B"
    size_x, size_y = sim.board_size
    xmin, xmax, ymin, ymax = (0, size_x - 1, 0, size_y - 1) if region_of_interest is None else region_of_interest
    xlo, xhi = max(0, xmin), min(xmax, size_x - 1)
    ylo, yhi = max(0, ymin), min(ymax, size_y - 1)
    candidates = set()
    for chain in sim.chains:
        if len(chain) != 1 or chain[0].player != attacker:
            continue
        _, liberties = _chain_and_liberties(sim, chain[0].coords)
        if len(liberties) != 1:
            continue
        x, y = liberties[0]  # 呼吸点は空点なので「空点だけ試す」条件も自動的に満たす
        if xlo <= x <= xhi and ylo <= y <= yhi:
            candidates.add((x, y))
    base = sim.current_node
    points = set()
    for x, y in sorted(candidates):
        try:
            sim.play(Move(coords=(x, y), player=defender))
        except IllegalMoveException:
            sim.set_current_node(base)
            continue
        chain, liberties = _chain_and_liberties(sim, (x, y))
        if chain is not None and len(chain) == 1 and len(liberties) == 1:
            try:
                sim.play(Move(coords=liberties[0], player=attacker))
            except IllegalMoveException as e:
                if "Ko" in str(e):
                    points.add((x, y))
                # 自殺手等でそもそも取り返せない形はコウではない
        sim.set_current_node(base)
    return points


def tsumego_competitive_replies(replies, ratio=TSUMEGO_KO_REPLY_RATIO, max_replies=TSUMEGO_KO_REPLY_MAX):
    """visits 降順で top と拮抗する応手（比 ratio 以上）を最大 max_replies 本返す"""
    ordered = sorted(replies, key=lambda m: -m.get("visits", 0))
    if not ordered:
        return []
    top_visits = ordered[0].get("visits", 0)
    return [r for r in ordered[:max_replies] if r.get("visits", 0) >= ratio * top_visits]


def tsumego_pv_reaches_region_ko(sim, first_player, pv, region_of_interest, max_plies=TSUMEGO_TIE_KO_PLIES):
    """PV を sim の現局面から並べ直し、リージョン内でコウのクラスに入るかを返す。

    判定は2本立て（どちらか成立でコウ経路）:

    1. **PV がコウ形の1子取りに到達する** — 取った石が単独・呼吸点1で、相手の取り返しが
       KaTrain の着手判定でコウとして禁じられる形。
    2. **守り方がコウ取りを打てる状態になる**（`tsumego_defender_ko_points`、深さ
       `TSUMEGO_KO_AVAIL_PLIES` まで）— PV がそのコウを打たなくても数える。リージョン解析は
       守り方からコウダテを取り上げるので、**コウが争点の局面ほど KataGo はそのコウを
       打たない**（実測 case U: 白のコウ抵抗は visits比 0.01・白の損と評価され、比 0.00 まで
       全応手を歩いても PV 由来では 0/5 run 検出できない）。
       ただし**候補手より前から打てたコウは数えない** — 局面の性質であって候補の性質では
       ないので、数えると全候補が一律コウ経路になりクラス裁定が候補を区別できなくなる
       （実測 case T の L1 / case F2 の N9 / case Q の M13。それらは判定1が別途拾っている）。

    コウ形 = 取った石が単独・呼吸点1で、相手の取り返しが KaTrain の着手判定でコウとして
    禁じられる形。詰碁の正解順序（無条件 > コウ）を同着バンドで効かせるための構造判定で、
    コウでも勝てると KataGo が読み切った局面ではスコア・gain・ownership のどれにも
    クラス差が出ない（実測 case K 2026-07-30: コウで殺す A12 と無条件の C13 が同着）。
    親局面の PV は使えないことに注意 — KataGo は読み切った詰碁への応対を放棄して
    枠へ手抜きするため、肝心のコウが現れない（実測: A12 の親 PV は白 K12 手抜き）。
    リージョン限定の子局面解析（depth1 で守り方が局所応答を強制される）の応手 PV を渡すこと。

    リージョン外のコウ形は枠格子の偶発物なので数えない（実測 probe: 枠内 L5 の偶発コウが
    詰碁と無関係に検出された）。region_of_interest が無い枠なしモードでは盤全体を対象にする。
    sim は使い捨ての局面を渡すこと（この関数は sim に読み筋を書き足す）。PV が現盤面と
    食い違って打てない場合は判定不能としてコウ扱いしない。
    """
    if not pv:
        return False

    def in_region(coords):
        return region_of_interest is None or (
            region_of_interest[0] <= coords[0] <= region_of_interest[1]
            and region_of_interest[2] <= coords[1] <= region_of_interest[3]
        )

    defender = "W" if first_player == "B" else "B"
    # 候補手より前から守り方が打てたコウ取り。これは局面の性質なので候補の判定から除く
    already_available = tsumego_defender_ko_points(sim, defender, region_of_interest)
    for i, gtp in enumerate(pv[:max_plies]):
        if gtp == "pass":
            break
        mover = first_player if i % 2 == 0 else defender
        opponent = "W" if mover == "B" else "B"
        move = Move.from_gtp(gtp, player=mover)
        try:
            played = sim.play(move)
        except IllegalMoveException:
            return False
        chain, liberties = _chain_and_liberties(sim, move.coords)
        if chain is not None and len(chain) == 1 and len(liberties) == 1 and in_region(move.coords):
            try:
                sim.play(Move(coords=liberties[0], player=opponent))
            except IllegalMoveException as e:
                if "Ko" in str(e):
                    return True
                # 自殺手等でそもそも取り返せない形。盤面は変わっていないので PV を続ける
            else:
                sim.set_current_node(played)  # 取り返せた＝コウではない。試した手を外して続行
        # 攻め方が打ち終わって守り方の手番になったところで、新しく立ったコウ取りを見る
        if mover == first_player and i + 1 <= TSUMEGO_KO_AVAIL_PLIES:
            if tsumego_defender_ko_points(sim, defender, region_of_interest) - already_available:
                return True
    return False


def tsumego_candidate_reaches_region_ko(game, node, candidate_gtp, reply_pv, region_of_interest, max_plies=None):
    """候補手＋守り方の応手 PV を親局面から並べ直してコウ形を検査する。

    検査シーケンスは必ず候補手自身から始めること。コウ形は候補手そのものにも現れる
    （実測 case L 2026-07-30: B L5 が白 L6 を1子取りして自身が呼吸点1になる「打った瞬間に
    コウを開始する手」。守り方は次にコウ禁止で取り返せないため応手 PV にはコウ形が出ず、
    応手 PV だけを歩いた旧実装は L5 を無条件と誤判定した）。応手 PV 側のコウ形
    （実測 case K: A11 → B11）も同じ1回の歩きで拾う。
    """
    sim = tsumego_simulation_game(game, node)
    if sim is None:
        return False
    pv = [candidate_gtp] + list(reply_pv or [])
    if max_plies is None:
        max_plies = 1 + TSUMEGO_TIE_KO_PLIES  # 応手 PV の深さは従来どおり、先頭に候補手が乗る分を足す
    return tsumego_pv_reaches_region_ko(sim, node.next_player, pv, region_of_interest, max_plies)


def tsumego_eligible_candidates(candidates, max_points_behind, min_visits):
    """目数ガード・min_visits・ownership 有無を通した候補（gain の競争に参加できる手）"""
    searched = [c for c in candidates if c.get("visits", 0) >= min_visits]
    candidates = searched or candidates
    best_loss = min(c["pointsLost"] for c in candidates)
    return [c for c in candidates if c.get("ownership") and c["pointsLost"] <= best_loss + max_points_behind]


def tsumego_score_best(eligible):
    """目数ガードを通った中で最も目数の良い手＝gain の挑戦者が覆す相手。無ければ None"""
    return min(eligible, key=lambda c: c["pointsLost"]) if eligible else None


def tsumego_gain_contenders(eligible, score_best, min_visit_ratio):
    """目数最善手と探索の深さが比較できる候補だけに絞る（`TSUMEGO_GAIN_MIN_VISIT_RATIO` 参照）。

    visits 情報が無い解析結果ではゲートしない（解析がほぼ進んでいない局面で候補ゼロにすると、
    呼び出し側が「ownership が取れない」と誤認して最善手フォールバックに落ちる）。
    """
    ref = (score_best or {}).get("visits", 0)
    if not ref or min_visit_ratio <= 0:
        return list(eligible)
    return [c for c in eligible if c is score_best or c.get("visits", 0) >= min_visit_ratio * ref]


# gain 争いに参加できなかった候補の救済: gain が選択手をこれ以上上回っていたら同深さ検証にかけ、
# 検証も同じマージンで上回ったときだけ採用する（トリガーと採用の両方に使う）。
# 実測 2026-07-30:
# - case G2（枠なし盤 2手目）: 枠なしでは「殺し損ねても外の空き地で取り返せる」ため目数差が
#   圧縮され、正解 C13 の pointsLost が 1.56〜2.26 とガード帯（best+2.0）を挟んで揺れる＝
#   コイン投げで足切り。gain はリージョン内の石だけの集計なので汚染されず C13 +5.79〜+6.60 vs
#   選択手 B13 -3.19〜-4.09 と差約10。同深さ検証は C13 +8.4 で3run安定
# - case H（枠なし盤 5手目）: 正解 N4 はガード内なのに visit比 0.46〜0.49 < 0.5 で深さゲートに
#   足切り。gain +4.4 で断トツ、同深さ検証 N4 +14.1 vs F7 +9.6（差+4.5）で3run安定
# 採用マージンが通常の覆し（gain_verify_margin 0.3）より厳しいのは、救済は深さゲートを迂回する
# ため偽 gain の候補（case F: N6 +11〜14）も検証まで来るから。偽は検証で -0.24 と負けるので
# +1.0 要求なら noise（±0.3）の安全域が広い。本物は +4.5 / +8.4 で余裕
TSUMEGO_GAIN_RESCUE_MARGIN = 1.0

# 救済で同深さ検証にかける候補数の上限（検証は1候補あたり同深さ解析1本のコスト）。
# トップ1だけでは足りない: 実測 case F2（2026-07-30）で v10 のノイズ手 N9(g+6.77) が gain 1位に
# 立ち、N9 の却下で救済が終わって、2位3位の本物 N11(g+5.41)/M12(g+5.30) が検証の機会を失い
# 誤答 J11 を打った。検証自体は毎回正しく序列化する（N9 -26.9 / N11 -17.1 / M12 -17.2 /
# J11 -19.4）ので、複数候補を検証に渡せば最良の本物が残る
TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES = 3

# 救済候補に課す visits の**床**（root で最も探索された手に対する比）。順位づけではなく桁の切り捨て。
#
# 救済は「深さゲートで足切りされた本物」を拾うために visit比条件を課さない設計だが、その根拠は
# 「本物 0.21〜0.49 と偽 0.24〜0.36 は**重なるので順位づけには使えない**」であって、その帯の
# **1桁下**まで拾えという意味ではない。実測の救済候補の比:
#
#   G2 C13(正解) 0.90 ・ H N4(正解) 0.52 ・ F2 N11/M12(正解) 0.33/0.30
#   **R J13(誤答) 0.036〜0.05**  ← v48/最多 v1337
#
# 実測 case R（2026-07-31、答えがコウの詰碁）: J13 の gain は救済トリガーを超えるが、同深さ検証の
# 差が margin=1.0 をまたいで揺れ（-1.05〜+1.31）、採用された run では J13 自身がコウ経路なので
# D8/C8 へ格下げされて誤答した。**この揺れは wideRootNoise 由来ではない**（wRN=0 でも J13 の
# 子局面だけばらつき 0.63 が残る＝追記25）。答えがコウの詰碁では ply1 の ownership が成否を
# 運ばないので、検証の側では止められない。止められるのは入口の桁だけ。
#
# 0.15 は本物の最小 0.30 と case R の最大 0.05 の中間（両側に 2倍の余裕）。case F の
# 「比 0.31 の gain は既に片側ノイズ」という実測とも整合する（0.15 はさらにその半分）。
TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO = 0.15


def tsumego_rescue_candidates(
    candidates,
    contenders,
    chosen,
    root_ownership,
    stones,
    board_size,
    player_sign,
    min_visits,
    rescue_margin=TSUMEGO_GAIN_RESCUE_MARGIN,
    max_candidates=TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES,
    min_visit_ratio=TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO,
):
    """gain 争いに参加できなかった候補のうち、同深さ検証にかける価値のある手を gain 降順で返す。

    対象は contenders（目数ガード＋深さゲートを通った候補）に居ない手すべて。条件:
    (1) ownership があり min_visits 以上 (2) gain が選択手を rescue_margin 超えて上回る
    (3) visits が root 最多手の `min_visit_ratio` 以上。

    (3) は**順位づけではなく桁の切り捨て**。visit比で「本物か偽か」を決めることはできない
    （実測 case H: 本物 N4 の比 0.46 と case F の偽 N7 の比 0.24〜0.36 は重なる）ので、
    その帯の判定は従来どおり同深さ検証に委ねる。落とすのは**1桁下**だけ
    （`TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO` のコメント参照。実測 case R の誤答 J13 は 0.036）。
    visits 情報が無い解析結果では床をかけない。

    トップ1でなく複数返すのは、ノイズ手が gain 1位に立って本物を影に隠すため
    （`TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES` のコメント参照）。ここで返した手を**そのまま
    採用してはいけない**。呼び出し側が全員を同深さ検証（`_verified_choice`、マージンは
    rescue_margin）で測り、裏づけの取れた最良の手だけを採用する。
    """
    if chosen is None or not chosen.get("ownership") or not root_ownership or not stones:
        return []
    contender_moves = {c["move"] for c in contenders}
    chosen_gain = tsumego_ownership_gain(root_ownership, chosen["ownership"], stones, board_size, player_sign)
    top_visits = max((c.get("visits", 0) for c in candidates), default=0)
    visit_floor = min_visit_ratio * top_visits if top_visits and min_visit_ratio > 0 else 0
    scored = []
    for cand in candidates:
        if cand["move"] in contender_moves or not cand.get("ownership"):
            continue
        if cand.get("visits", 0) < min_visits:
            continue
        if cand.get("visits", 0) < visit_floor:
            continue
        gain = tsumego_ownership_gain(root_ownership, cand["ownership"], stones, board_size, player_sign)
        if gain <= chosen_gain + rescue_margin:
            continue
        scored.append((gain, cand))
    scored.sort(key=lambda item: -item[0])
    return [cand for _gain, cand in scored[:max_candidates]]


def tsumego_speculation_plan(
    candidate_moves,
    eligible,
    chosen,
    score_best,
    root_ownership,
    stones,
    board_size,
    player_sign,
    min_visits,
    min_visit_ratio,
    points_epsilon,
    rescue_margin=TSUMEGO_GAIN_RESCUE_MARGIN,
    include_rescue=True,
    include_ko_screen=True,
):
    """後段（救済・コウ経路検査）が撃つことになりそうな子局面クエリの温めプランを返す。

    **判定には一切使わない**読み取り専用の純関数。返した手は同一条件・低優先度で
    先回り解析され結果は捨てられる（実クエリが同一条件で再クエリするとエンジン側
    キャッシュで 0.1〜0.3 秒＝実測 2026-08-03 の QUERY:462/480）。ミスしても実クエリが
    従来どおりコールドで走るだけで、着手判定への影響は構造的にゼロ。

    救済の最終リスト（`tsumego_rescue_candidates`）は「検証後の選択手」の gain を閾値に
    使うため発火時点では決まらないが、検証後の選択手は {chosen, score_best, challengers}
    のどれかなので、**その中で gain 最小のものをアンカー**に計算すれば上位集合になる
    （閾値が最小＝候補が最多。cap も +1 して縁を保険する）。

    コウ経路検査の対象は最終選択手（＋格下げ時の対抗馬）だが、実測で最終選択手はほぼ
    chosen か score_best なので、その2手（同一なら1手）を検査と同一条件
    （`TSUMEGO_KO_REGION_UNTIL_DEPTH`・`TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`）で温める。
    ガード外の選択手は検査されない（`tsumego_class_screen_applies`）ので温めない。

    `rescue_margin` は実救済呼び出し（`select_tsumego_move` 経路、ユーザー設定
    `gain_rescue_margin`）と**必ず同じ値を渡すこと**。既定 `TSUMEGO_GAIN_RESCUE_MARGIN` と
    ずれると、閾値が実クエリよりプラン側で高くなるケース（ユーザー設定が既定より小さい等）で
    実救済が撃つ候補をプランが温めず、「温め集合は実救済リストの上位集合」という不変条件が
    破れる（精度への影響は無いが温め漏れでキャッシュがコールドのままになる）。

    要素は {"move", "until_depth", "wide_root_noise"}。None は「本譜と同じ既定」
    （`_start_region_root` と同じ意味論）。
    """
    if chosen is None or score_best is None or not stones or not root_ownership:
        return []
    plan = []
    if include_rescue:
        anchors = [chosen, score_best]
        if chosen["move"] != score_best["move"] and tsumego_needs_score_best_verify(
            chosen, score_best, points_epsilon
        ):
            anchors += tsumego_score_best_challengers(
                chosen, eligible, score_best, root_ownership, stones, board_size, player_sign, min_visit_ratio
            )
        with_gain = [
            (tsumego_ownership_gain(root_ownership, a["ownership"], stones, board_size, player_sign), a)
            for a in anchors
            if a.get("ownership")
        ]
        if with_gain:
            anchor = min(with_gain, key=lambda item: item[0])[1]
            for cand in tsumego_rescue_candidates(
                candidate_moves,
                tsumego_gain_contenders(eligible, score_best, min_visit_ratio),
                anchor,
                root_ownership,
                stones,
                board_size,
                player_sign,
                min_visits,
                rescue_margin=rescue_margin,
                max_candidates=TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES + 1,
            ):
                plan.append({"move": cand["move"], "until_depth": None, "wide_root_noise": None})
    if include_ko_screen and tsumego_class_screen_applies(chosen, eligible):
        for cand in {c["move"]: c for c in [chosen, score_best]}.values():
            plan.append(
                {
                    "move": cand["move"],
                    "until_depth": TSUMEGO_KO_REGION_UNTIL_DEPTH,
                    "wide_root_noise": TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
                }
            )
    return plan


# 段階3（前倒し投機）の発火閾値: root リージョン解析の visits 合計がこの割合に達したら
# Game 側ウォッチャが温め集合を発行する（スペック 2026-08-03-tsumego-stage3-early-speculation）。
# 実測 2026-08-03（Task 4a）: 唯一の PARTIAL 報告点の visits は position-dependent にばらつき
# （990v=0.55 に対し M@4 903v・V2@2 708v は届かず、独立試行(run1) 1/3 しか発火しない）。
# 実測 2026-08-03（Task 4b・A/B、各ケース独立試行3プロセス）: 0.35（630v）にすると M@4/O@2/V2@2
# とも 3/3 発火（V2@2 は 0.55 でも run 間分散で 708〜1233v とばらつき偶発的に 1/3 発火することは
# あるが、630v は 9/9 で安定して届く）。**主指標は正味秒（analyse+generate＝ユーザー体感時間）**:
# 3ケースとも改善（M@4 -0.57s・O@2 -0.33s・V2@2 -0.80s）。root ウォール単体（analyse 秒）は
# O@2/V2@2 で改善、M@4 だけ n=3 で +0.30s・n=6（0.35側のみ追加測定）で +0.20s に縮小する
# 再現性のある実効果（発火率が 0/3→6/6 と最大に増えたケースで、同時投機クエリの増加分だけ
# root が GPU を分け合う）。ただし劣化ゲート（+0.3s 超）には一度も抵触せず、generate 短縮が
# これを上回るため正味は改善。0.35 を採用（Task 4b 報告: .superpowers/sdd/
# 2026-08-03-tsumego-stage3-early-speculation/task-4b-report.md、追記3）
TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION = 0.35


def tsumego_early_speculation_items(candidate_moves, root_ownership, stones, board_size, player_sign, settings):
    """root 部分結果のスナップショットから前倒し温め集合を返す純関数（判定には一切使わない）。

    集合 = 検証バッチ本体（仮 chosen・目数最善・挑戦者。実検証と同一条件＝untilDepth 既定・
    wRN 既定・ownership=True で撃たれる）＋ 段階1+2 の温め集合（`tsumego_speculation_plan`）。
    仮選択は最終 1800visits と別物になりうるが、ずれた分はミス（捨てるだけ）で安全。
    設定キーと既定値は `_generate_move` の抽出と同一に保つこと（ずれると温め条件が実クエリと
    合わずキャッシュ全ミスになる）。
    """
    settings = settings or {}
    max_points_behind = settings.get("max_points_behind", 2.0)
    gain_epsilon = settings.get("gain_epsilon", 0.3)
    min_visits = settings.get("min_visits", 10)
    min_visit_ratio = float(settings.get("gain_min_visit_ratio", TSUMEGO_GAIN_MIN_VISIT_RATIO))
    points_epsilon = float(settings.get("points_epsilon", TSUMEGO_POINTS_EPSILON))
    rescue_margin = float(settings.get("gain_rescue_margin", TSUMEGO_GAIN_RESCUE_MARGIN))
    chosen = select_tsumego_move(
        candidate_moves, root_ownership, stones, board_size, player_sign,
        max_points_behind, gain_epsilon, min_visits, min_visit_ratio, points_epsilon,
    )
    if chosen is None:
        return []
    eligible = tsumego_eligible_candidates(candidate_moves, max_points_behind, min_visits)
    score_best = tsumego_score_best(eligible)
    items = []
    if score_best is not None:
        verify_moves = [chosen["move"]]
        if score_best["move"] not in verify_moves:
            verify_moves.append(score_best["move"])
        if chosen["move"] != score_best["move"] and tsumego_needs_score_best_verify(chosen, score_best, points_epsilon):
            for cand in tsumego_score_best_challengers(
                chosen, eligible, score_best, root_ownership, stones, board_size, player_sign, min_visit_ratio
            ):
                if cand["move"] not in verify_moves:
                    verify_moves.append(cand["move"])
        items += [{"move": m, "until_depth": None, "wide_root_noise": None} for m in verify_moves]
    items += tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, root_ownership, stones, board_size, player_sign,
        min_visits, min_visit_ratio, points_epsilon, rescue_margin=rescue_margin,
        include_rescue=settings.get("gain_verify", True),
        include_ko_screen=settings.get("tie_ko_screen", True),
    )
    # 現状の3経路（検証バッチ／救済／コウ検査）は構成上ここで衝突しない
    # （verify_moves は contenders 由来、rescue は `tsumego_rescue_candidates` が
    # contenders を除外、ko_screen は条件（until_depth/wRN）が別）が、温め集合を
    # 足すときに同一 (move, until_depth, wide_root_noise) を二重発行しないための
    # 安全網としてこの重複排除は残す
    seen, deduped = set(), []
    for item in items:
        key = (item["move"], item["until_depth"], item["wide_root_noise"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def select_tsumego_move(
    candidates,
    root_ownership,
    stones,
    board_size,
    player_sign,
    max_points_behind,
    gain_epsilon=0.3,
    min_visits=10,
    gain_min_visit_ratio=TSUMEGO_GAIN_MIN_VISIT_RATIO,
    points_epsilon=TSUMEGO_POINTS_EPSILON,
):
    """目数ガードを通した候補から ownership gain 最大の手を返す。選べなければ None。

    詰碁の正解判定は対象石群の死活で決まるが KataGo の目的関数は盤全体の目数であり、
    この不一致が誤答の主因になる（実測: 目数では誤答手が上位、ownership では正解手が上位）。
    目数ガードは「gain は大きいが大損する手」を弾くためのもので、最善手からの相対で見る
    （詰碁では最善手自体が目数を損することがあるため、絶対値では判定できない）。

    gain 差が gain_epsilon 以内の手は同着として扱い、目数の少ない方を選ぶ。root の時点で
    対象石が既に決着している局面（KataGo が勝ちを読み切っている＝解答の途中では普通に起きる）
    では正解手でも gain が動かず、上位手の gain 差が ±0.03 のノイズに埋もれて選択が
    コイン投げになるため（実測 2026-07-29、4 run 中1回で誤答手を選択）。

    その目数も points_epsilon 以内で並ぶなら「同着バンド」として扱い、visits 最多
    （KataGo の principal variation）を選ぶ。

    詰碁の正解順序 無条件 > コウ の裁定（コウ経路の格下げ）はここではやらない。かつては
    このバンド内だけで格下げしていたが、コウで殺す手の gain は「コウに勝つ前提」の実信号で
    バンドから抜け出してしまう（実測 case M 2026-07-30: gain +1.9 で単独首位）ため、
    呼び出し側が選択の最後に成功クラス全体へ適用する（`tsumego_declass_choice`）。

    visits タイブレークは複数の手が同じ死活結果に到達する局面向け。目数差もノイズになり、コイン投げの先が
    アプリの解答樹に無い「正しい別解」だと不正解になる（実測 case J 2026-07-30: N10/N11 が
    gain・目数とも 0.02 差で並び N11 を選択。両手とも殺しは成立しており 8000visits でも
    分離不能）。解答樹の本線は KataGo の本命手と一致しやすいので visits に寄せる。
    別解自体は原理的に防げないため、これは的中率を上げるヒューリスティック。

    min_visits 未満の手は候補から外す。1visit の手の ownership・スコアは探索結果ではなく
    NN の生評価1回で、gain が実手の10〜100倍のノイズになる（実測 2026-07-30: 探索済みの手が
    +0.00〜+0.06 のところ 1visit の手が +0.55／+1.19 で競り勝ち、-16.5目の手を打った）。
    目数ガードより前に落とすのは、1visit の楽観的なスコアが best_loss を押し下げて
    ガードを不当に狭めるのも防ぐため。全候補が min_visits 未満なら（＝解析がほとんど
    進んでいない）フィルタせず従来どおり全候補で判断する。

    さらに gain で目数最善手を覆せるのは、その手と探索の深さが比較できる候補だけに限る
    （`gain_min_visit_ratio`。理由と実測は `TSUMEGO_GAIN_MIN_VISIT_RATIO` のコメント参照）。
    """
    band = _tsumego_scored_band(
        candidates,
        root_ownership,
        stones,
        board_size,
        player_sign,
        max_points_behind,
        gain_epsilon,
        min_visits,
        gain_min_visit_ratio,
        points_epsilon,
    )
    if not band:
        return None
    return max(
        band,
        key=lambda scored_move: (
            scored_move[2].get("visits", 0),
            scored_move[1],
            scored_move[0],
        ),
    )[2]


def _tsumego_scored_band(
    candidates,
    root_ownership,
    stones,
    board_size,
    player_sign,
    max_points_behind,
    gain_epsilon,
    min_visits,
    gain_min_visit_ratio,
    points_epsilon,
):
    """select_tsumego_move の最終同着バンドを (gain, -pointsLost, cand) のリストで返す"""
    if not candidates or not root_ownership or not stones:
        return []
    eligible = tsumego_eligible_candidates(candidates, max_points_behind, min_visits)
    contenders = tsumego_gain_contenders(eligible, tsumego_score_best(eligible), gain_min_visit_ratio)
    scored = [
        (tsumego_ownership_gain(root_ownership, c["ownership"], stones, board_size, player_sign), -c["pointsLost"], c)
        for c in contenders
    ]
    if not scored:
        return []
    best_gain = max(scored_move[0] for scored_move in scored)
    finalists = [scored_move for scored_move in scored if best_gain - scored_move[0] <= gain_epsilon]
    best_points = max(scored_move[1] for scored_move in finalists)
    return [scored_move for scored_move in finalists if best_points - scored_move[1] <= points_epsilon]


def tsumego_selection_band(
    candidates,
    root_ownership,
    stones,
    board_size,
    player_sign,
    max_points_behind,
    gain_epsilon=0.3,
    min_visits=10,
    gain_min_visit_ratio=TSUMEGO_GAIN_MIN_VISIT_RATIO,
    points_epsilon=TSUMEGO_POINTS_EPSILON,
):
    """最終同着バンドの候補 dict を返す。generate_move がコウ検査（tie_ko_screen）の対象を知る入口。

    バンドが2手以上のときだけコウ検査（候補1つあたりリージョン解析1本）を走らせるための
    事前照会なので、select_tsumego_move と同じ計算を共有する（結果は決定的に一致する）。
    """
    return [
        scored_move[2]
        for scored_move in _tsumego_scored_band(
            candidates,
            root_ownership,
            stones,
            board_size,
            player_sign,
            max_points_behind,
            gain_epsilon,
            min_visits,
            gain_min_visit_ratio,
            points_epsilon,
        )
    ]


def tsumego_needs_score_best_verify(chosen, score_best, points_epsilon=TSUMEGO_POINTS_EPSILON):
    """目数最善でない選択手に同深さ検証（gain 覆しの裁定）が必要かを返す。

    検証が要るのは「目数を本当に犠牲にして gain で覆す」選択だけ。目数差が
    points_epsilon 以内の選択は同着バンドの visits タイブレークで、「gain が良いから
    覆す」ではなく「等価なので PV に寄せる」判断なので検証の対象外。等価な2手は
    検証でも margin(0.3) を超えて分離できず（実測 case J: N10 +43.97 vs N11 +43.92 の
    差 +0.05）、無条件に検証にかけると必ず却下 → 目数最善へ巻き戻しになり、
    同着タイブレークが丸ごと無効化される（2026-07-30 GUI 実測で再発）。
    """
    return chosen["pointsLost"] - score_best["pointsLost"] > points_epsilon


# gain 覆しの同深さ検証にかける挑戦者の上限。**救済の `TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES` と
# まったく同じ理由**（gain 1位のノイズ手が本物を影に隠す）で、こちらもトップ1指名にしてはいけない。
TSUMEGO_SCORE_BEST_MAX_CHALLENGERS = 3


def tsumego_score_best_challengers(
    chosen,
    eligible,
    score_best,
    root_ownership,
    stones,
    board_size,
    player_sign,
    min_visit_ratio,
    max_candidates=TSUMEGO_SCORE_BEST_MAX_CHALLENGERS,
):
    """gain 覆しの同深さ検証にかける挑戦者列（選択手を先頭に、残りは gain 降順の contenders）。

    選択手（＝gain 争いの勝者）だけを挑戦者にすると、**gain 1位がノイズ手だった run で
    2位以下の本物が検証の機会を失い、incumbent の目数最善に巻き戻る**。救済側は case F2 で
    同じ失敗を踏んで複数候補に直してある（`TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES`）のに、
    こちらは1手のままだった。

    実測 case W（2026-08-01・13路右下・枠なし・黒は守り方。正解 H1＝コウで黒生き）:

        当たり run  L1 の visit比 0.43〜0.48 → 深さゲート外 → gain 首位は正解 H1 → 検証 → H1
        外れ run    L1 の visit比 **0.53〜0.58** → 深さゲート内 → gain 首位が L1(g+4.63) に
                    入れ替わる（H1 は g+0.66 で2位）→ 検証 L1 -13.85 vs 目数最善 J1 -12.54 で
                    却下 → **incumbent の J1 に巻き戻り、H1 は一度も測られない** → 誤答 J1

    L1 は v95 前後の浅い候補で、gain の片側ノイズ（`TSUMEGO_GAIN_MIN_VISIT_RATIO` のコメント
    参照）が乗ったまま深さゲートの境界をまたぐ。閾値では分離できない（root 解析の visit 配分の
    分散そのもの）が、**同深さ検証は毎回正しく序列化する**（H1 -10.4〜-11.2 > J1 -12.5 > L1 -13.9）
    ので、2位以下も測れば本物が残る。これは case F2 で救済側が学んだのと同じ構図。

    ownership が無い候補（movesOwnership に載っていない）は gain を出せないので除く。
    """
    if score_best is None:
        return [chosen]
    contenders = tsumego_gain_contenders(eligible, score_best, min_visit_ratio)
    ranked = sorted(
        (c for c in contenders if c["move"] != score_best["move"] and c.get("ownership")),
        key=lambda c: -tsumego_ownership_gain(root_ownership, c["ownership"], stones, board_size, player_sign),
    )
    ordered = [chosen] + [c for c in ranked if c["move"] != chosen["move"]]
    return ordered[: max(1, max_candidates)]


def tsumego_class_screen_pool(chosen, eligible, max_candidates=TSUMEGO_TIE_KO_MAX_CANDIDATES):
    """コウ経路検査（クラスの裁定）にかける候補列: 選択手＋目数ガード内の対抗馬（visits 降順）。

    検査対象を同着バンド（gain 同着 ∩ 目数同着）に限っていた旧設計は case M（2026-07-30）で
    破れた: コウで殺す手の gain は L2/M3 の白石を「コウに勝つ前提」で取り切る**実信号**
    （同深さ検証でも +1.29 と裏づけられる）なので、gain がバンドの同着から抜け出して検査が
    走らず、検証・救済のどの経路もクラスを見ないまま採用してしまう。クラス（無条件 > コウ）は
    スコアの多寡ではなく到達局面の構造なので、成功している候補（目数ガード＝同じ成功クラスの
    proxy）全員が検査対象になる。上限は同着バンド検査と同じ `TSUMEGO_TIE_KO_MAX_CANDIDATES`。

    ただし**選択手が目数ガード外（eligible 非メンバー）のときは検査自体を成立させない**
    （pool は選択手のみ → 呼び出し側の「2手以上」条件で検査が走らない）。クラス裁定が意味を
    持つのは「スコアが同じ成功と見なす帯」の中だけで、帯の外から同深さ検証で拾った手
    （救済採用）は、スコアが嘘をつく枠なし局面（case G2 の圧縮）にいる。実測 case F2
    （2026-07-30）: 救済採用の正解 N11(pt+3.85、ガード外) が、応手が N9 に振れた run の
    PV の偶発コウ形で格下げされ、ガード内の clean な J10 — 同深さ検証 -18.8 で N11 -17.0 に
    負けている**失敗手** — に差し替わった。検証の実測をスコアの嘘で上書きしてはならない。
    """
    if not tsumego_class_screen_applies(chosen, eligible):
        return [chosen]
    rivals = sorted(
        [c for c in eligible if c["move"] != chosen["move"]],
        key=lambda c: -c.get("visits", 0),
    )
    return [chosen] + rivals[: max(0, max_candidates - 1)]


def tsumego_class_screen_applies(chosen, eligible):
    """クラス裁定（コウ経路検査）を走らせてよいか＝選択手が目数ガード内か。

    **「pool が2手以上か」を代わりに使ってはいけない**。それは2つの別々の状況を混同する:

      (a) 選択手がガード外（救済採用）→ 検査しない。スコアが嘘をつく枠なし局面から
          拾った手を、ガード内の「スコアだけ良い失敗手」で上書きしてはいけない
          （実測 case F2。`tsumego_class_screen_pool` の docstring 参照）
      (b) 選択手はガード内だが対抗馬が1手も居ない → **検査すべき**。むしろ
          「到達できる手が全部コウ」が最も純粋に成立する形で、コウ脱出
          （`_ko_escape_choice`）のトリガーそのもの

    旧実装は両方を `len(pool) >= 2` で落としていたため、root が1手に visits を集中させて
    eligible が1手に潰れた局面ではクラス裁定も脱出も丸ごと no-op になっていた
    （実測 2026-07-31 case T: eligible=[J2] のみ。J2 はコウ経路で正解 L1（セキ＝clean）は
    目数ガード外に居たので、脱出さえ走れば prior 2位で拾えた）。
    """
    return any(c["move"] == chosen["move"] for c in eligible)


def tsumego_declass_choice(chosen, pool, ko_routes, points_epsilon=TSUMEGO_POINTS_EPSILON):
    """選択手がコウ経路なら、pool の clean な対抗馬（visits 最多、次いで目数）に格下げする。

    詰碁の正解順序 無条件 > コウ の適用。gain・目数・同深さ検証はすべて「コウに勝った」
    前提のスコアを含むためクラスを分離できず（実測 case K: 0.1 目差 / case M: 検証 +1.29 で
    コウ側を追認）、分離できるのは到達局面の構造検出（ko_routes）だけ。全員コウ経路
    （＝同じクラス）や clean な対抗馬が居ない場合は選択手を維持する。

    **ただし格下げ先は同着バンド（`points_epsilon`）内に限る**。クラス裁定は同着の裁定で
    あって、実測の目数差を覆す権限は無い。「無条件」は「詰碁と無関係で何も起きないので
    自明に clean」でも成立してしまい、**答えがコウの詰碁では ply1 に成否が現れない**ので
    格下げ先が本物かを ownership で検算することもできない（実測 case R 2026-07-31、13路上辺
    枠なし・正解 G13→白 J12→黒 J13 のコウ: 同深さ800visits の全リージョン石 ownership は
    正解 G13 +0.86/+0.97 に対し誤答 D8 +1.32/+2.34 と**誤答のほうが高く**、相手石は全候補で
    −0.55〜−0.72＝どの手でも白は生きている。`tsumego_ko_escape_accepts` を流用しても
    D8 は素通りする）。

    符号が一貫している唯一の指標は目数だった。格下げが正しかった実測4ケースは格下げ先が
    例外なく目数で**優る**（K −0.05 / L −0.11 / M −0.57 / P −0.03）のに対し、case R の D8 は
    +0.52 劣る。無条件の正解がコウ手より目数で下に出るのは「コウに勝った前提」の下駄ぶん
    （実測 case O の同深さ ownership で 0.10）なので、同着バンド幅で足りる。
    """
    if chosen["move"] not in ko_routes:
        return chosen
    clean = [
        c
        for c in pool
        if c["move"] not in ko_routes and c["pointsLost"] - chosen["pointsLost"] <= points_epsilon
    ]
    if not clean:
        return chosen
    return max(clean, key=lambda c: (c.get("visits", 0), -c["pointsLost"]))


def tsumego_declass_confirmed(per_stone, threshold=TSUMEGO_SUCCESS_OWNERSHIP):
    """格下げ先が本当に「無条件で解いた手」かを成否の絶対 ownership（1子平均）で確かめる。

    `tsumego_declass_choice` が要求するのは「clean であること」と「目数同着バンド内であること」
    だけだが、**「無条件」は「攻めないので何も起きず自明に clean」でも成立する**。case R は
    その非解が目数で劣ったので同着バンドで塞げた。**非解が目数でむしろ優る**局面は塞げない。

    実測 case V（2026-07-31、13路右上・枠あり・黒は攻め方。正解 L12＝コウ/最終セキで白の
    無条件生きを防ぐ形、旧実装は K10 へ格下げして白が無条件で生きた）:

        目数        K10 -0.33 ＜ L12 -0.29（格下げ先のほうが 0.04 良い＝バンド 0.25 の内側）
        役割石      L12 -0.99/-1.00 ・ K10 **-1.00/-1.00**（同深さ800visits・相手石7子・2run）

    ＝格下げ先は白を殺していない。`select_tsumego_move` 単体は正解 L12 を選んでおり
    （`frame_validity_probe.py` で確認）、差し替えていたのは格下げだけだった。

    格下げが正しかった実測4ケースの格下げ先は、同じ尺度で例外なく成立している:

        K C13 +0.99/子（攻め方・相手石8子）   L J6 +0.99/子（攻め方・15子）
        M K1  +0.98/子（守り方・自石8子）     P J1 +0.99/子（攻め方・9子）

    採るべき +0.98 と落とすべき -1.00 の間に約 2.0 の空白があり、閾値は成功判定と同じ
    `TSUMEGO_SUCCESS_OWNERSHIP`（1子平均 0.5）がその中間に入る。

    **答えがコウの詰碁では正解も ply1 では成立しない**（case V の L12 も -1.00）が、この判定は
    格下げ**先**にしか課さないので、そのときは「格下げしない＝コウを維持する」に倒れる。
    格下げ先の成否だけを見るのが肝で、両者を比べる相対判定にすると case R のように
    **非解のほうが高く出る**（全リージョン石で 正解 +0.86 < 誤答 +1.32）。

    **役割が読めない枠なし盤でもこの確認は要る**。旧実装は `solver_attacks is None` で確認を
    丸ごとスキップしていた（＝バンドだけで格下げしていた）が、それは case R が「非解は目数で
    劣る」形だったから成立していただけで、**枠なしでも非解が目数で優る**局面がある。

    実測 case W（2026-08-01、13路右下・**枠なし**・黒は守り方。正解 H1＝白 G1 → 黒 K1 のコウで
    黒生き、旧実装は J1 へ格下げして黒が無条件死。E2E 3/3 で決定的）:

        目数        J1 +1.94 ＜ H1 +2.20（格下げ先のほうが 0.26 良い＝目数最善なのでバンド内）
        自石(7子)   H1 **+0.51/+0.35** ・ J1 **-0.22/-0.21**（同深さ800visits・2run）
        相手石(9子) H1 -0.83/-0.85 ・ J1 -0.92（守り方なので相手が生きるのは正常）

    ＝格下げ先 J1 は「clean だが黒が死ぬ」＝詰碁の順序で**最下位の失敗クラス**で、コウの H1 の
    下にいる。役割が読めないので測る尺度は `tsumego_success_ownership` の役割不明ヘッジ
    （自石・相手石の1子平均の**小さいほう**）＝ J1 は -0.92 で閾値 0.5 に遠く届かない。

    ヘッジが枠なしで妥当なのは、外し方が「格下げしない＝コウを維持」に倒れるから（守り方の
    正解が無条件生きなら相手も生きているので min は負に振れ、確認が通らず格下げを見送る）。
    格下げが正しかった実測4ケースは**全部枠あり**（役割が読めるので min ではなく役割石で測る）
    なので、この保守側への倒れが既存の正解を壊さないことは E2E 全ケースで確認する。

    測れなかった（`per_stone is None`＝ownership が無い／石が1つも無い）ときだけ確認手段が
    無いので従来動作（バンドのみ）を維持する。
    """
    if per_stone is None:
        return True
    return per_stone >= threshold


# 到達局面のクラス（小さいほど上位）。**順序の中身は役割で読み替えるが、失敗が最下位なのは共通**:
#
#     攻め方  無条件に殺す > コウ > （セキ）> **相手が無条件で生きる＝失敗**
#     守り方  無条件に生きる > セキ > コウ > **自石が無条件で死ぬ＝失敗**
#
# 成否は役割石（攻め方＝相手石／守り方＝自石）の1子平均 ownership で測るので、クラスの計算自体は
# 役割に依存しない（`tsumego_role_stones` が役割を吸収している）。
TSUMEGO_CLASS_UNCONDITIONAL = 0
TSUMEGO_CLASS_KO = 1
TSUMEGO_CLASS_FAILED = 2


def tsumego_result_class(is_ko, succeeds):
    """到達局面のクラスを返す（`TSUMEGO_CLASS_*`、小さいほど上位）。

    コウ経路で**かつ**成立していると読めた手は「コウ」に置く（`TSUMEGO_CLASS_KO`）。
    詰碁の順序で「無条件」を名乗れるのは構造的にコウが現れない手だけで、コウ手のスコアや
    ownership は「コウに勝った前提」で高く出る（実測 case O: コウの B12 +41.95 > 正解 A11 +41.85）
    ため、成立の読みでクラスを繰り上げてはいけない。
    """
    if is_ko:
        return TSUMEGO_CLASS_KO
    return TSUMEGO_CLASS_UNCONDITIONAL if succeeds else TSUMEGO_CLASS_FAILED


def tsumego_class_screen_all_ko(pool, ko_routes):
    """検査した pool が全員コウ経路か＝コウ脱出（`_ko_escape_choice`）のトリガー。

    脱出の前提は「到達できる手が全部コウなら、無条件の正解はプールの外にいる」（case O）。
    **「格下げしなかった」を代わりに使ってはいけない** — 目数で劣る clean 手が居るために
    格下げを断った場合（case R）は前提が偽で、成否と無関係な ownership で root policy の
    上位を拾って的外れな手に飛ぶ。格下げを断った理由を区別するための述語。
    """
    return all(c["move"] in ko_routes for c in pool)


def tsumego_ko_escape_applies(pool, ko_routes, solver_attacks=None):
    """コウ脱出（`_ko_escape_choice`）を走らせてよいか。

    素直な前提は `tsumego_class_screen_all_ko`＝「到達できる手が全部コウなら無条件の正解は
    プールの外」。clean な対抗馬が居るのに格下げを断った場合（目数同着バンドの外＝case R）は
    その前提が偽なので脱出しない、というのが従来の裁定だった。

    **その「前提が偽」の推論は攻め方の話でしかない**。「clean なのに目数で劣る手は詰碁を
    解いていない」が成り立つのは、成功＝相手を殺す＝目数が増える、のとき。守り方の正解が
    セキだと clean のまま目数で必ず劣る（地は0目・相手も生きる）ので、この推論は正解を
    「詰碁と無関係な手」と誤認する。実測 case T（黒が守り・正解 L1＝セキ）: 対抗馬 N4 が
    ko 検出の揺れで clean と読まれた run だけこの分岐に落ち、脱出が走らず誤答 J2 が残った
    （4run 中1回。他の3run は N4 もコウ経路と読まれて all_ko → 脱出 → 正解 L1）。

    そこで**役割が分かっているなら脱出を走らせる**。誤爆しないのは、脱出の採否が役割ごとの
    石（攻め方=相手石／守り方=自石）の同深さ ownership で決まるから: 答えが本当にコウの詰碁
    では clean な候補は成功しないので検証で落ちる（実測 case T の同深さ800visits・自石12子:
    正解 L1 +11.97 に対し失敗する clean 手は -11.93＝24 の空白）。case R がこの安全弁を
    使えなかったのは**枠なしで役割が読めず**、全リージョン石の合計では成否が分離できなかった
    ため（正解のコウ +0.86 < 誤答の clean +1.32）。役割不明の局面は従来どおり脱出しない。
    """
    return tsumego_class_screen_all_ko(pool, ko_routes) or solver_attacks is not None


# コウ一色バンドからの脱出。選択手も目数ガード内の対抗馬も**全部**コウ経路だったとき、その事実
# 自体が「無条件の正解は候補プールの外にいる」という信号になる（詰碁の正解順序は 無条件 > コウ
# なので、無条件の手があるならそれが答え）。
#
# 実測 case O（2026-07-31、13路左上・黒番初手。正解 A11 に対し AI は B12 を打ち、白 A11 でコウに
# されて不正解）: root 1800visits の visit 配分は B12 1172 / C10 622 で、**残り46手はすべて v1**。
# 正解 A11 は root を 12000visits にしても v1 のまま＝深さでは絶対に届かない。原因は root の
# value 推定が約29目ずれていること:
#
#   A11  root 1visit の評価      pt +28.74  白石 own -7.03（＝白は生き）
#   A11  子局面を独立に 1800v    lead +11.53  白10子すべて +0.99（＝白は全滅）
#
# この 1visit の数字で min_visits(10)・目数ガード(best+2.0)・gain・救済・コウ検査プールの
# すべてから締め出されるため、選択パイプラインのどの経路にも A11 は入れない。
#
# 探す先は root policy の上位。実測 prior は B12 .68 / C10 .20 / B13 .043 / C13 .011 /
# A11 .0076-.0091 / A8 .0008 / **残り42手すべて .0001（NN の下限）** で、正解 A11 は 2/2 run とも
# 5位で固定。value は壊れていても policy は「読む価値のある手」を正しく挙げている。下限手との間に
# 10倍近い崖があるので、prior の下限と本数上限で「未検査だが policy が認めた手」だけを拾える。
TSUMEGO_KO_ESCAPE_MAX_CANDIDATES = 4
TSUMEGO_KO_ESCAPE_MIN_PRIOR = 0.001

# 脱出候補の採用条件は「incumbent を**上回る**」ではなく「tolerance 超えて下回らない」。
# コウ手のスコアは「コウに勝った前提」で出るので無条件の正解よりむしろわずかに高い
# （実測 case O の同深さ 800visits: コウの B12 +9.95 / C10 +9.94 に対し無条件の正解 A11 +9.91）。
# 既存の覆し（`tsumego_override_confirmed`: gain_verify_margin=0.3 超えで上回ること）をそのまま
# 使うと正解が却下される。順序を決めるのはスコアではなくクラス（無条件 > コウ）で、スコアは
# 「その手で本当に詰碁が成立しているか」の確認にだけ使う。失敗する clean 手は同じ尺度で
# -9.98〜-10.00（差 20）に落ちるので 0.5 で十分に分離できる。
#
# この非対称性が安全弁でもある: 答えが本当にコウの詰碁（case E/L/M）では、clean な候補は
# 詰碁が成立しないので ownership 検査を通らず、脱出は何もせずコウを維持する。
TSUMEGO_KO_ESCAPE_TOLERANCE = 0.5


def tsumego_ko_escape_candidates(
    candidates,
    screened_moves,
    min_prior=TSUMEGO_KO_ESCAPE_MIN_PRIOR,
    max_candidates=TSUMEGO_KO_ESCAPE_MAX_CANDIDATES,
):
    """コウ経路検査を通っていない候補のうち、root policy が認めた上位手を prior 降順で返す。

    root 探索の visits・pointsLost・gain は当てにできない（それらが壊れているから正解が
    漏れている）ので、**policy だけ**で絞る。ここで返した手を**そのまま採用してはいけない**。
    呼び出し側が1本ずつ子局面を同深さで解析し、「clean かつ詰碁が成立している」ことを
    確かめた手だけを採る（`TSUMEGO_KO_ESCAPE_MAX_CANDIDATES` のコメント参照）。
    """
    pool = [
        c
        for c in candidates
        if c.get("move")
        and c["move"] != "pass"
        and c["move"] not in screened_moves
        and c.get("prior", 0.0) >= min_prior
    ]
    pool.sort(key=lambda c: -c.get("prior", 0.0))
    return pool[: max(0, max_candidates)]


def tsumego_ko_escape_accepts(value, incumbent_value, tolerance=TSUMEGO_KO_ESCAPE_TOLERANCE):
    """脱出候補（clean）の同深さ ownership が、コウの選択手に tolerance 超えて劣らないか。

    不等号の向きに注意（`TSUMEGO_KO_ESCAPE_TOLERANCE` のコメント参照）。コウ手のほうが
    スコアは高く出るのが正常で、それでも無条件を採るのが詰碁の順序。

    **これは相対比較なので単独では使えない**。incumbent 自身が失敗している局面では全候補が
    横並びになって退化する（`tsumego_ko_escape_succeeds` 参照）。
    """
    return value >= incumbent_value - tolerance


def tsumego_ko_escape_succeeds(value, stone_count, threshold=TSUMEGO_SUCCESS_OWNERSHIP):
    """脱出候補が**実際に詰碁を解いているか**（役割石の1子平均 ownership の絶対判定）。

    脱出の採否を `tsumego_ko_escape_accepts` の相対比較だけに任せると、**incumbent 自身が
    失敗している局面で退化する**。相対条件は「incumbent に tolerance 超えて劣らないこと」
    なので、全員が同じくらい失敗していれば全員が合格になり、ノイズ幅の差で1手が「最良」に
    選ばれてしまう。

    実測 case F（2026-07-31、`frame_destroys_problem` 導入前の壊れた枠の盤・黒は守り方で
    自石10子）: 選択手 N8 −9.72 に対し policy 上位の J11 −9.82 / J10 −9.86 / N11 −9.90 /
    M12 −9.89 が**全部 tolerance 0.5 の内側**に並び、0.08 差で J11 が採用されて N8 が
    捨てられた（2/2 run。同深さ800visits で全候補が **1子平均 −0.97〜−0.99＝どれも詰碁を
    解いていない**、目数も −30目）。脱出は「無条件で成立する手を探す」機構なので、成立して
    いない手は相対値がどうであれ採ってはいけない。

    閾値は成功判定と同じ `TSUMEGO_SUCCESS_OWNERSHIP`（1子平均 0.5）。実測の分離幅は桁違いで、
    採るべき手（case O の正解 A11 +0.99/子 ・ case T の正解 L1＝セキ +1.00/子 ・ コウの
    incumbent B12/C10 +0.99〜+1.00）と落とすべき手（case O の失敗する clean 手 C13/B13
    −1.00/子 ・ case F の全候補 −0.97〜−0.99）の間に約 1.9 の空白がある。

    役割石が取れない（stone_count=0）ときは判定できない＝採用しない（incumbent 維持側に倒す）。
    """
    if not stone_count:
        return False
    return value / stone_count >= threshold


def tsumego_book_next_move(game):
    """回答帳の次手 (ヒットしたか, coords)。パスが記録されていれば (True, None)。

    白の応手が全 line から逸脱した／記録手の点が占有済み（認識ずれ）なら
    (False, None) ＝ 呼び出し側は従来パイプラインへ。毎手呼び直すので、白が
    記録の枝に戻れば再ヒットする（回答帳スペック§7）。解析クエリは使わない。
    """
    entry = getattr(game, "tsumego_book_entry", None)
    transforms = getattr(game, "tsumego_book_transforms", None)
    if not entry or not transforms:
        return False, None
    try:
        from katrain.core import tsumego_answer_book as answer_book
        from katrain.core.tsumego_solver_api import moves_from_game

        size = game.board_size
        if not isinstance(size, int):
            size = size[0]
        found, coords = answer_book.next_move(entry, transforms, moves_from_game(game), size)
        if not found:
            return False, None
        if coords is not None and any(m.coords == coords for m in game.stones):
            return False, None  # 認識ずれ等で占有点になっている＝記録が現盤に合わない
        return True, coords
    except Exception as e:
        try:
            game.katrain.log(f"tsumego_answer_book: 再生照合でエラー（{e}）", OUTPUT_DEBUG)
        except Exception:
            pass
        return False, None


def tsumego_book_status(game):
    """回答帳の再生状況（GUI バナー用）。"" / "playing" / "done" / "off"。

    "" は「この問題は回答帳に無い（＝通常の詰碁パイプライン）」。着手判定には使わず
    表示だけに使うが、"playing" の条件は `tsumego_book_next_move` と一致させる
    （占有ずれで再生できない局面を「解答中」と表示しないため）。解析クエリは使わない。
    """
    entry = getattr(game, "tsumego_book_entry", None)
    transforms = getattr(game, "tsumego_book_transforms", None)
    if not entry or not transforms:
        return ""
    try:
        from katrain.core import tsumego_answer_book as answer_book
        from katrain.core.tsumego_solver_api import moves_from_game

        size = game.board_size
        if not isinstance(size, int):
            size = size[0]
        status = answer_book.line_status(entry, transforms, moves_from_game(game), size)
        if status == "playing" and not tsumego_book_next_move(game)[0]:
            return "off"
        return status
    except Exception:
        return ""


@register_strategy(AI_TSUMEGO_SOLVER)
class TsumegoSolverStrategy(AIStrategy):
    """詰碁専用 死活ソルバ戦略（スペック 2026-08-01-tsumego-solver-design.md §9.1）。

    KataGo を使わず死活を厳密に解いて着手する。問題コンテキスト（Problem・型・region）は
    出題時に確定してセッションに保持し、以後の手番は局面だけ差し替えて解く。
    解けない盤・打ち切り・FAILED 裁定は現行 ai:tsumego へフォールバックする（G5）。
    """

    def generate_move(self) -> Tuple[Move, str]:
        started = time.time()
        try:
            return self._generate_move()
        finally:
            self.game.katrain.log(
                f"[{self.strategy_name}] 着手決定に {time.time() - started:.1f} 秒", OUTPUT_INFO
            )

    def _solver_settings(self) -> Dict:
        katrain = self.game.katrain
        try:
            settings = dict(katrain.config("tsumego_capture") or {})
        except Exception:
            settings = {}
        settings.update(self.settings or {})
        return settings

    def _generate_move(self) -> Tuple[Move, str]:
        from katrain.core import tsumego_solver_api as solver_api

        katrain = self.game.katrain

        def logger(msg, level=None):
            katrain.log(msg, OUTPUT_ERROR if level == "error" else OUTPUT_INFO)

        book_hit, book_coords = tsumego_book_next_move(self.game)
        if book_hit:
            katrain.log(f"[{self.strategy_name}] 回答帳の記録手順から着手します", OUTPUT_INFO)
            return Move(book_coords, player=self.cn.next_player), "回答帳: 記録された正解手順"

        settings = self._solver_settings()
        session = getattr(self.game, "tsumego_solver_session", None)
        if session is None and settings.get("solver_enabled", True):
            session = solver_api.build_session_from_game(self.game, settings, logger)
            # 抽出失敗は False で記憶し、毎手の再抽出を避ける（局面は同じ問題のまま進むため）
            self.game.tsumego_solver_session = session if session is not None else False
        if session:
            session.sync_moves(solver_api.moves_from_game(self.game))
            # 同格の別解のタイブレーク用に KataGo の本命順と visits を渡す（§6.5.1-3。
            # 解析がまだ無ければ渡さない＝ソルバの着手を解析待ちでブロックしない）。
            # visits は証明ストア即答の同格差し替え（_prefer_ranked_gate_move）の決定性
            # ゲートに使う（拮抗した別解の入れ替えを防ぐ）
            session.move_ranker = None
            session.move_visits = None
            try:
                if self.cn.analysis.get("root") is not None:
                    order = {c["move"]: i for i, c in enumerate(self.cn.candidate_moves)}
                    session.move_ranker = lambda coords: order.get(Move(coords).gtp(), 10**6)
                    session.move_visits = {
                        Move.from_gtp(c["move"]).coords: c.get("visits", 0)
                        for c in self.cn.candidate_moves
                        if c.get("move") and c["move"].lower() != "pass"
                    }
            except Exception:
                pass
            coords, thoughts = session.generate()
            if coords is not None:
                return Move(coords, player=self.cn.next_player), thoughts
            if not thoughts.startswith("FALLBACK"):
                return Move(coords=None, player=self.cn.next_player), thoughts  # パスが本手 / コウ待ち
        if not settings.get("solver_fallback", True):
            return Move(coords=None, player=self.cn.next_player), "ソルバ未解決（フォールバック無効のためパス）"
        katrain.log(f"[{self.strategy_name}] 現行 {AI_TSUMEGO} へフォールバックします", OUTPUT_INFO)
        fallback_settings = dict(katrain.config(f"ai/{AI_TSUMEGO}") or {})
        return TsumegoOwnershipStrategy(self.game, fallback_settings).generate_move()


@register_strategy(AI_TSUMEGO)
class TsumegoOwnershipStrategy(AIStrategy):
    """詰碁用: 盤全体の目数ではなく対象石群の死活（ownership の変化量）で手を選ぶ"""

    def generate_move(self) -> Tuple[Move, str]:
        # 体感速度の調査用に所要時間を必ず出す（キャプチャ側の「枠の採否判定に X 秒」と同じ意図）
        started = time.time()
        self._speculative_nodes = []
        book_hit, book_coords = tsumego_book_next_move(self.game)
        if book_hit:
            self.game.katrain.log(f"[{self.strategy_name}] 回答帳の記録手順から着手します", OUTPUT_INFO)
            return Move(book_coords, player=self.cn.next_player), "回答帳: 記録された正解手順"
        try:
            return self._generate_move()
        finally:
            # 未消化の投機を掃除＝この後の新規ノード解析（priority 1000）とGPUを取り合わない
            self._cancel_speculation()
            self.game.katrain.log(
                f"[{self.strategy_name}] 着手決定に {time.time() - started:.1f} 秒", OUTPUT_INFO
            )

    def _generate_move(self) -> Tuple[Move, str]:
        self.wait_for_analysis()
        # 選択手のコウ経路検査（wRN=0・untilDepth=6・ownership 付き）の生解析を手番内で使い回す
        # ための memo（`_region_child_verdict` が **visits・wRN・untilDepth の3つとも同条件のとき
        # だけ** 再利用する）。判定側は case Y 以降 `TSUMEGO_VERDICT_UNTIL_DEPTH`(12) で撃つので
        # 現状この共有は成立せず、クラス格上げの incumbent 検証は解析1本を撃ち直す（深さの違う
        # 解析を混ぜると失敗手を「相手は死んだ」と読む地平線バグが戻るので、共有より正しさを取る）。
        # 手番をまたいで持ち越さない
        self._screen_root_memo = {}
        candidate_moves = self.cn.candidate_moves
        if not candidate_moves:
            self.game.katrain.log(f"[{self.strategy_name}] 候補手が無いためパスします", OUTPUT_INFO)
            return Move(coords=None, player=self.cn.next_player), "候補手が無いためパス"

        max_points_behind = (self.settings or {}).get("max_points_behind", 2.0)
        gain_epsilon = (self.settings or {}).get("gain_epsilon", 0.3)
        min_visits = (self.settings or {}).get("min_visits", 10)
        min_visit_ratio = float((self.settings or {}).get("gain_min_visit_ratio", TSUMEGO_GAIN_MIN_VISIT_RATIO))
        points_epsilon = float((self.settings or {}).get("points_epsilon", TSUMEGO_POINTS_EPSILON))
        stones = tsumego_gain_stones([s.coords for s in self.game.stones], self.game.region_of_interest)
        player_sign = self.cn.player_sign(self.cn.next_player)
        # 手番側が攻め方か守り方か。詰碁の正解順序は役割で逆転する（攻め: 無条件死 > コウ > セキ /
        # 守り: 無条件生き > セキ > コウ）ので、「成否を担っている石はどちらか」がこれで決まる。
        # 枠が読めなければ None＝従来どおり役割非依存で動く（`tsumego_solver_attacks` 参照）
        solver_attacks = tsumego_solver_attacks(
            self.game.stones, self.game.region_of_interest, self.game.board_size, self.cn.next_player
        )
        role_text = {True: "攻め方（相手を殺す）", False: "守り方（自石を生かす）", None: "不明（役割非依存で判定）"}[
            solver_attacks
        ]
        self.game.katrain.log(f"[{self.strategy_name}] 手番側の役割: {role_text}", OUTPUT_DEBUG)
        ko_move = self._pick_ko_win_move(candidate_moves, min_visits, player_sign, solver_attacks)
        if ko_move is not None:
            return ko_move
        self._log_candidates(candidate_moves, stones, player_sign)
        selection_args = (
            candidate_moves,
            self.cn.ownership,
            stones,
            self.game.board_size,
            player_sign,
            max_points_behind,
            gain_epsilon,
            min_visits,
            min_visit_ratio,
            points_epsilon,
        )
        eligible = tsumego_eligible_candidates(candidate_moves, max_points_behind, min_visits)
        if len(eligible) <= 1:
            # 対抗馬が居ない＝この手番で戦略は何も判断していない（KataGo の最善手をそのまま返すだけ）。
            # gain・同深さ検証・救済・コウ経路検査・コウ脱出は全部「目数ガード内の候補を比べる」
            # 機構なので、eligible が1手に潰れると揃って不発になる。root が1手に visits を集中させ、
            # 残りが min_visits 未満に沈むと起きる（実測 case Q 2026-07-31: H13 が 1800visits 中 1764、
            # 12000visits でも 11943 を占め、正解 N9 は v1〜v4 で eligible から脱落。全盤 20000visits
            # でも N9 は v3・winrate 0.450 で、KataGo の value がこの準備手を読めていない）。
            # 「候補37手」だけを見ると選択則が37手から選んだように読めてしまい誤答の切り分けが
            # 遅れるので、不発だったことをログに残す
            self.game.katrain.log(
                f"[{self.strategy_name}] 対抗馬なし: 目数ガード＋min_visits={min_visits} を通ったのは "
                f"{[c['move'] for c in eligible] or '0手'}（候補{len(candidate_moves)}手中）。"
                f"gain・同深さ検証・救済・コウ経路検査は全て不発で、KataGo の最善手をそのまま返します",
                OUTPUT_INFO,
            )
        chosen = select_tsumego_move(*selection_args)
        if chosen is None:
            # ownership が無い（_enable_ownership が false 等）。無言で劣化させず既定動作に戻す
            self.game.katrain.log(
                f"[{self.strategy_name}] ownership が取得できないため最善手にフォールバックします"
                f"（engine/_enable_ownership を確認してください）",
                OUTPUT_INFO,
            )
            chosen = candidate_moves[0]
            gain_text = "ownership なし"
        else:
            escape_value, escape_label = None, "コウ脱出"
            score_best = tsumego_score_best(eligible)
            # 手番内投機: この後の段（救済・コウ経路検査）が撃つことになりそうな子局面を
            # 同一条件・低優先度で先回り発行して NN キャッシュを温める（結果は捨てる＝
            # 判定への影響ゼロ。実クエリの再クエリが 0.1〜0.3 秒で返る）。
            # 設計: docs/superpowers/specs/2026-08-03-tsumego-latency-overlap-design.md
            self._fire_speculation(
                tsumego_speculation_plan(
                    candidate_moves,
                    eligible,
                    chosen,
                    score_best,
                    self.cn.ownership,
                    stones,
                    self.game.board_size,
                    player_sign,
                    min_visits,
                    min_visit_ratio,
                    points_epsilon,
                    rescue_margin=float((self.settings or {}).get("gain_rescue_margin", TSUMEGO_GAIN_RESCUE_MARGIN)),
                    include_rescue=(self.settings or {}).get("gain_verify", True),
                    include_ko_screen=(self.settings or {}).get("tie_ko_screen", True),
                )
            )
            if (
                score_best is not None
                and chosen["move"] != score_best["move"]
                and tsumego_needs_score_best_verify(chosen, score_best, points_epsilon)
            ):
                # 挑戦者は選択手だけでなく gain 降順の contenders も渡す。gain 1位がノイズ手
                # だった run で2位以下の本物が機会を失い目数最善へ巻き戻る（実測 case W）＝
                # 救済側が case F2 で学んだのと同じ構図（`tsumego_score_best_challengers`）
                challengers = tsumego_score_best_challengers(
                    chosen,
                    eligible,
                    score_best,
                    self.cn.ownership,
                    stones,
                    self.game.board_size,
                    player_sign,
                    min_visit_ratio,
                )
                if len(challengers) > 1:
                    self.game.katrain.log(
                        f"[{self.strategy_name}] 同深さ検証: 挑戦者は gain 降順で "
                        + " ".join(c["move"] for c in challengers)
                        + f"（目数最善 {score_best['move']} が incumbent）",
                        OUTPUT_DEBUG,
                    )
                chosen = self._verified_choice(score_best, challengers, stones, player_sign, fallback=chosen)
            if (self.settings or {}).get("gain_verify", True):
                # 救済: gain 争いに参加できなかった候補（目数ガード外・深さゲート外）でも gain が
                # 明確に上回る手は同深さ検証にかける。検証なしでは絶対に採用しない（ガード外の
                # 大損な手や偽 gain の浅い手も含むため）。採用マージンも rescue_margin（厳格）。
                # 実測: case G2 は正解がガード帯を、case H は深さゲート（visit比0.49）を
                # わずかに外れてコイン投げで足切りされた。複数候補を検証に渡すのは case F2
                # 対策（ノイズ手が gain 1位に立ち、トップ1指名では本物が影に隠れて誤答した）
                rescue_margin = float((self.settings or {}).get("gain_rescue_margin", TSUMEGO_GAIN_RESCUE_MARGIN))
                rescues = tsumego_rescue_candidates(
                    candidate_moves,
                    tsumego_gain_contenders(eligible, score_best, min_visit_ratio),
                    chosen,
                    self.cn.ownership,
                    stones,
                    self.game.board_size,
                    player_sign,
                    min_visits,
                    rescue_margin,
                )
                if rescues:
                    # visit比も出す＝救済の床（`TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO`）の両側を
                    # ログだけで測れるようにするため（実測で本物と偽の帯が近い）
                    top_visits = max((c.get("visits", 0) for c in candidate_moves), default=0) or 1
                    self.game.katrain.log(
                        f"[{self.strategy_name}] 救済: "
                        + " ".join(
                            f"{c['move']}(pt{c['pointsLost']:+.2f}/v{c.get('visits', 0)}"
                            f"/{c.get('visits', 0) / top_visits:.2f})"
                            for c in rescues
                        )
                        + f" の gain が選択手 {chosen['move']} を gain_rescue_margin={rescue_margin} 超えて"
                        f"上回るため同深さ検証にかけます",
                        OUTPUT_INFO,
                    )
                    chosen = self._verified_choice(
                        chosen,
                        rescues,
                        stones,
                        player_sign,
                        incumbent_label="選択手",
                        margin=rescue_margin,
                        fallback=chosen,
                    )
            if (self.settings or {}).get("tie_ko_screen", True):
                # クラスの裁定（詰碁の順序 無条件 > コウ）は選択パイプラインの最後に置く。
                # コウで殺す手の gain・目数・同深さ検証値は「コウに勝った」前提の実信号なので
                # （実測 case M: gain +1.9 単独首位・検証 +1.29 で追認）、バンド・検証・救済の
                # どの経路で選ばれてもスコア系メトリックではクラス混同を検出できない。
                # 選択手が clean なら検査1本で終わる。対抗馬の検査は選択手がコウ経路のときだけ
                pool = tsumego_class_screen_pool(chosen, eligible)
                class_screen_applies = tsumego_class_screen_applies(chosen, eligible)
                # 選択手だけ敏感側の比で検査する（見逃すとクラス裁定が丸ごと no-op になるため）。
                # 格下げ先候補（pool[1:]）は保守側のまま＝過検出は脱出の誤爆に化ける
                if class_screen_applies and self._ko_route_screen(
                    [chosen], ratio=TSUMEGO_KO_REPLY_RATIO_CHOSEN, want_ownership=True
                ):
                    ko_routes = frozenset({chosen["move"]}) | self._ko_route_screen(pool[1:])
                    declassed = tsumego_declass_choice(chosen, pool, ko_routes, points_epsilon)
                    # clean は「無条件に解いた」の証拠にならない（攻めないので何も起きない手も
                    # clean になる）。格下げ先が本当に解いているかを同深さの ownership で
                    # 確かめてから差し替える（`tsumego_declass_confirmed`。役割が読めれば役割石、
                    # 読めなければ自石・相手石の厳しいほう＝枠なしの case W）
                    if declassed["move"] != chosen["move"] and not self._declass_target_confirmed(
                        declassed, solver_attacks, player_sign
                    ):
                        declassed = chosen
                    if declassed["move"] != chosen["move"]:
                        self.game.katrain.log(
                            f"[{self.strategy_name}] コウ経路検査: 選択手 {chosen['move']} を格下げし、"
                            f"無条件の {declassed['move']} を採用します（詰碁の順序: 無条件 > コウ）",
                            OUTPUT_INFO,
                        )
                        chosen = declassed
                    elif tsumego_ko_escape_applies(pool, ko_routes, solver_attacks):
                        # 目数ガード内が全部コウ＝正解（無条件）は候補プールの外にいる、という信号。
                        # root policy の上位から探し直す（`_ko_escape_choice`）。
                        # clean な対抗馬が居ても役割が分かっていれば探す（`tsumego_ko_escape_applies`）
                        clean_rivals = [c for c in pool if c["move"] not in ko_routes]
                        self.game.katrain.log(
                            f"[{self.strategy_name}] コウ経路検査: 選択手 {chosen['move']} はコウ経路で、"
                            + (
                                "clean な対抗馬 "
                                + " ".join(f"{c['move']}(pt{c['pointsLost']:+.2f})" for c in clean_rivals)
                                + " には格下げしていない（目数同着バンドの外＝守り方のセキは目数で"
                                "必ず劣るので「答えがコウ」の根拠にはならない、または格下げ先が"
                                "詰碁を解いていない）"
                                if clean_rivals
                                else "clean な対抗馬が居ない"
                            )
                            + "ため、プールの外を探します",
                            OUTPUT_INFO,
                        )
                        # 脱出の採否は「その手で詰碁が成立しているか」の判定なので、gain と違って
                        # **成否を担っている石だけ**で測る。全リージョン石だと守り方のセキが
                        # 相手33子に支配されてコウ生きより低く出て、正解が却下される
                        # （実測 case T: 全石 J2 -16.66 > L1 -19.79 だが自石だけなら +0.99 < +1.00/子）。
                        # 役割不明なら従来どおり全石（case O の校正はこの経路）
                        own_stones, opponent_stones = tsumego_region_stones_by_player(
                            self.game.stones, self.game.region_of_interest, self.cn.next_player
                        )
                        # 除外するのはコウ経路と分かった手だけ。pool に残った clean な対抗馬は
                        # 「役割が分かっているから脱出する」経路で初めて出てくる候補なので、
                        # policy 上位と同じ土俵（同深さ・役割ごとの石）で測って比べる。
                        # 全員コウの経路（case O）では ko_routes ⊇ pool なので従来と同じ集合になる
                        chosen, escape_value = self._ko_escape_choice(
                            chosen,
                            candidate_moves,
                            {c["move"] for c in pool if c["move"] in ko_routes},
                            tsumego_role_stones(own_stones, opponent_stones, solver_attacks),
                            player_sign,
                        )
                    else:
                        # clean な対抗馬は居るが同着バンドの外で、**役割も読めない**＝答えがコウの
                        # 詰碁とみなす（case R）。脱出も前提が偽なので走らせない
                        # （`tsumego_ko_escape_applies` 参照）
                        self.game.katrain.log(
                            f"[{self.strategy_name}] コウ経路検査: 選択手 {chosen['move']} はコウ経路だが、"
                            f"clean な対抗馬 "
                            + " ".join(
                                f"{c['move']}(pt{c['pointsLost']:+.2f})"
                                for c in pool
                                if c["move"] not in ko_routes
                            )
                            + f" は目数同着バンド（points_epsilon={points_epsilon}）の外なので格下げしません"
                            f"（役割が読めないので「答えがコウの詰碁」とみなす）",
                            OUTPUT_INFO,
                        )
                elif class_screen_applies:
                    # 選択手は clean。詰碁の順序で最下位なのは「相手が無条件で生きる／自石が死ぬ」＝
                    # 失敗なので、成立していない clean を採るくらいならコウ経路のほうが上位になる
                    # （格下げの裏返し＝`_ko_promotion_choice`。実測 case V2）
                    chosen, promoted_value = self._ko_promotion_choice(
                        chosen, candidate_moves, solver_attacks, player_sign
                    )
                    if promoted_value is not None:
                        escape_value, escape_label = promoted_value, "クラス格上げ"
            if escape_value is not None:
                # 脱出で採った手の root ownership は 1visit の生評価なので gain を出しても意味がない
                # （実測 case O: 正解 A11 の root gain は -16.99）。同深さ検証値のほうを見せる
                gain_text = f"{escape_label}/同深さ検証{escape_value:+.2f}"
            else:
                gain = tsumego_ownership_gain(
                    self.cn.ownership, chosen["ownership"], stones, self.game.board_size, player_sign
                )
                gain_text = f"gain={gain:+.2f}"
        move = Move.from_gtp(chosen["move"], player=self.cn.next_player)
        self.game.katrain.log(
            f"[{self.strategy_name}] Final decision: {move.gtp()} "
            f"({gain_text}, pointsLost={chosen['pointsLost']:+.2f}, "
            f"visits={chosen.get('visits', 0)}, "
            f"候補{len(candidate_moves)}手（うち対抗馬{len(eligible)}手）, gain集計石{len(stones)}子, "
            f"max_points_behind={max_points_behind}, "
            f"gain_epsilon={gain_epsilon}, min_visits={min_visits}, "
            f"gain_min_visit_ratio={min_visit_ratio}, points_epsilon={points_epsilon})",
            OUTPUT_DEBUG,
        )
        return move, f"詰碁戦略: {len(candidate_moves)}手から {move.gtp()} を選択（{gain_text}）"

    def _fire_speculation(self, plan):
        """温めプランを低優先度で発行する。結果は捨てる＝着手判定への影響は構造的にゼロ。

        投機クエリは使い捨て複製ゲームの子ノードに紐づける（`_region_prefetch_sim` と同じ
        パターン）＝ terminate が投機だけに当たり、本譜ノードのクエリを巻き込まない。
        条件（visits・ownership・untilDepth・wRN・リージョン）は実クエリと完全一致させる
        — KataGo の NN キャッシュは ownerMap の有無や設定差を区別するため、ずれた温めは
        1秒も速くしない（実測 2026-08-01 prefetch_cache_probe.py）。

        投機は純最適化＝どの失敗も着手生成に伝播させない（結果は元々捨てるだけなので、
        ここで起きる例外はすべて黙って諦めてよい）。
        """
        if not plan:
            return
        sim = tsumego_simulation_game(self.game, self.cn)
        if sim is None:
            return
        base = sim.current_node
        try:
            engine = self.game.engines[self.cn.next_player]
        except Exception as exc:
            self.game.katrain.log(
                f"[{self.strategy_name}] 投機温め: engine 取得に失敗（投機を中止）: {exc}",
                OUTPUT_DEBUG,
            )
            return
        visits = int((self.settings or {}).get("gain_verify_visits", TSUMEGO_GAIN_VERIFY_VISITS))
        fired = []
        for item in plan:
            try:
                sim.set_current_node(base)
                child = sim.play(Move.from_gtp(item["move"], player=self.cn.next_player))
                wrn = item["wide_root_noise"]
                engine.request_analysis(
                    child,
                    callback=lambda _analysis, _partial: None,
                    error_callback=lambda _error: None,
                    visits=visits,
                    time_limit=False,
                    ownership=True,
                    region_of_interest=self.game.region_of_interest,
                    region_until_depth=item["until_depth"],
                    extra_settings=region_analysis_extra_settings(
                        visits,
                        getattr(self.game, "region_analysis_wide_root_noise", REGION_ANALYSIS_WIDE_ROOT_NOISE)
                        if wrn is None
                        else wrn,
                    ),
                    priority=PRIORITY_TSUMEGO_SPECULATION,
                )
                self._speculative_nodes.append(child)
                fired.append(item["move"])
            except IllegalMoveException:
                continue
            except Exception as exc:
                self.game.katrain.log(
                    f"[{self.strategy_name}] 投機温め: {item.get('move')} の発行に失敗（無視して続行）: {exc}",
                    OUTPUT_DEBUG,
                )
                continue
        if fired:
            self.game.katrain.log(
                f"[{self.strategy_name}] 投機温め: {fired} の子局面を先回り発行（{visits}visits・結果は捨てる）",
                OUTPUT_DEBUG,
            )

    def _cancel_speculation(self):
        """未消化の投機クエリを打ち切る（結果はもともと捨てるだけなので副作用なし）"""
        nodes = self._speculative_nodes
        self._speculative_nodes = []
        for node in nodes:
            for engine in set(self.game.engines.values()):
                engine.terminate_queries(only_for_node=node)

    def _log_candidates(self, candidate_moves, stones, player_sign, top=5):
        """上位候補を visits / 最多手比 / 目数 / gain つきで残す。

        誤答の切り分けをログだけで済ませるため（case F の調査では、ログに選択手の gain しか
        無かったので盤面を再構築するまで「gain ノイズか本物の信号か」が分からなかった）。
        """
        root_ownership = self.cn.ownership
        if not root_ownership:
            return
        rows = [
            (
                c["move"],
                c.get("visits", 0),
                c["pointsLost"],
                tsumego_ownership_gain(root_ownership, c["ownership"], stones, self.game.board_size, player_sign),
            )
            for c in candidate_moves
            if c.get("ownership")
        ]
        if not rows:
            return
        ref = max(row[1] for row in rows) or 1
        text = lambda row: f"{row[0]}(v{row[1]}/{row[1] / ref:.2f} pt{row[2]:+.2f} g{row[3]:+.2f})"  # noqa: E731
        self.game.katrain.log(
            f"[{self.strategy_name}] gain順: " + " ".join(text(r) for r in sorted(rows, key=lambda r: -r[3])[:top]),
            OUTPUT_DEBUG,
        )
        self.game.katrain.log(
            f"[{self.strategy_name}] 目数順: " + " ".join(text(r) for r in sorted(rows, key=lambda r: r[2])[:top]),
            OUTPUT_DEBUG,
        )

    def _ko_route_screen(self, pool, ratio=TSUMEGO_KO_REPLY_RATIO, want_ownership=False):
        """pool の各候補を1手進めてリージョン解析し、コウ経路の候補の手（GTP）を返す。

        詰碁の正解順序は 無条件 > コウ で、目数はクラス内のタイブレークにすぎない。
        コウでも勝てると KataGo が読み切った局面では、コウで殺す手のスコア系メトリック
        （gain・目数・同深さ検証値）は全て「コウに勝った」前提の値になりクラスが見えない
        （実測 case K: A12/C13 が 4/4 観測で 0.1 目差以内。case M: gain +1.9 が実信号で
        単独首位、同深さ検証 +1.29 もコウ側を追認）。クラス差は「守り方に局所応答を
        強制する」リージョン子局面解析の最善応手 PV にだけ現れる（実測 case K 3/3 /
        case M 2/2 run 安定: M2 には白 K1 → 黒 M4 の1子取りコウ形、K1/C13 は clean）。
        検出は `tsumego_pv_reaches_region_ko`。

        子局面の解析は **PV の内容そのものが証拠**なので、歩く深さぶんリージョン外を禁じて
        撃つ（`TSUMEGO_KO_REGION_UNTIL_DEPTH`）。既定の untilDepth=1 では ply2 以降の PV が
        枠へ手抜きしてコウが現れない（実測 case P: 検出 1/4 → 4/4）。同じ理由で
        **wideRootNoise も切る**（`TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`）— 応手の並び自体が証拠
        なのに、root ノイズが run ごとに visits の配り方を変えて比を揺らす（実測 case M:
        wRN=0.04 で比 0.44〜0.88 とばらつき本番 3/6 で検出漏れ → wRN=0 で 0.15 が 4/4 不動）。

        `ratio` は「守り方が選べる競争力のある抵抗」の下限比。選択手には敏感側
        （`TSUMEGO_KO_REPLY_RATIO_CHOSEN`）、格下げ先候補には保守側(既定)を渡す
        ＝検出漏れと過検出のコストが非対称だから（定数のコメント参照）。

        コストは候補1つあたり解析1本（gain_verify_visits）。呼び出し側は選択手を先に
        検査し、コウ経路だったときだけ対抗馬を検査する（通常の手番は1本で済む）。
        候補が複数のときは解析を並列に発行する（内容・判定順は1本ずつと同一）。

        `want_ownership` は選択手の検査用: ownership 付きで撃って生解析を memo し、同条件の
        `_region_child_verdict`（クラス格上げの incumbent 検証）が同じ子局面を撃ち直さずに済む
        ようにする。includeOwnership は探索に影響しない（探索木からの集計のみ）。
        """
        settings = self.settings or {}
        visits = int(settings.get("gain_verify_visits", TSUMEGO_GAIN_VERIFY_VISITS))
        player = self.cn.next_player
        region = self.game.region_of_interest
        routes = set()
        pending = []
        for cand in sorted(pool, key=lambda c: -c.get("visits", 0))[:TSUMEGO_TIE_KO_MAX_CANDIDATES]:
            # 候補自身がコウを開始する形（実測 case L: L5 の1子取り）は解析クエリ不要で確定
            if tsumego_candidate_reaches_region_ko(self.game, self.cn, cand["move"], [], region):
                routes.add(cand["move"])
                self.game.katrain.log(
                    f"[{self.strategy_name}] コウ経路検査: {cand['move']} はコウ経路"
                    f"（候補自身がリージョン内のコウ形の1子取り）",
                    OUTPUT_INFO,
                )
                continue
            sim = tsumego_simulation_game(self.game, self.cn)
            if sim is None:
                self.game.katrain.log(f"[{self.strategy_name}] コウ経路検査: 局面を再現できないため省略", OUTPUT_DEBUG)
                break
            try:
                node = sim.play(Move.from_gtp(cand["move"], player=player))
            except IllegalMoveException:
                continue
            pending.append(
                (
                    cand,
                    self._start_region_root(
                        node,
                        visits,
                        ownership=want_ownership,
                        until_depth=TSUMEGO_KO_REGION_UNTIL_DEPTH,
                        wide_root_noise=TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
                    ),
                )
            )
        self._wait_region_roots([handle for _, handle in pending])
        for cand, handle in pending:
            root = handle.get("root")
            if want_ownership and root is not None and root.get("ownership") is not None:
                memo = getattr(self, "_screen_root_memo", None)
                if memo is not None:
                    memo[cand["move"]] = {
                        "visits": visits,
                        "wide_root_noise": TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
                        "until_depth": TSUMEGO_KO_REGION_UNTIL_DEPTH,
                        "root": root,
                    }
            replies = (root or {}).get("moves") or []
            # 拮抗している応手は全部歩く。top 1本では応手ランキングの分散でコウを見逃す
            # （実測 case M: 白のコウ仕掛け K1 と穏健な M4 が拮抗し、M4 が top の run で素通り）
            walk = tsumego_competitive_replies(replies, ratio)
            if not walk:
                continue
            ko_reply = next(
                (
                    r
                    for r in walk
                    if tsumego_candidate_reaches_region_ko(self.game, self.cn, cand["move"], r.get("pv") or [], region)
                ),
                None,
            )
            if ko_reply is not None:
                routes.add(cand["move"])
                self.game.katrain.log(
                    f"[{self.strategy_name}] コウ経路検査: {cand['move']} はコウ経路"
                    f"（応手 {ko_reply.get('move')} の PV がリージョン内のコウ形に到達）",
                    OUTPUT_INFO,
                )
            else:
                self.game.katrain.log(
                    f"[{self.strategy_name}] コウ経路検査: {cand['move']} は無条件"
                    f"（候補自身・拮抗応手 {[r.get('move') for r in walk]} の PV ともコウ形なし）",
                    OUTPUT_DEBUG,
                )
        return frozenset(routes)

    def _declass_target_confirmed(self, target, solver_attacks, player_sign):
        """格下げ先が本当に詰碁を解いているかを同深さで測る（解析1本）。

        判定の中身と実測は `tsumego_declass_confirmed` の docstring を参照。格下げが起きようと
        している手番でしか走らないので、通常の手番のコストは増えない。

        **役割が読めない枠なし盤でも走らせる**（旧実装はここで即 True を返していた＝case W）。
        尺度は成功判定と同じ `tsumego_success_ownership` で、役割が読めれば役割石だけ・読めなければ
        自石と相手石の1子平均の小さいほう。どちらも**同じ子局面解析1本**から取る。
        """
        settings = self.settings or {}
        visits = int(settings.get("gain_verify_visits", TSUMEGO_GAIN_VERIFY_VISITS))
        threshold = float(settings.get("ko_success_ownership", TSUMEGO_SUCCESS_OWNERSHIP))
        own_stones, opponent_stones = tsumego_region_stones_by_player(
            self.game.stones, self.game.region_of_interest, self.cn.next_player
        )
        role_stones = tsumego_role_stones(own_stones, opponent_stones, solver_attacks)
        verdict = self._region_child_verdict(target["move"], role_stones, player_sign, visits)
        per_stone = (
            None
            if verdict is None
            else tsumego_success_ownership(
                verdict["ownership"],
                own_stones,
                opponent_stones,
                self.game.board_size,
                player_sign,
                solver_attacks,
            )
        )
        confirmed = tsumego_declass_confirmed(per_stone, threshold)
        if per_stone is None:
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ経路検査: 格下げ先 {target['move']} の成否を測れないため"
                f"従来どおり格下げします",
                OUTPUT_INFO,
            )
        else:
            scope = (
                f"役割石{len(role_stones)}子"
                if solver_attacks is not None
                else f"自石{len(own_stones)}子・相手石{len(opponent_stones)}子の厳しいほう"
            )
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ経路検査: 格下げ先 {target['move']} の同深さ{visits}visits・"
                f"{scope}は{per_stone:+.2f}/子"
                + (
                    f"（>= ko_success_ownership={threshold}）＝無条件で成立"
                    if confirmed
                    else f"（< ko_success_ownership={threshold}）＝詰碁を解いていないので格下げしません"
                ),
                OUTPUT_INFO,
            )
        return confirmed

    def _region_child_verdict(self, move_gtp, stones, player_sign, visits, wide_root_noise=None):
        """候補手を1手進め、リージョン解析**1本**で「コウ経路か」と「同深さ ownership」を同時に取る。

        コウ経路の判定は `_ko_route_screen` と同じ手順（候補手自身の1子取り＋守り方の拮抗応手の
        PV）。あちらは ownership を要求しないので、脱出の判定に必要な絶対 ownership を得るために
        こちらを別に用意する（選択手だけは両方で1本ずつ撃つことになるが、脱出はコウ一色のときに
        しか走らないので実害はない。既に回帰の取れている `_ko_route_screen` を触らずに済むほうを取る）。

        リージョンの拘束深さは**コウ検出より深い** `TSUMEGO_VERDICT_UNTIL_DEPTH`。ここは
        「その手で相手が死ぬか」を聞く判定なので、拘束が局所の攻防より先に切れると守り方が枠外へ
        逃げ、その群を捨てた局面が評価されて**失敗手が「相手は死んだ」と読まれる**（実測 case Y）。
        `value` は候補と incumbent を同条件で測った相対比較にしか使わないので、拘束を深くしても
        両者に同じだけ効く。

        `wide_root_noise` の既定（None）は本譜と同じ設定＝**脱出の校正（case O/T/F）はこの条件**。
        **`ko` フラグそのものを裁定に使う呼び出しだけ** `TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`(0) を
        渡す（root の Dirichlet ノイズが応手の visits 比を run ごとに揺らす＝case M。格上げ
        `_ko_promotion_choice` はクラスで決めるのでこちら側）。

        選択手のコウ経路検査（`_ko_route_screen` want_ownership=True）が同条件で撃った生解析が
        memo に残っていればそれを使う＝同じ子局面を同じ設定で撃ち直さない（サンプルを共有する
        だけで判定ロジックは同一）。**拘束深さも一致を要求する**（あちらは 6、こちらは 12 なので
        現状は一致しない＝共有しない。深さの違う解析を混ぜると case Y の誤答がそのまま戻る）。

        取れなければ None。
        """
        memo = (getattr(self, "_screen_root_memo", None) or {}).get(move_gtp)
        if (
            memo is not None
            and memo["visits"] == visits
            and memo["wide_root_noise"] == wide_root_noise
            and memo["until_depth"] == TSUMEGO_VERDICT_UNTIL_DEPTH
        ):
            return self._child_verdict_from_root(move_gtp, memo["root"], stones, player_sign)
        player = self.cn.next_player
        sim = tsumego_simulation_game(self.game, self.cn)
        if sim is None:
            return None
        try:
            node = sim.play(Move.from_gtp(move_gtp, player=player))
        except IllegalMoveException:
            return None
        root = self._analyze_region_root(
            node,
            visits,
            ownership=True,
            until_depth=TSUMEGO_VERDICT_UNTIL_DEPTH,
            wide_root_noise=wide_root_noise,
        )
        if root is None or root.get("ownership") is None:
            return None
        return self._child_verdict_from_root(move_gtp, root, stones, player_sign)

    def _child_verdict_from_root(self, move_gtp, root, stones, player_sign):
        """子局面の生解析から {ko, ko_reply, value, lead, ownership} を組む（`_region_child_verdict` の判定部）

        `ownership` は生の盤グリッドをそのまま返す。`value` は呼び出し側が渡した1グループぶんの
        合計しか持たないので、**同じ解析から別の石グループも測りたい**呼び出し（役割が読めない
        ときの格下げ確認＝自石と相手石の両方を見る `_declass_target_confirmed`）が
        子局面をもう1本撃たずに済むようにするため。
        """
        region = self.game.region_of_interest
        ko_reply = None
        if tsumego_candidate_reaches_region_ko(self.game, self.cn, move_gtp, [], region):
            ko_reply = "候補手自身"
        else:
            walk = tsumego_competitive_replies(root.get("moves") or [])
            hit = next(
                (
                    r
                    for r in walk
                    if tsumego_candidate_reaches_region_ko(self.game, self.cn, move_gtp, r.get("pv") or [], region)
                ),
                None,
            )
            if hit is not None:
                ko_reply = hit.get("move")
        return {
            "ko": ko_reply is not None,
            "ko_reply": ko_reply,
            "value": tsumego_absolute_ownership(root["ownership"], stones, self.game.board_size, player_sign),
            "lead": player_sign * root["lead"],
            "ownership": root["ownership"],
        }

    def _child_verdicts(self, moves, stones, player_sign, visits, wide_root_noise=None):
        """複数候補の `_region_child_verdict` を並列解析でまとめて取る。{move: verdict} を返す。

        sim の構築と PV 歩きは従来どおり直列・従来順で、解析クエリの発行→待ちだけを束ねる
        （クエリ内容・判定は1本ずつ撃つのと同一。取れなかった手は dict に入らない＝None 相当）。
        """
        pending = {}
        for move_gtp in moves:
            if move_gtp in pending:
                continue
            memo = (getattr(self, "_screen_root_memo", None) or {}).get(move_gtp)
            if (
                memo is not None
                and memo["visits"] == visits
                and memo["wide_root_noise"] == wide_root_noise
                and memo["until_depth"] == TSUMEGO_VERDICT_UNTIL_DEPTH
            ):
                pending[move_gtp] = {"root": memo["root"]}
                continue
            sim = tsumego_simulation_game(self.game, self.cn)
            if sim is None:
                continue
            try:
                node = sim.play(Move.from_gtp(move_gtp, player=self.cn.next_player))
            except IllegalMoveException:
                continue
            pending[move_gtp] = self._start_region_root(
                node,
                visits,
                ownership=True,
                until_depth=TSUMEGO_VERDICT_UNTIL_DEPTH,
                wide_root_noise=wide_root_noise,
            )
        self._wait_region_roots([h for h in pending.values() if "_visits" in h])
        verdicts = {}
        for move_gtp, handle in pending.items():
            root = handle.get("root")
            if root is None or root.get("ownership") is None:
                continue
            verdicts[move_gtp] = self._child_verdict_from_root(move_gtp, root, stones, player_sign)
        return verdicts

    def _ko_promotion_choice(self, chosen, candidate_moves, solver_attacks, player_sign):
        """clean な選択手が詰碁を成立させていないとき、上位クラス（無条件 > コウ）へ格上げする。

        クラス裁定はこれまで**格下げ方向（コウ → 無条件）しか持っていなかった**。ところが
        詰碁の順序で最下位なのは「相手が無条件で生きる／自石が無条件で死ぬ」＝**失敗**であって、
        成立していない clean 手はコウ手より下にいる。格下げ側だけだと、選択手が clean で失敗して
        いる局面で機構が丸ごと沈黙する。

        実測 case V2（2026-07-31、case V の続き＝黒L12 白N10 まで進めた局面・黒は攻め方。
        正解 N13 でコウ、AI は K10 を打って白の無条件生き）:

            K10（選択・clean） pt+0.42 v1069 prior1位   相手石 -0.91/-1.00 /子
            L11（対抗馬・clean）pt+0.41 v676  prior2位   相手石 -0.99/-0.99 /子
            N13（正解・**コウ**）pt+7.97 v17  prior3位   相手石 -1.00/-1.00 /子
            L13（clean）        pt+7.71 v2   prior4位   相手石 -1.00/-1.00 /子

        ＝**どの手でも白は生きる**と読まれており、目数・gain・同深さ ownership のどれも正解を
        指さない（正解は目数ガード best+2.0 の外で v17、gain も同着）。分離できるのはクラスだけで、
        N13 だけが「応手 L11 の PV がリージョン内のコウ形に到達」と 2/2 run で出る。

        探す先が root policy なのは case O と同じ理由（value が壊れた手に visits は付かない）。
        実測の prior は K10 .196 / L11 .0172 / **N13 .0133** / L13 .0021 で、残り全部が NN 下限
        .00009＝正解は `ko_escape_min_prior`(0.001) の上、下限手との間に 20 倍の崖がある。

        **トリガーは絶対判定（役割石の1子平均 < `ko_success_ownership`）で、相対比較ではない**。
        枠あり8ケースの実測では、正解の clean 手は例外なく ply1・800visits で成立している
        （D A4 +0.99 / E K1 +1.00 / J N10 +1.00 / K C13 +0.99 / L J6 +0.99 / M K1 +0.98（守り方）/
        P J1 +0.99 / T M1 +1.00（守り方））ので、この機構はそれらの手番では**1本も解析せずに
        素通りする**（root の movesOwnership で先に振るう）。

        役割が読めない（枠なし）盤では走らない＝成否を測る尺度が無く、全リージョン石の合計では
        成否が分離できないため（case R）。

        (採用する候補, 検証値) を返す。格上げしなければ (chosen, None)。
        """
        settings = self.settings or {}
        max_candidates = int(settings.get("ko_escape_candidates", TSUMEGO_KO_ESCAPE_MAX_CANDIDATES))
        if solver_attacks is None or max_candidates <= 0:
            return chosen, None
        threshold = float(settings.get("ko_success_ownership", TSUMEGO_SUCCESS_OWNERSHIP))
        visits = int(settings.get("gain_verify_visits", TSUMEGO_GAIN_VERIFY_VISITS))
        min_prior = float(settings.get("ko_escape_min_prior", TSUMEGO_KO_ESCAPE_MIN_PRIOR))
        own_stones, opponent_stones = tsumego_region_stones_by_player(
            self.game.stones, self.game.region_of_interest, self.cn.next_player
        )
        role_stones = tsumego_role_stones(own_stones, opponent_stones, solver_attacks)
        if not role_stones:
            return chosen, None
        # 解析を撃つ前に root の movesOwnership で振るう。成立していると読めているならクラス裁定は
        # 不要で、通常の手番のコストは 0 本のまま（実測の正解手は +0.98〜+1.00 でここを通らない）
        if chosen.get("ownership"):
            root_per_stone = (
                tsumego_absolute_ownership(chosen["ownership"], role_stones, self.game.board_size, player_sign)
                / len(role_stones)
            )
            if root_per_stone >= threshold:
                return chosen, None
        incumbent = self._region_child_verdict(
            chosen["move"],
            role_stones,
            player_sign,
            visits,
            wide_root_noise=TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
        )
        if incumbent is None:
            return chosen, None
        if tsumego_ko_escape_succeeds(incumbent["value"], len(role_stones), threshold):
            self.game.katrain.log(
                f"[{self.strategy_name}] クラス格上げ: 選択手 {chosen['move']} は同深さ{visits}visits・"
                f"役割石{len(role_stones)}子で{incumbent['value'] / len(role_stones):+.2f}/子＝成立しているため不要",
                OUTPUT_DEBUG,
            )
            return chosen, None
        shortlist = tsumego_ko_escape_candidates(candidate_moves, {chosen["move"]}, min_prior, max_candidates)
        if not shortlist:
            return chosen, None
        listed = " ".join("{}(p{:.4f})".format(c["move"], c.get("prior", 0.0)) for c in shortlist)
        self.game.katrain.log(
            f"[{self.strategy_name}] クラス格上げ: 選択手 {chosen['move']} は無条件だが"
            f"{incumbent['value'] / len(role_stones):+.2f}/子＝詰碁が成立していない（最下位クラス）ため、"
            f"policy 上位 {listed} を同深さ{visits}visits で測ります"
            f"（成否は役割石{len(role_stones)}子の1子平均 >= {threshold}）",
            OUTPUT_INFO,
        )
        # 独立な子局面なので全員分を並列で測る（評価順・採用規則・打ち切りログは従来どおり）
        verdicts = self._child_verdicts(
            [c["move"] for c in shortlist],
            role_stones,
            player_sign,
            visits,
            wide_root_noise=TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
        )
        best = None
        for cand in shortlist:
            verdict = verdicts.get(cand["move"])
            if verdict is None:
                continue
            per_stone = verdict["value"] / len(role_stones)
            succeeds = tsumego_ko_escape_succeeds(verdict["value"], len(role_stones), threshold)
            result_class = tsumego_result_class(verdict["ko"], succeeds)
            label = {
                TSUMEGO_CLASS_UNCONDITIONAL: "無条件で成立",
                TSUMEGO_CLASS_KO: f"コウ経路（{verdict['ko_reply']}）",
                TSUMEGO_CLASS_FAILED: "成立していない（選択手と同じ最下位クラス）",
            }[result_class]
            self.game.katrain.log(
                f"[{self.strategy_name}] クラス格上げ: {cand['move']} 検証値{verdict['value']:+.2f}"
                f"（{per_stone:+.2f}/子） 目数{verdict['lead']:+.2f} → {label}",
                OUTPUT_INFO,
            )
            if result_class < TSUMEGO_CLASS_FAILED and (best is None or result_class < best[0]):
                best = (result_class, cand, verdict)
            if best is not None and best[0] == TSUMEGO_CLASS_UNCONDITIONAL:
                break  # 無条件はクラスの最上位なので、これ以上測る必要が無い
        if best is None:
            self.game.katrain.log(
                f"[{self.strategy_name}] クラス格上げ: 上位クラスの手が無いため選択手 {chosen['move']} を維持します",
                OUTPUT_INFO,
            )
            return chosen, None
        promoted = "無条件" if best[0] == TSUMEGO_CLASS_UNCONDITIONAL else "コウ"
        self.game.katrain.log(
            f"[{self.strategy_name}] クラス格上げ: 成立していない {chosen['move']} より上位の "
            f"{promoted}の {best[1]['move']} を採用します"
            f"（詰碁の順序: 無条件 > コウ > 相手が無条件で生きる/自石が死ぬ）",
            OUTPUT_INFO,
        )
        return best[1], best[2]["value"]

    def _ko_escape_choice(self, chosen, candidate_moves, screened_moves, stones, player_sign):
        """選択手も対抗馬も全部コウ経路のとき、root が読まなかった policy 上位手から無条件手を探す。

        「目数ガード内が全部コウ」は、詰碁の順序（無条件 > コウ）からすると
        **正解が候補プールの外にいる**という信号になる。実測 case O（2026-07-31）では正解 A11 が
        root 12000visits でも 1visit のままで、その 1visit の評価（+28.74目損）で選択則の全ゲートから
        締め出されていた（詳細は `TSUMEGO_KO_ESCAPE_MAX_CANDIDATES` のコメント）。

        採用は「clean かつ、**その手で詰碁が成立していて**（`tsumego_ko_escape_succeeds`）、
        同深さ ownership がコウの選択手に tolerance 超えて劣らない」ときだけ。スコアで上回る
        ことは要求しない（コウ手のほうが高く出るのが正常）。答えが本当にコウの詰碁では clean な
        候補が成立判定を通らないので、この機構は何もしない。

        **成立判定を相対比較（tolerance）で代用してはいけない** — incumbent 自身が失敗して
        いると全候補が横並びになって退化する（実測 case F: 全員 −0.97〜−0.99/子 なのに
        0.08 差で1手が「最良」に選ばれ、選択手が捨てられた）。

        (採用する候補, 検証値) を返す。脱出しなかったときは (chosen, None)。
        """
        settings = self.settings or {}
        max_candidates = int(settings.get("ko_escape_candidates", TSUMEGO_KO_ESCAPE_MAX_CANDIDATES))
        if max_candidates <= 0:
            return chosen, None
        min_prior = float(settings.get("ko_escape_min_prior", TSUMEGO_KO_ESCAPE_MIN_PRIOR))
        tolerance = float(settings.get("ko_escape_tolerance", TSUMEGO_KO_ESCAPE_TOLERANCE))
        success_ownership = float(settings.get("ko_success_ownership", TSUMEGO_SUCCESS_OWNERSHIP))
        visits = int(settings.get("gain_verify_visits", TSUMEGO_GAIN_VERIFY_VISITS))
        shortlist = tsumego_ko_escape_candidates(candidate_moves, screened_moves, min_prior, max_candidates)
        if not shortlist:
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ脱出: prior>={min_prior} の未検査候補が無いため打ち切ります",
                OUTPUT_INFO,
            )
            return chosen, None
        incumbent = self._region_child_verdict(chosen["move"], stones, player_sign, visits)
        if incumbent is None:
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ脱出: 選択手 {chosen['move']} を測れないため打ち切ります", OUTPUT_INFO
            )
            return chosen, None
        listed = " ".join("{}(p{:.4f})".format(c["move"], c.get("prior", 0.0)) for c in shortlist)
        incumbent_per_stone = f"（{incumbent['value'] / len(stones):+.2f}/子）" if stones else ""
        self.game.katrain.log(
            # トリガーは「目数ガード内が全てコウ経路」だけではない（役割が読めるなら clean な
            # 対抗馬が居ても走る＝case T、格下げ先が詰碁を解いていなくても走る＝case V）ので、
            # 共通する事実（コウの選択手を格下げできなかった）を書く
            f"[{self.strategy_name}] コウ脱出: コウの選択手を格下げできなかったため、root が読まなかった "
            f"policy 上位 {listed} を同深さ{visits}visits で測ります"
            f"（選択手 {chosen['move']} の検証値{incumbent['value']:+.2f}{incumbent_per_stone}、"
            f"成否は役割石{len(stones)}子の1子平均 >= {success_ownership}、tolerance={tolerance}）",
            OUTPUT_INFO,
        )
        # 独立な子局面なので全員分を並列で測る（評価順・採用規則は従来どおり）
        shortlist_verdicts = self._child_verdicts([c["move"] for c in shortlist], stones, player_sign, visits)
        best = None
        for cand in shortlist:
            verdict = shortlist_verdicts.get(cand["move"])
            if verdict is None:
                continue
            # 相対条件（コウの incumbent に劣りすぎない）の前に、**その手で詰碁が成立して
            # いるか**を絶対値で見る。incumbent 自身が失敗していると相対条件は退化して
            # ノイズ幅で1手を選んでしまう（`tsumego_ko_escape_succeeds` 参照＝case F）
            succeeds = tsumego_ko_escape_succeeds(verdict["value"], len(stones), success_ownership)
            accepted = (
                not verdict["ko"]
                and succeeds
                and tsumego_ko_escape_accepts(verdict["value"], incumbent["value"], tolerance)
            )
            if verdict["ko"]:
                reason = f"コウ経路（{verdict['ko_reply']}）"
            elif not succeeds:
                reason = f"詰碁が成立していない（ko_success_ownership={success_ownership}）"
            elif accepted:
                reason = "採用候補"
            else:
                reason = f"コウの選択手に tolerance={tolerance} 超えて劣る"
            per_stone = f"（{verdict['value'] / len(stones):+.2f}/子）" if stones else ""
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ脱出: {cand['move']} 検証値{verdict['value']:+.2f}{per_stone} "
                f"目数{verdict['lead']:+.2f} → {reason}",
                OUTPUT_INFO,
            )
            if accepted and (best is None or verdict["value"] > best[0]):
                best = (verdict["value"], cand)
        if best is None:
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ脱出: 無条件で成立する手が無いためコウの {chosen['move']} を維持します",
                OUTPUT_INFO,
            )
            return chosen, None
        self.game.katrain.log(
            f"[{self.strategy_name}] コウ脱出: 無条件の {best[1]['move']}（検証値{best[0]:+.2f}）を採用します"
            f"（詰碁の順序: 無条件 > コウ。root では v{best[1].get('visits', 0)}/pt{best[1]['pointsLost']:+.2f} で"
            f"読まれていなかった手）",
            OUTPUT_INFO,
        )
        return best[1], best[0]

    def _verified_choice(
        self, incumbent, challengers, stones, player_sign, incumbent_label="目数最善", margin=None, fallback=None
    ):
        """incumbent と挑戦者たちを同じ深さで測り直し、margin 超えで上回る最良の挑戦者に覆す。

        gain は1本の root 探索の movesOwnership から取るので候補ごとに探索の深さが違い、浅い手ほど
        ownership が未決着側へドリフトする（実測 case F: N7 が 214-307visits で +2.70〜+9.10、
        同じ手を 637visits まで探索すると +0.06 に消えた）。そこで子局面を同 visits で解析し直し、
        対象石の ownership を**絶対値**で直接比較する（root 差分は基準が揃わないので使えない）。
        実測 case F（各1800visits）: N8 -26.60 > N7 -26.91 で正解が残る。

        挑戦者が複数のときは全員を測り、incumbent を margin 超えて上回った中の最良を採る
        （実測 case F2: gain 1位のノイズ手 N9 は検証 -26.9 で落ち、2位の本物 N11 -17.1 が
        incumbent J11 -19.4 を上回って採用される。トップ1指名では N9 の影で N11 が消えた）。

        検証が実行できない場合（局面を再現できない・incumbent が解析できない等）は fallback
        （＝呼び出し時点の選択）を返す。個別の挑戦者が打てない・解析できない場合はその挑戦者
        だけ飛ばす。
        """
        settings = self.settings or {}
        if fallback is None:
            fallback = challengers[0]
        if not settings.get("gain_verify", True):
            return fallback
        visits = int(settings.get("gain_verify_visits", TSUMEGO_GAIN_VERIFY_VISITS))
        if margin is None:
            margin = float(settings.get("gain_verify_margin", TSUMEGO_GAIN_VERIFY_MARGIN))
        sim = tsumego_simulation_game(self.game, self.cn)
        if sim is None:
            self.game.katrain.log(f"[{self.strategy_name}] 同深さ検証: 局面を再現できないため省略", OUTPUT_DEBUG)
            return fallback
        base = sim.current_node
        # 独立な子局面のクエリは全員分を発行してからまとめて待つ（内容不変で待ちは最長1本ぶん）
        handles = {}
        for cand in [incumbent] + challengers:
            if cand["move"] in handles:
                continue
            sim.set_current_node(base)
            try:
                node = sim.play(Move.from_gtp(cand["move"], player=self.cn.next_player))
            except IllegalMoveException:
                continue
            handles[cand["move"]] = self._start_region_root(node, visits, ownership=True)
        self._wait_region_roots(handles.values())
        values = {}
        for move_gtp, handle in handles.items():
            root = handle.get("root")
            if root is None or root.get("ownership") is None:
                continue
            values[move_gtp] = tsumego_absolute_ownership(
                root["ownership"], stones, self.game.board_size, player_sign
            )
        if incumbent["move"] not in values:
            return fallback
        incumbent_value = values[incumbent["move"]]
        best = None
        for cand in challengers:
            value = values.get(cand["move"])
            if value is None:
                continue
            confirmed = tsumego_override_confirmed(value, incumbent_value, margin)
            self.game.katrain.log(
                f"[{self.strategy_name}] 同深さ検証({visits}visits): {cand['move']} {value:+.2f} "
                f"vs {incumbent_label} {incumbent['move']} {incumbent_value:+.2f}"
                f"（差{value - incumbent_value:+.2f} / margin={margin}）→ "
                f"{'採用候補' if confirmed else '却下'}",
                OUTPUT_INFO,
            )
            if confirmed and (best is None or value > best[0]):
                best = (value, cand)
        if best is None:
            self.game.katrain.log(
                f"[{self.strategy_name}] 同深さ検証: 全挑戦者が却下、{incumbent_label} {incumbent['move']} を維持",
                OUTPUT_INFO,
            )
            return incumbent
        self.game.katrain.log(
            f"[{self.strategy_name}] 同深さ検証: {best[1]['move']}（検証値{best[0]:+.2f}）を採用", OUTPUT_INFO
        )
        return best[1]

    def _pick_ko_win_move(self, candidate_moves, min_visits, player_sign, solver_attacks=None):
        """コウに持ち込める手があり、コウに勝った局面が通常の最善手より良ければその手を返す。

        詰碁ではコウダテがあるものとして正解が決まる（コウにできればそれが最大の成果）。
        枠の中では攻め方のコウダテが乏しく KataGo は「コウは守り側が勝つ」と読むため、
        殺せないセキ等を選んでしまう（実測 2026-07-30: 正解のコウ手 -21.7目 / セキ -12.3目 /
        コウを勝った局面 +8.1目）。コウの手だけ取り返した後の局面で評価して慣習に合わせる。

        **これは攻め方の話**（攻め: 無条件死 > コウ > セキ）。守り方の順序は 無条件生き >
        セキ > コウ で、コウはセキの**下**なので持ち上げてはいけない。振り分けは
        `tsumego_already_succeeded` の成功判定に委ねる: 役割が分かっていればセキも
        「自石が生きている＝成功」と読まれ、この機構ごとスキップされる（`solver_attacks`）。
        """
        settings = self.settings or {}
        if not settings.get("ko_win_assumption", True):
            self.game.katrain.log(f"[{self.strategy_name}] コウ判定: ko_win_assumption=false のため省略", OUTPUT_DEBUG)
            return None
        playable = [c for c in candidate_moves if c.get("move") and c["move"] != "pass"]
        searched = [c for c in playable if c.get("visits", 0) >= min_visits]
        if not searched:
            return None
        # 通常最善は信頼できる候補（min_visits 以上）から取る。一方コウの検査自体は構造判定で、
        # 評価も別途取り直すので visits の下限を課さない（探索分散で正解手が数 visits に
        # 沈むことがあり、そこで検査対象から外すと詰碁の慣習が効かなくなる）
        best_normal = max(player_sign * c["scoreLead"] for c in searched)
        success_lead = float(settings.get("ko_success_lead", TSUMEGO_SUCCESS_LEAD))
        own_stones, opponent_stones = tsumego_region_stones_by_player(
            self.game.stones, self.game.region_of_interest, self.cn.next_player
        )
        success_own = tsumego_success_ownership(
            self.cn.ownership, own_stones, opponent_stones, self.game.board_size, player_sign, solver_attacks
        )
        measured = {True: "相手石", False: "自石", None: "自石・相手石の厳しいほう"}[solver_attacks]
        order_text = {
            True: "攻め方なので 無条件死 > コウ > セキ",
            False: "守り方なので 無条件生き > セキ > コウ",
            None: "役割不明（攻め方の順序 無条件 > コウ > セキ で動く）",
        }[solver_attacks]
        own_text = "n/a" if success_own is None else f"{measured} {success_own:+.2f}/子"
        success_own_threshold = float(settings.get("ko_success_ownership", TSUMEGO_SUCCESS_OWNERSHIP))
        if tsumego_already_succeeded(best_normal, success_lead, success_own, success_own_threshold):
            # 無条件に成功できるならコウは慣習上の格下げ。解析1本も節約できる
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ判定: 通常最善{best_normal:+.2f}目・関係石 ownership {own_text} で"
                f"既に成功しているため省略（ko_success_lead={success_lead}、"
                f"ko_success_ownership={success_own_threshold}。{order_text}）",
                OUTPUT_INFO,
            )
            return None
        if best_normal > success_lead:
            # 目数は成功と言っているが ownership が同意しない。枠の代償地帯が未決着でスコアが
            # 詰碁から切り離されている局面（実測 case Q: +10.45目・相手石 −0.99/子）なので、
            # スキップせずコウ機構を走らせる（保険は ko_win_margin）
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ判定: 通常最善{best_normal:+.2f}目は成功と言っているが"
                f"関係石 ownership {own_text} が ko_success_ownership={success_own_threshold} に届かないため"
                f"省略しません（枠の代償地帯が未決着でスコアが詰碁から切り離されている可能性）",
                OUTPUT_INFO,
            )
        player = self.cn.next_player
        ko_visits = int(settings.get("ko_win_visits", 800))
        ko_margin = float(settings.get("ko_win_margin", TSUMEGO_KO_MARGIN))
        pending = []
        checked = 0
        for cand in sorted(playable, key=lambda c: -c.get("visits", 0)):
            if checked >= _TSUMEGO_KO_MAX_CANDIDATES:
                break
            move = Move.from_gtp(cand["move"], player=player)
            ko_node = tsumego_ko_win_node(self.game, self.cn, move)
            if ko_node is None:
                continue
            checked += 1
            # コウ形の候補は互いに独立なので解析を並列に発行する（評価順・採用は従来どおり）
            pending.append((cand, move, self._start_region_root(ko_node, ko_visits, ownership=False)))
        self._wait_region_roots([handle for _, _, handle in pending])
        best = None
        for cand, move, handle in pending:
            root = handle.get("root")
            if root is None:
                continue
            value = player_sign * root["lead"]
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ判定: {move.gtp()} 通常{player_sign * cand['scoreLead']:+.2f}目 → "
                f"コウ勝ち前提{value:+.2f}目（通常の最善は{best_normal:+.2f}目）",
                OUTPUT_INFO,
            )
            if best is None or value > best[0]:
                best = (value, move, cand)
        if best is None:
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ判定: 候補{len(playable)}手にコウの形なし", OUTPUT_DEBUG
            )
            return None
        if not tsumego_ko_beats_normal(best[0], best_normal, ko_margin):
            self.game.katrain.log(
                f"[{self.strategy_name}] コウ判定: {best[1].gtp()} のコウ勝ち前提{best[0]:+.2f}目は"
                f"通常最善{best_normal:+.2f}目を ko_win_margin={ko_margin} 超えて上回らないため不採用"
                f"（差{best[0] - best_normal:+.2f}目）",
                OUTPUT_INFO,
            )
            return None
        value, move, cand = best
        self.game.katrain.log(
            f"[{self.strategy_name}] Final decision: {move.gtp()} "
            f"（コウ勝ち前提{value:+.2f}目 > 通常最善{best_normal:+.2f}目、差{value - best_normal:+.2f}目 > "
            f"ko_win_margin={ko_margin}、pointsLost={cand['pointsLost']:+.2f}, ko_win_visits={ko_visits}）",
            OUTPUT_INFO,
        )
        return move, f"詰碁戦略: {move.gtp()} でコウに持ち込む（コウ勝ち前提 {value:+.2f}目）"

    def _analyze_score_lead(self, node, visits, timeout=60.0):
        """使い捨てノードを解析して root の scoreLead（黒視点）だけ取る。取れなければ None"""
        root = self._analyze_region_root(node, visits, ownership=False, timeout=timeout)
        return None if root is None else root["lead"]

    def _start_region_root(self, node, visits, ownership=False, until_depth=None, wide_root_noise=None):
        """リージョン限定解析を**発行だけして待たない**。結果ハンドル（dict）を返す。

        KataGo は `numAnalysisThreads`(=12) 本のクエリを並列に処理できるのに、1本ずつ発行して
        完了を待つと選択則の追加解析（同深さ検証・コウ経路検査・脱出・格上げ・コウ勝ち評価）が
        全部直列になる。独立な子局面のクエリは全員分を発行してから `_wait_region_roots` で
        まとめて待つ＝クエリ内容・判定順序は一切変えず wall time だけ縮める（並列実行が
        クエリ結果に与える影響は GPU を分け合って遅くなることだけで、探索木・NN 評価値は
        変わらない。E2E 回帰 2026-07-31 で全ケース不変を確認）。
        """
        engine = self.game.engines[self.cn.next_player]
        result = {"_visits": visits}
        engine.request_analysis(
            node,
            callback=lambda analysis, partial_result: (
                None
                if partial_result
                else result.setdefault(
                    "root",
                    {
                        "lead": analysis["rootInfo"]["scoreLead"],
                        "ownership": analysis.get("ownership"),
                        "moves": analysis.get("moveInfos"),
                    },
                )
            ),
            error_callback=lambda error: result.setdefault("error", error),
            visits=visits,
            time_limit=False,
            ownership=ownership,
            region_of_interest=self.game.region_of_interest,
            region_until_depth=until_depth,
            extra_settings=region_analysis_extra_settings(
                visits,
                getattr(self.game, "region_analysis_wide_root_noise", REGION_ANALYSIS_WIDE_ROOT_NOISE)
                if wide_root_noise is None
                else wide_root_noise,
            ),
            priority=PRIORITY_EXTRA_AI_QUERY,
        )
        return result

    def _wait_region_roots(self, handles, timeout=60.0):
        """`_start_region_root` のハンドル群が全部返るまで待つ（並列に走るので待ちは最長1本ぶん）。

        タイムアウト予算はバッチ本数でスケールする＝直列版（1本あたり timeout 秒）より先に
        諦めない。通常は全ハンドルが数秒で揃って即抜けするので、この上限に意味が出るのは
        エンジンが劣化した異常時だけ。
        """
        handles = list(handles)
        deadline = time.time() + timeout * max(1, len(handles))
        while time.time() < deadline and any("root" not in h and "error" not in h for h in handles):
            time.sleep(0.02)
        for h in handles:
            if "root" not in h:
                self.game.katrain.log(
                    f"[{self.strategy_name}] 追加解析に失敗しました（{h.get('_visits')}visits）", OUTPUT_INFO
                )

    def _analyze_region_root(self, node, visits, ownership=False, timeout=60.0, until_depth=None, wide_root_noise=None):
        """使い捨てノードをリージョン限定で解析し root の {lead(黒視点), ownership} を返す。

        本譜の解析と同じリージョン・wideRootNoise で撃つ（条件を変えると本譜の候補評価と
        比較できなくなる）。取れなければ None。

        `until_depth` はリージョン外を禁じる深さ。既定（None=1）は本譜と同じで root の着手選択
        だけを縛る。**PV の内容を証拠に使う呼び出しだけ** `TSUMEGO_KO_REGION_UNTIL_DEPTH` を渡す
        （untilDepth=1 の PV は ply2 以降で枠へ手抜きし、コウが現れない）。

        `wide_root_noise` も同じく**応手の並びを証拠に使う呼び出しだけ**が 0 を渡す
        （`TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`）。既定（None）は本譜と同じ設定。

        複数の独立な子局面を測るときはこれを1本ずつ呼ばず、`_start_region_root` +
        `_wait_region_roots` で並列に撃つこと（内容は同一で待ちだけ縮む）。
        """
        handle = self._start_region_root(
            node, visits, ownership=ownership, until_depth=until_depth, wide_root_noise=wide_root_noise
        )
        self._wait_region_roots([handle], timeout=timeout)
        return handle.get("root")


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
        elif mode == "complex":
            return self._generate_human(complex_mode=True)
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

    def _build_complexity_weight_dict(self):
        """複雑化重み = 力戦重み（contact/invasion 込み）× 切りボーナス。"""
        base_weights = self._build_fighting_weight_dict()
        cut_boost = self.settings.get("complexity_cut_boost", 2.0)
        opponent_player = "W" if self.cn.next_player == "B" else "B"
        return _apply_cut_boost(
            base_weights, self.game.board, self.game.chains, opponent_player, cut_boost
        )

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

    def _generate_human(self, complex_mode: bool = False) -> Tuple[Move, str]:
        """案B: HumanStyleStrategy拡張 + 力戦重みで着���選択"""
        self.game.katrain.log(
            f"[FightingStrategy:{'complex' if complex_mode else 'human'}] Starting move generation",
            OUTPUT_DEBUG,
        )

        # complex モード用の変数を早期初期化（move_infos が空でも Step 4/5 で参照されるため）
        complexity_weights = {}
        current_lead = 0.0

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

            # --- complex モード: リード適応＋鋭さ＋複雑さゲート ---
            # complexity_weights: cut_boost 込み（最終選択の重み付け用）
            # gate_weights: cut_boost 抜きの素の力戦重み（損失予算ゲートの複雑さ条件用）。
            #   cut_boost で max が膨らみ高損失手が閾値(0.5×max)を超えられず門前払いになる
            #   相互干渉を避けるため、ゲート判定は素の力戦重みで行う。
            complexity_weights = {}
            gate_weights = {}
            current_lead = best_score
            if complex_mode:
                _opp_stones = [s for s in self.game.stones if s.player != self.cn.next_player]
                if len(_opp_stones) >= 2:
                    complexity_weights = self._build_complexity_weight_dict()
                    gate_weights = self._build_fighting_weight_dict()
                root_src = clean_analysis if (clean_analysis and not clean_error) else analysis
                current_lead = player_sign * (root_src or {}).get("rootInfo", {}).get("scoreLead", best_score)
                lead_threshold = self.settings.get("complexity_lead_threshold", 15.0)
                complexity_max_loss = self.settings.get("complexity_max_loss", 10.0)
                sharpness_min = self.settings.get("complexity_sharpness_min", 3.0)
                complexity_base_max_loss = self.settings.get("complexity_base_max_loss", BAD_MOVE_THRESHOLD)
                complexity_weight_by_gtp = {
                    Move((x, y), player=self.cn.next_player).gtp(): w
                    for (x, y), w in gate_weights.items()
                }
                good_moves = _complexity_loss_filter(
                    move_infos, best_score, player_sign, BAD_MOVE_THRESHOLD,
                    current_lead, lead_threshold, complexity_max_loss, sharpness_min,
                    _COMPLEXITY_WEIGHT_FRAC, complexity_weight_by_gtp, _COMPLEXITY_RAMP,
                    complexity_base_max_loss,
                )
                _effective_cap = max(
                    _complexity_relaxed_cap(current_lead, BAD_MOVE_THRESHOLD, lead_threshold, complexity_max_loss),
                    complexity_base_max_loss,
                )
                self.game.katrain.log(
                    f"[FightingStrategy:complex] lead={current_lead:.1f} "
                    f"cap={_effective_cap:.1f} (base={complexity_base_max_loss:.1f}) "
                    f"{len(good_moves)} moves pass complexity filter",
                    OUTPUT_DEBUG,
                )
            else:
                good_moves = _filter_moves(move_infos, BAD_MOVE_THRESHOLD, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score)
            # --- 段階的閾値緩和フェイルセーフ ---
            _FILTER_RELAXATION_STEPS = [1.5, 2.0]
            _FILTER_ABSOLUTE_CAP = 9.0
            if not complex_mode and not good_moves:
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
            if not complex_mode:
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
            if complex_mode:
                _SAFETY_LOSS_THRESHOLD = max(
                    4.0,
                    _complexity_relaxed_cap(
                        current_lead, BAD_MOVE_THRESHOLD, lead_threshold, complexity_max_loss,
                    ),
                    complexity_base_max_loss,
                )
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
        if complex_mode:
            fighting_weights = complexity_weights
        elif len(opponent_stones) >= 2:
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

        # complex: 予算バンド（loss>=base_threshold、既にsharp+complexゲート通過済み）の勝負手を
        # 選択でも実際に打てるよう重みを底上げする。humanPolicy≒0で抽選に勝てない問題への対処。
        # ゲートが品質を担保しているので「ただの悪手」は混ざらない。
        if complex_mode and moves and _COMPLEXITY_SACRIFICE_FLOOR > 0:
            loss_by_gtp = {
                mi.get("move", ""): player_sign * (best_score - mi.get("scoreLead", 0))
                for mi in (move_infos or [])
            }
            # ゲート通過済みだが humanPolicy=0 で選択プールに入らなかった予算バンド手を追加
            _present = {m.gtp() for m, _ in moves}
            for _gtp in good_moves:
                if _gtp != "pass" and _gtp not in _present and loss_by_gtp.get(_gtp, 0.0) >= BAD_MOVE_THRESHOLD:
                    _bm = Move.from_gtp(_gtp, player=self.cn.next_player)
                    if _bm.coords is not None:
                        moves.append((_bm, 0.0))
            _losses = [loss_by_gtp.get(m.gtp(), 0.0) for m, _ in moves]
            _floored = _floor_budget_weights(
                [w for _, w in moves], _losses, BAD_MOVE_THRESHOLD, _COMPLEXITY_SACRIFICE_FLOOR
            )
            _n_budget = sum(1 for lv in _losses if lv >= BAD_MOVE_THRESHOLD)
            if _n_budget:
                moves = [(m, _floored[i]) for i, (m, _) in enumerate(moves)]
                self.game.katrain.log(
                    f"[FightingStrategy:complex] Sacrifice floor: {_n_budget} budget moves "
                    f"(loss>={BAD_MOVE_THRESHOLD}) floored to {_COMPLEXITY_SACRIFICE_FLOOR}x max weight",
                    OUTPUT_DEBUG,
                )

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

        label = "Complex+Fighting" if complex_mode else "Human+Fighting"
        ai_thoughts = (
            f"\n{top_str}\n\n{label}: played {move.gtp()} "
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
_COMPLEXITY_SACRIFICE_FLOOR = 0.3  # 予算バンド手の選択重みフロア（候補中最大重みに対する比、0で無効）


def _floor_budget_weights(weights, losses, base_threshold, floor_frac):
    """予算バンド（loss >= base_threshold）の手の選択重みを floor_frac × max(weights) まで
    底上げした新リストを返す。humanPolicy≒0 の勝負手が抽選で選ばれない問題への対処。
    floor_frac <= 0 で無効（現状維持）。"""
    if floor_frac <= 0 or not weights:
        return list(weights)
    floor_w = floor_frac * max(weights)
    return [max(w, floor_w) if losses[i] >= base_threshold else w for i, w in enumerate(weights)]


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


def _complexity_relaxed_cap(current_lead, base_threshold, lead_threshold, max_loss, ramp=_COMPLEXITY_RAMP):
    """リードに応じた損失上限。current_lead < lead_threshold なら base のまま。"""
    if current_lead < lead_threshold or max_loss <= base_threshold:
        return base_threshold
    frac = min(1.0, (current_lead - lead_threshold) / ramp) if ramp > 0 else 1.0
    return base_threshold + frac * (max_loss - base_threshold)


def _passes_complexity_gate(loss, base_threshold, relaxed_cap, score_stdev, sharpness_min,
                            complexity_weight, max_complexity_weight, weight_frac):
    """1手がフィルタを通過するか判定する。"""
    if loss < base_threshold:
        return True
    if loss >= relaxed_cap:
        return False
    if score_stdev is None or score_stdev < sharpness_min:
        return False
    if max_complexity_weight <= 0:
        return False
    if complexity_weight < weight_frac * max_complexity_weight:
        return False
    return True


def _complexity_loss_filter(move_infos, best_score, player_sign, base_threshold,
                            current_lead, lead_threshold, max_loss, sharpness_min,
                            weight_frac, complexity_weight_by_gtp, ramp=_COMPLEXITY_RAMP,
                            base_max_loss=None):
    """complex モードの悪手フィルタ。通過手の GTP set を返す。

    base_max_loss: リードに関係なく常時開放するゲート付き帯の上限（None=base_threshold）。
    効く上限 = max(base_max_loss, リード適応 relaxed_cap)。無条件パス帯(loss<base_threshold)は不変。
    """
    relaxed_cap = _complexity_relaxed_cap(current_lead, base_threshold, lead_threshold, max_loss, ramp)
    if base_max_loss is not None:
        relaxed_cap = max(relaxed_cap, base_max_loss)
    max_cw = max(complexity_weight_by_gtp.values(), default=0.0)
    result = set()
    for mi in move_infos:
        gtp = mi.get("move", "")
        score = mi.get("scoreLead", 0)
        loss = player_sign * (best_score - score)
        stdev = mi.get("scoreStdev")
        cw = complexity_weight_by_gtp.get(gtp, 0.0)
        if _passes_complexity_gate(loss, base_threshold, relaxed_cap, stdev, sharpness_min, cw, max_cw, weight_frac):
            result.add(gtp)
    return result


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