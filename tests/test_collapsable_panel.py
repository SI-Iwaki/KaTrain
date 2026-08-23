"""CollapsablePanel（右パネルのタブ付きパネル）の回帰テスト。

詰碁の自動ループで 1 問ごとにキャプチャが遅くなっていく現象（実測 2026-08-23: 300 問で
1.7 秒→5.7 秒、+12〜16ms/問）の根本原因がここにあった:

- `set_option_state` が `option_active[ix] = ...` を 1 項目ずつ書き、`option_active` が
  `build_options` に bind されていたため、プレイ／解析のモード切替（`load_ui_state`）の
  たびに全タブボタン（KivyMD ボタン）を作り直していた（3 パネル×3 項目×2 回＝1 問あたり
  100 個超）。
- KivyMD のボタンは `__init__` でグローバルな `theme_cls` に bound method を bind する。
  `theme_cls` のプロパティは一度も変わらないので死んだ WeakMethod が掃除されず、Kivy の
  `bind()` は重複チェックのため既存 observer を全部デリファレンスする＝bind 1 回の費用が
  observer 数に比例して伸びる（実測 0.012ms@0 → 6.3ms@20k）。

`set_option_state` はボタンを作り直さず、状態を更新するだけでなければならない。
"""

import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import pytest


@pytest.fixture(scope="module")
def md_app():
    """KivyMD ウィジェットは App.get_running_app().theme_cls を要求するので MDApp を 1 つ作る。"""
    pytest.importorskip("kivy")
    pytest.importorskip("kivymd")
    from kivy.properties import StringProperty
    from kivymd.app import MDApp

    class _App(MDApp):  # CollapsablePanel は app.language（KaTrainApp のプロパティ）に bind する
        language = StringProperty("en")

    app = MDApp.get_running_app() or _App()
    return app


def make_panel():
    from katrain.gui.kivyutils import CollapsablePanel

    return CollapsablePanel(
        options=["score", "winrate", "points"],
        option_colors=[[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]],
        option_active=[True, False, False],
    )


def test_set_option_state_keeps_existing_tab_buttons(md_app):
    panel = make_panel()
    before = list(panel.option_buttons)
    assert len(before) == 3
    panel.set_option_state({"score": False, "winrate": True, "points": True})
    assert [b is a for a, b in zip(before, panel.option_buttons)] == [True, True, True]
    assert panel.option_active == [False, True, True]
    assert [b.state for b in panel.option_buttons] == ["normal", "down", "down"]


def test_set_option_state_does_not_grow_theme_observers(md_app):
    """モード切替のたびに theme_cls の observer が増えない（＝bind の O(n) 劣化を起こさない）。"""
    panel = make_panel()
    theme = md_app.theme_cls

    def n_obs():
        return len(list(theme.get_property_observers("primary_palette")))

    base = n_obs()
    for _ in range(20):
        panel.set_option_state({"score": True, "winrate": False, "points": False})
        panel.set_option_state({"score": False, "winrate": True, "points": True})
    assert n_obs() == base


def test_set_option_state_same_values_is_noop(md_app):
    panel = make_panel()
    before = list(panel.option_buttons)
    panel.set_option_state({"score": True, "winrate": False, "points": False})
    assert [b is a for a, b in zip(before, panel.option_buttons)] == [True, True, True]
    assert panel.option_active == [True, False, False]


def test_option_active_assignment_syncs_buttons(md_app):
    panel = make_panel()
    before = list(panel.option_buttons)
    panel.option_active[2] = True
    assert panel.option_buttons[2] is before[2]
    assert panel.option_buttons[2].state == "down"


def test_kv_style_late_property_assignment_builds_buttons(md_app):
    """kv からの構築では options / option_colors / option_active が __init__ の後に順に届く。

    旧実装は option_active の bind で作り直していたので本数が揃った。同期だけにすると
    ボタンが 0 個のまま trigger_select が on_option_state に空 dict を流し、gui.kv の
    `graph.show_graphs(args[1])` が KeyError で落ちる（実機で確認）。
    """
    from katrain.gui.kivyutils import CollapsablePanel

    panel = CollapsablePanel()
    assert panel.option_buttons == []
    panel.options = ["score", "winrate", "points"]
    panel.option_colors = [[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]]
    panel.option_active = [True, False, True]
    assert len(panel.option_buttons) == 3
    assert [b.state for b in panel.option_buttons] == ["down", "normal", "down"]
    # 以後は同期だけ（作り直さない）
    before = list(panel.option_buttons)
    panel.set_option_state({"score": False})
    assert [b is a for a, b in zip(before, panel.option_buttons)] == [True, True, True]
    assert panel.option_buttons[0].state == "normal"


def test_state_observers_do_not_accumulate_on_rebuild(md_app):
    """本当の作り直し（options 変更・言語切替）でも panel.state の observer は増えない。"""
    panel = make_panel()
    base = len(list(panel.get_property_observers("state")))
    for _ in range(5):
        panel.build_options()
    assert len(list(panel.get_property_observers("state"))) == base
