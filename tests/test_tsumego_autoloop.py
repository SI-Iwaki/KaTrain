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
    """結果ポップアップ（濃紺のタイトル帯＋内側の小盤）だけを True にする（spec 追記4）。

    「盤の上端が黄色でない」だけだと認定証・遷移中・ホームまでポップアップ扱いになり、
    そこへ「次の問題」を撃ってしまう＝誤タップ事故の根本原因 (1)
    """
    assert al.popup_present(_frame("popup_wrong.png")) is True
    assert al.popup_present(_frame("popup_correct.png")) is True
    assert al.popup_present(_frame("popup_correct_animating.png")) is True
    assert al.popup_present(_frame("problem.png")) is False
    assert al.popup_present(_frame("hint.png")) is False
    assert al.popup_present(_frame("hint_disabled.png")) is False
    assert al.popup_present(_frame("transition.png")) is False
    assert al.popup_present(_frame("certificate_device.png")) is False


def test_popup_present_inner_board_measurements():
    """内側の小盤の黄色率実測（spec 追記4）。

    popup_wrong 0.87 / popup_correct 0.83 / popup_correct_animating 0.86 / 認定証 0.0。
    問題・遷移・ヒント画面は 0.94〜0.96 だが、盤の上端の帯（POPUP_STRIP）条件で既に除外される
    のでこの条件だけでは分離しない＝ホーム/メニュー画面（盤が中央に無い）を落とすための条件。
    """
    ratio = al.yellow_ratio
    assert abs(ratio(_frame("popup_wrong.png"), al.POPUP_INNER_BOARD_BOX) - 0.87) < 0.02
    assert abs(ratio(_frame("popup_correct.png"), al.POPUP_INNER_BOARD_BOX) - 0.83) < 0.02
    assert abs(ratio(_frame("popup_correct_animating.png"), al.POPUP_INNER_BOARD_BOX) - 0.86) < 0.02
    assert ratio(_frame("certificate_device.png"), al.POPUP_INNER_BOARD_BOX) == 0.0


def test_popup_present_false_without_inner_board():
    """盤の上端の帯とタイトル帯の条件を満たしても、中央に盤が無ければポップアップにしない。

    popup_wrong.png の内側の小盤ボックスを単色で塗りつぶして合成する（ホーム画面等、盤の無い
    未知の画面を模す）。他の2条件（黄色帯でない・タイトル帯が濃紺）は元のフレームのまま。
    """
    frame = _frame("popup_wrong.png").copy()
    x0, y0, x1, y1 = al._box(frame, al.POPUP_INNER_BOARD_BOX)
    px = frame.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            px[x, y] = (240, 240, 240)
    assert al.yellow_ratio(frame, al.POPUP_STRIP) < al.POPUP_STRIP_YELLOW_MAX
    assert al.result_title_band_dark(frame) is True
    assert al.popup_present(frame) is False


def test_result_title_band_dark_measurements():
    """帯の実測値（閾値 140 の下に 39.5 の余裕）。

    実測: popup_wrong / popup_correct 81.1・出現途中 100.5（＜140＝濃紺）。
    問題画面 53.7・遷移 43.5・**認定証 44.5** もアプリの青ヘッダなので**暗い側**に出る
    ＝この帯だけでは問題画面とも認定証とも分離できない（認定証は問題画面の上に載るダイアログで、
    この帯はその上に残るヘッダ＝spec 追記5）。分離するのは popup_present の黄色帯と内側の小盤。
    """
    band = al._band_mean
    assert abs(band(_frame("popup_wrong.png"), al.OVERLAY_TITLE_BAND) - 81.1) < 1.0
    assert abs(band(_frame("popup_correct_animating.png"), al.OVERLAY_TITLE_BAND) - 100.5) < 1.0
    assert abs(band(_frame("certificate_device.png"), al.OVERLAY_TITLE_BAND) - 44.5) < 1.0
    assert al.result_title_band_dark(_frame("popup_wrong.png")) is True
    assert al.result_title_band_dark(_frame("popup_correct.png")) is True
    assert al.result_title_band_dark(_frame("popup_correct_animating.png")) is True
    assert al.result_title_band_dark(_frame("problem.png")) is True  # 青ヘッダ（黄色帯で切る）


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


def test_foreground_package_parses_current_focus_line():
    runner = FakeRunner(
        {
            "-s 127.0.0.1:5565 shell dumpsys window": (
                "  mCurrentFocus=Window{d04619f u0 fm.wars.goquest/fm.wars.goquest_flutter.MainActivity}\n"
            )
        }
    )
    adb = al.AdbClient("HD-Adb.exe", "127.0.0.1:5565", runner=runner)
    assert adb.foreground_package() == "fm.wars.goquest"


def test_foreground_package_none_on_empty_output():
    adb = al.AdbClient("HD-Adb.exe", "127.0.0.1:5565", runner=FakeRunner())
    assert adb.foreground_package() is None


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


def test_discover_serial_prefers_instance_with_app_in_foreground(tmp_path):
    """複数インスタンスが応答するとき、詰碁アプリが前面のものを選ぶ（最初に応答した port ではない）"""
    conf = tmp_path / "bluestacks.conf"
    conf.write_text(
        'bst.instance.Pie64.adb_port="5555"\nbst.instance.Pie64_2.adb_port="5565"\n', encoding="utf-8"
    )
    runner = FakeRunner(
        {
            "connect 127.0.0.1:5555": "connected to 127.0.0.1:5555",
            "connect 127.0.0.1:5565": "connected to 127.0.0.1:5565",
            "devices": "List of devices attached\n127.0.0.1:5555\tdevice\n127.0.0.1:5565\tdevice\n",
            "-s 127.0.0.1:5555 shell dumpsys window": "  mCurrentFocus=Window{x u0 com.other.app/com.other.Main}\n",
            "-s 127.0.0.1:5565 shell dumpsys window": (
                "  mCurrentFocus=Window{x u0 fm.wars.goquest/fm.wars.goquest_flutter.MainActivity}\n"
            ),
        }
    )
    assert al.discover_serial("HD-Adb.exe", str(conf), runner=runner) == "127.0.0.1:5565"


def test_discover_serial_falls_back_to_first_responding_when_no_app_match(tmp_path):
    """どちらの前面も詰碁アプリでなければ、従来どおり最初に応答した serial を返す"""
    conf = tmp_path / "bluestacks.conf"
    conf.write_text(
        'bst.instance.Pie64.adb_port="5555"\nbst.instance.Pie64_2.adb_port="5565"\n', encoding="utf-8"
    )
    runner = FakeRunner(
        {
            "connect 127.0.0.1:5555": "connected to 127.0.0.1:5555",
            "connect 127.0.0.1:5565": "connected to 127.0.0.1:5565",
            "devices": "List of devices attached\n127.0.0.1:5555\tdevice\n127.0.0.1:5565\tdevice\n",
        }
    )
    assert al.discover_serial("HD-Adb.exe", str(conf), runner=runner) == "127.0.0.1:5555"


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
        self.events = []  # ("tap", x, y) / ("cap",) の時系列（タップと screencap の順序を見るため）

    def tap(self, x, y):
        self.taps.append((int(x), int(y)))
        self.events.append(("tap", int(x), int(y)))


class FakeVision:
    """フレームは dict: {"popup": bool, "grid": grid, "hint": (i,j)|None, "hint_on": bool, "overlay": bool}"""

    RECT = (0, 0, 899, 899)

    def __init__(self, size=3):
        self.size = size

    def popup_present(self, f):
        return f.get("popup", False)

    def popup_state(self, f):
        return f.get("state", "none")

    def overlay_present(self, f):
        return f.get("overlay", False)

    def find_close_glyph(self, f):
        return f.get("close", (40, 50))

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
    def __init__(self, capture_ok=True):
        self.captures = 0
        self.capture_ok = capture_ok  # trigger_capture が「起動した」と答えるか（I2e）
        self.saved = []
        self.protect_flags = []
        self.save_error = None
        self.stopped = 0
        self.notes = []
        self.logs = []

    def trigger_capture(self):
        self.captures += 1
        return self.capture_ok

    def save_line(self, base_grid, moves, protect_log=True):
        if self.save_error is not None:
            raise self.save_error
        self.saved.append((base_grid, moves))
        self.protect_flags.append(protect_log)
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
        self.screencaps = 0

    def screencap(self):
        self.screencaps += 1
        self.events.append(("cap",))
        if len(self.frames) > 1:
            return self.frames.pop(0)
        return self.frames[0]

    def connect(self):
        return True

    def is_device(self):
        return True


def _controller(frames, tmp_path, vision=None, gui=None, **over):
    settings = al.autoloop_settings_from_config(
        {"poll_ms": 0, "settle_ms": 0, "ledger_path": str(tmp_path / "l.jsonl"), "shots_dir": str(tmp_path), **over}
    )
    clock = FakeClock()
    gui = gui or FakeGui()
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
        {"popup": True, "state": "correct"},             # ANSWERING: ポップアップ 1 枚目（まだ RESULT にしない）
        {"popup": True, "state": "correct"},             # ANSWERING: 2 枚目 → RESULT
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
    c.step()                                             # popup 1 枚目（2 フレーム規則）
    assert c.state == "ANSWERING"
    c.step()                                             # popup 2 枚目 → RESULT
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
        {"popup": True, "state": "wrong"},               # ANSWERING: popup 1 枚目
        {"popup": True, "state": "wrong"},               # ANSWERING: 2 枚目 → RESULT
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
    c.step()                                             # popup 1 枚目（2 フレーム規則）
    c.step()                                             # popup 2 枚目 → RESULT
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
    frames = [{"grid": BASE}] * 5 + [{"popup": True, "state": "wrong"}]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_capture_failed("窓が無い")
    c.step()                                             # CAPTURE_FAILED に入る（I2c: 最初の1周は待つ）
    assert c.state == "CAPTURE_FAILED" and adb.taps == []
    c.step()                                             # 1 周待ったので空点をタップ
    assert adb.taps[-1] == al.board_to_device(0, 0, FakeVision.RECT, 3)
    c.step()                                             # タップ済み・結果待ち
    c.step()                                             # popup 1 枚目（2 フレーム規則）
    c.step()                                             # popup 2 枚目 → RESULT（base は ADB フレームから読んだ BASE）
    assert c.state == "RESULT"
    c.step()                                             # wrong → HARVEST
    assert c.state == "HARVEST"


def test_controller_capture_timeout_goes_to_capture_failed(tmp_path):
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    assert c.state == "CAPTURING"
    clock.advance(26)                                    # capture_timeout(25) 超過
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
    c.step()                                             # CAPTURE_FAILED に入る（最初の1周は待つ）
    assert c.state == "CAPTURE_FAILED"
    c.step()                                             # 空点をタップ
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


def test_controller_await_deadline_does_not_tap_without_board(tmp_path):
    """spec 追記4: 盤の見えない画面（アプリのホーム等）では「次の問題」を再タップしない。

    比率座標の bar_next は問題画面の座標なので、別画面では無関係なボタンを踏む。
    タップの代わりに 1 枚だけスクショを残し、2 回目の締切超過で従来どおり _error_step に回す
    """
    c, gui, adb, clock = _controller(
        [{"grid": None}], tmp_path, vision=_NoRectVision(3), max_consecutive_errors=1, answer_timeout_s=5
    )
    c.activate()
    clock.advance(6)
    c.step()
    assert adb.taps == [] and c.state == "AWAIT_PROBLEM"
    assert any("盤が見えない画面です" in m for m in gui.logs)
    clock.advance(6)
    c.step()
    assert adb.taps == [] and c.state == "IDLE" and c.stats["failed"] == 1


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
    c.step()                                             # ANSWERING: popup 1 枚目（2 フレーム規則）
    c.step()                                             # ANSWERING: popup 2 枚目 -> RESULT
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
    # S1: ホットキーの二重起動を排他し、孤児コントローラも含めて全部止める
    assert "_autoloop_lock" in src
    assert "_autoloop_instances" in src
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


# --- 実機スモーク修正（Task 6b: S1 二重起動 / S2 ポップアップ判定の安定化） ---


def test_controller_answering_needs_two_popup_frames(tmp_path):
    """S2: ポップアップ 1 枚では RESULT に行かない。出現アニメーション途中のフレームは判定帯に
    別の行が掛かって unknown になる（実機 2/6）ので、2 フレーム連続で見えてから RESULT へ"""
    frames = [
        {"grid": BASE}, {"grid": BASE},                  # AWAIT → CAPTURING
        {"grid": BASE},                                  # ANSWERING
        {"popup": True, "state": "correct"},             # popup 1 枚目（据え置き）
        {"grid": BASE},                                  # ポップアップが消えた → 数え直し
        {"popup": True, "state": "correct"},             # popup 1 枚目
        {"popup": True, "state": "correct"},             # popup 2 枚目 → RESULT
    ]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    assert c.state == "ANSWERING"
    c.step()                                             # popup 1 枚目 → まだ ANSWERING
    assert c.state == "ANSWERING"
    c.step()                                             # 非ポップアップ → カウントはリセット
    assert c.state == "ANSWERING"
    c.step()                                             # popup 1 枚目（数え直し）
    assert c.state == "ANSWERING"
    c.step()                                             # popup 2 枚目 → RESULT
    assert c.state == "RESULT"


def test_controller_stalled_needs_two_popup_frames(tmp_path):
    """S2: STALLED から RESULT に入る経路も 2 フレーム規則を使う"""
    c, gui, adb, clock = _controller([{"grid": BASE}, {"popup": True, "state": "correct"}], tmp_path)
    c.activate()
    c.state = "STALLED"
    c._deadline = clock() + 999
    c.problem = al._Problem(1, BASE, "k", "frame", clock())
    c.step()                                             # 非ポップアップ
    assert c.state == "STALLED"
    c.step()                                             # popup 1 枚目
    assert c.state == "STALLED"
    c.step()                                             # popup 2 枚目 → RESULT
    assert c.state == "RESULT"


def test_controller_result_retries_unknown_then_takes_correct(tmp_path):
    """S2: RESULT の verdict が unknown なら数フレーム粘る（アニメーション途中で撮れた回の救済）"""
    frames = [
        {"grid": BASE}, {"grid": BASE}, {"grid": BASE},
        {"popup": True, "state": "unknown"},             # ANSWERING: popup 1 枚目
        {"popup": True, "state": "unknown"},             # ANSWERING: 2 枚目 → RESULT
        {"popup": True, "state": "unknown"},             # RESULT: 再試行 1
        {"popup": True, "state": "unknown"},             # RESULT: 再試行 2
        {"popup": True, "state": "correct"},             # RESULT: 判定できた → correct
    ]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    c.step(); c.step()
    assert c.state == "RESULT"
    c.step(); c.step()                                   # unknown ×2 → まだ判定しない
    assert c.state == "RESULT"
    c.step()                                             # correct → 即処理
    assert c.state == "NEXT" and c.stats["correct"] == 1
    rec = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["outcome"] == "correct"


def test_controller_result_gives_up_after_repeated_unknown(tmp_path):
    """S2: 粘っても unknown のままなら従来どおり unknown_popup として処理して次へ"""
    frames = [
        {"grid": BASE}, {"grid": BASE}, {"grid": BASE},
        {"popup": True, "state": "unknown"},             # 以後この frame が繰り返る
    ]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    c.step(); c.step()                                   # ANSWERING: popup 2 枚 → RESULT
    assert c.state == "RESULT"
    for _ in range(al.RESULT_UNKNOWN_RETRIES):           # 再試行ぶんは判定しない
        c.step()
        assert c.state == "RESULT"
    c.step()                                             # 打ち切り → unknown_popup で次へ
    assert c.state == "NEXT"
    rec = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["outcome"] == "unknown_popup"


def test_popup_state_animating_frame_is_unknown():
    """実機 2026-08-23 の 20260823_085947_002_unknown_popup.png（正解ポップアップの出現途中）。
    判定帯に別の行が掛かり tail がテンプレとずれる → unknown（wrong と誤判定しないことを固定）"""
    templates = al.load_templates()
    assert al.popup_state(_frame("popup_correct_animating.png"), templates) == "unknown"


# --- 最終レビュー修正（I1-I7 / m1-m9） ---


def test_capture_timeout_default_is_25():
    """I2a: 正答中の問題に「わざと1手」を打ちに行かないよう、キャプチャ待ちを 25 秒にする"""
    assert al.autoloop_settings_from_config(None).capture_timeout_s == 25
    path = os.path.join(os.path.dirname(__file__), "..", "katrain", "config.json")
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["tsumego_autoloop"]["capture_timeout_s"] == 25


def test_harvest_deadline_is_180s():
    """m4: 40 手 ≒ 140 秒の実測ペースに合わせて収穫の全体締切を伸ばす"""
    assert al.HARVEST_MAX_S == 180.0


def test_farthest_empty_point_is_far_from_stones():
    """m5: 「わざと1手」はどの石からも最も遠い空点（チェビシェフ距離の最大・同値なら先頭）"""
    grid = [list("B...B"), list("....."), list("....."), list("....."), list("B....")]
    assert al.empty_points(grid)[0] == (0, 1)   # 左上から順だと石の隣
    assert al.farthest_empty_point(grid) == (4, 4)
    assert al.farthest_empty_point([list("BB"), list("BB")]) is None
    assert al.farthest_empty_point([list(".."), list("..")]) == (0, 0)  # 石が無ければ先頭


def test_controller_black_move_before_problem_ready_is_tapped(tmp_path):
    """I1: 再出題の高速解析では黒の着手が problem_ready より先に来る。捨てずに溜めてタップする"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    assert c.state == "CAPTURING"
    c.on_black_move(token=7, coords_xy=(1, 1))           # problem_ready より先に来た黒
    c.step()
    assert adb.taps == []                                # CAPTURING 中はまだ打たない（溜めるだけ）
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    assert c.state == "ANSWERING"
    assert adb.taps[-1] == al.board_to_device(1, 1, FakeVision.RECT, 3)


def test_controller_drops_early_taps_of_other_tokens(tmp_path):
    """I1: 別トークン（前の問題）の先行黒手は破棄する"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_black_move(token=999, coords_xy=(1, 1))
    c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    assert c.state == "ANSWERING" and adb.taps == []
    assert any("先行" in m for m in gui.logs)


def test_controller_late_problem_ready_after_capture_failed_returns_to_answering(tmp_path):
    """I2b: 遅れて届いたキャプチャ完了は、CAPTURE_FAILED でも（未タップなら）活かす"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    assert c.state == "CAPTURING"
    clock.advance(26)                                    # capture_timeout(25) 超過
    c.step()
    assert c.state == "CAPTURE_FAILED" and adb.taps == []
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    assert c.state == "ANSWERING"
    assert c.stats["problems"] == 1                      # CAPTURE_FAILED で数えた1問を二重に数えない


def test_controller_late_problem_ready_ignored_after_deliberate_tap(tmp_path):
    """I2b: すでに「わざと1手」を打った後の problem_ready は受理しない（盤がずれている）"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    clock.advance(26)
    c.step()                                             # CAPTURE_FAILED に入る
    c.step()                                             # 1 周待つ（遅いキャプチャの猶予）
    c.step()                                             # わざと1手
    assert adb.taps != []
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    assert c.state == "CAPTURE_FAILED"


def test_controller_await_stays_when_trigger_capture_declines(tmp_path):
    """I2e: キャプチャを起動できなかった（busy/debounce）ら CAPTURING に入らず AWAIT で再試行する"""
    gui = FakeGui(capture_ok=False)
    c, _gui, adb, clock = _controller([{"grid": BASE}], tmp_path, gui=gui)
    c.activate()
    c.step(); c.step()
    assert gui.captures == 1 and c.state == "AWAIT_PROBLEM"
    gui.capture_ok = True
    c.step()
    assert gui.captures == 2 and c.state == "CAPTURING"


def test_controller_taps_before_screencap_when_rect_known(tmp_path):
    """I3b: 2 手目以降は rect が既知なので screencap を待たずにタップする（余分な撮影もしない）"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.on_black_move(token=7, coords_xy=(1, 1))
    c.step()                                             # 1 手目: frame から rect を確定
    assert c.problem.rect is not None
    caps, mark = adb.screencaps, len(adb.events)
    c.on_black_move(token=7, coords_xy=(0, 0))
    c.step()
    assert adb.events[mark][0] == "tap"                  # screencap より前にタップが出ている
    assert adb.screencaps == caps + 1                    # タップのために撮影が増えない


def test_run_waits_poll_minus_step_elapsed(tmp_path):
    """I3a: 実効周期を保つ（step の所要ぶんだけ待ちを縮める）"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path, poll_ms=100)
    waits = []

    def slow_step():
        clock.advance(0.06)

    class _Wake:
        def wait(self, t):
            waits.append(t)
            c._stop.set()
            return True

        def clear(self):
            pass

        def set(self):
            pass

        def is_set(self):
            return False

    c.step = slow_step
    c._wake = _Wake()
    c._stop.clear()
    c._thread = threading.current_thread()
    c._run()
    assert waits and abs(waits[0] - 0.04) < 1e-6


class _DoneHarvester:
    def __init__(self, moves):
        self.moves = moves

    def step(self, frame):
        return "done", list(self.moves)


def test_controller_harvest_protect_log_only_for_real_problem(tmp_path):
    """I4: CAPTURE_FAILED→HARVEST の保存では .keep を付けない（前問のログが保護されてしまう）"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.problem = al._Problem(7, BASE, "k", "frame", clock())
    c.harvester, c.state = _DoneHarvester([((1, 1), "B")]), "HARVEST"
    c.step()
    assert gui.protect_flags == [True]
    c.problem = al._Problem(None, BASE, None, None, clock())
    c.harvester, c.state = _DoneHarvester([((1, 1), "B")]), "HARVEST"
    c.step()
    assert gui.protect_flags == [True, False]


def test_controller_harvest_survives_save_failure(tmp_path):
    """m7: 回答帳への保存が例外を投げても台帳に残して次の問題へ進む"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    gui.save_error = RuntimeError("boom")
    c.problem = al._Problem(7, BASE, "k", "frame", clock())
    c.harvester, c.state = _DoneHarvester([((1, 1), "B")]), "HARVEST"
    c.step()
    assert c.state == "NEXT"
    rec = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["harvest"].startswith("skipped:save_failed")


class _RaisingAdb(FakeAdb):
    def tap(self, x, y):
        raise al.AdbError("boom")


def test_harvester_survives_adb_tap_error():
    """I5: タップの AdbError で例外を上げない（_run の例外カウンタでループ全体が止まるのを防ぐ）"""
    base = [list("..."), list("..."), list("...")]
    h = al.Harvester(_RaisingAdb(), FakeVision(3), base, 3, settle_ms=0, clock=FakeClock(), log=lambda m: None)
    assert h.step({"popup": True}) == ("running", None)   # close のタップ
    h2 = al.Harvester(_RaisingAdb(), FakeVision(3), base, 3, settle_ms=0, clock=FakeClock(), log=lambda m: None)
    st, _p = _run_harvest(h2, [{"grid": base}, {"grid": base, "hint": (1, 1)}])  # 赤丸への黒タップ
    assert st == "running"


def test_harvester_survives_capture_error_in_wait_hint():
    """I5: wait_hint の board_rect が CaptureError でも running を返す（遷移画面のフレーム）"""
    base = [list("..."), list("..."), list("...")]
    h = al.Harvester(FakeAdb(), _NoRectVision(3), base, 3, settle_ms=0, clock=FakeClock(), log=lambda m: None)
    st, _p = _run_harvest(h, [{"grid": base}, {"grid": base, "hint": (1, 1)}])
    assert st == "running"


def test_step_returns_when_stopped_during_screencap(tmp_path):
    """m1: stop() が screencap 中に入っても _step_idle を呼びに行かない"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    real = adb.screencap

    def stopping():
        c.state = "IDLE"
        return real()

    adb.screencap = stopping
    c.step()
    assert c.state == "IDLE"


def test_run_adb_raises_on_nonzero_returncode(monkeypatch):
    """m2: adb が非ゼロ終了したら AdbError（無言で空文字を返さない）"""

    class _Proc:
        returncode = 1
        stdout = b""
        stderr = b"error: device not found"

    monkeypatch.setattr(al.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(al.AdbError) as e:
        al._run_adb(["adb", "devices"])
    assert "not found" in str(e.value)


def test_adb_connect_returns_false_on_error():
    """m2: connect() は AdbError を捕まえて False を返す（discover_serial が次の port へ進める）"""

    def runner(args, binary=False, timeout_s=10):
        raise al.AdbError("boom")

    assert al.AdbClient("adb", "127.0.0.1:5585", runner=runner).connect() is False


def test_discover_serial_passes_timeout(tmp_path):
    """I6: ADB 探索は短いタイムアウトで撃つ（見つからない port で GUI が固まらない）"""
    conf = tmp_path / "bluestacks.conf"
    conf.write_text('bst.instance.Pie64.adb_port="5585"\n', encoding="utf-8")
    seen = []

    def runner(args, binary=False, timeout_s=10):
        seen.append(timeout_s)
        return "connected to 127.0.0.1:5585" if args[1] == "connect" else "127.0.0.1:5585\tdevice\n"

    assert al.discover_serial("HD-Adb.exe", str(conf), runner=runner, timeout_s=1.5) == "127.0.0.1:5585"
    # connect + devices + foreground_package(dumpsys window) の3本、全部が同じ短いタイムアウトで飛ぶ
    assert seen == [1.5, 1.5, 1.5]


def test_ledger_records_header_hash_and_log_name(tmp_path):
    """m3: 台帳に header_hash（出題フレーム）と log（詰碁ログのファイル名）を残す"""
    frames = [{"grid": BASE}] * 3 + [{"popup": True, "state": "correct"}] * 3
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame", log_name="tsumego_20260823_0900.log")
    c.step(); c.step(); c.step(); c.step()
    rec = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["outcome"] == "correct" and rec["header_hash"] == "h"
    assert rec["log"] == "tsumego_20260823_0900.log"


def test_to_idle_and_stop_clear_event_queue(tmp_path):
    """m6: IDLE 中にイベントを溜めない（次の start で古い黒手が飛び出すのを防ぐ）"""
    c, gui, adb, clock = _controller([{"grid": BASE}], tmp_path)
    c.activate()
    c.on_black_move(token=1, coords_xy=(0, 0))
    c._to_idle("test")
    assert c._events.empty()
    c.on_capture_failed("x")
    c.stop()
    assert c._events.empty()


def test_controller_capture_failed_taps_farthest_empty(tmp_path):
    """m5: わざと1手は「どの石からも最も遠い空点」（左上の空点ではない）"""
    g = [list("B...B"), list("....."), list("....."), list("....."), list("B....")]
    c, gui, adb, clock = _controller([{"grid": g}], tmp_path, vision=FakeVision(5))
    c.activate()
    c.step(); c.step()
    c.on_capture_failed("窓が無い")
    c.step()                                             # CAPTURE_FAILED（1周待ち）
    c.step()                                             # わざと1手＝最も遠い空点
    assert adb.taps[-1] == al.board_to_device(4, 4, FakeVision.RECT, 5)


def test_transition_frame_is_not_popup_and_board_reads():
    """I7: 遷移画面（ヘッダ・下バー無し・右上に残り秒）はポップアップではなく、盤は 13 路で読める"""
    fr = _frame("transition.png")
    assert al.popup_present(fr) is False
    assert al.read_board(fr, (9, 13, 19)).size == 13


def _main_func_src(name):
    import ast

    for n in ast.walk(_main_tree()):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.unparse(n)
    raise AssertionError(f"{name} が見つかりません")


def test_main_autoloop_start_is_guarded():
    """I6: 起動本体を try/except で包み、ADB 探索は短いタイムアウト＋前回 serial の記憶"""
    src = _main_func_src("_autoloop_trigger_locked")
    assert "自動ループを開始できません" in src and "except Exception" in src
    assert "ADB に接続中" in src
    assert "auto_ai_black" in src
    assert "_autoloop_serial" in src
    find = _main_func_src("_autoloop_find_serial")   # 前回 serial を先に試す・探索は短いタイムアウト
    assert "timeout_s=3.0" in find and "_autoloop_serial" in find
    # 前回の serial も詰碁アプリが前面かどうかを確認してから使う（複数インスタンス対策）
    assert "foreground_package" in find and "APP_PACKAGE" in find


def test_main_capture_trigger_reports_whether_it_ran():
    """I2e/I2d: trigger_capture は bool を返し、早期 return でも on_capture_failed を通知する"""
    trig = _main_func_src("_tsumego_capture_trigger")
    assert "return False" in trig and "return True" in trig
    cb = _main_func_src("trigger_capture")
    assert "return self._tsumego_capture_trigger" in cb
    apply_src = _main_func_src("_do_tsumego_capture_apply")
    assert apply_src.count("_autoloop_capture_failed") >= 2


def test_main_save_answer_line_takes_protect_log():
    """I4: 回答帳保存はログ保護の有無を選べる（自動ループの CAPTURE_FAILED では付けない）"""
    import ast

    for n in ast.walk(_main_tree()):
        if isinstance(n, ast.FunctionDef) and n.name == "_save_answer_line":
            assert "protect_log" in [a.arg for a in n.args.args]
            break
    else:
        raise AssertionError("_save_answer_line が見つかりません")
    assert "protect_log" in _main_func_src("save_line")


def test_main_passes_log_name_to_problem_ready():
    """m3: 台帳の log 欄に詰碁ログのファイル名を渡す"""
    src = _main_func_src("_do_tsumego_capture_apply")   # finish_gui は同名が複数あるので親で見る
    assert "log_name=os.path.basename" in src


# --- 認定証などのフルスクリーン画面（spec 追記2） ---

# "popup": True は歴史的な名残（実機では overlay と popup は排他）。ANSWERING/STALLED も
# spec 追記4 で _handle_overlay を先頭に置いたため、この "popup" フラグは overlay=True の間は
# 一切参照されない（overlay が先に消費するため）。RESULT 到達後に出す想定でだけ使う
OVERLAY = {"popup": True, "state": "unknown", "overlay": True}


def test_find_close_glyph_on_certificate():
    """認定証**ダイアログ**の左上 × を見つける（実機 900x1600 のフレームで ≈(0.09, 0.20)）。

    認定証は全画面ではなく問題画面の上に載るダイアログで、アプリのヘッダ（← 戻る ≈(0.045,0.05)）
    はその上に残る＝画面の左上を探すと ← を押してホームへ飛ぶ（spec 追記5）。
    """
    frame = _frame("certificate_device.png")
    w, h = frame.size
    point = al.find_close_glyph(frame)
    assert point is not None
    x, y = point
    assert abs(x / w - 0.09) < 0.02 and abs(y / h - 0.20) < 0.02


def test_find_close_glyph_none_on_problem_screen():
    """問題画面のヘッダの ← を × と取り違えない（取り違えるとアプリをホームへ飛ばす）"""
    assert al.find_close_glyph(_frame("problem.png")) is None


def test_overlay_present_only_on_certificate():
    """結果ポップアップ（中央に小盤）・問題画面（盤の上端が黄色）はオーバーレイではない"""
    assert al.overlay_present(_frame("certificate_device.png")) is True
    assert al.overlay_present(_frame("popup_correct.png")) is False
    assert al.overlay_present(_frame("popup_correct_animating.png")) is False
    assert al.overlay_present(_frame("popup_wrong.png")) is False
    assert al.overlay_present(_frame("problem.png")) is False
    assert al.overlay_present(_frame("hint.png")) is False
    assert al.overlay_present(_frame("hint_disabled.png")) is False
    assert al.overlay_present(_frame("transition.png")) is False


def test_overlay_present_measurements_on_certificate():
    """認定証ダイアログの署名の実測（spec 追記5）: 盤の帯 0.017 / 中央の小盤 0.0 / 紙 247.2"""
    frame = _frame("certificate_device.png")
    assert al.yellow_ratio(frame, al.POPUP_STRIP) < al.POPUP_STRIP_YELLOW_MAX
    assert al.yellow_ratio(frame, al.POPUP_INNER_BOARD_BOX) < al.OVERLAY_INNER_BOARD_YELLOW_MAX
    assert abs(al._band_mean(frame, al.OVERLAY_PAPER_BAND) - 247.2) < 1.0
    # 結果ポップアップの同じ帯も 215.4 で明るい＝紙の条件だけでは分離しない（分離は小盤と ×）
    assert al._band_mean(_frame("popup_wrong.png"), al.OVERLAY_PAPER_BAND) >= al.OVERLAY_PAPER_MIN


def test_vision_exposes_overlay_helpers():
    v = al.Vision((9, 13, 19), templates={})
    frame = _frame("certificate_device.png")
    assert v.overlay_present(frame) is True
    assert v.find_close_glyph(frame) == al.find_close_glyph(frame)


def test_controller_result_closes_overlay_then_takes_verdict(tmp_path):
    """RESULT の先頭でオーバーレイを × で閉じる（判定は進めない）。消えたら通常どおり判定する。

    spec 追記4: × は 2 フレーム連続で見えてから 1 回、次は OVERLAY_TAP_WAIT_S 待ってから
    （フェード中に連打して、消えた後の問題画面の ← 戻るを押す事故への対策）。
    ANSWERING → RESULT の遷移は overlay の無い純粋な popup フレームで起こす（spec 追記4 で
    ANSWERING も _handle_overlay を先頭で見るため、overlay=True のフレームはそちらで消費される）
    """
    frames = [
        {"grid": BASE}, {"grid": BASE}, {"grid": BASE},
        {"popup": True, "state": "unknown"}, {"popup": True, "state": "unknown"},  # ANSWERING: popup 2 枚 → RESULT
        OVERLAY, OVERLAY, OVERLAY,                       # RESULT: 1 枚目は確認・以降 × をタップ
        {"popup": True, "state": "correct"},             # RESULT: オーバーレイが消えた → correct
        {"popup": True, "state": "correct"},
    ]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    c.step(); c.step()
    assert c.state == "RESULT"
    c.step()                                             # 1 枚目: 確認だけ（タップしない）
    assert c.state == "RESULT" and adb.taps == []
    c.step()                                             # 2 枚目: × を 1 回
    assert c.state == "RESULT" and adb.taps == [(40, 50)]
    c.step()                                             # 待ちの間は 2 回目を押さない
    assert adb.taps == [(40, 50)]
    clock.advance(2.0)
    c.step()
    assert c.state == "RESULT" and adb.taps == [(40, 50)] * 2
    assert any("オーバーレイ" in m for m in gui.logs)
    clock.advance(2.0)
    c.step()
    assert c.state == "NEXT" and c.stats["correct"] == 1


def test_controller_answering_closes_overlay_without_waiting_for_stalled(tmp_path):
    """ANSWERING 中に認定証が出たら、STALLED（40秒+60秒待ち）を経由せず即座に × で閉じにいく。

    spec 追記4: _handle_overlay を _step_answering の先頭でも呼ぶ。オーバーレイは popup_present
    の署名（濃紺のタイトル帯）とは無関係なので、先頭で割り込まなければ answer_timeout_s の締切
    まで気付かれない。
    """
    frames = [
        {"grid": BASE}, {"grid": BASE}, {"grid": BASE},
        {"overlay": True, "close": (40, 50)},            # ANSWERING: 1 枚目は確認だけ
        {"overlay": True, "close": (40, 50)},             # ANSWERING: 2 枚目 → × を 1 回
    ]
    c, gui, adb, clock = _controller(frames, tmp_path)
    c.activate()
    c.step(); c.step()
    c.on_problem_ready(token=7, base_grid=BASE, key="k1", route="frame")
    c.step()
    assert c.state == "ANSWERING"
    clock.advance(200.0)                                  # answer_timeout_s(40)+STALL_EXTRA_S(60) 超
    c.step()                                              # overlay 1 枚目: 確認だけ（タップしない）
    assert c.state == "ANSWERING" and adb.taps == []
    c.step()                                              # overlay 2 枚目: × を 1 回。STALLED にはならない
    assert c.state == "ANSWERING" and adb.taps == [(40, 50)]


def test_controller_overlay_taps_are_capped(tmp_path):
    """閉じられないオーバーレイは OVERLAY_MAX_TAPS で打ち切る（無限タップにしない）"""
    c, gui, adb, clock = _controller([OVERLAY], tmp_path, max_consecutive_errors=9)
    c.activate()
    c.step()                                             # 1 枚目は確認だけ
    assert adb.taps == []
    for _ in range(al.OVERLAY_MAX_TAPS):
        c.step()
        clock.advance(2.0)
    assert adb.taps == [(40, 50)] * al.OVERLAY_MAX_TAPS and c.stats["failed"] == 0
    c.step()
    assert adb.taps == [(40, 50)] * al.OVERLAY_MAX_TAPS and c.stats["failed"] == 1
    assert c.state == "AWAIT_PROBLEM"                    # 状態は変えない


def test_controller_overlay_needs_two_frames_and_waits(tmp_path):
    """× は 2 フレーム連続で見えてから 1 回だけ。待ちが明けるまで次のタップは撃たない"""
    c, gui, adb, clock = _controller([OVERLAY], tmp_path)
    c.activate()
    c.step()
    assert adb.taps == [] and c._overlay_seen == 1
    c.step()
    assert adb.taps == [(40, 50)] and c._overlay_taps == 1
    for _ in range(3):                                   # 待ちの間は何回 step しても増えない
        c.step()
    assert adb.taps == [(40, 50)]
    clock.advance(al.OVERLAY_TAP_WAIT_S + 0.1)
    c.step()
    assert adb.taps == [(40, 50)] * 2


def test_controller_overlay_without_close_glyph_never_taps(tmp_path):
    """× が見つからないフレームでは 1 回もタップしない（比率フォールバックは廃止）"""
    c, gui, adb, clock = _controller([dict(OVERLAY, close=None)], tmp_path, max_consecutive_errors=9)
    c.activate()
    for _ in range(al.OVERLAY_MAX_TAPS + 2):
        c.step()
        clock.advance(2.0)
    assert adb.taps == [] and c.stats["failed"] == 1
    assert any("× が見つかりません" in m for m in gui.logs)


def test_controller_overlay_counter_resets_when_gone(tmp_path):
    """オーバーレイが消えたらカウンタは 0 に戻る（次の認定証も 3 回まで粘れる）"""
    c, gui, adb, clock = _controller([OVERLAY], tmp_path)
    c.activate()
    c.step(); c.step()
    assert c._overlay_taps == 1 and c._overlay_seen == 2
    clock.advance(2.0)
    c.adb.frames = [{"grid": BASE}]
    c.step()
    assert c._overlay_taps == 0 and c._overlay_seen == 0


def test_controller_next_taps_are_capped(tmp_path):
    """popup が消えないまま NEXT を繰り返したら、当てずっぽうの × を撃たずに失敗で打ち切る

    spec 追記4: 旧実装は上限超えで CLOSE_FALLBACK_POINT(0.045,0.035) を撃っていたが、
    そこは問題画面ではヘッダの ← 戻る＝アプリをホームへ飛ばす座標だった
    """
    c, gui, adb, clock = _controller([{"popup": True, "state": "correct"}], tmp_path, max_consecutive_errors=9)
    c.activate()

    def next_round():                                    # AWAIT（popup）→ NEXT（タップ）
        clock.advance(1.0); c.step()
        clock.advance(1.0); c.step()

    nxt = al.ui_point("popup_next", (900, 1600))
    for _ in range(al.NEXT_MAX_TAPS):
        next_round()
    assert adb.taps == [nxt] * al.NEXT_MAX_TAPS and c.stats["failed"] == 0
    next_round()                                         # 上限超え → × は撃たずに打ち切り
    assert adb.taps == [nxt] * (al.NEXT_MAX_TAPS + 1)
    assert c.stats["failed"] == 1 and c._next_taps == 0
    assert not hasattr(al, "CLOSE_FALLBACK_POINT")


def test_controller_next_taps_reset_when_board_appears(tmp_path):
    """AWAIT で石のある盤が読めたら NEXT の連続タップ数は 0 に戻る"""
    c, gui, adb, clock = _controller([{"popup": True, "state": "correct"}], tmp_path)
    c.activate()
    clock.advance(1.0); c.step()
    clock.advance(1.0); c.step()
    assert c._next_taps == 1
    adb.frames = [{"grid": BASE}]
    clock.advance(1.0); c.step()
    assert c._next_taps == 0
