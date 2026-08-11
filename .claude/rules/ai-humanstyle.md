---
description: HumanStyleStrategy悪手フィルタの実装詳細・パラメータ・チェックリスト（ai.py編集時に参照）
paths:
  - "katrain/core/ai.py"
---

# HumanStyleStrategy 悪手フィルタ実装ガイド

## 悪手フィルタの仕組み

`HumanStyleStrategy.generate_move()` でKataGoの`moveInfos`を使い、大悪手を除外してからhumanPolicy重みで選択する。

### 二段階クエリ

`humanSLProfile`付きクエリの`scoreLead`はバイアスされ、人間モデルが高確率を与える手のスコアが楽観的に歪められる。そのため二段階でクエリを送信する:

1. **Stage 1（humanSLProfile付き）**: `humanPolicy`を取得するためのクエリ
2. **Stage 2（humanSLProfileなし・wideRootNoise=0）**: 正確な`scoreLead`を取得するためのクリーンクエリ

**両ステージの実効 visits は config `max_visits`（現在 1000）**。旧コードは dict に
800/600 を書いていたが extra_settings の maxVisits は top-level に負けて効かない
dead キーだった（2026-08-11 に除去・挙動不変。詳細は ai-parameters.md「エンジン設定」）。
悪手フィルタ・first_impression_deviation・green_blendのスコア判定はすべてStage 2のクリーンな`moveInfos`を使用する。Stage 2が失敗した場合はStage 1の`moveInfos`にフォールバック（HumanStyle系。**Jigo は 2026-08-11 から Stage1 が 1visit の humanPolicy 取得専用になったため、Stage2 失敗は KataGo 最善手へフォールバック**）。

### スコア計算の注意点

- KataGoの`scoreLead`は**常にBlackの視点**（正 = Black有利）。Whiteの場合は符号反転が必要
- `player_sign = 1 if Black else -1` を使い `loss = player_sign * (best_score - score)` で計算
- 参照点は`move_infos[0]`（最多探索手）ではなく、現在プレイヤーにとっての**真の最善スコア**を使う
- `moveInfos`に含まれない手（探索されなかった手）も除外する

## フェーズ別閾値の詳細

- 序盤境界: `math.ceil(0.14 × 盤面マス数)` — 19路: 1〜50手目、9路: 1〜11手目
- 小さいほど強い（悪手が減る）が、人間らしさも減る
- 現在値: 19路 OPENING=2.8 / NORMAL=5.6、9路 OPENING=0.5 / NORMAL=3.3

## 第一感ぶれ（first_impression_deviation）

全盤面・中盤以降（opening_boundary以降）のみ発動。

- 悪手フィルター通過後のhumanPolicy重み付き候補から**上位3位**を取り出す
- そのうち損失 `0.5 <= loss < dev_loss_max` の手があれば、損失最小の手を**確定選択**（確率的選択を行わない）
  - `dev_loss_max`: 9路=1.5目、13路・19路=2.0目
- 損失0.5未満（ほぼベスト）や上限以上の手は対象外
- 候補がなければ通常の確率的選択にフォールバック
- **デフォルトでは序盤は無効**（`current_move < opening_boundary` の手番は発動しない）
- `first_impression_deviation_opening: true` で序盤でも発動可能（試験的オプション）
- 設定: `first_impression_deviation: bool`（デフォルト false、起動時リセットなし）
- 設定: `first_impression_deviation_opening: bool`（デフォルト false）

### green_blend（第一感緑ブレンド）

`first_impression_deviation` ON 時の追加オプション。

- 条件: 第一感1位（humanPolicy最大）が緑（0 < loss < 0.5）かつスコア最善でない、かつ上位3位内に 0.5 <= loss < dev_loss_max の手がある
- 動作: `green_blend_green_ratio`の確率で緑の第一感1位、残りで偏差候補（最小損失手）を選択
  - 0.6 → 緑寄り(60/40)、0.5 → 均等(50/50)、0.4 → dev寄り(40/60)
- 条件不成立時: 既存の `first_impression_deviation` 動作（最小損失を確定選択）にフォールバック
- 設定: `first_impression_green_blend: bool`（デフォルト false）
- 設定: `green_blend_green_ratio: float`（デフォルト 0.5、選択肢: 0.4/0.5/0.6）

## パラメータ変更チェックリスト

### `OPENING_THRESHOLD` / `NORMAL_THRESHOLD` を変更する場合

- [ ] `katrain/core/ai.py` の `HumanStyleStrategy.generate_move()` 内（盤面サイズ別の条件分岐）
- [ ] CLAUDE.md の「現在のパラメータ値」テーブルを更新

### `first_impression_deviation` の動作を変更する場合

- [ ] `katrain/core/ai.py` — 損失範囲 `0.5 <= loss < 2.0` や上位N位数を変更
- [ ] `katrain/core/constants.py` — `AI_OPTION_VALUES` に既に `"bool"` で登録済みか確認
- [ ] CLAUDE.md の「第一感ぶれ」セクションを更新

### `maxVisits` を変更する場合

**Stage1/Stage2 の visits は GUI の `max_visits`（config）がそのまま実効値**（2026-08-11 判明・
dead キー除去済み）。`extra_settings` に `maxVisits` を書いても top-level（`visits` 引数＝既定
`config["max_visits"]`）に負けて効かないので、GUI の `max_visits` を変えれば Stage1・Stage2・
事後分析がすべて連動する＝「Stage1 と GUI を揃える」は構造的に常時成立。特定クエリだけ
visits を変えたいときは `request_analysis(..., visits=N)` を**引数で**渡す（Jigo Stage1 の
`visits=1` がその例）。

| 場所 | 実効値 | 役割 |
|------|--------|------|
| KaTrain GUI → `C:\Users\iwaki\.katrain\config.json` `max_visits` | 1000 | 事後分析・Stage1・Stage2 すべての実効 visits |
| `katrain/core/ai.py` Jigo Stage1 `visits=1`（引数） | 1 | humanPolicy 取得のみ（例外的な明示指定） |
| `katrain/KataGo/analysis_config.cfg` 51行目（**パッケージ側**。エンジンが実際に読むのはこちら） | 500 | デフォルト値（明示指定のないクエリのみ） |

エンジンが読む cfg は `config.json` の `engine.config` が解決する**パッケージ側** `katrain/KataGo/analysis_config.cfg` で、`C:\Users\iwaki\.katrain\analysis_config.cfg` は**参照されない**。個々のクエリは毎回 `maxVisits` を明示送信するため、cfg 側のデフォルト値が効く場面は明示指定のないクエリに限られ限定的。

- [ ] KaTrain GUI「エンジン設定 → 分析時の最大探索手数」→「設定を更新」（Stage1/2 も連動）
- [ ] `katrain/KataGo/analysis_config.cfg` — `maxVisits = XXX`（パッケージ側。`C:\Users\iwaki\.katrain\analysis_config.cfg` を編集しても反映されない）

## GREEN_MOVE_THRESHOLD 調整メモ（13路盤）

> 二段階フィルタ導入前の記録。Stage2クリーンクエリ導入により、着手生成時と事後分析のスコアズレは大幅に縮小されている。

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
