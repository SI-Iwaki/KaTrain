# SiegeStrategy humanPolicy導入 設計書

**日付**: 2026-04-10
**対象**: `katrain/core/ai.py` SiegeStrategyクラス

## 概要

SiegeStrategy（攻城戦略）の着手選択に humanPolicy の重みを導入する。
現在は KataGo の通常 policy で重み付けしているが、FightingStrategy (human) と同様に
humanSLProfile から取得した humanPolicy に置き換え、人間らしい着手選択を実現する。

## 変更方針

### 2段階クエリの導入

FightingStrategy (human) / HumanStyleStrategy と同じパターン：

- **Stage 1**: `humanSLProfile="rank_9d"`, `maxVisits=800` → humanPolicy 取得
- **Stage 2**: `humanSLProfile`なし, `maxVisits=600`, `wideRootNoise=0.0` → クリーンスコア取得

CLAUDE.md のルールに従い、Stage 1 の scoreLead はフィルタ判定に使用しない。

### フェーズ別の着手選択

#### Concede フェーズ（序盤）

| 項目 | 現在 | 変更後 |
|---|---|---|
| 重み | `policy × concede_score` | `humanPolicy × concede_score` |
| フィルタ | 通常クエリの loss | Stage 2 クリーンスコアの loss |
| 閾値 | `concede_max_loss`（19路:4.0, 13路:3.0） | 同じ |

#### Attack フェーズ（攻撃）

| 項目 | 現在 | 変更後 |
|---|---|---|
| 重み | `policy × proximity × target_instability` | `humanPolicy × proximity × target_instability` |
| フィルタ | 通常クエリの loss | Stage 2 クリーンスコアの loss |
| 閾値 | `siege_max_loss`（19路:5.0, 13路:4.0） | 同じ |

### 追加機能

#### タイブレーク

FightingStrategy (human) と同じロジック：
- humanPolicy の比率が 1.05 未満、または visits が逆転/同数の場合に発動
- スコア差 >= 2.0 目なら高スコア側を確定選択

#### 安全弁 (Safety Valve)

- 最高重みの手の損失 >= 4.0 目の場合、最善スコアの手に強制切替
- 大悪手の暴走を防止

#### エンドゲーム処理

- 終盤閾値: 9路=32手、他=`ceil(0.5 × board_area)`
- 閾値以降は戦略重み（proximity, instability, concede_score）を無視
- top humanPolicy の手を選択

### 変更しないもの

- フェーズ切替ロジック（手数条件 + ターゲット判定）
- `_find_targets()` のグループ検出ロジック
- GUI パラメータ（既存の siege 系パラメータ）
- 9路盤非対応（19路・13路のみ）

## 変更対象ファイル

- `katrain/core/ai.py` — SiegeStrategy クラス
  - `generate_move()` に 2 段階クエリを実装
  - `_generate_concede()` の policy → humanPolicy 置換 + Stage 2 フィルタ
  - `_generate_attack()` の policy → humanPolicy 置換 + Stage 2 フィルタ
  - タイブレーク、安全弁、エンドゲーム処理を追加

## パラメータ（変更なし）

| パラメータ | 19路 | 13路 |
|---|---|---|
| siege_transition_move | 40 | 25 |
| siege_min_group_size | 5 | 4 |
| concede_max_loss | 4.0 | 3.0 |
| siege_max_loss | 5.0 | 4.0 |
| siege_proximity_stddev | 3.0 | 2.5 |
| siege_instability_min | 0.3 | 0.3 |

## エンジン設定

| 場所 | 値 | 役割 |
|---|---|---|
| Stage 1 `maxVisits` | 800 | humanSL 着手選択 |
| Stage 2 `maxVisits` | 600 | クリーンスコア検証 |
