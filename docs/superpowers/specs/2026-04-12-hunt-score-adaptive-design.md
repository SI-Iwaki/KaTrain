# HuntStrategy スコア適応型損失制御

## 概要

HuntStrategyに局面のスコア差に応じた2つの適応機能を追加する。

1. **劣勢時の損失制限** -- 負けている局面で無理な手を打たせない
2. **勝勢時の最善手weight抑制** -- 大差勝ち局面でAI最善手一致率を下げ、棋風を維持した攻撃的な手を増やす

## 動機

- 6目以上劣勢なのに段階的緩和で最大12目の損失を許容するのは人間らしくない。負けているときは堅実に打つべき
- 15目以上勝勢の局面でAI最善手ばかり選ぶと一致率が不自然に高くなる。勝勢では棋風を活かした手を積極的に選びたい

## 機能1: 劣勢時の損失制限

### 仕様

- **発動条件**: `best_score * player_sign < -6.0`（自分が6目以上劣勢）
  - `best_score`: Stage 2クリーンクエリの最善手のscoreLead
  - `player_sign`: 黒=1, 白=-1
- **効果**: 損失上限を4.0にキャップ
  - `effective_max_loss = min(hunt_max_loss, 4.0)`
  - `effective_invasion_max_loss = min(hunt_invasion_max_loss, 4.0)`
  - 段階的緩和もすべて4.0でキャップされる
  - 4.0で候補が見つからなければ即failsafe（最善手を選択）
- **実装方式**: ハードコード（常時有効、GUI設定なし）
- **適用範囲**: Hunt / Invade / Hunt(9-dan) 全phase
- **閾値**: `LOSING_THRESHOLD = -6.0`, `LOSING_MAX_LOSS = 4.0`（定数としてコード内に定義）

### ログ出力

```
Losing restrict: score_lead=-8.2, max_loss 6.0 -> 4.0
```

## 機能2: 勝勢時の最善手weight抑制

### 仕様

- **発動条件**: `best_score * player_sign > 15.0`（自分が15目以上勝勢）
- **効果**: AIの最善手（`best_gtp_by_score`）のcombined weightに抑制係数0.3を掛ける
- **適用タイミング**: combined weight計算完了後、最終選択の直前
- **実装方式**: チェックボックスでオン/オフ切替
- **適用範囲**: Hunt / Invade / Hunt(9-dan) 全phase
- **閾値**: `WINNING_THRESHOLD = 15.0`, `WINNING_SUPPRESS_FACTOR = 0.3`（定数としてコード内に定義）

### パラメータ

| パラメータ名 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `hunt_winning_suppress_enabled` | bool | False | 勝勢時の最善手weight抑制を有効化 |

### 安全性

- 最善手しかまともな候補がない場合（他のcombined weightが極端に低い）、抑制後も最善手のweightが相対的に最大となるため、最善手が選ばれる
- 既存のSafety valve（top weighted moveの損失≥4.0で最善手に強制変更）は引き続き有効
- チェックボックスOFFで即座に無効化可能

### ログ出力

```
Winning suppress: score_lead=18.5, best_move=Q16 weight 0.4200 -> 0.1260
```

## 2機能の関係

| 局面スコア差 | 機能1（劣勢制限） | 機能2（勝勢抑制） |
|---|---|---|
| < -6.0（6目以上劣勢） | 有効 | 適用外 |
| -6.0 ~ +15.0 | 適用外 | 適用外 |
| > +15.0（15目以上勝勢） | 適用外 | 有効（ONの場合） |

競合なし（相互排他的な条件）。

## 変更対象ファイル

| ファイル | 変更内容 |
|---|---|
| `katrain/core/ai.py` | HuntStrategy.generate_move()にスコア判定ロジック追加 |
| `katrain/core/constants.py` | `hunt_winning_suppress_enabled` チェックボックス定義追加 |
| `katrain/config.json` | デフォルト値追加 |
| `C:\Users\iwaki\.katrain\config.json` | ローカル設定にキー追加 |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 英語ヘルプテキスト |
| `katrain/i18n/locales/ja/LC_MESSAGES/katrain.po` | 日本語ヘルプテキスト |
| `.claude/rules/ai-parameters.md` | パラメータテーブル更新 |
