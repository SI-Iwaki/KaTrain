# HuntStrategy Dead Stone Avoidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HuntStrategy に「ownershipで確実に死んでいる自分の石の周辺に打つ無駄手」を検出して候補手 weight を ×0.05 に減衰する機構を追加する。GUI トグル `hunt_dead_stone_avoid_enabled`（デフォルト True）で制御。

**Architecture:** `HuntStrategy.generate_move()` 内、候補 weight 計算完了後〜`hunt_winning_suppress` ブロックの直前に新ブロックを挿入。判定は 2 条件の OR (候補点自体の ownership OR 4 近傍の死自石の ownership) ＋ loss > 0.5 の AND。閾値・係数は module 定数でハードコード。

**Tech Stack:** Python 3.12 / KataGo ownership データ / 既存 HuntStrategy パイプライン

**関連設計書:** `docs/superpowers/specs/2026-04-12-hunt-dead-stone-avoidance-design.md`

---

## File Structure

| ファイル | 役割 | 変更タイプ |
|---|---|---|
| `katrain/core/ai.py` | HuntStrategy 内の定数・設定読み込み・実装ブロック | Modify |
| `katrain/core/constants.py` | `AI_OPTION_VALUES` と `AI_OPTION_ORDER` への追加 | Modify |
| `katrain/config.json` | パッケージ同梱のデフォルト値 | Modify |
| `C:\Users\iwaki\.katrain\config.json` | ユーザーローカル設定（GUI表示のため必須） | Modify |
| `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | 日本語ヘルプテキスト | Modify |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 英語ヘルプテキスト | Modify |
| `.mo` ファイル | `python tools/compile_mo.py` で再コンパイル | Generated |
| `.claude/rules/ai-parameters.md` | パラメータ表の更新 | Modify |
| `tests/test_hunt_dead_stone.py` | 判定関数のユニットテスト | Create |

---

## Task 1: 判定関数のユニットテストを作成

**Files:**
- Create: `tests/test_hunt_dead_stone.py`

`is_dead_zone_move` 相当の純粋関数をテストしやすい形に設計する。HuntStrategy から切り出してユニットテスト可能にすることで、盤面を使ったテストが書ける。

- [ ] **Step 1: Write the failing test file**

```python
# tests/test_hunt_dead_stone.py
"""HuntStrategy Dead Stone Avoidance judgment tests."""
import pytest

from katrain.core.ai import (
    _DEAD_OWNERSHIP_THRESHOLD,
    _DEAD_LOSS_MIN,
    _DEAD_WEIGHT_FACTOR,
    is_dead_zone_move,
)


def make_grid(size, fills):
    """ownership grid を構築するヘルパ。fills: {(x,y): value}"""
    grid = [[0.0 for _ in range(size)] for _ in range(size)]
    for (x, y), v in fills.items():
        grid[y][x] = v
    return grid


def test_condition_a_candidate_point_strong_opponent_triggers():
    """候補点自体が player_sign 視点で -0.85 未満なら発動。"""
    # 白番 (player_sign=-1), A10=(0,9) の ownership=+0.92 (黒寄り)
    # 白視点: 0.92 * -1 = -0.92 < -0.85 → 発動
    grid = make_grid(19, {(0, 9): 0.92})
    own_coords = set()  # 隣接自石なし
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=own_coords,
        player_sign=-1,
        loss=1.86,
        board_size=(19, 19),
    ) is True


def test_condition_b_dead_neighbor_own_stone_triggers():
    """候補点は中立だが4近傍に死んだ自石があれば発動。"""
    # 白番, 候補A10=(0,9) ownership=0 (中立)
    # 隣 B10=(1,9) は自石, ownership=+0.90 (黒寄り=白視点 -0.90 < -0.85)
    grid = make_grid(19, {(0, 9): 0.0, (1, 9): 0.90})
    own_coords = {(1, 9)}
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=own_coords,
        player_sign=-1,
        loss=1.86,
        board_size=(19, 19),
    ) is True


def test_low_loss_exempts_even_dead_zone():
    """loss <= 0.5 なら死石周辺でも対象外（条件C で除外）。"""
    grid = make_grid(19, {(0, 9): 0.92})
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=-1,
        loss=0.3,
        board_size=(19, 19),
    ) is False


def test_weak_ownership_does_not_trigger():
    """|ownership|<0.85 なら発動しない（閾値厳格）。"""
    grid = make_grid(19, {(0, 9): 0.70})  # 白視点 -0.70 > -0.85
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=-1,
        loss=2.0,
        board_size=(19, 19),
    ) is False


def test_live_own_neighbor_does_not_trigger():
    """隣接自石が生きていれば条件(B)は満たさない。"""
    # 候補点自体は中立、隣の自石も生きている（白視点 +0.5）
    grid = make_grid(19, {(0, 9): 0.0, (1, 9): -0.5})  # -0.5 * -1 = +0.5
    own_coords = {(1, 9)}
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=own_coords,
        player_sign=-1,
        loss=2.0,
        board_size=(19, 19),
    ) is False


def test_pass_move_is_exempt():
    """パス (coords=None) は対象外。"""
    grid = make_grid(19, {})
    assert is_dead_zone_move(
        move_coords=None,
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=-1,
        loss=2.0,
        board_size=(19, 19),
    ) is False


def test_black_player_sign_condition_a():
    """黒番 (player_sign=+1) の場合、ownership=-0.92 (白寄り) で発動。"""
    grid = make_grid(19, {(0, 9): -0.92})  # 黒視点: -0.92 * +1 = -0.92
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=+1,
        loss=2.0,
        board_size=(19, 19),
    ) is True


def test_out_of_bounds_neighbors_ignored():
    """盤外の近傍は無視される（エッジ A10 など）。"""
    # A10 = (0, 9): x=0 なので x=-1 は盤外
    # 候補点自体は中立、盤内の近傍 B10=(1,9) は空（own_coordsに含まれない）
    grid = make_grid(19, {(0, 9): 0.0})
    assert is_dead_zone_move(
        move_coords=(0, 9),
        ownership_grid=grid,
        own_stone_coords=set(),
        player_sign=-1,
        loss=2.0,
        board_size=(19, 19),
    ) is False


def test_constants_values():
    """ハードコード定数の値が設計通り。"""
    assert _DEAD_OWNERSHIP_THRESHOLD == 0.85
    assert _DEAD_LOSS_MIN == 0.5
    assert _DEAD_WEIGHT_FACTOR == 0.05
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hunt_dead_stone.py -v`

Expected: `ImportError: cannot import name '_DEAD_OWNERSHIP_THRESHOLD' from 'katrain.core.ai'`（定数・関数未定義）

- [ ] **Step 3: Commit**

```bash
git add tests/test_hunt_dead_stone.py
git commit -m "test: HuntStrategy Dead Stone Avoidance 判定関数のユニットテスト追加"
```

---

## Task 2: 定数と判定関数の実装

**Files:**
- Modify: `katrain/core/ai.py` (モジュールレベル定数の近く、`HuntStrategy` クラスの外側)

既存の定数 `_WINNING_THRESHOLD` / `_WINNING_SUPPRESS_FACTOR` は `HuntStrategy.generate_move()` の関数内定数として定義されている（line 3676-3677）。本タスクでは同じパターンで定数を関数内に置きつつ、判定関数 `is_dead_zone_move` はテスト可能性のためモジュールレベルに配置する。

- [ ] **Step 1: モジュールレベル定数と判定関数を追加**

`katrain/core/ai.py` の既存 import 群の直後（line 30 付近、`register_strategy` デコレータ定義より前）に以下を追加:

```python
# --- Hunt Dead Stone Avoidance 定数 ---
_DEAD_OWNERSHIP_THRESHOLD = 0.85  # |ownership * player_sign| > 0.85 で死と判定
_DEAD_LOSS_MIN = 0.5              # loss > 0.5 でなければ対象外
_DEAD_WEIGHT_FACTOR = 0.05        # 検出時のweight減衰係数


def is_dead_zone_move(move_coords, ownership_grid, own_stone_coords, player_sign, loss, board_size):
    """候補手が『死んだ自石の周辺の無駄手』かを判定する。

    Args:
        move_coords: (x, y) タプル、またはパスの場合 None
        ownership_grid: 2次元配列 [y][x] → [-1, +1] の KataGo ownership
        own_stone_coords: 現プレイヤー自石の座標 set {(x, y), ...}
        player_sign: +1 (Black) or -1 (White)
        loss: 候補手の損失（目数、正=損）
        board_size: (bx, by) タプル

    Returns:
        bool: True なら減衰対象
    """
    if move_coords is None:
        return False
    if loss <= _DEAD_LOSS_MIN:
        return False

    x, y = move_coords
    bx, by = board_size

    # 条件(A): 候補点自体が強く相手地
    own_xy = ownership_grid[y][x] * player_sign
    if own_xy < -_DEAD_OWNERSHIP_THRESHOLD:
        return True

    # 条件(B): 4近傍に死んだ自石
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

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_hunt_dead_stone.py -v`

Expected: 全 9 テストが PASS

- [ ] **Step 3: Commit**

```bash
git add katrain/core/ai.py
git commit -m "feat: is_dead_zone_move 判定関数とHunt死石回避定数を実装"
```

---

## Task 3: HuntStrategy に設定読み込みを追加

**Files:**
- Modify: `katrain/core/ai.py` line 3678 付近（既存 `hunt_winning_suppress` 読み込みの直後）

- [ ] **Step 1: 設定読み込み行を追加**

`katrain/core/ai.py` line 3678 の直後に以下を挿入:

```python
        hunt_winning_suppress = self.settings.get("hunt_winning_suppress_enabled", False)
        hunt_dead_stone_avoid = self.settings.get("hunt_dead_stone_avoid_enabled", True)
```

（既存の `hunt_winning_suppress = ...` 行の後に1行追加するのみ）

- [ ] **Step 2: 起動ログに含める**

同じ箇所の `[HuntStrategy] Starting move generation` ログ（line 3680-3689）に追加情報なし（ログの横幅肥大を避ける）。代わりに実装ブロック内でログ出力する。

- [ ] **Step 3: 既存テストが壊れていないことを確認**

Run: `pytest tests/test_hunt_dead_stone.py -v`

Expected: PASS（import エラーが出ないこと）

- [ ] **Step 4: Commit**

```bash
git add katrain/core/ai.py
git commit -m "feat: hunt_dead_stone_avoid_enabled 設定を HuntStrategy で読み込み"
```

---

## Task 4: Dead Stone Avoidance ブロックを HuntStrategy に挿入

**Files:**
- Modify: `katrain/core/ai.py` line 4188-4190 の間（`N candidate moves` ログ直後、`hunt_winning_suppress` ブロック直前）

`ai.py` line 4188 は以下:
```python
        self.game.katrain.log(
            f"[HuntStrategy] {len(moves)} candidate moves ({filtered_count} filtered)",
            OUTPUT_DEBUG,
        )

        # --- 勝勢時の最善手weight抑制 ---   ← line 4190
```

この間に新ブロックを挿入する。

- [ ] **Step 1: Dead Stone Avoidance ブロックを追加**

line 4188 (上記ログ出力) の直後、line 4190 (`# --- 勝勢時の最善手weight抑制 ---`) の直前に以下を挿入:

```python
        # --- 死石周辺の無駄手抑制 (Dead Stone Avoidance) ---
        if hunt_dead_stone_avoid and moves and move_infos and self.cn.ownership:
            _ownership_grid_dsa = var_to_grid(self.cn.ownership, board_size)
            _own_stone_coords_dsa = {
                s.coords for s in self.game.stones
                if s.player == self.cn.next_player and s.coords
            }
            _score_by_gtp_dsa = {mi.get("move", ""): mi.get("scoreLead", 0) for mi in move_infos}
            _penalized_count = 0
            for i, (m, w) in enumerate(moves):
                gtp = m.gtp()
                if gtp not in _score_by_gtp_dsa or best_score is None:
                    continue
                loss_m = player_sign * (best_score - _score_by_gtp_dsa[gtp])
                if is_dead_zone_move(
                    move_coords=m.coords,
                    ownership_grid=_ownership_grid_dsa,
                    own_stone_coords=_own_stone_coords_dsa,
                    player_sign=player_sign,
                    loss=loss_m,
                    board_size=board_size,
                ):
                    own_val = (
                        _ownership_grid_dsa[m.coords[1]][m.coords[0]] * player_sign
                        if m.coords else 0.0
                    )
                    new_w = w * _DEAD_WEIGHT_FACTOR
                    moves[i] = (m, new_w)
                    _penalized_count += 1
                    self.game.katrain.log(
                        f"[HuntStrategy] Dead stone avoid: {gtp} "
                        f"(own={own_val:.2f}, loss={loss_m:.2f}) "
                        f"weight {w:.4f} -> {new_w:.4f}",
                        OUTPUT_DEBUG,
                    )
            if _penalized_count > 0:
                self.game.katrain.log(
                    f"[HuntStrategy] Dead stone avoid: {_penalized_count} moves penalized "
                    f"(scanned {len(moves)} candidates)",
                    OUTPUT_DEBUG,
                )
        elif hunt_dead_stone_avoid and (not self.cn.ownership or not move_infos):
            self.game.katrain.log(
                "[HuntStrategy] Dead stone avoid: skipped (no ownership/move_infos data)",
                OUTPUT_DEBUG,
            )

```

- [ ] **Step 2: 手動動作確認 (起動のみ)**

`python -m katrain` で起動、AI 対局を開始できることを確認（機能テストは後のタスクで実施）。

Expected: 起動成功、エラーなし。

- [ ] **Step 3: Commit**

```bash
git add katrain/core/ai.py
git commit -m "feat: HuntStrategy に Dead Stone Avoidance ブロックを挿入

候補手 weight 計算後・hunt_winning_suppress 直前に、
ownership_grid と 4 近傍自石を使って死石周辺の無駄手を検出、
weight × 0.05 に減衰する。loss > 0.5 との AND で勝負手は除外。"
```

---

## Task 5: GUI 設定登録（constants.py）

**Files:**
- Modify: `katrain/core/constants.py` line 180（`AI_OPTION_VALUES`）と line 226（`AI_OPTION_ORDER`）

- [ ] **Step 1: `AI_OPTION_VALUES` に追加**

`katrain/core/constants.py` line 180 `"hunt_winning_suppress_enabled": "bool",` の直後に追加:

```python
    "hunt_winning_suppress_enabled": "bool",
    "hunt_dead_stone_avoid_enabled": "bool",
    "hunt_dodge_max_loss": [x / 2 for x in range(1, 7)],  # 0.5〜3.0（0.5刻み）
```

- [ ] **Step 2: `AI_OPTION_ORDER` に追加**

`katrain/core/constants.py` line 226 `"hunt_winning_suppress_enabled": 28,` の直後に追加:

```python
    "hunt_winning_suppress_enabled": 28,
    "hunt_dead_stone_avoid_enabled": 29,
    "hunt_dodge_max_loss": 0,
```

- [ ] **Step 3: 起動して GUI 表示確認**

`python -m katrain` で起動 → メインメニューから AI 設定画面を開く → 狩猟戦略セクションに「hunt_dead_stone_avoid_enabled」のチェックボックスが表示されることを確認（i18n 未対応のため英語キー名のまま表示される、それは Task 7 で修正）。

Expected: チェックボックスが表示される。クラッシュしない（`GridLayoutException: Too many children` が出ないことを確認、max_options=15 未満）。

- [ ] **Step 4: Commit**

```bash
git add katrain/core/constants.py
git commit -m "feat: hunt_dead_stone_avoid_enabled を GUI 設定に登録"
```

---

## Task 6: config.json（パッケージ + ユーザーローカル）にデフォルト値追加

**Files:**
- Modify: `katrain/config.json` line 186 付近（`ai:hunt` セクション）
- Modify: `C:\Users\iwaki\.katrain\config.json`（`ai:hunt` セクション）

> **重要**: CLAUDE.md の警告に従い、ユーザーローカル config.json はメインセッションで直接 Edit する（サブエージェントに委任しない）。

- [ ] **Step 1: パッケージ同梱の config.json を編集**

`katrain/config.json` line 186 `"hunt_winning_suppress_enabled": false` を変更:

```json
            "hunt_pursue_enabled": true,
            "hunt_winning_suppress_enabled": false,
            "hunt_dead_stone_avoid_enabled": true
```

（カンマの位置に注意 — `hunt_winning_suppress_enabled` の行末にカンマを追加し、新行は末尾なのでカンマなし）

- [ ] **Step 2: ユーザーローカル config.json を編集（メインセッションで直接）**

`C:\Users\iwaki\.katrain\config.json` の `ai:hunt` セクションに同じキーを追加:

```json
            "hunt_pursue_enabled": true,
            "hunt_winning_suppress_enabled": <既存値>,
            "hunt_dead_stone_avoid_enabled": true
```

既存値を上書きしないよう確認すること（`hunt_winning_suppress_enabled` が true だったら true のまま残す）。

- [ ] **Step 3: 起動して GUI で設定値を確認**

`python -m katrain` で起動 → AI 設定画面の狩猟戦略を開き → `hunt_dead_stone_avoid_enabled` のチェックが ON になっていることを確認。

Expected: チェックボックス ON（= デフォルト true 反映）。

- [ ] **Step 4: Commit（パッケージ config.json のみ。ユーザーローカルは Git 管理外）**

```bash
git add katrain/config.json
git commit -m "feat: hunt_dead_stone_avoid_enabled のデフォルト値(true)を追加"
```

---

## Task 7: i18n ヘルプテキスト追加と .mo 再コンパイル

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` line 1082-1084 付近
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` line 991-993 付近

- [ ] **Step 1: 日本語 .po を編集**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `hunt_winning_suppress_enabled` ヘルプ文の直後（line 1084 の `"棋風を維持しつつAI最善手一致率を下げます。"` の次）に追加:

変更前:
```
"hunt_winning_suppress_enabled: 勝勢時の最善手抑制。"
"15目以上リードしている場合、KataGo最善手の重みを低減し、"
"棋風を維持しつつAI最善手一致率を下げます。"
```

変更後:
```
"hunt_winning_suppress_enabled: 勝勢時の最善手抑制。"
"15目以上リードしている場合、KataGo最善手の重みを低減し、"
"棋風を維持しつつAI最善手一致率を下げます。\n"
"hunt_dead_stone_avoid_enabled: 死石周辺の無駄手を抑制。"
"ownership でほぼ確実に死んでいると判定された自石の周辺で、"
"損失が発生する手の重みを大きく減衰し、人間高段者のように無駄手を避けます。"
```

- [ ] **Step 2: 英語 .po を編集**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の `hunt_winning_suppress_enabled` ヘルプ文の直後（line 993 の `"to lower the top-move match rate while maintaining playing style."` の次）に追加:

変更前:
```
"hunt_winning_suppress_enabled: Winning position best-move suppression. "
"When leading by 15+ points, reduces the weight of KataGo's best move "
"to lower the top-move match rate while maintaining playing style."
```

変更後:
```
"hunt_winning_suppress_enabled: Winning position best-move suppression. "
"When leading by 15+ points, reduces the weight of KataGo's best move "
"to lower the top-move match rate while maintaining playing style.\n"
"hunt_dead_stone_avoid_enabled: Avoid futile moves near dead stones. "
"Heavily down-weights candidate moves on or adjacent to the player's own stones "
"that ownership confirms as dead, mimicking how strong human players ignore dead stones."
```

- [ ] **Step 3: .mo を再コンパイル**

Run: `python tools/compile_mo.py`

Expected: `Compiled katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo` などの出力。エラーなし。

- [ ] **Step 4: 起動してヘルプテキスト確認**

`python -m katrain` で起動 → AI 設定画面の狩猟戦略 → `hunt_dead_stone_avoid_enabled` の行にマウスオーバー、ツールチップに日本語/英語の説明が表示されることを確認。

Expected: 翻訳済みヘルプが表示される。

- [ ] **Step 5: Commit**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "feat: hunt_dead_stone_avoid_enabled のi18nヘルプテキストを追加（en/jp）"
```

---

## Task 8: ピンポイント検証（問題局面の再現確認）

**Files:**
- Run only（コード変更なし）

設計書 § 6.1 の検証を実施する。問題局面 SGF を使い、有効時/無効時の挙動差を確認する。

- [ ] **Step 1: 有効時の挙動を取得**

Run:
```bash
python -m katrain_debug \
  --sgf "sgfout/KaTrain_人間 (通常対局) vs AI (狩猟戦略) 2026-04-12 19 22 31.sgf" \
  --move 171 --strategy hunt --output json \
  --settings hunt_dead_stone_avoid_enabled=true 2>/dev/null > /tmp/dsa_on.json
```

- [ ] **Step 2: 無効時の挙動を取得**

Run:
```bash
python -m katrain_debug \
  --sgf "sgfout/KaTrain_人間 (通常対局) vs AI (狩猟戦略) 2026-04-12 19 22 31.sgf" \
  --move 171 --strategy hunt --output json \
  --settings hunt_dead_stone_avoid_enabled=false 2>/dev/null > /tmp/dsa_off.json
```

- [ ] **Step 3: 結果を比較**

Run:
```bash
python -c "
import json
on = json.load(open('/tmp/dsa_on.json'))
off = json.load(open('/tmp/dsa_off.json'))
print('ON  top5:', [(m['gtp'], round(m['weight'], 5)) for m in on.get('top_moves', [])[:5]])
print('OFF top5:', [(m['gtp'], round(m['weight'], 5)) for m in off.get('top_moves', [])[:5]])
"
```

Expected:
- **ON** の出力に A10 が含まれていない、または weight が 0.0001 付近（元の 0.0018 × 0.05 = 0.00009）に減衰している
- **OFF** の出力では A10 が top5 に残る（従来動作）
- ON 側のログに `Dead stone avoid: A10` 行が存在する

- [ ] **Step 4: 結果を記録**

検証結果を `docs/superpowers/plans/2026-04-12-hunt-dead-stone-avoidance-verification.md` に簡潔に書き出し（任意）。コミット不要。

- [ ] **Step 5: 期待通りでない場合の対応**

期待通りでない場合:
- `/tmp/dsa_on.json` の思考過程を確認、`Dead stone avoid` ログが出ているか
- A10 の ownership 値・loss 値が設計閾値を満たしているか確認
- 必要なら Task 4 の実装に戻って修正、Task 2 テストを追加

**このタスクでは検証のみ。追加の実装が必要なら別タスクとして切り出す。**

---

## Task 9: バッチ評価で回帰チェック

**Files:**
- Run only（コード変更なし）

設計書 § 6.2 の検証。平均損失・一致率の悪化がないか確認。

- [ ] **Step 1: 無効時のバッチ評価**

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy hunt --batch --player W \
  --settings hunt_dead_stone_avoid_enabled=false 2>/dev/null > /tmp/batch_off.txt
```

- [ ] **Step 2: 有効時のバッチ評価**

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy hunt --batch --player W \
  --settings hunt_dead_stone_avoid_enabled=true 2>/dev/null > /tmp/batch_on.txt
```

- [ ] **Step 3: 結果を比較**

Run:
```bash
diff <(grep -E "Top1|Top5|Mean loss|Accuracy" /tmp/batch_off.txt) \
     <(grep -E "Top1|Top5|Mean loss|Accuracy" /tmp/batch_on.txt)
```

Expected:
- 平均損失 (Mean loss) が悪化していない（同等または改善）
- Top1 / Top5 一致率が有意に悪化していない（1%程度の変動は許容）
- Notable Divergences から死石周辺手が消えている

期待通りでない場合はこの Task で原因調査、必要なら実装修正（Task 4 に戻る）。

**このタスクでは検証のみ。**

---

## Task 10: ドキュメント更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（パラメータ表に追加）

> **重要**: CLAUDE.md の「やってはいけないこと」に従い、`.claude/rules/` 配下の編集は `dontAsk` で拒否されることがある。その場合は **サブエージェント (Agent tool) 経由で編集**する。

- [ ] **Step 1: `.claude/rules/ai-parameters.md` の狩猟戦略テーブルを更新**

狩猟戦略 (HuntStrategy) の「スコア適応型損失制御」セクションの直前、既存パラメータ表の末尾に追加:

```markdown
| hunt_dead_stone_avoid_enabled | true | true | 死石周辺の無駄手抑制。ownership × player_sign < -0.85 の自石または近傍で loss > 0.5 の候補手を weight×0.05 に減衰（GUI: チェックボックス） |
```

Edit が直接拒否された場合:
```
Agent tool (general-purpose subagent) に「.claude/rules/ai-parameters.md の HuntStrategy パラメータ表に hunt_dead_stone_avoid_enabled 行を追加してコミット」と依頼する
```

- [ ] **Step 2: `.claude/rules/log-analysis.md` があれば Dead stone avoid パターンを追加（ファイルが存在する場合のみ）**

Run:
```bash
ls .claude/rules/log-analysis.md 2>/dev/null && echo EXISTS || echo SKIP
```

EXISTS の場合、HuntStrategy のログパターン例に `Dead stone avoid:` を追加。SKIP ならこの Step をスキップ。

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/ai-parameters.md
# log-analysis.md を更新した場合は git add .claude/rules/log-analysis.md
git commit -m "docs: hunt_dead_stone_avoid_enabled のパラメータテーブル行を追加"
```

---

## Task 11: 最終統合確認

**Files:**
- Run only

- [ ] **Step 1: 全テスト実行**

Run:
```bash
pytest --ignore=tests/test_ai.py -v
```

Expected: 新規追加した `test_hunt_dead_stone.py` を含め全テスト PASS。

- [ ] **Step 2: black フォーマッタ**

Run:
```bash
black katrain/core/ai.py katrain/core/constants.py tests/test_hunt_dead_stone.py
```

Expected: `1 file reformatted` もしくは `already well formatted`。

- [ ] **Step 3: フォーマット修正があればコミット**

```bash
git diff --quiet || git commit -am "style: black フォーマッタ適用"
```

- [ ] **Step 4: 実対局で最終動作確認**

`python -m katrain` を起動し、狩猟戦略で AI 対局を1局実施。ログを確認:

```bash
grep "Dead stone avoid:" C:/Users/iwaki/.katrain/logs/game_*.log | tail -20
```

Expected:
- 勝勢になる局面で `Dead stone avoid:` ログが出現する（死石が発生する局面で）
- 序盤（手数 20 以下）では発動していない
- 発動時は loss > 0.5 の手のみが対象

- [ ] **Step 5: 成果物確認**

- [ ] `tests/test_hunt_dead_stone.py` - 9 テスト PASS
- [ ] `katrain/core/ai.py` - 定数・判定関数・実装ブロック追加済み
- [ ] `katrain/core/constants.py` - `AI_OPTION_VALUES` + `AI_OPTION_ORDER` に登録済み
- [ ] `katrain/config.json` - デフォルト値 `true` で追加済み
- [ ] `C:\Users\iwaki\.katrain\config.json` - ユーザーローカルにも追加済み
- [ ] `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po` - ヘルプテキスト追加済み、.mo再コンパイル済み
- [ ] `.claude/rules/ai-parameters.md` - パラメータ表更新済み
- [ ] A10 問題局面で手が変わることを確認済み（Task 8）
- [ ] バッチ評価で回帰していないことを確認済み（Task 9）

---

## Self-Review Notes

**Spec coverage:** 設計書 § 1〜§ 7 の各要件に対応するタスク:
- § 1 背景/目的 → Plan header
- § 2 目的/非目的 → Task 1-4 で HuntStrategy のみに限定実装
- § 3 検出アルゴリズム → Task 1-2（テスト+実装）
- § 4 パイプライン統合位置 → Task 4
- § 5 設定とGUI → Task 5-7
- § 6 検証方法 → Task 8-9, 11
- § 7 関連ファイル更新 → Task 10
- § 8 決定ログ → Plan header および Task 2 の定数値で反映

**Placeholder scan:** No TBD/TODO/fill-in-later found. All code blocks contain complete implementations.

**Type consistency:**
- `is_dead_zone_move` シグネチャは Task 1 テストと Task 2 実装で一致（`move_coords`, `ownership_grid`, `own_stone_coords`, `player_sign`, `loss`, `board_size`）
- 定数名 `_DEAD_OWNERSHIP_THRESHOLD` / `_DEAD_LOSS_MIN` / `_DEAD_WEIGHT_FACTOR` は全タスクで統一
- 設定キー `hunt_dead_stone_avoid_enabled` は Task 3/5/6/7/10 で統一
