import pytest

from katrain.core.ai import tsumego_ko_win_node
from katrain.core.game import BaseGame, KaTrainSGF, Move

# 5路のコウ形。黒 C3 は単独で呼吸点1（B3）になり、白 B3 で取られ、黒の C3 取り返しがコウで禁じられる
#    A B C D E
#  4 . B W . .
#  3 B . . W .
#  2 . B W . .
KO_SGF = "(;GM[1]FF[4]SZ[5]KM[0]RU[chinese]PL[B]AB[ac][bb][bd]AW[cb][cd][dc])"


class _KaTrainStub:
    def config(self, key, default=None):
        return {"game/rules": "chinese"}.get(key, default)

    def log(self, *args, **kwargs):
        pass


def _game(sgf=KO_SGF):
    return BaseGame(katrain=_KaTrainStub(), move_tree=KaTrainSGF.parse_sgf(sgf))


def _replay(node):
    sim = _game()
    for path_node in node.nodes_from_root[1:]:
        sim.play(path_node.move, ignore_ko=True)
    return sim


def _stone_at(game, gtp):
    x, y = Move.from_gtp(gtp).coords
    chain_id = game.board[y][x]
    return None if chain_id < 0 else game.chains[chain_id][0].player


def test_ko_win_node_returns_position_after_the_attacker_retakes():
    # 詰碁ではコウダテがあるものとして正解が決まるので、コウの手は「攻め方がコウに勝った
    # 局面」で評価する。返るノードでは攻め方が取り返しており、守り側の石は消えている
    game = _game()
    node = tsumego_ko_win_node(game, game.current_node, Move.from_gtp("C3", player="B"))
    assert node is not None
    sim = _replay(node)
    assert _stone_at(sim, "C3") == "B"  # 攻め方が取り返している
    assert _stone_at(sim, "B3") is None  # 守り側の取り石は消えている
    assert node.next_player == "W"  # 手番は守り側（通常の候補手評価と偶奇が揃う）


def test_ko_win_node_is_none_without_a_ko():
    # コウにならない普通の手では None（＝通常どおりスコアで評価する）
    game = _game()
    assert tsumego_ko_win_node(game, game.current_node, Move.from_gtp("E5", player="B")) is None


def test_ko_win_node_is_none_when_not_short_of_liberties():
    # 呼吸点が複数ある手はコウの形にならない
    game = _game()
    assert tsumego_ko_win_node(game, game.current_node, Move.from_gtp("A1", player="B")) is None


def test_ko_win_node_does_not_touch_the_real_game():
    # 本譜のツリーを汚さない（汚すと SGF に読み筋が残り、AIの着手判定にも影響する）
    game = _game()
    before_children = len(game.current_node.children)
    before_board = [row[:] for row in game.board]
    tsumego_ko_win_node(game, game.current_node, Move.from_gtp("C3", player="B"))
    assert len(game.current_node.children) == before_children
    assert game.board == before_board


def test_ko_win_node_is_none_for_an_illegal_move():
    game = _game()
    assert tsumego_ko_win_node(game, game.current_node, Move.from_gtp("B4", player="B")) is None


# 打った石とは「別の1子」が取られてコウになる形。生きる詰碁ではこちらが普通に出る。
# 黒 E5 は自身は安全だが、既にアタリの黒 C3 を白 B3 が取ると、黒の C3 取り返しがコウになる
#    A B C D E
#  4 . B W . .
#  3 B . B W .
#  2 . B W . .
OTHER_STONE_KO_SGF = "(;GM[1]FF[4]SZ[5]KM[0]RU[chinese]PL[B]AB[ac][bb][bd][cc]AW[cb][cd][dc])"


def test_ko_win_node_detects_a_ko_on_another_stone_than_the_move():
    # 生きる詰碁のコウ（打った石ではなく別の自石が取られてコウになる）も拾う
    game = _game(OTHER_STONE_KO_SGF)
    node = tsumego_ko_win_node(game, game.current_node, Move.from_gtp("E5", player="B"))
    assert node is not None
    sim = BaseGame(katrain=_KaTrainStub(), move_tree=KaTrainSGF.parse_sgf(OTHER_STONE_KO_SGF))
    for path_node in node.nodes_from_root[1:]:
        sim.play(path_node.move, ignore_ko=True)
    assert _stone_at(sim, "E5") == "B"  # 打った手はそのまま残る
    assert _stone_at(sim, "C3") == "B"  # 取られた1子を取り返している
    assert _stone_at(sim, "B3") is None  # 守り側の取り石は消えている
    assert node.next_player == "W"
