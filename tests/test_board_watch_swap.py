"""盤面監視: 表示した候補をアプリで打ったら KaTrain の決定手を差し替える（board-watch spec 追記15）。

守っているのは:
1. `swap_moves` が空なら reconcile は従来とビット同一（差し替えを判定しない）。
2. 「1手前＋候補手」だけでなく「1手前＋候補手＋相手の1手」も同じ候補手の差し替え（早碁では確定前に相手の石が載る）。
3. 候補以外の点は従来どおり mismatch。
4. 監視は確定2周で on_swap を1回だけ呼び、反映されるまで投げ直さない。差し替えた手から元の手へも戻せる。
5. `Game.replace_last_move` は最終手のノードを親から外して打ち直し、非合法なら元に戻す。
"""

import pytest

from katrain.core.board_watch import (
    BoardWatcher,
    WatchSettings,
    WatchState,
    apply_game_watch_flags,
    candidate_swap_enabled,
    reconcile,
    ring_candidates_enabled,
    swap_candidate,
)
from katrain.core.game import BaseGame, Game, GameNode, IllegalMoveException
from katrain.core.sgf_parser import Move


def _grid(rows):
    return [list(r) for r in rows]


PREVIOUS = _grid([".....", ".....", "..W..", ".....", "....."])  # 相手（白）が打った直後
CURRENT = _grid([".....", ".B...", "..W..", ".....", "....."])  # KaTrain の AI（黒）が (1,1) に打った
SWAPPED = _grid([".....", ".....", "..W..", "...B.", "....."])  # アプリでは代わりに候補 (3,3) が打たれた
SWAPPED_REPLY = _grid([".....", ".....", "..W..", "...B.", ".W..."])  # さらに相手がすぐ応じた
OTHER = _grid([".....", ".....", "..W..", ".....", "B...."])  # 候補でない点 (4,0)


def _state(swap_moves=((3, 3),), current=CURRENT, last_move=(1, 1, "B"), previous=PREVIOUS, move_number=7):
    return WatchState(
        current_grid=current,
        last_move=last_move,
        to_play="W",
        to_play_is_human=True,
        ai_can_respond=True,
        move_number=move_number,
        board_size=len(current),
        previous_grid=previous,
        swap_moves=tuple(swap_moves),
    )


def test_reconcile_without_swap_moves_is_unchanged():
    state = _state(swap_moves=())
    assert reconcile(state, SWAPPED).kind == "mismatch"
    assert reconcile(state, PREVIOUS).kind == "ahead"
    assert reconcile(state, CURRENT).kind == "in_sync"


def test_reconcile_swap_when_a_shown_candidate_is_on_the_app_board():
    verdict = reconcile(_state(), SWAPPED)
    assert (verdict.kind, verdict.move) == ("swap", (3, 3))


def test_reconcile_swap_even_when_the_opponent_already_replied():
    verdict = reconcile(_state(), SWAPPED_REPLY)
    assert (verdict.kind, verdict.move) == ("swap", (3, 3))


def test_reconcile_a_point_that_is_not_a_candidate_is_still_a_mismatch():
    assert reconcile(_state(), OTHER).kind == "mismatch"
    assert reconcile(_state(swap_moves=((3, 3), (0, 0))), OTHER).kind == "mismatch"


def test_reconcile_swap_never_overrides_ahead_or_in_sync():
    state = _state(swap_moves=((3, 3), (1, 1)))
    assert reconcile(state, PREVIOUS).kind == "ahead"
    assert reconcile(state, CURRENT).kind == "in_sync"


def test_reconcile_two_extra_stones_after_the_swap_is_a_mismatch():
    two = _grid([".....", ".....", "..W..", "...B.", ".WW.."])
    assert reconcile(_state(), two).kind == "mismatch"


def test_swap_candidate_needs_the_previous_grid():
    assert swap_candidate(_state(previous=None), SWAPPED) is None
    assert swap_candidate(_state(last_move=None), SWAPPED) is None


def test_swap_candidate_handles_a_candidate_that_captures():
    previous = _grid(["WB...", ".....", ".....", ".....", "....."])
    current = _grid(["WB...", ".....", "..B..", ".....", "....."])
    observed = _grid([".B...", "B....", ".....", ".....", "....."])  # (1,0) で白1子を取る
    state = _state(swap_moves=((1, 0),), current=current, last_move=(2, 2, "B"), previous=previous)
    assert swap_candidate(state, observed) == (1, 0)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Harness:
    def __init__(self, with_swap=True):
        self.frames = []
        self.state = None
        self.moves = []
        self.swaps = []
        self.statuses = []
        self.ahead = []
        self.clock = FakeClock()
        self.watcher = BoardWatcher(
            capture_fn=lambda: self.frames.pop(0),
            get_state_fn=lambda: self.state,
            on_move=lambda i, j, color, move_number, size: self.moves.append((i, j, color, move_number)),
            on_status=lambda kind, text: self.statuses.append((kind, text)),
            settings=WatchSettings(stable_frames=2),
            clock=self.clock,
            on_ahead=self.ahead.append,
            on_swap=(lambda *args: self.swaps.append(args)) if with_swap else None,
        )

    def step(self, frame, state=None):
        self.frames.append(frame)
        if state is not None:
            self.state = state
        self.watcher.step()


def test_watcher_fires_one_swap_after_stable_frames_and_polls_fast_meanwhile():
    h = Harness()
    h.step(PREVIOUS, _state())
    assert h.ahead[-1] == (1, 1)  # 決定手の輪が出ている
    h.step(SWAPPED)
    assert h.swaps == [] and h.ahead[-1] is None  # 1周目では確定しない。輪は消す（もう打たれた）
    assert h.watcher.interval_ms == h.watcher.settings.poll_interval_active_ms  # 確定待ちは 50ms 周期
    h.step(SWAPPED)
    assert h.swaps == [(3, 3, "B", 7, 5, (1, 1))]
    h.step(SWAPPED)  # KaTrain 側がまだ差し替えていない＝投げ直さない
    h.step(SWAPPED)
    assert len(h.swaps) == 1 and h.moves == []


def test_watcher_injects_the_opponent_reply_after_the_swap_lands():
    h = Harness()
    h.step(SWAPPED, _state())
    h.step(SWAPPED_REPLY)  # 候補手は同じ＝確定の数え直しにならない
    assert h.swaps == [(3, 3, "B", 7, 5, (1, 1))]
    # KaTrain が差し替えた（最終手が (3,3)・手数は同じ）→ 相手の石は通常の move 判定で入る
    swapped_state = _state(swap_moves=((1, 1),), current=SWAPPED, last_move=(3, 3, "B"))
    h.step(SWAPPED_REPLY, swapped_state)
    h.step(SWAPPED_REPLY)
    assert h.moves == [(4, 1, "W", 7)] and len(h.swaps) == 1


def test_watcher_can_swap_back_to_the_original_move():
    """アプリの仮置き・読み違いで差し替えても、元の決定手を引き継いでいるので同じ規則で戻せる"""
    h = Harness()
    h.step(SWAPPED, _state())
    h.step(SWAPPED)
    swapped_state = _state(swap_moves=((1, 1),), current=SWAPPED, last_move=(3, 3, "B"))
    h.step(CURRENT, swapped_state)  # アプリの盤は結局 (1,1) だった
    h.step(CURRENT)
    assert h.swaps[-1] == (1, 1, "B", 7, 5, (3, 3)) and len(h.swaps) == 2


def test_watcher_warns_and_blocks_a_swap_that_never_lands():
    h = Harness()
    h.step(SWAPPED, _state())
    h.step(SWAPPED)
    h.clock.now += 10.0  # inject_timeout_ms(5000) を超える
    h.step(SWAPPED)
    assert "差し替え" in h.statuses[-1][1]
    h.step(SWAPPED)
    h.step(SWAPPED)
    assert len(h.swaps) == 1  # 同じ局面では投げ直さない


def test_watcher_non_candidate_point_still_warns_as_before():
    h = Harness()
    h.step(OTHER, _state())
    assert h.swaps == [] and h.statuses[-1][1].startswith("盤面の差が1手で説明できません")


def test_watcher_without_on_swap_treats_a_swap_as_mismatch():
    h = Harness(with_swap=False)
    h.step(SWAPPED, _state())
    h.step(SWAPPED)
    assert h.statuses[-1][1].startswith("盤面の差が1手で説明できません")


def test_candidate_flags():
    on = {"highlight_candidates": True, "highlight_color": "cyan"}
    assert ring_candidates_enabled(on) and candidate_swap_enabled(on)
    assert not ring_candidates_enabled({"highlight_candidates": True, "highlight_color": "off"})
    assert not ring_candidates_enabled({}) and not candidate_swap_enabled({})
    assert not candidate_swap_enabled({**on, "candidate_swap": False})


def test_candidates_turn_on_the_human_policy_prefetch_flag():
    class G:
        current_node = None

        def _maybe_ring_hp_prefetch(self, node):
            pass

    game = G()
    apply_game_watch_flags(game, {"highlight_candidates": True})
    assert game.ring_difficulty_active is True
    apply_game_watch_flags(game, {"highlight_candidates": True, "highlight_color": "off"})
    assert game.ring_difficulty_active is False


class FakeEngine:
    def __init__(self):
        self.terminated = []

    def terminate_queries(self, only_for_node=None, lock=True):
        self.terminated.append(only_for_node)


class _PlainPlayGame(Game):
    """`Game.play` の解析発行を通さない（盤と木の操作だけを見る）"""

    def play(self, move, **kwargs):
        return BaseGame.play(self, move, **kwargs)


def _game():
    class K:
        def log(self, *args, **kwargs):
            pass

    base = BaseGame(K(), move_tree=GameNode(properties={"SZ": 9, "RU": "chinese", "KM": 7.0}))
    base.play(Move.from_gtp("E5", player="B"))
    base.play(Move.from_gtp("C3", player="W"))
    base.play(Move.from_gtp("G7", player="B"))
    game = _PlainPlayGame.__new__(_PlainPlayGame)
    game.__dict__.update(base.__dict__)
    engine = FakeEngine()
    game.engines = {"B": engine, "W": engine}
    return game, engine


def test_replace_last_move_removes_the_old_node_and_plays_the_new_one():
    game, engine = _game()
    old = game.current_node
    parent = old.parent
    game._enigma_ponder_owner = "B"  # 置き換える手の応手を温めている先読みは、同じ色の着手でも止める
    game._enigma_ponder_gen = 3
    new = game.replace_last_move(Move.from_gtp("D4", player="B"))
    assert game.current_node is new and new.parent is parent and new.move.gtp() == "D4"
    assert parent.children == [new]  # 打たれなかった手は分岐として残さない
    assert sorted(m.gtp() for m in game.stones) == ["C3", "D4", "E5"]
    assert new.depth == old.depth and new.next_player == "W"
    assert old in engine.terminated
    assert game._enigma_ponder_owner is None and game._enigma_ponder_gen == 4


def test_replace_last_move_restores_the_position_when_the_new_move_is_illegal():
    game, _engine = _game()
    old = game.current_node
    with pytest.raises(IllegalMoveException):
        game.replace_last_move(Move.from_gtp("E5", player="B"))  # 石のある点
    assert game.current_node is old and old.parent.children == [old]
    assert sorted(m.gtp() for m in game.stones) == ["C3", "E5", "G7"]


def test_replace_last_move_refuses_the_wrong_color_and_nodes_with_children():
    game, _engine = _game()
    with pytest.raises(IllegalMoveException):
        game.replace_last_move(Move.from_gtp("D4", player="W"))
    game.set_current_node = lambda node: None
    leaf = game.current_node
    with game._lock:
        game.current_node = leaf.parent
        game._calculate_groups()
    with pytest.raises(IllegalMoveException):
        game.replace_last_move(Move.from_gtp("D4", player="W"))  # 先がある手は置き換えない
    assert leaf.parent.children == [leaf]


def test_candidates_option_is_wired_into_settings_gui_translations_config_and_main():
    """静的検査: 設定画面の「候補」チェック・訳文・同梱 config の既定・本体の配線（どれか欠けると黙って効かない）"""
    import json
    import os

    root = os.path.join(os.path.dirname(__file__), "..", "katrain")
    kv = open(os.path.join(root, "popups.kv"), encoding="utf-8").read()
    assert 'input_property: "board_watch/highlight_candidates"' in kv
    assert 'i18n._("board_watch:highlight_candidates")' in kv
    for locale in ("jp", "en"):
        po = open(os.path.join(root, "i18n", "locales", locale, "LC_MESSAGES", "katrain.po"), encoding="utf-8").read()
        assert 'msgid "board_watch:highlight_candidates"' in po, locale
    pkg = json.load(open(os.path.join(root, "config.json"), encoding="utf-8"))["board_watch"]
    assert pkg["highlight_candidates"] is False and pkg["candidate_swap"] is True
    assert pkg["candidates_max_loss"] == 2.0
    main = open(os.path.join(root, "__main__.py"), encoding="utf-8").read()
    assert "def _do_board_watch_swap(" in main and '"board-watch-swap"' in main
    assert "on_swap=on_swap" in main and "swap_moves=swap_moves" in main
    assert "MarkerSet(" in main and "self.game.replace_last_move(" in main
    ai = open(os.path.join(root, "core", "ai.py"), encoding="utf-8").read()
    assert 'played_node.ai_decision = getattr(strategy, "ring_decision", None)' in ai


# --- 本体（__main__）の配線。Kivy を import せずに、メソッドの本文だけ取り出して偽の self で動かす ---


def _main_method(name):
    import ast
    import os
    import textwrap

    path = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
    src = open(path, encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            ns = {
                "Move": Move,
                "IllegalMoveException": IllegalMoveException,
                "OUTPUT_INFO": 0,
                "BW_STATUS_WARN": "bw-warn",
                "MODE_PLAY": "play",
            }
            exec(textwrap.dedent(ast.get_source_segment(src, node)), ns)
            return ns[name]
    raise AssertionError(name)


class _Info:
    def __init__(self, ai):
        self.ai, self.human = ai, not ai


class _FakeApp:
    """KaTrainGui の代わり。黒が AI・白が人間（アプリの相手）"""

    def __init__(self, game, cfg):
        from types import SimpleNamespace

        self.game = game
        self._config = {"board_watch": cfg}
        self.players_info = {"B": _Info(True), "W": _Info(False)}
        self.play_analyze_mode = "play"
        self.board_gui = SimpleNamespace(animating_pv="x")
        self.logs, self.warnings, self.sounds = [], [], 0

    def log(self, message, level=None):
        self.logs.append(message)

    def _board_watch_status(self, kind, text):
        self.warnings.append(text)

    def _play_stone_sound(self):
        self.sounds += 1


ON = {"highlight_candidates": True, "highlight_color": "cyan"}


def test_main_swap_replaces_the_ai_move_and_carries_the_other_candidates():
    game, _engine = _game()  # 最終手は黒（AI）の G7
    node = game.current_node
    node.watch_swap_auto = frozenset({"D4", "E3"})
    app = _FakeApp(game, ON)
    swap = _main_method("_do_board_watch_swap")
    d4, g7 = Move.from_gtp("D4").coords, Move.from_gtp("G7").coords
    swap(app, d4, "B", node.depth, g7)
    new = game.current_node
    assert new.move.gtp() == "D4" and new.move.player == "B" and new.parent.children == [new]
    assert new.watch_swap_carry == {"G7", "E3"}  # 元の決定手へも、残りの候補へも差し替え直せる
    assert new.ai_decision == {"kind": "swap", "from": "G7", "trap": False}
    assert app.sounds == 1 and any("D4" in m and "G7" in m for m in app.logs) and app.warnings == []
    # 差し替え直し: アプリの盤は結局 G7 だった
    swap(app, g7, "B", new.depth, d4)
    assert game.current_node.move.gtp() == "G7" and game.current_node.watch_swap_carry == {"D4", "E3"}


def test_main_swap_is_dropped_when_the_position_moved_since_the_watcher_looked():
    game, _engine = _game()
    node = game.current_node
    app = _FakeApp(game, ON)
    swap = _main_method("_do_board_watch_swap")
    d4, g7, e5 = (Move.from_gtp(g).coords for g in ("D4", "G7", "E5"))
    swap(app, d4, "B", node.depth + 1, g7)  # 手数が違う
    swap(app, d4, "W", node.depth, g7)  # 色が違う
    swap(app, d4, "B", node.depth, e5)  # 監視が見た最終手と違う
    assert game.current_node is node and len(app.logs) == 3 and all("破棄" in m for m in app.logs)
    swap(app, e5, "B", node.depth, g7)  # 石のある点＝非合法 → 元の局面のまま警告
    assert game.current_node is node and len(app.warnings) == 1


def test_main_state_offers_swap_moves_only_for_an_ai_move_with_the_option_on():
    from katrain.core.board_watch import move_to_grid

    game, _engine = _game()
    game.region_of_interest = None
    node = game.current_node
    node.watch_swap_auto = frozenset({"D4", "E3"})
    state_fn = _main_method("_board_watch_state")
    at = lambda gtp: move_to_grid(Move.from_gtp(gtp).coords, 9)  # noqa: E731
    state = state_fn(_FakeApp(game, ON))
    assert set(state.swap_moves) == {at("D4"), at("E3")} and state.last_move == (*at("G7"), "B")
    assert state.previous_grid is not None  # 差し替えの判定は1手前の盤から作る
    assert state_fn(_FakeApp(game, {})).swap_moves == ()  # 候補の表示が OFF
    assert state_fn(_FakeApp(game, {**ON, "candidate_swap": False})).swap_moves == ()
    human = _FakeApp(game, ON)
    human.players_info = {"B": _Info(False), "W": _Info(True)}  # 最終手が人間側の手
    assert state_fn(human).swap_moves == ()


def test_main_marks_add_thin_rings_with_glyphs_for_the_other_candidates():
    from types import SimpleNamespace

    from katrain.core.board_watch import move_to_grid
    from katrain.core.screen_marker import ring_color

    game, _engine = _game()
    node = game.current_node  # 黒 G7
    hp = [0.0] * 82
    x, y = Move.from_gtp("D4").coords
    hp[(8 - y) * 9 + x] = 0.7
    node.parent.ring_human_policy = hp
    node.parent.analysis["moves"] = {
        "F6": {"move": "F6", "order": 0, "scoreLead": 1.0, "winrate": 0.5, "visits": 900, "pv": ["F6"]},
        "D4": {"move": "D4", "order": 1, "scoreLead": 0.5, "winrate": 0.5, "visits": 200, "pv": ["D4"]},
    }
    node.parent.analysis["root"] = {"scoreLead": 1.0, "winrate": 0.5, "visits": 1100}
    node.ai_decision = {"kind": "gamble", "trap": True}
    reader = SimpleNamespace(screen_point=lambda i, j: (100 + j * 40, 100 + i * 40, 40))
    marks_fn = _main_method("_board_watch_marks")
    at = lambda gtp: move_to_grid(Move.from_gtp(gtp).coords, 9)  # noqa: E731
    point, red = (999, 999, 40), (255, 0, 0)
    app = _FakeApp(game, ON)
    marks = marks_fn(app, ON, reader, at("G7"), point, red)
    cyan = ring_color("cyan")
    f6, d4 = reader.screen_point(*at("F6")), reader.screen_point(*at("D4"))
    assert marks == [(*point, "罠", True, red), (*f6, "最", False, cyan), (*d4, "感", False, cyan)]
    assert node.watch_swap_auto == {"F6", "D4"}
    assert any("候補" in m for m in app.logs)  # 対局ログに1行
    # OFF・人間側の手・輪の指す手が最終手でない → 決定手の輪だけ（今までと同じ）
    assert marks_fn(_FakeApp(game, {}), {}, reader, at("G7"), point, red) == [(*point, "", True, red)]
    human = _FakeApp(game, ON)
    human.players_info = {"B": _Info(False), "W": _Info(True)}
    assert marks_fn(human, ON, reader, at("G7"), point, red) == [(*point, "", True, red)]
    assert marks_fn(app, ON, reader, at("A1"), point, red) == [(*point, "", True, red)]
