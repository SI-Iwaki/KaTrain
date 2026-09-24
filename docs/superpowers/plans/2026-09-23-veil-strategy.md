# 韜晦（9/13/19路）戦略 ai:veil9 / ai:veil13 / ai:veil19 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 9/13/19路それぞれ専用の新戦略 `ai:veil9` / `ai:veil13` / `ai:veil19`（韜晦）を追加し、自己対局ハーネスで 13路の既定値を校正する。勝ちを最優先にしたまま、自分の AI 最善手一致率（KaTrain の終局レポートの値）を絶対目標（13路 30%）まで下げる＝ほぼ損失ゼロの外しは常に、損をする外しは一致率が目標を超えているときだけリードの余剰から払う。

**Architecture:** `Veil9Strategy(Enigma9Strategy)` が `_generate_move` を上書き（spec §4 の S0〜S20）し、13/19路は属性（`BOARD_LEN` / `KEY_PREFIX` / `LABEL` / `SETTING_DEFAULTS` / `VEIL_BOARD`）だけのサブクラス。判断はすべて `veil_*` 純関数（ai.py の `Mimic13Strategy` の後・`ScoreLossStrategy` の前）に切り出して境界値テストし、流れはエンジンなしのスタブ `_Harness` で通しテストする。難解の `_run_query` / `_probe_children` / `_terminal_band_move` / `_cancel_ponder` / `generate_move`（時間ログ）を継承して使い、既存戦略には触らない（ai.py は import 行の追記と新ブロックの追加だけ）。校正は先行計画の自己対局ハーネスで段階1〜3を回し、境界線をユーザーに見せて安全条件以外の既定値を選んでもらう。

**Tech Stack:** Python 3.12 / pytest（KataGo・Kivy 不要のスタブテスト）/ `katrain_debug`（KataGo 起動の単一局面確認）/ `katrain_debug.selfplay`（自己対局ハーネス・先行計画で実装済み）

**Spec:** `docs/superpowers/specs/2026-09-23-veil-strategy-design.md`（ハーネスの spec は `docs/superpowers/specs/2026-09-23-selfplay-harness-design.md`。ハーネスの計画 `docs/superpowers/plans/2026-09-23-selfplay-harness.md` を**先に実行し終えている**ことが前提＝Task 0 で確かめる）

## Global Constraints

- **勝ちが最優先**（spec 要件1）。安全条件＝`reserve`（9/13/19路 3.0 / 5.0 / 7.0 目）と `min_winrate`（0.85）は緩めない。変えるのはユーザーが要件1を再決定したときだけ（Task 16）。「攻め」プリセット（reserve 3・min_winrate 0.75・max_loss 6・spend_rate 1.0・dominant_max_loss 3・yose_max_loss 2）は測定専用。
- 一致率は**終局レポートと同じ定義**（spec 要件2・§5）: 分母＝着手があり root でないノードのうち `points_lost` が None でないもの、一致＝`parent.analysis_complete and parent.candidate_moves[0]["move"] == move.gtp()`。パスも数え、相手は切り揃えない（`parity9_match_tally` の切り揃えた数は比較用に `Rate:` 行へ出すだけ）。避ける最善手は親局面の通常解析の `candidate_moves[0]`。
- 目標は絶対値 `target_rate`（9路 0.40・13/19路 0.30・値域 0.15〜0.50）。`p_match = (mine+1)/(n+1)`、`u = clamp((p_match − T)/0.10, 0, 1)`、`p_match <= 0.15` なら u = 0 で、さらに同値の閾値を 0.1 に下げ罠のゲート閉時経路も止める。
- 同値外し（free）は u に関係なく常に（要件5）。支払う外し（paid）と明らかな一手（最善手の hp >= `dominant_hp`）の外しは u > 0 のときだけ。
- 予算（spec §6）: `F_eff = free_loss`（lead < −1 か p_match <= 0.15 なら min(free_loss, 0.1)）、`S = lead − reserve`、`A_t = 0`（u == 0 か S <= 0）、それ以外 `A_t = min(S, F + u × (max(F, min(cap, spend_rate × S)) − F))`。cap はヨセ前 `max_loss`・ヨセ中 `yose_max_loss`。明らかな一手は `A_t' = min(A_t, dominant_max_loss)`（絞るだけ）。
- 罠（spec §7）: `price = max(0, vloss) − 0.5 × ΔE`。資格 ΔE >= trap_min_delta_e・find_hp <= 0.25・hp >= 0.02。安全条件は vloss で判定（割り引かない）。素の外し P は罠 Q が P の cost より 0.3 目以上安いときだけ Q に替える。既定 OFF。
- 既定値は spec §6.1 の表（Task 9a・11 のコードとテストの `SPEC_DEFAULTS` に写してある）。`VEIL_BOARD`: endgame_move 30 / 85 / 150・unsettled_max 8 / 16 / 36・trusted_visits 100 / 50 / 50・probe_hp 3 / 3 / 3・probe_cheap 2 / 2 / 1。
- **ponder を起動しない**（`_start_ponder` を呼ばない）。HumanStyle へ委譲しない。全フェイルセーフは `_best_move`。`AnalysisDiscardedException` だけは再送出する。
- **難解（enigma9/13/19・各 plus）と擬態（mimic13）はビット同一**。`ai.py` の変更は「import 行への追記」「`import json` / `from dataclasses import dataclass` の追加」「`@register_strategy(AI_SCORELOSS)` の直前への新ブロック追加」だけ。
- **既存の `.py`（`katrain/core/ai.py`・`katrain/core/constants.py`・`katrain_debug/runner.py`）は CRLF かつ black 未整形。Edit/Write ツールで触らない**（PostToolUse フックが black で全体を再整形する）。必ず下の `crlf_patch.py` を使うパッチスクリプトで書き換える。CRLF かどうかは python の `b"\r\n" in open(p, "rb").read()` で判定し、grep では判定しない。既存の `.json` / `.po` / `.md` / `.html` も CRLF を保つためパッチスクリプトで書き換える。新規ファイル `tests/test_ai_veil.py` は Write でよい（載せてあるコードは black 整形済み＝フックで変わらない）。`katrain/gui/ai_help.py` と `tests/test_ai_help_text.py` は LF かつ black 整形済みなので Edit ツールでよい。
- ツールの本文にバックスラッシュ＋u＋16進4桁のエスケープを書かない（変換される）。必要なら `chr()` で組み立てる（この計画のコードには含まれていない）。
- コミット前に `git diff --stat` で**削除行数が想定どおりか**確かめる（再整形の混入検知。各タスクに期待値を書いてある）。**改行コードは `git diff` では見えない**（このリポジトリは `core.autocrlf=true` で、index は LF・作業ツリーは CRLF。作業ツリーの CRLF→LF の反転は差分に出ない）ので、`git ls-files --eol <変更したファイル>` の2列目で確かめる: 既存の CRLF のファイル（`ai.py`・`constants.py`・`runner.py`・`katrain/config.json`・`.po`・`CLAUDE.md`・`.claude/rules/*.md`・`INDEX.md`・マニュアルの `.html`）は `w/crlf` のまま、`katrain/gui/ai_help.py`・`tests/test_ai_help_text.py`・`tests/test_ai_veil.py`（新規）・spec md は `w/lf`。
- コミットメッセージは日本語の Conventional Commits。末尾は `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- **ユーザーの `C:\Users\iwaki\.katrain\config.json` はメインセッションだけが、KaTrain を止めてから編集する**（サブエージェントに委任しない）。
- i18n は `katrain/i18n/locales/<lang>/LC_MESSAGES/katrain.po` を編集してから `python tools/compile_mo.py`。
- テストは `pytest <対象> -q`。KataGo（ハーネス・デバッグ CLI）と並走させない（時間閾値系の偽陽性）。`tests/test_ai.py` の結合テストは humanSL モデルが要る（KataGo 不要なのは `tests/test_ai.py::TestAI::test_order`）。
- `ai.py` を触る前に `.claude/rules/ai-strategies.md` を読む（`ai-parameters.md` / `ai-settings-gui.md` / `ai-humanstyle.md` は必要に応じて grep）。

---

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `katrain/core/ai.py` | `VEIL_*` 定数・`veil_*` 純関数・`VeilCtx`・`Veil9Strategy` / `Veil13Strategy` / `Veil19Strategy` | Modify（パッチスクリプト・追加のみ） |
| `katrain/core/constants.py` | `AI_VEIL_9/13/19`・戦略リスト・`AI_STRENGTH`・`_VEIL_*` 候補値・`AI_OPTION_VALUES` / `AI_OPTION_ORDER`（16 キー × 3 盤） | Modify（パッチスクリプト） |
| `katrain/config.json` | パッケージ既定 `ai:veil9` / `ai:veil13` / `ai:veil19` | Modify（パッチスクリプト） |
| `C:\Users\iwaki\.katrain\config.json` | ユーザー設定（GUI とハーネスが読む） | Modify（**メインセッションだけ**） |
| `katrain/gui/ai_help.py` | 説明欄の共通文面 `aiopt:veil*_<suffix>`（`{p}` 置換） | Modify（Edit） |
| `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po` → `.mo` | 戦略名・概要・16 項目の解説（jp） | Modify（パッチスクリプト）＋ compile |
| `katrain_debug/runner.py` | `--strategy veil9 / veil13 / veil19` | Modify（パッチスクリプト） |
| `tests/test_ai_veil.py` | 純関数・`game_report` との一致・`_generate_move` 通し・登録整合 | Create（タスクごとに追記） |
| `tests/test_ai_help_text.py` | 共通文面の `{p}` 置換と兄弟キー参照の正規表現に veil | Modify（Edit） |
| `docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md`（＋ `veil13-campaign/*.json`） | ハーネス校正の結果・境界線・採否 | Create |
| `.claude/rules/ai-strategies.md` / `ai-parameters.md` / `CLAUDE.md` / `docs/manual/src/06_ai_overview.html` / `06d_ai_parity.html` → `docs/manual/index.html` / `docs/superpowers/specs/INDEX.md` / spec の状態 | ドキュメント（表はコードから生成） | Modify（パッチスクリプト）＋ build |

パッチ用ヘルパー（**リポジトリには入れない**。スクラッチパッドに置く）: `<scratchpad>/crlf_patch.py`

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

`<scratchpad>` は実行するセッションのスクラッチパッド（システムプロンプトに書かれているディレクトリ）。各タスクのパッチスクリプトは同じディレクトリに Write し、**リポジトリのルートを cwd にして**実行する（パッチスクリプトは `.py` なので Write 後にフックで black 整形されることがあるが、埋め込んだコードは文字列なので中身は変わらない）。

**Bash での書き方（`$SP`）**: スクラッチパッドのパスはバックスラッシュ区切りの Windows パス（`C:\Users\iwaki\AppData\...`）なので、そのまま Git Bash に貼るとバックスラッシュが消えてスクリプトが見つからない。Run 行ではスクラッチパッドを `"$SP"` と書く。**Bash ツールはコマンドをまたいでシェル変数を保持しない**ので、`$SP` を使うコマンドは毎回先頭で `SP="$(cygpath -m '<スクラッチパッドの Windows パス>')";` と定義する（例 `SP="$(cygpath -m 'C:\Users\...\scratchpad')"; python "$SP/patch_veil_t1.py"`）か、`$SP` をスラッシュ区切りの絶対パス（`C:/Users/.../scratchpad`）に置き換えて書く。どちらでも**必ずダブルクォートで囲む**（`python "$SP/patch_veil_t1.py"`・`> "$SP/veil_smoke_20.txt" 2>&1`）。

**スクラッチパッドはセッションごと**に別のディレクトリになる。計画を複数のセッションに分けて実行するときは、新しいセッションの最初に Task 0 Step 3（`crlf_patch.py` の Write）をやり直す。Task 16 の `veil_defaults.json` は Task 17 と同じセッションで使う（決定そのものは Task 16 Step 3 で `veil13-campaign.md` にコミットしてあるので、セッションが変わったらそこから作り直す）。

## 共有インターフェース（後続タスク・ハーネス・ログ集計が読む値）

- `Veil9Strategy.last_decision_info`（毎手作り直す dict）と、同じ中身を1行にした `Decision: {json}` ログ（`veil_decision_record`: ASCII のみ・キー順固定・float は小数3桁・NaN は null）。キー:
  `depth` `player` `best` `chosen` `tier` `kind` `why` `queries` `secs` `mine` `n` `opp` `n_opp` `opp_trunc` `p_match` `T` `u` `lead` `root_wr` `unsettled` `in_yose` `reserve` `F` `S` `A_t` `cap` `best_hp` `dominant` `close` `trap_shadow` `raw` `vloss` `cons` `cost` `hp` `d_e` `E` `find_hp` `price` `pass_loss`（手番によって一部だけ。`unsettled` は S6 でヨセ入りを判定した手番だけ＝ヨセ前で `depth >= endgame_move` のとき。ownership が無ければ null）。ハーネス（`selfplay_stats._decision_metrics`）が読むのは `tier` `kind` `best` `chosen` `vloss` `lead` `E` `close` と ledger（キー名を変えない）。
  - `tier`: `"i"`（候補なし）/ `"ii"`（明らかな一手）/ `"iii"`（通常）/ `"terminal"`（相手の直前パス・終局帯）/ `"failsafe"`
  - `kind`（打った手の種類）: `"best"` / `"free"` / `"paid"` / `"trap"` / `"decided"`（決着局面の即決）/ `"swap"`（終局帯の入れ替え）/ `"finish"`（9段の終局処理の手）/ `"pass"`
  - `why`（最善手・フェイルセーフの理由）: `"board"` `"no_cands"` `"pass"` `"no_lead"` `"no_pool"` `"no_hp"` `"dominant_closed"` `"no_natural"` `"no_shortlist"` `"no_best_probe"` `"none_qualified"` `"invariant"` `"error"` `"opp_pass"` `"terminal"`
- `game._veil_state[KEY_PREFIX]` = `{"endgame": bool, "close_drift": float, "ledger": [(depth, best, chosen, kind), ...]}`（Game に載るので対局ごとにリセット）。
- 毎手 `Rate: mine=a/n opp=b/m opp_trunc=c p_match=… target=… u=…` を1行（S4）。ヨセ前で `depth >= endgame_move` の手番は `Endgame check: depth=… thr=… unsettled=… max=… -> yose (sticky)|not yet` を1行（S6。擬態の同名の行と同じ形）。

---

### Task 0: 準備（前提の確認・ブランチ・パッチ用ヘルパー・計画のコミット）

**Files:**
- Create: `<scratchpad>/crlf_patch.py`（File Structure 節のとおり）
- Commit: `docs/superpowers/plans/2026-09-23-veil-strategy.md`

**Interfaces:**
- Consumes: 先行計画の成果 `katrain_debug/selfplay.py` / `katrain_debug/selfplay_stats.py`（`python -m katrain_debug.selfplay run|calibrate|summarize|report-sgf`）
- Produces: `crlf_patch.patch(path, edits)`（以降のパッチスクリプトが `from crlf_patch import patch` で使う）

- [x] **Step 1: 前提（ハーネス計画が完了している）を確かめる**

Run:
```bash
git log --oneline -5
python -c "import os;print(all(os.path.exists(p) for p in ['katrain_debug/selfplay.py','katrain_debug/selfplay_stats.py']))"
python -m katrain_debug.selfplay --help
```
Expected: `True` と、`run` / `calibrate` / `summarize` / `report-sgf` が並ぶヘルプ。`False` かヘルプが出なければ**ここで止める**（ハーネス計画を先に実行する）。

- [x] **Step 2: 作業ブランチを切る**（ハーネスの成果が入っているブランチから。master にマージ済みなら master から）
  （ブランチは `git worktree add -b feature/veil-strategy` で作成済み＝確認だけ）

```bash
git status --short
git checkout -b feature/veil-strategy
SP="$(cygpath -m '<スクラッチパッドの Windows パス>')"; git rev-parse HEAD | tee "$SP/veil_base.txt"
```
（最後の行＝計画のコミット前の HEAD＝この計画の差分の基準。Task 19 Step 2 はこれを Step 5 の計画コミットの親としてコミット履歴から取り直すので、セッションが変わっても失われない。`veil_base.txt` は同じセッションでの突き合わせ用）

- [x] **Step 3: `<scratchpad>/crlf_patch.py` を Write**（内容は File Structure 節のとおり）

- [x] **Step 4: 触る前の既存テストが緑であることを確かめる**

Run: `pytest tests/test_ai_mimic13.py tests/test_ai_enigma_plus.py tests/test_ai_enigma9.py tests/test_ai_help_text.py tests/test_ai.py::TestAI::test_order -q`
Expected: 全 PASS（落ちるなら韜晦とは無関係の既存の問題＝先に報告して止める）
Run: `pytest tests/test_ai.py::TestAI::test_ai_rank_estimation -q`
Expected: `1 failed`（`assert -20 <= nan`）＝**既知の失敗**。HEAD `3f4c4a00` の時点で、`AI_STRENGTH` が nan の戦略（parity9・enigma9/9plus/13/13plus/19/19plus・mimic13・siege・hunt・hunt_diverge・tsumego・tsumego_solver）で `ai_rank_estimation` が nan を返すので落ちている。この計画では直さない（veil9/13/19 も同じく nan）。落ち方がこれと違えば報告する。

- [x] **Step 5: 計画をコミット**

```bash
git add docs/superpowers/plans/2026-09-23-veil-strategy.md
git commit -m "docs(veil): 韜晦（9/13/19路）戦略の実装計画

純関数（一致率・予算・候補・分類・選択・罠・終局帯・不変条件）→ Veil9 の決定フロー S0〜S20 →
13/19路 → 登録 → デバッグ CLI → 自己対局ハーネスでの校正とユーザーの既定値選択 → ドキュメントの順。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 1: モジュール定数と一致率の集計 `veil_tally`

**Files:**
- Modify: `katrain/core/ai.py`（`@register_strategy(AI_SCORELOSS)` の直前＝`Mimic13Strategy` の後に追加）
- Create: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: `game_report(game, thresholds, depth_filter=None)`（ai.py 既存・比較の基準）
- Produces: 定数 `VEIL_TARGET_FLOOR=0.15` `VEIL_URGENCY_WIDTH=0.10` `VEIL_STRICT_FREE=0.1` `VEIL_BEHIND_LIMIT=-1.0` `VEIL_YOSE_FREE_WR_DROP=0.01` `VEIL_CLOSE_WR=0.9` `VEIL_DECIDED_WR=0.97` `VEIL_DECIDED_MARGIN=3.0` `VEIL_TERMINAL_MAX=0.10` `VEIL_TERMINAL_CLOSE_MAX=0.05` `VEIL_TERMINAL_CLOSE_LEAD=3.0` `VEIL_TERMINAL_MIN_VISITS=10` `VEIL_RAW_MARGIN=0.3` `VEIL_TRAP_CREDIT=0.5` `VEIL_TRAP_MIN_HP=0.02` `VEIL_TRAP_PROBES=3` `VEIL_TRAP_RAW_EXTRA=1.0` `VEIL_TRAP_SWAP_MARGIN=0.3` `VEIL_HP_TIE=0.02` と内部用 `_VEIL_EPS=1e-9`（上限比較の許容誤差）。
  `veil_tally(nodes, ai_player) -> (mine: int, n_mine: int, opp: int, n_opp: int)`（nodes は `cn.nodes_from_root`・root 込みでよい）

- [x] **Step 1: 失敗するテストを書く** — `tests/test_ai_veil.py` を Write（本物の `GameNode` で木を作り、本物の `game_report` と数を突き合わせる。未完了の親・パス・未解析のノード・白番で相手が1手多い・ランダムな木 40 本）

```python
# tests/test_ai_veil.py
"""「韜晦（9/13/19路）」ai:veil9 / ai:veil13 / ai:veil19 の純関数・登録整合・_generate_move 通しテスト。

KataGo / Kivy 不要。設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md
"""

import json
import random
import types

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import (
    game_report,
    veil_tally,
)
from katrain.core.game_node import GameNode
from katrain.core.sgf_parser import Move

THRESHOLDS = [12, 6, 3, 1.5, 0.5, 0]


def _analyze(node, best, complete=True):
    """通常解析を模す。best が candidate_moves[0]（order 0）、A1/B2/C3 のうち best 以外がその後ろ。"""
    others = [g for g in ("A1", "B2", "C3") if g != best]
    node.analysis["moves"] = {
        gtp: {"move": gtp, "order": order, "scoreLead": 0.0, "winrate": 0.5, "prior": 0.1, "visits": 100}
        for order, gtp in enumerate([best, *others])
    }
    node.analysis["root"] = {"scoreLead": 0.0, "winrate": 0.5, "visits": 100}
    node.analysis["completed"] = complete


def _tree(moves, analyses):
    """13路の木（本物の GameNode）。moves: [(player, gtp)]。analyses: root から順に各局面の
    (best, complete) か None（未解析＝その局面へ打った手の points_lost が None になる）。"""
    nodes = [GameNode(properties={"SZ": 13})]
    for player, gtp in moves:
        nodes.append(GameNode(parent=nodes[-1], move=Move.from_gtp(gtp, player=player)))
    for node, a in zip(nodes, analyses):
        if a is not None:
            _analyze(node, *a)
    return nodes


def _report_counts(last):
    """本物の game_report から (一致数, 分母) を色ごとに取り出す。"""
    game = types.SimpleNamespace(current_node=last, board_size=(13, 13))
    stats, _histogram, ptloss = game_report(game, THRESHOLDS)
    out = {}
    for bw in "BW":
        n = len(ptloss[bw])
        out[bw] = (round(stats[bw]["ai_top_move"] * n) if n else 0, n)
    return out


class TestTally:
    def test_matches_game_report_with_pass_incomplete_parent_and_unanalyzed_node(self):
        moves = [("B", "D4"), ("W", "K10"), ("B", "C3"), ("W", "L11"), ("B", "pass"), ("W", "D10")]
        analyses = [("D4", True), ("K10", True), ("C4", True), ("L11", False), ("pass", True), ("D10", True), None]
        nodes = _tree(moves, analyses)
        # 黒: D4 一致・C3 不一致・pass 一致 → 2/3。白: K10 一致・L11 は親が未完了（分母だけ）・
        # D10 は打った後の局面が未解析（points_lost None＝数えない）→ 1/2
        assert veil_tally(nodes[-1].nodes_from_root, "B") == (2, 3, 1, 2)
        report = _report_counts(nodes[-1])
        assert report == {"B": (2, 3), "W": (1, 2)}

    def test_white_ai_opponent_has_one_more_move_and_is_not_truncated(self):
        moves = [("B", "D4"), ("W", "K10"), ("B", "C3"), ("W", "L11"), ("B", "E5")]
        analyses = [("D4", True), ("K10", True), ("C3", True), ("A1", True), ("E5", True), ("A1", True)]
        nodes = _tree(moves, analyses)
        mine, n_mine, opp, n_opp = veil_tally(nodes[-1].nodes_from_root, "W")
        assert (mine, n_mine, opp, n_opp) == (1, 2, 3, 3)
        report = _report_counts(nodes[-1])
        assert (mine, n_mine) == report["W"] and (opp, n_opp) == report["B"]

    def test_random_trees_match_game_report_exactly(self):
        rng = random.Random(20260923)
        gtps = ["D4", "K10", "C3", "L11", "E5", "pass", "A1", "B2"]
        for _ in range(40):
            length = rng.randint(1, 30)
            moves = [("B" if i % 2 == 0 else "W", rng.choice(gtps)) for i in range(length)]
            analyses = []
            for i in range(length + 1):
                if rng.random() < 0.15:
                    analyses.append(None)
                else:
                    best = moves[i][1] if i < length and rng.random() < 0.5 else rng.choice(gtps)
                    analyses.append((best, rng.random() < 0.85))
            nodes = _tree(moves, analyses)
            report = _report_counts(nodes[-1])
            for ai in "BW":
                opp = "W" if ai == "B" else "B"
                assert veil_tally(nodes[-1].nodes_from_root, ai) == (*report[ai], *report[opp])

    def test_root_only_is_empty(self):
        root = GameNode(properties={"SZ": 13})
        assert veil_tally(root.nodes_from_root, "B") == (0, 0, 0, 0)
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'veil_tally' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t1.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
# ===== 「韜晦」戦略 ai:veil9 / ai:veil13 / ai:veil19 の定数と純関数群 =====
# 設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md
#
# 勝ちを最優先にしたまま、自分の AI 最善手一致率（KaTrain の終局レポートの値）を絶対目標
# `<prefix>_target_rate` まで下げる。ほぼ損失ゼロの外し（free＝同値外し）は一致率に関係なく常に行い、
# 損をする外し（paid）は一致率が目標を超えている間（緊急度 u > 0）だけリードの余剰
# S = lead − reserve から払う。外しはすべて子局面プローブで検証し、最安帯の中で humanPolicy 最大の手を
# 選ぶ。罠（ΔE）は `<prefix>_trap_mode` で足す A/B 用の上乗せ層。ponder（先読み）は使わない。

VEIL_TARGET_FLOOR = 0.15         # この一致率以下へは払わない（理想帯 15〜35% の下端）
VEIL_URGENCY_WIDTH = 0.10        # 緊急度 u = (p_match − T) / これ を 0〜1 にクランプ
VEIL_STRICT_FREE = 0.1           # 劣勢（lead < VEIL_BEHIND_LIMIT）か p_match <= VEIL_TARGET_FLOOR のときの同値の閾値（目）
VEIL_BEHIND_LIMIT = -1.0         # これ未満のリードは劣勢扱い
VEIL_YOSE_FREE_WR_DROP = 0.01    # ヨセで着手後リードが reserve 未満のとき、同値外しに許す勝率低下
VEIL_CLOSE_WR = 0.9              # 最善手の着手後勝率がこれ未満なら「接戦」
VEIL_DECIDED_WR = 0.97           # 決着局面の勝率（即決経路・同値外しの勝率条件の免除）
VEIL_DECIDED_MARGIN = 3.0        # 決着局面の即決に要る reserve 超過分（目）
VEIL_TERMINAL_MAX = 0.10         # 終局帯の入れ替えに許す生の loss（目）
VEIL_TERMINAL_CLOSE_MAX = 0.05   # 同・|lead| < VEIL_TERMINAL_CLOSE_LEAD のとき（持碁の落とし穴を避ける）
VEIL_TERMINAL_CLOSE_LEAD = 3.0   # 終局帯の「接戦」の境（目）
VEIL_TERMINAL_MIN_VISITS = 10    # 終局帯の入れ替えに要る visits
VEIL_RAW_MARGIN = 0.3            # 生の loss の足切りに持たせる余裕（目）。生の loss はノイズが大きく検証で救える手がある
VEIL_TRAP_CREDIT = 0.5           # 罠の値段で ΔE を信用する割合（実損 ≈ 1.06×E・R²=0.18 なので半分だけ）
VEIL_TRAP_MIN_HP = 0.02          # 罠に要る humanPolicy（自然さの床は免除）
VEIL_TRAP_PROBES = 3             # 罠枠のプローブ数
VEIL_TRAP_RAW_EXTRA = 1.0        # 罠用プールの生の loss の上乗せ（目）
VEIL_TRAP_SWAP_MARGIN = 0.3      # 素の外し P を罠 Q に替えるのに要る値段の差（目）
VEIL_HP_TIE = 0.02               # hp の同点幅（この差以内なら余剰がある手番は着手後勝率を優先）
_VEIL_EPS = 1e-9                 # 上限比較の浮動小数の許容誤差


def veil_tally(nodes, ai_player):
    """終局レポート（`game_report`）と同じ定義で両者の AI 最善手一致数と分母を返す: (mine, n_mine, opp, n_opp)。

    nodes は `cn.nodes_from_root`（root 込みでよい）。着手があり root でないノードのうち `points_lost` が
    None でないものが分母、そのうち親局面の解析が完了していて `candidate_moves[0]` と着手の gtp が
    一致するものが分子（`game_report` の ai_top_move_count と同一式）。パスも数え、相手は切り揃えない
    （切り揃えるのは比較用の `parity9_match_tally` だけ）。
    """
    counts = {"B": [0, 0], "W": [0, 0]}
    for n in nodes:
        if not n.move or n.is_root:
            continue
        if n.points_lost is None:
            continue
        row = counts[n.player]
        row[1] += 1
        parent = n.parent
        if parent.analysis_complete:
            cands = parent.candidate_moves
            if cands and cands[0]["move"] == n.move.gtp():
                row[0] += 1
    opp = "W" if ai_player == "B" else "B"
    return counts[ai_player][0], counts[ai_player][1], counts[opp][0], counts[opp][1]
'''

patch("katrain/core/ai.py", [(ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t1.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `4 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 56 +++…`（削除 0 行）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 韜晦の定数と一致率の集計 veil_tally（終局レポートと同一定義）

分母は points_lost が None でない着手、一致は親の解析完了かつ candidate_moves[0] と同じ手。
パスも数え相手は切り揃えない。合成木で game_report と完全一致することをテストで固定。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 緊急度・同値の閾値・支払い枠（`veil_urgency` / `veil_free_limit` / `veil_allowance`）

**Files:**
- Modify: `katrain/core/ai.py`（同じ位置に追記）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: Task 1 の `VEIL_URGENCY_WIDTH` / `VEIL_TARGET_FLOOR` / `VEIL_BEHIND_LIMIT` / `VEIL_STRICT_FREE`
- Produces:
  - `veil_urgency(mine, n, target, width=VEIL_URGENCY_WIDTH, floor=VEIL_TARGET_FLOOR) -> (p_match: float, u: float)`
  - `veil_free_limit(free_loss, lead, p_match, behind_limit=VEIL_BEHIND_LIMIT, floor=VEIL_TARGET_FLOOR, strict=VEIL_STRICT_FREE) -> float`（F_eff）
  - `veil_allowance(lead, reserve, spend_rate, free, cap, u) -> (A_t: float, S: float)`

- [x] **Step 1: 失敗するテストを書く** — `tests/test_ai_veil.py` の `from katrain.core.ai import (` 〜 `)` のブロックを次に置き換え（Edit）

```python
from katrain.core.ai import (
    game_report,
    veil_allowance,
    veil_free_limit,
    veil_tally,
    veil_urgency,
)
```

ファイル末尾に（空行2つを挟んで）追記（spec §6 の目安をそのままテストケースにする）:

```python
class TestUrgency:
    def test_empty_history_is_fully_urgent(self):
        assert veil_urgency(0, 0, 0.30) == (1.0, 1.0)

    @pytest.mark.parametrize(
        "mine,n,expected_p,expected_u",
        [
            (3, 9, 0.40, 1.0),  # 目標を 10pt 超過 → 全開
            (6, 19, 0.35, 0.5),  # 5pt 超過 → 半分
            (2, 9, 0.30, 0.0),  # ちょうど目標 → 閉
            (4, 19, 0.25, 0.0),  # 目標未満 → 閉
        ],
    )
    def test_linear_ramp_over_ten_points(self, mine, n, expected_p, expected_u):
        p_match, u = veil_urgency(mine, n, 0.30)
        assert p_match == pytest.approx(expected_p)
        assert u == pytest.approx(expected_u)

    def test_at_or_below_the_floor_is_closed_even_for_a_lower_target(self):
        assert veil_urgency(2, 19, 0.10)[1] == 0.0  # p_match = 0.15（床ちょうど）
        assert veil_urgency(3, 19, 0.10)[1] == pytest.approx(1.0)  # p_match = 0.20


class TestFreeLimit:
    def test_normal_position_uses_free_loss(self):
        assert veil_free_limit(0.3, 0.5, 0.40) == 0.3
        assert veil_free_limit(0.3, -1.0, 0.40) == 0.3  # ちょうど −1 はまだ劣勢でない

    def test_behind_or_low_rate_is_strict(self):
        assert veil_free_limit(0.3, -1.5, 0.40) == pytest.approx(0.1)
        assert veil_free_limit(0.3, 5.0, 0.15) == pytest.approx(0.1)

    def test_strict_never_raises_a_smaller_free_loss(self):
        assert veil_free_limit(0.0, -3.0, 0.10) == 0.0


class TestAllowance:
    """spec §6 の目安（13路・reserve 5・spend_rate 0.5・F_eff 0.3・u = 1）。"""

    @pytest.mark.parametrize("lead,expected", [(5.0, 0.0), (7.0, 1.0), (10.0, 2.5), (14.0, 4.5), (20.0, 4.5)])
    def test_before_yose_cap_4_5(self, lead, expected):
        a_t, surplus = veil_allowance(lead, 5.0, 0.5, 0.3, 4.5, 1.0)
        assert a_t == pytest.approx(expected)
        assert surplus == pytest.approx(lead - 5.0)

    @pytest.mark.parametrize("lead,expected", [(5.0, 0.0), (6.5, 0.75), (8.0, 1.5), (12.0, 1.5)])
    def test_in_yose_cap_1_5(self, lead, expected):
        assert veil_allowance(lead, 5.0, 0.5, 0.3, 1.5, 1.0)[0] == pytest.approx(expected)

    def test_closed_gate_pays_nothing(self):
        assert veil_allowance(20.0, 5.0, 0.5, 0.3, 4.5, 0.0) == (0.0, 15.0)

    def test_partial_urgency_interpolates_from_free(self):
        assert veil_allowance(10.0, 5.0, 0.5, 0.3, 4.5, 0.5)[0] == pytest.approx(0.3 + 0.5 * (2.5 - 0.3))

    def test_small_surplus_gives_the_smaller_of_free_and_surplus(self):
        assert veil_allowance(5.2, 5.0, 0.5, 0.3, 4.5, 1.0)[0] == pytest.approx(0.2)

    @pytest.mark.parametrize("u", [0.25, 0.5, 1.0])
    def test_cap_below_free_does_not_shrink_with_urgency(self, u):
        assert veil_allowance(8.0, 5.0, 0.5, 0.3, 0.0, u)[0] == pytest.approx(0.3)

    def test_never_exceeds_the_surplus(self):
        for lead in [5.05, 5.1, 5.3, 6.0, 9.0, 15.0, 40.0]:
            for u in [0.1, 0.5, 1.0]:
                a_t, surplus = veil_allowance(lead, 5.0, 1.0, 0.3, 6.0, u)
                assert a_t <= surplus + 1e-12
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'veil_allowance' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t2.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
def veil_urgency(mine, n, target, width=VEIL_URGENCY_WIDTH, floor=VEIL_TARGET_FLOOR):
    """この手も一致させた場合の一致率 p_match = (mine+1)/(n+1) と緊急度 u（0〜1）を返す: (p_match, u)。

    u = clamp((p_match − target) / width, 0, 1)。p_match <= floor なら u = 0（15% 未満へ無駄に払わない）。
    u > 0 が「ゲートが開いている」＝支払う外しと明らかな一手の外しが許される。u == 0 でも同値外しは続ける。
    """
    p_match = (mine + 1) / (n + 1)
    if p_match <= floor:
        return p_match, 0.0
    if width <= 0:
        return p_match, 1.0 if p_match > target else 0.0
    return p_match, min(1.0, max(0.0, (p_match - target) / width))


def veil_free_limit(free_loss, lead, p_match, behind_limit=VEIL_BEHIND_LIMIT, floor=VEIL_TARGET_FLOOR,
                    strict=VEIL_STRICT_FREE):
    """同値外しの閾値 F_eff（目）。劣勢（lead < behind_limit）か p_match <= floor では strict まで下げる。"""
    if lead < behind_limit or p_match <= floor:
        return min(free_loss, strict)
    return free_loss


def veil_allowance(lead, reserve, spend_rate, free, cap, u):
    """支払う外し1回の許容損失 A_t と余剰 S を返す: (A_t, S)。

    S = lead − reserve。u == 0 か S <= 0 なら A_t = 0（支払う外しなし）。それ以外は
    A_lead = max(free, min(cap, spend_rate × S))、A_t = min(S, free + u × (A_lead − free))。
    cap はヨセ前 max_loss・ヨセ中 yose_max_loss。max(free, …) を先に取るので cap < free でも
    A_t は u について減らない。A_t <= S なので支払う外しだけで reserve を割ることはない。
    """
    surplus = lead - reserve
    if u <= 0 or surplus <= 0:
        return 0.0, surplus
    a_lead = max(free, min(cap, spend_rate * surplus))
    return min(surplus, free + u * (a_lead - free)), surplus
'''

patch("katrain/core/ai.py", [(ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t2.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `29 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 37 +++…`・`tests/test_ai_veil.py` は追加のみ（削除はテストの import ブロックの置き換え分だけ）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 緊急度・同値の閾値・支払い枠（veil_urgency / veil_free_limit / veil_allowance）

u = clamp((p_match − T)/0.10, 0, 1)（p_match <= 0.15 は 0）。A_t は余剰を超えず、
cap < F_eff でも u について減らない。spec §6 の目安（ヨセ前 4.5・ヨセ 1.5）をテストで固定。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 自然さの床・生の足切り・検証候補（`veil_natural_floor` / `veil_prefilter` / `veil_shortlist`）

**Files:**
- Modify: `katrain/core/ai.py`
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: 既存の `mimic_natural_floor(hp_top, min_hp, ratio)`・`enigma9_shortlist_spread(pool, base_k, extra, trusted_visits)`・`ENIGMA9_TRUSTED_VISITS`
- Produces:
  - `veil_natural_floor(hp_top, min_hp, ratio, dominant) -> float`
  - `veil_prefilter(pool0, raw_cap) -> list`（pool0 は `parity9_build_candidates` の `{"gtp","loss","visits","wr"}`）
  - `veil_shortlist(naturals, trap_cands, hp_of, band_cap, probe_hp, probe_cheap, trap_probes, trusted_visits=ENIGMA9_TRUSTED_VISITS) -> (nat: list, traps: list)`

- [x] **Step 1: 失敗するテストを書く** — import ブロックを次に置き換え（Edit）

```python
from katrain.core.ai import (
    game_report,
    veil_allowance,
    veil_free_limit,
    veil_natural_floor,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_urgency,
)
```

ファイル末尾に追記:

```python
def cand(gtp, loss, visits=100):
    return {"gtp": gtp, "loss": loss, "visits": visits, "wr": 0.5}


def hp_table(values):
    return lambda gtp: values.get(gtp, 0.0)


class TestNaturalFloor:
    def test_relative_floor_applies_when_not_dominant(self):
        assert veil_natural_floor(0.40, 0.05, 0.2, dominant=False) == pytest.approx(0.08)
        assert veil_natural_floor(0.10, 0.05, 0.2, dominant=False) == pytest.approx(0.05)

    def test_dominant_uses_only_the_absolute_floor(self):
        assert veil_natural_floor(0.90, 0.05, 0.2, dominant=True) == pytest.approx(0.05)


class TestPrefilter:
    def test_keeps_moves_within_the_raw_cap_and_drops_pass(self):
        pool0 = [cand("D4", 0.2), cand("K10", 0.61), cand("pass", 0.0), cand("C3", 0.6)]
        assert [c["gtp"] for c in veil_prefilter(pool0, 0.6)] == ["D4", "C3"]


class TestShortlist:
    def test_hp_top_then_cheapest_of_the_rest_within_the_band(self):
        naturals = [cand("A", 0.9), cand("B", 0.1), cand("C", 0.5), cand("D", 0.3), cand("E", 0.2), cand("F", 2.0)]
        hp = hp_table({"A": 0.30, "B": 0.10, "C": 0.25, "D": 0.20, "E": 0.09, "F": 0.50})
        nat, traps = veil_shortlist(naturals, [], hp, 1.0, 3, 2, 0)
        # F は帯（1.0）の外。hp 上位 A/C/D → 残り B(0.1)・E(0.2) を安い順
        assert [c["gtp"] for c in nat] == ["A", "C", "D", "B", "E"]
        assert traps == []

    def test_cheap_slots_can_be_zero(self):
        naturals = [cand("A", 0.2), cand("B", 0.1)]
        nat, _ = veil_shortlist(naturals, [], hp_table({"A": 0.3, "B": 0.2}), 1.0, 1, 0, 0)
        assert [c["gtp"] for c in nat] == ["A"]

    def test_trap_slots_are_spread_over_the_rest_and_never_change_the_natural_slots(self):
        naturals = [cand("A", 0.2), cand("B", 0.4)]
        trap_cands = [
            cand("A", 0.2),
            cand("T1", 0.5),
            cand("T2", 1.0),
            cand("T3", 1.5),
            cand("T4", 2.0),
            cand("T5", 2.5),
        ]
        hp = hp_table({"A": 0.3, "B": 0.2, "T1": 0.03, "T2": 0.03, "T3": 0.03, "T4": 0.03, "T5": 0.03})
        nat_off, traps_off = veil_shortlist(naturals, trap_cands, hp, 1.0, 3, 2, 0)
        nat_on, traps_on = veil_shortlist(naturals, trap_cands, hp, 1.0, 3, 2, 3)
        assert [c["gtp"] for c in nat_on] == [c["gtp"] for c in nat_off] == ["A", "B"]
        assert traps_off == []
        # 自然枠に入った A は罠枠に出ない。残り5手から loss の範囲に等間隔（両端込み）
        assert [c["gtp"] for c in traps_on] == ["T1", "T3", "T5"]
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'veil_natural_floor' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t3.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
def veil_natural_floor(hp_top, min_hp, ratio, dominant):
    """「人間らしい外し」に要求する humanPolicy の床。

    明らかな一手（dominant）の手番は絶対床 min_hp だけ（第一感が1点に集中しているので相対床を掛けると
    代替手が消える）。それ以外は `mimic_natural_floor`＝max(min_hp, ratio × hp_top)。
    """
    if dominant:
        return min_hp
    return mimic_natural_floor(hp_top, min_hp, ratio)


def veil_prefilter(pool0, raw_cap):
    """生の loss（relativePointsLost）が raw_cap 以下の候補（pass は除く）。プローブ前の足切り（クエリ0本）。"""
    return [c for c in pool0 if c["gtp"] != "pass" and c["loss"] <= raw_cap]


def veil_shortlist(naturals, trap_cands, hp_of, band_cap, probe_hp, probe_cheap, trap_probes,
                   trusted_visits=ENIGMA9_TRUSTED_VISITS):
    """子局面プローブに回す候補を (自然枠, 罠枠) で返す。

    自然枠: 生の loss が band_cap 以内の自然な候補から hp 降順に probe_hp 手（同点は loss → gtp）、
    残りから生の loss の安い順に probe_cheap 手（同点は visits 多い順 → gtp）。
    罠枠: 罠用の候補のうち自然枠に入らなかった手から、`enigma9_shortlist_spread` で loss の範囲に
    等間隔に trap_probes 手（0 なら空）。罠枠の有無で自然枠は変わらない（罠 ON/OFF のクエリ列は罠枠だけが違う）。
    """
    band = [c for c in naturals if c["loss"] <= band_cap]
    top = sorted(band, key=lambda c: (-hp_of(c["gtp"]), c["loss"], c["gtp"]))[: max(0, int(probe_hp))]
    taken = {c["gtp"] for c in top}
    rest = sorted(
        [c for c in band if c["gtp"] not in taken],
        key=lambda c: (c["loss"], -c.get("visits", 0), c["gtp"]),
    )
    nat = top + rest[: max(0, int(probe_cheap))]
    taken = {c["gtp"] for c in nat}
    if int(trap_probes) <= 0:
        return nat, []
    trap_rest = [c for c in trap_cands if c["gtp"] not in taken]
    return nat, enigma9_shortlist_spread(trap_rest, 0, int(trap_probes), trusted_visits)
'''

patch("katrain/core/ai.py", [(ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t3.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `35 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 40 +++…`（削除 0 行）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 自然さの床・生の足切り・検証候補（veil_natural_floor / veil_prefilter / veil_shortlist）

自然枠は帯の中の hp 上位＋安い順、罠枠は残りから loss の範囲に等間隔。罠枠の有無で自然枠は変わらない。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 外しの分類（`VeilCtx` / `veil_cons_loss` / `veil_near_free_ok` / `veil_paid_ok` / `veil_close_drift_ok` / `veil_classify`）

**Files:**
- Modify: `katrain/core/ai.py`（`from dataclasses import dataclass` を import に追加し、定義を追記）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: Task 1 の `VEIL_DECIDED_WR` / `VEIL_YOSE_FREE_WR_DROP` / `_VEIL_EPS`
- Produces:
  - `@dataclass VeilCtx(lead, reserve, surplus, urgency, p_match, f_eff, allowance, trap_cap, min_winrate, free_wr_drop, in_yose, close, close_drift, close_drift_cap, trap_min_delta_e)`（すべてキーワードで作る）
  - `veil_cons_loss(vloss, raw, visits, trusted) -> float`
  - `veil_near_free_ok(cost, wr_drop, wr_after, lead_after, ctx) -> bool`
  - `veil_paid_ok(cost, wr_after, ctx) -> bool`
  - `veil_close_drift_ok(close, drift, vloss, cap) -> bool`
  - `veil_classify(c, ctx) -> (kind: "free"|"paid"|None, cost: float)`（c は `{"cons","vloss","wr_drop","wr_after","lead_after"}`）

- [x] **Step 1: 失敗するテストを書く** — import ブロックを次に置き換え（Edit）

```python
from katrain.core.ai import (
    VeilCtx,
    game_report,
    veil_allowance,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_free_limit,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_urgency,
)
```

ファイル末尾に追記:

```python
def ctx(**kw):
    """13路の既定に近い判定コンテキスト（lead 12・u 1・A_t' 3.5・ヨセ前・接戦でない）。"""
    base = dict(
        lead=12.0,
        reserve=5.0,
        surplus=7.0,
        urgency=1.0,
        p_match=0.5,
        f_eff=0.3,
        allowance=3.5,
        trap_cap=4.5,
        min_winrate=0.85,
        free_wr_drop=0.03,
        in_yose=False,
        close=False,
        close_drift=0.0,
        close_drift_cap=0.0,
        trap_min_delta_e=0.5,
    )
    base.update(kw)
    return VeilCtx(**base)


def row(cons, vloss=None, wr_drop=0.01, wr_after=0.93, lead_after=11.0):
    vloss = cons if vloss is None else vloss
    return {"cons": cons, "vloss": vloss, "wr_drop": wr_drop, "wr_after": wr_after, "lead_after": lead_after}


class TestConsLoss:
    def test_trusted_candidate_also_counts_the_raw_loss(self):
        assert veil_cons_loss(0.1, 0.25, visits=200, trusted=50) == 0.25
        assert veil_cons_loss(0.4, 0.25, visits=200, trusted=50) == 0.4

    def test_shallow_candidate_uses_only_the_verified_loss(self):
        assert veil_cons_loss(0.1, 0.9, visits=12, trusted=50) == 0.1


class TestNearFree:
    def test_cheap_with_small_winrate_drop_is_free(self):
        assert veil_near_free_ok(0.3, 0.03, 0.60, 0.2, ctx())

    def test_too_expensive_or_too_large_a_drop_is_not(self):
        assert not veil_near_free_ok(0.31, 0.0, 0.60, 0.2, ctx())
        assert not veil_near_free_ok(0.1, 0.05, 0.60, 0.2, ctx())

    def test_decided_winrate_waives_the_drop(self):
        assert veil_near_free_ok(0.1, 0.05, 0.975, 20.0, ctx())

    def test_missing_winrate_is_not_free(self):
        assert not veil_near_free_ok(0.1, None, None, 0.2, ctx())

    def test_yose_guard_below_reserve_needs_a_one_percent_drop(self):
        yose = ctx(in_yose=True)
        assert not veil_near_free_ok(0.1, 0.02, 0.88, 4.9, yose)
        assert veil_near_free_ok(0.1, 0.01, 0.88, 4.9, yose)
        assert veil_near_free_ok(0.1, 0.02, 0.88, 5.0, yose)  # reserve を保つなら通常の条件


class TestPaid:
    def test_within_allowance_reserve_and_winrate_floor(self):
        assert veil_paid_ok(3.5, 0.85, ctx())

    def test_rejections(self):
        assert not veil_paid_ok(3.6, 0.95, ctx())  # A_t' 超
        assert not veil_paid_ok(1.0, 0.84, ctx())  # 勝率フロア
        assert not veil_paid_ok(1.0, None, ctx())
        assert not veil_paid_ok(1.0, 0.95, ctx(urgency=0.0))  # ゲート閉
        assert not veil_paid_ok(0.2, 0.95, ctx(lead=5.0, surplus=0.0, allowance=0.0))  # 余剰なし
        assert not veil_paid_ok(2.0, 0.95, ctx(lead=6.0, surplus=1.0, allowance=3.0))  # reserve を割る


class TestCloseDrift:
    def test_off_or_not_close_is_unlimited(self):
        assert veil_close_drift_ok(True, 5.0, 1.0, 0.0)
        assert veil_close_drift_ok(False, 5.0, 1.0, 1.0)

    def test_cap_counts_only_positive_losses(self):
        assert veil_close_drift_ok(True, 0.9, 0.1, 1.0)
        assert not veil_close_drift_ok(True, 0.95, 0.1, 1.0)
        assert veil_close_drift_ok(True, 1.0, -0.2, 1.0)


class TestClassify:
    def test_free_beats_paid_and_cost_is_clamped_at_zero(self):
        assert veil_classify(row(-0.2), ctx()) == ("free", 0.0)
        assert veil_classify(row(0.25), ctx()) == ("free", 0.25)

    def test_paid_when_not_free_but_within_budget(self):
        assert veil_classify(row(1.5), ctx()) == ("paid", 1.5)

    def test_free_is_independent_of_the_gate(self):
        closed = ctx(urgency=0.0, allowance=0.0, lead=0.5, surplus=-4.5, close=True)
        assert veil_classify(row(0.2, wr_after=0.55, lead_after=0.4), closed) == ("free", 0.2)
        assert veil_classify(row(1.0, wr_after=0.55, lead_after=0.4), closed) == (None, 1.0)

    def test_close_drift_cap_turns_free_into_paid_or_nothing(self):
        capped = ctx(close=True, close_drift=0.25, close_drift_cap=0.3)
        assert veil_classify(row(0.1), capped) == ("paid", 0.1)
        closed = ctx(close=True, close_drift=0.25, close_drift_cap=0.3, urgency=0.0, allowance=0.0)
        assert veil_classify(row(0.1), closed) == (None, 0.1)
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'VeilCtx' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t4.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
@dataclass
class VeilCtx:
    """1手番の判定に使う値（`veil_classify` / `veil_trap_ok` 共通）。lead は打つ側視点の root lead。"""

    lead: float
    reserve: float
    surplus: float            # S = lead − reserve
    urgency: float            # u（0 = ゲート閉）
    p_match: float            # この手も一致させた場合の一致率
    f_eff: float              # 同値外しの閾値
    allowance: float          # 支払う外しの許容損失 A_t'（明らかな一手なら dominant_max_loss で絞った後）
    trap_cap: float           # 罠の vloss 上限（ヨセ前 max_loss・ヨセ中 yose_max_loss。明らかな一手は dominant_max_loss でも頭打ち）
    min_winrate: float
    free_wr_drop: float
    in_yose: bool
    close: bool               # 接戦（lead < reserve または最善手の着手後勝率 < VEIL_CLOSE_WR）
    close_drift: float        # この局の接戦中の同値外しの vloss 累計
    close_drift_cap: float    # 0 で上限なし
    trap_min_delta_e: float


def veil_cons_loss(vloss, raw, visits, trusted):
    """保守的な損失 cons。十分に読まれた候補（visits >= trusted）は生の loss も見て大きいほう、それ以外は検証値。"""
    if raw is not None and visits >= trusted:
        return max(vloss, raw)
    return vloss


def veil_near_free_ok(cost, wr_drop, wr_after, lead_after, ctx):
    """同値外し（free）の安全条件（自然さと接戦の累計は呼び出し側）。

    cost <= F_eff かつ（1手の勝率低下 <= free_wr_drop または着手後勝率 >= VEIL_DECIDED_WR）かつ
    ヨセでは（着手後リード >= reserve または勝率低下 <= VEIL_YOSE_FREE_WR_DROP）。勝率が取れなければ不可。
    """
    if cost > ctx.f_eff + _VEIL_EPS or wr_drop is None or wr_after is None:
        return False
    if not (wr_drop <= ctx.free_wr_drop + _VEIL_EPS or wr_after >= VEIL_DECIDED_WR):
        return False
    if ctx.in_yose:
        holds_reserve = lead_after is not None and lead_after >= ctx.reserve
        if not (holds_reserve or wr_drop <= VEIL_YOSE_FREE_WR_DROP + _VEIL_EPS):
            return False
    return True


def veil_paid_ok(cost, wr_after, ctx):
    """支払う外し（paid）の条件: ゲートが開いていて余剰があり、cost <= A_t'、lead − cost >= reserve、
    着手後勝率 >= min_winrate。"""
    return (
        ctx.urgency > 0
        and ctx.surplus > 0
        and cost <= ctx.allowance + _VEIL_EPS
        and ctx.lead - cost >= ctx.reserve - _VEIL_EPS
        and wr_after is not None
        and wr_after >= ctx.min_winrate
    )


def veil_close_drift_ok(close, drift, vloss, cap):
    """接戦中の同値外しの累計上限（cap <= 0 なら上限なし）。drift + max(0, vloss) <= cap なら可。"""
    if cap <= 0 or not close:
        return True
    return drift + max(0.0, vloss) <= cap + _VEIL_EPS


def veil_classify(c, ctx):
    """素の外し（自然な候補）の種類と値段を返す: (kind, cost)。kind は "free" / "paid" / None。

    c は {"cons", "vloss", "wr_drop", "wr_after", "lead_after"}。cost = max(0, cons)（500v のノイズで負になりうる）。
    同値の条件を満たせば一致率に関係なく free、満たさなければゲートと余剰の範囲で paid。
    """
    cost = max(0.0, c["cons"])
    if veil_near_free_ok(cost, c.get("wr_drop"), c.get("wr_after"), c.get("lead_after"), ctx) and veil_close_drift_ok(
        ctx.close, ctx.close_drift, c["vloss"], ctx.close_drift_cap
    ):
        return "free", cost
    if veil_paid_ok(cost, c.get("wr_after"), ctx):
        return "paid", cost
    return None, cost
'''

patch(
    "katrain/core/ai.py",
    [
        ("from abc import ABC, abstractmethod\n", "from abc import ABC, abstractmethod\nfrom dataclasses import dataclass\n", 1),
        (ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1),
    ],
)
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t4.py"`
Expected: `patched katrain/core/ai.py (CRLF, 2 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `50 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 82 +++…`（削除 0 行・import 1 行の追加を含む）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 外しの分類（VeilCtx・veil_cons_loss・同値／支払いの安全条件・veil_classify）

同値外しは一致率に関係なく（勝率低下 <= free_wr_drop・ヨセで reserve 割れは 0.01）、
支払う外しは u > 0 かつ余剰の範囲で着手後勝率フロア付き。cost = max(0, cons)。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 最安帯で humanPolicy 最大を選ぶ `veil_choose`

**Files:**
- Modify: `katrain/core/ai.py`
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: `VEIL_HP_TIE` / `_VEIL_EPS`
- Produces: `veil_choose(scored, slack, prefer_safe, hp_tie=VEIL_HP_TIE) -> dict | None`（scored は `{"gtp","kind","cost","hp","wr_after"}`・kind が真の行だけが対象）

- [x] **Step 1: 失敗するテストを書く** — import ブロックを次に置き換え（Edit）

```python
from katrain.core.ai import (
    VeilCtx,
    game_report,
    veil_allowance,
    veil_choose,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_free_limit,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_urgency,
)
```

ファイル末尾に追記:

```python
def pick(gtp, cost, hp, wr_after=0.9, kind="free"):
    return {"gtp": gtp, "kind": kind, "cost": cost, "hp": hp, "wr_after": wr_after}


class TestChoose:
    def test_none_without_a_qualifying_move(self):
        assert veil_choose([], 0.3, prefer_safe=False) is None
        assert veil_choose([pick("D4", 0.1, 0.3, kind=None)], 0.3, prefer_safe=False) is None

    def test_most_human_move_inside_the_cheapest_band(self):
        scored = [pick("A", 0.0, 0.10), pick("B", 0.3, 0.40), pick("C", 0.31, 0.90, kind="paid")]
        assert veil_choose(scored, 0.3, prefer_safe=False)["gtp"] == "B"  # C は帯（0.0〜0.3）の外

    def test_zero_slack_is_the_cheapest(self):
        scored = [pick("A", 0.2, 0.10), pick("B", 0.1, 0.05)]
        assert veil_choose(scored, 0.0, prefer_safe=False)["gtp"] == "B"

    def test_exact_hp_tie_breaks_on_cost_then_gtp(self):
        scored = [pick("K10", 0.2, 0.3), pick("D4", 0.2, 0.3), pick("C3", 0.1, 0.3)]
        assert veil_choose(scored, 0.3, prefer_safe=False)["gtp"] == "C3"
        scored = [pick("K10", 0.2, 0.3), pick("D4", 0.2, 0.3)]
        assert veil_choose(scored, 0.3, prefer_safe=False)["gtp"] == "D4"

    def test_with_surplus_near_tied_hp_prefers_the_safer_move(self):
        scored = [pick("A", 0.1, 0.30, wr_after=0.90), pick("B", 0.2, 0.29, wr_after=0.95), pick("C", 0.0, 0.20)]
        assert veil_choose(scored, 0.3, prefer_safe=True)["gtp"] == "B"
        assert veil_choose(scored, 0.3, prefer_safe=False)["gtp"] == "A"

    def test_with_surplus_a_clearly_more_human_move_still_wins(self):
        scored = [pick("A", 0.1, 0.30, wr_after=0.90), pick("B", 0.2, 0.27, wr_after=0.99)]
        assert veil_choose(scored, 0.3, prefer_safe=True)["gtp"] == "A"
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'veil_choose' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t5.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
def veil_choose(scored, slack, prefer_safe, hp_tie=VEIL_HP_TIE):
    """種類の付いた候補（kind が真）から1手を選ぶ。該当なしは None。

    cost の最小値 c0 から slack 以内の帯で humanPolicy 最大（決定的）。prefer_safe（余剰がある手番）なら
    hp の差が hp_tie 以内の手のうち着手後勝率が高い手を優先し、それでも同点なら cost 昇順 → gtp 昇順。
    prefer_safe でなければ hp 降順 → cost 昇順 → gtp 昇順。
    scored: [{"gtp", "kind", "cost", "hp", "wr_after"}]。
    """
    eligible = [c for c in scored if c.get("kind")]
    if not eligible:
        return None
    cheapest = min(c["cost"] for c in eligible)
    band = [c for c in eligible if c["cost"] <= cheapest + slack + _VEIL_EPS]
    if prefer_safe:
        top_hp = max(c["hp"] for c in band)
        tied = [c for c in band if c["hp"] >= top_hp - hp_tie - _VEIL_EPS]
        return min(
            tied,
            key=lambda c: (-(c["wr_after"] if c.get("wr_after") is not None else -1.0), c["cost"], c["gtp"]),
        )
    return min(band, key=lambda c: (-c["hp"], c["cost"], c["gtp"]))
'''

patch("katrain/core/ai.py", [(ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t5.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `56 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 23 +++…`（削除 0 行）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 最安帯で humanPolicy 最大を選ぶ veil_choose

帯は最安から cost_slack 以内。余剰がある手番は hp 差 0.02 以内なら着手後勝率の高い手、同点は cost → gtp。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 罠の値段・資格・合流（`veil_trap_price` / `veil_trap_ok` / `veil_merge_trap`）

**Files:**
- Modify: `katrain/core/ai.py`
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: `VeilCtx`（Task 4）・既存の `ENIGMA9_GAMBLE_MAX_FIND`（0.25）・`VEIL_TRAP_CREDIT` / `VEIL_TRAP_MIN_HP` / `VEIL_TRAP_SWAP_MARGIN` / `VEIL_TARGET_FLOOR`
- Produces:
  - `veil_trap_price(vloss, delta_e, credit=VEIL_TRAP_CREDIT) -> float`
  - `veil_trap_ok(t, ctx) -> (ok: bool, price: float | None)`（t は `{"vloss","d_e","find","hp","wr_after"}`）
  - `veil_merge_trap(plain, traps, swap_margin=VEIL_TRAP_SWAP_MARGIN) -> dict | None`（plain は `veil_choose` の結果・traps は `"price"` 付きの行）

- [x] **Step 1: 失敗するテストを書く** — import ブロックを次に置き換え（Edit）

```python
from katrain.core.ai import (
    VeilCtx,
    game_report,
    veil_allowance,
    veil_choose,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_free_limit,
    veil_merge_trap,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_trap_ok,
    veil_trap_price,
    veil_urgency,
)
```

ファイル末尾に追記:

```python
def trap(vloss=1.0, d_e=2.0, find=0.1, hp=0.03, wr_after=0.93, gtp="T"):
    return {"gtp": gtp, "vloss": vloss, "d_e": d_e, "find": find, "hp": hp, "wr_after": wr_after}


class TestTrap:
    def test_price_discounts_half_of_delta_e_and_clamps_the_loss(self):
        assert veil_trap_price(1.0, 2.0) == pytest.approx(0.0)
        assert veil_trap_price(-0.4, 1.0) == pytest.approx(-0.5)

    def test_open_gate_accepts_within_the_allowance(self):
        assert veil_trap_ok(trap(vloss=3.0, d_e=1.0), ctx()) == (True, pytest.approx(2.5))
        assert veil_trap_ok(trap(vloss=4.2, d_e=1.0), ctx())[0] is False  # price 3.7 > A_t' 3.5

    def test_qualification(self):
        assert veil_trap_ok(trap(d_e=0.4), ctx())[0] is False  # ΔE 不足
        assert veil_trap_ok(trap(find=0.3), ctx())[0] is False  # 正しい応手が本の手
        assert veil_trap_ok(trap(hp=0.019), ctx())[0] is False  # NN の床に張り付いた手
        assert veil_trap_ok(trap(d_e=None), ctx()) == (False, None)

    def test_safety_is_judged_on_the_raw_verified_loss(self):
        # 値段は負でも、vloss が罠の上限（ヨセなら yose_max_loss）を超えたら不可
        assert veil_trap_ok(trap(vloss=1.6, d_e=6.0), ctx(trap_cap=1.5))[0] is False
        assert veil_trap_ok(trap(vloss=1.5, d_e=6.0), ctx(trap_cap=1.5))[0] is True
        assert veil_trap_ok(trap(vloss=2.0, d_e=6.0), ctx(lead=6.5, surplus=1.5))[0] is False  # reserve を割る
        assert veil_trap_ok(trap(wr_after=0.80), ctx())[0] is False

    def test_closed_gate_needs_a_non_positive_price_within_free_and_a_rate_above_the_floor(self):
        closed = ctx(urgency=0.0, allowance=0.0)
        assert veil_trap_ok(trap(vloss=0.3, d_e=0.6), closed) == (True, pytest.approx(0.0))
        assert veil_trap_ok(trap(vloss=0.3, d_e=0.5), closed)[0] is False  # price 0.05 > 0
        assert veil_trap_ok(trap(vloss=0.4, d_e=2.0), closed)[0] is False  # vloss > F_eff
        assert veil_trap_ok(trap(vloss=0.3, d_e=0.6), ctx(urgency=0.0, allowance=0.0, p_match=0.15))[0] is False

    def test_merge_keeps_the_plain_move_unless_the_trap_is_clearly_cheaper(self):
        plain = {"gtp": "D4", "kind": "free", "cost": 0.2}
        dear = {"gtp": "C3", "kind": "trap", "price": -0.05, "hp": 0.03}
        cheap = {"gtp": "F2", "kind": "trap", "price": -0.1, "hp": 0.03}
        assert veil_merge_trap(plain, [dear])["gtp"] == "D4"
        assert veil_merge_trap(plain, [dear, cheap])["gtp"] == "F2"
        assert veil_merge_trap(plain, [])["gtp"] == "D4"
        assert veil_merge_trap(None, [dear, cheap])["gtp"] == "F2"
        assert veil_merge_trap(None, []) is None

    def test_merge_breaks_price_ties_on_hp_then_gtp(self):
        a = {"gtp": "B2", "kind": "trap", "price": -1.0, "hp": 0.03}
        b = {"gtp": "A1", "kind": "trap", "price": -1.0, "hp": 0.05}
        c = {"gtp": "A2", "kind": "trap", "price": -1.0, "hp": 0.05}
        assert veil_merge_trap(None, [a, b, c])["gtp"] == "A1"
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'veil_merge_trap' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t6.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
def veil_trap_price(vloss, delta_e, credit=VEIL_TRAP_CREDIT):
    """罠の値段 = max(0, vloss) − credit × ΔE（E は集計でしか較正されていないので半分だけ信用する）。"""
    return max(0.0, vloss) - credit * delta_e


def veil_trap_ok(t, ctx):
    """罠（`<prefix>_trap_mode` の上乗せ層）の判定。返り値 (ok, price)（ΔE か find_hp が無ければ (False, None)）。

    t は {"vloss", "d_e", "find", "hp", "wr_after"}。
    1. 資格: ΔE >= trap_min_delta_e、find_hp <= ENIGMA9_GAMBLE_MAX_FIND、hp >= VEIL_TRAP_MIN_HP（自然さの床は免除）。
    2. 安全（vloss で判定・値段では割り引かない）: max(0, vloss) <= trap_cap、lead − max(0, vloss) >= reserve、
       着手後勝率 >= min_winrate。
    3. 値段: ゲートが開いていれば price <= A_t'、閉じていれば price <= 0 かつ max(0, vloss) <= F_eff かつ
       p_match > VEIL_TARGET_FLOOR。
    """
    d_e, find = t.get("d_e"), t.get("find")
    if d_e is None or find is None:
        return False, None
    price = veil_trap_price(t["vloss"], d_e)
    paid = max(0.0, t["vloss"])
    if d_e < ctx.trap_min_delta_e or find > ENIGMA9_GAMBLE_MAX_FIND or t.get("hp", 0.0) < VEIL_TRAP_MIN_HP:
        return False, price
    wr_after = t.get("wr_after")
    if paid > ctx.trap_cap + _VEIL_EPS or ctx.lead - paid < ctx.reserve - _VEIL_EPS:
        return False, price
    if wr_after is None or wr_after < ctx.min_winrate:
        return False, price
    if ctx.urgency > 0:
        return price <= ctx.allowance + _VEIL_EPS, price
    ok = price <= _VEIL_EPS and paid <= ctx.f_eff + _VEIL_EPS and ctx.p_match > VEIL_TARGET_FLOOR
    return ok, price


def veil_merge_trap(plain, traps, swap_margin=VEIL_TRAP_SWAP_MARGIN):
    """素の外し P（`veil_choose` の結果・None 可）と合格した罠の列から最終の1手を返す。

    罠 Q は値段最小（同点は hp 降順 → gtp）。P があれば P、ただし Q の値段が P の cost より swap_margin 以上
    安ければ Q。P が無ければ Q（外しが1回増える）。P があれば戻り値は必ず非 None。
    """
    best_trap = min(traps, key=lambda t: (t["price"], -t.get("hp", 0.0), t["gtp"])) if traps else None
    if plain is None:
        return best_trap
    if best_trap is not None and best_trap["price"] <= plain["cost"] - swap_margin + _VEIL_EPS:
        return best_trap
    return plain
'''

patch("katrain/core/ai.py", [(ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t6.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `63 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 47 +++…`（削除 0 行）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 罠の値段・資格・合流（veil_trap_price / veil_trap_ok / veil_merge_trap）

値段は vloss − 0.5 ΔE、安全条件（上限・reserve・勝率フロア）は vloss で判定して割り引かない。
素の外しは罠が 0.3 目以上安いときだけ替わり、素の外しがあれば結果は必ず非 None。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 終局帯の入れ替え（`veil_terminal_limit` / `veil_terminal_swap`）

**Files:**
- Modify: `katrain/core/ai.py`
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: `VEIL_TERMINAL_MAX` / `VEIL_TERMINAL_CLOSE_MAX` / `VEIL_TERMINAL_CLOSE_LEAD` / `VEIL_TERMINAL_MIN_VISITS`
- Produces:
  - `veil_terminal_limit(lead) -> float`（|lead| < 3 なら 0.05、それ以外 0.10）
  - `veil_terminal_swap(candidates, best_gtp, hp_of, floor, lead, dominant, urgency, close_drift=0.0, close_drift_cap=0.0) -> dict | None`（返り値は候補 dict に `"hp"` を足したもの）

- [x] **Step 1: 失敗するテストを書く** — import ブロックを次に置き換え（Edit）

```python
from katrain.core.ai import (
    VeilCtx,
    game_report,
    veil_allowance,
    veil_choose,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_free_limit,
    veil_merge_trap,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_terminal_limit,
    veil_terminal_swap,
    veil_trap_ok,
    veil_trap_price,
    veil_urgency,
)
```

ファイル末尾に追記:

```python
class TestTerminalSwap:
    CANDS = [cand("E5", 0.0, 900), cand("D4", 0.04, 50), cand("C3", 0.08, 40), cand("F6", 0.2, 30), cand("G7", 0.0, 5)]
    CANDS.append(cand("pass", 0.1, 60))
    HP = staticmethod(hp_table({"D4": 0.10, "C3": 0.30, "F6": 0.60, "G7": 0.70, "pass": 0.9}))

    def test_limit_depends_on_the_lead(self):
        assert veil_terminal_limit(2.9) == pytest.approx(0.05)
        assert veil_terminal_limit(-2.9) == pytest.approx(0.05)
        assert veil_terminal_limit(3.0) == pytest.approx(0.10)

    def test_clear_lead_allows_up_to_0_10_and_picks_the_most_human(self):
        swap = veil_terminal_swap(self.CANDS, "E5", self.HP, 0.05, lead=10.0, dominant=False, urgency=0.0)
        assert swap["gtp"] == "C3" and swap["hp"] == pytest.approx(0.30)  # F6 は 0.2 目・G7 は visits 5・pass は除外

    def test_close_game_allows_only_0_05(self):
        swap = veil_terminal_swap(self.CANDS, "E5", self.HP, 0.05, lead=1.0, dominant=False, urgency=0.0)
        assert swap["gtp"] == "D4"

    def test_natural_floor_applies(self):
        assert veil_terminal_swap(self.CANDS, "E5", self.HP, 0.2, lead=1.0, dominant=False, urgency=1.0) is None

    def test_dominant_needs_an_open_gate(self):
        assert veil_terminal_swap(self.CANDS, "E5", self.HP, 0.05, lead=10.0, dominant=True, urgency=0.0) is None
        assert veil_terminal_swap(self.CANDS, "E5", self.HP, 0.05, lead=10.0, dominant=True, urgency=0.5) is not None

    def test_close_drift_cap_in_close_games(self):
        args = (self.CANDS, "E5", self.HP, 0.05)
        assert veil_terminal_swap(*args, lead=1.0, dominant=False, urgency=0.0, close_drift=0.96, close_drift_cap=1.0)
        blocked = veil_terminal_swap(
            *args, lead=1.0, dominant=False, urgency=0.0, close_drift=0.97, close_drift_cap=1.0
        )
        assert blocked is None
        free = veil_terminal_swap(*args, lead=10.0, dominant=False, urgency=0.0, close_drift=5.0, close_drift_cap=1.0)
        assert free["gtp"] == "C3"  # |lead| >= 3 では累計を見ない
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'veil_terminal_limit' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t7.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
def veil_terminal_limit(lead):
    """終局帯で最善手から外してよい生の loss の上限。|lead| < VEIL_TERMINAL_CLOSE_LEAD なら厳しい側。"""
    return VEIL_TERMINAL_CLOSE_MAX if abs(lead) < VEIL_TERMINAL_CLOSE_LEAD else VEIL_TERMINAL_MAX


def veil_terminal_swap(candidates, best_gtp, hp_of, floor, lead, dominant, urgency, close_drift=0.0,
                       close_drift_cap=0.0):
    """終局帯の入れ替え（ダメ詰めの順番入れ替え＝レポート上の不一致）。候補が無ければ None。

    candidates は `parity9_build_candidates` の {"gtp", "loss", "visits", "wr"}。最善手でも pass でもなく、
    visits >= VEIL_TERMINAL_MIN_VISITS、生の loss <= `veil_terminal_limit(lead)`、hp >= floor の手のうち hp 最大
    （同点は loss → gtp）。明らかな一手（dominant）でゲートが閉じていれば不可。close_drift_cap > 0 かつ
    |lead| < VEIL_TERMINAL_CLOSE_LEAD なら、累計 close_drift + max(0, loss) が上限を超える手は除く。
    返り値は候補 dict に "hp" を足したもの。
    """
    if dominant and urgency <= 0:
        return None
    limit = veil_terminal_limit(lead)
    capped = close_drift_cap > 0 and abs(lead) < VEIL_TERMINAL_CLOSE_LEAD
    pool = []
    for c in candidates:
        if c["gtp"] in (best_gtp, "pass") or c.get("visits", 0) < VEIL_TERMINAL_MIN_VISITS:
            continue
        if c["loss"] > limit + _VEIL_EPS:
            continue
        hp = hp_of(c["gtp"])
        if hp < floor:
            continue
        if capped and close_drift + max(0.0, c["loss"]) > close_drift_cap + _VEIL_EPS:
            continue
        pool.append({**c, "hp": hp})
    if not pool:
        return None
    return min(pool, key=lambda c: (-c["hp"], c["loss"], c["gtp"]))
'''

patch("katrain/core/ai.py", [(ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t7.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `69 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 36 +++…`（削除 0 行）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 終局帯の入れ替え veil_terminal_swap

最善手でも pass でもなく visits >= 10・生 loss <= 0.10（|lead| < 3 は 0.05）・自然さの床以上の手のうち hp 最大。
明らかな一手はゲート閉なら不可、接戦の累計上限にも従う。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 不変条件と Decision 行（`veil_invariant_ok` / `veil_decision_record`）

**Files:**
- Modify: `katrain/core/ai.py`（`import json` を import に追加し、定義を追記）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Produces:
  - `veil_invariant_ok(chosen, best, cand_gtps, kind, bounds) -> bool`（bounds のキー: free / decided `{"cost","f_eff"}`・paid `{"cost","allowance","lead","reserve"}`・trap `{"price","allow","vloss","trap_cap","lead","reserve"}`・terminal `{"raw","limit"}`）
  - `veil_decision_record(**fields) -> str`（ASCII の JSON・`sort_keys`・float は小数3桁・NaN/inf は null）

- [x] **Step 1: 失敗するテストを書く** — import ブロックを次に置き換え（Edit）

```python
from katrain.core.ai import (
    VeilCtx,
    game_report,
    veil_allowance,
    veil_choose,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_decision_record,
    veil_free_limit,
    veil_invariant_ok,
    veil_merge_trap,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_terminal_limit,
    veil_terminal_swap,
    veil_trap_ok,
    veil_trap_price,
    veil_urgency,
)
```

ファイル末尾に追記:

```python
class TestInvariant:
    GTPS = {"E5", "D4", "C3", "pass"}

    def test_common_rules(self):
        free = {"cost": 0.1, "f_eff": 0.3}
        assert veil_invariant_ok("D4", "E5", self.GTPS, "free", free)
        assert not veil_invariant_ok("E5", "E5", self.GTPS, "free", free)  # 最善手
        assert not veil_invariant_ok("pass", "E5", self.GTPS, "free", free)
        assert not veil_invariant_ok("Q16", "E5", self.GTPS, "free", free)  # 候補に無い
        assert not veil_invariant_ok(None, "E5", self.GTPS, "free", free)

    def test_bounds_per_kind(self):
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "decided", {"cost": 0.31, "f_eff": 0.3})
        paid = {"cost": 2.0, "allowance": 2.0, "lead": 7.0, "reserve": 5.0}
        assert veil_invariant_ok("D4", "E5", self.GTPS, "paid", paid)
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "paid", {**paid, "allowance": 1.9})
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "paid", {**paid, "lead": 6.9})
        trap_b = {"price": -0.5, "allow": 0.0, "vloss": 1.5, "trap_cap": 1.5, "lead": 8.0, "reserve": 5.0}
        assert veil_invariant_ok("C3", "E5", self.GTPS, "trap", trap_b)
        assert not veil_invariant_ok("C3", "E5", self.GTPS, "trap", {**trap_b, "vloss": 1.6})
        assert not veil_invariant_ok("C3", "E5", self.GTPS, "trap", {**trap_b, "price": 0.1})
        assert veil_invariant_ok("D4", "E5", self.GTPS, "terminal", {"raw": 0.05, "limit": 0.05})
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "terminal", {"raw": 0.06, "limit": 0.05})

    def test_unknown_kind_or_missing_bounds_fail(self):
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "mystery", {"cost": 0.0, "f_eff": 1.0})
        assert not veil_invariant_ok("D4", "E5", self.GTPS, "paid", {"cost": 0.1})


class TestDecisionRecord:
    def test_json_is_ascii_sorted_and_rounded(self):
        text = veil_decision_record(
            tier="iii", kind="free", vloss=0.123456, lead=float("nan"), ledger=(1, "D4"), ok=True
        )
        assert text == '{"kind": "free", "lead": null, "ledger": [1, "D4"], "ok": true, "tier": "iii", "vloss": 0.123}'
        assert text.isascii()
        assert json.loads(text)["vloss"] == 0.123
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'veil_decision_record' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t8.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
def veil_invariant_ok(chosen, best, cand_gtps, kind, bounds):
    """選んだ手の最終確認（S19）。違反なら False（呼び出し側は ERROR ログ＋最善手）。

    共通: chosen が通常解析の候補 cand_gtps に含まれ、best でも pass でもないこと。種類ごとの上限（bounds のキー）:
    free / decided: cost <= f_eff。paid: cost <= allowance かつ lead − cost >= reserve。
    trap: price <= allow かつ max(0, vloss) <= trap_cap かつ lead − max(0, vloss) >= reserve。
    terminal: raw <= limit。それ以外の kind・キー欠落は False。
    """
    if chosen is None or chosen == best or chosen == "pass" or chosen not in cand_gtps:
        return False
    try:
        if kind in ("free", "decided"):
            return bounds["cost"] <= bounds["f_eff"] + _VEIL_EPS
        if kind == "paid":
            return (
                bounds["cost"] <= bounds["allowance"] + _VEIL_EPS
                and bounds["lead"] - bounds["cost"] >= bounds["reserve"] - _VEIL_EPS
            )
        if kind == "trap":
            paid = max(0.0, bounds["vloss"])
            return (
                bounds["price"] <= bounds["allow"] + _VEIL_EPS
                and paid <= bounds["trap_cap"] + _VEIL_EPS
                and bounds["lead"] - paid >= bounds["reserve"] - _VEIL_EPS
            )
        if kind == "terminal":
            return bounds["raw"] <= bounds["limit"] + _VEIL_EPS
    except (KeyError, TypeError):
        return False
    return False


def veil_decision_record(**fields):
    """`Decision:` 行の JSON（ASCII のみ・キー順固定・float は小数3桁・NaN/inf は null）。"""

    def clean(v):
        if v is None or isinstance(v, (bool, int, str)):
            return v
        if isinstance(v, float):
            return None if math.isnan(v) or math.isinf(v) else round(v, 3)
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        if isinstance(v, dict):
            return {str(k): clean(x) for k, x in v.items()}
        return str(v)

    return json.dumps({k: clean(v) for k, v in fields.items()}, ensure_ascii=True, sort_keys=True)
'''

patch(
    "katrain/core/ai.py",
    [
        ("import heapq\nimport math\n", "import heapq\nimport json\nimport math\n", 1),
        (ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1),
    ],
)
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t8.py"`
Expected: `patched katrain/core/ai.py (CRLF, 2 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `73 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 50 +++…`（削除 0 行・`import json` 1 行を含む）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 不変条件 veil_invariant_ok と Decision 行 veil_decision_record

選んだ手が候補に含まれ最善手でも pass でもなく、種類ごとの上限内にあることを最後に確かめる。
Decision 行は ASCII のみ・キー順固定（ログ集計とハーネス用）。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9a: `Veil9Strategy` の骨組みと前半フロー（S0〜S6・S9〜S12・早期終了）と `AI_VEIL_*` 定数

**Files:**
- Modify: `katrain/core/constants.py`（`AI_MIMIC_13` の直後に `AI_VEIL_9/13/19` の3定数だけ。リストへの登録は Task 12）
- Modify: `katrain/core/ai.py`（import 行に `AI_VEIL_9, AI_VEIL_13, AI_VEIL_19`、クラスを追記）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: Task 1〜8 の純関数・継承する `Enigma9Strategy` の `generate_move` / `_setting` / `_log` / `_best_move` / `_run_query` / `_probe_children` / `_cancel_ponder` / `_terminal_band_move`・既存の `parity9_match_tally` / `parity9_is_endgame` / `PARITY9_UNSETTLED_ABS` / `parity9_build_candidates` / `enigma9_hp_lookup` / `enigma9_reply_table` / `enigma9_expected_punish` / `enigma9_reply_findability` / `mimic_hp_top`
- Produces:
  - `AI_VEIL_9 = "ai:veil9"` / `AI_VEIL_13 = "ai:veil13"` / `AI_VEIL_19 = "ai:veil19"`（constants.py）
  - `@register_strategy(AI_VEIL_9) class Veil9Strategy(Enigma9Strategy)`: `BOARD_LEN = 9`・`KEY_PREFIX = "veil9"`・`LABEL = "Veil9"`・`SETTING_DEFAULTS`（16 キー・spec §6.1 の 9路列）・`VEIL_BOARD`
  - メソッド: `_veil_state() -> dict`・`_veil_punish(probe, opponent) -> (E|None, find_hp|None)`・`_veil_finish(result, info, tier, kind, **fields)`・`_veil_violation(chosen, kind, bounds) -> (Move, str)`・`_veil_terminal(cands, player, best_gtp, lead, u, info) -> None | (result, tier, kind, fields)`（**仮の実装＝常に None**。Task 10 で置き換える）・`_generate_move()`（S0 ラッパー）・`_veil_move()`（S1〜S12。**S13〜S20 は仮の末尾＝最善手 `why="none_qualified"` の4行**。Task 9b で置き換える）
  - 共有インターフェース節の `last_decision_info` / `Decision:` / `game._veil_state` / `Rate:`、S6 の `Endgame check:` 行と `info["unsettled"]`
  - テスト側: `SPEC_DEFAULTS` / `CALIBRATED_DEFAULTS` / `EXPECTED_DEFAULTS` / `SAFETY_DEFAULTS`・`_hp_array` / `_child` / `_hist` / `_Harness` / `EVEN`（Task 9b〜12・17 が使う）

- [x] **Step 1: 失敗するテストを書く** — import ブロック（`from katrain.core.ai import (` 〜 `)`）を次に置き換え（Edit。constants の import 行が増える）

```python
from katrain.core.ai import (
    STRATEGY_REGISTRY,
    AnalysisDiscardedException,
    Enigma9Strategy,
    Veil9Strategy,
    VeilCtx,
    game_report,
    veil_allowance,
    veil_choose,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_decision_record,
    veil_free_limit,
    veil_invariant_ok,
    veil_merge_trap,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_terminal_limit,
    veil_terminal_swap,
    veil_trap_ok,
    veil_trap_price,
    veil_urgency,
)
from katrain.core.constants import AI_VEIL_9
```

ファイル末尾に追記（`SPEC_DEFAULTS` は凍結した spec の既定値。通しテストはこれを明示の設定として渡すので、Task 17 で既定値を変えてもテストの前提は動かない。`CALIBRATED_DEFAULTS` は Task 17 のスクリプトが書き換える差分）。このタスクのテストは S12 までで結論が出る手番だけ（段(i)・段(ii) 閉・フェイルセーフの前半）:

```python
# spec §6.1 の既定値（凍結）。通しテストはこの値を明示の設定として渡す＝校正で既定値を変えてもテストの前提は動かない
SPEC_DEFAULTS = {
    9: {
        "target_rate": 0.40,
        "reserve": 3.0,
        "min_winrate": 0.85,
        "free_loss": 0.2,
        "free_wr_drop": 0.03,
        "close_drift_cap": 0.0,
        "spend_rate": 0.5,
        "max_loss": 3.0,
        "yose_max_loss": 1.0,
        "dominant_hp": 0.8,
        "dominant_max_loss": 1.5,
        "min_human_policy": 0.05,
        "natural_ratio": 0.2,
        "cost_slack": 0.3,
        "trap_mode": False,
        "trap_min_delta_e": 0.5,
    },
    13: {
        "target_rate": 0.30,
        "reserve": 5.0,
        "min_winrate": 0.85,
        "free_loss": 0.3,
        "free_wr_drop": 0.03,
        "close_drift_cap": 0.0,
        "spend_rate": 0.5,
        "max_loss": 4.5,
        "yose_max_loss": 1.5,
        "dominant_hp": 0.8,
        "dominant_max_loss": 2.0,
        "min_human_policy": 0.05,
        "natural_ratio": 0.2,
        "cost_slack": 0.3,
        "trap_mode": False,
        "trap_min_delta_e": 0.5,
    },
    19: {
        "target_rate": 0.30,
        "reserve": 7.0,
        "min_winrate": 0.85,
        "free_loss": 0.3,
        "free_wr_drop": 0.03,
        "close_drift_cap": 0.0,
        "spend_rate": 0.5,
        "max_loss": 6.0,
        "yose_max_loss": 2.0,
        "dominant_hp": 0.8,
        "dominant_max_loss": 3.0,
        "min_human_policy": 0.05,
        "natural_ratio": 0.2,
        "cost_slack": 0.3,
        "trap_mode": False,
        "trap_min_delta_e": 0.7,
    },
}
# 校正（Task 17）で選んだ既定値の差分。apply_veil_defaults.py が書き換える（空なら spec のまま）
CALIBRATED_DEFAULTS = {9: {}, 13: {}, 19: {}}
# コードとパッケージ config の既定値＝spec ＋ 校正の差分
EXPECTED_DEFAULTS = {size: {**SPEC_DEFAULTS[size], **CALIBRATED_DEFAULTS[size]} for size in SPEC_DEFAULTS}
# 勝ちの安全条件（要件1）。変えてよいのはユーザーが要件1を再決定したときだけ（apply_veil_defaults.py --safety-redecided）
SAFETY_DEFAULTS = {
    9: {"reserve": 3.0, "min_winrate": 0.85},
    13: {"reserve": 5.0, "min_winrate": 0.85},
    19: {"reserve": 7.0, "min_winrate": 0.85},
}


# ===== _generate_move の通しテスト（Veil9Strategy・9路・KataGo なし）=====


def _hp_array(size, values):
    """{gtp: hp} → KataGo の humanPolicy フラット配列（末尾 pass）"""
    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        if gtp == "pass":
            arr[-1] = v
            continue
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def _child(lead, wr, punish=0.0, size=9):
    """黒番の AI が候補を打った後の子局面プローブ（scoreLead / winrate は黒視点）。

    白の応手は A9（人間の本命）と J1。punish > 0 なら本命 A9 が punish 目損する罠の形
    （hp A9 0.9 / J1 0.1 → E = 0.9 × punish、正解 J1 の hp 0.1＝find_hp）。punish 0 なら E = 0。
    """
    replies = [("A9", lead + punish, 300), ("J1", lead, 200)]
    reply_hp = {"A9": 0.9, "J1": 0.1} if punish > 0 else {"A9": 0.5, "J1": 0.5}
    clean = {
        "rootInfo": {"scoreLead": lead, "winrate": wr},
        "moveInfos": [{"move": g, "scoreLead": s, "visits": v} for g, s, v in replies],
    }
    return {"clean": clean, "hp": {"humanPolicy": _hp_array(size, reply_hp)}}


def _hist(ai_player, mine, n_mine, opp=0, n_opp=0):
    """一致率の履歴（veil_tally / parity9_match_tally が読む属性だけの疑似ノード列・root 込み）。"""
    nodes = [types.SimpleNamespace(move=None, is_root=True, parent=None, player="W")]
    opp_player = "W" if ai_player == "B" else "B"
    for player, matched, total in ((ai_player, mine, n_mine), (opp_player, opp, n_opp)):
        for i in range(total):
            parent = types.SimpleNamespace(
                analysis_complete=True, candidate_moves=[{"move": "A1" if i < matched else "B2"}]
            )
            move = Move.from_gtp("A1", player=player)
            nodes.append(types.SimpleNamespace(move=move, is_root=False, parent=parent, player=player, points_lost=0.0))
    return nodes


class _Harness:
    """_generate_move の通しテスト用スタブ（エンジンなし）。黒番・最善手 E5。
    名前が Test で始まらないので pytest には収集されない（継承した側だけが走る）。"""

    CLS = Veil9Strategy
    SIZE = 9
    CANDS = [
        {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.62},
        {"move": "D4", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 300, "winrate": 0.61},
        {"move": "F6", "pointsLost": 0.8, "relativePointsLost": 0.8, "visits": 150, "winrate": 0.58},
        {"move": "C7", "pointsLost": 2.0, "relativePointsLost": 2.0, "visits": 60, "winrate": 0.50},
        {"move": "G3", "pointsLost": 3.8, "relativePointsLost": 3.8, "visits": 40, "winrate": 0.45},
        {"move": "A1", "pointsLost": 9.0, "relativePointsLost": 9.0, "visits": 3, "winrate": 0.20},
    ]
    # 床 = max(0.05, 0.2 × 0.40) = 0.08 → 自然な候補は D4 / F6、C7 / G3 は罠の資格（hp >= 0.02）だけ
    HP = {"E5": 0.40, "D4": 0.30, "F6": 0.15, "C7": 0.03, "G3": 0.04}

    def _strategy(
        self,
        *,
        lead=10.0,
        wr=0.95,
        depth=12,
        cands=None,
        hp=None,
        hp_ok=True,
        probes=None,
        settings=None,
        hist=None,
        last_move=None,
        ownership=None,
        size=None,
        **game_attrs,
    ):
        size = size or self.SIZE
        logs = []
        katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
        node = types.SimpleNamespace(
            next_player="B",
            player="W",
            depth=depth,
            move=last_move,
            is_root=False,
            analysis_complete=True,
            analysis={"root": {"scoreLead": lead, "winrate": wr}},
            candidate_moves=[dict(c) for c in (self.CANDS if cands is None else cands)],
            nodes_from_root=[] if hist is None else hist,
            policy_ranking=[],
        )
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(size, size), **game_attrs)
        spec = {f"{self.CLS.KEY_PREFIX}_{k}": v for k, v in SPEC_DEFAULTS[self.CLS.BOARD_LEN].items()}
        s = self.CLS(game, {**spec, **(settings or {})})
        s.queries, s.probe_calls, s.ponders = [], [], []
        hp_values = self.HP if hp is None else hp

        def run_query(label, **kw):
            s.queries.append(label)
            if label == "parent hp":
                return {"humanPolicy": _hp_array(size, hp_values)} if hp_ok else None
            return None if ownership is None else {"ownership": ownership, "rootInfo": {"scoreLead": lead}}

        def probe_children(gtps, player, parent_hp=False):
            s.probe_calls.append(list(gtps))
            return {g: (probes or {}).get(g) for g in gtps}, None

        s._run_query = run_query
        s._probe_children = probe_children
        s._start_ponder = lambda *a, **k: s.ponders.append(a)
        return s, logs


EVEN = dict(lead=0.5, wr=0.55)  # 互角・目標ちょうど（9路 T 0.40 → u = 0）の手番に _hist("B", 3, 9) と組む


class TestStrategyClass:
    def test_registered_as_a_9x9_enigma_subclass(self):
        assert AI_VEIL_9 == "ai:veil9"
        assert STRATEGY_REGISTRY[AI_VEIL_9] is Veil9Strategy
        assert issubclass(Veil9Strategy, Enigma9Strategy)
        assert (Veil9Strategy.BOARD_LEN, Veil9Strategy.KEY_PREFIX, Veil9Strategy.LABEL) == (9, "veil9", "Veil9")

    def test_defaults_match_the_spec(self):
        assert Veil9Strategy.SETTING_DEFAULTS == EXPECTED_DEFAULTS[9]
        assert Veil9Strategy.VEIL_BOARD == {
            "endgame_move": 30,
            "unsettled_max": 8,
            "trusted_visits": 100,
            "probe_hp": 3,
            "probe_cheap": 2,
        }

    def test_only_the_flow_is_overridden(self):
        assert Veil9Strategy.generate_move is Enigma9Strategy.generate_move  # 時間ログのラッパーは共有
        assert Veil9Strategy._generate_move is not Enigma9Strategy._generate_move
        assert Veil9Strategy._terminal_band_move is Enigma9Strategy._terminal_band_move


class TestTiers(_Harness):
    def test_tier_i_only_the_best_move_needs_no_query(self):
        s, logs = self._strategy(cands=[self.CANDS[0], self.CANDS[-1]])
        move, _ = s.generate_move()
        assert move.gtp() == "E5"
        assert s.queries == [] and s.probe_calls == []
        assert s.last_decision_info["tier"] == "i"

    def test_tier_ii_closed_at_target_costs_one_query(self):
        s, logs = self._strategy(**EVEN, hist=_hist("B", 3, 9), hp={**self.HP, "E5": 0.85})
        move, _ = s.generate_move()
        assert move.gtp() == "E5"
        assert s.queries == ["parent hp"] and s.probe_calls == []
        assert (s.last_decision_info["tier"], s.last_decision_info["why"]) == ("ii", "dominant_closed")


class TestFailSafes(_Harness):
    def test_wrong_board_size(self):
        s, logs = self._strategy(size=13)
        assert s.generate_move()[0].gtp() == "E5"
        assert s.queries == [] and any("is not 9x9" in m for m in logs)

    def test_no_candidates(self):
        s, _ = self._strategy(cands=[])
        assert s.generate_move()[0].is_pass
        assert s.last_decision_info["why"] == "no_cands"

    def test_no_lead(self):
        s, _ = self._strategy(lead=None)
        assert s.generate_move()[0].gtp() == "E5" and s.queries == []

    def test_humansl_failure(self):
        s, _ = self._strategy(hp_ok=False)
        assert s.generate_move()[0].gtp() == "E5" and s.queries == ["parent hp"] and s.probe_calls == []

    def test_unexpected_exception_plays_the_best_move(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(ai_module, "veil_allowance", boom)
        s, logs = self._strategy()
        assert s.generate_move()[0].gtp() == "E5"
        assert any("error RuntimeError: boom" in m for m in logs)
        assert s.last_decision_info["why"] == "error"

    def test_discarded_analysis_is_not_swallowed(self, monkeypatch):
        def discarded(*a, **k):
            raise AnalysisDiscardedException("new game")

        monkeypatch.setattr(ai_module, "veil_allowance", discarded)
        s, _ = self._strategy()
        with pytest.raises(AnalysisDiscardedException):
            s.generate_move()
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'Veil9Strategy' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t9a.py`（constants.py に3定数、ai.py の import 行とクラス。`_veil_move` は S12 の後に仮の末尾4行を置く）

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

CONSTANTS = '''AI_MIMIC_13 = "ai:mimic13"
# 9/13/19路「韜晦」戦略。勝ちを最優先にしたまま、自分の AI 最善手一致率（終局レポートの値）を絶対目標まで
# 下げる＝ほぼ損失ゼロの外しは常に、損をする外しは一致率が目標超のときだけリードの余剰から払う
# （ai.py の Veil9Strategy / Veil13Strategy / Veil19Strategy・spec 2026-09-23-veil-strategy-design.md）
AI_VEIL_9 = "ai:veil9"
AI_VEIL_13 = "ai:veil13"
AI_VEIL_19 = "ai:veil19"
'''

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
@register_strategy(AI_VEIL_9)
class Veil9Strategy(Enigma9Strategy):
    """9路専用「韜晦」戦略＝勝ちを最優先にしたまま、自分の AI 最善手一致率を絶対目標まで下げる。

    一致率は KaTrain の終局レポートの値（`veil_tally`＝`game_report` と同一定義）。手番は3段:
    (i) 候補が最善手しか無い → 最善手、(ii) 最善手の humanPolicy が dominant_hp 以上（明らかな一手）→
    一致率が目標を超えているとき（u > 0）だけ dominant_max_loss までで外す、(iii) それ以外 → ほぼ損失ゼロの
    外し（free）は常に、損をする外し（paid）は u > 0 のときだけ余剰 S = lead − reserve の範囲で払う。
    外しはすべて子局面プローブ（clean 500v + humanSL 8v）で検証し、最安帯の中で humanPolicy 最大を選ぶ。
    罠（trap_mode）は ΔE の上乗せ層。ヨセは委譲しない・ponder は起動しない。全分岐のフェイルセーフは最善手。

    難解（Enigma9Strategy）からは generate_move（時間ログ）・_setting・_log・_best_move・_run_query・
    _probe_children・_cancel_ponder・_terminal_band_move を継承して使う。13/19路は属性だけ差し替えたサブクラス。
    sticky な状態は `game._veil_state[KEY_PREFIX]`（endgame・close_drift・ledger）。
    設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md
    """

    BOARD_LEN = 9
    KEY_PREFIX = "veil9"
    LABEL = "Veil9"
    SETTING_DEFAULTS = {
        "target_rate": 0.40,        # 目標一致率（9路は下限 35〜45% が実測済み）
        "reserve": 3.0,             # 支払う外し・罠の後にも残すリード（目）＝勝ちの安全条件
        "min_winrate": 0.85,        # 支払う外しと罠の着手後勝率フロア＝勝ちの安全条件
        "free_loss": 0.2,           # 同値外しの閾値（目）
        "free_wr_drop": 0.03,       # 同値外しで許す1手の勝率低下
        "close_drift_cap": 0.0,     # 接戦中の同値外し vloss の1局あたり累計上限（0 = 上限なし）
        "spend_rate": 0.5,          # 余剰のうち1回に使う割合
        "max_loss": 3.0,            # 支払い上限（ヨセ前・目）。罠の vloss のハード上限も兼ねる
        "yose_max_loss": 1.0,       # ヨセ中の支払い上限（目・罠も同じ）。0 で同値のみ
        "dominant_hp": 0.8,         # 「明らかな一手」の閾値（1.01 で OFF）
        "dominant_max_loss": 1.5,   # 明らかな一手で許す損失（目・上限を絞るだけ）
        "min_human_policy": 0.05,   # 自然さの絶対床
        "natural_ratio": 0.2,       # 自然さの相対床（第一感比）
        "cost_slack": 0.3,          # 最安帯の幅（目）
        "trap_mode": False,         # 罠の上乗せ層（A/B 用）
        "trap_min_delta_e": 0.5,    # 罠とみなす ΔE（目）
    }
    # スライダーにしない盤サイズ別の値（spec §6.1）
    VEIL_BOARD = {"endgame_move": 30, "unsettled_max": 8, "trusted_visits": 100, "probe_hp": 3, "probe_cheap": 2}

    def _veil_state(self):
        """この局の sticky 状態（Game に載るので対局ごとに作り直される）。"""
        state = getattr(self.game, "_veil_state", None)
        if not isinstance(state, dict):
            state = {}
            setattr(self.game, "_veil_state", state)
        return state.setdefault(self.KEY_PREFIX, {"endgame": False, "close_drift": 0.0, "ledger": []})

    def _veil_punish(self, probe, opponent):
        """子局面プローブから (E, find_hp) を返す（不完全なら (None, None)）。"""
        clean, hp_child = (probe or {}).get("clean"), (probe or {}).get("hp")
        if not clean or not clean.get("moveInfos") or not hp_child or "humanPolicy" not in hp_child:
            return None, None
        replies, _best_reply = enigma9_reply_table(clean["moveInfos"], opponent)
        if not replies:
            return None, None
        hp_of = enigma9_hp_lookup(hp_child["humanPolicy"], self.game.board_size)
        e_punish, _coverage = enigma9_expected_punish(replies, hp_of)
        return e_punish, enigma9_reply_findability(replies, hp_of)

    def _veil_finish(self, result, info, tier, kind, **fields):
        """1手の結論を記録して返す（last_decision_info・`Decision:` 行・ledger）。result は (Move, 理由)。"""
        move = result[0]
        record = {k: v for k, v in info.items() if k != "t0"}
        record.update(fields)
        record.update(tier=tier, kind=kind, chosen=None if move is None else move.gtp(), secs=time.time() - info["t0"])
        self.last_decision_info = record
        self._veil_state()["ledger"].append((record.get("depth"), record.get("best"), record["chosen"], kind))
        self._log("Decision: " + veil_decision_record(**record))
        return result

    def _veil_violation(self, chosen, kind, bounds):
        """不変条件違反（S19）。ERROR ログを出して最善手。"""
        self.game.katrain.log(
            f"[{type(self).__name__}] Invariant violated: chosen={chosen} kind={kind} bounds={bounds} -> best move",
            OUTPUT_ERROR,
        )
        return self._best_move(f"{self.LABEL}: invariant check failed, playing best move.")

    def _veil_terminal(self, cands, player, best_gtp, lead, u, info):
        """S7（相手の直前パス）と S8（終局帯）。該当すれば (result, tier, kind, fields)、しなければ None。"""
        return None

    def _generate_move(self) -> Tuple[Move, str]:
        # ---- S0 ラッパー: 解析の破棄は上へ、それ以外の例外は最善手 ----
        try:
            return self._veil_move()
        except AnalysisDiscardedException:
            raise
        except Exception as e:  # noqa: BLE001 フェイルセーフ＝どんな例外でも最善手
            self.game.katrain.log(
                f"[{type(self).__name__}] error {type(e).__name__}: {e} -> best move", OUTPUT_ERROR
            )
            self.last_decision_info = {"tier": "failsafe", "kind": "best", "why": "error", "error": repr(e)}
            return self._best_move(f"{self.LABEL}: internal error, playing best move.")

    def _veil_move(self) -> Tuple[Move, str]:
        # ---- S1 前処理（クエリ0本）----
        t0 = time.time()
        self._cancel_ponder()  # 前に動いていた難解の ponder の後始末（走っていなければ何もしない）
        self.game.board_watch_probe_warm = False  # 難解が立てたままだと監視の先読みが Probe の温めを続ける
        self.wait_for_analysis()
        self.last_decision_info = {}
        state = self._veil_state()
        cn = self.cn
        player = cn.next_player
        sign = 1 if player == "B" else -1
        opponent = "W" if player == "B" else "B"
        info = {"depth": cn.depth, "player": player, "queries": 0, "t0": t0}

        def finish(result, tier, kind, **fields):
            return self._veil_finish(result, info, tier, kind, **fields)

        # ---- S2 盤サイズ ----
        side = self.BOARD_LEN
        if max(self.game.board_size) != side:
            self.game.katrain.log(
                f"[{type(self).__name__}] board size {self.game.board_size} is not {side}x{side}; "
                f"this mode is {side}x{side}-only, playing KataGo best move",
                OUTPUT_INFO,
            )
            return finish(
                self._best_move(f"{self.LABEL}: not a {side}x{side} board, playing best move."),
                "failsafe", "best", why="board",
            )

        # ---- S3 最善手（レポートと同じ candidate_moves[0]）----
        cands = cn.candidate_moves
        if not cands:
            return finish(self._best_move(f"{self.LABEL}: no candidate moves."), "failsafe", "best", why="no_cands")
        best_gtp = cands[0]["move"]
        info["best"] = best_gtp
        if best_gtp == "pass":
            return finish(self._best_move(f"{self.LABEL}: best move is pass, playing it."), "i", "best", why="pass")
        cand_gtps = {d["move"] for d in cands}

        # ---- S4 一致率（クエリ0本・レポートと同じ定義）----
        nodes = cn.nodes_from_root
        mine, n_mine, opp, n_opp = veil_tally(nodes, player)
        _mine_t, opp_trunc, _counted = parity9_match_tally(nodes, player)
        target = float(self._setting("target_rate"))
        p_match, u = veil_urgency(mine, n_mine, target)
        info.update(mine=mine, n=n_mine, opp=opp, n_opp=n_opp, opp_trunc=opp_trunc, p_match=p_match, T=target, u=u)
        self._log(
            f"Rate: mine={mine}/{n_mine} opp={opp}/{n_opp} opp_trunc={opp_trunc} "
            f"p_match={p_match:.3f} target={target:.2f} u={u:.2f}"
        )

        # ---- S5 リード（打つ側視点）----
        root = cn.analysis.get("root") or {}
        root_lead = root.get("scoreLead")
        if root_lead is None:
            self._log("Lead unavailable -> best move")
            return finish(
                self._best_move(f"{self.LABEL}: lead unavailable, playing best move."), "failsafe", "best", why="no_lead"
            )
        lead = root_lead * sign
        root_wr = root.get("winrate")
        root_wr = None if root_wr is None else (root_wr if player == "B" else 1.0 - root_wr)
        info.update(lead=lead, root_wr=root_wr)

        # ---- S6 ヨセ判定（sticky・クエリ0本。ownership が無ければ手数だけ）----
        board = self.VEIL_BOARD
        in_yose = bool(state["endgame"])
        if not in_yose and cn.depth >= board["endgame_move"]:
            ownership = cn.analysis.get("ownership")
            n_unsettled = None if ownership is None else sum(1 for o in ownership if abs(o) < PARITY9_UNSETTLED_ABS)
            if parity9_is_endgame(cn.depth, ownership, board["endgame_move"], board["unsettled_max"]):
                state["endgame"] = True
                in_yose = True
            info["unsettled"] = n_unsettled
            self._log(
                f"Endgame check: depth={cn.depth} thr={board['endgame_move']} unsettled={n_unsettled} "
                f"max={board['unsettled_max']} -> {'yose (sticky)' if in_yose else 'not yet'}"
            )
        info["in_yose"] = in_yose

        # ---- S7 / S8 相手の直前パス・終局帯 ----
        terminal = self._veil_terminal(cands, player, best_gtp, lead, u, info)
        if terminal is not None:
            result, tier, kind, fields = terminal
            return finish(result, tier, kind, **fields)

        # ---- S9 予算 ----
        reserve = float(self._setting("reserve"))
        f_eff = veil_free_limit(float(self._setting("free_loss")), lead, p_match)
        cap_phase = float(self._setting("yose_max_loss" if in_yose else "max_loss"))
        allowance, surplus = veil_allowance(lead, reserve, float(self._setting("spend_rate")), f_eff, cap_phase, u)
        info.update(reserve=reserve, F=f_eff, S=surplus, A_t=allowance, cap=cap_phase)
        self._log(
            f"Budget: lead={lead:.2f} reserve={reserve:.1f} S={surplus:.2f} F={f_eff:.2f} "
            f"cap={cap_phase:.2f} A_t={allowance:.2f} yose={in_yose}"
        )

        # ---- S10 生の候補プール（クエリ0本）----
        trap_on = bool(self._setting("trap_mode"))
        candidates, _n_searched = parity9_build_candidates(cands, player=player, min_visits=ENIGMA9_POOL_MIN_VISITS)
        pool0 = [c for c in candidates if c["gtp"] not in (best_gtp, "pass")]
        raw_cap = max(f_eff, allowance) + VEIL_RAW_MARGIN
        nat_pool = veil_prefilter(pool0, raw_cap)
        trap_pool = veil_prefilter(pool0, raw_cap + VEIL_TRAP_RAW_EXTRA) if trap_on else []
        if not nat_pool and not trap_pool:
            self._log(f"Tier i: no candidate within raw cap {raw_cap:.2f} -> best move")
            return finish(
                self._best_move(f"{self.LABEL}: only the best move is a candidate, playing it."),
                "i", "best", why="no_pool",
            )

        # ---- S11 親局面の humanSL（1本）----
        stage_hp = self._run_query(
            "parent hp",
            include_policy=True,
            ownership=False,
            visits=ENIGMA9_HP_CHILD_VISITS,
            extra_settings={"humanSLProfile": ENIGMA9_HUMAN_PROFILE, "ignorePreRootHistory": False},
        )
        info["queries"] += 1
        if not stage_hp or "humanPolicy" not in stage_hp:
            self._log("HumanSL unavailable -> best move")
            return finish(
                self._best_move(f"{self.LABEL}: humanSL unavailable, playing best move."), "failsafe", "best", why="no_hp"
            )
        human_policy = stage_hp["humanPolicy"]
        hp_of = enigma9_hp_lookup(human_policy, self.game.board_size)
        best_hp = hp_of(best_gtp)
        info["best_hp"] = best_hp

        # ---- S12 段の判定と自然さ ----
        dominant = best_hp >= float(self._setting("dominant_hp"))
        info["dominant"] = dominant
        if dominant and u <= 0:
            self._log(f"Tier ii closed: best {best_gtp} hp={best_hp:.3f} and rate at/below target -> best move")
            return finish(
                self._best_move(f"{self.LABEL}: the best move is the obvious human move (hp {best_hp:.1%}), playing it."),
                "ii", "best", why="dominant_closed",
            )
        tier = "ii" if dominant else "iii"
        dominant_max = float(self._setting("dominant_max_loss"))
        allowance2 = min(allowance, dominant_max) if dominant else allowance
        trap_cap = min(cap_phase, dominant_max) if dominant else cap_phase
        if dominant:  # 上限を絞るだけ（広げない）。自然用の足切りを掛け直す
            raw_cap = max(f_eff, allowance2) + VEIL_RAW_MARGIN
            nat_pool = veil_prefilter(pool0, raw_cap)
        info["A_t"] = allowance2
        floor = veil_natural_floor(
            mimic_hp_top(human_policy, self.game.board_size),
            float(self._setting("min_human_policy")),
            float(self._setting("natural_ratio")),
            dominant,
        )
        naturals = [c for c in nat_pool if hp_of(c["gtp"]) >= floor]
        trap_cands = [c for c in trap_pool if hp_of(c["gtp"]) >= VEIL_TRAP_MIN_HP]
        self._log(
            f"Natural: tier={tier} floor={floor:.3f} best_hp={best_hp:.3f} raw_cap={raw_cap:.2f} "
            f"naturals={[c['gtp'] for c in naturals]} trap_cands={len(trap_cands)}"
        )
        if not naturals and not trap_cands:
            return finish(
                self._best_move(f"{self.LABEL}: no natural alternative, playing best move."), "i", "best", why="no_natural"
            )

        # ---- S13〜S20 は Task 9b で置き換える（仮: 最善手）----
        return finish(
            self._best_move(f"{self.LABEL}: no safe deviation, playing best move."), tier, "best", why="none_qualified"
        )
'''

patch("katrain/core/constants.py", [('AI_MIMIC_13 = "ai:mimic13"\n', CONSTANTS, 1)])
patch(
    "katrain/core/ai.py",
    [
        (
            "AI_ENIGMA_9_PLUS, AI_ENIGMA_19_PLUS, AI_MIMIC_13\n)",
            "AI_ENIGMA_9_PLUS, AI_ENIGMA_19_PLUS, AI_MIMIC_13, AI_VEIL_9, AI_VEIL_13, AI_VEIL_19\n)",
            1,
        ),
        (ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1),
    ],
)
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t9a.py"`
Expected:
```
patched katrain/core/constants.py (CRLF, 1 edit(s))
patched katrain/core/ai.py (CRLF, 2 edit(s))
```

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `84 passed`

- [x] **Step 6: 既存戦略が無変更で通ることを確認**（登録の衝突・import の破損の検知）

Run: `pytest tests/test_ai_mimic13.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_gamble.py tests/test_ai_enigma_overdraft.py tests/test_ai_enigma_opening.py tests/test_ai_parity9.py -q`
Expected: 全 PASS

- [x] **Step 7: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 270 +++…-`（+269 / −1。削除は import 行の置き換え 1 行だけ）・`katrain/core/constants.py | 6 +`（削除 0 行）

- [x] **Step 8: コミット**

```bash
git add katrain/core/ai.py katrain/core/constants.py tests/test_ai_veil.py
git commit -m "feat(veil): Veil9Strategy の骨組みと前半フロー（S0〜S6・S9〜S12）と AI_VEIL_* 定数

一致率（レポート定義）→ リード → sticky ヨセ → 予算 → 生の足切り → 親 humanSL 1本 → 段の判定まで。
S13 以降（外し）は次のコミットで入れる（それまでは最善手）。ponder なし・HumanStyle 委譲なし・全フェイルセーフは最善手。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9b: 素の外し（S13〜S20: 決着局面の即決・子局面プローブ・free / paid・最安帯で hp 最大・不変条件・記録）

**Files:**
- Modify: `katrain/core/ai.py`（Task 9a の仮の末尾4行を置き換える）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: Task 9a の `_veil_move`（S12 までの局所変数 `tier` / `naturals` / `trap_cands` / `allowance2` / `trap_cap` / `floor` ほか）と仮の末尾4行・`_veil_punish` / `_veil_violation`・Task 3〜5・8 の純関数・既存の `enigma9_verified_metrics`
- Produces: `_veil_move` の S13〜S20。kind は `"decided"` / `"free"` / `"paid"`（罠の判定と合流は Task 9c）、why は `"no_shortlist"` / `"no_best_probe"` / `"none_qualified"` / `"invariant"`。罠 ON なら S14 の検証候補に罠枠が入るが、このタスクではまだ罠として選ばない。

- [x] **Step 1: 失敗するテストを書く** — ファイル末尾に追記（import は変えない）

```python
class TestTiersDeviating(_Harness):
    """段(ii) 開と決着局面の即決（S13 以降を通る手番）。"""

    def test_tier_ii_open_pays_only_up_to_dominant_max_loss(self):
        hp = {"E5": 0.85, "D4": 0.01, "F6": 0.06, "C7": 0.03, "G3": 0.04}  # 明らかな一手 → 床は 0.05 だけ
        ok, _ = self._strategy(hp=hp, probes={"E5": _child(10.0, 0.95), "F6": _child(8.8, 0.93)})
        move, _ = ok.generate_move()
        assert move.gtp() == "F6"
        assert ok.probe_calls == [["E5", "F6"]]  # C7（生 2.0）は絞った足切り 1.5 + 0.3 の外
        assert (ok.last_decision_info["tier"], ok.last_decision_info["kind"]) == ("ii", "paid")
        dear, _ = self._strategy(hp=hp, probes={"E5": _child(10.0, 0.95), "F6": _child(8.2, 0.93)})
        assert dear.generate_move()[0].gtp() == "E5"  # vloss 1.8 > dominant_max_loss 1.5

    def test_decided_position_deviates_without_probes(self):
        s, logs = self._strategy(lead=7.0, wr=0.98)
        move, _ = s.generate_move()
        assert move.gtp() == "D4"
        assert s.queries == ["parent hp"] and s.probe_calls == []
        assert s.last_decision_info["kind"] == "decided"


class TestFreeAndPaid(_Harness):
    def test_near_free_deviation_even_at_target(self):
        probes = {"E5": _child(0.5, 0.55), "D4": _child(0.45, 0.545)}
        s, logs = self._strategy(**EVEN, hist=_hist("B", 3, 9), probes=probes, board_watch_probe_warm=True)
        move, reason = s.generate_move()
        assert move.gtp() == "D4"
        assert s.probe_calls == [["E5", "D4"]]
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["best"], info["chosen"]) == ("iii", "free", "E5", "D4")
        assert (info["mine"], info["n"], info["u"], info["queries"]) == (3, 9, 0.0, 5)
        assert s.game._veil_state["veil9"]["ledger"] == [(12, "E5", "D4", "free")]
        assert any(m.startswith("[Veil9Strategy] Decision: {") for m in logs)
        assert any(m.startswith("[Veil9Strategy] Rate: mine=3/9") for m in logs)
        assert s.game.board_watch_probe_warm is False
        assert s.ponders == []

    def test_near_free_needs_a_small_winrate_drop(self):
        probes = {"E5": _child(0.5, 0.55), "D4": _child(0.45, 0.50)}
        s, _ = self._strategy(**EVEN, hist=_hist("B", 3, 9), probes=probes)
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["why"] == "none_qualified"

    def test_paid_deviation_from_surplus_when_above_target(self):
        hp = {**self.HP, "D4": 0.01, "F6": 0.30}
        s, _ = self._strategy(hp=hp, probes={"E5": _child(10.0, 0.95), "F6": _child(9.0, 0.93)})
        move, _ = s.generate_move()
        assert move.gtp() == "F6"
        assert s.last_decision_info["kind"] == "paid"
        assert s.last_decision_info["cost"] == pytest.approx(1.0)

    def test_winrate_floor_rejects_a_paid_deviation(self):
        hp = {**self.HP, "D4": 0.01, "F6": 0.30}
        s, _ = self._strategy(hp=hp, probes={"E5": _child(10.0, 0.95), "F6": _child(9.0, 0.80)})
        assert s.generate_move()[0].gtp() == "E5"

    def test_small_surplus_cannot_pay_below_the_reserve(self):
        cands = [dict(c) for c in self.CANDS]
        cands[2]["relativePointsLost"] = 0.3  # F6 を足切りの内側へ
        hp = {**self.HP, "D4": 0.01, "F6": 0.30}
        s, _ = self._strategy(
            lead=3.5, wr=0.9, cands=cands, hp=hp, probes={"E5": _child(3.5, 0.9), "F6": _child(2.5, 0.88)}
        )
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["A_t"] == pytest.approx(0.25)

    def test_the_rate_line_counts_the_opponent_like_the_report(self):
        s, logs = self._strategy(**EVEN, hist=_hist("B", 3, 9, opp=2, n_opp=10), probes={})
        s.generate_move()
        assert (s.last_decision_info["opp"], s.last_decision_info["n_opp"]) == (2, 10)


class TestYoseAndCloseGames(_Harness):
    def test_yose_guard_needs_a_one_percent_drop_below_the_reserve(self):
        strict, _ = self._strategy(
            lead=2.5, wr=0.9, depth=32, probes={"E5": _child(2.5, 0.90), "D4": _child(2.45, 0.88)}
        )
        assert strict.generate_move()[0].gtp() == "E5"
        assert strict.game._veil_state["veil9"]["endgame"] is True  # 手数だけでヨセ（ownership なし）
        ok, _ = self._strategy(lead=2.5, wr=0.9, depth=32, probes={"E5": _child(2.5, 0.90), "D4": _child(2.45, 0.895)})
        assert ok.generate_move()[0].gtp() == "D4"

    def test_yose_is_sticky(self):
        state = {"veil9": {"endgame": True, "close_drift": 0.0, "ledger": []}}
        s, _ = self._strategy(depth=20, probes={}, _veil_state=state)
        s.generate_move()
        assert s.last_decision_info["in_yose"] is True
        assert s.last_decision_info["cap"] == pytest.approx(1.0)  # yose_max_loss

    @pytest.mark.parametrize(
        "cap,drift,expected,drift_after", [(0.0, 0.08, "D4", 0.08), (0.1, 0.08, "E5", 0.08), (0.2, 0.08, "D4", 0.13)]
    )
    def test_close_drift_cap(self, cap, drift, expected, drift_after):
        state = {"veil9": {"endgame": False, "close_drift": drift, "ledger": []}}
        probes = {"E5": _child(0.5, 0.55), "D4": _child(0.45, 0.545)}
        s, _ = self._strategy(
            **EVEN, hist=_hist("B", 3, 9), probes=probes, settings={"veil9_close_drift_cap": cap}, _veil_state=state
        )
        assert s.generate_move()[0].gtp() == expected
        assert state["veil9"]["close_drift"] == pytest.approx(drift_after)


class TestFailSafesDeviating(_Harness):
    """best プローブの欠落と不変条件違反（S15〜S19）。"""

    def test_missing_best_probe(self):
        s, _ = self._strategy(probes={"D4": _child(9.95, 0.948)})
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["why"] == "no_best_probe"

    def test_invariant_violation_plays_the_best_move(self, monkeypatch):
        bogus = {"gtp": "J9", "kind": "free", "cost": 0.0, "vloss": 0.0, "hp": 0.5, "raw": 0.0, "cons": 0.0}
        monkeypatch.setattr(ai_module, "veil_choose", lambda *a, **k: dict(bogus))
        probes = {"E5": _child(0.5, 0.55), "D4": _child(0.45, 0.545)}
        s, logs = self._strategy(**EVEN, hist=_hist("B", 3, 9), probes=probes)
        assert s.generate_move()[0].gtp() == "E5"
        assert any("Invariant violated: chosen=J9" in m for m in logs)
        assert s.last_decision_info["why"] == "invariant"
        assert s.ponders == []
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `9 failed, 90 passed`（仮の末尾は常に最善手なので、外すはずの手番と `no_best_probe` / `Invariant violated` を見るテストが落ちる。最善手のままで正しい手番のテストは通る）

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t9b.py`（仮の末尾4行を丸ごと置き換える）

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

STUB = '''        # ---- S13〜S20 は Task 9b で置き換える（仮: 最善手）----
        return finish(
            self._best_move(f"{self.LABEL}: no safe deviation, playing best move."), tier, "best", why="none_qualified"
        )
'''

REAL = r'''
        # ---- S13 決着局面の即決（プローブ0本）----
        slack = float(self._setting("cost_slack"))
        if root_wr is not None and root_wr >= VEIL_DECIDED_WR and lead >= reserve + VEIL_DECIDED_MARGIN and not dominant:
            quick = [
                {**c, "kind": "decided", "cost": max(0.0, c["loss"]), "hp": hp_of(c["gtp"]), "wr_after": c.get("wr")}
                for c in naturals
                if c["loss"] <= f_eff + _VEIL_EPS and c.get("visits", 0) >= board["trusted_visits"]
            ]
            pick = veil_choose(quick, slack, prefer_safe=False)
            if pick is not None:
                bounds = {"cost": pick["cost"], "f_eff": f_eff}
                if not veil_invariant_ok(pick["gtp"], best_gtp, cand_gtps, "decided", bounds):
                    return finish(
                        self._veil_violation(pick["gtp"], "decided", bounds), "failsafe", "best", why="invariant"
                    )
                self._log(f"Decided: played {pick['gtp']} (raw {pick['loss']:.2f}, hp {pick['hp']:.3f}) without probes")
                return finish(
                    (
                        Move.from_gtp(pick["gtp"], player=player),
                        f"{self.LABEL}: decided position, near-free deviation to {pick['gtp']} "
                        f"(raw loss {pick['loss']:.2f}, hp {pick['hp']:.1%}) instead of {best_gtp}.",
                    ),
                    tier, "decided", raw=pick["loss"], cost=pick["cost"], hp=pick["hp"],
                )

        # ---- S14 検証する候補 ----
        band_cap = raw_cap if (u > 0 and surplus > 0) else f_eff + VEIL_RAW_MARGIN
        nat_short, trap_short = veil_shortlist(
            naturals, trap_cands, hp_of, band_cap, board["probe_hp"], board["probe_cheap"],
            VEIL_TRAP_PROBES if trap_on else 0,
        )
        shortlist = nat_short + trap_short
        if not shortlist:
            return finish(
                self._best_move(f"{self.LABEL}: no alternative in the passable band, playing best move."),
                tier, "best", why="no_shortlist",
            )

        # ---- S15 プローブ（best + 候補を1バッチ）----
        probes, _unused = self._probe_children([best_gtp] + [c["gtp"] for c in shortlist], player, parent_hp=False)
        info["queries"] += 2 * (1 + len(shortlist))
        best_probe = probes.get(best_gtp) or {}
        best_lead_after, best_wr_after = enigma9_verified_metrics(best_probe.get("clean"), player)
        if best_lead_after is None:
            self._log("Best-move probe unavailable -> best move")
            return finish(
                self._best_move(f"{self.LABEL}: best-move probe unavailable, playing best move."),
                "failsafe", "best", why="no_best_probe",
            )
        best_e, _best_find = self._veil_punish(best_probe, opponent)
        close = lead < reserve or best_wr_after is None or best_wr_after < VEIL_CLOSE_WR
        info["close"] = close
        drift_cap = float(self._setting("close_drift_cap"))
        ctx = VeilCtx(
            lead=lead,
            reserve=reserve,
            surplus=surplus,
            urgency=u,
            p_match=p_match,
            f_eff=f_eff,
            allowance=allowance2,
            trap_cap=trap_cap,
            min_winrate=float(self._setting("min_winrate")),
            free_wr_drop=float(self._setting("free_wr_drop")),
            in_yose=in_yose,
            close=close,
            close_drift=state["close_drift"],
            close_drift_cap=drift_cap,
            trap_min_delta_e=float(self._setting("trap_min_delta_e")),
        )

        # ---- S16 分類（自然枠は free / paid、罠は §7）----
        nat_gtps = {c["gtp"] for c in nat_short}
        plain = []
        for c in shortlist:
            pr = probes.get(c["gtp"]) or {}
            lead_after, wr_after = enigma9_verified_metrics(pr.get("clean"), player)
            if lead_after is None:
                self._log(f"Probe incomplete for {c['gtp']} -> dropped")
                continue
            vloss = best_lead_after - lead_after
            wr_drop = None if (wr_after is None or best_wr_after is None) else best_wr_after - wr_after
            cons = veil_cons_loss(vloss, c["loss"], c.get("visits", 0), board["trusted_visits"])
            e_punish, find = self._veil_punish(pr, opponent)
            d_e = None if (e_punish is None or best_e is None) else e_punish - best_e
            row = {
                **c, "raw": c["loss"], "vloss": vloss, "cons": cons, "wr_after": wr_after, "wr_drop": wr_drop,
                "lead_after": lead_after, "hp": hp_of(c["gtp"]), "e": e_punish, "d_e": d_e, "find": find,
            }
            kind, cost = (None, max(0.0, cons))
            if c["gtp"] in nat_gtps:
                kind, cost = veil_classify(row, ctx)
                if kind:
                    plain.append({**row, "kind": kind, "cost": cost})
            wr_txt = "n/a" if wr_after is None else f"{wr_after:.1%}"
            de_txt = "n/a" if d_e is None else f"{d_e:+.2f}"
            self._log(
                f"Score {c['gtp']}: raw={c['loss']:.2f} vloss={vloss:.2f} cons={cons:.2f} wr={wr_txt} "
                f"hp={row['hp']:.3f} dE={de_txt} kind={kind or '-'}"
            )

        # ---- S17 / S18 選択と罠の合流 ----
        plain_pick = veil_choose(plain, slack, prefer_safe=surplus > 0)
        chosen = plain_pick
        if chosen is None:
            self._log("No qualifying deviation -> best move")
            return finish(
                self._best_move(f"{self.LABEL}: no safe deviation, playing best move."), tier, "best", why="none_qualified"
            )

        # ---- S19 不変条件 ----
        kind = chosen["kind"]
        if kind == "free":
            bounds = {"cost": chosen["cost"], "f_eff": f_eff}
        elif kind == "paid":
            bounds = {"cost": chosen["cost"], "allowance": allowance2, "lead": lead, "reserve": reserve}
        else:
            bounds = {
                "price": chosen.get("price"), "allow": allowance2 if u > 0 else 0.0, "vloss": chosen.get("vloss"),
                "trap_cap": trap_cap, "lead": lead, "reserve": reserve,
            }
        if not veil_invariant_ok(chosen.get("gtp"), best_gtp, cand_gtps, kind, bounds):
            return finish(self._veil_violation(chosen.get("gtp"), kind, bounds), "failsafe", "best", why="invariant")

        # ---- S20 記録 ----
        if kind == "free" and close and drift_cap > 0:
            state["close_drift"] += max(0.0, chosen["vloss"])
        self._log(
            f"Deviate: played {chosen['gtp']} ({kind}, cost={chosen['cost']:.2f}, vloss={chosen['vloss']:.2f}, "
            f"hp={chosen['hp']:.3f}) instead of {best_gtp}"
        )
        return finish(
            (
                Move.from_gtp(chosen["gtp"], player=player),
                f"{self.LABEL}: deviated to {chosen['gtp']} ({kind}, verified loss {chosen['vloss']:.2f}, "
                f"hp {chosen['hp']:.1%}) instead of {best_gtp}; match rate {mine}/{n_mine}, target {target:.0%}.",
            ),
            tier, kind, raw=chosen["raw"], vloss=chosen["vloss"], cons=chosen["cons"], cost=chosen["cost"],
            hp=chosen["hp"], d_e=chosen.get("d_e"), E=chosen.get("e"), find_hp=chosen.get("find"),
            price=chosen.get("price"),
        )
'''

patch("katrain/core/ai.py", [(STUB, REAL.strip("\n") + "\n", 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t9b.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `99 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 141 +++…--`（+139 / −2。置き換えるのは仮の末尾4行だが、そのうち `        return finish(` と `        )` の2行は新しいコードの行と一致するので git の数える削除は 2 行。これより多ければ再整形の混入）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 素の外し（S13〜S20）＝決着局面の即決・子局面プローブ・free/paid・最安帯で hp 最大・不変条件

自然枠（＋罠枠）を best と1バッチでプローブし、同値外しは一致率に関係なく、支払う外しは u > 0 かつ余剰の範囲で。
選んだ手は候補に含まれ最善手でも pass でもなく種類ごとの上限内であることを最後に確かめる。罠の判定は次のコミット。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9c: 罠の上乗せ層（S16 の `veil_trap_ok`・`trap_shadow`・S17 の `veil_merge_trap`）

**Files:**
- Modify: `katrain/core/ai.py`（Task 9b の S16〜S17 に5か所の置き換え。それ以外の行は変えない）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: Task 6 の `veil_trap_ok` / `veil_merge_trap`・Task 9b の S16 のループ（`row` / `ctx` / `vloss` / `trap_on`）
- Produces: 罠 ON なら合格した罠を素の外しと合流（kind `"trap"`・`price` / `E` / `d_e` / `find_hp` を Decision に残す）、罠 OFF でも使えたはずの罠の数を `last_decision_info["trap_shadow"]` に残す。`Score …` 行に `trap=` の列。

- [x] **Step 1: 失敗するテストを書く** — ファイル末尾に追記（import は変えない）

```python
class TestTrapLayer(_Harness):
    PROBES = {"E5": _child(10.0, 0.95), "D4": _child(9.95, 0.948), "F6": _child(9.2, 0.93)}

    def test_trap_mode_only_adds_trap_slots_to_the_probe_batch(self):
        off, _ = self._strategy(probes=self.PROBES)
        on, _ = self._strategy(probes=self.PROBES, settings={"veil9_trap_mode": True})
        assert off.generate_move()[0].gtp() == on.generate_move()[0].gtp() == "D4"
        assert off.queries == on.queries == ["parent hp"]
        assert off.probe_calls == [["E5", "D4", "F6"]]
        assert on.probe_calls == [["E5", "D4", "F6", "C7", "G3"]]

    def test_a_plain_deviation_is_not_lost_to_a_dearer_trap(self):
        probes = {**self.PROBES, "C7": _child(8.4, 0.90, punish=3.0)}  # 値段 1.6 − 0.5 × 2.7 = 0.25
        s, _ = self._strategy(probes=probes, settings={"veil9_trap_mode": True})
        assert s.generate_move()[0].gtp() == "D4"
        assert s.last_decision_info["kind"] == "free"

    def test_a_clearly_cheaper_trap_replaces_the_plain_deviation(self):
        probes = {**self.PROBES, "C7": _child(9.6, 0.94, punish=3.0)}  # 値段 0.4 − 1.35 = −0.95
        s, _ = self._strategy(probes=probes, settings={"veil9_trap_mode": True})
        assert s.generate_move()[0].gtp() == "C7"
        assert s.last_decision_info["kind"] == "trap"
        assert s.last_decision_info["price"] == pytest.approx(-0.95)
        assert s.last_decision_info["E"] == pytest.approx(2.7)  # ハーネスが罠の実損 / E に使うキー

    def test_trap_off_only_logs_the_trap_it_could_have_used(self):
        hp = {**self.HP, "D4": 0.30}
        probes = {"E5": _child(10.0, 0.95), "D4": _child(9.9, 0.94, punish=3.0), "F6": _child(9.2, 0.93)}
        s, _ = self._strategy(hp=hp, probes=probes)
        assert s.generate_move()[0].gtp() == "D4"
        assert s.last_decision_info["trap_shadow"] == 1

    def test_yose_trap_never_exceeds_yose_max_loss(self):
        hp = {"E5": 0.40, "D4": 0.01, "F6": 0.01, "C7": 0.03, "G3": 0.04}
        probes = {"E5": _child(10.0, 0.95), "C7": _child(8.8, 0.93, punish=3.0)}  # vloss 1.2・値段 −0.15
        yose, _ = self._strategy(depth=32, hp=hp, probes=probes, settings={"veil9_trap_mode": True})
        assert yose.generate_move()[0].gtp() == "E5"  # ヨセの上限 yose_max_loss 1.0 < 1.2
        mid, _ = self._strategy(depth=12, hp=hp, probes=probes, settings={"veil9_trap_mode": True})
        assert mid.generate_move()[0].gtp() == "C7"

    def test_dominant_trap_never_exceeds_dominant_max_loss(self):
        hp = {"E5": 0.85, "D4": 0.01, "F6": 0.01, "C7": 0.03, "G3": 0.04}
        dear = {"E5": _child(10.0, 0.95), "C7": _child(8.2, 0.93, punish=3.0)}  # vloss 1.8 > 1.5
        s, _ = self._strategy(hp=hp, probes=dear, settings={"veil9_trap_mode": True})
        assert s.generate_move()[0].gtp() == "E5"
        cheap = {"E5": _child(10.0, 0.95), "C7": _child(8.8, 0.93, punish=3.0)}
        s, _ = self._strategy(hp=hp, probes=cheap, settings={"veil9_trap_mode": True})
        assert s.generate_move()[0].gtp() == "C7"
        assert s.last_decision_info["tier"] == "ii"
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `4 failed, 101 passed`（罠を選ぶはずの手番と `trap_shadow` を見るテストが落ちる。罠枠のプローブ列と「高い罠に素の外しを奪われない」テストは Task 9b の時点で通る）

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t9c.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

# S16 に罠の判定、ループの後に trap_shadow、S17 に罠の合流を足す（それ以外の行は変えない）
EDITS = [
    (
        r'''        nat_gtps = {c["gtp"] for c in nat_short}
        plain = []
''',
        r'''        nat_gtps = {c["gtp"] for c in nat_short}
        plain, traps, shadow = [], [], []
''',
    ),
    (
        r'''                    plain.append({**row, "kind": kind, "cost": cost})
            wr_txt = "n/a" if wr_after is None else f"{wr_after:.1%}"
''',
        r'''                    plain.append({**row, "kind": kind, "cost": cost})
            trap_ok, price = veil_trap_ok(row, ctx)
            if trap_ok:
                (traps if trap_on else shadow).append({**row, "kind": "trap", "price": price, "cost": max(0.0, vloss)})
            wr_txt = "n/a" if wr_after is None else f"{wr_after:.1%}"
''',
    ),
    (
        r'''                f"hp={row['hp']:.3f} dE={de_txt} kind={kind or '-'}"
''',
        r'''                f"hp={row['hp']:.3f} dE={de_txt} kind={kind or '-'} trap={'ok' if trap_ok else '-'}"
''',
    ),
    (
        r'''            )

        # ---- S17 / S18 選択と罠の合流 ----
''',
        r'''            )
        info["trap_shadow"] = len(shadow)

        # ---- S17 / S18 選択と罠の合流 ----
''',
    ),
    (
        r'''        chosen = plain_pick
''',
        r'''        chosen = veil_merge_trap(plain_pick, traps) if trap_on else plain_pick
''',
    ),
]

patch("katrain/core/ai.py", [(old, new, 1) for old, new in EDITS])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t9c.py"`
Expected: `patched katrain/core/ai.py (CRLF, 5 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `105 passed`

- [x] **Step 6: 既存戦略が無変更で通ることを確認**

Run: `pytest tests/test_ai_mimic13.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_gamble.py tests/test_ai_enigma_overdraft.py tests/test_ai_enigma_opening.py tests/test_ai_parity9.py -q`
Expected: 全 PASS

- [x] **Step 7: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 10 +++++++---`（+7 / −3。削除は置き換えた 3 行だけ）

- [x] **Step 8: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 罠の上乗せ層（veil_trap_ok の判定・veil_merge_trap・trap_shadow）

罠 ON なら合格した罠を素の外しと合流（0.3 目以上安いときだけ替える・素の外しは消えない）。
罠 OFF でも使えたはずの罠の数を trap_shadow に残す。ヨセ・明らかな一手の上限を罠にも掛ける。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: 相手の直前パスと終局帯（S7 / S8 の `_veil_terminal`）

**Files:**
- Modify: `katrain/core/ai.py`（Task 9a の仮の `_veil_terminal` を置き換える）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: 継承した `_terminal_band_move(cands, player)`（相手の直前パスでは必ず非 None）・既存の `enigma9_pass_loss` / `enigma9_human_top` / `enigma9_terminal_pass` / `enigma9_terminal_move` / `_AREA_PASS_MARGIN`・Task 7 の `veil_terminal_limit` / `veil_terminal_swap`・Task 8 の `veil_invariant_ok`
- Produces: `_veil_terminal(cands, player, best_gtp, lead, u, info) -> None | (result, "terminal"|"failsafe", kind, fields)`（kind は `"pass"` / `"best"` / `"swap"` / `"finish"`、`fields["why"]` は `"opp_pass"` / `"terminal"` / `"no_hp"` / `"invariant"`）

- [x] **Step 1: 失敗するテストを書く** — ファイル末尾に追記（import は変えない）

```python
class TestTerminal(_Harness):
    """S7（相手の直前パス）と S8（終局帯）。9路・黒番・最善手 E5。"""

    END = [
        {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.9},
        {"move": "D4", "pointsLost": 0.04, "relativePointsLost": 0.04, "visits": 50, "winrate": 0.9},
        {"move": "C3", "pointsLost": 0.08, "relativePointsLost": 0.08, "visits": 40, "winrate": 0.9},
        {"move": "F6", "pointsLost": 0.3, "relativePointsLost": 0.3, "visits": 30, "winrate": 0.9},
        {"move": "G7", "pointsLost": 0.02, "relativePointsLost": 0.02, "visits": 5, "winrate": 0.9},
        {"move": "pass", "pointsLost": 0.2, "relativePointsLost": 0.2, "visits": 60, "winrate": 0.9},
    ]
    # 盤上の第一感 G7 0.45 → 床 = max(0.05, 0.2 × 0.45) = 0.09
    END_HP = {"E5": 0.30, "D4": 0.10, "C3": 0.25, "F6": 0.40, "G7": 0.45, "pass": 0.0}

    def _end(self, pass_loss=0.2, **kw):
        cands = [dict(c) for c in self.END]
        cands[-1]["relativePointsLost"] = cands[-1]["pointsLost"] = pass_loss
        kw.setdefault("hp", self.END_HP)
        return self._strategy(cands=cands, **kw)

    def test_opponent_pass_with_an_expensive_pass_never_deviates(self):
        s, _ = self._end(pass_loss=3.0, lead=10.0, last_move=Move(None, player="W"), ownership=[0.1] * 81)
        move, _ = s.generate_move()
        assert move.gtp() == "E5"
        assert s.queries == ["Probe"] and s.probe_calls == []
        info = s.last_decision_info
        assert (info["tier"], info["why"], info["queries"]) == ("terminal", "opp_pass", 1)

    def test_opponent_pass_on_a_settled_board_passes(self):
        s, _ = self._end(pass_loss=3.0, last_move=Move(None, player="W"), ownership=[0.95] * 81)
        assert s.generate_move()[0].is_pass
        assert s.queries == ["Probe"]

    def test_opponent_pass_with_a_cheap_pass_passes_without_queries(self):
        s, _ = self._end(pass_loss=0.2, last_move=Move(None, player="W"))
        assert s.generate_move()[0].is_pass
        assert s.queries == [] and s.last_decision_info["kind"] == "pass"

    def test_terminal_band_passes_when_a_9d_would(self):
        s, _ = self._end(hp={**self.END_HP, "pass": 0.6})
        assert s.generate_move()[0].is_pass
        assert s.queries == ["parent hp"] and s.probe_calls == []

    def test_swap_allows_0_10_with_a_clear_lead_and_0_05_in_a_close_game(self):
        clear, _ = self._end(lead=10.0)
        move, _ = clear.generate_move()
        assert move.gtp() == "C3"  # hp 0.25・0.08 目（F6 は 0.3 目、G7 は visits 5）
        assert clear.last_decision_info["kind"] == "swap" and clear.probe_calls == []
        close, _ = self._end(lead=1.0)
        assert close.generate_move()[0].gtp() == "D4"  # 0.05 目以内は D4 だけ

    def test_swap_needs_an_open_gate_for_an_obvious_move(self):
        hp = {**self.END_HP, "E5": 0.85, "G7": 0.05}
        s, _ = self._end(lead=10.0, hist=_hist("B", 3, 9), hp=hp)
        move, _ = s.generate_move()
        assert move.gtp() == "E5"  # 9段の最上位 E5＝最善手（(d)）
        assert s.last_decision_info["kind"] == "best"

    def test_finishing_move_respects_the_same_loss_limit(self):
        hp = {"E5": 0.30, "D4": 0.01, "C3": 0.01, "F6": 0.02, "G7": 0.45}
        cheap, _ = self._end(lead=1.0, hp=hp)
        assert cheap.generate_move()[0].gtp() == "G7"  # 0.02 目 <= 0.05
        assert cheap.last_decision_info["kind"] == "finish"
        dear_cands = [dict(c) for c in self.END]
        dear_cands[4]["relativePointsLost"] = 0.3
        dear, _ = self._strategy(cands=dear_cands, lead=1.0, hp=hp)
        assert dear.generate_move()[0].gtp() == "E5"  # 0.3 目 > 0.05（margin 0.5 未満でも打たない）

    @pytest.mark.parametrize("cap,kind,drift_after", [(0.0, "swap", 0.08), (0.2, "swap", 0.12), (0.1, "finish", 0.08)])
    def test_close_drift_cap_limits_the_swap(self, cap, kind, drift_after):
        hp = {"E5": 0.20, "D4": 0.30, "C3": 0.25, "F6": 0.0, "G7": 0.0}
        state = {"veil9": {"endgame": False, "close_drift": 0.08, "ledger": []}}
        s, _ = self._end(lead=1.0, hp=hp, settings={"veil9_close_drift_cap": cap}, _veil_state=state)
        assert s.generate_move()[0].gtp() == "D4"
        assert s.last_decision_info["kind"] == kind
        assert state["veil9"]["close_drift"] == pytest.approx(drift_after)

    def test_terminal_humansl_failure_plays_the_best_move(self):
        s, _ = self._end(hp_ok=False)
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["why"] == "no_hp"
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `9 failed, 107 passed`（仮の `_veil_terminal` は常に None なので、相手の直前パスでも `parent hp` を撃って外しに進む等）

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t10.py`（仮の実装の3行を丸ごと置き換える）

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

STUB = '''    def _veil_terminal(self, cands, player, best_gtp, lead, u, info):
        """S7（相手の直前パス）と S8（終局帯）。該当すれば (result, tier, kind, fields)、しなければ None。"""
        return None
'''

REAL = r'''
    def _veil_terminal(self, cands, player, best_gtp, lead, u, info):
        """S7（相手の直前パス）と S8（終局帯）。該当すれば (result, tier, kind, fields)、しなければ None。"""
        pass_loss = enigma9_pass_loss(cands)
        # ---- S7 相手の直前パス: pass_loss の値に関係なく基底の終局処理（外しには進まない）----
        # pass_loss < 0.5 なら即パス、そうでなければ ownership の Probe を1本撃ち、決着ならパス・未決着なら最善手
        # （中国ルールで死石が残って pass が大損に出る終局でも外さない＝game_20260828_065952 の回帰防止）
        if self.cn.move is not None and self.cn.move.is_pass:
            cheap_pass = pass_loss is not None and pass_loss < _AREA_PASS_MARGIN
            info["queries"] += 0 if cheap_pass else 1
            result = self._terminal_band_move(cands, player)
            if result is not None:
                kind = "pass" if result[0].is_pass else "best"
                return result, "terminal", kind, {"why": "opp_pass", "pass_loss": pass_loss}
        if pass_loss is None or pass_loss >= _AREA_PASS_MARGIN:
            return None
        # ---- S8 終局帯（盤上に 0.5 目以上の手が無い）----
        stage_hp = self._run_query(
            "parent hp",
            include_policy=True,
            ownership=False,
            visits=ENIGMA9_HP_CHILD_VISITS,
            extra_settings={"humanSLProfile": ENIGMA9_HUMAN_PROFILE, "ignorePreRootHistory": False},
        )
        info["queries"] += 1
        board_size = self.game.board_size
        human_policy = (stage_hp or {}).get("humanPolicy")
        human_top = enigma9_human_top(human_policy, board_size)
        fields = {"why": "terminal", "pass_loss": pass_loss}
        if human_top is None:
            self._log(f"Terminal: pass loses {pass_loss:.2f} but humanSL unavailable -> best move")
            return (
                self._best_move(f"{self.LABEL}: game is nearly over, humanSL unavailable, playing best move."),
                "failsafe", "best", {**fields, "why": "no_hp"},
            )
        top_gtp, top_hp, pass_hp = human_top
        hp_of = enigma9_hp_lookup(human_policy, board_size)
        best_hp = hp_of(best_gtp)
        dominant = best_hp >= float(self._setting("dominant_hp"))
        floor = veil_natural_floor(
            mimic_hp_top(human_policy, board_size),
            float(self._setting("min_human_policy")),
            float(self._setting("natural_ratio")),
            dominant,
        )
        fields.update(best_hp=best_hp, dominant=dominant)
        # (b) 9段が pass を最上位に置き、pass の損失も margin 未満 → パス
        if enigma9_terminal_pass(pass_loss, pass_hp, top_hp):
            self._log(f"Terminal: pass loses {pass_loss:.2f}, humanSL pass {pass_hp:.1%} >= {top_gtp} {top_hp:.1%} -> pass")
            return (
                (Move(None, player=player), f"{self.LABEL}: game is over (pass loses {pass_loss:.2f}), passing."),
                "terminal", "pass", fields,
            )
        # (c) ダメ詰めの順番入れ替え（レポート上の不一致）
        state = self._veil_state()
        drift_cap = float(self._setting("close_drift_cap"))
        candidates, _n_searched = parity9_build_candidates(cands, player=player, min_visits=ENIGMA9_POOL_MIN_VISITS)
        limit = veil_terminal_limit(lead)
        swap = veil_terminal_swap(candidates, best_gtp, hp_of, floor, lead, dominant, u, state["close_drift"], drift_cap)
        if swap is not None:
            bounds = {"raw": swap["loss"], "limit": limit}
            if not veil_invariant_ok(swap["gtp"], best_gtp, {d["move"] for d in cands}, "terminal", bounds):
                return self._veil_violation(swap["gtp"], "terminal", bounds), "failsafe", "best", {**fields, "why": "invariant"}
            if drift_cap > 0 and abs(lead) < VEIL_TERMINAL_CLOSE_LEAD:
                state["close_drift"] += max(0.0, swap["loss"])
            self._log(f"Terminal swap: played {swap['gtp']} (raw {swap['loss']:.2f} <= {limit:.2f}, hp {swap['hp']:.3f})")
            return (
                (
                    Move.from_gtp(swap["gtp"], player=player),
                    f"{self.LABEL}: game is nearly over, filling {swap['gtp']} (loss {swap['loss']:.2f}) "
                    f"instead of {best_gtp}.",
                ),
                "terminal", "swap", {**fields, "raw": swap["loss"], "hp": swap["hp"]},
            )
        # (d) 9段の終局処理の手（最善手でなければ (c) と同じ損失上限）
        finish_loss = enigma9_terminal_move(top_gtp, cands)
        if finish_loss is not None and (top_gtp == best_gtp or finish_loss <= limit + _VEIL_EPS):
            kind = "best" if top_gtp == best_gtp else "finish"
            self._log(f"Terminal: humanSL top {top_gtp} {top_hp:.1%} (loss {finish_loss:.2f}) -> play it")
            return (
                (
                    Move.from_gtp(top_gtp, player=player),
                    f"{self.LABEL}: game is nearly over, playing the 9d finishing move {top_gtp} "
                    f"(loss {finish_loss:.2f}).",
                ),
                "terminal", kind, {**fields, "raw": finish_loss, "hp": top_hp},
            )
        # (e) 最善手
        self._log(f"Terminal: no cheap natural finishing move (limit {limit:.2f}) -> best move")
        return (
            self._best_move(f"{self.LABEL}: game is nearly over, playing best move."),
            "terminal", "best", fields,
        )
'''

patch("katrain/core/ai.py", [(STUB, REAL.strip("\n") + "\n", 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t10.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `116 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 91 +++…-`（削除は仮の `return None` の 1 行だけ）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 相手の直前パスと終局帯（S7/S8）

相手の直前パスは pass_loss の値に関係なく基底の終局処理（外しに進まない＝game_20260828_065952 の回帰防止）。
終局帯は 9段がパスならパス、ダメ詰めの順番入れ替え（0.10・接戦 0.05）、9段の終局処理の手（同じ上限）、最善手の順。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: 13路・19路版 `Veil13Strategy` / `Veil19Strategy`

**Files:**
- Modify: `katrain/core/ai.py`
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: `Veil9Strategy`（Task 9a〜9c・10）・`AI_VEIL_13` / `AI_VEIL_19`（Task 9a で constants.py に追加済み）
- Produces: `@register_strategy(AI_VEIL_13) class Veil13Strategy(Veil9Strategy)`（`BOARD_LEN = 13`・`KEY_PREFIX = "veil13"`・`LABEL = "Veil13"`・13路の `SETTING_DEFAULTS`・`VEIL_BOARD`）、`@register_strategy(AI_VEIL_19) class Veil19Strategy(Veil9Strategy)`（同 19路）。テスト側の `VEILS`（(クラス, 盤, 接頭辞, ai キー, 定数) の表）は Task 12 も使う。

- [x] **Step 1: 失敗するテストを書く** — import ブロック（`from katrain.core.ai import (` から、その直後の `from katrain.core.constants import AI_VEIL_9` の行まで＝Task 9a で置いた2つの import 文）を次に置き換え（Edit。constants の行も新しいブロックの1行に置き換わる＝constants の import が2本にならないこと）

```python
from katrain.core.ai import (
    STRATEGY_REGISTRY,
    AnalysisDiscardedException,
    Enigma9Strategy,
    Veil9Strategy,
    Veil13Strategy,
    Veil19Strategy,
    VeilCtx,
    game_report,
    veil_allowance,
    veil_choose,
    veil_classify,
    veil_close_drift_ok,
    veil_cons_loss,
    veil_decision_record,
    veil_free_limit,
    veil_invariant_ok,
    veil_merge_trap,
    veil_natural_floor,
    veil_near_free_ok,
    veil_paid_ok,
    veil_prefilter,
    veil_shortlist,
    veil_tally,
    veil_terminal_limit,
    veil_terminal_swap,
    veil_trap_ok,
    veil_trap_price,
    veil_urgency,
)
from katrain.core.constants import AI_VEIL_9, AI_VEIL_13, AI_VEIL_19
```

ファイル末尾に追記:

```python
# (クラス, 盤, 設定接頭辞, ai キー, 定数)
VEILS = [
    (Veil9Strategy, 9, "veil9", "ai:veil9", AI_VEIL_9),
    (Veil13Strategy, 13, "veil13", "ai:veil13", AI_VEIL_13),
    (Veil19Strategy, 19, "veil19", "ai:veil19", AI_VEIL_19),
]
VEIL_IDS = [v[2] for v in VEILS]


class TestBoardFamily:
    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_registered_with_board_prefix_and_label(self, cls, size, prefix, ai_key, const):
        assert const == ai_key
        assert STRATEGY_REGISTRY[const] is cls
        assert issubclass(cls, Veil9Strategy)
        assert (cls.BOARD_LEN, cls.KEY_PREFIX, cls.LABEL) == (size, prefix, f"Veil{size}")

    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_defaults_match_the_spec_table(self, cls, size, prefix, ai_key, const):
        assert cls.SETTING_DEFAULTS == EXPECTED_DEFAULTS[size]
        for key, value in SAFETY_DEFAULTS[size].items():
            assert cls.SETTING_DEFAULTS[key] == value, key

    def test_board_constants(self):
        assert Veil13Strategy.VEIL_BOARD == {
            "endgame_move": 85,
            "unsettled_max": 16,
            "trusted_visits": 50,
            "probe_hp": 3,
            "probe_cheap": 2,
        }
        assert Veil19Strategy.VEIL_BOARD == {
            "endgame_move": 150,
            "unsettled_max": 36,
            "trusted_visits": 50,
            "probe_hp": 3,
            "probe_cheap": 1,
        }

    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS[1:], ids=VEIL_IDS[1:])
    def test_the_flow_is_shared(self, cls, size, prefix, ai_key, const):
        assert cls._generate_move is Veil9Strategy._generate_move
        assert cls.generate_move is Enigma9Strategy.generate_move


class _Harness13(_Harness):
    CLS = Veil13Strategy
    SIZE = 13
    CANDS = [
        {"move": "G7", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.62},
        {"move": "D4", "pointsLost": 0.2, "relativePointsLost": 0.2, "visits": 80, "winrate": 0.61},
        {"move": "K10", "pointsLost": 1.0, "relativePointsLost": 1.0, "visits": 120, "winrate": 0.58},
        {"move": "A1", "pointsLost": 9.0, "relativePointsLost": 9.0, "visits": 3, "winrate": 0.20},
    ]
    HP = {"G7": 0.40, "D4": 0.30, "K10": 0.15}


class TestVeil13Flow(_Harness13):
    def test_budget_follows_the_spec_example(self):
        # 13路・u = 1・lead +7 → S = 2・A_t = 1.0（spec §6 の目安）
        s, logs = self._strategy(lead=7.0, wr=0.9, probes={})
        s.generate_move()
        assert s.last_decision_info["A_t"] == pytest.approx(1.0)
        assert any("Budget: lead=7.00 reserve=5.0 S=2.00 F=0.30 cap=4.50 A_t=1.00" in m for m in logs)

    def test_state_is_kept_per_board_prefix(self):
        probes = {"G7": _child(0.5, 0.55, size=13), "D4": _child(0.45, 0.545, size=13)}
        s, _ = self._strategy(lead=0.5, wr=0.55, hist=_hist("B", 2, 9), probes=probes)
        move, _ = s.generate_move()
        # u = 0（p_match 0.30 = 目標）・D4 は visits 80 >= trusted 50 → cons = max(0.05, 0.2) = 0.2 <= 0.3
        assert move.gtp() == "D4" and s.last_decision_info["kind"] == "free"
        assert list(s.game._veil_state) == ["veil13"]

    def test_endgame_threshold_is_85_moves(self):
        s, _ = self._strategy(depth=84, probes={})
        s.generate_move()
        assert s.last_decision_info["in_yose"] is False
        s, _ = self._strategy(depth=85, probes={})
        s.generate_move()
        assert s.last_decision_info["in_yose"] is True

    def test_wrong_board_plays_the_best_move(self):
        s, logs = self._strategy(size=9, cands=[dict(c) for c in _Harness.CANDS])
        assert s.generate_move()[0].gtp() == "E5"
        assert any("is not 13x13" in m for m in logs)
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: 収集エラー `ImportError: cannot import name 'Veil13Strategy' from 'katrain.core.ai'`

- [x] **Step 3: パッチスクリプトを Write** — `<scratchpad>/patch_veil_t11.py`

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "\n\n\n@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

BLOCK = r'''
@register_strategy(AI_VEIL_13)
class Veil13Strategy(Veil9Strategy):
    """13路専用「韜晦」戦略（Veil9Strategy の盤サイズ・設定キー・既定値差し替え版）。

    既定値は SETTING_DEFAULTS（13路は自己対局ハーネスで測って選ぶ・値と校正状況は
    .claude/rules/ai-parameters.md）。sticky 状態は `game._veil_state["veil13"]`。
    """

    BOARD_LEN = 13
    KEY_PREFIX = "veil13"
    LABEL = "Veil13"
    SETTING_DEFAULTS = {
        "target_rate": 0.30,
        "reserve": 5.0,
        "min_winrate": 0.85,
        "free_loss": 0.3,
        "free_wr_drop": 0.03,
        "close_drift_cap": 0.0,
        "spend_rate": 0.5,
        "max_loss": 4.5,
        "yose_max_loss": 1.5,
        "dominant_hp": 0.8,
        "dominant_max_loss": 2.0,
        "min_human_policy": 0.05,
        "natural_ratio": 0.2,
        "cost_slack": 0.3,
        "trap_mode": False,
        "trap_min_delta_e": 0.5,
    }
    VEIL_BOARD = {"endgame_move": 85, "unsettled_max": 16, "trusted_visits": 50, "probe_hp": 3, "probe_cheap": 2}


@register_strategy(AI_VEIL_19)
class Veil19Strategy(Veil9Strategy):
    """19路専用「韜晦」戦略（Veil9Strategy の盤サイズ・設定キー・既定値差し替え版・未校正）。

    1手の解析が重いので自然枠の安い順は 1 手（probe_hp 3 + probe_cheap 1）。sticky 状態は
    `game._veil_state["veil19"]`。
    """

    BOARD_LEN = 19
    KEY_PREFIX = "veil19"
    LABEL = "Veil19"
    SETTING_DEFAULTS = {
        "target_rate": 0.30,
        "reserve": 7.0,
        "min_winrate": 0.85,
        "free_loss": 0.3,
        "free_wr_drop": 0.03,
        "close_drift_cap": 0.0,
        "spend_rate": 0.5,
        "max_loss": 6.0,
        "yose_max_loss": 2.0,
        "dominant_hp": 0.8,
        "dominant_max_loss": 3.0,
        "min_human_policy": 0.05,
        "natural_ratio": 0.2,
        "cost_slack": 0.3,
        "trap_mode": False,
        "trap_min_delta_e": 0.7,
    }
    VEIL_BOARD = {"endgame_move": 150, "unsettled_max": 36, "trusted_visits": 50, "probe_hp": 3, "probe_cheap": 1}
'''

patch("katrain/core/ai.py", [(ANCHOR, "\n\n\n" + BLOCK.strip("\n") + ANCHOR, 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t11.py"`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [x] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `129 passed`

- [x] **Step 6: 差分の健全性**

Run: `git diff --stat`
Expected: `katrain/core/ai.py | 64 +++…`（削除 0 行）

- [x] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 13路・19路版 Veil13Strategy / Veil19Strategy

属性（盤サイズ・設定キー接頭辞・既定値・VEIL_BOARD）だけの差し替え。19路は安い順の検証を 1 手に絞る。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: GUI・設定・i18n・デバッグ CLI への登録

**Files:**
- Modify: `katrain/core/constants.py`（`AI_STRATEGIES_ENGINE`・`AI_STRATEGIES_RECOMMENDED_ORDER`（擬態の直後）・`AI_STRENGTH`（nan）・`_VEIL_*` 候補値・`AI_OPTION_VALUES` / `AI_OPTION_ORDER` に 16 キー × 3 盤）
- Modify: `katrain_debug/runner.py`（`STRATEGY_NAME_MAP` に veil9 / veil13 / veil19）
- Modify: `katrain/config.json`（`"ai:scoreloss"` の直前に3ブロック）
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` / `en/LC_MESSAGES/katrain.po` → `python tools/compile_mo.py`
- Modify: `katrain/gui/ai_help.py`（共通文面 `aiopt:veil*_<suffix>`）
- Modify: `tests/test_ai_help_text.py`（veil の `{p}` 置換テスト・兄弟キー参照の正規表現）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: `Veil9/13/19Strategy.SETTING_DEFAULTS`（Task 9a・11）・`AI_VEIL_*`
- Produces: GUI の戦略一覧に「韜晦（9路）／（13路）／（19路）」、AI 設定画面の 16 スライダー（説明欄の【各項目】は `aiopt:veil*_<suffix>` から自動で並ぶ）、`python -m katrain_debug --strategy veil9|veil13|veil19`、ハーネスのアーム指定 `veil13[:key=val,...]`。表示順は `SETTING_DEFAULTS` の並び（target_rate 0 〜 trap_min_delta_e 15）。

- [x] **Step 1: 失敗するテストを書く** — `tests/test_ai_veil.py` の先頭の import 群（`import json` 〜 `import katrain.core.ai as ai_module`）を次に置き換え（Edit）

```python
import json
import random
import re
import types
from pathlib import Path

import pytest

import katrain
import katrain.core.ai as ai_module
```

ファイル末尾に追記:

```python
class TestRegistration:
    """戦略リスト・AI_OPTION_VALUES / AI_OPTION_ORDER・パッケージ config.json・i18n・デバッグ CLI の整合。"""

    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_listed_everywhere(self, cls, size, prefix, ai_key, const):
        from katrain.core.constants import (
            AI_STRATEGIES,
            AI_STRATEGIES_ENGINE,
            AI_STRATEGIES_RECOMMENDED_ORDER,
            AI_STRENGTH,
        )

        assert const in AI_STRATEGIES_ENGINE and const in AI_STRATEGIES
        assert const in AI_STRATEGIES_RECOMMENDED_ORDER and const in AI_STRENGTH

    def test_recommended_order_puts_the_family_right_after_mimic(self):
        from katrain.core.constants import AI_MIMIC_13, AI_STRATEGIES_RECOMMENDED_ORDER

        i = AI_STRATEGIES_RECOMMENDED_ORDER.index(AI_MIMIC_13)
        assert AI_STRATEGIES_RECOMMENDED_ORDER[i + 1 : i + 4] == [AI_VEIL_9, AI_VEIL_13, AI_VEIL_19]

    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_defaults_in_gui_options_and_package_config(self, cls, size, prefix, ai_key, const):
        from katrain.core.constants import AI_OPTION_ORDER, AI_OPTION_VALUES

        with open(Path(katrain.__file__).parent / "config.json", encoding="utf-8") as f:
            package_ai_conf = json.load(f)["ai"][ai_key]
        assert set(package_ai_conf) == {f"{prefix}_{suffix}" for suffix in cls.SETTING_DEFAULTS}
        for order, (suffix, default) in enumerate(cls.SETTING_DEFAULTS.items()):
            key = f"{prefix}_{suffix}"
            assert package_ai_conf[key] == default, key
            assert AI_OPTION_ORDER[key] == order, key  # SETTING_DEFAULTS の並び＝画面の並び
            if AI_OPTION_VALUES[key] == "bool":
                assert isinstance(default, bool), key
                continue
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]
            assert default in plain, key

    @pytest.mark.parametrize("size", [9, 13, 19])
    def test_target_rate_range_and_off_values(self, size):
        from katrain.core.constants import AI_OPTION_VALUES

        rates = [v for v, _label in AI_OPTION_VALUES[f"veil{size}_target_rate"]]
        assert min(rates) == pytest.approx(0.15) and max(rates) == pytest.approx(0.50)
        assert (0.0, "OFF") in AI_OPTION_VALUES[f"veil{size}_close_drift_cap"]
        assert (1.01, "OFF") in AI_OPTION_VALUES[f"veil{size}_dominant_hp"]

    def test_attack_preset_is_selectable_on_13x13(self):
        from katrain.core.constants import AI_OPTION_VALUES

        preset = {"reserve": 3.0, "min_winrate": 0.75, "max_loss": 6.0, "spend_rate": 1.0}
        preset.update({"dominant_max_loss": 3.0, "yose_max_loss": 2.0})
        for suffix, value in preset.items():
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[f"veil13_{suffix}"]]
            assert value in plain, suffix

    def test_debug_cli_names(self):
        from katrain_debug.runner import STRATEGY_NAME_MAP

        for cls, size, prefix, ai_key, const in VEILS:
            assert STRATEGY_NAME_MAP[prefix] == const

    @pytest.mark.parametrize("lang", ["jp", "en"])
    def test_i18n_has_names_and_overviews(self, lang):
        po = (Path(katrain.__file__).parent / "i18n" / "locales" / lang / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        for cls, size, prefix, ai_key, const in VEILS:
            assert f'msgid "{ai_key}"' in po and f'msgid "aihelp:{prefix}"' in po, (lang, prefix)

    def test_jp_explains_every_slider_once_for_the_family(self):
        po = (Path(katrain.__file__).parent / "i18n" / "locales" / "jp" / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        for suffix in Veil9Strategy.SETTING_DEFAULTS:
            assert po.count(f'msgid "aiopt:veil*_{suffix}"') == 1, suffix

    def test_en_overview_has_one_bullet_per_slider(self):
        po = (Path(katrain.__file__).parent / "i18n" / "locales" / "en" / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        for cls, size, prefix, ai_key, const in VEILS:
            m = re.search(rf'msgid "aihelp:{prefix}"\s*\nmsgstr "(.*)"', po)
            assert m, prefix
            bullets = [line for line in m.group(1).split("\\n") if line.startswith("* ")]
            assert len(bullets) == len(cls.SETTING_DEFAULTS), prefix
```

- [x] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `16 failed, 129 passed`（`AI_VEIL_9 not in AI_STRATEGIES_ENGINE`・`KeyError: 'ai:veil9'`・`KeyError: 'veil9'` 等）

- [x] **Step 3: constants.py・runner.py・パッケージ config のパッチスクリプトを Write** — `<scratchpad>/patch_veil_t12.py`（`AI_OPTION_VALUES` / `AI_OPTION_ORDER` の 48 行はループで生成する）

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

# 表示順（AI_OPTION_ORDER の 0〜15）と候補値の参照先。max_loss だけ盤サイズ別
SUFFIXES = [
    ("target_rate", "_VEIL_TARGET_RATE"),
    ("reserve", "_VEIL_RESERVE"),
    ("min_winrate", "_VEIL_MIN_WINRATE"),
    ("free_loss", "_VEIL_FREE_LOSS"),
    ("free_wr_drop", "_VEIL_FREE_WR_DROP"),
    ("close_drift_cap", "_VEIL_CLOSE_DRIFT_CAP"),
    ("spend_rate", "_VEIL_SPEND_RATE"),
    ("max_loss", "_VEIL_MAX_LOSS[{size}]"),
    ("yose_max_loss", "_VEIL_YOSE_MAX_LOSS"),
    ("dominant_hp", "_VEIL_DOMINANT_HP"),
    ("dominant_max_loss", "_VEIL_DOMINANT_MAX_LOSS"),
    ("min_human_policy", "_VEIL_MIN_HUMAN_POLICY"),
    ("natural_ratio", "_VEIL_NATURAL_RATIO"),
    ("cost_slack", "_VEIL_COST_SLACK"),
    ("trap_mode", '"bool"'),
    ("trap_min_delta_e", "_VEIL_TRAP_MIN_DELTA_E"),
]

VALUE_LISTS = '''
# 韜晦（veil*_・spec 2026-09-23-veil-strategy-design.md）の候補値。支払い上限だけ盤サイズ別、他は3盤共通。
# 目標一致率は 15〜50%（15% 未満へは払わない設計）。勝ちの安全条件（reserve・min_winrate）の既定は
# 9/13/19路 3/5/7 目・85%。「攻め」プリセット（測定専用: reserve 3・min_winrate 75%・max_loss 6・
# spend_rate 1.0・dominant_max_loss 3・yose_max_loss 2）も候補値に含める
_VEIL_TARGET_RATE = [(0.15, "15%"), (0.2, "20%"), (0.25, "25%"), (0.3, "30%"), (0.35, "35%"), (0.4, "40%"), (0.45, "45%"), (0.5, "50%")]
_VEIL_RESERVE = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]
_VEIL_MIN_WINRATE = [(0.5, "50%"), (0.6, "60%"), (0.7, "70%"), (0.75, "75%"), (0.8, "80%"), (0.85, "85%"), (0.9, "90%"), (0.95, "95%")]
_VEIL_FREE_LOSS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
_VEIL_FREE_WR_DROP = [(0.0, "0%"), (0.01, "1%"), (0.02, "2%"), (0.03, "3%"), (0.05, "5%")]
_VEIL_CLOSE_DRIFT_CAP = [(0.0, "OFF"), (0.5, "0.5"), (1.0, "1.0"), (1.5, "1.5"), (2.0, "2.0"), (3.0, "3.0")]
_VEIL_SPEND_RATE = [0.25, 0.5, 0.75, 1.0]
_VEIL_MAX_LOSS = {
    9: [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
    13: [2.0, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0],
    19: [3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
}
_VEIL_YOSE_MAX_LOSS = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
_VEIL_DOMINANT_HP = [(0.6, "60%"), (0.7, "70%"), (0.8, "80%"), (0.9, "90%"), (0.95, "95%"), (1.01, "OFF")]
_VEIL_DOMINANT_MAX_LOSS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
_VEIL_MIN_HUMAN_POLICY = [(0.01, "1%"), (0.02, "2%"), (0.03, "3%"), (0.05, "5%"), (0.1, "10%")]
_VEIL_NATURAL_RATIO = [0.1, 0.2, 0.3, 0.5]
_VEIL_COST_SLACK = [0.0, 0.2, 0.3, 0.5, 1.0]
_VEIL_TRAP_MIN_DELTA_E = [0.3, 0.5, 0.7, 1.0, 1.5]

AI_OPTION_VALUES = {
'''

option_values = ["    # ===== Veil9/13/19Strategy（韜晦）spec 2026-09-23-veil-strategy-design.md =====\n"]
option_order = []
for size in (9, 13, 19):
    for order, (suffix, ref) in enumerate(SUFFIXES):
        option_values.append(f'    "veil{size}_{suffix}": {ref.format(size=size)},\n')
        option_order.append(f'    "veil{size}_{suffix}": {order},\n')

patch(
    "katrain/core/constants.py",
    [
        (
            "AI_ENIGMA_19, AI_ENIGMA_19_PLUS, AI_MIMIC_13, AI_ANTIMIRROR]",
            "AI_ENIGMA_19, AI_ENIGMA_19_PLUS, AI_MIMIC_13, AI_VEIL_9, AI_VEIL_13, AI_VEIL_19, AI_ANTIMIRROR]",
            1,
        ),
        (
            "    AI_MIMIC_13,\n    AI_ANTIMIRROR,\n",
            "    AI_MIMIC_13,\n    AI_VEIL_9,\n    AI_VEIL_13,\n    AI_VEIL_19,\n    AI_ANTIMIRROR,\n",
            1,
        ),
        (
            '    AI_MIMIC_13: float("nan"),\n',
            '    AI_MIMIC_13: float("nan"),\n    AI_VEIL_9: float("nan"),\n'
            '    AI_VEIL_13: float("nan"),\n    AI_VEIL_19: float("nan"),\n',
            1,
        ),
        ("\nAI_OPTION_VALUES = {\n", VALUE_LISTS, 1),
        (
            '    "mimic13_unsettled_max": [8, 12, 16, 20, 24],\n',
            '    "mimic13_unsettled_max": [8, 12, 16, 20, 24],\n' + "".join(option_values),
            1,
        ),
        ('    "mimic13_unsettled_max": 12,\n}\n', '    "mimic13_unsettled_max": 12,\n' + "".join(option_order) + "}\n", 1),
    ],
)

patch(
    "katrain_debug/runner.py",
    [
        (
            "    AI_ENIGMA_9_PLUS, AI_ENIGMA_19_PLUS, AI_MIMIC_13,\n)",
            "    AI_ENIGMA_9_PLUS, AI_ENIGMA_19_PLUS, AI_MIMIC_13, AI_VEIL_9, AI_VEIL_13, AI_VEIL_19,\n)",
            1,
        ),
        (
            '    "mimic13": AI_MIMIC_13,\n}',
            '    "mimic13": AI_MIMIC_13,\n    "veil9": AI_VEIL_9,\n    "veil13": AI_VEIL_13,\n    "veil19": AI_VEIL_19,\n}',
            1,
        ),
    ],
)

CONFIG_BLOCKS = '''        "ai:veil9": {
            "veil9_target_rate": 0.4,
            "veil9_reserve": 3.0,
            "veil9_min_winrate": 0.85,
            "veil9_free_loss": 0.2,
            "veil9_free_wr_drop": 0.03,
            "veil9_close_drift_cap": 0.0,
            "veil9_spend_rate": 0.5,
            "veil9_max_loss": 3.0,
            "veil9_yose_max_loss": 1.0,
            "veil9_dominant_hp": 0.8,
            "veil9_dominant_max_loss": 1.5,
            "veil9_min_human_policy": 0.05,
            "veil9_natural_ratio": 0.2,
            "veil9_cost_slack": 0.3,
            "veil9_trap_mode": false,
            "veil9_trap_min_delta_e": 0.5
        },
        "ai:veil13": {
            "veil13_target_rate": 0.3,
            "veil13_reserve": 5.0,
            "veil13_min_winrate": 0.85,
            "veil13_free_loss": 0.3,
            "veil13_free_wr_drop": 0.03,
            "veil13_close_drift_cap": 0.0,
            "veil13_spend_rate": 0.5,
            "veil13_max_loss": 4.5,
            "veil13_yose_max_loss": 1.5,
            "veil13_dominant_hp": 0.8,
            "veil13_dominant_max_loss": 2.0,
            "veil13_min_human_policy": 0.05,
            "veil13_natural_ratio": 0.2,
            "veil13_cost_slack": 0.3,
            "veil13_trap_mode": false,
            "veil13_trap_min_delta_e": 0.5
        },
        "ai:veil19": {
            "veil19_target_rate": 0.3,
            "veil19_reserve": 7.0,
            "veil19_min_winrate": 0.85,
            "veil19_free_loss": 0.3,
            "veil19_free_wr_drop": 0.03,
            "veil19_close_drift_cap": 0.0,
            "veil19_spend_rate": 0.5,
            "veil19_max_loss": 6.0,
            "veil19_yose_max_loss": 2.0,
            "veil19_dominant_hp": 0.8,
            "veil19_dominant_max_loss": 3.0,
            "veil19_min_human_policy": 0.05,
            "veil19_natural_ratio": 0.2,
            "veil19_cost_slack": 0.3,
            "veil19_trap_mode": false,
            "veil19_trap_min_delta_e": 0.7
        },
'''
patch("katrain/config.json", [('        "ai:scoreloss": {\n', CONFIG_BLOCKS + '        "ai:scoreloss": {\n', 1)])
```

- [x] **Step 4: パッチを当てる**

Run: `python "$SP/patch_veil_t12.py"`
Expected:
```
patched katrain/core/constants.py (CRLF, 6 edit(s))
patched katrain_debug/runner.py (CRLF, 2 edit(s))
patched katrain/config.json (CRLF, 1 edit(s))
```
Run: `python -c "import json;json.load(open('katrain/config.json',encoding='utf-8'));print('ok')"`
Expected: `ok`

- [x] **Step 5: i18n のパッチスクリプトを Write** — `<scratchpad>/patch_veil_t12po.py`（jp: 戦略名・概要・16 項目の共通解説 `aiopt:veil*_<suffix>`（1 行目＝日本語名・2 行目以降＝解説・`{p}` は接頭辞に置き換わる）。en: 戦略名・概要（16 スライダーの `* ` 行つき。en には aiopt の訳文が無いので概要に書く））

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

BOARDS = [(9, "veil9", "既定値は未校正（設計時の初期値のまま。自己対局での校正は 13路だけ）。"), (13, "veil13", ""), (19, "veil19", "既定値は未校正（設計時の初期値のまま。自己対局での校正は 13路だけ）。1手の解析が重いので着手が遅ければ 13路より長く待ちます。")]

# 概要（aihelp）。各項目の解説は aiopt:veil*_<suffix>（下）から説明欄に自動で並ぶので、ここには書かない
JP_OVERVIEW = (
    "{size}路盤専用。勝ちを最優先にしたまま、評価レポートの「AI の最善手との一致率」（自分）を目標（{prefix}_target_rate）"
    "まで下げます。ほぼ損失ゼロの外し（同値外し）は一致率に関係なく常に打ち、損をする外しは一致率が目標を超えている"
    "間だけ、リードの余剰（リード − {prefix}_reserve）から払います。外す先は 9段が実際に打ちそうな手（humanPolicy が床以上）"
    "に限り、候補はすべて着手後の局面まで読んで損失と勝率を確かめ、最も安い帯の中で最も人間らしい手を選びます。"
    "9段の第一感が最善手に集中している局面（明らかな一手）は、一致率が目標を超えているときだけ小さな損失で外します。"
    "外した後もリードと勝率が安全条件（{prefix}_reserve・{prefix}_min_winrate）を割らないことを毎手確かめ、満たす手が"
    "無ければ最善手を打ちます。ヨセも自分で打ち（委譲しない）、着手後の先読みはしません。罠（相手の期待損失を増やす手）は"
    "{prefix}_trap_mode で足せます（測定用・既定 OFF）。{note}{size}路以外の盤では常に最善手を打ちます。"
    "humanSL モデル（一般・エンジン設定の human-like model）が必要です。"
)

EN_OVERVIEW = (
    "{size}x{size} only. Wins first and, within that, lowers its own AI-best-move match rate (the game report value) "
    "toward an absolute target. Near-free deviations are always played; deviations that cost points are paid for from the "
    "surplus lead (lead minus the reserve) only while the match rate is above the target. Every deviation is a "
    "human-looking move (9d humanPolicy above a floor), is verified by reading the position after it, and must keep the "
    "reserve and the winrate floor; otherwise the best move is played. It plays its own endgame and does not ponder. "
    "Requires the humanSL model. On other board sizes it always plays the best move."
    "\\n\\n[What each slider does] (top to bottom)"
    "\\n* Target match rate: paid deviations and deviations from an obvious move are allowed only while the match rate "
    "(counting this move as a match) is above this; fully open 10 points above it. It never pays to go below 15%. "
    "Higher: fewer deviations, safer wins. Lower: more deviations, more of the lead is spent."
    "\\n* Lead to keep: paid deviations and traps must leave at least this lead (a safety condition). Higher: safer, "
    "fewer deviations. Lower: more deviations, closer games."
    "\\n* Winrate floor after the move: paid deviations and traps are not played if the winrate after the move (with the "
    "best reply) falls below this (a safety condition)."
    "\\n* Free loss: deviations costing at most this many points are played whatever the match rate (0.1 when behind or "
    "below 15%). Higher: more deviations, but small losses add up."
    "\\n* Free winrate drop: a near-free deviation may lower the winrate by at most this much (waived at 97% or more). "
    "Higher: more deviations in close games."
    "\\n* Close-game drift cap: the total verified loss of near-free deviations while the game is close, per game. "
    "OFF = no cap (the per-move winrate rule still applies)."
    "\\n* Share of surplus per move: one paid deviation may cost up to surplus times this (capped by the max loss). "
    "Higher: expensive deviations even with a small lead."
    "\\n* Max loss per move: the ceiling of one paid deviation before the endgame; also the hard cap for traps. Higher: "
    "more deviations when far ahead, but the slack is easier to see."
    "\\n* Max loss per move in the endgame: the same ceiling once the endgame starts (0 = near-free only)."
    "\\n* Obvious-move threshold: when a 9d picks the best move with at least this probability, it deviates only while "
    "above the target. OFF disables it."
    "\\n* Max loss for an obvious move: the ceiling in those positions (it only narrows the normal ceiling)."
    "\\n* Min humanPolicy: a deviation needs at least this 9d probability. Lower: more deviations, rarer moves."
    "\\n* Natural ratio: a deviation also needs this share of the 9d first choice (not used for obvious moves)."
    "\\n* Cost tie band: candidates within this many points of the cheapest count as equally cheap and the most "
    "human-looking one is played. 0 = always the cheapest."
    "\\n* Trap layer: ON also allows traps (moves that raise the opponent's expected loss E by at least the trap "
    "threshold), priced at the verified loss minus half the extra E with unchanged safety limits; a trap replaces a "
    "plain deviation only when it is 0.3 points cheaper. For A/B measurement, off by default."
    "\\n* Trap threshold: the extra E (points) a move needs to count as a trap."
)

AIOPT = r'''msgid "aiopt:veil*_target_rate"
msgstr ""
"目標一致率\n"
"評価レポートの「AI の最善手との一致率」（自分）の目標です。この手も一致させた場合の一致率がこれを超えている間だけ、損をする外しと「明らかな一手」の外しを許します（超過 10pt で全開）。ほぼ損失ゼロの外しは目標と関係なく常に行います。15% 以下へは下げにいきません。上げると外しが減って勝ちは堅くなり、下げると外しが増えるぶんリードを払います。"

msgid "aiopt:veil*_reserve"
msgstr ""
"確保するリード（目）\n"
"損をする外しや罠を打った後にも必ず残すリードで、余剰（リード − この値）だけを外しの代金に使います。勝ちの安全条件です。上げると勝ちは堅いが外せる手番が減り、下げると外しが増えますが僅差の決着が増えます。"

msgid "aiopt:veil*_min_winrate"
msgstr ""
"着手後の勝率フロア\n"
"損をする外しと罠は、外した後の勝率（相手の最善応手込み）がこれを割るなら打ちません。勝ちの安全条件です。上げると安全ですが外しが減り、下げると不利寄りの局面でも払って外します。"

msgid "aiopt:veil*_free_loss"
msgstr ""
"同値外しの閾値（目）\n"
"損失がこの値以下の外し（同値外し）は、一致率に関係なく常に行います（十分に読まれた候補は生の損失も見ます）。1 目以上負けているときや一致率が 15% 以下のときは 0.1 目に下げます。上げると外しが増えますが小さな損が積み重なり、下げると序盤・接戦の外しが減ります。"

msgid "aiopt:veil*_free_wr_drop"
msgstr ""
"同値外しで許す勝率低下\n"
"同値外しでも、1 手で勝率がこの値より下がる手は打ちません（勝率 97% 以上の決着局面は免除）。互角付近では 3% がおよそ 0.16 目に当たります。上げると接戦でも外しが増え、下げると接戦の外しが減ります。"

msgid "aiopt:veil*_close_drift_cap"
msgstr ""
"接戦中の同値外しの累計上限（目）\n"
"接戦（リードが {p}_reserve 未満、または最善手の着手後勝率が 90% 未満）で打った同値外しの損失の、1 局あたりの合計の上限です。OFF で上限なし（1 手ごとの勝率条件だけで守ります）。値を入れると、合計がそれを超える同値外しは打ちません。"

msgid "aiopt:veil*_spend_rate"
msgstr ""
"1回に使う余剰の割合\n"
"損をする外し 1 回に使えるのは、余剰（リード − {p}_reserve）× この割合までです（天井はヨセ前 {p}_max_loss・ヨセ {p}_yose_max_loss）。上げると少ないリードでも高い外しを買い、下げると大きくリードするまで安い外しだけになります。"

msgid "aiopt:veil*_max_loss"
msgstr ""
"1手の支払い上限（目・ヨセ前）\n"
"ヨセ前に損をする外し 1 回で払ってよい目数の天井です。罠の損失の上限も兼ねます。上げると大差のときに外せる手番が増えますが、はっきりした緩みに見えやすくなります。"

msgid "aiopt:veil*_yose_max_loss"
msgstr ""
"1手の支払い上限（目・ヨセ）\n"
"ヨセに入った後（手数と未確定点で判定・一度入ったら固定）の支払いの天井です（罠も同じ）。0 で同値外しだけ。上げるとヨセでも外せますが、ヨセの緩みは目立ちやすくなります。"

msgid "aiopt:veil*_dominant_hp"
msgstr ""
"明らかな一手の閾値\n"
"9段が最善手を選ぶ確率（humanPolicy）がこれ以上の局面を「明らかな一手」として、一致率が目標を超えているときだけ外します（目標以下なら最善手）。OFF で判定しません。下げるとより多くの局面を明らかと見なして慎重になり、上げると明らかな局面でも外しやすくなります。"

msgid "aiopt:veil*_dominant_max_loss"
msgstr ""
"明らかな一手で許す損失（目）\n"
"明らかな一手の局面で外すときの支払いの上限です（通常の上限を絞るだけで広げません）。上げると明らかな局面でも高い外しを打ち、下げるとほぼ同値の外しだけになります。"

msgid "aiopt:veil*_min_human_policy"
msgstr ""
"自然さの絶対床\n"
"外す先は、9段がその手を選ぶ確率（humanPolicy）がこの値以上の手に限ります。下げると外せる手番が増えますが珍しい手が混ざり、上げるとはっきり人間らしい手だけになります。"

msgid "aiopt:veil*_natural_ratio"
msgstr ""
"自然さの相対床（第一感比）\n"
"外す先の humanPolicy は、9段の第一感トップのこの割合以上も必要です（{p}_min_human_policy と厳しいほうが効き、明らかな一手の局面では使いません）。上げると第一感に近い有力手だけになり、下げると 2 番手・3 番手へも外します。"

msgid "aiopt:veil*_cost_slack"
msgstr ""
"最安帯の幅（目）\n"
"候補のうち最も安い外しからこの目数以内を同じくらい安いとみなし、その中で最も人間らしい（humanPolicy 最大の）手を打ちます。上げると人間らしさ優先で少し多く払い、0 で常に最安です。"

msgid "aiopt:veil*_trap_mode"
msgstr ""
"罠の上乗せ層\n"
"ON で、相手の期待損失 E を最善手より {p}_trap_min_delta_e 以上増やす罠も外し先に加えます（人間らしさの床は免除・humanPolicy 2% 以上）。罠の値段は損失から E の上積みの半分を割り引いたもので、安全条件（損失の上限・{p}_reserve・{p}_min_winrate）は割り引きません。素直な外しより 0.3 目以上安いときだけ罠に替えます。A/B 測定用で既定は OFF。"

msgid "aiopt:veil*_trap_min_delta_e"
msgstr ""
"罠とみなす E の上積み（目）\n"
"{p}_trap_mode が ON のとき、E（相手が 9段の直感どおりに応じたときの期待損失）が最善手よりこの値以上大きい手を罠とみなします。下げると罠が増えますが E の誤差を拾いやすく、上げるとはっきり大きい罠だけになります。"

'''

jp_names = ""
en_names = ""
for size, prefix, note in BOARDS:
    jp_names += f'msgid "ai:{prefix}"\nmsgstr "韜晦（{size}路）"\n\n'
    jp_names += f'msgid "aihelp:{prefix}"\nmsgstr "{JP_OVERVIEW.format(size=size, prefix=prefix, note=note)}"\n\n'
    en_names += f'msgid "ai:{prefix}"\nmsgstr "Veil ({size}x{size})"\n\n'
    en_names += f'msgid "aihelp:{prefix}"\nmsgstr "{EN_OVERVIEW.format(size=size)}"\n\n'

patch(
    "katrain/i18n/locales/jp/LC_MESSAGES/katrain.po",
    [
        ('msgid "ai:enigma19"\n', jp_names + 'msgid "ai:enigma19"\n', 1),
        ('msgid "aiopt:ai:tsumego/min_visits"\n', AIOPT + 'msgid "aiopt:ai:tsumego/min_visits"\n', 1),
    ],
)
patch("katrain/i18n/locales/en/LC_MESSAGES/katrain.po", [('msgid "ai:enigma19"\n', en_names + 'msgid "ai:enigma19"\n', 1)])
```

- [x] **Step 6: i18n を当ててコンパイル**

Run: `python "$SP/patch_veil_t12po.py"`
Expected:
```
patched katrain/i18n/locales/jp/LC_MESSAGES/katrain.po (CRLF, 2 edit(s))
patched katrain/i18n/locales/en/LC_MESSAGES/katrain.po (CRLF, 1 edit(s))
```
Run: `python tools/compile_mo.py`
Expected: `OK: …en…katrain.mo (N entries)` と `OK: …jp…katrain.mo (M entries)`（エラーなし）

- [x] **Step 7: 韜晦のテストが通ることを確認**

Run: `pytest tests/test_ai_veil.py -q`
Expected: `145 passed`

- [x] **Step 8: 説明欄の失敗を確認**（共通文面の検索がまだ enigma だけ）

Run: `pytest tests/test_ai_help_text.py -q`
Expected: `3 failed`（`TestJapaneseCoverage::test_every_setting_has_a_japanese_name_and_explanation[ai:veil9]` / `[ai:veil13]` / `[ai:veil19]`）

- [x] **Step 9: `tests/test_ai_help_text.py` にテストを足す**（Edit ツール・LF・black 整形済み）

(a) `test_board_specific_entry_beats_the_family_text` の後ろ＝`test_missing_translation_returns_none` の前に追加。old:

```python
    def test_missing_translation_returns_none(self):
```
new:
```python
    def test_veil_family_text_gets_the_real_key_prefix(self):
        t = _translator({"aiopt:veil*_spend_rate": "1回に使う余剰の割合\n天井は {p}_max_loss"})
        assert ai_help.ai_option_help_entry("ai:veil13", "veil13_spend_rate", t) == (
            "1回に使う余剰の割合",
            "天井は veil13_max_loss",
        )
        assert ai_help.ai_option_help_entry("ai:veil9", "veil9_spend_rate", t)[1] == "天井は veil9_max_loss"
        assert ai_help.ai_option_help_entry("ai:enigma13", "enigma13_spend_rate", t) is None

    def test_missing_translation_returns_none(self):
```

(b) `TestJapaneseCoverage.test_referenced_sibling_keys_exist_in_the_same_strategy` の正規表現に veil を足す。old:

```python
        ref_pattern = re.compile(r"\b(?:enigma(?:9|13|19)(?:plus)?|mimic13|parity9|jigo9)_[a-z0-9_]*[a-z0-9]")
```
new:
```python
        ref_pattern = re.compile(
            r"\b(?:enigma(?:9|13|19)(?:plus)?|mimic13|parity9|jigo9|veil(?:9|13|19))_[a-z0-9_]*[a-z0-9]"
        )
```

Run: `pytest tests/test_ai_help_text.py -q`
Expected: `4 failed`（上の3件と `test_veil_family_text_gets_the_real_key_prefix`）

- [x] **Step 10: `katrain/gui/ai_help.py` を直す**（Edit ツール・LF・black 整形済み）

(a) モジュール docstring。old:
```
難解系の共通文面 `aiopt:enigma*_<suffix>`。難解系（enigma9/13/19 と＋版）は同じ項目がキー接頭辞
違いで 6 つずつ並ぶので、共通文面の `{p}` を実際の接頭辞（例 enigma13plus）へ置き換えて 1 本で書く。
```
new:
```
難解系・韜晦系の共通文面 `aiopt:enigma*_<suffix>` / `aiopt:veil*_<suffix>`。難解系（enigma9/13/19 と＋版）は
同じ項目がキー接頭辞違いで 6 つずつ、韜晦系（veil9/13/19）は 3 つずつ並ぶので、共通文面の `{p}` を実際の
接頭辞（例 enigma13plus / veil13）へ置き換えて 1 本で書く。
```

(b) 正規表現。old:
```python
_ENIGMA_FAMILY = re.compile(r"^(enigma(?:9|13|19)(?:plus)?)_(.+)$")
```
new:
```python
_ENIGMA_FAMILY = re.compile(r"^(enigma(?:9|13|19)(?:plus)?)_(.+)$")
_VEIL_FAMILY = re.compile(r"^(veil(?:9|13|19))_(.+)$")
# （キーの正規表現, 共通文面の msgid 接頭辞）。共通文面の {p} は一致したキー接頭辞（例 enigma13plus / veil13）になる
_FAMILIES = ((_ENIGMA_FAMILY, "enigma*"), (_VEIL_FAMILY, "veil*"))
```

(c) `ai_option_help_entry` の先頭。old:
```python
    candidates = [f"aiopt:{strategy}/{key}", f"aiopt:{key}"]
    family = _ENIGMA_FAMILY.match(key)
    if family:
        candidates.append(f"aiopt:enigma*_{family.group(2)}")
```
new:
```python
    candidates = [f"aiopt:{strategy}/{key}", f"aiopt:{key}"]
    family = None
    for pattern, wildcard in _FAMILIES:
        family = pattern.match(key)
        if family:
            candidates.append(f"aiopt:{wildcard}_{family.group(2)}")
            break
```

- [x] **Step 11: 登録まわりのテストを通す**

Run: `pytest tests/test_ai_veil.py tests/test_ai_help_text.py tests/test_ai_options_grid.py tests/test_ai_mimic13.py tests/test_ai_enigma_plus.py tests/test_ai_enigma9.py tests/test_debug_runner.py::TestStrategyNameMapping tests/test_ai.py::TestAI::test_order -q`
Expected: 全 PASS（`test_ai_options_grid.py` は `test_collapsable_panel.py` と順序依存のフレークがある＝単体で落ちたら単体再実行で切り分ける）
Run: `python -m black --check katrain/gui/ai_help.py tests/test_ai_help_text.py tests/test_ai_veil.py`
Expected: `3 files would be left unchanged.`

- [x] **Step 12: 差分の健全性**

Run: `git diff --stat`
Expected（行数の目安）: `katrain/config.json | 54 +`・`katrain/core/constants.py | 129 +…-`（削除 1 行＝`AI_STRATEGIES_ENGINE` の行の置き換え）・`katrain_debug/runner.py | 5 +-`（削除 1 行）・`katrain/i18n/locales/jp/…/katrain.po | 98 +`・`en/…/katrain.po | 18 +`・`.mo` 2 本（Bin）・`katrain/gui/ai_help.py`（+12 −5）・`tests/test_ai_help_text.py`（+12 −1）・`tests/test_ai_veil.py`

- [x] **Step 13: コミット**

```bash
git add katrain/core/constants.py katrain/config.json katrain_debug/runner.py katrain/i18n katrain/gui/ai_help.py tests/test_ai_help_text.py tests/test_ai_veil.py
git commit -m "feat(veil): 韜晦（9/13/19路）を GUI・設定・i18n・デバッグ CLI に登録

戦略リスト（擬態の直後）・AI_STRENGTH・16 スライダー × 3 盤（目標一致率 15〜50%・攻めプリセットも選べる候補値）・
パッケージ config・jp の共通解説 aiopt:veil*_<suffix>（説明欄は {p} を接頭辞に置換）・en の概要・runner の名前。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: ユーザーローカル設定（**MAIN SESSION ONLY・KaTrain 停止中**）

> **このタスクはサブエージェントに委任しない。メインセッションが自分で行う。** KaTrain が起動していると終了時に設定が上書きされて消える。

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（リポジトリ外・コミットなし）
- Create: `<scratchpad>/patch_user_config_veil.py`

**Interfaces:**
- Consumes: Task 12 のパッケージ `katrain/config.json` の `ai:veil9` / `ai:veil13` / `ai:veil19` ブロック
- Produces: ユーザー設定に同じ3ブロック（GUI は保存済みキーしか表示しない・ハーネスとデバッグ CLI はユーザー設定を読む）

- [x] **Step 1: KaTrain が起動していないことを確かめる**（ウィンドウ名の前方一致で判定。ソースから起動した版も別にインストールした版も、同じ `~/.katrain` を使い、ウィンドウ名は `KaTrain v<版>`）

Run: `powershell -NoProfile -Command 'if (Get-Process | Where-Object { $_.MainWindowTitle -clike "KaTrain v*" }) { "running" } else { "not-running" }'`
Expected: `not-running`（`running` ならユーザーに終了を頼み、終わるまで進まない）。`-clike`（大文字小文字を区別）にしてあるのは、`-like` だと VS Code のウィンドウ名 `katrain-1.17.1.1 - Visual Studio Code` まで拾うため。Bash ツールでは全体を単引用符で囲む（二重引用符だと `$_` を bash が展開して壊れる）。PowerShell ツールで実行するなら外側の `powershell -NoProfile -Command '…'` を外して中身だけを渡す。
続けて、**ユーザーに KaTrain を閉じたことをチャットで確かめる**（必須。上の判定はウィンドウを持たない状態の KaTrain を拾えない。返事が来るまで Step 3 を実行しない）。

- [x] **Step 2: スクリプトを Write** — `<scratchpad>/patch_user_config_veil.py`（パッケージの3ブロックをそのまま写す・編集前のコピーをスクラッチパッドに残す）

```python
"""ユーザー設定 ~/.katrain/config.json に ai:veil9 / ai:veil13 / ai:veil19 を足す（メインセッション専用・KaTrain 停止中）。

パッケージ katrain/config.json の3ブロックをそのまま写す（値の食い違いを作らない）。リポジトリのルートで実行する。
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch  # noqa: E402

USER_CONFIG = os.path.expanduser(os.path.join("~", ".katrain", "config.json"))
ANCHOR = '        "ai:scoreloss": {\n'

package = open("katrain/config.json", "rb").read().decode("utf-8").replace("\r\n", "\n")
start = package.index('        "ai:veil9": {\n')
blocks = package[start : package.index(ANCHOR, start)]
assert blocks.count('"ai:veil') == 3, blocks[:200]
user = open(USER_CONFIG, "rb").read().decode("utf-8")
if '"ai:veil' in user:
    sys.exit("user config already has ai:veil* blocks")
shutil.copyfile(USER_CONFIG, os.path.join(os.path.dirname(os.path.abspath(__file__)), "user-config-before-veil.json"))
patch(USER_CONFIG, [(ANCHOR, blocks + ANCHOR, 1)])
```

- [x] **Step 3: 実行**（リポジトリのルートで）

Run: `python "$SP/patch_user_config_veil.py"`
Expected: `patched C:\Users\iwaki\.katrain\config.json (CRLF, 1 edit(s))`

- [x] **Step 4: JSON とキーの検算**

Run: `python -c "import json,os;c=json.load(open(os.path.expanduser('~/.katrain/config.json'),encoding='utf-8'));print({k: len(c['ai'][k]) for k in ('ai:veil9','ai:veil13','ai:veil19')})"`
Expected: `{'ai:veil9': 16, 'ai:veil13': 16, 'ai:veil19': 16}`

（リポジトリ外なのでコミットなし）

---

### Task 14: 実エンジンでの単一局面スモーク（デバッグ CLI）

**Files:** なし（出力はスクラッチパッドに保存するだけ・コミットなし）

**Interfaces:**
- Consumes: Task 12 の `STRATEGY_NAME_MAP["veil13"]`・Task 13 のユーザー設定（無くてもコードの既定値で動く）
- Produces: 実 KataGo での `Rate:` / `Budget:` / `Decision:` 行と所要時間の確認（Task 15 の前提）

`--move N` は「N 手打った後の局面」（runner の `load_sgf_to_move`）。使う SGF は 13路・AI 黒番の実戦 `docs/superpowers/specs/calibration-data/enigma13/enigma13plus-vs-app-20260911-184025-black.sgf`（125 手）なので、黒番＝AI の手番は N が偶数。ハーネス計画で移設した実戦の SGF（`docs/superpowers/specs/calibration-data/selfplay/recon/`）も1本使う。KaTrain・ハーネスと同時に走らせない。

- [x] **Step 1: 序盤・中盤・ヨセの3局面**

Run:
```bash
SP="$(cygpath -m '<スクラッチパッドの Windows パス>')"
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma13/enigma13plus-vs-app-20260911-184025-black.sgf --move 20 --strategy veil13 > "$SP/veil_smoke_20.txt" 2>&1
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma13/enigma13plus-vs-app-20260911-184025-black.sgf --move 40 --strategy veil13 > "$SP/veil_smoke_40.txt" 2>&1
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma13/enigma13plus-vs-app-20260911-184025-black.sgf --move 90 --strategy veil13 > "$SP/veil_smoke_90.txt" 2>&1
```
Expected（各ファイル）: `=== Strategy Debug: Veil13Strategy ===`、Decision Log に `[Veil13Strategy] Rate: mine=…`（履歴の局面は runner が解析しないので、SGF に解析が保存されていなければ `0/0`・`u=1.00`）と `[Veil13Strategy] Decision: {` の行、`[Veil13Strategy] 着手決定に X.X 秒`（13路の目安 0.0〜3 秒）、`ERROR:` の行なし、Result の Move が盤上の手。
`--move 90`（手数は 13路の endgame_move 85 以上）は、runner の通常解析に ownership が入る（ユーザー設定 `engine._enable_ownership: true`）ので、手数に加えて未確定点（|ownership| < 0.5）の数も見る: `[Veil13Strategy] Endgame check: depth=90 thr=85 unsettled=N max=16 -> …` の行が出て、Decision に `"unsettled": N`。N <= 16 なら `-> yose (sticky)`・`"in_yose": true`・`"cap": 1.5`、N > 16 なら `-> not yet`・`"in_yose": false`・`"cap": 4.5`（**どちらも正常**＝N で判別する。デバッグの対象にしない）。ownership が取れていなければ `unsettled=None` で手数だけでヨセ入り（`true`・`1.5`）。S9 より前で終わった手番（相手の直前パス・終局帯・best が pass）は `cap` キーが無くてよい。

- [x] **Step 2: 罠 ON と盤サイズ違い**

Run:
```bash
SP="$(cygpath -m '<スクラッチパッドの Windows パス>')"
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma13/enigma13plus-vs-app-20260911-184025-black.sgf --move 40 --strategy veil13 --settings veil13_trap_mode=true > "$SP/veil_smoke_40_trap.txt" 2>&1
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma13/enigma13plus-vs-app-20260911-184025-black.sgf --move 40 --strategy veil9 > "$SP/veil_smoke_40_veil9.txt" 2>&1
```
Expected: 罠 ON は `Score …` 行に `trap=` の列があり、Decision の `queries` が罠 OFF（Step 1 の @40）以上。`veil9` は `board size (13, 13) is not 9x9` の行と `"why": "board"`、Move は KataGo の最善手。

- [x] **Step 3: 移設した実戦 SGF でも1局面**

Run: `python -c "import glob;print(sorted(glob.glob('docs/superpowers/specs/calibration-data/selfplay/recon/*.sgf'))[:3])"`
先頭の SGF で、AI 側の手番になる N（黒なら偶数・白なら奇数。SGF の PB/PW を見て決める）を1つ選んで実行:
`python -m katrain_debug --sgf <その SGF> --move <N> --strategy veil13 > "$SP/veil_smoke_recon.txt" 2>&1`
Expected: Step 1 と同じ形（エラーなし）。recon が無ければこの Step は飛ばしてよい（Step 1 の SGF も実戦）。

- [x] **Step 4: 異常があれば直す**
  （該当なし: 6 本のスモークで ERROR 行・例外・遅い着手は出なかった）

`ERROR:` 行・例外・3 秒を大きく超える手番があれば superpowers:systematic-debugging で原因を調べ、`tests/test_ai_veil.py` に再現テストを足してから ai.py をパッチスクリプトで直す（Task 1〜10 と同じ手順・同じコミット形式 `fix(veil): …`）。`--move 90` の `in_yose` が false なのは未確定点が多いだけなら異常ではない（Step 1）。

---

### Task 15: 自己対局ハーネスでの校正キャンペーン（段階1・1b・2・3・バックグラウンド）と結果 md

**Files:**
- Create: `docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md`
- Create: `docs/superpowers/specs/calibration-data/selfplay/veil13-campaign/`（各段階の `<label>-run.json` と、比較ごとの `<label>-<A>-vs-<B>-summary.json` / `.txt` の写し。`experiments/` は gitignore 済みなので写して残す）

**Interfaces:**
- Consumes: `python -m katrain_debug.selfplay run / summarize`（ハーネス spec §8）、相手プール `docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json`（ハーネス計画の校正で作成済み）、`last_decision_info`（共有インターフェース節）
- Produces: 境界線（アームごとの自分の一致率 vs 勝ち・損失・外した手の hp）と採否の判定＝Task 16 でユーザーに見せる材料

所要（ハーネス spec §6・13路）: 段階1 約4時間・1b 約5時間（6 アーム）・2 約3時間・3 約2〜3時間。**必ず1本ずつ順に**、`run_in_background: true` で流して完了通知を待つ（並列にしない・KaTrain やデバッグ CLI と同時に走らせない）。途中で落ちたら同じコマンドに `--resume <出力ディレクトリ>` を付けて再開する。

- [x] **Step 0: USER CHECKPOINT（メインセッション）— 走らせてよいか聞く**

ユーザーに次を伝え、開始してよいか・どの時間帯に流すか・段階の間で止めて結果を見るかを聞く。**返事が来るまで Step 2 以降を始めない**（Step 1 の確認だけは先にしてよい）:
- 段階ごとの所要: スモーク 約10分・段階1 約4時間・1b 約5時間・2 約3時間・3 約2〜3時間＝**合計 約14〜15時間**（GPU を使い続ける。1本ずつ順に流す）。
- その間 **KaTrain を起動できない**（同じ `~/.katrain/config.json` と GPU を使う。KaTrain が終了時に設定を上書きする・時間の計測が狂う）。
- 途中で止めても、同じコマンドに `--resume <出力ディレクトリ>` を付ければ続きから再開できる。
段階の間で止めると言われたら、各段階の完了後に Step 7 の集計を見せて、次の段階を始めてよいか聞き直す。

- [x] **Step 1: 前提の確認**

Run:
```bash
powershell -NoProfile -Command 'if (Get-Process | Where-Object { $_.MainWindowTitle -clike "KaTrain v*" }) { "running" } else { "not-running" }'
python -c "import os;print(os.path.exists('docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json'))"
python -c "import json,os;c=json.load(open(os.path.expanduser('~/.katrain/config.json'),encoding='utf-8'));print('ai:veil13' in c['ai'], 'ai:enigma13plus' in c['ai'], c['ai'].get('ai:human'))"
python -m katrain_debug.selfplay run --help
```
Expected: `not-running`（判定の仕方は Task 13 Step 1）・`True`・`True True {…}`、ヘルプに `--arm` `--size` `--pairs` `--opp-pool` `--hp-audit` `--label` `--no-resign` `--komi-shift` `--opponent` `--resume` がある。3行目の最後はユーザー設定の `ai:human`（段階1・3 の HumanStyle は上書きで 9段にするので、ここの段位は何でもよい＝記録用）。相手プールが無ければ**ここで止めてユーザーに報告する**（ハーネス計画の校正が済んでいない。校正は**ハーネス計画の作業なので、この計画では実行しない**。参考までにプールを書き出すコマンドは `python -m katrain_debug.selfplay calibrate --size 13 --strategy enigma13plus --ranks rank_8k,rank_5k,rank_3k,rank_1k,rank_1d,rank_3d --games 8 --write-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json`＝`--write-pool` が無いと何時間走ってもプールは書かれない）。フラグ名がハーネスの実装と違うときは、同じ意味のハーネス側のフラグに読み替え、その対応を結果 md の「実行条件」に書く。

- [x] **Step 2: 1 seed のスモーク**（約 10 分・パイプラインと判定情報の確認）

Run（background）:
```bash
python -m katrain_debug.selfplay run --size 13 --pairs 1 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json --hp-audit rank_9d --label veil13-smoke --arm default=veil13 --arm enigma=enigma13plus
```
Expected: 完了後の `experiments/selfplay/<日時>_veil13-smoke/` に `run.json` / `games.jsonl` / `moves.jsonl` / `summary.txt`。`games.jsonl` の default アームの行の `veil` に `tiers`（i / ii / iii / terminal / failsafe の数）と `kinds`（free / paid / best ほか）が入り（`last_decision_info` の `tier` / `kind` から）、`veil.ledger_mismatch`（外したつもりの手がレポートで一致になった数）が 0。enigma アームの `veil` は null。null ガード・綴りチェックで止まらない。

- [x] **Step 3: 段階1 主比較**（5 アーム × 20 seed・通常の相手プール・投了あり）

Run（background）:
```bash
python -m katrain_debug.selfplay run --size 13 --pairs 20 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json --hp-audit rank_9d --label veil13-p1 --arm default=veil13 --arm trap=veil13:veil13_trap_mode=true --arm attack=veil13:veil13_reserve=3.0,veil13_min_winrate=0.75,veil13_max_loss=6.0,veil13_spend_rate=1.0,veil13_dominant_max_loss=3.0,veil13_yose_max_loss=2.0 --arm enigma=enigma13plus --arm human=human:human_kyu_rank=-8,modern_style=true
```
（`attack` は spec §6.1 の「攻め」プリセット＝測定専用。既定にするには要件1の再決定が要る）

- [ ] **Step 4: 段階1b 安全条件以外のつまみの掃引**（spec §10.3・§12 の dominant_hp / natural_ratio / free_loss と、接戦の累計上限の感度）
  （実施しなかった: ユーザー判断で段階1の後に測定を打ち切った・2026-09-24。段階1b は未実施）

Run（background）:
```bash
python -m katrain_debug.selfplay run --size 13 --pairs 20 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json --hp-audit rank_9d --label veil13-p1b --arm default=veil13 --arm dom090=veil13:veil13_dominant_hp=0.9 --arm domoff=veil13:veil13_dominant_hp=1.01 --arm nat010=veil13:veil13_natural_ratio=0.1 --arm free040=veil13:veil13_free_loss=0.4 --arm drift1=veil13:veil13_close_drift_cap=1.0
```

- [ ] **Step 5: 段階2 投了なし**（投了がヨセの手数＝一致率を左右するための必須の感度アーム）
  （実施しなかった: ユーザー判断で段階1の後に測定を打ち切った・2026-09-24。段階2 は未実施）

Run（background）:
```bash
python -m katrain_debug.selfplay run --size 13 --pairs 20 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json --hp-audit rank_9d --no-resign --label veil13-p2 --arm default=veil13 --arm enigma=enigma13plus
```

- [ ] **Step 6: 段階3 接戦ストレス**（AI 不利に 4 目・強めの相手＝HumanStyle 9段。段階1で trap が default より一致率を 3pt 以上下げ、敗局も増えていなければ `--arm trap=veil13:veil13_trap_mode=true` を足す）
  （実施しなかった: ユーザー判断で段階1の後に測定を打ち切った・2026-09-24。段階3 は未実施＝spec §10.4 (a) 接戦の安全は未評価）

相手の HumanStyle は**必ず上書きで 9段にする**（上書きが無いとハーネスはユーザー設定の `ai:human` をそのまま使う。ユーザー設定は 8級＝`human_kyu_rank: 8`・`modern_style: false` なので、接戦がほとんど生まれず、要件1の採否（spec §10.4 (a)）が意味を失う）。

Run（background）:
```bash
python -m katrain_debug.selfplay run --size 13 --pairs 20 --komi-shift 4 --opponent strategy:human:human_kyu_rank=-8,modern_style=true --hp-audit rank_9d --label veil13-p3 --arm default=veil13 --arm enigma=enigma13plus
```
完了後、出力ディレクトリの `run.json` の `opponent` が `"kind": "strategy"`・`"strategy": "human"`・`"override_items": ["human_kyu_rank=-8", "modern_style=true"]` であることを確かめ（違えば結果を使わずに止める）、結果 md の「実行条件」に写す。

- [x] **Step 7: 集計と写し**（`summarize` は呼ぶたびに `summary.json` / `summary.txt` を**上書きする**＝比較ごとに実行して、その直後に写す）
  （段階1だけ。段階1b・2・3 は実施しなかった）

写し先は `docs/superpowers/specs/calibration-data/selfplay/veil13-campaign/`（以下 `CD`）。ファイル名は `<label>-<A>-vs-<B>-summary.{json,txt}` に固定し、`run.json` は各ディレクトリで1回だけ `<label>-run.json` に写す。例（段階1・`<DIR>` は veil13-p1 の出力ディレクトリ）:
```bash
CD=docs/superpowers/specs/calibration-data/selfplay/veil13-campaign; mkdir -p "$CD"
cp <DIR>/run.json "$CD/veil13-p1-run.json"
python -m katrain_debug.selfplay summarize <DIR> --compare default enigma
cp <DIR>/summary.json "$CD/veil13-p1-default-vs-enigma-summary.json"; cp <DIR>/summary.txt "$CD/veil13-p1-default-vs-enigma-summary.txt"
python -m katrain_debug.selfplay summarize <DIR> --compare default trap
cp <DIR>/summary.json "$CD/veil13-p1-default-vs-trap-summary.json"; cp <DIR>/summary.txt "$CD/veil13-p1-default-vs-trap-summary.txt"
```
比較の一覧（どれも「summarize → すぐ2ファイルを写す」）:
- 段階1（veil13-p1）: `default enigma` / `default trap` / `default attack` / `default human`
- 段階1b（veil13-p1b）: `default dom090` / `default domoff` / `default nat010` / `default free040` / `default drift1`
- 段階2（veil13-p2）: `default enigma`
- 段階3（veil13-p3）: `default enigma`（既定の信頼度 0.975）と、**採否用に `--conf 0.95`**: `python -m katrain_debug.selfplay summarize <DIR> --compare default enigma --conf 0.95` → `veil13-p3-default-vs-enigma-conf95-summary.{json,txt}`（spec §10.4 (a) は flip_moves の対の差の **95%** 上限。`summarize` の既定 0.975 はハーネスの2回見る停止規則用）。段階3に trap アームを足したら `default trap` も同じく2通り。

- [x] **Step 8: 結果 md を書く** — `docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md`（数値はすべて summary から写す。局平均と 95% 区間は summary の局単位クラスタ bootstrap の値）

構成（この見出しと列で書く。括弧内は games.jsonl / summary の元の値＝ハーネス計画 Task 2 の `selfplay_game_summary` のキー）:

1. `# 韜晦（13路）自己対局キャンペーン結果（<実行日>）`
2. `## 実行条件` — git HEAD と dirty（run.json）、ユーザー設定の `ai:veil13` の値、相手プール、各段階の局数と所要、Step 1 のフラグの読み替え、**ハーネスと実戦のずれ**＝enigma アームの自分の一致率（局平均）− 実戦の難解＋ 53.3%（ハーネス spec §3）
3. `## 段階1 主比較` と `## 段階1b つまみの掃引` — 表の列: アーム ｜ 自分の一致率 WATCH 局平均 [95%]（`own_top1`） ｜ 相手の一致率（`opp_top1`） ｜ P(own <= 0.35)（`own_le_target_plus5`） ｜ P(own < 0.15)（`own_lt_floor`） ｜ 勝ち/局数 [Wilson 95%]（`result`） ｜ flip_moves/局（`flip_moves`） ｜ 自分の mean_ptloss（`own_mean_ptloss`） ｜ ≥6目の失着/局（`ai_tail.ge6`） ｜ 外した手の 9段 hp 中央値（`hp_dev_median`・hp 監査） ｜ 戦略時間 p95（`strategy_p95`） ｜ default との差（その比較の `<label>-default-vs-<アーム>-summary.json` の `compare[0].diffs` の対の差と区間。区間の信頼度は `compare[0].conf`＝0.975 と明記）
4. `## 段階2 投了なし` — 同じ列（default と enigma）＋手数の中央値と区間別（<24 / 24〜84 / >=85）の自分の一致率
5. `## 段階3 接戦ストレス` — 表の上に「相手 HumanStyle 9段（`human_kyu_rank=-8`・`modern_style=true`・run.json で確認済み）・区間の信頼度 0.95（spec §10.4）」と書く。列: アーム ｜ 勝ち/局数 ｜ 敗局の SGF（1局ずつ見た所見を1行ずつ） ｜ flip_moves/局 ｜ flip_moves の対の差（veil − enigma）の 95% 上限（`veil13-p3-default-vs-enigma-conf95-summary.json`。0.975 の値を使う場合は「保守側（区間が広い）」と明記） ｜ lead < reserve での同値でない外しの数（`veil.nonfree_below_reserve`。終局帯の `swap` / `finish`＝0.05 目以内の入れ替えも数えるので `veil.kinds` の内訳を添える） ｜ 接戦中の同値外しの vloss 合計/局（`veil.close_free_vloss`）
6. `## 罠 A/B（段階1 trap vs default）` — 自分と相手の一致率・勝率・mean_ptloss・払った vloss の合計（`veil.paid_vloss_sum`）・種類別（`veil.vloss_by_kind`）・罠の次の相手手の実損 / E（`veil.trap_next_loss_over_E`＝`last_decision_info` の `E` を使う。1.06 から大きく外れたら結論を保留と書く）・選んだ手の hp 中央値
7. `## 採否（spec §10.4）` — (a) 勝ちの安全: 段階3の flip の対の差の 95% 上限 <= 0.1/局 かつ 敗局数が enigma より 2 局を超えて多くない → 可／否、(b) 人間らしさ: default の外した手の hp 中央値 >= 5% → 可／否、(c) 一致率: P(own <= 0.35) と P(own < 0.15)（前者が高く後者が低いほど良い）
8. `## 境界線と推奨` — 段階1・1b の各アームを「自分の一致率（横）× 勝ち・flip・hp 中央値」で並べた表と、安全条件（reserve・min_winrate）を変えずに (a)(b) を満たすアームのうち P(own <= 0.35) が最大のものを推奨として1行（attack は「要件1の再決定が要る」と明記して参考に並べる）

- [x] **Step 9: コミット**

```bash
git add docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md docs/superpowers/specs/calibration-data/selfplay/veil13-campaign
git commit -m "docs(veil): 自己対局ハーネスでの 13路校正結果と境界線

段階1（主比較 5 アーム）・1b（安全条件以外のつまみ）・2（投了なし）・3（接戦ストレス）× 20 seed。
採否は spec §10.4（flip の対の差・敗局・外した手の hp・P(own <= T+0.05)）。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: **USER CHECKPOINT** — 境界線を見せて既定値を選んでもらう（メインセッション）

> **サブエージェントに委任しない。メインセッションがユーザーに提示し、返事が来るまで先へ進まない。**

**Files:**
- Create: `<scratchpad>/veil_defaults.json`（変える項目だけ。Task 17 の入力。リポジトリ外）
- Modify: `docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md`（末尾に「ユーザーの決定」の節を足してコミット）

**Interfaces:**
- Consumes: Task 15 の `veil13-campaign.md`（境界線・採否・推奨）
- Produces: `<scratchpad>/veil_defaults.json`（Task 17 の入力）、要件1を再決定したかどうか、進み方（変える＝Task 17・18 へ／据え置き＝Task 18 へ／設計に戻る＝ここで止める）。決定は `veil13-campaign.md` にコミットして残す

- [x] **Step 1: 提示する**

`veil13-campaign.md` の「境界線と推奨」「採否」「罠 A/B」を要約してユーザーに見せる（表はそのまま貼る）。聞くこと:
1. 安全条件以外のつまみ（`target_rate` `free_loss` `free_wr_drop` `close_drift_cap` `spend_rate` `max_loss` `yose_max_loss` `dominant_hp` `dominant_max_loss` `min_human_policy` `natural_ratio` `cost_slack` `trap_mode` `trap_min_delta_e`）の 13路の既定値をどうするか（推奨アームの値・現状維持・個別指定）。値はスライダーの候補値から選ぶ（`katrain/core/constants.py` の `_VEIL_*`）。
2. 9路・19路も同じ向きに動かすか（未校正のまま据え置くのが基本）。
3. 安全条件（`reserve` / `min_winrate`）は**変えない**。ユーザーが「攻め」の結果を見て変えたいと言った場合だけ、要件1（勝ちが最優先・安全条件は緩めない）を再決定するのかを明示的に確認する。
4. 採否の基準を満たさない項目があれば、それを先に伝え、「既定値を据え置いて実戦確認へ進む」か「設計に戻る」かを聞く。

- [x] **Step 2: 返事を記録する**

ユーザーが選んだ**変える項目だけ**を `<scratchpad>/veil_defaults.json` に書く（盤サイズの文字列 → {接尾辞: 値}）。形の例（ユーザーが 13路の free_loss を 0.4・dominant_hp を 0.9 にした場合）:

```json
{"13": {"free_loss": 0.4, "dominant_hp": 0.9}}
```

進み方はユーザーの返事で3通りに分かれる:
- **変える**: 上のとおり `veil_defaults.json` を書き、Task 17 → Task 18 → Task 19 と進む。要件1を再決定した（reserve / min_winrate を変える）場合は Task 17 で `--safety-redecided` を付ける。
- **据え置いて実戦確認へ進む**（何も変えない）: ファイルを作らず、Task 17 を飛ばして Task 18 へ進む。Task 18 のスクリプトは `tests/test_ai_veil.py` の `CALIBRATED_DEFAULTS[13]` が空であることから「据え置き」と判断し、マニュアルの校正状況・`ai-parameters.md` の「校正」行・INDEX・spec の状態を「ハーネスで測定し、spec の初期値を据え置いた」の文面で書く（「校正して選んだ」とは書かない）。
- **設計に戻る**: Task 17・18・19 は実行しない。下の Step 3 で決定をコミットし、INDEX は 📝 のまま、**ここで計画を止めてユーザーに報告する**（何が採否の基準を満たさなかったか・`veil13-campaign.md` の場所）。

- [x] **Step 3: 決定を記録してコミットする**（どの選択でも必ず行う）

`veil13-campaign.md` の末尾に次の節を足す（Task 15 で Write した LF の新規ファイルなので Edit ツールで追記してよい）:

```markdown
## ユーザーの決定（YYYY-MM-DD）

- 進み方: 変える / 据え置いて実戦確認へ進む / 設計に戻る（どれか1つ）
- 変える項目と値: 13路 free_loss 0.3 → 0.4 …（`veil_defaults.json` と同じ内容。無ければ「なし」）
- 9路・19路: 据え置き / 変える項目と値
- 要件1（安全条件 reserve / min_winrate）: 据え置き / 再決定した（新しい値と理由）
- 採否の基準で満たさなかった項目とその扱い（無ければ「なし」）
```

```bash
git add docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md
git commit -m "docs(veil): 校正結果に対するユーザーの既定値選択を記録

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: 選んだ既定値の反映（コード・パッケージ config・テスト期待値・ユーザー設定）

（飛ばした: Task 16 で 13路の既定値を据え置いたため。コード・パッケージ config・テスト期待値・ユーザー設定は変えていない）

**Files:**
- Modify: `katrain/core/ai.py`（`Veil{9,13,19}Strategy.SETTING_DEFAULTS` の該当行だけ）
- Modify: `katrain/config.json`（`ai:veil*` の該当キーだけ）
- Modify: `tests/test_ai_veil.py`（`CALIBRATED_DEFAULTS`・要件1を再決定したときだけ `SAFETY_DEFAULTS`）
- Modify: `C:\Users\iwaki\.katrain\config.json`（**Step 6 はメインセッションだけ・KaTrain 停止中**）

**Interfaces:**
- Consumes: `<scratchpad>/veil_defaults.json`（Task 16）
- Produces: 新しい既定値。`.claude/rules/ai-parameters.md` の韜晦の表（既定 9 / 13 / 19 列）とマニュアルの表は Task 18 のスクリプトがこの既定値から生成する（このタスクでは md を触らない＝値の二重管理をしない）

- [ ] **Step 1: 反映スクリプトを Write** — `<scratchpad>/apply_veil_defaults.py`（値がスライダーの候補値に無い・安全条件を `--safety-redecided` なしで変えようとした・キーが見つからない、のどれでも何も書かずに止まる）

```python
"""校正後に選んだ韜晦の既定値を、コード・パッケージ config・テストの期待値へ同時に反映する。

使い方（リポジトリのルートで）: python "$SP/apply_veil_defaults.py" "$SP/veil_defaults.json" [--safety-redecided]
JSON は {"13": {"free_loss": 0.4, "dominant_hp": 0.9}, "9": {...}, "19": {...}}（盤ごとに変える項目だけ）。
reserve / min_winrate（勝ちの安全条件）は、ユーザーが要件1を再決定したとき（--safety-redecided）しか変えない。
値はスライダーの候補値（AI_OPTION_VALUES）に含まれていなければ止まる（候補値から選ぶ）。
書き換えるもの: ai.py の Veil{9,13,19}Strategy.SETTING_DEFAULTS、katrain/config.json の ai:veil{9,13,19}、
tests/test_ai_veil.py の CALIBRATED_DEFAULTS（と --safety-redecided なら SAFETY_DEFAULTS）。
"""

import ast
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.getcwd())
from katrain.core.constants import AI_OPTION_VALUES  # noqa: E402

SAFETY = {"reserve", "min_winrate"}
CLASS_HEADERS = {
    9: "class Veil9Strategy(Enigma9Strategy):",
    13: "class Veil13Strategy(Veil9Strategy):",
    19: "class Veil19Strategy(Veil9Strategy):",
}
NL = chr(10)


def read(path):
    raw = open(path, "rb").read()
    return raw.decode("utf-8").replace(chr(13) + NL, NL), (chr(13) + NL).encode() in raw


def write(path, text, crlf):
    if crlf:
        text = text.replace(NL, chr(13) + NL)
    open(path, "wb").write(text.encode("utf-8"))


def replace_in_block(text, start_marker, end_marker, pattern, repl, what):
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    block, n = re.subn(pattern, repl, text[start:end], count=1, flags=re.M)
    if n != 1:
        sys.exit(f"not found: {what}")
    return text[:start] + block + text[end:]


def py_literal(value):
    return repr(bool(value)) if isinstance(value, bool) else repr(value)


def main():
    choice = json.load(open(sys.argv[1], encoding="utf-8"))
    safety_ok = "--safety-redecided" in sys.argv[2:]
    ai_text, ai_crlf = read("katrain/core/ai.py")
    cfg_text, cfg_crlf = read("katrain/config.json")
    test_text, test_crlf = read("tests/test_ai_veil.py")
    # テストの CALIBRATED_DEFAULTS（1文・次のコメント行まで）を読み、選んだ値を足して書き戻す
    cal_start = test_text.index("CALIBRATED_DEFAULTS = ")
    cal_end = test_text.index(NL + "#", cal_start)
    calibrated = ast.literal_eval(test_text[cal_start:cal_end].split("=", 1)[1].strip())
    for size_str, values in choice.items():
        size = int(size_str)
        prefix = f"veil{size}"
        for suffix, value in values.items():
            key = f"{prefix}_{suffix}"
            if suffix in SAFETY and not safety_ok:
                sys.exit(f"{key} は勝ちの安全条件（要件1）。ユーザーが再決定したときだけ --safety-redecided で変える")
            options = AI_OPTION_VALUES.get(key)
            if options is None:
                sys.exit(f"unknown key {key}")
            if options == "bool":
                if not isinstance(value, bool):
                    sys.exit(f"{key} は true/false")
            else:
                plain = [v[0] if isinstance(v, tuple) else v for v in options]
                if value not in plain:
                    sys.exit(f"{key}={value} はスライダーの候補値 {plain} に無い")
            ai_text = replace_in_block(
                ai_text,
                CLASS_HEADERS[size],
                "    VEIL_BOARD = {",
                rf'^(        "{suffix}": )[^,]+(,)',
                lambda m: m.group(1) + py_literal(value) + m.group(2),
                f"ai.py {key}",
            )
            cfg_text = replace_in_block(
                cfg_text,
                f'        "ai:{prefix}": {{',
                "        }",
                rf'^(            "{key}": )[^,\s]+',
                lambda m: m.group(1) + json.dumps(value),
                f"config.json {key}",
            )
            calibrated.setdefault(size, {})[suffix] = value
            if suffix in SAFETY:  # SAFETY_DEFAULTS の1行（例 `    13: {"reserve": 5.0, "min_winrate": 0.85},`）
                test_text = replace_in_block(
                    test_text,
                    "SAFETY_DEFAULTS = {",
                    NL + "}",
                    rf'^(    {size}: {{.*"{suffix}": )[0-9.]+',
                    lambda m: m.group(1) + py_literal(value),
                    f"SAFETY_DEFAULTS {key}",
                )
            print(f"{key} -> {value}")
    body = ", ".join(
        f"{size}: {{" + ", ".join(f'"{k}": {py_literal(v)}' for k, v in calibrated[size].items()) + "}"
        for size in sorted(calibrated)
    )
    cal_end = test_text.index(NL + "#", cal_start)
    test_text = test_text[:cal_start] + "CALIBRATED_DEFAULTS = {" + body + "}" + test_text[cal_end:]
    json.loads(cfg_text)
    write("katrain/core/ai.py", ai_text, ai_crlf)
    write("katrain/config.json", cfg_text, cfg_crlf)
    write("tests/test_ai_veil.py", test_text, test_crlf)
    subprocess.run([sys.executable, "-m", "black", "-q", "tests/test_ai_veil.py"], check=True)
    print("ok")


main()
```

- [ ] **Step 2: 実行**（リポジトリのルートで）

Run: `python "$SP/apply_veil_defaults.py" "$SP/veil_defaults.json"`（要件1を再決定した場合だけ末尾に `--safety-redecided`）
Expected: 変えたキーごとに `veil13_free_loss -> 0.4` のような行と、最後に `ok`

- [ ] **Step 3: テスト**

Run: `pytest tests/test_ai_veil.py tests/test_ai_help_text.py tests/test_ai_options_grid.py -q`
Expected: 全 PASS（通しテストは凍結した `SPEC_DEFAULTS` を明示の設定として渡すので既定値の変更に影響されない。`TestBoardFamily` / `TestRegistration` は `EXPECTED_DEFAULTS`＝spec＋`CALIBRATED_DEFAULTS` とコード・config の一致を確かめる）

- [ ] **Step 4: 差分の健全性**

Run: `git diff --stat`
Expected: 変えたキーの数だけ `katrain/core/ai.py` と `katrain/config.json` が同数の +/−（例: 2 キーなら各 `2 ++--`）、`tests/test_ai_veil.py` は `CALIBRATED_DEFAULTS` の行だけ（black が複数行に分けた場合はその行数）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py katrain/config.json tests/test_ai_veil.py
git commit -m "feat(veil): 自己対局ハーネスの境界線からユーザーが選んだ既定値を反映

選択の根拠は docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md。安全条件（reserve・min_winrate）は据え置き。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
（要件1を再決定して安全条件も変えた場合は、本文の2行目を「要件1の再決定（<日付>・ユーザー）により reserve / min_winrate も変更」に書き換える）

- [ ] **Step 6: ユーザー設定にも写す（MAIN SESSION ONLY・KaTrain 停止中）**

Task 13 Step 1 と同じ方法（`-clike "KaTrain v*"` のウィンドウ名判定と、ユーザーへのチャットでの確認の両方）で KaTrain が止まっていることを確かめてから、スクリプト `<scratchpad>/sync_user_config_veil.py` を Write して実行する（書き換えるのは JSON に書いたキーだけ・編集前のコピーをスクラッチパッドに残す）。

```python
"""Task 17 で選んだ既定値をユーザー設定 ~/.katrain/config.json の ai:veil* にも写す（メインセッション専用・KaTrain 停止中）。

使い方: python "$SP/sync_user_config_veil.py" "$SP/veil_defaults.json"
JSON は apply_veil_defaults.py と同じ形（{"13": {"free_loss": 0.4}, ...}）。書き換えるのは JSON に書いたキーだけ。
"""

import json
import os
import re
import shutil
import sys

USER_CONFIG = os.path.expanduser(os.path.join("~", ".katrain", "config.json"))
NL = chr(10)

choice = json.load(open(sys.argv[1], encoding="utf-8"))
raw = open(USER_CONFIG, "rb").read()
crlf = (chr(13) + NL).encode() in raw
text = raw.decode("utf-8").replace(chr(13) + NL, NL)
for size_str, values in choice.items():
    prefix = f"veil{int(size_str)}"
    start = text.index(f'        "ai:{prefix}": {{')
    end = text.index("        }", start)
    block = text[start:end]
    for suffix, value in values.items():
        key = f"{prefix}_{suffix}"
        block, n = re.subn(rf'^(            "{key}": )[^,\s]+', lambda m: m.group(1) + json.dumps(value), block, flags=re.M)
        if n != 1:
            sys.exit(f"not found in user config: {key}")
        print(f"{key} -> {json.dumps(value)}")
    text = text[:start] + block + text[end:]
json.loads(text)
shutil.copyfile(USER_CONFIG, os.path.join(os.path.dirname(os.path.abspath(__file__)), "user-config-before-veil-defaults.json"))
if crlf:
    text = text.replace(NL, chr(13) + NL)
open(USER_CONFIG, "wb").write(text.encode("utf-8"))
print("ok")
```

Run: `python "$SP/sync_user_config_veil.py" "$SP/veil_defaults.json"`
Expected: 変えたキーごとの行と `ok`（リポジトリ外なのでコミットなし）

---

### Task 18: ドキュメント（rules・CLAUDE.md・マニュアル・INDEX・spec の状態）

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（末尾に節を追加。既定値・候補値・モジュール定数の表はコードから生成）
- Modify: `.claude/rules/ai-strategies.md`（「## 関連 spec」の前に段落）
- Modify: `CLAUDE.md`（改修3系統の表の「Human-like AI 戦略」行・ディレクトリ構造の `ai.py` 行・コーディング規約の戦略クラス列挙）
- Modify: `docs/manual/src/06_ai_overview.html`（用途別の案内と一覧表に3行）・`docs/manual/src/06d_ai_parity.html`（末尾にカード）→ `python tools/build_manual.py`（`docs/manual/index.html` を再生成）
- Modify: `docs/superpowers/specs/INDEX.md`（📝 → 🟢）・`docs/superpowers/specs/2026-09-23-veil-strategy-design.md`（冒頭の「状態」）

**Interfaces:**
- Consumes: 現在の `Veil*Strategy.SETTING_DEFAULTS`（Task 17 の反映後）・`AI_OPTION_VALUES`・`VEIL_*`・`tests/test_ai_veil.py` の `CALIBRATED_DEFAULTS`（13路が空＝Task 16 で据え置き）・Task 15 の結果 md の場所
- Produces: 利用者向け（マニュアル・GUI ヘルプは Task 12）と開発者向け（rules）の説明。校正状況の文面は「13路を校正して選んだ」か「13路はハーネスで測定し spec の初期値を据え置いた」のどちらか（`CALIBRATED_DEFAULTS[13]` で自動で選ぶ）。9路・19路は常に「spec の初期値のままの未校正」。

Task 16 で「設計に戻る」を選んだ場合はこのタスクを実行しない。

- [x] **Step 1: スクリプトを Write** — `<scratchpad>/patch_veil_docs.py`（CRLF を保つ。`.claude/rules/*.md` も Edit ツールでなくこのスクリプトで書く）

```python
"""韜晦のドキュメント（rules 2 本・CLAUDE.md・マニュアル・INDEX・spec の状態）を更新する。

既定値・候補値・モジュール定数の表はコード（Veil*Strategy.SETTING_DEFAULTS / AI_OPTION_VALUES / VEIL_*）から
生成する＝Task 17 で選んだ既定値がそのまま載る。校正状況の文面は tests/test_ai_veil.py の CALIBRATED_DEFAULTS[13]
（Task 17 が書き換える差分）が空なら「据え置き」、空でなければ「校正して選んだ」。リポジトリのルートで実行する。
"""

import ast
import datetime
import os
import sys

os.environ.setdefault("KIVY_NO_ARGS", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
from crlf_patch import patch  # noqa: E402

import katrain.core.ai as ai  # noqa: E402
from katrain.core.constants import AI_OPTION_VALUES  # noqa: E402

CLASSES = {9: ai.Veil9Strategy, 13: ai.Veil13Strategy, 19: ai.Veil19Strategy}
NL = chr(10)
CAMPAIGN = "docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md"


def calibrated_13():
    """tests/test_ai_veil.py の CALIBRATED_DEFAULTS[13]（Task 17 で変えた 13路の既定値。空なら spec の初期値を据え置いた）。"""
    text = open("tests/test_ai_veil.py", encoding="utf-8").read()
    start = text.index("CALIBRATED_DEFAULTS = ")
    end = text.index(NL + "#", start)
    return ast.literal_eval(text[start:end].split("=", 1)[1].strip()).get(13, {})


KEPT_13 = not calibrated_13()
CALIB_13 = "自己対局ハーネスで測定し、spec の初期値を据え置いた" if KEPT_13 else "自己対局ハーネスで校正した"
print(f"veil13 defaults: {'kept (spec initial values)' if KEPT_13 else 'calibrated (changed in Task 17)'}")

# 各項目の（意味, マニュアルの「上げると／下げると」）
DOCS = {
    "target_rate": (
        "目標一致率（この手も一致させた場合の一致率がこれを超えている間だけ、損をする外しと明らかな一手の外しを許す。超過 10pt で全開・15% 以下へは払わない）",
        '<span class="up">上げる</span>外しが減り勝ちが堅い。<span class="down">下げる</span>外しが増えるぶんリードを払う',
    ),
    "reserve": (
        "損をする外し・罠の後にも残すリード（目）＝勝ちの安全条件",
        '<span class="up">上げる</span>勝ちは堅いが外せる手番が減る。<span class="down">下げる</span>外しが増えるが僅差の決着が増える',
    ),
    "min_winrate": (
        "損をする外し・罠の着手後勝率フロア＝勝ちの安全条件",
        '<span class="up">上げる</span>安全だが外しが減る。<span class="down">下げる</span>不利寄りの局面でも払って外す',
    ),
    "free_loss": (
        "同値外し（一致率に関係なく常に打つ外し）の損失の上限（目）。劣勢・一致率 15% 以下では 0.1",
        '<span class="up">上げる</span>外しが増えるが小さな損が積み重なる。<span class="down">下げる</span>序盤・接戦の外しが減る',
    ),
    "free_wr_drop": (
        "同値外しで許す1手の勝率低下（着手後勝率 97% 以上は免除・ヨセで reserve を割るなら 1%）",
        '<span class="up">上げる</span>接戦でも外しが増える。<span class="down">下げる</span>接戦の外しが減る',
    ),
    "close_drift_cap": (
        "接戦中の同値外しの損失の1局あたり合計の上限（目）。OFF で上限なし",
        '<span class="up">値を入れる</span>接戦の外しを合計で頭打ちにする。<span class="down">OFF</span>1手ごとの勝率条件だけで守る',
    ),
    "spend_rate": (
        "損をする外し1回に使う余剰（リード − reserve）の割合",
        '<span class="up">上げる</span>少ないリードでも高い外しを買う。<span class="down">下げる</span>大きくリードするまで安い外しだけ',
    ),
    "max_loss": (
        "1手の支払い上限（目・ヨセ前）。罠の損失の上限も兼ねる",
        '<span class="up">上げる</span>大差で外せる手番が増えるが緩みが見えやすい。<span class="down">下げる</span>小さな損の外しだけ',
    ),
    "yose_max_loss": (
        "1手の支払い上限（目・ヨセ）。0 で同値外しだけ",
        '<span class="up">上げる</span>ヨセでも外せるが目立ちやすい。<span class="down">下げる</span>ヨセは最善手寄り',
    ),
    "dominant_hp": (
        "9段が最善手を選ぶ確率がこれ以上＝明らかな一手（一致率が目標を超えているときだけ外す）。OFF で判定しない",
        '<span class="up">上げる</span>明らかな局面でも外しやすい。<span class="down">下げる</span>慎重で自然',
    ),
    "dominant_max_loss": (
        "明らかな一手で外すときの支払いの上限（目・通常の上限を絞るだけ）",
        '<span class="up">上げる</span>明らかな局面でも高い外し。<span class="down">下げる</span>ほぼ同値の外しだけ',
    ),
    "min_human_policy": (
        "外す先に要る 9段の humanPolicy（絶対床）",
        '<span class="down">下げる</span>外せる手番が増えるが珍しい手が混ざる。<span class="up">上げる</span>はっきり人間らしい手だけ',
    ),
    "natural_ratio": (
        "外す先に要る humanPolicy の第一感比（相対床・明らかな一手の局面では使わない）",
        '<span class="up">上げる</span>第一感に近い有力手だけ。<span class="down">下げる</span>2番手・3番手へも外す',
    ),
    "cost_slack": (
        "最安の外しからこの目数以内を同じ安さとみなし、その中で最も人間らしい手を打つ",
        '<span class="up">上げる</span>人間らしさ優先で少し多く払う。0 で常に最安',
    ),
    "trap_mode": (
        "罠（相手の期待損失 E を増やす手）の上乗せ層（A/B 測定用）。値段は損失 − 0.5 × E の上積み、安全条件は割り引かない",
        '<span class="up">ON</span>罠も外し先にする（素直な外しより 0.3 目以上安いときだけ替える）',
    ),
    "trap_min_delta_e": (
        "罠とみなす E の上積み（目）",
        '<span class="down">下げる</span>罠が増えるが E の誤差を拾いやすい。<span class="up">上げる</span>大きい罠だけ',
    ),
}
assert list(DOCS) == list(ai.Veil9Strategy.SETTING_DEFAULTS)


def fmt_value(key, value):
    options = AI_OPTION_VALUES[key]
    if options == "bool" or isinstance(value, bool):
        return "ON" if value else "OFF"
    for option in options:
        if isinstance(option, tuple) and abs(option[0] - value) < 1e-9:
            return option[1]
    return f"{value:g}"


def fmt_range(suffix):
    def one(key):
        options = AI_OPTION_VALUES[key]
        if options == "bool":
            return "ON/OFF"
        if isinstance(options[0], tuple):
            labels = [label for _value, label in options]
            if labels[-1] == "OFF":
                return f"{labels[0]}〜{labels[-2]}／OFF"
            if labels[0] == "OFF":
                return f"OFF／{labels[1]}〜{labels[-1]}"
            return f"{labels[0]}〜{labels[-1]}"
        return f"{min(options):g}〜{max(options):g}"

    ranges = {size: one(f"veil{size}_{suffix}") for size in CLASSES}
    if len(set(ranges.values())) == 1:
        return ranges[13]
    return "・".join(f"{size}路 {r}" for size, r in ranges.items())


def defaults(suffix):
    return {size: fmt_value(f"veil{size}_{suffix}", cls.SETTING_DEFAULTS[suffix]) for size, cls in CLASSES.items()}


def append(path, text):
    raw = open(path, "rb").read()
    crlf = (chr(13) + NL).encode() in raw
    body = raw.decode("utf-8").replace(chr(13) + NL, NL).rstrip(NL) + NL + text
    if crlf:
        body = body.replace(NL, chr(13) + NL)
    open(path, "wb").write(body.encode("utf-8"))
    print(f"appended {path}")


# ---- .claude/rules/ai-parameters.md（末尾に節を追加）----
rows = []
for suffix, (meaning, _updown) in DOCS.items():
    d = defaults(suffix)
    rows.append(f"| `veil*_{suffix}` | {meaning} | {fmt_range(suffix)} | {d[9]} / **{d[13]}** / {d[19]} |")
boards = [
    f"{size}路 " + "・".join(f"{k} {v}" for k, v in cls.VEIL_BOARD.items()) for size, cls in CLASSES.items()
]
constants = ", ".join(f"`{name}={getattr(ai, name)!r}`" for name in sorted(n for n in dir(ai) if n.startswith("VEIL_")))
PARAMS = f"""
## Veil9/13/19Strategy（`ai:veil9` / `ai:veil13` / `ai:veil19` / 韜晦（9/13/19路））

9/13/19路それぞれ専用。**勝ちを最優先にしたまま、自分の AI 最善手一致率（終局レポートの値）を絶対目標まで下げる**。
設計: `2026-09-23-veil-strategy-design.md`。`Veil9Strategy(Enigma9Strategy)` が `_generate_move` を上書きし、13/19路は
属性（`BOARD_LEN` / `KEY_PREFIX` / `LABEL` / `SETTING_DEFAULTS` / `VEIL_BOARD`）だけのサブクラス。sticky 状態は
`game._veil_state["veil{{9,13,19}}"]`（endgame・close_drift・ledger）、ログタグは `[Veil13Strategy]` 等。ponder と HumanStyle 委譲は使わない。

u = clamp((p_match − target_rate) / 0.10, 0, 1)（p_match = (一致数 + 1) / (分母 + 1)・0.15 以下は 0）。
同値外し: cons = max(vloss, 生 loss〈visits >= trusted_visits のとき〉) <= F_eff かつ勝率低下 <= free_wr_drop（勝率 97% 以上は免除・
ヨセで着手後リード < reserve なら 0.01）。支払う外し: u > 0 かつ S = lead − reserve > 0 で cons <= A_t =
min(S, F + u × (max(F, min(cap, spend_rate × S)) − F))（cap はヨセ前 max_loss・ヨセ中 yose_max_loss。明らかな一手は
dominant_max_loss でも頭打ち）かつ着手後勝率 >= min_winrate。選択は最安から cost_slack 以内の帯で hp 最大。

| キー | 意味 | 候補値 | 既定 9 / **13** / 19 |
|---|---|---|---|
{NL.join(rows)}

クラス属性 `VEIL_BOARD`（スライダーにしない）: {" ／ ".join(boards)}。
モジュール定数: {constants}。

**確認**: ログの `Rate:`（mine/n・opp/n_opp・p_match・u）/ `Endgame check:`（unsettled・max）/ `Budget:` / `Natural:` / `Decided:` / `Score …` / `Deviate:` /
`Terminal…` / `Decision: {{json}}`（tier i/ii/iii/terminal/failsafe・kind best/free/paid/trap/decided/swap/finish/pass・why）。
CLI: `python -m katrain_debug --sgf <SGF> --move N --strategy veil9|veil13|veil19`。
**校正**: 13路は{CALIB_13}（`{CAMPAIGN}`）。9/19路は spec の初期値のままの未校正。**実戦校正は未実施**。
"""
append(".claude/rules/ai-parameters.md", PARAMS)

# ---- .claude/rules/ai-strategies.md（「## 関連 spec」の前に段落）----
STRATEGIES = (
    "9/13/19路には**勝ち優先で自分の一致率を絶対目標まで下げる戦略 `ai:veil9` / `ai:veil13` / `ai:veil19`（韜晦）**がある"
    "（2026-09-23・spec `2026-09-23-veil-strategy-design.md`。擬態の後継だが擬態は無変更）。実装は `Veil9Strategy(Enigma9Strategy)` が"
    " `_generate_move` を上書きし、難解の子局面プローブ・相手の直前パスの終局処理を再利用、ponder と HumanStyle 委譲は使わない。"
    "一致率は終局レポートと同一定義（`veil_tally`。合成木で `game_report` との完全一致をテストで固定）。**同値外し（free）は一致率に"
    "関係なく常に、損をする外し（paid）は一致率が目標を超えている間だけリードの余剰から**払い、最善手の hp >= dominant_hp（明らかな一手）"
    "は目標超のときだけ dominant_max_loss まで。候補は自然さの床を満たす手だけを子局面で検証し、最安帯の中で hp 最大。決着局面は"
    "プローブなしで即決、終局帯はダメ詰めの順番入れ替え（生 loss 0.10・接戦 0.05 まで）。罠は `trap_mode`（既定 OFF・A/B 用）の上乗せ層で、"
    "値段は ΔE の半分だけ割り引き安全条件は割り引かない。全フェイルセーフと不変条件違反は最善手。毎手 `Decision: {json}` と"
    " `last_decision_info` と `game._veil_state[prefix]` の ledger を残す（自己対局ハーネスが読む）。既定値とハーネスでの境界線は"
    f" `ai-parameters.md` と `{CAMPAIGN}`。**実戦校正は未実施**。"
)
patch(".claude/rules/ai-strategies.md", [(NL + "## 関連 spec" + NL, NL + STRATEGIES + NL + NL + "## 関連 spec" + NL, 1)])

# ---- CLAUDE.md（3 箇所）----
patch(
    "CLAUDE.md",
    [
        (
            "擬態（13路＝相手より低い一致率で勝つ・`Mimic13Strategy`） |",
            "擬態（13路＝相手より低い一致率で勝つ・`Mimic13Strategy`）/ 韜晦（9・13・19路＝勝ち優先で自分の一致率を絶対目標まで下げる・`Veil9Strategy`） |",
            1,
        ),
        (" / Mimic13 / TsumegoOwnership / TsumegoSolver）", " / Mimic13 / Veil9（Veil13 / Veil19） / TsumegoOwnership / TsumegoSolver）", 1),
        ("`Mimic13Strategy` / `TsumegoOwnershipStrategy`", "`Mimic13Strategy` / `Veil9Strategy`（+13/19） / `TsumegoOwnershipStrategy`", 1),
    ],
)

# ---- マニュアル（AI 概要の案内と一覧表・一致率の節のカード）----
MIMIC_ROW = (
    '    <tr><th><a href="#ai-mimic13">擬態（13路）</a></th><td><code>ai:mimic13</code></td><td>13</td><td>必須</td>'
    "<td>相手より低い一致率を保って勝つ（人間らしい外し＋罠・ヨセは9段）</td></tr>" + NL
)
VEIL_ROWS = "".join(
    f'    <tr><th><a href="#ai-veil">韜晦（{size}路）</a></th><td><code>ai:veil{size}</code></td><td>{size}</td><td>必須</td>'
    f"<td>{text}</td></tr>" + NL
    for size, text in [
        (9, "勝ちを優先して自分の一致率を目標まで下げる（未校正）"),
        (13, "同・13路専用（" + ("自己対局で測定・設計時の初期値" if KEPT_13 else "自己対局ハーネスで校正") + "）"),
        (19, "同・19路専用（未校正）"),
    ]
)
patch(
    "docs/manual/src/06_ai_overview.html",
    [
        (
            '／13路で相手より低く保つなら <a href="#ai-mimic13">擬態（13路）</a>',
            '／13路で相手より低く保つなら <a href="#ai-mimic13">擬態（13路）</a>'
            '／勝ちを優先して目標の一致率まで下げるなら <a href="#ai-veil">韜晦（9/13/19路）</a>',
            1,
        ),
        (MIMIC_ROW, MIMIC_ROW + VEIL_ROWS, 1),
    ],
)
card_rows = []
for suffix, (meaning, updown) in DOCS.items():
    d = defaults(suffix)
    card_rows.append(
        f'      <tr><td>veil*_{suffix}</td><td>{d[13]}<span class="jp">9路 {d[9]}・19路 {d[19]}</span></td>'
        f"<td>{fmt_range(suffix)}</td><td>{meaning}</td><td>{updown}</td></tr>"
    )
CARD = f"""
<div class="card" id="ai-veil">
  <h3>韜晦（9路 / 13路 / 19路） <code>ai:veil9</code> / <code>ai:veil13</code> / <code>ai:veil19</code></h3>
  <div class="tags"><span class="tag ok">盤サイズごとに専用</span><span class="tag hs">humanSL 必須</span><span class="tag">勝ち優先</span></div>
  <p>
    勝ちを最優先にしたまま、評価レポートの<b>自分の最善手一致率を目標（<code>veil*_target_rate</code>）まで下げる</b>戦略です。
    相手より低くすることは目指しません（相手の一致率はログに出すだけ）。3 つは同じ仕組みで、盤サイズに合わせた既定値だけが違います
    （設定は <code>veil9_*</code> / <code>veil13_*</code> / <code>veil19_*</code> と別々に保存）。対応しない盤サイズで選ぶと常に最善手を打ちます。
  </p>
  <ol>
    <li><b>ほぼ損失ゼロの外し（同値外し）</b>は、一致率に関係なく常に打ちます（損失が <code>veil*_free_loss</code> 以下で、1 手の勝率低下も <code>veil*_free_wr_drop</code> 以下の手）。</li>
    <li><b>損をする外し</b>は、一致率が目標を超えている間だけ、リードの余剰（リード − <code>veil*_reserve</code>）から払います。1 回の上限は余剰 × <code>veil*_spend_rate</code>（天井はヨセ前 <code>veil*_max_loss</code>・ヨセ <code>veil*_yose_max_loss</code>）。外した後も着手後勝率が <code>veil*_min_winrate</code> を割らないことが条件です。</li>
    <li><b>9段の第一感が最善手に集中している局面</b>（明らかな一手）は、一致率が目標を超えているときだけ、<code>veil*_dominant_max_loss</code> までの損失で外します。</li>
    <li>外す先は 9段が実際に打ちそうな手に限り、候補を着手後の局面まで読んで確かめ、最も安い帯（<code>veil*_cost_slack</code>）の中で最も人間らしい手を選びます。</li>
    <li>ヨセも自分で打ち（委譲しない）、盤上に 0.5 目以上の手が無い終局間際はダメ詰めの順番を入れ替える程度（0.1 目・接戦 0.05 目まで）に留めます。</li>
  </ol>
  <div class="tablewrap"><table class="params">
    <thead><tr><th>設定項目</th><th>既定（13路）</th><th>範囲</th><th>意味</th><th>上げると／下げると</th></tr></thead>
    <tbody>
{NL.join(card_rows)}
    </tbody>
  </table></div>
  <div class="callout warn">
    <span class="label">校正状況</span>
    13路の既定値は、人間を模したボットとの無人対局（自己対局ハーネス）で一致率と勝ちの安全を{'測ったうえで、設計時の初期値を据え置きました' if KEPT_13 else '測って選びました'}。9路・19路は設計時の初期値のままの未校正の値です。実戦での確認はこれからです。
  </div>
</div>
"""
append("docs/manual/src/06d_ai_parity.html", CARD)

# ---- INDEX と spec の状態 ----
patch(
    "docs/superpowers/specs/INDEX.md",
    [
        ("| `2026-09-23-veil-strategy-design.md` | 📝 韜晦（9/13/19路）", "| `2026-09-23-veil-strategy-design.md` | 🟢 韜晦（9/13/19路）", 1),
        (
            "＝ハーネスで境界線を測って既定値を決める |",
            f"＝ハーネスで境界線を測って{'既定値は据え置いた' if KEPT_13 else '既定値を決めた'}（`calibration-data/selfplay/veil13-campaign.md`）・**実戦校正は未実施** |",
            1,
        ),
    ],
)
today = datetime.date.today().isoformat()
patch(
    "docs/superpowers/specs/2026-09-23-veil-strategy-design.md",
    [
        (
            "状態: 設計（未実装）。検証は自己対局ハーネス（spec `2026-09-23-selfplay-harness-design.md`）→実戦の順" + NL,
            f"状態: 実装済み（{today}）・13路は{CALIB_13}（`calibration-data/selfplay/veil13-campaign.md`）・実戦校正は未実施" + NL,
            1,
        )
    ],
)
```

- [x] **Step 2: 実行してマニュアルを再生成**

Run: `python "$SP/patch_veil_docs.py"`
Expected（1行目は Task 16 の選択どおりか確かめる: 何も変えなかったなら `kept`、Task 17 で 13路を変えたなら `calibrated`）:
```
veil13 defaults: kept (spec initial values)        ← または veil13 defaults: calibrated (changed in Task 17)
appended .claude/rules/ai-parameters.md
patched .claude/rules/ai-strategies.md (CRLF, 1 edit(s))
patched CLAUDE.md (CRLF, 3 edit(s))
patched docs/manual/src/06_ai_overview.html (CRLF, 2 edit(s))
appended docs/manual/src/06d_ai_parity.html
patched docs/superpowers/specs/INDEX.md (CRLF, 2 edit(s))
patched docs/superpowers/specs/2026-09-23-veil-strategy-design.md (LF, 1 edit(s))
```
（Kivy の起動ログが先に数行出ることがある）
Run: `python tools/build_manual.py`
Expected: `missing images: none` / `broken anchors: none`（exit 0）

- [x] **Step 3: 目視確認**

Run: `git diff .claude/rules/ai-parameters.md | head -60`
Expected: 16 行の表の「既定 9 / **13** / 19」列が現在のコードの値（Task 17 で変えた値を含む）、`veil*_dominant_hp` の候補値が `60%〜95%／OFF`、`veil*_close_drift_cap` が `OFF／0.5〜3.0`、末尾の「**校正**:」行が Task 16 の選択と合っている（据え置きなら「測定し、spec の初期値を据え置いた」）。
Run: `git diff docs/manual/src/06d_ai_parity.html | grep -A2 "校正状況"`
Expected: 9路・19路は「設計時の初期値のままの未校正の値」、13路は Task 16 の選択どおりの文面。

- [x] **Step 4: 差分の健全性**

Run: `git diff --stat`
Expected: `.claude/rules/ai-parameters.md`（+40 前後）・`.claude/rules/ai-strategies.md`（+2）・`CLAUDE.md`（3 +/3 −）・`docs/manual/src/06_ai_overview.html`（+4/−1）・`docs/manual/src/06d_ai_parity.html`（+42 前後）・`docs/manual/index.html`・`INDEX.md`（1 +/1 −）・spec（1 +/1 −）。これ以外のファイルや、既存行の大量の削除（再整形）が出たら止める。
Run: `git ls-files --eol .claude/rules/ai-parameters.md .claude/rules/ai-strategies.md CLAUDE.md docs/manual/src/06_ai_overview.html docs/manual/src/06d_ai_parity.html docs/manual/index.html docs/superpowers/specs/INDEX.md docs/superpowers/specs/2026-09-23-veil-strategy-design.md`
Expected: 2列目が spec md だけ `w/lf`、それ以外はすべて `w/crlf`（`core.autocrlf=true` なので改行コードの反転は `git diff` に出ない＝ここで確かめる。違えば止める）。

- [x] **Step 5: コミット**

```bash
git add .claude/rules/ai-parameters.md .claude/rules/ai-strategies.md CLAUDE.md docs/manual docs/superpowers/specs/INDEX.md docs/superpowers/specs/2026-09-23-veil-strategy-design.md
git commit -m "docs(veil): 韜晦の rules・CLAUDE.md・マニュアル・INDEX を更新

パラメータ表とマニュアルの既定値はコードから生成（校正で選んだ値がそのまま載る）。

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 19: 最終検証

- [x] **Step 1: 全テスト**（KataGo・ハーネスと並走させない）
  （2026-09-24: `--ignore=tests/test_ai.py` は 1918 passed。test_ai.py の test_ai_strategies はワークツリーにエンジン本体が無い既知の失敗、test_ai_rank_estimation は既知の `-20 <= nan`）

Run: `pytest --ignore=tests/test_ai.py -q`
Expected: 全 PASS。`test_collapsable_panel.py` の 6 件が落ちたら既知の順序依存フレーク＝`pytest tests/test_collapsable_panel.py -q` 単体で PASS を確認。`tests/test_debug_runner.py` の結合テストは実 KataGo を起動するので数十秒かかる。ソルバの時間閾値系が落ちたら KataGo と並走していないか確かめて単体再実行。
Run: `pytest tests/test_ai.py -q --deselect tests/test_ai.py::TestAI::test_ai_rank_estimation`（humanSL モデルがある環境で・数分）
Expected: 全 PASS（veil9 / veil13 は 19路で最善手のフェイルセーフ、veil19 は 19路でフローを通る）。
`test_ai_rank_estimation` を外すのは **HEAD `3f4c4a00` から落ちている既存の失敗**だから（Task 0 Step 4 で記録済み。`AI_STRENGTH` が nan の parity9 / enigma* / mimic13 / siege / hunt / hunt_diverge / tsumego / tsumego_solver で `-20 <= nan` が偽）。veil9/13/19 も同じく nan なので結果は変わらない＝**この計画では直さない**（veil に数値の強さを入れて通そうとしない）。
Run: `pytest tests/test_ai.py::TestAI::test_ai_rank_estimation -q`
Expected: `1 failed`・`assert -20 <= nan`（Task 0 Step 4 と同じ落ち方。違う落ち方なら報告する）

- [x] **Step 2: 差分の健全性**（この計画のコミット前の HEAD との比較）

Run:
```bash
BASE="$(git rev-parse "$(git log -1 --format=%H -F --grep='docs(veil): 韜晦（9/13/19路）戦略の実装計画')~1")"; echo "$BASE"
git diff "$BASE" --stat -- . ':!docs/superpowers/plans'
```
（BASE＝Task 0 Step 5 の計画コミットの親＝Task 0 Step 2 で `veil_base.txt` に残した値。同じセッションなら `cat "$SP/veil_base.txt"` と一致することも確かめる）
Expected: `katrain/core/ai.py` は +934 / −1（計画の写しでの実測。Task 14 の `fix(veil)` があればその分増える。削除は import 行の置き換えだけ＝既存行の削除がそれ以上あれば再整形の混入）、`katrain/core/constants.py` は +134 / −1、`katrain_debug/runner.py` +4 / −1、`katrain/config.json` +54（Task 17 で変えたキーぶんの ± を足す）。
Run: `git ls-files --eol katrain/core/ai.py katrain/core/constants.py katrain_debug/runner.py katrain/config.json katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/gui/ai_help.py tests/test_ai_help_text.py tests/test_ai_veil.py`
Expected: 2列目が `ai_help.py`・`test_ai_help_text.py`・`test_ai_veil.py` だけ `w/lf`、それ以外は `w/crlf`。

- [ ] **Step 3: GUI 確認の依頼**（ユーザー作業・メインセッションが依頼する）
  （保留: ユーザーの GUI 確認待ち。ワークツリーから起動するか master へのマージ後に行う）

KaTrain を起動 → 対局設定で AI に「韜晦（9路）／（13路）／（19路）」が選べること、AI 設定画面に 16 スライダーが並び説明欄の【各項目】に `veil13_target_rate` 〜 `veil13_trap_min_delta_e` の日本語名と解説が出ること、13路で数手打たせて `~/.katrain/logs/game_*.log` に `[Veil13Strategy] 着手決定に` が出ること（`debug_level: 1` なら `Rate:` / `Decision:` 行も）を確かめてもらう。

- [x] **Step 4: 計画を完了済みに更新してコミット**

この計画の `- [ ]` を、実施したステップだけ `- [x]` にする。飛ばしたタスク・ステップ（例: Task 16 で据え置いたので Task 17 を飛ばした・recon が無く Task 14 Step 3 を飛ばした）は `- [ ]` のまま、その見出しの直後に理由を1行添える（例「（飛ばした: Task 16 で既定値を据え置いたため）」）。計画 md は LF で作ってある（python の `b"\r\n" in open(p, "rb").read()` が False）ので Edit ツールでよい（CRLF になっていたら crlf_patch で書き換える）。

```bash
git add docs/superpowers/plans/2026-09-23-veil-strategy.md
git commit -m "docs(veil): 韜晦の実装計画を完了済みに更新

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 実装後の実戦確認（この計画の範囲外・記録だけ）

spec §10.5: 実戦で各 10 局以上（13路）打ち、ログの `Rate:` / `Decision:` 行と終局レポート（または `python -m katrain_debug.selfplay report-sgf <保存 SGF>`）で自分と相手の一致率・勝敗・払った vloss を集計して、ハーネスの予測（`veil13-campaign.md`・ハーネスと実戦のずれ込み）と比べる。9路・19路はハーネスの校正をしていない。

---

## Self-Review（計画作成時に実施・2026-09-23 のレビュー反映後に再実施）

### 1. spec の網羅

| spec | 対応するタスク |
|---|---|
| §1 要件1（勝ち最優先・安全条件を緩めない） | Global Constraints・Task 4（`veil_paid_ok`）・Task 6（罠の安全は vloss で判定）・Task 9a（フェイルセーフ）・Task 9b（不変条件）・Task 15（段階3 の相手を HumanStyle 9段に上書き・採否の区間 0.95）・Task 16（要件1の再決定なしに reserve / min_winrate を変えない）・Task 17（`--safety-redecided` が無ければ止まる） |
| 要件2（レポートの一致率・`candidate_moves[0]`） | Task 1（`veil_tally` と `game_report` の完全一致テスト 40 木）・Task 9a（S3・S4） |
| 要件3（絶対目標・15% 未満へ払わない・相手はログだけ） | Task 2（`veil_urgency` / `veil_free_limit`）・Task 6（ゲート閉の罠は p_match > 0.15）・Task 9a（`Rate:` 行） |
| 要件4（勝勢で 13路 4.5 目まで） | Task 2（§6 の目安テスト）・Task 11（13路の `max_loss` 4.5） |
| 要件5（3段・同値外しは常に・支払いは目標超だけ） | Task 4（`veil_classify` の free はゲート非依存）・Task 9a（`TestTiers`）・Task 9b（`TestTiersDeviating` / `TestFreeAndPaid`） |
| 要件6（候補＝許容損失以内かつ hp 床以上） | Task 3・Task 9a（S10〜S12）・Task 9b（S13〜S14） |
| 要件7（人間らしい手・予算が回数に効く） | Task 5（最安帯で hp 最大）・Task 9b（最安1手でなく帯の中の hp 最大） |
| 要件8（罠は切り替え・床免除 hp >= 0.02・A/B） | Task 6・Task 9c（`TestTrapLayer`）・Task 15（段階1 の trap アームと罠 A/B 節） |
| 要件9（9・13・19路） | Task 9a・11・12 |
| 要件10（ハーネス → 実戦） | Task 15〜17・計画末尾の「実戦確認」 |
| §3 構成・継承・使わないもの | Task 9a（`Enigma9Strategy` 継承・ponder / HumanStyle / net / ΔE 床 / `mimic_choose` は使わない）・Task 11 |
| §3.1 ponder を使わない | Task 9a・9b（`_start_ponder` を呼ばない・テストで `s.ponders == []`） |
| §4 S0〜S20 | Task 9a（S0〜S6・S9〜S12）・Task 9b（S13〜S20 の素の外し）・Task 9c（S16・S17 の罠）・Task 10（S7・S8） |
| §4.1 クエリ数 | Task 9a〜9c・10 のテストが `s.queries` / `s.probe_calls` / `info["queries"]` で固定 |
| §5 集計と緊急度 | Task 1・2 |
| §6 予算・§6.1 既定値・`VEIL_BOARD`・モジュール定数 | Task 1（定数）・2・9a・11・12（候補値）・18（表） |
| §7 罠 1〜5 | Task 6（資格・安全・値段・合流）・Task 9b（素の分類は ΔE を見ない＝ΔE が負でも素の手は減点しない）・Task 9c（合流） |
| §8 純関数の表（15 本） | Task 1〜8（`veil_tally` `veil_urgency` `veil_free_limit` `veil_allowance` `veil_natural_floor` `veil_prefilter` `veil_shortlist` `veil_cons_loss` `veil_near_free_ok` `veil_paid_ok` `veil_close_drift_ok` `veil_classify` `veil_choose` `veil_trap_price` `veil_trap_ok` `veil_merge_trap` `veil_terminal_swap` `veil_invariant_ok` `veil_decision_record`＋補助 `veil_terminal_limit`） |
| §9 テスト: 境界値・`game_report` 一致 | Task 1〜8 |
| §9: `veil_allowance` が §6 の目安どおり（ヨセ前・ヨセ中・cap < F_eff） | Task 2 `TestAllowance` |
| §9: 3盤の登録・既定値・両 config・`AI_OPTION_VALUES` / `AI_OPTION_ORDER` | Task 11 `TestBoardFamily`・Task 12 `TestRegistration`（ユーザー config は Task 13 の検算） |
| §9: 段(i) 0本・段(ii) 閉 1本・決着局面の即決 | Task 9a `TestTiers`（段(i)・段(ii) 閉）・Task 9b `TestTiersDeviating`（段(ii) 開・決着局面の即決） |
| §9: reserve と勝率フロアでの拒否 | Task 9b `test_small_surplus_cannot_pay_below_the_reserve` / `test_winrate_floor_rejects_a_paid_deviation`・Task 4 `TestPaid` |
| §9: ヨセの 0.01 ガード・`close_drift_cap` ON/OFF | Task 9b `TestYoseAndCloseGames`・Task 4 |
| §9: 相手の直前パスで pass_loss >= 0.5 のとき外しに進まない | Task 10 `test_opponent_pass_with_an_expensive_pass_never_deviates` |
| §9: 終局帯入れ替えの 0.05 / 0.10・(d) の損失上限 | Task 10 `test_swap_allows_0_10…` / `test_finishing_move_respects_the_same_loss_limit`・Task 7 |
| §9: 罠 ON/OFF で罠枠以外のクエリ列が同一・素の外しが罠で消えない | Task 9c `TestTrapLayer`・Task 3 `test_trap_slots_…never_change_the_natural_slots`・Task 6 `test_merge_…` |
| §9: ヨセの罠が yose_max_loss を超えない・dominant の罠が dominant_max_loss を超えない | Task 9c `test_yose_trap_never_exceeds_yose_max_loss` / `test_dominant_trap_never_exceeds_dominant_max_loss` |
| §9: 全フェイルセーフと不変条件違反で最善手 | Task 9a `TestFailSafes`（盤サイズ・候補なし・lead なし・humanSL 失敗・例外・解析破棄の再送出）・Task 9b `TestFailSafesDeviating`（best プローブ欠落・不変条件）と `test_near_free_needs_a_small_winrate_drop`（全候補不合格）・Task 10（終局帯の humanSL 失敗） |
| §9: `_start_ponder` が一度も呼ばれない・`board_watch_probe_warm` が False に戻る | Task 9b `test_near_free_deviation_even_at_target` ほか |
| §9: 難解・擬態の既存テストが無変更で通る | Task 9a Step 6・Task 9c Step 6・Task 12 Step 11・Task 19 |
| §9: `test_ai_help_text.py` のファミリー正規表現に veil | Task 12 Step 9 |
| §10 校正と採否 | Task 15（Step 0 で実行の了承・段階1〜3＋つまみの掃引 1b・段階3 は HumanStyle 9段・比較ごとの summary の写し・採否 (a) は `--conf 0.95`）・Task 16（ユーザーが選ぶ・3通りの進み方・決定をコミット）・Task 17 |
| §11 登録・触るファイル | Task 9a（定数）・12・13・18 |
| §12 リスク | 監視の材料は `Decision:` 行と Task 15 の結果 md（接戦の同値外しの vloss 合計・ハーネスと実戦のずれ・19路は未校正と明記） |

### 2. プレースホルダの走査

コードとスクリプトはすべて実物を載せた。実行時にしか決まらないのは、Task 15 の結果 md に写す**測定値**（どの summary のどの値をどの列に写すかは指定済み）、Task 16 の**ユーザーの選択**（`veil_defaults.json` と決定の節の形は固定・例つき）、実行するセッションの**スクラッチパッドのパス**（`<スクラッチパッドの Windows パス>`＝`$SP` の定義に入れる値。File Structure 節）だけ。「TBD」「後で」「適切に処理」の類は無い。Task 9a〜9c の赤・緑の件数と diff stat は下の 4 で実測した値。

### 3. 名前と型の一貫性

- `VeilCtx` のフィールド（Task 4）＝Task 6 の `veil_trap_ok`・Task 9b の生成箇所（15 フィールドすべてキーワード指定）。
- 純関数の引数順は Task 1〜8 の定義と Task 9a〜9c・10 の呼び出しで一致（`veil_allowance(lead, reserve, spend_rate, free, cap, u)`・`veil_shortlist(naturals, trap_cands, hp_of, band_cap, probe_hp, probe_cheap, trap_probes)`・`veil_terminal_swap(candidates, best_gtp, hp_of, floor, lead, dominant, urgency, close_drift, close_drift_cap)`・`veil_invariant_ok(chosen, best, cand_gtps, kind, bounds)`）。
- 仮の実装と置き換えの一致: Task 9a の仮の `_veil_terminal` の3行＝Task 10 の `STUB`、Task 9a の仮の末尾4行＝Task 9b の `STUB`（どちらも一字一句同じ・件数 1）。Task 9c の5つの置き換え元（`EDITS` の old）は Task 9b の `REAL` にそれぞれちょうど1回現れ、置き換え後は分割前の Task 9 のコードと同一。
- Task 9b の S13〜S20 が使う S12 までの局所変数（`tier` `naturals` `trap_cands` `allowance2` `trap_cap` `cap_phase` `f_eff` `surplus` `hp_of` `cand_gtps` `opponent` `trap_on` ほか）は Task 9a のコードで定義済み。Task 9c が使う `row` `ctx` `vloss` `trap_on` は Task 9b / 9a で定義済み。
- テストの import: Task 9a は `from katrain.core.ai import (…)` と `from katrain.core.constants import AI_VEIL_9` の2文、Task 11 はその2文を丸ごと置き換える（constants の import は1本のまま）。Task 12 は先頭の `import json` 〜 `import katrain.core.ai as ai_module` を置き換える。
- `SPEC_DEFAULTS` / `CALIBRATED_DEFAULTS` / `EXPECTED_DEFAULTS` / `SAFETY_DEFAULTS`（Task 9a のテスト）と Task 17 のスクリプトが書き換える箇所が一致。Task 18 のスクリプトは同じ `CALIBRATED_DEFAULTS` の読み方（`CALIBRATED_DEFAULTS = ` から次のコメント行まで）で 13路が空かを見て、校正状況の文面を Task 16 の「変える／据え置き」に合わせる（「設計に戻る」では Task 18 を実行しない）。
- `last_decision_info` のキー（共有インターフェース節・`unsettled` を含む）＝Task 9a〜9c・10 のコードと Task 18 のドキュメント。
- `$SP` の書き方は File Structure 節の1か所で定義し、Run 行はすべて `"$SP/…"`（ダブルクォート・スラッシュ）。
- KaTrain の起動判定は Task 13 Step 1 の1か所で定義（`-clike "KaTrain v*"`＋チャットでの確認）し、Task 15 Step 1・Task 17 Step 6 はそれを参照する。

### 4. 実行で確かめたこと

Task 1〜12 のコード・テスト・パッチスクリプトと Task 13・17・18 のスクリプトは、HEAD `3f4c4a00` のリポジトリの写し（スクラッチ）に順に当てて実行した: 各タスクの赤（収集エラー／Task 9b `9 failed, 90 passed`／Task 9c `4 failed, 101 passed`／Task 10 `9 failed, 107 passed`／Task 12 `16 failed, 129 passed`）と緑（4 / 29 / 35 / 50 / 56 / 63 / 69 / 73 / 84 / 99 / 105 / 116 / 129 / 145 passed）は本文の Expected のとおり。diff stat（ai.py: Task 9a +269/−1・9b +139/−2・9c +7/−3・10 +90/−1・11 +64/−0 ほか）も本文のとおり。Task 9a+9b+9c+10 を当てた後の ai.py は、分割前の Task 9 のコード（S6 の `Endgame check:` 診断の差し替えだけが違う）＋ Task 10 と一字一句同じ。S6 の診断は ownership なし（`unsettled=None -> yose`）・未確定 19（`-> not yet`・cap 4.5）・未確定 9（`-> yose`・cap 1.5）の3通りで確かめた。`tests/test_ai_veil.py`・`katrain/gui/ai_help.py`・`tests/test_ai_help_text.py` は black 整形済み。既存戦略テスト（Task 9a / 9c Step 6 の mimic13・enigma 系・parity9）は 422 passed。登録後（Task 12 の Step 9・10 まで）に `pytest --ignore=tests/test_ai.py --ignore=tests/test_debug_runner.py -q` は 1711 passed（分割後の計画で当て直して確認）、`tests/test_ai.py::TestAI::test_order` も PASS。`tests/test_ai.py::TestAI::test_ai_rank_estimation` は HEAD の時点で `assert -20 <= nan` で落ちる（nan の戦略 13 個）＝Task 0 Step 4 / Task 19 Step 1 で既知の失敗として扱う。`apply_veil_defaults.py` は候補値外・安全条件の無断変更で止まり、変更後もテストが通ること、`patch_user_config_veil.py` / `sync_user_config_veil.py` はユーザー設定の写しで CRLF を保つことを確かめた。`patch_veil_docs.py` の後の `tools/build_manual.py` は `missing images: none` / `broken anchors: none`。KaTrain の起動判定は、`-like "KaTrain*"` だと VS Code のウィンドウ名（`katrain-1.17.1.1 - Visual Studio Code`）を拾う誤検知を実機で確かめ、`-clike "KaTrain v*"` にした。`git log -1 -F --grep=<日本語の件名>` で計画コミットを引けることも確かめた。このリポジトリは `core.autocrlf=true`（index LF・作業ツリー CRLF）で、改行コードの反転は `git diff` に出ない＝`git ls-files --eol` で見る。ハーネス（Task 15）と実 KataGo（Task 14）はこの計画の作成時には走らせていない（ハーネス計画の完了が前提）。

### 5. spec からの解釈・補い（実装で決めたこと）

- `Rate:` 行は S4 で毎手1回だけ出す（S20 でも出すと集計が二重になる）。一致数は `Decision:` 行にも入る。
- S6 は擬態と同じ形の `Endgame check: … unsettled=N max=M -> yose (sticky)|not yet` 行と `info["unsettled"]` を出す（spec §4 S6 はログを定めていない。実エンジンでは通常解析に ownership が入るので、ヨセに入らない理由＝未確定点の数をログで見分けられるようにする。判定そのものは spec どおり `parity9_is_endgame`）。
- S12 で明らかな一手のときに掛け直すのは spec どおり**自然用の足切りだけ**。罠用のプールは S10 のまま（罠の vloss は `trap_cap` = min(cap, dominant_max_loss) で頭打ち）。
- 「自然な候補」は自然枠（`veil_shortlist` の第1返り値）に入った手だけ。罠枠の手は罠としてしか選ばれない＝素の外し P は罠 ON/OFF で同じ（A/B の比較を罠の上乗せだけにする）。
- `F_eff` の厳しい側は `min(free_loss, 0.1)`（ユーザーが free_loss を 0.1 未満にしていたら上げない）。
- 勝率が取れない候補は同値外しにしない。最善手の着手後勝率が取れなければ接戦扱い（安全側）。
- S8 (d)（9段の終局処理の手）は spec どおり損失上限だけを見て、接戦の累計上限は掛けない（入れ替え (c) だけが累計を見る）。
- 終局帯の humanSL クエリのラベルは S11 と同じ `"parent hp"`（テストのスタブがラベルで応答を振り分ける）。
- 校正に段階1b（安全条件以外のつまみの掃引）を足した。ハーネス spec §6 の段階1〜3 だけでは spec §10.3・§12 が「選ぶ」と言う dominant_hp / natural_ratio / free_loss / close_drift_cap の境界線が描けないため。段階3 の強めの相手は spec §6 の2案のうち `--opponent strategy:human` で、**`human_kyu_rank=-8,modern_style=true` の上書きで 9段にする**（ハーネスは上書きの無いキーをユーザー設定から取り、ユーザー設定の `ai:human` は 8級）。
- 採否 (a) の「95% 上限」は `summarize --compare default enigma --conf 0.95` の値（ハーネスの既定 0.975 は2回見る停止規則用）。
- Task 16 の進み方を3通りに固定した（変える／据え置いて実戦確認へ／設計に戻る＝Task 17〜19 を実行せず止める）。どれでも決定を `veil13-campaign.md` にコミットする。9路・19路の既定値は spec の初期値のまま（GUI の概要・マニュアル・`ai-parameters.md` もそう書く）。
