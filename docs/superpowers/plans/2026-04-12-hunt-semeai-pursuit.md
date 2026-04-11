# HuntStrategy 攻め合い追撃機能（Semeai Pursuit）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 攻め合い中にKataGoが死と判定した大石に対して、相手が勝負手を打った場合に手抜きせず詰め手を継続する機能を実装する

**Architecture:** 前手番のターゲット情報をGameNodeに記憶し、次の手番で相手の着手がターゲット付近か判定。リバティ数・ownership確信度・石群サイズで追撃可否を決定し、条件を満たせば `find_targets()` の結果にターゲットを再注入する。GUIチェックボックスでオン/オフ切り替え可能。

**Tech Stack:** Python 3.12, Kivy (GUI), KataGo (AI engine)

---

### Task 1: リバティ計算ヘルパー関数

**Files:**
- Modify: `katrain/core/ai.py:31-114`（モジュールレベル関数エリア）
- Test: `tests/test_ai.py`

- [ ] **Step 1: テストを書く**

`tests/test_ai.py` の末尾に追加：

```python
from katrain.core.ai import count_group_liberties


class TestCountGroupLiberties:
    def test_corner_group_liberties(self):
        # 19x19 board, -1 = empty, 0+ = chain id
        board = [[-1] * 19 for _ in range(19)]
        # Place a 2-stone group at (0,0) and (1,0) — chain id 0
        board[0][0] = 0
        board[0][1] = 0
        group_coords = {(0, 0), (1, 0)}
        board_size = (19, 19)
        libs = count_group_liberties(board, group_coords, board_size)
        # (0,0) neighbors: (1,0)=same group, (0,1)=empty → 1 liberty
        # (1,0) neighbors: (0,0)=same group, (2,0)=empty, (1,1)=empty → 2 liberties
        # Total unique: {(0,1), (2,0), (1,1)} = 3
        assert libs == 3

    def test_surrounded_group_zero_liberties(self):
        board = [[-1] * 5 for _ in range(5)]
        # Target stone at (2,2) — chain 0
        board[2][2] = 0
        # Surround with chain 1
        board[2][1] = 1
        board[2][3] = 1
        board[1][2] = 1
        board[3][2] = 1
        group_coords = {(2, 2)}
        libs = count_group_liberties(board, group_coords, (5, 5))
        assert libs == 0

    def test_large_group_shared_liberties(self):
        board = [[-1] * 9 for _ in range(9)]
        # L-shape group at (0,0), (1,0), (1,1)
        board[0][0] = 0
        board[0][1] = 0
        board[1][1] = 0
        group_coords = {(0, 0), (1, 0), (1, 1)}
        libs = count_group_liberties(board, group_coords, (9, 9))
        # Unique empty neighbors: (0,1), (2,0), (2,1), (1,2), (0,1) counted once
        # (0,0) → right (1,0)=group, down (0,1)=empty → {(0,1)}
        # (1,0) → left (0,0)=group, right (2,0)=empty, down (1,1)=group → {(2,0)}
        # (1,1) → left (0,1)=empty, right (2,1)=empty, up (1,0)=group, down (1,2)=empty → {(0,1),(2,1),(1,2)}
        # Total unique: {(0,1), (2,0), (2,1), (1,2)} = 4
        assert libs == 4
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_ai.py::TestCountGroupLiberties -v`
Expected: FAIL with `ImportError: cannot import name 'count_group_liberties'`

- [ ] **Step 3: ヘルパー関数を実装**

`katrain/core/ai.py` の `find_targets()` 関数の直前（line 57付近）に追加：

```python
def count_group_liberties(board, group_coords, board_size):
    """石群のリバティ数（呼吸点＝隣接する空点の数）を算出する。

    Args:
        board: 2D list [y][x] of chain IDs (-1 = empty)
        group_coords: set of (x, y) coordinates of the group
        board_size: (width, height)
    Returns:
        int: number of unique liberties
    """
    bx, by = board_size
    liberties = set()
    for x, y in group_coords:
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < bx and 0 <= ny < by and board[ny][nx] == -1:
                liberties.add((nx, ny))
    return len(liberties)
```

- [ ] **Step 4: テストがパスすることを確認**

Run: `pytest tests/test_ai.py::TestCountGroupLiberties -v`
Expected: 3 tests PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai.py
git commit -m "feat: リバティ計算ヘルパー関数 count_group_liberties を追加"
```

---

### Task 2: 追撃判定ロジック関数

**Files:**
- Modify: `katrain/core/ai.py:57付近`（モジュールレベル関数エリア、count_group_libertiesの後）
- Test: `tests/test_ai.py`

- [ ] **Step 1: テストを書く**

`tests/test_ai.py` の末尾に追加：

```python
from katrain.core.ai import evaluate_pursuit_targets


class TestEvaluatePursuitTargets:
    def _make_board(self, size=9):
        return [[-1] * size for _ in range(size)]

    def test_no_previous_targets(self):
        result = evaluate_pursuit_targets(
            previous_targets=[],
            opponent_move_coords=(4, 4),
            current_opponent_coords={(3, 3), (3, 4)},
            board=[[-1] * 9 for _ in range(9)],
            board_size=(9, 9),
            ownership_grid=None,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        assert result == []

    def test_opponent_move_far_from_target(self):
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": [(0, 0), (1, 0), (0, 1)], "size": 3}],
            opponent_move_coords=(8, 8),  # Far away
            current_opponent_coords={(0, 0), (1, 0), (0, 1)},
            board=[[-1] * 9 for _ in range(9)],
            board_size=(9, 9),
            ownership_grid=None,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        assert result == []

    def test_stones_removed_from_board(self):
        # Previous target coords no longer in current_opponent_coords
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": [(3, 3), (3, 4), (3, 5)], "size": 3}],
            opponent_move_coords=(3, 6),  # Near previous target
            current_opponent_coords=set(),  # Stones removed
            board=[[-1] * 9 for _ in range(9)],
            board_size=(9, 9),
            ownership_grid=None,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        assert result == []

    def test_pursue_high_liberties(self):
        board = [[-1] * 9 for _ in range(9)]
        # Place opponent stones — chain 0
        board[3][3] = 0
        board[4][3] = 0
        board[5][3] = 0
        target_coords = [(3, 3), (3, 4), (3, 5)]
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": target_coords, "size": 3}],
            opponent_move_coords=(3, 6),  # Adjacent to target
            current_opponent_coords={(3, 3), (3, 4), (3, 5)},
            board=board,
            board_size=(9, 9),
            ownership_grid=None,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        # Group has many liberties (>= 3), should pursue
        assert len(result) == 1
        assert result[0][2] == {(3, 3), (3, 4), (3, 5)}  # group coords

    def test_no_pursue_low_liberties_high_ownership(self):
        board = [[-1] * 9 for _ in range(9)]
        # Place opponent stone — chain 0
        board[4][4] = 0
        # Surround most sides — chain 1 (our stones)
        board[3][4] = 1
        board[5][4] = 1
        board[4][3] = 1
        # (4,5) is the only liberty
        target_coords = [(4, 4)]
        # ownership_grid: opponent's stone has high ownership for us
        ownership_grid = [[0.0] * 9 for _ in range(9)]
        ownership_grid[4][4] = 0.90  # Black owns this area strongly (player_sign=1)
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": target_coords, "size": 1}],
            opponent_move_coords=(4, 5),  # Adjacent to target
            current_opponent_coords={(4, 4)},
            board=board,
            board_size=(9, 9),
            ownership_grid=ownership_grid,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        # 1 liberty (< 3), ownership |0.90| >= 0.85, size < 10 → no pursuit
        assert result == []

    def test_pursue_low_liberties_low_ownership(self):
        board = [[-1] * 9 for _ in range(9)]
        board[4][4] = 0
        board[3][4] = 1
        board[5][4] = 1
        board[4][3] = 1
        target_coords = [(4, 4)]
        ownership_grid = [[0.0] * 9 for _ in range(9)]
        ownership_grid[4][4] = 0.70  # Not fully confirmed
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": target_coords, "size": 1}],
            opponent_move_coords=(4, 5),
            current_opponent_coords={(4, 4)},
            board=board,
            board_size=(9, 9),
            ownership_grid=ownership_grid,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        # 1 liberty (< 3), but ownership |0.70| < 0.85 → pursue
        assert len(result) == 1

    def test_large_group_stricter_threshold(self):
        board = [[-1] * 19 for _ in range(19)]
        target_coords = []
        for i in range(12):
            board[5][i] = 0
            target_coords.append((i, 5))
        # Place our stones to limit liberties to 2
        for i in range(12):
            board[4][i] = 1  # above
            board[6][i] = 1  # below
        board[5][12] = 1  # right end
        # Only liberty: left end at (-1, 5) is off-board, so...
        # Actually (0,5) already has the stone. Let me reconsider.
        # Liberties: check empty neighbors of group stones not occupied
        # All above/below/right blocked. Left of (0,5) is off-board.
        # So 0 liberties — but we want 2 liberties for this test
        # Let's remove two blockers
        board[4][0] = -1  # open above (0,5)
        board[4][1] = -1  # open above (1,5)
        ownership_grid = [[0.0] * 19 for _ in range(19)]
        for i in range(12):
            ownership_grid[5][i] = 0.88  # player_sign=1, so this is ours (high)
        result = evaluate_pursuit_targets(
            previous_targets=[{"coords": target_coords, "size": 12}],
            opponent_move_coords=(0, 4),  # Near target (distance 1 from (0,5))
            current_opponent_coords=set(target_coords),
            board=board,
            board_size=(19, 19),
            ownership_grid=ownership_grid,
            player_sign=1,
            pursue_proximity=2,
            pursue_min_liberties=3,
            pursue_ownership_threshold=0.85,
        )
        # 2 liberties (< 3), size=12 (>=10) → threshold bumped to 0.90
        # |ownership| = 0.88 < 0.90 → pursue
        assert len(result) == 1
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_ai.py::TestEvaluatePursuitTargets -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_pursuit_targets'`

- [ ] **Step 3: 追撃判定関数を実装**

`katrain/core/ai.py` の `count_group_liberties()` の直後に追加：

```python
def evaluate_pursuit_targets(
    previous_targets,
    opponent_move_coords,
    current_opponent_coords,
    board,
    board_size,
    ownership_grid,
    player_sign,
    pursue_proximity,
    pursue_min_liberties,
    pursue_ownership_threshold,
):
    """前手番のターゲットに対して追撃すべきかを判定する。

    Args:
        previous_targets: list of dicts with "coords" (list of (x,y)) and "size" (int)
        opponent_move_coords: (x, y) of opponent's last move, or None
        current_opponent_coords: set of (x, y) of current opponent stones on board
        board: 2D list [y][x] of chain IDs (-1 = empty)
        board_size: (width, height)
        ownership_grid: 2D list [y][x] of ownership values, or None
        player_sign: 1 for Black, -1 for White
        pursue_proximity: max Chebyshev distance for "near target" detection
        pursue_min_liberties: liberty count threshold for unconditional pursuit
        pursue_ownership_threshold: base ownership threshold for pursuit decision
    Returns:
        list of (target_score, instability, group_coords_set) to inject into targets
    """
    if not previous_targets or opponent_move_coords is None:
        return []

    pursuit_targets = []
    ox, oy = opponent_move_coords

    for prev_target in previous_targets:
        prev_coords = set(tuple(c) for c in prev_target["coords"])
        prev_size = prev_target["size"]

        # Check proximity: is opponent's move near this previous target?
        min_dist = min(
            max(abs(ox - cx), abs(oy - cy))  # Chebyshev distance
            for cx, cy in prev_coords
        )
        if min_dist > pursue_proximity:
            continue

        # Step 1: Are stones still on the board?
        surviving_coords = prev_coords & current_opponent_coords
        if not surviving_coords:
            continue

        # Re-group surviving stones (some may have been captured)
        groups = find_connected_groups(surviving_coords)
        for group in groups:
            group_size = len(group)

            # Step 2: Liberty check
            liberties = count_group_liberties(board, group, board_size)
            if liberties >= pursue_min_liberties:
                # Unconditional pursuit
                instability = max(0.2, 1.0 - (1.0 - liberties * 0.05))  # rough estimate
                # Use a more meaningful instability: clamp to at least 0.2
                instability = max(0.2, min(1.0, liberties * 0.1))
                target_score = group_size * instability
                pursuit_targets.append((target_score, instability, group))
                continue

            # Step 3: Ownership check
            if ownership_grid is not None:
                total_ownership = sum(ownership_grid[y][x] for x, y in group)
                avg_ownership = total_ownership / group_size
                abs_ownership = abs(avg_ownership)

                # Adjust threshold by group size
                threshold = pursue_ownership_threshold
                if group_size >= 15:
                    threshold += 0.10
                elif group_size >= 10:
                    threshold += 0.05

                if abs_ownership < threshold:
                    # Ownership not confirmed enough — pursue
                    instability = max(0.2, 1.0 - abs_ownership)
                    target_score = group_size * instability
                    pursuit_targets.append((target_score, instability, group))

    return pursuit_targets
```

- [ ] **Step 4: テストがパスすることを確認**

Run: `pytest tests/test_ai.py::TestEvaluatePursuitTargets -v`
Expected: 7 tests PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai.py
git commit -m "feat: 攻め合い追撃判定関数 evaluate_pursuit_targets を追加"
```

---

### Task 3: HuntStrategy.generate_move() にターゲット記憶と追撃判定を統合

**Files:**
- Modify: `katrain/core/ai.py:3535-3570`（設定読み込み）
- Modify: `katrain/core/ai.py:3786-3790`（find_targets直後に追撃判定を挿入）
- Modify: `katrain/core/ai.py:4085-4088`（末尾でターゲット記憶保存）

- [ ] **Step 1: 設定読み込みに追撃パラメータを追加**

`katrain/core/ai.py` の line 3560（`hunt_focus_stddev` の読み込み）の直後に追加：

```python
        hunt_pursue_enabled = self.settings.get("hunt_pursue_enabled", True)
        hunt_pursue_proximity = self.settings.get("hunt_pursue_proximity", 2)
        hunt_pursue_min_liberties = self.settings.get("hunt_pursue_min_liberties", 3)
        hunt_pursue_ownership_threshold = self.settings.get("hunt_pursue_ownership_threshold", 0.85)
```

- [ ] **Step 2: ログメッセージに追撃設定を追加**

`katrain/core/ai.py` の既存のログ出力（line 3562-3570）を修正し、末尾に追撃情報を追加：

既存の f-string の末尾 `focus_stddev={hunt_focus_stddev})` を以下に変更：

```python
            f"focus_stddev={hunt_focus_stddev}, pursue_enabled={hunt_pursue_enabled})",
```

- [ ] **Step 3: find_targets() 直後に追撃判定を挿入**

`katrain/core/ai.py` の line 3787（`has_group_targets = len(targets) > 0`）の直後に追加：

```python
        # --- 攻め合い追撃判定 ---
        if hunt_pursue_enabled and not has_group_targets:
            # エンドゲーム判定（追撃はエンドゲームでは無効）
            if bx >= 19 and by >= 19:
                _endgame_threshold = int(self.settings.get("hunt_endgame_move", 200))
            else:
                _endgame_threshold = math.ceil(bx * by * 0.5)
            current_move = self.cn.depth

            if current_move < _endgame_threshold:
                # 2手前ノード（自分の前手番）からターゲット記憶を取得
                prev_node = self.cn.parent  # 相手の着手ノード
                prev_prev_node = prev_node.parent if prev_node else None  # 自分の前手番ノード
                prev_targets = getattr(prev_prev_node, "hunt_previous_targets", None) if prev_prev_node else None

                if prev_targets and self.cn.move and self.cn.move.coords:
                    opponent_move_coords = self.cn.move.coords

                    # 現在の相手石座標を取得
                    current_opponent_coords = set()
                    for s in self.game.stones:
                        if s.player != self.cn.next_player and s.coords:
                            current_opponent_coords.add(s.coords)

                    # ownershipグリッドを取得（Stage 2のクリーンクエリから）
                    _ownership = self.cn.ownership
                    _ownership_grid = var_to_grid(_ownership, board_size) if _ownership else None

                    pursuit_results = evaluate_pursuit_targets(
                        previous_targets=prev_targets,
                        opponent_move_coords=opponent_move_coords,
                        current_opponent_coords=current_opponent_coords,
                        board=self.game.board,
                        board_size=board_size,
                        ownership_grid=_ownership_grid,
                        player_sign=player_sign,
                        pursue_proximity=hunt_pursue_proximity,
                        pursue_min_liberties=hunt_pursue_min_liberties,
                        pursue_ownership_threshold=hunt_pursue_ownership_threshold,
                    )

                    if pursuit_results:
                        for score, instab, group in pursuit_results:
                            targets.append((score, instab, group))
                            liberties = count_group_liberties(self.game.board, group, board_size)
                            # ownershipを計算（ログ用）
                            if _ownership_grid:
                                avg_own = sum(_ownership_grid[y][x] for x, y in group) / len(group)
                            else:
                                avg_own = 0.0
                            self.game.katrain.log(
                                f"[HuntStrategy] Pursue: opponent played "
                                f"[{Move(opponent_move_coords, player=self.cn.next_player).gtp()}] "
                                f"near previous target (size={len(group)}, liberties={liberties}, "
                                f"ownership={abs(avg_own):.2f}) → re-targeting",
                                OUTPUT_DEBUG,
                            )
                        targets.sort(key=lambda t: t[0], reverse=True)
                        has_group_targets = True
                    else:
                        # 追撃スキップのログ
                        if prev_targets and self.cn.move and self.cn.move.coords:
                            for prev_target in prev_targets:
                                prev_coords = set(tuple(c) for c in prev_target["coords"])
                                ox, oy = opponent_move_coords
                                min_dist = min(
                                    max(abs(ox - cx), abs(oy - cy))
                                    for cx, cy in prev_coords
                                ) if prev_coords else 999
                                if min_dist <= hunt_pursue_proximity:
                                    self.game.katrain.log(
                                        f"[HuntStrategy] Pursue: opponent played "
                                        f"[{Move(opponent_move_coords, player=self.cn.next_player).gtp()}] "
                                        f"near previous target but stones confirmed dead → no pursuit",
                                        OUTPUT_DEBUG,
                                    )
```

- [ ] **Step 4: generate_move() 末尾にターゲット記憶保存を追加**

`katrain/core/ai.py` の `_select_final_move` 呼び出し（line 4086-4088）の直前に追加：

```python
        # --- ターゲット記憶保存 ---
        if hunt_pursue_enabled:
            self.cn.hunt_previous_targets = [
                {
                    "coords": list(group),
                    "size": len(group),
                }
                for _, _, group in targets
            ]
```

注意: この保存は `return` 文の前に配置する必要がある。`generate_move()` には複数の `return` 文（安全弁、パス処理、エンドゲーム等）があるため、正規の着手選択パス上（line 4075の「デバッグ: 上位5手表示」の直前）に配置する。

- [ ] **Step 5: 動作確認（デバッグCLI）**

Run: `python -m katrain_debug --sgf tests/data/ogs.sgf --move 50 --strategy hunt --output text`
Expected: 正常に動作すること（追撃は発動しないが、クラッシュしないことを確認）

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntStrategy.generate_move() にターゲット記憶と追撃判定を統合"
```

---

### Task 4: GUI設定（constants.py + config.json）

**Files:**
- Modify: `katrain/core/constants.py:178`（AI_OPTION_VALUES, hunt_endgame_moveの後）
- Modify: `katrain/core/constants.py:222`（AI_OPTION_ORDER, hunt_endgame_moveの後）
- Modify: `katrain/config.json:184`（ai:hunt セクション末尾）
- Modify: `katrain/config.json:197`（ai:hunt_diverge セクション末尾）
- Modify: `C:\Users\iwaki\.katrain\config.json:184`（ユーザーローカル ai:hunt）
- Modify: `C:\Users\iwaki\.katrain\config.json:197`（ユーザーローカル ai:hunt_diverge）

- [ ] **Step 1: AI_OPTION_VALUES にチェックボックスを追加**

`katrain/core/constants.py` の line 178（`"hunt_endgame_move"` の行）の直後に追加：

```python
    "hunt_pursue_enabled": "bool",
```

- [ ] **Step 2: AI_OPTION_ORDER に表示順を追加**

`katrain/core/constants.py` の line 222（`"hunt_endgame_move": 26,` の行）の直後に追加：

```python
    "hunt_pursue_enabled": 27,
```

- [ ] **Step 3: パッケージ config.json の ai:hunt セクションに追加**

`katrain/config.json` の ai:hunt セクション（line 184 `"hunt_endgame_move": 200` の行）を修正：

`"hunt_endgame_move": 200` → `"hunt_endgame_move": 200,` に変更し、次の行に追加：

```json
            "hunt_pursue_enabled": true
```

- [ ] **Step 4: パッケージ config.json の ai:hunt_diverge セクションに追加**

`katrain/config.json` の ai:hunt_diverge セクション（line 197 `"hunt_endgame_move": 200` の行）を修正：

`"hunt_endgame_move": 200` → `"hunt_endgame_move": 200,` に変更し、次の行に追加：

```json
            "hunt_pursue_enabled": true
```

- [ ] **Step 5: ユーザーローカル config.json の ai:hunt セクションに追加**

**重要: メインセッションで直接Editする（サブエージェント不可）**

`C:\Users\iwaki\.katrain\config.json` の ai:hunt セクション（line 184 `"hunt_endgame_move": 200` の行）を修正：

`"hunt_endgame_move": 200` → `"hunt_endgame_move": 200,` に変更し、次の行に追加：

```json
            "hunt_pursue_enabled": true
```

- [ ] **Step 6: ユーザーローカル config.json の ai:hunt_diverge セクションに追加**

**重要: メインセッションで直接Editする（サブエージェント不可）**

`C:\Users\iwaki\.katrain\config.json` の ai:hunt_diverge セクション（line 197 `"hunt_endgame_move": 200` の行）を修正：

`"hunt_endgame_move": 200` → `"hunt_endgame_move": 200,` に変更し、次の行に追加：

```json
            "hunt_pursue_enabled": true
```

- [ ] **Step 7: コミット**

```bash
git add katrain/core/constants.py katrain/config.json
git commit -m "feat: hunt_pursue_enabled チェックボックスをGUI設定に追加"
```

---

### Task 5: i18nヘルプテキスト

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:988`
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:1079`

- [ ] **Step 1: 英語ヘルプテキストに追撃説明を追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の line 988（`"Only affects 19x19 boards."` の行）を修正：

```
"Only affects 19x19 boards.\n"
"hunt_pursue_enabled: Semeai pursuit. Continue playing killing moves when "
"the opponent resists during a capturing race, instead of tenuki."
```

- [ ] **Step 2: 日本語ヘルプテキストに追撃説明を追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の line 1079（`"ヨセモードではターゲット重みを無視しhumanPolicy最上位手を選択する。19路盤のみ有効。"` の行）を修正：

```
"ヨセモードではターゲット重みを無視しhumanPolicy最上位手を選択する。19路盤のみ有効。\n"
"hunt_pursue_enabled: 攻め合い追撃。攻め合い中に相手が勝負手を打った場合、"
"手抜きせず詰め手を継続します。"
```

- [ ] **Step 3: .moファイルをコンパイル**

Run: `python tools/compile_mo.py`
Expected: 正常終了（エラーなし）

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/
git commit -m "feat: hunt_pursue_enabled のi18nヘルプテキストを追加（en/jp）"
```

---

### Task 6: パラメータテーブル更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`

- [ ] **Step 1: ai-parameters.md の狩猟戦略テーブルに追撃パラメータを追加**

`.claude/rules/ai-parameters.md` の狩猟戦略テーブル（`hunt_endgame_move` 行の後）に以下を追加：

```markdown
| hunt_pursue_enabled | true | true | 攻め合い追撃。相手が勝負手を打った場合、手抜きせず詰め手を継続する（GUI: チェックボックス） |
| hunt_pursue_proximity | 2 | 2 | 勝負手判定の近接距離（Chebyshev距離、路）。config.json手動編集のみ |
| hunt_pursue_min_liberties | 3 | 3 | この数以上のリバティなら無条件追撃。config.json手動編集のみ |
| hunt_pursue_ownership_threshold | 0.85 | 0.85 | ownership確信度の閾値（石群サイズ≥10で+0.05、≥15で+0.10）。config.json手動編集のみ |
```

- [ ] **Step 2: コミット**

注意: `.claude/rules/` 配下のEditが拒否される場合はサブエージェント経由で編集する。

```bash
git add .claude/rules/ai-parameters.md
git commit -m "docs: ai-parameters.md に攻め合い追撃パラメータを追加"
```

---

### Task 7: 統合テストとGUI動作確認

**Files:**
- No new files

- [ ] **Step 1: 既存テストが全てパスすることを確認**

Run: `pytest tests/ --ignore=tests/test_ai.py -v`
Expected: ALL PASS（test_ai.py はKataGoが必要なため除外）

Run: `pytest tests/test_ai.py::TestFindConnectedGroups tests/test_ai.py::TestFindTargets tests/test_ai.py::TestCountGroupLiberties tests/test_ai.py::TestEvaluatePursuitTargets -v`
Expected: ALL PASS

- [ ] **Step 2: デバッグCLIで追撃ログを確認**

Run: `python -m katrain_debug --sgf tests/data/ogs.sgf --move 80 --strategy hunt --output text`
Expected: 正常動作。ログに `pursue_enabled=True` が表示される。

- [ ] **Step 3: GUI起動確認**

1. `C:\Users\iwaki\.katrain\config.json` の `debug_level` を `1` に設定
2. `python -m katrain` で起動
3. AI設定画面 → 狩猟戦略 → 「攻め合い追撃」チェックボックスが表示されることを確認
4. チェックボックスをオフにして対局開始 → ログに `pursue_enabled=False` が表示されることを確認
5. チェックボックスをオンに戻して確認後、`debug_level` を `0` に戻す

- [ ] **Step 4: フォーマット確認**

Run: `black katrain/core/ai.py katrain/core/constants.py --check`
Expected: PASS（フォーマット済み）。失敗した場合は `black katrain/core/ai.py katrain/core/constants.py` で修正してコミット。
