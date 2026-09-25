# tests/test_selfplay_window.py
"""序盤の窓の指標（docs/superpowers/specs/calibration-data/selfplay/window_stats.py）。合成した moves.jsonl で確かめる。

設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md §16.2 手順7
"""

import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "docs", "superpowers", "specs", "calibration-data", "selfplay", "window_stats.py")
_spec = importlib.util.spec_from_file_location("window_stats", SCRIPT)
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)


def _move(arm, seed, depth, is_ai, match=True, loss=0.0, **kw):
    row = {
        "arm": arm,
        "seed": seed,
        "depth": depth,
        "is_ai": is_ai,
        "match": match,
        "points_lost": loss,
        "trailing_pass": False,
        "lead_after_ai": float(depth),
        "wr_before_ai": 0.8,
        "wr_after_ai": 0.8,
    }
    row.update(kw)
    return row


def _game(arm, seed, n_moves=8, ai_first=True, result="win", overrides=None):
    """1局の moves（AI が黒なら奇数手）。overrides: {手数: {列: 値}}。"""
    rows = []
    for d in range(1, n_moves + 1):
        is_ai = (d % 2 == 1) == ai_first
        rows.append(_move(arm, seed, d, is_ai, **(overrides or {}).get(d, {})))
    rec = {"arm": arm, "seed": seed, "result": result, "opponent_stats": {}}
    return rec, rows


def _write_run(path, games, size=9, arms=None, opponent=None, resign=None):
    """run.json は selfplay_run.load_records が読める最小の形（"arms"・"opponent"・"resign" を持つ）にする
    （final-fix finding 1: window_stats.load_runs が複数 DIR で load_records を呼ぶため）。"""
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "run.json"), "w", encoding="utf-8") as f:
        json.dump({"size": size, "arms": arms or [], "opponent": opponent or {}, "resign": resign or {}}, f)
    with open(os.path.join(path, "games.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(rec) + "\n" for rec, _ in games)
    with open(os.path.join(path, "moves.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(row) + "\n" for _, rows in games for row in rows)
    return str(path)


class TestWindowSplit:
    def test_rates_losses_and_lead_on_both_sides_of_the_window(self, tmp_path):
        game = _game(
            "open",
            1000,
            overrides={
                1: {"match": False, "loss": 2.5},
                2: {"match": False, "loss": 6.5},
                5: {"match": False, "loss": 0.4},
            },
        )
        run = _write_run(tmp_path / "r", [game])
        s = W.window_stats([run], window=4)["arms"]["open"]
        assert s["games"] == 1
        assert s["own_in"]["n"] == 2 and s["own_in"]["rate_mean"] == 0.5 and s["own_in"]["ge2_per_game"] == 1
        assert s["opp_in"]["rate_pooled"] == 0.5 and s["opp_in"]["ge6_per_game"] == 1
        assert s["own_out"]["n"] == 2 and s["own_out"]["rate_mean"] == 0.5
        assert s["own_out"]["loss_per_move"] == pytest.approx(0.2)
        assert s["lead_at_w"]["median"] == 4.0  # 手数 <= W の最後の行（手数 4）の lead_after_ai

    def test_default_window_follows_the_board_size(self, tmp_path):
        run9 = _write_run(tmp_path / "r9", [_game("a", 1000)], size=9)
        run13 = _write_run(tmp_path / "r13", [_game("a", 1000)], size=13)
        assert W.window_stats([run9])["window"] == 12 and W.window_stats([run13])["window"] == 30
        with pytest.raises(SystemExit, match="no default window"):
            W.window_stats([_write_run(tmp_path / "r19", [_game("a", 1000)], size=19)])

    def test_aborted_games_are_excluded(self, tmp_path):
        run = _write_run(tmp_path / "r", [_game("a", 1000), _game("a", 1001, result="aborted")])
        assert W.window_stats([run], window=4)["arms"]["a"]["games"] == 1

    def test_report_definition_drops_moves_without_points_lost_and_trailing_passes(self, tmp_path):
        game = _game("a", 1000, overrides={1: {"points_lost": None}, 7: {"trailing_pass": True, "match": False}})
        s = W.window_stats([_write_run(tmp_path / "r", [game])], window=4)["arms"]["a"]
        assert s["own_in"]["n"] == 1 and s["own_out"]["n"] == 1 and s["own_out"]["rate_mean"] == 1.0

    def test_flips_u_and_paid_after_the_window(self, tmp_path):
        game = _game(
            "a",
            1000,
            overrides={
                3: {"wr_before_ai": 0.6, "wr_after_ai": 0.4},
                5: {"decision_u": 1.0, "decision_kind": "paid"},
                7: {"decision_u": 0.5, "decision_kind": "free", "wr_before_ai": 0.55, "wr_after_ai": 0.45},
            },
        )
        s = W.window_stats([_write_run(tmp_path / "r", [game])], window=4)["arms"]["a"]
        assert s["flip_in_per_game"] == 1 and s["flip_out_per_game"] == 1
        assert s["u_after_mean"] == 0.75 and s["paid_after_per_game"] == 1

    def test_open_window_is_checked_against_decision_open(self, tmp_path):
        game = _game(
            "open",
            1000,
            overrides={1: {"decision_open": "played"}, 3: {"decision_open": "gate"}, 5: {"decision_open": "played"}},
        )
        s = W.window_stats([_write_run(tmp_path / "r", [game])], window=2)["arms"]["open"]
        assert s["open"] == {"played": 2, "gate": 1} and s["open_outside"] == 2 and s["open_missing_inside"] == 0
        assert s["games_with_open"] == 1 and s["games"] == 1
        plain = W.window_stats([_write_run(tmp_path / "p", [_game("layers", 1000)])], window=2)["arms"]["layers"]
        assert plain["open"] == {} and plain["open_missing_inside"] == 0  # 韜晦の窓の無いアームは数えない
        assert plain["games_with_open"] == 0

    def test_open_arm_counts_missing_inside_even_when_a_game_never_engaged(self, tmp_path):
        """final-fix finding 2: 窓の外し（decision_open）が一度も出ない局でも、そのアームが open なら窓の中の AI の手は
        すべて missing_inside に数える（レビューの再現ケース: 局1は発動・局2は decision_open が無い → missing_inside > 0・
        games_with_open は 1/2）。"""
        engaged = _game("open", 1000, overrides={1: {"decision_open": "played"}})
        silent = _game("open", 1001)  # decision_open が一つも無い局（研究外しが一度も発動しなかった）
        s = W.window_stats([_write_run(tmp_path / "r", [engaged, silent])], window=2)["arms"]["open"]
        assert s["games"] == 2 and s["games_with_open"] == 1
        assert s["open_missing_inside"] == 1  # silent 局の depth 1 の AI の手（窓の中）が missing

    def test_run_json_effective_settings_mark_the_arm_open_even_if_no_game_ever_engaged(self, tmp_path):
        """run.json の effective_settings に `*_open_moves` > 0 があれば、moves.jsonl に decision_open が一度も出ない
        （フォールバックでは判定できない）ケースでも open 扱いにする（finding 2: run.json を優先する）。"""
        game = _game("open", 1000)  # decision_open が一つも無い
        arms = [{"name": "open", "effective_settings": {"veil9_open_moves": 12}}]
        run = _write_run(tmp_path / "r", [game], arms=arms)
        s = W.window_stats([run], window=2)["arms"]["open"]
        assert s["open_missing_inside"] == 1  # window=2 内の AI の手（depth 1）が missing
        assert s["games_with_open"] == 0 and s["games"] == 1

    def test_book_exit_comes_from_the_opponent_stats(self, tmp_path):
        rec, rows = _game("a", 1000)
        rec["opponent_stats"] = {"book_exit_depth": 7, "book_exit_reason": "ai_loss"}
        rec2, rows2 = _game("a", 1001)
        rec2["opponent_stats"] = {"book_exit_depth": 24, "book_exit_reason": "limit"}
        s = W.window_stats([_write_run(tmp_path / "r", [(rec, rows), (rec2, rows2)])], window=4)["arms"]["a"]
        assert s["book_exit"]["games"] == 2 and s["book_exit"]["median"] == 15.5 and s["book_exit"]["min"] == 7
        assert s["book_exit"]["reasons"] == {"ai_loss": 1, "limit": 1}
        # game "a"/1000 の depth 7 は既定 (match True, loss 0.0) の AI の手＝噪音駆動の外し（最善手のまま外れた）
        assert s["book_exit"]["noise"] == {"n": 1, "on_best_move": 1, "loss_median": 0.0, "loss_mean": 0.0}

    def test_book_exit_noise_reports_whether_the_exit_move_was_the_best_move(self, tmp_path):
        """final-fix finding 3: ai_loss で外れた局は、外れた手（moves.jsonl の depth == book_exit_depth の AI の手）が
        最善手だったか（match True＝噪音駆動）と、その手の points_lost の中央値・平均を報告する。"""
        rec1, rows1 = _game("a", 1000, overrides={5: {"match": True, "loss": 0.35}})
        rec1["opponent_stats"] = {"book_exit_depth": 5, "book_exit_reason": "ai_loss"}
        rec2, rows2 = _game("a", 1001, overrides={5: {"match": False, "loss": 1.2}})
        rec2["opponent_stats"] = {"book_exit_depth": 5, "book_exit_reason": "ai_loss"}
        s = W.window_stats([_write_run(tmp_path / "r", [(rec1, rows1), (rec2, rows2)])], window=4)["arms"]["a"]
        assert s["book_exit"]["noise"]["n"] == 2 and s["book_exit"]["noise"]["on_best_move"] == 1
        assert s["book_exit"]["noise"]["loss_median"] == pytest.approx(0.775)
        assert s["book_exit"]["noise"]["loss_mean"] == pytest.approx(0.775)
        text = W.format_text(W.window_stats([_write_run(tmp_path / "t", [(rec1, rows1), (rec2, rows2)])], window=4))
        assert "noise 1/2" in text

    def test_text_table_includes_opponent_loss_and_book_played(self, tmp_path):
        """final-fix finding 7: 表に相手の損失（窓の中・後）と定跡を知る相手の book_played を足す。"""
        rec, rows = _game("a", 1000, overrides={2: {"loss": 1.5}})
        rec["opponent_stats"] = {"book_played": 3, "book_exit_depth": 4, "book_exit_reason": "limit"}
        result = W.window_stats([_write_run(tmp_path / "r", [(rec, rows)])], window=4)
        s = result["arms"]["a"]
        assert s["opp_in"]["loss_per_move"] == pytest.approx(0.75)
        assert s["book_played_per_game"] == 3
        text = W.format_text(result)
        assert "loss p in/out" in text and "played/game=3.0" in text


class TestPairsAndRuns:
    def test_paired_diff_uses_the_same_seeds(self, tmp_path):
        games = [
            _game("open", 1000, overrides={1: {"match": False}}),
            _game("layers", 1000),
            _game("open", 1001, overrides={3: {"match": False}}),
            _game("layers", 1001),
            _game("layers", 1002),  # 対の無い seed は数えない
        ]
        result = W.window_stats([_write_run(tmp_path / "r", games)], window=4, compare=("open", "layers"))
        d = result["compare"][0]["diffs"]
        assert d["own_in"]["n"] == 2 and d["own_in"]["mean"] == -0.5
        assert d["own_out"]["mean"] == 0.0 and d["lead_at_w"]["mean"] == 0.0
        assert "## paired diff open - layers" in W.format_text(result)

    def test_two_runs_are_read_together_and_duplicates_stop(self, tmp_path):
        a = _write_run(tmp_path / "a", [_game("open", 1000)])
        b = _write_run(tmp_path / "b", [_game("open", 1024)])
        assert W.window_stats([a, b], window=4)["arms"]["open"]["games"] == 2
        with pytest.raises(SystemExit, match="appears in both"):  # finding 1: selfplay_run.load_records の突き合わせ
            W.window_stats([a, a], window=4)
        with pytest.raises(SystemExit, match="different board sizes"):
            W.window_stats([a, _write_run(tmp_path / "c", [_game("open", 2000)], size=13)], window=4)

    def test_merging_runs_validates_arm_fingerprints_like_load_records(self, tmp_path):
        """final-fix finding 1: 複数 DIR は selfplay_run.load_records で突き合わせる（アームの指紋・対局条件が違えば
        SystemExit・互いに合う DIR は合算する）。"""

        def arm(reserve):
            settings = {"veil9_reserve": reserve}
            return {
                "name": "open",
                "strategy": "veil9",
                "mode": "ai:veil9",
                "settings": settings,
                "fingerprint": W.S.settings_fingerprint("ai:veil9", settings),
            }

        a = _write_run(tmp_path / "a", [_game("open", 1000)], arms=[arm(3.0)])
        b = _write_run(tmp_path / "b", [_game("open", 1024)], arms=[arm(4.0)])
        with pytest.raises(SystemExit, match="settings differ between the run directories"):
            W.window_stats([a, b], window=4)
        c = _write_run(tmp_path / "c", [_game("open", 2048)], arms=[arm(3.0)])
        assert W.window_stats([a, c], window=4)["arms"]["open"]["games"] == 2  # 同じ指紋の DIR は合算できる

    def test_merging_runs_validates_plan_conditions(self, tmp_path):
        """final-fix finding 1: 対局条件（komi・相手・投了モデルなど）が違う DIR の合算は止まる。"""
        a = _write_run(tmp_path / "a", [_game("open", 1000)], opponent={"kind": "humansl", "book_moves": 4})
        b = _write_run(tmp_path / "b", [_game("open", 1024)], opponent={"kind": "humansl", "book_moves": 24})
        with pytest.raises(SystemExit, match="game conditions differ between the run directories"):
            W.window_stats([a, b], window=4)

    def test_main_writes_the_json_and_an_ascii_table(self, tmp_path, capsys):
        run = _write_run(tmp_path / "r", [_game("open", 1000), _game("layers", 1000)])
        W.main([run, "--window", "4", "--compare", "open", "layers"])
        saved = json.load(open(os.path.join(run, "window_stats.json"), encoding="utf-8"))
        assert saved["window"] == 4 and set(saved["arms"]) == {"layers", "open"}
        out = capsys.readouterr().out
        assert out.startswith("# window stats (W = 4") and out.isascii()


def _report(path, name, ai, matches, size=9):
    """合成の recon の report_<name>.json（rows は手数 1 から・黒が先・matches[i] は手数 i + 1 の match）。"""
    rows = [
        {"depth": d, "player": "B" if d % 2 else "W", "match": m, "ptloss": 0.0 if m else 1.0}
        for d, m in enumerate(matches, 1)
    ]
    summary = {"game": name, "ai": ai, "n_moves": len(rows), "strategy": "Veil9Strategy", "board_size": size}
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, f"report_{name}.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": rows}, f)
    return str(path)


class TestReconMode:
    """実戦の事後解析（spec 2026-09-23-veil-strategy-design.md §16.5 の「実戦」: recon_9_veil と recon_9 を比べる）。"""

    def test_opponent_rates_and_best_move_streak(self, tmp_path):
        # AI は黒（奇数手）。相手（偶数手）は 2・4 手目が最善手、6 手目で外れ、8 手目は最善手
        run = _report(tmp_path / "rv", "game_1", "B", [True, True, False, True, True, False, True, True])
        result = W.recon_window_stats(run, window=4)
        (g,) = result["games"]
        assert g["opp_streak"] == 2 and g["opp_in"] == {"n": 2, "match": 2} and g["opp_out"] == {"n": 2, "match": 1}
        assert g["own_in"] == {"n": 2, "match": 1} and g["own_out"] == {"n": 2, "match": 2}
        assert result["window"] == 4 and result["summary"]["opp_out"]["rate_pooled"] == 0.5

    def test_default_window_and_the_table(self, tmp_path, capsys):
        veil = _report(tmp_path / "recon_9_veil", "game_1", "W", [True] * 30)
        enigma = _report(tmp_path / "recon_9", "game_2", "W", [False] * 30)
        assert W.recon_window_stats(veil)["window"] == 12  # 9路の既定の窓
        W.main(["--recon", veil, enigma])
        out = capsys.readouterr().out
        assert out.isascii() and out.count("# real games ") == 2
        assert not os.path.exists(os.path.join(veil, "window_stats_recon.json"))  # --out が無ければ書かない
        lines = out.splitlines()
        assert any(line.startswith("game_1 ") and line.split()[-1] == "15" for line in lines)  # 相手の 15 手すべて
        assert any(line.startswith("game_2 ") and line.split()[-1] == "0" for line in lines)
        W.main(["--recon", veil, "--out", str(tmp_path)])
        (saved,) = json.load(open(os.path.join(tmp_path, "window_stats_recon.json"), encoding="utf-8"))
        assert saved["games"][0]["opp_streak"] == 15
