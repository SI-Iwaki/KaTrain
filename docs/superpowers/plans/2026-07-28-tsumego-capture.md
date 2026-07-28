# 詰碁画面キャプチャ→KaTrain自動反映 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** グローバルホットキー一発で BlueStacks 上の詰碁アプリ（13路・黒番固定）の盤面をキャプチャ・認識し、KaTrain に石配置+詰碁外枠適用まで自動実行する。

**Architecture:** Kivy 非依存の認識モジュール `katrain/core/tsumego_capture.py`（PILのみ使用: 黄色盤検出→格子推定→交点色分類→SGF生成）+ `katrain/__main__.py` へのグルーコード（keyboard ライブラリのグローバルホットキー→認識→単一メッセージ `tsumego-capture-apply` で `_do_new_game`+`_do_tsumego_frame` を同期実行）。

**Tech Stack:** Python 3.12（システムPython、venv無し）、Pillow 12.1.1（導入済み）、keyboard（新規導入）、ctypes/Win32 API（ウィンドウ検出）、pytest。

**Spec:** `docs/superpowers/specs/2026-07-28-tsumego-capture-design.md`

## Global Constraints

- コミットメッセージは**日本語**・Conventional Commits 形式（`feat:` `fix:` `docs:` 等）
- 実行環境はシステム Python: `python`（= `C:\Users\iwaki\AppData\Local\Programs\Python\Python312\python.exe`）。`uv run` や `.venv` は存在しない
- `C:\Users\iwaki\.katrain\config.json`（ユーザーローカル設定）の編集は**メインセッションで直接 Edit** すること。サブエージェントに委任禁止（CLAUDE.md ルール）
- CLI のユーザー向け print 出力は cp932 端末対応のため盤面表示は ASCII のみ（`B`/`W`/`.`）。日本語メッセージは可（cp932 でエンコード可能）
- 新規コードは line-length 120。既存ファイルに black を全体実行しない（巨大差分になるため）
- テスト実行は対象ファイル指定: `python -m pytest tests/test_tsumego_capture.py -v`（`tests/test_ai.py` は humanSL モデル依存のため全体実行しない）
- `katrain/core/tsumego_capture.py` は Kivy を import しない（単体テスト・CLI 実行可能に保つ）

---

### Task 1: サンプル画像の取り込みと盤検出 `detect_board`

**Files:**
- Create: `tests/data/tsumego_app_sample.png`（`c:\temp\詰碁アプリ画像.png` のコピー）
- Create: `katrain/core/tsumego_capture.py`
- Create: `tests/test_tsumego_capture.py`

**Interfaces:**
- Consumes: なし（最初のタスク）
- Produces:
  - `CaptureError(Exception)` — ユーザー向けメッセージを持つ認識失敗例外
  - `detect_board(img: PIL.Image.Image) -> tuple[int, int, int, int]` — 盤の bbox `(x0, y0, x1, y1)`（両端含むピクセル座標）。検出失敗時 `CaptureError`

- [ ] **Step 1: サンプル画像をテストデータにコピー**

```powershell
Copy-Item "c:\temp\詰碁アプリ画像.png" "tests\data\tsumego_app_sample.png"
```

- [ ] **Step 2: サンプル画像を目視確認**

Read ツールで `tests/data/tsumego_app_sample.png` を開き、次を確認する:
- 黄色い盤が画像内で最大の黄色領域であること
- 盤上の石の配置（Task 2 の期待値検証に使う。行 i=上から0起点、列 j=左から0起点）:
  - 白石: (0,0), (0,2), (0,3), (1,0), (1,3), (2,3), (3,0), (3,1), (3,2), (3,3) の10子
  - 黒石: (1,2), (1,4), (2,0), (2,1), (2,4), (3,4), (4,0), (4,1), (4,2), (4,3), (4,4) の11子
- 上記リストと画像が食い違う場合はこのステップで**画像を正としてリストを訂正**し、Task 2 の期待値に反映する

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_tsumego_capture.py` を新規作成:

```python
import os

import pytest
from PIL import Image

from katrain.core.tsumego_capture import CaptureError, detect_board

SAMPLE = os.path.join(os.path.dirname(__file__), "data", "tsumego_app_sample.png")


def test_detect_board_returns_square_bbox():
    img = Image.open(SAMPLE)
    x0, y0, x1, y1 = detect_board(img)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    assert min(w, h) >= 300
    assert 0.9 < w / h < 1.1
    # 盤は画像の中央下寄り: bbox が画像内に収まっている
    assert 0 <= x0 < x1 < img.width
    assert 0 <= y0 < y1 < img.height


def test_detect_board_fails_without_board():
    img = Image.new("RGB", (800, 600), (20, 40, 120))  # 青一色
    with pytest.raises(CaptureError):
        detect_board(img)
```

- [ ] **Step 4: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'katrain.core.tsumego_capture'`）

- [ ] **Step 5: `detect_board` を実装**

`katrain/core/tsumego_capture.py` を新規作成:

```python
"""BlueStacks上の詰碁アプリ盤面をキャプチャ・認識して13路SGFにする（Kivy非依存・PILのみ使用）"""

import ctypes
import ctypes.wintypes

from PIL import Image, ImageGrab, ImageStat

DEFAULT_WINDOW_TITLE = "BlueStacks"
DEFAULT_BOARD_SIZE = 13
DETECT_SCALE = 4  # 盤検出時の縮小率


class CaptureError(Exception):
    """盤面キャプチャ・認識の失敗（ユーザー向けメッセージ付き）"""


def _is_yellow(r, g, b):
    # サンプル画像の盤色 約RGB(247,193,62)。木目・照明ムラを許容する広めの閾値
    return r > 170 and g > 120 and b < 150 and (r - b) > 60


def detect_board(img):
    """画像内の黄色い碁盤領域の bbox (x0, y0, x1, y1) を返す（両端含む）"""
    w, h = img.size
    thumb = img.convert("RGB").resize((max(1, w // DETECT_SCALE), max(1, h // DETECT_SCALE)), Image.NEAREST)
    tw, th = thumb.size
    px = thumb.load()
    row_counts = [0] * th
    col_counts = [0] * tw
    for y in range(th):
        for x in range(tw):
            if _is_yellow(*px[x, y][:3]):
                row_counts[y] += 1
                col_counts[x] += 1
    max_row = max(row_counts, default=0)
    max_col = max(col_counts, default=0)
    if max_row < tw * 0.25 or max_col < th * 0.25:
        raise CaptureError("盤面を検出できません（盤が画面に表示されているか確認してください）")
    rows = [y for y, c in enumerate(row_counts) if c >= max_row * 0.5]
    cols = [x for x, c in enumerate(col_counts) if c >= max_col * 0.5]
    x0, x1 = cols[0] * DETECT_SCALE, (cols[-1] + 1) * DETECT_SCALE - 1
    y0, y1 = rows[0] * DETECT_SCALE, (rows[-1] + 1) * DETECT_SCALE - 1
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if min(bw, bh) < 300 or not (0.9 < bw / bh < 1.1):
        raise CaptureError(f"盤面の形が不正です（検出領域 {bw}x{bh}。盤が隠れていないか確認してください）")
    return (x0, y0, x1, y1)
```

- [ ] **Step 6: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -v`
Expected: 2 PASS

- [ ] **Step 7: コミット**

```powershell
git add tests/data/tsumego_app_sample.png tests/test_tsumego_capture.py katrain/core/tsumego_capture.py
git commit -m "feat(tsumego-capture): 詰碁アプリ画像からの盤検出を実装"
```

---

### Task 2: 交点分類 `classify_intersections`

**Files:**
- Modify: `katrain/core/tsumego_capture.py`（関数追加）
- Modify: `tests/test_tsumego_capture.py`（テスト追加）

**Interfaces:**
- Consumes: `detect_board(img) -> (x0, y0, x1, y1)`、`CaptureError`（Task 1）
- Produces: `classify_intersections(img: PIL.Image.Image, board_rect: tuple[int, int, int, int], board_size: int = 13) -> list[list[str]]` — `grid[i][j]` が `"B"`/`"W"`/`"."`（i=上から行、j=左から列）。曖昧な交点があれば `CaptureError`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_capture.py` に追記（期待値は Task 1 Step 2 で目視確定したもの。食い違いがあった場合はそちらを正とする）:

```python
from katrain.core.tsumego_capture import classify_intersections

EXPECTED_WHITE = {(0, 0), (0, 2), (0, 3), (1, 0), (1, 3), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3)}
EXPECTED_BLACK = {(1, 2), (1, 4), (2, 0), (2, 1), (2, 4), (3, 4), (4, 0), (4, 1), (4, 2), (4, 3), (4, 4)}


def test_classify_sample_image():
    img = Image.open(SAMPLE)
    grid = classify_intersections(img, detect_board(img), 13)
    assert len(grid) == 13 and all(len(row) == 13 for row in grid)
    black = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "B"}
    white = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "W"}
    assert black == EXPECTED_BLACK
    assert white == EXPECTED_WHITE
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -v`
Expected: `test_classify_sample_image` が FAIL（`ImportError: cannot import name 'classify_intersections'`）

- [ ] **Step 3: `classify_intersections` を実装**

`katrain/core/tsumego_capture.py` の `detect_board` の後に追加:

```python
def classify_intersections(img, board_rect, board_size=DEFAULT_BOARD_SIZE):
    """各交点を "B"（黒石）/"W"（白石）/"."（空点）に分類した board_size x board_size のグリッドを返す。

    格子は規則配置前提: セル幅 = 盤幅/board_size、第1線は盤端から半セル内側。
    判定はパッチ平均色: 低輝度=黒石、低彩度かつ高輝度=白石、黄色系=空点。どれでもなければ CaptureError。
    """
    x0, y0, x1, y1 = board_rect
    cell_w = (x1 - x0 + 1) / board_size
    cell_h = (y1 - y0 + 1) / board_size
    rgb = img.convert("RGB")
    rad = max(2, int(min(cell_w, cell_h) * 0.25))
    grid = []
    ambiguous = []
    for i in range(board_size):
        row = []
        for j in range(board_size):
            cx = x0 + cell_w * (j + 0.5)
            cy = y0 + cell_h * (i + 0.5)
            patch = rgb.crop((int(cx) - rad, int(cy) - rad, int(cx) + rad + 1, int(cy) + rad + 1))
            mr, mg, mb = ImageStat.Stat(patch).mean
            brightness = (mr + mg + mb) / 3
            spread = max(mr, mg, mb) - min(mr, mg, mb)
            if brightness < 90:
                row.append("B")
            elif spread < 60 and brightness > 160:
                row.append("W")
            elif spread > 90 and mr > mb:
                row.append(".")
            else:
                ambiguous.append((i, j, (round(mr), round(mg), round(mb))))
                row.append("?")
        grid.append(row)
    if ambiguous:
        raise CaptureError(f"判定できない交点があります（先頭5件: {ambiguous[:5]}）")
    return grid
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -v`
Expected: 3 PASS。もし `test_classify_sample_image` が失敗したら、失敗した交点についてサンプル画像を目視で再確認し、(a) 期待値が誤っていれば期待値を訂正、(b) 閾値が原因なら失敗交点の実測 RGB（ambiguous のメッセージや print デバッグで取得）に合わせて閾値を調整する。**画像の実配置が常に正**

- [ ] **Step 5: コミット**

```powershell
git add katrain/core/tsumego_capture.py tests/test_tsumego_capture.py
git commit -m "feat(tsumego-capture): 交点の石分類を実装"
```

---

### Task 3: SGF生成 `grid_to_sgf`

**Files:**
- Modify: `katrain/core/tsumego_capture.py`（関数追加）
- Modify: `tests/test_tsumego_capture.py`（テスト追加)

**Interfaces:**
- Consumes: `classify_intersections` の返す grid 形式（Task 2）、`CaptureError`
- Produces: `grid_to_sgf(grid: list[list[str]], komi: float = 6.5) -> str` — `(;GM[1]FF[4]CA[UTF-8]SZ[n]KM[k]PL[B]AB[..]AW[..])` 形式の SGF 文字列。石が0個なら `CaptureError`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_capture.py` に追記:

```python
from katrain.core.tsumego_capture import grid_to_sgf


def _empty_grid(size=13):
    return [["." for _ in range(size)] for _ in range(size)]


def test_grid_to_sgf():
    grid = _empty_grid()
    grid[0][1] = "B"  # i=0(上端行), j=1(左から2列目) → SGF座標 "ba"（列j→1文字目, 行i→2文字目）
    grid[12][12] = "W"  # 右下隅 → "mm"
    sgf = grid_to_sgf(grid, komi=6.5)
    assert sgf == "(;GM[1]FF[4]CA[UTF-8]SZ[13]KM[6.5]PL[B]AB[ba]AW[mm])"


def test_grid_to_sgf_empty_board_raises():
    with pytest.raises(CaptureError):
        grid_to_sgf(_empty_grid())


def test_grid_to_sgf_parses_in_katrain():
    # KaTrain 本体のパーサで読めて黒番になることを保証する結合テスト
    from katrain.core.sgf_parser import SGF

    grid = _empty_grid()
    grid[2][3] = "B"
    grid[5][6] = "W"
    root = SGF.parse_sgf(grid_to_sgf(grid))
    assert root.get_property("SZ") == "13"
    assert root.initial_player == "B"
    assert root.get_list_property("AB") == ["dc"]
    assert root.get_list_property("AW") == ["gf"]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -v`
Expected: 新規3件が FAIL（`ImportError: cannot import name 'grid_to_sgf'`）

- [ ] **Step 3: `grid_to_sgf` を実装**

`katrain/core/tsumego_capture.py` に追加:

```python
def grid_to_sgf(grid, komi=6.5):
    """認識グリッドを黒番の SGF 文字列にする（AB/AW 配置・PL[B]）"""
    size = len(grid)
    ab = [chr(97 + j) + chr(97 + i) for i, row in enumerate(grid) for j, v in enumerate(row) if v == "B"]
    aw = [chr(97 + j) + chr(97 + i) for i, row in enumerate(grid) for j, v in enumerate(row) if v == "W"]
    if not ab and not aw:
        raise CaptureError("石が1つも見つかりません（詰碁が表示されているか確認してください）")
    sgf = f"(;GM[1]FF[4]CA[UTF-8]SZ[{size}]KM[{komi}]PL[B]"
    if ab:
        sgf += "AB" + "".join(f"[{p}]" for p in ab)
    if aw:
        sgf += "AW" + "".join(f"[{p}]" for p in aw)
    return sgf + ")"
```

補足: `parse_sgf` は `sgf_parser.py:417` の `class SGF`（408行）のクラスメソッドで、`SGFNode` を返す（確認済み）。`KaTrainSGF` はその KaTrain 版サブクラス。

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -v`
Expected: 6 PASS

- [ ] **Step 5: コミット**

```powershell
git add katrain/core/tsumego_capture.py tests/test_tsumego_capture.py
git commit -m "feat(tsumego-capture): 認識グリッドからのSGF生成を実装"
```

---

### Task 4: ウィンドウキャプチャ・オーケストレーション・デバッグCLI

**Files:**
- Modify: `katrain/core/tsumego_capture.py`（関数追加）
- Modify: `tests/test_tsumego_capture.py`（CLIスモークテスト追加）

**Interfaces:**
- Consumes: `detect_board` / `classify_intersections` / `grid_to_sgf` / `CaptureError`（Task 1〜3）
- Produces:
  - `find_window_rect(title_substring: str) -> tuple[int, int, int, int]` — 可視ウィンドウをタイトル部分一致（大小無視）で検索し画面座標 `(left, top, right, bottom)` を返す。無ければ `CaptureError`
  - `capture_screen_rect(rect: tuple[int, int, int, int]) -> PIL.Image.Image`
  - `capture_tsumego_sgf(settings: dict, komi: float = 6.5) -> str` — 全体オーケストレーション。settings キー: `window_title`, `board_size`
  - CLI: `python -m katrain.core.tsumego_capture --image PATH | --window [--title T] [--size N]`

- [ ] **Step 1: 失敗するテスト（CLIスモーク）を書く**

`tests/test_tsumego_capture.py` に追記:

```python
import subprocess
import sys


def test_cli_image_mode():
    result = subprocess.run(
        [sys.executable, "-m", "katrain.core.tsumego_capture", "--image", SAMPLE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "SZ[13]" in result.stdout
    assert "PL[B]" in result.stdout
    # ASCII盤面が13行出力される
    board_lines = [ln for ln in result.stdout.splitlines() if ln and all(c in "BW. " for c in ln)]
    assert len(board_lines) == 13
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_capture.py::test_cli_image_mode -v`
Expected: FAIL（CLI 未実装のため returncode != 0）

- [ ] **Step 3: キャプチャ関数と CLI を実装**

`katrain/core/tsumego_capture.py` に追加:

```python
def find_window_rect(title_substring):
    """タイトル部分一致（大小無視）で可視ウィンドウを探し、画面座標 (left, top, right, bottom) を返す"""
    user32 = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 座標のDPI仮想化を防ぐ。設定済みなら失敗するが無視
    except OSError:
        pass
    matches = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_substring.lower() in buf.value.lower():
                    rect = ctypes.wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if rect.right - rect.left > 200 and rect.bottom - rect.top > 200:
                        matches.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    user32.EnumWindows(enum_cb, 0)
    if not matches:
        raise CaptureError(f"ウィンドウが見つかりません: {title_substring}（起動・最小化解除を確認してください）")
    return matches[0]


def capture_screen_rect(rect):
    """画面座標 rect の領域をキャプチャして PIL Image を返す（マルチモニタの仮想座標に対応）"""
    left, top, right, bottom = rect
    img = ImageGrab.grab(all_screens=True)
    vx = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    return img.crop((left - vx, top - vy, right - vx, bottom - vy))


def capture_tsumego_sgf(settings, komi=6.5):
    """ウィンドウ検出→キャプチャ→認識→SGF生成の全体処理。失敗は CaptureError"""
    rect = find_window_rect(settings.get("window_title", DEFAULT_WINDOW_TITLE))
    img = capture_screen_rect(rect)
    board_rect = detect_board(img)
    grid = classify_intersections(img, board_rect, int(settings.get("board_size", DEFAULT_BOARD_SIZE)))
    return grid_to_sgf(grid, komi=komi)


def main():
    import os

    os.environ["KIVY_NO_ARGS"] = "1"  # 慣例(本モジュールはKivy非import): Kivyの引数横取り防止
    import argparse

    parser = argparse.ArgumentParser(description="Tsumego capture debug CLI")
    parser.add_argument("--image", help="保存済みスクリーンショットを解析（ライブキャプチャの代わり）")
    parser.add_argument("--window", action="store_true", help="ウィンドウからライブキャプチャして解析")
    parser.add_argument("--title", default=DEFAULT_WINDOW_TITLE, help="ウィンドウタイトルの部分一致文字列")
    parser.add_argument("--size", type=int, default=DEFAULT_BOARD_SIZE, help="盤サイズ")
    args = parser.parse_args()
    try:
        if args.image:
            img = Image.open(args.image)
        elif args.window:
            img = capture_screen_rect(find_window_rect(args.title))
        else:
            parser.error("--image か --window を指定してください")
        board_rect = detect_board(img)
        print(f"board rect: {board_rect}")
        grid = classify_intersections(img, board_rect, args.size)
    except CaptureError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)
    for row in grid:
        print(" ".join(row))
    print(grid_to_sgf(grid))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -v`
Expected: 7 PASS

- [ ] **Step 5: CLI を手動でも一度実行して出力を目視確認**

Run: `python -m katrain.core.tsumego_capture --image tests/data/tsumego_app_sample.png`
Expected: `board rect: (...)` + 13行の ASCII 盤面（左上に W/B の塊）+ `(;GM[1]FF[4]...PL[B]AB[...]AW[...])`

- [ ] **Step 6: コミット**

```powershell
git add katrain/core/tsumego_capture.py tests/test_tsumego_capture.py
git commit -m "feat(tsumego-capture): ウィンドウキャプチャとデバッグCLIを実装"
```

---

### Task 5: 依存パッケージと設定の追加（※ローカル config はメインセッション限定）

**Files:**
- Modify: `pyproject.toml`（dependencies に keyboard / pillow 追加）
- Modify: `katrain/config.json`（`tsumego_capture` セクション追加）
- Modify: `C:\Users\iwaki\.katrain\config.json`（同セクション追加。**メインセッションで直接 Edit。サブエージェント委任禁止**）

**Interfaces:**
- Consumes: なし
- Produces: config セクション `tsumego_capture`（キー: `enabled`, `hotkey`, `window_title`, `board_size`, `frame_margin`, `frame_ko`）。Task 6 のグルーコードが `self._config.get("tsumego_capture")` で読む

- [ ] **Step 1: keyboard パッケージをインストール**

Run: `python -m pip install keyboard`
Expected: `Successfully installed keyboard-0.13.5`（バージョンは最新でよい）

- [ ] **Step 2: pyproject.toml の dependencies に追加**

`pyproject.toml` の `dependencies` リスト末尾（`"kivymd==0.104.1",` の後）に追加:

```toml
    "pillow>=10",
    "keyboard>=0.13.5 ; platform_system == 'Windows'",
```

- [ ] **Step 3: パッケージ config.json にセクション追加**

`katrain/config.json` の `"game"` セクションの閉じ括弧の後に追加（JSON の カンマ位置に注意）:

```json
    "tsumego_capture": {
        "enabled": true,
        "hotkey": "ctrl+shift+g",
        "window_title": "BlueStacks",
        "board_size": 13,
        "frame_margin": 4,
        "frame_ko": false
    },
```

- [ ] **Step 4: JSON 構文チェック**

Run: `python -c "import json; json.load(open('katrain/config.json', encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 5: ローカル config.json に同セクション追加（メインセッションで直接 Edit）**

`C:\Users\iwaki\.katrain\config.json` に Step 3 と同じ `tsumego_capture` セクションを追加する。**このステップはサブエージェントに委任せず、必ずメインセッションで Edit ツールを使うこと**（CLAUDE.md ルール: サブエージェントが成功報告しても反映されないことがある）。

Run: `python -c "import json; json.load(open(r'C:\Users\iwaki\.katrain\config.json', encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 6: コミット（リポジトリ内ファイルのみ）**

```powershell
git add pyproject.toml katrain/config.json
git commit -m "feat(tsumego-capture): keyboard依存と設定セクションを追加"
```

---

### Task 6: GUI グルーコード（ホットキー登録→認識→盤面反映+外枠適用）

**Files:**
- Modify: `katrain/__main__.py`

**Interfaces:**
- Consumes:
  - `capture_tsumego_sgf(settings, komi)` / `CaptureError`（Task 4）
  - config セクション `tsumego_capture`（Task 5）
  - 既存: `KaTrainSGF.parse_sgf(str)`（`__main__.py:98` で import 済み）、`self._do_new_game(move_tree=...)`（`__main__.py:352`）、`self._do_tsumego_frame(ko, margin)`（`__main__.py:530`）、`self.config("game/komi", 6.5)`、`self.log(msg, OUTPUT_ERROR)`（STATUS 表示連動）、メッセージループ `self("message-name", ...)`
- Produces: KaTrainGui メソッド `_setup_tsumego_capture()` / `_tsumego_capture_trigger()` / `_do_tsumego_capture_apply(sgf, ko, margin)`

**設計上の注意（実装前に読むこと）:**
- メッセージループは投入時の `game_id` と現在の `game_id` が違うメッセージを破棄する（`__main__.py:312`）。そのため「new-game」「tsumego-frame」を別メッセージで投入してはならない（前者で game_id が変わり後者が破棄される）。**単一メッセージ `tsumego-capture-apply` の中で両方を同期実行**する
- `self("tsumego-capture-apply", ...)` は `"popup"` で終わらない名前なのでメッセージキュー経由でメッセージループスレッドで実行される。これは popups.kv の `root.katrain("tsumego-frame", ...)` と同じ実行経路であり、`_do_new_game`/`_do_tsumego_frame` をこのスレッドから呼ぶのは既存の正常パターン
- keyboard のコールバックはリスナースレッドで走る。認識（数百ms）はそこで行い、Kivy 反映はメッセージキューに委ねる

- [ ] **Step 1: `KaTrainGui.start()` 末尾にセットアップ呼び出しを追加**

`katrain/__main__.py` の `start()`（186行付近）の末尾、`self._do_new_game(_log=False)` の後（else ブロックの外、メソッド末尾）に追加:

```python
        self._setup_tsumego_capture()
```

- [ ] **Step 2: KaTrainGui にメソッド3つを追加**

`_do_tsumego_frame`（530行付近）の直後に追加:

```python
    def _setup_tsumego_capture(self):
        settings = self._config.get("tsumego_capture") or {}
        if not settings.get("enabled", False):
            return
        try:
            import keyboard
        except ImportError:
            self.log("tsumego_capture: keyboard パッケージ未導入のためホットキー無効 (pip install keyboard)", OUTPUT_INFO)
            return
        hotkey = settings.get("hotkey", "ctrl+shift+g")
        try:
            keyboard.add_hotkey(hotkey, self._tsumego_capture_trigger)
            self._tsumego_capture_busy = False
            self.log(f"tsumego_capture: ホットキー {hotkey} を登録しました", OUTPUT_INFO)
        except Exception as e:
            self.log(f"tsumego_capture: ホットキー登録失敗: {e}", OUTPUT_ERROR)

    def _tsumego_capture_trigger(self):
        # keyboard リスナースレッドで実行される。認識までここで行い、反映はメッセージループに投げる
        from katrain.core.tsumego_capture import CaptureError, capture_tsumego_sgf

        if getattr(self, "_tsumego_capture_busy", False):
            return
        self._tsumego_capture_busy = True
        try:
            settings = self._config.get("tsumego_capture") or {}
            try:
                sgf = capture_tsumego_sgf(settings, komi=self.config("game/komi", 6.5))
            except CaptureError as e:
                self.log(f"詰碁キャプチャ失敗: {e}", OUTPUT_ERROR)
                return
            except Exception as e:
                self.log(f"詰碁キャプチャで予期しないエラー: {e}", OUTPUT_ERROR)
                return
            self.log(f"詰碁キャプチャ成功: {sgf}", OUTPUT_DEBUG)
            self(
                "tsumego-capture-apply",
                sgf,
                settings.get("frame_ko", False),
                int(settings.get("frame_margin", 4)),
            )
        finally:
            self._tsumego_capture_busy = False

    def _do_tsumego_capture_apply(self, sgf, ko, margin):
        # メッセージループスレッドで実行。new-game と tsumego-frame を同一メッセージ内で行う
        # （分割すると new-game で game_id が変わり後続メッセージが破棄されるため）
        try:
            move_tree = KaTrainSGF.parse_sgf(sgf)
        except ParseError as e:
            self.log(f"詰碁キャプチャSGF解析失敗: {e}", OUTPUT_ERROR)
            return
        self._do_new_game(move_tree=move_tree)
        self._do_tsumego_frame(ko=ko, margin=margin)
        self.controls.set_status("詰碁盤面を取り込みました", STATUS_INFO)

        def raise_window(_dt):
            try:
                Window.restore()
                Window.raise_window()
            except Exception as e:
                self.log(f"tsumego_capture: ウィンドウ前面化失敗: {e}", OUTPUT_DEBUG)

        Clock.schedule_once(raise_window, 0.1)
```

- [ ] **Step 3: import の確認**

`katrain/__main__.py` の既存 import に以下が含まれることを Grep で確認し、無ければ追加:
- `OUTPUT_DEBUG`（`katrain.core.constants` からの import 群、73行付近）
- `Window`（`from kivy.core.window import Window`）
- `Clock`（`from kivy.clock import Clock`）
- `KaTrainSGF` / `ParseError`（98-99行に import 済みのはず）

Run: `python -c "import ast; ast.parse(open('katrain/__main__.py', encoding='utf-8').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 4: 既存テストが壊れていないことを確認**

Run: `python -m pytest tests/test_tsumego_capture.py tests/test_parser.py -v`
Expected: 全 PASS（`__main__.py` はテストから import されないが念のため周辺テストも実行）

- [ ] **Step 5: KaTrain 起動スモークテスト**

Run: `python -m katrain` を起動し、コンソール/ログに `tsumego_capture: ホットキー ctrl+shift+g を登録しました` が出ることを確認（`C:\Users\iwaki\.katrain\config.json` の `debug_level` が 0 でも OUTPUT_INFO は出る。出ない場合は Grep でログファイル確認）。確認後終了。
Expected: 起動正常・ホットキー登録ログあり

- [ ] **Step 6: コミット**

```powershell
git add katrain/__main__.py
git commit -m "feat(tsumego-capture): ホットキーからの盤面反映と外枠自動適用を実装"
```

---

### Task 7: E2E 検証とドキュメント更新

**Files:**
- Modify: `CLAUDE.md`（概要・ディレクトリ構造に1行ずつ追記）
- Modify: `docs/superpowers/specs/2026-07-28-tsumego-capture-design.md`（実測結果を追記、閾値を変更した場合はその値も）

**Interfaces:**
- Consumes: 全タスクの成果物
- Produces: 動作確認済みの機能とドキュメント

- [ ] **Step 1: ライブキャプチャを CLI で検証（KaTrain 不要）**

BlueStacks で詰碁を表示した状態で:

Run: `python -m katrain.core.tsumego_capture --window`
Expected: ASCII 盤面が BlueStacks の表示と一致。不一致の交点があれば閾値を調整し `python -m pytest tests/test_tsumego_capture.py -v` が通ることを再確認

- [ ] **Step 2: E2E 検証（ユーザー実施でも可）**

1. BlueStacks で詰碁を表示
2. `python -m katrain` で KaTrain を起動
3. `Ctrl+Shift+G` を押す
4. 確認項目:
   - KaTrain の盤面に石が正しく配置される（13路）
   - 詰碁外枠が自動生成され、解析リージョンが問題領域に設定される
   - 黒番になっている（次の手番表示が黒）
   - KaTrain ウィンドウが前面に出る
   - ホットキー押下から盤面完成まで 5 秒以内
5. エラー系: BlueStacks を最小化して `Ctrl+Shift+G` → ステータスバーに「ウィンドウが見つかりません」系のエラーが出て KaTrain は正常動作を継続

- [ ] **Step 3: CLAUDE.md に追記**

- 「概要」の主な改修の末尾に追記: `詰碁画面キャプチャ（tsumego_capture: グローバルホットキーでBlueStacks上の詰碁アプリ盤面を認識しKaTrainに反映+外枠自動適用）を追加`
- 「ディレクトリ構造」の `core/` 配下に追記: `tsumego_capture.py   -- 詰碁アプリ画面キャプチャ→盤面認識→SGF化（Kivy非依存、CLI: python -m katrain.core.tsumego_capture）`

- [ ] **Step 4: 設計書に実測結果を追記**

`docs/superpowers/specs/2026-07-28-tsumego-capture-design.md` の末尾に「実装結果」セクションを追加し、E2E での所要時間実測値・調整した閾値（あれば）を記録する。

- [ ] **Step 5: 最終テストとコミット**

Run: `python -m pytest tests/test_tsumego_capture.py -v`
Expected: 全 PASS

```powershell
git add CLAUDE.md docs/superpowers/specs/2026-07-28-tsumego-capture-design.md
git commit -m "docs(tsumego-capture): E2E検証結果とドキュメントを更新"
```
