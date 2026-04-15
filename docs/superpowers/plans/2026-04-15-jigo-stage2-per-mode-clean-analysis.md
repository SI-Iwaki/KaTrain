# Jigo 応答速度改善フェーズ2（Jigo 専用 scoped wideRootNoise=0.0）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JigoStrategy の Stage 2 クエリ（600 visits クリーン）を既定解析の scoped クリーン化で代替し、追加で約 40% の応答時間短縮を実現する。

**Architecture:** `engine.py` の `KataGoEngine.request_analysis` 内で「次に打つ側が Jigo の場合」だけ `wideRootNoise=0.0` に上書き。`ai.py` の `JigoStrategy.generate_move()` から Stage 2 ブロックを削除し、`self.cn.analysis["root"]` および `self.cn.candidate_moves` 経由で scoreLead/moveInfos を読み取る。

**Tech Stack:** Python 3.12 / Kivy / KataGo v1.16.4（TensorRT）/ katrain_debug CLI / pytest / black

**Spec:** `docs/superpowers/specs/2026-04-15-jigo-stage2-per-mode-clean-analysis-design.md`

---

## ファイル構成

### 変更対象ファイル
- `katrain/core/engine.py` — AI_JIGO import 追加 + `request_analysis` 内に scoped 上書き分岐を追加（合計 8-10 行）
- `katrain/core/ai.py` — `JigoStrategy.generate_move()` の Stage 2 ブロックを削除（約 30 行）→ 既定解析読み替えに置換（約 15 行）
- `.claude/rules/ai-parameters.md` — maxVisits テーブルの Jigo 行、Jigo 戦略説明の該当箇所を更新

### 新規作成ファイル
- `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-results-20260415.md` — 検証結果サマリ
- `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-{before,after}-{sgf-tag}-{color}-run{1,2,3}.json` — batch_eval 出力群（18 ファイル）

### 参照ファイル（読むだけ）
- `tests/data/ogs.sgf`（19路 校正 SGF）
- `docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf`, `game2.sgf`（13路 校正 SGF）

---

## Task 1: Before-baseline 校正データ採取

**目的:** 案A 適用済コード（= 現状）での Jigo batch_eval 結果を 3-run で採取し、after 比較の基準を確定する。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-ogs-W-run1.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-ogs-W-run{2,3}.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-ogs-B-run{1,2,3}.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-13ro-game1-W-run{1,2,3}.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-13ro-game1-B-run{1,2,3}.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-13ro-game2-W-run{1,2,3}.json`
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-13ro-game2-B-run{1,2,3}.json`

**前提確認:**

- [ ] **Step 1.0: working tree が clean であることを確認**

Run: `git status`
Expected: `nothing to commit, working tree clean`（`.claude/settings.local.json` の untracked は無視可）

これから 18 run × 2-3 分 = 約 45-60 分の採取になる。

- [ ] **Step 1.1: 19路 ogs.sgf × 白番 × run1**

Run:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --strategy jigo --batch --player W --output json > docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-ogs-W-run1.json 2>&1
```
Expected: ファイルが作成され、末尾に `"stats": {` を含む JSON 構造が入る。

- [ ] **Step 1.2: 19路 ogs.sgf × 白番 × run2**

Run:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --strategy jigo --batch --player W --output json > docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-ogs-W-run2.json 2>&1
```

- [ ] **Step 1.3: 19路 ogs.sgf × 白番 × run3**

Run:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --strategy jigo --batch --player W --output json > docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-ogs-W-run3.json 2>&1
```

- [ ] **Step 1.4: 19路 ogs.sgf × 黒番 × run1-3**

Run（3回実行、ファイル名の runN 部分を run1/run2/run3 に変えて繰り返す）:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --strategy jigo --batch --player B --output json > docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-ogs-B-run1.json 2>&1
```

- [ ] **Step 1.5: 13路 game1 × 白黒 × run1-3（計6本）**

Run:
```bash
# 白番 run1-3
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf --strategy jigo --batch --player W --output json > docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-13ro-game1-W-run1.json 2>&1
# （run2, run3 も同様）
# 黒番 run1-3
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game1.sgf --strategy jigo --batch --player B --output json > docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-13ro-game1-B-run1.json 2>&1
```

- [ ] **Step 1.6: 13路 game2 × 白黒 × run1-3（計6本）**

Run（game1 と同じ要領で game2 SGF を対象に 6 本）:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/jigo-speedup/katrain-13ro-20260401-game2.sgf --strategy jigo --batch --player W --output json > docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-13ro-game2-W-run1.json 2>&1
# 以下 W-run2/run3, B-run1/run2/run3 を同様に実行
```

- [ ] **Step 1.7: 18 ファイルが生成されたか確認**

Run:
```bash
ls docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-*.json | wc -l
```
Expected: `18`

- [ ] **Step 1.8: 各 JSON が正しい構造を含むか抜き打ち確認**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "import json; d=json.load(open('docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-ogs-W-run1.json', encoding='utf-8')); print('stats keys:', list(d.get('stats', {}).keys()))"
```
Expected: `stats keys: ['overall', 'by_player', 'by_phase', ...]`（少なくとも `overall` キーが存在）

- [ ] **Step 1.9: Commit**

Run:
```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/phase2-before-*.json
git commit -m "$(cat <<'EOF'
chore(jigo-speedup): フェーズ2 before baseline を採取（案A 適用済コード）

19路 ogs.sgf + 13路 game1/game2 × 白黒 × 3-run = 計18ファイル。
フェーズ2 実装後の after との比較基準として使用する。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: engine.py に AI_JIGO scoping 分岐を追加

**目的:** `KataGoEngine.request_analysis` で次に打つ側が Jigo の場合、`wideRootNoise` を 0.0 に上書きする。

**Files:**
- Modify: `katrain/core/engine.py:15-23`（import 追記）
- Modify: `katrain/core/engine.py:443-446`（scoping 分岐追加）

- [ ] **Step 2.1: `AI_JIGO` import を追加**

Edit `katrain/core/engine.py`（先頭の import セクション）:

```python
from katrain.core.constants import (
    OUTPUT_DEBUG,
    OUTPUT_ERROR,
    OUTPUT_EXTRA_DEBUG,
    OUTPUT_KATAGO_STDERR,
    DATA_FOLDER,
    KATAGO_EXCEPTION,
    PONDERING_REPORT_DT,
)
```

を以下に変更:

```python
from katrain.core.constants import (
    OUTPUT_DEBUG,
    OUTPUT_ERROR,
    OUTPUT_EXTRA_DEBUG,
    OUTPUT_KATAGO_STDERR,
    DATA_FOLDER,
    KATAGO_EXCEPTION,
    PONDERING_REPORT_DT,
    AI_JIGO,
)
```

- [ ] **Step 2.2: scoping 分岐を追加**

`engine.py` の `request_analysis` 内、現行:

```python
        settings = copy.copy(self.override_settings)
        settings["wideRootNoise"] = self.config["wide_root_noise"]
        if time_limit:
            settings["maxTime"] = self.config["max_time"]
```

を以下に変更:

```python
        settings = copy.copy(self.override_settings)
        settings["wideRootNoise"] = self.config["wide_root_noise"]
        # Jigo 戦略はクリーンな scoreLead を必要とする。次の打ち手が Jigo のときだけ
        # 既定解析の wideRootNoise を 0.0 に上書きする（他 AI モード・他戦略への影響なし）
        try:
            next_player = analysis_node.next_player
            player_info = self.katrain.players_info.get(next_player)
            if player_info is not None and player_info.ai and player_info.strategy == AI_JIGO:
                settings["wideRootNoise"] = 0.0
        except Exception:
            pass
        if time_limit:
            settings["maxTime"] = self.config["max_time"]
```

- [ ] **Step 2.3: 診断ログを一時追加**

`engine.py` の Step 2.2 で追加した try ブロック**直後**に以下を追加（確認目的）:

```python
        try:
            next_player = analysis_node.next_player
            player_info = self.katrain.players_info.get(next_player)
            if player_info is not None and player_info.ai and player_info.strategy == AI_JIGO:
                settings["wideRootNoise"] = 0.0
        except Exception:
            pass
        # [TEMP_DIAG] wideRootNoise 実効値を確認（Task 4 で確認後に削除）
        self.katrain.log(
            f"[JigoScoped] wideRootNoise={settings['wideRootNoise']}", OUTPUT_ERROR
        )
        if time_limit:
            settings["maxTime"] = self.config["max_time"]
```

- [ ] **Step 2.4: black フォーマット確認**

Run:
```bash
black --check katrain/core/engine.py
```
Expected: `All done!` もしくは差分のフィードバック。差分ある場合は `black katrain/core/engine.py` で修正。

- [ ] **Step 2.5: import エラーがないか構文チェック**

Run:
```bash
python -c "from katrain.core.engine import KataGoEngine; print('OK')"
```
Expected: `OK`（エラーなく import できる）

- [ ] **Step 2.6: 非 AI 系テストで regression がないか**

Run:
```bash
pytest --ignore=tests/test_ai.py -q
```
Expected: all pass（または現状と同じ結果）

- [ ] **Step 2.7: Commit（診断ログ込み）**

Run:
```bash
git add katrain/core/engine.py
git commit -m "$(cat <<'EOF'
perf(jigo): engine.py に Jigo 専用 scoped wideRootNoise=0.0 分岐を追加

次に打つ側が Jigo の場合だけ既定解析の wideRootNoise を 0.0 に上書きする。
他 AI モード・他戦略への影響なし。

診断ログ [JigoScoped] は Task 4 の smoke test 確認後に削除する。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: JigoStrategy の Stage 2 ブロックを既定解析読み替えに置換

**目的:** Stage 2 クエリ（600 visits）を削除し、`self.cn.analysis["root"]` と `self.cn.candidate_moves` から scoreLead / moveInfos 相当を取得する。

**Files:**
- Modify: `katrain/core/ai.py:920-967`（Stage 2 ブロック → 既定解析読み替え）

- [ ] **Step 3.1: Stage 2 ブロックを削除し、既定解析読み替えを挿入**

`ai.py` の Stage 1 完了ログ（`f"[JigoStrategy] Stage1 query complete ..."` の log 呼び出し）から `scores_player = [mi.get("scoreLead", 0) * sign for mi in move_infos]` の直前までを以下のように置換。

**削除対象:**

```python
        # ---- Stage 2: クリーンクエリ（scoreLead 用） ----
        stage2_override = {
            "ignorePreRootHistory": False,
            "maxVisits": 600,
            "wideRootNoise": 0.0,
        }
        stage2_analysis = None
        stage2_error = False

        def _set_stage2(a, partial):
            nonlocal stage2_analysis
            if not partial:
                stage2_analysis = a

        def _err_stage2(a):
            nonlocal stage2_error
            stage2_error = True
            self.game.katrain.log(f"[JigoStrategy] Stage2 error: {a}", OUTPUT_ERROR)

        engine.request_analysis(
            self.cn, callback=_set_stage2, error_callback=_err_stage2,
            priority=PRIORITY_EXTRA_AI_QUERY, include_policy=False,
            extra_settings=stage2_override,
        )
        while not (stage2_error or stage2_analysis):
            time.sleep(0.01)
            engine.check_alive(exception_if_dead=True)

        # Stage 2 失敗時は Stage 1 にフォールバック
        if stage2_error or not stage2_analysis:
            self.last_decision_info["score_lead_biased"] = True
            self.game.katrain.log(
                "[JigoStrategy] Stage2 failed, using Stage1 moveInfos (biased)", OUTPUT_DEBUG
            )
            score_analysis = stage1_analysis
        else:
            score_analysis = stage2_analysis
        move_infos = score_analysis.get("moveInfos", [])
        if not move_infos:
            self.game.katrain.log("[JigoStrategy] No moveInfos, passing", OUTPUT_DEBUG)
            return Move(None, player=self.cn.next_player), "No moveInfos, passing"

        # current_lead を前倒し計算（effective max_loss 判定のため）
        current_lead = score_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
```

**挿入する置換後コード:**

```python
        # ---- Stage 2 代替: 既定解析（wideRootNoise=0.0 scoped）を直接読む ----
        # engine.py 側で「次の打ち手が Jigo の場合」wideRootNoise=0.0 が保証されている
        default_analysis = self.cn.analysis
        if not default_analysis or not default_analysis.get("root"):
            # フォールバック: Stage 1 moveInfos を使用（Stage 2 失敗経路相当）
            self.last_decision_info["score_lead_biased"] = True
            self.game.katrain.log(
                "[JigoStrategy] Default analysis unavailable, using Stage1 moveInfos (biased)",
                OUTPUT_DEBUG,
            )
            move_infos = stage1_analysis.get("moveInfos", [])
            if not move_infos:
                self.game.katrain.log("[JigoStrategy] No moveInfos, passing", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "No moveInfos, passing"
            current_lead = stage1_analysis.get("rootInfo", {}).get("scoreLead", 0) * sign
        else:
            # 既定解析の candidate_moves（sorted）から scoreLead 付き候補リストを構築
            move_infos = [
                {"move": c["move"], "scoreLead": c.get("scoreLead", 0)}
                for c in self.cn.candidate_moves
            ]
            if not move_infos:
                self.game.katrain.log("[JigoStrategy] No moveInfos, passing", OUTPUT_DEBUG)
                return Move(None, player=self.cn.next_player), "No moveInfos, passing"
            current_lead = default_analysis["root"].get("scoreLead", 0) * sign
```

- [ ] **Step 3.2: 置換後のブロックに続く既存処理（`scores_player = ...` 以降）が正しく接続されているか確認**

置換後のコードブロック直後は以下の既存コードが続くべき:

```python
        # ---- 候補リスト構築（すべて自分視点 = sign を掛けた値） ----
        scores_player = [mi.get("scoreLead", 0) * sign for mi in move_infos]
        best_score = max(scores_player)  # 自分視点の最善スコア
```

`move_infos` 変数名は維持されているため、既存処理は無変更で動作する。

- [ ] **Step 3.3: Stage 2 関連ログの修正（Stage2 query complete の log を調整）**

置換後は「Stage2 query complete」のログは意味を持たなくなる。`ai.py` 内の該当ログを検索:

Run:
```bash
grep -n "Stage2 query complete" katrain/core/ai.py
```

存在する場合は削除または以下のように修正:

```python
        self.game.katrain.log(
            f"[JigoStrategy] Stage2 query complete ({len(candidates)} candidates, "
            f"best_score={best_score:.2f})", OUTPUT_DEBUG
        )
```
↓
```python
        self.game.katrain.log(
            f"[JigoStrategy] Score source: default_analysis ({len(candidates)} candidates, "
            f"best_score={best_score:.2f})", OUTPUT_DEBUG
        )
```

- [ ] **Step 3.4: black フォーマット**

Run:
```bash
black katrain/core/ai.py
```
Expected: 差分の自動整形。結果を確認して意図しない変更がないか git diff で確認。

- [ ] **Step 3.5: 構文チェック**

Run:
```bash
python -c "from katrain.core.ai import JigoStrategy; print('OK')"
```
Expected: `OK`

- [ ] **Step 3.6: 非 AI 系テスト**

Run:
```bash
pytest --ignore=tests/test_ai.py -q
```
Expected: all pass

- [ ] **Step 3.7: Commit**

Run:
```bash
git add katrain/core/ai.py
git commit -m "$(cat <<'EOF'
perf(jigo): Stage 2 クエリを廃止して既定解析を直接読み替え

engine.py 側で保証された wideRootNoise=0.0 の scoped 既定解析を読むことで
Stage 2 の 600 visits 追加クエリを完全廃止。応答時間を約 40% 短縮。

- self.cn.analysis["root"]["scoreLead"] を current_lead の計算に使用
- self.cn.candidate_moves から moveInfos 相当のリストを構築
- 既定解析が利用不可の場合は Stage 1 biased フォールバックを維持

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 実装直後 smoke test

**目的:** Step 2.3 で追加した診断ログにより「次の打ち手が Jigo のとき wideRootNoise=0.0、それ以外は 0.04」が実際に効いていることを確認する。

- [ ] **Step 4.1: Jigo 実行で 0.0 ログが出ることを確認**

Run:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --output text 2>&1 | grep -a "JigoScoped"
```
Expected: `ERROR: [JigoScoped] wideRootNoise=0.0` のログが（少なくとも1回）出力される

- [ ] **Step 4.2: 非 Jigo 戦略で 0.04 ログが出ることを確認**

Run:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy human --output text 2>&1 | grep -a "JigoScoped"
```
Expected: `ERROR: [JigoScoped] wideRootNoise=0.04` のみ（0.0 は出ない）

- [ ] **Step 4.3: `Default analysis unavailable` フォールバックログが**出ていない**ことを確認**

Run:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy jigo --output text 2>&1 | grep -a "Default analysis unavailable"
```
Expected: 何も出力されない（空）

- [ ] **Step 4.4: 診断ログを撤去**

Edit `katrain/core/engine.py` の Step 2.3 で追加した以下のブロックを削除:

```python
        # [TEMP_DIAG] wideRootNoise 実効値を確認（Task 4 で確認後に削除）
        self.katrain.log(
            f"[JigoScoped] wideRootNoise={settings['wideRootNoise']}", OUTPUT_ERROR
        )
```

- [ ] **Step 4.5: 撤去後に構文チェック**

Run:
```bash
python -c "from katrain.core.engine import KataGoEngine; print('OK')"
```
Expected: `OK`

- [ ] **Step 4.6: black フォーマット**

Run:
```bash
black --check katrain/core/engine.py
```
Expected: `All done!`

- [ ] **Step 4.7: Commit**

Run:
```bash
git add katrain/core/engine.py
git commit -m "$(cat <<'EOF'
chore(jigo): Task 4 smoke test 完了後の診断ログを撤去

Jigo 戦略時の wideRootNoise=0.0 / 非 Jigo 時 0.04 の動作を確認済。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: After 校正データ採取

**目的:** フェーズ2 適用後の Jigo batch_eval 結果を 3-run × 両色 × 2盤面 で採取する。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-after-*.json`（合計 18 ファイル、before と同じ命名規則）

- [ ] **Step 5.1〜5.6: Before と同じパターンで 18 run を採取**

Task 1（Step 1.1〜1.6）と同じコマンドで、出力ファイル名の `phase2-before-` → `phase2-after-` に変更して 18 run を実行する。

代表例（他は同様）:
```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --strategy jigo --batch --player W --output json > docs/superpowers/specs/calibration-data/jigo-speedup/phase2-after-ogs-W-run1.json 2>&1
```

- [ ] **Step 5.7: 18 ファイル生成確認**

Run:
```bash
ls docs/superpowers/specs/calibration-data/jigo-speedup/phase2-after-*.json | wc -l
```
Expected: `18`

- [ ] **Step 5.8: 各 JSON の構造抜き打ち確認**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "import json; d=json.load(open('docs/superpowers/specs/calibration-data/jigo-speedup/phase2-after-ogs-W-run1.json', encoding='utf-8')); print('stats keys:', list(d.get('stats', {}).keys()))"
```
Expected: `stats keys: ['overall', ...]`

- [ ] **Step 5.9: Commit**

Run:
```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/phase2-after-*.json
git commit -m "$(cat <<'EOF'
chore(jigo-speedup): フェーズ2 after 校正データを採取

19路 ogs + 13路 game1/game2 × 白黒 × 3-run = 計18ファイル。
Task 6 で before との差分を比較する。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 比較・判定・結果まとめ

**目的:** before/after の差分を集計し、spec §5.2 の合格基準に照らして GO/NO-GO を判定する。

**Files:**
- Create: `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-results-20260415.md`

- [ ] **Step 6.1: 集計スクリプトを使って before/after の 3-run 平均を算出**

以下の Python one-liner で各 SGF × 各色の 3-run 平均（Top1/Top5 一致率・mean ptloss・Choice-vs-Median Gap・Post-98% Slack）を算出:

```bash
PYTHONIOENCODING=utf-8 python <<'PYEOF'
import json, glob, os
from statistics import mean

def load_avg(pattern, keys):
    files = sorted(glob.glob(pattern))
    assert len(files) == 3, f"Expected 3 runs, got {len(files)}: {files}"
    result = {k: [] for k in keys}
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        stats = d.get("stats", {}).get("overall", {})
        for k in keys:
            v = stats.get(k)
            if v is not None:
                result[k].append(v)
    return {k: (mean(result[k]) if result[k] else None) for k in keys}

metrics = [
    "ai_top_move",
    "ai_top5_move",
    "mean_ptloss",
    "choice_vs_median_gap",
    "post_98pct_slack",
]

for sgf_tag in ["ogs", "13ro-game1", "13ro-game2"]:
    for color in ["W", "B"]:
        base = f"docs/superpowers/specs/calibration-data/jigo-speedup/phase2-{{}}-{sgf_tag}-{color}-run*.json"
        before = load_avg(base.format("before"), metrics)
        after = load_avg(base.format("after"), metrics)
        print(f"\n== {sgf_tag} {color} ==")
        for k in metrics:
            b, a = before[k], after[k]
            if b is None or a is None:
                print(f"  {k}: N/A")
                continue
            delta = a - b
            print(f"  {k}: before={b:.4f} after={a:.4f} delta={delta:+.4f}")
PYEOF
```

Expected: 6 ブロック × 5 メトリックの before/after/delta が出力される。

- [ ] **Step 6.2: 合格基準と照合**

spec §5.2 の合格基準:

| メトリック | 合格基準 |
|---|---|
| Top1 AI一致率 (`ai_top_move`) | delta の絶対値 ≤ 0.02 |
| Top5 AI一致率 (`ai_top5_move`) | delta の絶対値 ≤ 0.02 |
| 平均損失 (`mean_ptloss`) | delta の絶対値 ≤ 0.1 |
| Choice-vs-Median Gap | delta の絶対値 ≤ 0.1 |
| Post-98% Slack | delta の絶対値 ≤ 0.1 |

全 6 ブロック × 5 メトリック = 30 項目のうち、**逸脱があるブロックを列挙**する。

- [ ] **Step 6.3: 判定**

- 全項目が合格基準内 → **GO**（Task 7 へ進む）
- 1-2 項目が逸脱（特に単一 SGF × 色ブロックに集中） → **保留**。Step 6.5 で Task 7 着手の可否をユーザに確認
- 多数項目（9 以上）が逸脱 → **NO-GO**（ロールバック検討。「ロールバック」セクション参照）

- [ ] **Step 6.4: 結果ファイルを作成**

Create `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-results-20260415.md`:

```markdown
# Jigo speedup phase 2 校正結果（2026-04-15）

**Spec:** `docs/superpowers/specs/2026-04-15-jigo-stage2-per-mode-clean-analysis-design.md`

**Before:** 案A 適用済・Stage 2 クエリ残存（600 visits クリーン）
**After:** フェーズ2 適用後・Stage 2 廃止、既定解析を Jigo-scoped クリーン化で読み替え

## 3-run 平均の差分（delta = after - before）

| SGF × Color | Top1 一致率 Δ | Top5 一致率 Δ | mean_ptloss Δ | Choice-vs-Median Gap Δ | Post-98% Slack Δ |
|---|---|---|---|---|---|
| ogs W | {数値} | {数値} | {数値} | {数値} | {数値} |
| ogs B | {数値} | {数値} | {数値} | {数値} | {数値} |
| 13ro-game1 W | {数値} | {数値} | {数値} | {数値} | {数値} |
| 13ro-game1 B | {数値} | {数値} | {数値} | {数値} | {数値} |
| 13ro-game2 W | {数値} | {数値} | {数値} | {数値} | {数値} |
| 13ro-game2 B | {数値} | {数値} | {数値} | {数値} | {数値} |

## 合格基準逸脱

{逸脱項目の列挙、または「逸脱なし」}

## 判定

{GO / 保留 / NO-GO}

{判定の根拠を 2-3 行で記述}
```

Step 6.1 の出力を使ってテーブルの `{数値}` を実値に置換。

- [ ] **Step 6.5: Commit**

Run:
```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/phase2-results-20260415.md
git commit -m "$(cat <<'EOF'
docs(jigo-speedup): フェーズ2 校正結果サマリを追加（20260415）

before/after 3-run 平均の差分と合格基準逸脱をまとめた。
判定: {GO / 保留 / NO-GO}

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 実対局での応答時間計測

**目的:** spec §5.1、R1 の実測。`wait_for_analysis()` が実対局で遅延していないことを確認。

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`（一時的に `"debug_level": 0` → `1`、確認後に戻す）

- [ ] **Step 7.1: debug_level を 1 に変更**

Edit `C:\Users\iwaki\.katrain\config.json`: `"debug_level": 0` → `"debug_level": 1`

**注意:** このファイルはメインセッションで直接 Edit（サブエージェントに委任しない。CLAUDE.md の「やってはいけないこと」参照）。

- [ ] **Step 7.2: KaTrain 起動**

Run:
```bash
python -m katrain
```

- [ ] **Step 7.3: 19路 Jigo 対局を5-10手実施**

GUI で:
1. 黒または白を Jigo（"Jigo" AI 選択）、相手を Human にセット
2. 新しい19路対局を開始
3. 相手手→Jigo 手の経過時間を 5-10 手ストップウォッチで計測
4. 終了後、game log から `[JigoStrategy] Starting move generation` と `[JigoStrategy] Selected:` の時刻差分も抽出

- [ ] **Step 7.4: 13路 Jigo 対局で同様に計測**

Step 7.3 と同手順で 13路盤にて計測。

- [ ] **Step 7.5: 結果を Task 6 の results ファイルに追記**

Edit `docs/superpowers/specs/calibration-data/jigo-speedup/phase2-results-20260415.md`:

以下を末尾に追記:

```markdown
## 実対局応答時間計測（spec §5.1）

### 19路
- ストップウォッチ平均: {実測値} 秒（目標 0.2 秒以下）
- ログ時刻差分平均: {実測値} 秒

### 13路
- ストップウォッチ平均: {実測値} 秒
- ログ時刻差分平均: {実測値} 秒

### Default analysis unavailable 発生数
- 19路: {count} / 13路: {count}（spec R4: 想定ゼロ）

### 判定
{目標達成 / 未達成、判定理由}
```

- [ ] **Step 7.6: debug_level を 0 に戻す**

Edit `C:\Users\iwaki\.katrain\config.json`: `"debug_level": 1` → `"debug_level": 0`

- [ ] **Step 7.7: Commit**

Run:
```bash
git add docs/superpowers/specs/calibration-data/jigo-speedup/phase2-results-20260415.md
git commit -m "$(cat <<'EOF'
docs(jigo-speedup): フェーズ2 実対局応答時間計測結果を追記

spec §5.1 R1 の実測。目標 0.2s 以下の達成可否と Default analysis unavailable
の発生数を記録。

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `.claude/rules/ai-parameters.md` 更新

**目的:** パラメータリファレンスを新構成に合わせて更新する。

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（「エンジン設定（maxVisits）」テーブル、Jigo 戦略セクション）

**重要:** `.claude/rules/*` の Edit は dontAsk モードでも拒否されることがある（memory `feedback_claude_rules_edit.md`）。**サブエージェント（Agent tool）経由で編集**する。

- [ ] **Step 8.1: エンジン設定テーブルの Jigo 行を修正**

Agent dispatch で以下の編集を実施:

`.claude/rules/ai-parameters.md` の「エンジン設定（maxVisits）」テーブル内で:

現行:
```markdown
| ai.py `clean_override_settings["maxVisits"]` | 600 | Stage2: クリーンスコア検証（独立値） |
```

を以下に変更:

```markdown
| ~~ai.py `clean_override_settings["maxVisits"]`~~ | ~~600~~ | ~~Stage2: 廃止（Jigo は engine.py 側 scoped wideRootNoise=0.0 の既定解析を直接読み替え）~~ |
```

または Jigo 行は完全削除。どちらか。

- [ ] **Step 8.2: Jigo 戦略セクションの着手選択説明を更新**

`.claude/rules/ai-parameters.md` の「持碁戦略（JigoStrategy）」セクション内で:

現行:
```markdown
**着手選択**: HumanStyle と同じ2段階クエリ方式（Stage1 humanSL 9段固定 / Stage2 クリーンスコア）。
```

を以下に変更:

```markdown
**着手選択**: Stage 1 で humanSL 9段の humanPolicy のみ取得（maxVisits=1）し、
scoreLead は既定解析を直接読む（engine.py で Jigo 判定時に wideRootNoise=0.0 に scoped 上書き）。
```

- [ ] **Step 8.3: Agent 経由で Edit + Commit を依頼**

Agent dispatch（要点を指示）:
- Task 8 の Step 8.1 / 8.2 を `.claude/rules/ai-parameters.md` に適用
- 上記2箇所のみ編集（他の行に手を入れない）
- commit message: `docs(rules): Jigo の Stage 2 廃止に合わせて ai-parameters.md を更新`
- Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com> を末尾に含める

- [ ] **Step 8.4: 編集が反映されたか確認**

Run:
```bash
grep -n "clean_override_settings" .claude/rules/ai-parameters.md
grep -n "2段階クエリ方式" .claude/rules/ai-parameters.md
```
Expected: Step 8.1 の結果に応じて該当行が消えているか取消線表記になっている。Step 8.2 の「2段階クエリ方式」は消えて新しい記述に置換されている。

- [ ] **Step 8.5: git log で commit が作られたか確認**

Run:
```bash
git log --oneline -3
```
Expected: 最新 commit が Task 8 の subject を含む。

---

## ロールバック（全 Task 失敗時の復旧手順）

Task 6 で NO-GO 判定となった場合、または Task 7 で応答時間が現行より悪化した場合、以下で元に戻す:

```bash
# Task 3 / Task 4 / Task 2 の実装コミットを逆順に revert
git log --oneline | head -10  # 該当 commit hash を確認
git revert <task4-commit-hash>
git revert <task3-commit-hash>
git revert <task2-commit-hash>
```

校正データ（before/after JSON, results.md）はそのまま残し、次回検討時の参考データとする。`.claude/rules/ai-parameters.md` の変更 (Task 8) も revert する。

---

## 完了条件

- Task 1〜8 のすべての checkbox が完了
- `git log --oneline | head -10` で以下の commit が積まれている:
  1. before baseline データ (Task 1)
  2. engine.py scoping 追加 + 診断ログ (Task 2)
  3. ai.py Stage 2 廃止 (Task 3)
  4. 診断ログ撤去 (Task 4)
  5. after 校正データ (Task 5)
  6. results サマリ (Task 6)
  7. 実対局計測追記 (Task 7)
  8. ai-parameters.md 更新 (Task 8)
- `phase2-results-20260415.md` の判定が GO
- 実対局応答時間が 19路・13路とも平均 0.2 秒以下
- `working tree clean`

## 変更しないこと（スコープ外）

- `katrain/config.json`（パッケージ同梱）や `C:\Users\iwaki\.katrain\config.json`（ランタイム）の内容変更（ただし Task 7 の `debug_level` 一時切替は例外）
- `katrain/core/constants.py` の `AI_JIGO` 定数本体（既存値 `"ai:jigo"` をそのまま使う）
- 他戦略（HumanStyle / Fighting / Siege / Hunt / Divergence）のコード
- 他戦略の校正データ（取り直し不要）
- `katrain/core/engine.py` の `override_settings` 初期値や他の query 組み立てロジック
- `C:\Users\iwaki\.katrain\analysis_config.cfg`
- i18n ファイル（`.po` / `.mo`）
