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

**方式: 2アンカーmax（v2）**

初期実装のα=0.5平均方式は、直前手と不安定ターゲットが盤の反対側にある場合に「幻影中心」（どちらにも近くない架空の点）を生成し、実際の戦闘エリアの手がペナルティを受ける問題があった。

修正後は2つの独立したGaussianの最大値を取る:
```
anchors = [last_move_coords, unstable_center]  # 利用可能なもののみ
penalty = max(gaussian(dist_to_anchor) for anchor in anchors)
```

これにより「直前手の近く」**または**「不安定ターゲットの近く」の手はペナルティを受けず、**どちらからも遠い手だけ**が抑制される。

**フォールバック:**
- 直前手がパスまたは初手 -> ターゲット重心のみアンカーとして使用
- ターゲットが空 -> フォーカスなし（ペナルティ適用しない）
- アンカーが0個 -> フォーカスなし

### フォーカスペナルティの適用

各候補手 `(x, y)` に対して:

```python
best_penalty = focus_floor
for ax, ay in focus_anchors:
    dist_sq = (x - ax) ** 2 + (y - ay) ** 2
    penalty = math.exp(-0.5 * dist_sq / focus_var)
    if penalty > best_penalty:
        best_penalty = penalty
combined *= best_penalty
```

**パラメータ:**

| パラメータ | 値 | 説明 |
|---|---|---|
| `hunt_focus_stddev` | 19路: 7.0, 13路: 5.0 | 注意フォーカスの広がりを制御するGaussian標準偏差。小さいほどフォーカス中心付近に集中し遠い手を強く抑制する。大きいほど緩やかになり広範囲の手を許容する。GUIから調整可能 |
| `focus_floor` | 0.05（固定） | フォーカスペナルティの下限値。どれだけ遠い手でも元の重みの5%は維持され、完全排除を防ぐ。温度w^0.5適用後は実効約22%になる |
| `focus_var` | `hunt_focus_stddev ** 2` | 内部計算用の分散値。Gaussian関数 `exp(-0.5 * dist² / focus_var)` で使用 |

**stddev=7.0の効果（19路）:**

| フォーカス中心からの距離 | ペナルティ倍率 |
|---|---|
| 0~3路 | 0.91~1.00 |
| 5路 | 0.78 |
| 7路 | 0.61 |
| 10路 | 0.37 |
| 14路 | 0.14 |
| 18路 | 0.05（floor） |

**適用タイミング:** `combined = hp_weight * proximity * intensity * territory_avoid` の直後、`moves.append()` の直前。温度変換 `w^(1/inv_temp)` の前に適用されるため、温度で平坦化されても遠い手の抑制が効く。ただし温度はペナルティを緩和する方向に作用する（例: ペナルティ0.14 → 温度2.0適用後は実効0.37）。それでもフォーカスなし（重み比1.25倍）と比べ十分な差（3倍）が残るため問題にならない。

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
[HuntStrategy] Focus: anchors=[last_move(R4),unstable(group(9,7))] stddev=7.0
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
