"""BlueStacks上の詰碁アプリ盤面をキャプチャ・認識して13路SGFにする（Kivy非依存・PILのみ使用）"""

import ctypes
import ctypes.wintypes
from collections import namedtuple

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


def _classify_patch(rgb, cx, cy, rad):
    """交点1点をパッチ平均色で分類し ("B"/"W"/"."/"?", 平均色) を返す。

    低輝度=黒石、低彩度かつ高輝度=白石、黄色系=空点。どれでもなければ "?"（判定不能）
    """
    patch = rgb.crop((int(cx) - rad, int(cy) - rad, int(cx) + rad + 1, int(cy) + rad + 1))
    mr, mg, mb = ImageStat.Stat(patch).mean
    brightness = (mr + mg + mb) / 3
    spread = max(mr, mg, mb) - min(mr, mg, mb)
    if brightness < 90:
        return "B", (mr, mg, mb)
    if spread < 60 and brightness > 160:
        return "W", (mr, mg, mb)
    if spread > 90 and mr > mb:
        return ".", (mr, mg, mb)
    return "?", (mr, mg, mb)


def classify_intersections(img, board_rect, board_size=DEFAULT_BOARD_SIZE):
    """各交点を "B"（黒石）/"W"（白石）/"."（空点）に分類した board_size x board_size のグリッドを返す。

    格子は規則配置前提: セル幅 = 盤幅/board_size、第1線は盤端から半セル内側。
    判定はパッチ平均色（_classify_patch）。判定できない交点があれば CaptureError。
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
            label, means = _classify_patch(rgb, cx, cy, rad)
            if label == "?":
                ambiguous.append((i, j, tuple(round(m) for m in means)))
            row.append(label)
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
    """タイトル部分一致（大小無視）で可視ウィンドウを探し、画面座標 (left, top, right, bottom) を返す。

    カンマ区切りで複数の候補を指定でき（例 "BlueStacks,Puzzle Run"）、先に書いた候補を優先する
    （BlueStacks とブラウザの両方が開いていても従来どおり BlueStacks が選ばれる）
    """
    user32 = ctypes.windll.user32
    titles = [t.strip().lower() for t in title_substring.split(",") if t.strip()]
    matches = {}  # タイトル候補 -> 最初に見つかったウィンドウ矩形

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                window_title = buf.value.lower()
                for t in titles:
                    if t in window_title and t not in matches:
                        rect = ctypes.wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        if rect.right - rect.left > 200 and rect.bottom - rect.top > 200:
                            matches[t] = (rect.left, rect.top, rect.right, rect.bottom)
        return True

    user32.EnumWindows(enum_cb, 0)
    for t in titles:
        if t in matches:
            return matches[t]
    raise CaptureError(f"ウィンドウが見つかりません: {title_substring}（起動・最小化解除を確認してください）")


def capture_screen_rect(rect):
    """画面座標 rect の領域をキャプチャして PIL Image を返す（マルチモニタの仮想座標に対応）"""
    left, top, right, bottom = rect
    img = ImageGrab.grab(all_screens=True)
    vx = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    return img.crop((left - vx, top - vy, right - vx, bottom - vy))


GRID_SCORE_MIN = 0.5  # 正解サイズは概ね0.8超、誤サイズは0.2未満になる（実サンプルで確認）
GRID_SCORE_MARGIN = 0.15


def _grid_line_score(rgb, board_rect, size):
    """候補サイズの想定縦線位置（交点間の中点）に実際に暗い線ピクセルがある割合を返す。

    石に隠れた点（7x7パッチが黒石の暗さ or 白石の明るさ）は分母から除外する。
    正しいサイズなら線上の点ばかりでスコア≈1、誤ったサイズなら線間の黄色に落ちてスコア≈0.1
    """
    x0, y0, x1, y1 = board_rect
    cell_w = (x1 - x0 + 1) / size
    cell_h = (y1 - y0 + 1) / size
    px = rgb.load()
    w, h = rgb.size
    hits = total = 0
    for j in range(size):
        lx = int(x0 + cell_w * (j + 0.5))
        for k in range(size - 1):
            ly = int(y0 + cell_h * (k + 1.0))  # 縦線上かつ横線と重ならない中点
            if not (4 <= lx < w - 4 and 4 <= ly < h - 4):
                continue
            patch = rgb.crop((lx - 3, ly - 3, lx + 4, ly + 4))
            mr, mg, mb = ImageStat.Stat(patch).mean
            brightness = (mr + mg + mb) / 3
            spread = max(mr, mg, mb) - min(mr, mg, mb)
            if brightness < 95 or (brightness > 185 and spread < 60):
                continue  # 石の内部に隠れている
            total += 1
            if any((sum(px[lx + dx, ly][:3]) / 3) < 150 for dx in range(-3, 4)):
                hits += 1
    return hits / total if total else 0.0


def detect_size_and_classify(img, board_rect, sizes=DEFAULT_BOARD_SIZES):
    """格子線の位置から盤サイズを判定し、そのサイズで分類したグリッドを返す。

    「曖昧エラーが出なければ採用」方式は、石が少ない盤でサンプル点が偶然
    境界を踏まないと誤サイズが成立してしまうため、格子線検出で判定する
    """
    rgb = img.convert("RGB")
    scores = {size: _grid_line_score(rgb, board_rect, size) for size in sizes}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_size, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score < GRID_SCORE_MIN or best_score - second_score < GRID_SCORE_MARGIN:
        detail = ", ".join(f"{s}:{v:.2f}" for s, v in scores.items())
        raise CaptureError(f"盤サイズを判定できません（格子線スコア {detail}）")
    return best_size, classify_intersections(img, board_rect, best_size)


# ============================================================
# Web 盤面認識（PlayGo.gg 等）: 格子線検出方式
#
# BlueStacks の詰碁アプリは「黄色領域の縁＝盤の端・第1線は半セル内側」の規則配置だが、
# Web サイトの盤は (a) 黄色の盤画像の内側に座標ラベル帯（A〜T・1〜19）を持ち、
# (b) 問題に合わせて盤の一部だけを表示する（部分表示）ことがある。そこで黄色領域からの
# 割り算ではなく、格子線そのもの（黄色地の上の細い暗線）を検出して格子を決め、ラベル帯の
# 文字を読んで盤サイズと絶対座標を確定する。認識の入口 recognize_board は既存方式
# （detect_size_and_classify）を先に試すので BlueStacks 経路の挙動は不変。
# 実測データ・生成スクリプトは docs/superpowers/specs/calibration-data/tsumego-web/ 参照
# ============================================================

WEB_EDGE_PAD = 3  # 盤領域の縁の暗色アーティファクト（境界線・アンチエイリアス）除去幅
WEB_THIN_GAP = 6  # 「細い暗線」判定: 両側 gap px が非暗なら線候補（石・影の太い暗塊を除外）
WEB_LINE_MIN_FRACTION = 0.25  # 盤範囲のこの割合以上が線画素なら格子線とみなす
WEB_LINE_DARK = 145  # 格子線の暗判定閾値（等重み輝度。実測: 1線目の薄い線 114・木地 178）
WEB_GLYPH_DARK = 90  # ラベル文字の暗判定閾値（実測: 文字色 51、木目の暗い筋の大半は 90 超）
WEB_GLYPH_MIN_H, WEB_GLYPH_MAX_H = 8, 30  # ラベルはズーム非依存の固定UIフォント（実測 h=13-14px）
WEB_GLYPH_MAX_W = 30
WEB_GLYPH_MIN_PX = 12  # これ未満の暗画素数の成分は木目ノイズ
WEB_GLYPH_MAX_DISTANCE = 45  # 正規化ビットマップ 10x14=140bit 中の許容ハミング距離（実測は 15 以下）
WEB_GLYPH_NORM_W, WEB_GLYPH_NORM_H = 10, 14
COL_LETTERS = "ABCDEFGHJKLMNOPQRST"  # I を飛ばす囲碁座標

BoardView = namedtuple("BoardView", "grid kind cropped_sides size_fallback")
# kind: "app"=従来の全面盤（BlueStacks）/ "web_full"=Web の全体表示 / "web_partial"=Web の部分表示


def _web_mean_gray(rgb):
    """等重み輝度のグレースケール。PIL 既定の "L"（緑重視）だと1線目の薄い線 RGB(140,123,80) が
    L=123 になり暗判定を外れる（等重みなら 114）"""
    return rgb.convert("L", (1 / 3, 1 / 3, 1 / 3, 0))


def _web_thin_profile(gray, box, axis):
    """axis='v': 各列の細い暗画素割合 / axis='h': 各行。両側 WEB_THIN_GAP px が非暗の画素だけ
    数えることで、石・影・木目の太い暗塊を除外して格子線だけを拾う"""
    x0, y0, x1, y1 = box
    px = gray.load()
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    iw, ih = gray.size

    def dark(x, y):
        return 0 <= x < iw and 0 <= y < ih and px[x, y] < WEB_LINE_DARK

    prof = []
    if axis == "v":
        for x in range(x0, x1 + 1):
            c = sum(
                1 for y in range(y0, y1 + 1) if dark(x, y) and not dark(x - WEB_THIN_GAP, y) and not dark(x + WEB_THIN_GAP, y)
            )
            prof.append(c / h)
    else:
        for y in range(y0, y1 + 1):
            c = sum(
                1 for x in range(x0, x1 + 1) if dark(x, y) and not dark(x, y - WEB_THIN_GAP) and not dark(x, y + WEB_THIN_GAP)
            )
            prof.append(c / w)
    return prof


def _web_runs(profile, thresh):
    """閾値以上が連続する帯を1本にまとめ、中心位置のリストを返す"""
    out = []
    run = []
    for i, v in enumerate(profile):
        if v >= thresh:
            run.append(i)
        elif run:
            out.append(sum(run) / len(run))
            run = []
    if run:
        out.append(sum(run) / len(run))
    return out


def _web_fit_uniform(cands, extent):
    """候補位置を等間隔グリッドにフィットし (位置リスト, 間隔) を返す。内側の欠け（石で隠れた線）は
    補間し、縁のアーティファクト（等間隔に乗らない位置）は外れ値として捨てる"""
    cands = [c for c in cands if WEB_EDGE_PAD <= c <= extent - 1 - WEB_EDGE_PAD]
    if len(cands) < 4:
        raise CaptureError(f"格子線が少なすぎます（検出 {len(cands)} 本）")
    gaps = sorted(b - a for a, b in zip(cands, cands[1:]))
    spacing = gaps[len(gaps) // 2]
    best = None
    for base in cands:
        idx = {}
        for c in cands:
            k = round((c - base) / spacing)
            if abs(c - (base + k * spacing)) <= spacing * 0.15 and k not in idx:
                idx[k] = c
        if best is None or len(idx) > len(best):
            best = idx
    ks = sorted(best)
    n = len(ks)
    mean_k = sum(ks) / n
    mean_p = sum(best[k] for k in ks) / n
    denom = sum((k - mean_k) ** 2 for k in ks)
    if denom > 0:
        spacing = sum((k - mean_k) * (best[k] - mean_p) for k in ks) / denom
    base = mean_p - spacing * mean_k
    return [base + spacing * k for k in range(ks[0], ks[-1] + 1)], spacing


def _web_extend_hidden_lines(rgb, positions, spacing, other_positions, lo, hi, axis):
    """端の線が石で完全に埋まってプロファイルに出なかった場合の外挿。
    外挿位置の交点に石の色が見えるときだけ線として追加する（ラベル帯の文字では発火しない）"""
    rad = max(2, int(spacing * 0.25))
    changed = True
    while changed:
        changed = False
        for cand in (positions[0] - spacing, positions[-1] + spacing):
            if not (lo + spacing * 0.2 <= cand <= hi - spacing * 0.2):
                continue
            stones = 0
            for q in other_positions:
                cx, cy = (cand, q) if axis == "v" else (q, cand)
                if _classify_patch(rgb, cx, cy, rad)[0] in "BW":
                    stones += 1
            if stones:
                positions.insert(0, cand) if cand < positions[0] else positions.append(cand)
                changed = True
    return positions


def _web_detect_lines(rgb, board_rect):
    """格子線の位置を検出して (縦線x座標列, 横線y座標列, 縦間隔, 横間隔) を返す"""
    gray = _web_mean_gray(rgb)
    x0, y0, x1, y1 = board_rect
    vpos, vsp = _web_fit_uniform(_web_runs(_web_thin_profile(gray, board_rect, "v"), WEB_LINE_MIN_FRACTION), x1 - x0 + 1)
    hpos, hsp = _web_fit_uniform(_web_runs(_web_thin_profile(gray, board_rect, "h"), WEB_LINE_MIN_FRACTION), y1 - y0 + 1)
    vpos = [p + x0 for p in vpos]
    hpos = [p + y0 for p in hpos]
    vpos = _web_extend_hidden_lines(rgb, vpos, vsp, hpos, x0, x1, "v")
    hpos = _web_extend_hidden_lines(rgb, hpos, hsp, vpos, y0, y1, "h")
    return vpos, hpos, vsp, hsp


def _web_band_boxes(board_rect, vpos, hpos, vsp, hsp):
    """4辺のラベル帯領域 {side: box or None}。帯幅 0.55 セル未満なら None（そちら側は切れている）。
    帯の内側境界も最外線から 0.55 セル（石の半径の外）に取り、1線の石のはみ出しを帯に入れない"""
    x0, y0, x1, y1 = board_rect
    out = {}
    for side, box, width, cell in (
        ("left", (x0, int(hpos[0] - hsp / 2), int(vpos[0] - vsp * 0.55), int(hpos[-1] + hsp / 2)), vpos[0] - x0, vsp),
        ("right", (int(vpos[-1] + vsp * 0.55), int(hpos[0] - hsp / 2), x1, int(hpos[-1] + hsp / 2)), x1 - vpos[-1], vsp),
        ("top", (int(vpos[0] - vsp / 2), y0, int(vpos[-1] + vsp / 2), int(hpos[0] - hsp * 0.55)), hpos[0] - y0, hsp),
        ("bottom", (int(vpos[0] - vsp / 2), int(hpos[-1] + hsp * 0.55), int(vpos[-1] + vsp / 2), y1), y1 - hpos[-1], hsp),
    ):
        out[side] = box if width >= cell * 0.55 else None
    return out


def _web_glyph_components(rgb, box):
    """帯領域内の暗画素連結成分のうちラベル文字らしいものだけ (x0, y0, x1, y1, 画素数) で返す。
    帯の境界に接する成分（石のはみ出し・盤領域の縁）とサイズ外の成分（木目ノイズ）は捨てる"""
    bx0, by0, bx1, by1 = box
    bx0, by0 = max(bx0, 0), max(by0, 0)
    bx1, by1 = min(bx1, rgb.size[0] - 1), min(by1, rgb.size[1] - 1)
    if bx1 <= bx0 or by1 <= by0:
        return []
    g = _web_mean_gray(rgb.crop((bx0, by0, bx1 + 1, by1 + 1)))
    w, h = g.size
    px = g.load()
    seen = [[False] * w for _ in range(h)]
    comps = []
    for sy in range(h):
        for sx in range(w):
            if seen[sy][sx] or px[sx, sy] >= WEB_GLYPH_DARK:
                continue
            stack = [(sx, sy)]
            seen[sy][sx] = True
            pts = []
            while stack:
                cx, cy = stack.pop()
                pts.append((cx, cy))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and px[nx, ny] < WEB_GLYPH_DARK:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            gx0, gy0, gx1, gy1 = min(xs), min(ys), max(xs), max(ys)
            gw, gh = gx1 - gx0 + 1, gy1 - gy0 + 1
            if not (WEB_GLYPH_MIN_H <= gh <= WEB_GLYPH_MAX_H and gw <= WEB_GLYPH_MAX_W and len(pts) >= WEB_GLYPH_MIN_PX):
                continue
            if gx0 == 0 or gy0 == 0 or gx1 == w - 1 or gy1 == h - 1:
                continue
            comps.append((gx0 + bx0, gy0 + by0, gx1 + bx0, gy1 + by0, len(pts)))
    return comps


def _web_glyph_bitmap(rgb, comp):
    """グリフ bbox を切り出して 10x14 の二値ビットマップ（行タプルのタプル）に正規化する。
    LANCZOS で4倍中間サイズへ→BOX で縮小、の2段は小さいグリフの角の情報を保つため"""
    x0, y0, x1, y1, _ = comp
    g = _web_mean_gray(rgb.crop((x0, y0, x1 + 1, y1 + 1)))
    g = g.resize((WEB_GLYPH_NORM_W * 4, WEB_GLYPH_NORM_H * 4), Image.LANCZOS).resize(
        (WEB_GLYPH_NORM_W, WEB_GLYPH_NORM_H), Image.BOX
    )
    px = g.load()
    return tuple(
        tuple(1 if px[x, y] < 128 else 0 for x in range(WEB_GLYPH_NORM_W)) for y in range(WEB_GLYPH_NORM_H)
    )


def _web_bitmap_distance(a, b):
    return sum(av != bv for ra, rb in zip(a, b) for av, bv in zip(ra, rb))


def _web_templates():
    """埋め込みテンプレート（tsumego_capture_glyphs）をビットマップ形式に展開する（初回のみ）"""
    global _WEB_TEMPLATE_CACHE
    if _WEB_TEMPLATE_CACHE is None:
        from katrain.core.tsumego_capture_glyphs import GLYPH_TEMPLATES

        _WEB_TEMPLATE_CACHE = {
            ch: [tuple(tuple(1 if c == "#" else 0 for c in row) for row in s.split("/")) for s in samples]
            for ch, samples in GLYPH_TEMPLATES.items()
        }
    return _WEB_TEMPLATE_CACHE


_WEB_TEMPLATE_CACHE = None


def _web_classify_glyph(rgb, comp, alphabet):
    """グリフを alphabet 内の文字に分類する。テンプレートから遠すぎる場合は None（ノイズ）"""
    bmp = _web_glyph_bitmap(rgb, comp)
    templates = _web_templates()
    dist, char = min(
        (min(_web_bitmap_distance(bmp, t) for t in templates[ch]), ch) for ch in templates if ch in alphabet
    )
    return char if dist <= WEB_GLYPH_MAX_DISTANCE else None


def _web_read_band(rgb, side, box, vpos, hpos, vsp, hsp):
    """帯のグリフを最寄りの線に割り当て {線インデックス: [グリフcomp, ...]}（複数桁は左→右）を返す"""
    comps = _web_glyph_components(rgb, box)
    lines = vpos if side in ("top", "bottom") else hpos
    spacing = vsp if side in ("top", "bottom") else hsp
    assigned = {}
    for c in comps:
        center = (c[0] + c[2]) / 2 if side in ("top", "bottom") else (c[1] + c[3]) / 2
        best = min(range(len(lines)), key=lambda i: abs(lines[i] - center))
        if abs(lines[best] - center) <= spacing * 0.45:
            assigned.setdefault(best, []).append(c)
    return {i: sorted(cs, key=lambda c: c[0]) for i, cs in assigned.items()}


def _web_fit_axis(votes, what):
    """ラベル読みの票（座標値+線indexの和 or 差）から軸の定数を多数決で決める。
    3分の2以上が一致しない読みは不安定として弾く"""
    if not votes:
        raise CaptureError(f"{what}の座標ラベルが読めません（盤の端が画面内にあるか確認してください）")
    votes = sorted(votes)
    c = votes[len(votes) // 2]
    matching = sum(1 for v in votes if v == c)
    if matching < max(2, (len(votes) * 2 + 2) // 3) and len(votes) > 1:
        raise CaptureError(f"{what}の座標ラベルの読み取りが不安定です（票: {votes}）")
    return c


def recognize_web_board(img, board_rect, sizes=DEFAULT_BOARD_SIZES):
    """Web 盤面（格子線＋座標ラベル）を認識し BoardView を返す。失敗は CaptureError。

    - 格子線を検出し、ラベル帯の有無で「どの辺が盤の端か」を判定する（ラベルのある辺＝端が
      見えている。ラベルなしで線が縁まで届く辺＝そこで切れている）
    - 行番号（左右帯の数字）・列文字（上下帯の文字）を読んで可視域の絶対座標を確定する
    - 盤サイズは「上端が見えていれば最上行の番号」「右端が見えていれば最右列の文字」から決まる。
      どちらも切れている場合は可視域が収まる最小の候補サイズに倒す（size_fallback=True）
    - 石は盤サイズの全面グリッドに絶対座標で配置して返す（可視域の外は空点）。これにより
      部分表示の詰碁も従来の枠張り・ソルバ・回答帳の経路にそのまま乗る
    """
    rgb = img.convert("RGB")
    vpos, hpos, vsp, hsp = _web_detect_lines(rgb, board_rect)
    bands = _web_band_boxes(board_rect, vpos, hpos, vsp, hsp)
    reads = {}
    edge = {}
    for side in ("left", "right", "top", "bottom"):
        n_lines = len(vpos if side in ("top", "bottom") else hpos)
        reads[side] = _web_read_band(rgb, side, bands[side], vpos, hpos, vsp, hsp) if bands[side] else {}
        edge[side] = len(reads[side]) >= max(2, n_lines // 3)
    digits = set("0123456789")
    row_votes = []
    for side in ("left", "right"):
        for i, comps in reads[side].items():
            if len(comps) > 2:
                continue
            chars = [_web_classify_glyph(rgb, c, digits) for c in comps]
            if None in chars:
                continue
            num = int("".join(chars))
            if 1 <= num <= 19:
                row_votes.append(num + i)  # 行番号は上から下へ1ずつ減る: num + index = 一定
    row_c = _web_fit_axis(row_votes, "行")
    letters = set(COL_LETTERS)
    col_votes = []
    for side in ("top", "bottom"):
        for i, comps in reads[side].items():
            if len(comps) != 1:
                continue
            ch = _web_classify_glyph(rgb, comps[0], letters)
            if ch is not None:
                col_votes.append(COL_LETTERS.index(ch) + 1 - i)  # 列は左から右へ1ずつ増える
    col_c = _web_fit_axis(col_votes, "列")

    def row_of(i):
        return row_c - i

    def col_of(j):
        return col_c + j

    size = None
    if edge["top"]:
        size = row_of(0)  # 上端が見えている＝最上行の番号が盤サイズ
    if edge["right"]:
        s2 = col_of(len(vpos) - 1)
        if size is not None and s2 != size:
            raise CaptureError(f"盤サイズが行と列で一致しません（行 {size} / 列 {s2}）")
        size = size or s2
    size_fallback = False
    if size is None:
        # 上端も右端も切れている: サイズを確定できる情報が画面に無い。可視域＋切れた側の最低1線が
        # 収まる最小の候補サイズに倒す（詰碁は局所の死活なので、開き方向の余白の過不足は稀にしか効かない）
        need = max(row_of(0), col_of(len(vpos) - 1)) + 1
        size = min((s for s in sizes if s >= need), default=None)
        if size is None:
            raise CaptureError(f"盤サイズを推定できません（可視域だけで {need} 路が必要）")
        size_fallback = True
    if not (row_of(len(hpos) - 1) >= 1 and col_of(0) >= 1 and row_of(0) <= size and col_of(len(vpos) - 1) <= size):
        raise CaptureError(
            f"座標ラベルの読み取りが不整合です（行 {row_of(0)}..{row_of(len(hpos) - 1)} / "
            f"列 {col_of(0)}..{col_of(len(vpos) - 1)} / 盤 {size}路）"
        )
    cropped_sides = tuple(side for side in ("left", "right", "top", "bottom") if not edge[side])
    if not cropped_sides and not (size == len(vpos) == len(hpos)):
        raise CaptureError(f"格子線の本数（{len(vpos)}x{len(hpos)}）が盤サイズ（{size}路）と一致しません")
    rad = max(2, int(min(vsp, hsp) * 0.25))
    grid = [["." for _ in range(size)] for _ in range(size)]
    ambiguous = []
    for i, y in enumerate(hpos):
        for j, x in enumerate(vpos):
            label, means = _classify_patch(rgb, x, y, rad)
            if label == "?":
                ambiguous.append((f"{COL_LETTERS[col_of(j) - 1]}{row_of(i)}", tuple(round(m) for m in means)))
            elif label in "BW":
                grid[size - row_of(i)][col_of(j) - 1] = label
    if ambiguous:
        raise CaptureError(f"判定できない交点があります（先頭5件: {ambiguous[:5]}）")
    kind = "web_full" if not cropped_sides else "web_partial"
    return BoardView(grid, kind, cropped_sides, size_fallback)


def recognize_board(img, sizes=DEFAULT_BOARD_SIZES):
    """盤面画像を認識して BoardView を返す。従来方式（BlueStacks 型の全面盤）を先に試し、
    失敗したときだけ Web 方式（格子線＋座標ラベル）にフォールバックする＝既存経路は不変"""
    board_rect = detect_board(img)
    try:
        _size, grid = detect_size_and_classify(img, board_rect, sizes)
        return BoardView(grid, "app", (), False)
    except CaptureError as app_err:
        try:
            return recognize_web_board(img, board_rect, sizes)
        except CaptureError as web_err:
            raise CaptureError(f"{app_err} ／ Web盤面認識も失敗: {web_err}")


def capture_board_view(settings):
    """ウィンドウ検出→キャプチャ→認識を行い BoardView を返す。失敗は CaptureError。

    SGF ではなくグリッドを返すのは、呼び出し側が枠適用（非コア石の除去を含む）を
    してから局面を確定する必要があるため。
    """
    rect = find_window_rect(settings.get("window_title", DEFAULT_WINDOW_TITLE))
    img = capture_screen_rect(rect)
    sizes = [int(s) for s in (settings.get("board_sizes") or DEFAULT_BOARD_SIZES)]
    return recognize_board(img, sizes)


def capture_tsumego_grid(settings):
    """capture_board_view の後方互換ラッパ（認識グリッドだけ返す）"""
    return capture_board_view(settings).grid


DEFAULT_NOFRAME_REGION_PAD = 3


def capture_settings_for_frame_mode(settings, frameless):
    """枠なしキャプチャ（ホットキー指定）のときだけ設定を差し替えて返す。

    枠は「認識石の外接矩形 + margin」の**閉じた箱**で、`fit_margin` が枠外に守り側の
    代償地帯（約 (盤面積-コミ-5)/2 点）を要求するため**内側は盤の約半分が上限**になる。
    箱の外に正解手がある問題では、壁（攻め方の色）がその点を占めて打てなくなる
    （実測 2026-08-05 case AG・13路・ログ tsumego_20260805_015813: bbox 8行×7列で
    margin が 4→2 に縮み壁が row 4 に来た。正解手順は白が L8→M7→M6→L5 と下辺へ走る
    ので、続く白 **M4 が黒の壁石**だった）。

    枠を広げる方向では直せない（margin 3 は枠外 59 点 < 78.5 点で不成立）。自動判定も
    できない — 「対象が問題自身の石で囲われていない」は実測30キャプチャ中25件で発火し、
    これで枠を切り替えると正常な問題まで枠なしに落ちる。よって枠なしは**ユーザーの明示
    指定**（`hotkey_noframe`）とし、押されなければ設定オブジェクトをそのまま返す＝
    既存の3ホットキーの経路は一切変わらない。

    枠なし時のリージョンは `noframe_region_pad`（既定 3）で取る。既定の `region_pad`(1)
    のままだと人間（白）は盤全体に打てる一方で **AI（黒）の候補が壁の内側に留まる**ため、
    箱の外へ出た戦いを追えない。
    """
    if not frameless:
        return settings
    try:
        pad = max(0, int(settings.get("noframe_region_pad", DEFAULT_NOFRAME_REGION_PAD)))
    except (TypeError, ValueError):
        pad = DEFAULT_NOFRAME_REGION_PAD
    return {**settings, "use_frame": False, "region_pad": pad}


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
        view = recognize_board(img, sizes)
        print(
            f"board size: {len(view.grid)}  kind: {view.kind}"
            + (f"  cropped: {','.join(view.cropped_sides)}" if view.cropped_sides else "")
            + ("  (size guessed)" if view.size_fallback else "")
        )
    except CaptureError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)
    for row in view.grid:
        print(" ".join(row))
    print(grid_to_sgf(view.grid))


if __name__ == "__main__":
    main()
