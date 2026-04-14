# Jigo Stage 2 既定解析置換（案C）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `JigoStrategy.generate_move()` の Stage 2（クリーン scoreLead クエリ, 600 visits）を、既定解析 (`self.cn.analysis`) で置換し、1手あたりのクエリを 1本に削減する（特に 13路で追加の応答時間短縮）。

**Architecture:** `wait_for_analysis()` 完了時点で `cn.analysis` には既定解析の moveInfos と rootInfo が揃っており、Stage 2 で必要な scoreLead 情報をすべて含む。これを `score_analysis = {"moveInfos": ..., "rootInfo": ...}` の形に整形して既存ロジックにそのまま渡す。trade-off は visits +33%（800 vs 600）と wideRootNoise 0.04（vs クリーン 0.0）の小ノイズで、校正で許容範囲を確認する。

**Tech Stack:** Python 3.12, KaTrain (Kivy), KataGo v1.16.4 (TensorRT), katrain_debug CLI

**Spec:** `docs/superpowers/specs/2026-04-14-jigo-stage2-default-analysis-design.md`

**前提:** 案A 適用済（コミット `024e4b1`、Stage 1 maxVisits=1）

---

## ファイル構成

| 種別 | パス | 役割 |
|---|---|---|
| Modify | `katrain/core/ai.py` | `JigoStrategy.generate_move()` の Stage 2 ブロック置換 |
| Create | `docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf` | 13路校正 SGF（92手, B評価） |
| Create | `docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game2.sgf` | 13路校正 SGF（86手, W評価） |
| Create | `docs/superpowers/specs/calibration-data/jigo-speedup/planC-13ro-before-{game1,game2}-run{1,2,3}.json` | 13路 before --batch JSON × 6 |
| Create | `docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-{19ro-white,19ro-black,13ro-game1,13ro-game2}-run{1,2,3}.json` | After --batch JSON × 12 |
| Create | `docs/superpowers/specs/calibration-data/jigo-speedup/planC-results-20260414.md` | 結果サマリ |
| Modify | `.claude/rules/ai-parameters.md` | エンジン設定テーブルの Stage 2 行更新 |

---

### Task 1: 13路校正 SGF の前処理（KaTrainログから main-line 化コピー）

**目的:** `KaTrainログ` ディレクトリの 13路 SGF 2局を、`clean_sgf_main_line.py` で main-line 化して校正データディレクトリに配置する。KaTrain 保存 SGF は variation 多数で `node.children[0]` traversal が短い分岐に陥るため、前処理が必須（CLAUDE.md「やってはいけないこと」記載済）。

**Files:**
- Read: `C:\Users\iwaki\Documents\KaTrainログ\KaTrain_人間 (通常対局) vs AI (力戦派) 2026-04-01 02 17 40.sgf`
- Read: `C:\Users\iwaki\Documents\KaTrainログ\KaTrain_人間 (通常対局) vs AI (力戦派) 2026-04-01 19 08 44.sgf`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game2.sgf`

- [ ] **Step 1: game1（92手）を main-line 化してコピー**

```bash
cd C:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1
PYTHONIOENCODING=utf-8 python docs/superpowers/specs/calibration-data/clean_sgf_main_line.py \
  "C:/Users/iwaki/Documents/KaTrainログ/KaTrain_人間 (通常対局) vs AI (力戦派) 2026-04-01 02 17 40.sgf" \
  docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf
```

期待出力（stderr）: `Wrote 92 main-line moves to ...`（手数は若干前後する可能性あり、80手以上なら可）

- [ ] **Step 2: game2（86手）を main-line 化してコピー**

```bash
PYTHONIOENCODING=utf-8 python docs/superpowers/specs/calibration-data/clean_sgf_main_line.py \
  "C:/Users/iwaki/Documents/KaTrainログ/KaTrain_人間 (通常対局) vs AI (力戦派) 2026-04-01 19 08 44.sgf" \
  docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game2.sgf
```

期待出力: `Wrote 86 main-line moves to ...`

- [ ] **Step 3: 盤面サイズと手数を検証**

```bash
python -c "
import re
for f in ['katrain-13ro-20260401-game1.sgf', 'katrain-13ro-20260401-game2.sgf']:
    p = f'docs/superpowers/specs/calibration-data/jigo-speedup/{f}'
    s = open(p, encoding='utf-8').read()
    sz = re.search(r'SZ\[(\d+)\]', s).group(1)
    moves = len(re.findall(r';[BW]\[', s))
    print(f'{f}: {sz}x{sz}, {moves} moves')
"
```

期待出力:
```
katrain-13ro-20260401-game1.sgf: 13x13, 92 moves
katrain-13ro-20260401-game2.sgf: 13x13, 86 moves
```

合格基準: 両ファイルとも `13x13` で手数 80 以上。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf \
        docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game2.sgf
git commit -m "$(cat <<'EOF'
chore(jigo-speedup): 13路校正 SGF を main-line 化してコピー

KaTrainログから 2026-04-01 の人間vs力戦派 13路対局2局を
clean_sgf_main_line.py で前処理。案C の 13路 batch_eval 校正用。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 13路 before ベースライン batch_eval（案A適用済の現行コード）

**目的:** 案C 適用前（コミット `024e4b1` Stage 1 maxVisits=1, Stage 2 600 visits クリーン）の 13路 精度ベースラインを 3run 平均で取得。19路 before は既存 `jigo-speedup-results-20260414.md` の "after" データ流用のため新規取得不要。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/planC-13ro-before-game1-run{1,2,3}.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/planC-13ro-before-game2-run{1,2,3}.json`

**所要時間目安:** 13路 1 SGF × 3 run ≒ 6-9分（jigo は argmax で速い）。2 SGF 計 12-18分。

- [ ] **Step 1: game1（B評価）を 3run 実行**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf \
    --strategy jigo \
    --batch \
    --player B \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/planC-13ro-before-game1-run${i}.json 2>/dev/null
  echo "13ro game1 before run${i} done"
done
```

- [ ] **Step 2: game2（W評価）を 3run 実行**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game2.sgf \
    --strategy jigo \
    --batch \
    --player W \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/planC-13ro-before-game2-run${i}.json 2>/dev/null
  echo "13ro game2 before run${i} done"
done
```

- [ ] **Step 3: 3run の集計値を確認（両 SGF）**

```bash
python -c "
import json, statistics
def load(prefix):
    runs=[]
    for i in (1,2,3):
        with open(f'docs/superpowers/specs/calibration-data/jigo-speedup/{prefix}-run{i}.json', encoding='utf-8') as f:
            runs.append(json.load(f))
    return runs
for label, prefix in [('game1 (B)', 'planC-13ro-before-game1'), ('game2 (W)', 'planC-13ro-before-game2')]:
    runs = load(prefix)
    print(f'--- {label} ---')
    for key in ['ai_top_move','ai_top5_move','mean_ptloss']:
        vals = [r['stats']['overall'][key] for r in runs]
        print(f'  {key}: mean={statistics.mean(vals):.4f}, stdev={statistics.stdev(vals):.4f}')
    cvm = [r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in runs]
    print(f'  cvm_gap_overall: mean={statistics.mean(cvm):.4f}, stdev={statistics.stdev(cvm):.4f}')
"
```

期待: stdev は jigo deterministic のため 0.001〜0.05 程度。値を控えておく（Task 6 の比較で使用）。

- [ ] **Step 4: フォールバック発生がないことを確認**

```bash
grep -l "cn.analysis incomplete\|Stage1 failed" docs/superpowers/specs/calibration-data/jigo-speedup/planC-13ro-before-*.json || echo "No fallback detected (OK)"
```

期待出力: `No fallback detected (OK)`（このタスクは案C 適用前のため、`cn.analysis incomplete` は理論的に発生しないが念のため確認）

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/planC-13ro-before-*.json
git commit -m "$(cat <<'EOF'
chore(jigo-speedup): 案C 13路 before ベースライン(2 SGF × 3 run)を記録

案A 適用済の現行コード(024e4b1)で 13路 game1(B評価) と
game2(W評価) の精度メトリックを取得。19路 before は既存
jigo-speedup-results-20260414.md 流用のため新規取得不要。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 案C コード変更（Stage 2 を cn.analysis で置換）+ smoke test

**目的:** `JigoStrategy.generate_move()` の Stage 2 ブロックを `self.cn.analysis` 参照に置換。即座に smoke test で正常動作（フォールバック未発動）を確認。

**Files:**
- Modify: `katrain/core/ai.py` (~920-956 行)

- [ ] **Step 1: `ai.py` の Stage 2 ブロックを置換**

変更前（`katrain/core/ai.py:920-956`）:

```python
        # ---- Stage 2: クリーンクエリ（scoreLead 用） ----
        stage2_override = {
            "ignorePreRootHistory": False,
            "maxVisits": 600,
            "wideRootNoise": 0.0,
        }
        stage2_analysis = None
        stage2_error = False

        def _set_stage2(a, partial):
            nonlocal stage2_analysis
            if not partial:
                stage2_analysis = a

        def _err_stage2(a):
            nonlocal stage2_error
            stage2_error = True
            self.game.katrain.log(f"[JigoStrategy] Stage2 error: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=_set_stage2, error_callback=_err_stage2,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=False,
            extra_settings=stage2_override,
        )
        while not (stage2_error or stage2_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        # Stage 2 失敗時は Stage 1 にフォールバック
        if stage2_error or not stage2_analysis:
            self.last_decision_info["score_lead_biased"] = True
            self.game.katrain.log(
                "[JigoStrategy] Stage2 failed, using Stage1 moveInfos (biased)", OUTPUT_DEBUG
            )
            score_analysis = stage1_analysis
        else:
            score_analysis = stage2_analysis
```

変更後（同じ範囲を以下で置換）:

```python
        # ---- Stage 2 を既定解析 (cn.analysis) で置換 — 案C ----
        # wait_for_analysis() で analysis_complete=True 保証済（generate_move 冒頭）
        # trade-off: visits 600→800 (+33%), wideRootNoise 0.0→0.04 (小ノイズ)
        move_dicts = list(self.cn.analysis.get("moves", {}).values())
        root_info = self.cn.analysis.get("root")
        if move_dicts and root_info:
            score_analysis = {
                "moveInfos": move_dicts,
                "rootInfo": root_info,
            }
        else:
            self.last_decision_info["score_lead_biased"] = True
            self.game.katrain.log(
                "[JigoStrategy] cn.analysis incomplete, using Stage1 (biased)", OUTPUT_DEBUG
            )
            score_analysis = stage1_analysis
```

注意: 上記の 920 行から 956 行までを完全に置換する。後続の `move_infos = score_analysis.get("moveInfos", [])` 以降は変更不要。

- [ ] **Step 2: black フォーマット適用**

```bash
black katrain/core/ai.py
```

期待出力: `1 file left unchanged.` または `reformatted katrain/core/ai.py`（line-length=120 のため大幅変更は出ない見込み）

- [ ] **Step 3: 構文回帰テスト**

```bash
pytest tests/ --ignore=tests/test_ai.py -q 2>&1 | tail -20
```

期待: 既存テストが全て pass（`test_ai.py` は humanSL モデル必要のため除外）。

- [ ] **Step 4: smoke test（19路）— `cn.analysis` が score_analysis として正しく機能するか確認**

```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf \
  --move 30 --strategy jigo --output json 2>/dev/null | python -c "
import sys, json
d = json.loads(sys.stdin.read())
exp = d.get('explanation', '')
ok_started = exp.startswith('Jigo (mode=')
no_biased = 'biased' not in exp.lower()
no_failed = 'failed' not in exp.lower()
print(f'explanation: {exp[:120]}')
print(f'started OK: {ok_started}')
print(f'no biased fallback: {no_biased}')
print(f'no Stage1 fail: {no_failed}')
print('PASS' if (ok_started and no_biased and no_failed) else 'FAIL')
"
```

期待出力: `PASS`

**`FAIL` が出た場合の切り分け:**

- `cn.analysis incomplete` ログが出ていれば、データ構造アクセスが想定外。`game_node.py:256` 周りで `self.analysis["root"]` と `self.analysis["moves"]` の構造を再確認
- `Stage1 failed` ログなら案A 由来の問題で、案C とは独立（別タスクで対処）

- [ ] **Step 5: smoke test（13路）— 13路 SGF でも正常動作確認**

```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf \
  --move 20 --strategy jigo --output json 2>/dev/null | python -c "
import sys, json
d = json.loads(sys.stdin.read())
exp = d.get('explanation', '')
print(f'explanation: {exp[:120]}')
print('PASS' if exp.startswith('Jigo (mode=') and 'biased' not in exp.lower() else 'FAIL')
"
```

期待出力: `PASS`

- [ ] **Step 6: Commit**

```bash
git add katrain/core/ai.py
git commit -m "$(cat <<'EOF'
perf(jigo): Stage 2 を既定解析 cn.analysis で置換

案C 適用。1手あたりのクエリを Stage 1(maxVisits=1) 1本のみに削減。
score_analysis は cn.analysis の moves/root から構築。
trade-off: visits 600→800 (+33%), wideRootNoise 0.0→0.04 (小ノイズ)。
精度は校正で許容範囲を確認する。

Spec: docs/superpowers/specs/2026-04-14-jigo-stage2-default-analysis-design.md
Plan: docs/superpowers/plans/2026-04-14-jigo-stage2-default-analysis.md

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 19路 after batch_eval（案C 適用後）

**目的:** 案C 適用後の 19路 精度メトリックを 3run 平均で取得。Task 6 で既存 19路 before（`jigo-speedup-results-20260414.md` "after" 列）と比較する。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-19ro-white-run{1,2,3}.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-19ro-black-run{1,2,3}.json`

**所要時間目安:** 19路白(60手) × 3run ≒ 9-12分、19路黒(134手) × 3run ≒ 18-25分。計 30-40分。

- [ ] **Step 1: 19路白番（W評価）を 3run 実行**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf \
    --strategy jigo \
    --batch \
    --player W \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-19ro-white-run${i}.json 2>/dev/null
  echo "19ro white after run${i} done"
done
```

- [ ] **Step 2: 19路黒番（B評価）を 3run 実行**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-black.sgf \
    --strategy jigo \
    --batch \
    --player B \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-19ro-black-run${i}.json 2>/dev/null
  echo "19ro black after run${i} done"
done
```

- [ ] **Step 3: 集計値を確認**

```bash
python -c "
import json, statistics
def load(prefix):
    runs=[]
    for i in (1,2,3):
        with open(f'docs/superpowers/specs/calibration-data/jigo-speedup/{prefix}-run{i}.json', encoding='utf-8') as f:
            runs.append(json.load(f))
    return runs
for label, prefix in [('19ro W', 'planC-after-19ro-white'), ('19ro B', 'planC-after-19ro-black')]:
    runs = load(prefix)
    print(f'--- {label} ---')
    for key in ['ai_top_move','ai_top5_move','mean_ptloss']:
        vals = [r['stats']['overall'][key] for r in runs]
        print(f'  {key}: mean={statistics.mean(vals):.4f}, stdev={statistics.stdev(vals):.4f}')
    cvm = [r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in runs]
    print(f'  cvm_gap_overall: mean={statistics.mean(cvm):.4f}')
    color = 'W' if 'white' in prefix else 'B'
    slack = [r['stats']['lambdago_metrics']['post_98_slack'].get(color) for r in runs]
    slack_d = [s['slack_delta'] for s in slack if s is not None]
    if slack_d:
        print(f'  slack_delta_{color}: mean={statistics.mean(slack_d):.4f}')
"
```

- [ ] **Step 4: フォールバック発生なしを確認**

```bash
grep -l "cn.analysis incomplete\|Stage1 failed" docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-19ro-*.json || echo "No fallback detected (OK)"
```

期待出力: `No fallback detected (OK)`

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-19ro-*.json
git commit -m "$(cat <<'EOF'
chore(jigo-speedup): 案C 適用後の 19路 batch_eval(白/黒 × 3 run)を記録

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 13路 after batch_eval（案C 適用後）

**目的:** 案C 適用後の 13路 精度メトリックを 3run 平均で取得。Task 2 のベースラインと比較する。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-13ro-game1-run{1,2,3}.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-13ro-game2-run{1,2,3}.json`

**所要時間目安:** 13路 2 SGF × 3 run ≒ 12-18分。

- [ ] **Step 1: game1（B評価）を 3run 実行**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf \
    --strategy jigo \
    --batch \
    --player B \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-13ro-game1-run${i}.json 2>/dev/null
  echo "13ro game1 after run${i} done"
done
```

- [ ] **Step 2: game2（W評価）を 3run 実行**

```bash
for i in 1 2 3; do
  PYTHONIOENCODING=utf-8 python -m katrain_debug \
    --sgf docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game2.sgf \
    --strategy jigo \
    --batch \
    --player W \
    --output json \
    > docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-13ro-game2-run${i}.json 2>/dev/null
  echo "13ro game2 after run${i} done"
done
```

- [ ] **Step 3: 集計値を確認**

```bash
python -c "
import json, statistics
def load(prefix):
    runs=[]
    for i in (1,2,3):
        with open(f'docs/superpowers/specs/calibration-data/jigo-speedup/{prefix}-run{i}.json', encoding='utf-8') as f:
            runs.append(json.load(f))
    return runs
for label, prefix, color in [('13ro game1 (B)', 'planC-after-13ro-game1', 'B'), ('13ro game2 (W)', 'planC-after-13ro-game2', 'W')]:
    runs = load(prefix)
    print(f'--- {label} ---')
    for key in ['ai_top_move','ai_top5_move','mean_ptloss']:
        vals = [r['stats']['overall'][key] for r in runs]
        print(f'  {key}: mean={statistics.mean(vals):.4f}, stdev={statistics.stdev(vals):.4f}')
    cvm = [r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in runs]
    print(f'  cvm_gap_overall: mean={statistics.mean(cvm):.4f}')
    slack = [r['stats']['lambdago_metrics']['post_98_slack'].get(color) for r in runs]
    slack_d = [s['slack_delta'] for s in slack if s is not None]
    if slack_d:
        print(f'  slack_delta_{color}: mean={statistics.mean(slack_d):.4f}')
"
```

- [ ] **Step 4: フォールバック発生なしを確認**

```bash
grep -l "cn.analysis incomplete\|Stage1 failed" docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-13ro-*.json || echo "No fallback detected (OK)"
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/planC-after-13ro-*.json
git commit -m "$(cat <<'EOF'
chore(jigo-speedup): 案C 適用後の 13路 batch_eval(game1/game2 × 3 run)を記録

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: PASS/FAIL 判定（19路 + 13路 全比較）

**目的:** 全4 SGF の before/after 比較を一括で行い、合格基準を全指標が満たすか判定する。FAIL の場合はロールバックを検討。

**Files:**
- なし（既存データの集計のみ）

- [ ] **Step 1: 19路 before データを `jigo-speedup-results-20260414.md` から読み出す**

19路 before（案A 適用後の数値、`jigo-speedup-results-20260414.md` の "変更後" 列）:

| 指標 | 19路 W | 19路 B |
|---|---|---|
| `ai_top_move` | 0.1228 | 0.3089 |
| `ai_top5_move` | 0.2906 | 0.4658 |
| `mean_ptloss` | 1.5237 | 1.2743 |
| `cvm_gap` | -0.5073 | -1.6516 |
| `slack_delta_*` | 0.9773 (W) | 0.5178 (B) |

これを Python 辞書で定数化（次の Step で使用）。

- [ ] **Step 2: 全 SGF の before/after 比較スクリプトを実行**

```bash
python -c "
import json, statistics

# 19路 before（jigo-speedup-results-20260414.md の数値、案A適用後）
before_19ro = {
    'white': {'ai_top_move': 0.1228, 'ai_top5_move': 0.2906, 'mean_ptloss': 1.5237, 'cvm_gap': -0.5073},
    'black': {'ai_top_move': 0.3089, 'ai_top5_move': 0.4658, 'mean_ptloss': 1.2743, 'cvm_gap': -1.6516},
}

def load_runs(prefix):
    runs = []
    for i in (1, 2, 3):
        with open(f'docs/superpowers/specs/calibration-data/jigo-speedup/{prefix}-run{i}.json', encoding='utf-8') as f:
            runs.append(json.load(f))
    return runs

def aggregate(runs):
    stats = {}
    for key in ['ai_top_move', 'ai_top5_move', 'mean_ptloss']:
        vals = [r['stats']['overall'][key] for r in runs]
        stats[key] = {'mean': statistics.mean(vals), 'stdev': statistics.stdev(vals)}
    cvm = [r['stats']['lambdago_metrics']['choice_vs_median']['overall']['mean'] for r in runs]
    stats['cvm_gap'] = {'mean': statistics.mean(cvm), 'stdev': statistics.stdev(cvm)}
    return stats

THRESHOLDS = {'ai_top_move': 0.02, 'ai_top5_move': 0.02, 'mean_ptloss': 0.1, 'cvm_gap': 0.1}

# 19路 比較
print('=' * 60)
print('19路 W (after vs existing baseline)')
print('=' * 60)
after = aggregate(load_runs('planC-after-19ro-white'))
for key, thr in THRESHOLDS.items():
    b = before_19ro['white'][key]
    a = after[key]['mean']
    sd = after[key]['stdev']
    diff = a - b
    sigma = abs(diff) / sd if sd > 1e-6 else float('inf')
    pass_thr = abs(diff) <= thr
    pass_sigma = sigma <= 2.0
    mark = 'PASS' if pass_thr or pass_sigma else 'FAIL'
    note = '' if pass_thr else f' (sigma={sigma:.2f})'
    print(f'  {key}: before={b:.4f}, after={a:.4f}, diff={diff:+.4f}, thr=±{thr} -> {mark}{note}')

print()
print('=' * 60)
print('19路 B (after vs existing baseline)')
print('=' * 60)
after = aggregate(load_runs('planC-after-19ro-black'))
for key, thr in THRESHOLDS.items():
    b = before_19ro['black'][key]
    a = after[key]['mean']
    sd = after[key]['stdev']
    diff = a - b
    sigma = abs(diff) / sd if sd > 1e-6 else float('inf')
    pass_thr = abs(diff) <= thr
    pass_sigma = sigma <= 2.0
    mark = 'PASS' if pass_thr or pass_sigma else 'FAIL'
    note = '' if pass_thr else f' (sigma={sigma:.2f})'
    print(f'  {key}: before={b:.4f}, after={a:.4f}, diff={diff:+.4f}, thr=±{thr} -> {mark}{note}')

# 13路 比較（before も新規測定）
for label, game_id in [('13ro game1 (B)', 'game1'), ('13ro game2 (W)', 'game2')]:
    print()
    print('=' * 60)
    print(label)
    print('=' * 60)
    before = aggregate(load_runs(f'planC-13ro-before-{game_id}'))
    after = aggregate(load_runs(f'planC-after-13ro-{game_id}'))
    for key, thr in THRESHOLDS.items():
        b = before[key]['mean']
        a = after[key]['mean']
        sd = max(before[key]['stdev'], after[key]['stdev'])
        diff = a - b
        sigma = abs(diff) / sd if sd > 1e-6 else float('inf')
        pass_thr = abs(diff) <= thr
        pass_sigma = sigma <= 2.0
        mark = 'PASS' if pass_thr or pass_sigma else 'FAIL'
        note = '' if pass_thr else f' (sigma={sigma:.2f})'
        print(f'  {key}: before={b:.4f}, after={a:.4f}, diff={diff:+.4f}, thr=±{thr} -> {mark}{note}')
"
```

**合格基準:**

| メトリック | 合格範囲 | 統計的補正 |
|---|---|---|
| `ai_top_move` | ±0.02 | 2σ 以内なら受容 |
| `ai_top5_move` | ±0.02 | 2σ 以内なら受容 |
| `mean_ptloss` | ±0.1 目 | 2σ 以内なら受容 |
| `cvm_gap` | ±0.1 目 | 2σ 以内なら受容（プラン A の白判定と整合） |

**全指標が PASS（閾値内 OR 2σ 以内）であれば案C 採用確定。**

- [ ] **Step 3: FAIL の場合の対処判断**

| FAIL ケース | 対処 |
|---|---|
| 1指標のみ FAIL かつ 19路/13路 片方のみ | 残タスクの記録に留めて採用判断（プラン A 前例あり） |
| 複数指標 FAIL または mean_ptloss > 0.15 退行 | **案C 不採用**。Task 3 のコミットを `git revert` してロールバック |
| `cvm_gap` のみ大幅退行（鋭手除外への noise 影響） | 鋭手除外の閾値緩和（`+0.5` → `+0.7`）を別タスクで検討 |

**判断結果を Task 8 の結果サマリに記録する。**

---

### Task 7: 実対局体感速度検証（19路・13路）

**目的:** 実際の人間 vs jigoAI 対局で、案C 適用前（プラン A 適用済の現行）と適用後の応答時間差を体感確認。特に 13路で改善が出るか。

**Files:**
- なし（手動検証）

- [ ] **Step 1: KaTrain を起動**

```bash
python -m katrain
```

- [ ] **Step 2: 19路で 5-10手の応答時間を計測**

設定: AI = `ai:jigo`, 9段, 通常設定。手元のストップウォッチで計測。

| 手番 | 計測時間(秒) |
|---|---|
| AI 1手目 | ___ |
| AI 2手目 | ___ |
| ... | ___ |
| **平均** | ___ |

期待: プラン A 適用後の 0.5秒以下からさらに短縮（0.2-0.3秒程度）。

- [ ] **Step 3: 13路で 5-10手の応答時間を計測**

| 手番 | 計測時間(秒) |
|---|---|
| AI 1手目 | ___ |
| ... | ___ |
| **平均** | ___ |

期待: プラン A では「体感差わずか」だった 13路で **明確な短縮** が出る。

- [ ] **Step 4: KaTrain ログでフォールバック発生がないことを確認**

```bash
grep -i "cn.analysis incomplete\|Stage1 failed\|Stage2 failed" "C:/Users/iwaki/.katrain/katrain.log" 2>/dev/null | tail -20 || echo "No fallback in recent log"
```

期待: フォールバックログなし。

---

### Task 8: 結果サマリ markdown 作成 + コミット

**目的:** Task 4-7 の実測値を1つの markdown にまとめて将来参照できるようにする。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/planC-results-20260414.md`

- [ ] **Step 1: 結果 markdown を作成（Task 4-7 の数値を埋める）**

以下のテンプレートを `planC-results-20260414.md` として新規作成。`_` の箇所は実測値を埋める。

```markdown
# Jigo Stage 2 既定解析置換（案C）校正結果（2026-04-14）

## 変更概要

`katrain/core/ai.py` `JigoStrategy.generate_move()` の Stage 2 ブロック（620 visits クリーンクエリ）を `self.cn.analysis` 参照に置換。1手あたりのクエリ削減（Stage 1 のみ）で追加の応答時間短縮を狙う。

- Spec: `docs/superpowers/specs/2026-04-14-jigo-stage2-default-analysis-design.md`
- Plan: `docs/superpowers/plans/2026-04-14-jigo-stage2-default-analysis.md`
- コード変更コミット: `_______`
- 前提コミット: `024e4b1`（案A 適用済）

## trade-off

| 軸 | 案A 後 (Stage 2) | 案C (cn.analysis) |
|---|---|---|
| visits | 600 | 800 (ユーザー max_visits 設定) |
| wideRootNoise | 0.0 | 0.04 |
| クエリ数/手 | 2 | 1 |

## 精度回帰（3run 平均）

### 19路 W（`jigo-vs-3dan-20260413-white.sgf`、60手評価）

| 指標 | before (案A後) | after (案C適用) | 差分 | 合格範囲 | 合否 |
|---|---|---|---|---|---|
| `ai_top_move` | 0.1228 | _ | _ | ±0.02 | _ |
| `ai_top5_move` | 0.2906 | _ | _ | ±0.02 | _ |
| `mean_ptloss` | 1.5237 | _ | _ | ±0.1 | _ |
| `cvm_gap` | -0.5073 | _ | _ | ±0.1 | _ |
| `slack_delta_W` | 0.9773 | _ | _ | 情報のみ | — |

### 19路 B（`jigo-vs-3dan-20260413-black.sgf`、134手評価）

| 指標 | before (案A後) | after (案C適用) | 差分 | 合格範囲 | 合否 |
|---|---|---|---|---|---|
| `ai_top_move` | 0.3089 | _ | _ | ±0.02 | _ |
| `ai_top5_move` | 0.4658 | _ | _ | ±0.02 | _ |
| `mean_ptloss` | 1.2743 | _ | _ | ±0.1 | _ |
| `cvm_gap` | -1.6516 | _ | _ | ±0.1 | _ |
| `slack_delta_B` | 0.5178 | _ | _ | 情報のみ | — |

### 13路 game1（`katrain-13ro-20260401-game1.sgf`、B評価 ~46手）

| 指標 | before | after | 差分 | 合格範囲 | 合否 |
|---|---|---|---|---|---|
| `ai_top_move` | _ | _ | _ | ±0.02 | _ |
| `ai_top5_move` | _ | _ | _ | ±0.02 | _ |
| `mean_ptloss` | _ | _ | _ | ±0.1 | _ |
| `cvm_gap` | _ | _ | _ | ±0.1 | _ |

### 13路 game2（`katrain-13ro-20260401-game2.sgf`、W評価 ~43手）

| 指標 | before | after | 差分 | 合格範囲 | 合否 |
|---|---|---|---|---|---|
| `ai_top_move` | _ | _ | _ | ±0.02 | _ |
| `ai_top5_move` | _ | _ | _ | ±0.02 | _ |
| `mean_ptloss` | _ | _ | _ | ±0.1 | _ |
| `cvm_gap` | _ | _ | _ | ±0.1 | _ |

## フォールバック発生率

新規 18 run のログから `cn.analysis incomplete` と `Stage1 failed` 検索結果: **_ 件**（通常 0 件想定）

## 体感応答時間（実対局・ユーザー計測）

| 盤面 | 案A 後（参考） | 案C 後 | 短縮幅 |
|---|---|---|---|
| 19路 | ~0.5 秒 | _ 秒 | _ 秒 |
| 13路 | 体感差わずか | _ 秒 | _ 秒 |

## 結論

- [ ] 精度回帰なし（全主要指標が合格範囲内 OR 2σ 以内）
- [ ] 体感応答時間が改善（特に 13路で明確な短縮）
- [ ] フォールバック発生なし

判定: **採用 / 不採用**

## 関連コミット

`git log --oneline | head -10` 出力をここに貼る:

```
（埋める）
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/planC-results-20260414.md
git commit -m "$(cat <<'EOF'
docs(jigo-speedup): 案C 校正結果サマリ（20260414）を追加

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `.claude/rules/ai-parameters.md` の更新（サブエージェント経由）

**目的:** エンジン設定セクションから Jigo の Stage 2 行を削除（クエリ削減を反映）。**このファイルは Edit が拒否されることがあるため、サブエージェント経由で編集する**（CLAUDE.md「やってはいけないこと」記載ルール）。

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（エンジン設定テーブル）

- [ ] **Step 1: サブエージェント（general-purpose）に編集を委任**

Agent tool で `general-purpose` を起動し、以下のプロンプトを渡す:

> `.claude/rules/ai-parameters.md` の「## エンジン設定（maxVisits）」セクションのテーブルから、**Jigo の Stage 2 行を削除**してください。
>
> 対象セクションは「Stage1とGUI/analysis_configの3箇所を同じ値に揃える。Stage2は独立値。」のテーブルです。
>
> **削除する行:**
> ```
> | ai.py `clean_override_settings["maxVisits"]` | 600 | Stage2: クリーンスコア検証（独立値） |
> ```
>
> **追加するメモ（テーブル直下に1行）:**
> ```
>
> 注: Jigo は Stage 2 を廃止し、既定解析（`cn.analysis`, max_visits=800, wideRootNoise=0.04）を流用する。
> ```
>
> 編集完了後、以下のコマンドでコミットしてください:
>
> ```bash
> cd C:/Users/iwaki/Documents/katrain-1.17.1.1/katrain-1.17.1.1
> git add .claude/rules/ai-parameters.md
> git commit -m "docs(rules): Jigo の Stage 2 廃止を反映（案C適用後）"
> ```

- [ ] **Step 2: 編集結果を確認**

```bash
git log --oneline -1 .claude/rules/ai-parameters.md
```

直近コミットが上記メッセージなら OK。

---

### Task 10: CLAUDE.md / Spec へ案C 採用の追記（採用確定時のみ）

**目的:** Task 6 で案C 採用と判定された場合のみ、CLAUDE.md の Jigo セクションと spec ファイルに採用結果を反映する。

**Files:**
- Modify: `CLAUDE.md`（KataGo 解析結果セクション）
- Modify: `docs/superpowers/specs/2026-04-14-jigo-stage2-default-analysis-design.md`（採用ステータス）

- [ ] **Step 1: CLAUDE.md の Jigo 関連記述を確認**

```bash
grep -n -i "jigo\|Stage 2\|Stage2\|cn.analysis" CLAUDE.md | head -20
```

- [ ] **Step 2: CLAUDE.md の「KataGo 解析結果の扱い」セクションに追記が必要なら追加**

例えば以下を「KataGo 解析結果の扱い」末尾に追加:

```markdown
- **JigoStrategy は Stage 2 を持たず `self.cn.analysis` を直接消費する**: `wait_for_analysis()` 完了時点の moveInfos と rootInfo を `score_analysis = {"moveInfos": list(cn.analysis["moves"].values()), "rootInfo": cn.analysis["root"]}` の形で利用。wideRootNoise=0.04 込みの値だが校正で許容範囲を確認済（`docs/superpowers/specs/calibration-data/jigo-speedup/planC-results-20260414.md`）
```

- [ ] **Step 3: spec ファイルに採用ステータスを追記**

`docs/superpowers/specs/2026-04-14-jigo-stage2-default-analysis-design.md` の最後に以下のセクションを追加:

```markdown

## 採用ステータス

- **判定**: 採用 (2026-04-14)
- **校正結果**: `docs/superpowers/specs/calibration-data/jigo-speedup/planC-results-20260414.md` 参照
- **コミット**: `<Task 3 のコミットハッシュ>`
```

- [ ] **Step 4: Commit（変更があった場合のみ）**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-04-14-jigo-stage2-default-analysis-design.md
git commit -m "$(cat <<'EOF'
docs: 案C(Jigo Stage 2 既定解析置換) 採用を反映

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 完了条件

- [ ] Task 6 で全主要指標が合格範囲（または 2σ 以内）
- [ ] Task 7 の実対局で体感速度改善（特に 13路で明確）
- [ ] Task 8 の結果サマリ markdown が完成・コミット済み
- [ ] Task 9 のドキュメント更新完了
- [ ] フォールバック発生なし（Task 4・5 のログ確認）

## ロールバック手順

Task 6 で **不採用** 判定の場合:

```bash
# Task 3 のコード変更コミットを revert
git revert <Task 3 のコミットハッシュ>
git push  # 必要に応じて

# 校正データは記録として残す（不採用の根拠）
# Task 8 の結果サマリも残す（判定: 不採用 と記載）
```

設定ファイル変更なし、他ストラテジへの影響なしのため、ロールバックは安全。

## 残タスク（完了後の検討事項）

- パッケージ既定 `max_visits=500` 環境での挙動（500 visits は Stage 2 600 より少ない → 精度低下の可能性）。問題化したら別タスクでパッケージ既定値の引き上げを検討
- `cvm_gap` のみ退行が観測された場合、鋭手除外閾値緩和（`score > current_lead + 0.5` → `+0.7`）の別タスク検討
