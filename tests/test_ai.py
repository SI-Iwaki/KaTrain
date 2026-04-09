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
