# 詰碁の自動ループ（tsumego autoloop）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BlueStacks 上の「囲碁詰めチャレ」を ADB で操作し、出題→回答→正誤→（誤答なら）ヒント歩きで回答帳へ自動記録→次の問題、を人力ゼロで回す。

**Architecture:** 新モジュール `katrain/core/tsumego_autoloop.py`（Kivy 非依存）に ADB クライアント・画面判定（PIL のみ）・収穫（ヒント歩き）・状態機械・台帳を置き、`__main__.py` には接続点だけ足す（ホットキー／キャプチャ起動／キャプチャ完了・失敗通知／AI 黒の着手フック／回答帳保存の関数切り出し）。白の応手の取り込みは既存 `BoardWatcher` のまま。解析・選択則には触れない。

**Tech Stack:** Python 3.12 / PIL（ImageStat・ImageGrab は既存）/ subprocess（`HD-Adb.exe`）/ pytest。numpy・OpenCV・OCR は**使わない**（環境に無い）。

**Spec:** `docs/superpowers/specs/2026-08-23-tsumego-autoloop-design.md`

## Global Constraints

- 依存追加なし（PIL のみ）。`import numpy` / `import cv2` を書かない
- `katrain/core/tsumego_autoloop.py` は Kivy / KataGo / `__main__` を import しない（テストから直接 import する）
- ADB フレームはデバイス解像度 **900×1600**（比率座標の基準。テンプレートもこの解像度）
- UI 座標は**比率**（0..1）。既定値は spec §4.1（`bar_next (0.472,0.784)` / `bar_hint (0.833,0.784)` / `bar_undo (0.933,0.784)` / `popup_next (0.256,0.781)` / `popup_view (0.489,0.781)`）
- ホットキー既定 `ctrl+alt+a`。`Theme.KEY_*` と重ねない（F キー禁止）
- 収穫の終了条件は「ヒント押下後 1.5 秒以内に赤丸が出ない **かつ** ヒントアイコンがグレー」
- unknown ポップアップは**正解扱いで NEXT**（収穫を走らせない側）
- 台帳 `~/.katrain/tsumego_ledger.jsonl` は追記のみ。スクショは失敗系のときだけ `~/.katrain/logs/autoloop/` へ
- コミットメッセージは日本語・Conventional Commits。`black` を既存ファイル全体に掛けない（差分が巨大化する）
- **ユーザーのローカル `C:\Users\iwaki\.katrain\config.json` の編集はメインセッションで直接 Edit する**（サブエージェントに委任しない。KaTrain 起動中に編集すると終了時に上書きで消えるので、起動していないことを確認してから）
- 座標規約: 認識グリッド `grid[i][j]` は i=上から（top origin）、KaTrain の `Move.coords=(x,y)` は y=下から。変換は `board_watch.move_to_grid` / `grid_to_move` を必ず通す

## ファイル構成

| ファイル | 役割 |
|---|---|
| `katrain/core/tsumego_autoloop.py`（新規） | 設定・比率座標・画面判定（純関数＋`Vision`）・`AdbClient`・`Ledger`・`Harvester`・`AutoLoopController`・CLI（`python -m katrain.core.tsumego_autoloop probe`） |
| `katrain/img/autoloop/popup_wrong_tail.png`（新規）・`popup_correct_tail.png`（Task 6 で取得） | 判定文テンプレート（900×1600 のフレームから切り出し） |
| `tests/data/autoloop/problem.png` / `hint.png` / `popup_wrong.png`（このプランのコミットで追加済み） | 実フレーム（2026-08-23 取得）。Task 6 で `popup_correct.png` / `hint_disabled.png` を追加 |
| `tests/test_tsumego_autoloop.py`（新規） | 純関数・ADB フェイク・Harvester・状態機械のテスト |
| `katrain/__main__.py`（変更） | ホットキー表・`_autoloop_trigger`・`_save_answer_line` 切り出し・3 フック |
| `katrain/config.json` と `~/.katrain/config.json`（変更） | `tsumego_autoloop` セクション |
| `CLAUDE.md` / `.claude/rules/tsumego.md` / spec 追記（変更） | 運用メモ |

---

### Task 1: 設定・比率座標・画面判定の純関数（実フレームで固定）

**Files:**
- Create: `katrain/core/tsumego_autoloop.py`
- Create: `katrain/img/autoloop/popup_wrong_tail.png`（スクリプトで生成）
- Test: `tests/test_tsumego_autoloop.py`
- Fixtures（既に存在）: `tests/data/autoloop/problem.png`（問題画面・ヒント有効）、`hint.png`（赤丸あり・(i,j)=(2,9)）、`popup_wrong.png`（不正解ポップアップ）

**Interfaces（Produces）:**
- `DEFAULT_UI_POINTS: dict[str, tuple[float,float]]`、`ui_point(name, frame_size, ui_points=None) -> (int,int)`
- `AutoLoopSettings(NamedTuple)` と `autoloop_settings_from_config(cfg: dict|None) -> AutoLoopSettings`
- `yellow_ratio(frame, box_ratio) -> float`、`popup_present(frame) -> bool`
- `load_templates(dir_path=TEMPLATE_DIR) -> dict[str, Image]`、`popup_state(frame, templates) -> "none"|"correct"|"wrong"|"unknown"`
- `BoardRead(NamedTuple: rect, size, grid)`、`read_board(frame, sizes) -> BoardRead`（失敗は `CaptureError`）、`board_rect_of(frame) -> rect`
- `board_to_device(i, j, rect, size) -> (int,int)`、`device_to_board(x, y, rect, size) -> (int,int)`
- `find_hint_circle(frame, rect, size) -> (i,j)|None`、`hint_enabled(frame) -> bool`、`header_hash(frame) -> str`、`empty_points(grid) -> list[(i,j)]`
- `class Vision(sizes, templates)`: 上の関数を束ねたメソッド群（`popup_present/popup_state/read_board/board_rect/find_hint_circle/hint_enabled/header_hash/ui_point`）

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_tsumego_autoloop.py
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
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q`
Expected: FAIL（`ModuleNotFoundError: katrain.core.tsumego_autoloop`）

- [ ] **Step 3: モジュールの骨格と純関数を実装**

```python
# katrain/core/tsumego_autoloop.py
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
```

- [ ] **Step 4: 不正解テンプレートを生成**

```bash
mkdir -p katrain/img/autoloop
python - <<'EOF'
from PIL import Image
from katrain.core import tsumego_autoloop as al
f = Image.open("tests/data/autoloop/popup_wrong.png").convert("RGB")
tail = al.verdict_tail(f)
assert tail is not None and tail.size[0] == al.VERDICT_TAIL_W, tail
tail.save("katrain/img/autoloop/popup_wrong_tail.png")
print(tail.size)
EOF
```
Expected: `(140, 39)` 前後（高さは文字 bbox + 9）。画像を開いて「でした・・」の末尾が入っていることを目視。

- [ ] **Step 5: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q`
Expected: 全件 PASS。`test_hint_enabled_on_problem_frame` が落ちる場合はアイコン中心の実測（`ImageStat` の平均 151 付近）を見て `HINT_ICON` の cy を ±0.01 調整する（テストの方を緩めない）。`test_popup_state_wrong_template` が落ちる場合は `verdict_tail` が返す bbox を print して `VERDICT_BAND` の y を合わせる。

- [ ] **Step 6: コミット**

```bash
git add katrain/core/tsumego_autoloop.py katrain/img/autoloop/popup_wrong_tail.png tests/test_tsumego_autoloop.py
git commit -m "feat(autoloop): 詰碁自動ループの画面判定（ポップアップ・赤丸・ヒント有効・盤座標）と設定を追加"
```

---

### Task 2: ADB クライアントと CLI（probe / tap）

**Files:**
- Modify: `katrain/core/tsumego_autoloop.py`（末尾に追記）
- Test: `tests/test_tsumego_autoloop.py`

**Interfaces:**
- Consumes: Task 1 の `Vision`, `read_board`, `DEFAULT_ADB_PATH`, `BLUESTACKS_CONF`
- Produces: `class AdbClient(adb_path, serial, runner=None, timeout_s=10)` with `connect() -> bool`, `is_device() -> bool`, `screencap() -> Image`, `tap(x, y) -> None`（失敗は `AdbError`）; `discover_serial(adb_path, conf_path=BLUESTACKS_CONF, runner=None) -> str|None`; `class AdbError(Exception)`; `main(argv)`（`probe` / `tap <name|x y>` / `shot <path>`）

- [ ] **Step 1: 失敗するテストを書く**

```python
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
    runner = FakeRunner({"connect 127.0.0.1:5585": "connected to 127.0.0.1:5585",
                         "devices": "List of devices attached\n127.0.0.1:5585\tdevice\n"})
    assert al.discover_serial("HD-Adb.exe", str(conf), runner=runner) == "127.0.0.1:5585"


def test_discover_serial_none_when_nothing_answers(tmp_path):
    conf = tmp_path / "bluestacks.conf"
    conf.write_text('bst.instance.Pie64.adb_port="5555"\n', encoding="utf-8")
    assert al.discover_serial("HD-Adb.exe", str(conf), runner=FakeRunner()) is None
```

（ファイル先頭の import に `import io` を足す）

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q -k adb`
Expected: FAIL（`AttributeError: ... AdbClient`）

- [ ] **Step 3: 実装**

```python
# --- ADB（BlueStacks 同梱 HD-Adb.exe） ---
class AdbError(Exception):
    pass


def _run_adb(args, binary=False, timeout_s=10):
    """subprocess.run の薄い包み。binary=True は stdout をそのまま返す（screencap の PNG）"""
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout_s,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q`
Expected: 全件 PASS

- [ ] **Step 5: 実機で probe（BlueStacks が起動していれば）**

Run: `python -m katrain.core.tsumego_autoloop probe`
Expected: `popup_present False/True`・`board (…) size 13`・`hint_enabled True` のように出る。デバイスが無ければ終了コード 2 で文言が出る（それでもテストは独立に通る）。

- [ ] **Step 6: コミット**

```bash
git add katrain/core/tsumego_autoloop.py tests/test_tsumego_autoloop.py
git commit -m "feat(autoloop): ADB クライアント（connect/devices/screencap/tap・ポート自動探索）と probe CLI を追加"
```

---

### Task 3: 台帳と収穫（ヒント歩き）

**Files:**
- Modify: `katrain/core/tsumego_autoloop.py`
- Test: `tests/test_tsumego_autoloop.py`

**Interfaces:**
- Consumes: `apply_move_to_grid`（board_watch）、Task 1 の `Vision` 相当、Task 2 の `AdbClient` 相当（`tap` だけ使う）
- Produces: `class Ledger(path)` with `append(record: dict)`; `white_reply(expected, observed) -> (i,j)|None|False`（None=応手なし、False=説明できない差分）; `class Harvester(adb, vision, base_grid, size, settle_ms, clock, log)` with `step(frame) -> (status, payload)`（status: `"running"` / `"done"`（payload=moves）/ `"failed"`（payload=理由文字列））。moves は `[((i,j),"B"|"W"), ...]`

- [ ] **Step 1: 失敗するテストを書く**

```python
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
    g1 = al.apply_move_to_grid(base, 1, 1, "B")          # 黒 (1,1)
    g2 = al.apply_move_to_grid(g1, 0, 0, "W")            # 白 (0,0)
    g3 = al.apply_move_to_grid(g2, 2, 2, "B")            # 黒 (2,2)＝最終手（白応じず）
    # 1 フレーム = 1 step。phase "hint" はヒントを押して running を返す（赤丸は次のフレームで読む）ので、
    # 赤丸つきフレームはヒント押下フレームの**次**に置く
    frames = [
        {"popup": True},                                  # close: 問題を見る
        {"grid": g3},                                     # rewind: 最終局面 → 戻す
        {"grid": base},                                   # rewind: 初期局面 → hint: ヒント押下
        {"grid": base, "hint": (1, 1)},                   # wait_hint: 赤丸 → 黒タップ
        {"grid": g2}, {"grid": g2},                       # wait_move: 黒+白 安定 2 フレーム → 手順追記
        {"grid": g2},                                     # hint: ヒント押下
        {"grid": g2, "hint": (2, 2)},                     # wait_hint: 赤丸 → 黒タップ
        {"grid": g3}, {"grid": g3},                       # wait_move: 黒のみ 安定 → 手順追記
        {"grid": g3},                                     # hint: ヒント押下
        {"grid": g3, "hint": None, "hint_on": True},      # wait_hint: まだ 1.5 秒以内
    ]
    st, payload = _run_harvest(h, frames)
    assert st == "running"
    clock.advance(2.0)                                    # 1.5 秒経過・赤丸なし・ヒント灰 → 終了
    st, payload = h.step({"grid": g3, "hint": None, "hint_on": False})
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
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q -k "ledger or white_reply or harvester"`
Expected: FAIL（`AttributeError: Ledger`）

- [ ] **Step 3: 実装**

```python
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
        self.deadline = 0.0
        self.not_before = 0.0
        self.pending = None  # (i, j, expected_grid)
        self.last_obs = None
        self.hint_retry = 0

    def _tap_named(self, name, frame):
        self.adb.tap(*self.vision.ui_point(name, frame))
        self.not_before = self.clock() + self.settle_s

    def step(self, frame):
        now = self.clock()
        if now < self.not_before:
            return "running", None
        if self.phase == "close":
            if self.vision.popup_present(frame):
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
                    return "failed", "rewind: 初期局面に戻せません"
                self.rewind_taps += 1
                self._tap_named("bar_undo", frame)
                return "running", None
        if self.phase == "hint":
            if len(self.moves) >= HARVEST_MAX_MOVES:
                return "failed", "hint: 手数上限"
            self._tap_named("bar_hint", frame)
            self.deadline = self.clock() + HINT_WAIT_S
            self.phase = "wait_hint"
            return "running", None
        if self.phase == "wait_hint":
            rect = self.vision.board_rect(frame)
            pt = self.vision.find_hint_circle(frame, rect, self.size)
            if pt is not None:
                i, j = pt
                expected = apply_move_to_grid(self.grid, i, j, BLACK)
                if expected is None:
                    return "failed", f"hint: 赤丸 {pt} に打てません"
                self.adb.tap(*board_to_device(i, j, rect, self.size))
                self.pending = (i, j, expected)
                self.last_obs = None
                self.deadline = self.clock() + MOVE_WAIT_S
                self.not_before = self.clock() + self.settle_s
                self.phase = "wait_move"
                return "running", None
            if now >= self.deadline:
                if not self.vision.hint_enabled(frame):
                    return "done", list(self.moves)
                if self.hint_retry < 1:
                    self.hint_retry += 1
                    self.phase = "hint"  # もう 1 回だけ押し直す
                    return "running", None
                return "failed", "hint: 赤丸が出ません（ヒントは有効のまま）"
            return "running", None
        if self.phase == "wait_move":
            i, j, expected = self.pending
            try:
                obs = self.vision.read_board(frame, self.size).grid
            except CaptureError:
                obs = None
            if obs is not None and obs[i][j] == BLACK and obs == self.last_obs:
                w = white_reply(expected, obs)
                if w is False:
                    return "failed", f"diff: 黒 {(i, j)} の後の盤を説明できません"
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
                return "failed", f"move: 黒 {(i, j)} が盤に現れません"
            return "running", None
        return "failed", f"unknown phase {self.phase}"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q`
Expected: 全件 PASS。`test_harvester_walks_hints_and_returns_line` の最後で `FakeClock.advance(2.0)` 後に `done` になること（`wait_hint` の deadline 判定は `now` で行う）。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/tsumego_autoloop.py tests/test_tsumego_autoloop.py
git commit -m "feat(autoloop): 台帳（jsonl）と収穫（ヒント歩き→黒白の手順）を追加"
```

---

### Task 4: 状態機械 `AutoLoopController`

**Files:**
- Modify: `katrain/core/tsumego_autoloop.py`
- Test: `tests/test_tsumego_autoloop.py`

**Interfaces:**
- Consumes: Task 1〜3 すべて
- Produces: `class AutoLoopController(adb, vision, gui, settings, ledger, clock=time.monotonic)`:
  - スレッド: `start()` / `stop()`（`running` プロパティ）
  - GUI → コントローラのイベント（どのスレッドから呼んでもよい）: `on_problem_ready(token, base_grid, key, route)`、`on_capture_failed(message)`、`on_black_move(token, coords_xy)`（KaTrain 座標 (x,y)。パスは `None`→無視）
  - `step()`（テストが直接叩く）、`state`（文字列）、`stats`（dict: problems/correct/wrong/harvested/failed）
  - `gui` は次のメソッドを持つオブジェクト: `trigger_capture()`, `save_line(base_grid, moves_grid) -> (bool, int)`, `stop_watch()`, `notify(kind, text)`, `log(text)`

- [ ] **Step 1: 失敗するテストを書く**

```python
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


def _controller(frames, tmp_path, **over):
    settings = al.autoloop_settings_from_config(
        {"poll_ms": 0, "settle_ms": 0, "ledger_path": str(tmp_path / "l.jsonl"), "shots_dir": str(tmp_path), **over}
    )
    clock = FakeClock()
    gui = FakeGui()
    adb = FrameAdb(frames)
    c = al.AutoLoopController(adb, FakeVision(3), gui, settings, al.Ledger(settings.ledger_path), clock=clock)
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
    c.step()
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
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q -k controller`
Expected: FAIL（`AttributeError: AutoLoopController`）

- [ ] **Step 3: 実装**

```python
# --- 状態機械 ---
STALL_EXTRA_S = 60.0  # STALLED からポップアップをさらに待つ秒数
FRAME_FAIL_RECONNECT = 3
FRAME_FAIL_GIVEUP = 6


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
        self._deadline = 0.0
        self._not_before = 0.0
        self._frame_failures = 0
        self._errors = 0
        self._cf_tapped = False
        self._cf_base = None
        self._pending_taps = []

    # --- スレッド ---
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def activate(self):
        """状態だけ AWAIT_PROBLEM にする（テスト・start から使う）"""
        self.state = "AWAIT_PROBLEM"
        self._errors = 0
        self._await_prev = None

    def start(self):
        self._stop.clear()
        self.activate()
        self._thread = threading.Thread(target=self._run, name="tsumego-autoloop", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self.state = "IDLE"

    def _run(self):
        while not self._stop.is_set():
            try:
                self.step()
            except Exception as e:  # 1 周の例外でスレッドを落とさない
                self.gui.log(f"autoloop: step で例外: {e!r}")
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
            if kind == "problem_ready" and self.state == "CAPTURING":
                _k, token, base_grid, key, route = ev
                self.problem = _Problem(token, base_grid, key, route, self.clock())
                self.stats["problems"] += 1
                self.state = "ANSWERING"
                self.gui.notify("info", self._banner("解答中"))
            elif kind == "capture_failed" and self.state == "CAPTURING":
                self.gui.log(f"autoloop: キャプチャ失敗 → わざと1手打って収穫に回します（{ev[1]}）")
                self._enter_capture_failed()
            elif kind == "black_move" and self.state == "ANSWERING" and self.problem is not None:
                _k, token, coords_xy = ev
                if token != self.problem.token:
                    continue
                self._pending_taps.append(coords_xy)

    def _step_await_problem(self, frame):
        if self.vision.popup_present(frame):
            self.state = "NEXT"
            return
        try:
            grid = self.vision.read_board(frame).grid
        except CaptureError:
            self._await_prev = None
            return
        has_stones = any(v != EMPTY for row in grid for v in row)
        if not has_stones or grid == self.last_initial or grid == self.last_final:
            self._await_prev = None
            return
        if grid != self._await_prev:
            self._await_prev = grid
            return  # 2 フレーム連続で同じになるまで待つ
        self._await_prev = None
        self._pending_taps = []
        self.state = "CAPTURING"
        self._deadline = self.clock() + self.settings.capture_timeout_s
        self.gui.trigger_capture()

    def _step_capturing(self, frame):
        if self.clock() >= self._deadline:
            self.gui.log("autoloop: キャプチャ完了の通知が来ません（timeout）→ CAPTURE_FAILED")
            self._enter_capture_failed()

    def _step_answering(self, frame):
        p = self.problem
        if self.vision.popup_present(frame):
            self.state = "RESULT"
            return
        if self._pending_taps:
            try:
                p.rect = self.vision.board_rect(frame)
            except CaptureError:
                return  # 次のフレームで
            for coords_xy in self._pending_taps:
                i, j = move_to_grid(coords_xy, p.size)
                self.adb.tap(*board_to_device(i, j, p.rect, p.size))
                p.n_black += 1
            self._pending_taps = []
            return
        if self.clock() - p.started > self.settings.answer_timeout_s:
            self.state = "STALLED"
            self._deadline = self.clock() + STALL_EXTRA_S
            self._save_shot(frame, "stalled")

    def _step_result(self, frame):
        verdict = self.vision.popup_state(frame)
        p = self.problem
        if verdict == "none":
            self.state = "NEXT"  # ポップアップが消えた（ユーザー操作等）
            return
        if verdict == "wrong":
            self.stats["wrong"] += 1
            self._errors = 0
            self.gui.stop_watch()
            base = p.base if (p and p.base) else self._cf_base
            if base is None:
                self._record(p, "wrong", harvest="skipped:盤が読めていない")
                self._save_shot(frame, "wrong_nobase")
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
        self._cf_tapped = False
        self._cf_base = None
        self._deadline = self.clock() + 45.0

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
                    self.adb.tap(*board_to_device(i, j, read.rect, read.size))
            except CaptureError:
                self._save_shot(frame, "capture_failed")
                w, h = frame.size
                self.adb.tap(w // 2, int(h * 0.46))
            self._cf_tapped = True
            return
        if self.clock() >= self._deadline:
            self._record(self.problem, "capture_failed", harvest="skipped:ポップアップが出ない")
            self._error_step("capture_failed: 結果が出ません")
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
            self._record(p, "wrong", harvest=f"skipped:{payload}")
            self._save_shot(frame, "harvest_failed")
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
        self.adb.tap(*self.vision.ui_point(name, frame))
        self.problem = None
        self._cf_base = None
        self._not_before = self.clock() + max(self.settings.settle_ms, 300) / 1000.0
        if self.settings.max_problems and self.stats["problems"] >= self.settings.max_problems:
            self._to_idle(f"{self.settings.max_problems} 問に達したため停止しました")
            return
        self.state = "AWAIT_PROBLEM"
        self._await_prev = None

    # --- 補助 ---
    def _error_step(self, why):
        self._errors += 1
        self.stats["failed"] += 1
        self.gui.log(f"autoloop: {why}（連続 {self._errors}）")
        if self._errors >= self.settings.max_consecutive_errors:
            self._to_idle(f"連続 {self._errors} 回失敗したため停止しました（{why}）")

    def _fail(self, why, frame):
        self._record(self.problem, "error", harvest=f"skipped:{why}")
        if frame is not None:
            self._save_shot(frame, "error")

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
        }
        try:
            self.ledger.append(rec)
        except Exception as e:
            self.gui.log(f"autoloop: 台帳に書けません: {e}")

    def _save_shot(self, frame, tag):
        try:
            os.makedirs(self.settings.shots_dir, exist_ok=True)
            path = os.path.join(self.settings.shots_dir, f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}.png")
            if hasattr(frame, "save"):
                frame.save(path)
        except Exception as e:
            self.gui.log(f"autoloop: スクショ保存失敗: {e}")
```

`_record` の `time.strftime` は実時刻でよい（テストは `ts` を見ない）。`move_to_grid` は Task 1 のファイル先頭 import に含めてある（`board_watch` との循環はない）。

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q`
Expected: 全件 PASS。`test_controller_stalled_then_error_then_idle_after_3` は `max_consecutive_errors=1` なので 1 回で IDLE。

- [ ] **Step 5: 既存テストの回帰**

Run: `python -m pytest tests/test_board_watch.py tests/test_tsumego_answer_book.py tests/test_tsumego_capture.py -q`
Expected: PASS（既存モジュールは無変更）

- [ ] **Step 6: コミット**

```bash
git add katrain/core/tsumego_autoloop.py tests/test_tsumego_autoloop.py
git commit -m "feat(autoloop): 状態機械（出題検知→キャプチャ→回答→正誤→収穫→次の問題）を追加"
```

---

### Task 5: GUI 接続（ホットキー・フック・回答帳保存の切り出し・設定）

**Files:**
- Modify: `katrain/__main__.py`
  - `_setup_global_hotkeys`（`:932-990` 付近）: `tsumego_autoloop` のホットキーを表に追加
  - `_do_tsumego_record_toggle`（`:501-560`）: 保存分岐を `_save_answer_line` に切り出し
  - `_do_tsumego_capture_apply` の `finish_gui` 末尾（`:2048-2055` 付近）: `on_problem_ready`
  - `_tsumego_capture_failed`（`:1462`）: `on_capture_failed`
  - `_do_ai_move`（`:456`）: `on_black_move`
  - `_tsumego_capture_trigger`（`:1045`）: `force` 引数でデバウンスを飛ばす
  - 新メソッド `_autoloop_trigger` / `_autoloop_callbacks` / `_save_answer_line`
- Modify: `katrain/config.json`（`board_watch` の直後に `tsumego_autoloop` セクション）
- Modify: `C:\Users\iwaki\.katrain\config.json`（同セクション。**メインセッションで直接 Edit**）
- Test: `tests/test_tsumego_autoloop.py`（AST で接続点の存在を確認）

**Interfaces:**
- Consumes: Task 4 の `AutoLoopController`・`Vision`・`AdbClient`・`discover_serial`・`Ledger`・`autoloop_settings_from_config`
- Produces: `KaTrainGui._save_answer_line(base_grid, moves_xy) -> (bool, int)`（moves は `[(coords_xy, color)]`・KaTrain 座標）、`KaTrainGui._autoloop_trigger()`（ホットキー）、`self._autoloop`（コントローラ or None）

- [ ] **Step 1: 失敗するテストを書く（AST）**

```python
def _main_tree():
    import ast
    path = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())


def test_main_has_autoloop_hooks():
    import ast
    tree = _main_tree()
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert {"_autoloop_trigger", "_autoloop_callbacks", "_save_answer_line"} <= names
    src = ast.unparse(tree)
    assert "on_problem_ready(" in src and "on_capture_failed(" in src and "on_black_move(" in src
    assert '"tsumego_autoloop"' in src  # 設定セクション名


def test_package_config_has_autoloop_section():
    path = os.path.join(os.path.dirname(__file__), "..", "katrain", "config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    sec = cfg["tsumego_autoloop"]
    assert sec["hotkey"] == "ctrl+alt+a" and sec["enabled"] is True and "adb_path" in sec
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py -q -k "main_has or package_config"`
Expected: FAIL

- [ ] **Step 3: `_save_answer_line` を切り出し、記録ボタンから呼ぶ**

`_do_tsumego_record_toggle` の「# 保存」以降を次に置き換える:

```python
        # 保存
        moves = moves_from_game(game)
        Clock.schedule_once(lambda _dt: setattr(self, "tsumego_recording", False), 0)
        prev = getattr(self, "_tsumego_record_prev_black", None)
        self._tsumego_record_prev_black = None
        if prev:
            self.update_player("B", player_type=prev[0], player_subtype=prev[1])
        if not moves or moves[0][1] != "B":
            self._tsumego_message("手順が空か黒番から始まっていないため記録を破棄しました", kind="warn")
            return
        added, n = self._save_answer_line(game.tsumego_app_grid, moves)
        if added:
            self._tsumego_message(f"正解手順を回答帳に保存しました（{n}手）", kind="save")
        else:
            self._tsumego_message("同じ手順が記録済みです（回答帳は変更なし）", kind="info")

    def _save_answer_line(self, base_grid, moves):
        """回答帳へ 1 手順を保存する（記録ボタンと自動ループの共用）。

        base_grid は枠を張る前の認識グリッド（= game.tsumego_app_grid = アプリの盤）。moves は
        KaTrain 座標 (x, y) の (coords, color) 列（パスは None）。キーは `_do_tsumego_capture_apply` と
        同じ canonicalize なので、同じ盤なら同じ entry に追記される。戻り値 (追加されたか, 手数)。
        """
        from katrain.core import tsumego_answer_book as answer_book
        from katrain.core.tsumego_problem import grid_to_stones

        bk_black, bk_white, (bk_size, _) = grid_to_stones(base_grid)
        key, transforms = answer_book.canonicalize(bk_black, bk_white, bk_size, "B")
        t0 = transforms[0]
        line = answer_book.moves_to_canonical(moves, t0, bk_size)
        canonical_black = sorted(answer_book.point_to_gtp(answer_book.transform_point(p, t0, bk_size)) for p in bk_black)
        canonical_white = sorted(answer_book.point_to_gtp(answer_book.transform_point(p, t0, bk_size)) for p in bk_white)
        book = answer_book.get_book(lambda msg: self.log(msg, OUTPUT_INFO))
        added = book.add_line(key, bk_size, "B", canonical_black, canonical_white, line)
        game = self.game
        if getattr(game, "tsumego_book_key", None) == key:
            game.tsumego_book_entry = book.lookup(key)  # 保存直後から再生可能
        # 回答帳に入った問題のログは自動削除の対象から外す（誤答も、次から即答させたい正解済みも同じ）
        kept = self.keep_current_log(key=key, note=f"answer_book {len(line)}手 {' '.join(line)}")
        if kept:
            self.log(f"tsumego_answer_book: このログを保護しました（自動削除しません）: {kept}", OUTPUT_INFO)
        return added, len(line)
```

（旧コードの `bk_black, bk_white, bk_size = game.tsumego_book_stones` 〜 `_tsumego_message(...)` までが置き換わる。`game.tsumego_app_grid` は `_do_tsumego_capture_apply` が必ず設定している）

- [ ] **Step 4: フックとホットキーを足す**

(a) `_do_ai_move`:
```python
    def _do_ai_move(self, node=None):
        if node is None or self.game.current_node == node:
            mode = self.next_player_info.strategy
            settings = self.config(f"ai/{mode}")
            if settings is not None:
                move, _played = generate_ai_move(self.game, mode, settings)
                autoloop = getattr(self, "_autoloop", None)
                if autoloop is not None and move is not None and move.player == "B":
                    autoloop.on_black_move(id(self.game), move.coords)
            else:
                self.log(f"AI Mode {mode} not found!", OUTPUT_ERROR)
```

(b) `_tsumego_capture_failed`:
```python
    def _tsumego_capture_failed(self, message):
        """失敗をターミナルと GUI の両方に出す（作業スレッドから呼ばれるため GUI 更新は Clock 経由）"""
        self.log(message, OUTPUT_ERROR)
        Clock.schedule_once(lambda _dt: self.controls.set_status(message, STATUS_ERROR, check_level=False), 0)
        autoloop = getattr(self, "_autoloop", None)
        if autoloop is not None:
            autoloop.on_capture_failed(message)
```

(c) `_do_tsumego_capture_apply` の `finish_gui` 末尾（`_start_tsumego_watch` の try/except の直後・同じインデント）:
```python
            autoloop = getattr(self, "_autoloop", None)
            if autoloop is not None:
                game = self.game
                route = "book" if getattr(game, "tsumego_book_entry", None) else self.players_info["B"].player_subtype
                autoloop.on_problem_ready(
                    id(game), getattr(game, "tsumego_app_grid", None), getattr(game, "tsumego_book_key", None), route
                )
```

(d) `_tsumego_capture_trigger` のシグネチャとデバウンス:
```python
    def _tsumego_capture_trigger(self, black_to_attack=None, frameless=False, force=False):
        # ホットキースレッドが起こした作業スレッドで実行される。
        # 認識までここで行い、盤面への反映はメッセージループに投げる
        from katrain.core.tsumego_capture import CaptureError, capture_board_view

        now = time.time()
        if not force and now - getattr(self, "_tsumego_capture_last_trigger", 0.0) < 2.0:
            return
```

(e) ホットキー表（`_setup_global_hotkeys`）: 先頭の読み込みと早期 return を
```python
        tsumego = self._config.get("tsumego_capture") or {}
        watch = self._config.get("board_watch") or {}
        autoloop = self._config.get("tsumego_autoloop") or {}
        if not tsumego.get("enabled", False) and not watch.get("enabled", False) and not autoloop.get("enabled", False):
            return
```
にし、`specs` に board_watch の次で追加:
```python
        if autoloop.get("enabled", False):
            specs.append((autoloop, "tsumego_autoloop", "hotkey", "ctrl+alt+a", "_autoloop_trigger", (), "詰碁自動ループ トグル"))
```

(f) 新メソッド（`_board_watch_trigger` の近くに置く）:
```python
    def _autoloop_trigger(self):
        """ctrl+alt+a のワーカースレッド。OFF なら ADB に接続して開始、ON なら停止する"""
        from katrain.core.tsumego_autoloop import (
            AdbClient,
            AutoLoopController,
            Ledger,
            Vision,
            autoloop_settings_from_config,
            discover_serial,
        )

        now = time.time()
        if now - getattr(self, "_autoloop_last_trigger", 0.0) < 2.0:
            return
        self._autoloop_last_trigger = now
        current = getattr(self, "_autoloop", None)
        if current is not None:
            current.stop()
            self._autoloop = None
            self.log("autoloop: 停止しました", OUTPUT_INFO)
            self._tsumego_message("自動ループを停止しました", kind="info")
            return
        settings = autoloop_settings_from_config(self._config.get("tsumego_autoloop"))
        serial = settings.adb_serial or discover_serial(settings.adb_path)
        if not serial:
            self._tsumego_message("ADB デバイスが見つかりません（BlueStacks 設定で ADB を ON にして再起動）", kind="warn", seconds=8)
            return
        adb = AdbClient(settings.adb_path, serial)
        try:
            adb.connect()
            if not adb.is_device():
                raise RuntimeError(f"{serial} が device として見えません")
        except Exception as e:
            self._tsumego_message(f"ADB に接続できません: {e}", kind="warn", seconds=8)
            return
        cap = self._config.get("tsumego_capture") or {}
        sizes = [int(s) for s in (cap.get("board_sizes") or [9, 13, 19])]
        controller = AutoLoopController(
            adb, Vision(sizes, ui_points=settings.ui_points), self._autoloop_callbacks(), settings, Ledger(settings.ledger_path)
        )
        self._autoloop = controller
        controller.start()
        self.log(f"autoloop: 開始しました（{serial}）", OUTPUT_INFO)
        self._tsumego_message("自動ループを開始しました（ctrl+alt+a で停止）", kind="info")

    def _autoloop_callbacks(self):
        """コントローラが使う GUI 側の操作（どれもワーカースレッドから呼ばれる）"""
        from types import SimpleNamespace

        from katrain.core.board_watch import grid_to_move

        def trigger_capture():
            self._tsumego_capture_trigger(black_to_attack=None, frameless=False, force=True)

        def save_line(base_grid, moves_grid):
            size = len(base_grid)
            moves = [(grid_to_move(i, j, size), color) for (i, j), color in moves_grid]
            return self._save_answer_line(base_grid, moves)

        def stop_watch():
            if self._stop_board_watcher(kinds=("tsumego",)):
                self._board_watch_status("", "")

        def notify(kind, text):
            self._tsumego_message(text, kind=kind)

        def log(text):
            self.log(text, OUTPUT_INFO)

        return SimpleNamespace(trigger_capture=trigger_capture, save_line=save_line, stop_watch=stop_watch, notify=notify, log=log)
```

`_save_answer_line` はメッセージループ外（ワーカースレッド）からも呼ばれるが、中で触るのは回答帳ファイル・ログ・`game.tsumego_book_entry` だけで、記録ボタン経由と同じ（Clock は使っていない）。

(g) `__init__` 近く（`self._tsumego_flash_event = None` の行の隣）に `self._autoloop = None` を足す。

- [ ] **Step 5: 設定セクションを両方の config.json に追加**

`katrain/config.json` の `"board_watch": {...},` の直後:
```json
    "tsumego_autoloop": {
        "enabled": true,
        "hotkey": "ctrl+alt+a",
        "adb_path": "C:\\Program Files\\BlueStacks_nxt\\HD-Adb.exe",
        "adb_serial": "",
        "poll_ms": 500,
        "settle_ms": 700,
        "answer_timeout_s": 40,
        "capture_timeout_s": 15,
        "max_problems": 0,
        "max_consecutive_errors": 3
    },
```
`C:\Users\iwaki\.katrain\config.json` にも同じブロックを同じ位置に追加する（**メインセッションで直接 Edit。KaTrain が起動していないことを `tasklist | grep -ai python` で確認してから**。追加後 `python -c "import json;json.load(open(r'C:\Users\iwaki\.katrain\config.json',encoding='utf-8'))"` で JSON が壊れていないことを確認）。

- [ ] **Step 6: テストと起動確認**

Run: `python -m pytest tests/test_tsumego_autoloop.py tests/test_board_watch.py -q`
Expected: PASS（`test_board_watch.py` のホットキー表 AST テストは `_autoloop_trigger` が存在するので通る）

Run: `python -m katrain`（起動して終了）→ `~/.katrain/logs/` の最新ログ or ターミナルに `tsumego_autoloop: ホットキー ctrl+alt+a=詰碁自動ループ トグル を登録しました` が出ること。

- [ ] **Step 7: コミット**

```bash
git add katrain/__main__.py katrain/config.json tests/test_tsumego_autoloop.py
git commit -m "feat(autoloop): ホットキー ctrl+alt+a・キャプチャ/着手フック・回答帳保存の共通化・設定セクションを追加"
```

---

### Task 6: 実機スモークとテンプレート・閾値の確定（ユーザー同席）

**Files:**
- Create: `katrain/img/autoloop/popup_correct_tail.png`、`tests/data/autoloop/popup_correct.png`、`tests/data/autoloop/hint_disabled.png`
- Modify: `katrain/core/tsumego_autoloop.py`（`HINT_ICON_ENABLED_MIN` の確定）、`tests/test_tsumego_autoloop.py`
- Modify: `docs/superpowers/specs/2026-08-23-tsumego-autoloop-design.md`（追記1: 実機実測）

**Interfaces:** 変更なし（定数の確定のみ）

- [ ] **Step 1: 正解ポップアップと無効ヒントのフレームを撮る**

ユーザーに (a) 1 問正解してポップアップ、(b) 1 問不正解→ヒント歩きを最後まで進めてヒントがグレーの状態、をそれぞれ作ってもらい、その都度:
```bash
python -m katrain.core.tsumego_autoloop shot tests/data/autoloop/popup_correct.png
python -m katrain.core.tsumego_autoloop shot tests/data/autoloop/hint_disabled.png
```

- [ ] **Step 2: 正解テンプレートを生成し、閾値を実測**

```bash
python - <<'EOF'
from PIL import Image, ImageStat
from katrain.core import tsumego_autoloop as al
f = Image.open("tests/data/autoloop/popup_correct.png").convert("RGB")
al.verdict_tail(f).save("katrain/img/autoloop/popup_correct_tail.png")
t = al.load_templates()
for name in ("popup_wrong.png", "popup_correct.png"):
    fr = Image.open(f"tests/data/autoloop/{name}").convert("RGB")
    tail = al.verdict_tail(fr)
    print(name, {k: round(al._mad(tail, v), 1) for k, v in t.items()}, "->", al.popup_state(fr, t))
for name in ("problem.png", "hint_disabled.png"):
    fr = Image.open(f"tests/data/autoloop/{name}").convert("RGB")
    w, h = fr.size; cx, cy, rad = int(al.HINT_ICON[0]*w), int(al.HINT_ICON[1]*h), al.HINT_ICON[2]
    print(name, "hint icon mean", round(ImageStat.Stat(fr.crop((cx-rad, cy-rad, cx+rad, cy+rad)).convert("L")).mean[0], 1))
EOF
```
Expected: wrong フレームは wrong 側の MAD が小さく（< 30）correct 側と 10 以上離れる（逆も同様）。ヒントアイコンは有効 ≈151 / 無効がそれより十分低い。無効側が 110 を超えるなら `HINT_ICON_ENABLED_MIN` を「有効と無効の中点」に置き換える。

- [ ] **Step 3: テストを追加**

```python
def test_popup_state_correct_template():
    templates = al.load_templates()
    assert {"wrong", "correct"} <= set(templates)
    assert al.popup_state(_frame("popup_correct.png"), templates) == "correct"
    assert al.popup_state(_frame("popup_wrong.png"), templates) == "wrong"


def test_hint_disabled_frame():
    assert al.hint_enabled(_frame("hint_disabled.png")) is False
    assert al.hint_enabled(_frame("problem.png")) is True
```

Run: `python -m pytest tests/test_tsumego_autoloop.py -q` → PASS

- [ ] **Step 4: 通しスモーク（1 問ずつ）**

KaTrain を起動し BlueStacks を問題画面にして `ctrl+alt+a`。確認項目:
1. 新しい問題でキャプチャが起動し、AI の黒がアプリに打たれ、白が KaTrain に入り、ポップアップまで進む
2. 正解なら「次の問題」が押され次の問題がキャプチャされる
3. 不正解なら 問題を見る→戻す→ヒント歩き→「正解手順を回答帳に保存しました」バナー → 次の問題
4. `~/.katrain/tsumego_ledger.jsonl` に 1 問 1 行、`~/.katrain/tsumego_answers.json` に entry が増える
5. `ctrl+alt+a` で停止する

問題が出たら `python -m katrain.core.tsumego_autoloop probe` でその画面の判定値を見る。30 秒タイムアウト時の挙動（不正解ポップアップになるか）もここで確認し、spec 追記1 に書く。

- [ ] **Step 5: spec 追記とコミット**

spec 末尾に「## 追記1（実機 2026-08-xx）」として: テンプレート MAD の実測・ヒントアイコンの有効/無効の輝度・タイムアウト時の挙動・スモーク 3 問の台帳行 を 10 行程度で記す。

```bash
git add katrain/img/autoloop/popup_correct_tail.png tests/data/autoloop/popup_correct.png tests/data/autoloop/hint_disabled.png katrain/core/tsumego_autoloop.py tests/test_tsumego_autoloop.py docs/superpowers/specs/2026-08-23-tsumego-autoloop-design.md
git commit -m "feat(autoloop): 正解テンプレートと無効ヒントの実フレームで判定閾値を確定・実機スモークの記録"
```

---

### Task 7: ドキュメント

**Files:**
- Modify: `CLAUDE.md`（冒頭の3系統テーブルの「盤面監視」行に自動ループを足す／ディレクトリ構造に `tsumego_autoloop.py`）
- Modify: `.claude/rules/tsumego.md`（機能の全体像に 1 段落）
- Modify: `docs/superpowers/specs/INDEX.md`（⚪→🟢）

- [ ] **Step 1: CLAUDE.md**

3系統テーブルの盤面監視行の「内容」セルに追記:
`board_watch.py` … の後に「／ `tsumego_autoloop.py`: 詰碁の自動ループ（ADB でアプリを操作。トグル `ctrl+alt+d` ではなく `ctrl+alt+a`。spec `2026-08-23-tsumego-autoloop-design.md`）」。ディレクトリ構造の `board_watch.py` 行の下に
`    tsumego_autoloop.py  -- 詰碁の自動ループ（ADB 操作・正誤検知・ヒント歩きで回答帳へ自動収穫・台帳 ~/.katrain/tsumego_ledger.jsonl。トグル ctrl+alt+a）`
を足す。

- [ ] **Step 2: .claude/rules/tsumego.md**

「機能の全体像」の白番自動反映の段落の直後に:
> さらに**自動ループ** `tsumego_autoloop`（2026-08-23・spec `2026-08-23-tsumego-autoloop-design.md`）: `ctrl+alt+a` で、アプリの新しい問題を検知→キャプチャ（役割は自動推定）→AI の黒を ADB でタップ→白は既存監視→結果ポップアップを画面判定→正解なら次の問題、不正解なら 問題を見る→戻す→ヒントの赤丸を歩いて `add_line` で回答帳へ保存→次の問題、を回す。初見問題の一次正答率は上がらない（別解・判定不能）が、再出題は回答帳で 100% になるので回すほど漸近する。1問1行の台帳 `~/.katrain/tsumego_ledger.jsonl`、失敗時だけ `logs/autoloop/` にスクショ。**unknown ポップアップは正解扱いで次へ**（未知画面で戻す・ヒントを叩かない）。判定の閾値は `tests/data/autoloop/` の実フレームで固定している＝アプリの UI が変わったらフレームを撮り直して閾値を直す（`python -m katrain.core.tsumego_autoloop probe`）。

- [ ] **Step 3: INDEX.md の行を 🟢 に更新し、コミット**

```bash
git add CLAUDE.md .claude/rules/tsumego.md docs/superpowers/specs/INDEX.md
git commit -m "docs(autoloop): 詰碁自動ループの運用メモを CLAUDE.md / rules / INDEX に追加"
```

（`.claude/rules/` の Edit が拒否されたらサブエージェント経由で編集する＝CLAUDE.md の既知事項）

---

## 自己レビュー（プラン作成時）

- spec §3 の全状態（AWAIT_PROBLEM / CAPTURING / ANSWERING / RESULT / CAPTURE_FAILED / HARVEST / NEXT / STALLED / ERROR→IDLE）は Task 4 に対応。§4 の判定は Task 1（+Task 6 で正解テンプレと無効ヒント）。§5 タップは Task 2・4。§6 収穫は Task 3。§7 接続点は Task 5。§8 台帳は Task 3・4。§9 安全弁（ADB 断の再接続・連続失敗で IDLE・上限）は Task 4。§10 設定は Task 1・5。§11 テストは各 Task。
- 型の一貫性: `on_black_move(token, coords_xy)` は KaTrain 座標、`save_line(base_grid, moves_grid)` はグリッド座標で、変換は `_autoloop_callbacks.save_line` と `_step_answering`（`move_to_grid`）の 2 箇所のみ。`Harvester.step` → `("done", moves_grid)`。
- 未確定点（spec 明記）: 30 秒タイムアウトがポップアップになるか → Task 6 で確認し追記。
