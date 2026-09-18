# tests/test_ai_mimic13.py
"""「擬態（13路）」ai:mimic13 の純関数・登録整合・_generate_move 通しテスト（KataGo/Kivy 不要）。

設計: docs/superpowers/specs/2026-09-17-mimic13-strategy-design.md
"""

import types

import pytest

import katrain.core.ai as ai_module
from katrain.core.ai import (
    MIMIC_BEHIND_LIMIT,
    MIMIC_TRAP_MIN_HP,
    Enigma9Strategy,
    Enigma13Strategy,
    Mimic13Strategy,
    mimic_choose,
    mimic_hp_top,
    mimic_natural_floor,
    mimic_price_cap,
    mimic_qualifies,
    mimic_shortlist,
    mimic_yose_delegates,
)
from katrain.core.sgf_parser import Move


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


def _hp_array(size, values):
    """{gtp: hp} → KataGo の humanPolicy フラット配列（末尾 pass）"""
    arr = [0.0] * (size * size + 1)
    for gtp, v in values.items():
        if gtp == "pass":
            arr[-1] = v
            continue
        x, y = Move.from_gtp(gtp).coords
        arr[(size - 1 - y) * size + x] = v
    return arr


def _child(lead_black, replies, reply_hp):
    """子局面プローブの疑似レスポンス。replies: [(gtp, scoreLead 黒視点, visits)]・reply_hp: {gtp: hp}"""
    clean = {
        "rootInfo": {"scoreLead": lead_black, "winrate": 0.6},
        "moveInfos": [{"move": g, "scoreLead": s, "visits": v} for g, s, v in replies],
    }
    return {"clean": clean, "hp": {"humanPolicy": _hp_array(13, reply_hp)}}


class TestStrategyClass:
    def test_registered_as_a_13x13_enigma_subclass(self):
        from katrain.core.ai import STRATEGY_REGISTRY
        from katrain.core.constants import AI_MIMIC_13

        assert AI_MIMIC_13 == "ai:mimic13"
        assert STRATEGY_REGISTRY[AI_MIMIC_13] is Mimic13Strategy
        assert issubclass(Mimic13Strategy, Enigma13Strategy)
        assert (Mimic13Strategy.BOARD_LEN, Mimic13Strategy.KEY_PREFIX, Mimic13Strategy.LABEL) == (
            13,
            "mimic13",
            "Mimic13",
        )

    def test_defaults_match_the_spec(self):
        assert Mimic13Strategy.SETTING_DEFAULTS == {
            "max_loss": 2.0,
            "reserve": 3.0,
            "spend_rate": 0.25,
            "free_loss": 0.3,
            "min_winrate": 0.4,
            "dominant_hp": 0.8,
            "min_human_policy": 0.05,
            "natural_ratio": 0.2,
            "trap_min_delta_e": 0.5,
            "cost_slack": 0.3,
            "probe_extra": 4,
            "endgame_move": 85,
            "unsettled_max": 16,
        }

    def test_base_flow_is_untouched(self):
        assert Enigma13Strategy._generate_move is not Mimic13Strategy._generate_move
        assert Mimic13Strategy.generate_move is Enigma13Strategy.generate_move  # 時間ログのラッパーは共有


class _Harness:
    """_generate_move の通しテスト用スタブ（エンジンなし）。黒番・13路・最善手 G7。
    名前が Test で始まらないので pytest には収集されない（継承した側だけが走る）。"""

    CANDS = [
        {"move": "G7", "pointsLost": 0.0, "relativePointsLost": 0.0, "visits": 600, "winrate": 0.62},
        {"move": "D4", "pointsLost": 0.4, "relativePointsLost": 0.4, "visits": 200, "winrate": 0.60},
        {"move": "K10", "pointsLost": 1.2, "relativePointsLost": 1.2, "visits": 40, "winrate": 0.57},
        {"move": "A1", "pointsLost": 9.0, "relativePointsLost": 9.0, "visits": 3, "winrate": 0.2},
    ]

    def _strategy(self, *, lead=8.0, depth=30, hp=None, probes=None, settings=None, ownership=None, **game_attrs):
        logs = []
        katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
        node = types.SimpleNamespace(
            next_player="B",
            player="W",
            depth=depth,
            move=None,
            analysis_complete=True,
            analysis={"root": {"scoreLead": lead}},
            candidate_moves=[dict(c) for c in self.CANDS],
            nodes_from_root=[],
        )
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(13, 13), **game_attrs)
        s = Mimic13Strategy(game, settings or {})
        s.queries, s.probe_calls = [], []

        def run_query(label, **kw):
            s.queries.append(label)
            if label == "HumanSL":
                return None if hp is None else {"humanPolicy": hp}
            return None if ownership is None else {"ownership": ownership, "rootInfo": {"scoreLead": lead}}

        def probe_children(gtps, player, parent_hp=False):
            s.probe_calls.append(list(gtps))
            return {g: (probes or {}).get(g) for g in gtps}, None

        s._run_query = run_query
        s._probe_children = probe_children
        s._start_ponder = lambda *a, **k: None
        return s, logs

    # 応手テーブル: 白の応手 C11（本命）/ L3。scoreLead は黒視点（白は小さいほど良い）
    def _probes(self, d4_lead=7.8, d4_punish=0.0, k10_lead=7.0, k10_punish=0.0):
        hp = {"C11": 0.5, "L3": 0.5}
        return {
            "G7": _child(8.0, [("C11", 8.0, 300), ("L3", 8.0, 200)], hp),
            "D4": _child(d4_lead, [("C11", d4_lead, 300), ("L3", d4_lead + 2 * d4_punish, 200)], hp),
            "K10": _child(k10_lead, [("C11", k10_lead, 300), ("L3", k10_lead + 2 * k10_punish, 200)], hp),
        }


class TestGenerateMove(_Harness):
    def test_dominant_first_instinct_plays_the_best_move_without_probes(self):
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.91, "D4": 0.05}), probes=self._probes())
        move, _ = s.generate_move()
        assert move.gtp() == "G7"
        assert s.queries == ["HumanSL"] and s.probe_calls == []
        assert any("Dominant" in m for m in logs)

    def test_natural_cheap_deviation_is_bought_with_surplus(self):
        # lead 8・reserve 3 → λ=1.25。D4 は hp 0.30（自然）・vloss 0.2・ΔE 0 → price 0.2
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.40, "D4": 0.30, "K10": 0.02}), probes=self._probes())
        move, reason = s.generate_move()
        assert move.gtp() == "D4"
        assert any("Deviate" in m and "natural" in m for m in logs)

    def test_unnatural_move_without_trap_value_is_not_played(self):
        # D4 の hp を床未満に。K10 も hp 0.02・ΔE 0 → 資格者なし
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.60, "D4": 0.02, "K10": 0.02}), probes=self._probes())
        move, _ = s.generate_move()
        assert move.gtp() == "G7"

    def test_trap_is_played_even_when_behind_if_it_pays_for_itself(self):
        # lead -2 → λ=0。K10 は hp 0.02（不自然）だが vloss 1.0・ΔE 1.5（L3 が 3 目損・hp 0.5）→ price -0.5
        probes = self._probes(k10_lead=7.0, k10_punish=1.5)
        s, logs = self._strategy(
            lead=-2.0,
            hp=_hp_array(13, {"G7": 0.60, "D4": 0.02, "K10": 0.02}),
            probes=probes,
            settings={"mimic13_min_winrate": 0.3},
        )
        move, _ = s.generate_move()
        assert move.gtp() == "K10"
        assert any("trap" in m for m in logs)

    def test_price_above_lambda_keeps_the_best_move(self):
        # lead 3（余剰 0）→ λ=0.3。D4 は自然だが vloss 0.8
        s, logs = self._strategy(lead=3.0, hp=_hp_array(13, {"G7": 0.40, "D4": 0.30}), probes=self._probes(d4_lead=7.2))
        move, _ = s.generate_move()
        assert move.gtp() == "G7"

    def test_verified_loss_above_max_loss_is_dropped(self):
        s, logs = self._strategy(
            lead=30.0, hp=_hp_array(13, {"G7": 0.40, "D4": 0.30}), probes=self._probes(d4_lead=5.5)
        )
        move, _ = s.generate_move()
        assert move.gtp() == "G7"
        assert any("Drop D4" in m for m in logs)

    def test_humansl_failure_is_failsafe(self):
        s, logs = self._strategy(hp=None, probes=self._probes())
        move, _ = s.generate_move()
        assert move.gtp() == "G7" and s.probe_calls == []

    def test_wrong_board_size_is_failsafe(self):
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.4, "D4": 0.3}), probes=self._probes())
        s.game.board_size = (9, 9)
        move, _ = s.generate_move()
        assert move.gtp() == "G7" and s.queries == []

    def test_missing_lead_is_failsafe(self):
        s, logs = self._strategy(hp=_hp_array(13, {"G7": 0.4, "D4": 0.3}), probes=self._probes())
        s.cn.analysis = {}
        move, _ = s.generate_move()
        assert move.gtp() == "G7" and s.queries == []


class _FakeHumanStyle:
    calls = []

    def __init__(self, game, settings):
        type(self).calls.append(settings)
        self.game = game

    def generate_move(self):
        return Move.from_gtp("D4", player="B"), "fake 9d"


class TestYose(_Harness):
    def test_enters_yose_by_moves_and_unsettled_points_then_delegates(self, monkeypatch):
        monkeypatch.setattr(ai_module, "HumanStyleStrategy", _FakeHumanStyle)
        _FakeHumanStyle.calls = []
        s, logs = self._strategy(depth=90, lead=6.0, ownership=[0.95] * 160 + [0.1] * 9)
        move, reason = s.generate_move()
        assert s.queries == ["Probe"]  # ヨセ突入の判定に ownership を1本
        assert s.game._mimic13_endgame is True  # sticky
        assert move.gtp() == "D4" and reason.startswith("[Mimic13→9d yose]")
        assert _FakeHumanStyle.calls == [{"human_kyu_rank": -8, "modern_style": True}]

    def test_sticky_yose_needs_no_probe(self, monkeypatch):
        monkeypatch.setattr(ai_module, "HumanStyleStrategy", _FakeHumanStyle)
        s, logs = self._strategy(depth=95, lead=6.0, _mimic13_endgame=True)
        move, _ = s.generate_move()
        assert s.queries == [] and move.gtp() == "D4"

    def test_thin_lead_in_yose_plays_the_best_move(self, monkeypatch):
        monkeypatch.setattr(ai_module, "HumanStyleStrategy", _FakeHumanStyle)
        _FakeHumanStyle.calls = []
        s, logs = self._strategy(depth=95, lead=2.0, _mimic13_endgame=True)
        move, _ = s.generate_move()
        assert move.gtp() == "G7" and _FakeHumanStyle.calls == []

    def test_unsettled_board_stays_in_the_middle_game(self):
        s, logs = self._strategy(
            depth=90,
            ownership=[0.1] * 169,
            hp=_hp_array(13, {"G7": 0.40, "D4": 0.30}),
            probes=self._probes(),
        )
        move, _ = s.generate_move()
        assert getattr(s.game, "_mimic13_endgame", False) is False
        assert s.queries == ["Probe", "HumanSL"] and move.gtp() == "D4"


class TestGuiConfigConsistency:
    """SETTING_DEFAULTS・AI_OPTION_VALUES・AI_OPTION_ORDER・パッケージ config.json・戦略リストの整合。"""

    def test_listed_everywhere(self):
        from katrain.core.constants import (
            AI_MIMIC_13,
            AI_STRATEGIES,
            AI_STRATEGIES_ENGINE,
            AI_STRATEGIES_RECOMMENDED_ORDER,
            AI_STRENGTH,
        )

        assert AI_MIMIC_13 in AI_STRATEGIES_ENGINE  # 通常解析の完了を待つ系
        assert AI_MIMIC_13 in AI_STRATEGIES
        assert AI_MIMIC_13 in AI_STRATEGIES_RECOMMENDED_ORDER
        assert AI_MIMIC_13 in AI_STRENGTH

    def test_defaults_in_gui_options_and_package_config(self):
        import json
        from pathlib import Path

        import katrain
        from katrain.core.constants import AI_OPTION_ORDER, AI_OPTION_VALUES

        with open(Path(katrain.__file__).parent / "config.json", encoding="utf-8") as f:
            package_ai_conf = json.load(f)["ai"]["ai:mimic13"]
        expected = {f"mimic13_{suffix}" for suffix in Mimic13Strategy.SETTING_DEFAULTS}
        assert set(package_ai_conf) == expected
        for suffix, default in Mimic13Strategy.SETTING_DEFAULTS.items():
            key = f"mimic13_{suffix}"
            assert package_ai_conf[key] == default, key
            assert key in AI_OPTION_ORDER, key
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]
            assert default in plain, key

    def test_debug_cli_knows_the_strategy(self):
        from katrain.core.constants import AI_MIMIC_13
        from katrain_debug.runner import STRATEGY_NAME_MAP

        assert STRATEGY_NAME_MAP["mimic13"] == AI_MIMIC_13

    @pytest.mark.parametrize("lang", ["jp", "en"])
    def test_i18n_has_every_label(self, lang):
        from pathlib import Path

        import katrain

        po = (Path(katrain.__file__).parent / "i18n" / "locales" / lang / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        for msgid in ["ai:mimic13", "aihelp:mimic13"] + [f"mimic13_{s}" for s in Mimic13Strategy.SETTING_DEFAULTS]:
            assert f'msgid "{msgid}"' in po, msgid

    @pytest.mark.parametrize("lang,bullet", [("jp", None), ("en", "* ")])
    def test_help_explains_every_slider(self, lang, bullet):
        """GUI の説明欄はスライダー1本につき1つずつ「上げると／下げると」を説明している。

        スライダーを足したのにヘルプを足し忘れる、を検出するための本数チェック（.po を直接読む＝.mo 非依存）。
        jp は項目ごとの訳文 aiopt:mimic13_*（説明欄の【各項目】に英語キー付きで画面の順に自動で並ぶ・
        katrain/gui/ai_help.py）、en は aihelp:mimic13 本文の「* 」の行。
        """
        import re
        from pathlib import Path

        import katrain

        po = (Path(katrain.__file__).parent / "i18n" / "locales" / lang / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        if bullet is None:
            for suffix in Mimic13Strategy.SETTING_DEFAULTS:
                assert f'msgid "aiopt:mimic13_{suffix}"' in po, suffix
            return
        m = re.search(r'msgid "aihelp:mimic13"\s*\nmsgstr "(.*)"', po)
        assert m, "aihelp:mimic13 not found"
        lines = m.group(1).split("\\n")  # .po の中では改行は 2 文字のエスケープ \n
        explained = [line for line in lines if line.startswith(bullet)]
        assert len(explained) == len(Mimic13Strategy.SETTING_DEFAULTS)
