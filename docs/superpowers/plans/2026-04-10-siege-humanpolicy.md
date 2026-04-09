# SiegeStrategy humanPolicy導入 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SiegeStrategyの着手選択にhumanPolicyの重みを導入し、人間らしい手選びを実現する

**Architecture:** FightingStrategy (human) と同じ2段階クエリ方式（Stage1: humanSL→humanPolicy取得、Stage2: クリーンスコア取得）を導入。既存の戦略重み（proximity, instability, concede_score）とhumanPolicyを掛け合わせる。安全弁・タイブレーク・エンドゲーム処理も追加。

**Tech Stack:** Python 3.12, KataGo engine API

---

### Task 1: generate_move() に2段階クエリを追加

**Files:**
- Modify: `katrain/core/ai.py:2708-2755` (SiegeStrategy.generate_move)

- [ ] **Step 1: Stage 1（humanSLProfile付き）クエリを追加**

`generate_move()` の `self.wait_for_analysis()` の直後、パラメータ読み込みの後に Stage 1 クエリを追加する。

`self.wait_for_analysis()` の後の行（現在の `board_size = self.game.board_size` 付近）に以下を挿入:

```python
        # --- Stage 1: humanSLProfile付きクエリ（9段固定） ---
        human_profile = "rank_9d"
        override_settings = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 800,
        }
        self.game.katrain.log(f"[SiegeStrategy] Stage 1: requesting humanSL analysis ({human_profile})", OUTPUT_DEBUG)

        analysis = None
        error = False

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[SiegeStrategy] Error in Stage 1: {a}", OUTPUT_ERROR)

        engine = self.game.engines[self.cn.player]
        engine.request_analysis(
            self.cn,
            callback=set_analysis,
            error_callback=set_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=True,
            extra_settings=override_settings,
        )

        while not (error or analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if error or not analysis or "humanPolicy" not in analysis:
            self.game.katrain.log(f"[SiegeStrategy] Stage 1 failed, falling back to standard policy", OUTPUT_DEBUG)
            # フォールバック: 従来のロジック（humanPolicyなし）
            candidate_moves = self.cn.candidate_moves
            if not candidate_moves:
                return Move(None, player=self.cn.next_player), "No candidate moves found, passing."
            top_move = Move.from_gtp(candidate_moves[0]["move"], player=self.cn.next_player)
            if top_move.is_pass:
                return top_move, "Top move is pass."
            targets = self._find_targets(min_group_size, instability_min)
            has_target = len(targets) > 0
            in_attack_phase = (current_move >= transition_move and has_target) or force_transition
            if in_attack_phase:
                return self._generate_attack_fallback(candidate_moves, targets, max_loss, proximity_stddev)
            else:
                return self._generate_concede_fallback(candidate_moves, concede_max_loss)

        human_policy = analysis["humanPolicy"]
```

- [ ] **Step 2: Stage 2（クリーンスコア）クエリを追加**

Stage 1 の直後に追加:

```python
        # --- Stage 2: クリーンクエリ（正確なスコア取得） ---
        clean_override_settings = {
            "ignorePreRootHistory": False,
            "maxVisits": 600,
            "wideRootNoise": 0.0,
        }
        clean_analysis = None
        clean_error = False

        def set_clean_analysis(a, partial_result):
            nonlocal clean_analysis
            if not partial_result:
                clean_analysis = a

        def set_clean_error(a):
            nonlocal clean_error
            clean_error = True
            self.game.katrain.log(f"[SiegeStrategy] Error in Stage 2: {a}", OUTPUT_ERROR)

        self.game.katrain.log(f"[SiegeStrategy] Stage 2: requesting clean analysis", OUTPUT_DEBUG)
        engine.request_analysis(
            self.cn,
            callback=set_clean_analysis,
            error_callback=set_clean_error,
            priority=PRIORITY_EXTRA_AI_QUERY,
            include_policy=False,
            extra_settings=clean_override_settings,
        )

        while not (clean_error or clean_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        if clean_analysis and not clean_error:
            move_infos = clean_analysis.get("moveInfos", [])
            self.game.katrain.log(f"[SiegeStrategy] Using clean moveInfos ({len(move_infos)} moves)", OUTPUT_DEBUG)
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log(f"[SiegeStrategy] Clean query failed, using Stage 1 moveInfos", OUTPUT_DEBUG)
```

- [ ] **Step 3: スコア計算・悪手フィルタの共通処理を追加**

Stage 2 の直後に追加。フェーズ別に閾値を使い分けるため、ここではmove_infosの前処理とarea scoringの判定のみ行う:

```python
        # --- スコア計算の前処理 ---
        player_sign = 1 if self.cn.next_player == "B" else -1
        best_score = None
        best_gtp_by_score = None
        if move_infos:
            best_score = max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
            best_gtp_by_score = max(
                move_infos, key=lambda mi: mi.get("scoreLead", 0) * player_sign
            ).get("move", "")

            if best_gtp_by_score == "pass":
                self.game.katrain.log(f"[SiegeStrategy] Best move is pass, forcing pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."

        # area scoringルール判定
        _ruleset = self.cn.ruleset
        _rules = KataGoEngine.get_rules(_ruleset)
        is_area_scoring = (
            (isinstance(_rules, str) and _rules.lower() in ["chinese", "aga", "tromp-taylor", "new zealand", "stone_scoring"])
            or (isinstance(_rules, dict) and _rules.get("scoring", "").lower() == "area")
        )
```

- [ ] **Step 4: フェーズ判定とディスパッチを更新**

既存のフェーズ判定ロジックを維持しつつ、新しい引数を渡すように更新:

```python
        targets = self._find_targets(min_group_size, instability_min)
        has_target = len(targets) > 0
        in_attack_phase = (current_move >= transition_move and has_target) or force_transition

        if in_attack_phase:
            phase = "attack (forced)" if force_transition and not has_target else "attack"
            self.game.katrain.log(f"[SiegeStrategy] Phase: {phase}, move={current_move}, targets={len(targets)}", OUTPUT_DEBUG)
            return self._generate_attack(
                human_policy, move_infos, targets, max_loss, proximity_stddev,
                player_sign, best_score, best_gtp_by_score, is_area_scoring,
            )
        else:
            self.game.katrain.log(f"[SiegeStrategy] Phase: concede, move={current_move}", OUTPUT_DEBUG)
            return self._generate_concede(
                human_policy, move_infos, concede_max_loss,
                player_sign, best_score, best_gtp_by_score, is_area_scoring,
            )
```

- [ ] **Step 5: 既存メソッドをフォールバック用にリネーム**

既存の `_generate_concede` と `_generate_attack` を `_generate_concede_fallback` と `_generate_attack_fallback` にリネームする（Stage 1 失敗時のフォールバック用として残す）:

```python
    def _generate_concede_fallback(self, candidate_moves, concede_max_loss):
        """フォールバック: humanPolicy取得失敗時の序盤フェーズ（従来ロジック）"""
        # 既存の _generate_concede のコードをそのまま維持
        ...

    def _generate_attack_fallback(self, candidate_moves, targets, max_loss, proximity_stddev):
        """フォールバック: humanPolicy取得失敗時の攻撃フェーズ（従来ロジック）"""
        # 既存の _generate_attack のコードをそのまま維持
        ...
```

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py
git commit -m "refactor: SiegeStrategyに2段階クエリ基盤を追加（humanPolicy/クリーンスコア）"
```

---

### Task 2: _generate_concede() をhumanPolicy対応に書き換え

**Files:**
- Modify: `katrain/core/ai.py` (SiegeStrategy._generate_concede)

- [ ] **Step 1: 新しい _generate_concede() を実装**

humanPolicy + Stage 2 スコアフィルタ + pass処理を含む新メソッド:

```python
    def _generate_concede(self, human_policy, move_infos, concede_max_loss,
                          player_sign, best_score, best_gtp_by_score, is_area_scoring):
        """序盤フェーズ: humanPolicy × concede_score で地を譲る手を選択する。"""
        board_size = self.game.board_size
        bx, by = board_size

        # --- Stage 2 moveInfosで悪手フィルタ ---
        good_moves = set()
        if move_infos and best_score is not None:
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss <= concede_max_loss:
                    good_moves.add(gtp_move)

            self.game.katrain.log(
                f"[SiegeStrategy:concede] {len(good_moves)} moves pass score filter out of {len(move_infos)} "
                f"(threshold={concede_max_loss})",
                OUTPUT_DEBUG,
            )

        # --- スコア情報をdict化 ---
        score_by_gtp = {}
        if move_infos:
            for mi in move_infos:
                score_by_gtp[mi.get("move", "")] = mi.get("scoreLead", 0)

        # --- humanPolicy × concede_score で候補構築 ---
        has_filter = len(good_moves) > 0
        moves = []
        filtered_count = 0
        for x in range(bx):
            for y in range(by):
                idx = (by - y - 1) * bx + x
                if idx < len(human_policy) and human_policy[idx] > 0:
                    m = Move((x, y), player=self.cn.next_player)
                    if has_filter and m.gtp() not in good_moves:
                        filtered_count += 1
                        continue

                    hp_weight = human_policy[idx]

                    # concede_score: 損失が大きいほど高い重み（地を譲る手を優先）
                    gtp = m.gtp()
                    if gtp in score_by_gtp and best_score is not None:
                        score = score_by_gtp[gtp]
                        loss = player_sign * (best_score - score)
                        concede_score = min(max(loss, 0), concede_max_loss) / concede_max_loss
                        concede_score = max(concede_score, 0.05)
                    else:
                        concede_score = 0.5  # スコア不明の手はデフォルト中間値

                    weight = hp_weight * concede_score
                    moves.append((m, weight))

        # passが候補に含まれるか確認
        pass_idx = bx * by
        if pass_idx < len(human_policy) and human_policy[pass_idx] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[pass_idx]))

        self.game.katrain.log(
            f"[SiegeStrategy:concede] {len(moves)} candidate moves ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )

        # フォールバック
        if not moves:
            self.game.katrain.log(f"[SiegeStrategy:concede] No valid moves, playing best move", OUTPUT_DEBUG)
            if best_gtp_by_score and best_gtp_by_score != "pass":
                return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), "Concede fallback: no valid moves."
            if move_infos:
                fb = move_infos[0].get("move", "pass")
                if fb == "pass":
                    return Move(None, player=self.cn.next_player), "Concede fallback: pass."
                return Move.from_gtp(fb, player=self.cn.next_player), "Concede fallback: best search move."
            return Move(None, player=self.cn.next_player), "Concede fallback: no moves."

        # --- pass処理（area scoring） ---
        if any(m.is_pass for m, _ in moves):
            if is_area_scoring:
                _AREA_PASS_MARGIN = 0.5
                pass_mi = next((mi for mi in (move_infos or []) if mi.get("move") == "pass"), None)
                if pass_mi is not None and best_score is not None:
                    pass_loss = player_sign * (best_score - pass_mi.get("scoreLead", best_score))
                    if pass_loss < _AREA_PASS_MARGIN:
                        self.game.katrain.log(
                            f"[SiegeStrategy:concede] Area scoring: pass near-optimal (loss={pass_loss:.2f}), forcing pass",
                            OUTPUT_DEBUG,
                        )
                        return Move(None, player=self.cn.next_player), "Area scoring: pass near-optimal, forcing pass."
                moves_no_pass = [(m, w) for m, w in moves if not m.is_pass]
                if moves_no_pass:
                    moves = moves_no_pass
                else:
                    if best_gtp_by_score and best_gtp_by_score != "pass":
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), \
                            "Area scoring: playing best non-pass move."
                    return Move(None, player=self.cn.next_player), "Area scoring: no non-pass candidates."
            else:
                return Move(None, player=self.cn.next_player), "Pass is in candidates, forcing pass."

        # --- 安全弁: 最高重み候補のlossが閾値以上なら最善スコア手に強制切替 ---
        _SAFETY_LOSS_THRESHOLD = 4.0
        if moves and move_infos and best_gtp_by_score:
            top_move_candidate, _ = max(moves, key=lambda x: x[1])
            top_gtp = top_move_candidate.gtp()
            if top_gtp in score_by_gtp and top_gtp != best_gtp_by_score:
                top_loss = player_sign * (best_score - score_by_gtp[top_gtp])
                if top_loss >= _SAFETY_LOSS_THRESHOLD:
                    self.game.katrain.log(
                        f"[SiegeStrategy:concede] Safety valve: top weighted {top_gtp} "
                        f"loss={top_loss:.2f} >= {_SAFETY_LOSS_THRESHOLD}, "
                        f"forcing best-score move {best_gtp_by_score}",
                        OUTPUT_DEBUG,
                    )
                    if best_gtp_by_score == "pass":
                        return Move(None, player=self.cn.next_player), "Safety valve: best move is pass."
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                        f"Safety valve: top weighted {top_gtp} had loss={top_loss:.2f}, "
                        f"forced best-score move {best_gtp_by_score}."
                    )

        # --- エンドゲーム: 戦略重みを無視してtop humanPolicy ---
        endgame_threshold = 32 if (bx == 9 and by == 9) else math.ceil(bx * by * 0.5)
        current_move = self.cn.depth
        if current_move >= endgame_threshold:
            endgame_moves = []
            for x in range(bx):
                for y in range(by):
                    idx = (by - y - 1) * bx + x
                    if idx < len(human_policy) and human_policy[idx] > 0:
                        m = Move((x, y), player=self.cn.next_player)
                        if not has_filter or m.gtp() in good_moves:
                            endgame_moves.append((m, human_policy[idx]))
            if endgame_moves:
                top_move = max(endgame_moves, key=lambda x: x[1])
                self.game.katrain.log(
                    f"[SiegeStrategy:concede] Endgame: playing top humanPolicy move {top_move[0].gtp()}",
                    OUTPUT_DEBUG,
                )
                return top_move[0], f"Endgame: played top humanPolicy move {top_move[0].gtp()}."

        # --- タイブレーク ---
        _TIEBREAK_WEIGHT_RATIO = 1.05
        _TIEBREAK_SCORE_DIFF = 2.0
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
        if len(top5) >= 2 and move_infos:
            _score_by_gtp_tb = {mi.get("move", ""): mi.get("scoreLead", 0) * player_sign for mi in move_infos}
            _visits_by_gtp = {mi.get("move", ""): mi.get("visits", 0) for mi in move_infos}
            top1_move, top1_w = top5[0]
            top2_move, top2_w = top5[1]
            top1_visits = _visits_by_gtp.get(top1_move.gtp(), 0)
            top2_visits = _visits_by_gtp.get(top2_move.gtp(), 0)
            is_policy_close = top2_w > 0 and top1_w / top2_w < _TIEBREAK_WEIGHT_RATIO
            is_visits_reversal = top2_visits > top1_visits * 2.0
            is_mcts_nonprefer = top1_visits > 0 and top2_visits >= top1_visits
            if is_policy_close or is_visits_reversal or is_mcts_nonprefer:
                s1 = _score_by_gtp_tb.get(top1_move.gtp())
                s2 = _score_by_gtp_tb.get(top2_move.gtp())
                if s1 is not None and s2 is not None and abs(s1 - s2) >= _TIEBREAK_SCORE_DIFF:
                    winner = top1_move if s1 > s2 else top2_move
                    loser = top2_move if s1 > s2 else top1_move
                    trigger = "policy" if is_policy_close else ("visits_reversal" if is_visits_reversal else "mcts_nonprefer")
                    self.game.katrain.log(
                        f"[SiegeStrategy:concede] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt)",
                        OUTPUT_DEBUG,
                    )
                    return winner, f"Siege[concede] tiebreak({trigger}): played {winner.gtp()} (score diff={abs(s1-s2):.1f}pt)."

        # --- デバッグ: 上位5手表示 ---
        top_str = "\n".join([f"#{i+1}: {m.gtp()} weight={w:.4f}" for i, (m, w) in enumerate(top5)])
        self.game.katrain.log(f"[SiegeStrategy:concede] Top 5:\n{top_str}", OUTPUT_DEBUG)

        # --- 重み付き選択 ---
        selected = weighted_selection_without_replacement(moves, 1)[0]
        aimove = selected[0]
        ai_thoughts = (
            f"Siege[concede]: {len(moves)} candidates within {concede_max_loss}pt. "
            f"Selected {aimove.gtp()} (weight={selected[1]:.4f}). ({filtered_count} filtered)"
        )
        self.game.katrain.log(f"[SiegeStrategy:concede] Selected: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts
```

- [ ] **Step 2: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: SiegeStrategy _generate_concede をhumanPolicy対応に書き換え"
```

---

### Task 3: _generate_attack() をhumanPolicy対応に書き換え

**Files:**
- Modify: `katrain/core/ai.py` (SiegeStrategy._generate_attack)

- [ ] **Step 1: 新しい _generate_attack() を実装**

humanPolicy + Stage 2 スコアフィルタ + proximity × instability + pass処理 + 安全弁 + タイブレーク + エンドゲームを含む新メソッド:

```python
    def _generate_attack(self, human_policy, move_infos, targets, max_loss, proximity_stddev,
                         player_sign, best_score, best_gtp_by_score, is_area_scoring):
        """攻撃フェーズ: humanPolicy × proximity × instability で着手選択する。"""
        board_size = self.game.board_size
        bx, by = board_size
        prox_var = proximity_stddev ** 2

        # ターゲット情報
        if targets:
            primary_target = targets[0]
            target_instability = primary_target[1]
            target_coords = primary_target[2]
            if len(targets) > 1:
                target_coords = target_coords | targets[1][2]
        else:
            target_instability = 0.5
            target_coords = set()
            for s in self.game.stones:
                if s.player != self.cn.next_player and s.coords:
                    target_coords.add(s.coords)
            if not target_coords:
                if best_gtp_by_score and best_gtp_by_score != "pass":
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), "Attack: no opponent stones."
                return Move(None, player=self.cn.next_player), "Attack: no opponent stones, passing."

        # --- Stage 2 moveInfosで悪手フィルタ ---
        good_moves = set()
        if move_infos and best_score is not None:
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss <= max_loss:
                    good_moves.add(gtp_move)

            self.game.katrain.log(
                f"[SiegeStrategy:attack] {len(good_moves)} moves pass score filter out of {len(move_infos)} "
                f"(threshold={max_loss})",
                OUTPUT_DEBUG,
            )

        # --- スコア情報をdict化 ---
        score_by_gtp = {}
        if move_infos:
            for mi in move_infos:
                score_by_gtp[mi.get("move", "")] = mi.get("scoreLead", 0)

        # --- humanPolicy × proximity × instability で候補構築 ---
        has_filter = len(good_moves) > 0
        moves = []
        filtered_count = 0
        for x in range(bx):
            for y in range(by):
                idx = (by - y - 1) * bx + x
                if idx < len(human_policy) and human_policy[idx] > 0:
                    m = Move((x, y), player=self.cn.next_player)
                    if has_filter and m.gtp() not in good_moves:
                        filtered_count += 1
                        continue

                    hp_weight = human_policy[idx]

                    # ターゲットへの近接度
                    min_dist_sq = min((x - tx) ** 2 + (y - ty) ** 2 for tx, ty in target_coords)
                    proximity = math.exp(-0.5 * min_dist_sq / prox_var) if prox_var > 0 else 1.0

                    weight = hp_weight * proximity * target_instability
                    moves.append((m, weight))

        # passが候補に含まれるか確認
        pass_idx = bx * by
        if pass_idx < len(human_policy) and human_policy[pass_idx] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[pass_idx]))

        self.game.katrain.log(
            f"[SiegeStrategy:attack] Targets: {len(targets)}, candidates: {len(moves)} ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )

        # フォールバック
        if not moves:
            self.game.katrain.log(f"[SiegeStrategy:attack] No valid moves within {max_loss}pt, playing best", OUTPUT_DEBUG)
            if best_gtp_by_score and best_gtp_by_score != "pass":
                return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), "Attack fallback: no moves within threshold."
            if move_infos:
                fb = move_infos[0].get("move", "pass")
                if fb == "pass":
                    return Move(None, player=self.cn.next_player), "Attack fallback: pass."
                return Move.from_gtp(fb, player=self.cn.next_player), "Attack fallback: best search move."
            return Move(None, player=self.cn.next_player), "Attack fallback: no moves."

        # --- pass処理（area scoring） ---
        if any(m.is_pass for m, _ in moves):
            if is_area_scoring:
                _AREA_PASS_MARGIN = 0.5
                pass_mi = next((mi for mi in (move_infos or []) if mi.get("move") == "pass"), None)
                if pass_mi is not None and best_score is not None:
                    pass_loss = player_sign * (best_score - pass_mi.get("scoreLead", best_score))
                    if pass_loss < _AREA_PASS_MARGIN:
                        self.game.katrain.log(
                            f"[SiegeStrategy:attack] Area scoring: pass near-optimal (loss={pass_loss:.2f}), forcing pass",
                            OUTPUT_DEBUG,
                        )
                        return Move(None, player=self.cn.next_player), "Area scoring: pass near-optimal, forcing pass."
                moves_no_pass = [(m, w) for m, w in moves if not m.is_pass]
                if moves_no_pass:
                    moves = moves_no_pass
                else:
                    if best_gtp_by_score and best_gtp_by_score != "pass":
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), \
                            "Area scoring: playing best non-pass move."
                    return Move(None, player=self.cn.next_player), "Area scoring: no non-pass candidates."
            else:
                return Move(None, player=self.cn.next_player), "Pass is in candidates, forcing pass."

        # --- 安全弁: 最高重み候補のlossが閾値以上なら最善スコア手に強制切替 ---
        _SAFETY_LOSS_THRESHOLD = 4.0
        if moves and move_infos and best_gtp_by_score:
            top_move_candidate, _ = max(moves, key=lambda x: x[1])
            top_gtp = top_move_candidate.gtp()
            if top_gtp in score_by_gtp and top_gtp != best_gtp_by_score:
                top_loss = player_sign * (best_score - score_by_gtp[top_gtp])
                if top_loss >= _SAFETY_LOSS_THRESHOLD:
                    self.game.katrain.log(
                        f"[SiegeStrategy:attack] Safety valve: top weighted {top_gtp} "
                        f"loss={top_loss:.2f} >= {_SAFETY_LOSS_THRESHOLD}, "
                        f"forcing best-score move {best_gtp_by_score}",
                        OUTPUT_DEBUG,
                    )
                    if best_gtp_by_score == "pass":
                        return Move(None, player=self.cn.next_player), "Safety valve: best move is pass."
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                        f"Safety valve: top weighted {top_gtp} had loss={top_loss:.2f}, "
                        f"forced best-score move {best_gtp_by_score}."
                    )

        # --- エンドゲーム: 戦略重みを無視してtop humanPolicy ---
        endgame_threshold = 32 if (bx == 9 and by == 9) else math.ceil(bx * by * 0.5)
        current_move = self.cn.depth
        if current_move >= endgame_threshold:
            endgame_moves = []
            for x in range(bx):
                for y in range(by):
                    idx = (by - y - 1) * bx + x
                    if idx < len(human_policy) and human_policy[idx] > 0:
                        m = Move((x, y), player=self.cn.next_player)
                        if not has_filter or m.gtp() in good_moves:
                            endgame_moves.append((m, human_policy[idx]))
            if endgame_moves:
                top_move = max(endgame_moves, key=lambda x: x[1])
                self.game.katrain.log(
                    f"[SiegeStrategy:attack] Endgame: playing top humanPolicy move {top_move[0].gtp()}",
                    OUTPUT_DEBUG,
                )
                return top_move[0], f"Endgame: played top humanPolicy move {top_move[0].gtp()}."

        # --- タイブレーク ---
        _TIEBREAK_WEIGHT_RATIO = 1.05
        _TIEBREAK_SCORE_DIFF = 2.0
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
        if len(top5) >= 2 and move_infos:
            _score_by_gtp_tb = {mi.get("move", ""): mi.get("scoreLead", 0) * player_sign for mi in move_infos}
            _visits_by_gtp = {mi.get("move", ""): mi.get("visits", 0) for mi in move_infos}
            top1_move, top1_w = top5[0]
            top2_move, top2_w = top5[1]
            top1_visits = _visits_by_gtp.get(top1_move.gtp(), 0)
            top2_visits = _visits_by_gtp.get(top2_move.gtp(), 0)
            is_policy_close = top2_w > 0 and top1_w / top2_w < _TIEBREAK_WEIGHT_RATIO
            is_visits_reversal = top2_visits > top1_visits * 2.0
            is_mcts_nonprefer = top1_visits > 0 and top2_visits >= top1_visits
            if is_policy_close or is_visits_reversal or is_mcts_nonprefer:
                s1 = _score_by_gtp_tb.get(top1_move.gtp())
                s2 = _score_by_gtp_tb.get(top2_move.gtp())
                if s1 is not None and s2 is not None and abs(s1 - s2) >= _TIEBREAK_SCORE_DIFF:
                    winner = top1_move if s1 > s2 else top2_move
                    loser = top2_move if s1 > s2 else top1_move
                    trigger = "policy" if is_policy_close else ("visits_reversal" if is_visits_reversal else "mcts_nonprefer")
                    self.game.katrain.log(
                        f"[SiegeStrategy:attack] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt)",
                        OUTPUT_DEBUG,
                    )
                    return winner, (
                        f"Siege[attack] tiebreak({trigger}): played {winner.gtp()} (score diff={abs(s1-s2):.1f}pt). "
                        f"({filtered_count} filtered)"
                    )

        # --- デバッグ: 上位5手表示 ---
        top_str = "\n".join([f"#{i+1}: {m.gtp()} weight={w:.4f}" for i, (m, w) in enumerate(top5)])
        self.game.katrain.log(f"[SiegeStrategy:attack] Top 5:\n{top_str}", OUTPUT_DEBUG)

        # --- 重み付き選択 ---
        selected = weighted_selection_without_replacement(moves, 1)[0]
        aimove = selected[0]
        target_info = f"primary_size={len(targets[0][2])}" if targets else "pressure_mode"
        ai_thoughts = (
            f"Siege[attack]: {target_info}, {len(moves)} candidates within {max_loss}pt. "
            f"Selected {aimove.gtp()} (weight={selected[1]:.4f}). ({filtered_count} filtered)"
        )
        self.game.katrain.log(f"[SiegeStrategy:attack] Selected: {aimove.gtp()}", OUTPUT_DEBUG)
        return aimove, ai_thoughts
```

- [ ] **Step 2: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: SiegeStrategy _generate_attack をhumanPolicy対応に書き換え"
```

---

### Task 4: 手動検証

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json` (debug_level 一時変更)

- [ ] **Step 1: debug_level を有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `"debug_level": 1` に変更。

- [ ] **Step 2: KaTrainを起動して対局テスト**

```bash
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
python -m katrain
```

攻城戦略（ai:siege）を選択して19路盤で対局を開始。
以下のログが出ることを確認:

- `[SiegeStrategy] Stage 1: requesting humanSL analysis (rank_9d)` — Stage 1 クエリ
- `[SiegeStrategy] Stage 2: requesting clean analysis` — Stage 2 クエリ
- `[SiegeStrategy:concede] N moves pass score filter` — 悪手フィルタ動作
- `[SiegeStrategy:concede] N candidate moves (M filtered)` — humanPolicy候補構築
- `[SiegeStrategy:attack] N moves pass score filter` — 攻撃フェーズのフィルタ

- [ ] **Step 3: debug_level を戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` → `"debug_level": 0` に変更。

- [ ] **Step 4: 最終コミット（必要な修正があった場合）**

```bash
git add katrain/core/ai.py
git commit -m "fix: SiegeStrategy humanPolicy導入の検証修正"
```
