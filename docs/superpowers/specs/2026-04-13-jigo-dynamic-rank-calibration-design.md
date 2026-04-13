# JigoStrategy 動的 rank 閾値校正 設計書

- 作成日: 2026-04-13
- ブランチ: `feat/jigo-weak-opponent`（続き、または派生ブランチ）
- 対象コード: `katrain/core/ai.py` `_select_rank_by_lead` / `JigoStrategy`、`katrain_debug/batch_eval.py`
- 前提 spec: `docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md`

## 1. 目的

`JigoStrategy.jigo_dynamic_rank=True` 時の Stage 1 humanSL rank 降格閾値（現行 `delta > 5` で 1段下、`delta > 15` で `rank_5d` 固定）は初期の当て推量値であり、弱相手対局での校正が未完了。本タスクで弱相手 vs 9段相当の実データを用いて閾値を校正し、**人間らしさを劣化させずに lead 収束傾向を改善する** 値を確定する。

## 2. スコープ

### in-scope
- `_select_rank_by_lead` の 2 閾値の校正（`delta_1`, `delta_2` の最終値確定）
- 閾値を CLI から上書きできるよう `jigo_rank_delta_1` / `jigo_rank_delta_2` 設定キーを追加（GUI 非露出）
- `katrain_debug/batch_eval.py` に Jigo 専用指標（lead 推移・humanPolicy・rank 降格カウント等）を追加
- 校正結果を `ai.py` デフォルト・`.claude/rules/ai-parameters.md`・前提 spec に反映
- 完了後、校正メモリ `project_jigo_dynamic_rank_calibration.md` を削除

### out-of-scope
- `_JIGO_RANK_CHAIN` の拡張（`rank_3d` 等の追加）
- `max_loss_per_move` の lead 依存化等、他パラメータの校正
- 自動プロット・グラフ生成
- 他戦略（Hunt/Siege 等）への同様の指標追加

## 3. テストデータ

### 入力 SGF（N=1）
- 元ファイル: `sgfout/KaTrain_人間 (通常対局) vs AI (Kata持碁) 2026-04-13 11 43 30.sgf`
- リネームコピー先: `docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf`
- 内容: 19 路、白=AI Jigo (`rank_9d`)、黒=人間3段、120 手で黒投了（最終 lead +33）
- 実対局時の設定: `target_score=0.5`, `target_score_max=5.0`, `max_loss_per_move=7.0`, `min_human_policy=0.02`, `jigo_mode=natural`, `human_profile=rank_9d`, `jigo_dynamic_rank=True`

### 制約の自覚
- N=1 のため汎化性は低い。採用判定は「現行 `5-15` から有意に改善」の高バー + 保守的バイアスで過剰適合を抑止
- 判定結果に「N=1 SGF での校正」を明記し、将来の再校正可能性を残す

## 4. 評価指標と batch_eval 拡張

### 4.1 `JigoStrategy` 側の露出

`generate_move` 末尾で instance attribute `self.last_decision_info` に選択情報を格納。既存の `(Move, str)` 戻り値は維持。

```python
self.last_decision_info = {
    "rank_used": human_profile,        # Stage1 で実際に使われた humanSL rank
    "selected_hp": selected["hp"],     # 選択手の humanPolicy
    "selected_score": selected["score"], # 選択手の Stage2 scoreLead（現プレイヤー視点）
    "filter_relaxed": was_relaxed,     # 段階緩和が発動したか
    "score_lead": current_lead,        # 親ノード時点の lead（現プレイヤー視点）
}
```

### 4.2 `batch_eval.py` 拡張

戦略実行後に `strategy.last_decision_info` を読み取り、`move_results` に以下フィールドを追加:
- `rank_used`, `selected_hp`, `selected_score`, `filter_relaxed`, `score_lead`

戦略名が `jigo` の場合のみ `_aggregate_stats` の戻り値に `jigo_metrics` セクションを追加:

| 指標 | 定義 |
|---|---|
| `mean_lead` | 全 AI 手番の `score_lead` 平均 |
| `max_lead` | 全 AI 手番の `score_lead` 最大 |
| `in_target_ratio` | `target_score ≤ score_lead ≤ target_score_max` だった手番比率 |
| `over_target_ratio` | `score_lead > target_score_max` だった手番比率 |
| `mean_selected_hp` | 選択手 humanPolicy 平均 |
| `p10_selected_hp` | 選択手 humanPolicy の下位 10% 値 |
| `filter_relax_rate` | 段階緩和発動手番の比率 |
| `rank_downgrade_counts` | `{rank_9d: N, rank_7d: N, rank_5d: N}` |

`target_score` / `target_score_max` は `ai_settings` から取得。

### 4.3 CLI 出力

`cli.py` の `--batch` text 出力に `Jigo Metrics` ブロックを追加（既存 `Aggregate Stats` の下）。`--output json` では `stats.jigo_metrics` キーで構造化。Jigo 以外の戦略では追加しない。

## 5. 閾値の設定化

### 5.1 関数シグネチャ変更

```python
def _select_rank_by_lead(current_lead, target_score_max, base_profile,
                          delta_1=5, delta_2=15):
    ...
    if delta > delta_2:
        new_idx = 0  # rank_5d 固定
    elif delta > delta_1:
        new_idx = max(0, idx - 1)
    else:
        new_idx = idx
    ...
```

### 5.2 `JigoStrategy.generate_move` からの受け渡し

```python
delta_1 = self.settings.get("jigo_rank_delta_1", 5)
delta_2 = self.settings.get("jigo_rank_delta_2", 15)
human_profile = _select_rank_by_lead(
    last_lead, target_score_max, base_profile,
    delta_1=delta_1, delta_2=delta_2,
)
```

### 5.3 設定キーの位置づけ

- 校正実験用の内部パラメータ。GUI（`constants.py AI_OPTION_VALUES`）には登録しない
- 校正完了後、採用値を関数デフォルト引数（`delta_1` / `delta_2`）に反映
- 設定キー自体は残す（将来の再校正用 escape hatch）
- ユーザローカル `config.json` には追加しない（指定ない限り関数デフォルトが使われる）

## 6. 校正実験

### 6.1 config グリッド（5 configs × 3 run = 15 run）

| config ID | `jigo_dynamic_rank` | `jigo_rank_delta_1` | `jigo_rank_delta_2` | 意図 |
|---|---|---|---|---|
| `off` | false | — | — | 動的 rank なし baseline |
| `5-15` | true | 5 | 15 | 現行未校正値 = 比較基準 |
| `3-10` | true | 3 | 10 | 早発動（積極降格） |
| `5-10` | true | 5 | 10 | delta_2 のみ前倒し |
| `3-15` | true | 3 | 15 | delta_1 のみ前倒し |

### 6.2 実行コマンド

```bash
python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf \
  --strategy jigo --batch --player W \
  --settings target_score_max=5.0 max_loss_per_move=7.0 \
             jigo_dynamic_rank=true \
             jigo_rank_delta_1=3 jigo_rank_delta_2=10 \
  --output json > docs/superpowers/specs/calibration-data/runs/3-10_run1.json
```

各 config 3 回実行。結果 JSON を `calibration-data/runs/{config_id}_run{1,2,3}.json` に保存。

### 6.3 3-run 平均の根拠

`memory/feedback_batch_eval_variance.md` より：`katrain_debug --batch` の比較は 3 run 平均必須。単一 run では温度サンプリングの分散に埋もれる。

## 7. 判定ルール

### 7.1 Step 1: 人間らしさ gate（必須条件）

現行 `5-15` の 3-run 平均を基準とし、候補 config が**全て満たす**なら gate 通過:

- `mean_selected_hp` が `5-15` の **0.9 倍以上**（10% 以上の劣化なし）
- `p10_selected_hp` が `5-15` の **0.8 倍以上**（下位ケースの悪化が 20% 以内）
- `filter_relax_rate` が `5-15` の **1.2 倍以下**（フィルタ緩和が 20% 以上は増えない）

いずれか違反で **その config は却下**。

### 7.2 Step 2: lead 収束スコア（gate 通過 configs の中で最良を選ぶ）

```
convergence_score = in_target_ratio - 0.5 × over_target_ratio - 0.02 × mean_lead
```

高いほど良い。係数は経験則（`in_target_ratio` の最大化・`over_target_ratio` の抑制・`mean_lead` の軽いペナルティ）。

### 7.3 Step 3: 採用判定

- 最良スコアの config が現行 `5-15` を **0.05 以上上回る** かつ **3-run 標準偏差を超える** → 採用
- 差が誤差範囲 → **現行 `5-15` 維持**（保守的バイアス）
- 全候補が gate 落ち → `off`（`dynamic_rank=False` 推奨）を結論に記載

### 7.4 分散の扱い

- 各指標について 3-run 平均と標準偏差の両方を記録
- 平均差が 3-run 標準偏差以下なら「有意差なし」扱い
- 判定レポートに `mean ± std` 形式で全指標を記載

## 8. 実装順序

1. SGF リネームコピー
2. `_select_rank_by_lead` の設定化（`ai.py`）＋ 既存 `test_ai.py` にヘルパー関数用ユニットテスト追加
3. `JigoStrategy.last_decision_info` 露出（`ai.py`）
4. `batch_eval.py` 拡張（収集・集計・出力）
5. 動作確認（`off` config 1 run で json/text 検証）
6. 5 config × 3 run 実行（2.5h）
7. 集計スクリプトで 15 個の JSON から config × 指標 × mean/std を table 化・判定
8. `calibration-data/jigo-dynamic-rank-results-YYYYMMDD.md` に結果と判定根拠を記載
9. 採用値を `_select_rank_by_lead` デフォルト引数に反映
10. `.claude/rules/ai-parameters.md` と前提 spec を更新
11. `memory/project_jigo_dynamic_rank_calibration.md` 削除、`MEMORY.md` 該当行削除
12. コミット（論理単位で分割、日本語 Conventional Commits）

## 9. リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| 単一 SGF で分散が大きく全 config 差が埋もれる | 校正不能 | 3-run 標準偏差が大きすぎる場合、「有意差なし・現行維持」として結論し、結果ドキュメントに「追加 SGF で再校正」を明記 |
| `last_decision_info` 追加で既存コード回帰 | バグ | instance attribute 追加のみで外部インターフェース不変。既存ユニットテスト通過で確認 |
| デフォルト引数変更で既存 GUI 動作が変わる | 回帰 | 設定キー未指定時は関数デフォルトが使われる。デフォルト変更時は前提 spec・`ai-parameters.md`・i18n 説明文（`aihelp:jigo` の `jigo_dynamic_rank` 記述）を同時更新 |
| N=1 SGF への過剰適合 | 汎化失敗 | 採用の高バー（0.05 以上 + 分散超え）と「差 < 0.05 なら現行維持」の保守的バイアス。結果ドキュメントに「N=1」と明記 |
| `batch_eval` 拡張中に他戦略の既存動作が壊れる | 他戦略回帰 | `jigo_metrics` は `strategy == "jigo"` 時のみ追加。既存戦略のテスト（あれば）を走らせて確認 |

## 10. 完了条件

1. 採用閾値が `_select_rank_by_lead` デフォルトに反映済み
2. `.claude/rules/ai-parameters.md` JigoStrategy セクションに採用値反映済み
3. `docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md` の「弱相手対応」セクションに採用値反映済み
4. 校正結果ドキュメント `calibration-data/jigo-dynamic-rank-results-YYYYMMDD.md` コミット済み
5. `memory/project_jigo_dynamic_rank_calibration.md` 削除、`MEMORY.md` 該当行削除済み
6. 既存ユニットテスト（モデル不要分）全パス

## 11. 参考

- 前提 spec: `docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md`
- 対象メモリ: `memory/project_jigo_dynamic_rank_calibration.md`
- 分散ルール: `memory/feedback_batch_eval_variance.md`
- batch 評価ツール: `katrain_debug/batch_eval.py`
- 戦略コード: `katrain/core/ai.py` `_select_rank_by_lead` (L746)、`JigoStrategy` (L785)
