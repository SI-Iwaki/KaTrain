# JigoStrategy: 圧勝時の `max_loss_per_move` 動的緩和（最小介入案）

- **作成日**: 2026-04-13
- **対象戦略**: `JigoStrategy` (`katrain/core/ai.py` `_jigo_filter_candidates` 周辺)
- **関連 spec**: `2026-04-12-jigo-humanlike-design.md`, `2026-04-13-jigo-weak-opponent-design.md`, `2026-04-13-jigo-dynamic-rank-calibration-design.md`

## 背景

現状の `JigoStrategy` は `loss ≤ max_loss_per_move (5.6目) AND hp ≥ min_human_policy (0.02)` で候補をフィルタする。`current_lead > target_score_max (10目)` のとき `_jigo_select_move` は `argmin |score - target_score|` で「最も target に近い手」を選ぶが、寄せる方向の手の loss が 5.6 を超えると除外され、結果として「target に寄せたい局面で寄せる手が候補に残らない」デッドロックが起きる。実戦の `--batch` 観察でも、相手が弱く lead が拡大した試合では target 範囲 (0.5〜10目) に収束しないまま終局するケースが頻繁に発生している。

`ai-parameters.md` の Jigo セクションには「相手の棋力が持碁モード（humanSL 9段相当）と釣り合うときのみ目差収束を期待する設計」と現状の限界が明記されている。本 spec はこの限界を「人間らしさを毀損しない範囲で」少しだけ緩和することを目的とする。

## 目的 / 非目的

### 目的

- `current_lead` が target_score_max を大きく超えた局面でのみ `max_loss_per_move` を一時的に緩め、target に寄せる方向の中 loss 手を候補プールに含める
- 既存の選択ロジック（natural=hp 重み / maintain=argmin / 範囲外=argmin）を**一切変更しない**
- 既存の鋭手除外（`_jigo_exclude_sharp_moves`）を**一切変更しない**ため、lead 拡大方向の手は常に除外される（緩和の効果は寄せ方向のみ）

### 非目的

- argmax loss 等の deterministic 選択の導入（人間らしさ毀損の懸念で却下済み）
- humanPolicy 重みの数式変更
- target_score の動的シフト（代替案として検討したが採用せず）
- 弱相手検知ロジックの追加（lead 値だけで判定）

## アルゴリズム

### 発動条件

```
current_lead ≥ target_score_max + jigo_large_lead_delta
```

- `target_score_max` を相対基準にすることで、ユーザーが `target_score_max` を変更しても整合
- `current_lead` は Stage 2 の `rootInfo.scoreLead × player_sign`（既存実装と同じ取得方法）

### 動作

発動時のみ `max_loss_per_move` の値を `jigo_large_lead_max_loss` で置換し、`_jigo_filter_candidates` および `_jigo_relax_filters` に渡す `max_loss` 引数を effective 値とする。発動しない場合は現行の `max_loss_per_move` をそのまま使う。

### 選択ロジック

完全に現行維持。`_jigo_filter_candidates` のフィルタ閾値が変わるだけで、`_jigo_select_move`・`_jigo_exclude_sharp_moves`・`_jigo_relax_filters` の挙動は変えない。

### 期待効果

- `current_lead - effective_max_loss ≤ target_score_max` を満たす程度に target に寄せる手が hp 重み選択の対象になる
- 鋭手除外で lead 拡大手は依然候補外
- humanPolicy 重み付けで「9段らしくない無理筋手」の選択確率は低いまま

### 制御フロー変更点（実装メモ）

現行 `JigoStrategy.generate_move()` では `current_lead` を `_jigo_filter_candidates` 呼び出し後（line 991 付近）に算出している。新ロジックはフィルタ前に `current_lead` が必要なため、`score_analysis` 確定直後（line 922-930 付近）に前倒しする。

## パラメータ仕様

| キー | 型 | デフォルト (19路/13路) | デフォルト (9路) | GUI 表示 | 備考 |
|---|---|---|---|---|---|
| `jigo_large_lead_delta` | float | 5.0 | 5.0 | 「圧勝発動目数差」 | 全盤面共通 |
| `jigo_large_lead_max_loss` | float | 8.0 | 5.0 | 「圧勝時の許容損失」 | 9路は内部キャップ |

### 9路盤の扱い

`max_loss_per_move` のデフォルト (5.6) と異なり、9路の HumanStyle NORMAL_THRESHOLD は 3.3。新パラメータも 9路は控えめにする。GUI には単一の値を表示し、`_jigo_filter_candidates` 呼び出し時に board_size に応じて min クランプする：

```python
effective_large_lead_max_loss = jigo_large_lead_max_loss
if board_size <= 9:
    effective_large_lead_max_loss = min(jigo_large_lead_max_loss, 5.0)
```

GUI 値は単一に保ち、内部実装で 9路上限を強制する。具体実装は writing-plans 段階で決定。

### 既存戦略パラメータとの相互作用

- `jigo_dynamic_rank` (opt-in): 完全独立。両方発動可能（rank 降格 + max_loss 緩和の併用は理にかなう）
- `target_score`, `target_score_max`: 既存通り使用。新ロジックは `target_score_max` のみ参照
- `min_human_policy`: 変更なし。発動時も同じ hp 閾値が適用される

## エッジケース

1. **Stage 2 失敗時**: `score_lead_biased=true` のフラグが立った場合でも、新ロジックは発動する。Stage 1 の biased な scoreLead を `current_lead` として使うため、発動判定も誤差を含むが、既存実装の bias 問題と同質で新規副作用なし
2. **段階緩和フォールバック (`_jigo_relax_filters`)**: 新ロジック発動時は effective max_loss を起点に段階緩和が走る。実質より広い候補プールから緩和開始するため、`safety_valve` 到達確率が下がる（改善方向）
3. **鋭手除外との発動順序**: 新ロジック発動時 (`current_lead ≥ target_score_max + 5`) は必ず鋭手除外条件 (`current_lead > target_score_max`) も満たすため、鋭手除外は常にセットで動作する。lead 拡大方向の手は引き続き除外
4. **target_score_max 変更時**: 例えばユーザーが `target_score_max=5.0` に下げた場合、新発動条件は `current_lead ≥ 10.0`。相対値設計のため自然に追随
5. **`current_lead` 計算の前倒し**: 既存ロジックの並びに依存している箇所がないか確認（line 991 以前で `current_lead` を参照していないことを確認済み）

## ファイル変更

| ファイル | 変更内容 |
|---|---|
| `katrain/core/ai.py` | `JigoStrategy.generate_move()`: `current_lead` 計算前倒し、effective max_loss 算出ロジック追加、debug log 追加 |
| `katrain/core/constants.py` | `AI_OPTION_VALUES["jigo"]` に 2 キー追加 |
| `katrain/config.json` | パッケージ同梱デフォルトに 2 キー追加 |
| `C:\Users\iwaki\.katrain\config.json` | **メインセッションで直接 Edit** — ユーザーローカル設定に 2 キー追加 |
| `katrain/i18n/locales/*/LC_MESSAGES/katrain.po` | 「圧勝発動目数差」「圧勝時の許容損失」の翻訳追加。`python tools/compile_mo.py` で `.mo` 再コンパイル |
| `.claude/rules/ai-parameters.md` | Jigo パラメータ表に 2 行追加（**サブエージェント経由で編集・コミット**） |

## 検証

### 1. 既存 batch_eval で回帰確認

`docs/superpowers/specs/calibration-data/` 配下の Jigo 校正 SGF を `--strategy jigo --batch` で 3-run 評価。Jigo Metrics ブロック（target 範囲到達率・終局時 lead 等）を変更前後で比較。

### 2. パラメータグリッド検証

`jigo_large_lead_max_loss` を 6.0 / 8.0 / 10.0 で 3-run 比較し、以下の指標を集計：

- target 範囲（0.5〜10目）到達率
- 終局時 lead の平均と分散
- 「sharp 手」「無理筋手」発生率（`Notable Divergences` セクションの loss > 6.0 の hp と頻度）
- humanlike 性の主観評価（特定手数の手をスポット確認）

結果は `docs/superpowers/specs/calibration-data/jigo-large-lead-max-loss-results-YYYYMMDD.md` に記録する。

### 3. 個別局面確認

圧勝局面の SGF を選び `python -m katrain_debug --sgf FILE --move N --strategy jigo --output text` で発動ログ（新規追加する `[JigoStrategy] Large lead expansion: ...`）を確認。

### 4. 既存テスト

`tests/test_jigo.py` に新規ヘルパ関数のユニットテストを追加（effective max_loss 算出ロジック、9路キャップ、target_score_max 変更時の発動閾値追随）。pure function として実装し、KataGo 起動なしでテスト可能にする。

## デバッグログ仕様

新規追加する debug ログ（`OUTPUT_DEBUG`）：

```
[JigoStrategy] Large lead expansion: lead={current_lead:.2f} ≥ target_max+{delta} = {threshold}, max_loss: {base} → {effective}
```

発動しなかった場合のログ追加は不要（既存 `Filter: N → M passed` ログで挙動は把握可能）。

## ロールバック計画

`jigo_large_lead_delta` または `jigo_large_lead_max_loss` をユーザー設定で大きな値（例: `delta=999`）にすれば実質的に発動しなくなる。コード上のフラグは追加しない（YAGNI）。問題発生時は GUI から無効化可能。

## 受け入れ条件

- [ ] 既存 batch_eval で「現行通り」の局面（`current_lead < target_score_max + 5`）の選択結果が変わらない
- [ ] 圧勝局面の SGF で `Large lead expansion` ログが期待通り発火する
- [ ] パラメータグリッド (6.0/8.0/10.0) の 3-run 結果で 8.0 が他値と比べて極端な悪化を示さない
- [ ] 9路盤での発動時に effective max_loss が 5.0 以下にクランプされる
- [ ] 新規ユニットテストが pass する
- [ ] `.claude/rules/ai-parameters.md` の Jigo パラメータ表に 2 行追加されている
