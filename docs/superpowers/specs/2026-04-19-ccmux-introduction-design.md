# ccmux 導入設計

- 作成日: 2026-04-19
- 対象ツール: [Shin-sibainu/ccmux](https://github.com/Shin-sibainu/ccmux) v0.5.4
- npm パッケージ: [`ccmux-cli`](https://www.npmjs.com/package/ccmux-cli) @0.5.4

## 1. 背景と目的

ccmux は Claude Code を複数ペインで並行実行する Rust 製 TUI マルチプレクサー。ratatui/crossterm/portable-pty ベース。主機能は以下:

- 縦横分割可能な独立 PTY ペイン
- タブ（プロジェクト単位で切り替え）
- ファイルツリー サイドバー（構文ハイライト付きプレビュー）
- Claude Code 実行中のペインを枠色で検知
- `cd` に追従するディレクトリ自動追跡

### 導入動機（ユーザー選択）

- **A. 複数プロジェクト並行**: KaTrain と別プロジェクトを同時に Claude Code で触る
- **B. 長時間タスク + 別作業**: KaTrain のバッチ評価（数分〜10 分クラス）を 1 ペインで回しつつ、別ペインで並行実装・調査
- **D. ファイルツリー + 構文ハイライトのビューワ用途**: 統合 TUI としての閲覧性

### 完成状態

- `ccmux-cli@0.5.4` がグローバルインストール済み。`ccmux` コマンドが PATH から呼べる
- Windows Terminal に「ccmux (KaTrain)」プロファイル登録済み。起動時に KaTrain リポジトリ直下から ccmux TUI が立ち上がる
- VS Code はコード編集・Git 操作に従来通り使用。ccmux は Windows Terminal 上で独立稼働し VS Code とは分離
- Max プランの 5 時間メッセージ上限を共有消費する前提で、同時並行ペインは 2-3 を目安に運用

## 2. インストール手順

### 2.1 事前確認

- Node: v24.14.1（>=16 要件、既に OK）
- npm: 11.11.0
- Rust: 不要（npm postinstall が Releases から Windows 用事前ビルドバイナリを取得する）

### 2.2 インストールコマンド

```bash
# バージョンピン止めでグローバルインストール
npm install -g ccmux-cli@0.5.4

# 確認
ccmux --version   # → 0.5.4 が表示されるはず
where ccmux       # npm global bin 配下のシム (ccmux.cmd) のパスを表示
```

### 2.3 バージョン戦略

pre-1.0（3 日で 6 リリースの非常に活発な開発）のため、**明示バージョン固定**で導入する。

- 更新時: `npm view ccmux-cli versions` でリリース一覧確認 → `npm install -g ccmux-cli@<新バージョン>` でピン止め更新
- ロールバック: 問題があれば `npm install -g ccmux-cli@0.5.4` で戻す

### 2.4 失敗時のチェックポイント

- 権限エラー: `npm config get prefix` で書き込み可能なパスか確認、必要なら `npm config set prefix %APPDATA%\npm`
- バイナリ配置確認: `%APPDATA%\npm\node_modules\ccmux-cli\` にインストール済みか、`bin/` に Windows バイナリがあるか
- PATH 反映: Windows Terminal 再起動で PATH 再読込

## 3. Windows Terminal プロファイル登録

### 3.1 `settings.json` への追加内容

```jsonc
{
  "name": "ccmux (KaTrain)",
  "commandline": "ccmux.cmd",
  "startingDirectory": "C:\\Users\\iwaki\\Documents\\katrain-1.17.1.1\\katrain-1.17.1.1",
  "icon": "🟧",
  "hidden": false,
  "guid": "{新規 GUID を生成}"
}
```

- `commandline`: npm が作る Windows シム `ccmux.cmd` を直接叩く（node 経由で Rust バイナリへ PTY 接続）
- `startingDirectory`: KaTrain リポジトリ固定。起動直後にファイルツリーがそのまま KaTrain を指す
- `guid`: PowerShell で `[guid]::NewGuid()` 生成して埋め込む
- `icon`: 絵文字または画像パス（任意）

### 3.2 フォールバック

`ccmux.cmd` 経由で TUI が崩れる場合は `commandline` を直接 .exe に切り替え:

```
C:\Users\iwaki\AppData\Roaming\npm\node_modules\ccmux-cli\bin\ccmux-windows-x64.exe
```

（実際のパスは `npm config get prefix` に従う）

## 4. 使い方ワークフロー

### 4.1 起動

1. Windows Terminal で「ccmux (KaTrain)」プロファイルを選択
2. ccmux TUI が KaTrain リポジトリをファイルツリー表示した状態で立ち上がる
3. 初期ペインで `claude` 実行 → KaTrain 用 Claude Code セッション開始（ペイン枠がオレンジに変化）

### 4.2 ユースケース A（複数プロジェクト並行）

- ccmux のタブ機能で「KaTrain」「他プロジェクト」を別タブに分ける
- 各タブの初期ペインで `cd <project>` → `claude` で並行セッションを確立
- タブ切り替えで文脈を切り替え

### 4.3 ユースケース B（長時間タスク + 別作業）

- 左ペイン: `python -m katrain_debug --sgf ... --batch` 等の長時間バッチ実行
- 右ペインにスプリット: Claude Code セッションを起動し別の実装・調査を並行
- ペイン枠色でどのペインが Claude 実行中か一目で判別

### 4.4 ユースケース D（ファイルツリー + 構文ハイライト）

- サイドバーの KaTrain ツリーで Claude が編集したファイルを即プレビュー
- `cd` したペインに応じてツリーが追従するのでサブディレクトリ絞り込みも可

### 4.5 キーバインド

README に記載の Ctrl+D/E/W 系を初回起動時に実物で確認する。pre-1.0 で変動の可能性があるため本 spec 内には固定記載せず、使用時に GitHub の最新 README を参照する運用とする。

## 5. リスク / 失敗時対応

| リスク | 対処 |
|---|---|
| `npm install -g` 権限エラー | `npm config get prefix` で書き込み可能パスか確認、必要なら `%APPDATA%\npm` に再設定 |
| Windows Terminal で `ccmux.cmd` が起動しない | `commandline` を Windows バイナリの絶対パスに切り替え（3.2 参照） |
| pre-1.0 破壊的変更で動作不能 | `@0.5.4` にピン止め済み。更新前に `npm view ccmux-cli versions` で確認。問題あれば固定バージョンに戻す |
| Max プラン 5 時間メッセージ上限に抵触 | 同時起動ペインは 2-3 を目安。Claude Code の `/cost` で消費を随時確認 |
| VS Code 統合ターミナル内で ccmux 誤起動 | ccmux は Windows Terminal 専用運用。VS Code 統合ターミナルでの動作は保証外 |
| 不要時のクリーンアップ | `npm uninstall -g ccmux-cli` + Windows Terminal プロファイル削除 + `%APPDATA%\ccmux\` 等が生成されていれば手動削除 |

## 6. 検証項目（導入完了判定）

1. `ccmux --version` → `0.5.4` が表示される
2. Windows Terminal のプロファイル一覧に「ccmux (KaTrain)」が現れる
3. そのプロファイルから起動すると KaTrain リポジトリがファイルツリーに表示される
4. 初期ペインで `claude` 実行 → ペイン枠がオレンジに変化（Claude Code 検知動作確認）
5. ペイン分割のキーバインドで 2 ペイン作成可能
6. 片方のペインで `python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --output text` を実行、他方で別セッション操作できることを確認
7. タブ追加・切り替え動作確認
8. ccmux を抜けて通常シェル（または Windows Terminal のトップ）に戻れる

## 7. スコープ外（やらないこと）

- ccmux 設定ファイル（もし生成されるなら `%APPDATA%\ccmux\`）の詳細カスタマイズ — 初回は素の状態で運用
- KaTrain 側コードの変更 — ccmux は外部ツール導入であり KaTrain のコード・設定には一切触れない
- WSL / Git Bash からの ccmux 起動 — Windows Terminal + Windows バイナリの組み合わせのみ対象
- VS Code 統合ターミナル内での ccmux 動作保証
- Rust ソースからのビルド

## 付録: 実導入時の記録（2026-04-19）

### インストール結果

| 項目 | 実測値 |
|---|---|
| 導入バージョン | `ccmux-cli@0.5.4`（`npm list -g ccmux-cli` で確認） |
| npm global prefix | `C:\Users\iwaki\AppData\Roaming\npm` |
| コマンドシム | `C:\Users\iwaki\AppData\Roaming\npm\ccmux.cmd` と POSIX 用 `ccmux` |
| 実バイナリ | `C:\Users\iwaki\AppData\Roaming\npm\node_modules\ccmux-cli\bin\ccmux.exe` |
| 同梱ランチャ | `C:\Users\iwaki\AppData\Roaming\npm\node_modules\ccmux-cli\bin\cli.js` |

**注**: npm パッケージ内ではバイナリが `ccmux-windows-x64.exe` ではなく単に `ccmux.exe` にリネームされて配置されている。spec §3.2 のフォールバックパスは実在バイナリ名 `ccmux.exe` に置き換える必要がある。

### Windows Terminal プロファイル

| 項目 | 実測値 |
|---|---|
| settings.json パス | `C:\Users\iwaki\AppData\Local\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json` |
| プロファイル名 | `ccmux (KaTrain)` |
| GUID | `{c4cc3983-c0ed-4f29-b8cd-21ebe9f6d968}` |
| commandline | `ccmux.cmd`（フォールバック不要で動作） |
| icon | 🟧（`\ud83d\udfe7` escape で格納） |

### 動作確認結果（Task 4〜7）

- ✅ プロファイル一覧に「ccmux (KaTrain)」表示
- ✅ 起動時に KaTrain リポジトリのファイルツリーが表示される
- ✅ 初期ペインで `claude` 実行時にペイン枠がオレンジに変化
- ✅ ペイン縦分割で独立 PTY が動作
- ✅ 新規タブ作成 + `cd` でファイルツリーが追従

### 運用上の気づき

1. **ccmux は CLI フラグ非対応**: `ccmux --version` / `ccmux --help` ともに "not a directory: --version" エラーとなる。引数はすべて開始ディレクトリとして扱われる仕様。バージョン確認は `npm list -g ccmux-cli` を使う
2. **settings.json の非 ASCII 文字は Unicode escape 保存**: Windows Terminal が既存プロファイル名（「コマンド プロンプト」）を `\u30b3...` 形式で保存しているため、アイコン絵文字も同じ escape 形式で格納した（生絵文字のままでもパース可能だが、ファイル慣習に合わせた）
3. **commandline は `ccmux.cmd` のファイル名のみで動作**: npm global bin が PATH に通っているため絶対パス不要。フォールバック条件（絶対パス指定）は今回発動せず
