# KaTrain 改修版 完全マニュアル 設計

作成日: 2026-08-29
ステータス: 実装中（自律モード＝ユーザー承認ゲートは `/goal` の指示で省略し、判断はここに記録する）

## 0. 目的

改修版 KaTrain（v1.17.1.1）の**利用者向け完全マニュアル**を作る。要件（ユーザー指定）:

1. 初めて使う人でもすぐ理解できる親切丁寧な構成
2. 各 AI 戦略の設定項目を素人向けに解説し、**値をどう変えるとどう挙動が変わるか**が分かる
3. 実際の KaTrain 画面のスクリーンショットつき（設定画面等）
4. 形式は自由＝「一番きれいに見やすくできる方法」

既存の `CUSTOM_AI_FEATURES.md`（2026-04-02 のスナップショット・4機能のみ）と
`docs/ai-strategy-guide.html`（力戦派・攻城・狩猟の設計解説）は**開発者向け／部分的**で、
利用者が最初に読むものが無い。本マニュアルはそれを埋める。

## 1. 決定事項

| 項目 | 決定 | 理由 |
|---|---|---|
| 形式 | **単一の HTML**（`docs/manual/index.html`）＋画像フォルダ（`docs/manual/img/`） | ブラウザで開くだけで読める・目次サイドバー・表・図・スクショを最も見やすく組める。Markdown は表の中の長文とスクショの配置が崩れる |
| 言語 | 日本語（GUI の表示も日本語＝ユーザーの `lang: jp`） | 利用者がこのユーザー本人／日本語話者 |
| スクショの撮り方 | **KaTrain 自身を起動して Kivy の `Window.screenshot` で撮る**自動ツアー（`tools/manual_screenshots.py`） | KaTrain は Kivy アプリで Playwright は使えない。手作業だと再現性が無い。設定画面はコードからプログラム的に開ける（`gui("ai-popup")` 等） |
| スクショ時の設定の隔離 | `USERPROFILE` を一時ディレクトリに向け、`~/.katrain/config.json` の**コピー**で起動 | 起動中の設定書き戻しでユーザーの本物の設定を汚さない（memory: 起動中の編集は終了時に上書きされる） |
| AI 戦略の説明の深さ | 「何をする AI か」「向いている用途」「設定項目ごとに: 既定・範囲・意味・**上げると／下げると**」「注意」 | 要件2。設計の裏付け（実測値・却下案）は spec への参照に留め、本文は利用者の判断に必要な範囲 |
| 既存ドキュメントの扱い | `docs/ai-strategy-guide.html` は残し、本マニュアルから「深く知りたい人向け」としてリンク | 開発者向けとしての価値は別 |
| 公開 | リポジトリにコミット。Artifact 版は画像を縮小して埋め込んだ別ファイルを**追加で**生成できれば公開 | 一次成果物はローカルで開く HTML |

## 2. 構成（目次）

1. はじめに — KaTrain とは／改修版で増えたこと／読み方
2. インストールと初回起動 — 前提・`uv sync`・`python -m katrain`・エンジン／モデルの設定（humanSL モデルが無いと動かない戦略）
3. 画面の見方 — メイン画面各部・対局／分析モード・エンジン状態ランプ・ドットの色
4. 対局する — 新規対局・対局者設定・指導対局・時間・待った／パス／投了・局面生成
5. 分析する — 上部トグル（q/w/e/r/t）・分析オプション・棋譜の読込／保存・評価レポート・一局分析・指導／分析設定
6. **AI 戦略ガイド** — 選び方早見表 → AI 設定画面の使い方 → 戦略ごとの解説（標準／人間らしい／攻撃型／一致率／持碁／難解／詰碁）
7. 詰碁機能 — キャプチャ（4ホットキー）・枠・ソルバ・白番自動反映・回答帳・自動ループ・Web 詰碁・ログ
8. 盤面監視モード — 準備・トグル・バナー・AI 着手の強調表示・制約
9. 盤面テーマ
10. 設定リファレンス — 一般／エンジン設定・`config.json` の各セクション・ログの場所
11. キーボードショートカット一覧
12. トラブルシューティング
付録: 用語集

## 3. スクリーンショット一覧（自動ツアーの撮影順）

| ファイル | 内容 | 取り方 |
|---|---|---|
| `main_play.png` | 対局モード（19路・vs Human-like で数手進めた盤） | 新規対局→白を AI に→黒を数手打つ |
| `menu.png` | メインメニュー（ナビゲーションドロワー） | `nav_drawer.set_state("open")` |
| `popup_newgame.png` / `popup_setup_position.png` / `popup_editgame.png` | 新規対局ダイアログの3タブ | `gui("new-game-popup")`・`content.mode` を切替 |
| `ai_<戦略>.png` ×28 | AI 設定画面（戦略ごと） | `gui("ai-popup")`・`ai_select.select_key()` |
| `popup_settings.png` | 一般・エンジン設定 | `gui("config-popup")` |
| `popup_timer.png` / `popup_teacher.png` | 時間設定／指導・分析設定 | 同上 |
| `main_analyze.png` | 分析モード（ogs.sgf 読込・ドット／候補／地合い ON） | `load_sgf_file(fast=True)` |
| `analysis_menu.png` | 分析オプションのドロップダウン | `analysis_controls.toggle_dropdown()` |
| `popup_report.png` / `popup_reanalyze.png` / `popup_tsumego_frame.png` / `popup_load.png` | 評価レポート／一局分析／詰碁枠／棋譜読込 | 各 open 関数 |
| `tsumego_frame_board.png` | 詰碁の枠を張った盤 | 手製の詰碁 SGF → `gui("tsumego-frame", False, 4)` |
| `tsumego_view.png` | 詰碁ビュー＋回答帳バナー | `tsumego_view=True` 等のプロパティ |
| `board_watch_banner.png` | 盤面監視のバナー | `board_watch_status="bw-watching"` |
| `theme_<名前>.png` | 盤面テーマ（default/koast/lizzie/milos） | `theme_manager.apply_theme()` |
| `zen.png` | 最小表示（F12） | `gui.zen = 2` |

ポップアップは撮影後に **ポップアップ矩形で切り抜く**（座標は Kivy の pos/size から manifest に記録し、後処理で PIL が切る）。

## 4. 検証

- ツアーが全画像を生成し、manifest の件数と `docs/manual/img/` の件数が一致すること
- HTML の `<img src>` が全部存在すること（ビルド後にチェックスクリプトで検証）
- 戦略の設定項目表が `AI_OPTION_VALUES` / `config.json` の既定値と一致すること（同じくスクリプトで突合）
- 本物の `~/.katrain/config.json` が撮影の前後で不変であること（ハッシュ比較）
