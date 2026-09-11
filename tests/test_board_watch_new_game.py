"""盤面監視の連続対局（spec 2026-08-18-board-watch-design.md 追記10）。

対局者アイコンから手前（KaTrain の AI）の色を読む・監視を始めるときに AI の色を決める・監視中に
アプリで次の対局が始まったら張り直す、の3つ。Kivy・KataGo 不要。
"""

import ast
import os

import pytest
from PIL import Image

import katrain.core.board_watch as bw
from katrain.core.board_watch import BLACK, WHITE, BoardWatcher, WatchSettings, WatchState

_DATA = os.path.join(os.path.dirname(__file__), "data")
_MAIN = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")


def _image(name):
    return Image.open(os.path.join(_DATA, name))


def _quest_icons(name):
    from katrain.core.tsumego_capture import detect_board

    img = _image(name)
    return bw.player_icon_colors(img, detect_board(img))


# --- 対局者アイコン（実スクショ） ---


def test_icons_read_near_black_on_real_screenshot():
    # 手前（自分）が黒・相手（右上）が白で始まった9路（アプリ AI が白）
    assert _quest_icons("board_watch_start_black.png") == (BLACK, WHITE)


@pytest.mark.parametrize("name", ["board_watch_start_white.png", "board_watch_before.png"])
def test_icons_read_near_white_on_real_screenshots(name):
    # 手前が白・相手が黒。before.png は BlueStacks の枠込み（窓の大きさ・盤の位置が違う）
    assert _quest_icons(name) == (WHITE, BLACK)


def test_wood_board_app_has_no_readable_icons():
    # 木目盤アプリは対局者アイコンを持たない（窓の中は黒い余白＝両方同じ色か読めない）
    from katrain.core.tsumego_capture import detect_wood_board

    img = _image("board_watch_wood9.png")
    near, far = bw.player_icon_colors(img, detect_wood_board(img))
    assert bw.confirmed_near_color(near, far) is None


def test_icon_windows_outside_the_image_are_unreadable():
    # 盤が画像の端いっぱい＝対局者の帯が写っていない
    img = Image.new("RGB", (100, 100), (0, 64, 114))
    assert bw.player_icon_colors(img, (0, 0, 100, 100)) == (None, None)


def test_uniform_background_is_not_a_stone():
    # 窓がまるごと暗い（石ではなく背景）は黒石と読まない＝PLAYER_ICON_MAX_FRACTION
    img = Image.new("RGB", (100, 200), (10, 10, 10))
    assert bw.player_icon_colors(img, (0, 50, 100, 150)) == (None, None)


@pytest.mark.parametrize(
    "near, far, expected",
    [(BLACK, WHITE, BLACK), (WHITE, BLACK, WHITE), (BLACK, BLACK, None), (None, WHITE, None), (WHITE, None, None)],
)
def test_near_color_is_confirmed_only_when_the_two_icons_are_opposite(near, far, expected):
    assert bw.confirmed_near_color(near, far) == expected


# --- AppBoardReader 経由（実スクショを撮影結果として流す） ---


def _reader_on(monkeypatch, img):
    from katrain.core import tsumego_capture as tc

    monkeypatch.setattr(
        bw,
        "_capture_api",
        lambda: (lambda _title: (0, 0) + img.size, lambda _rect: img, tc.detect_board, tc.detect_size_and_classify),
    )
    return bw.AppBoardReader("BlueStacks", [9, 13, 19])


def test_reader_reads_the_near_color_from_the_last_frame(monkeypatch):
    reader = _reader_on(monkeypatch, _image("board_watch_start_black.png"))
    assert reader.near_player_color() is None  # まだ撮っていない
    reader.read()
    assert reader.player_icon_colors() == (BLACK, WHITE)
    assert reader.near_player_color() == BLACK
    reader.read()  # 盤の画素が同じ周（指紋の速い経路）でも読める
    assert reader.near_player_color() == BLACK


def test_reader_gives_no_color_on_the_wood_board_app(monkeypatch):
    reader = _reader_on(monkeypatch, _image("board_watch_wood9.png"))
    reader.read()
    assert reader._profile == "wood"
    assert reader.player_icon_colors() == (None, None)


# --- 監視を始めるときの AI の色 ---


def test_assignment_moves_the_ai_to_the_near_color():
    assert bw.watch_player_assignment(["W"], BLACK)[0] == BLACK
    assert bw.watch_player_assignment(["B"], WHITE)[0] == WHITE


def test_assignment_keeps_the_setting_when_it_already_matches_or_the_icon_is_unreadable():
    assert bw.watch_player_assignment(["B"], BLACK)[0] == BLACK
    assert bw.watch_player_assignment(["W"], None)[0] == WHITE


@pytest.mark.parametrize("ai_colors", [[], ["B", "W"]])
def test_assignment_needs_exactly_one_ai_to_take_the_strategy_from(ai_colors):
    color, reason = bw.watch_player_assignment(ai_colors, BLACK)
    assert color is None
    assert "AI" in reason


# --- 序盤形（「次の対局が始まった」の証拠） ---


def _grid(rows):
    return [list(r) for r in rows]


@pytest.mark.parametrize(
    "rows, expected",
    [
        (["...", "...", "..."], BLACK),  # 空盤
        (["...", ".B.", "..."], WHITE),  # 黒の初手だけ
        (["W..", ".B.", "..."], BLACK),  # 1手ずつ
        (["B..", ".B.", "..."], None),  # 黒2子・白0子＝取りが起きた形
        (["W..", ".B.", "..B"], None),  # 3子以上＝対局の途中
    ],
)
def test_opening_next_player(rows, expected):
    assert bw.opening_next_player(_grid(rows)) == expected


# --- 監視中の「次の対局」検出（BoardWatcher） ---


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Harness:
    def __init__(self, color=BLACK, hooks=True):
        self.frames = []
        self.state = None
        self.color = color
        self.statuses = []
        self.new_games = []
        hook_kwargs = {}
        if hooks:
            hook_kwargs = dict(
                player_color_fn=lambda: self.color,
                on_new_game=lambda grid, size, color: self.new_games.append((grid, size, color)),
            )
        self.watcher = BoardWatcher(
            capture_fn=self._capture,
            get_state_fn=lambda: self.state,
            on_move=lambda *a: None,
            on_status=lambda kind, text: self.statuses.append((kind, text)),
            settings=WatchSettings(),
            clock=FakeClock(),
            **hook_kwargs,
        )

    def _capture(self):
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame

    def step(self, frame, state):
        self.frames.append(frame)
        self.state = state
        self.watcher.step()

    def warned(self):
        return any(kind == bw.STATUS_WARN for kind, _ in self.statuses)


def _state(current, move_number=30, ai_ok=True):
    return WatchState(
        current_grid=current,
        last_move=None,
        to_play=BLACK,
        to_play_is_human=True,
        ai_can_respond=ai_ok,
        move_number=move_number,
        board_size=len(current),
    )


_FINISHED = _grid(["BW.", "WB.", "B.W"])  # 前の対局の終盤（KaTrain 側）
_EMPTY = _grid(["...", "...", "..."])
_FIRST_MOVE = _grid(["...", ".B.", "..."])


def test_new_game_fires_once_after_stable_frames_and_stops_the_watcher():
    h = Harness(color=WHITE)
    state = _state(_FINISHED)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES - 1):
        h.step(_EMPTY, state)
    assert h.new_games == []
    assert not h.warned()  # 確認中は同期ずれの警告を出さない
    assert h.watcher.interval_ms == WatchSettings().poll_interval_active_ms  # 確認の周を詰める
    h.step(_EMPTY, state)
    assert h.new_games == [(_EMPTY, 3, WHITE)]
    assert h.watcher._stopped.is_set()  # 自分で止まる＝張り直しが済むまでに何度も投げない
    assert h.statuses[-1] == (bw.STATUS_WATCHING, bw.NEW_GAME_TEXT)


def test_new_game_needs_the_near_player_color():
    h = Harness(color=None)
    state = _state(_FINISHED)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES + 2):
        h.step(_EMPTY, state)
    assert h.new_games == []
    assert h.warned()  # 色が読めなければ従来どおりの同期ずれ警告（再同期はホットキー）


def test_new_game_ignores_boards_that_are_not_an_opening():
    h = Harness()
    state = _state(_EMPTY, move_number=0)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES + 2):
        h.step(_FINISHED, state)
    assert h.new_games == []
    assert h.warned()


def test_new_game_ignores_a_board_equal_to_katrain():
    # 盤は同じで AI が応手できないだけ（分岐・終局）。張り直しても取り込みが起きず同じ状態に戻る
    h = Harness()
    state = _state(_EMPTY, move_number=0, ai_ok=False)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES + 2):
        h.step(_EMPTY, state)
    assert h.new_games == []


def test_new_game_is_off_without_the_hooks():
    # 詰碁の白番自動反映はフックを渡さない＝詰碁の盤を「次の対局」と取り違えない
    h = Harness(hooks=False)
    state = _state(_FINISHED)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES + 2):
        h.step(_EMPTY, state)
    assert h.new_games == []
    assert h.warned()


def test_new_game_restarts_the_count_when_the_board_changes():
    # アプリ AI が黒で初手をすぐ打つ＝空盤の確認中に1子の盤へ変わる。変わった盤で数え直す
    h = Harness(color=WHITE)
    state = _state(_FINISHED)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES - 1):
        h.step(_EMPTY, state)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES - 1):
        h.step(_FIRST_MOVE, state)
    assert h.new_games == []
    h.step(_FIRST_MOVE, state)
    assert h.new_games == [(_FIRST_MOVE, 3, WHITE)]


def test_new_game_count_needs_consecutive_frames():
    h = Harness()
    state = _state(_FINISHED)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES - 1):
        h.step(_EMPTY, state)
    h.step(RuntimeError("遷移中のフレーム"), state)
    for _ in range(bw.NEW_GAME_STABLE_FRAMES - 1):
        h.step(_EMPTY, state)
    assert h.new_games == []
    h.step(_EMPTY, state)
    assert len(h.new_games) == 1


def test_new_game_detects_a_board_size_change():
    h = Harness()
    state = _state(_FINISHED)
    empty4 = _grid(["....", "....", "....", "...."])
    for _ in range(bw.NEW_GAME_STABLE_FRAMES):
        h.step(empty4, state)
    assert h.new_games == [(empty4, 4, BLACK)]


def test_real_screenshots_previous_game_to_next_game(monkeypatch):
    """実画面の列: 前の対局（手前が白・22子）を監視中に、アプリが次の対局（手前が黒・黒白1子ずつ）へ移る。

    AppBoardReader の最新フレームから手前の色を読むところまで本物で通す（BoardWatcher はフックだけ注入）
    """
    from katrain.core import tsumego_capture as tc

    previous_game, next_game = _image("board_watch_start_white.png"), _image("board_watch_start_black.png")
    frames = [previous_game, previous_game] + [next_game] * bw.NEW_GAME_STABLE_FRAMES
    monkeypatch.setattr(
        bw,
        "_capture_api",
        lambda: (
            lambda _title: (0, 0, 557, 735),
            lambda _rect: frames.pop(0),
            tc.detect_board,
            tc.detect_size_and_classify,
        ),
    )
    reader = bw.AppBoardReader("BlueStacks", [9, 13, 19])
    katrain_grid = reader.read()  # KaTrain 側は前の対局に追随済み
    new_games = []
    watcher = BoardWatcher(
        capture_fn=reader.read,
        get_state_fn=lambda: _state(katrain_grid, move_number=41),
        on_move=lambda *a: None,
        on_status=lambda *a: None,
        settings=WatchSettings(),
        clock=FakeClock(),
        player_color_fn=reader.near_player_color,
        on_new_game=lambda grid, size, color: new_games.append((grid, size, color)),
    )
    while frames:
        watcher.step()
    assert len(new_games) == 1
    grid, size, color = new_games[0]
    assert (size, color) == (9, BLACK)
    assert {(i, j): v for i, row in enumerate(grid) for j, v in enumerate(row) if v != "."} == {
        (3, 5): WHITE,
        (5, 5): BLACK,
    }
    assert bw.import_next_player(grid, human_color=WHITE)[0] == BLACK  # KaTrain（黒）の手番で取り込まれる


def test_run_loop_ends_by_itself_after_new_game():
    calls = []
    holder = {}

    def capture():
        calls.append(1)
        if len(calls) > 20:  # 自分で止まらなかった場合の安全弁（テストを固めない）
            holder["watcher"].stop()
        return _EMPTY

    holder["watcher"] = BoardWatcher(
        capture_fn=capture,
        get_state_fn=lambda: _state(_FINISHED),
        on_move=lambda *a: None,
        on_status=lambda *a: None,
        settings=WatchSettings(poll_interval_ms=1, poll_interval_active_ms=1),
        player_color_fn=lambda: BLACK,
        on_new_game=lambda *a: None,
    )
    holder["watcher"].run()
    assert len(calls) == bw.NEW_GAME_STABLE_FRAMES


# --- __main__ の配線（静的検査。__main__ は Kivy 依存で import できない） ---


def _functions():
    with open(_MAIN, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _callee(call):
    return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", None)


def _calls(func):
    return [n for n in ast.walk(func) if isinstance(n, ast.Call)]


def _watcher_keywords(func):
    watcher_calls = [c for c in _calls(func) if _callee(c) == "BoardWatcher"]
    assert watcher_calls
    return {kw.arg for kw in watcher_calls[0].keywords}


def test_game_watch_gets_the_new_game_hooks_and_the_tsumego_watch_does_not():
    funcs = _functions()
    assert {"player_color_fn", "on_new_game"} <= _watcher_keywords(funcs["_do_board_watch_start"])
    assert not {"player_color_fn", "on_new_game"} & _watcher_keywords(funcs["_start_tsumego_watch"])


def test_start_reads_the_icons_and_moves_the_ai_to_the_near_color():
    funcs = _functions()
    trigger = [_callee(c) for c in _calls(funcs["_board_watch_trigger"])]
    assert "player_icon_colors" in trigger and "confirmed_near_color" in trigger
    start = [_callee(c) for c in _calls(funcs["_do_board_watch_start"])]
    assert "watch_player_assignment" in start and "update_player" in start


def test_new_game_restart_stops_the_old_watch_and_imports_the_new_board():
    funcs = _functions()
    calls = _calls(funcs["_do_board_watch_new_game"])
    assert "_stop_board_watcher" in [_callee(c) for c in calls]
    starts = [c for c in calls if _callee(c) == "_do_board_watch_start"]
    assert starts and any(
        kw.arg == "force_import" and getattr(kw.value, "value", None) is True for kw in starts[0].keywords
    )
