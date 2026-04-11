# Hunt Invadeフェーズ 温度選択後安全チェック 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invadeフェーズの温度選択後に、選ばれた手のスコア損失が `hunt_max_loss` 以上なら top weighted move にフォールバックする安全チェックを追加する。

**Architecture:** 温度選択ブロック（`ai.py:3987-3992`）の直後、`move = selected[0]` の前に、選択手のlossを計算しフォールバック判定を挿入する。既存の `move_infos`・`best_score`・`player_sign`・`hunt_max_loss`・`moves` をそのまま利用し、新規パラメータは不要。

**Tech Stack:** Python 3.12 / KaTrain / KataGo

---

## ファイル構成

| 操作 | ファイル | 責務 |
|---|---|---|
| Modify | `katrain/core/ai.py:3990-3993` | 温度選択後の安全チェック追加 |

---

### Task 1: 温度選択後の安全チェックを実装

**Files:**
- Modify: `katrain/core/ai.py:3990-3993`

**コンテキスト:** 3987-3993行目の現在のコード:

```python
        # 重み付き選択（Invadeフェーズは温度で分布を平坦化）
        if phase_name == "Invade" and hunt_invasion_temperature != 1.0:
            inv_temp = 1.0 / hunt_invasion_temperature
            temp_moves = [(m, w ** inv_temp) for m, w in moves]
            selected = weighted_selection_without_replacement(temp_moves, 1)[0]
        else:
            selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]
        self.game.katrain.log(f"[HuntStrategy] Selected: {move.gtp()} ({phase_name})", OUTPUT_DEBUG)
```

利用可能な変数（すべてこの時点でスコープ内）:
- `move_infos`: Stage 2のクリーンクエリ結果（各手の`scoreLead`を含む）
- `best_score`: `player_sign * max(scoreLead)` — 現在プレイヤーにとっての最善スコア
- `player_sign`: `1`（Black）/ `-1`（White）
- `hunt_max_loss`: 設定値（19路: 6.0、13路: 4.0）— 3479行目で定義
- `best_gtp_by_score`: Stage 2スコア最善手のGTP文字列
- `moves`: 温度適用前の`(Move, weight)`リスト

- [ ] **Step 1: 安全チェックコードを追加**

`katrain/core/ai.py` の3990行目 `selected = weighted_selection_without_replacement(temp_moves, 1)[0]` の後、`move = selected[0]` の前に以下を挿入:

```python
            # 温度選択後の安全チェック: 選択手のlossがhunt_max_lossを超えたらtop weighted moveにフォールバック
            _sel_gtp = selected[0].gtp()
            _pt_score_map = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
            if _sel_gtp in _pt_score_map and _sel_gtp != best_gtp_by_score:
                _sel_loss = player_sign * (best_score - _pt_score_map[_sel_gtp])
                if _sel_loss >= hunt_max_loss:
                    _top_w_move = max(moves, key=lambda x: x[1])[0]
                    self.game.katrain.log(
                        f"[HuntStrategy] Post-temp safety: {_sel_gtp} loss={_sel_loss:.2f} >= {hunt_max_loss}, "
                        f"fallback to top weighted {_top_w_move.gtp()}",
                        OUTPUT_DEBUG,
                    )
                    selected = (_top_w_move, 0)
```

変更後の全体像（3986-4000行目）:

```python
        # 重み付き選択（Invadeフェーズは温度で分布を平坦化）
        if phase_name == "Invade" and hunt_invasion_temperature != 1.0:
            inv_temp = 1.0 / hunt_invasion_temperature
            temp_moves = [(m, w ** inv_temp) for m, w in moves]
            selected = weighted_selection_without_replacement(temp_moves, 1)[0]
            # 温度選択後の安全チェック: 選択手のlossがhunt_max_lossを超えたらtop weighted moveにフォールバック
            _sel_gtp = selected[0].gtp()
            _pt_score_map = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
            if _sel_gtp in _pt_score_map and _sel_gtp != best_gtp_by_score:
                _sel_loss = player_sign * (best_score - _pt_score_map[_sel_gtp])
                if _sel_loss >= hunt_max_loss:
                    _top_w_move = max(moves, key=lambda x: x[1])[0]
                    self.game.katrain.log(
                        f"[HuntStrategy] Post-temp safety: {_sel_gtp} loss={_sel_loss:.2f} >= {hunt_max_loss}, "
                        f"fallback to top weighted {_top_w_move.gtp()}",
                        OUTPUT_DEBUG,
                    )
                    selected = (_top_w_move, 0)
        else:
            selected = weighted_selection_without_replacement(moves, 1)[0]
        move = selected[0]
        self.game.katrain.log(f"[HuntStrategy] Selected: {move.gtp()} ({phase_name})", OUTPUT_DEBUG)
```

- [ ] **Step 2: 構文確認**

Run: `python -c "import ast; ast.parse(open('katrain/core/ai.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: Invadeフェーズ温度選択後の安全チェックを追加（hunt_max_loss超過時にtop weighted moveへフォールバック）"
```

---

### Task 2: 動作検証

- [ ] **Step 1: debug_level を有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `"debug_level": 1` に変更。

- [ ] **Step 2: 対局で検証**

`python -m katrain` で起動し、Hunt戦略（`hunt_invasion_temperature: 2.5`）で対局。

- [ ] **Step 3: ログで安全チェック発動を確認**

Grepパターン:
- 安全チェック発動: `Post-temp safety`
- 全着手: `Selected:`
- 大損失手の有無: KaTrain GUI の評価レポートで6目以上の損失手数を確認

期待結果:
- `Post-temp safety` が適宜発動し、6目以上損失の手がフォールバックされている
- 中盤までの6目以上損失手が従来の6回から大幅に減少

- [ ] **Step 4: debug_level を元に戻す**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 1` → `"debug_level": 0` に変更。
