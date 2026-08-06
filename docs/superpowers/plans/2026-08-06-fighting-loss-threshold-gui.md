# 力戦派 悪手フィルタ閾値の GUI 化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 力戦派 `fighting_mode: human` / `complex` の悪手フィルタ閾値を、9路と 13/19路で独立した GUI スライダーにする（主目的は閾値の引き下げ）。

**Architecture:** 閾値の「決定」だけを新しい純関数 `_fighting_loss_thresholds()` に切り出し、`FightingStrategy._generate_human()` のハードコード分岐と `complexity_*` 読み出しをその戻り値に置き換える。フィルタ本体（`_filter_moves` / `_complexity_loss_filter` / `_complexity_relaxed_cap` / `_passes_complexity_gate`）は一切変更しない。純関数なので KataGo なしで単体テストできる。

**Tech Stack:** Python 3.12 / pytest / Kivy（GUI 設定は `AI_OPTION_VALUES` 駆動）

## Global Constraints

- 適用範囲は `ai:p:fighting` の `fighting_mode` が `human` または `complex` のときのみ。`classic` / `scoreloss` および他戦略（`ai:human` / 攻城 / 狩猟 / 持碁 / 一致率追随）は挙動不変。
- 既定値はすべて現行のハードコード値と一致させる: 13/19路 序盤 2.8 / 中盤以降 5.6、9路 序盤 0.5 / 中盤以降 3.3。既定のままなら挙動は現状維持。
- 盤面サイズの分類は現行と同じ 2 クラス: `bx == 9 and by == 9` が 9路、それ以外はすべて 13/19路扱い。
- 序盤境界は `math.ceil(0.14 * bx * by)`（19路=51 / 13路=24 / 9路=12）。`current_move < opening_boundary` が序盤。
- **コード内フォールバックは config.json の既定値と一致させる**（直近コミット `58a0feb` の方針に合わせる）。
- 安全弁 `_SAFETY_LOSS_THRESHOLD`（4.0）は変更しない。引き下げ用途ではフィルタが先に切るため無害。
- 段階的緩和フェイルセーフ（×1.5 → ×2.0 → 9.0）は維持する。
- コミットメッセージは日本語・Conventional Commits 形式。
- `black` はファイル全体を再フォーマットしてしまうので**走らせない**（既存コードベースが未整形）。

---

### Task 1: 閾値解決の純関数 `_fighting_loss_thresholds`

**Files:**
- Modify: `katrain/core/ai.py`（`_complexity_loss_filter` の直後、現状 6173 行付近に追加）
- Test: `tests/test_fighting_complexity.py`

**Interfaces:**
- Consumes: なし（新規の独立ユニット）
- Produces: `_fighting_loss_thresholds(settings: Dict, board_size: Tuple[int, int], current_move: int) -> Tuple[float, float, float]`
  戻り値は `(bad_move_threshold, complexity_base_max_loss, complexity_max_loss)`。Task 2 がこの3値を使う。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fighting_complexity.py` の import 群（現状 11 行目 `from katrain.core.ai import _floor_budget_weights` の直後）に追加:

```python
from katrain.core.ai import _fighting_loss_thresholds
```

ファイル末尾に以下のクラスを追加:

```python
class TestFightingLossThresholds:
    """悪手フィルタ閾値の盤面サイズ×フェーズ解決。

    序盤境界 = ceil(0.14 * マス数) → 19路 51 / 13路 24 / 9路 12。
    current_move < 境界 が序盤。
    """

    def test_19_opening_default(self):
        assert _fighting_loss_thresholds({}, (19, 19), 0)[0] == 2.8
        assert _fighting_loss_thresholds({}, (19, 19), 50)[0] == 2.8

    def test_19_normal_default(self):
        assert _fighting_loss_thresholds({}, (19, 19), 51)[0] == 5.6

    def test_9_opening_default(self):
        assert _fighting_loss_thresholds({}, (9, 9), 0)[0] == 0.5
        assert _fighting_loss_thresholds({}, (9, 9), 11)[0] == 0.5

    def test_9_normal_default(self):
        assert _fighting_loss_thresholds({}, (9, 9), 12)[0] == 3.3

    def test_13_uses_19_family(self):
        # 13路は 9路系ではなく 13/19路系の値を使う（境界は 24）
        assert _fighting_loss_thresholds({}, (13, 13), 23)[0] == 2.8
        assert _fighting_loss_thresholds({}, (13, 13), 24)[0] == 5.6

    def test_settings_override_19(self):
        s = {"fighting_human_opening_max_loss": 1.5, "fighting_human_max_loss": 3.0}
        assert _fighting_loss_thresholds(s, (19, 19), 0)[0] == 1.5
        assert _fighting_loss_thresholds(s, (19, 19), 51)[0] == 3.0

    def test_settings_override_9(self):
        s = {"fighting_human_opening_max_loss_9": 0.3, "fighting_human_max_loss_9": 2.0}
        assert _fighting_loss_thresholds(s, (9, 9), 0)[0] == 0.3
        assert _fighting_loss_thresholds(s, (9, 9), 12)[0] == 2.0

    def test_9_settings_do_not_leak_to_19(self):
        s = {"fighting_human_max_loss_9": 2.0, "complexity_base_max_loss_9": 4.0}
        assert _fighting_loss_thresholds(s, (19, 19), 51) == (5.6, 5.6, 10.0)

    def test_19_settings_do_not_leak_to_9(self):
        s = {"fighting_human_max_loss": 9.0, "complexity_base_max_loss": 8.0}
        assert _fighting_loss_thresholds(s, (9, 9), 12) == (3.3, 3.3, 6.0)

    def test_complexity_caps_default_by_board(self):
        assert _fighting_loss_thresholds({}, (19, 19), 51)[1:] == (5.6, 10.0)
        assert _fighting_loss_thresholds({}, (9, 9), 12)[1:] == (3.3, 6.0)

    def test_complexity_caps_override_by_board(self):
        s = {
            "complexity_base_max_loss": 7.0,
            "complexity_max_loss": 12.0,
            "complexity_base_max_loss_9": 4.0,
            "complexity_max_loss_9": 5.0,
        }
        assert _fighting_loss_thresholds(s, (19, 19), 51)[1:] == (7.0, 12.0)
        assert _fighting_loss_thresholds(s, (9, 9), 12)[1:] == (4.0, 5.0)

    def test_complexity_caps_are_phase_independent(self):
        # 上限2値はフェーズで変わらない（変わるのは bad_move_threshold だけ）
        assert _fighting_loss_thresholds({}, (19, 19), 0)[1:] == _fighting_loss_thresholds({}, (19, 19), 51)[1:]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_fighting_complexity.py::TestFightingLossThresholds -v`
Expected: FAIL — `ImportError: cannot import name '_fighting_loss_thresholds' from 'katrain.core.ai'`

- [ ] **Step 3: 最小実装を書く**

`katrain/core/ai.py` の `_complexity_loss_filter` 関数の直後（現状 6173 行、`def _get_corner_star_points` の直前）に追加:

```python
_FIGHTING_LOSS_DEFAULTS = {
    # (盤面クラス): (序盤閾値, 中盤以降閾値, complexity base 上限, complexity max 上限)
    "9": (0.5, 3.3, 3.3, 6.0),
    "std": (2.8, 5.6, 5.6, 10.0),
}


def _fighting_loss_thresholds(settings, board_size, current_move):
    """力戦派 human/complex の損失閾値を盤面サイズ×フェーズで解決する。

    settings: ai:p:fighting の設定 dict
    board_size: (bx, by)
    current_move: 現在の手数（0 始まり）

    戻り値: (bad_move_threshold, complexity_base_max_loss, complexity_max_loss)

    bad_move_threshold は序盤/中盤以降で切り替わる。complexity の2上限はフェーズ
    非依存で、盤面サイズだけで決まる。9路と 13/19路は完全に独立したキーを使うので
    片方の設定がもう片方へ漏れない。
    """
    bx, by = board_size
    if bx == 9 and by == 9:
        suffix = "_9"
        opening_default, normal_default, base_default, max_default = _FIGHTING_LOSS_DEFAULTS["9"]
    else:
        suffix = ""
        opening_default, normal_default, base_default, max_default = _FIGHTING_LOSS_DEFAULTS["std"]

    opening_boundary = math.ceil(0.14 * bx * by)
    if current_move < opening_boundary:
        bad_move_threshold = settings.get(f"fighting_human_opening_max_loss{suffix}", opening_default)
    else:
        bad_move_threshold = settings.get(f"fighting_human_max_loss{suffix}", normal_default)

    return (
        bad_move_threshold,
        settings.get(f"complexity_base_max_loss{suffix}", base_default),
        settings.get(f"complexity_max_loss{suffix}", max_default),
    )
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_fighting_complexity.py -v`
Expected: PASS（新規 12 個 + 既存すべて）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_fighting_complexity.py
git commit -m "feat(fighting): 悪手フィルタ閾値を盤面サイズ×フェーズで解決する純関数を追加

_fighting_loss_thresholds を追加。9路と13/19路で独立したキーを引き、
片方の設定がもう片方へ漏れないようにする。既定値は現行のハードコード値と同一。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `_generate_human` を新関数に配線する

**Files:**
- Modify: `katrain/core/ai.py:5640-5649`（ハードコード分岐の置換）
- Modify: `katrain/core/ai.py:5729`（`complexity_max_loss` の読み出し）
- Modify: `katrain/core/ai.py:5731`（`complexity_base_max_loss` の読み出し）

**Interfaces:**
- Consumes: Task 1 の `_fighting_loss_thresholds(settings, board_size, current_move) -> (float, float, float)`
- Produces: なし（既存のローカル変数 `BAD_MOVE_THRESHOLD` / `complexity_base_max_loss` / `complexity_max_loss` の値が変わるだけ。`_complexity_loss_filter` のシグネチャは不変）

- [ ] **Step 1: 閾値決定部を置換**

`katrain/core/ai.py` の以下のブロック（`# --- 悪手フィルタ ---` コメント直後、現状 5640-5649 行）:

```python
        bx, by = board_size
        opening_boundary = math.ceil(0.14 * bx * by)
        if bx == 9 and by == 9:
            OPENING_THRESHOLD = 0.5
            NORMAL_THRESHOLD = 3.3
        else:
            OPENING_THRESHOLD = 2.8
            NORMAL_THRESHOLD = 5.6
        current_move = self.cn.depth
        BAD_MOVE_THRESHOLD = OPENING_THRESHOLD if current_move < opening_boundary else NORMAL_THRESHOLD
```

を、次に置き換える:

```python
        bx, by = board_size
        current_move = self.cn.depth
        BAD_MOVE_THRESHOLD, _COMPLEXITY_BASE_CAP, _COMPLEXITY_MAX_CAP = _fighting_loss_thresholds(
            self.settings, board_size, current_move
        )
        self.game.katrain.log(
            f"[FightingStrategy:human] Loss thresholds: board={bx}x{by} move={current_move} "
            f"bad_move={BAD_MOVE_THRESHOLD} complexity_base={_COMPLEXITY_BASE_CAP} "
            f"complexity_max={_COMPLEXITY_MAX_CAP}",
            OUTPUT_DEBUG,
        )
```

`opening_boundary` はこの関数内では 5649 行でしか使われていないため、変数ごと削除する
（6455 行以降の同名変数は `HumanStyleStrategy` のもので別物。触らないこと）。
`bx, by` は 5914 行の盤面サイズ判定でまだ使うので残す。

- [ ] **Step 2: complex 側の2つの読み出しを置換**

現状 5728-5731 行:

```python
                lead_threshold = self.settings.get("complexity_lead_threshold", 15.0)
                complexity_max_loss = self.settings.get("complexity_max_loss", 10.0)
                sharpness_min = self.settings.get("complexity_sharpness_min", 3.0)
                complexity_base_max_loss = self.settings.get("complexity_base_max_loss", BAD_MOVE_THRESHOLD)
```

を、次に置き換える（`lead_threshold` と `sharpness_min` は盤面非依存なので変更しない）:

```python
                lead_threshold = self.settings.get("complexity_lead_threshold", 15.0)
                complexity_max_loss = _COMPLEXITY_MAX_CAP
                sharpness_min = self.settings.get("complexity_sharpness_min", 3.0)
                complexity_base_max_loss = _COMPLEXITY_BASE_CAP
```

- [ ] **Step 3: 旧キーの直接参照が残っていないことを確認**

Run: `grep -n "OPENING_THRESHOLD\|NORMAL_THRESHOLD" katrain/core/ai.py`
Expected: 6456-6463 行付近の `HumanStyleStrategy` の分だけがヒットし、5640-5650 行付近には**1件も残っていない**こと。

Run: `grep -n 'settings.get("complexity_max_loss"\|settings.get("complexity_base_max_loss"' katrain/core/ai.py`
Expected: **0 件**（両方とも `_fighting_loss_thresholds` 内に移った）

- [ ] **Step 4: import とシンタックスを確認**

Run: `python -c "import katrain.core.ai as m; print(m._fighting_loss_thresholds({}, (19,19), 51))"`
Expected: `(5.6, 5.6, 10.0)` が出力される

Run: `python -m pytest tests/test_fighting_complexity.py tests/test_ai_options_grid.py -v`
Expected: PASS（全件）

- [ ] **Step 5: 既定値で挙動が変わらないことを実局面で確認**

Run: `python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy fighting --settings fighting_mode=human --output text`
Expected: KataGo が起動して着手が1つ返る（約30秒）。エラー・例外なし。
出力に `Loss thresholds: board=19x19 move=30 bad_move=2.8 complexity_base=5.6 complexity_max=10.0` 相当のログが出ること
（debug ログが見えない場合は `C:\Users\iwaki\.katrain\config.json` の `debug_level` を一時的に 1 にする。確認後 0 に戻すこと）。

- [ ] **Step 6: 引き下げが効くことを確認**

Run: `python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy fighting --settings fighting_mode=human fighting_human_max_loss=2.0 --output text`
Expected: `bad_move=2.8`（move 30 は 19路の序盤なので中盤以降キーは効かない）

Run: `python -m katrain_debug --sgf tests/data/ogs.sgf --move 60 --strategy fighting --settings fighting_mode=human fighting_human_max_loss=2.0 --output text`
Expected: `bad_move=2.0`（move 60 は中盤以降なので引き下げが効く）。
`N moves pass score filter` の N が、同じ局面を既定値（5.6）で回したときより**減っている**こと。

- [ ] **Step 7: コミット**

```bash
git add katrain/core/ai.py
git commit -m "refactor(fighting): human/complex の閾値決定を _fighting_loss_thresholds へ移譲

ハードコードの4値分岐と complexity_* の直接読み出しを純関数の戻り値に置換。
フィルタ本体は無変更で、既定値のままなら挙動も変わらない。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: GUI スライダーと設定既定値

**Files:**
- Modify: `katrain/core/constants.py:141-256`（`AI_OPTION_VALUES` に6キー）
- Modify: `katrain/core/constants.py:258-339`（`AI_OPTION_ORDER` に表示順）
- Modify: `katrain/config.json:259-277`（`ai:p:fighting` に既定値6キー）
- Modify: `C:\Users\iwaki\.katrain\config.json`（同じ6キー。**サブエージェントに委任せずメインセッションで直接 Edit すること**）
- Test: `tests/test_ai_options_grid.py`

**Interfaces:**
- Consumes: Task 1 のキー名6つ — `fighting_human_opening_max_loss` / `fighting_human_max_loss` / `fighting_human_opening_max_loss_9` / `fighting_human_max_loss_9` / `complexity_base_max_loss_9` / `complexity_max_loss_9`
- Produces: なし（GUI 表示のみ）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ai_options_grid.py` の末尾に追加:

```python
def test_fighting_loss_threshold_keys_are_configurable():
    """力戦派の損失閾値6キーが GUI ウィジェットと同梱既定値の両方に登録されていること。"""
    from katrain.core.constants import AI_FIGHTING, AI_OPTION_ORDER, AI_OPTION_VALUES
    from katrain.core.utils import find_package_resource

    keys = [
        "fighting_human_opening_max_loss",
        "fighting_human_max_loss",
        "fighting_human_opening_max_loss_9",
        "fighting_human_max_loss_9",
        "complexity_base_max_loss_9",
        "complexity_max_loss_9",
    ]
    with open(find_package_resource("katrain/config.json"), encoding="utf-8") as f:
        fighting = json.load(f)["ai"][AI_FIGHTING]

    for k in keys:
        assert k in AI_OPTION_VALUES, f"{k} が AI_OPTION_VALUES にない（GUI にスライダーが出ない）"
        assert k in AI_OPTION_ORDER, f"{k} が AI_OPTION_ORDER にない（表示順が不定になる）"
        assert k in fighting, f"{k} が同梱 config.json の {AI_FIGHTING} にない"
        assert fighting[k] in AI_OPTION_VALUES[k], f"{k} の既定値 {fighting[k]} がスライダー候補値にない"


def test_fighting_defaults_match_hardcoded_thresholds():
    """同梱既定値が変更前のハードコード値と一致すること（既定なら挙動不変）。"""
    from katrain.core.constants import AI_FIGHTING
    from katrain.core.utils import find_package_resource

    with open(find_package_resource("katrain/config.json"), encoding="utf-8") as f:
        fighting = json.load(f)["ai"][AI_FIGHTING]

    assert fighting["fighting_human_opening_max_loss"] == 2.8
    assert fighting["fighting_human_max_loss"] == 5.6
    assert fighting["fighting_human_opening_max_loss_9"] == 0.5
    assert fighting["fighting_human_max_loss_9"] == 3.3
    assert fighting["complexity_base_max_loss_9"] == 3.3
    assert fighting["complexity_max_loss_9"] == 6.0
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_ai_options_grid.py -v`
Expected: FAIL — `fighting_human_opening_max_loss が AI_OPTION_VALUES にない（GUI にスライダーが出ない）`

- [ ] **Step 3: `AI_OPTION_VALUES` に6キーを追加**

`katrain/core/constants.py` の `"complexity_sharpness_min": [1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0],`（現状 191 行）の直後に追加:

```python
    # 力戦派 human/complex の悪手フィルタ閾値（9路と13/19路で独立。引き下げ方向に刻みを厚くする）
    "fighting_human_opening_max_loss": [0.5, 1.0, 1.5, 2.0, 2.8, 4.0],       # 13/19路・序盤
    "fighting_human_max_loss": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.6, 7.0, 9.0],  # 13/19路・中盤以降
    "fighting_human_opening_max_loss_9": [0.2, 0.3, 0.5, 1.0, 1.5, 2.0],     # 9路・序盤
    "fighting_human_max_loss_9": [0.5, 1.0, 1.5, 2.0, 2.5, 3.3, 4.0, 5.0],   # 9路・中盤以降
    "complexity_base_max_loss_9": [2.0, 2.5, 3.3, 4.0, 5.0, 6.0],            # 9路・complex 常時上限
    "complexity_max_loss_9": [4.0, 5.0, 6.0, 8.0, 10.0],                     # 9路・complex 緩和上限
```

- [ ] **Step 4: `AI_OPTION_ORDER` に表示順を追加**

`katrain/core/constants.py` の `"complexity_sharpness_min": 10,`（現状 278 行）の直後に追加。
既存の力戦派キーは 0〜10 を使っているので、損失閾値群は 11〜16 にまとめる:

```python
    "fighting_human_opening_max_loss": 11,
    "fighting_human_max_loss": 12,
    "fighting_human_opening_max_loss_9": 13,
    "fighting_human_max_loss_9": 14,
    "complexity_base_max_loss_9": 15,
    "complexity_max_loss_9": 16,
```

- [ ] **Step 5: 同梱 `config.json` に既定値を追加**

`katrain/config.json` の `"ai:p:fighting"` セクション内、`"complexity_sharpness_min": 3.0,`（現状 270 行）の直後に追加:

```json
            "fighting_human_opening_max_loss": 2.8,
            "fighting_human_max_loss": 5.6,
            "fighting_human_opening_max_loss_9": 0.5,
            "fighting_human_max_loss_9": 3.3,
            "complexity_base_max_loss_9": 3.3,
            "complexity_max_loss_9": 6.0,
```

- [ ] **Step 6: テストが通ることを確認**

Run: `python -m pytest tests/test_ai_options_grid.py -v`
Expected: PASS（新規2個 + 既存3個）。特に `test_all_packaged_strategies_fit_in_grid` が
23 項目でも通ること。

- [ ] **Step 7: ユーザーローカル `config.json` に同じキーを追加**

**この編集はメインセッションで直接 Edit すること**（サブエージェントに委任すると反映されないことがある）。
また **KaTrain が起動中だと終了時に上書きされて消える**ので、編集前にウィンドウが閉じていることを確認する。

`C:\Users\iwaki\.katrain\config.json` の `"ai:p:fighting"` 内、`"complexity_sharpness_min": 3.0,` の直後に
Step 5 と同じ6行を追加する。既存の値（`fighting_mode: "complex"` / `complexity_base_max_loss: 6.1` 等）は変更しない。

Run: `python -c "import json; d=json.load(open(r'C:\Users\iwaki\.katrain\config.json', encoding='utf-8'))['ai']['ai:p:fighting']; print({k: v for k, v in d.items() if 'max_loss' in k})"`
Expected: 6つの新キーと既存の `fighting_max_loss` / `complexity_base_max_loss` / `complexity_max_loss` がすべて表示される

- [ ] **Step 8: コミット**

```bash
git add katrain/core/constants.py katrain/config.json tests/test_ai_options_grid.py
git commit -m "feat(fighting): 損失閾値6キーをGUIスライダーとして追加

9路と13/19路を独立させ、序盤/中盤以降も別スライダーにする。
候補値は引き下げ方向に刻みを厚くし、既定値は現行のハードコード値と同一。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: i18n ラベルとドキュメント

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:692-714`
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:1004-1027`
- Modify: `.claude/rules/ai-parameters.md:38-67`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task 3 のキー名6つ
- Produces: なし（最終タスク）

- [ ] **Step 1: 日本語ラベルを追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `msgid "complexity_sharpness_min"` /
`msgstr "鋭さ閾値(scoreStdev)"` のペア（現状 714-715 行付近）の直後に追加:

```po
msgid "fighting_human_opening_max_loss"
msgstr "損失上限:序盤(13/19路)"

msgid "fighting_human_max_loss"
msgstr "損失上限:中盤以降(13/19路)"

msgid "fighting_human_opening_max_loss_9"
msgstr "損失上限:序盤(9路)"

msgid "fighting_human_max_loss_9"
msgstr "損失上限:中盤以降(9路)"

msgid "complexity_base_max_loss_9"
msgstr "常時の損失上限:9路(互角時)"

msgid "complexity_max_loss_9"
msgstr "緩和時の損失上限:9路"
```

- [ ] **Step 2: 日本語のヘルプ本文を修正**

同ファイルの `msgid "aihelp:p:fighting"` の本文（現状 692-700 行付近）にある次の行:

```
"'fighting_max_loss'はScoreLoss/Humanの許容損失目数(小さいほど強). "
```

を、次の2行に置き換える（`fighting_max_loss` は実際には ScoreLoss 専用で Human には効かない）:

```
"'fighting_max_loss'はScoreLoss専用の許容損失目数(小さいほど強). "
"Human拡張/complexの許容損失は'fighting_human_*_max_loss'で調整し, 9路(_9付き)と13/19路は独立. "
```

- [ ] **Step 3: 英語ラベルとヘルプ本文を追加・修正**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の `msgid "complexity_sharpness_min"` /
`msgstr "Sharpness gate (scoreStdev)"` のペア（現状 1027-1028 行付近）の直後に追加:

```po
msgid "fighting_human_opening_max_loss"
msgstr "Loss cap: opening (13/19x19)"

msgid "fighting_human_max_loss"
msgstr "Loss cap: midgame+ (13/19x19)"

msgid "fighting_human_opening_max_loss_9"
msgstr "Loss cap: opening (9x9)"

msgid "fighting_human_max_loss_9"
msgstr "Loss cap: midgame+ (9x9)"

msgid "complexity_base_max_loss_9"
msgstr "Always-on loss cap: 9x9 (even game)"

msgid "complexity_max_loss_9"
msgstr "Max loss when leading: 9x9"
```

同ファイルの `msgid "aihelp:p:fighting"` 本文にある次の行:

```
"'fighting_max_loss': max point loss for ScoreLoss/Human (lower=stronger). "
```

を、次の2行に置き換える:

```
"'fighting_max_loss': max point loss for ScoreLoss mode only (lower=stronger). "
"Human/complex use 'fighting_human_*_max_loss'; 9x9 (_9 suffix) and 13/19x19 are independent. "
```

- [ ] **Step 4: `.mo` を再コンパイルして検証**

Run: `python tools/compile_mo.py`
Expected: エラーなく完了

Run: `python -c "import os; os.environ['KIVY_NO_ARGS']='1'; from katrain.core.lang import i18n; i18n.switch_lang('jp'); print(i18n._('fighting_human_max_loss'))"`
Expected: `損失上限:中盤以降(13/19路)` が出力される（msgid のままなら `.mo` が反映されていない）

- [ ] **Step 5: `.claude/rules/ai-parameters.md` の力戦派テーブルを更新**

`## 力戦派モード（FightingStrategy）` のテーブル（現状 40-49 行）の `fighting_max_loss` 行の備考を
`"scorelossモード専用の悪手フィルタ閾値（目数）"` のまま残し、テーブルの直後にある次の一文:

```
humanモードの悪手フィルタ閾値はHumanStyleStrategyと同じBAD_MOVE_THRESHOLD（19路 NORMAL=5.6 / OPENING=2.8、9路 NORMAL=3.3 / OPENING=0.5）を使用。`fighting_max_loss`は無効。
```

を、次に置き換える:

```
human/complex モードの悪手フィルタ閾値は **GUI 調整可能**（`fighting_max_loss` は無効＝scoreloss 専用）。盤面サイズ×フェーズで独立したキーを引く（`_fighting_loss_thresholds`）。

| パラメータ | デフォルト | 適用 |
|---|---|---|
| fighting_human_opening_max_loss | 2.8 | 13/19路・序盤 |
| fighting_human_max_loss | 5.6 | 13/19路・中盤以降 |
| fighting_human_opening_max_loss_9 | 0.5 | 9路・序盤 |
| fighting_human_max_loss_9 | 3.3 | 9路・中盤以降 |

序盤境界は `ceil(0.14 × 盤面マス数)`（19路=51 / 13路=24 / 9路=12）。安全弁は 4.0 固定なので、閾値を 4.0 超に**引き上げる**と最高重み候補が安全弁で最善手に巻き戻される（引き下げ用途では無害）。
```

さらに `### complexモード（複雑化）` のパラメータテーブル（現状 59-65 行）に2行追加し、
`complexity_base_max_loss` / `complexity_max_loss` の備考に「13/19路専用」を明記する:

```
| complexity_base_max_loss_9 | 3.3 | 2.0/2.5/3.3/4.0/5.0/6.0 | 9路版。既存 complexity_base_max_loss は13/19路専用になった |
| complexity_max_loss_9 | 6.0 | 4.0/5.0/6.0/8.0/10.0 | 9路版。既存 complexity_max_loss は13/19路専用になった |
```

- [ ] **Step 6: `CLAUDE.md` を更新**

`## 概要` の「主な改修」段落にある力戦派の説明（`力戦派には複雑化モード \`complex\`（切りボーナス＋リード適応の損失予算ゲートで盤面を紛れさせる）を追加。` の直後）に、次の一文を挿入する:

```
力戦派の human/complex の悪手フィルタ閾値は **9路と13/19路・序盤と中盤以降で独立した GUI スライダー**（`fighting_human_*_max_loss` / `complexity_*_max_loss_9`、解決は共有純関数 `_fighting_loss_thresholds`）で、既定値は従来のハードコード値と同一。`fighting_max_loss` は scoreloss 専用で human/complex には効かない。
```

- [ ] **Step 7: 全テストを回して回帰がないことを確認**

Run: `python -m pytest --ignore=tests/test_ai.py -q`
Expected: PASS（`test_ai.py` は humanSL モデルが必要なため除外）

- [ ] **Step 8: GUI で実際にスライダーが出ることを確認**

Run: `python -m katrain`
Expected: 起動後、プレイヤー設定 → AI 戦略「力戦派」を選ぶと設定画面に6つの新スライダーが表示され、
値を変更して「設定を更新」すると `C:\Users\iwaki\.katrain\config.json` に保存される。
既存項目のレイアウトが崩れていないこと。確認したら KaTrain を終了する。

- [ ] **Step 9: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.mo .claude/rules/ai-parameters.md CLAUDE.md
git commit -m "docs(fighting): 損失閾値6キーのi18nラベルとドキュメントを追加

fighting_max_loss が ScoreLoss 専用である旨の誤記も修正。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## 完了条件

- [ ] `python -m pytest --ignore=tests/test_ai.py -q` が全 PASS
- [ ] 既定値のまま `katrain_debug` で 19路 move 60 を回すと `bad_move=5.6` がログに出る（現状維持）
- [ ] `fighting_human_max_loss=2.0` を渡すと `bad_move=2.0` になり、フィルタ通過手数が減る
- [ ] GUI の力戦派設定に6スライダーが日本語ラベルで表示される
- [ ] `C:\Users\iwaki\.katrain\config.json` に6キーが入っている
