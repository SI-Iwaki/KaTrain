"""詰碁の手番内投機（温め・結果は捨てる）の回帰テスト。

守っているのは3点:
1. **投機プランは実際に後段が撃つクエリの上位集合**（救済の最終リストは選択手確定後に
   決まるが、温め集合はどの選択結果でもそれを含む＝ミスによる温め漏れが構造的に出ない。
   アンカー選定は chosen・score_best だけでなく `tsumego_score_best_challengers` 経由の
   第3の eligible 候補にも及ぶ＝その候補が検証後の勝者になるケースも塞ぐ）
2. 温め条件（untilDepth・wideRootNoise・**rescue_margin**）が実クエリと一致する（条件が
   ずれると NN キャッシュ全ミス＝1秒も速くならない。特に rescue_margin はユーザー設定
   `gain_rescue_margin` を渡す経路なので既定値決め打ちだと上位集合が破れる。ownership は
   配管側 Task 2 で担保）
3. 投機は判定に影響しない＝プラン計算は読み取り専用の純関数
"""

from katrain.core.ai import (
    TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION,
    TSUMEGO_GAIN_RESCUE_MARGIN,
    TSUMEGO_KO_REGION_UNTIL_DEPTH,
    TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE,
    TsumegoOwnershipStrategy,
    tsumego_early_speculation_items,
    tsumego_gain_contenders,
    tsumego_rescue_candidates,
    tsumego_speculation_plan,
)
from katrain.core.constants import PRIORITY_TSUMEGO_SPECULATION
from katrain.core.game import BaseGame, Game, GameNode, Move

BOARD = 13
# tsumego_ownership_gain は var_to_grid(ownership, board_size) 経由で盤を読むため、
# board_size は int ではなく (width, height) タプル（katrain 全体で game.board_size がそう）。
# 実装（katrain/core/ai.py 内 game.board_size の使われ方）を読んで確認し、テスト側をこれに合わせる。
BOARD_SIZE = (BOARD, BOARD)


def _cand(move, points_lost, visits, gain_cells):
    """ownership はリージョン石2子 {(3,3),(4,4)} だけ非ゼロの疎な盤で作る。

    `tsumego_ownership_gain` は `katrain.core.utils.var_to_grid` 経由で ownership 配列を
    grid[y][x] に変換する。`var_to_grid` は y=board_size-1 から 0 へ向けて board_size 個ずつ
    詰めるため、配列インデックスは `y*board_size+x` ではなく
    `(board_size-1-y)*board_size+x`（実装を読んで確認・座標系をここに合わせている）。

    gain_cells は {(x,y): value}。tsumego_ownership_gain は
    sum(player_sign * (move_own[i] - root_own[i]) for stones) なので、
    root=0 の盤なら gain = sum(gain_cells の石の値)。
    """
    ownership = [0.0] * (BOARD * BOARD)
    for (x, y), v in gain_cells.items():
        ownership[(BOARD - 1 - y) * BOARD + x] = v
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
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    # score_best が incumbent 勝ちしたときの実救済リスト
    real_rescues = tsumego_rescue_candidates(
        candidate_moves, tsumego_gain_contenders(eligible, score_best, 0.5), score_best,
        ROOT_OWNERSHIP, STONES, BOARD_SIZE, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN,
    )
    assert {c["move"] for c in real_rescues} <= _plan_moves(plan)
    assert "E5" in _plan_moves(plan)  # chosen 基準では出ない救済候補も温まっている


def test_ko_screen_targets_are_chosen_and_score_best_with_screen_conditions():
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    chosen["pointsLost"] = 0.4
    eligible = [chosen, score_best]
    plan = tsumego_speculation_plan(
        eligible, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
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
        eligible + [rescue], eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
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
    args = (eligible + [rescue], eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE)
    kwargs = dict(player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25)
    no_rescue = tsumego_speculation_plan(*args, include_rescue=False, **kwargs)
    assert "E5" not in _plan_moves(no_rescue)
    no_screen = tsumego_speculation_plan(*args, include_ko_screen=False, **kwargs)
    assert all(i["until_depth"] is None for i in no_screen)


def test_rescue_superset_covers_challenger_anchor_with_third_eligible_candidate():
    """検証後の勝者が chosen でも score_best でもない第3の eligible 候補になるケースも、
    アンカー選定（gain 最小）に取り込まれて上位集合が保たれる。

    F6 は `tsumego_score_best_challengers` 経由で anchors に入る第3の eligible 候補で、
    gain が chosen・score_best の両方より低い。F6 がアンカーに選ばれて初めて、chosen 基準
    （閾値+2.8）・score_best 基準（閾値+1.1）のどちらでも超えられない救済候補 G7
    （gain+1.08）が温め集合に入る（F6 基準の閾値は+1.05）。
    """
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})  # gain +1.8
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})  # gain +0.1
    # 第3の eligible 候補: gain は score_best よりさらに低く、visits は深さゲート(0.5)を通る
    third = _cand("F6", 0.2, 250, {(3, 3): 0.05})  # gain +0.05
    eligible = [chosen, score_best, third]
    # F6 基準の閾値(+0.05+1.0=+1.05)だけを超え、chosen(+2.8)・score_best(+1.1)基準では超えない
    rescue = _cand("G7", 3.0, 200, {(3, 3): 0.54, (4, 4): 0.54})  # gain +1.08
    candidate_moves = eligible + [rescue]

    plan = tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )

    # (a) chosen・score_best を直接アンカーにした実救済呼び出しでは G7 は救済されない
    # ＝F6 がアンカーになって初めて G7 が温め集合に入ることの裏づけ
    contenders = tsumego_gain_contenders(eligible, score_best, 0.5)
    rescue_with_chosen = tsumego_rescue_candidates(
        candidate_moves, contenders, chosen, ROOT_OWNERSHIP, STONES, BOARD_SIZE, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN
    )
    rescue_with_score_best = tsumego_rescue_candidates(
        candidate_moves, contenders, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN
    )
    assert "G7" not in {c["move"] for c in rescue_with_chosen}
    assert "G7" not in {c["move"] for c in rescue_with_score_best}

    # (b) F6（検証後の勝者）基準の実救済リストは温め集合に包含される
    rescue_with_third = tsumego_rescue_candidates(
        candidate_moves, contenders, third, ROOT_OWNERSHIP, STONES, BOARD_SIZE, 1, 10, TSUMEGO_GAIN_RESCUE_MARGIN
    )
    assert {c["move"] for c in rescue_with_third} <= _plan_moves(plan)
    assert "G7" in _plan_moves(plan)  # F6 がアンカーに選ばれて初めて温まる救済候補


def test_rescue_margin_parameter_propagates_to_rescue_threshold():
    """rescue_margin を明示的に渡すと救済の閾値が変わる（実救済のユーザー設定
    `gain_rescue_margin` と揃える経路）。

    既定 margin(1.0) では救済候補 H8(gain +0.9) は score_best 基準の閾値(+0.1+1.0=+1.1)
    を超えられず温まらないが、より狭い margin(0.5) を渡すと閾値(+0.1+0.5=+0.6) を超えて
    温め対象に入る。`tsumego_speculation_plan` が rescue_margin を内部の
    `tsumego_rescue_candidates` 呼び出しに伝播していないと、この2つの呼び出し結果が
    同じになり後半の assert が失敗する。
    """
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})  # gain +1.8
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})  # gain +0.1
    eligible = [chosen, score_best]
    borderline_margin = _cand("H8", 3.0, 200, {(3, 3): 0.45, (4, 4): 0.45})  # gain +0.9
    candidate_moves = eligible + [borderline_margin]

    plan_default = tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    )
    assert "H8" not in _plan_moves(plan_default)

    plan_narrow_margin = tsumego_speculation_plan(
        candidate_moves, eligible, chosen, score_best, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25, rescue_margin=0.5,
    )
    assert "H8" in _plan_moves(plan_narrow_margin)


def test_empty_when_no_score_best():
    """score_best=None（後段の検証がまだ走っていない等）は stones があってもガードで [] を返す。"""
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9})
    assert tsumego_speculation_plan(
        [chosen], [chosen], chosen, None, ROOT_OWNERSHIP, STONES, BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    ) == []


def test_empty_when_no_stones():
    """score_best があっても stones=[]（gain 集計対象なし）ならガードで [] を返す。"""
    chosen = _cand("C3", 0.0, 500, {(3, 3): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    assert tsumego_speculation_plan(
        [chosen, score_best], [chosen, score_best], chosen, score_best, ROOT_OWNERSHIP, [], BOARD_SIZE,
        player_sign=1, min_visits=10, min_visit_ratio=0.5, points_epsilon=0.25,
    ) == []


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


def _speculation_strategy(pre_moves=None, engine_cls=FakeEngine):
    katrain = FakeKatrain()
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": 13, "RU": "japanese", "KM": 6.5}))
    node = base.current_node  # 黒番の初期局面
    for gtp in pre_moves or []:
        node = base.play(Move.from_gtp(gtp, player=node.next_player))
    engine = engine_cls()
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
    strategy.strategy_name = "TsumegoOwnershipStrategy"
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
    # wRN の伝播検証: NN キャッシュ全ミス対策で実クエリと完全一致が必須
    assert kw1["extra_settings"]["wideRootNoise"] == 0.04  # None→本譜の既定値
    assert kw2["extra_settings"]["wideRootNoise"] == 0.0   # 指定あり→その値
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


def test_fire_speculation_skips_move_on_occupied_point():
    """cn が黒 C3 を打った直後の局面（次番=白）で、plan が既に石のある C3 を狙うと
    非合法手として例外を出さずスキップされる（`sim.play` の IllegalMoveException）。"""
    strategy, engine, node = _speculation_strategy(pre_moves=["C3"])
    strategy._fire_speculation([{"move": "C3", "until_depth": None, "wide_root_noise": None}])
    assert engine.requests == []
    assert strategy._speculative_nodes == []


class RaisingOnceEngine(FakeEngine):
    """1回目の request_analysis だけ例外を送出し、以降は通常どおり記録する。

    投機は純最適化なので、1件のクエリ発行が失敗しても他の予定（後続 plan 項目）は
    続行されねばならない（`_fire_speculation` の per-item ガードの検証用）。
    """

    def __init__(self):
        super().__init__()
        self._calls = 0

    def request_analysis(self, node, **kwargs):
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("boom")
        super().request_analysis(node, **kwargs)


def test_fire_speculation_isolates_request_analysis_exception():
    strategy, engine, node = _speculation_strategy(engine_cls=RaisingOnceEngine)
    plan = [
        {"move": "C3", "until_depth": None, "wide_root_noise": None},  # 1件目: 例外で失敗
        {"move": "D4", "until_depth": None, "wide_root_noise": None},  # 2件目: 成功して残る
    ]
    strategy._fire_speculation(plan)
    assert len(engine.requests) == 1
    assert len(strategy._speculative_nodes) == 1


def test_early_items_include_verify_batch_and_stage12_sets():
    """検証バッチ本体（chosen・score_best・挑戦者、条件None/None）と段階1+2集合の和集合を返す"""
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


def test_early_items_keep_same_move_under_different_conditions():
    """dedup のキーは (move, until_depth, wide_root_noise) の3要素で、move だけでは潰さない。

    C3 は検証バッチ本体（until_depth=None/wRN=None）とコウ検査温め（until_depth=6/wRN=0.0）の
    両方に対象として現れる。同じ手でも条件が違えば別クエリなので両方とも残らねばならない
    （move だけで潰す実装だと、後段の実クエリの一方が温まらずキャッシュミスする）。
    全キーがユニークであること自体は重複排除の回帰網として引き続き有効。
    """
    chosen = _cand("C3", 0.4, 500, {(3, 3): 0.9, (4, 4): 0.9})
    score_best = _cand("D4", -0.1, 400, {(3, 3): 0.1})
    items = tsumego_early_speculation_items(
        [chosen, score_best], ROOT_OWNERSHIP, STONES, (BOARD, BOARD), 1, {}
    )
    keys = [(i["move"], i["until_depth"], i["wide_root_noise"]) for i in items]
    assert len(keys) == len(set(keys))
    assert ("C3", None, None) in keys
    assert ("C3", TSUMEGO_KO_REGION_UNTIL_DEPTH, TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE) in keys


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
