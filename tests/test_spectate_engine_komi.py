"""観戦モード（spec 2026-11-15-spectate-watch-design.md §5.4）のコミ補正と取り石の下駄。

エンジンに渡すコミ＝root のコミ＋root.engine_komi_offset（画面に出すコミは元のまま）、対局者欄の取り石＝
盤上で取られた石＋Game.capture_base。KataGo も Kivy の画面も起動しない（request_analysis が組んだクエリを
send_query で横取りする）。
"""

import threading
import time

import pytest

from katrain.core.base_katrain import KaTrainBase
from katrain.core.board_spectate import counted_captures, spectate_line, spectate_root, spectate_rules
from katrain.core.engine import BaseEngine, KataGoEngine
from katrain.core.game import Game, KaTrainSGF


class MockKaTrain(KaTrainBase):
    pass


class MockEngine:
    def request_analysis(self, *args, **kwargs):
        pass


class QueryCapturingEngine(KataGoEngine):
    """KataGo を起動せず、request_analysis が組んだクエリ dict を send_query で受け取る"""

    def __init__(self, katrain):
        BaseEngine.__init__(
            self,
            katrain,
            {"_enable_ownership": False, "max_visits": 10, "fast_visits": 5, "wide_root_noise": 0.04, "max_time": 1.0},
        )
        self.override_settings = {"reportAnalysisWinratesAs": "BLACK"}
        self.base_priority = 0
        self.sent = []

    def send_query(self, query, callback, error_callback, next_move=None, node=None):
        self.sent.append(query)


@pytest.fixture
def katrain():
    return MockKaTrain(force_package_config=True, debug_level=0)


@pytest.fixture
def fake_engine_query(katrain):
    return QueryCapturingEngine(katrain)


@pytest.fixture
def make_game(katrain):
    def _make(sgf):
        return Game(katrain, MockEngine(), move_tree=KaTrainSGF.parse_sgf(sgf))

    return _make


def sent_komi(engine, node):
    engine.request_analysis(node, callback=lambda *_args, **_kwargs: None)
    return engine.sent[-1]["komi"]


def g(s):
    return [list(r) for r in s.split("/")]


def tip_of(game):
    node = game.root
    while node.children:
        node = node.children[0]
    return node


G_SMALL = g("...../.B.../...../...W./.....")

# 黒が ca に打って白 2 子（aa・ba）を取り、白が ee に打った 9 路
SGF_WITH_TWO_WHITE_CAPTURED = "(;GM[1]FF[4]SZ[9]KM[6.5]RU[japanese]AB[ab][bb]AW[aa][ba];B[ca];W[ee])"


# --- エンジンに渡すコミ ---


def test_engine_query_uses_offset_komi(fake_engine_query):
    root = KaTrainSGF.parse_sgf("(;GM[1]SZ[9]KM[6.5]RU[japanese])")
    root.engine_komi_offset = -3.0
    assert sent_komi(fake_engine_query, root) == 3.5 and root.komi == 6.5  # 表示のコミは元のまま


def test_engine_query_komi_is_unchanged_without_offset(fake_engine_query):
    # 観戦以外の棋譜（補正の既定 0.0）はこれまでどおり KM そのもの
    root = KaTrainSGF.parse_sgf("(;GM[1]SZ[9]KM[6.5]RU[japanese];B[ee])")
    assert root.engine_komi_offset == 0.0
    assert sent_komi(fake_engine_query, root.children[0]) == 6.5


def test_offset_on_the_root_reaches_queries_for_later_nodes(fake_engine_query):
    root = KaTrainSGF.parse_sgf("(;GM[1]SZ[9]KM[7.5]RU[japanese];B[ee];W[cc])")
    root.engine_komi_offset = 2.0
    assert sent_komi(fake_engine_query, root.children[0].children[0]) == 9.5


def test_first_root_query_already_carries_the_offset(fake_engine_query):
    # 補正は _do_new_game より前に root へ付ける＝最初の解析から効く
    root = spectate_root(G_SMALL, komi=6.5, rules="japanese", next_player="B", agehama_b=3, agehama_w=0)
    assert root.engine_komi_offset == -3.0 and sent_komi(fake_engine_query, root) == 3.5
    assert root.komi == 6.5 and root.get_property("RU") == "japanese" and root.next_player == "B"


def test_new_game_analyses_the_root_at_once_with_the_offset(katrain, fake_engine_query):
    # Game の生成と同時に root の解析が走る（Game.__init__ の analyze_all_nodes）。後から補正を付けても間に合わない
    root = spectate_root(G_SMALL, komi=6.5, rules="japanese", next_player="W", agehama_b=0, agehama_w=2)
    Game(katrain, fake_engine_query, move_tree=root)
    deadline = time.time() + 5
    while not fake_engine_query.sent and time.time() < deadline:
        time.sleep(0.01)
    assert fake_engine_query.sent and fake_engine_query.sent[0]["komi"] == 8.5


@pytest.mark.parametrize(
    "rules, expected",
    [("japanese", -3.0), ("jp", -3.0), ("korean", -3.0), ("chinese", 0.0), ("cn", 0.0), ("aga", 0.0)],
)
def test_root_offset_is_only_for_territory_rules_and_accepts_abbreviations(rules, expected):
    # game/rules や RU は "jp" のような略記でもありうる。読み替えずに渡すと補正が黙って 0 になる
    root = spectate_root(G_SMALL, komi=6.5, rules=rules, next_player="B", agehama_b=3, agehama_w=0)
    assert root.engine_komi_offset == expected


def test_spectate_rules_normalises_like_the_engine():
    assert spectate_rules("jp") == "japanese" and spectate_rules("Chinese") == "chinese"
    assert spectate_rules(None) is None


# --- 取り込み後に数えた取り石 ---


def test_counted_captures_follow_the_tip_not_the_displayed_node(make_game):
    # 末尾までに白 2 子が取られている棋譜で、表示位置を root に戻しても数は変わらない・下駄も混ざらない
    game = make_game(SGF_WITH_TWO_WHITE_CAPTURED)
    game.capture_base = {"B": 0, "W": 3}
    game.set_current_node(game.root)
    assert counted_captures(game.root, tip_of(game)) == {"B": 0, "W": 2}


def test_spectate_line_replays_from_the_root_placement(make_game):
    game = make_game(SGF_WITH_TWO_WHITE_CAPTURED)
    grids, captured = spectate_line(game.root, tip_of(game))
    assert captured == {"B": 0, "W": 2}
    assert len(grids) == 3  # root・黒の取り・白の着手
    assert "".join(grids[0][0][:3]) == "WW." and "".join(grids[0][1][:3]) == "BB."
    assert "".join(grids[1][0][:3]) == "..B"
    assert grids[2][4][4] == "W" and grids[1][4][4] == "."


def test_spectate_line_of_the_root_alone(make_game):
    game = make_game(SGF_WITH_TWO_WHITE_CAPTURED)
    grids, captured = spectate_line(game.root, game.root)
    assert len(grids) == 1 and captured == {"B": 0, "W": 0}


# --- 対局者欄の取り石（prisoner_count）の下駄 ---


def test_prisoner_count_adds_capture_base(make_game):
    game = make_game("(;GM[1]SZ[9]KM[6.5])")
    game.capture_base = {"B": 0, "W": 3}
    assert game.prisoner_count == {"B": 0, "W": 3}


def test_prisoner_count_adds_the_base_to_captures_on_the_board(make_game):
    game = make_game(SGF_WITH_TWO_WHITE_CAPTURED)
    game.capture_base = {"B": 1, "W": 3}
    game.set_current_node(tip_of(game))
    assert game.prisoner_count == {"B": 1, "W": 5}


def test_prisoner_count_is_unchanged_without_a_base(make_game):
    game = make_game(SGF_WITH_TWO_WHITE_CAPTURED)
    game.set_current_node(tip_of(game))
    assert game.capture_base == {"B": 0, "W": 0}
    assert game.prisoner_count == {"B": 0, "W": 2}


def test_capture_base_is_not_shared_between_games(make_game):
    a, b = make_game("(;GM[1]SZ[9])"), make_game("(;GM[1]SZ[9])")
    a.capture_base["W"] = 4
    assert b.capture_base == {"B": 0, "W": 0}


def test_prisoner_count_tolerates_games_built_without_init():
    # いくつかのテストは Game.__new__(Game) で素の Game を作る（BaseGame.__init__ を通らない）
    game = Game.__new__(Game)
    game._lock = threading.RLock()
    game.prisoners = []
    assert game.prisoner_count == {"B": 0, "W": 0}
