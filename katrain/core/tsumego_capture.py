"""BlueStacks上の詰碁アプリ盤面をキャプチャ・認識して13路SGFにする（Kivy非依存・PILのみ使用）"""

import ctypes
import ctypes.wintypes

from PIL import Image, ImageGrab, ImageStat

DEFAULT_WINDOW_TITLE = "BlueStacks"
DEFAULT_BOARD_SIZE = 13
DEFAULT_BOARD_SIZES = (9, 13, 19)  # 自動判定の試行順（詰碁アプリは問題により盤サイズが変わる）
DETECT_SCALE = 4  # 盤検出時の縮小率


class CaptureError(Exception):
    """盤面キャプチャ・認識の失敗（ユーザー向けメッセージ付き）"""


def ensure_dpi_awareness():
    """プロセスのDPI仮想化を無効化する（1回だけ・ベストエフォート）。既に設定済みならHRESULTが失敗を返すが実害なし"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        pass


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


def grid_to_sgf(grid, komi=6.5):
    """認識グリッドを黒番の SGF 文字列にする（AB/AW 配置・PL[B]）"""
    size = len(grid)
    ab = [chr(97 + j) + chr(97 + i) for i, row in enumerate(grid) for j, v in enumerate(row) if v == "B"]
    aw = [chr(97 + j) + chr(97 + i) for i, row in enumerate(grid) for j, v in enumerate(row) if v == "W"]
    if not ab and not aw:
        raise CaptureError("石が1つも見つかりません（詰碁が表示されているか確認してください）")
    sgf = f"(;GM[1]FF[4]CA[UTF-8]SZ[{size}]KM[{komi}]PL[B]"
    if ab:
        sgf += "AB" + "".join(f"[{p}]" for p in ab)
    if aw:
        sgf += "AW" + "".join(f"[{p}]" for p in aw)
    return sgf + ")"


def find_window_rect(title_substring):
    """タイトル部分一致（大小無視）で可視ウィンドウを探し、画面座標 (left, top, right, bottom) を返す"""
    user32 = ctypes.windll.user32
    matches = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_substring.lower() in buf.value.lower():
                    rect = ctypes.wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if rect.right - rect.left > 200 and rect.bottom - rect.top > 200:
                        matches.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    user32.EnumWindows(enum_cb, 0)
    if not matches:
        raise CaptureError(f"ウィンドウが見つかりません: {title_substring}（起動・最小化解除を確認してください）")
    return matches[0]


def capture_screen_rect(rect):
    """画面座標 rect の領域をキャプチャして PIL Image を返す（マルチモニタの仮想座標に対応）"""
    left, top, right, bottom = rect
    img = ImageGrab.grab(all_screens=True)
    vx = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    return img.crop((left - vx, top - vy, right - vx, bottom - vy))


def detect_size_and_classify(img, board_rect, sizes=DEFAULT_BOARD_SIZES):
    """候補サイズを順に試し、曖昧交点なしで分類できたサイズとグリッドを返す。

    誤ったサイズでのサンプリングは交点が線・石の境界に落ちて曖昧エラーになるため、
    分類が通ること自体がサイズ判定になる（9/13/19 の相互誤読拒否はテストで固定）
    """
    for size in sizes:
        try:
            return size, classify_intersections(img, board_rect, size)
        except CaptureError:
            continue
    tried = "/".join(str(s) for s in sizes)
    raise CaptureError(f"盤サイズを判定できません（{tried}路のいずれでも曖昧な交点がありました）")


def capture_tsumego_sgf(settings, komi=6.5):
    """ウィンドウ検出→キャプチャ→認識→SGF生成の全体処理。失敗は CaptureError"""
    rect = find_window_rect(settings.get("window_title", DEFAULT_WINDOW_TITLE))
    img = capture_screen_rect(rect)
    board_rect = detect_board(img)
    sizes = [int(s) for s in (settings.get("board_sizes") or DEFAULT_BOARD_SIZES)]
    _size, grid = detect_size_and_classify(img, board_rect, sizes)
    return grid_to_sgf(grid, komi=komi)


def main():
    import os

    os.environ["KIVY_NO_ARGS"] = "1"  # 慣例(本モジュールはKivy非import): Kivyの引数横取り防止
    import argparse

    ensure_dpi_awareness()
    parser = argparse.ArgumentParser(description="Tsumego capture debug CLI")
    parser.add_argument("--image", help="保存済みスクリーンショットを解析（ライブキャプチャの代わり）")
    parser.add_argument("--window", action="store_true", help="ウィンドウからライブキャプチャして解析")
    parser.add_argument("--title", default=DEFAULT_WINDOW_TITLE, help="ウィンドウタイトルの部分一致文字列")
    parser.add_argument("--size", type=int, default=None, help="盤サイズ（省略時は 9/13/19 を自動判定）")
    args = parser.parse_args()
    try:
        if args.image:
            img = Image.open(args.image)
        elif args.window:
            img = capture_screen_rect(find_window_rect(args.title))
        else:
            parser.error("--image か --window を指定してください")
        board_rect = detect_board(img)
        print(f"board rect: {board_rect}")
        sizes = [args.size] if args.size else DEFAULT_BOARD_SIZES
        size, grid = detect_size_and_classify(img, board_rect, sizes)
        print(f"board size: {size}")
    except CaptureError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)
    for row in grid:
        print(" ".join(row))
    print(grid_to_sgf(grid))


if __name__ == "__main__":
    main()
