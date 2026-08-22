import io
import json
import os

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
