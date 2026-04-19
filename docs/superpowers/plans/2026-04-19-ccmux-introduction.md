# ccmux 導入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ccmux-cli@0.5.4` をユーザー環境にグローバルインストールし、Windows Terminal から KaTrain リポジトリ直下で起動する「ccmux (KaTrain)」プロファイルを整備する。

**Architecture:** npm 経由インストール (`ccmux-cli@0.5.4`) → postinstall で GitHub Releases から Windows バイナリ取得 → Windows Terminal `settings.json` にプロファイル追加 → 対話的に動作確認。KaTrain のコード・設定には一切触れない。

**Tech Stack:** Node.js v24.14.1 / npm 11.11.0 / Windows Terminal / ccmux (Rust TUI)

**Spec:** [`docs/superpowers/specs/2026-04-19-ccmux-introduction-design.md`](../specs/2026-04-19-ccmux-introduction-design.md)

---

## Task 1: 事前環境確認

**Files:** なし（読み取り専用コマンドのみ）

- [ ] **Step 1: Node/npm バージョンを確認**

Run:
```bash
node --version
npm --version
```
Expected:
```
v24.14.1
11.11.0
```
Node が v16 未満なら中止して Node の更新から行う。

- [ ] **Step 2: npm global prefix を確認**

Run:
```bash
npm config get prefix
```
Expected: `C:\Users\iwaki\AppData\Roaming\npm` または類似の書き込み可能パス。
書き込み権限がない場所（例: `C:\Program Files\nodejs`）の場合、以下で再設定:
```bash
npm config set prefix %APPDATA%\npm
```
その後 PATH に `%APPDATA%\npm` が入っているかも確認。

- [ ] **Step 3: 既存 ccmux がないことを確認**

Run:
```bash
where ccmux 2>&1 || echo "not installed (OK)"
```
Expected: `not installed (OK)` もしくはコマンド未検出エラー。既にインストール済みの場合はバージョン確認してスキップ判断。

---

## Task 2: ccmux-cli を npm グローバルインストール

**Files:** なし（ユーザー環境の変更のみ）

- [ ] **Step 1: バージョンピン止めインストール**

Run:
```bash
npm install -g ccmux-cli@0.5.4
```
Expected: postinstall で GitHub Releases から Windows バイナリ (`ccmux-windows-x64.exe`, 約 4.2 MB) を取得。最後に `added 1 package in Xs` 等のメッセージ。

失敗時の対処:
- `EACCES` / 権限エラー → Task 1 Step 2 に従い prefix を `%APPDATA%\npm` に再設定
- ネットワークエラー → 再実行、または後述のバイナリ直接ダウンロードで代替

- [ ] **Step 2: インストール結果を検証**

Run:
```bash
ccmux --version
```
Expected:
```
0.5.4
```
(正確な出力形式は `ccmux-cli 0.5.4` か `0.5.4` 単体かツール依存。`0.5.4` という文字列が含まれていれば OK)

- [ ] **Step 3: ccmux 実行パスを記録**

Run:
```bash
where ccmux
```
Expected 例:
```
C:\Users\iwaki\AppData\Roaming\npm\ccmux
C:\Users\iwaki\AppData\Roaming\npm\ccmux.cmd
```
この値（特に `.cmd` パスが存在すること）を記録。Task 3 のプロファイル設定で使用。

- [ ] **Step 4: バイナリが実際に配置されていることを確認**

Run:
```bash
ls "$APPDATA/npm/node_modules/ccmux-cli/bin/" 2>&1 || ls "C:/Users/iwaki/AppData/Roaming/npm/node_modules/ccmux-cli/bin/"
```
Expected: `ccmux-windows-x64.exe` が含まれること。存在しない場合 postinstall が失敗している可能性。`npm install -g ccmux-cli@0.5.4 --verbose` で再実行してログ確認。

---

## Task 3: Windows Terminal プロファイルを登録

**Files:**
- Modify: `C:\Users\iwaki\AppData\Local\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json`（ストア版の場合）
  - または: `C:\Users\iwaki\AppData\Local\Microsoft\Windows Terminal\settings.json`（スタンドアロン版）

- [ ] **Step 1: settings.json の場所を特定**

Windows Terminal を起動 → 設定（Ctrl+,）→ 左下「JSON ファイルを開く」。開いたファイルのフルパスを記録。

- [ ] **Step 2: 新規 GUID を生成**

PowerShell で:
```powershell
[guid]::NewGuid()
```
Expected: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` 形式の GUID。この値を記録し、以降の JSON の `guid` フィールドに使用。

- [ ] **Step 3: settings.json の profiles.list に追加**

settings.json の `"profiles"` → `"list"` 配列に以下の要素を追加（既存プロファイルの末尾に追加、直前のブラケットに `,` を追加するのを忘れずに）:

```jsonc
{
  "name": "ccmux (KaTrain)",
  "commandline": "ccmux.cmd",
  "startingDirectory": "C:\\Users\\iwaki\\Documents\\katrain-1.17.1.1\\katrain-1.17.1.1",
  "icon": "🟧",
  "hidden": false,
  "guid": "{Step 2 で生成した GUID}"
}
```

注意点:
- `guid` は `{...}` で囲む（Windows Terminal 仕様）
- `startingDirectory` のバックスラッシュは JSON エスケープで `\\` と二重化
- `commandline` は Task 2 Step 3 で記録した `.cmd` のファイル名（PATH 通しで動作するため絶対パス不要）

- [ ] **Step 4: settings.json を保存し構文チェック**

ファイル保存後、Windows Terminal 画面下部にエラー通知が出ないことを確認。JSON 構文エラーがあれば赤バナーで警告が出る。

- [ ] **Step 5: プロファイル一覧に表示されることを確認**

Windows Terminal の新規タブドロップダウン（`^` または Ctrl+Shift+Space）を開く。「ccmux (KaTrain)」が一覧に現れていること。

---

## Task 4: ccmux 起動スモークテスト

**Files:** なし

- [ ] **Step 1: ccmux プロファイルから起動**

Windows Terminal のドロップダウンから「ccmux (KaTrain)」を選択。
Expected:
- ccmux の TUI が立ち上がる
- ファイルツリー サイドバーに KaTrain リポジトリのディレクトリ構造が表示される
- 初期ペインが 1 つ存在する

失敗時:
- `ccmux.cmd` が起動しない、または TUI が崩れる → spec §3.2 に従い `commandline` を絶対パスに変更:
  ```
  C:\Users\iwaki\AppData\Roaming\npm\node_modules\ccmux-cli\bin\ccmux-windows-x64.exe
  ```
  （Task 2 Step 4 で確認した実パスに合わせる）

- [ ] **Step 2: 初期ペインで `pwd` を実行**

ccmux の初期ペインで:
```bash
pwd
```
Expected: `C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1` またはその POSIX 形式（起動シェル依存）。KaTrain リポジトリ直下になっていること。

- [ ] **Step 3: Claude Code を起動しオレンジ枠を確認**

ccmux の初期ペインで:
```bash
claude
```
Expected:
- Claude Code セッションが開始される
- **そのペインの枠がオレンジ色に変化する**（ccmux の Claude Code 検知機能）

確認できたら `/exit` または Ctrl+C で Claude Code を終了（ペインは残す）。

---

## Task 5: マルチペイン並行動作を確認（ユースケース B）

**Files:** なし

- [ ] **Step 1: ペインを分割**

ccmux の README 記載のキーバインド（Ctrl+D or Ctrl+E 系）でペインを縦分割。
Expected: 右側に新しいペインが追加されシェルが起動する。キーバインドで迷ったらプロジェクトの README を参照: https://github.com/Shin-sibainu/ccmux#readme

- [ ] **Step 2: 左ペインで軽量バッチ処理を実行**

左ペインで（数十秒で終わる検証用コマンド）:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --output text
```
Expected: KataGo が起動し、30 手目の hunt 戦略決定結果がテキストで出力される（30 秒前後）。

- [ ] **Step 3: バッチ実行中に右ペインで別操作ができることを確認**

Step 2 のコマンド実行中（KataGo が解析している最中）、右ペインに切り替えて:
```bash
ls katrain/core/
```
Expected: 左ペインの処理を止めずに右ペインが即応答すること。ペイン間で PTY が独立していることの確認。

- [ ] **Step 4: 両ペインの出力が混ざらないことを確認**

左ペインに戻り Step 2 の出力が正常に完了していること。右ペインの `ls` 出力は左ペインに漏れていないこと。

---

## Task 6: タブ並行動作を確認（ユースケース A）

**Files:** なし

- [ ] **Step 1: 新規タブを追加**

ccmux のキーバインド（README 参照、Ctrl+T 系の想定）で新規タブを作成。

- [ ] **Step 2: 新タブで別ディレクトリに移動**

新タブのペインで:
```bash
cd C:/Users/iwaki/Documents  # 任意の別プロジェクトのパスでも可
pwd
```
Expected: 移動先のディレクトリが pwd で表示される。

- [ ] **Step 3: ファイルツリーが追従することを確認**

サイドバーのファイルツリーが Step 2 で `cd` したディレクトリのツリーに切り替わっていること（ccmux のディレクトリ自動追跡機能の検証）。

- [ ] **Step 4: タブ切替で元の KaTrain タブに戻る**

キーバインドで最初のタブに戻ると、ファイルツリーが KaTrain のディレクトリ表示に戻ること。

---

## Task 7: ファイルプレビュー機能を確認（ユースケース D）

**Files:** なし

- [ ] **Step 1: ファイルツリーで Python ファイルを選択**

サイドバーで `katrain/core/ai.py` を選択／展開。
Expected: ファイル内容が構文ハイライト付きでプレビュー表示される（ccmux の syntect 連携）。

- [ ] **Step 2: 別言語ファイルも確認**

サイドバーで `docs/superpowers/specs/2026-04-19-ccmux-introduction-design.md` を選択。
Expected: Markdown として構文ハイライトされる。

---

## Task 8: ccmux 終了・再起動フローを確認

**Files:** なし

- [ ] **Step 1: ccmux を終了**

README 記載の終了キーバインド（Ctrl+Q 等）で ccmux を終了。
Expected: ccmux が終了し Windows Terminal の通常シェルに戻るか、タブ自体が閉じる。

- [ ] **Step 2: プロファイルから再起動**

再び Windows Terminal ドロップダウンから「ccmux (KaTrain)」を選択。
Expected: Task 4 Step 1 と同じ起動状態が再現される（再起動耐性の確認）。

---

## Task 9: 導入完了メモを spec に追記

**Files:**
- Modify: `docs/superpowers/specs/2026-04-19-ccmux-introduction-design.md` （末尾に付録を追加）

- [ ] **Step 1: 付録セクションを追記**

spec ファイル末尾に以下を追加:

```markdown

## 付録: 実導入時の記録（2026-04-19）

- 導入バージョン: ccmux-cli@0.5.4
- インストール実パス: {Task 2 Step 3 で `where ccmux` の出力を記録}
- Windows Terminal プロファイル GUID: {Task 3 Step 2 で生成した GUID}
- `commandline` 最終値: `ccmux.cmd`（または絶対パスにフォールバックした場合はそのパス）
- 起動確認時のバッチテスト結果: `python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt` が左ペインで正常完了 / 右ペインで並行操作可能
```

具体値は Task 2-4 で記録した実測値で埋める。

- [ ] **Step 2: コミット**

```bash
cd C:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1
git add docs/superpowers/specs/2026-04-19-ccmux-introduction-design.md
git commit -m "docs(ccmux): 導入完了記録を spec 付録に追記"
```

---

## 失敗時のロールバック手順

いずれかのタスクで復旧不能な問題が発生した場合:

- [ ] **Rollback 1: npm パッケージを削除**

```bash
npm uninstall -g ccmux-cli
where ccmux  # 何も表示されないことを確認
```

- [ ] **Rollback 2: Windows Terminal プロファイルを削除**

settings.json から「ccmux (KaTrain)」のオブジェクトを削除、保存。

- [ ] **Rollback 3: 残存ファイルを手動削除**

`%APPDATA%\ccmux\` が生成されていれば（設定ファイル置き場の想定）手動で削除。

---

## スコープ外（本プランでは行わない）

- KaTrain 側コード・設定ファイルの変更
- WSL / Git Bash からの ccmux 起動検証
- VS Code 統合ターミナル内での ccmux 動作保証
- Rust ソースからのビルド
- ccmux 設定ファイルのカスタマイズ（初期状態で運用）
