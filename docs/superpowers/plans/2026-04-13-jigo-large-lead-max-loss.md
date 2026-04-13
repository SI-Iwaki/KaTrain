# Jigo 圧勝時 max_loss 動的緩和 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `current_lead ≥ target_score_max + 5` の圧勝局面でのみ `max_loss_per_move` を `8.0` (9路は 5.0) に動的緩和し、target 範囲への収束率を改善する。選択ロジックは現行（hp 重み / argmin）を完全維持。

**Architecture:** 純関数ヘルパ `_jigo_compute_effective_max_loss` を新設し、`JigoStrategy.generate_move()` で `current_lead` 算出を前倒ししてヘルパ呼び出し → effective 値を `_jigo_filter_candidates` / `_jigo_relax_filters` に渡す。GUI 設定 2 個と i18n 翻訳 (jp/en) を追加。

**Tech Stack:** Python 3.12, Kivy GUI, KaTrain 既存パターン (AI_OPTION_VALUES / config.json / .po → .mo)

**関連 spec:** `docs/superpowers/specs/2026-04-13-jigo-large-lead-max-loss-design.md`

---

## File Structure

| ファイル | 役割 | 変更タイプ |
|---|---|---|
| `katrain/core/ai.py` | 純関数ヘルパ追加 + `JigoStrategy.generate_move()` 統合 | 修正（追加 ~30 行） |
| `tests/test_jigo.py` | ヘルパのユニットテスト追加 | 修正（テストクラス追加） |
| `katrain/core/constants.py` | `AI_OPTION_VALUES["jigo"]` と `AI_OPTION_ORDER` に 2 キー追加 | 修正（4 行追加） |
| `katrain/config.json` | パッケージ同梱の jigo デフォルト 2 キー追加 | 修正（2 行追加） |
| `C:\Users\iwaki\.katrain\config.json` | ユーザーローカル設定 2 キー追加 | 修正（メインセッション直接 Edit） |
| `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | 日本語翻訳 2 件 + Kata持碁 help 追記 | 修正 |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 英訳 2 件 + Kata持碁 help 追記 | 修正 |
| `.claude/rules/ai-parameters.md` | Jigo パラメータ表に 2 行追加 | サブエージェント経由 Edit |
| `docs/superpowers/specs/calibration-data/jigo-large-lead-max-loss-results-20260413.md` | グリッド検証結果 | 新規作成 |

---

## Task 1: 純関数ヘルパ `_jigo_compute_effective_max_loss` の追加（TDD）

**Files:**
- Modify: `katrain/core/ai.py`（`_jigo_select_move` 関数の直前、line 770 付近）
- Test: `tests/test_jigo.py`（末尾に `TestJigoComputeEffectiveMaxLoss` クラス追加）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jigo.py` の末尾に追加:

```python
from katrain.core.ai import _jigo_compute_effective_max_loss


class TestJigoComputeEffectiveMaxLoss:
    def test_returns_base_when_lead_below_threshold(self):
        # lead=14 < target_max(10) + delta(5) = 15 → 緩和発動せず
        result = _jigo_compute_effective_max_loss(
            current_lead=14.0, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=19,
        )
        assert result == 5.6

    def test_returns_large_lead_value_when_threshold_exceeded(self):
        # lead=15 == 10 + 5 → 緩和発動
        result = _jigo_compute_effective_max_loss(
            current_lead=15.0, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=19,
        )
        assert result == 8.0

    def test_caps_at_5_for_9x9_board(self):
        # 9路盤では effective を 5.0 にキャップ
        result = _jigo_compute_effective_max_loss(
            current_lead=20.0, target_score_max=10.0, base_max_loss=3.3,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=9,
        )
        assert result == 5.0

    def test_does_not_cap_at_5_for_13x13_board(self):
        # 13路は 9路扱いしない
        result = _jigo_compute_effective_max_loss(
            current_lead=20.0, target_score_max=10.0, base_max_loss=4.0,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=13,
        )
        assert result == 8.0

    def test_never_goes_below_base_max_loss(self):
        # ユーザーが large_lead_max_loss を base より小さく設定しても base を維持
        result = _jigo_compute_effective_max_loss(
            current_lead=20.0, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=5.0, large_lead_max_loss=3.0, board_size=19,
        )
        assert result == 5.6

    def test_threshold_follows_target_score_max(self):
        # target_score_max=5 にすると発動閾値も 5+5=10 に追随
        result = _jigo_compute_effective_max_loss(
            current_lead=10.0, target_score_max=5.0, base_max_loss=5.6,
            large_lead_delta=5.0, large_lead_max_loss=8.0, board_size=19,
        )
        assert result == 8.0

    def test_custom_delta(self):
        # delta=3 にすると 10+3=13 で発動
        result_below = _jigo_compute_effective_max_loss(
            current_lead=12.5, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=3.0, large_lead_max_loss=8.0, board_size=19,
        )
        result_above = _jigo_compute_effective_max_loss(
            current_lead=13.0, target_score_max=10.0, base_max_loss=5.6,
            large_lead_delta=3.0, large_lead_max_loss=8.0, board_size=19,
        )
        assert result_below == 5.6
        assert result_above == 8.0
```

- [ ] **Step 2: テストを実行して失敗を確認**

```bash
pytest tests/test_jigo.py::TestJigoComputeEffectiveMaxLoss -v
```

期待: `ImportError: cannot import name '_jigo_compute_effective_max_loss' from 'katrain.core.ai'`（関数未定義のため import で失敗）

- [ ] **Step 3: 最小実装を追加**

`katrain/core/ai.py` の `_jigo_select_move` 関数の **直前**（line 770 付近、`_JIGO_RANK_CHAIN` 関連の `_select_rank_by_lead` の直後）に追加:

```python
# 9路盤での圧勝時 max_loss 上限（9路は HumanStyle NORMAL_THRESHOLD=3.3 のため緩和を控えめにする）
JIGO_LARGE_LEAD_9X9_CAP = 5.0


def _jigo_compute_effective_max_loss(
    current_lead, target_score_max, base_max_loss,
    large_lead_delta, large_lead_max_loss, board_size,
):
    """current_lead が target_score_max + large_lead_delta を超えた場合のみ max_loss を緩和する。

    9路盤 (board_size <= 9) では effective 値を JIGO_LARGE_LEAD_9X9_CAP (5.0) にキャップする。
    緩和発動しない場合・large_lead_max_loss が base より小さい場合は base_max_loss を返す。
    """
    threshold = target_score_max + large_lead_delta
    if current_lead < threshold:
        return base_max_loss
    effective = large_lead_max_loss
    if board_size <= 9:
        effective = min(effective, JIGO_LARGE_LEAD_9X9_CAP)
    return max(base_max_loss, effective)
```

- [ ] **Step 4: テスト再実行で全 7 件 pass を確認**

```bash
pytest tests/test_jigo.py::TestJigoComputeEffectiveMaxLoss -v
```

期待: 7 件すべて PASS

- [ ] **Step 5: 既存テスト全件 pass を確認**

```bash
pytest tests/test_jigo.py -v
```

期待: 既存テストも含めて全件 PASS

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo.py
git commit -m "$(cat <<'EOF'
feat(jigo): 圧勝時の effective max_loss 算出ヘルパを追加

current_lead が target_score_max + large_lead_delta を超えた場合のみ
max_loss を large_lead_max_loss に緩和する純関数。9路盤は 5.0 にキャップ。
ユーザー設定が base より小さい場合は base を維持。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `JigoStrategy.generate_move()` への統合

**Files:**
- Modify: `katrain/core/ai.py:800-1035`（`JigoStrategy.generate_move()` 内）

- [ ] **Step 1: `current_lead` 算出を前倒し**

`katrain/core/ai.py` の `JigoStrategy.generate_move()` 内、line 922-934 付近の `score_analysis` 確定後、line 936（`scores_player = ...`）の **直前** に以下を挿入:

```python
        # current_lead を前倒し計算（effective max_loss 判定のため）
        current_lead = score_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
```

そして元々 line 991 にあった以下の行を **削除**:

```python
        current_lead = score_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
```

（line 992 以降の `in_range = ...` 等はそのまま残す）

- [ ] **Step 2: 設定読み込みを追加**

line 820 付近の既存設定読み込みブロック（`base_profile = self.settings.get("human_profile", "rank_9d")` の直後）に追加:

```python
        large_lead_delta    = self.settings.get("jigo_large_lead_delta", 5.0)
        large_lead_max_loss = self.settings.get("jigo_large_lead_max_loss", 8.0)
```

そして line 821-825 の `[JigoStrategy] Settings:` ログを以下に置換:

```python
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}, "
            f"profile={base_profile}, dynamic_rank={dynamic_rank}, "
            f"large_lead_delta={large_lead_delta}, large_lead_max_loss={large_lead_max_loss}",
            OUTPUT_DEBUG,
        )
```

- [ ] **Step 3: effective max_loss 算出とフィルタへの適用**

line 970 付近の `filtered = _jigo_filter_candidates(candidates, max_loss, min_hp)` を以下に置換:

```python
        # ---- 圧勝時の max_loss 動的緩和 ----
        board_size = max(self.game.board_size)
        effective_max_loss = _jigo_compute_effective_max_loss(
            current_lead=current_lead,
            target_score_max=target_score_max,
            base_max_loss=max_loss,
            large_lead_delta=large_lead_delta,
            large_lead_max_loss=large_lead_max_loss,
            board_size=board_size,
        )
        if effective_max_loss != max_loss:
            self.game.katrain.log(
                f"[JigoStrategy] Large lead expansion: lead={current_lead:.2f} ≥ "
                f"target_max+{large_lead_delta} = {target_score_max + large_lead_delta:.2f}, "
                f"max_loss: {max_loss} → {effective_max_loss}",
                OUTPUT_DEBUG,
            )

        # ---- フィルタ適用 ----
        filtered = _jigo_filter_candidates(candidates, effective_max_loss, min_hp)
        passed = len(filtered)
        self.game.katrain.log(
            f"[JigoStrategy] Filter: {len(candidates)} → {passed} passed "
            f"(loss<={effective_max_loss}, hp>={min_hp})", OUTPUT_DEBUG
        )
```

（既存の `passed = len(filtered)` 行と次のログ行は上記置換に含まれる）

- [ ] **Step 4: 段階緩和フォールバックも effective 値を使う**

line 978-988 付近の `_jigo_relax_filters` 呼び出しを以下に置換:

```python
        # ---- フォールバック段階緩和 ----
        if not filtered:
            filtered, reason = _jigo_relax_filters(candidates, effective_max_loss, min_hp)
            self.last_decision_info["filter_relaxed"] = True
            self.game.katrain.log(
                f"[JigoStrategy] Fallback triggered: reason={reason}, {len(filtered)} candidates",
                OUTPUT_DEBUG
            )
            if reason == "safety_valve":
                self.game.katrain.log(
                    "[JigoStrategy] Safety valve: using KataGo top move", OUTPUT_ERROR
                )
```

（変更点は `max_loss` → `effective_max_loss` のみ）

- [ ] **Step 5: 既存テストの回帰確認**

```bash
pytest tests/test_jigo.py -v
```

期待: 全件 PASS（generate_move は KataGo 起動が必要なため直接テストされないが、既存ヘルパテストが影響を受けないことを確認）

- [ ] **Step 6: 個別局面で発動ログを確認**

KaTrain 校正用 SGF を使い、圧勝局面（lead ≥ 15）で発動を確認:

```bash
ls docs/superpowers/specs/calibration-data/*.sgf
```

任意の SGF を選び、圧勝局面の手番（例: 60手目以降）で実行:

```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/<chosen.sgf> --move 80 --strategy jigo --output text 2>&1 | grep -E "Settings:|Large lead expansion|Filter:|Mode:|Selected:"
```

期待: `Large lead expansion: lead=XX.XX ≥ target_max+5.0 = 15.00, max_loss: 5.6 → 8.0` のログが出力される（lead が条件を満たす場合）。`Filter: N → M passed (loss<=8.0, ...)` も併せて確認

- [ ] **Step 7: コミット**

```bash
git add katrain/core/ai.py
git commit -m "$(cat <<'EOF'
feat(jigo): 圧勝時 max_loss 緩和を generate_move に統合

current_lead 計算を filter 前に前倒し、_jigo_compute_effective_max_loss
で算出した effective 値を _jigo_filter_candidates / _jigo_relax_filters
に渡す。既存の選択ロジック・鋭手除外は完全現行維持。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `constants.py` と `katrain/config.json` への登録

**Files:**
- Modify: `katrain/core/constants.py:184-198`（`AI_OPTION_VALUES`）と `:245-251`（`AI_OPTION_ORDER`）
- Modify: `katrain/config.json:102-110`（`ai:jigo` セクション）

- [ ] **Step 1: `AI_OPTION_VALUES` に 2 キー追加**

`katrain/core/constants.py` の line 197 `"jigo_dynamic_rank": "bool",` の **直後**（line 198 の `}` の前）に追加:

```python
    "jigo_large_lead_delta": [3.0, 5.0, 7.0, 10.0],
    "jigo_large_lead_max_loss": [6.0, 7.0, 8.0, 9.0, 10.0],
```

- [ ] **Step 2: `AI_OPTION_ORDER` に 2 エントリ追加**

line 251 `"jigo_dynamic_rank": 6,` の **直後**（line 252 の `}` の前）に追加:

```python
    "jigo_large_lead_delta": 7,
    "jigo_large_lead_max_loss": 8,
```

- [ ] **Step 3: `katrain/config.json` の `ai:jigo` にデフォルト追加**

line 109 `"jigo_dynamic_rank": false` を `"jigo_dynamic_rank": false,` に変更（カンマ追加）し、その直後に追加:

```json
            "jigo_large_lead_delta": 5.0,
            "jigo_large_lead_max_loss": 8.0
```

変更後の `ai:jigo` ブロックは:

```json
        "ai:jigo": {
            "target_score": 0.5,
            "target_score_max": 10.0,
            "max_loss_per_move": 5.6,
            "min_human_policy": 0.02,
            "jigo_mode": "natural",
            "human_profile": "rank_9d",
            "jigo_dynamic_rank": false,
            "jigo_large_lead_delta": 5.0,
            "jigo_large_lead_max_loss": 8.0
        },
```

- [ ] **Step 4: black フォーマット適用**

```bash
black katrain/core/constants.py
```

- [ ] **Step 5: 構文チェック**

```bash
python -c "from katrain.core.constants import AI_OPTION_VALUES, AI_OPTION_ORDER; print(AI_OPTION_VALUES['jigo_large_lead_delta']); print(AI_OPTION_ORDER['jigo_large_lead_max_loss'])"
```

期待: `[3.0, 5.0, 7.0, 10.0]` と `8` が出力される

```bash
python -c "import json; print(json.load(open('katrain/config.json'))['ai']['ai:jigo'])"
```

期待: 新キー 2 つを含む dict が出力される

- [ ] **Step 6: コミット**

```bash
git add katrain/core/constants.py katrain/config.json
git commit -m "$(cat <<'EOF'
feat(jigo): 圧勝 max_loss 緩和パラメータを constants/config に登録

jigo_large_lead_delta (発動閾値, デフォルト 5.0)
jigo_large_lead_max_loss (緩和後 max_loss, デフォルト 8.0)
を AI_OPTION_VALUES / AI_OPTION_ORDER / config.json に追加。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: ユーザーローカル `config.json` への追加（メインセッション直接 Edit）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json` の `ai:jigo` セクション

> **CLAUDE.md ルール遵守**: このファイルは **メインセッションで直接 Edit** すること。サブエージェント委任不可。

- [ ] **Step 1: 現状確認**

```bash
python -c "import json; cfg=json.load(open('/c/Users/iwaki/.katrain/config.json'))['ai'].get('ai:jigo', {}); print(cfg)"
```

期待: 既存 jigo 設定が出力される（`jigo_large_lead_*` キーは含まれない）

- [ ] **Step 2: Read で対象ブロックを確認**

`Read` ツールで `C:\Users\iwaki\.katrain\config.json` を読み、`"ai:jigo":` ブロックの末尾を特定する。

- [ ] **Step 3: Edit で 2 キー追加**

`Edit` ツールで以下のように変更（既存値は環境依存のため、見つかったブロックの末尾キーの後にカンマ追加 + 新キー 2 行追加）:

例（既存最終キーが `jigo_dynamic_rank` の場合）:

```
old_string:
            "jigo_dynamic_rank": false
        },

new_string:
            "jigo_dynamic_rank": false,
            "jigo_large_lead_delta": 5.0,
            "jigo_large_lead_max_loss": 8.0
        },
```

> **注意**: ユーザーローカル config の最終キー名は環境により異なる可能性あり。`Read` で実際の末尾キーを確認してから `Edit` の `old_string` を組み立てること。

- [ ] **Step 4: 反映確認**

```bash
python -c "import json; cfg=json.load(open('/c/Users/iwaki/.katrain/config.json'))['ai']['ai:jigo']; print(cfg.get('jigo_large_lead_delta'), cfg.get('jigo_large_lead_max_loss'))"
```

期待: `5.0 8.0` が出力される

- [ ] **Step 5: コミット不要**

ユーザーローカル config は git 管理外。コミットステップなし。

---

## Task 5: i18n 翻訳追加 と `.mo` 再コンパイル

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`

- [ ] **Step 1: jp.po の既存 jigo 翻訳の場所を特定**

```bash
grep -n "jigo_dynamic_rank\|jigo_mode\|max_loss_per_move\|target_score_max\|min_human_policy" katrain/i18n/locales/jp/LC_MESSAGES/katrain.po
```

期待: 各キーの `msgid` 行番号が出力される。これらの翻訳ブロック群の **直後** に新規追加する。

- [ ] **Step 2: jp.po に翻訳追加**

`Edit` で `jigo_dynamic_rank` の翻訳ブロック直後に追加:

```
msgid "jigo_large_lead_delta"
msgstr "圧勝発動目数差 (target_max + Δ で発動)"

msgid "jigo_large_lead_max_loss"
msgstr "圧勝時の許容損失 (目)"
```

- [ ] **Step 3: jp.po の Kata持碁 help 文を更新**

`grep -n "圧勝時は「リードを広げる鋭手」を自動除外" katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` で line を特定し、`Edit` で末尾に追記:

```
old_string: "圧勝時は「リードを広げる鋭手」を自動除外。"
new_string: "圧勝時は「リードを広げる鋭手」を自動除外。current_lead が target_score_max + jigo_large_lead_delta を超えた場合のみ max_loss を jigo_large_lead_max_loss に緩和し、target 範囲への収束率を改善（9路は 5.0 上限）。"
```

- [ ] **Step 4: en.po の同位置に英訳追加**

```bash
grep -n "jigo_dynamic_rank\|Kata Jigo\|target_score_max" katrain/i18n/locales/en/LC_MESSAGES/katrain.po | head -10
```

`jigo_dynamic_rank` の翻訳ブロック直後に `Edit`:

```
msgid "jigo_large_lead_delta"
msgstr "Large-lead trigger delta"

msgid "jigo_large_lead_max_loss"
msgstr "Large-lead max loss (points)"
```

- [ ] **Step 5: en.po の Kata Jigo help 文を更新**

`Edit` で末尾に追記（既存英文 help の末尾に):

```
old_string: <既存末尾文>
new_string: <既存末尾文> When current_lead exceeds target_score_max + jigo_large_lead_delta, max_loss is temporarily relaxed to jigo_large_lead_max_loss to improve convergence into the target range (capped at 5.0 on 9x9).
```

- [ ] **Step 6: `.mo` ファイルを再コンパイル**

```bash
python tools/compile_mo.py
```

期待: エラーなく完了

- [ ] **Step 7: 反映確認（GUI 起動なしで msgfmt の出力確認）**

```bash
python -c "import gettext; t=gettext.translation('katrain', 'katrain/i18n/locales', languages=['jp']); print(t.gettext('jigo_large_lead_delta'))"
```

期待: `圧勝発動目数差 (target_max + Δ で発動)` が出力される

- [ ] **Step 8: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "$(cat <<'EOF'
i18n(jigo): 圧勝時 max_loss 緩和パラメータの翻訳追加

jigo_large_lead_delta / jigo_large_lead_max_loss の jp/en 翻訳と
Kata持碁 help 説明文の追記。.mo を再コンパイル。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `.claude/rules/ai-parameters.md` の更新（サブエージェント経由）

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（Jigo セクション末尾のパラメータ表）

> **CLAUDE.md ルール**: `.claude/rules/` 配下の Edit は dontAsk モードでも拒否されることがあるため、**サブエージェント (Agent tool) 経由で編集・コミット** する。

- [ ] **Step 1: サブエージェントを起動して編集とコミットを依頼**

`Agent` ツール（subagent_type: general-purpose）に以下のタスクを依頼する:

> プロンプト要約: `.claude/rules/ai-parameters.md` の Jigo セクション（「持碁戦略（JigoStrategy）」のパラメータ表）に以下 2 行を追加し、git commit までしてください。
>
> 追加位置: `jigo_dynamic_rank` 行の **直後**
>
> 追加内容:
> ```markdown
> | jigo_large_lead_delta | 5.0 | 圧勝発動目数差。`current_lead ≥ target_score_max + delta` で `max_loss_per_move` を一時的に緩和（Δ=3.0/5.0/7.0/10.0） |
> | jigo_large_lead_max_loss | 8.0 | 圧勝時の許容損失（目）。9路盤は内部で 5.0 にキャップ。値の選択肢: 6.0/7.0/8.0/9.0/10.0 |
> ```
>
> また「設計上の限界」「弱相手対応」セクションのいずれかに以下の 1 行を追加（Jigo の改善履歴として）:
>
> ```markdown
> **圧勝時 max_loss 動的緩和（2026-04-13 追加）**: `current_lead ≥ target_score_max + jigo_large_lead_delta` のとき `max_loss_per_move` を `jigo_large_lead_max_loss (デフォルト 8.0)` に動的緩和。選択ロジック・鋭手除外は完全現行維持で hp 重み選択により target 方向の中 loss 手が候補入りやすくなる。9路盤は 5.0 上限。
> ```
>
> 編集後に以下でコミット:
> ```
> git add .claude/rules/ai-parameters.md
> git commit -m "docs: Jigo 圧勝時 max_loss 緩和パラメータをルールに追記"
> ```
>
> 結果（実際の追加位置の line number と commit hash）を 100 字以内で報告してください。

- [ ] **Step 2: サブエージェントの報告を確認**

サブエージェントからの結果報告を読み、commit hash が報告されていることを確認。`.claude/rules/ai-parameters.md` を `Read` で開いて 2 行が追加されていることをスポットチェック。

---

## Task 7: パラメータグリッド検証（実機 batch_eval）

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-large-lead-max-loss-results-20260413.md`

- [ ] **Step 1: 校正用 SGF を選定**

```bash
ls docs/superpowers/specs/calibration-data/*.sgf
```

弱相手シミュレーションが入っている SGF を選ぶ（`weak_opponent` 等の名前を含むもの優先、なければ既存 jigo 校正 SGF を流用）。選んだファイルパスをメモ。

- [ ] **Step 2: ベースライン取得（緩和 OFF 相当: large_lead_max_loss=5.6）**

```bash
python -m katrain_debug --sgf <selected.sgf> --strategy jigo --batch \
    --settings jigo_large_lead_delta=5.0 jigo_large_lead_max_loss=5.6 \
    --output json > /tmp/jigo_baseline.json 2>/dev/null
```

実行時間: 約 2-3 分（jigo は 1 run でほぼ deterministic のため 1 run のみ）

- [ ] **Step 3: グリッド 6.0 / 8.0 / 10.0 を 3 run ずつ実行**

各 max_loss 値について 3 run 実行（jigo は分散小だが念のため）:

```bash
for VAL in 6.0 8.0 10.0; do
  for RUN in 1 2 3; do
    python -m katrain_debug --sgf <selected.sgf> --strategy jigo --batch \
        --settings jigo_large_lead_delta=5.0 jigo_large_lead_max_loss=$VAL \
        --output json > /tmp/jigo_grid_${VAL}_run${RUN}.json 2>/dev/null
  done
done
```

実行時間: 9 run × ~2-3 分 = 約 20-30 分

- [ ] **Step 4: 集計スクリプトで結果を整形**

既存の `chore: Jigo 校正結果の 3-run 集計スクリプトを追加` (commit 14bdb01) で追加されたスクリプトを使用。スクリプト名を git log で特定:

```bash
git show 14bdb01 --stat
```

期待: 集計用 Python スクリプトのパスが出力される。それを使って /tmp/jigo_grid_*.json を集計。

集計内容:
- target 範囲（0.5〜10目）到達率
- 終局時 lead の平均と分散
- `Notable Divergences` (loss > 6.0) の頻度と平均 hp
- `Large lead expansion` 発動回数

- [ ] **Step 5: 結果を Markdown で記録**

`docs/superpowers/specs/calibration-data/jigo-large-lead-max-loss-results-20260413.md` を新規作成し、以下のテンプレートで記録:

```markdown
# Jigo 圧勝時 max_loss 緩和 グリッド検証結果（2026-04-13）

## 検証 SGF
- パス: `<selected.sgf>`
- 手数: <N>
- 想定局面: 弱相手シミュレーション / 圧勝局面

## 検証パラメータ
- jigo_large_lead_delta: 5.0（固定）
- jigo_large_lead_max_loss: 5.6 (baseline) / 6.0 / 8.0 / 10.0
- 1 設定あたり 3 run

## 結果サマリ

| max_loss | target 到達率 | 終局時 lead 平均 | lead 分散 | Notable Div 頻度 | Large lead 発動 |
|---|---|---|---|---|---|
| 5.6 (baseline) | XX% | XX.X 目 | XX.X | X 回 | 0 回 |
| 6.0 | XX% | XX.X 目 | XX.X | X 回 | XX 回 |
| 8.0 | XX% | XX.X 目 | XX.X | X 回 | XX 回 |
| 10.0 | XX% | XX.X 目 | XX.X | X 回 | XX 回 |

## 判定

<以下のいずれかを記載>

- (a) **8.0 採用**: 6.0/10.0 と比べて target 到達率が改善され、Notable Div 頻度の悪化が許容範囲内
- (b) **設定変更**: <数値> がより良いため `katrain/config.json` のデフォルトを変更し、ユーザーローカル config も更新
- (c) **緩和不要**: 全グリッドで baseline と差がなく、機能無効化（GUI で `large_lead_max_loss=5.6` 推奨）

## Notable Divergence サンプル

<ピックアップした手の局面 + hp + loss を 3-5 件貼る>
```

- [ ] **Step 6: コミット**

```bash
git add docs/superpowers/specs/calibration-data/jigo-large-lead-max-loss-results-20260413.md
git commit -m "$(cat <<'EOF'
docs: Jigo 圧勝時 max_loss 緩和のグリッド検証結果を記録

jigo_large_lead_max_loss=5.6/6.0/8.0/10.0 の 4 グリッド × 3 run で
target 範囲到達率・Notable Divergence 頻度を比較。判定: <a/b/c のいずれか>。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: 判定が (b) の場合のみ追加変更**

`Task 3` および `Task 4` の手順で `katrain/config.json` とユーザーローカル config の `jigo_large_lead_max_loss` 値を変更。`.claude/rules/ai-parameters.md` のデフォルト値も `Task 6` 同様サブエージェント経由で更新。

判定が (a) または (c) の場合はこのステップ不要。

---

## 完了確認

- [ ] 全 Task 完了後、以下で全テスト pass を確認:

```bash
pytest tests/test_jigo.py tests/test_batch_eval_jigo.py -v
```

- [ ] GUI 起動で新パラメータが表示されることを目視確認:

```bash
python -m katrain
```

KaTrain 起動 → AI 設定 → ai:jigo を選択 → 「圧勝発動目数差」と「圧勝時の許容損失」のスライダーが表示されていること、デフォルト値が 5.0 / 8.0 であることを確認。

- [ ] 圧勝局面のリアル対局で発動を確認:

`C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `1` に変更し、`python -m katrain` で起動。Jigo モードで対局し、ログに `[JigoStrategy] Large lead expansion: ...` が出力されることを確認。確認後 `debug_level` を `0` に戻す。
