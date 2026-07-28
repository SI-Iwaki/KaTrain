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


def classify_intersections(img, board_rect, board_size=DEFAULT_BOARD_SIZE):
    """各交点を "B"（黒石）/"W"（白石）/"."（空点）に分類した board_size x board_size のグリッドを返す。

    格子は規則配置前提: セル幅 = 盤幅/board_size、第1線は盤端から半セル内側。
    判定はパッチ平均色: 低輝度=黒石、低彩度かつ高輝度=白石、黄色系=空点。どれでもなければ CaptureError。
    """
    x0, y0, x1, y1 = board_rect
    cell_w = (x1 - x0 + 1) / board_size
    cell_h = (y1 - y0 + 1) / board_size
    rgb = img.convert("RGB")
    rad = max(2, int(min(cell_w, cell_h) * 0.25))
    grid = []
    ambiguous = []
    for i in range(board_size):
        row = []
        for j in range(board_size):
            cx = x0 + cell_w * (j + 0.5)
            cy = y0 + cell_h * (i + 0.5)
            patch = rgb.crop((int(cx) - rad, int(cy) - rad, int(cx) + rad + 1, int(cy) + rad + 1))
            mr, mg, mb = ImageStat.Stat(patch).mean
            brightness = (mr + mg + mb) / 3
            spread = max(mr, mg, mb) - min(mr, mg, mb)
            if brightness < 90:
                row.append("B")
            elif spread < 60 and brightness > 160:
                row.append("W")
            elif spread > 90 and mr > mb:
                row.append(".")
            else:
                ambiguous.append((i, j, (round(mr), round(mg), round(mb))))
                row.append("?")
        grid.append(row)
    if ambiguous:
        raise CaptureError(f"判定できない交点があります（先頭5件: {ambiguous[:5]}）")
    return grid
