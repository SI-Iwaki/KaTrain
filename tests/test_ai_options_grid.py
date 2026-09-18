"""AI設定ポップアップ（ConfigAIPopup）の項目欄のリグレッションテスト。

経緯:
- 項目数が固定行数（旧 `max_options`=17）を超える戦略（`ai:p:fighting` 等）を選ぶと
  `GridLayoutException: Too many children in GridLayout` でクラッシュしていた。
- 行数を項目数まで広げて直したが、固定枠に 20 行以上を詰め込むと 1 行が 16px まで潰れ、
  長いキー名（`enigma13plus_opening_humanstyle_moves`）が 2 行に折り返して上下の行に重なった。
  → 項目欄は行の高さ固定のスクロールリスト（列数だけ指定＝行数の上限なし）にした。
"""

import json
import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import pytest


def test_fighting_loss_threshold_keys_are_configurable():
    """力戦派の損失閾値6キーが GUI ウィジェットと同梱既定値の両方に登録されていること。"""
    from katrain.core.constants import AI_FIGHTING, AI_OPTION_ORDER, AI_OPTION_VALUES
    from katrain.core.utils import find_package_resource

    keys = [
        "fighting_human_opening_max_loss",
        "fighting_human_max_loss",
        "fighting_human_opening_max_loss_9",
        "fighting_human_max_loss_9",
        "complexity_base_max_loss_9",
        "complexity_max_loss_9",
    ]
    with open(find_package_resource("katrain/config.json"), encoding="utf-8") as f:
        fighting = json.load(f)["ai"][AI_FIGHTING]

    for k in keys:
        assert k in AI_OPTION_VALUES, f"{k} が AI_OPTION_VALUES にない（GUI にスライダーが出ない）"
        assert k in AI_OPTION_ORDER, f"{k} が AI_OPTION_ORDER にない（表示順が不定になる）"
        assert k in fighting, f"{k} が同梱 config.json の {AI_FIGHTING} にない"
        assert fighting[k] in AI_OPTION_VALUES[k], f"{k} の既定値 {fighting[k]} がスライダー候補値にない"


def test_fighting_defaults_match_hardcoded_thresholds():
    """同梱既定値が変更前のハードコード値と一致すること（既定なら挙動不変）。"""
    from katrain.core.constants import AI_FIGHTING
    from katrain.core.utils import find_package_resource

    with open(find_package_resource("katrain/config.json"), encoding="utf-8") as f:
        fighting = json.load(f)["ai"][AI_FIGHTING]

    assert fighting["fighting_human_opening_max_loss"] == 2.8
    assert fighting["fighting_human_max_loss"] == 5.6
    assert fighting["fighting_human_opening_max_loss_9"] == 0.5
    assert fighting["fighting_human_max_loss_9"] == 3.3
    assert fighting["complexity_base_max_loss_9"] == 3.3
    assert fighting["complexity_max_loss_9"] == 6.0


def test_loss_cap_sliders_reach_low_values():
    """損失上限のスライダーが引き下げ方向をカバーしていること。

    候補値に無い数値もテキストボックスに直接打てば保存はされるが、そのスライダーを
    一度でも動かすと on_change が最寄りの候補値で上書きしてしまう（実測）。
    引き下げが主目的のパラメータなので、候補値そのものが低い側まで届いている必要がある。
    """
    from katrain.core.constants import AI_OPTION_VALUES

    # complexity の2上限は無条件帯の上限まで下げられないと「互角時は上乗せしない」設定にできない
    for k in ["fighting_human_max_loss", "complexity_base_max_loss", "complexity_max_loss"]:
        assert min(AI_OPTION_VALUES[k]) <= 1.0, f"{k} が 1.0 まで下げられない"
    for k in ["fighting_human_max_loss_9", "complexity_base_max_loss_9"]:
        assert min(AI_OPTION_VALUES[k]) <= 0.5, f"{k} が 0.5 まで下げられない"
    # complexity 側は対応する無条件帯の上限と同じ値を選べること（max() に吸収されない設定が作れる）
    assert set(AI_OPTION_VALUES["fighting_human_max_loss"]) <= set(AI_OPTION_VALUES["complexity_base_max_loss"])
    assert set(AI_OPTION_VALUES["fighting_human_max_loss_9"]) <= set(AI_OPTION_VALUES["complexity_base_max_loss_9"])


def _ensure_headless_app():
    """アプリを run() せずに KaTrain のウィジェットを組み立てられるようにする。

    MDTextField が `MDApp.get_running_app().theme_cls` を要求するので、
    App._running_app を手で差し込む（GUI ループは起動しない）。I18NSpinner は
    アプリの `language` プロパティに bind するので、無ければ足す。
    """
    pytest.importorskip("kivy")
    pytest.importorskip("kivymd")
    from kivy.app import App
    from kivy.lang import Builder
    from kivy.properties import StringProperty
    from kivy.resources import resource_add_path, resource_find
    from kivymd.app import MDApp

    from katrain.core.utils import PATHS, find_package_resource
    from katrain.gui.theme import Theme

    if App.get_running_app() is None:
        app = MDApp()
        App._running_app = app
        app.theme_cls.theme_style = "Dark"
        gui_kv = find_package_resource("katrain/gui.kv")
        resource_add_path(PATHS["PACKAGE"] + "/fonts")
        Theme.DEFAULT_FONT = resource_find(Theme.DEFAULT_FONT) or Theme.DEFAULT_FONT
        Builder.load_file(gui_kv)
        Builder.load_file(find_package_resource("katrain/popups.kv"))
    app = App.get_running_app()
    if "language" not in app.properties():
        app.apply_property(language=StringProperty("en"))


def _build_headless_slider():
    """アプリを run() せずに LabelledSelectionSlider を1つ組み立てる。"""
    _ensure_headless_app()
    from katrain.gui.popups import LabelledSelectionSlider

    return LabelledSelectionSlider(values=[(1.0, "1.0"), (2.0, "2.0")], input_property="x")


def test_slider_value_box_is_vertically_centered():
    """数値ボックスがスライダーと縦中央で揃うこと。

    LabelledFloatInput は `size_hint: 0.5, None`（高さ 53px 固定）なので、
    水平 BoxLayout の既定では行の下端に置かれ、行が縮むほど上へはみ出して
    スライダーとの縦ズレが広がる（実測: 17行で +12.2px / 23行で +16.2px）。
    pos_hint で中央に固定して行の高さから独立させる。
    """
    w = _build_headless_slider()
    assert w.textbox.size_hint_y is None, "前提が変わった: textbox の高さが可変になっている"
    assert w.textbox.pos_hint.get("center_y") == 0.5, "数値ボックスが縦中央に固定されていない"


def _package_ai_config():
    from katrain.core.utils import find_package_resource

    with open(find_package_resource("katrain/config.json"), encoding="utf-8") as f:
        return json.load(f)["ai"]


def _build_headless_ai_popup(strategy, lang="jp"):
    """同梱 config.json の設定で ConfigAIPopup を組み立て、strategy を選んだ状態にする"""
    _ensure_headless_app()
    from katrain.core.lang import i18n
    from katrain.gui.popups import ConfigAIPopup

    class Player:
        pass

    class StubKaTrain:
        _config = {"ai": _package_ai_config()}
        players_info = {"B": Player(), "W": Player()}

        def config(self, path, default=None):
            node = self._config
            for part in path.split("/"):
                node = node.get(part, default) if isinstance(node, dict) else default
            return node

        def log(self, *_args, **_kwargs):
            pass

    for player in StubKaTrain.players_info.values():
        player.strategy = strategy
    previous = i18n.lang
    i18n.switch_lang(lang)
    try:
        popup = ConfigAIPopup(StubKaTrain())
        return popup, popup.help_label.text
    finally:
        i18n.switch_lang(previous)


def test_ai_popup_lists_every_setting_in_a_scrollable_grid():
    """最も項目の多い戦略でも、行数の上限なしのスクロールリストに全項目が1行ずつ並ぶ（詰め込み・空行なし）"""
    from kivy.uix.scrollview import ScrollView

    ai_config = _package_ai_config()
    strategy = max((s for s, v in ai_config.items() if isinstance(v, dict)), key=lambda s: len(ai_config[s]))
    popup, _help = _build_headless_ai_popup(strategy)
    grid = popup.options_grid
    assert grid.cols == 2 and not grid.rows, "行数を固定すると項目数が増えたときに GridLayoutException / 行の潰れが再発する"
    assert grid.row_force_default and grid.row_default_height > 0, "行の高さが固定されていない（詰め込みで文字が重なる）"
    assert len(grid.children) == 2 * len(ai_config[strategy]), "項目名と入力欄が1行ずつ並んでいない"
    assert isinstance(grid.parent, ScrollView), "項目欄がスクロールできない"


def test_ai_popup_help_names_every_setting_by_its_english_key():
    """説明欄の【各項目】に、画面の項目名（英語キー）がすべて並ぶ（どのスライダーの解説か分かる）"""
    ai_config = _package_ai_config()
    for strategy in ["ai:mimic13", "ai:enigma13plus", "ai:tsumego"]:
        _popup, help_text = _build_headless_ai_popup(strategy)
        missing = [k for k in ai_config[strategy] if k not in help_text]
        assert not missing, f"{strategy}: 説明欄に英語キーが無い項目 {missing}"


def test_tsumego_switches_are_checkboxes():
    """詰碁の ON/OFF 項目がチェックボックスで出る（数値欄だと True が float に読めず保存できなかった）"""
    from katrain.gui.popups import LabelledCheckBox, LabelledFloatInput

    popup, _help = _build_headless_ai_popup("ai:tsumego")
    inputs = {}
    for anchor in popup.options_grid.children:
        for child in getattr(anchor, "children", []):
            if isinstance(child, (LabelledCheckBox, LabelledFloatInput)):
                inputs[child.input_property.rsplit("/", 1)[-1]] = child
    for key in ["gain_verify", "ko_win_assumption", "promotion_dominant_requires_success", "tie_ko_screen"]:
        assert isinstance(inputs[key], LabelledCheckBox), f"{key} がチェックボックスになっていない"
