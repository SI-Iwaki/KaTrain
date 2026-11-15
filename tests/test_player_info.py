"""上流 1.20.1 の回帰テスト: 対局者欄は kv の子ができた時点で初期ラベルを描き直す。

`__init__` 中の bind 発火では `subtype_label` がまだ無く `set_label` が素通りするので、
`on_kv_post` で1回呼ばないと名前・段位が次にプロパティが変わるまで出ない。
"""

import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import pytest


def test_player_info_refreshes_its_label_after_kv_build():
    pytest.importorskip("kivymd")
    from katrain.gui.kivyutils import PlayerInfo

    refreshed = []

    class PlayerInfoAfterKv:
        def set_label(self):
            refreshed.append(True)

    PlayerInfo.on_kv_post(PlayerInfoAfterKv(), None)

    assert refreshed == [True]
