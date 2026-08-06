# tests/test_ai_parity9.py
"""9路専用「一致率追随」戦略 ai:parity9 の純関数テスト（KataGo/Kivy 不要）。"""
from types import SimpleNamespace

from katrain.core.ai import (
    PARITY9_UNSETTLED_ABS,
    Parity9Strategy,
    parity9_budget,
    parity9_build_candidates,
    parity9_is_endgame,
    parity9_match_tally,
    parity9_select,
)


class FakeMove:
    def __init__(self, gtp):
        self._gtp = gtp

    def gtp(self):
        return self._gtp


def node(player, gtp, top_gtp, complete=True):
    """一致判定に必要な最小限の属性だけを持つ疑似ノードを作る。

    top_gtp=None で「親の candidate_moves が空」を表す。
    """
    return SimpleNamespace(
        player=player,
        move=FakeMove(gtp),
        is_root=False,
        parent=SimpleNamespace(
            analysis_complete=complete,
            candidate_moves=[{"move": top_gtp}] if top_gtp is not None else [],
        ),
    )


class TestMatchTally:
    def test_empty_history(self):
        assert parity9_match_tally([], "B") == (0, 0, 0)

    def test_black_all_matched(self):
        # B/W が交互に2手ずつ、全員が最善手と一致
        nodes = [
            node("B", "E5", "E5"),
            node("W", "C3", "C3"),
            node("B", "G7", "G7"),
            node("W", "G3", "G3"),
        ]
        assert parity9_match_tally(nodes, "B") == (2, 2, 2)

    def test_black_leads_when_opponent_misses(self):
        nodes = [
            node("B", "E5", "E5"),
            node("W", "C3", "D4"),   # 不一致
            node("B", "G7", "G7"),
            node("W", "G3", "G3"),
        ]
        assert parity9_match_tally(nodes, "B") == (2, 1, 2)

    def test_white_truncates_opponent_extra_move(self):
        # 白の手番直前: B が3手、W が2手。B の3手目は切り捨てる
        nodes = [
            node("B", "E5", "E5"),   # 一致（数える）
            node("W", "C3", "C3"),   # 一致
            node("B", "G7", "G7"),   # 一致（数える）
            node("W", "G3", "D4"),   # 不一致
            node("B", "C7", "C7"),   # 一致だが切り捨て
        ]
        assert parity9_match_tally(nodes, "W") == (1, 2, 2)

    def test_skips_nodes_without_complete_parent_analysis(self):
        nodes = [
            node("B", "E5", "E5"),
            node("W", "C3", "C3"),
            node("B", "G7", "G7", complete=False),   # 両者とも列に入れない
            node("W", "G3", "G3"),
        ]
        # B は1手、W は2手 → opp は先頭1手だけ
        assert parity9_match_tally(nodes, "B") == (1, 1, 1)

    def test_skips_nodes_with_empty_candidate_moves(self):
        nodes = [
            node("B", "E5", None),   # candidate_moves 空
            node("W", "C3", "C3"),
            node("B", "G7", "G7"),
        ]
        assert parity9_match_tally(nodes, "B") == (1, 1, 1)

    def test_pass_is_compared_like_any_move(self):
        nodes = [
            node("B", "pass", "pass"),
            node("W", "C3", "pass"),
        ]
        assert parity9_match_tally(nodes, "B") == (1, 0, 1)

    def test_opponent_sequence_shorter_than_mine_uses_all_of_it(self):
        # 黒番で相手がまだ1手しか打っていない状態
        nodes = [
            node("B", "E5", "E5"),
            node("W", "C3", "C3"),
            node("B", "G7", "G7"),
        ]
        assert parity9_match_tally(nodes, "B") == (2, 1, 2)


class TestBudget:
    def test_behind_gives_zero(self):
        assert parity9_budget(-4.0, 3.0) == 0.0

    def test_even_gives_zero(self):
        assert parity9_budget(0.0, 3.0) == 0.0

    def test_exactly_at_margin_gives_zero(self):
        assert parity9_budget(3.0, 3.0) == 0.0

    def test_winning_gives_surplus(self):
        assert parity9_budget(8.5, 3.0) == 5.5

    def test_zero_margin_passes_lead_through(self):
        assert parity9_budget(2.0, 0.0) == 2.0


class TestIsEndgame:
    def test_before_move_threshold_is_not_endgame(self):
        # 未確定点が0でも手数が足りなければヨセではない
        assert parity9_is_endgame(20, [1.0] * 81, 30, 8) is False

    def test_missing_ownership_falls_back_to_move_count(self):
        # 測れないときは手数だけでヨセ入り（外さない側＝安全側）
        assert parity9_is_endgame(30, None, 30, 8) is True

    def test_too_many_unsettled_points_is_not_endgame(self):
        ownership = [0.0] * 12 + [1.0] * 69   # 未確定12点 > 上限8
        assert parity9_is_endgame(35, ownership, 30, 8) is False

    def test_exactly_at_unsettled_limit_is_endgame(self):
        ownership = [0.0] * 8 + [1.0] * 73
        assert parity9_is_endgame(35, ownership, 30, 8) is True

    def test_threshold_is_absolute_value(self):
        # 白地（負値）も確定として数える
        ownership = [-1.0] * 40 + [1.0] * 41
        assert parity9_is_endgame(30, ownership, 30, 0) is True

    def test_unsettled_boundary_is_strict(self):
        # |o| == PARITY9_UNSETTLED_ABS は「確定」側（< で判定するため）
        ownership = [PARITY9_UNSETTLED_ABS] * 81
        assert parity9_is_endgame(30, ownership, 30, 0) is True


class TestSelect:
    def _cands(self):
        return [
            {"gtp": "E5", "loss": 0.0, "hp": 0.30},   # 最善手
            {"gtp": "C3", "loss": 0.4, "hp": 0.25},
            {"gtp": "G7", "loss": 1.2, "hp": 0.40},
            {"gtp": "A1", "loss": 0.2, "hp": 0.001},  # humanPolicy が低すぎる
            {"gtp": "pass", "loss": 0.1, "hp": 0.90},
        ]

    def test_picks_highest_human_policy_within_cap(self):
        chosen = parity9_select(self._cands(), "E5", cap=1.5, min_hp=0.01)
        assert chosen["gtp"] == "G7"

    def test_cap_excludes_higher_loss_move(self):
        chosen = parity9_select(self._cands(), "E5", cap=0.5, min_hp=0.01)
        assert chosen["gtp"] == "C3"

    def test_best_move_is_never_selected(self):
        cands = [{"gtp": "E5", "loss": 0.0, "hp": 0.99}]
        assert parity9_select(cands, "E5", cap=1.5, min_hp=0.01) is None

    def test_pass_is_never_selected(self):
        cands = [
            {"gtp": "E5", "loss": 0.0, "hp": 0.30},
            {"gtp": "pass", "loss": 0.1, "hp": 0.90},
        ]
        assert parity9_select(cands, "E5", cap=1.5, min_hp=0.01) is None

    def test_min_human_policy_floor_blocks_all(self):
        assert parity9_select(self._cands(), "E5", cap=1.5, min_hp=0.5) is None

    def test_zero_cap_still_allows_zero_loss_alternative(self):
        cands = [
            {"gtp": "E5", "loss": 0.0, "hp": 0.30},
            {"gtp": "C3", "loss": 0.0, "hp": 0.20},
        ]
        chosen = parity9_select(cands, "E5", cap=0.0, min_hp=0.01)
        assert chosen["gtp"] == "C3"

    def test_human_policy_tie_prefers_smaller_loss(self):
        cands = [
            {"gtp": "E5", "loss": 0.0, "hp": 0.30},
            {"gtp": "C3", "loss": 1.0, "hp": 0.25},
            {"gtp": "G7", "loss": 0.3, "hp": 0.25},
        ]
        chosen = parity9_select(cands, "E5", cap=1.5, min_hp=0.01)
        assert chosen["gtp"] == "G7"

    def test_empty_candidates(self):
        assert parity9_select([], "E5", cap=1.5, min_hp=0.01) is None


class TestBuildCandidates:
    """parity9_build_candidates: Stage2 moveInfos → (candidates, best_score, n_searched)。

    finding 1: 損失の基準は best_gtp（regular analysis の最善手）であって
    Stage2 argmax ではない。min_visits 未満（1visit の楽観バイアス）は
    基準にも候補にも入れない。
    """

    @staticmethod
    def _mi(move, score_lead, visits):
        return {"move": move, "scoreLead": score_lead, "visits": visits}

    def test_visit_floor_excludes_low_visit_entries(self):
        move_infos = [
            self._mi("E5", 5.0, 200),   # best_gtp, searched
            self._mi("C3", 4.0, 150),   # searched
            self._mi("G7", 50.0, 1),    # 1visit optimistic outlier, excluded
        ]
        hp = lambda gtp: {"E5": 0.30, "C3": 0.25, "G7": 0.90}[gtp]
        candidates, best_score, n_searched = parity9_build_candidates(
            move_infos, sign=1, best_gtp="E5", hp_for_gtp=hp
        )
        assert n_searched == 2
        assert {c["gtp"] for c in candidates} == {"E5", "C3"}
        # G7 の 50.0 が基準に混入していないことも確認（混入すれば best_score=50.0）
        assert best_score == 5.0

    def test_baseline_anchors_on_best_gtp_not_stage2_argmax(self):
        # Stage2 の argmax は C3 (6.0) だが best_gtp は E5 (5.0)。
        # E5 自身の loss は基準そのものなので必ず 0.0
        move_infos = [
            self._mi("E5", 5.0, 200),
            self._mi("C3", 6.0, 200),
        ]
        hp = lambda gtp: 0.1
        candidates, best_score, n_searched = parity9_build_candidates(
            move_infos, sign=1, best_gtp="E5", hp_for_gtp=hp
        )
        by_gtp = {c["gtp"]: c for c in candidates}
        assert best_score == 5.0
        assert by_gtp["E5"]["loss"] == 0.0
        assert by_gtp["C3"]["loss"] == -1.0

    def test_best_gtp_below_visit_floor_still_anchors_baseline(self):
        # best_gtp 自身が min_visits 未満でも、regular analysis が選んだ手である
        # 以上は full move_infos から見つけて基準にする
        move_infos = [
            self._mi("E5", 5.0, 1),     # best_gtp, below floor
            self._mi("C3", 4.0, 200),   # searched
        ]
        hp = lambda gtp: 0.1
        candidates, best_score, n_searched = parity9_build_candidates(
            move_infos, sign=1, best_gtp="E5", hp_for_gtp=hp
        )
        assert best_score == 5.0
        assert n_searched == 1
        by_gtp = {c["gtp"]: c for c in candidates}
        assert by_gtp["C3"]["loss"] == 1.0

    def test_empty_searched_falls_back_to_full_move_infos(self):
        # 全部が min_visits 未満でも候補ゼロにはしない（フェイルセーフ）
        move_infos = [
            self._mi("E5", 5.0, 1),
            self._mi("C3", 4.0, 1),
        ]
        hp = lambda gtp: 0.1
        candidates, best_score, n_searched = parity9_build_candidates(
            move_infos, sign=1, best_gtp="E5", hp_for_gtp=hp
        )
        assert n_searched == 0
        assert {c["gtp"] for c in candidates} == {"E5", "C3"}
        assert best_score == 5.0

    def test_best_gtp_absent_falls_back_to_max_over_working_set(self):
        move_infos = [
            self._mi("C3", 4.0, 200),
            self._mi("G7", 6.0, 200),
        ]
        hp = lambda gtp: 0.1
        candidates, best_score, n_searched = parity9_build_candidates(
            move_infos, sign=1, best_gtp="E5", hp_for_gtp=hp
        )
        assert best_score == 6.0

    def test_candidate_scoring_better_than_best_gtp_yields_negative_loss(self):
        move_infos = [
            self._mi("E5", 5.0, 200),
            self._mi("C3", 6.0, 200),
        ]
        hp = lambda gtp: 0.1
        candidates, best_score, n_searched = parity9_build_candidates(
            move_infos, sign=1, best_gtp="E5", hp_for_gtp=hp
        )
        by_gtp = {c["gtp"]: c for c in candidates}
        assert by_gtp["C3"]["loss"] == -1.0


class TestBuildCandidatesWhiteSign:
    """sign=-1（白番）でも scoreLead（常に黒視点）から白視点の loss が正しく
    出ることを確認する。符号バグは「劣勢のときだけ外す」という設計違反を
    生むが、既存のテストは黒番（sign=1）しか撃っていなかった。
    """

    def test_white_perspective_loss_is_correct(self):
        # scoreLead は黒視点（正=黒有利）。白から見た良し悪しは符号が逆になる
        move_infos = [
            {"move": "E5", "scoreLead": -3.0, "visits": 200},  # 白+3.0 = best_gtp
            {"move": "C3", "scoreLead": -1.0, "visits": 200},  # 白+1.0 = loss 2.0
            {"move": "G7", "scoreLead": 2.0, "visits": 200},   # 白-2.0 = loss 5.0
        ]
        hp = lambda gtp: 0.1
        candidates, best_score, n_searched = parity9_build_candidates(
            move_infos, sign=-1, best_gtp="E5", hp_for_gtp=hp
        )
        by_gtp = {c["gtp"]: c for c in candidates}
        assert best_score == 3.0
        assert by_gtp["E5"]["loss"] == 0.0
        assert by_gtp["C3"]["loss"] == 2.0
        assert by_gtp["G7"]["loss"] == 5.0


class TestHumanPolicyLookupOrientation:
    """_human_policy_lookup: idx = (by - 1 - y) * bx + x の向きを検算する。

    game/engine なしで軽量インスタンスを作る（tests/test_jigo9.py と同じ
    __new__ パターン）。合成配列 array[i] == i で座標→idx の対応を直接読む。
    """

    @staticmethod
    def _lookup():
        obj = Parity9Strategy.__new__(Parity9Strategy)
        obj.game = SimpleNamespace(board_size=(9, 9))
        human_policy = list(range(82))  # 81 board points + 1 pass, array[i] == i
        return obj._human_policy_lookup(human_policy)

    def test_corner(self):
        # A1: x=0 (column A), y=0 (row 1) -> idx = (9-1-0)*9 + 0 = 72
        assert self._lookup()("A1") == 72

    def test_j_column_skips_i(self):
        # GTP columns skip "I": J is the 9th letter (index 8), not out of range.
        # J5: x=8, y=4 -> idx = (9-1-4)*9 + 8 = 44
        assert self._lookup()("J5") == 44

    def test_pass_is_last_element(self):
        assert self._lookup()("pass") == 81
