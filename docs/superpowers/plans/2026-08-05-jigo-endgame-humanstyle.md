# 持碁モード ヨセ段階の HumanStyle 9段委譲 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 持碁モード（`ai:jigo` / `ai:jigo9`）が終盤のヨセ段階に入ったら target 追従をやめ、HumanStyle 9段（`rank_9d`）として打つオプションを追加する。

**Architecture:** 判定は `ai.py` の JigoStrategy pure-function helpers に純関数2つ（`_jigo_endgame_threshold` / `_jigo_endgame_handoff`）として置く。`JigoStrategy.generate_move()` の設定読み込み直後・Stage1 クエリ発行前に判定し、成立したら `HumanStyleStrategy(self.game, {"human_kyu_rank": -8, "modern_style": True})` を生成して結果をそのまま返す。`Jigo9Strategy` は `generate_move` を継承しているので自動的に同じ経路に乗る。

**Tech Stack:** Python 3.12 / pytest / Kivy（GUI設定のみ）/ gettext（i18n）

**Spec:** `docs/superpowers/specs/2026-08-05-jigo-endgame-humanstyle-design.md`

## Global Constraints

- コミットメッセージは**日本語**・Conventional Commits 形式（`feat:` / `fix:` / `docs:` / `test:`）
- `black` を既存ファイル全体にかけない（コードベースが未整形のため巨大差分になる）。編集した行だけ既存スタイル（インデント4・行長120以内）に合わせる
- `C:\Users\iwaki\.katrain\config.json`（ユーザーローカル設定）の編集は**メインセッションで直接行う**。サブエージェントに委任しない。**KaTrain が起動中は編集しない**（終了時に上書きされて消える）
- `.po` を編集したら必ず `python tools/compile_mo.py` で `.mo` を再コンパイルする
- パッケージ `katrain/config.json` だけ更新して終わらない。ユーザーローカル `config.json` にも同じキーを足さないと GUI に項目が出ない
- Python スクリプトで日本語を扱うときは cp932 対策として `io.open(..., encoding="utf-8")` を明示する。CLI の print は ASCII のみにする
- テスト実行は `pytest --ignore=tests/test_ai.py`（`test_ai.py` は humanSL モデル実体が要る）

## File Structure

| ファイル | 役割 | 変更 |
|---|---|---|
| `katrain/core/ai.py` | 判定純関数（helpers ブロック）＋ `JigoStrategy.generate_move` の委譲分岐 | Modify |
| `tests/test_jigo_endgame.py` | 判定純関数の境界テスト＋委譲配線テスト（KataGo/Kivy 不要） | Create |
| `katrain/core/constants.py` | `AI_OPTION_VALUES` / `AI_OPTION_ORDER` へのウィジェット登録 | Modify |
| `katrain/config.json` | パッケージ同梱デフォルト値 | Modify |
| `C:\Users\iwaki\.katrain\config.json` | ユーザーローカル設定（GUI 表示に必須） | Modify |
| `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po` | 設定項目の短ラベル＋ `aihelp:jigo` / `aihelp:jigo9` 本文 | Modify |
| `.claude/rules/ai-parameters.md`, `CLAUDE.md` | パラメータ表・概要 | Modify |

---

### Task 1: 判定純関数（`_jigo_endgame_threshold` / `_jigo_endgame_handoff`）

**Files:**
- Modify: `katrain/core/ai.py`（`_jigo_exclude_sharp_moves` の直後、`# 動的 rank 降格の chain` コメントの直前＝現在の 749〜750 行目あたり）
- Test: `tests/test_jigo_endgame.py`（新規）

**Interfaces:**
- Consumes: `math`（`ai.py` 冒頭で import 済み）
- Produces:
  - `_jigo_endgame_threshold(board_size: int, settings: dict) -> int`
  - `_jigo_endgame_handoff(board_size: int, move_num: int, last_lead: float | None, target_score: float, settings: dict, sticky: bool = False) -> bool`
  - `_JIGO_ENDGAME_MOVE_KEYS: dict[int, tuple[str, int]]`
  - `board_size` は `max(width, height)`（既存の `_jigo_resolve_phase` と同じ呼び出し規約）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jigo_endgame.py` を新規作成:

```python
# tests/test_jigo_endgame.py
"""持碁モードのヨセ段階 HumanStyle 9段委譲のテスト（KataGo/Kivy 不要）。"""
import pytest

from katrain.core.ai import _jigo_endgame_handoff, _jigo_endgame_threshold


def _s(**kw):
    """チェックボックス ON の settings を作る。"""
    d = {"jigo_endgame_humanstyle": True}
    d.update(kw)
    return d


class TestEndgameThreshold:
    def test_19x19_uses_its_own_key(self):
        assert _jigo_endgame_threshold(19, {"jigo_endgame_move": 170}) == 170

    def test_13x13_uses_its_own_key(self):
        assert _jigo_endgame_threshold(13, {"jigo_endgame_move_13": 70}) == 70

    def test_9x9_uses_its_own_key(self):
        assert _jigo_endgame_threshold(9, {"jigo9_endgame_move": 26}) == 26

    def test_defaults_when_key_absent(self):
        assert _jigo_endgame_threshold(19, {}) == 150
        assert _jigo_endgame_threshold(13, {}) == 85
        assert _jigo_endgame_threshold(9, {}) == 30

    def test_float_slider_value_is_coerced_to_int(self):
        # GUI スライダーは float で保存される（~/.katrain/config.json 実測: 18.0 等）
        assert _jigo_endgame_threshold(19, {"jigo_endgame_move": 160.0}) == 160

    def test_unknown_board_falls_back_to_half_board_convention(self):
        # 他戦略と同じ ceil(0.5 x 盤面マス数)
        assert _jigo_endgame_threshold(15, {}) == 113


class TestEndgameHandoff:
    def test_disabled_never_hands_off(self):
        s = {"jigo_endgame_humanstyle": False, "jigo_endgame_move": 150}
        assert _jigo_endgame_handoff(19, 200, 10.0, 0.5, s) is False

    def test_disabled_ignores_sticky(self):
        s = {"jigo_endgame_humanstyle": False}
        assert _jigo_endgame_handoff(19, 200, 10.0, 0.5, s, sticky=True) is False

    def test_one_move_before_threshold_is_false(self):
        assert _jigo_endgame_handoff(19, 149, 5.0, 0.5, _s(jigo_endgame_move=150)) is False

    def test_exactly_at_threshold_is_true(self):
        assert _jigo_endgame_handoff(19, 150, 5.0, 0.5, _s(jigo_endgame_move=150)) is True

    def test_no_cached_lead_is_false(self):
        assert _jigo_endgame_handoff(19, 200, None, 0.5, _s(jigo_endgame_move=150)) is False

    def test_lead_below_target_is_false(self):
        assert _jigo_endgame_handoff(19, 200, 0.4, 0.5, _s(jigo_endgame_move=150)) is False

    def test_lead_equal_to_target_is_true(self):
        assert _jigo_endgame_handoff(19, 200, 0.5, 0.5, _s(jigo_endgame_move=150)) is True

    def test_sticky_ignores_move_number_and_lead(self):
        s = _s(jigo_endgame_move=150)
        assert _jigo_endgame_handoff(19, 10, -30.0, 0.5, s, sticky=True) is True

    def test_9x9_board_uses_9x9_key(self):
        s = _s(jigo9_endgame_move=30, jigo_endgame_move=150)
        assert _jigo_endgame_handoff(9, 29, 2.0, 0.5, s) is False
        assert _jigo_endgame_handoff(9, 30, 2.0, 0.5, s) is True
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_jigo_endgame.py -v`
Expected: FAIL — `ImportError: cannot import name '_jigo_endgame_handoff' from 'katrain.core.ai'`

- [ ] **Step 3: 純関数を実装**

`katrain/core/ai.py` の `_jigo_exclude_sharp_moves` 関数の直後（`# 動的 rank 降格の chain` コメントの直前）に挿入:

```python
# ヨセ委譲の盤サイズ別スライダーキー（board_size → (設定キー, 既定手数)）
# 19路150 / 9路30 は deception phase3 開始手数と一致（deception の ON/OFF で
# 切替タイミングが動かない）。13路の phase3 開始 83 はスライダーの5刻みに
# 乗らないので、他戦略と同じ共通規約 ceil(0.5 x 169) = 85 を採る。
_JIGO_ENDGAME_MOVE_KEYS = {
    19: ("jigo_endgame_move", 150),
    13: ("jigo_endgame_move_13", 85),
    9: ("jigo9_endgame_move", 30),
}


def _jigo_endgame_threshold(board_size, settings):
    """ヨセ委譲を開始する手数。

    19/13/9 路は盤サイズ別スライダー、それ以外は他戦略と同じ共通規約
    ceil(0.5 × 盤面マス数) にフォールバックする。
    board_size は max(width, height)（既存の呼び出し規約）。
    GUI スライダーは float で保存されるので int() で丸める。
    """
    key_default = _JIGO_ENDGAME_MOVE_KEYS.get(board_size)
    if key_default is None:
        return math.ceil(0.5 * board_size * board_size)
    key, default = key_default
    return int(settings.get(key, default))


def _jigo_endgame_handoff(board_size, move_num, last_lead, target_score, settings, sticky=False):
    """HumanStyle 9段へ委譲すべきか。

    条件: チェックボックス ON かつ
          （sticky＝既に委譲済み）または
          （手数が閾値以上 かつ last_lead が target_score 以上）

    last_lead は前手のキャッシュ（None なら未到達扱い＝委譲しない）。
    比較対象は**ユーザー設定の target_score** であって deception の eff_target
    ではない。phase1/2 の eff_target は負なので、それと比べると「設計どおり
    劣勢に留まっている状態」を到達とみなして即委譲してしまう。
    """
    if not settings.get("jigo_endgame_humanstyle", False):
        return False
    if sticky:
        return True
    if move_num < _jigo_endgame_threshold(board_size, settings):
        return False
    return last_lead is not None and last_lead >= target_score
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_jigo_endgame.py -v`
Expected: PASS（15 tests）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo_endgame.py
git commit -m "feat(jigo): ヨセ委譲の判定純関数を追加"
```

---

### Task 2: `JigoStrategy.generate_move` への委譲分岐

**Files:**
- Modify: `katrain/core/ai.py`（`JigoStrategy.generate_move` 内、Settings ログ出力の直後・`# ---- Phase 解決` コメントの直前＝現在の 1011 行目あたり）
- Test: `tests/test_jigo_endgame.py`（Task 1 で作ったファイルに追記）

**Interfaces:**
- Consumes: Task 1 の `_jigo_endgame_handoff` / `_jigo_endgame_threshold`、既存の `HumanStyleStrategy`（同一モジュール内・`ai.py:5843` 定義）
- Produces:
  - `game._jigo_endgame_handoff: bool` — 一度委譲したら立つ sticky フラグ
  - `strategy.last_decision_info["endgame_handoff"]: bool` — 新キー（`katrain_debug/batch_eval.py:160` が読む dict に追加）
  - 返り値の ai_thoughts は `"[Jigo→9d yose] " + HumanStyle の thoughts`

**注意:** `HumanStyleStrategy` はファイル内で `JigoStrategy` より**後ろ**（5843行目）に定義されているが、参照されるのは `generate_move` の実行時なので前方参照の問題は起きない。クラスの定義順を動かさないこと。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jigo_endgame.py` の末尾に追記:

```python
# ---------------------------------------------------------------------------
# 委譲の配線テスト（フェイクの game/katrain。KataGo エンジンは起動しない）
# ---------------------------------------------------------------------------


class _ReachedStage1(Exception):
    """委譲されずに通常経路（Stage1 クエリ）へ進んだことを示すセンチネル。"""


class _NoEngines(dict):
    def __getitem__(self, key):
        raise _ReachedStage1(key)


class FakeKatrain:
    def __init__(self):
        self.logs = []

    def log(self, msg, level=None):
        self.logs.append(str(msg))


class FakeNode:
    def __init__(self, depth):
        self.depth = depth
        self.analysis_complete = True
        self.next_player = "B"
        self.player = "W"

    def player_sign(self, player):
        # GameNode.player_sign と同じ規約。委譲されなかった経路が
        # self.game.engines に触れるところまで進めるために必要
        return 1 if player == "B" else -1


class FakeGame:
    def __init__(self, depth, board_size=(19, 19)):
        self.board_size = board_size
        self.current_node = FakeNode(depth)
        self.katrain = FakeKatrain()
        self.engines = _NoEngines()


def _patch_humanstyle(monkeypatch, captured):
    """HumanStyleStrategy.generate_move を差し替えてエンジン呼び出しを避ける。"""
    from katrain.core import ai as ai_mod
    from katrain.core.sgf_parser import Move

    def fake_generate(self):
        captured["settings"] = self.settings
        return Move((3, 3), player="B"), "stub thoughts"

    monkeypatch.setattr(ai_mod.HumanStyleStrategy, "generate_move", fake_generate)
    return ai_mod


def test_generate_move_delegates_to_humanstyle_9d(monkeypatch):
    captured = {}
    ai_mod = _patch_humanstyle(monkeypatch, captured)

    game = FakeGame(depth=200)
    game._jigo_last_current_lead = 2.0
    settings = {"jigo_endgame_humanstyle": True, "jigo_endgame_move": 150, "target_score": 0.5}
    strategy = ai_mod.JigoStrategy(game, settings)

    move, thoughts = strategy.generate_move()

    assert move.gtp() == "D4"
    assert thoughts.startswith("[Jigo→9d yose]")
    assert captured["settings"] == {"human_kyu_rank": -8, "modern_style": True}
    assert game._jigo_endgame_handoff is True
    assert strategy.last_decision_info["endgame_handoff"] is True
    assert strategy.last_decision_info["rank_used"] == "rank_9d"
    assert any("Endgame handoff" in line for line in game.katrain.logs)


def test_generate_move_stays_in_jigo_while_behind(monkeypatch):
    captured = {}
    ai_mod = _patch_humanstyle(monkeypatch, captured)

    game = FakeGame(depth=200)
    game._jigo_last_current_lead = -1.0  # target 未到達
    settings = {"jigo_endgame_humanstyle": True, "jigo_endgame_move": 150, "target_score": 0.5}
    strategy = ai_mod.JigoStrategy(game, settings)

    # 委譲されず通常経路へ進み、エンジン参照でセンチネルが飛ぶ
    with pytest.raises(_ReachedStage1):
        strategy.generate_move()

    assert "settings" not in captured
    assert getattr(game, "_jigo_endgame_handoff", False) is False
    assert any("Endgame pending" in line for line in game.katrain.logs)


def test_generate_move_sticky_delegates_even_before_threshold(monkeypatch):
    captured = {}
    ai_mod = _patch_humanstyle(monkeypatch, captured)

    game = FakeGame(depth=20)
    game._jigo_last_current_lead = -30.0
    game._jigo_endgame_handoff = True  # 既に委譲済み
    settings = {"jigo_endgame_humanstyle": True, "jigo_endgame_move": 150, "target_score": 0.5}
    strategy = ai_mod.JigoStrategy(game, settings)

    move, thoughts = strategy.generate_move()

    assert thoughts.startswith("[Jigo→9d yose]")
    assert any("sticky" in line for line in game.katrain.logs)


def test_generate_move_ignores_option_when_disabled(monkeypatch):
    captured = {}
    ai_mod = _patch_humanstyle(monkeypatch, captured)

    game = FakeGame(depth=250)
    game._jigo_last_current_lead = 30.0
    settings = {"jigo_endgame_humanstyle": False, "target_score": 0.5}
    strategy = ai_mod.JigoStrategy(game, settings)

    with pytest.raises(_ReachedStage1):
        strategy.generate_move()

    assert "settings" not in captured
    assert not any("Endgame" in line for line in game.katrain.logs)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_jigo_endgame.py -v -k generate_move`
Expected: FAIL — 4件とも失敗する（委譲分岐が無いので `test_generate_move_delegates_to_humanstyle_9d` は `_ReachedStage1` 例外、sticky も同様）

- [ ] **Step 3: 委譲分岐を実装**

`katrain/core/ai.py` の `JigoStrategy.generate_move` 内、Settings ログ出力（`equivalent_epsilon={equivalent_epsilon}, deception={deception_enabled}` で終わる `self.game.katrain.log(...)` 呼び出し）の直後、`# ---- Phase 解決（jigo_deception=True 時のみ有効値を上書き） ----` コメントの直前に挿入:

```python
        # ---- ヨセ段階の HumanStyle 9段委譲 ----
        # ヨセで target に合わせるための手抜きは相手から見て露骨なので、
        # 目差が target 以上になったら以降は素の9段として打つ。
        # 判定は Stage1/Stage2 の前に行い、目差は前手のキャッシュを使う（1手ラグ）。
        if self.settings.get("jigo_endgame_humanstyle", False):
            board_size_for_endgame = max(self.game.board_size)
            endgame_sticky = getattr(self.game, "_jigo_endgame_handoff", False)
            cached_lead = getattr(self.game, "_jigo_last_current_lead", None)
            endgame_threshold = _jigo_endgame_threshold(board_size_for_endgame, self.settings)
            if _jigo_endgame_handoff(
                board_size_for_endgame, self.cn.depth, cached_lead,
                target_score, self.settings, sticky=endgame_sticky,
            ):
                if endgame_sticky:
                    self.game.katrain.log(
                        "[JigoStrategy] Endgame handoff: sticky (already handed off) "
                        "→ HumanStyle rank_9d",
                        OUTPUT_DEBUG,
                    )
                else:
                    self.game.katrain.log(
                        f"[JigoStrategy] Endgame handoff: move={self.cn.depth} >= "
                        f"thr={endgame_threshold}, lead={cached_lead:.2f} >= "
                        f"target={target_score} → HumanStyle rank_9d",
                        OUTPUT_DEBUG,
                    )
                self.game._jigo_endgame_handoff = True
                self.last_decision_info.update({
                    "rank_used": "rank_9d",
                    "score_lead": cached_lead,
                    "endgame_handoff": True,
                })
                delegate = HumanStyleStrategy(
                    self.game, {"human_kyu_rank": -8, "modern_style": True}
                )
                move, thoughts = delegate.generate_move()
                return move, f"[Jigo→9d yose] {thoughts}"
            if self.cn.depth >= endgame_threshold:
                self.game.katrain.log(
                    f"[JigoStrategy] Endgame pending: move={self.cn.depth} >= "
                    f"thr={endgame_threshold} but lead={cached_lead} < target={target_score}",
                    OUTPUT_DEBUG,
                )
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_jigo_endgame.py -v`
Expected: PASS（19 tests）

- [ ] **Step 5: 既存の持碁テストが壊れていないことを確認**

Run: `pytest tests/test_jigo.py tests/test_jigo9.py tests/test_jigo_deception.py tests/test_batch_eval_jigo.py -v`
Expected: PASS（チェックボックス既定 OFF なので既存挙動は不変）

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo_endgame.py
git commit -m "feat(jigo): ヨセ段階で HumanStyle 9段へ委譲する分岐を追加"
```

---

### Task 3: GUI 設定登録（constants.py＋両方の config.json）

**Files:**
- Modify: `katrain/core/constants.py`（`AI_OPTION_VALUES` の JigoStrategy / Jigo9Strategy ブロック、`AI_OPTION_ORDER` の持碁ブロック）
- Modify: `katrain/config.json`（`ai:jigo` / `ai:jigo9`）
- Modify: `C:\Users\iwaki\.katrain\config.json`（`ai:jigo` / `ai:jigo9`）

**Interfaces:**
- Consumes: Task 1/2 が読む設定キー `jigo_endgame_humanstyle` / `jigo_endgame_move` / `jigo_endgame_move_13` / `jigo9_endgame_move`
- Produces: GUI のチェックボックス1つ＋スライダー（`ai:jigo` に2つ・`ai:jigo9` に1つ）

- [ ] **Step 1: `AI_OPTION_VALUES` にウィジェット種別を登録**

`katrain/core/constants.py`、`"jigo_force_sanrensei": "bool",` の直後に追加:

```python
    "jigo_endgame_humanstyle": "bool",
    "jigo_endgame_move": list(range(120, 210, 10)),  # 120〜200（10刻み・19路用）
    "jigo_endgame_move_13": list(range(55, 95, 5)),  # 55〜90（5刻み・13路用）
```

同ファイルの `# ===== Jigo9Strategy（9路専用） =====` ブロック、`"jigo9_phase2_target": [-0.5, -1.0, -1.5],` の直後に追加:

```python
    "jigo9_endgame_move": [22, 26, 30, 34, 38],
```

- [ ] **Step 2: `AI_OPTION_ORDER` に表示順を登録**

同ファイル、`"jigo_force_sanrensei": 16,` の直後に追加:

```python
    "jigo_endgame_humanstyle": 17,
    "jigo_endgame_move": 18,
    "jigo_endgame_move_13": 19,
```

`"jigo9_phase2_target": 15,` の直後に追加（別セクションなので `jigo_endgame_move` と値が重なっても問題ない）:

```python
    "jigo9_endgame_move": 18,
```

- [ ] **Step 3: パッケージ `config.json` にデフォルト値を追加**

`katrain/config.json` の `"ai"` → `"ai:jigo"` の `"jigo_force_sanrensei": false` の後に追加:

```json
      "jigo_endgame_humanstyle": false,
      "jigo_endgame_move": 150,
      "jigo_endgame_move_13": 85
```

`"ai:jigo9"` の `"jigo9_phase2_target": -0.5` の後に追加:

```json
      "jigo_endgame_humanstyle": false,
      "jigo9_endgame_move": 30
```

インデントは既存の行に合わせること（このファイルは JSON なので、追加した行の前のキーに `,` を付け忘れないよう注意）。

- [ ] **Step 4: 設定ファイルが壊れていないことを確認**

Run:
```bash
python -c "import json,io; d=json.load(io.open('katrain/config.json',encoding='utf-8')); print(sorted(d['ai']['ai:jigo'])); print(sorted(d['ai']['ai:jigo9']))"
```
Expected: `ai:jigo` に `jigo_endgame_humanstyle` / `jigo_endgame_move` / `jigo_endgame_move_13` が、`ai:jigo9` に `jigo_endgame_humanstyle` / `jigo9_endgame_move` が現れる

- [ ] **Step 5: GUI のオプション行数テストを回す**

Run: `pytest tests/test_ai_options_grid.py -v`
Expected: PASS（`ai:jigo` は 17→20 項目になるが、`ai_options_grid_rows` が行数を自動拡張するので `GridLayoutException` は出ない）

- [ ] **Step 6: ユーザーローカル設定に同じキーを追加**

> **この手順はメインセッションで直接 Edit する。サブエージェントに委任しない**（成功報告が出ても実際には反映されないことがある）。**KaTrain が起動していないことを先に確認する**（起動中に編集すると終了時に上書きされて消える）。

`C:\Users\iwaki\.katrain\config.json` の `"ai:jigo"` に:

```json
      "jigo_endgame_humanstyle": false,
      "jigo_endgame_move": 150,
      "jigo_endgame_move_13": 85
```

`"ai:jigo9"` に:

```json
      "jigo_endgame_humanstyle": false,
      "jigo9_endgame_move": 30
```

（ユーザーのローカル値は既定と異なる調整済みの値が入っている。**既存キーの値は絶対に書き換えず、新キーを追加するだけ**にする）

- [ ] **Step 7: ユーザー設定も壊れていないことを確認**

Run:
```bash
python -c "import json,io; d=json.load(io.open('C:/Users/iwaki/.katrain/config.json',encoding='utf-8')); print(sorted(d['ai']['ai:jigo'])); print(sorted(d['ai']['ai:jigo9']))"
```
Expected: 新キーが両セクションに現れ、既存キー（`target_score` 等）が消えていない

- [ ] **Step 8: コミット**

```bash
git add katrain/core/constants.py katrain/config.json
git commit -m "feat(jigo): ヨセ委譲オプションを GUI 設定に登録"
```

（`C:\Users\iwaki\.katrain\config.json` はリポジトリ外なのでコミット対象に含まれない）

---

### Task 4: i18n とドキュメント

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`
- Modify: `.claude/rules/ai-parameters.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task 3 で登録した4つの設定キー名（`msgid` はキー名そのもの）
- Produces: GUI に表示される日本語/英語ラベルと `aihelp:jigo` / `aihelp:jigo9` の説明文

- [ ] **Step 1: 短ラベルの msgid/msgstr を追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `msgid "jigo_force_sanrensei"` / `msgstr` のペアの直後（空行を1つ挟んで）に追加:

```
msgid "jigo_endgame_humanstyle"
msgstr "ヨセは9段で打つ (target 追従をやめ手抜きを止める)"

msgid "jigo_endgame_move"
msgstr "[19路] ヨセ切替手数 (この手数以降・目差が target 以上なら9段)"

msgid "jigo_endgame_move_13"
msgstr "[13路] ヨセ切替手数 (この手数以降・目差が target 以上なら9段)"

msgid "jigo9_endgame_move"
msgstr "[9路] ヨセ切替手数 (この手数以降・目差が target 以上なら9段)"
```

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の `msgid "jigo_force_sanrensei"` / `msgstr` のペアの直後に追加:

```
msgid "jigo_endgame_humanstyle"
msgstr "Play endgame as 9-dan (stop chasing the target score)"

msgid "jigo_endgame_move"
msgstr "[19x19] Endgame switch move (9-dan from here if lead >= target)"

msgid "jigo_endgame_move_13"
msgstr "[13x13] Endgame switch move (9-dan from here if lead >= target)"

msgid "jigo9_endgame_move"
msgstr "[9x9] Endgame switch move (9-dan from here if lead >= target)"
```

- [ ] **Step 2: `aihelp:jigo` / `aihelp:jigo9` の本文に説明を追記**

これらの `msgstr` は1行の長い文字列なので、手編集ではなくスクリプトで末尾に追記する（cp932 でのバイト破壊と改行コード変換を避けるため、UTF-8 明示・`newline=""` で読み書きする）。

以下を `add_endgame_help.py` として保存して実行し、実行後にファイルを削除する:

```python
# add_endgame_help.py -- aihelp の msgstr 末尾に一文を追記する使い捨てスクリプト
import io

JP = (
    "jigo_endgame_humanstyle: ON でヨセ（ヨセ切替手数以降）は target 追従をやめ、"
    "目差が target_score 以上になった手番から HumanStyle 9段としてそのまま打つ"
    "（ヨセの手抜きは相手から見て露骨なので、それを止めるためのオプション）。"
    "劣勢のうちは通常の持碁を続けるので deception の挽回は取りこぼさない。"
    "一度切り替わったら以降は戻らない。相手が弱いとヨセで素直に稼ぐため、"
    "最終的な目差は target を超えて広がりうる。"
)
EN = (
    "jigo_endgame_humanstyle: ON makes the AI stop chasing the target score once "
    "the endgame switch move is reached and the lead is at or above target_score; "
    "from then on it simply plays as HumanStyle 9-dan (holding back during the "
    "endgame is obvious to a human opponent). While still behind it keeps playing "
    "normal jigo, so the deception recovery is not cut short. Once switched it "
    "never switches back. Against a weak opponent the final margin may therefore "
    "grow beyond the target."
)

TARGETS = [
    ("katrain/i18n/locales/jp/LC_MESSAGES/katrain.po", "aihelp:jigo", JP),
    ("katrain/i18n/locales/jp/LC_MESSAGES/katrain.po", "aihelp:jigo9", JP),
    ("katrain/i18n/locales/en/LC_MESSAGES/katrain.po", "aihelp:jigo", EN),
    ("katrain/i18n/locales/en/LC_MESSAGES/katrain.po", "aihelp:jigo9", EN),
]

for path, key, extra in TARGETS:
    src = io.open(path, encoding="utf-8", newline="").read()
    i = src.index('msgid "%s"' % key)
    i = src.index('msgstr "', i) + len('msgstr "')
    eol = src.index("\n", i)
    close = src.rindex('"', i, eol)  # 行末の閉じ引用符（CRLF でも安全）
    src = src[:close] + " " + extra + src[close:]
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    print("updated", path, key)
```

Run: `python add_endgame_help.py && rm add_endgame_help.py`
Expected: `updated ...` が4行出る

- [ ] **Step 3: `.mo` を再コンパイル**

Run: `python tools/compile_mo.py`
Expected: エラーなし（コンパイルしないと GUI にラベルが反映されない）

- [ ] **Step 4: 翻訳が引けることを確認**

`katrain.core.lang` は Kivy を import するので、コンパイル結果は stdlib の `gettext` で直接読む。日本語を print すると cp932 端末で `UnicodeEncodeError` になるため出力は ASCII のみにする。

Run:
```bash
python -c "
import gettext
for lang in ['jp','en']:
    t = gettext.translation('katrain', localedir='katrain/i18n/locales', languages=[lang])
    for k in ['jigo_endgame_humanstyle','jigo_endgame_move','jigo_endgame_move_13','jigo9_endgame_move']:
        print(lang, k, 'TRANSLATED' if t.gettext(k) != k else 'MISSING')
"
```
Expected: 8行すべて `TRANSLATED`（`MISSING` があれば `.po` の追記漏れかコンパイル漏れ）

- [ ] **Step 5: パラメータ表を更新**

`.claude/rules/ai-parameters.md` の「持碁戦略（JigoStrategy）」のパラメータ表、`jigo_force_sanrensei` の行の後に追加:

```markdown
| jigo_endgame_humanstyle | false | ON でヨセ段階（下記手数以降）は target 追従をやめ、目差が target_score 以上になった手番から HumanStyle 9段（rank_9d）へ委譲する。目差判定は前手のキャッシュ（1手ラグ）。劣勢のうちは jigo を継続（＝実質最善手なので手抜きは起きず、deception の挽回も取りこぼさない）。一度委譲したら戻らない（sticky）。副作用: 相手が弱いとヨセで稼ぐため最終目差は target を超えて広がりうる。Spec: docs/superpowers/specs/2026-08-05-jigo-endgame-humanstyle-design.md |
| jigo_endgame_move | 150 | [19路] ヨセ委譲を開始する手数（120〜200・10刻み）。既定は deception phase3 開始手数と同じ |
| jigo_endgame_move_13 | 85 | [13路] 同上（55〜90・5刻み）。既定は共通規約 ceil(0.5×169)=85（phase3 開始 83 は5刻みに乗らないため） |
```

同ファイルの「持碁（9路）戦略（Jigo9Strategy）」のパラメータ表の末尾に追加:

```markdown
| jigo_endgame_humanstyle | false | bool | ON でヨセ段階は HumanStyle 9段へ委譲（19/13路と共通のキー） |
| jigo9_endgame_move | 30 | 22/26/30/34/38 | ヨセ委譲を開始する手数。既定は deception phase3 開始手数と同じ |
```

> `.claude/rules/` 配下の Edit は `dontAsk` モードで拒否されることがある。拒否されたらサブエージェント（Agent tool）経由で編集する。

- [ ] **Step 6: CLAUDE.md の概要を更新**

`CLAUDE.md` の「概要」節、`Jigo には序盤星打ち強制オプション ...` の文に続けて、Jigo の説明の流れの中に次の一文を追加:

```
さらに Jigo/Jigo9 には終盤ヨセの9段委譲オプション `jigo_endgame_humanstyle` を追加（ヨセで target に合わせる手抜きは相手から見て露骨なので、指定手数〈`jigo_endgame_move` 19路150 / `jigo_endgame_move_13` 13路85 / `jigo9_endgame_move` 9路30〉以降かつ目差が target_score 以上になった手番から HumanStyle 9段へ丸ごと委譲する。目差の判定は前手のキャッシュ＝1手ラグ、劣勢のうちは jigo を継続するので deception の挽回を取りこぼさない、一度委譲したら戻らない）。
```

- [ ] **Step 7: 全テストを回す**

Run: `pytest --ignore=tests/test_ai.py -q`
Expected: PASS（既存テストの失敗が出た場合は本変更が原因か切り分ける）

- [ ] **Step 8: コミット**

```bash
git add katrain/i18n .claude/rules/ai-parameters.md CLAUDE.md
git commit -m "docs(jigo): ヨセ委譲オプションの i18n とパラメータ表を追加"
```

---

## 最終検証（GUI 実戦・手動）

実装完了後にユーザーが行う確認。自動テストでは代替できない（`--batch` は per-move ログを抑制し、trajectory 形成型の機能も測れない）。

1. `C:\Users\iwaki\.katrain\config.json` の `"debug_level"` を `1` にして `python -m katrain` で起動
2. AI設定画面で「Kata持碁」を開き、**ヨセは9段で打つ**チェックボックスと**[19路]/[13路] ヨセ切替手数**スライダーが表示されることを確認。「Kata持碁（9路）」でもチェックボックスと **[9路] ヨセ切替手数**が出ること
3. チェックボックスを ON にして13路で1局打ち、ログを確認:
   ```bash
   grep -a "Endgame handoff\|Endgame pending" C:/Users/iwaki/.katrain/logs/game_*.log | tail -20
   ```
   期待: 設定手数以降に `Endgame handoff` が1回出て、以降は `sticky` 行が続く。委譲後の手が `[HumanStyleStrategy]` の経路を通っている
4. `jigo_deception` を ON にして13路でもう1局。phase3 の挽回が終わって目差が target 以上になってから `Endgame handoff` が出ること（それまでは `Endgame pending`）を確認
5. 確認後 `debug_level` を `0` に戻す
