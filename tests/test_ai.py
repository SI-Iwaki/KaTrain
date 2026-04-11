import os

import pytest

from katrain.core.ai import ai_rank_estimation, generate_ai_move, find_connected_groups
from katrain.core.base_katrain import KaTrainBase
from katrain.core.constants import AI_STRATEGIES, AI_STRATEGIES_RECOMMENDED_ORDER, AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, OUTPUT_INFO
from katrain.core.engine import KataGoEngine
from katrain.core.game import Game


class TestAI:
    def test_order(self):
        assert set(AI_STRATEGIES_RECOMMENDED_ORDER) == set(AI_STRATEGIES)

    @pytest.mark.skipif(os.environ.get("CI", "").lower() == "true", reason="GH actions has no OpenCL")
    def test_ai_strategies(self):
        katrain = KaTrainBase(force_package_config=True, debug_level=0)
        engine = KataGoEngine(katrain, katrain.config("engine"))

        game = Game(katrain, engine)
        n_rounds = 3
        for _ in range(n_rounds):
            for strategy in AI_STRATEGIES:
                if strategy in [AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE]:
                    continue
                settings = katrain.config(f"ai/{strategy}")
                move, played_node = generate_ai_move(game, strategy, settings)
                katrain.log(f"Testing strategy {strategy} -> {move}", OUTPUT_INFO)
                assert move.coords is not None
                assert played_node == game.current_node

        assert game.current_node.depth == (len(AI_STRATEGIES) - 4) * n_rounds

        for strategy in AI_STRATEGIES:
            if strategy in [AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE]:
                continue
            game = Game(katrain, engine)
            settings = katrain.config(f"ai/{strategy}")
            move, played_node = generate_ai_move(game, strategy, settings)
            katrain.log(f"Testing strategy on first move {strategy} -> {move}", OUTPUT_INFO)
            assert game.current_node.depth == 1

    def test_ai_rank_estimation(self):
        katrain = KaTrainBase(force_package_config=True, debug_level=0)
        for strategy in AI_STRATEGIES:
            if strategy in [AI_HUMAN, AI_PRO]:
                continue
            settings = katrain.config(f"ai/{strategy}")
            rank = ai_rank_estimation(strategy, settings)
            assert -20 <= rank <= 9


class TestFindConnectedGroups:
    def test_single_stone(self):
        stones = {(3, 3)}
        groups = find_connected_groups(stones)
        assert len(groups) == 1
        assert groups[0] == {(3, 3)}

    def test_two_connected_stones(self):
        stones = {(3, 3), (3, 4)}
        groups = find_connected_groups(stones)
        assert len(groups) == 1
        assert groups[0] == {(3, 3), (3, 4)}

    def test_two_separate_groups(self):
        stones = {(0, 0), (5, 5)}
        groups = find_connected_groups(stones)
        assert len(groups) == 2

    def test_diagonal_not_connected(self):
        stones = {(3, 3), (4, 4)}
        groups = find_connected_groups(stones)
        assert len(groups) == 2

    def test_l_shape_group(self):
        stones = {(0, 0), (1, 0), (1, 1), (1, 2)}
        groups = find_connected_groups(stones)
        assert len(groups) == 1
        assert len(groups[0]) == 4

    def test_empty_input(self):
        groups = find_connected_groups(set())
        assert len(groups) == 0


class TestFindTargets:
    def test_score_calculation(self):
        group_size = 5
        avg_ownership = -0.5
        instability = 1 - abs(avg_ownership)
        score = group_size * instability
        assert instability == 0.5
        assert score == 2.5

    def test_instability_range(self):
        assert 1 - abs(-1.0) == 0.0
        assert 1 - abs(0.0) == 1.0
        assert abs(1 - abs(-0.3) - 0.7) < 0.01


from katrain.core.ai import count_group_liberties


class TestCountGroupLiberties:
    def test_corner_group_liberties(self):
        # 19x19 board, -1 = empty, 0+ = chain id
        board = [[-1] * 19 for _ in range(19)]
        # Place a 2-stone group at (0,0) and (1,0) — chain id 0
        board[0][0] = 0
        board[0][1] = 0
        group_coords = {(0, 0), (1, 0)}
        board_size = (19, 19)
        libs = count_group_liberties(board, group_coords, board_size)
        # (0,0) neighbors: (1,0)=same group, (0,1)=empty → 1 liberty
        # (1,0) neighbors: (0,0)=same group, (2,0)=empty, (1,1)=empty → 2 liberties
        # Total unique: {(0,1), (2,0), (1,1)} = 3
        assert libs == 3

    def test_surrounded_group_zero_liberties(self):
        board = [[-1] * 5 for _ in range(5)]
        # Target stone at (2,2) — chain 0
        board[2][2] = 0
        # Surround with chain 1
        board[2][1] = 1
        board[2][3] = 1
        board[1][2] = 1
        board[3][2] = 1
        group_coords = {(2, 2)}
        libs = count_group_liberties(board, group_coords, (5, 5))
        assert libs == 0

    def test_large_group_shared_liberties(self):
        board = [[-1] * 9 for _ in range(9)]
        # L-shape group at (0,0), (1,0), (1,1)
        board[0][0] = 0
        board[0][1] = 0
        board[1][1] = 0
        group_coords = {(0, 0), (1, 0), (1, 1)}
        libs = count_group_liberties(board, group_coords, (9, 9))
        # Unique empty neighbors: (0,1), (2,0), (2,1), (1,2), (0,1) counted once
        # (0,0) → right (1,0)=group, down (0,1)=empty → {(0,1)}
        # (1,0) → left (0,0)=group, right (2,0)=empty, down (1,1)=group → {(2,0)}
        # (1,1) → left (0,1)=empty, right (2,1)=empty, up (1,0)=group, down (1,2)=empty → {(0,1),(2,1),(1,2)}
        # Total unique: {(0,1), (2,0), (2,1), (1,2)} = 4
        assert libs == 4


from katrain.core.ai import evaluate_pursuit_targets


class TestEvaluatePursuitTargets:
    def _make_board(self, size=9):
        return [[-1] * size for _ in range(size)]

    def test_no_previous_targets(self):
        result = evaluate_pursuit_targets(
            previous_targets=[],
            opponent_move_coords=(4, 4),
            current_opponent_coords={(3, 3), (3, 4)},
            board=[[-1] * 9 for _ in range(9)],
            board_size=(9, 9),
            ownership_grid=None,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        assert result == []

    def test_opponent_move_far_from_target(self):
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": [(0, 0), (1, 0), (0, 1)], "size": 3}],
            opponent_move_coords=(8, 8),  # Far away
            current_opponent_coords={(0, 0), (1, 0), (0, 1)},
            board=[[-1] * 9 for _ in range(9)],
            board_size=(9, 9),
            ownership_grid=None,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        assert result == []

    def test_stones_removed_from_board(self):
        # Previous target coords no longer in current_opponent_coords
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": [(3, 3), (3, 4), (3, 5)], "size": 3}],
            opponent_move_coords=(3, 6),  # Near previous target
            current_opponent_coords=set(),  # Stones removed
            board=[[-1] * 9 for _ in range(9)],
            board_size=(9, 9),
            ownership_grid=None,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        assert result == []

    def test_pursue_high_liberties(self):
        board = [[-1] * 9 for _ in range(9)]
        # Place opponent stones — chain 0
        board[3][3] = 0
        board[4][3] = 0
        board[5][3] = 0
        target_coords = [(3, 3), (3, 4), (3, 5)]
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": target_coords, "size": 3}],
            opponent_move_coords=(3, 6),  # Adjacent to target
            current_opponent_coords={(3, 3), (3, 4), (3, 5)},
            board=board,
            board_size=(9, 9),
            ownership_grid=None,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        # Group has many liberties (>= 3), should pursue
        assert len(result) == 1
        assert result[0][2] == {(3, 3), (3, 4), (3, 5)}  # group coords

    def test_no_pursue_low_liberties_high_ownership(self):
        board = [[-1] * 9 for _ in range(9)]
        # Place opponent stone — chain 0
        board[4][4] = 0
        # Surround most sides — chain 1 (our stones)
        board[3][4] = 1
        board[5][4] = 1
        board[4][3] = 1
        # (4,5) is the only liberty
        target_coords = [(4, 4)]
        # ownership_grid: opponent's stone has high ownership for us
        ownership_grid = [[0.0] * 9 for _ in range(9)]
        ownership_grid[4][4] = 0.90  # Black owns this area strongly (player_sign=1)
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": target_coords, "size": 1}],
            opponent_move_coords=(4, 5),  # Adjacent to target
            current_opponent_coords={(4, 4)},
            board=board,
            board_size=(9, 9),
            ownership_grid=ownership_grid,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        # 1 liberty (< 3), ownership |0.90| >= 0.85, size < 10 → no pursuit
        assert result == []

    def test_pursue_low_liberties_low_ownership(self):
        board = [[-1] * 9 for _ in range(9)]
        board[4][4] = 0
        board[3][4] = 1
        board[5][4] = 1
        board[4][3] = 1
        target_coords = [(4, 4)]
        ownership_grid = [[0.0] * 9 for _ in range(9)]
        ownership_grid[4][4] = 0.70  # Not fully confirmed
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": target_coords, "size": 1}],
            opponent_move_coords=(4, 5),
            current_opponent_coords={(4, 4)},
            board=board,
            board_size=(9, 9),
            ownership_grid=ownership_grid,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        # 1 liberty (< 3), but ownership |0.70| < 0.85 → pursue
        assert len(result) == 1

    def test_large_group_stricter_threshold(self):
        board = [[-1] * 19 for _ in range(19)]
        target_coords = []
        for i in range(12):
            board[5][i] = 0
            target_coords.append((i, 5))
        # Place our stones to limit liberties to 2
        for i in range(12):
            board[4][i] = 1  # above
            board[6][i] = 1  # below
        board[5][12] = 1  # right end
        # Remove two blockers to create 2 liberties
        board[4][0] = -1  # open above (0,5)
        board[4][1] = -1  # open above (1,5)
        ownership_grid = [[0.0] * 19 for _ in range(19)]
        for i in range(12):
            ownership_grid[5][i] = 0.88  # player_sign=1, so this is ours (high)
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": target_coords, "size": 12}],
            opponent_move_coords=(0, 4),  # Near target (distance 1 from (0,5))
            current_opponent_coords=set(target_coords),
            board=board,
            board_size=(19, 19),
            ownership_grid=ownership_grid,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        # 2 liberties (< 3), size=12 (>=10) → threshold bumped to 0.90
        # |ownership| = 0.88 < 0.90 → pursue
        assert len(result) == 1
