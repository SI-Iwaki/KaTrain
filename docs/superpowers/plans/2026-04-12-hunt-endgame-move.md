# hunt_endgame_move パラメータ追加 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HuntStrategyのヨセモード発動手数を設定可能にし、19路盤のデフォルトを200手に変更する

**Architecture:** `hunt_endgame_move` パラメータを `constants.py`・`config.json`(2箇所)・`ai.py`・i18n に追加。19路盤ではこのパラメータ値を使い、13路以下は従来の `math.ceil(bx * by * 0.5)` を維持する。HuntDivergenceStrategyはHuntStrategyを継承しており、親クラスの変更が自動的に適用される。

**Tech Stack:** Python 3.12, KaTrain

---

### Task 1: constants.py にパラメータ定義を追加

**Files:**
- Modify: `katrain/core/constants.py:177` (AI_OPTION_VALUES), `katrain/core/constants.py:220` (GUI行位置)

- [ ] **Step 1: AI_OPTION_VALUES にスライダー定義を追加**

`hunt_focus_stddev` の直後（178行目付近）に追加:

```python
    "hunt_endgame_move": list(range(150, 260, 10)),  # 150〜250（10刻み）
```

- [ ] **Step 2: GUI行位置を追加**

`hunt_focus_stddev: 25` の直後（221行目付近）に追加:

```python
    "hunt_endgame_move": 26,
```

- [ ] **Step 3: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat: hunt_endgame_moveパラメータのGUI定義を追加"
```

### Task 2: ai.py のエンドゲーム閾値をパラメータ化

**Files:**
- Modify: `katrain/core/ai.py:4054` (HuntStrategy.generate_move 内のエンドゲーム閾値)

- [ ] **Step 1: エンドゲーム閾値をパラメータから取得するよう変更**

`ai.py` 4054行目を変更:

```python
# 変更前
        endgame_threshold = math.ceil(bx * by * 0.5)

# 変更後
        if bx >= 19 and by >= 19:
            endgame_threshold = int(self.settings.get("hunt_endgame_move", 200))
        else:
            endgame_threshold = math.ceil(bx * by * 0.5)
```

- [ ] **Step 2: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntStrategyのヨセモード閾値をhunt_endgame_moveパラメータで制御"
```

### Task 3: config.json（パッケージ）にデフォルト値を追加

**Files:**
- Modify: `katrain/config.json:183` (ai:hunt セクション)

- [ ] **Step 1: ai:hunt セクションに hunt_endgame_move を追加**

`hunt_focus_stddev: 7.0` の行末にカンマを追加し、次の行に追加:

```json
        "ai:hunt": {
            "hunt_max_loss": 6.0,
            "hunt_min_group_size": 5,
            "hunt_proximity_stddev": 3.0,
            "hunt_instability_min": 0.3,
            "hunt_invasion_max_loss": 8.0,
            "hunt_invasion_min": 0.2,
            "hunt_invasion_max": 0.7,
            "hunt_invasion_proximity_stddev": 3.0,
            "hunt_invasion_temperature": 1.5,
            "hunt_focus_stddev": 7.0,
            "hunt_endgame_move": 200
        },
```

注意: `ai:hunt_diverge` セクションにも追加する（HuntDivergenceStrategyはHuntStrategyを継承し同じ `settings` を参照する）:

```json
        "ai:hunt_diverge": {
            "hunt_max_loss": 6.0,
            "hunt_min_group_size": 5,
            "hunt_proximity_stddev": 3.0,
            "hunt_instability_min": 0.3,
            "hunt_invasion_max_loss": 8.0,
            "hunt_invasion_min": 0.2,
            "hunt_invasion_max": 0.7,
            "hunt_invasion_proximity_stddev": 3.0,
            "hunt_dodge_max_loss": 1.0,
            "hunt_dodge_top_n": 3,
            "hunt_endgame_move": 200
        },
```

- [ ] **Step 2: コミット**

```bash
git add katrain/config.json
git commit -m "feat: config.json（パッケージ）にhunt_endgame_moveデフォルト値を追加"
```

### Task 4: config.json（ユーザーローカル）にキーを追加

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json:183` (ai:hunt), `C:\Users\iwaki\.katrain\config.json:195` (ai:hunt_diverge)

- [ ] **Step 1: ai:hunt セクションに追加**

`hunt_focus_stddev: 7.0` の行末にカンマを追加し、次の行に追加:

```json
            "hunt_endgame_move": 200
```

- [ ] **Step 2: ai:hunt_diverge セクションに追加**

`hunt_dodge_top_n: 3` の行末にカンマを追加し、次の行に追加:

```json
            "hunt_endgame_move": 200
```

- [ ] **Step 3: 確認（コミット対象外）**

ユーザーローカル設定はgit管理外のため、コミット不要。

### Task 5: i18n（英語・日本語）にヘルプテキストを追加

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po:985` (ai:hunt ヘルプ末尾)
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:1077` (ai:hunt ヘルプ末尾)

- [ ] **Step 1: 英語ヘルプに hunt_endgame_move の説明を追加**

`katrain.po`（en）の `aihelp:hunt` msgstr 末尾（985行目、`hunt_focus_stddev` の説明の後）に追記:

```
"hunt_focus_stddev: Attention focus radius. Controls how strongly moves are focused "
"near the current action area (last move + most unstable target). "
"Lower = tighter focus on current fight, higher = allow moves across wider area.\n"
"hunt_endgame_move: Move number to switch to endgame (yose) mode on 19x19. "
"In endgame mode, plays the top humanPolicy move ignoring target weights. "
"Only affects 19x19 boards."
```

- [ ] **Step 2: 日本語ヘルプに hunt_endgame_move の説明を追加**

`katrain.po`（jp）の `aihelp:hunt` msgstr 末尾（1077行目）に追記:

```
"hunt_focus_stddev: 注意フォーカス半径。直前の着手と最も不安定なターゲット付近に注意を集中する度合いを制御。"
"小さい＝現在の戦いに集中、大きい＝広い範囲の手を許容。\n"
"hunt_endgame_move: 19路盤でヨセモードに切り替える手数。"
"ヨセモードではターゲット重みを無視しhumanPolicy最上位手を選択する。19路盤のみ有効。"
```

- [ ] **Step 3: .mo ファイルをコンパイル**

```bash
python tools/compile_mo.py
```

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/
git commit -m "feat: hunt_endgame_moveのi18nヘルプテキストを追加（en/jp）"
```

### Task 6: ai-parameters.md を更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md` (狩猟戦略テーブル)

- [ ] **Step 1: 狩猟戦略パラメータテーブルに hunt_endgame_move を追加**

`hunt_focus_stddev` の行の後に追加:

```markdown
| hunt_endgame_move | 200 | — | 19路盤でヨセモードに切り替える手数（19路盤のみ。13路以下は `ceil(0.5×盤面マス数)` 固定） |
```

- [ ] **Step 2: コミット**

```bash
git add .claude/rules/ai-parameters.md
git commit -m "docs: ai-parameters.mdにhunt_endgame_moveを追加"
```

### Task 7: 動作確認（CLIデバッグ）

- [ ] **Step 1: 19路盤でヨセモード発動を確認**

199手目（ヨセモード前）と200手目（ヨセモード後）で出力を比較:

```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --move 199 --strategy hunt --output text
python -m katrain_debug --sgf tests/data/panda1.sgf --move 200 --strategy hunt --output text
```

199手目: ヨセモードでない（Phase: Invade/Hunt等）
200手目: `Endgame: played top humanPolicy move` が表示される

- [ ] **Step 2: パラメータ変更が効くことを確認**

```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --move 180 --strategy hunt --settings hunt_endgame_move=180 --output text
```

180手目でヨセモードが発動することを確認。

- [ ] **Step 3: 13路盤が影響を受けないことを確認**

13路盤のSGFがあれば、従来通り `ceil(0.5×169)=85` 手目でヨセモードになることを確認。
