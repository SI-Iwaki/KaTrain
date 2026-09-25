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


class TestOfflineReport:
    def test_bins_follow_the_board_size(self):
        off = _load("offline_report")
        rows = [
            {"depth": d, "player": "B" if d % 2 else "W", "ptloss": 0.5, "match": d % 3 == 0, "score": 1.0}
            for d in range(1, 60)
        ]
        s13 = off.summarize("g", "B", rows, 13)
        assert [k for k in s13 if "85" in k] == ["mine_pre85", "mine_post85", "opp_pre85", "opp_post85"]
        assert s13["board_size"] == 13 and s13["mine_post85"] is None
        s9 = off.summarize("g", "B", rows, 9)
        assert [k for k in s9 if "41" in k] == ["mine_pre41", "mine_post41", "opp_pre41", "opp_post41"]
        assert s9["board_size"] == 9 and s9["mine_post41"]["n"] == 10


def _calib_targets(*args):
    r = subprocess.run(
        [sys.executable, os.path.join(DATA, "calib_targets.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return r.stdout.splitlines()


class TestCalibTargets:
    def test_13x13_output_is_unchanged(self):
        """recon/（13路 18局）の既存の出力 32 行は変えない（2026-09-26 の出力の sha256）。"""
        lines = _calib_targets()
        digest = hashlib.sha256("\n".join(lines[:32]).encode("utf-8")).hexdigest()
        assert digest == "1d8e92e93c8d56cad8b3e01d728dcaac2074fdd3254a02bc6795daec3b089cc0"
        assert lines[32:34] == ["games 18 / ai_mean over 18 (all)", "CALIB_TARGET_GAMES 18/18"]

    def test_9x9_bins_filters_and_the_targets_line(self, tmp_path):
        for i, (loss_ok, cfg) in enumerate(((True, 1.6), (False, 1.8))):
            rows = [
                {
                    "depth": d,
                    "player": "B" if d % 2 else "W",
                    "ptloss": 3.0 if d == 42 else 0.2,
                    "match": d < 12,
                    "score": 1.0,
                    "top_prior": 0.5,
                }
                for d in range(1, 49)
            ]
            summary = {
                "game": f"g{i}",
                "ai": "B",
                "n_moves": 48,
                "final_score": 5.0,
                "secs": 1.0,
                "strategy": "Enigma9PlusStrategy",
                "board_size": 9,
                "mine": {"n": 24, "match": 0.5 if loss_ok else 0.25, "mean_loss": 0.2},
                "opp": {"n": 24, "match": 0.2 + 0.1 * i, "mean_loss": 0.4},
                "settings": {"enigma9plus_max_loss": cfg},
            }
            (tmp_path / f"report_game_{i}.json").write_text(
                json.dumps({"summary": summary, "rows": rows}), encoding="utf-8"
            )
        lines = _calib_targets(str(tmp_path), "--size", "9", "--ai-where", "enigma9plus_max_loss=1.6")
        assert any(line.startswith("opp opening<12 ") for line in lines)
        assert any(line.startswith("opp middle12-40 ") for line in lines)
        assert any(line.startswith("opp endgame>=41 ") for line in lines)
        assert "CALIB_TARGET_GAMES 1/2" in lines
        targets = json.loads(next(line for line in lines if line.startswith("CALIB_TARGETS "))[len("CALIB_TARGETS ") :])
        assert targets["ai_mean"] == 0.5 and targets["opp_mean"] == 0.25 and targets["moves_median"] == 48
        assert targets["bins"]["cal_opening"]["opp_top1"] == 1.0 and targets["bins"]["cal_endgame"]["opp_top1"] == 0.0
        assert targets["opp_ge2"] == round(2 / 48, 2)
