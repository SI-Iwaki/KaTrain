import json
import pytest
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame


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
