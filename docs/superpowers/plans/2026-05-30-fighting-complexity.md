# 力戦派 複雑化モード（FightingStrategy `complex`）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FightingStrategy に4つ目のモード `complex` を追加し、接触戦の密度を最優先に盤面を複雑化する per-move バイアスと、大差リード時のみ複雑化手に損失予算を許すゲートを実装する。

**Architecture:** 複雑さ判定・損失ゲートのロジックを **ai.py のモジュールレベル純関数**として切り出し（TDD でユニットテスト）、FightingStrategy の既存 `_generate_human()` パイプラインに `complex_mode` フラグで組み込む。`classic`/`scoreloss`/`human` は不変。複雑さ重み = 既存 fighting 重み（contact/invasion 込み）× 切りボーナス。損失フィルタ = `loss < base` は常に許容、`base ≤ loss < relaxed_cap` はリード条件＋鋭さ(`scoreStdev`)＋複雑さの3条件ゲートを満たす手のみ許容。

**Tech Stack:** Python 3.12 / Kivy / KataGo（humanSL）。テストは pytest（純関数のみ、モデル不要）。

仕様書: `docs/superpowers/specs/2026-05-30-fighting-complexity-design.md`

---

## File Structure

| ファイル | 役割 | 変更 |
|---|---|---|
| `katrain/core/ai.py` | 純関数群（`_count_cut_adjacency` 等）＋ `FightingStrategy` への組み込み | Modify |
| `tests/test_fighting_complexity.py` | 純関数のユニットテスト（モデル不要） | Create |
| `katrain/core/constants.py` | `AI_OPTION_VALUES` / `AI_OPTION_ORDER` に新パラメータ | Modify |
| `katrain/config.json` | パッケージ既定値（`ai:p:fighting`） | Modify |
| `C:\Users\iwaki\.katrain\config.json` | ローカル既定値（GUI 表示に必須・メインセッション直接編集） | Modify |
| `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po` | ラベル・説明文 | Modify |
| `.claude/rules/ai-parameters.md` | パラメータ表 | Modify（サブエージェント経由・既知の Edit 拒否対策） |
| `CLAUDE.md` | 概要追記 | Modify |

**純関数の配置場所:** `katrain/core/ai.py` の `FightingStrategy` クラス終端（現在の `generate_weighted_coords` の直後、`_get_corner_star_points` の直前＝現状 2716 行付近）にモジュールレベルで追加する。テストは `from katrain.core.ai import _count_cut_adjacency, ...` で取得する（`test_star_opening.py` と同じ流儀）。

**モジュール定数（純関数群の直前に定義）:**
```python
_COMPLEXITY_WEIGHT_FRAC = 0.5   # 緩和バンド通過に必要な複雑さ重み（候補中の最大重みに対する比）
_COMPLEXITY_RAMP = 10.0         # relaxed_cap が base から max_loss まで上りきるリード差（目）
```

---

### Task 1: 純関数 `_count_cut_adjacency`（切り検出）

候補の空点が「異なる相手 chain に2つ以上接する＝切り/楔」かを数える。`game.board`（`board[y][x]`＝chain id、-1=空）と `game.chains`（chain id → Move リスト）を使う純関数。

**Files:**
- Create: `tests/test_fighting_complexity.py`
- Modify: `katrain/core/ai.py`（2716 行付近、モジュールレベル）

- [ ] **Step 1: Write the failing test**

`tests/test_fighting_complexity.py`:
```python
# tests/test_fighting_complexity.py
"""力戦派 複雑化モードの純関数テスト（モデル不要）。"""
import pytest

from katrain.core.ai import _count_cut_adjacency
from katrain.core.game import Move


def _board(width, height, stones):
    """stones: {(x,y): chain_id} から board[y][x] グリッドを作る（未指定は -1）。"""
    board = [[-1 for _ in range(width)] for _ in range(height)]
    for (x, y), cid in stones.items():
        board[y][x] = cid
    return board


class TestCountCutAdjacency:
    def test_two_distinct_opponent_chains_is_cut(self):
        # (2,2) の上下に別々の白 chain（id 0, 1）。next=黒 → 相手=白。
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1})
        chains = [[Move(coords=(2, 1), player="W")], [Move(coords=(2, 3), player="W")]]
        assert _count_cut_adjacency(board, chains, (2, 2), "W") == 2

    def test_same_chain_on_two_sides_is_not_cut(self):
        # 上下とも同じ chain id 0 → 切りではない（1 を返す）。
        board = _board(5, 5, {(2, 1): 0, (2, 3): 0})
        chains = [[Move(coords=(2, 1), player="W"), Move(coords=(2, 3), player="W")]]
        assert _count_cut_adjacency(board, chains, (2, 2), "W") == 1

    def test_own_stones_are_ignored(self):
        # 隣接が自分(黒)の石なら相手 chain ではないので 0。
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1})
        chains = [[Move(coords=(2, 1), player="B")], [Move(coords=(2, 3), player="B")]]
        assert _count_cut_adjacency(board, chains, (2, 2), "W") == 0

    def test_edge_point_no_out_of_bounds(self):
        board = _board(5, 5, {(1, 0): 0})
        chains = [[Move(coords=(1, 0), player="W")]]
        # (0,0) の隣接は (1,0) と (0,1) のみ（盤外は無視）
        assert _count_cut_adjacency(board, chains, (0, 0), "W") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fighting_complexity.py -v`
Expected: FAIL with `ImportError: cannot import name '_count_cut_adjacency'`

- [ ] **Step 3: Write minimal implementation**

`katrain/core/ai.py`（2716 行付近・モジュールレベル、まず定数も置く）:
```python
_COMPLEXITY_WEIGHT_FRAC = 0.5
_COMPLEXITY_RAMP = 10.0


def _count_cut_adjacency(board, chains, coord, opponent_player):
    """coord (x,y) の4近傍に接する『異なる相手 chain』の数を返す。

    board: List[List[int]]  # board[y][x] = chain id（-1=空）
    chains: List[List[Move]]
    opponent_player: "B" or "W"
    戻り値が 2 以上なら『切り/楔』とみなせる。
    """
    x, y = coord
    height = len(board)
    width = len(board[0]) if height else 0
    opp_chain_ids = set()
    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
        if 0 <= nx < width and 0 <= ny < height:
            c = board[ny][nx]
            if c >= 0 and chains[c] and chains[c][0].player == opponent_player:
                opp_chain_ids.add(c)
    return len(opp_chain_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fighting_complexity.py -v`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git add tests/test_fighting_complexity.py katrain/core/ai.py
git commit -m "feat(fighting): 複雑化モード用 切り検出純関数 _count_cut_adjacency を追加"
```

---

### Task 2: 純関数 `_apply_cut_boost`（切りボーナス適用）

力戦重み辞書 `{(x,y): w}` のうち、空点かつ切り点（相手 chain 2つ以上隣接）に `cut_boost` を乗算した新 dict を返す。

**Files:**
- Modify: `katrain/core/ai.py`
- Modify: `tests/test_fighting_complexity.py`

- [ ] **Step 1: Write the failing test**

`tests/test_fighting_complexity.py` に追記:
```python
from katrain.core.ai import _apply_cut_boost  # 既存 import 行に追加


class TestApplyCutBoost:
    def test_cut_point_is_boosted(self):
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1})
        chains = [[Move(coords=(2, 1), player="W")], [Move(coords=(2, 3), player="W")]]
        weights = {(2, 2): 1.0, (0, 0): 1.0}
        out = _apply_cut_boost(weights, board, chains, "W", 2.0)
        assert out[(2, 2)] == 2.0   # 切り点 → ×2.0
        assert out[(0, 0)] == 1.0   # 非切り点 → 不変

    def test_boost_one_is_noop(self):
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1})
        chains = [[Move(coords=(2, 1), player="W")], [Move(coords=(2, 3), player="W")]]
        weights = {(2, 2): 1.0}
        out = _apply_cut_boost(weights, board, chains, "W", 1.0)
        assert out == weights

    def test_occupied_point_not_boosted(self):
        # 既に石がある点（board != -1）は切り点でもブーストしない
        board = _board(5, 5, {(2, 1): 0, (2, 3): 1, (2, 2): 2})
        chains = [
            [Move(coords=(2, 1), player="W")],
            [Move(coords=(2, 3), player="W")],
            [Move(coords=(2, 2), player="B")],
        ]
        weights = {(2, 2): 1.0}
        out = _apply_cut_boost(weights, board, chains, "W", 2.0)
        assert out[(2, 2)] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fighting_complexity.py::TestApplyCutBoost -v`
Expected: FAIL with `ImportError: cannot import name '_apply_cut_boost'`

- [ ] **Step 3: Write minimal implementation**

`katrain/core/ai.py`（`_count_cut_adjacency` の直後）:
```python
def _apply_cut_boost(weights, board, chains, opponent_player, cut_boost):
    """weights {(x,y): w} の空点かつ切り点に cut_boost を乗算した新 dict を返す。"""
    if cut_boost == 1.0:
        return dict(weights)
    boosted = {}
    for (x, y), w in weights.items():
        if board[y][x] == -1 and _count_cut_adjacency(board, chains, (x, y), opponent_player) >= 2:
            boosted[(x, y)] = w * cut_boost
        else:
            boosted[(x, y)] = w
    return boosted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fighting_complexity.py::TestApplyCutBoost -v`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git add tests/test_fighting_complexity.py katrain/core/ai.py
git commit -m "feat(fighting): 切りボーナス適用純関数 _apply_cut_boost を追加"
```

---

### Task 3: 純関数 `_complexity_relaxed_cap`（リード適応の損失上限）

リードが `lead_threshold` 未満なら緩和なし（`base_threshold`）。以上なら `_COMPLEXITY_RAMP` 目かけて `max_loss` まで線形に上昇。

**Files:**
- Modify: `katrain/core/ai.py`
- Modify: `tests/test_fighting_complexity.py`

- [ ] **Step 1: Write the failing test**

```python
from katrain.core.ai import _complexity_relaxed_cap  # import 行に追加


class TestComplexityRelaxedCap:
    def test_below_threshold_no_relaxation(self):
        assert _complexity_relaxed_cap(10.0, 5.6, 15.0, 10.0) == 5.6

    def test_at_threshold_returns_base(self):
        assert _complexity_relaxed_cap(15.0, 5.6, 15.0, 10.0) == 5.6

    def test_ramps_linearly_to_max(self):
        # ramp=10: lead=20 → 半分 → base + 0.5*(10-5.6) = 5.6 + 2.2 = 7.8
        assert _complexity_relaxed_cap(20.0, 5.6, 15.0, 10.0, ramp=10.0) == pytest.approx(7.8)

    def test_caps_at_max_loss(self):
        # lead 差が ramp を超えても max_loss でクランプ
        assert _complexity_relaxed_cap(100.0, 5.6, 15.0, 10.0, ramp=10.0) == pytest.approx(10.0)

    def test_max_loss_below_base_returns_base(self):
        # max_loss が base 以下なら緩和しない（tightening しない）
        assert _complexity_relaxed_cap(50.0, 5.6, 15.0, 4.0) == 5.6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fighting_complexity.py::TestComplexityRelaxedCap -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
def _complexity_relaxed_cap(current_lead, base_threshold, lead_threshold, max_loss, ramp=_COMPLEXITY_RAMP):
    """リードに応じた損失上限。current_lead < lead_threshold なら base のまま。"""
    if current_lead < lead_threshold or max_loss <= base_threshold:
        return base_threshold
    frac = min(1.0, (current_lead - lead_threshold) / ramp) if ramp > 0 else 1.0
    return base_threshold + frac * (max_loss - base_threshold)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fighting_complexity.py::TestComplexityRelaxedCap -v`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
git add tests/test_fighting_complexity.py katrain/core/ai.py
git commit -m "feat(fighting): リード適応損失上限 _complexity_relaxed_cap を追加"
```

---

### Task 4: 純関数 `_passes_complexity_gate`（1手の通過判定）

`loss < base` は常に通過。`base ≤ loss < relaxed_cap` は鋭さ条件（`scoreStdev ≥ sharpness_min`）＋複雑さ条件（複雑さ重みが候補中最大の `weight_frac` 倍以上）の両方で通過。`loss ≥ relaxed_cap` は不通過。

**Files:**
- Modify: `katrain/core/ai.py`
- Modify: `tests/test_fighting_complexity.py`

- [ ] **Step 1: Write the failing test**

```python
from katrain.core.ai import _passes_complexity_gate  # import 行に追加


class TestPassesComplexityGate:
    BASE = 5.6
    CAP = 10.0

    def test_low_loss_always_passes(self):
        # loss < base → 鋭さ/複雑さに関係なく通過
        assert _passes_complexity_gate(2.0, self.BASE, self.CAP, None, 3.0, 0.0, 1.0, 0.5) is True

    def test_above_cap_rejected(self):
        assert _passes_complexity_gate(11.0, self.BASE, self.CAP, 9.0, 3.0, 1.0, 1.0, 0.5) is False

    def test_relaxed_band_needs_sharpness(self):
        # band 内だが scoreStdev 不足 → 不通過
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, 1.0, 3.0, 1.0, 1.0, 0.5) is False

    def test_relaxed_band_needs_complexity(self):
        # 鋭いが複雑さ重みが最大の 0.5 倍未満 → 不通過
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, 9.0, 3.0, 0.2, 1.0, 0.5) is False

    def test_relaxed_band_passes_both(self):
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, 9.0, 3.0, 0.8, 1.0, 0.5) is True

    def test_missing_stdev_rejected(self):
        # scoreStdev が None（取得できず）→ band 内は安全側で不通過
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, None, 3.0, 1.0, 1.0, 0.5) is False

    def test_zero_max_weight_rejected(self):
        assert _passes_complexity_gate(7.0, self.BASE, self.CAP, 9.0, 3.0, 0.0, 0.0, 0.5) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fighting_complexity.py::TestPassesComplexityGate -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
def _passes_complexity_gate(loss, base_threshold, relaxed_cap, score_stdev, sharpness_min,
                            complexity_weight, max_complexity_weight, weight_frac):
    """1手がフィルタを通過するか判定する。"""
    if loss < base_threshold:
        return True
    if loss >= relaxed_cap:
        return False
    if score_stdev is None or score_stdev < sharpness_min:
        return False
    if max_complexity_weight <= 0:
        return False
    if complexity_weight < weight_frac * max_complexity_weight:
        return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fighting_complexity.py::TestPassesComplexityGate -v`
Expected: PASS（7 tests）

- [ ] **Step 5: Commit**

```bash
git add tests/test_fighting_complexity.py katrain/core/ai.py
git commit -m "feat(fighting): 複雑化ゲート判定 _passes_complexity_gate を追加"
```

---

### Task 5: 純関数 `_complexity_loss_filter`（フィルタ本体）

`move_infos` 全体を受け取り、通過手の GTP set を返す。`_complexity_relaxed_cap` と `_passes_complexity_gate` を組み合わせる。

**Files:**
- Modify: `katrain/core/ai.py`
- Modify: `tests/test_fighting_complexity.py`

- [ ] **Step 1: Write the failing test**

```python
from katrain.core.ai import _complexity_loss_filter  # import 行に追加


class TestComplexityLossFilter:
    def _mi(self, move, score_lead, stdev):
        return {"move": move, "scoreLead": score_lead, "scoreStdev": stdev}

    def test_winning_admits_sharp_complex_move(self):
        # 黒番 player_sign=1, best_score=20。
        # A: loss0（最善）, B: loss7（band内・鋭い・複雑）, C: loss7（band内・鈍い）
        move_infos = [
            self._mi("A", 20.0, 5.0),
            self._mi("B", 13.0, 9.0),
            self._mi("C", 13.0, 1.0),
        ]
        cw = {"A": 0.1, "B": 1.0, "C": 1.0}
        out = _complexity_loss_filter(
            move_infos, best_score=20.0, player_sign=1, base_threshold=5.6,
            current_lead=20.0, lead_threshold=15.0, max_loss=10.0, sharpness_min=3.0,
            weight_frac=0.5, complexity_weight_by_gtp=cw, ramp=10.0,
        )
        assert "A" in out          # 常に通過
        assert "B" in out          # 鋭く複雑 → 通過
        assert "C" not in out      # 鈍い → 不通過

    def test_not_winning_only_low_loss(self):
        # current_lead < threshold → 緩和なし。band の手は全部落ちる
        move_infos = [self._mi("A", 20.0, 5.0), self._mi("B", 13.0, 9.0)]
        cw = {"A": 0.1, "B": 1.0}
        out = _complexity_loss_filter(
            move_infos, best_score=20.0, player_sign=1, base_threshold=5.6,
            current_lead=3.0, lead_threshold=15.0, max_loss=10.0, sharpness_min=3.0,
            weight_frac=0.5, complexity_weight_by_gtp=cw, ramp=10.0,
        )
        assert out == {"A"}

    def test_white_sign_loss_calc(self):
        # 白番 player_sign=-1。scoreLead は黒視点。best_score=-20（白+20）。
        # B: scoreLead=-13 → loss = -1*(-20 - (-13)) = -1*(-7) = 7（band内）
        move_infos = [self._mi("A", -20.0, 5.0), self._mi("B", -13.0, 9.0)]
        cw = {"A": 0.1, "B": 1.0}
        out = _complexity_loss_filter(
            move_infos, best_score=-20.0, player_sign=-1, base_threshold=5.6,
            current_lead=20.0, lead_threshold=15.0, max_loss=10.0, sharpness_min=3.0,
            weight_frac=0.5, complexity_weight_by_gtp=cw, ramp=10.0,
        )
        assert out == {"A", "B"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fighting_complexity.py::TestComplexityLossFilter -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
def _complexity_loss_filter(move_infos, best_score, player_sign, base_threshold,
                            current_lead, lead_threshold, max_loss, sharpness_min,
                            weight_frac, complexity_weight_by_gtp, ramp=_COMPLEXITY_RAMP):
    """complex モードの悪手フィルタ。通過手の GTP set を返す。"""
    relaxed_cap = _complexity_relaxed_cap(current_lead, base_threshold, lead_threshold, max_loss, ramp)
    max_cw = max(complexity_weight_by_gtp.values(), default=0.0)
    result = set()
    for mi in move_infos:
        gtp = mi.get("move", "")
        score = mi.get("scoreLead", 0)
        loss = player_sign * (best_score - score)
        stdev = mi.get("scoreStdev")
        cw = complexity_weight_by_gtp.get(gtp, 0.0)
        if _passes_complexity_gate(loss, base_threshold, relaxed_cap, stdev, sharpness_min, cw, max_cw, weight_frac):
            result.add(gtp)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fighting_complexity.py::TestComplexityLossFilter -v`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git add tests/test_fighting_complexity.py katrain/core/ai.py
git commit -m "feat(fighting): complexモード悪手フィルタ _complexity_loss_filter を追加"
```

---

### Task 6: `_build_complexity_weight_dict` メソッド追加

既存 `_build_fighting_weight_dict()`（contact_boost / invasion_bonus 込み）の結果に切りボーナスを乗せる薄いメソッド。`game.board` / `game.chains` を純関数 `_apply_cut_boost` に渡す。

**Files:**
- Modify: `katrain/core/ai.py`（`FightingStrategy._build_fighting_weight_dict` の直後＝現状 2211 行付近）

このメソッドは `self.game`/`self.cn` 依存のためユニットテストはしない（既存 `_build_fighting_weight_dict` も同様にテストなし）。コアの切りボーナス計算は Task 2 でテスト済み。

- [ ] **Step 1: Implement the method**

`katrain/core/ai.py`（`_build_fighting_weight_dict` の `return weights` 直後）:
```python
    def _build_complexity_weight_dict(self):
        """複雑化重み = 力戦重み（contact/invasion 込み）× 切りボーナス。"""
        base_weights = self._build_fighting_weight_dict()
        cut_boost = self.settings.get("complexity_cut_boost", 2.0)
        opponent_player = "W" if self.cn.next_player == "B" else "B"
        return _apply_cut_boost(
            base_weights, self.game.board, self.game.chains, opponent_player, cut_boost
        )
```

- [ ] **Step 2: Verify import compiles**

Run: `python -c "import katrain.core.ai"`
Expected: 出力なし（エラーなし）

- [ ] **Step 3: Commit**

```bash
git add katrain/core/ai.py
git commit -m "feat(fighting): 複雑化重み構築メソッド _build_complexity_weight_dict を追加"
```

---

### Task 7: `complex` モードを `generate_move` / `_generate_human` に組み込む

`fighting_mode == "complex"` で `_generate_human(complex_mode=True)` を呼ぶ。`_generate_human` 内を `complex_mode` で分岐し、(a) 重み辞書を複雑化重みに、(b) 悪手フィルタを `_complexity_loss_filter` に、(c) 安全弁閾値を relaxed_cap に引き上げる。

**Files:**
- Modify: `katrain/core/ai.py`（`FightingStrategy.generate_move` 2155 行付近 / `_generate_human` 2274〜2696 行）

このタスクは KataGo を要するためユニットテスト不可。検証は Task 12 の CLI スモークで行う（既存 `_generate_human` 同様）。

- [ ] **Step 1: `generate_move` に complex 分岐を追加**

`katrain/core/ai.py` 2155-2160（`if mode == "scoreloss": ...` ブロック）を以下に変更:
```python
        if mode == "scoreloss":
            return self._generate_scoreloss()
        elif mode == "human":
            return self._generate_human()
        elif mode == "complex":
            return self._generate_human(complex_mode=True)
        else:
            return self._generate_classic()
```

- [ ] **Step 2: `_generate_human` のシグネチャに `complex_mode` を追加**

2274 行 `def _generate_human(self) -> Tuple[Move, str]:` を:
```python
    def _generate_human(self, complex_mode: bool = False) -> Tuple[Move, str]:
```

- [ ] **Step 3: 悪手フィルタ部を complex 分岐に置換**

2401-2466 のフィルタ構築ブロック（`chaos_relax = ...` から `f"[FightingStrategy:human] {len(good_moves)} moves pass score filter"` ログまで）を、complex 分岐を先頭に足す形に変更する。`_filter_moves` 内部関数定義はそのまま残し、その**呼び出し**を以下のように分岐する。

`good_moves = _filter_moves(move_infos, BAD_MOVE_THRESHOLD, ...)`（2431 行）の直前に挿入し、2431 の無条件呼び出しを `if not complex_mode:` 配下へ移す:
```python
            # --- complex モード: リード適応＋鋭さ＋複雑さゲート ---
            complexity_weights = {}
            current_lead = best_score
            if complex_mode:
                opponent_stones = [s for s in self.game.stones if s.player != self.cn.next_player]
                if len(opponent_stones) >= 2:
                    complexity_weights = self._build_complexity_weight_dict()
                root_src = clean_analysis if (clean_analysis and not clean_error) else analysis
                current_lead = player_sign * (root_src or {}).get("rootInfo", {}).get("scoreLead", best_score)
                lead_threshold = self.settings.get("complexity_lead_threshold", 15.0)
                complexity_max_loss = self.settings.get("complexity_max_loss", 10.0)
                sharpness_min = self.settings.get("complexity_sharpness_min", 3.0)
                complexity_weight_by_gtp = {
                    Move((x, y), player=self.cn.next_player).gtp(): w
                    for (x, y), w in complexity_weights.items()
                }
                good_moves = _complexity_loss_filter(
                    move_infos, best_score, player_sign, BAD_MOVE_THRESHOLD,
                    current_lead, lead_threshold, complexity_max_loss, sharpness_min,
                    _COMPLEXITY_WEIGHT_FRAC, complexity_weight_by_gtp, _COMPLEXITY_RAMP,
                )
                self.game.katrain.log(
                    f"[FightingStrategy:complex] lead={current_lead:.1f} "
                    f"relaxed_cap={_complexity_relaxed_cap(current_lead, BAD_MOVE_THRESHOLD, lead_threshold, complexity_max_loss):.1f} "
                    f"{len(good_moves)} moves pass complexity filter",
                    OUTPUT_DEBUG,
                )
            else:
                good_moves = _filter_moves(move_infos, BAD_MOVE_THRESHOLD, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score)
```

そして既存の段階緩和フェイルセーフ（2432 `_FILTER_RELAXATION_STEPS` 〜 2462）全体を `if not complex_mode:` でガードする（complex は空集合時に後段の「全手フィルタ時フォールバック」へ流す）。先頭に1行追加:
```python
            # --- 段階的閾値緩和フェイルセーフ（complex モードは複雑化フィルタを使うためスキップ） ---
            _FILTER_RELAXATION_STEPS = [1.5, 2.0]
            _FILTER_ABSOLUTE_CAP = 9.0
            if not complex_mode and not good_moves:
                original_threshold = BAD_MOVE_THRESHOLD
                ...  # 既存の中身そのまま
```

- [ ] **Step 4: 安全弁閾値を complex モードで relaxed_cap に引き上げる**

2496 行 `_SAFETY_LOSS_THRESHOLD = 4.0` を以下に変更（意図的な予算内損失を安全弁で潰さない）:
```python
            _SAFETY_LOSS_THRESHOLD = 4.0
            if complex_mode:
                _SAFETY_LOSS_THRESHOLD = max(
                    4.0,
                    _complexity_relaxed_cap(
                        current_lead, BAD_MOVE_THRESHOLD,
                        self.settings.get("complexity_lead_threshold", 15.0),
                        self.settings.get("complexity_max_loss", 10.0),
                    ),
                )
```

- [ ] **Step 5: 重み辞書構築を complex 分岐に**

2516-2521（`opponent_stones = ...` / `fighting_weights = self._build_fighting_weight_dict()` ブロック）を以下に変更（complex は構築済みを再利用）:
```python
        opponent_stones = [s for s in self.game.stones if s.player != self.cn.next_player]
        if complex_mode:
            fighting_weights = complexity_weights
        elif len(opponent_stones) >= 2:
            fighting_weights = self._build_fighting_weight_dict()
        else:
            fighting_weights = {}
```

- [ ] **Step 6: ai_thoughts ラベルを complex 用に（任意・末尾の return）**

2692-2695 の `ai_thoughts` 文字列の `"Human+Fighting: played ..."` を以下に:
```python
        label = "Complex+Fighting" if complex_mode else "Human+Fighting"
        ai_thoughts = (
            f"\n{top_str}\n\n{label}: played {move.gtp()} "
            f"({filtered_count} bad moves filtered)"
        )
```

- [ ] **Step 7: Verify import compiles**

Run: `python -c "import katrain.core.ai"`
Expected: 出力なし

- [ ] **Step 8: Run existing tests to confirm no regression on pure functions**

Run: `pytest tests/test_fighting_complexity.py tests/test_board.py -v`
Expected: PASS（全件）

- [ ] **Step 9: Commit**

```bash
git add katrain/core/ai.py
git commit -m "feat(fighting): complexモードを generate_move/_generate_human に組み込み"
```

---

### Task 8: `constants.py` にパラメータ登録

**Files:**
- Modify: `katrain/core/constants.py`

- [ ] **Step 1: `fighting_mode` の選択肢に complex を追加**

152-156 行を:
```python
    "fighting_mode": [
        ("classic", "[fighting:classic]"),
        ("scoreloss", "[fighting:scoreloss]"),
        ("human", "[fighting:human]"),
        ("complex", "[fighting:complex]"),
    ],
```

- [ ] **Step 2: `AI_OPTION_VALUES` に新パラメータ4件を追加**

161 行 `"fighting_chaos_relax": ...` の直後に:
```python
    "complexity_cut_boost": [1.0, 1.5, 2.0, 3.0, 5.0],          # 切り点の重みブースト
    "complexity_lead_threshold": [5.0, 10.0, 15.0, 20.0, 25.0, 30.0],  # 緩和解禁リード差（目）
    "complexity_max_loss": [6.0, 7.0, 8.0, 9.0, 10.0, 12.0],    # 緩和時の損失上限（目）
    "complexity_sharpness_min": [1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0],  # 鋭さゲート（scoreStdev、要校正）
```

- [ ] **Step 3: `AI_OPTION_ORDER` に表示順を追加**

226 行 `"fighting_chaos_relax": 5,` の直後に:
```python
    "complexity_cut_boost": 6,
    "complexity_lead_threshold": 7,
    "complexity_max_loss": 8,
    "complexity_sharpness_min": 9,
```

- [ ] **Step 4: Verify import compiles**

Run: `python -c "import katrain.core.constants"`
Expected: 出力なし

- [ ] **Step 5: Commit**

```bash
git add katrain/core/constants.py
git commit -m "feat(fighting): complexモードのパラメータを constants に登録"
```

---

### Task 9: `config.json`（パッケージ＋ローカル）に既定値追加

`ai:p:fighting` は現在12キー。4キー追加で16（GUI `max_options=17` 以内）。

**Files:**
- Modify: `katrain/config.json`
- Modify: `C:\Users\iwaki\.katrain\config.json`（**メインセッションで直接 Edit。サブエージェント委任不可**）

- [ ] **Step 1: パッケージ `config.json` の `ai:p:fighting` に4キー追加**

`"fighting_chaos_relax": 0.0,` の直後に:
```json
      "complexity_cut_boost": 2.0,
      "complexity_lead_threshold": 15.0,
      "complexity_max_loss": 10.0,
      "complexity_sharpness_min": 3.0,
```
（インデントは既存 `ai:p:fighting` ブロックに合わせる）

- [ ] **Step 2: 追加が JSON として妥当か検証**

Run: `python -c "import json; d=json.load(open('katrain/config.json',encoding='utf-8')); print({k:v for k,v in d['ai']['ai:p:fighting'].items() if k.startswith('complexity')})"`
Expected: `{'complexity_cut_boost': 2.0, 'complexity_lead_threshold': 15.0, 'complexity_max_loss': 10.0, 'complexity_sharpness_min': 3.0}`

- [ ] **Step 3: ローカル `C:\Users\iwaki\.katrain\config.json` の `ai:p:fighting` に同じ4キーを追加**

メインセッションで Read → Edit。`fighting_chaos_relax` の直後に同じ4行を挿入する。
（ローカル config に `ai:p:fighting` が無い／キー構成が異なる場合は、パッケージ側の `ai:p:fighting` 全体をコピーして補う）

- [ ] **Step 4: ローカル config の検証**

Run: `python -c "import json; d=json.load(open(r'C:/Users/iwaki/.katrain/config.json',encoding='utf-8')); print({k:v for k,v in d['ai']['ai:p:fighting'].items() if k.startswith('complexity')})"`
Expected: 4キーが表示される

- [ ] **Step 5: Commit（パッケージ config のみ。ローカル config は git 管理外）**

```bash
git add katrain/config.json
git commit -m "feat(fighting): complexモード既定値をパッケージconfigに追加"
```

---

### Task 10: i18n ラベル・説明文 ＋ `.mo` コンパイル

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`

- [ ] **Step 1: 既存の `fighting:human` 周辺を確認して挿入位置を特定**

Run: `grep -n "fighting:human\|fighting:classic\|fighting_contact_boost" katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
Expected: 既存 msgid 行番号が表示される

- [ ] **Step 2: jp `.po` に msgid を追加**

`fighting:human` の近くに:
```po
msgid "fighting:complex"
msgstr "複雑化"

msgid "complexity_cut_boost"
msgstr "切りボーナス"

msgid "complexity_lead_threshold"
msgstr "緩和解禁リード差"

msgid "complexity_max_loss"
msgstr "緩和時の損失上限"

msgid "complexity_sharpness_min"
msgstr "鋭さ閾値(scoreStdev)"
```
さらに既存 `aihelp:ai:p:fighting`（力戦派の説明本文）に complex モードの説明を1段落追記する（grep で本文を特定）。

- [ ] **Step 3: en `.po` に同じ msgid を英語で追加**

```po
msgid "fighting:complex"
msgstr "Complex"

msgid "complexity_cut_boost"
msgstr "Cut boost"

msgid "complexity_lead_threshold"
msgstr "Lead to unlock loss budget"

msgid "complexity_max_loss"
msgstr "Max loss when leading"

msgid "complexity_sharpness_min"
msgstr "Sharpness gate (scoreStdev)"
```

- [ ] **Step 4: `.mo` を再コンパイル**

Run: `python tools/compile_mo.py`
Expected: 成功（エラーなし）

- [ ] **Step 5: Commit**

```bash
git add katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.mo katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo
git commit -m "feat(i18n): complexモードのラベル・説明を追加"
```

---

### Task 11: ドキュメント更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（**サブエージェント経由で編集・コミット**＝既知の Edit 拒否対策）
- Modify: `CLAUDE.md`

- [ ] **Step 1: `ai-parameters.md` の力戦派セクションに complex モードの表を追記**

力戦派モード（FightingStrategy）の表の下に新パラメータ4件と complex モードの説明を追加（サブエージェントに以下を渡す）:

| パラメータ | デフォルト | 備考 |
|---|---|---|
| complexity_cut_boost | 2.0 | 切り点（相手chain2つ以上隣接）の重みブースト（1.0〜5.0） |
| complexity_lead_threshold | 15.0 | この目数以上リードで損失緩和を解禁 |
| complexity_max_loss | 10.0 | 緩和時の損失上限（リードに比例して base→max を10目かけて上昇） |
| complexity_sharpness_min | 3.0 | 緩和バンド通過に必要な scoreStdev（要GUI校正） |

加えてハードコード定数 `_COMPLEXITY_WEIGHT_FRAC=0.5` / `_COMPLEXITY_RAMP=10.0` も記載。

- [ ] **Step 2: `CLAUDE.md` の「概要」に complex モードを1行追記**

「主な改修」の FightingStrategy 記述に「力戦派に複雑化モード `complex`（切りボーナス＋リード適応の損失予算ゲート）を追加」を加える。

- [ ] **Step 3: Commit（CLAUDE.md。ai-parameters.md はサブエージェントがコミット）**

```bash
git add CLAUDE.md
git commit -m "docs(fighting): complexモードをCLAUDE.md概要に追記"
```

---

### Task 12: CLI スモーク検証

純関数以外（実エンジン経路）を KataGo 起動ありで確認する。humanSL モデルが必要。

**Files:**（変更なし・検証のみ）

- [ ] **Step 1: complex モードが起動・着手まで通ることを確認**

Run:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 60 --strategy fighting --settings fighting_mode=complex --output text
```
Expected: クラッシュせず着手が出力される。`result.move` に座標、`explanation` に "Complex+Fighting" 等。

- [ ] **Step 2: 大差リード局面で緩和バンドが作動するか確認**

大差局面（片側が15目以上リード）の手数を `--move N` で指定し、debug ログを確認:
```bash
python -m katrain_debug --sgf <大差SGF> --move <N> --strategy fighting --settings fighting_mode=complex --output json 2>/dev/null | python -c "import sys,json; d=json.load(sys.stdin); print(d['result'].get('explanation',''))"
```
Expected: `[FightingStrategy:complex] lead=... relaxed_cap=...` がログに出る（lead≥15 で relaxed_cap>5.6）。リード不足の局面では relaxed_cap=5.6 のまま。

- [ ] **Step 3: 非リード局面で通常 human と同等の安全性（大悪手を打たない）を確認**

Run:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 60 --strategy fighting --settings fighting_mode=complex --output text
```
Expected: 選択手の loss が NORMAL_THRESHOLD(5.6) 未満（リードしていなければ緩和は無効）。

- [ ] **Step 4: 全純関数テストの最終確認**

Run: `pytest tests/test_fighting_complexity.py -v`
Expected: 全 PASS（22 tests）

- [ ] **Step 5: 検証結果を記録（コミット不要）**

GUI 実戦での複雑化効果は batch 評価では測れない（仕様書「既知の限界」）。`debug_level=1` での GUI 対局で `[FightingStrategy:complex]` ログを `grep -a` 確認することを README 的に Task 完了メモに残す。

---

## Self-Review

**1. Spec coverage:**
- 土台=FightingStrategy human パイプライン → Task 7 ✓
- complex モード追加 → Task 7, 8 ✓
- 複雑さ重み（切りボーナス＋接触強調=既存 contact_boost 流用） → Task 2, 6 ✓
- リード適応損失予算 → Task 3, 5, 7 ✓
- 鋭さゲート（scoreStdev） → Task 4, 5 ✓
- 複雑さ条件（weight_frac） → Task 4, 5 ✓
- 安全弁の扱い（relaxed_cap に引き上げ） → Task 7 Step 4 ✓
- パラメータ/GUI/config 3箇所/i18n → Task 8, 9, 10 ✓
- 検証方法・既知の限界 → Task 12 ✓
- 最小構成スタート（新戦場ボーナスは後追加） → 本計画に含めず（仕様通り）✓

**2. Placeholder scan:** TBD/TODO なし。`complexity_sharpness_min` は「要校正」だが default=3.0 を確定値として採用（校正は GUI 実戦で）。

**3. Type consistency:** 純関数シグネチャは Task 1-5 で定義し Task 6-7 の呼び出しと一致（`_apply_cut_boost(weights, board, chains, opponent_player, cut_boost)`、`_complexity_loss_filter(move_infos, best_score, player_sign, base_threshold, current_lead, lead_threshold, max_loss, sharpness_min, weight_frac, complexity_weight_by_gtp, ramp)`）。モジュール定数 `_COMPLEXITY_WEIGHT_FRAC` / `_COMPLEXITY_RAMP` は Task 1 で定義し Task 5, 7 で参照。

**注意点（実装者向け）:**
- Task 7 は巨大メソッド `_generate_human`（約420行）への外科的編集。行番号は目安。編集前に該当ブロックを Read で確認し、`_filter_moves` 内部関数・段階緩和フェイルセーフ・安全弁v1/v2 の位置関係を把握してから着手すること。
- `scoreStdev` は KataGo 標準フィールドだが、欠落時は `_passes_complexity_gate` が安全側（緩和バンド不通過）に倒れる設計。
