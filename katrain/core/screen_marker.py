"""他アプリ（BlueStacks）の窓の上に「次にタップする交点」の輪を描く（Windows 専用・Kivy 非依存）。

対局監視モード（board_watch）は アプリ→KaTrain の片方向同期なので、KaTrain の AI が打った手は
ユーザーが手でアプリの盤へタップする。そのたびに KaTrain の盤とアプリの盤を見比べる往復を
無くすため、アプリ盤の該当交点の真上に輪を出す（spec 2026-08-18-board-watch-design.md 追記6）。

仕組み: 最前面・クリック透過（WS_EX_TRANSPARENT）・非アクティブ（WS_EX_NOACTIVATE）の**ピクセル単位の
透明度を持つレイヤードウィンドウ**（WS_EX_LAYERED + UpdateLayeredWindow）に、アンチエイリアスした輪の
ビットマップ（PIL で 8 倍解像度に描いて面積平均＝BOX で縮小）を 1 枚載せる。当初は窓を輪の形に切り抜く
`SetWindowRgn` 方式だったが、Windows の領域は画素単位の階段状にしかならず輪が荒かった（ユーザー報告）。
描画は表示・移動・色変更のたびに 80px 四方を 1 回作るだけ（数ミリ秒・常時の負荷なし）。
アプリには入力もフックも送らない（DWM が上に合成するだけ＝録画ソフトの REC 表示と同種で、
Android 側からは存在を知る手段がない）。

**監視スレッド自身の画面キャプチャに写り込ませない**のが要点。写ると交点分類が壊れる
（輪の画素は石でも空点でもない色なので `?`→認識失敗、しかも盤矩形の fingerprint が毎周変わる）。
`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` で BitBlt（PIL ImageGrab）から除外する
（実測 2026-08-28・build 26200: region 窓の対照＝輪が 1764 画素写る → 除外で差分 0 画素。
AA レイヤード窓でも 対照 2788 画素 → 除外 0 画素。WS_EX_LAYERED だけでは除外されない）。
除外に失敗した環境（Win10 2004 未満）では輪を**出さない**＝監視を壊すより表示を諦める。

座標系は `tsumego_capture.find_window_rect`（GetWindowRect）と同じ画面座標。窓の生成・描画・破棄は
専用スレッド（メッセージループ）が行い、他スレッドは目標状態を書いて PostMessage で起こすだけ。
"""

import ctypes
import ctypes.wintypes
import sys
import threading

# 設定 board_watch.highlight_color の選択肢。キーが設定値、表示名は i18n "board_watch:highlight_color:<キー>"。
# 既定はシアン＝黄色い盤・黒白の石のどれとも混ざらない（輪は自分のキャプチャからは除外されるので認識との衝突は無い）
RING_COLORS = {
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "lime": (0, 255, 0),
    "red": (255, 0, 0),
    "orange": (255, 140, 0),
    "white": (255, 255, 255),
}
RING_COLOR_DEFAULT = "cyan"
RING_COLOR = RING_COLORS[RING_COLOR_DEFAULT]
HIGHLIGHT_OFF = "off"  # 設定値 "off" ＝強調表示しない（ON/OFF と色は設定画面で1つのドロップダウン＝行数を増やさない）


def highlight_choices():
    """設定画面のドロップダウンの選択肢（設定値）: 表示しない ＋ 色プリセット"""
    return [HIGHLIGHT_OFF, *RING_COLORS]


RING_DIAMETER_RATIO = 1.0  # 輪の外径 = セル幅（隣の交点に掛からない）
RING_THICKNESS_RATIO = 0.14  # 線の太さ = 外径 × これ
RING_MIN_THICKNESS = 3
RING_MIN_SIZE = 8
RING_SUPERSAMPLE = 8  # アンチエイリアス: この倍率で描いて面積平均で縮小する（縁は 64 段階）

WDA_EXCLUDEFROMCAPTURE = 0x11


def ring_geometry(x, y, cell):
    """中心 (x, y)・セル幅 cell の輪の窓矩形 (left, top, size) と線の太さを返す（純関数）"""
    size = max(RING_MIN_SIZE, int(round(cell * RING_DIAMETER_RATIO)))
    thickness = max(RING_MIN_THICKNESS, int(round(size * RING_THICKNESS_RATIO)))
    return int(round(x - size / 2)), int(round(y - size / 2)), size, thickness


def ring_color(name):
    """設定値 → RGB。"off" は None（強調表示しない）。未知の値は既定色＝設定が壊れていても輪は出す"""
    if name == HIGHLIGHT_OFF:
        return None
    return RING_COLORS.get(name, RING_COLORS[RING_COLOR_DEFAULT])


def ring_bgra(size, thickness, rgb):
    """輪を size×size の 32bit 事前乗算 BGRA（UpdateLayeredWindow が読む形式）で描いて bytes で返す（純関数）。

    輪の外側・内側は透明、線の中は不透明、縁は縮小で中間の透明度＝アンチエイリアス。
    """
    from PIL import Image, ImageChops, ImageDraw

    ss = RING_SUPERSAMPLE
    big = size * ss
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, big - 1, big - 1), fill=255)
    inset = thickness * ss
    draw.ellipse((inset, inset, big - 1 - inset, big - 1 - inset), fill=0)
    # BOX＝面積平均: 線の内側は正確に 255・外は 0・縁だけ ss² 段階の中間値。LANCZOS は2値マスクで
    # リンギングを起こし内側が 253〜254 になる（実測）＝色の一致判定が揺れるので使わない
    alpha = mask.resize((size, size), Image.BOX)
    r, g, b = rgb
    # 事前乗算 = 各色 × α/255。multiply は (a*b)/255 なので単色チャンネルと α の積でそのまま得られる
    channels = [ImageChops.multiply(Image.new("L", (size, size), c), alpha) for c in (b, g, r)]
    return Image.merge("RGBA", (*channels, alpha)).tobytes()


class ScreenMarker:
    """輪を1つ出す。show/hide/set_color/close はどのスレッドから呼んでもよい（内部で直列化）。

    capture_excluded: None=窓を未作成 / True=画面キャプチャから除外できた / False=できなかった（輪は出ない）
    """

    _CLASS_NAME = "KaTrainScreenMarker"
    _WM_APPLY = 0x8000 + 1  # WM_APP + 1

    def __init__(self, log=None, color=RING_COLOR):
        self._log = log or (lambda message: None)
        self._lock = threading.Lock()
        self._target = None  # ring_geometry の戻り値 or None（消す）
        self._applied = None  # 窓に反映済みの target（None＝非表示）
        self._color = tuple(color)  # 目標の色（set_color で実行時に変えられる）
        self._applied_color = None
        self._thread = None
        self._hwnd = None
        self._ready = threading.Event()
        self._closed = False
        self.capture_excluded = None

    @staticmethod
    def available():
        return sys.platform == "win32"

    # --- 外向き API ---
    def show(self, x, y, cell):
        target = ring_geometry(x, y, cell)
        with self._lock:
            if self._closed or target == self._target:
                return
            self._target = target
        self._kick()

    def hide(self):
        with self._lock:
            if self._target is None:
                return
            self._target = None
        self._kick()

    def set_color(self, rgb):
        """輪の色を変える（表示中なら描き直す）。設定画面で色を変えたときに使う"""
        color = tuple(rgb)
        with self._lock:
            if self._closed or color == self._color:
                return
            self._color = color
            if self._target is None:
                return  # 出していない輪は次の show で新しい色になる
        self._kick()

    def close(self):
        with self._lock:
            self._closed = True
            self._target = None
            thread = self._thread
        if thread is None:
            return
        self._ready.wait(2.0)
        hwnd = self._hwnd
        if hwnd:
            _user32().PostMessageW(hwnd, _WM_CLOSE, 0, 0)
        thread.join(2.0)

    @property
    def visible(self):
        hwnd = self._hwnd
        return bool(hwnd) and bool(_user32().IsWindowVisible(hwnd))

    # --- 内部 ---
    def _kick(self):
        """目標状態が変わった。窓スレッドが無ければ起こし、あれば適用メッセージを投げる"""
        if not self.available():
            return
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="screen-marker", daemon=True)
                self._thread.start()
                return  # スレッドは窓を作った直後に _target を読んで適用する
        if self._ready.is_set() and self._hwnd:
            _user32().PostMessageW(self._hwnd, self._WM_APPLY, 0, 0)

    def _run(self):
        try:
            hwnd = self._create_window()
        except Exception as e:
            self._log(f"screen_marker: 強調表示の窓を作れません: {e!r}")
            self._ready.set()
            return
        self._hwnd = hwnd
        _MARKERS[hwnd] = self
        self._ready.set()  # ここより後に _target を読む＝show() 側の「ready なら post」と噛み合う
        self._apply()
        user32 = _user32()
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        _MARKERS.pop(hwnd, None)
        self._hwnd = None

    def _create_window(self):
        user32 = _user32()
        _register_class()
        ex_style = _WS_EX_TOPMOST | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE | _WS_EX_LAYERED
        hwnd = user32.CreateWindowExW(
            ex_style, self._CLASS_NAME, "KaTrain marker", _WS_POPUP, 0, 0, RING_MIN_SIZE, RING_MIN_SIZE,
            None, None, _hinstance(), None
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW failed (err {ctypes.windll.kernel32.GetLastError()})")
        self.capture_excluded = self._exclude_from_capture(hwnd)
        if not self.capture_excluded:
            self._log("screen_marker: 画面キャプチャからの除外に失敗したため強調表示を出しません（Windows 10 2004 以降が必要）")
        return hwnd

    @staticmethod
    def _exclude_from_capture(hwnd):
        """監視スレッドの ImageGrab に写らないようにする。失敗（0）なら False"""
        return bool(_user32().SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))

    def _apply(self):
        """窓スレッドで目標状態を窓に反映する"""
        with self._lock:
            target = self._target
            color = self._color
        if not self.capture_excluded:
            target = None  # 除外できていない輪は出さない（監視の認識を壊す）
        user32 = _user32()
        hwnd = self._hwnd
        if target is None:
            if self._applied is not None:
                user32.ShowWindow(hwnd, _SW_HIDE)
            self._applied = None
            return
        if target == self._applied and color == self._applied_color:
            return
        left, top, size, thickness = target
        _update_layered(hwnd, left, top, size, ring_bgra(size, thickness, color))
        if self._applied is None:
            user32.ShowWindow(hwnd, _SW_SHOWNA)  # 非アクティブのまま見せる（アプリからフォーカスを奪わない）
        self._applied = target
        self._applied_color = color


# --- Win32 ---
_MARKERS = {}  # hwnd -> ScreenMarker（WndProc から実体へ戻すため）
_WNDPROC_REF = []  # コールバックを GC から守る
_CLASS_REGISTERED = False

_WS_POPUP = 0x80000000
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_SW_HIDE = 0
_SW_SHOWNA = 8
_WM_CLOSE = 0x0010
_WM_DESTROY = 0x0002
_ULW_ALPHA = 0x00000002
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


def _user32():
    return ctypes.windll.user32


def _gdi32():
    return ctypes.windll.gdi32


def _hinstance():
    kernel32 = ctypes.windll.kernel32
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    return kernel32.GetModuleHandleW(None)


def _update_layered(hwnd, left, top, size, bgra):
    """事前乗算 BGRA のビットマップを DIB に写し、位置・大きさごと窓に載せる（UpdateLayeredWindow）"""
    w = ctypes.wintypes
    user32 = _user32()
    gdi32 = _gdi32()
    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth = size
    bmi.biHeight = -size  # 上から下（トップダウン DIB）
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bits = ctypes.c_void_p()
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    try:
        if not bitmap or not bits:
            raise OSError("CreateDIBSection failed")
        ctypes.memmove(bits, bgra, len(bgra))
        old = gdi32.SelectObject(mem_dc, bitmap)
        try:
            dst = w.POINT(left, top)
            dst_size = w.SIZE(size, size)
            src = w.POINT(0, 0)
            blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)
            ok = user32.UpdateLayeredWindow(
                hwnd, None, ctypes.byref(dst), ctypes.byref(dst_size), mem_dc, ctypes.byref(src), 0,
                ctypes.byref(blend), _ULW_ALPHA,
            )
            if not ok:
                raise OSError(f"UpdateLayeredWindow failed (err {ctypes.windll.kernel32.GetLastError()})")
        finally:
            gdi32.SelectObject(mem_dc, old)
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


def _register_class():
    global _CLASS_REGISTERED
    if _CLASS_REGISTERED:
        return
    w = ctypes.wintypes
    user32 = _user32()
    gdi32 = _gdi32()
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.CreateWindowExW.argtypes = [
        w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, w.DWORD]
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.UpdateLayeredWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        w.DWORD, ctypes.c_void_p, w.DWORD,
    ]
    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, w.DWORD,
    ]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

    @wndproc_type
    def wndproc(hwnd, msg, wparam, lparam):
        if msg == ScreenMarker._WM_APPLY:
            marker = _MARKERS.get(hwnd)
            if marker is not None:
                marker._apply()
            return 0
        if msg == _WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == _WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint),
            ("lpfnWndProc", wndproc_type),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", w.LPCWSTR),
            ("lpszClassName", w.LPCWSTR),
        ]

    # hbrBackground=None: レイヤード窓は UpdateLayeredWindow のビットマップがそのまま表示され WM_PAINT を使わない
    wc = WNDCLASSW(0, wndproc, 0, 0, _hinstance(), None, None, None, None, ScreenMarker._CLASS_NAME)
    if not user32.RegisterClassW(ctypes.byref(wc)):
        raise OSError(f"RegisterClassW failed (err {ctypes.windll.kernel32.GetLastError()})")
    _WNDPROC_REF.append(wndproc)
    _CLASS_REGISTERED = True
