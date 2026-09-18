# 難解「捨て身の罠（overdraft）」オプション Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 難解 / 難解＋（9・13・19路）に、勝勢の消費モードでリードの予算を超えて「正しく応じられたら最大 D 目の劣勢・引っかかれば勝勢のまま」の罠を net 比較を飛ばして打つオプションを足す（既定 OFF＝ビット同一）。

**Architecture:** 判定は純関数 4 本（`enigma9_fooled_punish` / `enigma9_overdraft_window` / `enigma9_overdraft_probe_picks` / `enigma9_overdraft_pick`）に置き、`Enigma9Strategy._generate_move` には「窓の判定」「追加プローブ」「上限超え候補の振り分け」「スコアリング後の採用」の 4 箇所だけ差し込む。難解＋は `_generate_move` を継承、`Mimic13Strategy` は上書きしているので無関係。設定は接頭辞ごとに 4 キー × 6 戦略。

**Tech Stack:** Python 3.12 / pytest / Kivy 非依存のスタブテスト / gettext（`tools/compile_mo.py`）

**Spec:** `docs/superpowers/specs/2026-09-18-enigma-overdraft-design.md`（実測: `docs/superpowers/specs/calibration-data/enigma-overdraft/enigma-overdraft-results-20260918.md`）

## Global Constraints

- 既定値は `overdraft_deficit=0.0`（OFF）・`overdraft_answered_max=0.0`・`overdraft_min_fooled_lead=2.0`・`overdraft_probes=6`。OFF の手番は解析条件・採用判断ともビット同一
- 発動は ヨセ前 × 消費モード（`cost_weight < 1.0`）× `min(lead + D, ceiling) > cap`。`ceiling = max(cap, 1.5 × large_lead_max_loss)`。序盤の賭け罠（`cost_weight >= 1.0`）とは排他
- 資格は「検証済み損失が cap を超えた候補」だけが対象: `vloss <= ceiling`・`−D <= lead_after < min(target, answered_max)`（上端だけ exclusive）・`find <= 0.25`・`lead_after + e_fooled >= min_fooled_lead`。順位は `lead_after + E` 最大（同点は `lead_after` 大）。勝率フロア・net 比較・`net_margin`・局所性・難解＋の ΔE 床は通さない
- モジュール定数: `ENIGMA9_OVERDRAFT_MAX_FIND = ENIGMA9_HP_BOOK`(0.25) / `ENIGMA9_OVERDRAFT_CEILING_FACTOR = 1.5` / `ENIGMA9_OVERDRAFT_RAW_MARGIN = 1.5`
- GUI 表示名は「捨て身の罠」（en: All-in trap）。コード上の名前は overdraft
- 作業ツリーの既存ファイル（`katrain/core/*.py`・`katrain/config.json`・`.po`・`.claude/rules/*.md`・`INDEX.md`・`CLAUDE.md`・マニュアル）は **CRLF かつ .py は black 未整形**。Edit/Write ツールは PostToolUse フックで black が .py 全体を再整形するので、**既存ファイルはスクラッチの python パッチスクリプトで書き換える**。新規ファイルは Write でよい。パッチスクリプトは必ず次のヘルパーを使う（ヒット数を assert・CRLF を保つ）:

```python
import io


def patch(path, replacements):
    """replacements = [(old, new, 期待ヒット数)]。改行は LF に正規化して置換し、元が CRLF なら CRLF に戻す。"""
    raw = io.open(path, encoding="utf-8", newline="").read()
    crlf = "\r\n" in raw
    s = raw.replace("\r\n", "\n")
    for old, new, count in replacements:
        assert s.count(old) == count, (path, old[:70], s.count(old))
        s = s.replace(old, new)
    if crlf:
        s = s.replace("\n", "\r\n")
    io.open(path, "w", encoding="utf-8", newline="").write(s)
```

- `~/.katrain/config.json` はメインセッションが直接書く（サブエージェントに委任しない）。書く前に KaTrain が起動していないことを確かめる（起動中は終了時に上書きされる）
- pytest は KataGo と並走させない（時間閾値系のテストが偽陽性で落ちる）
- コミットメッセージは日本語・Conventional Commits・末尾に `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`

---

### Task 1: 純関数と定数

**Files:**
- Modify: `katrain/core/ai.py`（定数は `ENIGMA9_GAMBLE_PROBE_EXTRA = 4 ...` の行の直後、純関数は `enigma9_gamble_pick` の `return max(qualifiers, ...)` の直後・`@register_strategy(AI_ENIGMA_9)` の前）
- Create: `tests/test_ai_enigma_overdraft.py`

**Interfaces:**
- Produces:
  - `enigma9_fooled_punish(replies, hp_of, adequate_loss=ENIGMA9_ADEQUATE_LOSS, punish_cap=ENIGMA9_PUNISH_CAP) -> (e_fooled: float, p_fooled: float)`。`replies` は `enigma9_reply_table` の `[{"gtp","loss","visits"}]`、`hp_of` は `gtp -> humanPolicy`
  - `enigma9_overdraft_window(deficit, in_yose, cost_weight, lead, cap, large_cap, factor=ENIGMA9_OVERDRAFT_CEILING_FACTOR) -> (over_cap, ceiling) | None`
  - `enigma9_overdraft_probe_picks(candidates, best_gtp, taken, lo, hi, k, trusted_visits=ENIGMA9_TRUSTED_VISITS) -> list`。`candidates` は `parity9_build_candidates` の `[{"gtp","loss","visits","wr"}]`、`taken` は gtp の集合、帯は `(lo, hi]`
  - `enigma9_overdraft_pick(over_scored, deficit, upper, min_fooled_lead, ceiling, max_find=ENIGMA9_OVERDRAFT_MAX_FIND) -> (pick | None, qualifiers)`。`over_scored` の要素は `gtp` / `loss`（検証済み損失）/ `lead_after` / `e` / `e_fooled` / `find`。返す dict には `fooled_lead` と `u` が足される

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_ai_enigma_overdraft.py` を新規作成）

```python
# tests/test_ai_enigma_overdraft.py
"""難解の「捨て身の罠」オプション（spec 2026-09-18-enigma-overdraft-design.md）のテスト（KataGo/Kivy 不要）。"""
import pytest

from katrain.core.ai import (
    ENIGMA9_HP_BOOK,
    ENIGMA9_OVERDRAFT_CEILING_FACTOR,
    ENIGMA9_OVERDRAFT_MAX_FIND,
    ENIGMA9_OVERDRAFT_RAW_MARGIN,
    enigma9_fooled_punish,
    enigma9_overdraft_pick,
    enigma9_overdraft_probe_picks,
    enigma9_overdraft_window,
)


def hp_lookup(table):
    return lambda gtp: table.get(gtp, 0.0)


def reply(gtp, loss, visits=50):
    return {"gtp": gtp, "loss": loss, "visits": visits}


class TestConstants:
    def test_values(self):
        assert ENIGMA9_OVERDRAFT_MAX_FIND == ENIGMA9_HP_BOOK == 0.25
        assert ENIGMA9_OVERDRAFT_CEILING_FACTOR == 1.5
        assert ENIGMA9_OVERDRAFT_RAW_MARGIN == 1.5


class TestFooledPunish:
    def test_hp_weighted_mean_loss_of_inadequate_replies(self):
        replies = [reply("C3", 0.0, 300), reply("M12", 6.0), reply("Q1", 2.0, 5)]
        e_fooled, p_fooled = enigma9_fooled_punish(replies, hp_lookup({"C3": 0.1, "M12": 0.6, "Q1": 0.2}))
        assert e_fooled == pytest.approx((0.6 * 6.0 + 0.2 * 2.0) / 0.8)
        assert p_fooled == pytest.approx(0.8 / 0.9)

    def test_adequate_boundary_is_not_fooled(self):
        # 損失 0.3 目ちょうどは「十分な応手」＝引っかかった側に数えない
        replies = [reply("C3", 0.3), reply("M12", 0.31)]
        e_fooled, p_fooled = enigma9_fooled_punish(replies, hp_lookup({"C3": 0.5, "M12": 0.5}))
        assert e_fooled == pytest.approx(0.31)
        assert p_fooled == pytest.approx(0.5)

    def test_single_reply_loss_is_capped(self):
        e_fooled, _ = enigma9_fooled_punish([reply("C3", 0.0), reply("M12", 20.0)], hp_lookup({"C3": 0.2, "M12": 0.8}))
        assert e_fooled == pytest.approx(8.0)

    def test_no_inadequate_reply_or_no_hp_mass(self):
        assert enigma9_fooled_punish([reply("C3", 0.0)], hp_lookup({"C3": 0.9})) == (0.0, 0.0)
        assert enigma9_fooled_punish([reply("C3", 0.0), reply("M12", 5.0)], hp_lookup({})) == (0.0, 0.0)
        assert enigma9_fooled_punish([], hp_lookup({})) == (0.0, 0.0)


class TestOverdraftWindow:
    def test_off_when_deficit_is_zero(self):
        assert enigma9_overdraft_window(0.0, False, 0.4, 6.0, 4.0, 8.0) is None
        assert enigma9_overdraft_window(None, False, 0.4, 6.0, 4.0, 8.0) is None

    def test_requires_spending_mode_pre_yose_and_a_lead(self):
        assert enigma9_overdraft_window(2.5, False, 1.0, 6.0, 1.6, 8.0) is None  # 消費モードでない
        assert enigma9_overdraft_window(2.5, True, 0.4, 6.0, 4.0, 8.0) is None  # ヨセ
        assert enigma9_overdraft_window(2.5, False, 0.4, None, 4.0, 8.0) is None  # lead なし

    def test_over_cap_is_lead_plus_deficit(self):
        assert enigma9_overdraft_window(2.5, False, 0.4, 6.0, 4.0, 8.0) == (8.5, 12.0)

    def test_ceiling_clamps_the_window(self):
        # lead 11: cap は large(8) で頭打ち、over_cap = min(13.5, 1.5×8=12)
        assert enigma9_overdraft_window(2.5, False, 0.2, 11.0, 8.0, 8.0) == (12.0, 12.0)

    def test_window_closes_when_the_ceiling_is_not_above_the_cap(self):
        # large が小さく ceiling = max(cap, 6) = cap → 上限の外に帯が無い
        assert enigma9_overdraft_window(2.5, False, 0.2, 11.0, 8.0, 4.0) is None


def cand(gtp, loss, visits=1):
    return {"gtp": gtp, "loss": loss, "visits": visits, "wr": 0.5}


class TestOverdraftProbePicks:
    def test_band_excludes_best_pass_taken_and_out_of_range(self):
        cands = [cand("D4", 0.0, 900), cand("pass", 5.0), cand("K10", 3.0, 50), cand("G7", 5.0),
                 cand("H8", 2.5), cand("J9", 10.0), cand("A1", 10.1)]
        picks = enigma9_overdraft_probe_picks(cands, "D4", {"K10"}, 2.5, 10.0, 6)
        # H8 は下端ちょうど（exclusive）、J9 は上端ちょうど（inclusive）、A1 は帯の外
        assert [c["gtp"] for c in picks] == ["G7", "J9"]

    def test_trusted_candidates_are_spread_by_loss(self):
        trusted = [cand(f"T{i}", 3.0 + i, 20) for i in range(5)]
        picks = enigma9_overdraft_probe_picks([cand("D4", 0.0, 900)] + trusted, "D4", set(), 2.0, 9.0, 3)
        assert [c["gtp"] for c in picks] == ["T0", "T2", "T4"]

    def test_shallow_candidates_fill_the_rest_by_visits(self):
        cands = [cand("D4", 0.0, 900), cand("T0", 3.0, 20), cand("S1", 4.5, 3), cand("S2", 5.5, 8)]
        picks = enigma9_overdraft_probe_picks(cands, "D4", set(), 2.0, 9.0, 3)
        assert [c["gtp"] for c in picks] == ["T0", "S2", "S1"]

    def test_zero_probes_or_empty_band(self):
        assert enigma9_overdraft_probe_picks([cand("G7", 5.0)], "D4", set(), 2.0, 9.0, 0) == []
        assert enigma9_overdraft_probe_picks([cand("G7", 1.0)], "D4", set(), 2.0, 9.0, 6) == []


def over(gtp, lead_after, e, e_fooled, find=0.1, loss=None):
    return {"gtp": gtp, "lead_after": lead_after, "loss": (6.0 - lead_after) if loss is None else loss,
            "e": e, "e_fooled": e_fooled, "p_fooled": 0.9, "find": find, "wr_after": 0.35}


def pick(entries, deficit=2.5, upper=0.0, floor=2.0, ceiling=12.0):
    return enigma9_overdraft_pick(entries, deficit, upper, floor, ceiling)


class TestOverdraftPick:
    def test_qualifier_is_returned_with_derived_fields(self):
        chosen, quals = pick([over("G7", -1.5, 5.3, 6.0)])
        assert chosen["gtp"] == "G7"
        assert chosen["fooled_lead"] == pytest.approx(4.5)
        assert chosen["u"] == pytest.approx(3.8)
        assert len(quals) == 1

    def test_deficit_boundary_is_inclusive(self):
        assert pick([over("G7", -2.5, 5.0, 6.0)])[0] is not None
        assert pick([over("G7", -2.51, 5.0, 6.0)])[0] is None

    def test_upper_bound_is_exclusive(self):
        assert pick([over("G7", 0.0, 5.0, 6.0)])[0] is None
        assert pick([over("G7", -0.01, 5.0, 6.0)])[0] is not None
        # upper = 目標差（穏やかな手も含む設定）
        assert pick([over("G7", 0.5, 5.0, 6.0)], upper=2.0)[0] is not None
        assert pick([over("G7", 2.0, 5.0, 6.0)], upper=2.0)[0] is None

    def test_findability_gate_is_inclusive(self):
        assert pick([over("G7", -1.5, 5.0, 6.0, find=0.25)])[0] is not None
        assert pick([over("G7", -1.5, 5.0, 6.0, find=0.26)])[0] is None

    def test_fooled_lead_floor_is_inclusive(self):
        assert pick([over("G7", -1.5, 3.0, 3.5)])[0] is not None  # −1.5 + 3.5 = 2.0
        assert pick([over("G7", -1.5, 3.0, 3.4)])[0] is None

    def test_ceiling_is_inclusive(self):
        assert pick([over("G7", -1.5, 5.0, 6.0, loss=12.0)])[0] is not None
        assert pick([over("G7", -1.5, 5.0, 6.0, loss=12.1)])[0] is None

    def test_ranking_is_expected_lead_then_safer(self):
        a = over("A1", -2.0, 6.0, 7.0)  # u = 4.0
        b = over("B2", -0.5, 4.0, 5.0)  # u = 3.5
        c = over("C3", -1.0, 5.0, 6.0)  # u = 4.0（a と同点・応じられた後が浅い）
        chosen, quals = pick([a, b, c])
        assert chosen["gtp"] == "C3"
        assert {q["gtp"] for q in quals} == {"A1", "B2", "C3"}

    def test_empty_and_inputs_are_not_mutated(self):
        assert pick([]) == (None, [])
        entry = over("G7", -1.5, 5.3, 6.0)
        pick([entry])
        assert "fooled_lead" not in entry and "u" not in entry
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_ai_enigma_overdraft.py -q`
Expected: ImportError（`ENIGMA9_OVERDRAFT_CEILING_FACTOR` が無い）

- [ ] **Step 3: 実装**（python パッチスクリプトで `katrain/core/ai.py` に挿入。Global Constraints の `patch` ヘルパーを使う）

定数。アンカーは `ENIGMA9_GAMBLE_PROBE_EXTRA = 4              # 窓の中で保証する spread プローブ数（基底の安い順 7 手は高い帯を見ない）\n`（1 ヒット）で、その直後に挿入:

```python

# 捨て身の罠（overdraft）オプション（spec 2026-09-18-enigma-overdraft-design.md）。ヨセ前 × 勝勢の消費モード
# （cost_weight < 1）の手番で、リードの予算（lead − target）を超えて「正しく応じられたら最大
# `<prefix>_overdraft_deficit` 目の劣勢・引っかかれば勝勢のまま」の罠を net 比較を飛ばして打つ。
# deficit 0 = OFF（採用判断・解析条件とも従来とビット同一）。賭け罠（cost_weight >= 1 の手番）とは排他
ENIGMA9_OVERDRAFT_MAX_FIND = ENIGMA9_HP_BOOK   # 十分な応手の hp 最大値がこれ以下＝正しい応手が「本の手」でない
ENIGMA9_OVERDRAFT_CEILING_FACTOR = 1.5         # 1 手の損失の天井 = これ × large_lead_max_loss（+20 から 22 目捨てる手を塞ぐ）
ENIGMA9_OVERDRAFT_RAW_MARGIN = 1.5             # プローブ候補を選ぶ生 loss の帯の余裕（目）。生 loss は両側に外れる
```

純関数。アンカーは `    return max(qualifiers, key=lambda c: (c["u"], c["e"], -c["loss"])), qualifiers\n`（1 ヒット）で、その直後に挿入（先頭に空行 2 つ）:

```python


def enigma9_fooled_punish(replies, hp_of, adequate_loss=ENIGMA9_ADEQUATE_LOSS, punish_cap=ENIGMA9_PUNISH_CAP):
    """相手が罠に引っかかった場合の期待損失 (e_fooled, p_fooled) を返す。

    e_fooled = 「十分でない応手（損失 > adequate_loss）」だけの humanSL 重みつき平均損失（1 応手
    punish_cap 目で cap）。E（`enigma9_expected_punish`）は正しく応じた場合（損失 0）も平均に含むので、
    「引っかかったらどこまで戻るか」を測るには薄まる。p_fooled はその応手の hp 質量の割合（ログ用。
    find_hp < 0.2 帯のモデル値は過大＝予測 0.94 → 実現 0.60〜0.72・2026-09-03）。
    十分でない応手が無い・hp 質量が 0 なら (0.0, 0.0)。
    """
    total = sum(hp_of(r["gtp"]) for r in replies)
    if total <= 0.0:
        return 0.0, 0.0
    bad = [(hp_of(r["gtp"]), r["loss"]) for r in replies if r["loss"] > adequate_loss]
    bad_mass = sum(h for h, _ in bad)
    if bad_mass <= 0.0:
        return 0.0, 0.0
    return sum(h * min(loss, punish_cap) for h, loss in bad) / bad_mass, bad_mass / total


def enigma9_overdraft_window(deficit, in_yose, cost_weight, lead, cap, large_cap,
                             factor=ENIGMA9_OVERDRAFT_CEILING_FACTOR):
    """捨て身の罠の窓。開いていれば (over_cap, ceiling)、閉じていれば None。

    条件（全部 AND）: deficit > 0 ／ ヨセ前 ／ 消費モード（cost_weight < 1＝余剰リード > max_loss）／
    lead が取れている ／ over_cap = min(lead + deficit, ceiling) が通常上限 cap を超える。
    ceiling = max(cap, factor × large_cap) は 1 手の損失の天井。消費モードに限るのは実測
    （2026-09-18・13路 18 局）でリード 3.5 目以下の 126 手番に資格のある罠が 0 件だったため。
    """
    d = float(deficit or 0.0)
    if d <= 0.0 or in_yose or cost_weight >= 1.0 or lead is None:
        return None
    ceiling = max(cap, factor * large_cap)
    over_cap = min(lead + d, ceiling)
    if over_cap <= cap + 1e-9:
        return None
    return over_cap, ceiling


def enigma9_overdraft_probe_picks(candidates, best_gtp, taken, lo, hi, k,
                                  trusted_visits=ENIGMA9_TRUSTED_VISITS):
    """捨て身の罠の追加プローブ対象を k 手まで返す。

    生 loss が (lo, hi] の候補（最善手・pass・taken＝通常の shortlist を除く）から、信頼できる候補
    （visits >= trusted_visits）を loss 昇順で等間隔に k 手、足りなければ浅い候補を visits 多い順で
    埋める（`enigma9_shortlist_spread` の追加分と同じ規則）。プローブ前に罠を見分ける特徴は無い
    （実測: own_hp・visits・生 loss のどれも資格を予測しない）ので等間隔に撒く。
    """
    k = int(k or 0)
    if k <= 0:
        return []
    band = [
        c for c in candidates
        if c["gtp"] != best_gtp and c["gtp"] != "pass" and c["gtp"] not in taken and lo < c["loss"] <= hi
    ]
    trusted = sorted(
        [c for c in band if c.get("visits", 0) >= trusted_visits],
        key=lambda c: (c["loss"], -c.get("visits", 0)),
    )
    shallow = sorted(
        [c for c in band if c.get("visits", 0) < trusted_visits],
        key=lambda c: (-c.get("visits", 0), c["loss"]),
    )
    picks = _enigma9_spread_picks(trusted, k)
    if len(picks) < k:
        picks += shallow[: k - len(picks)]
    return picks


def enigma9_overdraft_pick(over_scored, deficit, upper, min_fooled_lead, ceiling,
                           max_find=ENIGMA9_OVERDRAFT_MAX_FIND):
    """捨て身の罠の資格がある候補から1手選ぶ。返り値 (pick | None, qualifiers)。

    over_scored は「検証済み損失が通常上限 cap を超えた」候補のスコアリング済みエントリ。資格は全部 AND:
      - loss <= ceiling（1 手の損失の天井）
      - −deficit <= lead_after < upper（正しく応じられた後のリード。上端だけ exclusive）
      - find <= max_find（十分な応手のうち最も見つけやすい手が 9 段の「本の手」でない）
      - lead_after + e_fooled >= min_fooled_lead（引っかかった場合に残るリード）
    順位は u = lead_after + E（相手の応手分布で見た期待リード）最大、同点は lead_after 大。
    入力の dict は書き換えない（返す dict に fooled_lead と u を足したコピー）。

    実測（2026-09-18・13路 18 局・消費モード 182 手番・12 プローブ）: 既定（必ずマイナス・下限 2 目）で
    資格ありは 23 手番＝1.28 回/局（6 プローブ換算 0.82 回/局）、うち 17 手番は資格が 1 手だけ。
    選ばれる手は中央値 vloss 8.4・応じられたら −0.48・引っかかれば +3.3、E − vloss は −4.25
    ＝期待値では毎回損をする演出用のオプション。
    """
    eps = 1e-9
    qualifiers = []
    for c in over_scored:
        la = c.get("lead_after")
        if la is None or la < -deficit - eps or la >= upper:
            continue
        if c["loss"] > ceiling + eps:
            continue
        find = c.get("find")
        if find is None or find > max_find + eps:
            continue
        fooled_lead = la + c.get("e_fooled", 0.0)
        if fooled_lead < min_fooled_lead - eps:
            continue
        qualifiers.append({**c, "fooled_lead": fooled_lead, "u": la + c["e"]})
    if not qualifiers:
        return None, []
    return max(qualifiers, key=lambda c: (c["u"], c["lead_after"])), qualifiers
```

- [ ] **Step 4: 通過を確認**

Run: `python -m pytest tests/test_ai_enigma_overdraft.py -q`
Expected: 全部 PASS

Run: `git diff --stat katrain/core/ai.py`
Expected: 追加行のみ（削除 0 行＝再整形の混入なし）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_enigma_overdraft.py
git commit -m "feat(enigma): 捨て身の罠の純関数（窓・追加プローブ・引っかかった場合の得・資格つき選択）"
```

---

### Task 2: 設定キーの登録（SETTING_DEFAULTS・GUI 候補値・パッケージ config・i18n）

既存の不変条件テスト（`tests/test_ai_enigma9.py::TestGuiConfigConsistency`・`tests/test_ai_enigma_plus.py` の
`test_base_options_are_shared_with_the_base_strategy` / `test_i18n_has_name_and_labels` ほか）が
SETTING_DEFAULTS ↔ `AI_OPTION_VALUES` ↔ `AI_OPTION_ORDER` ↔ パッケージ `config.json` ↔ `.po` の整合を検査するので、
全部を同じタスクで入れる。

**Files:**
- Modify: `katrain/core/ai.py`（`Enigma9Strategy` / `Enigma13Strategy` / `Enigma19Strategy` の `SETTING_DEFAULTS`）
- Modify: `katrain/core/constants.py`（`AI_OPTION_VALUES` / `AI_OPTION_ORDER`）
- Modify: `katrain/config.json`
- Modify: `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po` → `python tools/compile_mo.py`
- Test: `tests/test_ai_enigma_overdraft.py`（追記）

**Interfaces:**
- Produces: 設定キー `<prefix>_overdraft_deficit` / `<prefix>_overdraft_answered_max` / `<prefix>_overdraft_min_fooled_lead` / `<prefix>_overdraft_probes`
  （prefix = enigma9 / enigma9plus / enigma13 / enigma13plus / enigma19 / enigma19plus）。`self._setting("overdraft_deficit")` 等で読める

- [ ] **Step 1: 失敗するテストを追記**（`tests/test_ai_enigma_overdraft.py` の末尾）

```python
from katrain.core.ai import (
    Enigma9PlusStrategy,
    Enigma9Strategy,
    Enigma13PlusStrategy,
    Enigma13Strategy,
    Enigma19PlusStrategy,
    Enigma19Strategy,
    Mimic13Strategy,
)
from katrain.core.constants import AI_OPTION_VALUES

ALL_ENIGMA = [
    Enigma9Strategy, Enigma9PlusStrategy, Enigma13Strategy, Enigma13PlusStrategy,
    Enigma19Strategy, Enigma19PlusStrategy,
]


def _plain(key):
    return [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]


class TestOverdraftSettings:
    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_defaults_are_off_negative_only_two_points_six_probes(self, cls):
        d = cls.SETTING_DEFAULTS
        assert d["overdraft_deficit"] == 0
        assert d["overdraft_answered_max"] == 0
        assert d["overdraft_min_fooled_lead"] == 2.0
        assert d["overdraft_probes"] == 6

    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_gui_options(self, cls):
        p = cls.KEY_PREFIX
        deficit = _plain(f"{p}_overdraft_deficit")
        assert deficit[0] == 0 and 2.5 in deficit
        assert AI_OPTION_VALUES[f"{p}_overdraft_deficit"][0] == (0.0, "OFF")
        assert _plain(f"{p}_overdraft_answered_max") == [-1.0, 0.0, 99.0]
        assert _plain(f"{p}_overdraft_min_fooled_lead") == [1.0, 2.0, 3.0, 5.0, 8.0]
        assert _plain(f"{p}_overdraft_probes") == [4, 6, 8, 12]

    def test_mimic13_is_untouched(self):
        assert not any(k.startswith("overdraft") for k in Mimic13Strategy.SETTING_DEFAULTS)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_ai_enigma_overdraft.py -q`
Expected: `KeyError: 'overdraft_deficit'`

- [ ] **Step 3: 実装**（スクラッチの python パッチスクリプト 1 本で 5 ファイルを書き換える。リポジトリのルートで実行）

```python
# scratch: patch_overdraft_task2.py（Global Constraints の patch ヘルパーを先頭に貼る）
import io
import re

PREFIXES = ["enigma9", "enigma9plus", "enigma13", "enigma13plus", "enigma19", "enigma19plus"]
BASES = {"enigma9": 9, "enigma13": 13, "enigma19": 19}

# ---- ai.py: 3 クラスの SETTING_DEFAULTS ----
OLD = '        "gamble_min_delta_e": 0.5,       # 賭け罠: 罠とみなす E の上積み（目）\n'
NEW = OLD + (
    '        "overdraft_deficit": 0.0,            # 捨て身の罠: 最大ビハインド（目・0=OFF）。spec 2026-09-18-enigma-overdraft-design.md\n'
    '        "overdraft_answered_max": 0.0,       # 捨て身の罠: 応じられた後のリードの上限（0=必ずマイナス・99=目標差未満）\n'
    '        "overdraft_min_fooled_lead": 2.0,    # 捨て身の罠: 引っかかった場合に残るリードの下限（目）\n'
    '        "overdraft_probes": 6,               # 捨て身の罠: 追加プローブ数\n'
)
patch("katrain/core/ai.py", [(OLD, NEW, 3)])

# ---- constants.py ----
reps = [(
    "_ENIGMA_GAMBLE_MIN_DELTA_E = [0.3, 0.5, 0.7, 1.0, 1.5]\n",
    "_ENIGMA_GAMBLE_MIN_DELTA_E = [0.3, 0.5, 0.7, 1.0, 1.5]\n"
    "\n"
    "# 難解の捨て身の罠（enigma*_overdraft_*・spec 2026-09-18-enigma-overdraft-design.md）。全盤サイズ共通。\n"
    "# deficit 0=OFF、answered_max は「応じられた後のリードの上限」（99=MAX＝目標差未満まで）\n"
    '_ENIGMA_OVERDRAFT_DEFICIT = [(0.0, "OFF"), (1.0, "1.0"), (1.5, "1.5"), (2.0, "2.0"), (2.5, "2.5"), (3.0, "3.0"), (4.0, "4.0"), (5.0, "5.0")]\n'
    '_ENIGMA_OVERDRAFT_ANSWERED_MAX = [(-1.0, "-1"), (0.0, "0"), (99.0, "MAX")]\n'
    "_ENIGMA_OVERDRAFT_MIN_FOOLED_LEAD = [1.0, 2.0, 3.0, 5.0, 8.0]\n"
    "_ENIGMA_OVERDRAFT_PROBES = [4, 6, 8, 12]\n",
    1,
)]
for p in PREFIXES:
    old = f'    "{p}_gamble_min_delta_e": _ENIGMA_GAMBLE_MIN_DELTA_E,\n'
    reps.append((old, old + (
        f'    "{p}_overdraft_deficit": _ENIGMA_OVERDRAFT_DEFICIT,\n'
        f'    "{p}_overdraft_answered_max": _ENIGMA_OVERDRAFT_ANSWERED_MAX,\n'
        f'    "{p}_overdraft_min_fooled_lead": _ENIGMA_OVERDRAFT_MIN_FOOLED_LEAD,\n'
        f'    "{p}_overdraft_probes": _ENIGMA_OVERDRAFT_PROBES,\n'
    ), 1))
    old = f'    "{p}_gamble_min_delta_e": 16,\n'
    reps.append((old, old + (
        f'    "{p}_overdraft_deficit": 17,\n'
        f'    "{p}_overdraft_answered_max": 18,\n'
        f'    "{p}_overdraft_min_fooled_lead": 19,\n'
        f'    "{p}_overdraft_probes": 20,\n'
    ), 1))
patch("katrain/core/constants.py", reps)

# ---- katrain/config.json（各セクションの末尾行＝カンマ無し）----
reps = []
for p in PREFIXES:
    old = f'            "{p}_gamble_min_delta_e": 0.5\n'
    reps.append((old, (
        f'            "{p}_gamble_min_delta_e": 0.5,\n'
        f'            "{p}_overdraft_deficit": 0.0,\n'
        f'            "{p}_overdraft_answered_max": 0.0,\n'
        f'            "{p}_overdraft_min_fooled_lead": 2.0,\n'
        f'            "{p}_overdraft_probes": 6\n'
    ), 1))
patch("katrain/config.json", reps)

# ---- .po（ラベル 24×2・aihelp 3×2）----
LABELS = {
    "jp": [
        ("overdraft_deficit", "捨て身の罠: 最大ビハインド（目・OFF=従来）"),
        ("overdraft_answered_max", "捨て身の罠: 応じられた後のリード上限（MAX=目標差未満）"),
        ("overdraft_min_fooled_lead", "捨て身の罠: 引っかかった時に残るリードの下限（目）"),
        ("overdraft_probes", "捨て身の罠: 追加プローブ数"),
    ],
    "en": [
        ("overdraft_deficit", "All-in trap: max deficit if answered (pts, OFF = classic)"),
        ("overdraft_answered_max", "All-in trap: lead ceiling if answered (MAX = below target)"),
        ("overdraft_min_fooled_lead", "All-in trap: minimum lead if the opponent falls for it (pts)"),
        ("overdraft_probes", "All-in trap: extra probes"),
    ],
}
HELP = {
    "jp": (
        "{p}_overdraft_deficit: 捨て身の罠（既定 OFF）。ヨセ前・勝勢の消費モード中の手番で、リードの予算（リード − 目標差）を超えて払う罠を探します。"
        "通常の損失上限の外側から「リード ＋ この値」までの候補を {p}_overdraft_probes 手だけ追加で検証し、"
        "「正しく応じられた後のリードが −この値 以上かつ {p}_overdraft_answered_max 未満（0=必ずマイナスになる手だけ・MAX=目標差未満＝応じられても少しプラスで済む手も含む）・"
        "十分な応手が 9 段の第一感（25%）に無い・引っかかった場合（十分でない応手を 9 段の第一感で重みづけた平均）のリードが {p}_overdraft_min_fooled_lead 以上」を"
        "全部満たす手があれば、難解さの比較と勝率フロアを飛ばしてその罠を打ちます（複数あれば 応じられた後のリード＋E が最大の手）。"
        "1 手の損失は勝勢時の勝負手損失上限の 1.5 倍まで。正しく応じられたら素直に劣勢になり、消費モードが切れるので従来どおり実質最善手で打ち続けます。"
        "13路の実測では既定値（必ずマイナス・下限 2 目・6 手）で約 0.8 回/局・55% の局で 1 回以上、リード 3.5 目以下の局面には在庫がありません。"
        "モデル自身の見積もりで 1 回あたり 3〜4 目の期待値の損＝演出用のオプションです（検証 1 手につきコールド約 +0.2 秒）。"
    ),
    "en": (
        "{p}_overdraft_deficit: all-in traps (off by default). Before the endgame and only while the far-ahead spending mode is active, the AI also looks for traps that cost more than its lead budget (lead minus target). "
        "It verifies {p}_overdraft_probes extra candidates from just beyond the normal loss cap up to 'lead + this value', and if some move "
        "(1) still leaves the lead at or above minus this value and below {p}_overdraft_answered_max when the opponent answers correctly (0 = only moves that really fall behind, MAX = anything below the target, including milder traps that stay slightly ahead), "
        "(2) has no adequate reply among a 9-dan's first instincts (25%), and (3) keeps the lead at or above {p}_overdraft_min_fooled_lead when the opponent falls for it (average over the inadequate replies weighted by a 9-dan's instincts), "
        "that trap is played without the usual difficulty comparison or the winrate floor (with several, the one maximising lead-if-answered plus E). "
        "A single move never loses more than 1.5x the far-ahead loss cap. If the opponent answers correctly the AI simply falls behind; the spending mode switches off and it keeps playing essentially the best moves. "
        "Measured on 13x13: about 0.8 such traps per game at the defaults (at least one in 55% of games), none when the lead is 3.5 points or less, and by the model's own estimate each one gives up 3-4 points of expectation, "
        "so this is a showmanship option (each extra probe costs about +0.2 s on a cold cache). "
    ),
}
TAIL = {
    "jp": lambda n: f"{n}路以外の盤では常に最善手を打つだけになるので、他の戦略を使ってください。",
    "en": lambda n: "On other board sizes it simply plays the best move.",
}
for lang in ("jp", "en"):
    path = f"katrain/i18n/locales/{lang}/LC_MESSAGES/katrain.po"
    s = io.open(path, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    reps = []
    for p in PREFIXES:
        bracket = re.search(r'msgid "%s_max_loss"\nmsgstr "(\[[^\]]+\])' % p, s).group(1)
        entry = re.search(r'msgid "%s_gamble_min_delta_e"\nmsgstr "[^\n]*"\n' % p, s).group(0)
        added = "".join(f'\nmsgid "{p}_{sfx}"\nmsgstr "{bracket} {text}"\n' for sfx, text in LABELS[lang])
        reps.append((entry, entry + added, 1))
    for p, n in BASES.items():
        line = re.search(r'msgid "aihelp:%s"\nmsgstr "[^\n]*"\n' % p, s).group(0)
        tail = TAIL[lang](n)
        assert line.count(tail) == 1, (lang, p)
        reps.append((line, line.replace(tail, HELP[lang].format(p=p) + tail), 1))
    patch(path, reps)
print("ok")
```

難解＋の `aihelp:*plus` は「他の項目は難解の同名項目と同じ意味」と基底に委ねているので触らない。

- [ ] **Step 4: `.mo` を再コンパイルしてテスト**

Run: `python tools/compile_mo.py`
Run: `python -m pytest tests/test_ai_enigma_overdraft.py tests/test_ai_enigma_gamble.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py tests/test_ai_mimic13.py tests/test_ai_options_grid.py -q`
Expected: 全部 PASS（`TestGuiConfigConsistency` と難解＋の i18n テストが新キーを検査する）

- [ ] **Step 5: 差分の健全性を確認してコミット**

Run: `git diff --stat`
Expected: 削除行は「config.json の 6 行（カンマ追加）＋ .po の help 6 行」だけ（再整形の混入なし）。`.mo` 2 本が更新されている

```bash
git add katrain/core/ai.py katrain/core/constants.py katrain/config.json katrain/i18n tests/test_ai_enigma_overdraft.py
git commit -m "feat(enigma): 捨て身の罠の設定キーを GUI・config・i18n に登録"
```

---

### Task 3: `_generate_move` への接続

**Files:**
- Modify: `katrain/core/ai.py`（`Enigma9Strategy._generate_move` の 5 箇所の置換）
- Test: `tests/test_ai_enigma_overdraft.py`（追記）

**Interfaces:**
- Consumes: Task 1 の純関数 4 本と定数 `ENIGMA9_OVERDRAFT_RAW_MARGIN`・Task 2 の設定キー。`_generate_move` 内の既存ローカル変数
  `in_yose` / `cost_weight` / `lead_now`（`not in_yose` のときだけ定義される）/ `cap` / `large_cap` / `target` / `candidates` / `shortlist` / `probes`
- Produces: ログ `Overdraft: window …` / `Over <gtp>: …` / `Overdraft: band=… qualifiers=…` / `Overdraft: played <gtp> …`、ai_thoughts `<LABEL>: overdraft trap <gtp> (…)`

- [ ] **Step 1: 失敗する接続テストを追記**（`tests/test_ai_enigma_overdraft.py` の末尾）

```python
import types


def _hp(size, values):
    """humanPolicy のフラット配列（size×size＋pass）。values は {gtp: hp}。"""
    from katrain.core.sgf_parser import Move

    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def _child(lead_after, wr_after, replies, reply_hp, size=13):
    """黒番が打った後の子局面プローブ（clean + hp）。replies は [(gtp, 白視点の損失, visits)]。

    KataGo の scoreLead / winrate は常に黒視点。白の最善応手後の黒リードが lead_after、
    白が loss 目損する応手の後は lead_after + loss。
    """
    move_infos = [
        {"move": g, "scoreLead": lead_after + loss, "visits": v, "order": i}
        for i, (g, loss, v) in enumerate(replies)
    ]
    return {
        "clean": {"rootInfo": {"scoreLead": lead_after, "winrate": wr_after}, "moveInfos": move_infos},
        "hp": {"humanPolicy": _hp(size, reply_hp)},
    }


EASY = ([("C3", 0.0, 300), ("N1", 0.4, 20)], {"C3": 0.9, "N1": 0.05})  # 応手が自明＝E≈0
TRAP = ([("C3", 0.0, 300), ("M12", 6.0, 40)], {"C3": 0.10, "M12": 0.80})  # 正解 C3 は hp 10%・自然な M12 は 6 目損


def _overdraft_strategy(cls, prefix, settings=None, *, root_lead=6.0, d4_lead=6.0, g7_lead=-1.5, h8_lead=3.2,
                        endgame=False):
    """黒 +6 目（target 2・max_loss 1.6 → 消費モード cap 4.0）の13路・黒番。

    D4=最善（子局面 root のリード d4_lead＝検証済み損失の基準）/ K10=安い外し（従来の net 比較はこれを選ぶ）/
    H8=生 loss 3.0（通常の shortlist に入る）/ G7=生 loss 7.5（通常上限の外＝捨て身の罠の追加プローブでしか
    調べない）。G7 は応じられたら g7_lead（既定 −1.5・勝率 20%＝勝率フロア 30% 未満）、引っかかれば +6 目戻る本物の罠。
    """
    logs = []
    katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
    cands = [
        {"move": "D4", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.95},
        {"move": "K10", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 60, "winrate": 0.94},
        {"move": "H8", "pointsLost": 3.0, "relativePointsLost": 3.0, "visits": 30, "winrate": 0.80},
        {"move": "G7", "pointsLost": 7.5, "relativePointsLost": 7.5, "visits": 1, "winrate": 0.20},
    ]
    node = types.SimpleNamespace(
        next_player="B", player="W", depth=40, move=None, analysis_complete=True,
        analysis={"root": {"scoreLead": root_lead}}, candidate_moves=cands,
    )
    game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(13, 13))
    if endgame:
        setattr(game, f"_{prefix}_endgame", True)
    base = {f"{prefix}_opening_humanstyle_moves": 0, f"{prefix}_max_loss": 1.6, f"{prefix}_locality_stddev": 0.0}
    s = cls(game, {**base, **(settings or {})})
    s.probed = []

    def probe(gtps, player, parent_hp=False):
        s.probed.append(list(gtps))
        h8 = TRAP if h8_lead < 0 else EASY
        table = {
            "D4": _child(d4_lead, 0.95, *EASY),
            "K10": _child(5.9, 0.94, *EASY),
            "H8": _child(h8_lead, 0.80 if h8_lead >= 0 else 0.25, *h8),
            "G7": _child(g7_lead, 0.20, *TRAP),
        }
        parent = {"humanPolicy": _hp(13, {"D4": 0.6, "H8": 0.1, "G7": 0.05})} if parent_hp else None
        return {g: table[g] for g in gtps}, parent

    s._probe_children = probe
    s._run_query = lambda label, **kw: None
    return s, logs


ON = {"enigma13_overdraft_deficit": 2.5}


class TestOverdraftEndToEnd:
    def test_off_plays_the_classic_choice_and_never_probes_beyond_the_cap(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13")
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert "G7" not in s.probed[0]
        assert not any("Over" in m for m in logs)

    def test_on_plays_the_trap_beyond_the_cap_ignoring_the_winrate_floor(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON)
        move, thoughts = s.generate_move()
        assert move.gtp() == "G7"
        assert "overdraft trap G7" in thoughts
        assert "G7" in s.probed[0]
        assert any("Overdraft: window" in m and "G7" in m for m in logs)
        assert any("Overdraft: played G7" in m for m in logs)

    def test_deficit_setting_blocks_a_deeper_fall(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", {"enigma13_overdraft_deficit": 1.0})
        assert s.generate_move()[0].gtp() == "K10"  # 応じられたら −1.5 < −1.0
        assert any("Overdraft: band" in m and "qualifiers=[]" in m for m in logs)

    def test_fooled_lead_setting_blocks_the_trap(self):
        s, _ = _overdraft_strategy(
            Enigma13Strategy, "enigma13", {**ON, "enigma13_overdraft_min_fooled_lead": 5.0}
        )
        assert s.generate_move()[0].gtp() == "K10"  # 引っかかっても −1.5 + 6.0 = 4.5 < 5.0

    def test_negative_only_default_skips_a_mild_trap(self):
        s, _ = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, g7_lead=0.5)
        assert s.generate_move()[0].gtp() == "K10"

    def test_answered_max_setting_admits_a_mild_trap_below_the_target(self):
        s, _ = _overdraft_strategy(
            Enigma13Strategy, "enigma13", {**ON, "enigma13_overdraft_answered_max": 99.0}, g7_lead=0.5
        )
        assert s.generate_move()[0].gtp() == "G7"

    def test_shortlist_candidate_verified_beyond_the_cap_is_routed_instead_of_dropped(self):
        # H8 は生 loss 3.0 で通常の shortlist に入るが、検証すると −1.0（vloss 7.0 > cap 4.0）
        off, off_logs = _overdraft_strategy(Enigma13Strategy, "enigma13", h8_lead=-1.0)
        assert off.generate_move()[0].gtp() == "K10"
        assert any("Drop H8" in m for m in off_logs)
        on, on_logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, h8_lead=-1.0)
        # H8（u = −1.0 + E）と G7（u = −1.5 + E）の両方が資格あり → 期待リードの大きい H8
        assert on.generate_move()[0].gtp() == "H8"
        assert not any("Drop H8" in m for m in on_logs)

    def test_outside_the_spending_mode_nothing_changes(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, root_lead=0.2)
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert "G7" not in s.probed[0]
        assert not any("Over" in m for m in logs)

    def test_yose_is_left_alone(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, endgame=True)
        move, _ = s.generate_move()
        assert move.gtp() == "D4"  # スタブの Probe は None → lead unavailable → 最善手
        assert not any("Over" in m for m in logs)

    def test_plus_inherits_the_overdraft(self):
        s, _ = _overdraft_strategy(Enigma13PlusStrategy, "enigma13plus", {"enigma13plus_overdraft_deficit": 2.5})
        assert s.generate_move()[0].gtp() == "G7"

    def test_aim_jigo_band_ends_at_minus_one(self):
        # aim_jigo: target = −1 → cap = min(8, lead + 1) = 7.0、帯は [−2.5, min(−1, 0)) ＝ [−2.5, −1)
        jigo = {**ON, "enigma13_aim_jigo": True}
        deep, _ = _overdraft_strategy(Enigma13Strategy, "enigma13", jigo)  # vloss 7.5 > 7.0・応じられたら −1.5
        assert deep.generate_move()[0].gtp() == "G7"
        # 最善手の子局面が +7（root の +6 より上）だと、応じられたら −0.5 の G7 も vloss 7.5 で上限の外に
        # 回るが、帯の上端（target = −1）の外なので資格なし → 従来の選択（G7 は scored に居ない）
        mild, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", jigo, d4_lead=7.0, g7_lead=-0.5)
        assert mild.generate_move()[0].gtp() == "K10"
        assert any("Overdraft: band=[-2.5, -1.0)" in m and "qualifiers=[]" in m for m in logs)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_ai_enigma_overdraft.py::TestOverdraftEndToEnd -q`
Expected: `test_off_*` / `test_outside_*` / `test_yose_*` / `test_deficit_*`（K10 は合うがログの assert で FAIL）などが混在。
ON で G7 / H8 を期待するテスト（`test_on_*` / `test_answered_max_*` / `test_shortlist_*` / `test_plus_*` / `test_aim_jigo_*`）は FAIL（K10 のまま）

- [ ] **Step 3: 実装**（スクラッチの python パッチスクリプト・`patch` ヘルパーで `katrain/core/ai.py` の 5 箇所。全部 1 ヒット）

(a) 窓の判定。賭け罠の窓の直後に足す:

```python
OLD_A = (
    "            not in_yose and cost_weight >= 1.0 and enigma9_gamble_window(self.cn.depth, gamble_until)\n"
    "        )\n"
)
NEW_A = OLD_A + (
    "\n"
    "        # ---- 捨て身の罠（overdraft）の窓（spec 2026-09-18-enigma-overdraft-design.md）----\n"
    "        # ヨセ前 × 勝勢の消費モード（cost_weight < 1）× deficit > 0。OFF（既定）なら None＝以降の分岐は\n"
    "        # すべて従来どおり（ビット同一）。賭け罠（cost_weight >= 1 の手番）とは排他。lead_now は\n"
    "        # `not in_yose` の分岐でしか定義されないので、その内側でだけ参照する\n"
    "        over_win = None\n"
    "        if not in_yose and cost_weight < 1.0:\n"
    "            over_win = enigma9_overdraft_window(\n"
    '                self._setting("overdraft_deficit"), in_yose, cost_weight, lead_now, cap, large_cap\n'
    "            )\n"
)
```

(b) 追加プローブ。子局面プローブのコメント行の直前に足す:

```python
OLD_B = "        # ---- 子局面プローブ + 親局面 humanSL（自手の意外さ用）を1バッチで並列発行 ----\n"
NEW_B = (
    "        # ---- 捨て身の罠の追加プローブ（窓が開いている手番だけ）----\n"
    "        # 通常上限の外側〜over_cap の候補を生 loss で等間隔に選ぶ（生 loss は両側に外れるので帯を\n"
    "        # RAW_MARGIN ぶん広げる）。勝率フロアは見ない。採否は子局面プローブの検証値で決める\n"
    "        over_picks = []\n"
    "        if over_win is not None:\n"
    "            over_cap, over_ceiling = over_win\n"
    "            over_picks = enigma9_overdraft_probe_picks(\n"
    '                candidates, best_gtp, {c["gtp"] for c in shortlist},\n'
    "                cap - ENIGMA9_OVERDRAFT_RAW_MARGIN, over_cap + ENIGMA9_OVERDRAFT_RAW_MARGIN,\n"
    '                int(self._setting("overdraft_probes")),\n'
    "            )\n"
    "            self._log(\n"
    '                f"Overdraft: window lead={lead_now:.2f} cap={cap:.2f} over_cap={over_cap:.2f} "\n'
    '                f"ceiling={over_ceiling:.2f} probes +{len(over_picks)} "\n'
    "                f\"{[(c['gtp'], round(c['loss'], 2)) for c in over_picks]}\"\n"
    "            )\n"
    "\n"
) + OLD_B
```

(c) プローブ対象に足す:

```python
OLD_C = "        probe_items = ([best_cand] if best_cand else []) + shortlist\n"
NEW_C = "        probe_items = ([best_cand] if best_cand else []) + shortlist + over_picks\n"
```

(d) 上限超えの候補を捨てずに振り分ける（2 置換）:

```python
OLD_D1 = "        scored = []\n        for c in probe_items:\n"
NEW_D1 = "        scored = []\n        over_scored = []  # 捨て身の罠: 検証済み損失が cap を超えた候補（窓が開いている手番だけ）\n        for c in probe_items:\n"

OLD_D2 = (
    '            if c["gtp"] != best_gtp:\n'
    "                if vloss > cap:\n"
    "                    self._log(\n"
    "                        f\"Drop {c['gtp']}: verified loss {vloss:.2f} > cap {cap:.2f} \"\n"
    "                        f\"(raw {c['loss']:.2f}, v{c.get('visits', 0)})\"\n"
    "                    )\n"
    "                    continue\n"
    "                if wr_after is not None and wr_after < min_wr:\n"
)
NEW_D2 = (
    "            over_route = False\n"
    '            if c["gtp"] != best_gtp:\n'
    "                if vloss > cap:\n"
    "                    if over_win is None or vloss > over_win[1]:\n"
    "                        self._log(\n"
    "                            f\"Drop {c['gtp']}: verified loss {vloss:.2f} > cap {cap:.2f} \"\n"
    "                            f\"(raw {c['loss']:.2f}, v{c.get('visits', 0)})\"\n"
    "                        )\n"
    "                        continue\n"
    "                    over_route = True  # 捨て身の罠の候補。勝率フロアは見ない（意図して 50% を割る手）\n"
    "                elif wr_after is not None and wr_after < min_wr:\n"
)

OLD_D3 = (
    "            findability = enigma9_reply_findability(replies, hp_of)\n"
    '            own_hp = own_hp_of(c["gtp"])\n'
)
NEW_D3 = (
    "            findability = enigma9_reply_findability(replies, hp_of)\n"
    "            if over_route:\n"
    "                e_fooled, p_fooled = enigma9_fooled_punish(replies, hp_of)\n"
    "                over_scored.append(\n"
    '                    {**c, "loss": vloss, "raw_loss": c["loss"], "lead_after": lead_after, "wr_after": wr_after,\n'
    '                     "e": e_punish, "e_fooled": e_fooled, "p_fooled": p_fooled, "find": findability,\n'
    '                     "reply": best_reply}\n'
    "                )\n"
    '                wr_txt = "n/a" if wr_after is None else f"{wr_after:.1%}"\n'
    "                self._log(\n"
    "                    f\"Over {c['gtp']}: vloss={vloss:.2f} (raw {c['loss']:.2f}) la={lead_after:+.2f} wr={wr_txt} \"\n"
    '                    f"E={e_punish:.2f} Ef={e_fooled:.2f} p_fooled={p_fooled:.0%} find_hp={findability:.3f} "\n'
    '                    f"reply={best_reply}"\n'
    "                )\n"
    "                continue\n"
    '            own_hp = own_hp_of(c["gtp"])\n'
)
```

`elif` にしてよい理由: 元のコードは `vloss > cap` なら必ず `continue` するので、勝率フロアの判定は `vloss <= cap` のときしか走らない＝
`elif` と等価。`over_route` のときだけ勝率フロアを飛ばす。

(e) スコアリング後の採用。賭け罠の採用ブロックの直前に足す:

```python
OLD_E = (
    "        if gamble_on:\n"
    "            # 賭け罠: 資格（勝率フロア・ΔE・応手の見つけにくさ）のある挑戦者が居れば、net 比較・\n"
)
NEW_E = (
    "        if over_win is not None:\n"
    "            # 捨て身の罠: 資格（応じられた後のリードの帯・応手の見つけにくさ・引っかかった後のリード）の\n"
    "            # ある候補が居れば、net 比較・net_margin・局所性・ΔE 床・勝率フロアを通さずに打つ\n"
    '            o_deficit = float(self._setting("overdraft_deficit"))\n'
    '            o_upper = min(target, float(self._setting("overdraft_answered_max")))\n'
    '            o_floor = float(self._setting("overdraft_min_fooled_lead"))\n'
    "            o_pick, o_quals = enigma9_overdraft_pick(over_scored, o_deficit, o_upper, o_floor, over_win[1])\n"
    "            self._log(\n"
    '                f"Overdraft: band=[{-o_deficit:.1f}, {o_upper:.1f}) fooled>={o_floor:.1f} "\n'
    '                f"scored={len(over_scored)} qualifiers="\n'
    "                f\"{[(c['gtp'], round(c['lead_after'], 2), round(c['fooled_lead'], 2)) for c in o_quals]}\"\n"
    "            )\n"
    "            if o_pick is not None:\n"
    "                self._log(\n"
    "                    f\"Overdraft: played {o_pick['gtp']} (answered {o_pick['lead_after']:+.2f}, \"\n"
    "                    f\"fooled {o_pick['fooled_lead']:+.2f}, vloss={o_pick['loss']:.2f}, E={o_pick['e']:.2f}, \"\n"
    "                    f\"find_hp={o_pick['find']:.3f}, p_fooled={o_pick['p_fooled']:.0%}) instead of {best_gtp}\"\n"
    "                )\n"
    '                self._start_ponder(o_pick["gtp"], probes.get(o_pick["gtp"]), player)\n'
    "                return (\n"
    '                    Move.from_gtp(o_pick["gtp"], player=player),\n'
    "                    f\"{self.LABEL}: overdraft trap {o_pick['gtp']} (verified loss {o_pick['loss']:.2f}, \"\n"
    "                    f\"lead {o_pick['lead_after']:+.2f} if answered correctly, {o_pick['fooled_lead']:+.2f} if the \"\n"
    "                    f\"opponent falls for it, reply findability {o_pick['find']:.1%}) instead of {best_gtp}.\",\n"
    "                )\n"
    "\n"
) + OLD_E
```

スクリプトの最後で `patch("katrain/core/ai.py", [(OLD_A, NEW_A, 1), (OLD_B, NEW_B, 1), (OLD_C, NEW_C, 1), (OLD_D1, NEW_D1, 1), (OLD_D2, NEW_D2, 1), (OLD_D3, NEW_D3, 1), (OLD_E, NEW_E, 1)])`。

- [ ] **Step 4: 通過を確認**

Run: `python -m pytest tests/test_ai_enigma_overdraft.py tests/test_ai_enigma_gamble.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py tests/test_ai_mimic13.py -q`
Expected: 全部 PASS

Run: `python -c "import ast,io; ast.parse(io.open('katrain/core/ai.py', encoding='utf-8').read())"` → 無出力（構文 OK）
Run: `git diff --stat katrain/core/ai.py` → 削除は `Drop` ブロックの字下げ変更ぶん（約 8 行）と `probe_items` の 1 行だけ

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_enigma_overdraft.py
git commit -m "feat(enigma): 捨て身の罠を難解の選択フローに接続"
```

---

### Task 4: ユーザーローカル config（メインセッション直営）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（git 管理外）

- [ ] **Step 1: KaTrain が起動していないことを確認**

Run: `tasklist | grep -a -i "python\|katago"`
Expected: `katago.exe` が居ない（居たら KaTrain が起動中＝ユーザーに閉じてもらうまで書かない。起動中に書くと終了時に上書きされて消える）

- [ ] **Step 2: バックアップを取り、6 セクションに 4 キーを既定値で足す**

```python
# scratch: patch_local_config_overdraft.py
import json
import os
import shutil

path = os.path.expanduser("~/.katrain/config.json")
shutil.copyfile(path, path + ".bak-20260918-pre-overdraft")
conf = json.load(open(path, encoding="utf-8"))
before = json.dumps(conf, sort_keys=True)
ADD = {"overdraft_deficit": 0.0, "overdraft_answered_max": 0.0, "overdraft_min_fooled_lead": 2.0, "overdraft_probes": 6}
for p in ["enigma9", "enigma9plus", "enigma13", "enigma13plus", "enigma19", "enigma19plus"]:
    sec = conf["ai"][f"ai:{p}"]
    for sfx, v in ADD.items():
        sec.setdefault(f"{p}_{sfx}", v)
json.dump(conf, open(path, "w", encoding="utf-8"), indent=4, ensure_ascii=False)
after = json.load(open(path, encoding="utf-8"))
n = sum(1 for p in ["enigma9", "enigma9plus", "enigma13", "enigma13plus", "enigma19", "enigma19plus"]
        for sfx in ADD if f"{p}_{sfx}" in after["ai"][f"ai:{p}"])
assert n == 24, n
for p in ["enigma9", "enigma9plus", "enigma13", "enigma13plus", "enigma19", "enigma19plus"]:
    for sfx in ADD:
        del after["ai"][f"ai:{p}"][f"{p}_{sfx}"]
assert json.dumps(after, sort_keys=True) == before  # 他のキーは不変
print("ok: 24 keys")
```

実行前に既存ファイルの書式を確認する: `python -c "import io,os; s=io.open(os.path.expanduser('~/.katrain/config.json'),encoding='utf-8').read(); print(repr(s[:80]))"`。
字下げが 4 スペースでない・`ensure_ascii` が違う場合は `json.dump` の引数を既存の書式に合わせる（KaTrain は読み込み時に書式を気にしないが、差分を小さく保つ）。

---

### Task 5: ドキュメント

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（Enigma9 / Enigma13 / Enigma19 の表に 4 行ずつ＋難解＋の「他14項目」を「他18項目」に）
- Modify: `.claude/rules/ai-strategies.md`（序盤の賭け罠の段落の直後に 1 段落）
- Modify: `docs/manual/src/06f_ai_enigma.html`（params 表に 4 行）→ `python tools/build_manual.py`
- Modify: `docs/superpowers/specs/INDEX.md`（⛔ 未実装 → 🟢）
- Modify: `CLAUDE.md`（spec の本数 `全53本` → `全55本`）
- Modify: `C:\Users\iwaki\.claude\projects\C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1\memory\project_enigma_overdraft_trap.md` と `MEMORY.md` の該当行（「設計提示まで」→「2026-09-18 実装・既定 OFF・実戦校正は未実施」。メインセッションが Write/Edit で直接）

- [ ] **Step 1: パッチスクリプトで追記**（`patch` ヘルパー。`.claude/rules/` の Edit が拒否されることがあるのでスクリプト経由で書く）

`ai-parameters.md` の Enigma13 の表。アンカーは `| \`enigma13_gamble_min_delta_e\` | ` で始まる行（1 ヒット・行末まで正規表現で取って直後に挿入）:

```markdown
| `enigma13_overdraft_deficit` | **捨て身の罠（2026-09-18・spec `2026-09-18-enigma-overdraft-design.md`）の最大ビハインド D（目）**。ヨセ前 × 勝勢の消費モード（`cost_weight < 1`）の手番で、通常上限 cap の外側〜`over_cap = min(lead + D, ceiling)`（`ceiling = max(cap, 1.5 × large_lead_max_loss)`）の候補を生 loss の帯 `(cap − 1.5, over_cap + 1.5]` から `overdraft_probes` 手だけ追加プローブし（`enigma9_overdraft_probe_picks`＝trusted を loss 等間隔・足りなければ浅い候補を visits 順）、検証済み損失が cap を超えた候補（通常の shortlist 由来で上限超えだった手も破棄せず回す）のうち「`vloss <= ceiling`・`−D <= lead_after < min(target, overdraft_answered_max)`・`find_hp <= 0.25`・`lead_after + e_fooled >= overdraft_min_fooled_lead`」を全部満たす手があれば、net 比較・net_margin・局所性・難解＋の ΔE 床・**勝率フロア**を通さず `lead_after + E` 最大の手を打つ（`enigma9_overdraft_pick`）。`e_fooled`＝十分でない応手（損失 > 0.3）だけの humanSL 重みつき平均損失（`enigma9_fooled_punish`）。0 = OFF＝ビット同一。序盤の賭け罠（`cost_weight >= 1`）とは排他、擬態（13路）は対象外。**実測**（13路 18 局の反実仮想・消費モード 182 手番・12 プローブ・`calibration-data/enigma-overdraft/`）: 既定（必ずマイナス・下限 2 目）で 1.28 回/局、6 プローブ換算 **0.82 回/局・55% の局で 1 回以上**。リード 3.5 目以下の 126 手番は在庫 0（＝消費モードに限る根拠）。選ばれる手は中央値 vloss 8.4・応じられたら −0.48（勝率 41%・最悪 30%）・引っかかれば +3.3・**E − vloss −4.25＝期待値では毎回 3〜4 目の損＝演出用**。「引っかかれば現リードを維持」まで満たす手は 0.06〜0.33 回/局。プローブ前に罠を見分ける特徴は無く発動回数はプローブ数にほぼ比例。確認はログの `Overdraft: window` / `Over <gtp>:` / `Overdraft: played`。**実戦校正は未実施** | OFF/1/1.5/2/2.5/3/4/5 | **0（OFF）**・推奨 2.5 |
| `enigma13_overdraft_answered_max` | 応じられた後のリードの上限（目）。帯は `[−D, min(target, これ))`。0=必ずマイナスになる手だけ／−1=1 目以上の劣勢になる手だけ／MAX(99)=目標差未満＝穏やかな手も含む（6 プローブで 2.0 回/局〈下限 2 目〉・1.1 回/局〈下限 3 目〉） | −1/0/MAX | **0** |
| `enigma13_overdraft_min_fooled_lead` | 引っかかった場合に残るリードの下限 W（目）。必ずマイナス・6 プローブで W=2: 0.82 回/局 → W=3: 0.54 回/局 | 1/2/3/5/8 | **2.0** |
| `enigma13_overdraft_probes` | 追加プローブ数 k。必ずマイナス・W=2 で k=4/6/8/12 → 0.59/0.82/1.01/1.28 回/局。1 手あたりコールド約 +0.2 秒（対象は消費モードの手番＝約 10 手番/局・先読みでは温まらない） | 4/6/8/12 | **6** |
```

Enigma9 の表（アンカーは `| \`enigma9_gamble_min_delta_e\` | 同上 | 0.3/0.5/0.7/1.0/1.5 | **0.5** |` の行・直後に挿入）:

```markdown
| `enigma9_overdraft_deficit` | 13路と同じ機構（`enigma13_overdraft_*` 参照）。**未校正**（9路はログの代理集計でリード 8 目未満に大きい罠が 0%＝ほぼ発動しない見込み） | OFF/1/1.5/2/2.5/3/4/5 | **0（OFF）** |
| `enigma9_overdraft_answered_max` | 同上 | −1/0/MAX | **0** |
| `enigma9_overdraft_min_fooled_lead` | 同上 | 1/2/3/5/8 | **2.0** |
| `enigma9_overdraft_probes` | 同上 | 4/6/8/12 | **6** |
```

Enigma19 の表（アンカーは `| \`enigma19_gamble_min_delta_e\` | 同上 | 0.3/0.5/0.7/1.0/1.5 | **0.5** |` の行・直後に挿入）:

```markdown
| `enigma19_overdraft_deficit` | 13路と同じ機構（`enigma13_overdraft_*` 参照）。**未校正**（19路は未計測。probe 1 本が重いぶん追加プローブの時間の増分は 13路より大） | OFF/1/1.5/2/2.5/3/4/5 | **0（OFF）** |
| `enigma19_overdraft_answered_max` | 同上 | −1/0/MAX | **0** |
| `enigma19_overdraft_min_fooled_lead` | 同上 | 1/2/3/5/8 | **2.0** |
| `enigma19_overdraft_probes` | 同上 | 4/6/8/12 | **6** |
```

難解＋の表: `他14項目（` → `他18項目（`、`序盤の賭け罠 \`enigma*plus_gamble_*\` の 3 項目を含む` → `序盤の賭け罠 \`enigma*plus_gamble_*\` の 3 項目と捨て身の罠 \`enigma*plus_overdraft_*\` の 4 項目を含む`（各 1 ヒット）。

`ai-strategies.md`: `難解 / 難解＋（9/13/19路共通）には**序盤の賭け罠オプション**` で始まる段落の直後（空行を挟む）に 1 段落:

```markdown
難解 / 難解＋（9/13/19路共通）には**捨て身の罠オプション** `<prefix>_overdraft_deficit` / `_overdraft_answered_max` / `_overdraft_min_fooled_lead` / `_overdraft_probes` がある（2026-09-18・既定 OFF＝ビット同一・spec `2026-09-18-enigma-overdraft-design.md`）。ヨセ前 × 勝勢の消費モード（`cost_weight < 1`）の手番で、リードの予算（lead − target）を超えて払う罠＝「正しく応じられた後のリードが [−D, min(target, answered_max))・十分な応手の hp が 0.25 以下・引っかかった場合（十分でない応手の humanSL 重みつき平均 `enigma9_fooled_punish`）のリードが下限以上・1 手の損失は large_lead_max_loss の 1.5 倍まで」を、通常上限の外側から追加プローブで探し、資格があれば net 比較と勝率フロアを飛ばして `lead_after + E` 最大の手を打つ（`enigma9_overdraft_pick`）。序盤の賭け罠（`cost_weight >= 1`）とは排他。正しく応じられたら素直に劣勢になり、消費モードが切れて実質最善手で打つ＝「リスクを取って、応じられたら負ける」演出用のオプション。過去の2案（2026-09-03 の接戦での cap 緩和・賭け罠の文字どおり版）は在庫なしだったが、**勝勢の局面で予算の外まで払う本案は在庫がある**（13路 18 局の反実仮想: 必ずマイナス・下限 2 目・6 プローブで 0.82 回/局・55% の局で 1 回以上。リード 3.5 目以下は 126 手番で 0 件）。ただし**モデル自身の見積もりで毎回 3〜4 目の期待値の損**（E − vloss 中央値 −4.25）で、「引っかかれば現リードを維持」まで満たす手はほぼ無い。プローブ前に罠を見分ける特徴は無い＝発動回数はプローブ数に比例。**実戦校正は未実施**（9路はほぼ発動しない見込み・19路は未計測）。
```

`docs/manual/src/06f_ai_enigma.html`: `<tr><td>enigma*_gamble_min_delta_e</td>` の行の直後に 4 行:

```html
      <tr><td>enigma*_overdraft_deficit</td><td>OFF<span class="jp">未校正</span></td><td>OFF<span class="jp">推奨 2.5</span></td><td>OFF<span class="jp">未校正</span></td><td><b>捨て身の罠</b>の最大ビハインド（目）。ヨセ前・勝勢の消費モード中の手番で、リードの予算（リード − 目標差）を超えて払う罠を探す。「正しく応じられた後のリードが −この値 以上・正しい応手が 9 段の第一感に無い・引っかかればリードが下限以上残る」手があれば、難解さの比較と勝率フロアを飛ばしてその罠を打つ。1 手の損失は勝負手損失上限の 1.5 倍まで。正しく応じられたら素直に劣勢になり、そこからは実質最善手で打つ。13路の実測で約 0.8 回/局（55% の局で 1 回以上）。リード 3.5 目以下の局面には在庫が無い。<b>期待値では 1 回あたり 3〜4 目の損＝演出用</b>。9路はほぼ発動しない見込み。</td><td><span class="up">上げる</span>より深く沈む罠も打つ／<span class="down">OFF</span>従来どおり</td></tr>
      <tr><td>enigma*_overdraft_answered_max</td><td>0</td><td>0</td><td>0</td><td>正しく応じられた後のリードの上限（目）。0 = 必ずマイナスになる手だけ、−1 = 1 目以上の劣勢になる手だけ、MAX = 目標差未満＝応じられても少しプラスで済む穏やかな罠も含む。</td><td><span class="up">MAX</span>発動が約 2.4 倍に増える（穏やかな罠が中心）。<span class="down">−1</span>約 0.6 倍</td></tr>
      <tr><td>enigma*_overdraft_min_fooled_lead</td><td>2</td><td>2</td><td>2</td><td>相手が罠に引っかかった場合に残るリードの下限（目）。「引っかかった場合」は十分でない応手を 9 段の第一感で重みづけた平均。</td><td><span class="up">上げる</span>勝勢がはっきり残る罠だけ（3 で約 2/3）。<span class="down">下げる</span>頻繁に打つ</td></tr>
      <tr><td>enigma*_overdraft_probes</td><td>6</td><td>6</td><td>6</td><td>罠を探すために追加で検証する手数。罠は事前に見分けられないので、発動回数はほぼこの値に比例する（4/6/8/12 手で 0.6/0.8/1.0/1.3 回/局）。</td><td><span class="up">上げる</span>発動が増えるが、対象の手番で 1 手あたり約 +0.2 秒。<span class="down">下げる</span>速い</td></tr>
```

`INDEX.md`: `| \`2026-09-18-enigma-overdraft-design.md\` | ⛔ **未実装（設計のみ）** 難解` → `| \`2026-09-18-enigma-overdraft-design.md\` | 🟢 難解`、同じ行の末尾 `＝演出用 |` → `＝演出用・**実戦校正は未実施** |`（各 1 ヒット）。

`CLAUDE.md`: `に全53本。` → `に全55本。`（1 ヒット）。

- [ ] **Step 2: マニュアルを再ビルドして確認**

Run: `python tools/build_manual.py`
Run: `grep -c "enigma\*_overdraft_deficit" docs/manual/index.html` → `1`

- [ ] **Step 3: メモリを更新**（メインセッション）

`project_enigma_overdraft_trap.md` の description と本文冒頭を「2026-09-18 実装・既定 OFF・実戦校正は未実施」に直し、
設定キー 4 本と純関数名、`calibration-data/enigma-overdraft/` の場所を書く。`MEMORY.md` の該当行の「設計提示まで」も直す。

- [ ] **Step 4: コミット**

```bash
git add .claude/rules/ai-parameters.md .claude/rules/ai-strategies.md docs/manual docs/superpowers/specs/INDEX.md CLAUDE.md
git commit -m "docs(enigma): 捨て身の罠の rules・マニュアル・INDEX を更新"
```

---

### Task 6: 実局面での検証（KataGo あり）と回帰

**Files:**
- Modify: `docs/superpowers/specs/2026-09-18-enigma-overdraft-design.md`（§9「実局面での検証」を追記）
- Modify: `docs/superpowers/plans/2026-09-18-enigma-overdraft.md`（チェックボックスを完了に）

局面は `docs/superpowers/specs/calibration-data/enigma-overdraft/recon/` の復元 SGF（AI は黒／白は `games.json` の `ai`）。
`katrain_debug --move N` は N 手打った後の局面で次の手を選ぶ＝反実仮想の `d=N` と同じ局面。

- [ ] **Step 1: 資格があった局面を ON で 3 run ずつ**

```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma-overdraft/recon/game_20260918_004112.sgf --move 50 --strategy enigma13plus --settings enigma13plus_overdraft_deficit=2.5 enigma13plus_overdraft_probes=12 2>&1 | grep -a "Overdraft\|Over \|Spend:\|Deviate\|Best move wins\|着手決定"
```

```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma-overdraft/recon/game_20260917_233314.sgf --move 41 --strategy enigma13plus --settings enigma13plus_overdraft_deficit=2.5 enigma13plus_overdraft_probes=12 2>&1 | grep -a "Overdraft\|Over \|Spend:\|Deviate\|Best move wins\|着手決定"
```

Expected: `Spend:` → `Overdraft: window lead=… probes +N […]` → `Over <gtp>: …` が複数 → `Overdraft: band=[-2.5, 0.0) … qualifiers=[…]`。
反実仮想では 004112@50 は G10（応じられたら −1.96・引っかかれば +4.18）、233314@41 は D5（−2.29／+5.53）が資格ありだった。
プローブの標本（shortlist の除外・spread）と E・hp は run 間で揺れるので、3 run の資格の出入りと選択手をそのまま記録する
（資格の手がプローブに入らなかった run は `qualifiers=[]` のあと従来の選択になる＝正常）。

- [ ] **Step 2: OFF で従来どおり・消費モード外とヨセで発動しないことを 1 run ずつ**

```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma-overdraft/recon/game_20260918_004112.sgf --move 50 --strategy enigma13plus 2>&1 | grep -a -c "Overdraft\|Over "
```
Expected: `0`

```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma-overdraft/recon/game_20260918_004112.sgf --move 12 --strategy enigma13plus --settings enigma13plus_overdraft_deficit=2.5 2>&1 | grep -a -c "Overdraft\|Over "
```
Expected: `0`（リードが小さく消費モードでない。`Spend:` 行も出ない）

- [ ] **Step 3: 着手時間の増分を確認**

Step 1 の `着手決定に X 秒` と、同じ局面の OFF の秒数を並べる（コールド同士。目安は 12 プローブで +2〜2.5 秒・6 プローブで +1.2 秒）。

- [ ] **Step 4: 結果を spec §9 に追記してコミット**

spec の末尾に `## 9. 実局面での検証（2026-09-18・katrain_debug・ユーザーのローカル設定＋ overdraft_deficit=2.5）` を足し、
局面ごとに run 別の `qualifiers` と選択手・OFF の手・着手時間を表で書く（賭け罠 spec §9 と同じ体裁）。

```bash
git add docs/superpowers/specs/2026-09-18-enigma-overdraft-design.md
git commit -m "docs(enigma): 捨て身の罠の実局面検証を spec に追記"
```

- [ ] **Step 5: 回帰（KataGo と並走させない）**

Run: `python -m pytest tests/test_ai_enigma_overdraft.py tests/test_ai_enigma_gamble.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py tests/test_ai_mimic13.py tests/test_ai_options_grid.py tests/test_board_watch_prefetch.py -q`
Expected: 全部 PASS

- [ ] **Step 6: 計画を完了済みに更新してコミット**

このファイルのチェックボックスを `- [x]` にして

```bash
git add docs/superpowers/plans/2026-09-18-enigma-overdraft.md
git commit -m "docs(enigma): 捨て身の罠の実装計画を完了済みに更新"
```
