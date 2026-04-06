# AI一致率低減モード 設計仕様

**日付**: 2026-04-06  
**対象バージョン**: KaTrain v1.17.1.1+

---

## 概要

評価レポートにおけるAI最善手一致率・AI上位5手一致率を下げつつ、強さ（平均損失目数）を維持する新戦略モード。  
既存の HumanStyleStrategy とは独立した新クラスとして実装する。

### 目標値

| 指標 | 目標 |
|---|---|
| `ai_top_move`（最善手一致率） | ≤ 30% |
| `ai_top5_move`（上位5手一致率） | ≤ 40% |
| `mean_ptloss`（平均損失目数） | < 1.00 |

---

## アーキテクチャ

### 新規コンポーネント

| ファイル | 変更内容 |
|---|---|
| `katrain/core/constants.py` | `AI_DIVERGE = "ai_diverge_move"` 定数追加、`AI_OPTION_VALUES` にパラメータ追加 |
| `katrain/core/ai.py` | `DivergenceStrategy(AIStrategy)` クラス追加、`ai_rank_estimation()` に分岐追加 |
| `katrain/config.json` | AI設定デフォルト値追加 |
| `C:\Users\iwaki\.katrain\config.json` | ユーザー設定にキー追加（GUIに表示するため必須） |

### クラス構成

```
AIStrategy (ABC)
└── DivergenceStrategy   ← 新規（HumanStyleStrategyとは独立）
```

HumanStyleStrategy のインフラ（2段階クエリ、スコアフィルタ処理）はコードを参考にしつつ、`DivergenceStrategy` 内に独立して実装する。

---

## コアアルゴリズム

### 2段階クエリ

HumanStyleStrategy と同様の2段階クエリを使用する。

| ステージ | 設定 | 目的 |
|---|---|---|
| Stage 1 | `humanSLProfile` + `maxVisits=800` | `humanPolicy[N×N]` 取得 |
| Stage 2 | クリーン（humanSLなし）+ `maxVisits=600` + `wideRootNoise=0` | 正確な `scoreLead`・`order` 取得 |

### スコア計算

各候補手 `i` に対して：

```
loss[i] = player_sign × (best_score - scoreLead[i])

divergence_score[i] = humanPolicy[i] × (order[i] + 1)^divergence_power
```

- `order[i]`: KataGo の探索順位（0 = AI最善手、数字が大きいほどAIが低く評価）
- 指数は**正**。order が大きい（AIが低く評価する）手ほど重みが大きくなる
- `divergence_power`（α）が大きいほど AI 下位手のブーストが強くなり、結果として AI 上位手が選ばれにくくなる
- 例（α=0.5）: order=0 → ×1.0、order=4 → ×2.2、order=9 → ×3.2（humanPolicy との積で確率的選択）

### フィルタとフォールバック

1. **スコアフィルタ**: `loss > diverge_score_filter` の手を除外
2. **候補数フォールバック**: フィルタ後の候補が **3手以下** の場合、`divergence_score` を `humanPolicy` に差し替えて乖離ペナルティを無効化
3. **空集合フォールバック**: フィルタ後が0手の場合、`diverge_score_filter` を段階的に緩和して再試行（HumanStyleStrategy と同パターン）
4. **humanPolicy除外**: `moveInfos` に含まれない手（スコア不明）は候補から除外

---

## データフロー

```
generate_move()
│
├─ Stage 1クエリ（humanSLProfile + maxVisits=800）
│   └─ humanPolicy[N×N] 取得
│
├─ Stage 2クエリ（クリーン + maxVisits=600 + wideRootNoise=0）
│   └─ moveInfos[] 取得 → {move, order, scoreLead, ...}
│
├─ 候補構築
│   ├─ moveInfos の各手:
│   │   ├─ humanPolicy[座標インデックス] → human重み
│   │   ├─ loss = player_sign × (best_score - scoreLead)
│   │   └─ divergence_score = human重み × (order+1)^(-α)
│   └─ moveInfos 外の手は除外
│
├─ スコアフィルタ（loss > diverge_score_filter を除外）
│
├─ 候補数チェック
│   ├─ ≤ 3手 → divergence_score を humanPolicy に差し替え
│   └─ > 3手 → divergence_score をそのまま使用
│
└─ weighted_selection() → 着手
```

---

## パラメータ

| パラメータ名 | 型 | デフォルト | 範囲 | 説明 |
|---|---|---|---|---|
| `divergence_power` | float | 0.5 | 0.3〜1.5 | AI一致率低減強度。大きいほど AI 下位手のブーストが強まり、AI トップ手が選ばれにくくなる |
| `diverge_score_filter` | float | 2.5 | 1.0〜5.0 | 許容する最大損失（目数）。小さいほど精度重視 |
| `human_kyu_rank` | int | -8（9段） | -9〜9 | humanSLプロファイルのベース段位（負=段位、正=級位） |

### `divergence_power` の目安

| 値 | 特性 |
|---|---|
| 0.0 | 乖離なし（純粋な humanPolicy 選択） |
| 0.5 | デフォルト。目標値（ai_top ≤30%, ai_top5 ≤40%）の想定値 |
| 1.0 | 中程度。mean_loss がやや上昇する可能性あり |
| 1.5 | 強度設定。mean_loss の上昇に注意 |

---

## 強さ推定

- `divergence_power=0.5`, `diverge_score_filter=2.5`, `human_kyu_rank=-8` で**9段相当**を想定
- `ai_rank_estimation()` へのELO追加: 固定値 **~1650**（humanSL 9段 + スコアフィルタ補正）
- `divergence_power` が大きくなるほど実質的な強さは低下するが、`diverge_score_filter` が防波堤となる
- デフォルト値は実装後の実戦テストで調整が必要（目標値到達まで `divergence_power` を 0.3 刻みで調整推奨）

---

## game_report との対応

| 目標 | メカニズム |
|---|---|
| `ai_top_move ≤ 30%` | `order=0` の手のブースト係数は `(1)^α = 1.0`（最小）。他の候補がブーストされるため相対的に選ばれにくくなる |
| `ai_top5_move ≤ 40%` | AI 上位5手はブースト係数が小さく、humanPolicy の高い下位候補に確率が移る。損失0.5〜2.5目の手が頻出する |
| `mean_loss < 1.00` | `score_filter=2.5` で大悪手を遮断。humanPolicy ベースで自然な手が残る |

---

## 実装上の注意点

- **Stage 1 の `scoreLead` は使用禁止**: humanSLProfile によりバイアスされる（HumanStyleStrategy と同じ制約）
- **`player_sign` の適用**: `scoreLead` は常に Black 視点。White 番では符号反転が必要
- **`best_score` の参照点**: `moveInfos[0]` ではなく、`order=0` の手の `scoreLead`（探索数最多手とは異なる場合あり）
- **humanPolicy インデックス変換**: `moveInfos` の GTP 座標 → 盤面インデックスへの変換が必要（HumanStyleStrategy の実装を参照）
- **CLAUDE.md 更新**: 新パラメータをパラメータ値テーブルに追記する
- **ユーザー config.json 更新必須**: パッケージ版だけでなく `C:\Users\iwaki\.katrain\config.json` にも追加しないと GUI に表示されない

---

## 実装しないもの

- `first_impression_deviation` / `green_blend` 相当機能: 本モードの目的（AI乖離）と方向性が異なるため不要
- `pick_override` パラメータ: 候補数ベースの自動フォールバックで代替するため不要
- 盤面サイズ別の閾値分岐: 初期実装では単一の `diverge_score_filter` で統一（必要なら後で追加）
