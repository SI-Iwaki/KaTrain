# 対局盤面の監視モード（board_watch）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BlueStacks の囲碁対局アプリの盤面を定期的に画面認識し、相手 AI の着手を KaTrain へ「人間側の手」として即時注入する監視モードを追加する。

**Architecture:** Kivy 非依存の新モジュール `katrain/core/board_watch.py` に判定ロジック（純関数）とポーリングスレッドを閉じ込め、`katrain/__main__.py` は配線（ホットキー・状態取得・着手注入・バナー）だけを持つ。判定の中核は「観測グリッドに1手打って **完全一致するまで確定しない**」という1本の規則で、取り・アニメーション途中フレーム・ホバー石を同じ仕組みで吸収する。

**Tech Stack:** Python 3.12 / Kivy / Pillow（`ImageGrab`）/ Win32 `RegisterHotKey`・`GetWindowRect`（ctypes）/ pytest

**Spec:** `docs/superpowers/specs/2026-08-18-board-watch-design.md`

**検算済み:** Task 2〜7 のコードとテスト期待値は、計画作成時にプロトタイプとして実際に走らせて **37件すべて PASS** を確認してある（取りの盤面・自殺手・reconcile の優先順位・デバウンス・注入ガード・タイムアウト・バックオフ・ウォッチドッグ・`run()` の例外耐性）。テストが落ちたら、まず**写し間違い**を疑うこと。

## Global Constraints

- **Windows 専用**。`sys.platform != "win32"` では登録せずログのみ（既存 `_setup_tsumego_capture` と同じゲート）。
- **グローバルホットキーは `Theme.KEY_*` と重ねない**。`RegisterHotKey` はフォーカス窓からキーを奪う。既定は `ctrl+alt+b`。`f9` は `Theme.KEY_CONTRIBUTE_POPUP`（`theme.py:191`）なので**使用禁止**。
- **新しい設定キーはパッケージ `katrain/config.json` と `C:\Users\iwaki\.katrain\config.json` の両方に追加する**（後者はマージされない）。ローカル側は **KaTrain を終了した状態でメインセッションから直接 Edit**（サブエージェントに委任しない／起動中に編集すると終了時の書き戻しで消える）。
- **`config("a/b")` は2階層固定**（`base_katrain.py:261-270`）。`board_watch` はトップレベルブロックにフラットなキーだけを置く。
- **詰碁経路の認識関数（`_classify_patch` / `detect_board` / `_grid_line_score` 等）を変更しない**。閾値調整が要る場合も別関数として足す（認識条件を変える改修は「以前成功していた側の破損率」測定が必要になり、詰碁の校正資産を巻き込む）。
- **判定ロジックを `__main__.py` に置かない**（テストから import できないため）。座標変換も純関数として `board_watch.py` に置く。
- **コミットメッセージは日本語・Conventional Commits**（`feat:` / `fix:` / `docs:` / `refactor:`）。
- **`print` は ASCII のみ**（cp932 端末で `UnicodeEncodeError`）。ファイル書き出しは `PYTHONIOENCODING=utf-8`。
- **ログの確認は Grep**（Read で全読みしない）。
- **`detect_size_and_classify` の戻り値は `(size, grid)` の順**（`tsumego_capture.py:215`）。`(grid, size)` ではない。
- 既存テストは `pytest tests/ --ignore=tests/test_ai.py`（771件）。本計画で追加するテストは KataGo も Kivy も不要。

---

### Task 1: スパイク — 対局アプリで既存の認識器が通るか確かめる

**これは実装タスクではなく調査タスク。** 結果次第で Task 2 以降の前提が変わる（最悪、対局アプリ用の別認識経路が必要になる）。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/board-watch/spike_capture.py`
- Create: `docs/superpowers/specs/calibration-data/board-watch/spike-results-20260818.md`

**Interfaces:**
- Consumes: `katrain.core.tsumego_capture` の `find_window_rect` / `capture_screen_rect` / `detect_board` / `detect_size_and_classify`
- Produces: 2枚の実スクショ（`tests/data/board_watch_before.png` / `board_watch_after.png`）と、その期待グリッド。Task 13 の回帰テストがこれを使う

- [ ] **Step 1: スパイクスクリプトを書く**

`docs/superpowers/specs/calibration-data/board-watch/spike_capture.py`:

```python
"""対局アプリの盤面が既存の認識器で読めるかを確かめるスパイク。

使い方（BlueStacks で対局アプリを開き、盤面が画面に見えている状態で）:
    python docs/superpowers/specs/calibration-data/board-watch/spike_capture.py --save tests/data/board_watch_before.png

出力は ASCII のみ（cp932 端末対策）。
"""
import argparse
import os
import sys

os.environ["KIVY_NO_ARGS"] = "1"  # 慣例（本スクリプトは Kivy 非 import）

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from katrain.core.tsumego_capture import (  # noqa: E402
    CaptureError,
    capture_screen_rect,
    detect_board,
    detect_size_and_classify,
    find_window_rect,
)


def main():
    parser = argparse.ArgumentParser(description="board_watch spike: recognize the game app board")
    parser.add_argument("--title", default="BlueStacks", help="window title substring")
    parser.add_argument("--save", help="save the captured screenshot to this path")
    parser.add_argument("--sizes", default="9,13,19", help="candidate board sizes")
    args = parser.parse_args()

    rect = find_window_rect(args.title)
    print(f"window rect: {rect}")
    img = capture_screen_rect(rect)
    if args.save:
        img.save(args.save)
        print(f"saved: {args.save}")
    try:
        board_rect = detect_board(img)
    except CaptureError as e:
        print(f"ERROR detect_board: {e}")
        raise SystemExit(1)
    print(f"board rect: {board_rect}")
    sizes = [int(s) for s in args.sizes.split(",")]
    try:
        size, grid = detect_size_and_classify(img, board_rect, sizes)
    except CaptureError as e:
        print(f"ERROR detect_size_and_classify: {e}")
        raise SystemExit(1)
    print(f"board size: {size}")
    for row in grid:
        print(" ".join(row))
    counts = {"B": 0, "W": 0, ".": 0}
    for row in grid:
        for v in row:
            counts[v] += 1
    print(f"counts: B={counts['B']} W={counts['W']} empty={counts['.']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 対局アプリを開いてスパイクを実行（相手が打つ前）**

BlueStacks で対局アプリを開き、**数手進んだ対局**を表示する（最終手マーカーが見える状態にする）。KaTrain と並べて両方見えるように配置する。

Run:
```bash
python docs/superpowers/specs/calibration-data/board-watch/spike_capture.py --save tests/data/board_watch_before.png
```

確認すること（この順で、失敗したら Step 4 へ）:
1. `board rect` が盤の範囲になっているか（時計・取り石カウンタを巻き込んでいないか）
2. `board size` が正しいか
3. 出力グリッドが画面の石と**1子ずつ一致**するか
4. **最終手マーカーが乗っている石が正しく `B`/`W` と読めているか**（`.` に化けていないか）

- [ ] **Step 3: 相手が1手打った後にもう一度実行**

アプリ側で自分が1手打ち、相手 AI が応じるのを待ってから:

```bash
python docs/superpowers/specs/calibration-data/board-watch/spike_capture.py --save tests/data/board_watch_after.png
```

2枚のグリッドの差が**ちょうど相手の1手ぶん**（取りがあれば取られた石も）になっていることを確認する。

- [ ] **Step 4: 結果を記録する**

`docs/superpowers/specs/calibration-data/board-watch/spike-results-20260818.md` に記録する。テンプレート:

```markdown
# board_watch スパイク結果（2026-08-18）

対象アプリ: <アプリ名>/ ウィンドウタイトル: <実際にマッチした文字列>

| 確認項目 | 結果 |
|---|---|
| detect_board が盤の範囲を返す | OK / NG（詳細） |
| 盤サイズ判定 | OK（19路）/ NG |
| 石の分類が画面と一致 | OK / NG（食い違った座標） |
| 最終手マーカーの石の分類 | B/W と読めた / "." に化けた / "?" で CaptureError |
| 2枚の差が相手の1手ぶん | OK / NG |

## 判定

- [ ] 既存の認識器がそのまま使える → Task 2 へ進む
- [ ] 最終手マーカーで石が "." に化ける → 設計どおり §2.5(c) の進捗ウォッチドッグが要る（Task 6 で実装）。
      加えて board_watch 専用の分類関数が必要かをここで判断する（**詰碁経路の関数は変更しない**）
- [ ] 盤が検出できない → 設計の前提が崩れる。ここで止めてユーザーと相談する

## 生データ

（spike_capture.py の出力を貼る）
```

- [ ] **Step 5: コミット**

```bash
git add docs/superpowers/specs/calibration-data/board-watch/ tests/data/board_watch_before.png tests/data/board_watch_after.png
git commit -m "spike(board-watch): 対局アプリの盤面認識を実測し、実スクショ2枚を回帰用に追加"
```

---

### Task 2: 座標変換の純関数（`stones_to_grid` / `move_to_grid` / `grid_to_move`）

**Files:**
- Create: `katrain/core/board_watch.py`
- Create: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `EMPTY = "."` / `BLACK = "B"` / `WHITE = "W"`
  - `stones_to_grid(stones, size) -> list[list[str]]` — `stones` は `(coords, player)` のイテラブル。`coords` は KaTrain の `(x, y)`（**下origin**）、`None`（パス）は無視
  - `move_to_grid(coords, size) -> tuple[int, int] | None` — 下origin `(x, y)` → 上origin `(i, j)`。`None` は `None`
  - `grid_to_move(i, j, size) -> tuple[int, int]` — 上origin `(i, j)` → 下origin `(x, y)`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_board_watch.py`:

```python
from katrain.core.board_watch import EMPTY, grid_to_move, move_to_grid, stones_to_grid


def test_stones_to_grid_uses_top_origin_rows():
    # KaTrain の (x=0, y=0) は盤の左下 = グリッドの最終行の先頭
    grid = stones_to_grid([((0, 0), "B"), ((2, 2), "W")], 3)
    assert grid == [
        [EMPTY, EMPTY, "W"],
        [EMPTY, EMPTY, EMPTY],
        ["B", EMPTY, EMPTY],
    ]


def test_stones_to_grid_ignores_pass():
    assert stones_to_grid([(None, "B")], 2) == [[EMPTY, EMPTY], [EMPTY, EMPTY]]


def test_move_to_grid_round_trip():
    size = 19
    for x in range(size):
        for y in range(size):
            i, j = move_to_grid((x, y), size)
            assert grid_to_move(i, j, size) == (x, y)


def test_move_to_grid_pass_is_none():
    assert move_to_grid(None, 19) is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'katrain.core.board_watch'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/board_watch.py`:

```python
"""対局アプリの盤面を監視して、相手の着手を KaTrain へ注入するためのロジック。

Kivy にも KataGo にも依存しない（テストから直接 import できるようにするため）。
設計は docs/superpowers/specs/2026-08-18-board-watch-design.md 参照。

座標系に注意: 認識グリッド grid[i][j] の i は**画面上origin**（tsumego_capture.py:100）、
KaTrain の Move.coords = (x, y) は **y が下origin**（sgf_parser.py:31-39）。
この変換漏れは実測済みのバグ源なので、変換は必ずこのモジュールの純関数を通す。
"""

EMPTY = "."
BLACK = "B"
WHITE = "W"


def stones_to_grid(stones, size):
    """(coords, player) の列（coords は KaTrain の下origin (x, y)）を上origin グリッドにする"""
    grid = [[EMPTY] * size for _ in range(size)]
    for coords, player in stones:
        if coords is None:  # パスは盤に石を置かない
            continue
        x, y = coords
        grid[size - 1 - y][x] = player
    return grid


def move_to_grid(coords, size):
    """KaTrain の Move.coords (x, y) → グリッド座標 (i, j)。パス（None）は None"""
    if coords is None:
        return None
    x, y = coords
    return (size - 1 - y, x)


def grid_to_move(i, j, size):
    """グリッド座標 (i, j) → KaTrain の Move.coords (x, y)"""
    return (j, size - 1 - i)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: PASS（4件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board-watch): 盤面グリッドと KaTrain 座標の変換を純関数として追加"
```

---

### Task 3: `apply_move_to_grid`（取りと自殺手の処理）

**Files:**
- Modify: `katrain/core/board_watch.py`
- Modify: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: `EMPTY` / `BLACK` / `WHITE`
- Produces: `apply_move_to_grid(grid, i, j, color) -> list[list[str]] | None` — 打てないとき（盤外・既石・自殺手）は `None`。取りは処理済みの新グリッドを返す（引数は破壊しない）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_board_watch.py` に追記（import 行に `apply_move_to_grid` を追加する）:

```python
from katrain.core.board_watch import apply_move_to_grid  # 既存の import 行に足す


def _grid(rows):
    """'.BW' の文字列行からグリッドを作る（行は上origin）"""
    return [list(r) for r in rows]


def test_apply_move_places_stone():
    out = apply_move_to_grid(_grid(["...", "...", "..."]), 1, 1, "B")
    assert out == _grid(["...", ".B.", "..."])


def test_apply_move_rejects_occupied_point():
    assert apply_move_to_grid(_grid(["B.."]), 0, 0, "W") is None


def test_apply_move_rejects_out_of_board():
    assert apply_move_to_grid(_grid(["..", ".."]), 2, 0, "B") is None


def test_apply_move_captures_single_stone():
    # 白1子 (2,0) の呼吸点は (2,1) だけ。黒がそこに打つと取れる
    before = _grid([
        "...",
        "B..",
        "W..",
    ])
    out = apply_move_to_grid(before, 2, 1, "B")
    assert out == _grid([
        "...",
        "B..",
        ".B.",
    ])
    assert before == _grid(["...", "B..", "W.."])  # 引数は破壊しない


def test_apply_move_captures_multi_stone_group():
    # 白2子 {(1,1),(1,2)} の呼吸点は (1,3) だけ
    before = _grid([
        ".BB.",
        "BWW.",
        ".BB.",
        "....",
    ])
    out = apply_move_to_grid(before, 1, 3, "B")
    assert out == _grid([
        ".BB.",
        "B..B",
        ".BB.",
        "....",
    ])


def test_apply_move_rejects_suicide():
    # 四方を白の独立した1子に囲まれた点。どの白も呼吸点が残るので取れず、自分が窒息する
    before = _grid([
        ".W.",
        "W.W",
        ".W.",
    ])
    assert apply_move_to_grid(before, 1, 1, "B") is None


def test_apply_move_capture_frees_own_liberties():
    # 打つ点そのものは呼吸点0だが、先に白3子を取るので合法（取り→自殺判定の順序）
    before = _grid([
        ".WB",
        "WWB",
        "BB.",
    ])
    out = apply_move_to_grid(before, 0, 0, "B")
    assert out == _grid([
        "B.B",
        "..B",
        "BB.",
    ])
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: FAIL（`ImportError: cannot import name 'apply_move_to_grid'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/board_watch.py` に追記:

```python
def _neighbours(i, j, size):
    for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ni, nj = i + di, j + dj
        if 0 <= ni < size and 0 <= nj < size:
            yield ni, nj


def _group_and_liberties(grid, i, j):
    """(i, j) の石と同色で連結した石の集合と、その呼吸点の集合を返す"""
    size = len(grid)
    color = grid[i][j]
    stack = [(i, j)]
    group = {(i, j)}
    liberties = set()
    while stack:
        ci, cj = stack.pop()
        for ni, nj in _neighbours(ci, cj, size):
            v = grid[ni][nj]
            if v == EMPTY:
                liberties.add((ni, nj))
            elif v == color and (ni, nj) not in group:
                group.add((ni, nj))
                stack.append((ni, nj))
    return group, liberties


def apply_move_to_grid(grid, i, j, color):
    """グリッドに1手打ち、取りを処理した新グリッドを返す。打てないときは None。

    コウは判定しない（グリッド1枚では履歴が無いため）。コウ違反はエンジン側が
    弾き、注入ガードのタイムアウトとして表面化する（spec §2.5b）。
    """
    size = len(grid)
    if not (0 <= i < size and 0 <= j < size) or grid[i][j] != EMPTY:
        return None
    opponent = WHITE if color == BLACK else BLACK
    new_grid = [row[:] for row in grid]
    new_grid[i][j] = color
    for ni, nj in _neighbours(i, j, size):
        if new_grid[ni][nj] == opponent:
            group, liberties = _group_and_liberties(new_grid, ni, nj)
            if not liberties:
                for gi, gj in group:
                    new_grid[gi][gj] = EMPTY
    _group, liberties = _group_and_liberties(new_grid, i, j)
    if not liberties:
        return None  # 自殺手（取りを処理した後でも呼吸点が無い）
    return new_grid
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board-watch): グリッドに1手打って取りを処理する純関数を追加"
```

---

### Task 4: `WatchState` / `Verdict` / `reconcile`

**Files:**
- Modify: `katrain/core/board_watch.py`
- Modify: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: `apply_move_to_grid`, `EMPTY`
- Produces:
  - `WatchState(current_grid, last_move, to_play, to_play_is_human, ai_can_respond, move_number, board_size)` — `last_move` は `(i, j, color)` か `None`（パス・root は `None`）
  - `Verdict(kind, move, reason)` — `kind` は `"in_sync"` / `"waiting"` / `"ahead"` / `"move"` / `"mismatch"`、`move` は `kind == "move"` のとき `(i, j)`
  - `reconcile(state, observed) -> Verdict`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_board_watch.py` に追記:

```python
from katrain.core.board_watch import WatchState, reconcile  # 既存の import 行に足す


def _state(current, to_play="B", last_move=None, human=True, ai_ok=True, move_number=1):
    return WatchState(
        current_grid=current,
        last_move=last_move,
        to_play=to_play,
        to_play_is_human=human,
        ai_can_respond=ai_ok,
        move_number=move_number,
        board_size=len(current),
    )


def test_reconcile_board_size_mismatch_wins_first():
    state = _state(_grid(["...", "...", "..."]))
    verdict = reconcile(state, _grid(["..", ".."]))
    assert verdict.kind == "mismatch"
    assert "盤サイズ" in verdict.reason


def test_reconcile_ai_cannot_respond_is_mismatch_even_when_boards_agree():
    board = _grid(["...", "...", "..."])
    verdict = reconcile(_state(board, ai_ok=False), board)
    assert verdict.kind == "mismatch"


def test_reconcile_ai_turn_is_silent_waiting():
    board = _grid(["...", "...", "..."])
    verdict = reconcile(_state(board, human=False), board)
    assert verdict.kind == "waiting"


def test_reconcile_ai_turn_never_injects_even_if_a_move_fits():
    # 色の割り当てが逆なら、相手の石が to_play と同色になって「1手で説明できる」が、
    # AI の手番では絶対に注入しない
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B", human=False), observed)
    assert verdict.kind == "waiting"


def test_reconcile_in_sync():
    board = _grid([".B.", "...", "..W"])
    assert reconcile(_state(board), board).kind == "in_sync"


def test_reconcile_detects_opponent_move():
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B"), observed)
    assert verdict.kind == "move"
    assert verdict.move == (1, 1)


def test_reconcile_detects_move_with_capture():
    # 白1子 (2,0) の呼吸点は (2,1) だけ。黒がそこに打つと白が消える
    current = _grid(["...", "B..", "W.."])
    observed = _grid(["...", "B..", ".B."])
    verdict = reconcile(_state(current, to_play="B"), observed)
    assert verdict.kind == "move"
    assert verdict.move == (2, 1)


def test_reconcile_ahead_when_katrain_played_but_app_has_not():
    current = _grid(["...", ".W.", "..."])
    observed = _grid(["...", "...", "..."])
    state = _state(current, to_play="B", last_move=(1, 1, "W"))
    assert reconcile(state, observed).kind == "ahead"


def test_reconcile_root_position_has_no_last_move():
    # 対局開始直後（KaTrain 側 AI が白＝相手が先着）。last_move=None でも落ちない
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B", last_move=None, move_number=0), observed)
    assert verdict.kind == "move"


def test_reconcile_after_pass_has_no_last_move():
    # パス直後は last_move が None として渡ってくる（__main__ 側で coords=None を落とす）
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B", last_move=None), observed)
    assert verdict.kind == "move"


def test_reconcile_wrong_color_stone_is_mismatch():
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".W.", "..."])
    verdict = reconcile(_state(current, to_play="B"), observed)
    assert verdict.kind == "mismatch"


def test_reconcile_two_moves_ahead_is_mismatch():
    current = _grid(["...", "...", "..."])
    observed = _grid(["W..", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B"), observed)
    assert verdict.kind == "mismatch"


def test_reconcile_single_noise_stone_removed_is_mismatch():
    current = _grid([".B.", "...", "..W"])
    observed = _grid([".B.", "...", "..."])
    state = _state(current, to_play="B", last_move=(0, 1, "B"))
    assert reconcile(state, observed).kind == "mismatch"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: FAIL（`ImportError: cannot import name 'WatchState'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/board_watch.py` の先頭付近に `from typing import NamedTuple, Optional, Tuple` を足し、末尾に追記:

```python
class WatchState(NamedTuple):
    """KaTrain 側の局面スナップショット（__main__ が作り、判定はここでだけ行う）"""

    current_grid: list
    last_move: Optional[Tuple[int, int, str]]  # (i, j, color)。root とパスは None
    to_play: str
    to_play_is_human: bool
    ai_can_respond: bool
    move_number: int
    board_size: int


class Verdict(NamedTuple):
    kind: str  # "in_sync" | "waiting" | "ahead" | "move" | "mismatch"
    move: Optional[Tuple[int, int]] = None
    reason: str = ""


def reconcile(state, observed):
    """観測グリッドが「現局面＋打つ側の1手」で説明できるかを判定する。

    表は**上から評価する優先順位**（spec §2.3）。特に「AI の手番なら絶対に注入しない」
    （waiting）を Move 判定より前に置くのが安全弁の要 — 色の割り当てが逆だと相手の石が
    常に to_play と同色になり、Move 判定が成立してしまう。
    """
    if len(observed) != state.board_size:
        return Verdict(
            "mismatch",
            reason=f"盤サイズが違います（アプリ {len(observed)}路 / KaTrain {state.board_size}路）",
        )
    if not state.ai_can_respond:
        return Verdict("mismatch", reason="AI が応手できない局面です（分岐・終局・解析モード・リージョン）")
    if not state.to_play_is_human:
        # KaTrain の AI が考えている最中。正常状態なので無音（数秒続くため警告にしてはいけない）。
        # 色の割り当てが逆でここから永久に出られないケースは BoardWatcher のウォッチドッグが拾う
        return Verdict("waiting")
    if observed == state.current_grid:
        return Verdict("in_sync")
    if state.last_move is not None:
        li, lj, lcolor = state.last_move
        if apply_move_to_grid(observed, li, lj, lcolor) == state.current_grid:
            return Verdict("ahead")
    matches = []
    for i in range(state.board_size):
        for j in range(state.board_size):
            if observed[i][j] == state.to_play and state.current_grid[i][j] == EMPTY:
                if apply_move_to_grid(state.current_grid, i, j, state.to_play) == observed:
                    matches.append((i, j))
    if len(matches) == 1:
        return Verdict("move", move=matches[0])
    return Verdict("mismatch", reason="盤面の差が1手で説明できません")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board-watch): 観測盤面と現局面を突き合わせる reconcile を追加"
```

---

### Task 5: `board_sgf`（空盤でも作れる SGF 生成）

**Files:**
- Modify: `katrain/core/board_watch.py`
- Modify: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: `EMPTY`
- Produces: `board_sgf(grid, komi, rules, next_player) -> str` — `AB`/`AW` は石があるときだけ書く。**石が0個でも例外にしない**（`tsumego_capture.grid_to_sgf` は `CaptureError` を投げるので流用できない）

- [ ] **Step 1: 失敗するテストを書く**

```python
from katrain.core.board_watch import board_sgf  # 既存の import 行に足す


def test_board_sgf_empty_board_is_valid():
    sgf = board_sgf(_grid(["...", "...", "..."]), komi=6.5, rules="japanese", next_player="B")
    assert "SZ[3]" in sgf and "KM[6.5]" in sgf and "PL[B]" in sgf
    assert "AB" not in sgf and "AW" not in sgf


def test_board_sgf_places_stones_with_top_origin_rows():
    sgf = board_sgf(_grid(["B..", "...", "..W"]), komi=7.5, rules="chinese", next_player="W")
    assert "AB[aa]" in sgf
    assert "AW[cc]" in sgf
    assert "PL[W]" in sgf
    assert "RU[chinese]" in sgf


def test_board_sgf_parses_with_katrain_sgf_parser():
    from katrain.core.game import KaTrainSGF  # sgf_parser ではなく game.py:56 にある

    root = KaTrainSGF.parse_sgf(board_sgf(_grid(["B..", "...", "..W"]), 6.5, "japanese", "W"))
    assert root.board_size == (3, 3)
    assert root.next_player == "W"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: FAIL（`ImportError: cannot import name 'board_sgf'`）

- [ ] **Step 3: 最小実装を書く**

```python
_SGF_COORD = "abcdefghijklmnopqrstuvwxyz"


def board_sgf(grid, komi, rules, next_player):
    """監視モード用の SGF（配置のみ）。石が0個でも成立する。

    tsumego_capture.grid_to_sgf を流用しないのは、あれが石0個で CaptureError を投げ
    （詰碁向けの文言が出る）、PL[B] 固定でもあるため（spec §3.2）。
    """
    size = len(grid)
    black = [_SGF_COORD[j] + _SGF_COORD[i] for i, row in enumerate(grid) for j, v in enumerate(row) if v == BLACK]
    white = [_SGF_COORD[j] + _SGF_COORD[i] for i, row in enumerate(grid) for j, v in enumerate(row) if v == WHITE]
    sgf = f"(;GM[1]FF[4]CA[UTF-8]SZ[{size}]KM[{komi}]RU[{rules}]PL[{next_player}]"
    if black:
        sgf += "AB" + "".join(f"[{p}]" for p in black)
    if white:
        sgf += "AW" + "".join(f"[{p}]" for p in white)
    return sgf + ")"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board-watch): 空盤でも作れる監視用 SGF 生成を追加"
```

---

### Task 6: `WatchSettings` と `BoardWatcher.step()`（1周ぶんの判断）

スレッドとスリープを含めず、**1周ぶんを `step()` として切り出す**。テストは注入した偽クロックと偽フレーム列で `step()` を直接叩くので、`sleep` に依存する不安定なテストにならない。

**Files:**
- Modify: `katrain/core/board_watch.py`
- Modify: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: `reconcile`, `apply_move_to_grid`, `WatchState`
- Produces:
  - `WatchSettings(poll_interval_ms, stable_frames, failure_warn_frames, inject_timeout_ms, stall_warn_sec, resync_hint_frames, backoff_after_failures, backoff_factor, poll_interval_max_ms)`
  - `watch_settings_from_config(cfg) -> WatchSettings`
  - `BoardWatcher(capture_fn, get_state_fn, on_move, on_status, settings, clock=time.monotonic)` と `BoardWatcher.step()`
  - `on_move(i, j, color, move_number, board_size)` / `on_status(kind, text)`（`kind` は `"bw-watching"` / `"bw-warn"` / `""`）
  - `PermanentCaptureError` — `capture_fn` がこれを投げたら**即警告**（ウィンドウが無い等）。それ以外の例外は過渡失敗として `failure_warn_frames` 回まで黙ってスキップする（`CaptureError` は1種類しかなく型で切り分けられないため、**投げる側**が恒久かどうかを表明する）

- [ ] **Step 1: 失敗するテストを書く**

```python
from katrain.core.board_watch import BoardWatcher, WatchSettings  # 既存の import 行に足す


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Harness:
    """BoardWatcher を偽の外界で駆動する"""

    def __init__(self, settings=None):
        self.frames = []           # capture_fn が順に返すもの（例外インスタンスなら raise）
        self.state = None
        self.moves = []
        self.statuses = []
        self.clock = FakeClock()
        self.watcher = BoardWatcher(
            capture_fn=self._capture,
            get_state_fn=lambda: self.state,
            on_move=lambda i, j, color, move_number, size: self.moves.append((i, j, color, move_number)),
            on_status=lambda kind, text: self.statuses.append((kind, text)),
            settings=settings or WatchSettings(),
            clock=self.clock,
        )

    def _capture(self):
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame

    def step(self, frame, state=None):
        self.frames.append(frame)
        if state is not None:
            self.state = state
        self.watcher.step()


def test_watcher_injects_after_stable_frames():
    h = Harness(WatchSettings(stable_frames=2))
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    state = _state(current, to_play="B", move_number=4)
    h.step(observed, state)
    assert h.moves == []           # 1フレーム目では確定しない
    h.step(observed, state)
    assert h.moves == [(1, 1, "B", 4)]


def test_watcher_resets_stability_when_move_changes():
    h = Harness(WatchSettings(stable_frames=2))
    current = _grid(["...", "...", "..."])
    state = _state(current, to_play="B")
    h.step(_grid(["...", ".B.", "..."]), state)
    h.step(_grid(["B..", "...", "..."]), state)
    assert h.moves == []


def test_watcher_does_not_inject_again_while_pending():
    h = Harness(WatchSettings(stable_frames=1))
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    state = _state(current, to_play="B", move_number=4)
    h.step(observed, state)
    assert len(h.moves) == 1
    h.step(observed, state)        # KaTrain 側はまだ反映されていない
    assert len(h.moves) == 1


def test_watcher_clears_pending_when_move_number_changes():
    h = Harness(WatchSettings(stable_frames=1))
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    h.step(observed, _state(current, to_play="B", move_number=4))
    assert len(h.moves) == 1
    # KaTrain が着手し、さらに AI が応じた（期待グリッドは一瞬しか存在しない）
    after = _grid(["W..", ".B.", "..."])
    h.step(after, _state(after, to_play="B", last_move=(0, 0, "W"), move_number=6))
    assert h.watcher._pending is None


def test_watcher_warns_and_blocks_move_after_inject_timeout():
    h = Harness(WatchSettings(stable_frames=1, inject_timeout_ms=1000))
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    state = _state(current, to_play="B", move_number=4)
    h.step(observed, state)
    h.clock.advance(2.0)
    h.step(observed, state)
    assert any(kind == "bw-warn" for kind, _text in h.statuses)
    h.step(observed, state)        # 同じ手を再注入しない
    assert len(h.moves) == 1


def test_watcher_is_silent_while_waiting_and_ahead():
    h = Harness()
    board = _grid(["...", "...", "..."])
    h.step(board, _state(board, human=False))
    h.step(board, _state(board))
    assert all(kind == "bw-watching" for kind, _t in h.statuses)


def test_watcher_warns_when_quiet_too_long():
    h = Harness(WatchSettings(stall_warn_sec=20))
    board = _grid(["...", "...", "..."])
    state = _state(board, human=False)
    h.step(board, state)
    h.clock.advance(25.0)
    h.step(board, state)
    assert any(kind == "bw-warn" and "変化しません" in text for kind, text in h.statuses)


def test_watcher_quiet_timer_resets_when_state_changes():
    h = Harness(WatchSettings(stall_warn_sec=20))
    board = _grid(["...", "...", "..."])
    h.step(board, _state(board, human=False, move_number=1))
    h.clock.advance(15.0)
    h.step(board, _state(board, human=False, move_number=2))
    h.clock.advance(15.0)
    h.step(board, _state(board, human=False, move_number=2))
    assert not any(kind == "bw-warn" for kind, _t in h.statuses)


def test_watcher_adds_resync_hint_after_repeated_mismatch():
    h = Harness(WatchSettings(resync_hint_frames=3))
    current = _grid(["...", "...", "..."])
    observed = _grid(["W..", ".B.", "..."])
    state = _state(current, to_play="B")
    for _ in range(3):
        h.step(observed, state)
    assert any("ctrl+alt+b" in text for _kind, text in h.statuses)


def test_watcher_skips_transient_capture_failures_then_warns():
    h = Harness(WatchSettings(failure_warn_frames=3))
    for _ in range(2):
        h.step(RuntimeError("judgement failed"))
    assert h.statuses == []
    h.step(RuntimeError("judgement failed"))
    assert any(kind == "bw-warn" for kind, _t in h.statuses)


def test_watcher_backs_off_and_recovers():
    h = Harness(WatchSettings(poll_interval_ms=400, backoff_after_failures=2, backoff_factor=2.0, poll_interval_max_ms=2000))
    h.step(RuntimeError("x"))
    h.step(RuntimeError("x"))
    assert h.watcher.interval_ms == 800
    h.step(RuntimeError("x"))
    assert h.watcher.interval_ms == 1600
    board = _grid(["...", "...", "..."])
    h.step(board, _state(board))
    assert h.watcher.interval_ms == 400


def test_watcher_ignores_none_state():
    h = Harness()
    board = _grid(["...", "...", "..."])
    h.step(board, None)
    assert h.moves == []


def test_watcher_warns_immediately_on_permanent_failure():
    from katrain.core.board_watch import PermanentCaptureError

    h = Harness(WatchSettings(failure_warn_frames=8))
    h.step(PermanentCaptureError("ウィンドウが見つかりません"))
    assert any(kind == "bw-warn" for kind, _t in h.statuses)


def test_watcher_recovers_after_permanent_failure():
    from katrain.core.board_watch import PermanentCaptureError

    h = Harness(WatchSettings(failure_warn_frames=8))
    h.step(PermanentCaptureError("ウィンドウが見つかりません"))
    board = _grid(["...", "...", "..."])
    h.step(board, _state(board))
    assert h.statuses[-1][0] == "bw-watching"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: FAIL（`ImportError: cannot import name 'BoardWatcher'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/board_watch.py` の先頭に `import threading` と `import time` を足し、末尾に追記:

```python
class WatchSettings(NamedTuple):
    poll_interval_ms: int = 400
    stable_frames: int = 2
    failure_warn_frames: int = 8
    inject_timeout_ms: int = 5000
    stall_warn_sec: float = 20.0
    resync_hint_frames: int = 10
    backoff_after_failures: int = 3
    backoff_factor: float = 2.0
    poll_interval_max_ms: int = 2000


def watch_settings_from_config(cfg):
    d = cfg or {}
    default = WatchSettings()
    return WatchSettings(
        poll_interval_ms=int(d.get("poll_interval_ms", default.poll_interval_ms)),
        stable_frames=int(d.get("stable_frames", default.stable_frames)),
        failure_warn_frames=int(d.get("failure_warn_frames", default.failure_warn_frames)),
        inject_timeout_ms=int(d.get("inject_timeout_ms", default.inject_timeout_ms)),
        stall_warn_sec=float(d.get("stall_warn_sec", default.stall_warn_sec)),
        resync_hint_frames=int(d.get("resync_hint_frames", default.resync_hint_frames)),
        backoff_after_failures=int(d.get("backoff_after_failures", default.backoff_after_failures)),
        backoff_factor=float(d.get("backoff_factor", default.backoff_factor)),
        poll_interval_max_ms=int(d.get("poll_interval_max_ms", default.poll_interval_max_ms)),
    )


STATUS_WATCHING = "bw-watching"
STATUS_WARN = "bw-warn"
WATCHING_TEXT = "盤面監視中（相手の手を自動反映）"
RESYNC_HINT = "（ctrl+alt+b を2回押すと現局面を取り込み直します）"


class PermanentCaptureError(Exception):
    """すぐ直らない失敗（ウィンドウが無い等）。過渡失敗と違い即警告する。

    tsumego_capture の CaptureError は1種類しかなく、app 経路と Web 経路のメッセージを
    連結して投げ直すため**型では切り分けられない**。そこで「どこで失敗したか」を
    知っている投げる側（AppBoardReader）に恒久かどうかを表明させる。
    """


def _grid_key(grid):
    return tuple("".join(row) for row in grid)


class BoardWatcher:
    """アプリ盤面をポーリングして相手の着手を検出する。KaTrain の型は一切知らない。

    外界とはコールバックだけで接する:
      capture_fn()    -> 観測グリッド（失敗は例外）
      get_state_fn()  -> WatchState または None
      on_move(i, j, color, move_number, board_size)
      on_status(kind, text)   kind: "bw-watching" / "bw-warn" / ""
    """

    def __init__(self, capture_fn, get_state_fn, on_move, on_status, settings, clock=time.monotonic):
        self.capture_fn = capture_fn
        self.get_state_fn = get_state_fn
        self.on_move = on_move
        self.on_status = on_status
        self.settings = settings
        self.clock = clock
        self.interval_ms = settings.poll_interval_ms
        self._stopped = threading.Event()
        self._stable_move = None
        self._stable_count = 0
        self._fail_count = 0
        self._mismatch_count = 0
        self._pending = None  # (i, j, move_number, deadline)
        self._blocked = None  # (i, j, move_number) タイムアウトした手を同じ局面で再注入しない
        self._quiet_key = None
        self._quiet_since = None

    # --- 1周ぶんの判断（テストはここを直接叩く） ---
    def step(self):
        try:
            observed = self.capture_fn()
        except Exception as e:  # CaptureError も未知の例外もここで吸収する
            self._on_capture_failure(str(e), permanent=isinstance(e, PermanentCaptureError))
            return
        self._on_capture_success()
        state = self.get_state_fn()
        if state is None:
            return
        if self._pending is not None and not self._resolve_pending(state):
            return
        verdict = reconcile(state, observed)
        if verdict.kind == "mismatch":
            self._on_mismatch(verdict.reason)
            return
        self._mismatch_count = 0
        if verdict.kind == "move":
            self._on_move_verdict(state, verdict.move)
            return
        self._on_quiet(state, observed, verdict.kind)

    def _resolve_pending(self, state):
        """注入の反映を待っている間の処理。まだ待つなら False を返す。

        spec §2.5(b) は「期待グリッド」または「期待グリッド＋KaTrain の最終手」の
        いずれかで成立、と書いているが、実装は **move_number（= current_node.depth）が
        変わったか**で見る。これは spec の2条件を包含する（どちらの盤面になっていても
        手数は必ず増えている）うえ、期待グリッドが AI の応手で一瞬しか存在しない問題も
        同時に解ける。KaTrain 側が undo で戻った場合も「変わった」に入り、その後の
        reconcile が Mismatch として拾う。
        """
        i, j, move_number, deadline = self._pending
        if state.move_number != move_number:  # KaTrain 側で局面が進んだ＝反映された
            self._pending = None
            self._blocked = None
            return True
        if self.clock() >= deadline:
            self._pending = None
            self._blocked = (i, j, move_number)
            self._warn("着手が反映されませんでした（コウ・非合法手の可能性）" + RESYNC_HINT)
            return False
        return False

    def _on_move_verdict(self, state, move):
        self._quiet_key = None
        self._quiet_since = None
        if self._blocked == (move[0], move[1], state.move_number):
            return  # タイムアウトした手は局面が変わるまで投げ直さない
        if self._stable_move == move:
            self._stable_count += 1
        else:
            self._stable_move = move
            self._stable_count = 1
        if self._stable_count < self.settings.stable_frames:
            return
        self._stable_move = None
        self._stable_count = 0
        self._pending = (move[0], move[1], state.move_number, self.clock() + self.settings.inject_timeout_ms / 1000.0)
        self._watching()
        self.on_move(move[0], move[1], state.to_play, state.move_number, state.board_size)

    def _on_mismatch(self, reason):
        self._stable_move = None
        self._stable_count = 0
        self._quiet_key = None
        self._quiet_since = None
        self._mismatch_count += 1
        message = reason
        if self._mismatch_count >= self.settings.resync_hint_frames:
            message += RESYNC_HINT
        self._warn(message)

    def _on_quiet(self, state, observed, kind):
        """waiting / ahead / in_sync = 無音の終端状態。長すぎたら警告する（spec §2.5c）"""
        self._stable_move = None
        self._stable_count = 0
        key = (kind, state.move_number, _grid_key(observed))
        now = self.clock()
        if key != self._quiet_key:
            self._quiet_key = key
            self._quiet_since = now
            self._watching()
        elif self._quiet_since is not None and now - self._quiet_since >= self.settings.stall_warn_sec:
            self._quiet_since = now  # 再警告は stall_warn_sec ごと
            self._warn("盤面が変化しません（最終手マーカーの誤認識、または色の割り当てが逆の可能性）")

    def _on_capture_failure(self, message, permanent=False):
        self._fail_count += 1
        if self._fail_count >= self.settings.backoff_after_failures:
            self.interval_ms = min(
                int(self.interval_ms * self.settings.backoff_factor), self.settings.poll_interval_max_ms
            )
        # 恒久失敗は即警告、過渡失敗（アニメーション中の "?" 等）は連続 N 回まで黙る。
        # どちらも監視は止めない（最小化しただけで死なないように）
        if permanent or self._fail_count >= self.settings.failure_warn_frames:
            self._warn(f"盤面を認識できません: {message}")

    def _on_capture_success(self):
        self._fail_count = 0
        self.interval_ms = self.settings.poll_interval_ms

    def _watching(self):
        self.on_status(STATUS_WATCHING, WATCHING_TEXT)

    def _warn(self, message):
        self.on_status(STATUS_WARN, message)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board-watch): 監視の1周ぶんの判断（デバウンス・注入ガード・ウォッチドッグ・バックオフ）を実装"
```

---

### Task 7: `BoardWatcher.run()` と `AppBoardReader`（スレッドと認識キャッシュ）

**Files:**
- Modify: `katrain/core/board_watch.py`
- Modify: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: `BoardWatcher.step`, `tsumego_capture` の `find_window_rect` / `capture_screen_rect` / `detect_board` / `detect_size_and_classify`
- Produces:
  - `BoardWatcher.run()` / `BoardWatcher.stop()` / `BoardWatcher.start()`（daemon スレッド）
  - `AppBoardReader(window_title, board_sizes)` と `.read() -> grid`、`.size`

- [ ] **Step 1: 失敗するテストを書く**

```python
import katrain.core.board_watch as bw  # 既存の import 行の下に足す


def test_run_stops_and_survives_unexpected_exceptions():
    h = Harness(WatchSettings(poll_interval_ms=1))
    calls = []

    def boom():
        calls.append(1)
        if len(calls) >= 3:
            h.watcher.stop()
        raise ValueError("boom")

    h.watcher.get_state_fn = boom
    h.frames = [_grid(["..", ".."])] * 10
    h.watcher.run()
    assert len(calls) >= 3
    assert any(kind == "bw-warn" for kind, _t in h.statuses)


def test_reader_caches_board_rect_and_size(monkeypatch):
    calls = {"detect_board": 0, "classify": 0, "sizes": []}

    def fake_find_window_rect(title):
        return (0, 0, 100, 100)

    def fake_capture_screen_rect(rect):
        return "IMG"

    def fake_detect_board(img):
        calls["detect_board"] += 1
        return (1, 2, 3, 4)

    def fake_detect_size_and_classify(img, board_rect, sizes):
        calls["classify"] += 1
        calls["sizes"].append(list(sizes))
        return 9, [["."] * 9 for _ in range(9)]

    monkeypatch.setattr(bw, "_capture_api", lambda: (
        fake_find_window_rect, fake_capture_screen_rect, fake_detect_board, fake_detect_size_and_classify
    ))
    reader = bw.AppBoardReader("BlueStacks", [9, 13, 19])
    reader.read()
    reader.read()
    assert calls["detect_board"] == 1          # 2周目は盤矩形を再検出しない
    assert calls["sizes"] == [[9, 13, 19], [9]]  # 2周目はキャッシュしたサイズ1候補だけ
    assert reader.size == 9


def test_reader_reruns_detection_after_failure(monkeypatch):
    calls = {"detect_board": 0}
    state = {"fail": False}

    def fake_detect_size_and_classify(img, board_rect, sizes):
        if state["fail"]:
            raise RuntimeError("grid score too low")
        return 9, [["."] * 9 for _ in range(9)]

    def fake_detect_board(img):
        calls["detect_board"] += 1
        return (1, 2, 3, 4)

    monkeypatch.setattr(bw, "_capture_api", lambda: (
        lambda title: (0, 0, 100, 100), lambda rect: "IMG", fake_detect_board, fake_detect_size_and_classify
    ))
    reader = bw.AppBoardReader("BlueStacks", [9])
    reader.read()
    state["fail"] = True
    try:
        reader.read()
    except RuntimeError:
        pass
    state["fail"] = False
    reader.read()
    assert calls["detect_board"] == 2  # 失敗後は盤矩形からやり直す
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: FAIL（`AttributeError: module 'katrain.core.board_watch' has no attribute 'AppBoardReader'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/board_watch.py` の `BoardWatcher` に追記:

```python
    # --- スレッド ---
    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def run(self):
        while not self._stopped.is_set():
            try:
                self.step()
            except Exception as e:
                # step() 内で吸収しきれなかった想定外の例外でもスレッドを殺さない。
                # 落ちると「緑バナーのまま1手も入らない」無症状の停止になる
                self._warn(f"監視でエラーが発生しました: {e}")
            self._stopped.wait(self.interval_ms / 1000.0)

    def stop(self):
        self._stopped.set()
```

末尾に追記:

```python
def _capture_api():
    """tsumego_capture の関数群を遅延 import して返す（テストで差し替えられるように関数にする）"""
    from katrain.core.tsumego_capture import (
        capture_screen_rect,
        detect_board,
        detect_size_and_classify,
        find_window_rect,
    )

    return find_window_rect, capture_screen_rect, detect_board, detect_size_and_classify


class AppBoardReader:
    """アプリ窓を撮って観測グリッドを返す。盤矩形と盤サイズをキャッシュする。

    キャッシュ有りの1周は「撮影 27ms ＋ 格子検算 5〜25ms ＋ 分類 7〜29ms」＝40〜85ms（実測）。
    毎周 detect_size_and_classify をキャッシュしたサイズ1候補で回すのは、これが
    「盤矩形と規則配置の仮定がまだ合っているか」の検算を兼ねるため。
    """

    def __init__(self, window_title, board_sizes):
        self.window_title = window_title
        self.board_sizes = list(board_sizes)
        self.size = None
        self._window_rect = None
        self._board_rect = None

    def read(self):
        find_window_rect, capture_screen_rect, detect_board, detect_size_and_classify = _capture_api()
        try:
            rect = find_window_rect(self.window_title)
        except Exception as e:
            # ウィンドウが無い＝最小化・終了。過渡失敗と違い連続 N 回待たずに即警告させる
            raise PermanentCaptureError(str(e)) from e
        if rect != self._window_rect:  # 窓が動いた・リサイズされた
            self._window_rect = rect
            self._board_rect = None
        img = capture_screen_rect(rect)
        if self._board_rect is None:
            board_rect = detect_board(img)
            size, grid = detect_size_and_classify(img, board_rect, self.board_sizes)
            self._board_rect = board_rect
            self.size = size
            return grid
        try:
            _size, grid = detect_size_and_classify(img, self._board_rect, [self.size])
        except Exception:
            self._board_rect = None  # 次回はフル検出からやり直す
            raise
        return grid
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_board_watch.py -v`
Expected: PASS（全件）

- [ ] **Step 5: 既存テストが壊れていないことを確認**

Run: `pytest tests/ --ignore=tests/test_ai.py -q`
Expected: 既存 771 件＋新規が PASS

- [ ] **Step 6: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board-watch): 監視スレッドと、盤矩形・盤サイズをキャッシュする読み取り器を追加"
```

---

### Task 8: ホットキー登録の一般化（挙動不変のリファクタ）

**Files:**
- Modify: `katrain/__main__.py:228`（呼び出し）, `:793-832`（登録）, `:834-879`（ループ）

**Interfaces:**
- Consumes: なし
- Produces: `_setup_global_hotkeys()` — `tsumego_capture` と `board_watch` の `enabled` を**独立に評価**して表を組む。表の要素は `(hotkey_id, spec, mods, vk, (handler_name, args), label, feature)`

**このタスクだけでは監視ホットキーは動かない**（`board_watch` ブロックがまだ config に無く、`_board_watch_trigger` も未実装）。既存4本が**完全に同じ挙動**であることを確認するのが目的。

- [ ] **Step 1: 登録関数を書き換える**

`katrain/__main__.py` の `_setup_tsumego_capture` を以下で置き換える（関数名も変える）:

```python
    def _setup_global_hotkeys(self):
        """詰碁キャプチャと盤面監視のグローバルホットキーを1本のメッセージループで登録する。

        2つの機能の enabled は**独立に評価する**。以前は tsumego_capture.enabled が偽だと
        関数ごと早期 return していたため、詰碁を使わないユーザーでは board_watch の
        ホットキーも登録されず、ログにも何も出なかった。
        """
        tsumego = self._config.get("tsumego_capture") or {}
        watch = self._config.get("board_watch") or {}
        if not tsumego.get("enabled", False) and not watch.get("enabled", False):
            return
        if sys.platform != "win32":
            self.log("グローバルホットキー: Windows 専用機能のため登録しません", OUTPUT_INFO)
            return
        from katrain.core.tsumego_capture import ensure_dpi_awareness

        ensure_dpi_awareness()
        # 役割指定ホットキー: 枠の攻め方推定（極値票）は殺される側が盤端の極値線を占める辺の
        # 詰碁で構造的に反転し、測って直すことはできない（生盤 ownership・枠バランス・手番
        # フリップの3測定族すべて実測で分離不能＝spec 追記37）。アプリの問題文（黒先白死/
        # 黒先活）を見ているユーザーだけが役割を知っているので、押し分けで明示してもらう
        # 枠なしキャプチャ（hotkey_noframe）: 枠は認識石の bbox+margin の閉じた箱で、内側は
        # 設計上「盤の約半分」が上限（`capture_settings_for_frame_mode`）。箱の外に正解手が
        # ある問題では壁がその点を占めて打てない（case AG）。自動では判定できないので、
        # アプリの解答手順を見ているユーザーに押し分けてもらう。枠なしでは役割が読めない
        # （壁の色が無い＝`tsumego_solver_attacks` が None）ので役割指定との組合せは持たない
        specs = []
        if tsumego.get("enabled", False):
            for key, default, role, frameless, label in (
                ("hotkey", "f4", None, False, "自動推定"),
                ("hotkey_attack", "shift+f4", True, False, "黒が攻め方(殺す問題)"),
                ("hotkey_defend", "ctrl+f4", False, False, "黒が守り方(生きる問題)"),
                ("hotkey_noframe", "shift+ctrl+f4", None, True, "枠なし(正解手が枠の外に出る問題)"),
            ):
                specs.append((tsumego, "tsumego_capture", key, default, "_tsumego_capture_trigger", (role, frameless), label))
        if watch.get("enabled", False):
            # ホットキーは Theme.KEY_* と重ねないこと（RegisterHotKey はフォーカス窓から
            # キーを奪うので、重ねると KaTrain 本体のショートカットが黙って死ぬ）
            specs.append((watch, "board_watch", "hotkey", "ctrl+alt+b", "_board_watch_trigger", (), "盤面監視トグル"))
        hotkeys = []
        for settings, feature, key, default, handler, args, label in specs:
            spec = settings.get(key, default)
            if not spec:
                continue  # 空文字でそのキーだけ無効化できる
            try:
                mods, vk = self._parse_hotkey(spec)
            except ValueError as e:
                self.log(f"{feature}: ホットキー設定({key})が不正です: {e}", OUTPUT_ERROR)
                continue
            hotkeys.append((self._TSUMEGO_HOTKEY_ID + len(hotkeys), spec, mods, vk, (handler, args), label, feature))
        if not hotkeys:
            return
        self._tsumego_capture_busy = False
        self._board_watch_busy = False
        threading.Thread(target=self._global_hotkey_loop, args=(hotkeys,), daemon=True).start()
```

- [ ] **Step 2: ループ側の dispatch を書き換える**

`_tsumego_hotkey_loop` を `_global_hotkey_loop` に改名し、以下の3箇所を変える（docstring はそのまま残す）:

```python
    def _global_hotkey_loop(self, hotkeys):
        # ...（既存の docstring をそのまま残す）...
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        registered = []
        for hotkey_id, spec, mods, vk, action, label, feature in hotkeys:
            if not user32.RegisterHotKey(None, hotkey_id, mods | self._MOD_NOREPEAT, vk):
                self.log(
                    f"{feature}: ホットキー {spec}（{label}）の登録に失敗しました"
                    f"（他のアプリが同じキーを使用している可能性があります）",
                    OUTPUT_ERROR,
                )
                continue
            registered.append((hotkey_id, spec, action, label, feature))
        if not registered:
            return
        actions = {hotkey_id: action for hotkey_id, _spec, action, _label, _feature in registered}
        for feature in sorted({f for *_rest, f in registered}):
            entries = [(spec, label) for _id, spec, _action, label, f in registered if f == feature]
            self.log(
                f"{feature}: ホットキー " + " / ".join(f"{spec}={label}" for spec, label in entries) + " を登録しました",
                OUTPUT_INFO,
            )
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self._WM_HOTKEY and msg.wParam in actions:
                    # キャプチャ中もメッセージループを止めないよう、実処理は作業スレッドに投げる
                    handler, args = actions[msg.wParam]
                    threading.Thread(target=getattr(self, handler), args=args, daemon=True).start()
        finally:
            for hotkey_id, _spec, _action, _label, _feature in registered:
                user32.UnregisterHotKey(None, hotkey_id)
```

- [ ] **Step 3: 呼び出し元を直す**

`katrain/__main__.py:228` の `self._setup_tsumego_capture()` を `self._setup_global_hotkeys()` に変える。

Run: `grep -n "_setup_tsumego_capture\|_tsumego_hotkey_loop" katrain/__main__.py`
Expected: 出力なし（旧名が残っていない）

- [ ] **Step 4: 構文と参照を確認**

Run: `python -c "import ast,sys; ast.parse(open('katrain/__main__.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

Run: `pytest tests/ --ignore=tests/test_ai.py -q`
Expected: 既存テストが PASS（`__main__.py` はテスト対象外だが、壊していないことの確認）

- [ ] **Step 5: 実機で挙動不変を確認**

`python -m katrain` を起動し、ログに `tsumego_capture: ホットキー ... を登録しました` が出ることを確認。詰碁キャプチャのホットキー（ローカル設定では `ctrl+alt+z`）を1回押して従来どおりキャプチャできることを確認する。

Run: `grep -a "ホットキー" ~/.katrain/logs/*.log | tail -3`

- [ ] **Step 6: コミット**

```bash
git add katrain/__main__.py
git commit -m "refactor(hotkey): グローバルホットキー登録を機能ごとに独立させる（挙動不変）"
```

---

### Task 9: 設定ブロック `board_watch` を両方の config.json に追加

**Files:**
- Modify: `katrain/config.json`
- Modify: `C:\Users\iwaki\.katrain\config.json`（**KaTrain 終了中に、メインセッションで直接 Edit**）

**Interfaces:**
- Consumes: なし
- Produces: `board_watch` ブロック（`watch_settings_from_config` が読むキーと `enabled` / `hotkey` / `window_title`）

- [ ] **Step 1: KaTrain が起動していないことを確認**

Run: `tasklist | grep -i python`
Expected: KaTrain のプロセスが無い（起動中にローカル config を編集すると、終了時の全体書き戻しで消える）

- [ ] **Step 2: パッケージ側 `katrain/config.json` に追加**

`"tsumego_capture"` ブロックの直後に追加する:

```json
  "board_watch": {
    "enabled": true,
    "hotkey": "ctrl+alt+b",
    "window_title": "",
    "poll_interval_ms": 400,
    "stable_frames": 2,
    "failure_warn_frames": 8,
    "inject_timeout_ms": 5000,
    "stall_warn_sec": 20,
    "resync_hint_frames": 10,
    "backoff_after_failures": 3,
    "backoff_factor": 2.0,
    "poll_interval_max_ms": 2000
  },
```

- [ ] **Step 3: ローカル `C:\Users\iwaki\.katrain\config.json` にも同じブロックを追加**

**この編集はサブエージェントに委任しない。** パッケージ側の新キーはユーザーファイルへマージされない（`base_katrain.py:210-238`）ので、両方に入れないと GUI/実行時に読まれない。

- [ ] **Step 4: JSON が壊れていないことを確認**

Run:
```bash
python -c "import json;a=json.load(open('katrain/config.json'));b=json.load(open(r'C:/Users/iwaki/.katrain/config.json'));print(sorted(a['board_watch'])==sorted(b['board_watch']), len(a['board_watch']))"
```
Expected: `True 12`

- [ ] **Step 5: コミット**

```bash
git add katrain/config.json
git commit -m "feat(board-watch): 監視モードの設定ブロックを追加"
```

---

### Task 10: 着手注入の専用ハンドラ `board-watch-play`

**Files:**
- Modify: `katrain/__main__.py`（`_do_play` の直後に追加）

**Interfaces:**
- Consumes: `Move`, `IllegalMoveException`, `play_sound`, `Theme`
- Produces: `_do_board_watch_play(coords, color, expect_move_number)` — メッセージループで走り、**手数と手番を再検証してから**着手する

- [ ] **Step 1: ハンドラを追加**

`katrain/__main__.py` の `_do_play` の直後に追加:

```python
    def _do_board_watch_play(self, coords, color, expect_move_number):
        """盤面監視が検出した相手の着手を反映する。

        "play" を流用しないのは、_do_play が色を引数に取らず「その時点の」
        next_player_info.player で打つため。ワーカーが検査した手番はキュー投入前の
        スナップショットで、投入から実行までの間にホイール undo（:1737-1739）や
        キーボード undo（:1833）が1手ぶん parity を反転させると、空点への合法手として
        **例外もログも無しに逆色の石が入る**。ここで再検証して不一致なら捨てる。
        """
        node = self.game.current_node
        if node.depth != expect_move_number or node.next_player != color:
            self.log(
                f"board_watch: 注入を破棄しました（手数 {node.depth}!={expect_move_number} / "
                f"手番 {node.next_player}!={color}）",
                OUTPUT_INFO,
            )
            self._board_watch_status(BW_STATUS_WARN, "着手の直前に局面が変わったため注入を取り消しました")
            return
        self.board_gui.animating_pv = None
        try:
            old_prisoner_count = self.game.prisoner_count["W"] + self.game.prisoner_count["B"]
            self.game.play(Move(coords, player=color))
            if old_prisoner_count < self.game.prisoner_count["W"] + self.game.prisoner_count["B"]:
                play_sound(Theme.CAPTURING_SOUND)
            else:
                self._play_stone_sound()
            self.log(f"board_watch: 相手の着手 {Move(coords, player=color).gtp()} を反映しました", OUTPUT_INFO)
        except IllegalMoveException as e:
            self.log(f"board_watch: 注入した手が非合法でした: {e}", OUTPUT_INFO)
            self._board_watch_status(BW_STATUS_WARN, f"注入した手が非合法でした: {e}")
```

- [ ] **Step 2: 定数とステータス更新ヘルパを追加**

`katrain/__main__.py` の `_tsumego_capture_failed` の直後に追加:

```python
    def _board_watch_status(self, kind, text):
        """監視バナーを更新する（ワーカースレッドから呼ばれるため Clock 経由）"""

        def _set(_dt):
            self.board_watch_status = kind
            self.board_watch_detail = text

        Clock.schedule_once(_set, 0)
```

import 節（`from katrain.core.ai import ...` の近く）に追加:

```python
from katrain.core.board_watch import STATUS_WARN as BW_STATUS_WARN
```

- [ ] **Step 3: プロパティを追加**

`katrain/__main__.py:132`（`tsumego_banner_flash_kind` の直後）に追加:

```python
    # 盤面監視モードの状態（"" = OFF）。status は色トークン、detail は自由文の理由。
    # 既存の tsumego_book_status に相乗りできない（update_gui が毎回上書きする）し、
    # 既存バナーの status は i18n と色辞書の列挙キーなので可変文言を載せられない
    board_watch_status = StringProperty("")
    board_watch_detail = StringProperty("")
```

- [ ] **Step 4: 構文を確認**

Run: `python -c "import ast; ast.parse(open('katrain/__main__.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

Run: `grep -n "board_watch_status\|_do_board_watch_play" katrain/__main__.py`
Expected: プロパティ2行・ヘルパ・ハンドラが見える

- [ ] **Step 5: コミット**

```bash
git add katrain/__main__.py
git commit -m "feat(board-watch): 手番を再検証してから着手する専用の注入ハンドラを追加"
```

---

### Task 11: 状態取得・トグル・局面の取り込み

**Files:**
- Modify: `katrain/__main__.py`

**Interfaces:**
- Consumes: `board_watch` の `AppBoardReader` / `BoardWatcher` / `WatchState` / `stones_to_grid` / `move_to_grid` / `grid_to_move` / `board_sgf` / `watch_settings_from_config`
- Produces:
  - `_board_watch_trigger()` — ホットキーのワーカースレッド。ON/OFF を切り替える
  - `_board_watch_state()` — `WatchState` を作る（監視スレッドから呼ばれる）
  - `_do_board_watch_start(reader, grid, size)` — メッセージループ側の開始処理

- [ ] **Step 1: 状態取得を追加**

`katrain/__main__.py` の `_board_watch_status` の直後に追加:

```python
    def _board_watch_state(self):
        """監視スレッドが読む KaTrain 側のスナップショット（判定は board_watch 側で行う）"""
        from katrain.core.board_watch import WatchState, move_to_grid, stones_to_grid

        game = self.game
        if game is None:
            return None
        size_x, size_y = game.board_size
        if size_x != size_y:
            return None  # 長方形の盤は監視対象外
        node = game.current_node
        # game.stones はプロパティ自身が _lock を取る（呼び出し側でロックを取らない）
        grid = stones_to_grid(((s.coords, s.player) for s in game.stones), size_x)
        last_move = None
        move = node.move
        if move is not None and move.coords is not None:  # パスは coords=None の Move
            i, j = move_to_grid(move.coords, size_x)
            last_move = (i, j, move.player)
        to_play = node.next_player
        return WatchState(
            current_grid=grid,
            last_move=last_move,
            to_play=to_play,
            to_play_is_human=self.players_info[to_play].human,
            # AI が構造的に応手できない状態（分岐・終局・解析モード・リージョン残り）は
            # 盤面が一致していても無症状のデッドロックになるので、判定側へ渡して警告させる
            ai_can_respond=(
                self.play_analyze_mode == MODE_PLAY
                and not node.children
                and not game.end_result
                and game.region_of_interest is None
            ),
            move_number=node.depth,
            board_size=size_x,
        )
```

- [ ] **Step 2: ホットキーのトグルを追加**

`_board_watch_state` の直後に追加:

```python
    def _board_watch_trigger(self):
        """ctrl+alt+b のワーカースレッド。OFF なら認識してから開始、ON なら停止する"""
        from katrain.core.board_watch import AppBoardReader

        now = time.time()
        if now - getattr(self, "_board_watch_last_trigger", 0.0) < 2.0:
            return
        self._board_watch_last_trigger = now
        if getattr(self, "_board_watch_busy", False):
            return
        watcher = getattr(self, "_board_watcher", None)
        if watcher is not None:
            watcher.stop()
            self._board_watcher = None
            self._board_watch_status("", "")
            self.log("board_watch: 監視を停止しました", OUTPUT_INFO)
            return
        self._board_watch_busy = True
        try:
            settings = self._config.get("board_watch") or {}
            tsumego = self._config.get("tsumego_capture") or {}
            title = settings.get("window_title") or tsumego.get("window_title", "BlueStacks")
            sizes = [int(s) for s in (tsumego.get("board_sizes") or [9, 13, 19])]
            reader = AppBoardReader(title, sizes)
            try:
                grid = reader.read()
            except Exception as e:
                self.log(f"board_watch: 盤面を認識できないため開始しません: {e}", OUTPUT_ERROR)
                self._board_watch_status(BW_STATUS_WARN, f"盤面を認識できません: {e}")
                return
            self("board-watch-start", reader, grid, reader.size)
        finally:
            self._board_watch_busy = False
```

- [ ] **Step 3: 開始処理（前提チェック・取り込み・スレッド起動）を追加**

`_do_board_watch_play` の直後に追加:

```python
    def _do_board_watch_start(self, reader, grid, size):
        """監視の開始。前提チェック → 必要なら局面取り込み → プレイモード → スレッド起動。

        既存の capture-fullboard-apply は流用しない（両者を人間に戻す・raise_window で
        フォーカスを奪う・解析モードに入る、の3つが監視モードに不都合）。
        new-game と後続を分けると game_id 更新で後続メッセージが黙って破棄されるため、
        ここで1メッセージ内に完結させる（_do_tsumego_capture_apply と同じ作法）。
        """
        from katrain.core.board_watch import (
            BoardWatcher,
            board_sgf,
            grid_to_move,
            stones_to_grid,
            watch_settings_from_config,
        )

        ai_players = [bw for bw, info in self.players_info.items() if info.ai]
        if len(ai_players) != 1:
            self._board_watch_status(
                BW_STATUS_WARN, "片方を AI・片方を人間に設定してから開始してください"
            )
            return
        human_color = "W" if ai_players[0] == "B" else "B"
        if self.game.region_of_interest is not None:
            self.game.set_region_of_interest([0, 0, 0, 0])  # 解除（詰碁キャプチャの残骸）
        size_x, size_y = self.game.board_size
        current = stones_to_grid(((s.coords, s.player) for s in self.game.stones), size_x) if size_x == size_y else None
        if current != grid or size_x != size:
            # 取り込み: 手番は「人間側（アプリ AI）の色」に固定する。石数パリティでは決まらない
            # （盤上石数 b,w と取られた石数 cb,cw は b-w = cw-cb なので、取りが1回でも入ると
            # パリティは手番を表さない）。人間側に倒すのは安全側＝KaTrain が誤った色で
            # 勝手に打ち出す事故が構造的に起きない
            komi = self.config("game/komi", 6.5)
            rules = self.config("game/rules", "japanese")
            try:
                move_tree = KaTrainSGF.parse_sgf(board_sgf(grid, komi, rules, human_color))
            except ParseError as e:
                self.log(f"board_watch: 取り込み SGF の解析に失敗: {e}", OUTPUT_ERROR)
                self._board_watch_status(BW_STATUS_WARN, f"局面を取り込めません: {e}")
                return
            self._do_new_game(move_tree=move_tree)
            self.log(f"board_watch: アプリの局面（{size}路）を取り込みました（手番={human_color}）", OUTPUT_INFO)
            # move_tree ありの new-game は解析モードに入るので、プレイモードへ戻す。
            # switch_ui_mode のトグルは他所の予約済みクリックと競合して mode の読み値が狂う
            Clock.schedule_once(lambda _dt: self.play_mode.play.trigger_action(duration=0), 0)
        elif self.play_analyze_mode != MODE_PLAY:
            Clock.schedule_once(lambda _dt: self.play_mode.play.trigger_action(duration=0), 0)

        def on_move(i, j, color, move_number, board_size):
            self("board-watch-play", grid_to_move(i, j, board_size), color, move_number)

        watcher = BoardWatcher(
            capture_fn=reader.read,
            get_state_fn=self._board_watch_state,
            on_move=on_move,
            on_status=self._board_watch_status,
            settings=watch_settings_from_config(self._config.get("board_watch")),
        )
        self._board_watcher = watcher
        watcher.start()
        self.log("board_watch: 監視を開始しました", OUTPUT_INFO)
```

- [ ] **Step 4: 構文と参照を確認**

Run: `python -c "import ast; ast.parse(open('katrain/__main__.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

Run: `grep -n "MODE_PLAY\|KaTrainSGF\|ParseError" katrain/__main__.py | head -5`
Expected: いずれも既に import 済み（`:69-88` の constants / `:101-109` の game・sgf_parser）

- [ ] **Step 5: コミット**

```bash
git add katrain/__main__.py
git commit -m "feat(board-watch): 監視のトグル・状態取得・局面取り込みを実装"
```

---

### Task 12: バナー表示

**Files:**
- Modify: `katrain/gui/theme.py:155-163`
- Modify: `katrain/gui.kv:325-341`（バナーのクラスルール）, `:1199-1206`（配置）

**Interfaces:**
- Consumes: `board_watch_status` / `board_watch_detail`（Task 10 で追加済み）
- Produces: 監視中＝緑・警告＝橙の全幅バナー。OFF は高さ0

- [ ] **Step 1: テーマ色を追加**

`katrain/gui/theme.py` の `TSUMEGO_BOOK_BANNER_COLORS` に2キー追加（既存の `off` / `warn` は回答帳の意味で使用中なので**衝突しない名前**にする）:

```python
    TSUMEGO_BOOK_BANNER_COLORS = {
        "playing": YELLOW,
        "done": GREEN,
        "off": ORANGE,
        "save": GREEN,
        "info": BLUE,
        "warn": ORANGE,
        "bw-watching": GREEN,  # 盤面監視モード: 監視中
        "bw-warn": ORANGE,  # 盤面監視モード: 同期できません
    }
```

- [ ] **Step 2: バナーのクラスルールに監視用の2プロパティを足す**

`katrain/gui.kv` の `<TsumegoBookBanner@MDBoxLayout+BackgroundMixin>:` を変更（優先順位は flash > 監視 > 回答帳）:

```
<TsumegoBookBanner@MDBoxLayout+BackgroundMixin>:
    status: ''
    flash: ''
    flash_kind: 'save'
    watch_status: ''
    watch_detail: ''
    background_color: Theme.TSUMEGO_BOOK_BANNER_COLORS.get(root.flash_kind if root.flash else (root.watch_status if root.watch_status else root.status), Theme.TSUMEGO_BOOK_BANNER_COLORS['playing'])
```

Label の `text:` 行を差し替える:

```
        text: root.flash if root.flash else (root.watch_detail if root.watch_detail else (i18n._('tsumego:book-playing') if root.status=='playing' else (i18n._('tsumego:book-done') if root.status=='done' else (i18n._('tsumego:book-off') if root.status=='off' else ''))))
```

**注**: 監視側は i18n を通さない自由文をそのまま出す（既存の `flash` と同じ経路）。`.po`/`.mo` の更新は不要。

- [ ] **Step 3: 配置側のバインディングを足す**

`katrain/gui.kv` の `TsumegoBookBanner:` インスタンス（`:1199-1206`）を変更:

```
                        TsumegoBookBanner:
                            id: tsumego_book_banner
                            status: root.tsumego_book_status
                            flash: root.tsumego_banner_flash
                            flash_kind: root.tsumego_banner_flash_kind
                            watch_status: root.board_watch_status
                            watch_detail: root.board_watch_detail
                            size_hint_y: None
                            height: dp(30) if (root.tsumego_book_status or root.tsumego_banner_flash or root.board_watch_status) else 0
                            opacity: 1 if (root.tsumego_book_status or root.tsumego_banner_flash or root.board_watch_status) else 0
```

- [ ] **Step 4: 起動して表示を確認**

Run: `python -m katrain`

確認: 起動直後はバナーが出ない（高さ0＝従来レイアウト）。詰碁キャプチャを1回撮って、回答帳バナーが従来どおり出ることも確認する。

- [ ] **Step 5: コミット**

```bash
git add katrain/gui/theme.py katrain/gui.kv
git commit -m "feat(board-watch): 監視状態を盤上バナーに表示する"
```

---

### Task 13: 実スクショによる回帰テスト

**Files:**
- Modify: `tests/test_board_watch.py`
- Uses: `tests/data/board_watch_before.png` / `board_watch_after.png`（Task 1 で保存）

**Interfaces:**
- Consumes: `tsumego_capture.detect_board` / `detect_size_and_classify`, `board_watch.reconcile`
- Produces: 「実スクショ2枚の差がちょうど相手の1手になる」ことを固定する回帰テスト

- [ ] **Step 1: 失敗するテストを書く**

Task 1 の結果（盤サイズ・相手の着手座標・色）を埋めてから追加する:

```python
import os

import pytest

DATA = os.path.join(os.path.dirname(__file__), "data")
BEFORE = os.path.join(DATA, "board_watch_before.png")
AFTER = os.path.join(DATA, "board_watch_after.png")

# Task 1 のスパイク結果で埋める（アプリ側の実測値）
EXPECTED_SIZE = 19
EXPECTED_MOVE = (3, 15)  # (i, j) 上origin
EXPECTED_COLOR = "W"


def _recognize(path):
    from PIL import Image

    from katrain.core.tsumego_capture import detect_board, detect_size_and_classify

    img = Image.open(path)
    board_rect = detect_board(img)
    size, grid = detect_size_and_classify(img, board_rect, [9, 13, 19])
    return size, grid


@pytest.mark.skipif(not os.path.exists(BEFORE), reason="スパイクのスクショが未取得")
def test_real_screenshots_differ_by_exactly_one_move():
    size_before, before = _recognize(BEFORE)
    size_after, after = _recognize(AFTER)
    assert size_before == size_after == EXPECTED_SIZE
    state = _state(before, to_play=EXPECTED_COLOR, move_number=1)
    verdict = reconcile(state, after)
    assert verdict.kind == "move"
    assert verdict.move == EXPECTED_MOVE
```

- [ ] **Step 2: テストを実行**

Run: `pytest tests/test_board_watch.py -k real_screenshots -v`
Expected: PASS（スクショが無ければ SKIP）

FAIL する場合は Task 1 の `spike-results` に戻り、`EXPECTED_*` を実測値に合わせる。認識そのものが通らない場合は**詰碁経路の関数を変更せず**、board_watch 専用の分類経路を足すかをユーザーと相談する。

- [ ] **Step 3: コミット**

```bash
git add tests/test_board_watch.py
git commit -m "test(board-watch): 実スクショ2枚の差が相手の1手になることを回帰で固定"
```

---

### Task 14: 実機での通し確認

**Files:** なし（検証のみ）

- [ ] **Step 1: デバッグログを有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level"` を `1` にする（**KaTrain 終了中に編集**）。

- [ ] **Step 2: 新規対局で通しを確認**

1. KaTrain で新規対局（片方を AI に設定）、BlueStacks の対局アプリでも新規対局
2. `ctrl+alt+b` を押す → バナーが緑「盤面監視中」になる
3. KaTrain の AI が黒なら、その手をアプリでタップ
4. アプリの AI が応じる → **KaTrain の盤面に自動で反映される**
5. これを5手以上繰り返す

Run: `grep -a "board_watch" ~/.katrain/logs/game_*.log | tail -20`
Expected: `監視を開始しました` と `相手の着手 ... を反映しました` が並ぶ

- [ ] **Step 3: 異常系を確認**

| 操作 | 期待 |
|---|---|
| BlueStacks を最小化する | 橙バナー「盤面を認識できません」・監視は継続。戻すと緑に復帰 |
| KaTrain で undo を押す | 橙バナー「盤面の差が1手で説明できません」・盤面は書き換わらない。10フレーム後に `ctrl+alt+b` の案内が付く |
| `ctrl+alt+b` を2回押す | 停止 → 現局面を取り込んで再開し、緑に戻る |
| アプリで待った | 橙バナー・KaTrain は無変化 |
| KaTrain を解析モードに切り替える | 橙バナー「AI が応手できない局面です」 |

- [ ] **Step 4: `debug_level` を 0 に戻す**

**KaTrain を終了してから**編集する。

- [ ] **Step 5: 結果を記録してコミット**

`docs/superpowers/specs/calibration-data/board-watch/spike-results-20260818.md` に「実機通し確認」節を追記し、上の表の実際の結果を書く。

```bash
git add docs/superpowers/specs/calibration-data/board-watch/
git commit -m "docs(board-watch): 実機での通し確認の結果を記録"
```

---

## 完了条件

- [ ] `pytest tests/ --ignore=tests/test_ai.py -q` が全件 PASS
- [ ] 実対局で相手の手が5手以上連続で自動反映される
- [ ] 異常系（最小化・undo・待った・解析モード）が橙バナーで警告され、盤面が壊れない
- [ ] `ctrl+alt+b` の2回押しで再同期できる
- [ ] 詰碁キャプチャのホットキーが従来どおり動く
