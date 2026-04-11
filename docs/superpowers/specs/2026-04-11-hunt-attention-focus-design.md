# Hunt戦略 注意フォーカス機能 設計書

## 課題

HuntStrategyの`hunt_invasion_temperature=2.0`で棋風の多様性は良好だが、人間らしくない挙動が発生する:
- 左辺で戦闘中なのに突然右辺や下辺の急所に打つ
- Huntフェーズで複数ターゲット間を行ったり来たりする
- Safety valve発動が1局あたり10回前後と多い

**根本原因**: proximity計算が「最近接ターゲット1つ」のみで行われるため、盤面全体のターゲットに対して均等に近接重みが付く。高温度で分布が平坦化されると、遠いターゲット付近の手も同等の確率で選ばれる。

人間は「直前の着手の周辺」と「最も激しい戦闘が起きている場所」に注意が集中し、遠い場所の急所は一段落してから打つ。この注意集中が欠けている。

## 設計

### 方針

既存のproximity計算はそのまま維持し、追加の「注意フォーカス」Gaussianペナルティを乗算する。近くの手の多様性は最大限維持し、明らかに遠い手だけを抑制する。

### 対象戦略

- **今回**: HuntStrategyのみ
- **将来**: 効果確認後にHuntDivergenceStrategyにも展開（generate_moveを継承しているため、コード変更なしで自動適用可能）

### フォーカス中心点の算出

毎手、以下の2つの要素から「注意の中心点」を計算する:

1. **直前の着手位置** `(last_x, last_y)` -- 相手・自分問わず直前の1手
2. **最も不安定なターゲットの重心** `(unstable_cx, unstable_cy)` -- group_targetsが存在する場合: 最大instabilityを持つグループの全石座標の算術平均（重心）。group_targetsがない場合（Invadeフェーズ）: invasion_targets（`all_target_coords`のうち`group_coords`に含まれない座標群）の中で、`opp_strength_map`の値が最大の座標をそのまま使用

合成:
```
focus_x = 0.5 * last_x + 0.5 * unstable_cx
focus_y = 0.5 * last_y + 0.5 * unstable_cy
```

alpha=0.5（固定）。直前手と不安定ターゲットが同エリアなら強化され、離れていれば中間点がフォーカスになるが、どちらからも遠い手はいずれにせよペナルティを受ける。

**フォールバック:**
- 直前手がパスまたは初手 -> ターゲット重心のみ使用
- ターゲットが空 -> フォーカスなし（ペナルティ適用しない）

### フォーカスペナルティの適用

各候補手 `(x, y)` に対して:

```python
focus_dist_sq = (x - focus_x) ** 2 + (y - focus_y) ** 2
focus_penalty = max(focus_floor, math.exp(-0.5 * focus_dist_sq / focus_var))
combined *= focus_penalty
```

**パラメータ:**

| パラメータ | 値 | 備考 |
|---|---|---|
| `hunt_focus_stddev` | 19路: 7.0, 13路: 5.0 | GUIから調整可能 |
| `focus_floor` | 0.05（固定） | 遠い手でも最低5%の重みは残す |
| `focus_var` | `hunt_focus_stddev ** 2` | 内部計算用 |

**stddev=7.0の効果（19路）:**

| フォーカス中心からの距離 | ペナルティ倍率 |
|---|---|
| 0~3路 | 0.91~1.00 |
| 5路 | 0.78 |
| 7路 | 0.61 |
| 10路 | 0.37 |
| 14路 | 0.14 |
| 18路 | 0.05（floor） |

**適用タイミング:** `combined = hp_weight * proximity * intensity * territory_avoid` の直後、`moves.append()` の直前。温度変換の前に適用されるため、温度で平坦化されても遠い手の抑制が効く。

**適用条件:** Invade・Hunt両フェーズで適用。ターゲットがない場合は適用しない。

### 変更ファイル

| ファイル | 変更内容 |
|---|---|
| `katrain/core/ai.py` | HuntStrategy.generate_move()にフォーカス計算・ペナルティ適用を追加 |
| `katrain/core/constants.py` | AI_OPTION_VALUESにhunt_focus_stddevの設定UIを追加 |
| `katrain/config.json` | パッケージデフォルト設定にhunt_focus_stddevを追加 |
| `C:\Users\iwaki\.katrain\config.json` | ローカル設定にも同キーを追加 |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 英語ラベル追加 |
| `katrain/i18n/locales/ja/LC_MESSAGES/katrain.po` | 日本語ラベル追加 |
| `.claude/rules/ai-parameters.md` | パラメータテーブル更新 |

### ログ出力（debug_level=1）

```
[HuntStrategy] Focus: center=(9.5, 7.0) stddev=7.0 source=last_move(R4)+unstable_group(D10,instab=0.76)
```

初期化ログにも `hunt_focus_stddev` を含める。

### 変更しないもの

- HuntDivergenceStrategy（将来展開）
- SiegeStrategy / FightingStrategy
- 既存のproximity計算
- 温度選択の仕組み
- Safety valve

## 検証方法

1. `debug_level=1` で対局を実施
2. ログでフォーカス中心の算出を確認
3. 遠い手への飛びが減少しているか確認
4. Safety valve発動回数の減少を確認（改善前: 10回/局）
5. 近くの手のバリエーションが維持されているか確認

**調整シナリオ:**

| 症状 | 対応 |
|---|---|
| まだ遠い手が出る | `hunt_focus_stddev` を下げる（7.0->5.0） |
| 近くの手ばかりで単調 | `hunt_focus_stddev` を上げる（7.0->9.0） |
