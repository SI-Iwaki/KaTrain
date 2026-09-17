# tests/test_ai_enigma_gamble.py
"""難解の「序盤の賭け罠」オプション（spec 2026-09-17-enigma-gamble-design.md）のテスト（KataGo/Kivy 不要）。"""

import pytest

from katrain.core.ai import (
    ENIGMA9_GAMBLE_COST_WEIGHT,
    ENIGMA9_GAMBLE_MAX_FIND,
    ENIGMA9_GAMBLE_PROBE_EXTRA,
    ENIGMA9_HP_BOOK,
    Enigma9PlusStrategy,
    Enigma9Strategy,
    Enigma13PlusStrategy,
    Enigma13Strategy,
    Enigma19PlusStrategy,
    Enigma19Strategy,
    Mimic13Strategy,
    enigma9_gamble_pick,
    enigma9_gamble_window,
)
from katrain.core.constants import AI_OPTION_VALUES

ALL_ENIGMA = [
    Enigma9Strategy,
    Enigma9PlusStrategy,
    Enigma13Strategy,
    Enigma13PlusStrategy,
    Enigma19Strategy,
    Enigma19PlusStrategy,
]


def entry(gtp, e, loss, wr, find=0.05):
    return {"gtp": gtp, "e": e, "loss": loss, "wr_after": wr, "find": find, "net": 0.0}


BEST = entry("D4", 0.10, 0.0, 0.52, find=0.9)


class TestGambleWindow:
    def test_zero_is_off(self):
        assert enigma9_gamble_window(0, 0) is False
        assert enigma9_gamble_window(10, None) is False

    def test_active_below_the_slider_only(self):
        assert enigma9_gamble_window(34, 35) is True
        assert enigma9_gamble_window(35, 35) is False

    def test_float_slider_value_is_coerced(self):
        assert enigma9_gamble_window(34, 35.0) is True


class TestGamblePick:
    def test_constants(self):
        assert ENIGMA9_GAMBLE_MAX_FIND == ENIGMA9_HP_BOOK
        assert ENIGMA9_GAMBLE_COST_WEIGHT == 0.5
        assert ENIGMA9_GAMBLE_PROBE_EXTRA == 4

    def test_picks_a_real_trap_inside_the_floor(self):
        trap = entry("G7", 0.90, 1.0, 0.36)
        pick, quals = enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5)
        assert pick["gtp"] == "G7"
        assert [c["gtp"] for c in quals] == ["G7"]
        assert pick["d_e"] == pytest.approx(0.80)
        assert pick["u"] == pytest.approx(0.80 - 0.5 * 1.0)

    def test_winrate_floor_blocks(self):
        trap = entry("G7", 0.90, 1.0, 0.34)
        assert enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5) == (None, [])

    def test_missing_winrate_blocks(self):
        trap = entry("G7", 0.90, 1.0, None)
        assert enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5) == (None, [])

    def test_small_delta_e_blocks(self):
        trap = entry("G7", 0.55, 1.0, 0.40)  # dE 0.45 < 0.5
        assert enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5) == (None, [])

    def test_findable_reply_blocks(self):
        trap = entry("G7", 0.90, 1.0, 0.40, find=0.30)
        assert enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5) == (None, [])

    def test_boundaries_are_inclusive(self):
        trap = entry("G7", 0.60, 1.0, 0.35, find=0.25)  # dE 0.5 / wr 0.35 / find 0.25 ちょうど
        pick, _ = enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5)
        assert pick["gtp"] == "G7"

    def test_clearly_bigger_trap_wins_despite_its_price(self):
        cheap = entry("C7", 0.67, 0.39, 0.49)  # dE 0.57 -> u 0.375
        big = entry("H3", 1.12, 1.18, 0.40)  # dE 1.02 -> u 0.43
        pick, quals = enigma9_gamble_pick([BEST, cheap, big], "D4", 0.35, 0.5)
        assert pick["gtp"] == "H3"
        assert len(quals) == 2

    def test_marginally_bigger_trap_loses_to_the_cheaper_one(self):
        cheap = entry("L6", 0.66, 0.74, 0.45)  # dE 0.56 -> u 0.19
        pricey = entry("K7", 0.74, 1.23, 0.40)  # dE 0.64 -> u 0.025
        pick, _ = enigma9_gamble_pick([BEST, cheap, pricey], "D4", 0.35, 0.5)
        assert pick["gtp"] == "L6"

    def test_negative_vloss_is_not_a_bonus(self):
        a = entry("A1", 0.70, -0.40, 0.55)
        b = entry("B1", 0.75, 0.00, 0.52)
        pick, _ = enigma9_gamble_pick([BEST, a, b], "D4", 0.35, 0.5)
        assert pick["gtp"] == "B1"  # u は dE だけで決まる（-0.40 は 0 扱い）

    def test_missing_best_entry_fails_safe(self):
        trap = entry("G7", 0.90, 1.0, 0.40)
        assert enigma9_gamble_pick([trap], "D4", 0.35, 0.5) == (None, [])

    def test_input_entries_are_not_mutated(self):
        trap = entry("G7", 0.90, 1.0, 0.40)
        enigma9_gamble_pick([BEST, trap], "D4", 0.35, 0.5)
        assert "u" not in trap and "d_e" not in trap


class TestGambleSettings:
    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_defaults_are_off_with_35_percent_floor(self, cls):
        assert cls.SETTING_DEFAULTS["gamble_until_move"] == 0
        assert cls.SETTING_DEFAULTS["gamble_min_winrate"] == 0.35
        assert cls.SETTING_DEFAULTS["gamble_min_delta_e"] == 0.5

    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_off_value_and_recommended_window_are_gui_options(self, cls):
        key = f"{cls.KEY_PREFIX}_gamble_until_move"
        values = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]
        assert values[0] == 0
        recommended = {9: 16, 13: 35, 19: 75}[cls.BOARD_LEN]
        assert recommended in values

    def test_mimic13_is_untouched(self):
        assert not any(k.startswith("gamble") for k in Mimic13Strategy.SETTING_DEFAULTS)
