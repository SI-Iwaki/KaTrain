"""BlueStacks上の詰碁アプリ盤面をキャプチャ・認識して13路SGFにする（Kivy非依存・PILのみ使用）"""

import ctypes
import ctypes.wintypes

from PIL import Image, ImageGrab, ImageStat

DEFAULT_WINDOW_TITLE = "BlueStacks"
DEFAULT_BOARD_SIZE = 13
DETECT_SCALE = 4  # 盤検出時の縮小率


class CaptureError(Exception):
    """盤面キャプチャ・認識の失敗（ユーザー向けメッセージ付き）"""


def _is_yellow(r, g, b):
    # サンプル画像の盤色 約RGB(247,193,62)。木目・照明ムラを許容する広めの閾値
    return r > 170 and g > 120 and b < 150 and (r - b) > 60


def detect_board(img):
    """画像内の黄色い碁盤領域の bbox (x0, y0, x1, y1) を返す（両端含む）"""
    w, h = img.size
    thumb = img.convert("RGB").resize((max(1, w // DETECT_SCALE), max(1, h // DETECT_SCALE)), Image.NEAREST)
    tw, th = thumb.size
    px = thumb.load()
    row_counts = [0] * th
    col_counts = [0] * tw
    for y in range(th):
        for x in range(tw):
            if _is_yellow(*px[x, y][:3]):
                row_counts[y] += 1
                col_counts[x] += 1
    max_row = max(row_counts, default=0)
    max_col = max(col_counts, default=0)
    if max_row < tw * 0.25 or max_col < th * 0.25:
        raise CaptureError("盤面を検出できません（盤が画面に表示されているか確認してください）")
    rows = [y for y, c in enumerate(row_counts) if c >= max_row * 0.5]
    cols = [x for x, c in enumerate(col_counts) if c >= max_col * 0.5]
    x0, x1 = cols[0] * DETECT_SCALE, (cols[-1] + 1) * DETECT_SCALE - 1
    y0, y1 = rows[0] * DETECT_SCALE, (rows[-1] + 1) * DETECT_SCALE - 1
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if min(bw, bh) < 300 or not (0.9 < bw / bh < 1.1):
        raise CaptureError(f"盤面の形が不正です（検出領域 {bw}x{bh}。盤が隠れていないか確認してください）")
    return (x0, y0, x1, y1)
