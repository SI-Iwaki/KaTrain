"""観戦モードの KaTrain 側セッション（katrain/__main__.py の観戦ハンドラ）を Kivy の窓も KataGo も起動せずに動かす。

__main__ は import した時点で Kivy の窓を作るので、KaTrainGui の該当メソッドを AST でソースごと抜き出し、本物の Game
（解析は捨てるエンジン）・偽のアプリ盤・すぐ実行する Clock・その場で走るスレッドを持つスタブに載せて実行する。
監視スレッドは起動せず、SpectateWatcher.step_once / step を手で回す（決定的）。メソッドが新しいグローバル名を使い始めたら
NameError で落ちる＝下の _GLOBALS に足すこと。spec 2026-11-15-spectate-watch-design.md §5.3・§5.4
"""

import ast
import os
import textwrap
import time
from types import SimpleNamespace

import pytest

import katrain.core.board_spectate as board_spectate
import katrain.core.board_watch as board_watch
from katrain.core.base_katrain import KaTrainBase
from katrain.core.board_spectate import SpectateInfo, SpectateWatcher
from katrain.core.board_watch import STATUS_WARN, STATUS_WATCHING, apply_game_watch_flags, clear_game_watch_flags
from katrain.core.constants import (
    AI_DEFAULT,
    MODE_ANALYZE,
    MODE_PLAY,
    OUTPUT_DEBUG,
    OUTPUT_ERROR,
    OUTPUT_INFO,
    PLAYER_AI,
    PLAYER_HUMAN,
    PLAYING_NORMAL,
)
from katrain.core.game import Game, IllegalMoveException
from katrain.core.sgf_parser import Move, ParseError

_MAIN = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
_EXTRA = {"_do_new_game", "_stop_board_watcher", "_board_watch_marker_close", "_board_watch_trigger"}
HUMAN = (PLAYER_HUMAN, PLAYING_NORMAL)
AI = (PLAYER_AI, AI_DEFAULT)


class ImmediateClock:
    @staticmethod
    def schedule_once(fn, _timeout=0):
        fn(0)


class SyncThread:
    """threading.Thread の代わり。start() でその場で走らせる（「今すぐ反映」のワーカーを決定的にする）"""

    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


_GLOBALS = {
    "Clock": ImmediateClock,
    "time": time,
    "threading": SimpleNamespace(Thread=SyncThread),
    "Move": Move,
    "IllegalMoveException": IllegalMoveException,
    "ParseError": ParseError,
    "BW_STATUS_WARN": STATUS_WARN,
    "OUTPUT_INFO": OUTPUT_INFO,
    "OUTPUT_ERROR": OUTPUT_ERROR,
    "OUTPUT_DEBUG": OUTPUT_DEBUG,
    "PLAYER_HUMAN": PLAYER_HUMAN,
    "PLAYING_NORMAL": PLAYING_NORMAL,
    "MODE_PLAY": MODE_PLAY,
    "MODE_ANALYZE": MODE_ANALYZE,
    "Game": Game,
    "apply_game_watch_flags": apply_game_watch_flags,
    "clear_game_watch_flags": clear_game_watch_flags,
}


def _load_methods():
    with open(_MAIN, encoding="utf-8") as f:
        src = f.read()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "KaTrainGui")
    methods = {}
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith(("_spectate", "_do_spectate", "spectate_")) or node.name in _EXTRA:
            namespace = dict(_GLOBALS)
            exec(compile(textwrap.dedent(ast.get_source_segment(src, node)), f"__main__.{node.name}", "exec"), namespace)
            methods[node.name] = namespace[node.name]
    return methods


METHODS = _load_methods()


class MockEngine:
    def __init__(self):
        self.new_games = 0

    def request_analysis(self, *args, **kwargs):
        pass

    def on_new_game(self):
        self.new_games += 1


class FakeReader:
    window_title = "BlueStacks"

    def __init__(self, grid):
        self.grid = grid
        self.size = len(grid)
        self.last_mover = None

    def read(self):
        return [row[:] for row in self.grid]

    def last_mover_color(self):
        return self.last_mover

    def profile_name(self):
        return "quest"

    def window_title_text(self):
        return None

    def player_icon_colors(self):
        return None, None


class Harness(KaTrainBase):
    """KaTrainGui の観戦まわりが触る属性だけを持つスタブ。メッセージは溜めて dispatch() で流す"""

    def __init__(self):
        super().__init__(force_package_config=True, debug_level=0)
        self.engine = MockEngine()
        self.messages, self.banner, self.logs = [], [], []
        self.redraws = 0
        self.play_mode = SimpleNamespace(mode=MODE_PLAY, switch_ui_mode=lambda: None)
        self.board_gui = SimpleNamespace(animating_pv=None, reset_rotation=lambda: None)
        self.controls = SimpleNamespace(
            graph=SimpleNamespace(initialize_from_game=lambda root: None),
            move_tree=SimpleNamespace(redraw=self._count_redraw),
            set_status=lambda *a, **k: None,
        )
        self.tsumego_recording = False
        self._tsumego_flash_event = None
        self._spectate_session = None
        self._spectate_importing = False
        self.spectate_active, self.spectate_auto, self.spectate_text = False, True, ""
        self.tsumego_view = True
        self.board_watch_status = ""
        self.game = Game(self, self.engine)
        self.update_player("B", player_type=PLAYER_AI, player_subtype=AI_DEFAULT)

    def _count_redraw(self):
        self.redraws += 1

    @property
    def play_analyze_mode(self):
        return self.play_mode.mode

    def __getattr__(self, name):
        if name in METHODS:
            return METHODS[name].__get__(self)
        raise AttributeError(name)

    def __call__(self, message, *args, **kwargs):
        self.messages.append((message, args, kwargs))

    def dispatch(self):
        while self.messages:
            message, args, kwargs = self.messages.pop(0)
            if message != "update_state":
                getattr(self, "_do_" + message.replace("-", "_"))(*args, **kwargs)

    def update_state(self, redraw_board=False):
        pass

    def start_game_log(self):
        pass

    def log(self, message, level=OUTPUT_INFO):
        self.logs.append(message)

    def _board_watch_status(self, kind, text):
        self.banner.append((kind, text))

    def players(self):
        return {bw: (p.player_type, p.player_subtype) for bw, p in self.players_info.items()}


def put(grid, *stones):
    grid = [row[:] for row in grid]
    for i, j, c in stones:
        grid[i][j] = c
    return grid


E9 = [["."] * 9 for _ in range(9)]
G0 = put(E9, (2, 2, "B"), (6, 6, "W"), (2, 6, "B"))  # 黒 2・白 1 ＝白番
INFO = SpectateInfo(rules="japanese", komi=6.5, agehama_b=2, agehama_w=0, next_player="W", app_move_number=40)
# 取りのアニメーションの途中: 呼吸点の無い白石が盤に残っている（Game の生成が "Unexpected illegal move" で落ちる）
DEAD = put(E9, (0, 0, "W"), (0, 1, "B"), (1, 0, "B"))


@pytest.fixture(autouse=True)
def no_watcher_threads(monkeypatch):
    # 監視スレッドは起動しない（テストが step_once / step を手で回す）
    monkeypatch.setattr(SpectateWatcher, "start", lambda self: setattr(self, "started", True))


@pytest.fixture
def h():
    return Harness()


def start(h, grid=G0, info=INFO):
    reader = FakeReader(grid)
    h._do_spectate_start(reader, grid, len(grid), info)
    return reader


def app_moves(h, reader, grid, last_mover, once=True):
    """アプリの盤が grid になった周を回してメッセージを流す。once=False は通常周期（確定に stable_frames 周）"""
    reader.grid, reader.last_mover = grid, last_mover
    watcher = h._spectate_session["watcher"]
    if once:
        verdict = watcher.step_once()
    else:
        watcher.step()
        watcher.step()
        verdict = None
    h.dispatch()
    return verdict


# --- 開始・終了 ---


def test_start_switches_players_and_imports_with_the_offset(h):
    start(h)
    s = h._spectate_session
    assert s is not None and h._board_watch_kind == "spectate" and h._board_watcher is s["watcher"]
    assert h.players() == {"B": HUMAN, "W": HUMAN} and s["saved_players"] == {"B": AI, "W": HUMAN}
    assert h.game.root.engine_komi_offset == -2.0 and h.game.root.komi == 6.5 and h.game.root.next_player == "W"
    assert h.game.capture_base == {"W": 2, "B": 0} and h.game.prisoner_count == {"B": 0, "W": 2}
    assert h.spectate_active and h.spectate_auto and not h.tsumego_view
    assert h.spectate_text == "観戦中 40手目  日本ルール コミ6.5  アゲハマ 黒2 白0"
    assert not any(m[0] == "spectate-info-popup" for m in h.messages)


def test_stop_restores_players_and_keeps_the_game_attributes(h):
    start(h)
    root = h.game.root
    h._do_spectate_stop()
    assert h._spectate_session is None and h._board_watcher is None and not h.spectate_active
    assert h.players() == {"B": AI, "W": HUMAN}
    assert h.game.root is root and root.engine_komi_offset == -2.0 and h.game.capture_base == {"W": 2, "B": 0}
    h._do_spectate_stop()  # 2 度目は何もしない
    assert not h.spectate_active


def test_unread_komi_and_turn_fall_back_and_ask(h):
    start(h, info=SpectateInfo())
    assert h.game.root.next_player == "W" and h.game.root.komi == h.config("game/komi")
    assert ("spectate-info-popup", (), {}) in h.messages  # 入力欄（Task 6）の _do_spectate_info_popup がある
    h2 = Harness()
    h2._do_spectate_info_popup = lambda: None
    start(h2, info=SpectateInfo())
    assert ("spectate-info-popup", (), {}) in h2.messages


def test_new_game_and_stop_board_watcher_end_spectating(h):
    start(h)
    h._do_new_game()
    assert h._spectate_session is None and h.players() == {"B": AI, "W": HUMAN}
    h2 = Harness()
    start(h2)
    assert h2._stop_board_watcher() and h2._spectate_session is None and h2.players() == {"B": AI, "W": HUMAN}


# --- 追記 ---


def test_append_follows_the_tip_when_viewing_it(h):
    reader = start(h)
    verdict = app_moves(h, reader, put(G0, (4, 4, "W")), "W")
    s = h._spectate_session
    assert verdict.kind == "moves" and s["tip"].depth == 1 and h.game.current_node is s["tip"]
    assert h.spectate_text.startswith("観戦中 41手目")


def test_append_keeps_the_cursor_while_browsing_and_redraws_the_tree(h):
    reader = start(h)
    app_moves(h, reader, put(G0, (4, 4, "W")), "W")
    h.game.set_current_node(h.game.root)
    redraws = h.redraws
    app_moves(h, reader, put(G0, (4, 4, "W"), (0, 0, "B")), "B")
    assert h._spectate_session["tip"].depth == 2 and h.game.current_node is h.game.root
    assert h.redraws == redraws + 1


def test_estimated_moves_get_the_batch_note(h):
    reader = start(h)
    verdict = app_moves(h, reader, put(G0, (4, 4, "W"), (0, 0, "B")), "B")
    first = h._spectate_session["tip"].parent
    assert verdict.estimated and first.note == "順序は推定（まとめて反映した 2 手）"
    assert h.banner[-1] == (STATUS_WATCHING, "順序は推定（まとめて反映した 2 手）")


def test_captures_after_import_add_to_the_totals(h):
    reader = start(h)
    g = put(G0, (0, 1, "W"))
    app_moves(h, reader, g, "W")
    g = put(g, (0, 0, "B"))
    app_moves(h, reader, g, "B")
    g = put(g, (7, 7, "W"))
    app_moves(h, reader, g, "W")
    g = put(g, (8, 8, "B"))
    app_moves(h, reader, g, "B")
    g = put(g, (1, 0, "W"), (0, 0, "."))  # 白が黒 (0,0) を取る
    verdict = app_moves(h, reader, g, "W")
    assert verdict.kind == "moves" and h._spectate_session["tip"].depth == 5
    assert h.spectate_info_values() == {"rules": "japanese", "komi": 6.5, "agehama_b": 2, "agehama_w": 1, "next_player": "B"}
    assert h.game.prisoner_count == {"B": 1, "W": 2}
    assert "アゲハマ 黒2 白1" in h.spectate_text


def test_stale_appends_and_reimports_are_dropped(h):
    reader = start(h)
    old_root = h.game.root
    app_moves(h, reader, put(E9, (4, 4, "B"), (3, 3, "W")), "W")  # 取り込み直し
    s = h._spectate_session
    assert h.game.root is not old_root and s["tip"] is h.game.root
    h._do_spectate_append(((5, 5, "B"),), 0, False, tip=old_root)
    h._do_spectate_append(((5, 5, "B"),), 3, False)
    assert s["tip"].depth == 0
    root = h.game.root
    h._do_spectate_reimport(put(E9, (1, 1, "B")), "x", SpectateInfo(), tip=old_root)
    h._do_spectate_reimport(put(E9, (4, 4, "B"), (3, 3, "W")), "x", SpectateInfo())  # 末尾と同じ盤
    assert h.game.root is root


def test_deleted_tip_reimports_with_the_exact_turn(h):
    reader = start(h)
    g = put(G0, (5, 5, "W"))
    app_moves(h, reader, g, "W")
    tip = h._spectate_session["tip"]
    tip.parent.children.remove(tip)  # 棋譜ツリーで削除（parent は残る）
    h.game.set_current_node(h.game.root)
    root = h.game.root
    app_moves(h, reader, put(g, (6, 5, "B")), "B")
    assert h.game.root is not root and h.game.root.next_player == "W"
    assert any("本譜の末尾が削除された" in m for m in h.logs)


# --- 取り込み直し・対局情報 ---


def test_reimport_carries_the_totals_and_keeps_the_players(h):
    reader = start(h)
    h._do_spectate_toggle_auto()
    old_root = h.game.root
    verdict = app_moves(h, reader, put(E9, (4, 4, "B"), (3, 3, "W")), "W")
    s = h._spectate_session
    assert verdict.kind == "reimport" and h.game.root is not old_root and h._spectate_session is s
    assert s["agehama_base"] == (2, 0) and h.game.capture_base == {"W": 2, "B": 0}
    assert h.game.root.next_player == "B" and h.game.root.engine_komi_offset == -2.0
    assert "取り込み直しました（アゲハマを確認してください）" in h.banner[-1][1]
    assert s["base_move_number"] is None and h.spectate_text.startswith("観戦中（取り込みから 0 手）")
    assert h.players() == {"B": HUMAN, "W": HUMAN}


def test_info_moves_the_import_time_base_and_reanalyses_only_on_engine_changes(h):
    reader = start(h)
    g = put(G0, (0, 1, "W"))
    for stones, mover in (((0, 0, "B"),), "B"), (((7, 7, "W"),), "W"), (((8, 8, "B"),), "B"):
        g = put(g, *stones)
        app_moves(h, reader, g, mover)
    app_moves(h, reader, put(g, (1, 0, "W"), (0, 0, ".")), "W")  # 取り込み後に白が黒 1 子を取る
    s = h._spectate_session
    n = h.engine.new_games
    h._do_spectate_info("japanese", 6.5, 2, 1, None)  # 何も変わらない
    assert h.engine.new_games == n
    h._do_spectate_info("chinese", 7.5, 3, 1, "W")  # 手順があるので手番の変更は無視
    assert h.game.root.get_property("RU") == "chinese" and h.game.root.komi == 7.5
    assert s["agehama_base"] == (3, 0) and h.game.capture_base == {"W": 3, "B": 0}
    assert h.game.root.engine_komi_offset == 0.0 and h.engine.new_games == n + 1
    h._do_spectate_info("japanese", 6.5, 3, 1, None)
    assert h.game.root.engine_komi_offset == -3.0  # 取り込み時点の分から（累計からではない）


def test_turn_correction_without_moves_reimports(h):
    start(h)
    root = h.game.root
    h._do_spectate_info("japanese", 6.5, 2, 0, "B")
    assert h.game.root is not root and h.game.root.next_player == "B"
    assert h.game.root.engine_komi_offset == -2.0 and h._spectate_session["tip"] is h.game.root


# --- 指摘 2: 挿入モード ---


def test_insert_mode_holds_the_watcher_until_it_ends(h):
    reader = start(h)
    h.game.insert_mode = True
    assert h._spectate_state(h._spectate_session, {}) is None
    assert app_moves(h, reader, put(G0, (4, 4, "W")), "W", once=False) is None
    assert h._spectate_session["tip"].depth == 0 and not h.messages
    h.game.insert_mode = False
    app_moves(h, reader, put(G0, (4, 4, "W")), "W", once=False)  # 挿入モードを抜けたら通常どおり確定する
    assert h._spectate_session["tip"].depth == 1


def test_skip_in_insert_mode_forgets_the_fired_verdict(h):
    reader = start(h)
    reader.grid, reader.last_mover = put(G0, (4, 4, "W")), "W"
    watcher = h._spectate_session["watcher"]
    watcher.step()
    watcher.step()  # 確定して発火（メッセージはまだ流していない）
    h.game.insert_mode = True  # その間にユーザーが挿入モードに入った
    h.dispatch()
    assert h._spectate_session["tip"].depth == 0 and watcher._fired is None
    h.game.insert_mode = False
    app_moves(h, reader, reader.grid, "W", once=False)
    assert h._spectate_session["tip"].depth == 1


# --- 指摘 4: 着手と棋譜ツリーのクリックのすれ違い ---


def test_click_during_append_does_not_attach_the_move_to_the_clicked_node(h):
    reader = start(h)
    app_moves(h, reader, put(G0, (4, 4, "W")), "W")
    s = h._spectate_session
    tip = s["tip"]
    original_play = h.game.play

    def play_after_a_click(move, **kwargs):
        h.game.set_current_node(h.game.root)  # Kivy スレッドで棋譜ツリーがクリックされた
        return original_play(move, **kwargs)

    h.game.play = play_after_a_click
    app_moves(h, reader, put(G0, (4, 4, "W"), (0, 0, "B")), "B")
    assert s["tip"] is tip and h.game.current_node is h.game.root  # 末尾は進めず、ユーザーの表示位置のまま
    assert [c.move.gtp() for c in h.game.root.children] == ["E5"]  # クリックした局面に打っていない
    assert s["watcher"]._fired is None  # 同じ手をもう一度確定させる
    h.game.play = original_play
    app_moves(h, reader, put(G0, (4, 4, "W"), (0, 0, "B")), "B")
    assert s["tip"].depth == 2 and s["tip"].parent is tip


# --- 指摘 5: 非合法の途中失敗 ---


def test_illegal_move_midway_restores_the_cursor_and_keeps_the_tip(h, monkeypatch):
    reader = start(h)
    app_moves(h, reader, put(G0, (4, 4, "W")), "W")
    s = h._spectate_session
    tip = s["tip"]
    h.game.set_current_node(h.game.root)  # 過去の手を検討中
    original_play = h.game.play
    calls = []

    def play_then_illegal(move, **kwargs):
        calls.append(move)
        if len(calls) == 2:
            raise IllegalMoveException("Ko")
        return original_play(move, **kwargs)

    h.game.play = play_then_illegal
    # 取り込み直しも失敗させる＝部分的に足した手が末尾として残らないことを見る
    monkeypatch.setattr(board_spectate, "spectate_root", lambda *a, **k: (_ for _ in ()).throw(ParseError("x")))
    app_moves(h, reader, put(G0, (4, 4, "W"), (0, 0, "B"), (8, 8, "W")), "W")
    assert len(calls) == 2
    assert s["tip"] is tip and h.game.current_node is h.game.root and h._spectate_session is s


# --- 指摘 3: 取り込みの失敗 ---


def test_import_failure_at_start_restores_the_players_and_warns(h):
    old_root = h.game.root
    start(h, grid=DEAD)
    assert h._spectate_session is None and not h.spectate_active
    assert h.players() == {"B": AI, "W": HUMAN} and h.game.root is old_root
    assert h.banner[-1][0] == STATUS_WARN and "局面を取り込めません" in h.banner[-1][1]


def test_import_failure_at_reimport_keeps_the_previous_session(h):
    start(h)
    s = h._spectate_session
    root, tip = h.game.root, s["tip"]
    h._do_spectate_reimport(DEAD, "x", SpectateInfo(agehama_b=9, agehama_w=9, next_player="B", app_move_number=99))
    assert h._spectate_session is s and h.game.root is root and s["tip"] is tip
    assert s["agehama_base"] == (2, 0) and s["base_move_number"] == 40 and h.game.capture_base == {"W": 2, "B": 0}
    assert h.banner[-1][0] == STATUS_WARN and "局面を取り込めません" in h.banner[-1][1]


def test_failed_turn_correction_keeps_the_previous_base(h, monkeypatch):
    start(h)
    s = h._spectate_session
    monkeypatch.setattr(board_spectate, "spectate_root", lambda *a, **k: (_ for _ in ()).throw(ParseError("x")))
    h._do_spectate_info("japanese", 6.5, 5, 0, "B")
    assert s["agehama_base"] == (2, 0) and h.game.root.next_player == "W"


# --- 指摘 1: 新規対局ポップアップ ---


class FakeSetup:
    def __init__(self, player_type, player_subtype):
        self.dump = {"player_type": player_type, "player_subtype": player_subtype}

    @property
    def player_type_dump(self):
        return dict(self.dump)


class FakeSetupBlock:
    """NewGamePopup.player_setup（PlayerSetupBlock）の代わり。update_player_params は同期で欄を書き換える"""

    def __init__(self, black, white):
        self.players = {"B": FakeSetup(*black), "W": FakeSetup(*white)}

    def update_player_params(self, bw, params):
        self.players[bw].dump = dict(params)


def popup_new_game(h, block):
    """NewGamePopup.update_config（新規対局）の順: 終了の口 → 欄を読む → 新規対局 → 欄をもう一度読む"""
    h.spectate_end_for_new_game(block)
    for bw, setup in block.players.items():
        h.update_player(bw, **setup.player_type_dump)
    h._do_new_game()
    for bw, setup in block.players.items():
        h.update_player(bw, **setup.player_type_dump)


def test_new_game_popup_restores_the_players_from_before_spectating(h):
    start(h)
    popup_new_game(h, FakeSetupBlock(HUMAN, HUMAN))  # 欄は観戦中の「人間・人間」を写している
    assert h._spectate_session is None and h.players() == {"B": AI, "W": HUMAN}


def test_new_game_popup_keeps_a_colour_the_user_changed_in_the_popup(h):
    start(h)
    jigo = (PLAYER_AI, "ai:jigo")
    popup_new_game(h, FakeSetupBlock(HUMAN, jigo))
    assert h.players() == {"B": AI, "W": jigo}


def test_new_game_popup_hook_is_inert_without_a_session(h):
    block = FakeSetupBlock(HUMAN, HUMAN)
    h.spectate_end_for_new_game(block)
    assert block.players["B"].dump == {"player_type": PLAYER_HUMAN, "player_subtype": PLAYING_NORMAL}
    assert h.players() == {"B": AI, "W": HUMAN}


# --- 自動反映・今すぐ反映・ホットキー ---


def test_toggle_auto_and_sync_now(h):
    reader = start(h)
    s = h._spectate_session
    first_watcher = s["watcher"]
    h._do_spectate_toggle_auto()
    assert not s["auto"] and not h.spectate_auto and h._board_watcher is first_watcher
    reader.grid, reader.last_mover = put(G0, (4, 4, "W")), "W"
    h._do_spectate_sync_now()  # ワーカーはその場で走る（SyncThread）
    h.dispatch()
    assert s["tip"].depth == 1 and not s["syncing"]
    h._do_spectate_toggle_auto()
    assert s["auto"] and s["watcher"] is not first_watcher and h._board_watcher is s["watcher"]
    h._do_spectate_sync_now()  # 自動反映 ON の間は何もしない
    assert not h.messages


def test_spectate_hotkey_starts_and_stops(h, monkeypatch):
    monkeypatch.setattr(board_watch, "AppBoardReader", lambda title, sizes: FakeReader(G0))
    monkeypatch.setattr(board_spectate, "read_spectate_info", lambda reader: INFO)
    h._spectate_trigger()
    assert [m[0] for m in h.messages] == ["spectate-start"] and h.messages[0][1][3] == INFO
    h.dispatch()
    h._spectate_last_trigger = 0.0
    h._spectate_trigger()
    assert [m[0] for m in h.messages] == ["spectate-stop"]


def test_game_watch_hotkey_ends_spectating_then_starts(h, monkeypatch):
    monkeypatch.setattr(board_watch, "AppBoardReader", lambda title, sizes: FakeReader(G0))
    start(h)
    h.board_watch_status = STATUS_WATCHING  # 観戦のバナーが出ていても「消すだけ」に落ちない
    h._board_watch_trigger()
    assert [m[0] for m in h.messages] == ["spectate-stop", "board-watch-start"]
