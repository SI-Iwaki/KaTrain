# Jigo speedup phase 2 校正結果（2026-04-15）

**Spec:** `docs/superpowers/specs/2026-04-15-jigo-stage2-per-mode-clean-analysis-design.md`

**Before:** 案A 適用済・Stage 2 クエリ残存（600 visits クリーン）
**After:** フェーズ2 適用後・Stage 2 廃止、既定解析を Jigo-scoped クリーン化で読み替え

**Commits:**
- Before baseline (Task 1): de5c3a4
- Task 2 (engine.py scoping): 211e5bc + f93382d
- Task 3 (ai.py Stage 2 廃止): 3531cd5
- Task 4 (runner/batch_eval + 診断撤去): e31f238 + 1eae682
- After baseline (Task 5): be7bc90

## 3-run 平均の差分（delta = after - before）

### ogs W

| 指標 | before (3-run mean) | before stdev | after (3-run mean) | after stdev | delta | 基準 | 判定 |
|---|---|---|---|---|---|---|---|
| ai_top_move | 0.3750 | 0.0309 | 0.3988 | 0.0273 | +0.0238 | ≤ 0.02 | FAIL |
| ai_top5_move | 0.4702 | 0.0206 | 0.4524 | 0.0206 | -0.0179 | ≤ 0.02 | PASS |
| mean_ptloss | 1.6897 | 0.3000 | 1.7869 | 0.1007 | +0.0972 | ≤ 0.1 | PASS |
| choice_vs_median_gap | -2.8220 | 0.2529 | -2.1824 | 0.4539 | +0.6396 | ≤ 0.1 | FAIL |
| post_98pct_slack | 1.9102 | 1.1776 | 2.1204 | 0.4439 | +0.2102 | ≤ 0.1 | FAIL |

### ogs B

| 指標 | before (3-run mean) | before stdev | after (3-run mean) | after stdev | delta | 基準 | 判定 |
|---|---|---|---|---|---|---|---|
| ai_top_move | 0.5294 | 0.0355 | 0.5263 | 0.0175 | -0.0031 | ≤ 0.02 | PASS |
| ai_top5_move | 0.7883 | 0.0159 | 0.8012 | 0.0203 | +0.0128 | ≤ 0.02 | PASS |
| mean_ptloss | 0.3324 | 0.0287 | 0.3005 | 0.0091 | -0.0318 | ≤ 0.1 | PASS |
| choice_vs_median_gap | -3.4026 | 0.0103 | -2.7648 | 0.0545 | +0.6378 | ≤ 0.1 | FAIL |
| post_98pct_slack | N/A | — | N/A | — | N/A | ≤ 0.1 | N/A |

### 13ro-game1 W

| 指標 | before (3-run mean) | before stdev | after (3-run mean) | after stdev | delta | 基準 | 判定 |
|---|---|---|---|---|---|---|---|
| ai_top_move | 0.3106 | 0.0347 | 0.3106 | 0.0131 | +0.0000 | ≤ 0.02 | PASS |
| ai_top5_move | 0.3788 | 0.0131 | 0.3636 | 0.0227 | -0.0152 | ≤ 0.02 | PASS |
| mean_ptloss | 1.9612 | 0.0981 | 2.2595 | 0.0698 | +0.2983 | ≤ 0.1 | FAIL |
| choice_vs_median_gap | -2.0382 | 0.5123 | -1.5239 | 0.1723 | +0.5143 | ≤ 0.1 | FAIL |
| post_98pct_slack | 1.1060 | 0.0603 | 1.6483 | 0.0122 | +0.5422 | ≤ 0.1 | FAIL |

### 13ro-game1 B

| 指標 | before (3-run mean) | before stdev | after (3-run mean) | after stdev | delta | 基準 | 判定 |
|---|---|---|---|---|---|---|---|
| ai_top_move | 0.6364 | 0.1041 | 0.6364 | 0.0601 | +0.0000 | ≤ 0.02 | PASS |
| ai_top5_move | 0.8864 | 0.0227 | 0.8561 | 0.0347 | -0.0303 | ≤ 0.02 | FAIL |
| mean_ptloss | 0.0921 | 0.0100 | 0.1720 | 0.0883 | +0.0800 | ≤ 0.1 | PASS |
| choice_vs_median_gap | -3.6105 | 0.1331 | -2.2711 | 0.0583 | +1.3394 | ≤ 0.1 | FAIL |
| post_98pct_slack | N/A | — | N/A | — | N/A | ≤ 0.1 | N/A |

### 13ro-game2 W

| 指標 | before (3-run mean) | before stdev | after (3-run mean) | after stdev | delta | 基準 | 判定 |
|---|---|---|---|---|---|---|---|
| ai_top_move | 0.1240 | 0.0269 | 0.1085 | 0.0269 | -0.0155 | ≤ 0.02 | PASS |
| ai_top5_move | 0.2248 | 0.0269 | 0.2171 | 0.0355 | -0.0078 | ≤ 0.02 | PASS |
| mean_ptloss | 2.7575 | 0.1359 | 2.8629 | 0.1085 | +0.1053 | ≤ 0.1 | FAIL |
| choice_vs_median_gap | -0.5836 | 0.0433 | -0.4310 | 0.1436 | +0.1527 | ≤ 0.1 | FAIL |
| post_98pct_slack | 0.7928 | 0.2008 | 1.6194 | 0.2641 | +0.8267 | ≤ 0.1 | FAIL |

### 13ro-game2 B

| 指標 | before (3-run mean) | before stdev | after (3-run mean) | after stdev | delta | 基準 | 判定 |
|---|---|---|---|---|---|---|---|
| ai_top_move | 0.6822 | 0.0585 | 0.6667 | 0.0537 | -0.0155 | ≤ 0.02 | PASS |
| ai_top5_move | 0.9535 | 0.0000 | 0.9225 | 0.0134 | -0.0310 | ≤ 0.02 | FAIL |
| mean_ptloss | 0.3175 | 0.1956 | 0.1800 | 0.0614 | -0.1375 | ≤ 0.1 | FAIL |
| choice_vs_median_gap | -2.8330 | 0.0471 | -2.0973 | 0.0394 | +0.7357 | ≤ 0.1 | FAIL |
| post_98pct_slack | 11.8026 | 6.8753 | 3.0411 | 2.8624 | -8.7614 | ≤ 0.1 | FAIL |

## 合格基準逸脱のまとめ

合計 28 項目チェック（N/A 除く）中 **16 項目が逸脱**:

**ai_top_move 逸脱（1件）:**
- ogs W: delta=+0.0238（基準 ±0.02、before stdev=0.0309 で並列探索分散の範囲内）

**ai_top5_move 逸脱（2件）:**
- 13ro-game1 B: delta=-0.0303（基準 ±0.02）
- 13ro-game2 B: delta=-0.0310（基準 ±0.02）

**mean_ptloss 逸脱（3件）:**
- 13ro-game1 W: delta=+0.2983（基準 ±0.1、**3倍超過**）
- 13ro-game2 W: delta=+0.1053（基準 ±0.1 をわずかに超過）
- 13ro-game2 B: delta=-0.1375（基準 ±0.1、before stdev=0.1956 で高分散）

**choice_vs_median_gap 逸脱（6件、全ブロック）:**
- ogs W: delta=+0.6396
- ogs B: delta=+0.6378
- 13ro-game1 W: delta=+0.5143
- 13ro-game1 B: delta=+1.3394
- 13ro-game2 W: delta=+0.1527
- 13ro-game2 B: delta=+0.7357
- **全ブロックで一貫して正方向にシフト**。after で「選択手がAI候補中央値より悪い傾向に変化」を示す系統的変化

**post_98pct_slack 逸脱（4件）:**
- ogs W: delta=+0.2102（before stdev=1.1776、低サンプル数による高分散）
- 13ro-game1 W: delta=+0.5422（before stdev=0.0603、low_sample=True）
- 13ro-game2 W: delta=+0.8267（low_sample=True）
- 13ro-game2 B: delta=-8.7614（before stdev=6.8753、before 3-run 間で 4〜18 と極端な不安定、低信頼）

## 判定

**NO-GO**

16/28 項目が逸脱（判定基準: 9項目以上で NO-GO）。最も深刻な問題は **`choice_vs_median_gap` の全ブロック一貫逸脱**で、delta の平均は +0.7 目前後（基準 ±0.1 の 7 倍超）。これは Stage 2 → 既定解析への置換により `scoreLead` フィルタの判定基準が変わり、before では候補中央値より有利な手を選んでいた傾向が薄れたことを示す系統的な変化であり、並列探索の確率的分散では説明できない。また 13ro-game1 W の `mean_ptloss` が +0.2983（3倍超過）と大幅に悪化しており、精度劣化が実ゲームプレイに影響し得る水準にある。

ロールバック対象コミット: `3531cd5`（ai.py Stage 2 廃止）および `211e5bc` + `f93382d`（engine.py scoping）の revert を検討。詳細は plan のロールバックセクション参照。

## 補足: 3-run stdev の観察

**主要指標の分散状況:**

- `ogs W ai_top_move`: before stdev=0.0309、after stdev=0.0273。FAIL delta=+0.0238 は stdev と同程度で並列探索非決定性の範囲内の可能性があるが、他の系統的逸脱と合わせて NO-GO 判定に影響なし。
- `choice_vs_median_gap`: ogs W before stdev=0.2529 は高めだが、全ブロックで一貫して正方向にシフト（delta +0.51 〜 +1.34）しており、分散では説明できない系統変化。
- `post_98pct_slack 13ro-game2 B`: before stdev=6.8753 は極端に高く（low_sample=True、3-run で 4.2 / 13.7 / 17.5 と大きくばらつく）、この項目単独のFAILは統計的に信頼性が低い。ただし他の逸脱が既に NO-GO を確定させている。
- `mean_ptloss ogs W`: before stdev=0.3000 は高く、delta=+0.0972 は PASS 判定。13ro-game1 W の stdev=0.0981 は低く delta=+0.2983 は確実な逸脱。

## 次ステップ

- **Task 6 判定: NO-GO のため Task 7/8 は保留**
- ロールバック: plan のロールバックセクション参照（`3531cd5`, `f93382d`, `211e5bc` の revert）
- 原因調査候補:
  - `candidate_moves` 経由の `scoreLead` が Stage 2 直接クエリと同等でない可能性（`pointsLost` ベース vs raw `scoreLead` の差）
  - `engine.py` scoping 判定が実際に機能しているか（`wideRootNoise=0.0` が実際に既定解析に適用されているか）の smoke test 再確認
  - `choice_vs_median_gap` の系統シフトが `self.cn.candidate_moves` の順序・内容の差によるものか確認
- Task 8 (.claude/rules/ai-parameters.md 更新) は NO-GO のためスキップ
