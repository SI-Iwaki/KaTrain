# コウ戦略（KoStrategy）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 地よりコウで競る独立AI戦略 `ai:ko`（GUI「コウ」）を追加する。緊張を高めてコウを誘発し、損失バジェット内でコウを仕掛ける。

**Architecture:** 新 `KoStrategy(AIStrategy)` を `katrain/core/ai.py` に追加。Hunt/Siege と同じ2段階クエリ（Stage1 humanSL 9段 → Stage2 クリーンスコア）。コウ検出は純粋盤面ロジック（`detect_ko_capture_points` / `is_ko_ban_active`、KataGo追加照会なし）。3フェーズ（Seek＝力戦的に種まき / KoFight＝コウ食いつき＋コウ材 / Endgame＝humanPolicy最大手）。

**Tech Stack:** Python 3.12 / Kivy / KataGo（humanSLモデル）。テストは pytest。設計書: `docs/superpowers/specs/2026-05-24-ko-strategy-design.md`。

**重要な前提（実装者向け）:**
- KataGo `scoreLead` は常に黒視点。`player_sign = 1 if Black else -1`、`loss = player_sign * (best_score - score)` で打つ側視点に変換する。
- 盤面表現（`katrain/core/game.py`）: `game.board[y][x]` = 連ID（空点 -1）、`game.chains[id]` = `Move` のリスト（取られた連は `[]`）、`game.stones` / `game.board_size` / `game.last_capture` / `game.current_node`。
- 設計書の「config.json に9パラメータ」は、確立パターン（Hunt の `hunt_pursue_*` は config.json にもAI_OPTION_VALUESにも入れずコード既定値のみ）に合わせ、**config.json と AI_OPTION_VALUES には GUI 5項目のみ**を入れる。config手動の4項目はコード `settings.get(key, default)` の既定値のみ（ユーザーが手動でconfigに追記して上書き可能）。

---

## Task 1: コウ検出ヘルパー（純粋盤面ロジック・モデル不要TDD）

**Files:**
- Modify: `katrain/core/ai.py`（`find_targets` の直後、`interp_ix` の手前 = 270行付近に3関数を追加）
- Test: `tests/test_ko_detection.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ko_detection.py` を新規作成:

```python
import pytest

from katrain.core.base_katrain import KaTrainBase
from katrain.core.game import Game, Move
from katrain.core.game_node import GameNode
from katrain.core.ai import detect_ko_capture_points, is_ko_ban_active


class MockKaTrain(KaTrainBase):
    pass


class MockEngine:
    def request_analysis(self, *args, **kwargs):
        pass


@pytest.fixture
def new_game():
    return GameNode(properties={"SZ": 19})


def _build(new_game):
    return Game(MockKaTrain(force_package_config=True), MockEngine(), move_tree=new_game)


def test_detects_ko_capture_point(new_game):
    # Black A2,B1 / White B2,C1 -> White A1 captures lone Black B1 and self-ataris = ko shape
    b = _build(new_game)
    for mv in ["A2", "B1"]:
        b.play(Move.from_gtp(mv, player="B"))
    for mv in ["B2", "C1"]:
        b.play(Move.from_gtp(mv, player="W"))
    points = detect_ko_capture_points(b.board, b.chains, b.board_size, "W")
    assert (0, 0) in points  # A1


def test_normal_capture_is_not_ko(new_game):
    # Black B3,C2,C4 / White C3 -> Black D3 captures lone White C3 but keeps 4 liberties = not ko
    b = _build(new_game)
    for mv in ["B3", "C2", "C4"]:
        b.play(Move.from_gtp(mv, player="B"))
    b.play(Move.from_gtp("C3", player="W"))
    points = detect_ko_capture_points(b.board, b.chains, b.board_size, "B")
    assert points == set()


def test_ko_ban_active_after_capture(new_game):
    # After White A1 captures Black B1, recapture at B1 is ko-banned for Black
    b = _build(new_game)
    for mv in ["A2", "B1"]:
        b.play(Move.from_gtp(mv, player="B"))
    for mv in ["B2", "C1"]:
        b.play(Move.from_gtp(mv, player="W"))
    b.play(Move.from_gtp("A1", player="W"))
    assert is_ko_ban_active(b) == (1, 0)  # B1


def test_no_ko_ban_on_plain_move(new_game):
    b = _build(new_game)
    b.play(Move.from_gtp("D4", player="B"))
    assert is_ko_ban_active(b) is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_ko_detection.py -v`
Expected: FAIL（`ImportError: cannot import name 'detect_ko_capture_points'`）

- [ ] **Step 3: ヘルパー3関数を実装**

`katrain/core/ai.py` の `find_targets` 関数の `return targets`（269行付近）の直後、空行を挟んで以下を追加:

```python
def _ko_chain_liberties(chain, board, board_size):
    """連（Move のリスト）の呼吸点座標の集合を返す。"""
    bx, by = board_size
    libs = set()
    for m in chain:
        if not m.coords:
            continue
        sx, sy = m.coords
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = sx + dx, sy + dy
            if 0 <= nx < bx and 0 <= ny < by and board[ny][nx] == -1:
                libs.add((nx, ny))
    return libs


def detect_ko_capture_points(board, chains, board_size, player):
    """player が打つと「相手の単石をちょうど1目取り、打った石が単独でアタリ（呼吸点1）」
    になる点 (x, y) の集合を返す。これがコウ形（取り返せばコウになる）。
    純粋な盤面ロジックで判定し、KataGo 照会を行わない。snapback（取った後に呼吸点が
    複数残る）や、自石と繋がって連になる手は除外する。

    board[y][x] = 連ID（空点 -1）, chains[id] = Move のリスト, board_size = (bx, by),
    player = "B" / "W"
    """
    bx, by = board_size

    def neighbors(x, y):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < bx and 0 <= ny < by:
                yield nx, ny

    ko_points = set()
    for x in range(bx):
        for y in range(by):
            if board[y][x] != -1:
                continue  # 空点のみ

            # この手で取れる相手連を探す（呼吸点が (x, y) だけの連）
            captured = []  # [(cap_x, cap_y, chain_len), ...]
            for nx, ny in neighbors(x, y):
                cid = board[ny][nx]
                if cid < 0:
                    continue
                chain = chains[cid]
                if not chain or chain[0].player == player:
                    continue  # 空連 or 自分の石
                if _ko_chain_liberties(chain, board, board_size) == {(x, y)}:
                    captured.append((nx, ny, len(chain)))

            # コウ条件1: 取れる相手連がちょうど1つ、かつそれが単石
            if len(captured) != 1 or captured[0][2] != 1:
                continue
            cap_x, cap_y, _ = captured[0]

            # コウ条件2: 打った石が自石と繋がらない（単独石になる）
            connects_friendly = False
            for nx, ny in neighbors(x, y):
                cid = board[ny][nx]
                if cid >= 0 and chains[cid] and chains[cid][0].player == player:
                    connects_friendly = True
                    break
            if connects_friendly:
                continue

            # コウ条件3: 取った後、打った石の呼吸点がちょうど {取った点} の1つ（=アタリ）
            played_libs = set()
            for nx, ny in neighbors(x, y):
                if (nx, ny) == (cap_x, cap_y):
                    played_libs.add((nx, ny))  # 取られて空になる
                elif board[ny][nx] == -1:
                    played_libs.add((nx, ny))  # 既存の空点
            if played_libs == {(cap_x, cap_y)}:
                ko_points.add((x, y))

    return ko_points


def is_ko_ban_active(game):
    """直前手が単石を取り、その点への取り返しが現在コウ禁止になっている場合、
    その点 (x, y) を返す。コウでなければ None。
    """
    if len(game.last_capture) != 1:
        return None
    cap = game.last_capture[0]
    if not cap.coords:
        return None
    recapture_player = game.current_node.next_player
    ko_points = detect_ko_capture_points(
        game.board, game.chains, game.board_size, recapture_player
    )
    if cap.coords in ko_points:
        return cap.coords
    return None
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_ko_detection.py -v`
Expected: PASS（4 tests）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ko_detection.py
git commit -m "feat(ko): コウ検出の純粋盤面ロジック detect_ko_capture_points / is_ko_ban_active を追加"
```

---

## Task 2: 定数登録（AI_KO とGUIウィジェット定義）

**Files:**
- Modify: `katrain/core/constants.py`
- Test: `tests/test_ko_wiring.py`（新規・この Task では定数のみ検証）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ko_wiring.py` を新規作成:

```python
def test_ai_ko_in_strategies():
    from katrain.core.constants import AI_KO, AI_STRATEGIES, AI_STRATEGIES_RECOMMENDED_ORDER
    assert AI_KO == "ai:ko"
    assert AI_KO in AI_STRATEGIES
    assert AI_KO in AI_STRATEGIES_RECOMMENDED_ORDER


def test_ko_gui_options_defined():
    from katrain.core.constants import AI_OPTION_VALUES
    for key in ["ko_max_loss", "ko_bonus", "ko_threat_bonus",
                "ko_seek_contact_boost", "ko_endgame_move"]:
        assert key in AI_OPTION_VALUES, f"{key} missing from AI_OPTION_VALUES"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_ko_wiring.py -v`
Expected: FAIL（`ImportError: cannot import name 'AI_KO'`）

- [ ] **Step 3: 定数を追加**

3-1. `katrain/core/constants.py` の `AI_HUNT_DIVERGE = "ai:hunt_diverge"`（61行付近）の直後に追加:

```python
AI_KO = "ai:ko"
```

3-2. `AI_STRATEGIES`（68行）の末尾リストに `AI_KO` を追加:

```python
AI_STRATEGIES = AI_STRATEGIES_ENGINE + AI_STRATEGIES_POLICY + [AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE, AI_KO]
```

3-3. `AI_STRATEGIES_RECOMMENDED_ORDER`（69-91行）の `AI_HUNT_DIVERGE,` の直後に追加:

```python
    AI_HUNT_DIVERGE,
    AI_KO,
]
```

3-4. `AI_STRENGTH`（93-115行）の `AI_HUNT_DIVERGE: float("nan"),` の直後に追加:

```python
    AI_HUNT_DIVERGE: float("nan"),
    AI_KO: float("nan"),
}
```

3-5. `AI_OPTION_VALUES`（117-207行）の `"jigo_deception_13_phase2_target": [-0.5, -1.0, -1.5, -2.0],`（206行）の直後、辞書を閉じる `}` の手前に追加:

```python
    # ===== KoStrategy =====
    "ko_max_loss": [3.0, 4.0, 5.0, 6.0, 8.0],
    "ko_bonus": [2.0, 4.0, 6.0, 10.0, 15.0],
    "ko_threat_bonus": [1.5, 2.0, 3.0, 5.0],
    "ko_seek_contact_boost": [1.0, 1.5, 2.0, 3.0],
    "ko_endgame_move": [150, 180, 200, 220, 250],
```

3-6. `AI_OPTION_ORDER`（210-270行）の `"jigo_deception_13_phase2_target": 15,`（269行）の直後、辞書を閉じる `}` の手前に追加:

```python
    "ko_max_loss": 0,
    "ko_bonus": 1,
    "ko_threat_bonus": 2,
    "ko_seek_contact_boost": 3,
    "ko_endgame_move": 4,
```

> **注意:** `AI_KEY_PROPERTIES`（272行〜）は変更不要。Hunt/Siege の戦略パラメータも登録されていない（強度決定パラメータ専用の集合のため）。

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_ko_wiring.py -v`
Expected: PASS（2 tests）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/constants.py tests/test_ko_wiring.py
git commit -m "feat(ko): AI_KO 定数とGUIウィジェット定義（AI_OPTION_VALUES 5項目）を登録"
```

---

## Task 3: KoStrategy クラス本体

**Files:**
- Modify: `katrain/core/ai.py`（import に `AI_KO` 追加 / `generate_ai_move`（5016行）の手前に `KoStrategy` クラスを追加）

- [ ] **Step 1: import に AI_KO を追加**

`katrain/core/ai.py` の16行目（`... AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE`）の末尾に `, AI_KO` を追加:

```python
    OUTPUT_ERROR, OUTPUT_INFO, PRIORITY_EXTRA_AI_QUERY, ADDITIONAL_MOVE_ORDER, AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE, AI_KO
```

- [ ] **Step 2: KoStrategy クラスを追加**

`katrain/core/ai.py` の `def generate_ai_move(`（5016行）の手前に、以下のクラス全体を追加:

```python
@register_strategy(AI_KO)
class KoStrategy(AIStrategy):
    """コウ戦略 — 緊張を高めてコウを誘発し、損失バジェット内でコウを仕掛ける。地よりコウで競る碁。"""

    BOARD_PARAMS = {
        19: {"max_loss": 6.0, "min_group_size": 5, "seek_proximity_stddev": 3.0, "endgame_move": 200},
        13: {"max_loss": 4.0, "min_group_size": 4, "seek_proximity_stddev": 2.5, "endgame_move": None},
    }

    def generate_move(self) -> Tuple[Move, str]:
        board_size = self.game.board_size
        bx, by = board_size
        params = self.BOARD_PARAMS.get(bx, self.BOARD_PARAMS[19])

        ko_max_loss = self.settings.get("ko_max_loss", params["max_loss"])
        ko_bonus = self.settings.get("ko_bonus", 6.0)
        ko_threat_bonus = self.settings.get("ko_threat_bonus", 3.0)
        ko_seek_contact_boost = self.settings.get("ko_seek_contact_boost", 1.5)
        ko_seek_unsettled_power = self.settings.get("ko_seek_unsettled_power", 2.0)
        ko_seek_proximity_stddev = self.settings.get("ko_seek_proximity_stddev", params["seek_proximity_stddev"])
        ko_min_group_size = self.settings.get("ko_min_group_size", params["min_group_size"])
        ko_instability_min = self.settings.get("ko_instability_min", 0.3)
        if params["endgame_move"] is not None:
            ko_endgame_move = int(self.settings.get("ko_endgame_move", params["endgame_move"]))
        else:
            ko_endgame_move = math.ceil(bx * by * 0.5)

        _LOSING_THRESHOLD = -6.0
        _LOSING_MAX_LOSS = 4.0
        _SAFETY_LOSS_THRESHOLD = 4.0

        self.game.katrain.log(
            f"[KoStrategy] Starting (max_loss={ko_max_loss}, ko_bonus={ko_bonus}, "
            f"ko_threat_bonus={ko_threat_bonus}, endgame={ko_endgame_move})",
            OUTPUT_DEBUG,
        )

        self.wait_for_analysis()

        # --- Stage 1: humanSL（9段固定） ---
        override_settings = {"humanSLProfile": "rank_9d", "ignorePreRootHistory": False, "maxVisits": 800}
        analysis = None
        error = False

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[KoStrategy] Error in Stage 1: {a}", OUTPUT_ERROR)

        engine = self.game.engines[self.cn.player]
        engine.request_analysis(
            self.cn, callback=set_analysis, error_callback=set_error,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=True, extra_settings=override_settings,
        )
        while not (error or analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if error or not analysis or "humanPolicy" not in analysis:
            self.game.katrain.log("[KoStrategy] Stage 1 failed, falling back to best move", OUTPUT_DEBUG)
            candidate_moves = self.cn.candidate_moves
            if not candidate_moves:
                return Move(None, player=self.cn.next_player), "No candidate moves, passing."
            top_move = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
            if top_move.is_pass:
                return top_move, "Top move is pass."
            return top_move, "Ko fallback: Stage 1 failed, best move."

        human_policy = analysis["humanPolicy"]

        # --- Stage 2: クリーンクエリ（正確なスコア） ---
        clean_override_settings = {"ignorePreRootHistory": False, "maxVisits": 600, "wideRootNoise": 0.0}
        clean_analysis = None
        clean_error = False

        def set_clean_analysis(a, partial_result):
            nonlocal clean_analysis
            if not partial_result:
                clean_analysis = a

        def set_clean_error(a):
            nonlocal clean_error
            clean_error = True
            self.game.katrain.log(f"[KoStrategy] Error in Stage 2: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=set_clean_analysis, error_callback=set_clean_error,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=False, extra_settings=clean_override_settings,
        )
        while not (clean_error or clean_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if clean_analysis and not clean_error:
            move_infos = clean_analysis.get("moveInfos", [])
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log("[KoStrategy] Clean query failed, using Stage 1 moveInfos", OUTPUT_DEBUG)

        # --- スコア前処理 ---
        player_sign = 1 if self.cn.next_player == "B" else -1
        best_score = None
        best_gtp_by_score = None
        if move_infos:
            best_score = max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
            best_gtp_by_score = max(move_infos, key=lambda mi: mi.get("scoreLead", 0) * player_sign).get("move", "")
            if best_gtp_by_score == "pass":
                return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."

        # --- 劣勢時の損失キャップ ---
        if best_score is not None:
            score_lead = best_score * player_sign
            if score_lead < _LOSING_THRESHOLD:
                capped = min(ko_max_loss, _LOSING_MAX_LOSS)
                if capped != ko_max_loss:
                    self.game.katrain.log(
                        f"[KoStrategy] Losing restrict: score_lead={score_lead:.1f}, "
                        f"ko_max_loss {ko_max_loss} -> {capped}",
                        OUTPUT_DEBUG,
                    )
                    ko_max_loss = capped

        current_move = self.cn.depth

        # --- 悪手フィルタ ---
        good_moves = set()
        score_by_gtp = {}
        if move_infos and best_score is not None:
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score_by_gtp[gtp_move] = mi.get("scoreLead", 0)
                if player_sign * (best_score - mi.get("scoreLead", 0)) <= ko_max_loss:
                    good_moves.add(gtp_move)
        has_filter = len(good_moves) > 0

        # --- コウ検出（純粋盤面ロジック） ---
        ko_points = detect_ko_capture_points(self.game.board, self.game.chains, board_size, self.cn.next_player)
        ko_ban_pt = is_ko_ban_active(self.game)

        # --- フェーズ判定 ---
        if bx not in (13, 19):
            phase_name = "Endgame"  # 非対応サイズは humanPolicy 最大手に縮退
        elif ko_points or ko_ban_pt:
            phase_name = "KoFight"
        elif current_move >= ko_endgame_move:
            phase_name = "Endgame"
        else:
            phase_name = "Seek"

        self.game.katrain.log(
            f"[KoStrategy] Phase: {phase_name} (move={current_move}, "
            f"ko_points={len(ko_points)}, ko_ban={ko_ban_pt})",
            OUTPUT_DEBUG,
        )

        if phase_name == "Endgame":
            return self._top_human_policy_move(human_policy, board_size, "Endgame")

        # --- コウ材ターゲット（取り返し待ち時に相手弱石を脅かす） ---
        targets = find_targets(self.game, self.cn, ko_min_group_size, ko_instability_min)
        group_coords = set()
        target_instability = 0.0
        if targets:
            target_instability = targets[0][1]
            group_coords = set(targets[0][2])
            if len(targets) > 1:
                group_coords |= targets[1][2]

        # --- 候補構築 ---
        opponent_coords = [s.coords for s in self.game.stones if s.player != self.cn.next_player and s.coords]
        seek_prox_var = ko_seek_proximity_stddev ** 2
        ownership_grid = var_to_grid(self.cn.ownership, board_size) if self.cn.ownership else None

        moves = []
        filtered_count = 0
        for x in range(bx):
            for y in range(by):
                idx = (by - y - 1) * bx + x
                if idx >= len(human_policy) or human_policy[idx] <= 0:
                    continue
                m = Move((x, y), player=self.cn.next_player)
                if has_filter and m.gtp() not in good_moves:
                    filtered_count += 1
                    continue
                hp_weight = human_policy[idx]

                if phase_name == "KoFight":
                    if (x, y) in ko_points:
                        mult = ko_bonus
                    elif ko_ban_pt is not None and group_coords:
                        min_dist_sq = min((x - tx) ** 2 + (y - ty) ** 2 for tx, ty in group_coords)
                        proximity = math.exp(-0.5 * min_dist_sq / seek_prox_var)
                        mult = 1.0 + ko_threat_bonus * proximity * target_instability
                    else:
                        mult = 1.0
                else:  # Seek
                    mult = self._seek_multiplier(
                        x, y, ownership_grid, opponent_coords,
                        ko_seek_unsettled_power, seek_prox_var, ko_seek_contact_boost,
                    )

                moves.append((m, hp_weight * mult))

        # pass 候補
        if len(human_policy) > bx * by and human_policy[-1] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[-1]))

        self.game.katrain.log(
            f"[KoStrategy] {len(moves)} candidates ({filtered_count} filtered)", OUTPUT_DEBUG
        )

        # フォールバック
        if not moves:
            if best_gtp_by_score and best_gtp_by_score != "pass":
                return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), "Ko fallback: no candidates, best move."
            return Move(None, player=self.cn.next_player), "Ko fallback: no candidates, passing."

        # pass 強制
        if any(mm.is_pass for mm, _ in moves):
            return Move(None, player=self.cn.next_player), "Pass in candidates, forcing pass."

        # --- 重み付き選択 ---
        selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]

        # --- 選択後安全弁 ---
        if move_infos and best_gtp_by_score and best_score is not None:
            sel_gtp = move.gtp()
            if sel_gtp in score_by_gtp and sel_gtp != best_gtp_by_score:
                sel_loss = player_sign * (best_score - score_by_gtp[sel_gtp])
                if sel_loss >= _SAFETY_LOSS_THRESHOLD:
                    top_w_move = max(moves, key=lambda t: t[1])[0]
                    self.game.katrain.log(
                        f"[KoStrategy] Post-selection safety: {sel_gtp} loss={sel_loss:.2f} "
                        f">= {_SAFETY_LOSS_THRESHOLD}, fallback to top weighted {top_w_move.gtp()}",
                        OUTPUT_DEBUG,
                    )
                    move = top_w_move

        self.game.katrain.log(f"[KoStrategy] Selected: {move.gtp()} ({phase_name})", OUTPUT_DEBUG)
        return move, (
            f"{phase_name}: played {move.gtp()} "
            f"({filtered_count} bad moves filtered, ko_points={len(ko_points)})"
        )

    def _seek_multiplier(self, x, y, ownership_grid, opponent_coords, unsettled_power, prox_var, contact_boost):
        """Seek相: 未確定度 × 相手石への近接 × 接触ブースト（力戦派の重みを流用）。"""
        o = ownership_grid[y][x] if ownership_grid else 0.0
        unsettled = (1.0 - abs(o)) ** unsettled_power
        if opponent_coords:
            min_dist_sq = min((x - ox) ** 2 + (y - oy) ** 2 for ox, oy in opponent_coords)
            prox = math.exp(-0.5 * min_dist_sq / prox_var)
        else:
            min_dist_sq = 1000
            prox = 1.0
        w = unsettled * prox
        if min_dist_sq == 1:  # 相手石への接触手
            w *= contact_boost
        return max(w, 1e-6)

    def _top_human_policy_move(self, human_policy, board_size, label):
        """humanPolicy 最大の合法空点を返す（Endgame / 非対応サイズ用）。"""
        bx, by = board_size
        best = None
        best_w = -1.0
        for x in range(bx):
            for y in range(by):
                if self.game.board[y][x] != -1:
                    continue
                idx = (by - y - 1) * bx + x
                if idx < len(human_policy) and human_policy[idx] > best_w:
                    best_w = human_policy[idx]
                    best = Move((x, y), player=self.cn.next_player)
        if best is None:
            return Move(None, player=self.cn.next_player), f"{label}: no legal move, passing."
        self.game.katrain.log(f"[KoStrategy] {label}: top humanPolicy {best.gtp()}", OUTPUT_DEBUG)
        return best, f"{label}: played top humanPolicy {best.gtp()}."
```

- [ ] **Step 3: クラスがロード・登録されることを確認（モデル不要）**

Run: `python -c "from katrain.core.ai import KoStrategy, STRATEGY_REGISTRY; from katrain.core.constants import AI_KO; assert STRATEGY_REGISTRY[AI_KO] is KoStrategy; print('OK')"`
Expected: `OK`（import エラーや登録漏れがないこと）

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat(ko): KoStrategy クラス本体（2段階クエリ・3フェーズ・コウ重み・安全弁）を追加"
```

---

## Task 4: デバッグCLI登録 ＋ 配線スモークテスト

**Files:**
- Modify: `katrain_debug/runner.py`
- Test: `tests/test_ko_wiring.py`（Task 2 のファイルに追記）

- [ ] **Step 1: 失敗するテストを追記**

`tests/test_ko_wiring.py` の末尾に追加:

```python
def test_ko_registered_in_strategy_registry():
    from katrain.core.ai import STRATEGY_REGISTRY, KoStrategy
    from katrain.core.constants import AI_KO
    assert STRATEGY_REGISTRY[AI_KO] is KoStrategy


def test_ko_in_debug_name_map():
    from katrain_debug.runner import STRATEGY_NAME_MAP
    from katrain.core.constants import AI_KO
    assert STRATEGY_NAME_MAP["ko"] == AI_KO
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_ko_wiring.py::test_ko_in_debug_name_map -v`
Expected: FAIL（`KeyError: 'ko'`）

- [ ] **Step 3: katrain_debug にコウ戦略を登録**

3-1. `katrain_debug/runner.py` の import（7行目）の末尾に `AI_KO` を追加:

```python
    AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE, AI_KO,
```

3-2. `STRATEGY_NAME_MAP`（20-43行）の `"hunt_diverge": AI_HUNT_DIVERGE,` の直後に追加:

```python
    "hunt_diverge": AI_HUNT_DIVERGE,
    "ko": AI_KO,
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_ko_wiring.py -v`
Expected: PASS（4 tests）

- [ ] **Step 5: コミット**

```bash
git add katrain_debug/runner.py tests/test_ko_wiring.py
git commit -m "feat(ko): katrain_debug に ko 戦略を登録（STRATEGY_NAME_MAP）"
```

---

## Task 5: config.json へのデフォルト値追加（パッケージ ＋ ユーザーローカル）

**Files:**
- Modify: `katrain/config.json`
- Modify: `C:\Users\iwaki\.katrain\config.json`（**メインセッションで直接編集。サブエージェントに委任しない** — CLAUDE.md の禁止事項）

> **GUI表示の条件:** GUI は「両方の config.json に保存されたキー」かつ「AI_OPTION_VALUES に定義のあるキー」のみ表示する。config.json には GUI 5項目のみを入れる（config手動の4項目 `ko_seek_unsettled_power` / `ko_seek_proximity_stddev` / `ko_min_group_size` / `ko_instability_min` はコード既定値のみで、ユーザーが手動追記して上書きする — Hunt の `hunt_pursue_*` と同じ扱い）。

- [ ] **Step 1: パッケージ config.json に ai:ko を追加**

`katrain/config.json` の `"ai:hunt_diverge"` ブロックの閉じ `}` の直後（`"ai:siege"` の手前）に、コロン区切りを正しく保って追加:

```json
        "ai:ko": {
            "ko_max_loss": 6.0,
            "ko_bonus": 6.0,
            "ko_threat_bonus": 3.0,
            "ko_seek_contact_boost": 1.5,
            "ko_endgame_move": 200
        },
```

- [ ] **Step 2: パッケージ config.json が壊れていないことを確認**

Run: `python -c "import json; json.load(open('katrain/config.json', encoding='utf-8')); print('valid json')"`
Expected: `valid json`

- [ ] **Step 3: ユーザーローカル config.json に同じブロックを追加（メインセッション必須）**

`C:\Users\iwaki\.katrain\config.json` の `"ai"` オブジェクト内に、Step 1 と同じ `"ai:ko"` ブロックを追加する。

Run（検証）: `python -c "import json; json.load(open(r'C:\Users\iwaki\.katrain\config.json', encoding='utf-8')); print('valid json')"`
Expected: `valid json`

- [ ] **Step 4: コミット（パッケージ config.json のみ。ユーザーローカルは git 管理外）**

```bash
git add katrain/config.json
git commit -m "feat(ko): config.json に ai:ko デフォルト値（GUI5項目）を追加"
```

---

## Task 6: i18n（GUIラベル・ヘルプ）

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
- Run: `python tools/compile_mo.py`

- [ ] **Step 1: 英語 .po にエントリを追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` に以下を追加（既存の `ai:hunt` / `aihelp:hunt` 周辺に並べる）:

```po
msgid "ai:ko"
msgstr "Ko"

msgid "aihelp:ko"
msgstr "Plays to provoke and fight kos rather than win by territory. Builds tension early (fighting-style) to create ko shapes, then chases kos within a loss budget. 19x19 and 13x13 only."

msgid "ko_max_loss"
msgstr "Max points lost"

msgid "ko_bonus"
msgstr "Ko move bonus"

msgid "ko_threat_bonus"
msgstr "Ko threat bonus"

msgid "ko_seek_contact_boost"
msgstr "Contact move boost (seek)"

msgid "ko_endgame_move"
msgstr "Endgame move (19x19)"
```

- [ ] **Step 2: 日本語 .po にエントリを追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` に以下を追加:

```po
msgid "ai:ko"
msgstr "コウ"

msgid "aihelp:ko"
msgstr "地ではなくコウで競る碁。序盤は力戦的に緊張を高めてコウ形を作り、損失バジェット内でコウを仕掛け続ける。19路・13路のみ対応。"

msgid "ko_max_loss"
msgstr "許容最大損失（目）"

msgid "ko_bonus"
msgstr "コウ手の重み倍率"

msgid "ko_threat_bonus"
msgstr "コウ材の重み倍率"

msgid "ko_seek_contact_boost"
msgstr "接触手ブースト（種まき）"

msgid "ko_endgame_move"
msgstr "ヨセ切替手数（19路）"
```

- [ ] **Step 3: .mo を再コンパイル**

Run: `python tools/compile_mo.py`
Expected: エラーなく完了（`.mo` ファイルが更新される）

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.mo katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo
git commit -m "feat(ko): i18n（GUIラベル「コウ」とパラメータ名・ヘルプ）を追加"
```

---

## Task 7: ドキュメント更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（**サブエージェント経由で編集** — CLAUDE.md の既知の問題により直接 Edit が拒否されるため）
- Modify: `CLAUDE.md`

- [ ] **Step 1: ai-parameters.md にコウ戦略の節を追加（サブエージェント経由）**

サブエージェント（Agent tool）に以下を依頼する: 「`.claude/rules/ai-parameters.md` の「狩猟戦略（HuntStrategy）」節の後に、以下のコウ戦略の節を追加してコミットせずに保存して」

````markdown
## コウ戦略（KoStrategy）

独立した戦略（`ai:ko`、GUI「コウ」）。地で勝つのではなくコウで競る碁。コウ不在時は力戦的に緊張を高めてコウを誘発し（Seek相）、コウ形が現れたら食いつき、取り返し待ち時は相手弱石を脅かすコウ材を選ぶ（KoFight相）。終盤は humanPolicy 最大手（Endgame相）。対応盤面: 19路・13路（他サイズは humanPolicy 最大手に縮退）。

**着手選択**: 2段階クエリ（Stage1 humanSL 9段 / Stage2 クリーンスコア）。重み = `humanPolicy × phase_multiplier`。Seek相は力戦重み（`unsettled^power × proximity × contact_boost`）、KoFight相はコウ取り点に `ko_bonus`、コウ材に `1 + ko_threat_bonus × proximity × instability`。

**コウ検出**: `detect_ko_capture_points`（純粋盤面ロジック・KataGo照会なし）で候補手を分類。`is_ko_ban_active` でコウ禁止状態を判定。snapback は除外。

| パラメータ | デフォルト(19路) | デフォルト(13路) | GUI | 備考 |
|---|---|---|---|---|
| `ko_max_loss` | 6.0 | 4.0 | ✅ | 許容最大損失（目）。劣勢時（score_lead<-6）は min(値,4.0) にキャップ |
| `ko_bonus` | 6.0 | 6.0 | ✅ | コウ取り/作り手の重み倍率 |
| `ko_threat_bonus` | 3.0 | 3.0 | ✅ | コウ材手の重み倍率 |
| `ko_seek_contact_boost` | 1.5 | 1.5 | ✅ | Seek相の接触手ブースト |
| `ko_endgame_move` | 200 | ceil(0.5×マス) | ✅ | ヨセ切替手数（19路。13路は固定式） |
| `ko_seek_unsettled_power` | 2.0 | 2.0 | ❌ config手動 | Seek相の未確定度指数 |
| `ko_seek_proximity_stddev` | 3.0 | 2.5 | ❌ config手動 | Seek相/コウ材の近接stddev |
| `ko_min_group_size` | 5 | 4 | ❌ config手動 | コウ材判定の弱石群最小サイズ |
| `ko_instability_min` | 0.3 | 0.3 | ❌ config手動 | コウ材判定の最小不安定度 |

**ハードコード**: 劣勢閾値 -6.0 / 劣勢時キャップ 4.0 / 選択後安全弁閾値 4.0。
````

依頼後、サブエージェントに「`git add .claude/rules/ai-parameters.md && git commit -m "docs(ko): ai-parameters.md にコウ戦略のパラメータ表を追加"` を実行して」と依頼する。

- [ ] **Step 2: CLAUDE.md の改修概要にコウ戦略を追記**

`CLAUDE.md` の「主な改修」行（ファイル冒頭付近）の戦略列挙に「コウ（Ko）」を追加し、`ai.py` の説明行（`HumanStyleStrategy, FightingStrategy, ...` の列挙）に `KoStrategy` を追加する。

変更前（`ai.py` 行）:
```
    ai.py             -- AI着手生成（HumanStyleStrategy, FightingStrategy, SiegeStrategy, HuntStrategy, HuntDivergenceStrategy, DivergenceStrategy = 主な改修箇所）
```
変更後:
```
    ai.py             -- AI着手生成（HumanStyleStrategy, FightingStrategy, SiegeStrategy, HuntStrategy, HuntDivergenceStrategy, DivergenceStrategy, KoStrategy = 主な改修箇所）
```

- [ ] **Step 3: コミット**

```bash
git add CLAUDE.md
git commit -m "docs(ko): CLAUDE.md にコウ戦略を追記"
```

---

## Task 8: 統合検証（CLI ＋ GUI）

**Files:** なし（実行・確認のみ）

> humanSL モデル（`b18c384nbt-humanv0.bin.gz`）と KataGo が必要。Task 1-4 のユニットテストはモデル不要だが、戦略全体の挙動はこの Task で確認する。

- [ ] **Step 1: 全ユニットテストが通ることを確認**

Run: `pytest tests/test_ko_detection.py tests/test_ko_wiring.py -v`
Expected: PASS（8 tests）

- [ ] **Step 2: CLI で単一局面の分類・フェーズを確認**

Run: `python -m katrain_debug --sgf tests/data/ogs.sgf --move 60 --strategy ko --output text`
Expected: `[KoStrategy] Phase: ...` のログと選択手が出力される。エラーなく Move が返ること。コウが盤上にある局面なら `Phase: KoFight`、なければ `Phase: Seek`。

- [ ] **Step 3: CLI バッチで AI一致率・損失を確認**

Run: `python -m katrain_debug --sgf tests/data/panda1.sgf --strategy ko --batch --player W`
Expected: Aggregate Stats が出力され、平均損失が `ko_max_loss`（白番13路なら4.0、19路なら6.0）を大きく超えないこと。クラッシュしないこと。

- [ ] **Step 4: GUI 実機対局で確認**

1. `C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` を `1` に変更
2. `python -m katrain` で起動
3. 対局相手の AI を「コウ」に設定し、19路または13路で対局を実施
4. GUI のAI設定画面に5項目（許容最大損失/コウ手の重み倍率/コウ材の重み倍率/接触手ブースト/ヨセ切替手数）が表示されることを確認
5. ログを Grep で確認:
   - `grep -a "\[KoStrategy\] Phase:" <ログ>` — Seek/KoFight/Endgame の遷移
   - `grep -a "\[KoStrategy\] Selected:" <ログ>` — 着手結果
   - `grep -a "Post-selection safety\|Losing restrict" <ログ>` — 安全機構の発動
6. コウが実際に発生する局面でコウ手が選ばれているか目視確認
7. 確認後 `debug_level` を `0` に戻す

- [ ] **Step 5: フォーマッタを適用**

Run: `black katrain/core/ai.py katrain/core/constants.py katrain_debug/runner.py tests/test_ko_detection.py tests/test_ko_wiring.py`
Expected: 整形完了。差分があればコミット:

```bash
git add -u
git commit -m "style(ko): black によるフォーマット適用"
```

---

## 完了条件

- [ ] `pytest tests/test_ko_detection.py tests/test_ko_wiring.py` が全て PASS
- [ ] `python -m katrain_debug --strategy ko --batch` がクラッシュせず妥当な損失を出す
- [ ] GUI で「コウ」戦略が選択でき、5項目の設定が表示され、対局でコウ手が選ばれる
- [ ] `debug_level` が `0` に戻っている
