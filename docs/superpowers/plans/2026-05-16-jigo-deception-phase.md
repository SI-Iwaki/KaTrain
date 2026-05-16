# Jigo 油断誘発フェーズ機構 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JigoStrategy に `jigo_deception` オプトインフラグを追加し、序中盤で 2〜3 目劣勢を演出して終盤で target_score に収束させる Phase 0/1/2/3 機構を実装する。

**Architecture:** `JigoStrategy.generate_move()` の Stage 1/2 クエリ前に Phase 解決層を挿入。Phase 1/2 では `target_score` / `target_score_max` を一時的に負の値へ上書きし、既存の `_jigo_select_move` 4 分岐ロジックを再利用して「target ≈ -3 目の手」を選ばせる。安全弁（±5 目で Phase 3 ジャンプ）と `jigo_large_lead_max_loss` の Phase 1/2 中スキップで暴走を防ぐ。

**Tech Stack:** Python 3.12, pytest, KataGo (v1.16.4 TensorRT), Kivy (GUI 表示)

**Spec:** `docs/superpowers/specs/2026-05-16-jigo-deception-phase-design.md`

---

## File Structure

| ファイル | 役割 | 変更タイプ |
|---|---|---|
| `katrain/core/ai.py` | Phase 解決定数/関数の追加、`JigoStrategy.generate_move()` への組み込み | Modify |
| `tests/test_jigo_deception.py` | `_jigo_resolve_phase` のユニットテスト（新規） | Create |
| `katrain/core/constants.py` | `AI_OPTION_VALUES[AI_JIGO]` に `jigo_deception: "bool"` 追加 | Modify |
| `katrain/config.json` | パッケージ同梱デフォルト値 | Modify |
| `C:\Users\iwaki\.katrain\config.json` | ユーザーローカル設定（**メインセッションで直接 Edit**） | Modify |
| `.claude/rules/ai-parameters.md` | JigoStrategy パラメータテーブル更新（**サブエージェント経由**） | Modify |

---

## Task 1: Phase 解決定数 + ヘルパー関数を追加（TDD）

**Files:**
- Create: `tests/test_jigo_deception.py`
- Modify: `katrain/core/ai.py` (between `JIGO_LARGE_LEAD_9X9_CAP` definition at line 773 and `_jigo_compute_effective_max_loss` at line 776)

### - [ ] Step 1.1: 失敗するテストファイルを作成

Create `tests/test_jigo_deception.py`:

```python
# tests/test_jigo_deception.py
"""Jigo deception Phase 解決のユニットテスト"""
import pytest

from katrain.core.ai import (
    JIGO_DECEPTION_PHASE_TABLE,
    JIGO_DECEPTION_TARGETS,
    JIGO_DECEPTION_SAFETY_OVERSHOOT,
    _jigo_resolve_phase,
)


class TestJigoPhaseBoundaries19:
    """19 路盤の手数ベース phase 境界"""

    def test_move_1_is_phase0(self):
        assert _jigo_resolve_phase(19, 1, None) == "phase0"

    def test_move_29_is_phase0(self):
        assert _jigo_resolve_phase(19, 29, None) == "phase0"

    def test_move_30_is_phase1(self):
        assert _jigo_resolve_phase(19, 30, None) == "phase1"

    def test_move_79_is_phase1(self):
        assert _jigo_resolve_phase(19, 79, None) == "phase1"

    def test_move_80_is_phase2(self):
        assert _jigo_resolve_phase(19, 80, None) == "phase2"

    def test_move_149_is_phase2(self):
        assert _jigo_resolve_phase(19, 149, None) == "phase2"

    def test_move_150_is_phase3(self):
        assert _jigo_resolve_phase(19, 150, None) == "phase3"

    def test_move_250_is_phase3(self):
        assert _jigo_resolve_phase(19, 250, None) == "phase3"


class TestJigoPhaseBoundaries13:
    """13 路盤の手数ベース phase 境界"""

    def test_move_16_is_phase0(self):
        assert _jigo_resolve_phase(13, 16, None) == "phase0"

    def test_move_17_is_phase1(self):
        assert _jigo_resolve_phase(13, 17, None) == "phase1"

    def test_move_44_is_phase2(self):
        assert _jigo_resolve_phase(13, 44, None) == "phase2"

    def test_move_83_is_phase3(self):
        assert _jigo_resolve_phase(13, 83, None) == "phase3"


class TestJigoPhaseBoundaries9:
    """9 路盤の手数ベース phase 境界"""

    def test_move_7_is_phase0(self):
        assert _jigo_resolve_phase(9, 7, None) == "phase0"

    def test_move_8_is_phase1(self):
        assert _jigo_resolve_phase(9, 8, None) == "phase1"

    def test_move_20_is_phase2(self):
        assert _jigo_resolve_phase(9, 20, None) == "phase2"

    def test_move_38_is_phase3(self):
        assert _jigo_resolve_phase(9, 38, None) == "phase3"


class TestJigoSafetyValve:
    """安全弁: ±5 目で phase3 ジャンプ"""

    def test_phase1_overshoot_jumps_to_phase3(self):
        # 19路 phase1 target_max=-2.0、+5 超過 → lead > 3.0 で phase3
        assert _jigo_resolve_phase(19, 30, current_lead=3.5) == "phase3"

    def test_phase1_undershoot_jumps_to_phase3(self):
        # 19路 phase1 target_max=-2.0、-5 不足 → lead < -7.0 で phase3
        assert _jigo_resolve_phase(19, 30, current_lead=-7.5) == "phase3"

    def test_phase1_in_range_stays(self):
        # lead が ±5 目以内なら phase1 維持
        assert _jigo_resolve_phase(19, 30, current_lead=0.0) == "phase1"
        assert _jigo_resolve_phase(19, 30, current_lead=-4.0) == "phase1"

    def test_phase2_overshoot_jumps_to_phase3(self):
        # 19路 phase2 target_max=-0.5、+5 超過 → lead > 4.5 で phase3
        assert _jigo_resolve_phase(19, 80, current_lead=5.0) == "phase3"

    def test_phase2_undershoot_jumps_to_phase3(self):
        # 19路 phase2 target_max=-0.5、-5 不足 → lead < -5.5 で phase3
        assert _jigo_resolve_phase(19, 80, current_lead=-6.0) == "phase3"

    def test_phase0_no_safety_valve(self):
        # phase0 は安全弁発動しない（巨大 lead でも phase0 維持）
        assert _jigo_resolve_phase(19, 10, current_lead=100.0) == "phase0"
        assert _jigo_resolve_phase(19, 10, current_lead=-100.0) == "phase0"

    def test_phase3_no_safety_valve(self):
        # phase3 は終局フェーズ、lead 変動で再ジャンプしない
        assert _jigo_resolve_phase(19, 200, current_lead=100.0) == "phase3"
        assert _jigo_resolve_phase(19, 200, current_lead=-100.0) == "phase3"

    def test_last_lead_none_skips_safety_valve(self):
        # 初手や lead 未取得時は安全弁スキップ
        assert _jigo_resolve_phase(19, 30, current_lead=None) == "phase1"


class TestJigoUnknownBoardSize:
    """未対応盤面サイズは 19 路にフォールバック"""

    def test_board_size_15_falls_back_to_19(self):
        assert _jigo_resolve_phase(15, 30, None) == "phase1"
        assert _jigo_resolve_phase(15, 150, None) == "phase3"

    def test_board_size_7_falls_back_to_19(self):
        # 7 路の 30 手目 → 19 路テーブルで phase1
        assert _jigo_resolve_phase(7, 30, None) == "phase1"


class TestJigoDeceptionTargetsLookup:
    """JIGO_DECEPTION_TARGETS の中身検証"""

    def test_19_phase0_is_none(self):
        assert JIGO_DECEPTION_TARGETS[(19, "phase0")] is None

    def test_19_phase1_targets(self):
        assert JIGO_DECEPTION_TARGETS[(19, "phase1")] == (-3.0, -2.0)

    def test_19_phase2_targets(self):
        assert JIGO_DECEPTION_TARGETS[(19, "phase2")] == (-1.5, -0.5)

    def test_19_phase3_is_none(self):
        assert JIGO_DECEPTION_TARGETS[(19, "phase3")] is None

    def test_13_phase1_targets(self):
        assert JIGO_DECEPTION_TARGETS[(13, "phase1")] == (-2.0, -1.0)

    def test_13_phase2_targets(self):
        assert JIGO_DECEPTION_TARGETS[(13, "phase2")] == (-1.0, 0.0)

    def test_9_phase1_targets(self):
        assert JIGO_DECEPTION_TARGETS[(9, "phase1")] == (-1.5, -0.5)

    def test_9_phase2_targets(self):
        assert JIGO_DECEPTION_TARGETS[(9, "phase2")] == (-0.5, 0.0)

    def test_safety_overshoot_value(self):
        assert JIGO_DECEPTION_SAFETY_OVERSHOOT == 5.0


class TestJigoPhaseTableStructure:
    """JIGO_DECEPTION_PHASE_TABLE の構造検証"""

    def test_19_has_three_phases(self):
        assert len(JIGO_DECEPTION_PHASE_TABLE[19]) == 3

    def test_19_boundaries(self):
        assert JIGO_DECEPTION_PHASE_TABLE[19] == [
            (30, "phase1"), (80, "phase2"), (150, "phase3"),
        ]

    def test_13_boundaries(self):
        assert JIGO_DECEPTION_PHASE_TABLE[13] == [
            (17, "phase1"), (44, "phase2"), (83, "phase3"),
        ]

    def test_9_boundaries(self):
        assert JIGO_DECEPTION_PHASE_TABLE[9] == [
            (8, "phase1"), (20, "phase2"), (38, "phase3"),
        ]
```

### - [ ] Step 1.2: テストを実行して ImportError で失敗することを確認

Run:
```bash
pytest tests/test_jigo_deception.py -v
```

Expected: `ImportError: cannot import name 'JIGO_DECEPTION_PHASE_TABLE' from 'katrain.core.ai'` （定数も関数もまだ存在しない）

### - [ ] Step 1.3: `katrain/core/ai.py` に定数と関数を実装

Open `katrain/core/ai.py` and locate line 773 (`JIGO_LARGE_LEAD_9X9_CAP = 5.0`). Insert the following **after** that line and **before** `def _jigo_compute_effective_max_loss(`:

```python
# ----------------------------------------------------------------
# Jigo deception Phase 機構
# ----------------------------------------------------------------
# 手数ベースの phase 境界（盤面サイズ → [(境界手数, phase 名), ...]）
JIGO_DECEPTION_PHASE_TABLE = {
    19: [(30, "phase1"), (80, "phase2"), (150, "phase3")],
    13: [(17, "phase1"), (44, "phase2"), (83, "phase3")],
    9:  [(8,  "phase1"), (20, "phase2"), (38, "phase3")],
}

# (board_size, phase) → (target_score, target_score_max) または None
# None は「ユーザ設定 target_score / target_score_max をそのまま使用」を意味
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

# 過剰優勢/過剰劣勢の安全弁閾値（目数）
JIGO_DECEPTION_SAFETY_OVERSHOOT = 5.0


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
        # 安全弁判定用 target_max を自己ルックアップ（未登録 board_size は 19 路フォールバック）
        targets = JIGO_DECEPTION_TARGETS.get((board_size, base_phase))
        if targets is None:
            targets = JIGO_DECEPTION_TARGETS.get((19, base_phase))
        if targets is not None:
            _, base_target_max = targets
            if current_lead > base_target_max + JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"  # 過剰優勢: 早期に勝ちにいく
            if current_lead < base_target_max - JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"  # 過剰劣勢: 回復に専念
    return base_phase
```

### - [ ] Step 1.4: テストが全 PASS することを確認

Run:
```bash
pytest tests/test_jigo_deception.py -v
```

Expected: All tests PASS (32 tests across 5 classes)

### - [ ] Step 1.5: 既存テストへのレグレッションが無いことを確認

Run:
```bash
pytest tests/test_jigo.py -v
```

Expected: All existing jigo tests PASS（追加した定数・関数は既存パスを変更しないため影響なし）

### - [ ] Step 1.6: コミット

```bash
git add katrain/core/ai.py tests/test_jigo_deception.py
git commit -m "$(cat <<'EOF'
feat(jigo-deception): Phase 解決定数とヘルパー関数を追加

JIGO_DECEPTION_PHASE_TABLE / JIGO_DECEPTION_TARGETS / JIGO_DECEPTION_SAFETY_OVERSHOOT
を追加し、_jigo_resolve_phase で手数 + 安全弁による phase 判定を実装。19/13/9 路
の境界と過剰優勢/劣勢のジャンプ条件を網羅したユニットテストを tests/test_jigo_deception.py
に追加（32 ケース、全 PASS）。本コミットでは JigoStrategy 本体への組み込みは未実施。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `JigoStrategy.generate_move()` に Phase 解決層を組み込み

**Files:**
- Modify: `katrain/core/ai.py:857-1118` (`JigoStrategy.generate_move`)

### - [ ] Step 2.1: 設定読み込み部分に `jigo_deception` キーを追加

Locate `katrain/core/ai.py` around line 880 (after `equivalent_epsilon = self.settings.get("jigo_equivalent_epsilon", 0.5)`). Insert immediately after:

```python
        deception_enabled = self.settings.get("jigo_deception", False)
```

And update the existing log statement (lines 881-888) to include `deception_enabled`:

```python
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}, "
            f"profile={base_profile}, dynamic_rank={dynamic_rank}, "
            f"large_lead_delta={large_lead_delta}, large_lead_max_loss={large_lead_max_loss}, "
            f"equivalent_epsilon={equivalent_epsilon}, deception={deception_enabled}",
            OUTPUT_DEBUG,
        )
```

### - [ ] Step 2.2: Phase 解決ブロックを追加

After the log statement above (and before `sign = self.cn.player_sign(self.cn.next_player)` at line 890), insert:

```python
        # ---- Phase 解決（jigo_deception=True 時のみ有効値を上書き） ----
        eff_target = target_score
        eff_target_max = target_score_max
        eff_mode = mode
        eff_large_lead_delta = large_lead_delta
        phase = "phase0"
        if deception_enabled:
            # board_size は既存呼び出し規約に合わせ max(width, height) を採用
            board_size_for_phase = max(self.game.board_size)
            move_num = self.cn.depth
            last_lead = getattr(self.game, "_jigo_last_current_lead", None)
            phase = _jigo_resolve_phase(board_size_for_phase, move_num, last_lead)
            overrides = JIGO_DECEPTION_TARGETS.get((board_size_for_phase, phase))
            if overrides is None:
                overrides = JIGO_DECEPTION_TARGETS.get((19, phase))
            if overrides is not None:
                eff_target, eff_target_max = overrides
            # Phase 1/2 中は mode を maintain に固定（natural だと in_range で target に寄らない）
            if phase in ("phase1", "phase2"):
                eff_mode = "maintain"
                # Phase 1/2 中は large_lead 緩和を無効化（小さい eff_target_max で誤発動を防ぐ）
                eff_large_lead_delta = float("inf")
            self.game.katrain.log(
                f"[JigoStrategy] Deception: move={move_num}, phase={phase}, "
                f"eff_target={eff_target}, eff_target_max={eff_target_max}, "
                f"eff_mode={eff_mode}, last_lead={last_lead}",
                OUTPUT_DEBUG,
            )
```

### - [ ] Step 2.3: dynamic_rank 呼び出しの `target_score_max` を `eff_target_max` に置換

Locate the existing `_select_rank_by_lead` call (around line 899-902):

```python
            human_profile = _select_rank_by_lead(
                last_lead, target_score_max, base_profile,
                delta_1=delta_1, delta_2=delta_2,
            )
```

Replace `target_score_max` with `eff_target_max`:

```python
            human_profile = _select_rank_by_lead(
                last_lead, eff_target_max, base_profile,
                delta_1=delta_1, delta_2=delta_2,
            )
```

### - [ ] Step 2.4: `_jigo_compute_effective_max_loss` 呼び出しを差し替え

Locate the existing call (lines 1037-1044):

```python
        effective_max_loss = _jigo_compute_effective_max_loss(
            current_lead=current_lead,
            target_score_max=target_score_max,
            base_max_loss=max_loss,
            large_lead_delta=large_lead_delta,
            large_lead_max_loss=large_lead_max_loss,
            board_size=board_size,
        )
```

Replace `target_score_max` with `eff_target_max` and `large_lead_delta` with `eff_large_lead_delta`:

```python
        effective_max_loss = _jigo_compute_effective_max_loss(
            current_lead=current_lead,
            target_score_max=eff_target_max,
            base_max_loss=max_loss,
            large_lead_delta=eff_large_lead_delta,
            large_lead_max_loss=large_lead_max_loss,
            board_size=board_size,
        )
```

### - [ ] Step 2.5: in_range / 鋭手除外 / `_jigo_select_move` 呼び出しを置換

Locate lines 1074-1091:

```python
        # ---- 現在リード & 選択分岐 ----
        in_range = target_score <= current_lead <= target_score_max
        self.game.katrain.log(
            f"[JigoStrategy] Mode: {mode}, lead={current_lead:.2f}, in_range={in_range}",
            OUTPUT_DEBUG,
        )

        # ---- 鋭手除外（圧勝時のみ） ----
        if current_lead > target_score_max:
            before_exclude = len(filtered)
            filtered = _jigo_exclude_sharp_moves(filtered, current_lead)
            self.game.katrain.log(
                f"[JigoStrategy] Sharp-move exclusion: {before_exclude} → {len(filtered)} "
                f"(lead={current_lead:.2f} > target_max={target_score_max})",
                OUTPUT_DEBUG,
            )

        pick = _jigo_select_move(filtered, current_lead, target_score, target_score_max, mode, equivalent_epsilon)
```

Replace with:

```python
        # ---- 現在リード & 選択分岐 ----
        in_range = eff_target <= current_lead <= eff_target_max
        self.game.katrain.log(
            f"[JigoStrategy] Mode: {eff_mode}, lead={current_lead:.2f}, in_range={in_range}",
            OUTPUT_DEBUG,
        )

        # ---- 鋭手除外（圧勝時のみ） ----
        if current_lead > eff_target_max:
            before_exclude = len(filtered)
            filtered = _jigo_exclude_sharp_moves(filtered, current_lead)
            self.game.katrain.log(
                f"[JigoStrategy] Sharp-move exclusion: {before_exclude} → {len(filtered)} "
                f"(lead={current_lead:.2f} > eff_target_max={eff_target_max})",
                OUTPUT_DEBUG,
            )

        pick = _jigo_select_move(filtered, current_lead, eff_target, eff_target_max, eff_mode, equivalent_epsilon)
```

### - [ ] Step 2.6: large lead expansion log の `target_score_max` 参照を更新

Locate lines 1045-1051:

```python
        if effective_max_loss != max_loss:
            self.game.katrain.log(
                f"[JigoStrategy] Large lead expansion: lead={current_lead:.2f} ≥ "
                f"target_max+{large_lead_delta} = {target_score_max + large_lead_delta:.2f}, "
                f"max_loss: {max_loss} → {effective_max_loss}",
                OUTPUT_DEBUG,
            )
```

Replace with (use eff_* values for accuracy):

```python
        if effective_max_loss != max_loss:
            self.game.katrain.log(
                f"[JigoStrategy] Large lead expansion: lead={current_lead:.2f} ≥ "
                f"eff_target_max+{eff_large_lead_delta} = {eff_target_max + eff_large_lead_delta:.2f}, "
                f"max_loss: {max_loss} → {effective_max_loss}",
                OUTPUT_DEBUG,
            )
```

### - [ ] Step 2.7: ai_thoughts 文字列の mode 表示を更新

Locate lines 1098-1101:

```python
        ai_thoughts = (
            f"Jigo (mode={mode}, lead={current_lead:.1f}): chose {pick['move']} "
            f"(loss={pick['loss']:.2f}, hp={pick['hp']:.3f}, score={pick['score']:.2f})"
        )
```

Replace with:

```python
        ai_thoughts = (
            f"Jigo (mode={eff_mode}, phase={phase}, lead={current_lead:.1f}): chose {pick['move']} "
            f"(loss={pick['loss']:.2f}, hp={pick['hp']:.3f}, score={pick['score']:.2f})"
        )
```

### - [ ] Step 2.8: 既存テストでレグレッションが無いことを確認

Run:
```bash
pytest tests/test_jigo.py tests/test_jigo_deception.py -v
```

Expected: All tests PASS. `test_jigo.py` は pure-function テストで `generate_move` を呼ばないため影響を受けない。`test_jigo_deception.py` は `_jigo_resolve_phase` のみテストするので Task 1 と同じく全 PASS。

### - [ ] Step 2.9: humanSL モデル未配置の環境では `test_ai.py` を除外して検証

Run:
```bash
pytest --ignore=tests/test_ai.py -v
```

Expected: All tests PASS（CLAUDE.md「やってはいけないこと」記載通り、humanSL モデル未配置環境では test_ai.py を除外）

### - [ ] Step 2.10: コミット

```bash
git add katrain/core/ai.py
git commit -m "$(cat <<'EOF'
feat(jigo-deception): JigoStrategy.generate_move に Phase 解決層を組み込み

jigo_deception=true で Phase 0/1/2/3 に応じて target_score / target_score_max を
内部上書き。Phase 1/2 中は mode を maintain に強制し、large_lead 緩和を無効化
（eff_large_lead_delta=inf）。既存 _jigo_select_move / _jigo_compute_effective_max_loss
/ _select_rank_by_lead には effective 値を渡す。デフォルト値は false なので
既存ユーザの挙動は変わらない。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `AI_OPTION_VALUES` に `jigo_deception` を追加

**Files:**
- Modify: `katrain/core/constants.py:197-200` および `:252-257`

### - [ ] Step 3.1: `AI_OPTION_VALUES[AI_JIGO]` に `jigo_deception: "bool"` を追加

Locate `katrain/core/constants.py` around line 197-200:

```python
    "jigo_dynamic_rank": "bool",
    "jigo_large_lead_delta": [3.0, 5.0, 7.0, 10.0],
    "jigo_large_lead_max_loss": [6.0, 7.0, 8.0, 9.0, 10.0],
    "jigo_equivalent_epsilon": [0.0, 0.3, 0.5, 1.0],
}
```

Insert `"jigo_deception": "bool",` **after** `"jigo_equivalent_epsilon": [...]`:

```python
    "jigo_dynamic_rank": "bool",
    "jigo_large_lead_delta": [3.0, 5.0, 7.0, 10.0],
    "jigo_large_lead_max_loss": [6.0, 7.0, 8.0, 9.0, 10.0],
    "jigo_equivalent_epsilon": [0.0, 0.3, 0.5, 1.0],
    "jigo_deception": "bool",
}
```

### - [ ] Step 3.2: AI_OPTION_ORDER 相当の辞書に表示順を追加

Locate `katrain/core/constants.py` around line 252-257:

```python
    "jigo_mode": 4,
    "human_profile": 5,
    "jigo_dynamic_rank": 6,
    "jigo_large_lead_delta": 7,
    "jigo_large_lead_max_loss": 8,
    "jigo_equivalent_epsilon": 9,
}
```

Insert `"jigo_deception": 10,` **before** the closing `}`:

```python
    "jigo_mode": 4,
    "human_profile": 5,
    "jigo_dynamic_rank": 6,
    "jigo_large_lead_delta": 7,
    "jigo_large_lead_max_loss": 8,
    "jigo_equivalent_epsilon": 9,
    "jigo_deception": 10,
}
```

### - [ ] Step 3.3: 起動して import エラーが無いことを確認

Run:
```bash
python -c "from katrain.core.constants import AI_OPTION_VALUES, AI_JIGO; print('jigo_deception' in AI_OPTION_VALUES[AI_JIGO])"
```

Expected output: `True`

### - [ ] Step 3.4: コミット

```bash
git add katrain/core/constants.py
git commit -m "$(cat <<'EOF'
feat(jigo-deception): constants.py の AI_OPTION_VALUES に jigo_deception を追加

GUI 側で Jigo モード設定としてチェックボックス表示されるよう "bool" 型で登録。
表示順は既存 jigo_equivalent_epsilon(9) の次の 10 を割り当て。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: パッケージ同梱 `config.json` にデフォルト値追加

**Files:**
- Modify: `katrain/config.json:108-113`

### - [ ] Step 4.1: Jigo セクションに `jigo_deception: false` を追加

Locate `katrain/config.json` around lines 108-113:

```json
            "human_profile": "rank_9d",
            "jigo_dynamic_rank": false,
            "jigo_large_lead_delta": 5.0,
            "jigo_large_lead_max_loss": 8.0,
            "jigo_equivalent_epsilon": 0.5
        },
```

Add `"jigo_deception": false` **after** `"jigo_equivalent_epsilon": 0.5` (note trailing comma added):

```json
            "human_profile": "rank_9d",
            "jigo_dynamic_rank": false,
            "jigo_large_lead_delta": 5.0,
            "jigo_large_lead_max_loss": 8.0,
            "jigo_equivalent_epsilon": 0.5,
            "jigo_deception": false
        },
```

### - [ ] Step 4.2: JSON 構文が壊れていないか確認

Run:
```bash
python -c "import json; json.load(open('katrain/config.json'))" && echo OK
```

Expected output: `OK`

### - [ ] Step 4.3: コミット

```bash
git add katrain/config.json
git commit -m "$(cat <<'EOF'
feat(jigo-deception): パッケージ config.json に jigo_deception=false を追加

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: ユーザーローカル `config.json` に `jigo_deception` キー追加（**メインセッションで直接 Edit**）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`

**重要**: CLAUDE.md「やってはいけないこと」: **このファイルは必ずメインセッションで直接 Edit する**。サブエージェントに委任すると成功報告されても反映されないことがある。

### - [ ] Step 5.1: 現在の jigo セクションを Read で確認

Read tool で `C:\Users\iwaki\.katrain\config.json` を開き、`"ai"` → `"ai:jigo"` セクションを確認。`jigo_equivalent_epsilon` が存在するはず。

### - [ ] Step 5.2: `jigo_deception: false` を追加

Edit tool で `"jigo_equivalent_epsilon": <現在値>` の行末にカンマを追加し、次行に `"jigo_deception": false` を挿入。形式はパッケージ同梱 config.json と同じ。

### - [ ] Step 5.3: JSON 構文確認

Run:
```bash
python -c "import json; cfg=json.load(open(r'C:\Users\iwaki\.katrain\config.json')); print('jigo_deception' in cfg['ai']['ai:jigo'])"
```

Expected output: `True`

### - [ ] Step 5.4: KaTrain GUI 起動確認（オプション、CLI のみで進めるならスキップ可）

```bash
python -m katrain
```

GUI が起動し、「AI 設定」→「Jigo」セクションに新しい「jigo_deception」チェックボックスが表示されることを確認。確認後 KaTrain を終了。

**注意**: コミットは無し（このファイルは git 管理外）。

---

## Task 6: `.claude/rules/ai-parameters.md` を更新（**サブエージェント経由**）

**Files:**
- Modify: `.claude/rules/ai-parameters.md`

**重要**: CLAUDE.md「やってはいけないこと」: `.claude/rules/` 配下の編集は `settings.local.json` で許可していても拒否されることがあるため、**サブエージェント（Agent tool）経由で編集・コミット**する。

### - [ ] Step 6.1: サブエージェントに編集を委任

Agent tool（subagent_type: `general-purpose`）で以下のプロンプトを与える:

> `.claude/rules/ai-parameters.md` を編集してください。「持碁戦略（JigoStrategy）」セクションのパラメータテーブルに以下の行を末尾に追加してください:
>
> | jigo_deception | false | 油断誘発 Phase 機構を有効化。Phase 0 (1-29 手) は通常 Jigo、Phase 1 (30-79 手) で target=-3.0/-2.0、Phase 2 (80-149 手) で target=-1.5/-0.5、Phase 3 (150 手-) で user 設定復帰。安全弁 ±5 目で Phase 3 強制ジャンプ。13/9 路は手数比例スケール。Spec: `docs/superpowers/specs/2026-05-16-jigo-deception-phase-design.md` |
>
> 編集後 `git add .claude/rules/ai-parameters.md && git commit -m "docs(jigo-deception): ai-parameters.md に jigo_deception パラメータを追記"` でコミットしてください。コミットメッセージ末尾に `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` を追加してください。

### - [ ] Step 6.2: サブエージェントの編集結果を確認

Run:
```bash
git log -1 --stat .claude/rules/ai-parameters.md
```

Expected: 直前のコミットが `.claude/rules/ai-parameters.md` の修正であること。

```bash
grep jigo_deception .claude/rules/ai-parameters.md
```

Expected: `jigo_deception` を含む行が 1 行ヒット。

---

## Task 7: CLI 検証（各 Phase の挙動確認）

**Files:**
- Use only: `tests/data/panda1.sgf`, `katrain_debug` CLI

### - [ ] Step 7.1: Phase 0 の挙動確認（手数 15、定石期間）

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --settings jigo_deception=true --move 15 --output text
```

Expected: ログに `phase=phase0` が出力され、eff_target / eff_target_max が user 設定値 (0.5 / 10.0 等) のままになっていること。選択手は通常 Jigo と同等の挙動。

### - [ ] Step 7.2: Phase 1 の挙動確認（手数 35、中盤入口）

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --settings jigo_deception=true --move 35 --output text
```

Expected: ログに `phase=phase1, eff_target=-3.0, eff_target_max=-2.0, eff_mode=maintain` が出力。選択手の score が現在 lead より低め（理想的には score ≈ -3 付近）になる傾向。

### - [ ] Step 7.3: Phase 2 の挙動確認（手数 90）

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --settings jigo_deception=true --move 90 --output text
```

Expected: ログに `phase=phase2, eff_target=-1.5, eff_target_max=-0.5` が出力。

### - [ ] Step 7.4: Phase 3 の挙動確認（手数 160、終盤入口）

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --settings jigo_deception=true --move 160 --output text
```

Expected: ログに `phase=phase3` が出力され、eff_target / eff_target_max が user 設定値復帰。

### - [ ] Step 7.5: 安全弁発動の確認（仮想的に lead を作る）

`panda1.sgf` 内で current_lead が大きく振れる手を探す。または別の SGF (`tests/data/LS vs AG - G4 - English.sgf` 等) で手数 30 付近で大きく lead が振れている局面を `--move N --output json` で確認し、`phase=phase3` ジャンプが発生するかをログで検証。

(検証手段の補足: `cn.depth` ベースで判定するため、安全弁が確実に発動する局面の特定が難しい場合は Task 7 Step 7.5 は省略可能。Task 1 の単体テストで安全弁ロジックは網羅済み。)

### - [ ] Step 7.6: deception=false での既存挙動確認（レグレッション保証）

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --settings jigo_deception=false --move 35 --output text
```

Expected: ログに `phase=phase0` が出力（deception=false なら常に phase0）。選択手は本機能追加前と同じ。

### - [ ] Step 7.7: CLI 検証ログをユーザに報告

各 Step の `[JigoStrategy] Deception:` ログ抜粋と選択手をユーザに報告し、想定通りの挙動か確認を依頼。

---

## Task 8: バッチ評価校正（オプション、ユーザ判断で実施）

**Files:**
- Use only: `katrain_debug --batch`、既存 SGF

**実施判断**: ユーザが「校正実施」と明示した場合のみ実施。デフォルトはスキップ。

### - [ ] Step 8.1: 実施可否をユーザに確認

ユーザに以下を提示:
- batch_eval は 19 路 SGF (panda1.sgf 等) で約 10 分/run、3-run 平均で 30 分かかる
- 校正値: deception=false vs true の 2 条件 × 3 run = 6 run = 約 1 時間
- 校正結果は spec の付録として追記する

ユーザ承認後にのみ Step 8.2 以降を実施。

### - [ ] Step 8.2: 校正実行

```bash
# deception=false (baseline)
for i in 1 2 3; do
  python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo \
    --batch --player W --settings jigo_deception=false \
    --output json > /tmp/jigo_baseline_run${i}.json
done

# deception=true
for i in 1 2 3; do
  python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo \
    --batch --player W --settings jigo_deception=true \
    --output json > /tmp/jigo_deception_run${i}.json
done
```

### - [ ] Step 8.3: 結果集計

各 JSON から `stats.overall.ai_top_move`, `stats.overall.mean_ptloss`, 手数 30/80/150/終局時点の `score_lead` を抽出し、3-run 平均を計算。

### - [ ] Step 8.4: 結果を spec 付録に追記してコミット

`docs/superpowers/specs/2026-05-16-jigo-deception-phase-design.md` 末尾に「校正結果（2026-05-XX）」セクションを追加し、上記集計値を記録。

```bash
git add docs/superpowers/specs/2026-05-16-jigo-deception-phase-design.md
git commit -m "docs(jigo-deception): バッチ評価校正結果を追記"
```

---

## Self-Review チェック

実装計画を spec 全項目と照合して確認:

| Spec 要件 | 対応タスク |
|---|---|
| `_jigo_resolve_phase` 関数追加 | Task 1 |
| `JIGO_DECEPTION_PHASE_TABLE` / `JIGO_DECEPTION_TARGETS` / `JIGO_DECEPTION_SAFETY_OVERSHOOT` 定数追加 | Task 1 |
| 19/13/9 路の手数境界 | Task 1 + Task 7 |
| 安全弁 ±5 目で Phase 3 強制ジャンプ | Task 1（テスト）, Task 2（実装） |
| `JigoStrategy.generate_move()` Phase 解決層挿入 | Task 2 |
| `eff_target` / `eff_target_max` への置換 | Task 2 Step 2.3, 2.4, 2.5 |
| Phase 1/2 中の `eff_mode = "maintain"` 強制 | Task 2 Step 2.2 |
| Phase 1/2 中の `eff_large_lead_delta = inf` 上書き | Task 2 Step 2.2, 2.4 |
| `_select_rank_by_lead` への eff_target_max 引き渡し | Task 2 Step 2.3 |
| `jigo_deception: bool` の AI_OPTION_VALUES 登録 | Task 3 |
| パッケージ config.json デフォルト追加 | Task 4 |
| ユーザーローカル config.json 追加 | Task 5 |
| `.claude/rules/ai-parameters.md` 更新 | Task 6 |
| ユニットテスト（手数境界 / 安全弁 / 未対応盤面） | Task 1 |
| CLI 検証 | Task 7 |
| batch_eval 校正（オプション） | Task 8 |
| i18n は MVP 対象外 | （対応タスクなし、spec の非目標に記載済み） |

**Placeholder scan**: 全タスクで具体的なコード・コマンド・期待出力を記載済み。`TBD` / `add appropriate error handling` 等の placeholder は無し。

**Type consistency**: `eff_target` / `eff_target_max` / `eff_mode` / `eff_large_lead_delta` は Task 2 内で一貫使用。`phase` 変数も Task 2 で初期化済み。`_jigo_resolve_phase` のシグネチャは Task 1（定義）と Task 2（呼び出し）で一致。
