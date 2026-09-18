"""AI設定画面の説明欄（katrain/gui/ai_help.py）のテスト。

説明欄は「戦略の概要」のあとに、設定画面の表示順どおり
「■ 英語キー（日本語名）［既定 X］: 解説」を並べる。画面の項目名は英語キーのままなので、
説明文の側に英語キーを必ず出して、どのスライダーの解説か分かるようにする。
"""

import gettext
import json
import os
import re

os.environ.setdefault("KIVY_NO_ARGS", "1")

import pytest

from katrain.core.constants import AI_KEY_PROPERTIES, AI_OPTION_ORDER, AI_STRATEGIES_RECOMMENDED_ORDER
from katrain.core.utils import find_package_resource
from katrain.gui import ai_help

NBSP = "\u00a0"


def _translator(table):
    """gettext と同じく、訳が無ければ msgid をそのまま返す"""
    return lambda msgid: table.get(msgid, msgid)


def _jp():
    locale_dir = os.path.join(os.path.dirname(find_package_resource("katrain/i18n/__init__.py")), "locales")
    return gettext.translation("katrain", locale_dir, languages=["jp"]).gettext


def _package_ai_config():
    with open(find_package_resource("katrain/config.json"), encoding="utf-8") as f:
        return json.load(f)["ai"]


STRATEGIES_WITH_SETTINGS = sorted(s for s, v in _package_ai_config().items() if isinstance(v, dict) and v)


class TestCjkWrapFriendly:
    def test_spaces_next_to_japanese_become_non_breaking(self):
        out = ai_help.cjk_wrap_friendly("難解の net = E（9段 の")
        assert " " not in out
        assert out.count(NBSP) == 4

    def test_english_words_glued_to_japanese_are_not_break_points(self):
        """英語の途中で切ると、続く日本語の長い塊が丸ごと次の行へ送られて行が不揃いになる"""
        out = ai_help.cjk_wrap_friendly("一般設定の wide root noise を上げる")
        assert " " not in out
        out = ai_help.cjk_wrap_friendly("ヨセは Human-like 9段へ委譲し")
        assert f"Human-like{NBSP}9段" in out

    def test_spaces_in_a_purely_english_line_stay_breakable(self):
        out = ai_help.cjk_wrap_friendly("日本語の説明\nwide root noise\nです")
        assert "wide root noise" in out

    def test_text_without_cjk_is_unchanged(self):
        text = "Picks moves, according to: a model = 1 [b]x[/b]."
        assert ai_help.cjk_wrap_friendly(text) == text

    def test_newlines_are_kept(self):
        assert ai_help.cjk_wrap_friendly("概要\n\n■ 項目") == f"概要\n\n■{NBSP}項目"


class TestDisplayOrder:
    def test_matches_the_settings_grid_order(self):
        settings = {k: 0 for k in ["zzz", "endgame", "pick_frac", "kyu_rank", "pick_override", "aaa"]}
        expected = sorted(settings, key=lambda k: (k not in AI_KEY_PROPERTIES, AI_OPTION_ORDER.get(k, 99), k))
        assert ai_help.ai_option_display_order(settings) == expected
        assert ai_help.ai_option_display_order(settings)[:2] == ["pick_frac", "kyu_rank"]


class TestHelpEntry:
    def test_first_line_is_the_name_and_the_rest_is_the_explanation(self):
        t = _translator({"aiopt:strength": "損に対する厳しさ\n1 でほぼ最善手。\n0 で弱い。"})
        assert ai_help.ai_option_help_entry("ai:scoreloss", "strength", t) == (
            "損に対する厳しさ",
            "1 でほぼ最善手。\n0 で弱い。",
        )

    def test_strategy_specific_entry_wins_over_the_shared_one(self):
        t = _translator({"aiopt:ai:p:tenuki/stddev": "遠さ\n遠くへ", "aiopt:stddev": "近さ\n近くへ"})
        assert ai_help.ai_option_help_entry("ai:p:tenuki", "stddev", t) == ("遠さ", "遠くへ")
        assert ai_help.ai_option_help_entry("ai:p:local", "stddev", t) == ("近さ", "近くへ")

    def test_enigma_family_text_gets_the_real_key_prefix(self):
        t = _translator({"aiopt:enigma*_endgame_move": "ヨセ切替手数\n{p}_unsettled_max との AND"})
        assert ai_help.ai_option_help_entry("ai:enigma13plus", "enigma13plus_endgame_move", t) == (
            "ヨセ切替手数",
            "enigma13plus_unsettled_max との AND",
        )
        assert ai_help.ai_option_help_entry("ai:enigma9", "enigma9_endgame_move", t)[1] == (
            "enigma9_unsettled_max との AND"
        )

    def test_board_specific_entry_beats_the_family_text(self):
        t = _translator({"aiopt:enigma*_max_loss": "共通\nA", "aiopt:enigma9_max_loss": "9路\nB"})
        assert ai_help.ai_option_help_entry("ai:enigma9", "enigma9_max_loss", t) == ("9路", "B")
        assert ai_help.ai_option_help_entry("ai:enigma13", "enigma13_max_loss", t) == ("共通", "A")

    def test_missing_translation_returns_none(self):
        assert ai_help.ai_option_help_entry("ai:human", "modern_style", _translator({})) is None


class TestFormatValue:
    def test_bool(self):
        assert ai_help.format_ai_option_value("enigma9_aim_jigo", False, _translator({})) == "OFF"
        assert ai_help.format_ai_option_value("tie_ko_screen", True, _translator({})) == "ON"

    def test_labelled_candidates_use_the_slider_label(self):
        t = _translator({})
        assert ai_help.format_ai_option_value("enigma13_min_winrate", 0.3, t) == "30%"
        assert ai_help.format_ai_option_value("enigma13_locality_stddev", 0.0, t) == "OFF"
        assert ai_help.format_ai_option_value("enigma13_overdraft_answered_max", 99.0, t) == "MAX"

    def test_label_with_translated_part(self):
        t = _translator({"strength:dan": "段", "strength:kyu": "級"})
        assert ai_help.format_ai_option_value("human_kyu_rank", -8, t) == "9段"
        assert ai_help.format_ai_option_value("kyu_rank", 4.0, t) == "4級"

    def test_plain_numbers(self):
        t = _translator({})
        assert ai_help.format_ai_option_value("enigma13_max_loss", 1.5, t) == "1.5"
        assert ai_help.format_ai_option_value("opening_moves", 22.0, t) == "22"
        assert ai_help.format_ai_option_value("gain_verify_visits", 800, t) == "800"
        assert ai_help.format_ai_option_value("ko_escape_min_prior", 0.001, t) == "0.001"


UI = {
    "ai option help header": "【各項目】（画面の上から順）",
    "ai option item": "■ {key}（{name}）［既定 {default}］: {body}",
    "ai option item nodefault": "■ {key}（{name}）: {body}",
}


class TestCompose:
    def test_items_in_display_order_with_english_key_japanese_name_and_default(self):
        t = _translator(
            {
                **UI,
                "aihelp:foo": "概要です。",
                "aiopt:zeta": "名前Z\n解説Z",
                "aiopt:pick_frac": "候補の割合\n解説P",
            }
        )
        out = ai_help.compose_ai_help("ai:foo", {"zeta": 1.5, "pick_frac": 0.35}, t, defaults={"zeta": 2.0})
        plain = out.replace(NBSP, " ")
        assert plain.startswith("概要です。\n\n【各項目】（画面の上から順）\n")
        assert plain.index("pick_frac") < plain.index("zeta")  # AI_KEY_PROPERTIES が先
        assert f"■ [b][color={ai_help.KEY_COLOR}]zeta[/color][/b]（名前Z）［既定 2］: 解説Z" in plain
        # 同梱の既定値が無い項目は既定を書かない
        assert f"■ [b][color={ai_help.KEY_COLOR}]pick_frac[/color][/b]（候補の割合）: 解説P" in plain

    def test_only_the_space_between_heading_and_explanation_can_break(self):
        """見出し（英語キー〜既定値）は途中で改行させず、解説との間だけ改行できる＝英語キーと日本語名が離れない"""
        t = _translator({**UI, "aihelp:foo": "概要", "aiopt:zeta": "名前Z\n1 手で 2 目"})
        out = ai_help.compose_ai_help("ai:foo", {"zeta": 1}, t, defaults={"zeta": 2.0})
        item = out.split("\n")[-1]
        assert item.count(" ") == 1
        assert f"［既定{NBSP}2］: 1{NBSP}手で{NBSP}2{NBSP}目" in item

    def test_markup_characters_in_texts_are_escaped(self):
        t = _translator({**UI, "aihelp:foo": "[9路] & 概要", "aiopt:zeta": "名[前]\n[b]解説[/b]"})
        out = ai_help.compose_ai_help("ai:foo", {"zeta": 1}, t, defaults={}).replace(NBSP, " ")
        assert out.startswith("&bl;9路&br; &amp; 概要")
        assert "（名&bl;前&br;）: &bl;b&br;解説&bl;/b&br;" in out

    def test_items_without_translation_are_skipped(self):
        t = _translator({**UI, "aihelp:foo": "概要", "aiopt:zeta": "名前\n解説"})
        out = ai_help.compose_ai_help("ai:foo", {"zeta": 1, "unknown_key": 2}, t, defaults={})
        assert "unknown_key" not in out

    def test_tips_follow_the_item_list(self):
        t = _translator(
            {**UI, "aihelp:foo": "概要", "aiopt:zeta": "名前\n解説", "aihelptips:foo": "【こんなときは】\n・a"}
        )
        out = ai_help.compose_ai_help("ai:foo", {"zeta": 1}, t, defaults={})
        assert out.endswith("解説\n\n【こんなときは】\n・a")

    def test_language_without_item_entries_shows_the_overview_only(self):
        t = _translator({"aihelp:foo": "Overview."})
        assert ai_help.compose_ai_help("ai:foo", {"zeta": 1}, t, defaults={"zeta": 1}) == "Overview."


class TestJapaneseCoverage:
    """同梱 config.json の全戦略の全項目に、日本語の名前と解説があること（新しい設定を足したら解説も足す）"""

    @pytest.mark.parametrize("strategy", STRATEGIES_WITH_SETTINGS)
    def test_every_setting_has_a_japanese_name_and_explanation(self, strategy):
        t = _jp()
        settings = _package_ai_config()[strategy]
        missing = [k for k in settings if ai_help.ai_option_help_entry(strategy, k, t) is None]
        assert not missing, f"{strategy}: 説明欄に解説が無い項目 {missing}（aiopt:<key> を jp の .po に足す）"
        for k in settings:
            name, body = ai_help.ai_option_help_entry(strategy, k, t)
            assert name and body, f"{strategy}/{k}: 名前か解説が空"
            assert "{p}" not in name + body, f"{strategy}/{k}: 難解系の {{p}} が置換されていない"

    @pytest.mark.parametrize("strategy", STRATEGIES_WITH_SETTINGS)
    def test_referenced_sibling_keys_exist_in_the_same_strategy(self, strategy):
        """解説文中で名指しする項目（enigma13plus_… 等）がその戦略に実在すること＝難解系の共通文面が
        ＋版だけの項目を無印に書いてしまう等の取り違えを捕まえる"""
        t = _jp()
        settings = _package_ai_config()[strategy]
        ref_pattern = re.compile(r"\b(?:enigma(?:9|13|19)(?:plus)?|mimic13|parity9|jigo9)_[a-z0-9_]*[a-z0-9]")
        for k in settings:
            entry = ai_help.ai_option_help_entry(strategy, k, t)
            if entry is None:
                continue  # 解説の欠落は上のテストが報告する
            name, body = entry
            for ref in ref_pattern.findall(name + body):
                assert ref in settings, f"{strategy}/{k}: 解説が存在しない項目 {ref} を指している"

    def test_every_listed_strategy_has_a_japanese_name_and_overview(self):
        t = _jp()
        for strategy in AI_STRATEGIES_RECOMMENDED_ORDER:
            assert t(strategy) != strategy, f"{strategy} の戦略名が未翻訳"
            help_id = strategy.replace("ai:", "aihelp:")
            assert t(help_id) != help_id, f"{help_id} が未翻訳"

    def test_ui_strings_are_translated(self):
        t = _jp()
        for msgid in list(UI) + ["ai help hint", "ai help title", "close help"]:
            assert t(msgid) != msgid, f"{msgid} が未翻訳"
        assert "{key}" in t("ai option item") and "{name}" in t("ai option item")
