---
description: 盤面監視モード（board_watch / screen_marker / screen_cursor / move_difficulty）の機能の全体像と設定キー
paths:
  - "katrain/core/board_watch.py"
  - "katrain/core/screen_marker.py"
  - "katrain/core/screen_cursor.py"
  - "katrain/core/move_difficulty.py"
  - "katrain/core/move_candidates.py"
  - "katrain/core/board_spectate.py"
  - "katrain/core/screen_ocr.py"
  - "katrain/core/screen_ocr.ps1"
  - "tests/test_board_watch*.py"
  - "tests/test_screen_*.py"
  - "tests/test_move_difficulty.py"
  - "tests/test_move_candidates.py"
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

- **実機確認（2026-11-15・野狐の観戦）で直した点**: (1) 帯のボタンは高さとフォントを固定する（`SizedButton` は高さ未指定だと文字が巨大化して上のパネルへはみ出す）。帯は 2 段（文言／ボタン）で、先頭の「盤を拡大」が右パネルを畳む（`spectate_panel_hidden`・畳んでいる間は勝率と目差 `spectate_eval` を帯に出す）。(2) 日本ルールの部屋のコミ表記は「黒6.5目コミ出し」＝`parse_fox_panel` が「N目…出し」を数字で拾う。(3) 黒白 1 手ずつの 2 手は順序が決まるので`estimated` にしない（10 秒の早碁では確定待ちの間に 2 手進むのが普通）。(4) 対局情報の数字欄は`numeric_input_filter` で全角を半角に直す（日本語入力のままだと欄のフォントに無く豆腐になる）。画面の確認は別プロファイルで起動して `Window.screenshot` を撮る（窓の幅は 4 の倍数にする＝そうでないと画像が斜めに歪む）

## 複数候補の表示と差し替え（spec 追記15・2026-11-19）

設定画面の輪の行の「候補」チェック（`board_watch.highlight_candidates`・既定 OFF）で、決定手の太い輪に加えて細い輪＋輪の内側の字を出す。字は 最＝KataGo の最善手／感＝第一感（humanSL 9段の確率最大・悪手でもそのまま）／人＝悪手でない中で 9段の確率最大（第一感の損失が 2 目を超える・KataGo が読んでいない、のときだけ別の点に出る）／全＝最善手と第一感が同じ点／罠＝決定手が罠。同じ点の役割は 1 つの輪にまとめる（1 点に最大 2 字・輪は最大 4 つ）。表示した候補をアプリで打つと KaTrain の決定手をその手に差し替える（`board_watch.candidate_swap`・既定 ON）。候補以外の点は従来どおり警告。

- ファイル: 判定 `katrain/core/move_candidates.py`（`candidate_roles` / `candidate_marks` / `ring_roles_of` / `swap_targets`）、描画 `screen_marker.py`（`mark_bgra`・`MarkerSet`）、差し替えの判定 `board_watch.swap_candidate`（verdict `swap`）と `BoardWatcher._on_swap_verdict` / `_resolve_swap`、本体 `__main__._board_watch_marks` / `_do_board_watch_swap`、盤の置き換え `Game.replace_last_move`
- 設定キー: `highlight_candidates`（false）／`candidate_swap`（true）／`candidates_max_loss`（2.0＝「悪手でない」の上限・目。GUI なし）
- 罠の記録は戦略の `ring_decision` → 着手ノードの `ai_decision`（`generate_ai_move`）。難解 / 難解＋と擬態が書く

やってはいけないこと:

- **罠かどうかを着手ノードに記憶しない** — ノードが現局面になるのは `game.play` の中、戦略の記録が付くのはその後。すき間で監視スレッドが計算すると「罠でない」が固定される。役割（最・感・人）だけ記憶し、罠は毎回読む
- **難解の記録を `last_decision_info` に書かない** — 自己対局ハーネスと batch_eval は `last_decision_info` を持つ戦略を「判定情報あり」として集計する。輪の表示用は `ring_decision`
- **第一感が悪手かどうかの判定に visits の下限を掛けない** — 通常解析は visits を数手に集中させるので、掛けると第一感が浅いだけの手番で「人」が別の点へ飛ぶ。下限を掛けるのは代わりの手を選ぶときだけ
- **字を輪の色で塗らない** — 2 字は輪の線に掛かるので同じ色に沈む（赤い輪の上の「罠感」が読めなかった）。白＋黒い縁取り
- **バッジを輪の外に出さない** — 囲碁は候補が隣の交点に並ぶ。将棋の marker.py の四隅バッジは隣どうしで重なる（モックで確認）
- **差し替えの反映待ちを手数で見ない** — 差し替えは手数が変わらない。最終手が差し替え先になったかで見る（`_resolve_swap`）
- **`swap_candidate` から「相手の 1 手つき」の分岐を外さない** — 早碁では確定前に相手の石が載り、外すと mismatch から戻れない
- **差し替えで最終手のノードを分岐として残さない** — `children[0]` を辿る集計・保存が打たれなかった手へ進む。親から外す
- **設定画面の輪の行にコントロールを足したら実際に起動して撮る** — `python tools/manual_screenshots.py --out <dir> --groups settings`。4 つ目でラベルが 2 行に折れた
