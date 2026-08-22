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
