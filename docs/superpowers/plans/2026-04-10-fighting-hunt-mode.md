# Fighting Hunt Mode（狩猟モード）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FightingStrategy に新モード `"hunt"` を追加し、弱い相手石群を見つけて集中攻撃する狩猟型の着手選択を実現する。

**Architecture:** SiegeStrategy の `_find_targets()` をモジュールレベル関数 `find_targets()` に抽出して共有化し、FightingStrategy に `_generate_hunt()` メソッドを新設する。2段階クエリ（humanSL 9段 + クリーンスコア）でターゲット有無に応じた重み計算を行い、安全弁・タイブレーク・エンドゲーム処理は既存 human モードと同じパターンを適用する。

**Tech Stack:** Python 3.12, KataGo v1.16.4, Kivy GUI

**Spec:** `docs/superpowers/specs/2026-04-10-fighting-hunt-mode-design.md`

---

### Task 1: `find_targets()` をモジュールレベル関数に抽出し SiegeStrategy をリファクタ

**Files:**
- Modify: `katrain/core/ai.py:2871-2917` (SiegeStrategy._find_targets → 削除)
- Modify: `katrain/core/ai.py:57` 付近 (find_connected_groups の直後に find_targets を追加)
- Modify: `katrain/core/ai.py:2777-2779, 2853-2855` (SiegeStrategy 内の呼び出し元)

- [ ] **Step 1: `find_connected_groups()` の直後（57行目付近）にモジュールレベル `find_targets()` を追加**

```python
def find_targets(game, cn, min_group_size, instability_min):
    """ターゲットとなる不安定な相手石群を特定する（共有関数）。

    Args:
        game: Game オブジェクト（stones, board_size, katrain.log にアクセス）
        cn: GameNode オブジェクト（ownership, next_player にアクセス）
        min_group_size: ターゲットとする最小グループサイズ
        instability_min: ターゲット判定の最小不安定度
    Returns:
        [(target_score, instability, group_coords_set), ...] スコア降順
    """
    board_size = game.board_size
    ownership = cn.ownership
    if not ownership:
        game.katrain.log("[find_targets] No ownership data available", OUTPUT_DEBUG)
        return []

    ownership_grid = var_to_grid(ownership, board_size)

    opponent_coords = set()
    for s in game.stones:
        if s.player != cn.next_player and s.coords:
            opponent_coords.add(s.coords)

    if not opponent_coords:
        return []

    groups = find_connected_groups(opponent_coords)

    targets = []
    for group in groups:
        if len(group) < min_group_size:
            continue

        total_ownership = 0.0
        for x, y in group:
            total_ownership += ownership_grid[y][x]
        avg_ownership = total_ownership / len(group)

        instability = 1.0 - abs(avg_ownership)
        if instability < instability_min:
            continue

        target_score = len(group) * instability
        targets.append((target_score, instability, group))

    targets.sort(key=lambda t: t[0], reverse=True)

    if targets:
        top = targets[0]
        game.katrain.log(
            f"[find_targets] Primary target: size={len(top[2])}, instability={top[1]:.2f}, score={top[0]:.2f}",
            OUTPUT_DEBUG,
        )

    return targets
```

- [ ] **Step 2: SiegeStrategy の `_find_targets` メソッドを削除（2871-2917行）**

`_find_targets` メソッド全体を削除する。

- [ ] **Step 3: SiegeStrategy 内の呼び出し箇所を `find_targets()` に変更**

2箇所変更する:

**呼び出し1（2777行付近）:**
```python
# 変更前:
            targets = self._find_targets(min_group_size, instability_min)
# 変更後:
            targets = find_targets(self.game, self.cn, min_group_size, instability_min)
```

**呼び出し2（2853行付近）:**
```python
# 変更前:
        targets = self._find_targets(min_group_size, instability_min)
# 変更後:
        targets = find_targets(self.game, self.cn, min_group_size, instability_min)
```

- [ ] **Step 4: 起動確認**

```bash
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
python -c "from katrain.core.ai import find_targets, find_connected_groups; print('Import OK')"
```

Expected: `Import OK`（構文エラーがないことを確認）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "refactor: _find_targets()をモジュールレベル関数find_targets()に抽出"
```

---

### Task 2: constants.py に hunt モードのパラメータを追加

**Files:**
- Modify: `katrain/core/constants.py:146-150` (fighting_mode に hunt 追加)
- Modify: `katrain/core/constants.py:156-161` 付近 (AI_OPTION_VALUES に hunt パラメータ追加)
- Modify: `katrain/core/constants.py:175-180` 付近 (AI_OPTION_ORDER に hunt 表示順追加)

- [ ] **Step 1: `fighting_mode` に `"hunt"` を追加（146-150行）**

```python
# 変更前:
    "fighting_mode": [
        ("classic", "[fighting:classic]"),
        ("scoreloss", "[fighting:scoreloss]"),
        ("human", "[fighting:human]"),
    ],
# 変更後:
    "fighting_mode": [
        ("classic", "[fighting:classic]"),
        ("scoreloss", "[fighting:scoreloss]"),
        ("human", "[fighting:human]"),
        ("hunt", "[fighting:hunt]"),
    ],
```

- [ ] **Step 2: `AI_OPTION_VALUES` に hunt パラメータ4つを追加（161行の `}` 直前）**

`"siege_instability_min"` の行の後に追加:

```python
    "hunt_max_loss": [x / 2 for x in range(2, 21)],  # 1.0〜10.0（0.5刻み）
    "hunt_min_group_size": list(range(2, 11)),  # 2〜10
    "hunt_proximity_stddev": [x / 2 for x in range(3, 13)],  # 1.5〜6.0（0.5刻み）
    "hunt_instability_min": [x / 10 for x in range(1, 9)],  # 0.1〜0.8（0.1刻み）
```

- [ ] **Step 3: `AI_OPTION_ORDER` に hunt パラメータの表示順を追加（192行の `}` 直前）**

`"siege_instability_min": 21,` の後に追加:

```python
    "hunt_max_loss": 6,
    "hunt_min_group_size": 7,
    "hunt_proximity_stddev": 8,
    "hunt_instability_min": 9,
```

- [ ] **Step 4: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat: constants.pyにhuntモードのGUIパラメータ定義を追加"
```

---

### Task 3: config.json（パッケージ + ユーザー）に hunt パラメータのデフォルト値を追加

**Files:**
- Modify: `katrain/config.json:159-172` (ai:p:fighting セクション)
- Modify: `C:\Users\iwaki\.katrain\config.json:159-172` (ai:p:fighting セクション)

- [ ] **Step 1: パッケージ `katrain/config.json` の `"ai:p:fighting"` に hunt パラメータ追加**

`"proximity_stddev": 3.0` の後に4つ追加:

```json
    "hunt_max_loss": 6.0,
    "hunt_min_group_size": 5,
    "hunt_proximity_stddev": 3.0,
    "hunt_instability_min": 0.3
```

変更後の `"ai:p:fighting"` 全体:
```json
"ai:p:fighting": {
    "fighting_mode": "classic",
    "fighting_max_loss": 3.0,
    "force_tengen_opening": false,
    "fighting_invasion_bonus": 1.0,
    "fighting_contact_boost": 1.0,
    "fighting_chaos_relax": 0.0,
    "pick_override": 0.95,
    "pick_n": 10,
    "pick_frac": 0.2,
    "endgame": 0.45,
    "unsettled_power": 2.0,
    "proximity_stddev": 3.0,
    "hunt_max_loss": 6.0,
    "hunt_min_group_size": 5,
    "hunt_proximity_stddev": 3.0,
    "hunt_instability_min": 0.3
}
```

- [ ] **Step 2: ユーザー `C:\Users\iwaki\.katrain\config.json` の `"ai:p:fighting"` にも同じ4キーを追加**

`"proximity_stddev": 3.0` の後に同じ4つを追加（`fighting_mode` の現在値 `"human"` はそのまま維持）:

```json
    "hunt_max_loss": 6.0,
    "hunt_min_group_size": 5,
    "hunt_proximity_stddev": 3.0,
    "hunt_instability_min": 0.3
```

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat: config.jsonにhuntモードのデフォルト値を追加"
```

注意: ユーザー config (`C:\Users\iwaki\.katrain\config.json`) は git 管理外なのでコミットに含めない。

---

### Task 4: i18n ファイル（英語 + 日本語）に hunt モードの説明を追加

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:917-924` (aihelp:p:fighting)
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:602-609` (aihelp:p:fighting)

- [ ] **Step 1: 英語 i18n の `aihelp:p:fighting` を更新**

既存の msgstr の末尾に hunt モードの説明を追加する（`\n` で改行）:

```
# 変更前の最終行:
"'endgame': disables fighting weights after this board fraction."

# 変更後（末尾に追加）:
"'endgame': disables fighting weights after this board fraction.\n"
"\n"
"'hunt' mode: Identifies weak opponent groups and focuses attacks on them. "
"When no targets exist, plays like a normal 9-dan. 9x9 not supported (falls back to human mode).\n"
"'hunt_max_loss': max point loss allowed when attacking a target (higher=riskier, lower=safer).\n"
"'hunt_min_group_size': minimum stones in an opponent group to be targeted (lower=smaller groups too, higher=big groups only).\n"
"'hunt_proximity_stddev': how tightly focused attacks are on the target (lower=concentrate near target, higher=spread wider).\n"
"'hunt_instability_min': minimum instability to consider a group as target (lower=more stable groups too, higher=very unstable only)."
```

- [ ] **Step 2: 日本語 i18n の `aihelp:p:fighting` を更新**

既存の msgstr の末尾に hunt モードの説明を追加する:

```
# 変更前の最終行:
"'endgame'以降は力戦重みを無効化."

# 変更後（末尾に追加）:
"'endgame'以降は力戦重みを無効化.\n"
"\n"
"'hunt'モード: 相手の弱い石群を見つけて集中攻撃する狩猟モード. "
"ターゲットがない時は通常の9段として着手. 9路盤は非対応(humanモードにフォールバック).\n"
"'hunt_max_loss': 攻撃時に許容する最大損失(目数). 大きい=リスクの高い攻めを許容, 小さい=安全な攻め.\n"
"'hunt_min_group_size': ターゲットとする最小グループサイズ. 小さい=小さい石群も狙う, 大きい=大石だけ狙う.\n"
"'hunt_proximity_stddev': 攻撃の集中度. 小さい=ターゲット付近に集中, 大きい=広く攻める.\n"
"'hunt_instability_min': ターゲット判定の最小不安定度. 小さい=安定した石群も狙う, 大きい=非常に不安定な石群だけ狙う."
```

- [ ] **Step 3: コミット**

```bash
git add katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.po
git commit -m "feat: i18nにhuntモードのGUI説明テキストを追加"
```

---

### Task 5: FightingStrategy に `_generate_hunt()` を実装しディスパッチャを更新

**Files:**
- Modify: `katrain/core/ai.py:1378-1392` (generate_move ディスパッチャ)
- Modify: `katrain/core/ai.py:1928` 付近 (_generate_human の直後に _generate_hunt を追加)

- [ ] **Step 1: `generate_move()` ディスパッチャに `"hunt"` ルートを追加（1378-1392行）**

```python
# 変更前:
        if mode == "scoreloss":
            return self._generate_scoreloss()
        elif mode == "human":
            return self._generate_human()
        else:
            return self._generate_classic()

# 変更後:
        if mode == "scoreloss":
            return self._generate_scoreloss()
        elif mode == "human":
            return self._generate_human()
        elif mode == "hunt":
            return self._generate_hunt()
        else:
            return self._generate_classic()
```

- [ ] **Step 2: `_generate_human()` の直後（1928行付近）に `_generate_hunt()` メソッドを追加**

`_generate_human()` メソッドの `return move, ai_thoughts` の後、`generate_weighted_coords()` の前に以下を挿入:

```python
    def _generate_hunt(self) -> Tuple[Move, str]:
        """Hunt mode: 弱い石群を見つけて集中攻撃する狩猟モード。"""
        board_size = self.game.board_size
        bx, by = board_size

        # 9路フォールバック
        if bx == 9 and by == 9:
            self.game.katrain.log(
                "[FightingStrategy:hunt] Hunt mode not supported on 9x9, falling back to human mode",
                OUTPUT_DEBUG,
            )
            return self._generate_human()

        # 盤面サイズ別デフォルト
        if bx <= 13:
            default_max_loss = 4.0
            default_min_group = 4
            default_prox_stddev = 2.5
        else:
            default_max_loss = 6.0
            default_min_group = 5
            default_prox_stddev = 3.0

        hunt_max_loss = self.settings.get("hunt_max_loss", default_max_loss)
        hunt_min_group_size = self.settings.get("hunt_min_group_size", default_min_group)
        hunt_proximity_stddev = self.settings.get("hunt_proximity_stddev", default_prox_stddev)
        hunt_instability_min = self.settings.get("hunt_instability_min", 0.3)

        self.game.katrain.log(
            f"[FightingStrategy:hunt] Starting move generation "
            f"(max_loss={hunt_max_loss}, min_group={hunt_min_group_size}, "
            f"prox_stddev={hunt_proximity_stddev}, instability_min={hunt_instability_min})",
            OUTPUT_DEBUG,
        )

        # 標準解析を待つ（ownership取得のため）
        self.wait_for_analysis()

        # --- Stage 1: humanSLProfile付きクエリ（9段固定） ---
        human_profile = "rank_9d"
        override_settings = {
            "humanSLProfile": human_profile,
            "ignorePreRootHistory": False,
            "maxVisits": 800,
        }
        self.game.katrain.log(
            f"[FightingStrategy:hunt] Stage 1: requesting humanSL analysis ({human_profile})",
            OUTPUT_DEBUG,
        )

        analysis = None
        error = False

        def set_analysis(a, partial_result):
            nonlocal analysis
            if not partial_result:
                analysis = a

        def set_error(a):
            nonlocal error
            error = True
            self.game.katrain.log(f"[FightingStrategy:hunt] Error in Stage 1: {a}", OUTPUT_ERROR)

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
            self.game.katrain.log(
                "[FightingStrategy:hunt] Stage 1 failed, falling back to human mode",
                OUTPUT_DEBUG,
            )
            return self._generate_human()

        human_policy = analysis["humanPolicy"]

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
            self.game.katrain.log(f"[FightingStrategy:hunt] Error in Stage 2: {a}", OUTPUT_ERROR)

        self.game.katrain.log("[FightingStrategy:hunt] Stage 2: requesting clean analysis", OUTPUT_DEBUG)
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
            self.game.katrain.log(
                f"[FightingStrategy:hunt] Using clean moveInfos ({len(move_infos)} moves)", OUTPUT_DEBUG
            )
        else:
            move_infos = analysis.get("moveInfos", [])
            self.game.katrain.log(
                "[FightingStrategy:hunt] Clean query failed, using biased moveInfos", OUTPUT_DEBUG
            )

        # --- 基本情報 ---
        _ruleset = self.cn.ruleset
        _rules = KataGoEngine.get_rules(_ruleset)
        is_area_scoring = (
            (isinstance(_rules, str) and _rules.lower() in ["chinese", "aga", "tromp-taylor", "new zealand", "stone_scoring"])
            or (isinstance(_rules, dict) and _rules.get("scoring", "").lower() == "area")
        )

        player_sign = 1 if self.cn.next_player == "B" else -1
        current_move = self.cn.depth

        good_moves = set()
        best_gtp_by_score = None
        best_score = None

        if move_infos:
            best_score = max(mi.get("scoreLead", 0) * player_sign for mi in move_infos) / player_sign
            best_gtp_by_score = max(
                move_infos, key=lambda mi: mi.get("scoreLead", 0) * player_sign
            ).get("move", "")

            if best_gtp_by_score == "pass":
                self.game.katrain.log("[FightingStrategy:hunt] Best move is pass, forcing pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "Best move is pass, forcing pass."

            # --- 悪手フィルタ（hunt_max_loss 統一閾値） ---
            self.game.katrain.log(
                f"[FightingStrategy:hunt] Move {current_move}: threshold={hunt_max_loss}, best_score={best_score:.1f}",
                OUTPUT_DEBUG,
            )

            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss <= hunt_max_loss:
                    good_moves.add(gtp_move)

            total_candidates = len([mi for mi in move_infos if mi.get("move", "") != "pass"])
            self.game.katrain.log(
                f"[FightingStrategy:hunt] {len(good_moves)} moves pass score filter out of {total_candidates} "
                f"(threshold={hunt_max_loss})",
                OUTPUT_DEBUG,
            )

            # 段階的緩和
            if not good_moves:
                original_threshold = hunt_max_loss
                for relaxed in [hunt_max_loss * 1.5, hunt_max_loss * 2.0, 9.0]:
                    for mi in move_infos:
                        gtp_move = mi.get("move", "")
                        score = mi.get("scoreLead", 0)
                        loss = player_sign * (best_score - score)
                        if loss <= relaxed:
                            good_moves.add(gtp_move)
                    if good_moves:
                        self.game.katrain.log(
                            f"[FightingStrategy:hunt] Filter relaxed: threshold {original_threshold} -> {relaxed:.1f}, "
                            f"found {len(good_moves)} moves",
                            OUTPUT_DEBUG,
                        )
                        break

            # 最終フォールバック
            if not good_moves and best_gtp_by_score:
                good_moves.add(best_gtp_by_score)
                self.game.katrain.log(
                    f"[FightingStrategy:hunt] Filter failsafe: forcing best-score move {best_gtp_by_score}",
                    OUTPUT_DEBUG,
                )
                if best_gtp_by_score == "pass":
                    return Move(None, player=self.cn.next_player), "Filter failsafe: best move is pass."
                return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                    f"Filter failsafe: no moves within cap, forced {best_gtp_by_score}."
                )

            # --- 安全弁クロスバリデーション用ヘルパー ---
            def _safety_valve_cross_check(forced_gtp, candidate_gtp, p_sign, label="v1"):
                """安全弁の強制手をRegular分析でクロスチェック。安全ならTrue。"""
                _CROSS_CHECK_MAX_LOSS = 2.0
                _reg_moves = self.cn.analysis.get("moves", {})
                _reg_forced = _reg_moves.get(forced_gtp)
                _reg_candidate = _reg_moves.get(candidate_gtp)
                if _reg_forced is None:
                    self.game.katrain.log(
                        f"[FightingStrategy:hunt] Safety {label}: {forced_gtp} not in regular analysis, skipping force",
                        OUTPUT_DEBUG,
                    )
                    return False
                if _reg_candidate is None:
                    return True
                reg_forced_score = _reg_forced.get("scoreLead", 0)
                reg_cand_score = _reg_candidate.get("scoreLead", 0)
                reg_loss = p_sign * (reg_cand_score - reg_forced_score)
                if reg_loss > _CROSS_CHECK_MAX_LOSS:
                    self.game.katrain.log(
                        f"[FightingStrategy:hunt] Safety {label} cross-check FAILED: "
                        f"{forced_gtp} loses {reg_loss:.2f}pt vs {candidate_gtp} in regular analysis",
                        OUTPUT_DEBUG,
                    )
                    return False
                return True

            # 安全弁v1: 最多探索手のlossが閾値以上なら最善スコア手を確定選択
            _SAFETY_LOSS_THRESHOLD = 4.0
            max_visit_mi = max(move_infos, key=lambda mi: mi.get("visits", 0))
            max_visit_gtp = max_visit_mi.get("move", "")
            max_visit_score = max_visit_mi.get("scoreLead", 0)
            max_visit_loss = player_sign * (best_score - max_visit_score)
            if max_visit_loss >= _SAFETY_LOSS_THRESHOLD and best_gtp_by_score and best_gtp_by_score != max_visit_gtp:
                if _safety_valve_cross_check(best_gtp_by_score, max_visit_gtp, player_sign, "v1"):
                    self.game.katrain.log(
                        f"[FightingStrategy:hunt] Safety valve: max-visit move {max_visit_gtp} "
                        f"loss={max_visit_loss:.2f} >= {_SAFETY_LOSS_THRESHOLD}, "
                        f"forcing best-score move {best_gtp_by_score}",
                        OUTPUT_DEBUG,
                    )
                    if best_gtp_by_score == "pass":
                        return Move(None, player=self.cn.next_player), "Safety valve: best move is pass."
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                        f"Safety valve: max-visit {max_visit_gtp} had loss={max_visit_loss:.2f}, "
                        f"forced best-score move {best_gtp_by_score}."
                    )

        # --- ターゲット検出 ---
        targets = find_targets(self.game, self.cn, hunt_min_group_size, hunt_instability_min)
        has_targets = len(targets) > 0

        if has_targets:
            primary_target = targets[0]
            target_instability = primary_target[1]
            target_coords = set(primary_target[2])
            if len(targets) > 1:
                target_coords = target_coords | targets[1][2]
            self.game.katrain.log(
                f"[FightingStrategy:hunt] Phase: Attack (targets={len(targets)}, "
                f"primary: size={len(primary_target[2])}, instability={target_instability:.2f})",
                OUTPUT_DEBUG,
            )
        else:
            self.game.katrain.log("[FightingStrategy:hunt] Phase: No targets, playing as 9-dan", OUTPUT_DEBUG)

        # --- humanPolicy × (proximity × instability | 1.0) で候補構築 ---
        prox_var = hunt_proximity_stddev ** 2
        moves = []
        filtered_count = 0
        has_filter = len(good_moves) > 0

        for x in range(bx):
            for y in range(by):
                idx = (by - y - 1) * bx + x
                if idx < len(human_policy) and human_policy[idx] > 0:
                    m = Move((x, y), player=self.cn.next_player)
                    if has_filter and m.gtp() not in good_moves:
                        filtered_count += 1
                    else:
                        hp_weight = human_policy[idx]
                        if has_targets:
                            min_dist_sq = min((x - tx) ** 2 + (y - ty) ** 2 for tx, ty in target_coords)
                            proximity = math.exp(-0.5 * min_dist_sq / prox_var)
                            combined = hp_weight * proximity * target_instability
                        else:
                            combined = hp_weight
                        moves.append((m, combined))

        # パス候補
        if len(human_policy) > bx * by and human_policy[-1] > 0:
            if not has_filter or "pass" in good_moves:
                moves.append((Move(None, player=self.cn.next_player), human_policy[-1]))

        self.game.katrain.log(
            f"[FightingStrategy:hunt] {len(moves)} candidate moves ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )

        # 安全弁v2: 最高重み候補のlossが閾値以上なら最善スコア手を確定選択
        _SAFETY_LOSS_THRESHOLD = 4.0
        if moves and move_infos and best_gtp_by_score:
            _score_by_gtp_v2 = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
            top_move_v2, _ = max(moves, key=lambda x: x[1])
            top_gtp_v2 = top_move_v2.gtp()
            if top_gtp_v2 in _score_by_gtp_v2 and top_gtp_v2 != best_gtp_by_score:
                top_loss_v2 = player_sign * (best_score - _score_by_gtp_v2[top_gtp_v2])
                self.game.katrain.log(
                    f"[FightingStrategy:hunt] Safety v2: top weighted move {top_gtp_v2} loss={top_loss_v2:.2f}",
                    OUTPUT_DEBUG,
                )
                if top_loss_v2 >= _SAFETY_LOSS_THRESHOLD:
                    if _safety_valve_cross_check(best_gtp_by_score, top_gtp_v2, player_sign, "v2"):
                        self.game.katrain.log(
                            f"[FightingStrategy:hunt] Safety valve v2: top weighted {top_gtp_v2} "
                            f"loss={top_loss_v2:.2f} >= {_SAFETY_LOSS_THRESHOLD}, "
                            f"forcing best-score move {best_gtp_by_score}",
                            OUTPUT_DEBUG,
                        )
                        if best_gtp_by_score == "pass":
                            return Move(None, player=self.cn.next_player), "Safety valve v2: best move is pass."
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                            f"Safety valve v2: top weighted {top_gtp_v2} had loss={top_loss_v2:.2f}, "
                            f"forced best-score move {best_gtp_by_score}."
                        )

        # 全手フィルタ時のフォールバック
        if not moves:
            self.game.katrain.log("[FightingStrategy:hunt] All moves filtered, using best search move", OUTPUT_DEBUG)
            if move_infos:
                best_gtp = best_gtp_by_score if best_gtp_by_score else move_infos[0].get("move", "pass")
                if best_gtp == "pass":
                    return Move(None, player=self.cn.next_player), "All moves filtered, playing best move."
                return Move.from_gtp(best_gtp, player=self.cn.next_player), "All moves filtered, playing best move."
            return Move(None, player=self.cn.next_player), "No valid moves found."

        # パス処理
        if any(m.is_pass for m, _ in moves):
            if is_area_scoring:
                _AREA_PASS_MARGIN = 0.5
                pass_mi = next((mi for mi in (move_infos or []) if mi.get("move") == "pass"), None)
                if pass_mi is not None:
                    pass_score_lead = pass_mi.get("scoreLead", best_score)
                    pass_loss = player_sign * (best_score - pass_score_lead)
                    if pass_loss < _AREA_PASS_MARGIN:
                        self.game.katrain.log(
                            f"[FightingStrategy:hunt] Area scoring: pass within {_AREA_PASS_MARGIN}pt of best "
                            f"(loss={pass_loss:.2f}), forcing pass",
                            OUTPUT_DEBUG,
                        )
                        return Move(None, player=self.cn.next_player), "Area scoring: pass near-optimal, forcing pass."
                moves_without_pass = [(m, w) for m, w in moves if not m.is_pass]
                if moves_without_pass:
                    moves = moves_without_pass
                    self.game.katrain.log(
                        "[FightingStrategy:hunt] Area scoring: pass removed from candidates", OUTPUT_DEBUG
                    )
                else:
                    if best_gtp_by_score and best_gtp_by_score != "pass":
                        return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), \
                            "Area scoring: playing best non-pass move."
                    return Move(None, player=self.cn.next_player), "Area scoring: no non-pass candidates."
            else:
                self.game.katrain.log("[FightingStrategy:hunt] Pass is among candidates, forcing pass", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "Pass is in candidates, forcing pass."

        # エンドゲーム: humanPolicy最上位手（ターゲット重み無視）
        endgame_threshold = math.ceil(bx * by * 0.5)
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
                    f"[FightingStrategy:hunt] Endgame: playing top humanPolicy move {top_move[0].gtp()}",
                    OUTPUT_DEBUG,
                )
                return top_move[0], f"Endgame: played top humanPolicy move {top_move[0].gtp()}."

        # デバッグ: 上位5手表示
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
        top_str = "\n".join([f"#{i+1}: {m.gtp()} weight={w:.4f}" for i, (m, w) in enumerate(top5)])
        self.game.katrain.log(f"[FightingStrategy:hunt] Top 5:\n{top_str}", OUTPUT_DEBUG)

        # タイブレーク
        _TIEBREAK_WEIGHT_RATIO = 1.05
        _TIEBREAK_VISITS_REVERSAL_RATIO = 2.0
        _TIEBREAK_SCORE_DIFF = 2.0
        if len(top5) >= 2 and move_infos:
            _score_by_gtp = {mi.get("move", ""): mi.get("scoreLead", 0) * player_sign for mi in move_infos}
            _visits_by_gtp = {mi.get("move", ""): mi.get("visits", 0) for mi in move_infos}
            top1_move, top1_w = top5[0]
            top2_move, top2_w = top5[1]
            top1_visits = _visits_by_gtp.get(top1_move.gtp(), 0)
            top2_visits = _visits_by_gtp.get(top2_move.gtp(), 0)
            is_policy_close = top2_w > 0 and top1_w / top2_w < _TIEBREAK_WEIGHT_RATIO
            is_visits_reversal = top2_visits > top1_visits * _TIEBREAK_VISITS_REVERSAL_RATIO
            is_mcts_nonprefer = top1_visits > 0 and top2_visits >= top1_visits
            if is_policy_close or is_visits_reversal or is_mcts_nonprefer:
                s1 = _score_by_gtp.get(top1_move.gtp())
                s2 = _score_by_gtp.get(top2_move.gtp())
                if s1 is not None and s2 is not None and abs(s1 - s2) >= _TIEBREAK_SCORE_DIFF:
                    winner = top1_move if s1 > s2 else top2_move
                    loser = top2_move if s1 > s2 else top1_move
                    trigger = "policy" if is_policy_close else ("visits_reversal" if is_visits_reversal else "mcts_nonprefer")
                    self.game.katrain.log(
                        f"[FightingStrategy:hunt] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt, "
                        f"policy_ratio={top1_w/top2_w:.3f}, visits={top1_visits}/{top2_visits})",
                        OUTPUT_DEBUG,
                    )
                    return winner, (
                        f"\n{top_str}\n\nScore tiebreak({trigger}): played {winner.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt). ({filtered_count} filtered)"
                    )

        # 重み付き選択
        selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]
        phase = "Hunt(attack)" if has_targets else "Hunt(9-dan)"
        self.game.katrain.log(f"[FightingStrategy:hunt] Selected: {move.gtp()} ({phase})", OUTPUT_DEBUG)

        ai_thoughts = (
            f"\n{top_str}\n\n{phase}: played {move.gtp()} "
            f"({filtered_count} bad moves filtered)"
        )
        return move, ai_thoughts
```

- [ ] **Step 3: 構文確認**

```bash
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
python -c "from katrain.core.ai import FightingStrategy; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: FightingStrategyにhuntモード（狩猟モード）を実装"
```

---

### Task 6: CLAUDE.md に hunt モードのパラメータテーブルを追加

**Files:**
- Modify: `CLAUDE.md` (力戦派モード テーブルの後に hunt モード セクション追加)

- [ ] **Step 1: `### 力戦派モード（FightingStrategy）` セクションの末尾に hunt モードの説明を追加**

`humanモードの悪手フィルタ閾値は〜` の段落の後（`### AI一致率低減モード` の前）に追加:

```markdown
### 狩猟モード（FightingStrategy hunt）

相手の弱い石群を見つけて集中攻撃する狩猟モード。ターゲットがない序盤は通常の9段として着手し、弱い石群が出現したら集中攻撃に切り替える。攻め切れないと判断したら次のターゲットに移る。9路盤は非対応（humanモードにフォールバック）。

**着手選択**: humanモードと同じ2段階クエリ方式。重み = `humanPolicy × proximity × target_instability`（ターゲットあり時）/ `humanPolicy`（ターゲットなし時）。安全弁・タイブレーク・エンドゲーム処理はhumanモードと同じ。

**ターゲット検出**: `find_targets()`（SiegeStrategyと共有）で毎手再評価。不安定度が閾値以下になった石群は自動的にターゲットから外れる。

| パラメータ | デフォルト(19路) | デフォルト(13路) | 備考 |
|---|---|---|---|
| hunt_max_loss | 6.0 | 4.0 | 攻撃時の許容最大損失（目） |
| hunt_min_group_size | 5 | 4 | ターゲット最小グループサイズ |
| hunt_proximity_stddev | 3.0 | 2.5 | ターゲット近接重みの標準偏差 |
| hunt_instability_min | 0.3 | 0.3 | ターゲット判定の最小不安定度 |
```

- [ ] **Step 2: `fighting_mode` の説明行を更新**

パラメータテーブル内の `fighting_mode` 行:

```markdown
# 変更前:
| fighting_mode | "classic" | "classic" / "scoreloss" / "human" |

# 変更後:
| fighting_mode | "classic" | "classic" / "scoreloss" / "human" / "hunt" |
```

- [ ] **Step 3: 検証方法セクションのGrepパターンにhuntを追加**

フェーズ確認の行:

```markdown
# 変更前:
   - フェーズ確認: `Phase:`（SiegeStrategy）/ `Mode:`（FightingStrategy）

# 変更後:
   - フェーズ確認: `Phase:`（SiegeStrategy / FightingStrategy:hunt）/ `Mode:`（FightingStrategy）
```

- [ ] **Step 4: コミット**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.mdにhuntモード（狩猟モード）のパラメータ情報を追加"
```

---

### Task 7: 手動検証

**前提:** Task 1-6 が全てコミット済みであること。

- [ ] **Step 1: debug_level を有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `1` に変更。

- [ ] **Step 2: 19路盤で hunt モードをテスト**

1. `python -m katrain` で起動
2. AI設定 → 力戦派 → `fighting_mode: hunt` を選択
3. 対局開始（19路盤）
4. 序盤: ターゲットがない状態で通常の9段として着手することを確認
5. 中盤: ターゲット出現後に集中攻撃に切り替わることを確認

- [ ] **Step 3: ログ確認（Grep パターン）**

```bash
# 設定値の確認
grep "FightingStrategy:hunt.*Starting move generation" <logfile>

# ターゲット検出
grep "find_targets.*Primary target" <logfile>

# フェーズ切替
grep "FightingStrategy:hunt.*Phase:" <logfile>

# 着手結果
grep "FightingStrategy:hunt.*Selected:" <logfile>

# 悪手フィルタ
grep "FightingStrategy:hunt.*moves pass score filter" <logfile>
```

- [ ] **Step 4: 9路盤フォールバック確認**

1. 9路盤で対局開始
2. ログに `Hunt mode not supported on 9x9, falling back to human mode` が出ることを確認

- [ ] **Step 5: 13路盤で盤面別デフォルト確認**

1. 13路盤で対局開始
2. ログで `max_loss=4.0, min_group=4, prox_stddev=2.5` が出ることを確認（config.json で 19路デフォルト値 6.0 を設定していても、コード内の 13路デフォルトが適用される）

- [ ] **Step 6: SiegeStrategy の動作確認（リグレッション）**

1. AI設定 → 攻城戦略に切り替えて対局
2. `find_targets` のログが正常に出ることを確認（`_find_targets` → `find_targets` リファクタの回帰テスト）

- [ ] **Step 7: debug_level を戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` → `0` に変更。
