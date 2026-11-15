"""観戦バー・対局情報の入力欄（spectate spec §4・§5.4）。Kivy は起動せず、kv / po の文字列と純関数だけを検査する"""

import pathlib
import re

import pytest

from katrain.core.board_spectate import parse_spectate_info_inputs

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEYS = [
    "spectate:auto",
    "spectate:sync-now",
    "spectate:info",
    "spectate:stop",
    "spectate:panel-hide",
    "spectate:panel-show",
    "spectate:info-title",
    "spectate:agehama-b",
    "spectate:agehama-w",
    "spectate:next-player",
]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def block(text, header):
    """header の行から、それより浅いインデントの行が来る手前までのブロック"""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == header)
    indent = len(lines[start]) - len(lines[start].lstrip())
    out = [lines[start]]
    for ln in lines[start + 1 :]:
        if ln.strip() and len(ln) - len(ln.lstrip()) <= indent:
            break
        out.append(ln)
    return "\n".join(out)


def test_spectate_bar_is_static_and_hidden_when_inactive():
    kv = read("katrain/gui.kv")
    bar = block(kv, "SpectateBar:")
    assert "height: dp(58) if root.spectate_active else 0" in bar
    # ボタンは高さとフォントを固定する（未指定だと文字が巨大化して上のパネルへはみ出す＝実機 2026-11-15）
    assert bar.count("size_hint: None, None") == 5 and bar.count("_font_size: sp(13)") == 5
    # 右パネルを畳んで盤を広げるボタン（観戦中だけ効く）と、畳んでいる間の形勢の表示
    assert "root.spectate_panel_hidden = not root.spectate_panel_hidden" in bar and "root.spectate_eval" in bar
    assert kv.count("(root.spectate_active and root.spectate_panel_hidden)") == 2
    assert "opacity: 1 if root.spectate_active else 0" in bar and "disabled: not root.spectate_active" in bar
    assert "root.spectate_text" in bar
    assert "disabled: root.spectate_auto" in bar  # 「今すぐ反映」は自動反映 ON の間は無効
    for msg in ("spectate-toggle-auto", "spectate-sync-now", "spectate-info-popup", "spectate-stop"):
        assert msg in bar
    # バーは TsumegoBookBanner の直前（既存レイアウトの並びを変えない）
    assert kv.index("SpectateBar:") < kv.index("TsumegoBookBanner:\n                            id: tsumego_book_banner")


def test_auto_button_follows_property_not_own_state():
    bar = block(read("katrain/gui.kv"), "SpectateBar:")
    # 行の先頭は「盤を拡大」なので、id で自動反映ボタンのブロックを取る
    auto = bar[bar.index("id: spectate_auto_button") : bar.index("id: spectate_sync_button")]
    assert "root.spectate_auto" in auto and 'root("spectate-toggle-auto")' in auto and "ToggleButton" not in bar


def test_info_popup_layout_in_popups_kv():
    kv = read("katrain/popups.kv")
    pop = block(kv, "<SpectateInfoPopup>:")
    for key in ("spectate:agehama-b", "spectate:agehama-w", "spectate:next-player", "root.confirm()"):
        assert key in pop


@pytest.mark.parametrize("lang", ["jp", "en"])
def test_i18n_keys_exist(lang):
    po = read(f"katrain/i18n/locales/{lang}/LC_MESSAGES/katrain.po")
    for key in KEYS:
        m = re.search(rf'msgid "{re.escape(key)}"\r?\nmsgstr "(.+)"', po)
        assert m, key


def test_i18n_japanese_labels():
    po = read("katrain/i18n/locales/jp/LC_MESSAGES/katrain.po")
    for text in ("自動反映", "今すぐ反映", "対局情報", "終了", "対局情報（観戦）", "黒のアゲハマ", "白のアゲハマ", "次の手番"):
        assert f'msgstr "{text}"' in po


def test_handler_exists_in_main():
    src = read("katrain/__main__.py")
    assert "def _do_spectate_info_popup(self)" in src
    assert "self.spectate_info_popup = None" in src


def test_parse_info_inputs_ok():
    assert parse_spectate_info_inputs("japanese", "6.5", "3", "0", "B") == ("japanese", 6.5, 3, 0, "B")
    assert parse_spectate_info_inputs("chinese", " -0.5 ", " 12 ", "7", "W") == ("chinese", -0.5, 12, 7, "W")


@pytest.mark.parametrize(
    "args",
    [
        ("japanese", "abc", "0", "0", "B"),
        ("japanese", "", "0", "0", "B"),
        ("japanese", "nan", "0", "0", "B"),
        ("japanese", "inf", "0", "0", "B"),
        ("japanese", "6.5", "-1", "0", "B"),
        ("japanese", "6.5", "1.5", "0", "B"),
        ("japanese", "6.5", "0", "", "B"),
        ("japanese", "6.5", "0", "x", "B"),
        ("", "6.5", "0", "0", "B"),
        ("japanese", "6.5", "0", "0", ""),
    ],
)
def test_parse_info_inputs_rejects_invalid(args):
    assert parse_spectate_info_inputs(*args) is None
