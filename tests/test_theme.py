"""上流 1.20.1 の回帰テスト: 手数の数字は石の色と逆の色で描く（橙の単色は白石の上で読めなかった）。"""

from katrain.gui.theme import Theme


def test_move_numbers_contrast_with_the_stone_color():
    assert Theme.MOVE_NUMBER_COLORS == {"B": [1, 1, 1, 1], "W": [0, 0, 0, 1]}
