# JigoStrategy ε バンド tiebreak 設計書

- 作成日: 2026-04-19
- 対象: `katrain/core/ai.py` の `_jigo_select_move`（ai.py:794-807）
- 方針: target-closest 選択に「同点扱いバンド」を導入し、定石〜互角局面での AI 最善手一致率を控えめに下げる
- 前提: `2026-04-12-jigo-humanlike-design.md`（JigoStrategy 本体設計）の拡張

## 背景と課題

現行 JigoStrategy は `current_lead` に応じて 3 分岐で着手を選ぶ（`_jigo_select_move`）:

| 分岐 | 条件 | 選択方法 |
|---|---|---|
| 1 | `lead < target_score` | `argmin(\|score - target\|)` |
| 2 | `in_range` & `mode=natural` | humanPolicy 重み選択 |
| 3 | `in_range` & `mode=maintain`、および `lead > target_max` | `argmin(\|score - target\|)` |

実戦で観察される挙動として、**target_score_max (10 目) を超えるまで AI 最善手と一致する手を連続で打つ**傾向が強い。原因は:

1. 分岐 1・3 の `argmin` がタイの場合 Python の `min()` 仕様により `move_infos` 先頭（KataGo 最善手）を返す
2. 分岐 2 の humanPolicy 重み選択でも、humanPolicy 最大手と KataGo 最善手は強く相関するため、結果的に最善手が選ばれやすい

分岐 2（既に stochastic）は別の課題なので今回は触らず、**分岐 1 と「`in_range` & `mode=maintain`」に対してのみ「同点扱いバンド」を導入**する。

## 目標

- 定石フェーズ（`lead < target_score`）と互角〜中盤の maintain モードで、target に「ほぼ同じぐらい近い」候補が複数あるときに humanPolicy 重みで分散選択する
- AI 最善手一致率の**控えめな低下**（batch_eval 実測で 5〜15% 程度を想定）
- `mean_ptloss` の劣化を +0.3 目以内に抑える
- target 範囲収束性（`lead <= target_score_max` への到達）を悪化させない
- 定石一本道局面では候補1個のみバンドに入り、現行と同じ手を打つ

## 非目標

- 分岐 2（`in_range & natural`）への適用 — 既に humanPolicy 重みで stochastic
- 分岐「`lead > target_score_max`」への適用 — 削り意図と干渉するため除外
- ε の動的調整（lead 差に応じた可変化） — YAGNI、固定値で開始
- ε の盤面サイズ別デフォルト（19路 / 13路 / 9路で分けない）— 1 値で開始
- 純ランダム tiebreak — humanPolicy 重みのほうが人間らしさを保てる

## アーキテクチャ

### 変更対象の 4 分岐整理

現行 `_jigo_select_move` を 4 分岐に整理（分岐 3 を「maintain」と「over-max」に分離）:

| 分岐 | 条件 | 現状 | 変更後 |
|---|---|---|---|
| 1 | `lead < target_score` | `argmin(\|score - target\|)` | **ε バンド + humanPolicy 重み** |
| 2 | `in_range` & `mode=natural` | humanPolicy 重み | 変更なし |
| 3 | `in_range` & `mode=maintain` | `argmin(\|score - target\|)` | **ε バンド + humanPolicy 重み** |
| 4 | `lead > target_score_max` | `argmin(\|score - target\|)`（鋭手除外後） | 変更なし |

### ε バンド選択ヘルパー（新設）

```python
def _pick_target_closest_with_epsilon(candidates, target, epsilon):
    """target に近い候補群を同点扱いし、humanPolicy 重みで選択する。

    - epsilon=0 または候補1個 → 現行の argmin と同じ手を返す
    - candidates 空 → None（上位でフォールバック処理済）
    - バンド内 hp 全ゼロ → argmin による決定的選択（safety net）
    """
    if not candidates:
        return None
    diffs = [(c, abs(c["score"] - target)) for c in candidates]
    min_diff = min(d for _, d in diffs)
    band = [c for c, d in diffs if d <= min_diff + epsilon]
    if epsilon <= 0 or len(band) <= 1:
        return band[0]
    total_hp = sum(c["hp"] for c in band)
    if total_hp <= 0:
        return min(band, key=lambda c: abs(c["score"] - target))
    weighted = [(c, c["hp"]) for c in band]
    return weighted_selection_without_replacement(weighted, 1)[0][0]
```

### `_jigo_select_move` の書き換え

```python
def _jigo_select_move(candidates, current_lead, target_score, target_score_max, mode, epsilon):
    in_range = target_score <= current_lead <= target_score_max

    # 分岐 1: 負け〜互角
    if current_lead < target_score:
        return _pick_target_closest_with_epsilon(candidates, target_score, epsilon)

    # 分岐 2: in_range & natural（変更なし）
    if in_range and mode == "natural":
        weighted = [(c, c["hp"]) for c in candidates]
        return weighted_selection_without_replacement(weighted, 1)[0][0]

    # 分岐 3: in_range & maintain
    if in_range and mode == "maintain":
        return _pick_target_closest_with_epsilon(candidates, target_score, epsilon)

    # 分岐 4: lead > target_max（変更なし、削り意図を保つ）
    return min(candidates, key=lambda c: abs(c["score"] - target_score))
```

呼び出し元（`JigoStrategy.generate_move`, ai.py:1054）では `self.settings.get("jigo_equivalent_epsilon", 0.5)` を渡す。

### tiebreak に humanPolicy 重みを選んだ理由

ユーザーの初期案は純ランダムだったが、humanPolicy 重みを採用する理由:

- バンド内で「人間が打ちそうな手」を優先 → 人間らしさを維持
- humanPolicy が偏る局面では決定的に近く、均等な局面では分散 → 自然な挙動
- バンド内 hp 全ゼロ時は argmin にフォールバックするため極端な悪手は出ない

## 設定項目

### 新規パラメータ

| キー | 型 | デフォルト | 選択肢 | 備考 |
|---|---|---|---|---|
| `jigo_equivalent_epsilon` | float | 0.5 | [0.0, 0.3, 0.5, 1.0] | target-closest からの同点扱い許容幅（目数）。0.0 で完全現行動作 |

### 配置ファイル（CLAUDE.md の 3 箇所ルール）

1. `katrain/core/constants.py` — `AI_OPTION_VALUES[AI_JIGO]` に追加
2. `katrain/config.json` — パッケージ同梱デフォルト値
3. `C:\Users\iwaki\.katrain\config.json` — ユーザーローカル設定（**メインセッションで直接 Edit**、サブエージェント委任禁止）
4. `.claude/rules/ai-parameters.md` — JigoStrategy パラメータテーブルに追記

## エッジケース処理

| ケース | 動作 |
|---|---|
| `epsilon = 0.0` | `len(band) == 1` に収束し現行 `argmin` と同じ手を返す（レグレッション保証） |
| 候補リスト空 | `None` 返却（上位の既存フォールバックに委ねる） |
| バンド内候補1個 | humanPolicy 選択をスキップして即返却 |
| バンド内 humanPolicy 全ゼロ | `argmin(\|score - target\|)` で決定的選択（safety net） |
| `lead > target_max` | ε を適用しない（分岐 4、削り意図を保つ） |
| 鋭手除外（`_jigo_exclude_sharp_moves`）後 | 鋭手除外は分岐 4 のみ発動するため ε と干渉しない |

## テスト計画

### ユニットテスト（新規 `tests/test_jigo_epsilon.py`）

1. `ε=0.0` で現行 `argmin` と同じ手を返す（レグレッション保証）
2. 単独候補 → そのまま返却
3. 複数候補かつバンド内 hp 非ゼロ → humanPolicy 重み分布で選択される
4. バンド内 hp 全ゼロ → `argmin` による決定的選択
5. `lead > target_max` 分岐では ε 無視（`_pick_target_closest_with_epsilon` は呼ばれない）
6. `lead < target_score` 分岐で ε を適用（分岐 1 経由で `_pick_target_closest_with_epsilon` が呼ばれる）
7. `in_range & maintain` で ε を適用（分岐 3 経由）
8. `in_range & natural` では ε を無視（分岐 2 は humanPolicy 重み単体のまま）

### batch_eval 校正

**対象 SGF**: `docs/superpowers/specs/calibration-data/jigo-speedup/` の既存 SGF から 2〜3 局を流用可能か確認後決定。流用不可なら新規 SGF を撮り直す。

**比較条件**:
- `ε ∈ {0.0, 0.3, 0.5, 1.0}` × 3-run 平均（jigo の KataGo 探索非決定性メモリに基づく）
- `jigo_mode ∈ {"natural", "maintain"}` 両方で計測

**測定指標**:
- `ai_top_move` — AI 最善手一致率（低下が目標）
- `mean_ptloss` — 平均損失目数（劣化を +0.3 目以内に抑える）
- target 範囲（`[target_score, target_score_max]`）内への収束率
- Choice-vs-Median Gap / Post-98% Slack（lambdago 指標、`docs/superpowers/specs/2026-04-14-lambdago-cheat-metrics-design.md`）

**合格基準（案）**:
- `ai_top_move` が ε=0.5 で 5〜15% 程度低下
- `mean_ptloss` が ε=0.0 比で +0.3 目以内
- target 超過局数（`lead > target_score_max` の手数）が増加しない
- natural モードは分岐 2 のまま変更なしなので ε による指標差は実測誤差範囲内に収まる想定（確認用）

### 手動検証

1. `python -m katrain_debug --sgf <SGF> --move <N> --strategy jigo --settings jigo_equivalent_epsilon=0.5` で単一局面の挙動確認
2. KaTrain GUI で jigo モード対局、ログ (`[JigoStrategy] Selected:`) を確認

## 実装順序（writing-plans 用メモ）

1. `_pick_target_closest_with_epsilon` ヘルパーの新設と unit test
2. `_jigo_select_move` の 4 分岐化と ε 引数追加
3. `JigoStrategy.generate_move` からの引数渡し
4. `katrain/core/constants.py` の `AI_OPTION_VALUES` 追加
5. `katrain/config.json` のデフォルト追加
6. ユーザーローカル `C:\Users\iwaki\.katrain\config.json` 追加（メインセッション直接 Edit）
7. `.claude/rules/ai-parameters.md` 追記
8. batch_eval 校正（3-run 平均 × ε 4 値 × mode 2 値 × SGF 2〜3）
9. 校正結果を本 spec の付録に追記

## 参考

- 関連 spec: `docs/superpowers/specs/2026-04-12-jigo-humanlike-design.md`（JigoStrategy 本体）
- 関連 spec: `docs/superpowers/specs/2026-04-13-jigo-large-lead-max-loss-design.md`（圧勝時 max_loss 動的緩和）
- 関連 spec: `docs/superpowers/specs/2026-04-13-jigo-dynamic-rank-calibration-design.md`（動的 rank 降格）
- CLAUDE.md の「やってはいけないこと」: `weighted_selection_without_replacement` の使い方、ユーザーローカル config の編集は必ずメインセッション
- `.claude/rules/ai-parameters.md`: JigoStrategy パラメータ一覧（更新対象）
