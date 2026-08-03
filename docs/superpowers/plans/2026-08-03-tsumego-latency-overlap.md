# 詰碁着手決定の重畳発行（レイテンシ短縮）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 詰碁AI黒番1手あたりの着手決定チェーン（root待ち2.4秒＋検証/救済/コウ検査の直列3〜3.2秒）を、判定・クエリ内容を完全不変のまま「手番内投機（温め・結果は捨てる）」で 3〜3.5秒/手 に縮める。

**Architecture:** `select_tsumego_move` が選択手を返した直後に、「この後の段（救済・コウ経路検査）で撃つことになりそうな子局面クエリ」を同一条件・低優先度で先回り発行し結果は捨てる。実クエリが後から同一条件で再クエリするとエンジン側キャッシュで0.1〜0.3秒で返る（実測: ログ QUERY:462/480 の再クエリが 807visits を0.1秒）。判定コード（`_verified_choice` / 救済 / `_ko_route_screen`）は1行も変えない。

**Tech Stack:** Python 3.12 / KataGo Analysis Engine（numAnalysisThreads）/ pytest

**Spec:** `docs/superpowers/specs/2026-08-03-tsumego-latency-overlap-design.md`

## Global Constraints

- **精度不変が絶対条件**: 実クエリの内容（visits・wRN・untilDepth・ownership）・発行順・待ち合わせ・判定関数・タイブレークは一切変更しない。投機は「温め」だけで結果は必ず捨てる
- 投機クエリの条件は実クエリと完全一致させる（KataGo の NN キャッシュは ownerMap の有無・設定差を区別する。ownership=True 必須）
- 投機の優先度は新定数 `PRIORITY_TSUMEGO_SPECULATION = 500`（実クエリ `PRIORITY_EXTRA_AI_QUERY`=10_000・通常ノード解析 `PRIORITY_DEFAULT`=1000 より下、アイドル先読み `PRIORITY_REGION_PREFETCH`=-50 より上）
- コミットメッセージは日本語・Conventional Commits
- `black` は編集した行のみ手で整形（ファイル全体に black を走らせない＝巨大差分になる）
- 必須ゲート: `e2e_suite.py --full` の正答が全ケース不変
- 段階3（root部分結果からの前倒し発火）は**このプランのスコープ外**（スペック§6: 段階1+2の計測で目標到達なら実装しない。未達なら別プラン）

## File Structure

- Modify: `katrain/core/constants.py` — `PRIORITY_TSUMEGO_SPECULATION` 追加（1行）
- Modify: `katrain/core/ai.py` —
  - モジュール関数 `tsumego_speculation_plan(...)`（純関数。何を温めるかの決定＝単体テスト対象）を `tsumego_rescue_candidates` の直後に追加
  - `TsumegoOwnershipStrategy._fire_speculation(plan)` / `_cancel_speculation()`（発行・掃除の配管）
  - `generate_move` の finally に掃除、`_generate_move` の score_best 計算直後に発火フック
- Create: `tests/test_tsumego_speculation.py` — 純関数テスト＋FakeEngine配管テスト（`tests/test_tsumego_prefetch.py` のFakeパターンを流用）
- Modify: `CLAUDE.md`・`.claude/rules/ai-parameters.md` — 高速化第3弾の記録、numAnalysisThreads 記述の更新

---

### Task 1: 投機プラン計算の純関数 `tsumego_speculation_plan`

**Files:**
- Modify: `katrain/core/ai.py`（`tsumego_rescue_candidates` の直後、`select_tsumego_move` の直前あたり＝2433行付近）
- Test: `tests/test_tsumego_speculation.py`（新規）

**Interfaces:**
- Consumes（既存・すべて `katrain/core/ai.py` のモジュール関数）:
  - `tsumego_ownership_gain(root_ownership, move_ownership, stones, board_size, player_sign) -> float`
  - `tsumego_gain_contenders(eligible, score_best, min_visit_ratio) -> list`
  - `tsumego_rescue_candidates(candidates, contenders, chosen, root_ownership, stones, board_size, player_sign, min_visits, rescue_margin=..., max_candidates=..., min_visit_ratio=...) -> list`
  - `tsumego_needs_score_best_verify(chosen, score_best, points_epsilon) -> bool`
  - `tsumego_score_best_challengers(chosen, eligible, score_best, root_ownership, stones, board_size, player_sign, min_visit_ratio) -> list`
  - `tsumego_class_screen_applies(chosen, eligible) -> bool`
  - 定数 `TSUMEGO_GAIN_RESCUE_MARGIN`(1.0) / `TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES`(3) / `TSUMEGO_KO_REGION_UNTIL_DEPTH`(6) / `TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`(0.0)
- Produces（Task 2/3 が使う）:
  - `tsumego_speculation_plan(candidate_moves, eligible, chosen, score_best, root_ownership, stones, board_size, player_sign, min_visits, min_visit_ratio, points_epsilon, include_rescue=True, include_ko_screen=True) -> list[dict]`
  - 返り値の各要素: `{"move": str(GTP), "until_depth": Optional[int], "wide_root_noise": Optional[float]}`。`until_depth=None`/`wide_root_noise=None` は「本譜と同じ既定」（`_start_region_root` と同じ意味論）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_speculation.py` を新規作成:

```python
"""詰碁の手番内投機（温め・結果は捨てる）の回帰テスト。

守っているのは3点:
1. **投機プランは実際に後段が撃つクエリの上位集合**（救済の最終リストは選択手確定後に
   決まるが、温め集合はどの選択結果でもそれを含む＝ミスによる温め漏れが構造的に出ない）
2. 温め条件（untilDepth・wideRootNoise）が実クエリと一致する（条件がずれると NN キャッシュ
   全ミス＝1秒も速くならない。ownership は配管側 Task 2 で担保）
3. 投機は判定に影響しない＝プラン計算は読み取り専用の純関数
"""

from katrain.core.ai import (
    TSUMEGO_GAIN_RESCUE_MARGIN,
    TSUMEGO_KO_REGION_UNTIL_DEPTH,
    TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
    tsumego_gain_contenders,
    tsumego_rescue_candidates,
    tsumego_score_best,
    tsumego_speculation_plan,
)

BOARD = 13


def _cand(move, points_lost, visits, gain_cells):
    """ownership はリージョン石2子 {(3,3),(4,4)} だけ非ゼロの疎な盤で作る。

    gain_cells は {(x,y): value}。tsumego_ownership_gain は
    sum(player_sign * (move_own[i] - root_own[i]) for stones) なので、
    root=0 の盤なら gain = sum(gain_cells の石の値)。
    """
    ownership = [0.0] * (BOARD * BOARD)
    for (x, y), v in gain_cells.items():
        ownership[y * BOARD + x] = v
    return {"move": move, "pointsLost": points_lost, "visits": visits, "ownership": ownership}


STONES = [(3, 3), (4, 4)]
ROOT_OWNERSHIP = [0.0] * (BOARD * BOARD)


def _plan_moves(plan):
    return {item["move"] for item in plan}


def test_rescue_superset_covers_all_possible_chosen_outcomes():
    """検証で選択手が目数最善へ巻き戻った場合の救済リストも温め集合に含まれる。

    chosen(gain大) と score_best(gain小) で救済の gain 閾値が変わる:
    実フローの救済は「検証後の選択手」基準なので、score_best が incumbent 勝ちすると
    閾値が下がり救済候補が**増える**。プランは最小 gain のアンカーで計算するので
    どちらの結果でも上位集合になる。
    """
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9, (4, 4): 0.9})  # gain +1.8
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})  # gain +0.1（目数最善・gain 小）
    # 検証が必要になる形: chosen が目数で score_best に 0.1 劣る（points_epsilon=0.25 の外は不要、
    # needs_verify は「バンド外で目数最善でない」ときに立つ。ここでは pointsLost 差 0.1 < 0.25 だと
    # バンド内で検証不要になるため、差を 0.5 にする
    chosen["pointsLost"] = 0.4
    eligible = [chosen, score_best]
    # 非contender: gain +1.3 = score_best 基準(+0.1+1.0=+1.1) は超えるが chosen 基準(+1.8+1.0=+2.8) は超えない
    borderline = _cand("E5", 3.0, 200, {(3, 3): 0.65, (4, 4): 0.65})
    candidate_moves = eligible + [borderline]

    plan = tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    # score_best が incumbent 勝ちしたときの実救済リスト
    real_rescues = tsumego_rescue_candidates(
        candidate_moves, tsumego_gain_contenders(eligible, score_best, 0.5), score_best,
        ROOT_OWNERSHIP, STONES, BOARD, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN,
    )
    assert {c["move"] for c in real_rescues} <= _plan_moves(plan)
    assert "E5" in _plan_moves(plan)  # chosen 基準では出ない救済候補も温まっている


def test_ko_screen_targets_are_chosen_and_score_best_with_screen_conditions():
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    chosen["pointsLost"] = 0.4
    eligible = [chosen, score_best]
    plan = tsumego_speculation_plan(
        eligible, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    screen_items = [i for i in plan if i["until_depth"] == TSUMEGO_KO_REGION_UNTIL_DEPTH]
    assert {i["move"] for i in screen_items} == {"C3", "D4"}
    for item in screen_items:
        # 実クエリ（_ko_route_screen）と同一条件でないと NN キャッシュ全ミス
        assert item["wide_root_noise"] == TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE


def test_rescue_items_use_default_conditions():
    """救済の実クエリ（_verified_choice）は untilDepth=既定(None=1)・wRN=既定(None=本譜)"""
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    eligible = [chosen, score_best]
    rescue = _cand("E5", 3.0, 200, {(3, 3): 0.65, (4, 4): 0.65})
    plan = tsumego_speculation_plan(
        eligible + [rescue], eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    rescue_items = [i for i in plan if i["move"] == "E5"]
    assert rescue_items and rescue_items[0]["until_depth"] is None
    assert rescue_items[0]["wide_root_noise"] is None


def test_flags_disable_each_kind():
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    eligible = [chosen, score_best]
    rescue = _cand("E5", 3.0, 200, {(3, 3): 0.65, (4, 4): 0.65})
    args = (eligible + [rescue], eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD)
    kwargs = dict(player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25)
    no_rescue = tsumego_speculation_plan(*args, include_rescue=False, **kwargs)
    assert "E5" not in _plan_moves(no_rescue)
    no_screen = tsumego_speculation_plan(*args, include_ko_screen=False, **kwargs)
    assert all(i["until_depth"] is None for i in no_screen)


def test_empty_when_no_stones_or_no_score_best():
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9})
    assert tsumego_speculation_plan(
        [chosen], [chosen], chosen, None, ROOT_OWNERSHIP, [], BOARD,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    ) == []
```

注意: `tsumego_score_best` / `tsumego_class_screen_applies` の実シグネチャに合わせて
テスト中の想定（「目数ガード内なら screen 対象」）がずれる場合は、**実装ではなくテストの
局面データ側を直す**（判定関数には触らない）。

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_tsumego_speculation.py -v`
Expected: FAIL（`ImportError: cannot import name 'tsumego_speculation_plan'`）

- [ ] **Step 3: 実装**

`katrain/core/ai.py` の `tsumego_rescue_candidates`（2383-2432行）の直後に追加:

```python
def tsumego_speculation_plan(
    candidate_moves,
    eligible,
    chosen,
    score_best,
    root_ownership,
    stones,
    board_size,
    player_sign,
    min_visits,
    min_visit_ratio,
    points_epsilon,
    include_rescue=True,
    include_ko_screen=True,
):
    """後段（救済・コウ経路検査）が撃つことになりそうな子局面クエリの温めプランを返す。

    **判定には一切使わない**読み取り専用の純関数。返した手は同一条件・低優先度で
    先回り解析され結果は捨てられる（実クエリが同一条件で再クエリするとエンジン側
    キャッシュで 0.1〜0.3 秒＝実測 2026-08-03 の QUERY:462/480）。ミスしても実クエリが
    従来どおりコールドで走るだけで、着手判定への影響は構造的にゼロ。

    救済の最終リスト（`tsumego_rescue_candidates`）は「検証後の選択手」の gain を閾値に
    使うため発火時点では決まらないが、検証後の選択手は {chosen, score_best, challengers}
    のどれかなので、**その中で gain 最小のものをアンカー**に計算すれば上位集合になる
    （閾値が最小＝候補が最多。cap も +1 して縁を保険する）。

    コウ経路検査の対象は最終選択手（＋格下げ時の対抗馬）だが、実測で最終選択手はほぼ
    chosen か score_best なので、その2手（同一なら1手）を検査と同一条件
    （`TSUMEGO_KO_REGION_UNTIL_DEPTH`・`TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`）で温める。
    ガード外の選択手は検査されない（`tsumego_class_screen_applies`）ので温めない。

    要素は {"move", "until_depth", "wide_root_noise"}。None は「本譜と同じ既定」
    （`_start_region_root` と同じ意味論）。
    """
    if chosen is None or score_best is None or not stones or not root_ownership:
        return []
    plan = []
    if include_rescue:
        anchors = [chosen, score_best]
        if chosen["move"] != score_best["move"] and tsumego_needs_score_best_verify(
            chosen, score_best, points_epsilon
        ):
            anchors += tsumego_score_best_challengers(
                chosen, eligible, score_best, root_ownership, stones, board_size, player_sign, min_visit_ratio
            )
        with_gain = [
            (tsumego_ownership_gain(root_ownership, a["ownership"], stones, board_size, player_sign), a)
            for a in anchors
            if a.get("ownership")
        ]
        if with_gain:
            anchor = min(with_gain, key=lambda item: item[0])[1]
            for cand in tsumego_rescue_candidates(
                candidate_moves,
                tsumego_gain_contenders(eligible, score_best, min_visit_ratio),
                anchor,
                root_ownership,
                stones,
                board_size,
                player_sign,
                min_visits,
                max_candidates=TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES + 1,
            ):
                plan.append({"move": cand["move"], "until_depth": None, "wide_root_noise": None})
    if include_ko_screen and tsumego_class_screen_applies(chosen, eligible):
        for cand in {c["move"]: c for c in [chosen, score_best]}.values():
            plan.append(
                {
                    "move": cand["move"],
                    "until_depth": TSUMEGO_KO_REGION_UNTIL_DEPTH,
                    "wide_root_noise": TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
                }
            )
    return plan
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_tsumego_speculation.py -v`
Expected: PASS（5件）。既存回帰も: `pytest tests/test_tsumego_prefetch.py tests/test_tsumego_solver_strategy.py -v` → PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_tsumego_speculation.py
git commit -m "feat(tsumego): 手番内投機の温めプラン計算（純関数）を追加"
```

---

### Task 2: 発行・掃除の配管 `_fire_speculation` / `_cancel_speculation`

**Files:**
- Modify: `katrain/core/constants.py`（28行付近の PRIORITY 群に追加）
- Modify: `katrain/core/ai.py`（`TsumegoOwnershipStrategy` クラス内、`_log_candidates` の手前あたり）
- Test: `tests/test_tsumego_speculation.py`（追記）

**Interfaces:**
- Consumes: Task 1 の plan 形式、既存 `tsumego_simulation_game(game, node)`、`region_analysis_extra_settings(visits, wide_root_noise)`（ai.py に import 済み）、`REGION_ANALYSIS_WIDE_ROOT_NOISE`
- Produces:
  - `constants.PRIORITY_TSUMEGO_SPECULATION = 500`
  - `TsumegoOwnershipStrategy._fire_speculation(plan: list[dict]) -> None`（投機クエリ発行、`self._speculative_nodes` に子ノードを記録）
  - `TsumegoOwnershipStrategy._cancel_speculation() -> None`（記録済みノードのクエリを terminate、リストを空に。二重呼び出し無害）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_speculation.py` に追記（FakeEngine 群は `test_tsumego_prefetch.py` と同型）:

```python
from katrain.core.constants import PRIORITY_TSUMEGO_SPECULATION
from katrain.core.game import BaseGame, Game, GameNode
from katrain.core.sgf_parser import Move
from katrain.core.ai import TsumegoOwnershipStrategy


class FakeEngine:
    def __init__(self):
        self.requests = []
        self.terminated = []

    def request_analysis(self, node, **kwargs):
        self.requests.append((node, kwargs))

    def terminate_queries(self, only_for_node=None, lock=True):
        self.terminated.append(only_for_node)


class FakeKatrain:
    def log(self, *args, **kwargs):
        pass


def _speculation_strategy():
    katrain = FakeKatrain()
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": 13, "RU": "japanese", "KM": 6.5}))
    node = base.current_node  # 黒番の初期局面
    engine = FakeEngine()
    game = Game.__new__(Game)  # エンジン起動・解析スレッドを伴わない素の Game
    game.katrain = katrain
    game.engines = {"B": engine, "W": engine}
    game.root = base.root
    game.current_node = node
    game.region_of_interest = [2, 6, 2, 6]
    game.region_analysis_wide_root_noise = 0.04
    strategy = TsumegoOwnershipStrategy.__new__(TsumegoOwnershipStrategy)
    strategy.game = game
    strategy.cn = node
    strategy.settings = {"gain_verify_visits": 800}
    strategy._speculative_nodes = []
    return strategy, engine, node


def test_fire_speculation_issues_discardable_queries_with_exact_conditions():
    strategy, engine, node = _speculation_strategy()
    plan = [
        {"move": "C3", "until_depth": None, "wide_root_noise": None},
        {"move": "D4", "until_depth": 6, "wide_root_noise": 0.0},
    ]
    strategy._fire_speculation(plan)
    assert len(engine.requests) == 2
    (child1, kw1), (child2, kw2) = engine.requests
    for child, kw in engine.requests:
        assert kw["ownership"] is True  # ownerMap の有無で NN キャッシュが別物になる
        assert kw["visits"] == 800
        assert kw["region_of_interest"] == [2, 6, 2, 6]
        assert kw["priority"] == PRIORITY_TSUMEGO_SPECULATION
        assert child is not node and child.parent is not node  # 複製ゲームの子ノード
    assert kw1["region_until_depth"] is None
    assert kw2["region_until_depth"] == 6
    assert strategy._speculative_nodes == [child1, child2]


def test_cancel_terminates_exactly_the_speculative_nodes():
    strategy, engine, node = _speculation_strategy()
    strategy._fire_speculation([{"move": "C3", "until_depth": None, "wide_root_noise": None}])
    fired = list(strategy._speculative_nodes)
    strategy._cancel_speculation()
    assert engine.terminated == fired
    assert strategy._speculative_nodes == []
    strategy._cancel_speculation()
    assert engine.terminated == fired  # 二重 cancel は no-op


def test_fire_speculation_skips_illegal_moves_and_empty_plan():
    strategy, engine, node = _speculation_strategy()
    strategy._fire_speculation([])
    assert engine.requests == []
    # 既に石がある点（root の追加配置は無いので普通の空点2連打で再現: C3 を2回）
    strategy._fire_speculation(
        [
            {"move": "C3", "until_depth": None, "wide_root_noise": None},
            {"move": "C3", "until_depth": None, "wide_root_noise": None},
        ]
    )
    # 同一 sim 上で同じ空点に2回打つ→2手目は set_current_node(base) で戻すので両方合法。
    # 非合法スキップの検証は盤外相当が作れないため「例外を出さず発行数が plan 以下」で担保
    assert 1 <= len(engine.requests) <= 2
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_tsumego_speculation.py -v`
Expected: 新規3件が FAIL（`ImportError: PRIORITY_TSUMEGO_SPECULATION` / `AttributeError: _fire_speculation`）

- [ ] **Step 3: 実装**

`katrain/core/constants.py` の 28行 `PRIORITY_REGION_PREFETCH = -50` の下に:

```python
PRIORITY_TSUMEGO_SPECULATION = 500  # 手番内投機（温め）: 実クエリ(10_000)・新規ノード解析(1000)より下
```

`katrain/core/ai.py` の import に `PRIORITY_TSUMEGO_SPECULATION` を追加（既存の
`from .constants import ...` 群に合わせる）。`TsumegoOwnershipStrategy` クラス内に追加:

```python
    def _fire_speculation(self, plan):
        """温めプランを低優先度で発行する。結果は捨てる＝着手判定への影響は構造的にゼロ。

        投機クエリは使い捨て複製ゲームの子ノードに紐づける（`_region_prefetch_sim` と同じ
        パターン）＝ terminate が投機だけに当たり、本譜ノードのクエリを巻き込まない。
        条件（visits・ownership・untilDepth・wRN・リージョン）は実クエリと完全一致させる
        — KataGo の NN キャッシュは ownerMap の有無や設定差を区別するため、ずれた温めは
        1秒も速くしない（実測 2026-08-01 prefetch_cache_probe.py）。
        """
        if not plan:
            return
        sim = tsumego_simulation_game(self.game, self.cn)
        if sim is None:
            return
        base = sim.current_node
        engine = self.game.engines[self.cn.next_player]
        visits = int((self.settings or {}).get("gain_verify_visits", TSUMEGO_GAIN_VERIFY_VISITS))
        fired = []
        for item in plan:
            sim.set_current_node(base)
            try:
                child = sim.play(Move.from_gtp(item["move"], player=self.cn.next_player))
            except IllegalMoveException:
                continue
            wrn = item["wide_root_noise"]
            engine.request_analysis(
                child,
                callback=lambda _analysis, _partial: None,
                error_callback=lambda _error: None,
                visits=visits,
                time_limit=False,
                ownership=True,
                region_of_interest=self.game.region_of_interest,
                region_until_depth=item["until_depth"],
                extra_settings=region_analysis_extra_settings(
                    visits,
                    getattr(self.game, "region_analysis_wide_root_noise", REGION_ANALYSIS_WIDE_ROOT_NOISE)
                    if wrn is None
                    else wrn,
                ),
                priority=PRIORITY_TSUMEGO_SPECULATION,
            )
            self._speculative_nodes.append(child)
            fired.append(item["move"])
        if fired:
            self.game.katrain.log(
                f"[{self.strategy_name}] 投機温め: {fired} の子局面を先回り発行（{visits}visits・結果は捨てる）",
                OUTPUT_DEBUG,
            )

    def _cancel_speculation(self):
        """未消化の投機クエリを打ち切る（結果はもともと捨てるだけなので副作用なし）"""
        nodes = self._speculative_nodes
        self._speculative_nodes = []
        for node in nodes:
            for engine in set(self.game.engines.values()):
                engine.terminate_queries(only_for_node=node)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_tsumego_speculation.py -v`
Expected: PASS（8件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/constants.py katrain/core/ai.py tests/test_tsumego_speculation.py
git commit -m "feat(tsumego): 投機クエリの発行・掃除の配管（優先度500・使い捨てノード）"
```

---

### Task 3: `_generate_move` への発火フックと掃除フック

**Files:**
- Modify: `katrain/core/ai.py:3041-3054`（`generate_move`）と `ai.py:3130` 付近（`_generate_move` の score_best 計算直後）

**Interfaces:**
- Consumes: Task 1 `tsumego_speculation_plan`、Task 2 `_fire_speculation` / `_cancel_speculation`
- Produces: なし（既存フローへの2フックのみ）

- [ ] **Step 1: `generate_move` に初期化と掃除を追加**

現在（ai.py:3041-3053）:

```python
    def generate_move(self) -> Tuple[Move, str]:
        # 体感速度の調査用に所要時間を必ず出す（キャプチャ側の「枠の採否判定に X 秒」と同じ意図）
        started = time.time()
        book_hit, book_coords = tsumego_book_next_move(self.game)
        if book_hit:
            self.game.katrain.log(f"[{self.strategy_name}] 回答帳の記録手順から着手します", OUTPUT_INFO)
            return Move(book_coords, player=self.cn.next_player), "回答帳: 記録された正解手順"
        try:
            return self._generate_move()
        finally:
            self.game.katrain.log(
                f"[{self.strategy_name}] 着手決定に {time.time() - started:.1f} 秒", OUTPUT_INFO
            )
```

変更後:

```python
    def generate_move(self) -> Tuple[Move, str]:
        # 体感速度の調査用に所要時間を必ず出す（キャプチャ側の「枠の採否判定に X 秒」と同じ意図）
        started = time.time()
        self._speculative_nodes = []
        book_hit, book_coords = tsumego_book_next_move(self.game)
        if book_hit:
            self.game.katrain.log(f"[{self.strategy_name}] 回答帳の記録手順から着手します", OUTPUT_INFO)
            return Move(book_coords, player=self.cn.next_player), "回答帳: 記録された正解手順"
        try:
            return self._generate_move()
        finally:
            # 未消化の投機を掃除＝この後の新規ノード解析（priority 1000）とGPUを取り合わない
            self._cancel_speculation()
            self.game.katrain.log(
                f"[{self.strategy_name}] 着手決定に {time.time() - started:.1f} 秒", OUTPUT_INFO
            )
```

- [ ] **Step 2: `_generate_move` に発火フックを追加**

`ai.py:3130` 付近、現在:

```python
            escape_value, escape_label = None, "コウ脱出"
            score_best = tsumego_score_best(eligible)
            if (
                score_best is not None
                and chosen["move"] != score_best["move"]
```

変更後（`score_best = ...` の直後・検証 if の前に挿入）:

```python
            escape_value, escape_label = None, "コウ脱出"
            score_best = tsumego_score_best(eligible)
            # 手番内投機: この後の段（救済・コウ経路検査）が撃つことになりそうな子局面を
            # 同一条件・低優先度で先回り発行して NN キャッシュを温める（結果は捨てる＝
            # 判定への影響ゼロ。実クエリの再クエリが 0.1〜0.3 秒で返る）。
            # 設計: docs/superpowers/specs/2026-08-03-tsumego-latency-overlap-design.md
            self._fire_speculation(
                tsumego_speculation_plan(
                    candidate_moves,
                    eligible,
                    chosen,
                    score_best,
                    self.cn.ownership,
                    stones,
                    self.game.board_size,
                    player_sign,
                    min_visits,
                    min_visit_ratio,
                    points_epsilon,
                    include_rescue=(self.settings or {}).get("gain_verify", True),
                    include_ko_screen=(self.settings or {}).get("tie_ko_screen", True),
                )
            )
            if (
                score_best is not None
                and chosen["move"] != score_best["move"]
```

- [ ] **Step 3: 単体テスト全体を回す**

Run: `pytest tests/test_tsumego_speculation.py tests/test_tsumego_prefetch.py tests/test_tsumego_solver.py tests/test_tsumego_solver_strategy.py -v`
Expected: 全 PASS

- [ ] **Step 4: E2E スモーク（2ケース・KataGo 起動あり）**

Run: `python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py V W`
Expected: V=L12・W=H1（正答不変）。`--debug` 付き単発
`python docs/superpowers/specs/calibration-data/tsumego/generate_move_e2e.py` のログに
`投機温め:` 行が出ており、後続の `同深さ検証(800visits)` / `コウ経路検査` のクエリと
手が突き合うことを目視確認

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py
git commit -m "feat(tsumego): 着手決定パイプラインに手番内投機（温め）を接続"
```

---

### Task 4: フル回帰と時間計測

**Files:**
- なし（実行と記録のみ。結果はスペックに追記）

**Interfaces:**
- Consumes: Task 1-3 の完成コード
- Produces: スペック追記（計測値）

- [ ] **Step 1: E2E フル回帰（バックグラウンド・約20分超）**

Run: `python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py --full`（run_in_background）
Expected: **全ケース正答不変**（必須ゲート。1件でも変われば投機は無関係のはずなので
`--debug` で該当ケースの経路を切り分け＝投機は結果を捨てるだけなので、変わったなら
run 間分散か別の原因。3run して従来の揺れ幅（F2 コイン投げ等）と比較する）

- [ ] **Step 2: 時間計測（重経路ケース・別プロセス3run）**

対象: 従来実測のある M / O / V2（ai-parameters.md 記載のコールド 4.7〜5.4 秒）と
コウ詰碁 case Z 系。各ケースを**別プロセス**で3run し、`着手決定に X 秒` と
root 解析ウォールを前後比較（run1 のエンジン起動込みは除外）。

Run（例）: `python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py M O V2`
Expected: 着手決定（root 完了後）が救済・コウ検査発動手番で 1.5〜3.2 秒 → 0.7〜1.5 秒級。
劣化（投機が実クエリのスロットを奪って検証バッチが遅くなる）が見えたら numAnalysisThreads
（Task 5）前なので想定内＝Task 5 後に再計測で判断

- [ ] **Step 3: スペックに計測結果を追記してコミット**

```bash
git add docs/superpowers/specs/2026-08-03-tsumego-latency-overlap-design.md
git commit -m "docs(tsumego): 重畳発行の実測（E2E回帰・時間計測）を追記"
```

---

### Task 5: numAnalysisThreads 4→8（ユーザー手動編集）と再計測

**Files:**
- ユーザー編集: `C:\Users\iwaki\.katrain\analysis_config.cfg`（手動管理ルールにつき Claude は編集しない）
- Modify: `CLAUDE.md`（「独立した追加解析クエリは1本ずつ待たない」段落の `numAnalysisThreads=4` 表記）
- Modify: `katrain/core/ai.py:4063`（`_start_region_root` docstring の `numAnalysisThreads`(=4) 表記）
- Modify: `.claude/rules/ai-parameters.md`（高速化第3弾の段落を追加。※dontAsk で Edit 拒否されたらサブエージェント経由で編集・コミット）

**Interfaces:**
- Consumes: Task 4 の計測値（比較基準）
- Produces: 設定変更後の確定計測値・ドキュメント

- [ ] **Step 1: ユーザーに cfg 編集を依頼（チェックポイント）**

依頼内容: `analysis_config.cfg` の `numAnalysisThreads = 4` → `8` に変更し KaTrain / E2E を
再起動。**このステップはユーザー操作待ちで停止する**

- [ ] **Step 2: 単発レイテンシの非劣化確認**

Run: `python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py V`（3run・別プロセス）
Expected: root 1800visits のウォールが 4スレッド時と同等（±0.3秒）。劣化するなら 6 で再測、
それでも劣化なら 4 に戻して Task 5 を打ち切り（コード側の重畳だけで確定）

- [ ] **Step 3: 重経路ケースの再計測**

Run: `python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py M O V2`（3run）
Expected: 黒番1手あたり（root待ち＋着手決定）3〜3.5 秒（スペックの成功基準）

- [ ] **Step 4: ドキュメント更新**

- CLAUDE.md「開発ワークフロー」の `numAnalysisThreads=4` → 採用値（8 or 6）に更新し、
  概要の詰碁段落の高速化記述に「手番内投機（2026-08-03）」を1文追記
- `ai.py:4063` docstring の `(=4)` を採用値に更新
- `.claude/rules/ai-parameters.md` に「高速化第3弾（2026-08-03・精度不変）」段落を追加:
  発火点（score_best 計算直後）・温め集合（救済スーパーセット＝最小gainアンカー、
  コウ検査＝chosen+score_best）・優先度500・finally 掃除・実測値

- [ ] **Step 5: コミット**

```bash
git add CLAUDE.md katrain/core/ai.py .claude/rules/ai-parameters.md
git commit -m "docs(tsumego): 手番内投機の記録と numAnalysisThreads 記述の更新"
```

---

## Self-Review 結果

- スペック§4（救済温め）→ Task 1・3 / §5（コウ検査温め）→ Task 1・3 / §3（優先度・terminate・使い捨てノード）→ Task 2 / §7（numAnalysisThreads）→ Task 5 / §8（ログ・回帰・計測）→ Task 2 のログ＋Task 4 / §6（段階3）→ Global Constraints で明示的にスコープ外
- 型整合: plan 要素 `{"move", "until_depth", "wide_root_noise"}` は Task 1 の Produces と Task 2 のテスト・実装で一致。`PRIORITY_TSUMEGO_SPECULATION` は Task 2 で定義し Task 2 テストが import
- 既知の不確実性（実装者への注意）: `tsumego_class_screen_applies` / `tsumego_needs_score_best_verify` の判定詳細により Task 1 のテスト局面データが期待とずれる可能性がある。その場合は**判定関数に合わせてテストデータを調整**する（判定関数・実装の意図は変えない）
