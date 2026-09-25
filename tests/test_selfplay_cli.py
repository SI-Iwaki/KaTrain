# tests/test_selfplay_cli.py
"""自己対局ハーネスの CLI（python -m katrain_debug.selfplay）。KataGo の代わりに偽エンジンを差し込む。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §8
"""

import json
import os

import pytest

from katrain_debug import selfplay as CLI
from tests.selfplay_fakes import FakeEngine, make_stub

RECON_9_LENGTHS = (31, 48, 99)  # テストの 9路の実戦の手数（本物の recon_9/ は計測の準備で作る）


@pytest.fixture
def env(tmp_path, monkeypatch):
    make_stub(tmp_path, **{"ai:policy": {}})  # tmp_path/config.json を書く
    monkeypatch.setattr(CLI, "start_engine", lambda stub: FakeEngine())
    monkeypatch.setattr(CLI, "katago_processes", lambda: [])
    recon9 = tmp_path / "recon_9"
    recon9.mkdir()
    for i, n in enumerate(RECON_9_LENGTHS):
        summary = {"ai": "B", "n_moves": n, "final_score": 5.0, "board_size": 9}
        (recon9 / f"report_game_{i}.json").write_text(json.dumps({"summary": summary}), encoding="utf-8")
    monkeypatch.setitem(CLI.R.RECON_DIRS, 9, str(recon9))
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
        assert "settings_source" not in out  # ユーザー config の節で走るアームは何も言わない

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

    def test_override_equal_to_the_code_default_is_a_null_experiment(self, env, monkeypatch):
        engine_started = []
        monkeypatch.setattr(CLI, "start_engine", lambda stub: engine_started.append(1) or FakeEngine())
        with pytest.raises(SystemExit, match="null experiment"):  # mimic13_probe_extra の既定値は 4
            CLI.main(_run_args(env, "--arm", "A=mimic13", "--arm", "B=mimic13:mimic13_probe_extra=4"))
        assert engine_started == []

    def test_code_default_settings_are_announced_at_plan_time(self, env, capsys):
        cfg = json.loads(open(env["config"], encoding="utf-8").read())
        del cfg["ai"]["ai:default"]  # 戦略の節がユーザー config に無い＝コードの既定値で走る
        open(env["config"], "w", encoding="utf-8").write(json.dumps(cfg))
        CLI.main(_run_args(env, "--arm", "A=default"))
        out = capsys.readouterr().out
        assert "arm A (default): settings_source = code defaults (mode missing from the user config)" in out

    def test_typo_in_an_override_is_refused(self, env):
        with pytest.raises(SystemExit, match="unknown setting keys"):
            CLI.main(_run_args(env, "--arm", "A=enigma13plus:enigma13plus_max_los=2.0"))

    def test_missing_ranks_is_refused(self, env, monkeypatch):
        monkeypatch.setattr(CLI.R, "default_pool_path", lambda size: os.path.join(env["out"], "missing.json"))
        args = [a for a in _run_args(env, "--arm", "A=default") if a not in ("--ranks", "rank_3k")]
        with pytest.raises(SystemExit, match="no opponent ranks"):
            CLI.main(args)

    def test_ranks_are_stripped(self, env):
        args = [a if a != "rank_3k" else " rank_3k , rank_1d " for a in _run_args(env, "--arm", "A=default")]
        CLI.main(args)
        plan = json.load(open(os.path.join(_only_dir(env["out"]), "run.json"), encoding="utf-8"))
        assert plan["opponent"]["ranks"] == ["rank_3k", "rank_1d"]

    @pytest.mark.parametrize(
        "extra",
        [
            ["--ranks", "rank_3k,rank3k"],  # --ranks は後の指定が勝つ
            ["--ranks", "rank_3k,1d"],
            ["--hp-audit", "9d"],
        ],
    )
    def test_invalid_humansl_profiles_are_refused_before_the_engine_starts(self, env, monkeypatch, extra):
        started = []
        monkeypatch.setattr(CLI, "start_engine", lambda stub: started.append(1) or FakeEngine())
        with pytest.raises(SystemExit, match="invalid humanSL profile"):
            CLI.main(_run_args(env, "--arm", "A=default", *extra))
        assert started == [] and not os.path.exists(env["out"])

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


def _resign_args(env, *extra):
    return [a for a in _run_args(env, "--arm", "A=default") if a != "--no-resign"] + list(extra)


def _run_files(run_dir):
    plan = json.load(open(os.path.join(run_dir, "run.json"), encoding="utf-8"))
    recs = [json.loads(x) for x in open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8")]
    return plan, recs


class TestResignModel:
    def test_length_model_is_the_default(self, env):
        CLI.main(_resign_args(env))
        plan, recs = _run_files(_only_dir(env["out"]))
        lens = CLI.R.load_resign_lengths(9)  # 9路の実戦の手数（recon_9・縮めない）
        assert lens == list(RECON_9_LENGTHS)
        assert plan["resign"]["model"] == "length" and plan["resign"]["lengths"] == lens
        assert all(s["resign_len"] in lens and s["resign_lead"] is None for s in plan["schedule"])
        assert [(r["resign_model"], r["resign_len"]) for r in recs] == [
            ("length", s["resign_len"]) for s in plan["schedule"]
        ]

    def test_lead_model_is_selectable(self, env):
        CLI.main(_resign_args(env, "--resign-model", "lead", "--resign-lead", "8:40"))
        plan, recs = _run_files(_only_dir(env["out"]))
        assert plan["resign"]["model"] == "lead" and plan["resign"]["range"] == [8.0, 40.0]
        assert all(8 <= s["resign_lead"] <= 40 and s["resign_len"] is None for s in plan["schedule"])
        assert all(r["resign_model"] == "lead" and r["resign_len"] is None for r in recs)

    def test_lead_model_on_9x9_needs_a_range(self, env):
        with pytest.raises(SystemExit, match="needs --resign-lead"):  # spec §16.2 手順5: 9路の実戦のリードの標本は無い
            CLI.main(_resign_args(env, "--resign-model", "lead"))

    def test_resign_lead_applies_only_to_the_lead_model(self, env):
        with pytest.raises(SystemExit, match="--resign-model lead"):
            CLI.main(_resign_args(env, "--resign-lead", "8:40"))

    def test_no_resign_records_no_model(self, env):
        CLI.main(_run_args(env, "--arm", "A=default"))
        plan, recs = _run_files(_only_dir(env["out"]))
        assert plan["resign"]["model"] == "none" and all(r["resign_model"] == "none" for r in recs)

    def test_runs_with_different_resign_models_are_not_merged(self, env):
        CLI.main(_resign_args(env))
        CLI.main(
            _resign_args(
                env, "--resign-model", "lead", "--resign-lead", "8:40", "--seed-base", "1002", "--label", "ext"
            )
        )
        dirs = [os.path.join(env["out"], d) for d in sorted(os.listdir(env["out"]), key=lambda d: d.endswith("_ext"))]
        with pytest.raises(SystemExit, match="game conditions differ"):
            CLI.main(["summarize", *dirs, "--boot", "100"])


def _calibrate_args(env, pool=None, ranks="rank_8k,rank_3k,rank_1d", games="2"):
    args = [
        "calibrate",
        "--size",
        "13",
        "--strategy",
        "default",
        "--ranks",
        ranks,
        "--games",
        games,
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
    ]
    if pool is not None:
        args += ["--write-pool", str(pool)]
    return args


class TestCalibrate:
    def test_writes_calibration_files_and_the_pool(self, env, capsys):
        pool = env["tmp"] / "opponent_pool_13.json"
        CLI.main(_calibrate_args(env, pool=pool))
        run_dir = _only_dir(env["out"])
        assert run_dir.endswith("_calib-default")
        cal = json.load(open(os.path.join(run_dir, "calibration.json"), encoding="utf-8"))
        assert set(cal["per_rank"]) == {"rank_8k", "rank_3k", "rank_1d"}
        assert all(s["games"] == 2 for s in cal["per_rank"].values())
        assert cal["integrity"] == {"fallbacks": 0, "humansl_errors": 0, "hp_audit_errors": 0, "shadow_errors": 0}
        assert os.path.exists(os.path.join(run_dir, "calibration.md"))
        written = json.loads(pool.read_text(encoding="utf-8"))
        assert sorted(written["ranks"]) == ["rank_1d", "rank_3k", "rank_8k"] and written["tau"] == 1.0
        assert not (env["tmp"] / "opponent_pool_13.json.suspect").exists()
        out = capsys.readouterr().out
        assert "WARN integrity" not in out  # clean run: no WARN anywhere

    def test_calibrate_surfaces_humansl_errors(self, env, capsys, monkeypatch):
        """review finding on Task 6fix: calibrate must warn about integrity problems too, not just `run`."""
        monkeypatch.setattr(CLI, "start_engine", lambda stub: FakeEngine(hp_errors={"rank_3k": "boom"}))
        CLI.main(_calibrate_args(env, ranks="rank_3k", games="1"))
        run_dir = _only_dir(env["out"])
        cal = json.load(open(os.path.join(run_dir, "calibration.json"), encoding="utf-8"))
        assert cal["integrity"]["humansl_errors"] > 0
        md = open(os.path.join(run_dir, "calibration.md"), encoding="utf-8").read()
        assert "WARN integrity:" in md
        out = capsys.readouterr().out
        assert "WARN integrity:" in out

    def test_calibrate_writes_a_suspect_pool_when_integrity_counters_are_non_zero(self, env, capsys, monkeypatch):
        monkeypatch.setattr(CLI, "start_engine", lambda stub: FakeEngine(hp_errors={"rank_3k": "boom"}))
        pool = env["tmp"] / "opponent_pool_13.json"
        pool.write_text('{"ranks": ["rank_1k"]}', encoding="utf-8")  # コミット済みの既定のプール
        CLI.main(_calibrate_args(env, pool=pool))
        assert json.loads(pool.read_text(encoding="utf-8")) == {"ranks": ["rank_1k"]}  # 上書きしない
        suspect = env["tmp"] / "opponent_pool_13.json.suspect"
        assert sorted(json.loads(suspect.read_text(encoding="utf-8"))["ranks"]) == ["rank_1d", "rank_3k", "rank_8k"]
        out = capsys.readouterr().out
        assert "WARN integrity: pool NOT written" in out and "opponent_pool_13.json.suspect" in out

    def test_force_pool_overwrites_despite_integrity_counters(self, env, capsys, monkeypatch):
        monkeypatch.setattr(CLI, "start_engine", lambda stub: FakeEngine(hp_errors={"rank_3k": "boom"}))
        pool = env["tmp"] / "opponent_pool_13.json"
        CLI.main(_calibrate_args(env, pool=pool) + ["--force-pool"])
        assert pool.exists() and not (env["tmp"] / "opponent_pool_13.json.suspect").exists()
        assert (
            "WARN integrity: pool written from games with integrity problems (--force-pool)" in capsys.readouterr().out
        )

    def test_invalid_calibrate_ranks_are_refused(self, env):
        with pytest.raises(SystemExit, match="invalid humanSL profile"):
            CLI.main(_calibrate_args(env, ranks="rank_8k, 3k"))


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


def _edit_run_json(run_dir, change):
    path = os.path.join(run_dir, "run.json")
    plan = json.load(open(path, encoding="utf-8"))
    change(plan)
    open(path, "w", encoding="utf-8").write(json.dumps(plan))


class TestMeasurementBaseline:
    def test_resume_refuses_a_changed_engine_unless_allow_mixed(self, env, capsys):
        CLI.main(_run_args(env, "--arm", "A=default"))
        run_dir = _only_dir(env["out"])
        # 止めた後に config のモデルを替えた（run.json の記録と今の config がずれる）
        _edit_run_json(run_dir, lambda p: p["engine"].update(model="older.bin.gz"))
        with pytest.raises(SystemExit, match="engine[.]model: 'older.bin.gz' vs None"):
            CLI.main(["run", "--resume", run_dir, "--boot", "100"])
        capsys.readouterr()
        CLI.main(["run", "--resume", run_dir, "--boot", "100", "--allow-mixed"])
        assert "WARN measurement baseline differs" in capsys.readouterr().out

    def test_summarize_refuses_mixed_code_versions_unless_allow_mixed(self, env, capsys):
        CLI.main(_run_args(env, "--arm", "A=default"))
        CLI.main(_run_args(env, "--arm", "A=default", "--seed-base", "1002", "--label", "ext"))
        dirs = [os.path.join(env["out"], d) for d in sorted(os.listdir(env["out"]), key=lambda d: d.endswith("_ext"))]
        _edit_run_json(dirs[1], lambda p: p["git"].update(head="0" * 40))  # 別のコミットで打った延長
        with pytest.raises(SystemExit, match="git[.]head"):
            CLI.main(["summarize", *dirs, "--boot", "100"])
        capsys.readouterr()
        CLI.main(["summarize", *dirs, "--boot", "100", "--allow-mixed"])
        out = capsys.readouterr().out
        assert "WARN measurement baseline differs" in out and "git.head" in out

    def test_run_json_paths_are_relative_to_the_repo(self, env):
        args = _resign_args(env)
        args[args.index("--size") + 1] = "13"  # 13路の投了モデルは recon/（リポジトリの中）
        CLI.main(args)
        plan, _ = _run_files(_only_dir(env["out"]))
        assert plan["ai_file"] == "katrain/core/ai.py"
        assert plan["resign"]["source"] == "docs/superpowers/specs/calibration-data/selfplay/recon"


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
