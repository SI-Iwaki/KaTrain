"""対局盤面監視の明るい木目盤アプリ対応（自動フォールバック経路）のテスト。

tests/data/board_watch_wood*.png はユーザー提供の実スクショ4枚（別の BlueStacks 囲碁アプリ・
19路 before/after の1手差ペア・13路・9路）。期待値の石マップは画素解析＋目視照合で確定した値
（実測データは docs/superpowers/specs/2026-08-18-board-watch-design.md の追記参照）。

既存の tests/test_board_watch.py には追記しない（black 未整形のため Edit すると全体再整形になる）。
"""

import os

import pytest

import katrain.core.board_watch as bw
from katrain.core.board_watch import (
    BLACK,
    EMPTY,
    WHITE,
    AppBoardReader,
    WatchState,
    grid_screen_point,
    reconcile,
)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_WOOD19_BEFORE = os.path.join(_DATA_DIR, "board_watch_wood19_before.png")
_WOOD19_AFTER = os.path.join(_DATA_DIR, "board_watch_wood19_after.png")
_WOOD13 = os.path.join(_DATA_DIR, "board_watch_wood13.png")
_WOOD9 = os.path.join(_DATA_DIR, "board_watch_wood9.png")
_ALL_WOOD = [_WOOD19_BEFORE, _WOOD19_AFTER, _WOOD13, _WOOD9]
_SCREENSHOTS_MISSING = not all(os.path.exists(p) for p in _ALL_WOOD)

# 画素解析＋目視照合で確定した石マップ（非空セルの完全一致で比較する＝余計な石の混入も検出）。
# (2, 9)=B は白い輪の直前着手マーカー付き黒石＝小半径リトライ（WOOD_MARKER_PATCH_RATIO）経路、
# (9, 2)=W（13路）は黒い輪のマーカー付き白石。空点の星点が W に化けないこと（median 分類の回帰）も
# このマップ一致が同時に固定する
_EXPECTED_19_BEFORE = {
    (2, 9): BLACK,
    (2, 15): BLACK,
    (3, 3): WHITE,
    (9, 15): BLACK,
    (12, 16): BLACK,
    (15, 3): WHITE,
    (15, 9): WHITE,
    (15, 13): WHITE,
    (15, 14): WHITE,
    (15, 16): BLACK,
    (16, 13): WHITE,
    (16, 14): BLACK,
    (16, 15): BLACK,
}
_WHITE_MOVE = (2, 6)  # after は before に白 G17 が1手加わったペア
_EXPECTED_19_AFTER = {**_EXPECTED_19_BEFORE, _WHITE_MOVE: WHITE}
_EXPECTED_13 = {(2, 2): BLACK, (3, 10): BLACK, (9, 2): WHITE, (9, 9): WHITE}
_EXPECTED_9 = {(2, 6): BLACK, (5, 2): WHITE}


def _recognize_wood_screenshot(path, sizes=(9, 13, 19)):
    from PIL import Image

    from katrain.core.tsumego_capture import classify_wood_intersections, detect_wood_board, detect_wood_grid

    img = Image.open(path)
    board_rect = detect_wood_board(img)
    size, xs, ys = detect_wood_grid(img, board_rect, sizes)
    grid = classify_wood_intersections(img, xs, ys)
    return size, grid, xs, ys


def _stones(grid):
    return {(i, j): v for i, row in enumerate(grid) for j, v in enumerate(row) if v != EMPTY}


# ============================================================
# 認識器単体（実スクショ回帰）
# ============================================================


@pytest.mark.skipif(_SCREENSHOTS_MISSING, reason="木目盤アプリのスクショが未取得")
def test_wood_screenshots_fail_yellow_detector():
    """自動ディスパッチの前提の固定: 木目盤（木地 b≈159）は黄盤検出（b<150 要求）に掛からない。

    これが成立しなくなったら「detect_board 失敗 → 木目盤」の分岐が変わる＝先に気づく必要がある
    """
    from PIL import Image

    from katrain.core.tsumego_capture import CaptureError, detect_board

    for path in _ALL_WOOD:
        with pytest.raises(CaptureError):
            detect_board(Image.open(path))


@pytest.mark.skipif(_SCREENSHOTS_MISSING, reason="木目盤アプリのスクショが未取得")
def test_wood_screenshots_recognized_grids():
    """認識器単体の回帰: 盤サイズ（19/19/13/9）と非空セルの完全一致を固定する。

    19路は盤領域の四辺に座標ラベル帯があり第1線が縁から約 1.4 セル内側（規則配置が破れる）、
    13/9路は帯なし・約半セル＝レイアウトのサイズ差を格子線検出が吸収していることの回帰でもある
    """
    for path, expected_size, expected_stones in [
        (_WOOD19_BEFORE, 19, _EXPECTED_19_BEFORE),
        (_WOOD19_AFTER, 19, _EXPECTED_19_AFTER),
        (_WOOD13, 13, _EXPECTED_13),
        (_WOOD9, 9, _EXPECTED_9),
    ]:
        size, grid, _xs, _ys = _recognize_wood_screenshot(path)
        assert size == expected_size, path
        assert _stones(grid) == expected_stones, path


@pytest.mark.skipif(_SCREENSHOTS_MISSING, reason="木目盤アプリのスクショが未取得")
def test_wood_screenshots_reconcile_detects_white_move():
    """end-to-end 回帰: before の局面に after を reconcile すると白の1手（G17）が move と裁定される"""
    _size, before, _xs, _ys = _recognize_wood_screenshot(_WOOD19_BEFORE)
    _size, after, _xs2, _ys2 = _recognize_wood_screenshot(_WOOD19_AFTER)
    state = WatchState(
        current_grid=before,
        last_move=None,
        to_play=WHITE,
        to_play_is_human=True,  # アプリ側（注入対象）の手番
        ai_can_respond=True,
        move_number=14,
        board_size=len(before),
        previous_grid=None,
    )
    verdict = reconcile(state, after)
    assert verdict.kind == "move"
    assert verdict.move == _WHITE_MOVE


@pytest.mark.skipif(_SCREENSHOTS_MISSING, reason="木目盤アプリのスクショが未取得")
def test_wood_screen_point_uses_detected_lines_not_regular_placement():
    """輪の座標の回帰: 19路のラベル帯レイアウトでは第1線が縁から約 1.4 セル内側にある。

    規則配置（intersection_screen_point）で計算すると第1線は縁から半セル（この盤では約 20px）に
    出て約 0.8 セルずれる。screen_point が検出済みの格子線位置を使っていることを実測値で固定する
    """
    from PIL import Image

    from katrain.core.tsumego_capture import detect_board, detect_size_and_classify

    img = Image.open(_WOOD19_BEFORE)
    monkey_rect = (0, 0, img.size[0], img.size[1])
    reader = AppBoardReader("BlueStacks", [9, 13, 19])
    reader._window_rect = None
    orig_capture_api = bw._capture_api
    bw_capture = lambda: (lambda _t: monkey_rect, lambda _r: img, detect_board, detect_size_and_classify)
    try:
        bw._capture_api = bw_capture
        grid = reader.read()
    finally:
        bw._capture_api = orig_capture_api
    assert _stones(grid) == _EXPECTED_19_BEFORE
    assert reader.size == 19
    x, y, _cell = reader.screen_point(0, 0)
    assert x == pytest.approx(48.3, abs=2.0)  # 実測の第1線位置。規則配置なら約 19.7px
    assert y == pytest.approx(210.5, abs=2.0)


# ============================================================
# 等差フィット（純関数）
# ============================================================


def _fit(peaks, sizes=(9, 13, 19)):
    from katrain.core.tsumego_capture import _wood_fit_line_progression

    return _wood_fit_line_progression(list(peaks), sizes)


def test_fit_line_progression_perfect_peaks():
    peaks = [50.0 + 36.0 * k for k in range(19)]
    fit = _fit(peaks)
    assert fit is not None
    count, positions = fit
    assert count == 19
    assert positions == pytest.approx(peaks)


def test_fit_line_progression_fills_missing_middle_lines():
    """石で隠れて欠けた中間の線は k の飛びとして補完される（密集盤でも幾何が出る）"""
    full = [50.0 + 36.0 * k for k in range(19)]
    sparse = [p for k, p in enumerate(full) if k not in (4, 5, 9, 13)]
    fit = _fit(sparse)
    assert fit is not None
    count, positions = fit
    assert count == 19
    assert positions == pytest.approx(full, abs=0.01)


def test_fit_line_progression_rejects_count_not_in_sizes():
    peaks = [50.0 + 36.0 * k for k in range(11)]  # 11 本は盤サイズにない
    assert _fit(peaks) is None


def test_fit_line_progression_rejects_sparse_coverage():
    full = [50.0 + 36.0 * k for k in range(19)]
    sparse = [full[k] for k in (0, 1, 2, 3, 17, 18)]  # 6/19 = 0.32 < WOOD_FIT_MIN_COVERAGE
    assert _fit(sparse) is None


def test_fit_line_progression_rejects_non_uniform_peaks():
    peaks = [50.0, 86.0, 122.0, 165.0, 194.0]  # 間隔 36/36/43/29＝等差でない
    assert _fit(peaks) is None


def test_grid_screen_point_math():
    xs = (48.0, 84.0, 120.0)
    ys = (210.0, 246.0, 282.0)
    x, y, cell = grid_screen_point((100, 200, 500, 600), xs, ys, 0, 0)
    assert (x, y, cell) == (100 + 48.0, 200 + 210.0, 36.0)
    x, y, _cell = grid_screen_point((100, 200, 500, 600), xs, ys, 2, 1)
    assert (x, y) == (100 + 84.0, 200 + 282.0)  # i=行（y）・j=列（x）


# ============================================================
# AppBoardReader のディスパッチ（_capture_api / _wood_api を差し替えた単体テスト）
# ============================================================


class _FakeImage:
    """crop().tobytes() だけを持つ最小の画像スタブ（test_board_watch.py と同型）"""

    def __init__(self, pixels):
        self.pixels = pixels

    def crop(self, _box):
        return self

    def tobytes(self):
        return self.pixels.encode()


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, sec):
        self.now += sec


def _yellow_fails_api(frames, calls):
    def fake_detect_board(_img):
        calls["yellow_detect"] += 1
        raise RuntimeError("盤面を検出できません（黄盤なし）")

    def fake_detect_size_and_classify(_img, _rect, _sizes):
        raise AssertionError("quest の分類は呼ばれないはず")

    return lambda: (
        lambda _t: (1000, 2000, 1500, 2500),
        lambda _r: frames.pop(0),
        fake_detect_board,
        fake_detect_size_and_classify,
    )


def _wood_harness(monkeypatch, frames):
    """黄盤検出が常に失敗し、木目盤経路が 9 路のダミー幾何を返す reader"""
    calls = {"yellow_detect": 0, "wood_detect": 0, "wood_grid": 0, "wood_classify": 0, "grid_sizes": []}
    geometry = {"rect": (0, 0, 199, 199), "xs": tuple(10.0 + 20.0 * k for k in range(9))}

    def fake_detect_wood_board(_img):
        calls["wood_detect"] += 1
        return geometry["rect"]

    def fake_detect_wood_grid(_img, _rect, sizes):
        calls["wood_grid"] += 1
        calls["grid_sizes"].append(list(sizes))
        return 9, geometry["xs"], geometry["xs"]

    def fake_classify(_img, _xs, _ys):
        calls["wood_classify"] += 1
        grid = [["."] * 9 for _ in range(9)]
        grid[0][0] = str(calls["wood_classify"])  # 呼び出しごとに区別できるようにする
        return grid

    monkeypatch.setattr(bw, "_capture_api", _yellow_fails_api(frames, calls))
    monkeypatch.setattr(bw, "_wood_api", lambda: (fake_detect_wood_board, fake_detect_wood_grid, fake_classify))
    return bw.AppBoardReader("BlueStacks", [9, 13, 19]), calls, geometry


def test_reader_dispatches_to_wood_when_yellow_fails(monkeypatch):
    reader, calls, geometry = _wood_harness(monkeypatch, [_FakeImage("a")])
    grid = reader.read()
    assert grid[0][0] == "1"
    assert reader.size == 9
    assert calls["grid_sizes"] == [[9, 13, 19]]  # フル検出は全サイズ候補
    x, y, cell = reader.screen_point(2, 3)
    assert (x, y, cell) == (1000 + geometry["xs"][3], 2000 + geometry["xs"][2], 20.0)


def test_reader_skips_wood_classification_when_pixels_unchanged(monkeypatch):
    reader, calls, _geometry = _wood_harness(monkeypatch, [_FakeImage("same"), _FakeImage("same")])
    first = reader.read()
    second = reader.read()
    assert calls["wood_classify"] == 1  # 画素が同一なら分類は走らない（指紋の速い経路は wood でも有効）
    assert second == first


def test_reader_does_not_touch_wood_api_when_yellow_board_detected(monkeypatch):
    wood_calls = {"n": 0}

    def spy_wood_api():
        wood_calls["n"] += 1
        raise AssertionError("黄盤が検出できたのに木目盤経路が呼ばれた")

    monkeypatch.setattr(
        bw,
        "_capture_api",
        lambda: (
            lambda _t: (0, 0, 100, 100),
            lambda _r: _FakeImage("a"),
            lambda _img: (0, 0, 10, 10),
            lambda _img, _rect, _sizes: (9, [["."] * 9 for _ in range(9)]),
        ),
    )
    monkeypatch.setattr(bw, "_wood_api", spy_wood_api)
    reader = bw.AppBoardReader("BlueStacks", [9])
    reader.read()
    reader.read()
    assert wood_calls["n"] == 0


def test_reader_raises_yellow_diagnostics_when_both_paths_fail(monkeypatch):
    """黄盤でも木目盤でもない画面（メニュー等）は従来どおり黄盤側の診断で過渡失敗にする"""
    calls = {"yellow_detect": 0}

    def fake_detect_wood_board(_img):
        from katrain.core.tsumego_capture import CaptureError

        raise CaptureError("木目盤を検出できません")

    monkeypatch.setattr(bw, "_capture_api", _yellow_fails_api([_FakeImage("a")], calls))
    monkeypatch.setattr(bw, "_wood_api", lambda: (fake_detect_wood_board, None, None))
    reader = bw.AppBoardReader("BlueStacks", [9])
    with pytest.raises(RuntimeError, match="黄盤なし"):
        reader.read()


def test_reader_refits_wood_lines_when_board_moves_inside_window(monkeypatch):
    clock = FakeClock()
    frames = [_FakeImage("a"), _FakeImage("b"), _FakeImage("c")]
    reader, calls, geometry = _wood_harness(monkeypatch, frames)
    reader.clock = clock
    reader.read()
    assert reader.screen_point(0, 0)[0] == 1000 + 10.0
    clock.advance(bw.BOARD_RECT_RECHECK_SEC)
    geometry["rect"] = (4, 4, 203, 203)  # アプリの中で盤が動いた
    geometry["xs"] = tuple(14.0 + 20.0 * k for k in range(9))
    reader.read()
    assert calls["wood_grid"] == 2
    assert calls["grid_sizes"][-1] == [9]  # 張り替えはキャッシュしたサイズ1候補
    assert reader.screen_point(0, 0)[0] == 1000 + 14.0


def test_reader_reruns_full_detection_after_wood_classification_failure(monkeypatch):
    frames = [_FakeImage("a"), _FakeImage("b"), _FakeImage("c")]
    reader, calls, _geometry = _wood_harness(monkeypatch, frames)
    reader.read()
    monkeypatch.setattr(
        bw,
        "_wood_api",
        lambda: (
            lambda _img: (_ for _ in ()).throw(RuntimeError("判定できない交点があります")),
            None,
            lambda _img, _xs, _ys: (_ for _ in ()).throw(RuntimeError("判定できない交点があります")),
        ),
    )
    with pytest.raises(RuntimeError):
        reader.read()
    assert reader._board_rect is None  # 失敗＝忘れて次周フル検出
    assert reader._profile is None
