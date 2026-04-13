# JigoStrategy 弱相手対応 設計書

- 作成日: 2026-04-13
- 対象: `katrain/core/ai.py` の `JigoStrategy`（`ai:jigo`）
- 方針: 現行実装（`2026-04-12-jigo-humanlike-design.md`）に対する追加改修として、弱い相手（3〜7段相当）に対しても AI らしさを崩さずに対応できるようにする
- 前提: 現行の 2段階クエリ + 損失/humanPolicy フィルタ構造は維持

## 背景と課題

現行 `JigoStrategy` は humanSL 9段を固定で使用し、`max_loss_per_move = 5.6` / `min_human_policy = 0.01` のフィルタで人間らしさを担保している。これは 9段相当の相手との対局で目差を target レンジに収束させる前提で調整されている。

既知の限界（`.claude/rules/ai-parameters.md` に明記）:

> 相手が毎手 6 目以上の大損失手を連続で打つような極端な棋力差の対局では、1 手あたり損失上限 `max_loss_per_move (5.6)` を AI 側が超えられず、target 範囲への収束が保証されない。

弱い相手との対局で発生する具体的な問題:

1. **収束困難**: 相手が 3〜7段相当で毎手 3目以上の悪手を打ってくると、リードが際限なく広がる。フィルタ内で選べる give-back 幅（最大 5.6目）では追いつかない。
2. **鋭手選択リスク**: target 超過状態でも、KataGo が提示する最善手は依然として「さらに差を広げる鋭手」になりうる。selection の `abs(score - target)` 距離が最小でも、候補が鋭手しかない場合に落ちる。
3. **AI らしさの露出懸念**: 上記を単純に「max_loss を 15 に引き上げる」等で緩和すると、humanPolicy が低い「人間なら打たない譲歩手」が通ってしまう。

## 目標

- 弱い相手との対局でも **「人間なら絶対打たない手」を絶対に選ばない**（humanPolicy フロアの厳格化）
- 圧勝状況で **「さらに差を広げる鋭手」を明示的に回避**（鋭手除外）
- humanSL rank を設定可能にし、相手に合わせた棋力分布を選べる
- 相手の棋力（＝ lead-delta）に応じて rank を自動降格する opt-in 機能を提供
- target 収束は best-effort とし、**人間らしさを最優先**

## 非目標

- `max_loss_per_move` を大幅に引き上げる方向の改修（明らかな譲歩手の混入を招くため、ユーザ方針により不採用）
- 棋譜履歴解析による相手棋力推定（D-b 方式。opt-in でも複雑度が高いため defer）
- 複数局にまたがる相手モデリング（毎回異なる相手を前提とするため不要）
- target 範囲への収束保証（人間らしさとトレードオフ）

## 設計方針サマリ

| 変更 | 分類 | 概要 |
|---|---|---|
| A | 必須 | 鋭手除外（`current_lead > target_score_max` 時、`score > current_lead + ε` の手を除外） |
| B | 必須 | humanPolicy フロア強化（デフォルト 0.01→0.02、緩和下限 0.005 ハードフロア） |
| C | 追加 | humanSL rank 設定可能化（`human_profile`：rank_5d / rank_7d / rank_9d） |
| D-a | 追加 | 動的 rank 切替（opt-in、lead-delta ベース） |

## アーキテクチャ

### 全体フロー（変更箇所を ★ で示す）

```
[設定読み込み]
  target_score, target_score_max, max_loss, min_hp, mode に加え:
  ★ human_profile (default rank_9d)
  ★ jigo_dynamic_rank (default false)

[★ 動的 rank 判定 (D-a)]
  jigo_dynamic_rank=true かつ着手前 current_lead 既知なら:
    effective_rank = _select_rank_by_lead(current_lead, target_score_max)
  else:
    effective_rank = human_profile

  ※ current_lead は前ターンに Stage2 で計算されていれば再利用、
     初手など未知の場合は human_profile をそのまま使用

[Stage 1: humanSL クエリ (maxVisits=800)]
  humanSLProfile = effective_rank   ★ 従来は "rank_9d" 固定

[Stage 2: クリーンクエリ (maxVisits=600, wideRootNoise=0)]
  変更なし — 正確な scoreLead を取得

[候補リスト構築]
  変更なし — {move, score, loss, hp} を構築

[★ フィルタ (B: hp フロア強化)]
  filtered = [c for c in candidates
              if c["loss"] <= max_loss AND c["hp"] >= min_hp]
  ※ min_hp のデフォルトが 0.02 に変更されるのみ、ロジックは同じ

[★ 段階緩和フォールバック (B: ハードフロア追加)]
  現行: hp×0.5 → hp×0.25 → loss×1.5 → safety valve
  新 : hp×0.5 → hp×0.25 → loss×1.5 → safety valve
       ただし各段階で max(min_hp × factor, 0.005) を適用
       → 0.5% より下げない

[★ 鋭手除外 (A)]
  if current_lead > target_score_max:
    non_sharp = [c for c in filtered
                 if c["score"] <= current_lead + SHARP_EPSILON]
    if non_sharp:
      filtered = non_sharp
    # 空なら除外スキップ（安全弁）

[選択ロジック分岐]
  変更なし（現行 _jigo_select_move）
```

### 変更 A: 鋭手除外

```python
SHARP_EPSILON = 0.5  # 微小な浮動小数ノイズを許容するバッファ

def _jigo_exclude_sharp_moves(candidates, current_lead, epsilon=SHARP_EPSILON):
    """圧勝時に「リードをさらに広げる手」を除外する。

    current_lead を厳密に超える score を持つ手を候補から落とす。
    結果が空になる場合は除外をスキップ（呼び出し側で filtered を保持）。
    """
    non_sharp = [c for c in candidates if c["score"] <= current_lead + epsilon]
    return non_sharp if non_sharp else candidates  # 全滅なら元のまま
```

呼び出し箇所:

```python
# _jigo_filter_candidates / _jigo_relax_filters のあと、
# _jigo_select_move の直前

if current_lead > target_score_max:
    before_exclude = len(filtered)
    filtered = _jigo_exclude_sharp_moves(filtered, current_lead)
    self.game.katrain.log(
        f"[JigoStrategy] Sharp-move exclusion: {before_exclude} → {len(filtered)} "
        f"(lead={current_lead:.2f} > target_max={target_score_max})",
        OUTPUT_DEBUG,
    )
```

**挙動補足**:
- `in_range` / `current_lead < target_score` の場合は除外を走らせない（ target を狙って積極的に打つフェーズなので、鋭手 = 最善手は当然選んでよい）
- `SHARP_EPSILON = 0.5` は KataGo scoreLead の微細ノイズで target_max を一瞬超えた場合の誤判定を防ぐため

### 変更 B: humanPolicy フロア強化

#### B-1. デフォルト値の変更

| 場所 | 現行 | 新 |
|---|---|---|
| `katrain/config.json` の `ai:jigo.min_human_policy` | `0.01` | `0.02` |
| `C:\Users\iwaki\.katrain\config.json` の `ai:jigo.min_human_policy` | `0.01` | `0.02` |

`AI_OPTION_VALUES["min_human_policy"]` の選択肢は現行のまま（`(0.005, "0.5%"), (0.01, "1%"), (0.02, "2%"), (0.05, "5%")`）で、デフォルトを 2% 寄りに移動する扱い。

#### B-2. 段階緩和のハードフロア

```python
MIN_HP_HARD_FLOOR = 0.005  # 0.5% — これより下には絶対に緩和しない

def _jigo_relax_filters(candidates, max_loss, min_hp, hard_floor=MIN_HP_HARD_FLOOR):
    reason_map = [("hp_half", 0.5), ("hp_quarter", 0.25)]
    for reason, hp_factor in reason_map:
        threshold = max(min_hp * hp_factor, hard_floor)  # ★ ハードフロア適用
        f = [c for c in candidates
             if c["loss"] <= max_loss and c["hp"] >= threshold]
        if f:
            return f, reason
    threshold = max(min_hp * 0.25, hard_floor)
    f = [c for c in candidates
         if c["loss"] <= max_loss * 1.5 and c["hp"] >= threshold]
    if f:
        return f, "loss_150"
    return ([candidates[0]] if candidates else []), "safety_valve"
```

**挙動例**（`min_hp = 0.02` の場合）:
- hp×0.5 → 0.01（ハードフロア以上なのでそのまま）
- hp×0.25 → 0.005（ハードフロアに張り付き）
- loss×1.5 + hp×0.25 → 0.005（ハードフロアに張り付き）

**挙動例**（`min_hp = 0.01` を手動選択した場合）:
- hp×0.5 → 0.005（ハードフロアに張り付き）
- hp×0.25 → 0.0025 → **0.005 にクリップ**（新挙動）
- これにより min_hp をユーザが下げても「人間なら打たない手」までは到達しない

### 変更 C: humanSL rank 設定可能化

#### C-1. 新設定項目

| キー | 型 | 選択肢 | デフォルト | GUI 表示 |
|---|---|---|---|---|
| `human_profile` | ラベル付き文字列 | `rank_5d` / `rank_7d` / `rank_9d` | `rank_9d` | スライダー風（3ノッチ） |

`AI_OPTION_VALUES["human_profile"]`:

```python
"human_profile": [
    ("rank_5d", "5段"),
    ("rank_7d", "7段"),
    ("rank_9d", "9段"),
],
```

`AI_OPTION_ORDER` の `human_profile`: `JigoStrategy` セクション内で `target_score`（=0）より前に表示。値は `-1` 等を割り当て。

#### C-2. Stage 1 クエリでの使用

```python
# 従来
human_profile = "rank_9d"  # 9段固定

# 新
human_profile = self.settings.get("human_profile", "rank_9d")
# さらに D-a が有効なら動的 rank 選択ロジックで上書き（次節）
```

#### C-3. 下位 rank の挙動確認（実装前メモ）

KataGo humanSL モデルは `rank_Xd` / `rank_Yk` 系の段位指定を受け付ける。事前に `katrain_debug` で `rank_5d` / `rank_7d` が実際にモデルで応答を返すか検証する（humanSL モデルが未学習の段位を指定すると 0% 近い humanPolicy が返る可能性あり）。

失敗時のフォールバック: `rank_5d` / `rank_7d` の応答が妥当でない場合、選択肢を `rank_9d` 固定のまま保持し、C を取り下げる（D-a は 9段固定でも lead-delta に応じて別戦略で対応可能）。

### 変更 D-a: 動的 rank 切替（lead-delta ベース）

#### D-a-1. 新設定項目

| キー | 型 | デフォルト | 備考 |
|---|---|---|---|
| `jigo_dynamic_rank` | bool | `false` | ON で lead-delta に応じて rank を自動降格 |

OFF の場合は `human_profile` の値をそのまま使用。

#### D-a-2. 降格ロジック

```python
def _select_rank_by_lead(current_lead, target_score_max, base_profile):
    """リードが target_max をどれだけ超えているかで rank を降格する。

    - delta ≤ 5  : base_profile そのまま
    - 5 < delta ≤ 15 : chain で1段下（9d → 7d, 7d → 5d, 5d → 5d）
    - delta > 15 : 一気に rank_5d まで下げる（9d → 5d, 7d → 5d, 5d → 5d）
    """
    delta = current_lead - target_score_max
    rank_chain = ["rank_5d", "rank_7d", "rank_9d"]
    if base_profile not in rank_chain:
        return base_profile  # 未知のプロファイルは触らない
    idx = rank_chain.index(base_profile)
    if delta > 15:
        new_idx = 0  # rank_5d まで下げる
    elif delta > 5:
        new_idx = max(0, idx - 1)
    else:
        new_idx = idx
    return rank_chain[new_idx]
```

#### D-a-3. current_lead の取得タイミング問題

Stage 1 クエリ実行前に `current_lead` を知る必要があるが、現行実装では Stage 2（クリーンクエリ）で scoreLead を取得しており、順序的には Stage 1 が先。

対応策:

- **前ターンの Stage 2 結果をキャッシュ**する
  - `JigoStrategy` インスタンスに `_last_current_lead: float | None` を保持
  - 各ターン末尾で `score_analysis["rootInfo"]["scoreLead"] * sign` を記録
  - 次ターンの冒頭で「前ターン末尾 + 相手の1手」の近似値として利用
  - 初手や戦略切替直後はキャッシュ未設定 → D-a を発動せず base_profile を使用

- もしくは **Stage 0 として超軽量な root 評価のみを先行実行**
  - コストは高いが正確
  - 初期実装では不採用、キャッシュ方式で十分

**採用**: キャッシュ方式。精度は犠牲になるが実装が単純で、相手1手分のズレは rank 判定には十分許容できる粒度。

```python
# generate_move の末尾付近で保存
self._last_current_lead = current_lead
```

（`JigoStrategy.__init__` で `self._last_current_lead = None` 初期化）

#### D-a-4. ログ出力

```
[JigoStrategy] Dynamic rank: base=rank_9d, lead=25.3, delta=15.3 > 15 → rank_5d
```

## パラメータ一覧（更新後）

| パラメータ | デフォルト値 | 選択肢 | 備考 |
|---|---|---|---|
| target_score | 0.5 | 既存 | 狙う目差 |
| target_score_max | 10.0 | 既存 | 許容上限 |
| max_loss_per_move | 5.6 | 既存 | **変更なし（ユーザ方針）** |
| min_human_policy | **0.02** | 0.005 / 0.01 / 0.02 / 0.05 | **デフォルト変更** |
| jigo_mode | "natural" | natural / maintain | 既存 |
| **human_profile** | **"rank_9d"** | rank_5d / rank_7d / rank_9d | **新規** |
| **jigo_dynamic_rank** | **false** | bool | **新規** |

## ファイル変更一覧

| ファイル | 変更内容 |
|---|---|
| `katrain/core/ai.py` | `_jigo_exclude_sharp_moves` 追加、`_jigo_relax_filters` ハードフロア、`_select_rank_by_lead` 追加、`JigoStrategy.generate_move` 統合、`__init__` で `_last_current_lead` 初期化 |
| `katrain/core/constants.py` | `AI_OPTION_VALUES` に `human_profile` / `jigo_dynamic_rank` 追加、`AI_OPTION_ORDER` 更新 |
| `katrain/config.json` | `ai:jigo` に `human_profile` / `jigo_dynamic_rank` 追加、`min_human_policy` デフォルトを 0.02 に |
| `C:\Users\iwaki\.katrain\config.json` | 上と同じ（メインセッションで直接編集、サブエージェントに委任しない） |
| `.claude/rules/ai-parameters.md` | JigoStrategy セクションに新パラメータ、挙動記述を追加 |
| `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po` | `aihelp:jigo` / `human_profile` / `jigo_dynamic_rank` のラベルと説明を追加 |
| `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.mo` | `python tools/compile_mo.py` で再生成 |
| `CLAUDE.md` | 現在のパラメータ値テーブル（必要なら）、弱相手対応の説明 |

## エラー処理・フォールバック

| 状況 | 挙動 |
|---|---|
| Stage 1 失敗 | 既存どおり KataGo 最善手にフォールバック（AI としては人間らしくないが致命ではない） |
| Stage 2 失敗 | 既存どおり Stage 1 の moveInfos を使用（バイアスあり） |
| 鋭手除外で候補全滅 | 除外をスキップし元の filtered を使用 |
| 動的 rank: `_last_current_lead is None` | 初手／戦略切替直後。`base_profile`（= `human_profile` 設定値）をそのまま使用 |
| 動的 rank: 下位 rank が低 humanPolicy しか返さない | 緩和フォールバック（hp×0.5/×0.25）→ 最終 safety valve。ハードフロア 0.005 で歯止め |
| `human_profile` に未知の値 | `_select_rank_by_lead` は base_profile を返す → Stage 1 はその値で照会、KataGo が無視する場合は空 humanPolicy → 既存の失敗パスへ |

## テスト・検証

### 単体テスト（Kivy 依存なしで実行可能）

`tests/test_ai.py` または新規 `tests/test_jigo.py` に追加:

- `_jigo_exclude_sharp_moves`:
  - `current_lead=+20`, 候補に `score=+22` / `score=+18` / `score=+15` → `+18` と `+15` のみ残る
  - 全候補が `score > current_lead` → 入力そのまま返す（空にしない）
  - `epsilon=0.5` の境界: `score=+20.4` は残る、`+20.6` は除外
- `_jigo_relax_filters`（ハードフロア）:
  - `min_hp=0.02`, hp×0.25=0.005 → ちょうどフロア
  - `min_hp=0.005`, hp×0.25=0.00125 → 0.005 にクリップ
- `_select_rank_by_lead`:
  - `base=rank_9d`, delta=3 → `rank_9d`
  - `base=rank_9d`, delta=10 → `rank_7d`
  - `base=rank_9d`, delta=20 → `rank_5d`
  - `base=rank_7d`, delta=20 → `rank_5d`
  - `base=rank_5d`, delta=20 → `rank_5d`（下限）
  - `base="unknown"`, delta=20 → `"unknown"`（変化なし）

### 統合検証（`katrain_debug` 使用）

```bash
# 既存の panda1.sgf 等で基準確認（9段相手）
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --batch --player W

# 鋭手除外の単点確認（圧勝局面）
python -m katrain_debug --sgf <圧勝SGF> --move <着手番号> --strategy jigo \
    --settings target_score=0.5 target_score_max=5.0 --output text
# 期待: ログに "Sharp-move exclusion: N → M" が出現

# 動的 rank の単点確認
python -m katrain_debug --sgf <圧勝SGF> --move <着手番号> --strategy jigo \
    --settings jigo_dynamic_rank=true --output text
# 期待: ログに "Dynamic rank: base=rank_9d, lead=..., delta=..., → rank_Xd"
```

### 実戦検証

- `C:\Users\iwaki\.katrain\config.json` の `debug_level: 1` で起動
- JigoStrategy で対局（自分が相手役として弱い手を故意に打つテストシナリオ）
- ログを Grep で確認:
  - `grep "Sharp-move exclusion"` — 圧勝時に発動しているか
  - `grep "Dynamic rank"` — lead-delta 降格が発生しているか
  - `grep "Safety valve"` — ハードフロア到達頻度（多すぎなら閾値見直し）

### バッチ評価によるパラメータ校正

D-a の降格閾値（5 / 15）は初期値であり、以下の手順で校正する:

1. 弱い相手を想定した SGF を複数（例: 7段 vs 9段、5段 vs 9段）用意
2. `--batch` で各 rank × delta 閾値の組み合わせを評価
3. 指標:
   - 目差収束度（終局スコアが target_score_max 以内に入る割合）
   - AI らしさ維持度（humanPolicy 最低値、safety valve 発動率）
4. 両指標のバランスが良い設定を確定

校正結果は `.claude/rules/ai-parameters.md` に反映。

## 移行・互換性

- 既存ユーザの `ai:jigo` 設定は `target_score` / `target_score_max` / `max_loss_per_move` / `min_human_policy` / `jigo_mode` のみ保持している想定
- 新キー `human_profile` / `jigo_dynamic_rank` は起動時に読み込み → 未設定なら新デフォルト（`rank_9d` / `false`）が適用される
- `min_human_policy` のデフォルト変更（0.01 → 0.02）は既に 0.01 を明示保存しているユーザには影響しない（そのユーザの値を尊重）。新規ユーザ・デフォルト値を使っているユーザのみ 0.02 に自動移行
- 起動時リセット: `base_katrain.py` の `_load_config` 末尾で `jigo_dynamic_rank` を強制リセットする必要はない（挙動を変える opt-in 機能であり、ユーザが明示的に ON にするもの）

## 実装順序（想定）

1. 純粋関数の追加: `_jigo_exclude_sharp_moves` / `_select_rank_by_lead` / ハードフロア付き `_jigo_relax_filters`
2. 単体テスト追加・パス
3. `JigoStrategy.generate_move` への統合（`__init__` キャッシュ初期化含む）
4. `constants.py` / `config.json` / ユーザ `config.json` への設定追加
5. `katrain_debug` での単点検証（A / B / C / D-a それぞれ）
6. i18n ラベル追加 → `compile_mo.py`
7. 実戦対局での挙動確認
8. `.claude/rules/ai-parameters.md` / `CLAUDE.md` の更新
9. バッチ評価によるパラメータ校正（任意、設計検証後の別タスクでも可）

## 未解決事項・リスク

- **`rank_5d` / `rank_7d` の humanSL モデル応答精度**: 事前検証で問題があれば C を取り下げ、D-a も 9段固定での動作に限定する
- **動的 rank の降格閾値（5 / 15）は当て推量**: バッチ評価で要校正。ただし opt-in なので未校正状態でもデフォルト（OFF）動作に影響なし
- **キャッシュ方式の 1手分ラグ**: 前ターン末尾の lead を使うため、相手の強烈な勝負手1つで rank 判定がズレる可能性。ただし rank は段階的なので実害は限定的

## 校正履歴

- **2026-04-13 校正完了**: N=1 SGF で評価、有意差なしのため現行値 5/15 を維持。
  詳細: `docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md`
