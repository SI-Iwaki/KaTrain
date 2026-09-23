# tests/test_selfplay_run.py
"""自己対局ハーネスの実行計画・出力・再開・要約（katrain_debug/selfplay_run.py）。偽エンジン。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §5・§6
"""

import json
import statistics

import pytest

from katrain_debug import selfplay_run as R
from katrain_debug import selfplay_stats as S
from katrain_debug.selfplay_game import resolve_arm
from tests.selfplay_fakes import FakeEngine, make_stub


def _plan(stub, n_seeds=2, max_moves=6, seed_base=1000):
    arm = resolve_arm(stub, "A", "default", [])
    schedule = S.selfplay_schedule(n_seeds, ["rank_3k"], seed_base)
    return R.make_plan("run", [arm], schedule, size=9, komi=7.0, max_moves=max_moves, timeout=5)


def _run(plan, out, stub, engine, retry_aborted=False):
    lines = []
    R.execute_plan(
        plan,
        out,
        stub,
        engine_factory=lambda s: engine,
        watchdog_interval=None,
        retry_aborted=retry_aborted,
        log=lines.append,
    )
    return lines


class DiesInTheSecondGame(FakeEngine):
    """2局目の3本目の問い合わせで落ち、再起動されるまで返事をしない（落ちた KataGo と同じ）。"""

    game_requests = 0

    def on_new_game(self):
        super().on_new_game()
        self.game_requests = 0

    def request_analysis(self, node, callback, error_callback=None, **kwargs):
        self.game_requests += 1
        if self.new_games == 2 and self.restarts == 0 and self.game_requests >= 3:
            self.alive = False
        if self.alive:
            super().request_analysis(node, callback, error_callback, **kwargs)


class TestExecutePlan:
    def test_writes_every_output_file(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        engine = FakeEngine()
        lines = _run(_plan(stub), out, stub, engine)
        recs = out.records()
        assert [(r["arm"], r["seed"], r["ai_color"]) for r in recs] == [("A", 1000, "B"), ("A", 1001, "W")]
        assert all(r["result"] != "aborted" and r["sgf"] for r in recs)
        assert len(lines) == 2 and lines[0].startswith("[1/2] A seed=1000 ai=B vs rank_3k")
        moves = [json.loads(line) for line in open(out.file("moves.jsonl"), encoding="utf-8")]
        assert len(moves) == 12 and {m["seed"] for m in moves} == {1000, 1001}
        assert (tmp_path / "run" / "sgf" / "A_1000_B.sgf").exists()
        assert (tmp_path / "run" / "logs" / "A_1000_B.log").exists()
        assert engine.shutdowns == 1

    def test_sgf_carries_kt_analysis_and_the_result(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        arm = resolve_arm(stub, "A", "default", [])
        schedule = S.selfplay_schedule(1, ["rank_3k"], 1000, resign_range=(10.0, 10.0))  # 相手が投了する局
        plan = R.make_plan("run", [arm], schedule, size=9, komi=7.0, max_moves=60, timeout=5)
        _run(plan, out, stub, FakeEngine(lead=30.0, winrate=0.99))
        rec = out.records()[0]
        assert rec["end_reason"] == "opp_resign" and rec["result"] == "win"
        sgf = (tmp_path / "run" / "sgf" / "A_1000_B.sgf").read_text(encoding="utf-8")
        assert "KT[" in sgf and "PB[AI A (default)]" in sgf and "PW[humanSL:rank_3k]" in sgf
        assert "RE[B+R]" in sgf

    def test_resume_skips_finished_games_and_replays_the_unfinished(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _plan(stub)
        _run(plan, out, stub, FakeEngine())
        games = open(out.file("games.jsonl"), encoding="utf-8").read().splitlines()
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:  # 2局目の途中で落ちた状態にする
            f.write(games[0] + "\n")
        lines = _run(plan, out, stub, FakeEngine())
        assert len(lines) == 1 and "seed=1001" in lines[0]
        assert [r["seed"] for r in out.records()] == [1000, 1001]
        moves = [json.loads(line) for line in open(out.file("moves.jsonl"), encoding="utf-8")]
        assert len(moves) == 12  # 落ちた局の書きかけの行は捨ててから書き直す
        assert _run(plan, out, stub, FakeEngine()) == []

    def test_engine_death_aborts_only_the_game_in_progress(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        engine = DiesInTheSecondGame()
        _run(_plan(stub, n_seeds=4), out, stub, engine)
        results = {r["seed"]: r["result"] for r in out.records()}
        assert results[1001] == "aborted" and "engine died" in out.records()[1]["error"]
        assert all(results[s] != "aborted" for s in (1000, 1002, 1003))
        assert engine.restarts == 1  # 3局目の前に起こした（落ちたエンジンのまま次の局を始めない）

    def test_retry_aborted_replays_only_the_aborted_games(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _plan(stub, n_seeds=4)
        _run(plan, out, stub, DiesInTheSecondGame())
        assert _run(plan, out, stub, FakeEngine()) == []  # 既定の再開は aborted も完了として飛ばす
        lines = _run(plan, out, stub, FakeEngine(), retry_aborted=True)
        assert lines[0].startswith("retry: 1 aborted") and len(lines) == 2 and "seed=1001" in lines[1]
        assert sorted(r["seed"] for r in out.records()) == [1000, 1001, 1002, 1003]
        assert all(r["result"] != "aborted" for r in out.records())
        assert [json.loads(x)["seed"] for x in open(out.file("aborted.jsonl"), encoding="utf-8")] == [1001]
        moves = [json.loads(line) for line in open(out.file("moves.jsonl"), encoding="utf-8")]
        assert len(moves) == 24 and sum(m["seed"] == 1001 for m in moves) == 6

    def test_changed_settings_stop_the_resume(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _plan(stub, n_seeds=4)
        _run(plan, out, stub, FakeEngine())
        first_two = out.records()[:2]
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:  # 2局だけ終えて止まった実行
            f.writelines(json.dumps(r) + "\n" for r in first_two)
        edited = make_stub(tmp_path, **{"ai:default": {"edited": 1}})  # 再開の前に config の節を書き換えた
        engine = FakeEngine()
        with pytest.raises(SystemExit, match="differ from run.json"):
            _run(plan, out, edited, engine)
        assert engine.requests == [] and engine.new_games == 0  # 1局も打たずに止まる
        assert [r["seed"] for r in out.records()] == [1000, 1001]

    def test_resume_drops_torn_last_lines_with_a_warning(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _plan(stub)
        _run(plan, out, stub, FakeEngine())
        games = open(out.file("games.jsonl"), encoding="utf-8").read().splitlines()
        moves = open(out.file("moves.jsonl"), encoding="utf-8").read().splitlines()
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:  # 2局目の行を書いている途中で止まった
            f.write(games[0] + "\n" + games[1][:40])
        with open(out.file("moves.jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(moves) + "\n" + moves[-1][:30])
        lines = _run(plan, out, stub, FakeEngine())
        warnings = [line for line in lines if line.startswith("warning:")]
        assert len(warnings) == 2 and "games.jsonl" in warnings[0] and "moves.jsonl" in warnings[1]
        assert "torn last line" in warnings[0]
        assert [r["seed"] for r in out.records()] == [1000, 1001]  # 書きかけの局は打ち直した
        for name in ("games.jsonl", "moves.jsonl"):
            text = open(out.file(name), encoding="utf-8").read()
            assert text.endswith("\n") and all(json.loads(line) for line in text.splitlines())
        assert len(open(out.file("moves.jsonl"), encoding="utf-8").read().splitlines()) == 12

    def test_summarize_skips_a_torn_last_line_with_a_warning(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        _run(_plan(stub), out, stub, FakeEngine())
        with open(out.file("games.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"arm": "A", "seed": 10')  # 書きかけ（集計は読むだけでファイルは直さない）
        lines = []
        summary, _ = R.summarize_dir(out, n_boot=50, log=lines.append)
        assert summary["arms"]["A"]["games"] == 2
        assert len(lines) == 1 and lines[0].startswith("warning:") and "torn last line" in lines[0]

    def test_a_broken_line_in_the_middle_stops(self, tmp_path):
        out = R.OutputDir(tmp_path / "run")
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"arm": "A", "seed": 1}\n{"arm": \n{"arm": "A", "seed": 2}\n')
        with pytest.raises(SystemExit, match="games.jsonl line 2"):
            out.records()

    def test_rewrites_go_through_a_temp_file(self, tmp_path, monkeypatch):
        """drop_aborted / prune_moves は一時ファイルに書いてから os.replace する（途中で止まっても元のファイルは無傷）。"""
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        _run(_plan(stub, n_seeds=4), out, stub, DiesInTheSecondGame())
        before = {name: open(out.file(name), "rb").read() for name in ("games.jsonl", "moves.jsonl")}

        def interrupted(src, dst):
            raise KeyboardInterrupt

        monkeypatch.setattr(R.os, "replace", interrupted)
        with pytest.raises(KeyboardInterrupt):
            out.drop_aborted()
        with pytest.raises(KeyboardInterrupt):
            out.prune_moves({("A", 1000)})
        monkeypatch.undo()
        assert {name: open(out.file(name), "rb").read() for name in before} == before
        assert sorted(p.name for p in (tmp_path / "run").iterdir() if p.name.endswith(".tmp")) == []
        assert out.drop_aborted() == 1 and [r["seed"] for r in out.records()] == [1000, 1002, 1003]

    def test_plan_order_is_abba(self, tmp_path):
        stub = make_stub(tmp_path, **{"ai:policy": {}})
        arms = [resolve_arm(stub, "A", "default", []), resolve_arm(stub, "B", "policy", [])]
        plan = R.make_plan("run", arms, S.selfplay_schedule(20, ["r"], 1), size=13, komi=7.0)
        assert plan["order"][:2] == [["A", 0], ["A", 1]] and plan["order"][20] == ["B", 10]
        assert plan["target"] == 0.30 and plan["arms"][1]["fingerprint"]


def _cal_record(**overrides):
    """calibrate の games.jsonl の1行（相手の一致率と区間の形だけ）。"""
    block = {"top1": 0.2, "top5": 0.5, "mean_ptloss": 1.8, "n": 30}
    reports = {"WATCH": {n: {"ai": {}, "opp": block} for n, _ in S.REPORT_BINS}}
    rec = {
        "arm": "calib",
        "seed": 0,
        "rank": "rank_3k",
        "ai_color": "B",
        "result": "win",
        "opp_top1": 0.2,
        "opp_n": 30,
        "own_top1": 0.55,
        "opp_mean_ptloss": 1.8,
        "opp_tail": {"n": 30, "ge2": 9, "ge5": 3},
        "n_moves": 80,
        "reports": reports,
    }
    rec.update(overrides)
    return rec


def _run_json(stub, n_seeds=2):
    """CLI が書く run.json と同じ形（計画 + 実行環境）＝再開のときの plan。"""
    return json.loads(json.dumps({**_plan(stub, n_seeds), **R.run_meta(stub)}, default=str))


class TestMeasurementBaseline:
    """再開と複数の実行の要約は、エンジン設定とコードの版が run.json と違えば止まる（--allow-mixed で続行）。"""

    def test_resume_with_the_same_baseline_continues(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _run_json(stub)
        _run(plan, out, stub, FakeEngine())
        assert _run(plan, out, make_stub(tmp_path), FakeEngine()) == []

    @pytest.mark.parametrize(
        "key, change",
        [
            ("engine.max_visits", lambda p: p["engine"].update(max_visits=200)),
            ("engine.model", lambda p: p["engine"].update(model="other.bin.gz")),
            ("engine.humanlike_model", lambda p: p["engine"].update(humanlike_model="h.bin.gz")),
            ("engine.wide_root_noise", lambda p: p["engine"].update(wide_root_noise=0.0)),
            ("git.head", lambda p: p["git"].update(head="0" * 40)),
            ("ai_file", lambda p: p.update(ai_file="D:/elsewhere/katrain/core/ai.py")),
        ],
    )
    def test_resume_refuses_a_changed_baseline(self, tmp_path, key, change):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _run_json(stub, n_seeds=4)
        change(plan)  # 記録した run.json と今の config・コードがずれた状態
        engine = FakeEngine()
        with pytest.raises(SystemExit, match=f"measurement baseline differs.*{key.replace('.', '[.]')}"):
            _run(plan, out, stub, engine)
        assert engine.requests == [] and engine.new_games == 0 and out.records() == []

    def test_allow_mixed_continues_with_a_warning(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _run_json(stub)
        plan["engine"]["max_time"] = 30.0
        lines = []
        R.execute_plan(
            plan,
            out,
            stub,
            engine_factory=lambda s: FakeEngine(),
            watchdog_interval=None,
            allow_mixed=True,
            log=lines.append,
        )
        assert lines[0].startswith("WARN measurement baseline differs") and "engine.max_time: 30.0 vs 8.0" in lines[0]
        assert len(out.records()) == 2

    def test_numbers_are_compared_by_value(self):
        meta = {"engine": {"max_visits": 2500, "max_time": 8}, "git": {"head": "a"}, "ai_file": "katrain/core/ai.py"}
        same = {
            "engine": {"max_visits": 2500.0, "max_time": 8.0},
            "git": {"head": "a"},
            "ai_file": "katrain/core/ai.py",
        }
        assert R.baseline_differences(meta, same) == []

    def test_ai_file_recorded_as_an_absolute_path_matches_the_repo_relative_one(self):
        old = {"engine": {}, "git": {}, "ai_file": R.os.path.join(R.REPO_ROOT, "katrain", "core", "ai.py")}
        new = {"engine": {}, "git": {}, "ai_file": "katrain/core/ai.py"}
        assert R.baseline_differences(old, new) == []

    def test_summarize_refuses_runs_with_different_baselines(self, tmp_path):
        stub = make_stub(tmp_path)
        outs = []
        for label, seed_base in (("a", 1000), ("b", 1002)):
            out = R.OutputDir(tmp_path / label)
            plan = _plan(stub, seed_base=seed_base)
            _run(plan, out, stub, FakeEngine())
            meta = json.loads(json.dumps(R.run_meta(stub)))
            if label == "b":
                meta["engine"]["model"] = "other.bin.gz"  # 別のモデルで打った延長
            out.write_json("run.json", {**plan, **meta})
            outs.append(out)
        with pytest.raises(SystemExit, match="measurement baseline differs.*engine[.]model"):
            R.load_records(outs)
        lines = []
        assert len(R.load_records(outs, allow_mixed=True, log=lines.append)) == 4
        assert len(lines) == 1 and lines[0].startswith("WARN measurement baseline differs")


class TestGitInfo:
    def test_untracked_files_do_not_make_the_tree_dirty(self, tmp_path):
        def git(*args):
            R.subprocess.run(
                ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                check=True,
                capture_output=True,
            )

        git("init", "-q")
        (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-q", "-m", "init")
        (tmp_path / "untracked.md").write_text("x\n", encoding="utf-8")
        info = R.git_info(str(tmp_path))
        assert len(info["head"]) == 40 and info["dirty"] is False
        (tmp_path / "a.txt").write_text("b\n", encoding="utf-8")
        assert R.git_info(str(tmp_path))["dirty"] is True


class TestProvenancePaths:
    """記録に残すパスはリポジトリ相対（コミットする成果物に作業ツリーの絶対パスを埋め込まない）。"""

    def test_run_meta_records_ai_file_relative_to_the_repo(self, tmp_path):
        assert R.run_meta(make_stub(tmp_path))["ai_file"] == "katrain/core/ai.py"

    def test_calibration_outputs_record_the_run_dir_relative_to_the_repo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "REPO_ROOT", str(tmp_path))
        out = R.OutputDir(tmp_path / "experiments" / "selfplay" / "20260924_0202_calib13")
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(_cal_record()) + "\n")
        plan = {"size": 13, "arms": [{"name": "calib", "strategy": "enigma13plus"}], "opponent": {"tau": 1.0}}
        cal = R.calibration_result(out, plan)
        assert cal["run_dir"] == "experiments/selfplay/20260924_0202_calib13"
        assert "実行: `experiments/selfplay/20260924_0202_calib13`" in R.format_calibration_md(cal)

    def test_pool_file_source_run_is_relative_to_the_repo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "REPO_ROOT", str(tmp_path))
        out = R.OutputDir(tmp_path / "experiments" / "cal")
        recs = [
            _cal_record(rank=rank, seed=i, opp_top1=0.1 + 0.05 * i)
            for i, rank in enumerate(("rank_8k", "rank_3k", "rank_1d"))
        ]
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in recs)
        plan = {"size": 13, "arms": [{"name": "calib", "strategy": "enigma13plus"}], "opponent": {"tau": 1.0}}
        assert R.pool_file_content(R.calibration_result(out, plan))["source_run"] == "experiments/cal"

    def test_summary_sources_are_relative_to_the_repo(self, tmp_path, monkeypatch):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        _run(_plan(stub), out, stub, FakeEngine())
        monkeypatch.setattr(R, "REPO_ROOT", str(tmp_path))
        summary, _ = R.summarize_dir(out, n_boot=50)
        assert summary["sources"] == ["run"]


class TestSummaries:
    def test_summary_files_are_ascii(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        _run(_plan(stub), out, stub, FakeEngine())
        summary, text = R.summarize_dir(out, n_boot=200, compare=("A", "A"))
        assert summary["arms"]["A"]["games"] == 2
        assert summary["compare"][0]["diffs"]["own_top1"]["n"] == 2
        written = (tmp_path / "run" / "summary.txt").read_text(encoding="ascii")  # ASCII 以外があれば例外
        assert written == text and "paired diff A - A" in text
        verdicts = {
            line.split()[0]: line.rsplit("verdict(+-3pt)=", 1)[1] for line in text.splitlines() if "verdict(" in line
        }
        assert verdicts["own_top1"] == "within" and verdicts["own_minus_opp"] == "within"  # ±3pt は一致率の差だけ
        assert verdicts["flip_moves"] == verdicts["own_mean_ptloss"] == verdicts["ge6"] == verdicts["win"] == "-"
        assert json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))["arms"]["A"]

    def test_integrity_warning_only_when_a_counter_is_non_zero(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        _run(_plan(stub), out, stub, FakeEngine())
        summary, text = R.summarize_dir(out, n_boot=100)
        assert summary["arms"]["A"]["integrity"] == {
            "fallbacks": 0,
            "humansl_errors": 0,
            "hp_audit_errors": 0,
            "shadow_errors": 0,
        }
        assert "WARN integrity:" not in text
        recs = out.records()
        recs[1]["opponent_stats"]["fallbacks"] = 2
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in recs)
        summary, text = R.summarize_dir(out, n_boot=100)
        assert summary["arms"]["A"]["integrity"]["fallbacks"] == 2
        assert [line for line in text.splitlines() if "WARN" in line] == ["WARN integrity: arm A: fallbacks=2"]
        assert "WARN integrity: arm A: fallbacks=2" in (tmp_path / "run" / "summary.txt").read_text(encoding="ascii")

    def test_resign_pool_reads_report_jsons(self, tmp_path):
        for i, (ai, n, fs) in enumerate([("B", 59, 28.9), ("W", 31, -2.7)]):
            summary = {"ai": ai, "n_moves": n, "final_score": fs}
            (tmp_path / f"report_game_{i}.json").write_text(json.dumps({"summary": summary}), encoding="utf-8")
        assert R.load_resign_pool(13, str(tmp_path)) == [28.9]
        assert R.load_resign_lengths(13, str(tmp_path)) == [59, 31]

    def test_resign_lengths_are_the_real_game_lengths(self):
        lens = R.load_resign_lengths(13)  # 実戦 13路 18局（recon/report_game_*.json の summary.n_moves）
        assert len(lens) == 18 and statistics.median(lens) == 78.5 and (min(lens), max(lens)) == (31, 128)
        assert R.load_resign_lengths(9) == [round(n * 81 / 169) for n in lens]
        assert R.load_resign_lengths(19) == [round(n * 361 / 169) for n in lens]

    def test_repo_relpath(self, tmp_path):
        inside = R.os.path.join(R.REPO_ROOT, "experiments", "selfplay", "20260924_0202_calib13")
        assert R.repo_relpath(inside) == "experiments/selfplay/20260924_0202_calib13"
        assert R.repo_relpath(R.RECON_DIR) == "docs/superpowers/specs/calibration-data/selfplay/recon"
        outside = str(tmp_path / "run")  # リポジトリの外は絶対パスのまま（スラッシュ区切り）
        assert R.repo_relpath(outside) == R.os.path.abspath(outside).replace("\\", "/")
        assert R.repo_relpath(None) is None

    def test_resign_model_is_a_game_condition(self):
        def plan(resign):
            return {"size": 13, "komi": 7.0, "opponent": {"kind": "humansl"}, "resign": resign}

        length = plan({"model": "length", "no_resign": False, "range": None})
        lead = plan({"model": "lead", "no_resign": False, "range": None})
        old = plan({"no_resign": False, "range": None})  # 長さのモデルより前の run.json＝lead
        assert R.plan_conditions(length) != R.plan_conditions(lead)
        assert R.plan_conditions(old) == R.plan_conditions(lead)
        assert R.plan_conditions(plan({"no_resign": True, "range": None}))["resign"]["model"] == "none"

    def test_calibration_markdown_and_pool_file(self, tmp_path):
        out = R.OutputDir(tmp_path / "cal")
        recs = []
        for rank, rates in (("rank_8k", [0.1, 0.12]), ("rank_3k", [0.2, 0.26]), ("rank_1d", [0.22, 0.3])):
            for i, rate in enumerate(rates):
                block = {"top1": rate, "top5": 0.5, "mean_ptloss": 1.8, "n": 30}
                reports = {"WATCH": {n: {"ai": {}, "opp": block} for n, _ in S.REPORT_BINS}}
                recs.append(
                    {
                        "arm": "calib",
                        "seed": i,
                        "rank": rank,
                        "ai_color": "B",
                        "result": "win",
                        "opp_top1": rate,
                        "opp_n": 30,
                        "own_top1": 0.55,
                        "opp_mean_ptloss": 1.8,
                        "opp_tail": {"n": 30, "ge2": 9, "ge5": 3},
                        "n_moves": 80,
                        "reports": reports,
                    }
                )
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in recs)
        plan = {
            "size": 13,
            "arms": [{"strategy": "enigma13plus"}],
            "opponent": {"tau": 1.0},
            "resign": {"model": "length"},
        }
        cal = R.calibration_result(out, plan)
        assert cal["best"]["ranks"] == ["rank_8k", "rank_3k", "rank_1d"]
        assert abs(cal["harness_drift_ai"] - (0.55 - 0.533)) < 1e-9
        md = R.format_calibration_md(cal)
        assert "| rank_3k | 2 |" in md and "実戦（目標）" in md and "投了モデル: length" in md
        pool = R.pool_file_content(cal)
        assert pool["ranks"] == ["rank_8k", "rank_3k", "rank_1d"] and pool["tau"] == 1.0
        assert pool["resign_model"] == "length"

    def test_calibration_result_and_markdown_carry_integrity_totals(self, tmp_path):
        """review finding on Task 6fix (outside its file list): calibrate must surface integrity problems too."""
        out = R.OutputDir(tmp_path / "cal")
        plan = {"size": 13, "arms": [{"name": "calib", "strategy": "enigma13plus"}], "opponent": {"tau": 1.0}}
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(_cal_record()) + "\n")
        cal = R.calibration_result(out, plan)
        assert cal["integrity"] == {
            "fallbacks": 0,
            "humansl_errors": 0,
            "hp_audit_errors": 0,
            "shadow_errors": 0,
        }
        assert "WARN integrity" not in R.format_calibration_md(cal)

        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(_cal_record(opponent_stats={"humansl_errors": 2})) + "\n")
        cal = R.calibration_result(out, plan)
        assert cal["integrity"]["humansl_errors"] == 2
        assert "WARN integrity: arm calib: humansl_errors=2" in R.format_calibration_md(cal)
