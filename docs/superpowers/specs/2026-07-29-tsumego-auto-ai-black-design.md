# 詰碁キャプチャ: 黒番AI自動着手（正解手自動再生）設計書

日付: 2026-07-29
ステータス: 承認済み

## 目的

F4詰碁キャプチャで盤面反映後、黒番（詰碁の手番）をAI（KataGo最善手 = 正解手）が自動で打ち、
ユーザーは白番として応手する。白が打つたびに黒AIが自動応答し、詰碁の正解変化を対話的に検証できる。

## 要件

- キャプチャ適用後、黒番AIが自動で最善手（リージョン内 = 詰碁枠内の正解手）を打つ
- ユーザーが白を打つと、黒AIが自動で応答する（以降繰り返し）
- AIの着手は必ず詰碁枠内の最善手であること（枠外の手を打たない）
- 白の考慮中に秒読みビープが鳴らないこと
- 設定でOFFにでき、OFF時は従来動作（解析モードのまま、AIは打たない）に戻ること

## アプローチ（採用: A）

**A（採用）: KaTrain標準のプレイヤー設定＋プレイモードを使う**
キャプチャ適用時に黒=AI（`ai:default`）・白=人間（normal）に設定し、プレイモードへ切替える。
KaTrain既存の対局ループ（`update_state` が「プレイモード ∧ 手番プレイヤーがAI ∧ 解析完了 ∧ 子ノードなし」で
`_do_ai_move` を自動発火）がそのまま回る。追加コードは約10行。

- B（不採用）: 白着手のたびに独自フックで ai-move を発行 — 対局ループの再実装になる
- C（不採用）: 初手のみAIが打つワンショット — 白応手への自動応答の要件を満たさない

## 成立根拠（コード確認済み）

1. **AIの着手はリージョン内最善手になる**: `DefaultStrategy.generate_move()`（`ai.py:576`）は
   `wait_for_analysis()`（既存解析の完了待ちのみ、新規クエリなし）→ `cn.candidate_moves[0]` を打つ。
   候補手リストは `set_analysis` の枠外刈り取り（242e48c）適用済みのため、必ず詰碁枠内の最善手。
2. **白着手後の解析もリージョン限定**: `Game.play()`（`game.py:545`）は `region_of_interest` 設定時に
   2段解析（全盤fast→リージョン限定）を行うため、黒の応答もリージョン内最善手になる。
3. **AI自動発火はプレイモード時のみ**: `update_state`（`__main__.py:261`）の条件
   `play_analyze_mode == MODE_PLAY`。現状のキャプチャ適用フローは
   `_do_new_game(move_tree=...)` と `_do_tsumego_frame` が解析モードへ切替えるため、
   最後にプレイモードへ戻す必要がある。

## 追加発見: 全盤fast解析とのレース（要ゲート）

`analysis_complete` は**全盤fast解析（25 visits・リージョンなし）の完了時点で True になる**
（`game_node.py:276` — `is_normal_query` はリージョン有無を見ない）。このため対策なしでは、
リージョン限定解析（500 visits）が返る前に AI 自動着手が発火し、**刈り取り前の枠外候補・浅読み候補**を
打ってしまう（枠外B4バグの「実際に着手される」版）。

対策（リージョン解析完了ゲート）:

1. `GameNode.clear_analysis`: analysis 辞書に `"region_requested": False` / `"region_completed": False` を追加
2. `GameNode.analyze`: `region_of_interest` 指定時に `analysis["region_requested"] = True`
3. `GameNode.set_analysis`: リージョン刈り取りブロック内で最終結果（`not partial_result`）時に
   `analysis["region_completed"] = True`
4. `update_state` の AI 発火ブロック: リージョン設定時は `region_completed` が立つまで発火を待つ。
   未発行（`region_requested` が偽 = 手動リージョン選択直後等）なら一度だけリージョン解析を発行して待つ
   （自己回復。`Game.play` / `_do_tsumego_frame` 経由のノードは発行済みフラグが立つため二重発行しない）

このゲートは正解手の品質にも必須（ゲートなしだと25visitsの浅い解析で着手が決まる）。

## 変更内容

### 1. `katrain/__main__.py` — `_do_tsumego_capture_apply`

`_do_tsumego_frame(ko, margin)` の後（メッセージループスレッド内）:

```python
auto_ai = settings.get("auto_ai_black", True)
if auto_ai:
    self.update_player("B", player_type=PLAYER_AI, player_subtype=AI_DEFAULT)
    self.update_player("W", player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL)
    Clock.schedule_once(lambda _dt: self.play_mode.play.trigger_action(duration=0))
```

- `update_player` はメッセージループスレッドからの呼び出しが既存パターン（`_do_new_game` 内 372-378行）。
- **モード切替はトグル（`switch_ui_mode`）ではなくプレイタブの `trigger_action` を直接スケジュール**する。
  理由: `_do_new_game` / `_do_tsumego_frame` が解析モードへの切替クリックを既にスケジュール済みで、
  `self.play_mode.mode` の読み値がクリック発火前だと競合する。ターゲット明示なら常にプレイモードで確定
  （Kivy Clock は同一timeoutのイベントをスケジュール順に発火するため、解析切替→プレイ切替の順で収束）。
- `select_mode` は同一モードなら no-op なので二重発火も安全。

### 2. タイマー一時停止 — `finish_gui` 内（メインスレッド）

```python
self.controls.timer.paused = True
```

プレイモードでは人間手番中に秒読み（ユーザー設定 30秒×5、sound=true）が進行しビープが鳴るため
（`controlspanel.py:204`）、キャプチャ適用時に対局タイマーを一時停止する。
`auto_ai_black` が有効な場合のみ実施（従来動作モードでは解析モードのままなのでタイマーは進まない）。

### 3. 設定フラグ — `tsumego_capture.auto_ai_black`

- `katrain/config.json` と `C:\Users\iwaki\.katrain\config.json` の両方の `tsumego_capture` に
  `"auto_ai_black": true` を追加（GUIパネルなし、config直接編集で切替）。
- ローカルconfigの編集は KaTrain 非起動を `FindWindowW(None, 'KaTrain v1.17.1')` で確認してから
  メインセッションで直接行う（サブエージェント委任禁止・起動中は終了時に上書きされるため）。
- `false` の場合: プレイヤー設定・モード切替・タイマー停止をすべてスキップし、従来動作
  （解析モードで反映のみ）となる。

## 仕様上の注意（既知の挙動）

- プレイヤー設定（黒=AI:default）は次の通常対局にも引き継がれる。詰碁後に通常対局を始める際は
  新規対局ダイアログで黒のAI種別を選び直す（KaTrainの標準挙動、対策しない）。
- 「待った」はプレイモードのスマートundo（AI手＋人間手の2手戻し）が働き、白の別の応手を試せる。
- 詰碁が解け切った局面では黒AIがパスすることがある（KataGo仕様、問題なし）。
- プレイモードのUI状態（ヒント非表示等）が適用されるが、tsumego_view では解析コントロール自体が
  非表示のため実質影響なし。

## 検証

- ユニットテスト対象の純ロジックなし（GUIグルーのみ）。既存テストスイート（267件）の回帰確認。
- E2E（ユーザー確認）: F4キャプチャ → 黒AIが枠内に自動着手 → 白応手 → 黒が自動応答 →
  秒読みビープが鳴らない → 待った動作 → F12復帰 → `auto_ai_black: false` で従来動作。
