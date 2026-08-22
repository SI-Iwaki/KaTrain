"""詰碁の自動ループ（spec: docs/superpowers/specs/2026-08-23-tsumego-autoloop-design.md）。

BlueStacks の「囲碁詰めチャレ」を ADB で操作し、出題→回答→正誤→（誤答なら）ヒント歩きで
回答帳へ記録→次の問題、を回す。Kivy / KataGo / __main__ に依存しない（テストから直接 import）。

座標系: 認識グリッド grid[i][j] は i=上から（top origin）。KaTrain の Move.coords=(x,y) は
y=下から。変換は board_watch.move_to_grid / grid_to_move を使う（自前で書かない）。
"""

import hashlib
import io
import json
import os
import queue
import re
import subprocess
import threading
import time
from typing import NamedTuple, Optional

from PIL import Image, ImageStat

from katrain.core.board_watch import EMPTY, BLACK, WHITE, apply_move_to_grid, move_to_grid
from katrain.core.tsumego_capture import CaptureError, _is_yellow, detect_board, detect_size_and_classify

# --- 定数（デバイス解像度 900x1600 基準。比率は解像度が変わっても追従する） ---
DEVICE_W, DEVICE_H = 900, 1600
DEFAULT_ADB_PATH = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
BLUESTACKS_CONF = r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "img", "autoloop")
DEFAULT_UI_POINTS = {
    "bar_next": (0.472, 0.784),
    "bar_hint": (0.833, 0.784),
    "bar_undo": (0.933, 0.784),
    "popup_next": (0.256, 0.781),
    "popup_view": (0.489, 0.781),
}
POPUP_STRIP = (0.02, 0.181, 0.98, 0.19)  # 大盤の上端の帯。実測: 問題画面 黄 0.957 / ポップアップ 0.074
POPUP_STRIP_YELLOW_MAX = 0.5
VERDICT_BAND = (0.10, 0.289, 0.90, 0.325)  # 判定文 1 行目（実測 文字 y 481..511）
VERDICT_DARK_SUM = 300  # 文字画素: R+G+B < 300（紙色は 600 超）
VERDICT_TAIL_W = 140  # 文字列の右端に寄せた切り出し幅（中央寄せ文の長さ差を吸収）
VERDICT_MAX_MAD = 30.0  # テンプレートとの平均絶対差の上限
VERDICT_MIN_GAP = 10.0  # 1位と2位の差がこれ未満なら unknown
HINT_ICON = (0.833, 0.775, 18)  # (cx比, cy比, 半径px)。実測 平均輝度: 有効 151 / グレーの戻す 48
HINT_ICON_ENABLED_MIN = 110.0
HEADER_BAND = (0.10, 0.15, 0.90, 0.18)
RED_RING_MIN_PIXELS = 80


def _is_red(r, g, b):
    return r > 180 and g < 110 and b < 110 and (r - g) > 90


def ui_point(name, frame_size, ui_points=None):
    """比率座標 → フレーム座標（int）"""
    rx, ry = (ui_points or DEFAULT_UI_POINTS)[name]
    w, h = frame_size
    return int(round(rx * w)), int(round(ry * h))


class AutoLoopSettings(NamedTuple):
    enabled: bool
    hotkey: str
    adb_path: str
    adb_serial: str
    poll_ms: int
    settle_ms: int
    answer_timeout_s: float
    capture_timeout_s: float
    max_problems: int
    max_consecutive_errors: int
    ui_points: dict
    ledger_path: str
    shots_dir: str


def autoloop_settings_from_config(cfg):
    cfg = cfg or {}
    points = dict(DEFAULT_UI_POINTS)
    for k, v in (cfg.get("ui_points") or {}).items():
        points[k] = (float(v[0]), float(v[1]))
    home = os.path.expanduser("~")
    return AutoLoopSettings(
        enabled=bool(cfg.get("enabled", True)),
        hotkey=str(cfg.get("hotkey", "ctrl+alt+a")),
        adb_path=str(cfg.get("adb_path") or DEFAULT_ADB_PATH),
        adb_serial=str(cfg.get("adb_serial") or ""),
        poll_ms=int(cfg.get("poll_ms", 500)),
        settle_ms=int(cfg.get("settle_ms", 700)),
        answer_timeout_s=float(cfg.get("answer_timeout_s", 40)),
        capture_timeout_s=float(cfg.get("capture_timeout_s", 15)),
        max_problems=int(cfg.get("max_problems", 0)),
        max_consecutive_errors=int(cfg.get("max_consecutive_errors", 3)),
        ui_points=points,
        ledger_path=str(cfg.get("ledger_path") or os.path.join(home, ".katrain", "tsumego_ledger.jsonl")),
        shots_dir=str(cfg.get("shots_dir") or os.path.join(home, ".katrain", "logs", "autoloop")),
    )


# --- 画面判定（純関数・PIL のみ） ---
def _box(frame, ratio_box):
    w, h = frame.size
    x0, y0, x1, y1 = ratio_box
    return int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)


def yellow_ratio(frame, ratio_box):
    x0, y0, x1, y1 = _box(frame, ratio_box)
    px = frame.load()
    n = t = 0
    for y in range(y0, y1):
        for x in range(x0, x1, 2):
            t += 1
            if _is_yellow(*px[x, y][:3]):
                n += 1
    return n / t if t else 0.0


def popup_present(frame):
    """結果ポップアップが盤を覆っているか（大盤の上端の帯が黄色でなくなる）"""
    return yellow_ratio(frame, POPUP_STRIP) < POPUP_STRIP_YELLOW_MAX


def _dark_bbox(frame, ratio_box):
    x0, y0, x1, y1 = _box(frame, ratio_box)
    px = frame.load()
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y][:3]
            if r + g + b < VERDICT_DARK_SUM:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def verdict_tail(frame):
    """判定文の右端に寄せた切り出し（グレースケール）。文字が無ければ None"""
    bbox = _dark_bbox(frame, VERDICT_BAND)
    if bbox is None:
        return None
    _x0, y0, x1, y1 = bbox
    return frame.crop((x1 + 1 - VERDICT_TAIL_W, y0 - 4, x1 + 1, y1 + 5)).convert("L")


def load_templates(dir_path=TEMPLATE_DIR):
    out = {}
    for name in ("wrong", "correct"):
        path = os.path.join(dir_path, f"popup_{name}_tail.png")
        if os.path.exists(path):
            out[name] = Image.open(path).convert("L")
    return out


def _mad(a, b):
    if a.size != b.size:
        b = b.resize(a.size)
    pa, pb = a.load(), b.load()
    w, h = a.size
    return sum(abs(pa[x, y] - pb[x, y]) for y in range(h) for x in range(w)) / float(w * h)


def popup_state(frame, templates):
    """'none'（ポップアップ無し）/ 'correct' / 'wrong' / 'unknown'"""
    if not popup_present(frame):
        return "none"
    tail = verdict_tail(frame)
    if tail is None or not templates:
        return "unknown"
    scored = sorted((_mad(tail, tpl), name) for name, tpl in templates.items())
    best_mad, best = scored[0]
    if best_mad > VERDICT_MAX_MAD:
        return "unknown"
    if len(scored) > 1 and scored[1][0] - best_mad < VERDICT_MIN_GAP:
        return "unknown"
    return best


class BoardRead(NamedTuple):
    rect: tuple
    size: int
    grid: list


def board_rect_of(frame):
    return detect_board(frame)


def read_board(frame, sizes):
    rect = detect_board(frame)
    size, grid = detect_size_and_classify(frame, rect, list(sizes))
    return BoardRead(rect, size, grid)


def board_to_device(i, j, rect, size):
    x0, y0, x1, y1 = rect
    cell_w = (x1 - x0 + 1) / size
    cell_h = (y1 - y0 + 1) / size
    return int(round(x0 + cell_w * (j + 0.5))), int(round(y0 + cell_h * (i + 0.5)))


def device_to_board(x, y, rect, size):
    x0, y0, x1, y1 = rect
    cell_w = (x1 - x0 + 1) / size
    cell_h = (y1 - y0 + 1) / size
    j = int((x - x0) / cell_w)
    i = int((y - y0) / cell_h)
    return max(0, min(size - 1, i)), max(0, min(size - 1, j))


def find_hint_circle(frame, rect, size):
    """盤の中の赤いリング（ヒント）の交点 (i, j)。無ければ None。複数（離れた赤）なら None"""
    x0, y0, x1, y1 = rect
    px = frame.load()
    xs, ys = [], []
    for y in range(y0, y1 + 1, 2):
        for x in range(x0, x1 + 1, 2):
            if _is_red(*px[x, y][:3]):
                xs.append(x)
                ys.append(y)
    if len(xs) < RED_RING_MIN_PIXELS:
        return None
    cell = (x1 - x0 + 1) / size
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    if not (cell * 0.4 <= bw <= cell * 1.3 and cell * 0.4 <= bh <= cell * 1.3):
        return None  # 1交点の大きさでない＝別の赤（複数の赤丸・UI）
    return device_to_board((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, rect, size)


def hint_enabled(frame):
    w, h = frame.size
    cx, cy, rad = int(HINT_ICON[0] * w), int(HINT_ICON[1] * h), HINT_ICON[2]
    mean = ImageStat.Stat(frame.crop((cx - rad, cy - rad, cx + rad, cy + rad)).convert("L")).mean[0]
    return mean >= HINT_ICON_ENABLED_MIN


def header_hash(frame):
    """ヘッダ（出典・番号）の帯を 32x4 グレースケールに縮めた sha1 の先頭 16 桁（同じ問題なら同じ）"""
    band = frame.crop(_box(frame, HEADER_BAND)).convert("L").resize((32, 4), Image.BILINEAR)
    return hashlib.sha1(band.tobytes()).hexdigest()[:16]


def empty_points(grid):
    return [(i, j) for i, row in enumerate(grid) for j, v in enumerate(row) if v == EMPTY]


class Vision:
    """画面判定の束（テストでは同じメソッド名のフェイクに差し替える）"""

    def __init__(self, sizes, templates=None, ui_points=None):
        self.sizes = tuple(sizes)
        self.templates = templates if templates is not None else load_templates()
        self.ui_points = ui_points or DEFAULT_UI_POINTS

    def popup_present(self, frame):
        return popup_present(frame)

    def popup_state(self, frame):
        return popup_state(frame, self.templates)

    def read_board(self, frame, size=None):
        return read_board(frame, (size,) if size else self.sizes)

    def board_rect(self, frame):
        return board_rect_of(frame)

    def find_hint_circle(self, frame, rect, size):
        return find_hint_circle(frame, rect, size)

    def hint_enabled(self, frame):
        return hint_enabled(frame)

    def header_hash(self, frame):
        return header_hash(frame)

    def ui_point(self, name, frame):
        return ui_point(name, frame.size, self.ui_points)


# --- ADB（BlueStacks 同梱 HD-Adb.exe） ---
class AdbError(Exception):
    pass


def _run_adb(args, binary=False, timeout_s=10):
    """subprocess.run の薄い包み。binary=True は stdout をそのまま返す（screencap の PNG）"""
    try:
        proc = subprocess.run(
            args, capture_output=True, timeout=timeout_s, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AdbError(f"adb 実行失敗: {e}") from e
    if binary:
        return proc.stdout
    return proc.stdout.decode("utf-8", errors="replace")


class AdbClient:
    def __init__(self, adb_path, serial, runner=None, timeout_s=10):
        self.adb_path = adb_path
        self.serial = serial
        self.runner = runner or _run_adb
        self.timeout_s = timeout_s

    def _adb(self, *args, binary=False):
        return self.runner([self.adb_path, *args], binary=binary, timeout_s=self.timeout_s)

    def connect(self):
        out = self._adb("connect", self.serial)
        return "connected" in out or "already connected" in out

    def is_device(self):
        out = self._adb("devices")
        return any(line.split("\t")[:2] == [self.serial, "device"] for line in out.splitlines())

    def screencap(self):
        data = self._adb("-s", self.serial, "exec-out", "screencap", "-p", binary=True)
        if not data:
            raise AdbError("screencap が空でした（接続を確認）")
        try:
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            raise AdbError(f"screencap を画像にできません: {e}") from e

    def tap(self, x, y):
        self._adb("-s", self.serial, "shell", "input", "tap", str(int(round(x))), str(int(round(y))))


def discover_serial(adb_path, conf_path=BLUESTACKS_CONF, runner=None):
    """bluestacks.conf の adb_port を順に connect し、devices に 'device' で現れた最初のものを返す"""
    ports = []
    try:
        with open(conf_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'bst\.instance\.[^.]+\.adb_port="(\d+)"', line.strip())
                if m and m.group(1) not in ports:
                    ports.append(m.group(1))
    except OSError:
        return None
    for port in ports:
        serial = f"127.0.0.1:{port}"
        client = AdbClient(adb_path, serial, runner=runner)
        try:
            client.connect()
            if client.is_device():
                return serial
        except AdbError:
            continue
    return None


# --- 台帳 ---
class Ledger:
    def __init__(self, path):
        self.path = path

    def append(self, record):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- 収穫（ヒント歩き） ---
HINT_WAIT_S = 1.5  # ヒント押下後に赤丸を待つ上限（spec §4.4）
MOVE_WAIT_S = 6.0  # 黒タップ後に盤が安定するまでの上限
REWIND_MAX_TAPS = 20
HARVEST_MAX_MOVES = 40
HARVEST_MAX_S = 120.0  # 収穫1問あたりの総時間上限（close/rewind が無限に粘る事態への全体締切）
CLOSE_MAX_TAPS = 5  # ポップアップが閉じ続ける場合の打ち切り


def white_reply(expected, observed):
    """expected（黒を打った直後の盤）と observed の差が「白 1 手」で説明できればその (i,j)。
    差が無ければ None、説明できなければ False"""
    if observed == expected:
        return None
    size = len(expected)
    for i in range(size):
        for j in range(size):
            if expected[i][j] == EMPTY and observed[i][j] == WHITE:
                if apply_move_to_grid(expected, i, j, WHITE) == observed:
                    return (i, j)
                return False
    return False


class Harvester:
    """不正解後のヒント歩き。step(frame) を繰り返し呼ぶ（1 回 = 1 フレーム・待ちは deadline で表現）。"""

    def __init__(self, adb, vision, base_grid, size, settle_ms, clock, log):
        self.adb, self.vision, self.base, self.size = adb, vision, [r[:] for r in base_grid], size
        self.settle_s = settle_ms / 1000.0
        self.clock, self.log = clock, log
        self.phase = "close"
        self.grid = None
        self.moves = []
        self.rewind_taps = 0
        self.close_taps = 0
        self.deadline = 0.0
        self.deadline_all = self.clock() + HARVEST_MAX_S
        self.not_before = 0.0
        self.pending = None  # (i, j, expected_grid)
        self.last_obs = None
        self.hint_retry = 0
        self.gray_seen = 0

    def _tap_named(self, name, frame):
        self.adb.tap(*self.vision.ui_point(name, frame))
        self.not_before = self.clock() + self.settle_s

    def _fail(self, reason):
        self.log(f"[Harvester] failed: {reason}")
        return "failed", reason

    def step(self, frame):
        now = self.clock()
        if now >= self.deadline_all:
            return self._fail("harvest: 時間切れ")
        if now < self.not_before:
            return "running", None
        if self.phase == "close":
            if self.vision.popup_present(frame):
                if self.close_taps >= CLOSE_MAX_TAPS:
                    return self._fail("close: ポップアップが閉じません")
                self.close_taps += 1
                self._tap_named("popup_view", frame)
                return "running", None
            self.phase = "rewind"
        if self.phase == "rewind":
            try:
                grid = self.vision.read_board(frame, self.size).grid
            except CaptureError:
                return "running", None
            if grid == self.base:
                self.grid = [r[:] for r in grid]
                self.phase = "hint"
            else:
                if self.rewind_taps >= REWIND_MAX_TAPS:
                    return self._fail("rewind: 初期局面に戻せません")
                self.rewind_taps += 1
                self._tap_named("bar_undo", frame)
                return "running", None
        if self.phase == "hint":
            if len(self.moves) >= HARVEST_MAX_MOVES:
                return self._fail("hint: 手数上限")
            self._tap_named("bar_hint", frame)
            self.deadline = self.not_before + HINT_WAIT_S
            self.gray_seen = 0
            self.phase = "wait_hint"
            return "running", None
        if self.phase == "wait_hint":
            rect = self.vision.board_rect(frame)
            pt = self.vision.find_hint_circle(frame, rect, self.size)
            if pt is not None:
                self.gray_seen = 0
                i, j = pt
                expected = apply_move_to_grid(self.grid, i, j, BLACK)
                if expected is None:
                    return self._fail(f"hint: 赤丸 {pt} に打てません")
                self.adb.tap(*board_to_device(i, j, rect, self.size))
                self.pending = (i, j, expected)
                self.last_obs = None
                self.not_before = self.clock() + self.settle_s
                self.deadline = self.not_before + MOVE_WAIT_S
                self.phase = "wait_move"
                return "running", None
            if now >= self.deadline:
                if not self.vision.hint_enabled(frame):
                    self.gray_seen += 1
                    if self.gray_seen < 2:
                        return "running", None  # 誤読対策: ヒント灰読みは2連続要求
                    if not self.moves:
                        return self._fail("hint: 手順が取れません")
                    self.log(f"[Harvester] done: {len(self.moves)} 手")
                    return "done", list(self.moves)
                if self.hint_retry < 1:
                    self.hint_retry += 1
                    self.phase = "hint"  # もう 1 回だけ押し直す
                    return "running", None
                return self._fail("hint: 赤丸が出ません（ヒントは有効のまま）")
            return "running", None
        if self.phase == "wait_move":
            i, j, expected = self.pending
            try:
                obs = self.vision.read_board(frame, self.size).grid
            except CaptureError:
                obs = None
            # 盤が変化して2フレーム安定したら受理する（obs[i][j]==BLACK に限定しない）。
            # 投げ込み・ナカデ捨て石は白の応手が黒自身を取るため、その黒点は EMPTY のまま
            # 戻ってこない。白の応手は white_reply（apply_move_to_grid 由来）が判定する。
            if obs is not None and obs != self.grid and obs == self.last_obs:
                w = white_reply(expected, obs)
                if w is False:
                    return self._fail(f"diff: 黒 {(i, j)} の後の盤を説明できません")
                self.moves.append(((i, j), BLACK))
                if w is not None:
                    self.moves.append((w, WHITE))
                self.grid = [r[:] for r in obs]
                self.pending = None
                self.hint_retry = 0
                self.phase = "hint"
                return "running", None
            self.last_obs = obs
            if now >= self.deadline:
                return self._fail(f"move: 黒 {(i, j)} が盤に現れません")
            return "running", None
        return self._fail(f"unknown phase {self.phase}")


# --- 状態機械 ---
STALL_EXTRA_S = 60.0  # STALLED からポップアップをさらに待つ秒数
CAPTURE_FAILED_WAIT_S = 45.0  # CAPTURE_FAILED でポップアップ（結果）を待つ秒数
FRAME_FAIL_RECONNECT = 3
FRAME_FAIL_GIVEUP = 6
MAX_TAPS_PER_PROBLEM = 60  # 1問あたりのタップ上限（spec §9）


class _Problem:
    def __init__(self, token, base_grid, key, route, started):
        self.token, self.base, self.key, self.route, self.started = token, base_grid, key, route, started
        self.size = len(base_grid) if base_grid else None
        self.n_black = 0
        self.rect = None


class AutoLoopController:
    def __init__(self, adb, vision, gui, settings, ledger, clock=time.monotonic):
        self.adb, self.vision, self.gui, self.settings, self.ledger, self.clock = adb, vision, gui, settings, ledger, clock
        self.state = "IDLE"
        self.stats = {"problems": 0, "correct": 0, "wrong": 0, "harvested": 0, "failed": 0}
        self._events = queue.Queue()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.problem = None
        self.harvester = None
        self.last_initial = None
        self.last_final = None
        self._await_prev = None
        self._await_retapped = False
        self._deadline = 0.0
        self._not_before = 0.0
        self._frame_failures = 0
        self._errors = 0
        self._cf_tapped = False
        self._cf_base = None
        self._pending_taps = []
        self._shots = []
        self._shot_seq = 0

    # --- スレッド ---
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def activate(self):
        """状態だけ AWAIT_PROBLEM にする（テスト・start から使う）"""
        self.state = "AWAIT_PROBLEM"
        self.stats = {"problems": 0, "correct": 0, "wrong": 0, "harvested": 0, "failed": 0}
        self._errors = 0
        self._await_prev = None
        self._await_retapped = False
        self._deadline = self.clock() + self.settings.answer_timeout_s
        self._shots = []

    def start(self):
        self._stop.clear()
        self.activate()
        self._thread = threading.Thread(target=self._run, name="tsumego-autoloop", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self.state = "IDLE"
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)

    def _run(self):
        me = threading.current_thread()
        exc_count = 0
        while not self._stop.is_set() and self._thread is me:
            try:
                self.step()
                exc_count = 0
            except Exception as e:  # 1 周の例外でスレッドを落とさない
                exc_count += 1
                self.gui.log(f"autoloop: step で例外: {e!r}")
                if exc_count >= 10:
                    self._to_idle("step の例外が続くため停止しました")
            self._wake.wait(self.settings.poll_ms / 1000.0)
            self._wake.clear()

    # --- GUI からのイベント ---
    def on_problem_ready(self, token, base_grid, key, route):
        self._events.put(("problem_ready", token, base_grid, key, route))
        self._wake.set()

    def on_capture_failed(self, message):
        self._events.put(("capture_failed", message))
        self._wake.set()

    def on_black_move(self, token, coords_xy):
        if coords_xy is None:
            return
        self._events.put(("black_move", token, coords_xy))
        self._wake.set()

    # --- 1 周 ---
    def step(self):
        if self.state == "IDLE":
            return
        self._drain_events()
        if self.state == "IDLE" or self.clock() < self._not_before:
            return
        try:
            frame = self.adb.screencap()
            self._frame_failures = 0
        except Exception as e:
            self._frame_failures += 1
            if self._frame_failures == FRAME_FAIL_RECONNECT:
                self.gui.log(f"autoloop: 画面取得に連続失敗、ADB へ再接続します（{e}）")
                try:
                    self.adb.connect()
                except Exception:
                    pass
            if self._frame_failures >= FRAME_FAIL_GIVEUP:
                self._fail("adb: 画面が取れません", frame=None)
                self._to_idle("ADB から画面が取れないため停止しました")
            return
        getattr(self, f"_step_{self.state.lower()}")(frame)

    def _drain_events(self):
        while True:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                return
            kind = ev[0]
            if kind == "problem_ready":
                if self.state == "CAPTURING":
                    _k, token, base_grid, key, route = ev
                    self.problem = _Problem(token, base_grid, key, route, self.clock())
                    self.stats["problems"] += 1
                    self._shots = []
                    self.state = "ANSWERING"
                    self.gui.notify("info", self._banner("解答中"))
                else:
                    self.gui.log(f"autoloop: problem_ready を無視しました（state={self.state}）")
            elif kind == "capture_failed":
                if self.state == "CAPTURING":
                    self.gui.log(f"autoloop: キャプチャ失敗 → わざと1手打って収穫に回します（{ev[1]}）")
                    self._enter_capture_failed()
                else:
                    self.gui.log(f"autoloop: capture_failed を無視しました（state={self.state}）")
            elif kind == "black_move":
                _k, token, coords_xy = ev
                if self.state == "ANSWERING" and self.problem is not None and token == self.problem.token:
                    self._pending_taps.append(coords_xy)
                else:
                    self.gui.log(f"autoloop: black_move を無視しました（state={self.state}, token={token}）")

    def _step_await_problem(self, frame):
        if self.vision.popup_present(frame):
            self.state = "NEXT"
            return
        try:
            grid = self.vision.read_board(frame).grid
        except CaptureError:
            grid = None
        has_stones = grid is not None and any(v != EMPTY for row in grid for v in row)
        if grid is None or not has_stones or grid == self.last_initial or grid == self.last_final:
            self._await_prev = None
        elif grid == self._await_prev:
            self._await_prev = None
            self._pending_taps = []
            self.state = "CAPTURING"
            self._deadline = self.clock() + self.settings.capture_timeout_s
            self.gui.trigger_capture()
            return
        else:
            self._await_prev = grid  # 2 フレーム連続で同じになるまで待つ
        self._check_await_deadline(frame)

    def _check_await_deadline(self, frame):
        """出題（NEXT のタップ）を検出できないまま長時間 AWAIT_PROBLEM に留まっていないか。
        1 回目の締切超過で「次の問題」を再タップ、2 回目で _error_step に回す（bounded loop）。"""
        if self.clock() < self._deadline:
            return
        if not self._await_retapped:
            self.gui.log("autoloop: 出題を検出できません。「次の問題」を再タップします")
            self._tap(*self.vision.ui_point("bar_next", frame))
            self._await_retapped = True
        else:
            self._error_step("await_problem: 出題を検出できません")
            self._await_retapped = False
        self._deadline = self.clock() + self.settings.answer_timeout_s

    def _step_capturing(self, frame):
        if self.clock() >= self._deadline:
            self.gui.log("autoloop: キャプチャ完了の通知が来ません（timeout）→ CAPTURE_FAILED")
            self._enter_capture_failed()

    def _step_answering(self, frame):
        p = self.problem
        if self.vision.popup_present(frame):
            self.state = "RESULT"
            return
        # 締切チェックは pending_taps の処理より前に置く: board_rect が読めない盤が
        # 続く場合でも（pending_taps が残ったままでも）STALLED に必ず抜けられるようにする
        if self.clock() - p.started > self.settings.answer_timeout_s:
            self.state = "STALLED"
            self._deadline = self.clock() + STALL_EXTRA_S
            self._save_shot(frame, "stalled")
            return
        if self._pending_taps:
            if p.n_black >= MAX_TAPS_PER_PROBLEM:
                self._pending_taps = []
                self._save_shot(frame, "tap_cap")
                self.gui.log(f"autoloop: 1問あたりのタップ上限（{MAX_TAPS_PER_PROBLEM}）に達しました")
                self.state = "STALLED"
                self._deadline = self.clock() + STALL_EXTRA_S
                return
            try:
                p.rect = self.vision.board_rect(frame)
            except CaptureError:
                return  # 次のフレームで
            for coords_xy in self._pending_taps:
                i, j = move_to_grid(coords_xy, p.size)
                self._tap(*board_to_device(i, j, p.rect, p.size))
                p.n_black += 1
            self._pending_taps = []
            return

    def _step_result(self, frame):
        verdict = self.vision.popup_state(frame)
        p = self.problem
        if verdict == "none":
            self._record(p, "unknown_popup", harvest="skipped:popup_vanished")
            self.state = "NEXT"  # ポップアップが消えた（ユーザー操作等）
            return
        if verdict == "wrong":
            self.stats["wrong"] += 1
            self._errors = 0
            self.gui.stop_watch()
            base = p.base if (p and p.base) else self._cf_base
            if base is None:
                self._save_shot(frame, "wrong_nobase")
                self._record(p, "wrong", harvest="skipped:盤が読めていない")
                self.state = "NEXT"
                return
            self.harvester = Harvester(self.adb, self.vision, base, len(base), self.settings.settle_ms, self.clock, self.gui.log)
            self.state = "HARVEST"
            self.gui.notify("info", self._banner("収穫中"))
            return
        if verdict == "unknown":
            self._save_shot(frame, "unknown_popup")
        self.stats["correct"] += 1
        self._errors = 0
        self._record(p, "correct" if verdict == "correct" else "unknown_popup")
        self.state = "NEXT"

    def _enter_capture_failed(self):
        self.state = "CAPTURE_FAILED"
        self.problem = _Problem(None, None, None, None, self.clock())
        self.stats["problems"] += 1  # キャプチャ失敗も 1 問（max_problems の対象）
        self._shots = []
        self._cf_tapped = False
        self._cf_base = None
        self._deadline = self.clock() + CAPTURE_FAILED_WAIT_S

    def _step_capture_failed(self, frame):
        if self.vision.popup_present(frame):
            p = self.problem
            p.base = self._cf_base
            if p.base:
                p.size = len(p.base)
            self.state = "RESULT"
            return
        if not self._cf_tapped:
            try:
                read = self.vision.read_board(frame)
                self._cf_base = [r[:] for r in read.grid]
                empties = empty_points(read.grid)
                if empties:
                    i, j = empties[0]
                    self._tap(*board_to_device(i, j, read.rect, read.size))
            except CaptureError:
                self._save_shot(frame, "capture_failed")
                w, h = frame.size
                self._tap(w // 2, int(h * 0.46))
            self._cf_tapped = True
            return
        if self.clock() >= self._deadline:
            self._record(self.problem, "capture_failed", harvest="skipped:ポップアップが出ない")
            self._error_step("capture_failed: 結果が出ません")
            if self.state != "IDLE":  # _error_step が上限で IDLE にしていたら上書きしない
                self.state = "NEXT"

    def _step_harvest(self, frame):
        status, payload = self.harvester.step(frame)
        if status == "running":
            return
        p = self.problem
        if status == "done":
            base = p.base if (p and p.base) else self._cf_base
            added, n = self.gui.save_line(base, payload)
            self.stats["harvested"] += 1
            self._record(p, "wrong", harvest="saved" if added else "duplicate", line_len=n)
            self.gui.notify("save", f"正解手順を回答帳に保存しました（{n}手）")
        else:
            self._save_shot(frame, "harvest_failed")
            self._record(p, "wrong", harvest=f"skipped:{payload}")
            self.gui.log(f"autoloop: 収穫失敗: {payload}")
        self.harvester = None
        self.state = "NEXT"

    def _step_stalled(self, frame):
        if self.vision.popup_present(frame):
            self.state = "RESULT"
            return
        if self.clock() >= self._deadline:
            self._record(self.problem, "stalled")
            self._error_step("stalled: 結果が出ません")
            if self.state != "IDLE":
                self.state = "NEXT"

    def _step_next(self, frame):
        try:
            self.last_final = self.vision.read_board(frame).grid
        except CaptureError:
            pass
        if self.problem is not None and self.problem.base:
            self.last_initial = self.problem.base
        name = "popup_next" if self.vision.popup_present(frame) else "bar_next"
        self._tap(*self.vision.ui_point(name, frame))
        self.problem = None
        self._cf_base = None
        self._not_before = self.clock() + max(self.settings.settle_ms, 300) / 1000.0
        if self.settings.max_problems and self.stats["problems"] >= self.settings.max_problems:
            self._to_idle(f"{self.settings.max_problems} 問に達したため停止しました")
            return
        self.state = "AWAIT_PROBLEM"
        self._await_prev = None
        self._await_retapped = False
        self._deadline = self.clock() + self.settings.answer_timeout_s

    # --- 補助 ---
    def _tap(self, x, y):
        try:
            self.adb.tap(x, y)
            return True
        except AdbError as e:
            self.gui.log(f"autoloop: タップ失敗: {e}")
            return False

    def _error_step(self, why):
        self._errors += 1
        self.stats["failed"] += 1
        self.gui.log(f"autoloop: {why}（連続 {self._errors}）")
        if self._errors >= self.settings.max_consecutive_errors:
            self._to_idle(f"連続 {self._errors} 回失敗したため停止しました（{why}）")

    def _fail(self, why, frame):
        if frame is not None:
            self._save_shot(frame, "error")
        self._record(self.problem, "error", harvest=f"skipped:{why}")

    def _to_idle(self, text):
        self.state = "IDLE"
        self.gui.notify("warn", f"自動ループ: {text}")
        self.gui.log(f"autoloop: {text}")

    def _banner(self, what):
        s = self.stats
        return f"自動ループ: {what}（{s['problems']}問目 正解 {s['correct']} / 誤答 {s['wrong']} / 収穫 {s['harvested']}）"

    def _record(self, p, outcome, harvest=None, line_len=None):
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "key": p.key if p else None,
            "size": p.size if p else None,
            "route": p.route if p else None,
            "outcome": outcome,
            "elapsed_s": round(self.clock() - p.started, 1) if p else None,
            "n_black": p.n_black if p else 0,
            "harvest": harvest,
            "line_len": line_len,
            "shots": list(self._shots),
        }
        try:
            self.ledger.append(rec)
        except Exception as e:
            self.gui.log(f"autoloop: 台帳に書けません: {e}")

    def _save_shot(self, frame, tag):
        """スクショを保存しパスを返す（保存できなければ None）。self._shots にも積む。
        ファイル名は per-process カウンタで一意にする（同一秒内の複数保存の衝突回避）"""
        if not hasattr(frame, "save"):
            return None
        try:
            os.makedirs(self.settings.shots_dir, exist_ok=True)
            self._shot_seq += 1
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.settings.shots_dir, f"{ts}_{self._shot_seq:03d}_{tag}.png")
            frame.save(path)
            self._shots.append(path)
            return path
        except Exception as e:
            self.gui.log(f"autoloop: スクショ保存失敗: {e}")
            return None


def main(argv=None):
    """手動確認用 CLI: probe（画面状態を出す）/ tap <name>|<x> <y> / shot <path>"""
    import argparse

    p = argparse.ArgumentParser(prog="python -m katrain.core.tsumego_autoloop")
    p.add_argument("cmd", choices=["probe", "tap", "shot"])
    p.add_argument("args", nargs="*")
    p.add_argument("--adb", default=DEFAULT_ADB_PATH)
    p.add_argument("--serial", default="")
    a = p.parse_args(argv)
    serial = a.serial or discover_serial(a.adb)
    if not serial:
        print("ADB デバイスが見つかりません（BlueStacks 設定で ADB を ON にして再起動）")
        return 2
    adb = AdbClient(a.adb, serial)
    if a.cmd == "shot":
        adb.screencap().save(a.args[0])
        print("saved", a.args[0])
        return 0
    if a.cmd == "tap":
        frame = adb.screencap()
        if len(a.args) == 1:
            x, y = ui_point(a.args[0], frame.size)
        else:
            x, y = int(a.args[0]), int(a.args[1])
        adb.tap(x, y)
        print("tapped", x, y)
        return 0
    frame = adb.screencap()
    vision = Vision((9, 13, 19))
    print("serial", serial, "frame", frame.size)
    print("popup_present", vision.popup_present(frame), "popup_state", vision.popup_state(frame))
    print("hint_enabled", vision.hint_enabled(frame), "header", vision.header_hash(frame))
    try:
        read = vision.read_board(frame)
        print("board", read.rect, "size", read.size, "stones", sum(v != EMPTY for row in read.grid for v in row))
        print("hint_circle", vision.find_hint_circle(frame, read.rect, read.size))
    except CaptureError as e:
        print("board: 読めません:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
