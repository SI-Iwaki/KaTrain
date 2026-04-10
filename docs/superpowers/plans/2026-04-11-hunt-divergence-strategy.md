# HuntDivergenceStrategy 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HuntStrategyの棋風を維持しつつAI最善手一致率を35-45%に低減する新戦略 `HuntDivergenceStrategy` を追加する。

**Architecture:** HuntStrategyの選択ロジック末尾を `_try_tiebreak` / `_select_final_move` メソッドに切り出し、子クラスで `_select_final_move` のみオーバーライドして Best-move dodge を実装する。

**Tech Stack:** Python 3.12 / KaTrain / KataGo

---

## ファイル構成

| 操作 | ファイル | 責務 |
|---|---|---|
| Modify | `katrain/core/constants.py` | AI_HUNT_DIVERGE定数、AI_STRATEGIES登録、AI_OPTION_VALUES/ORDER追加 |
| Modify | `katrain/core/ai.py` | HuntStrategy選択ロジック切り出し + HuntDivergenceStrategy新設 |
| Modify | `katrain/config.json` | パッケージデフォルト設定追加 |
| Modify | `C:\Users\iwaki\.katrain\config.json` | ユーザーローカル設定追加 |
| Modify | `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 英語翻訳 |
| Modify | `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | 日本語翻訳 |
| Modify | `.claude/rules/ai-parameters.md` | パラメータテーブル追加 |

---

### Task 1: constants.py に定数・設定を追加

**Files:**
- Modify: `katrain/core/constants.py`

- [ ] **Step 1: AI_HUNT_DIVERGE定数を追加**

60行目 `AI_HUNT = "ai:hunt"` の直後に追加:

```python
AI_HUNT_DIVERGE = "ai:hunt_diverge"
```

- [ ] **Step 2: AI_STRATEGIES に追加**

67行目 `AI_STRATEGIES` の末尾 `AI_HUNT` の後に `AI_HUNT_DIVERGE` を追加:

```python
AI_STRATEGIES = AI_STRATEGIES_ENGINE + AI_STRATEGIES_POLICY + [AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE]
```

- [ ] **Step 3: AI_STRATEGIES_RECOMMENDED_ORDER に追加**

88行目 `AI_HUNT` の直後に追加:

```python
    AI_HUNT_DIVERGE,
```

- [ ] **Step 4: AI_STRENGTH に追加**

111行目 `AI_HUNT: float("nan"),` の直後に追加:

```python
    AI_HUNT_DIVERGE: float("nan"),
```

- [ ] **Step 5: AI_OPTION_VALUES にdodgeパラメータ追加**

173行目 `"hunt_invasion_temperature"` の行の直後に追加:

```python
    "hunt_dodge_max_loss": [x / 2 for x in range(1, 7)],  # 0.5〜3.0（0.5刻み）
    "hunt_dodge_top_n": list(range(2, 6)),  # 2〜5
```

- [ ] **Step 6: AI_OPTION_ORDER にdodgeパラメータの表示順追加**

213行目 `"hunt_invasion_temperature": 24,` の直後に追加:

```python
    "hunt_dodge_max_loss": 0,
    "hunt_dodge_top_n": 1,
```

- [ ] **Step 7: 構文確認**

Run: `python -c "import ast; ast.parse(open('katrain/core/constants.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 8: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat: HuntDivergenceStrategy用の定数・設定値を追加"
```

---

### Task 2: HuntStrategy の選択ロジックをメソッドに切り出し

**Files:**
- Modify: `katrain/core/ai.py:3949-4014`

**目的:** generate_move末尾のタイブレーク+選択ロジックを `_try_tiebreak` と `_select_final_move` に分離し、子クラスでオーバーライド可能にする。

- [ ] **Step 1: `_try_tiebreak` メソッドを追加**

`generate_move` メソッドの直前（`class HuntStrategy` 内、generate_moveの外）に以下を追加:

```python
    def _try_tiebreak(self, top5, move_infos, player_sign, filtered_count, top_str):
        """タイブレーク判定。発動した場合は (Move, ai_thoughts) を返し、しなければ None を返す。"""
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
                        f"[{self.__class__.__name__}] Tiebreak({trigger}): {winner.gtp()} over {loser.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt, "
                        f"policy_ratio={top1_w/top2_w:.3f}, visits={top1_visits}/{top2_visits})",
                        OUTPUT_DEBUG,
                    )
                    return winner, (
                        f"\n{top_str}\n\nScore tiebreak({trigger}): played {winner.gtp()} "
                        f"(score diff={abs(s1-s2):.1f}pt). ({filtered_count} filtered)"
                    )
        return None
```

- [ ] **Step 2: `_select_final_move` メソッドを追加**

`_try_tiebreak` の直後に追加:

```python
    def _select_final_move(self, moves, phase_name, move_infos, best_score,
                           best_gtp_by_score, player_sign, hunt_max_loss,
                           filtered_count, top_str, human_policy):
        """最終的な手の選択。子クラスでオーバーライド可能。"""
        hunt_invasion_temperature = self.settings.get("hunt_invasion_temperature", 1.5)

        # 重み付き選択（Invadeフェーズは温度で分布を平坦化）
        if phase_name == "Invade" and hunt_invasion_temperature != 1.0:
            inv_temp = 1.0 / hunt_invasion_temperature
            temp_moves = [(m, w ** inv_temp) for m, w in moves]
            selected = weighted_selection_without_replacement(temp_moves, 1)[0]
            # 温度選択後の安全チェック
            if move_infos and best_gtp_by_score:
                _sel_gtp = selected[0].gtp()
                _pt_score_map = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
                if _sel_gtp in _pt_score_map and _sel_gtp != best_gtp_by_score:
                    _sel_loss = player_sign * (best_score - _pt_score_map[_sel_gtp])
                    if _sel_loss >= hunt_max_loss:
                        _top_w_move = max(moves, key=lambda x: x[1])[0]
                        self.game.katrain.log(
                            f"[{self.__class__.__name__}] Post-temp safety: {_sel_gtp} loss={_sel_loss:.2f} >= {hunt_max_loss}, "
                            f"fallback to top weighted {_top_w_move.gtp()}",
                            OUTPUT_DEBUG,
                        )
                        selected = (_top_w_move, 0)
        else:
            selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]
        self.game.katrain.log(f"[{self.__class__.__name__}] Selected: {move.gtp()} ({phase_name})", OUTPUT_DEBUG)

        ai_thoughts = (
            f"\n{top_str}\n\n{phase_name}: played {move.gtp()} "
            f"({filtered_count} bad moves filtered)"
        )
        return move, ai_thoughts
```

- [ ] **Step 3: generate_move末尾を書き換え**

`generate_move` 内の3949行目〜4014行目（top5表示、タイブレーク、選択ロジック）を以下に置き換え:

```python
        # デバッグ: 上位5手表示
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
        top_str = "\n".join([f"#{i+1}: {m.gtp()} weight={w:.4f}" for i, (m, w) in enumerate(top5)])
        self.game.katrain.log(f"[{self.__class__.__name__}] Top 5:\n{top_str}", OUTPUT_DEBUG)

        # タイブレーク
        tiebreak_result = self._try_tiebreak(top5, move_infos, player_sign, filtered_count, top_str)
        if tiebreak_result:
            return tiebreak_result

        # 最終選択（子クラスでオーバーライド可能）
        return self._select_final_move(moves, phase_name, move_infos, best_score,
                                       best_gtp_by_score, player_sign, hunt_max_loss,
                                       filtered_count, top_str, human_policy)
```

- [ ] **Step 4: 構文確認**

Run: `python -c "import ast; ast.parse(open('katrain/core/ai.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "refactor: HuntStrategyのタイブレーク・選択ロジックをメソッドに切り出し"
```

---

### Task 3: HuntDivergenceStrategy クラスを追加

**Files:**
- Modify: `katrain/core/ai.py`

- [ ] **Step 1: import に AI_HUNT_DIVERGE を追加**

ai.py冒頭のimport文で `AI_HUNT` がimportされている行に `AI_HUNT_DIVERGE` を追加。

- [ ] **Step 2: HuntDivergenceStrategy クラスを追加**

HuntStrategyクラスの直後（旧4014行目 `return move, ai_thoughts` の後、`def generate_ai_move` の前）に以下を追加:

```python
@register_strategy(AI_HUNT_DIVERGE)
class HuntDivergenceStrategy(HuntStrategy):
    """狩猟戦略（一致率低減版） — HuntStrategyの棋風を維持しつつAI最善手一致率を低減する"""

    def _select_final_move(self, moves, phase_name, move_infos, best_score,
                           best_gtp_by_score, player_sign, hunt_max_loss,
                           filtered_count, top_str, human_policy):
        """温度なしのweighted selection + Best-move dodge。"""
        # 通常のweighted selection（温度なし）
        selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]

        # Best-move dodge: 選ばれた手がKataGo最善手なら、僅差+humanPolicy上位の代替手に差し替え
        if move_infos and best_gtp_by_score and move.gtp() == best_gtp_by_score:
            dodge_max_loss = self.settings.get("hunt_dodge_max_loss", 1.0)
            dodge_top_n = int(self.settings.get("hunt_dodge_top_n", 3))

            # 候補手プール内でのhumanPolicy順位を算出
            bx, by = self.game.board_size
            hp_by_gtp = {}
            for m, w in moves:
                if m.coords:
                    x, y = m.coords
                    idx = (by - y - 1) * bx + x
                    if idx < len(human_policy):
                        hp_by_gtp[m.gtp()] = human_policy[idx]

            sorted_by_hp = sorted(hp_by_gtp.items(), key=lambda x: -x[1])
            top_n_gtps = {gtp for gtp, _ in sorted_by_hp[:dodge_top_n]}

            # スコアマップ
            score_map = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}

            # 代替候補: スコア僅差 + humanPolicy上位N + 非最善手
            alternatives = []
            for m, w in moves:
                gtp = m.gtp()
                if gtp == best_gtp_by_score or gtp not in top_n_gtps or gtp not in score_map:
                    continue
                loss = player_sign * (best_score - score_map[gtp])
                if loss <= dodge_max_loss:
                    hp_rank = next(i for i, (g, _) in enumerate(sorted_by_hp) if g == gtp) + 1
                    alternatives.append((m, loss, hp_rank))

            if alternatives:
                best_alt = min(alternatives, key=lambda x: x[1])
                alt_move, alt_loss, alt_rank = best_alt
                self.game.katrain.log(
                    f"[HuntDivergenceStrategy] Best-move dodge: {best_gtp_by_score} -> {alt_move.gtp()} "
                    f"(loss={alt_loss:.2f}, hP rank={alt_rank}/{len(sorted_by_hp)})",
                    OUTPUT_DEBUG,
                )
                move = alt_move
            else:
                self.game.katrain.log(
                    f"[HuntDivergenceStrategy] Best-move dodge: no alternative "
                    f"(best={best_gtp_by_score}, candidates checked={len(moves)-1})",
                    OUTPUT_DEBUG,
                )

        self.game.katrain.log(f"[HuntDivergenceStrategy] Selected: {move.gtp()} ({phase_name})", OUTPUT_DEBUG)

        ai_thoughts = (
            f"\n{top_str}\n\n{phase_name}: played {move.gtp()} "
            f"({filtered_count} bad moves filtered)"
        )
        return move, ai_thoughts
```

- [ ] **Step 3: 構文確認**

Run: `python -c "import ast; ast.parse(open('katrain/core/ai.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntDivergenceStrategy（狩猟戦略・一致率低減版）を追加"
```

---

### Task 4: config.json にデフォルト設定を追加

**Files:**
- Modify: `katrain/config.json`
- Modify: `C:\Users\iwaki\.katrain\config.json`

- [ ] **Step 1: パッケージconfig.jsonに追加**

`katrain/config.json` の `"ai:hunt"` セクション（182行目 `"hunt_invasion_temperature": 1.5` の `}` の後）に追加:

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
            "hunt_dodge_top_n": 3
        },
```

- [ ] **Step 2: ユーザーローカルconfig.jsonに追加**

`C:\Users\iwaki\.katrain\config.json` の `"ai:hunt"` セクションの直後に同じエントリを追加。

- [ ] **Step 3: コミット（パッケージconfig.jsonのみ）**

```bash
git add katrain/config.json
git commit -m "feat: HuntDivergenceStrategyのデフォルト設定をconfig.jsonに追加"
```

---

### Task 5: i18n翻訳を追加

**Files:**
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`

- [ ] **Step 1: 英語翻訳を追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の `ai:hunt` 関連エントリの直後（`"hunt_invasion_temperature"` の説明行の後）に追加:

```
msgid "ai:hunt_diverge"
msgstr "Hunt Strategy (Low Agreement)"

msgid "aihelp:hunt_diverge"
msgstr ""
"Hunt Strategy (Low Agreement): Same aggressive invasion and group attack "
"as Hunt Strategy, but with reduced AI top-move agreement rate. Uses "
"Best-move dodge to avoid playing KataGo's top choice when a close "
"alternative exists.\n"
"hunt_dodge_max_loss: Maximum score loss for dodge alternatives. "
"Larger = more dodge opportunities but weaker moves.\n"
"hunt_dodge_top_n: Only consider top N humanPolicy moves as dodge "
"alternatives. Smaller = more natural moves."
```

- [ ] **Step 2: 日本語翻訳を追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `ai:hunt` 関連エントリの直後に追加:

```
msgid "ai:hunt_diverge"
msgstr "狩猟戦略（一致率低減）"

msgid "aihelp:hunt_diverge"
msgstr ""
"狩猟戦略（一致率低減）: 狩猟戦略と同じ侵入・石群攻撃の棋風を維持しつつ、"
"AI最善手一致率を低減します。KataGo最善手が選ばれた際に、スコア僅差かつ"
"humanPolicy上位の代替手があれば差し替えます。\n"
"hunt_dodge_max_loss: dodge対象とするスコア僅差の閾値（目数）。"
"大きい＝dodge機会が増えるが弱い手も選ばれる。\n"
"hunt_dodge_top_n: dodge対象とするhumanPolicy上位N位。"
"小さい＝より自然な手だけを対象にする。"
```

- [ ] **Step 3: .moファイルをコンパイル**

Run: `python tools/compile_mo.py`

- [ ] **Step 4: コミット**

```bash
git add katrain/i18n/
git commit -m "feat: HuntDivergenceStrategyのi18n翻訳を追加（英語・日本語）"
```

---

### Task 6: ai-parameters.md にパラメータテーブルを追加

**Files:**
- Modify: `.claude/rules/ai-parameters.md`

- [ ] **Step 1: 狩猟戦略（一致率低減版）セクションを追加**

`## 狩猟戦略（HuntStrategy）` セクションの直後に追加:

```markdown
## 狩猟戦略・一致率低減版（HuntDivergenceStrategy）

HuntStrategyを継承。温度は使わず、Best-move dodgeでAI最善手一致率を低減する。Hunt系パラメータはHuntStrategyと共通。

**着手選択**: HuntStrategyと同じ2段階クエリ・重み計算・フェーズ判定。最終選択のみ異なる: 温度なしのweighted_selection後、選択手がKataGo最善手と一致した場合、スコア僅差かつhumanPolicy上位の代替手に差し替える（Best-move dodge）。

| パラメータ | デフォルト(19路) | デフォルト(13路) | 備考 |
|---|---|---|---|
| hunt_dodge_max_loss | 1.0 | 1.0 | dodge対象のスコア僅差閾値（目） |
| hunt_dodge_top_n | 3 | 3 | humanPolicy上位N位以内が対象 |

その他のhunt_*パラメータはHuntStrategyと同値。
```

- [ ] **Step 2: コミット**

```bash
git add .claude/rules/ai-parameters.md
git commit -m "docs: ai-parameters.mdにHuntDivergenceStrategyのパラメータテーブルを追加"
```

---

### Task 7: 動作検証

- [ ] **Step 1: debug_level を有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `"debug_level": 1` に変更。

- [ ] **Step 2: 対局で検証**

`python -m katrain` で起動。AI設定から「狩猟戦略（一致率低減）」を選択して対局。

- [ ] **Step 3: ログで確認**

Grepパターン:
- dodge発動: `Best-move dodge:`
- dodge未発動: `no alternative`
- 全着手: `Selected:`
- フェーズ: `Phase:`（Invade/Hunt両方出現するか）
- 設定値: `Initializing.*Strategy with settings`

- [ ] **Step 4: 評価レポートで一致率確認**

KaTrain評価レポートでAI最善手一致率が35-45%範囲か確認。

- [ ] **Step 5: debug_level を元に戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` → `"debug_level": 0` に変更。
