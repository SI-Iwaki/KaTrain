# JigoStrategy ε バンド tiebreak 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JigoStrategy の target-closest 選択に「同点扱い ε バンド + humanPolicy 重み」を導入し、定石〜互角局面での AI 最善手一致率を控えめに下げる。

**Architecture:** 既存 `_jigo_select_move`（pure function）を 4 分岐に整理し、`lead < target_score` 分岐と `in_range & maintain` 分岐のみに新ヘルパー `_pick_target_closest_with_epsilon` を挟む。`in_range & natural` と `lead > target_max` 分岐は変更なし。新規パラメータ `jigo_equivalent_epsilon` (default 0.5 目) を settings 経由で受け取る。

**Tech Stack:** Python 3.12 / pytest / Kivy（GUI 設定） / gettext（i18n）

**Spec:** `docs/superpowers/specs/2026-04-19-jigo-epsilon-tiebreak-design.md`

---

## File Map

| ファイル | 変更種別 | 責務 |
|---|---|---|
| `katrain/core/ai.py` | 修正 | `_pick_target_closest_with_epsilon` 新設、`_jigo_select_move` を 4 分岐化、`generate_move` からの引数渡し |
| `katrain/core/constants.py` | 修正 | `AI_OPTION_VALUES` に `jigo_equivalent_epsilon` 選択肢追加、`AI_OPTION_ORDER` に順序追加 |
| `katrain/config.json` | 修正 | パッケージ同梱デフォルト追加（`ai:jigo` セクション） |
| `C:\Users\iwaki\.katrain\config.json` | 修正（メインセッション直接 Edit） | ユーザーローカル設定にデフォルト追加（GUI 表示のため必須） |
| `tests/test_jigo.py` | 修正（既存ファイルに追記） | 新ヘルパー単体テスト + `_jigo_select_move` の ε 挙動テスト追加 |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 修正 | 英語ラベル追加 |
| `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | 修正 | 日本語ラベル追加 |
| `.claude/rules/ai-parameters.md` | 修正（サブエージェント経由） | JigoStrategy パラメータテーブルに追記 |

---

## Task 1: `_pick_target_closest_with_epsilon` ヘルパー新設

**Files:**
- Modify: `katrain/core/ai.py`（`_jigo_select_move` の直前、現 ai.py:794 の直前に挿入）
- Test: `tests/test_jigo.py`（末尾に新クラス追加）

- [ ] **Step 1: Write failing tests**

`tests/test_jigo.py` の末尾に追記:

```python
from katrain.core.ai import _pick_target_closest_with_epsilon


class TestPickTargetClosestWithEpsilon:
    def test_empty_candidates_returns_none(self):
        assert _pick_target_closest_with_epsilon([], target=0.5, epsilon=0.5) is None

    def test_single_candidate_returned_regardless_of_epsilon(self):
        cands = [_c("A1", 3.0, 0.0, 0.10)]
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.5)
        assert pick["move"] == "A1"

    def test_epsilon_zero_matches_argmin_deterministic(self):
        # epsilon=0 なら現行 argmin と同じ手を返す（レグレッション保証）
        cands = [
            _c("A1", 5.0, 0.0, 0.90),  # diff=4.5
            _c("B2", 0.5, 4.5, 0.05),  # diff=0 ← closest
            _c("C3", 1.0, 4.0, 0.10),  # diff=0.5
        ]
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.0)
        assert pick["move"] == "B2"

    def test_epsilon_zero_with_exact_tie_returns_first_in_list(self):
        # 完全タイ(diff 同値)は入力順で先頭を返す（current min() と同挙動）
        cands = [
            _c("A1", 1.0, 0.0, 0.05),  # diff=0.5
            _c("B2", 0.0, 1.0, 0.10),  # diff=0.5（タイ）
        ]
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.0)
        assert pick["move"] == "A1"

    def test_band_multiple_candidates_uses_humanpolicy_weighted(self, monkeypatch):
        # diff 最小=0（B2）、band = diff <= 0 + 0.5 = 0.5 → {A1(0.5), B2(0), C3(0.5)}
        cands = [
            _c("A1", 1.0, 0.0, 0.20),
            _c("B2", 0.5, 0.5, 0.05),
            _c("C3", 0.0, 1.0, 0.60),  # hp 最大、band 内
            _c("D4", 5.0, -4.5, 0.50),  # diff=4.5、band 外
        ]
        from katrain.core import ai as ai_mod

        def fake_weighted(items, n):
            return [max(items, key=lambda t: t[1])]

        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.5)
        assert pick["move"] == "C3"  # band 内で hp 最大

    def test_band_all_zero_humanpolicy_falls_back_to_argmin(self):
        # band 内 hp 全ゼロ → argmin 決定的選択（safety net）
        cands = [
            _c("A1", 1.0, 0.0, 0.0),  # diff=0.5
            _c("B2", 0.5, 0.5, 0.0),  # diff=0、argmin
        ]
        pick = _pick_target_closest_with_epsilon(cands, target=0.5, epsilon=0.5)
        assert pick["move"] == "B2"

    def test_band_excludes_candidates_beyond_epsilon(self):
        # diff 最小=0 (B2)、ε=0.3 → band = diff <= 0.3、C3(diff=1.0) は除外
        cands = [
            _c("A1", 0.8, 0.0, 0.10),  # diff=0.3（境界内）
            _c("B2", 0.5, 0.3, 0.20),  # diff=0、argmin
            _c("C3", 1.5, -1.0, 0.50),  # diff=1.0、除外
        ]
        # hp 全ゼロ fallback path を使って決定的に検証
        cands_zero_hp = [{**c, "hp": 0.0} for c in cands]
        pick = _pick_target_closest_with_epsilon(cands_zero_hp, target=0.5, epsilon=0.3)
        assert pick["move"] == "B2"  # band 内 hp ゼロ → argmin → B2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jigo.py::TestPickTargetClosestWithEpsilon -v`

Expected: ImportError / `_pick_target_closest_with_epsilon` not defined（全7テスト FAIL）

- [ ] **Step 3: Implement `_pick_target_closest_with_epsilon`**

`katrain/core/ai.py` の `_jigo_select_move` 定義の直前（現行 ai.py:794 `def _jigo_select_move(...)` の直前）に挿入:

```python
def _pick_target_closest_with_epsilon(candidates, target, epsilon):
    """target に近い候補群を同点扱いし、humanPolicy 重みで選択する。

    - epsilon <= 0 または候補1個 → argmin と同じ手を返す（band[0]）
    - candidates 空 → None
    - バンド内 hp 全ゼロ → argmin 決定的選択（safety net）
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_jigo.py::TestPickTargetClosestWithEpsilon -v`

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add katrain/core/ai.py tests/test_jigo.py
git commit -m "feat(jigo): _pick_target_closest_with_epsilon ヘルパーを新設

target に近い候補群を ε バンドで同点扱いし、humanPolicy 重みで選択する
pure function。epsilon=0 なら argmin と同じ手を返し、バンド内 hp 全ゼロ
時は argmin 決定的選択にフォールバック。"
```

---

## Task 2: `_jigo_select_move` の 4 分岐化と ε 引数追加

**Files:**
- Modify: `katrain/core/ai.py:794-807`（`_jigo_select_move` 本体）
- Test: `tests/test_jigo.py`（既存 `TestJigoSelectMove` クラスに追加）

- [ ] **Step 1: Write failing tests**

`tests/test_jigo.py` の `TestJigoSelectMove` クラス末尾（現行 `test_in_range_maintain_picks_closest_to_target` の後）に追記:

```python
    def test_epsilon_kwarg_defaults_to_zero_preserves_current_behavior(self):
        # epsilon 省略時は現行 argmin 挙動と同じ
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

    def test_epsilon_applied_in_below_target_branch(self, monkeypatch):
        # lead < target_score → 分岐1 → ε バンドで humanPolicy 重み
        cands = [
            _c("A1", 0.5, 0.0, 0.10),  # diff=0（argmin）
            _c("B2", 0.8, -0.3, 0.80),  # diff=0.3、hp 最大
        ]
        from katrain.core import ai as ai_mod

        def fake_weighted(items, n):
            return [max(items, key=lambda t: t[1])]

        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)
        pick = _jigo_select_move(
            cands, current_lead=-3.0, target_score=0.5,
            target_score_max=10.0, mode="natural", epsilon=0.5
        )
        # band = {A1(diff=0), B2(diff=0.3)} → hp 最大 B2
        assert pick["move"] == "B2"

    def test_epsilon_applied_in_in_range_maintain_branch(self, monkeypatch):
        # in_range & mode=maintain → 分岐3 → ε バンドで humanPolicy 重み
        cands = [
            _c("A1", 0.5, 0.0, 0.10),  # diff=0
            _c("B2", 1.0, -0.5, 0.80),  # diff=0.5、hp 最大
        ]
        from katrain.core import ai as ai_mod

        def fake_weighted(items, n):
            return [max(items, key=lambda t: t[1])]

        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)
        pick = _jigo_select_move(
            cands, current_lead=5.0, target_score=0.5,
            target_score_max=10.0, mode="maintain", epsilon=0.5
        )
        assert pick["move"] == "B2"

    def test_epsilon_ignored_in_in_range_natural_branch(self, monkeypatch):
        # 分岐2(natural) は ε を無視して既存 humanPolicy 重み単体
        cands = [
            _c("A1", 5.0, 0.0, 0.90),  # hp 最大
            _c("B2", 0.5, 4.5, 0.05),  # target 最近接
        ]
        from katrain.core import ai as ai_mod

        def fake_weighted(items, n):
            return [max(items, key=lambda t: t[1])]

        monkeypatch.setattr(ai_mod, "weighted_selection_without_replacement", fake_weighted)
        pick = _jigo_select_move(
            cands, current_lead=5.0, target_score=0.5,
            target_score_max=10.0, mode="natural", epsilon=0.5
        )
        # 分岐2: ε 無視、全候補 hp 重み → A1
        assert pick["move"] == "A1"

    def test_epsilon_ignored_in_above_target_max_branch(self):
        # 分岐4(lead > target_max) は ε を無視して argmin
        cands = [
            _c("A1", 25.0, 0.0, 0.80),  # hp 大だが diff 大
            _c("B2", 0.5, 24.5, 0.05),  # diff=0、argmin
        ]
        pick = _jigo_select_move(
            cands, current_lead=30.0, target_score=0.5,
            target_score_max=10.0, mode="natural", epsilon=0.5
        )
        assert pick["move"] == "B2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jigo.py::TestJigoSelectMove -v`

Expected: 新しい 5 テストは `_jigo_select_move() got an unexpected keyword argument 'epsilon'` で FAIL、既存 4 テストは PASS

- [ ] **Step 3: Update `_jigo_select_move` implementation**

`katrain/core/ai.py:794-807` の `_jigo_select_move` を以下で完全置換:

```python
def _jigo_select_move(candidates, current_lead, target_score, target_score_max, mode, epsilon=0.0):
    """現在リード × Mode × ε で着手を選択。
    - 分岐1: current_lead < target_score → target 近傍 ε バンド + humanPolicy 重み
    - 分岐2: in_range & natural → humanPolicy 重み単体（ε 無視）
    - 分岐3: in_range & maintain → target 近傍 ε バンド + humanPolicy 重み
    - 分岐4: lead > target_max → argmin(|score-target|) 決定的（ε 無視、削り意図を保つ）
    """
    in_range = target_score <= current_lead <= target_score_max

    # 分岐1: 負け〜互角
    if current_lead < target_score:
        return _pick_target_closest_with_epsilon(candidates, target_score, epsilon)

    # 分岐2: in_range & natural（ε 無視）
    if in_range and mode == "natural":
        weighted = [(c, c["hp"]) for c in candidates]
        selected = weighted_selection_without_replacement(weighted, 1)[0]
        return selected[0]

    # 分岐3: in_range & maintain
    if in_range and mode == "maintain":
        return _pick_target_closest_with_epsilon(candidates, target_score, epsilon)

    # 分岐4: lead > target_max（ε 無視、鋭手除外後の決定的選択）
    return min(candidates, key=lambda c: abs(c["score"] - target_score))
```

- [ ] **Step 4: Run full jigo tests to verify all pass**

Run: `pytest tests/test_jigo.py -v`

Expected: 全テスト PASS（既存 + 新規 5 件）

- [ ] **Step 5: Commit**

```bash
git add katrain/core/ai.py tests/test_jigo.py
git commit -m "feat(jigo): _jigo_select_move を 4 分岐化し ε 引数を追加

現行の 3 分岐を以下の 4 分岐に整理:
- 分岐1 (lead < target_score): ε バンド + humanPolicy 重み
- 分岐2 (in_range & natural): 変更なし、ε 無視
- 分岐3 (in_range & maintain): ε バンド + humanPolicy 重み
- 分岐4 (lead > target_max): 変更なし、ε 無視

epsilon=0.0 デフォルトで後方互換。既存テスト全通過を確認。"
```

---

## Task 3: `JigoStrategy.generate_move` から ε を受け渡し

**Files:**
- Modify: `katrain/core/ai.py:836-851`（settings 読み込み部）
- Modify: `katrain/core/ai.py:1054`（`_jigo_select_move` 呼び出し部）

- [ ] **Step 1: Read `jigo_equivalent_epsilon` from settings**

`katrain/core/ai.py` の `JigoStrategy.generate_move` 冒頭、設定読み込みブロック（現行 ai.py:836-844 あたり）に追記。現行:

```python
        large_lead_delta    = self.settings.get("jigo_large_lead_delta", 5.0)
        large_lead_max_loss = self.settings.get("jigo_large_lead_max_loss", 8.0)
```

の直後に以下を追加:

```python
        equivalent_epsilon  = self.settings.get("jigo_equivalent_epsilon", 0.5)
```

合わせて設定ログ（ai.py:845-851）の f-string 末尾に `equivalent_epsilon` を追記:

**変更前:**
```python
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}, "
            f"profile={base_profile}, dynamic_rank={dynamic_rank}, "
            f"large_lead_delta={large_lead_delta}, large_lead_max_loss={large_lead_max_loss}",
            OUTPUT_DEBUG,
        )
```

**変更後:**
```python
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}, "
            f"profile={base_profile}, dynamic_rank={dynamic_rank}, "
            f"large_lead_delta={large_lead_delta}, large_lead_max_loss={large_lead_max_loss}, "
            f"equivalent_epsilon={equivalent_epsilon}",
            OUTPUT_DEBUG,
        )
```

- [ ] **Step 2: Pass epsilon to `_jigo_select_move`**

`katrain/core/ai.py:1054`:

**変更前:**
```python
        pick = _jigo_select_move(filtered, current_lead, target_score, target_score_max, mode)
```

**変更後:**
```python
        pick = _jigo_select_move(filtered, current_lead, target_score, target_score_max, mode, equivalent_epsilon)
```

- [ ] **Step 3: Run full jigo tests to confirm no regression**

Run: `pytest tests/test_jigo.py -v`

Expected: 全テスト PASS

- [ ] **Step 4: Commit**

```bash
git add katrain/core/ai.py
git commit -m "feat(jigo): jigo_equivalent_epsilon を settings から読み取り select_move に渡す

JigoStrategy.generate_move で jigo_equivalent_epsilon (default 0.5) を
settings.get() し、_jigo_select_move に引数として渡す。デバッグログにも
値を追記。"
```

---

## Task 4: constants.py に設定項目登録

**Files:**
- Modify: `katrain/core/constants.py:184-200`（`AI_OPTION_VALUES` JigoStrategy セクション）
- Modify: `katrain/core/constants.py:247-256`（`AI_OPTION_ORDER`）

- [ ] **Step 1: Add to `AI_OPTION_VALUES`**

`katrain/core/constants.py:199` の末尾（`"jigo_large_lead_max_loss": [6.0, 7.0, 8.0, 9.0, 10.0],` の直後、line 200 の `}` の前）に追加:

**変更前:**
```python
    "jigo_large_lead_delta": [3.0, 5.0, 7.0, 10.0],
    "jigo_large_lead_max_loss": [6.0, 7.0, 8.0, 9.0, 10.0],
}
```

**変更後:**
```python
    "jigo_large_lead_delta": [3.0, 5.0, 7.0, 10.0],
    "jigo_large_lead_max_loss": [6.0, 7.0, 8.0, 9.0, 10.0],
    "jigo_equivalent_epsilon": [0.0, 0.3, 0.5, 1.0],
}
```

- [ ] **Step 2: Add to `AI_OPTION_ORDER`**

`katrain/core/constants.py:255` の末尾（`"jigo_large_lead_max_loss": 8,` の直後、`}` の前）に追加:

**変更前:**
```python
    "jigo_large_lead_delta": 7,
    "jigo_large_lead_max_loss": 8,
}
```

**変更後:**
```python
    "jigo_large_lead_delta": 7,
    "jigo_large_lead_max_loss": 8,
    "jigo_equivalent_epsilon": 9,
}
```

- [ ] **Step 3: Verify constants.py imports still work**

Run: `python -c "from katrain.core.constants import AI_OPTION_VALUES; print(AI_OPTION_VALUES['jigo_equivalent_epsilon'])"`

Expected: `[0.0, 0.3, 0.5, 1.0]`

- [ ] **Step 4: Commit**

```bash
git add katrain/core/constants.py
git commit -m "feat(jigo): constants.py に jigo_equivalent_epsilon を登録

AI_OPTION_VALUES に選択肢 [0.0, 0.3, 0.5, 1.0]、AI_OPTION_ORDER に 9
を追加。GUI で target-closest 同点扱いバンド幅 (目) を選択可能にする。"
```

---

## Task 5: パッケージ同梱 config.json にデフォルト追加

**Files:**
- Modify: `katrain/config.json:102-112`（`ai:jigo` セクション）

- [ ] **Step 1: Add default to `ai:jigo` section**

`katrain/config.json:102-112`:

**変更前:**
```json
        "ai:jigo": {
            "target_score": 0.5,
            "target_score_max": 10.0,
            "max_loss_per_move": 5.6,
            "min_human_policy": 0.02,
            "jigo_mode": "natural",
            "human_profile": "rank_9d",
            "jigo_dynamic_rank": false,
            "jigo_large_lead_delta": 5.0,
            "jigo_large_lead_max_loss": 8.0
        },
```

**変更後:**
```json
        "ai:jigo": {
            "target_score": 0.5,
            "target_score_max": 10.0,
            "max_loss_per_move": 5.6,
            "min_human_policy": 0.02,
            "jigo_mode": "natural",
            "human_profile": "rank_9d",
            "jigo_dynamic_rank": false,
            "jigo_large_lead_delta": 5.0,
            "jigo_large_lead_max_loss": 8.0,
            "jigo_equivalent_epsilon": 0.5
        },
```

- [ ] **Step 2: Verify JSON still parses**

Run: `python -c "import json; json.load(open('katrain/config.json'))"`

Expected: エラーなし

- [ ] **Step 3: Commit**

```bash
git add katrain/config.json
git commit -m "feat(jigo): パッケージ config.json に jigo_equivalent_epsilon=0.5 追加

ai:jigo セクションに新パラメータのデフォルト値を追加。"
```

---

## Task 6: ユーザーローカル config.json にデフォルト追加

> **重要**: この Task は**メインセッションで直接 Edit する**。サブエージェント経由では反映されない場合がある（CLAUDE.md / memory `project_ai_settings_pattern.md` のルール）。

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json:102-112`（`ai:jigo` セクション）

- [ ] **Step 1: Add default to user local config**

`C:\Users\iwaki\.katrain\config.json:102-112`:

**変更前:**
```json
        "ai:jigo": {
            "target_score": 0.9,
            "target_score_max": 2.0,
            "max_loss_per_move": 7.0,
            "min_human_policy": 0.02,
            "jigo_mode": "natural",
            "human_profile": "rank_5d",
            "jigo_dynamic_rank": true,
            "jigo_large_lead_delta": 8.0,
            "jigo_large_lead_max_loss": 6.0
        },
```

**変更後:**
```json
        "ai:jigo": {
            "target_score": 0.9,
            "target_score_max": 2.0,
            "max_loss_per_move": 7.0,
            "min_human_policy": 0.02,
            "jigo_mode": "natural",
            "human_profile": "rank_5d",
            "jigo_dynamic_rank": true,
            "jigo_large_lead_delta": 8.0,
            "jigo_large_lead_max_loss": 6.0,
            "jigo_equivalent_epsilon": 0.5
        },
```

- [ ] **Step 2: Verify JSON still parses**

Run: `python -c "import json; json.load(open('C:/Users/iwaki/.katrain/config.json'))"`

Expected: エラーなし

- [ ] **Step 3: (commit 不要)**

ユーザーローカル config.json は git 管理外のため commit しない。次の Task に進む。

---

## Task 7: i18n ラベル追加（en / jp）

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`（`jigo_large_lead_delta` エントリの近く）
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`（同上）
- Execute: `python tools/compile_mo.py`

- [ ] **Step 1: Locate existing jigo i18n entries**

Run: `grep -n "jigo_large_lead" katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`

両ファイルで `msgid "jigo_large_lead_delta"` / `msgid "jigo_large_lead_max_loss"` の行番号を確認する（エントリの近傍に追記するため）。

- [ ] **Step 2: Add English entry**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の `msgid "jigo_large_lead_max_loss"` エントリの直後（msgstr 行の直後、空行を挟む）に追記:

```
msgid "jigo_equivalent_epsilon"
msgstr "target-equivalent band (pt, 0=off)"
```

- [ ] **Step 3: Add Japanese entry**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `msgid "jigo_large_lead_max_loss"` エントリの直後に追記:

```
msgid "jigo_equivalent_epsilon"
msgstr "target 同点扱い幅 ε (目、0=無効)"
```

- [ ] **Step 4: Compile .mo files**

Run: `python tools/compile_mo.py`

Expected: エラーなしで両言語の `.mo` が更新される

- [ ] **Step 5: Verify compilation**

Run: `ls -la katrain/i18n/locales/en/LC_MESSAGES/katrain.mo katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo`

Expected: 両ファイルの mtime が直前の compile_mo.py 実行時刻に更新されている

- [ ] **Step 6: Commit**

```bash
git add katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.mo katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo
git commit -m "i18n(jigo): jigo_equivalent_epsilon のラベル追加 (en/jp)

英語: 'target-equivalent band (pt, 0=off)'
日本語: 'target 同点扱い幅 ε (目、0=無効)'
.po 編集後に tools/compile_mo.py で .mo を再コンパイル済み。"
```

---

## Task 8: `.claude/rules/ai-parameters.md` に追記（サブエージェント経由）

> **重要**: `.claude/rules/` 配下は Edit が dontAsk でも拒否されることがある（memory `feedback_claude_rules_edit.md`）。**サブエージェント（Agent tool）経由で編集・commit する**こと。

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（JigoStrategy パラメータテーブル）

- [ ] **Step 1: Dispatch subagent to edit and commit**

サブエージェント（`general-purpose`）に以下のプロンプトを送る:

```
.claude/rules/ai-parameters.md の「## 持碁戦略（JigoStrategy）」セクション内、
パラメータテーブル（`| jigo_large_lead_max_loss | 8.0 | 圧勝時の許容損失...` の行がある表）の
最終行の後に、以下の1行を追加してください:

| jigo_equivalent_epsilon | 0.5 | target-closest からの同点扱い許容幅（目）。分岐1(lead<target)と分岐3(in_range&maintain)でのみ適用、0.0/0.3/0.5/1.0 から選択。0 で完全現行動作 |

また、JigoStrategy セクションの動作説明ブロック（「**選択ロジック**:」のリスト）の直後に、
以下の段落を追加してください:

**target-closest 同点扱いバンド（2026-04-19 追加）**: `lead < target_score` と `in_range & mode=maintain` の分岐で、
argmin(|score-target|) の結果を「min_diff + jigo_equivalent_epsilon 以内の候補」に拡張し、その中から
humanPolicy 重みで1手を選択する（`_pick_target_closest_with_epsilon`）。定石一本道局面では候補1個のみ
バンドに入り現行挙動と一致。バンド内 hp 全ゼロ時は argmin にフォールバック。`in_range & natural` と
`lead > target_max` 分岐は変更なし。Spec: `docs/superpowers/specs/2026-04-19-jigo-epsilon-tiebreak-design.md`

編集後は以下の commit を作成してください:

git commit -m "docs(jigo): ai-parameters.md に jigo_equivalent_epsilon を追記

target-closest 同点扱いバンド機構の説明とパラメータテーブル行を追加。
Spec: 2026-04-19-jigo-epsilon-tiebreak-design.md"

編集作業のみ実行し、実装タスクには触らないでください。
```

- [ ] **Step 2: Verify commit was created**

Run: `git log --oneline -3`

Expected: 最新 commit に `docs(jigo): ai-parameters.md に jigo_equivalent_epsilon を追記` が表示される

---

## Task 9: 手動検証（GUI + katrain_debug CLI）

**Files:** なし（動作確認のみ）

- [ ] **Step 1: GUI 表示確認**

Run: `python -m katrain`

期待動作:
- 対局メニュー → AI 設定 → Jigo を選択 → 新しい「target 同点扱い幅 ε」スライダー（0.0 / 0.3 / 0.5 / 1.0）が表示される
- 既存の他パラメータ（target_score、jigo_mode 等）も正常に表示される
- デフォルトは 0.5 に選択されている

- [ ] **Step 2: katrain_debug CLI で単一局面の挙動確認**

Run:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --settings jigo_equivalent_epsilon=0.5 --output text 2>&1 | head -50
```

期待動作:
- 正常終了（KataGo 起動 ~30秒）
- 出力に `equivalent_epsilon=0.5` が含まれる（Settings ログ）
- `[JigoStrategy] Selected:` 行で着手が選択されている

ε=0.0 との比較:

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --settings jigo_equivalent_epsilon=0.0 --output text 2>&1 | head -50
```

期待動作:
- 同一局面・同一 seed で実行した場合、ε=0.0 は決定的に現行と同じ手を選ぶ（レグレッション保証）

- [ ] **Step 3: (任意) batch_eval で校正実験**

以下は spec §9 の校正ステップ。実装プラン終了後の別セッションで実施可:

```bash
# Baseline (ε=0.0)
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/jigo-speedup/<任意の SGF> --strategy jigo --batch --settings jigo_equivalent_epsilon=0.0

# ε=0.5 (default)
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/jigo-speedup/<任意の SGF> --strategy jigo --batch --settings jigo_equivalent_epsilon=0.5

# 3-run 平均のために各設定で 3 回繰り返し（jigo 分散メモリより）
```

期待指標:
- `ai_top_move` が ε=0.5 で ε=0.0 比 5〜15% 低下
- `mean_ptloss` の劣化が +0.3 目以内
- target 範囲超過局数が増えない

結果は `docs/superpowers/specs/calibration-data/jigo-epsilon/` に保存し、本 spec 付録に追記。

---

## 自己レビューチェックリスト（書き終わった後に私が確認した項目）

- [x] spec §アーキテクチャの 4 分岐すべてに対応するタスクがある（Task 1-3）
- [x] spec §設定項目の 3 箇所配置ルールを全て満たす（Task 4: constants、Task 5: package config、Task 6: user local config）
- [x] spec §テスト計画の 8 項目すべてに対応するテストが Task 1-2 にある
- [x] エッジケース（空リスト、単独候補、ε=0、hp 全ゼロ、lead > target_max での ε 無視、lead < target での ε 適用、maintain での ε 適用、natural での ε 無視）すべてテスト済み
- [x] i18n 編集後の `tools/compile_mo.py` 実行を明記（Task 7）
- [x] `.claude/rules/` 編集のサブエージェント委任を明記（Task 8）
- [x] ユーザーローカル config 編集のメインセッション直接 Edit を明記（Task 6）
- [x] TDD 順序（failing test → run fail → implement → run pass → commit）を各タスクで遵守
- [x] 全コードブロックが具体的な実装内容（placeholder なし）
- [x] ファイルパス・行番号を既存コードの grep 結果に基づいて記載
- [x] `epsilon` 引数のデフォルト値 `0.0` で後方互換を保証（既存 `TestJigoSelectMove` テストが通り続ける）
