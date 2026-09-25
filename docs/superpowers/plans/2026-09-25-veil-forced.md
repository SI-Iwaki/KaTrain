# 韜晦の「最善手しか無い手番の外し」実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

日付: 2026-09-25
実行: サブエージェント駆動（worktree `.claude/worktrees/veil-forced`・ブランチ `veil-forced`）。タスクは順に1つずつ、実装 → レビュー → 修正。

**Goal:** 韜晦（veil9/13/19）に、通常の層が最善手しか打てない手番でも、打った後にリードと勝率が残る 9段らしい手があれば打つ層（`<prefix>_forced_mode`・既定 OFF・LOG＝記録のみ・ON）を足し、13路で一致率を平均 30〜45% に近づける。

**Architecture:** 通常の流れが最善手で終わる4つの出口（S10 `no_pool`・S12 `no_natural`・S14 `no_shortlist`・S17 `none_qualified`）の直前で新メソッド `_veil_forced` を呼ぶ。判定は純関数（候補・資格・選択・不変条件）に分け、`_veil_move` は呼び出しを足すだけ。mode 0 では何もしない（クエリ・記録・選ぶ手とも今と同じ）。

**Tech Stack:** Python 3.12・pytest・KaTrain（`katrain/core/ai.py` の韜晦）・gettext（`.po` → `tools/compile_mo.py`）・マニュアル（`tools/build_manual.py`）・自己対局ハーネス（`python -m katrain_debug.selfplay`）。

**Spec:** `docs/superpowers/specs/2026-09-23-veil-strategy-design.md` §14（worktree 内・コミット `aa28bd86`）。§14 が要件の正本。

## Global Constraints

1. **CRLF・black 未整形の既存ファイル**（`katrain/core/ai.py`・`katrain/core/constants.py`・`katrain/config.json`・`katrain/i18n/locales/*/LC_MESSAGES/katrain.po`・`docs/**/*.md`・`docs/manual/src/*.html`・`.claude/rules/*.md`）は **python のパッチスクリプトだけで変える**（`<scratchpad>/crlf_patch.py` を import して `patch(path, [(old, new, count)])`。old/new は LF で書く。件数が合わなければ何も書かずに止まる）。Edit / Write ツールで `.py` を書くと PostToolUse の black フックがファイル全体を整形してしまう（ai.py は 1 万行超の未整形ファイル）。パッチスクリプトは `<scratchpad>` に置いて実行する。
   - 例外: `tests/test_ai_veil.py` は black 整形済み（CRLF）なので Edit ツールで直接変えてよい。
2. 触ってよいのは韜晦（veil 純関数群・Veil9/13/19）とその登録・文書・テストだけ。**難解（Enigma*）・擬態（Mimic13）・その他の戦略のコードと共有メソッド（`_probe_children` など）は変えない**。
3. KataGo を起動しない（テストはすべてスタブ）。`C:/Users/iwaki/.katrain/config.json`（ユーザー設定）は触らない（メインセッションの仕事）。
4. 既存のテストを弱めない。**forced_mode 0（既定）の挙動は1バイトも変えない**＝mode 0 ではクエリ数・`Decision:` の中身・選ぶ手・`_veil_state` の中身が今と同じ（`forced` で始まるキーを足さない）。
5. 安全条件の値（reserve・min_winrate・`SAFETY_DEFAULTS`）と既存の既定値は変えない。新しい4キーのコードの既定は3盤とも `forced_mode` 0。
6. コミットは日本語の Conventional Commits、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
7. テスト: 自分のタスクの focused テスト（`python -m pytest tests/test_ai_veil.py -q` など）と brief が挙げる関連テスト。**全体スイートはコントローラが後で流す**。既知の失敗 `tests/test_ai.py::TestAI::test_ai_strategies` は対象外（`--ignore=tests/test_ai.py`）。
8. i18n を変えたら `python tools/compile_mo.py`、マニュアルの src を変えたら `python tools/build_manual.py`（どちらも worktree のルートで）。

---

## Task 1: 最善手しか無い手番の外しの定数・純関数・不変条件（TDD）

状態: 完了（`931fbb28`）。

**Files:**
- Modify: `katrain/core/ai.py`（定数は `VEIL_BLUNDER_PROB = 0.5 ...` の行の直後・`_VEIL_EPS` の前。純関数は `def veil_decided_verified_ok` の直前。`veil_invariant_ok` に kind `"forced"`）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Produces（Task 3 が使う）:
  - `VEIL_FORCED_PROBES = 4`
  - `veil_forced_candidates(candidates, best_gtp, hp_of, floor, cap, raw_margin=VEIL_RAW_MARGIN, limit=VEIL_FORCED_PROBES) -> list[dict]`（元の dict のコピーに `"hp"` を足したもの）
  - `veil_forced_ok(row, max_loss, lead, min_lead, min_wr) -> bool`（row は `{"cost", "lead_after", "wr_after", ...}`）
  - `veil_forced_pick(rows) -> dict | None`
  - `veil_invariant_ok(chosen, best, cand_gtps, "forced", bounds)`（bounds のキー: `cost` `max_loss` `lead` `min_lead` `wr_after` `min_wr`）

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_ai_veil.py`。import 群に `VEIL_FORCED_PROBES, veil_forced_candidates, veil_forced_ok, veil_forced_pick` を足し、`TestBlunderPick` の後に置く。`cand` と `hp_table` は既存のヘルパー）

```python
class TestForcedConstants:
    def test_constants_match_the_spec(self):
        assert VEIL_FORCED_PROBES == 4


class TestForcedCandidates:
    """spec §14.3 手順4: best・pass 以外で、生の loss <= cap + VEIL_RAW_MARGIN かつ hp >= floor。hp の降順（同点は gtp）。"""

    @staticmethod
    def gtps(cands, hp=None, floor=0.08, cap=3.0, **kw):
        hp_of = hp_table({c["gtp"]: 0.2 for c in cands} if hp is None else hp)
        return [c["gtp"] for c in veil_forced_candidates(cands, "E5", hp_of, floor, cap, **kw)]

    def test_keeps_moves_up_to_cap_plus_the_raw_margin(self):
        cands = [cand("A1", 0.0), cand("B2", 3.0), cand("C3", 3.3), cand("D4", 3.31)]
        assert self.gtps(cands) == ["A1", "B2", "C3"]

    def test_no_lower_bound_on_the_loss(self):
        """通常の層で外れた安い手（同値・支払いの条件で落ちた手）も、この層の条件で拾い直す。"""
        assert self.gtps([cand("A1", -0.2), cand("B2", 0.05)]) == ["A1", "B2"]

    def test_hp_floor_is_inclusive(self):
        cands = [cand("A1", 1.0), cand("B2", 1.0)]
        assert self.gtps(cands, hp={"A1": 0.08, "B2": 0.079}) == ["A1"]

    def test_excludes_the_best_move_and_pass(self):
        cands = [cand("E5", 0.0), cand("pass", 0.5), cand("A1", 0.5)]
        assert self.gtps(cands, hp={"E5": 0.9, "pass": 0.9, "A1": 0.2}) == ["A1"]

    def test_sorted_by_hp_then_gtp_and_cut_at_the_limit(self):
        cands = [cand(g, 1.0) for g in ("D4", "C3", "B2", "A1", "F6")]
        hp = {"D4": 0.3, "C3": 0.2, "B2": 0.2, "A1": 0.1, "F6": 0.5}
        assert self.gtps(cands, hp=hp) == ["F6", "D4", "B2", "C3"]  # 既定の limit は VEIL_FORCED_PROBES = 4
        assert self.gtps(cands, hp=hp, limit=2) == ["F6", "D4"]

    def test_returns_copies_with_hp_and_leaves_the_input_alone(self):
        cands = [cand("A1", 1.0)]
        rows = veil_forced_candidates(cands, "E5", hp_table({"A1": 0.2}), 0.08, 3.0)
        assert rows == [{**cands[0], "hp": 0.2}] and "hp" not in cands[0]


class TestForcedOk:
    """spec §14.3 手順6: cost <= max_loss・lead_after >= min_lead・lead − cost >= min_lead・wr_after >= min_wr。"""

    @staticmethod
    def ok(lead=20.0, max_loss=5.0, min_lead=1.0, min_wr=0.70, **kw):
        row = {"cost": 1.4, "lead_after": 2.6, "wr_after": 0.74, **kw}
        return veil_forced_ok(row, max_loss, lead, min_lead, min_wr)

    def test_accepts_a_move_that_keeps_the_lead_and_the_winrate(self):
        assert self.ok(lead=4.0)

    def test_cost_up_to_max_loss(self):
        assert self.ok(cost=5.0, lead_after=15.0) and not self.ok(cost=5.01, lead_after=15.0)

    def test_lead_after_the_probe_must_keep_min_lead(self):
        assert self.ok(lead_after=1.0) and not self.ok(lead_after=0.99)

    def test_root_lead_minus_cost_must_keep_min_lead(self):
        assert self.ok(lead=4.0, cost=3.0) and not self.ok(lead=4.0, cost=3.01)

    def test_winrate_after_floor(self):
        assert self.ok(wr_after=0.70) and not self.ok(wr_after=0.699)

    @pytest.mark.parametrize("key", ["cost", "lead_after", "wr_after"])
    def test_missing_metrics_fail(self, key):
        assert not self.ok(**{key: None})

    def test_missing_root_lead_fails(self):
        assert not veil_forced_ok({"cost": 1.0, "lead_after": 5.0, "wr_after": 0.9}, 5.0, None, 1.0, 0.7)


class TestForcedPick:
    def test_most_human_move_wins(self):
        rows = [{"gtp": "A1", "hp": 0.2, "cost": 0.5}, {"gtp": "B2", "hp": 0.3, "cost": 2.0}]
        assert veil_forced_pick(rows)["gtp"] == "B2"

    def test_hp_ties_go_to_the_smaller_cost_then_gtp(self):
        rows = [{"gtp": "C3", "hp": 0.3, "cost": 1.0}, {"gtp": "B2", "hp": 0.3, "cost": 0.5},
                {"gtp": "A1", "hp": 0.3, "cost": 0.5}]
        assert veil_forced_pick(rows)["gtp"] == "A1"

    def test_empty_is_none(self):
        assert veil_forced_pick([]) is None
```

`TestInvariant` に次を足す:

```python
    def test_forced_bounds(self):
        cands = {"E5", "D4", "C7"}
        good = {"cost": 1.4, "max_loss": 5.0, "lead": 4.0, "min_lead": 1.0, "wr_after": 0.74, "min_wr": 0.70}
        assert veil_invariant_ok("C7", "E5", cands, "forced", good)
        assert not veil_invariant_ok("C7", "E5", cands, "forced", {**good, "cost": 5.01})
        assert not veil_invariant_ok("C7", "E5", cands, "forced", {**good, "cost": 3.01})  # lead − cost < min_lead
        assert not veil_invariant_ok("C7", "E5", cands, "forced", {**good, "wr_after": 0.69})
        assert not veil_invariant_ok("C7", "E5", cands, "forced", {**good, "wr_after": None})
        assert not veil_invariant_ok("C7", "E5", cands, "forced", {k: v for k, v in good.items() if k != "min_lead"})
        assert not veil_invariant_ok("A1", "E5", cands, "forced", good)  # 候補に無い手（共通規則）
        assert not veil_invariant_ok("E5", "E5", cands, "forced", good)  # 最善手そのもの
```

- [ ] **Step 2: RED を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q -k "Forced or forced_bounds"`
Expected: import エラー（`cannot import name 'VEIL_FORCED_PROBES'`）で FAIL。出力を report に写す。

- [ ] **Step 3: 実装する**（パッチスクリプト `<scratchpad>/patch_forced_t1.py`・crlf_patch）

定数（`VEIL_BLUNDER_PROB = 0.5 ...` の行の直後）:

```python
VEIL_FORCED_PROBES = 4           # 最善手しか無い手番の外しで検証する候補の数（hp の高い順・spec §14）
```

純関数（`def veil_decided_verified_ok` の直前・この順）:

```python
def veil_forced_candidates(candidates, best_gtp, hp_of, floor, cap, raw_margin=VEIL_RAW_MARGIN,
                           limit=VEIL_FORCED_PROBES):
    """最善手しか無い手番の外しの候補（spec §14.3 手順4・クエリ 0 本）。

    candidates は `_veil_candidates` の {"gtp", "loss", "visits", "wr"}、hp_of は gtp → humanPolicy、floor は通常の層と
    同じ自然さの床、cap は cap_f = min(上限, lead − forced_min_lead)。best_gtp・pass 以外で、生の loss <= cap + raw_margin
    かつ hp >= floor の手を、hp の降順（同点は gtp の昇順）に並べて先頭 limit 手。生の loss の下限は置かない（通常の層の
    条件で落ちた安い手も拾い直す）。返り値は候補 dict のコピーに "hp" を足したもの（元は変えない）。
    """
    pool = []
    for c in candidates:
        if c["gtp"] in (best_gtp, "pass") or c["loss"] > cap + raw_margin + _VEIL_EPS:
            continue
        hp = hp_of(c["gtp"])
        if hp < floor:
            continue
        pool.append({**c, "hp": hp})
    pool.sort(key=lambda c: (-c["hp"], c["gtp"]))
    return pool[:limit]


def veil_forced_ok(row, max_loss, lead, min_lead, min_wr):
    """最善手しか無い手番の外しの資格（spec §14.3 手順6）。row は検証済みの {"cost", "lead_after", "wr_after", ...}
    （cost = max(0, cons)・打つ側視点）、lead は root リード。

    cost <= max_loss かつ lead_after >= min_lead かつ lead − cost >= min_lead（root リード基準・不変条件 kind forced と
    同じ式）かつ wr_after >= min_wr。lead かどれかの値が None なら False。
    """
    cost, lead_after, wr_after = row.get("cost"), row.get("lead_after"), row.get("wr_after")
    if lead is None or cost is None or lead_after is None or wr_after is None:
        return False
    return (
        cost <= max_loss + _VEIL_EPS
        and lead_after >= min_lead - _VEIL_EPS
        and lead - cost >= min_lead - _VEIL_EPS
        and wr_after >= min_wr - _VEIL_EPS
    )


def veil_forced_pick(rows):
    """資格のある手から1手（spec §14.3 手順6）: hp 最大、同点は cost の小さい方、さらに同点は gtp の昇順。空なら None。"""
    if not rows:
        return None
    return min(rows, key=lambda r: (-r["hp"], r["cost"], r["gtp"]))
```

`veil_invariant_ok`: docstring の種類ごとの上限に1行 `forced: cost <= max_loss かつ lead − max(0, cost) >= min_lead かつ wr_after >= min_wr。` を足し、`if kind == "blunder": ...` のブロックの後に:

```python
        if kind == "forced":
            paid = max(0.0, bounds["cost"])
            return (
                bounds["cost"] <= bounds["max_loss"] + _VEIL_EPS
                and bounds["lead"] - paid >= bounds["min_lead"] - _VEIL_EPS
                and bounds["wr_after"] >= bounds["min_wr"] - _VEIL_EPS
            )
```

- [ ] **Step 4: GREEN を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q` と `python -m pytest tests/test_ai_mimic13.py -q`（と `ls tests | grep -i enigma` で見つかる enigma 系のテストファイル）
Expected: すべて PASS。`git diff --stat` で ai.py の変更が挿入だけ（既存行の変更は `veil_invariant_ok` の docstring だけ）。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 最善手しか無い手番の外しの候補・資格・選択・不変条件の純関数を追加" -m "spec §14.3 手順4・6・8。判定フローへの組み込みは次のタスク。" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: 最善手しか無い手番の外しの設定4キー（既定値・登録・GUI の説明・マニュアルの表）

状態: 完了（`d429bd37`）。

**Files:**
- Modify: `katrain/core/ai.py`（`Veil9Strategy` / `Veil13Strategy` / `Veil19Strategy` の `SETTING_DEFAULTS` の末尾＝`blunder_hp_ratio` の後）
- Modify: `katrain/core/constants.py`（候補値のリスト・`AI_OPTION_VALUES`・`AI_OPTION_ORDER`）
- Modify: `katrain/config.json`（`ai:veil9` / `ai:veil13` / `ai:veil19`）
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`・`katrain/i18n/locales/en/LC_MESSAGES/katrain.po`（→ `python tools/compile_mo.py`）
- Modify: `docs/manual/src/06d_ai_parity.html`（韜晦の設定の表に4行 → `python tools/build_manual.py`）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Produces（Task 3 が `self._setting("...")` で読む）: 接尾辞 `forced_mode`（int）・`forced_min_lead`（float）・`forced_min_winrate`（float）・`forced_max_loss`（float）。画面の並びは 20・21・22・23。

この Task は設定を足して登録するだけで、判定フローでは使わない（Task 3 で使う）。

- [ ] **Step 1: 失敗するテストを書く**

`SPEC_DEFAULTS` の 9 / 13 / 19 の末尾（`"blunder_hp_ratio": 0.7,` の後）に:

```python
        # spec §14.2（2026-09-25）
        "forced_mode": 0,
        "forced_min_lead": 1.0,      # 13路 2.0・19路 3.0
        "forced_min_winrate": 0.70,
        "forced_max_loss": 5.0,      # 13路 10.0・19路 15.0
```

（13路は `2.0` / `10.0`、19路は `3.0` / `15.0`。コメントは 9路だけに付けてよい。）

`TestRegistration` の `test_blunder_settings_are_registered` の後に:

```python
    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_forced_settings_are_registered(self, cls, size, prefix, ai_key, const):
        """最善手しか無い手番の外しの4キー（spec §14.2）: 画面の並びは 20〜23、候補値は spec の表どおり、mode は整数、
        jp の概要がこの層（<prefix>_forced_mode）を案内する。"""
        from katrain.core.constants import AI_OPTION_ORDER, AI_OPTION_VALUES

        with open(Path(katrain.__file__).parent / "config.json", encoding="utf-8") as f:
            package_ai_conf = json.load(f)["ai"][ai_key]
        min_lead = {9: [0.5, 1.0, 2.0, 3.0], 13: [1.0, 2.0, 3.0, 5.0], 19: [2.0, 3.0, 5.0, 8.0]}
        max_loss = {9: [3.0, 4.0, 5.0, 6.0, 8.0], 13: [6.0, 8.0, 10.0, 12.0, 15.0], 19: [8.0, 10.0, 15.0, 20.0]}
        winrates = [(0.6, "60%"), (0.7, "70%"), (0.75, "75%"), (0.8, "80%"), (0.85, "85%")]
        expected = {  # 接尾辞: (画面の並び, 候補値, 型)
            "forced_mode": (20, [(0, "OFF"), (1, "LOG"), (2, "ON")], int),
            "forced_min_lead": (21, min_lead[size], float),
            "forced_min_winrate": (22, winrates, float),
            "forced_max_loss": (23, max_loss[size], float),
        }
        for suffix, (order, values, typ) in expected.items():
            key = f"{prefix}_{suffix}"
            assert AI_OPTION_ORDER[key] == order, key
            assert AI_OPTION_VALUES[key] == values, key
            assert type(cls.SETTING_DEFAULTS[suffix]) is typ, key
            assert type(package_ai_conf[key]) is typ, key
        assert cls.SETTING_DEFAULTS["forced_mode"] == 0
        po = (Path(katrain.__file__).parent / "i18n" / "locales" / "jp" / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        m = re.search(rf'msgid "aihelp:{prefix}"\s*\nmsgstr "(.*)"', po)
        assert m and f"{prefix}_forced_mode" in m.group(1), prefix
```

既存の `test_defaults_match_the_spec`・`test_defaults_in_gui_options_and_package_config`・`test_jp_explains_every_slider_once_for_the_family`・`test_en_overview_has_one_bullet_per_slider`・`test_manual_defaults_table_matches_setting_defaults` は、キーが増えると自動で新しい4キーも確かめる（テストは変えない）。

- [ ] **Step 2: RED を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q -k "Registration or defaults or Board"`
Expected: FAIL（SETTING_DEFAULTS に forced キーが無い・AI_OPTION_ORDER に無い、など）。出力を report に写す。

- [ ] **Step 3: 実装する**（パッチスクリプト `<scratchpad>/patch_forced_t2.py`・crlf_patch）

1. ai.py の SETTING_DEFAULTS（3クラス。`"blunder_hp_ratio": 0.7,` の後）。Veil9Strategy は既存と同じ書式で行末コメント:

```python
        "forced_mode": 0,           # 最善手しか無い手番の外し（spec §14）: 0 OFF / 1 記録のみ（影）/ 2 ON
        "forced_min_lead": 1.0,     # 打った後に残すリード（目・root リード − 損と検証済みリードの両方）
        "forced_min_winrate": 0.70,  # 打った後の検証済み勝率の下限
        "forced_max_loss": 5.0,     # 1手の損の上限（検証済み・目。ヨセは yose_max_loss）
```

Veil13Strategy は `0 / 2.0 / 0.70 / 10.0`、Veil19Strategy は `0 / 3.0 / 0.70 / 15.0`（既存の2クラスの書式に合わせる。コメントの有無も周りに合わせる）。3クラスで Veil9 のパッチ対象の文字列（`"blunder_hp_ratio": 0.7,`＋行末）が区別できるか `count` を確かめ、区別できなければ前後の行を含めて一意にする。

2. constants.py（`_VEIL_BLUNDER_HP_RATIO = ...` の直後）:

```python
_VEIL_FORCED_MODE = [(0, "OFF"), (1, "LOG"), (2, "ON")]
_VEIL_FORCED_MIN_LEAD = {
    9: [0.5, 1.0, 2.0, 3.0],
    13: [1.0, 2.0, 3.0, 5.0],
    19: [2.0, 3.0, 5.0, 8.0],
}
_VEIL_FORCED_MIN_WINRATE = [(0.6, "60%"), (0.7, "70%"), (0.75, "75%"), (0.8, "80%"), (0.85, "85%")]
_VEIL_FORCED_MAX_LOSS = {
    9: [3.0, 4.0, 5.0, 6.0, 8.0],
    13: [6.0, 8.0, 10.0, 12.0, 15.0],
    19: [8.0, 10.0, 15.0, 20.0],
}
```

`AI_OPTION_VALUES` の各盤の `"veilN_blunder_hp_ratio": _VEIL_BLUNDER_HP_RATIO,` の後（N = 9・13・19）:

```python
    "veil9_forced_mode": _VEIL_FORCED_MODE,
    "veil9_forced_min_lead": _VEIL_FORCED_MIN_LEAD[9],
    "veil9_forced_min_winrate": _VEIL_FORCED_MIN_WINRATE,
    "veil9_forced_max_loss": _VEIL_FORCED_MAX_LOSS[9],
```

（13・19 も同じ形で `[13]` / `[19]`。）`AI_OPTION_ORDER` の各盤の `"veilN_blunder_hp_ratio": 19,` の後に `"veilN_forced_mode": 20,`・`"veilN_forced_min_lead": 21,`・`"veilN_forced_min_winrate": 22,`・`"veilN_forced_max_loss": 23,`。

3. config.json（3ブロック。`"veilN_blunder_hp_ratio": 0.7` に `,` を足してその後に4行。mode は整数 `0`）:

```json
            "veil9_blunder_hp_ratio": 0.7,
            "veil9_forced_mode": 0,
            "veil9_forced_min_lead": 1.0,
            "veil9_forced_min_winrate": 0.7,
            "veil9_forced_max_loss": 5.0
```

（13: `2.0` / `0.7` / `10.0`、19: `3.0` / `0.7` / `15.0`。）JSON として読めることを `python -c "import json;json.load(open('katrain/config.json',encoding='utf-8'))"` で確かめる。

4. jp の .po（`msgid "aiopt:veil*_blunder_hp_ratio"` のエントリの後に4つ。1行目が見出し、2行目が説明。`{p}` はキー接頭辞に置き換わる既存の仕組み）:

```
msgid "aiopt:veil*_forced_mode"
msgstr ""
"最善手しか無い手番の外し\n"
"通常の外しの条件（支払いの余剰・自然さ）では最善手しか打てない手番でも、9段が打ちそうな手（自然さの床以上）のうち、打った後もリードが {p}_forced_min_lead 目以上・勝率が {p}_forced_min_winrate 以上残り、損が {p}_forced_max_loss 目以下（ヨセは {p}_yose_max_loss 目以下）の手があれば打ちます。一致率が目標を超えている間だけ動きます。LOG（記録のみ）は打つ手を探してログに書くだけで、最善手を打ちます。ON で実際に打ちます。接戦でもリードが残る範囲で外すので、ON にするとまれに負けます（20 局に 1 局ほどを許す設定です）。既定は OFF。"

msgid "aiopt:veil*_forced_min_lead"
msgstr ""
"外した後に残すリード（目）\n"
"{p}_forced_mode で外した後にも残すリードです（打つ前のリードから損を引いた値と、打った後の局面を読んだ値の両方で見ます）。上げると接戦では外さなくなって負けにくくなりますが、一致率は下がりにくくなります。"

msgid "aiopt:veil*_forced_min_winrate"
msgstr ""
"外した後の勝率の下限\n"
"{p}_forced_mode で外した後の局面の勝率（読みで確かめた値）の下限です。上げると負けにくくなりますが、一致率は下がりにくくなります。"

msgid "aiopt:veil*_forced_max_loss"
msgstr ""
"外す手の損の上限（目）\n"
"{p}_forced_mode で 1 手に許す損（打った後の局面を読んだ値）の上限です。ヨセに入った後は {p}_yose_max_loss を使います。上げると大差のときに大きく緩めて一致率が下がりますが、6 目を超えるような大きな損の手も出ます。"
```

jp の `aihelp:veil9` / `aihelp:veil13` / `aihelp:veil19` の本文で、1文「9段でも迷う局面でまれに人間らしい失着を打つ層は veilN_blunder_mode で足せます（既定 OFF・LOG で記録のみ）。」の直後に、次の1文を足す（N は各盤）:

「最善手しか打てない手番でも、打った後にリードと勝率が残る人間らしい手があれば打つ層は veilN_forced_mode で足せます（既定 OFF・LOG で記録のみ。ON にすると 20 局に 1 局ほどの負けを許します）。」

en の .po の `aihelp:veil9` / `aihelp:veil13` / `aihelp:veil19` は「1スライダー1箇条」（`test_en_overview_has_one_bullet_per_slider`）なので、最後の箇条「* Blunder naturalness: ...」の後に4箇条を足す（msgstr の中の改行は `\n`）:

```
* Best-only deviations: on turns where the normal rules leave only the best move, it still plays a human-looking move (above the naturalness floor) if the lead after it stays at least the forced minimum lead, the winrate at least the forced winrate floor, and the loss at most the forced max loss (the endgame max loss in the endgame). Only while the match rate is above the target. LOG only writes the move it would play to the log; ON plays it. Because it also deviates in close games as long as the lead holds, ON accepts an occasional loss (about 1 game in 20). Off by default.
* Forced minimum lead: the lead (points) that must remain after a best-only deviation, both as the lead before the move minus its loss and as the lead read after the move. Higher: fewer deviations in close games and fewer losses, but a higher match rate.
* Forced winrate floor: the winrate after a best-only deviation (verified by reading) must be at least this. Higher: fewer losses, but a higher match rate.
* Forced max loss: the largest verified loss (points) allowed for one best-only deviation; the endgame max loss applies in the endgame. Higher: looser play with a big lead and a lower match rate, but also moves that lose more than 6 points.
```

en に `aiopt:veil*_...` の英語エントリがあるか確かめ、ある形に合わせる（無ければ足さない）。`python tools/compile_mo.py`。

5. マニュアル（`docs/manual/src/06d_ai_parity.html` の韜晦の設定の表。`veil*_blunder_hp_ratio` の行の後に4行。既定欄は 13路が本文、9路・19路は `<span class="jp">`。書式は `_manual_cell`＝画面のラベル（OFF・70%）か数値 `f"{v:g}"`）:

```html
      <tr><td>veil*_forced_mode</td><td>OFF<span class="jp">9路 OFF・19路 OFF</span></td><td>OFF/LOG/ON</td><td>最善手しか無い手番の外し（通常の外しでは最善手しか打てない手番でも、打った後にリードと勝率が残る 9段らしい手があれば打つ）。LOG は打つ手をログに書くだけ（最善手を打つ）</td><td><span class="up">ON</span>一致率が下がる。接戦でもリードが残る範囲で外すので、まれに負ける（20 局に 1 局ほどを許す設定）</td></tr>
      <tr><td>veil*_forced_min_lead</td><td>2<span class="jp">9路 1・19路 3</span></td><td>9路 0.5〜3・13路 1〜5・19路 2〜8</td><td>最善手しか無い手番で外した後に残すリード（目。打つ前のリード − 損と、打った後の読みの両方）</td><td><span class="up">上げる</span>接戦で外さなくなる（負けにくいが一致率は下がりにくい）</td></tr>
      <tr><td>veil*_forced_min_winrate</td><td>70%<span class="jp">9路 70%・19路 70%</span></td><td>60%〜85%</td><td>最善手しか無い手番で外した後の勝率の下限（読みで確かめた値）</td><td><span class="up">上げる</span>負けにくいが一致率は下がりにくい</td></tr>
      <tr><td>veil*_forced_max_loss</td><td>10<span class="jp">9路 5・19路 15</span></td><td>9路 3〜8・13路 6〜15・19路 8〜20</td><td>最善手しか無い手番で1手に許す損の上限（目・読みで確かめた値。ヨセは yose_max_loss）</td><td><span class="up">上げる</span>大差で大きく緩めて一致率が下がる（6 目を超える損の手も出る）</td></tr>
```

`python tools/build_manual.py`。

6. `katrain/gui/ai_help.py` の `_VEIL_FAMILY` は接尾辞を問わないので変更は要らないはず。確かめて、要るときだけ直す。

- [ ] **Step 4: GREEN を確かめる**

Run: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py -q`、と i18n・設定の整合を見る既存のテスト（`git grep -ln "compile_mo\|katrain.po\|config.json" tests` で見つかるもの）。
Expected: すべて PASS。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py katrain/core/constants.py katrain/config.json katrain/i18n docs/manual tests/test_ai_veil.py
git commit -m "feat(veil): 最善手しか無い手番の外しの設定4キー（既定 OFF）を登録する" -m "spec §14.2。GUI の説明（jp / en）とマニュアルの設定の表も足す。" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: 最善手しか無い手番の外しを判定フローに組み込む（TDD）

状態: 完了（`5aae2e2a`）。

**Files:**
- Modify: `katrain/core/ai.py`（`Veil9Strategy` に `_veil_forced`・`_veil_move` の4つの出口）
- Test: `tests/test_ai_veil.py`

**Interfaces:**
- Consumes: Task 1 の `VEIL_FORCED_PROBES`・`veil_forced_candidates`・`veil_forced_ok`・`veil_forced_pick`・`veil_invariant_ok(..., "forced", bounds)`。Task 2 の設定4キー。既存の `_veil_parent_hp(info)`・`_veil_candidates(cands, player)`・`_veil_floor(human_policy, dominant)`・`_probe_children(gtps, player, parent_hp=False)`（返り値 `({gtp: {"clean", "hp"}}, None)`）・`enigma9_verified_metrics(clean, player)`・`veil_cons_loss(vloss, raw, visits, trusted)`・`_veil_violation`・`_veil_state()`。
- Produces（Task 4・5 が頼る記録）: tier / kind `"forced"`。`Decision:` のフィールド `forced`（gate / no_hp / no_cand / no_probe / rejected / shadow / invariant / played）・`forced_from`（元の why）・`forced_gtp`・`forced_cost`・`forced_vloss`・`forced_hp`・`forced_wr`・`forced_lead_after`。打った手番は `raw` `vloss` `cons` `cost` `hp`。`_veil_state()["forced"]`＝今局 ON で打った数（打ったときだけ作る＝mode 0 の状態は今と同じ）。

- [ ] **Step 1: 失敗するテストを書く**（`TestBlunder` の後に置く。`_Harness` を継承・9路・SPEC_DEFAULTS＝reserve 3・free_loss 0.2・spend_rate 0.5・max_loss 3・yose_max_loss 1・natural_ratio 0.2・forced 1.0 / 0.70 / 5.0・trusted_visits 100）

場面の組み立て（すべて黒番・lead 4.0・root 勝率 0.80・一致率の履歴 9/10＝p_match 0.909・u = 1）:
- S9: S = 4 − 3 = 1、A_t = min(1, 0.2 + (0.5 − 0.2)) = 0.5、raw_cap = 0.5 + 0.3 = 0.8。
- 出口 `no_pool` の場面: 候補を E5 0.0（600）・C7 2.0（60）・G3 3.8（40）にすると raw_cap 0.8 以内の手が無い。
- この層: cap_f = min(5.0, 4.0 − 1.0) = 3.0 → 生の loss <= 3.3 の C7 だけ。hp の床 = max(0.05, 0.2 × 0.40) = 0.08 → C7 0.20 が残る。
- 検証: E5 → lead 4.0・勝率 0.80、C7 → lead 2.6・勝率 0.74 → vloss 1.4、C7 の visits 60 < 100 なので cons = 1.4 → cost 1.4 <= 5・lead_after 2.6 >= 1・4.0 − 1.4 >= 1・0.74 >= 0.70 → 資格あり。

```python
class TestForced(_Harness):
    """最善手しか無い手番の外し（spec §14.3）。場面は docstring の上の計算（計画 Task 3 Step 1）どおり。"""

    NO_POOL_CANDS = [
        {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.80},
        {"move": "C7", "pointsLost": 2.0, "relativePointsLost": 2.0, "visits": 60, "winrate": 0.74},
        {"move": "G3", "pointsLost": 3.8, "relativePointsLost": 3.8, "visits": 40, "winrate": 0.70},
    ]
    HP = {"E5": 0.40, "C7": 0.20, "G3": 0.10}
    PROBES = {"E5": (4.0, 0.80), "C7": (2.6, 0.74)}

    def _forced(self, mode, *, probes=None, player="B", lead=4.0, wr=0.80, hist=None, settings=None, **kw):
        table = self.PROBES if probes is None else probes
        kw.setdefault("cands", self.NO_POOL_CANDS)
        if player == "W":
            kw["cands"] = [{**c, "winrate": 1.0 - c["winrate"]} for c in kw["cands"]]
        kw["probes"] = {g: None if v is None else _child(*v, player=player) for g, v in table.items()}
        settings = {"veil9_forced_mode": mode, **(settings or {})}
        hist = _hist(player, 9, 10) if hist is None else hist
        return self._strategy(lead=lead, wr=wr, player=player, hist=hist, settings=settings, **kw)

    @staticmethod
    def _decision(logs):
        decisions = [m for m in logs if "Decision: {" in m]
        assert len(decisions) == 1
        return json.loads(decisions[0].split("Decision: ", 1)[1])

    def test_mode_0_changes_nothing(self):
        s, logs = self._forced(0)
        move, _ = s.generate_move()
        info = s.last_decision_info
        assert (move.gtp(), info["tier"], info["kind"], info["why"]) == ("E5", "i", "best", "no_pool")
        assert not any(k.startswith("forced") for k in info)
        assert not any(k.startswith("forced") for k in self._decision(logs))
        assert s.queries == [] and s.probe_calls == [] and info["queries"] == 0
        assert "forced" not in s.game._veil_state["veil9"]
        assert not any("Forced" in m for m in logs)

    def test_mode_1_records_the_move_without_playing_it(self):
        s, logs = self._forced(1)
        move, _ = s.generate_move()
        info = s.last_decision_info
        assert (move.gtp(), info["kind"], info["why"]) == ("E5", "best", "no_pool")
        assert (info["forced"], info["forced_from"], info["forced_gtp"]) == ("shadow", "no_pool", "C7")
        assert info["forced_cost"] == pytest.approx(1.4) and info["forced_vloss"] == pytest.approx(1.4)
        assert info["forced_hp"] == pytest.approx(0.20) and info["forced_wr"] == pytest.approx(0.74)
        assert info["forced_lead_after"] == pytest.approx(2.6)
        assert self._decision(logs)["forced"] == "shadow"
        assert s.queries == ["parent hp"] and s.probe_calls == [["E5", "C7"]] and info["queries"] == 5
        assert "forced" not in s.game._veil_state["veil9"]
        assert any(m.startswith("[Veil9Strategy] Forced shadow: C7") for m in logs)

    def test_mode_2_plays_the_move(self):
        s, logs = self._forced(2)
        move, _ = s.generate_move()
        info = s.last_decision_info
        assert (move.gtp(), info["tier"], info["kind"]) == ("C7", "forced", "forced")
        assert (info["forced"], info["forced_from"]) == ("played", "no_pool")
        assert info["cost"] == pytest.approx(1.4) and info["hp"] == pytest.approx(0.20)
        record = self._decision(logs)
        assert (record["kind"], record["forced"], record["forced_gtp"]) == ("forced", "played", "C7")
        state = s.game._veil_state["veil9"]
        assert state["forced"] == 1 and state["ledger"] == [(12, "E5", "C7", "forced")]
        assert any("Forced C7: raw=2.00 vloss=1.40 cost=1.40 hp=0.200 wr=74.0% lead_after=2.60 ok=True" in m for m in logs)
        s.generate_move()  # 1局の回数の上限は無い
        assert s.last_decision_info["forced"] == "played" and s.game._veil_state["veil9"]["forced"] == 2

    @pytest.mark.parametrize(
        "kw",
        [
            dict(hist=_hist("B", 3, 9)),  # p_match 0.40 = 目標 → u = 0
            dict(wr=0.69),  # root 勝率 < forced_min_winrate
            dict(wr=None),  # root 勝率が無い
            dict(lead=1.0),  # cap_f = min(5, 1 − 1) = 0
        ],
    )
    def test_gate_stops_the_layer_without_queries(self, kw):
        s, _ = self._forced(2, **kw)
        assert s.generate_move()[0].gtp() == "E5"
        info = s.last_decision_info
        assert (info["forced"], info["forced_from"], info["why"]) == ("gate", "no_pool", "no_pool")
        assert s.queries == [] and s.probe_calls == []

    def test_gate_winrate_bound_is_inclusive(self):
        s, _ = self._forced(2, wr=0.70)
        assert s.generate_move()[0].gtp() == "C7"

    def test_humansl_failure(self):
        s, _ = self._forced(2, hp_ok=False)
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["forced"] == "no_hp" and s.queries == ["parent hp"] and s.probe_calls == []

    def test_no_candidate_below_the_natural_floor(self):
        s, _ = self._forced(2, hp={"E5": 0.40, "C7": 0.07, "G3": 0.10})
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["forced"] == "no_cand" and s.probe_calls == []

    @pytest.mark.parametrize(
        "c7",
        [
            (2.6, 0.69),  # 着手後勝率 < 0.70
            (0.9, 0.90),  # lead_after 0.9 < 1・4.0 − 3.1 < 1
        ],
    )
    def test_rejected_after_the_probe(self, c7):
        s, _ = self._forced(2, probes={"E5": (4.0, 0.80), "C7": c7})
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["forced"] == "rejected"

    def test_missing_best_probe(self):
        s, _ = self._forced(2, probes={"E5": None, "C7": (2.6, 0.74)})
        assert s.generate_move()[0].gtp() == "E5"
        assert s.last_decision_info["forced"] == "no_probe"

    def test_invariant_violation_plays_the_best_move(self, monkeypatch):
        real = ai_module.veil_invariant_ok
        monkeypatch.setattr(
            ai_module, "veil_invariant_ok", lambda c, b, g, kind, bounds: False if kind == "forced" else real(c, b, g, kind, bounds)
        )
        s, logs = self._forced(2)
        assert s.generate_move()[0].gtp() == "E5"
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["why"], info["forced"]) == ("failsafe", "best", "invariant", "invariant")
        assert any("Invariant violated: chosen=C7 kind=forced" in m for m in logs)
        assert "forced" not in s.game._veil_state["veil9"]

    def test_yose_uses_the_yose_max_loss(self):
        state = {"veil9": {"endgame": True, "close_drift": 0.0, "ledger": [], "blunders": 0}}
        s, _ = self._forced(2, _veil_state=state)  # cap_f = min(1.0, 3.0) = 1.0 → C7（生 2.0）は候補外
        assert s.generate_move()[0].gtp() == "E5" and s.last_decision_info["forced"] == "no_cand"
        cheap = [{**c, "pointsLost": 0.9, "relativePointsLost": 0.9} if c["move"] == "C7" else c for c in self.NO_POOL_CANDS]
        state = {"veil9": {"endgame": True, "close_drift": 0.0, "ledger": [], "blunders": 0}}
        s, _ = self._forced(2, cands=cheap, probes={"E5": (4.0, 0.80), "C7": (3.1, 0.76)}, _veil_state=state)
        assert s.generate_move()[0].gtp() == "C7"  # cost 0.9 <= yose_max_loss 1.0
        assert s.last_decision_info["forced_cost"] == pytest.approx(0.9)

    def test_no_natural_exit_shares_the_parent_humansl(self):
        """通常の候補 D4（生 0.1）・F6（0.8）が床（0.08）より下＝no_natural。この層は C7（生 2.0・hp 0.20）を拾う。"""
        hp = {"E5": 0.40, "D4": 0.03, "F6": 0.03, "C7": 0.20, "G3": 0.04}
        s, _ = self._forced(2, cands=_Harness.CANDS, hp=hp)
        assert s.generate_move()[0].gtp() == "C7"
        info = s.last_decision_info
        assert (info["forced_from"], info["kind"]) == ("no_natural", "forced")
        assert s.queries == ["parent hp"] and s.probe_calls == [["E5", "C7"]]

    def test_none_qualified_exit_reuses_the_s15_probes(self):
        """通常の候補 D4（hp 0.30）・F6（0.15）はプローブで cost 0.7・1.0 > A_t 0.5 → none_qualified。
        この層は同じプローブを使って D4（hp 最大）を打つ（読み直さない）。"""
        probes = {"E5": (4.0, 0.80), "D4": (3.3, 0.75), "F6": (3.0, 0.74)}
        s, _ = self._forced(2, cands=_Harness.CANDS, hp=_Harness.HP, probes=probes)
        assert s.generate_move()[0].gtp() == "D4"
        info = s.last_decision_info
        assert (info["forced_from"], info["forced_gtp"]) == ("none_qualified", "D4")
        assert info["forced_cost"] == pytest.approx(0.7)
        assert s.probe_calls == [["E5", "D4", "F6"]] and info["queries"] == 7

    def test_white_plays_the_same_move(self):
        s, _ = self._forced(2, player="W")
        assert s.generate_move()[0].gtp() == "C7"
        assert s.last_decision_info["forced"] == "played"
```

実装の前に、上の場面の数値（S9 の A_t・raw_cap・`none_qualified` に落ちる理由・yose の手番で終局帯〈S7/S8〉に入らないこと）を `_veil_move` を読んで確かめる。合わない場面があれば、テストの意図（どの出口から入り、どの結末になるか）を保ったまま数値だけを直し、report に書く。

- [ ] **Step 2: RED を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q -k TestForced`
Expected: mode 0 のテストは PASS（既存の挙動）、それ以外は FAIL（`forced` キーが無い・C7 を打たない）。出力を report に写す。

- [ ] **Step 3: 実装する**（パッチスクリプト `<scratchpad>/patch_forced_t3.py`・crlf_patch）

1. 新メソッド（`Veil9Strategy`・`_veil_blunder` の後、`_generate_move` の前）:

```python
    def _veil_forced(self, cands, player, best_gtp, lead, root_wr, in_yose, u, info, why,
                     stage_hp=None, hp_fetched=False, probes=None):
        """最善手しか無い手番の外し（spec §14.3）。通常の流れが最善手で終わる出口（why = no_pool / no_natural /
        no_shortlist / none_qualified）の直前に呼ぶ。返り値は打つときだけ (result, tier, kind, fields)、それ以外は None
        （呼び出し側が元の why で最善手を打つ）。

        forced_mode 0 なら何もしない（クエリ 0 本・info に何も足さない）。関門（クエリ 0 本・`forced = "gate"`）は u <= 0・
        root 勝率が無いか forced_min_winrate 未満・cap_f = min(上限, lead − forced_min_lead) <= 0 のどれか（上限はヨセなら
        yose_max_loss、それ以外は forced_max_loss）。stage_hp / hp_fetched は S9b・S11 の親局面の humanSL（撃っていれば
        使う＝同じ手番で2回撃たない）、probes は S15 の子局面プローブ（同じ手は読み直さない）。"""
        mode = int(self._setting("forced_mode"))
        if mode <= 0:
            return None
        info["forced_from"] = why
        min_lead = float(self._setting("forced_min_lead"))
        min_wr = float(self._setting("forced_min_winrate"))
        max_loss = float(self._setting("yose_max_loss" if in_yose else "forced_max_loss"))
        cap_f = min(max_loss, lead - min_lead)
        if u <= 0 or root_wr is None or root_wr < min_wr - _VEIL_EPS or cap_f <= 0:
            info["forced"] = "gate"
            return None
        if not hp_fetched:
            stage_hp = self._veil_parent_hp(info)
        if not stage_hp or "humanPolicy" not in stage_hp:
            info["forced"] = "no_hp"
            return None
        human_policy = stage_hp["humanPolicy"]
        hp_of = enigma9_hp_lookup(human_policy, self.game.board_size)
        rows0 = veil_forced_candidates(
            self._veil_candidates(cands, player), best_gtp, hp_of, self._veil_floor(human_policy, False), cap_f
        )
        if not rows0:
            info["forced"] = "no_cand"
            return None
        probes = dict(probes or {})
        need = [g for g in [best_gtp] + [c["gtp"] for c in rows0] if not (probes.get(g) or {}).get("clean")]
        if need:
            fresh, _unused = self._probe_children(need, player, parent_hp=False)
            info["queries"] += 2 * len(need)
            probes.update(fresh)
        best_lead_after, _best_wr_after = enigma9_verified_metrics((probes.get(best_gtp) or {}).get("clean"), player)
        if best_lead_after is None:
            self._log("Forced: best-move probe unavailable -> best move")
            info["forced"] = "no_probe"
            return None
        trusted = self.VEIL_BOARD["trusted_visits"]
        ok_rows = []
        for c in rows0:
            lead_after, wr_after = enigma9_verified_metrics((probes.get(c["gtp"]) or {}).get("clean"), player)
            if lead_after is None:
                self._log(f"Forced {c['gtp']}: probe incomplete -> dropped")
                continue
            vloss = best_lead_after - lead_after
            cons = veil_cons_loss(vloss, c["loss"], c.get("visits", 0), trusted)
            row = {
                **c, "raw": c["loss"], "vloss": vloss, "cons": cons, "cost": max(0.0, cons),
                "lead_after": lead_after, "wr_after": wr_after,
            }
            ok = veil_forced_ok(row, max_loss, lead, min_lead, min_wr)
            wr_txt = "n/a" if wr_after is None else f"{wr_after:.1%}"
            self._log(
                f"Forced {c['gtp']}: raw={c['loss']:.2f} vloss={vloss:.2f} cost={row['cost']:.2f} hp={c['hp']:.3f} "
                f"wr={wr_txt} lead_after={lead_after:.2f} ok={ok}"
            )
            if ok:
                ok_rows.append(row)
        pick = veil_forced_pick(ok_rows)
        if pick is None:
            info["forced"] = "rejected"
            return None
        gtp = pick["gtp"]
        fields = {
            "forced_gtp": gtp, "forced_cost": pick["cost"], "forced_vloss": pick["vloss"], "forced_hp": pick["hp"],
            "forced_wr": pick["wr_after"], "forced_lead_after": pick["lead_after"],
        }
        info.update(fields)
        summary = f"{gtp} (cost {pick['cost']:.2f}, vloss {pick['vloss']:.2f}, hp {pick['hp']:.3f}) instead of {best_gtp}"
        # 影（mode 1）: 記録だけして最善手（元の why のまま）
        if mode == 1:
            info["forced"] = "shadow"
            self._log(f"Forced shadow: {summary} -> not played (mode 1)")
            return None
        bounds = {
            "cost": pick["cost"], "max_loss": max_loss, "lead": lead, "min_lead": min_lead,
            "wr_after": pick["wr_after"], "min_wr": min_wr,
        }
        if not veil_invariant_ok(gtp, best_gtp, {d["move"] for d in cands}, "forced", bounds):
            info["forced"] = "invariant"
            return self._veil_violation(gtp, "forced", bounds), "failsafe", "best", {"why": "invariant"}
        state = self._veil_state()
        state["forced"] = state.get("forced", 0) + 1  # 打ったときだけ作る（mode 0 の状態は今と同じ）
        info["forced"] = "played"
        self._log(f"Forced: played {summary}")
        return (
            (
                Move.from_gtp(gtp, player=player),
                f"{self.LABEL}: deviated to {gtp} on a best-only turn (verified loss {pick['vloss']:.2f}, "
                f"hp {pick['hp']:.1%}, lead after {pick['lead_after']:.1f}, winrate after {pick['wr_after']:.0%}) "
                f"instead of {best_gtp}.",
            ),
            "forced", "forced",
            {"raw": pick["raw"], "vloss": pick["vloss"], "cons": pick["cons"], "cost": pick["cost"], "hp": pick["hp"]},
        )
```

2. `_veil_move` の4つの出口（それぞれ `return finish(self._best_move(...), ..., why="...")` の直前に足す。元の `return finish(...)` は変えない）:

S10（`if not nat_pool and not trap_pool:` の中・`self._log(f"Tier i: no candidate ...")` の後）:

```python
            forced = self._veil_forced(
                cands, player, best_gtp, lead, root_wr, in_yose, u, info, "no_pool",
                stage_hp=stage_hp, hp_fetched=hp_fetched,
            )
            if forced is not None:
                result, tier_f, kind_f, fields = forced
                return finish(result, tier_f, kind_f, **fields)
```

S12（`if not naturals and not trap_cands:` の中）:

```python
            forced = self._veil_forced(
                cands, player, best_gtp, lead, root_wr, in_yose, u, info, "no_natural",
                stage_hp=stage_hp, hp_fetched=True,
            )
            if forced is not None:
                result, tier_f, kind_f, fields = forced
                return finish(result, tier_f, kind_f, **fields)
```

S14（`if not shortlist:` の中）は同じ形で `"no_shortlist"`・`stage_hp=stage_hp, hp_fetched=True`。
S17（`if chosen is None:` の中・`self._log("No qualifying deviation -> best move")` の後）は `"none_qualified"`・`stage_hp=stage_hp, hp_fetched=True, probes=probes`。

3. `Veil9Strategy` の docstring の失着の層の段落の後に1文「最善手しか無い手番の外し（forced_mode・spec §14・既定 OFF）は、通常の流れが最善手で終わる4つの出口（no_pool / no_natural / no_shortlist / none_qualified）で、打った後にリード forced_min_lead・勝率 forced_min_winrate が残り損が forced_max_loss（ヨセは yose_max_loss）以下の 9段らしい手を探し、LOG（1）は記録だけ、ON（2）は打つ（u > 0 のときだけ）。」を足し、sticky な状態の列挙に「forced（ON で打った数・打ったときだけ作る）」を足す。

- [ ] **Step 4: GREEN を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q`（全件）と `python -m pytest tests/test_ai_mimic13.py tests/test_ai_help_text.py -q` と enigma 系のテストファイル。
Expected: すべて PASS。既存のテスト（すべて forced_mode 0）が1件も変わらずに通ること＝mode 0 の挙動が今と同じ。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 最善手しか無い手番の外しを判定フローに組み込む（既定 OFF・記録のみ／ON）" -m "spec §14.3。通常の流れが最善手で終わる4つの出口の直前で、リードと勝率が残る 9段らしい手を探す。" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: 文書（開発者向けルール・マニュアルの本文・測定の記録・INDEX・計画の状態）

状態: 完了（`0cd6efd2`）。

**Files:**
- Modify: `.claude/rules/ai-parameters.md`・`.claude/rules/ai-strategies.md`
- Modify: `docs/manual/src/06d_ai_parity.html`（本文の箇条）→ `python tools/build_manual.py`
- Modify: `docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md`（見積もりの節とユーザーの決定）
- Modify: `docs/superpowers/specs/INDEX.md`（韜晦の spec の行の状態）・`docs/superpowers/plans/2026-09-25-veil-forced.md`（各 Task の状態）
- Test: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py -q`（マニュアルの表の整合テストが通ること）

- [ ] **Step 1: `.claude/rules/ai-parameters.md`**（パッチスクリプト `<scratchpad>/patch_forced_t4.py`）
  - 韜晦のパラメータ表の `veil*_blunder_hp_ratio` の行の後に4行（書式は既存の行どおり。既定は 9路 / **13路** / 19路）:
    - `veil*_forced_mode` | 最善手しか無い手番の外し（spec §14）: 通常の流れが最善手で終わる4つの出口（no_pool / no_natural / no_shortlist / none_qualified）で、9段らしさの床以上の手を hp の高い順に最大 4 手（`VEIL_FORCED_PROBES`）500v で検証し、資格（cost = max(0, cons) <= 上限〈ヨセは yose_max_loss〉・lead_after >= forced_min_lead・lead − cost >= forced_min_lead・wr_after >= forced_min_winrate）のある手の hp 最大を、LOG は記録だけ・ON は打つ。関門: u > 0・root 勝率 >= forced_min_winrate・min(上限, lead − forced_min_lead) > 0。**ON のときだけ要件1を「20局に1局ほどの負けは許す」に緩める（ユーザーの決定 2026-09-25）** | OFF/LOG/ON | OFF / **OFF** / OFF
    - `veil*_forced_min_lead` | 外した後に残すリード（目・root − cost と検証済み lead_after の両方） | 9路 0.5〜3・13路 1〜5・19路 2〜8 | 1 / **2** / 3
    - `veil*_forced_min_winrate` | 外した後の検証済み勝率の下限 | 60%〜85% | 70% / **70%** / 70%
    - `veil*_forced_max_loss` | 1手の損の上限（検証済み・目。ヨセは yose_max_loss） | 9路 3〜8・13路 6〜15・19路 8〜20 | 5 / **10** / 15
  - sticky 状態の説明（`endgame・close_drift・ledger・blunders`）に「forced（ON で打った数・打ったときだけ作る）」を足す。
  - `Decision: {json}` の説明の tier と kind の列挙に `forced` を足し、why の列挙の後の文に「最善手しか無い手番の外しが LOG／ON の手番はフィールド `forced`＝gate / no_hp / no_cand / no_probe / rejected / shadow / invariant / played と `forced_from`（元の why）、候補を選べたら `forced_gtp` `forced_cost` `forced_vloss` `forced_hp` `forced_wr` `forced_lead_after`」を足す。
  - 失着の層の計測の段落の後に1段落: 「**最善手しか無い手番の外し（spec §14・既定 OFF）**: 2026-09-25 のユーザーの決定（20局に1局ほどの負けを許して一致率を平均 30〜45% に）で足した層。見積もり（反実仮想）はハーネス 36〜42%・実戦 43〜45%（13路・既定の forced 値）。9段らしさの床は変えないので、明らかな一手（9段 hp >= 0.95）は開かない（安全条件を全部外しても下限はハーネス 24%・実戦 28%）。測定の結果は campaign md。」
- [ ] **Step 2: `.claude/rules/ai-strategies.md`** の韜晦（Veil）の段落に1文: 「最善手しか無い手番の外し（`veil*_forced_mode`・spec §14・既定 OFF）は、通常の層が最善手しか打てない手番でも、打った後にリードと勝率が残る 9段らしい手を打つ（ON のときだけ要件1を『20局に1局ほどの負けは許す』に緩める）。」
- [ ] **Step 3: マニュアル**（`06d_ai_parity.html`）: 失着の層の `<li>`（`<b>失着の層</b>` で始まる箇条）の後に `<li>` を1つ:
  「<b>最善手しか無い手番の外し</b>（<code>veil*_forced_mode</code>・既定 OFF）は、ふつうの外しでは最善手しか打てない手番でも、9段が打ちそうな手のうち、打った後もリードが <code>veil*_forced_min_lead</code> 目以上・勝率が <code>veil*_forced_min_winrate</code> 以上残り、損が <code>veil*_forced_max_loss</code> 目以下（ヨセは <code>veil*_yose_max_loss</code>）の手があれば打ちます。一致率が目標を超えている間だけ動きます。接戦でもリードが残る範囲で外すので、ON にするとまれに負けます（20 局に 1 局ほどを許す設定です）。9段がほぼ必ず打つ明らかな一手は外しません。LOG は打つ手をログに書くだけで最善手を打ちます。」→ `python tools/build_manual.py`。
- [ ] **Step 4: campaign md**（`veil13-campaign.md`）: `## ユーザーの決定（2026-09-25）` の節の前に `## 最善手しか無い手番の外し（spec §14）の見積もり（2026-09-25）` の節を足す（記録は `experiments/selfplay/relax-spike-20260925/`〈gitignore〉。数値は下のとおり＝そこの `workflow_summary.md` の reconcile の最終表から写した値。書き換えない）:
  - 方法: 実戦3局（119手）・ハーネスの通常の相手 60局（p1b loose・blunder13-shadow sh_loose・blunder13-on loose）・接戦ストレス 20局（p3b loose）の強制手番 1790 手で、2500v の親解析・humanSL（9段・5段・3段・1段）・候補最大 8 手の 500v プローブを集め、条件ごとに1手ずつの反実仮想（先の外しの損は lead から引く一次近似）。評価は独立の3実装で全値一致。
  - 表1（同じ局面を humanSL の確率どおりに打つ人の一致率）: 通常 9段 48.3%・5段 46.3%・3段 44.4%・1段 41.7%／接戦ストレス 48.4・46.0・43.9・41.1%／実戦 51.9・49.6・47.3・44.7%。
  - 表2（主な条件・1局ごとの平均の一致率。範囲は素朴〜悲観）: 今（loose）通常 45.2%・実戦 53.6%・ストレス 65.4%／① 安全は今のまま・強制手番だけ上限 10目: 40.2〜42.2%・49.0%・63.0〜66.2%／② リード +2・勝率 70%・上限 6目: 38.4〜43.7%・46.4〜48.4%・59.5〜64.2%／③ 同・上限 10目: 36.3〜42.2%・43.5〜45.4%・59.5〜65.4%／④ 同・上限なし: 34.6〜41.4%・41.8〜48.4%・59.5〜65.4%。最終リードが負になる局（一次近似・ストレス 20局）: ①② 0・③④ 1。
  - 要点: 9段らしさの床を守る限り、安全条件をすべて外しても下限は通常 23.9%・実戦 27.8%（最善手の 9段 hp >= 0.95 の手番は 390 手中 0 しか開かない）。効くのは大差での1手の損の上限。1局の勝率の予算は終盤の勝率の飽和で効かず（B05 はストレスで 2/20 局の最終リードが負）、弱い段位の humanSL を基準にする案は +0.3〜1.1pt だけ。新しく外す手の 9段 hp の中央値は 0.23〜0.25（既存の外しは 0.26）。
  - `## ユーザーの決定（2026-09-25）` の節の末尾に1項: 「最善手しか無い手番の外し（spec §14）: 20局に1局ほどの負けを許して一致率を平均 30〜45% に下げる。条件は ③（着手後リード +2目・着手後勝率 70%・1手の損の上限 10目・ヨセは yose_max_loss）。コードの既定は OFF、校正に合格したらローカル設定で ON。」
- [ ] **Step 5: INDEX と計画**: `docs/superpowers/specs/INDEX.md` の韜晦の spec の行の状態に「§14 最善手しか無い手番の外し（2026-09-25・既定 OFF）」を足す（ファイルの場所は `git ls-files | grep INDEX.md` で確かめる）。この計画の Task 1〜4 の見出しの下に `状態: 完了（<コミット>）` を足す。
- [ ] **Step 6: 確かめてコミット**

Run: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py -q`
Expected: PASS。

```bash
git add .claude/rules docs
git commit -m "docs(veil): 最善手しか無い手番の外しを開発者向けルール・マニュアル・測定の記録に反映" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5（コントローラ）: 校正・採否・仕上げ

状態: 完了（校正は合格＝`e1e0848e`・ユーザーの決定でローカル設定の 13路を ON にし、master にマージ）。

KataGo を使う。**KaTrain が動いていないことを確かめてから**（`Get-CimInstance Win32_Process` で `-m katrain` の python と、自分が起動していない katago.exe が無いこと）。走っている間はユーザーに KaTrain を起動しないよう伝える。

- [ ] **Step 1: 全体のテスト**: `python -m pytest -q -p no:cacheprovider tests --ignore=tests/test_ai.py`（期待: 2021 件＋この計画で足した件数がすべて PASS）。
- [ ] **Step 2: アーム**: `experiments/selfplay/sdd-records/forced/arms.py`（`sdd-records/blunder/arms.py` と同じ形）で 24 キーを明示した2アームを作る:
  - `cur` = loose の 20 キー（`target_rate 0.3・reserve 5.0・min_winrate 0.85・free_loss 0.4・free_wr_drop 0.03・close_drift_cap 0.0・spend_rate 1.0・max_loss 6.0・yose_max_loss 2.0・dominant_hp 1.01・dominant_max_loss 3.0・min_human_policy 0.05・natural_ratio 0.1・cost_slack 0.3・trap_mode false・trap_min_delta_e 0.5・blunder_mode 2・blunder_max_loss 10.0・blunder_per_game 1・blunder_hp_ratio 0.7`）＋`forced_mode 0・forced_min_lead 2.0・forced_min_winrate 0.7・forced_max_loss 10.0`
  - `new` = `cur` の `forced_mode` を 2 にしたもの
- [ ] **Step 3: 通常の相手**（約 45 分）:
  `python -m katrain_debug.selfplay run --size 13 --pairs 20 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json --hp-audit rank_9d --label veil13-forced --arm cur=veil13:<24キー> --arm new=veil13:<24キー>`
  → `python -m katrain_debug.selfplay summarize <run>`。
- [ ] **Step 4: 接戦ストレス**（約 1 時間 45 分）:
  `python -m katrain_debug.selfplay run --size 13 --pairs 40 --komi-shift 4 --opponent strategy:human:human_kyu_rank=-8,modern_style=true --hp-audit rank_9d --label veil13-forced-p3 --arm cur=veil13:<24キー> --arm new=veil13:<24キー>`
- [ ] **Step 5: 集計**: `sdd-records/forced/forced_tables.py`（`sdd-records/blunder/blunder_tables.py` と同じ形）で `moves.jsonl` の `decision_forced`（gate / no_cand / rejected / played ほか）・`decision_forced_from`・打った手の cost・hp・lead_after・勝率・≥6目の数・1手の戦略時間 p95 を出す。
- [ ] **Step 6: 採否**（spec §14.4）:
  - (a) 通常: `new` の自分の一致率（1局ごとの平均）<= 42%・`new` の負け <= 1/20。
  - (b) 接戦ストレス: `new` の負け（持碁を含む）<= 2/40。
  - (c) この層で打った手の 9段 hp の中央値 >= 0.15。≥6目の手/局を出す。
  - (d) 戦略時間 p95 <= 2 秒。
  - (b) を満たさなければ `forced_min_lead 3・forced_min_winrate 0.75` で接戦ストレスだけやり直す。それでも満たさない、または (a) を満たさないときは、結果をユーザーに見せて決めてもらう。
- [ ] **Step 7: 記録**: campaign md に `## 最善手しか無い手番の外し（spec §14）の計測（実行日）` の節（実行条件・表・採否）。spec §14 に `### 14.5 計測の結果とユーザーの決定`、spec の状態行・`.claude/rules/ai-parameters.md` の段落を実測に合わせる。summary と run.json の写しを `calibration-data/selfplay/veil13-campaign/` に置く（前の段階と同じ形）。コミット。
- [ ] **Step 8: ユーザーの確認と仕上げ**: 結果を報告し、ユーザーの決定（ローカル設定で ON にするか・値を変えるか）を受けてから、KaTrain が止まっていることを確かめてメインセッションで `C:\Users\iwaki\.katrain\config.json` の `veil13_forced_*` を足す（`veil9`・`veil19` にも4キーを既定で足す＝GUI が読めるように）。変更前の写しを `sdd-records/forced/` に置く。最後にブランチ全体のレビュー → 全体のテスト → master にマージ（finishing-a-development-branch）。
