# JigoStrategy 油断誘発（deception）フェーズ機構 設計書

- 作成日: 2026-05-16
- 対象: `katrain/core/ai.py` の `JigoStrategy.generate_move()`
- 方針: 序中盤で意図的に 2〜3 目劣勢を維持し、終盤で指定 target に収束させる新オプション機能
- 前提: `2026-04-12-jigo-humanlike-design.md`（JigoStrategy 本体）、`2026-04-19-jigo-epsilon-tiebreak-design.md`（ε バンド）

## 背景と狙い

現行 JigoStrategy は最初から `target_score (+0.5)` を狙うため、序盤から「ちょうど勝つ」進行になる。これは KataGo 最善手と一致しすぎる傾向と相まって、対局相手に「明らかに不自然に強い」「最後まで均衡を保つ」印象を与えやすい。

人間同士の対局では、**序中盤に小幅劣勢に見えていた側が終盤で逆転する**展開がしばしば起こる（読みの深さ・終盤の正確さの差）。本機能はこの「序中盤の劣勢 → 終盤逆転」を演出することで:

1. 相手を油断させ、終盤の集中力を緩める効果を狙う
2. 終始リードを保つ Jigo 既存挙動より「人間らしい」棋風に見せる

ただし序盤の定石/布石で大きく外すと取り返しのつかない損失が出るため、**Phase 0（純粋な定石期間）は通常 Jigo として打ち、Phase 1（序中盤入口）から段階的に控える**設計とする。

## 目標

- 19 路盤で「中盤入口 (30 手目〜) で約 -3 目劣勢 → 中盤後半 (80 手目〜) で約 -1.5 目 → 終盤入口 (150 手目〜) で target_score (+0.5) に収束」を実現する
- 既存 Jigo ユーザの挙動を一切変えない（デフォルト OFF のオプトイン式）
- 13 路 / 9 路でも盤面サイズに比例したスケールで同様の挙動を提供
- 異常状態（過剰優勢・過剰劣勢）では Phase 3 に強制ジャンプして勝利優先に切替
- 既存 `_jigo_select_move` ロジック・`jigo_dynamic_rank`・`jigo_equivalent_epsilon`・`jigo_large_lead_max_loss` と共存

## 非目標

- 純粋な棋風変化（一手ごとの「らしさ」改善）— 本機能はあくまでスコア軌跡の演出
- Phase 境界手数や控え目標値の GUI 編集 — MVP ではコード固定、将来拡張可能性は残す
- 対局途中での deception ON/OFF 切替 — 起動時設定固定
- 「相手の悪手検出に応じた回復タイミング調整」— YAGNI、手数ベースで開始
- Phase 機構内で `jigo_mode = natural` を活かす — 控えと natural は意味的に矛盾するため、Phase 1/2 中は強制的に maintain 相当（分岐 4）の挙動になる
- 多言語化（i18n） — MVP では設定キー追加のみ、`.po` / `.mo` 更新は後続タスク

## アーキテクチャ

### Phase 解決層の挿入

`JigoStrategy.generate_move()` の Stage 1/2 クエリ前に Phase 解決層を新設する。Phase 0/3 では既存 `target_score` / `target_score_max` をそのまま使い、Phase 1/2 では一時的に**負の値**へ上書きする。`_jigo_select_move` の 4 分岐ロジック自体は変更しない。

```
JigoStrategy.generate_move()
  ├─ 設定読み込み（既存）
  ├─ [NEW] Phase 解決
  │   ├─ jigo_deception=False → effective_target = (target_score, target_score_max)
  │   └─ jigo_deception=True  →
  │       ├─ 現在手数 + 盤面サイズから base_phase 決定
  │       ├─ 安全弁（過剰優勢/過剰劣勢）で base_phase を phase3 に上書き
  │       └─ phase に応じて effective_target = (eff_target, eff_target_max) を決定
  ├─ Stage 1 humanSL クエリ（既存、effective_target_max を dynamic_rank へ渡す）
  ├─ Stage 2 クリーンクエリ（既存）
  ├─ effective_max_loss 計算（既存、effective_target_max を使用）
  ├─ filter & relax（既存）
  └─ _jigo_select_move(..., eff_target, eff_target_max, mode, epsilon)（既存）
```

### Phase テーブル（モジュール定数）

```python
# ai.py
JIGO_DECEPTION_PHASE_TABLE = {
    19: [(30, "phase1"), (80, "phase2"), (150, "phase3")],
    13: [(17, "phase1"), (44, "phase2"), (83, "phase3")],
    9:  [(8,  "phase1"), (20, "phase2"), (38, "phase3")],
}

# (board_size, phase) → (target_score, target_score_max) or None
# None = ユーザ設定 (target_score, target_score_max) をそのまま使用
JIGO_DECEPTION_TARGETS = {
    (19, "phase0"): None,
    (19, "phase1"): (-3.0, -2.0),
    (19, "phase2"): (-1.5, -0.5),
    (19, "phase3"): None,
    (13, "phase0"): None,
    (13, "phase1"): (-2.0, -1.0),
    (13, "phase2"): (-1.0,  0.0),
    (13, "phase3"): None,
    (9,  "phase0"): None,
    (9,  "phase1"): (-1.5, -0.5),
    (9,  "phase2"): (-0.5,  0.0),
    (9,  "phase3"): None,
}

JIGO_DECEPTION_SAFETY_OVERSHOOT = 5.0  # 目数（±5 目で phase3 強制ジャンプ）
```

未対応盤面サイズ（例: 7 路・15 路）は 19 路テーブルにフォールバック（既存 HuntStrategy と同じ思想）。

### Phase 解決関数（新設）

`_jigo_resolve_phase` は手数ベースの base phase を内部解決し、安全弁判定に必要な target_max も `JIGO_DECEPTION_TARGETS` から自己ルックアップする。呼び出し側は board_size / move_num / last_lead を渡すだけで完結する。

```python
def _jigo_resolve_phase(board_size, move_num, current_lead):
    """手数 + 安全弁から有効 phase を返す。

    Args:
        board_size: 19/13/9 等。テーブル未登録なら 19 路にフォールバック
        move_num: 1-indexed の現在手数（self.cn.depth 相当）
        current_lead: 前ターンの current_lead（None なら安全弁スキップ）

    Returns:
        "phase0" | "phase1" | "phase2" | "phase3"
    """
    table = JIGO_DECEPTION_PHASE_TABLE.get(board_size, JIGO_DECEPTION_PHASE_TABLE[19])
    base_phase = "phase0"
    for boundary, phase in table:
        if move_num >= boundary:
            base_phase = phase

    # 安全弁は phase1/phase2 のみ
    if base_phase in ("phase1", "phase2") and current_lead is not None:
        targets = JIGO_DECEPTION_TARGETS.get((board_size, base_phase))
        if targets is not None:
            _, base_target_max = targets
            if current_lead > base_target_max + JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"  # 過剰優勢: 早期に勝ちにいく
            if current_lead < base_target_max - JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"  # 過剰劣勢: 回復に専念
    return base_phase
```

### `JigoStrategy.generate_move()` への組み込み

設定読み込み直後・dynamic_rank 計算前に挿入:

```python
deception_enabled = self.settings.get("jigo_deception", False)
eff_target = target_score
eff_target_max = target_score_max
phase = "phase0"
if deception_enabled:
    # KaTrain の Game.board_size は (width, height) tuple、正方形前提で width を採用
    board_size = self.game.board_size[0]
    move_num = self.cn.depth  # 1-indexed 手数
    last_lead = getattr(self.game, "_jigo_last_current_lead", None)
    phase = _jigo_resolve_phase(board_size, move_num, last_lead)
    overrides = JIGO_DECEPTION_TARGETS.get((board_size, phase))
    if overrides is None:
        # phase0/phase3 はユーザ設定そのまま、未登録 board_size は 19 路にフォールバック
        overrides = JIGO_DECEPTION_TARGETS.get((19, phase))
    if overrides is not None:
        eff_target, eff_target_max = overrides
    self.game.katrain.log(
        f"[JigoStrategy] Deception: move={move_num}, phase={phase}, "
        f"target={eff_target}, target_max={eff_target_max}, last_lead={last_lead}",
        OUTPUT_DEBUG,
    )
```

以降の処理は `target_score` → `eff_target`、`target_score_max` → `eff_target_max` に置換するだけ。`dynamic_rank` の `_select_rank_by_lead`、`_jigo_compute_effective_max_loss`、`_jigo_select_move` への引数渡しはすべて effective 値を使う。

### 既存 `_jigo_select_move` 4 分岐との適合

Phase 1/2 開始時の典型値で動作確認:

| 状況 | current_lead | eff_target | eff_target_max | 入る分岐 | 選択 |
|---|---|---|---|---|---|
| Phase 1 開始（19 路 30 手目、互角） | 0.0 | -3.0 | -2.0 | 分岐 4 (`lead > target_max`) | `argmin(\|score - (-3)\|)` → score ≈ -3 の手 |
| Phase 1 進行中（劣勢方向に振れた） | -2.5 | -3.0 | -2.0 | 分岐 1 (`lead < target`) | ε バンド + hp 重み（target=-3 付近） |
| Phase 1 in_range | -2.5 | -3.0 | -2.0 | 分岐 1 ではない… → 確認 | **下記注記参照** |

**注記**: `lead = -2.5` で `target = -3.0`, `target_max = -2.0` のとき、`in_range` 判定は `-3 ≤ -2.5 ≤ -2` で **True**。`jigo_mode` がデフォルト `"natural"` だと分岐 2（humanPolicy 単体重み）に入り、target に寄せない挙動になる。これは deception の意図と矛盾する。

**解決**: Phase 1/2 中は `_jigo_select_move` に渡す `mode` 引数を強制的に `"maintain"` に上書きする。これにより in_range でも分岐 3（target 最接近 + ε バンド）に入る。

```python
eff_mode = mode
if deception_enabled and phase in ("phase1", "phase2"):
    eff_mode = "maintain"
```

これで Phase 1/2 内のすべての lead 範囲で target に寄せる挙動が一貫する。

### sharp move exclusion との相互作用

`_jigo_exclude_sharp_moves` は分岐 4（`lead > target_max`）でのみ発動し、`score > current_lead + 0.5` を除外する。Phase 1 開始時（lead=0, target_max=-2）で分岐 4 に入る場合、`score > 0.5` を除外 = 「現状より良くなる手」を弾く。これは「劣勢方向に進めたい」意図に合致するため、**そのまま流用で OK**。

ただし Phase 1 で過剰劣勢に振れた瞬間（例: lead=-4）に分岐 1/3 が走り `_jigo_exclude_sharp_moves` は呼ばれない。これは想定通り（lead が target に近づいたら鋭手除外は不要）。

### `jigo_dynamic_rank` との相互作用

`_select_rank_by_lead(last_lead, target_score_max, base_profile, delta_1, delta_2)` は `delta = last_lead - target_score_max` で降格判定する。

| Phase | eff_target_max | last_lead | delta | 動作 |
|---|---|---|---|---|
| Phase 1 (19 路) | -2.0 | 0.0 | +2.0 | base のまま（delta ≤ 5） |
| Phase 1 | -2.0 | -4.0 | -2.0 | base のまま（負の delta は降格対象外） |
| Phase 3 (19 路) | 10.0 | 12.0 | +2.0 | base のまま |
| Phase 3 | 10.0 | 18.0 | +8.0 | 1 段降格 |

Phase 1/2 中は eff_target_max が小さい（≤ 0）ため delta が大きくなりやすく、**意図せず dynamic_rank が降格してしまう懸念がある**。例えば Phase 1 (eff_target_max=-2) で last_lead=+4 のとき delta=+6 → 1 段降格。これは「序中盤で控えるはずなのに勝ちすぎているから AI を弱くする」となり、deception の意図とは異なる方向の応急処置になる。

**設計判断**: この相互作用は許容する。理由:
- dynamic_rank はそもそも「target を超えて勝ちすぎたとき」の救済機構なので、Phase 1/2 で勝ちすぎ ＝ deception 失敗 → AI を弱くして相手の取り分を増やす方向は意味的に合致
- 安全弁（過剰優勢で Phase 3 ジャンプ）が +5 目で発動するため、+4 目程度では Phase 1/2 に留まる → dynamic_rank の助けで控え方向の手を増やしたい
- 実装簡素化（追加分岐なし）

ただし `jigo_dynamic_rank=true` かつ `jigo_deception=true` の組み合わせは校正で挙動を必ず確認する（dynamic_rank 降格が連発しないか）。

### `jigo_equivalent_epsilon`・`jigo_large_lead_max_loss` との相互作用

- `jigo_equivalent_epsilon`: 分岐 1/3 で ε バンド + hp 重み選択 → Phase 1/2 でも自然に効く（target が負でも distance は絶対値）
- `jigo_large_lead_max_loss`: `current_lead ≥ eff_target_max + jigo_large_lead_delta` で max_loss を緩和 → Phase 1 で lead=0, eff_target_max=-2, delta=5 → 0 ≥ 3 で発動。これは「Phase 1 で互角なのに max_loss を緩和」となり**不要な緩和**になる懸念

**対策**: Phase 1/2 中は `jigo_large_lead_max_loss` の緩和をスキップする。`_jigo_compute_effective_max_loss` 呼び出し時に `large_lead_delta = float("inf")` を渡せば緩和条件 `lead ≥ target_max + inf` が常に False になり、`max_loss_per_move` 既定値が維持される。

実装は既存呼び出しの引数差し替えのみ（実シグネチャ: `current_lead, target_score_max, base_max_loss, large_lead_delta, large_lead_max_loss, board_size`）:

```python
eff_large_lead_delta = large_lead_delta
if deception_enabled and phase in ("phase1", "phase2"):
    eff_large_lead_delta = float("inf")
effective_max_loss = _jigo_compute_effective_max_loss(
    current_lead, eff_target_max, max_loss,
    eff_large_lead_delta, large_lead_max_loss, board_size,
)
```

## 設定項目

### 新規パラメータ

| キー | 型 | デフォルト | 選択肢 | 備考 |
|---|---|---|---|---|
| `jigo_deception` | bool | false | true/false | Phase 0/1/2/3 機構を有効化（GUI: チェックボックス） |

Phase 境界手数・控え目標値・安全弁閾値はコード固定（モジュール定数）。将来 GUI 拡張するなら別 spec で追加。

### 配置ファイル（CLAUDE.md の 3 箇所ルール）

1. `katrain/core/constants.py` — `AI_OPTION_VALUES[AI_JIGO]` に `"jigo_deception": "bool"` 追加
2. `katrain/config.json` — パッケージ同梱デフォルト値 `"jigo_deception": false` 追加
3. `C:\Users\iwaki\.katrain\config.json` — ユーザーローカル設定（**メインセッションで直接 Edit**、サブエージェント委任禁止）
4. `.claude/rules/ai-parameters.md` — JigoStrategy パラメータテーブルに `jigo_deception` 行と Phase テーブル追記

## エッジケース処理

| ケース | 動作 |
|---|---|
| `jigo_deception=false` | Phase 解決層完全スキップ、既存挙動と完全一致 |
| 初手（move_num=1） | base_phase=phase0 → eff_target は user 設定そのまま（既存挙動） |
| `last_lead` キャッシュなし（初手 + deception=true） | 安全弁スキップ、base_phase のみで決定 |
| 未対応盤面サイズ（7 路・15 路 等） | 19 路テーブルにフォールバック |
| Phase 1/2 で過剰優勢 (`lead > eff_target_max + 5`) | phase3 強制ジャンプ → user 設定 target に向かう |
| Phase 1/2 で過剰劣勢 (`lead < eff_target_max - 5`) | phase3 強制ジャンプ → user 設定 target に向かう（max_loss も復帰） |
| Phase 3 中の lead 変動 | 安全弁判定なし（phase3 は終局フェーズ） |
| `jigo_mode = natural` + deception=true | Phase 1/2 では `eff_mode = maintain` に上書き、Phase 0/3 では natural のまま |
| 9 路盤の Phase 1 (`eff_target_max = -0.5`) | 9 路は `JIGO_LARGE_LEAD_9X9_CAP = 5.0` キャップが既存ロジックで適用される（`_jigo_compute_effective_max_loss` 内） |

## テスト計画

### ユニットテスト（新規 `tests/test_jigo_deception.py`）

1. `_jigo_resolve_phase` の手数境界テスト（19 路・13 路・9 路 × phase0〜3 の境界手数前後）
2. 安全弁: phase1 で lead=+10 → phase3
3. 安全弁: phase2 で lead=-10 → phase3
4. 安全弁: phase3 では lead 過剰でも phase3 のまま
5. 安全弁: last_lead=None → 安全弁スキップ、base_phase 返却
6. 未対応盤面サイズ（7） → 19 路テーブルにフォールバック
7. `JIGO_DECEPTION_TARGETS` ルックアップ: 各 (board_size, phase) で期待値返却
8. `JigoStrategy.generate_move()` 統合テスト: deception=false で従来挙動、deception=true で Phase 1 開始時に分岐 4 経由・score ≈ -3 の手が選ばれる（モック candidates）

### CLI 検証

```bash
# Phase 0 (純粋な定石期間)
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo \
  --settings jigo_deception=true --move 15 --output json

# Phase 1 入口（中盤入口）
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo \
  --settings jigo_deception=true --move 35 --output json

# Phase 2 入口
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo \
  --settings jigo_deception=true --move 90 --output json

# Phase 3 入口（通常 Jigo 復帰）
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo \
  --settings jigo_deception=true --move 160 --output json
```

各 phase で debug ログ（`[JigoStrategy] Deception: move=..., phase=...`）と選択手の score を確認。

### batch_eval 校正

**対象 SGF**: `docs/superpowers/specs/calibration-data/` から既存 jigo 関連 SGF (panda1.sgf 等) を流用。流用不可なら撮り直す。

**比較条件**:
- `jigo_deception ∈ {false, true}` × 3-run 平均（jigo の KataGo 探索非決定性メモリに基づく）
- `jigo_mode = natural` 固定（deception=true 時は Phase 1/2 で maintain に上書きされる挙動を含む）

**測定指標**:
- `ai_top_move` — AI 最善手一致率
- `mean_ptloss` — 平均損失目数
- 手数 30/80/150 時点の `score_lead` 分布（Phase 切替境界での実測）
- 終局 score（target_score 収束率）

**合格基準（案）**:
- 30 手目時点の `score_lead` 中央値が 0 〜 -2 目程度（Phase 0 から Phase 1 への移行が機能）
- 80 手目時点の `score_lead` 中央値が -1 〜 -3 目程度
- 150 手目時点の `score_lead` 中央値が -1 〜 +1 目程度（Phase 3 復帰準備）
- 終局 score が target_score 近傍に収束（既存 Jigo と同等）
- 安全弁発動率が < 30%（過剰条件が頻発しないこと）
- `mean_ptloss` の劣化が +1.0 目以内（既存 Jigo 比）

### 手動検証

1. KaTrain GUI で `jigo_deception` を ON にして AI 同士または人間 vs AI で対局
2. `[JigoStrategy] Deception:` ログで Phase 遷移を確認
3. 中盤 (80 手目付近) で UI 上の評価値が -1〜-3 目程度になるか
4. 終盤入り (150 手目付近) で target_score (+0.5) 方向に向かうか
5. 安全弁発動時のログ (`phase=phase3` への急遷移) を確認

## 実装順序（writing-plans 用メモ）

1. `_jigo_resolve_phase` + 定数テーブル 3 個を `katrain/core/ai.py` に追加
2. `JigoStrategy.generate_move()` に Phase 解決層を挿入（既存変数を eff_target/eff_target_max/eff_mode/eff_large_lead_delta に置換）
3. `tests/test_jigo_deception.py` で `_jigo_resolve_phase` のユニットテスト追加
4. `katrain/core/constants.py` の `AI_OPTION_VALUES[AI_JIGO]` に `"jigo_deception": "bool"` 追加
5. `katrain/config.json` のデフォルト追加
6. ユーザーローカル `C:\Users\iwaki\.katrain\config.json` 追加（メインセッション直接 Edit）
7. `.claude/rules/ai-parameters.md` 追記
8. CLI 検証で各 phase の挙動確認
9. batch_eval 校正（3-run 平均 × deception 2 値 × SGF 2〜3）
10. 校正結果を本 spec の付録に追記

## 校正結果（2026-05-16）

**実行条件**:
- SGF: `tests/data/panda1.sgf`（19 路、205 手の実戦譜、白勝 +37 目）
- `--player W`, `--strategy jigo`, `--batch`
- 3-run 平均（jigo は argmax のため戦略側決定的だが、KataGo 事後解析の非決定性で多少のばらつきあり）

### 全体メトリクス（baseline vs deception）

| 指標 | baseline 平均 | deception 平均 | 差分 | 評価 |
|---|---|---|---|---|
| ai_top_move | 32.4% | 29.7% | -2.6% | AI 一致率が意図通り低下 |
| ai_top5_move | 46.7% | 42.5% | -4.3% | 上位 5 手一致率も低下 |
| mean_ptloss | 1.24 | 1.30 | +0.05 目 | 劣化は KataGo run 間 stdev (0.04-0.05) 範囲内、許容範囲内 |
| accuracy | 69.9% | 68.9% | -1.0% | 微減、許容範囲内 |

### Phase 別メトリクス

| Phase | 指標 | baseline | deception | 差分 |
|---|---|---|---|---|
| opening | ai_top_move | 64.1% | 60.3% | -3.8% |
| opening | mean_ptloss | 0.18 | 0.22 | +0.04 |
| middle | ai_top_move | 21.9% | 19.8% | -2.1% |
| middle | mean_ptloss | 1.82 | 1.89 | +0.07 |
| endgame | ai_top_move | 19.4% | 16.7% | -2.8% |
| endgame | mean_ptloss | 0.48 | 0.48 | 0.00 |

### 内部 Phase 分布（deception runs、全 3 run で一致）

- phase0: 15 手（手数 1-29、定石期間）
- phase1: 11 手（手数 30-79、中盤入口で控えロジック適用）
- phase2: **0 手**（安全弁が phase3 にジャンプさせた）
- phase3: 77 手（手数 80 以降、panda1.sgf では既に白 +20 目以上で安全弁発動）

### 手選択の差分（run1、計 25 手 / 103 手で異なる選択）

| Phase | 差分手数 | 備考 |
|---|---|---|
| phase0 | 4 手 | ε バンド tiebreak の確率分散（既存機能） |
| phase1 | 6 手 | **Deception 機構の本来作用**: -3 目方向の手を選択 |
| phase3 | 15 手 | ε バンド tiebreak + 内部キャッシュ差（user 設定復帰中） |

### 校正所見

1. **Phase 解決層は決定論的に動作**: 3 run すべてで内部 phase 分布が完全一致（15/11/0/77）
2. **安全弁が設計通り発動**: panda1.sgf は白優勢ゲームのため Phase 2 入りすべき手数 80+ では実 lead +20 目超 → +4.5 目（target_max -0.5 + 安全弁 +5）を遥かに超え phase3 強制ジャンプ。Phase 2 がスキップされる挙動は spec 通り
3. **AI 一致率の低下 (-2.6%)** は Phase 1（11 手）と Phase 0/3 の ε バンド tiebreak からの寄与の合算
4. **mean_ptloss の劣化 +0.05 目** は KataGo run 間ノイズ範囲内、設計目標（+1.0 目以内）を大幅クリア

### 校正の限界

- panda1.sgf は実戦譜のため score_lead trajectory（手数 30/80/150 時点）は両条件で同一。spec の合格基準「30 手目時点の score_lead 中央値が 0 ~ -2 目程度」は **AI 同士の実対局でしか検証不可**（バッチ評価は手選択の評価のみ、対局再生は行わない）
- 弱い対戦相手（loss > 5.6 連発）を想定した到達性検証は本校正では未実施
- 真の「序中盤で -3 目劣勢を作る」挙動は GUI での AI vs AI 対局・人間 vs AI 対局ログで確認すること

## 参考

- 関連 spec: `docs/superpowers/specs/2026-04-12-jigo-humanlike-design.md`（JigoStrategy 本体）
- 関連 spec: `docs/superpowers/specs/2026-04-13-jigo-large-lead-max-loss-design.md`（圧勝時 max_loss 動的緩和）
- 関連 spec: `docs/superpowers/specs/2026-04-13-jigo-dynamic-rank-calibration-design.md`（動的 rank 降格）
- 関連 spec: `docs/superpowers/specs/2026-04-19-jigo-epsilon-tiebreak-design.md`（ε バンド tiebreak）
- CLAUDE.md の「やってはいけないこと」: ユーザーローカル config の編集は必ずメインセッション、`.claude/rules/` 編集はサブエージェント経由
- `.claude/rules/ai-parameters.md`: JigoStrategy パラメータ一覧（更新対象）
- `.claude/rules/ai-settings-gui.md`: AI 設定 GUI 追加手順
