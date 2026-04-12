# JigoStrategy 人間らしさ改修 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存 `JigoStrategy` を置き換え、humanSL 2段階クエリ + 損失上限 + humanPolicy フィルタ + Mode A/B（natural/maintain）を実装して、大差リード時のサボタージュ的着手（自石アタリ等）を排除する。

**Architecture:** HumanStyleStrategy と同じ 2段階クエリ実装パターン（Stage1 humanSL, Stage2 clean）を採用。フィルタ判定・候補選択・フォールバックの3処理を純粋関数として切り出し、TDD でユニットテスト可能にする。GUI 設定は `constants.py` の `AI_OPTION_VALUES[AI_JIGO]` に 4 キー追加。既存 `target_score` は流用。

**Tech Stack:** Python 3.12 / Kivy / KataGo humanSLProfile / 既存 `weighted_selection_without_replacement` ヘルパ

**関連設計書:** `docs/superpowers/specs/2026-04-12-jigo-humanlike-design.md`

---

## File Structure

| ファイル | 役割 | 変更タイプ |
|---|---|---|
| `katrain/core/ai.py` | `JigoStrategy.generate_move()` 全面書き換え + 3つの純粋関数を追加 | Modify |
| `katrain/core/constants.py` | `AI_OPTION_VALUES` に 4 キー追加 + `AI_OPTION_ORDER` 追加 | Modify |
| `katrain/config.json` | パッケージ同梱デフォルト値（4 キー追加） | Modify |
| `C:\Users\iwaki\.katrain\config.json` | ユーザーローカル設定（GUI表示のため必須・メインセッションで直接 Edit） | Modify |
| `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | `aihelp:jigo` を新挙動の説明に更新 | Modify |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 同上（英語） | Modify |
| `.mo` ファイル | `python tools/compile_mo.py` で再コンパイル | Generated |
| `.claude/rules/ai-parameters.md` | Jigo セクション追加（**サブエージェント経由**で編集） | Modify |
| `tests/test_jigo.py` | 純粋関数のユニットテスト | Create |

---

## Task 1: 純粋関数のユニットテストを先に書く（TDD Red）

**Files:**
- Create: `tests/test_jigo.py`

純粋関数 3 つを `katrain/core/ai.py` から切り出してユニットテスト可能にする。テスト先行で書く（この段階では import はまだ失敗する）。

- [ ] **Step 1: テストファイルを作成**

```python
# tests/test_jigo.py
"""JigoStrategy pure-function unit tests."""
import pytest

from katrain.core.ai import (
    _jigo_filter_candidates,
    _jigo_relax_filters,
    _jigo_select_move,
)


def _c(move, score, loss, hp):
    """Build a candidate dict shorthand."""
    return {"move": move, "score": score, "loss": loss, "hp": hp}


class TestJigoFilterCandidates:
    def test_passes_moves_within_both_limits(self):
        cands = [
            _c("A1", 5.0, 0.0, 0.10),
            _c("B2", 4.0, 1.0, 0.05),
        ]
        result = _jigo_filter_candidates(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 2

    def test_rejects_move_exceeding_loss_cap(self):
        cands = [
            _c("A1", 5.0, 0.0, 0.10),
            _c("B2", -2.0, 7.0, 0.05),  # loss 7.0 > 5.6
        ]
        result = _jigo_filter_candidates(cands, max_loss=5.6, min_hp=0.01)
        assert [c["move"] for c in result] == ["A1"]

    def test_rejects_move_below_hp_threshold(self):
        cands = [
            _c("A1", 5.0, 0.0, 0.10),
            _c("B2", 4.0, 1.0, 0.005),  # hp 0.005 < 0.01
        ]
        result = _jigo_filter_candidates(cands, max_loss=5.6, min_hp=0.01)
        assert [c["move"] for c in result] == ["A1"]


class TestJigoRelaxFilters:
    def test_first_relax_step_hp_half(self):
        # all candidates have hp < base_hp but >= base_hp*0.5
        cands = [_c("A1", 5.0, 1.0, 0.006)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "hp_half"

    def test_second_relax_step_hp_quarter(self):
        cands = [_c("A1", 5.0, 1.0, 0.003)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "hp_quarter"

    def test_loss_relax_step(self):
        # hp ok under 0.25*base, but loss is between base and base*1.5
        cands = [_c("A1", 5.0, 7.0, 0.003)]  # loss 7.0 < 5.6*1.5=8.4
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "loss_150"

    def test_safety_valve_returns_top_candidate_when_all_fail(self):
        # hp and loss both too extreme — safety valve falls back to cands[0]
        cands = [
            _c("A1", 5.0, 99.0, 0.0),
            _c("B2", 4.0, 99.0, 0.0),
        ]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert result == [cands[0]]
        assert reason == "safety_valve"


class TestJigoSelectMove:
    """Selection logic is (current_lead × mode) dependent."""

    def test_below_target_picks_closest_to_target(self):
        # current_lead = -3.0, target = 0.5 → natural
        cands = [
            _c("A1", 5.0, 0.0, 0.10),
            _c("B2", 1.0, 4.0, 0.05),
            _c("C3", 0.5, 4.5, 0.05),  # closest to target=0.5
        ]
        pick = _jigo_select_move(
            cands, current_lead=-3.0, target_score=0.5,
            target_score_max=10.0, mode="natural"
        )
        assert pick["move"] == "C3"

    def test_above_max_picks_closest_to_target(self):
        # current_lead = 30.0 (way over 10.0) — both modes act the same
        cands = [
            _c("A1", 25.0, 0.0, 0.10),
            _c("B2", 5.0, 20.0, 0.05),
            _c("C3", 1.0, 24.0, 0.05),  # closest to target=0.5
        ]
        pick = _jigo_select_move(
            cands, current_lead=30.0, target_score=0.5,
            target_score_max=10.0, mode="natural"
        )
        assert pick["move"] == "C3"

    def test_in_range_natural_uses_weighted_choice(self, monkeypatch):
        # in range: natural → weighted_selection_without_replacement path
        cands = [
            _c("A1", 5.0, 0.0, 0.90),
            _c("B2", 3.0, 2.0, 0.05),
        ]

        def fake_weighted(items, n):
            # pick the highest-weight entry deterministically
            return [max(items, key=lambda t: t[1])]

        from katrain.core import ai as ai_mod
        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)

        pick = _jigo_select_move(
            cands, current_lead=5.0, target_score=0.5,
            target_score_max=10.0, mode="natural"
        )
        assert pick["move"] == "A1"

    def test_in_range_maintain_picks_closest_to_target(self):
        cands = [
            _c("A1", 5.0, 0.0, 0.90),
            _c("B2", 1.0, 4.0, 0.05),  # closest to target=0.5
        ]
        pick = _jigo_select_move(
            cands, current_lead=5.0, target_score=0.5,
            target_score_max=10.0, mode="maintain"
        )
        assert pick["move"] == "B2"
```

- [ ] **Step 2: テストを実行して import エラーになることを確認**

Run: `pytest tests/test_jigo.py -v`
Expected: `ImportError: cannot import name '_jigo_filter_candidates' from 'katrain.core.ai'`

---

## Task 2: 純粋関数3つを `ai.py` に実装（TDD Green）

**Files:**
- Modify: `katrain/core/ai.py`（既存 `JigoStrategy` の直前、ai.py:691 の前）

- [ ] **Step 1: 3つの純粋関数を追加**

`@register_strategy(AI_JIGO)` の直前（ai.py:690 付近）に以下を挿入：

```python
# ==============================================================================
# JigoStrategy pure-function helpers
# ==============================================================================
def _jigo_filter_candidates(candidates, max_loss, min_hp):
    """フィルタ通過手のみを返す。各候補は {move, score, loss, hp} を持つ dict。"""
    return [c for c in candidates if c["loss"] <= max_loss and c["hp"] >= min_hp]


def _jigo_relax_filters(candidates, max_loss, min_hp):
    """両フィルタ不通過時の段階緩和。
    返り値: (filtered_list, reason) — reason は "hp_half" / "hp_quarter" / "loss_150" / "safety_valve"。
    hp×0.5 → hp×0.25 → loss×1.5 → safety valve。
    """
    reason_map = [("hp_half", 0.5), ("hp_quarter", 0.25)]
    for reason, hp_factor in reason_map:
        f = [c for c in candidates
             if c["loss"] <= max_loss and c["hp"] >= min_hp * hp_factor]
        if f:
            return f, reason
    f = [c for c in candidates
         if c["loss"] <= max_loss * 1.5 and c["hp"] >= min_hp * 0.25]
    if f:
        return f, "loss_150"
    # Safety valve: 先頭候補（呼び出し側で KataGo 最善手が先頭に来るよう渡す前提）
    return ([candidates[0]] if candidates else []), "safety_valve"


def _jigo_select_move(candidates, current_lead, target_score, target_score_max, mode):
    """現在リード × Mode で着手を選択。
    - current_lead < target_score → target 最接近
    - target_score <= lead <= target_score_max & mode=natural → humanPolicy 重み付き
    - Mode=maintain または lead > target_score_max → target 最接近
    """
    in_range = target_score <= current_lead <= target_score_max
    if current_lead < target_score:
        return min(candidates, key=lambda c: abs(c["score"] - target_score))
    if in_range and mode == "natural":
        weighted = [(c, c["hp"]) for c in candidates]
        selected = weighted_selection_without_replacement(weighted, 1)[0]
        return selected[0]  # (candidate_dict, weight) の tuple なので [0] で dict
    return min(candidates, key=lambda c: abs(c["score"] - target_score))
```

- [ ] **Step 2: テストを実行して通ることを確認**

Run: `pytest tests/test_jigo.py -v`
Expected: all tests PASS

- [ ] **Step 3: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo.py
git commit -m "$(cat <<'EOF'
feat: JigoStrategy用の純粋関数（フィルタ/緩和/選択）を追加

humanSL 2段階クエリを前提とした候補フィルタと選択ロジックを
純粋関数として切り出し、ユニットテスト可能にする。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `constants.py` に設定キーを追加

**Files:**
- Modify: `katrain/core/constants.py`

- [ ] **Step 1: `AI_OPTION_VALUES` に 4 キー追加**

既存 `hunt_dodge_top_n` の直後（constants.py:183 の次）に追加：

```python
    # ===== JigoStrategy =====
    "target_score_max": [5.0, 10.0, 15.0],
    "max_loss_per_move": [3.0, 4.0, 5.6, 7.0],
    "min_human_policy": [(0.005, "0.5%"), (0.01, "1%"), (0.02, "2%"), (0.05, "5%")],
    "jigo_mode": [
        ("natural", "natural"),
        ("maintain", "maintain"),
    ],
```

- [ ] **Step 2: `AI_OPTION_ORDER` に順序を追加**

既存 `hunt_dodge_top_n: 1` の直後（constants.py:230 の次）に追加：

```python
    "target_score": 0,
    "target_score_max": 1,
    "max_loss_per_move": 2,
    "min_human_policy": 3,
    "jigo_mode": 4,
```

- [ ] **Step 3: 構文エラーがないことを確認**

Run: `python -c "from katrain.core import constants; print(list(constants.AI_OPTION_VALUES.keys())[-5:])"`
Expected: `['target_score_max', 'max_loss_per_move', 'min_human_policy', 'jigo_mode', ...]`（追加4キーが見える）

- [ ] **Step 4: コミット**

```bash
git add katrain/core/constants.py
git commit -m "$(cat <<'EOF'
feat: JigoStrategy用の設定キーを constants に追加

target_score_max / max_loss_per_move / min_human_policy / jigo_mode を
AI_OPTION_VALUES と AI_OPTION_ORDER に登録。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `JigoStrategy.generate_move()` を書き換え（2段階クエリ）

**Files:**
- Modify: `katrain/core/ai.py:691-741`（既存 `JigoStrategy` クラス全体）

- [ ] **Step 1: 既存の `JigoStrategy` を削除**

`ai.py:691-741`（`@register_strategy(AI_JIGO)` から次の `@register_strategy` の直前まで）を削除。

- [ ] **Step 2: 新しい `JigoStrategy` を実装**

削除した位置に以下を貼る：

```python
@register_strategy(AI_JIGO)
class JigoStrategy(AIStrategy):
    """Jigo strategy - target を狙いつつ大差時も人間らしさを維持する戦略。

    ロジック:
        1. Stage 1 (humanSL 9段固定) で humanPolicy を取得
        2. Stage 2 (clean) で正確な scoreLead を取得
        3. loss <= max_loss_per_move AND hp >= min_human_policy でフィルタ
        4. current_lead × jigo_mode で選択ロジック分岐
        5. 候補ゼロ時は段階緩和 → 最終的に KataGo 最善手へフォールバック
    """

    def generate_move(self) -> Tuple[Move, str]:
        import time
        self.game.katrain.log(f"[JigoStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()

        # ---- 設定読み込み ----
        target_score     = self.settings.get("target_score", 0.5)
        target_score_max = self.settings.get("target_score_max", 10.0)
        max_loss         = self.settings.get("max_loss_per_move", 5.6)
        min_hp           = self.settings.get("min_human_policy", 0.01)
        mode             = self.settings.get("jigo_mode", "natural")
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}", OUTPUT_DEBUG
        )

        sign = self.cn.player_sign(self.cn.next_player)
        engine = self.game.engines[self.cn.player]

        # ---- Stage 1: humanSL 9段固定クエリ ----
        human_profile = "rank_9d"  # 9段固定（HuntStrategy/SiegeStrategy/FightingStrategy と同じ表記）
        stage1_override = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 800,
        }
        stage1_analysis = None
        stage1_error = False

        def _set_stage1(a, partial):
            nonlocal stage1_analysis
            if not partial:
                stage1_analysis = a

        def _err_stage1(a):
            nonlocal stage1_error
            stage1_error = True
            self.game.katrain.log(f"[JigoStrategy] Stage1 error: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=_set_stage1, error_callback=_err_stage1,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=True,
            extra_settings=stage1_override,
        )
        while not (stage1_error or stage1_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if stage1_error or not stage1_analysis or "humanPolicy" not in stage1_analysis:
            self.game.katrain.log(
                "[JigoStrategy] Stage1 failed, falling back to KataGo top move", OUTPUT_DEBUG
            )
            candidate_moves = self.cn.candidate_moves
            if not candidate_moves:
                return Move(None, player=self.cn.next_player), "Stage1 failed, no candidates"
            top = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
            return top, "Stage1 failed — using KataGo top move"

        human_policy = stage1_analysis["humanPolicy"]
        self.game.katrain.log(
            f"[JigoStrategy] Stage1 query complete (humanPolicy len={len(human_policy)})",
            OUTPUT_DEBUG,
        )

        # ---- Stage 2: クリーンクエリ（scoreLead 用） ----
        stage2_override = {
            "ignorePreRootHistory": False,
            "maxVisits": 600,
            "wideRootNoise": 0.0,
        }
        stage2_analysis = None
        stage2_error = False

        def _set_stage2(a, partial):
            nonlocal stage2_analysis
            if not partial:
                stage2_analysis = a

        def _err_stage2(a):
            nonlocal stage2_error
            stage2_error = True
            self.game.katrain.log(f"[JigoStrategy] Stage2 error: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=_set_stage2, error_callback=_err_stage2,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=False,
            extra_settings=stage2_override,
        )
        while not (stage2_error or stage2_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        # Stage 2 失敗時は Stage 1 にフォールバック
        if stage2_error or not stage2_analysis:
            self.game.katrain.log(
                "[JigoStrategy] Stage2 failed, using Stage1 moveInfos (biased)", OUTPUT_DEBUG
            )
            score_analysis = stage1_analysis
        else:
            score_analysis = stage2_analysis
        move_infos = score_analysis.get("moveInfos", [])
        if not move_infos:
            self.game.katrain.log("[JigoStrategy] No moveInfos, passing", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "No moveInfos, passing"

        # ---- 候補リスト構築（すべて自分視点 = sign を掛けた値） ----
        scores_player = [mi.get("scoreLead", 0) * sign for mi in move_infos]
        best_score = max(scores_player)  # 自分視点の最善スコア

        # Stage 1 のhumanPolicy をフラット配列から gtp → value のルックアップに変換
        bx, by = self.game.board_size
        def _hp_for_gtp(gtp):
            if gtp == "pass":
                return human_policy[-1] if len(human_policy) > bx * by else 0.0
            try:
                m = Move.from_gtp(gtp, player=self.cn.next_player)
                if m.coords is None:
                    return 0.0
                x, y = m.coords
                idx = (by - y - 1) * bx + x
                return human_policy[idx] if 0 <= idx < len(human_policy) else 0.0
            except Exception:
                return 0.0

        candidates = []
        for mi, score in zip(move_infos, scores_player):
            gtp = mi.get("move", "")
            candidates.append({
                "move": gtp,
                "score": score,           # 自分視点
                "loss": best_score - score,
                "hp": _hp_for_gtp(gtp),
            })
        self.game.katrain.log(
            f"[JigoStrategy] Stage2 query complete ({len(candidates)} candidates, "
            f"best_score={best_score:.2f})", OUTPUT_DEBUG
        )

        # ---- フィルタ適用 ----
        filtered = _jigo_filter_candidates(candidates, max_loss, min_hp)
        passed = len(filtered)
        self.game.katrain.log(
            f"[JigoStrategy] Filter: {len(candidates)} → {passed} passed "
            f"(loss<={max_loss}, hp>={min_hp})", OUTPUT_DEBUG
        )

        # ---- フォールバック段階緩和 ----
        if not filtered:
            filtered, reason = _jigo_relax_filters(candidates, max_loss, min_hp)
            self.game.katrain.log(
                f"[JigoStrategy] Fallback triggered: reason={reason}, {len(filtered)} candidates",
                OUTPUT_DEBUG
            )
            if reason == "safety_valve":
                self.game.katrain.log(
                    "[JigoStrategy] Safety valve: using KataGo top move", OUTPUT_ERROR
                )

        # ---- 現在リード & 選択分岐 ----
        current_lead = score_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
        in_range = target_score <= current_lead <= target_score_max
        self.game.katrain.log(
            f"[JigoStrategy] Mode: {mode}, lead={current_lead:.2f}, in_range={in_range}",
            OUTPUT_DEBUG,
        )
        pick = _jigo_select_move(filtered, current_lead, target_score, target_score_max, mode)

        # ---- 結果 ----
        if pick["move"] == "pass":
            aimove = Move(None, player=self.cn.next_player)
        else:
            aimove = Move.from_gtp(pick["move"], player=self.cn.next_player)
        ai_thoughts = (
            f"Jigo (mode={mode}, lead={current_lead:.1f}): chose {pick['move']} "
            f"(loss={pick['loss']:.2f}, hp={pick['hp']:.3f}, score={pick['score']:.2f})"
        )
        self.game.katrain.log(
            f"[JigoStrategy] Selected: {pick['move']} "
            f"(loss={pick['loss']:.2f}, hp={pick['hp']:.3f}, score={pick['score']:.2f})",
            OUTPUT_DEBUG,
        )
        return aimove, ai_thoughts
```

- [ ] **Step 3: 構文チェック**

Run: `python -c "from katrain.core import ai"`
Expected: import エラーなし

- [ ] **Step 4: テスト再実行（helper 関数が他の場所に影響していないか確認）**

Run: `pytest tests/test_jigo.py tests/test_board.py tests/test_parser.py -v`
Expected: all PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "$(cat <<'EOF'
feat: JigoStrategy を 2段階クエリ + 損失/humanPolicyフィルタで書き換え

大差リード時のサボタージュ的着手を排除する新ロジックに置換。
humanSL 9段固定のStage1で humanPolicy を取得し、Stage2 のクリーンな
scoreLead を基に loss フィルタと Mode A/B 選択を行う。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: パッケージ `config.json` のデフォルト値追加

**Files:**
- Modify: `katrain/config.json:102-104`

- [ ] **Step 1: `ai:jigo` セクションに 4 キー追加**

既存：
```json
        "ai:jigo": {
            "target_score": 0.5
        },
```

変更後：
```json
        "ai:jigo": {
            "target_score": 0.5,
            "target_score_max": 10.0,
            "max_loss_per_move": 5.6,
            "min_human_policy": 0.01,
            "jigo_mode": "natural"
        },
```

- [ ] **Step 2: JSON 構文チェック**

Run: `python -c "import json; json.load(open('katrain/config.json'))"`
Expected: エラーなし（JSON として valid）

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "$(cat <<'EOF'
feat: ai:jigo にデフォルト値（target_score_max / max_loss_per_move / min_human_policy / jigo_mode）を追加

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: ユーザーローカル `config.json` 更新（**メインセッションで直接 Edit**）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json:102-104`

> **CLAUDE.md ルール**: ユーザーローカル `config.json` の編集はサブエージェントに委任しないこと。メインセッションで直接 Edit する。

- [ ] **Step 1: 同じ内容を追加**

既存：
```json
        "ai:jigo": {
            "target_score": 0.0
        },
```

変更後：
```json
        "ai:jigo": {
            "target_score": 0.5,
            "target_score_max": 10.0,
            "max_loss_per_move": 5.6,
            "min_human_policy": 0.01,
            "jigo_mode": "natural"
        },
```

> 注: 現在の `target_score: 0.0` は設計書のデフォルト 0.5 に揃える（ユーザ希望通り）。

- [ ] **Step 2: JSON 構文チェック**

Run: `python -c "import json; json.load(open('C:/Users/iwaki/.katrain/config.json'))"`
Expected: エラーなし

- [ ] **Step 3: このファイルは git 管理外なのでコミット不要**

---

## Task 7: i18n ヘルプテキスト更新

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:526-527`
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:835-838`

- [ ] **Step 1: 日本語版 `aihelp:jigo` を更新**

既存（jp.po:526-527）：
```
msgid "aihelp:jigo"
msgstr "指定された目差ちょうど（デフォルトは半目）だけ勝つことをめざします. それ以外は制限なし."
```

変更後：
```
msgid "aihelp:jigo"
msgstr "target_score〜target_score_max 目の僅差で勝つことをめざします。1手あたり max_loss_per_move 目以下 & humanPolicy >= min_human_policy の手のみ選び、人間らしくない悪手を避けます。jigo_mode: natural=範囲内は最善手 / maintain=常に target に寄せる."
```

- [ ] **Step 2: 英語版 `aihelp:jigo` を更新**

既存（en.po:835-838）：
```
msgid "aihelp:jigo"
msgstr ""
"Will try to win by a set amount of points (default 0.5), without further "
"restrictions."
```

変更後：
```
msgid "aihelp:jigo"
msgstr ""
"Aims to win by a close margin (target_score to target_score_max points). "
"Only plays moves with loss <= max_loss_per_move and humanPolicy >= "
"min_human_policy, avoiding inhuman blunders. jigo_mode: natural=best move "
"within range / maintain=always aim toward target."
```

- [ ] **Step 3: `.mo` ファイルを再コンパイル**

Run: `python tools/compile_mo.py`
Expected: 出力に `jp` / `en` の更新ログ、エラーなし

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po \
        katrain/i18n/locales/en/LC_MESSAGES/katrain.po \
        katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo \
        katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "$(cat <<'EOF'
docs: JigoStrategy の aihelp を新挙動に合わせて更新（jp/en）

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `.claude/rules/ai-parameters.md` にJigoセクション追加（**サブエージェント経由**）

**Files:**
- Modify: `.claude/rules/ai-parameters.md`

> **CLAUDE.md ルール**: `.claude/rules/*` の Edit は拒否されることがある。必ずサブエージェント経由で編集する（`memory/feedback_claude_rules_edit.md`）。

- [ ] **Step 1: サブエージェントを dispatch して編集させる**

Agent tool（general-purpose）で以下のプロンプトを渡す：

```
.claude/rules/ai-parameters.md に「持碁戦略（JigoStrategy）」セクションを追加してください。
ファイル末尾（攻城戦略セクションの次）に以下の内容を追記:

## 持碁戦略（JigoStrategy）

指定した目差範囲（0.5〜10目）で僅差勝ちを目指す戦略。人間らしくない大損失手・humanPolicy≒0 の手を除外して、サボタージュ的挙動を防ぐ。対応盤面: 全盤面（19路・13路・9路）。

**着手選択**: HumanStyle と同じ2段階クエリ方式（Stage1 humanSL 9段固定 / Stage2 クリーンスコア）。フィルタ = `loss ≤ max_loss_per_move AND humanPolicy ≥ min_human_policy`。候補ゼロ時は段階緩和（hp×0.5 → hp×0.25 → loss×1.5 → KataGo 最善手）。

**選択ロジック**:
- `current_lead < target_score`: target 最接近手（最善近辺）
- `target_score ≤ lead ≤ target_score_max` & Mode=natural: humanPolicy 重み付き（HumanStyle 相当）
- Mode=maintain または `lead > target_score_max`: target 最接近手

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| target_score | 0.5 | 狙う目差（既存流用） |
| target_score_max | 10.0 | 許容上限。これ以下なら Natural モードは普通に打つ |
| max_loss_per_move | 5.6 | 1手あたり許容損失（HumanStyle NORMAL_THRESHOLD と同値） |
| min_human_policy | 0.01 | humanPolicy 最低閾値（1%） |
| jigo_mode | "natural" | "natural"=範囲内は最善手 / "maintain"=常にtargetに寄せる |

編集後、以下のコマンドで git add & commit してください:
- git add .claude/rules/ai-parameters.md
- git commit -m "docs: ai-parameters.md に JigoStrategy セクションを追加"
   （CLAUDE.md のコミットメッセージ規約: 日本語・Conventional Commits・Co-Authored-By 行必須）
```

- [ ] **Step 2: サブエージェント終了後、git log で追加コミットを確認**

Run: `git log --oneline -3`
Expected: `docs: ai-parameters.md に JigoStrategy セクションを追加` が先頭付近にある

---

## Task 9: CLI 検証（対局不要・数十秒）

**Files:**
- 読み取り: `tests/data/panda1.sgf` など既存 SGF

- [ ] **Step 1: デフォルト設定で特定局面を確認**

Run: `python -m katrain_debug --sgf tests/data/panda1.sgf --move 30 --strategy jigo --output text`
Expected:
- `[JigoStrategy] Stage1 query complete` と `Stage2 query complete` のログ
- `Filter: N → M passed` のログ
- `Selected: <座標> (loss=X, hp=Y, score=Z)` の表示

- [ ] **Step 2: Mode B（maintain）に切り替えて挙動差を確認**

Run: `python -m katrain_debug --sgf tests/data/panda1.sgf --move 30 --strategy jigo --settings jigo_mode=maintain --output text`
Expected: Mode A と異なる手が選ばれる可能性あり（範囲内局面なら differ、範囲外なら同じ）

- [ ] **Step 3: フィルタを厳しくしてフォールバック発動を確認**

Run: `python -m katrain_debug --sgf tests/data/panda1.sgf --move 30 --strategy jigo --settings max_loss_per_move=0.5 min_human_policy=0.5 --output text`
Expected: `Fallback triggered` のログが出る（極端な設定のため）

- [ ] **Step 4: JSON 出力で structure を確認**

Run: `python -m katrain_debug --sgf tests/data/panda1.sgf --move 30 --strategy jigo --output json 2>/dev/null | python -c "import sys,json; d=json.loads(sys.stdin.read()); print('selected_move:', d.get('selected_move'))"`
Expected: JSON parse 成功、`selected_move` が None ではない

---

## Task 10: バッチ評価で 3 run 平均比較

**Files:**
- 読み取り: `tests/data/panda1.sgf`（白番が負けすぎていない棋譜）

- [ ] **Step 1: Mode A (natural) を 3 run 実行**

```bash
for i in 1 2 3; do
  python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --batch --player W \
    --settings jigo_mode=natural > /tmp/jigo_natural_run$i.txt 2>&1
  echo "=== run $i ==="
  grep -E "Overall|Mean loss|Top1" /tmp/jigo_natural_run$i.txt
done
```
Expected: 3 run 分の Overall/Mean loss/Top1 一致率が出力される

- [ ] **Step 2: Mode B (maintain) を 3 run 実行**

```bash
for i in 1 2 3; do
  python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --batch --player W \
    --settings jigo_mode=maintain > /tmp/jigo_maintain_run$i.txt 2>&1
  echo "=== run $i ==="
  grep -E "Overall|Mean loss|Top1" /tmp/jigo_maintain_run$i.txt
done
```
Expected: 3 run 分の結果

- [ ] **Step 3: 合格基準を満たすか手動でチェック**

各 run の出力を見て以下を確認（ユーザと共有）：
- [ ] Notable Divergences に loss > 8.4 の手がないこと（fallback 最大緩和後の上限）
- [ ] Notable Divergences に humanPolicy ≒ 0 の「打つわけがない」手がないこと
- [ ] Mean loss が HumanStyle 9段相当（経験則で約 0.3〜0.6 目）の範囲に収まっている

問題があればパラメータ調整（`max_loss_per_move` を下げる等）を検討する。

---

## Task 11: GUI 実対局テスト（手動）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（`debug_level` 切り替え）

- [ ] **Step 1: デバッグモード有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` を `1` に変更。

- [ ] **Step 2: KaTrain 起動**

Run: `python -m katrain`

- [ ] **Step 3: Jigo モードで対局**

- AI モードを「持碁」に設定
- 可能なら +30 目程度リードする局面を作って終局まで打たせる
- コンソールログで以下を確認:
  - `[JigoStrategy] Stage1 query complete` / `Stage2 query complete`
  - `Mode: natural, lead=X, in_range=True/False`
  - `Selected: <move> (loss=X, hp=Y, score=Z)`
  - 各 loss が 5.6 以下（fallback 発動時のみ 8.4 以下）
  - 最終スコア差が 0.5〜10.0 目範囲に収束するか

- [ ] **Step 4: maintain モードでも同じ流れで対局**

GUI 設定画面で `jigo_mode` を `maintain` に変更し、同じ手順を繰り返す。

- [ ] **Step 5: `debug_level` を 0 に戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` を `0` に戻す。

---

## Task 12: 最終確認とマージ前チェック

- [ ] **Step 1: 全テスト再実行**

Run: `pytest --ignore=tests/test_ai.py`
Expected: all PASS（`test_ai.py` はhumanSLモデル依存のため除外）

- [ ] **Step 2: 変更ファイル一覧を確認**

Run: `git log --oneline master..HEAD`
Expected: Task 2/4/5/7/8 のコミットが順に並ぶ

- [ ] **Step 3: 差分の最終レビュー**

Run: `git diff master..HEAD -- katrain/core/ai.py katrain/core/constants.py katrain/config.json`
- 既存 `JigoStrategy` が完全に新ロジックに置き換わっているか
- `_jigo_*` helper 関数 3 つが追加されているか
- `AI_OPTION_VALUES` / `AI_OPTION_ORDER` に 4 キーずつ追加されているか
- `katrain/config.json` の `ai:jigo` セクションに 4 キー追加されているか

- [ ] **Step 4: ブランチマージの方針確認（ユーザに委ねる）**

master 直打ちか、`feat/jigo-humanlike` ブランチでPR化するかはユーザ判断。現在のリポジトリのワークフロー（recent merges: `Merge branch 'feat/hunt-dead-stone-avoidance'`）に従ってブランチ運用する場合は事前にブランチ切り替えること。
