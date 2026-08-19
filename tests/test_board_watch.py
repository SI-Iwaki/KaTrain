import ast
import os
import re
import threading

import pytest

from katrain.core.board_watch import EMPTY, BLACK, WHITE, apply_move_to_grid, grid_to_move, move_to_grid, stones_to_grid, WatchState, reconcile, board_sgf, import_next_player
from katrain.core.board_watch import BoardWatcher, WatchSettings  # 既存の import 行に足す
import katrain.core.board_watch as bw  # 既存の import 行の下に足す


def test_stones_to_grid_uses_top_origin_rows():
    # KaTrain の (x=0, y=0) は盤の左下 = グリッドの最終行の先頭
    grid = stones_to_grid([((0, 0), "B"), ((2, 2), "W")], 3)
    assert grid == [
        [EMPTY, EMPTY, "W"],
        [EMPTY, EMPTY, EMPTY],
        ["B", EMPTY, EMPTY],
    ]


def test_stones_to_grid_ignores_pass():
    assert stones_to_grid([(None, "B")], 2) == [[EMPTY, EMPTY], [EMPTY, EMPTY]]


def test_move_to_grid_round_trip():
    size = 19
    for x in range(size):
        for y in range(size):
            i, j = move_to_grid((x, y), size)
            assert grid_to_move(i, j, size) == (x, y)


def test_move_to_grid_pass_is_none():
    assert move_to_grid(None, 19) is None


def _grid(rows):
    """'.BW' の文字列行からグリッドを作る（行は上origin）"""
    return [list(r) for r in rows]


def test_apply_move_places_stone():
    out = apply_move_to_grid(_grid(["...", "...", "..."]), 1, 1, "B")
    assert out == _grid(["...", ".B.", "..."])


def test_apply_move_rejects_occupied_point():
    assert apply_move_to_grid(_grid(["B.."]), 0, 0, "W") is None


def test_apply_move_rejects_out_of_board():
    assert apply_move_to_grid(_grid(["..", ".."]), 2, 0, "B") is None


def test_apply_move_captures_single_stone():
    # 白1子 (2,0) の呼吸点は (2,1) だけ。黒がそこに打つと取れる
    before = _grid([
        "...",
        "B..",
        "W..",
    ])
    out = apply_move_to_grid(before, 2, 1, "B")
    assert out == _grid([
        "...",
        "B..",
        ".B.",
    ])
    assert before == _grid(["...", "B..", "W.."])  # 引数は破壊しない


def test_apply_move_captures_multi_stone_group():
    # 白2子 {(1,1),(1,2)} の呼吸点は (1,3) だけ
    before = _grid([
        ".BB.",
        "BWW.",
        ".BB.",
        "....",
    ])
    out = apply_move_to_grid(before, 1, 3, "B")
    assert out == _grid([
        ".BB.",
        "B..B",
        ".BB.",
        "....",
    ])


def test_apply_move_rejects_suicide():
    # 四方を白の独立した1子に囲まれた点。どの白も呼吸点が残るので取れず、自分が窒息する
    before = _grid([
        ".W.",
        "W.W",
        ".W.",
    ])
    assert apply_move_to_grid(before, 1, 1, "B") is None


def test_apply_move_capture_frees_own_liberties():
    # 打つ点そのものは呼吸点0だが、先に白3子を取るので合法（取り→自殺判定の順序）
    before = _grid([
        ".WB",
        "WWB",
        "BB.",
    ])
    out = apply_move_to_grid(before, 0, 0, "B")
    assert out == _grid([
        "B.B",
        "..B",
        "BB.",
    ])


def _state(current, to_play="B", last_move=None, human=True, ai_ok=True, move_number=1):
    return WatchState(
        current_grid=current,
        last_move=last_move,
        to_play=to_play,
        to_play_is_human=human,
        ai_can_respond=ai_ok,
        move_number=move_number,
        board_size=len(current),
    )


def test_reconcile_board_size_mismatch_wins_first():
    state = _state(_grid(["...", "...", "..."]))
    verdict = reconcile(state, _grid(["..", ".."]))
    assert verdict.kind == "mismatch"
    assert "盤サイズ" in verdict.reason


def test_reconcile_ai_cannot_respond_is_mismatch_even_when_boards_agree():
    board = _grid(["...", "...", "..."])
    verdict = reconcile(_state(board, ai_ok=False), board)
    assert verdict.kind == "mismatch"


def test_reconcile_ai_turn_is_silent_waiting():
    board = _grid(["...", "...", "..."])
    verdict = reconcile(_state(board, human=False), board)
    assert verdict.kind == "waiting"


def test_reconcile_ai_turn_never_injects_even_if_a_move_fits():
    # 色の割り当てが逆なら、相手の石が to_play と同色になって「1手で説明できる」が、
    # AI の手番では絶対に注入しない
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B", human=False), observed)
    assert verdict.kind == "waiting"


def test_reconcile_in_sync():
    board = _grid([".B.", "...", "..W"])
    assert reconcile(_state(board), board).kind == "in_sync"


def test_reconcile_detects_opponent_move():
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B"), observed)
    assert verdict.kind == "move"
    assert verdict.move == (1, 1)


def test_reconcile_detects_move_with_capture():
    # 白1子 (2,0) の呼吸点は (2,1) だけ。黒がそこに打つと白が消える
    current = _grid(["...", "B..", "W.."])
    observed = _grid(["...", "B..", ".B."])
    verdict = reconcile(_state(current, to_play="B"), observed)
    assert verdict.kind == "move"
    assert verdict.move == (2, 1)


def test_reconcile_ahead_when_katrain_played_but_app_has_not():
    current = _grid(["...", ".W.", "..."])
    observed = _grid(["...", "...", "..."])
    state = _state(current, to_play="B", last_move=(1, 1, "W"))
    assert reconcile(state, observed).kind == "ahead"


def test_reconcile_root_position_has_no_last_move():
    # 対局開始直後（KaTrain 側 AI が白＝相手が先着）。last_move=None でも落ちない
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B", last_move=None, move_number=0), observed)
    assert verdict.kind == "move"


def test_reconcile_after_pass_has_no_last_move():
    # パス直後は last_move が None として渡ってくる（__main__ 側で coords=None を落とす）
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B", last_move=None), observed)
    assert verdict.kind == "move"


def test_reconcile_wrong_color_stone_is_mismatch():
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".W.", "..."])
    verdict = reconcile(_state(current, to_play="B"), observed)
    assert verdict.kind == "mismatch"


def test_reconcile_two_moves_ahead_is_mismatch():
    current = _grid(["...", "...", "..."])
    observed = _grid(["W..", ".B.", "..."])
    verdict = reconcile(_state(current, to_play="B"), observed)
    assert verdict.kind == "mismatch"


def test_reconcile_single_noise_stone_removed_is_mismatch():
    current = _grid([".B.", "...", "..W"])
    observed = _grid([".B.", "...", "..."])
    state = _state(current, to_play="B", last_move=(0, 1, "B"))
    assert reconcile(state, observed).kind == "mismatch"


def test_board_sgf_empty_board_is_valid():
    sgf = board_sgf(_grid(["...", "...", "..."]), komi=6.5, rules="japanese", next_player="B")
    assert "SZ[3]" in sgf and "KM[6.5]" in sgf and "PL[B]" in sgf
    assert "AB" not in sgf and "AW" not in sgf


def test_board_sgf_places_stones_with_top_origin_rows():
    sgf = board_sgf(_grid(["B..", "...", "..W"]), komi=7.5, rules="chinese", next_player="W")
    assert "AB[aa]" in sgf
    assert "AW[cc]" in sgf
    assert "PL[W]" in sgf
    assert "RU[chinese]" in sgf


def test_board_sgf_parses_with_katrain_sgf_parser():
    from katrain.core.game import KaTrainSGF

    root = KaTrainSGF.parse_sgf(board_sgf(_grid(["B..", "...", "..W"]), 6.5, "japanese", "W"))
    assert root.board_size == (3, 3)
    assert root.next_player == "W"


def test_import_next_player_empty_board_is_black_regardless_of_human_color():
    # 空盤＝新規対局そのもの。碁のルールで黒が先手（推測ではない）。
    # human_color が黒でも白でも、空盤なら必ず黒番を返す
    empty = _grid(["...", "...", "..."])
    assert import_next_player(empty, human_color="W") == BLACK
    assert import_next_player(empty, human_color="B") == BLACK


def test_import_next_player_single_stone_falls_back_to_human_color():
    # 石が1つでもあれば石数パリティは手番を表さない（b-w = cw-cb）ので、
    # 安全側の human_color に倒す
    grid = _grid(["B..", "...", "..."])
    assert import_next_player(grid, human_color="W") == "W"
    assert import_next_player(grid, human_color="B") == "B"


def test_import_next_player_many_stones_falls_back_to_human_color():
    grid = _grid([
        "BW.",
        ".BW",
        "W.B",
    ])
    assert import_next_player(grid, human_color="W") == "W"
    assert import_next_player(grid, human_color="B") == "B"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Harness:
    """BoardWatcher を偽の外界で駆動する"""

    def __init__(self, settings=None):
        self.frames = []           # capture_fn が順に返すもの（例外インスタンスなら raise）
        self.state = None
        self.moves = []
        self.statuses = []
        self.clock = FakeClock()
        self.watcher = BoardWatcher(
            capture_fn=self._capture,
            get_state_fn=lambda: self.state,
            on_move=lambda i, j, color, move_number, size: self.moves.append((i, j, color, move_number)),
            on_status=lambda kind, text: self.statuses.append((kind, text)),
            settings=settings or WatchSettings(),
            clock=self.clock,
        )

    def _capture(self):
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame

    def step(self, frame, state=None):
        self.frames.append(frame)
        if state is not None:
            self.state = state
        self.watcher.step()


def test_watcher_injects_after_stable_frames():
    h = Harness(WatchSettings(stable_frames=2))
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    state = _state(current, to_play="B", move_number=4)
    h.step(observed, state)
    assert h.moves == []           # 1フレーム目では確定しない
    h.step(observed, state)
    assert h.moves == [(1, 1, "B", 4)]


def test_watcher_resets_stability_when_move_changes():
    h = Harness(WatchSettings(stable_frames=2))
    current = _grid(["...", "...", "..."])
    state = _state(current, to_play="B")
    h.step(_grid(["...", ".B.", "..."]), state)
    h.step(_grid(["B..", "...", "..."]), state)
    assert h.moves == []


def test_watcher_does_not_inject_again_while_pending():
    h = Harness(WatchSettings(stable_frames=1))
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    state = _state(current, to_play="B", move_number=4)
    h.step(observed, state)
    assert len(h.moves) == 1
    h.step(observed, state)        # KaTrain 側はまだ反映されていない
    assert len(h.moves) == 1


def test_watcher_clears_pending_when_move_number_changes():
    h = Harness(WatchSettings(stable_frames=1))
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    h.step(observed, _state(current, to_play="B", move_number=4))
    assert len(h.moves) == 1
    # KaTrain が着手し、さらに AI が応じた（期待グリッドは一瞬しか存在しない）
    after = _grid(["W..", ".B.", "..."])
    h.step(after, _state(after, to_play="B", last_move=(0, 0, "W"), move_number=6))
    assert h.watcher._pending is None


def test_watcher_warns_and_blocks_move_after_inject_timeout():
    h = Harness(WatchSettings(stable_frames=1, inject_timeout_ms=1000))
    current = _grid(["...", "...", "..."])
    observed = _grid(["...", ".B.", "..."])
    state = _state(current, to_play="B", move_number=4)
    h.step(observed, state)
    h.clock.advance(2.0)
    h.step(observed, state)
    assert any(kind == "bw-warn" for kind, _text in h.statuses)
    h.step(observed, state)        # 同じ手を再注入しない
    assert len(h.moves) == 1


def test_watcher_is_silent_while_waiting_and_ahead():
    h = Harness()
    board = _grid(["...", "...", "..."])
    h.step(board, _state(board, human=False))
    h.step(board, _state(board))
    assert all(kind == "bw-watching" for kind, _t in h.statuses)


def test_watcher_warns_when_quiet_too_long():
    h = Harness(WatchSettings(stall_warn_sec=20))
    board = _grid(["...", "...", "..."])
    state = _state(board, human=False)
    h.step(board, state)
    h.clock.advance(25.0)
    h.step(board, state)
    assert any(kind == "bw-warn" and "変化しません" in text for kind, text in h.statuses)


def test_watcher_quiet_timer_resets_when_state_changes():
    h = Harness(WatchSettings(stall_warn_sec=20))
    board = _grid(["...", "...", "..."])
    h.step(board, _state(board, human=False, move_number=1))
    h.clock.advance(15.0)
    h.step(board, _state(board, human=False, move_number=2))
    h.clock.advance(15.0)
    h.step(board, _state(board, human=False, move_number=2))
    assert not any(kind == "bw-warn" for kind, _t in h.statuses)


def test_watcher_adds_resync_hint_after_repeated_mismatch():
    # 具体的なキー名（例: "ctrl+alt+d"）はユーザー設定 board_watch.hotkey で変わりうるので
    # 固定文字列を再ピン留めしない。実際に効くべき性質は「RESYNC_HINT がそのまま
    # 追記されること」なので、モジュール定数を通して検査する
    h = Harness(WatchSettings(resync_hint_frames=3))
    current = _grid(["...", "...", "..."])
    observed = _grid(["W..", ".B.", "..."])
    state = _state(current, to_play="B")
    for _ in range(3):
        h.step(observed, state)
    assert any(bw.RESYNC_HINT in text for _kind, text in h.statuses)


def test_watcher_skips_transient_capture_failures_then_warns():
    h = Harness(WatchSettings(failure_warn_frames=3))
    for _ in range(2):
        h.step(RuntimeError("judgement failed"))
    assert h.statuses == []
    h.step(RuntimeError("judgement failed"))
    assert any(kind == "bw-warn" for kind, _t in h.statuses)


def test_watcher_backs_off_and_recovers():
    h = Harness(WatchSettings(poll_interval_ms=400, backoff_after_failures=2, backoff_factor=2.0, poll_interval_max_ms=2000))
    h.step(RuntimeError("x"))
    h.step(RuntimeError("x"))
    assert h.watcher.interval_ms == 800
    h.step(RuntimeError("x"))
    assert h.watcher.interval_ms == 1600
    board = _grid(["...", "...", "..."])
    h.step(board, _state(board))
    assert h.watcher.interval_ms == 400


def test_watcher_ignores_none_state():
    h = Harness()
    board = _grid(["...", "...", "..."])
    h.step(board, None)
    assert h.moves == []


def test_watcher_warns_immediately_on_permanent_failure():
    from katrain.core.board_watch import PermanentCaptureError

    h = Harness(WatchSettings(failure_warn_frames=8))
    h.step(PermanentCaptureError("ウィンドウが見つかりません"))
    assert any(kind == "bw-warn" for kind, _t in h.statuses)


def test_watcher_recovers_after_permanent_failure():
    from katrain.core.board_watch import PermanentCaptureError

    h = Harness(WatchSettings(failure_warn_frames=8))
    h.step(PermanentCaptureError("ウィンドウが見つかりません"))
    board = _grid(["...", "...", "..."])
    h.step(board, _state(board))
    assert h.statuses[-1][0] == "bw-watching"


def test_run_stops_and_survives_unexpected_exceptions():
    h = Harness(WatchSettings(poll_interval_ms=1))
    calls = []

    def boom():
        calls.append(1)
        if len(calls) >= 3:
            h.watcher.stop()
        raise ValueError("boom")

    h.watcher.get_state_fn = boom
    h.frames = [_grid(["..", ".."])] * 10
    h.watcher.run()
    assert len(calls) >= 3
    assert any(kind == "bw-warn" for kind, _t in h.statuses)


def test_reader_caches_board_rect_and_size(monkeypatch):
    calls = {"detect_board": 0, "classify": 0, "sizes": []}

    def fake_find_window_rect(title):
        return (0, 0, 100, 100)

    def fake_capture_screen_rect(rect):
        return "IMG"

    def fake_detect_board(img):
        calls["detect_board"] += 1
        return (1, 2, 3, 4)

    def fake_detect_size_and_classify(img, board_rect, sizes):
        calls["classify"] += 1
        calls["sizes"].append(list(sizes))
        return 9, [["."] * 9 for _ in range(9)]

    monkeypatch.setattr(bw, "_capture_api", lambda: (
        fake_find_window_rect, fake_capture_screen_rect, fake_detect_board, fake_detect_size_and_classify
    ))
    reader = bw.AppBoardReader("BlueStacks", [9, 13, 19])
    reader.read()
    reader.read()
    assert calls["detect_board"] == 1          # 2周目は盤矩形を再検出しない
    assert calls["sizes"] == [[9, 13, 19], [9]]  # 2周目はキャッシュしたサイズ1候補だけ
    assert reader.size == 9


def test_reader_reruns_detection_after_failure(monkeypatch):
    calls = {"detect_board": 0}
    state = {"fail": False}

    def fake_detect_size_and_classify(img, board_rect, sizes):
        if state["fail"]:
            raise RuntimeError("grid score too low")
        return 9, [["."] * 9 for _ in range(9)]

    def fake_detect_board(img):
        calls["detect_board"] += 1
        return (1, 2, 3, 4)

    monkeypatch.setattr(bw, "_capture_api", lambda: (
        lambda title: (0, 0, 100, 100), lambda rect: "IMG", fake_detect_board, fake_detect_size_and_classify
    ))
    reader = bw.AppBoardReader("BlueStacks", [9])
    reader.read()
    state["fail"] = True
    try:
        reader.read()
    except RuntimeError:
        pass
    state["fail"] = False
    reader.read()
    assert calls["detect_board"] == 2  # 失敗後は盤矩形からやり直す


def _running_watcher(settings=None):
    """実スレッドで動かす BoardWatcher。capture_fn が呼ばれるたびに polled イベントを立てる"""
    polled = threading.Event()

    def capture_fn():
        polled.set()
        return _grid(["..", ".."])

    watcher = BoardWatcher(
        capture_fn=capture_fn,
        get_state_fn=lambda: None,  # None を返せば step() は何もせず即戻る
        on_move=lambda *a: None,
        on_status=lambda *a: None,
        settings=settings or WatchSettings(poll_interval_ms=1),
    )
    return watcher, polled


def test_start_called_twice_creates_only_one_live_thread():
    watcher, polled = _running_watcher()
    watcher.start()
    assert polled.wait(2.0)  # ループが実際に回っていることを確認してから
    first_thread = watcher._thread
    assert first_thread.is_alive()

    watcher.start()  # 2回目は無視されるべき
    assert watcher._thread is first_thread  # 新しいスレッドに差し替わっていない

    watcher.stop()


def test_stop_after_start_leaves_thread_not_alive_and_is_noop_when_never_started():
    watcher, polled = _running_watcher()
    watcher.start()
    assert polled.wait(2.0)

    watcher.stop()
    assert not watcher._thread.is_alive()  # join 済みなので即座に確認できる

    # 一度も start() していないウォッチャーで stop() を呼んでも例外にならない
    never_started, _polled = _running_watcher()
    assert never_started._thread is None
    never_started.stop()


def test_start_after_stop_restarts_the_loop():
    watcher, polled = _running_watcher()
    watcher.start()
    assert polled.wait(2.0)
    watcher.stop()
    assert not watcher._thread.is_alive()

    polled.clear()
    watcher.start()  # stop() 後の再 start() でも本当にループが回ることを確認する
    assert polled.wait(2.0)  # capture_fn が呼ばれた＝run() が1周以上回った証拠
    assert watcher._thread.is_alive()

    watcher.stop()


def test_all_hotkey_dispatch_handler_names_have_matching_defs():
    """Task 8 レビューの Critical defect の回帰テスト。

    `katrain/__main__.py` の `_global_hotkey_loop` は、ホットキー登録表に文字列として
    積まれたハンドラ名を `getattr(self, handler)` で解決してからワーカースレッドを起動する。
    この解決は `try/finally`（finally は登録済み全ホットキーの UnregisterHotKey）の中で
    無防備に行われていたため、表に存在しないハンドラ名が1つ紛れ込むだけで
    AttributeError がメッセージループのスレッドを直撃し、finally が発火して
    **他の機能（詰碁キャプチャの4本）のホットキーまで巻き添えで unregister され、
    ループ自体を持つ daemon スレッドが落ちる**＝プロセス再起動までグローバル
    ホットキーが全滅する。

    このテストは KataGo/Kivy/Win32 いずれにも依存せず、`__main__.py` を ast で静的に
    解析するだけで検査できる不変条件を確認する: `_setup_global_hotkeys` が組み立てる
    `specs`（`(settings, feature, key, default, handler, args, label)` の7要素タプル、
    handler はインデックス4）の `specs.append((...))` 呼び出しから拾える全ハンドラ名
    文字列リテラルが、同ファイル内に対応する `def` を持つこと。

    実装メモ: 素朴には「ファイル全体で `^_[a-z0-9_]+_trigger$` に一致する文字列リテラル
    全部」を対象にする実装をまず試したが、`_tsumego_capture_trigger`（詰碁キャプチャの
    連打防止デバウンス用タイムスタンプを持たせる **instance attribute** 名。
    `getattr(self, "_tsumego_capture_last_trigger", 0.0)` /
    `self._tsumego_capture_last_trigger = now`、`_tsumego_capture_trigger` メソッド内）が
    たまたま同じ命名の形に一致し、かつ def を持たない（メソッドではなく属性なので
    持つべきでもない）ため、Task 11 が `_board_watch_trigger` を実装した後もこのテストが
    ずっと red のままになる恒久的な誤検出だった。dispatch table の実際の構造
    （`specs.append` タプルの5番目の要素が handler 名という、このファイルが自分で
    定義している契約）に検査対象を絞ることで、この属性名を誤検出せずに済み、かつ
    元の欠陥（specs テーブルに存在しないハンドラ名が紛れ込む）は変わらず検出できる。
    """
    main_path = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
    source = open(main_path, encoding="utf-8").read()
    tree = ast.parse(source)

    handler_name_pattern = re.compile(r"^_[a-z0-9_]+_trigger$")
    handler_field_index = 4  # (settings, feature, key, default, handler, args, label)

    dispatch_handler_names = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "specs"
            and node.args
            and isinstance(node.args[0], ast.Tuple)
            and len(node.args[0].elts) > handler_field_index
        ):
            continue
        handler_elt = node.args[0].elts[handler_field_index]
        assert isinstance(handler_elt, ast.Constant) and isinstance(handler_elt.value, str), (
            "specs.append(...) のハンドラ位置(index 4)がリテラル文字列ではありません。"
            "実装のタプル構造が変わった可能性があり、このテストの前提(handler_field_index)を"
            "見直す必要があります"
        )
        assert handler_name_pattern.match(handler_elt.value), (
            f"specs.append(...) のハンドラ位置(index 4)の値 {handler_elt.value!r} が想定する"
            "ハンドラ名の形('_..._trigger')に一致しません。テストの前提(handler_field_index)が"
            "実装とずれている可能性があります"
        )
        dispatch_handler_names.add(handler_elt.value)

    assert dispatch_handler_names, (
        "specs.append(...) からハンドラ名を1つも抽出できませんでした。"
        "_setup_global_hotkeys の実装が変わり、このテストの前提とずれている可能性があります"
    )

    defined_function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    missing = sorted(dispatch_handler_names - defined_function_names)
    assert not missing, (
        f"katrain/__main__.py の specs.append(...) ホットキー登録表がハンドラ名 {missing} を"
        "文字列リテラルとして参照していますが、同ファイル内に対応する def がありません。"
        "これは Task 8 の Critical defect と全く同じ形です: specs テーブルに存在しない"
        "ハンドラ名が1つ紛れ込むと、`_global_hotkey_loop` 内の `getattr(self, handler)` が"
        "その名前を押されたときに AttributeError を送出し、メッセージループのスレッドを"
        "直撃します。この例外は try/finally の finally 節（登録済み全ホットキーの"
        "UnregisterHotKey）を発火させてからスレッド外へ伝播するため、無関係な他機能の"
        "ホットキー（詰碁キャプチャの4本を含む）まで巻き添えで解除され、ループを持つ"
        "daemon スレッドごと落ちます。結果、プロセスを再起動するまでグローバルホットキーが"
        "全て無反応になります。"
    )


# ============================================================
# Task 13: 実スクショによる回帰テスト
#
# tests/data/board_watch_before.png / board_watch_after.png は Task 1 のスパイクで
# 実際の対局アプリ（BlueStacks上の囲碁クエスト、9路・vs :KaasanBot）から保存した2枚。
# 詳細・生データは docs/superpowers/specs/calibration-data/board-watch/spike-results-20260818.md。
#
# この2枚がカバーする範囲（実測済み）:
#   - 9路盤の rect/size 判定
#   - 疎な配置（石1〜3個）の石分類（黒/白）
#   - 最終手マーカーが乗った黒石が "." に化けずに "B" と読めること
#
# この2枚がカバーしない範囲（他ケースの回帰にはならない）:
#   - 13路・19路盤
#   - 白石に最終手マーカーが乗るケース（今回のペアは両方とも黒番の着手）
#   - 石が密集した局面
#   - 石が取られる（capture）局面
#   - 「観測差がちょうど相手の1手ぶん」という前提（このペアは撮影間隔が数分空き、
#     実際は2手ぶん＝人間の着手+アプリAIの応手が進んでいた。Test B はそれを
#     素通しで reconcile するのではなく、人間の着手を before に適用してから
#     reconcile することで「機能が実際に使われる状況」を再現する）
#
# アプリAIはこの対局では黒番（人間が白番）。KaTrain 側の WatchState では
# 「注入対象（アプリAI）の手番かどうか」を to_play_is_human で表すので、
# アプリAI（黒）の手番では to_play_is_human=True になる（board_watch.py の
# WatchState docstring・reconcile の分岐参照）。

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_BEFORE_PNG = os.path.join(_DATA_DIR, "board_watch_before.png")
_AFTER_PNG = os.path.join(_DATA_DIR, "board_watch_after.png")

# Task 1 スパイクの実測値（spike-results-20260818.md の生データより）
_EXPECTED_SIZE = 9
_EXPECTED_BEFORE_STONES = {(4, 5): BLACK}
_EXPECTED_AFTER_STONES = {(4, 5): BLACK, (4, 3): WHITE, (3, 3): BLACK}
_HUMAN_MOVE = (4, 3, WHITE)  # 人間（白）の着手: row=4 col=3
_APP_AI_REPLY = (3, 3)  # アプリAI（黒）の応手: row=3 col=3


def _recognize_real_screenshot(path):
    from PIL import Image

    from katrain.core.tsumego_capture import detect_board, detect_size_and_classify

    img = Image.open(path)
    board_rect = detect_board(img)
    size, grid = detect_size_and_classify(img, board_rect, [9, 13, 19])
    return size, grid


def _stones(grid):
    return {(i, j): v for i, row in enumerate(grid) for j, v in enumerate(row) if v != EMPTY}


_SCREENSHOTS_MISSING = not (os.path.exists(_BEFORE_PNG) and os.path.exists(_AFTER_PNG))


@pytest.mark.skipif(_SCREENSHOTS_MISSING, reason="スパイクのスクショが未取得")
def test_real_screenshots_recognized_grids_match_spike_measurement():
    """認識器単体（board_watch のロジックは一切通さない）の回帰。

    Task 1 スパイクで実測した盤サイズ・石の座標・色をそのまま固定する。
    期待値は「非空セルの集合」全体で比較する（部分集合の包含チェックだと
    余計な石が紛れ込んでも通ってしまうため）。この関数が red になったら
    認識器（detect_board / detect_size_and_classify）がドリフトした証拠で、
    board_watch 側の変更は無関係。
    """
    size_before, before = _recognize_real_screenshot(_BEFORE_PNG)
    size_after, after = _recognize_real_screenshot(_AFTER_PNG)
    assert size_before == _EXPECTED_SIZE
    assert size_after == _EXPECTED_SIZE
    assert _stones(before) == _EXPECTED_BEFORE_STONES
    assert _stones(after) == _EXPECTED_AFTER_STONES


@pytest.mark.skipif(_SCREENSHOTS_MISSING, reason="スパイクのスクショが未取得")
def test_real_screenshots_reconcile_detects_app_ai_reply():
    """実際に使われる状況を再現する end-to-end 回帰: KaTrain が人間の着手を
    反映した直後の局面に、ウォッチャーがアプリAIの応手を観測する。

    before/after を素通しで reconcile すると差は2手ぶんなので mismatch になる
    （spike-results 参照）。それは「1手差」の主張として使えないため、ここでは
    before に人間の着手（White, row=4 col=3）を apply_move_to_grid で適用して
    from-state を作り、そこに after を reconcile する。
    """
    _size_before, before = _recognize_real_screenshot(_BEFORE_PNG)
    _size_after, after = _recognize_real_screenshot(_AFTER_PNG)

    human_i, human_j, human_color = _HUMAN_MOVE
    current = apply_move_to_grid(before, human_i, human_j, human_color)
    assert current is not None  # 人間の着手が合法手として適用できること自体も固定する

    state = _state(
        current,
        to_play=BLACK,          # アプリAI（黒）の手番
        last_move=_HUMAN_MOVE,
        human=True,              # アプリAI側 = KaTrain 用語の「human」（注入対象）
        ai_ok=True,
        move_number=2,
    )
    verdict = reconcile(state, after)
    assert verdict.kind == "move"
    assert verdict.move == _APP_AI_REPLY
