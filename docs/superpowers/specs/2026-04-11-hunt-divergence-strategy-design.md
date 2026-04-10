# HuntDivergenceStrategy（狩猟戦略・一致率低減版）設計仕様書

## 目的

HuntStrategyの攻撃的な棋風（Invade/Huntフェーズ、石群攻撃）を完全に維持しながら、KataGo最善手一致率を35-45%に低減する新戦略を追加する。

## 背景

- HuntStrategyのtemperature=2.0では一致率50%超（棋風は良好）
- temperature=2.5では一致率は低減するが、Invade手が散り、Huntフェーズに移行できず棋風が崩壊する
- temperatureと別の偏差メカニズム（Best-move dodge）を組み合わせると2つの機構が競合し挙動が分かりにくい
- → 温度を使わない独立した新戦略として実装する

## アーキテクチャ

HuntStrategyを継承し、選択ロジックのみを差し替える。

```
HuntDivergenceStrategy（HuntStrategyの子クラス）
├── Invade/Huntフェーズ判定 → 親クラスそのまま
├── ターゲット検出（find_targets） → 親クラスそのまま
├── 2段階クエリ（Stage 1/2） → 親クラスそのまま
├── 重み計算（humanPolicy × proximity × intensity × territory_avoid） → 親クラスそのまま
├── スコアフィルタ → 親クラスそのまま
├── Safety v2 → 親クラスそのまま
├── タイブレーク → 親クラスそのまま
└── 最終選択 → 独自ロジック（温度なし + Best-move dodge）
```

### 選択ロジック（親との差分）

**親クラス（HuntStrategy）**:
```
温度選択（w^(1/temp)） → Post-temp safety → Selected
```

**新クラス（HuntDivergenceStrategy）**:
```
weighted_selection（温度なし） → Best-move dodge → Selected
```

## Best-move dodge 仕様

### トリガー条件

weighted_selectionで選ばれた手が `best_gtp_by_score`（KataGo最善手）と一致した場合のみ発動。

### 代替候補の条件（すべて満たす）

1. **スコア損失 ≤ `hunt_dodge_max_loss`**（デフォルト: 1.0目） — Stage 2のクリーンスコアで計算
2. **humanPolicy順位が候補手プール内で上位 `hunt_dodge_top_n` 以内**（デフォルト: 3） — Stage 1の`human_policy`配列から算出
3. **KataGo最善手（`best_gtp_by_score`）ではない**

### humanPolicy順位の算出方法

親クラスの`generate_move`内で取得済みの`human_policy`配列（`analysis["humanPolicy"]`）を使用する。候補手プール（`moves`リスト）に含まれる各手の盤面インデックスから`human_policy[idx]`を取得し、プール内で降順ソートして順位を決定する。

### 選択ルール

- 該当候補が複数 → スコア損失が最小の手を選択
- 該当候補がゼロ → そのまま最善手を着手（変更なし）

### フェーズ適用範囲

Invade/Hunt両フェーズで適用（フェーズによる区別なし）。Endgameフェーズでは親クラスのEndgame処理がdodgeより前に発動するため影響なし。

## 設定パラメータ

### 新規パラメータ

| パラメータ | デフォルト(19路) | デフォルト(13路) | GUI選択肢 | 備考 |
|---|---|---|---|---|
| hunt_dodge_max_loss | 1.0 | 1.0 | 0.5〜3.0（0.5刻み） | dodge対象のスコア僅差閾値（目） |
| hunt_dodge_top_n | 3 | 3 | 2〜5 | humanPolicy上位N位以内が対象 |

### 親クラスから継承するパラメータ

hunt_max_loss, hunt_min_group_size, hunt_proximity_stddev, hunt_instability_min, hunt_invasion_max_loss, hunt_invasion_min, hunt_invasion_max, hunt_invasion_proximity_stddev

**温度パラメータ（`hunt_invasion_temperature`）は含めない。**

## 変更ファイル一覧

### katrain/core/constants.py

- `AI_HUNT_DIVERGE = "ai:hunt_diverge"` 定数追加
- `AI_STRATEGIES` リストに追加
- `AI_STRATEGIES_RECOMMENDED_ORDER` に `AI_HUNT` の直後に追加
- `AI_STRENGTH` に `AI_HUNT_DIVERGE: float("nan")` 追加
- `AI_OPTION_VALUES` に `hunt_dodge_max_loss` と `hunt_dodge_top_n` の選択肢追加
- `AI_OPTION_ORDER` に `hunt_dodge_max_loss` と `hunt_dodge_top_n` の表示順追加

### katrain/core/ai.py

HuntDivergenceStrategyクラスを追加（HuntStrategyの直後）:

- `@register_strategy(AI_HUNT_DIVERGE)` でデコレート
- `HuntStrategy` を継承
- `generate_move()` をオーバーライド:
  - 親クラスのgenerate_moveの大部分を再利用する必要がある
  - **実装方針**: 親クラスのgenerate_moveの選択ロジック部分（温度選択〜return）を抽出可能にするか、子クラスでgenerate_moveを完全にオーバーライドして最終選択部分だけ差し替える
  - 親のgenerate_moveが長い（約550行）ため、コピーは避ける。`_select_move`のようなメソッドを親に切り出し、子でオーバーライドするのが最善

### 親クラスのリファクタリング（最小限）

HuntStrategyの`generate_move`末尾（3986行目〜4000行目、選択ロジック部分）を`_select_move(moves, phase_name, move_infos, ...)`メソッドとして切り出す。これにより:

- HuntStrategy: `_select_move`で温度選択 + Post-temp safety
- HuntDivergenceStrategy: `_select_move`をオーバーライドしてweighted_selection + dodge

### katrain/config.json（パッケージ同梱）

```json
"ai:hunt_diverge": {
    "hunt_max_loss": 6.0,
    "hunt_min_group_size": 5,
    "hunt_proximity_stddev": 3.0,
    "hunt_instability_min": 0.3,
    "hunt_invasion_max_loss": 8.0,
    "hunt_invasion_min": 0.2,
    "hunt_invasion_max": 0.7,
    "hunt_invasion_proximity_stddev": 3.0,
    "hunt_dodge_max_loss": 1.0,
    "hunt_dodge_top_n": 3
}
```

### C:\Users\iwaki\.katrain\config.json（ユーザーローカル）

上記と同じエントリを追加。

### katrain/i18n/locales/en/LC_MESSAGES/katrain.po

```
msgid "ai:hunt_diverge"
msgstr "Hunt Strategy (Low Agreement)"

msgid "aihelp:hunt_diverge"
msgstr ""
"Hunt Strategy (Low Agreement): Same aggressive invasion and group attack "
"as Hunt Strategy, but with reduced AI top-move agreement rate. Uses "
"Best-move dodge to avoid playing KataGo's top choice when a close "
"alternative exists.\n"
"hunt_dodge_max_loss: Maximum score loss for dodge alternatives. "
"Larger = more dodge opportunities but weaker moves.\n"
"hunt_dodge_top_n: Only consider top N humanPolicy moves as dodge "
"alternatives. Smaller = more natural moves."
```

### katrain/i18n/locales/jp/LC_MESSAGES/katrain.po

```
msgid "ai:hunt_diverge"
msgstr "狩猟戦略（一致率低減）"

msgid "aihelp:hunt_diverge"
msgstr ""
"狩猟戦略（一致率低減）: 狩猟戦略と同じ侵入・石群攻撃の棋風を維持しつつ、"
"AI最善手一致率を低減します。KataGo最善手が選ばれた際に、スコア僅差かつ"
"humanPolicy上位の代替手があれば差し替えます。\n"
"hunt_dodge_max_loss: dodge対象とするスコア僅差の閾値（目数）。"
"大きい＝dodge機会が増えるが弱い手も選ばれる。\n"
"hunt_dodge_top_n: dodge対象とするhumanPolicy上位N位。"
"小さい＝より自然な手だけを対象にする。"
```

### .claude/rules/ai-parameters.md

狩猟戦略（一致率低減版）セクションを追加。

## デバッグログ

```
[HuntDivergenceStrategy] Best-move dodge: {best} -> {alt} (loss={loss:.2f}, hP rank={rank}/{total})
[HuntDivergenceStrategy] Best-move dodge: no alternative (best={best}, candidates checked={n})
```

## 検証方法

1. `debug_level: 1` で起動
2. Hunt Strategy (Low Agreement) を選択して対局
3. ログで確認:
   - `Best-move dodge:` の発動回数と代替手の品質
   - `Selected:` で最終的に選ばれた手
   - `Phase:` でInvade/Hunt両フェーズが出現すること
4. KaTrain評価レポートでAI最善手一致率が35-45%範囲か確認
5. 棋風がHuntStrategy（temperature=2.0）と同等の攻撃性を維持しているか目視確認
