# tests/test_ai_enigma_gamble.py
"""難解の「序盤の賭け罠」オプション（spec 2026-09-17-enigma-gamble-design.md）のテスト（KataGo/Kivy 不要）。"""

import types

import pytest

from katrain.core.ai import (
    ENIGMA9_GAMBLE_COST_WEIGHT,
    ENIGMA9_GAMBLE_MAX_FIND,
    ENIGMA9_GAMBLE_PROBE_EXTRA,
    ENIGMA9_HP_BOOK,
    ENIGMA9_SHORTLIST,
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
from katrain.core.sgf_parser import Move

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


def _hp(size, values):
    """humanPolicy のフラット配列（size×size＋pass）。values は {gtp: hp}。"""
    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def _child(lead_after, wr_after, replies, reply_hp, size=13):
    """黒番が打った後の子局面プローブ（clean + hp）。replies は [(gtp, 白視点の損失, visits)]。

    KataGo の scoreLead / winrate は常に黒視点。白の最善応手後の黒リードが lead_after、
    白が loss 目損する応手の後は lead_after + loss。
    """
    move_infos = [
        {"move": g, "scoreLead": lead_after + loss, "visits": v, "order": i}
        for i, (g, loss, v) in enumerate(replies)
    ]
    return {
        "clean": {"rootInfo": {"scoreLead": lead_after, "winrate": wr_after}, "moveInfos": move_infos},
        "hp": {"humanPolicy": _hp(size, reply_hp)},
    }


def _gamble_strategy(cls, prefix, settings=None, *, depth=10, root_lead=0.2, extra_cands=0):
    """互角の13路・黒番。D4=最善 / K10=安い外し（珍しいだけ）/ G7=1.2 目払う本物の罠。"""
    logs = []
    katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
    cands = [
        {"move": "D4", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.52},
        {"move": "K10", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 60, "winrate": 0.50},
        {"move": "G7", "pointsLost": 1.2, "relativePointsLost": 1.2, "visits": 30, "winrate": 0.37},
    ]
    for i in range(extra_cands):  # 安い順 7 手の枠を埋める雑魚候補（G7 を shortlist の外へ押し出す）
        loss = 0.2 + i * 0.01
        cands.insert(
            2, {"move": f"A{i + 1}", "pointsLost": loss, "relativePointsLost": loss, "visits": 40, "winrate": 0.49}
        )
    node = types.SimpleNamespace(
        next_player="B",
        player="W",
        depth=depth,
        move=None,
        analysis_complete=True,
        analysis={"root": {"scoreLead": root_lead}},
        candidate_moves=cands,
    )
    game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(13, 13))
    base = {f"{prefix}_opening_humanstyle_moves": 0, f"{prefix}_max_loss": 1.6, f"{prefix}_locality_stddev": 0.0}
    s = cls(game, {**base, **(settings or {})})
    s.probed = []

    def probe(gtps, player, parent_hp=False):
        s.probed.append(list(gtps))
        table = {
            # 最善手: 応手は自明（E≈0）
            "D4": _child(0.2, 0.52, [("C3", 0.0, 300), ("N1", 0.4, 20)], {"C3": 0.9, "N1": 0.05}),
            # 安い外し: 罠は無いが自手が珍しい（own_hp 0）＝従来の net 比較はこれを選ぶ
            "K10": _child(0.1, 0.50, [("C3", 0.0, 300), ("N1", 0.4, 20)], {"C3": 0.9, "N1": 0.05}),
            # 本物の罠: 正しい応手 C3 は hp 20%、自然な M12（hp 70%）は 0.9 目損＝E 0.70。1.2 目払い、
            # 正しく応じられたら勝率 36%。net は 0.70 + 0.2 − 1.2 < 最善手＝従来の比較では選ばれない
            "G7": _child(-1.0, 0.36, [("C3", 0.0, 300), ("M12", 0.9, 40)], {"C3": 0.20, "M12": 0.70}),
        }
        for g in gtps:
            table.setdefault(g, _child(0.0, 0.49, [("C3", 0.0, 300)], {"C3": 0.9}))
        parent = {"humanPolicy": _hp(13, {"D4": 0.6, "G7": 0.25})} if parent_hp else None
        return {g: table[g] for g in gtps}, parent

    s._probe_children = probe
    s._run_query = lambda label, **kw: None
    return s, logs


class TestGambleEndToEnd:
    """_generate_move への接続（純関数だけだと「呼び出し側が繋がっていない」を取り逃す）。"""

    def test_off_plays_the_classic_net_choice(self):
        s, logs = _gamble_strategy(Enigma13Strategy, "enigma13")
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert not any("Gamble" in m for m in logs)

    def test_on_plays_the_trap_that_loses_the_net_race(self):
        s, logs = _gamble_strategy(Enigma13Strategy, "enigma13", {"enigma13_gamble_until_move": 35})
        move, thoughts = s.generate_move()
        assert move.gtp() == "G7"
        assert "gamble trap G7" in thoughts
        assert any("Gamble: played G7" in m for m in logs)

    def test_outside_the_window_nothing_changes(self):
        s, logs = _gamble_strategy(Enigma13Strategy, "enigma13", {"enigma13_gamble_until_move": 35}, depth=35)
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert not any("Gamble" in m for m in logs)

    def test_winrate_floor_setting_blocks_the_trap(self):
        s, logs = _gamble_strategy(
            Enigma13Strategy,
            "enigma13",
            {"enigma13_gamble_until_move": 35, "enigma13_gamble_min_winrate": 0.4},
        )
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert any("Gamble: window" in m and "qualifiers=[]" in m for m in logs)

    def test_delta_e_setting_blocks_the_trap(self):
        s, _ = _gamble_strategy(
            Enigma13Strategy,
            "enigma13",
            {"enigma13_gamble_until_move": 35, "enigma13_gamble_min_delta_e": 1.5},
        )
        assert s.generate_move()[0].gtp() == "K10"

    def test_spending_mode_is_left_alone(self):
        # lead 12 → budget 10 > max_loss＝消費モード（cost_weight < 1）では発動しない
        s, logs = _gamble_strategy(Enigma13Strategy, "enigma13", {"enigma13_gamble_until_move": 35}, root_lead=12.0)
        s.generate_move()
        assert any("Spend:" in m for m in logs)
        assert not any("Gamble" in m for m in logs)

    def test_plus_inherits_the_gamble(self):
        s, _ = _gamble_strategy(Enigma13PlusStrategy, "enigma13plus", {"enigma13plus_gamble_until_move": 35})
        assert s.generate_move()[0].gtp() == "G7"

    def test_base_shortlist_is_widened_only_inside_the_window(self):
        # 雑魚候補 8 手で安い順 7 手の枠が埋まる → OFF では G7（loss 1.2）はプローブされない
        off, _ = _gamble_strategy(Enigma13Strategy, "enigma13", extra_cands=8)
        off.generate_move()
        assert "G7" not in off.probed[0]
        assert len(off.probed[0]) == ENIGMA9_SHORTLIST
        on, _ = _gamble_strategy(Enigma13Strategy, "enigma13", {"enigma13_gamble_until_move": 35}, extra_cands=8)
        move, _ = on.generate_move()
        assert "G7" in on.probed[0]  # spread は最も高い手を必ず含む
        assert move.gtp() == "G7"
