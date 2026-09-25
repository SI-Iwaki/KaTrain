# tests/test_selfplay_recon.py
"""実戦の復元と事後解析のスクリプト（docs/superpowers/specs/calibration-data/selfplay/ の recon_logs.py・offline_report.py・
calib_targets.py）。KataGo は起動しない（offline_report は summarize だけ・calib_targets は合成の report で走らせる）。

設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md §16.2 手順1〜4
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "docs", "superpowers", "specs", "calibration-data", "selfplay")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(DATA, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestReconLogs:
    def test_missing_opponent_pass_is_inserted_before_an_opponent_passed_turn(self):
        rl = _load("recon_logs")
        reason = {"reason": "Enigma9Plus: opponent passed but the board is not settled, playing best move."}
        events = [
            ("ai", "E5", {"reason": "x"}),
            ("opp", "C3", None),
            ("ai", "F2", {"reason": "y"}),
            ("ai", "G8", reason),
        ]
        fixed, inserted = rl.insert_opponent_passes(events)
        assert [(w, m) for w, m, _ in fixed] == [
            ("ai", "E5"),
            ("opp", "C3"),
            ("ai", "F2"),
            ("opp", "pass"),
            ("ai", "G8"),
        ]
        assert inserted == [4]  # 1 始まりの手数

    def test_a_logged_opponent_pass_is_not_doubled(self):
        rl = _load("recon_logs")
        reason = {"reason": "Enigma9Plus: opponent passed but the board is not settled, playing best move."}
        events = [("ai", "E5", {"reason": "x"}), ("opp", "pass", None), ("ai", "G8", reason)]
        assert rl.insert_opponent_passes(events) == (events, [])

    def test_a_single_setup_stone_of_the_other_colour_is_the_first_move(self):
        rl = _load("recon_logs")
        assert rl.setup_as_first_move([("B", "G7")], "W") == ([], "B", ("B", "G7"))
        assert rl.setup_as_first_move([], "B") == ([], "B", None)
        assert rl.setup_as_first_move([("B", "C3"), ("B", "G7")], "W") == ([("B", "C3"), ("B", "G7")], "W", None)

    def test_board_size_goes_into_the_sgf_coordinates(self):
        rl = _load("recon_logs")
        assert rl.gtp_to_sgf("G7", 9) == "gc" and rl.gtp_to_sgf("G7", 13) == "gg" and rl.gtp_to_sgf("pass", 9) == ""
        assert rl.EXCLUDE_9 == {"game_20260919_224212": "持碁9路（初手だけ難解＋）"}

    def test_9x9_log_is_reconstructed_with_the_fixes(self, tmp_path):
        """合成のログ（相手の初手が root の置き石・監視の外の相手のパス）から SGF と summary を作る。"""
        stones = '"initialStones": [["B", "G7"]], "rules": "chinese", "initialPlayer": "W"'
        settings = {"enigma9plus_max_loss": 1.6, "enigma9plus_target_score": 0.2}
        lines = [
            "board_watch: アプリの局面（9路）を取り込みました（手番=W・2子以内なので石数から確定）",
            'Sending query QUERY:1: {"komi": 7.0, ' + stones + "}",
            f"Initializing Enigma9PlusStrategy with settings: {settings!r}",
            "Generating move using Enigma9PlusStrategy (mode ai:enigma9plus)",
            "Move generation complete: F6 -- Enigma9Plus: best move is also the most confusing in budget, playing it.",
            "board_watch: 相手の着手 G6 を反映しました",
            "Generating move using Enigma9PlusStrategy (mode ai:enigma9plus)",
            "Move generation complete: F5 -- Enigma9Plus: no admissible deviation (cap 6.00), playing best move.",
            "Generating move using Enigma9PlusStrategy (mode ai:enigma9plus)",
            "Move generation complete: G8 -- Enigma9Plus: opponent passed but the board is not settled, playing best move.",
        ]
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "game_20260919_213546.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        rl = _load("recon_logs")
        rl.main(["--size", "9", "--log-dir", str(tmp_path / "logs"), "--out", str(tmp_path / "recon_9")])
        sgf = (tmp_path / "recon_9" / "game_20260919_213546.sgf").read_text(encoding="utf-8")
        assert sgf.startswith("(;GM[1]FF[4]SZ[9]KM[7]RU[chinese]PB[app]PW[AI:Enigma9PlusStrategy]")
        assert sgf.endswith("PL[B];B[gc];W[fd];B[gd];W[fe];B[];W[gb])")
        (s,) = json.loads((tmp_path / "recon_9" / "summary.json").read_text(encoding="utf-8"))
        assert s["board_size"] == 9 and s["ai"] == "W" and s["n_moves"] == 6 and s["problems"] == []
        assert s["setup_as_first_move"] == ["B", "G7"] and s["inserted_opponent_passes"] == [5]
        assert s["settings"] == settings and s["settings_changed"] == []

    def test_9x9_default_keeps_only_the_enigma9plus_games(self, tmp_path):
        """spec §16.2 手順1: 同じ置き場に退避した一致率ひかえめ9路の局は recon_9 に混ぜない（--strategy で recon_9_veil に出す）。"""
        (tmp_path / "logs").mkdir()
        for name, cls, mode in (
            ("game_20260930_200000", "Enigma9PlusStrategy", "ai:enigma9plus"),
            ("game_20260930_210000", "Veil9Strategy", "ai:veil9"),
        ):
            lines = [
                'Sending query QUERY:1: {"komi": 7.0, "initialStones": [], "rules": "chinese", "initialPlayer": "B"}',
                f"Generating move using {cls} (mode {mode})",
                "Move generation complete: E5 -- best move is also the most confusing in budget, playing it.",
                "board_watch: 相手の着手 C3 を反映しました",
            ]
            (tmp_path / "logs" / f"{name}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        rl = _load("recon_logs")
        logs = ["--size", "9", "--log-dir", str(tmp_path / "logs")]
        rl.main([*logs, "--out", str(tmp_path / "recon_9")])
        (s,) = json.loads((tmp_path / "recon_9" / "summary.json").read_text(encoding="utf-8"))
        assert (s["game"], s["strategy"]) == ("game_20260930_200000", "Enigma9PlusStrategy")
        assert not (tmp_path / "recon_9" / "game_20260930_210000.sgf").exists()
        rl.main([*logs, "--strategy", "Veil9Strategy", "--out", str(tmp_path / "recon_9_veil")])
        (v,) = json.loads((tmp_path / "recon_9_veil" / "summary.json").read_text(encoding="utf-8"))
        assert (v["game"], v["strategy"], v["n_moves"]) == ("game_20260930_210000", "Veil9Strategy", 2)
