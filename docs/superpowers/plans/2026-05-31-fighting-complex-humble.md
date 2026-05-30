# 力戦派 complex_humble（力戦派・調整）モード Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 力戦派に新 `fighting_mode` 値 `complex_humble`（GUI「力戦派（調整）」）を追加し、complex の複雑さを保ったまま勝勢時のみ AI 最善手をハード回避して終局時の全局 AI 一致率を相手並みに下げる。

**Architecture:** `_generate_human(complex_mode=True, humble=True)` で complex のパイプラインをそのまま通し、最終選択直前に「謙虚ブロック」を一段挿入。謙虚予算 `max(0, lead − keep_margin)`（互角=0・勝勢ほど増・常にリード未満）が正なら AI 最善手をプールから除き、予算内の複雑手から `humanPolicy×complexity` で確率選択。発動時のみ force-best 機構（安全弁v2・タイブレーク）を抑止。既存 classic/scoreloss/human/complex は無変更。

**Tech Stack:** Python 3.12 / Kivy / pytest / gettext（.po→.mo）。コア改修は `katrain/core/ai.py`。設計仕様: `docs/superpowers/specs/2026-05-31-fighting-complex-humble-design.md`。

---

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `katrain/core/ai.py` | 純関数 `_humble_budget` / `_humble_keep_indices`、`_generate_human` の謙虚ブロック・dispatch | Modify |
| `tests/test_fighting_complexity.py` | 純関数のユニットテスト | Modify |
| `katrain/core/constants.py` | `fighting_mode` 値・`complexity_humble_margin` の GUI 定義 | Modify |
| `katrain/config.json` | パッケージ既定値 | Modify |
| `C:\Users\iwaki\.katrain\config.json` | ユーザーローカル既定値（GUI 表示に必須） | Modify（**メインセッションで直接**） |
| `katrain/gui/controlspanel.py` | プレイヤー欄のモード表示を「調整」にマップ | Modify |
| `katrain/i18n/locales/jp,en/LC_MESSAGES/katrain.po` | ラベル・aihelp 翻訳 | Modify |
| `.claude/rules/ai-parameters.md` / `CLAUDE.md` | パラメータ表・概要 | Modify（rules はサブエージェント経由） |

> **注意（CLAUDE.md 由来の落とし穴）**
> - `black katrain/` を**ファイル全体に走らせない**（未整形コードベースのため巨大差分になる）。編集箇所のみ line-length=120 で手動整形。
> - ユーザーローカル `C:\Users\iwaki\.katrain\config.json` の編集は**メインセッションで直接 Edit**（サブエージェント委任で反映漏れの実績あり）。
> - `.claude/rules/*` の Edit は `dontAsk` で拒否される実績あり → **サブエージェント経由で編集**。
> - `.po` 編集後は `python tools/compile_mo.py` で `.mo` を再コンパイルしないと翻訳が反映されない。

---

## Task 1: 純関数 `_humble_budget` / `_humble_keep_indices` ＋ ユニットテスト（TDD・モデル不要）

**Files:**
- Modify: `katrain/core/ai.py`（`_floor_budget_weights` 定義の直後、現状 2820-2848 付近のモジュール関数群）
- Test: `tests/test_fighting_complexity.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fighting_complexity.py` の import 群（11行目 `_floor_budget_weights` の下）に追加:

```python
from katrain.core.ai import _humble_budget
from katrain.core.ai import _humble_keep_indices
```

ファイル末尾（287行目の後）に追加:

```python
class TestHumbleBudget:
    def test_even_is_zero(self):
        assert _humble_budget(3.0, 5.0) == 0.0

    def test_at_margin_is_zero(self):
        assert _humble_budget(5.0, 5.0) == 0.0

    def test_winning_grows_linearly(self):
        assert _humble_budget(12.0, 5.0) == 7.0

    def test_budget_always_below_lead(self):
        # reserve 厳守: budget < lead が常に成り立つ（keep_margin>0 のとき）
        for lead in (8.0, 20.0, 50.0):
            assert _humble_budget(lead, 5.0) < lead

    def test_negative_lead_is_zero(self):
        assert _humble_budget(-4.0, 5.0) == 0.0


class TestHumbleKeepIndices:
    def test_inactive_when_budget_zero(self):
        assert _humble_keep_indices(["A", "B"], [0.0, 1.0], "A", 0.0) is None

    def test_inactive_when_no_best_gtp(self):
        assert _humble_keep_indices(["A", "B"], [0.0, 1.0], None, 5.0) is None

    def test_drops_best_keeps_within_budget(self):
        # best=A(idx0). B(idx1) loss2<=5 → keep [1]
        assert _humble_keep_indices(["A", "B"], [0.0, 2.0], "A", 5.0) == [1]

    def test_inactive_when_only_over_budget_alternatives(self):
        # best=A. B loss7>budget5 → 予算内代替なし → None
        assert _humble_keep_indices(["A", "B"], [0.0, 7.0], "A", 5.0) is None

    def test_keeps_only_within_budget_among_many(self):
        # best=A(0). B loss2<=5 keep, C loss8>5 drop, D loss1<=5 keep → [1,3]
        assert _humble_keep_indices(["A", "B", "C", "D"], [0.0, 2.0, 8.0, 1.0], "A", 5.0) == [1, 3]

    def test_best_only_move_returns_none(self):
        # プールに best しかない → 代替なし → None
        assert _humble_keep_indices(["A"], [0.0], "A", 5.0) is None
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_fighting_complexity.py::TestHumbleBudget tests/test_fighting_complexity.py::TestHumbleKeepIndices -v`
Expected: FAIL（`ImportError: cannot import name '_humble_budget'`）

- [ ] **Step 3: 純関数を実装**

`katrain/core/ai.py` の `_floor_budget_weights` 関数定義の直後（現状 2848 付近、`def _apply_cut_boost` の直前）に追加:

```python
def _humble_budget(current_lead, keep_margin):
    """謙虚予算 = max(0, リード - keep_margin)。

    互角(lead<=keep_margin)でゼロ、勝勢ほど増える。keep_margin>0 のとき常に
    budget < current_lead なので、予算内の手だけ選べば1手で勝ちを手放さない。
    """
    return max(0.0, current_lead - keep_margin)


def _humble_keep_indices(gtps, losses, best_gtp, budget):
    """謙虚ブロックの選択プール(keep index 列)を返す。

    budget>0 かつ「best_gtp 以外で loss<=budget」の手が1つ以上あれば、その手
    (best 除外・loss<=budget) の index リストを返す。条件未達なら None(=不発)。
    gtps/losses は同じ並びの平行配列。
    """
    if budget <= 0.0 or not best_gtp:
        return None
    keep = [
        i for i, (g, l) in enumerate(zip(gtps, losses))
        if g != best_gtp and l <= budget
    ]
    return keep if keep else None
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/test_fighting_complexity.py::TestHumbleBudget tests/test_fighting_complexity.py::TestHumbleKeepIndices -v`
Expected: PASS（11 個）

- [ ] **Step 5: 既存の純関数テストも回帰確認**

Run: `python -m pytest tests/test_fighting_complexity.py -v`
Expected: 全 PASS（既存 + 新規）

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py tests/test_fighting_complexity.py
git commit -m "feat(fighting): complex_humble の純関数 _humble_budget/_humble_keep_indices 追加"
```

---

## Task 2: `_generate_human` に謙虚ブロックを統合 ＋ dispatch

**Files:**
- Modify: `katrain/core/ai.py`
  - dispatch: `2159-2160`
  - シグネチャ + 開始ログ: `2285-2290`
  - 謙虚セットアップ + 安全弁v2 ゲート: `2618-2621` の直前/条件
  - 謙虚ブロック挿入 + タイブレークゲート: `2742`（top5 算出直前）/ `2755`
  - ラベル: `2789`

> モデルが必要なため `_generate_human` の自動ユニットテストは不可（CLAUDE.md: complex 系の検証は GUI 実戦のみ）。本タスクの自動検証は「import が通る」「Task 1 の純関数テストが緑のまま」「black 差分が編集箇所限定」。挙動検証は最後の GUI スモーク。

- [ ] **Step 1: dispatch に `complex_humble` を追加**

`katrain/core/ai.py:2159-2160` を:

```python
        elif mode == "complex":
            return self._generate_human(complex_mode=True)
```

の直後に分岐を追加して:

```python
        elif mode == "complex":
            return self._generate_human(complex_mode=True)
        elif mode == "complex_humble":
            return self._generate_human(complex_mode=True, humble=True)
```

- [ ] **Step 2: `_generate_human` のシグネチャと開始ログを更新**

`katrain/core/ai.py:2285-2290` を:

```python
    def _generate_human(self, complex_mode: bool = False) -> Tuple[Move, str]:
        """案B: HumanStyleStrategy拡張 + 力戦重みで着手選択"""
        self.game.katrain.log(
            f"[FightingStrategy:{'complex' if complex_mode else 'human'}] Starting move generation",
            OUTPUT_DEBUG,
        )
```

に置換:

```python
    def _generate_human(self, complex_mode: bool = False, humble: bool = False) -> Tuple[Move, str]:
        """案B: HumanStyleStrategy拡張 + 力戦重みで着手選択。

        humble=True は complex_mode=True を包含し、勝勢時のみ AI 最善手を回避する
        謙虚ブロックを最終選択直前に挿入する（complex_humble モード）。
        """
        _mode_label = "humble" if humble else ("complex" if complex_mode else "human")
        self.game.katrain.log(
            f"[FightingStrategy:{_mode_label}] Starting move generation",
            OUTPUT_DEBUG,
        )
```

- [ ] **Step 3: 安全弁v2 の直前に謙虚セットアップを挿入し、安全弁v2 を条件付き抑止**

`katrain/core/ai.py:2618-2621`、現状:

```python
        # 安全弁v2: 最高重み候補のlossが閾値以上なら最善スコア手を確定選択
        # 安全弁v1はmove_infosの最多探索手を対象とするが、実際に選ばれる手は
        # humanPolicy×fighting_weightで決まるため、v2でその手を直接チェックする
        if moves and move_infos and best_gtp_by_score:
```

を、セットアップ挿入 + 条件変更して:

```python
        # --- 謙虚（complex_humble）セットアップ ---
        # current_lead/current_move/board_size/best_gtp_by_score は既に算出済み。
        # endgame_threshold は後段(2696)定義のため、ここでは self.game.board_size から直接計算する。
        keep_margin = self.settings.get("complexity_humble_margin", 5.0)
        humble_budget = _humble_budget(current_lead, keep_margin) if humble else 0.0
        _hb = self.game.board_size
        _eg_threshold_h = 32 if (_hb[0] == 9 and _hb[1] == 9) else math.ceil(_hb[0] * _hb[1] * 0.5)
        is_endgame_h = current_move >= _eg_threshold_h
        humble_may_fire = humble and humble_budget > 0.0 and not is_endgame_h
        humble_active = False

        # 安全弁v2: 最高重み候補のlossが閾値以上なら最善スコア手を確定選択
        # 安全弁v1はmove_infosの最多探索手を対象とするが、実際に選ばれる手は
        # humanPolicy×fighting_weightで決まるため、v2でその手を直接チェックする
        # （謙虚発動見込み時は最善手へ引き戻すこの機構を抑止する）
        if not humble_may_fire and moves and move_infos and best_gtp_by_score:
```

> `current_lead` / `current_move` / `best_gtp_by_score` / `board_size`(=`self.game.board_size`) はすべて 2618 行より前で定義済み（確認済み: current_move=2384, best_gtp_by_score=2403, current_lead=2456/2463）。`math` は既に import 済み。

- [ ] **Step 4: 謙虚ブロックを挿入（top5 算出の直前）し、タイブレークを抑止**

`katrain/core/ai.py:2743` の top5 デバッグ:

```python
        # デバッグ: 上位5手表示
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
```

の**直前**に謙虚ブロックを挿入:

```python
        # --- 謙虚ブロック: 勝勢時のみ AI 最善手を除外し、予算内の複雑手プールから選ぶ ---
        # ゲート通過済み(good_moves)・sacrifice floor 適用済みの moves を対象にする。
        # 選択プールは「best 除外・loss<=humble_budget」に限定し、reserve(lead-keep_margin)を厳守。
        if humble_may_fire and moves and best_gtp_by_score and best_gtp_by_score != "pass":
            _loss_by_gtp_h = {
                mi.get("move", ""): player_sign * (best_score - mi.get("scoreLead", 0))
                for mi in (move_infos or [])
            }
            _gtps_h = [m.gtp() for m, _ in moves]
            _losses_h = [_loss_by_gtp_h.get(g, 0.0) for g in _gtps_h]
            _keep_h = _humble_keep_indices(_gtps_h, _losses_h, best_gtp_by_score, humble_budget)
            if _keep_h is not None:
                moves = [moves[i] for i in _keep_h]
                humble_active = True
                self.game.katrain.log(
                    f"[FightingStrategy:humble] active: lead={current_lead:.1f} "
                    f"keep_margin={keep_margin} budget={humble_budget:.1f} "
                    f"dropped best={best_gtp_by_score} (pool={len(moves)})",
                    OUTPUT_DEBUG,
                )

        # デバッグ: 上位5手表示
        top5 = sorted(moves, key=lambda x: -x[1])[:5]
```

次に、タイブレークの発火条件 `katrain/core/ai.py:2755`:

```python
        if len(top5) >= 2 and move_infos:
```

を、謙虚発動時はスキップするよう変更:

```python
        # 謙虚発動時は最善手へ引き戻すタイブレークを抑止
        if not humble_active and len(top5) >= 2 and move_infos:
```

- [ ] **Step 5: 最終ラベルに humble を反映**

`katrain/core/ai.py:2789`:

```python
        label = "Complex+Fighting" if complex_mode else "Human+Fighting"
```

を:

```python
        if humble_active:
            label = "Humble+Fighting"
        elif complex_mode:
            label = "Complex+Fighting"
        else:
            label = "Human+Fighting"
```

- [ ] **Step 6: import とテストの健全性を確認**

Run: `python -c "import katrain.core.ai; print('ok')"`
Expected: `ok`（構文エラーなし）

Run: `python -m pytest tests/test_fighting_complexity.py -v`
Expected: 全 PASS（純関数の回帰）

- [ ] **Step 7: 編集箇所のみ整形差分か確認（ファイル全体 black 禁止）**

Run: `git diff --stat katrain/core/ai.py`
Expected: 変更行が Task 2 の編集範囲（dispatch / シグネチャ / 安全弁v2 / 謙虚ブロック / タイブレーク / ラベル）に限定。意図しない全体再フォーマットが無いこと。

- [ ] **Step 8: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat(fighting): complex_humble モードの謙虚ブロックを_generate_humanに統合"
```

---

## Task 3: GUI 定義（constants.py）

**Files:**
- Modify: `katrain/core/constants.py`
  - `fighting_mode` 値リスト: `152-157`
  - `AI_OPTION_VALUES` の新キー: `167` の直後
  - 表示順 dict: `237` の直後

- [ ] **Step 1: `fighting_mode` に `complex_humble` を追加**

`katrain/core/constants.py:152-157` を:

```python
    "fighting_mode": [
        ("classic", "[fighting:classic]"),
        ("scoreloss", "[fighting:scoreloss]"),
        ("human", "[fighting:human]"),
        ("complex", "[fighting:complex]"),
    ],
```

に `complex_humble` 行を足して:

```python
    "fighting_mode": [
        ("classic", "[fighting:classic]"),
        ("scoreloss", "[fighting:scoreloss]"),
        ("human", "[fighting:human]"),
        ("complex", "[fighting:complex]"),
        ("complex_humble", "[fighting:complex_humble]"),
    ],
```

- [ ] **Step 2: `complexity_humble_margin` を `AI_OPTION_VALUES` に追加**

`katrain/core/constants.py:167`（`complexity_sharpness_min` 行）の直後に追加:

```python
    "complexity_humble_margin": [2.0, 3.0, 5.0, 8.0, 10.0, 15.0],  # 調整: この差以上リードでAI最善手回避を解禁（小さいほど早く発動）
```

- [ ] **Step 3: 表示順 dict に登録**

`katrain/core/constants.py:237`（`"complexity_sharpness_min": 10,`）の直後に追加:

```python
    "complexity_humble_margin": 11,
```

- [ ] **Step 4: 反映を確認**

Run:
```bash
python -c "from katrain.core.constants import AI_OPTION_VALUES; print('complex_humble' in [v[0] for v in AI_OPTION_VALUES['fighting_mode']]); print('complexity_humble_margin' in AI_OPTION_VALUES)"
```
Expected: `True` / `True`

- [ ] **Step 5: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat(fighting): complex_humble モードとcomplexity_humble_marginのGUI定義追加"
```

---

## Task 4: 既定値（config.json × 2）

**Files:**
- Modify: `katrain/config.json:186`（`ai:p:fighting`）
- Modify: `C:\Users\iwaki\.katrain\config.json:186`（同・**メインセッションで直接編集**）

- [ ] **Step 1: パッケージ config に既定値追加**

`katrain/config.json`、`"complexity_sharpness_min": 3.0,`（186行目）の直後に追加:

```json
            "complexity_humble_margin": 5.0,
```

- [ ] **Step 2: ユーザーローカル config に同キー追加（メインセッションで直接 Edit）**

`C:\Users\iwaki\.katrain\config.json`、`"complexity_sharpness_min": 3.0,`（186行目）の直後に同じ行を追加:

```json
            "complexity_humble_margin": 5.0,
```

- [ ] **Step 3: 両ファイルの JSON 妥当性とキー存在を確認**

Run:
```bash
python -c "import json; d=json.load(open(r'katrain/config.json',encoding='utf-8')); print(d['ai']['ai:p:fighting']['complexity_humble_margin'])"
python -c "import json; d=json.load(open(r'C:\Users\iwaki\.katrain\config.json',encoding='utf-8')); print(d['ai']['ai:p:fighting']['complexity_humble_margin'])"
```
Expected: `5.0` / `5.0`（どちらもパース成功）

- [ ] **Step 4: コミット**（ユーザーローカルは git 管理外なのでパッケージ config のみ）

```bash
git add katrain/config.json
git commit -m "feat(fighting): complexity_humble_margin の既定値(5.0)を追加"
```

---

## Task 5: プレイヤー欄のモード表示を「調整」にマップ（controlspanel.py）

**Files:**
- Modify: `katrain/gui/controlspanel.py:99`

- [ ] **Step 1: 表示マッピングを追加**

`katrain/gui/controlspanel.py:99`:

```python
                self.players[bw].rank = fighting_settings.get("fighting_mode", "classic")
```

を:

```python
                _fmode = fighting_settings.get("fighting_mode", "classic")
                # complex_humble は GUI 表示名「調整」（→ 力戦派 (調整)）。他モードは raw 値のまま。
                self.players[bw].rank = {"complex_humble": "調整"}.get(_fmode, _fmode)
```

- [ ] **Step 2: import 健全性を確認**

Run: `python -c "import ast; ast.parse(open(r'katrain/gui/controlspanel.py',encoding='utf-8').read()); print('ok')"`
Expected: `ok`（構文エラーなし。Kivy 実 import は GUI 起動時に確認）

- [ ] **Step 3: コミット**

```bash
git add katrain/gui/controlspanel.py
git commit -m "feat(gui): 力戦派 complex_humble のプレイヤー表示を「調整」にマップ"
```

---

## Task 6: i18n（jp / en .po ＋ .mo 再コンパイル）

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`

- [ ] **Step 1: jp .po にモード名ラベルを追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:505-506`:

```
msgid "fighting:complex"
msgstr "複雑化"
```

の直後（507 空行の後）に追加:

```
msgid "fighting:complex_humble"
msgstr "調整"
```

- [ ] **Step 2: jp .po にパラメータ短ラベルを追加**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:657-658`:

```
msgid "complexity_sharpness_min"
msgstr "鋭さ閾値(scoreStdev)"
```

の直後に追加:

```
msgid "complexity_humble_margin"
msgstr "調整マージン(この差で最善手回避)"
```

- [ ] **Step 3: jp .po の `aihelp:fighting` 本文に complex_humble 説明を追記**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po:643` の complex 説明行:

```
"complexモード: 接触戦の密度を上げ盤面を複雑化する。大差リード時のみ、鋭く複雑な手に限り損失を緩和する（complexity_* 各設定）。"
```

の直後（同じ msgstr 連結ブロック内）に1行追加:

```
"complex_humble（調整）モード: complexの複雑さを保ったまま、勝勢時のみAI最善手を避けて一致率を相手並みに下げる。complexity_humble_margin（既定5.0目）以上リードしたら発動し、互角では普通に最強で打つ。"
```

- [ ] **Step 4: en .po に同等のエントリを追加**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po:791-792`:

```
msgid "fighting:complex"
msgstr "Complex"
```

の直後に追加:

```
msgid "fighting:complex_humble"
msgstr "Humble"
```

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po:970-971`:

```
msgid "complexity_sharpness_min"
msgstr "Sharpness gate (scoreStdev)"
```

の直後に追加:

```
msgid "complexity_humble_margin"
msgstr "Humble margin (avoid best when ahead)"
```

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po:956` の complex 説明行:

```
"complex mode: maximizes contact-fight density; only when winning by a large margin does it allow extra loss, and only for sharp/complex moves (see complexity_* settings)."
```

の直後に1行追加:

```
"complex_humble mode: keeps complex's complexity but, only when clearly ahead, avoids KataGo's top move to bring move-match rate down toward the opponent's. Triggers once the lead exceeds complexity_humble_margin (default 5.0); plays normally (strongest) when even."
```

- [ ] **Step 5: .mo を再コンパイル**

Run: `python tools/compile_mo.py`
Expected: エラーなく終了（jp/en の .mo が更新される）

- [ ] **Step 6: 翻訳が引けることを確認**

Run:
```bash
python -c "import polib; po=polib.pofile(r'katrain/i18n/locales/jp/LC_MESSAGES/katrain.po'); print([e.msgstr for e in po if e.msgid=='fighting:complex_humble'])"
```
Expected: `['調整']`
（polib 未導入なら本確認はスキップし、Step 5 の compile_mo 成功と GUI スモークで代替）

- [ ] **Step 7: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "i18n(fighting): complex_humble(調整)モードとcomplexity_humble_marginの翻訳追加"
```

---

## Task 7: ドキュメント更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（**サブエージェント経由で編集・コミット**）
- Modify: `CLAUDE.md`

- [ ] **Step 1: `.claude/rules/ai-parameters.md` の力戦派セクションを更新（サブエージェント）**

サブエージェント（Agent tool）に以下を依頼:
- 「力戦派モード（FightingStrategy）」表の `fighting_mode` 行の選択肢に `complex_humble` を追記
- 「### complexモード（複雑化）」の後に「### complex_humble モード（調整）」小節を追加。内容:
  - complex のパイプライン・complexity_* を流用し、勝勢時のみ AI 最善手をハード回避して終局時の全局 AI 一致率を相手並みに下げるモード（GUI「力戦派（調整）」）
  - 謙虚予算 `max(0, current_lead − complexity_humble_margin)`。互角=0（現行 complex と同一）、勝勢ほど増、常に lead 未満（勝ちを手放さない）
  - 発動時のみ安全弁v2・タイブレークを抑止。選択は予算内の非・最善手から `humanPolicy×complexity` 確率選択。ヨセ区間は不発
  - パラメータ表に `complexity_humble_margin`（既定 5.0、選択肢 2/3/5/8/10/15、小さいほど接戦でも発動＝全局平均一致率がより下がる主校正ダイヤル）を追加
  - 検証は GUI 実戦のみ（batch_eval はリード軌跡を作れず不可）。`grep -a "FightingStrategy:humble"` で発火確認
  - Spec: `docs/superpowers/specs/2026-05-31-fighting-complex-humble-design.md`
- 編集後 `git add .claude/rules/ai-parameters.md && git commit -m "docs(rules): complex_humble モードのパラメータ表を追記"` まで実行

- [ ] **Step 2: `CLAUDE.md` の概要にモードを追記**

`CLAUDE.md` の「## 概要」内、力戦派 complex を説明している箇所:

```
力戦派には複雑化モード `complex`（切りボーナス＋リード適応の損失予算ゲートで盤面を紛れさせる）を追加。
```

の文の直後に追記:

```
さらに力戦派には `complex_humble`（GUI「力戦派（調整）」）を追加。complex の複雑さを保ったまま、勝勢時のみ AI 最善手を回避して終局時の全局 AI 最善手一致率を相手並みに下げる（校正ダイヤルは `complexity_humble_margin`）。
```

- [ ] **Step 3: CLAUDE.md をコミット**

```bash
git add CLAUDE.md
git commit -m "docs: complex_humble(力戦派・調整)モードを概要に追記"
```

---

## Task 8: GUI スモーク検証（手動・モデル必要）

> 自動テスト不可の挙動部分を実機確認する。CLAUDE.md「変更の検証方法」に準拠。

- [ ] **Step 1: デバッグ有効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` を `1` に変更。

- [ ] **Step 2: 起動して GUI を確認**

Run: `python -m katrain`
確認:
- AI 設定で力戦派の `fighting_mode` ドロップダウンに「調整」(complex_humble) が出る
- `complexity_humble_margin` スライダーが表示される（保存済みキーが両 config にあること）
- 力戦派（調整）を選んだプレイヤー欄が「力戦派 (調整)」と表示される

- [ ] **Step 3: 対局して発火を確認**

力戦派（調整）で対局し、コンソール/ログを確認:

Run（別端末でログ tail 相当、または対局後にログを grep）: `grep -a "FightingStrategy:humble" <ログ>`
確認:
- 勝勢の局面で `active: lead=... budget=... dropped best=...` が出る（最善手除外が発動）
- 互角の局面では発火しない（現行 complex のまま＝ログに humble active が出ない）
- 盤面が complex 同様に接触・切りで複雑になっている（**特徴喪失なら設計上の却下条件** → 要再検討）

- [ ] **Step 4: `complexity_humble_margin` の校正メモ**

数局打って終局時の全局 AI 一致率（相手 vs 自分）を比較。自分側が相手並みに下がるまで `complexity_humble_margin` を小さくする方向で調整（接戦寄りでも発動）。

- [ ] **Step 5: デバッグ無効化**

`C:\Users\iwaki\.katrain\config.json` の `"debug_level"` を `0` に戻す。

---

## Self-Review（記録）

- **Spec coverage**: §3.1 dispatch→Task2/Step1, §3.2 謙虚ブロック→Task1+Task2/Step4, §3.3 force-best抑止→Task2/Step3(安全弁v2)+Step4(タイブレーク), §3.4 ヨセ除外→Task2/Step3(`is_endgame_h`、加えて endgame branch が先に return), §4 新パラメータ→Task3/4, §5 変更ファイル→Task2-7, §6 テスト→Task1+Task8。全節にタスク対応あり。
- **Placeholder scan**: TBD/TODO なし。各コードステップに実コード掲載。
- **Type/名前整合**: `_humble_budget` / `_humble_keep_indices` / `humble_may_fire` / `humble_active` / `humble_budget` / `keep_margin` / `complexity_humble_margin` / `complex_humble` を全タスクで一貫使用。純関数の引数順（gtps, losses, best_gtp, budget）が Task1 定義と Task2 呼び出しで一致。
