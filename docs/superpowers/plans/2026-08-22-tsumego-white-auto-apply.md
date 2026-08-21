# 詰碁モードの白番自動反映 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 詰碁キャプチャで出題中、BlueStacks の詰碁アプリが返す白の応手を KaTrain へ自動で反映する。

**Architecture:** 既存の対局監視モード（`BoardWatcher` / `reconcile`）の機構をそのまま流用し、比較の基準だけ差し替える。詰碁では枠（壁・充填・非コア石の除去）のせいで `game.stones` がアプリの盤と一致しないため、`WatchState.current_grid` に「キャプチャ時の認識グリッド ＋ root からの着手列を再生した影グリッド」を渡す。これで `reconcile` の判定表は1行も変えずに詰碁の意味になる。

**Tech Stack:** Python 3.12 / Kivy（GUI）/ pytest。新しい依存は無い。

**Spec:** `docs/superpowers/specs/2026-08-22-tsumego-white-auto-apply-design.md`

## Global Constraints

- **判定ロジックを `katrain/__main__.py` に置かない。** `__main__.py` は Kivy 依存でテストから import できないため、判定は `katrain/core/board_watch.py` の純関数に置き、`__main__.py` はそれを呼ぶだけにする（board-watch design §1）。
- **`katrain/core/board_watch.py` は Kivy にも KataGo にも依存させない。** 追加で import してよいのは `katrain.core.constants` のみ（Kivy を import していないことを確認済み）。
- **座標系**: 認識グリッド `grid[i][j]` の `i` は**画面上origin**、KaTrain の `Move.coords = (x, y)` は **`y` が下origin**。変換は必ず `move_to_grid` / `grid_to_move` を通す。
- **対局監視モード（`board_watch`）の既存挙動を変えない。** 新しい引数はすべて既定値が現行動作と一致すること。
- **コミットメッセージは日本語・Conventional Commits 形式**（`feat:` / `fix:` / `docs:` / `test:`）。
- **`black` を既存ファイル全体に走らせない**（コードベースが未整形なので巨大差分になる）。編集した範囲だけ手で line-length 120 に合わせる。
- 設定キーは**パッケージ `katrain/config.json` とユーザーローカル `C:\Users\iwaki\.katrain\config.json` の両方**に追加する。ローカル側は**メインセッションで直接編集**し、**KaTrain が起動していないこと**を確認してから書く（起動中に編集すると終了時に上書きで消える）。

---

### Task 1: 影グリッドの純関数 `replay_grid`

**Files:**
- Modify: `katrain/core/board_watch.py`（`apply_move_to_grid` の直後、`class WatchState` の直前＝現行 152行目付近）
- Test: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: 既存の `apply_move_to_grid(grid, i, j, color)`、`move_to_grid(coords, size)`、定数 `EMPTY` / `BLACK` / `WHITE`
- Produces: `replay_grid(base_grid, moves, size) -> list[list[str]] | None`
  - `base_grid`: 上origin グリッド（`list[list[str]]`）
  - `moves`: `(coords, color)` の列。`coords` は KaTrain の下origin `(x, y)`、パスは `None`
  - 戻り: 再生後の上origin グリッド。再現できなければ `None`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_board_watch.py` の末尾に追記する。冒頭の import 行に `replay_grid` を足すこと
（現行1行目の `from katrain.core.board_watch import EMPTY, BLACK, WHITE, apply_move_to_grid, ...` の末尾に `, replay_grid` を追加）。

```python
def test_replay_grid_no_moves_returns_copy_of_base():
    base = _grid(["...", ".B.", "..."])
    out = replay_grid(base, [], 3)
    assert out == base
    assert out is not base          # 呼び出し側が破壊できないようにコピーを返す


def test_replay_grid_applies_move_in_katrain_coords():
    # KaTrain の (x=0, y=0) は盤の左下 = グリッドの最終行の先頭
    out = replay_grid(_grid(["...", "...", "..."]), [((0, 0), "B")], 3)
    assert out == _grid(["...", "...", "B.."])


def test_replay_grid_skips_pass():
    base = _grid(["...", "...", "..."])
    assert replay_grid(base, [(None, "B"), (None, "W")], 3) == base


def test_replay_grid_captures_on_the_app_board():
    # 白1子 (2,0)=グリッド(0,2) の呼吸点はグリッド(0,1) と (1,2)。両方詰めると取れる。
    # 取りは「アプリの盤」の上で計算される＝KaTrain 側の枠石を巻き込まない
    base = _grid(["..W", "...", "..."])
    out = replay_grid(base, [((1, 2), "B"), ((2, 1), "B")], 3)
    assert out == _grid([".B.", "..B", "..."])


def test_replay_grid_returns_none_when_point_is_occupied_on_app_board():
    # 枠が消した非コア石の位置に AI が打つと、アプリ側では石があるので再現できない
    base = _grid(["W..", "...", "..."])
    assert replay_grid(base, [((0, 2), "B")], 3) is None


def test_replay_grid_returns_none_on_size_mismatch():
    assert replay_grid(_grid(["..", ".."]), [], 3) is None


def test_replay_grid_returns_none_for_missing_base():
    assert replay_grid(None, [], 3) is None
```

- [ ] **Step 2: テストが落ちることを確認する**

Run: `python -m pytest tests/test_board_watch.py -k replay_grid -v`
Expected: FAIL（`ImportError: cannot import name 'replay_grid'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/board_watch.py` の `apply_move_to_grid` の直後（`class WatchState` の直前）に足す:

```python
def replay_grid(base_grid, moves, size):
    """キャプチャ時の認識グリッドに root からの着手列を再生して「アプリ側の盤」を再現する。

    詰碁では KaTrain の盤とアプリの盤が一致しない。枠は壁と充填を**足す**だけでなく、
    drop_non_core_stones（tsumego_frame.py）で枠矩形の境界線上・外側の非コア石を
    **盤から消す**ため、game.stones はアプリの盤と両方向にずれている。そこで監視の
    比較基準は「キャプチャ時の認識グリッド + root からの着手列」で作り直す。

    moves は (coords, color) の列で、coords は KaTrain の下origin (x, y)（パスは None）。
    取りはこのグリッド＝アプリの盤の上で計算されるので、枠石を巻き込む KaTrain 側の
    取りとずれない。

    キャッシュせず毎周 root から再生する前提の関数（13路×20手で apply_move_to_grid 20回＝
    無視できるコスト）。こうすると undo/redo/分岐が自動的に正しくなる。

    再現できない（アプリ側では既に石がある等）ときは None を返す＝「比較しない」に倒す。
    """
    if base_grid is None or len(base_grid) != size:
        return None
    grid = [row[:] for row in base_grid]
    for coords, color in moves:
        if coords is None:  # パスは盤に石を置かない
            continue
        i, j = move_to_grid(coords, size)
        grid = apply_move_to_grid(grid, i, j, color)
        if grid is None:
            return None
    return grid
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `python -m pytest tests/test_board_watch.py -v`
Expected: PASS（既存69本＋新規7本すべて）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board_watch): アプリ盤を再現する影グリッド replay_grid を追加"
```

---

### Task 2: `BoardWatcher` に active 扱いする verdict の集合を持たせる

**Files:**
- Modify: `katrain/core/board_watch.py`（`BoardWatcher.__init__` 現行269行目付近、`_on_quiet` 現行365行目付近）
- Test: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: 既存の `BoardWatcher`、`WatchSettings`、テストの `Harness` / `_state` / `_grid` ヘルパ
- Produces: `BoardWatcher(..., active_kinds=("in_sync",))` キーワード引数。`self.active_kinds` は `tuple`

**背景:** 詰碁で白が来る直前の状態は `ahead`（黒を打ったがまだアプリへタップしていない）。現行は `in_sync` のときだけ 50ms 周期に落とすので、詰碁では最大 450ms の位相待ちが乗る。`ahead` を active に含めると最大 100ms になる。`ahead` →「黒＋白が同時に現れた観測」の遷移は1周で検出できるので、**正しさは変わらず遅延だけの話**。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_board_watch.py` の末尾に追記する。

```python
def _ahead_case():
    """KaTrain が黒を打ったがアプリにはまだ反映されていない（ahead）状態の一式"""
    current = _grid(["...", ".B.", "..."])
    observed = _grid(["...", "...", "..."])
    state = _state(current, to_play="W", last_move=(1, 1, "B"), move_number=5)
    return current, observed, state


def test_ahead_is_idle_by_default():
    h = Harness(WatchSettings(poll_interval_ms=400, poll_interval_active_ms=50))
    _current, observed, state = _ahead_case()
    h.step(observed, state)
    assert h.watcher.interval_ms == 400


def test_ahead_is_active_when_requested():
    h = Harness(WatchSettings(poll_interval_ms=400, poll_interval_active_ms=50))
    h.watcher.active_kinds = ("in_sync", "ahead")
    _current, observed, state = _ahead_case()
    h.step(observed, state)
    assert h.watcher.interval_ms == 50


def test_in_sync_stays_active_with_default_active_kinds():
    h = Harness(WatchSettings(poll_interval_ms=400, poll_interval_active_ms=50))
    current = _grid(["...", ".B.", "..."])
    h.step(current, _state(current, to_play="W", move_number=5))
    assert h.watcher.interval_ms == 50


def test_active_kinds_defaults_to_in_sync_only():
    h = Harness()
    assert h.watcher.active_kinds == ("in_sync",)


def test_active_kinds_can_be_passed_to_constructor():
    watcher = BoardWatcher(
        capture_fn=lambda: _grid(["..", ".."]),
        get_state_fn=lambda: None,
        on_move=lambda *a: None,
        on_status=lambda *a: None,
        settings=WatchSettings(),
        active_kinds=("in_sync", "ahead"),
    )
    assert watcher.active_kinds == ("in_sync", "ahead")
```

- [ ] **Step 2: テストが落ちることを確認する**

Run: `python -m pytest tests/test_board_watch.py -k "active_kinds or ahead_is" -v`
Expected: FAIL（`AttributeError: 'BoardWatcher' object has no attribute 'active_kinds'` と `TypeError: __init__() got an unexpected keyword argument 'active_kinds'`）

- [ ] **Step 3: 最小実装を書く**

`BoardWatcher.__init__` のシグネチャに `active_kinds=("in_sync",)` を足し（`clock=time.monotonic` の後ろ）、本体の `self.settings = settings` の下に代入を足す:

```python
    def __init__(self, capture_fn, get_state_fn, on_move, on_status, settings, clock=time.monotonic,
                 active_kinds=("in_sync",)):
        self.capture_fn = capture_fn
        self.get_state_fn = get_state_fn
        self.on_move = on_move
        self.on_status = on_status
        self.settings = settings
        # 低遅延（poll_interval_active_ms）で回す無音状態の集合。既定は in_sync だけ＝対局
        # モードの従来どおり。詰碁は ahead（黒を打ったがまだアプリへタップしていない）が
        # 白の来る直前の状態なので ("in_sync", "ahead") を渡す（spec 2026-08-22 §5）
        self.active_kinds = tuple(active_kinds)
        self.clock = clock
```

`_on_quiet` の分岐を集合参照に変える（現行の `if kind == "in_sync":` の行）:

```python
        if kind in self.active_kinds:
            # 盤がアプリと一致している＝次に変わるのは相手の石。ここだけが低遅延を要する
            # 局面で、waiting（KaTrain の AI が思考中）は相手の石が来ようがないので idle の
            # まま。ahead（ユーザーがまだアプリへタップしていない）は対局モードでは同じく
            # idle だが、詰碁ではタップ直後にアプリが白を返すので active に含める
            self._active()
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `python -m pytest tests/test_board_watch.py -v`
Expected: PASS（既存の対局モードのテストが1本も落ちないこと＝既定が現行動作と同じ）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board_watch): 低遅延で回す verdict の集合を差し替え可能にする"
```

---

### Task 3: 詰碁監視の入口ゲートとバナー整形の純関数

**Files:**
- Modify: `katrain/core/board_watch.py`（ファイル末尾の `AppBoardReader` の後ろに追記）
- Test: `tests/test_board_watch.py`

**Interfaces:**
- Consumes: `katrain.core.constants` の `AI_TSUMEGO` / `AI_TSUMEGO_SOLVER`、既存の `STATUS_WARN`
- Produces:
  - `tsumego_watch_can_start(watch_white, view_kind, auto_ai, black_subtype, white_is_human) -> (bool, str)`
  - `tsumego_watch_status(kind, text) -> (str, str)`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_board_watch.py` の末尾に追記する。

```python
def test_can_start_accepts_normal_tsumego_capture():
    ok, reason = bw.tsumego_watch_can_start(
        watch_white=True, view_kind="app", auto_ai=True,
        black_subtype="ai:tsumego", white_is_human=True,
    )
    assert ok is True
    assert reason == ""


def test_can_start_accepts_solver_subtype():
    ok, _reason = bw.tsumego_watch_can_start(
        watch_white=True, view_kind="app", auto_ai=True,
        black_subtype="ai:tsumego_solver", white_is_human=True,
    )
    assert ok is True


def test_can_start_rejects_when_disabled():
    ok, reason = bw.tsumego_watch_can_start(
        watch_white=False, view_kind="app", auto_ai=True,
        black_subtype="ai:tsumego", white_is_human=True,
    )
    assert ok is False and "watch_white" in reason


def test_can_start_rejects_web_capture():
    # AppBoardReader は Web 盤面（格子線＋ラベルOCR）を読めない
    for kind in ("web_full", "web_partial"):
        ok, reason = bw.tsumego_watch_can_start(
            watch_white=True, view_kind=kind, auto_ai=True,
            black_subtype="ai:tsumego", white_is_human=True,
        )
        assert ok is False and kind in reason


def test_can_start_rejects_when_black_is_not_tsumego_ai():
    # 色の割り当てが逆のまま走らせない入口ゲート
    ok, reason = bw.tsumego_watch_can_start(
        watch_white=True, view_kind="app", auto_ai=True,
        black_subtype="ai:default", white_is_human=True,
    )
    assert ok is False and "ai:default" in reason


def test_can_start_rejects_when_auto_ai_off():
    ok, reason = bw.tsumego_watch_can_start(
        watch_white=True, view_kind="app", auto_ai=False,
        black_subtype="ai:tsumego", white_is_human=True,
    )
    assert ok is False and "auto_ai_black" in reason


def test_can_start_rejects_when_white_is_not_human():
    ok, reason = bw.tsumego_watch_can_start(
        watch_white=True, view_kind="app", auto_ai=True,
        black_subtype="ai:tsumego", white_is_human=False,
    )
    assert ok is False and "白" in reason


def test_watch_status_passes_warnings_through():
    assert bw.tsumego_watch_status(bw.STATUS_WARN, "こまった") == (bw.STATUS_WARN, "こまった")


def test_watch_status_swallows_watching_so_the_answer_book_banner_stays_visible():
    assert bw.tsumego_watch_status(bw.STATUS_WATCHING, bw.WATCHING_TEXT) == ("", "")
    assert bw.tsumego_watch_status("", "") == ("", "")
```

- [ ] **Step 2: テストが落ちることを確認する**

Run: `python -m pytest tests/test_board_watch.py -k "can_start or watch_status" -v`
Expected: FAIL（`AttributeError: module 'katrain.core.board_watch' has no attribute 'tsumego_watch_can_start'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/board_watch.py` の末尾（`AppBoardReader` クラスの後ろ）に足す:

```python
# --- 詰碁モード（白番自動反映。spec 2026-08-22-tsumego-white-auto-apply-design.md） ---
# constants は Kivy を import していないので、この2定数だけ本モジュールから参照してよい
from katrain.core.constants import AI_TSUMEGO, AI_TSUMEGO_SOLVER  # noqa: E402

TSUMEGO_AI_SUBTYPES = (AI_TSUMEGO, AI_TSUMEGO_SOLVER)


def tsumego_watch_can_start(watch_white, view_kind, auto_ai, black_subtype, white_is_human):
    """詰碁の白番自動反映を開始してよいか。(可否, 理由) を返す。

    黒が詰碁 AI・白が人間であることを要求するのが**色の割り当てが逆のまま走らせない**ための
    入口ゲート（reconcile の「AI の手番なら注入しない」行と二重の防御）。
    """
    if not watch_white:
        return False, "設定 watch_white が無効です"
    if view_kind != "app":
        return False, f"アプリ盤面以外のキャプチャ（{view_kind}）は監視しません"
    if not auto_ai:
        return False, "auto_ai_black が無効です（黒が AI でないと応手が返りません）"
    if black_subtype not in TSUMEGO_AI_SUBTYPES:
        return False, f"黒が詰碁戦略ではありません（{black_subtype}）"
    if not white_is_human:
        return False, "白が人間ではありません"
    return True, ""


def tsumego_watch_status(kind, text):
    """詰碁経路のバナー用に監視ステータスを絞る。

    TsumegoBookBanner（gui.kv）は watch_detail を回答帳ステータスより優先して表示するので、
    正常時の「監視中」を出しっぱなしにすると**回答帳バナーが恒久的に隠れる**（詰碁ビューでは
    右パネルごと非表示なので、回答帳の再生状況を知る手段がバナーしかない）。警告だけ通し、
    それ以外は空にして回答帳バナーへ譲る。
    """
    if kind == STATUS_WARN:
        return kind, text
    return "", ""
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `python -m pytest tests/test_board_watch.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/board_watch.py tests/test_board_watch.py
git commit -m "feat(board_watch): 詰碁監視の入口ゲートとバナー整形の純関数を追加"
```

---

### Task 4: `__main__.py` の配線と設定キー

**Files:**
- Modify: `katrain/__main__.py`
  - `_tsumego_capture_trigger`（現行 1075行目の `self("tsumego-capture-apply", ...)`）
  - `_do_tsumego_capture_apply`（現行 1575行目のシグネチャ／1740行目付近の `tsumego_solver_problem` 代入／1838行目付近の `finish_gui`）
  - `_do_new_game`（現行 388行目）
  - `_do_board_watch_start`（現行 703行目付近の `self._board_watcher = watcher`）
  - `_board_watch_trigger`（現行 1518行目付近の停止分岐）
  - 新規メソッド `_stop_board_watcher` / `_start_tsumego_watch` / `_tsumego_watch_state`（`_board_watch_state` の隣＝現行 1463〜1498行目付近に置く）
- Modify: `katrain/config.json`（`tsumego_capture` セクション）
- Modify: `C:\Users\iwaki\.katrain\config.json`（同セクション。**メインセッションで直接編集、KaTrain 停止中に**）

**Interfaces:**
- Consumes: Task 1〜3 の `replay_grid` / `active_kinds` / `tsumego_watch_can_start` / `tsumego_watch_status`、既存の `AppBoardReader` / `BoardWatcher` / `watch_settings_from_config` / `grid_to_move` / `move_to_grid` / `WatchState`、`katrain.core.tsumego_solver_api.moves_from_game`
- Produces: 実行時の挙動のみ（他タスクが参照する新しい API は無い）

**注意:** `__main__.py` は Kivy 依存でユニットテストから import できない。このタスクの検証は
「構文チェック＋実アプリでの手動 E2E」で行う（判定ロジックは Task 1〜3 で既にテスト済み）。

- [ ] **Step 1: キャプチャ経路に `watchable` を通す**

`_tsumego_capture_trigger` の最終行（現行1075行目）を差し替える:

```python
            # watchable: BlueStacks 型の全面盤だけ監視できる（AppBoardReader は Web 盤面の
            # 格子線＋ラベルOCR を持たない）。spec 2026-08-22 §3.1
            self(
                "tsumego-capture-apply", view.grid, ko, margin, black_to_attack, frameless,
                capture_note=capture_note, view_kind=view.kind,
            )
```

`_do_tsumego_capture_apply` のシグネチャ（現行1575行目）を差し替える:

```python
    def _do_tsumego_capture_apply(
        self, grid, ko, margin, black_to_attack=None, frameless=False, capture_note=None, view_kind="app"
    ):
```

- [ ] **Step 2: 影グリッドの種を Game に持たせる**

`_do_tsumego_capture_apply` 内の `self.game.tsumego_solver_problem = solver_problem` の**直後**に足す:

```python
        # 白番自動反映（spec 2026-08-22）の比較基準。枠を張る**前**の認識グリッド＝アプリの盤
        # そのもの。tsumego_book_stones を流用しないのは、あちらが回答帳の照合 try の中で
        # 設定され、照合に失敗すると設定されないため（監視の基準を別機能の副産物にしない）
        self.game.tsumego_app_grid = grid
```

- [ ] **Step 3: 監視の開始・停止・状態取得を実装する**

`_board_watch_state`（現行1463〜1498行目）の**直後**に3つのメソッドを足す:

```python
    def _stop_board_watcher(self, kinds=None):
        """走っている監視スレッドを止める。kinds を渡すとその種別のときだけ止める。

        戻り値は「実際に止めたか」。kinds=("tsumego",) は詰碁の白番自動反映だけを対象にする
        （対局監視モードを巻き添えで止めない）。
        """
        watcher = getattr(self, "_board_watcher", None)
        if watcher is None:
            return False
        if kinds is not None and getattr(self, "_board_watch_kind", None) not in kinds:
            return False
        watcher.stop()
        self._board_watcher = None
        self._board_watch_kind = None
        return True

    def _tsumego_watch_state(self, watch_game):
        """詰碁監視スレッドが読む KaTrain 側のスナップショット（判定は board_watch 側で行う）。

        対局版（_board_watch_state）との差は2点だけ:
        (1) 比較基準が game.stones ではなく**アプリ盤の再現**（影グリッド）。枠は壁と充填を
            足すうえ drop_non_core_stones で枠外の非コア石を消すので、game.stones はアプリの
            盤と両方向にずれている。
        (2) ai_can_respond から region_of_interest 条件を落とす（詰碁では ROI が正常状態）。
            not node.children は**残す**＝回答帳の記録モードで undo 後に打ち直している間の
            誤注入を止める既存の安全弁。
        """
        from katrain.core.board_watch import WatchState, move_to_grid, replay_grid
        from katrain.core.tsumego_solver_api import moves_from_game

        game = self.game
        if game is None or game is not watch_game:
            return None  # 張り替え・停止と競合した瞬間
        if self.tsumego_recording:
            return None  # 回答帳の記録モード（undo 後の打ち直し）では注入しない
        base_grid = getattr(game, "tsumego_app_grid", None)
        if base_grid is None:
            return None
        size_x, size_y = game.board_size
        if size_x != size_y:
            return None  # 長方形の盤は監視対象外
        current = replay_grid(base_grid, moves_from_game(game), size_x)
        if current is None:
            if not getattr(self, "_tsumego_watch_replay_warned", False):
                self._tsumego_watch_replay_warned = True  # 毎周は出さない（1問1回）
                self.log(
                    "tsumego_watch: アプリ盤を再現できないため監視を休止します"
                    "（枠が消した非コア石の位置に着手した可能性）",
                    OUTPUT_INFO,
                )
            return None
        node = game.current_node
        last_move = None
        move = node.move
        if move is not None and move.coords is not None:  # パスは coords=None の Move
            i, j = move_to_grid(move.coords, size_x)
            last_move = (i, j, move.player)
        to_play = node.next_player
        return WatchState(
            current_grid=current,
            last_move=last_move,
            to_play=to_play,
            to_play_is_human=self.players_info[to_play].human,
            ai_can_respond=(
                self.play_analyze_mode == MODE_PLAY and not node.children and not game.end_result
            ),
            move_number=node.depth,
            board_size=size_x,
        )

    def _start_tsumego_watch(self, settings, view_kind):
        """詰碁の白番自動反映を開始する（キャプチャ完了後・プレイヤー設定の検証後に呼ぶ）"""
        from katrain.core.board_watch import (
            AppBoardReader,
            BoardWatcher,
            grid_to_move,
            tsumego_watch_can_start,
            tsumego_watch_status,
            watch_settings_from_config,
        )

        ok, reason = tsumego_watch_can_start(
            watch_white=settings.get("watch_white", True),
            view_kind=view_kind,
            auto_ai=settings.get("auto_ai_black", True),
            black_subtype=self.players_info["B"].player_subtype,
            white_is_human=self.players_info["W"].human,
        )
        if not ok:
            self.log(f"tsumego_watch: 白番の自動反映は開始しません（{reason}）", OUTPUT_DEBUG)
            return
        title = settings.get("window_title", "BlueStacks")
        sizes = [int(s) for s in (settings.get("board_sizes") or [9, 13, 19])]
        watch_game = self.game
        self._tsumego_watch_replay_warned = False
        # 詰碁では ahead（黒を打ったがまだアプリへタップしていない）が白の来る直前の状態
        active_kinds = ("in_sync", "ahead") if settings.get("watch_active_on_ahead", True) else ("in_sync",)

        def on_move(i, j, color, move_number, board_size):
            self("board-watch-play", grid_to_move(i, j, board_size), color, move_number)

        # AppBoardReader は構築時にキャプチャしない（最初の read() で盤矩形と盤サイズを
        # 確定する）ので、ここでメッセージループを画面キャプチャで塞がない
        watcher = BoardWatcher(
            capture_fn=AppBoardReader(title, sizes).read,
            get_state_fn=lambda: self._tsumego_watch_state(watch_game),
            on_move=on_move,
            on_status=lambda kind, text: self._board_watch_status(*tsumego_watch_status(kind, text)),
            settings=watch_settings_from_config(self._config.get("board_watch")),
            active_kinds=active_kinds,
        )
        self._stop_board_watcher()
        self._board_watcher = watcher
        self._board_watch_kind = "tsumego"
        watcher.start()
        self.log("tsumego_watch: 白番の自動反映を開始しました", OUTPUT_INFO)
        self._tsumego_message("白番の自動反映を開始しました", kind="info")
```

- [ ] **Step 4: `finish_gui` の末尾から開始する**

`_do_tsumego_capture_apply` 内の `finish_gui` の最後（`self.log(f"tsumego_capture: ウィンドウ前面化失敗: {e}", OUTPUT_DEBUG)` の except ブロックの直後、`Clock.schedule_once(finish_gui, 0.1)` の前）に足す:

```python
            # 監視の開始は finish_gui の**末尾**で行う。対局者ウィジェットの Clock 経由の
            # 更新が player_subtype を ai:default へ巻き戻すことがあり、この関数がその実効値を
            # 検証して入れ直しているため（実測 2026-07-30）。入口ゲートは検証後の値で判定する
            self._start_tsumego_watch(settings, view_kind)
```

- [ ] **Step 5: 停止フックを付ける**

(a) `_do_new_game`（現行388行目）の `if _log:` の**前**に足す:

```python
        # 詰碁の白番自動反映は局面に紐づくので、新しい局面になったら止める。次のキャプチャが
        # 張り直す。対局監視モード（kind="game"）は巻き添えにしない
        if self._stop_board_watcher(kinds=("tsumego",)):
            self.log("tsumego_watch: 新しい局面になったため白番の自動反映を停止しました", OUTPUT_INFO)
            self._board_watch_status("", "")
```

(b) `_do_board_watch_start` の `self._board_watcher = watcher`（現行703行目）の直後に足す:

```python
        self._board_watch_kind = "game"  # _do_new_game の詰碁専用フックに巻き込まれないように
```

(c) `_board_watch_trigger` の停止分岐、`self._board_watcher = None`（現行1518行目）の直後に足す:

```python
                self._board_watch_kind = None
```

- [ ] **Step 6: 設定キーを両方の config.json に足す**

`katrain/config.json` の `tsumego_capture` セクション、`"ponder_replies": 3,` の直後に足す:

```json
    "watch_white": true,
    "watch_active_on_ahead": true,
```

同じ2行を `C:\Users\iwaki\.katrain\config.json` の `tsumego_capture` セクションにも足す。
**KaTrain が起動していないことを確認してから編集する**（起動中の編集は終了時に上書きで消える）。
確認: `tasklist | grep -i python`（KaTrain のプロセスが無いこと）

- [ ] **Step 7: 構文と import の健全性を確認する**

```bash
python -c "import ast,io; ast.parse(io.open('katrain/__main__.py',encoding='utf-8').read()); print('main ok')"
python -c "import katrain.core.board_watch as bw; print(bw.tsumego_watch_can_start(True,'app',True,'ai:tsumego',True))"
python -c "import json,io; c=json.load(io.open('katrain/config.json',encoding='utf-8')); print(c['tsumego_capture']['watch_white'], c['tsumego_capture']['watch_active_on_ahead'])"
python -c "import json,io; c=json.load(io.open('C:/Users/iwaki/.katrain/config.json',encoding='utf-8')); print(c['tsumego_capture']['watch_white'], c['tsumego_capture']['watch_active_on_ahead'])"
python -m pytest tests/test_board_watch.py tests/test_board_watch_prefetch.py tests/test_tsumego_capture.py -q
```
Expected: `main ok` / `(True, '')` / `True True` ×2 / テスト全 PASS

- [ ] **Step 8: 手動 E2E**

`C:\Users\iwaki\.katrain\config.json` の `debug_level` を `1` にしてから `python -m katrain` で起動し、BlueStacks の詰碁アプリを並べて確認する:

1. F4 でキャプチャ → バナーに「白番の自動反映を開始しました」が数秒出る／詰碁ログに `tsumego_watch: 白番の自動反映を開始しました` が出る
2. AI（黒）の手をアプリでタップ → アプリが白を返す → **KaTrain の盤に白が自動で入る**（詰碁ログに `board_watch: 相手の着手 ... を反映しました`）
3. 回答帳の「正解手順を記録」を押す → 記録モード中は白が入らない（盤が勝手に進まない）
4. `ctrl+alt+d` を押す → 詰碁ログに `board_watch: 監視を停止しました`、以後は白が入らない
5. アプリで次の問題へ進む → バナーが橙の警告になるだけで KaTrain の盤は壊れない
6. 回答帳にヒットする問題をキャプチャ → 回答帳バナー（黄／緑）が**隠れずに**出る

確認後 `debug_level` を `0` に戻す。

- [ ] **Step 9: コミット**

```bash
git add katrain/__main__.py katrain/config.json
git commit -m "feat(tsumego): 詰碁モードで白番（アプリの応手）を自動反映する"
```

---

### Task 5: ドキュメント更新

**Files:**
- Modify: `.claude/rules/tsumego.md`
- Modify: `.claude/rules/tsumego-parameters.md`
- Modify: `docs/superpowers/specs/INDEX.md`

**Interfaces:**
- Consumes: Task 1〜4 の実装結果
- Produces: なし（ドキュメントのみ）

**注意:** `.claude/rules/` 配下の Edit は `dontAsk` モードで拒否されることがある。拒否されたら
サブエージェント（Agent tool）経由で編集・コミットする。

- [ ] **Step 1: `tsumego.md` に落とし穴を追記する**

「やってはいけないこと（詰碁）」節の末尾に足す:

```markdown
- **詰碁の盤面監視で `game.stones` をアプリの盤と比べない** — 枠は壁と充填を**足す**だけでなく `drop_non_core_stones`（`tsumego_frame.py:938`）で枠矩形の境界線上・外側の非コア石を**盤から消す**ので、KaTrain の盤はアプリの盤と**両方向に**ずれている。対局監視モードの `reconcile` をそのまま使うと毎周 `Mismatch` になる。比較基準は「キャプチャ時の認識グリッド（`game.tsumego_app_grid`）＋ root からの着手列」を `replay_grid` で再生した**影グリッド**にする（`board_watch.py`）。影グリッドの上では取りもアプリの盤の意味で計算されるので、枠石を巻き込む KaTrain 側の取りとずれない。判定表（`reconcile`）そのものは1行も変えなくてよい。spec `2026-08-22-tsumego-white-auto-apply-design.md`
```

「機能の全体像」節の冒頭付近（詰碁キャプチャの説明の後ろ）に足す:

```markdown
さらに**白番の自動反映**（2026-08-22・spec `2026-08-22-tsumego-white-auto-apply-design.md`）: BlueStacks の詰碁アプリをキャプチャで出題すると、そのままアプリ盤を監視してアプリが返す白の応手を人間側の手として注入する（`tsumego_capture.watch_white`、既定 ON）。機構は対局監視モード（`BoardWatcher` / `reconcile`）の流用で、比較基準だけ影グリッド（`replay_grid`）に差し替える。OFF は `ctrl+alt+d`。回答帳の記録モード中と、新しい局面になったときは自動で止まる。Web 盤面は対象外（`AppBoardReader` が格子線＋ラベルOCR を持たないため、`view.kind == "app"` のときだけ起動する）。
```

- [ ] **Step 2: `tsumego-parameters.md` にキーを追記する**

「リージョン解析クエリ側（`tsumego_capture` セクション）」の表の末尾に2行足す:

```markdown
| watch_white | true | **白番の自動反映**（spec 2026-08-22）。BlueStacks 型の全面盤（`view.kind == "app"`）で出題したとき、アプリ盤を監視して白の応手を人間側の手として注入する。false で従来どおり手入力 |
| watch_active_on_ahead | true | 監視の低遅延化。`ahead`（黒を打ったがまだアプリへタップしていない）も 50ms 周期で回す＝反映が最大 450ms → 100ms。代償はタップ待ちの間の CPU（画素不変フレームは1周 21〜23ms なので1コアの約45%、false なら約5%）。**正しさは変わらず遅延だけの設定**（`ahead` →「黒＋白が同時に現れた観測」の遷移はどちらでも1周で検出できる） |
```

- [ ] **Step 3: `INDEX.md` に spec を追加する**

「## 盤面監視」節の表に1行足す:

```markdown
| `2026-08-22-tsumego-white-auto-apply-design.md` | 🟢 `board_watch.py` + `__main__.py`。詰碁モードでアプリの白の応手を自動反映（影グリッド方式・`reconcile` は無変更） |
```

- [ ] **Step 4: 追記が正しく入ったか確認する**

```bash
grep -c "2026-08-22-tsumego-white-auto-apply-design" .claude/rules/tsumego.md docs/superpowers/specs/INDEX.md
grep -c "watch_active_on_ahead" .claude/rules/tsumego-parameters.md
```
Expected: それぞれ 1 以上

- [ ] **Step 5: コミット**

```bash
git add .claude/rules/tsumego.md .claude/rules/tsumego-parameters.md docs/superpowers/specs/INDEX.md
git commit -m "docs(tsumego): 白番自動反映の設計・パラメータ・索引を追記"
```
