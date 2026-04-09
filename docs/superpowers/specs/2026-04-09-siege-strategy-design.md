# 攻城戦略（SiegeStrategy）設計書

## 概要

新AIモード `ai:攻城戦略` — 序盤は相手に地を与えて大模様を張らせ、中盤以降に不安定な大石群を攻めて逆転を狙う「背水の陣」戦略。

## コンセプト

- 序盤は意図的に地を譲り、相手の石群を大きく育てさせる
- 中盤〜終盤でターゲットの大石群を集中攻撃
- 大石を取れなくても攻めのプレッシャーで利益を得る
- 最低限の自衛はする（自分の大石が取られるような大損は回避）
- 対応盤面: 19路・13路

## クラス構造

- **クラス名**: `SiegeStrategy`
- **登録名**: `ai:攻城戦略`
- **継承**: 既存の戦略基底クラスと同様
- **KataGoクエリ**: 1ステージ（クリーンクエリのみ、humanSLProfile不要）
  - policy, scoreLead, ownership を取得

## フェーズ管理

### フェーズ切替

```
序盤フェーズ (Concede Phase)
  ↓ 切替条件を満たしたら
攻撃フェーズ (Attack Phase)
```

**切替条件（AND）:**
1. `current_move >= siege_transition_move`
2. `siege_min_group_size` 以上の不安定な相手石群が存在する

**例外:** 全体の60%の手数を過ぎたら条件2を無視して無条件移行（プレッシャーモード）。

## 序盤フェーズ（Concede Phase）

### 目的
相手に地を与え、大模様を張らせる。相手の石群が大きく不安定になる展開を誘導する。

### 着手選択ロジック

1. クリーンクエリで policy + scoreLead + ownership を取得
2. 悪手フィルタ: `loss > concede_max_loss` の手を除外
3. 甘受スコア計算:
   ```
   concede_score = min(loss, concede_max_loss) / concede_max_loss
   ```
   - loss=0（最善手）→ concede_score=0（選ばれにくい）
   - loss=上限 → concede_score=1（選ばれやすい）
4. 重み計算: `concede_weight = policy × concede_score`
5. 重み付きランダム選択

### 狙い
- 最善手を避けつつ、壊滅的な悪手も避ける
- 自然と相手に地を与え、相手の石群が大きくなる展開になる

## 攻撃フェーズ（Attack Phase）

### ターゲット選定

毎手、盤面のownershipデータからターゲットを特定する。

1. **相手石のグループ化**: 盤面上の相手の石を連結グループに分類（上下左右の隣接判定、自前ロジック）
2. **不安定度の評価**: 各グループの平均ownershipの不安定度を算出
   ```
   instability = 1 - |avg_ownership|
   ```
   `instability >= siege_instability_min` のグループを抽出
3. **ターゲットスコア**: 最大スコアのグループをプライマリターゲットに選定
   ```
   target_score = group_size × instability
   ```
4. サブターゲットも保持（2番目に大きいスコアのグループ）— プライマリが安定化したら切り替え

### 攻撃重み計算

各候補手について:
```
min_dist = min(距離 to ターゲットグループの各石)
proximity = exp(-0.5 × min_dist² / siege_proximity_stddev²)
attack_weight = policy × proximity × target_instability
```

### 悪手フィルタ
`loss > siege_max_loss` の手を除外

`target_instability` はターゲットグループの `instability` 値（0〜1）。ターゲットが不安定なほど攻撃重みが高くなる。

### ターゲットが見つからない場合
不安定な大石群がなければ、最も不安定な領域にプレッシャーをかける手を選ぶ（フォールバック）。

## パラメータ

| パラメータ | デフォルト値(19路) | デフォルト値(13路) | 説明 |
|---|---|---|---|
| siege_transition_move | 40 | 25 | 攻撃フェーズ移行の最小手数 |
| siege_min_group_size | 5 | 4 | ターゲット最小グループサイズ |
| concede_max_loss | 4.0 | 3.0 | 序盤の許容最大損失（目） |
| siege_max_loss | 5.0 | 4.0 | 攻撃時の許容最大損失（目） |
| siege_proximity_stddev | 3.0 | 2.5 | ターゲット近接重みの標準偏差 |
| siege_instability_min | 0.3 | 0.3 | ターゲット判定の最小不安定度 |

## GUI設定

constants.pyの `AI_OPTION_VALUES` に `ai:攻城戦略` を追加。既存モードと同様にGUIのドロップダウンから選択可能にする。

## 全体フロー

```
1. クリーンクエリ（1回） → policy, scoreLead, ownership 取得
2. フェーズ判定
   ├─ 序盤: concede_weight = policy × concede_score → 重み付き選択
   └─ 攻撃: ターゲット選定 → attack_weight = policy × proximity × instability → 重み付き選択
3. 悪手フィルタ（各フェーズで閾値が異なる）
4. 重み付きランダム選択
```
