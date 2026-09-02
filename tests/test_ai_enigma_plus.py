# tests/test_ai_enigma_plus.py
"""「難解＋」ai:enigma9plus / ai:enigma13plus / ai:enigma19plus の純関数・登録・設定整合テスト（KataGo/Kivy 不要）。

難解（9/13/19路）との差分は `EnigmaPlusMixin` の3フックだけ（spec enigma9 追記12・12-2・12-3）:
- `_shortlist`: 子局面プローブの挑戦者を「安い順 7 手」＋「残りから loss の範囲で等間隔に probe_extra 手」
- `_ponder_wave2_targets`: 先読み wave2 も同じ規則で温める
- `_filter_challengers`: ΔE 床＝E − 最善手の E >= min_delta_e、または vloss <= cheap_loss の挑戦者だけ
既存の enigma9/13/19 は基底フックが従来動作でビット同一。
"""

import json
import types
from pathlib import Path

import pytest

import katrain
from katrain.core.ai import (
    ENIGMA9_CHEAP_LOSS,
    ENIGMA9_MIN_DELTA_E,
    ENIGMA9_PROBE_EXTRA,
    ENIGMA9_SHORTLIST,
    STRATEGY_REGISTRY,
    Enigma9PlusStrategy,
    Enigma9Strategy,
    Enigma13PlusStrategy,
    Enigma13Strategy,
    Enigma19PlusStrategy,
    Enigma19Strategy,
    EnigmaPlusMixin,
    enigma9_delta_e_filter,
    enigma9_shortlist,
    enigma9_shortlist_spread,
    enigma9_wave2_targets,
)
from katrain.core.constants import (
    AI_ENIGMA_9_PLUS,
    AI_ENIGMA_13_PLUS,
    AI_ENIGMA_19_PLUS,
    AI_OPTION_ORDER,
    AI_OPTION_VALUES,
    AI_STRATEGIES,
    AI_STRATEGIES_RECOMMENDED_ORDER,
    AI_STRENGTH,
)

BASES = (Enigma9Strategy, Enigma13Strategy, Enigma19Strategy)
# (Plus クラス, 基底クラス, 設定接頭辞, ai キー, 定数)
PLUS = [
    (Enigma9PlusStrategy, Enigma9Strategy, "enigma9plus", "ai:enigma9plus", AI_ENIGMA_9_PLUS),
    (Enigma13PlusStrategy, Enigma13Strategy, "enigma13plus", "ai:enigma13plus", AI_ENIGMA_13_PLUS),
    (Enigma19PlusStrategy, Enigma19Strategy, "enigma19plus", "ai:enigma19plus", AI_ENIGMA_19_PLUS),
]
PLUS_IDS = [p[2] for p in PLUS]


def entry(gtp, e, loss, net=1.0):
    return {"gtp": gtp, "e": e, "loss": loss, "net": net}


def gtps(entries):
    return [c["gtp"] for c in entries]


def _stub(cls, settings=None):
    katrain_ns = types.SimpleNamespace(log=lambda *a, **k: None)
    node = types.SimpleNamespace(next_player="W")
    game = types.SimpleNamespace(katrain=katrain_ns, current_node=node)
    return cls(game, settings or {})


class TestDeltaEFilter:
    """純関数 enigma9_delta_e_filter(scored, best_gtp, min_delta_e, cheap_loss) -> (kept, dropped)。"""

    def test_keeps_challenger_that_buys_enough_e(self):
        scored = [entry("F6", 3.10, 0.0), entry("D12", 3.40, 0.5)]
        kept, dropped = enigma9_delta_e_filter(scored, "F6", 0.2, 0.3)
        assert gtps(kept) == ["F6", "D12"] and dropped == []

    def test_drops_expensive_challenger_with_low_delta_e(self):
        # 実測 game_20260902_003240（AI=黒）35手目: J5 は vloss 3.48 を払って E 2.65 < 最善 F6 の E 3.10
        scored = [entry("F6", 3.10, 0.0), entry("J5", 2.65, 3.48)]
        kept, dropped = enigma9_delta_e_filter(scored, "F6", 0.2, 0.3)
        assert gtps(kept) == ["F6"] and gtps(dropped) == ["J5"]

    def test_cheap_challenger_is_exempt(self):
        # 序盤の安い外し（同 黒1手目 L4: vloss 0.04・ΔE +0.01）は床を免除して残す
        scored = [entry("K10", 0.04, 0.0), entry("L4", 0.05, 0.04)]
        kept, dropped = enigma9_delta_e_filter(scored, "K10", 0.2, 0.3)
        assert gtps(kept) == ["K10", "L4"] and dropped == []

    def test_negative_vloss_counts_as_cheap(self):
        # 同 黒38手目 E1: 検証済み損失 −0.86（最善手より良い）・ΔE +0.08 → 残す
        scored = [entry("J3", 0.62, 0.0), entry("E1", 0.70, -0.86)]
        kept, _ = enigma9_delta_e_filter(scored, "J3", 0.2, 0.3)
        assert gtps(kept) == ["J3", "E1"]

    def test_boundaries_are_inclusive(self):
        scored = [entry("A1", 1.0, 0.0), entry("B2", 1.2, 2.0), entry("C3", 1.0, 0.3)]
        kept, dropped = enigma9_delta_e_filter(scored, "A1", 0.2, 0.3)
        assert gtps(kept) == ["A1", "B2", "C3"] and dropped == []

    def test_best_entry_is_always_kept(self):
        # 最善手は scored の先頭でなくても残る。D4 は ΔE 0・vloss 5.0 で落ちる
        scored = [entry("D4", 0.0, 5.0), entry("A1", 0.0, 0.0)]
        kept, dropped = enigma9_delta_e_filter(scored, "A1", 0.2, 0.3)
        assert gtps(kept) == ["A1"] and gtps(dropped) == ["D4"]

    def test_floor_zero_disables_filter(self):
        # min_delta_e=0 は OFF＝難解と同一挙動（ΔE が負でも高くても落とさない）
        scored = [entry("A1", 1.0, 0.0), entry("B2", 0.5, 3.0)]
        kept, dropped = enigma9_delta_e_filter(scored, "A1", 0.0, 0.3)
        assert kept == scored and dropped == []

    def test_missing_best_fails_safe(self):
        scored = [entry("B2", 0.5, 3.0)]
        kept, dropped = enigma9_delta_e_filter(scored, "A1", 0.2, 0.3)
        assert kept == scored and dropped == []

    def test_preserves_order(self):
        scored = [entry("B2", 9.0, 3.0), entry("A1", 1.0, 0.0), entry("C3", 1.05, 0.1), entry("D4", 1.05, 1.0)]
        kept, dropped = enigma9_delta_e_filter(scored, "A1", 0.2, 0.3)
        assert gtps(kept) == ["B2", "A1", "C3"] and gtps(dropped) == ["D4"]


class TestFilterHook:
    def test_base_classes_hook_is_identity(self):
        scored = [entry("A1", 1.0, 0.0), entry("B2", 0.5, 3.0)]
        for cls in BASES:
            kept, dropped = _stub(cls)._filter_challengers(scored, "A1")
            assert kept == scored and dropped == [], cls.__name__

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_plus_hook_uses_defaults(self, cls, base, prefix, ai_key, const):
        scored = [entry("F6", 3.10, 0.0), entry("J5", 2.65, 3.48), entry("L4", 3.15, 0.04)]
        kept, dropped = _stub(cls)._filter_challengers(scored, "F6")
        assert gtps(kept) == ["F6", "L4"] and gtps(dropped) == ["J5"]

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_plus_hook_reads_settings(self, cls, base, prefix, ai_key, const):
        scored = [entry("F6", 3.10, 0.0), entry("J5", 3.40, 3.48), entry("L4", 3.15, 0.04)]
        strat = _stub(cls, {f"{prefix}_min_delta_e": 0.5, f"{prefix}_cheap_loss": 0.0})
        kept, dropped = strat._filter_challengers(scored, "F6")
        assert gtps(kept) == ["F6"] and gtps(dropped) == ["J5", "L4"]

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_plus_hook_off_at_zero_floor(self, cls, base, prefix, ai_key, const):
        scored = [entry("F6", 3.10, 0.0), entry("J5", 2.65, 3.48)]
        kept, dropped = _stub(cls, {f"{prefix}_min_delta_e": 0.0})._filter_challengers(scored, "F6")
        assert kept == scored and dropped == []


class TestRegistration:
    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_registered_as_subclass_of_its_base(self, cls, base, prefix, ai_key, const):
        assert STRATEGY_REGISTRY[const] is cls
        assert issubclass(cls, base) and issubclass(cls, EnigmaPlusMixin)
        assert const == ai_key

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_class_attributes(self, cls, base, prefix, ai_key, const):
        assert (cls.BOARD_LEN, cls.KEY_PREFIX) == (base.BOARD_LEN, prefix)
        assert cls.LABEL != base.LABEL

    def test_labels_are_distinct(self):
        labels = {c.LABEL for c in BASES} | {p[0].LABEL for p in PLUS}
        assert len(labels) == 6

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_setting_defaults_extend_the_base(self, cls, base, prefix, ai_key, const):
        plus = cls.SETTING_DEFAULTS
        assert {k: plus[k] for k in base.SETTING_DEFAULTS} == base.SETTING_DEFAULTS
        assert {k: plus[k] for k in plus if k not in base.SETTING_DEFAULTS} == EnigmaPlusMixin.PLUS_DEFAULTS

    def test_plus_default_values(self):
        assert EnigmaPlusMixin.PLUS_DEFAULTS == {
            "min_delta_e": ENIGMA9_MIN_DELTA_E,
            "cheap_loss": ENIGMA9_CHEAP_LOSS,
            "probe_extra": ENIGMA9_PROBE_EXTRA,
        }
        assert (ENIGMA9_MIN_DELTA_E, ENIGMA9_CHEAP_LOSS, ENIGMA9_PROBE_EXTRA) == (0.2, 0.3, 4)

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_generate_move_not_overridden(self, cls, base, prefix, ai_key, const):
        assert cls.generate_move is Enigma9Strategy.generate_move

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_listed_in_strategy_tables(self, cls, base, prefix, ai_key, const):
        assert const in AI_STRATEGIES and const in AI_STRATEGIES_RECOMMENDED_ORDER and const in AI_STRENGTH

    def test_debug_cli_names(self):
        from katrain_debug.runner import STRATEGY_NAME_MAP

        for cls, base, prefix, ai_key, const in PLUS:
            assert STRATEGY_NAME_MAP[prefix] == const


class TestGuiConfigConsistency:
    """SETTING_DEFAULTS・AI_OPTION_VALUES・パッケージ config.json・i18n の整合（test_ai_enigma9 と同じ判定）。"""

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_defaults_in_gui_options_and_package_config(self, cls, base, prefix, ai_key, const):
        config_path = Path(katrain.__file__).parent / "config.json"
        with open(config_path, encoding="utf-8") as f:
            package_ai_conf = json.load(f)["ai"][ai_key]
        expected_keys = {f"{prefix}_{suffix}" for suffix in cls.SETTING_DEFAULTS}
        assert set(package_ai_conf) == expected_keys
        for suffix, default in cls.SETTING_DEFAULTS.items():
            key = f"{prefix}_{suffix}"
            assert package_ai_conf[key] == default, key
            assert key in AI_OPTION_ORDER, key
            if AI_OPTION_VALUES[key] == "bool":
                assert isinstance(default, bool), key
                continue
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[key]]
            assert default in plain, key

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_base_options_are_shared_with_the_base_strategy(self, cls, base, prefix, ai_key, const):
        # 引き継いだ10項目のスライダー候補値は基底戦略と同じ（盤サイズごとの候補値をそのまま使う）
        for suffix in base.SETTING_DEFAULTS:
            assert AI_OPTION_VALUES[f"{prefix}_{suffix}"] == AI_OPTION_VALUES[f"{base.KEY_PREFIX}_{suffix}"], suffix

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_off_values_are_gui_options(self, cls, base, prefix, ai_key, const):
        for suffix in ("min_delta_e", "probe_extra"):
            plain = [v[0] if isinstance(v, tuple) else v for v in AI_OPTION_VALUES[f"{prefix}_{suffix}"]]
            assert 0 in plain, suffix

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_i18n_has_name_and_labels(self, cls, base, prefix, ai_key, const):
        for lang in ("en", "jp"):
            po = (Path(katrain.__file__).parent / "i18n" / "locales" / lang / "LC_MESSAGES" / "katrain.po").read_text(
                encoding="utf-8"
            )
            assert f'msgid "{ai_key}"' in po, lang
            assert f'msgid "aihelp:{prefix}"' in po, lang
            for suffix in cls.SETTING_DEFAULTS:
                assert f'msgid "{prefix}_{suffix}"' in po, (lang, suffix)


def cand(gtp, loss, visits=100):
    return {"gtp": gtp, "loss": loss, "visits": visits}


def _spread_pool():
    # trusted 12 手（loss 0.1〜1.2）＋ shallow 3 手
    trusted = [cand(f"T{i}", round(0.1 * i, 2), visits=50) for i in range(1, 13)]
    shallow = [cand("S1", 0.05, visits=3), cand("S2", 0.5, visits=5), cand("S3", 0.9, visits=1)]
    return trusted + shallow


class TestShortlistSpread:
    """罠探索の拡張: 安い順の base_k 手＋残りを loss の範囲で等間隔に extra 手（spec 追記12-2）。"""

    def test_extra_zero_is_the_legacy_shortlist(self):
        pool = _spread_pool()
        assert enigma9_shortlist_spread(pool, 7, 0) == enigma9_shortlist(pool, 7)

    def test_base_part_is_legacy_and_extras_span_the_expensive_range(self):
        pool = _spread_pool()
        out = enigma9_shortlist_spread(pool, 7, 4)
        assert out[:7] == enigma9_shortlist(pool, 7)
        # 残る trusted は T8〜T12 の5手 → 等間隔4手＝ T8, T9, T11, T12（最安と最高を含む）
        assert gtps(out[7:]) == ["T8", "T9", "T11", "T12"]

    def test_no_duplicates_and_bounded_length(self):
        out = enigma9_shortlist_spread(_spread_pool(), 7, 4)
        assert len(out) == 11 and len({c["gtp"] for c in out}) == 11

    def test_extras_fall_back_to_shallow_by_visits_when_trusted_run_out(self):
        pool = [cand(f"T{i}", round(0.1 * i, 2), visits=50) for i in range(1, 9)]
        pool += [cand("S1", 0.3, visits=3), cand("S2", 0.6, visits=5)]
        out = enigma9_shortlist_spread(pool, 7, 4)
        assert gtps(out[7:]) == ["T8", "S2", "S1"]

    def test_small_pool_returns_everything_once(self):
        out = enigma9_shortlist_spread([cand("A", 0.1), cand("B", 0.2)], 7, 4)
        assert gtps(out) == ["A", "B"]

    def test_single_extra_takes_the_most_expensive(self):
        out = enigma9_shortlist_spread(_spread_pool(), 7, 1)
        assert gtps(out[7:]) == ["T12"]


def info(move, order, score_lead, visits=20):
    return {"move": move, "order": order, "scoreLead": score_lead, "visits": visits}


def _wave2_infos():
    # 黒視点 scoreLead。白番の損失 = scoreLead(候補) − scoreLead(最善) ＝ B2 0.2 … L11 4.0 / M12 8.0 / N13 2.2(shallow)
    return [
        info("A1", 0, -5.0, 300),
        info("B2", 1, -4.8, 120),
        info("C3", 2, -4.5, 80),
        info("D4", 3, -4.2, 60),
        info("E5", 4, -4.0, 40),
        info("F6", 5, -3.8, 30),
        info("G7", 6, -3.5, 25),
        info("H8", 7, -3.0, 20),
        info("J9", 8, -2.5, 15),
        info("K10", 9, -2.0, 12),
        info("L11", 10, -1.0, 10),
        info("M12", 11, 3.0, 10),
        info("pass", 12, 0.0, 5),
        info("N13", 13, -2.8, 2),
    ]


LEGACY_TOP8 = ["A1", "B2", "C3", "D4", "E5", "F6", "G7", "H8"]


class TestWave2Targets:
    """先読み wave2 の温め対象: 従来の visits 上位 k ＋ 予測局面に同じ spread 規則を当てた追加分。"""

    def test_extra_zero_is_the_legacy_top_k_without_pass(self):
        assert enigma9_wave2_targets(_wave2_infos(), "W", 8, 0, None) == LEGACY_TOP8

    def test_no_cap_means_legacy(self):
        assert enigma9_wave2_targets(_wave2_infos(), "W", 8, 4, None) == LEGACY_TOP8

    def test_extras_are_added_within_cap_for_the_mover(self):
        out = enigma9_wave2_targets(_wave2_infos(), "W", 8, 4, 4.0)
        assert out[:8] == LEGACY_TOP8
        # cap 4.0 の挑戦者のうち従来7手（B2〜H8）の残り: trusted J9/K10/L11 → 全部、4手目は shallow N13
        assert out[8:] == ["J9", "K10", "L11", "N13"]
        assert len(out) == len(set(out))

    def test_cap_excludes_expensive_and_pass(self):
        out = enigma9_wave2_targets(_wave2_infos(), "W", 8, 4, 3.0)
        assert "pass" not in out and "M12" not in out and "L11" not in out
        assert out[8:] == ["J9", "K10", "N13"]

    def test_black_perspective_mirrors_white(self):
        flipped = [dict(d, scoreLead=-d["scoreLead"]) for d in _wave2_infos()]
        assert enigma9_wave2_targets(flipped, "B", 8, 4, 4.0) == enigma9_wave2_targets(_wave2_infos(), "W", 8, 4, 4.0)


class TestShortlistHooks:
    def test_base_shortlist_hook_is_legacy(self):
        pool = _spread_pool()
        for cls in BASES:
            assert _stub(cls)._shortlist(pool) == enigma9_shortlist(pool, ENIGMA9_SHORTLIST - 1), cls.__name__

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_plus_shortlist_adds_probe_extra(self, cls, base, prefix, ai_key, const):
        pool = _spread_pool()
        assert _stub(cls)._shortlist(pool) == enigma9_shortlist_spread(pool, ENIGMA9_SHORTLIST - 1, 4)
        off = _stub(cls, {f"{prefix}_probe_extra": 0})
        assert off._shortlist(pool) == enigma9_shortlist(pool, ENIGMA9_SHORTLIST - 1)

    def test_base_wave2_hook_is_legacy_top_k(self):
        analysis = {"rootInfo": {"scoreLead": -5.0}, "moveInfos": _wave2_infos()}
        for cls in BASES:
            assert _stub(cls)._ponder_wave2_targets(analysis, "W") == LEGACY_TOP8, cls.__name__

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_plus_wave2_hook_uses_the_spending_cap(self, cls, base, prefix, ai_key, const):
        # 白の lead 8.0 → budget 6.0 > max_loss → cap = min(large_lead_max_loss, 6.0)（enigma9_spending_plan と同じ）
        analysis = {"rootInfo": {"scoreLead": -8.0}, "moveInfos": _wave2_infos()}
        out = _stub(cls)._ponder_wave2_targets(analysis, "W")
        cap = min(
            float(base.SETTING_DEFAULTS["large_lead_max_loss"]), 8.0 - float(base.SETTING_DEFAULTS["target_score"])
        )
        assert out == enigma9_wave2_targets(_wave2_infos(), "W", ENIGMA9_SHORTLIST, 4, cap)
        assert len(out) > 8

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_plus_wave2_hook_even_game_uses_max_loss(self, cls, base, prefix, ai_key, const):
        analysis = {"rootInfo": {"scoreLead": 0.0}, "moveInfos": _wave2_infos()}
        out = _stub(cls)._ponder_wave2_targets(analysis, "W")
        assert out == enigma9_wave2_targets(
            _wave2_infos(), "W", ENIGMA9_SHORTLIST, 4, float(base.SETTING_DEFAULTS["max_loss"])
        )

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_plus_wave2_hook_without_root_lead_is_legacy(self, cls, base, prefix, ai_key, const):
        analysis = {"moveInfos": _wave2_infos()}
        assert _stub(cls)._ponder_wave2_targets(analysis, "W") == LEGACY_TOP8


def _load_enigma9_test_helpers():
    import importlib.util

    path = Path(__file__).with_name("test_ai_enigma9.py")
    spec = importlib.util.spec_from_file_location("_enigma9_test_helpers", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPlusPonderWorker:
    """先読みワーカーが難解＋のフックを通り、追加分（spread）の子局面プローブまで発行すること。"""

    @pytest.mark.parametrize("cls,base,prefix,ai_key,const", PLUS, ids=PLUS_IDS)
    def test_wave2_issues_spread_targets(self, cls, base, prefix, ai_key, const):
        h = _load_enigma9_test_helpers()
        game, engine = h._ponder_game()
        strategy = cls(game, {})
        probe = {
            "clean": {"moveInfos": [{"move": "D5", "visits": 50}]},
            "hp": {"humanPolicy": h._hp_array(9, h._REPLY_HP)},
        }
        strategy._ponder_worker(game.current_node, "E5", probe, "B", 0)
        # 予測局面（白 E4 の後・黒番）の解析: 黒視点 lead 6.0 → budget 4.0 > max_loss → cap = min(large, 4.0) >= 3.6
        gtps_ = ["D5", "F4", "C4", "G5", "E3", "D3", "F6", "C6", "G3", "B5", "H7", "A1"]
        leads = [6.0, 5.6, 5.2, 4.8, 4.4, 4.0, 3.6, 3.2, 2.8, 2.4, 2.0, -2.0]
        analysis = {
            "rootInfo": {"visits": 2000, "scoreLead": 6.0},
            "moveInfos": [
                {"move": g, "order": i, "visits": 50 - i, "scoreLead": s} for i, (g, s) in enumerate(zip(gtps_, leads))
            ],
        }
        h._roots(engine)[0]["callback"](analysis, False)
        wave2 = [r for r in engine.requests if "next_move" in r]
        targets = [r["next_move"].gtp() for r in wave2[0::2]]
        cap = min(
            float(base.SETTING_DEFAULTS["large_lead_max_loss"]), 6.0 - float(base.SETTING_DEFAULTS["target_score"])
        )
        assert targets == enigma9_wave2_targets(analysis["moveInfos"], "B", ENIGMA9_SHORTLIST, 4, cap)
        assert targets[:8] == gtps_[:8] and len(targets) == 11 and "A1" not in targets  # A1 は loss 8 > cap
        assert all(r["next_move"].player == "B" for r in wave2)
