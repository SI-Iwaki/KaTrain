# tests/test_ai_enigma_underdog.py
"""難解の「劣勢演出の罠」オプション（spec 2026-11-17-enigma-underdog-design.md）のテスト（KataGo/Kivy 不要）。"""

import types

import pytest

from katrain.core.ai import (
    ENIGMA9_UNDERDOG_CEILING_FACTOR,
    ENIGMA9_UNDERDOG_MIN_DELTA_E,
    ENIGMA9_UNDERDOG_MIN_FOOLED_LEAD,
    ENIGMA9_UNDERDOG_UPPER,
    Enigma9PlusStrategy,
    Enigma9Strategy,
    Enigma13PlusStrategy,
    Enigma13Strategy,
    Enigma19PlusStrategy,
    Enigma19Strategy,
    Mimic13Strategy,
    enigma9_underdog_pick,
    enigma9_underdog_probe_picks,
    enigma9_underdog_window,
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


class TestConstants:
    def test_values(self):
        assert ENIGMA9_UNDERDOG_UPPER == 0.0
        assert ENIGMA9_UNDERDOG_MIN_FOOLED_LEAD == 1.0
        assert ENIGMA9_UNDERDOG_MIN_DELTA_E == 0.5
        assert ENIGMA9_UNDERDOG_CEILING_FACTOR == 1.0


def window(depth=30, until=50, deficit=2.0, in_yose=False, lead=3.0, cap=1.6, large=8.0, upper=0.0):
    return enigma9_underdog_window(depth, until, deficit, in_yose, lead, cap, large, upper)


class TestUnderdogWindow:
    def test_off_when_until_move_is_zero(self):
        assert window(until=0) is None
        assert window(until=None) is None

    def test_move_window_is_exclusive_at_until_move(self):
        assert window(depth=49) is not None
        assert window(depth=50) is None
        assert window(depth=49, until=50.0) is not None  # スライダー値は float で来る

    def test_requires_a_deficit_pre_yose_and_a_lead_reading(self):
        assert window(deficit=0.0) is None
        assert window(in_yose=True) is None
        assert window(lead=None) is None

    def test_opens_outside_the_spending_mode(self):
        # 消費モード（cost_weight < 1）かどうかは引数に無い＝小差のリードでも開く
        assert window(lead=3.0, cap=1.6) == (5.0, 8.0)

    def test_closed_when_not_ahead(self):
        assert window(lead=0.0) is None  # lead <= upper
        assert window(lead=-1.0) is None
        assert window(lead=0.1) is not None

    def test_over_cap_is_lead_plus_deficit_clamped_by_the_ceiling(self):
        assert window(lead=4.0, deficit=2.5) == (6.5, 8.0)
        assert window(lead=7.0, deficit=2.0, cap=5.0) == (8.0, 8.0)

    def test_ceiling_is_the_far_ahead_cap_not_one_and_a_half_times_it(self):
        assert window(lead=6.0, cap=4.0, large=8.0)[1] == 8.0
        assert window(lead=6.0, cap=9.0, large=8.0)[1] == 9.0  # cap のほうが大きい誤設定でも下回らない

    def test_closed_when_the_ceiling_cannot_reach_the_band(self):
        assert window(lead=7.9, cap=5.9) is not None
        assert window(lead=8.0, cap=6.0) is None  # 8 目払っても 0 目＝帯 [−2, 0) に届かない
        assert window(lead=20.0, cap=8.0) is None

    def test_stays_open_when_the_band_is_inside_the_normal_cap(self):
        # lead + deficit <= cap（帯が通常上限の内側）でも開く＝通常の候補から資格を探す
        assert window(lead=0.5, deficit=2.0, cap=3.0) == (2.5, 8.0)

    def test_aim_jigo_upper_shifts_the_closed_region(self):
        assert window(lead=-0.5, upper=-1.0) is not None
        assert window(lead=-1.0, upper=-1.0) is None


def entry(gtp, lead_after, e, e_fooled, find=0.1, loss=3.0):
    return {"gtp": gtp, "lead_after": lead_after, "e": e, "e_fooled": e_fooled, "find": find, "loss": loss}


def pick(entries, best_e=0.2, deficit=2.0, upper=0.0, floor=1.0, ceiling=8.0):
    return enigma9_underdog_pick(entries, best_e, deficit, upper, floor, ceiling)


class TestUnderdogPick:
    def test_qualifier_is_returned_with_derived_fields(self):
        p, quals = pick([entry("G7", -0.5, 2.0, 3.0)])
        assert p["gtp"] == "G7" and len(quals) == 1
        assert p["fooled_lead"] == pytest.approx(2.5)
        assert p["u"] == pytest.approx(1.5)

    def test_delta_e_gate_is_inclusive(self):
        assert pick([entry("G7", -0.5, 0.7, 3.0)], best_e=0.2)[0] is not None  # ΔE = 0.5
        assert pick([entry("G7", -0.5, 0.69, 3.0)], best_e=0.2)[0] is None
        # 最善手のほうが大きい罠の手番では打たない
        assert pick([entry("G7", -0.5, 1.5, 3.0)], best_e=2.5)[0] is None

    def test_no_best_entry_means_no_pick(self):
        assert pick([entry("G7", -0.5, 2.0, 3.0)], best_e=None) == (None, [])

    def test_band_is_negative_only_and_bounded_by_the_deficit(self):
        assert pick([entry("G7", 0.0, 2.0, 3.0)])[0] is None  # 上端は exclusive
        assert pick([entry("G7", -0.01, 2.0, 3.0)])[0] is not None
        assert pick([entry("G7", -2.0, 2.0, 4.0)])[0] is not None  # 下端は inclusive
        assert pick([entry("G7", -2.1, 2.0, 4.0)])[0] is None

    def test_findability_fooled_lead_and_ceiling_gates(self):
        assert pick([entry("G7", -0.5, 2.0, 3.0, find=0.25)])[0] is not None
        assert pick([entry("G7", -0.5, 2.0, 3.0, find=0.26)])[0] is None
        assert pick([entry("G7", -0.5, 2.0, 1.5)])[0] is not None  # −0.5 + 1.5 = 1.0
        assert pick([entry("G7", -0.5, 2.0, 1.4)])[0] is None
        assert pick([entry("G7", -0.5, 2.0, 3.0, loss=8.0)])[0] is not None
        assert pick([entry("G7", -0.5, 2.0, 3.0, loss=8.1)])[0] is None

    def test_ranking_is_expected_lead_then_shallower(self):
        shallow = entry("A1", -0.2, 1.0, 3.0)  # u = 0.8
        deep = entry("B2", -1.5, 2.6, 4.0)  # u = 1.1
        assert pick([shallow, deep])[0]["gtp"] == "B2"
        tie = entry("C3", -0.4, 1.2, 3.0)  # u = 0.8 → 同点は応じられた後のリードが大きいほう
        assert pick([tie, shallow])[0]["gtp"] == "A1"

    def test_inputs_are_not_mutated(self):
        e = entry("G7", -0.5, 2.0, 3.0)
        before = dict(e)
        pick([e])
        assert e == before
        assert pick([]) == (None, [])


def cand(gtp, loss, visits=1):
    return {"gtp": gtp, "loss": loss, "visits": visits}


class TestUnderdogProbePicks:
    def test_band_excludes_best_pass_taken_and_out_of_range(self):
        cands = [cand("D4", 0.0, 900), cand("pass", 2.0), cand("K10", 2.0), cand("A1", 1.0), cand("B2", 2.0),
                 cand("C3", 4.0), cand("E5", 4.1)]
        picks = enigma9_underdog_probe_picks(cands, "D4", {"K10"}, 1.0, 4.0, 6)
        assert [c["gtp"] for c in picks] == ["B2", "C3"]  # 下端は exclusive・上端は inclusive

    def test_spread_is_even_over_the_band_regardless_of_visits(self):
        # 浅い候補（visits 1）だけの帯でも、安い順に固めず両端を含めて等間隔に取る
        cands = [cand(f"T{i}", 1.0 + 0.1 * i) for i in range(1, 12)]  # 1.1 〜 2.1 の 11 手
        picks = enigma9_underdog_probe_picks(cands, "D4", set(), 1.0, 3.0, 3)
        assert [c["gtp"] for c in picks] == ["T1", "T6", "T11"]
        # 信頼できる候補（visits 多い）を優先しない
        mixed = [cand("A1", 1.1, 50), cand("B2", 1.2, 50), cand("C3", 1.3, 50), cand("E5", 2.0), cand("F6", 3.0)]
        assert [c["gtp"] for c in enigma9_underdog_probe_picks(mixed, "D4", set(), 1.0, 3.0, 2)] == ["A1", "F6"]

    def test_small_band_and_zero_probes(self):
        cands = [cand("A1", 1.5), cand("B2", 2.5)]
        assert len(enigma9_underdog_probe_picks(cands, "D4", set(), 1.0, 3.0, 6)) == 2
        assert enigma9_underdog_probe_picks(cands, "D4", set(), 1.0, 3.0, 0) == []
        assert enigma9_underdog_probe_picks([], "D4", set(), 1.0, 3.0, 6) == []


def _plain(key):
    return [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]


class TestUnderdogSettings:
    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_defaults_are_off_two_points_six_probes(self, cls):
        d = cls.SETTING_DEFAULTS
        assert d["underdog_until_move"] == 0
        assert d["underdog_deficit"] == 2.0
        assert d["underdog_probes"] == 6

    @pytest.mark.parametrize("cls", ALL_ENIGMA, ids=lambda c: c.KEY_PREFIX)
    def test_gui_options(self, cls):
        p = cls.KEY_PREFIX
        assert AI_OPTION_VALUES[f"{p}_underdog_until_move"][0] == (0, "OFF")
        until = _plain(f"{p}_underdog_until_move")
        assert until == sorted(until) and len(until) == 5
        assert _plain(f"{p}_underdog_deficit") == [1.0, 1.5, 2.0, 2.5, 3.0]
        assert _plain(f"{p}_underdog_probes") == [4, 6, 8, 12]

    def test_window_candidates_scale_with_the_board(self):
        assert _plain("enigma9_underdog_until_move")[1:] == [12, 16, 20, 24]
        assert _plain("enigma13_underdog_until_move")[1:] == [30, 40, 50, 60]
        assert _plain("enigma19_underdog_until_move")[1:] == [60, 80, 100, 120]

    def test_mimic13_is_untouched(self):
        assert not any(k.startswith("underdog") for k in Mimic13Strategy.SETTING_DEFAULTS)


def _hp(size, values):
    """humanPolicy のフラット配列（size×size＋pass）。values は {gtp: hp}。"""
    from katrain.core.sgf_parser import Move

    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def _child(lead_after, wr_after, replies, reply_hp, size=13):
    """黒番が打った後の子局面プローブ（clean + hp）。replies は [(gtp, 白視点の損失, visits)]。"""
    move_infos = [
        {"move": g, "scoreLead": lead_after + loss, "visits": v, "order": i} for i, (g, loss, v) in enumerate(replies)
    ]
    return {
        "clean": {"rootInfo": {"scoreLead": lead_after, "winrate": wr_after}, "moveInfos": move_infos},
        "hp": {"humanPolicy": _hp(size, reply_hp)},
    }


EASY = ([("C3", 0.0, 300), ("N1", 0.4, 20)], {"C3": 0.9, "N1": 0.05})  # 応手が自明＝E≈0
TRAP = ([("C3", 0.0, 300), ("M12", 6.0, 40)], {"C3": 0.10, "M12": 0.80})  # 正解 C3 は hp 10%・自然な M12 は 6 目損
SMALL = ([("C3", 0.0, 300), ("M12", 1.2, 40)], {"C3": 0.10, "M12": 0.80})  # 引っかかっても 1.2 目しか戻らない罠


def _underdog_strategy(
    cls,
    prefix,
    settings=None,
    *,
    depth=30,
    root_lead=3.0,
    d4=EASY,
    h8_raw=1.4,
    h8_lead=2.2,
    h8_wr=0.70,
    h8=EASY,
    g7_raw=3.6,
    g7_lead=-0.5,
    g7=TRAP,
    endgame=False,
):
    """黒 +3 目（target 2・max_loss 1.6 → 消費モードの外＝cap 1.6）の13路・黒番・30 手目。

    D4=最善 / K10=安い外し（従来の net 比較はこれを選ぶ）/ H8=生 loss 1.4（通常上限の内側＝通常の shortlist）/
    G7=生 loss 3.6（通常上限の外＝劣勢演出の罠の追加プローブでしか調べない）。G7 は応じられたら g7_lead
    （既定 −0.5）、引っかかれば +6 目戻る本物の罠。
    """
    logs = []
    katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
    cands = [
        {"move": "D4", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.85},
        {"move": "K10", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 60, "winrate": 0.84},
        {"move": "H8", "pointsLost": h8_raw, "relativePointsLost": h8_raw, "visits": 30, "winrate": 0.70},
        {"move": "G7", "pointsLost": g7_raw, "relativePointsLost": g7_raw, "visits": 1, "winrate": 0.40},
    ]
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
    if endgame:
        setattr(game, f"_{prefix}_endgame", True)
    base = {f"{prefix}_opening_humanstyle_moves": 0, f"{prefix}_max_loss": 1.6, f"{prefix}_locality_stddev": 0.0}
    s = cls(game, {**base, **(settings or {})})
    s.probed = []

    def probe(gtps, player, parent_hp=False):
        s.probed.append(list(gtps))
        table = {
            "D4": _child(root_lead, 0.85, *d4),
            "K10": _child(root_lead - 0.1, 0.84, *EASY),
            "H8": _child(h8_lead, h8_wr, *h8),
            "G7": _child(g7_lead, 0.40, *g7),
        }
        parent = {"humanPolicy": _hp(13, {"D4": 0.6, "H8": 0.1, "G7": 0.05})} if parent_hp else None
        return {g: table[g] for g in gtps}, parent

    s._probe_children = probe
    s._run_query = lambda label, **kw: None
    return s, logs


ON = {"enigma13_underdog_until_move": 50}


class TestUnderdogEndToEnd:
    def test_off_plays_the_classic_choice_and_never_probes_beyond_the_cap(self):
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13")
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert "G7" not in s.probed[0]
        assert not any("Underdog" in m or "Over" in m for m in logs)

    def test_on_plays_the_trap_outside_the_spending_mode(self):
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON)
        move, thoughts = s.generate_move()
        assert move.gtp() == "G7"
        assert "underdog trap G7" in thoughts
        assert "G7" in s.probed[0]
        assert not any("Spend:" in m for m in logs)  # 消費モードではない手番
        assert any("Underdog: window" in m and "G7" in m for m in logs)
        assert any("Underdog: band=[-2.0, 0.0)" in m for m in logs)
        assert any("Underdog: played G7" in m for m in logs)

    def test_outside_the_move_window_nothing_changes(self):
        off, _ = _underdog_strategy(Enigma13Strategy, "enigma13", depth=50)
        on, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, depth=50)
        assert on.generate_move()[0].gtp() == off.generate_move()[0].gtp() == "K10"
        assert on.probed == off.probed
        assert not any("Underdog" in m for m in logs)

    def test_not_ahead_means_no_trap(self):
        # 互角以下の手番では開かない＝既に劣勢なら通常の選択で挽回する
        off, _ = _underdog_strategy(Enigma13Strategy, "enigma13", root_lead=0.0, g7_raw=1.0, g7_lead=-1.0)
        on, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, root_lead=0.0, g7_raw=1.0, g7_lead=-1.0)
        assert on.generate_move()[0].gtp() == off.generate_move()[0].gtp()
        assert on.probed == off.probed
        assert not any("Underdog" in m for m in logs)

    def test_answered_lead_must_be_negative(self):
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, g7_lead=0.3)
        assert s.generate_move()[0].gtp() == "K10"
        assert any("Underdog: band" in m and "qualifiers=[]" in m for m in logs)

    def test_deficit_setting_blocks_a_deeper_fall(self):
        deep = {**ON, "enigma13_underdog_deficit": 1.0}
        s, _ = _underdog_strategy(Enigma13Strategy, "enigma13", deep, g7_lead=-1.5)
        assert s.generate_move()[0].gtp() == "K10"
        s, _ = _underdog_strategy(Enigma13Strategy, "enigma13", {**ON, "enigma13_underdog_deficit": 2.0}, g7_lead=-1.5)
        assert s.generate_move()[0].gtp() == "G7"

    def test_trap_must_leave_a_lead_when_the_opponent_falls_for_it(self):
        # 引っかかっても −0.5 + 1.2 = +0.7 < 1.0 → 資格なし
        s, _ = _underdog_strategy(Enigma13Strategy, "enigma13", ON, g7=SMALL)
        assert s.generate_move()[0].gtp() == "K10"

    def test_no_trap_when_the_best_move_is_the_bigger_trap(self):
        # 最善手自体が E の大きい罠＝ΔE < 0.5 → 損をして小さい罠を打たない（最善手が net でも勝つ）
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, d4=TRAP)
        assert s.generate_move()[0].gtp() == "D4"
        assert any("Underdog: band" in m and "qualifiers=[]" in m for m in logs)

    def test_candidate_inside_the_normal_cap_can_qualify(self):
        # リード +1.2・H8 は生 loss 1.4（通常の shortlist）で応じられたら −0.2＝検証済み損失 1.4 <= cap 1.6
        kw = dict(root_lead=1.2, h8_lead=-0.2, h8_wr=0.45, h8=TRAP, g7_raw=9.0)
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, **kw)
        move, thoughts = s.generate_move()
        assert move.gtp() == "H8" and "underdog trap H8" in thoughts
        assert any("Score H8" in m for m in logs)  # 上限の内側＝通常のスコアリングも通っている

    def test_winrate_floor_failure_inside_the_cap_is_routed_instead_of_dropped(self):
        # 同じ H8 が勝率フロア 30% 未満（25%）に落ちる場合。OFF は Drop、ON は罠の候補として残す
        kw = dict(root_lead=1.2, h8_lead=-0.2, h8_wr=0.25, h8=TRAP, g7_raw=9.0)
        off, off_logs = _underdog_strategy(Enigma13Strategy, "enigma13", **kw)
        assert off.generate_move()[0].gtp() == "K10"
        assert any("Drop H8: verified wr" in m for m in off_logs)
        on, on_logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, **kw)
        assert on.generate_move()[0].gtp() == "H8"
        assert not any("Drop H8" in m for m in on_logs)

    def test_extra_probe_inside_the_cap_does_not_join_the_normal_comparison(self):
        # G7 は生 loss 1.9（通常上限 1.6 の外＝OFF はプローブしない）だが検証すると損失 1.4＝上限の内側で、
        # 応じられてもリード +1.6（劣勢演出の罠の資格なし）。E は大きいので通常の net 比較に入れば勝つ手だが、
        # 追加プローブは罠の候補にしか回さない → 資格が無い手番は OFF と同じ手
        kw = dict(g7_raw=1.9, g7_lead=1.6)
        off, _ = _underdog_strategy(Enigma13Strategy, "enigma13", **kw)
        on, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, **kw)
        assert off.generate_move()[0].gtp() == "K10"
        assert on.generate_move()[0].gtp() == "K10"
        assert "G7" in on.probed[0] and "G7" not in off.probed[0]
        assert any("Over G7" in m for m in logs) and not any("Score G7" in m for m in logs)
        assert any("Underdog: band" in m and "qualifiers=[]" in m for m in logs)

    def test_one_move_price_is_capped_by_the_far_ahead_cap(self):
        # リード +7.5（消費モード cap 5.5・天井 = large 8.0）。G7 は応じられたら −1.0＝損失 8.5 > 8.0 → Drop
        kw = dict(root_lead=7.5, g7_raw=8.0, g7_lead=-1.0)
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, **kw)
        assert s.generate_move()[0].gtp() != "G7"
        assert any("Drop G7" in m for m in logs)
        # 同じ手番でも −0.4（損失 7.9）なら天井の内側
        s, _ = _underdog_strategy(Enigma13Strategy, "enigma13", ON, root_lead=7.5, g7_raw=8.0, g7_lead=-0.4)
        assert s.generate_move()[0].gtp() == "G7"

    def test_far_ahead_the_window_stays_closed(self):
        off, _ = _underdog_strategy(Enigma13Strategy, "enigma13", root_lead=12.0, g7_raw=12.5, g7_lead=-0.5)
        on, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, root_lead=12.0, g7_raw=12.5, g7_lead=-0.5)
        assert on.generate_move()[0].gtp() == off.generate_move()[0].gtp()
        assert on.probed == off.probed
        assert not any("Underdog" in m for m in logs)

    def test_probe_count_setting(self):
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", {**ON, "enigma13_underdog_probes": 0})
        assert s.generate_move()[0].gtp() == "K10"
        assert "G7" not in s.probed[0]

    def test_replaces_the_overdraft_inside_the_move_window(self):
        # 捨て身の罠 ON（MAX＝応じられても少しプラスの穏やかな罠も打つ）。リード +6 の消費モードで G7 は
        # 応じられたら +0.5。手数の窓の外は捨て身の罠が打ち、窓の中は劣勢演出の罠の帯（必ずマイナス）に置き換わる
        od = {"enigma13_overdraft_deficit": 2.5, "enigma13_overdraft_answered_max": 99.0}
        kw = dict(root_lead=6.0, g7_raw=6.0, g7_lead=0.5)
        outside, out_logs = _underdog_strategy(Enigma13Strategy, "enigma13", {**od, **ON}, depth=60, **kw)
        move, thoughts = outside.generate_move()
        assert move.gtp() == "G7" and "overdraft trap G7" in thoughts
        assert any("Overdraft: played G7" in m for m in out_logs)
        inside, in_logs = _underdog_strategy(Enigma13Strategy, "enigma13", {**od, **ON}, depth=30, **kw)
        assert inside.generate_move()[0].gtp() != "G7"
        assert any("Underdog: band=[-2.0, 0.0)" in m for m in in_logs)
        assert not any("Overdraft:" in m for m in in_logs)

    def test_takes_precedence_over_the_gamble(self):
        # 賭け罠の資格（H8: ΔE 大・勝率 45% >= 35%）と劣勢演出の罠の資格（G7）が同じ手番にある → 劣勢演出の罠
        both = {**ON, "enigma13_gamble_until_move": 50}
        kw = dict(h8_lead=2.0, h8_wr=0.45, h8=TRAP)
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", both, **kw)
        assert s.generate_move()[0].gtp() == "G7"
        assert not any("Gamble: played" in m for m in logs)
        # 劣勢演出の罠の資格が無ければ賭け罠がそのまま働く
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", both, g7_lead=0.3, **kw)
        assert s.generate_move()[0].gtp() == "H8"
        assert any("Gamble: played H8" in m for m in logs)

    def test_yose_is_left_alone(self):
        s, logs = _underdog_strategy(Enigma13Strategy, "enigma13", ON, endgame=True)
        move, _ = s.generate_move()
        assert move.gtp() == "D4"  # スタブの Probe は None → lead unavailable → 最善手
        assert not any("Underdog" in m for m in logs)

    def test_plus_inherits_the_underdog(self):
        s, _ = _underdog_strategy(Enigma13PlusStrategy, "enigma13plus", {"enigma13plus_underdog_until_move": 50})
        assert s.generate_move()[0].gtp() == "G7"

    def test_aim_jigo_band_ends_at_minus_one(self):
        # aim_jigo: target = −1 → 消費モード cap = min(8, lead + 1) = 4.0、帯は [−2, min(−1, 0)) ＝ [−2, −1)
        jigo = {**ON, "enigma13_aim_jigo": True}
        # 応じられたら −0.5 の G7 は帯の外＝劣勢演出の罠としては打たない（損失 3.5 は上限の内側なので、
        # 打つとしても従来の難解さの比較による外し）
        mild, logs = _underdog_strategy(Enigma13Strategy, "enigma13", jigo)
        _, thoughts = mild.generate_move()
        assert "underdog trap" not in thoughts
        assert any("Underdog: band=[-2.0, -1.0)" in m and "qualifiers=[]" in m for m in logs)
        # 応じられたら −1.5（損失 4.5 > cap 4.0）は帯の中 → 劣勢演出の罠
        deep, _ = _underdog_strategy(Enigma13Strategy, "enigma13", jigo, g7_lead=-1.5)
        move, thoughts = deep.generate_move()
        assert move.gtp() == "G7" and "underdog trap G7" in thoughts
