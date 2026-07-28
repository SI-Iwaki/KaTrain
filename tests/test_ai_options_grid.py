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
