"""Alt 単独押し（ナビドロワー＝ハンバーガーメニューの開閉）と、Ctrl+Alt+D 等の組み合わせの区別。

グローバルホットキー（RegisterHotKey）はトリガーキー（ctrl+alt+d の d）の WM_KEYDOWN だけを
フォーカス窓から奪い、修飾キーの押下・解放はそのまま KaTrain に届く。Kivy から見えるのは
「Ctrl↓ Alt↓ Alt↑」で、`_single_key_action` の「最後に押したキーが Alt のまま Alt が離された」
判定が Alt 単独押しと誤認してドロワーを開いていた。Ctrl を先に押したときだけ起きる
（Alt を先に押すと最後のキーが Ctrl になり判定を外れる）ので「ときどき」開くように見えた。
"""

import ast
import os

from katrain.core.utils import alt_pressed_alone


def test_alt_tap_alone_is_single_press():
    assert alt_pressed_alone(["alt"])
    assert alt_pressed_alone(["alt", "numlock"])  # ロック系は修飾の組み合わせではない
    assert alt_pressed_alone(["alt", "capslock", "numlock"])
    assert alt_pressed_alone([])


def test_alt_pressed_while_other_modifier_held_is_chord():
    assert not alt_pressed_alone(["ctrl", "alt"])  # ctrl+alt+d / ctrl+alt+a / ctrl+alt+v
    assert not alt_pressed_alone(["ctrl", "shift", "alt"])
    assert not alt_pressed_alone(["shift", "alt"])
    assert not alt_pressed_alone(["meta", "alt"])


def _function_source(tree, source, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} が katrain/__main__.py に見つかりません")


def test_single_key_action_ignores_alt_chords():
    """配線の回帰テスト。__main__.py は Kivy 依存でここから import できないので ast で見る。

    Alt の押下時の修飾キーを `_on_keyboard_down` が覚え、`_single_key_action` がそれを
    `alt_pressed_alone` で判定していること（どちらかが外れるとドロワー誤作動が戻る）。
    """
    main_path = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
    source = open(main_path, encoding="utf-8").read()
    tree = ast.parse(source)
    assert "self.last_key_down_modifiers = modifiers" in _function_source(tree, source, "_on_keyboard_down")
    assert "alt_pressed_alone(self.last_key_down_modifiers)" in _function_source(tree, source, "_single_key_action")
