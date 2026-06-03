# 持碁（9路）専用モード Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 9路専用の独立戦略 `ai:jigo9`（持碁（9路））を新設し、既存 `ai:jigo` から9路を除去。9路 deception を5スライダーで調整可能にし、phase3開始の前倒し（既定30手）で挽回を間に合わせる。

**Architecture:** `JigoStrategy` を継承した `Jigo9Strategy` を追加（案A）。`generate_move` は親実装を流用し、deception ブロックに `board_size==9` 分岐を追加。外す4機能はクラス属性 `FORCED_SETTINGS` ＋ヘルパー `_jigo_get` で GUI 非表示・config 非格納・コード無効化を両立。既存 jigo の9路専用定数・キャップは削除。

**Tech Stack:** Python 3.12, pytest, KaTrain（Kivy GUI）, gettext（i18n）

設計仕様: `docs/superpowers/specs/2026-06-04-jigo-9x9-dedicated-mode-design.md`

---

## ファイル構成

| ファイル | 責務 | 変更種別 |
|---|---|---|
| `katrain/core/constants.py` | `AI_JIGO_9` 定数・戦略登録・GUIウィジェット定義（`AI_OPTION_VALUES`/`AI_OPTION_ORDER`） | Modify |
| `katrain/core/ai.py` | `Jigo9Strategy` 新設・`_jigo_resolve_path_overrides` 汎用化・`generate_move` の9路分岐・`_jigo_get`/`FORCED_SETTINGS`・9路定数削除・`ai_rank_estimation` | Modify |
| `katrain/config.json` | パッケージ同梱デフォルト（`ai:jigo9` セクション） | Modify |
| `C:\Users\iwaki\.katrain\config.json` | ユーザーローカル設定（GUI表示用。**メインセッションで直接Edit**） | Modify |
| `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po` | 戦略名・ヘルプ・短ラベル | Modify |
| `katrain_debug/runner.py` | CLIの戦略名マッピング | Modify |
| `katrain_debug/batch_eval.py` | jigo_metrics 分岐 | Modify |
| `tests/test_jigo_deception.py` | phase解決・override のユニットテスト（9路化対応） | Modify |
| `tests/test_jigo.py` | `_jigo_compute_effective_max_loss` テスト（9路キャップ削除対応） | Modify |
| `tests/test_jigo9.py` | `Jigo9Strategy.FORCED_SETTINGS`/`_jigo_get` の新規テスト | Create |
| `.claude/rules/ai-parameters.md` / `CLAUDE.md` | パラメータ表・概要 | Modify |

**注意（CLAUDE.md 由来）**:
- `.claude/rules/` 配下の Edit が `dontAsk` モードで拒否されることがある。拒否されたらサブエージェント経由で編集・コミット。
- ユーザーローカル `C:\Users\iwaki\.katrain\config.json` の編集はサブエージェントに委任せず**メインセッションで直接Edit**。
- i18n `.po` 編集後は `python tools/compile_mo.py` で `.mo` 再コンパイル必須。
- AI系テスト（`test_ai.py`）は humanSL モデルが必要。本計画のテストはモデル不要（純関数・属性のみ）だが、全体実行時は `pytest --ignore=tests/test_ai.py` を使う。

---

## Task 1: `_jigo_resolve_path_overrides` の汎用化（13路機構を9路へ転用可能に）

既存 `_jigo_resolve_13path_overrides` を `key_prefix` 引数付きの `_jigo_resolve_path_overrides` にリネーム・汎用化する。13路呼び出しは後方互換（デフォルト `key_prefix="jigo_deception_13"`）。

**Files:**
- Modify: `katrain/core/ai.py:851-873`（関数定義）
- Test: `tests/test_jigo_deception.py:236-269`（既存 `TestJigo13PathOverrides`）+ 新規9路ケース

- [ ] **Step 1: 既存テストの import と呼び出しを新名へ更新し、9路用テストを追加（失敗する）**

`tests/test_jigo_deception.py` の import（10行目）を変更:

```python
from katrain.core.ai import (
    JIGO_DECEPTION_PHASE_TABLE,
    JIGO_DECEPTION_TARGETS,
    JIGO_DECEPTION_SAFETY_OVERSHOOT,
    _jigo_resolve_phase,
    _jigo_resolve_path_overrides,  # 汎用化（旧 _jigo_resolve_13path_overrides）
)
```

`TestJigo13PathOverrides` クラス（236-269行）内の全 `_jigo_resolve_13path_overrides(` を `_jigo_resolve_path_overrides(` に置換（6箇所）。`test_phase1_uses_setting` / `test_phase2_uses_setting` 等は `key_prefix` 省略でデフォルト `"jigo_deception_13"` が効くため引数追加不要。

さらに同ファイル末尾に9路用テストクラスを追加:

```python
class TestJigo9PathOverrides:
    """_jigo_resolve_path_overrides の key_prefix='jigo9' 挙動"""

    def test_phase0_passthrough(self):
        result = _jigo_resolve_path_overrides("phase0", 0.5, 5.0, {}, key_prefix="jigo9")
        assert result == (0.5, 5.0)

    def test_phase3_passthrough(self):
        result = _jigo_resolve_path_overrides("phase3", 0.5, 5.0, {}, key_prefix="jigo9")
        assert result == (0.5, 5.0)

    def test_phase1_uses_setting(self):
        settings = {"jigo9_phase1_target": -2.0}
        result = _jigo_resolve_path_overrides("phase1", 0.0, 0.0, settings, key_prefix="jigo9")
        assert result == (-2.0, -1.0)

    def test_phase2_uses_setting(self):
        settings = {"jigo9_phase2_target": -1.0}
        result = _jigo_resolve_path_overrides("phase2", 0.0, 0.0, settings, key_prefix="jigo9")
        assert result == (-1.0, 0.0)

    def test_phase1_missing_uses_9x9_default(self):
        # 9路 phase1 のフォールバック既定は -1.5
        result = _jigo_resolve_path_overrides("phase1", 0.0, 0.0, {}, key_prefix="jigo9")
        assert result == (-1.5, -0.5)

    def test_phase2_missing_uses_9x9_default(self):
        # 9路 phase2 のフォールバック既定は -0.5
        result = _jigo_resolve_path_overrides("phase2", 0.0, 0.0, {}, key_prefix="jigo9")
        assert result == (-0.5, 0.5)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_jigo_deception.py -k "PathOverrides" -v`
Expected: FAIL（`ImportError: cannot import name '_jigo_resolve_path_overrides'`）

- [ ] **Step 3: `ai.py` の関数を汎用化**

`katrain/core/ai.py:851-873` の `_jigo_resolve_13path_overrides` を以下で置換:

```python
# key_prefix ごとの「設定キー欠落時」フォールバック target（target_max は +1.0 で自動）
_JIGO_PATH_TARGET_DEFAULTS = {
    "jigo_deception_13": {"phase1": -2.0, "phase2": -1.0},
    "jigo9":             {"phase1": -1.5, "phase2": -0.5},
}


def _jigo_resolve_path_overrides(phase, default_target, default_target_max, settings,
                                 key_prefix="jigo_deception_13"):
    """deception 有効時、Phase 1/2 で eff_target/eff_target_max を
    settings (スライダー値) に置換して返す。盤面別に key_prefix で切替。

    Phase 0/3 は default をそのまま返す（既存挙動）。
    target_max は target + 1.0 で自動算出（1.0 目幅維持）。

    Args:
        phase: "phase0" | "phase1" | "phase2" | "phase3"
        default_target: phase0/phase3 用フォールバック値
        default_target_max: phase0/phase3 用フォールバック値
        settings: Strategy.settings 相当の dict-like
        key_prefix: "jigo_deception_13"（13路）/ "jigo9"（9路）

    Returns:
        (eff_target, eff_target_max)
    """
    fallbacks = _JIGO_PATH_TARGET_DEFAULTS[key_prefix]
    if phase == "phase1":
        t = settings.get(f"{key_prefix}_phase1_target", fallbacks["phase1"])
        return t, t + 1.0
    if phase == "phase2":
        t = settings.get(f"{key_prefix}_phase2_target", fallbacks["phase2"])
        return t, t + 1.0
    return default_target, default_target_max
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/test_jigo_deception.py -k "PathOverrides" -v`
Expected: PASS（13路・9路 両クラス）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo_deception.py
git commit -m "$(cat <<'EOF'
refactor(jigo): _jigo_resolve_13path_overrides を key_prefix 付きで汎用化

9路 deception スライダーと13路で同一ロジックを共有できるよう
_jigo_resolve_path_overrides にリネーム。key_prefix ごとのフォールバック
target を _JIGO_PATH_TARGET_DEFAULTS に集約。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `FORCED_SETTINGS` / `_jigo_get` 無効化機構

`JigoStrategy` にクラス属性 `FORCED_SETTINGS = {}` とヘルパー `_jigo_get` を追加し、外す4設定の read をこのヘルパー経由にする。基底は空 dict なので挙動不変。`Jigo9Strategy`（Task 5 で定義）が override する土台を作る。

**Files:**
- Modify: `katrain/core/ai.py`（`JigoStrategy` クラス本体・`generate_move` 内4箇所の read）
- Test: `tests/test_jigo9.py`（新規）

- [ ] **Step 1: 失敗するテストを書く（基底分のみ。`Jigo9Strategy` 未定義のため import しない）**

`tests/test_jigo9.py` を新規作成:

```python
# tests/test_jigo9.py
"""Jigo9Strategy の FORCED_SETTINGS / _jigo_get 無効化機構のユニットテスト"""
from katrain.core.ai import JigoStrategy


def _bare(cls, settings):
    """engine/game なしで _jigo_get だけ検証する軽量インスタンスを作る"""
    obj = cls.__new__(cls)
    obj.settings = settings
    return obj


class TestJigoGetBase:
    """基底 JigoStrategy は FORCED_SETTINGS 空 → settings をそのまま返す"""

    def test_returns_settings_value(self):
        obj = _bare(JigoStrategy, {"jigo_equivalent_epsilon": 0.7})
        assert obj._jigo_get("jigo_equivalent_epsilon", 0.5) == 0.7

    def test_returns_default_when_missing(self):
        obj = _bare(JigoStrategy, {})
        assert obj._jigo_get("jigo_equivalent_epsilon", 0.5) == 0.5

    def test_base_forced_settings_is_empty(self):
        assert JigoStrategy.FORCED_SETTINGS == {}
```

> `TestJigo9Forced`（`Jigo9Strategy` を import するクラス）は Task 5 Step 7 で追加する。Task 5 完了前に import すると collection エラーになるため、ここでは基底分のみ。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_jigo9.py -v`
Expected: FAIL（`AttributeError: ... 'JigoStrategy' ... '_jigo_get'` / `FORCED_SETTINGS`）

- [ ] **Step 3: `JigoStrategy` に `FORCED_SETTINGS` と `_jigo_get` を追加**

`katrain/core/ai.py` の `class JigoStrategy(AIStrategy):` 直下（docstring の後、`def generate_move` の前）に追加:

```python
    # サブクラスで特定設定を強制無効化するための上書きマップ（基底は空）
    FORCED_SETTINGS = {}

    def _jigo_get(self, key, default):
        """FORCED_SETTINGS にあればその値、なければ self.settings.get(key, default)。"""
        if key in self.FORCED_SETTINGS:
            return self.FORCED_SETTINGS[key]
        return self.settings.get(key, default)
```

`generate_move` 内の以下4箇所を `self.settings.get` → `self._jigo_get` に変更:

```python
        base_profile     = self._jigo_get("human_profile", "rank_9d")
        dynamic_rank     = self._jigo_get("jigo_dynamic_rank", False)
        large_lead_delta    = self._jigo_get("jigo_large_lead_delta", 5.0)
        equivalent_epsilon  = self._jigo_get("jigo_equivalent_epsilon", 0.5)
```

（元: `katrain/core/ai.py:976-980` 付近の対応する4行。`target_score`/`target_score_max`/`max_loss`/`min_hp`/`mode` 等のその他 read は `self.settings.get` のまま）

- [ ] **Step 4: 基底テストを実行して成功を確認**

Run: `pytest tests/test_jigo9.py -k "TestJigoGetBase" -v`
Expected: PASS（3 tests）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo9.py
git commit -m "$(cat <<'EOF'
feat(jigo): FORCED_SETTINGS/_jigo_get で設定をサブクラス強制無効化可能に

JigoStrategy に空の FORCED_SETTINGS とヘルパー _jigo_get を追加し、
human_profile/jigo_dynamic_rank/jigo_large_lead_delta/jigo_equivalent_epsilon
の read を経由化。基底は挙動不変、Jigo9Strategy 無効化の土台。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 既存 JigoStrategy から9路サポートを除去

9路専用の定数・テーブルエントリ・キャップ分岐を削除する。9路は新モードが override で駆動するためテーブル非依存。

**Files:**
- Modify: `katrain/core/ai.py`（`JIGO_DECEPTION_PHASE_TABLE`/`JIGO_DECEPTION_TARGETS`/`JIGO_LARGE_LEAD_9X9_CAP`/`_jigo_compute_effective_max_loss`）
- Test: `tests/test_jigo_deception.py`・`tests/test_jigo.py`（9路参照テストの削除）

- [ ] **Step 1: 9路を参照する既存テストを削除（先に削除して赤線を消す）**

`tests/test_jigo_deception.py` から以下を削除:
- `TestJigoPhaseBoundaries9` クラス全体（58-71行）
- `TestJigoDeceptionTargetsLookup` 内の `test_9_phase1_targets`（146-147行）と `test_9_phase2_targets`（149-150行）
- `TestJigoPhaseTableStructure` 内の `test_9_boundaries`（172-175行）

`tests/test_jigo.py` から以下を削除:
- `test_caps_at_5_for_9x9_board`（423-429行）

- [ ] **Step 2: `ai.py` の9路定数・分岐を削除**

`katrain/core/ai.py`:

`JIGO_DECEPTION_PHASE_TABLE`（780-784行）から `9:` 行を削除:

```python
JIGO_DECEPTION_PHASE_TABLE = {
    19: [(30, "phase1"), (80, "phase2"), (150, "phase3")],
    13: [(17, "phase1"), (44, "phase2"), (83, "phase3")],
}
```

`JIGO_DECEPTION_TARGETS`（788-801行）から `(9, ...)` 4エントリを削除:

```python
JIGO_DECEPTION_TARGETS = {
    (19, "phase0"): None,
    (19, "phase1"): (-3.0, -2.0),
    (19, "phase2"): (-1.5, -0.5),
    (19, "phase3"): None,
    (13, "phase0"): None,
    (13, "phase1"): (-2.0, -1.0),
    (13, "phase2"): (-1.0,  0.0),
    (13, "phase3"): None,
}
```

`JIGO_LARGE_LEAD_9X9_CAP`（772-773行）の定数とコメントを削除。

`_jigo_compute_effective_max_loss`（876-891行）から `board_size <= 9` キャップ分岐を削除:

```python
def _jigo_compute_effective_max_loss(
    current_lead, target_score_max, base_max_loss,
    large_lead_delta, large_lead_max_loss, board_size,
):
    """current_lead が target_score_max + large_lead_delta を超えた場合のみ max_loss を緩和する。

    緩和発動しない場合・large_lead_max_loss が base より小さい場合は base_max_loss を返す。
    board_size は呼び出し側互換のため残す（盤面別の特別扱いは廃止）。
    """
    threshold = target_score_max + large_lead_delta
    if current_lead < threshold:
        return base_max_loss
    return max(base_max_loss, large_lead_max_loss)
```

- [ ] **Step 3: テストを実行して成功を確認（9路参照削除後も全て緑）**

Run: `pytest tests/test_jigo_deception.py tests/test_jigo.py -v`
Expected: PASS（残った全テスト。9路参照テストは削除済み、`_jigo_compute_effective_max_loss` の19/13路テストは挙動不変で緑）

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo_deception.py tests/test_jigo.py
git commit -m "$(cat <<'EOF'
refactor(jigo): 既存 JigoStrategy から9路専用コードを除去

JIGO_DECEPTION_PHASE_TABLE/TARGETS の9路エントリ、JIGO_LARGE_LEAD_9X9_CAP、
_jigo_compute_effective_max_loss の board_size<=9 キャップ分岐を削除。
9路は新 ai:jigo9 に集約。関連する9路参照テストも削除。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `generate_move` に `board_size==9` deception 分岐を追加

deception 有効時、9路で `jigo9_*` スライダーを読み phase_table_override / target_overrides / eff_target を構築する分岐を追加。

**Files:**
- Modify: `katrain/core/ai.py`（`generate_move` の deception ブロック、現1003-1035行付近）

- [ ] **Step 1: phase_table_override / target_overrides 構築に `==9` 分岐を追加**

`katrain/core/ai.py` の `if board_size_for_phase == 13:` ブロック（phase_table_override 構築、現1006-1017行）の直後に `elif` を追加:

```python
            elif board_size_for_phase == 9:
                phase_table_override = [
                    (self.settings.get("jigo9_phase1_start", 6),  "phase1"),
                    (self.settings.get("jigo9_phase2_start", 16), "phase2"),
                    (self.settings.get("jigo9_phase3_start", 30), "phase3"),
                ]
                p1_target = self.settings.get("jigo9_phase1_target", -1.5)
                p2_target = self.settings.get("jigo9_phase2_target", -0.5)
                target_overrides = {
                    "phase1": (p1_target, p1_target + 1.0),
                    "phase2": (p2_target, p2_target + 1.0),
                }
```

- [ ] **Step 2: eff_target 解決を `==13` / `==9` / else の3分岐に整理**

eff_target/eff_target_max 解決部（現1026-1035行）を以下で置換:

```python
            # Phase 1/2 の eff_target/eff_target_max を決定
            if board_size_for_phase == 13:
                eff_target, eff_target_max = _jigo_resolve_path_overrides(
                    phase, target_score, target_score_max, self.settings,
                    key_prefix="jigo_deception_13",
                )
            elif board_size_for_phase == 9:
                eff_target, eff_target_max = _jigo_resolve_path_overrides(
                    phase, target_score, target_score_max, self.settings,
                    key_prefix="jigo9",
                )
            else:
                overrides = JIGO_DECEPTION_TARGETS.get((board_size_for_phase, phase))
                if overrides is None:
                    overrides = JIGO_DECEPTION_TARGETS.get((19, phase))
                if overrides is not None:
                    eff_target, eff_target_max = overrides
```

- [ ] **Step 3: 構文チェック（import が壊れていないこと）**

Run: `python -c "import katrain.core.ai"`
Expected: エラーなく終了（Kivy 警告は無視）

- [ ] **Step 4: 既存 deception テストが緑のままであることを確認**

Run: `pytest tests/test_jigo_deception.py -v`
Expected: PASS（13/19路の phase 解決は不変）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "$(cat <<'EOF'
feat(jigo): generate_move に9路 deception 分岐を追加

board_size==9 で jigo9_* スライダーを読み phase 境界・target を構築。
eff_target 解決を13路/9路/その他の3分岐に整理。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `Jigo9Strategy` クラスと戦略登録

新戦略クラス本体・`@register_strategy`・import・`AI_JIGO_9` 定数・各種登録・`ai_rank_estimation` を追加。

**Files:**
- Modify: `katrain/core/constants.py`（定数・登録）
- Modify: `katrain/core/ai.py`（import・クラス・`ai_rank_estimation`）
- Test: `tests/test_jigo9.py`（Task 2 の `TestJigo9Forced` がここで緑になる）

- [ ] **Step 1: `constants.py` に定数と登録を追加**

`katrain/core/constants.py`:

`AI_JIGO = "ai:jigo"`（44行）の直後に追加:

```python
AI_JIGO_9 = "ai:jigo9"
```

`AI_STRATEGIES_ENGINE`（65行）に `AI_JIGO_9` を追加:

```python
AI_STRATEGIES_ENGINE = [AI_DEFAULT, AI_HANDICAP, AI_SCORELOSS, AI_SIMPLE_OWNERSHIP, AI_JIGO, AI_JIGO_9, AI_ANTIMIRROR]
```

`AI_STRATEGIES_RECOMMENDED_ORDER`（69-91行）の `AI_JIGO,` 行直後に `AI_JIGO_9,` を追加。

`AI_STRENGTH`（93-115行）に追加（`AI_JIGO: float("nan"),` の直後）:

```python
    AI_JIGO_9: float("nan"),
```

- [ ] **Step 2: `AI_OPTION_VALUES` に9路キーを追加し `max_loss_per_move` に3.3を足す**

`katrain/core/constants.py`:

`"max_loss_per_move": [3.0, 4.0, 5.6, 7.0],`（192行）を変更:

```python
    "max_loss_per_move": [3.0, 3.3, 4.0, 5.6, 7.0],
```

JigoStrategy ブロック末尾（`"jigo_force_sanrensei": "bool",` の直後、213行付近）に追加:

```python
    # ===== Jigo9Strategy（9路専用） =====
    "jigo9_phase1_start": [4, 6, 8, 10],
    "jigo9_phase2_start": [12, 16, 20, 24],
    "jigo9_phase3_start": [26, 30, 34, 38],
    "jigo9_phase1_target": [-1.0, -1.5, -2.0, -2.5],
    "jigo9_phase2_target": [-0.5, -1.0, -1.5],
```

- [ ] **Step 3: `AI_OPTION_ORDER` に9路キーの表示順を追加**

`katrain/core/constants.py` の `AI_OPTION_ORDER`、`"jigo_force_sanrensei": 16,`（282行）の直後に追加:

```python
    "jigo9_phase1_start": 11,
    "jigo9_phase2_start": 12,
    "jigo9_phase3_start": 13,
    "jigo9_phase1_target": 14,
    "jigo9_phase2_target": 15,
```

（共有キー `target_score`=0 / `target_score_max`=1 / `max_loss_per_move`=2 / `min_human_policy`=3 / `jigo_mode`=4 / `jigo_deception`=10 は既存値を流用。GUI は表示対象キーのみを order 昇順で並べるため gap は問題なし）

- [ ] **Step 4: `ai.py` の import に `AI_JIGO_9` を追加**

`katrain/core/ai.py:9` の import 行に `AI_JIGO_9` を追加:

```python
    AI_DEFAULT, AI_HANDICAP, AI_INFLUENCE, AI_INFLUENCE_ELO_GRID, AI_JIGO, AI_JIGO_9,
```

- [ ] **Step 5: `ai_rank_estimation` に `AI_JIGO_9` を追加**

`katrain/core/ai.py:296` を変更:

```python
    if strategy in [AI_DEFAULT, AI_HANDICAP, AI_JIGO, AI_JIGO_9, AI_PRO]:
        return 9
```

- [ ] **Step 6: `Jigo9Strategy` クラスを定義**

`katrain/core/ai.py` の `JigoStrategy` クラス定義の**直後**（`generate_move` の最後の `return` を含むメソッド群の後、次の `@register_strategy` または関数の前）に追加:

```python
@register_strategy(AI_JIGO_9)
class Jigo9Strategy(JigoStrategy):
    """持碁（9路）専用モード。JigoStrategy を継承し generate_move を流用。

    9路に無関係な上級設定（human_profile / jigo_dynamic_rank /
    jigo_large_lead_delta / jigo_equivalent_epsilon）は FORCED_SETTINGS で
    無効化値に固定し、GUI 非表示・config 非格納のままコードで確実に無効化する。
    deception は generate_move の board_size==9 分岐で jigo9_* スライダーを読む。
    """

    FORCED_SETTINGS = {
        "jigo_equivalent_epsilon": 0.0,
        "jigo_large_lead_delta": float("inf"),  # large-lead 緩和を無効化
        "jigo_dynamic_rank": False,
        "human_profile": "rank_9d",
    }
```

- [ ] **Step 7: `tests/test_jigo9.py` に `TestJigo9Forced` を追加し全体を確認**

`tests/test_jigo9.py` の import を更新（`Jigo9Strategy` を追加）:

```python
from katrain.core.ai import JigoStrategy, Jigo9Strategy
```

ファイル末尾に追加:

```python
class TestJigo9Forced:
    """Jigo9Strategy は FORCED_SETTINGS で4設定を無効化値に固定"""

    def test_epsilon_forced_to_zero(self):
        obj = _bare(Jigo9Strategy, {"jigo_equivalent_epsilon": 0.7})
        assert obj._jigo_get("jigo_equivalent_epsilon", 0.5) == 0.0

    def test_large_lead_delta_forced_to_inf(self):
        obj = _bare(Jigo9Strategy, {"jigo_large_lead_delta": 5.0})
        assert obj._jigo_get("jigo_large_lead_delta", 5.0) == float("inf")

    def test_dynamic_rank_forced_false(self):
        obj = _bare(Jigo9Strategy, {"jigo_dynamic_rank": True})
        assert obj._jigo_get("jigo_dynamic_rank", False) is False

    def test_human_profile_forced_9d(self):
        obj = _bare(Jigo9Strategy, {"human_profile": "rank_5d"})
        assert obj._jigo_get("human_profile", "rank_9d") == "rank_9d"

    def test_non_forced_key_passes_through(self):
        obj = _bare(Jigo9Strategy, {"max_loss_per_move": 4.0})
        assert obj._jigo_get("max_loss_per_move", 3.3) == 4.0
```

Run: `pytest tests/test_jigo9.py -v`
Expected: PASS（`TestJigoGetBase` 3件 + `TestJigo9Forced` 5件）

Run: `python -c "from katrain.core.ai import STRATEGY_REGISTRY; from katrain.core.constants import AI_JIGO_9; print(STRATEGY_REGISTRY[AI_JIGO_9].__name__)"`
Expected: `Jigo9Strategy`

- [ ] **Step 8: コミット**

```bash
git add katrain/core/constants.py katrain/core/ai.py tests/test_jigo9.py
git commit -m "$(cat <<'EOF'
feat(jigo): 持碁（9路）専用戦略 Jigo9Strategy を追加

ai:jigo9 を新設・登録（ENGINE/RECOMMENDED_ORDER/STRENGTH/ai_rank_estimation）。
9路専用スライダー jigo9_phase* を AI_OPTION_VALUES/ORDER に追加、
max_loss_per_move に3.3を追加。上級4設定は FORCED_SETTINGS で無効化。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: config.json（パッケージ＋ユーザーローカル）に `ai:jigo9` セクション追加

GUI は config に保存済みかつ `AI_OPTION_VALUES` 登録済みのキーのみ表示する。11キーちょうどを格納する（外す4設定は格納しない）。

**Files:**
- Modify: `katrain/config.json`
- Modify: `C:\Users\iwaki\.katrain\config.json`（**メインセッションで直接Edit**）

- [ ] **Step 1: パッケージ `katrain/config.json` の `ai` セクションに `ai:jigo9` を追加**

`"ai:jigo"` セクションの直後に以下を追加（11キー、deception スライダーは既定値）:

```json
        "ai:jigo9": {
            "target_score": 0.5,
            "target_score_max": 5.0,
            "max_loss_per_move": 3.3,
            "min_human_policy": 0.02,
            "jigo_mode": "natural",
            "jigo_deception": false,
            "jigo9_phase1_start": 6,
            "jigo9_phase2_start": 16,
            "jigo9_phase3_start": 30,
            "jigo9_phase1_target": -1.5,
            "jigo9_phase2_target": -0.5
        },
```

- [ ] **Step 2: パッケージ config の JSON 妥当性を確認**

Run: `python -c "import json; d=json.load(open('katrain/config.json',encoding='utf-8')); print(list(d['ai']['ai:jigo9'].keys()))"`
Expected: 11キーのリストが表示される

- [ ] **Step 3: ユーザーローカル `C:\Users\iwaki\.katrain\config.json` に同じ `ai:jigo9` セクションを追加**

メインセッションで Read → Edit。`"ai:jigo"` セクションの直後に Step 1 と同一の `ai:jigo9` ブロックを挿入する。

> ローカル config の構造はパッケージと同じく `{"ai": {...}}` 階層。Read で `"ai:jigo"` の位置を特定してから Edit。

- [ ] **Step 4: ユーザーローカル config の妥当性を確認**

Run: `python -c "import json; d=json.load(open(r'C:/Users/iwaki/.katrain/config.json',encoding='utf-8')); print(list(d['ai']['ai:jigo9'].keys()))"`
Expected: 11キーのリストが表示される

- [ ] **Step 5: コミット（パッケージ config のみ。ユーザーローカルは git 管理外）**

```bash
git add katrain/config.json
git commit -m "$(cat <<'EOF'
feat(jigo): ai:jigo9 のデフォルト設定を config.json に追加

9路向け既定（target_score_max=5.0, max_loss=3.3, phase3_start=30 等）。
ユーザーローカル config にも同キーを追加済み（GUI表示用、git管理外）。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: i18n（戦略名・ヘルプ・短ラベル）

`ai:jigo9` / `aihelp:jigo9` と `jigo9_phase*` の短ラベルを en/jp に追加し `.mo` 再コンパイル。

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`

- [ ] **Step 1: 日本語 `.po` に追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `aihelp:jigo` エントリ（530行）の直後に追加:

```po
msgid "ai:jigo9"
msgstr "Kata持碁（9路）"

msgid "aihelp:jigo9"
msgstr "9路盤専用の持碁モード。target_score〜target_score_max 目の僅差で勝つことをめざします。1手あたり max_loss_per_move 目以下 & humanPolicy >= min_human_policy の手のみ選び、人間らしくない悪手を避けます。jigo_mode: natural=範囲内は最善手 / maintain=常に target に寄せる。jigo_deception: ON で序中盤に意図的に劣勢を演出 → 終盤で逆転する人間らしい棋風。Phase1/2/3 の開始手数と Phase1/2 の目標スコア差をスライダーで調整可能。各 Phase 中は target_max = target+1.0 で自動設定、過剰優勢/劣勢(±5目)で安全弁が Phase3 に強制ジャンプ。9路は終局が早いため Phase3（挽回開始）を早めに設定するのが推奨。段位は rank_9d 固定。19/13路盤では従来の Kata持碁 を使ってください。"

msgid "jigo9_phase1_start"
msgstr "[9路] Phase1開始手数 (控えめに打ち始める)"

msgid "jigo9_phase2_start"
msgstr "[9路] Phase2開始手数 (徐々に target に戻し始める)"

msgid "jigo9_phase3_start"
msgstr "[9路] Phase3開始手数 (通常 Jigo に復帰、勝ちに行く)"

msgid "jigo9_phase1_target"
msgstr "[9路] Phase1 目標スコア差 (例: -1.5=1.5目劣勢を維持)"

msgid "jigo9_phase2_target"
msgstr "[9路] Phase2 目標スコア差 (Phase3 復帰前の中間値)"
```

- [ ] **Step 2: 英語 `.po` に追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の `ai:jigo`/`aihelp:jigo` エントリ群の直後に追加:

```po
msgid "ai:jigo9"
msgstr "Kata Jigo (9x9)"

msgid "aihelp:jigo9"
msgstr "Jigo mode dedicated to the 9x9 board. Aims to win by a small margin of target_score to target_score_max points. Only plays moves with loss <= max_loss_per_move and humanPolicy >= min_human_policy, avoiding inhuman blunders. jigo_mode: natural = best move within range / maintain = always steer toward target. jigo_deception: ON makes the AI deliberately fall behind in the early/middle game and recover late for a human-like style. Phase1/2/3 start moves and Phase1/2 target score gaps are adjustable via sliders. During each phase target_max = target+1.0 is set automatically; a safety valve (±5 points) jumps to Phase3 on over/under-performance. Since 9x9 games end quickly, set Phase3 (recovery start) early. Rank is fixed at rank_9d. For 19x19/13x13 use the regular Kata Jigo."

msgid "jigo9_phase1_start"
msgstr "[9x9] Phase1 start move (begin playing modestly)"

msgid "jigo9_phase2_start"
msgstr "[9x9] Phase2 start move (gradually return toward target)"

msgid "jigo9_phase3_start"
msgstr "[9x9] Phase3 start move (return to normal Jigo, play to win)"

msgid "jigo9_phase1_target"
msgstr "[9x9] Phase1 target score gap (e.g. -1.5 = stay 1.5 pts behind)"

msgid "jigo9_phase2_target"
msgstr "[9x9] Phase2 target score gap (midpoint before Phase3 return)"
```

- [ ] **Step 3: `.mo` を再コンパイル**

Run: `python tools/compile_mo.py`
Expected: エラーなく完了（en/jp の .mo が更新される）

- [ ] **Step 4: 翻訳ロードを確認**

Run: `python -c "from katrain.core.lang import rank_label" 2>NUL & python -c "import gettext; t=gettext.translation('katrain','katrain/i18n/locales',languages=['jp']); t.install(); print(t.gettext('ai:jigo9'))"`
Expected: `Kata持碁（9路）`

> 上記が環境差で動かない場合は、`python -m katrain` 起動後に GUI の AI 選択ドロップダウンに「Kata持碁（9路）」が出ることで代替確認。

- [ ] **Step 5: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "$(cat <<'EOF'
feat(i18n): ai:jigo9 の戦略名・ヘルプ・短ラベルを追加（en/jp）

Kata持碁（9路）の表示名と jigo9_phase* スライダー説明を追加し
.mo を再コンパイル。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: デバッグCLI（katrain_debug）対応

`--strategy jigo9` を使えるようにし、jigo_metrics 集計を9路でも有効化。

**Files:**
- Modify: `katrain_debug/runner.py:20-43`（`STRATEGY_NAME_MAP`）
- Modify: `katrain_debug/batch_eval.py:193`（jigo_metrics 分岐）

- [ ] **Step 1: `runner.py` にマッピング追加**

`katrain_debug/runner.py` の import に `AI_JIGO_9` を追加（既存の `AI_JIGO` import 行に併記）し、`STRATEGY_NAME_MAP`（20-43行）の `"jigo": AI_JIGO,` の直後に追加:

```python
    "jigo9": AI_JIGO_9,
```

- [ ] **Step 2: `batch_eval.py` の jigo_metrics 分岐を拡張**

`katrain_debug/batch_eval.py:193` を変更:

```python
        if strategy_name in ("jigo", "jigo9"):
```

- [ ] **Step 3: CLI の戦略解決を確認（KataGo 起動なしの軽量チェック）**

Run: `python -c "from katrain_debug.runner import STRATEGY_NAME_MAP; from katrain.core.constants import AI_JIGO_9; assert STRATEGY_NAME_MAP['jigo9']==AI_JIGO_9; print('ok')"`
Expected: `ok`

- [ ] **Step 4: コミット**

```bash
git add katrain_debug/runner.py katrain_debug/batch_eval.py
git commit -m "$(cat <<'EOF'
feat(debug): katrain_debug に jigo9 戦略を追加

--strategy jigo9 を STRATEGY_NAME_MAP に登録し、jigo_metrics 集計を
9路でも有効化。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: ドキュメント更新

`.claude/rules/ai-parameters.md` と `CLAUDE.md` にパラメータ表・概要を反映。

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（持碁戦略セクション）
- Modify: `CLAUDE.md`（概要の主な改修一覧）

> **注意（CLAUDE.md 由来）**: `.claude/rules/` 配下の Edit が `dontAsk` モードで拒否される既知問題あり。拒否されたらサブエージェント経由で編集・コミットする。

- [ ] **Step 1: `ai-parameters.md` に「持碁（9路）戦略」サブセクションを追加**

`.claude/rules/ai-parameters.md` の「持碁戦略（JigoStrategy）」セクションの末尾に追加:

```markdown
### 持碁（9路）戦略（Jigo9Strategy）

9路盤専用の独立戦略（`ai:jigo9`）。`JigoStrategy` を継承し generate_move を流用。9路に無関係な上級設定は `FORCED_SETTINGS` で無効化（`human_profile`→rank_9d固定 / `jigo_dynamic_rank`→false / `jigo_large_lead_delta`→inf / `jigo_equivalent_epsilon`→0.0）。deception は generate_move の `board_size==9` 分岐で9路スライダーを読む（13路機構 `_jigo_resolve_path_overrides` を `key_prefix="jigo9"` で共有）。既存 `ai:jigo` は19/13路専用（9路コードは削除）。

| パラメータ | デフォルト | 選択肢 | 備考 |
|---|---|---|---|
| target_score | 0.5 | 既存流用 | 狙う目差 |
| target_score_max | 5.0 | 5/10/15 | 9路は10目で実質勝勢のため5.0既定 |
| max_loss_per_move | 3.3 | 3.0/3.3/4.0/5.6/7.0 | 9路 HumanStyle NORMAL=3.3 |
| min_human_policy | 0.02 | (0.005..0.05) | humanPolicy 最低閾値 |
| jigo_mode | natural | natural/maintain | |
| jigo_deception | false | bool | deception 有効化 |
| jigo9_phase1_start | 6 | 4/6/8/10 | phase0→1 境界手数 |
| jigo9_phase2_start | 16 | 12/16/20/24 | phase1→2 境界手数 |
| jigo9_phase3_start | 30 | 26/30/34/38 | phase2→3（挽回開始）。早いほど挽回が間に合う |
| jigo9_phase1_target | -1.5 | -1.0/-1.5/-2.0/-2.5 | target_max=target+1.0 自動 |
| jigo9_phase2_target | -0.5 | -0.5/-1.0/-1.5 | 同上 |

検証は GUI 実戦のみ（deception は trajectory 形成型で batch 評価不可）。CLI: `python -m katrain_debug --sgf <9路SGF> --move N --strategy jigo9`。Spec: `docs/superpowers/specs/2026-06-04-jigo-9x9-dedicated-mode-design.md`
```

既存「持碁戦略（JigoStrategy）」の対応盤面記述を「全盤面」→「19路・13路（9路は持碁（9路）戦略へ分離）」に更新。

- [ ] **Step 2: `CLAUDE.md` の概要を更新**

`CLAUDE.md` の「主な改修」段落の Jigo 記述に追記:

```markdown
Jigo には9路専用の独立戦略 `ai:jigo9`（持碁（9路））を追加（既存 `ai:jigo` は19/13路専用に整理）。9路 deception の phase 境界・target を5スライダーで調整可能（phase3前倒しで挽回を間に合わせる）
```

- [ ] **Step 3: コミット**

```bash
git add .claude/rules/ai-parameters.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(jigo): 持碁（9路）戦略のパラメータ表と概要を追記

ai-parameters.md に Jigo9Strategy セクション、CLAUDE.md 概要に9路分離を反映。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: 全体回帰テストと GUI スモーク確認

**Files:** なし（検証のみ）

- [ ] **Step 1: jigo 関連ユニットテストを一括実行**

Run: `pytest tests/test_jigo.py tests/test_jigo_deception.py tests/test_jigo9.py -v`
Expected: 全 PASS

- [ ] **Step 2: humanSL モデル不要のテストスイート全体を実行**

Run: `pytest --ignore=tests/test_ai.py -q`
Expected: 全 PASS（既存テストの回帰なし）

- [ ] **Step 3: GUI スモーク（手動）**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level"` を `1` にして `python -m katrain` 起動:
- AI 選択に「Kata持碁（9路）」が出ること
- 選択時の設定欄に11項目（target_score 〜 jigo9_phase2_target）だけが出て、19/13路専用項目（force_sanrensei・phase_13・human_profile 等）が**出ない**こと
- 9路盤で deception ON にして対局、ログ `[JigoStrategy] Deception: ... board=9, phase=...` に phase3 が phase3_start 手目で発動することを確認
- 確認後 `debug_level` を `0` に戻す

- [ ] **Step 4: ブランチ完了処理**

superpowers:finishing-a-development-branch スキルで merge/PR/cleanup を判断する。

---

## Self-Review 結果

- **Spec coverage**: 仕様の全要素（独立戦略追加=Task5 / 既存から9路除去=Task3 / 5スライダー deception=Task1,4,5 / FORCED_SETTINGS 無効化=Task2,5 / config=Task6 / i18n=Task7 / CLI=Task8 / docs=Task9）にタスク対応あり。
- **Placeholder scan**: プレースホルダなし。全ステップに実コード・実コマンド・期待値を記載。
- **Type consistency**: `_jigo_resolve_path_overrides`（key_prefix）・`_JIGO_PATH_TARGET_DEFAULTS`・`FORCED_SETTINGS`・`_jigo_get`・`Jigo9Strategy`・`AI_JIGO_9`・キー名 `jigo9_phase{1,2,3}_{start}` / `jigo9_phase{1,2}_target` は全タスク間で一貫。
- **依存順**: Task1（汎用化）→ Task4（9路分岐が新関数を使用）、Task2（_jigo_get 土台）→ Task5（Jigo9Strategy が FORCED_SETTINGS を使用）、Task5 完了で Task2 の `TestJigo9Forced` が緑化。Task3 は独立だが Task4 より前に実施し9路テスト赤線を解消。
