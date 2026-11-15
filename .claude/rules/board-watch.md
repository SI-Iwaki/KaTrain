---
description: 盤面監視モード（board_watch / screen_marker / screen_cursor / move_difficulty）の機能の全体像と設定キー
paths:
  - "katrain/core/board_watch.py"
  - "katrain/core/screen_marker.py"
  - "katrain/core/screen_cursor.py"
  - "katrain/core/move_difficulty.py"
  - "katrain/core/board_spectate.py"
  - "katrain/core/screen_ocr.py"
  - "katrain/core/screen_ocr.ps1"
  - "tests/test_board_watch*.py"
  - "tests/test_screen_*.py"
  - "tests/test_move_difficulty.py"
  - "tests/test_ring_difficulty_prefetch.py"
  - "tests/test_board_spectate.py"
  - "tests/test_screen_ocr.py"
  - "tests/test_spectate_*.py"
---

# 盤面監視

盤面監視まわりを触る前に読む。一次記録は `docs/superpowers/specs/2026-08-18-board-watch-design.md`（追記6〜14）。2026-11-15 に CLAUDE.md の概要の表から文言を変えずに移した。

`board_watch.py`: BlueStacks 上の対局アプリの着手を検出して人間側の手として片方向注入（トグル `ctrl+alt+d`）。**KaTrain の AI の色は対局画面の手前（下）の対局者アイコンから自動判定**して設定中の戦略をその色へ移し、監視中にアプリで次の対局が始まれば〈2子以内の序盤形＋逆色のアイコン＋3周〉自動で新規対局に張り直す＝連続対局〈黄盤のみ・木目盤は設定どおり＝spec 追記10〉。AI の着手はアプリ盤の該当交点の真上に輪を出して示す（`screen_marker.py`・設定画面 general 節のドロップダウン〈表示しない／6色〉＝`board_watch.highlight_color`。同じ行の「難易度」チェック〈`board_watch.highlight_difficulty`〉で輪を局面の難しさで塗り分ける＝明らか緑／難解赤／普通は設定色・相手の着手と同時に humanSL 9段 8visits を先回り＝輪は待たない・判定は `katrain/core/move_difficulty.py`・spec 追記11。監視の自前キャプチャからは `WDA_EXCLUDEFROMCAPTURE` で除外＝spec 追記6。対応盤は黄盤〈囲碁クエスト系〉＋明るい木目盤アプリ〈detect_board 失敗時に格子線検出へ自動フォールバック・9/13/19路〉＝spec 追記7、＋野狐囲碁の PC 版〈淡い黄の盤＝黄盤検出も通るので盤の色で判別して必ず格子線検出で読む・空点の四角カーソルは石にしない・窓は `board_watch.window_title` の「対局室」〈config.json には JSON のエスケープで書く＝Kivy の JsonStore は cp932 で読むので生の日本語は化ける〉・自分の色はユーザー一覧の自分の行の赤いピンの左隣の石アイコンから読む〈`fox_self_color`・黄盤と同じく AI の色の入れ替えと連続対局が動く・自分が黒の実物は未確認＝spec 追記13〉・途中から ON にしたときの手番は直前手の印から読む〈`last_mover_color`・囲碁クエストの赤い四角・木目盤アプリの輪も同じ＝対応する盤すべて＝spec 追記14〉・観戦は対象外＝spec 追記12。観戦は別モード＝下の「観戦モード」節〉。さらにその交点へ**マウスカーソルも運ぶ**〈`screen_cursor.py`・同じ行のチェック`board_watch.move_cursor`・既定 OFF。`SetCursorPos` だけでクリックはしない／新しい手のとき1回だけ＝毎周運ぶとカーソルが貼り付く／アプリが前面のときだけ＝前面化はしない＝spec 追記8〉。対局が5分進まなければ監視は自動停止〈`board_watch.auto_stop_sec`・相手待ちが20秒を超えたら 50ms→400ms に減速＝アプリの投了・時間切れは KaTrain に伝わらないので終局後の空回り対策・spec 追記9〉）／ `tsumego_autoloop.py`: 詰碁の自動ループ（ADB でアプリを操作。トグル `ctrl+alt+d` ではなく `ctrl+alt+a`。spec `2026-08-23-tsumego-autoloop-design.md`）

## 観戦モード（spec `2026-11-15-spectate-watch-design.md`）

プロ同士の対局など、黒白とも画面から来る対局を KaTrain に取り込んで勝率・目差と各手の分析を見るモード。AI は打たず、輪・カーソル・先読み・自動停止・停滞警告は出さない。トグルは `ctrl+alt+w`（設定 `board_watch.spectate_hotkey`）、ポーリング周期は `spectate_poll_ms`（既定 1000）。

- 操作バー: 自動反映 / 今すぐ反映 / 対局情報（ルール・コミ・アゲハマ・次の手番）/ 終了。自動 OFF の間に溜まった手は「今すぐ反映」でまとめて追記し、順序が推定になる手にはコメント「順序は推定（まとめて反映した N 手）」を付ける（自動 ON で確認窓内に2手が来たときも同じ）
- ファイル: `board_spectate.py`（同期判定 `spectate_sync`・`SpectateWatcher`・対局情報の読み取り `read_spectate_info`）、`screen_ocr.py` / `screen_ocr.ps1`（Windows 標準 OCR で野狐のパネルを読む）、`__main__.py` のセッション処理 `_do_spectate_*`、盤種の表 `BOARD_PROFILES`（`board_watch.py`・`reads_info` が True の盤種だけ対局情報を自動で読む）
- 新しい盤種の調査用に `python -m katrain.core.board_watch --save-sample [窓タイトル]` で窓を `~/.katrain/board_samples/` へ PNG 保存できる
- アプリが過去の局面・変化図を出している間は反映を待つ（`spectate_sync` の `behind`: 増えた石が無い／野狐の `[N手目]` が本譜の末尾より前か同じ）。野狐以外の盤は手数が読めないので変化図と本物の着手を区別できない

やってはいけないこと:

- **`reconcile` を観戦のために緩めない** — 観戦は別の純関数 `spectate_sync` で判定する（対局監視の安全側の判定を壊さない）
- **アゲハマのコミ換算を面積ルールに掛けない** — エンジンに渡すコミ `komi + agehama_w - agehama_b` は地を数えるルールのときだけ。2026-11-15 に KataGo で検証（9路・日本ルール・3000 visits）: 全手順を再生 -3.13 / initialStones でオフセット無し -4.10 / オフセット有り -3.21。中国ルールは -3.54 vs -3.58 でアゲハマは結果に影響しない
- **OCR の癖を忘れない** — Windows OCR は本番の切り出しで「0」を「ロ」と読み、「黒コミ」のラベルも誤読する。ラベルでなくコミの表記そのもので解釈し、ロ／〇／O は 0 として扱う。パネルの切り出しを窓の右端まで広げない（サイドバーが入るとコミの行が消える）
- **「取り込み後に数えた取り石」を `game.prisoner_count` から取らない** — それは表示中のノードの値で `capture_base` を含む。root から末尾まで再生して数える（`counted_captures`）
- **新規対局ポップアップの前に対局者を戻す** — ポップアップは `_do_new_game` のあとに対局者ウィジェットを読み直すので、観戦前の対局者は `spectate_end_for_new_game` で先に戻しておく
