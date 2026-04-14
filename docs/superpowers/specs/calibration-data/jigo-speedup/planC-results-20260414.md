# Jigo Stage 2 既定解析置換（案C）校正結果（2026-04-14）

## 変更概要

`katrain/core/ai.py` `JigoStrategy.generate_move()` の Stage 2 ブロック（600 visits クリーンクエリ）を `self.cn.analysis` 参照に置換する案C を試行。1手あたりのクエリ削減（Stage 1 のみ）で追加の応答時間短縮を狙った。

- Spec: `docs/superpowers/specs/2026-04-14-jigo-stage2-default-analysis-design.md`
- Plan: `docs/superpowers/plans/2026-04-14-jigo-stage2-default-analysis.md`
- コード変更コミット: `8165247`（案C 適用）
- ロールバック（revert）コミット: `18a6eac`
- 前提コミット: `024e4b1`（案A 適用済）

## 判定: **REJECT (不採用)**

精度退行が spec §7.4 のパス基準（±0.02 / ±0.1 / 2σ）を **9/16 指標で外れた**ため不採用。Stage 2 を `git revert` で復元（commit `18a6eac`）。

## trade-off（実測結果）

| 軸 | 案A 後 (Stage 2) | 案C (cn.analysis) | 想定 | 実測影響 |
|---|---|---|---|---|
| visits | 600 | 800 (+33%) | refinement 改善 | ほぼ無効 |
| wideRootNoise | 0.0 | 0.04 | scoreLead に ±0.1〜0.3 目 noise | **mean_ptloss を 0.22〜0.47 目悪化** |
| クエリ数/手 | 2 | 1 | 約 0.2-0.4 秒短縮 | （体感未測定、不採用のため） |

visits +33% 増加では wideRootNoise 増加を相殺できず、**理論想定より大きな精度退行**が発生。

## 精度回帰（3run 平均）

### 19路 W（`jigo-vs-3dan-20260413-white.sgf`、60手評価）

| 指標 | before (案A後) | after (案C適用) | 差分 | 合格範囲 | 合否 |
|---|---|---|---|---|---|
| `ai_top_move` | 0.1228 | 0.1278 | +0.0050 | ±0.02 | ✅ |
| `ai_top5_move` | 0.2906 | 0.2389 | -0.0517 | ±0.02 | ❌ (2.69σ) |
| `mean_ptloss` | 1.5237 | 1.8062 | +0.2825 | ±0.1 | ❌ (2.37σ) |
| `cvm_gap` | -0.5073 | -0.5659 | -0.0586 | ±0.1 | ✅ |
| `slack_delta_W` | 0.9773 | 1.2904 | +0.3131 | 情報のみ | — |

### 19路 B（`jigo-vs-3dan-20260413-black.sgf`、134手評価）

| 指標 | before (案A後) | after (案C適用) | 差分 | 合格範囲 | 合否 |
|---|---|---|---|---|---|
| `ai_top_move` | 0.3089 | 0.3010 | -0.0079 | ±0.02 | ✅ |
| `ai_top5_move` | 0.4658 | 0.4229 | -0.0429 | ±0.02 | ❌ (9.96σ) |
| `mean_ptloss` | 1.2743 | 1.4950 | +0.2207 | ±0.1 | ❌ (4.32σ) |
| `cvm_gap` | -1.6516 | -1.4778 | +0.1738 | ±0.1 | ❌ (4.25σ) |
| `slack_delta_B` | 0.5178 | 0.7558 | +0.2380 | 情報のみ | — |

### 13路 game1（`katrain-13ro-20260401-game1.sgf`、B評価 44手）

| 指標 | before | after | 差分 | 合格範囲 | 合否 |
|---|---|---|---|---|---|
| `ai_top_move` | 0.6288 | 0.6364 | +0.0076 | ±0.02 | ✅ |
| `ai_top5_move` | 0.9091 | 0.8788 | -0.0303 | ±0.02 | ✅ (1.15σ) |
| `mean_ptloss` | 0.0893 | 0.0966 | +0.0073 | ±0.1 | ✅ |
| `cvm_gap` | -3.5008 | -3.5842 | -0.0834 | ±0.1 | ✅ |

**game1 (B) は全指標 PASS**。AI top1 一致率が 63% と高く、wideRootNoise noise の影響を受けにくい局面。

### 13路 game2（`katrain-13ro-20260401-game2.sgf`、W評価 43手）

| 指標 | before | after | 差分 | 合格範囲 | 合否 |
|---|---|---|---|---|---|
| `ai_top_move` | 0.1406 | 0.0853 | -0.0554 | ±0.02 | ❌ (2.06σ) |
| `ai_top5_move` | 0.2501 | 0.1628 | -0.0873 | ±0.02 | ❌ (2.40σ) |
| `mean_ptloss` | 2.6955 | 3.1690 | +0.4734 | ±0.1 | ❌ (2.89σ) |
| `cvm_gap` | -0.5374 | -0.3316 | +0.2057 | ±0.1 | ❌ (2.98σ) |
| `slack_delta_W` | — | 1.2956 | — | 情報のみ | — |

**game2 (W) は全指標 FAIL**。AI top1 一致率が 14% と低く、scoreLead noise が候補選択に大きく影響。

## パターン分析

| 局面 | AI top1 | mean_ptloss 退行 | 退行の説明 |
|---|---|---|---|
| 13路 game1 (B) | 63% | +0.007 ✅ | top1 が高く、noise 0.04 では順位入れ替わりが起きにくい |
| 19路 B | 31% | +0.221 ❌ | 中位、noise で top5 圏内の入れ替わりが頻発 |
| 19路 W | 13% | +0.283 ❌ | 低 top1、候補手が多く噛み合いやすい局面で noise 影響大 |
| 13路 game2 (W) | 14% | +0.473 ❌ | 同上、最も顕著 |

**結論**: wideRootNoise=0.04 が JigoStrategy の `loss = best_score - score` フィルタ判定（max_loss=5.6）と humanPolicy 重み選択の組み合わせで、選択結果を実用上ぶれさせる。AI top1 一致率が中〜低の局面ほど影響が大きい。

## フォールバック発生率

新規 18 run（19路 after 6 + 13路 before 6 + 13路 after 6）のログから `cn.analysis incomplete` と `Stage1 failed` 検索結果: **0 件**。フォールバック経路は発動せず、案C のロジック自体は想定通り動作。退行はあくまで wideRootNoise=0.04 の精度影響。

## 体感応答時間

実対局検証は実施せず（不採用のため不要）。理論的には 13路 で明確な短縮が出る見込みだったが、精度退行とのトレードオフで採用断念。

## 関連コミット

```
18a6eac Revert "perf(jigo): Stage 2 を既定解析 cn.analysis で置換"
eee2c28 chore(jigo-speedup): 案C 適用後の 13路 batch_eval(game1/game2 × 3 run)を記録
dbdf55b chore(jigo-speedup): 案C 適用後の 19路 batch_eval(白/黒 × 3 run)を記録
8165247 perf(jigo): Stage 2 を既定解析 cn.analysis で置換 ← reverted
e3ff712 chore(jigo-speedup): 案C 13路 before ベースライン(2 SGF × 3 run)を記録
43adfc5 chore(jigo-speedup): 13路校正 SGF を main-line 化してコピー
```

## 学んだこと

1. **wideRootNoise=0.04 は JigoStrategy の精度に想定以上の影響**: spec §3 では「±0.1〜0.3 目程度」と見積もったが、実測 mean_ptloss は 0.22〜0.47 目悪化。visits +33% でも相殺できず
2. **noise 影響は局面依存**: AI top1 一致率が高い局面（game1 B 63%）は noise 耐性あり、低い局面（game2 W 14%）は致命的
3. **scoreLead noise は鋭手除外（0.5目精度）だけでなく `loss = best_score - score` のフィルタ判定全体に効く**: candidate 数が多く拮抗する局面で順位入れ替わりが頻発
4. **既存の Stage 2（クリーン 600 visits）は精度面で必要**: 案C のような共有データ流用は速度メリットが大きいが、JigoStrategy のように scoreLead 精度に依存する戦略には適さない

## 残タスク（救済可能性の検討）

不採用となった案C を救う案（spec §「将来拡張」相当）:

1. **既定解析の wideRootNoise=0 化**（B案 — 副作用大、KaTrain 全体のレビュー必要）
2. **既定解析の visits を 1200 等に大幅増加**（応答時間が長くなり目的に反する）
3. **JigoStrategy 専用に追加クリーンクエリ発行**（Stage 2 と同等になり案C の意味なし）
4. **鋭手除外閾値の緩和**（`+0.5` → `+0.7`）— scoreLead noise マージンを確保。ただし mean_ptloss 退行の主因はそこではないので部分的解決のみ

いずれも工数 vs 効果が見合わないため、**当面は現行（案A 適用済）を維持**し、案C 系の追加開発はしないことを推奨。
