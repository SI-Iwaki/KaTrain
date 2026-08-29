"""詰碁の自動ループ（spec: docs/superpowers/specs/2026-08-23-tsumego-autoloop-design.md）。

BlueStacks の「囲碁詰めチャレ」を ADB で操作し、出題→回答→正誤→（誤答なら）ヒント歩きで
回答帳へ記録→次の問題、を回す。Kivy / KataGo / __main__ に依存しない（テストから直接 import）。

座標系: 認識グリッド grid[i][j] は i=上から（top origin）。KaTrain の Move.coords=(x,y) は
y=下から。変換は board_watch.move_to_grid / grid_to_move を使う（自前で書かない）。
"""

import hashlib
import io
import json
import os
import queue
import re
import subprocess
import threading
import time
from typing import NamedTuple

from PIL import Image, ImageStat

from katrain.core.board_watch import EMPTY, BLACK, WHITE, apply_move_to_grid, move_to_grid
from katrain.core.tsumego_capture import CaptureError, _is_yellow, detect_board, detect_size_and_classify

# --- 定数（デバイス解像度 900x1600 基準。比率は解像度が変わっても追従する） ---
DEVICE_W, DEVICE_H = 900, 1600
DEFAULT_ADB_PATH = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
BLUESTACKS_CONF = r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"
APP_PACKAGE = "fm.wars.goquest"  # 詰碁アプリ（囲碁詰めチャレ）のパッケージ名
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "img", "autoloop")
DEFAULT_UI_POINTS = {
    "bar_next": (0.472, 0.784),
    "bar_hint": (0.833, 0.784),
    "bar_undo": (0.933, 0.784),
    "popup_next": (0.256, 0.781),
    "popup_view": (0.489, 0.781),
}
# 大盤の上端の帯（実測 3.0.70: 問題画面 黄 0.957 / ポップアップ 0.074）。**判定には使わない**
# ＝アプリ 3.0.72 で解答中の画面からヘッダと下のバーが消えて盤が 288 → 304〜308 に下がり、この
# 固定帯が盤の外（青い背景）に落ちて黄色率 0.000 ＝「盤は覆われている」＝ポップアップ、と
# **問題画面を毎回誤判定**した（実測 2026-08-29・自動ループが1問もキャプチャできず停止）。
# 盤が覆われているかは盤の位置そのものを検出する big_board_visible で見る（比率に依らない）
POPUP_STRIP = (0.02, 0.181, 0.98, 0.19)
POPUP_STRIP_YELLOW_MAX = 0.5
POPUP_INNER_BOARD_BOX = (0.25, 0.42, 0.75, 0.62)  # 結果ポップアップが常に出す内側の小盤
# 内側の小盤の「盤あり/なし」を分けるしきい値は **1本**（spec 追記6）。旧実装は popup>=0.5 /
# overlay<0.2 の2定数で、0.2〜0.5 がどちらにも分類されない死角だった＝石で小盤がほぼ覆われる
# 出題（実測 2026-08-24 太極詰碁 9路77子: 0.371）の昇段カードがそこへ落ち、STALLED で凍った。
# 実測: 盤なし（認定証2種）0.0 / 盤あり最小 0.371（覆われた盤の床は石の円の隙間で決まり、
# 石のみの横帯でも 0.256〜0.319）/ 通常の結果ポップアップ 0.83〜0.87。0.15 は両側に 0.1 超の余白
INNER_BOARD_YELLOW_SPLIT = 0.15
VERDICT_BAND = (0.10, 0.289, 0.90, 0.325)  # 判定文 1 行目（実測 文字 y 481..511）
VERDICT_DARK_SUM = 300  # 文字画素: R+G+B < 300（紙色は 600 超）
VERDICT_TAIL_W = 140  # 文字列の右端に寄せた切り出し幅（中央寄せ文の長さ差を吸収）
VERDICT_MAX_MAD = 30.0  # テンプレートとの平均絶対差の上限
VERDICT_MIN_GAP = 10.0  # 1位と2位の差がこれ未満なら unknown
HINT_ICON = (0.833, 0.775, 18)  # (cx比, cy比, 半径px)。実測 平均輝度: 有効 151 / グレーの戻す 48
HINT_ICON_ENABLED_MIN = 126.0  # 実測 2026-08-23: 有効 160.4 / 無効 92.7（中点）
# 下のボタンバー（次の問題/結果/シェアする/ヒント/戻す）。電球は半径 18px の点サンプルなので、
# 版差の 20px でバーを外して「無効」と誤読する（実測 3.0.72 の復習画面 123.4 ＜ 閾値 126）。
# バーの上端を盤の下端から探して、そこに合わせて測る（見つからなければ従来の比率へフォールバック）
BAR_SEARCH_DY = 90  # 盤の下端からバー上端を探す範囲[px]（900x1600 基準・フレーム高でスケール）
BAR_DARK_MAX = 58.0  # バーの行平均輝度の上限（実測 バー 22〜53 / 盤の下の背景 67〜71）
BAR_ICON_DY = 29  # バー上端から電球の中心まで（実測 3.0.70 1204→1234 / 3.0.72 1225→1255）
HEADER_BAND = (0.10, 0.15, 0.90, 0.18)
RED_RING_MIN_PIXELS = 80
# 認定証（spec 追記2・追記5）。実機は**問題画面の上に載るダイアログ**で、アプリのヘッダ
# （左上の ← 戻る ≈(0.045,0.05)・「囲碁詰めチャレ」・難易度/出典 y≈0.16）はダイアログの上に残る。
# ダイアログは y 0.175〜0.83・紙色 (251,249,225) 前後、閉じる × は**ダイアログの左上** ≈(0.09,0.20)。
CLOSE_GLYPH_BOX = (0.04, 0.17, 0.125, 0.225)
CLOSE_GLYPH_DARK_SUM = 450  # 暗画素: R+G+B < 450
CLOSE_GLYPH_WARM_MAX = 40  # 金の装飾（鳥）を落とす: R-B がこれを超える暖色は数えない（実測 × -6 / 金 +78）
CLOSE_GLYPH_MIN_PIXELS = 30
CLOSE_GLYPH_MIN_PX = 12  # bbox の辺の下限（900 幅基準・フレーム幅でスケール）
CLOSE_GLYPH_MAX_PX = 70  # 同・上限（実測 実機の × は 36x35 px）
OVERLAY_TITLE_BAND = (0.08, 0.145, 0.45, 0.175)  # 結果ポップアップでは濃紺の「囲碁詰めチャレ」帯
RESULT_TITLE_DARK_MAX = 140.0  # 結果ポップアップの署名。実測 81.1（正誤とも）/ 100.5（出現途中）
OVERLAY_PAPER_BAND = (0.2, 0.25, 0.8, 0.28)  # 認定証ダイアログの紙の帯（実測 247.2 / 結果ポップアップ 215.4）
OVERLAY_PAPER_MIN = 200.0


def _is_red(r, g, b):
    return r > 180 and g < 110 and b < 110 and (r - g) > 90


def ui_point(name, frame_size, ui_points=None):
    """比率座標 → フレーム座標（int）"""
    rx, ry = (ui_points or DEFAULT_UI_POINTS)[name]
    w, h = frame_size
    return int(round(rx * w)), int(round(ry * h))


class AutoLoopSettings(NamedTuple):
    enabled: bool
    hotkey: str
    adb_path: str
    adb_serial: str
    poll_ms: int
    settle_ms: int
    answer_timeout_s: float
    capture_timeout_s: float
    max_problems: int
    max_consecutive_errors: int
    ui_points: dict
    ledger_path: str
    shots_dir: str


def autoloop_settings_from_config(cfg):
    cfg = cfg or {}
    points = dict(DEFAULT_UI_POINTS)
    for k, v in (cfg.get("ui_points") or {}).items():
        points[k] = (float(v[0]), float(v[1]))
    home = os.path.expanduser("~")
    return AutoLoopSettings(
        enabled=bool(cfg.get("enabled", True)),
        hotkey=str(cfg.get("hotkey", "ctrl+alt+a")),
        adb_path=str(cfg.get("adb_path") or DEFAULT_ADB_PATH),
        adb_serial=str(cfg.get("adb_serial") or ""),
        poll_ms=int(cfg.get("poll_ms", 500)),
        settle_ms=int(cfg.get("settle_ms", 700)),
        answer_timeout_s=float(cfg.get("answer_timeout_s", 40)),
        capture_timeout_s=float(cfg.get("capture_timeout_s", 25)),
        max_problems=int(cfg.get("max_problems", 0)),
        max_consecutive_errors=int(cfg.get("max_consecutive_errors", 3)),
        ui_points=points,
        ledger_path=str(cfg.get("ledger_path") or os.path.join(home, ".katrain", "tsumego_ledger.jsonl")),
        shots_dir=str(cfg.get("shots_dir") or os.path.join(home, ".katrain", "logs", "autoloop")),
    )


# --- 画面判定（純関数・PIL のみ） ---
def _box(frame, ratio_box):
    w, h = frame.size
    x0, y0, x1, y1 = ratio_box
    return int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)


def yellow_ratio(frame, ratio_box):
    x0, y0, x1, y1 = _box(frame, ratio_box)
    px = frame.load()
    n = t = 0
    for y in range(y0, y1):
        for x in range(x0, x1, 2):
            t += 1
            if _is_yellow(*px[x, y][:3]):
                n += 1
    return n / t if t else 0.0


def _band_mean(frame, ratio_box):
    return ImageStat.Stat(frame.crop(_box(frame, ratio_box)).convert("L")).mean[0]


def result_title_band_dark(frame):
    """結果ポップアップの濃紺タイトル帯（「囲碁詰めチャレ」）が出ているか。

    実測（tests/data/autoloop）: popup_wrong / popup_correct 81.1・出現途中 100.5。
    問題画面（53.7）・遷移（43.5）・**認定証（44.5）** もアプリの青いヘッダなので暗い側に出る
    ＝この帯だけでは問題画面とも認定証とも分離できない（認定証はダイアログで、この帯はその
    上に残るヘッダ＝spec 追記5）。分離は popup_present の黄色帯と内側の小盤の条件が担う。
    """
    return _band_mean(frame, OVERLAY_TITLE_BAND) < RESULT_TITLE_DARK_MAX


def big_board_visible(frame):
    """アプリの大盤が丸ごと見えているか（＝ダイアログに覆われていないか）。

    旧実装は固定比率の帯 POPUP_STRIP が黄色かで見ていたが、アプリ 3.0.72 で盤が 20px 下がって
    帯が盤の外に落ち、問題画面を全部ポップアップと誤判定した（2026-08-29）。盤の位置そのものを
    検出すれば版差に依存しない。既存フレーム 11 枚では両者の判定は完全に一致する（問題/ヒント/
    遷移＝見える・帯 0.79〜1.00 / ポップアップ・認定証＝見えない・帯 0.01〜0.07 かつ検出も失敗）。
    ダイアログは盤の上下を隠すので detect_board は「盤面の形が不正です」で落ちる（実測 888x552）。
    """
    try:
        board_rect_of(frame)
    except CaptureError:
        return False
    return True


def popup_present(frame):
    """結果ポップアップが盤を覆っているか。

    「大盤が見えない」だけだと、アプリのホーム・遷移中・認定証まで一律に
    ポップアップ扱いになり、そこへ「次の問題」を撃ってしまう（spec 追記4 の誤タップ事故）。
    結果ポップアップの署名（濃紺のタイトル帯）を AND して、知らない画面と区別する。
    さらに結果ポップアップは中央に必ず内側の小盤（黄色）を出すので、それも AND する
    （spec 追記4）。ホーム・メニュー画面は中央に盤が無い＝この条件だけで「ポップアップではない」
    と確定できる（他の2条件が偶然揃っても、盤が無ければポップアップにしない）。
    """
    return (
        not big_board_visible(frame)
        and result_title_band_dark(frame)
        and yellow_ratio(frame, POPUP_INNER_BOARD_BOX) >= INNER_BOARD_YELLOW_SPLIT
    )


def _glyph_pixels(frame, ratio_box):
    """ratio_box の中の「暗くて暖色でない」画素（× の色。金の装飾は R-B が大きいので落ちる）"""
    x0, y0, x1, y1 = _box(frame, ratio_box)
    px = frame.load()
    pts = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y][:3]
            if r + g + b < CLOSE_GLYPH_DARK_SUM and r - b <= CLOSE_GLYPH_WARM_MAX:
                pts.append((x, y))
    return pts


def _pts_bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _blobs(pts):
    """8 近傍で連結した塊に分ける（探索窓は高々 100x100 px 程度なので素朴な BFS でよい）"""
    remaining = set(pts)
    out = []
    while remaining:
        seed = remaining.pop()
        blob, stack = [seed], [seed]
        while stack:
            x, y = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    p = (x + dx, y + dy)
                    if p in remaining:
                        remaining.discard(p)
                        blob.append(p)
                        stack.append(p)
        out.append(blob)
    return out


def find_close_glyph(frame):
    """認定証ダイアログを閉じる × の中心 (x, y)。見つからなければ None。

    探索窓は**ダイアログの左上**（CLOSE_GLYPH_BOX ≈ x 0.04〜0.125 / y 0.17〜0.225）。実機の
    認定証は問題画面の上に載るダイアログなので、画面の左上を探すとアプリのヘッダ（← 戻る）に
    当たる＝押すとホームへ飛ぶ（spec 追記5）。窓の中でも 3 つの夾雑物を落とす必要がある:
    (1) 金の装飾（鳥）は暖色なので数えない（× は R-B=-6 / 金は +78）、(2) 窓の上端に掛かる
    ヘッダの帯・ダイアログ左外の暗い背景は、暗画素をまとめた bbox を膨らませる。そこで bbox が
    サイズ判定（12〜70px・900 幅基準でスケール）を外れたら 8 近傍の塊に分け、判定に収まる塊の
    うち最も左上のもの（× はこの窓で唯一のコンパクトな暗い物体）を採る。UI の帯は窓の幅いっぱいに
    伸びるので上限で落ち、ダイアログ外の暗い縁は幅が足りず下限で落ちる。
    """
    pts = _glyph_pixels(frame, CLOSE_GLYPH_BOX)
    if len(pts) < CLOSE_GLYPH_MIN_PIXELS:
        return None
    scale = frame.size[0] / float(DEVICE_W)
    lo, hi = CLOSE_GLYPH_MIN_PX * scale, CLOSE_GLYPH_MAX_PX * scale

    def fits(bb):
        return lo <= bb[2] - bb[0] <= hi and lo <= bb[3] - bb[1] <= hi

    bbox = _pts_bbox(pts)
    if not fits(bbox):
        boxes = (_pts_bbox(b) for b in _blobs(pts) if len(b) >= CLOSE_GLYPH_MIN_PIXELS)
        found = [bb for bb in boxes if fits(bb)]
        if not found:
            return None
        bbox = min(found, key=lambda bb: (bb[1], bb[0]))
    return (bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2


def overlay_present(frame):
    """認定証ダイアログが出ているか（spec 追記5）。

    実機のジオメトリは**全画面ではなくダイアログ**で、アプリのヘッダ（← 戻る・「囲碁詰めチャレ」・
    難易度/出典）はその上に残る＝OVERLAY_TITLE_BAND は認定証でも濃紺（実測 44.5）のままなので、
    旧実装の「タイトル帯が紙色」という条件は実機で常に偽だった。署名は 4 つ:
    大盤が見えない（big_board_visible）・中央に結果ポップアップの小盤が無い・
    ダイアログの紙の帯が明るい（OVERLAY_PAPER_BAND）・ダイアログ左上に × がある。
    """
    return (
        not big_board_visible(frame)
        and yellow_ratio(frame, POPUP_INNER_BOARD_BOX) < INNER_BOARD_YELLOW_SPLIT
        and _band_mean(frame, OVERLAY_PAPER_BAND) >= OVERLAY_PAPER_MIN
        and find_close_glyph(frame) is not None
    )


def _dark_bbox(frame, ratio_box):
    x0, y0, x1, y1 = _box(frame, ratio_box)
    px = frame.load()
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y][:3]
            if r + g + b < VERDICT_DARK_SUM:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def verdict_tail(frame):
    """判定文の右端に寄せた切り出し（グレースケール）。文字が無ければ None"""
    bbox = _dark_bbox(frame, VERDICT_BAND)
    if bbox is None:
        return None
    _x0, y0, x1, y1 = bbox
    return frame.crop((x1 + 1 - VERDICT_TAIL_W, y0 - 4, x1 + 1, y1 + 5)).convert("L")


def load_templates(dir_path=TEMPLATE_DIR):
    out = {}
    for name in ("wrong", "correct"):
        path = os.path.join(dir_path, f"popup_{name}_tail.png")
        if os.path.exists(path):
            out[name] = Image.open(path).convert("L")
    return out


def _mad(a, b):
    if a.size != b.size:
        b = b.resize(a.size)
    pa, pb = a.load(), b.load()
    w, h = a.size
    return sum(abs(pa[x, y] - pb[x, y]) for y in range(h) for x in range(w)) / float(w * h)


def popup_state(frame, templates):
    """'none'（ポップアップ無し）/ 'correct' / 'wrong' / 'unknown'"""
    if not popup_present(frame):
        return "none"
    tail = verdict_tail(frame)
    if tail is None or not templates:
        return "unknown"
    scored = sorted((_mad(tail, tpl), name) for name, tpl in templates.items())
    best_mad, best = scored[0]
    if best_mad > VERDICT_MAX_MAD:
        return "unknown"
    if len(scored) > 1 and scored[1][0] - best_mad < VERDICT_MIN_GAP:
        return "unknown"
    return best


class BoardRead(NamedTuple):
    rect: tuple
    size: int
    grid: list


def board_rect_of(frame):
    return detect_board(frame)


def read_board(frame, sizes):
    rect = detect_board(frame)
    size, grid = detect_size_and_classify(frame, rect, list(sizes))
    return BoardRead(rect, size, grid)


def board_to_device(i, j, rect, size):
    x0, y0, x1, y1 = rect
    cell_w = (x1 - x0 + 1) / size
    cell_h = (y1 - y0 + 1) / size
    return int(round(x0 + cell_w * (j + 0.5))), int(round(y0 + cell_h * (i + 0.5)))


def device_to_board(x, y, rect, size):
    x0, y0, x1, y1 = rect
    cell_w = (x1 - x0 + 1) / size
    cell_h = (y1 - y0 + 1) / size
    j = int((x - x0) / cell_w)
    i = int((y - y0) / cell_h)
    return max(0, min(size - 1, i)), max(0, min(size - 1, j))


def find_hint_circle(frame, rect, size):
    """盤の中の赤いリング（ヒント）の交点 (i, j)。無ければ None。複数（離れた赤）なら None。

    赤画素は最も近い交点（device_to_board）ごとにクラスタへ振り分ける。実機では最終手に
    小さい赤四角マーカー（約16px）も描かれるため、単一 bbox で集計するとリングと合算されて
    サイズ判定を外れる（spec 2026-08-23 追記）。クラスタごとに bbox のサイズを見て、リング
    サイズ（cell*0.4〜1.3・かつ RED_RING_MIN_PIXELS 以上）に収まるものだけを候補とする。
    マーカーのような小さいクラスタは無視され、候補が 0 個・2 個以上なら None。
    """
    x0, y0, x1, y1 = rect
    px = frame.load()
    clusters = {}
    for y in range(y0, y1 + 1, 2):
        for x in range(x0, x1 + 1, 2):
            if _is_red(*px[x, y][:3]):
                key = device_to_board(x, y, rect, size)
                clusters.setdefault(key, []).append((x, y))
    cell = (x1 - x0 + 1) / size
    candidates = []
    for key, pts in clusters.items():
        if len(pts) < RED_RING_MIN_PIXELS:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bw, bh = max(xs) - min(xs), max(ys) - min(ys)
        if cell * 0.4 <= bw <= cell * 1.3 and cell * 0.4 <= bh <= cell * 1.3:
            candidates.append(key)
    if len(candidates) != 1:
        return None
    return candidates[0]


def bar_top_of(frame, rect=None):
    """盤の下のボタンバーの上端 y。バーが無い／盤を検出できないなら None。

    アプリ 3.0.72 は**解答中はバーを出さない**（ヘッダも消える）ので None が正しい＝ヒントは
    押せない。復習画面（結果ポップアップの「問題を見る」）ではバーが戻る。実測の上端は
    3.0.70 が 1204・3.0.72 が 1225 で、電球の中心はどちらもその 29〜30px 下（バー高は 95 で同一）。
    """
    try:
        rect = rect or board_rect_of(frame)
    except CaptureError:
        return None
    w, h = frame.size
    top = rect[3] + 1
    bottom = min(h, top + int(round(BAR_SEARCH_DY * h / DEVICE_H)))
    if bottom - top < 4:
        return None
    rows = frame.crop((0, top, w, bottom)).convert("L").resize((1, bottom - top), Image.BOX).load()
    for dy in range(bottom - top):
        if rows[0, dy] < BAR_DARK_MAX:
            return top + dy
    return None


def hint_enabled(frame):
    w, h = frame.size
    bar_top = bar_top_of(frame)
    # バーが見つからないフレーム（ポップアップ・認定証・遷移）は従来どおり比率で測る＝判定を
    # 変えない。ここで False（＝ヒントが灰色）に倒すと、収穫中に割り込んだポップアップで
    # ヒント歩きが途中終了し、切れた手順が回答帳に入る
    cy = bar_top + int(round(BAR_ICON_DY * h / DEVICE_H)) if bar_top is not None else int(HINT_ICON[1] * h)
    cx, rad = int(HINT_ICON[0] * w), HINT_ICON[2]
    mean = ImageStat.Stat(frame.crop((cx - rad, cy - rad, cx + rad, cy + rad)).convert("L")).mean[0]
    return mean >= HINT_ICON_ENABLED_MIN


def header_hash(frame):
    """ヘッダ（出典・番号）の帯を 32x4 グレースケールに縮めた sha1 の先頭 16 桁（同じ問題なら同じ）"""
    band = frame.crop(_box(frame, HEADER_BAND)).convert("L").resize((32, 4), Image.BILINEAR)
    return hashlib.sha1(band.tobytes()).hexdigest()[:16]


def empty_points(grid):
    return [(i, j) for i, row in enumerate(grid) for j, v in enumerate(row) if v == EMPTY]


def farthest_empty_point(grid):
    """どの石からも最も遠い空点（チェビシェフ距離の最大・同値なら先頭）。空点が無ければ None。

    CAPTURE_FAILED の「わざと1手」に使う。左上から順の `empty_points[0]` は問題の石の
    すぐ隣になりうる＝正解手や有効な変化を踏みかねないので、石から最も離れた点を選ぶ
    （不正解になれば、そのまま収穫＝ヒント歩きで正解手順を取り込める）。
    """
    empties = empty_points(grid)
    if not empties:
        return None
    stones = [(i, j) for i, row in enumerate(grid) for j, v in enumerate(row) if v != EMPTY]
    if not stones:
        return empties[0]
    best, best_d = None, -1
    for i, j in empties:
        d = min(max(abs(i - si), abs(j - sj)) for si, sj in stones)
        if d > best_d:
            best, best_d = (i, j), d
    return best


class Vision:
    """画面判定の束（テストでは同じメソッド名のフェイクに差し替える）"""

    def __init__(self, sizes, templates=None, ui_points=None):
        self.sizes = tuple(sizes)
        self.templates = templates if templates is not None else load_templates()
        self.ui_points = ui_points or DEFAULT_UI_POINTS

    def popup_present(self, frame):
        return popup_present(frame)

    def popup_state(self, frame):
        return popup_state(frame, self.templates)

    def overlay_present(self, frame):
        return overlay_present(frame)

    def find_close_glyph(self, frame):
        return find_close_glyph(frame)

    def read_board(self, frame, size=None):
        return read_board(frame, (size,) if size else self.sizes)

    def board_rect(self, frame):
        return board_rect_of(frame)

    def find_hint_circle(self, frame, rect, size):
        return find_hint_circle(frame, rect, size)

    def hint_enabled(self, frame):
        return hint_enabled(frame)

    def header_hash(self, frame):
        return header_hash(frame)

    def ui_point(self, name, frame):
        return ui_point(name, frame.size, self.ui_points)


# --- ADB（BlueStacks 同梱 HD-Adb.exe） ---
class AdbError(Exception):
    pass


def _run_adb(args, binary=False, timeout_s=10):
    """subprocess.run の薄い包み。binary=True は stdout をそのまま返す（screencap の PNG）"""
    try:
        proc = subprocess.run(
            args, capture_output=True, timeout=timeout_s, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AdbError(f"adb 実行失敗: {e}") from e
    if proc.returncode != 0:
        # 失敗を空文字（＝「接続されていない」と同じ見た目）で返さない。呼び出し側は
        # AdbError を捕まえて次の port へ進む／再接続する（devices の空出力と区別できる）
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise AdbError(f"adb 失敗（code {proc.returncode}）: {detail[:120]}")
    if binary:
        return proc.stdout
    return proc.stdout.decode("utf-8", errors="replace")


class AdbClient:
    def __init__(self, adb_path, serial, runner=None, timeout_s=10):
        self.adb_path = adb_path
        self.serial = serial
        self.runner = runner or _run_adb
        self.timeout_s = timeout_s

    def _adb(self, *args, binary=False):
        return self.runner([self.adb_path, *args], binary=binary, timeout_s=self.timeout_s)

    def connect(self):
        try:
            out = self._adb("connect", self.serial)
        except AdbError:  # 応答しない port は失敗であって例外ではない（探索が次へ進める）
            return False
        return "connected" in out or "already connected" in out

    def is_device(self):
        out = self._adb("devices")
        return any(line.split("\t")[:2] == [self.serial, "device"] for line in out.splitlines())

    def screencap(self):
        data = self._adb("-s", self.serial, "exec-out", "screencap", "-p", binary=True)
        if not data:
            raise AdbError("screencap が空でした（接続を確認）")
        try:
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            raise AdbError(f"screencap を画像にできません: {e}") from e

    def tap(self, x, y):
        self._adb("-s", self.serial, "shell", "input", "tap", str(int(round(x))), str(int(round(y))))

    def foreground_package(self):
        """前面に出ているアプリのパッケージ名。取れなければ None（AdbError も握って握り潰す）。

        `mCurrentFocus=`/`mFocusedApp=` を含む最初の行だけを見る（複数行あっても遷移中の
        古い行に引きずられないよう、最初に見つかった行で確定させる）。
        """
        try:
            out = self._adb("-s", self.serial, "shell", "dumpsys", "window")
        except AdbError:
            return None
        for line in out.splitlines():
            if "mCurrentFocus=" in line or "mFocusedApp=" in line:
                m = re.search(r"u0 ([A-Za-z0-9_.]+)/", line)
                return m.group(1) if m else None
        return None


def discover_serial(adb_path, conf_path=BLUESTACKS_CONF, runner=None, timeout_s=10, prefer_package=APP_PACKAGE):
    """bluestacks.conf の adb_port を順に connect し、応答した中から詰碁アプリが前面のものを返す

    devices に 'device' で現れた serial を**全部**集めてから、それぞれの foreground_package() を
    見て prefer_package と一致する最初の 1 本を返す（複数の BlueStacks インスタンスがある環境で
    「最初に応答した port」が別インスタンスだと誤接続になるため）。一致が無ければ従来どおり
    最初に応答した serial にフォールバックする。prefer_package=None で従来動作（最初の1本）。

    timeout_s は 1 本あたりの adb 実行の上限。GUI のホットキーから呼ぶときは短く（3 秒）指定する
    ＝応答しない port が複数あると既定の 10 秒×本数ぶん画面が固まって見える
    """
    ports = []
    try:
        with open(conf_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'bst\.instance\.[^.]+\.adb_port="(\d+)"', line.strip())
                if m and m.group(1) not in ports:
                    ports.append(m.group(1))
    except OSError:
        return None
    responding = []
    for port in ports:
        serial = f"127.0.0.1:{port}"
        client = AdbClient(adb_path, serial, runner=runner, timeout_s=timeout_s)
        try:
            client.connect()
            if client.is_device():
                responding.append(serial)
        except AdbError:
            continue
    if not responding:
        return None
    if prefer_package:
        for serial in responding:
            client = AdbClient(adb_path, serial, runner=runner, timeout_s=timeout_s)
            if client.foreground_package() == prefer_package:
                return serial
    return responding[0]


# --- 台帳 ---
class Ledger:
    def __init__(self, path):
        self.path = path

    def append(self, record):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- 収穫（ヒント歩き） ---
HINT_WAIT_S = 1.5  # ヒント押下後に赤丸を待つ上限（spec §4.4）
MOVE_WAIT_S = 6.0  # 黒タップ後に盤が安定するまでの上限
REWIND_MAX_TAPS = 20
HARVEST_MAX_MOVES = 40
HARVEST_MAX_S = 180.0  # 収穫1問あたりの総時間上限（実測 40 手 ≒ 140 秒。close/rewind の粘りへの全体締切）
CLOSE_MAX_TAPS = 5  # ポップアップが閉じ続ける場合の打ち切り


def white_reply(expected, observed):
    """expected（黒を打った直後の盤）と observed の差が「白 1 手」で説明できればその (i,j)。
    差が無ければ None、説明できなければ False"""
    if observed == expected:
        return None
    size = len(expected)
    for i in range(size):
        for j in range(size):
            if expected[i][j] == EMPTY and observed[i][j] == WHITE:
                if apply_move_to_grid(expected, i, j, WHITE) == observed:
                    return (i, j)
                return False
    return False


class Harvester:
    """不正解後のヒント歩き。step(frame) を繰り返し呼ぶ（1 回 = 1 フレーム・待ちは deadline で表現）。"""

    def __init__(self, adb, vision, base_grid, size, settle_ms, clock, log):
        self.adb, self.vision, self.base, self.size = adb, vision, [r[:] for r in base_grid], size
        self.settle_s = settle_ms / 1000.0
        self.clock, self.log = clock, log
        self.phase = "close"
        self.grid = None
        self.moves = []
        self.rewind_taps = 0
        self.close_taps = 0
        self.deadline = 0.0
        self.deadline_all = self.clock() + HARVEST_MAX_S
        self.not_before = 0.0
        self.pending = None  # (i, j, expected_grid)
        self.last_obs = None
        self.hint_retry = 0
        self.gray_seen = 0

    def _tap_xy(self, x, y):
        """タップ（AdbError は握って続行）。上げるとコントローラの `_run` の例外カウンタが進み、
        ADB の一時的な失敗でループ全体が止まってしまう"""
        try:
            self.adb.tap(x, y)
            return True
        except AdbError as e:
            self.log(f"[Harvester] タップ失敗: {e}")
            return False

    def _tap_named(self, name, frame):
        self._tap_xy(*self.vision.ui_point(name, frame))
        self.not_before = self.clock() + self.settle_s

    def _fail(self, reason):
        self.log(f"[Harvester] failed: {reason}")
        return "failed", reason

    def step(self, frame):
        now = self.clock()
        if now >= self.deadline_all:
            return self._fail("harvest: 時間切れ")
        if now < self.not_before:
            return "running", None
        if self.phase == "close":
            if self.vision.popup_present(frame):
                if self.close_taps >= CLOSE_MAX_TAPS:
                    return self._fail("close: ポップアップが閉じません")
                self.close_taps += 1
                self._tap_named("popup_view", frame)
                return "running", None
            self.phase = "rewind"
        if self.phase == "rewind":
            try:
                grid = self.vision.read_board(frame, self.size).grid
            except CaptureError:
                return "running", None
            if grid == self.base:
                self.grid = [r[:] for r in grid]
                self.phase = "hint"
            else:
                if self.rewind_taps >= REWIND_MAX_TAPS:
                    return self._fail("rewind: 初期局面に戻せません")
                self.rewind_taps += 1
                self._tap_named("bar_undo", frame)
                return "running", None
        if self.phase == "hint":
            if len(self.moves) >= HARVEST_MAX_MOVES:
                return self._fail("hint: 手数上限")
            self._tap_named("bar_hint", frame)
            self.deadline = self.not_before + HINT_WAIT_S
            self.gray_seen = 0
            self.phase = "wait_hint"
            return "running", None
        if self.phase == "wait_hint":
            try:
                rect = self.vision.board_rect(frame)
            except CaptureError:
                return "running", None  # 遷移画面等で盤が読めないフレーム。次のフレームで
            pt = self.vision.find_hint_circle(frame, rect, self.size)
            if pt is not None:
                self.gray_seen = 0
                i, j = pt
                expected = apply_move_to_grid(self.grid, i, j, BLACK)
                if expected is None:
                    return self._fail(f"hint: 赤丸 {pt} に打てません")
                self._tap_xy(*board_to_device(i, j, rect, self.size))
                self.pending = (i, j, expected)
                self.last_obs = None
                self.not_before = self.clock() + self.settle_s
                self.deadline = self.not_before + MOVE_WAIT_S
                self.phase = "wait_move"
                return "running", None
            if now >= self.deadline:
                if not self.vision.hint_enabled(frame):
                    self.gray_seen += 1
                    if self.gray_seen < 2:
                        return "running", None  # 誤読対策: ヒント灰読みは2連続要求
                    if not self.moves:
                        return self._fail("hint: 手順が取れません")
                    self.log(f"[Harvester] done: {len(self.moves)} 手")
                    return "done", list(self.moves)
                if self.hint_retry < 1:
                    self.hint_retry += 1
                    self.phase = "hint"  # もう 1 回だけ押し直す
                    return "running", None
                return self._fail("hint: 赤丸が出ません（ヒントは有効のまま）")
            return "running", None
        if self.phase == "wait_move":
            i, j, expected = self.pending
            try:
                obs = self.vision.read_board(frame, self.size).grid
            except CaptureError:
                obs = None
            # 盤が変化して2フレーム安定したら受理する（obs[i][j]==BLACK に限定しない）。
            # 投げ込み・ナカデ捨て石は白の応手が黒自身を取るため、その黒点は EMPTY のまま
            # 戻ってこない。白の応手は white_reply（apply_move_to_grid 由来）が判定する。
            if obs is not None and obs != self.grid and obs == self.last_obs:
                w = white_reply(expected, obs)
                if w is False:
                    return self._fail(f"diff: 黒 {(i, j)} の後の盤を説明できません")
                self.moves.append(((i, j), BLACK))
                if w is not None:
                    self.moves.append((w, WHITE))
                self.grid = [r[:] for r in obs]
                self.pending = None
                self.hint_retry = 0
                self.phase = "hint"
                return "running", None
            self.last_obs = obs
            if now >= self.deadline:
                return self._fail(f"move: 黒 {(i, j)} が盤に現れません")
            return "running", None
        return self._fail(f"unknown phase {self.phase}")


# --- 状態機械 ---
STALL_EXTRA_S = 60.0  # STALLED からポップアップをさらに待つ秒数
RESULT_UNKNOWN_RETRIES = 3  # RESULT で verdict が unknown のとき粘るフレーム数（出現アニメーション対策）
CAPTURE_FAILED_WAIT_S = 45.0  # CAPTURE_FAILED でポップアップ（結果）を待つ秒数
FRAME_FAIL_RECONNECT = 3
FRAME_FAIL_GIVEUP = 6
MAX_TAPS_PER_PROBLEM = 60  # 1問あたりのタップ上限（spec §9）
OVERLAY_MAX_TAPS = 3  # 認定証などのオーバーレイを × で閉じにいく連続タップの上限（spec 追記2・4）
OVERLAY_MIN_FRAMES = 2  # × を押す前にオーバーレイを確認するフレーム数（フェード中の誤検出よけ）
OVERLAY_TAP_WAIT_S = 1.5  # × を 1 回押したあと次のタップまでの最低待ち（フェードが終わるまで押さない）
NEXT_MAX_TAPS = 4  # popup が消えないまま NEXT のタップを繰り返してよい回数（超えたら失敗＝当てずっぽうは撃たない）


class _Problem:
    def __init__(self, token, base_grid, key, route, started, header_hash=None, log_name=None):
        self.token, self.base, self.key, self.route, self.started = token, base_grid, key, route, started
        self.size = len(base_grid) if base_grid else None
        self.n_black = 0
        self.rect = None
        self.header_hash = header_hash  # 出題フレームのヘッダ帯のハッシュ（同じ出典・番号なら同じ）
        self.log_name = log_name  # 詰碁ログのファイル名（台帳から 1問1ログ を引くため）


class AutoLoopController:
    def __init__(self, adb, vision, gui, settings, ledger, clock=time.monotonic):
        self.adb, self.vision, self.gui, self.settings, self.ledger, self.clock = adb, vision, gui, settings, ledger, clock
        self.state = "IDLE"
        self.stats = {"problems": 0, "correct": 0, "wrong": 0, "harvested": 0, "failed": 0}
        self._events = queue.Queue()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.problem = None
        self.harvester = None
        self.last_initial = None
        self.last_final = None
        self._await_prev = None
        self._await_retapped = False
        self._deadline = 0.0
        self._not_before = 0.0
        self._frame_failures = 0
        self._errors = 0
        self._cf_tapped = False
        self._cf_wait_one = False  # CAPTURE_FAILED に入った最初の step は打たずに 1 周待つ
        self._cf_base = None
        self._popup_seen = False  # ポップアップを 1 フレーム見た（2 フレーム目で RESULT へ）
        self._result_tries = 0  # RESULT で unknown を粘った回数
        self._pending_taps = []
        self._early_taps = {}  # problem_ready より先に届いた黒手（トークン別）
        self._pending_header = None  # 出題フレームの header_hash（CAPTURING へ入るときに撮る）
        self._overlay_taps = 0  # 認定証などのオーバーレイを閉じにいった連続回数
        self._overlay_seen = 0  # オーバーレイを連続で見たフレーム数（2 枚目から × を押す）
        self._overlay_shot = False  # そのオーバーレイのスクショを 1 枚撮ったか
        self._next_taps = 0  # popup が消えないまま NEXT をタップし続けた回数
        self._unknown_shot = False  # 盤の見えない画面のスクショを 1 枚撮ったか
        self._shots = []
        self._shot_seq = 0

    # --- スレッド ---
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def activate(self):
        """状態だけ AWAIT_PROBLEM にする（テスト・start から使う）"""
        self.state = "AWAIT_PROBLEM"
        self.stats = {"problems": 0, "correct": 0, "wrong": 0, "harvested": 0, "failed": 0}
        self._errors = 0
        self._await_prev = None
        self._await_retapped = False
        self._deadline = self.clock() + self.settings.answer_timeout_s
        self._shots = []
        self._popup_seen = False
        self._result_tries = 0
        self._early_taps = {}
        self._pending_header = None
        self._overlay_taps = 0
        self._overlay_seen = 0
        self._overlay_shot = False
        self._next_taps = 0
        self._unknown_shot = False

    def start(self):
        self._stop.clear()
        self.activate()
        self._thread = threading.Thread(target=self._run, name="tsumego-autoloop", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self.state = "IDLE"
        self._clear_events()  # IDLE 中に溜めない（次の start で前回の黒手が飛び出さないように）
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)
            if t.is_alive():  # 孤児化の診断（このスレッドは daemon なのでプロセスは終われる）
                self.gui.log(f"autoloop: スレッド {t.name} が 2 秒で止まりませんでした")

    def _run(self):
        me = threading.current_thread()
        exc_count = 0
        poll_s = self.settings.poll_ms / 1000.0
        while not self._stop.is_set() and self._thread is me:
            started = self.clock()
            try:
                self.step()
                exc_count = 0
            except Exception as e:  # 1 周の例外でスレッドを落とさない
                exc_count += 1
                self.gui.log(f"autoloop: step で例外: {e!r}")
                if exc_count >= 10:
                    self._to_idle("step の例外が続くため停止しました")
            # step 自体が screencap 等で時間を使うので、その分だけ待ちを縮めて実効周期を保つ
            # （縮めないと poll_ms=500 でも実効 1 Hz 近くまで落ちる）
            self._wake.wait(max(0.0, poll_s - (self.clock() - started)))
            self._wake.clear()

    # --- GUI からのイベント ---
    def on_problem_ready(self, token, base_grid, key, route, log_name=None):
        self._events.put(("problem_ready", token, base_grid, key, route, log_name))
        self._wake.set()

    def on_capture_failed(self, message):
        self._events.put(("capture_failed", message))
        self._wake.set()

    def on_black_move(self, token, coords_xy):
        if coords_xy is None:
            return
        self._events.put(("black_move", token, coords_xy))
        self._wake.set()

    # --- 1 周 ---
    def step(self):
        if self.state == "IDLE":
            return
        self._drain_events()
        if self.state == "IDLE" or self.clock() < self._not_before:
            return
        # 盤の位置が分かっている 2 手目以降は screencap を待たずにタップする（黒の着手が
        # 1 周ぶん遅れないように）。rect 未知・タップ上限のときは従来どおりフレームを見て決める
        if (
            self.state == "ANSWERING"
            and self._pending_taps
            and not self._popup_seen  # 直前のフレームでポップアップが見えていたら盤を触らない
            and self.problem is not None
            and self.problem.rect is not None
            and self.problem.n_black < MAX_TAPS_PER_PROBLEM
        ):
            self._flush_pending_taps()
        try:
            frame = self.adb.screencap()
            self._frame_failures = 0
        except Exception as e:
            self._frame_failures += 1
            if self._frame_failures == FRAME_FAIL_RECONNECT:
                self.gui.log(f"autoloop: 画面取得に連続失敗、ADB へ再接続します（{e}）")
                try:
                    self.adb.connect()
                except Exception:
                    pass
            if self._frame_failures >= FRAME_FAIL_GIVEUP:
                self._fail("adb: 画面が取れません", frame=None)
                self._to_idle("ADB から画面が取れないため停止しました")
            return
        if self.state == "IDLE":
            return  # screencap を待っている間に stop() された（_step_idle は無い）
        getattr(self, f"_step_{self.state.lower()}")(frame)

    def _clear_events(self):
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def _accept_problem(self, token, base_grid, key, route, log_name):
        """problem_ready を受理して ANSWERING へ。先に届いていた黒手はここで拾う（I1）"""
        counted = self.state == "CAPTURE_FAILED"  # CAPTURE_FAILED 入りで既に 1 問数えてある
        self.problem = _Problem(
            token, base_grid, key, route, self.clock(), header_hash=self._pending_header, log_name=log_name
        )
        if not counted:
            self.stats["problems"] += 1
            self._shots = []
        self._popup_seen = False
        self._cf_base = None
        self._pending_taps = self._early_taps.pop(token, [])
        if self._early_taps:
            self.gui.log(f"autoloop: 先行して届いた別トークンの黒手を破棄しました（{list(self._early_taps)}）")
            self._early_taps = {}
        self.state = "ANSWERING"
        self.gui.notify("info", self._banner("解答中"))

    def _drain_events(self):
        while True:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                return
            kind = ev[0]
            if kind == "problem_ready":
                _k, token, base_grid, key, route, log_name = ev
                # CAPTURE_FAILED でも「まだ わざと1手 を打っていない」なら遅れて来たキャプチャを活かす
                # （実測: 再出題の解析が capture_timeout を数秒超えるだけで正答中の問題を潰していた）
                if self.state == "CAPTURING" or (self.state == "CAPTURE_FAILED" and not self._cf_tapped):
                    self._accept_problem(token, base_grid, key, route, log_name)
                else:
                    self.gui.log(f"autoloop: problem_ready を無視しました（state={self.state}）")
            elif kind == "capture_failed":
                if self.state == "CAPTURING":
                    self.gui.log(f"autoloop: キャプチャ失敗 → わざと1手打って収穫に回します（{ev[1]}）")
                    self._enter_capture_failed()
                else:
                    self.gui.log(f"autoloop: capture_failed を無視しました（state={self.state}）")
            elif kind == "black_move":
                _k, token, coords_xy = ev
                if self.state == "ANSWERING" and self.problem is not None and token == self.problem.token:
                    self._pending_taps.append(coords_xy)
                elif self.state == "CAPTURING":
                    # 回答帳ヒット等の高速な再出題では、黒の着手が problem_ready より先に届く。
                    # 捨てるとその手が永久に打たれない（＝解答が止まる）のでトークン別に溜める
                    self._early_taps.setdefault(token, []).append(coords_xy)
                else:
                    self.gui.log(f"autoloop: black_move を無視しました（state={self.state}, token={token}）")

    def _popup_stable(self, frame):
        """ポップアップが 2 フレーム連続で見えたか（ANSWERING / STALLED / CAPTURE_FAILED で使う）。

        出現アニメーション途中のフレームは判定帯（VERDICT_BAND）に別の行が掛かり、tail が
        テンプレートとずれて unknown になる（実機 2026-08-23: 6 問中 2 問）。1 枚目では
        `_popup_seen` を立てるだけにして、次のフレームで確定させる。
        呼び出し側は「present だが 1 枚目」を `self._popup_seen` で判別する。
        """
        if not self.vision.popup_present(frame):
            self._popup_seen = False
            return False
        if not self._popup_seen:
            self._popup_seen = True
            return False
        return True

    def _enter_result(self):
        self._popup_seen = False
        self._result_tries = 0
        self.state = "RESULT"

    def _step_await_problem(self, frame):
        if self._handle_overlay(frame):
            return
        if self.vision.popup_present(frame):
            self.state = "NEXT"
            return
        try:
            grid = self.vision.read_board(frame).grid
        except CaptureError:
            grid = None
        has_stones = grid is not None and any(v != EMPTY for row in grid for v in row)
        if has_stones:
            self._next_taps = 0  # 出題まで来た＝「次の問題」は効いていた
        if grid is None or not has_stones or grid == self.last_initial or grid == self.last_final:
            self._await_prev = None
        elif grid == self._await_prev:
            if self.gui.trigger_capture() is False:
                # 取り込み中／デバウンス中で何も起きなかった。CAPTURING に入ると 25 秒待って
                # CAPTURE_FAILED に落ちるだけなので、AWAIT に留まって次の周で撃ち直す
                self.gui.log("autoloop: キャプチャを起動できませんでした。次の周で再試行します")
                self._check_await_deadline(frame)
                return
            self._await_prev = None
            self._pending_taps = []
            self._early_taps = {}
            self._pending_header = self._header_hash(frame)
            self.state = "CAPTURING"
            self._deadline = self.clock() + self.settings.capture_timeout_s
            return
        else:
            self._await_prev = grid  # 2 フレーム連続で同じになるまで待つ
        self._check_await_deadline(frame)

    def _check_await_deadline(self, frame):
        """出題（NEXT のタップ）を検出できないまま長時間 AWAIT_PROBLEM に留まっていないか。
        1 回目の締切超過で「次の問題」を再タップ、2 回目で _error_step に回す（bounded loop）。

        **再タップは盤が見えているフレームだけ**（spec 追記4）。ホーム画面などアプリの別画面へ
        迷い込んでいると、比率座標の「次の問題」は無関係なボタン（← 戻る等）を押してしまう。
        """
        if self.clock() < self._deadline:
            return
        if not self._await_retapped:
            if self._board_visible(frame):
                self.gui.log("autoloop: 出題を検出できません。「次の問題」を再タップします")
                self._tap(*self.vision.ui_point("bar_next", frame))
            else:
                self.gui.log("autoloop: 盤が見えない画面です（タップしません）")
                if not self._unknown_shot:
                    self._unknown_shot = True
                    self._save_shot(frame, "unknown_screen")
            self._await_retapped = True
        else:
            self._error_step("await_problem: 出題を検出できません")
            self._await_retapped = False
        self._deadline = self.clock() + self.settings.answer_timeout_s

    def _step_capturing(self, frame):
        if self.clock() >= self._deadline:
            self.gui.log("autoloop: キャプチャ完了の通知が来ません（timeout）→ CAPTURE_FAILED")
            self._enter_capture_failed()

    def _step_answering(self, frame):
        if self._handle_overlay(frame):
            return
        p = self.problem
        if self._popup_stable(frame):
            self._enter_result()
            return
        if self._popup_seen:
            return  # ポップアップ 1 枚目。次のフレームで確定させる
        # 締切チェックは pending_taps の処理より前に置く: board_rect が読めない盤が
        # 続く場合でも（pending_taps が残ったままでも）STALLED に必ず抜けられるようにする
        if self.clock() - p.started > self.settings.answer_timeout_s:
            self.state = "STALLED"
            self._popup_seen = False
            self._deadline = self.clock() + STALL_EXTRA_S
            self._save_shot(frame, "stalled")
            return
        if self._pending_taps:
            self._flush_pending_taps(frame)
            return

    def _flush_pending_taps(self, frame=None):
        """溜まっている黒手をアプリ盤へタップする。frame=None は screencap 前の呼び出し
        （盤の矩形が既知のときだけ成立する）。打てたら True"""
        p = self.problem
        if p is None or not self._pending_taps:
            return False
        if p.n_black >= MAX_TAPS_PER_PROBLEM:
            if frame is None:
                return False  # スクショを残したいのでフレームのある周で STALLED に落とす
            self._pending_taps = []
            self._save_shot(frame, "tap_cap")
            self.gui.log(f"autoloop: 1問あたりのタップ上限（{MAX_TAPS_PER_PROBLEM}）に達しました")
            self.state = "STALLED"
            self._popup_seen = False
            self._deadline = self.clock() + STALL_EXTRA_S
            return False
        if p.rect is None:
            if frame is None:
                return False
            try:
                p.rect = self.vision.board_rect(frame)
            except CaptureError:
                return False  # 次のフレームで
        for coords_xy in self._pending_taps:
            i, j = move_to_grid(coords_xy, p.size)
            self._tap(*board_to_device(i, j, p.rect, p.size))
            p.n_black += 1
        self._pending_taps = []
        return True

    def _step_result(self, frame):
        if self._handle_overlay(frame):
            return
        verdict = self.vision.popup_state(frame)
        p = self.problem
        if verdict == "unknown" and self._result_tries < RESULT_UNKNOWN_RETRIES:
            # 出現アニメーション途中で撮れた回は判定帯が壊れて unknown になる。次のフレームで測り直す
            self._result_tries += 1
            return
        if verdict == "none":
            self._record(p, "unknown_popup", harvest="skipped:popup_vanished")
            self.state = "NEXT"  # ポップアップが消えた（ユーザー操作等）
            return
        if verdict == "wrong":
            self.stats["wrong"] += 1
            self._errors = 0
            self.gui.stop_watch()
            base = p.base if (p and p.base) else self._cf_base
            if base is None:
                self._save_shot(frame, "wrong_nobase")
                self._record(p, "wrong", harvest="skipped:盤が読めていない")
                self.state = "NEXT"
                return
            self.harvester = Harvester(self.adb, self.vision, base, len(base), self.settings.settle_ms, self.clock, self.gui.log)
            self.state = "HARVEST"
            self.gui.notify("info", self._banner("収穫中"))
            return
        if verdict == "unknown":
            self._save_shot(frame, "unknown_popup")
        self.stats["correct"] += 1
        self._errors = 0
        harvest = line_len = None
        if verdict == "correct" and p is not None and p.token is not None:
            # 正解した手順も回答帳へ（再出題を解析なしの0秒即答にし、拮抗局面で run ごとに
            # 揺れる正解を凍結する）。回答帳どおりに解答した問題は GUI 側が "book" を返して
            # 再記録しない。unknown_popup はアプリの受理を確認できていないので記録しない
            try:
                harvest, n = self.gui.record_correct(p.token)
                line_len = n or None
            except Exception as e:
                harvest = f"skipped:record_failed:{e!r}"
        self._record(p, "correct" if verdict == "correct" else "unknown_popup", harvest=harvest, line_len=line_len)
        self.state = "NEXT"

    def _enter_capture_failed(self):
        self.state = "CAPTURE_FAILED"
        self._popup_seen = False
        self.problem = _Problem(None, None, None, None, self.clock(), header_hash=self._pending_header)
        self.stats["problems"] += 1  # キャプチャ失敗も 1 問（max_problems の対象）
        self._shots = []
        self._cf_tapped = False
        self._cf_wait_one = True  # 遅れて来る problem_ready のために 1 周だけ待つ
        self._cf_base = None
        self._early_taps = {}
        self._deadline = self.clock() + CAPTURE_FAILED_WAIT_S

    def _step_capture_failed(self, frame):
        if self._popup_stable(frame):
            p = self.problem
            p.base = self._cf_base
            if p.base:
                p.size = len(p.base)
            self._enter_result()
            return
        if self._popup_seen:
            return  # ポップアップ 1 枚目
        if self._cf_wait_one:
            # 「わざと1手」は正答中の問題を潰しうるので、遅れて届くキャプチャ完了に 1 周ぶん
            # 猶予を与える（届けば _drain_events が ANSWERING へ戻す）
            self._cf_wait_one = False
            return
        if not self._cf_tapped:
            try:
                read = self.vision.read_board(frame)
                self._cf_base = [r[:] for r in read.grid]
                far = farthest_empty_point(read.grid)
                if far is not None:
                    i, j = far
                    self._tap(*board_to_device(i, j, read.rect, read.size))
            except CaptureError:
                self._save_shot(frame, "capture_failed")
                w, h = frame.size
                self._tap(w // 2, int(h * 0.46))
            self._cf_tapped = True
            return
        if self.clock() >= self._deadline:
            self._record(self.problem, "capture_failed", harvest="skipped:ポップアップが出ない")
            self._error_step("capture_failed: 結果が出ません")
            if self.state != "IDLE":  # _error_step が上限で IDLE にしていたら上書きしない
                self.state = "NEXT"

    def _step_harvest(self, frame):
        status, payload = self.harvester.step(frame)
        if status == "running":
            return
        p = self.problem
        if status == "done":
            base = p.base if (p and p.base) else self._cf_base
            # ログの保護（.keep）はキャプチャできた問題だけ。CAPTURE_FAILED 由来の収穫では
            # いま開いているのは**前の問題**のログなので、保護すると無関係なログが残り続ける
            protect = bool(p is not None and p.token is not None)
            try:
                added, n = self.gui.save_line(base, payload, protect_log=protect)
            except Exception as e:
                self.gui.log(f"autoloop: 回答帳への保存に失敗: {e!r}")
                self._record(p, "wrong", harvest=f"skipped:save_failed:{e}")
                self.harvester = None
                self.state = "NEXT"
                return
            self.stats["harvested"] += 1
            self._record(p, "wrong", harvest="saved" if added else "duplicate", line_len=n)
            self.gui.notify("save", f"正解手順を回答帳に保存しました（{n}手）")
        else:
            self._save_shot(frame, "harvest_failed")
            self._record(p, "wrong", harvest=f"skipped:{payload}")
            self.gui.log(f"autoloop: 収穫失敗: {payload}")
        self.harvester = None
        self.state = "NEXT"

    def _step_stalled(self, frame):
        if self._handle_overlay(frame):
            return
        if self._popup_stable(frame):
            self._enter_result()
            return
        if self._popup_seen:
            return  # ポップアップ 1 枚目
        if self.clock() >= self._deadline:
            self._record(self.problem, "stalled")
            self._error_step("stalled: 結果が出ません")
            if self.state != "IDLE":
                self.state = "NEXT"

    def _step_next(self, frame):
        if self._handle_overlay(frame):
            return
        try:
            self.last_final = self.vision.read_board(frame).grid
        except CaptureError:
            pass
        if self.problem is not None and self.problem.base:
            self.last_initial = self.problem.base
        if self.vision.popup_present(frame):
            self._tap(*self.vision.ui_point("popup_next", frame))
        elif self._board_visible(frame):
            self._tap(*self.vision.ui_point("bar_next", frame))
        else:
            # 盤もポップアップも見えない画面に比率座標を撃たない（spec 追記4 と同じ方針）。実測
            # 2026-08-24: 昇段カードの上では bar_next が「問題を見る」に当たり別画面へ迷い込む。
            # タップせず AWAIT_PROBLEM の締切処理（盤が見えなければタップしない→error）に委ねる
            self.gui.log("autoloop: 盤もポップアップも見えないため「次の問題」をタップしません")
            if self._next_taps == 0:
                self._save_shot(frame, "unknown_screen")
        self._next_taps += 1
        if self._next_taps > NEXT_MAX_TAPS:
            # 「次の問題」が効いていない＝知らない画面の可能性。当てずっぽうの × は撃たない
            # （旧実装の比率フォールバックが問題画面の ← 戻る を押していた＝spec 追記4）
            self._next_taps = 0
            self._error_step("next: ポップアップが閉じません")
        self.problem = None
        self._cf_base = None
        self._pending_taps = []
        self._early_taps = {}
        self._pending_header = None
        self._not_before = self.clock() + max(self.settings.settle_ms, 300) / 1000.0
        if self.settings.max_problems and self.stats["problems"] >= self.settings.max_problems:
            self._to_idle(f"{self.settings.max_problems} 問に達したため停止しました")
            return
        if self.state == "IDLE":
            return  # _error_step が上限で停止させた（AWAIT_PROBLEM で上書きしない）
        self.state = "AWAIT_PROBLEM"
        self._await_prev = None
        self._await_retapped = False
        self._unknown_shot = False
        self._deadline = self.clock() + self.settings.answer_timeout_s

    # --- 補助 ---
    def _close_point(self, frame):
        """左上の × の座標。見つからなければ None（当てずっぽうのタップはしない＝spec 追記4）。

        比率のフォールバック（旧 CLOSE_FALLBACK_POINT = 0.045,0.035）は、問題画面では
        ヘッダの ← 戻る に当たってアプリをホームへ飛ばす。× は見えているときだけ押す。
        """
        try:
            return self.vision.find_close_glyph(frame)
        except Exception as e:
            self.gui.log(f"autoloop: × を探せません: {e!r}")
            return None

    def _board_visible(self, frame):
        """盤が読める＝問題画面にいる（比率座標の UI ボタンが意味を持つ）"""
        try:
            self.vision.board_rect(frame)
        except CaptureError:
            return False
        except Exception as e:
            self.gui.log(f"autoloop: 盤の位置を取れません: {e!r}")
            return False
        return True

    def _handle_overlay(self, frame):
        """認定証などのフルスクリーン画面なら × をタップして待つ（True なら呼び出し側は return）。

        状態は変えない（オーバーレイが消えた次の周で通常の判定に進む）。閉じられないまま
        OVERLAY_MAX_TAPS を超えたら失敗として打ち切る＝無限にタップし続けない。

        タップの条件は 3 つ（spec 追記4。フェード中の認定証を連打して、消えた後の問題画面の
        ← 戻る を押してしまった事故への対策）: (1) OVERLAY_MIN_FRAMES 連続で検出、
        (2) 1 回ごとに OVERLAY_TAP_WAIT_S 待つ、(3) × が実際に見えている。

        呼び出し元は AWAIT_PROBLEM / ANSWERING / RESULT / STALLED / NEXT の各先頭（spec 追記4）。
        ANSWERING / STALLED でも先頭に置くのは、認定証は popup_present（濃紺のタイトル帯）とは
        別の署名（紙色）なので通常のポップアップ検出には掛からず、放っておくと answer_timeout_s
        （40秒）→ STALLED → STALL_EXTRA_S（60秒）を丸ごと待ってからしか × を押しにいけないため。
        """
        try:
            present = self.vision.overlay_present(frame)
        except Exception as e:
            self.gui.log(f"autoloop: オーバーレイ判定に失敗: {e!r}")
            return False
        if not present:
            self._overlay_taps = 0
            self._overlay_seen = 0
            self._overlay_shot = False
            return False
        self._overlay_seen += 1
        if self._overlay_seen < OVERLAY_MIN_FRAMES:
            return True  # 1 枚目は確認だけ（遷移中の 1 フレームで押しにいかない）
        if self._overlay_taps >= OVERLAY_MAX_TAPS:
            self._overlay_taps = 0
            self._overlay_seen = 0
            self._error_step("overlay: 閉じられません")
            return True
        point = self._close_point(frame)
        if point is None:
            self.gui.log("autoloop: オーバーレイの × が見つかりません（タップしません）")
        else:
            self._tap(*point)
            self.gui.log("autoloop: 認定証などのオーバーレイを閉じます")
        self._overlay_taps += 1
        if not self._overlay_shot:
            self._overlay_shot = True
            self._save_shot(frame, "overlay")
        self._not_before = self.clock() + max(OVERLAY_TAP_WAIT_S, 2 * self.settings.settle_ms / 1000.0)
        return True

    def _tap(self, x, y):
        try:
            self.adb.tap(x, y)
            return True
        except AdbError as e:
            self.gui.log(f"autoloop: タップ失敗: {e}")
            return False

    def _error_step(self, why):
        self._errors += 1
        self.stats["failed"] += 1
        self.gui.log(f"autoloop: {why}（連続 {self._errors}）")
        if self._errors >= self.settings.max_consecutive_errors:
            self._to_idle(f"連続 {self._errors} 回失敗したため停止しました（{why}）")

    def _fail(self, why, frame):
        if frame is not None:
            self._save_shot(frame, "error")
        self._record(self.problem, "error", harvest=f"skipped:{why}")

    def _to_idle(self, text):
        self.state = "IDLE"
        self._clear_events()  # 止まっている間に届くイベントを溜めない
        self.gui.notify("warn", f"自動ループ: {text}")
        self.gui.log(f"autoloop: {text}")

    def _header_hash(self, frame):
        """出題フレームのヘッダ帯のハッシュ（台帳用）。取れなければ None"""
        try:
            return self.vision.header_hash(frame)
        except Exception as e:
            self.gui.log(f"autoloop: header_hash を取れません: {e}")
            return None

    def _banner(self, what):
        s = self.stats
        return f"自動ループ: {what}（{s['problems']}問目 正解 {s['correct']} / 誤答 {s['wrong']} / 収穫 {s['harvested']}）"

    def _record(self, p, outcome, harvest=None, line_len=None):
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "key": p.key if p else None,
            "size": p.size if p else None,
            "route": p.route if p else None,
            "outcome": outcome,
            "elapsed_s": round(self.clock() - p.started, 1) if p else None,
            "n_black": p.n_black if p else 0,
            "harvest": harvest,
            "line_len": line_len,
            "header_hash": p.header_hash if p else None,
            "log": p.log_name if p else None,
            "shots": list(self._shots),
        }
        try:
            self.ledger.append(rec)
        except Exception as e:
            self.gui.log(f"autoloop: 台帳に書けません: {e}")

    def _save_shot(self, frame, tag):
        """スクショを保存しパスを返す（保存できなければ None）。self._shots にも積む。
        ファイル名は per-process カウンタで一意にする（同一秒内の複数保存の衝突回避）"""
        if not hasattr(frame, "save"):
            return None
        try:
            os.makedirs(self.settings.shots_dir, exist_ok=True)
            self._shot_seq += 1
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.settings.shots_dir, f"{ts}_{self._shot_seq:03d}_{tag}.png")
            frame.save(path)
            self._shots.append(path)
            return path
        except Exception as e:
            self.gui.log(f"autoloop: スクショ保存失敗: {e}")
            return None


def main(argv=None):
    """手動確認用 CLI: probe（画面状態を出す）/ tap <name>|<x> <y> / shot <path>"""
    import argparse

    p = argparse.ArgumentParser(prog="python -m katrain.core.tsumego_autoloop")
    p.add_argument("cmd", choices=["probe", "tap", "shot"])
    p.add_argument("args", nargs="*")
    p.add_argument("--adb", default=DEFAULT_ADB_PATH)
    p.add_argument("--serial", default="")
    a = p.parse_args(argv)
    serial = a.serial or discover_serial(a.adb)
    if not serial:
        print("ADB デバイスが見つかりません（BlueStacks 設定で ADB を ON にして再起動）")
        return 2
    adb = AdbClient(a.adb, serial)
    if a.cmd == "shot":
        adb.screencap().save(a.args[0])
        print("saved", a.args[0])
        return 0
    if a.cmd == "tap":
        frame = adb.screencap()
        if len(a.args) == 1:
            x, y = ui_point(a.args[0], frame.size)
        else:
            x, y = int(a.args[0]), int(a.args[1])
        adb.tap(x, y)
        print("tapped", x, y)
        return 0
    frame = adb.screencap()
    vision = Vision((9, 13, 19))
    print("serial", serial, "foreground_package", adb.foreground_package(), "frame", frame.size)
    print("popup_present", vision.popup_present(frame), "popup_state", vision.popup_state(frame))
    print("title_band", round(_band_mean(frame, OVERLAY_TITLE_BAND), 1), "dark", result_title_band_dark(frame))
    print("hint_enabled", vision.hint_enabled(frame), "header", vision.header_hash(frame))
    print("overlay_present", vision.overlay_present(frame), "close_glyph", vision.find_close_glyph(frame))
    print("paper_band", round(_band_mean(frame, OVERLAY_PAPER_BAND), 1), "(認定証ダイアログなら 200 以上)")
    try:
        read = vision.read_board(frame)
        print("board", read.rect, "size", read.size, "stones", sum(v != EMPTY for row in read.grid for v in row))
        print("hint_circle", vision.find_hint_circle(frame, read.rect, read.size))
    except CaptureError as e:
        print("board: 読めません:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
