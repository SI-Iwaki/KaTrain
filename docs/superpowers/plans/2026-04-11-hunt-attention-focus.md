# Hunt戦略 注意フォーカス機能 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HuntStrategyに「注意フォーカス」Gaussianペナルティを追加し、戦闘エリアから遠い手の選択を抑制して人間らしい注意集中を実現する。

**Architecture:** 既存の候補手重み計算 `combined = hp_weight × proximity × intensity × territory_avoid` に `focus_penalty` を乗算する追加レイヤー。フォーカス中心は直前着手位置と最も不安定なターゲット重心の平均。`hunt_focus_stddev` パラメータでGUIから強弱調整可能。

**Tech Stack:** Python 3.12, Kivy GUI, KataGo, gettext i18n

**設計書:** `docs/superpowers/specs/2026-04-11-hunt-attention-focus-design.md`

---

### Task 1: constants.py に hunt_focus_stddev パラメータを追加

**Files:**
- Modify: `katrain/core/constants.py:168-178` (AI_OPTION_VALUES)
- Modify: `katrain/core/constants.py:210-220` (AI_OPTION_ORDER)

- [ ] **Step 1: AI_OPTION_VALUES に hunt_focus_stddev を追加**

`katrain/core/constants.py` の176行目（`hunt_invasion_temperature` の直後）に追加:

```python
    "hunt_focus_stddev": [x / 2 for x in range(6, 21)],  # 3.0〜10.0（0.5刻み）
```

- [ ] **Step 2: AI_OPTION_ORDER に hunt_focus_stddev を追加**

`katrain/core/constants.py` の218行目（`hunt_invasion_temperature` の直後）に追加:

```python
    "hunt_focus_stddev": 25,
```

- [ ] **Step 3: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat: constants.pyにhunt_focus_stddevパラメータを追加"
```

---

### Task 2: config.json にデフォルト値を追加

**Files:**
- Modify: `katrain/config.json:173-183` (ai:hunt セクション)
- Modify: `C:\Users\iwaki\.katrain\config.json` (ユーザー設定の ai:hunt セクション)

- [ ] **Step 1: パッケージ config.json の ai:hunt セクションに追加**

`katrain/config.json` の182行目（`"hunt_invasion_temperature": 1.5` の直後、閉じ括弧の前）に追加:

```json
            "hunt_focus_stddev": 7.0
```

既存の `"hunt_invasion_temperature": 1.5` の行末にカンマを追加すること。

- [ ] **Step 2: ユーザー config.json の ai:hunt セクションに追加**

`C:\Users\iwaki\.katrain\config.json` の `"ai:hunt"` セクション内、`"hunt_invasion_temperature"` の直後に追加:

```json
            "hunt_focus_stddev": 7.0
```

既存の `"hunt_invasion_temperature"` の行末にカンマを追加すること。

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat: config.jsonにhunt_focus_stddevのデフォルト値を追加（19路:7.0）"
```

---

### Task 3: i18n 翻訳を追加

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:981-982`
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:1074-1075`

- [ ] **Step 1: 英語翻訳を追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の `aihelp:hunt` エントリ末尾（982行目）を変更。現在の末尾:

```
"hunt_invasion_temperature: Selection temperature for invasion moves. "
"Higher = more variety in move selection while staying near invasion targets. 1.0 = no change."
```

これを以下に変更:

```
"hunt_invasion_temperature: Selection temperature for invasion moves. "
"Higher = more variety in move selection while staying near invasion targets. 1.0 = no change.\n"
"hunt_focus_stddev: Attention focus radius. Controls how strongly moves are focused "
"near the current action area (last move + most unstable target). "
"Lower = tighter focus on current fight, higher = allow moves across wider area."
```

- [ ] **Step 2: 日本語翻訳を追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `aihelp:hunt` エントリ末尾（1075行目）を変更。現在の末尾:

```
"hunt_invasion_temperature: 侵入手の選択温度。大きい＝侵入先付近の手からより多様に選択。1.0＝変更なし。"
```

これを以下に変更:

```
"hunt_invasion_temperature: 侵入手の選択温度。大きい＝侵入先付近の手からより多様に選択。1.0＝変更なし。\n"
"hunt_focus_stddev: 注意フォーカス半径。直前の着手と最も不安定なターゲット付近に注意を集中する度合いを制御。"
"小さい＝現在の戦いに集中、大きい＝広い範囲の手を許容。"
```

- [ ] **Step 3: .mo ファイルをコンパイル**

```bash
python tools/compile_mo.py
```

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/
git commit -m "feat: hunt_focus_stddevのi18n翻訳を追加（英語・日本語）"
```

---

### Task 4: ai.py にフォーカス計算とペナルティ適用を実装

**Files:**
- Modify: `katrain/core/ai.py:3536-3557` (パラメータ読み取り)
- Modify: `katrain/core/ai.py:3559-3566` (ログ出力)
- Modify: `katrain/core/ai.py:3815-3830` (フォーカス中心算出 — ターゲット構築直後)
- Modify: `katrain/core/ai.py:3920-3923` (ペナルティ適用 — combined計算直後)

- [ ] **Step 1: パラメータ読み取りを追加**

`katrain/core/ai.py` の3557行目（`hunt_invasion_temperature` の読み取り直後）に追加:

```python
        hunt_focus_stddev = self.settings.get("hunt_focus_stddev", default_focus_stddev)
```

デフォルト値の定義を3536行付近の盤面サイズ別デフォルトブロックに追加:

```python
        if bx <= 13:
            default_max_loss = 4.0
            default_min_group = 4
            default_prox_stddev = 2.5
            default_invasion_max_loss = 6.0
            default_invasion_prox_stddev = 3.0
            default_focus_stddev = 5.0   # ← 追加
        else:
            default_max_loss = 6.0
            default_min_group = 5
            default_prox_stddev = 3.0
            default_invasion_max_loss = 8.0
            default_invasion_prox_stddev = 3.0
            default_focus_stddev = 7.0   # ← 追加
```

- [ ] **Step 2: 初期化ログに hunt_focus_stddev を追加**

`katrain/core/ai.py` の3559-3566行のログ出力に `focus_stddev={hunt_focus_stddev}` を追加:

```python
        self.game.katrain.log(
            f"[HuntStrategy] Starting move generation "
            f"(max_loss={hunt_max_loss}, min_group={hunt_min_group_size}, "
            f"prox_stddev={hunt_proximity_stddev}, instability_min={hunt_instability_min}, "
            f"inv_max_loss={hunt_invasion_max_loss}, inv_min={hunt_invasion_min}, "
            f"inv_max={hunt_invasion_max}, inv_prox_stddev={hunt_invasion_prox_stddev}, "
            f"inv_temperature={hunt_invasion_temperature}, focus_stddev={hunt_focus_stddev})",
            OUTPUT_DEBUG,
        )
```

- [ ] **Step 3: フォーカス中心の算出を実装**

`katrain/core/ai.py` の `has_targets = len(all_target_coords) > 0`（3815行）の直後、フェーズ判定ブロック（3817行）の前に、フォーカス中心算出コードを挿入:

```python
        # --- 注意フォーカス中心の算出 ---
        focus_center = None
        _FOCUS_FLOOR = 0.05
        focus_var = hunt_focus_stddev ** 2

        if has_targets and hunt_focus_stddev > 0:
            # (1) 直前着手の座標を取得
            last_move_coords = None
            if self.cn.move and self.cn.move.coords:
                last_move_coords = self.cn.move.coords  # (x, y)

            # (2) 最も不安定なターゲットの重心を取得
            unstable_center = None
            if has_group_targets:
                # group_targetsの中で最大instabilityのグループの重心
                primary_coords = targets[0][2]  # set of (x, y)
                if primary_coords:
                    uc_x = sum(c[0] for c in primary_coords) / len(primary_coords)
                    uc_y = sum(c[1] for c in primary_coords) / len(primary_coords)
                    unstable_center = (uc_x, uc_y)
            else:
                # Invadeフェーズ: opp_strength_mapで最大強度の侵入座標
                if opp_strength_map:
                    max_coord = max(opp_strength_map, key=opp_strength_map.get)
                    unstable_center = (float(max_coord[0]), float(max_coord[1]))

            # (3) フォーカス中心の合成
            if last_move_coords and unstable_center:
                focus_center = (
                    0.5 * last_move_coords[0] + 0.5 * unstable_center[0],
                    0.5 * last_move_coords[1] + 0.5 * unstable_center[1],
                )
                focus_source = (
                    f"last_move({Move(last_move_coords, player=self.cn.next_player).gtp()})"
                    f"+unstable({'group' if has_group_targets else 'invasion'}"
                    f"({unstable_center[0]:.0f},{unstable_center[1]:.0f}))"
                )
            elif unstable_center:
                focus_center = unstable_center
                focus_source = (
                    f"unstable_only({'group' if has_group_targets else 'invasion'}"
                    f"({unstable_center[0]:.0f},{unstable_center[1]:.0f}))"
                )
            # last_move_coordsだけでunstable_centerがない場合はフォーカスなし

            if focus_center:
                self.game.katrain.log(
                    f"[HuntStrategy] Focus: center=({focus_center[0]:.1f}, {focus_center[1]:.1f}) "
                    f"stddev={hunt_focus_stddev} source={focus_source}",
                    OUTPUT_DEBUG,
                )
```

- [ ] **Step 4: フォーカスペナルティを候補手重みに適用**

`katrain/core/ai.py` の3920行（`combined = hp_weight * proximity * intensity * territory_avoid`）と3923行（`moves.append((m, combined))`）の間にフォーカスペナルティを挿入。

変更前（3920-3923行）:

```python
                            combined = hp_weight * proximity * intensity * territory_avoid
                        else:
                            combined = hp_weight * territory_avoid
                        moves.append((m, combined))
```

変更後:

```python
                            combined = hp_weight * proximity * intensity * territory_avoid
                        else:
                            combined = hp_weight * territory_avoid

                        # 注意フォーカスペナルティ
                        if focus_center:
                            focus_dist_sq = (x - focus_center[0]) ** 2 + (y - focus_center[1]) ** 2
                            focus_penalty = max(_FOCUS_FLOOR, math.exp(-0.5 * focus_dist_sq / focus_var))
                            combined *= focus_penalty

                        moves.append((m, combined))
```

- [ ] **Step 5: 動作確認**

```bash
python -m pytest tests/ -x -q
```

Expected: 既存テストが全てパスする（新パラメータはデフォルト値で動作するため破壊的変更なし）。

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntStrategyに注意フォーカスGaussianペナルティを実装"
```

---

### Task 5: ai-parameters.md を更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`

- [ ] **Step 1: HuntStrategyパラメータテーブルに追加**

`.claude/rules/ai-parameters.md` の `## 狩猟戦略（HuntStrategy）` セクション内のパラメータテーブルに行を追加。`hunt_invasion_temperature` の直後に:

```markdown
| hunt_focus_stddev | 7.0 | 5.0 | 注意フォーカスの広がり（Gaussian標準偏差）。直前手と最も不安定なターゲットの重心を中心に、遠い手をペナルティする。小さい＝集中、大きい＝緩やか。floor=0.05 |
```

- [ ] **Step 2: コミット**

```bash
git add .claude/rules/ai-parameters.md
git commit -m "docs: ai-parameters.mdにhunt_focus_stddevを追加"
```

---

### Task 6: 手動検証

- [ ] **Step 1: debug_level を 1 に設定**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` を `"debug_level": 1` に変更。

- [ ] **Step 2: KaTrain を起動して対局**

```bash
python -m katrain
```

AI設定で「狩猟戦略」を選択し、hunt_focus_stddev=7.0, hunt_invasion_temperature=2.0 で対局を実施。

- [ ] **Step 3: ログで以下を確認**

1. `Focus: center=` ログが毎手出力されていること
2. `source=` に last_move と unstable の情報が正しく表示されていること
3. Invadeフェーズで盤の反対側への飛びが改善前と比べて減少していること
4. Safety valve 発動回数が改善前（10回/局）より減少していること
5. 近くの手のバリエーション（棋風の多様性）が維持されていること

確認パターン:
```
grep "Focus: center=" game_YYYYMMDD_HHMMSS.log
grep "Safety valve" game_YYYYMMDD_HHMMSS.log | wc -l
```

- [ ] **Step 4: debug_level を 0 に戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` を `"debug_level": 0` に変更。
