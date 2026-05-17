# JigoStrategy 13路 deception スライダー化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JigoStrategy 油断誘発機構の Phase 境界手数 (3個) と Phase 1/2 の eff_target (2個) を、13路盤限定で GUI スライダーから調整可能にする。

**Architecture:** 既存 `_jigo_resolve_phase` のシグネチャを `phase_table_override` / `target_overrides` の2引数で拡張（デフォルト None で後方互換）。新規ヘルパー `_jigo_resolve_13path_overrides` で Phase 1/2 の eff_target を上書き。`JigoStrategy.generate_move()` で 13路かつ deception=True のとき settings から 5 個の新キーを読んで両関数に渡す。eff_target_max は eff_target + 1.0 で自動算出（既存 1.0 目幅維持）。

**Tech Stack:** Python 3.12, pytest, Kivy GUI, gettext (.po/.mo i18n)

**Spec:** `docs/superpowers/specs/2026-05-17-jigo-deception-13path-sliders-design.md`

---

### Task 1: `_jigo_resolve_phase` に `phase_table_override` 引数追加

**Files:**
- Modify: `katrain/core/ai.py:807-836`
- Test: `tests/test_jigo_deception.py`

- [ ] **Step 1: 失敗するテストを追加**

`tests/test_jigo_deception.py` の末尾に新規クラス追加:

```python
class TestJigoPhaseTableOverride:
    """phase_table_override 引数で境界手数をカスタマイズ"""

    def test_override_replaces_default_table(self):
        # Override で 13路の boundaries を 10/40/100 に変更
        override = [(10, "phase1"), (40, "phase2"), (100, "phase3")]
        # 手数 9 は phase0、10 は phase1
        assert _jigo_resolve_phase(13, 9, None, phase_table_override=override) == "phase0"
        assert _jigo_resolve_phase(13, 10, None, phase_table_override=override) == "phase1"
        # 手数 50 は phase2 (40 <= 50 < 100)
        assert _jigo_resolve_phase(13, 50, None, phase_table_override=override) == "phase2"
        # 手数 100 は phase3
        assert _jigo_resolve_phase(13, 100, None, phase_table_override=override) == "phase3"

    def test_override_none_uses_default_table(self):
        # phase_table_override=None なら既存挙動（17/44/83）
        assert _jigo_resolve_phase(13, 17, None, phase_table_override=None) == "phase1"
        assert _jigo_resolve_phase(13, 44, None, phase_table_override=None) == "phase2"

    def test_order_disorder_no_exception(self):
        # 順序矛盾でも例外なし、ループの「最後にマッチ」が勝つ
        override = [(35, "phase1"), (30, "phase2"), (110, "phase3")]
        # 手数 31: phase1 boundary=35 は False、phase2 boundary=30 は True → phase2
        assert _jigo_resolve_phase(13, 31, None, phase_table_override=override) == "phase2"
        # 手数 36: phase1=True で base=phase1、続けて phase2=True で base=phase2
        assert _jigo_resolve_phase(13, 36, None, phase_table_override=override) == "phase2"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_jigo_deception.py::TestJigoPhaseTableOverride -v`
Expected: FAIL with `TypeError: _jigo_resolve_phase() got an unexpected keyword argument 'phase_table_override'`

- [ ] **Step 3: `_jigo_resolve_phase` シグネチャに `phase_table_override` を追加**

`katrain/core/ai.py:807` の関数定義を以下に置換:

```python
def _jigo_resolve_phase(board_size, move_num, current_lead, phase_table_override=None):
    """手数 + 安全弁から有効 phase を返す。

    Args:
        board_size: 19/13/9 等。テーブル未登録なら 19 路にフォールバック
        move_num: 1-indexed の現在手数（self.cn.depth 相当）
        current_lead: 前ターンの current_lead（None なら安全弁スキップ）
        phase_table_override: 指定すると JIGO_DECEPTION_PHASE_TABLE の代わりに
            このリスト [(境界手数, phase 名), ...] を使う。13路スライダー用。

    Returns:
        "phase0" | "phase1" | "phase2" | "phase3"
    """
    table = phase_table_override if phase_table_override is not None else \
        JIGO_DECEPTION_PHASE_TABLE.get(board_size, JIGO_DECEPTION_PHASE_TABLE[19])
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
                return "phase3"
            if current_lead < base_target_max - JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"

    return base_phase
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_jigo_deception.py -v`
Expected: 全テスト PASS（既存テストも含む）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo_deception.py
git commit -m "feat(jigo-deception): _jigo_resolve_phase に phase_table_override 引数を追加"
```

---

### Task 2: `_jigo_resolve_phase` に `target_overrides` 引数追加（安全弁判定用）

**Files:**
- Modify: `katrain/core/ai.py:807` 以降の `_jigo_resolve_phase`
- Test: `tests/test_jigo_deception.py`

- [ ] **Step 1: 失敗するテストを追加**

`tests/test_jigo_deception.py` の末尾に追加:

```python
class TestJigoTargetOverrides:
    """target_overrides 引数で安全弁の target_max をカスタマイズ"""

    def test_safety_uses_override_target_max_overshoot(self):
        # Phase 1 で override target_max=-1.0、lead=+5.0 → +5.0 > -1.0 + 5.0 (=4.0)
        # → 過剰優勢で phase3 にジャンプ
        targets = {"phase1": (-2.0, -1.0), "phase2": (-1.0, 0.0)}
        result = _jigo_resolve_phase(13, 20, +5.0, target_overrides=targets)
        assert result == "phase3"

    def test_safety_uses_override_target_max_undershoot(self):
        # Phase 2 で override target_max=0.0、lead=-6.0 → -6.0 < 0.0 - 5.0 (=-5.0)
        # → 過剰劣勢で phase3 にジャンプ
        targets = {"phase1": (-2.0, -1.0), "phase2": (-1.0, 0.0)}
        result = _jigo_resolve_phase(13, 50, -6.0, target_overrides=targets)
        assert result == "phase3"

    def test_safety_within_band_keeps_phase(self):
        # Override target_max=-1.0、lead=+2.0 → 2.0 ≤ -1.0 + 5.0 (=4.0)、phase1 維持
        targets = {"phase1": (-2.0, -1.0), "phase2": (-1.0, 0.0)}
        result = _jigo_resolve_phase(13, 20, +2.0, target_overrides=targets)
        assert result == "phase1"

    def test_target_overrides_none_uses_default_targets(self):
        # target_overrides=None なら既存 JIGO_DECEPTION_TARGETS で判定
        # 13路 phase1 default target_max=-1.0、lead=+5.0 → +5.0 > -1.0+5.0=+4.0 → phase3
        result = _jigo_resolve_phase(13, 17, +5.0, target_overrides=None)
        assert result == "phase3"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_jigo_deception.py::TestJigoTargetOverrides -v`
Expected: FAIL with `TypeError: _jigo_resolve_phase() got an unexpected keyword argument 'target_overrides'`

- [ ] **Step 3: `_jigo_resolve_phase` に `target_overrides` 引数を追加**

`katrain/core/ai.py` の `_jigo_resolve_phase` 関数全体を以下で置換（Task 1 の結果に上書き）:

```python
def _jigo_resolve_phase(board_size, move_num, current_lead,
                        phase_table_override=None, target_overrides=None):
    """手数 + 安全弁から有効 phase を返す。

    Args:
        board_size: 19/13/9 等。テーブル未登録なら 19 路にフォールバック
        move_num: 1-indexed の現在手数（self.cn.depth 相当）
        current_lead: 前ターンの current_lead（None なら安全弁スキップ）
        phase_table_override: 指定すると JIGO_DECEPTION_PHASE_TABLE の代わりに
            このリスト [(境界手数, phase 名), ...] を使う。13路スライダー用。
        target_overrides: 指定すると JIGO_DECEPTION_TARGETS の代わりに
            このdict {"phase1": (target, target_max), "phase2": (...)} で
            安全弁の target_max を判定する。13路スライダー用。

    Returns:
        "phase0" | "phase1" | "phase2" | "phase3"
    """
    table = phase_table_override if phase_table_override is not None else \
        JIGO_DECEPTION_PHASE_TABLE.get(board_size, JIGO_DECEPTION_PHASE_TABLE[19])
    base_phase = "phase0"
    for boundary, phase in table:
        if move_num >= boundary:
            base_phase = phase

    # 安全弁は phase1/phase2 のみ
    if base_phase in ("phase1", "phase2") and current_lead is not None:
        base_target_max = None
        if target_overrides is not None and base_phase in target_overrides:
            _, base_target_max = target_overrides[base_phase]
        else:
            targets = JIGO_DECEPTION_TARGETS.get((board_size, base_phase))
            if targets is None:
                targets = JIGO_DECEPTION_TARGETS.get((19, base_phase))
            if targets is not None:
                _, base_target_max = targets
        if base_target_max is not None:
            if current_lead > base_target_max + JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"
            if current_lead < base_target_max - JIGO_DECEPTION_SAFETY_OVERSHOOT:
                return "phase3"

    return base_phase
```

- [ ] **Step 4: 全テストが通ることを確認**

Run: `python -m pytest tests/test_jigo_deception.py -v`
Expected: 全テスト PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo_deception.py
git commit -m "feat(jigo-deception): _jigo_resolve_phase に target_overrides 引数を追加"
```

---

### Task 3: `_jigo_resolve_13path_overrides` 新規追加

**Files:**
- Modify: `katrain/core/ai.py`（`_jigo_resolve_phase` の直後に追加）
- Test: `tests/test_jigo_deception.py`

- [ ] **Step 1: 失敗するテストを追加**

`tests/test_jigo_deception.py` の import 文に追加（先頭の import ブロック）:

```python
from katrain.core.ai import (
    JIGO_DECEPTION_PHASE_TABLE,
    JIGO_DECEPTION_TARGETS,
    JIGO_DECEPTION_SAFETY_OVERSHOOT,
    _jigo_resolve_phase,
    _jigo_resolve_13path_overrides,  # 新規
)
```

末尾に新規クラス追加:

```python
class TestJigo13PathOverrides:
    """_jigo_resolve_13path_overrides の挙動"""

    def test_phase0_passthrough(self):
        # phase0 は default をそのまま返す
        result = _jigo_resolve_13path_overrides("phase0", -3.0, -2.0, {})
        assert result == (-3.0, -2.0)

    def test_phase3_passthrough(self):
        # phase3 も default をそのまま返す
        result = _jigo_resolve_13path_overrides("phase3", 0.5, 10.0, {})
        assert result == (0.5, 10.0)

    def test_phase1_uses_setting(self):
        # phase1 で settings から target を読む、target_max は target+1.0
        settings = {"jigo_deception_13_phase1_target": -3.0}
        result = _jigo_resolve_13path_overrides("phase1", 0.0, 0.0, settings)
        assert result == (-3.0, -2.0)

    def test_phase2_uses_setting(self):
        # phase2 で settings から target を読む
        settings = {"jigo_deception_13_phase2_target": -0.5}
        result = _jigo_resolve_13path_overrides("phase2", 0.0, 0.0, settings)
        assert result == (-0.5, 0.5)

    def test_phase1_setting_missing_uses_default(self):
        # settings に該当キーがなければ default 値 -2.0 を使う
        result = _jigo_resolve_13path_overrides("phase1", 0.0, 0.0, {})
        assert result == (-2.0, -1.0)

    def test_phase2_setting_missing_uses_default(self):
        # settings に該当キーがなければ default 値 -1.0 を使う
        result = _jigo_resolve_13path_overrides("phase2", 0.0, 0.0, {})
        assert result == (-1.0, 0.0)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_jigo_deception.py::TestJigo13PathOverrides -v`
Expected: FAIL with `ImportError: cannot import name '_jigo_resolve_13path_overrides'`

- [ ] **Step 3: `_jigo_resolve_13path_overrides` を実装**

`katrain/core/ai.py` の `_jigo_resolve_phase` 関数の直後（`@register_strategy(AI_JIGO)` の前）に追加:

```python
def _jigo_resolve_13path_overrides(phase, default_target, default_target_max, settings):
    """13路盤の deception 有効時、Phase 1/2 で eff_target/eff_target_max を
    settings (スライダー値) に置換して返す。

    Phase 0/3 は default をそのまま返す（既存挙動）。
    target_max は target + 1.0 で自動算出（既存 1.0 目幅維持）。

    Args:
        phase: "phase0" | "phase1" | "phase2" | "phase3"
        default_target: phase0/phase3 用フォールバック値
        default_target_max: phase0/phase3 用フォールバック値
        settings: JigoStrategy.settings 相当の dict-like

    Returns:
        (eff_target, eff_target_max)
    """
    if phase == "phase1":
        t = settings.get("jigo_deception_13_phase1_target", -2.0)
        return t, t + 1.0
    if phase == "phase2":
        t = settings.get("jigo_deception_13_phase2_target", -1.0)
        return t, t + 1.0
    return default_target, default_target_max
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_jigo_deception.py -v`
Expected: 全テスト PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo_deception.py
git commit -m "feat(jigo-deception): _jigo_resolve_13path_overrides ヘルパーを追加"
```

---

### Task 4: `JigoStrategy.generate_move()` への組み込み

**Files:**
- Modify: `katrain/core/ai.py:954-981`（既存 Phase 解決ブロック）

- [ ] **Step 1: 既存 Phase 解決ブロックを 13路スライダー対応版に置換**

`katrain/core/ai.py:954-981` の以下のブロック:

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

を以下で置換:

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

            # 13路盤限定: スライダー値で phase 境界と target_overrides を構築
            phase_table_override = None
            target_overrides = None
            if board_size_for_phase == 13:
                phase_table_override = [
                    (self.settings.get("jigo_deception_13_phase1_start", 17), "phase1"),
                    (self.settings.get("jigo_deception_13_phase2_start", 44), "phase2"),
                    (self.settings.get("jigo_deception_13_phase3_start", 83), "phase3"),
                ]
                p1_target = self.settings.get("jigo_deception_13_phase1_target", -2.0)
                p2_target = self.settings.get("jigo_deception_13_phase2_target", -1.0)
                target_overrides = {
                    "phase1": (p1_target, p1_target + 1.0),
                    "phase2": (p2_target, p2_target + 1.0),
                }

            phase = _jigo_resolve_phase(
                board_size_for_phase, move_num, last_lead,
                phase_table_override=phase_table_override,
                target_overrides=target_overrides,
            )

            # Phase 1/2 の eff_target/eff_target_max を決定
            if board_size_for_phase == 13:
                eff_target, eff_target_max = _jigo_resolve_13path_overrides(
                    phase, target_score, target_score_max, self.settings
                )
            else:
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
                f"eff_mode={eff_mode}, last_lead={last_lead}, "
                f"board={board_size_for_phase}, sliders={target_overrides is not None}",
                OUTPUT_DEBUG,
            )
```

- [ ] **Step 2: 構文エラーなく import できることを確認**

Run: `python -c "from katrain.core.ai import JigoStrategy; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 既存テストが回帰していないことを確認**

Run: `python -m pytest tests/test_jigo_deception.py tests/test_jigo.py -v`
Expected: 全テスト PASS

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat(jigo-deception): JigoStrategy.generate_move に13路スライダー読み込みを統合"
```

---

### Task 5: `constants.py` に 5 キー追加

**Files:**
- Modify: `katrain/core/constants.py:184-202`（AI_OPTION_VALUES の JigoStrategy セクション）
- Modify: `katrain/core/constants.py:249-260`（AI_OPTION_ORDER の jigo セクション）

- [ ] **Step 1: `AI_OPTION_VALUES` に 5 キーを追加**

`katrain/core/constants.py:201`（`"jigo_deception": "bool",` の直後、`}` の前）に以下を追加:

```python
    "jigo_deception_13_phase1_start": [10, 17, 25, 35],
    "jigo_deception_13_phase2_start": [30, 44, 55, 70],
    "jigo_deception_13_phase3_start": [70, 83, 95, 110],
    "jigo_deception_13_phase1_target": [-1.0, -2.0, -3.0, -4.0],
    "jigo_deception_13_phase2_target": [-0.5, -1.0, -1.5, -2.0],
```

- [ ] **Step 2: `AI_OPTION_ORDER` に 5 キーを追加**

`katrain/core/constants.py:259`（`"jigo_deception": 10,` の直後、`}` の前）に以下を追加:

```python
    "jigo_deception_13_phase1_start": 11,
    "jigo_deception_13_phase2_start": 12,
    "jigo_deception_13_phase3_start": 13,
    "jigo_deception_13_phase1_target": 14,
    "jigo_deception_13_phase2_target": 15,
```

- [ ] **Step 3: 構文エラーなく import できることを確認**

Run: `python -c "from katrain.core.constants import AI_OPTION_VALUES, AI_OPTION_ORDER; assert 'jigo_deception_13_phase1_start' in AI_OPTION_VALUES; assert AI_OPTION_ORDER['jigo_deception_13_phase2_target'] == 15; print('OK')"`
Expected: `OK`

- [ ] **Step 4: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat(jigo-deception): 13路スライダー5キーを AI_OPTION_VALUES/ORDER に追加"
```

---

### Task 6: パッケージ `katrain/config.json` にデフォルト値追加

**Files:**
- Modify: `katrain/config.json:113`（`ai:jigo` セクション末尾）

- [ ] **Step 1: `ai:jigo` セクションに 5 キーを追加**

`katrain/config.json:113` の `"jigo_deception": false` を以下で置換:

```json
            "jigo_deception": false,
            "jigo_deception_13_phase1_start": 17,
            "jigo_deception_13_phase2_start": 44,
            "jigo_deception_13_phase3_start": 83,
            "jigo_deception_13_phase1_target": -2.0,
            "jigo_deception_13_phase2_target": -1.0
```

- [ ] **Step 2: JSON が正しいことを確認**

Run: `python -c "import json; data = json.load(open('katrain/config.json')); print(data['ai']['ai:jigo']['jigo_deception_13_phase2_target'])"`
Expected: `-1.0`

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat(jigo-deception): パッケージ config.json に13路スライダーのデフォルト値を追加"
```

---

### Task 7: ユーザーローカル `C:\Users\iwaki\.katrain\config.json` にデフォルト値追加

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json:113`（`ai:jigo` セクション末尾）

> **重要**: このファイルは CLAUDE.md の「やってはいけないこと」により**サブエージェントに委任禁止**。メインセッションの Edit ツールで直接編集する。

- [ ] **Step 1: ユーザー config の `ai:jigo` セクションに 5 キーを追加**

`C:\Users\iwaki\.katrain\config.json:113` の `"jigo_deception": true` を以下で置換:

```json
            "jigo_deception": true,
            "jigo_deception_13_phase1_start": 17,
            "jigo_deception_13_phase2_start": 44,
            "jigo_deception_13_phase3_start": 83,
            "jigo_deception_13_phase1_target": -2.0,
            "jigo_deception_13_phase2_target": -1.0
```

- [ ] **Step 2: JSON が正しいことを確認**

Run: `python -c "import json; data = json.load(open(r'C:\\Users\\iwaki\\.katrain\\config.json')); print(data['ai']['ai:jigo']['jigo_deception_13_phase1_start'])"`
Expected: `17`

- [ ] **Step 3: コミットしない**

ユーザーローカル設定ファイルは git 管理外。コミット手順なし。

---

### Task 8: 日本語 i18n 短ラベル 5 個 + `aihelp:jigo` 本文追記

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:526-537`

- [ ] **Step 1: 5 個の短ラベル msgid を追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:537` の `msgstr "target 同点扱い幅 ε (目、0=無効)"` の直後（次の `msgid "ai:scoreloss"` の前）に以下を挿入:

```
msgid "jigo_deception"
msgstr "油断誘発 Phase 機構を有効化"

msgid "jigo_deception_13_phase1_start"
msgstr "[13路] Phase1開始手数 (中盤入口で控えめに打ち始める)"

msgid "jigo_deception_13_phase2_start"
msgstr "[13路] Phase2開始手数 (徐々に target に戻し始める)"

msgid "jigo_deception_13_phase3_start"
msgstr "[13路] Phase3開始手数 (通常 Jigo に復帰、勝ちに行く)"

msgid "jigo_deception_13_phase1_target"
msgstr "[13路] Phase1 目標スコア差 (例: -2.0=2目劣勢を維持)"

msgid "jigo_deception_13_phase2_target"
msgstr "[13路] Phase2 目標スコア差 (Phase3 復帰前の中間値)"

```

> **注**: `jigo_deception` 自体の msgid もここで初追加（既存 .po 検索結果に存在しないため）。既に存在する場合はこの一塊だけ skip。

- [ ] **Step 2: `aihelp:jigo` の msgstr 末尾に説明文追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:527` の `msgstr "..."` の文字列末尾（最後の `"` の直前、`バンド内 hp 全ゼロ時は argmin にフォールバック。" の後）に以下の文を追記:

```
 jigo_deception: ON で序中盤に意図的に劣勢を演出 → 終盤で逆転する人間らしい棋風。13路盤では Phase1/2/3 の開始手数と Phase1/2 の目標スコア差をスライダーで調整可能（19/9路はコード固定）。各 Phase 中は target_max = target+1.0 で自動設定、過剰優勢/劣勢(±5目)で安全弁が Phase3 に強制ジャンプ。Phase1 開始 < Phase2 開始 < Phase3 開始 となるように設定するのが推奨だが、逆転値でもエラーにはならず「最後に手数条件を満たす Phase」が採用される。
```

具体的には `katrain.po:527` の長い msgstr 行の最後の `"` の直前に上記テキスト（先頭の半角スペース付き）を追記する。

- [ ] **Step 3: msgid の数が正しいことを確認**

Run: `grep -c 'jigo_deception_13_phase' katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
Expected: `5`

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po
git commit -m "feat(jigo-deception): 日本語 i18n に13路スライダー短ラベルと aihelp 追記"
```

---

### Task 9: 英語 i18n 短ラベル 5 個 + `aihelp:jigo` 本文追記

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`

- [ ] **Step 1: 英語 .po の `aihelp:jigo` セクション付近を確認**

Run: `grep -n 'aihelp:jigo\|jigo_large_lead\|jigo_equivalent_epsilon\|ai:scoreloss' katrain/i18n/locales/en/LC_MESSAGES/katrain.po`
Expected: 該当行番号が表示される（jp と類似の構造のはず）

- [ ] **Step 2: 短ラベル 5 個を追加**

Step 1 で確認した `jigo_equivalent_epsilon` の msgstr の直後（`ai:scoreloss` の前）に以下を挿入:

```
msgid "jigo_deception_13_phase1_start"
msgstr "[13x13] Phase 1 start move (begin holding back)"

msgid "jigo_deception_13_phase2_start"
msgstr "[13x13] Phase 2 start move (begin returning to target)"

msgid "jigo_deception_13_phase3_start"
msgstr "[13x13] Phase 3 start move (resume normal Jigo)"

msgid "jigo_deception_13_phase1_target"
msgstr "[13x13] Phase 1 target score diff (e.g. -2.0 = stay 2 pts behind)"

msgid "jigo_deception_13_phase2_target"
msgstr "[13x13] Phase 2 target score diff (intermediate before Phase 3)"

```

`jigo_deception` の msgid が英 .po に未存在の場合（jp と同じく）、同じ場所に以下も追加:

```
msgid "jigo_deception"
msgstr "Enable deception phase mechanism"

```

- [ ] **Step 3: `aihelp:jigo` msgstr 末尾に説明文追加**

英 .po の `aihelp:jigo` msgstr 文字列の最後の `"` の直前に以下を追記（先頭の半角スペース付き）:

```
 jigo_deception: when ON, deliberately plays slightly behind in early/middle game then catches up in endgame, mimicking human-like comeback play. On 13x13 boards, Phase 1/2/3 start moves and Phase 1/2 target score differences are adjustable via sliders (19x19 / 9x9 use hardcoded values). target_max = target + 1.0 within each phase, and a safety valve at +/-5 points jumps to Phase 3 on extreme lead/deficit. Recommended order is Phase1 start < Phase2 start < Phase3 start, but inverted values raise no error - the "last matching boundary wins".
```

- [ ] **Step 4: msgid 個数を確認**

Run: `grep -c 'jigo_deception_13_phase' katrain/i18n/locales/en/LC_MESSAGES/katrain.po`
Expected: `5`

- [ ] **Step 5: コミット**

```bash
git add katrain/i18n/locales/en/LC_MESSAGES/katrain.po
git commit -m "feat(jigo-deception): 英語 i18n に13路スライダー短ラベルと aihelp 追記"
```

---

### Task 10: `.mo` ファイルを再コンパイル

**Files:**
- Generate: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo`
- Generate: `katrain/i18n/locales/en/LC_MESSAGES/katrain.mo`

- [ ] **Step 1: `.mo` を再生成**

Run: `python tools/compile_mo.py`
Expected: エラーなく完了、`.mo` ファイルが更新される

- [ ] **Step 2: `.mo` のタイムスタンプが更新されたことを確認**

Run: `python -c "import os, time; jp=os.path.getmtime('katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo'); en=os.path.getmtime('katrain/i18n/locales/en/LC_MESSAGES/katrain.mo'); print(f'jp:{time.ctime(jp)}'); print(f'en:{time.ctime(en)}')"`
Expected: 現在時刻に近いタイムスタンプ

- [ ] **Step 3: 翻訳がロードされることを確認**

Run: `python -c "import gettext; t = gettext.translation('katrain', 'katrain/i18n/locales', languages=['jp']); print(t.gettext('jigo_deception_13_phase1_target'))"`
Expected: `[13路] Phase1 目標スコア差 (例: -2.0=2目劣勢を維持)`

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "feat(jigo-deception): i18n .mo ファイルを再コンパイル"
```

---

### Task 11: `.claude/rules/ai-parameters.md` に 5 行追加（サブエージェント経由）

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（JigoStrategy パラメータテーブル）

> **重要**: CLAUDE.md の「やってはいけないこと」により、`.claude/rules/` 配下の Edit は dontAsk モードで拒否されることがあるため**サブエージェント経由で編集**する。

- [ ] **Step 1: サブエージェントに編集を依頼**

Agent ツールで `general-purpose` サブエージェントを起動し、以下のプロンプトを渡す:

> `.claude/rules/ai-parameters.md` の JigoStrategy セクションのパラメータテーブル末尾（`jigo_deception` 行の直後）に以下の 5 行を追加してください:
>
> ```
> | jigo_deception_13_phase1_start | 17 | 13路盤のみ。Phase 0→1 境界手数。値: 10/17/25/35 |
> | jigo_deception_13_phase2_start | 44 | 13路盤のみ。Phase 1→2 境界手数。値: 30/44/55/70 |
> | jigo_deception_13_phase3_start | 83 | 13路盤のみ。Phase 2→3 境界手数。値: 70/83/95/110 |
> | jigo_deception_13_phase1_target | -2.0 | 13路盤のみ。Phase 1 の eff_target（target_max は +1.0 自動）。値: -1.0/-2.0/-3.0/-4.0 |
> | jigo_deception_13_phase2_target | -1.0 | 13路盤のみ。Phase 2 の eff_target（target_max は +1.0 自動）。値: -0.5/-1.0/-1.5/-2.0 |
> ```
>
> その後 `git add .claude/rules/ai-parameters.md && git commit -m "docs(jigo-deception): ai-parameters.md に13路スライダーの5パラメータを追記"` を実行してください。
> 編集と commit の両方を完了したら結果を報告してください。

- [ ] **Step 2: サブエージェント実行結果を確認**

サブエージェントが commit まで完了したことを確認。

Run: `git log --oneline -1 .claude/rules/ai-parameters.md`
Expected: 直近のコミットメッセージが「13路スライダーの5パラメータを追記」を含む

---

### Task 12: 全テスト実行で回帰確認

**Files:** （変更なし、確認のみ）

- [ ] **Step 1: jigo 関連テストを全て実行**

Run: `python -m pytest tests/test_jigo_deception.py tests/test_jigo.py tests/test_batch_eval_jigo.py -v`
Expected: 全テスト PASS

- [ ] **Step 2: humanSL モデル非依存テスト全部実行**

Run: `python -m pytest --ignore=tests/test_ai.py -v`
Expected: 全テスト PASS

---

### Task 13: CLI 検証（katrain_debug でデフォルト動作確認）

**Files:** （変更なし、確認のみ）

- [ ] **Step 1: 13路 SGF があるか確認**

Run: `python -c "from pathlib import Path; sgfs = list(Path('docs/superpowers/specs/calibration-data').rglob('*.sgf')); [print(p) for p in sgfs[:10]]"`
Expected: SGF パスのリスト

`tests/data/` 配下も確認:
Run: `python -c "from pathlib import Path; sgfs = list(Path('tests/data').glob('*.sgf')); [print(p) for p in sgfs[:10]]"`

13路 SGF があれば使用。なければ Step 2-4 は GUI 検証 (Task 14) で代替する旨を記録。

- [ ] **Step 2: デフォルト値で 13路 SGF を実行（13路 SGF がある場合のみ）**

Run（13路 SGF を `<SGF>` に置換）:
```
python -m katrain_debug --sgf <SGF> --strategy jigo --settings jigo_deception=true --move 20 --output json 2>NUL
```
Expected: JSON 出力。`result.move` フィールドに手座標、debug ログに `[JigoStrategy] Deception: move=20, phase=phase1, eff_target=-2.0, eff_target_max=-1.0, ..., sliders=True` 相当が含まれる

- [ ] **Step 3: スライダー値変更で挙動が変わることを確認**

Run:
```
python -m katrain_debug --sgf <SGF> --strategy jigo --settings jigo_deception=true jigo_deception_13_phase1_target=-4.0 --move 20 --output json 2>NUL
```
Expected: JSON 出力。debug ログに `eff_target=-4.0, eff_target_max=-3.0` 相当が含まれる

- [ ] **Step 4: Phase 開始手数変更で phase が切り替わることを確認**

Run:
```
python -m katrain_debug --sgf <SGF> --strategy jigo --settings jigo_deception=true jigo_deception_13_phase1_start=10 --move 12 --output json 2>NUL
```
Expected: debug ログに `phase=phase1`（デフォルト 17 なら phase0 のはず、10 に変更したので 12 手目で phase1）

---

### Task 14: GUI 検証

**Files:** （変更なし、確認のみ）

- [ ] **Step 1: KaTrain GUI を起動**

Run: `python -m katrain`
Expected: GUI が起動し、エラーなくメイン画面表示

- [ ] **Step 2: AI 設定ポップアップで Kata持碁 を選択**

GUI 操作:
1. メニューバーから「設定」→「AI設定」を開く
2. 戦略ドロップダウンで「Kata持碁」を選択

Expected: 設定パネルに以下 14 項目が表示される（順番は AI_OPTION_ORDER に従う）:
- target_score, target_score_max, max_loss_per_move, min_human_policy
- jigo_mode, human_profile, jigo_dynamic_rank
- jigo_large_lead_delta, jigo_large_lead_max_loss, jigo_equivalent_epsilon
- jigo_deception
- jigo_deception_13_phase1_start, jigo_deception_13_phase2_start, jigo_deception_13_phase3_start
- jigo_deception_13_phase1_target, jigo_deception_13_phase2_target

レイアウト崩れ・テキスト切れがないこと。

- [ ] **Step 3: 日本語短ラベルが反映されていることを確認**

Expected: `jigo_deception_13_phase1_start` の右側に「[13路] Phase1開始手数 (中盤入口で控えめに打ち始める)」相当のラベル表示

- [ ] **Step 4: 各スライダーで値変更 → 保存 → 再オープンで永続化確認**

GUI 操作:
1. `jigo_deception_13_phase1_start` を 17 から 25 へ変更
2. `jigo_deception_13_phase1_target` を -2.0 から -3.0 へ変更
3. 「保存」ボタンを押す
4. ポップアップを閉じる
5. 再度 AI 設定ポップアップを開く

Expected: 変更した値が保持されている

- [ ] **Step 5: ユーザー config に反映されていることを確認**

Run: `python -c "import json; d=json.load(open(r'C:\\Users\\iwaki\\.katrain\\config.json')); print(d['ai']['ai:jigo']['jigo_deception_13_phase1_start'], d['ai']['ai:jigo']['jigo_deception_13_phase1_target'])"`
Expected: `25 -3.0`

- [ ] **Step 6: 13路 AI 対局で挙動確認（任意・時間に余裕があれば）**

GUI 操作:
1. デバッグログを有効化（`C:\Users\iwaki\.katrain\config.json` の `debug_level` を `1` に変更、KaTrain 再起動）
2. 新規 13路盤の AI vs AI 対局を開始（両者を Kata持碁、jigo_deception=true）
3. 30 手前後まで進める
4. KaTrain のログウィンドウまたは標準出力で `[JigoStrategy] Deception: move=..., phase=..., sliders=True` を確認
5. 確認後 `debug_level` を `0` に戻す

Expected: スライダー値に応じた Phase 遷移が観測できる

---

### Task 15: 校正（batch_eval、3-run 平均）

**Files:** （変更なし、校正のみ）

> **注**: 元 spec の「校正の限界」セクションに記載の通り、batch_eval では trajectory 形成型機能（Phase 切替による劣勢演出）の有効性そのものは検証不可。本タスクはあくまで「デフォルト値の挙動が既存 baseline と整合し、カスタム値で AI 一致率・損失が許容範囲内に収まる」ことの確認。

- [ ] **Step 1: 13路 SGF を選定**

Run: `find docs/superpowers/specs/calibration-data tests/data -name "*.sgf" 2>NUL | xargs -I {} sh -c 'echo {}: $(grep -c "SZ\\[13\\]" {})' 2>NUL | grep ":1"`
Expected: 13路 SGF のパス一覧（なければ GUI 校正でのみ確認、本タスクスキップ）

- [ ] **Step 2: デフォルト値で 3-run 実行**

Run（`<SGF>` を 13路 SGF に置換、3 回）:
```
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --settings jigo_deception=true --output json 2>NUL > run1.json
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --settings jigo_deception=true --output json 2>NUL > run2.json
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --settings jigo_deception=true --output json 2>NUL > run3.json
```

各 JSON の `stats.overall.ai_top_move` / `mean_ptloss` を抽出し平均を取る。

- [ ] **Step 3: カスタム値で 3-run 実行**

Run（`<SGF>` を同じ 13路 SGF に置換）:
```
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --settings jigo_deception=true jigo_deception_13_phase1_target=-3.0 jigo_deception_13_phase2_target=-1.5 --output json 2>NUL > runc1.json
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --settings jigo_deception=true jigo_deception_13_phase1_target=-3.0 jigo_deception_13_phase2_target=-1.5 --output json 2>NUL > runc2.json
python -m katrain_debug --sgf <SGF> --strategy jigo --batch --settings jigo_deception=true jigo_deception_13_phase1_target=-3.0 jigo_deception_13_phase2_target=-1.5 --output json 2>NUL > runc3.json
```

- [ ] **Step 4: 結果を spec に追記**

`docs/superpowers/specs/2026-05-17-jigo-deception-13path-sliders-design.md` の末尾に「校正結果」セクションを追加し、3-run 平均の `ai_top_move` / `mean_ptloss` を記載。

合格基準:
- デフォルト値の `ai_top_move` / `mean_ptloss` が既存 13路 baseline と stdev 0.05 以内
- カスタム値の `mean_ptloss` 劣化が +1.0 目以内

- [ ] **Step 5: コミット**

```bash
git add docs/superpowers/specs/2026-05-17-jigo-deception-13path-sliders-design.md
git commit -m "docs(jigo-deception): 13路スライダー校正結果を spec に追記"
rm run1.json run2.json run3.json runc1.json runc2.json runc3.json
```

---

## 完了基準

- [ ] Task 1-3: ユニットテスト全 17 個（既存 + 新規 14 個）が PASS
- [ ] Task 4: `JigoStrategy.generate_move()` 統合完了、既存テスト無回帰
- [ ] Task 5-6: `constants.py` と `katrain/config.json` に 5 キー追加
- [ ] Task 7: ユーザー config に 5 キー追加（GUI に表示するため必須）
- [ ] Task 8-10: i18n .po 2 ファイル + .mo 再コンパイル、翻訳がロード可能
- [ ] Task 11: `.claude/rules/ai-parameters.md` 更新（サブエージェント経由）
- [ ] Task 12: 全テスト無回帰
- [ ] Task 13: CLI でスライダー値反映を確認（13路 SGF があれば）
- [ ] Task 14: GUI でスライダー表示・レイアウト・永続化を確認
- [ ] Task 15: batch_eval 校正（13路 SGF があれば）
