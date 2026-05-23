# 迷路戦略（MazeStrategy）実装計画

**【中止】2026-05-23: この計画に基づく実装は完了したが、GUI 実機テストの結果、戦略自体を中止。** 中止理由は spec（`docs/superpowers/specs/2026-05-23-maze-strategy-9x9-design.md`）冒頭の注記を参照。実装一式は `feature/maze-strategy-9x9` ブランチに保留（master 未マージ）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 9路盤専用の新 AI 戦略「迷路（MazeStrategy）」を追加し、相手が最善応手に最も深い読みを要する手（humanSL 期待損失 + 鋭さが最大の手）を選んで対局を難解化する。

**Architecture:** `AIStrategy` を継承した `MazeStrategy` を `katrain/core/ai.py` に追加。各候補手 M について `engine.request_analysis(next_move=M)` で2手先読み照会を行い、子局面で相手が直面する humanPolicy（Stage 1・humanSL 9段）と clean scoreLead（Stage 2）を取得。難解さ `D = E + w×S`（E=期待損失、S=鋭さ二次モーメント）を計算し、ネットスコア `N = D − λ×own_loss` を argmax で選ぶ。難解さの計算は純粋関数に切り出して単体テスト可能にする。

**Tech Stack:** Python 3.12 / Kivy GUI / KataGo (humanSL humanv0 モデル) / pytest / 既存 JigoStrategy の二段階クエリパターンを踏襲。

**Spec:** `docs/superpowers/specs/2026-05-23-maze-strategy-9x9-design.md`

---

## ファイル構成

| ファイル | 役割 | 変更種別 |
|---|---|---|
| `katrain/core/ai.py` | 純粋関数 `_maze_compute_difficulty` / `_maze_net_score` / `_maze_select_best` と `MazeStrategy` クラス、import に `AI_MAZE` 追加 | Modify |
| `katrain/core/constants.py` | `AI_MAZE` 定数、戦略リスト登録、`AI_STRENGTH`、`AI_OPTION_VALUES`、`AI_OPTION_ORDER` | Modify |
| `katrain/config.json` | `ai:maze` のパラメータ既定値 | Modify |
| `C:\Users\iwaki\.katrain\config.json` | 同じ既定値（GUI 表示用・**メインセッションで直接編集**） | Modify |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 英語ラベル・aihelp | Modify |
| `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | 日本語ラベル・aihelp | Modify |
| `katrain_debug/runner.py` | `STRATEGY_NAME_MAP` に `"maze"` 追加、import | Modify |
| `tests/test_maze.py` | 純粋関数の単体テスト | Create |
| `CLAUDE.md` / `.claude/rules/ai-parameters.md` | ドキュメント更新 | Modify |

---

## Task 1: 難解さ計算の純粋関数 + 単体テスト（TDD）

KataGo を使わずにテストできる純粋関数を先に実装する。これが戦略の数式的中核。

**Files:**
- Modify: `katrain/core/ai.py`（モジュールレベル関数を追加。`JigoStrategy` 等の helper 群の近く、例: `class JigoStrategy` の直前あたり）
- Test: `tests/test_maze.py`

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/test_maze.py`:

```python
# tests/test_maze.py
"""MazeStrategy pure-function unit tests (KataGo 不要)."""
import pytest

from katrain.core.ai import (
    _maze_compute_difficulty,
    _maze_net_score,
    _maze_select_best,
)


def _mi(move, score_lead):
    """Build a child moveInfo dict shorthand."""
    return {"move": move, "scoreLead": score_lead}


class TestMazeComputeDifficulty:
    def test_empty_move_infos_returns_zeros(self):
        E, S, D = _maze_compute_difficulty([], lambda m: 0.0, opp_sign=1, sharpness_weight=0.5)
        assert (E, S, D) == (0.0, 0.0, 0.0)

    def test_expected_loss_weighted_by_human_policy(self):
        # opp_sign=1 (opponent is Black). best opp score = 5.0 (A1).
        # B2: scoreLead 2.0 → ptloss 3.0 ; C3: scoreLead 5.0 → ptloss 0.0
        infos = [_mi("A1", 5.0), _mi("B2", 2.0), _mi("C3", 5.0)]
        # human likely plays B2 (the losing move): hp A1=0.1, B2=0.8, C3=0.1
        hp = {"A1": 0.1, "B2": 0.8, "C3": 0.1}
        E, S, D = _maze_compute_difficulty(infos, lambda m: hp[m], opp_sign=1, sharpness_weight=0.0)
        # total_hp=1.0; E = 0.1*2.0(A1 ptloss=0) ... compute precisely below
        # A1 ptloss=0, B2 ptloss=3.0, C3 ptloss=0 → E = 0.8*3.0 = 2.4
        assert E == pytest.approx(2.4)
        assert D == pytest.approx(2.4)  # sharpness_weight=0

    def test_sharpness_term_emphasizes_large_losses(self):
        infos = [_mi("A1", 5.0), _mi("B2", 2.0)]
        hp = {"A1": 0.5, "B2": 0.5}
        E, S, D = _maze_compute_difficulty(infos, lambda m: hp[m], opp_sign=1, sharpness_weight=1.0)
        # ptloss A1=0, B2=3.0 ; total_hp=1.0
        # E = 0.5*3.0 = 1.5 ; S = 0.5*3.0^2 = 4.5 ; D = 1.5 + 1.0*4.5 = 6.0
        assert E == pytest.approx(1.5)
        assert S == pytest.approx(4.5)
        assert D == pytest.approx(6.0)

    def test_white_to_move_uses_opp_sign(self):
        # opp_sign=-1 (opponent is White). scoreLead is Black-perspective.
        # White best = most negative Black lead. A1 lead=-5 → white score 5 (best)
        # B2 lead=-2 → white score 2 → ptloss 3.0
        infos = [_mi("A1", -5.0), _mi("B2", -2.0)]
        hp = {"A1": 0.2, "B2": 0.8}
        E, S, D = _maze_compute_difficulty(infos, lambda m: hp[m], opp_sign=-1, sharpness_weight=0.0)
        assert E == pytest.approx(0.8 * 3.0)

    def test_zero_human_policy_falls_back_to_uniform_sharpness(self):
        # humanPolicy all zero → E=0, S = mean of ptloss^2, D = sharpness_weight*S
        infos = [_mi("A1", 5.0), _mi("B2", 2.0)]
        E, S, D = _maze_compute_difficulty(infos, lambda m: 0.0, opp_sign=1, sharpness_weight=2.0)
        # ptloss A1=0, B2=3.0 → S = (0 + 9.0)/2 = 4.5 ; E=0 ; D = 0 + 2.0*4.5 = 9.0
        assert E == pytest.approx(0.0)
        assert S == pytest.approx(4.5)
        assert D == pytest.approx(9.0)


class TestMazeNetScore:
    def test_net_subtracts_lambda_times_own_loss(self):
        assert _maze_net_score(difficulty=6.0, own_loss=4.0, risk_lambda=0.3) == pytest.approx(4.8)

    def test_zero_lambda_ignores_own_loss(self):
        assert _maze_net_score(difficulty=6.0, own_loss=4.0, risk_lambda=0.0) == pytest.approx(6.0)


class TestMazeSelectBest:
    def test_returns_none_for_empty(self):
        assert _maze_select_best([]) is None

    def test_picks_max_n(self):
        cands = [
            {"move": "A1", "N": 1.0},
            {"move": "B2", "N": 5.0},
            {"move": "C3", "N": 3.0},
        ]
        assert _maze_select_best(cands)["move"] == "B2"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_maze.py -v`
Expected: FAIL — `ImportError: cannot import name '_maze_compute_difficulty'`

- [ ] **Step 3: 純粋関数を実装**

`katrain/core/ai.py` に、`@register_strategy(AI_JIGO)` の行（`class JigoStrategy` のデコレータ）の直前にモジュールレベル関数を追加する:

```python
def _maze_compute_difficulty(opp_move_infos, hp_lookup, opp_sign, sharpness_weight):
    """子局面で相手が直面する難解さを計算する純粋関数。

    Args:
        opp_move_infos: 子局面の相手応手リスト（各 dict は "move", "scoreLead" を持つ）。
                        scoreLead は KataGo 規約どおり常に Black 視点。
        hp_lookup: gtp(str) -> humanPolicy(float) のルックアップ関数。
        opp_sign: 相手（子局面の手番）の player_sign（Black=1, White=-1）。
        sharpness_weight: 鋭さ項 S のブレンド重み。
    Returns:
        (E, S, D): 期待損失・鋭さ（二次モーメント）・ブレンド済み難解さ。
    """
    if not opp_move_infos:
        return 0.0, 0.0, 0.0
    opp_scores = [mi.get("scoreLead", 0.0) * opp_sign for mi in opp_move_infos]
    best_opp = max(opp_scores)
    weighted = []
    for mi, s in zip(opp_move_infos, opp_scores):
        ptloss = max(0.0, best_opp - s)
        hp = max(0.0, hp_lookup(mi.get("move", "")))
        weighted.append((hp, ptloss))
    total_hp = sum(hp for hp, _ in weighted)
    if total_hp <= 0.0:
        # humanPolicy 全ゼロ: E 退化 → 一様重みの鋭さのみで評価
        n = len(weighted)
        S = sum(ptloss * ptloss for _, ptloss in weighted) / n
        return 0.0, S, sharpness_weight * S
    E = sum(hp * ptloss for hp, ptloss in weighted) / total_hp
    S = sum(hp * ptloss * ptloss for hp, ptloss in weighted) / total_hp
    D = E + sharpness_weight * S
    return E, S, D


def _maze_net_score(difficulty, own_loss, risk_lambda):
    """ネットスコア N = D - λ×own_loss。"""
    return difficulty - risk_lambda * own_loss


def _maze_select_best(candidates):
    """N 最大の候補を返す。空なら None。"""
    if not candidates:
        return None
    return max(candidates, key=lambda c: c["N"])
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_maze.py -v`
Expected: PASS（全 9 ケース）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_maze.py
git commit -m "feat(maze): 難解さ計算の純粋関数と単体テストを追加"
```

---

## Task 2: AI_MAZE 定数と戦略リスト登録（constants.py）

**Files:**
- Modify: `katrain/core/constants.py:61`（`AI_HUNT_DIVERGE` 定義の直後）, `:68`（`AI_STRATEGIES`）, `:90`（`AI_STRATEGIES_RECOMMENDED_ORDER` 末尾）, `AI_STRENGTH` dict

- [ ] **Step 1: 定数を追加**

`katrain/core/constants.py` の `AI_HUNT_DIVERGE = "ai:hunt_diverge"`（61行目）の直後に追加:

```python
AI_MAZE = "ai:maze"
```

- [ ] **Step 2: AI_STRATEGIES に登録**

`AI_STRATEGIES = ...`（68行目）の末尾リストに `AI_MAZE` を追加:

```python
AI_STRATEGIES = AI_STRATEGIES_ENGINE + AI_STRATEGIES_POLICY + [AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE, AI_MAZE]
```

- [ ] **Step 3: AI_STRATEGIES_RECOMMENDED_ORDER に登録**

`AI_STRATEGIES_RECOMMENDED_ORDER` リスト（69-91行目）の `AI_HUNT_DIVERGE,` の直後（`]` の前）に追加:

```python
    AI_HUNT_DIVERGE,
    AI_MAZE,
]
```

- [ ] **Step 4: AI_STRENGTH に登録**

`AI_STRENGTH` dict（93行目〜）の中、`AI_HUNT_DIVERGE: float("nan"),`（114行目）の直後に追加:

```python
    AI_MAZE: float("nan"),
```

- [ ] **Step 5: import が壊れていないか確認**

Run: `python -c "from katrain.core.constants import AI_MAZE, AI_STRATEGIES; print(AI_MAZE in AI_STRATEGIES)"`
Expected: `True`

- [ ] **Step 6: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat(maze): AI_MAZE 定数と戦略リスト登録を追加"
```

---

## Task 3: AI_OPTION_VALUES と AI_OPTION_ORDER（constants.py）

GUI のスライダー種別と表示順を定義する。

**Files:**
- Modify: `katrain/core/constants.py`（`AI_OPTION_VALUES` dict の末尾 `}` の前 = 206行目付近, `AI_OPTION_ORDER` dict の末尾 `}` の前 = 269行目付近）

- [ ] **Step 1: AI_OPTION_VALUES に 5 パラメータを追加**

`AI_OPTION_VALUES` dict 内、`"jigo_deception_13_phase2_target": [-0.5, -1.0, -1.5, -2.0],`（206行目）の直後（dict 閉じ `}` の前）に追加:

```python
    # ===== MazeStrategy（9路盤専用） =====
    "maze_candidates_k": list(range(6, 25)),  # 6〜24
    "maze_hard_cap": [x / 2 for x in range(4, 25)],  # 2.0〜12.0（0.5刻み）
    "maze_risk_lambda": [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0],
    "maze_sharpness_weight": [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0],
    "maze_child_visits": [100, 200, 300, 400, 600, 800],
```

- [ ] **Step 2: AI_OPTION_ORDER に表示順を追加**

`AI_OPTION_ORDER` dict 内、`"jigo_deception_13_phase2_target": 15,`（269行目）の直後（dict 閉じ `}` の前）に追加:

```python
    "maze_candidates_k": 0,
    "maze_hard_cap": 1,
    "maze_risk_lambda": 2,
    "maze_sharpness_weight": 3,
    "maze_child_visits": 4,
```

- [ ] **Step 3: 構文確認**

Run: `python -c "from katrain.core.constants import AI_OPTION_VALUES; print(AI_OPTION_VALUES['maze_candidates_k'][:3], AI_OPTION_VALUES['maze_hard_cap'][-1])"`
Expected: `[6, 7, 8] 12.0`

- [ ] **Step 4: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat(maze): AI_OPTION_VALUES/ORDER に迷路戦略の5パラメータを追加"
```

---

## Task 4: パッケージ config.json の既定値

**Files:**
- Modify: `katrain/config.json:239-246`（`"ai:siege"` ブロックの直後、`"ai"` セクション閉じ括弧の前）

- [ ] **Step 1: ai:maze ブロックを追加**

`katrain/config.json` の `"ai:siege": { ... }` ブロック（239-245行目）の閉じ `}` の後にカンマを付け、続けて追加する。変更後は以下の形:

```json
        "ai:siege": {
            "siege_transition_move": 40,
            "siege_min_group_size": 5,
            "concede_max_loss": 4.0,
            "siege_max_loss": 5.0,
            "siege_proximity_stddev": 3.0,
            "siege_instability_min": 0.3
        },
        "ai:maze": {
            "maze_candidates_k": 18,
            "maze_hard_cap": 8.0,
            "maze_risk_lambda": 0.3,
            "maze_sharpness_weight": 0.5,
            "maze_child_visits": 400
        }
    },
```

- [ ] **Step 2: JSON が妥当か確認**

Run: `python -c "import json; d=json.load(open('katrain/config.json', encoding='utf-8')); print(d['ai']['ai:maze'])"`
Expected: `{'maze_candidates_k': 18, 'maze_hard_cap': 8.0, 'maze_risk_lambda': 0.3, 'maze_sharpness_weight': 0.5, 'maze_child_visits': 400}`

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat(maze): パッケージ config.json に ai:maze 既定値を追加"
```

---

## Task 5: ユーザーローカル config.json の既定値（メインセッション必須）

> **重要（CLAUDE.md より）**: `C:\Users\iwaki\.katrain\config.json` の編集はサブエージェントに委任しない。**メインセッションで直接 Edit する**。GUI は保存済みキーのみ表示するため、このファイルにキーが無いとスライダーが現れない。

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（`ai` セクション内）

- [ ] **Step 1: 現在の ai セクション構造を確認**

Run: `python -c "import json; d=json.load(open(r'C:\Users\iwaki\.katrain\config.json', encoding='utf-8')); print('ai:siege' in d['ai'], 'ai:maze' in d['ai'])"`
Expected: `True False`（siege はあり、maze はまだ無い）

- [ ] **Step 2: ai:maze ブロックを追加**

`C:\Users\iwaki\.katrain\config.json` の `ai` セクション内に、Task 4 と同じ内容のブロックを追加する（既存の最後の `ai:*` エントリの後ろにカンマ区切りで挿入。末尾要素になる場合は直前要素にカンマを付ける）:

```json
        "ai:maze": {
            "maze_candidates_k": 18,
            "maze_hard_cap": 8.0,
            "maze_risk_lambda": 0.3,
            "maze_sharpness_weight": 0.5,
            "maze_child_visits": 400
        }
```

- [ ] **Step 3: JSON が妥当か確認**

Run: `python -c "import json; d=json.load(open(r'C:\Users\iwaki\.katrain\config.json', encoding='utf-8')); print(d['ai']['ai:maze'])"`
Expected: `{'maze_candidates_k': 18, 'maze_hard_cap': 8.0, 'maze_risk_lambda': 0.3, 'maze_sharpness_weight': 0.5, 'maze_child_visits': 400}`

- [ ] **Step 4: コミット不要**

ユーザーローカル設定は git 管理外。コミットしない。

---

## Task 6: MazeStrategy クラス本体（ai.py）

2手先読み照会とネット選択を行う中核クラス。Task 1 の純粋関数を使う。

**Files:**
- Modify: `katrain/core/ai.py:9-16`（import に `AI_MAZE` 追加）
- Modify: `katrain/core/ai.py`（`@register_strategy(AI_HUNT_DIVERGE)` の `HuntDivergenceStrategy` クラス定義の後ろ、ファイル後半のクラス群の末尾に新クラスを追加。`def generate_ai_move` の定義より前であること）

- [ ] **Step 1: import に AI_MAZE を追加**

`katrain/core/ai.py` の constants インポート行（16行目、`...AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE` で終わる行）の末尾に `, AI_MAZE` を追加:

```python
    OUTPUT_ERROR, OUTPUT_INFO, PRIORITY_EXTRA_AI_QUERY, ADDITIONAL_MOVE_ORDER, AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE, AI_MAZE
```

- [ ] **Step 2: MazeStrategy クラスを追加**

`HuntDivergenceStrategy` クラス定義の終わり（`def generate_ai_move` の直前）に以下を追加:

```python
@register_strategy(AI_MAZE)
class MazeStrategy(AIStrategy):
    """迷路戦略 — 9路盤専用。相手が最善応手を見つけるのに最も深い読みを要する手を選び、
    対局を難解化する。各候補手 M を打った後の子局面を humanSL 9段で2手先読み照会し、
    難解さ D = E + w×S を計算、ネットスコア N = D − λ×own_loss を argmax 選択する。
    """

    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log("[MazeStrategy] Starting move generation", OUTPUT_DEBUG)
        self.wait_for_analysis()

        # ---- 設定読み込み ----
        K = int(self.settings.get("maze_candidates_k", 18))
        hard_cap = self.settings.get("maze_hard_cap", 8.0)
        risk_lambda = self.settings.get("maze_risk_lambda", 0.3)
        sharpness_weight = self.settings.get("maze_sharpness_weight", 0.5)
        child_visits = int(self.settings.get("maze_child_visits", 400))
        human_profile = "rank_9d"
        self.game.katrain.log(
            f"[MazeStrategy] Settings: K={K}, hard_cap={hard_cap}, lambda={risk_lambda}, "
            f"sharpness_weight={sharpness_weight}, child_visits={child_visits}", OUTPUT_DEBUG
        )

        sign = self.cn.player_sign(self.cn.next_player)
        opp_sign = -sign
        engine = self.game.engines[self.cn.player]
        bx, by = self.game.board_size
        candidate_moves = self.cn.candidate_moves

        # ---- 9路盤ガード ----
        if (bx, by) != (9, 9):
            self.game.katrain.log(
                f"[MazeStrategy] Board {bx}x{by} != 9x9, falling back to KataGo top move", OUTPUT_DEBUG
            )
            if not candidate_moves:
                return Move(None, player=self.cn.next_player), "Non-9x9, no candidates"
            top = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
            return top, "Non-9x9 board — using KataGo top move"

        if not candidate_moves:
            self.game.katrain.log("[MazeStrategy] No candidate moves, passing", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "No candidates, passing"

        # ---- 自分の候補手集合（own_loss <= hard_cap の上位 K 手） ----
        # 現局面解析は root に humanSLProfile が無くクリーン。relativePointsLost = 最善手からのズレ。
        my_cands = []
        for c in candidate_moves:
            rpl = c.get("relativePointsLost")
            if rpl is None:
                continue
            own_loss = max(0.0, rpl)
            if own_loss <= hard_cap:
                my_cands.append({"move": c["move"], "own_loss": own_loss})
            if len(my_cands) >= K:
                break
        self.game.katrain.log(
            f"[MazeStrategy] Candidates: {len(my_cands)} (own_loss<={hard_cap}, top {K})", OUTPUT_DEBUG
        )
        if not my_cands:
            top = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
            return top, "All moves exceed hard_cap — using KataGo top move"

        # ---- 各候補で 2手先読み照会 + 難解さ計算 ----
        for cand in my_cands:
            mv = Move.from_gtp(cand["move"], player=self.cn.next_player)
            human_policy, opp_infos = self._query_child(engine, mv, human_profile, child_visits)
            if opp_infos is None:
                cand["D"] = None  # 照会失敗
                continue
            hp_lookup = self._make_hp_lookup(human_policy, bx, by)
            E, S, D = _maze_compute_difficulty(opp_infos, hp_lookup, opp_sign, sharpness_weight)
            cand["E"], cand["S"], cand["D"] = E, S, D
            cand["N"] = _maze_net_score(D, cand["own_loss"], risk_lambda)
            self.game.katrain.log(
                f"[MazeStrategy] {cand['move']}: own_loss={cand['own_loss']:.2f} "
                f"E={E:.2f} S={S:.2f} D={D:.2f} N={cand['N']:.2f}", OUTPUT_DEBUG
            )

        # ---- 選択 ----
        scored = [c for c in my_cands if c.get("D") is not None]
        pick = _maze_select_best(scored)
        if pick is None:
            top = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
            self.game.katrain.log(
                "[MazeStrategy] All child queries failed — using KataGo top move", OUTPUT_ERROR
            )
            return top, "Child queries failed — using KataGo top move"

        aimove = Move.from_gtp(pick["move"], player=self.cn.next_player)
        ai_thoughts = (
            f"Maze: chose {pick['move']} (N={pick['N']:.2f}, D={pick['D']:.2f}, "
            f"E={pick['E']:.2f}, own_loss={pick['own_loss']:.2f})"
        )
        self.game.katrain.log(f"[MazeStrategy] Selected: {ai_thoughts}", OUTPUT_DEBUG)
        return aimove, ai_thoughts

    def _query_child(self, engine, move, human_profile, child_visits):
        """move を打った後の子局面を2段照会する。

        Returns:
            (human_policy(list), opp_move_infos(list)) を返す。失敗時は (None, None)。
        """
        # --- 子 Stage 1: humanSL（humanPolicy 取得・maxVisits=1） ---
        s1 = {"result": None, "error": False}

        def _s1_cb(a, partial):
            if not partial:
                s1["result"] = a

        def _s1_err(a):
            s1["error"] = True
            self.game.katrain.log(f"[MazeStrategy] Child Stage1 error ({move.gtp()}): {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=_s1_cb, error_callback=_s1_err,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=True,
            next_move=move,
            extra_settings={"humanSLProfile": human_profile, "maxVisits": 1},
        )
        while not (s1["error"] or s1["result"]):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)
        if s1["error"] or not s1["result"] or "humanPolicy" not in s1["result"]:
            return None, None
        human_policy = s1["result"]["humanPolicy"]

        # --- 子 Stage 2: クリーン（scoreLead 取得） ---
        s2 = {"result": None, "error": False}

        def _s2_cb(a, partial):
            if not partial:
                s2["result"] = a

        def _s2_err(a):
            s2["error"] = True
            self.game.katrain.log(f"[MazeStrategy] Child Stage2 error ({move.gtp()}): {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=_s2_cb, error_callback=_s2_err,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=False,
            next_move=move,
            extra_settings={"maxVisits": child_visits, "wideRootNoise": 0.0},
        )
        while not (s2["error"] or s2["result"]):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)
        if s2["error"] or not s2["result"]:
            return None, None
        return human_policy, s2["result"].get("moveInfos", [])

    def _make_hp_lookup(self, human_policy, bx, by):
        """humanPolicy フラット配列を gtp→prob ルックアップ関数に変換（Jigo と同じ index 変換）。"""
        next_player = self.cn.next_player

        def _lookup(gtp):
            if gtp == "pass":
                return human_policy[-1] if len(human_policy) > bx * by else 0.0
            try:
                m = Move.from_gtp(gtp, player=next_player)
                if m.coords is None:
                    return 0.0
                x, y = m.coords
                idx = (by - y - 1) * bx + x
                return human_policy[idx] if 0 <= idx < len(human_policy) else 0.0
            except Exception:
                return 0.0

        return _lookup
```

- [ ] **Step 3: 既存の純粋関数テストが壊れていないか確認**

Run: `python -m pytest tests/test_maze.py -v`
Expected: PASS（Task 1 の 9 ケースが引き続き成功。クラス追加で import が壊れていないことを確認）

- [ ] **Step 4: モジュールが import でき、登録されているか確認**

Run: `python -c "from katrain.core.ai import STRATEGY_REGISTRY, MazeStrategy; from katrain.core.constants import AI_MAZE; print(STRATEGY_REGISTRY[AI_MAZE].__name__)"`
Expected: `MazeStrategy`

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat(maze): MazeStrategy 本体（2手先読み照会・ネット選択）を追加"
```

---

## Task 7: katrain_debug の --strategy maze 対応

CLI で対局不要に挙動を確認できるようにする。

**Files:**
- Modify: `katrain_debug/runner.py`（import 行 + `STRATEGY_NAME_MAP`）

- [ ] **Step 1: import に AI_MAZE を追加**

`katrain_debug/runner.py:11` の `AI_JIGO, AI_ANTIMIRROR,` を以下に変更（`AI_MAZE` を追加）:

```python
    AI_JIGO, AI_ANTIMIRROR, AI_MAZE,
```

- [ ] **Step 2: STRATEGY_NAME_MAP に追加**

`STRATEGY_NAME_MAP`（runner.py:20〜）の `"hunt_diverge": AI_HUNT_DIVERGE,`（42行目）の直後に追加:

```python
    "maze": AI_MAZE,
```

- [ ] **Step 3: マッピングを確認**

Run: `python -c "from katrain_debug.runner import STRATEGY_NAME_MAP; print(STRATEGY_NAME_MAP['maze'])"`
Expected: `ai:maze`

- [ ] **Step 4: 既存の debug runner テストが壊れていないか確認**

Run: `python -m pytest tests/test_debug_runner.py -v`
Expected: PASS（既存テストが引き続き成功。`maze` が choices に増えたことで失敗するアサーションが無いことを確認）

- [ ] **Step 5: コミット**

```bash
git add katrain_debug/runner.py
git commit -m "feat(maze): katrain_debug に --strategy maze を追加"
```

---

## Task 8: i18n（戦略名・aihelp・パラメータラベル）

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`

- [ ] **Step 1: 日本語 .po に追記**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の末尾に以下の msgid/msgstr を追加（既存の `ai:hunt` エントリ群と同じ形式）:

```po
msgid "ai:maze"
msgstr "迷路"

msgid "aihelp:maze"
msgstr "9路盤専用。相手が最善手を見つけるのに最も深い読みを要する手を選び、対局を難解化します。相手が読み切れず間違えれば敗北につながる局面を作り続けます。常に最善手を打つわけではなく、自分の損失（ハード上限内）と相手の期待損失を天秤にかけて手を選びます。"

msgid "maze_candidates_k"
msgstr "候補手数"

msgid "maze_hard_cap"
msgstr "自分の許容損失上限(目)"

msgid "maze_risk_lambda"
msgstr "自損ペナルティ(小=難解さ優先)"

msgid "maze_sharpness_weight"
msgstr "鋭さの重み"

msgid "maze_child_visits"
msgstr "子局面の探索数"
```

- [ ] **Step 2: 英語 .po に追記**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の末尾に追加:

```po
msgid "ai:maze"
msgstr "Maze"

msgid "aihelp:maze"
msgstr "9x9 only. Picks the move that forces the opponent to read the deepest to find the best reply, making the game maximally hard. Keeps creating double-edged positions where a wrong reply loses. It does not always play the best move: it balances its own loss (within a hard cap) against the opponent's expected mistake."

msgid "maze_candidates_k"
msgstr "Candidate moves"

msgid "maze_hard_cap"
msgstr "Own loss cap (pts)"

msgid "maze_risk_lambda"
msgstr "Own-loss penalty (low=harder)"

msgid "maze_sharpness_weight"
msgstr "Sharpness weight"

msgid "maze_child_visits"
msgstr "Child position visits"
```

- [ ] **Step 3: .mo を再コンパイル**

Run: `python tools/compile_mo.py`
Expected: エラーなく完了（各 locale の `.mo` が更新される）

- [ ] **Step 4: 翻訳が引けるか確認**

Run: `python -c "import json; [print(p, ':', __import__('gettext').translation('katrain', 'katrain/i18n/locales', [p]).gettext('ai:maze')) for p in ['jp','en']]"`
Expected: `jp : 迷路` と `en : Maze`

- [ ] **Step 5: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "feat(maze): i18n に迷路戦略の名称・aihelp・パラメータラベルを追加"
```

---

## Task 9: CLI 統合スモーク検証（KataGo + humanSL モデル必須・手動）

純粋関数テストでは検証できない「2手先読み照会が実際に humanPolicy と moveInfos を返すか」をライブで確認する。

**前提:** `C:\Users\iwaki\.katrain\config.json` の `humanlike_model` に humanSL モデル（`b18c384nbt-humanv0.bin.gz`）が設定済みであること。未設定だと humanSL 系戦略は全滅する。

**Files:**
- Create: `tests/data/maze_9x9.sgf`（9路盤テスト用フィクスチャ。`tests/data/` に 9x9 SGF が存在しないため新規作成）

- [ ] **Step 1: 9路盤 SGF フィクスチャを作成**

`tests/data/maze_9x9.sgf` を作成（20手の合法な 9路対局）:

```
(;GM[1]FF[4]SZ[9]KM[7]PB[B]PW[W];B[ee];W[cc];B[gg];W[gc];B[cg];W[eg];B[ge];W[ec];B[dh];W[ce];B[gd];W[fd];B[fe];W[ed];B[dg];W[df];B[eh];W[fg];B[fh];W[ff])
```

- [ ] **Step 2: 9路盤の SGF で単一局面実行**

```bash
python -m katrain_debug --sgf tests/data/maze_9x9.sgf --move 12 --strategy maze --output text --log-level 2
```

Expected:
- クラッシュせず `=== Strategy Debug: MazeStrategy ===` が表示される
- 選択手（gtp）と explanation に `Maze: chose <gtp> (N=.., D=.., E=.., own_loss=..)` が出る
- ログ（log-level 2）に候補手ごとの `[MazeStrategy] <move>: own_loss=.. E=.. S=.. D=.. N=..` 行が並ぶ（= 仕様書の「候補手ごとの D/E/S/own_loss/N 表示」を満たす）
- フォールバック（`Non-9x9` / `Child queries failed`）になっていないこと

- [ ] **Step 3: 非9路盤でフォールバックを確認**

19路 SGF（例: `tests/data/ogs.sgf`）で実行:

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 20 --strategy maze --output text
```

Expected: explanation に `Non-9x9 board — using KataGo top move` が出る（9路ガードが機能）

- [ ] **Step 4: JSON 出力が壊れていないか確認**

```bash
python -m katrain_debug --sgf tests/data/maze_9x9.sgf --move 12 --strategy maze --output json 2>$null | python -c "import sys,json; d=json.loads(sys.stdin.read()); print(d['move'], d['strategy_class'])"
```

Expected: `<gtp> MazeStrategy`

- [ ] **Step 5: 問題があれば修正、フィクスチャをコミット**

- humanPolicy が取得できず常にフォールバックする場合: `humanlike_model` 設定と humanSLProfile 値（`rank_9d`）を確認。
- moveInfos が空の場合: `child_visits` を一時的に増やして再確認。
- スモークが通ったらフィクスチャをコミット:

```bash
git add tests/data/maze_9x9.sgf
git commit -m "test(maze): 9路盤スモーク検証用 SGF フィクスチャを追加"
```

- 戦略コードを修正した場合: `git commit -m "fix(maze): <内容>"`

---

## Task 10: self-play 検証スクリプトと校正データ

固定 SGF のバッチ評価では難解化効果を測れないため、self-play で相手（humanSL）の実現損失を比較する。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/maze/maze-results-20260523.md`

- [ ] **Step 1: GUI で self-play 対局を実施**

KaTrain を起動し（`python -m katrain`、`debug_level=1`）、以下を各 3 局以上対局させる:
- 黒=Maze（`ai:maze`） vs 白=Human-like 9段（`ai:human`, `human_kyu_rank=-8`）
- 黒=KataGo最善手（`ai:default`） vs 白=Human-like 9段（ベースライン）

各局終了後、ゲームレポートから **白（humanSL 側）の mean ptloss と accuracy** を記録する。

- [ ] **Step 2: 結果を校正データに記録**

`docs/superpowers/specs/calibration-data/maze/maze-results-20260523.md` を作成し、以下の表を記入:

```markdown
# 迷路戦略 self-play 検証結果（2026-05-23）

## 設定
- Maze: 既定値（K=18, hard_cap=8.0, lambda=0.3, sharpness_weight=0.5, child_visits=400）
- 相手: ai:human / human_kyu_rank=-8（9段） / 白番

## 結果（白=humanSL 側の実現損失）

| 対 AI | 局数 | 白 mean ptloss | 白 accuracy | 備考 |
|---|---|---|---|---|
| Maze | 3 | (記入) | (記入) | |
| KataGo最善手（baseline） | 3 | (記入) | (記入) | |

## 判定
Maze の方が白 mean ptloss が高ければ「難解化」が機能（相手の誤りを増やせている）。

## 所見
(記入: 思考時間/手、明らかな悪手の有無、パラメータ調整の必要性)
```

- [ ] **Step 3: パラメータ調整の要否を判断**

- Maze 側の自分の mean ptloss が大きすぎる（局を頻繁に落とす）→ `maze_risk_lambda` を上げる or `maze_hard_cap` を下げる。
- 相手の損失が baseline と変わらない → `maze_sharpness_weight` を上げる or `maze_candidates_k` を増やす。
- 調整した場合は既定値（constants.py / config.json 2箇所）を更新し再検証。

- [ ] **Step 4: コミット**

```bash
git add docs/superpowers/specs/calibration-data/maze/maze-results-20260523.md
git commit -m "docs(maze): self-play 検証結果（校正データ）を追加"
```

---

## Task 11: ドキュメント更新（CLAUDE.md / ai-parameters.md）

> **注意（CLAUDE.md より）**: `.claude/rules/` 配下の編集は `dontAsk` モードで Edit が拒否されることがある。拒否されたら **サブエージェント（Agent tool）経由で編集・コミット**する。

**Files:**
- Modify: `CLAUDE.md`（概要セクションの戦略一覧、`ai.py` の説明）
- Modify: `.claude/rules/ai-parameters.md`（パラメータテーブル追加）

- [ ] **Step 1: CLAUDE.md に MazeStrategy を追記**

`CLAUDE.md` の「主な改修」行と、ディレクトリ構造の `ai.py` 説明行に `MazeStrategy`（9路盤専用の難解化戦略）を追加する。例:

```
ai.py  -- AI着手生成（..., HuntDivergenceStrategy, DivergenceStrategy, MazeStrategy = 主な改修箇所）
```

「主な改修」概要にも一文追加: 「9路盤専用の難解化戦略（Maze）= 相手の読み切る手数を最大化」。

- [ ] **Step 2: ai-parameters.md にテーブルを追加**

`.claude/rules/ai-parameters.md` の末尾に以下を追加:

```markdown
## 迷路戦略（MazeStrategy）

9路盤専用の難解化戦略（`ai:maze`）。各候補手 M を打った後の子局面を humanSL 9段で2手先読み照会し、相手の期待損失 E と鋭さ S をブレンドした難解さ D = E + w×S を計算、ネットスコア N = D − λ×own_loss を argmax 選択する。相手モデルは humanSL 9段固定。9路以外は KataGo 最善手にフォールバック。

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| maze_candidates_k | 18 | 評価する自分の候補手の数（探索幅、6〜24） |
| maze_hard_cap | 8.0 | 自分の1手で許容する最大損失（目、2.0〜12.0）。破綻防止の絶対上限 |
| maze_risk_lambda | 0.3 | ネットスコアの own_loss 重み（小=難解さ優先。0.0/0.1/0.2/0.3/0.5/0.7/1.0） |
| maze_sharpness_weight | 0.5 | 難解さ D の鋭さ項 S のブレンド重み（0.0〜2.0） |
| maze_child_visits | 400 | 子局面 Stage 2 の visits（100/200/300/400/600/800） |

**検証**: 固定 SGF の batch_eval 不可（trajectory 形成型）。Maze vs humanSL9段 と KataGo最善手 vs humanSL9段 の self-play で相手の実現損失を比較する。Spec: `docs/superpowers/specs/2026-05-23-maze-strategy-9x9-design.md`
```

- [ ] **Step 3: コミット**

```bash
git add CLAUDE.md .claude/rules/ai-parameters.md
git commit -m "docs(maze): CLAUDE.md と ai-parameters.md に迷路戦略を追記"
```

（`.claude/rules/ai-parameters.md` の Edit が拒否された場合はサブエージェント経由で編集・コミットする）

---

## 完了条件

- [ ] `python -m pytest tests/test_maze.py -v` が全 PASS
- [ ] `python -m pytest --ignore=tests/test_ai.py` で既存テストが全 PASS（リグレッションなし）
- [ ] GUI の AI 選択に「迷路 / Maze」が表示され、5 つのスライダーが出る
- [ ] `python -m katrain_debug --sgf tests/data/maze_9x9.sgf --move 12 --strategy maze` が MazeStrategy で着手を返す
- [ ] 19路 SGF で 9路ガードのフォールバックが機能する
- [ ] self-play で相手 humanSL の mean ptloss が baseline 比で増加（難解化の効果確認）
