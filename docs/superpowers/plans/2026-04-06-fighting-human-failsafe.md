# 力戦派humanモード フェイルセーフ実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 極端なパラメータ設定時にフィルタがバイパスされて大悪手が出る問題を、パラメータ範囲制限 + 段階的閾値緩和の二重防御で修正する。

**Architecture:** constants.pyでGUIパラメータ範囲を制限し、ai.pyの`_generate_human()`にフィルタ緩和ループを追加。既存フィルタロジックを関数化して再利用する。

**Tech Stack:** Python 3.12, KaTrain/KataGo

---

### Task 1: パラメータ範囲の制限（constants.py）

**Files:**
- Modify: `katrain/core/constants.py:119-147`

- [ ] **Step 1: `proximity_stddev` の最小値を 2.0 に変更**

`katrain/core/constants.py` 120行目を変更:

```python
# 変更前
"proximity_stddev": [x / 2 for x in range(2, 21)],  # 1.0 to 10.0 in 0.5 steps

# 変更後
"proximity_stddev": [x / 2 for x in range(4, 21)],  # 2.0 to 10.0 in 0.5 steps
```

- [ ] **Step 2: `fighting_invasion_bonus` と `fighting_contact_boost` の最大値を 5.0 に制限**

`katrain/core/constants.py` 145-146行目を変更:

```python
# 変更前
"fighting_invasion_bonus": [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0],
"fighting_contact_boost": [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0],

# 変更後
"fighting_invasion_bonus": [1.0, 1.5, 2.0, 3.0, 5.0],
"fighting_contact_boost": [1.0, 1.5, 2.0, 3.0, 5.0],
```

- [ ] **Step 3: `fighting_chaos_relax` の最大値を 3.0 に制限**

`katrain/core/constants.py` 147行目を変更:

```python
# 変更前
"fighting_chaos_relax": [x / 2 for x in range(0, 11)],

# 変更後
"fighting_chaos_relax": [x / 2 for x in range(0, 7)],  # 0.0 to 3.0 in 0.5 steps
```

- [ ] **Step 4: GUIスライダーインデックスの確認**

`AI_OPTION_ORDER` の `fighting_chaos_relax` のインデックスは `5` だが、新しい選択肢数は7個（0.0〜3.0）なので `5` は範囲内（0-indexed で chaos_relax=2.5）。変更不要。

ただし `fighting_invasion_bonus` のインデックスは `3` で、新しい選択肢 `[1.0, 1.5, 2.0, 3.0, 5.0]` のindex 3 は `3.0`。変更不要。

`fighting_contact_boost` のインデックスは `4` で、新しい選択肢のindex 4 は `5.0`。変更不要。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/constants.py
git commit -m "fix: 力戦派パラメータ範囲を制限し極端な設定を防止"
```

---

### Task 2: フィルタロジックの関数化（ai.py）

**Files:**
- Modify: `katrain/core/ai.py:1608-1631`

- [ ] **Step 1: 既存のフィルタループをヘルパー関数に抽出**

`_generate_human()` 内の1608-1627行のフィルタループを、同メソッド内のローカル関数として抽出する。1607行目（`opponent_coords = ...`）の直後に挿入:

```python
            def _filter_moves(move_infos, threshold_base, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score):
                """指定閾値で悪手フィルタを実行し、通過した手のsetを返す。"""
                result = set()
                for mi in move_infos:
                    gtp_move = mi.get("move", "")
                    score = mi.get("scoreLead", 0)
                    loss = player_sign * (best_score - score)

                    threshold = threshold_base
                    if chaos_relax > 0.0 and gtp_move != "pass":
                        mx, my = Move.from_gtp(gtp_move, player=self.cn.next_player).coords
                        o = ownership_grid[my][mx] if ownership_grid else 0.0
                        is_opponent_terr = (player_sign * o) < -0.5

                        min_dist_sq = 1000
                        if opponent_coords:
                            min_dist_sq = min((mx - ox) ** 2 + (my - oy) ** 2 for ox, oy in opponent_coords)

                        if is_opponent_terr and min_dist_sq == 1:
                            threshold += chaos_relax

                    if loss < threshold:
                        result.add(gtp_move)
                return result
```

- [ ] **Step 2: 既存のフィルタループをヘルパー呼び出しに置換**

1608-1627行（`for mi in move_infos:` 〜 `good_moves.add(gtp_move)` のブロック）を以下に置換:

```python
            good_moves = _filter_moves(move_infos, BAD_MOVE_THRESHOLD, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score)
```

- [ ] **Step 3: 動作確認**

`python -m katrain` で起動し、力戦派humanモードで数手打って正常動作を確認。ログに `moves pass score filter` が従来通り出力されることを確認。

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py
git commit -m "refactor: 力戦派humanモードの悪手フィルタをヘルパー関数に抽出"
```

---

### Task 3: 段階的閾値緩和の実装（ai.py）

**Files:**
- Modify: `katrain/core/ai.py` — Task 2で追加した `_filter_moves` 呼び出しの直後

- [ ] **Step 1: 段階的緩和ロジックを追加**

Task 2 で置換した `good_moves = _filter_moves(...)` の行と、既存のログ出力（`{len(good_moves)} moves pass score filter`）の間に以下を挿入:

```python
            # --- 段階的閾値緩和フェイルセーフ ---
            _FILTER_RELAXATION_STEPS = [1.5, 2.0]
            _FILTER_ABSOLUTE_CAP = 9.0
            if not good_moves:
                original_threshold = BAD_MOVE_THRESHOLD
                relaxed = False
                for multiplier in _FILTER_RELAXATION_STEPS:
                    relaxed_threshold = original_threshold * multiplier
                    good_moves = _filter_moves(move_infos, relaxed_threshold, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score)
                    if good_moves:
                        self.game.katrain.log(
                            f"[FightingStrategy:human] Filter relaxed: threshold {original_threshold} -> {relaxed_threshold:.1f}, found {len(good_moves)} moves",
                            OUTPUT_DEBUG,
                        )
                        relaxed = True
                        break
                if not good_moves:
                    good_moves = _filter_moves(move_infos, _FILTER_ABSOLUTE_CAP, chaos_relax, ownership_grid, opponent_coords, player_sign, best_score)
                    if good_moves:
                        self.game.katrain.log(
                            f"[FightingStrategy:human] Filter relaxed: threshold {original_threshold} -> {_FILTER_ABSOLUTE_CAP} (absolute cap), found {len(good_moves)} moves",
                            OUTPUT_DEBUG,
                        )
                        relaxed = True
                if not good_moves and best_gtp_by_score:
                    self.game.katrain.log(
                        f"[FightingStrategy:human] Filter failsafe: no moves passed even at {_FILTER_ABSOLUTE_CAP}pt cap, forcing best-score move {best_gtp_by_score}",
                        OUTPUT_DEBUG,
                    )
                    if best_gtp_by_score == "pass":
                        return Move(None, player=self.cn.next_player), "Filter failsafe: best move is pass."
                    return Move.from_gtp(best_gtp_by_score, player=self.cn.next_player), (
                        f"Filter failsafe: no moves within {_FILTER_ABSOLUTE_CAP}pt, forced {best_gtp_by_score}."
                    )
```

- [ ] **Step 2: コミット**

```bash
git add katrain/core/ai.py
git commit -m "fix: 力戦派humanモードに段階的閾値緩和フェイルセーフを追加"
```

---

### Task 4: CLAUDE.md のパラメータテーブル更新

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: パラメータ範囲変更の反映**

`CLAUDE.md` の「力戦派モード（FightingStrategy）」テーブルを以下のように更新:

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| `fighting_invasion_bonus` | 1.0 | 相手地への侵入手の重みボーナス（全モード共通、**最大5.0**） |
| `fighting_contact_boost` | 1.0 | 相手石への接触手（距離1）の重みブースト（全モード共通、**最大5.0**） |
| `fighting_chaos_relax` | 0.0 | humanモード: 相手地への接触手の悪手閾値を緩和する目数（**最大3.0**） |
| `proximity_stddev` | 3.0 | 相手石への近接重みの標準偏差（小さいほど近距離に集中、**最小2.0**） |

他のパラメータ（`fighting_mode`, `fighting_max_loss`, `force_tengen_opening`, `unsettled_power`）は変更なし。

- [ ] **Step 2: コミット**

```bash
git add CLAUDE.md
git commit -m "docs: 力戦派パラメータの範囲制限をCLAUDE.mdに反映"
```
