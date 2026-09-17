# 擬態（13路）戦略 ai:mimic13 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 13路専用の新戦略 `ai:mimic13`（擬態）を追加する。相手より低い AI 最善手一致率を保ったまま勝つ＝人間らしい非最善手か期待値プラスの罠へ、リード連動の支払い上限 λ の内側で外し、ヨセは HumanStyle 9段へ委譲する。

**Architecture:** `Mimic13Strategy(Enigma13Strategy)` が `_generate_move` を上書きし、基底のヘルパー（子局面プローブ・先読み・終局帯処理）を再利用する。判断は7本の純関数（`mimic_*`）に切り出してユニットテストする。基底 `Enigma9Strategy` の変更は終局帯ブロックの `_terminal_band_move` への機械的抽出だけ（挙動不変）。

**Tech Stack:** Python 3.12 / pytest（KataGo・Kivy 不要のスタブテスト）/ `katrain_debug`（KataGo 起動の単一局面確認）

**Spec:** `docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md`

## Global Constraints

- **既存の難解 6 戦略（enigma9/13/19・各 plus）は解析条件・採用判断ともビット同一**。基底の変更は Task 1 の抽出だけ。
- `price(c) = max(0, vloss(c)) − (E(c) − E(best))`。λ: `lead < -1.0 → 0` / `surplus <= 0 → free_loss` / `surplus > 0 → min(max_loss, max(free_loss, surplus × spend_rate))`（`surplus = lead − reserve`）。
- 資格: 自然 `hp >= max(min_human_policy, natural_ratio × hp_top)` または 罠 `ΔE >= trap_min_delta_e かつ hp >= 0.005`。支配ガード `hp(best) >= dominant_hp` は罠にも優先（最善手）。
- ハード条件: `vloss <= max_loss` かつ 着手後勝率 `>= min_winrate`（勝率 None は課さない）。
- 選択: 資格あり・`price <= λ` の price 最小、`cost_slack` 以内の帯は hp 最大。該当なしは最善手。
- ヨセ（手数 >= `endgame_move` AND 未確定点 <= `unsettled_max`・sticky `game._mimic13_endgame`）: `lead >= reserve` → `HumanStyleStrategy(game, {"human_kyu_rank": -8, "modern_style": True})` へ委譲、未満は最善手。
- 既定値（spec §4）: max_loss 2.0 / reserve 3.0 / spend_rate 0.25 / free_loss 0.3 / min_winrate 0.4 / dominant_hp 0.8 / min_human_policy 0.05 / natural_ratio 0.2 / trap_min_delta_e 0.5 / cost_slack 0.3 / probe_extra 4 / endgame_move 85 / unsettled_max 16。
- 全分岐のフェイルセーフは「KataGo 最善手」。
- **既存の `.py`（`katrain/core/ai.py`・`katrain/core/constants.py`・`katrain_debug/runner.py`）は CRLF かつ black 未整形。Edit/Write ツールで触らない**（PostToolUse フックが black で全体を再整形する）。**必ず下の `crlf_patch.py` 経由の python スクリプトで書き換える**。新規ファイル（`tests/test_ai_mimic13.py`）は Write でよい。`.json` / `.po` / `.md` / `.html` は Edit ツールでよい（フックは `.py` のみ）。
- コミット前に `git diff --stat` で**削除行数が想定どおりか**確認（再整形の混入検知）。
- コミットメッセージは日本語・Conventional Commits。末尾に `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。
- **ユーザー `C:\Users\iwaki\.katrain\config.json` はサブエージェントに委任せずメインセッションで直接 Edit**。編集前に KaTrain が起動していないことを確認。
- `.claude/rules/*.md` の Edit が拒否されたらサブエージェント経由で編集。
- テスト実行は `pytest <対象> -q`。KataGo と並走させない（時間閾値系の偽陽性）。

---

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `katrain/core/ai.py` | 純関数 `mimic_*`・`Mimic13Strategy`・基底の `_terminal_band_move` 抽出 | Modify（パッチスクリプト） |
| `katrain/core/constants.py` | `AI_MIMIC_13`・戦略リスト・`AI_OPTION_VALUES`/`AI_OPTION_ORDER` | Modify（パッチスクリプト） |
| `katrain/config.json` | パッケージ既定 `ai:mimic13` | Modify |
| `C:\Users\iwaki\.katrain\config.json` | ローカル設定（GUI 表示に必須） | Modify（メインセッション） |
| `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po` → `.mo` | 戦略名・ヘルプ・13 スライダーのラベル | Modify + compile |
| `katrain_debug/runner.py` | `--strategy mimic13` | Modify（パッチスクリプト） |
| `tests/test_ai_mimic13.py` | 純関数・登録整合・`_generate_move` 通し | Create |
| `.claude/rules/ai-strategies.md` / `ai-parameters.md` / `CLAUDE.md` | 設計要約・パラメータ表・クラス一覧 | Modify |
| `docs/manual/src/06_ai_overview.html` / `06d_ai_parity.html` → `index.html` | 利用者向け説明 | Modify + build |
| `docs/superpowers/specs/INDEX.md`・spec | 状態を 🟢 に | Modify |

パッチ用ヘルパー（**リポジトリには入れない**。スクラッチパッドに置く）:

`<scratchpad>/crlf_patch.py`

```python
"""CRLF を保ったままテキスト置換する（katrain の既存 .py は CRLF・black 未整形）。"""
import sys


def patch(path, edits):
    """edits: [(old, new, expected_count)]。old/new は LF で書く。件数が合わなければ何も書かずに止まる。"""
    raw = open(path, "rb").read()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    for old, new, count in edits:
        found = text.count(old)
        if found != count:
            sys.exit(f"{path}: expected {count} occurrence(s), found {found}: {old[:70]!r}")
        text = text.replace(old, new)
    if crlf:
        text = text.replace("\n", "\r\n")
    open(path, "wb").write(text.encode("utf-8"))
    print(f"patched {path} ({'CRLF' if crlf else 'LF'}, {len(edits)} edit(s))")
```

`<scratchpad>` = `C:\Users\iwaki\AppData\Local\Temp\claude\c--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1\148cf9e3-497e-4f35-b4f0-b85ab7226825\scratchpad`（別セッションならそのセッションのスクラッチパッド）。各タスクのパッチスクリプトは同じディレクトリに Write し、リポジトリのルートを cwd にして `python <scratchpad>/<script>.py` で実行する。

---

### Task 0: ブランチと spec のコミット

**Files:**
- Create: `<scratchpad>/crlf_patch.py`（上記）
- Commit: `docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md`, `docs/superpowers/specs/INDEX.md`, `docs/superpowers/plans/2026-09-17-mimic13-strategy.md`

- [ ] **Step 1: 作業ブランチを切る**

```bash
git checkout -b feature/mimic13-strategy
```

- [ ] **Step 2: `crlf_patch.py` をスクラッチパッドに Write**（内容は File Structure 節のとおり）

- [ ] **Step 3: spec・plan をコミット**

```bash
git add docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md docs/superpowers/specs/INDEX.md docs/superpowers/plans/2026-09-17-mimic13-strategy.md
git commit -m "docs(mimic13): 擬態（13路）戦略の設計と実装計画

相手より低い AI 最善手一致率で勝つ 13路専用戦略。price = vloss − ΔE を
リード連動の λ で買い、資格は自然さ（humanPolicy）か罠（ΔE）、ヨセは 9段委譲。
13路難解ログ 18 局の在庫実測つき。

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 1: 基底の終局帯ブロックを `_terminal_band_move` に抽出（挙動不変）

**Files:**
- Modify: `katrain/core/ai.py`（`Enigma9Strategy._generate_move` のゲート1b、約 3220-3300 行）
- Test: `tests/test_ai_mimic13.py`（新規・このタスクでは抽出の存在確認だけ）

**Interfaces:**
- Produces: `Enigma9Strategy._terminal_band_move(self, cands, player) -> Optional[Tuple[Move, str]]`
  （終局帯に該当すれば着手と理由、該当しなければ `None`。`cands` は `self.cn.candidate_moves`、`player` は `"B"`/`"W"`）

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_ai_mimic13.py` を Write

```python
# tests/test_ai_mimic13.py
"""「擬態（13路）」ai:mimic13 の純関数・登録整合・_generate_move 通しテスト（KataGo/Kivy 不要）。

設計: docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md
"""
import types

import pytest

from katrain.core.ai import Enigma9Strategy


def _node(**kw):
    base = dict(next_player="B", player="W", depth=30, move=None, analysis_complete=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


class TestTerminalBandExtraction:
    """基底の終局帯ブロックはメソッドに抽出されている（擬態13路と共有するため）。"""

    def test_returns_none_outside_the_terminal_band(self):
        katrain_ns = types.SimpleNamespace(log=lambda *a, **k: None)
        cands = [
            {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.6},
            {"move": "pass", "pointsLost": 30.0, "relativePointsLost": 30.0, "visits": 5, "winrate": 0.1},
        ]
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=_node(candidate_moves=cands), board_size=(9, 9))
        s = Enigma9Strategy(game, {})
        assert s._terminal_band_move(cands, "B") is None

    def test_opponent_pass_with_cheap_pass_returns_a_pass(self):
        from katrain.core.sgf_parser import Move

        katrain_ns = types.SimpleNamespace(log=lambda *a, **k: None)
        cands = [
            {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.6},
            {"move": "pass", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 50, "winrate": 0.6},
        ]
        node = _node(candidate_moves=cands, move=Move(None, player="W"))
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(9, 9))
        s = Enigma9Strategy(game, {})
        move, reason = s._terminal_band_move(cands, "B")
        assert move.is_pass
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_mimic13.py -q`
Expected: FAIL（`AttributeError: 'Enigma9Strategy' object has no attribute '_terminal_band_move'`）

- [ ] **Step 3: 抽出パッチ** — `<scratchpad>/patch_task1.py` を Write して実行

```python
"""Enigma9Strategy._generate_move の終局帯ブロック（ゲート1b）を _terminal_band_move に抽出する。"""
import sys

PATH = "katrain/core/ai.py"

raw = open(PATH, "rb").read()
crlf = b"\r\n" in raw
lines = raw.decode("utf-8").replace("\r\n", "\n").split("\n")

starts = [i for i, l in enumerate(lines) if "# ---- ゲート1b: 終局帯" in l]
ends = [i for i, l in enumerate(lines) if 'game is nearly over, playing best move (no deviation).")' in l]
heads = [
    i for i, l in enumerate(lines)
    if l == "    def generate_move(self) -> Tuple[Move, str]:" and "per-move 時間の常時ログ" in lines[i + 1]
]
if not (len(starts) == len(ends) == len(heads) == 1 and heads[0] < starts[0] < ends[0]):
    sys.exit(f"anchors not unique/ordered: starts={starts} ends={ends} heads={heads}")
start, end, head = starts[0], ends[0], heads[0]
block = lines[start : end + 1]
# ブロックが使う外側の名前は cands / player / self だけ（実測済み）。best_gtp を使っていたら抽出できない
# （"opponent passed" というログ文字列は含まれるので opponent では検査しない）
if "best_gtp" in "\n".join(block):
    sys.exit("block references best_gtp, which is not a parameter of the new method")

method = (
    [
        "    def _terminal_band_move(self, cands, player):",
        '        """終局帯（ゲート1b）の処理。該当すれば (Move, 理由)、しなければ None（通常の選択へ進む）。',
        "",
        "        `_generate_move` から機械的に抽出した（挙動不変）。擬態（13路）`Mimic13Strategy` と共有する。",
        '        """',
    ]
    + block
    + ["        return None", ""]
)
call = [
    "        # ---- ゲート1b: 終局帯（`_terminal_band_move`・擬態13路と共有）----",
    "        terminal = self._terminal_band_move(cands, player)",
    "        if terminal is not None:",
    "            return terminal",
]
lines[start : end + 1] = call          # 後ろ側を先に置換（head < start なので head の添字は不変）
lines[head:head] = method
text = "\n".join(lines)
if crlf:
    text = text.replace("\n", "\r\n")
open(PATH, "wb").write(text.encode("utf-8"))
print(f"extracted {len(block)} lines into _terminal_band_move ({'CRLF' if crlf else 'LF'})")
```

Run: `python <scratchpad>/patch_task1.py`
Expected: `extracted 81 lines into _terminal_band_move (CRLF)`（行数は前後してよい）

- [ ] **Step 4: 新規テストと既存の終局帯回帰を確認**

Run: `pytest tests/test_ai_mimic13.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py -q`
Expected: 全 PASS（`TestTerminalHelpers` / `TestTerminalEndToEnd` を含む）

- [ ] **Step 5: 差分が移動だけであることを確認してコミット**

Run: `git diff --stat katrain/core/ai.py`
Expected: `ai.py` の追加と削除がほぼ同数（ブロック約 81 行の移動＋メソッド見出し約 10 行）。数百行規模の差分なら再整形が混入している＝`git checkout katrain/core/ai.py` でやり直す。

```bash
git add katrain/core/ai.py tests/test_ai_mimic13.py
git commit -m "refactor(enigma): 終局帯ブロックを _terminal_band_move に抽出（挙動不変）

擬態（13路）戦略と終局処理を共有するための機械的な抽出。

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 純関数 `mimic_*`

**Files:**
- Modify: `katrain/core/ai.py`（`@register_strategy(AI_SCORELOSS)` の直前に挿入）
- Test: `tests/test_ai_mimic13.py`

**Interfaces:**
- Consumes: `enigma9_shortlist_spread(pool, base_k, extra)`（既存）
- Produces（すべて `katrain.core.ai`）:
  - `MIMIC_BEHIND_LIMIT = -1.0` / `MIMIC_TRAP_MIN_HP = 0.005` / `MIMIC_SHORTLIST_NATURAL = 4` / `MIMIC_SHORTLIST_CHEAP = 4`
  - `mimic_price_cap(lead, reserve, spend_rate, free_loss, max_loss, behind_limit=MIMIC_BEHIND_LIMIT) -> Optional[float]`
  - `mimic_hp_top(human_policy, board_size) -> float`
  - `mimic_natural_floor(hp_top, min_hp, ratio) -> float`
  - `mimic_shortlist(pool, hp_of, floor, k_natural=4, k_cheap=4, extra=0) -> List[dict]`（`pool` は `{"gtp","loss","visits","wr"}`）
  - `mimic_qualifies(hp, delta_e, floor, trap_min_delta_e, trap_min_hp=MIMIC_TRAP_MIN_HP) -> Optional[str]`（`"natural"` / `"trap"` / `None`）
  - `mimic_choose(scored, best_gtp, lam, slack) -> Optional[dict]`（`scored` は `{"gtp","price","own_hp","kind"}` を含む dict）
  - `mimic_yose_delegates(lead, reserve) -> bool`

- [ ] **Step 1: 失敗するテストを追記** — `tests/test_ai_mimic13.py` の import を差し替え、末尾にクラスを追記（Edit ツールでよい＝新規ファイルなので black 整形は無害）

import ブロックを次に置き換える:

```python
import types

import pytest

from katrain.core.ai import (
    MIMIC_BEHIND_LIMIT,
    MIMIC_TRAP_MIN_HP,
    Enigma9Strategy,
    mimic_choose,
    mimic_hp_top,
    mimic_natural_floor,
    mimic_price_cap,
    mimic_qualifies,
    mimic_shortlist,
    mimic_yose_delegates,
)
```

末尾に追記:

```python
def cand(gtp, loss, visits=100, wr=0.5):
    return {"gtp": gtp, "loss": loss, "visits": visits, "wr": wr}


def scored(gtp, price, hp, kind="natural"):
    return {"gtp": gtp, "price": price, "own_hp": hp, "kind": kind}


class TestPriceCap:
    """λ = 不一致1回に払ってよい price の上限（リード連動）。"""

    def test_none_when_lead_unknown(self):
        assert mimic_price_cap(None, 3.0, 0.25, 0.3, 2.0) is None

    def test_behind_pays_nothing(self):
        assert mimic_price_cap(MIMIC_BEHIND_LIMIT - 0.01, 3.0, 0.25, 0.3, 2.0) == 0.0

    def test_no_surplus_pays_only_free_loss(self):
        assert mimic_price_cap(-1.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(0.3)  # 境界は free 側
        assert mimic_price_cap(0.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(0.3)
        assert mimic_price_cap(3.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(0.3)

    def test_surplus_is_spent_at_the_spend_rate(self):
        assert mimic_price_cap(7.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(1.0)   # 余剰 4 目 × 0.25
        assert mimic_price_cap(3.4, 3.0, 0.25, 0.3, 2.0) == pytest.approx(0.3)   # 余剰が薄い間は free が床

    def test_capped_by_max_loss(self):
        assert mimic_price_cap(40.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(2.0)
        assert mimic_price_cap(0.0, 3.0, 0.25, 0.5, 0.2) == pytest.approx(0.2)   # max_loss < free_loss でも超えない

    def test_is_continuous_and_monotonic_in_lead(self):
        leads = [x / 10.0 for x in range(-10, 200)]
        caps = [mimic_price_cap(l, 3.0, 0.25, 0.3, 2.0) for l in leads]
        assert all(b >= a for a, b in zip(caps, caps[1:]))
        assert max(b - a for a, b in zip(caps, caps[1:])) <= 0.025 + 1e-9         # 0.1 目刻みで段差なし


class TestNaturalFloor:
    def test_hp_top_ignores_pass_and_illegal_points(self):
        policy = [0.1, -1.0, 0.4, 0.2] + [0.0] * 165 + [0.9]   # 13路: 169 点 + pass
        assert mimic_hp_top(policy, (13, 13)) == pytest.approx(0.4)

    def test_hp_top_of_empty_or_illegal_board_is_zero(self):
        assert mimic_hp_top([-1.0] * 169 + [1.0], (13, 13)) == 0.0

    def test_floor_is_the_larger_of_absolute_and_relative(self):
        assert mimic_natural_floor(0.9, 0.05, 0.2) == pytest.approx(0.18)   # 第一感が強い局面は相対側
        assert mimic_natural_floor(0.1, 0.05, 0.2) == pytest.approx(0.05)   # 分散した局面は絶対側


class TestQualifies:
    def test_natural_by_human_policy(self):
        assert mimic_qualifies(0.10, 0.0, 0.05, 0.5) == "natural"

    def test_trap_is_exempt_from_naturalness_but_not_from_the_hard_floor(self):
        assert mimic_qualifies(0.01, 0.8, 0.05, 0.5) == "trap"
        assert mimic_qualifies(MIMIC_TRAP_MIN_HP / 2, 3.0, 0.05, 0.5) is None   # 人間が絶対打たない手は罠でも不可

    def test_neither(self):
        assert mimic_qualifies(0.01, 0.4, 0.05, 0.5) is None

    def test_trap_off_sentinel(self):
        assert mimic_qualifies(0.01, 5.0, 0.05, 99.0) is None


class TestShortlist:
    def test_naturals_first_by_hp_then_cheapest_then_spread(self):
        hp = {"A1": 0.30, "B2": 0.20, "C3": 0.01, "D4": 0.01, "E5": 0.01, "F6": 0.01, "G7": 0.01}
        pool = [cand("C3", 0.1), cand("A1", 1.5), cand("D4", 0.2), cand("B2", 0.9),
                cand("E5", 0.6), cand("F6", 1.2), cand("G7", 1.9)]
        out = mimic_shortlist(pool, lambda g: hp[g], 0.05, k_natural=2, k_cheap=2, extra=2)
        gtps = [c["gtp"] for c in out]
        assert gtps[:2] == ["A1", "B2"]            # 自然な候補は hp 降順（高くても拾う）
        assert gtps[2:4] == ["C3", "D4"]           # 残りから安い順
        assert set(gtps[4:]) == {"E5", "G7"}       # 残りの loss 範囲を端まで等間隔
        assert len(gtps) == len(set(gtps))

    def test_no_naturals_falls_back_to_cheapest(self):
        pool = [cand("A1", 0.4), cand("B2", 0.1)]
        out = mimic_shortlist(pool, lambda g: 0.0, 0.05, k_natural=4, k_cheap=4, extra=0)
        assert [c["gtp"] for c in out] == ["B2", "A1"]


class TestChoose:
    def test_none_when_nothing_is_affordable(self):
        assert mimic_choose([scored("A1", 0.5, 0.3)], "E5", 0.3, 0.3) is None

    def test_unqualified_and_best_are_never_chosen(self):
        rows = [scored("E5", 0.0, 0.9), scored("A1", 0.1, 0.3, kind=None)]
        assert mimic_choose(rows, "E5", 1.0, 0.3) is None

    def test_cheapest_price_wins_outside_the_band(self):
        rows = [scored("A1", 0.9, 0.5), scored("B2", 0.1, 0.06)]
        assert mimic_choose(rows, "E5", 1.0, 0.3)["gtp"] == "B2"

    def test_band_prefers_the_most_human_move(self):
        rows = [scored("A1", 0.30, 0.5), scored("B2", 0.10, 0.06)]
        assert mimic_choose(rows, "E5", 1.0, 0.3)["gtp"] == "A1"

    def test_profitable_trap_is_affordable_with_zero_lambda(self):
        rows = [scored("T1", -0.7, 0.01, kind="trap"), scored("A1", 0.2, 0.4)]
        assert mimic_choose(rows, "E5", 0.0, 0.3)["gtp"] == "T1"

    def test_band_never_admits_a_price_above_lambda(self):
        rows = [scored("A1", 0.25, 0.1), scored("B2", 0.45, 0.9)]
        assert mimic_choose(rows, "E5", 0.3, 0.3)["gtp"] == "A1"


class TestYoseDelegates:
    def test_delegates_only_with_the_reserve_in_hand(self):
        assert mimic_yose_delegates(3.0, 3.0) is True
        assert mimic_yose_delegates(2.99, 3.0) is False
        assert mimic_yose_delegates(None, 3.0) is False
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_mimic13.py -q`
Expected: FAIL（`ImportError: cannot import name 'MIMIC_BEHIND_LIMIT'`）

- [ ] **Step 3: 純関数を挿入** — `<scratchpad>/patch_task2.py` を Write して実行

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

ANCHOR = "@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

CODE = '''# ===== 「擬態」戦略 ai:mimic13（13路）の純関数群 =====
# 設計: docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md
#
# 目的は「相手より低い AI 最善手一致率を保ったまま勝つ」。不一致1回の値段を
#   price(c) = max(0, vloss(c)) - (E(c) - E(best))
# （検証済み損失 − 相手の期待損失の上積み。難解の net から rarity 項を外したものと同値）で測り、
# リード連動の支払い上限 λ（mimic_price_cap）の内側で、人間らしい手（humanPolicy）か罠（ΔE）の
# 資格を持つ最安の手へ外す。プローブ条件・E の定義は難解（ENIGMA9_* / enigma9_*）を共有する。

MIMIC_BEHIND_LIMIT = -1.0      # lead がこれ未満なら λ=0（期待値プラスの手だけ）。13路 komi 込みの黒の開始時 lead は僅かに負なので 0 にしない
MIMIC_TRAP_MIN_HP = 0.005      # 罠でも要求する humanPolicy 下限（NN 下限に張り付いた手を除く・jigo の MIN_HP_HARD_FLOOR と同値）
MIMIC_SHORTLIST_NATURAL = 4    # 子局面プローブに回す「自然な候補」（hp 降順）
MIMIC_SHORTLIST_CHEAP = 4      # 同「安い順」（これに probe_extra 手の spread が足される）


def mimic_price_cap(lead, reserve, spend_rate, free_loss, max_loss, behind_limit=MIMIC_BEHIND_LIMIT):
    """不一致1回に払ってよい price の上限 λ（目）。lead が取れなければ None（呼び出し側は最善手）。

    lead は打つ側視点の目差。surplus = lead - reserve が「ヨセを 9段に任せても勝ち切るための
    確保リード」を超えた余剰で、1手に払うのはその spend_rate 倍まで（天井 max_loss）。余剰が無くても
    free_loss（タダ同然）までは払う。lead < behind_limit では 0＝price <= 0（期待値プラスの罠）しか通らない。
    """
    if lead is None:
        return None
    if lead < behind_limit:
        return 0.0
    surplus = lead - reserve
    if surplus <= 0:
        return min(free_loss, max_loss)
    return min(max_loss, max(free_loss, surplus * spend_rate))


def mimic_hp_top(human_policy, board_size):
    """盤上全点の humanPolicy 最大値（pass 除く・非合法点の -1 は 0 扱い）。"""
    bx, by = board_size
    return max([0.0] + [v for v in human_policy[: bx * by] if v is not None])


def mimic_natural_floor(hp_top, min_hp, ratio):
    """「人間らしい外し」に要求する humanPolicy 下限＝絶対値 min_hp と第一感トップ比 ratio の大きいほう。

    第一感が1点に集中した局面（hp_top 0.9）では相対側 0.18 が効いて代替手が消え、分散した局面
    （hp_top 0.1）では絶対側が効く＝「有力候補が1つしかないのに外す」を構造的に防ぐ。
    """
    return max(min_hp, ratio * max(0.0, hp_top))


def mimic_shortlist(pool, hp_of, floor, k_natural=MIMIC_SHORTLIST_NATURAL, k_cheap=MIMIC_SHORTLIST_CHEAP, extra=0):
    """子局面プローブに回す挑戦者: 自然な候補を hp 降順に k_natural 手 ＋ 残りから安い順 k_cheap 手 ＋ spread extra 手。

    難解の shortlist は「安い順」だけなので、9段の第一感だが 1 目前後損な手が漏れる。擬態の主役は
    その手なので hp 上位を先に確保し、残り枠は難解＋と同じ規則（`enigma9_shortlist_spread`）で罠を探す。
    pool は `enigma9_admissible` の出力（{"gtp","loss","visits","wr"}）。
    """
    naturals = sorted(
        [c for c in pool if hp_of(c["gtp"]) >= floor],
        key=lambda c: (-hp_of(c["gtp"]), c["loss"]),
    )[: max(0, int(k_natural))]
    taken = {c["gtp"] for c in naturals}
    rest = [c for c in pool if c["gtp"] not in taken]
    return naturals + enigma9_shortlist_spread(rest, int(k_cheap), int(extra))


def mimic_qualifies(hp, delta_e, floor, trap_min_delta_e, trap_min_hp=MIMIC_TRAP_MIN_HP):
    """外し候補の資格: "natural"（人間らしい）/ "trap"（相手を騙す手＝人間らしさ免除）/ None。"""
    if hp >= floor:
        return "natural"
    if delta_e >= trap_min_delta_e and hp >= trap_min_hp:
        return "trap"
    return None


def mimic_choose(scored, best_gtp, lam, slack):
    """資格あり・price <= λ の非最善手から price 最小を選ぶ。最小から slack 以内の帯は humanPolicy 最大。

    scored: [{"gtp","price","own_hp","kind", ...}]。該当なしは None（呼び出し側は最善手）。
    帯の全員が price <= λ を満たす（帯は eligible の部分集合）ので、人間らしさのために λ を超えて払うことはない。
    """
    eligible = [c for c in scored if c["gtp"] != best_gtp and c.get("kind") and c["price"] <= lam]
    if not eligible:
        return None
    cheapest = min(c["price"] for c in eligible)
    band = [c for c in eligible if c["price"] <= cheapest + slack]
    return max(band, key=lambda c: (c["own_hp"], -c["price"]))


def mimic_yose_delegates(lead, reserve):
    """ヨセを HumanStyle 9段へ任せてよいか（確保リードを持っている手番だけ。未満は最善手で勝ちを守る）。"""
    return lead is not None and lead >= reserve


'''

patch("katrain/core/ai.py", [(ANCHOR, CODE + ANCHOR, 1)])
```

Run: `python <scratchpad>/patch_task2.py`
Expected: `patched katrain/core/ai.py (CRLF, 1 edit(s))`

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_ai_mimic13.py -q`
Expected: 全 PASS

- [ ] **Step 5: コミット**

Run: `git diff --stat katrain/core/ai.py`（追加のみ・削除 0 行であること）

```bash
git add katrain/core/ai.py tests/test_ai_mimic13.py
git commit -m "feat(mimic13): 擬態戦略の純関数（λ・自然さの床・shortlist・資格・選択・ヨセ安全弁）

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `Mimic13Strategy`（選択フロー）と登録

**Files:**
- Modify: `katrain/core/constants.py`（`AI_MIMIC_13` 定数の定義だけ。GUI 一覧への登録は Task 4）
- Modify: `katrain/core/ai.py`（import・クラス）
- Test: `tests/test_ai_mimic13.py`

**Interfaces:**
- Consumes: Task 1 の `_terminal_band_move`、Task 2 の `mimic_*`、既存 `parity9_build_candidates` / `parity9_is_endgame` / `parity9_match_tally` / `enigma9_admissible` / `enigma9_hp_lookup` / `enigma9_verified_metrics` / `enigma9_reply_table` / `enigma9_expected_punish` / `HumanStyleStrategy` / `Enigma13Strategy` のヘルパー（`_run_query(label, **kwargs)` / `_probe_children(gtps, player, parent_hp=False)` / `_best_move(reason)` / `_cancel_ponder()` / `_start_ponder(gtp, probe, player)` / `_setting(suffix)` / `_log(msg)`）
- Produces: `katrain.core.constants.AI_MIMIC_13 = "ai:mimic13"`、`katrain.core.ai.Mimic13Strategy`（`KEY_PREFIX="mimic13"`・`LABEL="Mimic13"`・`SETTING_DEFAULTS` 13 項目・sticky フラグ `game._mimic13_endgame`）

- [ ] **Step 1: 失敗するテストを追記** — import に `Enigma13Strategy, Mimic13Strategy` と `import katrain.core.ai as ai_module`、`from katrain.core.sgf_parser import Move` を足し、末尾に追記

```python
def _hp_array(size, values):
    """{gtp: hp} → KataGo の humanPolicy フラット配列（末尾 pass）"""
    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        if gtp == "pass":
            arr[-1] = v
            continue
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def _child(lead_black, replies, reply_hp):
    """子局面プローブの疑似レスポンス。replies: [(gtp, scoreLead 黒視点, visits)]・reply_hp: {gtp: hp}"""
    clean = {
        "rootInfo": {"scoreLead": lead_black, "winrate": 0.6},
        "moveInfos": [{"move": g, "scoreLead": s, "visits": v} for g, s, v in replies],
    }
    return {"clean": clean, "hp": {"humanPolicy": _hp_array(13, reply_hp)}}


class TestStrategyClass:
    def test_registered_as_a_13x13_enigma_subclass(self):
        from katrain.core.ai import STRATEGY_REGISTRY
        from katrain.core.constants import AI_MIMIC_13

        assert AI_MIMIC_13 == "ai:mimic13"
        assert STRATEGY_REGISTRY[AI_MIMIC_13] is Mimic13Strategy
        assert issubclass(Mimic13Strategy, Enigma13Strategy)
        assert (Mimic13Strategy.BOARD_LEN, Mimic13Strategy.KEY_PREFIX, Mimic13Strategy.LABEL) == (13, "mimic13", "Mimic13")

    def test_defaults_match_the_spec(self):
        assert Mimic13Strategy.SETTING_DEFAULTS == {
            "max_loss": 2.0, "reserve": 3.0, "spend_rate": 0.25, "free_loss": 0.3, "min_winrate": 0.4,
            "dominant_hp": 0.8, "min_human_policy": 0.05, "natural_ratio": 0.2, "trap_min_delta_e": 0.5,
            "cost_slack": 0.3, "probe_extra": 4, "endgame_move": 85, "unsettled_max": 16,
        }

    def test_base_flow_is_untouched(self):
        assert Enigma13Strategy._generate_move is not Mimic13Strategy._generate_move
        assert Mimic13Strategy.generate_move is Enigma13Strategy.generate_move   # 時間ログのラッパーは共有


class _Harness:
    """_generate_move の通しテスト用スタブ（エンジンなし）。黒番・13路・最善手 G7。
    名前が Test で始まらないので pytest には収集されない（継承した側だけが走る）。"""

    CANDS = [
        {"move": "G7", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.62},
        {"move": "D4", "pointsLost": 0.4, "relativePointsLost": 0.4, "visits": 200, "winrate": 0.60},
        {"move": "K10", "pointsLost": 1.2, "relativePointsLost": 1.2, "visits": 40, "winrate": 0.57},
        {"move": "A1", "pointsLost": 9.0, "relativePointsLost": 9.0, "visits": 3, "winrate": 0.2},
    ]

    def _strategy(self, *, lead=8.0, depth=30, hp=None, probes=None, settings=None, ownership=None, **game_attrs):
        logs = []
        katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
        node = types.SimpleNamespace(
            next_player="B", player="W", depth=depth, move=None, analysis_complete=True,
            analysis={"root": {"scoreLead": lead}}, candidate_moves=[dict(c) for c in self.CANDS],
            nodes_from_root=[],
        )
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(13, 13), **game_attrs)
        s = Mimic13Strategy(game, settings or {})
        s.queries, s.probe_calls = [], []

        def run_query(label, **kw):
            s.queries.append(label)
            if label == "HumanSL":
                return None if hp is None else {"humanPolicy": hp}
            return None if ownership is None else {"ownership": ownership, "rootInfo": {"scoreLead": lead}}

        def probe_children(gtps, player, parent_hp=False):
            s.probe_calls.append(list(gtps))
            return {g: (probes or {}).get(g) for g in gtps}, None

        s._run_query = run_query
        s._probe_children = probe_children
        s._start_ponder = lambda *a, **k: None
        return s, logs

    # 応手テーブル: 白の応手 C11（本命）/ L3。scoreLead は黒視点（白は小さいほど良い）
    def _probes(self, d4_lead=7.8, d4_punish=0.0, k10_lead=7.0, k10_punish=0.0):
        hp = {"C11": 0.5, "L3": 0.5}
        return {
            "G7": _child(8.0, [("C11", 8.0, 300), ("L3", 8.0, 200)], hp),
            "D4": _child(d4_lead, [("C11", d4_lead, 300), ("L3", d4_lead + 2 * d4_punish, 200)], hp),
            "K10": _child(k10_lead, [("C11", k10_lead, 300), ("L3", k10_lead + 2 * k10_punish, 200)], hp),
        }


class TestGenerateMove(_Harness):
    def test_dominant_first_instinct_plays_the_best_move_without_probes(self):
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.91, "D4": 0.05}), probes=self._probes())
        move, _ = s.generate_move()
        assert move.gtp() == "G7"
        assert s.queries == ["HumanSL"] and s.probe_calls == []
        assert any("Dominant" in m for m in logs)

    def test_natural_cheap_deviation_is_bought_with_surplus(self):
        # lead 8・reserve 3 → λ=1.25。D4 は hp 0.30（自然）・vloss 0.2・ΔE 0 → price 0.2
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.40, "D4": 0.30, "K10": 0.02}), probes=self._probes())
        move, reason = s.generate_move()
        assert move.gtp() == "D4"
        assert any("Deviate" in m and "natural" in m for m in logs)

    def test_unnatural_move_without_trap_value_is_not_played(self):
        # D4 の hp を床未満に。K10 も hp 0.02・ΔE 0 → 資格者なし
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.60, "D4": 0.02, "K10": 0.02}), probes=self._probes())
        move, _ = s.generate_move()
        assert move.gtp() == "G7"

    def test_trap_is_played_even_when_behind_if_it_pays_for_itself(self):
        # lead -2 → λ=0。K10 は hp 0.02（不自然）だが vloss 1.0・ΔE 1.5（L3 が 3 目損・hp 0.5）→ price -0.5
        probes = self._probes(k10_lead=7.0, k10_punish=1.5)
        s, logs = self._strategy(
            lead=-2.0, hp=_hp_array(13, {"G7": 0.60, "D4": 0.02, "K10": 0.02}), probes=probes,
            settings={"mimic13_min_winrate": 0.3},
        )
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert any("trap" in m for m in logs)

    def test_price_above_lambda_keeps_the_best_move(self):
        # lead 3（余剰 0）→ λ=0.3。D4 は自然だが vloss 0.8
        s, logs = self._strategy(
            lead=3.0, hp=_hp_array(13, {"G7": 0.40, "D4": 0.30}), probes=self._probes(d4_lead=7.2)
        )
        move, _ = s.generate_move()
        assert move.gtp() == "G7"

    def test_verified_loss_above_max_loss_is_dropped(self):
        s, logs = self._strategy(
            lead=30.0, hp=_hp_array(13, {"G7": 0.40, "D4": 0.30}), probes=self._probes(d4_lead=5.5)
        )
        move, _ = s.generate_move()
        assert move.gtp() == "G7"
        assert any("Drop D4" in m for m in logs)

    def test_humansl_failure_is_failsafe(self):
        s, logs = self._strategy(hp=None, probes=self._probes())
        move, _ = s.generate_move()
        assert move.gtp() == "G7" and s.probe_calls == []

    def test_wrong_board_size_is_failsafe(self):
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.4, "D4": 0.3}), probes=self._probes())
        s.game.board_size = (9, 9)
        move, _ = s.generate_move()
        assert move.gtp() == "G7" and s.queries == []

    def test_missing_lead_is_failsafe(self):
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.4, "D4": 0.3}), probes=self._probes())
        s.cn.analysis = {}
        move, _ = s.generate_move()
        assert move.gtp() == "G7" and s.queries == []


class _FakeHumanStyle:
    calls = []

    def __init__(self, game, settings):
        type(self).calls.append(settings)
        self.game = game

    def generate_move(self):
        return Move.from_gtp("D4", player="B"), "fake 9d"


class TestYose(_Harness):
    def test_enters_yose_by_moves_and_unsettled_points_then_delegates(self, monkeypatch):
        monkeypatch.setattr(ai_module, "HumanStyleStrategy", _FakeHumanStyle)
        _FakeHumanStyle.calls = []
        s, logs = self._strategy(depth=90, lead=6.0, ownership=[0.95] * 160 + [0.1] * 9)
        move, reason = s.generate_move()
        assert s.queries == ["Probe"]                       # ヨセ突入の判定に ownership を1本
        assert s.game._mimic13_endgame is True               # sticky
        assert move.gtp() == "D4" and reason.startswith("[Mimic13→9d yose]")
        assert _FakeHumanStyle.calls == [{"human_kyu_rank": -8, "modern_style": True}]

    def test_sticky_yose_needs_no_probe(self, monkeypatch):
        monkeypatch.setattr(ai_module, "HumanStyleStrategy", _FakeHumanStyle)
        s, logs = self._strategy(depth=95, lead=6.0, _mimic13_endgame=True)
        move, _ = s.generate_move()
        assert s.queries == [] and move.gtp() == "D4"

    def test_thin_lead_in_yose_plays_the_best_move(self, monkeypatch):
        monkeypatch.setattr(ai_module, "HumanStyleStrategy", _FakeHumanStyle)
        _FakeHumanStyle.calls = []
        s, logs = self._strategy(depth=95, lead=2.0, _mimic13_endgame=True)
        move, _ = s.generate_move()
        assert move.gtp() == "G7" and _FakeHumanStyle.calls == []

    def test_unsettled_board_stays_in_the_middle_game(self):
        s, logs = self._strategy(
            depth=90, ownership=[0.1] * 169,
            hp=_hp_array(13, {"G7": 0.40, "D4": 0.30}), probes=self._probes(),
        )
        move, _ = s.generate_move()
        assert getattr(s.game, "_mimic13_endgame", False) is False
        assert s.queries == ["Probe", "HumanSL"] and move.gtp() == "D4"
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_mimic13.py -q`
Expected: FAIL（`ImportError: cannot import name 'Mimic13Strategy'`）

- [ ] **Step 3: 定数とクラスを挿入** — `<scratchpad>/patch_task3.py` を Write して実行

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

# --- constants.py: 定数の定義だけ（GUI 一覧への登録は Task 4） ---
patch(
    "katrain/core/constants.py",
    [
        (
            'AI_ENIGMA_19_PLUS = "ai:enigma19plus"\n',
            'AI_ENIGMA_19_PLUS = "ai:enigma19plus"\n'
            "# 13路専用「擬態」戦略。相手より低い AI 最善手一致率を保ったまま勝つ＝リード連動の支払い上限の内側で\n"
            "# 人間らしい非最善手か期待値プラスの罠へ外し、ヨセは HumanStyle 9段へ委譲する\n"
            "# （ai.py の Mimic13Strategy・spec 2026-09-17-mimic13-strategy-design.md）\n"
            'AI_MIMIC_13 = "ai:mimic13"\n',
            1,
        )
    ],
)

# --- ai.py: import とクラス ---
CLASS_ANCHOR = "@register_strategy(AI_SCORELOSS)\nclass ScoreLossStrategy(AIStrategy):"

CLASS_CODE = '''@register_strategy(AI_MIMIC_13)
class Mimic13Strategy(Enigma13Strategy):
    """13路専用「擬態」戦略＝相手より低い AI 最善手一致率を保ったまま勝つ。

    序盤〜中盤は、リード連動の支払い上限 λ（`mimic_price_cap`）の内側で、不一致1回の値段
    price = max(0, vloss) − (E − E_best) が最も安い「資格のある」非最善手へ外す。資格は
    人間らしさ（humanSL 9段の humanPolicy が床以上）か罠（ΔE が trap_min_delta_e 以上＝相手を騙す手は
    人間らしさを免除）。最善手の humanPolicy が dominant_hp 以上の手番は外さない（外すとバレる）。
    price が負の手＝期待値プラスの罠は余剰が無くても打てるので、相手の悪手を誘って予算を作る。
    ヨセ（手数 AND 未確定点・sticky）は HumanStyle 9段へ委譲し、lead < reserve の手番だけ最善手。

    難解（Enigma13Strategy）のヘルパー（子局面プローブ・先読み・終局帯）を再利用し、選択フローだけ
    上書きする。すべての分岐は「KataGo 最善手を打つ」に倒れる。
    設計: docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md
    """

    BOARD_LEN = 13
    KEY_PREFIX = "mimic13"
    LABEL = "Mimic13"
    SETTING_DEFAULTS = {
        "max_loss": 2.0,            # 1手の損失上限（検証済み・目）＝λ の天井
        "reserve": 3.0,             # 確保するリード（目）。余剰 = lead − これ。ヨセの 9段委譲の条件にも使う
        "spend_rate": 0.25,         # 1手で余剰の何割まで払うか
        "free_loss": 0.3,           # 余剰が無くても払う「タダ同然」の price（目）
        "min_winrate": 0.4,         # 着手後勝率フロア（打つ側視点）
        "dominant_hp": 0.8,         # 最善手の humanPolicy がこれ以上なら外さない
        "min_human_policy": 0.05,   # 自然な外しの humanPolicy 下限（絶対値）
        "natural_ratio": 0.2,       # 同（第一感トップ比）
        "trap_min_delta_e": 0.5,    # 罠とみなす E の上積み（目）。99 で罠の免除なし
        "cost_slack": 0.3,          # price の同値帯（帯の中は humanPolicy 最大）
        "probe_extra": 4,           # 罠探索で高い帯から足すプローブ数
        "endgame_move": 85,         # ヨセ切替手数（HumanStyle 自身の終局閾値 ceil(0.5×169) と同じ）
        "unsettled_max": 16,        # ヨセ判定の未確定点上限
    }

    def _log_rates(self, player):
        """自分と相手の AI 最善手一致率をログに出す（判定には使わない。ログ失敗で着手を止めない）。"""
        try:
            nodes = [n for n in self.cn.nodes_from_root if n.move and not n.is_root]
            mine, opp, counted = parity9_match_tally(nodes, player)
        except Exception:
            return
        if counted:
            self._log(
                f"Rate: mine={mine}/{counted} ({mine / counted:.0%}) opp={opp}/{counted} ({opp / counted:.0%})"
            )

    def _expected_punish_of(self, probe, opponent):
        """子局面プローブ（clean + hp）から E（相手の期待損失）を返す。不完全なら None。"""
        clean, hp_child = (probe or {}).get("clean"), (probe or {}).get("hp")
        if not clean or not clean.get("moveInfos") or not hp_child or "humanPolicy" not in hp_child:
            return None
        replies, _best_reply = enigma9_reply_table(clean["moveInfos"], opponent)
        if not replies:
            return None
        e_punish, _coverage = enigma9_expected_punish(
            replies, enigma9_hp_lookup(hp_child["humanPolicy"], self.game.board_size)
        )
        return e_punish

    def _yose_move(self, lead, reserve):
        if not mimic_yose_delegates(lead, reserve):
            self._log(f"Yose: lead {lead:.2f} < reserve {reserve:.1f} -> best move")
            return self._best_move(
                f"{self.LABEL}: endgame, securing the win (lead {lead:.2f} < reserve {reserve:.1f}), playing best move."
            )
        self._log(f"Yose: lead {lead:.2f} >= reserve {reserve:.1f} -> HumanStyle rank_9d")
        delegate = HumanStyleStrategy(self.game, {"human_kyu_rank": -8, "modern_style": True})
        move, thoughts = delegate.generate_move()
        return move, f"[{self.LABEL}→9d yose] {thoughts}"

    def _generate_move(self) -> Tuple[Move, str]:
        self._cancel_ponder()  # 前手番の先読みの残骸を最初に打ち切る
        self.wait_for_analysis()
        player = self.cn.next_player
        sign = 1 if player == "B" else -1
        opponent = "W" if player == "B" else "B"

        side = self.BOARD_LEN
        if max(self.game.board_size) != side:
            self.game.katrain.log(
                f"[{type(self).__name__}] board size {self.game.board_size} is not {side}x{side}; "
                f"this mode is {side}x{side}-only, playing KataGo best move",
                OUTPUT_INFO,
            )
            return self._best_move(f"{self.LABEL}: not a {side}x{side} board, playing best move.")

        cands = self.cn.candidate_moves
        if not cands:
            return self._best_move(f"{self.LABEL}: no candidate moves.")
        best_gtp = cands[0]["move"]
        if best_gtp == "pass":
            return self._best_move(f"{self.LABEL}: best move is pass, playing it.")

        terminal = self._terminal_band_move(cands, player)
        if terminal is not None:
            return terminal

        root_lead = (self.cn.analysis.get("root") or {}).get("scoreLead")
        if root_lead is None:
            self._log("Lead unavailable -> best move")
            return self._best_move(f"{self.LABEL}: lead unavailable, playing best move.")
        lead = root_lead * sign
        reserve = float(self._setting("reserve"))

        # ---- ヨセ（手数 AND 未確定点・sticky）→ HumanStyle 9段へ委譲 ----
        # 突入の判定にだけ ownership Probe を撃つ（sticky 後は追加クエリなし）。ownership が取れなければ
        # `parity9_is_endgame` が手数だけでヨセ入りに倒す＝「測れない＝外し続ける」にならない
        endgame_flag = f"_{self.KEY_PREFIX}_endgame"
        in_yose = bool(getattr(self.game, endgame_flag, False))
        endgame_move = int(self._setting("endgame_move"))
        if not in_yose and self.cn.depth >= endgame_move:
            unsettled_max = int(self._setting("unsettled_max"))
            probe = self._run_query(
                "Probe",
                include_policy=False,
                ownership=True,
                extra_settings={"ignorePreRootHistory": False, "wideRootNoise": 0.0},
            )
            ownership = probe.get("ownership") if probe else None
            n_unsettled = (
                None if ownership is None else sum(1 for o in ownership if abs(o) < PARITY9_UNSETTLED_ABS)
            )
            if parity9_is_endgame(self.cn.depth, ownership, endgame_move, unsettled_max):
                setattr(self.game, endgame_flag, True)  # sticky
                in_yose = True
            self._log(
                f"Endgame check: depth={self.cn.depth} thr={endgame_move} unsettled={n_unsettled} "
                f"max={unsettled_max} -> {'yose' if in_yose else 'not yet'}"
            )
        if in_yose:
            return self._yose_move(lead, reserve)

        self._log_rates(player)

        # ---- 親局面の humanSL 9段（8visits）→ 支配ガード ----
        # humanPolicy は root NN の出力で visits に依らない。難解のようにプローブバッチへ統合しないのは、
        # shortlist に hp が要るのと、支配ガードの手番（実測 約2割）でプローブを丸ごと省けるため
        stage_hp = self._run_query(
            "HumanSL",
            include_policy=True,
            ownership=False,
            visits=ENIGMA9_HP_CHILD_VISITS,
            extra_settings={"humanSLProfile": ENIGMA9_HUMAN_PROFILE, "ignorePreRootHistory": False},
        )
        if not stage_hp or "humanPolicy" not in stage_hp:
            self._log("HumanSL unavailable -> best move")
            return self._best_move(f"{self.LABEL}: humanSL unavailable, playing best move.")
        human_policy = stage_hp["humanPolicy"]
        hp_of = enigma9_hp_lookup(human_policy, self.game.board_size)
        best_hp = hp_of(best_gtp)
        dominant = float(self._setting("dominant_hp"))
        if best_hp >= dominant:
            self._log(f"Dominant: best {best_gtp} hp={best_hp:.3f} >= {dominant:.2f} -> best move")
            return self._best_move(
                f"{self.LABEL}: the best move is the obvious human move (hp {best_hp:.1%}), playing it."
            )

        # ---- 支払い上限 λ ----
        max_loss = float(self._setting("max_loss"))
        min_wr = float(self._setting("min_winrate"))
        lam = mimic_price_cap(
            lead, reserve, float(self._setting("spend_rate")), float(self._setting("free_loss")), max_loss
        )
        self._log(f"Budget: lead={lead:.2f} reserve={reserve:.1f} surplus={lead - reserve:.2f} lambda={lam:.2f}")

        # ---- プール（難解と同じ二段の漏斗: 生 loss の足切りは安全側・採否は検証値）----
        candidates, _n_searched = parity9_build_candidates(cands, player=player, min_visits=ENIGMA9_POOL_MIN_VISITS)
        pool = enigma9_admissible(candidates, best_gtp, max_loss, min_wr)
        if not pool:
            self._log(f"Pool: no admissible deviation (cap {max_loss:.2f}, min_wr {min_wr:.0%}) -> best move")
            return self._best_move(f"{self.LABEL}: no admissible deviation, playing best move.")
        floor = mimic_natural_floor(
            mimic_hp_top(human_policy, self.game.board_size),
            float(self._setting("min_human_policy")),
            float(self._setting("natural_ratio")),
        )
        shortlist = mimic_shortlist(pool, hp_of, floor, extra=int(self._setting("probe_extra") or 0))
        naturals = [c["gtp"] for c in shortlist if hp_of(c["gtp"]) >= floor]
        self._log(
            f"Natural: floor={floor:.3f} best_hp={best_hp:.3f} naturals={naturals} "
            f"pool={len(pool)} shortlist={len(shortlist)}"
        )

        # ---- 子局面プローブ（難解と同一条件・1バッチ並列）----
        probes, _ = self._probe_children([best_gtp] + [c["gtp"] for c in shortlist], player, parent_hp=False)
        best_probe = probes.get(best_gtp) or {}
        best_lead_after, _ = enigma9_verified_metrics(best_probe.get("clean"), player)
        best_e = self._expected_punish_of(best_probe, opponent)
        if best_lead_after is None or best_e is None:
            self._log("Best-move probe unavailable -> best move")
            return self._best_move(f"{self.LABEL}: best-move probe unavailable, playing best move.")

        trap_min = float(self._setting("trap_min_delta_e"))
        scored = []
        for c in shortlist:
            pr = probes.get(c["gtp"]) or {}
            lead_after, wr_after = enigma9_verified_metrics(pr.get("clean"), player)
            e_punish = self._expected_punish_of(pr, opponent)
            if lead_after is None or e_punish is None:
                self._log(f"Probe incomplete for {c['gtp']} -> dropped")
                continue
            vloss = best_lead_after - lead_after
            if vloss > max_loss:
                self._log(f"Drop {c['gtp']}: verified loss {vloss:.2f} > max_loss {max_loss:.2f} (raw {c['loss']:.2f})")
                continue
            if wr_after is not None and wr_after < min_wr:
                self._log(f"Drop {c['gtp']}: verified wr {wr_after:.1%} < floor {min_wr:.0%}")
                continue
            own_hp = hp_of(c["gtp"])
            delta_e = e_punish - best_e
            price = max(0.0, vloss) - delta_e
            kind = mimic_qualifies(own_hp, delta_e, floor, trap_min)
            scored.append(
                {**c, "vloss": vloss, "wr_after": wr_after, "e": e_punish, "delta_e": delta_e,
                 "price": price, "own_hp": own_hp, "kind": kind}
            )
            wr_txt = "n/a" if wr_after is None else f"{wr_after:.1%}"
            self._log(
                f"Score {c['gtp']}: vloss={vloss:.2f} (raw {c['loss']:.2f}) wr={wr_txt} E={e_punish:.2f} "
                f"dE={delta_e:+.2f} price={price:.2f} hp={own_hp:.3f} kind={kind or '-'}"
            )

        chosen = mimic_choose(scored, best_gtp, lam, float(self._setting("cost_slack")))
        if chosen is None:
            self._log(f"No qualifying deviation within lambda {lam:.2f} -> best move")
            self._start_ponder(best_gtp, probes.get(best_gtp), player)
            return self._best_move(f"{self.LABEL}: no natural or trap deviation within budget, playing best move.")

        self._log(
            f"Deviate: played {chosen['gtp']} (price={chosen['price']:.2f}, vloss={chosen['vloss']:.2f}, "
            f"dE={chosen['delta_e']:+.2f}, hp={chosen['own_hp']:.3f}, kind={chosen['kind']}, lambda={lam:.2f}) "
            f"instead of {best_gtp}"
        )
        self._start_ponder(chosen["gtp"], probes.get(chosen["gtp"]), player)
        return (
            Move.from_gtp(chosen["gtp"], player=player),
            f"{self.LABEL}: deviated to {chosen['gtp']} ({chosen['kind']}, price {chosen['price']:.2f}, "
            f"verified loss {chosen['vloss']:.2f}, extra expected punish {chosen['delta_e']:+.2f}, "
            f"hp {chosen['own_hp']:.1%}) instead of {best_gtp}; lead {lead:.2f}, budget per move {lam:.2f}.",
        )


'''

patch(
    "katrain/core/ai.py",
    [
        (
            "AI_ENIGMA_9_PLUS, AI_ENIGMA_19_PLUS\n)\nfrom katrain.core.engine import KataGoEngine",
            "AI_ENIGMA_9_PLUS, AI_ENIGMA_19_PLUS, AI_MIMIC_13\n)\nfrom katrain.core.engine import KataGoEngine",
            1,
        ),
        (CLASS_ANCHOR, CLASS_CODE + CLASS_ANCHOR, 1),
    ],
)
```

Run: `python <scratchpad>/patch_task3.py`
Expected: `patched katrain/core/constants.py (CRLF, 1 edit(s))` と `patched katrain/core/ai.py (CRLF, 2 edit(s))`

注意（パッチが失敗したら）: Task 2 の挿入で `CLASS_ANCHOR` の直前は `mimic_yose_delegates` の末尾になっている。アンカー自体は 1 件のままなので件数エラーは出ないはず。出たら `grep -n "register_strategy(AI_SCORELOSS)" katrain/core/ai.py` で確認する。

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_ai_mimic13.py -q`
Expected: 全 PASS

テストの数値の検算（落ちたときの手がかり）: `_probes()` の最善手 G7 は子局面 lead 8.0・応手 C11/L3 とも損失 0 → `E_best = 0`。D4 は既定で lead 7.8 → `vloss 0.2`・`E 0` → `price 0.2`。`k10_punish=1.5` は L3 の scoreLead を +3.0（黒視点＝白が 3 目損）にするので `E = 0.5×0 + 0.5×3.0 = 1.5`・`vloss 1.0` → `price −0.5`。

- [ ] **Step 5: 既存回帰とコミット**

Run: `pytest tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py tests/test_ai_mimic13.py -q`
Expected: 全 PASS

Run: `git diff --stat`（`ai.py` / `constants.py` とも追加のみ・削除は import 行の 1 行だけ）

```bash
git add katrain/core/ai.py katrain/core/constants.py tests/test_ai_mimic13.py
git commit -m "feat(mimic13): 擬態（13路）戦略 Mimic13Strategy の選択フロー

支配ガード → リード連動の λ → hp 上位＋安い順＋spread のプローブ →
price = vloss − ΔE の最安（帯は humanPolicy 最大）。ヨセは HumanStyle 9段へ委譲し
lead < reserve の手番だけ最善手。全分岐が最善手に倒れる。

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: GUI・設定・i18n・デバッグ CLI への登録

**Files:**
- Modify: `katrain/core/constants.py`（戦略リスト・`AI_STRENGTH`・`AI_OPTION_VALUES`・`AI_OPTION_ORDER`）
- Modify: `katrain/config.json`（`"ai:scoreloss"` の直前に `"ai:mimic13"` ブロック）
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` / `en/.../katrain.po` → `python tools/compile_mo.py`
- Modify: `katrain_debug/runner.py`
- Test: `tests/test_ai_mimic13.py`

**Interfaces:**
- Consumes: `AI_MIMIC_13`、`Mimic13Strategy.SETTING_DEFAULTS`（Task 3）
- Produces: GUI の戦略一覧に「擬態（13路）」、`python -m katrain_debug --strategy mimic13`

- [ ] **Step 1: 失敗するテストを追記**（末尾）

```python
class TestGuiConfigConsistency:
    """SETTING_DEFAULTS・AI_OPTION_VALUES・AI_OPTION_ORDER・パッケージ config.json・戦略リストの整合。"""

    def test_listed_everywhere(self):
        from katrain.core.constants import (
            AI_MIMIC_13, AI_STRATEGIES, AI_STRATEGIES_ENGINE, AI_STRATEGIES_RECOMMENDED_ORDER, AI_STRENGTH,
        )

        assert AI_MIMIC_13 in AI_STRATEGIES_ENGINE        # 通常解析の完了を待つ系
        assert AI_MIMIC_13 in AI_STRATEGIES
        assert AI_MIMIC_13 in AI_STRATEGIES_RECOMMENDED_ORDER
        assert AI_MIMIC_13 in AI_STRENGTH

    def test_defaults_in_gui_options_and_package_config(self):
        import json
        from pathlib import Path

        import katrain
        from katrain.core.constants import AI_OPTION_ORDER, AI_OPTION_VALUES

        with open(Path(katrain.__file__).parent / "config.json", encoding="utf-8") as f:
            package_ai_conf = json.load(f)["ai"]["ai:mimic13"]
        expected = {f"mimic13_{suffix}" for suffix in Mimic13Strategy.SETTING_DEFAULTS}
        assert set(package_ai_conf) == expected
        for suffix, default in Mimic13Strategy.SETTING_DEFAULTS.items():
            key = f"mimic13_{suffix}"
            assert package_ai_conf[key] == default, key
            assert key in AI_OPTION_ORDER, key
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]
            assert default in plain, key

    def test_debug_cli_knows_the_strategy(self):
        from katrain.core.constants import AI_MIMIC_13
        from katrain_debug.runner import STRATEGY_NAME_MAP

        assert STRATEGY_NAME_MAP["mimic13"] == AI_MIMIC_13

    @pytest.mark.parametrize("lang", ["jp", "en"])
    def test_i18n_has_every_label(self, lang):
        from pathlib import Path

        import katrain

        po = (Path(katrain.__file__).parent / "i18n" / "locales" / lang / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        for msgid in ["ai:mimic13", "aihelp:mimic13"] + [f"mimic13_{s}" for s in Mimic13Strategy.SETTING_DEFAULTS]:
            assert f'msgid "{msgid}"' in po, msgid
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_mimic13.py::TestGuiConfigConsistency -q`
Expected: FAIL（`AI_MIMIC_13 not in AI_STRATEGIES_ENGINE` 等）

- [ ] **Step 3: constants.py と runner.py をパッチ** — `<scratchpad>/patch_task4.py` を Write して実行

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crlf_patch import patch

OPTION_VALUES = '''    "enigma19plus_opening_humanstyle_moves": _ENIGMA_OPENING_HUMANSTYLE_MOVES,
    # ===== Mimic13Strategy（13路専用・擬態）spec 2026-09-17-mimic13-strategy-design.md =====
    # 相手より低い一致率で勝つ。price = vloss − ΔE をリード連動の λ で買う
    "mimic13_max_loss": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
    "mimic13_reserve": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0],
    "mimic13_spend_rate": [0.1, 0.25, 0.5, 1.0],
    "mimic13_free_loss": [0.0, 0.1, 0.2, 0.3, 0.5],
    "mimic13_min_winrate": [(0.3, "30%"), (0.35, "35%"), (0.4, "40%"), (0.45, "45%"), (0.5, "50%")],
    "mimic13_dominant_hp": [(0.6, "60%"), (0.7, "70%"), (0.8, "80%"), (0.9, "90%"), (0.95, "95%")],
    "mimic13_min_human_policy": [(0.01, "1%"), (0.02, "2%"), (0.03, "3%"), (0.05, "5%"), (0.1, "10%")],
    "mimic13_natural_ratio": [0.1, 0.2, 0.3, 0.5],
    # 99 = OFF（罠の「人間らしさ免除」を使わない）
    "mimic13_trap_min_delta_e": [(0.3, "0.3"), (0.5, "0.5"), (1.0, "1.0"), (1.5, "1.5"), (99.0, "OFF")],
    "mimic13_cost_slack": [0.0, 0.2, 0.3, 0.5, 1.0],
    "mimic13_probe_extra": [0, 2, 4, 6],
    # 85 = HumanStyle 自身の終局閾値 ceil(0.5×169)。それ未満だと委譲先が hp 重みのランダム選択になる
    "mimic13_endgame_move": [65, 75, 85, 95, 105],
    "mimic13_unsettled_max": [8, 12, 16, 20, 24],
}
'''

OPTION_ORDER = '''    "enigma19plus_opening_humanstyle_moves": 13,
    "mimic13_max_loss": 0,
    "mimic13_reserve": 1,
    "mimic13_spend_rate": 2,
    "mimic13_free_loss": 3,
    "mimic13_min_winrate": 4,
    "mimic13_dominant_hp": 5,
    "mimic13_min_human_policy": 6,
    "mimic13_natural_ratio": 7,
    "mimic13_trap_min_delta_e": 8,
    "mimic13_cost_slack": 9,
    "mimic13_probe_extra": 10,
    "mimic13_endgame_move": 11,
    "mimic13_unsettled_max": 12,
}
'''

patch(
    "katrain/core/constants.py",
    [
        ("AI_ENIGMA_19, AI_ENIGMA_19_PLUS, AI_ANTIMIRROR]", "AI_ENIGMA_19, AI_ENIGMA_19_PLUS, AI_MIMIC_13, AI_ANTIMIRROR]", 1),
        ("    AI_ENIGMA_19_PLUS,\n    AI_ANTIMIRROR,\n", "    AI_ENIGMA_19_PLUS,\n    AI_MIMIC_13,\n    AI_ANTIMIRROR,\n", 1),
        ('    AI_ENIGMA_19: float("nan"),\n', '    AI_ENIGMA_19: float("nan"),\n    AI_MIMIC_13: float("nan"),\n', 1),
        ('    "enigma19plus_opening_humanstyle_moves": _ENIGMA_OPENING_HUMANSTYLE_MOVES,\n}\n', OPTION_VALUES, 1),
        ('    "enigma19plus_opening_humanstyle_moves": 13,\n}\n', OPTION_ORDER, 1),
    ],
)

patch(
    "katrain_debug/runner.py",
    [
        ("    AI_ENIGMA_9_PLUS, AI_ENIGMA_19_PLUS,\n)", "    AI_ENIGMA_9_PLUS, AI_ENIGMA_19_PLUS, AI_MIMIC_13,\n)", 1),
        ('    "enigma19": AI_ENIGMA_19,\n}', '    "enigma19": AI_ENIGMA_19,\n    "mimic13": AI_MIMIC_13,\n}', 1),
    ],
)
```

Run: `python <scratchpad>/patch_task4.py`
Expected: 2 ファイルとも `patched ...`

- [ ] **Step 4: パッケージ `katrain/config.json` に既定値を追加**（Edit ツール。`"ai:scoreloss": {` の直前）

old:
```
        "ai:scoreloss": {
```
new:
```
        "ai:mimic13": {
            "mimic13_max_loss": 2.0,
            "mimic13_reserve": 3.0,
            "mimic13_spend_rate": 0.25,
            "mimic13_free_loss": 0.3,
            "mimic13_min_winrate": 0.4,
            "mimic13_dominant_hp": 0.8,
            "mimic13_min_human_policy": 0.05,
            "mimic13_natural_ratio": 0.2,
            "mimic13_trap_min_delta_e": 0.5,
            "mimic13_cost_slack": 0.3,
            "mimic13_probe_extra": 4,
            "mimic13_endgame_move": 85,
            "mimic13_unsettled_max": 16
        },
        "ai:scoreloss": {
```

Run: `python -c "import json;json.load(open('katrain/config.json',encoding='utf-8'));print('ok')"`
Expected: `ok`

- [ ] **Step 5: i18n（jp）** — `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `msgid "enigma19plus_opening_humanstyle_moves"` エントリ（msgstr の次の空行）の直後に追記（Edit ツール）

```
msgid "ai:mimic13"
msgstr "擬態（13路）"

msgid "aihelp:mimic13"
msgstr "13路盤専用。相手より低い「AIの最善手との一致率」を保ったまま勝つことを狙います。序盤〜中盤は、人間らしい非最善手（9段の humanPolicy が高い手）か、相手を騙す罠（相手の期待損失 E が最善手より大きく増える手）へ外します。1回の不一致の値段は「検証済み損失 − E の上積み」で測り、リードの余剰（リード − 確保するリード）に応じた上限の中で最も安い手を選びます。値段が負の罠は余剰が無くても打つので、相手の悪手を誘って外しの原資を作ります。9段の第一感が1点に集中している局面（外すとわざとだとバレる）では最善手を打ちます。ヨセ（手数と未確定点で判定）は Human-like 9段へ委譲し、リードが確保ラインを割った手番だけ最善手で勝ちを守ります。humanSL モデルが必要です。13路以外では常に最善手を打ちます。"

msgid "mimic13_max_loss"
msgstr "[擬態13] 1手あたり損失上限（目）"

msgid "mimic13_reserve"
msgstr "[擬態13] 確保するリード（目）"

msgid "mimic13_spend_rate"
msgstr "[擬態13] 1手で使う余剰リードの割合"

msgid "mimic13_free_loss"
msgstr "[擬態13] 余剰なしでも払う値段（目）"

msgid "mimic13_min_winrate"
msgstr "[擬態13] 着手後の勝率フロア"

msgid "mimic13_dominant_hp"
msgstr "[擬態13] 最善手の第一感がこれ以上なら外さない"

msgid "mimic13_min_human_policy"
msgstr "[擬態13] 自然な外しの humanPolicy 下限"

msgid "mimic13_natural_ratio"
msgstr "[擬態13] 自然な外しの下限（第一感トップ比）"

msgid "mimic13_trap_min_delta_e"
msgstr "[擬態13] 罠とみなす E の上積み（目・OFF=罠の免除なし）"

msgid "mimic13_cost_slack"
msgstr "[擬態13] 値段の同値帯（帯の中は人間らしさ優先）"

msgid "mimic13_probe_extra"
msgstr "[擬態13] 罠探索の追加プローブ数"

msgid "mimic13_endgame_move"
msgstr "[擬態13] ヨセ切替手数（85未満は9段がランダム選択）"

msgid "mimic13_unsettled_max"
msgstr "[擬態13] ヨセ判定の未確定点上限"

```

- [ ] **Step 6: i18n（en）** — `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の同じ位置に追記

```
msgid "ai:mimic13"
msgstr "Mimic (13x13)"

msgid "aihelp:mimic13"
msgstr "13x13 only. Aims to win while keeping its AI-best-move match rate below the opponent's. Before the endgame it deviates to a human-looking non-best move (high 9d humanPolicy) or to a trap (a move that raises the opponent's expected loss E well above the best move's). The price of one mismatch is 'verified loss minus the extra E'; the cheapest qualifying move is played if its price fits the per-move budget derived from the surplus lead (lead minus the reserve). Traps with a negative price are played even without surplus, which is how the mode earns budget from opponent mistakes. When the 9d first instinct is concentrated on the best move, the best move is played (deviating would look deliberate). The endgame (move number AND unsettled points) is handed to Human-like 9d; when the lead drops below the reserve the best move is played instead. Requires the humanSL model. On other board sizes it always plays the best move."

msgid "mimic13_max_loss"
msgstr "[Mimic13] Max loss per move (pts)"

msgid "mimic13_reserve"
msgstr "[Mimic13] Lead to keep in reserve (pts)"

msgid "mimic13_spend_rate"
msgstr "[Mimic13] Share of surplus lead spent per move"

msgid "mimic13_free_loss"
msgstr "[Mimic13] Price paid even without surplus (pts)"

msgid "mimic13_min_winrate"
msgstr "[Mimic13] Winrate floor after the move"

msgid "mimic13_dominant_hp"
msgstr "[Mimic13] Never deviate when best move humanPolicy >="

msgid "mimic13_min_human_policy"
msgstr "[Mimic13] Min humanPolicy of a natural deviation"

msgid "mimic13_natural_ratio"
msgstr "[Mimic13] Natural deviation floor (ratio of top humanPolicy)"

msgid "mimic13_trap_min_delta_e"
msgstr "[Mimic13] Extra E that makes a move a trap (OFF = no exemption)"

msgid "mimic13_cost_slack"
msgstr "[Mimic13] Price tie band (most human move wins inside)"

msgid "mimic13_probe_extra"
msgstr "[Mimic13] Extra probes for trap search"

msgid "mimic13_endgame_move"
msgstr "[Mimic13] Endgame switch move (below 85 the 9d samples randomly)"

msgid "mimic13_unsettled_max"
msgstr "[Mimic13] Max unsettled points for endgame"

```

Run: `python tools/compile_mo.py`
Expected: エラーなし（`.mo` が更新される）

- [ ] **Step 7: テストが通ることを確認**

Run: `pytest tests/test_ai_mimic13.py tests/test_ai_options_grid.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py -q`
Expected: 全 PASS（`test_ai_options_grid.py` は `test_collapsable_panel.py` と順序依存のフレークがある＝単体で落ちたら単体再実行で切り分ける）

- [ ] **Step 8: コミット**

Run: `git diff --stat`（`constants.py` / `runner.py` は追加のみ＋置換行）

```bash
git add katrain/core/constants.py katrain/config.json katrain_debug/runner.py katrain/i18n tests/test_ai_mimic13.py
git commit -m "feat(mimic13): 擬態（13路）を GUI・設定・i18n・デバッグ CLI に登録

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: ユーザーローカル設定（メインセッション限定）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（**サブエージェントに委任しない**）

- [ ] **Step 1: KaTrain が起動していないことを確認**

Run: `python -c "import ctypes; print('running' if ctypes.windll.user32.FindWindowW(None, 'KaTrain v1.17.1') else 'not-running')"`
Expected: `not-running`（`running` ならユーザーに終了を依頼してから進む＝起動中の編集は終了時に上書きで消える）

- [ ] **Step 2: `"ai"` セクションに `"ai:mimic13"` を追加**（Read してから Edit。Task 4 Step 4 と同じ 13 キー・同じ値。挿入位置は `"ai:enigma19plus"` ブロックの直後など `"ai"` 直下ならどこでもよい）

- [ ] **Step 3: JSON とキーの検算**

Run: `python -c "import json,os;c=json.load(open(os.path.expanduser('~/.katrain/config.json'),encoding='utf-8'));print(sorted(c['ai']['ai:mimic13'].items()))"`
Expected: 13 キーが既定値で出る

（リポジトリ外なのでコミットなし）

---

### Task 6: 実エンジンでの単一局面確認

**Files:** なし（確認のみ。結果は Task 7 の docs に数値で書く）

- [ ] **Step 1: 中盤の外し**（KataGo 起動・約 30〜60 秒）

Run:
```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma13/enigma13-vs-human-20260901-white.sgf --move 30 --strategy mimic13 --output text 2>&1 | grep -a -E "Mimic13|Selected|move" | head -40
```
Expected: `[Mimic13Strategy] Budget:` / `Natural:` / `Score …` 行が出て、`Deviate:` か `-> best move` で終わる。例外・`KeyError` が無いこと。

注意: この SGF は AI が白番。`--move N` の手番が白になる N（偶数手後＝`Score` 行の候補が白の手）を選ぶ。手番が黒でも戦略は動く（色非依存）ので確認には支障ない。KaTrain 保存 SGF は variation が多いので、手数が進まないときは `docs/superpowers/specs/calibration-data/clean_sgf_main_line.py` で main line 化してから使う。

- [ ] **Step 2: 支配ガード・ヨセ委譲の経路を1回ずつ踏む**

Run（手数を振って `Dominant:` と `Yose:` のログが出る局面を探す）:
```bash
for n in 12 24 36 48 60 90 100; do echo "== move $n"; python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma13/enigma13-vs-human-20260901-white.sgf --move $n --strategy mimic13 --output text 2>&1 | grep -a -E "\[Mimic13Strategy\] (Budget|Dominant|Natural|Deviate|Yose|Endgame check|No qualifying|Pool)|着手決定" ; done
```
Expected: 少なくとも1局面で `Deviate:`、90 手以降で `Endgame check:` → `Yose:`。`着手決定に X 秒` が中盤で概ね 3 秒以内（コールド）。

- [ ] **Step 3: 設定上書きが効くこと**

Run:
```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma13/enigma13-vs-human-20260901-white.sgf --move 30 --strategy mimic13 --settings mimic13_dominant_hp=0.0 --output text 2>&1 | grep -a "Dominant"
```
Expected: `Dominant: best … >= 0.00 -> best move`（フラグが読む側に届いていることの確認）

結果（外した手・price・λ・秒数）をメモして Task 7 の docs に書く。想定外の挙動（全手番で `No qualifying`、price が常に大きい等）があれば、**実装に戻る前に** `Score` 行の値を spec §2 の在庫実測と照合する。

---

### Task 7: ドキュメント

**Files:**
- Modify: `.claude/rules/ai-strategies.md`（末尾の「関連 spec」節の前に段落を追加）
- Modify: `.claude/rules/ai-parameters.md`（末尾に節を追加）
- Modify: `CLAUDE.md`（改修3系統の表の「Human-like AI 戦略」行・ディレクトリ構造の `ai.py` 行・「コーディング規約」の戦略クラス列挙）
- Modify: `docs/manual/src/06_ai_overview.html`（用途別の案内と一覧表に1行）/ `docs/manual/src/06d_ai_parity.html`（カード追加）→ `python tools/build_manual.py`
- Modify: `docs/superpowers/specs/INDEX.md`（⛔→🟢）/ spec 冒頭の「状態」

- [ ] **Step 1: `.claude/rules/ai-strategies.md`** — 「## 関連 spec」の直前に追加（Edit。拒否されたらサブエージェント経由）

```markdown
13路には**相手より低い一致率で勝つ専用戦略 `ai:mimic13`（擬態（13路））**がある（2026-09-17・spec `2026-09-17-mimic13-strategy-design.md`。実装は `Mimic13Strategy(Enigma13Strategy)` が `_generate_move` を上書きし、難解の子局面プローブ・先読み・終局帯〈`_terminal_band_move` に抽出して共有〉を再利用）。不一致1回の値段を `price = max(0, vloss) − (E − E_best)`〈難解の net から rarity 項を外したものと同値。own_rare は「humanPolicy の低い手ほど加点」で人間らしさと逆向き、reply_rare は E を与件にすると寄与ゼロ〉で測り、**リード連動の支払い上限 λ**〈`mimic_price_cap`: lead < −1 → 0／余剰なし → `free_loss` 0.3／余剰あり → min(`max_loss` 2.0, 余剰 × `spend_rate` 0.25)。余剰 = lead − `reserve` 3.0〉の内側で、**資格**〈自然＝hp >= max(`min_human_policy` 0.05, `natural_ratio` 0.2 × 第一感トップ)／罠＝ΔE >= `trap_min_delta_e` 0.5 かつ hp >= 0.005＝相手を騙す手は人間らしさを免除〉のある最安の手へ外す（`cost_slack` 0.3 以内の帯は hp 最大＝parity9 の「最安バンド内 humanPolicy 最大」と同型）。price が負＝期待値プラスの罠は余剰が無くても打つ＝**相手の悪手を誘って外しの原資を作る**。**支配ガード**: 最善手の hp >= `dominant_hp` 0.8 の手番は罠も含めて外さない（親 humanSL 8visits を先に1本撃つのでプローブ0本）。ヨセ（手数 >= 85 AND 未確定点 <= 16・sticky `game._mimic13_endgame`）は HumanStyle 9段へ丸ごと委譲し、`lead < reserve` の手番だけ最善手（85 は HumanStyle 自身の終局閾値＝それ未満だと委譲先が hp 重みのランダム選択になる）。一致率（`parity9_match_tally`）は毎手ログに出すだけで判定に使わない。設計の根拠は 13路難解ログ 18 局の在庫実測: 中盤 443 手番で 自然な非最善手が居る 67〜79%〈下限〉・タダ同然 or 期待値プラスの罠 約40%・最善手 hp>=0.8 が 22%、リードは典型 +3〜+35 ＝**律速は予算ではなく自然な代替手の在庫**。**実戦校正は未実施**（相手の一致率が未実測）。
```

- [ ] **Step 2: `.claude/rules/ai-parameters.md`** — 末尾に追加

```markdown

## Mimic13Strategy（`ai:mimic13` / 擬態（13路））

13路専用。**相手より低い AI 最善手一致率を保ったまま勝つ**。設計: `2026-09-17-mimic13-strategy-design.md`。
`Mimic13Strategy(Enigma13Strategy)` が `_generate_move` を上書き（プローブ条件・E・先読み・終局帯は難解と共有。
sticky ヨセフラグ `game._mimic13_endgame`・ログタグ `[Mimic13Strategy]`）。

`price = max(0, vloss) − (E − E_best)`。λ = lead < −1.0 → 0 ／ 余剰（lead − reserve）<= 0 → free_loss ／
余剰 > 0 → min(max_loss, max(free_loss, 余剰 × spend_rate))。資格（自然 or 罠）あり・price <= λ の最安、
`cost_slack` 以内の帯は hp 最大。ハード条件は vloss <= max_loss と着手後勝率 >= min_winrate（検証値）。

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `mimic13_max_loss` | 1手の損失上限（検証済み・目）＝λ の天井 | 0.5〜5.0 | 2.0 |
| `mimic13_reserve` | 確保するリード（目）。余剰 = lead − これ。ヨセの 9段委譲の条件にも使う | 0〜10 | 3.0 |
| `mimic13_spend_rate` | 1手で余剰の何割まで払うか | 0.1/0.25/0.5/1.0 | 0.25 |
| `mimic13_free_loss` | 余剰が無くても払う price（目） | 0〜0.5 | 0.3 |
| `mimic13_min_winrate` | 着手後勝率フロア | 30〜50% | 0.40 |
| `mimic13_dominant_hp` | 最善手の hp がこれ以上なら外さない（罠も不可・プローブ0本） | 60〜95% | 0.8 |
| `mimic13_min_human_policy` | 自然な外しの hp 下限（絶対値） | 1〜10% | 0.05 |
| `mimic13_natural_ratio` | 同（第一感トップ比） | 0.1/0.2/0.3/0.5 | 0.2 |
| `mimic13_trap_min_delta_e` | 罠とみなす ΔE（目）。99=OFF | 0.3/0.5/1.0/1.5/OFF | 0.5 |
| `mimic13_cost_slack` | price の同値帯（帯の中は hp 最大） | 0〜1.0 | 0.3 |
| `mimic13_probe_extra` | 罠探索で高い帯から足すプローブ数 | 0/2/4/6 | 4 |
| `mimic13_endgame_move` | ヨセ切替手数（AND の片側・sticky）。**85 未満は委譲先 HumanStyle が hp 重みのランダム選択** | 65〜105 | 85 |
| `mimic13_unsettled_max` | ヨセ判定の未確定点上限 | 8〜24 | 16 |

モジュール定数: `MIMIC_BEHIND_LIMIT=-1.0` / `MIMIC_TRAP_MIN_HP=0.005` / `MIMIC_SHORTLIST_NATURAL=4` /
`MIMIC_SHORTLIST_CHEAP=4`（プローブは最善手＋最大 12 手）。プローブ条件は `ENIGMA9_*` を共有。

**確認**: ログの `Rate:`（一致率の推移）/ `Budget:`（lead・λ）/ `Dominant:` / `Natural:` / `Score …`（vloss・dE・price・hp・kind）/
`Deviate:` / `Yose:`。CLI: `python -m katrain_debug --sgf <13路SGF> --move N --strategy mimic13`。
**実戦校正は未実施**（成功基準は 勝ち かつ 終局レポートで自分の一致率 < 相手の一致率。一致率だけで判定せず
払った vloss 合計・罠の実現値と並べて読む）。
```

Task 6 の単一局面の実測値（外した手・price・λ・着手決定秒）をこの節の末尾に 2〜3 行で追記する。

- [ ] **Step 3: `CLAUDE.md`** — 3 箇所

1. 改修3系統の表「Human-like AI 戦略」行の内容の末尾 `…・`EnigmaPlusMixin`）` の後ろに ` / 擬態（13路＝相手より低い一致率で勝つ・`Mimic13Strategy`）` を足す
2. ディレクトリ構造の `ai.py` 行のクラス列挙 `EnigmaPlusMixin（Enigma9Plus / Enigma13Plus / Enigma19Plus）` の後ろに ` / Mimic13` を足す
3. 「コーディング規約」の戦略クラス列挙 `` `Enigma9Strategy`（+13/19） `` の後ろに `` / `Mimic13Strategy` `` を足す

- [ ] **Step 4: マニュアル** — `docs/manual/src/06d_ai_parity.html` の `ai-parity9` カード（`</div>` で閉じる最後のカード）の後ろにカードを追加

```html
<div class="card" id="ai-mimic13">
  <h3>擬態（13路） <code>ai:mimic13</code></h3>
  <div class="tags"><span class="tag ok">13路専用</span><span class="tag no">9/19路では最善手のみ</span><span class="tag hs">humanSL 必須</span></div>
  <p>
    13路盤で、<b>相手より低い最善手一致率を保ったまま勝つ</b>ことを狙います。わざと外しているとバレないよう、外す先は「9段が実際に打ちそうな手」か「相手を騙す罠」に限ります。
  </p>
  <ol>
    <li><b>9段の第一感が最善手に集中している局面</b>（humanPolicy が <code>mimic13_dominant_hp</code> 以上）は最善手。ここで外すと露骨なため、罠も打ちません。</li>
    <li>それ以外は候補を子局面まで読み、<b>不一致 1 回の値段</b>＝「検証済み損失 −（相手の期待損失 E の上積み）」を出します。値段が負の手は<b>期待値プラスの罠</b>で、相手の悪手を誘って外しの原資を作ります。</li>
    <li>払える上限はリード連動: 余剰（リード − <code>mimic13_reserve</code>）が無ければ <code>mimic13_free_loss</code> まで、あれば余剰 × <code>mimic13_spend_rate</code>（天井 <code>mimic13_max_loss</code>）。1 目以上負けているときは値段が負の手しか打ちません。</li>
    <li>上限内で<b>最も安い手</b>を選び、<code>mimic13_cost_slack</code> 以内で並ぶ手があれば最も人間らしい手にします。資格は「人間らしい手」（humanPolicy が下限以上）か「罠」（E の上積みが <code>mimic13_trap_min_delta_e</code> 以上）。</li>
    <li>ヨセ（<code>mimic13_endgame_move</code> 手以降かつ未確定点が <code>mimic13_unsettled_max</code> 以下）は Human-like 9段へ委譲。リードが確保ラインを割った手番だけ最善手で勝ちを守ります。</li>
  </ol>
  <div class="tablewrap"><table class="params">
    <thead><tr><th>設定項目</th><th>既定</th><th>範囲</th><th>意味</th><th>上げると／下げると</th></tr></thead>
    <tbody>
      <tr><td>mimic13_max_loss</td><td>2.0</td><td>0.5〜5.0</td><td>1 手の損失上限（目）。</td><td><span class="up">上げる</span>大差のとき外せる手番が増えるが、外しが目立つ</td></tr>
      <tr><td>mimic13_reserve</td><td>3.0</td><td>0〜10</td><td>確保するリード（目）。これを超えた分だけを外しに使う。ヨセの 9段委譲の条件でもある。</td><td><span class="up">上げる</span>安全だが一致率が下がりにくい</td></tr>
      <tr><td>mimic13_spend_rate</td><td>0.25</td><td>0.1〜1.0</td><td>1 手で余剰の何割まで払うか。</td><td><span class="up">上げる</span>早く使い切る</td></tr>
      <tr><td>mimic13_free_loss</td><td>0.3</td><td>0〜0.5</td><td>余剰が無くても払う「タダ同然」の値段（目）。</td><td>0 で接戦の外しは期待値プラスの罠だけに</td></tr>
      <tr><td>mimic13_min_winrate</td><td>40%</td><td>30〜50%</td><td>着手後の勝率フロア。</td><td><span class="up">上げる</span>互角の局面で罠を打たなくなる</td></tr>
      <tr><td>mimic13_dominant_hp</td><td>80%</td><td>60〜95%</td><td>最善手の第一感がこれ以上なら外さない。</td><td><span class="down">下げる</span>より慎重（一致率は上がる）</td></tr>
      <tr><td>mimic13_min_human_policy</td><td>5%</td><td>1〜10%</td><td>人間らしい外しの humanPolicy 下限。</td><td><span class="down">下げる</span>外せる手番が増えるが珍しい手が混ざる</td></tr>
      <tr><td>mimic13_natural_ratio</td><td>0.2</td><td>0.1〜0.5</td><td>同じ下限を第一感トップとの比でも課す。</td><td><span class="up">上げる</span>第一感の強い局面で外さなくなる</td></tr>
      <tr><td>mimic13_trap_min_delta_e</td><td>0.5</td><td>0.3〜1.5／OFF</td><td>罠とみなす E の上積み（目）。罠は人間らしさの条件を免除。</td><td>OFF で人間らしい手しか打たない</td></tr>
      <tr><td>mimic13_cost_slack</td><td>0.3</td><td>0〜1.0</td><td>値段の同値帯。帯の中は最も人間らしい手。</td><td>0 で常に最安</td></tr>
      <tr><td>mimic13_probe_extra</td><td>4</td><td>0〜6</td><td>罠探索のために損失の高い帯から足すプローブ数。</td><td><span class="down">下げる</span>1 手が速くなる</td></tr>
      <tr><td>mimic13_endgame_move</td><td>85</td><td>65〜105</td><td>ヨセ判定の手数側の条件。</td><td>85 未満にすると、その間の 9段は候補から確率で選ぶ（ブレが出る）</td></tr>
      <tr><td>mimic13_unsettled_max</td><td>16</td><td>8〜24</td><td>ヨセ判定の未確定点上限。手数条件との AND。</td><td><span class="up">上げる</span>早くヨセ扱いに</td></tr>
    </tbody>
  </table></div>
  <div class="callout">
    <span class="label">一致率は相手次第です</span>
    相手が悪手を打つほど余剰ができて外せます。強い相手との接戦では「タダ同然の外し」と「期待値プラスの罠」しか打たないので一致率は高めに残ります（勝ちを優先する設計どおり）。
  </div>
</div>
```

`docs/manual/src/06_ai_overview.html`:
- 15 行目の案内 `9路なら <a href="#ai-parity9">一致率追随（9路）</a>` の後ろに `／13路で相手より低く保つなら <a href="#ai-mimic13">擬態（13路）</a>` を足す
- 一覧表の `ai:parity9` 行の次に追加:
```html
    <tr><th><a href="#ai-mimic13">擬態（13路）</a></th><td><code>ai:mimic13</code></td><td>13</td><td>必須</td><td>相手より低い一致率を保って勝つ（人間らしい外し＋罠・ヨセは9段）</td></tr>
```

Run: `python tools/build_manual.py`
Expected: `missing images: none` / `broken anchors: none`（exit 0）

- [ ] **Step 5: INDEX と spec の状態**

`docs/superpowers/specs/INDEX.md` の該当行を `| `2026-09-17-mimic13-strategy-design.md` | 🟢 擬態（13路）`ai:mimic13`＝相手より低い一致率で勝つ。price = vloss − ΔE をリード連動の λ で買う・自然さ（humanPolicy）か罠（ΔE）の資格・ヨセは 9段委譲・**実戦校正は未実施** |` に置き換える。
spec 冒頭の `状態: 設計（未実装）` を `状態: 実装済み（2026-09-17）・実戦校正は未実施` にする。

- [ ] **Step 6: コミット**

```bash
git add .claude/rules/ai-strategies.md .claude/rules/ai-parameters.md CLAUDE.md docs/manual docs/superpowers/specs
git commit -m "docs(mimic13): 擬態（13路）の rules・CLAUDE.md・マニュアル・INDEX を更新

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: 最終検証

- [ ] **Step 1: 全テスト**

Run: `pytest --ignore=tests/test_ai.py -q`
Expected: 全 PASS。`test_collapsable_panel.py` の 6 件が落ちたら既知の順序依存フレーク＝`pytest tests/test_collapsable_panel.py -q` 単体で PASS を確認する。ソルバの時間閾値系が落ちたら KataGo と並走していないか確認して単体再実行。

- [ ] **Step 2: 差分の健全性**

Run: `git diff upstream-v1.20-fixes --stat`
Expected: `ai.py` は +約 330 / −約 85（Task 1 の移動ぶん）、`constants.py` は +約 40 / −5 程度。桁が違えば再整形が混入している。

- [ ] **Step 3: GUI 確認の依頼**（ユーザー作業）

KaTrain を起動 → 対局設定で AI に「擬態（13路）」を選べること、AI 設定画面に 13 スライダーが日本語ラベルで並ぶこと、13路で数手打たせて `~/.katrain/logs/game_*.log` に `[Mimic13Strategy] 着手決定に` が出ることを確認してもらう。`debug_level: 1` にすれば `Budget:` / `Score` / `Deviate:` 行も出る。

---

## 実装後の校正（この計画の範囲外・記録だけ）

監視対局を数局打ち、ログの `Rate:` 行で自分と相手の一致率の推移、`Deviate:` 行の kind 別（natural/trap）件数と price 合計、フェーズ別（中盤/ヨセ）の一致率を集計して、`reserve` / `spend_rate` / `max_loss` / `dominant_hp` を決める。「一致率が下がった」だけで判定しない（実損失と並べる）。
