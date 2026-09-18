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

    def test_window_closes_when_no_move_within_the_ceiling_can_land_in_the_band(self):
        # 実戦ログ 2026-09-18: リード 12 目以上の 55 手番で窓が開き 115 手を無駄にプローブした。天井（12 目）まで
        # 払っても着手後リードが帯の上端 upper を下回らない（lead − ceiling >= upper）なら資格は原理的に出ない
        assert enigma9_overdraft_window(2.5, False, 0.2, 11.0, 8.0, 8.0, upper=0.0) == (12.0, 12.0)
        assert enigma9_overdraft_window(2.5, False, 0.2, 12.0, 8.0, 8.0, upper=0.0) is None  # ちょうど 0 は帯の外
        assert enigma9_overdraft_window(2.5, False, 0.1, 23.0, 8.0, 8.0, upper=0.0) is None
        assert enigma9_overdraft_window(2.5, False, 0.2, 12.5, 8.0, 8.0, upper=1.0) == (12.0, 12.0)  # MAX=目標差未満
        assert enigma9_overdraft_window(2.5, False, 0.2, 11.5, 8.0, 8.0, upper=-1.0) is None
        assert enigma9_overdraft_window(2.5, False, 0.1, 23.0, 8.0, 8.0) == (12.0, 12.0)  # upper 省略＝従来どおり

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


import types


def _hp(size, values):
    """humanPolicy のフラット配列（size×size＋pass）。values は {gtp: hp}。"""
    from katrain.core.sgf_parser import Move

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


EASY = ([("C3", 0.0, 300), ("N1", 0.4, 20)], {"C3": 0.9, "N1": 0.05})  # 応手が自明＝E≈0
TRAP = ([("C3", 0.0, 300), ("M12", 6.0, 40)], {"C3": 0.10, "M12": 0.80})  # 正解 C3 は hp 10%・自然な M12 は 6 目損


def _overdraft_strategy(cls, prefix, settings=None, *, root_lead=6.0, d4_lead=6.0, g7_lead=-1.5, h8_lead=3.2,
                        endgame=False, forced=False):
    """黒 +6 目（target 2・max_loss 1.6 → 消費モード cap 4.0）の13路・黒番。

    D4=最善（子局面 root のリード d4_lead＝検証済み損失の基準）/ K10=安い外し（従来の net 比較はこれを選ぶ）/
    H8=生 loss 3.0（通常の shortlist に入る）/ G7=生 loss 7.5（通常上限の外＝捨て身の罠の追加プローブでしか
    調べない）。G7 は応じられたら g7_lead（既定 −1.5・勝率 20%＝勝率フロア 30% 未満）、引っかかれば +6 目戻る本物の罠。
    """
    logs = []
    katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
    cands = [
        {"move": "D4", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 900, "winrate": 0.95},
        {"move": "K10", "pointsLost": 0.1, "relativePointsLost": 0.1, "visits": 60, "winrate": 0.94},
        {"move": "H8", "pointsLost": 3.0, "relativePointsLost": 3.0, "visits": 30, "winrate": 0.80},
        {"move": "G7", "pointsLost": 7.5, "relativePointsLost": 7.5, "visits": 1, "winrate": 0.20},
    ]
    if forced:  # 最善手以外は全部 通常上限（cap 4.0）の外＝通常の候補プールが空になる一本道の局面
        cands = [c for c in cands if c["move"] in ("D4", "G7")]
    node = types.SimpleNamespace(
        next_player="B", player="W", depth=40, move=None, analysis_complete=True,
        analysis={"root": {"scoreLead": root_lead}}, candidate_moves=cands,
    )
    game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(13, 13))
    if endgame:
        setattr(game, f"_{prefix}_endgame", True)
    base = {f"{prefix}_opening_humanstyle_moves": 0, f"{prefix}_max_loss": 1.6, f"{prefix}_locality_stddev": 0.0}
    s = cls(game, {**base, **(settings or {})})
    s.probed = []

    def probe(gtps, player, parent_hp=False):
        s.probed.append(list(gtps))
        h8 = TRAP if h8_lead < 0 else EASY
        table = {
            "D4": _child(d4_lead, 0.95, *EASY),
            "K10": _child(5.9, 0.94, *EASY),
            "H8": _child(h8_lead, 0.80 if h8_lead >= 0 else 0.25, *h8),
            "G7": _child(g7_lead, 0.20, *TRAP),
        }
        parent = {"humanPolicy": _hp(13, {"D4": 0.6, "H8": 0.1, "G7": 0.05})} if parent_hp else None
        return {g: table[g] for g in gtps}, parent

    s._probe_children = probe
    s._run_query = lambda label, **kw: None
    return s, logs


ON = {"enigma13_overdraft_deficit": 2.5}


class TestOverdraftEndToEnd:
    def test_off_plays_the_classic_choice_and_never_probes_beyond_the_cap(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13")
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert "G7" not in s.probed[0]
        assert not any("Over" in m for m in logs)

    def test_on_plays_the_trap_beyond_the_cap_ignoring_the_winrate_floor(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON)
        move, thoughts = s.generate_move()
        assert move.gtp() == "G7"
        assert "overdraft trap G7" in thoughts
        assert "G7" in s.probed[0]
        assert any("Overdraft: window" in m and "G7" in m for m in logs)
        assert any("Overdraft: played G7" in m for m in logs)

    def test_deficit_setting_blocks_a_deeper_fall(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", {"enigma13_overdraft_deficit": 1.0})
        assert s.generate_move()[0].gtp() == "K10"  # 応じられたら −1.5 < −1.0
        assert any("Overdraft: band" in m and "qualifiers=[]" in m for m in logs)

    def test_fooled_lead_setting_blocks_the_trap(self):
        s, _ = _overdraft_strategy(
            Enigma13Strategy, "enigma13", {**ON, "enigma13_overdraft_min_fooled_lead": 5.0}
        )
        assert s.generate_move()[0].gtp() == "K10"  # 引っかかっても −1.5 + 6.0 = 4.5 < 5.0

    def test_negative_only_default_skips_a_mild_trap(self):
        s, _ = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, g7_lead=0.5)
        assert s.generate_move()[0].gtp() == "K10"

    def test_answered_max_setting_admits_a_mild_trap_below_the_target(self):
        s, _ = _overdraft_strategy(
            Enigma13Strategy, "enigma13", {**ON, "enigma13_overdraft_answered_max": 99.0}, g7_lead=0.5
        )
        assert s.generate_move()[0].gtp() == "G7"

    def test_shortlist_candidate_verified_beyond_the_cap_is_routed_instead_of_dropped(self):
        # H8 は生 loss 3.0 で通常の shortlist に入るが、検証すると −1.0（vloss 7.0 > cap 4.0）
        off, off_logs = _overdraft_strategy(Enigma13Strategy, "enigma13", h8_lead=-1.0)
        assert off.generate_move()[0].gtp() == "K10"
        assert any("Drop H8" in m for m in off_logs)
        on, on_logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, h8_lead=-1.0)
        # H8（u = −1.0 + E）と G7（u = −1.5 + E）の両方が資格あり → 期待リードの大きい H8
        assert on.generate_move()[0].gtp() == "H8"
        assert not any("Drop H8" in m for m in on_logs)

    def test_trap_is_found_even_when_the_normal_pool_is_empty(self):
        # 実局面 game_20260918_004112 d=50: 最善手以外が全部 cap の外で「no admissible deviation」の早期 return に
        # 倒れ、反実仮想で資格のあった罠（G10）を一度もプローブしなかった。窓が開いていれば先へ進む
        off, off_logs = _overdraft_strategy(Enigma13Strategy, "enigma13", forced=True)
        move, thoughts = off.generate_move()
        assert move.gtp() == "D4" and "no admissible deviation" in thoughts
        assert off.probed == []
        on, _ = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, forced=True)
        assert on.generate_move()[0].gtp() == "G7"

    def test_empty_pool_and_no_overdraft_candidates_still_returns_early(self):
        # 窓は開いているが帯に候補が無い（deficit 0.5 → 生 loss の帯 (2.5, 8.0] に G7 の 7.5 は入るので、
        # G7 を帯の外へ出すために probes=0 相当＝帯が空になる設定を使う）
        s, _ = _overdraft_strategy(
            Enigma13Strategy, "enigma13", {**ON, "enigma13_overdraft_probes": 0}, forced=True
        )
        move, thoughts = s.generate_move()
        assert move.gtp() == "D4" and "no admissible deviation" in thoughts
        assert s.probed == []

    def test_far_ahead_the_window_stays_closed_and_nothing_extra_is_probed(self):
        # +20 目（cap 8・天井 12）: 12 目払っても +8 目＝帯 [−2.5, 0) に届かない → OFF と同じ手番になる
        off, _ = _overdraft_strategy(Enigma13Strategy, "enigma13", root_lead=20.0, d4_lead=20.0)
        on, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, root_lead=20.0, d4_lead=20.0)
        assert on.generate_move()[0].gtp() == off.generate_move()[0].gtp()
        assert on.probed == off.probed
        assert not any("Over" in m for m in logs)

    def test_outside_the_spending_mode_nothing_changes(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, root_lead=0.2)
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert "G7" not in s.probed[0]
        assert not any("Over" in m for m in logs)

    def test_yose_is_left_alone(self):
        s, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", ON, endgame=True)
        move, _ = s.generate_move()
        assert move.gtp() == "D4"  # スタブの Probe は None → lead unavailable → 最善手
        assert not any("Over" in m for m in logs)

    def test_plus_inherits_the_overdraft(self):
        s, _ = _overdraft_strategy(Enigma13PlusStrategy, "enigma13plus", {"enigma13plus_overdraft_deficit": 2.5})
        assert s.generate_move()[0].gtp() == "G7"

    def test_aim_jigo_band_ends_at_minus_one(self):
        # aim_jigo: target = −1 → cap = min(8, lead + 1) = 7.0、帯は [−2.5, min(−1, 0)) ＝ [−2.5, −1)
        jigo = {**ON, "enigma13_aim_jigo": True}
        deep, _ = _overdraft_strategy(Enigma13Strategy, "enigma13", jigo)  # vloss 7.5 > 7.0・応じられたら −1.5
        assert deep.generate_move()[0].gtp() == "G7"
        # 最善手の子局面が +7（root の +6 より上）だと、応じられたら −0.5 の G7 も vloss 7.5 で上限の外に
        # 回るが、帯の上端（target = −1）の外なので資格なし → 従来の選択（G7 は scored に居ない）
        mild, logs = _overdraft_strategy(Enigma13Strategy, "enigma13", jigo, d4_lead=7.0, g7_lead=-0.5)
        assert mild.generate_move()[0].gtp() == "K10"
        assert any("Overdraft: band=[-2.5, -1.0)" in m and "qualifiers=[]" in m for m in logs)
