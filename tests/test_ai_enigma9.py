# tests/test_ai_enigma9.py
"""「難解」戦略 ai:enigma9（9路）/ ai:enigma13（13路）/ ai:enigma19（19路）の純関数テスト（KataGo/Kivy 不要）。"""
import json
from pathlib import Path

import pytest

import katrain
from katrain.core.ai import (
    ENIGMA9_HP_BOOK,
    ENIGMA9_PUNISH_CAP,
    Enigma13Strategy,
    Enigma19Strategy,
    Enigma9Strategy,
    enigma9_admissible,
    enigma9_choose,
    enigma9_expected_punish,
    enigma9_hp_lookup,
    enigma9_net_score,
    enigma9_rarity,
    enigma9_reply_findability,
    enigma9_reply_table,
    enigma9_shortlist,
    enigma9_spending_plan,
    enigma9_verified_metrics,
)


def cand(gtp, loss, visits=100, wr=0.5):
    return {"gtp": gtp, "loss": loss, "visits": visits, "wr": wr}


class TestHpLookup:
    def make_policy(self):
        # 9x9: 81 + pass。E5 = coords (4,4) -> idx (9-1-4)*9+4 = 40
        policy = [0.0] * 82
        policy[40] = 0.25   # E5
        policy[72] = 0.03   # A1 = (0,0) -> (8)*9+0
        policy[81] = 0.001  # pass
        policy[0] = -1.0    # A9 相当のどこか非合法（humanPolicy の非合法値）
        return policy

    def test_lookup_coords(self):
        hp = enigma9_hp_lookup(self.make_policy(), (9, 9))
        assert hp("E5") == pytest.approx(0.25)
        assert hp("A1") == pytest.approx(0.03)

    def test_pass_entry(self):
        hp = enigma9_hp_lookup(self.make_policy(), (9, 9))
        assert hp("pass") == pytest.approx(0.001)

    def test_illegal_clamped_to_zero(self):
        hp = enigma9_hp_lookup(self.make_policy(), (9, 9))
        assert hp("A9") == 0.0  # idx 0 は -1 -> クランプ

    def test_no_pass_entry_when_array_short(self):
        hp = enigma9_hp_lookup([0.0] * 81, (9, 9))
        assert hp("pass") == 0.0

    def test_bad_gtp(self):
        hp = enigma9_hp_lookup(self.make_policy(), (9, 9))
        assert hp("Z99") == 0.0


class TestAdmissible:
    def test_filters_best_pass_loss_wr(self):
        candidates = [
            cand("E5", 0.0),            # best -> 除外
            cand("C3", 0.5),            # OK
            cand("D4", 1.5),            # loss > cap -> 除外
            cand("pass", 0.1),          # pass -> 除外
            cand("G7", 0.3, wr=0.2),    # wr < floor -> 除外
            cand("B2", 0.8, wr=None),   # wr 不明は許可
        ]
        pool = enigma9_admissible(candidates, "E5", cap=1.0, min_winrate=0.3)
        assert [c["gtp"] for c in pool] == ["C3", "B2"]

    def test_empty_when_all_filtered(self):
        assert enigma9_admissible([cand("E5", 0.0)], "E5", 1.0, 0.3) == []


class TestShortlist:
    def test_sorted_by_loss_then_visits(self):
        pool = [
            cand("A1", 0.5, visits=50),
            cand("B2", 0.2, visits=10),
            cand("C3", 0.2, visits=90),
            cand("D4", 0.9, visits=999),
        ]
        top = enigma9_shortlist(pool, 3)
        assert [c["gtp"] for c in top] == ["C3", "B2", "A1"]

    def test_k_larger_than_pool(self):
        pool = [cand("A1", 0.5)]
        assert len(enigma9_shortlist(pool, 5)) == 1

    def test_two_tiers_trusted_first(self):
        # 浅い候補（visits < trusted）は生 loss が最安でも第2段に回る
        pool = [
            cand("A1", 0.05, visits=3),    # 浅い・生 loss 最安
            cand("B2", 0.6, visits=40),    # 信用できる
            cand("C3", 0.4, visits=15),    # 信用できる
            cand("D4", 0.1, visits=7),     # 浅い・visits 多め
        ]
        top = enigma9_shortlist(pool, 4)
        assert [c["gtp"] for c in top] == ["C3", "B2", "D4", "A1"]

    def test_shallow_ranked_by_visits(self):
        pool = [
            cand("A1", 0.05, visits=3),
            cand("D4", 0.5, visits=8),
        ]
        top = enigma9_shortlist(pool, 1)
        assert [c["gtp"] for c in top] == ["D4"]


class TestVerifiedMetrics:
    def test_black_perspective_passthrough(self):
        lead, wr = enigma9_verified_metrics(
            {"rootInfo": {"scoreLead": 2.5, "winrate": 0.62}}, "B"
        )
        assert lead == pytest.approx(2.5)
        assert wr == pytest.approx(0.62)

    def test_white_perspective_flipped(self):
        lead, wr = enigma9_verified_metrics(
            {"rootInfo": {"scoreLead": 2.5, "winrate": 0.62}}, "W"
        )
        assert lead == pytest.approx(-2.5)
        assert wr == pytest.approx(0.38)

    def test_missing_values(self):
        assert enigma9_verified_metrics({}, "B") == (None, None)
        assert enigma9_verified_metrics(None, "W") == (None, None)


class TestReplyTable:
    def test_white_perspective_losses(self):
        # scoreLead は常に黒視点。白の応手なので低いほど良い
        infos = [
            {"move": "C3", "scoreLead": -2.0, "visits": 300},  # 白最善（白視点 +2.0）
            {"move": "D4", "scoreLead": 1.0, "visits": 100},   # 白視点 -1.0 -> loss 3.0
            {"move": "E5", "scoreLead": 4.0, "visits": 20},    # 白視点 -4.0 -> loss 6.0
        ]
        replies, best = enigma9_reply_table(infos, "W")
        assert best == "C3"
        losses = {r["gtp"]: r["loss"] for r in replies}
        assert losses["C3"] == pytest.approx(0.0)
        assert losses["D4"] == pytest.approx(3.0)
        assert losses["E5"] == pytest.approx(6.0)

    def test_black_perspective(self):
        infos = [
            {"move": "C3", "scoreLead": 5.0, "visits": 300},
            {"move": "D4", "scoreLead": 3.5, "visits": 100},
        ]
        replies, best = enigma9_reply_table(infos, "B")
        assert best == "C3"
        losses = {r["gtp"]: r["loss"] for r in replies}
        assert losses["D4"] == pytest.approx(1.5)

    def test_shallow_reply_cannot_take_reference(self):
        # 1visit の蜃気楼（白視点 +9.0）が基準を乗っ取ると全応手の損失が
        # かさ上げされる。基準は visits >= ref_min から取り、蜃気楼側の
        # 損失は 0 にクランプされる
        infos = [
            {"move": "C3", "scoreLead": -2.0, "visits": 300},
            {"move": "H8", "scoreLead": -9.0, "visits": 1},   # include からも外れる（< 2）
            {"move": "G2", "scoreLead": -8.0, "visits": 3},   # include はされるが基準ではない
        ]
        replies, best = enigma9_reply_table(infos, "W")
        assert best == "C3"
        losses = {r["gtp"]: r["loss"] for r in replies}
        assert "H8" not in losses
        assert losses["G2"] == pytest.approx(0.0)  # 基準より良く見えても 0 クランプ

    def test_all_shallow_falls_back(self):
        infos = [{"move": "C3", "scoreLead": 0.0, "visits": 3}]
        replies, best = enigma9_reply_table(infos, "W")
        assert best == "C3"
        assert len(replies) == 1

    def test_empty(self):
        assert enigma9_reply_table([], "W") == ([], None)


class TestExpectedPunish:
    def test_weighted_mean(self):
        replies = [
            {"gtp": "C3", "loss": 0.0, "visits": 300},
            {"gtp": "D4", "loss": 4.0, "visits": 100},
        ]
        hp = {"C3": 0.1, "D4": 0.3}.get
        e, cov = enigma9_expected_punish(replies, lambda g: hp(g, 0.0))
        assert cov == pytest.approx(0.4)
        assert e == pytest.approx((0.1 * 0.0 + 0.3 * 4.0) / 0.4)

    def test_punish_cap(self):
        replies = [{"gtp": "D4", "loss": 50.0, "visits": 100}]
        e, cov = enigma9_expected_punish(replies, lambda g: 1.0)
        assert e == pytest.approx(ENIGMA9_PUNISH_CAP)

    def test_zero_coverage(self):
        replies = [{"gtp": "D4", "loss": 3.0, "visits": 100}]
        assert enigma9_expected_punish(replies, lambda g: 0.0) == (0.0, 0.0)


class TestReplyFindability:
    def test_max_hp_among_adequate(self):
        replies = [
            {"gtp": "C3", "loss": 0.0, "visits": 300},   # 十分・hp 0.02
            {"gtp": "D4", "loss": 0.2, "visits": 100},   # 十分・hp 0.4 -> これが見つけやすさ
            {"gtp": "E5", "loss": 5.0, "visits": 100},   # 不十分・hp 0.9 は無関係
        ]
        hp = {"C3": 0.02, "D4": 0.4, "E5": 0.9}
        assert enigma9_reply_findability(replies, lambda g: hp[g]) == pytest.approx(0.4)

    def test_only_hard_reply(self):
        replies = [
            {"gtp": "C3", "loss": 0.0, "visits": 300},
            {"gtp": "E5", "loss": 5.0, "visits": 100},
        ]
        hp = {"C3": 0.01, "E5": 0.9}
        # 唯一の十分な応手 C3 は hp 0.01 = 人間には見えない
        assert enigma9_reply_findability(replies, lambda g: hp[g]) == pytest.approx(0.01)


class TestRarity:
    def test_book_and_above_is_zero(self):
        assert enigma9_rarity(ENIGMA9_HP_BOOK) == 0.0
        assert enigma9_rarity(0.9) == 0.0

    def test_zero_hp_is_one(self):
        assert enigma9_rarity(0.0) == 1.0

    def test_linear_between(self):
        assert enigma9_rarity(ENIGMA9_HP_BOOK / 2) == pytest.approx(0.5)

    def test_none_is_zero(self):
        assert enigma9_rarity(None) == 0.0

    def test_negative_clamped(self):
        assert enigma9_rarity(-1.0) == 1.0


class TestNetScore:
    def test_composition(self):
        # E=2.0, findability=0 (rare=1), own_hp=book (rare=0), loss=0.5
        net = enigma9_net_score(0.5, 2.0, 0.0, ENIGMA9_HP_BOOK)
        assert net == pytest.approx(2.0 + 1.0 + 0.0 - 0.5)

    def test_negative_loss_clamped(self):
        # 最善手の relativePointsLost は負になりうるが加点はしない
        assert enigma9_net_score(-0.3, 0.0, 1.0, 1.0) == pytest.approx(0.0)

    def test_cost_weight_discounts_loss(self):
        # 勝勢の消費モード: 損失 4.0 が cost_weight 0.25 で 1.0 に割り引かれる
        net = enigma9_net_score(4.0, 2.0, 0.0, ENIGMA9_HP_BOOK, cost_weight=0.25)
        assert net == pytest.approx(2.0 + 1.0 + 0.0 - 1.0)

    def test_cost_weight_default_is_full(self):
        assert enigma9_net_score(4.0, 2.0, 0.0, ENIGMA9_HP_BOOK) == pytest.approx(-1.0)


class TestSpendingPlan:
    def test_no_lead_keeps_base(self):
        assert enigma9_spending_plan(None, 2.0, 1.2, 5.0) == (1.2, 1.0, None)

    def test_losing_keeps_base(self):
        cap, cw, budget = enigma9_spending_plan(-3.0, 2.0, 1.2, 5.0)
        assert (cap, cw) == (1.2, 1.0)
        assert budget == pytest.approx(-5.0)

    def test_small_lead_keeps_base(self):
        # budget = 3.0 - 2.0 = 1.0 <= max_loss 1.2 -> 通常モード
        cap, cw, budget = enigma9_spending_plan(3.0, 2.0, 1.2, 5.0)
        assert (cap, cw) == (1.2, 1.0)
        assert budget == pytest.approx(1.0)

    def test_big_lead_relaxes_to_large_cap(self):
        # budget = 30 - 2 = 28 -> cap は large_cap で頭打ち、cost_weight = 1.2/28
        cap, cw, budget = enigma9_spending_plan(30.0, 2.0, 1.2, 5.0)
        assert cap == pytest.approx(5.0)
        assert cw == pytest.approx(1.2 / 28.0)
        assert budget == pytest.approx(28.0)

    def test_moderate_lead_caps_at_budget(self):
        # budget = 5 - 2 = 3 < large_cap 5 -> cap は budget（1手で目標差を割らない）
        cap, cw, budget = enigma9_spending_plan(5.0, 2.0, 1.2, 5.0)
        assert cap == pytest.approx(3.0)
        assert cw == pytest.approx(0.4)

    def test_cost_weight_continuous_at_boundary(self):
        # budget が max_loss と一致する境界で cw は 1.0 へ連続接続する
        # （浮動小数で 3.2-2.0 は 1.2000…2 になるため厳密比較はしない）
        cap, cw, _ = enigma9_spending_plan(3.2, 2.0, 1.2, 5.0)
        assert cap == pytest.approx(1.2)
        assert cw == pytest.approx(1.0)
        cap2, cw2, _ = enigma9_spending_plan(3.21, 2.0, 1.2, 5.0)
        assert cap2 == pytest.approx(1.21, abs=1e-6)
        assert cw2 == pytest.approx(1.2 / 1.21)

    def test_misconfigured_large_cap_never_below_base(self):
        # large_cap < max_loss の誤設定でも cap は max_loss を下回らない
        cap, cw, _ = enigma9_spending_plan(30.0, 2.0, 1.5, 1.0)
        assert cap == pytest.approx(1.5)

    def test_zero_max_loss_keeps_base(self):
        assert enigma9_spending_plan(30.0, 2.0, 0.0, 5.0) == (0.0, 1.0, 28.0)


class TestChoose:
    def entry(self, gtp, net, loss=0.5):
        return {"gtp": gtp, "net": net, "loss": loss}

    def test_deviates_when_challenger_wins(self):
        scored = [self.entry("E5", 1.0, loss=0.0), self.entry("C3", 1.5)]
        chosen = enigma9_choose(scored, "E5", margin=0.0)
        assert chosen["gtp"] == "C3"

    def test_tie_deviates_at_zero_margin(self):
        scored = [self.entry("E5", 1.0, loss=0.0), self.entry("C3", 1.0)]
        assert enigma9_choose(scored, "E5", margin=0.0)["gtp"] == "C3"

    def test_margin_blocks_marginal_challenger(self):
        scored = [self.entry("E5", 1.0, loss=0.0), self.entry("C3", 1.2)]
        assert enigma9_choose(scored, "E5", margin=0.3) is None

    def test_no_best_entry_fails_safe(self):
        assert enigma9_choose([self.entry("C3", 5.0)], "E5", margin=0.0) is None

    def test_no_challengers(self):
        assert enigma9_choose([self.entry("E5", 1.0)], "E5", margin=0.0) is None

    def test_challenger_tie_prefers_cheaper(self):
        scored = [
            self.entry("E5", 0.0, loss=0.0),
            self.entry("C3", 2.0, loss=0.8),
            self.entry("D4", 2.0, loss=0.3),
        ]
        assert enigma9_choose(scored, "E5", margin=0.0)["gtp"] == "D4"


class TestStrategyRegistration:
    def test_registered(self):
        from katrain.core.ai import STRATEGY_REGISTRY
        from katrain.core.constants import AI_ENIGMA_9

        assert STRATEGY_REGISTRY[AI_ENIGMA_9] is Enigma9Strategy

    def test_enigma13_registered(self):
        from katrain.core.ai import STRATEGY_REGISTRY
        from katrain.core.constants import AI_ENIGMA_13

        assert STRATEGY_REGISTRY[AI_ENIGMA_13] is Enigma13Strategy
        assert issubclass(Enigma13Strategy, Enigma9Strategy)

    def test_enigma19_registered(self):
        from katrain.core.ai import STRATEGY_REGISTRY
        from katrain.core.constants import AI_ENIGMA_19

        assert STRATEGY_REGISTRY[AI_ENIGMA_19] is Enigma19Strategy
        assert issubclass(Enigma19Strategy, Enigma9Strategy)


class TestBoardSizeParametrization:
    """13/19路版は Enigma9Strategy の盤サイズ・設定キー・既定値の差し替えだけであること。"""

    def test_class_attributes(self):
        assert (Enigma9Strategy.BOARD_LEN, Enigma9Strategy.KEY_PREFIX) == (9, "enigma9")
        assert (Enigma13Strategy.BOARD_LEN, Enigma13Strategy.KEY_PREFIX) == (13, "enigma13")
        assert (Enigma19Strategy.BOARD_LEN, Enigma19Strategy.KEY_PREFIX) == (19, "enigma19")
        assert len({Enigma9Strategy.LABEL, Enigma13Strategy.LABEL, Enigma19Strategy.LABEL}) == 3

    def test_same_setting_suffixes(self):
        # 片方にだけ設定を足すと GUI と SETTING_DEFAULTS がずれるのでキー集合を揃える
        assert set(Enigma13Strategy.SETTING_DEFAULTS) == set(Enigma9Strategy.SETTING_DEFAULTS)
        assert set(Enigma19Strategy.SETTING_DEFAULTS) == set(Enigma9Strategy.SETTING_DEFAULTS)

    def test_generate_move_not_overridden(self):
        # 選択パイプラインは共通（サブクラスは既定値の差し替えのみ）
        assert Enigma13Strategy.generate_move is Enigma9Strategy.generate_move
        assert Enigma19Strategy.generate_move is Enigma9Strategy.generate_move


class TestGuiConfigConsistency:
    """SETTING_DEFAULTS・AI_OPTION_VALUES（スライダー候補値）・パッケージ config.json の整合。"""

    @pytest.mark.parametrize(
        "cls,ai_key",
        [
            (Enigma9Strategy, "ai:enigma9"),
            (Enigma13Strategy, "ai:enigma13"),
            (Enigma19Strategy, "ai:enigma19"),
        ],
    )
    def test_defaults_in_gui_options_and_package_config(self, cls, ai_key):
        from katrain.core.constants import AI_OPTION_ORDER, AI_OPTION_VALUES

        config_path = Path(katrain.__file__).parent / "config.json"
        with open(config_path, encoding="utf-8") as f:
            package_ai_conf = json.load(f)["ai"][ai_key]

        expected_keys = {f"{cls.KEY_PREFIX}_{suffix}" for suffix in cls.SETTING_DEFAULTS}
        assert set(package_ai_conf) == expected_keys

        for suffix, default in cls.SETTING_DEFAULTS.items():
            key = f"{cls.KEY_PREFIX}_{suffix}"
            assert package_ai_conf[key] == default, key
            assert key in AI_OPTION_ORDER, key
            # 既定値がスライダー候補値に含まれていること（(値, ラベル) 形式も許容）
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]
            assert default in plain, key


class _RecordingEngine:
    """terminate_queries の呼び出しだけ記録する疑似エンジン。"""

    def __init__(self):
        self.terminated = []

    def terminate_queries(self, only_for_node=None):
        self.terminated.append(only_for_node)


def _strategy_stub(players_info=None, next_player="W", **game_attrs):
    import types

    katrain = types.SimpleNamespace(log=lambda *a, **k: None)
    if players_info is not None:
        katrain.players_info = players_info
    node = types.SimpleNamespace(next_player=next_player)
    game = types.SimpleNamespace(katrain=katrain, current_node=node, **game_attrs)
    return Enigma13Strategy(game, {})


def _player(player_type):
    import types

    return types.SimpleNamespace(player_type=player_type)


class TestPonderGating:
    """着手後先読み（NN キャッシュ温め）は 自分=AI・相手=人間 のときだけ発火する。"""

    def test_applies_only_when_ai_vs_human(self):
        from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN

        s = _strategy_stub({"W": _player(PLAYER_AI), "B": _player(PLAYER_HUMAN)})
        assert s._ponder_applies() is True
        # デバッグスタブ／バッチ評価は両者 human → 発火しない
        s = _strategy_stub({"W": _player(PLAYER_HUMAN), "B": _player(PLAYER_HUMAN)})
        assert s._ponder_applies() is False
        # AI 同士 → エンジンが遊んでいないので発火しない
        s = _strategy_stub({"W": _player(PLAYER_AI), "B": _player(PLAYER_AI)})
        assert s._ponder_applies() is False

    def test_no_players_info_is_off(self):
        assert _strategy_stub(players_info=None)._ponder_applies() is False

    def test_start_ponder_without_probe_is_noop(self):
        # プローブ結果が無い経路（moveInfos なし）ではスレッドすら起こさない
        from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN

        s = _strategy_stub({"W": _player(PLAYER_AI), "B": _player(PLAYER_HUMAN)})
        s._start_ponder("C3", None, "W")
        s._start_ponder("C3", {"clean": {}}, "W")  # 例外なく無視されること


class TestCancelPonder:
    """先読み残骸の掃除（Game.play の相手着手フックと generate 冒頭の保険）。"""

    def test_game_play_hook_cancels_only_on_opponent_move(self):
        import types

        from katrain.core.game import Game

        eng = _RecordingEngine()
        game = types.SimpleNamespace(
            _enigma_ponder=(eng, ["n1", "n2"]), _enigma_ponder_owner="W"
        )
        # 発行者（W）自身の着手では打ち切らない
        Game._cancel_enigma_ponder(game, types.SimpleNamespace(player="W"))
        assert game._enigma_ponder is not None
        assert eng.terminated == []
        # 相手（B）の着手で打ち切り、gen を進める
        Game._cancel_enigma_ponder(game, types.SimpleNamespace(player="B"))
        assert game._enigma_ponder is None
        assert game._enigma_ponder_owner is None
        assert game._enigma_ponder_gen == 1
        assert eng.terminated == ["n1", "n2"]

    def test_game_play_hook_bumps_gen_even_before_worker_fired(self):
        # 相手の応手がワーカーの sim 構築より速いレース: state 未設定でも
        # gen を進めておけば、遅れて発行したワーカー側が gen 不一致で自己回収する
        import types

        from katrain.core.game import Game

        game = types.SimpleNamespace(_enigma_ponder_owner="W")
        Game._cancel_enigma_ponder(game, types.SimpleNamespace(player="B"))
        assert game._enigma_ponder_owner is None
        assert game._enigma_ponder_gen == 1

    def test_game_play_hook_noop_without_owner(self):
        import types

        from katrain.core.game import Game

        game = types.SimpleNamespace()
        Game._cancel_enigma_ponder(game, types.SimpleNamespace(player="B"))  # no raise
        assert getattr(game, "_enigma_ponder_gen", 0) == 0

    def test_strategy_cancel_terminates_and_bumps_generation(self):
        eng = _RecordingEngine()
        s = _strategy_stub(
            players_info=None,
            _enigma_ponder=(eng, ["n"]),
            _enigma_ponder_owner="W",
        )
        s._cancel_ponder()
        assert s.game._enigma_ponder is None
        assert s.game._enigma_ponder_owner is None
        assert eng.terminated == ["n"]
        assert s.game._enigma_ponder_gen == 1
        # 2回目は状態なし＝gen だけ進む
        s._cancel_ponder()
        assert s.game._enigma_ponder_gen == 2
