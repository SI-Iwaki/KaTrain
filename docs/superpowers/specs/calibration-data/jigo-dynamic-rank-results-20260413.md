# Jigo Dynamic Rank Calibration Results (2026-04-13)

## Test Data
- Primary SGF: `docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-white.sgf`
  - 19 路、白=AI Jigo、黒=人間3段、120 手で黒投了、最終 lead +33
- Post-hoc validation SGF: `docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413-black.sgf`
  - 19 路、黒=AI Jigo、白=人間3段、222 手
- Base settings: `target_score=0.5`, `target_score_max=5.0`, `max_loss_per_move=7.0`, `min_human_policy=0.02`, `jigo_mode=natural`, `human_profile=rank_9d`
- Main evaluation: White moves only on primary SGF, 3 runs per config, 5 configs total (15 runs)
- Post-hoc validation: Black moves on secondary SGF, 1 run of winner config + 1 run of `off` baseline (2 runs)

## Results (3-run mean ± std)

| config | n | conv_score | in_target | over_target | mean_lead | max_lead | mean_hp | p10_hp | relax_rate |
|---|---|---|---|---|---|---|---|---|---|
| off | 3 | -0.345±0.000 | 21.7%±0.0% | 75.0%±0.0% | 9.31±0.01 | 33.1±0.0 | 0.347±0.003 | 0.032±0.003 | 0.0%±0.0% |
| 5-15 | 3 | -0.345±0.000 | 21.7%±0.0% | 75.0%±0.0% | 9.32±0.02 | 33.1±0.1 | 0.345±0.015 | 0.029±0.001 | 0.0%±0.0% |
| 3-10 | 3 | -0.344±0.000 | 21.7%±0.0% | 75.0%±0.0% | 9.30±0.01 | 33.2±0.1 | 0.362±0.006 | 0.036±0.002 | 0.0%±0.0% |
| 5-10 | 3 | -0.345±0.001 | 21.7%±0.0% | 75.0%±0.0% | 9.32±0.04 | 33.2±0.0 | 0.324±0.007 | 0.027±0.000 | 0.0%±0.0% |
| 3-15 | 3 | -0.344±0.000 | 21.7%±0.0% | 75.0%±0.0% | 9.30±0.01 | 33.1±0.0 | 0.350±0.007 | 0.038±0.005 | 0.0%±0.0% |

## Gates (vs baseline 5-15)

- `off`: pass
- `5-15`: baseline
- `3-10`: pass
- `5-10`: pass
- `3-15`: pass

人間らしさ gate（mean_hp ≥ 0.9×baseline, p10_hp ≥ 0.8×baseline, relax_rate ≤ 1.2×baseline）は全 config で通過。

## Rank Downgrade Counts (last run)

| config | rank_9d | rank_7d | rank_5d |
|---|---|---|---|
| off    | 60 |  0 |  0 |
| 5-15   | 41 | 16 |  3 |
| 3-10   | 31 | 20 |  9 |
| 5-10   | 42 |  9 |  9 |
| 3-15   | 32 | 25 |  3 |

`off` は全手で rank_9d（dynamic_rank=false の想定通り）。dynamic_rank config は閾値に応じて 7d / 5d に降格している。

## Decision

**採用閾値:** **現行 `delta_1=5, delta_2=15` 維持**

**判定根拠:**
- convergence_score: best は `3-10`（-0.344）、baseline `5-15`（-0.345）との diff は **+0.001**、採用閾値 `max(0.05, conv_score_std=0.000)` を大きく下回るため、改善は誤差範囲
- すべての dynamic_rank config および `off` が人間らしさ gate を通過（gate 落ち config なし）
- 全 config で `in_target_ratio=21.7%`, `over_target_ratio=75.0%`, `mean_lead≈9.3` がほぼ完全一致 — rank_downgrade_counts は config 毎に大きく変動しているにもかかわらず、最終選択手のスコア分布は変わらなかった
- これは主フィルタ（`target_score_max=5.0`, `max_loss_per_move=7.0`）が支配的で、Stage 1 humanPolicy の源（rank）が変わってもフィルタ後の argmax が安定しているためと解釈できる
- N=1 primary SGF での校正のため、過剰適合リスクを考慮して保守的バイアスを適用

## Post-hoc Generalization Check (black SGF, N=1 run each)

Post-hoc は winner 判定（= 保守判定で現行維持の `5-15`）と `off` baseline を黒番 SGF で 1 run ずつ実行。プランで指定された `summary.loss_mean` は未実装キーのため、主指標の `mean_lead` と副指標（`conv_score`, `filter_relax_rate`）で評価。

### Metrics comparison

| config | mean_lead (white 3-run) | mean_lead (black 1-run) | Δ | Within white ±1σ? |
|--------|-------------------------|-------------------------|-----|-------------------|
| off    | 9.31 ± 0.01            | 17.28                   | +7.97 | NO (±1σ=0.01 なので大幅外れ) |
| 5-15   | 9.32 ± 0.02            | 17.25                   | +7.93 | NO (±1σ=0.02 なので大幅外れ) |

| config | in_target (white) | in_target (black) | over_target (white) | over_target (black) | filter_relax (white) | filter_relax (black) |
|--------|---|---|---|---|---|---|
| off    | 21.7% | 11.9% | 75.0% | 80.6% | 0.0% | 0.75% |
| 5-15   | 21.7% | 11.9% | 75.0% | 80.6% | 0.0% | 0.00% |

### rank_downgrade_counts (black, 1-run)

| config | rank_9d | rank_7d | rank_5d |
|---|---|---|---|
| off    | 134 |  0 |  0 |
| 5-15   |  43 | 12 | 79 |

黒 SGF は白 SGF より大きなリード局面が多く（222 手の長期局、かつ 5-15 では 79 手が rank_5d まで降格）、5-15 の dynamic_rank 動作はより高頻度に発動している。

### Generalization verdict

**⚠️ 両方の config が白 SGF 3-run ±1σ の外に出たため、白 SGF 単独の数値評価は慎重に扱う必要がある**（黒 SGF は局面難易度が異なり mean_lead が ~8 高い）。

ただし、以下の点は白 SGF の結論と整合する:
- off と 5-15 の mean_lead 差は **Δ=0.03**（17.28 vs 17.25）で、白 SGF の「config 間差が誤差範囲」所見と一致
- `in_target_ratio` / `over_target_ratio` も両 config で完全一致（11.9% / 80.6%）
- 5-15 は `filter_relax_rate` が 0.75% → 0.0% に下がる定性的改善があり（downgrade による humanPolicy 緩和が効く）、dynamic_rank を有効化しておく意義は残る

**結論:** Black SGF での post-hoc は「現行 5-15 維持」判定を覆す根拠にならない。白 SGF で観察された「dynamic rank が rank_downgrade_counts を変えつつも最終選択スコア分布はほぼ不変」という挙動は黒 SGF でも再現された。

## Notes

- N=1 primary SGF での校正。将来、他の弱相手 SGF が得られたら再校正推奨
- 今回の結果は「dynamic rank 降格が humanPolicy 形状を変えるが、jigo の目的関数（target score 近傍選択）下では argmax が不変」という興味深い知見をもたらした
- `jigo_rank_delta_1` / `jigo_rank_delta_2` の設定キーは実装済み（GUI 非露出）。escape hatch として保持
- 今回の 3-run std はすべての config で極めて小さい（0.001-0.005 レンジ）。jigo は事実上 argmax 選択のため実質 deterministic。温度サンプリングを伴う他戦略と比較した runs は別途必要
