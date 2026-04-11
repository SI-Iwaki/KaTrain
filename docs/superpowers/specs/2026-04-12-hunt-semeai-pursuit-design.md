# 設計書: HuntStrategy 攻め合い追撃機能（Semeai Pursuit）

**日付**: 2026-04-12
**対象**: HuntStrategy / HuntDivergenceStrategy
**ステータス**: 設計承認済み

## 問題

HuntStrategyで大石の攻め合い（セメアイ）中、KataGoが手数を読み切って「勝ち」と判断すると、残りの詰め手を打たずに他の場所に手抜きする。これはAIとしては正しい判断だが、人間の高段者にも死活判断が難しい局面では不自然・不誠実に映る。

### 技術的原因

`find_targets()` は `instability = 1.0 - abs(avg_ownership)` で判定し、`instability_min = 0.3` を下回るとターゲットから除外する。KataGoが死と判定するとownershipが±1.0に近づき、instabilityが閾値を割ってターゲットから外れる。相手が勝負手を打っても、既にターゲットを見失っているため無関係な場所に着手する。

## 成功基準

- 攻め合い中に相手が勝負手を打った場合、手抜きせず詰め手を継続する
- 人間の高段者が見ても死と判断できる程度まで詰めてから手抜きする
- 完全な取り上げ（石の除去）までは不要

## 設計方針

**アプローチA「ターゲット記憶 + 再評価」方式**を採用。前手番のターゲット情報を記憶し、相手がその近くに打ったら追撃判定を行い、条件を満たせばターゲットリストに再注入する。

## 詳細設計

### 1. ターゲット記憶

`generate_move()` の末尾で、現在のターゲット石群情報をゲームノードの属性に保存する：

```python
cn.hunt_previous_targets = [
    {
        "coords": [(x1, y1), (x2, y2), ...],  # 石群の全座標
        "instability": 0.45,                    # 検出時のinstability
        "liberties": 5,                          # 検出時のリバティ数
        "size": 12,                              # 石数
    },
    ...
]
```

保存タイミングは着手選択後。追撃で復活したターゲットも含めて保存する（次手番でも追撃が連鎖可能）。ターゲットが0個でも空リストを保存する。

### 2. 勝負手検出

次の手番で、相手の着手を検査する：

1. 2手前のノード（＝自分の前手番）から `hunt_previous_targets` を取得
2. 相手の着手座標と各ターゲット石群の最短距離を計算
3. 近接距離 ≤ `hunt_pursue_proximity`（デフォルト: 2路）なら「勝負手候補」としてフラグ

### 3. 追撃判定ロジック

勝負手候補がフラグされた後、以下の3段階で追撃可否を判定する：

#### Step 1: 石群がまだ盤上にあるか

ターゲット石群の座標を現在の盤面と照合し、石が物理的に除去されていれば追撃不要。

#### Step 2: リバティ数チェック（最重要）

ターゲット石群の現在のリバティ数を算出：

- リバティ ≥ `hunt_pursue_min_liberties`（デフォルト: 3） → **追撃する**
- リバティ < 閾値 → Step 3へ

#### Step 3: ownership確信度チェック（補助）

リバティが少なくても、ownershipが不十分なら追撃する：

- |avg_ownership| < 閾値 → **追撃する**
- |avg_ownership| ≥ 閾値 → **追撃しない**

閾値は `hunt_pursue_ownership_threshold`（デフォルト: 0.85）。石群サイズで調整：

| 石群サイズ | ownership閾値 |
|---|---|
| < 10 | 0.85 |
| 10-14 | 0.90（+0.05） |
| ≥ 15 | 0.95（+0.10） |

#### 判定まとめ

```
盤上にない          → 追撃しない
リバティ ≥ 3        → 追撃する
|ownership| < 閾値  → 追撃する（閾値は石群サイズで変動）
それ以外            → 追撃しない
```

### 4. 追撃時の着手生成

追撃判定が「追撃する」となった場合、`find_targets()` の結果に追撃対象をターゲットとして注入する：

- 実際の現在instability値をそのまま使う（最低値 0.2 にクランプ）
- proximity_stddev は通常の `hunt_proximity_stddev` をそのまま使用
- 以降は通常のHuntフェーズとして処理（新しい着手生成ロジックは追加しない）

### 5. 処理フロー

`generate_move()` 内での処理順序：

```
1. Stage 1 / Stage 2 クエリ（既存）
2. 悪手フィルタ（既存）
3. find_targets()（既存）
4. ★ 追撃判定（新規）:
   a. hunt_pursue_enabled がオフ → スキップ
   b. エンドゲームフェーズ → スキップ
   c. 2手前ノードから hunt_previous_targets を取得
   d. 相手の着手がターゲット付近か判定
   e. 盤上存在 → リバティ → ownership で追撃可否を判定
   f. 追撃する → find_targets の結果に石群を注入
5. 侵入対象検出（既存）
6. フェーズ判定（既存 — 追撃注入済みならHuntフェーズになる）
7. 重み付け・着手選択（既存）
8. ★ ターゲット記憶保存（新規）:
   cn.hunt_previous_targets = 現在のターゲット情報
```

### 6. GUI設定

AI設定画面にチェックボックスを1つ追加：

- **パラメータ名**: `hunt_pursue_enabled`
- **デフォルト**: `true`
- **日本語ラベル**: 「攻め合い追撃」
- **英語ラベル**: 「Semeai pursuit」
- **日本語ヘルプ**: 「攻め合い中に相手が勝負手を打った場合、手抜きせず詰め手を継続します」
- **英語ヘルプ**: 「Continue playing killing moves when the opponent resists during a capturing race」

### 7. config.json 隠し閾値パラメータ

GUIには出さないが、config.jsonの手動編集で調整可能：

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `hunt_pursue_proximity` | 2 | 勝負手判定の近接距離（路） |
| `hunt_pursue_min_liberties` | 3 | この数以上のリバティなら無条件追撃 |
| `hunt_pursue_ownership_threshold` | 0.85 | ownership確信度の閾値 |

### 8. 適用範囲

- **HuntStrategy**: `hunt_pursue_enabled` を参照
- **HuntDivergenceStrategy**: 親クラスを継承するため自動適用
- **エンドゲームフェーズ**: 無効（`hunt_endgame_move` 判定が先に走る）
- **将来展開**: Siege/FightingStrategyにも同じ「ターゲット記憶」パターンで展開可能

### 9. ログ出力

追撃発動時：
```
Pursue: opponent played [E5] near previous target (size=12, liberties=4, ownership=0.78) → re-targeting
```

追撃スキップ時：
```
Pursue: opponent played [E5] near previous target but stones confirmed dead (liberties=1, ownership=0.92) → no pursuit
```

## 変更対象ファイル

| ファイル | 変更内容 |
|---|---|
| `katrain/core/ai.py` | HuntStrategy.generate_move() に追撃判定・ターゲット記憶を追加 |
| `katrain/core/constants.py` | AI_OPTION_VALUES にチェックボックス定義を追加 |
| `katrain/config.json` | hunt_pursue_enabled, 隠しパラメータのデフォルト値追加 |
| `C:\Users\iwaki\.katrain\config.json` | 同上（ローカル設定にも追加） |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 英語ヘルプテキスト |
| `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | 日本語ヘルプテキスト |
| `.claude/rules/ai-parameters.md` | パラメータテーブル更新 |
