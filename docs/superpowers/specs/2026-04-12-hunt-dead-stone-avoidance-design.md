# HuntStrategy Dead Stone Avoidance 設計書

- 日付: 2026-04-12
- 対象: `katrain/core/ai.py` `HuntStrategy`
- 関連issue: 2026-04-12 ログ `game_20260412_192231.log` 手172 W A10 の無意味手

## 1. 背景と問題

### 観測された問題

手172で HuntStrategy が A10 を選択した。

| 項目 | 値 |
|---|---|
| score_lead | +57.9（白の圧勝勢） |
| フェーズ | Invade（has_group_targets=False） |
| 盤面状況 | 白の左上石群（B10/C9/C10/D11/D12）が黒に包囲され完全死亡状態 |
| Top5 weight | K13=0.0107, T19=0.0059, **A10=0.0018**, C16=0.0016, M11=0.0015 |
| 選択 | A10（温度 2.0 の確率的サンプリングで上位から外れた手が選択） |

A10 は「既に死んでいる B10 の隣」に置かれる手で、白石群を救う効果は一切ない。黒があと2手打てば全部取られる局面で、人間の高段者なら絶対に打たない。

### 既存機構が機能しなかった理由

| 機構 | この局面での動作 |
|---|---|
| `hunt_winning_suppress_enabled` | ✅ 動作。KataGo 最善手 B5 を 0.0034 → 0.0010 に抑制。ただし **KataGo 最善1手のみ** を対象とするため、A10 のような下位候補には影響なし |
| `hunt_pursue_enabled` | ⚪ 未発動（Invade フェーズで `has_group_targets=False`）。仕様通り |
| `territory_avoid` | ⚪ 「自分の確定地」への打ち込みは抑制するが、「自分の死石周辺」は抑制対象外 |
| `Safety v2` | ⚪ A10 の loss=1.86 で閾値 4.0 未満のため非発動 |

### 人間の高段者の判断との差

人間の高段者は「自分の石が完全に死んでいる」と判断した領域には絶対に打たない。この判断は本質的に盤面の ownership（地の帰属）認識に基づく。KaTrain の既存「死石ハイライト」機能は `ownership × player_sign` を透明度に反映しているだけで、独立した死石判定アルゴリズムを持たない（`badukpan.py:244-250`）。つまり **raw ownership 値そのものが死石判定**として使える。

## 2. 目的と非目的

### 目的
HuntStrategy が「ownership 的に確実に死んでいる自分の石の周辺」に打つ無駄手を抑制し、人間高段者の判断（死石は見捨てる）に近づける。

### 非目的
- 劣勢時の勝負手としての死石復活は妨げない（厳格閾値 -0.85 で自然に除外される）
- 他戦略クラス（`SiegeStrategy`, `HuntDivergenceStrategy`）は変更しない（別タスクで検討）
- Endgame フェーズは現状維持

### 機構名
**Dead Stone Avoidance**

## 3. 検出アルゴリズム

### 入力
- `ownership_grid`: `var_to_grid(self.cn.ownership, board_size)` — 2次元配列、各セル値 ∈ [-1, +1]
- `player_sign`: Black=+1 / White=-1
- 盤面の石配置（`self.game.board` または `self.game.stones`）
- 候補手リスト `moves: [(Move, weight), ...]`
- 各候補手の損失 `loss_by_gtp`: Stage 2 クリーン `move_infos` から算出

### 判定ロジック

候補手 `(x, y)` について、**以下の (A) または (B) のいずれかを満たし、かつ (C) を満たす**場合に「死石周辺の無駄手」と判定:

- **(A) 候補手の座標それ自体が強く相手地**
  `ownership_grid[y][x] × player_sign < -0.85`

- **(B) 候補手の4近傍に死んだ自石がある**
  `(x±1, y)` または `(x, y±1)` の位置に自分の石があり、その石の `ownership × player_sign < -0.85`

- **(C) 損失がノイズ以上** `loss > 0.5`

### 擬似コード

```python
# 事前に自石座標セットを構築（HuntStrategy 内の既存パターンに準拠, ai.py:3937-3940）
current_player = self.cn.next_player
own_stone_coords = {
    s.coords for s in self.game.stones
    if s.player == current_player and s.coords
}

def is_dead_zone_move(move, ownership_grid, own_stone_coords, player_sign, loss, board_size):
    if loss <= _DEAD_LOSS_MIN:  # 0.5
        return False
    if move.coords is None:
        return False

    x, y = move.coords
    # 条件(A): 候補点自体が強く相手地
    own_xy = ownership_grid[y][x] * player_sign
    if own_xy < -_DEAD_OWNERSHIP_THRESHOLD:  # -0.85
        return True

    # 条件(B): 4近傍に死んだ自石
    bx, by = board_size
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nx, ny = x + dx, y + dy
        if not (0 <= nx < bx and 0 <= ny < by):
            continue
        if (nx, ny) not in own_stone_coords:
            continue
        own_neighbor = ownership_grid[ny][nx] * player_sign
        if own_neighbor < -_DEAD_OWNERSHIP_THRESHOLD:
            return True

    return False
```

### 減衰適用

```python
for i, (move, weight) in enumerate(moves):
    loss = loss_by_gtp.get(move.gtp(), None)
    if loss is None:
        continue  # loss 不明はスキップ（従来動作を維持）
    if is_dead_zone_move(move, ownership_grid, board, player_sign, loss, board_size):
        new_weight = weight * _DEAD_WEIGHT_FACTOR  # ×0.05
        moves[i] = (move, new_weight)
        penalized_count += 1
        log(f"[HuntStrategy] Dead stone avoid: {move.gtp()} "
            f"(own={own_xy:.2f}, loss={loss:.2f}) "
            f"weight {weight:.4f} -> {new_weight:.4f}")
```

### エッジケース

| ケース | 挙動 |
|---|---|
| `self.cn.ownership` が None | ブロック全体をスキップ、従来動作 |
| `move_infos` が空 | ブロック全体をスキップ |
| 候補手が move_infos に含まれない（loss 不明） | その候補のみスキップ |
| パス候補（coords=None） | 対象外 |
| loss ≤ 0.5 の手（取り手含む） | 条件(C)で除外 |

## 4. パイプライン統合

### 既存フロー（`ai.py` 4180行付近〜）

```
1. 候補手 weight 計算（humanPolicy × proximity × intensity × territory_avoid × focus_penalty）
2. パス候補追加
3. "N candidate moves (M filtered)" ログ
4. hunt_winning_suppress ブロック
5. Safety v2 ブロック
6. 候補なしフォールバック
7. 温度サンプリング / タイブレーク / 最終選択
```

### 挿入位置

**ステップ 3 と 4 の間**（`hunt_winning_suppress` ブロックの直前）:

```
3. "N candidate moves (M filtered)" ログ
       ↓
★ 新規: Dead Stone Avoidance ブロック ★
       ↓
4. hunt_winning_suppress ブロック
5. Safety v2 ブロック
...
```

### 挿入位置の根拠

1. **`hunt_winning_suppress` より前**: winning_suppress は特定1手（KataGo最善）のみを操作する微調整。dead stone avoidance は多数候補を無効化する基盤フィルタ。基盤を先に適用する。
2. **Safety v2 より前**: Safety v2 は top weighted の loss≥4.0 で強制差し替えする機構。dead stone 候補が top weighted になるのを先に防ぐ。
3. **温度サンプリング前**: サンプリング時点では既に weight が減衰済みなので、自然に選ばれなくなる。

## 5. 設定と GUI

### 新規設定項目

| キー | 型 | デフォルト | GUI | 備考 |
|---|---|---|---|---|
| `hunt_dead_stone_avoid_enabled` | bool | `true` | チェックボックス | 狩猟戦略: 死石周辺の無駄手を抑制 |

### 内部定数（ハードコード）

```python
_DEAD_OWNERSHIP_THRESHOLD = 0.85  # |own × player_sign| > 0.85 で死と判定
_DEAD_LOSS_MIN = 0.5              # loss > 0.5 で対象化
_DEAD_WEIGHT_FACTOR = 0.05        # weight 減衰係数
```

配置: `ai.py` モジュールレベル、既存の `_WINNING_THRESHOLD = 15.0` / `_WINNING_SUPPRESS_FACTOR = 0.3` の隣。

### 設定追加箇所（5ファイル）

| ファイル | 変更内容 |
|---|---|
| `katrain/core/ai.py` `HuntStrategy.generate_move()` | 設定読み込み、ログ、実装ブロック |
| `katrain/core/constants.py` `AI_OPTION_VALUES` | `"hunt_dead_stone_avoid_enabled": "bool"` 追加 |
| `katrain/config.json`（同梱） | Hunt 設定セクションに `"hunt_dead_stone_avoid_enabled": true` |
| `C:\Users\iwaki\.katrain\config.json`（ローカル） | 同上（メインセッションで直接 Edit） |
| `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po` → `.mo` | ヘルプテキスト翻訳。`python tools/compile_mo.py` 実行必須 |

### ログ出力仕様

```
[HuntStrategy] Dead stone avoid: A10 (own=-0.92, loss=1.86) weight 0.0018 -> 0.0001
[HuntStrategy] Dead stone avoid: A9  (own=-0.90, loss=2.14) weight 0.0006 -> 0.0000
[HuntStrategy] Dead stone avoid: 3 moves penalized (scanned 13 candidates)
```

ownership データ欠損時:
```
[HuntStrategy] Dead stone avoid: skipped (no ownership data)
```

`.claude/rules/log-analysis.md` に `Dead stone avoid:` パターンを追加。

## 6. 検証方法

### 6.1 ピンポイント検証（CLI デバッグツール）

```bash
# A10 問題局面の再現（有効/無効の比較）
python -m katrain_debug --sgf "sgfout/KaTrain_人間 (通常対局) vs AI (狩猟戦略) 2026-04-12 19 22 31.sgf" \
  --move 171 --strategy hunt --output json \
  --settings hunt_dead_stone_avoid_enabled=true

python -m katrain_debug --sgf "sgfout/..." --move 171 --strategy hunt --output json \
  --settings hunt_dead_stone_avoid_enabled=false
```

**成功基準**:
- 有効時: A10 の weight が大幅減衰、top5 から外れる、選択されない
- 無効時: 従来通り A10 が top5 に残る

### 6.2 バッチ評価での一致率・損失影響

```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy hunt --batch --player W \
  --settings hunt_dead_stone_avoid_enabled=true
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy hunt --batch --player W \
  --settings hunt_dead_stone_avoid_enabled=false
```

**成功基準**:
- 平均損失が悪化しない
- Top1/Top5 一致率が有意に悪化しない
- Notable Divergences から死石周辺手が消える

### 6.3 実対局ログの Grep 検証

```bash
# 発動局面の統計
grep "Dead stone avoid:" C:/Users/iwaki/.katrain/logs/game_YYYYMMDD_*.log
grep "Dead stone avoid:.*penalized" C:/Users/iwaki/.katrain/logs/*.log | wc -l
```

**成功基準**:
- 発動局面が「確実に死石がある終盤」に集中
- 序盤〜中盤での誤発動ゼロ（ownership 閾値 -0.85 は序盤で満たされないため）

### 6.4 劣勢局面での誤爆チェック

劣勢局面（白が -10 目以下）の SGF で検証:

```bash
python -m katrain_debug --sgf LOSING_GAME.sgf --strategy hunt --batch --player W
```

**成功基準**:
- 勝負手（loss 0〜0.3）が抑制されない（条件(C)で自動除外）
- 形勢不明の活き死にでは ownership < -0.85 が満たされず発動しない

## 7. 関連ファイル更新

- `.claude/rules/ai-parameters.md`: 狩猟戦略パラメータ表に `hunt_dead_stone_avoid_enabled` 行追加
- `.claude/rules/ai-humanstyle.md` or `.claude/rules/log-analysis.md`: `Dead stone avoid:` ログパターン追加
- `CLAUDE.md`: 現在のパラメータ値セクションは `.claude/rules/ai-parameters.md` を参照する方式のため、変更不要

## 8. 決定ログ

| 質問 | 選択 | 根拠 |
|---|---|---|
| Q1 検出方法 | (d) 候補点 OR 4近傍死石 | 候補点が相手地化された空点も、死石の補強もどちらも捕捉 |
| Q2 ownership閾値 | -0.85 | 条件「将来利用されない」を満たす厳格値。コウ等の復活余地を残さない |
| Q3 loss 条件 | `loss > 0.5` | ユーザー条件「損失でしかない」と対応。既存「緑判定」境界と整合 |
| Q4 減衰係数 | ×0.05 | territory_avoid(×0.1) より強い。閾値厳格なので強めでよい |
| Q5 (b)近傍範囲 | 距離1・4近傍 | 斜め/距離2は攻めの足場手を誤抑制するリスク |
| Q6 発動条件 | ownership 成熟度で自然ゲート | 手数条件不要。閾値が厳格なので序盤誤発動せず |
| Q7 設定化 | GUIトグルのみ、閾値ハードコード | シンプル。hunt_winning_suppress_enabled と同パターン |
| Q8 デフォルト・範囲 | True / HuntStrategy のみ | 明らかな悪手抑制なのでON、他戦略は別タスク |
