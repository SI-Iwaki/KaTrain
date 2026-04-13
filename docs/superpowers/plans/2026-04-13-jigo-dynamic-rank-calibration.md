# JigoStrategy 動的 rank 閾値校正 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `JigoStrategy.jigo_dynamic_rank=True` の降格閾値（現行 `delta > 5` → rank_7d、`delta > 15` → rank_5d）を弱相手対局データで校正し、人間らしさを劣化させずに lead 収束傾向を改善する値に確定する。

**Architecture:** (1) `_select_rank_by_lead` の閾値を関数引数化し `jigo_rank_delta_1/2` 設定キーから注入可能にする。(2) `JigoStrategy` が選択情報を `last_decision_info` に露出し、(3) `batch_eval.py` がそれを収集して Jigo 専用指標（lead 推移・humanPolicy・rank 降格カウント等）を集計する。(4) 5 config × 3 run のバッチ評価結果から、gate（人間らしさ維持）+ convergence_score で最良閾値を選ぶ。

**Tech Stack:** Python 3.12、pytest、KataGo TensorRT v1.16.4（既存）、`katrain_debug` バッチ評価ツール（既存）

**関連文書:**
- 設計書: `docs/superpowers/specs/2026-04-13-jigo-dynamic-rank-calibration-design.md`
- 前提 spec: `docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md`
- 対象メモリ: `memory/project_jigo_dynamic_rank_calibration.md`
- 分散ルール: `memory/feedback_batch_eval_variance.md`

---

## Task 1: テスト SGF を校正データフォルダにリネームコピー

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf`
- Source (不変): `sgfout/KaTrain_人間 (通常対局) vs AI (Kata持碁) 2026-04-13 11 43 30.sgf`

- [ ] **Step 1: ディレクトリ作成**

```bash
mkdir -p docs/superpowers/specs/calibration-data/runs
```

- [ ] **Step 2: SGF コピー（空白・日本語パス回避）**

```bash
cp "sgfout/KaTrain_人間 (通常対局) vs AI (Kata持碁) 2026-04-13 11 43 30.sgf" \
   "docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf"
```

- [ ] **Step 3: コピー結果を検証**

```bash
ls -la docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf
```

期待出力: ファイルが 14501 bytes 前後で存在

- [ ] **Step 4: .gitignore に runs/ を追加（JSON 結果ファイルをコミット対象外に）**

`docs/superpowers/specs/calibration-data/.gitignore` を新規作成:

```
runs/
```

- [ ] **Step 5: コミット**

```bash
git add docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf \
        docs/superpowers/specs/calibration-data/.gitignore
git commit -m "$(cat <<'EOF'
chore: Jigo 校正用テスト SGF を calibration-data に配置

3段 vs AI Jigo 白番の弱相手対局 SGF（120 手で黒投了、最終 lead +33）を
docs/superpowers/specs/calibration-data/ にリネームコピー。
runs/ はバッチ評価 JSON を置く作業フォルダのため gitignore。
EOF
)"
```

---

## Task 2: `_select_rank_by_lead` に delta_1 / delta_2 引数を追加

**Files:**
- Modify: `katrain/core/ai.py:746-765`
- Test: `tests/test_jigo.py:204-238`（既存テストに追加）

- [ ] **Step 1: 新しいテストケースを書く（失敗するべき）**

`tests/test_jigo.py` の `TestSelectRankByLead` クラスの末尾に追加:

```python
    def test_custom_delta_1_controls_one_step_downshift(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta_1=3 に設定すると、delta=4 で1段下
        assert _select_rank_by_lead(14.0, 10.0, "rank_9d", delta_1=3, delta_2=15) == "rank_7d"
        # delta=3 なら降格なし（delta > delta_1 の判定）
        assert _select_rank_by_lead(13.0, 10.0, "rank_9d", delta_1=3, delta_2=15) == "rank_9d"

    def test_custom_delta_2_controls_floor_downshift(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta_2=10 に設定すると、delta=11 で一気に rank_5d
        assert _select_rank_by_lead(21.0, 10.0, "rank_9d", delta_1=5, delta_2=10) == "rank_5d"
        # delta=10 なら 1段下（delta > delta_2 の判定）
        assert _select_rank_by_lead(20.0, 10.0, "rank_9d", delta_1=5, delta_2=10) == "rank_7d"

    def test_defaults_match_legacy_behavior(self):
        from katrain.core.ai import _select_rank_by_lead
        # 引数省略時は現行の 5 / 15 が使われる（後方互換）
        assert _select_rank_by_lead(16.0, 10.0, "rank_9d") == "rank_7d"   # delta=6 → 1段下
        assert _select_rank_by_lead(26.0, 10.0, "rank_9d") == "rank_5d"   # delta=16 → rank_5d
```

- [ ] **Step 2: テストを実行して失敗することを確認**

```bash
pytest tests/test_jigo.py::TestSelectRankByLead -v
```

期待出力: 新規 3 テストが TypeError（`_select_rank_by_lead() got an unexpected keyword argument 'delta_1'`）で失敗

- [ ] **Step 3: `_select_rank_by_lead` を書き換える**

`katrain/core/ai.py` の該当関数全体を置換:

```python
def _select_rank_by_lead(current_lead, target_score_max, base_profile,
                          delta_1=5, delta_2=15):
    """リードが target_max を超えた度合いに応じて humanSL rank を降格する。

    - delta ≤ delta_1           : base_profile そのまま
    - delta_1 < delta ≤ delta_2 : base_profile より 1段下（9d→7d, 7d→5d, 5d→5d）
    - delta > delta_2           : 一気に rank_5d まで下げる

    base_profile が _JIGO_RANK_CHAIN に含まれない場合はそのまま返す。
    delta_1 / delta_2 は校正実験で調整可能（デフォルトは校正前の初期値）。
    """
    if base_profile not in _JIGO_RANK_CHAIN:
        return base_profile
    delta = current_lead - target_score_max
    idx = _JIGO_RANK_CHAIN.index(base_profile)
    if delta > delta_2:
        new_idx = 0  # rank_5d 固定
    elif delta > delta_1:
        new_idx = max(0, idx - 1)
    else:
        new_idx = idx
    return _JIGO_RANK_CHAIN[new_idx]
```

- [ ] **Step 4: テスト全体を実行して既存 + 新規すべてパスすることを確認**

```bash
pytest tests/test_jigo.py::TestSelectRankByLead -v
```

期待出力: 既存 7 テスト + 新規 3 テストすべて PASS

- [ ] **Step 5: `JigoStrategy.generate_move` 内の呼び出しに設定キーを渡す**

`katrain/core/ai.py` の `generate_move` メソッド内、L820-L824 の `_select_rank_by_lead` 呼び出しブロックを置換:

```python
        # ---- Stage 1 用 humanSL rank 決定 ----
        # キャッシュは self.game に保存（strategy インスタンスは毎手破棄されるため）
        last_lead = getattr(self.game, "_jigo_last_current_lead", None)
        if dynamic_rank and last_lead is not None:
            delta_1 = self.settings.get("jigo_rank_delta_1", 5)
            delta_2 = self.settings.get("jigo_rank_delta_2", 15)
            human_profile = _select_rank_by_lead(
                last_lead, target_score_max, base_profile,
                delta_1=delta_1, delta_2=delta_2,
            )
            if human_profile != base_profile:
                self.game.katrain.log(
                    f"[JigoStrategy] Dynamic rank: base={base_profile}, "
                    f"last_lead={last_lead:.2f}, "
                    f"delta={last_lead - target_score_max:.2f} → {human_profile} "
                    f"(delta_1={delta_1}, delta_2={delta_2})",
                    OUTPUT_DEBUG,
                )
        else:
            human_profile = base_profile
```

- [ ] **Step 6: 回帰確認（全 Jigo テスト）**

```bash
pytest tests/test_jigo.py -v
```

期待出力: 全 PASS

- [ ] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo.py
git commit -m "$(cat <<'EOF'
feat: _select_rank_by_lead の閾値を delta_1/delta_2 引数化

動的 rank 校正実験のため、閾値を jigo_rank_delta_1 / jigo_rank_delta_2
設定キーから上書き可能にする。デフォルト値は現行の 5 / 15 を維持。
GUI 非露出（校正完了後に関数デフォルトに採用値を反映する想定）。
EOF
)"
```

---

## Task 3: `JigoStrategy.last_decision_info` を露出

**Files:**
- Modify: `katrain/core/ai.py:796-1009`（`JigoStrategy.generate_move`）

**背景:** `batch_eval.py` が Jigo 専用指標を集計するために、戦略実行ごとに選択情報（rank_used, selected_hp, selected_score, filter_relaxed, score_lead）を instance attribute として露出する必要がある。既存の戻り値 `(Move, str)` は維持（後方互換）。

本タスクはエンジン統合部分のため TDD 不可（KataGo 必須）。実装後の動作確認は Task 7 の dry-run で実施する。

- [ ] **Step 1: `__init__` で `last_decision_info` を初期化**

`JigoStrategy` クラスに `__init__` はないため、戦略実行時に初期化するのが自然。代わりに `generate_move` の先頭で初期化する。

`katrain/core/ai.py` の `JigoStrategy.generate_move` の先頭（`import time` の次の行）に追加:

```python
    def generate_move(self) -> Tuple[Move, str]:
        import time
        self.last_decision_info = {
            "rank_used": None,
            "selected_hp": None,
            "selected_score": None,
            "filter_relaxed": False,
            "score_lead": None,
        }
        self.game.katrain.log(f"[JigoStrategy] Starting move generation", OUTPUT_DEBUG)
```

- [ ] **Step 2: Stage1 失敗時の early return でも `last_decision_info` を保持**

Stage1 失敗のブロック（現行 L861-869）は既定値のまま返るので変更不要。`rank_used` だけは Stage1 試行時点の `human_profile` を記録したい：L860 の直前（`if stage1_error or not stage1_analysis or "humanPolicy" not in stage1_analysis:` の前）で instance attribute に記録しておくのが安全。

現行コード（L818-L869 付近）を確認し、`stage1_override = {"humanSLProfile": human_profile, ...}` の直後に以下を追加:

```python
        self.last_decision_info["rank_used"] = human_profile
```

- [ ] **Step 3: フォールバック段階緩和が起きたら `filter_relaxed=True` を記録**

現行 L959-L969 の「フォールバック段階緩和」ブロックを置換:

```python
        # ---- フォールバック段階緩和 ----
        if not filtered:
            filtered, reason = _jigo_relax_filters(candidates, max_loss, min_hp)
            self.last_decision_info["filter_relaxed"] = True
            self.game.katrain.log(
                f"[JigoStrategy] Fallback triggered: reason={reason}, {len(filtered)} candidates",
                OUTPUT_DEBUG
            )
            if reason == "safety_valve":
                self.game.katrain.log(
                    "[JigoStrategy] Safety valve: using KataGo top move", OUTPUT_ERROR
                )
```

- [ ] **Step 4: 選択確定直後に残りのフィールドを記録**

現行 L1000-L1008 の「結果」ブロック（`self.game.katrain.log(f"[JigoStrategy] Selected: ..."...)` の直後、`self.game._jigo_last_current_lead = current_lead` の直前）に追加:

```python
        # ---- 選択情報を batch_eval から参照できるよう露出 ----
        self.last_decision_info.update({
            "selected_hp": pick["hp"],
            "selected_score": pick["score"],
            "score_lead": current_lead,
        })
```

- [ ] **Step 5: ai.py の構文エラーがないことを確認**

```bash
python -c "from katrain.core import ai"
```

期待出力: エラーなし

- [ ] **Step 6: 既存 Jigo テストを実行して回帰がないことを確認**

```bash
pytest tests/test_jigo.py -v
```

期待出力: 全 PASS（純粋関数テストなのでエンジン不要、last_decision_info 追加で壊れないこと）

- [ ] **Step 7: コミット**

```bash
git add katrain/core/ai.py
git commit -m "$(cat <<'EOF'
feat: JigoStrategy.generate_move で last_decision_info を露出

batch_eval から選択情報（rank_used, selected_hp, selected_score,
filter_relaxed, score_lead）を参照できるよう instance attribute に記録。
既存の戻り値 (Move, str) は維持（後方互換）。Stage1 失敗時は既定値で返る。
EOF
)"
```

---

## Task 4: `batch_eval.py` に Jigo 専用データ収集を追加

**Files:**
- Modify: `katrain_debug/batch_eval.py:144-155`（move_results 構築部）

**背景:** 戦略実行後に `strategy.last_decision_info` を読み取り、`move_results` の各要素に Jigo 固有フィールドを格納する。

- [ ] **Step 1: `batch_eval.py` の `move_results.append` ブロックを拡張**

`katrain_debug/batch_eval.py` の L144-155（`move_results.append({...})` 部分）を置換:

```python
            # Jigo 固有情報（他戦略では None）
            jigo_info = getattr(strategy, "last_decision_info", None)

            move_results.append({
                "move_num": move_num,
                "player": player,
                "phase": phase,
                "ai_top": ai_top_move,
                "selected": selected_gtp,
                "actual": actual_move.gtp() if actual_move else None,
                "match_top": selected_gtp == ai_top_move,
                "match_approved": selected_gtp in ai_approved,
                "point_loss": point_loss,
                "explanation": explanation.split("\n")[0] if explanation else "",
                "rank_used": jigo_info.get("rank_used") if jigo_info else None,
                "selected_hp": jigo_info.get("selected_hp") if jigo_info else None,
                "selected_score": jigo_info.get("selected_score") if jigo_info else None,
                "filter_relaxed": jigo_info.get("filter_relaxed") if jigo_info else None,
                "score_lead": jigo_info.get("score_lead") if jigo_info else None,
            })
```

- [ ] **Step 2: 構文チェック**

```bash
python -c "from katrain_debug import batch_eval"
```

期待出力: エラーなし

- [ ] **Step 3: コミット**

```bash
git add katrain_debug/batch_eval.py
git commit -m "$(cat <<'EOF'
feat(debug): batch_eval に Jigo 固有フィールドを収集

strategy.last_decision_info から rank_used / selected_hp / selected_score
/ filter_relaxed / score_lead を move_results に格納。他戦略では全て None。
後続の集計ステップでこれらを Jigo 専用指標に集約する。
EOF
)"
```

---

## Task 5: `batch_eval.py` に Jigo 集計関数を追加

**Files:**
- Modify: `katrain_debug/batch_eval.py:160-170`（batch_evaluate 戻り値）
- Modify: `katrain_debug/batch_eval.py:176-217`（_aggregate_stats、末尾に新関数追加）
- Test: `tests/test_batch_eval_jigo.py`（新規）

**背景:** 戦略名が `jigo` の場合のみ、`stats` 辞書に `jigo_metrics` キーを追加する。純粋関数として `_aggregate_jigo_metrics(move_results, target_score, target_score_max)` を切り出してユニットテスト可能にする。

- [ ] **Step 1: ユニットテストを書く（失敗するべき）**

`tests/test_batch_eval_jigo.py` を新規作成:

```python
# tests/test_batch_eval_jigo.py
"""batch_eval の Jigo 集計関数のユニットテスト。"""
import pytest

from katrain_debug.batch_eval import _aggregate_jigo_metrics


def _m(score_lead=None, selected_hp=None, rank_used=None, filter_relaxed=False):
    """Minimal move_result shorthand."""
    return {
        "score_lead": score_lead,
        "selected_hp": selected_hp,
        "rank_used": rank_used,
        "filter_relaxed": filter_relaxed,
    }


class TestAggregateJigoMetrics:
    def test_empty_input_returns_empty_dict(self):
        result = _aggregate_jigo_metrics([], target_score=0.5, target_score_max=10.0)
        assert result == {}

    def test_ignores_moves_with_none_score_lead(self):
        # 非 Jigo 戦略で埋められた行（score_lead=None）は集計から除外
        moves = [_m(score_lead=None), _m(score_lead=5.0, selected_hp=0.3)]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["count"] == 1
        assert result["mean_lead"] == 5.0

    def test_mean_and_max_lead(self):
        moves = [
            _m(score_lead=2.0, selected_hp=0.5),
            _m(score_lead=8.0, selected_hp=0.3),
            _m(score_lead=14.0, selected_hp=0.2),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["mean_lead"] == pytest.approx(8.0)
        assert result["max_lead"] == 14.0

    def test_in_target_and_over_target_ratios(self):
        # target=0.5, target_max=10.0
        # in_target: 0.5 <= lead <= 10.0 → [2.0, 8.0] が該当 (2/3)
        # over_target: lead > 10.0 → [14.0] が該当 (1/3)
        moves = [
            _m(score_lead=2.0, selected_hp=0.5),
            _m(score_lead=8.0, selected_hp=0.3),
            _m(score_lead=14.0, selected_hp=0.2),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["in_target_ratio"] == pytest.approx(2 / 3)
        assert result["over_target_ratio"] == pytest.approx(1 / 3)

    def test_mean_and_p10_selected_hp(self):
        # hp: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        # mean = 0.55, p10（下位10%値）= 0.1
        moves = [_m(score_lead=5.0, selected_hp=hp / 10) for hp in range(1, 11)]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["mean_selected_hp"] == pytest.approx(0.55)
        assert result["p10_selected_hp"] == pytest.approx(0.1, abs=0.01)

    def test_filter_relax_rate(self):
        moves = [
            _m(score_lead=5.0, selected_hp=0.3, filter_relaxed=True),
            _m(score_lead=5.0, selected_hp=0.3, filter_relaxed=False),
            _m(score_lead=5.0, selected_hp=0.3, filter_relaxed=False),
            _m(score_lead=5.0, selected_hp=0.3, filter_relaxed=True),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["filter_relax_rate"] == pytest.approx(0.5)

    def test_rank_downgrade_counts(self):
        moves = [
            _m(score_lead=5.0, selected_hp=0.3, rank_used="rank_9d"),
            _m(score_lead=5.0, selected_hp=0.3, rank_used="rank_9d"),
            _m(score_lead=5.0, selected_hp=0.3, rank_used="rank_7d"),
            _m(score_lead=5.0, selected_hp=0.3, rank_used="rank_5d"),
        ]
        result = _aggregate_jigo_metrics(moves, target_score=0.5, target_score_max=10.0)
        assert result["rank_downgrade_counts"] == {
            "rank_9d": 2, "rank_7d": 1, "rank_5d": 1
        }
```

- [ ] **Step 2: テストを実行して失敗することを確認**

```bash
pytest tests/test_batch_eval_jigo.py -v
```

期待出力: ImportError（`_aggregate_jigo_metrics` が存在しない）

- [ ] **Step 3: 集計関数を実装**

`katrain_debug/batch_eval.py` の末尾（`_aggregate_stats` 関数の後）に追加:

```python
def _aggregate_jigo_metrics(move_results, target_score, target_score_max):
    """Jigo 戦略専用の集計指標を計算する。

    Args:
        move_results: batch_evaluate の move_results（Jigo 固有フィールド含む）
        target_score: Jigo の目標目差下限
        target_score_max: Jigo の目標目差上限

    Returns:
        Jigo 固有指標 dict、もしくは空 dict（有効行ゼロの場合）
    """
    # score_lead が None でない行のみ集計対象
    valid = [m for m in move_results if m.get("score_lead") is not None]
    if not valid:
        return {}

    n = len(valid)
    leads = [m["score_lead"] for m in valid]
    hps = [m["selected_hp"] for m in valid if m.get("selected_hp") is not None]

    mean_lead = sum(leads) / n
    max_lead = max(leads)
    in_target = sum(1 for l in leads if target_score <= l <= target_score_max)
    over_target = sum(1 for l in leads if l > target_score_max)

    # p10: 下位10%値（ソート後の 10 パーセンタイル位置）
    sorted_hps = sorted(hps) if hps else []
    if sorted_hps:
        mean_hp = sum(sorted_hps) / len(sorted_hps)
        # 線形補間 p10: index = 0.1 * (n-1)
        idx = 0.1 * (len(sorted_hps) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(sorted_hps) - 1)
        frac = idx - lo
        p10_hp = sorted_hps[lo] * (1 - frac) + sorted_hps[hi] * frac
    else:
        mean_hp = None
        p10_hp = None

    relax_count = sum(1 for m in valid if m.get("filter_relaxed"))
    filter_relax_rate = relax_count / n

    rank_counts = {"rank_9d": 0, "rank_7d": 0, "rank_5d": 0}
    for m in valid:
        r = m.get("rank_used")
        if r in rank_counts:
            rank_counts[r] += 1

    return {
        "count": n,
        "mean_lead": mean_lead,
        "max_lead": max_lead,
        "in_target_ratio": in_target / n,
        "over_target_ratio": over_target / n,
        "mean_selected_hp": mean_hp,
        "p10_selected_hp": p10_hp,
        "filter_relax_rate": filter_relax_rate,
        "rank_downgrade_counts": rank_counts,
    }
```

- [ ] **Step 4: テストを実行してパスすることを確認**

```bash
pytest tests/test_batch_eval_jigo.py -v
```

期待出力: 7 テスト全て PASS

- [ ] **Step 5: `batch_evaluate` の戻り値に `jigo_metrics` を追加**

`katrain_debug/batch_eval.py` の L160-L171（`stats = _aggregate_stats(move_results)` から `return {...}` まで）を置換:

```python
        # 集計
        stats = _aggregate_stats(move_results)
        if strategy_name == "jigo":
            stats["jigo_metrics"] = _aggregate_jigo_metrics(
                move_results,
                target_score=ai_settings.get("target_score", 0.5),
                target_score_max=ai_settings.get("target_score_max", 10.0),
            )
        return {
            "sgf": sgf_path,
            "total_moves": total_moves,
            "evaluated_range": (start, min(end, total_moves)),
            "strategy": strategy_name,
            "strategy_class": STRATEGY_REGISTRY[ai_mode].__name__,
            "player_filter": player_filter,
            "settings": ai_settings,
            "moves": move_results,
            "stats": stats,
        }
```

- [ ] **Step 6: 既存の batch_eval 回帰テストがあれば実行**

```bash
pytest tests/test_debug_runner.py tests/test_batch_eval_jigo.py -v
```

期待出力: 全 PASS（test_debug_runner に batch_eval カバレッジあれば）

- [ ] **Step 7: コミット**

```bash
git add katrain_debug/batch_eval.py tests/test_batch_eval_jigo.py
git commit -m "$(cat <<'EOF'
feat(debug): batch_eval に Jigo 専用集計指標を追加

_aggregate_jigo_metrics を追加。mean_lead / max_lead / in_target_ratio
/ over_target_ratio / mean_selected_hp / p10_selected_hp / filter_relax_rate
/ rank_downgrade_counts を算出。strategy == "jigo" 時のみ stats.jigo_metrics
に格納。純粋関数として切り出してユニットテスト可能にした。
EOF
)"
```

---

## Task 6: CLI の text 出力に Jigo Metrics ブロックを追加

**Files:**
- Modify: `katrain_debug/cli.py:85-145`（`format_batch_text`）

**背景:** `--output text`（デフォルト）のバッチ出力に Jigo 専用指標ブロックを追加する。`--output json` は stats.jigo_metrics として既に構造化済み。

- [ ] **Step 1: `format_batch_text` に Jigo ブロックを追加**

`katrain_debug/cli.py` の `format_batch_text` 関数、L143-L145（`return "\n".join(lines)` の直前）に以下を挿入:

```python
    # Jigo Metrics ブロック（strategy == "jigo" 時のみ）
    jigo_metrics = stats.get("jigo_metrics")
    if jigo_metrics:
        lines.append("--- Jigo Metrics ---")
        lines.append(f"  Count:              {jigo_metrics['count']}")
        lines.append(f"  Mean Lead:          {jigo_metrics['mean_lead']:.2f}")
        lines.append(f"  Max Lead:           {jigo_metrics['max_lead']:.2f}")
        lines.append(f"  In-Target Ratio:    {jigo_metrics['in_target_ratio']:.1%}")
        lines.append(f"  Over-Target Ratio:  {jigo_metrics['over_target_ratio']:.1%}")
        if jigo_metrics['mean_selected_hp'] is not None:
            lines.append(f"  Mean Selected HP:   {jigo_metrics['mean_selected_hp']:.4f}")
            lines.append(f"  P10 Selected HP:    {jigo_metrics['p10_selected_hp']:.4f}")
        lines.append(f"  Filter Relax Rate:  {jigo_metrics['filter_relax_rate']:.1%}")
        lines.append(f"  Rank Downgrades:    {jigo_metrics['rank_downgrade_counts']}")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 2: 構文チェック**

```bash
python -c "from katrain_debug import cli"
```

期待出力: エラーなし

- [ ] **Step 3: コミット**

```bash
git add katrain_debug/cli.py
git commit -m "$(cat <<'EOF'
feat(debug): CLI text 出力に Jigo Metrics ブロックを追加

--batch の text 出力末尾に stats.jigo_metrics を可視化するセクションを
追加。strategy == "jigo" 時のみ表示。JSON 出力側は既存の stats 配下で
参照可能なため変更不要。
EOF
)"
```

---

## Task 7: 動作確認（off config 1 run の smoke test）

**Files:** なし（ツール実行のみ）

**背景:** 実装した拡張が KataGo 経由で動くか、Jigo Metrics が期待通り出力されるかを 1 run で確認する。問題があればこの時点で修正。

- [ ] **Step 1: off config（`dynamic_rank=False`）で 1 run 実行**

```bash
python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf \
  --strategy jigo --batch --player W \
  --settings target_score_max=5.0 max_loss_per_move=7.0 jigo_dynamic_rank=false \
  --output text 2>/dev/null | tee docs/superpowers/specs/calibration-data/runs/smoketest_off.txt
```

期待出力: 最後に `--- Jigo Metrics ---` ブロックが現れ、以下のキーが埋まっている:
- Count（白番の評価手番数、60 前後）
- Mean Lead / Max Lead（数値、max は +30 近く）
- In-Target Ratio / Over-Target Ratio（% 表示）
- Mean Selected HP / P10 Selected HP（小数、0.0 より大）
- Filter Relax Rate（%）
- Rank Downgrades（`{'rank_9d': N, 'rank_7d': 0, 'rank_5d': 0}` で rank_9d のみカウント、dynamic_rank=False のため）

- [ ] **Step 2: JSON 出力も確認**

```bash
python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf \
  --strategy jigo --batch --player W \
  --settings target_score_max=5.0 max_loss_per_move=7.0 jigo_dynamic_rank=false \
  --output json 2>/dev/null > docs/superpowers/specs/calibration-data/runs/smoketest_off.json
```

```bash
python -c "import json; d=json.load(open('docs/superpowers/specs/calibration-data/runs/smoketest_off.json', encoding='utf-8')); print(d['stats'].get('jigo_metrics'))"
```

期待出力: dict が表示され、`count`, `mean_lead`, `rank_downgrade_counts` 等のキーが存在

- [ ] **Step 3: 問題があれば修正**

- `jigo_metrics` キー欠落 → Task 5 Step 5 の分岐を再確認
- `rank_used` が全 None → Task 3 Step 2（Stage1 override 直後の記録）を再確認
- `selected_hp/score` が None → Task 3 Step 4（選択直後の update）を再確認
- `filter_relaxed` が常に False → 実データで発動しない可能性も（正常ケース）。念のため off config より 5-15 config で発動数を見るのは Task 8 で可能

問題なければ smoketest ファイルは gitignore 配下なので削除不要（参照用に残す）。

---

## Task 7.5: SGF メインライン化と human_profile デフォルト対応

**Files:**
- Create: `docs/superpowers/specs/calibration-data/clean_sgf_main_line.py`
- Modify (overwrite): `docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf`

**背景:** 2026-04-13 セッションで Task 7 のスモークテストを実施した結果、以下 2 件の問題が判明:

1. **SGF が 18 手しか評価されない（実際は 120 手）**: テスト SGF は KaTrain で対局保存されたもので、189 個の variation を含む。`batch_eval.py` の `node = node.children[0]` traversal が短い分岐を選んで打ち切られる。最長パスは 120 手だが、最初の分岐点 (move 17) で `children[0]` が 1 手だけ、`children[1]` が 103 手の長いパスとなる。
2. **ユーザのローカル `~/.katrain/config.json` の `human_profile` デフォルトが `rank_5d`**: 実対局では `rank_9d` を使用していたため、Task 8 の校正条件と一致させるには `human_profile=rank_9d` を明示する必要がある。

**方針 (Option A: SGF 前処理):** `batch_eval.py` のセマンティクスは変えず、データ側を SGF main-line 慣習に合致させる。汎用前処理スクリプトとして `clean_sgf_main_line.py` を追加し、校正用 SGF を最長パスのみのクリーン版に置き換える。

- [ ] **Step 1: スクリプト作成**

`docs/superpowers/specs/calibration-data/clean_sgf_main_line.py` を新規作成:

```python
"""SGF の variation を全て落として、最長パス（actually-played main line）のみを残す前処理ツール。

KaTrain で保存された SGF は AI の代替手や user の探索が variation として保存されるため、
batch_eval の `node.children[0]` traversal が短い分岐に陥る。本ツールは最長パスを
辿ってその path 上の手だけを含む新 SGF を出力する。

使用:
    python clean_sgf_main_line.py <input.sgf> <output.sgf>
"""
import sys
from pathlib import Path

from katrain.core.game import KaTrainSGF


def longest_depth(node):
    """Return the depth of the longest path from this node to any leaf."""
    if not node.children:
        return 0
    return 1 + max(longest_depth(c) for c in node.children)


def collect_main_line_nodes(root):
    """Walk root → leaf following the longest child at each branch.

    Returns a list of nodes (excluding root) representing the main line.
    """
    nodes = []
    node = root
    while node.children:
        node = max(node.children, key=longest_depth)
        nodes.append(node)
    return nodes


def serialize_node_props(node):
    """Serialize a single node's properties as SGF string (excluding semicolon)."""
    parts = []
    for key, values in node.properties.items():
        # values is a list per SGF spec
        joined = "".join(f"[{v}]" for v in values)
        parts.append(f"{key}{joined}")
    return "".join(parts)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.sgf> <output.sgf>", file=sys.stderr)
        sys.exit(1)
    input_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])

    root = KaTrainSGF.parse_file(str(input_path))
    main_nodes = collect_main_line_nodes(root)

    # Build SGF: (root_props ;move1 ;move2 ... ;moveN)
    parts = ["(;"]
    parts.append(serialize_node_props(root))
    for n in main_nodes:
        parts.append(";")
        parts.append(serialize_node_props(n))
    parts.append(")")

    output_path.write_text("".join(parts), encoding="utf-8")
    print(f"Wrote {len(main_nodes)} main-line moves to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 元 SGF をバックアップしてからクリーン版で上書き**

```bash
cp docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf \
   docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf.orig

python docs/superpowers/specs/calibration-data/clean_sgf_main_line.py \
   docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf.orig \
   docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf
```

期待出力（stderr）: `Wrote 120 main-line moves to ...`

- [ ] **Step 3: クリーン版 SGF の検証**

```bash
python -c "
from katrain.core.game import KaTrainSGF
root = KaTrainSGF.parse_file('docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf')
def count_first(node, d=0):
    if not node.children: return d
    return count_first(node.children[0], d+1)
def count_longest(node, d=0):
    if not node.children: return d
    return max(count_longest(c, d+1) for c in node.children)
print(f'children[0] path: {count_first(root)} moves')
print(f'longest path: {count_longest(root)} moves')
"
```

期待出力: 両方とも `120 moves`（分岐がなくなったので一致）

- [ ] **Step 4: 元の variation 入り SGF (`.orig`) を gitignore に追加**

`docs/superpowers/specs/calibration-data/.gitignore` を編集:

```
runs/
*.sgf.orig
```

- [ ] **Step 5: スモークテストを再実行（クリーン版で 60 手程度の評価が出ることを確認）**

```bash
python -m katrain_debug \
  --sgf docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf \
  --strategy jigo --batch --player W \
  --settings target_score_max=5.0 max_loss_per_move=7.0 jigo_dynamic_rank=false \
             human_profile=rank_9d \
  --output text 2>/dev/null | tee docs/superpowers/specs/calibration-data/runs/smoketest_off_v2.txt
```

期待出力: `Count: ~60`（白番のみ、120 手の半分前後）、Rank Downgrades が `{rank_9d: N, rank_7d: 0, rank_5d: 0}`

- [ ] **Step 6: コミット**

```bash
git add docs/superpowers/specs/calibration-data/clean_sgf_main_line.py \
        docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf \
        docs/superpowers/specs/calibration-data/.gitignore
git commit -m "$(cat <<'EOF'
chore: 校正用 SGF を最長パスにクリーン化、human_profile 対応

KaTrain で保存された SGF が 189 個の variation を含み、batch_eval の
children[0] traversal が短い分岐で打ち切られていた問題を修正。
clean_sgf_main_line.py で最長パスを抽出し、main-line のみの SGF に
上書き（元ファイルは .orig として gitignore）。
これにより Task 8 のバッチ評価が 120 手の actual game を全て評価可能。
EOF
)"
```

---

## Task 8: 5 config × 3 run バッチ評価実行

**Files:** 生成のみ（`docs/superpowers/specs/calibration-data/runs/*.json`、gitignore 配下）

**背景:** 設計書の 5 configs（`off`, `5-15`, `3-10`, `5-10`, `3-15`）をそれぞれ 3 run 実行。1 run ≈ 10 分、合計 ≈ 2.5 時間。

- [ ] **Step 1: 実行用シェルスクリプト作成**

`docs/superpowers/specs/calibration-data/run_grid.sh` を新規作成:

```bash
#!/usr/bin/env bash
# Jigo dynamic rank 校正グリッド実行スクリプト
# 使用: bash docs/superpowers/specs/calibration-data/run_grid.sh

set -euo pipefail

SGF="docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf"
RUNS_DIR="docs/superpowers/specs/calibration-data/runs"
mkdir -p "$RUNS_DIR"

COMMON_SETTINGS="target_score_max=5.0 max_loss_per_move=7.0 human_profile=rank_9d"

run_config() {
    local config_id="$1"
    local extra_settings="$2"
    for i in 1 2 3; do
        local out="$RUNS_DIR/${config_id}_run${i}.json"
        if [ -f "$out" ]; then
            echo "SKIP ${config_id} run ${i} (already exists: $out)"
            continue
        fi
        echo "RUN  ${config_id} run ${i} → $out"
        python -m katrain_debug \
            --sgf "$SGF" \
            --strategy jigo --batch --player W \
            --settings $COMMON_SETTINGS $extra_settings \
            --output json 2>/dev/null > "$out"
    done
}

run_config "off"   "jigo_dynamic_rank=false"
run_config "5-15"  "jigo_dynamic_rank=true jigo_rank_delta_1=5 jigo_rank_delta_2=15"
run_config "3-10"  "jigo_dynamic_rank=true jigo_rank_delta_1=3 jigo_rank_delta_2=10"
run_config "5-10"  "jigo_dynamic_rank=true jigo_rank_delta_1=5 jigo_rank_delta_2=10"
run_config "3-15"  "jigo_dynamic_rank=true jigo_rank_delta_1=3 jigo_rank_delta_2=15"

echo "Done. Runs in $RUNS_DIR"
ls -la "$RUNS_DIR"
```

- [ ] **Step 2: スクリプト実行（長時間ジョブ）**

```bash
bash docs/superpowers/specs/calibration-data/run_grid.sh
```

期待出力: 15 個の JSON ファイル（5 config × 3 run）が `runs/` に生成される。全体で 2〜3 時間。

途中で中断した場合、既存ファイルはスキップされるので再実行で続きから再開可能。

- [ ] **Step 3: 15 ファイルすべて揃ったことを確認**

```bash
ls docs/superpowers/specs/calibration-data/runs/*.json | wc -l
```

期待出力: `15`

- [ ] **Step 4: スクリプトをコミット**

```bash
git add docs/superpowers/specs/calibration-data/run_grid.sh
git commit -m "$(cat <<'EOF'
chore: Jigo 動的 rank 校正グリッド実行スクリプトを追加

5 configs (off / 5-15 / 3-10 / 5-10 / 3-15) × 3 run をまとめて実行。
既存 JSON があればスキップするので中断再開可能。
EOF
)"
```

---

## Task 9: 集計スクリプトで 3-run 平均 / 標準偏差と convergence_score を算出

**Files:**
- Create: `docs/superpowers/specs/calibration-data/aggregate.py`

**背景:** 15 個の JSON から config × 指標 × (mean, std) のテーブルを作り、`convergence_score = in_target_ratio - 0.5 × over_target_ratio - 0.02 × mean_lead` を計算して判定に必要な情報を揃える。

- [ ] **Step 1: 集計スクリプト作成**

`docs/superpowers/specs/calibration-data/aggregate.py` を新規作成:

```python
# docs/superpowers/specs/calibration-data/aggregate.py
"""Jigo 動的 rank 校正の 3-run 集計スクリプト。

runs/ 配下の {config_id}_run{1,2,3}.json を読み、config ごとに
平均・標準偏差・convergence_score を算出して markdown テーブル + JSON を出力。
"""
import json
import math
import sys
from pathlib import Path

RUNS_DIR = Path(__file__).parent / "runs"
CONFIGS = ["off", "5-15", "3-10", "5-10", "3-15"]

METRICS = [
    "mean_lead", "max_lead",
    "in_target_ratio", "over_target_ratio",
    "mean_selected_hp", "p10_selected_hp",
    "filter_relax_rate",
]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def std(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def convergence_score(m):
    """convergence_score = in_target_ratio - 0.5*over_target_ratio - 0.02*mean_lead"""
    return (
        m["in_target_ratio"]
        - 0.5 * m["over_target_ratio"]
        - 0.02 * m["mean_lead"]
    )


def load_runs(config_id):
    runs = []
    for i in (1, 2, 3):
        path = RUNS_DIR / f"{config_id}_run{i}.json"
        if not path.exists():
            print(f"MISSING: {path}", file=sys.stderr)
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        jm = data["stats"].get("jigo_metrics")
        if jm is None:
            print(f"No jigo_metrics in {path}", file=sys.stderr)
            continue
        runs.append(jm)
    return runs


def aggregate_config(config_id):
    runs = load_runs(config_id)
    if not runs:
        return None
    agg = {"config_id": config_id, "n_runs": len(runs)}
    for metric in METRICS:
        vals = [r.get(metric) for r in runs]
        agg[f"{metric}_mean"] = mean(vals)
        agg[f"{metric}_std"] = std(vals)
    # convergence_score per run (run ごとに計算して平均・std)
    conv_scores = [convergence_score(r) for r in runs]
    agg["conv_score_mean"] = mean(conv_scores)
    agg["conv_score_std"] = std(conv_scores)
    # rank_downgrade_counts は最後の run のみ参考表示（3run 平均は意味薄）
    agg["rank_downgrade_counts_last"] = runs[-1].get("rank_downgrade_counts")
    return agg


def format_markdown_table(aggs):
    lines = []
    header = ("| config | n | conv_score | in_target | over_target | mean_lead | max_lead "
              "| mean_hp | p10_hp | relax_rate |")
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)
    for a in aggs:
        if a is None:
            continue
        row = (
            f"| {a['config_id']} | {a['n_runs']} "
            f"| {a['conv_score_mean']:.3f}±{a['conv_score_std']:.3f} "
            f"| {a['in_target_ratio_mean']:.1%}±{a['in_target_ratio_std']:.1%} "
            f"| {a['over_target_ratio_mean']:.1%}±{a['over_target_ratio_std']:.1%} "
            f"| {a['mean_lead_mean']:.2f}±{a['mean_lead_std']:.2f} "
            f"| {a['max_lead_mean']:.1f}±{a['max_lead_std']:.1f} "
            f"| {a['mean_selected_hp_mean']:.3f}±{a['mean_selected_hp_std']:.3f} "
            f"| {a['p10_selected_hp_mean']:.3f}±{a['p10_selected_hp_std']:.3f} "
            f"| {a['filter_relax_rate_mean']:.1%}±{a['filter_relax_rate_std']:.1%} |"
        )
        lines.append(row)
    return "\n".join(lines)


def apply_gates(aggs):
    """人間らしさ gate: 5-15 基準と比較して pass/fail を判定。"""
    baseline = next((a for a in aggs if a and a["config_id"] == "5-15"), None)
    if baseline is None:
        print("WARN: no baseline 5-15 found, skipping gate check", file=sys.stderr)
        return {}
    gates = {}
    for a in aggs:
        if a is None:
            continue
        cid = a["config_id"]
        if cid == "5-15":
            gates[cid] = "baseline"
            continue
        checks = []
        if baseline["mean_selected_hp_mean"] is not None and a["mean_selected_hp_mean"] is not None:
            checks.append(("mean_hp", a["mean_selected_hp_mean"] >= 0.9 * baseline["mean_selected_hp_mean"]))
        if baseline["p10_selected_hp_mean"] is not None and a["p10_selected_hp_mean"] is not None:
            checks.append(("p10_hp", a["p10_selected_hp_mean"] >= 0.8 * baseline["p10_selected_hp_mean"]))
        checks.append(("relax_rate", a["filter_relax_rate_mean"] <= 1.2 * max(baseline["filter_relax_rate_mean"], 0.01)))
        passed = all(ok for _, ok in checks)
        failing = [name for name, ok in checks if not ok]
        gates[cid] = "pass" if passed else f"fail({','.join(failing)})"
    return gates


def main():
    aggs = [aggregate_config(c) for c in CONFIGS]
    print("# Jigo Dynamic Rank Calibration Aggregate\n")
    print("## Aggregate Table (3-run mean ± std)\n")
    print(format_markdown_table(aggs))
    print()

    gates = apply_gates(aggs)
    print("## Gates\n")
    for cid, status in gates.items():
        print(f"- `{cid}`: {status}")
    print()

    # 採用判定候補
    valid = [a for a in aggs if a and a["config_id"] != "off" and gates.get(a["config_id"]) in ("pass", "baseline")]
    if valid:
        best = max(valid, key=lambda a: a["conv_score_mean"])
        baseline = next((a for a in aggs if a and a["config_id"] == "5-15"), None)
        print("## Decision Candidate\n")
        print(f"- Best conv_score config: `{best['config_id']}` "
              f"(score={best['conv_score_mean']:.3f}±{best['conv_score_std']:.3f})")
        if baseline and best["config_id"] != "5-15":
            diff = best["conv_score_mean"] - baseline["conv_score_mean"]
            threshold = max(0.05, best["conv_score_std"])
            adopt = diff >= threshold
            print(f"- Diff vs baseline 5-15: {diff:+.3f} "
                  f"(threshold=max(0.05, conv_score_std={best['conv_score_std']:.3f}))")
            print(f"- **Adopt:** {'YES' if adopt else 'NO (保守的バイアスで現行維持)'}")
        elif best["config_id"] == "5-15":
            print("- Best is baseline itself → 現行維持")

    print()
    # 最後に rank downgrade counts（デバッグ用）
    print("## Rank Downgrade Counts (last run)\n")
    for a in aggs:
        if a is None:
            continue
        print(f"- `{a['config_id']}`: {a['rank_downgrade_counts_last']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: スクリプト実行**

```bash
python docs/superpowers/specs/calibration-data/aggregate.py
```

期待出力: markdown 形式で集計テーブル + gate 判定 + 採用候補が stdout に出る。

- [ ] **Step 3: 結果を一時保存（後続タスクで参照）**

```bash
python docs/superpowers/specs/calibration-data/aggregate.py \
  > docs/superpowers/specs/calibration-data/_aggregate_output.md
```

- [ ] **Step 4: コミット（スクリプトのみ）**

```bash
git add docs/superpowers/specs/calibration-data/aggregate.py
git commit -m "$(cat <<'EOF'
chore: Jigo 校正結果の 3-run 集計スクリプトを追加

runs/*.json を読んで config × 指標の平均±標準偏差テーブルを markdown で出力。
convergence_score と人間らしさ gate の判定も自動化。採用候補と diff も表示。
EOF
)"
```

---

## Task 10: 結果文書と判定の作成

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md`

**背景:** Task 9 の集計結果を人間可読の判定文書にまとめる。設計書の「採用判定フロー」に従って最終結論を出す。

- [ ] **Step 1: 集計結果の markdown を雛形に流し込む**

`docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md` を新規作成（`_aggregate_output.md` の内容を参考に）:

```markdown
# Jigo Dynamic Rank Calibration Results (2026-04-13)

## Test Data
- SGF: `docs/superpowers/specs/calibration-data/jigo-vs-3dan-20260413.sgf`
  - 19 路、白=AI Jigo、黒=人間3段、120 手で黒投了、最終 lead +33
- Base settings: `target_score=0.5`, `target_score_max=5.0`, `max_loss_per_move=7.0`, `min_human_policy=0.02`, `jigo_mode=natural`, `human_profile=rank_9d`
- Evaluation: White moves only, 3 runs per config, 5 configs total (15 runs)

## Results (3-run mean ± std)

（ここに Task 9 で生成した aggregate table を貼り付け）

## Gates (vs baseline 5-15)

（ここに Task 9 の gate 結果を貼り付け。pass/fail と失敗指標）

## Rank Downgrade Counts (last run)

（ここに各 config の rank_downgrade_counts を貼り付け）

## Decision

（Task 9 の採用候補を元に手動で最終判定を記述）

**採用閾値:** `delta_1 = <X>`, `delta_2 = <Y>`
（または「現行 5-15 維持」「off 推奨」等）

**判定根拠:**
- convergence_score: <config_id> が <score> で最良、baseline 5-15 との diff <diff>（threshold=<threshold>）
- 人間らしさ gate: <pass/fail 説明>
- N=1 SGF での校正のため、過剰適合リスクを考慮して保守的判定を適用

## Notes

- N=1 SGF での校正。将来、他の弱相手 SGF が得られたら再校正推奨
- `jigo_rank_delta_1` / `jigo_rank_delta_2` の設定キーは実装済み（GUI 非露出）。escape hatch として保持
```

- [ ] **Step 2: `_aggregate_output.md` の内容を確認しつつ、テンプレの該当箇所を埋める**

```bash
cat docs/superpowers/specs/calibration-data/_aggregate_output.md
```

テンプレート内の「（ここに Task 9 で生成した ...）」箇所に実データを手動で転記し、**Decision** セクションに最終判定を書く。採用判定ロジック:

- **採用**: best config の conv_score が 5-15 より 0.05 以上 かつ その差 ≥ conv_score_std → そのconfigを採用
- **現行維持**: 差 < 0.05 または std 内 → 5-15 維持、Decision に「差が誤差範囲」と記載
- **off 推奨**: 全 dynamic_rank config が gate 落ち → off を採用（`jigo_dynamic_rank=False` 推奨）と記載

- [ ] **Step 3: 判定が決まったら `_aggregate_output.md` は削除**

```bash
rm docs/superpowers/specs/calibration-data/_aggregate_output.md
```

- [ ] **Step 4: 結果文書をコミット**

```bash
git add docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md
git commit -m "$(cat <<'EOF'
docs: Jigo 動的 rank 校正の結果と判定を記録

N=1 SGF (3段 vs Jigo 白番) でバッチ評価した 5 config × 3 run の結果。
採用: <delta_1>/<delta_2> （または現行維持／off 推奨）
判定根拠は convergence_score diff と人間らしさ gate を併用。
EOF
)"
```

---

## Task 11: 採用値をコードとドキュメントに反映

**Files:**
- Modify: `katrain/core/ai.py:746`（デフォルト引数）
- Modify: `.claude/rules/ai-parameters.md`（JigoStrategy セクションの閾値記述）
- Modify: `docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md`（弱相手対応セクション）

**背景:** Task 10 の判定に基づき、採用値を各箇所に反映する。「現行維持」判定の場合はコード変更なし・文書に「校正完了・現行値維持」を追記するのみ。

### 11-A. 採用値が現行と異なる場合（コード変更あり）

- [ ] **Step 1: `_select_rank_by_lead` のデフォルト引数を変更**

`katrain/core/ai.py` の `_select_rank_by_lead` の関数定義を変更:

```python
def _select_rank_by_lead(current_lead, target_score_max, base_profile,
                          delta_1=<採用値X>, delta_2=<採用値Y>):
```

- [ ] **Step 2: docstring 内の閾値記述も更新**

```python
    """リードが target_max を超えた度合いに応じて humanSL rank を降格する。

    - delta ≤ delta_1           : base_profile そのまま
    - delta_1 < delta ≤ delta_2 : base_profile より 1段下（9d→7d, 7d→5d, 5d→5d）
    - delta > delta_2           : 一気に rank_5d まで下げる

    base_profile が _JIGO_RANK_CHAIN に含まれない場合はそのまま返す。
    デフォルトの delta_1 / delta_2 は 2026-04-13 の校正で決定した値。
    """
```

- [ ] **Step 3: ユニットテスト `test_defaults_match_legacy_behavior` の期待値を更新**

Task 2 Step 1 で追加したテストは旧デフォルト（5/15）前提のため、新デフォルト値に合わせて更新:

```python
    def test_defaults_match_current_calibration(self):
        from katrain.core.ai import _select_rank_by_lead
        # 2026-04-13 校正後のデフォルト引数
        # （delta_1=<X>, delta_2=<Y> に合わせた期待値）
        # 例: delta_1=3, delta_2=10 → delta=4 で 1段下、delta=11 で rank_5d
        ...
```

（実際の assertion は採用値に応じて調整。test_defaults_match_legacy_behavior は削除 or リネーム）

- [ ] **Step 4: テスト実行**

```bash
pytest tests/test_jigo.py::TestSelectRankByLead -v
```

期待出力: 全 PASS

- [ ] **Step 5: `.claude/rules/ai-parameters.md` の JigoStrategy セクションを更新**

ファイル末尾の JigoStrategy セクション、`jigo_dynamic_rank` の行と「動的 rank 切替」の箇条書きを更新:

```markdown
| jigo_dynamic_rank | false | ON でリード差（`current_lead - target_score_max`）に応じて rank を自動降格（delta > <採用X> で1段下、> <採用Y> で rank_5d まで） |
```

と、下部の箇条書き:

```markdown
- **動的 rank 切替（opt-in）**: `jigo_dynamic_rank=true` で、前ターンの `current_lead` をキャッシュし、`delta = current_lead - target_score_max` に応じて Stage 1 の rank を降格:
  - `delta ≤ <採用X>`: base_profile そのまま
  - `<採用X> < delta ≤ <採用Y>`: chain で1段下（rank_9d → rank_7d, rank_7d → rank_5d）
  - `delta > <採用Y>`: 一気に rank_5d まで下げる
```

末尾の「**校正が必要な項目**」行は以下に置換:

```markdown
**校正履歴**: 動的 rank 降格閾値は 2026-04-13 に 3段 vs Jigo 白番 SGF でバッチ評価し、`delta_1=<X>, delta_2=<Y>` を採用（`docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md` 参照）。
```

- [ ] **Step 6: 前提 spec `2026-04-13-jigo-weak-opponent-design.md` の該当箇所を更新**

該当ファイル内の動的 rank の説明箇所を検索して校正後の値に更新:

```bash
grep -n "delta > 5\|delta > 15\|delta=5\|delta=15" \
  docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md
```

ヒットした箇所を採用値に置換。

- [ ] **Step 7: 注記として校正完了を追加**

`docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md` の末尾または該当セクションに追記:

```markdown
## 校正履歴

- **2026-04-13 校正完了**: 閾値 `delta_1=<X>, delta_2=<Y>` を採用。
  詳細: `docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md`
```

- [ ] **Step 8: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo.py .claude/rules/ai-parameters.md \
        docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md
git commit -m "$(cat <<'EOF'
feat(ai): 動的 rank 降格閾値を校正値 <X>/<Y> に更新

2026-04-13 の 3段 vs Jigo バッチ評価で、delta_1=<X>, delta_2=<Y> が
現行 5/15 より conv_score で有意に改善、人間らしさ gate も通過したため採用。
ai-parameters.md と weak-opponent spec も合わせて更新。
EOF
)"
```

### 11-B. 判定が「現行維持」の場合

- [ ] **Step 1: コードは変更なし、ai-parameters.md に校正履歴のみ追記**

`.claude/rules/ai-parameters.md` の「**校正が必要な項目**」行を以下に置換:

```markdown
**校正履歴**: 動的 rank 降格閾値は 2026-04-13 に 3段 vs Jigo 白番 SGF でバッチ評価したが、差が誤差範囲のため現行値 `delta_1=5, delta_2=15` を維持（`docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md` 参照）。
```

- [ ] **Step 2: weak-opponent spec にも同等の注記を追加**

`docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md` の末尾に:

```markdown
## 校正履歴

- **2026-04-13 校正完了**: N=1 SGF で評価、有意差なしのため現行値 5/15 を維持。
  詳細: `docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md`
```

- [ ] **Step 3: コミット**

```bash
git add .claude/rules/ai-parameters.md \
        docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md
git commit -m "$(cat <<'EOF'
docs: Jigo 動的 rank 校正は現行 5/15 維持（校正履歴追記）

2026-04-13 の 3段 vs Jigo バッチ評価で、候補閾値が現行より convergence_score で
有意な改善を示さなかった（差 < 0.05 または 3-run std 内）。保守的バイアスで
現行値を維持し、校正履歴を ai-parameters.md と weak-opponent spec に記録。
EOF
)"
```

---

## Task 12: 後片付け（メモリ削除・MEMORY.md 更新）

**Files:**
- Delete: `C:\Users\iwaki\.claude\projects\C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1\memory\project_jigo_dynamic_rank_calibration.md`
- Modify: `C:\Users\iwaki\.claude\projects\C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1\memory\MEMORY.md`

**背景:** 対象メモリで「完了したら本メモリを削除」と指示されている通り、校正完了後はメモリを撤去する。

- [ ] **Step 1: メモリファイルを削除**

```bash
rm "C:/Users/iwaki/.claude/projects/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/memory/project_jigo_dynamic_rank_calibration.md"
```

- [ ] **Step 2: MEMORY.md から該当行を削除**

`MEMORY.md` を読み込んで `project_jigo_dynamic_rank_calibration.md` の行を削除:

Edit ツールで以下を対象:
```
- [project_jigo_dynamic_rank_calibration.md](project_jigo_dynamic_rank_calibration.md) — JigoStrategy jigo_dynamic_rank の閾値 5/15 は未校正。テストデータ準備後にバッチ評価で校正予定
```

この行を削除（前後の改行ごと消す）。

- [ ] **Step 3: 変更確認**

```bash
cat "C:/Users/iwaki/.claude/projects/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/memory/MEMORY.md"
ls "C:/Users/iwaki/.claude/projects/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/memory/" | grep jigo
```

期待出力: MEMORY.md に `project_jigo_dynamic_rank_calibration.md` の行なし、ファイル一覧に該当ファイルなし

- [ ] **Step 4: 全体の最終確認**

```bash
pytest tests/test_jigo.py tests/test_batch_eval_jigo.py -v
python -c "from katrain.core import ai; from katrain_debug import batch_eval, cli"
git log --oneline -15
```

期待:
- 全テスト PASS
- import エラーなし
- コミットログに本プランの各タスクが順に並んでいる

---

## Self-Review 結果

このプランを設計書と照合:

**1. Spec coverage:**
- spec §2 スコープ → Task 2 (閾値設定化) / Task 3 (last_decision_info) / Task 4-6 (batch_eval 拡張) / Task 11 (結果反映) / Task 12 (メモリ削除) で全てカバー
- spec §3 テストデータ → Task 1 で配置
- spec §4 評価指標 → Task 3-6 で実装、Task 7 で検証
- spec §5 閾値設定化 → Task 2 で実装
- spec §6 校正実験 → Task 8 で実行
- spec §7 判定ルール → Task 9 で自動化、Task 10 で文書化
- spec §8 実装順序 → 本プランの Task 1-12 と一致
- spec §9 リスク → Task 10 の「現行維持」分岐（Task 11-B）でカバー
- spec §10 完了条件 → Task 11-12 で全項目達成

**2. Placeholder scan:**
- Task 11 の `<採用X>` / `<採用Y>` は意図的に残したプレースホルダ（Task 10 の結果に依存）。11-A / 11-B で分岐を明示しているので問題なし
- Task 10 の `（ここに Task 9 で生成した ...）` は手動転記ステップの指示として意図的

**3. Type consistency:**
- `_select_rank_by_lead(delta_1, delta_2)` — Task 2 以降一貫
- `last_decision_info` のキー（rank_used, selected_hp, selected_score, filter_relaxed, score_lead）— Task 3 定義、Task 4 で読み取り、Task 5 で集計、全て一致
- `_aggregate_jigo_metrics(move_results, target_score, target_score_max)` — Task 5 定義、同タスク内で呼び出し、一致
- `jigo_metrics` キーの構造 — Task 5（定義）、Task 6（CLI 出力）、Task 9（集計スクリプト）で一致
