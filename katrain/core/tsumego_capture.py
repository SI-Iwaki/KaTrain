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
    if 95 <= brightness <= 150 and spread >= 35 and (mr - mb) >= 35:
        # 盤色に半透明の黒が乗った茶色＝Web サイトのホバー石（マウス位置のプレビュー、実測
        # (130,115,79)）。着手済みの石ではないので空点扱い。黒石(<90)・白石・素の盤色より暗く
        # 彩度が落ちた帯だけを拾う
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
# 第2段（継ぎ目の影を y 方向にも許容した読み直し）の採用バー。第1段より厳しいのは、y 許容は誤サイズの
# スコアも押し上げるため（実測 2026-08-24・全サンプル×16 オフセット: 正解サイズの最小 0.75 / 誤サイズの
# 最大 0.51 / Web 盤〈従来方式が失敗して Web 認識へ落ちるべき画像〉の最大 0.46）。0.5 のままだと Web 盤を
# 従来方式が誤って受理しうる（余裕 0.04）。0.7 は両側に 0.2 以上の余裕
GRID_SCORE_MIN_SEAM = 0.7
GRID_SEAM_DY_TOLERANCE = 3


def _grid_line_score(rgb, board_rect, size, dy_tolerance=0):
    """候補サイズの想定縦線位置（交点間の中点）に実際に暗い線ピクセルがある割合を返す。

    石に隠れた点（7x7パッチが黒石の暗さ or 白石の明るさ）は分母から除外する。
    正しいサイズなら線上の点ばかりでスコア≈1、誤ったサイズなら線間の黄色に落ちてスコア≈0.1

    暗い線の探索は縦線向けに x 方向 ±3px だけ（縦線は y のずれに不感）。`dy_tolerance` > 0 なら
    y 方向 ±dy_tolerance px も見る＝石で埋まって縦線が隠れた盤では、信号が「縦に隣接する白石どうしの
    継ぎ目の影」（横向き 1〜2px）しか残らず、サンプル行が 1px ずれるだけで全部外れる（実測 2026-08-24
    9 路 70 子: 盤矩形が縮小画像由来で 4px 単位に量子化されるため y1 が 771/767 で揺れ、39/39 → 7/43）
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
            elif dy_tolerance and any(
                (sum(px[lx, ly + dy][:3]) / 3) < 150 for dy in range(-dy_tolerance, dy_tolerance + 1)
            ):
                hits += 1
    return hits / total if total else 0.0


def _rank_grid_scores(scores):
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_size, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    return best_size, best_score, second_score


def detect_size_and_classify(img, board_rect, sizes=DEFAULT_BOARD_SIZES):
    """格子線の位置から盤サイズを判定し、そのサイズで分類したグリッドを返す。

    「曖昧エラーが出なければ採用」方式は、石が少ない盤でサンプル点が偶然
    境界を踏まないと誤サイズが成立してしまうため、格子線検出で判定する
    """
    rgb = img.convert("RGB")
    scores = {size: _grid_line_score(rgb, board_rect, size) for size in sizes}
    best_size, best_score, second_score = _rank_grid_scores(scores)
    if best_score < GRID_SCORE_MIN or best_score - second_score < GRID_SCORE_MARGIN:
        # 第2段: 石で埋まって縦線が見えない盤（継ぎ目の影しか信号が無い）を y 許容で読み直す。
        # 第1段が決められた盤には一切触れない（従来経路はビット同一）
        seam_scores = {size: _grid_line_score(rgb, board_rect, size, GRID_SEAM_DY_TOLERANCE) for size in sizes}
        seam_size, seam_best, seam_second = _rank_grid_scores(seam_scores)
        if seam_best >= GRID_SCORE_MIN_SEAM and seam_best - seam_second >= GRID_SCORE_MARGIN:
            return seam_size, classify_intersections(img, board_rect, seam_size)
        detail = ", ".join(f"{s}:{v:.2f}" for s, v in scores.items())
        seam_detail = ", ".join(f"{s}:{v:.2f}" for s, v in seam_scores.items())
        raise CaptureError(f"盤サイズを判定できません（格子線スコア {detail} ／ 継ぎ目許容 {seam_detail}）")
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
WEB_GLYPH_MIN_H, WEB_GLYPH_MAX_H = 8, 40  # ラベルは盤ズーム非依存のUIフォント（実測 h=13-14px、モバイル風レイアウトは 19-30px）
WEB_GLYPH_MAX_W = 36
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


def _web_band_boxes(board_rect, vpos, hpos, vsp, hsp, img_size):
    """4辺のラベル帯領域 {side: box or None}。帯幅 0.45 セル未満なら None（そちら側は切れている）。

    - 内側境界は最外線から 0.45 セル＝1線の石（半径約 0.5 セル）が帯に届かないぎりぎりまで広げる
      （0.55 だと盤に寄ったラベルが境界に接触し、境界接触フィルタで落ちる。実測: 9路全体表示の
      左帯の数字が最外線から約 0.55 セルの位置にかかっていた）
    - 外側境界は盤領域（黄色 bbox）の縁より 4px 外まで広げる。ラベルは盤画像の縁ぴったりまで
      描かれることがあり（実測: 右帯の数字の右端が bbox 右端と同座標）、bbox を境界にすると
      境界接触フィルタでグリフごと落ちる。外側の暗い UI 領域は巨大成分としてサイズフィルタが落とす"""
    x0, y0, x1, y1 = board_rect
    iw, ih = img_size
    pad = 4
    out = {}
    for side, box, width, cell in (
        (
            "left",
            (max(0, x0 - pad), int(hpos[0] - hsp / 2), int(vpos[0] - vsp * 0.45), int(hpos[-1] + hsp / 2)),
            vpos[0] - x0,
            vsp,
        ),
        (
            "right",
            (int(vpos[-1] + vsp * 0.45), int(hpos[0] - hsp / 2), min(iw - 1, x1 + pad), int(hpos[-1] + hsp / 2)),
            x1 - vpos[-1],
            vsp,
        ),
        (
            "top",
            (int(vpos[0] - vsp / 2), max(0, y0 - pad), int(vpos[-1] + vsp / 2), int(hpos[0] - hsp * 0.45)),
            hpos[0] - y0,
            hsp,
        ),
        (
            "bottom",
            (int(vpos[0] - vsp / 2), int(hpos[-1] + hsp * 0.45), int(vpos[-1] + vsp / 2), min(ih - 1, y1 + pad)),
            y1 - hpos[-1],
            hsp,
        ),
    ):
        out[side] = box if width >= cell * 0.45 else None
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


def _web_trim_phantom_lines(pos, labeled):
    """ラベルの付かない端の線を落とす（最大片側2本）。

    縦に並んだ座標ラベルの列（数字が大きいレイアウトでは1本の細い暗線に見える）が
    幻の格子線として検出されることがある（実測: 19路部分表示の右帯の 19..9 が12本目の
    縦線に化けて右帯そのものを潰した／9路全体表示の左帯で列が0起点にずれた）。
    幻はラベル帯の中にいるので必ず端＝「本物の線はその帯のラベルが指している」ことを使い、
    ラベルが1本も付かない端の線だけを落とす。ラベルの読み損ね1件で本物を落とさないよう、
    ラベルが線の大半（2/3）をカバーしているときだけ発動する"""
    if not labeled:
        return pos, 0
    lo, hi = min(labeled), max(labeled)
    if len(labeled) < max(2, ((hi - lo + 1) * 2 + 2) // 3):
        return pos, 0  # ラベルがまばら＝読み取り自体が怪しいので線は触らない
    if lo > 2 or (len(pos) - 1 - hi) > 2:
        return pos, 0  # 端から3本以上落とすのは幻ではなく別の異常
    trimmed = pos[lo : hi + 1]
    return trimmed, lo


def recognize_web_board(img, board_rect, sizes=DEFAULT_BOARD_SIZES):
    """Web 盤面（格子線＋座標ラベル）を認識し BoardView を返す。失敗は CaptureError。

    - 格子線を検出し、ラベル帯の有無で「どの辺が盤の端か」を判定する（ラベルのある辺＝端が
      見えている。ラベルなしで線が縁まで届く辺＝そこで切れている）
    - 行番号（左右帯の数字）・列文字（上下帯の文字）を読んで可視域の絶対座標を確定する。
      数字が無い構図（下端だけ見えている等）は辺アンカー＝「文字帯のある下端の最下線は 1 の線」
      「数字帯のある左端の最左線は A の線」で補う
    - 盤サイズは「上端が見えていれば最上行の番号」「右端が見えていれば最右列の文字」から決まる。
      どちらも切れている場合は可視域が収まる最小の候補サイズに倒す（size_fallback=True）
    - 石は盤サイズの全面グリッドに絶対座標で配置して返す（可視域の外は空点）。これにより
      部分表示の詰碁も従来の枠張り・ソルバ・回答帳の経路にそのまま乗る
    """
    rgb = img.convert("RGB")
    vpos, hpos, vsp, hsp = _web_detect_lines(rgb, board_rect)
    reads = {}
    for _pass in range(3):
        bands = _web_band_boxes(board_rect, vpos, hpos, vsp, hsp, rgb.size)
        reads = {
            side: (_web_read_band(rgb, side, bands[side], vpos, hpos, vsp, hsp) if bands[side] else {})
            for side in ("left", "right", "top", "bottom")
        }
        # 幻線トリム: 列文字（上下帯）が指す縦線・行数字（左右帯）が指す横線だけを残す。
        # トリムすると帯領域が変わる（潰れていた帯が現れる）ので、変化があれば読み直す
        vpos2, _ = _web_trim_phantom_lines(vpos, set(reads["top"]) | set(reads["bottom"]))
        hpos2, _ = _web_trim_phantom_lines(hpos, set(reads["left"]) | set(reads["right"]))
        if len(vpos2) == len(vpos) and len(hpos2) == len(hpos):
            break
        vpos, hpos = vpos2, hpos2
    edge = {}
    for side in ("left", "right", "top", "bottom"):
        n_lines = len(vpos if side in ("top", "bottom") else hpos)
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
    if row_votes:
        row_c = _web_fit_axis(row_votes, "行")
    elif edge["bottom"]:
        # 行番号が1つも見えない構図（実測: 下辺の文字ラベルだけの下寄せクロップ）。
        # 文字帯は盤の端にしか描かれないので、下帯があるなら最下線は 1 の線
        row_c = len(hpos)
    else:
        raise CaptureError("行の座標ラベルが読めません（盤の端が画面内にあるか確認してください）")
    letters = set(COL_LETTERS)
    col_votes = []
    for side in ("top", "bottom"):
        for i, comps in reads[side].items():
            if len(comps) != 1:
                continue
            ch = _web_classify_glyph(rgb, comps[0], letters)
            if ch is not None:
                col_votes.append(COL_LETTERS.index(ch) + 1 - i)  # 列は左から右へ1ずつ増える
    if col_votes:
        col_c = _web_fit_axis(col_votes, "列")
    elif edge["left"]:
        col_c = 1  # 列文字が見えない構図でも、左帯（数字）があるなら最左線は A の線
    else:
        raise CaptureError("列の座標ラベルが読めません（盤の端が画面内にあるか確認してください）")

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
    # 辺アンカーとラベル読みの突き合わせ: 帯のある辺は盤の端なので、そこの最外線の座標は 1/size で
    # なければならない（ずれているなら幻線かラベルの誤読が残っている＝黙って誤った盤を出さない）
    if edge["bottom"] and row_of(len(hpos) - 1) != 1:
        raise CaptureError(f"下端が見えているのに最下線が {row_of(len(hpos) - 1)} の線と読めています")
    if edge["left"] and col_of(0) != 1:
        raise CaptureError(f"左端が見えているのに最左線が {COL_LETTERS[col_of(0) - 1]} の線と読めています")
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


# ============================================================
# 明るい木目盤認識（対局監視 board_watch の自動フォールバック経路）
#
# 別の BlueStacks 囲碁アプリ（明るい木目盤。実測の木地 median RGB≈(227,208,159)）は
# `_is_yellow` の b<150 を満たさず detect_board が全く動かない。さらに 19 路は盤領域の
# 四辺内側に座標ラベル帯があり第1線が縁から約 1.4 セル内側＝「縁から半セル」の規則配置
# 前提（classify_intersections）が破れる（13/9 路はラベル無しで約半セル＝サイズごとに
# レイアウトが違う）。そこで木地の色域で盤領域を取り、格子線そのものを検出して幾何を決める。
# 黄盤（b=62）は _is_bright_wood の b>100 を満たさない＝色域が相互排他なので、
# 「detect_board 失敗 → 木目盤」の自動ディスパッチで既存経路（詰碁・autoloop 含む）は不変。
# 実測データは docs/superpowers/specs/2026-08-18-board-watch-design.md の追記を参照
# ============================================================

from PIL import ImageChops

WOOD_BAND_FRACTION = 0.4  # 行/列ヒストグラムの帯採用閾値（detect_board の 0.5 相当。実測3枚は 0.3〜0.5 で安定）
WOOD_EDGE_PAD = 6  # 盤領域の縁の暗帯（枠線・影）の除外幅。無いと縁に幻線が1本出る（実測）
WOOD_LINE_DARK = 150  # 格子線の暗判定（等重み輝度。実測: 線 <120・木地 192-207）
WOOD_THIN_GAP = 6  # 細線判定: 両側 gap px が非暗なら線候補（石の胴体を除外。WEB_THIN_GAP と同思想）
WOOD_LINE_MIN_FRACTION = 0.5  # プロファイル最大値のこの割合超を線候補にする
WOOD_LINE_GROUP_GAP = 2  # 隣接この px 以内の候補列を1本の線にまとめる
WOOD_FIT_MIN_COVERAGE = 0.6  # 等差フィットで実検出ピークが線本数のこの割合未満なら不採用
WOOD_FIT_MAX_RESIDUAL = 3.0  # 等差フィットからの許容ずれ[px]（実測の線位置は ±0.5px で等間隔）
WOOD_GAP_TOLERANCE = 0.1  # 縦横のセル幅の許容差（比）
WOOD_STONE_PATCH_RATIO = 0.25  # 分類パッチ半径 = セル×この値（classify_intersections と同比率）
WOOD_MARKER_PATCH_RATIO = 0.08  # "?" 再判定の小半径。直前着手マーカー（石上の輪）の内側の石地色を拾う


def _is_bright_wood(r, g, b):
    # 実測の木地 median RGB≈(227,208,159)（明るい暖色・彩度は黄盤より低い）。黄盤 (247,193,62) は
    # b>100 を満たさず、r-b≈185 も上限 130 を超える＝ _is_yellow と両立しない（自動ディスパッチの要）
    return r > 180 and g > 150 and b > 100 and 30 < (r - b) < 130


def detect_wood_board(img):
    """画像内の明るい木目盤領域の bbox (x0, y0, x1, y1) を返す（両端含む。detect_board の木目盤版）"""
    w, h = img.size
    thumb = img.convert("RGB").resize((max(1, w // DETECT_SCALE), max(1, h // DETECT_SCALE)), Image.NEAREST)
    tw, th = thumb.size
    px = thumb.load()
    row_counts = [0] * th
    col_counts = [0] * tw
    for y in range(th):
        for x in range(tw):
            if _is_bright_wood(*px[x, y][:3]):
                row_counts[y] += 1
                col_counts[x] += 1
    max_row = max(row_counts, default=0)
    max_col = max(col_counts, default=0)
    if max_row < tw * 0.25 or max_col < th * 0.25:
        raise CaptureError("木目盤を検出できません（盤が画面に表示されているか確認してください）")
    rows = [y for y, c in enumerate(row_counts) if c >= max_row * WOOD_BAND_FRACTION]
    cols = [x for x, c in enumerate(col_counts) if c >= max_col * WOOD_BAND_FRACTION]
    x0, x1 = cols[0] * DETECT_SCALE, (cols[-1] + 1) * DETECT_SCALE - 1
    y0, y1 = rows[0] * DETECT_SCALE, (rows[-1] + 1) * DETECT_SCALE - 1
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if min(bw, bh) < 300 or not (0.9 < bw / bh < 1.1):
        raise CaptureError(f"木目盤の形が不正です（検出領域 {bw}x{bh}。盤が隠れていないか確認してください）")
    return (x0, y0, x1, y1)


def _wood_line_profiles(rgb, board_rect):
    """盤領域内の細い暗線の列プロファイル・行プロファイルを返す（各要素 0-255＝細線画素の割合×255）。

    「両側 WOOD_THIN_GAP px が非暗」の細線マスクを PIL の C 演算（point/offset/invert/multiply）で
    作り、BOX リサイズで軸ごとに畳む＝純 Python の全画素走査を避ける（実測 15-16ms/軸ペア）。
    ImageChops.offset は端で画素が回り込むが、縁 WOOD_EDGE_PAD を除外済みで第1線は
    さらに内側（実測 20px 以上）にあるため影響しない
    """
    x0, y0, x1, y1 = board_rect
    crop = rgb.crop((x0 + WOOD_EDGE_PAD, y0 + WOOD_EDGE_PAD, x1 + 1 - WOOD_EDGE_PAD, y1 + 1 - WOOD_EDGE_PAD))
    gray = _web_mean_gray(crop)
    dark = gray.point(lambda v: 255 if v < WOOD_LINE_DARK else 0)
    left = ImageChops.invert(ImageChops.offset(dark, WOOD_THIN_GAP, 0))
    right = ImageChops.invert(ImageChops.offset(dark, -WOOD_THIN_GAP, 0))
    thin_v = ImageChops.multiply(dark, ImageChops.multiply(left, right))
    up = ImageChops.invert(ImageChops.offset(dark, 0, WOOD_THIN_GAP))
    down = ImageChops.invert(ImageChops.offset(dark, 0, -WOOD_THIN_GAP))
    thin_h = ImageChops.multiply(dark, ImageChops.multiply(up, down))
    w, h = dark.size
    col_profile = list(thin_v.resize((w, 1), Image.BOX).tobytes())
    row_profile = list(thin_h.resize((1, h), Image.BOX).tobytes())
    return col_profile, row_profile


def _wood_line_peaks(profile):
    """プロファイルの線候補（最大値の WOOD_LINE_MIN_FRACTION 超）を隣接グループにまとめ、重心位置の列を返す"""
    peak = max(profile, default=0)
    if peak <= 0:
        return []
    floor = peak * WOOD_LINE_MIN_FRACTION
    groups = []
    for x, v in enumerate(profile):
        if v <= floor:
            continue
        if groups and x - groups[-1][-1][0] <= WOOD_LINE_GROUP_GAP:
            groups[-1].append((x, v))
        else:
            groups.append([(x, v)])
    return [sum(x * v for x, v in g) / sum(v for _x, v in g) for g in groups]


def _wood_fit_line_progression(peaks, sizes):
    """検出ピーク列を等差数列（等間隔の格子線）にフィットし (本数, 位置タプル) を返す。不成立は None。

    隣接間隔の最小クラスタの中央値を初期間隔にして各ピークを k 番目の線にスナップし、最小二乗で
    基点と間隔を refine する。石で隠れて欠けた中間の線は補完される（k が飛ぶだけ）。本数が sizes に
    無い・ピークが疎（カバレッジ不足）・等間隔から外れる、はすべて不採用＝過渡失敗扱いにする
    """
    if len(peaks) < 2:
        return None
    gaps = [b - a for a, b in zip(peaks, peaks[1:])]
    min_gap = min(gaps)
    if min_gap <= 0:
        return None
    cluster = sorted(g for g in gaps if g <= min_gap * 1.4)
    gap = cluster[len(cluster) // 2]
    ks = [round((p - peaks[0]) / gap) for p in peaks]
    if len(set(ks)) != len(ks):
        return None  # 2ピークが同じ線にスナップ＝間隔の仮説が壊れている
    n = len(peaks)
    mean_k = sum(ks) / n
    mean_p = sum(peaks) / n
    denom = sum((k - mean_k) ** 2 for k in ks)
    if denom <= 0:
        return None
    gap = sum((k - mean_k) * (p - mean_p) for k, p in zip(ks, peaks)) / denom
    base = mean_p - gap * mean_k
    if gap <= 0:
        return None
    if any(abs(p - (base + k * gap)) > WOOD_FIT_MAX_RESIDUAL for k, p in zip(ks, peaks)):
        return None
    count = max(ks) + 1
    if count not in sizes or len(peaks) / count < WOOD_FIT_MIN_COVERAGE:
        return None
    return count, tuple(base + k * gap for k in range(count))


def detect_wood_grid(img, board_rect, sizes=DEFAULT_BOARD_SIZES):
    """木目盤の格子線を検出し (盤サイズ, 縦線の x 座標タプル, 横線の y 座標タプル) を返す。

    座標は img（＝窓画像）座標。規則配置の割り算を使わないので、座標ラベル帯の有無や余白幅が
    盤サイズごとに違ってもそのまま吸収される（19 路: 帯あり・第1線は縁から 1.4 セル ／
    13・9 路: 帯なし・約半セル、を同じコードで読む）。失敗は CaptureError
    """
    rgb = img.convert("RGB")
    col_profile, row_profile = _wood_line_profiles(rgb, board_rect)
    v_peaks = _wood_line_peaks(col_profile)
    h_peaks = _wood_line_peaks(row_profile)
    v_fit = _wood_fit_line_progression(v_peaks, sizes)
    h_fit = _wood_fit_line_progression(h_peaks, sizes)
    if v_fit is None or h_fit is None or v_fit[0] != h_fit[0]:
        raise CaptureError(f"木目盤の格子線を検出できません（線候補 縦 {len(v_peaks)} 本 / 横 {len(h_peaks)} 本）")
    size, xs = v_fit
    _size, ys = h_fit
    gap_x = (xs[-1] - xs[0]) / (size - 1)
    gap_y = (ys[-1] - ys[0]) / (size - 1)
    if abs(gap_x - gap_y) > max(gap_x, gap_y) * WOOD_GAP_TOLERANCE:
        raise CaptureError(f"木目盤の格子が正方形ではありません（セル幅 縦 {gap_x:.1f} / 横 {gap_y:.1f}）")
    x0 = board_rect[0] + WOOD_EDGE_PAD
    y0 = board_rect[1] + WOOD_EDGE_PAD
    return size, tuple(x0 + x for x in xs), tuple(y0 + y for y in ys)


def _wood_median_channels(patch):
    """パッチの per-channel median (r, g, b)。histogram() は C 実装なので純 Python の画素走査より速い"""
    hist = patch.histogram()
    total = patch.size[0] * patch.size[1]
    half = (total + 1) // 2
    medians = []
    for channel in range(3):
        acc = 0
        for v in range(256):
            acc += hist[channel * 256 + v]
            if acc >= half:
                medians.append(v)
                break
    return medians


def _classify_wood_patch(rgb, cx, cy, rad):
    """木目盤の交点1点を per-channel median で分類し ("B"/"W"/"."/"?", median 色) を返す。

    mean（_classify_patch と同方式）だと星点の暗ドットが spread を潰し、空点の星点が
    「低彩度・高輝度」＝白石に化ける（実測5点）。median は格子線・星点・直前着手マーカーの
    少数派画素を自然に無視するので、木目盤では median を使う
    """
    patch = rgb.crop((int(cx) - rad, int(cy) - rad, int(cx) + rad + 1, int(cy) + rad + 1))
    mr, mg, mb = _wood_median_channels(patch)
    brightness = (mr + mg + mb) / 3
    spread = max(mr, mg, mb) - min(mr, mg, mb)
    if brightness < 90:
        return "B", (mr, mg, mb)
    if spread < 60 and brightness > 160:
        return "W", (mr, mg, mb)
    if spread >= 55 and (mr - mb) >= 40 and brightness >= 150:
        return ".", (mr, mg, mb)  # 明るい暖色＝木地（実測 brightness 192-207・spread 67-69・r-b 67-69）
    return "?", (mr, mg, mb)


def classify_wood_intersections(img, xs, ys):
    """検出済み格子線位置 (xs, ys) の全交点を分類したグリッドを返す（classify_intersections の木目盤版）。

    "?" は小半径（WOOD_MARKER_PATCH_RATIO）で1回だけ再判定する＝直前着手マーカー（石の上の輪）が
    パッチの median を壊すことがある（実測: 白輪付き黒石が brightness 111 で "?"）が、輪の内側は
    石の地色なので中心の小パッチなら確定する。それでも "?" が残れば CaptureError（過渡失敗扱い）
    """
    rgb = img.convert("RGB")
    cell_w = (xs[-1] - xs[0]) / (len(xs) - 1)
    cell_h = (ys[-1] - ys[0]) / (len(ys) - 1)
    cell = min(cell_w, cell_h)
    rad = max(2, int(cell * WOOD_STONE_PATCH_RATIO))
    marker_rad = max(2, int(cell * WOOD_MARKER_PATCH_RATIO))
    grid = []
    ambiguous = []
    for i, cy in enumerate(ys):
        row = []
        for j, cx in enumerate(xs):
            label, means = _classify_wood_patch(rgb, cx, cy, rad)
            if label == "?":
                label, means = _classify_wood_patch(rgb, cx, cy, marker_rad)
            if label == "?":
                ambiguous.append((i, j, tuple(round(m) for m in means)))
            row.append(label)
        grid.append(row)
    if ambiguous:
        raise CaptureError(f"判定できない交点があります（先頭5件: {ambiguous[:5]}）")
    return grid


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
