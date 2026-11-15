# 観戦用の盤面反映モード Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 観戦中のアプリ盤（野狐 PC 版・BlueStacks）の黒白両方の着手を KaTrain に取り込み、AI 戦略を走らせずに標準の解析で形勢と各手を見られるようにする。

**Architecture:** 判定は新ファイル `katrain/core/board_spectate.py` の純関数 `spectate_sync` に置き、既存 `reconcile` は触らない。監視ループは `BoardWatcher` のサブクラス `SpectateWatcher` が `step()` だけ差し替える（スレッド・撮影失敗処理は継承）。KaTrain 側は 3 つ目の種別 `_board_watch_kind = "spectate"` として `__main__.py` に足し、対局情報（ルール・コミ・アゲハマ）は root の属性とエンジン送信時のコミ補正で反映する。

**Tech Stack:** Python 3.12 / Kivy（kv の静的ウィジェット）/ Win32（ctypes）/ Windows 標準 OCR（PowerShell 5.1 経由の `Windows.Media.Ocr`・依存追加なし）/ pytest

**Spec:** `docs/superpowers/specs/2026-11-15-spectate-watch-design.md`

## Global Constraints

- `katrain/core/board_watch.py` の `reconcile` と `BoardWatcher.step` は変更しない。既存 `tests/test_board_watch*.py` は無変更で通ること
- 観戦中は AI が着手しない・輪／カーソル／応手先読み／自動停止（`auto_stop_sec`）／停滞警告が動かない
- 対応盤は野狐 PC 版と BlueStacks 上の黄盤／木目盤のみ。新しい検出器は作らない
- 既定値: ホットキー `ctrl+alt+w`（`board_watch.spectate_hotkey`）、周期 1000ms（`board_watch.spectate_poll_ms`）、確定は既存 `stable_frames`（2）
- OCR を呼ぶのは開始時と取り込み直し時だけ。GUI スレッドで呼ばない
- 推定で並べた手のノードにはコメント「順序は推定（自動反映 OFF の間の N 手）」を付ける
- 既存の `.py`（`__main__.py` / `engine.py` / `board_watch.py` / `tsumego_capture.py` 等）は CRLF かつ black 未整形。Edit/Write すると PostToolUse フックが全体を再整形するので、**既存ファイルの変更は CRLF 対応の Python パッチスクリプトを Bash で流す**。新規ファイルは普通に Write してよい（line-length 120）
- Kivy ウィジェットは作り直さない（kv に静的に置き、プロパティで出し入れする）
- コミットメッセージは日本語の Conventional Commits。末尾に `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`
- `C:\Users\iwaki\.katrain\config.json` の編集はメインセッションで直接行い、KaTrain が起動していないことを確かめてから書く
- テスト実行は `pytest tests/<file> -q`。KataGo を使うテストは足さない

## Review Focus

1. **コウの取り返し（石数が変わらない 2 手）や、打って取られた石を含む差**: `reimport` になり、例外・誤った手順の追記にならない → Task 1
2. **石を置く途中のフレーム・マウスの四角カーソル・一瞬の誤認識**: 2 周続けて同じ観測でない限り追記も取り込み直しもしない → Task 4
3. **ユーザーが検討中（過去の手を表示・変化を作成・本譜末尾のノードを削除・挿入モード）に着手が来る**: 表示位置は動かず、本譜末尾にだけ足す。末尾ノードが木から消えていたら取り込み直す → Task 5
4. **OCR が使えない／遅い／読み違える（PowerShell 無し・日本語 OCR 無し・タイムアウト・表に無いコミ表記）**: 例外を外へ出さず `None` を返し、入力欄を開く。推測値を黙って使わない → Task 2, 3
5. **観戦中に窓が閉じる・最小化される／KaTrain で新規対局・SGF 読み込みをする**: 前者は警告を出して観戦は残る、後者は観戦を終了して対局者設定を元に戻す → Task 4, 5
6. **アプリ側で過去の局面を表示する（野狐の ◀ ボタン・変化図）**: 石が「消えた」ように見えるが、棋譜を消して取り込み直してはいけない。本譜の途中の局面と一致する観測は何もしない（バナーに「アプリが過去の局面を表示中」）→ Task 1, 4
7. **窓タイトルの手数と盤の画像が一瞬食い違う**: 取り込み直しは通常周期（1000ms）で 2 周続いたときだけ確定する。速い周期（50ms）で確定させない → Task 4

---

## File Structure

| ファイル | 役割 |
|---|---|
| `katrain/core/board_spectate.py`（新規） | 観戦の純関数（`spectate_sync`・野狐の表記の解釈・アゲハマの計算）と `SpectateWatcher` |
| `katrain/core/screen_ocr.py` + `screen_ocr.ps1`（新規） | 画像 → 文字列の行。Kivy 非依存 |
| `katrain/core/tsumego_capture.py` | `find_window_title` を追加（`find_window_rect` と同じ列挙） |
| `katrain/core/board_watch.py` | `AppBoardReader` に `profile_name()` / `window_title_text()` / `last_image()`、`BOARD_PROFILES`、`--save-sample` CLI |
| `katrain/core/sgf_parser.py` / `engine.py` / `game.py` | エンジンへ渡すコミの補正、取り石表示の下駄 |
| `katrain/__main__.py` | 観戦セッション（開始・追記・取り込み直し・対局情報・終了）とホットキー |
| `katrain/gui.kv` / `katrain/gui/popups.py` / `katrain/popups.kv` | 観戦バーと対局情報の入力欄 |
| `tests/test_board_spectate.py` / `tests/test_screen_ocr.py`（新規） | 単体テスト |

---

### Task 1: 同期の判定 `spectate_sync`

**Files:**
- Create: `katrain/core/board_spectate.py`
- Test: `tests/test_board_spectate.py`

**Interfaces:**
- Consumes: `board_watch.BLACK / WHITE / EMPTY`, `board_watch.apply_move_to_grid(grid, i, j, color) -> grid`
- Produces:
  - `class SpectateVerdict(NamedTuple): kind: str; moves: tuple = (); estimated: bool = False; reason: str = ""` — `kind` は `"in_sync" | "moves" | "behind" | "reimport"`、`moves` は `((i, j, color), ...)` の着手順。`behind`＝アプリが本譜の過去の局面を表示している（何もしない）
  - `spectate_sync(tip_grid, observed, to_play, last_mover=None, app_move_number=None, tip_move_number=None, ancestor_grids=()) -> SpectateVerdict` — `ancestor_grids` は本譜の root〜末尾の 1 手前までの盤
  - `SPECTATE_MAX_PERMUTE = 6`（これを超える手数の差は並べ替えを試さず走査順だけ試す）

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_board_spectate.py`。盤は 5 路の文字列から作るヘルパ `g("...../..B../...")` を置く）

```python
def test_in_sync():
    assert spectate_sync(G0, G0, "B").kind == "in_sync"

def test_single_move_and_capture():
    # 白 1 子がアタリ。黒が取る 1 手 → moves 1 手・estimated False
    v = spectate_sync(ATARI, AFTER_CAPTURE, "B", last_mover="B")
    assert (v.kind, v.moves, v.estimated) == ("moves", ((1, 0, "B"),), False)

def test_three_moves_are_alternated_and_marked_estimated():
    v = spectate_sync(G0, G0_PLUS_BWB, "B", last_mover="B")
    assert v.kind == "moves" and [m[2] for m in v.moves] == ["B", "W", "B"] and v.estimated
    assert replay(G0, v.moves) == G0_PLUS_BWB

def test_order_that_needs_capture_first_is_found():
    # 走査順では置けない（取ってからでないと着手禁止）並びを並べ替えで見つける
    v = spectate_sync(NEEDS_ORDER, NEEDS_ORDER_AFTER, "B")
    assert v.kind == "moves" and replay(NEEDS_ORDER, v.moves) == NEEDS_ORDER_AFTER

@pytest.mark.parametrize("tip,obs,kw", [
    (G0, G0_PLUS_BB, {}),                         # 黒 2 手＝交互にならない
    (KO_BEFORE, KO_AFTER_TWO, {}),                # コウの取り返し（石数不変の 2 手）
    (G0, G0_MINUS_STONE, {}),                     # 石が消えただけ
    (G0, G0_PLUS_B, {"last_mover": "W"}),         # 直前手の印と色が合わない
    (G0, G0_PLUS_B, {"app_move_number": 12, "tip_move_number": 10}),  # 手数が合わない
    (G0, G7, {}),                                 # 盤サイズ違い
])
def test_unexplained_diff_reimports(tip, obs, kw):
    assert spectate_sync(tip, obs, "B", **kw).kind == "reimport"

def test_app_showing_earlier_mainline_position_is_behind_not_reimport():   # Review Focus 6
    v = spectate_sync(G0_PLUS_BWB, G0_PLUS_B, "W", ancestor_grids=(G0, G0_PLUS_B, G0_PLUS_BW))
    assert v.kind == "behind"

def test_move_number_check_passes_when_consistent():
    assert spectate_sync(G0, G0_PLUS_B, "B", app_move_number=11, tip_move_number=10).kind == "moves"
```

- [ ] **Step 2: 失敗を確認** — `pytest tests/test_board_spectate.py -q` → ImportError
- [ ] **Step 3: `spectate_sync` を実装**

決めごと（署名とテストだけでは決まらない部分）:
1. サイズ違い → `reimport`。`observed == tip_grid` → `in_sync`。`observed` が `ancestor_grids` のどれかと一致 → `behind`（以降の判定より先）
2. 増えた石＝`tip` が空で `observed` に石がある点。n 個を `to_play` から交互に割り当てたときの黒白の個数が、増えた石の黒白の個数と一致しなければ `reimport`。n==0（石が消えただけ・色が変わっただけ）も `reimport`
3. `last_mover` があり、交互列の最後の色と違えば `reimport`。`app_move_number` と `tip_move_number` が両方あり `tip_move_number + n != app_move_number` なら `reimport`
4. 各色の石を走査順（i, j 昇順）に並べて交互に再生（`apply_move_to_grid`。石のある点・自殺手は失敗扱い）。結果が `observed` と一致すれば採用。不一致で n <= `SPECTATE_MAX_PERMUTE` なら各色の順列の組を総当たりし、最初に一致した並びを採用。無ければ `reimport`
5. `estimated = (n >= 2)`

- [ ] **Step 4: 通ることを確認** — `pytest tests/test_board_spectate.py -q` → PASS、`pytest tests/test_board_watch.py -q` → PASS
- [ ] **Step 5: Commit** — `feat(board-watch): 観戦用の同期判定 spectate_sync を追加する`

---

### Task 2: 野狐の対局情報の解釈とアゲハマの計算（純関数）

**Files:**
- Modify: `katrain/core/board_spectate.py`
- Modify: `katrain/core/tsumego_capture.py:125-155`（`find_window_title` を追加）
- Test: `tests/test_board_spectate.py`

**Interfaces:**
- Produces:
  - `class SpectateInfo(NamedTuple): rules: Optional[str]; komi: Optional[float]; agehama_b: Optional[int]; agehama_w: Optional[int]; next_player: Optional[str]; app_move_number: Optional[int]` — `agehama_b` は**黒が取った石の数**。読めない項目は `None`
  - `parse_fox_title(title: str) -> tuple[Optional[int], Optional[str]]` —（手数, ルール）
  - `parse_fox_panel(lines: list[str]) -> tuple[Optional[float], Optional[str], Optional[int], Optional[int]]` —（コミ, ルール, 黒のアゲハマ, 白のアゲハマ）
  - `engine_komi_offset(rules: str, agehama_b: int, agehama_w: int) -> float`
  - `agehama_base(entered: int, counted_since_import: int) -> int`（= `max(0, entered - counted_since_import)`）
  - `next_player_from(last_mover, app_move_number) -> Optional[str]`
  - `tsumego_capture.find_window_title(title_substring: str) -> str`（`find_window_rect` と同じ候補順で最初に当たった窓のタイトル全文。無ければ `CaptureError`）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_parse_fox_title():
    assert parse_fox_title("> [高級対局室1] > 46372号対局室　観戦中 [98手目] - レーティング - 中国ルール") == (98, "chinese")
    assert parse_fox_title("> [高級対局室1] > 46453号大会対局室　観戦中 [85手目] - 大会") == (85, None)
    assert parse_fox_title("BlueStacks App Player") == (None, None)

def test_parse_fox_panel_real_ocr_lines():
    # 実測 2026-11-15 の OCR 出力（文字間に空白が入る・誤読行が混ざる）
    lines = ["噌 起", "黒 コ ミ 3 又 3 / 4 子", "1 分", "10 秒 1 回", "1 回 。 矜 読 み 1 回", "0 子 ア ゲ ハ マ 3 子"]
    assert parse_fox_panel(lines) == (7.5, "chinese", 3, 0)   # 左＝白が取った数、右＝黒が取った数

@pytest.mark.parametrize("text,komi,rules", [("黒コミ6目半", 6.5, "japanese"), ("黒コミ7目半", 7.5, None), ("黒コミ3又3/4子", 7.5, "chinese")])
def test_komi_table(text, komi, rules):
    assert parse_fox_panel([text])[:2] == (komi, rules)

def test_komi_is_found_even_when_the_label_is_misread():
    # 実測: 1 枚目の本番の切り出しでは「黒 。 ミ 3 又 3 / 4 子」と「コ」を読み違えた
    assert parse_fox_panel(["黒 。 ミ 3 又 3 / 4 子", "0 子 ア ゲ ハ マ 0 子"]) == (7.5, "chinese", 0, 0)

def test_unknown_komi_text_is_none_not_a_guess():
    assert parse_fox_panel(["黒コミ2又1/4子", "アゲハマ"]) == (None, None, None, None)

def test_engine_komi_offset_only_for_territory_rules():
    assert engine_komi_offset("japanese", 3, 0) == -3.0
    assert engine_komi_offset("korean", 0, 2) == 2.0
    assert engine_komi_offset("chinese", 3, 0) == 0.0

def test_agehama_base_does_not_double_count():
    assert agehama_base(5, 2) == 3 and agehama_base(1, 4) == 0

def test_next_player_from():
    assert next_player_from("B", None) == "W"
    assert next_player_from(None, 85) == "W"     # 奇数手目＝黒が打った直後
    assert next_player_from(None, 98) == "B"
    assert next_player_from(None, None) is None
```

- [ ] **Step 2: 失敗を確認** — `pytest tests/test_board_spectate.py -q`
- [ ] **Step 3: 実装** — 行は空白を全部除いてから正規表現で読む。手数は `\[(\d+)手目\]`、ルールは「中国ルール→chinese／日本ルール→japanese／韓国ルール→korean」。アゲハマは `(\d+)子アゲハマ(\d+)子` の左を白・右を黒。コミ表は `{"3又3/4子": (7.5, "chinese"), "6目半": (6.5, "japanese"), "7目半": (7.5, None)}`（表に無ければ `None`）。コミは「黒コミ」の見出しに頼らず、表のキーがどこかの行に含まれるかで拾う（見出しは読み違えることがある）。ただし「又」「目半」を含む行があるのに表のどのキーにも当たらないときは `None`。地を数えるルールは `("japanese", "korean")`、補正は `agehama_w - agehama_b`
- [ ] **Step 4: `find_window_title` を追加**（`find_window_rect` の列挙部を内部関数に括り出して両方から使う。`find_window_rect` の戻り値と例外文言は不変）。テスト: 列挙を monkeypatch した単体テストで候補順が同じこと
- [ ] **Step 5: 通ることを確認** — `pytest tests/test_board_spectate.py tests/test_board_watch_fox.py -q` → PASS
- [ ] **Step 6: Commit** — `feat(board-watch): 野狐の窓タイトルと対局者パネルから対局情報を読む純関数を追加する`

---

### Task 3: 画面の文字認識と野狐パネルの読み取り

**Files:**
- Create: `katrain/core/screen_ocr.py`, `katrain/core/screen_ocr.ps1`
- Modify: `katrain/core/board_watch.py`（`AppBoardReader` に 3 メソッド）
- Test: `tests/test_screen_ocr.py`, `tests/test_board_watch_fox.py`（追記）

**Interfaces:**
- Consumes: `parse_fox_title`, `parse_fox_panel`, `next_player_from`, `SpectateInfo`（Task 2）、`tsumego_capture.find_window_title`
- Produces:
  - `screen_ocr.ocr_lines(img: PIL.Image, scale: int = 3, timeout_sec: float = 8.0) -> Optional[list[str]]` — 失敗（非 Windows・PowerShell 無し・日本語 OCR 無し・タイムアウト・非 0 終了）はすべて `None`。例外を出さない
  - `AppBoardReader.profile_name() -> Optional[str]` — `"quest" | "wood" | "fox"`（`_profile == "wood" and _pale` が fox）
  - `AppBoardReader.window_title_text() -> Optional[str]`、`AppBoardReader.last_image() -> Optional[PIL.Image]`
  - `board_spectate.read_spectate_info(reader, ocr=screen_ocr.ocr_lines) -> SpectateInfo` — fox 以外は `last_mover_color` だけ使い残りは `None`。fox は タイトル → パネル OCR の順に埋める。ルールはタイトル優先。パネルの切り出しは盤矩形 `(bx0, by0, bx1, by1)`・幅 `bw`・高さ `bh` に対し `x: bx1 + 0.07*bw 〜 窓の右端 − 0.10*bw`、`y: 0.04*bh 〜 0.35*bh`（定数 `FOX_PANEL_BOX`）。**右のサイドバー（棋譜鑑賞・絶芸…）を入れてはいけない**＝実測 2026-11-15: 盤の右端から窓の右端まで切ると 1 枚目でコミの行が消えた。上の範囲（1 枚目・2 枚目とも x 764〜1112, y 28〜247 相当）なら両方でコミとアゲハマの行が読めた

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_screen_ocr.py
def test_ocr_lines_returns_none_when_powershell_fails(monkeypatch):
    monkeypatch.setattr(screen_ocr.subprocess, "run", raising_runner)   # FileNotFoundError / TimeoutExpired / returncode 1
    assert screen_ocr.ocr_lines(Image.new("RGB", (50, 20))) is None

@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR")
@pytest.mark.parametrize("path,agehama", [(SPECTATE1, (0, 0)), (SPECTATE2, (3, 0))])
def test_real_ocr_through_production_crop(monkeypatch, path, agehama):
    # 手で決めた矩形ではなく read_spectate_info の切り出しそのものを通す
    reader = _reader_on(monkeypatch, _open(path)); reader.read()
    monkeypatch.setattr(reader, "window_title_text", lambda: "x")
    if screen_ocr.ocr_lines(Image.new("RGB", (60, 30), "white")) is None: pytest.skip("日本語 OCR が無い環境")
    got = read_spectate_info(reader)
    assert (got.komi, got.agehama_b, got.agehama_w) == (7.5, *agehama)

# tests/test_board_watch_fox.py（既存の _reader_on / _open を使う）
def test_spectate_screenshots_read_board_and_info(monkeypatch):
    for path, title, counts, info in [
        (SPECTATE1, "> [高級対局室1] > 46453号大会対局室　観戦中 [85手目] - 大会", (43, 42), (85, "W")),
        (SPECTATE2, "> [高級対局室1] > 46372号対局室　観戦中 [98手目] - レーティング - 中国ルール", (49, 46), (98, "B")),
    ]:
        reader = _reader_on(monkeypatch, _open(path)); grid = reader.read()
        assert (count(grid, "B"), count(grid, "W")) == counts and reader.profile_name() == "fox"
        monkeypatch.setattr(reader, "window_title_text", lambda t=title: t)
        got = read_spectate_info(reader, ocr=lambda img: FAKE_LINES[path])
        assert (got.app_move_number, got.next_player) == info and got.komi == 7.5
```

- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: `screen_ocr.ps1` を作る** — 引数 `-Path <png>`。`[Console]::OutputEncoding = UTF8` を先頭で設定し、`Windows.Media.Ocr.OcrEngine` を言語 `ja` で作って行ごとに出力する。`TryCreateFromLanguage` が null なら終了コード 2。実証済みの呼び方は spec §5.4 の実測と同じ（`AsTask` をリフレクションで呼ぶ）
- [ ] **Step 4: `ocr_lines` を実装** — 画像を `scale` 倍（LANCZOS）にして一時 PNG に保存し、`powershell -NoProfile -ExecutionPolicy Bypass -File screen_ocr.ps1 -Path <png>` を `subprocess.run(capture_output=True, timeout=timeout_sec, creationflags=CREATE_NO_WINDOW)` で呼ぶ。stdout を UTF-8 で読み空行を除く。一時ファイルは必ず消す
- [ ] **Step 5: `AppBoardReader` の 3 メソッドと `read_spectate_info` を実装**（`board_watch.py` はパッチスクリプトで変更）
- [ ] **Step 6: 通ることを確認** — `pytest tests/test_screen_ocr.py tests/test_board_watch_fox.py tests/test_board_spectate.py -q`
- [ ] **Step 7: Commit** — `feat(board-watch): Windows 標準の文字認識で野狐の対局情報を読む`

---

### Task 4: 監視ループ `SpectateWatcher`

**Files:**
- Modify: `katrain/core/board_spectate.py`
- Test: `tests/test_board_spectate.py`

**Interfaces:**
- Consumes: `board_watch.BoardWatcher`（`start/run/stop`・`_on_capture_failure`・`_on_capture_success`・`_active`・`_warn` を継承）、`spectate_sync`
- Produces:
  - `class SpectateState(NamedTuple): tip_grid: list; to_play: str; tip_move_number: Optional[int]; tip_depth: int; board_size: int; ancestor_grids: tuple = ()`
  - `class SpectateWatcher(BoardWatcher)` — `__init__(capture_fn, get_state_fn, on_moves, on_reimport, on_status, settings, hints_fn=None, clock=time.monotonic)`
    - `get_state_fn() -> Optional[SpectateState]`（`None` はその周を飛ばす）
    - `hints_fn() -> (last_mover, app_move_number)`（省略時 `(None, None)`）
    - `on_moves(moves, tip_depth, estimated)`、`on_reimport(observed, reason)`
    - `step_once() -> SpectateVerdict | None` — 確定待ちをせず 1 回だけ判定して即コールバックする（「今すぐ反映」用）
  - `spectate_watch_settings(cfg) -> WatchSettings` — `poll_interval_ms = spectate_poll_ms(既定 1000)`、`auto_stop_sec = 0`、他は `watch_settings_from_config(cfg)` のまま

- [ ] **Step 1: 失敗するテストを書く**（撮影・状態・時計を偽物にして `step()` を直接叩く。既存 `tests/test_board_watch.py` の BoardWatcher テストと同じ作法）

```python
def test_move_needs_two_identical_frames():
    w, calls = make_watcher(frames=[G0_PLUS_B, G0_PLUS_B])
    w.step(); assert calls.moves == []
    w.step(); assert calls.moves == [(((2, 2, "B"),), 0, False)]

def test_flicker_frame_is_ignored():        # Review Focus 2
    w, calls = make_watcher(frames=[G0_PLUS_B, G0, G0])
    for _ in range(3): w.step()
    assert calls.moves == [] and calls.reimports == []

def test_reimport_needs_two_identical_frames_and_fires_once():
    w, calls = make_watcher(frames=[G0_MINUS_STONE] * 4)
    for _ in range(4): w.step()
    assert len(calls.reimports) == 1

def test_reimport_is_confirmed_at_idle_interval_not_fast():   # Review Focus 7
    w, calls = make_watcher(frames=[G0_MINUS_STONE] * 2)
    w.step(); assert w.interval_ms == w.settings.poll_interval_ms and calls.reimports == []

def test_behind_does_nothing_and_shows_hint():                # Review Focus 6
    w, calls = make_watcher(frames=[ANCESTOR] * 3, ancestors=(ANCESTOR,))
    for _ in range(3): w.step()
    assert calls.moves == [] and calls.reimports == [] and "過去の局面" in calls.status[-1][1]

def test_no_second_append_until_state_advances():
    w, calls = make_watcher(frames=[G0_PLUS_B] * 5)      # 状態は進めない
    for _ in range(5): w.step()
    assert len(calls.moves) == 1

def test_never_auto_stops_and_never_warns_stall():
    w, calls = make_watcher(frames=[G0] * 3, clock_step=3600.0)
    for _ in range(3): w.step()
    assert calls.idle_stops == 0 and not any(k == STATUS_WARN for k, _ in calls.status)

def test_capture_failure_warns_but_keeps_running():      # Review Focus 5
    w, calls = make_watcher(frames=[PermanentCaptureError("窓が無い"), G0])
    w.step(); assert calls.status[-1][0] == STATUS_WARN
    w.step(); assert calls.moves == [] and calls.reimports == []

def test_step_once_applies_without_waiting():
    w, calls = make_watcher(frames=[G0_PLUS_BWB])
    assert w.step_once().kind == "moves" and len(calls.moves) == 1
```

- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装** — `step()` を丸ごと上書きする（`BoardWatcher.step` は呼ばない）: 撮影（失敗は継承の `_on_capture_failure`）→ 状態 → `spectate_sync` → `in_sync` は確定カウンタを消して周期を `poll_interval_ms` に戻す／`moves`・`reimport` は「同じ (kind, moves または観測盤) が `stable_frames` 周続いたら」1 回だけコールバックする。`_active()` で次周を速めるのは `moves` のときだけ（`reimport` は通常周期のまま 2 周待つ）。`behind` は確定カウンタを消し、`on_status(STATUS_WATCHING, "アプリが過去の局面を表示中のため反映を待っています")` を出すだけ。コールバック後は `tip_depth` が変わる（追記）か観測盤が変わるまで同じものを投げ直さない。`super().__init__` には `on_move=None`、`on_idle_stop=None`、`player_color_fn=None`、`on_new_game=None` を渡す
- [ ] **Step 4: 通ることを確認** — `pytest tests/test_board_spectate.py tests/test_board_watch.py tests/test_board_watch_new_game.py -q`
- [ ] **Step 5: Commit** — `feat(board-watch): 観戦用の監視ループ SpectateWatcher を追加する`

---

### Task 5: KaTrain 側の観戦セッションと対局情報の反映

**Files:**
- Modify: `katrain/core/sgf_parser.py`（`SGFNode` に root 用の属性）、`katrain/core/engine.py:504`、`katrain/core/game.py:336-341`
- Modify: `katrain/__main__.py`（ホットキー表 `:1104-1110`、`_do_new_game` の監視フック `:396-424`、`_stop_board_watcher` `:1746-1770`、`update_gui` `:256-257`、新ハンドラ群）
- Test: `tests/test_board_spectate.py`（純粋部分）、`tests/test_spectate_engine_komi.py`（新規）

**Interfaces:**
- Consumes: Task 1〜4 の全公開名、`board_watch.board_sgf / stones_to_grid / grid_to_move / AppBoardReader`
- Produces（Task 6 が使う）:
  - Kivy プロパティ: `spectate_active = BooleanProperty(False)`、`spectate_auto = BooleanProperty(True)`、`spectate_text = StringProperty("")`
  - メッセージ（`self("<name>", ...)` → `_do_<name>`）: `spectate-start(reader, grid, size, info)`、`spectate-append(moves, tip_depth, estimated)`、`spectate-reimport(grid, reason, info)`、`spectate-toggle-auto`、`spectate-sync-now`、`spectate-info(rules, komi, agehama_b, agehama_w, next_player)`、`spectate-stop`
  - `self.spectate_info_values() -> dict` — 入力欄の初期値 `{rules, komi, agehama_b, agehama_w, next_player}`（アゲハマは「取り込み時点の分＋取り込み後に KaTrain が数えた分」）
  - `SGFNode.engine_komi_offset: float = 0.0`（root に置く。`engine.py` は `analysis_node.komi + analysis_node.root.engine_komi_offset` を送る）
  - `Game.capture_base: dict = {"B": 0, "W": 0}`（`prisoner_count` の戻り値に足す。キーは**取られた石の色**＝既存の意味のまま。黒のアゲハマは `"W"` 側）

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_spectate_engine_komi.py
def test_engine_query_uses_offset_komi(fake_engine_query):
    root = KaTrainSGF.parse_sgf("(;GM[1]SZ[9]KM[6.5]RU[japanese])"); root.engine_komi_offset = -3.0
    assert sent_komi(fake_engine_query, root) == 3.5 and root.komi == 6.5      # 表示のコミは元のまま

def test_first_root_query_already_carries_the_offset(fake_engine_query):
    # 補正は _do_new_game より前に root へ付ける＝最初の解析から効く
    root = spectate_root(G_SMALL, komi=6.5, rules="japanese", next_player="B", agehama_b=3, agehama_w=0)
    assert root.engine_komi_offset == -3.0 and sent_komi(fake_engine_query, root) == 3.5

def test_counted_captures_follow_the_tip_not_the_displayed_node():
    # 末尾までに白 2 子が取られている棋譜で、表示位置を root に戻しても数は変わらない・下駄も混ざらない
    game = make_game(SGF_WITH_TWO_WHITE_CAPTURED); game.capture_base = {"B": 0, "W": 3}
    game.set_current_node(game.root)
    assert counted_captures(game.root, tip_of(game)) == {"B": 0, "W": 2}

def test_prisoner_count_adds_capture_base():
    game = make_game("(;GM[1]SZ[9]KM[6.5])"); game.capture_base = {"B": 0, "W": 3}
    assert game.prisoner_count == {"B": 0, "W": 3}

# tests/test_board_spectate.py — セッションの判断を純関数に出してテストする
def test_append_plan_keeps_cursor_when_user_is_browsing():
    assert append_plan(cursor_is_tip=False, tip_in_tree=True, insert_mode=False) == "append_keep_cursor"
    assert append_plan(cursor_is_tip=True, tip_in_tree=True, insert_mode=False) == "append_follow"
    assert append_plan(cursor_is_tip=False, tip_in_tree=False, insert_mode=False) == "reimport"   # 末尾ノードが削除された
    assert append_plan(cursor_is_tip=True, tip_in_tree=True, insert_mode=True) == "skip"
```

`spectate_root(grid, komi, rules, next_player, agehama_b, agehama_w) -> GameNode`（`board_sgf` を解析し `engine_komi_offset` を付けて返す）と `counted_captures(root, tip) -> {"B": n, "W": n}`（root の配置に root→tip の着手列を `apply_move_to_grid` で再生し、取られた石を色別に数える。`game.prisoner_count` は**使わない**＝あれは表示中の局面の数で `capture_base` も含む）は `board_spectate.py` に置く。`sent_komi` は既存のエンジンテストの作法に合わせる（`request_analysis` が組むクエリ dict を横取りする。無ければ `engine.py` のクエリ組み立て部を小さな純関数 `query_komi(analysis_node)` に切り出してそれをテストする）。`append_plan` は `board_spectate.py` に置く。

- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: コミ補正と取り石の下駄を実装**（3 ファイルともパッチスクリプト）
- [ ] **Step 4: 観戦セッションを `__main__.py` に実装**

決めごと:
1. **開始**（ホットキーのワーカースレッド `_spectate_trigger`。`_board_watch_trigger` と同じ 2 秒デバウンス・busy ガード。観戦中なら `spectate-stop` を投げて終わり）: `AppBoardReader` で盤を読み、`read_spectate_info` を呼び（OCR はこのスレッドで）、`spectate-start` を投げる
2. **`_do_spectate_start`**: 動いている監視があれば `_stop_board_watcher()`。両者の `(player_type, player_subtype)` を覚えて両方 `PLAYER_HUMAN / PLAYING_NORMAL` にする。ROI を解除。`spectate_root(...)` で **`engine_komi_offset` を付けた root を作ってから** `_do_new_game(move_tree=root)`（解析モードに入る。新規対局の時点で root の解析が出るので、後から付けると最初の解析が補正なしになる。取り込み直しも同じ順）。欠けた値は `game/komi`・`game/rules`・0・「石数が同じなら黒番、黒が 1 多ければ白番、それ以外は黒番」で仮置きし、`info` のコミか手番が `None` のときは取り込み後に入力欄を開く（`self("spectate-info-popup")`）。game に `capture_base` を設定。「取り込み後に数えた分」は常に `counted_captures(root, tip)`（`spectate_info_values()` と `_do_spectate_info` の両方）。`_board_watch_kind = "spectate"`、`spectate_active = True`、`spectate_auto = True`、セッション dict（`reader`・`tip`（root）・`base_move_number`・`agehama_base_b/w`・`saved_players`）を保持して `SpectateWatcher` を起動
3. **`_do_new_game` のフック**: 観戦中に呼ばれたら観戦を終える。ただし観戦自身の取り込み（開始・取り込み直し）は除外する（セッションに「取り込み中」フラグを立てて区別）
4. **`_do_spectate_append`**: `append_plan` に従う。`tip_in_tree` は「`tip` から親をたどって `game.root` に着くか」。追記は `cur = game.current_node` → `game.set_current_node(tip)` → 各手を `game.play(Move(grid_to_move(i, j, size), player=color))` → 新しい末尾を `tip` に記録 → `append_keep_cursor` なら `game.set_current_node(cur)`。`estimated` なら追記した最初のノードの `note` に「順序は推定（自動反映 OFF の間の N 手）」。`tip.depth != tip_depth` なら捨てる。`IllegalMoveException` は警告を出して `reimport` に回す。最後に `update_state(redraw_board=True)`
5. **`_do_spectate_reimport`**: 対局者設定は触らず、同じルール・コミで取り込み直す。野狐は `info` のアゲハマで `agehama_base` を置き直し、それ以外は直前の累計を引き継いで「アゲハマを確認してください」。手番は `info.next_player`、無ければ直前の末尾の手番から交互が続いたと仮定して「手番を確認してください」。バナーに「手順を追えなかったため局面を取り込み直しました」。OCR は `on_reimport` を受けた監視スレッド側で `read_spectate_info` を呼んでからメッセージを投げる
6. **`_do_spectate_info`**: ルール・コミを root の `RU` / `KM` に書き、`agehama_base = agehama_base(入力値, 取り込み後に数えた分)`、`engine_komi_offset` を計算し直す。手番が変わったら root の `PL` を書き換えて取り込み直す（手順が無いときだけ許す。手順があるときは手番欄を無効にするのは Task 6）。値が変わったら `game.analyze_all_nodes(even_if_present=True)`
7. **`_do_spectate_toggle_auto`**: OFF＝ウォッチャを `stop()`（セッションは残す）、ON＝同じ reader で新しい `SpectateWatcher` を起動。**`_do_spectate_sync_now`**: ワーカースレッドで `step_once()` 相当を 1 回（自動 ON 中は何もしない）
8. **`_do_spectate_stop`**（および `_stop_board_watcher` が kind `"spectate"` を止めるとき）: ウォッチャ停止、対局者設定を復元、`spectate_active = False`、バナー消去。`engine_komi_offset` と `capture_base` はその棋譜に残す（読み込んだ局面の属性なので）
9. `spectate_text`: `観戦中 {base+depth}手目`（`base_move_number` が無ければ `取り込みから {depth} 手`）＋ `{ルール名} コミ{komi}`。追記・取り込み直し・情報変更のたびに更新
10. `_board_watch_state` の `get_state_fn` 相当: `tip_grid` は `tip` までの着手列を root の配置に再生して作る（`stones_to_grid` ＋ `replay_grid`）。`game.stones`（表示中の局面）は使わない。同じ再生の途中経過を `ancestor_grids` に入れる
11. ホットキー表に `(watch, "board_watch", "spectate_hotkey", "ctrl+alt+w", "_spectate_trigger", (), "観戦モード トグル")` を足す。`ctrl+alt+d` の開始時に観戦中なら先に `spectate-stop`

- [ ] **Step 5: 通ることを確認** — `pytest tests/test_board_spectate.py tests/test_spectate_engine_komi.py tests/test_board_watch.py tests/test_board_watch_new_game.py tests/test_board_watch_prefetch.py -q`
- [ ] **Step 6: Commit** — `feat(board-watch): 観戦モードのセッション（取り込み・追記・対局情報）を追加する`

---

### Task 6: 観戦バーと対局情報の入力欄

**Files:**
- Modify: `katrain/gui.kv`（`:1201` の `TsumegoBookBanner` の直前に `SpectateBar` を置く）
- Modify: `katrain/gui/popups.py`、`katrain/popups.kv`（`SpectateInfoPopup`）
- Modify: `katrain/__main__.py`（`_do_spectate_info_popup`）
- Modify: `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po` → `python tools/compile_mo.py`
- Test: `tests/test_spectate_gui.py`（新規）

**Interfaces:**
- Consumes: Task 5 のプロパティ・メッセージ・`spectate_info_values()`
- Produces: i18n キー `spectate:auto` / `spectate:sync-now` / `spectate:info` / `spectate:stop` / `spectate:info-title` / `spectate:agehama-b` / `spectate:agehama-w` / `spectate:next-player`

- [ ] **Step 1: 失敗するテストを書く** — kv の文字列検査（Kivy を起動しない。既存の kv 検査テストがあればその作法に合わせる）

```python
def test_spectate_bar_is_static_and_hidden_when_inactive():
    kv = read("katrain/gui.kv")
    bar = block(kv, "SpectateBar:")
    assert "height: dp(34) if root.spectate_active else 0" in bar
    assert "opacity: 1 if root.spectate_active else 0" in bar and "disabled: not root.spectate_active" in bar
    for msg in ("spectate-toggle-auto", "spectate-sync-now", "spectate-info-popup", "spectate-stop"):
        assert msg in kv

def test_i18n_keys_exist_in_both_languages():
    for lang in ("jp", "en"):
        po = read(f"katrain/i18n/locales/{lang}/LC_MESSAGES/katrain.po")
        for key in KEYS: assert f'msgid "{key}"' in po
```

- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: `SpectateBar` を kv に書く** — 横並び: 状態ラベル（`root.spectate_text`・左寄せ・省略あり）／自動反映トグル（`state: 'down' if root.spectate_auto else 'normal'`）／今すぐ反映（`disabled: root.spectate_auto`）／対局情報／終了。非表示時は高さ 0・不透明度 0・無効＝既存レイアウト不変。ウィジェットは kv に静的に置く
- [ ] **Step 4: `SpectateInfoPopup` を作る** — `QuickConfigGui` 系の既存ポップアップ（`NewGamePopup` のルール選択とコミ欄）と同じ部品を使う。欄: ルール／コミ／黒のアゲハマ／白のアゲハマ／次の手番（手順が 1 手でもあれば無効）。開くときに `spectate_info_values()` で埋め、確定で `self.katrain("spectate-info", ...)`。数値でない入力は確定させない
- [ ] **Step 5: `.po` に 8 キーを足して `python tools/compile_mo.py`**
- [ ] **Step 6: 通ることを確認** — `pytest tests/test_spectate_gui.py -q`、`python -m katrain` を起動して観戦バーが出ていない（従来レイアウトのまま）ことを目で確認
- [ ] **Step 7: Commit** — `feat(gui): 観戦バーと対局情報の入力欄を追加する`

---

### Task 7: 盤種プロファイルの表・サンプル保存・設定・文書

**Files:**
- Modify: `katrain/core/board_watch.py`（`BOARD_PROFILES`、`save_sample`、`if __name__ == "__main__":`）
- Modify: `katrain/config.json`（`board_watch` に `"spectate_hotkey": "ctrl+alt+w"`, `"spectate_poll_ms": 1000`）と `C:\Users\iwaki\.katrain\config.json`（同じ 2 キー・メインセッションで直接）
- Modify: `.claude/rules/board-watch.md`（`paths:` に `katrain/core/board_spectate.py`・`katrain/core/screen_ocr.py`・`tests/test_board_spectate.py`・`tests/test_screen_ocr.py` を足し、観戦の節を追記）、`CLAUDE.md`（概要の表の盤面監視の行とディレクトリ構造に 1 行ずつ）、`docs/superpowers/specs/INDEX.md`、`docs/manual/src/*.html` → `python tools/build_manual.py`
- Test: `tests/test_board_watch.py`（追記）

**Interfaces:**
- Produces:
  - `class BoardProfile(NamedTuple): name: str; label: str; reads_info: bool`、`BOARD_PROFILES = {"quest": ..., "wood": ..., "fox": BoardProfile("fox", "野狐囲碁 PC 版", True)}`
  - `save_sample(window_title: str, out_dir: str) -> str`（保存した PNG のパス。ファイル名 `sample_<YYYYMMDD_HHMMSS>.png`）
  - CLI: `python -m katrain.core.board_watch --save-sample [窓タイトル]`（既定は設定の `board_watch.window_title`、保存先 `~/.katrain/board_samples/`）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_every_reader_profile_is_registered():
    assert set(bw.BOARD_PROFILES) == {"quest", "wood", "fox"} and bw.BOARD_PROFILES["fox"].reads_info

def test_save_sample_writes_png(tmp_path, monkeypatch):
    monkeypatch.setattr(bw, "_capture_api", lambda: (lambda t: (0, 0, 300, 300), lambda r: Image.new("RGB", (300, 300)), None, None))
    path = bw.save_sample("x", str(tmp_path))
    assert path.endswith(".png") and Image.open(path).size == (300, 300)

def test_packaged_config_has_spectate_keys():
    cfg = json.load(open("katrain/config.json", encoding="utf-8"))["board_watch"]
    assert cfg["spectate_hotkey"] == "ctrl+alt+w" and cfg["spectate_poll_ms"] == 1000
```

- [ ] **Step 2: 失敗を確認**
- [ ] **Step 3: 実装** — `read_spectate_info` の fox 判定を `BOARD_PROFILES[name].reads_info` に置き換える。CLI は argparse（`board_watch.py` は Kivy を import しないので `KIVY_NO_ARGS` は不要。出力は ASCII のみ）
- [ ] **Step 4: 両方の `config.json` にキーを足す**（ユーザーローカルは KaTrain の窓が無いことを確認してから）
- [ ] **Step 5: 文書を更新**（rules・CLAUDE.md・INDEX.md・マニュアル。spec の状態を「実装済み」に）
- [ ] **Step 6: 全体の確認** — `pytest --ignore=tests/test_ai.py -q`（既知の順序依存フレーク `test_collapsable_panel.py` はペア実行で切り分ける）
- [ ] **Step 7: 実機確認（野狐の観戦）** — 開始 → 自動反映で数手 → OFF → 数手後に「今すぐ反映」（「順序は推定」が出る）→ 過去の手を表示したまま着手が来る（表示が動かない）→ 対局情報でアゲハマを変える（日本ルールで目差が動く・中国ルールで動かない）→ 終了で対局者設定が戻る。ログ `board_watch:` 行を Grep で確認
- [ ] **Step 8: Commit** — `feat(board-watch): 盤種プロファイルの表とサンプル保存を追加し、観戦モードの設定と文書を整える`
