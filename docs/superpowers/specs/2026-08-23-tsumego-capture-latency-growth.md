# 詰碁キャプチャの反映時間が問題数とともに伸びる（自動ループ 200 問で 5→10 秒）

2026-08-23。ユーザー報告: 自動ループ（`tsumego_autoloop`）を 200 問ほど回すと盤面キャプチャの
反映が 5 秒→10 秒近くまで遅くなる。詰碁アプリの回答制限は 30 秒なので改善が要る。

結論: **気のせいではない。GUI 側（Kivy メインスレッド）で 1 問ごとに +12〜16ms ずつ線形に
伸びる処理があった**。原因は右パネル `CollapsablePanel` のタブボタン（KivyMD）を
プレイ／解析のモード切替のたびに作り直していたこと × Kivy の `bind()` が observer 数に
比例して遅くなること。修正は `katrain/gui/kivyutils.py` の `CollapsablePanel` のみ（解析・
着手選択は一切触らない）。

## 1. 実測（本番の台帳とログから）

`~/.katrain/tsumego_ledger.jsonl`（ts・elapsed_s・log 名）と詰碁ログのファイル名時刻から
「ログ open（= `tsumego-capture-apply` の先頭）→ problem_ready（= `finish_gui` 末尾）」を
復元。セッション 4（12:03〜13:49・306 問）を 25 問ごとに:

| 問 | 中央値 [s] | p90 | book 経路 | ai:tsumego | solver |
|---|---|---|---|---|---|
| 0-24 | 1.7 | 2.8 | 1.5 | 1.7 | 1.6 |
| 100-124 | 3.0 | 4.5 | 2.9 | 3.0 | 2.8 |
| 200-224 | 4.2 | 4.9 | 4.5 | 4.2 | 3.8 |
| 275-299 | 5.7 | 6.5 | 6.0 | 5.7 | 6.3 |

- 約 +1.3 秒/100 問の線形増加。**回答帳（book）経路＝解析ゼロ でも同じ傾き**なので KataGo
  ではなく共通の GUI 経路。
- 残っていた 59 本のログで `枠の採否判定に X 秒`（0.7〜0.8）と `着手決定に X 秒`（中央値 ~1.0）は
  平坦＝解析側ではない。
- 1 問の総所要 `elapsed_s`（problem_ready→結果）は 10〜13 秒で平坦＝ADB screencap の劣化でもない
  （遅くなっていればポップアップ検出の 2 フレーム等で総所要も伸びる）。

## 2. 再現（ADB なし・GUI パイプラインだけ）

`docs/superpowers/specs/calibration-data/tsumego/capture_loop_latency_probe.py`: 実 KaTrain を
起動して `tsumego-capture-apply` を固定 6 盤面で N 回投げ、ready（投入→problem_ready）・
メインスレッドの長いフレーム・停止中のスタック（`sys._current_frames()` サンプリング）・
`theme_cls` の observer 数・GC 所要を JSONL に落とす。

修正前（n=89 / 120）:

- `ready` から apply 本体を引いた **gap = 0.43 秒 + 12.2 ms × 問**（v1 の最小二乗）。v3 では
  1 問目 0.36 秒 → 120 問目 1.9 秒。
- gap の正体は **メインスレッドの長いフレーム 1 本**（例 `long=[(0.387, 0.36)]`）。`finish_gui`
  自体は一瞬（`Window.raise_window` の時刻 = problem_ready の時刻）。
- 停止中のスタック（採れたぶん）は全部
  `controlspanel.select_mode → load_ui_state → CollapsablePanel.set_option_state → build_options →
  CollapsablePanelTab.__init__（KivyMD ボタン）→ BackgroundColorBehavior.__init__ の
  theme_cls.bind(...) → weakmethod.__call__`。サンプルが少ない（0.45 秒で 4 本）のは、
  メインスレッドが GIL を握る C 呼び出し（Kivy の bind のスキャン・GC）の中に居るから。
- `theme_cls` の observer: 181 → +78/問/プロパティ（primary_palette・accent_palette・
  theme_style の 3 本）。オブジェクト総数・スレッド数・Clock イベント数・メモリは平坦＝
  普通のリークではない。
- GC: 世代 2 の回収が毎問 0.1〜0.2 秒走っていた（作り直しのゴミが毎問 gen2 を起こす）。

Kivy `bind()` のマイクロベンチ（死んだ bound method の observer を積んでから 1 回 bind）:
0 個 0.012ms → 2000 個 0.62ms → 8000 個 2.6ms → 20000 個 6.3ms（線形）。`bind()` は重複チェックで
既存 observer を全部デリファレンスする（WeakMethod の `__call__`）ため。`theme_cls` の
プロパティは一度も変わらないので死んだ WeakMethod が dispatch 時の掃除を受けず、永久に残る。

## 3. 機構（なぜ毎問作り直していたか）

`CollapsablePanel.__init__` が `option_active` を `build_options` に bind していた。
`load_ui_state`（モード切替のたび）→ `set_option_state` が `option_active[ix] = ...` を
1 項目ずつ書く → 項目ごとに全タブ（KivyMD ボタン×3 ＋ アイコンボタン ＋ ヘッダ）を作り直す。
3 パネル × 3 項目 × 1 問あたり 2〜3 回のモード切替（`_do_new_game` / `_apply_tsumego_region` /
`play.trigger_action`）＝ 1 問で 100 個超の KivyMD ボタン。ボタンは `__init__` でグローバル
`theme_cls` に bound method を bind し、作り直しのたびに `self.bind(state=lambda ...)` も
1 本増えていた。ユーザーがタブをクリックしたときの `trigger_select` も同じ経路で作り直していた。

## 4. 修正（`katrain/gui/kivyutils.py` CollapsablePanel）

- `option_active` は `build_options` でなく `_sync_option_buttons` に bind: 既存ボタンの
  `state` を合わせるだけ。ボタン本数が `options / option_colors / option_active` の zip と
  合わないとき（kv の構築中は 3 つが `__init__` の後に順に届く）だけ `build_options`。
- `set_option_state` / `trigger_select` は値が変わるときしか `option_active` を書かない。
- `<< / >>` ボタンのアイコン更新の `self.bind(state=...)` は `__init__` で 1 回だけ。

修正後（同じプローブ・60 問）: ready 0.13〜0.3 秒で**一定**、長いフレームなし、
`theme_cls` observer 58 で不変、gen2 GC が毎問走らなくなった。初回の定数ぶん（~0.35 秒）も消える。
回帰: `tests/test_collapsable_panel.py`（旧コードでは 6 本とも失敗することを確認済み）。

## 5. 調査の教訓

- **GUI スレッドの停止は関数をラップしても見えない**（`finish_gui` の中身は全部 0ms だった）。
  Kivy の `Clock.schedule_interval(tick, 0)` でフレーム間隔を測り、長いフレームの間に
  `sys._current_frames()` を別スレッドから採る。GIL を握る C 呼び出し中はサンプルが採れないので
  「採れた本数の少なさ」自体が手掛かりになる。
- **オブジェクト数・メモリが平坦でも線形劣化はあり得る**: 小さな `BoundCallback` の蓄積と、
  それを線形にスキャンする `bind()` の組合せ。`gc.get_objects()` の型別センサス差分
  （`BoundCallback +552/問`）が最初の物証だった。
- 本番のログに時刻が無くても、**ログ名の時刻 × 台帳の ts − elapsed_s** で区間を復元できる。
