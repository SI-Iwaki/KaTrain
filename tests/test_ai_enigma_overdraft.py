# tests/test_ai_enigma_overdraft.py
"""難解の「捨て身の罠」オプション（spec 2026-09-18-enigma-overdraft-design.md）のテスト（KataGo/Kivy 不要）。"""

import pytest

from katrain.core.ai import (
    ENIGMA9_HP_BOOK,
    ENIGMA9_OVERDRAFT_CEILING_FACTOR,
    ENIGMA9_OVERDRAFT_MAX_FIND,
    ENIGMA9_OVERDRAFT_RAW_MARGIN,
    enigma9_fooled_punish,
    enigma9_overdraft_pick,
    enigma9_overdraft_probe_picks,
    enigma9_overdraft_window,
)


def hp_lookup(table):
    return lambda gtp: table.get(gtp, 0.0)


def reply(gtp, loss, visits=50):
    return {"gtp": gtp, "loss": loss, "visits": visits}


class TestConstants:
    def test_values(self):
        assert ENIGMA9_OVERDRAFT_MAX_FIND == ENIGMA9_HP_BOOK == 0.25
        assert ENIGMA9_OVERDRAFT_CEILING_FACTOR == 1.5
        assert ENIGMA9_OVERDRAFT_RAW_MARGIN == 1.5


class TestFooledPunish:
    def test_hp_weighted_mean_loss_of_inadequate_replies(self):
        replies = [reply("C3", 0.0, 300), reply("M12", 6.0), reply("Q1", 2.0, 5)]
        e_fooled, p_fooled = enigma9_fooled_punish(replies, hp_lookup({"C3": 0.1, "M12": 0.6, "Q1": 0.2}))
        assert e_fooled == pytest.approx((0.6 * 6.0 + 0.2 * 2.0) / 0.8)
        assert p_fooled == pytest.approx(0.8 / 0.9)

    def test_adequate_boundary_is_not_fooled(self):
        # 損失 0.3 目ちょうどは「十分な応手」＝引っかかった側に数えない
        replies = [reply("C3", 0.3), reply("M12", 0.31)]
        e_fooled, p_fooled = enigma9_fooled_punish(replies, hp_lookup({"C3": 0.5, "M12": 0.5}))
        assert e_fooled == pytest.approx(0.31)
        assert p_fooled == pytest.approx(0.5)

    def test_single_reply_loss_is_capped(self):
        e_fooled, _ = enigma9_fooled_punish([reply("C3", 0.0), reply("M12", 20.0)], hp_lookup({"C3": 0.2, "M12": 0.8}))
        assert e_fooled == pytest.approx(8.0)

    def test_no_inadequate_reply_or_no_hp_mass(self):
        assert enigma9_fooled_punish([reply("C3", 0.0)], hp_lookup({"C3": 0.9})) == (0.0, 0.0)
        assert enigma9_fooled_punish([reply("C3", 0.0), reply("M12", 5.0)], hp_lookup({})) == (0.0, 0.0)
        assert enigma9_fooled_punish([], hp_lookup({})) == (0.0, 0.0)


class TestOverdraftWindow:
    def test_off_when_deficit_is_zero(self):
        assert enigma9_overdraft_window(0.0, False, 0.4, 6.0, 4.0, 8.0) is None
        assert enigma9_overdraft_window(None, False, 0.4, 6.0, 4.0, 8.0) is None

    def test_requires_spending_mode_pre_yose_and_a_lead(self):
        assert enigma9_overdraft_window(2.5, False, 1.0, 6.0, 1.6, 8.0) is None  # 消費モードでない
        assert enigma9_overdraft_window(2.5, True, 0.4, 6.0, 4.0, 8.0) is None  # ヨセ
        assert enigma9_overdraft_window(2.5, False, 0.4, None, 4.0, 8.0) is None  # lead なし

    def test_over_cap_is_lead_plus_deficit(self):
        assert enigma9_overdraft_window(2.5, False, 0.4, 6.0, 4.0, 8.0) == (8.5, 12.0)

    def test_ceiling_clamps_the_window(self):
        # lead 11: cap は large(8) で頭打ち、over_cap = min(13.5, 1.5×8=12)
        assert enigma9_overdraft_window(2.5, False, 0.2, 11.0, 8.0, 8.0) == (12.0, 12.0)

    def test_window_closes_when_the_ceiling_is_not_above_the_cap(self):
        # large が小さく ceiling = max(cap, 6) = cap → 上限の外に帯が無い
        assert enigma9_overdraft_window(2.5, False, 0.2, 11.0, 8.0, 4.0) is None


def cand(gtp, loss, visits=1):
    return {"gtp": gtp, "loss": loss, "visits": visits, "wr": 0.5}


class TestOverdraftProbePicks:
    def test_band_excludes_best_pass_taken_and_out_of_range(self):
        cands = [
            cand("D4", 0.0, 900),
            cand("pass", 5.0),
            cand("K10", 3.0, 50),
            cand("G7", 5.0),
            cand("H8", 2.5),
            cand("J9", 10.0),
            cand("A1", 10.1),
        ]
        picks = enigma9_overdraft_probe_picks(cands, "D4", {"K10"}, 2.5, 10.0, 6)
        # H8 は下端ちょうど（exclusive）、J9 は上端ちょうど（inclusive）、A1 は帯の外
        assert [c["gtp"] for c in picks] == ["G7", "J9"]

    def test_trusted_candidates_are_spread_by_loss(self):
        trusted = [cand(f"T{i}", 3.0 + i, 20) for i in range(5)]
        picks = enigma9_overdraft_probe_picks([cand("D4", 0.0, 900)] + trusted, "D4", set(), 2.0, 9.0, 3)
        assert [c["gtp"] for c in picks] == ["T0", "T2", "T4"]

    def test_shallow_candidates_fill_the_rest_by_visits(self):
        cands = [cand("D4", 0.0, 900), cand("T0", 3.0, 20), cand("S1", 4.5, 3), cand("S2", 5.5, 8)]
        picks = enigma9_overdraft_probe_picks(cands, "D4", set(), 2.0, 9.0, 3)
        assert [c["gtp"] for c in picks] == ["T0", "S2", "S1"]

    def test_zero_probes_or_empty_band(self):
        assert enigma9_overdraft_probe_picks([cand("G7", 5.0)], "D4", set(), 2.0, 9.0, 0) == []
        assert enigma9_overdraft_probe_picks([cand("G7", 1.0)], "D4", set(), 2.0, 9.0, 6) == []


def over(gtp, lead_after, e, e_fooled, find=0.1, loss=None):
    return {
        "gtp": gtp,
        "lead_after": lead_after,
        "loss": (6.0 - lead_after) if loss is None else loss,
        "e": e,
        "e_fooled": e_fooled,
        "p_fooled": 0.9,
        "find": find,
        "wr_after": 0.35,
    }


def pick(entries, deficit=2.5, upper=0.0, floor=2.0, ceiling=12.0):
    return enigma9_overdraft_pick(entries, deficit, upper, floor, ceiling)


class TestOverdraftPick:
    def test_qualifier_is_returned_with_derived_fields(self):
        chosen, quals = pick([over("G7", -1.5, 5.3, 6.0)])
        assert chosen["gtp"] == "G7"
        assert chosen["fooled_lead"] == pytest.approx(4.5)
        assert chosen["u"] == pytest.approx(3.8)
        assert len(quals) == 1

    def test_deficit_boundary_is_inclusive(self):
        assert pick([over("G7", -2.5, 5.0, 6.0)])[0] is not None
        assert pick([over("G7", -2.51, 5.0, 6.0)])[0] is None

    def test_upper_bound_is_exclusive(self):
        assert pick([over("G7", 0.0, 5.0, 6.0)])[0] is None
        assert pick([over("G7", -0.01, 5.0, 6.0)])[0] is not None
        # upper = 目標差（穏やかな手も含む設定）
        assert pick([over("G7", 0.5, 5.0, 6.0)], upper=2.0)[0] is not None
        assert pick([over("G7", 2.0, 5.0, 6.0)], upper=2.0)[0] is None

    def test_findability_gate_is_inclusive(self):
        assert pick([over("G7", -1.5, 5.0, 6.0, find=0.25)])[0] is not None
        assert pick([over("G7", -1.5, 5.0, 6.0, find=0.26)])[0] is None

    def test_fooled_lead_floor_is_inclusive(self):
        assert pick([over("G7", -1.5, 3.0, 3.5)])[0] is not None  # −1.5 + 3.5 = 2.0
        assert pick([over("G7", -1.5, 3.0, 3.4)])[0] is None

    def test_ceiling_is_inclusive(self):
        assert pick([over("G7", -1.5, 5.0, 6.0, loss=12.0)])[0] is not None
        assert pick([over("G7", -1.5, 5.0, 6.0, loss=12.1)])[0] is None

    def test_ranking_is_expected_lead_then_safer(self):
        a = over("A1", -2.0, 6.0, 7.0)  # u = 4.0
        b = over("B2", -0.5, 4.0, 5.0)  # u = 3.5
        c = over("C3", -1.0, 5.0, 6.0)  # u = 4.0（a と同点・応じられた後が浅い）
        chosen, quals = pick([a, b, c])
        assert chosen["gtp"] == "C3"
        assert {q["gtp"] for q in quals} == {"A1", "B2", "C3"}

    def test_empty_and_inputs_are_not_mutated(self):
        assert pick([]) == (None, [])
        entry = over("G7", -1.5, 5.3, 6.0)
        pick([entry])
        assert "fooled_lead" not in entry and "u" not in entry


from katrain.core.ai import (
    Enigma9PlusStrategy,
    Enigma9Strategy,
    Enigma13PlusStrategy,
    Enigma13Strategy,
    Enigma19PlusStrategy,
    Enigma19Strategy,
    Mimic13Strategy,
)
from katrain.core.constants import AI_OPTION_VALUES

ALL_ENIGMA = [
    Enigma9Strategy, Enigma9PlusStrategy, Enigma13Strategy, Enigma13PlusStrategy,
    Enigma19Strategy, Enigma19PlusStrategy,
]


def _plain(key):
    return [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]


class TestOverdraftSettings:
    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_defaults_are_off_negative_only_two_points_six_probes(self, cls):
        d = cls.SETTING_DEFAULTS
        assert d["overdraft_deficit"] == 0
        assert d["overdraft_answered_max"] == 0
        assert d["overdraft_min_fooled_lead"] == 2.0
        assert d["overdraft_probes"] == 6

    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_gui_options(self, cls):
        p = cls.KEY_PREFIX
        deficit = _plain(f"{p}_overdraft_deficit")
        assert deficit[0] == 0 and 2.5 in deficit
        assert AI_OPTION_VALUES[f"{p}_overdraft_deficit"][0] == (0.0, "OFF")
        assert _plain(f"{p}_overdraft_answered_max") == [-1.0, 0.0, 99.0]
        assert _plain(f"{p}_overdraft_min_fooled_lead") == [1.0, 2.0, 3.0, 5.0, 8.0]
        assert _plain(f"{p}_overdraft_probes") == [4, 6, 8, 12]

    def test_mimic13_is_untouched(self):
        assert not any(k.startswith("overdraft") for k in Mimic13Strategy.SETTING_DEFAULTS)
