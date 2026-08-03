# 詰碁・段階3（root部分結果からの前倒し投機）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** root リージョン解析の部分結果（約0.67×1800visits 時点）から検証バッチ本体を含む温め集合を Game 側ウォッチャで前倒し発行し、コールド1手目の合計 4.6〜7.7秒を 3〜3.5秒級へ縮める（判定は完全不変）。

**Architecture:** `Game.play()` の region 分岐で次番が AI（ai:tsumego）ならウォッチャスレッドを起動（`_maybe_region_prefetch` の鏡像）。ウォッチャは `node.analysis["moves"]` の visits 合計が閾値に達したら、ai.py の新純関数 `tsumego_early_speculation_items`（検証バッチ本体＋段階1+2集合）で温めプランを計算し、使い捨て sim＋優先度500で発行、結果は捨てる。判定・実クエリは1バイトも変えない。

**Tech Stack:** Python 3.12 / KataGo Analysis Engine / pytest

**Spec:** `docs/superpowers/specs/2026-08-03-tsumego-stage3-early-speculation-design.md`（§3.1 は 53c799a で「Game側ウォッチャ」に訂正済み。プランはその訂正後の設計に従う）

## Global Constraints

- **精度不変が絶対条件**: 実クエリの内容・発行順・待ち合わせ・判定関数・タイブレーク・戦略コード（`TsumegoOwnershipStrategy`）は一切変更しない。温めの結果は必ず捨てる
- 温め条件は実クエリと完全一致（ownership=True・`gain_verify_visits`・region・untilDepth/wRN は項目指定、None=本譜既定）。優先度は既存 `PRIORITY_TSUMEGO_SPECULATION`(500)
- 新定数 `TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION = 0.67`（ai.py）
- **game.py から ai.py をモジュールレベル import しない**（循環。ウォッチャ内の遅延 import で解決）
- ウォッチャの bail 条件: `current_node` 切替 / リージョン解除 / `region_completed` / 期限30秒。発火は一度だけ。掃除は次の `Game.play()` 冒頭
- 採用ゲート（Task 4）: E2E フル回帰の正答不変 ＋ root ウォール非劣化（+0.3秒以内）
- コミットメッセージは日本語・Conventional Commits。ファイル全体に black を走らせない
- **長時間 KataGo 実行（フル回帰）はサブエージェント内バックグラウンドで走らせない**（孤児化の実績あり）。コントローラがデタッチ＋Monitor で直営するか、サブエージェントはフォアグラウンド1コマンドずつ

## File Structure

- Modify: `katrain/core/ai.py` — 定数1行＋純関数 `tsumego_early_speculation_items`（`tsumego_speculation_plan` の直後）
- Modify: `katrain/core/game.py` — `_maybe_early_speculation` / `_early_speculation_worker` / `_cancel_early_speculation` の3メソッド＋`play()` へのフック2行＋初期化1行＋`AI_TSUMEGO` import
- Create: `docs/superpowers/specs/calibration-data/tsumego/partial_payload_probe.py` — Task 1 の実測プローブ
- Test: `tests/test_tsumego_speculation.py`（純関数テスト追記）・`tests/test_tsumego_early_speculation.py`（新規・ウォッチャ配管）

---

### Task 1: 部分結果 payload の実測プローブ（スペック§4-1 の決着）

**Files:**
- Create: `docs/superpowers/specs/calibration-data/tsumego/partial_payload_probe.py`
- Modify: `docs/superpowers/specs/2026-08-03-tsumego-stage3-early-speculation-design.md`（結果を追記1として記録）

**Interfaces:**
- Consumes: 既存 `generate_move_e2e.py` の局面構築部（同ディレクトリ。KaTrainStub＋engine 起動のパターンをコピーして使う）
- Produces: スペック追記1「部分結果に ownership / per-move ownership が含まれるか」の実測結論。**含まれない場合、Task 2 の集合計算は「目数順上位3＋visits上位3の和集合を untilDepth=None/wRN=None で温める」簡易プロキシに差し替える**（このプランの Task 2 は含まれる前提で書いてある。プローブが否なら Task 2 のコードを差し替えてから進むこと — 差し替え後も関数名・返り値形式・テストの骨格は同じ）

- [ ] **Step 1: プローブを書く**

`partial_payload_probe.py` — 同ディレクトリの `generate_move_e2e.py` から「SGF 読み込み→エンジン起動→リージョン解析発行」までの最小部分を流用し、callback の `partial_result=True` 呼び出しごとに以下を1行ずつ print する（ASCII のみ）:

```python
# 骨子（generate_move_e2e.py の該当部をコピーして、request_analysis の callback だけ差し替える）
def on_result(analysis_json, partial_result):
    tag = "PARTIAL" if partial_result else "FINAL"
    mi = analysis_json.get("moveInfos") or []
    print(
        f"{tag} visits={analysis_json.get('rootInfo', {}).get('visits')} "
        f"n_moves={len(mi)} "
        f"has_root_ownership={analysis_json.get('ownership') is not None} "
        f"first_move_has_ownership={bool(mi and mi[0].get('ownership') is not None)}",
        flush=True,
    )
```

対象局面はケース V（`e2e_suite.py` の `CASES` から sgf/moves/region を転記）、visits=1800・ownership=True・movesOwnership=True・`reportDuringSearchEvery=1`・region 付き＝本番と同条件。

- [ ] **Step 2: 実行して記録**

Run: `python docs/superpowers/specs/calibration-data/tsumego/partial_payload_probe.py`（KataGo 起動あり・1〜2分・フォアグラウンド）
Expected: PARTIAL 行が2本以上出て、`has_root_ownership` / `first_move_has_ownership` の真偽が読める

- [ ] **Step 3: スペックに追記してコミット**

スペック末尾に「## 追記1（実測）: 部分結果の payload」として PARTIAL/FINAL 各行の実測値と結論（純関数がそのまま使える / プロキシに差し替え）を記録。

```bash
git add docs/superpowers/specs/calibration-data/tsumego/partial_payload_probe.py docs/superpowers/specs/2026-08-03-tsumego-stage3-early-speculation-design.md
git commit -m "docs(tsumego): 段階3の前提実測（部分結果のownership有無）を記録"
```

---

### Task 2: 純関数 `tsumego_early_speculation_items`

**Files:**
- Modify: `katrain/core/ai.py`（`tsumego_speculation_plan` の直後に追加。定数はその直前）
- Test: `tests/test_tsumego_speculation.py`（追記）

**Interfaces:**
- Consumes（既存）: `tsumego_eligible_candidates(candidates, max_points_behind, min_visits)` / `select_tsumego_move(...)` / `tsumego_score_best(eligible)` / `tsumego_needs_score_best_verify(chosen, score_best, points_epsilon)` / `tsumego_score_best_challengers(chosen, eligible, score_best, root_ownership, stones, board_size, player_sign, min_visit_ratio)` / `tsumego_speculation_plan(...)`（Task 1 の結果が「含まれない」なら本文の集合計算をプロキシ版に差し替え）
- Produces（Task 3 が使う）:
  - `TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION = 0.67`
  - `tsumego_early_speculation_items(candidate_moves, root_ownership, stones, board_size, player_sign, settings) -> list[dict]` — 要素は `{"move": str, "until_depth": Optional[int], "wide_root_noise": Optional[float]}`（`tsumego_speculation_plan` と同形式）。`settings` は `ai/ai:tsumego` の設定 dict（既定値の解決は関数内で `_generate_move` と同じキー・同じ既定値）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_speculation.py` に追記（既存の `_cand` / `STONES` / `ROOT_OWNERSHIP` / `BOARD` ヘルパを流用）:

```python
from katrain.core.ai import (
    TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION,
    tsumego_early_speculation_items,
)


def test_early_items_include_verify_batch_and_stage12_sets():
    """検証バッチ本体（chosen・score_best・挑戦者、条件None/None）と段階1+2集合の和집合を返す"""
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})  # gain大・目数2番手
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})  # 目数最善
    rescue = _cand("E5", 3.0, 200, {(3, 3): 0.65, (4, 4): 0.65})  # 非contenderのgain上位
    items = tsumego_early_speculation_items(
        [chosen, score_best, rescue], ROOT_OWNERSHIP, STONES, (BOARD, BOARD), 1, {}
    )
    default_cond = {i["move"] for i in items if i["until_depth"] is None and i["wide_root_noise"] is None}
    # 検証バッチ本体: chosen と score_best（この局面では挑戦者= chosen のみ）
    assert {"C3", "D4"} <= default_cond
    # 段階1+2 の救済スーパーセットも含まれる
    assert "E5" in default_cond
    # コウ検査温め（ud=6/wRN=0.0）も並存する
    screen_cond = {i["move"] for i in items if i["until_depth"] is not None}
    assert {"C3", "D4"} == screen_cond


def test_early_items_dedupe_same_condition():
    """同じ (move, until_depth, wRN) は1回だけ（検証バッチと救済集合の重複を潰す）"""
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    items = tsumego_early_speculation_items(
        [chosen, score_best], ROOT_OWNERSHIP, STONES, (BOARD, BOARD), 1, {}
    )
    keys = [(i["move"], i["until_depth"], i["wide_root_noise"]) for i in items]
    assert len(keys) == len(set(keys))


def test_early_items_empty_when_no_selection():
    """ownership が無い等で仮選択できなければ空（発行しない＝安全側）"""
    no_own = {"move": "C3", "pointsLost": 0.0, "visits": 500}  # ownership キーなし
    assert tsumego_early_speculation_items([no_own], ROOT_OWNERSHIP, STONES, (BOARD, BOARD), 1, {}) == []


def test_early_items_respect_settings_gates():
    """gain_verify=False で救済温めが消え、tie_ko_screen=False でコウ検査温めが消える"""
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    rescue = _cand("E5", 3.0, 200, {(3, 3): 0.65, (4, 4): 0.65})
    args = ([chosen, score_best, rescue], ROOT_OWNERSHIP, STONES, (BOARD, BOARD), 1)
    no_rescue = tsumego_early_speculation_items(*args, {"gain_verify": False})
    assert "E5" not in {i["move"] for i in no_rescue}
    no_screen = tsumego_early_speculation_items(*args, {"tie_ko_screen": False})
    assert all(i["until_depth"] is None for i in no_screen)
```

注意: `board_size` はタプル `(w, h)`。既存テストの `_cand` ヘルパの ownership 添字規約
（`(board_size-1-y)*board_size+x`）をそのまま使う。実際の判定関数の意味論とテスト局面が
ずれて期待どおり通らない場合は**テストの局面データ側を直す**（判定関数・新関数の設計は
変えない）。

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_tsumego_speculation.py -v`
Expected: 新規4件が `ImportError` で FAIL

- [ ] **Step 3: 実装**

`katrain/core/ai.py` の `tsumego_speculation_plan` の直後:

```python
# 段階3（前倒し投機）の発火閾値: root リージョン解析の visits 合計がこの割合に達したら
# Game 側ウォッチャが温め集合を発行する（スペック 2026-08-03-tsumego-stage3-early-speculation）。
# 部分結果は約1秒間隔（reportDuringSearchEvery=1）で届くので、0.67×1800≈1200v は
# 実質「2本目の部分結果」で発火する
TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION = 0.67


def tsumego_early_speculation_items(candidate_moves, root_ownership, stones, board_size, player_sign, settings):
    """root 部分結果のスナップショットから前倒し温め集合を返す純関数（判定には一切使わない）。

    集合 = 検証バッチ本体（仮 chosen・目数最善・挑戦者。実検証と同一条件＝untilDepth 既定・
    wRN 既定・ownership=True で撃たれる）＋ 段階1+2 の温め集合（`tsumego_speculation_plan`）。
    仮選択は最終 1800visits と別物になりうるが、ずれた分はミス（捨てるだけ）で安全。
    設定キーと既定値は `_generate_move` の抽出と同一に保つこと（ずれると温め条件が実クエリと
    合わずキャッシュ全ミスになる）。
    """
    settings = settings or {}
    max_points_behind = settings.get("max_points_behind", 2.0)
    gain_epsilon = settings.get("gain_epsilon", 0.3)
    min_visits = settings.get("min_visits", 10)
    min_visit_ratio = float(settings.get("gain_min_visit_ratio", TSUMEGO_GAIN_MIN_VISIT_RATIO))
    points_epsilon = float(settings.get("points_epsilon", TSUMEGO_POINTS_EPSILON))
    rescue_margin = float(settings.get("gain_rescue_margin", TSUMEGO_GAIN_RESCUE_MARGIN))
    chosen = select_tsumego_move(
        candidate_moves, root_ownership, stones, board_size, player_sign,
        max_points_behind, gain_epsilon, min_visits, min_visit_ratio, points_epsilon,
    )
    if chosen is None:
        return []
    eligible = tsumego_eligible_candidates(candidate_moves, max_points_behind, min_visits)
    score_best = tsumego_score_best(eligible)
    items = []
    if score_best is not None:
        verify_moves = [chosen["move"]]
        if score_best["move"] not in verify_moves:
            verify_moves.append(score_best["move"])
        if chosen["move"] != score_best["move"] and tsumego_needs_score_best_verify(chosen, score_best, points_epsilon):
            for cand in tsumego_score_best_challengers(
                chosen, eligible, score_best, root_ownership, stones, board_size, player_sign, min_visit_ratio
            ):
                if cand["move"] not in verify_moves:
                    verify_moves.append(cand["move"])
        items += [{"move": m, "until_depth": None, "wide_root_noise": None} for m in verify_moves]
    items += tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, root_ownership, stones, board_size, player_sign,
        min_visits, min_visit_ratio, points_epsilon, rescue_margin=rescue_margin,
        include_rescue=settings.get("gain_verify", True),
        include_ko_screen=settings.get("tie_ko_screen", True),
    )
    seen, deduped = set(), []
    for item in items:
        key = (item["move"], item["until_depth"], item["wide_root_noise"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
```

（Task 1 が「部分結果に ownership なし」だった場合の差し替え: `select_tsumego_move` 以降を
「`pointsLost` 昇順上位3＋`visits` 降順上位3の和集合を `until_depth=None/wRN=None` で返す」に
置き換え、docstring にその旨を書く。テストも同じ骨格で期待集合だけ変える）

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_tsumego_speculation.py -v`
Expected: 全件 PASS（既存17件＋新規4件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_tsumego_speculation.py
git commit -m "feat(tsumego): 前倒し投機の温め集合計算（純関数）を追加"
```

---

### Task 3: Game 側ウォッチャ（`_maybe_early_speculation` / `_early_speculation_worker` / `_cancel_early_speculation`）

**Files:**
- Modify: `katrain/core/game.py`（`_cancel_region_prefetch`〜`_region_prefetch_worker` 群の直後にメソッド3つ、`play()` にフック、471行付近に初期化、import に `AI_TSUMEGO` と `PRIORITY_TSUMEGO_SPECULATION` 追加）
- Test: `tests/test_tsumego_early_speculation.py`（新規。`tests/test_tsumego_prefetch.py` の Fake パターンを流用）

**Interfaces:**
- Consumes: Task 2 の `tsumego_early_speculation_items` / `TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION`・`TSUMEGO_GAIN_VERIFY_VISITS`（**ウォッチャ内で遅延 import**: `from katrain.core import ai as ai_mod`）、既存 `_region_prefetch_sim` / `region_analysis_extra_settings` / `constants.AI_TSUMEGO`("ai:tsumego") / `constants.PRIORITY_TSUMEGO_SPECULATION`(500)
- Produces: `Game._maybe_early_speculation(node)`（play から呼ばれる）/ `Game._cancel_early_speculation()`（play 冒頭で呼ばれる）/ `Game._early_speculation_nodes: list`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_early_speculation.py` を新規作成:

```python
"""段階3（root部分結果からの前倒し投機）ウォッチャの回帰テスト。

守っているのは4点:
1. 発火は次番が AI かつ strategy が ai:tsumego のときだけ（人間番の先読み prefetch と鏡像）
2. 温めクエリは実クエリと同一条件（ownership=True・gain_verify_visits・優先度500・複製ゲームの子ノード）
3. 掃除（_cancel_early_speculation）はウォッチャの子ノードだけを terminate する
4. region 完了済み・閾値未達では発火しない
"""
import time

from katrain.core.constants import AI_TSUMEGO, PLAYER_AI, PLAYER_HUMAN, PRIORITY_TSUMEGO_SPECULATION
from katrain.core.game import BaseGame, Game, GameNode
from katrain.core.sgf_parser import Move


class FakeEngine:
    def __init__(self):
        self.requests = []
        self.terminated = []

    def request_analysis(self, node, **kwargs):
        self.requests.append((node, kwargs))

    def terminate_queries(self, only_for_node=None, lock=True):
        self.terminated.append(only_for_node)


class FakeInfo:
    def __init__(self, player_type, strategy=None):
        self.player_type = player_type
        self.strategy = strategy


class FakeKatrain:
    players_info = {"B": FakeInfo(PLAYER_AI, AI_TSUMEGO), "W": FakeInfo(PLAYER_HUMAN)}

    def __init__(self, ai_settings=None):
        self._ai_settings = ai_settings or {}

    def config(self, path, default=None):
        if path == f"ai/{AI_TSUMEGO}":
            return self._ai_settings
        return default

    def log(self, *args, **kwargs):
        pass


BOARD = 13


def _own(cells):
    grid = [0.0] * (BOARD * BOARD)
    for (x, y), v in cells.items():
        grid[(BOARD - 1 - y) * BOARD + x] = v
    return grid


def _early_game(visits_now=1500, region_completed=False):
    """白が打った直後・黒(AI)番のノードに、閾値相当の部分解析が載った状態を作る"""
    katrain = FakeKatrain()
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": BOARD, "RU": "japanese", "KM": 6.5}))
    base.play(Move.from_gtp("D4", player="W"), ignore_ko=True)
    node = base.current_node  # 次番 = B = AI
    node.analysis["root"] = {"scoreLead": 0.0, "winrate": 0.5, "visits": 300}
    node.analysis["moves"] = {
        gtp: {
            "move": gtp, "order": i, "scoreLead": [0.0, -0.1][i], "winrate": 0.5,
            "visits": [visits_now - 400, 400][i], "pv": [gtp],
            "ownership": _own({(3, 3): [0.9, 0.1][i]}),
        }
        for i, gtp in enumerate(["C3", "E5"])
    }
    node.analysis["ownership"] = _own({})
    node.analysis["region_completed"] = region_completed

    engine = FakeEngine()
    game = Game.__new__(Game)  # エンジン起動・解析スレッドを伴わない素の Game
    game.katrain = katrain
    game.engines = {"B": engine, "W": engine}
    game.root = base.root
    game.current_node = node
    game.region_of_interest = [2, 6, 2, 6]
    game.region_analysis_visits = 1800
    game.region_analysis_wide_root_noise = 0.04
    game._early_speculation_nodes = []
    return game, node, engine


def test_worker_fires_exact_conditions_at_threshold():
    game, node, engine = _early_game(visits_now=1500)  # 1500 >= 0.67*1800=1206
    game._early_speculation_worker(node)
    assert engine.requests, "閾値到達で発火するはず"
    for child, kw in engine.requests:
        assert kw["ownership"] is True
        assert kw["visits"] == 800  # gain_verify_visits 既定
        assert kw["region_of_interest"] == [2, 6, 2, 6]
        assert kw["priority"] == PRIORITY_TSUMEGO_SPECULATION
        assert child is not node and child.parent is not node  # 複製ゲームの子ノード
    fired = {child.move.gtp() for child, _ in engine.requests}
    assert "C3" in fired  # 仮 chosen の検証バッチ温めが含まれる
    assert game._early_speculation_nodes == [c for c, _ in engine.requests]


def test_worker_does_not_fire_when_region_completed_or_below_threshold():
    game, node, engine = _early_game(visits_now=1500, region_completed=True)
    game._early_speculation_worker(node)
    assert engine.requests == []  # 完了済み＝段階1+2に委ねる
    game2, node2, engine2 = _early_game(visits_now=600)  # 600 < 1206
    game2.current_node = None  # 閾値未達のままノード切替 → bail（無限ループ防止のテスト都合）
    game2._early_speculation_worker(node2)
    assert engine2.requests == []


def test_maybe_skips_human_and_non_tsumego_ai():
    game, node, engine = _early_game()
    game.katrain.players_info = {"B": FakeInfo(PLAYER_HUMAN), "W": FakeInfo(PLAYER_AI, AI_TSUMEGO)}
    game._maybe_early_speculation(node)  # 次番が人間 → 発火しない（スレッドも起動しない想定で即検査）
    time.sleep(0.15)
    assert engine.requests == []
    game.katrain.players_info = {"B": FakeInfo(PLAYER_AI, "ai:default"), "W": FakeInfo(PLAYER_HUMAN)}
    game._maybe_early_speculation(node)
    time.sleep(0.15)
    assert engine.requests == []


def test_cancel_terminates_exactly_the_speculative_nodes():
    game, node, engine = _early_game()
    game._early_speculation_worker(node)
    fired = list(game._early_speculation_nodes)
    assert fired
    game._cancel_early_speculation()
    assert engine.terminated == fired
    assert game._early_speculation_nodes == []
    game._cancel_early_speculation()
    assert engine.terminated == fired  # 二重 cancel は no-op
```

実装上の注意（テストと実装の整合）: ウォッチャの発火判定ループは「閾値以上なら即発火して
return」なので、テストは visits を先に載せておけばスレッド無しで同期的に検証できる
（`_early_speculation_worker` を直接呼ぶ）。`_maybe_early_speculation` はゲート判定＋
スレッド起動だけの薄い関数にする。

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_tsumego_early_speculation.py -v`
Expected: FAIL（`AttributeError: _early_speculation_worker` 等）

- [ ] **Step 3: 実装**

`katrain/core/game.py`:

(a) import に追加（既存の `from katrain.core.constants import (...)` 群へ）: `AI_TSUMEGO`, `PRIORITY_TSUMEGO_SPECULATION`

(b) `__init__` の `self._region_prefetch_nodes = []`（471行付近）の直後:

```python
        self._early_speculation_nodes = []  # 前倒し投機（段階3）の使い捨て子ノード（terminate 用）
```

(c) `play()` の region 分岐（`self._maybe_region_prefetch(played_node)` の直後）に1行、冒頭の `self._cancel_region_prefetch()` の直後に1行:

```python
        self._cancel_early_speculation()
```
```python
                self._maybe_early_speculation(played_node)
```

(d) `_region_prefetch_worker` の直後にメソッド3つ:

```python
    def _cancel_early_speculation(self):
        """発行済みの前倒し投機クエリを打ち切る（結果はもともと捨てるだけなので副作用なし）"""
        nodes = self._early_speculation_nodes
        self._early_speculation_nodes = []
        for node in nodes:
            for engine in set(self.engines.values()):
                engine.terminate_queries(only_for_node=node)

    def _maybe_early_speculation(self, node):
        """次番が AI（ai:tsumego）なら、root 部分結果を見張って温め集合を前倒し発行する。

        `_maybe_region_prefetch`（次番が人間のときの応手先読み）の鏡像。目的は NN キャッシュ
        温めだけで結果は捨てる＝着手判定への影響はゼロ。設計はスペック
        2026-08-03-tsumego-stage3-early-speculation-design.md §3。
        """
        if not self.region_analysis_visits or not self.region_of_interest:
            return
        players_info = getattr(self.katrain, "players_info", None)
        if not players_info:
            return
        try:
            info = players_info[node.next_player]
            if info.player_type == PLAYER_HUMAN or getattr(info, "strategy", None) != AI_TSUMEGO:
                return
        except (KeyError, AttributeError):
            return
        threading.Thread(target=self._early_speculation_worker, args=(node,), daemon=True).start()

    def _early_speculation_worker(self, node):
        """root リージョン解析の visits 合計が閾値に達したら温め集合を計算・発行する。

        発火は一度だけ。region 完了（＝段階1+2 の実クエリ側に委ねる）・ノード切替・
        リージョン解除・期限30秒では発火せず終了する。温めの失敗は着手生成に影響しないので
        例外はすべて握って終了する（投機は純最適化）。
        """
        from katrain.core import ai as ai_mod  # game→ai のモジュール循環を避ける遅延 import

        deadline = time.time() + 30.0
        threshold = ai_mod.TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION * self.region_analysis_visits
        while True:
            if (
                time.time() > deadline
                or self.current_node is not node
                or not self.region_of_interest
                or node.analysis.get("region_completed")
            ):
                return
            moves = node.analysis.get("moves") or {}
            if moves and sum(d.get("visits", 0) for d in moves.values()) >= threshold:
                break
            time.sleep(0.05)
        try:
            settings = self.katrain.config(f"ai/{AI_TSUMEGO}") or {}
            player_sign = node.player_sign(node.next_player)
            stones = ai_mod.tsumego_gain_stones([s.coords for s in self.stones], self.region_of_interest)
            items = ai_mod.tsumego_early_speculation_items(
                node.candidate_moves, node.ownership, stones, self.board_size, player_sign, settings
            )
        except Exception:
            return
        if not items:
            return
        sim = self._region_prefetch_sim(node)
        if sim is None:
            return
        base = sim.current_node
        engine = self.engines[node.next_player]
        visits = int(settings.get("gain_verify_visits", ai_mod.TSUMEGO_GAIN_VERIFY_VISITS))
        region = self.region_of_interest
        fired_nodes, fired = [], []
        for item in items:
            if self.current_node is not node:
                break
            try:
                sim.set_current_node(base)
                child = sim.play(Move.from_gtp(item["move"], player=node.next_player), ignore_ko=True)
                wrn = item["wide_root_noise"]
                engine.request_analysis(
                    child,
                    callback=lambda _analysis, _partial: None,
                    error_callback=lambda _error: None,
                    visits=visits,
                    time_limit=False,
                    ownership=True,
                    region_of_interest=region,
                    region_until_depth=item["until_depth"],
                    extra_settings=region_analysis_extra_settings(
                        visits, self.region_analysis_wide_root_noise if wrn is None else wrn
                    ),
                    priority=PRIORITY_TSUMEGO_SPECULATION,
                )
            except Exception:
                continue
            fired_nodes.append(child)
            fired.append(item["move"])
        if not fired_nodes:
            return
        self._early_speculation_nodes = fired_nodes
        self.katrain.log(
            f"tsumego 前倒し投機: {fired} を root 部分結果（閾値{threshold:.0f}v）時点で発行"
            f"（{visits}visits・結果は捨てる）",
            OUTPUT_DEBUG,
        )
        if self.current_node is not node:
            self._early_speculation_nodes = []
            for child in fired_nodes:
                for child_engine in set(self.engines.values()):
                    child_engine.terminate_queries(only_for_node=child)
```

実装前の確認事項（棚卸し。ずれていたらテスト側・呼び出し側を合わせる）:
- `PLAYER_HUMAN` は game.py で import 済みか（prefetch が使用中のはず）
- `players_info[...]` に `strategy` 属性があるか（`base_katrain.py` の PlayerInfo を確認。
  属性名が違う場合はそちらに合わせ、テストの FakeInfo も直す。**属性が存在しない場合は
  発火しない側に倒す**＝`getattr(..., None)` のまま）
- `node.player_sign` は GameNode の staticmethod（game_node.py:454）
- `self.stones` / `self.board_size` は BaseGame のプロパティ（strategy 側の
  `_generate_move` と同じ使い方）
- `katrain.config(path)` のシグネチャ（`generate_ai_move` の
  `katrain.config(f"ai/{ai_mode}")` と同じ呼び方に合わせる。default 引数が無ければ `or {}`）

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_tsumego_early_speculation.py tests/test_tsumego_speculation.py tests/test_tsumego_prefetch.py -v`
Expected: 全 PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/game.py tests/test_tsumego_early_speculation.py
git commit -m "feat(tsumego): root部分結果からの前倒し投機ウォッチャ（Game側・判定不変）"
```

---

### Task 4: E2E 回帰と計測（採用ゲート）

**Files:**
- Modify: `docs/superpowers/specs/2026-08-03-tsumego-stage3-early-speculation-design.md`（追記2として結果記録）

**Interfaces:**
- Consumes: Task 1-3 の完成コード
- Produces: 採用判定（正答不変＋root ウォール非劣化）と計測値

- [ ] **Step 1: スモーク＋発火ログ確認**

Run: `python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py V W`（正答不変: V=L12・W=H1）。
`generate_move_e2e.py` 単発 `--debug` で `前倒し投機:` 行が出ること、後続の実クエリ
（同深さ検証・コウ経路検査）と手・条件が突き合うこと、**GUI 相当の経路でしか発火しない場合
（players_info の strategy が CLI スタブに無い等）はその旨を確認して記録**すること
（CLI で発火しないならスモークは配管の非発火＝無害を確認し、発火検証は Step 2 の
計測ログに委ねる。katrain_stub の players_info を確認し、必要なら harness 側で
strategy=AI_TSUMEGO の FakeInfo を立てる — **本体コードは変えない**）

- [ ] **Step 2: フル回帰（正答不変ゲート）**

Run: `python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py --full`
（**20分超。コントローラ直営のデタッチ＋Monitor 推奨**。サブエージェント実行ならフォアグラウンド分割）
Expected: 正答が前回（親スペック追記1: 66/69・K@0/R@2/Z@2 は既知分散）と同水準。
新たな回帰点失敗が出たら、フック接続前コミットとの A/B（**worktree＋`PYTHONPATH` 明示**）で
裁定してから進む

- [ ] **Step 3: 時間計測（採用ゲート込み）**

M@4 / O@0 / V2@0 / V2@2 を段階1+2 時点（コミット 964c132 以前の HEAD ではなく、**本プランの
Task 3 直前コミット**）と Task 3 後で比較（各1プロセス3rep・`--debug`・両側同一方式）:
- **root ウォール（analyse 秒）非劣化 +0.3秒以内**（採用ゲート。劣化したら
  `TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION` を 0.75 に上げて再測、それでも劣化なら
  ウォッチャの発火を revert して BLOCKED 報告）
- コールド run1 の「root待ち＋着手決定」合計の before/after
- 発火時刻と検証バッチ実クエリの応答時間（温めヒットの実証）
- 参考: fraction 0.5（1本目の部分結果で発火＝温め猶予 約1.4秒）の A/B を1ケース
  （V2@0）だけ取り、0.67 との差をスペックに記録（採用は別判断＝数値を残すだけ）

- [ ] **Step 4: スペック追記2に記録してコミット**

```bash
git add docs/superpowers/specs/2026-08-03-tsumego-stage3-early-speculation-design.md
git commit -m "docs(tsumego): 段階3の実測（回帰・rootウォール非劣化・コールド短縮）を追記"
```

---

### Task 5: ドキュメント更新

**Files:**
- Modify: `CLAUDE.md`（概要の詰碁高速化記述に段階3の1文追記）
- Modify: `.claude/rules/ai-parameters.md`（「高速化第4弾（2026-08-03・精度不変）」段落追加）

**Interfaces:**
- Consumes: Task 4 の確定計測値
- Produces: なし（記録のみ）

- [ ] **Step 1: CLAUDE.md 概要へ1文追記**

手番内投機（2026-08-03）の記述の直後に: 「さらに root 部分結果（visits 合計 0.67×1800）到達時点で Game 側ウォッチャが検証バッチ本体込みの温め集合を前倒し発行（段階3・2026-08-03）。コールド1手目合計 X.X〜X.X秒 → Y.Y〜Y.Y秒（実測値は Task 4 の結果で置換）。spec は 2026-08-03-tsumego-stage3-early-speculation-design.md」

- [ ] **Step 2: ai-parameters.md へ「高速化第4弾」段落追加**

内容: 発火場所（Game 側ウォッチャ＝prefetch の鏡像・戦略コード不変）/ 閾値定数 / 温め集合（検証バッチ本体＋段階1+2）/ 遅延 import の理由（循環回避）/ 採用ゲートの実測値 / 「戦略の wait_for_analysis は実質 no-op（root 待ちは戦略の外）」という棚卸し事実。
※ Edit が拒否されたらサブエージェント経由（CLAUDE.md の既知の問題）

- [ ] **Step 3: コミット**

```bash
git add CLAUDE.md .claude/rules/ai-parameters.md
git commit -m "docs(tsumego): 段階3（前倒し投機）の記録"
```

---

## Self-Review 結果

- スペック§3.1（Game側ウォッチャ・閾値・bail 条件）→ Task 3 / §3.2（温め集合・遅延import・純関数）→ Task 2+3 / §3.3（判定不変）→ Global Constraints＋Task 3 の設計（戦略コード不変） / §4-1（payload 実測）→ Task 1（否の場合の差し替え手順込み） / §4-2（リーク防止）→ Task 3 の bail・cancel テスト / §4-3・§5（採用ゲート・計測）→ Task 4 / ドキュメント → Task 5
- 型整合: `tsumego_early_speculation_items` のシグネチャと返り値形式は Task 2 定義・Task 3 使用・テストで一致。`board_size` はタプル。`_early_speculation_nodes` は Task 3 内で一貫
- 既知の不確実性（実装者への注意として本文に明記済み）: PlayerInfo の `strategy` 属性名 / `katrain.config` のシグネチャ / CLI スタブでの発火可否（Task 4 Step 1）。いずれも「存在しなければ発火しない＝安全側」に倒してある
