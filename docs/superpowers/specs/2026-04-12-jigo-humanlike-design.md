# JigoStrategy 人間らしさ改修 設計書

- 作成日: 2026-04-12
- 対象: `katrain/core/ai.py` の `JigoStrategy`（`ai:jigo`）
- 方針: 既存 `JigoStrategy` を置き換え、大差リード時の「明らかにおかしい手」を排除する

## 背景と課題

現行の `JigoStrategy`（`ai.py:691-740`）は `candidate_moves` の中から `scoreLead` が `target_score` に最も近い手を単純選択するだけ。具体的には:

```python
jigo_move = min(
    candidate_moves,
    key=lambda m: abs(sign * m["scoreLead"] - target_score)
)
```

このロジックは `humanPolicy` も悪手フィルタも参照しないため、大差でリード（例: +30 目）している局面では、target(0.5 目) に近づけるために数十目損する手が必要になり、結果として:

- 自石をアタリに放り込む
- 自陣の中に石を捨てる
- `humanPolicy` ≒ 0 の「人間が打つわけがない座標」へ着手する

といった「明らかにサボタージュ」な挙動が露出する。

## 目標

- リード幅が大きい局面でも、AI が「わざと負けに行っている／人間ではない」とばれない着手を選ぶ
- 最終スコア差を `[0.5, 10.0]` 目の範囲に収める（ユーザ許容レンジ）
- 既存の `target_score` 設定は流用し、移行コストを最小化

## 非目標

- 温度サンプリングのパラメータ化（YAGNI、必要になったら後追加）
- Mode A と B の中間挙動（ハイブリッド）の実装（まず A/B を検証してから判断）
- フェーズ別（序盤/中盤/終盤）の損失上限切り替え（固定値で開始）
- 負け局面からの逆転狙い（現行同様、自然に最善近辺を選ぶだけ）

## アーキテクチャ

### 全体フロー

```
[Stage 1: humanSL 9段クエリ (maxVisits=800)]
  → 各候補手の humanPolicy を取得

[Stage 2: クリーンクエリ (maxVisits=600, wideRootNoise=0)]
  → 正確な scoreLead を取得（Stage1 の scoreLead はバイアス）

[候補リスト構築]
  各手に {move, humanPolicy, scoreLead, loss} を紐付け
  best_score = Stage2 内の自分視点最大スコア
  loss = best_score - score (自分視点)

[フィルタ適用]
  - loss ≤ max_loss_per_move (default 5.6)
  - humanPolicy ≥ min_human_policy (default 0.01)

[選択ロジック分岐 (current_lead × jigo_mode)]
  current_lead = 着手前局面の scoreLead（自分視点）

  - current_lead < target_score (= 0.5, 負け〜互角):
      → target 最接近手（実質的に最善近辺）
  - target_score ≤ current_lead ≤ target_score_max (= 10.0), Mode A:
      → humanPolicy 重み付き softmax 選択（HumanStyle 相当）
  - target_score ≤ current_lead ≤ target_score_max, Mode B:
      → target 最接近手（常に寄せる）
  - current_lead > target_score_max:
      → Mode 問わず target 最接近手（削りに行く）

[候補ゼロ時フォールバック（段階緩和）]
  1. min_human_policy × 0.5
  2. min_human_policy × 0.25
  3. max_loss_per_move × 1.5
  4. KataGo 最善手 (safety valve, WARN ログ)
```

### 2段階クエリの流用

既存 `HumanStyleStrategy` の 2段階クエリ実装パターンに従う:

- Stage 1 (`override_settings`): `humanSLProfile=rank_-8`, `maxVisits=800`, `widerootnoise=デフォルト`
- Stage 2 (`clean_override_settings`): `humanSLProfile` なし, `maxVisits=600`, `wideRootNoise=0`

CLAUDE.md の「Stage 1 の scoreLead をフィルタ判定に使わない」に従い、**loss 計算は必ず Stage 2 の moveInfos を使う**。

## 設定項目

`katrain/core/constants.py` の `AI_OPTION_VALUES[AI_JIGO]` に以下を定義:

| キー | 型 | デフォルト | 選択肢 | 備考 |
|---|---|---|---|---|
| `target_score` | float | 0.5 | [0.5, 1.5, 5.5, 10.5] | **既存・流用** |
| `target_score_max` | float | 10.0 | [5.0, 10.0, 15.0] | 許容上限 |
| `max_loss_per_move` | float | 5.6 | [3.0, 4.0, 5.6, 7.0] | 1手あたり許容損失（HumanStyle NORMAL_THRESHOLD と同値） |
| `min_human_policy` | float | 0.01 | [0.005, 0.01, 0.02, 0.05] | humanPolicy 最低閾値 |
| `jigo_mode` | str | "natural" | ["natural", "maintain"] | A=natural / B=maintain |

### 配置ファイル（CLAUDE.md の3箇所ルール）

1. `katrain/config.json`（パッケージ同梱デフォルト）
2. `C:\Users\iwaki\.katrain\config.json`（ユーザローカル／メインセッションで直接 Edit）
3. `katrain/core/constants.py` の `AI_OPTION_VALUES[AI_JIGO]`

### i18n

`katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po` に以下のヘルプテキストを追加し、編集後 `python tools/compile_mo.py` で `.mo` を再コンパイル:

| キー | jp | en |
|---|---|---|
| `target_score_max` | 許容できる最大リード目数。これ以下ならNaturalモードは通常の人間手を打つ | Max acceptable lead margin. Natural mode plays normally when lead is within range |
| `max_loss_per_move` | 1手あたりの許容最大損失（目）。これを超える手は選ばない | Max allowed loss per move (points). Moves above this are rejected |
| `min_human_policy` | humanPolicy最低閾値。人間が検討しない手（自石アタリ等）を除外 | Minimum humanPolicy threshold. Rejects moves no human would consider |
| `jigo_mode` | natural=許容範囲内なら最善手／maintain=常にtargetに寄せる | natural=play best within range / maintain=always aim for target |

## 選択ロジック疑似コード

```python
def generate_move(self) -> Tuple[Move, str]:
    # 1. Stage 1/2 クエリ実行
    stage1 = self.run_humansl_query()       # humanPolicy 取得
    stage2 = self.run_clean_query()          # 正確な scoreLead 取得

    # 2. 候補リスト構築
    sign = self.cn.player_sign(self.cn.next_player)
    best_score = max(sign * mi["scoreLead"] for mi in stage2.moveInfos)
    candidates = []
    for mi in stage2.moveInfos:
        score = sign * mi["scoreLead"]
        candidates.append({
            "move": mi["move"],
            "score": score,
            "loss": best_score - score,
            "hp": stage1.humanPolicy.get(mi["move"], 0.0),
        })

    # 3. フィルタ適用
    filtered = [c for c in candidates
                if c["loss"] <= self.settings["max_loss_per_move"]
                and c["hp"]  >= self.settings["min_human_policy"]]

    # 4. フォールバック（段階緩和）
    if not filtered:
        filtered = self._relax_filters(candidates)

    # 5. 現在リード取得 & Mode で分岐
    current_lead = sign * self.cn.analysis["rootInfo"]["scoreLead"]
    target  = self.settings["target_score"]
    t_max   = self.settings["target_score_max"]
    mode    = self.settings["jigo_mode"]

    if current_lead < target:
        # 負け寄り: target 最接近
        pick = min(filtered, key=lambda c: abs(c["score"] - target))
    elif target <= current_lead <= t_max and mode == "natural":
        # 範囲内 × Mode A: humanPolicy 重み付き選択
        pick = self._weighted_choice(filtered, weights="hp")
    else:
        # Mode B または範囲外: target 最接近
        pick = min(filtered, key=lambda c: abs(c["score"] - target))

    aimove = Move.from_gtp(pick["move"], player=self.cn.next_player)
    return aimove, self._build_thoughts(pick, current_lead, mode)
```

### 重要な仕様メモ

- **`current_lead`** は着手前の `rootInfo.scoreLead`（候補手適用前）を使う
- **`loss`** は Stage 2 基準で計算（CLAUDE.md 遵守）
- **`best_score`** は Stage 2 の moveInfos 内の自分視点最大スコア
- **`_weighted_choice`** は `HumanStyleStrategy` で使われている humanPolicy 重み付き選択実装（softmax + 温度）を流用。実装箇所は `ai.py` の該当セクションを参照して同等の関数を呼ぶ
- **温度** は 1.0 固定（パラメータ化しない）
- **`rootInfo.scoreLead` 取得**: `self.cn.analysis` の root ノード scoreLead を参照。既存 `ai.py` 内で同様にルートスコアを取る実装箇所（例: HuntStrategy の score_lead 参照）を流用

## フォールバック詳細

```python
def _relax_filters(self, candidates):
    base_hp = self.settings["min_human_policy"]
    base_loss = self.settings["max_loss_per_move"]
    for hp_factor in (0.5, 0.25):
        f = [c for c in candidates
             if c["loss"] <= base_loss and c["hp"] >= base_hp * hp_factor]
        if f:
            self.log(f"Fallback: hp×{hp_factor}")
            return f
    for loss_factor in (1.5,):
        f = [c for c in candidates
             if c["loss"] <= base_loss * loss_factor and c["hp"] >= base_hp * 0.25]
        if f:
            self.log(f"Fallback: loss×{loss_factor}")
            return f
    # Safety valve: KataGo best
    self.log("Safety valve: using KataGo top move", level=WARN)
    return [candidates[0]]
```

## ログ要件

`log-analysis.md` の Grep パターンに沿い、以下のログを `ai.py` に出力:

- `[JigoStrategy] Stage1 query complete (N candidates)`
- `[JigoStrategy] Stage2 query complete (best_score=X)`
- `[JigoStrategy] Filter: N → M passed (loss≤X, hp≥Y)`
- `[JigoStrategy] Mode: <natural/maintain>, lead=X, in_range=<True/False>`
- `[JigoStrategy] Selected: <move> (loss=X, hp=Y, score=Z)`
- `[JigoStrategy] Fallback triggered: <reason>`（緩和時）
- `[JigoStrategy] Safety valve: using KataGo top`（最終フォールバック時）

## 検証計画

### 1. CLI 単体検証（対局不要・数十秒）

`katrain_debug/runner.py` の対応戦略リストに `jigo` を追加したうえで:

```bash
# 大差リード局面の挙動を確認
python -m katrain_debug --sgf <FILE> --move N --strategy jigo --output json

# パラメータ変更による比較
python -m katrain_debug --sgf <FILE> --move N --strategy jigo \
  --settings jigo_mode=maintain max_loss_per_move=4.0
```

### 2. バッチ評価（1局通し・約10分/run）

```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --batch --player W
```

**合格基準**:

- フィルタ通過手は `loss ≤ max_loss_per_move (5.6)` を満たす（通常手）
- フォールバック段階緩和発動率 < 5%（フィルタ機能の指標）
- 安全弁（KataGo 最善手）発動率 < 1%
- 最終スコア差が `[0.5, 10.0]` 目に収まる
- humanPolicy ≒ 0 の手が Notable Divergences に現れない
- `feedback_batch_eval_variance.md` に従い **3run 平均** で Mode A / Mode B を比較

### 3. GUI 実対局（最終確認）

- `debug_level: 1` に切り替え、`python -m katrain` 起動
- +30 目程度リードする局面を意図的に作り、持碁モードで終局まで打たせる
- ログで上記「ログ要件」を確認
- 確認後 `debug_level: 0` に戻す

## リスクと対策

| リスク | 対策 |
|---|---|
| Mode B で「毎手少し緩い手」が選ばれ、AI の棋力が不自然に低く見える | バッチ評価で AI 一致率を計測。Mode A と比較して極端に悪ければ Mode B はデフォルトから外す |
| フォールバック多発でパラメータが実質無効化される | ログに `Fallback triggered` を必ず出力。3run 平均で発生率を計測 |
| `max_loss_per_move=5.6` が序盤では緩すぎる | 初期値は HumanStyle NORMAL_THRESHOLD と同じにし、検証後に序盤だけ閾値を下げるオプション追加を検討（将来拡張） |
| 2段階クエリで生成時間が倍化 | HumanStyle/Fighting/Hunt などで既に採用済みの実装パターン。特有リスクではない |

## 参考ファイル

- `katrain/core/ai.py` - `JigoStrategy`（ai.py:691-740）、`HumanStyleStrategy` の 2段階クエリ実装
- `katrain/core/constants.py` - `AI_JIGO`, `AI_OPTION_VALUES`
- `.claude/rules/ai-humanstyle.md` - 2段階クエリ仕様、悪手フィルタ詳細
- `.claude/rules/ai-parameters.md` - 既存戦略のパラメータ値
- `.claude/rules/log-analysis.md` - ログ Grep パターン
- `memory/feedback_batch_eval_variance.md` - バッチ評価は 3run 平均必須
