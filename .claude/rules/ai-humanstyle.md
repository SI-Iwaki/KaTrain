---
description: HumanStyleStrategy悪手フィルタの実装詳細・パラメータ・チェックリスト（ai.py編集時に参照）
paths:
  - "katrain/core/ai.py"
---

# HumanStyleStrategy 悪手フィルタ実装ガイド

## 悪手フィルタの仕組み

`HumanStyleStrategy.generate_move()` でKataGoの`moveInfos`を使い、大悪手を除外してからhumanPolicy重みで選択する。

### スコア計算の注意点

- KataGoの`scoreLead`は**常にBlackの視点**（正 = Black有利）。Whiteの場合は符号反転が必要
- `player_sign = 1 if Black else -1` を使い `loss = player_sign * (best_score - score)` で計算
- 参照点は`move_infos[0]`（最多探索手）ではなく、現在プレイヤーにとっての**真の最善スコア**を使う
  - `move_infos[0]`はhumanSLProfileの影響で最善手≠最多探索手になることがある
- `moveInfos`に含まれない手（探索されなかった手）も除外する

## フェーズ別閾値の詳細

- 序盤境界: `math.ceil(0.14 × 盤面マス数)` — 19路: 1〜50手目、9路: 1〜11手目
- 小さいほど強い（悪手が減る）が、人間らしさも減る
- 現在値: 19路 OPENING=2.8 / NORMAL=5.9、9路 OPENING=0.5 / NORMAL=3.3

## 第一感ぶれ（first_impression_deviation）

19路盤専用・中盤以降（opening_boundary以降）のみ発動。

- 悪手フィルター通過後のhumanPolicy重み付き候補から**上位3位**を取り出す
- そのうち損失 `0.5 <= loss < 2.0` の手があれば、損失最小の手を**確定選択**（確率的選択を行わない）
- 損失0.5未満（ほぼベスト）や2.0以上の手は対象外
- 候補がなければ通常の確率的選択にフォールバック
- **序盤は無効**（`current_move < opening_boundary` の手番は発動しない）
- 設定: `first_impression_deviation: bool`（デフォルト false、起動時リセットなし）

### green_blend（第一感緑ブレンド）

`first_impression_deviation` ON 時の追加オプション。

- 条件: 第一感1位（humanPolicy最大）が緑（0 < loss < 0.5）かつスコア最善でない、かつ上位3位内に 0.5 <= loss < 2.0 の手がある
- 動作: 50%で緑の第一感1位、50%で偏差候補（0.5-2.0の最小損失手）を選択
- 条件不成立時: 既存の `first_impression_deviation` 動作（0.5-2.0の最小損失を確定選択）にフォールバック
- 設定: `first_impression_green_blend: bool`（デフォルト false、起動時リセットなし）

## policy_temperature（ポリシー温度）

humanPolicy重みに対して温度スケーリングを適用する。

```python
moves = [(m, w ** (1.0 / policy_temperature)) for m, w in moves]
```

- `1.0`（デフォルト）: 変化なし
- `> 1.0`: 確率分布をフラット化 → 低確率手が選ばれやすくなる（≥0.5損失手が増える）
- `< 1.0`: 確率分布をシャープ化 → 最高確率手に集中
- 設定: `policy_temperature: float`（1.0〜2.0）
- **起動時に 1.0 にリセット**される（`base_katrain.py` の `_load_config` 末尾処理）

## 大差フィルター（9路盤・13路盤）

`analysis["rootInfo"]["winrate"]` を使用。`rootInfo.winrate` は常にBlack視点のため、White番は `1.0 - winrate` で変換。

- **大差勝ち（勝率95%+）**: 最善手（`best_gtp_by_score`）を除外し、`GREEN_MOVE_THRESHOLD`以内の緑手のみからhumanPolicy重みで選択。緑手がない場合・推奨手が最善手のみの場合は最善手を打つ（`return`で確実に実行）
- **大差負け（勝率25%未満）**: humanPolicyを無視して最善手のみを打つ。勝率が50%を超えるまで継続（ヒステリシス）。状態は `self.game._human_ai_big_loss_mode` で管理
- 定数: `WIN_RATE_THRESHOLD = 0.95`, `BIG_LOSS_ENTER = 0.25`, `BIG_LOSS_EXIT = 0.50`

## パラメータ変更チェックリスト

### `OPENING_THRESHOLD` / `NORMAL_THRESHOLD` を変更する場合

- [ ] `katrain/core/ai.py` の `HumanStyleStrategy.generate_move()` 内（盤面サイズ別の条件分岐）
- [ ] CLAUDE.md の「現在のパラメータ値」テーブルを更新

### `first_impression_deviation` の動作を変更する場合

- [ ] `katrain/core/ai.py` — 損失範囲 `0.5 <= loss < 2.0` や上位N位数を変更
- [ ] `katrain/core/constants.py` — `AI_OPTION_VALUES` に既に `"bool"` で登録済みか確認
- [ ] CLAUDE.md の「第一感ぶれ」セクションを更新

### `policy_temperature` の動作を変更する場合

- [ ] `katrain/core/ai.py` — スケーリング式 `w ** (1.0 / policy_temperature)` の確認
- [ ] 起動時リセットが必要な場合は `base_katrain.py` の `_load_config` 末尾も確認
- [ ] CLAUDE.md の「ポリシー温度」テーブルを更新

### `maxVisits` を変更する場合

**3箇所を必ず同じ値に揃える**（不一致だとフィルタが不安定になる）

| 場所 | 設定項目 | 役割 |
|------|----------|------|
| `katrain/core/ai.py` 約1325行目 | `override_settings["maxVisits"]` | HumanSL着手選択クエリ |
| KaTrain GUI → `C:\Users\iwaki\.katrain\config.json` | `max_visits` | 事後分析クエリ |
| `C:\Users\iwaki\.katrain\analysis_config.cfg` 51行目 | `maxVisits` | デフォルト値 |

- [ ] `katrain/core/ai.py` — `override_settings` の `"maxVisits": XXX`
- [ ] KaTrain GUI「エンジン設定 → 分析時の最大探索手数」→「設定を更新」
- [ ] `C:\Users\iwaki\.katrain\analysis_config.cfg` — `maxVisits = XXX`

## GREEN_MOVE_THRESHOLD 調整メモ（13路盤）

> 着手生成時（`humanSLProfile` + `wideRootNoise=0.04` 付き）と事後分析でスコア推定に0.5目程度のズレが生じるため、閾値選択はこのズレを考慮する必要がある。

### 検証済みの閾値と結果（13路盤・白番・Human-like 9段）

| 閾値 | 正確度 | 平均損失 | 最善手一致率 | 上位5候補一致率 | ≥1.5目 | ≥3目 |
|------|--------|----------|-------------|---------------|--------|------|
| 1.5 | 84.2 | 0.39 | 42.5% | 77.5% | 2 | 1 |
| 1.0 | 95.7 | 0.17 | 73.3% | 80.0% | 1 | 0 |
| **1.2（現在採用）** | 中間値 | — | — | — | — | — |

- **1.5**: スコアズレにより事後分析で1.9目損失の手が緑判定される問題あり
- **1.0**: 緑手なし→最善手の頻度が高すぎる
- **1.2**: 1.0と1.5の中間値として採用（現在の設定値）

## デバッグ有効化手順

```
C:\Users\iwaki\.katrain\config.json の "debug_level": 0 → 1 に変更
python -m katrain で起動
確認後 debug_level を 0 に戻す
```
