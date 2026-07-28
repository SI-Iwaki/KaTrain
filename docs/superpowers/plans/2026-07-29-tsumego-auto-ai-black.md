# 詰碁キャプチャ黒番AI自動着手 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** F4詰碁キャプチャ後、黒番AI（`ai:default` = KataGo最善手 = 正解手）が自動着手し、ユーザーが白番で応手できるようにする。

**Architecture:** KaTrain標準の対局ループを再利用する。キャプチャ適用時に黒=AI・白=人間を設定しプレイモードへ切替えるだけで、既存の `update_state` がAI手番を自動発火する。ただし `analysis_complete` は全盤fast解析（25visits・リージョンなし）完了で真になるため、リージョン解析（500visits・枠外刈り取り済み）完了を待つゲートを `update_state` に追加する。

**Tech Stack:** Python 3.12 / Kivy / KataGo。スペック: `docs/superpowers/specs/2026-07-29-tsumego-auto-ai-black-design.md`

## Global Constraints

- コミットメッセージは日本語・Conventional Commits形式（`feat:` / `fix:` / `docs:`）
- 既存ファイルに black を実行しない（コードベース未整形のため巨大差分になる）
- テストは `python -m pytest tests/ --ignore=tests/test_ai.py -q`（humanSLモデル依存を除外）
- ローカル設定 `C:\Users\iwaki\.katrain\config.json` の編集は**サブエージェント委任禁止**・メインセッションで直接実施。編集前に KaTrain 非起動を確認（起動中は終了時に上書きされ消える）
- パッケージ `katrain/config.json` とローカル config の両方に同じキーを追加すること
- 作業ブランチ: `feat/tsumego-auto-ai-black`（master から分岐、実装開始時に作成）

---

### Task 1: リージョン解析完了ゲート（AIが刈り取り前候補を打つレースの防止）

**Files:**
- Modify: `katrain/core/game_node.py` — `clear_analysis`(107-109) / `analyze`(185-212) / `set_analysis` リージョン刈り取りブロック(253-263)
- Modify: `katrain/__main__.py` — `update_state` AI発火ブロック(279-287)
- Test: `tests/test_tsumego_capture.py`（末尾に追加。既存の `_fake_analysis` ヘルパを再利用）

**Interfaces:**
- Consumes: 既存 `GameNode.set_analysis(analysis_json, refine_move, additional_moves, region_of_interest, partial_result)`、`_fake_analysis(moves_visits)`（test_tsumego_capture.py:129）
- Produces: `node.analysis["region_requested"]: bool`（リージョン解析発行済み）/ `node.analysis["region_completed"]: bool`（リージョン最終結果反映済み）。Task 2 はこのゲートの存在を前提とする（Task 2 自体はこれらのキーに触らない）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_capture.py` の末尾（`test_cli_image_mode` の後）に追加:

```python
def test_region_completed_flag_gates_fast_analysis():
    # AI自動着手ゲートの回帰テスト: 全盤fast解析の完了時点では region_completed は立たず、
    # リージョン限定解析の最終結果で立つ（これがないとAIが刈り取り前の枠外・浅読み候補を打つ）
    from katrain.core.game_node import GameNode

    node = GameNode(properties={"SZ": "13"})
    node.set_analysis(_fake_analysis([("B4", 38)]))  # 全盤fast: region指定なし
    assert node.analysis_complete
    assert not node.analysis.get("region_completed")
    # 部分結果（ストリーミング途中）でも立たない
    node.set_analysis(_fake_analysis([("A12", 100)]), region_of_interest=[0, 10, 4, 12], partial_result=True)
    assert not node.analysis.get("region_completed")
    # リージョン限定解析の最終結果で立つ
    node.set_analysis(_fake_analysis([("A12", 335)]), region_of_interest=[0, 10, 4, 12])
    assert node.analysis.get("region_completed")


def test_analyze_marks_region_requested():
    # update_state 側の自己回復（未発行なら一度だけ発行）が二重発行しないためのフラグ
    from katrain.core.game_node import GameNode

    class FakeEngine:
        def request_analysis(self, node, **kwargs):
            self.requested = kwargs

    node = GameNode(properties={"SZ": "13"})
    engine = FakeEngine()
    assert not node.analysis.get("region_requested")
    node.analyze(engine, region_of_interest=[0, 10, 4, 12])
    assert node.analysis.get("region_requested")
    assert engine.requested["region_of_interest"] == [0, 10, 4, 12]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -q -k region`
Expected: 新規2件が FAIL（`region_completed` / `region_requested` が立たない）。既存 `test_region_analysis_prunes_outside_moves` は PASS のまま。

- [ ] **Step 3: `game_node.py` を実装**

`clear_analysis`（107-109行）を置換:

```python
    def clear_analysis(self):
        self.analysis_visits_requested = 0
        self.analysis = {
            "moves": {},
            "root": None,
            "ownership": None,
            "policy": None,
            "completed": False,
            "region_requested": False,
            "region_completed": False,
        }
```

`analyze`（185行〜）のメソッド本体先頭（`engine.request_analysis(` の直前）に追加:

```python
        if region_of_interest:
            self.analysis["region_requested"] = True
```

`set_analysis` のリージョン刈り取りブロック（253-263行）の辞書内包の直後に追加（`if region_of_interest and not additional_moves:` ブロック内、同インデント）:

```python
                if not partial_result:
                    self.analysis["region_completed"] = True
```

- [ ] **Step 4: `__main__.py` の AI発火ブロックにゲートを追加**

`update_state` 内（279-287行）を置換:

```python
                if (
                    cn.analysis_complete
                    and next_player.ai
                    and not cn.children
                    and not self.game.end_result
                    and not (teaching_undo and cn.auto_undo is None)
                ):  # cn mismatch stops this if undo fired. avoid message loop here or fires repeatedly.
                    region = self.game.region_of_interest
                    if not region or cn.analysis.get("region_completed"):
                        self._do_ai_move(cn)
                        Clock.schedule_once(self._play_stone_sound, 0.25)
                    elif not cn.analysis.get("region_requested"):
                        # リージョン設定時、全盤fast解析だけでAIを発火させると刈り取り前の枠外・浅読み
                        # 候補を打ってしまう。リージョン解析が未発行の局面（手動リージョン選択直後等）
                        # では一度だけ発行して完了を待つ（Game.play/_do_tsumego_frame 経由は発行済み）
                        cn.analyze(self.game.engines[cn.next_player], region_of_interest=region)
```

- [ ] **Step 5: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -q`
Expected: 14 passed（既存12 + 新規2）

- [ ] **Step 6: 回帰確認**

Run: `python -m pytest tests/ --ignore=tests/test_ai.py -q`
Expected: 269 passed（既存267 + 新規2。Kivy DeprecationWarning 13件は既知・無関係）

- [ ] **Step 7: コミット**

```bash
git add tests/test_tsumego_capture.py katrain/core/game_node.py katrain/__main__.py
git commit -m "fix(tsumego): リージョン設定時はリージョン解析完了までAI自動着手を待機"
```

---

### Task 2: キャプチャ適用時の黒AI設定・プレイモード切替・タイマー停止

**Files:**
- Modify: `katrain/__main__.py` — `_do_tsumego_capture_apply`(611-638)
- Modify: `katrain/config.json` — `tsumego_capture` セクション(51-59)
- Test: なし（GUIグルーのみ。既存スイートの回帰確認で担保）

**Interfaces:**
- Consumes: Task 1 のゲート（プレイモード切替後の初回AI発火がリージョン解析完了まで待たされる）。既存 `self.update_player(bw, player_type=, player_subtype=)`、`self.play_mode.play`（ToggleButton、`trigger_action` はメインスレッド必須）、`self.controls.timer.paused`（BooleanProperty）。定数 `PLAYER_AI` / `AI_DEFAULT` / `PLAYER_HUMAN` / `PLAYING_NORMAL` は `__main__.py` で import 済み（391行・376-377行で使用実績）
- Produces: 設定キー `tsumego_capture.auto_ai_black: bool`（デフォルト true）

- [ ] **Step 1: `_do_tsumego_capture_apply` を修正**

現在のコード（611-638行）を以下に置換:

```python
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
        settings = self._config.get("tsumego_capture") or {}
        maximize = settings.get("maximize_on_capture", True)
        auto_ai = settings.get("auto_ai_black", True)
        if auto_ai:
            # 黒=AI（最善手=正解手）・白=人間。AI自動着手はプレイモードでのみ発火する。
            # モード切替は switch_ui_mode のトグルではなくプレイタブを直接トリガーする
            # （_do_new_game/_do_tsumego_frame が解析モード切替クリックをスケジュール済みで、
            #  トグルだと mode の読み値がクリック発火前になり競合する。Kivy Clock は同一timeoutの
            #  イベントをスケジュール順に発火するため、後からの直接指定で必ずプレイモードに収束）
            self.update_player("B", player_type=PLAYER_AI, player_subtype=AI_DEFAULT)
            self.update_player("W", player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL)
            Clock.schedule_once(lambda _dt: self.play_mode.play.trigger_action(duration=0))
            self.controls.set_status("詰碁盤面を取り込みました（黒:AIが正解手を打ちます）", STATUS_INFO)
        else:
            self.controls.set_status("詰碁盤面を取り込みました", STATUS_INFO)

        def finish_gui(_dt):
            # kvバインディングがグラフィックス命令に触るため、プロパティ変更はメインスレッドで行う
            if auto_ai:
                self.controls.timer.paused = True  # プレイモードで白番考慮中の秒読みビープを防ぐ
            if maximize:
                self.tsumego_view = True  # 盤面拡大（下部ナビは残る。F12/`で通常表示に復帰）
            try:
                user32 = ctypes.windll.user32
                hwnd = user32.FindWindowW(None, Window.title)
                if hwnd and user32.IsIconic(hwnd):
                    Window.restore()
                Window.raise_window()
            except Exception as e:
                self.log(f"tsumego_capture: ウィンドウ前面化失敗: {e}", OUTPUT_DEBUG)

        Clock.schedule_once(finish_gui, 0.1)
```

- [ ] **Step 2: パッケージ `katrain/config.json` にフラグを追加**

`tsumego_capture` セクション（51-59行）の `"maximize_on_capture": true` の後に追加:

```json
    "tsumego_capture": {
        "enabled": true,
        "hotkey": "f4",
        "window_title": "BlueStacks",
        "board_sizes": [9, 13, 19],
        "frame_margin": 4,
        "frame_ko": false,
        "maximize_on_capture": true,
        "auto_ai_black": true
    },
```

- [ ] **Step 3: 起動スモーク＋回帰確認**

Run: `python -c "import ast; ast.parse(open('katrain/__main__.py', encoding='utf-8').read()); import json; json.load(open('katrain/config.json', encoding='utf-8')); print('OK')"`
Expected: `OK`

Run: `python -m pytest tests/ --ignore=tests/test_ai.py -q`
Expected: 269 passed

- [ ] **Step 4: コミット**

```bash
git add katrain/__main__.py katrain/config.json
git commit -m "feat(tsumego): キャプチャ後に黒番AIが正解手を自動着手（白は人間・タイマー停止）"
```

---

### Task 3: ローカルconfig反映・ドキュメント更新【メインセッション直接実施・サブエージェント委任禁止】

このタスクはローカル設定 `C:\Users\iwaki\.katrain\config.json` を含むため、**サブエージェントに委任せずコントローラー（メインセッション）が直接実行する**（CLAUDE.mdルール: サブエージェントが成功を報告しても実際に反映されないことがある）。

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json` — `tsumego_capture` セクション（リポジトリ外・コミット対象外）
- Modify: `CLAUDE.md` — 概要セクションの tsumego_capture 記述
- Test: なし（設定・ドキュメントのみ）

- [ ] **Step 1: KaTrain が起動していないことを確認**

Run: `python -c "import ctypes; print('RUNNING' if ctypes.windll.user32.FindWindowW(None, 'KaTrain v1.17.1') else 'NOT_RUNNING')"`
Expected: `NOT_RUNNING`。`RUNNING` の場合はユーザーに終了を依頼して待つ（起動中に編集すると終了時に上書きされ消える）。

- [ ] **Step 2: ローカル config に `auto_ai_black` を追加**

`C:\Users\iwaki\.katrain\config.json` の `tsumego_capture` セクションの `"maximize_on_capture": true` の後に `"auto_ai_black": true` を追加（パッケージ config と同じ形）。

- [ ] **Step 3: CLAUDE.md の概要を更新**

概要セクションの詰碁画面キャプチャの記述:

```
詰碁画面キャプチャ（tsumego_capture: グローバルホットキーでBlueStacks上の詰碁アプリ盤面を認識しKaTrainに反映+外枠自動適用）を追加
```

を以下に置換:

```
詰碁画面キャプチャ（tsumego_capture: グローバルホットキーでBlueStacks上の詰碁アプリ盤面を認識しKaTrainに反映+外枠自動適用+黒番AIが正解手を自動着手し白番はユーザーが応手、auto_ai_black:falseで従来動作）を追加
```

- [ ] **Step 4: コミット**

```bash
git add CLAUDE.md
git commit -m "docs(tsumego): 黒番AI自動着手の概要をCLAUDE.mdに反映"
```

---

## E2E検証（実装完了後・ユーザー確認）

1. `python -m katrain` を起動し、BlueStacks の詰碁を表示して **F4**
2. 盤面反映後、数秒（リージョン解析完了）で黒AIが**枠内に**自動着手すること
3. 白で応手 → 黒が自動で応答すること（以降繰り返し）
4. 白の考慮中に秒読みビープが鳴らないこと
5. 「待った」（undo）で白の応手をやり直せること、F12 で通常表示に戻ること
6. `auto_ai_black: false` に変更して F4 → 従来動作（解析モードのまま・AIは打たない）に戻ること
