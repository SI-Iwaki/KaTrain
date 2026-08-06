"""AI設定ポップアップ（ConfigAIPopup）のGridLayout行数計算のリグレッションテスト。

設定項目数が `max_options` を超える戦略（例: ローカル config に項目が追加された
`ai:p:fighting`）を AI 選択スピナーで選ぶと、GridLayout の
`on_children` チェックに引っかかり
`GridLayoutException: Too many children in GridLayout` でクラッシュしていた。
"""

import json
import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import pytest


def test_rows_never_below_setting_count():
    from katrain.gui.popups import ai_options_grid_rows

    # 項目数が基準行数を超える場合は項目数まで拡張する
    assert ai_options_grid_rows(18, 17) == 18
    assert ai_options_grid_rows(25, 17) == 25
    # 少ない場合は基準行数を維持（レイアウトを詰めない）
    assert ai_options_grid_rows(5, 17) == 17
    assert ai_options_grid_rows(17, 17) == 17


def test_grid_accepts_all_widgets_for_oversized_strategy():
    """max_options を超える項目数でも add_widget が例外を投げないこと。"""
    pytest.importorskip("kivy")
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.widget import Widget

    from katrain.gui.popups import ai_options_grid_rows

    num_settings = 18  # ai:p:fighting にキーを1つ追加した状態
    min_rows = 17
    grid = GridLayout(cols=2, rows=ai_options_grid_rows(num_settings, min_rows))
    for _ in range(num_settings * 2):  # 修正前はここで GridLayoutException
        grid.add_widget(Widget())
    assert len(grid.children) == num_settings * 2


def test_all_packaged_strategies_fit_in_grid():
    """同梱 config.json の全戦略がグリッドに収まること。"""
    from katrain.core.utils import find_package_resource
    from katrain.gui.popups import ConfigAIPopup, ai_options_grid_rows

    min_rows = ConfigAIPopup.max_options.defaultvalue
    with open(find_package_resource("katrain/config.json"), encoding="utf-8") as f:
        ai_config = json.load(f)["ai"]
    for strategy, settings in ai_config.items():
        if not isinstance(settings, dict):
            continue
        rows = ai_options_grid_rows(len(settings), min_rows)
        assert rows * 2 >= len(settings) * 2, f"{strategy} does not fit in the options grid"


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


def _build_headless_slider():
    """アプリを run() せずに LabelledSelectionSlider を1つ組み立てる。

    MDTextField が `MDApp.get_running_app().theme_cls` を要求するので、
    App._running_app を手で差し込む（GUI ループは起動しない）。
    """
    pytest.importorskip("kivy")
    pytest.importorskip("kivymd")
    from kivy.app import App
    from kivy.lang import Builder
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
