# HuntStrategy Invadeフェーズ 第一感ぶれ実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HuntStrategyのInvadeフェーズに適用確率付き第一感ぶれを導入し、最善手一致率を50%超→30-40%に低減する（強さ維持）

**Architecture:** Invadeフェーズの重み付き選択の前に、確率的に第一感ぶれ（上位3候補からloss 0.5-2.0の最小loss手を確定選択）を割り込ませる。適用率は `hunt_invasion_deviation_rate`（0.5/0.7/0.9、デフォルト0.7）でGUIから調整可能。

**Tech Stack:** Python 3.12, KaTrain/Kivy, KataGo

**設計ドキュメント:** `docs/superpowers/specs/2026-04-10-hunt-invade-deviation-design.md`

---

### Task 1: constants.py — GUI設定追加

**Files:**
- Modify: `katrain/core/constants.py:165-172` (AI_OPTION_VALUES) 
- Modify: `katrain/core/constants.py:204-211` (AI_OPTION_ORDER)

- [ ] **Step 1: AI_OPTION_VALUES にパラメータ追加**

`katrain/core/constants.py` の `AI_OPTION_VALUES` dict 末尾（`hunt_invasion_proximity_stddev` の次）に追加:

```python
    "hunt_invasion_deviation_rate": [0.5, 0.7, 0.9],  # 侵入時の第一感ぶれ適用率
```

- [ ] **Step 2: AI_OPTION_ORDER にパラメータ追加**

`AI_OPTION_ORDER` dict 内の `hunt_invasion_proximity_stddev` の次に追加:

```python
    "hunt_invasion_deviation_rate": 24,
```

- [ ] **Step 3: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat: HuntStrategy侵入フェーズの第一感ぶれ適用率をGUI設定に追加"
```

---

### Task 2: config.json — デフォルト値追加（2箇所）

**Files:**
- Modify: `katrain/config.json` (パッケージ同梱)
- Modify: `C:\Users\iwaki\.katrain\config.json` (ユーザーローカル)

- [ ] **Step 1: パッケージconfig.jsonに追加**

`katrain/config.json` の `"ai:hunt"` セクション内、`"hunt_invasion_proximity_stddev": 3.0` の次に追加:

```json
            "hunt_invasion_deviation_rate": 0.7
```

変更前:
```json
            "hunt_invasion_proximity_stddev": 3.0
        },
```

変更後:
```json
            "hunt_invasion_proximity_stddev": 3.0,
            "hunt_invasion_deviation_rate": 0.7
        },
```

- [ ] **Step 2: ユーザーローカルconfig.jsonに追加**

`C:\Users\iwaki\.katrain\config.json` の `"ai:hunt"` セクションに同じキーを追加:

```json
            "hunt_invasion_deviation_rate": 0.7
```

変更前:
```json
            "hunt_invasion_proximity_stddev": 3.0
        },
```

変更後:
```json
            "hunt_invasion_proximity_stddev": 3.0,
            "hunt_invasion_deviation_rate": 0.7
        },
```

**重要:** ユーザーローカルにも追加しないとGUIにスライダーが表示されない。

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat: hunt_invasion_deviation_rateのデフォルト値を追加（パッケージ+ローカル）"
```

Note: ユーザーローカル `config.json` はgit管理外のためgit addしない。

---

### Task 3: ai.py — 第一感ぶれロジック実装

**Files:**
- Modify: `katrain/core/ai.py:3479-3486` (パラメータ読み取り)
- Modify: `katrain/core/ai.py:3488-3494` (初期化ログ)
- Modify: `katrain/core/ai.py:3983-3993` (重み付き選択の直前に挿入)

- [ ] **Step 1: パラメータ読み取りを追加**

`ai.py:3486` の `hunt_invasion_prox_stddev` の下に追加:

```python
        hunt_invasion_deviation_rate = self.settings.get("hunt_invasion_deviation_rate", 0.7)
```

- [ ] **Step 2: 初期化ログにパラメータを追加**

`ai.py:3488-3494` のログ出力を更新して `hunt_invasion_deviation_rate` を含める。

現在:
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

変更後:
```python
        self.game.katrain.log(
            f"[HuntStrategy] Starting move generation "
            f"(max_loss={hunt_max_loss}, min_group={hunt_min_group_size}, "
            f"prox_stddev={hunt_proximity_stddev}, instability_min={hunt_instability_min}, "
            f"inv_max_loss={hunt_invasion_max_loss}, inv_min={hunt_invasion_min}, "
            f"inv_max={hunt_invasion_max}, inv_prox_stddev={hunt_invasion_prox_stddev}, "
            f"inv_deviation_rate={hunt_invasion_deviation_rate})",
            OUTPUT_DEBUG,
        )
```

- [ ] **Step 3: 第一感ぶれロジック挿入**

`ai.py` のタイブレーク処理（`ai.py:3982`付近 — tiebreak return の閉じ括弧）の後、
重み付き選択（`weighted_selection_without_replacement`）の前に以下を挿入:

```python
        # --- Invadeフェーズ: 第一感ぶれ ---
        if phase_name == "Invade" and len(top5) >= 2 and move_infos and best_score is not None:
            if random.random() < hunt_invasion_deviation_rate:
                _score_by_gtp_dev = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
                _DEV_LOSS_MIN = 0.5
                _DEV_LOSS_MAX = 2.0
                dev_candidates = []
                for m, w in top5[:3]:
                    gtp = m.gtp()
                    if gtp in _score_by_gtp_dev:
                        loss = player_sign * (best_score - _score_by_gtp_dev[gtp])
                        if _DEV_LOSS_MIN <= loss < _DEV_LOSS_MAX:
                            dev_candidates.append((m, loss))
                if dev_candidates:
                    dev_move, dev_loss = min(dev_candidates, key=lambda x: x[1])
                    self.game.katrain.log(
                        f"[HuntStrategy] Invade deviation: {dev_move.gtp()} "
                        f"(loss={dev_loss:.2f}, rate={hunt_invasion_deviation_rate})",
                        OUTPUT_DEBUG,
                    )
                    return dev_move, (
                        f"\n{top_str}\n\nInvade deviation: played {dev_move.gtp()} "
                        f"(loss={dev_loss:.2f}). ({filtered_count} bad moves filtered)"
                    )
                else:
                    self.game.katrain.log(
                        "[HuntStrategy] Invade deviation: no candidates in 0.5-2.0 range, "
                        "falling back to weighted selection",
                        OUTPUT_DEBUG,
                    )
```

- [ ] **Step 4: 動作確認**

```bash
python -c "import katrain.core.ai; print('import OK')"
```

Expected: `import OK`（構文エラーがないことを確認）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntStrategy侵入フェーズに第一感ぶれロジックを実装"
```

---

### Task 4: i18n — 翻訳追加 + .mo コンパイル

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:979-980`
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:1074`

- [ ] **Step 1: 英語ヘルプテキストに追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の `aihelp:hunt` msgstr 内、
`hunt_invasion_proximity_stddev` の説明の末尾（980行目 `"Lower = concentrate invasion, higher = spread across opponent territory."` の後）に追加:

変更前:
```
"hunt_invasion_proximity_stddev: How widely spread invasion moves are. "
"Lower = concentrate invasion, higher = spread across opponent territory."
```

変更後:
```
"hunt_invasion_proximity_stddev: How widely spread invasion moves are. "
"Lower = concentrate invasion, higher = spread across opponent territory.\n"
"hunt_invasion_deviation_rate: Probability of applying first-impression deviation during invasion. "
"Reduces AI top-move agreement rate while maintaining strength. Higher = more deviation."
```

- [ ] **Step 2: 日本語ヘルプテキストに追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `aihelp:hunt` msgstr 内、
`hunt_invasion_proximity_stddev` の説明の末尾（1074行目）に追加:

変更前:
```
"hunt_invasion_proximity_stddev: 侵入手の分散度。小さい＝侵入先に集中、大きい＝広く分散して侵入。"
```

変更後:
```
"hunt_invasion_proximity_stddev: 侵入手の分散度。小さい＝侵入先に集中、大きい＝広く分散して侵入。\n"
"hunt_invasion_deviation_rate: 侵入時の第一感ぶれ適用率。最善手一致率を下げつつ強さを維持する。大きい＝ぶれやすい。"
```

- [ ] **Step 3: .mo コンパイル**

```bash
python tools/compile_mo.py
```

Expected: コンパイル完了メッセージ（エラーなし）

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/
git commit -m "feat: hunt_invasion_deviation_rateのi18n翻訳を追加（英語・日本語）"
```

---

### Task 5: ai-parameters.md — パラメータテーブル更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`

- [ ] **Step 1: HuntStrategyパラメータテーブルに行追加**

`.claude/rules/ai-parameters.md` のHuntStrategyテーブル末尾（`hunt_invasion_proximity_stddev` の行の後）に追加:

```markdown
| hunt_invasion_deviation_rate | 0.7 | 0.7 | 侵入フェーズの第一感ぶれ適用率（0.5/0.7/0.9） |
```

- [ ] **Step 2: コミット**

```bash
git add .claude/rules/ai-parameters.md
git commit -m "docs: ai-parameters.mdにhunt_invasion_deviation_rateを追加"
```

---

### Task 6: 手動テスト（対局による検証）

- [ ] **Step 1: デバッグレベルを有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `"debug_level": 1` に変更

- [ ] **Step 2: KaTrainを起動して対局**

```bash
python -m katrain
```

HuntStrategy（狩猟戦略）で19路盤の対局を開始し、20手以上打つ。

- [ ] **Step 3: ログで第一感ぶれの発動を確認**

ログファイルを以下のパターンで検索:

```
Grep: "Invade deviation:"  → 第一感ぶれが発動した手
Grep: "no candidates in 0.5-2.0"  → 適用試行したが候補なし
Grep: "inv_deviation_rate="  → 設定値の読み込み確認
```

確認ポイント:
- Invade手のうち約70%で第一感ぶれが試行されている
- dev_loss値が0.5〜2.0の範囲内である
- Huntフェーズの手には第一感ぶれが適用されていない
- エンドゲーム・安全弁・タイブレークは従来通り動作

- [ ] **Step 4: GUI設定の確認**

AI設定画面でHuntStrategyを選択し:
- `hunt_invasion_deviation_rate` のスライダーが表示される
- 0.5 / 0.7 / 0.9 の3段階で動作する
- ヘルプテキストが英語/日本語で表示される

- [ ] **Step 5: デバッグレベルを戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` → `"debug_level": 0` に変更
