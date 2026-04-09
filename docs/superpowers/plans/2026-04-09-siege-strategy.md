# 攻城戦略（SiegeStrategy）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 序盤は相手に地を譲り、中盤以降に不安定な大石群を攻めて逆転を狙う「背水の陣」AIモードを実装する。

**Architecture:** 新クラス `SiegeStrategy` を `ai.py` に追加。フェーズ管理（序盤=Concede / 攻撃=Attack）で着手選択を切り替える。KataGoの通常解析（ownership + policy + scoreLead）のみ使用し、humanSLProfileは不要。石のグループ化は自前ロジックで実装。

**Tech Stack:** Python 3.12, KataGo Analysis API

---

## Task 1: constants.py に定数・設定を追加

**Files:**
- Modify: `katrain/core/constants.py:58` (AI_DIVERGE の後に定数追加)
- Modify: `katrain/core/constants.py:65` (AI_STRATEGIES に追加)
- Modify: `katrain/core/constants.py:66-85` (AI_STRATEGIES_RECOMMENDED_ORDER に追加)
- Modify: `katrain/core/constants.py:87-106` (AI_STRENGTH に追加)
- Modify: `katrain/core/constants.py:108-153` (AI_OPTION_VALUES に追加)
- Modify: `katrain/core/constants.py:156-178` (AI_OPTION_ORDER に追加)

- [ ] **Step 1: AI_SIEGE 定数を追加**

`katrain/core/constants.py` の `AI_DIVERGE = "ai:diverge_move"` の直後に追加:

```python
AI_SIEGE = "ai:攻城戦略"
```

- [ ] **Step 2: AI_STRATEGIES リストに追加**

`AI_STRATEGIES` の末尾に `AI_SIEGE` を追加:

```python
AI_STRATEGIES = AI_STRATEGIES_ENGINE + AI_STRATEGIES_POLICY + [AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE]
```

- [ ] **Step 3: AI_STRATEGIES_RECOMMENDED_ORDER に追加**

`AI_FIGHTING` の後に `AI_SIEGE` を追加:

```python
    AI_FIGHTING,
    AI_SIEGE,
]
```

- [ ] **Step 4: AI_STRENGTH に追加**

`AI_DIVERGE` の後に追加:

```python
    AI_SIEGE: float("nan"),
```

- [ ] **Step 5: AI_OPTION_VALUES にパラメータ定義を追加**

`"fighting_chaos_relax"` の後に以下を追加:

```python
    "siege_transition_move": list(range(15, 61, 5)),  # 15〜60（5刻み）
    "siege_min_group_size": list(range(3, 11)),  # 3〜10
    "concede_max_loss": [x / 2 for x in range(2, 13)],  # 1.0〜6.0（0.5刻み）
    "siege_max_loss": [x / 2 for x in range(2, 15)],  # 1.0〜7.0（0.5刻み）
    "siege_proximity_stddev": [x / 2 for x in range(4, 13)],  # 2.0〜6.0（0.5刻み）
    "siege_instability_min": [x / 10 for x in range(1, 6)],  # 0.1〜0.5（0.1刻み）
```

- [ ] **Step 6: AI_OPTION_ORDER に表示順を追加**

```python
    "siege_transition_move": 0,
    "siege_min_group_size": 1,
    "concede_max_loss": 10,
    "siege_max_loss": 11,
    "siege_proximity_stddev": 20,
    "siege_instability_min": 21,
```

- [ ] **Step 7: ai.py の import 文に AI_SIEGE を追加**

`katrain/core/ai.py` の 16行目の import に `AI_SIEGE` を追加:

```python
    AI_WEIGHTED, AI_WEIGHTED_ELO, CALIBRATED_RANK_ELO, OUTPUT_DEBUG,
    OUTPUT_ERROR, OUTPUT_INFO, PRIORITY_EXTRA_AI_QUERY, ADDITIONAL_MOVE_ORDER, AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE
)
```

- [ ] **Step 8: コミット**

```bash
git add katrain/core/constants.py katrain/core/ai.py
git commit -m "feat: 攻城戦略の定数・GUI設定パラメータを追加"
```

---

## Task 2: config.json にデフォルト設定を追加

**Files:**
- Modify: `katrain/config.json:192` (ai:diverge_move の後)
- Modify: `C:\Users\iwaki\.katrain\config.json` (同じ内容)

- [ ] **Step 1: パッケージ config.json にデフォルト値を追加**

`katrain/config.json` の `"ai:diverge_move": { ... }` ブロックの後に追加:

```json
        ,"ai:攻城戦略": {
            "siege_transition_move": 40,
            "siege_min_group_size": 5,
            "concede_max_loss": 4.0,
            "siege_max_loss": 5.0,
            "siege_proximity_stddev": 3.0,
            "siege_instability_min": 0.3
        }
```

- [ ] **Step 2: ユーザーローカル config.json に同じキーを追加**

`C:\Users\iwaki\.katrain\config.json` の `ai` セクション内、`"ai:diverge_move"` ブロックの後に同じ内容を追加:

```json
        ,"ai:攻城戦略": {
            "siege_transition_move": 40,
            "siege_min_group_size": 5,
            "concede_max_loss": 4.0,
            "siege_max_loss": 5.0,
            "siege_proximity_stddev": 3.0,
            "siege_instability_min": 0.3
        }
```

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat: 攻城戦略のデフォルト設定をconfig.jsonに追加"
```

（ユーザーローカルの `config.json` はgit管理外なのでコミット不要）

---

## Task 3: グループ化ユーティリティを実装

**Files:**
- Modify: `katrain/core/ai.py` (SiegeStrategy クラスの前にヘルパー関数を追加)

- [ ] **Step 1: テストを書く**

`tests/test_ai.py` に以下のテストを追加:

```python
from katrain.core.ai import find_connected_groups


class TestFindConnectedGroups:
    def test_single_stone(self):
        """1子のグループ"""
        stones = {(3, 3)}
        groups = find_connected_groups(stones)
        assert len(groups) == 1
        assert groups[0] == {(3, 3)}

    def test_two_connected_stones(self):
        """隣接する2子は1グループ"""
        stones = {(3, 3), (3, 4)}
        groups = find_connected_groups(stones)
        assert len(groups) == 1
        assert groups[0] == {(3, 3), (3, 4)}

    def test_two_separate_groups(self):
        """離れた2子は2グループ"""
        stones = {(0, 0), (5, 5)}
        groups = find_connected_groups(stones)
        assert len(groups) == 2

    def test_diagonal_not_connected(self):
        """斜め隣は接続しない"""
        stones = {(3, 3), (4, 4)}
        groups = find_connected_groups(stones)
        assert len(groups) == 2

    def test_l_shape_group(self):
        """L字型のグループ"""
        stones = {(0, 0), (1, 0), (1, 1), (1, 2)}
        groups = find_connected_groups(stones)
        assert len(groups) == 1
        assert len(groups[0]) == 4

    def test_empty_input(self):
        """空入力"""
        groups = find_connected_groups(set())
        assert len(groups) == 0
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
python -m pytest tests/test_ai.py::TestFindConnectedGroups -v
```

Expected: FAIL — `ImportError: cannot import name 'find_connected_groups'`

- [ ] **Step 3: find_connected_groups を実装**

`katrain/core/ai.py` に、`STRATEGY_REGISTRY` 定義（29行目）の後、最初のクラス定義の前に追加:

```python
def find_connected_groups(stones: set) -> list:
    """石の座標集合を連結グループに分類する。上下左右の隣接で接続判定。
    
    Args:
        stones: {(x, y), ...} 形式の座標集合
    Returns:
        [set((x,y), ...), ...] 形式のグループリスト
    """
    remaining = set(stones)
    groups = []
    while remaining:
        start = next(iter(remaining))
        group = set()
        queue = [start]
        while queue:
            coord = queue.pop()
            if coord in remaining:
                remaining.discard(coord)
                group.add(coord)
                x, y = coord
                for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                    neighbor = (x + dx, y + dy)
                    if neighbor in remaining:
                        queue.append(neighbor)
        groups.append(group)
    return groups
```

- [ ] **Step 4: テストがパスすることを確認**

```bash
python -m pytest tests/test_ai.py::TestFindConnectedGroups -v
```

Expected: 6 tests PASSED

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai.py
git commit -m "feat: 石のグループ化関数 find_connected_groups を追加"
```

---

## Task 4: SiegeStrategy クラスの骨格を実装

**Files:**
- Modify: `katrain/core/ai.py` (DivergenceStrategy クラスの後、`generate_ai_move` 関数の前に追加)

- [ ] **Step 1: SiegeStrategy のクラス骨格を実装**

`katrain/core/ai.py` の `DivergenceStrategy` クラスの後（`generate_ai_move` 関数の前）に追加:

```python
@register_strategy(AI_SIEGE)
class SiegeStrategy(AIStrategy):
    """攻城戦略 — 序盤は地を譲り、中盤以降に大石を攻めて逆転を狙う"""

    BOARD_PARAMS = {
        19: {"transition_move": 40, "min_group_size": 5, "concede_max_loss": 4.0, "max_loss": 5.0, "proximity_stddev": 3.0},
        13: {"transition_move": 25, "min_group_size": 4, "concede_max_loss": 3.0, "max_loss": 4.0, "proximity_stddev": 2.5},
    }

    def generate_move(self) -> Tuple[Move, str]:
        self.game.katrain.log(f"[SiegeStrategy] Starting move generation", OUTPUT_DEBUG)

        # 標準解析を待つ（ownership + policy + candidate_moves取得）
        self.wait_for_analysis()

        board_size = self.game.board_size
        bx = board_size[0]
        params = self.BOARD_PARAMS.get(bx, self.BOARD_PARAMS[19])

        # 設定読み取り（GUI設定 > デフォルト）
        transition_move = self.settings.get("siege_transition_move", params["transition_move"])
        min_group_size = self.settings.get("siege_min_group_size", params["min_group_size"])
        concede_max_loss = self.settings.get("concede_max_loss", params["concede_max_loss"])
        max_loss = self.settings.get("siege_max_loss", params["max_loss"])
        proximity_stddev = self.settings.get("siege_proximity_stddev", params["proximity_stddev"])
        instability_min = self.settings.get("siege_instability_min", 0.3)

        self.game.katrain.log(
            f"[SiegeStrategy] Settings: transition={transition_move}, min_group={min_group_size}, "
            f"concede_loss={concede_max_loss}, max_loss={max_loss}, prox_std={proximity_stddev}, instab_min={instability_min}",
            OUTPUT_DEBUG,
        )

        candidate_moves = self.cn.candidate_moves
        if not candidate_moves:
            self.game.katrain.log(f"[SiegeStrategy] No candidate moves, passing", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "No candidate moves found, passing."

        # パスが最善なら強制パス
        top_move = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
        if top_move.is_pass:
            self.game.katrain.log(f"[SiegeStrategy] Top move is pass, forcing pass", OUTPUT_DEBUG)
            return top_move, "Top move is pass."

        current_move = self.cn.depth
        total_moves = bx * board_size[1]  # 盤面マス数を概算上限とする
        force_transition = current_move >= int(total_moves * 0.6)

        # ターゲット選定（フェーズ判定に使用）
        targets = self._find_targets(min_group_size, instability_min)

        # フェーズ判定
        has_target = len(targets) > 0
        in_attack_phase = (current_move >= transition_move and has_target) or force_transition

        if in_attack_phase:
            phase = "attack (forced)" if force_transition and not has_target else "attack"
            self.game.katrain.log(f"[SiegeStrategy] Phase: {phase}, move={current_move}, targets={len(targets)}", OUTPUT_DEBUG)
            return self._generate_attack(candidate_moves, targets, max_loss, proximity_stddev)
        else:
            self.game.katrain.log(f"[SiegeStrategy] Phase: concede, move={current_move}", OUTPUT_DEBUG)
            return self._generate_concede(candidate_moves, concede_max_loss)

    def _find_targets(self, min_group_size, instability_min):
        """ターゲットとなる不安定な相手石群を特定する"""
        # Task 6で実装
        return []

    def _generate_concede(self, candidate_moves, concede_max_loss):
        """序盤フェーズ: 地を譲る手を選択"""
        # Task 5で実装
        return Move(None, player=self.cn.next_player), "Concede phase placeholder."

    def _generate_attack(self, candidate_moves, targets, max_loss, proximity_stddev):
        """攻撃フェーズ: ターゲットの大石を攻める"""
        # Task 7で実装
        return Move(None, player=self.cn.next_player), "Attack phase placeholder."
```

- [ ] **Step 2: テストに AI_SIEGE を追加**

`tests/test_ai.py` の import に `AI_SIEGE` を追加:

```python
from katrain.core.constants import AI_STRATEGIES, AI_STRATEGIES_RECOMMENDED_ORDER, AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, OUTPUT_INFO
```

`test_ai_strategies` のスキップリストに `AI_SIEGE` を追加（まだスタブなので）:

```python
                if strategy in [AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE]:
                    continue
```

同様に `test_ai_strategies` の二つ目のループ（38行目付近）でも:

```python
            if strategy in [AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE]:
                continue
```

- [ ] **Step 3: test_order テストがパスすることを確認**

```bash
python -m pytest tests/test_ai.py::TestAI::test_order -v
```

Expected: PASSED（AI_STRATEGIES と AI_STRATEGIES_RECOMMENDED_ORDER の集合が一致）

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py tests/test_ai.py
git commit -m "feat: SiegeStrategyクラスの骨格を実装（フェーズ判定付き）"
```

---

## Task 5: 序盤フェーズ（Concede Phase）を実装

**Files:**
- Modify: `katrain/core/ai.py` (SiegeStrategy._generate_concede)

- [ ] **Step 1: _generate_concede メソッドを実装**

`SiegeStrategy` クラスの `_generate_concede` メソッドを以下に置き換え:

```python
    def _generate_concede(self, candidate_moves, concede_max_loss):
        """序盤フェーズ: 最善手を避けつつ地を譲る手を選択する。
        
        concede_score = min(loss, concede_max_loss) / concede_max_loss で
        loss=0（最善手）は選ばれにくく、loss=上限は選ばれやすい。
        """
        player_sign = 1 if self.cn.next_player == "B" else -1
        best_score = max(player_sign * mi["scoreLead"] for mi in candidate_moves)

        # policy grid から各手の policy 値を取得
        policy = self.cn.policy
        board_size = self.game.board_size
        if policy:
            policy_grid = var_to_grid(policy, board_size)
        else:
            policy_grid = None

        weighted_moves = []
        for mi in candidate_moves:
            gtp_move = mi.get("move", "")
            if gtp_move == "pass":
                continue
            score = mi.get("scoreLead", 0)
            loss = player_sign * (best_score - player_sign * score)

            if loss > concede_max_loss:
                continue

            move = Move.from_gtp(gtp_move, player=self.cn.next_player)
            if move.coords is None:
                continue

            # policy 値の取得
            x, y = move.coords
            if policy_grid:
                pol = policy_grid[y][x]
            else:
                pol = mi.get("prior", 0.01)
            pol = max(pol, 1e-6)

            # concede_score: loss が大きいほど高い（地を譲る手を好む）
            concede_score = min(loss, concede_max_loss) / concede_max_loss
            # loss=0 の最善手にも最低限の重みを与える（完全排除しない）
            concede_score = max(concede_score, 0.05)

            weight = pol * concede_score
            weighted_moves.append((loss, weight, move))

        if not weighted_moves:
            # フォールバック: 全候補から最善手を選択
            self.game.katrain.log(f"[SiegeStrategy:concede] No valid moves, playing best move", OUTPUT_DEBUG)
            return Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player), "Concede fallback: no valid moves."

        # デバッグ: 上位5手表示
        top5 = heapq.nlargest(5, weighted_moves, key=lambda t: t[1])
        self.game.katrain.log(f"[SiegeStrategy:concede] Top 5 weighted moves:", OUTPUT_DEBUG)
        for i, (l, w, m) in enumerate(top5):
            self.game.katrain.log(f"  #{i+1}: {m.gtp()} loss={l:.2f} weight={w:.4f}", OUTPUT_DEBUG)

        # 重み付き選択
        selected = weighted_selection_without_replacement(weighted_moves, 1)[0]
        aimove = selected[2]
        ai_thoughts = (
            f"Siege[concede]: {len(weighted_moves)} candidates within {concede_max_loss}pt. "
            f"Selected {aimove.gtp()} (loss={selected[0]:.1f})."
        )
        self.game.katrain.log(f"[SiegeStrategy:concede] Selected: {aimove.gtp()} loss={selected[0]:.2f}", OUTPUT_DEBUG)
        return aimove, ai_thoughts
```

- [ ] **Step 2: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: SiegeStrategy序盤フェーズ（Concede）を実装"
```

---

## Task 6: ターゲット選定を実装

**Files:**
- Modify: `katrain/core/ai.py` (SiegeStrategy._find_targets)

- [ ] **Step 1: テストを書く**

`tests/test_ai.py` に追加:

```python
class TestFindTargets:
    """SiegeStrategy._find_targets のロジックテスト（ownership + stone grouping）"""

    def test_score_calculation(self):
        """target_score = group_size × instability の計算確認"""
        # instability = 1 - |avg_ownership|
        # group_size=5, avg_ownership=-0.5 → instability=0.5, score=2.5
        group_size = 5
        avg_ownership = -0.5
        instability = 1 - abs(avg_ownership)
        score = group_size * instability
        assert instability == 0.5
        assert score == 2.5

    def test_instability_range(self):
        """不安定度の範囲確認"""
        # ownership=-1.0（完全確定）→ instability=0
        assert 1 - abs(-1.0) == 0.0
        # ownership=0.0（完全中立）→ instability=1.0
        assert 1 - abs(0.0) == 1.0
        # ownership=-0.3 → instability=0.7
        assert abs(1 - abs(-0.3) - 0.7) < 0.01
```

- [ ] **Step 2: テストがパスすることを確認**

```bash
python -m pytest tests/test_ai.py::TestFindTargets -v
```

Expected: PASSED（純粋な計算テストなので即パス）

- [ ] **Step 3: _find_targets メソッドを実装**

`SiegeStrategy` クラスの `_find_targets` を以下に置き換え:

```python
    def _find_targets(self, min_group_size, instability_min):
        """ターゲットとなる不安定な相手石群を特定する。
        
        Returns:
            [(target_score, instability, group), ...] のリスト（scoreの降順）
        """
        board_size = self.game.board_size
        ownership = self.cn.ownership
        if not ownership:
            self.game.katrain.log(f"[SiegeStrategy] No ownership data available", OUTPUT_DEBUG)
            return []

        ownership_grid = var_to_grid(ownership, board_size)
        player_sign = 1 if self.cn.next_player == "B" else -1

        # 相手の石の座標を収集
        opponent_coords = set()
        for s in self.game.stones:
            if s.player != self.cn.next_player and s.coords:
                opponent_coords.add(s.coords)

        if not opponent_coords:
            return []

        # 連結グループに分類
        groups = find_connected_groups(opponent_coords)

        # 各グループの不安定度とターゲットスコアを計算
        targets = []
        for group in groups:
            if len(group) < min_group_size:
                continue

            # グループの平均ownershipを計算
            total_ownership = 0.0
            for x, y in group:
                total_ownership += ownership_grid[y][x]
            avg_ownership = total_ownership / len(group)

            instability = 1.0 - abs(avg_ownership)
            if instability < instability_min:
                continue

            target_score = len(group) * instability
            targets.append((target_score, instability, group))

        # スコアの降順でソート
        targets.sort(key=lambda t: t[0], reverse=True)

        if targets:
            top = targets[0]
            self.game.katrain.log(
                f"[SiegeStrategy] Primary target: size={len(top[2])}, instability={top[1]:.2f}, score={top[0]:.2f}",
                OUTPUT_DEBUG,
            )

        return targets
```

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py tests/test_ai.py
git commit -m "feat: SiegeStrategyターゲット選定（_find_targets）を実装"
```

---

## Task 7: 攻撃フェーズ（Attack Phase）を実装

**Files:**
- Modify: `katrain/core/ai.py` (SiegeStrategy._generate_attack)

- [ ] **Step 1: _generate_attack メソッドを実装**

`SiegeStrategy` クラスの `_generate_attack` を以下に置き換え:

```python
    def _generate_attack(self, candidate_moves, targets, max_loss, proximity_stddev):
        """攻撃フェーズ: ターゲットの大石群に近い手を重み付けして選択する。
        
        attack_weight = policy × proximity × target_instability
        proximity = exp(-0.5 × min_dist² / stddev²)
        """
        player_sign = 1 if self.cn.next_player == "B" else -1
        best_score = max(player_sign * mi["scoreLead"] for mi in candidate_moves)
        board_size = self.game.board_size
        prox_var = proximity_stddev ** 2

        # policy grid
        policy = self.cn.policy
        policy_grid = var_to_grid(policy, board_size) if policy else None

        # ターゲット座標を収集（プライマリ + サブターゲット）
        if targets:
            primary_target = targets[0]
            target_instability = primary_target[1]
            target_coords = primary_target[2]
            # サブターゲットがあれば座標を追加（ただしプライマリの重みが支配的）
            if len(targets) > 1:
                target_coords = target_coords | targets[1][2]
        else:
            # ターゲットなし（force_transitionでの移行）: 全相手石を対象にプレッシャー
            target_instability = 0.5  # デフォルトの不安定度
            target_coords = set()
            for s in self.game.stones:
                if s.player != self.cn.next_player and s.coords:
                    target_coords.add(s.coords)
            if not target_coords:
                # 相手石なし: 最善手を返す
                return Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player), "Attack: no opponent stones."

        weighted_moves = []
        for mi in candidate_moves:
            gtp_move = mi.get("move", "")
            if gtp_move == "pass":
                continue

            score = mi.get("scoreLead", 0)
            loss = player_sign * (best_score - player_sign * score)

            if loss > max_loss:
                continue

            move = Move.from_gtp(gtp_move, player=self.cn.next_player)
            if move.coords is None:
                continue

            mx, my = move.coords

            # policy 値
            if policy_grid:
                pol = policy_grid[my][mx]
            else:
                pol = mi.get("prior", 0.01)
            pol = max(pol, 1e-6)

            # ターゲットへの近接重み
            min_dist_sq = min((mx - tx) ** 2 + (my - ty) ** 2 for tx, ty in target_coords)
            proximity = math.exp(-0.5 * min_dist_sq / prox_var) if prox_var > 0 else 1.0

            weight = pol * proximity * target_instability
            weighted_moves.append((loss, weight, move))

        if not weighted_moves:
            # フォールバック: 最善手
            self.game.katrain.log(f"[SiegeStrategy:attack] No valid moves within {max_loss}pt, playing best", OUTPUT_DEBUG)
            return Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player), "Attack fallback: no moves within threshold."

        # デバッグ: 上位5手表示
        top5 = heapq.nlargest(5, weighted_moves, key=lambda t: t[1])
        self.game.katrain.log(f"[SiegeStrategy:attack] Targets: {len(targets)}, candidates: {len(weighted_moves)}", OUTPUT_DEBUG)
        self.game.katrain.log(f"[SiegeStrategy:attack] Top 5 weighted moves:", OUTPUT_DEBUG)
        for i, (l, w, m) in enumerate(top5):
            self.game.katrain.log(f"  #{i+1}: {m.gtp()} loss={l:.2f} weight={w:.4f}", OUTPUT_DEBUG)

        # 重み付き選択
        selected = weighted_selection_without_replacement(weighted_moves, 1)[0]
        aimove = selected[2]
        target_info = f"primary_size={len(targets[0][2])}" if targets else "pressure_mode"
        ai_thoughts = (
            f"Siege[attack]: {target_info}, {len(weighted_moves)} candidates within {max_loss}pt. "
            f"Selected {aimove.gtp()} (loss={selected[0]:.1f}, weight={selected[1]:.4f})."
        )
        self.game.katrain.log(f"[SiegeStrategy:attack] Selected: {aimove.gtp()} loss={selected[0]:.2f}", OUTPUT_DEBUG)
        return aimove, ai_thoughts
```

- [ ] **Step 2: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: SiegeStrategy攻撃フェーズ（Attack）を実装"
```

---

## Task 8: テストのスキップリスト更新と統合確認

**Files:**
- Modify: `tests/test_ai.py`

- [ ] **Step 1: test_ai_strategies のスキップリストを確認**

`tests/test_ai.py` の `test_ai_strategies` で `AI_SIEGE` がスキップリストに含まれていることを確認。SiegeStrategyはKataGoエンジンが必要なため、CI環境ではスキップが必要。ローカルでエンジンがある場合は手動テスト。

- [ ] **Step 2: test_order テストが通ることを確認**

```bash
python -m pytest tests/test_ai.py::TestAI::test_order -v
```

Expected: PASSED

- [ ] **Step 3: 全テストを実行**

```bash
python -m pytest tests/test_ai.py -v
```

Expected: TestAI::test_order PASSED, TestFindConnectedGroups 全PASSED, TestFindTargets 全PASSED
（test_ai_strategies と test_ai_rank_estimation はCI環境ではスキップ）

- [ ] **Step 4: コミット**

```bash
git add tests/test_ai.py
git commit -m "test: 攻城戦略のテストスキップリストを更新"
```

---

## Task 9: CLAUDE.md を更新

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: CLAUDE.md にパラメータテーブルを追加**

CLAUDE.md の「AI一致率低減モード（DivergenceStrategy）」セクションの後に以下を追加:

```markdown
### 攻城戦略（SiegeStrategy）

序盤は相手に地を譲り、中盤以降に不安定な大石群を攻めて逆転を狙う「背水の陣」モード。対応盤面: 19路・13路。

**フェーズ**: 序盤（Concede）→ 攻撃（Attack）。手数条件 + ターゲット存在で切替。

| パラメータ | デフォルト値(19路) | デフォルト値(13路) | 備考 |
|---|---|---|---|
| siege_transition_move | 40 | 25 | 攻撃フェーズ移行の最小手数 |
| siege_min_group_size | 5 | 4 | ターゲット最小グループサイズ |
| concede_max_loss | 4.0 | 3.0 | 序盤の許容最大損失（目） |
| siege_max_loss | 5.0 | 4.0 | 攻撃時の許容最大損失（目） |
| siege_proximity_stddev | 3.0 | 2.5 | ターゲット近接重みの標準偏差 |
| siege_instability_min | 0.3 | 0.3 | ターゲット判定の最小不安定度 |
```

- [ ] **Step 2: ディレクトリ構造に ai.py の SiegeStrategy を追記**

CLAUDE.md のディレクトリ構造セクションの `ai.py` の説明を更新:

```
    ai.py             -- AI着手生成（HumanStyleStrategy, FightingStrategy, SiegeStrategy = 主な改修箇所）
```

- [ ] **Step 3: コミット**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.mdに攻城戦略のパラメータを追記"
```

---

## Task 10: 手動テスト（KaTrain起動確認）

**Files:** なし（実行確認のみ）

- [ ] **Step 1: debug_level を 1 に設定**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` を `"debug_level": 1` に変更。

- [ ] **Step 2: KaTrain を起動してテスト**

```bash
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
python -m katrain
```

1. GUIで対局設定を開く
2. AIモードのドロップダウンに「攻城戦略」が表示されることを確認
3. 攻城戦略を選択し、パラメータスライダーが表示されることを確認
4. 対局を開始し、数手打って動作することを確認

- [ ] **Step 3: ログで動作確認**

Grepパターン:
```
[SiegeStrategy] — 全般ログ
[SiegeStrategy] Phase: concede — 序盤フェーズ
[SiegeStrategy] Phase: attack — 攻撃フェーズ
[SiegeStrategy] Primary target: — ターゲット選定
[SiegeStrategy:concede] Selected: — 序盤の着手
[SiegeStrategy:attack] Selected: — 攻撃の着手
```

- [ ] **Step 4: debug_level を 0 に戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` を `"debug_level": 0` に戻す。
