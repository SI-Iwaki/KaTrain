# tests/test_debug_stub.py
import json
import pytest
from katrain_debug.katrain_stub import KaTrainStub


class TestKaTrainStubLog:
    def test_log_accumulates_messages(self):
        stub = KaTrainStub.__new__(KaTrainStub)
        stub.debug_level = 1
        stub.logs = []
        stub.log("test message", 1)
        assert len(stub.logs) == 1
        assert stub.logs[0] == ("test message", 1)

    def test_log_accumulates_all_levels(self):
        stub = KaTrainStub.__new__(KaTrainStub)
        stub.debug_level = 1
        stub.logs = []
        stub.log("debug", 1)
        stub.log("info", 0)
        stub.log("error", -1)
        assert len(stub.logs) == 3

    def test_log_prints_when_level_sufficient(self, capsys):
        stub = KaTrainStub.__new__(KaTrainStub)
        stub.debug_level = 1
        stub.logs = []
        stub.log("visible", 1)
        captured = capsys.readouterr()
        assert "visible" in captured.out

    def test_log_suppresses_when_level_insufficient(self, capsys):
        stub = KaTrainStub.__new__(KaTrainStub)
        stub.debug_level = 0
        stub.logs = []
        stub.log("hidden", 1)
        captured = capsys.readouterr()
        assert "hidden" not in captured.out
        assert len(stub.logs) == 1


class TestKaTrainStubConfig:
    def test_config_simple_key(self, tmp_path):
        config_data = {"engine": {"max_visits": 800}, "general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert stub.config("engine") == {"max_visits": 800}

    def test_config_slash_path(self, tmp_path):
        config_data = {"engine": {"max_visits": 800}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert stub.config("engine/max_visits") == 800

    def test_config_default_value(self, tmp_path):
        config_data = {"engine": {}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert stub.config("engine/missing_key", 42) == 42

    def test_config_missing_category(self, tmp_path):
        config_data = {"engine": {}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert stub.config("nonexistent/key", "default") == "default"


class TestKaTrainStubControls:
    def test_controls_set_status_is_noop(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        stub.controls.set_status("test", 0)

    def test_controls_move_tree_is_noop(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        stub.controls.move_tree.insert_node = None
        stub.controls.move_tree.redraw()
        stub.controls.move_tree.redraw_tree_trigger()

    def test_update_state_is_noop(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        stub.update_state()


class TestKaTrainStubPlayersInfo:
    def test_players_info_has_both_colors(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert "B" in stub.players_info
        assert "W" in stub.players_info

    def test_players_info_are_player_objects(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        from katrain.core.base_katrain import Player
        assert isinstance(stub.players_info["B"], Player)
        assert isinstance(stub.players_info["W"], Player)
