# 詰碁 ownership 着手選択（ai:tsumego）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 詰碁キャプチャの黒番AIが、盤全体の目数ではなく対象石群の死活（ownership の変化量）で手を選ぶようにする。

**Architecture:** 目数ガードで大損の手を弾いてから、候補手ごとの ownership 変化量が最大の手を選ぶ。判定ロジックは Game に依存しない純関数2つに切り出して単体テストし、`AIStrategy` のサブクラスから呼ぶ。既存戦略・枠ロジック・リージョン算出には触れない。

**Tech Stack:** Python 3.12 / pytest。`katrain/core/ai.py` は Kivy 非依存でテストから import 可能。

## Global Constraints

- 設計書: `docs/superpowers/specs/2026-07-29-tsumego-ownership-design.md`
- コミットメッセージは**日本語**、Conventional Commits 形式（`feat:`, `fix:`, `refactor:`, `test:`）
- `black` を既存ファイル全体に走らせない（コードベースが未整形のため巨大差分になる）。line-length=120 に手で合わせる
- コメント・docstring は日本語（周囲のスタイルに合わせる）
- **既存の戦略クラスを変更しない**。`DefaultStrategy` / `OwnershipBaseStrategy` / `SimpleOwnershipStrategy` / `SettleStonesStrategy` はそのまま
- 既存テストの期待値を1つも変更しない（現在 304 tests pass）
- テスト実行は `python -m pytest tests/ --ignore=tests/test_ai.py`（`test_ai.py` は humanSL モデルが必要なため除外）
- `C:\Users\iwaki\.katrain\config.json`（ユーザーのローカル設定）はサブエージェントに編集させない。Task 3 で担当者が直接行う

## 既存コードの重要な事実（実装前に把握すること）

- `AIStrategy.__init__(self, game, ai_settings)` が `self.game` / `self.settings` / `self.cn` を設定する
- `generate_ai_move` は `settings = self.config(f"ai/{mode}")`（`__main__.py:432`）で渡すので、
  **`config.json` に `"ai:tsumego"` キーが無いと settings が None になる**
- `self.cn.ownership` は ROOT の ownership 配列（`game_node.py:306`）
- 候補手ごとの ownership は `self.cn.analysis["moves"][gtp]["ownership"]`。
  `analysis_dumps` が捨てるのは SGF 保存時だけでメモリ上には残る
- `var_to_grid(array, (size_x, size_y))` は `grid[y][x]` を返し、y は**下origin**。
  配列は上の行から順（y 降順）に詰まっている
- `Move.coords` は `(x, y)`。よって `grid[y][x]` で引ける
- `self.cn.player_sign(player)` が黒 `+1` / 白 `-1` を返す
- **`DefaultStrategy` の `Move(is_pass=True, player=...)` は誤り**（`Move.__init__` は
  `(coords=None, player="B")` で `is_pass` は property）。パスを作るなら `Move(coords=None, player=...)`。
  この誤りを真似しないこと
- `AI_SETTLE_STONES` は `AI_STRATEGIES` にも `AI_STRATEGIES_RECOMMENDED_ORDER` にも登録されていない
  「プログラムからのみ設定する戦略」の前例。`ai:tsumego` も同じ扱いにする。
  `tests/test_ai.py:14` が `set(AI_STRATEGIES_RECOMMENDED_ORDER) == set(AI_STRATEGIES)` を
  アサートしているため、**片方だけに足すと壊れる**

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `katrain/core/ai.py` | 純関数2つ + `TsumegoOwnershipStrategy` | 追記のみ |
| `katrain/core/constants.py` | `AI_TSUMEGO` 定数と `AI_STRENGTH` 登録 | 追記のみ |
| `katrain/config.json` | `ai:tsumego` の既定設定 | 追記のみ |
| `katrain/__main__.py` | キャプチャ時の黒番を `AI_TSUMEGO` に | 1行 |
| `C:\Users\iwaki\.katrain\config.json` | 同設定 + `_enable_ownership` | Task 3 |
| `tests/test_tsumego_ownership.py` | 純関数の単体テスト | 新規 |

---

### Task 1: 判定ロジック（純関数）と戦略クラス

**Files:**
- Modify: `katrain/core/constants.py`（`AI_SETTLE_STONES` の定義付近と `AI_STRENGTH`）
- Modify: `katrain/core/ai.py`（`SettleStonesStrategy` の後ろに追記）
- Modify: `katrain/config.json`（`ai` オブジェクト）
- Test: `tests/test_tsumego_ownership.py`（新規）

**Interfaces:**
- Consumes（すべて既存）: `var_to_grid`, `Move`, `AIStrategy`, `register_strategy`, `OUTPUT_DEBUG`, `OUTPUT_INFO`
- Produces:
  - `AI_TSUMEGO = "ai:tsumego"`（`constants.py`）
  - `tsumego_ownership_gain(root_ownership, move_ownership, stones, board_size, player_sign) -> float`
  - `select_tsumego_move(candidates, root_ownership, stones, board_size, player_sign, max_points_behind) -> dict | None`
  - `TsumegoOwnershipStrategy`（`@register_strategy(AI_TSUMEGO)`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_ownership.py` を新規作成:

```python
import pytest

from katrain.core.ai import select_tsumego_move, tsumego_ownership_gain

# var_to_grid は grid[y][x] を返し、配列は上の行(y降順)から詰まる。
# 3x3 なら array[0:3]=grid[2], array[3:6]=grid[1], array[6:9]=grid[0]
SIZE = (3, 3)
ZERO = [0.0] * 9


def _own(**cells):
    """cells は "x,y" -> 値。var_to_grid の並びに合わせた配列を作る"""
    arr = [0.0] * 9
    for key, val in cells.items():
        x, y = (int(v) for v in key.split("_"))
        arr[(SIZE[1] - 1 - y) * SIZE[0] + x] = val
    return arr


def test_gain_sums_ownership_change_over_stones():
    # (0,0) が +1.0、(1,1) が +0.5 動く。黒番(sign=+1)なので合計 +1.5
    move_own = _own(x0_y0=1.0, x1_y1=0.5)
    gain = tsumego_ownership_gain(ZERO, move_own, [(0, 0), (1, 1)], SIZE, +1)
    assert gain == pytest.approx(1.5)


def test_gain_ignores_points_without_stones():
    # 石の無い (2,2) が動いても gain には効かない（空き地の手が沈む理由）
    move_own = _own(x2_y2=1.0)
    gain = tsumego_ownership_gain(ZERO, move_own, [(0, 0), (1, 1)], SIZE, +1)
    assert gain == pytest.approx(0.0)


def test_gain_sign_flips_for_white():
    move_own = _own(x0_y0=1.0)
    assert tsumego_ownership_gain(ZERO, move_own, [(0, 0)], SIZE, +1) == pytest.approx(1.0)
    assert tsumego_ownership_gain(ZERO, move_own, [(0, 0)], SIZE, -1) == pytest.approx(-1.0)


def test_select_prefers_largest_gain():
    cands = [
        {"move": "A1", "pointsLost": 0.0, "ownership": ZERO},
        {"move": "B1", "pointsLost": 1.0, "ownership": _own(x0_y0=0.8)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "B1"


def test_select_rejects_move_beyond_points_guard():
    # gain は最大だが目数ガードを超える手は選ばれない（case B の D5 相当）
    cands = [
        {"move": "A1", "pointsLost": 0.0, "ownership": _own(x0_y0=0.3)},
        {"move": "B1", "pointsLost": 5.0, "ownership": _own(x0_y0=1.0)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "A1"


def test_select_guard_is_relative_to_best_not_zero():
    # 最善手自体が損をしている場合でも、そこからの相対で許容する（case C は最善が +1.7 目損）
    cands = [
        {"move": "A1", "pointsLost": 1.7, "ownership": ZERO},
        {"move": "B1", "pointsLost": 3.0, "ownership": _own(x0_y0=0.9)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "B1"


def test_select_tiebreaks_on_points_lost():
    cands = [
        {"move": "A1", "pointsLost": 1.5, "ownership": _own(x0_y0=0.5)},
        {"move": "B1", "pointsLost": 0.5, "ownership": _own(x0_y0=0.5)},
    ]
    chosen = select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0)
    assert chosen["move"] == "B1"


def test_select_returns_none_without_ownership():
    # ownership が取れない場合は None（呼び出し側が candidate_moves[0] にフォールバックする）
    cands = [{"move": "A1", "pointsLost": 0.0}, {"move": "B1", "pointsLost": 1.0}]
    assert select_tsumego_move(cands, ZERO, [(0, 0)], SIZE, +1, 2.0) is None


def test_select_returns_none_without_root_ownership():
    cands = [{"move": "A1", "pointsLost": 0.0, "ownership": ZERO}]
    assert select_tsumego_move(cands, None, [(0, 0)], SIZE, +1, 2.0) is None


def test_select_returns_none_without_stones():
    cands = [{"move": "A1", "pointsLost": 0.0, "ownership": ZERO}]
    assert select_tsumego_move(cands, ZERO, [], SIZE, +1, 2.0) is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_ownership.py -v`
Expected: FAIL — `ImportError: cannot import name 'select_tsumego_move' from 'katrain.core.ai'`

- [ ] **Step 3: 定数を追加する**

`katrain/core/constants.py` の `AI_SETTLE_STONES = "ai:settle"` の直後に追記:

```python
AI_TSUMEGO = "ai:tsumego"  # 詰碁キャプチャ用。プログラムからのみ設定する（GUIの一覧には出さない）
```

同ファイルの `AI_STRENGTH` 辞書の `AI_SETTLE_STONES: 2,` の直後に追記:

```python
    AI_TSUMEGO: float("nan"),
```

**`AI_STRATEGIES` / `AI_STRATEGIES_ENGINE` / `AI_STRATEGIES_RECOMMENDED_ORDER` には追加しない。**
`AI_SETTLE_STONES` と同じ「プログラムからのみ設定する戦略」の扱いにする。
`tests/test_ai.py:14` が両リストの一致をアサートしているため、片方だけに足すと壊れる。

- [ ] **Step 4: 純関数を実装する**

`katrain/core/ai.py` の `SettleStonesStrategy` クラスの定義が終わった直後（次の
`@register_strategy` または `class` の直前）に追記:

```python
def tsumego_ownership_gain(root_ownership, move_ownership, stones, board_size, player_sign):
    """盤上の全石について、手番側から見て有利な向きの ownership 変化量を合計する。

    石ごとに合計するので大きい連の死活ほど重く効く。石の無い点は数えないので、
    空き地の手は gain がほぼ 0 になり自動的に沈む。
    """
    root_grid = var_to_grid(root_ownership, board_size)
    move_grid = var_to_grid(move_ownership, board_size)
    return sum(player_sign * (move_grid[y][x] - root_grid[y][x]) for x, y in stones)


def select_tsumego_move(candidates, root_ownership, stones, board_size, player_sign, max_points_behind):
    """目数ガードを通した候補から ownership gain 最大の手を返す。選べなければ None。

    詰碁の正解判定は対象石群の死活で決まるが KataGo の目的関数は盤全体の目数であり、
    この不一致が誤答の主因になる（実測: 目数では誤答手が上位、ownership では正解手が上位）。
    目数ガードは「gain は大きいが大損する手」を弾くためのもので、最善手からの相対で見る
    （詰碁では最善手自体が目数を損することがあるため、絶対値では判定できない）。
    """
    if not candidates or not root_ownership or not stones:
        return None
    best_loss = min(c["pointsLost"] for c in candidates)
    scored = [
        (tsumego_ownership_gain(root_ownership, c["ownership"], stones, board_size, player_sign), -c["pointsLost"], c)
        for c in candidates
        if c.get("ownership") and c["pointsLost"] <= best_loss + max_points_behind
    ]
    if not scored:
        return None
    return max(scored, key=lambda scored_move: (scored_move[0], scored_move[1]))[2]
```

- [ ] **Step 5: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_ownership.py -v`
Expected: 10 passed

- [ ] **Step 6: 戦略クラスを実装する**

`katrain/core/ai.py` の Step 4 で追加した2関数の直後に追記:

```python
@register_strategy(AI_TSUMEGO)
class TsumegoOwnershipStrategy(AIStrategy):
    """詰碁用: 盤全体の目数ではなく対象石群の死活（ownership の変化量）で手を選ぶ"""

    def generate_move(self) -> Tuple[Move, str]:
        self.wait_for_analysis()
        candidate_moves = self.cn.candidate_moves
        if not candidate_moves:
            self.game.katrain.log(f"[{self.strategy_name}] 候補手が無いためパスします", OUTPUT_INFO)
            return Move(coords=None, player=self.cn.next_player), "候補手が無いためパス"

        max_points_behind = (self.settings or {}).get("max_points_behind", 2.0)
        stones = [s.coords for s in self.game.stones]
        player_sign = self.cn.player_sign(self.cn.next_player)
        chosen = select_tsumego_move(
            candidate_moves,
            self.cn.ownership,
            stones,
            self.game.board_size,
            player_sign,
            max_points_behind,
        )
        if chosen is None:
            # ownership が無い（_enable_ownership が false 等）。無言で劣化させず既定動作に戻す
            self.game.katrain.log(
                f"[{self.strategy_name}] ownership が取得できないため最善手にフォールバックします"
                f"（engine/_enable_ownership を確認してください）",
                OUTPUT_INFO,
            )
            chosen = candidate_moves[0]
            gain_text = "ownership なし"
        else:
            gain = tsumego_ownership_gain(
                self.cn.ownership, chosen["ownership"], stones, self.game.board_size, player_sign
            )
            gain_text = f"gain={gain:+.2f}"
        move = Move.from_gtp(chosen["move"], player=self.cn.next_player)
        self.game.katrain.log(
            f"[{self.strategy_name}] Final decision: {move.gtp()} "
            f"({gain_text}, pointsLost={chosen['pointsLost']:+.2f}, "
            f"候補{len(candidate_moves)}手, max_points_behind={max_points_behind})",
            OUTPUT_DEBUG,
        )
        return move, f"詰碁戦略: {len(candidate_moves)}手から {move.gtp()} を選択（{gain_text}）"
```

`katrain/core/ai.py:11-12` の constants import に `AI_TSUMEGO` を追加する。現状は

```python
    AI_POLICY, AI_RANK, AI_SCORELOSS, AI_SCORELOSS_ELO, AI_SETTLE_STONES,
    AI_SIMPLE_OWNERSHIP, AI_STRENGTH,
```

なので、`AI_STRENGTH,` の後ろに `AI_TSUMEGO,` を足してアルファベット順を保つ:

```python
    AI_POLICY, AI_RANK, AI_SCORELOSS, AI_SCORELOSS_ELO, AI_SETTLE_STONES,
    AI_SIMPLE_OWNERSHIP, AI_STRENGTH, AI_TSUMEGO,
```

- [ ] **Step 7: `katrain/config.json` に既定設定を追加**

`ai` オブジェクトの `"ai:settle"` エントリの直後に追記:

```json
    "ai:tsumego": {
      "max_points_behind": 2.0
    },
```

既存キーの整形は変えないこと。

- [ ] **Step 8: 設定が読めることを確認**

Run: `python -c "import json,io; d=json.load(io.open('katrain/config.json',encoding='utf-8')); print(d['ai']['ai:tsumego']); print('_enable_ownership =', d['engine']['_enable_ownership'])"`
Expected: `{'max_points_behind': 2.0}` と `_enable_ownership = True`

- [ ] **Step 9: 戦略が登録されていることを確認**

Run:
```bash
python -c "
import os; os.environ['KIVY_NO_ARGS']='1'
from katrain.core.ai import STRATEGY_REGISTRY
from katrain.core.constants import AI_TSUMEGO, AI_STRATEGIES, AI_STRATEGIES_RECOMMENDED_ORDER, AI_STRENGTH
print('registered:', AI_TSUMEGO in STRATEGY_REGISTRY)
print('in AI_STRENGTH:', AI_TSUMEGO in AI_STRENGTH)
print('not in AI_STRATEGIES:', AI_TSUMEGO not in AI_STRATEGIES)
print('lists match:', set(AI_STRATEGIES_RECOMMENDED_ORDER) == set(AI_STRATEGIES))
"
```
Expected: 4行すべて `True`

- [ ] **Step 10: 全テストを実行**

Run: `python -m pytest tests/ --ignore=tests/test_ai.py -q`
Expected: 314 passed（既存304 + 新規10）

- [ ] **Step 11: コミット**

```bash
git add katrain/core/ai.py katrain/core/constants.py katrain/config.json tests/test_tsumego_ownership.py
git commit -m "feat(ai): 詰碁用にownershipで着手を選ぶ ai:tsumego 戦略を追加

詰碁の正解判定は対象石群の死活で決まるが KataGo の目的関数は盤全体の目数であり、
この不一致が誤答の主因になる（実測: case C は目数だと誤答手J1が正解手H1に勝つが
ownership では H1 が明確に勝つ）。目数ガードで大損の手を弾いてから ownership の
変化量が最大の手を選ぶ。判定ロジックは Game 非依存の純関数に切り出して単体テストする。
ownership が取れない場合は最善手にフォールバックしログに出す。"
```

---

### Task 2: キャプチャ時の黒番を ai:tsumego にする

**Files:**
- Modify: `katrain/__main__.py`（`_do_tsumego_capture_apply` 内、`AI_DEFAULT` を使っている箇所）

**Interfaces:**
- Consumes: `AI_TSUMEGO`（Task 1 で `constants.py` に追加）
- Produces: なし

- [ ] **Step 1: 現在の記述を確認**

Run: `grep -n "AI_DEFAULT" katrain/__main__.py`
Expected: 3箇所（import 行、`_do_ai_move` 付近の1箇所、`_do_tsumego_capture_apply` 内の1箇所）。
このうち **`_do_tsumego_capture_apply` の中で `update_player("B", ...)` を呼んでいる行のみ**が対象。
他の2箇所（import と、キャプチャ以外の場所）は変更しない。

- [ ] **Step 2: 対象行を変更する**

`_do_tsumego_capture_apply` の中の

```python
            self.update_player("B", player_type=PLAYER_AI, player_subtype=AI_DEFAULT)
```

を次に置き換える:

```python
            # 詰碁の正解判定は対象石群の死活で決まるため、盤全体の目数で選ぶ ai:default ではなく
            # ownership の変化量で選ぶ ai:tsumego を使う
            self.update_player("B", player_type=PLAYER_AI, player_subtype=AI_TSUMEGO)
```

`katrain/__main__.py:85` は `    AI_DEFAULT,` の1行なので、その直後に1行足す:

```python
    AI_DEFAULT,
    AI_TSUMEGO,
```

`AI_DEFAULT` の import は他の箇所で使うので消さないこと。

- [ ] **Step 3: 変更範囲を確認**

Run: `git diff katrain/__main__.py`
Expected: import に1つ追加、`_do_tsumego_capture_apply` 内の1行 + コメント2行のみ。
`_do_ai_move` や他の `update_player` 呼び出しは差分に出ない

- [ ] **Step 4: 構文と参照を確認**

Run:
```bash
python -c "import ast,io; ast.parse(io.open('katrain/__main__.py',encoding='utf-8').read()); print('syntax ok')"
grep -c "AI_DEFAULT" katrain/__main__.py
```
Expected: `syntax ok` と `2`（import 行と、キャプチャ以外の1箇所）

- [ ] **Step 5: 全テストを実行**

Run: `python -m pytest tests/ --ignore=tests/test_ai.py -q`
Expected: 314 passed（Task 1 と同数。`__main__.py` はテスト対象外なので増えない）

- [ ] **Step 6: コミット**

```bash
git add katrain/__main__.py
git commit -m "feat(tsumego_capture): キャプチャ時の黒番を ai:tsumego に切り替え

盤全体の目数で選ぶ ai:default ではなく、対象石群の死活で選ぶ ai:tsumego を使う。"
```

---

### Task 3: ローカル設定と実機検証（メインセッションで実施）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`

**Interfaces:**
- Consumes: `ai:tsumego` の設定キー名と既定値（Task 1）、`engine._enable_ownership`
- Produces: なし

**このタスクはサブエージェントに委任しないこと。** サブエージェントが成功を報告しても
実際に反映されないことがある既知の問題があるため、担当者が直接 Edit する。

- [ ] **Step 1: KaTrain が起動していないことを確認**

Run (PowerShell):
`Get-Process | Where-Object { $_.MainWindowTitle -like "*KaTrain*" -and $_.MainWindowTitle -notlike "*Visual Studio Code*" } | Select-Object Id, MainWindowTitle`
Expected: 出力なし

**起動中に編集すると KaTrain 終了時に設定ごと上書きされて消える。**
出力があった場合はユーザーに終了を依頼し、再確認してから次へ進む。

- [ ] **Step 2: 現在の値を確認**

Run:
```bash
python -c "
import json,io
d=json.load(io.open(r'C:\Users\iwaki\.katrain\config.json',encoding='utf-8'))
print('_enable_ownership =', d['engine'].get('_enable_ownership'))
print('ai:tsumego =', d['ai'].get('ai:tsumego'))
"
```
Expected: `_enable_ownership = False` と `ai:tsumego = None`

- [ ] **Step 3: 2箇所を編集する**

Edit ツールで直接編集する。

`engine` オブジェクトの `"_enable_ownership": false` を `"_enable_ownership": true` に変更。
**これが false のままだと候補手ごとの ownership が返らず、戦略はフォールバックし続ける。**

`ai` オブジェクトの `"ai:settle"` エントリの直後に追記（ローカル設定のインデントに合わせる）:

```json
        "ai:tsumego": {
            "max_points_behind": 2.0
        },
```

- [ ] **Step 4: 値を確認**

Run:
```bash
python -c "
import json,io
d=json.load(io.open(r'C:\Users\iwaki\.katrain\config.json',encoding='utf-8'))
print('_enable_ownership =', d['engine']['_enable_ownership'])
print('ai:tsumego =', d['ai']['ai:tsumego'])
print('use_frame =', d['tsumego_capture']['use_frame'])
"
```
Expected: `_enable_ownership = True`、`ai:tsumego = {'max_points_behind': 2.0}`、`use_frame = True`

- [ ] **Step 5: 実機で確認**

1. `C:\Users\iwaki\.katrain\config.json` の `"debug_level"` を `1` にする
2. `python -m katrain` で起動し、BlueStacks で詰碁を表示して F4
3. ログで戦略が動いていることを確認:
   `grep -a "TsumegoOwnershipStrategy" C:\Users\iwaki\.katrain\logs\game_*.log | tail -5`
   - `Final decision: ... (gain=...)` が出ていれば ownership で選べている
   - `ownership が取得できないため最善手にフォールバック` が出ていたら `_enable_ownership` を疑う
4. 既知のケース（case A の L1、case B の B4、case C の H1）を含む問題群で正解率を確認する
5. `debug_level` を `0` に戻す

判定は設計書の「詰碁の正解判定ルール」に従う。AI が正解手と違う手を打っても、
**アプリが正解と判定すれば正解**（コウ・セキに持ち込む別解も正解）。

- [ ] **Step 6: 結果を記録し `max_points_behind` を評価する**

問題ごとに正解／不正解を記録する。既定値 2.0 は case B / C の2ケースからの推定なので、
誤答が出た場合はログの `pointsLost` と `gain` を見て、正解手が

- **目数ガードで弾かれていた**（正解手の pointsLost が最善手 + 2.0 を超えていた）→ 値を上げる
- **ガードは通ったが gain で負けた** → 値の問題ではない。設計書の「限界」の範疇

のどちらかを切り分ける。

---

## 完了条件

- `python -m pytest tests/ --ignore=tests/test_ai.py` が全て PASS（314件）
- 既存テストの期待値変更がゼロ
- 実機ログに `TsumegoOwnershipStrategy` の `Final decision: ... (gain=...)` が出る
  （フォールバックのログが出ていない）
- 既知ケースでの正解率が `ai:default` と比較できている

## この計画に含めないこと

- **komi によるバランス調整** — 設計書の「限界」に記載。飽和時は KataGo の探索自体が甘くなるため
  併用は有効な可能性があるが、本計画では評価しない
- **枠モード側への適用** — `ai:tsumego` はキャプチャ経路の黒番にのみ割り当てる。
  枠あり／なしのどちらでも同じ戦略が動く
- **GUI の戦略一覧への追加** — `AI_SETTLE_STONES` と同じくプログラムからのみ設定する扱いにする
