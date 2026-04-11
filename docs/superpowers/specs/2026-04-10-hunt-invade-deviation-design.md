# HuntStrategy Invadeフェーズ 第一感ぶれ導入

## 背景・動機

HuntStrategyの対局ログで最善手一致率が50%超、平均損失が0.5目程度と「強すぎる」状態。
棋風（侵入→攻撃のスタイル）は好ましいが、もう少し人間らしいブレが欲しい。

**目標値:**
- 最善手一致率: 30-40%（現状50%超）
- 平均損失: 1.0目前後（現状0.5目）
- Huntフェーズの攻撃精度は維持

## 現状分析

対局ログ（game_20260410_132202）の内訳（約101手）:

| 経路 | 手数 | 特徴 |
|---|---|---|
| 重み付きランダム選択（Selected） | 75 | humanPolicy × proximity × intensity × territory_avoid |
| 安全弁v2強制 | 9 | 常にAI最善手 |
| タイブレーク | 8 | スコア差でAI寄り |
| エンドゲーム | 9 | humanPolicy最上位を確定選択 |

安全弁+タイブレーク+エンドゲームだけで26手（約26%）が事実上AI最善手。
残りの重み付き選択でも、9段humanPolicyがAI最善手と高い相関を持つため一致しやすい。

Invadeフェーズが50手以上で大多数を占める一方、Huntフェーズは攻撃精度が重要。

## 設計

### 方針

Invadeフェーズの着手選択時に、HumanStyleStrategyの第一感ぶれロジックを**適用確率パラメータ付き**で組み込む。Huntフェーズ・エンドゲームには影響しない。

### 新パラメータ

| パラメータ名 | GUI表示 | 選択肢 | デフォルト |
|---|---|---|---|
| `hunt_invasion_deviation_rate` | 侵入時の第一感ぶれ適用率 | 0.5 / 0.7 / 0.9 | 0.7 |

### 動作フロー

Invadeフェーズの重み付き候補リスト構築後、既存の重み付きランダム選択の**前**に割り込む:

1. `phase_name == "Invade"` を確認（Huntフェーズ・エンドゲームはスキップ）
2. `random() < hunt_invasion_deviation_rate` を判定（不成立なら通常の重み付き選択へ）
3. 上位3候補を重み（combined weight）でソート
4. 各候補のStage 2スコアからlossを算出
5. `0.5 <= loss < 2.0` の候補があれば、その中の最小loss手を**確定選択**
6. 条件を満たす候補がなければ、通常の重み付き選択にフォールバック

### 既存ロジックとの関係

| 既存ロジック | 影響 |
|---|---|
| 安全弁v1/v2 | 変更なし（第一感ぶれより先に評価される） |
| タイブレーク | 変更なし（第一感ぶれより先に評価される） |
| エンドゲーム | 変更なし（第一感ぶれより先に評価される） |
| Huntフェーズ重み付き選択 | 変更なし |
| 悪手フィルタ | 変更なし（第一感ぶれの入力は悪手フィルタ通過後の候補） |

### コード挿入位置

`ai.py` HuntStrategy.generate_move() 内、タイブレーク処理（`ai.py:3952`付近）の後、
重み付き選択（`ai.py:3985` `weighted_selection_without_replacement`）の前に挿入。

```python
# --- Invadeフェーズ: 第一感ぶれ ---
if phase_name == "Invade" and len(top5) >= 2 and move_infos:
    deviation_rate = hunt_invasion_deviation_rate
    if random.random() < deviation_rate:
        _score_by_gtp_dev = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
        dev_candidates = []
        for m, w in top5[:3]:
            gtp = m.gtp()
            if gtp in _score_by_gtp_dev and best_score is not None:
                loss = player_sign * (best_score - _score_by_gtp_dev[gtp])
                if 0.5 <= loss < 2.0:
                    dev_candidates.append((m, loss))
        if dev_candidates:
            # 最小loss手を確定選択
            dev_move, dev_loss = min(dev_candidates, key=lambda x: x[1])
            # 選択して返す
```

## 変更ファイル

| ファイル | 変更内容 |
|---|---|
| `katrain/core/ai.py` | HuntStrategy.generate_move() に第一感ぶれロジック追加、パラメータ読み取り |
| `katrain/core/constants.py` | AI_OPTION_VALUES に `hunt_invasion_deviation_rate` 追加 |
| `katrain/config.json` | ai:hunt セクションにデフォルト値追加 |
| `C:\Users\iwaki\.katrain\config.json` | 同上（ローカル設定） |
| `katrain/i18n/*.po` | 翻訳追加 |
| `katrain/i18n/*.mo` | `python tools/compile_mo.py` で再コンパイル |
| `.claude/rules/ai-parameters.md` | パラメータテーブル更新 |

## 期待効果

- Invade手（全体の約50%）のうち70%（デフォルト）に第一感ぶれ適用
- 偏差発動時は0.5-2.0目のlossが加わる → 平均損失が0.5→1.0前後に上昇
- AI最善手一致率が50%→30-40%程度に低下する見込み
- Huntフェーズの攻撃精度は維持
- エンドゲームの精度は維持
