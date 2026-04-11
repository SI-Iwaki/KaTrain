import json
import os
import pytest
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame, STRATEGY_NAME_MAP, load_sgf_to_move


class TestDebugGame:
    def test_init_does_not_start_analysis_thread(self, tmp_path):
        """DebugGameはanalyze_all_nodesスレッドを起動しない"""
        config_data = {
            "general": {"debug_level": 1},
            "game": {"size": 9, "komi": 6.5, "rules": "japanese", "handicap": 0},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        game = DebugGame(katrain=stub, engine={}, bypass_config=True)
        assert game.engines == {}
        assert game.current_node is not None

    def test_init_with_sgf_tree(self, tmp_path):
        """SGF move_treeを渡してもanalyze_all_nodesが走らない"""
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))

        from katrain.core.game import KaTrainSGF
        sgf_path = "tests/data/ogs.sgf"
        move_tree = KaTrainSGF.parse_file(sgf_path)
        game = DebugGame(katrain=stub, engine={}, move_tree=move_tree)
        assert game.root is move_tree
        assert game.current_node is not None

    def test_play_does_not_trigger_analysis(self, tmp_path):
        """DebugGame.playは分析リクエストを送らない"""
        config_data = {
            "general": {"debug_level": 1},
            "game": {"size": 9, "komi": 6.5, "rules": "japanese", "handicap": 0},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        game = DebugGame(katrain=stub, engine={}, bypass_config=True)

        from katrain.core.sgf_parser import Move
        move = Move.from_gtp("D4", "B")
        played_node = game.play(move)
        assert played_node is not None
        assert game.current_node == played_node


class TestStrategyNameMapping:
    def test_known_strategies(self):
        assert STRATEGY_NAME_MAP["hunt"] == "ai:hunt"
        assert STRATEGY_NAME_MAP["siege"] == "ai:siege"
        assert STRATEGY_NAME_MAP["human"] == "ai:human"
        assert STRATEGY_NAME_MAP["fighting"] == "ai:p:fighting"
        assert STRATEGY_NAME_MAP["hunt_diverge"] == "ai:hunt_diverge"
        assert STRATEGY_NAME_MAP["diverge"] == "ai:diverge_move"

    def test_pro_strategy(self):
        assert STRATEGY_NAME_MAP["pro"] == "ai:pro"

    def test_default_strategy(self):
        assert STRATEGY_NAME_MAP["default"] == "ai:default"

    def test_unknown_strategy_not_in_map(self):
        assert "nonexistent" not in STRATEGY_NAME_MAP


class TestLoadSGFAndNavigate:
    def test_navigate_to_move(self):
        game_node = load_sgf_to_move("tests/data/ogs.sgf", move_number=5)
        assert game_node.depth == 5

    def test_navigate_to_move_1(self):
        game_node = load_sgf_to_move("tests/data/ogs.sgf", move_number=1)
        assert game_node.depth == 1

    def test_navigate_to_move_0_returns_root(self):
        game_node = load_sgf_to_move("tests/data/ogs.sgf", move_number=0)
        assert game_node.depth == 0

    def test_move_number_exceeds_game_length(self):
        with pytest.raises(ValueError, match="exceeds"):
            load_sgf_to_move("tests/data/ogs.sgf", move_number=9999)


@pytest.mark.skipif(
    not os.path.exists(os.path.expanduser("~/.katrain/katago.exe")),
    reason="KataGo not installed",
)
class TestRunStrategyIntegration:
    """実際のKataGoプロセスを使う結合テスト"""

    def test_run_hunt_strategy(self):
        from katrain_debug.runner import run_strategy

        result = run_strategy(
            sgf_path="tests/data/ogs.sgf",
            move_number=30,
            strategy_name="hunt",
        )
        assert result["move"] is not None
        assert result["player"] in ("B", "W")
        assert result["strategy"] == "hunt"
        assert result["strategy_class"] == "HuntStrategy"
        assert len(result["logs"]) > 0

    def test_run_human_strategy(self):
        from katrain_debug.runner import run_strategy

        result = run_strategy(
            sgf_path="tests/data/ogs.sgf",
            move_number=10,
            strategy_name="human",
        )
        assert result["move"] is not None
        assert result["strategy_class"] == "HumanStyleStrategy"

    def test_settings_override(self):
        from katrain_debug.runner import run_strategy

        result = run_strategy(
            sgf_path="tests/data/ogs.sgf",
            move_number=30,
            strategy_name="hunt",
            settings_overrides={"hunt_max_loss": 3.0},
        )
        assert result["settings"]["hunt_max_loss"] == 3.0
        assert result["move"] is not None

    def test_invalid_strategy_raises(self):
        from katrain_debug.runner import run_strategy

        with pytest.raises(KeyError, match="Unknown strategy"):
            run_strategy(
                sgf_path="tests/data/ogs.sgf",
                move_number=10,
                strategy_name="nonexistent",
            )

    def test_json_output_is_valid(self):
        from katrain_debug.runner import run_strategy
        from katrain_debug.cli import format_json_output

        result = run_strategy(
            sgf_path="tests/data/ogs.sgf",
            move_number=10,
            strategy_name="human",
        )
        json_str = format_json_output(result, "tests/data/ogs.sgf", 10)
        parsed = json.loads(json_str)
        assert parsed["move_number"] == 10
        assert "result" in parsed
        assert "logs" in parsed
