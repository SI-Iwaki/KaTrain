import pytest

from katrain.core.ai import (
    tsumego_candidate_reaches_region_ko,
    tsumego_defender_ko_points,
    tsumego_ko_win_node,
    tsumego_pv_reaches_region_ko,
)
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


# --- PV のコウ経路検出（tsumego_pv_reaches_region_ko） ---
# 実測 case K (2026-07-30): gain・目数とも同着の A12（コウで殺す）と C13（無条件に殺す）は
# スコアでは区別できないが、リージョン限定の子局面解析では守り方の最善応手 A11 の PV に
# コウ形の1子取り（B11）が現れる（3/3 run 安定）。PV を盤上で並べ直し、リージョン内で
# 「1子取り・取った石が呼吸点1・取り返しがコウで禁止」の形に到達するかを構造判定する。
#
# 5路の取るコウ形。黒 C2 で白 B2 を1子取りし、取った C2 自身が呼吸点1（B2）になる
#    A B C D E
#  3 B W . . .
#  2 . W? -> 黒C2で取り B W(C3/C1/D2)が囲む
#  1 . B W . .
CAPTURE_KO_SGF = "(;GM[1]FF[4]SZ[5]KM[0]RU[chinese]PL[B]AB[ad][be][bc]AW[bd][ce][cc][dd])"
WHOLE_BOARD = [0, 4, 0, 4]


def test_pv_ko_detects_a_capture_ko_inside_the_region():
    game = _game(CAPTURE_KO_SGF)
    assert tsumego_pv_reaches_region_ko(game, "B", ["C2"], WHOLE_BOARD)


def test_pv_ko_ignores_a_ko_outside_the_region():
    # 枠格子の中で偶発的に出るコウ形（実測 case K probe: ply7 の L5）を拾わないための
    # リージョン制限。コウ点がリージョン外なら数えない
    game = _game(CAPTURE_KO_SGF)
    assert not tsumego_pv_reaches_region_ko(game, "B", ["C2"], [3, 4, 3, 4])


def test_pv_ko_is_false_for_a_clean_pv():
    game = _game(CAPTURE_KO_SGF)
    assert not tsumego_pv_reaches_region_ko(game, "B", ["E5", "E4"], WHOLE_BOARD)


def test_pv_ko_walks_the_pv_with_alternating_players():
    # コウ取りが PV の途中（3手目）にあっても拾う。手番は PV の並びで交互
    game = _game(CAPTURE_KO_SGF)
    assert tsumego_pv_reaches_region_ko(game, "B", ["E5", "E4", "C2"], WHOLE_BOARD)


def test_pv_ko_is_false_for_an_unplayable_pv():
    # PV が現盤面と食い違う（着手不能）場合は判定不能＝コウ扱いしない
    game = _game(CAPTURE_KO_SGF)
    assert not tsumego_pv_reaches_region_ko(game, "B", ["B2"], WHOLE_BOARD)


def test_pv_ko_stops_at_max_plies():
    game = _game(CAPTURE_KO_SGF)
    assert not tsumego_pv_reaches_region_ko(game, "B", ["E5", "E4", "C2"], WHOLE_BOARD, max_plies=2)


def test_pv_ko_treats_no_region_as_whole_board():
    # 枠なしモード（リージョン無し）では盤全体を対象にする
    game = _game(CAPTURE_KO_SGF)
    assert tsumego_pv_reaches_region_ko(game, "B", ["C2"], None)


def test_candidate_ko_check_includes_the_candidate_itself():
    """コウ検査のシーケンスは応手 PV だけでなく候補手自身から始める。

    実測 case L (2026-07-30): B L5 は白 L6 を1子取りして自身が呼吸点1になる
    「打った瞬間にコウを開始する手」。白は次にコウ禁止で取り返せないため
    応手 PV（L3）にはコウ形が現れず、応手 PV しか歩かない旧実装は L5 を
    「無条件」と誤判定して visits タイブレークで選び不正解になった。
    """
    game = _game(CAPTURE_KO_SGF)
    # 候補 C2 自身がコウ形の1子取り（応手 PV が空でも検出する）
    assert tsumego_candidate_reaches_region_ko(game, game.current_node, "C2", [], WHOLE_BOARD)


def test_candidate_ko_check_still_walks_the_reply_pv():
    # 候補自身は clean でも応手 PV の途中のコウ形（case K の A11→B11）は従来どおり拾う
    game = _game(CAPTURE_KO_SGF)
    assert tsumego_candidate_reaches_region_ko(game, game.current_node, "E5", ["E4", "C2"], WHOLE_BOARD)


def test_candidate_ko_check_is_false_for_a_clean_line():
    game = _game(CAPTURE_KO_SGF)
    assert not tsumego_candidate_reaches_region_ko(game, game.current_node, "E5", ["E4", "D5"], WHOLE_BOARD)


# --- 守り方が「今すぐ打てるコウ取り」を得たかの検出（tsumego_defender_ko_points） ---
# 実測 case U (2026-07-31): 白のコウ抵抗は「コウダテの打てないリージョン解析では守り方の損」と
# 読まれるため、KataGo はどの応手 PV でもそのコウを**打たない**。PV がコウを打つことを要求する
# 既存判定では証拠が出ないので、歩きの途中で「守り方がコウ取りを打てる状態になったか」を見る。
#
# 5路。黒 B1 は単独で呼吸点2（A1/C1）。白 A1 でアタリにし、次に白 C1 で B1 を1子取ると
# C1 自身が呼吸点1（B1）になり黒の取り返しがコウで禁じられる＝白は2手でコウを作れる
#    A B C D E
#  2 . W B . .
#  1 . B . B .
AVAIL_KO_SGF = "(;GM[1]FF[4]SZ[5]KM[0]RU[chinese]PL[B]AB[be][cd][de]AW[bd])"


def test_defender_ko_points_lists_immediately_playable_kos():
    # 白は A1 で黒 B1 を1子取れ、取った A1 は呼吸点1で黒の取り返しがコウ禁止
    game = _game(CAPTURE_KO_SGF)
    assert Move.from_gtp("A1").coords in tsumego_defender_ko_points(game, "W", WHOLE_BOARD)


def test_defender_ko_points_is_empty_when_no_ko_is_ready():
    # AVAIL_KO_SGF の黒 B1 は呼吸点2なので、白は**まだ**コウ取りを打てない
    game = _game(AVAIL_KO_SGF)
    assert tsumego_defender_ko_points(game, "W", WHOLE_BOARD) == set()


def test_pv_ko_detects_a_ko_the_defender_gains_but_the_pv_never_plays():
    """PV がコウを打たなくても、守り方がコウ取りを打てる状態になったらコウ経路。

    実測 case U: 黒 A3 の後、白 C1（visits比 0.01・KataGo は白の損と評価）で黒 D1 が
    アタリになり、白 E1 の1子取りがコウになる。どの応手 PV もそのコウを打たないので
    「PV がコウ形に到達するか」だけでは 0/5 run 検出できなかった。
    """
    game = _game(AVAIL_KO_SGF)
    # 白 A1 の後、白は C1 で B1 をコウ取りできる状態になる（PV は C1 を打たない）
    assert tsumego_pv_reaches_region_ko(game, "B", ["E5", "A1", "E4"], WHOLE_BOARD)


def test_pv_ko_ignores_a_ko_the_defender_already_had():
    """候補手より前から打てたコウは候補の性質ではないので数えない。

    局面に元からあるコウ取りを数えると全候補が一律にコウ経路になり、クラス裁定
    （無条件 > コウ）が候補を区別できなくなる（実測 case T の L1 / case F2 の N9 /
    case Q の M13 は着手前から打てるコウで、既存判定が別途拾っている）。
    """
    game = _game(CAPTURE_KO_SGF)
    assert tsumego_defender_ko_points(game, "W", WHOLE_BOARD)  # 元からコウ取りがある局面
    assert not tsumego_pv_reaches_region_ko(game, "B", ["E5", "E4"], WHOLE_BOARD)


def test_pv_ko_ignores_an_available_ko_too_deep_in_the_line():
    """コウ取りの「権利」は PV が実際に打つより弱い証拠なので、歩く深さを短く切る。

    実測 case G2 の正解 C13 / case R の C8 は ply7 でだけコウ取りが立ち（詰碁と無関係な
    偶発コウ）、真陽性は case U ply5・case L/P/F ply3 に収まる（TSUMEGO_KO_AVAIL_PLIES=5）。
    """
    game = _game(AVAIL_KO_SGF)
    assert not tsumego_pv_reaches_region_ko(
        game, "B", ["E5", "E4", "D5", "D4", "C5", "A1", "C4"], WHOLE_BOARD, max_plies=7
    )


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
