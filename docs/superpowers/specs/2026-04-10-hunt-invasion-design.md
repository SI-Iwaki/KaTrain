# HuntStrategy 侵入フェーズ追加設計

## 概要

HuntStrategy（狩猟戦略）に**侵入フェーズ（Invade）**を追加し、序盤〜中盤初期に相手の勢力圏へ積極的に打ち込む動作を実現する。

### 背景・課題

現在のHuntStrategyは `find_targets()` が石グループターゲットを検出しない序盤に、`weight = humanPolicy` のみ（普通の9段）にフォールバックする。これにより序盤に特徴が出ず、攻撃的な棋風が発揮されない。

### 目標

- 序盤から相手の勢力圏に侵入し、接触戦で石を弱くして狩猟フェーズに繋げる
- 石グループと勢力圏の両方を常に攻撃対象とする
- 「ターゲットなし → 9段フォールバック」を廃止し、常にどこかを攻め続ける
- 攻撃性を優先するが、無謀な全滅レベルの大損は避ける

---

## アーキテクチャ

### アプローチ: 統合ターゲット方式

侵入対象（ownershipベースの領域）と石グループターゲットを1つの統合ターゲットリストにまとめ、proximity計算の対象座標として合算する。

### フェーズ構成（3フェーズ）

| フェーズ | 条件 | 動作 |
|---|---|---|
| **Invade** | 石グループターゲットなし、侵入対象あり | ownership領域を侵入対象としてproximity重み付け |
| **Hunt** | 石グループターゲットあり | 侵入対象 + 石グループ座標を統合してproximity重み付け |
| **Endgame** | 手数閾値超過（現行通り） | humanPolicy最上位手を直接選択 |

初手（盤面に石がない場合）のみ、従来通りhumanPolicyのみで着手。

---

## 侵入対象の検出ロジック

### ownership領域の抽出

通常解析完了後の `ownership` グリッドから侵入対象の交点を抽出する:

```python
# KataGoのownershipは常にBlack視点: -1.0(White確定) 〜 +1.0(Black確定)
# 着番に応じて符号を反転: player_sign = 1 (Black) or -1 (White)
# 自分視点のownership = ownership[y][x] * player_sign
# 相手のownership強度 = max(0, -ownership[y][x] * player_sign)

invasion_coords = set()
opp_strength_map = {}  # intensity計算用に保存
for (x, y) on board:
    own = ownership[y][x] * player_sign  # 自分視点に変換
    opp_strength = max(0, -own)  # 相手の強度 (0.0〜1.0)
    if hunt_invasion_min <= opp_strength <= hunt_invasion_max:
        invasion_coords.add((x, y))
        opp_strength_map[(x, y)] = opp_strength
```

- `opp_strength < hunt_invasion_min` → 相手の地でもないので無視
- `opp_strength > hunt_invasion_max` → 確定地で侵入が無謀

### 統合ターゲット座標の構築

```python
# 1. 侵入対象（ownership領域）
invasion_coords = {ownershipが範囲内の交点}

# 2. 石グループターゲット（既存のfind_targets）
group_coords = 既存のターゲット石グループの座標集合

# 3. 統合
all_target_coords = invasion_coords | group_coords
```

### 侵入対象が空になるケース

- 初手（盤面に石がない） → humanPolicyのみ
- 相手の全交点が確定地 → 石グループターゲットのみで攻撃
- 相手のownershipが薄すぎる → 石グループターゲットのみ

---

## proximity計算

### 二種類のstddevの使い分け

各候補手について、統合ターゲット座標内で最も近い座標を探し、その座標の由来に応じてstddevを切り替える:

```python
for each candidate move (x, y):
    min_dist_sq = infinity
    nearest_type = None

    for (tx, ty) in all_target_coords:
        dist_sq = (x - tx)^2 + (y - ty)^2
        if dist_sq < min_dist_sq:
            min_dist_sq = dist_sq
            nearest_type = "invasion" if (tx,ty) in invasion_coords else "group"

    if nearest_type == "invasion":
        stddev = hunt_invasion_proximity_stddev
    else:
        stddev = hunt_proximity_stddev

    proximity = exp(-0.5 * min_dist_sq / stddev^2)
```

### intensity（強度）の計算

- **侵入対象由来**: `intensity = opp_strength_map[(tx,ty)]`（最近接侵入交点の相手ownership強度。0.2〜0.7の範囲）
- **石グループ由来**: `intensity = instability`（既存と同じ）

### 最終的な重み計算式

```
weight = humanPolicy[idx] × proximity × intensity
```

計算式の構造は現行のAttackフェーズと同一。変更点はターゲット座標に侵入対象が含まれるようになったこと。

---

## 悪手フィルタと損失許容

### 二段階の損失許容

| 状況 | 使用する閾値 |
|---|---|
| 石グループターゲットあり | `hunt_max_loss`（既存: 6.0） |
| 石グループターゲットなし（侵入のみ） | `hunt_invasion_max_loss`（新規） |
| 両方あり | `hunt_max_loss` を使用 |

### 段階的緩和は現行と同じ構造

```python
threshold = hunt_invasion_max_loss  # or hunt_max_loss
for relaxed in [threshold * 1.5, threshold * 2.0, 9.0]:
    if good_moves:
        break
```

### Safety Valve（安全弁）は変更なし

既存の Safety v1/v2（損失4.0目以上で最善手に強制切替）+ クロスバリデーションはそのまま維持。

---

## パラメータ定義

### 新規パラメータ

| パラメータ | GUI範囲 | 刻み | デフォルト(19路) | デフォルト(13路) | 説明 |
|---|---|---|---|---|---|
| `hunt_invasion_max_loss` | 2.0〜12.0 | 0.5 | 8.0 | 6.0 | 侵入時の許容最大損失（目） |
| `hunt_invasion_min` | 0.1〜0.5 | 0.05 | 0.2 | 0.2 | 侵入対象ownershipの下限 |
| `hunt_invasion_max` | 0.4〜0.9 | 0.05 | 0.7 | 0.7 | 侵入対象ownershipの上限 |
| `hunt_invasion_proximity_stddev` | 2.0〜8.0 | 0.5 | 5.0 | 4.0 | 侵入用の近接重み標準偏差 |

### 既存パラメータ（変更なし）

| パラメータ | デフォルト(19路) | デフォルト(13路) | 説明 |
|---|---|---|---|
| `hunt_max_loss` | 6.0 | 4.0 | 攻撃時の許容最大損失（目） |
| `hunt_min_group_size` | 5 | 4 | ターゲット最小グループサイズ |
| `hunt_proximity_stddev` | 3.0 | 2.5 | ターゲット近接重みの標準偏差 |
| `hunt_instability_min` | 0.3 | 0.3 | ターゲット判定の最小不安定度 |

---

## 変更対象ファイル

1. **`katrain/core/ai.py`** — HuntStrategy.generate_move() に侵入ロジック追加
2. **`katrain/core/constants.py`** — AI_OPTION_VALUES と AI_OPTION_ORDER に4パラメータ追加
3. **`katrain/config.json`**（パッケージ同梱） — ai:hunt セクションに4パラメータのデフォルト値追加
4. **`C:\Users\iwaki\.katrain\config.json`**（ローカル） — 同上
5. **`katrain/i18n/`** — 新パラメータの翻訳（日本語・英語）+ .mo コンパイル
6. **`.claude/rules/ai-parameters.md`** — パラメータテーブル更新

---

## ログ出力

```
[HuntStrategy] Phase: Invade (invasion_targets=23, no group targets)
[HuntStrategy] Phase: Hunt (invasion_targets=15, group_targets=1, primary: size=7, instability=0.45)
[HuntStrategy] Phase: Endgame
```

---

## テスト・検証方法

1. `debug_level: 1` で起動
2. 序盤でPhase表示が `Invade` になることを確認
3. 相手の勢力圏付近に着手が集中することを確認
4. 石グループが弱くなったらPhase表示が `Hunt` に変わることを確認
5. Safety Valveが発動した場合のログを確認（大損回避が機能しているか）
6. 各パラメータを変更して挙動の変化を確認
