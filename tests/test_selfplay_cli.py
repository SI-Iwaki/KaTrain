# tests/test_selfplay_cli.py
"""自己対局ハーネスの CLI（python -m katrain_debug.selfplay）。KataGo の代わりに偽エンジンを差し込む。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §8
"""

import json
import os

import pytest

from katrain_debug import selfplay as CLI
from tests.selfplay_fakes import FakeEngine, make_stub


@pytest.fixture
def env(tmp_path, monkeypatch):
    make_stub(tmp_path, **{"ai:policy": {}})  # tmp_path/config.json を書く
    monkeypatch.setattr(CLI, "start_engine", lambda stub: FakeEngine())
    monkeypatch.setattr(CLI, "katago_processes", lambda: [])
    return {"config": str(tmp_path / "config.json"), "out": str(tmp_path / "out"), "tmp": tmp_path}


def _run_args(env, *extra):
    return [
        "run",
        "--size",
        "9",
        "--pairs",
        "2",
        "--ranks",
        "rank_3k",
        "--no-resign",
        "--max-moves",
        "6",
        "--timeout",
        "5",
        "--boot",
        "100",
        "--config",
        env["config"],
        "--out-root",
        env["out"],
        "--label",
        "t",
        *extra,
    ]


def _only_dir(root):
    dirs = os.listdir(root)
    assert len(dirs) == 1
    return os.path.join(root, dirs[0])


class TestRun:
    def test_end_to_end_with_resume_and_summarize(self, env, capsys):
        CLI.main(_run_args(env, "--arm", "A=default"))
        run_dir = _only_dir(env["out"])
        assert run_dir.endswith("_t")
        plan = json.load(open(os.path.join(run_dir, "run.json"), encoding="utf-8"))
        assert plan["arms"][0]["mode"] == "ai:default" and plan["opponent"]["ranks"] == ["rank_3k"]
        assert plan["git"] is not None and plan["ai_file"].endswith("ai.py") and "engine" in plan
        assert plan["resign"]["no_resign"] is True and all(s["resign_lead"] is None for s in plan["schedule"])
        games = open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8").read().splitlines()
        assert len(games) == 2
        out = capsys.readouterr().out
        assert "output:" in out and "# selfplay summary" in out

        CLI.main(["run", "--resume", run_dir, "--boot", "100"])
        assert len(open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8").read().splitlines()) == 2

        CLI.main(["summarize", run_dir, "--compare", "A", "A", "--boot", "100"])
        assert "paired diff A - A" in capsys.readouterr().out

    def test_refuses_to_run_next_to_a_live_katago(self, env, monkeypatch):
        monkeypatch.setattr(CLI, "katago_processes", lambda: ["katago.exe  1234 Console  1  900,000 K"])
        with pytest.raises(SystemExit, match="already running"):
            CLI.main(_run_args(env, "--arm", "A=default"))
        CLI.main(_run_args(env, "--arm", "A=default", "--allow-concurrent"))

    def test_null_experiment_is_refused(self, env):
        with pytest.raises(SystemExit, match="null experiment"):
            CLI.main(_run_args(env, "--arm", "A=default", "--arm", "B=default"))

    def test_typo_in_an_override_is_refused(self, env):
        with pytest.raises(SystemExit, match="unknown setting keys"):
            CLI.main(_run_args(env, "--arm", "A=enigma13plus:enigma13plus_max_los=2.0"))

    def test_missing_ranks_is_refused(self, env, monkeypatch):
        monkeypatch.setattr(CLI.R, "default_pool_path", lambda size: os.path.join(env["out"], "missing.json"))
        args = [a for a in _run_args(env, "--arm", "A=default") if a not in ("--ranks", "rank_3k")]
        with pytest.raises(SystemExit, match="no opponent ranks"):
            CLI.main(args)

    def test_opponent_pool_file_sets_ranks_and_tau(self, env):
        pool = env["tmp"] / "pool.json"
        pool.write_text(json.dumps({"ranks": ["rank_1k", "rank_1d"], "tau": 0.9}), encoding="utf-8")
        args = [a for a in _run_args(env, "--arm", "A=default") if a not in ("--ranks", "rank_3k")]
        CLI.main(args + ["--opp-pool", str(pool)])
        plan = json.load(open(os.path.join(_only_dir(env["out"]), "run.json"), encoding="utf-8"))
        assert plan["opponent"]["tau"] == 0.9 and [s["rank"] for s in plan["schedule"]] == ["rank_1k", "rank_1k"]

    def test_strategy_opponent(self, env):
        CLI.main(_run_args(env, "--arm", "A=default", "--opponent", "strategy:default"))
        recs = [json.loads(x) for x in open(os.path.join(_only_dir(env["out"]), "games.jsonl"), encoding="utf-8")]
        assert all(r["opponent"] == "strategy:default" and r["opp_top1"] == 1.0 for r in recs)


class TestCalibrate:
    def test_writes_calibration_files_and_the_pool(self, env):
        pool = env["tmp"] / "opponent_pool_13.json"
        CLI.main(
            [
                "calibrate",
                "--size",
                "13",
                "--strategy",
                "default",
                "--ranks",
                "rank_8k,rank_3k,rank_1d",
                "--games",
                "2",
                "--no-resign",
                "--max-moves",
                "6",
                "--timeout",
                "5",
                "--boot",
                "100",
                "--config",
                env["config"],
                "--out-root",
                env["out"],
                "--write-pool",
                str(pool),
            ]
        )
        run_dir = _only_dir(env["out"])
        assert run_dir.endswith("_calib-default")
        cal = json.load(open(os.path.join(run_dir, "calibration.json"), encoding="utf-8"))
        assert set(cal["per_rank"]) == {"rank_8k", "rank_3k", "rank_1d"}
        assert all(s["games"] == 2 for s in cal["per_rank"].values())
        assert os.path.exists(os.path.join(run_dir, "calibration.md"))
        written = json.loads(pool.read_text(encoding="utf-8"))
        assert sorted(written["ranks"]) == ["rank_1d", "rank_3k", "rank_8k"] and written["tau"] == 1.0


class TestSummarize:
    def test_two_runs_are_summarized_together(self, env, capsys):
        """停止規則の延長（spec §6）: --seed-base をずらした2本目の実行を1本目と合わせて対の差を出す。"""
        CLI.main(_run_args(env, "--arm", "A=default"))
        CLI.main(_run_args(env, "--arm", "A=default", "--seed-base", "1002", "--label", "ext"))
        dirs = [os.path.join(env["out"], d) for d in sorted(os.listdir(env["out"]), key=lambda d: d.endswith("_ext"))]
        capsys.readouterr()
        CLI.main(["summarize", *dirs, "--compare", "A", "A", "--boot", "100"])
        summary = json.load(open(os.path.join(dirs[0], "summary.json"), encoding="utf-8"))
        assert summary["arms"]["A"]["games"] == 4 and summary["compare"][0]["diffs"]["own_top1"]["n"] == 4
        assert "## sources" in capsys.readouterr().out
        with pytest.raises(SystemExit, match="appears in both"):
            CLI.main(["summarize", dirs[0], dirs[0], "--boot", "100"])


class TestReportSgf:
    def test_report_of_a_saved_game_equals_the_game_record(self, env, capsys, monkeypatch):
        CLI.main(_run_args(env, "--arm", "A=default"))
        run_dir = _only_dir(env["out"])
        rec = json.loads(open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8").readline())
        capsys.readouterr()
        replay = FakeEngine(lead=-5.0)  # 読み直しで再解析されたら数字が変わる
        monkeypatch.setattr(CLI, "start_engine", lambda stub: replay)
        CLI.main(["report-sgf", os.path.join(run_dir, rec["sgf"]), "--config", env["config"], "--json"])
        result = json.loads(capsys.readouterr().out)
        assert replay.requests == []  # SGF の KT（解析）をそのまま使った＝再解析なし
        watch = result["reports"]["WATCH"]["all"]
        black, white = (watch["ai"], watch["opp"]) if rec["ai_color"] == "B" else (watch["opp"], watch["ai"])
        assert black["top1"] == rec["own_top1"] and white["top1"] == rec["opp_top1"]
        assert black["n"] == rec["own_n"] and white["n"] == rec["opp_n"]
