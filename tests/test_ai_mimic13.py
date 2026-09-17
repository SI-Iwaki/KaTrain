# tests/test_ai_mimic13.py
"""「擬態（13路）」ai:mimic13 の純関数・登録整合・_generate_move 通しテスト（KataGo/Kivy 不要）。

設計: docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md
"""

import types

import pytest

from katrain.core.ai import (
    MIMIC_BEHIND_LIMIT,
    MIMIC_TRAP_MIN_HP,
    Enigma9Strategy,
    mimic_choose,
    mimic_hp_top,
    mimic_natural_floor,
    mimic_price_cap,
    mimic_qualifies,
    mimic_shortlist,
    mimic_yose_delegates,
)


def _node(**kw):
    base = dict(next_player="B", player="W", depth=30, move=None, analysis_complete=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


class TestTerminalBandExtraction:
    """基底の終局帯ブロックはメソッドに抽出されている（擬態13路と共有するため）。"""

    def test_returns_none_outside_the_terminal_band(self):
        katrain_ns = types.SimpleNamespace(log=lambda *a, **k: None)
        cands = [
            {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.6},
            {"move": "pass", "pointsLost": 30.0, "relativePointsLost": 30.0, "visits": 5, "winrate": 0.1},
        ]
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=_node(candidate_moves=cands), board_size=(9, 9))
        s = Enigma9Strategy(game, {})
        assert s._terminal_band_move(cands, "B") is None

    def test_opponent_pass_with_cheap_pass_returns_a_pass(self):
        from katrain.core.sgf_parser import Move

        katrain_ns = types.SimpleNamespace(log=lambda *a, **k: None)
        cands = [
            {"move": "E5", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.6},
            {"move": "pass", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 50, "winrate": 0.6},
        ]
        node = _node(candidate_moves=cands, move=Move(None, player="W"))
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(9, 9))
        s = Enigma9Strategy(game, {})
        move, reason = s._terminal_band_move(cands, "B")
        assert move.is_pass


def cand(gtp, loss, visits=100, wr=0.5):
    return {"gtp": gtp, "loss": loss, "visits": visits, "wr": wr}


def scored(gtp, price, hp, kind="natural"):
    return {"gtp": gtp, "price": price, "own_hp": hp, "kind": kind}


class TestPriceCap:
    """λ = 不一致1回に払ってよい price の上限（リード連動）。"""

    def test_none_when_lead_unknown(self):
        assert mimic_price_cap(None, 3.0, 0.25, 0.3, 2.0) is None

    def test_behind_pays_nothing(self):
        assert mimic_price_cap(MIMIC_BEHIND_LIMIT - 0.01, 3.0, 0.25, 0.3, 2.0) == 0.0

    def test_no_surplus_pays_only_free_loss(self):
        assert mimic_price_cap(-1.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(0.3)  # 境界は free 側
        assert mimic_price_cap(0.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(0.3)
        assert mimic_price_cap(3.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(0.3)

    def test_surplus_is_spent_at_the_spend_rate(self):
        assert mimic_price_cap(7.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(1.0)  # 余剰 4 目 × 0.25
        assert mimic_price_cap(3.4, 3.0, 0.25, 0.3, 2.0) == pytest.approx(0.3)  # 余剰が薄い間は free が床

    def test_capped_by_max_loss(self):
        assert mimic_price_cap(40.0, 3.0, 0.25, 0.3, 2.0) == pytest.approx(2.0)
        assert mimic_price_cap(0.0, 3.0, 0.25, 0.5, 0.2) == pytest.approx(0.2)  # max_loss < free_loss でも超えない

    def test_is_continuous_and_monotonic_in_lead(self):
        leads = [x / 10.0 for x in range(-10, 200)]
        caps = [mimic_price_cap(l, 3.0, 0.25, 0.3, 2.0) for l in leads]
        assert all(b >= a for a, b in zip(caps, caps[1:]))
        assert max(b - a for a, b in zip(caps, caps[1:])) <= 0.025 + 1e-9  # 0.1 目刻みで段差なし


class TestNaturalFloor:
    def test_hp_top_ignores_pass_and_illegal_points(self):
        policy = [0.1, -1.0, 0.4, 0.2] + [0.0] * 165 + [0.9]  # 13路: 169 点 + pass
        assert mimic_hp_top(policy, (13, 13)) == pytest.approx(0.4)

    def test_hp_top_of_empty_or_illegal_board_is_zero(self):
        assert mimic_hp_top([-1.0] * 169 + [1.0], (13, 13)) == 0.0

    def test_floor_is_the_larger_of_absolute_and_relative(self):
        assert mimic_natural_floor(0.9, 0.05, 0.2) == pytest.approx(0.18)  # 第一感が強い局面は相対側
        assert mimic_natural_floor(0.1, 0.05, 0.2) == pytest.approx(0.05)  # 分散した局面は絶対側


class TestQualifies:
    def test_natural_by_human_policy(self):
        assert mimic_qualifies(0.10, 0.0, 0.05, 0.5) == "natural"

    def test_trap_is_exempt_from_naturalness_but_not_from_the_hard_floor(self):
        assert mimic_qualifies(0.01, 0.8, 0.05, 0.5) == "trap"
        assert mimic_qualifies(MIMIC_TRAP_MIN_HP / 2, 3.0, 0.05, 0.5) is None  # 人間が絶対打たない手は罠でも不可

    def test_neither(self):
        assert mimic_qualifies(0.01, 0.4, 0.05, 0.5) is None

    def test_trap_off_sentinel(self):
        assert mimic_qualifies(0.01, 5.0, 0.05, 99.0) is None


class TestShortlist:
    def test_naturals_first_by_hp_then_cheapest_then_spread(self):
        hp = {"A1": 0.30, "B2": 0.20, "C3": 0.01, "D4": 0.01, "E5": 0.01, "F6": 0.01, "G7": 0.01}
        pool = [
            cand("C3", 0.1),
            cand("A1", 1.5),
            cand("D4", 0.2),
            cand("B2", 0.9),
            cand("E5", 0.6),
            cand("F6", 1.2),
            cand("G7", 1.9),
        ]
        out = mimic_shortlist(pool, lambda g: hp[g], 0.05, k_natural=2, k_cheap=2, extra=2)
        gtps = [c["gtp"] for c in out]
        assert gtps[:2] == ["A1", "B2"]  # 自然な候補は hp 降順（高くても拾う）
        assert gtps[2:4] == ["C3", "D4"]  # 残りから安い順
        assert set(gtps[4:]) == {"E5", "G7"}  # 残りの loss 範囲を端まで等間隔
        assert len(gtps) == len(set(gtps))

    def test_no_naturals_falls_back_to_cheapest(self):
        pool = [cand("A1", 0.4), cand("B2", 0.1)]
        out = mimic_shortlist(pool, lambda g: 0.0, 0.05, k_natural=4, k_cheap=4, extra=0)
        assert [c["gtp"] for c in out] == ["B2", "A1"]


class TestChoose:
    def test_none_when_nothing_is_affordable(self):
        assert mimic_choose([scored("A1", 0.5, 0.3)], "E5", 0.3, 0.3) is None

    def test_unqualified_and_best_are_never_chosen(self):
        rows = [scored("E5", 0.0, 0.9), scored("A1", 0.1, 0.3, kind=None)]
        assert mimic_choose(rows, "E5", 1.0, 0.3) is None

    def test_cheapest_price_wins_outside_the_band(self):
        rows = [scored("A1", 0.9, 0.5), scored("B2", 0.1, 0.06)]
        assert mimic_choose(rows, "E5", 1.0, 0.3)["gtp"] == "B2"

    def test_band_prefers_the_most_human_move(self):
        rows = [scored("A1", 0.30, 0.5), scored("B2", 0.10, 0.06)]
        assert mimic_choose(rows, "E5", 1.0, 0.3)["gtp"] == "A1"

    def test_profitable_trap_is_affordable_with_zero_lambda(self):
        rows = [scored("T1", -0.7, 0.01, kind="trap"), scored("A1", 0.2, 0.4)]
        assert mimic_choose(rows, "E5", 0.0, 0.3)["gtp"] == "T1"

    def test_band_never_admits_a_price_above_lambda(self):
        rows = [scored("A1", 0.25, 0.1), scored("B2", 0.45, 0.9)]
        assert mimic_choose(rows, "E5", 0.3, 0.3)["gtp"] == "A1"


class TestYoseDelegates:
    def test_delegates_only_with_the_reserve_in_hand(self):
        assert mimic_yose_delegates(3.0, 3.0) is True
        assert mimic_yose_delegates(2.99, 3.0) is False
        assert mimic_yose_delegates(None, 3.0) is False
