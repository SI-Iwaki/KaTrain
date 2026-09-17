# 難解「序盤の賭け罠（gamble）」オプション Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 難解 / 難解＋（9・13・19路）に、序盤の窓の中で「正しく応じられたときの勝率フロアの内側にある本物の罠」を net 比較を飛ばして打つオプションを足す（既定 OFF＝ビット同一）。

**Architecture:** 判定は純関数 2 本（`enigma9_gamble_window` / `enigma9_gamble_pick`）に置き、`Enigma9Strategy._generate_move` には「窓の判定」「窓の中だけ spread プローブ」「スコアリング後の賭け罠の採用」の 3 箇所だけ差し込む。難解＋は `_generate_move` を継承、`Mimic13Strategy` は上書きしているので無関係。設定は接頭辞ごとに 3 キー × 6 戦略。

**Tech Stack:** Python 3.12 / pytest / Kivy 非依存のスタブテスト / gettext（`tools/compile_mo.py`）

**Spec:** `docs/superpowers/specs/2026-09-17-enigma-gamble-design.md`

## Global Constraints

- 既定値は `gamble_until_move=0`（OFF）・`gamble_min_winrate=0.35`・`gamble_min_delta_e=0.5`。OFF の手番は解析条件・採用判断ともビット同一
- cap（`max_loss`・aim_jigo の頭打ち・消費モードの緩和）は動かさない。発動は ヨセ前 × `cost_weight >= 1.0` × `depth < gamble_until_move`
- モジュール定数: `ENIGMA9_GAMBLE_MAX_FIND = ENIGMA9_HP_BOOK`(0.25) / `ENIGMA9_GAMBLE_COST_WEIGHT = 0.5` / `ENIGMA9_GAMBLE_PROBE_EXTRA = 4`
- `katrain/core/*.py`・`katrain/config.json`・`.po`・`.claude/rules/*.md`・`INDEX.md`・`tests/test_ai_enigma9.py` は **CRLF かつ black 未整形**。Edit/Write ツールは PostToolUse フックで black が全体を再整形するので、**既存ファイルはスクラッチの python パッチスクリプト（`\r\n` を正規化して置換 → CRLF に戻して `newline=""` で書く）で書き換える**。新規ファイルは Write でよい
- `~/.katrain/config.json` はメインセッションが直接書く（サブエージェントに委任しない）。書く前に KaTrain が起動していないことを確かめる（起動中は終了時に上書きされる）
- コミットメッセージは日本語・Conventional Commits・末尾に `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`
- GUI 表示名は「賭け罠」（既存の `large_lead_max_loss` が「勝負手」を使っているため区別する）

---

### Task 1: 純関数と定数

**Files:**
- Modify: `katrain/core/ai.py`（定数は `ENIGMA9_LOCALITY_SLACK` の直後、純関数は `enigma9_delta_e_filter` の直後）
- Create: `tests/test_ai_enigma_gamble.py`

**Interfaces:**
- Produces: `enigma9_gamble_window(depth, until_move) -> bool`、
  `enigma9_gamble_pick(scored, best_gtp, min_winrate, min_delta_e, max_find=ENIGMA9_GAMBLE_MAX_FIND, cost_weight=ENIGMA9_GAMBLE_COST_WEIGHT) -> (pick|None, qualifiers)`。
  `scored` の要素は `_generate_move` が作る dict（`gtp` / `loss`=検証済み損失 / `wr_after` / `e` / `find`）。返す dict には `d_e` と `u` が足される

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_ai_enigma_gamble.py`）

```python
# tests/test_ai_enigma_gamble.py
"""難解の「序盤の賭け罠」オプション（spec 2026-09-17-enigma-gamble-design.md）のテスト（KataGo/Kivy 不要）。"""
import pytest

from katrain.core.ai import (
    ENIGMA9_GAMBLE_COST_WEIGHT,
    ENIGMA9_GAMBLE_MAX_FIND,
    ENIGMA9_GAMBLE_PROBE_EXTRA,
    ENIGMA9_HP_BOOK,
    enigma9_gamble_pick,
    enigma9_gamble_window,
)


def entry(gtp, e, loss, wr, find=0.05):
    return {"gtp": gtp, "e": e, "loss": loss, "wr_after": wr, "find": find, "net": 0.0}


BEST = entry("D4", 0.10, 0.0, 0.52, find=0.9)


class TestGambleWindow:
    def test_zero_is_off(self):
        assert enigma9_gamble_window(0, 0) is False
        assert enigma9_gamble_window(10, None) is False

    def test_active_below_the_slider_only(self):
        assert enigma9_gamble_window(34, 35) is True
        assert enigma9_gamble_window(35, 35) is False

    def test_float_slider_value_is_coerced(self):
        assert enigma9_gamble_window(34, 35.0) is True


class TestGamblePick:
    def test_constants(self):
        assert ENIGMA9_GAMBLE_MAX_FIND == ENIGMA9_HP_BOOK
        assert ENIGMA9_GAMBLE_COST_WEIGHT == 0.5
        assert ENIGMA9_GAMBLE_PROBE_EXTRA == 4

    def test_picks_a_real_trap_inside_the_floor(self):
        trap = entry("G7", 0.90, 1.0, 0.36)
        pick, quals = enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5)
        assert pick["gtp"] == "G7"
        assert [c["gtp"] for c in quals] == ["G7"]
        assert pick["d_e"] == pytest.approx(0.80)
        assert pick["u"] == pytest.approx(0.80 - 0.5 * 1.0)

    def test_winrate_floor_blocks(self):
        trap = entry("G7", 0.90, 1.0, 0.34)
        assert enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5) == (None, [])

    def test_missing_winrate_blocks(self):
        trap = entry("G7", 0.90, 1.0, None)
        assert enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5) == (None, [])

    def test_small_delta_e_blocks(self):
        trap = entry("G7", 0.55, 1.0, 0.40)  # dE 0.45 < 0.5
        assert enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5) == (None, [])

    def test_findable_reply_blocks(self):
        trap = entry("G7", 0.90, 1.0, 0.40, find=0.30)
        assert enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5) == (None, [])

    def test_boundaries_are_inclusive(self):
        trap = entry("G7", 0.60, 1.0, 0.35, find=0.25)  # dE 0.5 / wr 0.35 / find 0.25 ちょうど
        pick, _ = enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5)
        assert pick["gtp"] == "G7"

    def test_clearly_bigger_trap_wins_despite_its_price(self):
        cheap = entry("C7", 0.67, 0.39, 0.49)    # dE 0.57 -> u 0.375
        big = entry("H3", 1.12, 1.18, 0.40)      # dE 1.02 -> u 0.43
        pick, quals = enigma9_gamble_pick([BEST, cheap, big], "D4", 0.35, 0.5)
        assert pick["gtp"] == "H3"
        assert len(quals) == 2

    def test_marginally_bigger_trap_loses_to_the_cheaper_one(self):
        cheap = entry("L6", 0.66, 0.74, 0.45)    # dE 0.56 -> u 0.19
        pricey = entry("K7", 0.74, 1.23, 0.40)   # dE 0.64 -> u 0.025
        pick, _ = enigma9_gamble_pick([BEST, cheap, pricey], "D4", 0.35, 0.5)
        assert pick["gtp"] == "L6"

    def test_negative_vloss_is_not_a_bonus(self):
        a = entry("A1", 0.70, -0.40, 0.55)
        b = entry("B1", 0.75, 0.00, 0.52)
        pick, _ = enigma9_gamble_pick([BEST, a, b], "D4", 0.35, 0.5)
        assert pick["gtp"] == "B1"  # u は dE だけで決まる（-0.40 は 0 扱い）

    def test_missing_best_entry_fails_safe(self):
        trap = entry("G7", 0.90, 1.0, 0.40)
        assert enigma9_gamble_pick([trap], "D4", 0.35, 0.5) == (None, [])

    def test_input_entries_are_not_mutated(self):
        trap = entry("G7", 0.90, 1.0, 0.40)
        enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5)
        assert "u" not in trap and "d_e" not in trap
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_ai_enigma_gamble.py -q`
Expected: ImportError（`ENIGMA9_GAMBLE_COST_WEIGHT` が無い）

- [ ] **Step 3: 実装**（python パッチスクリプトで `katrain/core/ai.py` に挿入）

定数（`ENIGMA9_LOCALITY_SLACK = 0.3 ...` の行の直後）:

```python

# 序盤の賭け罠（gamble）オプション（spec 2026-09-17-enigma-gamble-design.md）。窓（手数 <
# `<prefix>_gamble_until_move`）× ヨセ前 × 消費モードでない手番で、「E を最善手より明確に多く買い、
# 十分な応手が見つけにくく、正しく応じられても勝率フロアを割らない」挑戦者を net 比較を飛ばして打つ。
# until_move 0 = OFF（採用判断・解析条件とも従来とビット同一）
ENIGMA9_GAMBLE_MAX_FIND = ENIGMA9_HP_BOOK   # 十分な応手の hp 最大値がこれ以下＝正しい応手が「本の手」でない
ENIGMA9_GAMBLE_COST_WEIGHT = 0.5            # 資格のある罠どうしの順位づけ u = ΔE − これ × max(0, vloss)
ENIGMA9_GAMBLE_PROBE_EXTRA = 4              # 窓の中で保証する spread プローブ数（基底の安い順 7 手は高い帯を見ない）
```

純関数（`enigma9_delta_e_filter` の `return kept, dropped` の直後・クラス定義の前）:

```python
def enigma9_gamble_window(depth, until_move):
    """序盤の賭け罠（`<prefix>_gamble_until_move`）の窓の中か。0 以下で OFF。

    「N 手まで」＝対局の手数 depth が N 未満の手番（序盤の 9段委譲 `enigma9_opening_handoff` と同じ
    数え方）。スライダー値は float で来ることがあるので int に丸める。
    """
    n = int(until_move or 0)
    return n > 0 and depth < n


def enigma9_gamble_pick(scored, best_gtp, min_winrate, min_delta_e,
                        max_find=ENIGMA9_GAMBLE_MAX_FIND, cost_weight=ENIGMA9_GAMBLE_COST_WEIGHT):
    """賭け罠の資格がある挑戦者から1手選ぶ。返り値 (pick | None, qualifiers)。

    scored は `_generate_move` のスコアリング済みエントリ（検証済み損失 <= cap と通常の勝率フロアは
    通過済み）。資格は3条件の AND:
      - wr_after >= min_winrate（相手が最善で応じた場合の勝率＝子局面 root の検証値。無ければ不可）
      - E − 最善手の E >= min_delta_e（相手の期待損失を最善手より明確に多く買う＝本物の罠）
      - find <= max_find（十分な応手のうち最も見つけやすい手が 9 段の「本の手」でない）
    順位は u = ΔE − cost_weight × max(0, vloss)（同点は E 大 → vloss 小）。rarity 項は使わない
    ＝実測で reply_rare は E を与件にすると寄与ゼロ、own_rare 単独の外しは序盤では騙せていない
    （親 spec 追記12・2026-09-03）。最善手のエントリが無ければ比較の基準が無いので (None, [])。
    入力の dict は書き換えない（返す dict に d_e と u を足したコピー）。境界は inclusive。

    実測（2026-09-17・難解＋13路 18 局・手数<=35 の非消費モード 116 手番）: 既定値で資格ありは
    16 手番（約 0.9 回/局）、うち 10 手番は資格が 1 手だけ。選ばれる手は平均 vloss 0.89・ΔE 0.71、
    着手後勝率 35〜69%。現行の net 比較が同じ手を選ぶのは 4/16。
    """
    best = next((c for c in scored if c["gtp"] == best_gtp), None)
    if best is None:
        return None, []
    eps = 1e-9
    qualifiers = []
    for c in scored:
        if c["gtp"] == best_gtp:
            continue
        wr = c.get("wr_after")
        if wr is None or wr < min_winrate - eps:
            continue
        d_e = c["e"] - best["e"]
        if d_e < min_delta_e - eps:
            continue
        find = c.get("find")
        if find is None or find > max_find + eps:
            continue
        qualifiers.append({**c, "d_e": d_e, "u": d_e - cost_weight * max(0.0, c["loss"])})
    if not qualifiers:
        return None, []
    return max(qualifiers, key=lambda c: (c["u"], c["e"], -c["loss"])), qualifiers
```

- [ ] **Step 4: 通過を確認**

Run: `python -m pytest tests/test_ai_enigma_gamble.py -q`
Expected: 全部 PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_enigma_gamble.py
git commit -m "feat(enigma): 序盤の賭け罠の純関数（窓の判定と資格つき選択）"
```

---

### Task 2: 設定キーの登録（SETTING_DEFAULTS・GUI 候補値・パッケージ config・i18n）

既存の不変条件テスト（`tests/test_ai_enigma9.py::TestGuiConfigConsistency`・
`tests/test_ai_enigma_plus.py::TestGuiConfigConsistency`）が SETTING_DEFAULTS ↔ `AI_OPTION_VALUES` ↔
`AI_OPTION_ORDER` ↔ パッケージ `config.json` ↔ `.po` の整合を検査するので、全部を同じタスクで入れる。

**Files:**
- Modify: `katrain/core/ai.py`（`Enigma9Strategy` / `Enigma13Strategy` / `Enigma19Strategy` の `SETTING_DEFAULTS`）
- Modify: `katrain/core/constants.py`（`AI_OPTION_VALUES` / `AI_OPTION_ORDER`）
- Modify: `katrain/config.json`
- Modify: `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po` → `python tools/compile_mo.py`
- Test: `tests/test_ai_enigma_gamble.py`（追記）

**Interfaces:**
- Produces: 設定キー `<prefix>_gamble_until_move` / `<prefix>_gamble_min_winrate` / `<prefix>_gamble_min_delta_e`
  （prefix = enigma9 / enigma9plus / enigma13 / enigma13plus / enigma19 / enigma19plus）。
  `self._setting("gamble_until_move")` 等で読める

- [ ] **Step 1: 失敗するテストを追記**（`tests/test_ai_enigma_gamble.py` の末尾）

```python
from katrain.core.ai import (
    Enigma9PlusStrategy,
    Enigma9Strategy,
    Enigma13PlusStrategy,
    Enigma13Strategy,
    Enigma19PlusStrategy,
    Enigma19Strategy,
    Mimic13Strategy,
)
from katrain.core.constants import AI_OPTION_VALUES

ALL_ENIGMA = [
    Enigma9Strategy, Enigma9PlusStrategy, Enigma13Strategy, Enigma13PlusStrategy,
    Enigma19Strategy, Enigma19PlusStrategy,
]


class TestGambleSettings:
    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_defaults_are_off_with_35_percent_floor(self, cls):
        assert cls.SETTING_DEFAULTS["gamble_until_move"] == 0
        assert cls.SETTING_DEFAULTS["gamble_min_winrate"] == 0.35
        assert cls.SETTING_DEFAULTS["gamble_min_delta_e"] == 0.5

    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_off_value_and_recommended_window_are_gui_options(self, cls):
        values = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[f"{cls.KEY_PREFIX}_gamble_until_move"]]
        assert values[0] == 0
        recommended = {9: 16, 13: 35, 19: 75}[cls.BOARD_LEN]
        assert recommended in values

    def test_mimic13_is_untouched(self):
        assert not any(k.startswith("gamble") for k in Mimic13Strategy.SETTING_DEFAULTS)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_ai_enigma_gamble.py -q`
Expected: `KeyError: 'gamble_until_move'`

- [ ] **Step 3: 実装**（python パッチスクリプト 1 本で 5 ファイルを書き換える）

`ai.py`: 3 クラスの `SETTING_DEFAULTS` の `"locality_slack": ENIGMA9_LOCALITY_SLACK, ...` 行の直後に

```python
        "gamble_until_move": 0,          # 序盤の賭け罠の窓（手数未満で発動・0=OFF）。spec 2026-09-17-enigma-gamble-design.md
        "gamble_min_winrate": 0.35,      # 賭け罠: 正しく応じられた場合の勝率の下限
        "gamble_min_delta_e": 0.5,       # 賭け罠: 罠とみなす E の上積み（目）
```

`constants.py`: `_ENIGMA_OPENING_HUMANSTYLE_MOVES = ...` の直後に

```python
# 難解の序盤の賭け罠（enigma*_gamble_*・spec 2026-09-17-enigma-gamble-design.md）。until_move は盤サイズ別
# （0=OFF・13路の推奨 35 を盤の点数比でスケール）、勝率フロアと ΔE の下限は共通
_ENIGMA_GAMBLE_UNTIL_MOVE = {
    9: [(0, "OFF"), (8, "8"), (10, "10"), (12, "12"), (16, "16"), (20, "20")],
    13: [(0, "OFF"), (20, "20"), (25, "25"), (30, "30"), (35, "35"), (40, "40"), (50, "50")],
    19: [(0, "OFF"), (40, "40"), (50, "50"), (60, "60"), (75, "75"), (90, "90"), (110, "110")],
}
_ENIGMA_GAMBLE_MIN_WINRATE = [(0.25, "25%"), (0.3, "30%"), (0.35, "35%"), (0.4, "40%"), (0.45, "45%")]
_ENIGMA_GAMBLE_MIN_DELTA_E = [0.3, 0.5, 0.7, 1.0, 1.5]
```

`AI_OPTION_VALUES` の各 `"<prefix>_opening_humanstyle_moves": _ENIGMA_OPENING_HUMANSTYLE_MOVES,` 行の直後に
（`<N>` は盤サイズ 9/13/19）

```python
    "<prefix>_gamble_until_move": _ENIGMA_GAMBLE_UNTIL_MOVE[<N>],
    "<prefix>_gamble_min_winrate": _ENIGMA_GAMBLE_MIN_WINRATE,
    "<prefix>_gamble_min_delta_e": _ENIGMA_GAMBLE_MIN_DELTA_E,
```

`AI_OPTION_ORDER` の各 `"<prefix>_opening_humanstyle_moves": 13,` 行の直後に

```python
    "<prefix>_gamble_until_move": 14,
    "<prefix>_gamble_min_winrate": 15,
    "<prefix>_gamble_min_delta_e": 16,
```

`katrain/config.json`: 各 `"<prefix>_opening_humanstyle_moves": <値>` 行（セクション末尾・カンマ無し）を

```json
            "<prefix>_opening_humanstyle_moves": <値>,
            "<prefix>_gamble_until_move": 0,
            "<prefix>_gamble_min_winrate": 0.35,
            "<prefix>_gamble_min_delta_e": 0.5
```

`.po`（jp / en）: 各 `msgid "<prefix>_opening_humanstyle_moves"` エントリの直後に 3 エントリ。
角括弧の接頭辞（`[13路＋]` / `[13x13+]` 等）は同じ戦略の `<prefix>_max_loss` のラベルから取る。

| msgid 接尾辞 | jp | en |
|---|---|---|
| `_gamble_until_move` | `<角括弧> 序盤の賭け罠（この手数未満で発動・OFF=従来）` | `<bracket> Opening gamble traps until move (OFF = classic)` |
| `_gamble_min_winrate` | `<角括弧> 賭け罠: 正しく応じられた場合の勝率の下限` | `<bracket> Gamble: winrate floor if answered correctly` |
| `_gamble_min_delta_e` | `<角括弧> 賭け罠: 罠の大きさの下限（E の上積み・目）` | `<bracket> Gamble: minimum trap size (extra E, pts)` |

`aihelp:enigma9` / `aihelp:enigma13` / `aihelp:enigma19`（基底 3 本。難解＋の help は「他の項目は難解の同名
項目と同じ意味」と委ねているので触らない）の msgstr の最後の一文の直前に挿入する。
jp の最後の一文は `<N>路以外の盤では常に最善手を打つだけになるので、他の戦略を使ってください。`、
en は `On other board sizes it simply plays the best move.`。

jp（`<p>` = enigma9 / enigma13 / enigma19）:

```
<p>_gamble_until_move: 序盤の賭け罠（既定 OFF）。対局の手数がこの値未満・ヨセ前・勝勢の消費モードでない手番で、「相手の期待損失 E を最善手より <p>_gamble_min_delta_e 目以上多く買い、十分な応手が 9 段の第一感（25%）に無く、相手が正しく最善で応じても勝率が <p>_gamble_min_winrate を割らない」手があれば、難解さの比較を飛ばしてその罠を打ちます（複数あれば E の上積み − 損失の半分が最大の手）。損失上限は変えません。正しく応じられたら素直に劣勢になり、そこからは従来の難解さの選択で逆転を狙います。13路の実測では既定値で約 0.9 回/局・1 回あたり平均 0.9 目の損失で E を 0.7 目上積みし、応じ損ねてもらっても「ほぼ互角に戻る」程度です（応じ損ねたら優勢、まで満たす手は序盤にはほぼ存在しません）。序盤の9段委譲の手番は従来どおり 9 段が打ちます。
```

en:

```
<p>_gamble_until_move: opening gamble traps (off by default). While the move number is below this value, before the endgame and outside the far-ahead spending mode, if some move buys at least <p>_gamble_min_delta_e points more expected punishment E than the best move, has no adequate reply among a 9-dan's first instincts (25%), and keeps the winrate at or above <p>_gamble_min_winrate even if the opponent answers correctly, that trap is played without the usual difficulty comparison (with several, the one maximising extra E minus half its loss). The loss cap is unchanged. If the opponent answers correctly the AI simply falls behind and tries to come back with the normal Enigma selection. Measured on 13x13: about 0.9 gambles per game at the defaults, paying 0.9 points on average for 0.7 points of extra E, so a wrong answer roughly restores an even game (moves that leave the AI clearly ahead after a wrong answer barely exist in the opening). Moves inside the opening 9-dan handoff are still played by the 9-dan.
```

パッチスクリプトは各置換のヒット数を assert する（6 セクション × 各ファイル）。

- [ ] **Step 4: `.mo` を再コンパイルしてテスト**

Run: `python tools/compile_mo.py`
Run: `python -m pytest tests/test_ai_enigma_gamble.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py tests/test_ai_mimic13.py tests/test_ai_options_grid.py -q`
Expected: 全部 PASS（`TestGuiConfigConsistency` が新キーを検査する）

- [ ] **Step 5: 差分の健全性を確認してコミット**

Run: `git diff --stat`（削除行が「config.json の 6 行＋.po の help 6 行」以外に出ていないこと＝再整形の混入なし）

```bash
git add katrain/core/ai.py katrain/core/constants.py katrain/config.json katrain/i18n tests/test_ai_enigma_gamble.py
git commit -m "feat(enigma): 序盤の賭け罠の設定キーを GUI・config・i18n に登録"
```

---

### Task 3: `_generate_move` への接続

**Files:**
- Modify: `katrain/core/ai.py`（`Enigma9Strategy._generate_move` の 3 箇所）
- Test: `tests/test_ai_enigma_gamble.py`（追記）

**Interfaces:**
- Consumes: Task 1 の純関数・Task 2 の設定キー・既存の `enigma9_shortlist_spread(pool, base_k, extra)`

- [ ] **Step 1: 失敗する接続テストを追記**

```python
import types

from katrain.core.ai import ENIGMA9_SHORTLIST


def _hp(size, values):
    """humanPolicy のフラット配列（size×size＋pass）。values は {gtp: hp}。"""
    from katrain.core.sgf_parser import Move

    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def _child(lead_after, wr_after, replies, reply_hp, size=13):
    """黒番が打った後の子局面プローブ（clean + hp）。replies は [(gtp, 白視点の損失, visits)]。

    KataGo の scoreLead / winrate は常に黒視点。白の最善応手後の黒リードが lead_after、
    白が loss 目損する応手の後は lead_after + loss。
    """
    move_infos = [
        {"move": g, "scoreLead": lead_after + loss, "visits": v, "order": i}
        for i, (g, loss, v) in enumerate(replies)
    ]
    return {
        "clean": {"rootInfo": {"scoreLead": lead_after, "winrate": wr_after}, "moveInfos": move_infos},
        "hp": {"humanPolicy": _hp(size, reply_hp)},
    }


def _gamble_strategy(cls, prefix, settings=None, *, depth=10, root_lead=0.2, extra_cands=0, endgame=False):
    """互角の13路・黒番。D4=最善 / K10=安い外し（珍しいだけ）/ G7=1.2 目払う本物の罠。"""
    logs = []
    katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
    cands = [
        {"move": "D4", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.52},
        {"move": "K10", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 60, "winrate": 0.50},
        {"move": "G7", "pointsLost": 1.2, "relativePointsLost": 1.2, "visits": 30, "winrate": 0.37},
    ]
    for i in range(extra_cands):  # 安い順 7 手の枠を埋める雑魚候補（G7 を shortlist の外へ押し出す）
        cands.insert(2, {"move": f"A{i + 1}", "pointsLost": 0.2, "relativePointsLost": 0.2 + i * 0.01,
                         "visits": 40, "winrate": 0.49})
    node = types.SimpleNamespace(
        next_player="B", player="W", depth=depth, move=None, analysis_complete=True,
        analysis={"root": {"scoreLead": root_lead}}, candidate_moves=cands,
    )
    game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(13, 13))
    if endgame:
        setattr(game, f"_{prefix}_endgame", True)
    base = {f"{prefix}_opening_humanstyle_moves": 0, f"{prefix}_max_loss": 1.6,
            f"{prefix}_locality_stddev": 0.0}
    s = cls(game, {**base, **(settings or {})})
    s.probed = []

    def probe(gtps, player, parent_hp=False):
        s.probed.append(list(gtps))
        table = {
            # 最善手: 応手は自明（E≈0）
            "D4": _child(0.2, 0.52, [("C3", 0.0, 300), ("Q1", 0.4, 20)], {"C3": 0.9, "Q1": 0.05}),
            # 安い外し: 罠は無いが自手が珍しい（own_hp 0）＝従来の net 比較はこれを選ぶ
            "K10": _child(0.1, 0.50, [("C3", 0.0, 300), ("Q1", 0.4, 20)], {"C3": 0.9, "Q1": 0.05}),
            # 本物の罠: 正しい応手 C3 は hp 20%、自然な M12（hp 70%）は 0.9 目損＝E 0.70。1.2 目払い、
            # 正しく応じられたら勝率 36%。net は 0.70 + 0.2 − 1.2 < 最善手＝従来の比較では選ばれない
            "G7": _child(-1.0, 0.36, [("C3", 0.0, 300), ("M12", 0.9, 40)], {"C3": 0.20, "M12": 0.70}),
        }
        for g in gtps:
            table.setdefault(g, _child(0.0, 0.49, [("C3", 0.0, 300)], {"C3": 0.9}))
        parent = {"humanPolicy": _hp(13, {"D4": 0.6, "G7": 0.25})} if parent_hp else None
        return {g: table[g] for g in gtps}, parent

    s._probe_children = probe
    s._run_query = lambda label, **kw: None
    return s, logs


class TestGambleEndToEnd:
    def test_off_plays_the_classic_net_choice(self):
        s, logs = _gamble_strategy(Enigma13Strategy, "enigma13")
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert not any("Gamble" in m for m in logs)

    def test_on_plays_the_trap_that_loses_the_net_race(self):
        s, logs = _gamble_strategy(Enigma13Strategy, "enigma13", {"enigma13_gamble_until_move": 35})
        move, thoughts = s.generate_move()
        assert move.gtp() == "G7"
        assert "gamble trap G7" in thoughts
        assert any("Gamble: played G7" in m for m in logs)

    def test_outside_the_window_nothing_changes(self):
        s, logs = _gamble_strategy(Enigma13Strategy, "enigma13", {"enigma13_gamble_until_move": 35}, depth=35)
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert not any("Gamble" in m for m in logs)

    def test_winrate_floor_setting_blocks_the_trap(self):
        s, logs = _gamble_strategy(
            Enigma13Strategy, "enigma13",
            {"enigma13_gamble_until_move": 35, "enigma13_gamble_min_winrate": 0.4},
        )
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert any("Gamble: window" in m and "qualifiers=[]" in m for m in logs)

    def test_delta_e_setting_blocks_the_trap(self):
        s, _ = _gamble_strategy(
            Enigma13Strategy, "enigma13",
            {"enigma13_gamble_until_move": 35, "enigma13_gamble_min_delta_e": 1.5},
        )
        assert s.generate_move()[0].gtp() == "K10"

    def test_spending_mode_is_left_alone(self):
        # lead 12 → budget 10 > max_loss＝消費モード（cost_weight < 1）では発動しない
        s, logs = _gamble_strategy(
            Enigma13Strategy, "enigma13", {"enigma13_gamble_until_move": 35}, root_lead=12.0
        )
        s.generate_move()
        assert any("Spend:" in m for m in logs)
        assert not any("Gamble" in m for m in logs)

    def test_plus_inherits_the_gamble(self):
        s, _ = _gamble_strategy(Enigma13PlusStrategy, "enigma13plus", {"enigma13plus_gamble_until_move": 35})
        assert s.generate_move()[0].gtp() == "G7"

    def test_base_shortlist_is_widened_only_inside_the_window(self):
        # 雑魚候補 8 手で安い順 7 手の枠が埋まる → OFF では G7（loss 1.2）はプローブされない
        off, _ = _gamble_strategy(Enigma13Strategy, "enigma13", extra_cands=8)
        off.generate_move()
        assert "G7" not in off.probed[0]
        assert len(off.probed[0]) == ENIGMA9_SHORTLIST
        on, _ = _gamble_strategy(Enigma13Strategy, "enigma13", {"enigma13_gamble_until_move": 35}, extra_cands=8)
        move, _ = on.generate_move()
        assert "G7" in on.probed[0]          # spread は最も高い手を必ず含む
        assert move.gtp() == "G7"
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_ai_enigma_gamble.py::TestGambleEndToEnd -q`
Expected: `test_off_*` / `test_outside_*` / `test_spending_*` は PASS、`test_on_*` など ON 系が FAIL（K10 のまま）

- [ ] **Step 3: 実装**（python パッチスクリプト・3 箇所）

(a) `# ヨセでは「自手の意外さ」を net から外す（`enigma9_own_rarity_weight`）` の行の直前に:

```python
        # ---- 序盤の賭け罠（gamble）の窓（spec 2026-09-17-enigma-gamble-design.md）----
        # ヨセ前 × 消費モードでない（余剰リードが max_loss 以下＝互角〜小差）× 手数が窓の中。
        # until_move 0（既定）= OFF＝以降の分岐はすべて従来どおり（ビット同一）。cap は動かさない
        gamble_until = int(self._setting("gamble_until_move") or 0)
        gamble_on = (
            not in_yose and cost_weight >= 1.0 and enigma9_gamble_window(self.cn.depth, gamble_until)
        )

```

(b) `shortlist = self._shortlist(pool)` の直後に:

```python
        if gamble_on and len(shortlist) < ENIGMA9_SHORTLIST - 1 + ENIGMA9_GAMBLE_PROBE_EXTRA:
            # 基底の shortlist は安い順 7 手＝互角の序盤では賭け罠の帯（vloss 0.6〜cap）を一度も
            # 調べない。窓の中だけ難解＋と同じ spread で高い帯まで見る（難解＋で probe_extra >= 4 なら
            # ここには来ない。pool が小さければ spread も全候補を返すだけ）
            shortlist = enigma9_shortlist_spread(pool, ENIGMA9_SHORTLIST - 1, ENIGMA9_GAMBLE_PROBE_EXTRA)
```

(c) `scored, _dropped = self._filter_challengers(scored, best_gtp)` の直前に:

```python
        if gamble_on:
            # 賭け罠: 資格（勝率フロア・ΔE・応手の見つけにくさ）のある挑戦者が居れば、net 比較・
            # net_margin・局所性の同点帯・難解＋の ΔE 床を通さずに打つ（`enigma9_gamble_pick`）
            g_floor = float(self._setting("gamble_min_winrate"))
            g_min_de = float(self._setting("gamble_min_delta_e"))
            g_pick, g_quals = enigma9_gamble_pick(scored, best_gtp, g_floor, g_min_de)
            self._log(
                f"Gamble: window depth={self.cn.depth} < {gamble_until} floor={g_floor:.0%} "
                f"min_dE={g_min_de:.2f} qualifiers="
                f"{[(c['gtp'], round(c['d_e'], 2), round(c['loss'], 2), round(c['wr_after'], 3)) for c in g_quals]}"
            )
            if g_pick is not None:
                self._log(
                    f"Gamble: played {g_pick['gtp']} (dE={g_pick['d_e']:+.2f}, vloss={g_pick['loss']:.2f}, "
                    f"wr={g_pick['wr_after']:.1%}, find_hp={g_pick['find']:.3f}, u={g_pick['u']:.2f}) "
                    f"instead of {best_gtp}"
                )
                self._start_ponder(g_pick["gtp"], probes.get(g_pick["gtp"]), player)
                return (
                    Move.from_gtp(g_pick["gtp"], player=player),
                    f"{self.LABEL}: gamble trap {g_pick['gtp']} (verified loss {g_pick['loss']:.2f}, "
                    f"expected punish {g_pick['e']:.2f} = +{g_pick['d_e']:.2f} over best, "
                    f"reply findability {g_pick['find']:.1%}, "
                    f"wr if answered correctly {g_pick['wr_after']:.1%}) instead of {best_gtp}.",
                )

```

- [ ] **Step 4: 通過を確認**

Run: `python -m pytest tests/test_ai_enigma_gamble.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py tests/test_ai_mimic13.py -q`
Expected: 全部 PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_enigma_gamble.py
git commit -m "feat(enigma): 序盤の賭け罠を難解の選択フローに接続"
```

---

### Task 4: ユーザーローカル config（メインセッション直営）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（git 管理外）

- [ ] **Step 1: KaTrain が起動していないことを確認**

Run: `tasklist | grep -a -i "python\|katrain"`（KaTrain のウィンドウを持つ python が居たら、ユーザーに閉じてもらうまで書かない）

- [ ] **Step 2: バックアップを取り、6 セクションに 3 キーを既定値で足す**

各 `"<prefix>_opening_humanstyle_moves": <値>` 行（セクション末尾）の後ろに Task 2 の config と同じ 3 行
（`0` / `0.35` / `0.5`）を python パッチスクリプトで足す。`json.load` で読み直して 18 キーが入っていること、
他のキーの値が変わっていないことを assert する。バックアップは `config.json.bak-20260917-pre-gamble`。

---

### Task 5: ドキュメント

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（Enigma9 / Enigma13 / Enigma19 の表に 3 行ずつ＋難解＋の「他11項目」を「他14項目」に）
- Modify: `.claude/rules/ai-strategies.md`（難解の段落の末尾に 1 段落）
- Modify: `docs/manual/src/06f_ai_enigma.html`（params 表に 3 行）→ `python tools/build_manual.py`
- Modify: `docs/superpowers/specs/INDEX.md`（enigma-locality の行の直後に 1 行）
- Modify: `docs/superpowers/specs/2026-09-17-enigma-gamble-design.md`（GUI 表示名「賭け罠」と検証結果の追記）

- [ ] **Step 1: パッチスクリプトで追記**（CRLF ファイルは CRLF を保つ。`.claude/rules/` の Edit が拒否されたらスクリプト経由で書く）

`ai-parameters.md` の Enigma13 の表（`enigma13_opening_humanstyle_moves` の行の直後）:

```markdown
| `enigma13_gamble_until_move` | **序盤の賭け罠（2026-09-17・spec `2026-09-17-enigma-gamble-design.md`）**。手数がこの値未満 × ヨセ前 × 消費モードでない（`cost_weight >= 1`）手番で、スコアリング済みの挑戦者に「`wr_after >= gamble_min_winrate`・`E − E_best >= gamble_min_delta_e`・`find_hp <= ENIGMA9_GAMBLE_MAX_FIND`(0.25)」を全部満たす手があれば net 比較・net_margin・局所性・難解＋の ΔE 床を通さず `u = ΔE − 0.5·max(0, vloss)` 最大の手を打つ（純関数 `enigma9_gamble_pick`）。cap は動かさない。窓の中は shortlist を spread +4 まで広げる（`ENIGMA9_GAMBLE_PROBE_EXTRA`・難解＋で probe_extra >= 4 なら不変）。0 = OFF＝ビット同一。実測（難解＋13路 18 局・手数<=35 の非消費 116 手番）: 既定値で資格あり 16 手番＝約 0.9 回/局・平均 vloss 0.89・ΔE 0.71・着手後勝率 35〜69%、現行 net が同じ手を選ぶのは 4/16。**「応じ損ねたら優勢（E > vloss）」まで満たす手は互角 59 手番中 1 手＝文字どおりの版は在庫なし**（着手後勝率 30〜45% の 293 候補で E>=1.0 は 1 手）。**実戦校正は未実施** | OFF/20/25/30/35/40/50 | **0（OFF）**・推奨 35 |
| `enigma13_gamble_min_winrate` | 賭け罠を打ったあと相手が最善で応じた場合の勝率（検証値）の下限。通常の `min_winrate` も効く＝実効は大きいほう。13路序盤の勝率勾配は約 19%/目なので 35% ≒ 互角から 0.8〜1.0 目損 | 25/30/35/40/45% | **0.35** |
| `enigma13_gamble_min_delta_e` | 罠とみなす E の上積み（目）。0.3 にすると発火は 2 倍強（払う損失に対する E の回収は 0.8 → 0.67 倍に落ちる） | 0.3/0.5/0.7/1.0/1.5 | **0.5** |
```

Enigma9 / Enigma19 の表にも同じ 3 行を接頭辞と候補値（9路 OFF/8/10/12/16/20・19路 OFF/40/50/60/75/90/110）を
替えて入れ、意味の欄は「13路と同じ機構（`enigma13_gamble_*` 参照）。**未校正**（推奨は盤の点数比で 9路 16・19路 75）」とする。

`ai-strategies.md`: 難解＋の段落（「難解には**改良版「難解＋」…」で始まる段落）の直前に 1 段落:

```markdown
難解 / 難解＋（9/13/19路共通）には**序盤の賭け罠オプション** `<prefix>_gamble_until_move` / `_gamble_min_winrate` / `_gamble_min_delta_e` がある（2026-09-17・既定 OFF＝ビット同一・spec `2026-09-17-enigma-gamble-design.md`）。窓（手数 < until_move）× ヨセ前 × 消費モードでない手番で、「E を最善手より min_delta_e(0.5) 目以上多く買い・十分な応手の hp が 0.25 以下・正しく応じられても勝率が min_winrate(35%) を割らない」挑戦者を net 比較を飛ばして打つ（`enigma9_gamble_pick`＝順位は ΔE − 0.5·vloss）。cap は動かさず、正しく応じられたら素直に劣勢を受け入れて従来の選択で逆転を狙う＝演出用のオプション。起点のユーザー要望は「応じられたら 35%・応じ損ねたら優勢」だったが、実測（難解＋13路 18 局のログ再集計）で**その在庫は序盤にほぼ無い**（着手後勝率 30〜45% の 293 候補で E>=1.0 は 1 手。E>=2 の大きい罠は全部 着手後も勝率 50% 以上＝既に優勢な局面のもので消費モードが打っている）ので、「応じ損ねたらほぼ互角に戻る」本物の罠まで緩めた版を入れた（約 0.9 回/局・平均 vloss 0.89・ΔE 0.71）。rarity 項を資格にも順位にも使わないのは追記12 の失敗モード（珍しさだけに払う外し）を避けるため。**実戦校正は未実施**。
```

`docs/manual/src/06f_ai_enigma.html`: `enigma*_opening_humanstyle_moves` の `<tr>` の直後に 3 行:

```html
      <tr><td>enigma*_gamble_until_move</td><td>OFF<span class="jp">目安 16</span></td><td>OFF<span class="jp">推奨 35</span></td><td>OFF<span class="jp">目安 75</span></td><td><b>序盤の賭け罠</b>。対局の手数がこの値未満・ヨセ前・勝勢の消費モードでない手番で、「相手の期待損失 E を最善手より明確に多く買い、正しい応手が 9 段の第一感に無く、正しく応じられても勝率が下限を割らない」手があれば、難解さの比較を飛ばしてその罠を打つ。損失上限は変わらない。正しく応じられたら素直に劣勢になり、そこから従来の難解さの選択で逆転を狙う。13路の実測で約 0.9 回/局・1 回あたり平均 0.9 目の損失。応じ損ねてもらっても「ほぼ互角に戻る」程度で、「応じ損ねたら優勢」まで満たす手は序盤にはほぼ存在しない。</td><td><span class="up">上げる</span>賭けに出る期間が延びる／<span class="down">OFF</span>従来どおり</td></tr>
      <tr><td>enigma*_gamble_min_winrate</td><td>35%</td><td>35%</td><td>35%</td><td>賭け罠を打ったあと、相手が正しく最善で応じた場合の勝率の下限。13路の序盤は 1 目 ≒ 勝率 19% なので、35% は互角から約 1 目損まで。通常の勝率フロアも引き続き効く。</td><td><span class="up">上げる</span>安全側＝賭けが減る。<span class="down">下げる</span>より深く沈む賭けも打つ</td></tr>
      <tr><td>enigma*_gamble_min_delta_e</td><td>0.5</td><td>0.5</td><td>0.5</td><td>罠とみなす E の上積み（目）＝候補の E − 最善手の E の下限。</td><td><span class="up">上げる</span>大きい罠だけ＝ほぼ発動しなくなる。<span class="down">下げる</span>頻繁に賭ける（0.3 で約 2 倍）が、払う損失に見合わない罠が増える</td></tr>
```

`INDEX.md`（`2026-08-25-enigma-locality-design.md` の行の直後）:

```markdown
| `2026-09-17-enigma-gamble-design.md` | 🟢 難解 / 難解＋の序盤の賭け罠オプション（窓の中で ΔE・応手の見つけにくさ・勝率フロアの資格がある罠を net 比較を飛ばして打つ・既定 OFF）。ログ 18 局の再集計で「応じ損ねたら優勢」の在庫はほぼゼロと確認したうえでの緩和版・**実戦校正は未実施** |
```

- [ ] **Step 2: マニュアルを再ビルドして確認**

Run: `python tools/build_manual.py`
Run: `grep -c "enigma\*_gamble_until_move" docs/manual/index.html` → `1`

- [ ] **Step 3: コミット**

```bash
git add .claude/rules/ai-parameters.md .claude/rules/ai-strategies.md docs/manual docs/superpowers/specs/INDEX.md docs/superpowers/specs/2026-09-17-enigma-gamble-design.md
git commit -m "docs(enigma): 序盤の賭け罠の rules・マニュアル・INDEX を更新"
```

---

### Task 6: 実局面での検証（KataGo あり）

**Files:**
- Create: `docs/superpowers/specs/calibration-data/enigma13/enigma13plus-vs-app-20260911-184025.sgf`（ログから復元）
- Modify: `docs/superpowers/specs/2026-09-17-enigma-gamble-design.md`（§9 検証結果を追記）

- [ ] **Step 1: ログから SGF を復元**

Run: `python docs/superpowers/specs/calibration-data/enigma9/restore_sgf_from_log.py ~/.katrain/logs/game_20260911_184025.log`
（使い方はスクリプト先頭の docstring に従う。AI の手番は `Opening handoff: move=<偶奇>` で確認して記録する）

- [ ] **Step 2: 資格があった局面（手数 12）を OFF / ON で 3 run ずつ**

Run（ON）: `python -m katrain_debug --sgf <復元SGF> --move 12 --strategy enigma13plus --settings enigma13plus_gamble_until_move=35 enigma13plus_opening_humanstyle_moves=8 enigma13plus_max_loss=1.6 enigma13plus_min_winrate=0.25 enigma13plus_probe_extra=6 enigma13plus_locality_stddev=3.0 enigma13plus_target_score=1.0 2>&1 | grep -a "Gamble\|Deviate\|Best move wins\|Score "`
Expected: `Gamble: window depth=12 < 35 ...` が出る。資格のある手（ログでは D5: dE 1.24・vloss 0.60・wr 41%）が居れば
`Gamble: played ...`、居なければ `qualifiers=[]` のあと従来の選択。OFF は `Gamble` 行が 1 本も出ないこと。
E・hp は run 間で揺れるので、3 run の資格の出入りをそのまま記録する。

- [ ] **Step 3: 窓の外（手数 40 前後）と消費モードの手番で `Gamble` 行が出ないことを 1 run ずつ確認**

- [ ] **Step 4: 結果を spec §9 に追記してコミット**

```bash
git add docs/superpowers/specs
git commit -m "docs(enigma): 序盤の賭け罠の実局面検証を spec に追記"
```

- [ ] **Step 5: 回帰（KataGo と並走させない）**

Run: `python -m pytest tests/test_ai_enigma_gamble.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py tests/test_ai_mimic13.py tests/test_ai_options_grid.py tests/test_board_watch_prefetch.py -q`
Expected: 全部 PASS
