"""盤面テーマ切り替え（katrain.gui.theme_manager）のテスト。

この機能の一番壊れやすいところは「巻き戻し」で、`Theme` クラスへの setattr は
従来 起動時の一方向適用しかなかった。切り替えのたびにデフォルトへ完全に戻せないと、
テーマを跨いだ設定が混ざって「default に戻したのに前のテーマが残る」になる。
"""

import json
import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import pytest


@pytest.fixture
def tm():
    from katrain.gui import theme_manager

    theme_manager.apply_theme(theme_manager.THEME_DEFAULT)
    yield theme_manager
    theme_manager.apply_theme(theme_manager.THEME_DEFAULT)


def theme_snapshot():
    from katrain.gui.theme import Theme

    return {k: repr(getattr(Theme, k)) for k in dir(Theme) if k.isupper()}


def test_lists_default_first_then_bundled(tm):
    names = [name for name, _label in tm.list_themes()]
    assert names[0] == tm.THEME_DEFAULT
    assert {"koast", "lizzie", "milos"} <= set(names)
    assert len(names) == len(set(names)), "テーマ名が重複している"


def test_apply_theme_changes_theme_attributes(tm):
    from katrain.gui.theme import Theme

    assert Theme.BOARD_TEXTURE == "board.png"
    tm.apply_theme("milos")
    assert Theme.BOARD_TEXTURE == "kaya.png"
    assert Theme.STONE_MARKS == "none"


def test_applying_default_restores_every_attribute(tm):
    before = theme_snapshot()
    tm.apply_theme("koast")
    assert theme_snapshot() != before, "koast が何も変えていない＝テストが無意味"
    tm.apply_theme(tm.THEME_DEFAULT)
    assert theme_snapshot() == before


def test_switching_between_themes_does_not_leak_keys(tm):
    """milos → koast で milos だけが持つキーが残らないこと。"""
    from katrain.gui.theme import Theme

    default_texture = Theme.BOARD_TEXTURE
    tm.apply_theme("milos")
    assert Theme.BOARD_TEXTURE == "kaya.png"
    tm.apply_theme("koast")
    assert Theme.BOARD_TEXTURE == default_texture


def test_unknown_theme_falls_back_to_default(tm):
    before = theme_snapshot()
    tm.apply_theme("koast")
    assert tm.apply_theme("no-such-theme") == tm.THEME_DEFAULT
    assert theme_snapshot() == before


def test_bundled_theme_json_keys_exist_on_theme(tm):
    """同梱テーマが参照するキーが Theme に実在すること（KaTrain 版差の互換チェック）。"""
    from katrain.gui.theme import Theme

    for name in ("koast", "lizzie", "milos"):
        for path in tm.theme_json_files(tm.theme_dir(name)):
            with open(path, encoding="utf-8") as f:
                for key in json.load(f):
                    assert hasattr(Theme, key), f"{name}: Theme に存在しないキー {key}"


def test_resource_path_follows_selected_theme(tm):
    from kivy.resources import resource_paths

    koast, lizzie = tm.theme_dir("koast"), tm.theme_dir("lizzie")
    tm.apply_theme("koast")
    assert koast in resource_paths and lizzie not in resource_paths
    tm.apply_theme("lizzie")
    assert lizzie in resource_paths and koast not in resource_paths
    tm.apply_theme(tm.THEME_DEFAULT)
    assert koast not in resource_paths and lizzie not in resource_paths


def test_selected_theme_images_win_over_packaged(tm):
    """テーマの board.png がパッケージ同梱より優先されること（探索順とキャッシュ破棄）。"""
    from kivy.resources import resource_find

    tm.apply_theme("koast")
    assert os.path.normpath(resource_find("board.png")).startswith(os.path.normpath(tm.theme_dir("koast")))
    tm.apply_theme(tm.THEME_DEFAULT)
    found = resource_find("board.png")
    assert found is None or not os.path.normpath(found).startswith(os.path.normpath(tm.theme_dir("koast")))


def test_user_themes_directory_is_scanned(tm, tmp_path, monkeypatch):
    user_theme = tmp_path / "themes" / "mytheme"
    user_theme.mkdir(parents=True)
    (user_theme / "theme-mine.json").write_text(json.dumps({"STONE_SIZE": 0.42}), encoding="utf-8")
    monkeypatch.setattr(tm, "user_themes_dir", lambda: str(tmp_path / "themes"))

    from katrain.gui.theme import Theme

    assert "mytheme" in [name for name, _ in tm.list_themes()]
    tm.apply_theme("mytheme")
    assert Theme.STONE_SIZE == 0.42
    tm.apply_theme(tm.THEME_DEFAULT)
    assert Theme.STONE_SIZE != 0.42


def test_user_theme_shadows_bundled_of_same_name(tm, tmp_path, monkeypatch):
    user_theme = tmp_path / "themes" / "koast"
    user_theme.mkdir(parents=True)
    (user_theme / "theme-mine.json").write_text(json.dumps({"STONE_SIZE": 0.11}), encoding="utf-8")
    monkeypatch.setattr(tm, "user_themes_dir", lambda: str(tmp_path / "themes"))

    from katrain.gui.theme import Theme

    assert tm.theme_dir("koast") == str(user_theme)
    tm.apply_theme("koast")
    assert Theme.STONE_SIZE == 0.11


def test_flat_user_json_is_applied_and_rolled_back(tm, tmp_path, monkeypatch):
    """従来からの `~/.katrain/theme*.json` ベタ置きは選択テーマと無関係に効き続ける。"""
    (tmp_path / "theme-tweak.json").write_text(json.dumps({"STARPOINT_SIZE": 0.33}), encoding="utf-8")
    monkeypatch.setattr(tm, "user_data_dir", lambda: str(tmp_path))

    from katrain.gui.theme import Theme

    tm.apply_theme(tm.THEME_DEFAULT)
    assert Theme.STARPOINT_SIZE == 0.33
    tm.apply_theme("koast")
    assert Theme.STARPOINT_SIZE == 0.33

    monkeypatch.undo()
    tm.apply_theme(tm.THEME_DEFAULT)
    assert Theme.STARPOINT_SIZE != 0.33


def test_selected_theme_wins_over_flat_user_json(tm, tmp_path, monkeypatch):
    (tmp_path / "theme-tweak.json").write_text(json.dumps({"STONE_MARKS": "all"}), encoding="utf-8")
    monkeypatch.setattr(tm, "user_data_dir", lambda: str(tmp_path))

    from katrain.gui.theme import Theme

    tm.apply_theme(tm.THEME_DEFAULT)
    assert Theme.STONE_MARKS == "all"
    tm.apply_theme("milos")
    assert Theme.STONE_MARKS == "none", "選択テーマがベタ置きより優先されること"


def test_broken_theme_json_does_not_crash(tm, tmp_path, monkeypatch):
    broken = tmp_path / "themes" / "broken"
    broken.mkdir(parents=True)
    (broken / "theme-broken.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(tm, "user_themes_dir", lambda: str(tmp_path / "themes"))

    before = theme_snapshot()
    assert tm.apply_theme("broken") == "broken"
    assert theme_snapshot() == before


# --- 設定ポップアップとの結線 -------------------------------------------------
# ConfigPopup を実体化すると GL ウィンドウと MDApp が要るので、kv 側は宣言のテキストで、
# Python 側はメソッドをスタブに対して直接呼んで確かめる。


def _popups_kv_source():
    from katrain.core.utils import find_package_resource

    with open(find_package_resource("katrain/popups.kv"), encoding="utf-8") as f:
        return f.read()


def test_popups_kv_declares_board_theme_spinner():
    src = _popups_kv_source()
    assert "board_theme: board_theme" in src, "<ConfigPopup> の id エイリアスが無い"
    assert 'input_property: "general/board_theme"' in src
    assert 'i18n._("general:board_theme")' in src


def test_fill_board_themes_populates_spinner(tm):
    from types import SimpleNamespace

    from katrain.gui.popups import ConfigPopup

    popup = SimpleNamespace(board_theme=SimpleNamespace(value_refs=[]))
    ConfigPopup.fill_board_themes(popup)
    assert popup.board_theme.value_refs == [name for name, _ in tm.list_themes()]
    assert popup.board_theme.value_refs[0] == tm.THEME_DEFAULT


def test_apply_board_theme_applies_and_redraws(tm):
    from types import SimpleNamespace

    from katrain.gui.popups import ConfigPopup
    from katrain.gui.theme import Theme

    redrawn = []
    katrain = SimpleNamespace(
        config=lambda key, default=None: "milos" if key == "general/board_theme" else default,
        log=lambda *a, **kw: None,
        board_gui=SimpleNamespace(redraw_trigger=lambda: redrawn.append(True)),
    )
    ConfigPopup.apply_board_theme(SimpleNamespace(katrain=katrain))
    assert Theme.BOARD_TEXTURE == "kaya.png"
    assert redrawn == [True], "テーマを変えたのに盤が描き直されていない"


def test_config_files_carry_the_setting():
    """GUI は保存済みキーしか表示しないので、両方の config.json に無いと項目が出ない。"""
    import os

    from katrain.core.utils import find_package_resource
    from katrain.gui import theme_manager

    package = find_package_resource("katrain/config.json")
    user = os.path.join(theme_manager.user_data_dir(), "config.json")
    for path in (package, user):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            assert "board_theme" in json.load(f)["general"], f"{path} に general/board_theme が無い"
