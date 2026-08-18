from katrain.core.board_watch import EMPTY, BLACK, WHITE, apply_move_to_grid, grid_to_move, move_to_grid, stones_to_grid, WatchState, reconcile, board_sgf
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
    h = Harness(WatchSettings(resync_hint_frames=3))
    current = _grid(["...", "...", "..."])
    observed = _grid(["W..", ".B.", "..."])
    state = _state(current, to_play="B")
    for _ in range(3):
        h.step(observed, state)
    assert any("ctrl+alt+b" in text for _kind, text in h.statuses)


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
