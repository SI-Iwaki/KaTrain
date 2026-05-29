# Jigo 三連星強制オプション 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** jigo モードに「序盤の星打ち強制」オプション `jigo_force_sanrensei`（19路盤のみ・黒=三連星/白=2連星）を追加し、設定画面のチェックボックスで切り替え可能にする。

**Architecture:** 星打ち布石の対象座標計算を `ai.py` の純関数ヘルパーに抽出（アプローチA）。`HumanStyleStrategy`（既存2連星）と `JigoStrategy`（新規）が共有する。Jigo は Stage 1（humanPolicy 取得）直後に強制対象を計算し、対象があれば Stage 2 をスキップして即着手する。

**Tech Stack:** Python 3.12 / Kivy / pytest。ヘルパーは Kivy 非依存の純関数として実装しユニットテスト可能にする（`Move` は `katrain.core.sgf_parser` 由来で Kivy 非依存）。

設計書: `docs/superpowers/specs/2026-05-30-jigo-force-sanrensei-design.md`

---

## ファイル構成

| ファイル | 責務 | 変更 |
|------|------|------|
| `katrain/core/ai.py` | `_get_star_lines` / `_compute_star_opening_targets` / `_select_star_target` 新設、HumanStyle 置換、Jigo 短絡挿入 | 修正 |
| `tests/test_star_opening.py` | ヘルパー3関数のユニットテスト | 新規 |
| `katrain/core/constants.py` | `AI_OPTION_VALUES` / `AI_OPTION_ORDER` へ登録 | 修正 |
| `katrain/gui/popups.py` | `max_options` 16→17 | 修正 |
| `katrain/config.json` | `ai:jigo` にデフォルト値 | 修正 |
| `C:\Users\iwaki\.katrain\config.json` | ユーザーローカルにキー追加（**メインセッションで直接 Edit**） | 修正 |
| `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po` | 短ラベル＋説明文追記 | 修正 |
| `.claude/rules/ai-parameters.md` / `CLAUDE.md` | パラメータ表追記（**rules はサブエージェント経由で編集**） | 修正 |

---

## Task 1: `_get_star_lines` ヘルパー

19路盤の4辺それぞれの星点ライン（隅2＋中辺星1 の3点）を返す純関数。中辺の星が存在しない盤面（13/9路等）では空リストを返す。

**Files:**
- Modify: `katrain/core/ai.py`（`_diagonal_star` 関数の直後、`ai.py:2716` 付近に追加）
- Test: `tests/test_star_opening.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

新規ファイル `tests/test_star_opening.py`:

```python
# tests/test_star_opening.py
"""星打ち布石ヘルパー（_get_star_lines / _compute_star_opening_targets / _select_star_target）の純関数テスト。"""
import pytest

from katrain.core.ai import _get_star_lines
from katrain.core.game import Move


class TestGetStarLines:
    def test_19x19_returns_four_three_point_lines(self):
        lines = _get_star_lines((19, 19))
        assert len(lines) == 4
        for line in lines:
            assert len(line) == 3
        # 各ラインがコリニア（行または列が一定）
        for line in lines:
            xs = {p[0] for p in line}
            ys = {p[1] for p in line}
            assert len(xs) == 1 or len(ys) == 1

    def test_19x19_contains_expected_hoshi(self):
        lines = _get_star_lines((19, 19))
        all_points = {p for line in lines for p in line}
        # 隅4 + 中辺4 = 8点（隅は2ラインで共有されるため集合では8点）
        expected = {
            (3, 3), (9, 3), (15, 3),   # 下辺
            (3, 15), (9, 15), (15, 15),  # 上辺
            (3, 9), (15, 9),           # 左右の中辺星
        }
        assert all_points == expected

    def test_13x13_returns_empty(self):
        assert _get_star_lines((13, 13)) == []

    def test_9x9_returns_empty(self):
        assert _get_star_lines((9, 9)) == []
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_star_opening.py::TestGetStarLines -v`
Expected: FAIL（`ImportError: cannot import name '_get_star_lines'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/ai.py` の `_diagonal_star`（`ai.py:2710-2715`）の直後に追加:

```python
def _get_star_lines(board_size):
    """19路盤の4辺それぞれの星点ライン（隅2 + 中辺星1 の3点コリニア集合）を返す。

    中辺の星が存在しない盤面（13/9路等）では空リストを返す（= n=3 三連星は19路専用）。
    """
    bx, by = board_size
    if not (bx == 19 and by == 19):
        return []
    near_x, far_x = 3, bx - 4   # 3, 15
    near_y, far_y = 3, by - 4   # 3, 15
    mid_x, mid_y = bx // 2, by // 2  # 9, 9
    bottom = [(near_x, near_y), (mid_x, near_y), (far_x, near_y)]
    top    = [(near_x, far_y),  (mid_x, far_y),  (far_x, far_y)]
    left   = [(near_x, near_y), (near_x, mid_y), (near_x, far_y)]
    right  = [(far_x, near_y),  (far_x, mid_y),  (far_x, far_y)]
    return [bottom, top, left, right]
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_star_opening.py::TestGetStarLines -v`
Expected: PASS（4 件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_star_opening.py
git commit -m "feat(jigo): 星点ライン算出ヘルパー _get_star_lines を追加"
```

---

## Task 2: `_compute_star_opening_targets` ヘルパー（n=2 / n=3）

星打ち強制の対象座標集合を返す純関数。`n=2` は既存2連星ロジックの移植（挙動不変）、`n=3` は新規の三連星ロジック。

**Files:**
- Modify: `katrain/core/ai.py`（`_get_star_lines` の直後に追加）
- Test: `tests/test_star_opening.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_star_opening.py` に追記:

```python
from katrain.core.ai import _compute_star_opening_targets


def _stones(spec):
    """[("B",(3,3)), ("W",(15,15))] 形式から Move リストを生成。"""
    return [Move(coords=c, player=p) for p, c in spec]


class TestComputeStarOpeningTargetsN2:
    """n=2: 既存2連星ロジックの移植（挙動不変）。"""

    def test_black_no_stones_returns_all_corners(self):
        targets = _compute_star_opening_targets((19, 19), _stones([]), "B", 2)
        assert targets == {(3, 3), (15, 3), (3, 15), (15, 15)}

    def test_white_with_opponent_star_plays_diagonal(self):
        # 黒が (3,3) → 白は対角 (15,15)
        stones = _stones([("B", (3, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "W", 2)
        assert targets == {(15, 15)}

    def test_one_ai_star_targets_same_side_corners(self):
        # 黒が (3,3) を持つ → 同辺（同行 or 同列）の隅星
        stones = _stones([("B", (3, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 2)
        assert targets == {(15, 3), (3, 15)}

    def test_two_ai_stars_stops(self):
        stones = _stones([("B", (3, 3)), ("B", (15, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 2)
        assert targets == set()

    def test_n2_works_on_13x13(self):
        # n=2 は隅星のみなので13路でも動作する
        targets = _compute_star_opening_targets((13, 13), _stones([]), "B", 2)
        assert targets == {(3, 3), (9, 3), (3, 9), (9, 9)}


class TestComputeStarOpeningTargetsN3:
    """n=3: 三連星（19路専用）。"""

    def test_black_no_stones_returns_corners_only(self):
        targets = _compute_star_opening_targets((19, 19), _stones([]), "B", 3)
        assert targets == {(3, 3), (15, 3), (3, 15), (15, 15)}

    def test_one_corner_stone_extends_both_lines(self):
        # (3,3) は下辺と左辺に属する → 両ラインの空き星点
        stones = _stones([("B", (3, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == {(9, 3), (15, 3), (3, 9), (3, 15)}

    def test_two_corners_same_side_completes_with_mid(self):
        # 下辺の両隅 → 中辺星 (9,3) で三連星完成
        stones = _stones([("B", (3, 3)), ("B", (15, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == {(9, 3)}

    def test_corner_and_mid_completes_with_far_corner(self):
        # 下辺の隅+中辺星 → 残り隅 (15,3)
        stones = _stones([("B", (3, 3)), ("B", (9, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == {(15, 3)}

    def test_completed_line_stops(self):
        # 下辺3点完成 → 強制停止（空集合）
        stones = _stones([("B", (3, 3)), ("B", (9, 3)), ("B", (15, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == set()

    def test_blocked_line_excluded(self):
        # 黒 (3,3) を持つが、下辺の (15,3) に白 → 下辺は除外、左辺のみ
        stones = _stones([("B", (3, 3)), ("W", (15, 3))])
        targets = _compute_star_opening_targets((19, 19), stones, "B", 3)
        assert targets == {(3, 9), (3, 15)}

    def test_n3_returns_empty_on_13x13(self):
        targets = _compute_star_opening_targets((13, 13), _stones([]), "B", 3)
        assert targets == set()
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_star_opening.py::TestComputeStarOpeningTargetsN2 tests/test_star_opening.py::TestComputeStarOpeningTargetsN3 -v`
Expected: FAIL（`ImportError: cannot import name '_compute_star_opening_targets'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/ai.py` の `_get_star_lines` の直後に追加:

```python
def _compute_star_opening_targets(board_size, stones, ai_player, n):
    """星打ち布石で次に打つべき星点座標の集合を返す。

    n=2: 隅4星のみを使う2連星ロジック（HumanStyle 既存挙動の移植）。
    n=3: 側辺ライン（隅2+中辺星）を使う三連星ロジック（19路専用）。
    強制不要・完成済み・盤面非対応なら空集合を返す。
    """
    opp = "W" if ai_player == "B" else "B"
    stones_by_pos = {m.coords: m.player for m in stones if m.coords is not None}
    corner_stars = _get_corner_star_points(board_size)

    if n == 2:
        ai_stars = [c for c in corner_stars if stones_by_pos.get(c) == ai_player]
        opp_stars = [c for c in corner_stars if stones_by_pos.get(c) == opp]
        empty = {c for c in corner_stars if c not in stones_by_pos}
        if len(ai_stars) == 0 and empty:
            if opp_stars:
                diag = _diagonal_star(opp_stars[0], corner_stars)
                return {diag} if diag and diag in empty else set(empty)
            return set(empty)
        if len(ai_stars) == 1 and empty:
            first = ai_stars[0]
            same_side = {c for c in corner_stars if c[0] == first[0] or c[1] == first[1]} - {first}
            return same_side & empty
        return set()

    if n == 3:
        lines = _get_star_lines(board_size)
        if not lines:
            return set()
        # いずれかのラインが既に完成していれば強制終了
        for line in lines:
            if sum(1 for p in line if stones_by_pos.get(p) == ai_player) >= 3:
                return set()
        # 有効ライン（相手石が乗っていない）を抽出
        viable = []  # (ai_count, empty_points)
        for line in lines:
            if any(stones_by_pos.get(p) == opp for p in line):
                continue
            ai_count = sum(1 for p in line if stones_by_pos.get(p) == ai_player)
            empty_pts = {p for p in line if p not in stones_by_pos}
            viable.append((ai_count, empty_pts))
        if not viable:
            return set()
        max_ai = max(c for c, _ in viable)
        if max_ai == 0:
            # AI 石ゼロ → 有効ライン上の空き隅星から開始（中辺星は最初に出さない）
            starts = set()
            for _, empty_pts in viable:
                starts |= {p for p in empty_pts if p in corner_stars}
            return starts
        targets = set()
        for ai_count, empty_pts in viable:
            if ai_count == max_ai:
                targets |= empty_pts
        return targets

    return set()
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_star_opening.py -v`
Expected: PASS（Task1 の 4 件 + 本タスクの 12 件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_star_opening.py
git commit -m "feat(jigo): 星打ち対象算出ヘルパー _compute_star_opening_targets を追加"
```

---

## Task 3: `_select_star_target` ヘルパー

target 集合から humanPolicy 最大の座標を決定的に選ぶ純関数。Jigo の短絡選択で使用する。

**Files:**
- Modify: `katrain/core/ai.py`（`_compute_star_opening_targets` の直後）
- Test: `tests/test_star_opening.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_star_opening.py` に追記:

```python
from katrain.core.ai import _select_star_target


class TestSelectStarTarget:
    def _hp_array(self, board_size, weights):
        """weights: {coord: value} から humanPolicy フラット配列（pass 含む len = bx*by+1）を生成。"""
        bx, by = board_size
        arr = [0.0] * (bx * by + 1)
        for (x, y), v in weights.items():
            arr[(by - y - 1) * bx + x] = v
        return arr

    def test_picks_highest_human_policy(self):
        bs = (19, 19)
        hp = self._hp_array(bs, {(3, 3): 0.1, (15, 3): 0.5, (3, 15): 0.2})
        chosen = _select_star_target({(3, 3), (15, 3), (3, 15)}, hp, bs)
        assert chosen == (15, 3)

    def test_ties_resolve_to_smallest_coord(self):
        # 全 hp=0（modern_style で星点が 0 のケース）→ 座標昇順で最小
        bs = (19, 19)
        hp = self._hp_array(bs, {})
        chosen = _select_star_target({(15, 3), (3, 3), (3, 15)}, hp, bs)
        assert chosen == (3, 3)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_star_opening.py::TestSelectStarTarget -v`
Expected: FAIL（`ImportError: cannot import name '_select_star_target'`）

- [ ] **Step 3: 最小実装を書く**

`katrain/core/ai.py` の `_compute_star_opening_targets` の直後に追加:

```python
def _select_star_target(target_stars, human_policy, board_size):
    """target_stars の中から humanPolicy 最大の座標を返す。同値は座標昇順で決定的に選ぶ。

    humanPolicy が全て 0（modern_style で星点に 0 が返るケース）でも強制するため、
    hp による足切りは行わず最小座標を返す。
    """
    bx, by = board_size

    def hp(coord):
        x, y = coord
        idx = (by - y - 1) * bx + x
        return human_policy[idx] if 0 <= idx < len(human_policy) else 0.0

    # 座標昇順で走査し max を取る → 同値時は最小座標が選ばれる（決定的）
    return max(sorted(target_stars), key=hp)
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_star_opening.py::TestSelectStarTarget -v`
Expected: PASS（2 件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_star_opening.py
git commit -m "feat(jigo): 星点 target 選択ヘルパー _select_star_target を追加"
```

---

## Task 4: `HumanStyleStrategy` を共有ヘルパーへ置換（挙動不変）

既存 `force_star_opening` のインライン target 計算をヘルパー呼び出しに置換する。返り値適用部（moves 制限＋hp=0 フォールバック生成）は現行コードを維持。

**Files:**
- Modify: `katrain/core/ai.py:2975-3021`

- [ ] **Step 1: 回帰テストが Task 2 の n=2 テストでカバーされていることを確認**

n=2 のロジックは `TestComputeStarOpeningTargetsN2` で網羅済み（黒0/1/2石・白対角・13路）。`generate_move` 全体はモデルが必要なためユニットテスト対象外。置換は target 計算部のみで適用部は不変のため、n=2 テストが回帰の担保となる。

Run: `python -m pytest tests/test_star_opening.py::TestComputeStarOpeningTargetsN2 -v`
Expected: PASS（5 件）

- [ ] **Step 2: 置換を実装する**

`katrain/core/ai.py:2975-3021` の現行ブロック:

```python
        # 2連星（序盤星打ち強制）フィルタ
        if self.settings.get("force_star_opening", False) and moves:
            corner_stars = _get_corner_star_points(board_size)
            stones_by_pos = {m.coords: m.player for m in self.game.stones}
            ai_player = self.cn.next_player
            opponent_player = "W" if ai_player == "B" else "B"

            ai_stars_played = [c for c in corner_stars if stones_by_pos.get(c) == ai_player]
            opp_stars_played = [c for c in corner_stars if stones_by_pos.get(c) == opponent_player]
            empty_stars = {c for c in corner_stars if c not in stones_by_pos}

            target_stars = set()

            if len(ai_stars_played) == 0 and empty_stars:
                if opp_stars_played:
                    # 相手が星を打っていたら対角線上に打つ（白番の対角戦略）
                    diag = _diagonal_star(opp_stars_played[0], corner_stars)
                    target_stars = {diag} if diag and diag in empty_stars else empty_stars
                else:
                    # 相手がまだ星に打っていない（黒番の1手目等）→ 任意の隅
                    target_stars = empty_stars
            elif len(ai_stars_played) == 1 and empty_stars:
                # 自分の1手目と同じ辺の星点に限定（2連星を完成させる）
                first = ai_stars_played[0]
                same_side = {c for c in corner_stars if c[0] == first[0] or c[1] == first[1]} - {first}
                target_stars = same_side & empty_stars
            # len(ai_stars_played) >= 2 → 強制しない（target_stars = {} のまま）

            if target_stars:
```

を次へ置換（`if target_stars:` 以降〜ログ出力までの適用部は**そのまま残す**）:

```python
        # 2連星（序盤星打ち強制）フィルタ
        if self.settings.get("force_star_opening", False) and moves:
            ai_player = self.cn.next_player
            target_stars = _compute_star_opening_targets(
                board_size, self.game.stones, ai_player, 2
            )

            if target_stars:
```

置換後、`if target_stars:` ブロック内（`ai.py:3003-3021` 相当）は変更しない。なお置換後はブロック内のログ出力 `ai_stars=...`/`opp_stars=...` が削除した変数を参照するため、ログ行を次へ簡略化する:

```python
                if star_moves:
                    moves = star_moves
                    self.game.katrain.log(
                        f"[HumanStyleStrategy] force_star_opening: "
                        f"targets={[f'({c[0]},{c[1]})' for c in target_stars]}",
                        OUTPUT_DEBUG,
                    )
```

- [ ] **Step 3: import / 構文チェック**

Run: `python -c "import katrain.core.ai"`
Expected: エラーなし（終了コード 0）

- [ ] **Step 4: 全ヘルパーテストが通ることを確認**

Run: `python -m pytest tests/test_star_opening.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "refactor(ai): HumanStyle の2連星ロジックを共有ヘルパーへ置換"
```

---

## Task 5: `JigoStrategy` に星打ち強制の短絡を挿入

Stage 1（humanPolicy 取得）直後に強制対象を計算し、対象があれば Stage 2 をスキップして即着手する。

**Files:**
- Modify: `katrain/core/ai.py`（`human_policy = stage1_analysis["humanPolicy"]` のログ出力直後 = `ai.py:1115` の後、Stage 2 ブロック `ai.py:1117` の前）

- [ ] **Step 1: 挿入位置を確認する**

`ai.py:1111-1117` 付近:

```python
        human_policy = stage1_analysis["humanPolicy"]
        self.game.katrain.log(
            f"[JigoStrategy] Stage1 query complete (humanPolicy len={len(human_policy)})",
            OUTPUT_DEBUG,
        )

        # ---- Stage 2: クリーンクエリ（scoreLead 用） ----
```

- [ ] **Step 2: 短絡ブロックを挿入する**

`self.game.katrain.log(... humanPolicy len ...)` の閉じ括弧直後、`# ---- Stage 2` コメントの前に追加:

```python
        # ---- 星打ち強制（19路盤・序盤のみ。黒=三連星 / 白=2連星） ----
        if self.settings.get("jigo_force_sanrensei", False) and \
                self.game.board_size[0] == 19 and self.game.board_size[1] == 19:
            n_star = 3 if self.cn.next_player == "B" else 2
            target_stars = _compute_star_opening_targets(
                self.game.board_size, self.game.stones, self.cn.next_player, n_star
            )
            if target_stars:
                coords = _select_star_target(target_stars, human_policy, self.game.board_size)
                aimove = Move(coords, player=self.cn.next_player)
                self.game.katrain.log(
                    f"[JigoStrategy] force_sanrensei: n={n_star}, "
                    f"targets={sorted(target_stars)}, chose={coords}",
                    OUTPUT_DEBUG,
                )
                return aimove, f"Jigo force star opening (n={n_star}): {aimove.gtp()}"
```

> 注: 短絡時は Stage 2・target 選択・deception を経由しない。`self.game._jigo_last_current_lead` は更新せず、`last_decision_info.score_lead` は `None` のまま（序盤の星打ちは損失≒0 で目標目差ロジックと非干渉のため問題なし）。

- [ ] **Step 3: import / 構文チェック**

Run: `python -c "import katrain.core.ai"`
Expected: エラーなし（終了コード 0）

- [ ] **Step 4: 既存 jigo テストが壊れていないことを確認**

Run: `python -m pytest tests/test_jigo.py tests/test_jigo_deception.py tests/test_star_opening.py -v`
Expected: PASS（全件。短絡は設定 OFF 時に発動しないため既存テストに影響なし）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat(jigo): 星打ち強制 jigo_force_sanrensei の短絡ロジックを追加"
```

---

## Task 6: `constants.py` へ設定登録

**Files:**
- Modify: `katrain/core/constants.py:206`（`AI_OPTION_VALUES` の jigo 群末尾）、`katrain/core/constants.py:269`（`AI_OPTION_ORDER` の jigo 群末尾）

- [ ] **Step 1: `AI_OPTION_VALUES` に追加**

`katrain/core/constants.py:206` の `"jigo_deception_13_phase2_target": [-0.5, -1.0, -1.5, -2.0],` の直後（`}` の前）に追加:

```python
    "jigo_force_sanrensei": "bool",
```

- [ ] **Step 2: `AI_OPTION_ORDER` に追加**

`katrain/core/constants.py:269` の `"jigo_deception_13_phase2_target": 15,` の直後（`}` の前）に追加:

```python
    "jigo_force_sanrensei": 16,
```

- [ ] **Step 3: import / 構文チェック**

Run: `python -c "import katrain.core.constants"`
Expected: エラーなし（終了コード 0）

- [ ] **Step 4: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat(jigo): jigo_force_sanrensei を AI設定定義に登録"
```

---

## Task 7: `popups.py` の `max_options` を引き上げ

jigo は既に 16 項目（上限）を使用。17 項目目を表示するため `max_options` を 17 にする。

**Files:**
- Modify: `katrain/gui/popups.py:398`

- [ ] **Step 1: 現在値を確認する**

`katrain/gui/popups.py:398`:

```python
    max_options = NumericProperty(16)
```

- [ ] **Step 2: 17 に変更する**

```python
    max_options = NumericProperty(17)
```

- [ ] **Step 3: import / 構文チェック**

Run: `python -c "import ast; ast.parse(open('katrain/gui/popups.py', encoding='utf-8').read())"`
Expected: エラーなし（Kivy 初期化を避けるため構文パースのみで確認）

- [ ] **Step 4: コミット**

```bash
git add katrain/gui/popups.py
git commit -m "fix(gui): AI設定の最大項目数を17に引き上げ（jigo 17項目対応）"
```

---

## Task 8: `config.json`（パッケージ）へデフォルト値追加

**Files:**
- Modify: `katrain/config.json:118`（`ai:jigo` ブロック末尾）

- [ ] **Step 1: デフォルト値を追加する**

`katrain/config.json:118` の `"jigo_deception_13_phase2_target": -1.0` を次へ変更（末尾カンマ追加＋新キー）:

```json
            "jigo_deception_13_phase2_target": -1.0,
            "jigo_force_sanrensei": false
```

- [ ] **Step 2: JSON 妥当性を確認する**

Run: `python -c "import json; json.load(open('katrain/config.json', encoding='utf-8'))"`
Expected: エラーなし（終了コード 0）

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat(jigo): config.json に jigo_force_sanrensei デフォルト値を追加"
```

---

## Task 9: ユーザーローカル `config.json` へキー追加（メインセッションで直接編集）

> **重要**: `C:\Users\iwaki\.katrain\config.json` の編集はサブエージェントに委任しない（CLAUDE.md の禁止事項）。**必ずメインセッションで直接 Edit する**。GUI は保存済みキーのみ表示するため、この追加が無いとチェックボックスが現れない。

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（`ai:jigo` ブロック）

- [ ] **Step 1: 現在の `ai:jigo` ブロックを Read で確認**

Read: `C:\Users\iwaki\.katrain\config.json` の `"ai:jigo"` セクション（キー構成はパッケージ版と異なる可能性があるため必ず実物を確認）。

- [ ] **Step 2: `jigo_force_sanrensei` を追加する**

`ai:jigo` ブロックの末尾キーの後に `"jigo_force_sanrensei": false` を追加（既存末尾キーにカンマを付与）。

- [ ] **Step 3: JSON 妥当性を確認する**

Run: `python -c "import json,os; json.load(open(os.path.expanduser('~/.katrain/config.json'), encoding='utf-8'))"`
Expected: エラーなし（終了コード 0）

- [ ] **Step 4: コミット不要**

ユーザーローカル設定は git 管理外のためコミットしない。

---

## Task 10: i18n ラベル・説明文を追加

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`

- [ ] **Step 1: 日本語 短ラベルを追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `msgid "jigo_deception"` エントリ付近（jigo 群）に新エントリを追加:

```
msgid "jigo_force_sanrensei"
msgstr "三連星強制 (黒=三連星/白=二連星、19路のみ)"
```

- [ ] **Step 2: 日本語 説明文を追記**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:527` の `msgid "aihelp:jigo"` の `msgstr` 末尾（閉じ引用符の直前）に追記:

```
 jigo_force_sanrensei: ON で 19路盤の序盤に星打ちを強制（黒番=一辺に沿った三連星、白番=同辺の隅星2つ＝二連星。相手が星にいれば対角隅）。13路・9路盤では無効。
```

- [ ] **Step 3: 英語 短ラベルを追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の jigo 群に追加:

```
msgid "jigo_force_sanrensei"
msgstr "Force sanrensei (B=sanrensei/W=2-star, 19x19 only)"
```

- [ ] **Step 4: 英語 説明文を追記**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po:836` の `msgid "aihelp:jigo"` の `msgstr` 末尾に追記:

```
 jigo_force_sanrensei: when ON, forces star-point opening on 19x19 (Black = sanrensei along one side; White = two corner stars on the same side, diagonal if opponent occupies a star). Disabled on 13x13 / 9x9.
```

- [ ] **Step 5: `.mo` を再コンパイル**

Run: `python tools/compile_mo.py`
Expected: エラーなく `.mo` が再生成される

- [ ] **Step 6: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "feat(i18n): jigo_force_sanrensei のラベル・説明文を追加"
```

---

## Task 11: ドキュメント更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（**サブエージェント経由で編集**＝CLAUDE.md の指示）
- Modify: `CLAUDE.md`

- [ ] **Step 1: `ai-parameters.md` の JigoStrategy パラメータ表に行を追加**

> `.claude/rules/` 配下の Edit は拒否されることがあるため、**Agent tool（サブエージェント）経由で編集・コミット**する（CLAUDE.md／メモリ `feedback_claude_rules_edit` 参照）。

JigoStrategy パラメータ表の末尾に追加:

```
| jigo_force_sanrensei | false | ON で19路盤序盤に星打ちを強制（黒=三連星/白=2連星）。13路・9路は無効。Stage 1 直後に対象を計算し非空なら Stage 2 をスキップして即着手。Spec: docs/superpowers/specs/2026-05-30-jigo-force-sanrensei-design.md |
```

- [ ] **Step 2: `CLAUDE.md` の改修概要に追記（任意・軽微）**

`CLAUDE.md` の主な改修リストの JigoStrategy 説明、または「主な改修」行に三連星強制オプション追加の旨を一文追記する（既存の記述スタイルに合わせる）。

- [ ] **Step 3: コミット**

```bash
git add .claude/rules/ai-parameters.md CLAUDE.md
git commit -m "docs(jigo): jigo_force_sanrensei をパラメータ表・CLAUDE.md に追記"
```

---

## Task 12: 統合検証（手動）

ユニットテストでカバーできない GUI 表示・実対局挙動を確認する。

**Files:** なし（検証のみ）

- [ ] **Step 1: 全テストスイートを実行**

Run: `python -m pytest --ignore=tests/test_ai.py -q`
Expected: PASS（humanSL モデル依存の test_ai.py は除外）

- [ ] **Step 2: CLI で 19路黒の序盤挙動を確認**

19路盤・序盤（空盤付近）の SGF を用意し、jigo 戦略で強制が発動することを確認:

Run:
```bash
python -m katrain_debug --sgf <19路序盤SGF> --move <序盤手数> --strategy jigo --settings jigo_force_sanrensei=true --output text
```
Expected: 出力に `force_sanrensei` ログ、着手が三連星ライン上の星点であること。

> 注: `katrain_debug` の `--settings` で bool を渡せるか実装を確認する。渡せない場合はユーザーローカル config を一時的に true にして GUI/CLI で確認する。

- [ ] **Step 3: GUI でチェックボックス表示を確認**

`C:\Users\iwaki\.katrain\config.json` の `debug_level` を 1 にして `python -m katrain` を起動 → AI 設定 → Kata持碁 を開き、「三連星強制」チェックボックスが表示され `GridLayoutException` が出ないことを確認。確認後 `debug_level` を 0 に戻す。

- [ ] **Step 4: 実対局で挙動確認**

jigo + `jigo_force_sanrensei` ON で19路黒の対局を開始し、黒が序盤3手で三連星を形成すること、白番では2連星になることを確認。ログを Grep:

Run: `grep -a "force_sanrensei" <ログ>`
Expected: 黒番で `n=3`、白番で `n=2` のログ。

---

## Self-Review（計画作成者によるチェック）

**1. Spec coverage:**
- 19路のみ → Task1（`_get_star_lines` 19限定）/ Task5（盤面ガード）/ Task2（n=3 13路空集合テスト）✓
- 黒=三連星/白=2連星 → Task5（`n_star = 3 if B else 2`）✓
- 白番挙動の説明文記載 → Task10（説明文に対角・2連星明記）✓
- 共有ヘルパー（アプローチA）→ Task2/Task4（HumanStyle 置換）✓
- UI チェックボックス・デフォルトOFF → Task6/Task8/Task9 ✓
- max_options 引き上げ → Task7 ✓
- Stage 1 直後短絡・Stage 2 スキップ → Task5 ✓
- 回帰担保 → Task4 Step1（n=2 テスト）✓
- ドキュメント → Task11 ✓

**2. Placeholder scan:** 全ステップに具体コード／コマンドあり。Task9 Step1・Task12 Step2 はユーザー環境依存のため「実物を Read して確認」と明示（プレースホルダではなく手順）。✓

**3. Type consistency:**
- `_compute_star_opening_targets(board_size, stones, ai_player, n)` — Task2 定義、Task4/Task5 呼び出しで引数一致 ✓
- `_select_star_target(target_stars, human_policy, board_size)` — Task3 定義、Task5 呼び出し一致 ✓
- `_get_star_lines(board_size)` — Task1 定義、Task2 で使用 ✓
- 返り値 set / Move 生成 `Move(coords, player=...)` — sgf_parser.Move コンストラクタ一致 ✓
