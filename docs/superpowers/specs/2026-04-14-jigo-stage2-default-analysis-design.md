# Jigo Stage 2 既定解析置換 設計書（案C）

## 概要

`JigoStrategy.generate_move()` の Stage 2（クリーン scoreLead クエリ, 600 visits）を、既定解析 (`self.cn.analysis`) で置換し、1手あたりのクエリを 1本に削減する。

- **動機**: 案A（Stage 1 maxVisits=1）適用後も残る Stage 2 600 visits を省略し、特に **13路で追加の応答時間短縮**を狙う
- **前提**: 案A 適用済（コミット `024e4b1`、`docs/superpowers/specs/2026-04-14-jigo-response-speedup-design.md`）
- **方針**: コード変更のみ（数行）、設定ファイル変更なし

## 背景

案A 適用後の現状フロー（案A 後）:

1. `wait_for_analysis()` で `self.cn.analysis_complete=True` を待機（既定解析 800 visits, wideRootNoise=0.04 が完了）
2. **Stage 1**: humanSL 9段, maxVisits=1 → `humanPolicy` 取得
3. **Stage 2**: クリーン (wideRootNoise=0.0) 600 visits → `moveInfos`, `scoreLead` 取得
4. フィルタ・選択

案C はステップ 3 を省略し、ステップ 1 で既に取得済みの `cn.analysis` を流用する。

## 設計

### 1. コード変更（`katrain/core/ai.py` `JigoStrategy.generate_move()`）

**削除**:
- `stage2_override = {...}`
- `engine.request_analysis(..., extra_settings=stage2_override)` 呼び出し
- `_set_stage2`, `_err_stage2` コールバック関数
- `while not (stage2_error or stage2_analysis): time.sleep(0.01); engine.check_alive(...)`
- Stage 2 失敗判定 `if stage2_error or not stage2_analysis: ...` ブロック

**追加**（Stage 2 ブロック全体の置換）:
```python
# Stage 2 を既定解析 (cn.analysis) で置換 — 案C
# wait_for_analysis() で analysis_complete=True 保証済
move_dicts = list(self.cn.analysis.get("moves", {}).values())
root_info = self.cn.analysis.get("root")
if move_dicts and root_info:
    score_analysis = {
        "moveInfos": move_dicts,
        "rootInfo": root_info,
    }
else:
    self.last_decision_info["score_lead_biased"] = True
    self.game.katrain.log(
        "[JigoStrategy] cn.analysis incomplete, using Stage1 (biased)", OUTPUT_DEBUG
    )
    score_analysis = stage1_analysis
```

**変更不要**:
- 後続 `move_infos = score_analysis.get("moveInfos", [])` 以降は構造互換
- `score_analysis.get("rootInfo", {}).get("scoreLead", 0)` も互換
- フィルタ・選択ロジックは完全に既存のまま

### 2. データ構造の互換性

| アクセス | 案A 後 (Stage 2) | 案C (cn.analysis) |
|---|---|---|
| `score_analysis["moveInfos"]` | KataGo response から直接 | `list(self.cn.analysis["moves"].values())` |
| `score_analysis["rootInfo"]["scoreLead"]` | KataGo response の `rootInfo` | `self.cn.analysis["root"]` (= `rootInfo` がそのまま代入: `game_node.py:256`) |
| 各 moveInfo の `move`, `scoreLead` | KataGo 出力 | 同左（`set_analysis` で `update_move_analysis` が moveInfos を保存） |

JigoStrategy が必要とするフィールドは `move` と `scoreLead` のみ。両方 cn.analysis に含まれる。`pointsLost` は KaTrain 計算値で JigoStrategy は使わない。

### 3. visits と wideRootNoise の trade-off

| 軸 | 案A 後 (Stage 2) | 案C (cn.analysis) | 影響 |
|---|---|---|---|
| visits | 600 | 800 (ユーザー `max_visits` 設定) | +33% → scoreLead refinement わずかに改善 |
| wideRootNoise | 0.0 (クリーン) | 0.04 | 探索が広がり scoreLead に小さな揺らぎ（理論 ±0.1〜0.3 目程度） |
| ignorePreRootHistory | False | 未指定（KataGo 既定 False） | 実質同じ |

正味の精度変化は実測必須。visits 増加が wideRootNoise の影響を部分的に相殺する見込み。

### 4. リスクと精度評価

**主要リスク**: `scoreLead` の wideRootNoise=0.04 由来の noise が JigoStrategy の判定に影響。

| 判定処理 | scoreLead 精度依存度 | 影響見込み |
|---|---|---|
| 大悪手フィルタ (`loss <= max_loss_per_move=5.6`) | 低（鈍感） | ほぼ無し |
| 鋭手除外 (`score > current_lead + 0.5`, 圧勝時のみ) | **高（0.5目精度依存）** | **要計測** |
| large_lead expansion (`current_lead >= target_score_max + delta`) | 中（delta=5〜10目） | ほぼ無し |
| natural モード in-range humanPolicy 選択 | 低（loss フィルタ依存のみ） | ほぼ無し |

**フォールバック発生時の挙動**: `cn.analysis` の moves/root が想定外に欠落した場合、Stage 1 (biased) にフォールバック。これは案A の Stage 2 失敗時と同じ挙動。`last_decision_info["score_lead_biased"]=True` でログから検知可能。

### 5. パッケージ既定 max_visits=500 の懸念

パッケージ同梱 `katrain/config.json` の `max_visits=500` < 現行 Stage 2 (600)。GUI で設定を変更していないユーザー環境では既定解析 visits が 500 になり、Stage 2 (600) より精度低下する可能性。

**対処**: 今回スコープ外。校正は GUI 設定済（800）の前提で実施。500 visits 環境での退行が問題化したら、別タスクでパッケージ既定値の引き上げを検討。

### 6. 想定効果

| 盤面 | 案A 後の体感 | 案C 追加効果見込み |
|---|---|---|
| 19路 | 案A で 0.5 秒短縮達成 | 追加 0.2〜0.4 秒短縮（Stage 2 600 visits 分） |
| 13路 | 案A 体感差わずか | **明確な短縮**（13路の Stage 2 600 visits は短いが体感差出る見込み） |

### 7. 検証計画

#### 7.1 校正対象 SGF（前処理: `clean_sgf_main_line.py` で main line 化）

| 盤面 | SGF | 評価色 | 想定手数 |
|---|---|---|---|
| 19路 | `jigo-vs-3dan-20260413-white.sgf`（既存） | W | ~60 |
| 19路 | `jigo-vs-3dan-20260413-black.sgf`（既存） | B | ~134 |
| 13路 | `KaTrain_人間 (通常対局) vs AI (力戦派) 2026-04-01 02 17 40.sgf` | B | ~46 |
| 13路 | `KaTrain_人間 (通常対局) vs AI (力戦派) 2026-04-01 19 08 44.sgf` | W | ~43 |

13路の SGF は KaTrainログ由来（`C:\Users\iwaki\Documents\KaTrainログ\`）。Jigo 専用の対局ではないが、`batch_eval` は各局面で JigoStrategy をシミュレートするため SGF の対局者は無関係。むしろ score 差が大きい局面が多く、案C の主リスク（鋭手除外への noise 影響）を検出しやすい。

#### 7.2 計測コマンド

```bash
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --player <B|W>
```

各 SGF × 3run を実行（`--batch` は決定的に近いが、KataGo 並列探索の非決定性で stdev ~0.03〜0.05 発生）。

#### 7.3 Before / After

- **Before（案A適用済の現行, コミット `024e4b1`）**
  - 19路: `jigo-speedup-results-20260414.md` の "after" 列を流用可能
  - 13路: 新規取得（案C 適用前のコミットで実施）
- **After（案C 適用後）**: 全4 SGF の3run 取得

#### 7.4 パス基準（プラン A と同じ閾値）

| メトリック | 合格範囲 |
|---|---|
| `ai_top_move` (Top1) | ±0.02 |
| `ai_top5_move` (Top5) | ±0.02 |
| `mean_ptloss` | ±0.1 目 |
| `cvm_gap` | ±0.1 目（2σ 以内なら統計的非有意として受容） |
| `slack_delta_*` | 情報のみ |

**統計的補正**: 単一指標が閾値を外れても、3run stdev から算出した σ で 2σ 以内なら統計的非有意として受容（プラン A の cvm_gap 白判定と整合）。

#### 7.5 フォールバック発生率

新規実行 18 run（19路 after 6 + 13路 before 6 + 13路 after 6）のログから `[JigoStrategy] cn.analysis incomplete` の発生数をカウント。通常はゼロ想定。発生していれば追加調査が必要。19路 before は既存データ流用のため再取得しない。

#### 7.6 速度実測（実対局・ユーザー計測）

19路・13路でそれぞれ 5-10 手サンプリングし体感応答時間を記録。

#### 7.7 校正データ保存先

```
docs/superpowers/specs/calibration-data/jigo-speedup/
  jigo-speedup-planC-results-20260414.md  ← 結果サマリ
  planC-13ro-before-run1/, planC-13ro-before-run2/, planC-13ro-before-run3/  ← 13路 before --batch JSON (2 SGF × 3 run)
  planC-after-run1/, planC-after-run2/, planC-after-run3/                    ← 全4 SGF after --batch JSON
```

19路 before は既存 `jigo-speedup-results-20260414.md` の "after" データ（同コミット `024e4b1`）を流用するため新規取得不要。

13路 SGF の前処理（`KaTrainログ` から `calibration-data/jigo-speedup/` にコピーして main-line 化）も校正タスクに含む。

### 8. ロールバック

`git revert <案C コミット>` で Stage 2 ブロックが復活。**設定ファイル変更なし**（コードのみ）のためロールバックは安全。

## コーディング規約準拠

- コミットメッセージ: 日本語 Conventional Commits（`perf(jigo): ...` または `refactor(jigo): ...`）
- フォーマット: `black katrain/`（line-length 120）
- 関連ドキュメント更新:
  - `.claude/rules/ai-parameters.md` の「エンジン設定（maxVisits）」テーブル — Jigo の Stage 2 行を削除/更新
  - `CLAUDE.md` の「KataGo 解析結果の扱い」セクションに、Jigo が `cn.analysis` を直接消費する旨を追記（必要に応じて）

## 変更影響範囲

- 単一ファイル変更（`katrain/core/ai.py` の `JigoStrategy.generate_move()` 内）
- 削除 ~30 行、追加 ~10 行
- GUI 変更なし、設定ファイル変更なし、i18n 変更なし
- 他ストラテジ（HumanStyle, Fighting, Siege, Hunt 等）への影響なし — 各々が独自の Stage 2 を保持
