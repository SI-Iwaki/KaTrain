"""AI の着手の交点へマウスカーソルを運ぶ（Windows 専用・Kivy 非依存）。

対局監視モード（board_watch）は アプリ→KaTrain の片方向同期なので、KaTrain の AI が打った手は
ユーザーが手でアプリの盤へタップする。その交点には既に輪が出ている（`screen_marker`）が、
ポインタは打つたびにユーザーが盤の上まで動かす必要がある。そこでカーソルを交点の真上へ運んでおく
（将棋側の同種機能 `tools/watch/autoclick.py` のカーソル部分に相当）。

**クリックはしない**（`SetCursorPos` だけ）。押してしまうと盤の読み違いがそのまま手を進めてしまう
＝運ぶだけなら最悪でもポインタの位置がずれるだけで、対局は壊れない。

**同じ手では1回しか運ばない**。呼び出し元 `_board_watch_ahead` は ahead（KaTrain が打ったが
アプリにまだ無い）の間ずっと毎周呼ばれる（窓が動いても輪が追えるように）ので、毎回運ぶと
カーソルがその交点に貼り付いて動かせなくなる。

**アプリが前面のときだけ運ぶ**。別のアプリで作業している最中にポインタを奪わないため。前面化
（SetForegroundWindow）はしない＝画面を奪わない。前面でなかった手番は「運んでいない」ままなので、
ユーザーがアプリへ切り替えた次の周に運ばれる。
"""

import ctypes
import sys


def available():
    """この環境でカーソルを動かせるか（Windows 以外では機能ごと無効）"""
    return sys.platform == "win32"


def move_cursor(x, y):
    """画面座標へカーソルを移動するだけ（クリックはしない）"""
    ctypes.windll.user32.SetCursorPos(int(round(x)), int(round(y)))


def foreground_title():
    """前面のウィンドウのタイトル。取れなければ None（＝運ばない側に倒す）"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:  # noqa: BLE001 Win32 の不調でカーソルを運ばないだけにする（監視は止めない）
        return None


def foreground_matches(window_title, title_fn=foreground_title):
    """前面の窓が監視対象のアプリか（純関数）。

    判定規則は `tsumego_capture.find_window_rect` と同じ＝カンマ区切りの候補・大小無視の部分一致。
    設定が空・タイトルが取れないときは False＝「確かめられないなら運ばない」に倒す
    """
    front = (title_fn() or "").lower()
    if not front:
        return False
    candidates = [t.strip().lower() for t in (window_title or "").split(",") if t.strip()]
    return any(t in front for t in candidates)


class CursorParker:
    """AI の着手の交点へカーソルを運ぶ。`park` を ahead の間 毎周呼んでよい（状態は「最後に運んだ手」だけ）。

    move_fn(x, y) -> None、foreground_fn() -> bool（アプリが前面か）。どちらも注入できる（テスト用）
    """

    def __init__(self, window_title="", move_fn=move_cursor, foreground_fn=None, log=None):
        self.move_fn = move_fn
        self.foreground_fn = foreground_fn or (lambda: foreground_matches(window_title))
        self.log = log or (lambda message: None)
        self._parked = None  # 最後に運んだ手 (i, j)

    def park(self, move, point, enabled=True):
        """必要ならカーソルを運ぶ。実際に運んだら True。

        move: ahead の手 (i, j) or None（解消）、point: `AppBoardReader.screen_point` の戻り値 or None
        """
        if move is None:
            self._parked = None  # 次に同じ交点へ打たれたらまた運ぶ
            return False
        if not enabled or move == self._parked:
            return False
        if point is None:  # 盤矩形がまだ確定していない＝運ばず、次の周にやり直す
            return False
        if not self.foreground_fn():  # 別のアプリが前面＝運ばず、戻ってきた周にやり直す
            return False
        self.move_fn(point[0], point[1])
        self._parked = move
        self.log(f"board_watch: カーソルを着手 {move} の交点 ({point[0]:.0f}, {point[1]:.0f}) へ移動しました")
        return True
