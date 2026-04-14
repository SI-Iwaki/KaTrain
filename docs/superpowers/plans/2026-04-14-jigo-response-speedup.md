# Jigo 応答速度改善 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JigoStrategy の1手生成時間を 1秒 → 0.5秒以下に短縮する（Stage 1 クエリの `maxVisits` を 800 → 1 に削減）。

**Architecture:** Stage 1 クエリは `humanPolicy`（humanSL NN の root policy 出力）取得のみに使われており、探索 visits を増やしても値は不変。Stage 1 の `maxVisits` を 1 に下げて NN 評価1回に短縮する。Stage 2（クリーンスコア検証）は完全に現状維持して精度を保つ。

**Tech Stack:** Python 3.12, KaTrain (Kivy), KataGo v1.16.4 (TensorRT), katrain_debug CLI

**Spec:** `docs/superpowers/specs/2026-04-14-jigo-response-speedup-design.md`

---

## 前提

実装開始時点のファイル状態:

- `katrain/core/ai.py:879` に `"maxVisits": 800,` がある（Stage 1 override 内）
- `katrain/core/ai.py:923` に `"maxVisits": 600,` がある（Stage 2 override 内。**これは触らない**）

校正データ保存先（新規作成）: `docs/superpowers/specs/calibration-data/jigo-speedup/`

---

### Task 1: 校正データディレクトリ準備と事前 smoke test

**目的:** 変更前の時点で katrain_debug CLI が正常動作することを確認し、校正データ保存先を用意する。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/` (ディレクトリのみ)

- [ ] **Step 1: 校正データディレクトリを作成**

```bash
mkdir -p docs/superpowers/specs/calibration-data/jigo-speedup
```

- [ ] **Step 2: CLI が現在の ai.py で動作することを smoke test で確認**

```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf --move 30 --strategy jigo --output json 2>/dev/null | python -c "
import sys, json
d = json.loads(sys.stdin.read())
exp = d.get('explanation', '')
if exp.startswith('Jigo (mode='):
    print(f'OK (explanation={exp[:80]})')
else:
    print(f'FAIL: Stage 1 failed or humanPolicy missing (explanation={exp[:120]})')
"
```

期待結果: `OK`（humanPolicy が populate されている）

失敗時: CLI セットアップに問題あり。実装前提が崩れる。ユーザーに相談。

- [ ] **Step 3: Commit（ディレクトリ作成のみ。gitkeep で空コミット）**

```bash
# ディレクトリ保持用の .gitkeep を作成
echo "" > docs/superpowers/specs/calibration-data/jigo-speedup/.gitkeep
git add docs/superpowers/specs/calibration-data/jigo-speedup/.gitkeep
git commit -m "chore: jigo-speedup 校正データディレクトリを作成"
```

---

### Task 2: 変更前ベースライン batch_eval 測定（19路・白番）

**目的:** 現行 `maxVisits=800` の精度メトリック（Top1一致率・平均損失・Choice-vs-Median Gap・Post-98% Slack）を3run平均で取得する。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/before-white-run1.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/before-white-run2.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/before-white-run3.json`

- [ ] **Step 1: Run 1 を実行（19路白番、変更前）**

```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf \
  --strategy jigo \
  --batch \
  --player W \
  --output json \
  > docs/superpowers/specs/calibration-data/jigo-speedup/before-white-run1.json 2>/dev/null
```

期待所要時間: 約2-3分（jigo は argmax のため他戦略より速い）。

- [ ] **Step 2: Run 2 を実行**

```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf \
  --strategy jigo \
  --batch \
  --player W \
  --output json \
  > docs/superpowers/specs/calibration-data/jigo-speedup/before-white-run2.json 2>/dev/null
```

- [ ] **Step 3: Run 3 を実行**

```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf \
  --strategy jigo \
  --batch \
  --player W \
  --output json \
  > docs/superpowers/specs/calibration-data/jigo-speedup/before-white-run3.json 2>/dev/null
```

- [ ] **Step 4: 3run の集計値を確認**

```bash
python -c "
import json, statistics
runs = []
for i in (1,2,3):
    with open(f'docs/superpowers/specs/calibration-data/jigo-speedup/before-white-run{i}.json', encoding='utf-8') as f:
        runs.append(json.load(f))
for key in ['ai_top_move','ai_top5_move','mean_ptloss']:
    vals = [r['stats']['overall'][key] for r in runs]
    print(f'{key}: mean={statistics.mean(vals):.4f}, stdev={statistics.stdev(vals):.4f}, values={vals}')
# lambdago metrics (Choice-vs-Median Gap overall + Post-98% Slack W)
cvm_vals = [r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in runs]
print(f'cvm_gap_overall: mean={statistics.mean(cvm_vals):.4f}, values={cvm_vals}')
slack_w = [r['stats']['lambdago_metrics']['post_98_slack'].get('W') for r in runs]
slack_delta_w = [s['slack_delta'] for s in slack_w if s is not None]
if slack_delta_w:
    print(f'slack_delta_W: mean={statistics.mean(slack_delta_w):.4f}, values={slack_delta_w}')
"
```

期待結果: jigo は deterministic のため stdev は 0.001〜0.005 程度で極小。値をコピペで記録する。

- [ ] **Step 5: Commit（結果ファイル）**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/before-white-run*.json
git commit -m "chore(jigo-speedup): 変更前ベースライン(19路白番)を3run記録"
```

---

### Task 3: 変更前ベースライン batch_eval 測定（19路・黒番）

**目的:** 黒番でも同様にベースラインを記録（白番・黒番は視点が異なるため独立に測る）。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/before-black-run{1,2,3}.json`

- [ ] **Step 1: Run 1-3 を黒番で実行**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-black.sgf \
    --strategy jigo \
    --batch \
    --player B \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/before-black-run${i}.json 2>/dev/null
  echo "run${i} done"
done
```

- [ ] **Step 2: 3run の集計値を確認**

```bash
python -c "
import json, statistics
runs = []
for i in (1,2,3):
    with open(f'docs/superpowers/specs/calibration-data/jigo-speedup/before-black-run{i}.json', encoding='utf-8') as f:
        runs.append(json.load(f))
for key in ['ai_top_move','ai_top5_move','mean_ptloss']:
    vals = [r['stats']['overall'][key] for r in runs]
    print(f'{key}: mean={statistics.mean(vals):.4f}, stdev={statistics.stdev(vals):.4f}, values={vals}')
cvm_vals = [r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in runs]
print(f'cvm_gap_overall: mean={statistics.mean(cvm_vals):.4f}, values={cvm_vals}')
slack_b = [r['stats']['lambdago_metrics']['post_98_slack'].get('B') for r in runs]
slack_delta_b = [s['slack_delta'] for s in slack_b if s is not None]
if slack_delta_b:
    print(f'slack_delta_B: mean={statistics.mean(slack_delta_b):.4f}, values={slack_delta_b}')
"
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/before-black-run*.json
git commit -m "chore(jigo-speedup): 変更前ベースライン(19路黒番)を3run記録"
```

---

### Task 4: Stage 1 maxVisits を 1 に変更 + smoke test

**目的:** コード変更本体と、`humanPolicy` が `maxVisits=1` で populate されるかを即座に検証する。前提が崩れた場合は段階的に visits を上げる。

**Files:**
- Modify: `katrain/core/ai.py:879`

- [ ] **Step 1: `ai.py:879` を編集**

変更前（`katrain/core/ai.py:876-880`）:

```python
        stage1_override = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 800,
        }
```

変更後:

```python
        stage1_override = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 1,
        }
```

- [ ] **Step 2: smoke test で humanPolicy が populate されるか確認**

```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf --move 30 --strategy jigo --output json 2>/dev/null | python -c "
import sys, json
d = json.loads(sys.stdin.read())
exp = d.get('explanation', '')
if exp.startswith('Jigo (mode='):
    print(f'OK (explanation={exp[:80]})')
else:
    print(f'FAIL: Stage 1 failed or humanPolicy missing (explanation={exp[:120]})')
"
```

期待結果: `OK`

**もし `FAIL` もしくはエラーログに `Stage1 failed, falling back to KataGo top move` が出た場合:**

1. `ai.py:879` の `maxVisits` を `2` に上げて再テスト
2. それでも失敗なら `5`, `10` と段階的に上げる
3. 成功した最小値を採用
4. 採用値をこの Plan の「### Task 4 採用値メモ」に追記（下記 Step 3）

- [ ] **Step 3: 採用された maxVisits 値を記録**

確認した最小値（1 以外になった場合のみ）:

```
採用 maxVisits: 1（デフォルト）
# もし変更になった場合:
# 採用 maxVisits: N （理由: 1 では humanPolicy が populate されなかったため）
```

- [ ] **Step 4: Commit（コード変更）**

```bash
git add katrain/core/ai.py
git commit -m "perf(jigo): Stage 1 クエリの maxVisits を 800 から 1 に削減

humanPolicy は humanSL NN の root policy 出力で、探索 visits に不変。
Stage 1 は humanPolicy 取得専用のため 1 visit で十分。Stage 2（scoreLead
用クリーンクエリ）は 600 visits のまま維持して精度を完全保全する。
体感応答時間を 1秒 → 0.5秒以下に短縮することを目的とする。"
```

---

### Task 5: 変更後 batch_eval 測定（19路・白番）

**目的:** 変更後の Top1一致率・平均損失・Gap 指標が変更前と誤差範囲内であることを3run平均で検証。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/after-white-run{1,2,3}.json`

- [ ] **Step 1: Run 1-3 を白番で実行（変更後コード）**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf \
    --strategy jigo \
    --batch \
    --player W \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/after-white-run${i}.json 2>/dev/null
  echo "after white run${i} done"
done
```

**所要時間観察ポイント:** 3run の合計時間が変更前（Task 2）と比べて**有意に短くなっている**ことを体感で確認する（batch_eval は KataGo 1回起動・全手評価なので応答時間改善効果が見える）。

- [ ] **Step 2: 変更前後の集計値を比較**

```bash
python -c "
import json, statistics
def load(prefix):
    runs=[]
    for i in (1,2,3):
        with open(f'docs/superpowers/specs/calibration-data/jigo-speedup/{prefix}-run{i}.json', encoding='utf-8') as f:
            runs.append(json.load(f))
    return runs
before = load('before-white')
after = load('after-white')
for key in ['ai_top_move','ai_top5_move','mean_ptloss']:
    b = statistics.mean([r['stats']['overall'][key] for r in before])
    a = statistics.mean([r['stats']['overall'][key] for r in after])
    diff = a - b
    print(f'{key}: before={b:.4f}, after={a:.4f}, diff={diff:+.4f}')
# Choice-vs-Median Gap (overall) 比較
b_cvm = statistics.mean([r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in before])
a_cvm = statistics.mean([r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in after])
print(f'cvm_gap_overall: before={b_cvm:.4f}, after={a_cvm:.4f}, diff={a_cvm - b_cvm:+.4f}')
"
```

**合格基準（白番）:**

| 指標 | 合格範囲 |
|---|---|
| `ai_top_move` | 差 ±0.02（±2pt） |
| `ai_top5_move` | 差 ±0.02 |
| `mean_ptloss` | 差 ±0.1（目） |
| `cvm_gap_overall` | 差 ±0.1（目） |

**合格基準を超える退行がある場合:** `ai.py:879` の `maxVisits` を段階的に上げて再計測（Task 4 Step 2 と同じ手順）。

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/after-white-run*.json
git commit -m "chore(jigo-speedup): 変更後(19路白番)を3run記録"
```

---

### Task 6: 変更後 batch_eval 測定（19路・黒番）

**目的:** 黒番でも合格基準を満たすことを確認。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/after-black-run{1,2,3}.json`

- [ ] **Step 1: Run 1-3 を黒番で実行**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-black.sgf \
    --strategy jigo \
    --batch \
    --player B \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/after-black-run${i}.json 2>/dev/null
  echo "after black run${i} done"
done
```

- [ ] **Step 2: 変更前後の集計値を比較**

```bash
python -c "
import json, statistics
def load(prefix):
    runs=[]
    for i in (1,2,3):
        with open(f'docs/superpowers/specs/calibration-data/jigo-speedup/{prefix}-run{i}.json', encoding='utf-8') as f:
            runs.append(json.load(f))
    return runs
before = load('before-black')
after = load('after-black')
for key in ['ai_top_move','ai_top5_move','mean_ptloss']:
    b = statistics.mean([r['stats']['overall'][key] for r in before])
    a = statistics.mean([r['stats']['overall'][key] for r in after])
    diff = a - b
    print(f'{key}: before={b:.4f}, after={a:.4f}, diff={diff:+.4f}')
b_cvm = statistics.mean([r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in before])
a_cvm = statistics.mean([r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in after])
print(f'cvm_gap_overall: before={b_cvm:.4f}, after={a_cvm:.4f}, diff={a_cvm - b_cvm:+.4f}')
"
```

合格基準は Task 5 Step 2 と同じ（白番と同一基準）。

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/after-black-run*.json
git commit -m "chore(jigo-speedup): 変更後(19路黒番)を3run記録"
```

---

### Task 7: 実対局での体感速度検証（19路）

**目的:** 実際の対局（人間 vs jigoAI）で「相手が打ってから AI が打つまで」の体感時間を測定し、目標0.5s以下を満たすか確認する。

**Files:**
- なし（手動検証）

- [ ] **Step 1: KaTrain を起動**

```bash
python -m katrain
```

- [ ] **Step 2: 19路で人間 vs AI(jigo 9段) 対局を開始**

  - AI 設定: `ai:jigo`
  - 人間番でプレイ
  - `C:\Users\iwaki\.katrain\config.json` の `debug_level` は **0 のまま**でよい（本タスクは体感計測）

- [ ] **Step 3: 10手分の応答時間を実測**

手元のストップウォッチ（スマホ可）で、相手が打ち終わってから AI が石を置くまでの時間を計測:

| 手番 | 計測時間(秒) |
|---|---|
| AI 1手目 | ___ |
| AI 2手目 | ___ |
| AI 3手目 | ___ |
| AI 4手目 | ___ |
| AI 5手目 | ___ |
| AI 6手目 | ___ |
| AI 7手目 | ___ |
| AI 8手目 | ___ |
| AI 9手目 | ___ |
| AI 10手目 | ___ |
| **平均** | ___ |

**合格基準:** 平均 0.5秒 以下。

- [ ] **Step 4: 13路でも同じ対局を実施**

AI 設定を 13路に切り替えて、同様に10手計測。目標: 19路と同等かさらに速い。

- [ ] **Step 5: 結果を記録**

---

### Task 8: 最終結果サマリを記録してコミット

**目的:** 3run平均・体感時間・採用 maxVisits 値・合否判定を1つの markdown にまとめて、将来参照できるようにする。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/jigo-speedup-results-20260414.md`

- [ ] **Step 1: 結果 markdown を作成**

以下の内容で `jigo-speedup-results-20260414.md` を新規作成（Task 5-7 の実測値を埋める）:

```markdown
# Jigo 応答速度改善 校正結果（2026-04-14）

## 変更概要

`katrain/core/ai.py:879` の Stage 1 `maxVisits`: **800 → 1**

Spec: `docs/superpowers/specs/2026-04-14-jigo-response-speedup-design.md`
Plan: `docs/superpowers/plans/2026-04-14-jigo-response-speedup.md`

## 採用 maxVisits

- 採用値: **1**（1 で humanPolicy が populate されることを smoke test で確認）

## 精度回帰（3run平均）

### 19路・白番（`jigo-vs-3dan-20260413-white.sgf`）

| 指標 | 変更前 | 変更後 | 差分 | 合否 |
|---|---|---|---|---|
| Top1 一致率 | _ | _ | _ | _ |
| Top5 一致率 | _ | _ | _ | _ |
| 平均損失 | _ | _ | _ | _ |

### 19路・黒番（`jigo-vs-3dan-20260413-black.sgf`）

| 指標 | 変更前 | 変更後 | 差分 | 合否 |
|---|---|---|---|---|
| Top1 一致率 | _ | _ | _ | _ |
| Top5 一致率 | _ | _ | _ | _ |
| 平均損失 | _ | _ | _ | _ |

## 体感応答時間（実対局）

### 19路

- 10手平均: _ 秒
- 合否: _

### 13路

- 10手平均: _ 秒
- 合否: _

## 結論

- [ ] 精度回帰なし（3run平均で全指標が合格範囲内）
- [ ] 体感応答時間が目標（0.5秒以下）を達成
- [ ] Stage 2 失敗フォールバックは発生していない（ログ確認済み）

## 残タスク

- 案C（Stage 2 を既定解析で置換）の実現可能性検証は別タスクで保留中
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/jigo-speedup-results-20260414.md
git commit -m "docs(jigo-speedup): 校正結果サマリ（20260414）を追加"
```

---

### Task 9: .claude/rules/ai-parameters.md の更新

**目的:** エンジン設定セクションの Stage 1 maxVisits 記述を更新。**このファイルは Edit が拒否されることがあるためサブエージェント経由で編集する**（CLAUDE.md 記載ルール）。

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（エンジン設定テーブル内）

- [ ] **Step 1: サブエージェントに編集を委任**

Agent tool（general-purpose）を起動し、以下のプロンプトを渡す:

> `.claude/rules/ai-parameters.md` の「## エンジン設定（maxVisits）」テーブルと、その直下のコメント行を以下のように編集してください。
>
> **変更前（現行）:**
> ```
> | ai.py `override_settings["maxVisits"]` | 800 | Stage1: HumanSL着手選択 |
> ```
>
> **変更後:**
> ```
> | ai.py `override_settings["maxVisits"]` (HumanStyle/Fighting/Siege/Hunt) | 800 | Stage1: HumanSL着手選択 |
> | ai.py `stage1_override["maxVisits"]` (Jigo) | 1 | Stage1: humanPolicy 取得のみ（humanSL NN の root policy 出力で visits 不変） |
> ```
>
> 編集完了後、`git add .claude/rules/ai-parameters.md && git commit -m "docs(rules): Jigo の Stage 1 maxVisits を1に更新"` でコミットしてください。

- [ ] **Step 2: 編集結果を確認**

```bash
git log --oneline -1 .claude/rules/ai-parameters.md
```

直近コミットが上記メッセージでなされていれば OK。

---

### Task 10: CLAUDE.md の現在パラメータ参照を確認（必要なら更新）

**目的:** CLAUDE.md から参照される Jigo パラメータ記述に maxVisits 関連があれば同期する。

**Files:**
- Read: `katrain/CLAUDE.md`（またはプロジェクトルートの `CLAUDE.md`）

- [ ] **Step 1: CLAUDE.md の Jigo 関連記述を確認**

```bash
grep -n -i "jigo\|maxVisits" CLAUDE.md | head -20
```

- [ ] **Step 2: Stage 1 maxVisits について記述があれば、ai-parameters.md と同じ内容に更新**

記述がなければスキップ（ai-parameters.md 側で管理されているため）。

- [ ] **Step 3: 変更があった場合のみ Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): Jigo Stage 1 maxVisits 記述を同期"
```

---

## 完了条件

- [ ] Task 8 の結果 markdown で全項目が「合格」
- [ ] 実対局で体感応答速度が改善していることをユーザーが確認
- [ ] 精度メトリック差分が合格範囲内
- [ ] 関連ドキュメント（`.claude/rules/ai-parameters.md`）が更新済み

## ロールバック手順

問題発生時は `katrain/core/ai.py:879` の `"maxVisits": 1,` を `"maxVisits": 800,` に戻すだけ。他のコード変更はない。

```bash
# 簡易ロールバック
git revert <該当コミットのハッシュ>
```

## 残タスク（完了後も保留）

- タスク #5: 案C（Stage 2 を既定解析 `cn.analysis` で置換）の実現可能性検証。案A 適用後もさらに短縮したい場合に着手。
