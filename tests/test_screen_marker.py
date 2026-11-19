"""AI 着手の強調表示（screen_marker）。輪の幾何は純関数、Win32 の窓は実際に作って
「画面には見えるが自分のキャプチャには写らない」を確かめる（board_watch spec 追記6）"""

import sys
import time

import pytest

from katrain.core.screen_marker import (
    HIGHLIGHT_OFF,
    difficulty_ring_color,
    RING_COLOR,
    RING_COLOR_DEFAULT,
    RING_COLORS,
    ScreenMarker,
    highlight_choices,
    ring_bgra,
    ring_color,
    ring_geometry,
)


def test_ring_bgra_is_an_anti_aliased_premultiplied_ring():
    size, thickness = 40, 6
    data = ring_bgra(size, thickness, (0, 255, 255))
    assert len(data) == size * size * 4
    px = [data[i : i + 4] for i in range(0, len(data), 4)]

    def at(x, y):
        return px[y * size + x]

    assert at(size // 2, size // 2)[3] == 0  # 中心は透明
    stroke = at(size // 2, thickness // 2)  # 上辺の線の真ん中は不透明
    assert stroke[3] == 255 and tuple(stroke[:3]) == (255, 255, 0)  # BGRA で cyan = (B=255, G=255, R=0)
    alphas = {p[3] for p in px}
    assert any(0 < a < 255 for a in alphas), "縁に中間の透明度が無い＝アンチエイリアスされていない"
    assert all(p[0] <= p[3] and p[1] <= p[3] and p[2] <= p[3] for p in px), "事前乗算なら各色 <= α"


def test_ring_color_presets_fall_back_to_the_default_for_unknown_names():
    assert ring_color("magenta") == (255, 0, 255)
    assert ring_color(None) == ring_color("no-such-color") == RING_COLORS[RING_COLOR_DEFAULT] == RING_COLOR
    assert ring_color(HIGHLIGHT_OFF) is None  # "off" ＝表示しない
    assert len(RING_COLORS) >= 4 and all(len(rgb) == 3 for rgb in RING_COLORS.values())
    assert highlight_choices() == [HIGHLIGHT_OFF, *RING_COLORS]  # ドロップダウンは OFF ＋ 色


def test_difficulty_ring_color_keeps_the_three_classes_distinct():
    """難易度の塗り分け（board-watch spec 追記11）: 明らか＝緑・難解＝赤・普通＝設定色。設定色と重なったら
    明らか＝水色・難解＝マゼンタに替えて、どの設定色でも3色が別になる。「表示しない」なら輪を出さない"""
    from katrain.core.move_difficulty import RING_HARD, RING_NORMAL, RING_OBVIOUS

    assert difficulty_ring_color("magenta", RING_OBVIOUS) == RING_COLORS["lime"]
    assert difficulty_ring_color("magenta", RING_HARD) == RING_COLORS["red"]
    assert difficulty_ring_color("magenta", RING_NORMAL) == RING_COLORS["magenta"]
    assert difficulty_ring_color("magenta", None) == RING_COLORS["magenta"]  # 判定なし＝普通の色
    assert difficulty_ring_color("lime", RING_OBVIOUS) == RING_COLORS["cyan"]
    assert difficulty_ring_color("red", RING_HARD) == RING_COLORS["magenta"]
    assert difficulty_ring_color(HIGHLIGHT_OFF, RING_HARD) is None
    for base in [*RING_COLORS, "no-such-color"]:
        colors = {difficulty_ring_color(base, kind) for kind in (RING_OBVIOUS, RING_NORMAL, RING_HARD)}
        assert len(colors) == 3, base


def test_ring_geometry_centers_the_window_on_the_point():
    left, top, size, thickness = ring_geometry(100, 200, 40)
    assert (left, top, size) == (80, 180, 40)
    assert 3 <= thickness < size // 2


def test_ring_geometry_has_a_floor_for_tiny_cells():
    _left, _top, size, thickness = ring_geometry(0, 0, 2)
    assert size == 8 and thickness == 3


win_only = pytest.mark.skipif(sys.platform != "win32", reason="Win32 の窓を実際に作るテスト")


def _wait(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _ring_pixels(left, top, size, color=RING_COLOR):
    """画面座標 (left, top) から size 四方を監視スレッドと同じ撮り方（ImageGrab）で撮り、輪の色の画素数を返す"""
    import ctypes

    from PIL import ImageGrab

    img = ImageGrab.grab(all_screens=True)
    vx = ctypes.windll.user32.GetSystemMetrics(76)
    vy = ctypes.windll.user32.GetSystemMetrics(77)
    patch = img.crop((left - vx, top - vy, left - vx + size, top - vy + size)).convert("RGB")
    px = patch.load()
    return sum(1 for y in range(size) for x in range(size) if px[x, y] == color)


@win_only
def test_marker_is_visible_on_screen_but_excluded_from_capture():
    left, top, size, _thickness = ring_geometry(300, 300, 80)
    before = _ring_pixels(left, top, size)
    marker = ScreenMarker()
    try:
        marker.show(300, 300, 80)
        assert _wait(lambda: marker.visible)
        assert marker.capture_excluded is True
        time.sleep(0.2)
        assert _ring_pixels(left, top, size) == before  # 監視スレッドの撮影には写らない
        # 対照: 除外を外すと同じ撮り方で輪が写る＝このテストが輪を見られることの証明
        import ctypes

        assert ctypes.windll.user32.SetWindowDisplayAffinity(marker._hwnd, 0)
        time.sleep(0.2)
        assert _ring_pixels(left, top, size) > before
        # 色の差し替え（設定画面）: 出したまま塗り直る
        magenta = ring_color("magenta")
        before_magenta = _ring_pixels(left, top, size, magenta)
        marker.set_color(magenta)
        time.sleep(0.3)
        assert _ring_pixels(left, top, size, magenta) > before_magenta
        assert _ring_pixels(left, top, size) == before  # シアンは消えた
        marker.hide()
        assert _wait(lambda: not marker.visible)
    finally:
        marker.close()
    assert marker._hwnd is None


@win_only
def test_marker_never_shows_when_capture_exclusion_fails(monkeypatch):
    monkeypatch.setattr(ScreenMarker, "_exclude_from_capture", staticmethod(lambda hwnd: False))
    logs = []
    marker = ScreenMarker(log=logs.append)
    try:
        marker.show(300, 300, 80)
        assert _wait(lambda: marker.capture_excluded is not None)
        time.sleep(0.1)
        assert marker.capture_excluded is False
        assert not marker.visible
        assert logs and "除外" in logs[0]
    finally:
        marker.close()


@win_only
def test_marker_show_and_hide_are_idempotent_and_safe_after_close():
    marker = ScreenMarker()
    marker.hide()  # 何も出していない状態の hide はスレッドすら起こさない
    assert marker._thread is None
    marker.close()
    marker.show(300, 300, 80)  # close 後の show は無視
    assert marker._thread is None


# --- 複数候補の表示（board-watch spec 追記15）: 輪の内側の字・細い輪・複数の窓 ---


def _alpha_count(data, size, box):
    """box=(x0, y0, x1, y1) の中の α>0 の画素数"""
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if data[(y * size + x) * 4 + 3] > 0)


def test_mark_without_text_is_byte_identical_to_the_plain_ring():
    from katrain.core.screen_marker import mark_bgra

    assert mark_bgra(40, 6, (0, 255, 255)) == ring_bgra(40, 6, (0, 255, 255))
    assert mark_bgra(40, 6, (0, 255, 255), "") == ring_bgra(40, 6, (0, 255, 255))


def test_mark_draws_glyphs_inside_the_ring_premultiplied():
    from katrain.core.screen_marker import load_font, mark_bgra

    size, thickness = 56, 4
    if load_font(20) is None:
        pytest.skip("日本語フォントが無い環境")
    plain = ring_bgra(size, thickness, (0, 255, 255))
    marked = mark_bgra(size, thickness, (0, 255, 255), "最")
    assert len(marked) == len(plain) and marked != plain
    center = (size // 4, size // 4, size * 3 // 4, size * 3 // 4)
    assert _alpha_count(plain, size, center) == 0 and _alpha_count(marked, size, center) > 50
    px = [marked[i : i + 4] for i in range(0, len(marked), 4)]
    assert all(p[0] <= p[3] and p[1] <= p[3] and p[2] <= p[3] for p in px), "事前乗算なら各色 <= α"
    # 字は白＋黒い縁取り（輪の色に依らず読める）。輪だけの絵には白も黒も無い
    def count(data, bgr):
        return sum(1 for i in range(0, len(data), 4) if data[i + 3] == 255 and tuple(data[i : i + 3]) == bgr)

    assert count(marked, (255, 255, 255)) > 20 and count(marked, (0, 0, 0)) > 20
    assert count(plain, (255, 255, 255)) == 0 and count(plain, (0, 0, 0)) == 0


def test_mark_without_a_font_falls_back_to_the_plain_ring(tmp_path):
    from katrain.core.screen_marker import mark_bgra

    assert mark_bgra(40, 6, (0, 255, 255), "最", font_directory=str(tmp_path)) == ring_bgra(40, 6, (0, 255, 255))


def test_glyph_layout_keeps_every_glyph_inside_the_window():
    from katrain.core.screen_marker import glyph_layout

    for size in (30, 38, 56, 80):
        for count in (1, 2, 3, 4, 7):
            height, centers = glyph_layout(count, size)
            assert len(centers) == min(count, 4)
            for cx, cy in centers:
                assert height / 2 <= cx <= size - height / 2 and height / 2 <= cy <= size - height / 2
    assert glyph_layout(1, 38)[0] > glyph_layout(2, 38)[0] >= 15  # 19路相当（38px）の2字でも 15px 以上


def test_thin_ring_geometry_for_the_other_candidates():
    from katrain.core.screen_marker import RING_THIN_THICKNESS_RATIO

    _l, _t, size, thick = ring_geometry(100, 100, 60)
    _l, _t, size2, thin = ring_geometry(100, 100, 60, RING_THIN_THICKNESS_RATIO)
    assert size == size2 and thin < thick


def test_show_carries_text_thickness_and_color_in_one_target(monkeypatch):
    marker = ScreenMarker()
    monkeypatch.setattr(marker, "_kick", lambda: None)  # 窓は作らない（目標状態だけ見る）
    marker.show(100, 100, 60)
    assert marker._target == (*ring_geometry(100, 100, 60), "")
    marker.show(100, 100, 60, text="罠", thick=False, color=(255, 0, 255))
    assert marker._target[3] < ring_geometry(100, 100, 60)[3] and marker._target[4] == "罠"
    assert marker._color == (255, 0, 255)


def test_marker_set_fills_slots_in_order_and_hides_the_rest(monkeypatch):
    from katrain.core.screen_marker import MARKER_SLOTS, MarkerSet

    markers = MarkerSet()
    assert len(markers.markers) == MARKER_SLOTS == 4
    for m in markers.markers:
        monkeypatch.setattr(m, "_kick", lambda: None)
    markers.show([(100, 100, 60, "罠", True, (255, 0, 0)), (200, 100, 60, "最", False, (0, 255, 255))])
    first, second, third, fourth = markers.markers
    assert first._target[4] == "罠" and first._color == (255, 0, 0)
    assert second._target[4] == "最" and second._target[3] < first._target[3]
    assert third._target is None and fourth._target is None
    markers.show([(100, 100, 60, "", True, (255, 0, 0))])  # 候補が減ったら余った輪は消える
    assert first._target[4] == "" and second._target is None
    markers.hide()
    assert all(m._target is None for m in markers.markers)


@win_only
def test_marker_set_shows_several_windows_and_hides_all_of_them():
    from katrain.core.screen_marker import MarkerSet

    markers = MarkerSet()
    try:
        markers.show([(300, 300, 60, "罠", True, RING_COLOR), (380, 300, 60, "最", False, RING_COLOR)])
        first, second, third, _fourth = markers.markers
        assert _wait(lambda: first.visible and second.visible)
        assert first.capture_excluded is True and second.capture_excluded is True  # どの窓も監視の撮影に写らない
        assert third._thread is None  # 使わない窓はスレッドも起こさない
        markers.hide()
        assert _wait(lambda: not first.visible and not second.visible)
    finally:
        markers.close()
    assert all(m._hwnd is None for m in markers.markers)
