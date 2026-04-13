# JigoStrategy 弱相手対応 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JigoStrategy を弱相手（3〜7段相当）との対局でも AI らしさを保てるよう拡張する。鋭手除外・humanPolicy フロア強化・humanSL rank 設定可能化・動的 rank 切替（opt-in）の4点を追加。

**Architecture:** 既存の2段階クエリ＋フィルタ構造は維持し、純粋関数（鋭手除外／rank 選択）と設定項目を追加する。`JigoStrategy.generate_move` の3箇所（rank 決定／フィルタ後／ターン終了時キャッシュ）に統合する。TDD で純粋関数を先行実装、統合は既存フローに最小侵襲で追加。

**Tech Stack:** Python 3.12 / KaTrain v1.17.1.1 / pytest / KataGo v1.16.4 humanSL

**Spec:** `docs/superpowers/specs/2026-04-13-jigo-weak-opponent-design.md`

---

## File Structure

### 新規作成ファイル
（なし。既存ファイルへの追加のみ）

### 変更ファイル
| パス | 役割 | 変更内容 |
|---|---|---|
| `katrain/core/ai.py` | JigoStrategy 本体 | 純粋関数3つ追加・`generate_move` 3箇所に統合・`__init__` でキャッシュ初期化 |
| `katrain/core/constants.py` | 設定項目定義 | `AI_OPTION_VALUES` / `AI_OPTION_ORDER` に2キー追加 |
| `katrain/config.json` | パッケージ既定値 | `ai:jigo` に2キー追加・`min_human_policy` を 0.02 に |
| `C:\Users\iwaki\.katrain\config.json` | ユーザ設定 | 同上（**メインセッションで直接編集、サブエージェント委任不可**） |
| `tests/test_jigo.py` | 単体テスト | 既存 `TestJigoFilterCandidates` などに追加、新クラス3つ追加 |
| `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` | 日本語 | `aihelp:jigo` 更新 |
| `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` | 英語 | `aihelp:jigo` 更新 |
| `katrain/i18n/locales/**/katrain.mo` | コンパイル済み | `python tools/compile_mo.py` で再生成 |
| `.claude/rules/ai-parameters.md` | パラメータ表 | JigoStrategy セクション更新（**サブエージェント経由で編集** — `feedback_claude_rules_edit.md` 参照） |

---

## Task 1: 鋭手除外純粋関数 `_jigo_exclude_sharp_moves`

**Files:**
- Modify: `katrain/core/ai.py`（`_jigo_select_move` 関数の直前に追加）
- Test: `tests/test_jigo.py`

- [ ] **Step 1: 失敗するテストを追加**

`tests/test_jigo.py` の末尾に以下を追加：

```python
class TestJigoExcludeSharpMoves:
    def test_excludes_moves_with_score_above_current_lead(self):
        from katrain.core.ai import _jigo_exclude_sharp_moves
        cands = [
            _c("A1", 22.0, 0.0, 0.10),  # score > lead=20.0 → 除外
            _c("B2", 18.0, 4.0, 0.05),  # score < lead → 残る
            _c("C3", 15.0, 7.0, 0.05),  # score < lead → 残る
        ]
        result = _jigo_exclude_sharp_moves(cands, current_lead=20.0)
        assert [c["move"] for c in result] == ["B2", "C3"]

    def test_epsilon_tolerates_tiny_overshoot(self):
        from katrain.core.ai import _jigo_exclude_sharp_moves
        cands = [
            _c("A1", 20.4, 0.0, 0.10),  # +0.4 over, within epsilon=0.5
            _c("B2", 20.6, 0.0, 0.10),  # +0.6 over, beyond epsilon
        ]
        result = _jigo_exclude_sharp_moves(cands, current_lead=20.0)
        assert [c["move"] for c in result] == ["A1"]

    def test_returns_original_when_all_candidates_would_be_excluded(self):
        from katrain.core.ai import _jigo_exclude_sharp_moves
        cands = [
            _c("A1", 25.0, 0.0, 0.10),
            _c("B2", 30.0, 0.0, 0.10),
        ]
        result = _jigo_exclude_sharp_moves(cands, current_lead=20.0)
        # 全滅なら元のリストを返す（安全弁）
        assert result == cands

    def test_empty_input_returns_empty(self):
        from katrain.core.ai import _jigo_exclude_sharp_moves
        result = _jigo_exclude_sharp_moves([], current_lead=20.0)
        assert result == []
```

- [ ] **Step 2: テスト失敗を確認**

Run: `pytest tests/test_jigo.py::TestJigoExcludeSharpMoves -v`
Expected: 4 FAIL with `ImportError: cannot import name '_jigo_exclude_sharp_moves'`

- [ ] **Step 3: 関数を実装**

`katrain/core/ai.py` の `_jigo_select_move` 関数の直前（現在の 719 行目付近）に追加：

```python
# 鋭手除外用バッファ（KataGo scoreLead の微細ノイズを許容）
SHARP_EPSILON = 0.5


def _jigo_exclude_sharp_moves(candidates, current_lead, epsilon=SHARP_EPSILON):
    """圧勝時に「現在リードをさらに広げる手」を除外する。

    score > current_lead + epsilon の候補を落とす。
    除外結果が空になる場合は元のリストを返す（安全弁）。
    """
    non_sharp = [c for c in candidates if c["score"] <= current_lead + epsilon]
    return non_sharp if non_sharp else candidates
```

- [ ] **Step 4: テスト成功を確認**

Run: `pytest tests/test_jigo.py::TestJigoExcludeSharpMoves -v`
Expected: 4 PASSED

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo.py
git commit -m "feat: JigoStrategy 鋭手除外ヘルパー _jigo_exclude_sharp_moves を追加"
```

---

## Task 2: 動的 rank 選択関数 `_select_rank_by_lead`

**Files:**
- Modify: `katrain/core/ai.py`（Task 1 で追加した関数の直後に配置）
- Test: `tests/test_jigo.py`

- [ ] **Step 1: 失敗するテストを追加**

`tests/test_jigo.py` の末尾に以下を追加：

```python
class TestSelectRankByLead:
    def test_no_downshift_when_delta_small(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta = 15 - 10 = 5、閾値（>5）未満 → 降格なし
        assert _select_rank_by_lead(15.0, 10.0, "rank_9d") == "rank_9d"

    def test_one_step_downshift_for_medium_delta(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta = 20 - 10 = 10、5 < delta <= 15 → 1段下
        assert _select_rank_by_lead(20.0, 10.0, "rank_9d") == "rank_7d"

    def test_two_step_downshift_for_large_delta(self):
        from katrain.core.ai import _select_rank_by_lead
        # delta = 30 - 10 = 20、delta > 15 → rank_5d まで一気に
        assert _select_rank_by_lead(30.0, 10.0, "rank_9d") == "rank_5d"

    def test_downshift_respects_floor(self):
        from katrain.core.ai import _select_rank_by_lead
        # base=rank_5d で delta > 15 → すでに下限
        assert _select_rank_by_lead(30.0, 10.0, "rank_5d") == "rank_5d"

    def test_downshift_from_rank_7d(self):
        from katrain.core.ai import _select_rank_by_lead
        # base=rank_7d, delta 10 (5<delta<=15) → 1段下で rank_5d
        assert _select_rank_by_lead(20.0, 10.0, "rank_7d") == "rank_5d"

    def test_unknown_base_profile_returned_unchanged(self):
        from katrain.core.ai import _select_rank_by_lead
        # chain にないプロファイルはそのまま返す
        assert _select_rank_by_lead(30.0, 10.0, "pro_pre-az") == "pro_pre-az"

    def test_negative_delta_no_downshift(self):
        from katrain.core.ai import _select_rank_by_lead
        # 自分が劣勢 → delta < 0 → 降格なし
        assert _select_rank_by_lead(-5.0, 10.0, "rank_9d") == "rank_9d"
```

- [ ] **Step 2: テスト失敗を確認**

Run: `pytest tests/test_jigo.py::TestSelectRankByLead -v`
Expected: 7 FAIL with `ImportError: cannot import name '_select_rank_by_lead'`

- [ ] **Step 3: 関数を実装**

`katrain/core/ai.py` の `_jigo_exclude_sharp_moves` の直後に追加：

```python
# 動的 rank 降格の chain（下位 → 上位）
_JIGO_RANK_CHAIN = ["rank_5d", "rank_7d", "rank_9d"]


def _select_rank_by_lead(current_lead, target_score_max, base_profile):
    """リードが target_max を超えた度合いに応じて humanSL rank を降格する。

    - delta ≤ 5  : base_profile そのまま
    - 5 < delta ≤ 15 : base_profile より 1段下（9d→7d, 7d→5d, 5d→5d）
    - delta > 15 : 一気に rank_5d まで下げる

    base_profile が _JIGO_RANK_CHAIN に含まれない場合はそのまま返す。
    """
    if base_profile not in _JIGO_RANK_CHAIN:
        return base_profile
    delta = current_lead - target_score_max
    idx = _JIGO_RANK_CHAIN.index(base_profile)
    if delta > 15:
        new_idx = 0  # rank_5d 固定
    elif delta > 5:
        new_idx = max(0, idx - 1)
    else:
        new_idx = idx
    return _JIGO_RANK_CHAIN[new_idx]
```

- [ ] **Step 4: テスト成功を確認**

Run: `pytest tests/test_jigo.py::TestSelectRankByLead -v`
Expected: 7 PASSED

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo.py
git commit -m "feat: JigoStrategy 動的 rank 選択ヘルパー _select_rank_by_lead を追加"
```

---

## Task 3: `_jigo_relax_filters` にハードフロア追加

**Files:**
- Modify: `katrain/core/ai.py`（既存 `_jigo_relax_filters` の改修、700 行付近）
- Test: `tests/test_jigo.py`

- [ ] **Step 1: 失敗するテストを追加**

`tests/test_jigo.py` の `class TestJigoRelaxFilters` の末尾に以下を追加：

```python
    def test_hard_floor_prevents_relaxation_below_0_005(self):
        # min_hp=0.01 で hp×0.25 = 0.0025 になるはずだが、ハードフロア 0.005 で止まる
        # → hp=0.003 の候補は通らない、hp=0.006 の候補は hp_half で通る
        cands = [
            _c("A1", 5.0, 1.0, 0.003),  # hp < ハードフロア → 通さない
            _c("B2", 5.0, 1.0, 0.006),  # hp_half (0.005) で通る
        ]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert [c["move"] for c in result] == ["B2"]
        assert reason == "hp_half"

    def test_hard_floor_with_user_lowering_min_hp(self):
        # min_hp=0.005 でも hp×0.25=0.00125 → 0.005 にクリップ
        # hp=0.004 の候補は通らない
        cands = [_c("A1", 5.0, 1.0, 0.004)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.005)
        # ハードフロアに阻まれ safety_valve へ
        assert reason == "safety_valve"
        assert result == [cands[0]]  # 先頭候補を返す

    def test_hard_floor_allows_exactly_at_floor(self):
        # hp=0.005 ちょうど → ハードフロアに一致して通る
        cands = [_c("A1", 5.0, 1.0, 0.005)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert [c["move"] for c in result] == ["A1"]
        assert reason == "hp_half"
```

**注意**: 既存テスト `test_second_relax_step_hp_quarter` と `test_loss_relax_step` は hp=0.003 を使っており、新ハードフロアで失敗に変わる。両方とも修正が必要：

```python
    def test_second_relax_step_hp_quarter(self):
        # hp×0.25 = 0.0025 だが、ハードフロア 0.005 で止まる
        # → hp=0.005 の候補が hp_quarter で通る（hp_half=0.005 より下だが hp_quarter=max(0.0025,0.005)=0.005）
        # 実際には hp_half=0.005 で先に通るため、このテストは成立しない
        # → hp=0.006 を使って hp_half で通るパターンに変更
        cands = [_c("A1", 5.0, 1.0, 0.006)]
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "hp_half"  # ← hp_quarter から hp_half に変更

    def test_loss_relax_step(self):
        # hp=0.005（ハードフロア）で hp_half/hp_quarter は同じ条件に。
        # loss が max_loss を超えていれば loss_150 に落ちる。
        cands = [_c("A1", 5.0, 7.0, 0.005)]  # loss 7.0 < 5.6*1.5=8.4
        result, reason = _jigo_relax_filters(cands, max_loss=5.6, min_hp=0.01)
        assert len(result) == 1
        assert reason == "loss_150"
```

上記2テストは **差し替え**（削除→新版追加）する。

- [ ] **Step 2: テスト失敗を確認**

Run: `pytest tests/test_jigo.py::TestJigoRelaxFilters -v`
Expected: 新3テストと差し替え2テストが FAIL（ハードフロア未実装のため挙動が違う）

- [ ] **Step 3: 関数を改修**

`katrain/core/ai.py` の `_jigo_relax_filters` を以下で置換：

```python
# humanPolicy ハードフロア（これ以下には絶対に緩和しない）
MIN_HP_HARD_FLOOR = 0.005


def _jigo_relax_filters(candidates, max_loss, min_hp, hard_floor=MIN_HP_HARD_FLOOR):
    """両フィルタ不通過時の段階緩和。

    返り値: (filtered_list, reason) — reason は "hp_half" / "hp_quarter" / "loss_150" / "safety_valve"。
    hp×0.5 → hp×0.25 → loss×1.5 → safety valve。

    各段階で hp 閾値は max(min_hp × factor, hard_floor) でクリップされる。
    """
    reason_map = [("hp_half", 0.5), ("hp_quarter", 0.25)]
    for reason, hp_factor in reason_map:
        threshold = max(min_hp * hp_factor, hard_floor)
        f = [c for c in candidates
             if c["loss"] <= max_loss and c["hp"] >= threshold]
        if f:
            return f, reason
    threshold = max(min_hp * 0.25, hard_floor)
    f = [c for c in candidates
         if c["loss"] <= max_loss * 1.5 and c["hp"] >= threshold]
    if f:
        return f, "loss_150"
    # Safety valve: 先頭候補（呼び出し側で KataGo 最善手が先頭に来るよう渡す前提）
    return ([candidates[0]] if candidates else []), "safety_valve"
```

- [ ] **Step 4: テスト成功を確認**

Run: `pytest tests/test_jigo.py::TestJigoRelaxFilters -v`
Expected: 全テスト PASSED（既存 + 新規含む）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_jigo.py
git commit -m "refactor: _jigo_relax_filters に humanPolicy ハードフロア 0.005 を追加"
```

---

## Task 4: `constants.py` に新設定項目を追加

**Files:**
- Modify: `katrain/core/constants.py`（185-191 行、236-243 行付近）

- [ ] **Step 1: `AI_OPTION_VALUES` に `human_profile` と `jigo_dynamic_rank` を追加**

`katrain/core/constants.py` の `"jigo_mode": [...]` の直後（約 191 行）に以下を挿入：

```python
    "human_profile": [
        ("rank_5d", "5段"),
        ("rank_7d", "7段"),
        ("rank_9d", "9段"),
    ],
    "jigo_dynamic_rank": "bool",
```

変更箇所の完成形（`AI_OPTION_VALUES` 内 JigoStrategy セクション）:

```python
    # ===== JigoStrategy =====
    "target_score_max": [5.0, 10.0, 15.0],
    "max_loss_per_move": [3.0, 4.0, 5.6, 7.0],
    "min_human_policy": [(0.005, "0.5%"), (0.01, "1%"), (0.02, "2%"), (0.05, "5%")],
    "jigo_mode": [
        ("natural", "natural"),
        ("maintain", "maintain"),
    ],
    "human_profile": [
        ("rank_5d", "5段"),
        ("rank_7d", "7段"),
        ("rank_9d", "9段"),
    ],
    "jigo_dynamic_rank": "bool",
}
```

- [ ] **Step 2: `AI_OPTION_ORDER` に順序を追加**

`AI_OPTION_ORDER` の `"jigo_mode": 4,` の直後（約 243 行）に以下を挿入：

```python
    "human_profile": 5,
    "jigo_dynamic_rank": 6,
```

変更箇所の完成形：

```python
    "target_score": 0,
    "target_score_max": 1,
    "max_loss_per_move": 2,
    "min_human_policy": 3,
    "jigo_mode": 4,
    "human_profile": 5,
    "jigo_dynamic_rank": 6,
}
```

- [ ] **Step 3: 構文チェック**

Run: `python -c "from katrain.core.constants import AI_OPTION_VALUES, AI_OPTION_ORDER; print(AI_OPTION_VALUES['human_profile']); print(AI_OPTION_ORDER['jigo_dynamic_rank'])"`
Expected:
```
[('rank_5d', '5段'), ('rank_7d', '7段'), ('rank_9d', '9段')]
6
```

- [ ] **Step 4: コミット**

```bash
git add katrain/core/constants.py
git commit -m "feat: constants.py に human_profile と jigo_dynamic_rank を追加"
```

---

## Task 5: パッケージ `config.json` 既定値を更新

**Files:**
- Modify: `katrain/config.json`（102-108 行）

- [ ] **Step 1: `ai:jigo` セクションを更新**

`katrain/config.json` の 102-108 行を以下で置換：

```json
        "ai:jigo": {
            "target_score": 0.5,
            "target_score_max": 10.0,
            "max_loss_per_move": 5.6,
            "min_human_policy": 0.02,
            "jigo_mode": "natural",
            "human_profile": "rank_9d",
            "jigo_dynamic_rank": false
        },
```

変更点: `min_human_policy` を 0.01 → 0.02、`human_profile` と `jigo_dynamic_rank` を追加。

- [ ] **Step 2: 構文チェック**

Run: `python -c "import json; d=json.load(open('katrain/config.json', encoding='utf-8')); print(d['ai']['ai:jigo'])"`
Expected:
```
{'target_score': 0.5, 'target_score_max': 10.0, 'max_loss_per_move': 5.6, 'min_human_policy': 0.02, 'jigo_mode': 'natural', 'human_profile': 'rank_9d', 'jigo_dynamic_rank': False}
```

- [ ] **Step 3: コミット**

```bash
git add katrain/config.json
git commit -m "feat: パッケージ config.json の ai:jigo に新キー追加・min_human_policy=0.02"
```

---

## Task 6: ユーザ `config.json` を更新（メインセッション必須）

> **重要**: `C:\Users\iwaki\.katrain\config.json` の編集は **必ずメインセッションで直接実行**してください。サブエージェントに委任すると成功報告されても反映されないことがあります（CLAUDE.md「やってはいけないこと」参照）。

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（`ai:jigo` セクション）

- [ ] **Step 1: 現在の `ai:jigo` セクションを確認**

Read `C:\Users\iwaki\.katrain\config.json` で該当箇所を読み、現在のキー構成を把握する。

- [ ] **Step 2: `ai:jigo` セクションを更新**

既存キーに以下を追加（`target_score` / `target_score_max` / `max_loss_per_move` / `jigo_mode` はそのまま）：
- `min_human_policy`: 既存値が 0.01 なら **0.02 に上書き**（ユーザが明示的に別値を選んでいた場合はそのまま）
- `human_profile`: 新規追加、値 `"rank_9d"`
- `jigo_dynamic_rank`: 新規追加、値 `false`

JSON 編集時は Edit ツールで `old_string` / `new_string` を明示指定（全体 Write は避ける）。

- [ ] **Step 3: 構文チェック**

Run: `python -c "import json; d=json.load(open(r'C:\Users\iwaki\.katrain\config.json', encoding='utf-8')); print(d['ai']['ai:jigo'])"`
Expected: 7キーすべてが表示される。

- [ ] **Step 4: GUI で表示確認（手動）**

`python -m katrain` で起動 → AI設定（Kata持碁選択）→ `human_profile` のスライダーと `jigo_dynamic_rank` のチェックボックスが表示されることを確認。

（この手順はコミット対象外：ユーザローカル設定はリポジトリ外ファイル）

---

## Task 7: `JigoStrategy.generate_move` に鋭手除外を統合

**Files:**
- Modify: `katrain/core/ai.py`（`JigoStrategy.generate_move` 内、894-912 行付近）

- [ ] **Step 1: 鋭手除外の挿入位置を特定**

`_jigo_relax_filters` 呼び出し後・`_jigo_select_move` 呼び出し前の箇所（現在の約 905-912 行、`current_lead` 計算後）。

- [ ] **Step 2: コードを統合**

以下の置換を行う：

**置換前**（約 905-912 行）:

```python
        # ---- 現在リード & 選択分岐 ----
        current_lead = score_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
        in_range = target_score <= current_lead <= target_score_max
        self.game.katrain.log(
            f"[JigoStrategy] Mode: {mode}, lead={current_lead:.2f}, in_range={in_range}",
            OUTPUT_DEBUG,
        )
        pick = _jigo_select_move(filtered, current_lead, target_score, target_score_max, mode)
```

**置換後**:

```python
        # ---- 現在リード & 選択分岐 ----
        current_lead = score_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
        in_range = target_score <= current_lead <= target_score_max
        self.game.katrain.log(
            f"[JigoStrategy] Mode: {mode}, lead={current_lead:.2f}, in_range={in_range}",
            OUTPUT_DEBUG,
        )

        # ---- 鋭手除外（圧勝時のみ） ----
        if current_lead > target_score_max:
            before_exclude = len(filtered)
            filtered = _jigo_exclude_sharp_moves(filtered, current_lead)
            self.game.katrain.log(
                f"[JigoStrategy] Sharp-move exclusion: {before_exclude} → {len(filtered)} "
                f"(lead={current_lead:.2f} > target_max={target_score_max})",
                OUTPUT_DEBUG,
            )

        pick = _jigo_select_move(filtered, current_lead, target_score, target_score_max, mode)
```

- [ ] **Step 3: import の確認**

`katrain/core/ai.py` の冒頭で `_jigo_exclude_sharp_moves` を特別にインポートする必要はない（同一モジュール内の関数）。

- [ ] **Step 4: 既存テストが壊れていないことを確認**

Run: `pytest tests/test_jigo.py -v`
Expected: 全テスト PASSED

- [ ] **Step 5: Kivy 非依存の smoke test（構文確認）**

Run: `python -c "from katrain.core.ai import JigoStrategy; print('OK')"`
Expected: `OK`（ImportError 等が出ないこと）

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: JigoStrategy.generate_move に鋭手除外ロジックを統合"
```

---

## Task 8: `human_profile` 設定を Stage 1 クエリで使用

**Files:**
- Modify: `katrain/core/ai.py`（`JigoStrategy.generate_move` 内、752-767 行付近）

- [ ] **Step 1: 設定読み込み箇所を更新**

**置換前**（約 752-767 行）:

```python
        # ---- 設定読み込み ----
        target_score     = self.settings.get("target_score", 0.5)
        target_score_max = self.settings.get("target_score_max", 10.0)
        max_loss         = self.settings.get("max_loss_per_move", 5.6)
        min_hp           = self.settings.get("min_human_policy", 0.01)
        mode             = self.settings.get("jigo_mode", "natural")
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}", OUTPUT_DEBUG
        )

        sign = self.cn.player_sign(self.cn.next_player)
        engine = self.game.engines[self.cn.player]

        # ---- Stage 1: humanSL 9段固定クエリ ----
        human_profile = "rank_9d"  # 9段固定（HuntStrategy/SiegeStrategy/FightingStrategy と同じ表記）
```

**置換後**:

```python
        # ---- 設定読み込み ----
        target_score     = self.settings.get("target_score", 0.5)
        target_score_max = self.settings.get("target_score_max", 10.0)
        max_loss         = self.settings.get("max_loss_per_move", 5.6)
        min_hp           = self.settings.get("min_human_policy", 0.02)
        mode             = self.settings.get("jigo_mode", "natural")
        base_profile     = self.settings.get("human_profile", "rank_9d")
        dynamic_rank     = self.settings.get("jigo_dynamic_rank", False)
        self.game.katrain.log(
            f"[JigoStrategy] Settings: target={target_score}, max={target_score_max}, "
            f"max_loss={max_loss}, min_hp={min_hp}, mode={mode}, "
            f"profile={base_profile}, dynamic_rank={dynamic_rank}", OUTPUT_DEBUG
        )

        sign = self.cn.player_sign(self.cn.next_player)
        engine = self.game.engines[self.cn.player]

        # ---- Stage 1 用 humanSL rank 決定（Task 9 で dynamic_rank を統合） ----
        human_profile = base_profile
```

- [ ] **Step 2: smoke test**

Run: `python -c "from katrain.core.ai import JigoStrategy; print('OK')"`
Expected: `OK`

- [ ] **Step 3: `katrain_debug` での動作確認**

Run:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --settings human_profile=rank_7d --output text 2>&1 | grep -E "Settings:|Stage1"
```
Expected: ログに `profile=rank_7d` が含まれること。

- [ ] **Step 4: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: JigoStrategy で human_profile 設定を Stage 1 クエリに反映"
```

---

## Task 9: 動的 rank 切替（D-a）を統合

**Files:**
- Modify: `katrain/core/ai.py`（`JigoStrategy` クラス全体）

- [ ] **Step 1: `__init__` でキャッシュ初期化を追加**

`@register_strategy(AI_JIGO)` の直下、`JigoStrategy` クラス定義内に `__init__` を追加（既存の `generate_move` の前）：

```python
@register_strategy(AI_JIGO)
class JigoStrategy(AIStrategy):
    """Jigo strategy - target を狙いつつ大差時も人間らしさを維持する戦略。

    ロジック:
        1. Stage 1 (humanSL rank指定) で humanPolicy を取得
        2. Stage 2 (clean) で正確な scoreLead を取得
        3. loss <= max_loss_per_move AND hp >= min_human_policy でフィルタ
        4. 圧勝時（lead > target_max）は鋭手除外を適用
        5. current_lead × jigo_mode で選択ロジック分岐
        6. 候補ゼロ時は段階緩和 → 最終的に KataGo 最善手へフォールバック

    動的 rank（jigo_dynamic_rank=True）: 前ターンの current_lead をキャッシュし、
    lead-delta に応じて Stage 1 の rank を降格。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 動的 rank 用: 前ターン末尾の current_lead をキャッシュ
        self._last_current_lead = None

    def generate_move(self) -> Tuple[Move, str]:
        ...（既存）
```

**注意**: AIStrategy の親クラスシグネチャによっては `__init__` 受け入れ方式が異なる。既存 HuntStrategy 等が `__init__` をオーバーライドしているか確認すること：

Run: `grep -n "def __init__" katrain/core/ai.py | head -20`

オーバーライド例が見つからなければ、AIStrategy は `__init__` を持たない（`AIStrategy` が dataclass 等で自動生成されている可能性）。その場合はクラス変数ではなく **インスタンス属性を `generate_move` の冒頭で遅延初期化**する方式に切り替える：

```python
def generate_move(self) -> Tuple[Move, str]:
    if not hasattr(self, "_last_current_lead"):
        self._last_current_lead = None
    ...
```

上記どちらか動作するパターンを採用する。

- [ ] **Step 2: Stage 1 の rank 決定に動的判定を組み込む**

Task 8 で追加した箇所を以下で置換：

**置換前**:

```python
        # ---- Stage 1 用 humanSL rank 決定（Task 9 で dynamic_rank を統合） ----
        human_profile = base_profile
```

**置換後**:

```python
        # ---- Stage 1 用 humanSL rank 決定 ----
        if dynamic_rank and self._last_current_lead is not None:
            human_profile = _select_rank_by_lead(
                self._last_current_lead, target_score_max, base_profile
            )
            self.game.katrain.log(
                f"[JigoStrategy] Dynamic rank: base={base_profile}, "
                f"last_lead={self._last_current_lead:.2f}, "
                f"delta={self._last_current_lead - target_score_max:.2f} → {human_profile}",
                OUTPUT_DEBUG,
            )
        else:
            human_profile = base_profile
```

- [ ] **Step 3: ターン末尾で current_lead をキャッシュ**

`generate_move` の末尾 `return aimove, ai_thoughts` の直前（約 928 行）に追加：

```python
        # ---- 次ターンの動的 rank 判定用にキャッシュ ----
        self._last_current_lead = current_lead

        return aimove, ai_thoughts
```

- [ ] **Step 4: smoke test**

Run: `python -c "from katrain.core.ai import JigoStrategy; print('OK')"`
Expected: `OK`

- [ ] **Step 5: `katrain_debug` での単点確認（静的、キャッシュ未起動）**

Run:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --settings jigo_dynamic_rank=true --output text 2>&1 | grep -E "Dynamic rank|Settings:"
```
Expected: `dynamic_rank=True` がログに出る。単点実行ではキャッシュが立ち上がらないため `Dynamic rank:` ログは出ない可能性あり（初手扱い）。

- [ ] **Step 6: 既存テストが壊れていないことを確認**

Run: `pytest tests/test_jigo.py -v`
Expected: 全テスト PASSED

- [ ] **Step 7: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat: JigoStrategy に動的 rank 切替（lead-delta ベース）を統合"
```

---

## Task 10: i18n `aihelp:jigo` を更新

**Files:**
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`（526-527 行）
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`（対応行）

- [ ] **Step 1: 日本語版を更新**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の 526-527 行を以下で置換：

**置換前**:
```
msgid "aihelp:jigo"
msgstr "target_score〜target_score_max 目の僅差で勝つことをめざします。1手あたり max_loss_per_move 目以下 & humanPolicy >= min_human_policy の手のみ選び、人間らしくない悪手を避けます。jigo_mode: natural=範囲内は最善手 / maintain=常に target に寄せる."
```

**置換後**:
```
msgid "aihelp:jigo"
msgstr "target_score〜target_score_max 目の僅差で勝つことをめざします。1手あたり max_loss_per_move 目以下 & humanPolicy >= min_human_policy の手のみ選び、人間らしくない悪手を避けます。jigo_mode: natural=範囲内は最善手 / maintain=常に target に寄せる。human_profile: humanSL の段位（rank_5d/7d/9d）。jigo_dynamic_rank: ON でリード差に応じて rank を自動降格（弱い相手にも対応）。圧勝時は「リードを広げる鋭手」を自動除外。"
```

- [ ] **Step 2: 英語版を更新**

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` で `msgid "aihelp:jigo"` を検索：

Run: `grep -n 'aihelp:jigo' katrain/i18n/locales/en/LC_MESSAGES/katrain.po`

見つかった行の `msgstr` を以下に置換：

```
msgstr "Aims to win by a narrow margin of target_score..target_score_max points. Picks moves with per-move loss <= max_loss_per_move and humanPolicy >= min_human_policy, avoiding unnaturally bad moves. jigo_mode: natural=best move within range / maintain=always push toward target. human_profile: humanSL rank (rank_5d/7d/9d). jigo_dynamic_rank: ON to auto-downshift rank based on lead delta (handles weaker opponents). Sharp moves that widen the lead are excluded when overshooting."
```

もし `aihelp:jigo` が英語版に存在しない場合は、該当日本語版の直上に同じ行構造を追加する。

- [ ] **Step 3: `.mo` ファイルを再コンパイル**

Run: `python tools/compile_mo.py`
Expected: `.mo` ファイルが両ロケールで更新される（exit code 0）。

- [ ] **Step 4: GUI 表示確認（手動・オプション）**

`python -m katrain` → AI設定ポップアップ → Kata持碁 選択 → 新設定項目が表示され、説明文が更新されていることを確認。

- [ ] **Step 5: コミット**

```bash
git add katrain/i18n/locales/jp/LC_MESSAGES/katrain.po katrain/i18n/locales/en/LC_MESSAGES/katrain.po katrain/i18n/locales/jp/LC_MESSAGES/katrain.mo katrain/i18n/locales/en/LC_MESSAGES/katrain.mo
git commit -m "docs(i18n): aihelp:jigo に human_profile/jigo_dynamic_rank の説明を追記"
```

---

## Task 11: `.claude/rules/ai-parameters.md` を更新

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（JigoStrategy セクション）

> **注意**: `.claude/rules/` 配下の編集は `dontAsk` モードで拒否されることがあるため、**サブエージェント経由で編集**する（CLAUDE.md `feedback_claude_rules_edit.md` 参照）。

- [ ] **Step 1: サブエージェントに編集を依頼**

以下のプロンプトでサブエージェント（general-purpose）を起動：

```
C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1\.claude\rules\ai-parameters.md の「持碁戦略（JigoStrategy）」セクションのみを更新してください。

変更内容：
1. 既存パラメータ表の下に新規パラメータ2行を追加:
   - human_profile | "rank_9d" | humanSL 段位（rank_5d/rank_7d/rank_9d）
   - jigo_dynamic_rank | false | ON でリード差に応じて rank を自動降格
2. 既存の min_human_policy 行のデフォルト値を 0.01 → 0.02 に更新
3. 設計上の限界セクションの後に以下を追記:

**弱相手対応（2026-04-13 追加）**: 以下の機構で改善:
- 鋭手除外: 圧勝時（lead > target_score_max）、score > current_lead + 0.5 の候補を除外
- humanPolicy ハードフロア 0.005（段階緩和が 0.5% 未満に落ちない）
- 動的 rank（opt-in）: lead-delta > 5 で1段降格、> 15 で rank_5d 固定。base_profile から chain `[rank_5d, rank_7d, rank_9d]` を辿る

校正が必要な項目：
- 動的 rank 降格閾値（5 / 15）— バッチ評価で要校正

変更はこのファイル1点のみ。他のセクションには触らない。編集後、git add + commit（メッセージ: "docs: ai-parameters.md JigoStrategy の弱相手対応を反映"）まで実施してください。
```

- [ ] **Step 2: サブエージェントの変更を検証**

Run: `git log -1 --stat .claude/rules/ai-parameters.md`
Expected: 直近コミットに `.claude/rules/ai-parameters.md` のみ含まれ、期待した変更行数（5-15 行程度）になっていること。

Run: `grep -A 2 "human_profile" .claude/rules/ai-parameters.md | head -10`
Expected: 新規追加行が表示される。

- [ ] **Step 3: 追加コミット不要（サブエージェントがコミット済み）**

完了確認のみ。

---

## Task 12: 統合検証（`katrain_debug`）

**Files:**
- 既存 SGF を使用（`tests/data/ogs.sgf`, `tests/data/panda1.sgf` 等）

- [ ] **Step 1: 基本動作の smoke test（9段・範囲内）**

Run:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --output text 2>&1 | tail -30
```
Expected: 正常終了、`[JigoStrategy] Selected:` ログが出る。`Sharp-move exclusion` は出ない（範囲内）。

- [ ] **Step 2: 鋭手除外の発動確認（圧勝局面）**

圧勝局面を含む SGF を探す。例: target_score_max を意図的に低くして発動させる：

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --move 150 --strategy jigo --settings target_score_max=2.0 --output text 2>&1 | grep -E "Sharp-move|Mode:|Selected:"
```
Expected: `Sharp-move exclusion: N → M (lead=X.XX > target_max=2.0)` が出力される。

- [ ] **Step 3: humanPolicy ハードフロアの確認**

Run:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --settings min_human_policy=0.005 --output text 2>&1 | grep -E "Fallback triggered|Safety valve"
```
Expected: ハードフロアにより極端な緩和が起きないこと（safety_valve 到達頻度が過度に増えないこと）。

- [ ] **Step 4: 動的 rank の発動確認**

圧勝局面で `jigo_dynamic_rank=true` を指定：

Run:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy jigo --batch --player W --settings jigo_dynamic_rank=true target_score_max=5.0 2>&1 | grep -E "Dynamic rank" | head -5
```
Expected: 少なくとも1回は `Dynamic rank: base=rank_9d, ... → rank_7d` か `rank_5d` が出る（バッチ中 `_last_current_lead` がキャッシュされていくため）。

- [ ] **Step 5: 既存 Jigo テストが影響を受けていないことの最終確認**

Run: `pytest tests/test_jigo.py -v`
Expected: 全テスト PASSED（合計10テスト程度）。

- [ ] **Step 6: 全体テストの確認（humanSL モデル必要なテストは除外）**

Run: `pytest --ignore=tests/test_ai.py`
Expected: 失敗なし。

- [ ] **Step 7: 実戦対局での動作確認（手動）**

1. `C:\Users\iwaki\.katrain\config.json` の `debug_level: 0` → `1` に変更
2. `python -m katrain` で起動
3. Kata持碁 AI で対局（弱い手を意図的に打って圧勝を演出、または既存 SGF を分析）
4. ログファイル（`C:\Users\iwaki\.katrain\logs\` 配下）を Grep:
   - `Sharp-move exclusion` の発動頻度
   - `Dynamic rank` の発動頻度（`jigo_dynamic_rank=true` 時のみ）
   - `Safety valve` の発動頻度（少ないこと）
5. 確認後 `debug_level` を `0` に戻す

**実戦検証は任意**。自動検証 (Step 1-6) が通れば基本機能は確認済み。

- [ ] **Step 8: コミット不要**

本タスクは検証のみ。追加の変更なし。

---

## Self-Review

### Spec coverage（仕様書項目との対応）

| 仕様項目 | 実装タスク |
|---|---|
| 変更 A: 鋭手除外 `_jigo_exclude_sharp_moves` | Task 1 + Task 7 |
| 変更 A: SHARP_EPSILON = 0.5 | Task 1 |
| 変更 B: min_human_policy デフォルト 0.02 | Task 5, Task 6 |
| 変更 B: MIN_HP_HARD_FLOOR = 0.005 | Task 3 |
| 変更 C: human_profile 設定 (rank_5d/7d/9d) | Task 4 (AI_OPTION_VALUES), Task 5/6 (config), Task 8 (Stage 1 使用) |
| 変更 D-a: `_select_rank_by_lead` | Task 2 + Task 9 |
| 変更 D-a: `jigo_dynamic_rank` 設定 | Task 4 (AI_OPTION_VALUES), Task 5/6 (config), Task 9 (使用) |
| 変更 D-a: `_last_current_lead` キャッシュ | Task 9 (Step 1, 3) |
| i18n 更新 | Task 10 |
| `.claude/rules/ai-parameters.md` 更新 | Task 11 |
| 統合検証 | Task 12 |

仕様書の全項目がタスクに対応済み。

### Placeholder scan

「TBD」「TODO」「implement later」「適宜」等のプレースホルダーなし。

- Task 9 Step 1 の「AIStrategy の親クラスシグネチャ確認」は実装時判断を求めているが、両方のパターンでの対処を明記済み（代替方式を具体的に示している）。
- Task 12 Step 2 の「圧勝局面を含む SGF を探す」は既存 SGF から選ぶ指示 + コマンド例を具体的に提示済み。
- Task 11 はサブエージェントへの具体的プロンプト全文を提示済み。

### Type consistency

- `_jigo_exclude_sharp_moves(candidates, current_lead, epsilon=0.5)` — Task 1 で定義、Task 7 で呼び出し（シグネチャ一致）
- `_select_rank_by_lead(current_lead, target_score_max, base_profile)` — Task 2 で定義、Task 9 で呼び出し（引数順一致）
- `_jigo_relax_filters(candidates, max_loss, min_hp, hard_floor=MIN_HP_HARD_FLOOR)` — Task 3 で改修、既存呼び出し箇所（`generate_move`）はデフォルト引数を使うため変更不要
- `self._last_current_lead` — Task 9 で Step 1（初期化）と Step 3（保存）で同じ属性名使用
- 設定キー `human_profile` / `jigo_dynamic_rank` — Task 4/5/6/8/9/10 で同じスペル・大文字小文字

一貫性 OK。

### Edge case coverage

- Task 1: 空候補・全除外されるケースの両方をテスト
- Task 2: 未知プロファイル・下限到達・負 delta をテスト
- Task 3: ハードフロアでクリップされる境界をテスト
- Task 9: キャッシュ未初期化時（初手）は `_last_current_lead is None` で base_profile にフォールバック

