"""AI 着手の強調表示（screen_marker）。輪の幾何は純関数、Win32 の窓は実際に作って
「画面には見えるが自分のキャプチャには写らない」を確かめる（board_watch spec 追記6）"""

import sys
import time

import pytest

from katrain.core.screen_marker import (
    HIGHLIGHT_OFF,
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
