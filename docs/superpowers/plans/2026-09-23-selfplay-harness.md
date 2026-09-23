# 自己対局ハーネス katrain_debug.selfplay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 戦略を人間を模した humanSL ボットと無人で N 局打たせ、本物の終局レポート（`game_report`）で両者の一致率・勝敗・最終目差を集計する自己対局ハーネス `python -m katrain_debug.selfplay`（run / calibrate / summarize / report-sgf）を作り、相手ボットを実戦の相手に校正する。

**Architecture:** 1プロセス・1エンジン（`KaTrainStub` + `KataGoEngine`）で、毎局本物の `Game` を作り、AI の手番は `generate_ai_move` を行ごとに写した `_ai_turn`（AST テストで一致を固定）、相手の手番は humanSL 1visit のサンプラー `HumanSLOpponent` で打つ。終局後に全ノードの解析完了を待って本物の `game_report` を WATCH（末尾のパスを除く木）と STRICT（全体）× 7区間で呼び、1局1行（games.jsonl）・1手1行（moves.jsonl）・KT 解析つき SGF に書く。数値の判断（日程・投了・WATCH 木・要約・統計）は KataGo 非依存の純関数（`selfplay_stats.py`）に切り出して TDD で固定する。

**Tech Stack:** Python 3.12 / pytest（偽エンジン＋本物の `Game`・`game_report`。KataGo 不要）/ 標準ライブラリだけ（統計は `statistics`・`random`・`math` で自前実装。scipy は入っていない）/ 実エンジンのスモークは KataGo v1.18.2 CUDA + b10c384 + humanSL（ユーザーのローカル設定）

**Spec:** `docs/superpowers/specs/2026-09-23-selfplay-harness-design.md`（実装者は spec も読むこと。コードの事実は同 spec の行番号どおり）

## Global Constraints

- 一致率は **KaTrain の終局レポートと完全に同じ数字**＝本物の `game_report(game, thresholds, depth_filter=f)`（ai.py:345-407）を呼ぶだけで再実装しない。一致＝`parent.analysis_complete` かつ `parent.candidate_moves[0]["move"] == move.gtp()`、分母は `points_lost` が None でない手、パスも数える、相手は切り揃えない。
- 木は2通り: **WATCH（主指標）**＝末尾のパスを除いた木（`watch_prune` が `game._lock` の下で最後の石のノードの children を外し、`game.current_node` を属性の直接代入で付け替え、finally で両方戻す。`set_current_node` は使わない）、**STRICT**＝全体。
- 区間: GUI の None / (0, 0.14) / (0.14, 0.4) / (0.4, 10)、校正用の (0, 24/169) / (24/169, 85/169) / (85/169, 10)（13路で手数 <24 / 24〜84 / >=85。9・19路は盤面積で比例＝同じ割合をそのまま渡す）。
- 戦略は GUI と同じ経路: 本物の `Game(stub, engine, game_properties={"SZ", "KM", "RU"})`（`DebugGame` は使わない）・`Game.play` の通常解析・`generate_ai_move`（ai.py:11678-11704）の行ごとの写し `_ai_turn`。AI の手番の前に経路上の全ノードの解析完了を待つ。両プレイヤーは stub 上 PLAYER_HUMAN のまま（難解系の ponder は発火しない）。`game.board_watch_active` は既定 False（`--watch-flags` で True）。
- 相手ボット（spec §3）: 毎手 humanSL を 1visit で1本（`visits=1, include_policy=True, ownership=False, extra_settings={"humanSLProfile": profile, "ignorePreRootHistory": False}`）、局ごとの seed の `random.Random` で hp^(1/τ) に比例して引く。非合法手は捨てて引き直す。パスが出たら現局面の通常解析の完了を待ち、候補のパスの `pointsLost` を pass_loss として `_area_scoring_should_pass(moves, pass_loss)` に渡し、真ならパス・偽か pass_loss が None ならパスを外して引き直す。`--opp-max-loss`（既定 OFF）は通常解析で `pointsLost <= max_loss` の手だけ残す。
- 終局: 相手の投了（開始手数 13路 40・9路 19・19路 85 以降に、AI 視点で lead >= R かつ AI 勝率 >= 0.95 が AI の2手番続く）、2連続パス、手数上限（9路 120・13路 250・19路 400。上限では最終 scoreLead で勝敗）、AI と相手の例外・エンジン停止・待ちのタイムアウト（aborted。エンジンは次の局の前に再起動して続行＝落ちた局だけが aborted）。AI は投了しない。R は実戦 13路の投了局（手数 >= 40）の最終リードから局ごとに復元抽出（`--resign-lead lo:hi` で一様、`--no-resign` で投了なし＝必須の感度アーム）。
- seed: 局 i の seed = `seed-base + i` で AI の色（交互）・相手の段位（2局ごとに巡回＝色と交絡しない層別。seed の数が 2 × 段位数 の倍数でなければ層の局数が揃わないので CLI が警告する）・相手の乱数列・投了閾値・戦略側の Python 乱数（ai.py はグローバル `random` を使う＝`random.seed(strategy_seed)`）を固定。KataGo の探索は非決定的＝seed は開始条件の対で再現ではない。
- A/B: 同じ seed で全アームを打ち、10 seed ごとのブロックでアームの順を反転（ABBA）。対の差は t 区間・Wilcoxon・局単位 bootstrap（既定 1万回）。停止規則は ±3pt（2回見る＝各回 α = 0.025 → 既定の区間は 97.5%。延長は `--seed-base` をずらした2本目の `run` を `summarize DIR1 DIR2 --compare A B` で合わせる）。複数アームの `run` はアーム間の差（先頭のアーム基準）も要約に出す。**null ガード**: 解決済み設定（ユーザー config の節 + 上書き）が同一のアームがあれば開始前に中止。上書きキーの綴り間違い（ユーザー config の節にも戦略の `SETTING_DEFAULTS` にも無いキー）も中止。
- 目標 T（`own_le_target_plus5` = own <= T + 0.05）: 13/19路 0.30・9路 0.40。`own_lt_floor` = own < 0.15。
- 校正目標（13路の実戦・事後 2500v）: 相手 局平均 23.1%（局間 SD 6.5pt）・損失 1.77目/手・>=2目 28%・>=5目 10%・区間 26.7% / 0.56目・18.2% / 2.43目・29.1% / 0.96目・AI 側 53.3%・手数中央値 78.5。
- 出力は `experiments/selfplay/<YYYYMMDD_HHMM>_<label>/`（`.gitignore:7` の `experiments` で無視済み）。`summary.txt` は ASCII のみ（cp932 対策）。1局ごとに games.jsonl / moves.jsonl へ追記して flush＝`--resume` 可（`--retry-aborted` で aborted の局も打ち直す）。同じ分に同じ label の出力ディレクトリがあれば止まる（記録が混ざるのを防ぐ）。
- **実戦中の KaTrain と同時に走らせない**（spec §7）。CLI は起動中の `katago.exe` を見つけたら止まる（`--allow-concurrent` で解除・非推奨）。既定 1 プロセス（並列はしない）。
- **既存の `.py` は触らない**（`katrain/core/ai.py`・`game.py`・`katrain_debug/cli.py`・`runner.py` 等はすべて無変更）。新規の `.py` は Write でよい（PostToolUse フックが black `--line-length 120` を掛けるが、下のコードは black 済みなので変わらない）。移設するスクリプトは `shutil` でコピーし、行単位の書き換えスクリプトで改行コード（CRLF/LF）を保ったまま直す（Edit/Write で触ると black が全体を再整形する）。CRLF の `.md`（`CLAUDE.md`・`INDEX.md`）は `crlf_patch.py` 経由で直す。
- ツールの本文に Unicode エスケープ（バックスラッシュ＋u＋16進4桁）を書かない（変換される）。非 ASCII は文字そのものを書く。パスはスラッシュ区切りで書く（Python は Windows でもそのまま受け付ける）。
- コミットメッセージは日本語の Conventional Commits。末尾は必ず `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- ユーザーの `C:/Users/iwaki/.katrain/config.json` は**読むだけ**（この計画で変更は不要）。変更が必要になったら作業を止めてメインセッションに戻す（サブエージェントは編集しない・KaTrain 停止中のみ）。GUI・i18n・`ai.py` は触らない。
- テスト: `pytest tests/test_selfplay_*.py -q`（KataGo 不要・約 2 秒）。KataGo と並走させない（時間閾値系の偽陽性）。全体は `pytest --ignore=tests/test_ai.py -q`（`tests/test_ai.py` は humanSL モデルが要る）。
- **シェル**: `Run:` 行と ```bash ブロックはすべて **Bash ツール（Git Bash）** で実行する（`tests/test_selfplay_*.py` の glob・`wc`・`tail`・`$(date ...)`・`> file 2>&1` は PowerShell では動かない）。KataGo の有無は `tasklist //FI "IMAGENAME eq katago.exe" //NH | grep -i katago.exe || echo "no katago"` で見る（Git Bash では `/FI` を `//FI` と書く）。数分を超える実行（Task 7 のスモーク・Task 10 の校正）は Bash ツールの `run_in_background: true` で出力をファイルへ落とし、`wc -l` / `tail` で進み具合を見る（前面の実行は 600000 ms で打ち切られる）。
- ユーザー config の `game/handicap` が 0 でないと `Harness` が止まる（`BaseGame` は `game_properties` を渡しても config の置石を置く＝game.py の `place_handicap_stones`）。config は読むだけなので直さず、ユーザーに伝える。

---

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `katrain_debug/selfplay_stats.py` | 純関数: 盤サイズ別の定数・日程（seed → 色・段位・投了閾値）と層の偏りの警告・ABBA・相手の1手の抽選・投了判定・勝敗・WATCH 木（`watch_prune`）・1手1行・1局の要約・アームの要約・統計（Wilson・bootstrap・t・Wilcoxon・停止規則）・null ガード・校正のプール選択 | Create（Task 2） |
| `katrain_debug/selfplay_opponent.py` | `GameAborted`・待ちループ `Waiter`（`check_alive` と再起動回数を毎回見る・humanSL クエリ）・相手ボット `HumanSLOpponent` | Create（Task 3） |
| `katrain_debug/selfplay_game.py` | エンジン起動・`EngineWatchdog`（`ensure_alive`）・`Arm`/`resolve_arm`・`_ai_turn`（`generate_ai_move` の写し）・`StrategyOpponent`・`compute_reports`（WATCH/STRICT × 7区間）・`Harness`・`play_game`・`report_sgf` | Create（Task 4a） |
| `katrain_debug/selfplay_run.py` | 実行計画 `make_plan`・`OutputDir`（run.json / games.jsonl / moves.jsonl / sgf / logs）・`execute_plan`（局の前のエンジン再起動・再開・aborted の打ち直し）・要約の出力（複数の実行を合わせる）・校正の集計と md | Create（Task 4b） |
| `katrain_debug/selfplay.py` | CLI（`python -m katrain_debug.selfplay run / calibrate / summarize / report-sgf`）・起動中の KataGo の検出 | Create（Task 5）、Modify（Task 6） |
| `katrain_debug/selfplay_hooks.py` | hp 監査 `HpAuditHook`・影判定 `ShadowHook` / `run_shadow` | Create（Task 6） |
| `tests/selfplay_fakes.py` | テスト用の偽エンジン `FakeEngine`・一時 config の `make_stub`・`new_game`（pytest は収集しない名前） | Create（Task 3） |
| `tests/test_selfplay_stats.py` | 純関数（47件） | Create（Task 2） |
| `tests/test_selfplay_opponent.py` | 待ちループと相手ボット（12件） | Create（Task 3） |
| `tests/test_selfplay_runner.py` | `_ai_turn` と `generate_ai_move` の一致・1局・投了・aborted（AI・相手・エンジン）・置石の拒否・`report_sgf`・watchdog（22件） | Create（Task 4a） |
| `tests/test_selfplay_run.py` | 出力ファイル・エンジン停止からの続行・再開と aborted の打ち直し・計画・要約・校正（10件） | Create（Task 4b） |
| `tests/test_selfplay_cli.py` | CLI 通し・複数の実行の要約・report-sgf が KT を再解析しないこと（10件） | Create（Task 5） |
| `tests/test_selfplay_hooks.py` | 影判定・hp 監査・CLI フラグ（8件） | Create（Task 6） |
| `docs/superpowers/specs/calibration-data/selfplay/` | 実戦 13路 18局の `recon/`・校正目標と試作と反実仮想のスクリプト・`README.md`・（Task 10 で）`opponent_pool_13.json` と結果 md | Create（Task 1・10） |
| `CLAUDE.md`（CRLF）/ `docs/superpowers/specs/INDEX.md`（CRLF）/ spec（LF） | 使い方・索引・状態 | Modify（Task 8・10、`crlf_patch.py` 経由） |

ファイルの分け方: spec §2 は `selfplay.py` と `selfplay_stats.py` の2本を挙げているが、1本だと約 1000 行になるので責務ごとに分ける（相手ボット・1局・実行計画と出力・計器・CLI）。**各タスクは新しいファイルを作るだけ**で、前のタスクのファイルを書き換えるのは Task 6 の `selfplay.py`（CLI フラグの追加・Edit 5か所）だけ。

タスクの順: 0 → 1 → 2 → 3 → 4a → 4b → 5 → 6 → 7 → 8 → 9 → 10 → 11（13 タスク）。Task 10（校正・約2時間）は Task 9 の最終検証の後に**同じブランチ**で行い、ブランチの扱い（Task 11）はその後に決める。

パッチ用ヘルパー（**リポジトリには入れない**。スクラッチパッドに置く）:

`<scratchpad>/crlf_patch.py`

```python
"""CRLF を保ったままテキスト置換する（katrain の既存 .py は CRLF・black 未整形）。"""

import sys


def patch(path, edits):
    """edits: [(old, new, expected_count)]。old/new は LF で書く。件数が合わなければ何も書かずに止まる。"""
    raw = open(path, "rb").read()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    for old, new, count in edits:
        found = text.count(old)
        if found != count:
            sys.exit(f"{path}: expected {count} occurrence(s), found {found}: {old[:70]!r}")
        text = text.replace(old, new)
    if crlf:
        text = text.replace("\n", "\r\n")
    open(path, "wb").write(text.encode("utf-8"))
    print(f"patched {path} ({'CRLF' if crlf else 'LF'}, {len(edits)} edit(s))")
```

`<scratchpad>` = このセッションのスクラッチパッド（システムプロンプトの「Scratchpad directory」）。各タスクのスクリプトは同じディレクトリに Write し、**リポジトリのルートを cwd にして** `python <scratchpad>/<script>.py` で実行する。コマンドはすべてリポジトリのルート（`C:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1`）で実行する。

---

### Task 0: 範囲の確認・ブランチ・計画のコミット

**Files:**
- Create: `<scratchpad>/crlf_patch.py`（上記）
- Commit: `docs/superpowers/plans/2026-09-23-selfplay-harness.md`（spec は `3f4c4a00` でコミット済み）

**Interfaces:**
- Consumes: なし
- Produces: `crlf_patch.patch(path, edits)`（Task 8・10 が使う）

- [ ] **Step 0: 範囲をユーザーに確かめる**

計画の末尾「この計画の範囲外」の3つ（**9路の校正**・**spec §6 の実験の組み合わせ（約11時間）**・**並列実行**）を spec から外して後に回すことを、ユーザーに1回で確認する（19路のスモークは Task 7 Step 5b に入れてある）。9路の校正を今回やるよう言われたら、`recon_logs.py` の盤サイズ対応と `CALIB_TARGETS_9` の作成が要るので、ここで止めてメインセッションに戻す（この計画には手順が無い）。

- [ ] **Step 1: 作業ツリーがきれいなことを確かめてブランチを切る**

```bash
git status --short
git checkout -b feature/selfplay-harness
```
Expected: `git status --short` は計画ファイル2本の `??` 行だけ（`?? docs/superpowers/plans/2026-09-23-selfplay-harness.md` と、別の計画 `?? docs/superpowers/plans/2026-09-23-veil-strategy.md`）。`M` の行や他の `??` があれば止めてユーザーに確認する。ブランチ作成は `Switched to a new branch 'feature/selfplay-harness'`。韜晦の計画はこの計画では**コミットしない**（add するのは Step 3 のファイルだけ）。

- [ ] **Step 2: `crlf_patch.py` をスクラッチパッドに Write**（内容は File Structure 節のとおり）

- [ ] **Step 3: 計画をコミット**

```bash
git add docs/superpowers/plans/2026-09-23-selfplay-harness.md
git commit -m "docs(selfplay): 自己対局ハーネスの実装計画

spec 2026-09-23-selfplay-harness-design.md を 13 タスク（Task 0〜11。Task 4 は
4a / 4b）に分解。純関数の TDD、generate_ai_move の写しの AST 固定、偽エンジンでの
通し、実エンジンのスモーク（13路・19路）、相手ボットの校正（約2時間）まで。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 1: 校正データとスクリプトの移設（spec §10）

校正の目標データと設計時のスクリプトはリポジトリ外の一時フォルダにしかない（消える）。最初に移す。

**Files:**
- Create: `<scratchpad>/migrate_selfplay_data.py`（リポジトリには入れない）
- Create: `docs/superpowers/specs/calibration-data/selfplay/`（`recon/` 38 ファイル・スクリプト 13 本・`README.md`）

**Interfaces:**
- Consumes: 移設元 2 か所（spec §10）:
  - `C:/Users/iwaki/AppData/Local/Temp/claude/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/d4ae766f-520f-4142-b31e-a59d28c60c07/scratchpad/` の `recon/`・`offline_report.py`・`recon_logs.py`・`join_turns.py`・`inventory2.py`
  - `C:/Users/iwaki/AppData/Local/Temp/claude/C--Users-iwaki--katrain/819b933e-8892-42ff-9c0a-7d2186f48b8c/scratchpad/design/` の `calib_targets.py`・`proto_selfplay.py`・`bench_pipeline.py`・`bench_size.py`・`cf_absolute.py`・`cf_absolute2.py`・`cf_veil.py`・`veil_cf.py`・`judge/unified_cf.py`
- Produces: `docs/superpowers/specs/calibration-data/selfplay/recon/report_game_*.json`（Task 5 の `resign_plan` → `selfplay_run.load_resign_pool` が投了閾値の標本として読む。`summary` の `ai`・`n_moves`・`final_score` を使う）

- [ ] **Step 1: 移設元が揃っているか確かめる**

```bash
ls "C:/Users/iwaki/AppData/Local/Temp/claude/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/d4ae766f-520f-4142-b31e-a59d28c60c07/scratchpad/recon" | wc -l
ls "C:/Users/iwaki/AppData/Local/Temp/claude/C--Users-iwaki--katrain/819b933e-8892-42ff-9c0a-7d2186f48b8c/scratchpad/design/judge/unified_cf.py"
```
Expected: `38` と、`unified_cf.py` のパスがそのまま表示される。どちらかが無ければ**ここで止めてユーザーに報告**（一時フォルダが掃除された＝データを失っている）。

- [ ] **Step 2: 移設スクリプトを `<scratchpad>/migrate_selfplay_data.py` に Write**

直書きのパスは「行頭一致」で行ごと差し替える（元の行に含まれる Windows のバックスラッシュを書かずに済む）。`HERE/recon` を使う `recon_logs.py`・`join_turns.py`・`inventory2.py` は移すだけで相対になる。改行コードは元のまま（`proto_selfplay.py`・`veil_cf.py` は CRLF）。

```python
"""spec §10: 校正の目標データとスクリプトを一時フォルダからリポジトリへ移し、直書きのパスをリポジトリ内の相対に直す。

使い方（リポジトリのルートで）: python <scratchpad>/migrate_selfplay_data.py .
移設先: docs/superpowers/specs/calibration-data/selfplay/。元の一時フォルダは消さない（読むだけ）。
"""

import os
import shutil
import sys

TEMP = "C:/Users/iwaki/AppData/Local/Temp/claude"
SRC_RECON = (
    TEMP + "/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/d4ae766f-520f-4142-b31e-a59d28c60c07/scratchpad"
)
SRC_DESIGN = TEMP + "/C--Users-iwaki--katrain/819b933e-8892-42ff-9c0a-7d2186f48b8c/scratchpad/design"
FILES = [
    (SRC_RECON, "offline_report.py"),
    (SRC_RECON, "recon_logs.py"),
    (SRC_RECON, "join_turns.py"),
    (SRC_RECON, "inventory2.py"),
    (SRC_DESIGN, "calib_targets.py"),
    (SRC_DESIGN, "proto_selfplay.py"),
    (SRC_DESIGN, "bench_pipeline.py"),
    (SRC_DESIGN, "bench_size.py"),
    (SRC_DESIGN, "cf_absolute.py"),
    (SRC_DESIGN, "cf_absolute2.py"),
    (SRC_DESIGN, "cf_veil.py"),
    (SRC_DESIGN, "veil_cf.py"),
    (SRC_DESIGN, "judge/unified_cf.py"),
]
HERE_DIR = "os.path.dirname(os.path.abspath(__file__))"
REPO_LINE = f'REPO = os.path.abspath(os.path.join({HERE_DIR}, "..", "..", "..", "..", ".."))  # リポジトリのルート'
# (ファイル, 行頭, 置き換える行（None なら行を消す）, 期待件数)。行頭一致なのでバックスラッシュを含む元の行も書かずに済む
LINE_RULES = [
    ("offline_report.py", 'REPO = r"C:', REPO_LINE, 1),
    ("proto_selfplay.py", 'REPO = r"C:', REPO_LINE, 1),
    ("bench_pipeline.py", 'REPO = r"C:', REPO_LINE, 1),
    ("bench_size.py", 'REPO = r"C:', REPO_LINE, 1),
    (
        "calib_targets.py",
        "D = sys.argv[1]",
        f'D = sys.argv[1] if len(sys.argv) > 1 else os.path.join({HERE_DIR}, "recon")',
        1,
    ),
    ("cf_absolute.py", 'R = r"C:/Users/iwaki/AppData', f'R = os.path.join({HERE_DIR}, "recon")', 1),
    ("judge/unified_cf.py", 'R = r"C:/Users/iwaki/AppData', f'R = os.path.join({HERE_DIR}, "..", "recon")', 1),
    ("cf_veil.py", 'RECON = r"C:/Users/iwaki/AppData', f'RECON = os.path.join({HERE_DIR}, "recon")', 1),
    ("veil_cf.py", "import math", "import math\nimport os", 1),
    ("veil_cf.py", 'RECON = ("C:/Users/iwaki/AppData', f'RECON = os.path.join({HERE_DIR}, "recon") + os.sep', 1),
    ("veil_cf.py", '         "d4ae766f-520f-4142-b31e-a59d28c60c07/scratchpad/recon/")', None, 1),
    ("cf_absolute2.py", "import sys", "import os\nimport sys", 1),
    (
        "cf_absolute2.py",
        'exec(open("cf_absolute.py", encoding="utf-8")',
        f'exec(open(os.path.join({HERE_DIR}, "cf_absolute.py"), encoding="utf-8").read().split("print(list(GAMES")[0])',
        1,
    ),
]


def rewrite_lines(path, rules):
    raw = open(path, "rb").read()
    crlf = b"\r\n" in raw
    lines = raw.decode("utf-8").replace("\r\n", "\n").split("\n")
    for prefix, new, count in rules:
        hits = [i for i, line in enumerate(lines) if line.startswith(prefix)]
        if len(hits) != count:
            sys.exit(f"{path}: expected {count} line(s) starting with {prefix!r}, found {len(hits)}")
        for i in reversed(hits):
            if new is None:
                del lines[i]
            else:
                lines[i : i + 1] = new.split("\n")
    text = "\n".join(lines)
    if crlf:
        text = text.replace("\n", "\r\n")
    open(path, "wb").write(text.encode("utf-8"))
    print(f"rewrote {path} ({'CRLF' if crlf else 'LF'}, {len(rules)} rule(s))")


def main(repo):
    dest = os.path.join(repo, "docs", "superpowers", "specs", "calibration-data", "selfplay")
    if os.path.exists(os.path.join(dest, "recon")):
        sys.exit(f"{dest}/recon already exists (already migrated?)")
    os.makedirs(os.path.join(dest, "judge"), exist_ok=True)
    shutil.copytree(os.path.join(SRC_RECON, "recon"), os.path.join(dest, "recon"))
    for src_dir, rel in FILES:
        shutil.copy2(os.path.join(src_dir, rel), os.path.join(dest, rel))
    by_file = {}
    for rel, prefix, new, count in LINE_RULES:
        by_file.setdefault(rel, []).append((prefix, new, count))
    for rel, rules in by_file.items():
        rewrite_lines(os.path.join(dest, rel), rules)
    print(f"migrated {len(FILES)} scripts + recon/ ({len(os.listdir(os.path.join(dest, 'recon')))} files) to {dest}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
```

- [ ] **Step 3: 実行する**

Run: `python <scratchpad>/migrate_selfplay_data.py .`
Expected（最後の行）: `migrated 13 scripts + recon/ (38 files) to ` で始まり、移設先のパス（`docs`・`superpowers`・`specs`・`calibration-data`・`selfplay`）で終わる。その前に `rewrote ...` が 10 行（`proto_selfplay.py` と `veil_cf.py` は `(CRLF, ...)`、他は `(LF, ...)`）。

- [ ] **Step 4: 直書きのパスが残っていないこと・スクリプトが新しい場所で動くことを確かめる**

```bash
python -c "import glob; print([p for p in glob.glob('docs/superpowers/specs/calibration-data/selfplay/**/*.py', recursive=True) if 'AppData' in open(p, encoding='utf-8').read() or ('r' + chr(34) + 'C:') in open(p, encoding='utf-8').read()])"
python docs/superpowers/specs/calibration-data/selfplay/calib_targets.py | grep -E "^opp all|median"
for f in cf_absolute.py cf_absolute2.py cf_veil.py veil_cf.py judge/unified_cf.py; do (cd "<scratchpad>" && python "C:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1/docs/superpowers/specs/calibration-data/selfplay/$f" > /dev/null; echo "$f exit $?"); done
```
Expected:
- 1行目 `[]`
- `lengths [31, 45, ..., 128] median 78.5` と `opp all                n= 715 match=0.218 loss=1.74 med=0.58 >=2:0.28 >=5:0.10 top_prior>=.8:0.08`（spec §3 の 18局の値）
- 5本とも `exit 0`（別ディレクトリから呼んでも `recon/` を相対で見つける）

- [ ] **Step 5: `README.md` を Write**（`docs/superpowers/specs/calibration-data/selfplay/README.md`・LF）

```markdown
# 自己対局ハーネスの校正データ（`calibration-data/selfplay/`）

spec `2026-09-23-selfplay-harness-design.md`（§3 校正・§10 移設）。設計セッションの一時フォルダから移設した
（元は `%TEMP%/claude/.../scratchpad/`）。スクリプトはこのディレクトリの `recon/` を相対パスで読む。
ハーネス本体は `python -m katrain_debug.selfplay`（`katrain_debug/selfplay*.py`）。

| ファイル | 中身 |
|---|---|
| `recon/game_*.sgf` | 実戦 13路 18局（2026-09-14〜18 の監視対局ログから復元。難解＋16局・擬態2局。AI の色は PB/PW） |
| `recon/report_game_*.json` / `report_all.json` | 18局の事後 2500v 再解析。1手1行（depth・player・move・top・match・ptloss・score・alt_min_loss・top_prior…） |
| `recon/summary.json` | ログ側の手番の分類（`recon_logs.py` の出力） |
| `recon_logs.py` | `~/.katrain/logs/game_*.log` → `recon/*.sgf` と `summary.json` |
| `offline_report.py` | `recon/*.sgf` を KataGo で事後解析して `recon/report_*.json` を書く（KataGo を起動する） |
| `calib_targets.py` | 校正目標（相手の一致率・損失・区間 <24 / 24〜84 / >=85 の形）を `recon/` から出す＝spec §3 の表 |
| `join_turns.py` / `inventory2.py` | ログ側の分類と事後解析の突き合わせ・擬態の資格の在庫（設計時の調査） |
| `proto_selfplay.py` | ハーネスの試作（本物の `generate_ai_move`・1visit humanSL の相手） |
| `bench_pipeline.py` / `bench_size.py` | 戦略なしの流れの所要時間（spec §7。KataGo を起動する） |
| `cf_absolute.py` / `cf_absolute2.py` / `cf_veil.py` / `veil_cf.py` / `judge/unified_cf.py` | 韜晦の反実仮想（KataGo 不要。韜晦 spec §2.4） |
| `opponent_pool_13.json` | 相手ボットの 3段位プール（`calibrate --write-pool` の出力。`run` の既定の相手） |
| `selfplay-calibration-results-*.md` | 校正の結果（段位ごとの表・プールの候補・ハーネスと実戦のずれ） |

確認: `python docs/superpowers/specs/calibration-data/selfplay/calib_targets.py` が
`opp all n= 715 match=0.218 loss=1.74`（相手 18局・全手まとめ）と `median 78.5`（手数）を出す。
```

- [ ] **Step 6: 無視されていないことを確かめてコミット**

```bash
git check-ignore -v docs/superpowers/specs/calibration-data/selfplay/recon/report_game_20260914_211800.json docs/superpowers/specs/calibration-data/selfplay/judge/unified_cf.py; echo "exit $?"
git add docs/superpowers/specs/calibration-data/selfplay
git diff --cached --stat | tail -1
```
Expected: `exit 1`（どちらも無視されていない）、`52 files changed, ...`（recon 38 + スクリプト 13 + README 1）。

```bash
git commit -m "chore(selfplay): 自己対局ハーネスの校正データとスクリプトを一時フォルダから移設

実戦 13路 18局の復元 SGF と事後 2500v レポート（recon/）、校正目標 calib_targets.py、
試作 proto_selfplay.py、計測 bench_*.py、韜晦の反実仮想を calibration-data/selfplay/ へ。
直書きの一時フォルダのパスはリポジトリ内の相対パスに書き換えた（spec §10）。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 純関数 `selfplay_stats.py`（TDD）

**Files:**
- Create: `katrain_debug/selfplay_stats.py`
- Test: `tests/test_selfplay_stats.py`

**Interfaces:**
- Consumes: なし（KataGo・Kivy・katrain 本体に依存しない。テストだけが本物の `GameNode`・`game_report`・`enigma9_hp_lookup` と突き合わせる）
- Produces（後続タスクが名前どおりに使う）:
  - 定数: `MOVE_CAP = {9: 120, 13: 250, 19: 400}`・`TARGET_RATE = {9: 0.40, 13: 0.30, 19: 0.30}`・`RATE_FLOOR = 0.15`・`TARGET_SLACK = 0.05`・`RESIGN_START_13 = 40`・`RESIGN_MIN_WINRATE = 0.95`・`RESIGN_STREAK = 2`・`VISITS_CHECK_RATIO = 0.9`・`BLUNDER_TAILS = (1.0, 2.0, 3.0, 6.0)`・`HP_AUDIT_LOW = 0.05`・`GUI_BINS` / `CALIB_BINS` / `REPORT_BINS`（`(名前, depth_filter | None)` のタプル。名前は `all`・`gui_opening`・`gui_middle`・`gui_endgame`・`cal_opening`・`cal_middle`・`cal_endgame`）・`CALIB_TARGETS_13`・`POOL_TOLERANCE`
  - `move_cap(size) -> int`・`resign_start_move(size) -> int`（13路 40 を盤面積で比例・9路 19・19路 85）・`depth_bin(depth, size, bins=CALIB_BINS) -> str | None`
  - `gtp_to_key(gtp) -> (x, y) | "pass"`・`key_to_gtp(key) -> str`・`hp_index(key, size) -> int`・`hp_to_cands(human_policy, size) -> [(key, p)]`・`hp_audit_values(human_policy, size, played_gtp, best_gtp) -> {"hp_played", "hp_best", "hp_rank"}`
  - `selfplay_schedule(n_seeds, ranks, seed_base=1000, resign_leads=None, resign_range=None, no_resign=False) -> [{"index", "seed", "ai_color", "rank", "opp_seed", "strategy_seed", "resign_lead"}]`・`schedule_balance_warning(schedule, ranks) -> str | None`（段位 × 色の層の局数が揃わないときの警告文。Task 5 の CLI が出す）・`abba_order(arm_names, n_seeds, block=10) -> [(arm, index)]`
  - `selfplay_opponent_pick(cands, rng, tau, try_move, pass_ok) -> (key, try_move の戻り値) | (None, None)`
  - `ai_view_lead(score_black, ai_color)`・`ai_view_winrate(wr_black, ai_color)`・`resign_pool_from_summaries(summaries, size) -> [float]`・`selfplay_should_resign(depth, lead_ai, wr_ai, streak, threshold, size) -> (bool, int)`・`selfplay_outcome(end_reason, final_lead_ai) -> "win" | "loss" | "jigo" | "aborted" | "unknown"`
  - `main_line_end(node)`・`watch_prune(game)`（コンテキストマネージャ・最後の石のノードを yield）・`report_block(sum_stats, player_ptloss, bw) -> {"top1", "top5", "mean_ptloss", "n"}`
  - `selfplay_move_rows(nodes, ai_color, size, max_visits=None) -> [row]`（row のキー: `depth, player, is_ai, move, best, match, points_lost, loss, lead_before_ai, lead_after_ai, wr_before_ai, wr_after_ai, parent_visits, visits_low, best_prior, bin, trailing_pass, run_own_rate, run_opp_rate`）・`merge_turns(rows, turns) -> rows`・`flat_row(row) -> dict`
  - `selfplay_game_summary(meta, reports, rows, target, reserve=None, ledger=None, wall_s=None) -> record`（games.jsonl の1行。`meta` のキーに加えて `result, n_moves, final_lead, lead_min, lead_max, ai_wr_min, reports, own_top1, opp_top1, own_top5, opp_top5, own_n, opp_n, own_mean_ptloss, opp_mean_ptloss, own_minus_opp, own_lt_opp, own_le_target_plus5, own_lt_floor, ai_tail{ge1,ge2,ge3,ge6}, opp_tail{n,ge2,ge5}, flip_moves, hp_dev_list, hp_dev_median, hp_dev_lt5, intent_report_mismatch, veil, shadow, strategy_times, strategy_p50, strategy_p95, strategy_max, wait_s, wall_s, visits_low`）
  - `percentile(values, q)`・`wilson(k, n, z=1.96)`・`cluster_bootstrap(clusters, stat, n_boot=10000, seed=0, conf=0.95)`・`t_cdf(t, df)`・`t_ppf(p, df)`・`t_interval(values, conf=0.95)`・`wilcoxon_signed_rank(diffs)`・`selfplay_stop_rule(lo, hi, margin=0.03) -> "extend" | "within" | "higher" | "lower" | "insufficient"`
  - `metric_value(rec, metric)`・`selfplay_arm_summary(records, n_boot=10000, seed=0) -> dict`・`selfplay_summarize(records, n_boot=10000, seed=0) -> {"arms", "strata"}`（strata のキーは `"<arm>|<rank>|<color>"`）・`selfplay_paired_diff(recs_a, recs_b, metric, n_boot=10000, seed=0, conf=0.975, margin=0.03) -> {"metric", "n", "mean", "t_ci", "wilcoxon_p", "boot_ci", "conf", "verdict"}`
  - `settings_fingerprint(mode, settings) -> str`（16桁）・`arms_null_guard(arms) -> [(name, name)]`（arms は `{"name", "mode", "settings"}` を持つ dict）・`unknown_override_keys(overrides, user_section, known_keys) -> [str]`・`parse_arm(text) -> (name, strategy, [items])`・`parse_range(text) -> (lo, hi)`
  - `calibration_rank_stats(records) -> {rank: {"games", "opp_mean", "opp_sd", "opp_pooled", "opp_loss", "opp_ge2", "opp_ge5", "own_mean", "moves_median", "bins"}}`・`selfplay_pool_choice(rank_stats, targets=CALIB_TARGETS_13, k=3, tolerance=POOL_TOLERANCE) -> [{"ranks", "opp_mean", "opp_sd", "opp_loss", "own_mean", "bins", "score"}]`（score 昇順）
  - 韜晦の判定情報（`last_decision_info`）から読むキー（韜晦の計画 `plans/2026-09-23-veil-strategy.md` の「共有インターフェース」。spec §4 S20 の一覧は `ΔE` と書き `close` を持たないので、キー名は計画の側に合わせる）: `tier`・`kind`（`free` / `paid` / `trap` ほか）・`best`・`chosen`・`vloss`・`lead`・`E`・`close`（無ければ `lead < reserve`）と ledger。ledger は `(depth, best_gtp, played, kind)` の列で、depth は着手前の局面（`cn.depth`）＝着手ノードは depth + 1。
  - games.jsonl の `veil`（韜晦のアームだけ）: `tiers, kinds, paid_vloss_sum, vloss_by_kind, report_loss_by_kind, curse_by_kind, nonfree_below_reserve, close_free_vloss, trap_next_loss_over_E, ledger_mismatch`（`curse_by_kind` = 外しの種類ごとの「レポートの損失 − 判定時の vloss」＝spec §6 の勝者の呪いの検出）。`shadow`: `arm, n, dev_rate, same_as_played, vloss_mean, played_loss_mean, secs_p95`（`vloss_mean` は影の B の手の pointsLost の平均・`played_loss_mean` は同じ手番で A が打った手の損失の平均＝spec §6 の「同じ局面での外し率とコスト」）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_selfplay_stats.py` を Write

```python
# tests/test_selfplay_stats.py
"""自己対局ハーネスの純関数（katrain_debug/selfplay_stats.py）。KataGo 不要。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md
"""

import random
import threading
import types

import pytest

from katrain.core.ai import enigma9_hp_lookup, game_report
from katrain.core.game_node import GameNode
from katrain.core.sgf_parser import Move
from katrain_debug import selfplay_stats as S

THRESHOLDS = [12, 6, 3, 1.5, 0.5, 0]


# ---- 盤サイズ・座標 ----
class TestBoardConstants:
    def test_move_cap_and_resign_start(self):
        assert [S.move_cap(n) for n in (9, 13, 19)] == [120, 250, 400]
        assert [S.resign_start_move(n) for n in (9, 13, 19)] == [19, 40, 85]

    def test_calibration_bins_match_game_report_boundaries(self):
        assert S.depth_bin(23, 13) == "cal_opening"
        assert S.depth_bin(24, 13) == "cal_middle"
        assert S.depth_bin(84, 13) == "cal_middle"
        assert S.depth_bin(85, 13) == "cal_endgame"
        assert S.depth_bin(11, 9) == "cal_opening" and S.depth_bin(12, 9) == "cal_middle"

    def test_gtp_keys_match_move(self):
        for gtp in ("A1", "D4", "N13", "T19", "J9"):
            assert S.gtp_to_key(gtp) == Move.from_gtp(gtp).coords
            assert S.key_to_gtp(S.gtp_to_key(gtp)) == gtp
        assert S.gtp_to_key("pass") == "pass" and S.key_to_gtp("pass") == "pass"

    def test_hp_index_matches_enigma9_hp_lookup(self):
        hp = [i / 1000 for i in range(13 * 13 + 1)]
        lookup = enigma9_hp_lookup(hp, (13, 13))
        for gtp in ("A1", "N13", "G7", "C11", "pass"):
            assert hp[S.hp_index(S.gtp_to_key(gtp), 13)] == lookup(gtp)

    def test_hp_to_cands_drops_illegal_and_zero_and_keeps_pass(self):
        hp = [0.0] * 82
        hp[S.hp_index((2, 2), 9)] = 0.5
        hp[S.hp_index((4, 4), 9)] = -1.0
        hp[81] = 0.2
        assert S.hp_to_cands(hp, 9) == [((2, 2), 0.5), ("pass", 0.2)]

    def test_hp_audit_values(self):
        hp = [0.0] * 82
        hp[S.hp_index(S.gtp_to_key("C3"), 9)] = 0.6
        hp[S.hp_index(S.gtp_to_key("D4"), 9)] = 0.3
        hp[81] = 0.1
        assert S.hp_audit_values(hp, 9, "D4", "C3") == {"hp_played": 0.3, "hp_best": 0.6, "hp_rank": 2}
        assert S.hp_audit_values(hp, 9, "E5", "C3")["hp_rank"] == 4


# ---- 日程 ----
class TestSchedule:
    def test_same_seed_gives_same_conditions(self):
        a = S.selfplay_schedule(12, ["rank_3k", "rank_1d"], 1000, resign_leads=[3.9, 28.9, 52.5])
        b = S.selfplay_schedule(12, ["rank_3k", "rank_1d"], 1000, resign_leads=[3.9, 28.9, 52.5])
        assert a == b
        assert [s["seed"] for s in a] == list(range(1000, 1012))

    def test_colors_alternate_and_ranks_are_stratified_by_color(self):
        ranks = ["rank_8k", "rank_5k", "rank_3k", "rank_1k", "rank_1d", "rank_3d"]
        sched = S.selfplay_schedule(48, ranks, 7)
        assert [s["ai_color"] for s in sched[:4]] == ["B", "W", "B", "W"]
        for rank in ranks:
            games = [s for s in sched if s["rank"] == rank]
            assert len(games) == 8
            assert sum(s["ai_color"] == "B" for s in games) == 4

    def test_resign_threshold_sources(self):
        pool = [3.9, 28.9, 52.5]
        assert all(s["resign_lead"] in pool for s in S.selfplay_schedule(20, ["r"], 1, resign_leads=pool))
        assert all(8 <= s["resign_lead"] <= 40 for s in S.selfplay_schedule(20, ["r"], 1, resign_range=(8, 40)))
        assert all(
            s["resign_lead"] is None for s in S.selfplay_schedule(5, ["r"], 1, resign_leads=pool, no_resign=True)
        )

    def test_unbalanced_strata_are_warned(self):
        ranks = ["rank_3k", "rank_1k", "rank_1d"]
        warn = S.schedule_balance_warning(S.selfplay_schedule(20, ranks, 1), ranks)
        assert "8/6/6" in warn and "multiple of 6" in warn
        assert S.schedule_balance_warning(S.selfplay_schedule(12, ranks, 1), ranks) is None

    def test_empty_ranks_is_an_error(self):
        with pytest.raises(ValueError):
            S.selfplay_schedule(2, [], 1)

    def test_abba_order(self):
        order = S.abba_order(["A", "B"], 20)
        assert order[:10] == [("A", i) for i in range(10)]
        assert order[10:20] == [("B", i) for i in range(10)]
        assert order[20:30] == [("B", i) for i in range(10, 20)]
        assert order[30:] == [("A", i) for i in range(10, 20)]


# ---- 相手ボットの1手 ----
class TestOpponentPick:
    CANDS = [((0, 0), 0.5), ((1, 1), 0.3), ("pass", 0.2)]

    def test_same_rng_seed_gives_same_pick(self):
        picks = [
            S.selfplay_opponent_pick(self.CANDS, random.Random(5), 1.0, lambda k: k, lambda: True)[0] for _ in range(3)
        ]
        assert len(set(picks)) == 1

    def test_illegal_move_is_dropped_and_redrawn(self):
        tried = []

        def try_move(key):
            tried.append(key)
            return None if key == (0, 0) else "played"

        key, res = S.selfplay_opponent_pick([((0, 0), 0.99), ((1, 1), 0.01)], random.Random(0), 1.0, try_move, None)
        assert tried[0] == (0, 0) and key == (1, 1) and res == "played"

    def test_pass_redrawn_when_not_allowed_and_asked_once(self):
        asked = []

        def pass_ok():
            asked.append(1)
            return False

        for seed in range(20):
            asked.clear()
            key, _ = S.selfplay_opponent_pick(
                [("pass", 0.9), ((1, 1), 0.1)], random.Random(seed), 1.0, lambda k: k, pass_ok
            )
            assert key == (1, 1)
            assert len(asked) <= 1

    def test_pass_played_when_allowed(self):
        key, res = S.selfplay_opponent_pick([("pass", 1.0)], random.Random(0), 1.0, lambda k: "node", lambda: True)
        assert key == "pass" and res == "node"

    def test_exhausted_candidates(self):
        assert S.selfplay_opponent_pick([((0, 0), 1.0)], random.Random(0), 1.0, lambda k: None, None) == (None, None)

    def test_low_temperature_concentrates_on_the_top_move(self):
        cands = [((0, 0), 0.6), ((1, 1), 0.4)]
        rng = random.Random(1)
        picks = [S.selfplay_opponent_pick(cands, rng, 0.05, lambda k: k, None)[0] for _ in range(200)]
        assert picks.count((0, 0)) >= 199


# ---- 投了・勝敗 ----
class TestResignAndOutcome:
    def test_needs_two_consecutive_ai_turns_after_the_start_move(self):
        assert S.selfplay_should_resign(39, 20.0, 0.99, 1, 10.0, 13) == (False, 0)
        ok, streak = S.selfplay_should_resign(40, 20.0, 0.99, 0, 10.0, 13)
        assert (ok, streak) == (False, 1)
        assert S.selfplay_should_resign(42, 20.0, 0.99, streak, 10.0, 13) == (True, 2)

    def test_winrate_and_lead_conditions_reset_the_streak(self):
        assert S.selfplay_should_resign(50, 20.0, 0.90, 1, 10.0, 13) == (False, 0)
        assert S.selfplay_should_resign(50, 9.0, 0.99, 1, 10.0, 13) == (False, 0)

    def test_no_resign(self):
        assert S.selfplay_should_resign(100, 50.0, 1.0, 5, None, 13) == (False, 0)

    def test_outcome(self):
        assert S.selfplay_outcome("opp_resign", -3.0) == "win"
        assert S.selfplay_outcome("aborted", 10.0) == "aborted"
        assert S.selfplay_outcome("double_pass", 0.6) == "win"
        assert S.selfplay_outcome("move_cap", -0.8) == "loss"
        assert S.selfplay_outcome("double_pass", 0.2) == "jigo"
        assert S.selfplay_outcome("double_pass", None) == "unknown"

    def test_resign_pool_from_real_game_summaries(self):
        summaries = [
            {"ai": "W", "n_moves": 123, "final_score": -3.9},
            {"ai": "B", "n_moves": 59, "final_score": 28.9},
            {"ai": "W", "n_moves": 31, "final_score": -2.7},  # 開始手数 40 より前に終わった局は除く
        ]
        assert S.resign_pool_from_summaries(summaries, 13) == [3.9, 28.9]
        assert S.resign_pool_from_summaries(summaries, 9) == [round(3.9 * 81 / 169, 2), round(28.9 * 81 / 169, 2)]

    def test_ai_view(self):
        assert S.ai_view_lead(3.0, "W") == -3.0 and S.ai_view_winrate(0.8, "W") == pytest.approx(0.2)


# ---- WATCH 木と1手1行（本物の GameNode と game_report）----
def _analyze(node, lead, moves, complete=True, visits=500):
    """moves: [(gtp, 黒視点 scoreLead)]（order 順）。"""
    node.analysis["root"] = {"scoreLead": lead, "winrate": 0.5 + lead / 100, "visits": visits}
    node.analysis["moves"] = {
        g: {"move": g, "order": i, "scoreLead": s, "winrate": 0.5 + s / 100, "visits": 100, "prior": 0.2, "pv": [g]}
        for i, (g, s) in enumerate(moves)
    }
    node.analysis["completed"] = complete


def _game_with_trailing_passes():
    """B C3(一致) W G7(一致) B D4(外し・1.5目損) W pass(外し) B pass(一致) の 9路。"""
    root = GameNode(properties={"SZ": 9, "KM": 7.0, "RU": "chinese"})
    nodes = [root]
    for player, gtp in (("B", "C3"), ("W", "G7"), ("B", "D4"), ("W", "pass"), ("B", "pass")):
        nodes.append(nodes[-1].play(Move.from_gtp(gtp, player=player)))
    _analyze(nodes[0], 0.5, [("C3", 0.5), ("E5", 0.3)])
    _analyze(nodes[1], 0.5, [("G7", 0.5), ("C7", 0.8)])
    _analyze(nodes[2], 0.5, [("E5", 0.5), ("D4", -1.0)])
    _analyze(nodes[3], -1.0, [("F6", -1.0), ("pass", -0.5)])
    _analyze(nodes[4], -1.0, [("pass", -1.0), ("A1", -1.2)])
    _analyze(nodes[5], -1.0, [])
    game = types.SimpleNamespace(current_node=nodes[5], board_size=(9, 9), _lock=threading.RLock())
    return game, nodes


class TestWatchPrune:
    def test_watch_excludes_trailing_passes_even_when_current_node_is_the_last_pass(self):
        game, nodes = _game_with_trailing_passes()
        strict, _, strict_loss = game_report(game, THRESHOLDS)
        assert strict["B"]["ai_top_move"] == pytest.approx(2 / 3) and strict["W"]["ai_top_move"] == 0.5
        with S.watch_prune(game) as last:
            assert last is nodes[3] and game.current_node is nodes[3]
            watch, _, watch_loss = game_report(game, THRESHOLDS)
        assert watch["B"]["ai_top_move"] == 0.5 and watch["W"]["ai_top_move"] == 1.0
        assert len(watch_loss["B"]) == 2 and len(watch_loss["W"]) == 1
        assert nodes[3].children == [nodes[4]] and game.current_node is nodes[5]

    def test_restores_on_exception(self):
        game, nodes = _game_with_trailing_passes()
        with pytest.raises(RuntimeError):
            with S.watch_prune(game):
                raise RuntimeError("boom")
        assert nodes[3].children == [nodes[4]] and game.current_node is nodes[5]

    def test_report_block(self):
        game, _ = _game_with_trailing_passes()
        sum_stats, _, ptloss = game_report(game, THRESHOLDS)
        block = S.report_block(sum_stats, ptloss, "B")
        assert block["n"] == 3 and block["top1"] == pytest.approx(2 / 3) and block["mean_ptloss"] == pytest.approx(0.5)
        assert S.report_block({"B": {}, "W": {}}, {"B": [], "W": []}, "W") == {
            "top1": None,
            "top5": None,
            "mean_ptloss": None,
            "n": 0,
        }


class TestMoveRows:
    def test_rows_follow_the_report_definition(self):
        _, nodes = _game_with_trailing_passes()
        rows = S.selfplay_move_rows(nodes[1:], "B", 9, max_visits=600)
        assert [r["match"] for r in rows] == [True, True, False, False, True]
        assert rows[2]["points_lost"] == pytest.approx(1.5) and rows[2]["loss"] == pytest.approx(1.5)
        assert [r["trailing_pass"] for r in rows] == [False, False, False, True, True]
        assert rows[2]["run_own_rate"] == 0.5 and rows[4]["run_own_rate"] == pytest.approx(2 / 3)
        assert rows[1]["run_opp_rate"] == 1.0
        assert rows[0]["visits_low"] is True  # 500 < 0.9 * 600
        assert rows[2]["lead_before_ai"] == 0.5 and rows[2]["lead_after_ai"] == -1.0
        assert rows[0]["bin"] == "cal_opening"

    def test_flat_row(self):
        row = {"depth": 3, "decision": {"kind": "free", "vloss": 0.1}, "shadow": {"move": "D4"}}
        assert S.flat_row(row) == {"depth": 3, "decision_kind": "free", "decision_vloss": 0.1, "shadow_move": "D4"}
        assert S.flat_row({"depth": 1, "decision": None}) == {"depth": 1}

    def test_merge_turns_only_touches_ai_rows(self):
        rows = [{"depth": 1, "is_ai": True}, {"depth": 2, "is_ai": False}]
        S.merge_turns(rows, [{"depth": 1, "strategy_s": 0.5}, {"depth": 2, "strategy_s": 9.9}])
        assert rows[0]["strategy_s"] == 0.5 and "strategy_s" not in rows[1]


# ---- 1局の要約 ----
def _row(depth, is_ai, match, loss, **kw):
    base = {
        "depth": depth,
        "is_ai": is_ai,
        "match": match,
        "best": "C3",
        "move": "C3" if match else "D4",
        "points_lost": loss,
        "loss": None if loss is None else max(0.0, loss),
        "lead_after_ai": 5.0,
        "wr_before_ai": 0.8,
        "wr_after_ai": 0.8,
        "visits_low": False,
    }
    base.update(kw)
    return base


def _reports(own, opp, own_n=10, opp_n=10):
    block = {"ai": {"top1": own, "top5": 0.9, "mean_ptloss": 0.4, "n": own_n}}
    block["opp"] = {"top1": opp, "top5": 0.5, "mean_ptloss": 1.8, "n": opp_n}
    return {"WATCH": {"all": block}, "STRICT": {"all": block}}


META = {"arm": "A", "seed": 1000, "rank": "rank_3k", "ai_color": "B", "end_reason": "opp_resign"}


class TestGameSummary:
    def test_rates_flags_tails_and_flips(self):
        rows = [
            _row(1, True, True, 0.0),
            _row(2, False, False, 5.5),
            _row(3, True, False, 6.2, wr_before_ai=0.55, wr_after_ai=0.40),
            _row(4, False, True, 2.0),
            _row(5, True, False, 1.1),
        ]
        rec = S.selfplay_game_summary(META, _reports(0.32, 0.25), rows, target=0.30, wall_s=12.0)
        assert rec["result"] == "win" and rec["n_moves"] == 5
        assert rec["own_minus_opp"] == pytest.approx(0.07) and rec["own_lt_opp"] is False
        assert rec["own_le_target_plus5"] is True and rec["own_lt_floor"] is False
        assert rec["ai_tail"] == {"ge1": 2, "ge2": 1, "ge3": 1, "ge6": 1}
        assert rec["opp_tail"] == {"n": 2, "ge2": 2, "ge5": 1}
        assert rec["flip_moves"] == 1
        assert rec["veil"] is None and rec["shadow"] is None
        assert rec["wall_s"] == 12.0

    def test_hp_audit_and_intent_mismatch(self):
        rows = [
            _row(1, True, False, 0.3, hp_played=0.02, best_at_decision="C3", played="D4"),
            _row(3, True, False, 0.2, hp_played=0.30, best_at_decision="C3", played="D4"),
            _row(5, True, True, 0.0, hp_played=0.90, best_at_decision="E5", played="C3"),
        ]
        rec = S.selfplay_game_summary(META, _reports(0.33, 0.2), rows, target=0.30)
        assert rec["hp_dev_list"] == [0.02, 0.3] and rec["hp_dev_median"] == pytest.approx(0.16)
        assert rec["hp_dev_lt5"] == 0.5
        assert rec["intent_report_mismatch"] == 1  # 外したつもり（E5 ではなく C3）がレポートでは一致

    def test_decision_metrics_only_for_strategies_with_decision_info(self):
        rows = [
            _row(
                1,
                True,
                False,
                0.2,
                decision={"tier": "iii", "kind": "free", "best": "C3", "chosen": "D4", "vloss": 0.2, "lead": 2.0},
            ),
            _row(2, False, False, 3.0),
            _row(
                3,
                True,
                False,
                1.0,
                decision={"tier": "iii", "kind": "paid", "best": "C3", "chosen": "D4", "vloss": 1.0, "lead": 9.0},
            ),
            _row(
                5,
                True,
                False,
                0.5,
                decision={
                    "tier": "iii",
                    "kind": "trap",
                    "best": "C3",
                    "chosen": "D4",
                    "vloss": 0.5,
                    "lead": 8.0,
                    "E": 2.0,
                },
            ),
            _row(6, False, False, 3.0),
            _row(
                7,
                True,
                True,
                0.0,
                decision={"tier": "ii", "kind": "best", "best": "C3", "chosen": "C3", "vloss": 0.0, "lead": 4.0},
            ),
        ]
        ledger = [(0, "C3", "D4", "free"), (6, "C3", "E5", "free")]
        rec = S.selfplay_game_summary(META, _reports(0.25, 0.2), rows, target=0.30, reserve=5.0, ledger=ledger)
        veil = rec["veil"]
        assert veil["tiers"] == {"iii": 3, "ii": 1}
        assert veil["kinds"] == {"free": 1, "paid": 1, "trap": 1, "best": 1}
        assert veil["paid_vloss_sum"] == pytest.approx(1.7)
        assert veil["vloss_by_kind"]["paid"] == pytest.approx(1.0)
        assert veil["report_loss_by_kind"]["paid"] == pytest.approx(1.0)
        assert veil["curse_by_kind"]["trap"] == pytest.approx(0.0)
        assert veil["nonfree_below_reserve"] == 0
        assert veil["close_free_vloss"] == pytest.approx(0.2)  # lead 2.0 < reserve 5.0
        assert veil["trap_next_loss_over_E"] == pytest.approx(1.5)  # 次の相手手 3.0 / E 2.0
        assert veil["ledger_mismatch"] == 1  # depth 6 の外しが depth 7 でレポート一致

    def test_shadow_metrics(self):
        rows = [
            _row(1, True, True, 0.0, move="C3", shadow={"arm": "B", "move": "D4", "vloss": 0.8, "secs": 0.4}),
            _row(3, True, True, 0.0, move="C3", shadow={"arm": "B", "move": "C3", "vloss": 0.0, "secs": 0.6}),
        ]
        sh = S.selfplay_game_summary(META, _reports(1.0, 0.2), rows, target=0.30)["shadow"]
        assert sh["arm"] == "B" and sh["n"] == 2 and sh["dev_rate"] == 0.5 and sh["same_as_played"] == 0.5
        assert sh["vloss_mean"] == pytest.approx(0.4) and sh["played_loss_mean"] == 0.0


# ---- 統計 ----
class TestStatistics:
    def test_wilson(self):
        lo, hi = S.wilson(10, 10)
        assert lo == pytest.approx(0.72246, abs=1e-4) and hi == 1.0
        assert S.wilson(0, 0) == (None, None)

    def test_t_quantiles(self):
        assert S.t_ppf(0.975, 19) == pytest.approx(2.093024, abs=1e-5)
        assert S.t_ppf(0.975, 1) == pytest.approx(12.706205, abs=1e-4)
        assert S.t_ppf(0.9875, 19) == pytest.approx(2.433440, abs=1e-5)

    def test_wilcoxon_exact(self):
        assert S.wilcoxon_signed_rank([1, 2, 3, 4, 5]) == pytest.approx(0.0625)
        assert S.wilcoxon_signed_rank([1, -2, 3, 4, 5, 6, 7, 8]) == pytest.approx(6 / 256)
        assert S.wilcoxon_signed_rank([0, 0]) is None

    def test_bootstrap_is_deterministic_for_a_seed(self):
        vals = [0.1, 0.4, 0.2, 0.5, 0.3]
        a = S.cluster_bootstrap(vals, lambda s: sum(s) / len(s), 2000, seed=3)
        b = S.cluster_bootstrap(vals, lambda s: sum(s) / len(s), 2000, seed=3)
        assert a == b and a[0] < 0.3 < a[1]

    def test_stop_rule(self):
        assert S.selfplay_stop_rule(-0.05, 0.01) == "extend"
        assert S.selfplay_stop_rule(0.01, 0.05) == "extend"
        assert S.selfplay_stop_rule(-0.02, 0.02) == "within"
        assert S.selfplay_stop_rule(0.04, 0.09) == "higher"
        assert S.selfplay_stop_rule(-0.09, -0.04) == "lower"
        assert S.selfplay_stop_rule(None, None) == "insufficient"


def _rec(arm, seed, own, opp, result="win", **kw):
    base = {
        "arm": arm,
        "seed": seed,
        "rank": "rank_3k",
        "ai_color": "B" if seed % 2 == 0 else "W",
        "result": result,
        "own_top1": own,
        "opp_top1": opp,
        "own_n": 40,
        "opp_n": 40,
        "own_mean_ptloss": 0.5,
        "opp_mean_ptloss": 1.7,
        "own_minus_opp": None if own is None else own - opp,
        "own_lt_opp": None if own is None else own < opp,
        "own_le_target_plus5": None if own is None else own <= 0.35,
        "own_lt_floor": None if own is None else own < 0.15,
        "ai_tail": {"ge6": 0},
        "flip_moves": 0,
        "final_lead": 10.0,
        "n_moves": 80,
        "reports": {"WATCH": {"all": {"ai": {"top1": own, "n": 40}}}},
        "hp_dev_list": [0.1, 0.2],
        "strategy_times": [0.5, 1.0],
        "visits_low": 0,
    }
    base.update(kw)
    return base


class TestArmSummary:
    def test_counts_rates_and_fractions(self):
        recs = [
            _rec("A", 0, 0.30, 0.20),
            _rec("A", 1, 0.50, 0.25, own_n=20),
            _rec("A", 2, 0.10, 0.30, result="loss"),
            _rec("A", 3, None, None, result="aborted"),
        ]
        s = S.selfplay_arm_summary(recs, n_boot=500)
        assert (s["games"], s["aborted"], s["wins"], s["losses"]) == (4, 1, 2, 1)
        assert s["own_top1_mean"] == pytest.approx(0.30)
        assert s["own_top1_pooled"] == pytest.approx((0.30 * 40 + 0.50 * 20 + 0.10 * 40) / 100)
        assert s["p_own_lt_opp"] == pytest.approx(1 / 3)
        assert s["p_own_le_target_plus5"] == pytest.approx(2 / 3)
        assert s["p_own_lt_floor"] == pytest.approx(1 / 3)
        assert s["hp_dev_median"] == pytest.approx(0.15) and s["hp_dev_n"] == 6
        assert s["own_top1_by_bin"]["all"] is not None

    def test_summarize_groups_by_arm_and_stratum(self):
        recs = [_rec("A", 0, 0.3, 0.2), _rec("A", 1, 0.4, 0.2), _rec("B", 0, 0.5, 0.2)]
        out = S.selfplay_summarize(recs, n_boot=100)
        assert set(out["arms"]) == {"A", "B"}
        assert set(out["strata"]) == {"A|rank_3k|B", "A|rank_3k|W", "B|rank_3k|B"}

    def test_paired_diff_matches_seeds(self):
        a = [_rec("A", s, 0.30 + 0.01 * s + (0.02 if s % 2 else 0.0), 0.2) for s in range(10)]
        b = [_rec("B", s, 0.40 + 0.01 * s, 0.2) for s in range(1, 11)]
        d = S.selfplay_paired_diff(a, b, "own_top1", n_boot=500)
        assert d["n"] == 9 and d["mean"] == pytest.approx(-0.8 / 9)
        assert d["t_ci"][1] < -0.03 and d["verdict"] == "lower"
        d2 = S.selfplay_paired_diff(a, a, "win", n_boot=100)
        assert d2["n"] == 10 and d2["mean"] == 0.0


class TestArmsAndParsing:
    def test_null_guard_detects_identical_resolved_settings(self):
        arms = [
            {"name": "A", "mode": "ai:veil13", "settings": {"veil13_trap_mode": False}},
            {"name": "B", "mode": "ai:veil13", "settings": {"veil13_trap_mode": False}},
            {"name": "C", "mode": "ai:veil13", "settings": {"veil13_trap_mode": True}},
        ]
        assert S.arms_null_guard(arms) == [("A", "B")]
        assert S.settings_fingerprint("ai:x", {"a": 1, "b": 2}) == S.settings_fingerprint("ai:x", {"b": 2, "a": 1})

    def test_unknown_override_keys(self):
        assert S.unknown_override_keys({"veil13_reserv": 4}, {"veil13_reserve": 5}, {"veil13_trap_mode"}) == [
            "veil13_reserv"
        ]
        assert S.unknown_override_keys({"veil13_trap_mode": True}, {}, {"veil13_trap_mode"}) == []

    def test_parse_arm_and_range(self):
        assert S.parse_arm("A=veil13") == ("A", "veil13", [])
        assert S.parse_arm("B=veil13:veil13_trap_mode=true,veil13_reserve=4.0") == (
            "B",
            "veil13",
            ["veil13_trap_mode=true", "veil13_reserve=4.0"],
        )
        with pytest.raises(ValueError):
            S.parse_arm("veil13")
        assert S.parse_range("8:40") == (8.0, 40.0)
        with pytest.raises(ValueError):
            S.parse_range("40:8")


class TestCalibration:
    def _recs(self, rank, rates, loss=1.8):
        out = []
        for i, r in enumerate(rates):
            rec = _rec("calib", i, 0.5, r, rank=rank, opp_mean_ptloss=loss)
            rec["opp_tail"] = {"n": 40, "ge2": 10, "ge5": 4}
            rec["reports"]["WATCH"]["cal_middle"] = {"opp": {"top1": r, "mean_ptloss": 2.0, "n": 20}}
            out.append(rec)
        return out

    def test_rank_stats(self):
        st = S.calibration_rank_stats(self._recs("rank_3k", [0.2, 0.3]))["rank_3k"]
        assert st["games"] == 2 and st["opp_mean"] == pytest.approx(0.25) and st["opp_sd"] == pytest.approx(0.05)
        assert st["opp_ge2"] == 0.25 and st["opp_ge5"] == 0.1
        assert st["bins"]["cal_middle"]["opp_top1"] == pytest.approx(0.25)
        assert st["bins"]["cal_opening"]["opp_top1"] is None

    def test_pool_choice_prefers_the_combo_nearest_the_targets(self):
        recs = (
            self._recs("rank_8k", [0.10, 0.12], loss=3.0)
            + self._recs("rank_3k", [0.20, 0.26], loss=1.8)
            + self._recs("rank_1d", [0.22, 0.30], loss=1.6)
            + self._recs("rank_3d", [0.40, 0.44], loss=0.9)
        )
        choices = S.selfplay_pool_choice(S.calibration_rank_stats(recs))
        assert len(choices) == 4
        assert choices[0]["ranks"] == ["rank_8k", "rank_3k", "rank_1d"]
        assert choices[0]["opp_mean"] == pytest.approx(0.20) and choices[0]["opp_loss"] == pytest.approx(6.4 / 3)
        assert [c["score"] for c in choices] == sorted(c["score"] for c in choices)
        assert choices[0]["bins"]["cal_middle"]["opp_top1"] == pytest.approx((0.11 + 0.23 + 0.26) / 3)
        assert choices[0]["bins"]["cal_opening"]["opp_top1"] is None
```

- [ ] **Step 2: 失敗を確かめる**

Run: `pytest tests/test_selfplay_stats.py -q`
Expected: FAIL（collection error: `ImportError: cannot import name 'selfplay_stats' from 'katrain_debug'`）

- [ ] **Step 3: 実装を書く** — `katrain_debug/selfplay_stats.py` を Write

```python
"""自己対局ハーネスの純関数（KataGo・Kivy・katrain 本体に依存しない）。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md
対局の実行は selfplay_game.py、CLI は selfplay.py。ここはテストで数値を固定できるものだけを置く。
"""

import hashlib
import itertools
import json
import math
import random
import statistics
from collections import Counter
from contextlib import contextmanager

# ---- 盤サイズ別の定数（spec §2 終局・§3 投了・§5 出力）----
MOVE_CAP = {9: 120, 13: 250, 19: 400}  # 手数上限（上限では最終 scoreLead で勝敗）
TARGET_RATE = {9: 0.40, 13: 0.30, 19: 0.30}  # 韜晦の一致率目標 T（own_le_target_plus5 の T）
RATE_FLOOR = 0.15  # own_lt_floor の床
TARGET_SLACK = 0.05  # own_le_target_plus5 の +0.05
RESIGN_START_13 = 40  # 投了判定の開始手数（13路。他の盤は盤面積で比例）
RESIGN_MIN_WINRATE = 0.95  # 投了の AI 勝率条件
RESIGN_STREAK = 2  # AI の手番で何回続いたら投了するか
VISITS_CHECK_RATIO = 0.9  # root visits が max_visits のこの倍率未満なら visits_low
BLUNDER_TAILS = (1.0, 2.0, 3.0, 6.0)  # AI の失着の尾（目）
HP_AUDIT_LOW = 0.05  # 外した手の 9段 hp がこれ未満の割合を出す
GTP_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

# game_report の depth_filter（盤面積の割合。game_report が ceil(frac * x * y) で手数に直す）
GUI_BINS = (("all", None), ("gui_opening", (0, 0.14)), ("gui_middle", (0.14, 0.4)), ("gui_endgame", (0.4, 10)))
CALIB_BINS = (
    ("cal_opening", (0, 24 / 169)),
    ("cal_middle", (24 / 169, 85 / 169)),
    ("cal_endgame", (85 / 169, 10)),
)
REPORT_BINS = GUI_BINS + CALIB_BINS

# 校正目標（13路の実戦・事後 2500v。spec §3 の表）
CALIB_TARGETS_13 = {
    "opp_mean": 0.231,
    "opp_sd": 0.065,
    "opp_loss": 1.77,
    "opp_ge2": 0.28,
    "opp_ge5": 0.10,
    "ai_mean": 0.533,
    "moves_median": 78.5,
    "bins": {
        "cal_opening": {"opp_top1": 0.267, "opp_loss": 0.56},
        "cal_middle": {"opp_top1": 0.182, "opp_loss": 2.43},
        "cal_endgame": {"opp_top1": 0.291, "opp_loss": 0.96},
    },
}
POOL_TOLERANCE = {"opp_mean": 0.01, "opp_sd": 0.02, "opp_loss": 0.25}  # プール選択のスコアの尺度


# ---- 盤サイズ ----
def move_cap(size):
    return MOVE_CAP.get(size, round(250 * size * size / 169))


def resign_start_move(size):
    """13路 40 を盤面積で比例（9路 19・19路 85）。"""
    return round(RESIGN_START_13 * size * size / 169)


def depth_bin(depth, size, bins=CALIB_BINS):
    """手数 depth が入る区間名（game_report と同じ ceil(frac * x * y) の半開区間）。"""
    for name, rng in bins:
        if rng is None:
            continue
        lo, hi = (math.ceil(f * size * size) for f in rng)
        if lo <= depth < hi:
            return name
    return None


# ---- 座標 ----
def gtp_to_key(gtp):
    """'D4' -> (3, 3)・'pass' -> 'pass'（Move.from_gtp と同じ座標）。"""
    if gtp.lower() == "pass":
        return "pass"
    return (GTP_LETTERS.index(gtp[0].upper()), int(gtp[1:]) - 1)


def key_to_gtp(key):
    if key == "pass":
        return "pass"
    x, y = key
    return f"{GTP_LETTERS[x]}{y + 1}"


def hp_index(key, size):
    """humanPolicy のフラット配列の添字（ai.py enigma9_hp_lookup と同じ。pass は末尾）。"""
    if key == "pass":
        return size * size
    x, y = key
    return (size - 1 - y) * size + x


def hp_to_cands(human_policy, size):
    """humanPolicy -> [(key, p)]（p > 0 のみ。非合法点の -1 と 0 は落とす）。"""
    cands = []
    for i, p in enumerate(human_policy[: size * size]):
        if p > 0:
            cands.append(((i % size, size - 1 - i // size), p))
    if len(human_policy) > size * size and human_policy[size * size] > 0:
        cands.append(("pass", human_policy[size * size]))
    return cands


def hp_audit_values(human_policy, size, played_gtp, best_gtp):
    """hp 監査の1手分: 選んだ手と最善手の hp、選んだ手の hp 順位（1 始まり・pass 込み）。"""

    def hp_of(gtp):
        if gtp is None:
            return None
        idx = hp_index(gtp_to_key(gtp), size)
        return max(0.0, human_policy[idx]) if idx < len(human_policy) else 0.0

    hp_played = hp_of(played_gtp)
    rank = None
    if hp_played is not None:
        rank = 1 + sum(1 for p in human_policy[: size * size + 1] if p > hp_played)
    return {"hp_played": hp_played, "hp_best": hp_of(best_gtp), "hp_rank": rank}


# ---- 日程（seed → 色・段位・投了閾値・乱数の種）----
def selfplay_schedule(n_seeds, ranks, seed_base=1000, resign_leads=None, resign_range=None, no_resign=False):
    """局ごとの開始条件。seed が同じなら全アームで同じ条件（A/B の対）。

    色は seed の偶奇で交互、段位は2局（黒白1局ずつ）ごとに ranks を巡回＝段位と色が交絡しない。
    投了閾値 R は `resign_range` (lo, hi) の一様か、`resign_leads`（実戦の投了局の最終リード）の復元抽出。
    """
    if not ranks:
        raise ValueError("ranks is empty")
    out = []
    for i in range(n_seeds):
        seed = seed_base + i
        rng = random.Random(seed)
        opp_seed = rng.randrange(2**31)
        strategy_seed = rng.randrange(2**31)
        if no_resign:
            resign_lead = None
        elif resign_range is not None:
            resign_lead = rng.uniform(resign_range[0], resign_range[1])
        elif resign_leads:
            resign_lead = rng.choice(list(resign_leads))
        else:
            resign_lead = None
        out.append(
            {
                "index": i,
                "seed": seed,
                "ai_color": "B" if i % 2 == 0 else "W",
                "rank": ranks[(i // 2) % len(ranks)],
                "opp_seed": opp_seed,
                "strategy_seed": strategy_seed,
                "resign_lead": resign_lead,
            }
        )
    return out


def schedule_balance_warning(schedule, ranks):
    """段位 × 色の層の局数が揃わないときの警告文（spec §3: 相手の段位は層別に同数）。揃っていれば None。

    段位は2局ごとに巡回するので、seed の数が 2 × 段位数 の倍数でないと層の局数がずれる（例 20 seed × 3段位 = 8/6/6局）。
    """
    cells = Counter((s["rank"], s["ai_color"]) for s in schedule)
    wanted = [(r, c) for r in dict.fromkeys(ranks) for c in ("B", "W")]
    if len({cells.get(k, 0) for k in wanted}) <= 1:
        return None
    per_rank = Counter(s["rank"] for s in schedule)
    counts = "/".join(str(per_rank.get(r, 0)) for r in dict.fromkeys(ranks))
    return (
        f"warning: {len(schedule)} seeds over {len(set(ranks))} ranks x 2 colours is unbalanced ({counts} games); "
        f"use a number of seeds that is a multiple of {2 * len(set(ranks))}"
    )


def abba_order(arm_names, n_seeds, block=10):
    """[(arm, index)]。block 個の seed ごとにアームの順を反転（2アームなら A B B A …）。"""
    order = []
    for b in range(math.ceil(n_seeds / block)):
        idxs = range(b * block, min((b + 1) * block, n_seeds))
        arms = list(arm_names) if b % 2 == 0 else list(reversed(arm_names))
        for arm in arms:
            order.extend((arm, i) for i in idxs)
    return order


# ---- 相手ボットの1手 ----
def selfplay_opponent_pick(cands, rng, tau, try_move, pass_ok):
    """hp^(1/τ) に比例して1手引き、打てなければ捨てて引き直す。

    cands: [(key, p)]（hp_to_cands の出力。key は (x, y) か "pass"）。
    try_move(key) -> 打てたら None 以外（呼んだ時点で盤に打たれる）・非合法なら None。
    pass_ok() -> パスしてよいか（パスが引かれたときだけ最大1回呼ぶ）。偽ならパスを外して引き直す。
    返り値 (key, try_move の戻り値)。候補が尽きたら (None, None)。
    """
    pool = list(cands)
    pass_allowed = None
    while pool:
        weights = [p ** (1.0 / tau) for _, p in pool]
        r = rng.random() * sum(weights)
        k = len(pool) - 1
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if acc >= r:
                k = i
                break
        key = pool[k][0]
        if key == "pass":
            if pass_allowed is None:
                pass_allowed = bool(pass_ok())
            if not pass_allowed:
                pool.pop(k)
                continue
        result = try_move(key)
        if result is not None:
            return key, result
        pool.pop(k)
    return None, None


# ---- 投了・勝敗 ----
def ai_view_lead(score_black, ai_color):
    return None if score_black is None else score_black * (1 if ai_color == "B" else -1)


def ai_view_winrate(wr_black, ai_color):
    return None if wr_black is None else (wr_black if ai_color == "B" else 1.0 - wr_black)


def selfplay_should_resign(depth, lead_ai, wr_ai, streak, threshold, size):
    """相手の投了判定（AI の手番ごとに呼ぶ）。返り値 (投了するか, 新しい連続回数)。

    開始手数以降に AI 視点で lead >= threshold かつ AI 勝率 >= 0.95 が AI の2手番続いたら投了。
    threshold None（--no-resign）なら投了しない。
    """
    if threshold is None or lead_ai is None or wr_ai is None or depth < resign_start_move(size):
        return False, 0
    streak = streak + 1 if (lead_ai >= threshold and wr_ai >= RESIGN_MIN_WINRATE) else 0
    return streak >= RESIGN_STREAK, streak


def resign_pool_from_summaries(summaries, size):
    """実戦の report_game_*.json の summary 群 → 投了局の最終リード（AI 視点）の標本。

    実戦の監視対局はパスで終わらない（相手の投了で終わる）ので全局を投了局とみなす。投了判定の開始手数
    （13路 40）未満で終わった局は除く。13路以外の盤は盤面積で比例させる（9路 ×81/169・19路 ×361/169）。
    """
    scale = size * size / 169
    out = []
    for s in summaries:
        if s.get("final_score") is None or s.get("n_moves", 0) < RESIGN_START_13:
            continue
        lead = s["final_score"] * (1 if s["ai"] == "B" else -1)
        out.append(round(lead * scale, 2))
    return out


def selfplay_outcome(end_reason, final_lead_ai):
    """終局理由と最終 scoreLead（AI 視点）から AI の勝敗（win / loss / jigo / aborted / unknown）。"""
    if end_reason == "aborted":
        return "aborted"
    if end_reason == "opp_resign":
        return "win"
    if final_lead_ai is None:
        return "unknown"
    rounded = round(2 * final_lead_ai) / 2  # manual_score と同じ半目丸め
    if rounded > 0:
        return "win"
    if rounded < 0:
        return "loss"
    return "jigo"


# ---- WATCH 木（末尾のパスを除いた木）----
def main_line_end(node):
    while node.children:
        node = node.children[0]
    return node


@contextmanager
def watch_prune(game):
    """game_report を「最後の石で終わる木」で呼ぶためのコンテキスト（spec §2 WATCH）。

    game._lock の下で (1) 最後の石のノードの children を一時的に外し、(2) game.current_node を
    属性の直接代入でそのノードへ付け替える（set_current_node は _calculate_groups を走らせるので使わない）。
    finally で children と current_node の両方を必ず戻す。
    """
    with game._lock:
        original_current = game.current_node
        last = main_line_end(original_current)
        while last.parent is not None and last.is_pass:
            last = last.parent
        saved_children = last.children
        last.children = []
        game.current_node = last
        try:
            yield last
        finally:
            last.children = saved_children
            game.current_node = original_current


def report_block(sum_stats, player_ptloss, bw):
    """game_report の1色分を {top1, top5, mean_ptloss, n} に。手が無ければ値は None・n は 0。"""
    s = sum_stats.get(bw) or {}
    return {
        "top1": s.get("ai_top_move"),
        "top5": s.get("ai_top5_move"),
        "mean_ptloss": s.get("mean_ptloss"),
        "n": len(player_ptloss.get(bw) or []),
    }


# ---- 1手1行 ----
def selfplay_move_rows(nodes, ai_color, size, max_visits=None):
    """本譜の着手ノード（root を除く・時系列）を1手1行にする。一致・分母はレポートと同じ定義。

    match = 親の解析が完了していて candidate_moves[0] と着手が同じ。points_lost が None の手は
    レポートの分母に入らない（run_*_rate も同じ）。trailing_pass は最後の石より後のパス。
    """
    opp_color = "W" if ai_color == "B" else "B"
    last_stone = max((i for i, n in enumerate(nodes) if not n.is_pass), default=-1)
    tally = {"B": [0, 0], "W": [0, 0]}
    rows = []
    for i, n in enumerate(nodes):
        parent = n.parent
        cands = parent.candidate_moves if parent.analysis_complete else []
        best = cands[0]["move"] if cands else None
        gtp = n.move.gtp()
        match = best is not None and best == gtp
        pl = n.points_lost
        if pl is not None:
            tally[n.player][1] += 1
            tally[n.player][0] += int(match)
        visits = parent.root_visits
        rows.append(
            {
                "depth": n.depth,
                "player": n.player,
                "is_ai": n.player == ai_color,
                "move": gtp,
                "best": best,
                "match": match,
                "points_lost": pl,
                "loss": None if pl is None else max(0.0, pl),
                "lead_before_ai": ai_view_lead(parent.score, ai_color),
                "lead_after_ai": ai_view_lead(n.score, ai_color),
                "wr_before_ai": ai_view_winrate(parent.winrate, ai_color),
                "wr_after_ai": ai_view_winrate(n.winrate, ai_color),
                "parent_visits": visits,
                "visits_low": bool(max_visits) and visits < VISITS_CHECK_RATIO * max_visits,
                "best_prior": cands[0].get("prior") if cands else None,
                "bin": depth_bin(n.depth, size),
                "trailing_pass": i > last_stone,
                "run_own_rate": tally[ai_color][0] / tally[ai_color][1] if tally[ai_color][1] else None,
                "run_opp_rate": tally[opp_color][0] / tally[opp_color][1] if tally[opp_color][1] else None,
            }
        )
    return rows


def merge_turns(rows, turns):
    """AI 手番の記録（depth = AI の着手ノードの手数）を同じ depth の行に足す。"""
    by_depth = {t["depth"]: t for t in turns}
    for row in rows:
        turn = by_depth.get(row["depth"])
        if row["is_ai"] and turn is not None:
            row.update({k: v for k, v in turn.items() if k != "depth"})
    return rows


def flat_row(row):
    """moves.jsonl の1行: 判定情報（decision）と影判定（shadow）の dict を decision_* / shadow_* の列に平らにする。"""
    out = {k: v for k, v in row.items() if k not in ("decision", "shadow")}
    for prefix in ("decision", "shadow"):
        for k, v in (row.get(prefix) or {}).items():
            out[f"{prefix}_{k}"] = v
    return out


# ---- 1局の要約 ----
def percentile(values, q):
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _decision_metrics(ai_rows, rows, reserve, ledger):
    """判定情報（last_decision_info）を持つ戦略（韜晦）だけの指標。持たない戦略では None。

    期待するキー（韜晦の計画 plans/2026-09-23-veil-strategy.md の「共有インターフェース」）: tier / kind（free・paid・
    trap ほか）/ best / chosen / vloss / lead / E / close（無ければ lead < reserve で代用）。
    curse_by_kind = 外しの種類ごとの「レポートの損失 − 判定時の vloss」（spec §6 勝者の呪いの検出。正なら判定が甘い）。
    """
    decs = [r for r in ai_rows if isinstance(r.get("decision"), dict) and r["decision"]]
    if not decs:
        return None

    def vl(d):
        v = d.get("vloss")
        return max(0.0, v) if _num(v) else 0.0

    infos = [r["decision"] for r in decs]
    dev_rows = [
        r
        for r in decs
        if r["decision"].get("chosen") is not None and r["decision"]["chosen"] != r["decision"].get("best")
    ]
    deviated = [r["decision"] for r in dev_rows]
    kinds = Counter(str(d.get("kind")) for d in infos)
    vloss_by_kind = {k: sum(vl(d) for d in deviated if str(d.get("kind")) == k) for k in sorted(kinds)}
    report_loss_by_kind = {
        k: sum(r["loss"] or 0.0 for r in dev_rows if str(r["decision"].get("kind")) == k) for k in sorted(kinds)
    }
    out = {
        "tiers": dict(Counter(str(d.get("tier")) for d in infos)),
        "kinds": dict(kinds),
        "paid_vloss_sum": sum(vl(d) for d in deviated),
        "vloss_by_kind": vloss_by_kind,
        "report_loss_by_kind": report_loss_by_kind,
        "curse_by_kind": {k: report_loss_by_kind[k] - vloss_by_kind[k] for k in sorted(kinds)},
        "nonfree_below_reserve": None,
        "close_free_vloss": None,
        "trap_next_loss_over_E": None,
        "ledger_mismatch": None,
    }
    if reserve is not None:
        below = [d for d in deviated if _num(d.get("lead")) and d["lead"] < reserve]
        out["nonfree_below_reserve"] = sum(1 for d in below if d.get("kind") != "free")
        out["close_free_vloss"] = sum(
            vl(d)
            for d in deviated
            if d.get("kind") == "free" and d.get("close", _num(d.get("lead")) and d["lead"] < reserve)
        )
    by_depth = {r["depth"]: r for r in rows}
    loss_sum = e_sum = 0.0
    for r in decs:
        d = r["decision"]
        nxt = by_depth.get(r["depth"] + 1)
        if d.get("kind") == "trap" and _num(d.get("E")) and d["E"] > 0 and nxt is not None and nxt["loss"] is not None:
            loss_sum += nxt["loss"]
            e_sum += d["E"]
    if e_sum > 0:
        out["trap_next_loss_over_E"] = loss_sum / e_sum
    if ledger is not None:
        ai_by_depth = {r["depth"]: r for r in ai_rows}
        mism = 0
        for entry in ledger:
            depth, best_gtp, played = entry[0], entry[1], entry[2]
            row = ai_by_depth.get(depth + 1)
            if row is not None and played != best_gtp and row["match"]:
                mism += 1
        out["ledger_mismatch"] = mism
    return out


def _shadow_metrics(ai_rows):
    """影判定（spec §6 --shadow）: 同じ局面での B の外し率とコスト（B の手の pointsLost）を、打った A の手と対で出す。"""
    sh = [r for r in ai_rows if isinstance(r.get("shadow"), dict) and r["shadow"].get("move")]
    if not sh:
        return None
    with_best = [r for r in sh if r["best"] is not None]
    return {
        "arm": sh[0]["shadow"].get("arm"),
        "n": len(sh),
        "dev_rate": (
            sum(1 for r in with_best if r["shadow"]["move"] != r["best"]) / len(with_best) if with_best else None
        ),
        "same_as_played": sum(1 for r in sh if r["shadow"]["move"] == r["move"]) / len(sh),
        "vloss_mean": _fmean([r["shadow"].get("vloss") for r in sh]),
        "played_loss_mean": _fmean([r["loss"] for r in sh]),
        "secs_p95": percentile([r["shadow"].get("secs") for r in sh], 0.95),
    }


def selfplay_game_summary(meta, reports, rows, target, reserve=None, ledger=None, wall_s=None):
    """games.jsonl の1行（spec §5）。meta は seed・arm・色・段位・komi・end_reason などの開始条件と終局理由。

    主指標は WATCH（末尾のパスを除いた木）の全体の一致率。own = AI・opp = 相手。
    """
    ai_rows = [r for r in rows if r["is_ai"]]
    opp_rows = [r for r in rows if not r["is_ai"]]
    watch_all = (reports.get("WATCH") or {}).get("all") or {}
    own = watch_all.get("ai") or {}
    opp = watch_all.get("opp") or {}
    own_top1, opp_top1 = own.get("top1"), opp.get("top1")
    leads = [r["lead_after_ai"] for r in rows if r["lead_after_ai"] is not None]
    wrs = [r["wr_after_ai"] for r in rows if r["wr_after_ai"] is not None]
    final_lead = leads[-1] if leads else None
    opp_losses = [r["loss"] for r in opp_rows if r["loss"] is not None]
    dev_hp = [
        r["hp_played"]
        for r in ai_rows
        if r.get("hp_played") is not None and r["best"] is not None and not r["match"] and r["points_lost"] is not None
    ]
    times = [r["strategy_s"] for r in ai_rows if r.get("strategy_s") is not None]
    rec = dict(meta)
    rec.update(
        {
            "result": selfplay_outcome(meta.get("end_reason"), final_lead),
            "n_moves": rows[-1]["depth"] if rows else 0,
            "final_lead": final_lead,
            "lead_min": min(leads) if leads else None,
            "lead_max": max(leads) if leads else None,
            "ai_wr_min": min(wrs) if wrs else None,
            "reports": reports,
            "own_top1": own_top1,
            "opp_top1": opp_top1,
            "own_top5": own.get("top5"),
            "opp_top5": opp.get("top5"),
            "own_n": own.get("n", 0),
            "opp_n": opp.get("n", 0),
            "own_mean_ptloss": own.get("mean_ptloss"),
            "opp_mean_ptloss": opp.get("mean_ptloss"),
            "own_minus_opp": None if own_top1 is None or opp_top1 is None else own_top1 - opp_top1,
            "own_lt_opp": None if own_top1 is None or opp_top1 is None else own_top1 < opp_top1,
            "own_le_target_plus5": None if own_top1 is None else own_top1 <= target + TARGET_SLACK,
            "own_lt_floor": None if own_top1 is None else own_top1 < RATE_FLOOR,
            "ai_tail": {
                f"ge{int(t)}": sum(1 for r in ai_rows if r["loss"] is not None and r["loss"] >= t)
                for t in BLUNDER_TAILS
            },
            "opp_tail": {
                "n": len(opp_losses),
                "ge2": sum(1 for x in opp_losses if x >= 2.0),
                "ge5": sum(1 for x in opp_losses if x >= 5.0),
            },
            "flip_moves": sum(
                1
                for r in ai_rows
                if r["wr_before_ai"] is not None
                and r["wr_after_ai"] is not None
                and r["wr_before_ai"] >= 0.5
                and r["wr_after_ai"] < 0.5
            ),
            "hp_dev_list": [round(x, 4) for x in dev_hp],
            "hp_dev_median": statistics.median(dev_hp) if dev_hp else None,
            "hp_dev_lt5": sum(1 for x in dev_hp if x < HP_AUDIT_LOW) / len(dev_hp) if dev_hp else None,
            "intent_report_mismatch": sum(
                1
                for r in ai_rows
                if r.get("best_at_decision") is not None
                and r.get("played") is not None
                and r["played"] != r["best_at_decision"]
                and r["match"]
            ),
            "veil": _decision_metrics(ai_rows, rows, reserve, ledger),
            "shadow": _shadow_metrics(ai_rows),
            "strategy_times": [round(t, 3) for t in times],
            "strategy_p50": percentile(times, 0.5),
            "strategy_p95": percentile(times, 0.95),
            "strategy_max": max(times) if times else None,
            "wait_s": sum(r.get("wait_s") or 0.0 for r in ai_rows),
            "wall_s": wall_s,
            "visits_low": sum(1 for r in rows if r["visits_low"]),
        }
    )
    return rec


# ---- 統計 ----
def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, center - half), min(1.0, center + half))


def cluster_bootstrap(clusters, stat, n_boot=10000, seed=0, conf=0.95):
    """局（クラスタ）を復元抽出して stat(標本) の percentile 区間。stat が None を返した標本は捨てる。"""
    if not clusters:
        return (None, None)
    rng = random.Random(seed)
    k = len(clusters)
    vals = []
    for _ in range(n_boot):
        v = stat([clusters[rng.randrange(k)] for _ in range(k)])
        if v is not None:
            vals.append(v)
    a = (1 - conf) / 2
    return (percentile(vals, a), percentile(vals, 1 - a))


def _betacf(a, b, x):
    """不完全ベータ関数の連分数（Numerical Recipes 6.4）。"""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-14:
            break
    return h


def _betainc(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    tail = 0.5 * _betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t >= 0 else tail


def t_ppf(p, df):
    lo, hi = -1e4, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def t_interval(values, conf=0.95):
    n = len(values)
    if n < 2:
        return (None, None)
    m = statistics.fmean(values)
    half = t_ppf(0.5 + conf / 2, n - 1) * statistics.stdev(values) / math.sqrt(n)
    return (m - half, m + half)


def wilcoxon_signed_rank(diffs):
    """両側 p 値。0 の差は捨てる（Wilcoxon 法）。同順位が無く n <= 50 なら正確分布、それ以外は正規近似。"""
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n == 0:
        return None
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    tie_sizes = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        if j > i:
            tie_sizes.append(j - i + 1)
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    if not tie_sizes and n <= 50:
        total = n * (n + 1) // 2
        counts = [0] * (total + 1)
        counts[0] = 1
        for k in range(1, n + 1):
            for s in range(total, k - 1, -1):
                counts[s] += counts[s - k]
        w = int(round(w_plus))
        tail = min(sum(counts[: w + 1]), sum(counts[w:]))
        return min(1.0, 2 * tail / 2**n)
    mean = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24 - sum(t**3 - t for t in tie_sizes) / 48
    if var <= 0:
        return None
    z = (w_plus - mean) / math.sqrt(var)
    return min(1.0, 2 * (1 - statistics.NormalDist().cdf(abs(z))))


def selfplay_stop_rule(lo, hi, margin=0.03):
    """停止規則（spec §6）: 差の区間が ±margin の判定線をまたぐなら extend。"""
    if lo is None or hi is None:
        return "insufficient"
    if lo < -margin < hi or lo < margin < hi:
        return "extend"
    if lo >= margin:
        return "higher"
    if hi <= -margin:
        return "lower"
    return "within"


# ---- アームの要約 ----
def metric_value(rec, metric):
    if metric == "win":
        if rec.get("result") in ("aborted", "unknown", None):
            return None
        return 1.0 if rec["result"] == "win" else 0.0
    if metric == "ge6":
        return (rec.get("ai_tail") or {}).get("ge6")
    v = rec.get(metric)
    if isinstance(v, bool):
        return float(v)
    return v


def _mean_rate(pairs):
    return statistics.fmean(v for v, _ in pairs) if pairs else None


def _pooled_rate(pairs):
    total = sum(n for _, n in pairs)
    return sum(v * n for v, n in pairs) / total if total else None


def _frac(recs, key):
    vals = [r.get(key) for r in recs if r.get(key) is not None]
    return sum(1 for v in vals if v) / len(vals) if vals else None


def _fmean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def selfplay_arm_summary(records, n_boot=10000, seed=0):
    """1群（アーム、またはアーム × 段位 × 色）の要約（spec §5 summary）。aborted の局は数えるだけ。"""
    ok = [r for r in records if r.get("result") != "aborted"]
    wins = sum(1 for r in ok if r["result"] == "win")
    out = {
        "games": len(records),
        "aborted": len(records) - len(ok),
        "wins": wins,
        "losses": sum(1 for r in ok if r["result"] == "loss"),
        "jigo": sum(1 for r in ok if r["result"] == "jigo"),
        "win_ci": list(wilson(wins, len(ok))),
    }
    for side in ("own", "opp"):
        pairs = [(r[f"{side}_top1"], r[f"{side}_n"]) for r in ok if r.get(f"{side}_top1") is not None]
        out[f"{side}_top1_mean"] = _mean_rate(pairs)
        out[f"{side}_top1_mean_ci"] = list(cluster_bootstrap(pairs, _mean_rate, n_boot, seed))
        out[f"{side}_top1_pooled"] = _pooled_rate(pairs)
        out[f"{side}_top1_pooled_ci"] = list(cluster_bootstrap(pairs, _pooled_rate, n_boot, seed))
        out[f"{side}_mean_ptloss"] = _fmean([r.get(f"{side}_mean_ptloss") for r in ok])
    diffs = [r["own_minus_opp"] for r in ok if r.get("own_minus_opp") is not None]
    out["own_minus_opp_mean"] = statistics.fmean(diffs) if diffs else None
    out["own_minus_opp_ci"] = list(cluster_bootstrap(diffs, lambda s: statistics.fmean(s), n_boot, seed))
    out["p_own_lt_opp"] = _frac(ok, "own_lt_opp")
    out["p_own_le_target_plus5"] = _frac(ok, "own_le_target_plus5")
    out["p_own_lt_floor"] = _frac(ok, "own_lt_floor")
    out["ge6_per_game"] = _fmean([(r.get("ai_tail") or {}).get("ge6") for r in ok])
    out["flip_per_game"] = _fmean([r.get("flip_moves") for r in ok])
    leads = [r["final_lead"] for r in ok if r.get("final_lead") is not None]
    out["final_lead_median"] = percentile(leads, 0.5)
    out["final_lead_iqr"] = [percentile(leads, 0.25), percentile(leads, 0.75)]
    out["moves_median"] = percentile([r.get("n_moves") for r in ok], 0.5)
    bins = {}
    for name, _ in REPORT_BINS:
        pairs = []
        for r in ok:
            block = (((r.get("reports") or {}).get("WATCH") or {}).get(name) or {}).get("ai") or {}
            if block.get("top1") is not None:
                pairs.append((block["top1"], block["n"]))
        bins[name] = _pooled_rate(pairs)
    out["own_top1_by_bin"] = bins
    hp = [x for r in ok for x in (r.get("hp_dev_list") or [])]
    out["hp_dev_median"] = statistics.median(hp) if hp else None
    out["hp_dev_n"] = len(hp)
    out["strategy_p95"] = percentile([t for r in ok for t in (r.get("strategy_times") or [])], 0.95)
    out["visits_low"] = sum(r.get("visits_low") or 0 for r in ok)
    out["shadow_dev_rate"] = _fmean([(r.get("shadow") or {}).get("dev_rate") for r in ok])
    out["shadow_same_as_played"] = _fmean([(r.get("shadow") or {}).get("same_as_played") for r in ok])
    out["shadow_vloss_mean"] = _fmean([(r.get("shadow") or {}).get("vloss_mean") for r in ok])
    out["shadow_played_loss_mean"] = _fmean([(r.get("shadow") or {}).get("played_loss_mean") for r in ok])
    return out


def selfplay_summarize(records, n_boot=10000, seed=0):
    """アームごと と アーム × 段位 × 色ごと の要約。"""
    arms, strata = {}, {}
    for r in records:
        arms.setdefault(r["arm"], []).append(r)
        strata.setdefault(f"{r['arm']}|{r['rank']}|{r['ai_color']}", []).append(r)
    return {
        "arms": {k: selfplay_arm_summary(v, n_boot, seed) for k, v in sorted(arms.items())},
        "strata": {k: selfplay_arm_summary(v, n_boot, seed) for k, v in sorted(strata.items())},
    }


def selfplay_paired_diff(recs_a, recs_b, metric, n_boot=10000, seed=0, conf=0.975, margin=0.03):
    """同じ seed の対の差 a − b（spec §6）。conf 既定 0.975＝2回見る停止規則の Bonferroni。"""
    fa = {r["seed"]: metric_value(r, metric) for r in recs_a if r.get("result") != "aborted"}
    fb = {r["seed"]: metric_value(r, metric) for r in recs_b if r.get("result") != "aborted"}
    seeds = sorted(s for s in fa if s in fb and fa[s] is not None and fb[s] is not None)
    diffs = [fa[s] - fb[s] for s in seeds]
    t_lo, t_hi = t_interval(diffs, conf)
    return {
        "metric": metric,
        "n": len(diffs),
        "mean": statistics.fmean(diffs) if diffs else None,
        "t_ci": [t_lo, t_hi],
        "wilcoxon_p": wilcoxon_signed_rank(diffs),
        "boot_ci": list(cluster_bootstrap(diffs, lambda s: statistics.fmean(s), n_boot, seed, conf)),
        "conf": conf,
        "verdict": selfplay_stop_rule(t_lo, t_hi, margin),
    }


# ---- 設定の突き合わせ ----
def settings_fingerprint(mode, settings):
    blob = json.dumps({"mode": mode, "settings": settings}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def arms_null_guard(arms):
    """解決済み設定が同一のアームの組 [(name, name)]。空でなければ null 実験＝中止する。"""
    pairs = []
    for a, b in itertools.combinations(arms, 2):
        if settings_fingerprint(a["mode"], a["settings"]) == settings_fingerprint(b["mode"], b["settings"]):
            pairs.append((a["name"], b["name"]))
    return pairs


def unknown_override_keys(overrides, user_section, known_keys):
    """ユーザー config の節にも戦略の既定値にも無い上書きキー（綴り間違いの検出）。"""
    return sorted(k for k in (overrides or {}) if k not in (user_section or {}) and k not in known_keys)


def parse_arm(text):
    """'A=veil13:veil13_trap_mode=true,veil13_reserve=4.0' -> ('A', 'veil13', ['veil13_trap_mode=true', ...])"""
    if "=" not in text:
        raise ValueError(f"arm must be NAME=STRATEGY[:key=val,...]: {text!r}")
    name, rest = text.split("=", 1)
    strategy, _, tail = rest.partition(":")
    name, strategy = name.strip(), strategy.strip()
    if not name or not strategy:
        raise ValueError(f"arm must be NAME=STRATEGY[:key=val,...]: {text!r}")
    return name, strategy, [s.strip() for s in tail.split(",") if s.strip()]


def parse_range(text):
    """'8:40' -> (8.0, 40.0)"""
    lo, hi = text.split(":", 1)
    lo, hi = float(lo), float(hi)
    if lo > hi:
        raise ValueError(f"range lo > hi: {text!r}")
    return lo, hi


# ---- 校正（spec §3 calibrate）----
def calibration_rank_stats(records):
    """段位ごとの相手の統計（局平均・局間 SD・損失・≥2/≥5 の割合・校正用区間の形）と AI 側の一致率。"""
    by_rank = {}
    for r in records:
        if r.get("result") != "aborted" and r.get("opp_top1") is not None:
            by_rank.setdefault(r["rank"], []).append(r)
    out = {}
    for rank, recs in by_rank.items():
        opp = [r["opp_top1"] for r in recs]
        tails = [r.get("opp_tail") or {} for r in recs]
        n_loss = sum(t.get("n", 0) for t in tails)
        bins = {}
        for name, _ in CALIB_BINS:
            blocks = [(((r["reports"].get("WATCH") or {}).get(name) or {}).get("opp") or {}) for r in recs]
            blocks = [b for b in blocks if b.get("top1") is not None and b.get("n")]
            n_bin = sum(b["n"] for b in blocks)
            bins[name] = {
                "opp_top1": sum(b["top1"] * b["n"] for b in blocks) / n_bin if n_bin else None,
                "opp_loss": sum(b["mean_ptloss"] * b["n"] for b in blocks) / n_bin if n_bin else None,
                "n": n_bin,
            }
        out[rank] = {
            "games": len(recs),
            "opp_mean": statistics.fmean(opp),
            "opp_sd": statistics.pstdev(opp),
            "opp_pooled": _pooled_rate([(r["opp_top1"], r["opp_n"]) for r in recs]),
            "opp_loss": _fmean([r.get("opp_mean_ptloss") for r in recs]),
            "opp_ge2": sum(t.get("ge2", 0) for t in tails) / n_loss if n_loss else None,
            "opp_ge5": sum(t.get("ge5", 0) for t in tails) / n_loss if n_loss else None,
            "own_mean": _fmean([r.get("own_top1") for r in recs]),
            "moves_median": percentile([r.get("n_moves") for r in recs], 0.5),
            "bins": bins,
        }
    return out


def selfplay_pool_choice(rank_stats, targets=CALIB_TARGETS_13, k=3, tolerance=POOL_TOLERANCE):
    """k 段位の組（層は同数）の局平均・局間 SD・損失を目標と比べ、スコアの小さい順に返す。

    局間 SD は全分散の公式（層内分散の平均 + 層平均の分散。どちらも母分散）。
    """
    choices = []
    for combo in itertools.combinations(list(rank_stats), k):
        st = [rank_stats[r] for r in combo]
        means = [s["opp_mean"] for s in st]
        mean = statistics.fmean(means)
        sd = math.sqrt(statistics.fmean([s["opp_sd"] ** 2 for s in st]) + statistics.pvariance(means))
        loss = _fmean([s["opp_loss"] for s in st])
        score = ((mean - targets["opp_mean"]) / tolerance["opp_mean"]) ** 2 + (
            (sd - targets["opp_sd"]) / tolerance["opp_sd"]
        ) ** 2
        if loss is not None:
            score += ((loss - targets["opp_loss"]) / tolerance["opp_loss"]) ** 2
        choices.append(
            {
                "ranks": list(combo),
                "opp_mean": mean,
                "opp_sd": sd,
                "opp_loss": loss,
                "own_mean": _fmean([s["own_mean"] for s in st]),
                "bins": {
                    name: {
                        "opp_top1": _fmean([s["bins"][name]["opp_top1"] for s in st]),
                        "opp_loss": _fmean([s["bins"][name]["opp_loss"] for s in st]),
                    }
                    for name, _ in CALIB_BINS
                },
                "score": score,
            }
        )
    return sorted(choices, key=lambda c: c["score"])
```

- [ ] **Step 4: 通ることを確かめる**

Run: `pytest tests/test_selfplay_stats.py -q`
Expected: `47 passed`

- [ ] **Step 5: 整形の確認とコミット**

Run: `python -m black --line-length 120 --check katrain_debug/selfplay_stats.py tests/test_selfplay_stats.py`
Expected: `2 files would be left unchanged.`

```bash
git add katrain_debug/selfplay_stats.py tests/test_selfplay_stats.py
git commit -m "feat(selfplay): 自己対局ハーネスの純関数（日程・投了・WATCH 木・要約・統計）

seed から色・段位・投了閾値・乱数の種を決める日程（層の偏りの警告つき）と ABBA、
hp^(1/τ) の抽選と非合法手・パスの引き直し、盤サイズ別の投了判定、末尾のパスを
除いた WATCH 木で game_report を呼ぶ watch_prune、1局とアームの要約（韜晦の外しの
種類ごとの勝者の呪い・影判定のコストを含む。Wilson・局単位 bootstrap・t 区間・
Wilcoxon・停止規則）、null ガード、校正のプール選択。KataGo 不要。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 相手ボット `HumanSLOpponent` と待ちループ（偽エンジンでテスト）

**Files:**
- Create: `katrain_debug/selfplay_opponent.py`
- Create: `tests/selfplay_fakes.py`（テスト用の偽エンジンとスタブ。`test_` で始まらないので pytest は収集しない。Task 4〜6 のテストも使う）
- Test: `tests/test_selfplay_opponent.py`

**Interfaces:**
- Consumes: `selfplay_stats.hp_to_cands` / `key_to_gtp` / `gtp_to_key` / `selfplay_opponent_pick`（Task 2）、`katrain.core.ai._area_scoring_should_pass(moves, pass_loss)`（ai.py:786）、`katrain.core.game.IllegalMoveException`、`KataGoEngine.request_analysis(node, callback, error_callback, visits, priority, ownership, include_policy, time_limit, extra_settings)`・`check_alive()`（死んでいても例外を投げず False を返す＝engine.py:242-259）
- Produces:
  - `GameAborted(Exception)` — その局を aborted にする
  - `Waiter(engine, timeout=180.0, watchdog=None)` — `.until(pred, what, poll=0.01)`（`engine.check_alive()` が偽・`watchdog.restarts` が作成時と違う・timeout 超過で `GameAborted`）、`.nodes(nodes, what="node analysis")`（全ノードの `analysis_complete` を待つ）、`.humansl(node, profile, visits=1) -> dict | None`（humanSL を1本撃って KataGo の JSON を返す。ノードに書き戻さない）
  - `HumanSLOpponent(profile, tau=1.0, seed=0, max_loss=None, visits=1)` — `.label`（`"humanSL:<profile>"`）、`.stats`（`moves`・`pass_redraws`・`illegal_redraws`・`fallbacks`）、`.play(game, waiter) -> GameNode`（打ったノード。候補が尽きたらパス）
  - `tests/selfplay_fakes.py`: `CONFIG`・`make_stub(tmp_path, **ai_sections) -> KaTrainStub`（`tmp_path/config.json` を書く）・`empties_of(node)`・`hp_array(size, weights)`・`top_right_hp(node, empties)`・`FakeEngine(hp_fn=top_right_hp, include_pass=False, pass_loss=0.0, lead=0.5, winrate=0.6, visits=100)`（属性 `requests`・`alive`・`restarts`・`shutdowns`・`new_games`、メソッド `request_analysis`・`terminate_queries`・`on_new_game`・`check_alive`・`restart`・`shutdown`）・`new_game(stub, engine, size=9) -> Game`
  - 偽エンジンの約束: 通常解析の候補は「空点を左下から x→y の順に走査した先頭3点」で `[0]` が最善手（`A1` → `B1` → …）。打つ側から見て i 番目の候補は 0.5×i 目悪い。humanSL は既定で右上の空点2つ（0.7 / 0.3）＝左下を埋める AI とぶつからない。

- [ ] **Step 1: 偽エンジンを書く** — `tests/selfplay_fakes.py` を Write

```python
"""自己対局ハーネスのテスト用の偽エンジンとスタブ（KataGo 不要）。test_ で始まらないので pytest は収集しない。"""

import json
import time

from katrain.core.game import Game
from katrain.core.sgf_parser import Move
from katrain_debug.katrain_stub import KaTrainStub

CONFIG = {
    "engine": {
        "max_visits": 100,
        "fast_visits": 10,
        "max_time": 8.0,
        "wide_root_noise": 0.04,
        "_enable_ownership": False,
    },
    "game": {"size": "9", "komi": 7.0, "rules": "chinese", "handicap": 0},
    "trainer": {
        "eval_thresholds": [12, 6, 3, 1.5, 0.5, 0],
        "save_feedback": [True, True, True, True, False, False],
        "eval_show_ai": True,
        "save_analysis": False,
        "save_marks": False,
    },
    "ai": {"ai:default": {}},
}


def make_stub(tmp_path, **ai_sections):
    """一時 config.json を書いて本物の KaTrainStub を作る。ai_sections は {"ai:mode": {...}}。"""
    cfg = json.loads(json.dumps(CONFIG))
    cfg["ai"].update(ai_sections)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return KaTrainStub(str(path), debug_level=0, quiet=True)


def empties_of(node):
    """node の局面の空点（左下から x→y の順）。取りは起きない前提の簡易版。"""
    size = node.board_size[0]
    occupied = {m.coords for n in node.nodes_from_root for m in n.moves if m.coords is not None}
    return [(x, y) for y in range(size) for x in range(size) if (x, y) not in occupied]


def hp_array(size, weights):
    """{(x, y) | "pass": hp} -> humanPolicy のフラット配列（末尾 pass）。"""
    arr = [0.0] * (size * size + 1)
    for key, v in weights.items():
        if key == "pass":
            arr[-1] = v
        else:
            x, y = key
            arr[(size - 1 - y) * size + x] = v
    return arr


def top_right_hp(node, empties):
    """既定の humanSL: 右上の空点2つ（左下から埋める AI とぶつからない）。"""
    size = node.board_size[0]
    return hp_array(size, {empties[-1]: 0.7, empties[-2]: 0.3})


class FakeEngine:
    """同期で答える偽 KataGo（呼んだスレッドでそのままコールバックする）。

    通常解析: 候補は空点を左下から走査した先頭3点（order 順・[0] が最善手）。勝率は全ノード winrate（黒視点）。黒視点 scoreLead は
    root = lead、候補 i = lead - sign * 0.5 * i（打つ側から見て i 番目ほど 0.5 目ずつ悪い）。
    include_pass なら pass を pointsLost = pass_loss で候補の末尾に足す。
    humanSL（extra_settings に humanSLProfile）: hp_fn(node, empties) の humanPolicy を返す。
    """

    def __init__(self, hp_fn=top_right_hp, include_pass=False, pass_loss=0.0, lead=0.5, winrate=0.6, visits=100):
        self.hp_fn = hp_fn
        self.winrate = winrate
        self.include_pass = include_pass
        self.pass_loss = pass_loss
        self.lead = lead
        self.visits = visits
        self.requests = []
        self.alive = True
        self.restarts = 0
        self.shutdowns = 0
        self.new_games = 0

    def request_analysis(self, node, callback, error_callback=None, **kwargs):
        self.requests.append((node, kwargs))
        empties = empties_of(node)
        extra = kwargs.get("extra_settings") or {}
        if "humanSLProfile" in extra:
            hp = self.hp_fn(node, empties)
            callback(
                {"rootInfo": {"scoreLead": 0.0, "winrate": 0.5, "visits": 1}, "moveInfos": [], "humanPolicy": hp}, False
            )
            return
        sign = 1 if node.next_player == "B" else -1
        infos = []
        for i, c in enumerate(empties[:3]):
            gtp = Move(c).gtp()
            infos.append(
                {
                    "move": gtp,
                    "order": i,
                    "visits": self.visits - 10 * i,
                    "scoreLead": self.lead - sign * 0.5 * i,
                    "winrate": self.winrate,
                    "prior": 0.5 / (i + 1),
                    "pv": [gtp],
                }
            )
        if self.include_pass:
            infos.append(
                {
                    "move": "pass",
                    "order": len(infos),
                    "visits": 5,
                    "scoreLead": self.lead - sign * self.pass_loss,
                    "winrate": self.winrate,
                    "prior": 0.01,
                    "pv": ["pass"],
                }
            )
        root = {"scoreLead": self.lead, "winrate": self.winrate, "visits": self.visits}
        callback({"rootInfo": root, "moveInfos": infos}, False)

    def terminate_queries(self, only_for_node=None, lock=True):
        pass

    def on_new_game(self):
        self.new_games += 1

    def check_alive(self, *args, **kwargs):
        return self.alive

    def restart(self):
        self.restarts += 1
        self.alive = True

    def shutdown(self, finish=False):
        self.shutdowns += 1


def new_game(stub, engine, size=9):
    """本物の Game（root の解析はデーモンスレッドで偽エンジンが即答する）。"""
    game = Game(stub, engine, game_properties={"SZ": size, "KM": 7.0, "RU": "chinese"})
    stub.game = game
    started = time.time()
    while not game.root.analysis_complete:
        assert time.time() - started < 5, "root analysis never completed"
        time.sleep(0.005)
    return game
```

- [ ] **Step 2: 失敗するテストを書く** — `tests/test_selfplay_opponent.py` を Write

```python
# tests/test_selfplay_opponent.py
"""自己対局ハーネスの相手ボット HumanSLOpponent と待ちループ Waiter（偽エンジン・本物の Game）。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §3
"""

import types

import pytest

from katrain.core.constants import PRIORITY_EXTRA_AI_QUERY
from katrain.core.sgf_parser import Move
from katrain_debug.selfplay_opponent import GameAborted, HumanSLOpponent, Waiter
from tests.selfplay_fakes import FakeEngine, hp_array, make_stub, new_game


def _hp(weights):
    return lambda node, empties: hp_array(node.board_size[0], weights)


class TestWaiter:
    def test_dead_engine_aborts(self):
        engine = FakeEngine()
        engine.alive = False
        with pytest.raises(GameAborted, match="engine died"):
            Waiter(engine, timeout=5).until(lambda: False, "x")

    def test_timeout_aborts(self):
        with pytest.raises(GameAborted, match="timeout"):
            Waiter(FakeEngine(), timeout=0.05).until(lambda: False, "x")

    def test_watchdog_restart_aborts(self):
        dog = types.SimpleNamespace(restarts=0)
        waiter = Waiter(FakeEngine(), timeout=5, watchdog=dog)
        dog.restarts = 1
        with pytest.raises(GameAborted, match="restarted"):
            waiter.until(lambda: False, "x")

    def test_humansl_query_shape(self, tmp_path):
        engine = FakeEngine()
        game = new_game(make_stub(tmp_path), engine)
        analysis = Waiter(engine, timeout=5).humansl(game.current_node, "rank_3k")
        assert "humanPolicy" in analysis
        node, kw = engine.requests[-1]
        assert node is game.current_node
        assert kw["visits"] == 1 and kw["include_policy"] is True and kw["ownership"] is False
        assert kw["priority"] == PRIORITY_EXTRA_AI_QUERY and kw["time_limit"] is False
        assert kw["extra_settings"] == {"humanSLProfile": "rank_3k", "ignorePreRootHistory": False}


class TestHumanSLOpponent:
    def _play(self, tmp_path, engine, opp, moves=()):
        game = new_game(make_stub(tmp_path), engine)
        for player, gtp in moves:
            game.play(Move.from_gtp(gtp, player=player))
        waiter = Waiter(engine, timeout=5)
        node = opp.play(game, waiter)
        return game, node

    def test_plays_the_humansl_sample(self, tmp_path):
        game, node = self._play(tmp_path, FakeEngine(hp_fn=_hp({(8, 8): 1.0})), HumanSLOpponent("rank_3k", seed=1))
        assert node is game.current_node and node.move.coords == (8, 8) and node.move.player == "B"

    def test_pass_is_redrawn_when_katago_has_no_pass_candidate(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=1)
        engine = FakeEngine(hp_fn=_hp({"pass": 0.99, (8, 8): 0.01}), include_pass=False)
        game, node = self._play(tmp_path, engine, opp)
        assert not node.is_pass and node.move.coords == (8, 8)
        assert opp.stats["pass_redraws"] == 1

    def test_passes_when_pass_is_cheap_and_humansl_prefers_it(self, tmp_path):
        engine = FakeEngine(hp_fn=_hp({"pass": 0.9, (8, 8): 0.1}), include_pass=True, pass_loss=0.1)
        game, node = self._play(tmp_path, engine, HumanSLOpponent("rank_3k", seed=0, tau=0.05))
        assert node.is_pass

    def test_costly_pass_is_redrawn(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0, tau=0.05)
        engine = FakeEngine(hp_fn=_hp({"pass": 0.9, (8, 8): 0.1}), include_pass=True, pass_loss=3.0)
        game, node = self._play(tmp_path, engine, opp)
        assert not node.is_pass and opp.stats["pass_redraws"] == 1

    def test_illegal_sample_is_redrawn(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0)
        engine = FakeEngine(hp_fn=_hp({(8, 8): 0.99, (0, 8): 0.01}))
        game, node = self._play(tmp_path, engine, opp, moves=[("B", "J9")])
        assert node.move.coords == (0, 8) and node.move.player == "W"
        assert opp.stats["illegal_redraws"] == 1

    def test_max_loss_keeps_only_cheap_katago_candidates(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0, max_loss=0.2)
        engine = FakeEngine(hp_fn=_hp({(0, 0): 0.2, (1, 0): 0.8}))  # 候補 A1(0目) / B1(0.5目) / C1(1.0目)
        game, node = self._play(tmp_path, engine, opp)
        assert node.move.coords == (0, 0) and opp.stats["fallbacks"] == 0

    def test_max_loss_falls_back_to_the_best_move(self, tmp_path):
        opp = HumanSLOpponent("rank_3k", seed=0, max_loss=0.2)
        game, node = self._play(tmp_path, FakeEngine(hp_fn=_hp({(8, 8): 1.0})), opp)
        assert node.move.coords == (0, 0) and opp.stats["fallbacks"] == 1

    def test_same_seed_same_moves(self, tmp_path):
        spread = {(x, 8): 0.1 + 0.05 * x for x in range(9)}
        runs = []
        for _ in range(2):
            engine = FakeEngine(
                hp_fn=lambda node, empties: hp_array(9, {k: v for k, v in spread.items() if k in empties})
            )
            game = new_game(make_stub(tmp_path), engine)
            opp = HumanSLOpponent("rank_3k", seed=42)
            waiter = Waiter(engine, timeout=5)
            seq = []
            for _ in range(4):
                seq.append(opp.play(game, waiter).move.gtp())
            runs.append(seq)
        assert runs[0] == runs[1]
```

- [ ] **Step 3: 失敗を確かめる**

Run: `pytest tests/test_selfplay_opponent.py -q`
Expected: FAIL（collection error: `ModuleNotFoundError: No module named 'katrain_debug.selfplay_opponent'`）

- [ ] **Step 4: 実装を書く** — `katrain_debug/selfplay_opponent.py` を Write

```python
"""自己対局ハーネスの相手ボット（humanSL 1visit のサンプラー）と待ちループ。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §2（待ちループ）・§3（相手ボット）
"""

import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import random  # noqa: E402
import time  # noqa: E402

from katrain.core.ai import _area_scoring_should_pass  # noqa: E402
from katrain.core.constants import PRIORITY_EXTRA_AI_QUERY  # noqa: E402
from katrain.core.game import IllegalMoveException  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402


class GameAborted(Exception):
    """この局を aborted にする（エンジン停止・再起動・待ちのタイムアウト・AI の例外）。"""


class Waiter:
    """待ちループの共通部分（1局に1つ）。毎回 engine.check_alive() と watchdog の再起動回数を見る。

    KataGoEngine.check_alive() は死んでいても例外を投げず False を返すだけ（engine.py:242-259）なので、
    戻り値を見ないと死んだエンジンを永遠に待つ。
    """

    def __init__(self, engine, timeout=180.0, watchdog=None):
        self.engine = engine
        self.timeout = timeout
        self.watchdog = watchdog
        self.generation = watchdog.restarts if watchdog is not None else None

    def until(self, pred, what, poll=0.01):
        started = time.time()
        while not pred():
            if not self.engine.check_alive():
                raise GameAborted(f"engine died while waiting for {what}")
            if self.watchdog is not None and self.watchdog.restarts != self.generation:
                raise GameAborted(f"engine restarted while waiting for {what}")
            if time.time() - started > self.timeout:
                raise GameAborted(f"timeout ({self.timeout:.0f}s) while waiting for {what}")
            time.sleep(poll)

    def nodes(self, nodes, what="node analysis"):
        self.until(lambda: all(n.analysis_complete for n in nodes), what)

    def humansl(self, node, profile, visits=1):
        """humanSL を1本撃って結果（KataGo の JSON）を返す。ノードには書き戻さない（コールバックで受けるだけ）。"""
        out = {}

        def on_result(analysis, partial_result):
            if not partial_result:
                out["a"] = analysis

        def on_error(analysis):
            out["err"] = analysis

        self.engine.request_analysis(
            node,
            callback=on_result,
            error_callback=on_error,
            visits=visits,
            priority=PRIORITY_EXTRA_AI_QUERY,
            ownership=False,
            include_policy=True,
            time_limit=False,
            extra_settings={"humanSLProfile": profile, "ignorePreRootHistory": False},
        )
        self.until(lambda: "a" in out or "err" in out, f"humanSL {profile}")
        return out.get("a")


class HumanSLOpponent:
    """実戦の相手を模したボット（spec §3・戦略登録はしない）。

    毎手 humanSL を visits 本（既定 1）で1本撃ち、局ごとに seed を固定した random.Random で hp^(1/τ) に比例して
    引く。非合法手は捨てて引き直す。パスが引かれたら現局面の通常解析を待ち、候補のパスの pointsLost を
    _area_scoring_should_pass に渡して真ならパス、偽かパスが候補に無ければパスを外して引き直す。
    max_loss（既定 None＝OFF）は通常解析で pointsLost <= max_loss の手だけを残す（強め・慎重な相手の層）。
    """

    def __init__(self, profile, tau=1.0, seed=0, max_loss=None, visits=1):
        self.profile = profile
        self.tau = tau
        self.rng = random.Random(seed)
        self.max_loss = max_loss
        self.visits = visits
        self.stats = {"moves": 0, "pass_redraws": 0, "illegal_redraws": 0, "fallbacks": 0}

    @property
    def label(self):
        return f"humanSL:{self.profile}"

    def play(self, game, waiter):
        cn = game.current_node
        player = cn.next_player
        size = game.board_size[0]
        analysis = waiter.humansl(cn, self.profile, self.visits)
        cands = S.hp_to_cands((analysis or {}).get("humanPolicy") or [], size)
        if self.max_loss is not None and cands:
            waiter.nodes([cn], "opponent max_loss filter")
            allowed = {d["move"] for d in cn.candidate_moves if d["pointsLost"] <= self.max_loss}
            cands = [(k, p) for k, p in cands if S.key_to_gtp(k) in allowed]
        if not cands:
            self.stats["fallbacks"] += 1
            waiter.nodes([cn], "opponent fallback")
            best = cn.candidate_moves[0]["move"] if cn.candidate_moves else "pass"
            cands = [(S.gtp_to_key(best), 1.0)]

        def to_move(key):
            return Move(None, player=player) if key == "pass" else Move(key, player=player)

        def try_move(key):
            try:
                return game.play(to_move(key))
            except IllegalMoveException:
                self.stats["illegal_redraws"] += 1
                return None

        def pass_ok():
            waiter.nodes([cn], "opponent pass check")
            pass_d = next((d for d in cn.candidate_moves if d["move"] == "pass"), None)
            pass_loss = None if pass_d is None else pass_d["pointsLost"]
            ok = _area_scoring_should_pass([(to_move(k), p) for k, p in cands], pass_loss)
            if not ok:
                self.stats["pass_redraws"] += 1
            return ok

        _, node = S.selfplay_opponent_pick(cands, self.rng, self.tau, try_move, pass_ok)
        if node is None:
            node = game.play(Move(None, player=player))
        self.stats["moves"] += 1
        return node
```

- [ ] **Step 5: 通ることを確かめる**

Run: `pytest tests/test_selfplay_opponent.py tests/test_selfplay_stats.py -q`
Expected: `59 passed`

- [ ] **Step 6: コミット**

```bash
git add katrain_debug/selfplay_opponent.py tests/selfplay_fakes.py tests/test_selfplay_opponent.py
git commit -m "feat(selfplay): humanSL 1visit の相手ボットと check_alive を見る待ちループ

HumanSLOpponent は局ごとの seed の乱数で hp^(1/τ) に比例して引き、非合法手は引き直し、
パスは通常解析の pass の pointsLost と humanPolicy で _area_scoring_should_pass が
真のときだけ打つ（候補に pass が無ければ打たない）。Waiter はエンジン停止・再起動・
タイムアウトで GameAborted。テストは同期で答える偽エンジン＋本物の Game。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4a: 1局の実行とレポート（`selfplay_game.py`）

**Files:**
- Create: `katrain_debug/selfplay_game.py`
- Test: `tests/test_selfplay_runner.py`

**Interfaces:**
- Consumes: Task 2 の `selfplay_stats`（`REPORT_BINS`・`watch_prune`・`report_block`・`selfplay_move_rows`・`merge_turns`・`selfplay_game_summary`・`selfplay_should_resign`・`ai_view_lead`・`ai_view_winrate`・`move_cap`・`TARGET_RATE`・`settings_fingerprint`・`unknown_override_keys`）、Task 3 の `GameAborted`・`Waiter`・`HumanSLOpponent`、既存の `katrain_debug.cli.parse_settings`（値に `.` があれば float・なければ int・`true`/`false` は bool）と `katrain_debug.runner.STRATEGY_NAME_MAP`（runner の戦略名 → `ai:` モード）、`katrain.core.ai.STRATEGY_REGISTRY` / `AnalysisDiscardedException` / `game_report` / `generate_ai_move`（テストだけ）、`Game(katrain, engine, move_tree=None, analyze_fast=False, game_properties=None)`・`Game.play(move, ignore_ko=False, analyze=True, expected_node=None)`・`Game.write_sgf(filename, trainer_config)`（`trainer_config["eval_thresholds"]` 必須・`save_analysis` 真で KT を書く）・`KataGoEngine.on_new_game()` / `restart()` / `check_alive()`
- Produces（`selfplay_game`。Task 4b・5・6 が使う）:
  - `KEEP_LOG_MARKERS`・`STRATEGY_LOG_RE`（`^\[\w+Strategy\] `）・`start_engine(stub) -> KataGoEngine`（`allow_recovery=False`＝スタブは呼び出し不可なので復旧ポップアップで読み取りスレッドが落ちるのを防ぐ）
  - `EngineWatchdog(engine, interval=2.0)` — `.start() -> self`・`.stop()`・`.ensure_alive()`（落ちていれば再起動。ロックの下で1回だけ）・`.restarts`
  - `Arm`（dataclass: `name, strategy, mode, settings, override_items, strategy_class, settings_source`・`.fingerprint`・`.as_dict()`）・`resolve_arm(stub, name, strategy, override_items) -> Arm`（未知の戦略は KeyError・綴り間違いの上書きキーは ValueError）
  - `_ai_turn(game, ai_mode, ai_settings) -> (move | None, played_node | None, strategy)`
  - `StrategyOpponent(arm)`（`.label = "strategy:<strategy>"`・`.play(game, waiter)`）・`make_opponent(opponent_plan, spec, opponent_arm=None)`
  - `drain_logs(stub) -> [str]`（エラー・`STRATEGY_LOG_RE` に合う行・`KEEP_LOG_MARKERS` を含む行だけ）・`jsonable(obj)`・`main_line(root) -> [GameNode]`
  - `compute_reports(game, thresholds, ai_color) -> {"WATCH": {bin: {"ai": block, "opp": block}}, "STRICT": {...}}`（block は `report_block` の形）
  - `Harness(stub, engine, size, komi=7.0, rules="chinese", watchdog=None, timeout=180.0, watch_flags=False)`（config の `game/handicap` が 0 でなければ SystemExit。属性 `thresholds`・`trainer_config`（`save_analysis=True`）・`max_visits`・`.waiter()`）
  - `GameResult(record, rows, logs, game)`・`play_game(h, arm, spec, opponent, *, komi_shift=0.0, max_moves=None, hooks=(), target=None) -> GameResult`（AI・相手の例外は `GameAborted` に包んでその局を aborted）。hooks は `before_ai(game, cn, waiter) -> dict`（AI の着手前・同じ局面）/ `after_ai(game, strategy, move, waiter) -> dict`（着手後）を任意で持つオブジェクト（Task 6 が使う）。戻り値の dict はその手番の記録に足す。
  - `report_sgf(stub, engine, path, timeout=1200.0) -> {"file", "moves", "reports"}`（黒＝`"ai"`・白＝`"opp"`）

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_selfplay_runner.py` を Write

`_ai_turn` の写しは AST で `generate_ai_move` の本体と文ごとに比べる（`return a, b, strategy` を `return a, b` に戻せば一致する＝唯一の差分）。上流の `generate_ai_move` が変わったらこのテストが落ちる（spec §11「写した generate_ai_move のずれ」）。

```python
# tests/test_selfplay_runner.py
"""自己対局ハーネスの1局（katrain_debug/selfplay_game.py）。偽エンジン・本物の Game・本物の game_report。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §2・§9
"""

import ast
import inspect
import textwrap
import time
import types

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import AIStrategy, AnalysisDiscardedException, generate_ai_move
from katrain.core.constants import OUTPUT_ERROR
from katrain.core.sgf_parser import Move
from katrain_debug import selfplay_game as G
from katrain_debug.selfplay_opponent import HumanSLOpponent
from tests.selfplay_fakes import FakeEngine, make_stub, new_game


def _body(fn, drop_strategy=False):
    """関数本体（docstring を除く）を ast.unparse で正規化した文のリスト。

    drop_strategy=True なら `return a, b, strategy` を `return a, b` に戻す（_ai_turn の唯一の差分）。
    """
    func = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    body = func.body
    if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if drop_strategy:
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                last = node.value.elts[-1]
                if isinstance(last, ast.Name) and last.id == "strategy":
                    node.value.elts = node.value.elts[:-1]
    return [ast.unparse(stmt) for stmt in body]


class TestAiTurnMirrorsGenerateAiMove:
    def test_body_is_a_line_by_line_copy(self):
        """上流の generate_ai_move が変わったら落ちる（写しが黙ってずれるのを防ぐ・spec §11）。"""
        assert _body(G._ai_turn, drop_strategy=True) == _body(generate_ai_move)

    def test_same_move_and_logs_as_generate_ai_move(self, tmp_path):
        results = []
        for fn in (generate_ai_move, G._ai_turn):
            stub = make_stub(tmp_path)
            game = new_game(stub, FakeEngine())
            out = fn(game, "ai:default", {})
            results.append(
                (
                    out[0].gtp(),
                    out[1] is game.current_node,
                    [m for m, _ in stub.logs if m.startswith(("Generating move using", "Move generation complete"))],
                )
            )
        assert results[0][0] == results[1][0] == "A1"
        assert results[0][1] and results[1][1]
        assert results[0][2] == results[1][2] and len(results[0][2]) == 2

    def test_unknown_mode_falls_back_like_generate_ai_move(self, tmp_path):
        stub = make_stub(tmp_path)
        game = new_game(stub, FakeEngine())
        move, played, strategy = G._ai_turn(game, "ai:nonexistent", {})
        assert type(strategy).__name__ == "DefaultStrategy" and played is not None
        assert any(level == OUTPUT_ERROR and "not found" in msg for msg, level in stub.logs)

    def test_discarded_analysis_returns_no_node(self, tmp_path, monkeypatch):
        class Discards(AIStrategy):
            def generate_move(self):
                raise AnalysisDiscardedException("gone")

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_discard", Discards)
        game = new_game(make_stub(tmp_path), FakeEngine())
        move, played, strategy = G._ai_turn(game, "ai:test_discard", {})
        assert move is None and played is None and isinstance(strategy, Discards)

    def test_moved_position_discards_the_move(self, tmp_path, monkeypatch):
        class MovesTheBoard(AIStrategy):
            def generate_move(self):
                self.game.play(Move.from_gtp("J9", player="B"))
                return Move.from_gtp("A1", player="W"), "late"

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_moved", MovesTheBoard)
        game = new_game(make_stub(tmp_path), FakeEngine())
        move, played, _ = G._ai_turn(game, "ai:test_moved", {})
        assert move.gtp() == "A1" and played is None


class TestResolveArm:
    def test_user_settings_plus_overrides(self, tmp_path):
        stub = make_stub(tmp_path, **{"ai:enigma13plus": {"enigma13plus_max_loss": 3.0}})
        arm = G.resolve_arm(stub, "A", "enigma13plus", ["enigma13plus_max_loss=2.5", "enigma13plus_probe_extra=4"])
        assert arm.mode == "ai:enigma13plus" and arm.strategy_class == "Enigma13PlusStrategy"
        assert arm.settings == {"enigma13plus_max_loss": 2.5, "enigma13plus_probe_extra": 4}
        assert arm.settings_source == "user config"

    def test_typo_is_rejected(self, tmp_path):
        stub = make_stub(tmp_path, **{"ai:enigma13plus": {}})
        with pytest.raises(ValueError, match="enigma13plus_max_los"):
            G.resolve_arm(stub, "A", "enigma13plus", ["enigma13plus_max_los=2.5"])

    def test_unknown_strategy(self, tmp_path):
        with pytest.raises(KeyError):
            G.resolve_arm(make_stub(tmp_path), "A", "nonexistent", [])

    def test_mode_missing_from_user_config_is_flagged(self, tmp_path):
        arm = G.resolve_arm(make_stub(tmp_path), "A", "enigma13", [])
        assert arm.settings == {} and arm.settings_source.startswith("code defaults")


def _spec(ai_color="B", resign_lead=None, seed=1000):
    return {
        "index": 0,
        "seed": seed,
        "ai_color": ai_color,
        "rank": "rank_3k",
        "opp_seed": 7,
        "strategy_seed": 11,
        "resign_lead": resign_lead,
    }


class TestPlayGame:
    def _harness(self, tmp_path, engine=None):
        stub = make_stub(tmp_path)
        return G.Harness(stub, engine or FakeEngine(), size=9, komi=7.0, rules="chinese", timeout=5)

    def test_short_game_reaches_the_move_cap_and_reports_both_sides(self, tmp_path):
        h = self._harness(tmp_path)
        arm = G.resolve_arm(h.stub, "A", "default", [])
        res = G.play_game(h, arm, _spec("B"), HumanSLOpponent("rank_3k", seed=7), max_moves=8)
        rec = res.record
        assert rec["end_reason"] == "move_cap" and rec["n_moves"] == 8 and rec["error"] is None
        assert rec["own_top1"] == 1.0 and rec["opp_top1"] == 0.0  # AI は常に最善手・相手は右上
        assert rec["own_n"] == 4 and rec["opp_n"] == 4
        assert set(rec["reports"]) == {"WATCH", "STRICT"}
        assert set(rec["reports"]["WATCH"]) == {name for name, _ in G.S.REPORT_BINS}
        assert len(res.rows) == 8 and sum(r["is_ai"] for r in res.rows) == 4
        ai_rows = [r for r in res.rows if r["is_ai"]]
        assert all(r["best_at_decision"] == r["played"] for r in ai_rows)
        assert all(r["strategy_s"] >= 0 and r["decision"] is None for r in ai_rows)
        assert rec["opponent"] == "humanSL:rank_3k" and rec["opponent_stats"]["moves"] == 4
        assert h.engine.new_games == 1

    def test_ai_as_white_and_komi_shift_against_the_ai(self, tmp_path):
        h = self._harness(tmp_path)
        arm = G.resolve_arm(h.stub, "A", "default", [])
        res = G.play_game(h, arm, _spec("W"), HumanSLOpponent("rank_3k", seed=7), komi_shift=4.0, max_moves=6)
        assert res.record["komi"] == 3.0 and res.game.root.komi == 3.0
        assert res.rows[0]["player"] == "B" and not res.rows[0]["is_ai"]

    def test_no_resignation_below_the_winrate_condition(self, tmp_path):
        h = self._harness(tmp_path, FakeEngine(lead=30.0, winrate=0.6))
        arm = G.resolve_arm(h.stub, "A", "default", [])
        res = G.play_game(h, arm, _spec("B", resign_lead=10.0), HumanSLOpponent("rank_3k", seed=7), max_moves=30)
        assert res.record["end_reason"] == "move_cap"

    def test_resignation_after_two_ai_turns_past_the_start_move(self, tmp_path):
        h = self._harness(tmp_path, FakeEngine(lead=30.0, winrate=0.99))
        arm = G.resolve_arm(h.stub, "A", "default", [])
        res = G.play_game(h, arm, _spec("B", resign_lead=10.0), HumanSLOpponent("rank_3k", seed=7), max_moves=60)
        rec = res.record
        assert rec["end_reason"] == "opp_resign" and rec["result"] == "win"
        assert rec["n_moves"] == 22  # 9路の開始 19 手以降の AI 手番（20・22 手目の局面）で2回続いた
        assert res.game.end_result == "B+R"

    def test_engine_death_aborts_the_game(self, tmp_path):
        engine = FakeEngine()
        h = self._harness(tmp_path, engine)
        arm = G.resolve_arm(h.stub, "A", "default", [])

        class Dies:
            label = "dies"
            stats = {}

            def play(self, game, waiter):
                engine.alive = False
                waiter.until(lambda: False, "a reply that never comes")

        res = G.play_game(h, arm, _spec("W"), Dies(), max_moves=6)
        assert res.record["result"] == "aborted" and "engine died" in res.record["error"]

    def test_opponent_exception_aborts_the_game(self, tmp_path):
        h = self._harness(tmp_path)
        arm = G.resolve_arm(h.stub, "A", "default", [])

        class Crashes:
            label = "crashes"
            stats = {}

            def play(self, game, waiter):
                raise RuntimeError("opp bug")

        res = G.play_game(h, arm, _spec("W"), Crashes(), max_moves=6)
        assert res.record["result"] == "aborted" and "opp bug" in res.record["error"]

    def test_handicap_in_the_config_is_refused(self, tmp_path):
        stub = make_stub(tmp_path)
        stub._config["game"]["handicap"] = 2  # BaseGame は game_properties を渡しても config の置石を置く
        with pytest.raises(SystemExit, match="even games"):
            G.Harness(stub, FakeEngine(), size=9)

    def test_ai_exception_aborts_the_game(self, tmp_path, monkeypatch):
        class Crashes(AIStrategy):
            def generate_move(self):
                raise RuntimeError("bug")

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_crash", Crashes)
        h = self._harness(tmp_path)
        arm = G.Arm("A", "x", "ai:test_crash", {}, [], "Crashes", "test")
        res = G.play_game(h, arm, _spec("B"), HumanSLOpponent("rank_3k", seed=7), max_moves=6)
        assert res.record["result"] == "aborted" and "RuntimeError" in res.record["error"]

    def test_decision_info_is_recorded(self, tmp_path, monkeypatch):
        class Decides(AIStrategy):
            def generate_move(self):
                self.last_decision_info = {"tier": "iii", "kind": "free", "best": "A1", "chosen": "A1", "vloss": 0.0}
                return Move.from_gtp(self.cn.candidate_moves[0]["move"], player=self.cn.next_player), "ok"

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_decides", Decides)
        h = self._harness(tmp_path)
        arm = G.Arm("A", "x", "ai:test_decides", {}, [], "Decides", "test")
        res = G.play_game(h, arm, _spec("B"), HumanSLOpponent("rank_3k", seed=7), max_moves=4)
        assert res.rows[0]["decision"]["kind"] == "free"
        assert res.record["veil"]["tiers"] == {"iii": 2}

    def test_logs_keep_only_strategy_lines(self, tmp_path):
        stub = make_stub(tmp_path)
        stub.log("Sending query QUERY:1", 1)
        stub.log("[0.3][QUERY:1] got 3 moves", 1)
        stub.log("[Veil13Strategy] Decision: {}", 1)
        stub.log("[Enigma13PlusStrategy] board size (9, 9) is not 13x13; playing KataGo best move", 0)
        stub.log("boom", OUTPUT_ERROR)
        assert G.drain_logs(stub) == [
            "[Veil13Strategy] Decision: {}",
            "[Enigma13PlusStrategy] board size (9, 9) is not 13x13; playing KataGo best move",
            "boom",
        ]
        assert stub.logs == []


class TestReportSgf:
    def test_reports_both_colours_from_an_sgf(self, tmp_path):
        path = tmp_path / "g.sgf"
        path.write_text("(;GM[1]FF[4]SZ[9]KM[7]RU[chinese];B[ai];W[ia];B[bi])", encoding="utf-8")
        stub = make_stub(tmp_path)
        out = G.report_sgf(stub, FakeEngine(), str(path), timeout=5)
        watch = out["reports"]["WATCH"]["all"]
        assert out["moves"] == 3
        assert watch["ai"]["top1"] == 1.0 and watch["ai"]["n"] == 2  # 黒 A1・B1 はどちらも左下の最善手
        assert watch["opp"]["top1"] == 0.0 and watch["opp"]["n"] == 1


class TestWatchdog:
    def test_restarts_a_dead_engine(self):
        engine = FakeEngine()
        dog = G.EngineWatchdog(engine, interval=0.01).start()
        engine.alive = False
        started = time.time()
        while dog.restarts == 0 and time.time() - started < 2:
            time.sleep(0.01)
        dog.stop()
        assert dog.restarts >= 1 and engine.restarts >= 1 and engine.alive

    def test_ensure_alive_restarts_only_a_dead_engine(self):
        engine = FakeEngine()
        dog = G.EngineWatchdog(engine)  # start しない（execute_plan が局の前に呼ぶ経路）
        dog.ensure_alive()
        engine.alive = False
        dog.ensure_alive()
        dog.ensure_alive()
        assert dog.restarts == 1 and engine.restarts == 1 and engine.alive
```

- [ ] **Step 2: 失敗を確かめる**

Run: `pytest tests/test_selfplay_runner.py -q`
Expected: FAIL（collection error: `ImportError: cannot import name 'selfplay_game' from 'katrain_debug'`）

- [ ] **Step 3: 実装を書く** — `katrain_debug/selfplay_game.py` を Write

要点: 試作 `proto_selfplay.py`（Task 1 で `calibration-data/selfplay/` に移設・実エンジンで 13路 160手まで通った）の実証済みの部分＝stub・エンジン・`Game(stub, engine, game_properties=...)` の作り方、humanSL クエリの引数、hp 配列の添字（`(i % sx, sy - 1 - i // sx)`）、非合法手の引き直し、終局後の全ノード待ち→`game_report` をそのまま使い、試作に無かったもの（check_alive・再起動・投了の勝率条件・パスの規則・WATCH 木・記録）を足している。`_ai_turn` は `generate_ai_move` の行ごとの写し（戦略オブジェクトも返す）。`play_game` は毎局 `engine.on_new_game()`（GUI の `_do_new_game` と同じ）→ 本物の `Game` → AI の手番で経路の全ノードの解析完了を待つ → 投了判定 → hooks.before_ai → `_ai_turn` → hooks.after_ai、相手の手番は `opponent.play`。終局後に全ノードの解析完了を待ってから `compute_reports`。AI・相手の例外やエンジン停止で落ちない（その局を aborted にして返す）。`EngineWatchdog.ensure_alive` はロックの下で1回だけ再起動する（見張りのスレッドと Task 4b の `execute_plan` の両方から呼ぶ）。ログは戦略自身の `[XxxStrategy]` 行（難解系の `_log`・盤サイズ不一致の INFO）・判定と時間の行・エラーだけ残す。config の `game/handicap` が 0 でなければ `Harness` が止まる（`BaseGame` は `game_properties` を渡しても config の置石を置く）。

```python
"""自己対局ハーネスの1局（本物の Game・generate_ai_move の写し・本物の game_report）。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §2
"""

import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import dataclasses  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from katrain.core.ai import STRATEGY_REGISTRY, AnalysisDiscardedException, game_report  # noqa: E402
from katrain.core.constants import AI_DEFAULT, OUTPUT_DEBUG, OUTPUT_ERROR  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import Game, KaTrainSGF  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.cli import parse_settings  # noqa: E402
from katrain_debug.runner import STRATEGY_NAME_MAP  # noqa: E402
from katrain_debug.selfplay_opponent import GameAborted, HumanSLOpponent, Waiter  # noqa: E402

# stub.logs から残す行（戦略自身の [XxxStrategy] 行・判定ログと時間ログ・エラー）。エンジンのクエリ送受信は捨てる
KEEP_LOG_MARKERS = ("Rate:", "Decision:", "着手決定に", "Generating move using", "Move generation complete")
STRATEGY_LOG_RE = re.compile(r"^\[\w+Strategy\] ")  # 戦略自身の行（_log・盤サイズ不一致の INFO など）


def start_engine(stub):
    """KataGo を1本起動する。allow_recovery=False: スタブは呼び出し不可なので、エンジン死亡時の
    復旧ポップアップ（engine.py:163-166 の self.katrain(...)）で読み取りスレッドが TypeError で落ちるのを防ぐ。"""
    return KataGoEngine(stub, {**stub.config("engine"), "allow_recovery": False})


class EngineWatchdog:
    """エンジンの死活を見張り、落ちていたら再起動する。

    戦略の待ちループは check_alive の戻り値を見ずに回り続ける（ai.py:584-591）ので、エンジンが死ぬと
    query_generation を進める restart でしか抜けられない（raise_if_discarded → AnalysisDiscardedException）。
    ハーネスの待ちループ（Waiter）は restarts の変化を見てその局を aborted にする。execute_plan は各局の前にも
    ensure_alive を呼ぶ（落ちたエンジンのまま次の局を始めると、残りの局が全部すぐ aborted になる）。
    """

    def __init__(self, engine, interval=2.0):
        self.engine = engine
        self.interval = interval
        self.restarts = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def ensure_alive(self):
        """落ちていれば再起動する（見張りのスレッドと execute_plan の局の間の両方から呼ぶ＝ロックで1回だけ）。"""
        with self._lock:
            if not self.engine.check_alive():
                self.engine.restart()
                self.restarts += 1

    def _run(self):
        while not self._stop.wait(self.interval):
            self.ensure_alive()

    def stop(self):
        self._stop.set()


@dataclasses.dataclass
class Arm:
    """アーム＝戦略と解決済み設定（ユーザー config の節 + 上書き）。"""

    name: str
    strategy: str
    mode: str
    settings: dict
    override_items: list
    strategy_class: str
    settings_source: str

    @property
    def fingerprint(self):
        return S.settings_fingerprint(self.mode, self.settings)

    def as_dict(self):
        return {**dataclasses.asdict(self), "fingerprint": self.fingerprint}


def resolve_arm(stub, name, strategy, override_items):
    """`<名前>=<runner の戦略名>[:key=val,...]` を解決する。綴り間違いの上書きキーは ValueError。"""
    if strategy not in STRATEGY_NAME_MAP:
        raise KeyError(f"Unknown strategy '{strategy}'. Available: {', '.join(sorted(STRATEGY_NAME_MAP))}")
    mode = STRATEGY_NAME_MAP[strategy]
    user = stub.config(f"ai/{mode}")
    overrides = parse_settings(list(override_items)) or {}
    cls = STRATEGY_REGISTRY.get(mode)
    known = set()
    if cls is not None and hasattr(cls, "KEY_PREFIX") and hasattr(cls, "SETTING_DEFAULTS"):
        known = {f"{cls.KEY_PREFIX}_{k}" for k in cls.SETTING_DEFAULTS}
    unknown = S.unknown_override_keys(overrides, user, known)
    if unknown:
        raise ValueError(
            f"arm {name}: unknown setting keys {unknown} (not in the user config nor the strategy defaults)"
        )
    return Arm(
        name=name,
        strategy=strategy,
        mode=mode,
        settings={**(user or {}), **overrides},
        override_items=list(override_items),
        strategy_class=cls.__name__ if cls is not None else None,
        settings_source="user config" if user is not None else "code defaults (mode missing from the user config)",
    )


def _ai_turn(game, ai_mode, ai_settings):
    """generate_ai_move（ai.py:11678-11704）の行ごとの写し。違いは戦略オブジェクトも返すことだけ
    （判定情報 last_decision_info を読むため）。tests/test_selfplay_runner.py が AST で本体の一致を固定する。"""
    strategy_class = STRATEGY_REGISTRY.get(ai_mode)
    if strategy_class is None:
        game.katrain.log(f"AI strategy '{ai_mode}' not found, falling back to '{AI_DEFAULT}'", OUTPUT_ERROR)
        strategy_class = STRATEGY_REGISTRY[AI_DEFAULT]
    strategy = strategy_class(game, ai_settings)

    game.katrain.log(f"Generating move using {strategy.__class__.__name__} (mode {ai_mode})", OUTPUT_DEBUG)
    try:
        move, ai_thoughts = strategy.generate_move()
    except AnalysisDiscardedException as e:
        game.katrain.log(f"Discarding AI move: {e}", OUTPUT_DEBUG)
        return None, None, strategy

    played_node = game.play(move, expected_node=strategy.cn)
    if played_node is None:
        game.katrain.log(f"Discarding AI move {move.gtp()}: position changed", OUTPUT_DEBUG)
        return move, None, strategy
    played_node.ai_thoughts = ai_thoughts
    game.katrain.log(f"Move generation complete: {move.gtp()} -- {ai_thoughts}", OUTPUT_DEBUG)
    return move, played_node, strategy


class StrategyOpponent:
    """`--opponent strategy:<名前>[:k=v,...]`: 登録済み戦略を相手にする（例: 強い・フィルタつきの HumanStyle）。"""

    def __init__(self, arm):
        self.arm = arm
        self.stats = {"moves": 0}

    @property
    def label(self):
        return f"strategy:{self.arm.strategy}"

    def play(self, game, waiter):
        waiter.nodes(game.current_node.nodes_from_root, "path analysis before the opponent strategy")
        move, played, _ = _ai_turn(game, self.arm.mode, self.arm.settings)
        if played is None:
            raise GameAborted(f"opponent strategy {self.arm.strategy} discarded its move")
        self.stats["moves"] += 1
        return played


def make_opponent(opponent_plan, spec, opponent_arm=None):
    if opponent_plan["kind"] == "strategy":
        return StrategyOpponent(opponent_arm)
    return HumanSLOpponent(
        spec["rank"], tau=opponent_plan.get("tau", 1.0), seed=spec["opp_seed"], max_loss=opponent_plan.get("max_loss")
    )


def drain_logs(stub):
    """stub.logs を空にして、残す行だけ返す（stub は全レベルを溜め続ける＝長時間の実行で膨らむ）。"""
    logs, stub.logs = stub.logs, []
    return [
        str(msg)
        for msg, level in logs
        if level == OUTPUT_ERROR or STRATEGY_LOG_RE.match(str(msg)) or any(m in str(msg) for m in KEEP_LOG_MARKERS)
    ]


def jsonable(obj):
    return None if obj is None else json.loads(json.dumps(obj, default=str))


def main_line(root):
    nodes = [root]
    while nodes[-1].children:
        nodes.append(nodes[-1].children[0])
    return nodes


def compute_reports(game, thresholds, ai_color):
    """両者の report（WATCH / STRICT × 全体・GUI の3区間・校正用の3区間）。本物の game_report を呼ぶだけ。"""
    opp_color = "W" if ai_color == "B" else "B"
    out = {}
    for tree in ("WATCH", "STRICT"):
        out[tree] = {}
        for name, depth_filter in S.REPORT_BINS:
            if tree == "WATCH":
                with S.watch_prune(game):
                    sum_stats, _, ptloss = game_report(game, thresholds, depth_filter=depth_filter)
            else:
                sum_stats, _, ptloss = game_report(game, thresholds, depth_filter=depth_filter)
            out[tree][name] = {
                "ai": S.report_block(sum_stats, ptloss, ai_color),
                "opp": S.report_block(sum_stats, ptloss, opp_color),
            }
    return out


class Harness:
    """1プロセス・1エンジンで局を回す（spec §2）。盤の条件と待ちの設定を持つ。"""

    def __init__(self, stub, engine, size, komi=7.0, rules="chinese", watchdog=None, timeout=180.0, watch_flags=False):
        if stub.config("game/handicap"):
            raise SystemExit(
                "selfplay assumes even games: config game/handicap is non-zero "
                "(BaseGame places config handicap stones even with game_properties)"
            )
        self.stub = stub
        self.engine = engine
        self.size = size
        self.komi = komi
        self.rules = rules
        self.watchdog = watchdog
        self.timeout = timeout
        self.watch_flags = watch_flags
        self.thresholds = stub.config("trainer/eval_thresholds")
        self.trainer_config = {**(stub.config("trainer") or {}), "save_analysis": True}
        self.max_visits = (stub.config("engine") or {}).get("max_visits")

    def waiter(self):
        return Waiter(self.engine, self.timeout, self.watchdog)


@dataclasses.dataclass
class GameResult:
    record: dict
    rows: list
    logs: list
    game: object


def _veil_extras(arm, game):
    """韜晦のアームだけ: reserve（設定）と ledger（game._veil_state[KEY_PREFIX]["ledger"]）。他の戦略は (None, None)。"""
    cls = STRATEGY_REGISTRY.get(arm.mode)
    prefix = getattr(cls, "KEY_PREFIX", None)
    defaults = getattr(cls, "SETTING_DEFAULTS", None) or {}
    reserve = arm.settings.get(f"{prefix}_reserve", defaults.get("reserve")) if prefix else None
    ledger = ((getattr(game, "_veil_state", None) or {}).get(prefix) or {}).get("ledger") if prefix else None
    return reserve, ledger


def play_game(h, arm, spec, opponent, *, komi_shift=0.0, max_moves=None, hooks=(), target=None):
    """1局打って GameResult を返す。例外で落ちない（エンジン停止・タイムアウト・AI と相手の例外は aborted）。

    hooks: before_ai(game, cn, waiter) -> dict（AI の着手前・同じ局面）/ after_ai(game, strategy, move, waiter) -> dict
    （着手後）を持つオブジェクト。戻り値の dict はその手番の記録に足す（所要時間の集計には入らない）。
    """
    size = h.size
    ai = spec["ai_color"]
    opp_color = "W" if ai == "B" else "B"
    komi = h.komi + (komi_shift if ai == "B" else -komi_shift)  # komi_shift は AI 不利の向き
    random.seed(spec["strategy_seed"])  # 戦略側の Python 乱数（ai.py はグローバルの random を使う）
    waiter = h.waiter()
    h.engine.on_new_game()  # GUI の新規対局（__main__._do_new_game）と同じく前局の残りのクエリを捨てる
    game = Game(h.stub, h.engine, game_properties={"SZ": size, "KM": komi, "RU": h.rules})
    h.stub.game = game
    h.stub.players_info[ai].name = f"AI {arm.name} ({arm.strategy})"
    h.stub.players_info[opp_color].name = opponent.label
    if h.watch_flags:
        game.board_watch_active = True
    cap = max_moves or S.move_cap(size)
    turns, logs = [], []
    streak, end_reason, error = 0, None, None
    started = time.time()
    try:
        while True:
            cn = game.current_node
            if cn.is_pass and cn.parent is not None and cn.parent.is_pass:
                end_reason = "double_pass"
                break
            if cn.depth >= cap:
                end_reason = "move_cap"
                break
            if cn.next_player == ai:
                t0 = time.time()
                waiter.nodes(cn.nodes_from_root, "path analysis before the AI move")
                wait_s = time.time() - t0
                lead, wr = S.ai_view_lead(cn.score, ai), S.ai_view_winrate(cn.winrate, ai)
                resign, streak = S.selfplay_should_resign(cn.depth, lead, wr, streak, spec["resign_lead"], size)
                if resign:
                    end_reason = "opp_resign"
                    break
                extra = {}
                for hook in hooks:
                    if hasattr(hook, "before_ai"):
                        extra.update(hook.before_ai(game, cn, waiter))
                t1 = time.time()
                try:
                    move, played, strategy = _ai_turn(game, arm.mode, arm.settings)
                except GameAborted:
                    raise
                except Exception as e:
                    raise GameAborted(f"AI exception: {e!r}") from e
                strategy_s = time.time() - t1
                if played is None:
                    raise GameAborted("AI move discarded (analysis discarded or position changed)")
                cands = strategy.cn.candidate_moves
                turn = {
                    "depth": played.depth,
                    "wait_s": wait_s,
                    "strategy_s": strategy_s,
                    "best_at_decision": cands[0]["move"] if cands else None,
                    "played": move.gtp(),
                    "decision": jsonable(getattr(strategy, "last_decision_info", None)),
                    **extra,
                }
                for hook in hooks:
                    if hasattr(hook, "after_ai"):
                        turn.update(hook.after_ai(game, strategy, move, waiter))
                turns.append(turn)
            else:
                try:
                    opponent.play(game, waiter)
                except GameAborted:
                    raise
                except Exception as e:  # 相手の戦略のバグでも実行全体を止めない（その局だけ aborted）
                    raise GameAborted(f"opponent exception: {e!r}") from e
            logs.extend(drain_logs(h.stub))
    except GameAborted as e:
        end_reason, error = "aborted", str(e)
    logs.extend(drain_logs(h.stub))
    wall_s = time.time() - started
    nodes = main_line(game.root)
    if end_reason != "aborted":
        try:
            waiter.nodes(nodes, "final analysis of all nodes")
        except GameAborted as e:
            end_reason, error = "aborted", str(e)
    if end_reason == "opp_resign":
        game.current_node.end_state = f"{ai}+R"
    reports = compute_reports(game, h.thresholds, ai) if end_reason != "aborted" else {}
    rows = S.merge_turns(S.selfplay_move_rows(nodes[1:], ai, size, h.max_visits), turns)
    meta = {
        "arm": arm.name,
        "strategy": arm.strategy,
        "seed": spec["seed"],
        "index": spec["index"],
        "ai_color": ai,
        "rank": spec["rank"],
        "opponent": opponent.label,
        "opponent_stats": dict(getattr(opponent, "stats", {})),
        "komi": komi,
        "size": size,
        "resign_lead": spec["resign_lead"],
        "end_reason": end_reason,
        "error": error,
    }
    reserve, ledger = _veil_extras(arm, game)
    goal = S.TARGET_RATE.get(size, 0.30) if target is None else target
    record = S.selfplay_game_summary(meta, reports, rows, goal, reserve=reserve, ledger=ledger, wall_s=wall_s)
    return GameResult(record=record, rows=rows, logs=logs, game=game)


def report_sgf(stub, engine, path, timeout=1200.0):
    """実戦の保存 SGF（KT 解析つきならそれを使う＝GUI で開いたのと同じ）から両者のレポートを出す。

    本譜（children[0]）の全ノードの解析完了を待ち、compute_reports を黒＝"ai"・白＝"opp" で呼ぶ。
    """
    root = KaTrainSGF.parse_file(path)
    game = Game(stub, engine, move_tree=root)
    stub.game = game
    nodes = main_line(root)
    Waiter(engine, timeout).nodes(nodes, "analysis of the SGF main line")
    return {
        "file": path,
        "moves": len(nodes) - 1,
        "reports": compute_reports(game, stub.config("trainer/eval_thresholds"), "B"),
    }
```

- [ ] **Step 4: 通ることを確かめる**

Run: `pytest tests/test_selfplay_runner.py -q`
Expected: `22 passed`

Run: `pytest tests/test_selfplay_stats.py tests/test_selfplay_opponent.py tests/test_selfplay_runner.py -q`
Expected: `81 passed`

Run: `python -m black --line-length 120 --check katrain_debug/selfplay_game.py tests/test_selfplay_runner.py`
Expected: `2 files would be left unchanged.`

- [ ] **Step 5: 既存のファイルを触っていないことを確かめてコミット**

Run: `git status --short -- katrain katrain_debug tests`
Expected: `?? katrain_debug/selfplay_game.py` と `?? tests/test_selfplay_runner.py` の2行だけ（`M` の行が無い。計画ファイルなど docs の `??` はこのパス指定では出ない）

```bash
git add katrain_debug/selfplay_game.py tests/test_selfplay_runner.py
git commit -m "feat(selfplay): 1局の実行と本物の game_report の WATCH/STRICT 集計

本物の Game と generate_ai_move の写し _ai_turn（AST テストで本体の一致を固定）で
AI を打ち、終局後に全ノードの解析を待って game_report を WATCH（末尾のパスを除く）と
STRICT × GUI の3区間・校正用の3区間で呼ぶ。AI・相手の例外、エンジン停止、待ちの
タイムアウトはその局だけ aborted。EngineWatchdog.ensure_alive は落ちたエンジンを
ロックの下で1回だけ再起動する。config に置石があれば始めない。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4b: 実行計画・出力・再開・要約（`selfplay_run.py`）

**Files:**
- Create: `katrain_debug/selfplay_run.py`
- Test: `tests/test_selfplay_run.py`

**Interfaces:**
- Consumes: Task 2 の `selfplay_stats`（`abba_order`・`resign_pool_from_summaries`・`selfplay_summarize`・`selfplay_paired_diff`・`calibration_rank_stats`・`selfplay_pool_choice`・`CALIB_TARGETS_13`・`TARGET_RATE`・`REPORT_BINS`・`flat_row`）、Task 4a の `EngineWatchdog`（`ensure_alive`・`restarts`）・`Harness`・`make_opponent`・`play_game`（`GameResult`）・`resolve_arm`・`start_engine`、Task 3 の偽エンジン（テストだけ）
- Produces（`selfplay_run`。Task 5・6 が使う）:
  - `REPO_ROOT`・`SELFPLAY_DATA`・`RECON_DIR`・`DEFAULT_OUT_ROOT`（`<repo>/experiments/selfplay`）・`COMPARE_METRICS`
  - `default_pool_path(size)`・`load_resign_pool(size, recon_dir=RECON_DIR) -> [float]`・`git_info(path)`・`run_meta(stub)`
  - `make_plan(subcommand, arms, schedule, *, size, komi, rules="chinese", komi_shift=0.0, max_moves=None, opponent=None, resign=None, watch_flags=False, timeout=180.0, target=None, extra=None) -> plan`（キー: `subcommand, created, command, size, komi, rules, komi_shift, max_moves, watch_flags, timeout, target, arms, schedule, order, opponent, resign` と `extra` の中身。`opponent` は `{"kind": "humansl", "ranks", "tau", "max_loss", ...}` か `{"kind": "strategy", "strategy", "override_items", "ranks"}`）
  - `OutputDir(path)`（`.create(root, label)`＝既にあれば SystemExit・`.file(*parts)`・`.write_json`・`.read_json`・`.records()`・`.done_keys()`・`.drop_aborted() -> int`・`.prune_moves(done)`・`.write_game(result, trainer_config)`）
  - `fmt_num(v, spec=".3f")`・`fmt_pct(v)`・`progress_line(rec, done, total)`
  - `execute_plan(plan, out, stub, *, engine_factory=start_engine, watchdog_interval=2.0, hooks_builder=None, retry_aborted=False, log=print)`（`hooks_builder(plan, arms) -> factory(arm_name) -> [hook]`。各局の前にエンジンを起こす）
  - `plan_conditions(plan) -> dict`・`load_records(outs) -> [record]`（複数の実行を合わせる。重複・指紋や条件の違いは SystemExit）
  - `format_summary_text(summary) -> str`（ASCII）・`summarize_dir(outs, n_boot=10000, compare=None, conf=0.975, dest=None) -> (summary, text)`（`outs` は `OutputDir` かそのリスト・`compare` は `(A, B)` か `[(A, B), ...]`・`summary["compare"]` は対ごとの dict のリスト・`summary["sources"]` は実行ディレクトリのリスト）
  - `calibration_result(out, plan) -> cal`・`pool_file_content(cal) -> dict`・`format_calibration_md(cal) -> str`

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_selfplay_run.py` を Write

```python
# tests/test_selfplay_run.py
"""自己対局ハーネスの実行計画・出力・再開・要約（katrain_debug/selfplay_run.py）。偽エンジン。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §5・§6
"""

import json

from katrain_debug import selfplay_run as R
from katrain_debug import selfplay_stats as S
from katrain_debug.selfplay_game import resolve_arm
from tests.selfplay_fakes import FakeEngine, make_stub


def _plan(stub, n_seeds=2, max_moves=6):
    arm = resolve_arm(stub, "A", "default", [])
    schedule = S.selfplay_schedule(n_seeds, ["rank_3k"], 1000)
    return R.make_plan("run", [arm], schedule, size=9, komi=7.0, max_moves=max_moves, timeout=5)


def _run(plan, out, stub, engine, retry_aborted=False):
    lines = []
    R.execute_plan(
        plan,
        out,
        stub,
        engine_factory=lambda s: engine,
        watchdog_interval=None,
        retry_aborted=retry_aborted,
        log=lines.append,
    )
    return lines


class DiesInTheSecondGame(FakeEngine):
    """2局目の3本目の問い合わせで落ち、再起動されるまで返事をしない（落ちた KataGo と同じ）。"""

    game_requests = 0

    def on_new_game(self):
        super().on_new_game()
        self.game_requests = 0

    def request_analysis(self, node, callback, error_callback=None, **kwargs):
        self.game_requests += 1
        if self.new_games == 2 and self.restarts == 0 and self.game_requests >= 3:
            self.alive = False
        if self.alive:
            super().request_analysis(node, callback, error_callback, **kwargs)


class TestExecutePlan:
    def test_writes_every_output_file(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        engine = FakeEngine()
        lines = _run(_plan(stub), out, stub, engine)
        recs = out.records()
        assert [(r["arm"], r["seed"], r["ai_color"]) for r in recs] == [("A", 1000, "B"), ("A", 1001, "W")]
        assert all(r["result"] != "aborted" and r["sgf"] for r in recs)
        assert len(lines) == 2 and lines[0].startswith("[1/2] A seed=1000 ai=B vs rank_3k")
        moves = [json.loads(line) for line in open(out.file("moves.jsonl"), encoding="utf-8")]
        assert len(moves) == 12 and {m["seed"] for m in moves} == {1000, 1001}
        assert (tmp_path / "run" / "sgf" / "A_1000_B.sgf").exists()
        assert (tmp_path / "run" / "logs" / "A_1000_B.log").exists()
        assert engine.shutdowns == 1

    def test_sgf_carries_kt_analysis_and_the_result(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        _run(_plan(stub, n_seeds=1), out, stub, FakeEngine())
        sgf = (tmp_path / "run" / "sgf" / "A_1000_B.sgf").read_text(encoding="utf-8")
        assert "KT[" in sgf and "PB[AI A (default)]" in sgf and "PW[humanSL:rank_3k]" in sgf

    def test_resume_skips_finished_games_and_replays_the_unfinished(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _plan(stub)
        _run(plan, out, stub, FakeEngine())
        games = open(out.file("games.jsonl"), encoding="utf-8").read().splitlines()
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:  # 2局目の途中で落ちた状態にする
            f.write(games[0] + "\n")
        lines = _run(plan, out, stub, FakeEngine())
        assert len(lines) == 1 and "seed=1001" in lines[0]
        assert [r["seed"] for r in out.records()] == [1000, 1001]
        moves = [json.loads(line) for line in open(out.file("moves.jsonl"), encoding="utf-8")]
        assert len(moves) == 12  # 落ちた局の書きかけの行は捨ててから書き直す
        assert _run(plan, out, stub, FakeEngine()) == []

    def test_engine_death_aborts_only_the_game_in_progress(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        engine = DiesInTheSecondGame()
        _run(_plan(stub, n_seeds=4), out, stub, engine)
        results = {r["seed"]: r["result"] for r in out.records()}
        assert results[1001] == "aborted" and "engine died" in out.records()[1]["error"]
        assert all(results[s] != "aborted" for s in (1000, 1002, 1003))
        assert engine.restarts == 1  # 3局目の前に起こした（落ちたエンジンのまま次の局を始めない）

    def test_retry_aborted_replays_only_the_aborted_games(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _plan(stub, n_seeds=4)
        _run(plan, out, stub, DiesInTheSecondGame())
        assert _run(plan, out, stub, FakeEngine()) == []  # 既定の再開は aborted も完了として飛ばす
        lines = _run(plan, out, stub, FakeEngine(), retry_aborted=True)
        assert lines[0].startswith("retry: 1 aborted") and len(lines) == 2 and "seed=1001" in lines[1]
        assert sorted(r["seed"] for r in out.records()) == [1000, 1001, 1002, 1003]
        assert all(r["result"] != "aborted" for r in out.records())
        assert [json.loads(x)["seed"] for x in open(out.file("aborted.jsonl"), encoding="utf-8")] == [1001]
        moves = [json.loads(line) for line in open(out.file("moves.jsonl"), encoding="utf-8")]
        assert len(moves) == 24 and sum(m["seed"] == 1001 for m in moves) == 6

    def test_changed_settings_stop_the_resume(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        plan = _plan(stub)
        plan["arms"][0]["fingerprint"] = "0" * 16
        try:
            _run(plan, out, stub, FakeEngine())
        except SystemExit as e:
            assert "differ from run.json" in str(e)
        else:
            raise AssertionError("expected SystemExit")

    def test_plan_order_is_abba(self, tmp_path):
        stub = make_stub(tmp_path, **{"ai:policy": {}})
        arms = [resolve_arm(stub, "A", "default", []), resolve_arm(stub, "B", "policy", [])]
        plan = R.make_plan("run", arms, S.selfplay_schedule(20, ["r"], 1), size=13, komi=7.0)
        assert plan["order"][:2] == [["A", 0], ["A", 1]] and plan["order"][20] == ["B", 10]
        assert plan["target"] == 0.30 and plan["arms"][1]["fingerprint"]


class TestSummaries:
    def test_summary_files_are_ascii(self, tmp_path):
        stub = make_stub(tmp_path)
        out = R.OutputDir(tmp_path / "run")
        _run(_plan(stub), out, stub, FakeEngine())
        summary, text = R.summarize_dir(out, n_boot=200, compare=("A", "A"))
        assert summary["arms"]["A"]["games"] == 2
        assert summary["compare"][0]["diffs"]["own_top1"]["n"] == 2
        written = (tmp_path / "run" / "summary.txt").read_text(encoding="ascii")  # ASCII 以外があれば例外
        assert written == text and "paired diff A - A" in text
        assert json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))["arms"]["A"]

    def test_resign_pool_reads_report_jsons(self, tmp_path):
        for i, (ai, n, fs) in enumerate([("B", 59, 28.9), ("W", 31, -2.7)]):
            summary = {"ai": ai, "n_moves": n, "final_score": fs}
            (tmp_path / f"report_game_{i}.json").write_text(json.dumps({"summary": summary}), encoding="utf-8")
        assert R.load_resign_pool(13, str(tmp_path)) == [28.9]

    def test_calibration_markdown_and_pool_file(self, tmp_path):
        out = R.OutputDir(tmp_path / "cal")
        recs = []
        for rank, rates in (("rank_8k", [0.1, 0.12]), ("rank_3k", [0.2, 0.26]), ("rank_1d", [0.22, 0.3])):
            for i, rate in enumerate(rates):
                block = {"top1": rate, "top5": 0.5, "mean_ptloss": 1.8, "n": 30}
                reports = {"WATCH": {n: {"ai": {}, "opp": block} for n, _ in S.REPORT_BINS}}
                recs.append(
                    {
                        "arm": "calib",
                        "seed": i,
                        "rank": rank,
                        "ai_color": "B",
                        "result": "win",
                        "opp_top1": rate,
                        "opp_n": 30,
                        "own_top1": 0.55,
                        "opp_mean_ptloss": 1.8,
                        "opp_tail": {"n": 30, "ge2": 9, "ge5": 3},
                        "n_moves": 80,
                        "reports": reports,
                    }
                )
        with open(out.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in recs)
        plan = {"size": 13, "arms": [{"strategy": "enigma13plus"}], "opponent": {"tau": 1.0}}
        cal = R.calibration_result(out, plan)
        assert cal["best"]["ranks"] == ["rank_8k", "rank_3k", "rank_1d"]
        assert abs(cal["harness_drift_ai"] - (0.55 - 0.533)) < 1e-9
        md = R.format_calibration_md(cal)
        assert "| rank_3k | 2 |" in md and "実戦（目標）" in md
        pool = R.pool_file_content(cal)
        assert pool["ranks"] == ["rank_8k", "rank_3k", "rank_1d"] and pool["tau"] == 1.0
```

- [ ] **Step 2: 失敗を確かめる**

Run: `pytest tests/test_selfplay_run.py -q`
Expected: FAIL（collection error: `ImportError: cannot import name 'selfplay_run' from 'katrain_debug'`）

- [ ] **Step 3: 実装を書く** — `katrain_debug/selfplay_run.py` を Write

要点: `run.json`（計画＋実行環境）を最初に書く。1局ごとに SGF → ログ → moves.jsonl → games.jsonl の順に書いて flush（games.jsonl の行が完了の印）。再開は games.jsonl にある (arm, seed) を飛ばし、書きかけの moves.jsonl の行を捨ててから続ける。アームの解決済み設定の指紋が run.json と違えば中止（途中で config を変えた）。各局の前にエンジンの死活を見て、落ちていれば再起動する（見張りがあれば `ensure_alive`）＝落ちた局だけが aborted になり、残りの局は続く（spec §1-5・§2）。`retry_aborted` は aborted の行を `aborted.jsonl` へ移してから再開する（既定の再開は aborted も完了として飛ばす）。`OutputDir.create` は同じ名前のディレクトリがあれば止まる（同じ分・同じ label で記録が混ざるのを防ぐ）。要約は複数の実行ディレクトリを合わせられる（spec §6 停止規則の延長。同じ (arm, seed) の重複・アームの指紋や対局条件の違いは止める）。`compare` は対の列で、複数アームの run は先頭のアームとの差を全部出す（spec §5「アーム間の差の表」）。

```python
"""自己対局ハーネスの実行計画・出力ディレクトリ・再開・要約（spec §5・§6）。

run.json（計画＋実行環境）を最初に書き、1局ごとに games.jsonl / moves.jsonl に追記して flush する。
--resume は run.json の計画をそのまま使い、games.jsonl にある (arm, seed) を飛ばす（--retry-aborted なら aborted の局は
打ち直す）。要約は複数の実行（停止規則の延長 --seed-base 1020 など）を合わせて出せる。
"""

import datetime
import glob
import json
import os
import subprocess
import sys

os.environ.setdefault("KIVY_NO_ARGS", "1")

from katrain.core import ai as ai_module  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.selfplay_game import (  # noqa: E402
    EngineWatchdog,
    Harness,
    make_opponent,
    play_game,
    resolve_arm,
    start_engine,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELFPLAY_DATA = os.path.join(REPO_ROOT, "docs", "superpowers", "specs", "calibration-data", "selfplay")
RECON_DIR = os.path.join(SELFPLAY_DATA, "recon")
DEFAULT_OUT_ROOT = os.path.join(REPO_ROOT, "experiments", "selfplay")
COMPARE_METRICS = ("own_top1", "opp_top1", "own_minus_opp", "flip_moves", "win", "own_mean_ptloss", "ge6")


def default_pool_path(size):
    return os.path.join(SELFPLAY_DATA, f"opponent_pool_{size}.json")


def load_resign_pool(size, recon_dir=RECON_DIR):
    summaries = []
    for path in sorted(glob.glob(os.path.join(recon_dir, "report_game_*.json"))):
        with open(path, encoding="utf-8") as f:
            summaries.append(json.load(f)["summary"])
    return S.resign_pool_from_summaries(summaries, size)


def git_info(path):
    def git(*args):
        try:
            r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    status = git("status", "--porcelain")
    return {"head": git("rev-parse", "HEAD"), "dirty": None if status is None else bool(status)}


def run_meta(stub):
    """run.json の実行環境: エンジン設定・ai.py の場所・git HEAD と dirty（worktree の取り違え対策）。"""
    ai_dir = os.path.dirname(os.path.abspath(ai_module.__file__))
    return {
        "engine": dict(stub.config("engine") or {}),
        "ai_file": os.path.abspath(ai_module.__file__),
        "git": git_info(ai_dir),
        "python": sys.version.split()[0],
    }


def make_plan(
    subcommand,
    arms,
    schedule,
    *,
    size,
    komi,
    rules="chinese",
    komi_shift=0.0,
    max_moves=None,
    opponent=None,
    resign=None,
    watch_flags=False,
    timeout=180.0,
    target=None,
    extra=None,
):
    """実行計画（run.json の本体）。order は ABBA（10 seed ごとにアームの順を反転）。"""
    return {
        "subcommand": subcommand,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "command": list(sys.argv),
        "size": size,
        "komi": komi,
        "rules": rules,
        "komi_shift": komi_shift,
        "max_moves": max_moves,
        "watch_flags": watch_flags,
        "timeout": timeout,
        "target": S.TARGET_RATE.get(size, 0.30) if target is None else target,
        "arms": [a.as_dict() for a in arms],
        "schedule": schedule,
        "order": [list(x) for x in S.abba_order([a.name for a in arms], len(schedule))],
        "opponent": opponent or {"kind": "humansl", "ranks": sorted({s["rank"] for s in schedule}), "tau": 1.0},
        "resign": resign or {},
        **(extra or {}),
    }


class OutputDir:
    """experiments/selfplay/<YYYYMMDD_HHMM>_<label>/（gitignore 済み）。"""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        for sub in ("sgf", "logs"):
            os.makedirs(os.path.join(self.path, sub), exist_ok=True)

    @classmethod
    def create(cls, root, label):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        path = os.path.join(root, f"{stamp}_{label}")
        if os.path.exists(path):  # 同じ分に同じ label で始めると前の games.jsonl と混ざる
            raise SystemExit(f"{path} already exists: use another --label, or --resume {path}")
        return cls(path)

    def file(self, *parts):
        return os.path.join(self.path, *parts)

    def write_json(self, name, obj):
        with open(self.file(name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)

    def read_json(self, name):
        with open(self.file(name), encoding="utf-8") as f:
            return json.load(f)

    def records(self):
        path = self.file("games.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def done_keys(self):
        return {(r["arm"], r["seed"]) for r in self.records()}

    def drop_aborted(self):
        """--retry-aborted: games.jsonl から aborted の行を aborted.jsonl へ移す（次の再開で打ち直す）。移した数を返す。"""
        records = self.records()
        aborted = [r for r in records if r.get("result") == "aborted"]
        if not aborted:
            return 0
        with open(self.file("aborted.jsonl"), "a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in aborted)
        with open(self.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in records if r not in aborted)
        return len(aborted)

    def prune_moves(self, done):
        """再開時: games.jsonl に無い局（落ちた局の書きかけ）の moves.jsonl の行を捨てる。"""
        path = self.file("moves.jsonl")
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            keep = [line for line in f if line.strip() and tuple(json.loads(line)[k] for k in ("arm", "seed")) in done]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(keep)

    def write_game(self, result, trainer_config):
        """SGF（KT 解析つき）・ログ・moves.jsonl・games.jsonl の順に書く（games.jsonl の行が完了の印）。"""
        rec = result.record
        key = f"{rec['arm']}_{rec['seed']}_{rec['ai_color']}"
        sgf_path = self.file("sgf", key + ".sgf")
        try:
            result.game.write_sgf(sgf_path, trainer_config=trainer_config)
            rec["sgf"] = os.path.relpath(sgf_path, self.path)
        except Exception as e:  # SGF が書けなくても集計は残す
            rec["sgf"] = None
            rec["sgf_error"] = repr(e)
        with open(self.file("logs", key + ".log"), "w", encoding="utf-8") as f:
            f.write("\n".join(result.logs) + "\n")
        with open(self.file("moves.jsonl"), "a", encoding="utf-8") as f:
            for row in result.rows:
                line = {"arm": rec["arm"], "seed": rec["seed"], **S.flat_row(row)}
                f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
            f.flush()
        with open(self.file("games.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            f.flush()


def fmt_num(v, spec=".3f"):
    return "-" if v is None else format(v, spec)


def progress_line(rec, done, total):
    return (
        f"[{done}/{total}] {rec['arm']} seed={rec['seed']} ai={rec['ai_color']} vs {rec['rank']}: "
        f"{rec['result']} ({rec['end_reason']}) moves={rec['n_moves']} own={fmt_num(rec['own_top1'])} "
        f"opp={fmt_num(rec['opp_top1'])} lead={fmt_num(rec['final_lead'], '+.1f')} {fmt_num(rec['wall_s'], '.0f')}s"
        + (f" error={rec['error']}" if rec.get("error") else "")
    )


def execute_plan(
    plan,
    out,
    stub,
    *,
    engine_factory=start_engine,
    watchdog_interval=2.0,
    hooks_builder=None,
    retry_aborted=False,
    log=print,
):
    """計画の未完了の局を順に打つ。アームの解決済み設定が計画時と違えば中止（config を途中で変えた）。

    各局の前にエンジンの死活を見て、落ちていれば再起動する（spec §2: 落ちた局だけ aborted にして続行）。
    hooks_builder(plan, arms) -> factory(arm_name) -> [hook]（hp 監査・影判定。selfplay_hooks.make_hooks_factory）。
    retry_aborted: 再開のとき aborted の局も打ち直す（OutputDir.drop_aborted）。
    """
    arms = {}
    for entry in plan["arms"]:
        arm = resolve_arm(stub, entry["name"], entry["strategy"], entry["override_items"])
        if arm.fingerprint != entry["fingerprint"]:
            raise SystemExit(
                f"arm {entry['name']}: resolved settings differ from run.json (config edited?). Start a new run."
            )
        arms[arm.name] = arm
    opponent_arm = None
    if plan["opponent"]["kind"] == "strategy":
        o = plan["opponent"]
        opponent_arm = resolve_arm(stub, "opponent", o["strategy"], o["override_items"])
    hooks_for = hooks_builder(plan, arms) if hooks_builder else (lambda name: [])
    if retry_aborted:
        n = out.drop_aborted()
        if n:
            log(f"retry: {n} aborted game(s) moved to aborted.jsonl and replayed")
    done = out.done_keys()
    out.prune_moves(done)
    engine = engine_factory(stub)
    watchdog = EngineWatchdog(engine, watchdog_interval).start() if watchdog_interval else None
    h = Harness(stub, engine, plan["size"], plan["komi"], plan["rules"], watchdog, plan["timeout"], plan["watch_flags"])
    try:
        for arm_name, idx in plan["order"]:
            spec = plan["schedule"][idx]
            if (arm_name, spec["seed"]) in done:
                continue
            if watchdog is not None:  # 前の局でエンジンが落ちていたら、次の局の前に起こす
                watchdog.ensure_alive()
            elif not engine.check_alive():
                engine.restart()
            result = play_game(
                h,
                arms[arm_name],
                spec,
                make_opponent(plan["opponent"], spec, opponent_arm),
                komi_shift=plan["komi_shift"],
                max_moves=plan["max_moves"],
                hooks=hooks_for(arm_name),
                target=plan["target"],
            )
            out.write_game(result, h.trainer_config)
            done.add((arm_name, spec["seed"]))
            log(progress_line(result.record, len(done), len(plan["order"])))
    finally:
        if watchdog is not None:
            watchdog.stop()
        engine.shutdown(finish=False)


# ---- 要約（summary.txt は cp932 の端末でも読めるよう ASCII のみ）----
def fmt_pct(v):
    return "-" if v is None else f"{100 * v:.1f}%"


def _ci(ci):
    return "-" if not ci or ci[0] is None else f"[{100 * ci[0]:.1f},{100 * ci[1]:.1f}]"


def format_summary_text(summary):
    lines = ["# selfplay summary (own = strategy, opp = opponent; WATCH tree; rates in %)", ""]
    header = (
        f"{'group':<32} {'n':>3} {'W-L-J':>8} {'win CI':>13} {'own mean':>8} {'own CI':>13} {'opp mean':>8} "
        f"{'own-opp':>7} {'P(o<p)':>6} {'P<=T+5':>6} {'P<15':>6} {'loss o/p':>9} {'>=6':>4} {'flip':>4} "
        f"{'lead med':>8} {'moves':>5} {'hp dev':>6} {'p95 s':>5}"
    )
    for title, groups in (("arms", summary["arms"]), ("arm|rank|color", summary["strata"])):
        lines += [f"## {title}", header]
        for name, s in groups.items():
            played = s["games"] - s["aborted"]
            lines.append(
                f"{name[:32]:<32} {played:>3} {s['wins']:>2}-{s['losses']}-{s['jigo']:<3} {_ci(s['win_ci']):>13} "
                f"{fmt_pct(s['own_top1_mean']):>8} {_ci(s['own_top1_mean_ci']):>13} {fmt_pct(s['opp_top1_mean']):>8} "
                f"{fmt_pct(s['own_minus_opp_mean']):>7} {fmt_pct(s['p_own_lt_opp']):>6} {fmt_pct(s['p_own_le_target_plus5']):>6} "
                f"{fmt_pct(s['p_own_lt_floor']):>6} "
                f"{fmt_num(s['own_mean_ptloss'], '.2f')}/{fmt_num(s['opp_mean_ptloss'], '.2f'):>4} "
                f"{fmt_num(s['ge6_per_game'], '.2f'):>4} {fmt_num(s['flip_per_game'], '.2f'):>4} "
                f"{fmt_num(s['final_lead_median'], '+.1f'):>8} {fmt_num(s['moves_median'], '.0f'):>5} "
                f"{fmt_pct(s['hp_dev_median']):>6} {fmt_num(s['strategy_p95'], '.2f'):>5}"
            )
        lines.append("")
    lines.append("## own top1 by bin (pooled)")
    for name, s in summary["arms"].items():
        bins = " ".join(f"{b}={fmt_pct(v)}" for b, v in s["own_top1_by_bin"].items())
        lines.append(f"{name}: {bins}")
    for compare in summary.get("compare") or []:
        lines += ["", f"## paired diff {compare['a']} - {compare['b']} (same seed; conf {compare['conf']})"]
        for m, d in compare["diffs"].items():
            lines.append(
                f"{m:<16} n={d['n']:>3} mean={fmt_num(d['mean'], '+.4f')} t={fmt_num(d['t_ci'][0], '+.4f')}.."
                f"{fmt_num(d['t_ci'][1], '+.4f')} boot={fmt_num(d['boot_ci'][0], '+.4f')}..{fmt_num(d['boot_ci'][1], '+.4f')} "
                f"wilcoxon_p={fmt_num(d['wilcoxon_p'], '.4f')} verdict(+-3pt)={d['verdict']}"
            )
    if len(summary.get("sources") or []) > 1:
        lines += ["", "## sources"] + summary["sources"]
    text = "\n".join(lines) + "\n"
    return text.encode("ascii", "replace").decode("ascii")


def plan_conditions(plan):
    """対局条件（別々の実行の games.jsonl を合わせて集計してよいかの判定）。アームの設定は指紋で別に見る。"""
    opp = plan.get("opponent") or {}
    resign = plan.get("resign") or {}
    return {
        **{k: plan.get(k) for k in ("size", "komi", "komi_shift", "rules", "max_moves", "watch_flags", "target")},
        "opponent": {k: opp.get(k) for k in ("kind", "ranks", "tau", "max_loss", "strategy", "override_items")},
        "resign": {k: resign.get(k) for k in ("no_resign", "range")},
    }


def load_records(outs):
    """複数の実行の games.jsonl を合わせる（spec §6 停止規則の延長: 20 ペアの後の --seed-base 1020 の実行など）。

    同じ (arm, seed) が2回現れる・同じ名前のアームの設定の指紋が違う・対局条件が違うときは止まる（run.json の無い
    ディレクトリは指紋と条件の突き合わせを飛ばす）。
    """
    records, seen, prints, conditions = [], {}, {}, None
    for out in outs:
        if os.path.exists(out.file("run.json")):
            plan = out.read_json("run.json")
            for arm in plan["arms"]:
                if prints.setdefault(arm["name"], arm["fingerprint"]) != arm["fingerprint"]:
                    raise SystemExit(f"arm {arm['name']}: settings differ between the run directories ({out.path})")
            cond = plan_conditions(plan)
            if conditions is not None and cond != conditions:
                raise SystemExit(f"game conditions differ between the run directories ({out.path})")
            conditions = cond
        for r in out.records():
            key = (r["arm"], r["seed"])
            if key in seen:
                raise SystemExit(f"arm {r['arm']} seed {r['seed']} appears in both {seen[key]} and {out.path}")
            seen[key] = out.path
            records.append(r)
    return records


def summarize_dir(outs, n_boot=10000, compare=None, conf=0.975, dest=None):
    """summary.txt（ASCII）/ summary.json を dest（既定: 最初の実行）に書く。

    outs は OutputDir かそのリスト（複数なら load_records で合わせる）。compare は (A, B) か [(A, B), ...]
    （同じ seed の対の差 A - B。既定の区間 97.5%＝2回見る停止規則）。
    """
    outs = list(outs) if isinstance(outs, (list, tuple)) else [outs]
    dest = dest or outs[0]
    records = load_records(outs)
    summary = S.selfplay_summarize(records, n_boot)
    summary["sources"] = [o.path for o in outs]
    pairs = [tuple(compare)] if compare and isinstance(compare[0], str) else [tuple(c) for c in compare or []]
    if pairs:
        summary["compare"] = []
        for a, b in pairs:
            ra = [r for r in records if r["arm"] == a]
            rb = [r for r in records if r["arm"] == b]
            diffs = {m: S.selfplay_paired_diff(ra, rb, m, n_boot, conf=conf) for m in COMPARE_METRICS}
            summary["compare"].append({"a": a, "b": b, "conf": conf, "diffs": diffs})
    dest.write_json("summary.json", summary)
    text = format_summary_text(summary)
    with open(dest.file("summary.txt"), "w", encoding="ascii", errors="replace") as f:
        f.write(text)
    return summary, text


# ---- 校正（spec §3 calibrate）----
def calibration_result(out, plan):
    records = out.records()
    per_rank = S.calibration_rank_stats(records)
    choices = S.selfplay_pool_choice(per_rank) if plan["size"] == 13 and len(per_rank) >= 3 else []
    best = choices[0] if choices else None
    return {
        "run_dir": out.path,
        "strategy": plan["arms"][0]["strategy"],
        "size": plan["size"],
        "tau": plan["opponent"]["tau"],
        "targets": S.CALIB_TARGETS_13,
        "per_rank": per_rank,
        "choices": choices[:5],
        "best": best,
        "harness_drift_ai": (
            None if best is None or best["own_mean"] is None else best["own_mean"] - S.CALIB_TARGETS_13["ai_mean"]
        ),
    }


def pool_file_content(cal):
    """opponent_pool_<size>.json の中身（run の --opp-pool が ranks と tau を読む）。"""
    best = cal["best"]
    return {
        "board_size": cal["size"],
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_run": cal["run_dir"],
        "strategy": cal["strategy"],
        "ranks": best["ranks"],
        "tau": cal["tau"],
        "fit": best,
        "targets": cal["targets"],
        "per_rank": cal["per_rank"],
        "harness_drift_ai": cal["harness_drift_ai"],
    }


def format_calibration_md(cal):
    t = cal["targets"]
    lines = [
        f"# 自己対局ハーネスの相手ボット校正（{cal['size']}路・{cal['strategy']}・tau {cal['tau']}）",
        "",
        f"実行: `{cal['run_dir']}`",
        "",
        "## 段位ごと（相手＝humanSL・WATCH 木・局単位）",
        "",
        "| 段位 | 局数 | 相手 一致率 局平均 | 局間 SD | 損失/手 | >=2目 | >=5目 | 序盤 一致/損失 | 中盤 | 終盤 | AI 一致率 | 手数中央値 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, s in cal["per_rank"].items():
        b = s["bins"]
        cells = [
            f"{fmt_pct(b[n]['opp_top1'])} / {fmt_num(b[n]['opp_loss'], '.2f')}"
            for n in ("cal_opening", "cal_middle", "cal_endgame")
        ]
        lines.append(
            f"| {rank} | {s['games']} | {fmt_pct(s['opp_mean'])} | {fmt_num(100 * s['opp_sd'], '.1f')}pt | "
            f"{fmt_num(s['opp_loss'], '.2f')} | {fmt_pct(s['opp_ge2'])} | {fmt_pct(s['opp_ge5'])} | {cells[0]} | {cells[1]} | "
            f"{cells[2]} | {fmt_pct(s['own_mean'])} | {fmt_num(s['moves_median'], '.0f')} |"
        )
    b = t["bins"]
    lines += [
        f"| **実戦（目標）** | 16/18 | {fmt_pct(t['opp_mean'])} | {100 * t['opp_sd']:.1f}pt | {t['opp_loss']:.2f} | "
        f"{fmt_pct(t['opp_ge2'])} | {fmt_pct(t['opp_ge5'])} | "
        + " | ".join(
            f"{fmt_pct(b[n]['opp_top1'])} / {b[n]['opp_loss']:.2f}"
            for n in ("cal_opening", "cal_middle", "cal_endgame")
        )
        + f" | {fmt_pct(t['ai_mean'])} | {t['moves_median']} |",
        "",
        "## 3段位プールの候補（スコア = 局平均・局間 SD・損失の目標からのずれの二乗和。小さいほど良い）",
        "",
        "| 順位 | 段位 | 局平均 | 局間 SD | 損失/手 | 中盤 一致/損失 | AI 一致率 | スコア |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(cal["choices"], 1):
        mid = c["bins"]["cal_middle"]
        lines.append(
            f"| {i} | {', '.join(c['ranks'])} | {fmt_pct(c['opp_mean'])} | {fmt_num(100 * c['opp_sd'], '.1f')}pt | "
            f"{fmt_num(c['opp_loss'], '.2f')} | {fmt_pct(mid['opp_top1'])} / {fmt_num(mid['opp_loss'], '.2f')} | "
            f"{fmt_pct(c['own_mean'])} | {c['score']:.2f} |"
        )
    drift = cal["harness_drift_ai"]
    lines += [
        "",
        "## ハーネスと実戦のずれ（AI 側）",
        "",
        f"選んだプールでの AI 一致率 - 実戦の難解＋ 局平均 {fmt_pct(t['ai_mean'])} = "
        f"{'-' if drift is None else f'{100 * drift:+.1f}pt'}（実戦の予測はこの差を引いて読む）",
        "",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: 通ることを確かめる**

Run: `pytest tests/test_selfplay_run.py -q`
Expected: `10 passed`

Run: `pytest tests/test_selfplay_stats.py tests/test_selfplay_opponent.py tests/test_selfplay_runner.py tests/test_selfplay_run.py -q`
Expected: `91 passed`

Run: `python -m black --line-length 120 --check katrain_debug/selfplay_run.py tests/test_selfplay_run.py`
Expected: `2 files would be left unchanged.`

- [ ] **Step 5: 既存のファイルを触っていないことを確かめてコミット**

Run: `git status --short -- katrain katrain_debug tests`
Expected: `?? katrain_debug/selfplay_run.py` と `?? tests/test_selfplay_run.py` の2行だけ（`M` の行が無い）

```bash
git add katrain_debug/selfplay_run.py tests/test_selfplay_run.py
git commit -m "feat(selfplay): 実行計画・出力・再開・要約

run.json（解決済み設定の指紋・ai.py・git HEAD）、games.jsonl / moves.jsonl を1局
ごとに追記、KT 解析つき SGF。各局の前に落ちたエンジンを再起動して、落ちた局だけを
aborted にして続ける。--resume 用に完了した (arm, seed) を飛ばし（retry_aborted で
aborted も打ち直す）、設定が変わっていたら止まる。要約は複数の実行を合わせて
アーム間の対の差を出す（停止規則の延長）。校正の集計と md。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: CLI（`run` / `calibrate` / `summarize` / `report-sgf`）

**Files:**
- Create: `katrain_debug/selfplay.py`
- Test: `tests/test_selfplay_cli.py`

**Interfaces:**
- Consumes: Task 2〜4b のすべて（`schedule_balance_warning`・`summarize_dir(outs, ..., compare=[(A, B), ...], dest=)`・`execute_plan(..., retry_aborted=)` を含む）。`python -m katrain_debug.selfplay` は `katrain_debug/__main__.py` を通らない＝このファイルの先頭で `os.environ["KIVY_NO_ARGS"] = "1"` を katrain の import より前に置く。
- Produces:
  - `safe_print(text)`（ASCII に落として出す）・`katago_processes() -> [str]`（`tasklist` で起動中の `katago.exe`）・`ensure_no_katago(args)`（見つけたら SystemExit。`--allow-concurrent` で解除）
  - `setup_errors()`（コンテキストマネージャ: 設定の解決の KeyError / ValueError だけを `error: ...` の SystemExit にする。対局中の例外は traceback のまま上げる＝`main` は例外を握りつぶさない）
  - `default_config_path()`・`make_stub(config_path)`・`opponent_plan(args, size) -> dict`・`resign_plan(args, size) -> {"no_resign", "range", "pool", "start_move", "source"}`
  - `_plan_run(args) -> (stub, plan)`・`_plan_calibrate(args) -> (stub, plan)`（Task 6 の Edit が `_plan_run` の中を書き換える）
  - `cmd_run(args)`（2アーム以上なら先頭のアームとの対の差も要約に出す＝spec §5「アーム間の差の表」）・`cmd_calibrate(args)`・`cmd_summarize(args)`・`format_report_sgf(result)`・`cmd_report_sgf(args)`・`build_parser()`・`main(argv=None)`
  - テストは `CLI.start_engine` と `CLI.katago_processes` を monkeypatch で差し替える（`cmd_*` は呼んだ時点のモジュール属性を引く）。
  - サブコマンドと主なフラグ（spec §8）:
    - `run --arm NAME=STRATEGY[:key=val,...]`（複数）`--size 13 --pairs 20 --seed-base 1000 [--opp-pool FILE | --ranks r1,r2] [--tau T] [--opp-max-loss X] [--opponent humansl | strategy:NAME[:k=v,...]] [--komi K] [--komi-shift 4] [--rules R] [--no-resign] [--resign-lead LO:HI] [--max-moves N] [--watch-flags] [--timeout 180] [--label L] [--out-root DIR] [--config PATH] [--resume DIR] [--retry-aborted] [--boot 10000] [--allow-concurrent]`
    - `calibrate --size 13 --strategy enigma13plus --ranks rank_8k,rank_5k,rank_3k,rank_1k,rank_1d,rank_3d --games 8 [--tau 1.0] [--write-pool FILE]`（＋ run と共通のフラグ）
    - `summarize DIR [DIR ...] [--compare A B] [--out DIR] [--boot N] [--conf 0.975]`（複数の DIR は合わせて集計＝spec §6 停止規則の延長。例: `run ... --seed-base 1000 --pairs 20 --label ab` の後に `run ... --seed-base 1020 --pairs 20 --label ab-ext` を走らせ `summarize DIR_ab DIR_ab-ext --compare A B`。同じ (arm, seed)・アームの指紋や対局条件が違う DIR は止まる。書き先は既定で最初の DIR）
    - `report-sgf FILE [--timeout 1200] [--config PATH] [--json] [--allow-concurrent]`
  - seed の数が 2 × 段位数 の倍数でなければ `warning: ... is unbalanced (8/6/6 games) ...` を出す（止めない）。
  - 相手の既定: `--ranks` も `--opp-pool` も無ければ `calibration-data/selfplay/opponent_pool_<size>.json`（Task 10 で作る）。どれも無ければ SystemExit（`no opponent ranks`）。投了の既定は `calibration-data/selfplay/recon/` の実戦の標本（無ければ SystemExit）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_selfplay_cli.py` を Write

```python
# tests/test_selfplay_cli.py
"""自己対局ハーネスの CLI（python -m katrain_debug.selfplay）。KataGo の代わりに偽エンジンを差し込む。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §8
"""

import json
import os

import pytest

from katrain_debug import selfplay as CLI
from tests.selfplay_fakes import FakeEngine, make_stub


@pytest.fixture
def env(tmp_path, monkeypatch):
    make_stub(tmp_path, **{"ai:policy": {}})  # tmp_path/config.json を書く
    monkeypatch.setattr(CLI, "start_engine", lambda stub: FakeEngine())
    monkeypatch.setattr(CLI, "katago_processes", lambda: [])
    return {"config": str(tmp_path / "config.json"), "out": str(tmp_path / "out"), "tmp": tmp_path}


def _run_args(env, *extra):
    return [
        "run",
        "--size",
        "9",
        "--pairs",
        "2",
        "--ranks",
        "rank_3k",
        "--no-resign",
        "--max-moves",
        "6",
        "--timeout",
        "5",
        "--boot",
        "100",
        "--config",
        env["config"],
        "--out-root",
        env["out"],
        "--label",
        "t",
        *extra,
    ]


def _only_dir(root):
    dirs = os.listdir(root)
    assert len(dirs) == 1
    return os.path.join(root, dirs[0])


class TestRun:
    def test_end_to_end_with_resume_and_summarize(self, env, capsys):
        CLI.main(_run_args(env, "--arm", "A=default"))
        run_dir = _only_dir(env["out"])
        assert run_dir.endswith("_t")
        plan = json.load(open(os.path.join(run_dir, "run.json"), encoding="utf-8"))
        assert plan["arms"][0]["mode"] == "ai:default" and plan["opponent"]["ranks"] == ["rank_3k"]
        assert plan["git"] is not None and plan["ai_file"].endswith("ai.py") and "engine" in plan
        assert plan["resign"]["no_resign"] is True and all(s["resign_lead"] is None for s in plan["schedule"])
        games = open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8").read().splitlines()
        assert len(games) == 2
        out = capsys.readouterr().out
        assert "output:" in out and "# selfplay summary" in out

        CLI.main(["run", "--resume", run_dir, "--boot", "100"])
        assert len(open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8").read().splitlines()) == 2

        CLI.main(["summarize", run_dir, "--compare", "A", "A", "--boot", "100"])
        assert "paired diff A - A" in capsys.readouterr().out

    def test_refuses_to_run_next_to_a_live_katago(self, env, monkeypatch):
        monkeypatch.setattr(CLI, "katago_processes", lambda: ["katago.exe  1234 Console  1  900,000 K"])
        with pytest.raises(SystemExit, match="already running"):
            CLI.main(_run_args(env, "--arm", "A=default"))
        CLI.main(_run_args(env, "--arm", "A=default", "--allow-concurrent"))

    def test_null_experiment_is_refused(self, env):
        with pytest.raises(SystemExit, match="null experiment"):
            CLI.main(_run_args(env, "--arm", "A=default", "--arm", "B=default"))

    def test_typo_in_an_override_is_refused(self, env):
        with pytest.raises(SystemExit, match="unknown setting keys"):
            CLI.main(_run_args(env, "--arm", "A=enigma13plus:enigma13plus_max_los=2.0"))

    def test_missing_ranks_is_refused(self, env, monkeypatch):
        monkeypatch.setattr(CLI.R, "default_pool_path", lambda size: os.path.join(env["out"], "missing.json"))
        args = [a for a in _run_args(env, "--arm", "A=default") if a not in ("--ranks", "rank_3k")]
        with pytest.raises(SystemExit, match="no opponent ranks"):
            CLI.main(args)

    def test_opponent_pool_file_sets_ranks_and_tau(self, env):
        pool = env["tmp"] / "pool.json"
        pool.write_text(json.dumps({"ranks": ["rank_1k", "rank_1d"], "tau": 0.9}), encoding="utf-8")
        args = [a for a in _run_args(env, "--arm", "A=default") if a not in ("--ranks", "rank_3k")]
        CLI.main(args + ["--opp-pool", str(pool)])
        plan = json.load(open(os.path.join(_only_dir(env["out"]), "run.json"), encoding="utf-8"))
        assert plan["opponent"]["tau"] == 0.9 and [s["rank"] for s in plan["schedule"]] == ["rank_1k", "rank_1k"]

    def test_strategy_opponent(self, env):
        CLI.main(_run_args(env, "--arm", "A=default", "--opponent", "strategy:default"))
        recs = [json.loads(x) for x in open(os.path.join(_only_dir(env["out"]), "games.jsonl"), encoding="utf-8")]
        assert all(r["opponent"] == "strategy:default" and r["opp_top1"] == 1.0 for r in recs)


class TestCalibrate:
    def test_writes_calibration_files_and_the_pool(self, env):
        pool = env["tmp"] / "opponent_pool_13.json"
        CLI.main(
            [
                "calibrate",
                "--size",
                "13",
                "--strategy",
                "default",
                "--ranks",
                "rank_8k,rank_3k,rank_1d",
                "--games",
                "2",
                "--no-resign",
                "--max-moves",
                "6",
                "--timeout",
                "5",
                "--boot",
                "100",
                "--config",
                env["config"],
                "--out-root",
                env["out"],
                "--write-pool",
                str(pool),
            ]
        )
        run_dir = _only_dir(env["out"])
        assert run_dir.endswith("_calib-default")
        cal = json.load(open(os.path.join(run_dir, "calibration.json"), encoding="utf-8"))
        assert set(cal["per_rank"]) == {"rank_8k", "rank_3k", "rank_1d"}
        assert all(s["games"] == 2 for s in cal["per_rank"].values())
        assert os.path.exists(os.path.join(run_dir, "calibration.md"))
        written = json.loads(pool.read_text(encoding="utf-8"))
        assert sorted(written["ranks"]) == ["rank_1d", "rank_3k", "rank_8k"] and written["tau"] == 1.0


class TestSummarize:
    def test_two_runs_are_summarized_together(self, env, capsys):
        """停止規則の延長（spec §6）: --seed-base をずらした2本目の実行を1本目と合わせて対の差を出す。"""
        CLI.main(_run_args(env, "--arm", "A=default"))
        CLI.main(_run_args(env, "--arm", "A=default", "--seed-base", "1002", "--label", "ext"))
        dirs = [os.path.join(env["out"], d) for d in sorted(os.listdir(env["out"]), key=lambda d: d.endswith("_ext"))]
        capsys.readouterr()
        CLI.main(["summarize", *dirs, "--compare", "A", "A", "--boot", "100"])
        summary = json.load(open(os.path.join(dirs[0], "summary.json"), encoding="utf-8"))
        assert summary["arms"]["A"]["games"] == 4 and summary["compare"][0]["diffs"]["own_top1"]["n"] == 4
        assert "## sources" in capsys.readouterr().out
        with pytest.raises(SystemExit, match="appears in both"):
            CLI.main(["summarize", dirs[0], dirs[0], "--boot", "100"])


class TestReportSgf:
    def test_report_of_a_saved_game_equals_the_game_record(self, env, capsys, monkeypatch):
        CLI.main(_run_args(env, "--arm", "A=default"))
        run_dir = _only_dir(env["out"])
        rec = json.loads(open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8").readline())
        capsys.readouterr()
        replay = FakeEngine(lead=-5.0)  # 読み直しで再解析されたら数字が変わる
        monkeypatch.setattr(CLI, "start_engine", lambda stub: replay)
        CLI.main(["report-sgf", os.path.join(run_dir, rec["sgf"]), "--config", env["config"], "--json"])
        result = json.loads(capsys.readouterr().out)
        assert replay.requests == []  # SGF の KT（解析）をそのまま使った＝再解析なし
        watch = result["reports"]["WATCH"]["all"]
        black, white = (watch["ai"], watch["opp"]) if rec["ai_color"] == "B" else (watch["opp"], watch["ai"])
        assert black["top1"] == rec["own_top1"] and white["top1"] == rec["opp_top1"]
        assert black["n"] == rec["own_n"] and white["n"] == rec["opp_n"]
```

- [ ] **Step 2: 失敗を確かめる**

Run: `pytest tests/test_selfplay_cli.py -q`
Expected: FAIL（collection error: `ImportError: cannot import name 'selfplay' from 'katrain_debug'`）

- [ ] **Step 3: 実装を書く** — `katrain_debug/selfplay.py` を Write

```python
"""自己対局ハーネスの CLI（戦略 vs humanSL ボットを無人で N 局打たせ、両者の終局レポートの一致率を集計する）。

    python -m katrain_debug.selfplay run --arm A=enigma13plus --arm B=enigma13plus:enigma13plus_max_loss=2.0
        --size 13 --pairs 20 [--opp-pool FILE | --ranks rank_3k,rank_1k,rank_1d] [--komi-shift 4] [--no-resign]
        [--label NAME] [--resume DIR]
    python -m katrain_debug.selfplay calibrate --size 13 --strategy enigma13plus
        --ranks rank_8k,rank_5k,rank_3k,rank_1k,rank_1d,rank_3d --games 8 [--write-pool FILE]
    python -m katrain_debug.selfplay summarize DIR [DIR ...] [--compare A B]
    python -m katrain_debug.selfplay report-sgf FILE.sgf

（実際のコマンドは1行で打つ。）設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md。
**実戦中の KaTrain と同時に走らせない**（§7）。出力は experiments/selfplay/<YYYYMMDD_HHMM>_<label>/（gitignore 済み）。
"""

import os

os.environ["KIVY_NO_ARGS"] = "1"

import argparse  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402

from katrain.core.constants import DATA_FOLDER  # noqa: E402
from katrain_debug import selfplay_run as R  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.selfplay_game import report_sgf, resolve_arm, start_engine  # noqa: E402

DEFAULT_CALIB_RANKS = "rank_8k,rank_5k,rank_3k,rank_1k,rank_1d,rank_3d"


def safe_print(text):
    """cp932 の端末でも落ちないよう ASCII に落として出す（戦略の例外文などに日本語が混ざりうる）。"""
    print(str(text).encode("ascii", "replace").decode("ascii"), flush=True)


def katago_processes():
    """起動中の katago.exe（KaTrain の実戦など）の tasklist の行。tasklist が無い環境では空。"""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq katago.exe", "/NH"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line for line in (r.stdout or "").splitlines() if "katago.exe" in line.lower()]


def ensure_no_katago(args):
    """実戦中の KaTrain と GPU を取り合わない（spec §7: 実戦の AI が遅くなり maxTime に当たる）。"""
    if getattr(args, "allow_concurrent", False):
        return
    if katago_processes():
        raise SystemExit(
            "KataGo is already running (KaTrain in a live game?). Stop it first, or pass --allow-concurrent."
        )


@contextlib.contextmanager
def setup_errors():
    """設定の解決（--arm・--opponent・--resign-lead・プール）の KeyError / ValueError だけを `error: ...` で止める。

    対局中の例外は traceback のまま上げる（実行時のバグを利用者向けの1行に丸めない）。
    """
    try:
        yield
    except (KeyError, ValueError) as e:
        raise SystemExit(f"error: {e}") from e


def default_config_path():
    return os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))


def make_stub(config_path):
    return KaTrainStub(config_path or default_config_path(), debug_level=0, quiet=True)


def opponent_plan(args, size):
    """相手の設定。humansl は --ranks か --opp-pool（無ければ calibration-data/selfplay/opponent_pool_<size>.json）。"""
    if args.opponent != "humansl":
        if not args.opponent.startswith("strategy:"):
            raise SystemExit(f"--opponent must be humansl or strategy:NAME[:k=v,...]: {args.opponent!r}")
        _, strategy, items = S.parse_arm("opponent=" + args.opponent[len("strategy:") :])
        return {"kind": "strategy", "strategy": strategy, "override_items": items, "ranks": [f"strategy:{strategy}"]}
    pool_file = args.opp_pool
    if pool_file is None and not args.ranks and os.path.exists(R.default_pool_path(size)):
        pool_file = R.default_pool_path(size)
    pool = None
    if pool_file:
        if not os.path.exists(pool_file):
            raise SystemExit(f"opponent pool not found: {pool_file}")
        with open(pool_file, encoding="utf-8") as f:
            pool = json.load(f)
    ranks = args.ranks.split(",") if args.ranks else (pool or {}).get("ranks")
    if not ranks:
        raise SystemExit("no opponent ranks: pass --ranks or --opp-pool (or run calibrate --write-pool first)")
    tau = args.tau if args.tau is not None else (pool or {}).get("tau", 1.0)
    return {
        "kind": "humansl",
        "ranks": ranks,
        "tau": tau,
        "max_loss": args.opp_max_loss,
        "pool_file": pool_file,
        "pool": pool,
    }


def resign_plan(args, size):
    """投了モデル: --no-resign / --resign-lead LO:HI / 実戦 13路の投了局の最終リード（既定）。"""
    start = S.resign_start_move(size)
    if args.no_resign:
        return {"no_resign": True, "range": None, "pool": [], "start_move": start, "source": None}
    if args.resign_lead:
        return {
            "no_resign": False,
            "range": list(S.parse_range(args.resign_lead)),
            "pool": [],
            "start_move": start,
            "source": "--resign-lead",
        }
    pool = R.load_resign_pool(size)
    if not pool:
        raise SystemExit(f"no resign data in {R.RECON_DIR}: pass --resign-lead LO:HI or --no-resign")
    return {"no_resign": False, "range": None, "pool": pool, "start_move": start, "source": R.RECON_DIR}


def _schedule(n_seeds, ranks, args, resign):
    return S.selfplay_schedule(
        n_seeds,
        ranks,
        args.seed_base,
        resign_leads=resign["pool"],
        resign_range=resign["range"],
        no_resign=resign["no_resign"],
    )


def _warn_if_unbalanced(plan):
    warning = S.schedule_balance_warning(plan["schedule"], plan["opponent"]["ranks"])
    if warning:
        safe_print(warning)


def _new_output(args, stub, plan, label):
    out = R.OutputDir.create(args.out_root, label)
    out.write_json("run.json", {**plan, **R.run_meta(stub)})
    safe_print(f"output: {out.path}")
    return out


def _resume(args):
    out = R.OutputDir(args.resume)
    plan = out.read_json("run.json")
    safe_print(f"resume: {out.path}")
    return out, plan, make_stub(plan["config_path"])


def _plan_run(args):
    """run の新しい計画（アームの解決・null ガード・相手・投了・日程）。-> (stub, plan)"""
    if not args.arm:
        raise SystemExit("run needs at least one --arm NAME=STRATEGY[:key=val,...] (or --resume DIR)")
    stub = make_stub(args.config)
    arms = [resolve_arm(stub, *S.parse_arm(text)) for text in args.arm]
    if len({a.name for a in arms}) != len(arms):
        raise SystemExit("arm names must be unique")
    same = S.arms_null_guard([a.as_dict() for a in arms])
    if same:
        raise SystemExit(f"null experiment: arms {same} resolve to identical settings")
    opponent = opponent_plan(args, args.size)
    if opponent["kind"] == "strategy":  # 相手の戦略名と上書きキーの綴りも開始前に確かめる
        resolve_arm(stub, "opponent", opponent["strategy"], opponent["override_items"])
    resign = resign_plan(args, args.size)
    plan = R.make_plan(
        "run",
        arms,
        _schedule(args.pairs, opponent["ranks"], args, resign),
        size=args.size,
        komi=args.komi if args.komi is not None else float(stub.config("game/komi")),
        rules=args.rules or stub.config("game/rules"),
        komi_shift=args.komi_shift,
        max_moves=args.max_moves,
        opponent=opponent,
        resign=resign,
        watch_flags=args.watch_flags,
        timeout=args.timeout,
        extra={"config_path": args.config or default_config_path()},
    )
    return stub, plan


def cmd_run(args):
    if args.resume:
        out, plan, stub = _resume(args)
    else:
        with setup_errors():
            stub, plan = _plan_run(args)
        _warn_if_unbalanced(plan)
        out = _new_output(args, stub, plan, args.label or "run")
    R.execute_plan(plan, out, stub, engine_factory=start_engine, retry_aborted=args.retry_aborted, log=safe_print)
    names = [a["name"] for a in plan["arms"]]
    _, text = R.summarize_dir(out, args.boot, compare=[(names[0], n) for n in names[1:]])  # アーム間の差（spec §5）
    safe_print(text)


def _plan_calibrate(args):
    """calibrate の計画（1アーム × 段位ごとに --games 局・色は交互）。-> (stub, plan)"""
    stub = make_stub(args.config)
    arm = resolve_arm(stub, "calib", args.strategy, [])
    ranks = args.ranks.split(",")
    resign = resign_plan(args, args.size)
    opponent = {
        "kind": "humansl",
        "ranks": ranks,
        "tau": 1.0 if args.tau is None else args.tau,
        "max_loss": args.opp_max_loss,
    }
    plan = R.make_plan(
        "calibrate",
        [arm],
        _schedule(args.games * len(ranks), ranks, args, resign),
        size=args.size,
        komi=args.komi if args.komi is not None else float(stub.config("game/komi")),
        rules=args.rules or stub.config("game/rules"),
        max_moves=args.max_moves,
        opponent=opponent,
        resign=resign,
        timeout=args.timeout,
        extra={"config_path": args.config or default_config_path(), "write_pool": args.write_pool},
    )
    return stub, plan


def cmd_calibrate(args):
    if args.resume:
        out, plan, stub = _resume(args)
    else:
        with setup_errors():
            stub, plan = _plan_calibrate(args)
        _warn_if_unbalanced(plan)
        out = _new_output(args, stub, plan, args.label or f"calib-{args.strategy}")
    R.execute_plan(plan, out, stub, engine_factory=start_engine, retry_aborted=args.retry_aborted, log=safe_print)
    R.summarize_dir(out, args.boot)
    cal = R.calibration_result(out, plan)
    out.write_json("calibration.json", cal)
    with open(out.file("calibration.md"), "w", encoding="utf-8") as f:
        f.write(R.format_calibration_md(cal))
    for rank, s in cal["per_rank"].items():
        safe_print(
            f"{rank}: games={s['games']} opp mean={R.fmt_pct(s['opp_mean'])} sd={R.fmt_num(100 * s['opp_sd'], '.1f')}pt "
            f"loss={R.fmt_num(s['opp_loss'], '.2f')} >=2={R.fmt_pct(s['opp_ge2'])} >=5={R.fmt_pct(s['opp_ge5'])} "
            f"own={R.fmt_pct(s['own_mean'])} moves={R.fmt_num(s['moves_median'], '.0f')}"
        )
    best = cal["best"]
    if best is not None:
        safe_print(
            f"best pool: {best['ranks']} mean={R.fmt_pct(best['opp_mean'])} sd={R.fmt_num(100 * best['opp_sd'], '.1f')}pt "
            f"loss={R.fmt_num(best['opp_loss'], '.2f')} drift_ai={R.fmt_num(cal['harness_drift_ai'], '+.3f')}"
        )
    if plan.get("write_pool") and best is not None:
        with open(plan["write_pool"], "w", encoding="utf-8") as f:
            json.dump(R.pool_file_content(cal), f, ensure_ascii=False, indent=1)
        safe_print(f"pool written: {plan['write_pool']}")
    safe_print(f"calibration: {out.file('calibration.md')}")


def cmd_summarize(args):
    """1つ以上の実行を合わせて集計する（停止規則の延長＝--seed-base をずらした実行を後ろに並べる）。"""
    for d in args.dirs:
        if not os.path.exists(os.path.join(d, "games.jsonl")):
            raise SystemExit(f"{d}: games.jsonl not found")
    outs = [R.OutputDir(d) for d in args.dirs]
    dest = R.OutputDir(args.out) if args.out else None
    compare = tuple(args.compare) if args.compare else None
    _, text = R.summarize_dir(outs, args.boot, compare, args.conf, dest=dest)
    safe_print(text)


def format_report_sgf(result):
    lines = [f"{result['file']}: {result['moves']} moves  (top1 / top5 / mean_ptloss / n)"]
    for tree in ("WATCH", "STRICT"):
        lines.append(f"## {tree}")
        for name, _ in S.REPORT_BINS:
            block = result["reports"][tree][name]
            cells = []
            for label, key in (("B", "ai"), ("W", "opp")):
                b = block[key]
                cells.append(
                    f"{label} {R.fmt_pct(b['top1'])} / {R.fmt_pct(b['top5'])} / {R.fmt_num(b['mean_ptloss'], '.2f')} / {b['n']}"
                )
            lines.append(f"{name:<12} " + "   ".join(cells))
    return "\n".join(lines)


def cmd_report_sgf(args):
    stub = make_stub(args.config)
    engine = start_engine(stub)
    try:
        result = report_sgf(stub, engine, args.file, timeout=args.timeout)
    finally:
        engine.shutdown(finish=False)
    if args.json:
        safe_print(json.dumps(result, indent=1))
    else:
        safe_print(format_report_sgf(result))


def _add_common(p):
    p.add_argument("--size", type=int, default=13, help="盤サイズ（9/13/19）")
    p.add_argument("--seed-base", type=int, default=1000, help="seed の起点（局 i の seed = seed-base + i）")
    p.add_argument("--komi", type=float, default=None, help="コミ（既定: config の game/komi）")
    p.add_argument("--rules", default=None, help="ルール（既定: config の game/rules）")
    p.add_argument("--no-resign", action="store_true", help="相手は投了しない（必須の感度アーム）")
    p.add_argument(
        "--resign-lead", default=None, metavar="LO:HI", help="投了閾値 R を一様分布で引く（既定: 実戦の分布）"
    )
    p.add_argument("--tau", type=float, default=None, help="相手の温度 τ（hp^(1/τ)。既定: プールの値か 1.0）")
    p.add_argument("--opp-max-loss", type=float, default=None, help="相手の悪手フィルタ（目。既定 OFF）")
    p.add_argument("--max-moves", type=int, default=None, help="手数上限（既定: 9路 120・13路 250・19路 400）")
    p.add_argument("--timeout", type=float, default=180.0, help="1回の待ちの上限秒（超えたらその局を aborted）")
    p.add_argument("--label", default=None, help="出力ディレクトリ名の末尾")
    p.add_argument("--out-root", default=R.DEFAULT_OUT_ROOT, help="出力の親ディレクトリ")
    p.add_argument("--config", default=None, help="config.json（既定: ~/.katrain/config.json）")
    p.add_argument("--resume", default=None, metavar="DIR", help="落ちた実行を run.json の計画のまま再開")
    p.add_argument(
        "--retry-aborted", action="store_true", help="--resume で aborted の局も打ち直す（行は aborted.jsonl へ移す）"
    )
    p.add_argument("--boot", type=int, default=10000, help="bootstrap の回数")
    p.add_argument("--allow-concurrent", action="store_true", help="他の KataGo が動いていても走らせる（非推奨）")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="katrain_debug.selfplay", description="自己対局ハーネス（戦略 vs humanSL ボット）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="アームごとに N 局打って集計する")
    run.add_argument("--arm", action="append", default=[], metavar="NAME=STRATEGY[:key=val,...]")
    run.add_argument("--pairs", type=int, default=20, help="seed の数（全アームが同じ seed を打つ）")
    run.add_argument("--opp-pool", default=None, help="相手の段位プール（calibrate --write-pool の出力）")
    run.add_argument("--ranks", default=None, help="相手の段位（カンマ区切り。プールより優先）")
    run.add_argument("--opponent", default="humansl", help="humansl か strategy:NAME[:key=val,...]")
    run.add_argument("--komi-shift", type=float, default=0.0, help="AI 不利にずらすコミ（接戦ストレス層）")
    run.add_argument("--watch-flags", action="store_true", help="game.board_watch_active を立てる（監視専用の分岐）")
    _add_common(run)
    cal = sub.add_parser("calibrate", help="相手ボットの段位ごとの統計を取り、3段位プールを選ぶ")
    cal.add_argument("--strategy", default="enigma13plus", help="校正に使う戦略（runner の戦略名）")
    cal.add_argument("--ranks", default=DEFAULT_CALIB_RANKS)
    cal.add_argument("--games", type=int, default=8, help="段位ごとの局数（色は交互）")
    cal.add_argument("--write-pool", default=None, help="選んだプールを書き出すパス（opponent_pool_13.json）")
    _add_common(cal)
    summ = sub.add_parser("summarize", help="games.jsonl を集計し直す（複数の実行を合わせられる）")
    summ.add_argument("dirs", nargs="+", metavar="DIR", help="実行ディレクトリ（延長の実行を後ろに並べる）")
    summ.add_argument("--out", default=None, metavar="DIR", help="summary.* の書き先（既定: 最初の DIR）")
    summ.add_argument("--compare", nargs=2, metavar=("A", "B"), help="同じ seed の対の差 A - B")
    summ.add_argument("--boot", type=int, default=10000)
    summ.add_argument("--conf", type=float, default=0.975, help="対の差の区間の信頼度（2回見る停止規則で 0.975）")
    rep = sub.add_parser("report-sgf", help="保存 SGF から両者のレポート一致率を出す")
    rep.add_argument("file")
    rep.add_argument("--timeout", type=float, default=1200.0)
    rep.add_argument("--config", default=None)
    rep.add_argument("--json", action="store_true")
    rep.add_argument("--allow-concurrent", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd in ("run", "calibrate", "report-sgf"):
        ensure_no_katago(args)
    handlers = {"run": cmd_run, "calibrate": cmd_calibrate, "summarize": cmd_summarize, "report-sgf": cmd_report_sgf}
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 通ることを確かめる**

Run: `pytest tests/test_selfplay_cli.py -q`
Expected: `10 passed`

Run: `pytest tests/test_selfplay_stats.py tests/test_selfplay_opponent.py tests/test_selfplay_runner.py tests/test_selfplay_run.py tests/test_selfplay_cli.py -q`
Expected: `101 passed`

Run: `python -m black --line-length 120 --check katrain_debug/selfplay.py tests/test_selfplay_cli.py`
Expected: `2 files would be left unchanged.`

- [ ] **Step 5: ヘルプが KataGo なしで出ることを確かめる**

Run: `python -m katrain_debug.selfplay --help`
Expected: `usage: katrain_debug.selfplay [-h] {run,calibrate,summarize,report-sgf} ...`（exit 0）

- [ ] **Step 6: コミット**

```bash
git add katrain_debug/selfplay.py tests/test_selfplay_cli.py
git commit -m "feat(selfplay): 自己対局ハーネスの CLI（run / calibrate / summarize / report-sgf）

python -m katrain_debug.selfplay。アームは <名前>=<戦略>[:key=val,...]、null 実験と
綴り間違いの上書きは開始前に止まる（設定の解決の誤りだけを1行に丸め、対局中の例外は
traceback を残す）。相手は --ranks か校正済みプール、投了は実戦の標本か
--resign-lead / --no-resign。層の局数が揃わない seed 数は警告。複数アームの run は
アーム間の対の差も出し、summarize は複数の実行を合わせる（停止規則の延長）。
--retry-aborted で aborted の局を打ち直す。calibrate は段位ごとの統計と 3段位
プールの候補・ハーネスと実戦のずれを calibration.json / .md に出し、--write-pool で
書き出す。report-sgf は保存 SGF から両者のレポートを出す。起動中の katago.exe が
あれば止まる。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: hp 監査（`--hp-audit`）と影判定（`--shadow`）

**Files:**
- Create: `katrain_debug/selfplay_hooks.py`
- Modify: `katrain_debug/selfplay.py`（Task 5 で作った新規ファイル＝black 済み。Edit ツールで5か所。フックの black は差分を出さない）
- Test: `tests/test_selfplay_hooks.py`

**Interfaces:**
- Consumes: `play_game(..., hooks=[...])` の hook 規約（Task 4a）、`Waiter.humansl`（Task 3）、`selfplay_stats.hp_audit_values`（Task 2）、`selfplay_game.jsonable`、`execute_plan(..., hooks_builder=...)`（Task 4b）、Task 5 の `_plan_run` / `cmd_run` の本文（Step 4 の Edit の old_string）
- Produces:
  - `SHADOW_FIXED_ATTRS`・`SHADOW_ATTR_PREFIXES`（`_veil`・`_enigma`・`_mimic`・`_parity9`・`_jigo`）・`SHADOW_DEFAULTS`・`shadow_state_keys(names) -> [str]`
  - `run_shadow(game, arm, store) -> {"arm", "move", "vloss", "decision", "secs"}`（`vloss` は B の手の通常解析の pointsLost＝同じ局面でのコスト。失敗時は `"move": None, "error"`。`AnalysisDiscardedException` だけは `GameAborted`）
  - `ShadowHook(arm)`（`before_ai`・B の sticky 状態は `game._shadow_state[arm.name]` に持つ＝局ごとに自動でリセット）・`HpAuditHook(profile="rank_9d")`（`after_ai`・戻り値 `{"hp_played", "hp_best", "hp_rank"}`）
  - `make_hooks_factory(plan, arms) -> factory(arm_name) -> [hook]`（`plan["shadow"]` のアーム自身には影を付けない）
  - CLI: `run --shadow ARM --hp-audit PROFILE`。plan に `shadow`・`hp_audit` が入る（`--resume` でも引き継ぐ）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_selfplay_hooks.py` を Write

```python
# tests/test_selfplay_hooks.py
"""自己対局ハーネスの hp 監査と影判定（katrain_debug/selfplay_hooks.py）。偽エンジン・本物の Game。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §4・§6
"""

import json
import os
import random

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import AIStrategy
from katrain.core.sgf_parser import Move
from katrain_debug import selfplay as CLI
from katrain_debug import selfplay_game as G
from katrain_debug import selfplay_hooks as H
from katrain_debug.selfplay_opponent import HumanSLOpponent, Waiter
from tests.selfplay_fakes import FakeEngine, make_stub, new_game


class _StickyProbe(AIStrategy):
    """影の B: game に sticky な状態を積み、グローバル乱数を消費し、最善手を返す。"""

    def generate_move(self):
        state = dict(getattr(self.game, "_veil_state", None) or {})
        state["B"] = state.get("B", 0) + 1
        self.game._veil_state = state
        self.game.board_watch_probe_warm = True
        random.random()
        self.last_decision_info = {"kind": "free", "n": state["B"]}
        return Move.from_gtp(self.cn.candidate_moves[0]["move"], player=self.cn.next_player), "probe"


@pytest.fixture
def probe_mode(monkeypatch):
    monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_probe", _StickyProbe)
    return G.Arm("B", "x", "ai:test_probe", {}, [], "_StickyProbe", "test")


class TestShadow:
    def test_state_keys(self):
        names = ["_veil_state", "_enigma13plus_endgame", "_mimic13_endgame", "board_watch_probe_warm", "_lock", "root"]
        assert H.shadow_state_keys(names) == [
            "_enigma13plus_endgame",
            "_mimic13_endgame",
            "_veil_state",
            "board_watch_probe_warm",
        ]

    def test_arm_a_state_is_untouched_and_b_keeps_its_own(self, tmp_path, probe_mode):
        game = new_game(make_stub(tmp_path), FakeEngine())
        game._veil_state = {"A": 1}
        before_node = game.current_node
        store = {}
        random.seed(3)
        rng_before = random.getstate()
        first = H.run_shadow(game, probe_mode, store)
        second = H.run_shadow(game, probe_mode, store)
        assert first["move"] == "A1" and first["decision"] == {"kind": "free", "n": 1} and first["vloss"] == 0.0
        assert second["decision"]["n"] == 2  # B の sticky 状態は影の store で持ち続ける
        assert game._veil_state == {"A": 1} and game.board_watch_probe_warm is False
        assert store["_veil_state"] == {"B": 2} and store["board_watch_probe_warm"] is True
        assert random.getstate() == rng_before
        assert game.current_node is before_node and not before_node.children

    def test_shadow_failure_does_not_stop_the_game(self, tmp_path, monkeypatch):
        class Crashes(AIStrategy):
            def generate_move(self):
                raise RuntimeError("shadow bug")

        monkeypatch.setitem(ai_module.STRATEGY_REGISTRY, "ai:test_shadow_crash", Crashes)
        game = new_game(make_stub(tmp_path), FakeEngine())
        out = H.run_shadow(game, G.Arm("B", "x", "ai:test_shadow_crash", {}, [], "Crashes", "t"), {})
        assert out["move"] is None and "shadow bug" in out["error"]

    def test_shadow_hook_in_a_game(self, tmp_path, probe_mode):
        stub = make_stub(tmp_path)
        h = G.Harness(stub, FakeEngine(), size=9, timeout=5)
        arm_a = G.resolve_arm(stub, "A", "default", [])
        spec = {"index": 0, "seed": 1, "ai_color": "B", "rank": "rank_3k", "opp_seed": 7, "strategy_seed": 11}
        spec["resign_lead"] = None
        opponent = HumanSLOpponent("rank_3k", seed=7)
        res = G.play_game(h, arm_a, spec, opponent, max_moves=6, hooks=[H.ShadowHook(probe_mode)])
        ai_rows = [r for r in res.rows if r["is_ai"]]
        assert [r["shadow"]["decision"]["n"] for r in ai_rows] == [1, 2, 3]
        assert all(r["played"] == r["best_at_decision"] for r in ai_rows)
        assert res.record["shadow"]["n"] == 3 and res.record["shadow"]["same_as_played"] == 1.0
        assert not hasattr(res.game, "_veil_state")  # A（DefaultStrategy）は状態を持たない＝B の状態が漏れていない


class TestHpAudit:
    def test_records_hp_of_the_played_and_best_moves(self, tmp_path):
        engine = FakeEngine()
        stub = make_stub(tmp_path)
        game = new_game(stub, engine)
        move, played, strategy = G._ai_turn(game, "ai:default", {})
        out = H.HpAuditHook("rank_9d").after_ai(game, strategy, move, Waiter(engine, 5))
        assert out == {"hp_played": 0.0, "hp_best": 0.0, "hp_rank": 3}  # 既定の偽 humanSL は右上2点だけ
        node, kw = engine.requests[-1]
        assert node is strategy.cn and kw["visits"] == 1
        assert kw["extra_settings"]["humanSLProfile"] == "rank_9d"

    def test_factory_skips_shadowing_the_arm_itself(self, probe_mode):
        arms = {"A": probe_mode, "B": probe_mode}
        factory = H.make_hooks_factory({"shadow": "B", "hp_audit": "rank_9d"}, arms)
        assert [type(x).__name__ for x in factory("A")] == ["ShadowHook", "HpAuditHook"]
        assert [type(x).__name__ for x in factory("B")] == ["HpAuditHook"]
        assert H.make_hooks_factory({}, arms)("A") == []


class TestCli:
    def _args(self, tmp_path, *extra):
        return [
            "run",
            "--arm",
            "A=default",
            "--arm",
            "B=default:dummy=2",
            "--size",
            "9",
            "--pairs",
            "1",
            "--ranks",
            "rank_3k",
            "--no-resign",
            "--max-moves",
            "4",
            "--timeout",
            "5",
            "--boot",
            "100",
            "--config",
            str(tmp_path / "config.json"),
            "--out-root",
            str(tmp_path / "out"),
            *extra,
        ]

    def test_shadow_and_hp_audit_flags(self, tmp_path, monkeypatch, capsys):
        make_stub(tmp_path, **{"ai:default": {"dummy": 1}})
        monkeypatch.setattr(CLI, "start_engine", lambda stub: FakeEngine())
        monkeypatch.setattr(CLI, "katago_processes", lambda: [])
        CLI.main(self._args(tmp_path, "--shadow", "B", "--hp-audit", "rank_9d"))
        assert "paired diff A - B" in capsys.readouterr().out  # 2アームの run はアーム間の差の表も出す
        run_dir = os.path.join(tmp_path / "out", os.listdir(tmp_path / "out")[0])
        plan = json.load(open(os.path.join(run_dir, "run.json"), encoding="utf-8"))
        assert plan["shadow"] == "B" and plan["hp_audit"] == "rank_9d"
        recs = {r["arm"]: r for r in map(json.loads, open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8"))}
        assert recs["A"]["shadow"]["arm"] == "B" and recs["B"]["shadow"] is None
        moves = [json.loads(x) for x in open(os.path.join(run_dir, "moves.jsonl"), encoding="utf-8")]
        assert all(m["hp_rank"] is not None for m in moves if m["is_ai"])

    def test_unknown_shadow_arm_is_refused(self, tmp_path, monkeypatch):
        make_stub(tmp_path, **{"ai:default": {"dummy": 1}})
        monkeypatch.setattr(CLI, "katago_processes", lambda: [])
        with pytest.raises(SystemExit, match="--shadow C"):
            CLI.main(self._args(tmp_path, "--shadow", "C"))
```

- [ ] **Step 2: 失敗を確かめる**

Run: `pytest tests/test_selfplay_hooks.py -q`
Expected: FAIL（collection error: `ImportError: cannot import name 'selfplay_hooks' from 'katrain_debug'`）

- [ ] **Step 3: 実装を書く** — `katrain_debug/selfplay_hooks.py` を Write

```python
"""自己対局ハーネスの追加の計器: hp 監査（spec §4）と影判定（spec §6 --shadow）。

どちらも play_game の hooks（before_ai / after_ai）で、所要時間（strategy_s）の集計には入らない。
"""

import os
import random
import time

os.environ.setdefault("KIVY_NO_ARGS", "1")

from katrain.core.ai import STRATEGY_REGISTRY, AnalysisDiscardedException  # noqa: E402
from katrain.core.constants import AI_DEFAULT  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.selfplay_game import jsonable  # noqa: E402
from katrain_debug.selfplay_opponent import GameAborted  # noqa: E402

# 戦略が game に載せる sticky な状態（影判定で A と B を入れ替える対象）。固定名＋接頭辞で拾う
SHADOW_FIXED_ATTRS = (
    "_veil_state",
    "_enigma_ponder",
    "_enigma_ponder_gen",
    "_enigma_ponder_owner",
    "board_watch_probe_warm",
)
SHADOW_ATTR_PREFIXES = ("_veil", "_enigma", "_mimic", "_parity9", "_jigo")
SHADOW_DEFAULTS = {"board_watch_probe_warm": False}  # Game.__init__ が持つ初期値（B の初回用）


def shadow_state_keys(names):
    return sorted({n for n in names if n in SHADOW_FIXED_ATTRS or n.startswith(SHADOW_ATTR_PREFIXES)})


def run_shadow(game, arm, store):
    """アーム B（arm）の戦略を同じ局面で実行し、選んだ手・そのコスト（通常解析の pointsLost）・判定情報だけ返す（打たない）。

    store は B 専用の影の状態（game._shadow_state[arm.name]・局をまたがない）。B の実行前に A の sticky 属性を
    退避して B の状態を載せ、実行後に B の状態を store へ書き戻してから A の属性とグローバル乱数を戻す。
    追加クエリ（_run_query / _probe_children）は結果をノードに書き戻さないので本譜の解析は汚れない。
    """
    names = list(vars(game))
    keys = shadow_state_keys(names + list(store))
    saved = {k: getattr(game, k) for k in keys if k in vars(game)}
    rng_state = random.getstate()
    for k in keys:
        if k in vars(game):
            delattr(game, k)
    for k, v in {**SHADOW_DEFAULTS, **store}.items():
        setattr(game, k, v)
    started = time.time()
    try:
        strategy_class = STRATEGY_REGISTRY.get(arm.mode) or STRATEGY_REGISTRY[AI_DEFAULT]
        strategy = strategy_class(game, arm.settings)
        move, _ = strategy.generate_move()
        cands = game.current_node.candidate_moves  # 打たないので current_node は A と同じ局面のまま
        result = {
            "arm": arm.name,
            "move": move.gtp(),
            "vloss": next((d["pointsLost"] for d in cands if d["move"] == move.gtp()), None),  # B の手のコスト
            "decision": jsonable(getattr(strategy, "last_decision_info", None)),
            "secs": time.time() - started,
        }
    except AnalysisDiscardedException as e:
        raise GameAborted(f"shadow {arm.name}: analysis discarded ({e})") from e
    except Exception as e:  # 影の失敗で本番の局を止めない
        result = {"arm": arm.name, "move": None, "error": repr(e), "secs": time.time() - started}
    finally:
        after = shadow_state_keys(list(vars(game)))
        store.clear()
        store.update({k: getattr(game, k) for k in after})
        for k in after:
            delattr(game, k)
        for k, v in saved.items():
            setattr(game, k, v)
        random.setstate(rng_state)
    return result


class ShadowHook:
    """AI（アーム A）の各手番の前に、同じ局面でアーム B の戦略を走らせて記録する。"""

    def __init__(self, arm):
        self.arm = arm

    def before_ai(self, game, cn, waiter):
        stores = game.__dict__.setdefault("_shadow_state", {})
        return {"shadow": run_shadow(game, self.arm, stores.setdefault(self.arm.name, {}))}


class HpAuditHook:
    """AI の全着手の親局面に humanSL（既定 rank_9d）を 1visit で撃ち、選んだ手と最善手の hp・順位を記録する。"""

    def __init__(self, profile="rank_9d"):
        self.profile = profile

    def after_ai(self, game, strategy, move, waiter):
        cands = strategy.cn.candidate_moves
        best = cands[0]["move"] if cands else None
        analysis = waiter.humansl(strategy.cn, self.profile, visits=1)
        hp = (analysis or {}).get("humanPolicy")
        if not hp:
            return {"hp_played": None, "hp_best": None, "hp_rank": None}
        return S.hp_audit_values(hp, game.board_size[0], move.gtp(), best)


def make_hooks_factory(plan, arms):
    """execute_plan の hooks_builder。plan["shadow"]（アーム名）と plan["hp_audit"]（humanSL の段位）を読む。"""
    shadow_name = plan.get("shadow")
    profile = plan.get("hp_audit")

    def factory(arm_name):
        hooks = []
        if shadow_name and shadow_name != arm_name:
            hooks.append(ShadowHook(arms[shadow_name]))
        if profile:
            hooks.append(HpAuditHook(profile))
        return hooks

    return factory
```

- [ ] **Step 4: CLI にフラグをつなぐ** — `katrain_debug/selfplay.py` を Edit ツールで5か所（どの old_string もファイル内で1回だけ現れる）

(a) import（old_string → new_string）:

```python
from katrain_debug.selfplay_game import report_sgf, resolve_arm, start_engine  # noqa: E402
```
```python
from katrain_debug.selfplay_game import report_sgf, resolve_arm, start_engine  # noqa: E402
from katrain_debug.selfplay_hooks import make_hooks_factory  # noqa: E402
```

(b) 影のアーム名の検査（`_plan_run` の中）:

```python
        raise SystemExit(f"null experiment: arms {same} resolve to identical settings")
```
```python
        raise SystemExit(f"null experiment: arms {same} resolve to identical settings")
    if args.shadow is not None and args.shadow not in {a.name for a in arms}:
        raise SystemExit(f"--shadow {args.shadow}: not one of the --arm names")
```

(c) 計画に載せる（`_plan_run` の `extra=`。`_plan_calibrate` の `extra=` は `write_pool` を含むので一致しない）:

```python
        extra={"config_path": args.config or default_config_path()},
    )
    return stub, plan
```
```python
        extra={
            "config_path": args.config or default_config_path(),
            "shadow": args.shadow,
            "hp_audit": args.hp_audit,
        },
    )
    return stub, plan
```

(d) `cmd_run` の `execute_plan` に hooks_builder を渡す（直前の `_new_output(... "run")` の行で `cmd_calibrate` と区別する）:

```python
        out = _new_output(args, stub, plan, args.label or "run")
    R.execute_plan(plan, out, stub, engine_factory=start_engine, retry_aborted=args.retry_aborted, log=safe_print)
```
```python
        out = _new_output(args, stub, plan, args.label or "run")
    R.execute_plan(
        plan,
        out,
        stub,
        engine_factory=start_engine,
        hooks_builder=make_hooks_factory,
        retry_aborted=args.retry_aborted,
        log=safe_print,
    )
```

(e) フラグ:

```python
    run.add_argument("--watch-flags", action="store_true", help="game.board_watch_active を立てる（監視専用の分岐）")
```
```python
    run.add_argument("--watch-flags", action="store_true", help="game.board_watch_active を立てる（監視専用の分岐）")
    run.add_argument("--shadow", default=None, metavar="ARM", help="他のアームの各手番でこのアームの判断も記録する")
    run.add_argument("--hp-audit", default=None, metavar="PROFILE", help="hp 監査の humanSL（例 rank_9d）")
```

- [ ] **Step 5: 通ることを確かめる**

Run: `pytest tests/test_selfplay_hooks.py -q`
Expected: `8 passed`

Run: `pytest tests/test_selfplay_*.py -q`
Expected: `109 passed`

Run: `python -m black --line-length 120 --check katrain_debug/selfplay.py katrain_debug/selfplay_hooks.py tests/test_selfplay_hooks.py`
Expected: `3 files would be left unchanged.`

- [ ] **Step 6: コミット**

```bash
git add katrain_debug/selfplay_hooks.py katrain_debug/selfplay.py tests/test_selfplay_hooks.py
git commit -m "feat(selfplay): hp 監査（--hp-audit）と影判定（--shadow）

hp 監査は AI の全着手の親局面に humanSL を 1visit で撃ち、選んだ手と最善手の hp・
順位を記録（外した手の 9段 hp の中央値を全アーム共通に測る）。影判定はアーム A の
各手番で B の戦略を同じ局面に走らせ、選んだ手・そのコスト（pointsLost）・判定情報
だけ記録する。B の sticky 状態は game._shadow_state に持ち、A の属性とグローバル乱数
は毎回戻す。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 実エンジンでのスモーク（13路・難解＋ vs rank_3k と 19路1局）

**KaTrain で対局中なら実行しない**（GPU を取り合うと実戦の AI が遅くなり maxTime に当たる＝spec §7）。CLI も起動中の `katago.exe` を見つけたら止まるが、始める前に自分でも確かめ、ユーザーに「30 分ほど KaTrain を使わない」ことを確認してから走らせる（13路 2局・フックつき 2局・19路 1局を順に。同時には走らせない）。

**Files:**
- Create: `<scratchpad>/smoke_check.py`（リポジトリには入れない）
- Modify: `docs/superpowers/specs/calibration-data/selfplay/README.md`（末尾に動作確認の記録を足す・LF の新規ファイルなので Edit でよい）
- 出力: `experiments/selfplay/<YYYYMMDD_HHMM>_smoke/`・`..._smoke-hooks/`・`..._smoke19/` と、コンソールの写し `experiments/selfplay/smoke*.console.txt`（すべて gitignore 済み）

**Interfaces:**
- Consumes: Task 5・6 の CLI、ユーザーのローカル設定（`~/.katrain/config.json` の `ai:enigma13plus`・エンジン設定。読むだけ）、Task 1 の `recon/`（投了閾値の標本）
- Produces: 実エンジンで「記録の一致率 == 保存 SGF を読み直した game_report の一致率」（WATCH / STRICT × 7区間）の確認と、1局の所要時間の実測（Task 8 の記述と Task 10 の見積もりに使う）、19路の経路（盤面積で比例した区間・投了の開始手数 85・19路の humanSL）の実エンジンでの通過

- [ ] **Step 1: KataGo が動いていないことを確かめる**

Run: `tasklist //FI "IMAGENAME eq katago.exe" //NH | grep -i katago.exe || echo "no katago"`
Expected: `no katago`。`katago.exe` の行が出たら**止めてユーザーに確認**（KaTrain の対局中・別のハーネスの実行中）。

- [ ] **Step 2: スモークを走らせる**（2局＝AI 黒・白1局ずつ。投了あり。約 5〜7 分。Bash ツールの `run_in_background: true` で走らせる＝前面の 600000 ms の打ち切りで途中で殺さない）

```bash
mkdir -p experiments/selfplay && python -m katrain_debug.selfplay run --arm A=enigma13plus --size 13 --pairs 2 --ranks rank_3k --label smoke --boot 1000 > experiments/selfplay/smoke.console.txt 2>&1
```
進み具合（数分おき）: `wc -l experiments/selfplay/*_smoke/games.jsonl; tail -3 experiments/selfplay/smoke.console.txt`
終了の通知が来たら `cat experiments/selfplay/smoke.console.txt` を読む。Expected:
- 最初に `output: ` と出力ディレクトリ（`experiments` の下の `selfplay` の中・末尾が `_smoke`）
- `[1/2] A seed=1000 ai=B vs rank_3k: win (opp_resign) moves=... own=0.... opp=0.... lead=+... ...s` と `[2/2] A seed=1001 ai=W ...` の2行（`error=` が付かない。`double_pass` / `move_cap` で終わってもよいが `aborted` は不可）
- 最後に `# selfplay summary ...` の表（`A` の行の n が 2）

途中でプロセスが落ちた場合は、同じく背景で `python -m katrain_debug.selfplay run --resume experiments/selfplay/<dir> >> experiments/selfplay/smoke.console.txt 2>&1` で続きから。

- [ ] **Step 3: 検算スクリプトを `<scratchpad>/smoke_check.py` に Write**

```python
"""Task 7: スモークの検算。games.jsonl の各局について、保存 SGF を report-sgf で読み直した数字が記録と完全に一致するか。

使い方（リポジトリのルートで・KaTrain を止めてから）: python <scratchpad>/smoke_check.py experiments/selfplay/<dir>
"""

import json
import os
import subprocess
import sys

BINS = ("all", "gui_opening", "gui_middle", "gui_endgame", "cal_opening", "cal_middle", "cal_endgame")

run_dir = sys.argv[1]
with open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8") as f:
    records = [json.loads(line) for line in f if line.strip()]
assert records, "games.jsonl is empty"
for rec in records:
    assert rec["result"] != "aborted", rec.get("error")
    assert rec["sgf"], rec.get("sgf_error")
    assert rec["own_n"] >= 20 and rec["opp_n"] >= 20, (rec["own_n"], rec["opp_n"])
    out = subprocess.run(
        [sys.executable, "-m", "katrain_debug.selfplay", "report-sgf", os.path.join(run_dir, rec["sgf"]), "--json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    reports = json.loads(out)["reports"]
    for tree in ("WATCH", "STRICT"):
        for name in BINS:
            black, white = reports[tree][name]["ai"], reports[tree][name]["opp"]
            own, opp = (black, white) if rec["ai_color"] == "B" else (white, black)
            mine = rec["reports"][tree][name]
            assert (own["top1"], own["n"]) == (mine["ai"]["top1"], mine["ai"]["n"]), (rec["seed"], tree, name)
            assert (opp["top1"], opp["n"]) == (mine["opp"]["top1"], mine["opp"]["n"]), (rec["seed"], tree, name)
    print(
        f"seed {rec['seed']} ai={rec['ai_color']}: {rec['result']} ({rec['end_reason']}) moves={rec['n_moves']} "
        f"own={rec['own_top1']:.3f} opp={rec['opp_top1']:.3f} strategy_p95={rec['strategy_p95']:.2f}s "
        f"wall={rec['wall_s']:.0f}s visits_low={rec['visits_low']} -> report-sgf identical"
    )
print("smoke OK")
```

- [ ] **Step 4: 記録と「保存 SGF を GUI と同じ経路で読み直したレポート」が完全に一致することを確かめる**

Run: `python <scratchpad>/smoke_check.py experiments/selfplay/<Step 2 の dir>`
Expected: `seed 1000 ai=B: win (...) moves=... own=0.xxx opp=0.xxx strategy_p95=...s wall=...s visits_low=... -> report-sgf identical` と `seed 1001 ai=W: ...` の2行、最後に `smoke OK`。
目安（外れても失敗ではないが、大きく外れたら Step 6 に進む前に `logs/*.log` と `moves.jsonl` を読む）: own 0.40〜0.70・opp 0.12〜0.40・strategy_p95 < 5 秒・wall 60〜300 秒・visits_low は手数の 1 割未満。

`AssertionError` なら、どの木・どの区間で食い違ったかがメッセージに出る。SGF の KT（解析）の往復で数字が変わる＝`write_sgf` / `load_analysis` の問題なので、`reports` の該当区間の `n` の差から調べる（偽エンジンでは `tests/test_selfplay_cli.py::TestReportSgf` が、読み直しで数字の違う偽エンジンに一度も解析を頼まない＝KT をそのまま使うことを固定している）。

- [ ] **Step 5: hp 監査と影判定を実エンジンで1回ずつ通す**（2局・40手・投了なし。約 3〜4 分。`run_in_background: true`）

```bash
python -m katrain_debug.selfplay run --arm A=enigma13plus --arm B=mimic13 --shadow B --hp-audit rank_9d --size 13 --pairs 1 --ranks rank_3k --no-resign --max-moves 40 --label smoke-hooks --boot 200 > experiments/selfplay/smoke-hooks.console.txt 2>&1
```
終了の通知が来たら `cat experiments/selfplay/smoke-hooks.console.txt`: `warning: 1 seeds over 1 ranks x 2 colours is unbalanced ...`（1 seed なので想定どおり）・`[1/2] A seed=1000 ...`・`[2/2] B seed=1000 ...`（`error=` なし）・要約の末尾に `## paired diff A - B`（n=1）。

Run:
```bash
python -c "import json,glob; d=sorted(glob.glob('experiments/selfplay/*_smoke-hooks'))[-1]; recs={r['arm']: r for r in map(json.loads, open(d+'/games.jsonl', encoding='utf-8'))}; moves=[json.loads(x) for x in open(d+'/moves.jsonl', encoding='utf-8')]; ai=[m for m in moves if m['is_ai']]; print('shadow A:', recs['A']['shadow']); print('shadow B:', recs['B']['shadow']); print('hp rows:', sum(m.get('hp_rank') is not None for m in ai), '/', len(ai)); print('hp_dev_median A:', recs['A']['hp_dev_median'], 'B:', recs['B']['hp_dev_median'])"
```
Expected: `shadow A: {'arm': 'B', 'n': 20, 'dev_rate': ..., 'same_as_played': ..., 'vloss_mean': ..., 'played_loss_mean': ..., 'secs_p95': ...}`（A の 20 手番すべてで B が判断した。`vloss_mean` は B の手の pointsLost の平均）、`shadow B: None`、`hp rows: 40 / 40`（両アームの AI の全着手）、`hp_dev_median` は 0〜1 の数か None（外した手が無い局）。

- [ ] **Step 5b: 19路のスモーク**（spec §3「19路: 13路のプールを流用し、数局のスモークだけ」。1局・120手まで・投了あり。約 5〜10 分。`run_in_background: true`）

19路の経路（`move_cap` 以外の盤面積の比例＝校正用区間の境界 52 / 182 手・投了の開始手数 85・19路の humanSL の 362 要素の humanPolicy・19路の KT 解析つき SGF）を実エンジンで1回通す。戦略は 19路の難解＋（`enigma19plus`。`enigma13plus` は 13路専用で、19路では盤サイズの門で KataGo の最善手を打つだけになる）。13路のプールは Task 10 まで無いので相手は `--ranks rank_3k`。

```bash
python -m katrain_debug.selfplay run --arm A=enigma19plus --size 19 --pairs 1 --ranks rank_3k --max-moves 120 --label smoke19 --boot 200 > experiments/selfplay/smoke19.console.txt 2>&1
```
終了の通知が来たら `cat experiments/selfplay/smoke19.console.txt`。Expected: 層の警告1行（1 seed なので想定どおり）と `[1/1] A seed=1000 ai=B vs rank_3k: ... (move_cap) moves=120 ...`（85手以降の相手の投了 `(opp_resign)` でもよい。`error=` なし・`aborted` 不可）。続けて Step 4 と同じ検算を 19路にも掛ける:

Run: `python <scratchpad>/smoke_check.py experiments/selfplay/<smoke19 の dir>`
Expected: `seed 1000 ai=B: ... -> report-sgf identical` と `smoke OK`。`logs/A_1000_B.log` に `[Enigma19PlusStrategy]` の行があること（`grep -c "Enigma19PlusStrategy" experiments/selfplay/*_smoke19/logs/A_1000_B.log` が 1 以上）。

- [ ] **Step 6: GUI で同じレポートが出ることをユーザーに確かめてもらう**（spec §2 の「GUI で開けば同じレポートが出ることを1回手で確かめる」）

Run（ユーザーに見せる数字）:
```bash
python -c "import json,glob; d=sorted(glob.glob('experiments/selfplay/*_smoke'))[-1]; r=json.loads(open(d+'/games.jsonl', encoding='utf-8').readline()); s=r['reports']['STRICT']['all']; b, w = (s['ai'], s['opp']) if r['ai_color']=='B' else (s['opp'], s['ai']); print(d+'/'+r['sgf']); print('black top1 %.1f%% (n=%d) / white top1 %.1f%% (n=%d)' % (100*b['top1'], b['n'], 100*w['top1'], w['n']))"
```
ユーザーへの依頼: 「KaTrain でこの SGF を開き、終局レポート（全体タブ）の AI 最善手一致率が黒・白ともこの値と一致するか見てください」。GUI のレポートは本譜全体（末尾のパス込み）＝STRICT と同じ定義。投了で終わった局は末尾にパスが無いので WATCH と同じ値。**確認が取れるまで Task 8 のコミットに進まない**（ユーザーが不在なら結果の報告に「GUI 確認は未実施」と明記して続ける）。

- [ ] **Step 7: 動作確認の記録を README に足す**（Edit・`docs/superpowers/specs/calibration-data/selfplay/README.md` の末尾に追記。`<...>` は Step 4・5・5b の出力の数字で置き換える）

```markdown

## 動作確認（<実施日 YYYY-MM-DD>・13路 難解＋ vs rank_3k・投了あり／19路 1局）

- seed 1000（AI 黒）: <result>（<end_reason>）<moves> 手・own <own> / opp <opp>・strategy_p95 <p95> 秒・wall <wall> 秒
- seed 1001（AI 白）: 同上の形式
- 保存 SGF を `report-sgf` で読み直した一致率は WATCH / STRICT × 7区間で記録と完全一致。GUI の終局レポートとの一致: <確認済み／未実施>
- `--shadow B --hp-audit rank_9d`（難解＋ / 擬態・40手）: 影判定 20/20 手番（B の手の pointsLost 平均 <vloss_mean>）、hp 監査 40/40 手
- 19路（`enigma19plus` vs rank_3k・120手まで）: <result>（<end_reason>）<moves> 手・own <own> / opp <opp>・wall <wall> 秒・report-sgf と完全一致
```

（コミットは Task 8 でまとめて行う）

---

### Task 8: ドキュメント（CLAUDE.md・INDEX・spec の状態）

**Files:**
- Create: `<scratchpad>/patch_docs_selfplay.py`（リポジトリには入れない）
- Modify: `CLAUDE.md`（CRLF。ディレクトリ構造の `katrain_debug/` の行と、使い方の段落）
- Modify: `docs/superpowers/specs/INDEX.md`（CRLF。spec の行を 🟢 に・校正データの一覧に `selfplay/`・計画の本数）
- Modify: `docs/superpowers/specs/2026-09-23-selfplay-harness-design.md`（LF。状態の行）

**Interfaces:**
- Consumes: `<scratchpad>/crlf_patch.py`（Task 0）、Task 7 の README 追記
- Produces: Task 10 の `patch_docs_calibrated.py` が置き換える文字列 `（相手ボットの校正は未実施） |`（INDEX）と、spec の状態の行の「相手ボットの校正は未実施（calibrate の結果を …selfplay/ に記録する）。」（正確な文字列は `patch_docs_selfplay.py` の `SPEC_EDITS` の new 側）

- [ ] **Step 1: パッチスクリプトを `<scratchpad>/patch_docs_selfplay.py` に Write**

````python
"""Task 8: CLAUDE.md・INDEX.md（CRLF）と spec（LF）を更新する。リポジトリのルートを cwd にして実行する。"""

import datetime
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch  # noqa: E402

TODAY = datetime.date.today().isoformat()

CLAUDE_TREE_OLD = "  katrain_stub.py     -- Kivy依存なしのKaTrainスタブ\n"
CLAUDE_TREE_NEW = (
    CLAUDE_TREE_OLD
    + "  selfplay.py         -- 自己対局ハーネスの CLI（run / calibrate / summarize / report-sgf）\n"
    + "  selfplay_game.py    -- 1局（本物の Game・generate_ai_move の写し・本物の game_report・WATCH/STRICT）\n"
    + "  selfplay_opponent.py -- 相手ボット（humanSL 1visit のサンプラー）と待ちループ\n"
    + "  selfplay_hooks.py   -- hp 監査（--hp-audit）と影判定（--shadow）\n"
    + "  selfplay_run.py     -- 実行計画・出力ディレクトリ・再開・要約・校正の集計\n"
    + "  selfplay_stats.py   -- 純関数（日程・投了・WATCH 木・1局/アームの要約・統計）\n"
)
CLAUDE_USAGE_OLD = "\n## コーディング規約\n"
CLAUDE_USAGE_NEW = (
    "\n**自己対局ハーネス**（`python -m katrain_debug.selfplay`・spec `2026-09-23-selfplay-harness-design.md`）: "
    "戦略 vs humanSL ボット（実戦の相手に校正）を無人で N 局打たせ、本物の `game_report` で両者の一致率・勝敗・目差を"
    "集計する。**実戦中の KaTrain と同時に走らせない**（起動中の katago.exe があれば止まる。GPU を取り合うと実戦の AI が "
    "maxTime に当たる）。\n"
    "```bash\n"
    "# A/B（全アームが同じ seed＝色・相手・投了閾値を対にする。10 seed ごとに ABBA）。相手は既定で calibration-data/selfplay/opponent_pool_13.json\n"
    "python -m katrain_debug.selfplay run --arm A=enigma13plus --arm B=enigma13plus:enigma13plus_max_loss=2.0 --size 13 --pairs 20 --label maxloss-ab\n"
    "# 投了なし（必須の感度アーム）・接戦ストレス層（AI 不利のコミ＋強めの相手）\n"
    "python -m katrain_debug.selfplay run --arm A=enigma13plus --size 13 --pairs 20 --no-resign --label nores\n"
    "python -m katrain_debug.selfplay run --arm A=enigma13plus --size 13 --pairs 20 --komi-shift 4 --ranks rank_5d,rank_9d --opp-max-loss 2 --label stress\n"
    "# 集計し直し・対の差（既定 97.5% 区間＝2回見る停止規則。2アームの run は終了時にも出す）・落ちた実行の再開\n"
    "python -m katrain_debug.selfplay summarize experiments/selfplay/<dir> --compare A B\n"
    "python -m katrain_debug.selfplay run --resume experiments/selfplay/<dir>   # --retry-aborted で aborted の局も打ち直す\n"
    "# 停止規則の延長（差の区間が ±3pt の線をまたぐとき 40 ペアへ）: seed をずらした 20 ペアを足し、2本を合わせて集計\n"
    "python -m katrain_debug.selfplay run --arm A=enigma13plus --arm B=enigma13plus:enigma13plus_max_loss=2.0 --size 13 --seed-base 1020 --pairs 20 --label maxloss-ab-ext\n"
    "python -m katrain_debug.selfplay summarize experiments/selfplay/<dir> experiments/selfplay/<ext の dir> --compare A B\n"
    "# 相手ボットの校正（13路 6段位×8局・約2時間）・実戦の保存 SGF の両者のレポート\n"
    "python -m katrain_debug.selfplay calibrate --size 13 --strategy enigma13plus --games 8 --write-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json\n"
    "python -m katrain_debug.selfplay report-sgf FILE.sgf\n"
    "```\n"
    "出力は `experiments/selfplay/<YYYYMMDD_HHMM>_<label>/`（`run.json`＝解決済み設定とハッシュ・ai.py の場所・git HEAD、"
    "`games.jsonl`＝1局1行、`moves.jsonl`＝1手1行、`sgf/`＝KT 解析つき、`logs/`＝戦略自身の `[XxxStrategy]` 行"
    "（`Rate:` / `Decision:` / 着手時間）とエラー、"
    "`summary.txt`（ASCII）/ `summary.json`）。主指標は **WATCH 木（末尾のパスを除く＝監視対局の木と同じ）の局ごとの一致率**。"
    "アームの書式は `<名前>=<runner の戦略名>[:key=val,...]`（綴り間違いのキーと、解決済み設定が同一のアーム＝null 実験は開始前に止まる）。"
    "`--shadow B` は他アームの各手番で B の判断を同じ局面で記録（打たない）、`--hp-audit rank_9d` は外した手の 9段 hp を測る。"
    "1局 13路 2〜3分（投了あり）。seed の数は 2 × 相手の段位数 の倍数にする（層の局数が揃わないと警告）。"
    "KataGo の探索は非決定的＝seed は開始条件の対で再現ではない（最低 20 ペアで比べる）。\n"
    "\n## コーディング規約\n"
)

INDEX_EDITS = [
    (
        "| `2026-09-23-selfplay-harness-design.md` | 📝 自己対局ハーネス",
        "| `2026-09-23-selfplay-harness-design.md` | 🟢 自己対局ハーネス",
        1,
    ),
    (
        "接戦ストレス層・投了なし・影判定・hp 監査 |\n",
        "接戦ストレス層・投了なし・影判定・hp 監査。実装 `katrain_debug/selfplay*.py`・データ `calibration-data/selfplay/`"
        "（相手ボットの校正は未実施） |\n",
        1,
    ),
    (
        "- `enigma-overdraft/` — 難解「捨て身の罠」の在庫の反実仮想（ハーネス `overdraft_cf.py`・集計 `overdraft_cf_report.py`・復元 SGF 18 局）\n",
        "- `enigma-overdraft/` — 難解「捨て身の罠」の在庫の反実仮想（ハーネス `overdraft_cf.py`・集計 `overdraft_cf_report.py`・復元 SGF 18 局）\n"
        "- `selfplay/` — 自己対局ハーネス（`python -m katrain_debug.selfplay`）: 実戦 13路 18局の復元 SGF と事後 2500v レポート"
        "（`recon/`）・校正目標 `calib_targets.py`・相手ボットのプール `opponent_pool_13.json`（calibrate の出力）・試作と計測・"
        "韜晦の反実仮想（`README.md` に一覧）\n",
        1,
    ),
]
# 計画の本数はコミット済みのもの（git ls-files）だけ数える。未コミットの計画（例: 韜晦の計画）は入れない
tracked = subprocess.run(["git", "ls-files", "docs/superpowers/plans/*.md"], capture_output=True, text=True, check=True)
n_plans = len(tracked.stdout.split())
if n_plans != 51:
    INDEX_EDITS.append(("51本。", f"{n_plans}本。", 1))

SPEC_EDITS = [
    (
        "状態: 設計（未実装）。最初の用途は韜晦（spec `2026-09-23-veil-strategy-design.md`）の校正と A/B\n",
        f"状態: 実装済み（{TODAY}・plan `2026-09-23-selfplay-harness.md`・実装 `katrain_debug/selfplay.py`（CLI）/ "
        "`selfplay_game.py` / `selfplay_opponent.py` / `selfplay_hooks.py` / `selfplay_run.py` / `selfplay_stats.py`）。"
        "相手ボットの校正は未実施（calibrate の結果を `calibration-data/selfplay/` に記録する）。"
        "最初の用途は韜晦（spec `2026-09-23-veil-strategy-design.md`）の校正と A/B\n",
        1,
    ),
]

patch("CLAUDE.md", [(CLAUDE_TREE_OLD, CLAUDE_TREE_NEW, 1), (CLAUDE_USAGE_OLD, CLAUDE_USAGE_NEW, 1)])
patch("docs/superpowers/specs/INDEX.md", INDEX_EDITS)
patch("docs/superpowers/specs/2026-09-23-selfplay-harness-design.md", SPEC_EDITS)
````

- [ ] **Step 2: 実行する**

Run: `python <scratchpad>/patch_docs_selfplay.py`
Expected:
```
patched CLAUDE.md (CRLF, 2 edit(s))
patched docs/superpowers/specs/INDEX.md (CRLF, 4 edit(s))
patched docs/superpowers/specs/2026-09-23-selfplay-harness-design.md (LF, 1 edit(s))
```
（INDEX の件数は、コミット済みの計画（`git ls-files`）の本数が 51 から変わっていれば 4、変わっていなければ 3。Task 0 でこの計画をコミットしたので通常は 52 本＝4。作業ツリーにあるだけの未コミットの計画（韜晦の計画など）は数えない）

- [ ] **Step 3: 改行コードが混ざっていないことと差分を確かめる**

Run: `python -c "import sys; [print(p, raw.count(bytes([10])), raw.count(bytes([13, 10]))) for p in ('CLAUDE.md', 'docs/superpowers/specs/INDEX.md') for raw in [open(p, 'rb').read()]]"`
Expected: 各行の2つの数が等しい（全行 CRLF）

Run: `git diff --stat`
Expected: `CLAUDE.md`（+25 行）・`INDEX.md`（+3 / −2）・spec（+1 / −1）・`calibration-data/selfplay/README.md`（Task 7 の追記）の4ファイルだけ

- [ ] **Step 4: コミット**

```bash
git add CLAUDE.md docs/superpowers/specs/INDEX.md docs/superpowers/specs/2026-09-23-selfplay-harness-design.md docs/superpowers/specs/calibration-data/selfplay/README.md
git commit -m "docs(selfplay): 自己対局ハーネスの使い方・索引・spec の状態を更新

CLAUDE.md に python -m katrain_debug.selfplay の使い方と katrain_debug/selfplay*.py、
INDEX の spec を実装済みに・校正データ selfplay/ を追加、spec の状態を実装済み
（相手ボットの校正は未実施）に。スモーク（難解＋ vs rank_3k 2局・19路1局）の記録を README に。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 最終検証

- [ ] **Step 1: 全テスト**（KataGo を止めた状態で）

Run: `pytest --ignore=tests/test_ai.py -q`
Expected: 全 PASS（新規 109 件を含む）。`test_collapsable_panel.py` の 6 件が落ちたら既知の順序依存フレーク＝`pytest tests/test_collapsable_panel.py -q` 単体で PASS を確認する。ソルバの時間閾値系が落ちたら KataGo と並走していないか確認して単体で再実行。

- [ ] **Step 2: 既存のコードを変えていないこと**

Run: `git diff master --stat -- katrain/ katrain_debug/cli.py katrain_debug/runner.py katrain_debug/batch_eval.py katrain_debug/__main__.py katrain_debug/katrain_stub.py`
Expected: 何も出ない（`katrain/` と既存の `katrain_debug/*.py` は無変更）

Run: `git diff master --stat | tail -1`
Expected: 新規ファイル（`katrain_debug/selfplay*.py` 6本・`tests/*selfplay*` 7本・`calibration-data/selfplay/` 52本）と docs 3本＋計画の変更だけ。桁違いの削除行が無い。

ブランチの扱い（マージ・push）はここでは決めない。Task 10 の校正の結果も同じブランチに載せてから Task 11 で確認する。

---

### Task 10: 相手ボットの校正キャンペーン（運用・バックグラウンド約2時間）

spec §3 の「校正手順（calibrate）」。**約2時間 GPU を占有する**ので、ユーザーに「その間 KaTrain を使わない」ことを確認してから始める（夜間推奨）。Task 9 の後に、同じブランチ `feature/selfplay-harness` の上でコードを変えずに実行する（コミットは Step 8 の1つ）。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json`（`calibrate --write-pool` が書く）
- Create: `docs/superpowers/specs/calibration-data/selfplay/selfplay-calibration-results-<YYYYMMDD>.md`（run の `calibration.md` の写し＋判断の節）
- Create: `<scratchpad>/patch_docs_calibrated.py`（リポジトリには入れない）
- Modify: `docs/superpowers/specs/INDEX.md`（CRLF）・spec（LF）の「校正は未実施」を置き換える

**Interfaces:**
- Consumes: Task 5 の `calibrate`・`selfplay_run.calibration_result` / `pool_file_content`、Task 8 が入れた「未実施」の文字列
- Produces: `opponent_pool_13.json`（キー `board_size, created, source_run, strategy, ranks, tau, fit, targets, per_rank, harness_drift_ai`。`run` は `--ranks` / `--opp-pool` が無ければこれを読む＝以後の A/B の既定の相手）

- [ ] **Step 0: ブランチを確かめる**

Run: `git branch --show-current`
Expected: `feature/selfplay-harness`。ユーザーの判断で Task 11 を先に済ませ（ブランチを master に取り込んだ後に）この Task を後日回す場合は、master の上で `git checkout -b feature/selfplay-calibration` を実行し（Expected: `Switched to a new branch 'feature/selfplay-calibration'`）、Step 8 のコミットの後にそのブランチの扱いをユーザーに確認する。**master の上へ直接コミットしない**。

- [ ] **Step 1: KataGo が動いていないことを確かめる**

Run: `tasklist //FI "IMAGENAME eq katago.exe" //NH | grep -i katago.exe || echo "no katago"`
Expected: `no katago`。

- [ ] **Step 2: バックグラウンドで開始する**（Bash ツールの `run_in_background: true`。難解＋13路・ユーザーのローカル設定 × rank_8k / 5k / 3k / 1k / 1d / 3d × 各8局＝48局・色は交互・投了あり）

```bash
mkdir -p experiments/selfplay && python -m katrain_debug.selfplay calibrate --size 13 --strategy enigma13plus --games 8 --label calib13 --boot 2000 --write-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json > experiments/selfplay/calib13.console.txt 2>&1
```

- [ ] **Step 3: 進み具合を見る**（数十分おきに。終わるまで他の KataGo 作業をしない）

Run: `wc -l experiments/selfplay/*_calib13/games.jsonl; tail -2 experiments/selfplay/calib13.console.txt`
Expected: 行数が 48 まで増える（1局 2〜3 分）。`error=` の行が続く・行数が 30 分以上増えないなら、`tail -40 experiments/selfplay/calib13.console.txt` と `logs/` を読んで原因を調べる。プロセスが落ちていたら、同じく背景で `python -m katrain_debug.selfplay calibrate --resume experiments/selfplay/<dir> >> experiments/selfplay/calib13.console.txt 2>&1`（計画の `--write-pool` も引き継ぐ）。KataGo が途中で落ちても、ハーネスは次の局の前に再起動するので、`aborted` になるのは落ちた局だけ（続けて何局も `error=engine died ...` が出るならエンジンの設定か GPU を疑い、止めてユーザーに報告）。

- [ ] **Step 4: 結果を読む**（終了後）

Run: `tail -12 experiments/selfplay/calib13.console.txt`
Expected: 段位ごとの `rank_8k: games=8 opp mean=...% sd=...pt loss=... >=2=...% >=5=...% own=...% moves=...` の6行、`best pool: [...] mean=...% sd=...pt loss=... drift_ai=...`、`pool written: docs/.../opponent_pool_13.json`、`calibration: .../calibration.md`。

Run: `python -c "import json,glob; d=sorted(glob.glob('experiments/selfplay/*_calib13'))[-1]; s=json.load(open(d+'/summary.json', encoding='utf-8')); c=json.load(open(d+'/calibration.json', encoding='utf-8')); b=c['best']; print(d, 'aborted', s['arms']['calib']['aborted']); print(b['ranks'], round(b['opp_mean'],3), round(b['opp_sd'],3), round(b['opp_loss'],2), 'mid', b['bins']['cal_middle'], 'score', round(b['score'],2), 'drift', c['harness_drift_ai'])"`
Expected: `aborted` が 4 以下（48局の 1 割以下）。超えたら `games.jsonl` の `error` を読み、エンジン停止・タイムアウトのような一時的な原因なら背景で `python -m katrain_debug.selfplay calibrate --resume experiments/selfplay/<dir> --retry-aborted >> experiments/selfplay/calib13.console.txt 2>&1` で aborted の局だけ打ち直す（行は `aborted.jsonl` へ移る）。戦略・ハーネスの例外（traceback つきの `error`）なら、コードを変えずに止めてユーザーに報告する。

- [ ] **Step 5: 区間の形が合わないときだけ τ で1回だけ再校正する**（spec §3 手順4。τ は 0.8〜1.2 の範囲）

判定（Step 4 の `mid`＝採用プールの中盤 手数 24〜84 の相手の一致率・損失）: `|opp_top1 − 0.182| > 0.05` または `|opp_loss − 2.43| > 0.5` のときだけ再校正する。どちらも範囲内なら Step 6 へ。
- 相手が強すぎる（`opp_top1 > 0.232` または `opp_loss < 1.93`）→ τ = 1.1（分布を平らに＝弱く）
- それ以外（弱すぎる）→ τ = 0.9

Run（バックグラウンド・約1時間。`<r1,r2,r3>` は Step 4 の `b['ranks']` をカンマでつないだもの）:
```bash
python -m katrain_debug.selfplay calibrate --size 13 --strategy enigma13plus --ranks <r1,r2,r3> --games 8 --tau <τ> --label calib13-tau<τ> --boot 2000 --write-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json > experiments/selfplay/calib13-tau.console.txt 2>&1
```
終わったら Step 4 の2本目のコマンドの `'*_calib13'` を `'*_calib13-tau*'` にして読み、**score が最初の実行の best の score より小さいときだけ採用**する。大きければ最初の実行のプールを書き戻す:
```bash
python -c "import json,sys; from katrain_debug import selfplay_run as R; out=R.OutputDir(sys.argv[1]); cal=R.calibration_result(out, out.read_json('run.json')); json.dump(R.pool_file_content(cal), open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False, indent=1); print(cal['best']['ranks'], cal['best']['score'])" experiments/selfplay/<最初の実行の dir> docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json
```
再校正でも範囲に入らなければ、それ以上 τ を動かさずに記録して Step 6 へ（spec §11「相手の忠実度」＝周辺統計でしか合わせられない）。

- [ ] **Step 6: 結果の md を作る**

```bash
cp experiments/selfplay/<採用したプールの実行の dir>/calibration.md "docs/superpowers/specs/calibration-data/selfplay/selfplay-calibration-results-$(date +%Y%m%d).md"
```
その md の末尾に次の節を Edit で足す（`<...>` は `calibration.json` / `summary.json` / コンソールの値で置き換える）:

```markdown

## 判断（<実施日 YYYY-MM-DD>）

- 採用したプール: <ranks>・τ <tau>（score <score>）。局平均 <opp_mean> / 局間 SD <opp_sd> / 損失 <opp_loss> 目（目標 23.1% / 6.5pt / 1.77 目）
- 区間の形（採用プールの中盤 24〜84 手）: 相手 <mid.opp_top1> / <mid.opp_loss> 目（目標 18.2% / 2.43 目）。τ の再校正: <しなかった／τ <値> で実施し <採用した／しなかった>（score <値>）>
- ハーネスと実戦のずれ（AI 側）: <harness_drift_ai×100> pt（プールでの難解＋の一致率 − 実戦の局平均 53.3%）。実戦の予測はこの差を引いて読む
- aborted <数> / 48 局。所要 <コンソールの最初の行から最後の行までの時間・ファイルの更新時刻で可>
- 注意: 段位ラベルはつまみにすぎない（humanSL は主に 19路のデータで、囲碁クエストの段級とは対応しない）。罠への掛かりやすさは周辺統計では校正できない（相手の実損 / E が実戦の 1.06 に近いかは韜晦の A/B で見る）
```

- [ ] **Step 7: INDEX と spec の「未実施」を置き換える**

`<scratchpad>/patch_docs_calibrated.py` を Write:

```python
"""Task 10: 相手ボットの校正結果を INDEX（CRLF）と spec（LF）に反映する。リポジトリのルートを cwd にして実行する。

引数: 結果の md のファイル名（docs/superpowers/specs/calibration-data/selfplay/ の中。例 selfplay-calibration-results-20260924.md）
"""

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch  # noqa: E402

results_md = sys.argv[1]
data_dir = "docs/superpowers/specs/calibration-data/selfplay"
assert os.path.exists(f"{data_dir}/{results_md}"), results_md
with open(f"{data_dir}/opponent_pool_13.json", encoding="utf-8") as f:
    pool = json.load(f)
ranks = " / ".join(pool["ranks"])
today = datetime.date.today().isoformat()
patch(
    "docs/superpowers/specs/INDEX.md",
    [
        (
            "（相手ボットの校正は未実施） |\n",
            f"（相手ボットは校正済み: {ranks}・τ {pool['tau']}・結果 `selfplay/{results_md}`） |\n",
            1,
        )
    ],
)
patch(
    "docs/superpowers/specs/2026-09-23-selfplay-harness-design.md",
    [
        (
            "相手ボットの校正は未実施（calibrate の結果を `calibration-data/selfplay/` に記録する）。",
            f"相手ボットは校正済み（{today}・{ranks}・τ {pool['tau']}・`calibration-data/selfplay/opponent_pool_13.json`・"
            f"結果 `calibration-data/selfplay/{results_md}`）。",
            1,
        )
    ],
)
```

Run: `python <scratchpad>/patch_docs_calibrated.py selfplay-calibration-results-<YYYYMMDD>.md`
Expected:
```
patched docs/superpowers/specs/INDEX.md (CRLF, 1 edit(s))
patched docs/superpowers/specs/2026-09-23-selfplay-harness-design.md (LF, 1 edit(s))
```

- [ ] **Step 8: 既定の相手で `run` が動くこと（プールを読む）を確かめてコミット**

Run: `python -c "import json; p=json.load(open('docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json', encoding='utf-8')); print(p['ranks'], p['tau'], p['strategy'], round(p['harness_drift_ai'], 3))"`
Expected: 3つの段位・τ・`enigma13plus`・ずれの数

```bash
git add docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json docs/superpowers/specs/calibration-data/selfplay/selfplay-calibration-results-*.md docs/superpowers/specs/INDEX.md docs/superpowers/specs/2026-09-23-selfplay-harness-design.md
git commit -m "docs(selfplay): 自己対局ハーネスの相手ボットを 13路の実戦に校正

難解＋13路 × humanSL 6段位 × 各8局。局平均の相手一致率・局間 SD・損失が実戦
（23.1% / 6.5pt / 1.77目）に最も近い 3段位を opponent_pool_13.json に保存し、
区間の形とハーネスと実戦のずれ（AI 側）を結果 md に記録。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: ブランチの扱いをユーザーに確認

- [ ] **Step 1: 状態を確かめる**

Run: `git status --short -- katrain katrain_debug tests CLAUDE.md docs/superpowers/specs; git log --oneline master..HEAD | wc -l`
Expected: 1つ目は何も出ない（`M` / `??` が無い）。2つ目は `10`（Task 0・1・2・3・4a・4b・5・6・8・10 のコミット。Task 7 はコミットしない）。

- [ ] **Step 2: superpowers:finishing-a-development-branch に従い、ブランチの扱いをユーザーに選んでもらう**（master へのマージ・push はユーザーの指示があるまでしない。未コミットの韜晦の計画 `plans/2026-09-23-veil-strategy.md` には触れない）

---

## この計画の範囲外（記録だけ）

Task 0 Step 0 でユーザーに確認してから後に回すもの（spec §3・§6・§7 にあるが、この計画では実装しない・回さない）。

- **9路の校正**（spec §3「9路」）: 相手の一致率の実測が無い。先に保持中の難解＋9路ログ 17局を SGF に戻し（`recon_logs.py` は 13路固定＝盤サイズを引数にする改修が要る）、`offline_report.py` で事後解析して 9路の `CALIB_TARGETS_9` を作ってから、同じ `calibrate --size 9` を回す（`calibration_result` のプール選択は今は 13路の目標でしか動かない＝`selfplay_pool_choice` に 9路の目標を渡す改修も要る）。投了閾値は 13路の標本を盤面積で比例させて使っている（`resign_pool_from_summaries`）。
- **spec §6 の実験の組み合わせ**（段階1 主比較・段階2 投了なし・段階3 接戦ストレス。合計約 11 時間）: 韜晦（`ai:veil13`）の実装後に、韜晦の計画の側で回す。停止規則は `summarize --compare A B` の `verdict(+-3pt)`（既定 97.5% 区間）で、`extend` なら `--seed-base 1020 --pairs 20` の run を足して `summarize DIR DIR_ext --compare A B` で 40 ペアを判定する。勝ちの安全は `flip_moves` の対の差の上限と敗局の SGF。
- **並列実行**（`--jobs`）: spec §7 の実測で 3 プロセスでもスループット +27% しか伸びず、解析待ちが maxTime に迫る＝既定 1 のまま入れない。どうしても要るなら `--seed-base` をずらした別プロセスを別ディレクトリで走らせ、`summarize DIR1 DIR2 ...` で合わせて集計する（同じ (arm, seed)・アームの設定や対局条件が違う DIR は止まる）。

---

## Self-Review

**1. spec の網羅**

| spec | 実装しているタスク |
|---|---|
| §0・§1-1 一致率は本物の game_report | Task 4a `compute_reports`（`game_report` を呼ぶだけ）、Task 7 の report-sgf 検算（13路・19路）・GUI 確認、Task 5 の `TestReportSgf`（KT を再解析しない） |
| §1-2・§2「AI の手番」 本物の Game と generate_ai_move の写し | Task 4a `_ai_turn`＋AST の一致テスト・`play_game` |
| §1-3・§3 相手ボットと校正 | Task 3 `HumanSLOpponent`、Task 5 `calibrate`、Task 10 |
| §1-4・§6 A/B（seed の対・ABBA・null ガード・t / Wilcoxon / bootstrap・停止規則と 40 ペアへの延長） | Task 2 `selfplay_schedule` / `abba_order` / `selfplay_paired_diff` / `selfplay_stop_rule` / `arms_null_guard`、Task 4b `load_records` / `summarize_dir`（複数の実行）、Task 5 `run` / `summarize DIR [DIR ...] --compare` |
| §1-5・§2 再開・エンジン停止の復旧（再起動してその局だけ aborted で続行）・実戦と同時に走らせない | Task 4a `EngineWatchdog.ensure_alive` / `Waiter`、Task 4b `execute_plan`（局の前に起こす・`retry_aborted`）/ `OutputDir`、Task 5 `ensure_no_katago` / `--retry-aborted`。テスト `test_engine_death_aborts_only_the_game_in_progress` |
| §2 構成（KIVY_NO_ARGS・stub と engine を1つずつ・PLAYER_HUMAN・`--watch-flags`） | Task 4a `Harness` / `start_engine`（config の置石は拒否）、Task 5 |
| §2 終局（投了・2連続パス・手数上限・aborted・AI は投了しない） | Task 2 `selfplay_should_resign` / `move_cap` / `selfplay_outcome`、Task 4a `play_game`（AI・相手の例外も aborted） |
| §2 集計（全ノード待ち・GUI と校正用の区間・WATCH / STRICT・`watch_prune`・KT つき SGF） | Task 2 `watch_prune` / `REPORT_BINS`、Task 4a `compute_reports`、Task 4b `OutputDir.write_game` |
| §2 判定情報は `last_decision_info` から・持たない戦略では空 | Task 4a `play_game`（`jsonable(getattr(...))`）、Task 2 `_decision_metrics`（無ければ `veil: None`。キーは韜晦の計画の「共有インターフェース」） |
| §3 パスの規則（pass_loss None ならパスしない）・`--opp-max-loss`・`--opponent strategy:human` | Task 3（テスト `test_pass_is_redrawn_when_katago_has_no_pass_candidate` ほか）、Task 4a `StrategyOpponent` |
| §3 投了モデル（実戦の最終リードの復元抽出・`--resign-lead`・`--no-resign`・開始手数） | Task 2 `resign_pool_from_summaries` / `selfplay_schedule`、Task 5 `resign_plan` |
| §3 seed（色・段位は層別に同数・相手の乱数・投了閾値・戦略側の Python 乱数） | Task 2 `selfplay_schedule` / `schedule_balance_warning`（揃わない seed 数を警告）、Task 4a `random.seed(strategy_seed)` |
| §3 19路（13路のプールを流用・数局のスモーク） | Task 7 Step 5b（Task 10 の前なのでプールの代わりに `--ranks rank_3k`） |
| §4 hp 監査 | Task 6 `HpAuditHook`・Task 2 `hp_audit_values` / `hp_dev_*` |
| §5 出力（run.json・games.jsonl の全列・moves.jsonl（判定情報は平らに）・sgf・logs・summary.txt/json・アーム間の差の表） | Task 2 `selfplay_game_summary` / `flat_row` / `selfplay_arm_summary`、Task 4a `drain_logs`（戦略自身の `[XxxStrategy]` 行）、Task 4b `make_plan` / `run_meta` / `OutputDir` / `format_summary_text`、Task 5 `cmd_run`（先頭のアームとの対の差） |
| §6 影判定（B の sticky 状態は `game._shadow_state[arm]`・A の属性を戻す・同じ局面での外し率とコスト） | Task 6 `run_shadow`（`vloss`）/ `ShadowHook`、Task 2 `_shadow_metrics`（`dev_rate` / `vloss_mean` / `played_loss_mean`） |
| §6 接戦ストレス層（`--komi-shift`・強めの相手・外しの種類ごとの判定時の vloss とレポートの損失の差） | Task 4a `komi_shift`、Task 5 のフラグ、Task 2 `_decision_metrics`（`vloss_by_kind` / `report_loss_by_kind` / `curse_by_kind`） |
| §8 CLI | Task 5（Task 6 で `--shadow` / `--hp-audit`） |
| §9 純関数とテスト（seed の決定性・null ガード・WATCH の復元・末尾パスで WATCH にパスが入らない・偽エンジンの短い対局・_ai_turn の一致・パスの規則・影で A が変わらない） | Task 2〜6 のテスト |
| §10 データの移設 | Task 1 |
| §11 リスク（visits_check・写しのずれ・設定の取り違え） | `visits_low`（Task 2）・AST テスト（Task 4a）・指紋と `settings_source`・`ai_file`・git（Task 4a・4b）・同じ出力ディレクトリの再利用の拒否（Task 4b） |
| §3 9路、§6 の実験の組み合わせ、§7 並列 | 範囲外の節に理由つきで記録（Task 0 Step 0 でユーザーに確認） |

**2. プレースホルダ**: コードのステップはすべて全文（HEAD のスナップショットに Task 2〜6 のコードを書き出して `pytest tests/test_selfplay_*.py` が 109 passed・black 済みを確かめたものをそのまま載せている。Task 8 と Task 10 のパッチスクリプトも HEAD の文書に当てて件数を確かめた）。`<scratchpad>`・`<dir>`・`<YYYYMMDD>` は実行時に決まる値で、どこから取るかを各ステップに書いた。Task 7 Step 7・Task 10 Step 6 の `<...>` は実行結果の数字を写す欄で、どの出力のどのキーかを指定してある。

**3. 型と名前の一貫性**: 後続タスクが使う名前は各タスクの Interfaces に列挙し、下の表のとおり一致させた。
- `play_game` の hook 規約 `before_ai(game, cn, waiter)` / `after_ai(game, strategy, move, waiter)` ＝ Task 6 の `ShadowHook.before_ai` / `HpAuditHook.after_ai`
- `execute_plan(..., hooks_builder=make_hooks_factory, retry_aborted=...)` ＝ `make_hooks_factory(plan, arms) -> factory(arm_name)`・CLI の `--retry-aborted`
- `EngineWatchdog.ensure_alive()` ＝ `_run`（見張り）と `execute_plan`（局の前）の両方が呼ぶ。`Waiter` は作った時点の `watchdog.restarts` を覚える（`play_game` の中で作る＝再起動の後）
- `summarize_dir(outs, n_boot, compare, conf, dest=None)` の `compare` は `(A, B)` か `[(A, B), ...]`、`summary["compare"]` はリスト ＝ `format_summary_text`・`cmd_run`（`[(先頭, 他), ...]`）・`cmd_summarize`（`(A, B)`）・テストの `summary["compare"][0]`
- games.jsonl の `own_top1` / `opp_top1` / `own_n` / `opp_n` / `reports[tree][bin]["ai" | "opp"]` ＝ `selfplay_arm_summary`・`calibration_rank_stats`・`smoke_check.py`・CLI テストが読むキー
- `veil` の `vloss_by_kind` / `report_loss_by_kind` / `curse_by_kind`、`shadow` の `vloss_mean` / `played_loss_mean` ＝ `run_shadow` の `"vloss"`・`selfplay_arm_summary` の `shadow_vloss_mean` / `shadow_played_loss_mean`
- `report_sgf` の `"ai"` ＝黒・`"opp"` ＝白 ＝ `format_report_sgf`・`smoke_check.py` の対応
- plan のキー `config_path`・`write_pool`・`shadow`・`hp_audit` ＝ `_resume`・`cmd_calibrate`・`make_hooks_factory` が読むキー。`plan_conditions` が見るキー（`size`・`komi`・`komi_shift`・`rules`・`max_moves`・`watch_flags`・`target`・`opponent`・`resign`）＝ `make_plan` の出力
- Task 6 Step 4 の Edit の old_string（5か所）＝ Task 5 の `selfplay.py` の本文（`_plan_run` の中の null ガードの行・`extra=` と `return stub, plan`・`cmd_run` の `_new_output(... "run")` と `execute_plan` の2行・`--watch-flags` の行・import の行）。どれも1回だけ現れることをスナップショットで確かめた
- テストの件数: stats 47・opponent 12・runner 22・run 10・cli 10・hooks 8（累計 59 / 81 / 91 / 101 / 109）
