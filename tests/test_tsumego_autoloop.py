import io
import json
import os
import threading
import time

import pytest
from PIL import Image

from katrain.core import tsumego_autoloop as al

DATA = os.path.join(os.path.dirname(__file__), "data", "autoloop")


def _frame(name):
    return Image.open(os.path.join(DATA, name)).convert("RGB")


def test_ui_point_scales_ratio_to_frame():
    assert al.ui_point("bar_hint", (900, 1600)) == (750, 1254)
    assert al.ui_point("popup_view", (450, 800)) == (220, 625)


def test_settings_defaults_and_override():
    s = al.autoloop_settings_from_config(None)
    assert s.hotkey == "ctrl+alt+a" and s.poll_ms == 500 and s.max_consecutive_errors == 3
    s2 = al.autoloop_settings_from_config({"poll_ms": 250, "ui_points": {"bar_hint": [0.5, 0.5]}})
    assert s2.poll_ms == 250 and s2.ui_points["bar_hint"] == (0.5, 0.5) and s2.ui_points["bar_undo"] == (0.933, 0.784)


def test_popup_present_on_real_frames():
    assert al.popup_present(_frame("popup_wrong.png")) is True
    assert al.popup_present(_frame("problem.png")) is False
    assert al.popup_present(_frame("hint.png")) is False


def test_popup_state_wrong_template():
    templates = al.load_templates()
    assert "wrong" in templates
    assert al.popup_state(_frame("popup_wrong.png"), templates) == "wrong"
    assert al.popup_state(_frame("problem.png"), templates) == "none"


def test_read_board_and_coordinates():
    frame = _frame("problem.png")  # 赤丸の無いフレームで読む（リングがパッチに掛かる可能性を避ける）
    read = al.read_board(frame, (9, 13, 19))
    assert read.size == 13 and len(read.grid) == 13
    assert read.grid[2][9] == "." and read.grid[1][9] == "W"
    x, y = al.board_to_device(2, 9, read.rect, 13)
    assert abs(x - 654) <= 6 and abs(y - 460) <= 6
    assert al.device_to_board(x, y, read.rect, 13) == (2, 9)


def test_find_hint_circle():
    frame = _frame("hint.png")
    rect = al.board_rect_of(frame)
    assert al.find_hint_circle(frame, rect, 13) == (2, 9)
    assert al.find_hint_circle(_frame("problem.png"), rect, 13) is None


def test_hint_enabled_on_problem_frame():
    assert al.hint_enabled(_frame("problem.png")) is True


def test_header_hash_is_stable_and_short():
    h1 = al.header_hash(_frame("problem.png"))
    h2 = al.header_hash(_frame("hint.png"))
    assert h1 == h2 and len(h1) == 16


def test_empty_points_lists_dots():
    grid = [list("B.W"), list("..."), list("W.B")]
    assert al.empty_points(grid) == [(0, 1), (1, 0), (1, 1), (1, 2), (2, 1)]


class FakeRunner:
    """subprocess.run の代役。呼ばれた引数列を記録し、登録した応答を返す"""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, args, binary=False, timeout_s=10):
        self.calls.append(list(args))
        key = " ".join(args[1:])  # adb パスを除いた部分で引く
        for k, v in self.responses.items():
            if key.startswith(k):
                return v
        return b"" if binary else ""


def test_adb_devices_and_tap_use_serial():
    runner = FakeRunner({"devices": "List of devices attached\n127.0.0.1:5585\tdevice\nemulator-5584\tdevice\n"})
    adb = al.AdbClient("HD-Adb.exe", "127.0.0.1:5585", runner=runner)
    assert adb.is_device() is True
    adb.tap(10.6, 20.2)
    assert runner.calls[-1] == ["HD-Adb.exe", "-s", "127.0.0.1:5585", "shell", "input", "tap", "11", "20"]


def test_adb_screencap_decodes_png():
    buf = io.BytesIO()
    Image.new("RGB", (4, 6), (1, 2, 3)).save(buf, format="PNG")
    runner = FakeRunner({"-s 127.0.0.1:5585 exec-out screencap -p": buf.getvalue()})
    adb = al.AdbClient("HD-Adb.exe", "127.0.0.1:5585", runner=runner)
    img = adb.screencap()
    assert img.size == (4, 6)


def test_adb_screencap_raises_on_empty():
    adb = al.AdbClient("HD-Adb.exe", "127.0.0.1:5585", runner=FakeRunner())
    with pytest.raises(al.AdbError):
        adb.screencap()


def test_discover_serial_reads_bluestacks_conf(tmp_path):
    conf = tmp_path / "bluestacks.conf"
    conf.write_text('bst.instance.Pie64.adb_port="5555"\nbst.instance.Pie64_3.adb_port="5585"\n', encoding="utf-8")
    runner = FakeRunner(
        {
            "connect 127.0.0.1:5585": "connected to 127.0.0.1:5585",
            "devices": "List of devices attached\n127.0.0.1:5585\tdevice\n",
        }
    )
    assert al.discover_serial("HD-Adb.exe", str(conf), runner=runner) == "127.0.0.1:5585"


def test_discover_serial_none_when_nothing_answers(tmp_path):
    conf = tmp_path / "bluestacks.conf"
    conf.write_text('bst.instance.Pie64.adb_port="5555"\n', encoding="utf-8")
    assert al.discover_serial("HD-Adb.exe", str(conf), runner=FakeRunner()) is None


def test_ledger_appends_jsonl(tmp_path):
    led = al.Ledger(str(tmp_path / "ledger.jsonl"))
    led.append({"a": 1})
    led.append({"b": "x"})
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l) for l in lines] == [{"a": 1}, {"b": "x"}]


def test_white_reply_detects_single_white_and_captures():
    g = [list("..."), list(".B."), list("...")]
    exp = al.apply_move_to_grid(g, 0, 1, "B")
    obs = al.apply_move_to_grid(exp, 0, 0, "W")
    assert al.white_reply(exp, obs) == (0, 0)
    assert al.white_reply(exp, exp) is None
    bad = [row[:] for row in exp]
    bad[2][2] = "B"
    assert al.white_reply(exp, bad) is False


class FakeAdb:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((int(x), int(y)))


class FakeVision:
    """フレームは dict: {"popup": bool, "grid": grid, "hint": (i,j)|None, "hint_on": bool}"""

    RECT = (0, 0, 899, 899)

    def __init__(self, size=3):
        self.size = size

    def popup_present(self, f):
        return f.get("popup", False)

    def popup_state(self, f):
        return f.get("state", "none")

    def read_board(self, f, size=None):
        if f.get("grid") is None:
            raise al.CaptureError("no board")
        return al.BoardRead(self.RECT, self.size, f["grid"])

    def board_rect(self, f):
        return self.RECT

    def find_hint_circle(self, f, rect, size):
        return f.get("hint")

    def hint_enabled(self, f):
        return f.get("hint_on", True)

    def header_hash(self, f):
        return "h"

    def ui_point(self, name, f):
        return al.ui_point(name, (900, 1600))


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def _run_harvest(h, frames):
    """フレーム列を順に step に流し、最初の非 running を返す"""
    for f in frames:
        st, payload = h.step(f)
        if st != "running":
            return st, payload
    return "running", None


def test_harvester_walks_hints_and_returns_line():
    base = [list("..."), list("..."), list("...")]
    clock = FakeClock()
    adb, vision = FakeAdb(), FakeVision(3)
    h = al.Harvester(adb, vision, base, 3, settle_ms=0, clock=clock, log=lambda m: None)
    g1 = al.apply_move_to_grid(base, 1, 1, "B")  # 黒 (1,1)
    g2 = al.apply_move_to_grid(g1, 0, 0, "W")  # 白 (0,0)
    g3 = al.apply_move_to_grid(g2, 2, 2, "B")  # 黒 (2,2)＝最終手（白応じず）
    # 1 フレーム = 1 step。phase "hint" はヒントを押して running を返す（赤丸は次のフレームで読む）ので、
    # 赤丸つきフレームはヒント押下フレームの**次**に置く
    frames = [
        {"popup": True},  # close: 問題を見る
        {"grid": g3},  # rewind: 最終局面 → 戻す
        {"grid": base},  # rewind: 初期局面 → hint: ヒント押下
        {"grid": base, "hint": (1, 1)},  # wait_hint: 赤丸 → 黒タップ
        {"grid": g2},
        {"grid": g2},  # wait_move: 黒+白 安定 2 フレーム → 手順追記
        {"grid": g2},  # hint: ヒント押下
        {"grid": g2, "hint": (2, 2)},  # wait_hint: 赤丸 → 黒タップ
        {"grid": g3},
        {"grid": g3},  # wait_move: 黒のみ 安定 → 手順追記
        {"grid": g3},  # hint: ヒント押下
        {"grid": g3, "hint": None, "hint_on": True},  # wait_hint: まだ 1.5 秒以内
    ]
    st, payload = _run_harvest(h, frames)
    assert st == "running"
    clock.advance(2.0)  # 1.5 秒経過・赤丸なし・ヒント灰 → 1回目の確認（2連続要求のため終了しない）
    st, payload = h.step({"grid": g3, "hint": None, "hint_on": False})
    assert st == "running"
    st, payload = h.step({"grid": g3, "hint": None, "hint_on": False})  # 2回目の灰確認 → 終了
    assert st == "done"
    assert payload == [((1, 1), "B"), ((0, 0), "W"), ((2, 2), "B")]
    names = [t for t in adb.taps]
    assert names[0] == al.ui_point("popup_view", (900, 1600))
    assert names[1] == al.ui_point("bar_undo", (900, 1600))


def test_harvester_fails_when_rewind_never_reaches_base():
    base = [list("..."), list("..."), list("...")]
    other = [list("B.."), list("..."), list("...")]
    h = al.Harvester(FakeAdb(), FakeVision(3), base, 3, settle_ms=0, clock=FakeClock(), log=lambda m: None)
    frames = [{"grid": other}] * 25
    st, payload = _run_harvest(h, frames)
    assert st == "failed" and "rewind" in payload


def test_harvester_fails_on_unexplained_diff():
    base = [list("..."), list("..."), list("...")]
    clock = FakeClock()
    h = al.Harvester(FakeAdb(), FakeVision(3), base, 3, settle_ms=0, clock=clock, log=lambda m: None)
    weird = [list("W.."), list(".B."), list("..B")]  # 黒 (1,1) は在るが (2,2) の黒が説明できない
    frames = [{"grid": base}, {"grid": base, "hint": (1, 1)}, {"grid": weird}, {"grid": weird}]
    st, payload = _run_harvest(h, frames)
    assert st == "failed" and "diff" in payload


def test_white_reply_detects_capture_of_just_played_black():
    """投げ込み/ナカデ捨て石: 白の応手が黒自身を取るので黒点は EMPTY のまま戻ってこない。
    white_reply は apply_move_to_grid で差分を検算するので obs[i][j]==BLACK に依存しない。"""
    base = [list("W.W"), list("..."), list("...")]  # (0,0)/(0,2) が白、(0,1) は 1 呼吸点だけの投げ込み点
    expected = al.apply_move_to_grid(base, 0, 1, "B")  # 黒 (0,1) 投げ込み（呼吸点 (1,1) のみ残る）
    observed = al.apply_move_to_grid(expected, 1, 1, "W")  # 白 (1,1) で最後の呼吸点を詰めて捕獲
    assert observed[0][1] == "."  # 黒は取られて盤上に残っていない
    assert al.white_reply(expected, observed) == (1, 1)


def test_harvester_accepts_black_captured_by_white_reply():
    base = [list("W.W"), list("..."), list("...")]
    clock = FakeClock()
    adb, vision = FakeAdb(), FakeVision(3)
    h = al.Harvester(adb, vision, base, 3, settle_ms=0, clock=clock, log=lambda m: None)
    observed = al.apply_move_to_grid(al.apply_move_to_grid(base, 0, 1, "B"), 1, 1, "W")
    frames = [
        {"grid": base},                                     # rewind: 初期局面 → hint: ヒント押下
        {"grid": base, "hint": (0, 1)},                      # wait_hint: 赤丸 → 黒タップ（投げ込み）
        {"grid": observed},
        {"grid": observed},                                  # wait_move: 白の捕獲後の盤で安定 → 手順追記
        {"grid": observed},                                  # hint: ヒント押下
        {"grid": observed, "hint": None, "hint_on": True},   # wait_hint: まだ 1.5 秒以内
    ]
    st, payload = _run_harvest(h, frames)
    assert st == "running"
    clock.advance(2.0)
    st, payload = h.step({"grid": observed, "hint": None, "hint_on": False})  # 1回目の灰確認
    assert st == "running"
    st, payload = h.step({"grid": observed, "hint": None, "hint_on": False})  # 2回目の灰確認 → 終了
    assert st == "done"
    assert payload == [((0, 1), "B"), ((1, 1), "W")]


def test_harvester_fails_when_popup_never_closes():
    base = [list("..."), list("..."), list("...")]
    h = al.Harvester(FakeAdb(), FakeVision(3), base, 3, settle_ms=0, clock=FakeClock(), log=lambda m: None)
    frames = [{"popup": True}] * 8
    st, payload = _run_harvest(h, frames)
    assert st == "failed" and "close" in payload


def test_harvester_fails_when_no_move_harvested():
    base = [list("..."), list("..."), list("...")]
    clock = FakeClock()
    h = al.Harvester(FakeAdb(), FakeVision(3), base, 3, settle_ms=0, clock=clock, log=lambda m: None)
    frames = [
        {"grid": base},                                   # rewind → hint: ヒント押下
        {"grid": base, "hint": None, "hint_on": True},     # wait_hint: まだ 1.5 秒以内
    ]
    st, payload = _run_harvest(h, frames)
    assert st == "running"
    clock.advance(2.0)
    st, payload = h.step({"grid": base, "hint": None, "hint_on": False})  # 1回目の灰確認
    assert st == "running"
    st, payload = h.step({"grid": base, "hint": None, "hint_on": False})  # 2回目 → 手順ゼロで失敗
    assert st == "failed" and "手順" in payload


def test_harvester_fails_after_overall_deadline():
    base = [list("..."), list("..."), list("...")]
    clock = FakeClock()
    h = al.Harvester(FakeAdb(), FakeVision(3), base, 3, settle_ms=0, clock=clock, log=lambda m: None)
    clock.advance(al.HARVEST_MAX_S + 1)
    st, payload = h.step({"grid": base})
    assert st == "failed" and "時間切れ" in payload


class FakeGui:
    def __init__(self):
        self.captures = 0
        self.saved = []
        self.stopped = 0
        self.notes = []
        self.logs = []

    def trigger_capture(self):
        self.captures += 1

    def save_line(self, base_grid, moves):
        self.saved.append((base_grid, moves))
        return True, len(moves)

    def stop_watch(self):
        self.stopped += 1

    def notify(self, kind, text):
        self.notes.append((kind, text))

    def log(self, text):
        self.logs.append(text)


class FrameAdb(FakeAdb):
    """screencap が与えたフレーム列を順に返す（尽きたら最後を繰り返す）"""

    def __init__(self, frames):
        super().__init__()
        self.frames = list(frames)

    def screencap(self):
        if len(self.frames) > 1:
            return self.frames.pop(0)
        return self.frames[0]

    def connect(self):
        return True

    def is_device(self):
        return True


def _controller(frames, tmp_path, vision=None, **over):
    settings = al.autoloop_settings_from_config(
        {"poll_ms": 0, "settle_ms": 0, "ledger_path": str(tmp_path / "l.jsonl"), "shots_dir": str(tmp_path), **over}
    )
    clock = FakeClock()
    gui = FakeGui()
    adb = FrameAdb(frames)
    c = al.AutoLoopController(adb, vision or FakeVision(3), gui, settings, al.Ledger(settings.ledger_path), clock=clock)
    return c, gui, adb, clock


BASE = [list("..."), list("..."), list("B..")]
FINAL = al.apply_move_to_grid(BASE, 1, 1, "B")


def test_controller_correct_flow_taps_black_and_advances(tmp_path):
    frames = [
        {"grid": BASE}, {"grid": BASE},                  # AWAIT: 2 フレーム同じ → キャプチャ起動
        {"grid": BASE},                                  # CAPTURING（完了は on_problem_ready）
        {"grid": BASE},                                  # ANSWERING: 黒の着手イベントを処理してタップ
        {"popup": True, "state": "correct"},             # ANSWERING: ポップアップ → RESULT
        {"popup": True, "state": "correct"},             # RESULT: correct → NEXT
        {"popup": True, "state": "correct"},             # NEXT: ポップアップの「次の問題」をタップ
        {"grid": [list("..."), list("..."), list("..W")]},
    ]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    assert gui.captures == 1 and c.state == "CAPTURING"
    c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.on_black_move(token=7, coords_xy=(1, 1))           # KaTrain 座標 (x=1,y=1) → グリッド (1,1)
    c.step()
    assert c.state == "ANSWERING"
    assert adb.taps[-1] == al.board_to_device(1, 1, FakeVision.RECT, 3)
    c.step()                                             # popup → RESULT
    assert c.state == "RESULT"
    c.step()                                             # correct → NEXT
    assert c.state == "NEXT" and c.stats["correct"] == 1
    c.step()                                             # 次の問題をタップ → AWAIT_PROBLEM
    assert adb.taps[-1] == al.ui_point("popup_next", (900, 1600)) and c.state == "AWAIT_PROBLEM"
    rec = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["outcome"] == "correct" and rec["key"] == "k1" and rec["route"] == "frame"


def test_controller_wrong_flow_harvests_and_saves(tmp_path):
    g1 = al.apply_move_to_grid(BASE, 1, 1, "B")
    frames = [
        {"grid": BASE}, {"grid": BASE}, {"grid": BASE}, {"grid": BASE},
        {"popup": True, "state": "wrong"},               # ANSWERING → RESULT
        {"popup": True, "state": "wrong"},               # RESULT: wrong → HARVEST
        {"popup": True},                                 # harvest close: 問題を見る
        {"grid": BASE},                                  # rewind: 初期局面 → ヒント押下
        {"grid": BASE, "hint": (1, 1)},                  # 赤丸 → 黒タップ
        {"grid": g1}, {"grid": g1},                      # 安定 → 手順追記
        {"grid": g1, "hint": None, "hint_on": False},    # ヒント押下（以後この frame が繰り返る）
    ]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step(); c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="solver")
    c.on_black_move(token=7, coords_xy=(0, 2))
    c.step()
    c.step()                                             # RESULT
    c.step()                                             # wrong → HARVEST（監視停止）
    assert c.state == "HARVEST" and gui.stopped == 1
    for _ in range(6):
        c.step()
    clock.advance(2.0)
    c.step()                                             # 1 回目の灰確認（2 連続要求のため終わらない）
    c.step()                                             # 2 回目の灰確認 → done
    assert gui.saved == [(BASE, [((1, 1), "B")])]
    assert c.state == "NEXT" and c.stats["harvested"] == 1


def test_controller_capture_failed_taps_empty_point_then_harvests(tmp_path):
    frames = [{"grid": BASE}, {"grid": BASE}, {"grid": BASE}, {"grid": BASE}, {"popup": True, "state": "wrong"}]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_capture_failed("窓が無い")
    c.step()                                             # CAPTURE_FAILED に入り、同じ周で空点をタップ
    assert c.state == "CAPTURE_FAILED"
    assert adb.taps[-1] == al.board_to_device(0, 0, FakeVision.RECT, 3)
    c.step()                                             # タップ済み・結果待ち
    c.step()                                             # popup → RESULT（base は ADB フレームから読んだ BASE）
    assert c.state == "RESULT"
    c.step()                                             # wrong → HARVEST
    assert c.state == "HARVEST"


def test_controller_capture_timeout_goes_to_capture_failed(tmp_path):
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    assert c.state == "CAPTURING"
    clock.advance(16)
    c.step()
    assert c.state == "CAPTURE_FAILED"


def test_controller_stalled_then_error_then_idle_after_3(tmp_path):
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path, max_consecutive_errors=1)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=1, base_grid=BASE, key="k", route="frame")
    c.step()
    clock.advance(41)
    c.step()
    assert c.state == "STALLED"
    clock.advance(61)
    c.step()
    assert c.state == "IDLE" and c.stats["failed"] == 1


def test_controller_ignores_black_move_from_other_game(tmp_path):
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=1, base_grid=BASE, key="k", route="frame")
    c.on_black_move(token=999, coords_xy=(0, 0))
    c.step()
    assert adb.taps == []


def test_controller_starts_on_popup_by_tapping_next(tmp_path):
    c, gui, adb, clock = _controller([{"popup": True, "state": "correct"}, {"popup": True, "state": "correct"}, {"grid": BASE}], tmp_path)
    c.activate()
    c.step()
    assert c.state == "NEXT"
    c.step()
    assert adb.taps[-1] == al.ui_point("popup_next", (900, 1600))


# --- レビュー修正（findings 1-5, m1-m6） ---


def test_controller_capture_failed_idle_not_overwritten(tmp_path):
    """finding 1: _error_step が上限で IDLE にした後、_step_capture_failed が NEXT で上書きしない"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path, max_consecutive_errors=1)
    c.activate()
    c.step(); c.step()
    c.on_capture_failed("窓が無い")
    c.step()                                             # CAPTURE_FAILED に入り、空点をタップ
    assert c.state == "CAPTURE_FAILED"
    c.step()                                             # タップ済み・結果待ち
    clock.advance(al.CAPTURE_FAILED_WAIT_S + 1)
    c.step()                                             # 締切超過 → error_step で IDLE（上書きされない）
    assert c.state == "IDLE" and c.stats["failed"] == 1


def test_controller_await_problem_retaps_then_errors(tmp_path):
    """finding 2a: NEXT のタップが効かず出題が検出できないまま AWAIT_PROBLEM に居続けたら、
    1 回目の締切超過で bar_next を再タップし、2 回目の締切超過で error_step に回す"""
    empty_frame = {"grid": [list("..."), list("..."), list("...")]}
    c, gui, adb, clock = _controller([empty_frame], tmp_path, max_consecutive_errors=1, answer_timeout_s=5)
    c.activate()
    clock.advance(6)
    c.step()
    assert adb.taps == [al.ui_point("bar_next", (900, 1600))]
    assert c.state == "AWAIT_PROBLEM"
    clock.advance(6)
    c.step()
    assert c.state == "IDLE" and c.stats["failed"] == 1


class _NoRectVision(FakeVision):
    """board_rect が常に失敗する Vision（finding 2b の検証用）"""

    def board_rect(self, f):
        raise al.CaptureError("no rect")


def test_controller_answering_unreadable_board_still_reaches_stalled(tmp_path):
    """finding 2b: pending_taps が残ったまま board_rect が読めなくても、締切超過で STALLED に抜ける"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path, vision=_NoRectVision(3))
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=1, base_grid=BASE, key="k", route="frame")
    c.on_black_move(token=1, coords_xy=(0, 0))
    c.step()
    assert c.state == "ANSWERING" and adb.taps == []
    clock.advance(41)
    c.step()
    assert c.state == "STALLED"


def test_controller_activate_resets_stats(tmp_path):
    """finding 3: activate() は stats をゼロへリセットする"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.stats["correct"] = 5
    c.activate()
    assert c.stats == {"problems": 0, "correct": 0, "wrong": 0, "harvested": 0, "failed": 0}


def test_controller_capture_failed_counts_toward_max_problems(tmp_path):
    """finding 3: CAPTURE_FAILED になった問題も stats["problems"] にカウントされる（max_problems の対象）"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path, max_problems=1)
    c.activate()
    c.step(); c.step()
    c.on_capture_failed("窓が無い")
    c.step()
    assert c.stats["problems"] == 1


def test_controller_start_stop_no_duplicate_threads(tmp_path):
    """finding 4: start(); stop(); start(); stop() で旧スレッドが残らない"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path, poll_ms=10)
    c.start()
    t1 = c._thread
    c.stop()
    assert c.running is False
    assert t1.is_alive() is False
    c.start()
    t2 = c._thread
    c.stop()
    assert c.running is False
    assert t2.is_alive() is False
    assert t1 is not t2


def test_controller_run_stops_after_repeated_step_exceptions(tmp_path):
    """m5: _run は step() が 10 回連続で例外を投げたら _to_idle で止まる"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path, poll_ms=5)

    def boom():
        raise RuntimeError("boom")

    c.step = boom
    c.state = "AWAIT_PROBLEM"
    c._stop.clear()
    c._thread = threading.Thread(target=c._run, name="tsumego-autoloop-test", daemon=True)
    c._thread.start()
    for _ in range(200):
        if c.state == "IDLE":
            break
        time.sleep(0.01)
    assert c.state == "IDLE"
    c.stop()
    c._thread.join(timeout=2.0)
    assert c._thread.is_alive() is False


def test_controller_answering_tap_cap_goes_to_stalled(tmp_path):
    """finding 5: 1問あたりのタップ上限に達したら pending_taps を捨てて STALLED へ（タップはしない）"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=1, base_grid=BASE, key="k", route="frame")
    c.step()
    c.problem.n_black = al.MAX_TAPS_PER_PROBLEM
    c.on_black_move(token=1, coords_xy=(0, 0))
    c.step()
    assert c.state == "STALLED"
    assert adb.taps == []


def test_controller_result_popup_vanished_records_ledger(tmp_path):
    """m1: verdict == "none" でも NEXT に行く前に unknown_popup/popup_vanished を台帳に書く"""
    frames = [
        {"grid": BASE}, {"grid": BASE}, {"grid": BASE},
        {"popup": True, "state": "none"},                # ANSWERING -> RESULT
    ]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=1, base_grid=BASE, key="k1", route="frame")
    c.step()
    c.step()                                             # ANSWERING: popup -> RESULT
    assert c.state == "RESULT"
    c.step()                                             # RESULT: verdict none -> NEXT（台帳に記録）
    assert c.state == "NEXT"
    rec = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["outcome"] == "unknown_popup" and rec["harvest"] == "skipped:popup_vanished"


class _SavableFrame(dict):
    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"x")


def test_controller_save_shot_returns_path_and_records_shots(tmp_path):
    """m4: _save_shot はパスを返し self._shots に積む。_record はそれを "shots" として書く"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    frame = _SavableFrame({"grid": BASE})
    path1 = c._save_shot(frame, "t1")
    path2 = c._save_shot(frame, "t2")
    assert path1 is not None and path2 is not None and path1 != path2
    assert c._shots == [path1, path2]
    c.problem = al._Problem(1, BASE, "k", "frame", clock())
    c._record(c.problem, "wrong")
    rec = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["shots"] == [path1, path2]


def test_controller_tap_helper_swallows_adb_error(tmp_path):
    """m5: _tap は AdbError を捕まえて gui.log し False を返す（呼び出し側はそのまま進む）"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)

    def raising_tap(x, y):
        raise al.AdbError("boom")

    c.adb.tap = raising_tap
    assert c._tap(1, 2) is False
    assert any("タップ失敗" in m for m in gui.logs)


# --- GUI 接続（Task 5）: Kivy を import せず ast で接続点の存在だけを確認する ---
def _main_source():
    path = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _main_tree():
    import ast

    return ast.parse(_main_source())


def test_main_has_autoloop_hooks():
    import ast

    tree = _main_tree()
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert {"_autoloop_trigger", "_autoloop_callbacks", "_save_answer_line"} <= names
    src = ast.unparse(tree)
    assert "on_problem_ready(" in src and "on_capture_failed(" in src and "on_black_move(" in src
    # 設定セクション名。ast.unparse は文字列リテラルの引用符を単引用符に正規化するので生ソースで見る
    assert '"tsumego_autoloop"' in _main_source()


def test_package_config_has_autoloop_section():
    path = os.path.join(os.path.dirname(__file__), "..", "katrain", "config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    sec = cfg["tsumego_autoloop"]
    assert sec["hotkey"] == "ctrl+alt+a" and sec["enabled"] is True and "adb_path" in sec


def test_popup_state_correct_template():
    # 実機 2026-08-23: 正解フレームの tail は correct テンプレと MAD 0.0 / wrong と 37.0（wrong フレームは逆）
    templates = al.load_templates()
    assert {"wrong", "correct"} <= set(templates)
    assert al.popup_state(_frame("popup_correct.png"), templates) == "correct"
    assert al.popup_state(_frame("popup_wrong.png"), templates) == "wrong"


def test_hint_disabled_frame():
    assert al.hint_enabled(_frame("hint_disabled.png")) is False
    assert al.hint_enabled(_frame("problem.png")) is True


def test_find_hint_circle_ignores_last_move_marker():
    # hint_disabled.png: 最終手の赤い四角マーカーだけ（赤丸なし）→ None
    fr = _frame("hint_disabled.png")
    rect = al.board_rect_of(fr)
    assert al.find_hint_circle(fr, rect, 13) is None
    # hint_with_marker.png: 赤丸 (2,9) ＋ 四角マーカー → 赤丸だけを返す
    fr2 = _frame("hint_with_marker.png")
    assert al.find_hint_circle(fr2, al.board_rect_of(fr2), 13) == (2, 9)
