# Lambdago Cheat Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add lambdago paper-derived metrics (Choice-vs-Median Gap, Post-98% Slack) to `katrain_debug --batch` output for jigo strategy parameter tuning.

**Architecture:** Pure-Python additions inside `katrain_debug/`. Per-move data collected during the existing batch loop, aggregated by a new `_aggregate_lambdago_metrics()` alongside `_aggregate_jigo_metrics()`, surfaced under `stats["lambdago_metrics"]` (json) and a new text block (cli). No changes to `katrain/core/ai.py` or KataGo engine wiring.

**Tech Stack:** Python 3.12, pytest, existing `katrain_debug/batch_eval.py` and `cli.py`.

**Spec:** `docs/superpowers/specs/2026-04-14-lambdago-cheat-metrics-design.md`

---

## File Structure

| File | Role | New/Modify |
|---|---|---|
| `katrain_debug/batch_eval.py` | Per-move helpers + `_aggregate_lambdago_metrics()` + integrate into `batch_evaluate()` | Modify |
| `katrain_debug/cli.py` | Text formatter for the new metrics block | Modify |
| `tests/test_lambdago_metrics.py` | Pure unit tests (no KataGo) | Create |
| `CLAUDE.md` | Document the new aggregate columns | Modify |

The helpers and aggregator live in `batch_eval.py` (same pattern as `_aggregate_jigo_metrics`). No new module — keeps cohesion with the existing aggregation pipeline.

---

### Task 1: Pure helper functions for per-move computation

**Files:**
- Modify: `katrain_debug/batch_eval.py` (add `import statistics`, two module-level helpers)
- Test: `tests/test_lambdago_metrics.py` (new)

This task adds `_winrate_for_player()` and `_candidate_median_loss()` as pure functions. They have no dependency on KaTrain runtime so they can be tested in isolation.

- [ ] **Step 1: Write failing tests for the helpers**

Create `tests/test_lambdago_metrics.py`:

```python
"""Unit tests for lambdago paper-derived metrics in katrain_debug.batch_eval.

All tests are pure-Python (no KataGo, no humanSL model) and operate on
dict literals shaped like KataGo candidate output and move_results rows.
"""
import pytest

from katrain.core.constants import ADDITIONAL_MOVE_ORDER
from katrain_debug.batch_eval import (
    _winrate_for_player,
    _candidate_median_loss,
)


class TestWinrateForPlayer:
    def test_black_perspective_passthrough(self):
        # wr_black = 0.7 → B sees 0.7
        assert _winrate_for_player(0.7, "B") == pytest.approx(0.7)

    def test_white_perspective_inverted(self):
        # wr_black = 0.7 → W sees 0.3
        assert _winrate_for_player(0.7, "W") == pytest.approx(0.3)

    def test_white_at_98_percent(self):
        # wr_black = 0.02 → W is at 98%
        assert _winrate_for_player(0.02, "W") == pytest.approx(0.98)


class TestCandidateMedianLoss:
    def _c(self, points_lost, order=0, prior=0.1):
        d = {"pointsLost": points_lost, "order": order}
        if prior is not None:
            d["prior"] = prior
        return d

    def test_basic_three_candidates(self):
        # losses [0.0, 1.0, 3.0] → median 1.0
        cands = [self._c(0.0), self._c(1.0, order=1), self._c(3.0, order=2)]
        assert _candidate_median_loss(cands) == pytest.approx(1.0)

    def test_excludes_raw_policy_candidates(self):
        # order >= ADDITIONAL_MOVE_ORDER must be filtered out
        cands = [
            self._c(0.0, order=0),
            self._c(1.0, order=1),
            self._c(99.0, order=ADDITIONAL_MOVE_ORDER),       # excluded
            self._c(99.0, order=ADDITIONAL_MOVE_ORDER + 5),   # excluded
        ]
        # Remaining losses [0.0, 1.0] → median 0.5
        assert _candidate_median_loss(cands) == pytest.approx(0.5)

    def test_excludes_candidates_without_prior(self):
        cands = [
            self._c(0.0, order=0, prior=None),  # no prior → excluded
            self._c(2.0, order=1),
            self._c(4.0, order=2),
        ]
        # Remaining losses [2.0, 4.0] → median 3.0
        assert _candidate_median_loss(cands) == pytest.approx(3.0)

    def test_returns_none_when_no_eligible_candidates(self):
        cands = [self._c(0.0, order=ADDITIONAL_MOVE_ORDER + 1)]
        assert _candidate_median_loss(cands) is None

    def test_no_clamping_negative_loss_preserved(self):
        # Negative pointsLost (player surprised KataGo by playing better than top)
        # must be preserved, not clamped to 0.
        cands = [self._c(-0.5), self._c(0.0, order=1), self._c(2.0, order=2)]
        # Median of [-0.5, 0.0, 2.0] = 0.0
        assert _candidate_median_loss(cands) == pytest.approx(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_lambdago_metrics.py -v`
Expected: ImportError (`_winrate_for_player`, `_candidate_median_loss` not defined).

- [ ] **Step 3: Implement the helpers**

Edit `katrain_debug/batch_eval.py`. Add `import statistics` near the top with the other imports:

```python
import math
import os
import statistics
import sys
import time
```

Then add the two helpers as module-level functions (place them just above `_aggregate_jigo_metrics()` so the aggregation helpers stay grouped):

```python
def _winrate_for_player(wr_black, player):
    """Convert KataGo's BLACK-perspective winrate to the given player's perspective.

    KataGo is configured with reportAnalysisWinratesAs=BLACK (engine.py:108),
    so all candidate winrates are from Black's viewpoint regardless of the player to move.
    """
    return wr_black if player == "B" else (1.0 - wr_black)


def _candidate_median_loss(cands):
    """Median pointsLost across visited candidates that have a policy prior assigned.

    Returns None if no eligible candidates. Does NOT clamp negative pointsLost
    (preserving the paper's signed effect ε(a) for Choice-vs-Median).
    """
    losses = [
        c["pointsLost"]
        for c in cands
        if c["order"] < ADDITIONAL_MOVE_ORDER and "prior" in c
    ]
    if not losses:
        return None
    return statistics.median(losses)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_lambdago_metrics.py -v`
Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add katrain_debug/batch_eval.py tests/test_lambdago_metrics.py
git commit -m "feat(lambdago): per-move helpers (winrate perspective, candidate median loss)"
```

---

### Task 2: `_aggregate_lambdago_metrics` — Choice-vs-Median portion

**Files:**
- Modify: `katrain_debug/batch_eval.py` (add `_aggregate_lambdago_metrics()`)
- Test: `tests/test_lambdago_metrics.py` (extend)

This task implements the Choice-vs-Median aggregation. Post-98% Slack is left for Task 3.

The function consumes a list of `move_results` rows (each containing `player`, `point_loss_raw` (unclamped pointsLost), `cand_median_loss`, plus the existing `point_loss`). The new fields will be plumbed into `move_results` in Task 4.

- [ ] **Step 1: Write failing tests for Choice-vs-Median aggregation**

Append to `tests/test_lambdago_metrics.py`:

```python
from katrain_debug.batch_eval import _aggregate_lambdago_metrics


def _row(player="B", point_loss_raw=0.0, cand_median_loss=0.0,
         point_loss=None, winrate_player=None):
    """Minimal move_result shorthand for lambdago aggregation tests."""
    return {
        "player": player,
        "point_loss_raw": point_loss_raw,
        "cand_median_loss": cand_median_loss,
        "point_loss": point_loss if point_loss is not None else max(0.0, point_loss_raw),
        "winrate_player": winrate_player,
        "move_num": 1,
    }


class TestAggregateChoiceVsMedian:
    def test_empty_input_returns_empty_dict(self):
        result = _aggregate_lambdago_metrics([])
        assert result == {}

    def test_overall_mean_basic(self):
        # gaps: -1.0, -0.5, 0.0 → mean -0.5
        rows = [
            _row(point_loss_raw=0.0, cand_median_loss=1.0),  # gap -1.0
            _row(point_loss_raw=0.5, cand_median_loss=1.0),  # gap -0.5
            _row(point_loss_raw=1.0, cand_median_loss=1.0),  # gap  0.0
        ]
        result = _aggregate_lambdago_metrics(rows)
        cvm = result["choice_vs_median"]
        assert cvm["overall"]["count"] == 3
        assert cvm["overall"]["mean"] == pytest.approx(-0.5)

    def test_negative_ratio_threshold(self):
        # gaps: -0.6 (counts), -0.4 (does not), -1.0 (counts), 0.5 (does not)
        # Threshold is gap < -0.5
        rows = [
            _row(point_loss_raw=0.0, cand_median_loss=0.6),   # gap -0.6 ✓
            _row(point_loss_raw=0.6, cand_median_loss=1.0),   # gap -0.4 ✗
            _row(point_loss_raw=0.0, cand_median_loss=1.0),   # gap -1.0 ✓
            _row(point_loss_raw=1.5, cand_median_loss=1.0),   # gap +0.5 ✗
        ]
        result = _aggregate_lambdago_metrics(rows)
        assert result["choice_vs_median"]["overall"]["negative_ratio"] == pytest.approx(0.5)

    def test_b_w_split(self):
        rows = [
            _row(player="B", point_loss_raw=0.0, cand_median_loss=2.0),  # B gap -2.0
            _row(player="B", point_loss_raw=0.0, cand_median_loss=2.0),  # B gap -2.0
            _row(player="W", point_loss_raw=1.0, cand_median_loss=1.0),  # W gap  0.0
        ]
        result = _aggregate_lambdago_metrics(rows)
        cvm = result["choice_vs_median"]
        assert cvm["B"]["count"] == 2
        assert cvm["B"]["mean"] == pytest.approx(-2.0)
        assert cvm["W"]["count"] == 1
        assert cvm["W"]["mean"] == pytest.approx(0.0)

    def test_skips_rows_with_missing_data(self):
        # Rows where cand_median_loss is None (e.g. no eligible candidates) are skipped.
        rows = [
            _row(point_loss_raw=0.0, cand_median_loss=None),
            _row(point_loss_raw=0.0, cand_median_loss=1.0),  # gap -1.0
        ]
        result = _aggregate_lambdago_metrics(rows)
        assert result["choice_vs_median"]["overall"]["count"] == 1
        assert result["choice_vs_median"]["overall"]["mean"] == pytest.approx(-1.0)

    def test_reference_block_included(self):
        rows = [_row(point_loss_raw=0.0, cand_median_loss=1.0)]
        result = _aggregate_lambdago_metrics(rows)
        assert result["reference"] == {
            "human_amateur_loss": 0.65,
            "ai_suspect_loss": 0.25,
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_lambdago_metrics.py::TestAggregateChoiceVsMedian -v`
Expected: ImportError or AttributeError on `_aggregate_lambdago_metrics`.

- [ ] **Step 3: Implement the aggregator (Choice-vs-Median only for now)**

Add this function to `katrain_debug/batch_eval.py`, immediately after `_aggregate_jigo_metrics()`:

```python
def _aggregate_lambdago_metrics(move_results):
    """Aggregate lambdago paper-derived metrics across move_results.

    Choice-vs-Median Gap (per overall/B/W):
        gap = point_loss_raw - cand_median_loss  (unclamped)
        Negative gap = AI-like (better than candidate median).

    Post-98% Slack: implemented in Task 3 (returns empty dict for now).

    Returns {} when no eligible rows are present.
    """
    if not move_results:
        return {}

    eligible = [m for m in move_results if m.get("cand_median_loss") is not None
                and m.get("point_loss_raw") is not None]
    if not eligible:
        return {}

    NEGATIVE_THRESHOLD = -0.5

    def _summarize(rows):
        gaps = [m["point_loss_raw"] - m["cand_median_loss"] for m in rows]
        n = len(gaps)
        return {
            "count": n,
            "mean": sum(gaps) / n,
            "negative_ratio": sum(1 for g in gaps if g < NEGATIVE_THRESHOLD) / n,
        }

    cvm = {"overall": _summarize(eligible)}
    for bw in ("B", "W"):
        group = [m for m in eligible if m["player"] == bw]
        if group:
            cvm[bw] = _summarize(group)

    return {
        "reference": {"human_amateur_loss": 0.65, "ai_suspect_loss": 0.25},
        "choice_vs_median": cvm,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_lambdago_metrics.py -v`
Expected: All TestWinrateForPlayer + TestCandidateMedianLoss + TestAggregateChoiceVsMedian PASS.

- [ ] **Step 5: Commit**

```bash
git add katrain_debug/batch_eval.py tests/test_lambdago_metrics.py
git commit -m "feat(lambdago): _aggregate_lambdago_metrics for Choice-vs-Median Gap"
```

---

### Task 3: Extend `_aggregate_lambdago_metrics` with Post-98% Slack

**Files:**
- Modify: `katrain_debug/batch_eval.py` (extend `_aggregate_lambdago_metrics()`)
- Test: `tests/test_lambdago_metrics.py` (extend)

- [ ] **Step 1: Write failing tests for Post-98% Slack**

Append to `tests/test_lambdago_metrics.py`:

```python
class TestAggregateSlack:
    def _row_slack(self, player, move_num, winrate_player, point_loss):
        return {
            "player": player,
            "move_num": move_num,
            "winrate_player": winrate_player,
            "point_loss": point_loss,
            "point_loss_raw": point_loss,
            # cand_median_loss must be present so the row is "eligible";
            # use a value such that the row also passes choice_vs_median filtering
            "cand_median_loss": 0.0,
        }

    def test_slack_detected_with_clear_pre_post(self):
        # B reaches 98% at move 3. pre = [0.2, 0.4] → 0.3, post = [0.8, 1.0] → 0.9
        # delta = +0.6
        rows = [
            self._row_slack("B", 1, 0.50, 0.2),
            self._row_slack("B", 2, 0.70, 0.4),
            self._row_slack("B", 3, 0.99, 0.8),  # first ≥ 0.98
            self._row_slack("B", 4, 0.99, 1.0),
        ]
        result = _aggregate_lambdago_metrics(rows)
        b_slack = result["post_98_slack"]["B"]
        assert b_slack["first_98_move"] == 3
        assert b_slack["n_pre"] == 2
        assert b_slack["n_post"] == 2
        assert b_slack["pre_98_avg_loss"] == pytest.approx(0.3)
        assert b_slack["post_98_avg_loss"] == pytest.approx(0.9)
        assert b_slack["slack_delta"] == pytest.approx(0.6)
        assert b_slack["low_sample"] is True  # n_post < 30

    def test_slack_not_reached_returns_none(self):
        rows = [
            self._row_slack("B", 1, 0.50, 0.2),
            self._row_slack("B", 2, 0.55, 0.3),
        ]
        result = _aggregate_lambdago_metrics(rows)
        assert result["post_98_slack"]["B"] is None

    def test_white_perspective_separate_from_black(self):
        # W reaches 98% at move 2; B never does.
        rows = [
            self._row_slack("W", 1, 0.50, 0.5),
            self._row_slack("W", 2, 0.98, 1.0),
            self._row_slack("B", 1, 0.50, 0.5),
            self._row_slack("B", 2, 0.02, 0.5),  # B's perspective is 0.02, not 0.98
        ]
        result = _aggregate_lambdago_metrics(rows)
        assert result["post_98_slack"]["W"] is not None
        assert result["post_98_slack"]["W"]["first_98_move"] == 2
        assert result["post_98_slack"]["B"] is None

    def test_low_sample_flag_false_when_n_post_30_or_more(self):
        rows = [self._row_slack("B", i, 0.50, 0.3) for i in range(1, 11)]   # 10 pre
        rows += [self._row_slack("B", i, 0.99, 0.5) for i in range(11, 41)] # 30 post
        result = _aggregate_lambdago_metrics(rows)
        assert result["post_98_slack"]["B"]["low_sample"] is False

    def test_slack_skips_rows_with_missing_winrate(self):
        # winrate_player=None rows must be ignored entirely (e.g. legacy data).
        rows = [
            self._row_slack("B", 1, None, 0.2),
            self._row_slack("B", 2, 0.99, 0.5),
            self._row_slack("B", 3, 0.99, 1.0),
        ]
        result = _aggregate_lambdago_metrics(rows)
        # After filtering: move 2 is the first ≥ 0.98, n_pre=0, n_post=2 → return None
        # (no pre data → cannot compute delta → return None)
        assert result["post_98_slack"]["B"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_lambdago_metrics.py::TestAggregateSlack -v`
Expected: KeyError on `result["post_98_slack"]`.

- [ ] **Step 3: Extend the aggregator with slack computation**

Replace the `return` statement at the end of `_aggregate_lambdago_metrics()` with the following block (and add helpers above the return):

```python
    SLACK_LOW_SAMPLE_THRESHOLD = 30

    def _slack_for_player(player):
        rows = [m for m in move_results
                if m.get("player") == player
                and m.get("winrate_player") is not None
                and m.get("point_loss") is not None]
        if not rows:
            return None

        first_98 = None
        for m in rows:
            if m["winrate_player"] >= 0.98:
                first_98 = m["move_num"]
                break
        if first_98 is None:
            return None

        pre = [m["point_loss"] for m in rows if m["move_num"] < first_98]
        post = [m["point_loss"] for m in rows if m["move_num"] >= first_98]
        if not pre or not post:
            return None

        pre_avg = sum(pre) / len(pre)
        post_avg = sum(post) / len(post)
        return {
            "first_98_move": first_98,
            "n_pre": len(pre),
            "n_post": len(post),
            "low_sample": len(post) < SLACK_LOW_SAMPLE_THRESHOLD,
            "pre_98_avg_loss": pre_avg,
            "post_98_avg_loss": post_avg,
            "slack_delta": post_avg - pre_avg,
        }

    return {
        "reference": {"human_amateur_loss": 0.65, "ai_suspect_loss": 0.25},
        "choice_vs_median": cvm,
        "post_98_slack": {
            "B": _slack_for_player("B"),
            "W": _slack_for_player("W"),
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_lambdago_metrics.py -v`
Expected: All tests PASS (helpers + Choice-vs-Median + Slack).

- [ ] **Step 5: Commit**

```bash
git add katrain_debug/batch_eval.py tests/test_lambdago_metrics.py
git commit -m "feat(lambdago): Post-98% Slack detection in _aggregate_lambdago_metrics"
```

---

### Task 4: Wire `batch_evaluate()` to collect new per-move fields and return aggregate

**Files:**
- Modify: `katrain_debug/batch_eval.py:147-186` (extend per-move dict, call new aggregator)

This task plumbs `winrate_player`, `point_loss_raw`, `cand_median_loss`, `choice_vs_median` into `move_results`, and adds `stats["lambdago_metrics"]` to the returned dict. Existing fields are unchanged.

- [ ] **Step 1: Read current `batch_evaluate()` per-move loop**

Open `katrain_debug/batch_eval.py` and locate lines 147-186 (the `move_results.append({...})` block and the post-loop aggregation in `_aggregate_stats` callsite). The next step modifies these.

- [ ] **Step 2: Add the new per-move fields**

In `katrain_debug/batch_eval.py`, replace this block (currently around lines 130-164):

```python
            # 選択手の損失を計算
            selected_info = next((d for d in cands if d["move"] == selected_gtp), None)
            point_loss = max(0.0, selected_info["pointsLost"]) if selected_info else None
```

with:

```python
            # 選択手の損失を計算（クランプ済み: 既存ユーザー向け / 生: lambdago 用）
            selected_info = next((d for d in cands if d["move"] == selected_gtp), None)
            if selected_info is not None:
                point_loss_raw = selected_info["pointsLost"]
                point_loss = max(0.0, point_loss_raw)
            else:
                point_loss_raw = None
                point_loss = None

            # lambdago 用: 候補手の median 損失と 打つ側視点 winrate
            # parent_node.winrate は手を打つ前の root winrate（黒視点固定）
            cand_median_loss = _candidate_median_loss(cands)
            wr_black_root = parent_node.winrate
            winrate_player = (
                _winrate_for_player(wr_black_root, player)
                if wr_black_root is not None else None
            )
```

Then in the `move_results.append({...})` dict immediately below, add three new keys (place them after `"point_loss": point_loss,`):

```python
                "point_loss": point_loss,
                "point_loss_raw": point_loss_raw,
                "cand_median_loss": cand_median_loss,
                "winrate_player": winrate_player,
                "choice_vs_median": (
                    point_loss_raw - cand_median_loss
                    if point_loss_raw is not None and cand_median_loss is not None
                    else None
                ),
```

- [ ] **Step 3: Hook the aggregator into the returned `stats` dict**

Find the existing block (around lines 168-175):

```python
        # 集計
        stats = _aggregate_stats(move_results)
        if strategy_name == "jigo":
            stats["jigo_metrics"] = _aggregate_jigo_metrics(
                move_results,
                target_score=ai_settings.get("target_score", 0.5),
                target_score_max=ai_settings.get("target_score_max", 10.0),
            )
```

and add one line after the `if strategy_name == "jigo":` block:

```python
        # 集計
        stats = _aggregate_stats(move_results)
        if strategy_name == "jigo":
            stats["jigo_metrics"] = _aggregate_jigo_metrics(
                move_results,
                target_score=ai_settings.get("target_score", 0.5),
                target_score_max=ai_settings.get("target_score_max", 10.0),
            )
        stats["lambdago_metrics"] = _aggregate_lambdago_metrics(move_results)
```

- [ ] **Step 4: Run unit tests + run a smoke `--batch` invocation**

```bash
pytest tests/test_lambdago_metrics.py tests/test_batch_eval_jigo.py -v
```
Expected: All PASS.

Then a smoke run (requires KataGo + humanSL; OK to skip if unavailable):

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --strategy hunt --batch \
  --move-range 1-30 --output json 2>/dev/null | python -c "import sys,json; \
d=json.loads(sys.stdin.read()); print('lambdago_metrics:', json.dumps(d['stats'].get('lambdago_metrics'), indent=2))"
```
Expected: `lambdago_metrics` block printed with `choice_vs_median.overall` populated.

- [ ] **Step 5: Commit**

```bash
git add katrain_debug/batch_eval.py
git commit -m "feat(lambdago): integrate Choice-vs-Median and Slack into batch_evaluate output"
```

---

### Task 5: Text output formatter in `cli.py`

**Files:**
- Modify: `katrain_debug/cli.py:145-162` (add a new block after Jigo Metrics, before the `return`)

- [ ] **Step 1: Add the text formatter block**

In `katrain_debug/cli.py`, find the existing Jigo Metrics block (around line 145) and add a new block immediately after it (just before the `return "\n".join(lines)` of `format_batch_text`):

```python
    # Lambdago Metrics ブロック（全戦略で常に表示）
    lambdago_metrics = stats.get("lambdago_metrics")
    if lambdago_metrics:
        lines.append("--- Lambdago Metrics (paper-derived) ---")
        ref = lambdago_metrics["reference"]
        lines.append(
            f"  Reference: human amateur ≈ -{ref['human_amateur_loss']} mean loss; "
            f"AI suspect ≈ -{ref['ai_suspect_loss']}"
        )
        lines.append("")

        lines.append("  Choice-vs-Median Gap (lower = more AI-like):")
        cvm = lambdago_metrics["choice_vs_median"]
        for key in ("overall", "B", "W"):
            if key not in cvm:
                continue
            block = cvm[key]
            label = {"overall": "Overall", "B": "Black  ", "W": "White  "}[key]
            lines.append(
                f"    {label}: {block['mean']:+.2f}  "
                f"(n={block['count']}, neg_ratio={block['negative_ratio']:.0%})"
            )
        lines.append("")

        lines.append("  Post-98% Slack (positive delta = sloppy after winning):")
        slack = lambdago_metrics["post_98_slack"]
        for player in ("B", "W"):
            label = {"B": "Black", "W": "White"}[player]
            block = slack.get(player)
            if block is None:
                lines.append(f"    {label}: not reached")
                continue
            sample_marker = " (low N)" if block["low_sample"] else ""
            lines.append(
                f"    {label}: pre={block['pre_98_avg_loss']:.2f}  "
                f"post={block['post_98_avg_loss']:.2f}  "
                f"delta={block['slack_delta']:+.2f}"
            )
            lines.append(
                f"           reached at move {block['first_98_move']} "
                f"(n_pre={block['n_pre']}, n_post={block['n_post']}{sample_marker})"
            )
        lines.append("")
```

- [ ] **Step 2: Run a smoke `--batch` text invocation**

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --strategy hunt --batch \
  --move-range 1-30 --output text 2>/dev/null | grep -A 20 "Lambdago Metrics"
```
Expected: Lambdago Metrics block visible with sensible numbers.

- [ ] **Step 3: Commit**

```bash
git add katrain_debug/cli.py
git commit -m "feat(lambdago): text formatter for Lambdago Metrics block in --batch output"
```

---

### Task 6: Regression check + CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md` (add 2-3 lines under the `--batch` description)

- [ ] **Step 1: Run regression diff (existing fields must be unchanged)**

Generate a baseline before the implementation by checking out HEAD~6 (before this feature) into a temp file is overkill — instead inspect a current json output and verify that legacy keys (`stats.overall.mean_ptloss`, `stats.B`, `stats.W`, `jigo_metrics`, per-move fields) have unchanged values for a deterministic strategy.

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --strategy jigo --batch \
  --move-range 1-30 --output json 2>/dev/null > /tmp/lambdago_after.json
python -c "import json; d=json.load(open('/tmp/lambdago_after.json')); \
print('legacy keys present:', 'overall' in d['stats'], \
'jigo_metrics' in d['stats'], 'lambdago_metrics' in d['stats']); \
print('per-move keys:', sorted(d['moves'][0].keys()))"
```
Expected: `True True True`; per-move keys include all legacy fields plus `point_loss_raw`, `cand_median_loss`, `winrate_player`, `choice_vs_median`.

(A full pre/post diff against an earlier checkout is optional — current change adds keys only, doesn't modify existing ones.)

- [ ] **Step 2: Run the full test suite to catch indirect breakage**

```bash
pytest tests/ --ignore=tests/test_ai.py -q
```
Expected: All tests pass.

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`, locate the section describing `--batch` (search for `バッチ評価モード`). Add a new sub-bullet after the existing description of `--batch` output:

Current text (around the `Notable Divergences` mention):

```markdown
出力: Settings（パラメータ値）、Aggregate Stats（Overall/B/W/Opening/Middle/Endgame別の Top1一致率・Top5一致率・平均損失・正確度）、Notable Divergences（損失2.0超の手一覧）。`--output json` で全手の詳細をJSON出力。KataGoは1回だけ起動し、205手の局で約10分。
```

Add immediately after it:

```markdown
追加メトリック（全戦略）: Lambdago Metrics ブロックに **Choice-vs-Median Gap**（選択手 vs 候補手中央値の損失差、負ほど AI 寄り）と **Post-98% Slack**（勝率 98% 到達後の平均損失変化、正なら勝勢で手が緩むサイン）を表示。lambdago 論文 (arXiv:2009.01606) 由来の診断指標で、jigo モードの人間らしさ評価に使用。詳細は `docs/superpowers/specs/2026-04-14-lambdago-cheat-metrics-design.md`。
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md に Lambdago Metrics ブロックの説明を追加"
```

---

### Task 7: Sanity check on real SGFs (manual validation)

**Files:**
- None to modify. This task validates that values match expectations.

This step verifies the spec's "数値の妥当性検証" requirement. If results are surprising, **revisit the candidate-filter logic in `_candidate_median_loss()` before declaring done**.

- [ ] **Step 1: AI-strong baseline check (KataGo's own top moves)**

Find or generate a SGF where one side plays exclusively KataGo top moves (existing `tests/data/` may have one; otherwise pick any pro game where one side is strong, e.g. an AI-vs-AI training game).

```bash
python -m katrain_debug --sgf <AI_HEAVY_SGF> --strategy jigo --batch \
  --player B --output text 2>/dev/null | grep -A 10 "Lambdago Metrics"
```
Expected: `Choice-vs-Median Gap` Black mean strongly negative (< -0.5) and `negative_ratio` high (> 50%). If gap is near 0, the median calculation likely includes too few candidates — check `_candidate_median_loss()`.

- [ ] **Step 2: Weak human baseline check**

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --strategy jigo --batch \
  --player W --output text 2>/dev/null | grep -A 10 "Lambdago Metrics"
```
Expected: `Choice-vs-Median Gap` mean closer to 0 (between -0.5 and +0.5), `negative_ratio` lower than the AI-heavy case.

- [ ] **Step 3: Jigo圧勝 SGF — Slack signal check**

Pick a SGF from `docs/superpowers/specs/calibration-data/` where jigo wins decisively (look for one where `mean_lead` was high in prior calibration runs).

```bash
python -m katrain_debug --sgf <CALIBRATION_SGF> --strategy jigo --batch \
  --output text 2>/dev/null | grep -A 15 "Post-98% Slack"
```
Expected: For the winning side, `Post-98% Slack delta` is positive (likely +0.3 or higher) reflecting the recent `jigo_large_lead_max_loss` relaxation. This is the diagnostic value of the metric.

- [ ] **Step 4: Document findings (no code change)**

If all three sanity checks return values matching expectations, no further action. If any value contradicts the design assumption, open a follow-up note (informal, no commit needed) describing what diverged. The plan is complete.

- [ ] **Step 5: Final commit (only if any sanity-check tweak was needed)**

If Steps 1-3 revealed a needed adjustment (e.g. filter tweak in `_candidate_median_loss`), make the change with a focused test and commit:

```bash
git add <files>
git commit -m "fix(lambdago): adjust <thing> based on real-SGF validation"
```

Otherwise, no commit — feature is complete after Task 6.
