# HuntStrategy スコア適応型損失制御 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HuntStrategyに劣勢時の損失制限（ハードコード）と勝勢時の最善手weight抑制（チェックボックス切替）を追加する

**Architecture:** フィルタ処理直前でスコア差を判定し、劣勢時は`hunt_max_loss`/`hunt_invasion_max_loss`を4.0にキャップ。勝勢時はcombined weight計算完了後に最善手のweightに0.3を掛ける。2機能は相互排他的（劣勢<-6.0 vs 勝勢>+15.0）

**Tech Stack:** Python 3.12, Kivy (GUI), KataGo

---

### Task 1: constants.py にチェックボックス定義を追加

**Files:**
- Modify: `katrain/core/constants.py:179` (AI_OPTION_VALUES), `katrain/core/constants.py:224` (AI_OPTION_ORDER)

- [ ] **Step 1: `AI_OPTION_VALUES` に `hunt_winning_suppress_enabled` を追加**

`katrain/core/constants.py` の179行目 `"hunt_pursue_enabled": "bool",` の直後に追加:

```python
    "hunt_winning_suppress_enabled": "bool",
```

変更後の179-180行:
```python
    "hunt_pursue_enabled": "bool",
    "hunt_winning_suppress_enabled": "bool",
    "hunt_dodge_max_loss": [x / 2 for x in range(1, 7)],  # 0.5〜3.0（0.5刻み）
```

- [ ] **Step 2: `AI_OPTION_ORDER` に表示順を追加**

`katrain/core/constants.py` の224行目 `"hunt_pursue_enabled": 27,` の直後に追加:

```python
    "hunt_winning_suppress_enabled": 28,
```

- [ ] **Step 3: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat: hunt_winning_suppress_enabled のGUIウィジェット定義を追加"
```

---

### Task 2: config.json（パッケージ）にデフォルト値を追加

**Files:**
- Modify: `katrain/config.json:185` (ai:hunt), `katrain/config.json:199` (ai:hunt_diverge)

- [ ] **Step 1: `ai:hunt` セクションに追加**

`katrain/config.json` の185行目を変更。`"hunt_pursue_enabled": true` の後にカンマを追加し、新キーを挿入:

変更前:
```json
            "hunt_pursue_enabled": true
        },
```

変更後:
```json
            "hunt_pursue_enabled": true,
            "hunt_winning_suppress_enabled": false
        },
```

- [ ] **Step 2: `ai:hunt_diverge` セクションに追加**

`katrain/config.json` の199行目を変更。`"hunt_pursue_enabled": true` の後にカンマを追加し、新キーを挿入:

変更前:
```json
            "hunt_pursue_enabled": true
        },
```

変更後:
```json
            "hunt_pursue_enabled": true,
            "hunt_winning_suppress_enabled": false
        },
```

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat: hunt_winning_suppress_enabled のデフォルト値を追加"
```

---

### Task 3: ローカル config.json にキーを追加

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json:185` (ai:hunt), `C:\Users\iwaki\.katrain\config.json:199` (ai:hunt_diverge)

**重要: このファイルは必ずメインセッションで直接Editすること（サブエージェント委任禁止）**

- [ ] **Step 1: `ai:hunt` セクションに追加**

`C:\Users\iwaki\.katrain\config.json` の `"hunt_pursue_enabled": true` 行の後にカンマと新キーを追加:

変更前:
```json
            "hunt_pursue_enabled": true
        },
```

変更後:
```json
            "hunt_pursue_enabled": true,
            "hunt_winning_suppress_enabled": false
        },
```

- [ ] **Step 2: `ai:hunt_diverge` セクションに追加**

同様に `"hunt_pursue_enabled": true` 行の後にカンマと新キーを追加:

変更前:
```json
            "hunt_pursue_enabled": true
        },
```

変更後:
```json
            "hunt_pursue_enabled": true,
            "hunt_winning_suppress_enabled": false
        },
```

---

### Task 4: ai.py に劣勢時の損失制限を実装

**Files:**
- Modify: `katrain/core/ai.py:3668-3669` (設定読み取り後), `katrain/core/ai.py:3799` (フィルタ前)

- [ ] **Step 1: スコア判定定数を定義**

`katrain/core/ai.py` の `HuntStrategy.generate_move()` 内、3669行目 `hunt_pursue_proximity = self.settings.get("hunt_pursue_proximity", 2)` の直後に定数を追加:

```python
        # スコア適応型損失制御の定数
        _LOSING_THRESHOLD = -6.0  # この値未満で劣勢と判定
        _LOSING_MAX_LOSS = 4.0    # 劣勢時の損失上限
```

- [ ] **Step 2: フィルタ前にスコア判定と損失上限キャップを追加**

`katrain/core/ai.py` の3799行目 `# --- 悪手フィルタ（hunt_max_loss 統一閾値） ---` の直前に挿入:

```python
            # --- 劣勢時の損失制限 ---
            score_lead = best_score * player_sign  # 正=自分が有利, 負=自分が不利
            if score_lead < _LOSING_THRESHOLD:
                original_hunt_max_loss = hunt_max_loss
                original_invasion_max_loss = hunt_invasion_max_loss
                hunt_max_loss = min(hunt_max_loss, _LOSING_MAX_LOSS)
                hunt_invasion_max_loss = min(hunt_invasion_max_loss, _LOSING_MAX_LOSS)
                self.game.katrain.log(
                    f"[HuntStrategy] Losing restrict: score_lead={score_lead:.1f}, "
                    f"max_loss {original_hunt_max_loss} -> {hunt_max_loss}, "
                    f"invasion_max_loss {original_invasion_max_loss} -> {hunt_invasion_max_loss}",
                    OUTPUT_DEBUG,
                )
```

**注意**: `hunt_max_loss` と `hunt_invasion_max_loss` はローカル変数なので、ここで上書きしても元のself.settingsは影響しない。以降のフィルタ処理・段階的緩和・侵入フェーズ再計算のすべてにキャップが自動的に効く。

- [ ] **Step 3: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntStrategy劣勢時の損失制限を実装（6目以上劣勢で上限4目）"
```

---

### Task 5: ai.py に勝勢時の最善手weight抑制を実装

**Files:**
- Modify: `katrain/core/ai.py:3669` (設定読み取り), `katrain/core/ai.py:4168` (weight計算後)

- [ ] **Step 1: 設定読み取りと定数追加**

`katrain/core/ai.py` のTask 4で追加した `_LOSING_MAX_LOSS` の直後に追加:

```python
        _WINNING_THRESHOLD = 15.0   # この値超で勝勢と判定
        _WINNING_SUPPRESS_FACTOR = 0.3  # 最善手のweight抑制係数
        hunt_winning_suppress = self.settings.get("hunt_winning_suppress_enabled", False)
```

- [ ] **Step 2: combined weight計算後に最善手weight抑制を追加**

`katrain/core/ai.py` の4168行目付近、候補ログ出力:
```python
        self.game.katrain.log(
            f"[HuntStrategy] {len(moves)} candidate moves ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )
```

この直後、`# 安全弁v2` の直前に挿入:

```python
        # --- 勝勢時の最善手weight抑制 ---
        if hunt_winning_suppress and moves and best_gtp_by_score and best_score is not None:
            score_lead_for_suppress = best_score * player_sign
            if score_lead_for_suppress > _WINNING_THRESHOLD:
                for i, (m, w) in enumerate(moves):
                    if m.gtp() == best_gtp_by_score:
                        original_w = w
                        suppressed_w = w * _WINNING_SUPPRESS_FACTOR
                        moves[i] = (m, suppressed_w)
                        self.game.katrain.log(
                            f"[HuntStrategy] Winning suppress: score_lead={score_lead_for_suppress:.1f}, "
                            f"best_move={best_gtp_by_score} weight {original_w:.4f} -> {suppressed_w:.4f}",
                            OUTPUT_DEBUG,
                        )
                        break

```

- [ ] **Step 3: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntStrategy勝勢時の最善手weight抑制を実装（15目以上勝勢でweight×0.3）"
```

---

### Task 6: i18n ヘルプテキストを追加

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:989-990`
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:1080-1081`

- [ ] **Step 1: 英語ヘルプテキストに追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の990行目 `"the opponent resists during a capturing race, instead of tenuki."` の直後に追加:

```
"hunt_winning_suppress_enabled: Winning position best-move suppression. "
"When leading by 15+ points, reduces the weight of KataGo's best move "
"to lower the top-move match rate while maintaining playing style."
```

変更後の989-993行:
```
"hunt_pursue_enabled: Semeai pursuit. Continue playing killing moves when "
"the opponent resists during a capturing race, instead of tenuki.\n"
"hunt_winning_suppress_enabled: Winning position best-move suppression. "
"When leading by 15+ points, reduces the weight of KataGo's best move "
"to lower the top-move match rate while maintaining playing style."
```

**注意**: `hunt_pursue_enabled` 行末に `\n` を追加して次エントリとの改行を確保すること。

- [ ] **Step 2: 日本語ヘルプテキストに追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の1081行目 `"手抜きせず詰め手を継続します。"` の直後に追加:

```
"hunt_winning_suppress_enabled: 勝勢時の最善手抑制。"
"15目以上リードしている場合、KataGo最善手の重みを低減し、"
"棋風を維持しつつAI最善手一致率を下げます。"
```

変更後の1080-1084行:
```
"hunt_pursue_enabled: 攻め合い追撃。攻め合い中に相手が勝負手を打った場合、"
"手抜きせず詰め手を継続します。\n"
"hunt_winning_suppress_enabled: 勝勢時の最善手抑制。"
"15目以上リードしている場合、KataGo最善手の重みを低減し、"
"棋風を維持しつつAI最善手一致率を下げます。"
```

**注意**: `hunt_pursue_enabled` 行末に `\n` を追加して次エントリとの改行を確保すること。

- [ ] **Step 3: `.mo` ファイルを再コンパイル**

```bash
python tools/compile_mo.py
```

期待出力: `Compiled ... .po -> .mo` のようなメッセージ

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/
git commit -m "feat: hunt_winning_suppress_enabled のi18nヘルプテキストを追加（en/jp）"
```

---

### Task 7: ai-parameters.md を更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`

- [ ] **Step 1: HuntStrategyパラメータテーブルに追加**

`.claude/rules/ai-parameters.md` の狩猟戦略パラメータテーブル末尾（`hunt_pursue_ownership_threshold` の行の後）に以下を追加:

```markdown
| hunt_winning_suppress_enabled | false | false | 勝勢時の最善手weight抑制。15目以上リードでKataGo最善手のweight×0.3（GUI: チェックボックス） |
```

- [ ] **Step 2: スコア適応型損失制御の説明を追加**

同テーブルの後に以下のセクションを追加:

```markdown

**スコア適応型損失制御（ハードコード）**: 劣勢時（`score_lead < -6.0`）は `hunt_max_loss` と `hunt_invasion_max_loss` を `min(設定値, 4.0)` にキャップ。段階的緩和も4.0でキャップされ、候補がなければ即failsafe（最善手選択）。
```

- [ ] **Step 3: コミット（サブエージェント経由）**

`.claude/rules/` 配下のEditは拒否されることがあるため、サブエージェント経由で編集・コミットする。

---

### Task 8: 動作検証

**Files:** なし（検証のみ）

- [ ] **Step 1: CLIで劣勢局面の損失制限を検証**

適当なSGFファイルで劣勢局面の手数を指定して実行:

```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --move 100 --strategy hunt --output text
```

ログに `Losing restrict:` が出力されていれば劣勢制限が発動している。`score_lead` が-6.0未満で `max_loss` が4.0にキャップされていることを確認。

- [ ] **Step 2: CLIで勝勢局面の最善手抑制を検証**

勝勢局面で `hunt_winning_suppress_enabled=true` を指定:

```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --move 50 --strategy hunt --settings hunt_winning_suppress_enabled=true --output text
```

ログに `Winning suppress:` が出力されていれば勝勢抑制が発動している。最善手のweightが0.3倍されていることを確認。

- [ ] **Step 3: チェックボックスOFFで無効化されることを確認**

`hunt_winning_suppress_enabled=false`（デフォルト）で `Winning suppress:` が出力されないことを確認:

```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --move 50 --strategy hunt --output text
```

- [ ] **Step 4: GUIでチェックボックスが表示されることを確認**

```bash
python -m katrain
```

設定画面 → Hunt戦略 → `hunt_winning_suppress_enabled` チェックボックスが表示されていることを確認。
