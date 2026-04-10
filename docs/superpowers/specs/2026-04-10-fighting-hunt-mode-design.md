# Fighting Hunt Mode（狩猟モード）設計書

## 概要

FightingStrategy に新モード `"hunt"` を追加する。相手の弱い石群を見つけて集中攻撃し、攻め切れないと判断したら次のターゲットに移る狩猟型の戦略モード。9段の humanPolicy で人間らしさを担保し、無理な攻めはしない。

## 背景・動機

- 既存の FightingStrategy（human モード）は相手石の近くで力戦を仕掛けるが、特定の弱い石群を狙い続ける機能がない
- SiegeStrategy は大石攻撃のターゲット検出機構を持つが、序盤の concede フェーズが前提であり「最初から攻める」コンセプトとは異なる
- 「自分の地は無視して攻めまくる」を、9段の品位を保ちつつ実現したい

## 設計方針

- **アプローチ A（シンプル統合）** を採用
- SiegeStrategy の `_find_targets()` をモジュールレベル関数に抽出し、FightingStrategy と SiegeStrategy の両方から呼び出す
- FightingStrategy の `fighting_mode: "hunt"` として独立したモードを新設
- humanPolicy ベースの 2 段階クエリ（human モードと同じ構造）

## アーキテクチャ

```
FightingStrategy.generate_move()
  +-- "classic" -> _generate_classic()
  +-- "scoreloss" -> _generate_scoreloss()
  +-- "human" -> _generate_human()
  +-- "hunt" -> _generate_hunt()    <-- 新規
                    |
                    +-- Stage 1: humanSLProfile (rank_9d, 800 visits)
                    +-- Stage 2: clean query (600 visits)
                    +-- find_targets()  <-- SiegeStrategy から抽出した共有関数
                    |
                    +-- [no targets] -> weight = humanPolicy (pure 9-dan)
                    +-- [has targets] -> weight = humanPolicy x proximity x instability
```

## アルゴリズム詳細

### ターゲット検出（毎手実行）

SiegeStrategy から `_find_targets()` をモジュールレベル関数 `find_targets()` として抽出。ロジックは変更なし：

1. 相手の石座標を取得
2. BFS で連結グループを検出
3. 各グループの平均 ownership から `instability = 1.0 - abs(avg_ownership)` を計算
4. `instability >= hunt_instability_min` かつ `len(group) >= hunt_min_group_size` のみ残す
5. `target_score = len(group) x instability` でソート（降順）
6. 返却: `[(target_score, instability, group_coords_set), ...]`

SiegeStrategy 側も同じ `find_targets()` を呼ぶようリファクタする。

### _generate_hunt() フロー

```
1. Stage 1: humanSLProfile (rank_9d, maxVisits=800) -> humanPolicy 配列を取得
2. Stage 2: クリーンクエリ (maxVisits=600, wideRootNoise=0.0) -> 正確な scoreLead を取得
3. find_targets(game_node, ownership_grid, board_size, hunt_min_group_size, hunt_instability_min)
4. 悪手フィルタ（Stage 2 のスコアで判定）:
   - 閾値: hunt_max_loss（序盤・通常とも統一）
   - 全滅時の段階的緩和: x1.5 -> x2.0 -> 9.0目上限 -> 最善手強制
5a. [ターゲットあり]:
   - 全ターゲットの石座標を統合 (target_coords)
   - primary_instability = targets[0][1]
   - weight = humanPolicy[idx] x proximity x primary_instability
   - proximity = exp(-0.5 x min_dist_sq / (hunt_proximity_stddev^2))
5b. [ターゲットなし]:
   - weight = humanPolicy[idx]（純粋な 9 段）
6. 安全弁: top weighted move の loss >= 4.0目 -> 最善手強制
7. パス処理: area scoring 時の pass 除外/強制
8. エンドゲーム: ceil(0.5 x board_squares) 手目以降 -> humanPolicy 順で選択
9. タイブレーク: weight 比 < 1.05 かつ score 差 >= 2.0目 -> 高スコア手を選択
10. weighted_selection_without_replacement で最終選択
```

### 9 路フォールバック

9 路盤で hunt モードを選択した場合、ログ警告を出して human モードにフォールバック：

```python
if board_size == (9, 9):
    log warning "Hunt mode not supported on 9x9, falling back to human mode"
    return self._generate_human()
```

理由: 9 路盤では石群が小さくターゲット追跡型の攻めが成立しにくい。

## パラメータ

### 新規パラメータ

| パラメータ | 値域 | デフォルト(19路) | デフォルト(13路) | GUI型 | 説明 |
|---|---|---|---|---|---|
| `hunt_max_loss` | 1.0~10.0 | 6.0 | 4.0 | spin(0.5刻み) | 攻撃時に許容する最大損失（目数） |
| `hunt_min_group_size` | 2~10 | 5 | 4 | spin(1刻み) | ターゲットとする最小グループサイズ |
| `hunt_instability_min` | 0.1~0.8 | 0.3 | 0.3 | spin(0.1刻み) | ターゲット判定の最小不安定度 |
| `hunt_proximity_stddev` | 1.5~6.0 | 3.0 | 2.5 | spin(0.5刻み) | ターゲット近接重みの標準偏差 |

### 盤面サイズ別デフォルト（BOARD_PARAMS）

`_generate_hunt()` 内で盤面サイズに応じたデフォルト値を適用。config.json のデフォルトは 19 路の値。13 路はコード内で切り替え。

### fighting_mode 選択肢の拡張

```python
"fighting_mode": [
    ("classic", "[fighting:classic]"),
    ("scoreloss", "[fighting:scoreloss]"),
    ("human", "[fighting:human]"),
    ("hunt", "[fighting:hunt]"),
],
```

### GUI 表示順（AI_OPTION_ORDER）

```python
"hunt_max_loss": 6,
"hunt_min_group_size": 7,
"hunt_proximity_stddev": 8,
"hunt_instability_min": 9,
```

## GUI 説明テキスト（i18n）

### 英語

```
'hunt' mode: Identifies weak opponent groups and focuses attacks on them.
When no targets exist, plays like a normal 9-dan. 9x9 not supported (falls back to human mode).

hunt_max_loss: Max points loss allowed when attacking a target.
Higher = riskier attacks, lower = safer attacks.
hunt_min_group_size: Minimum stones in an opponent group to be targeted.
Lower = target smaller groups too, higher = only go after big groups.
hunt_proximity_stddev: How tightly focused attacks are on the target.
Lower = concentrate near target, higher = spread attacks wider.
hunt_instability_min: Minimum instability to consider a group as target.
Lower = target more stable groups too, higher = only target very unstable groups.
```

### 日本語

```
'hunt'モード: 相手の弱い石群を見つけて集中攻撃する狩猟モード。
ターゲットがない時は通常の9段として着手。9路盤は非対応（humanモードにフォールバック）。

hunt_max_loss: 攻撃時に許容する最大損失（目数）。大きい＝リスクの高い攻めを許容、小さい＝安全な攻め。
hunt_min_group_size: ターゲットとする最小グループサイズ。小さい＝小さい石群も狙う、大きい＝大石だけ狙う。
hunt_proximity_stddev: 攻撃の集中度。小さい＝ターゲット付近に集中、大きい＝広く攻める。
hunt_instability_min: ターゲット判定の最小不安定度。小さい＝安定した石群も狙う、大きい＝非常に不安定な石群だけ狙う。
```

## 変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `katrain/core/ai.py` | `find_targets()` をモジュールレベル関数に抽出。`_generate_hunt()` を FightingStrategy に新設。SiegeStrategy の `_find_targets()` を `find_targets()` 呼び出しにリファクタ |
| `katrain/core/constants.py` | `fighting_mode` に `"hunt"` 追加、`hunt_*` 4 パラメータを `AI_OPTION_VALUES` / `AI_OPTION_ORDER` に追加 |
| `katrain/config.json` | `"ai:p:fighting"` に hunt 系デフォルト値 4 つを追加 |
| `C:\Users\iwaki\.katrain\config.json` | 同上（GUI 表示に必要） |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | `aihelp:p:fighting` に hunt モード説明を追加 |
| `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | 同上（日本語） |
| `CLAUDE.md` | hunt モードのパラメータテーブルを追加 |

## テスト計画

1. `debug_level: 1` で起動
2. 力戦派で `fighting_mode: hunt` を選択して対局
3. ログで確認:
   - `Initializing.*Strategy with settings` で hunt 関連パラメータが出力されること
   - ターゲット検出ログ（ターゲットのグループサイズ・不安定度）
   - `Selected:` で着手が選択されること
   - ターゲットがない序盤は通常の humanPolicy 選択
   - ターゲット出現後は proximity 重みが効いていること
4. 9 路盤で hunt を選択 -> human モードにフォールバック＋警告ログ
5. 13 路盤でデフォルト値が 19 路と異なることを確認
