# tests/test_ai_parity9.py
"""9路専用「一致率追随」戦略 ai:parity9 の純関数テスト（KataGo/Kivy 不要）。"""
from types import SimpleNamespace

from katrain.core.ai import (
    PARITY9_UNSETTLED_ABS,
    Parity9Strategy,
    parity9_has_admissible,
    parity9_build_candidates,
    parity9_is_endgame,
    parity9_match_tally,
    parity9_rate_gate,
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


class TestHasAdmissible:
    """parity9_has_admissible: Stage1（humanSL）を撃つ前の足切り。

    かつてここにあったスコア予算 `max(0, lead - keep_margin)` は撤去した。
    `scoreLead` は komi 込みなので「lead > 0」は「勝率 > 50%」と同義で、
    **9路 komi 7 の黒は開始時点で lead が負**（実測 2026-08-08 実戦:
    黒番 depth 0〜8 で -0.22〜-0.04）。予算 0 で早期 return するため序盤5手が
    問答無用で固定され、勝率フロアが一度も評価されないまま「no budget」と
    ログに出ていた（白番は lead +0.99 で通る＝黒白で非対称）。安全判定は
    着手後の勝率フロアただ1つに統一した。
    """

    @staticmethod
    def _c(gtp, loss, wr):
        return {"gtp": gtp, "loss": loss, "wr": wr, "visits": 100}

    def test_true_when_a_safe_cheap_move_exists(self):
        cands = [self._c("E5", 0.0, 0.9), self._c("C3", 0.3, 0.85)]
        assert parity9_has_admissible(cands, "E5", cap=3.0, min_winrate=0.7) is True

    def test_false_when_only_unsafe_moves_exist(self):
        cands = [self._c("E5", 0.0, 0.9), self._c("C3", 0.3, 0.52)]
        assert parity9_has_admissible(cands, "E5", cap=3.0, min_winrate=0.7) is False

    def test_false_when_only_expensive_moves_exist(self):
        cands = [self._c("E5", 0.0, 0.9), self._c("C3", 9.0, 0.9)]
        assert parity9_has_admissible(cands, "E5", cap=3.0, min_winrate=0.7) is False

    def test_false_when_best_move_is_the_only_candidate(self):
        assert parity9_has_admissible([self._c("E5", 0.0, 0.9)], "E5", 3.0, 0.7) is False

    def test_pass_is_never_admissible(self):
        cands = [self._c("E5", 0.0, 0.9), self._c("pass", 0.1, 0.9)]
        assert parity9_has_admissible(cands, "E5", cap=3.0, min_winrate=0.7) is False

    def test_negative_lead_does_not_block(self):
        # 黒番の 9路序盤（lead 負・勝率 ~48%）でも、勝率フロアを満たす候補が
        # あれば通る。判定は lead を一切見ない
        cands = [self._c("E5", 0.0, 0.48), self._c("C3", 0.3, 0.47)]
        assert parity9_has_admissible(cands, "E5", cap=3.0, min_winrate=0.4) is True

    def test_missing_winrate_does_not_block(self):
        cands = [{"gtp": "E5", "loss": 0.0, "wr": None},
                 {"gtp": "C3", "loss": 0.3, "wr": None}]
        assert parity9_has_admissible(cands, "E5", cap=3.0, min_winrate=0.9) is True

    def test_never_rejects_what_select_would_accept(self):
        # 足切りは安全側であること: select が採る候補は必ず admissible
        cands = [
            {"gtp": "E5", "loss": 0.0, "hp": 0.3, "wr": 0.9},
            {"gtp": "C3", "loss": 0.3, "hp": 0.2, "wr": 0.85},
        ]
        chosen = parity9_select(cands, "E5", cap=3.0, min_hp=0.01, min_winrate=0.7)
        assert chosen is not None
        assert parity9_has_admissible(cands, "E5", cap=3.0, min_winrate=0.7) is True


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


class TestSelectCostSlack:
    """cost_slack: 最安バンド内で humanPolicy 最大＝コストが第1基準。

    「予算内で humanPolicy 最大」だけだと毎回予算を使い切る（実測: 上限5.0で
    12手外して 21.2目）。ユーザー要件は「最善手の次にいいスコアの手」なので、
    安さが主・人間らしさがバンド内のタイブレークになる。
    """

    @staticmethod
    def _c(gtp, loss, hp):
        return {"gtp": gtp, "loss": loss, "hp": hp, "wr": 0.9}

    def test_expensive_high_hp_move_is_not_taken(self):
        cands = [
            self._c("E5", 0.0, 0.20),   # best
            self._c("C3", 0.30, 0.12),  # 最安
            self._c("G7", 3.90, 0.31),  # hp 最大だが高い
        ]
        chosen = parity9_select(cands, "E5", cap=5.0, min_hp=0.01, cost_slack=0.5)
        assert chosen["gtp"] == "C3"

    def test_within_slack_the_more_human_move_wins(self):
        cands = [
            self._c("E5", 0.0, 0.20),
            self._c("C3", 0.30, 0.12),
            self._c("G7", 0.70, 0.55),  # +0.40 だけ高いが十分人間らしい
        ]
        chosen = parity9_select(cands, "E5", cap=5.0, min_hp=0.01, cost_slack=0.5)
        assert chosen["gtp"] == "G7"

    def test_slack_zero_is_pure_cheapest(self):
        cands = [
            self._c("E5", 0.0, 0.20),
            self._c("C3", 0.30, 0.12),
            self._c("G7", 0.31, 0.90),
        ]
        chosen = parity9_select(cands, "E5", cap=5.0, min_hp=0.01, cost_slack=0.0)
        assert chosen["gtp"] == "C3"

    def test_default_is_legacy_max_hp(self):
        # 既定引数 inf は旧挙動（予算内で humanPolicy 最大）
        cands = [
            self._c("E5", 0.0, 0.20),
            self._c("C3", 0.30, 0.12),
            self._c("G7", 3.90, 0.31),
        ]
        chosen = parity9_select(cands, "E5", cap=5.0, min_hp=0.01)
        assert chosen["gtp"] == "G7"

    def test_band_is_measured_from_cheapest_admissible_not_from_zero(self):
        # 最安が 2.0 なら 2.0〜2.5 がバンド。0〜0.5 ではない
        cands = [
            self._c("E5", 0.0, 0.20),
            self._c("C3", 2.00, 0.10),
            self._c("G7", 2.40, 0.60),
            self._c("B2", 4.00, 0.99),
        ]
        chosen = parity9_select(cands, "E5", cap=5.0, min_hp=0.01, cost_slack=0.5)
        assert chosen["gtp"] == "G7"


class TestSelectWinrateFloor:
    """min_winrate: 「次の一手で逆転されない」を着手後勝率で判定する。

    候補の winrate は KataGo の探索値なので相手の最善応手込み＝「打った後で
    最善で返されてもまだこの勝率」。スコア予算（lead - keep_margin）は互角
    局面で必ず 0 になり序盤を構造的に外せないので、そちらの代わりを務める。
    """

    def test_low_winrate_candidate_is_rejected(self):
        cands = [
            {"gtp": "E5", "loss": 0.0, "hp": 0.30, "wr": 0.90},
            {"gtp": "C3", "loss": 0.2, "hp": 0.60, "wr": 0.55},  # hp 最大だが勝率不足
        ]
        assert parity9_select(cands, "E5", cap=3.0, min_hp=0.01, min_winrate=0.7) is None

    def test_candidate_above_floor_is_taken(self):
        cands = [
            {"gtp": "E5", "loss": 0.0, "hp": 0.30, "wr": 0.90},
            {"gtp": "C3", "loss": 0.2, "hp": 0.60, "wr": 0.82},
        ]
        chosen = parity9_select(cands, "E5", cap=3.0, min_hp=0.01, min_winrate=0.7)
        assert chosen["gtp"] == "C3"

    def test_missing_winrate_does_not_block(self):
        # 勝率が取れない経路ではこの条件を課さない（フェイルセーフ = 従来動作）
        cands = [
            {"gtp": "E5", "loss": 0.0, "hp": 0.30, "wr": None},
            {"gtp": "C3", "loss": 0.2, "hp": 0.60, "wr": None},
        ]
        chosen = parity9_select(cands, "E5", cap=3.0, min_hp=0.01, min_winrate=0.9)
        assert chosen["gtp"] == "C3"

    def test_default_floor_is_inert(self):
        # 既定引数 0.0 なら旧来の呼び出し（wr キー無し）でも壊れない
        cands = [{"gtp": "C3", "loss": 0.2, "hp": 0.60}]
        assert parity9_select(cands, "E5", cap=3.0, min_hp=0.01)["gtp"] == "C3"


class TestRateGate:
    """parity9_rate_gate: 絶対レート目標（相手が上回ればそこまで緩む）。

    旧・一致数差ゲート（mine - opp >= margin）の置き換え。旧ゲートは 0-0 で
    必ず閉じるため白の初手を落としており、実測ではそこが最も外し賃の安い
    局面だった。また相手が一度も最善手に一致しない対局では追随目標が
    原理的に達成不能だった。
    """

    def test_first_move_opens_gate(self):
        # counted=0 でも (0+1)/(0+1)=1.0 > 0.4 なので開く（旧ゲートは必ず閉じた）
        open_, eff, mine_r, opp_r = parity9_rate_gate(0, 0, 0, 0.4)
        assert open_ is True
        assert eff == 0.4
        assert (mine_r, opp_r) == (0.0, 0.0)

    def test_closed_when_running_rate_has_slack(self):
        # mine=1/5=20%。この手も一致させて 2/6=33% でも 40% を超えない → 外さない
        open_, _, _, _ = parity9_rate_gate(1, 0, 5, 0.4)
        assert open_ is False

    def test_open_when_matching_would_exceed_target(self):
        # mine=2/5=40%。この手も一致させると 3/6=50% > 40% → 外す
        open_, _, _, _ = parity9_rate_gate(2, 0, 5, 0.4)
        assert open_ is True

    def test_strong_opponent_does_not_raise_effective_target(self):
        # 相手が 8/10=80% 一致していても目標は 40% のまま。相手のレートで
        # 目標を引き上げるのは誤り（ユーザー要件の条件は「勝てない場合」で
        # あって「相手の一致率が高い場合」ではなく、「勝てない」は安全ゲートが
        # 処理する）。実測の実害: 相手が 43〜54% 一致してくる接戦で 30判断中
        # 5回、安全性と無関係にゲートを閉じていた
        open_, eff, _, opp_r = parity9_rate_gate(7, 8, 10, 0.4)
        assert eff == 0.4
        assert opp_r == 0.8      # opp はログ用に返るが判定には使わない
        assert open_ is True     # 8/11 = 72.7% > 40% なので外す

    def test_weak_opponent_does_not_lower_target(self):
        # 相手が 0% でも目標は絶対値 40% まで。0% まで下げにはいかない
        open_, eff, _, _ = parity9_rate_gate(1, 0, 5, 0.4)
        assert eff == 0.4
        assert open_ is False

    def test_opp_never_affects_the_decision(self):
        # 同じ (mine, counted) なら opp が何であれ判定は同一
        base = parity9_rate_gate(2, 0, 5, 0.4)
        for opp in (1, 3, 5):
            assert parity9_rate_gate(2, opp, 5, 0.4)[:2] == base[:2]

    def test_target_zero_always_opens(self):
        # 目標 0% は「常に外す」。安全側のゲート（予算・hp・ヨセ）だけが残る
        assert parity9_rate_gate(0, 0, 10, 0.0)[0] is True

    def test_converges_to_target(self):
        # 貪欲に回すとレートが目標へ収束することを確認する
        mine = counted = 0
        for _ in range(60):
            open_, _, _, _ = parity9_rate_gate(mine, 0, counted, 0.4)
            if not open_:
                mine += 1
            counted += 1
        assert 0.35 <= mine / counted <= 0.45


class TestBuildCandidates:
    """parity9_build_candidates: 通常解析 candidate_moves → (candidates, n_searched)。

    プールの出所が Stage2 の moveInfos から `GameNode.candidate_moves` に変わった。
    Stage2 は wideRootNoise=0 で探索が1点に集中し、9路では非最善候補が visit floor
    を越えられなかった（実測: 候補28手中 visits>=10 が最善手1手だけ）。通常解析は
    wideRootNoise=0.04 で候補が広がり、しかも損失が `relativePointsLost`
    （**打つ側視点に符号済み**の最善手基準）としてそのまま入っている。
    """

    @staticmethod
    def _cm(move, rel_points_lost, visits, order=0):
        """GameNode.candidate_moves が返す dict の必要フィールドだけの模造。"""
        return {
            "move": move,
            "relativePointsLost": rel_points_lost,
            "pointsLost": rel_points_lost,
            "visits": visits,
            "order": order,
        }

    def test_visit_floor_excludes_low_visit_entries(self):
        cands = [
            self._cm("E5", 0.0, 200, order=0),   # best move, searched
            self._cm("C3", 1.0, 150, order=1),   # searched
            self._cm("G7", -40.0, 1, order=2),   # 1visit optimistic outlier, excluded
        ]
        hp = lambda gtp: {"E5": 0.30, "C3": 0.25, "G7": 0.90}[gtp]
        candidates, n_searched = parity9_build_candidates(cands)
        assert n_searched == 2
        assert {c["gtp"] for c in candidates} == {"E5", "C3"}

    def test_loss_is_taken_verbatim_from_relative_points_lost(self):
        # relativePointsLost は GameNode 側で既に「最善手基準・打つ側視点」に
        # なっている。ここで符号を掛け直したり基準を付け替えたりしない
        cands = [
            self._cm("E5", 0.0, 200, order=0),
            self._cm("C3", 1.4, 120, order=1),
        ]
        hp = lambda gtp: 0.1
        candidates, _ = parity9_build_candidates(cands)
        by_gtp = {c["gtp"]: c for c in candidates}
        assert by_gtp["E5"]["loss"] == 0.0
        assert by_gtp["C3"]["loss"] == 1.4

    def test_white_perspective_needs_no_sign_flip(self):
        # 白番でも relativePointsLost は白視点で正=損。sign を掛けると符号が
        # 反転し「劣勢のときだけ外す」という設計違反になる（旧実装の落とし穴）
        cands = [
            self._cm("E5", 0.0, 200, order=0),
            self._cm("C3", 2.0, 200, order=1),
            self._cm("G7", 5.0, 200, order=2),
        ]
        hp = lambda gtp: 0.1
        candidates, _ = parity9_build_candidates(cands)
        by_gtp = {c["gtp"]: c for c in candidates}
        assert by_gtp["C3"]["loss"] == 2.0
        assert by_gtp["G7"]["loss"] == 5.0

    def test_empty_searched_falls_back_to_full_list(self):
        # 全部が min_visits 未満でも候補ゼロにはしない（フェイルセーフ）
        cands = [
            self._cm("E5", 0.0, 1, order=0),
            self._cm("C3", 1.0, 1, order=1),
        ]
        hp = lambda gtp: 0.1
        candidates, n_searched = parity9_build_candidates(cands)
        assert n_searched == 0
        assert {c["gtp"] for c in candidates} == {"E5", "C3"}

    def test_policy_fallback_dict_without_relative_points_lost(self):
        # analysis["moves"] が空のとき candidate_moves は pointsLost だけを持つ
        # 単一エントリを返す（relativePointsLost が無い）
        cands = [{"move": "E5", "pointsLost": 0, "order": 0}]
        candidates, n_searched = parity9_build_candidates(cands)
        assert n_searched == 0  # visits キー自体が無い = floor 未満扱い
        # hp はここでは載らない（Stage1 を撃ってから呼び出し側が載せる）
        assert candidates == [{"gtp": "E5", "loss": 0, "visits": 0, "wr": None}]

    def test_visits_are_carried_through(self):
        cands = [self._cm("E5", 0.0, 640, order=0), self._cm("C3", 0.8, 95, order=1)]
        hp = lambda gtp: 0.1
        candidates, _ = parity9_build_candidates(cands)
        assert {c["gtp"]: c["visits"] for c in candidates} == {"E5": 640, "C3": 95}


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
