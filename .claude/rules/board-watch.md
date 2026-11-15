---
description: 盤面監視モード（board_watch / screen_marker / screen_cursor / move_difficulty）の機能の全体像と設定キー
paths:
  - "katrain/core/board_watch.py"
  - "katrain/core/screen_marker.py"
  - "katrain/core/screen_cursor.py"
  - "katrain/core/move_difficulty.py"
  - "tests/test_board_watch*.py"
  - "tests/test_screen_*.py"
  - "tests/test_move_difficulty.py"
  - "tests/test_ring_difficulty_prefetch.py"
---

# 盤面監視

盤面監視まわりを触る前に読む。一次記録は `docs/superpowers/specs/2026-08-18-board-watch-design.md`（追記6〜14）。2026-11-15 に CLAUDE.md の概要の表から文言を変えずに移した。

`board_watch.py`: BlueStacks 上の対局アプリの着手を検出して人間側の手として片方向注入（トグル `ctrl+alt+d`）。**KaTrain の AI の色は対局画面の手前（下）の対局者アイコンから自動判定**して設定中の戦略をその色へ移し、監視中にアプリで次の対局が始まれば〈2子以内の序盤形＋逆色のアイコン＋3周〉自動で新規対局に張り直す＝連続対局〈黄盤のみ・木目盤は設定どおり＝spec 追記10〉。AI の着手はアプリ盤の該当交点の真上に輪を出して示す（`screen_marker.py`・設定画面 general 節のドロップダウン〈表示しない／6色〉＝`board_watch.highlight_color`。同じ行の「難易度」チェック〈`board_watch.highlight_difficulty`〉で輪を局面の難しさで塗り分ける＝明らか緑／難解赤／普通は設定色・相手の着手と同時に humanSL 9段 8visits を先回り＝輪は待たない・判定は `katrain/core/move_difficulty.py`・spec 追記11。監視の自前キャプチャからは `WDA_EXCLUDEFROMCAPTURE` で除外＝spec 追記6。対応盤は黄盤〈囲碁クエスト系〉＋明るい木目盤アプリ〈detect_board 失敗時に格子線検出へ自動フォールバック・9/13/19路〉＝spec 追記7、＋野狐囲碁の PC 版〈淡い黄の盤＝黄盤検出も通るので盤の色で判別して必ず格子線検出で読む・空点の四角カーソルは石にしない・窓は `board_watch.window_title` の「対局室」〈config.json には JSON のエスケープで書く＝Kivy の JsonStore は cp932 で読むので生の日本語は化ける〉・自分の色はユーザー一覧の自分の行の赤いピンの左隣の石アイコンから読む〈`fox_self_color`・黄盤と同じく AI の色の入れ替えと連続対局が動く・自分が黒の実物は未確認＝spec 追記13〉・途中から ON にしたときの手番は直前手の印から読む〈`last_mover_color`・囲碁クエストの赤い四角・木目盤アプリの輪も同じ＝対応する盤すべて＝spec 追記14〉・観戦は対象外＝spec 追記12〉。さらにその交点へ**マウスカーソルも運ぶ**〈`screen_cursor.py`・同じ行のチェック`board_watch.move_cursor`・既定 OFF。`SetCursorPos` だけでクリックはしない／新しい手のとき1回だけ＝毎周運ぶとカーソルが貼り付く／アプリが前面のときだけ＝前面化はしない＝spec 追記8〉。対局が5分進まなければ監視は自動停止〈`board_watch.auto_stop_sec`・相手待ちが20秒を超えたら 50ms→400ms に減速＝アプリの投了・時間切れは KaTrain に伝わらないので終局後の空回り対策・spec 追記9〉）／ `tsumego_autoloop.py`: 詰碁の自動ループ（ADB でアプリを操作。トグル `ctrl+alt+d` ではなく `ctrl+alt+a`。spec `2026-08-23-tsumego-autoloop-design.md`）
