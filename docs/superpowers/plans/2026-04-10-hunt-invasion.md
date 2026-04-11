# HuntStrategy 侵入フェーズ追加 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HuntStrategyに侵入フェーズを追加し、序盤から相手の勢力圏に攻め込む動作を実現する

**Architecture:** ownershipグリッドから相手の勢力圏を侵入対象として抽出し、既存の石グループターゲットと統合ターゲット座標リストにまとめる。proximity重みの計算対象に侵入座標を含めることで、「ターゲットなし→9段フォールバック」を廃止し、常にどこかを攻め続ける

**Tech Stack:** Python 3.12, KataGo ownership API

---

## Task 1: constants.py にパラメータ定義を追加

**Files:**
- Modify: `katrain/core/constants.py:165-168`（AI_OPTION_VALUES）
- Modify: `katrain/core/constants.py:200-203`（AI_OPTION_ORDER）

- [ ] **Step 1: AI_OPTION_VALUES に4パラメータ追加**

`katrain/core/constants.py` の既存hunt行（165-168行）の直後に追加:

```python
    "hunt_max_loss": [x / 2 for x in range(2, 21)],  # 1.0〜10.0（0.5刻み）
    "hunt_min_group_size": list(range(2, 11)),  # 2〜10
    "hunt_proximity_stddev": [x / 2 for x in range(3, 13)],  # 1.5〜6.0（0.5刻み）
    "hunt_instability_min": [x / 10 for x in range(1, 9)],  # 0.1〜0.8（0.1刻み）
    "hunt_invasion_max_loss": [x / 2 for x in range(4, 25)],  # 2.0〜12.0（0.5刻み）
    "hunt_invasion_min": [x / 20 for x in range(2, 11)],  # 0.1〜0.5（0.05刻み）
    "hunt_invasion_max": [x / 20 for x in range(8, 19)],  # 0.4〜0.9（0.05刻み）
    "hunt_invasion_proximity_stddev": [x / 2 for x in range(4, 17)],  # 2.0〜8.0（0.5刻み）
```

つまり既存4行の下に新しい4行を挿入する。既存行は変更しない。

- [ ] **Step 2: AI_OPTION_ORDER に表示順を追加**

既存のhunt行（200-203行）の直後に追加:

```python
    "hunt_max_loss": 0,
    "hunt_min_group_size": 1,
    "hunt_proximity_stddev": 10,
    "hunt_instability_min": 11,
    "hunt_invasion_max_loss": 20,
    "hunt_invasion_min": 21,
    "hunt_invasion_max": 22,
    "hunt_invasion_proximity_stddev": 23,
```

つまり既存4行の下に新しい4行を挿入する。既存行は変更しない。

- [ ] **Step 3: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat: HuntStrategy侵入フェーズ用の4パラメータをconstants.pyに追加"
```

---

## Task 2: config.json にデフォルト値を追加（パッケージ+ローカル）

**Files:**
- Modify: `katrain/config.json:173-178`（ai:hunt セクション）
- Modify: `C:\Users\iwaki\.katrain\config.json:173-178`（ai:hunt セクション）

- [ ] **Step 1: パッケージ config.json に追加**

`katrain/config.json` の ai:hunt セクション（173-178行）を以下に変更:

```json
        "ai:hunt": {
            "hunt_max_loss": 6.0,
            "hunt_min_group_size": 5,
            "hunt_proximity_stddev": 3.0,
            "hunt_instability_min": 0.3,
            "hunt_invasion_max_loss": 8.0,
            "hunt_invasion_min": 0.2,
            "hunt_invasion_max": 0.7,
            "hunt_invasion_proximity_stddev": 5.0
        },
```

既存の `"hunt_instability_min": 0.3` の末尾にカンマを追加し、新しい4行を挿入。

- [ ] **Step 2: ローカル config.json に追加**

`C:\Users\iwaki\.katrain\config.json` の ai:hunt セクション（173-178行）にも全く同じ変更を適用する。

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat: config.jsonにHuntStrategy侵入フェーズのデフォルト値を追加"
```

注: ローカルconfig.jsonはgit管理外なのでgit addしない。

---

## Task 3: ai.py に侵入ロジックを実装

**Files:**
- Modify: `katrain/core/ai.py:3466-3478`（デフォルト値・パラメータ取得）
- Modify: `katrain/core/ai.py:3480-3485`（開始ログ）
- Modify: `katrain/core/ai.py:3602-3651`（悪手フィルタ）
- Modify: `katrain/core/ai.py:3700-3739`（ターゲット検出・重み計算）
- Modify: `katrain/core/ai.py:3872-3882`（着手選択・フェーズ名）

### Step 1: デフォルト値とパラメータ取得を拡張

- [ ] **Step 1a: 盤面サイズ別デフォルト値に侵入パラメータを追加**

`ai.py` 3466-3473行を以下に変更:

```python
        # 盤面サイズ別デフォルト
        if bx <= 13:
            default_max_loss = 4.0
            default_min_group = 4
            default_prox_stddev = 2.5
            default_invasion_max_loss = 6.0
            default_invasion_prox_stddev = 4.0
        else:
            default_max_loss = 6.0
            default_min_group = 5
            default_prox_stddev = 3.0
            default_invasion_max_loss = 8.0
            default_invasion_prox_stddev = 5.0
```

- [ ] **Step 1b: パラメータ取得に4行追加**

3475-3478行の直後に追加:

```python
        hunt_max_loss = self.settings.get("hunt_max_loss", default_max_loss)
        hunt_min_group_size = self.settings.get("hunt_min_group_size", default_min_group)
        hunt_proximity_stddev = self.settings.get("hunt_proximity_stddev", default_prox_stddev)
        hunt_instability_min = self.settings.get("hunt_instability_min", 0.3)
        hunt_invasion_max_loss = self.settings.get("hunt_invasion_max_loss", default_invasion_max_loss)
        hunt_invasion_min = self.settings.get("hunt_invasion_min", 0.2)
        hunt_invasion_max = self.settings.get("hunt_invasion_max", 0.7)
        hunt_invasion_prox_stddev = self.settings.get("hunt_invasion_proximity_stddev", default_invasion_prox_stddev)
```

つまり既存4行はそのまま、その下に4行追加。

- [ ] **Step 1c: 開始ログを更新**

3480-3485行のログを更新して侵入パラメータも含める:

```python
        self.game.katrain.log(
            f"[HuntStrategy] Starting move generation "
            f"(max_loss={hunt_max_loss}, min_group={hunt_min_group_size}, "
            f"prox_stddev={hunt_proximity_stddev}, instability_min={hunt_instability_min}, "
            f"inv_max_loss={hunt_invasion_max_loss}, inv_min={hunt_invasion_min}, "
            f"inv_max={hunt_invasion_max}, inv_prox_stddev={hunt_invasion_prox_stddev})",
            OUTPUT_DEBUG,
        )
```

### Step 2: 悪手フィルタでフェーズ別閾値を使用

- [ ] **Step 2a: 悪手フィルタの閾値をフェーズ別にする**

悪手フィルタの閾値判定部分は、ターゲット検出の**後**に行う必要があるが、現在のコードではフィルタ（3602行）がターゲット検出（3700行）より**前**にある。

このため、悪手フィルタの閾値を後から切り替える方式にする。具体的には:

3602-3606行のログを以下に変更:

```python
            # --- 悪手フィルタ（hunt_max_loss 統一閾値、侵入時はhunt_invasion_max_lossに後で切替） ---
            self.game.katrain.log(
                f"[HuntStrategy] Move {current_move}: threshold={hunt_max_loss}, best_score={best_score:.1f}",
                OUTPUT_DEBUG,
            )
```

ここでは既存の `hunt_max_loss` でフィルタを実行する（変更なし）。侵入フェーズの場合は、ターゲット検出後に `good_moves` を再計算する。これは Step 3 で実装。

### Step 3: ターゲット検出と侵入ロジックを実装

- [ ] **Step 3a: ターゲット検出部分を拡張して侵入対象を追加**

3700-3739行を以下のコードに**全置換**する:

```python
        # --- ターゲット検出 ---
        targets = find_targets(self.game, self.cn, hunt_min_group_size, hunt_instability_min)
        has_group_targets = len(targets) > 0

        # --- 侵入対象の検出（ownershipベース） ---
        # player_sign は 3585行で定義済み (1=Black, -1=White)
        invasion_coords = set()
        opp_strength_map = {}
        ownership = self.cn.ownership
        if ownership:
            ownership_grid = var_to_grid(ownership, board_size)
            for ix in range(bx):
                for iy in range(by):
                    own_val = ownership_grid[iy][ix] * player_sign
                    opp_strength = max(0.0, -own_val)
                    if hunt_invasion_min <= opp_strength <= hunt_invasion_max:
                        invasion_coords.add((ix, iy))
                        opp_strength_map[(ix, iy)] = opp_strength

        has_invasion = len(invasion_coords) > 0

        # グループターゲット座標の構築
        group_coords = set()
        target_instability = 0.0
        if has_group_targets:
            primary_target = targets[0]
            target_instability = primary_target[1]
            group_coords = set(primary_target[2])
            if len(targets) > 1:
                group_coords = group_coords | targets[1][2]

        # 統合ターゲット
        all_target_coords = invasion_coords | group_coords
        has_targets = len(all_target_coords) > 0

        # フェーズ判定とログ
        if has_group_targets:
            phase_name = "Hunt"
            self.game.katrain.log(
                f"[HuntStrategy] Phase: Hunt (invasion_targets={len(invasion_coords)}, "
                f"group_targets={len(targets)}, primary: size={len(targets[0][2])}, "
                f"instability={target_instability:.2f})",
                OUTPUT_DEBUG,
            )
        elif has_invasion:
            phase_name = "Invade"
            self.game.katrain.log(
                f"[HuntStrategy] Phase: Invade (invasion_targets={len(invasion_coords)}, "
                f"no group targets)",
                OUTPUT_DEBUG,
            )
        else:
            phase_name = "Hunt(9-dan)"
            self.game.katrain.log(
                "[HuntStrategy] Phase: No targets and no invasion, playing as 9-dan",
                OUTPUT_DEBUG,
            )

        # --- 侵入フェーズ時は悪手フィルタを再計算 ---
        if not has_group_targets and has_invasion and hunt_invasion_max_loss != hunt_max_loss:
            good_moves = set()
            for mi in move_infos:
                gtp_move = mi.get("move", "")
                score = mi.get("scoreLead", 0)
                loss = player_sign * (best_score - score)
                if loss <= hunt_invasion_max_loss:
                    good_moves.add(gtp_move)
            total_candidates = len([mi for mi in move_infos if mi.get("move", "") != "pass"])
            self.game.katrain.log(
                f"[HuntStrategy] Invasion filter: {len(good_moves)} moves pass score filter "
                f"out of {total_candidates} (threshold={hunt_invasion_max_loss})",
                OUTPUT_DEBUG,
            )
            # 段階的緩和
            if not good_moves:
                for relaxed in [hunt_invasion_max_loss * 1.5, hunt_invasion_max_loss * 2.0, 9.0]:
                    for mi in move_infos:
                        gtp_move = mi.get("move", "")
                        score = mi.get("scoreLead", 0)
                        loss = player_sign * (best_score - score)
                        if loss <= relaxed:
                            good_moves.add(gtp_move)
                    if good_moves:
                        self.game.katrain.log(
                            f"[HuntStrategy] Invasion filter relaxed: "
                            f"threshold {hunt_invasion_max_loss} -> {relaxed:.1f}, "
                            f"found {len(good_moves)} moves",
                            OUTPUT_DEBUG,
                        )
                        break
            # 最終フォールバック
            if not good_moves and best_gtp_by_score:
                good_moves.add(best_gtp_by_score)

        # --- humanPolicy × proximity × intensity で候補構築 ---
        prox_var = hunt_proximity_stddev ** 2
        inv_prox_var = hunt_invasion_prox_stddev ** 2
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
                            # 最近接ターゲット座標を探し、由来で stddev を切替
                            min_dist_sq = float("inf")
                            nearest_type = None
                            for tx, ty in all_target_coords:
                                dist_sq = (x - tx) ** 2 + (y - ty) ** 2
                                if dist_sq < min_dist_sq:
                                    min_dist_sq = dist_sq
                                    nearest_coord = (tx, ty)
                                    nearest_type = "group" if (tx, ty) in group_coords else "invasion"

                            if nearest_type == "group":
                                proximity = math.exp(-0.5 * min_dist_sq / prox_var)
                                intensity = target_instability
                            else:
                                proximity = math.exp(-0.5 * min_dist_sq / inv_prox_var)
                                intensity = opp_strength_map.get(nearest_coord, 0.3)

                            combined = hp_weight * proximity * intensity
                        else:
                            combined = hp_weight
                        moves.append((m, combined))
```

### Step 4: フェーズ名を更新

- [ ] **Step 4a: 着手選択のフェーズ名を更新**

3872-3882行を以下に変更:

```python
        # 重み付き選択
        selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]
        self.game.katrain.log(f"[HuntStrategy] Selected: {move.gtp()} ({phase_name})", OUTPUT_DEBUG)

        ai_thoughts = (
            f"\n{top_str}\n\n{phase_name}: played {move.gtp()} "
            f"({filtered_count} bad moves filtered)"
        )
        return move, ai_thoughts
```

`has_targets` による旧フェーズ名判定を `phase_name` 変数に置換。

- [ ] **Step 5: var_to_grid のインポートを確認**

`var_to_grid` は既に `find_targets()` 関数内（76行）で使われているため、インポート済み。追加不要。

Run: `python -c "from katrain.core.ai import HuntStrategy; print('import OK')"`
Expected: `import OK`

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntStrategyに侵入フェーズ（Invade）を実装 — ownershipベースの勢力圏侵入"
```

---

## Task 4: i18n 翻訳を更新

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:959-971`
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:1061-1069`

- [ ] **Step 1: 英語翻訳を更新**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の aihelp:hunt エントリ（959-971行）を以下に変更:

```po
msgid "aihelp:hunt"
msgstr ""
"Hunt Strategy: Aggressively invades opponent territory and attacks weak groups. "
"In early game, targets opponent's influence zones based on ownership. "
"When weak groups appear, combines invasion with group attacks. 9x9 not supported.\n"
"\n"
"hunt_max_loss: Max points loss allowed when attacking a target group. "
"Higher = riskier attacks, lower = safer attacks.\n"
"hunt_min_group_size: Minimum stones in an opponent group to be targeted. "
"Lower = target smaller groups too, higher = only go after big groups.\n"
"hunt_proximity_stddev: How tightly focused attacks are on the target group. "
"Lower = concentrate near target, higher = spread attacks wider.\n"
"hunt_instability_min: Minimum instability to consider a group as target. "
"Lower = target more stable groups too, higher = only target very unstable groups.\n"
"hunt_invasion_max_loss: Max points loss allowed when invading opponent territory. "
"Higher = more aggressive invasions, lower = safer invasions.\n"
"hunt_invasion_min: Minimum opponent ownership strength to consider as invasion target. "
"Lower = invade weaker zones too, higher = only invade strong zones.\n"
"hunt_invasion_max: Maximum opponent ownership strength to invade. "
"Higher = invade near-settled territory, lower = only invade unsettled zones.\n"
"hunt_invasion_proximity_stddev: How widely spread invasion moves are. "
"Lower = concentrate invasion, higher = spread across opponent territory."
```

- [ ] **Step 2: 日本語翻訳を更新**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の aihelp:hunt エントリ（1061-1069行）を以下に変更:

```po
msgid "aihelp:hunt"
msgstr ""
"狩猟戦略: 相手の勢力圏に積極的に侵入し、弱い石群を集中攻撃する攻撃型モード。"
"序盤はownershipに基づいて相手の勢力圏を侵入対象にする。"
"弱い石群が出現したら侵入と石群攻撃を併用する。9路盤は非対応。\n"
"\n"
"hunt_max_loss: 石群攻撃時に許容する最大損失（目数）。大きい＝リスクの高い攻め、小さい＝安全な攻め。\n"
"hunt_min_group_size: ターゲットとする最小グループサイズ。小さい＝小さい石群も狙う、大きい＝大石だけ狙う。\n"
"hunt_proximity_stddev: 石群攻撃の集中度。小さい＝ターゲット付近に集中、大きい＝広く攻める。\n"
"hunt_instability_min: ターゲット判定の最小不安定度。小さい＝安定した石群も狙う、大きい＝非常に不安定な石群だけ狙う。\n"
"hunt_invasion_max_loss: 侵入時に許容する最大損失（目数）。大きい＝積極的に侵入、小さい＝慎重に侵入。\n"
"hunt_invasion_min: 侵入対象とする相手ownership強度の下限。小さい＝弱い勢力圏も侵入、大きい＝強い勢力圏だけ侵入。\n"
"hunt_invasion_max: 侵入対象とする相手ownership強度の上限。大きい＝確定地近くも侵入、小さい＝未確定地だけ侵入。\n"
"hunt_invasion_proximity_stddev: 侵入手の分散度。小さい＝侵入先に集中、大きい＝広く分散して侵入。"
```

- [ ] **Step 3: .mo ファイルをコンパイル**

Run: `python tools/compile_mo.py`
Expected: コンパイル成功メッセージ

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/
git commit -m "feat: HuntStrategy侵入フェーズのi18n翻訳を追加（英語・日本語）"
```

---

## Task 5: ai-parameters.md を更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md:50-63`

- [ ] **Step 1: HuntStrategy セクションを更新**

`.claude/rules/ai-parameters.md` の50-63行（狩猟戦略セクション）を以下に変更:

```markdown
## 狩猟戦略（HuntStrategy）

独立した戦略（`ai:hunt`）。序盤から相手の勢力圏に積極的に侵入し、弱い石群を集中攻撃する攻撃型モード。ownershipベースの侵入対象と石グループターゲットを統合して常に攻め続ける。対応盤面: 19路・13路（9路は非対応）。

**着手選択**: 2段階クエリ方式（humanSL 9段固定）。重み = `humanPolicy × proximity × intensity`（侵入/攻撃時）/ `humanPolicy`（対象なし時）。proximity のstddevは侵入対象と石グループで別パラメータ。intensityは侵入対象ならopp_strength、石グループならinstability。安全弁・タイブレーク・エンドゲーム処理あり。

**フェーズ**: Invade（侵入対象のみ）→ Hunt（侵入+石グループ）→ Endgame。石グループターゲットの有無で自動切替。

**ターゲット検出**: 石グループは `find_targets()`（SiegeStrategyと共有）で毎手再評価。侵入対象はownershipグリッドから毎手抽出（`hunt_invasion_min` 〜 `hunt_invasion_max` の範囲）。

| パラメータ | デフォルト(19路) | デフォルト(13路) | 備考 |
|---|---|---|---|
| hunt_max_loss | 6.0 | 4.0 | 石群攻撃時の許容最大損失（目） |
| hunt_min_group_size | 5 | 4 | ターゲット最小グループサイズ |
| hunt_proximity_stddev | 3.0 | 2.5 | 石群攻撃の近接重みの標準偏差 |
| hunt_instability_min | 0.3 | 0.3 | ターゲット判定の最小不安定度 |
| hunt_invasion_max_loss | 8.0 | 6.0 | 侵入時の許容最大損失（目） |
| hunt_invasion_min | 0.2 | 0.2 | 侵入対象ownership強度の下限 |
| hunt_invasion_max | 0.7 | 0.7 | 侵入対象ownership強度の上限 |
| hunt_invasion_proximity_stddev | 5.0 | 4.0 | 侵入用の近接重みの標準偏差 |
```

- [ ] **Step 2: コミット**

```bash
git add .claude/rules/ai-parameters.md
git commit -m "docs: ai-parameters.mdのHuntStrategyセクションを侵入フェーズ対応に更新"
```

---

## Task 6: 動作確認

- [ ] **Step 1: debug_level を 1 に変更**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` を `"debug_level": 1` に変更。

- [ ] **Step 2: KaTrain を起動して対局**

Run: `python -m katrain`

対局を開始し、以下を確認:
1. 序盤で `Phase: Invade (invasion_targets=XX, no group targets)` のログが出ること
2. 着手が相手の勢力圏付近に集中すること
3. 石グループが弱くなったら `Phase: Hunt` に変わること
4. Safety Valve が発動して大損が回避されていること
5. 新パラメータがGUIに表示され、変更できること

- [ ] **Step 3: debug_level を 0 に戻す**

確認後、`"debug_level": 1` を `"debug_level": 0` に戻す。
