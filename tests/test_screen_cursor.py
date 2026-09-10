"""AI の着手の交点へマウスカーソルを運ぶ（screen_cursor）。

Win32 は呼ばず、カーソル移動と「前面の窓」を注入して判定だけを確かめる。
要点は2つ: **同じ手では1回しか運ばない**（ahead の間 毎周呼ばれるのでカーソルが貼り付く）と、
**アプリが前面でないときは運ばない**（別のアプリで作業中にポインタを奪わない）。
"""

from katrain.core.screen_cursor import CursorParker, foreground_matches


class FakeCursor:
    """move_cursor の代わり。運ばれた座標を記録するだけ"""

    def __init__(self):
        self.points = []

    def __call__(self, x, y):
        self.points.append((x, y))


def make_parker(cursor=None, foreground=True):
    cursor = cursor or FakeCursor()
    state = {"foreground": foreground}
    parker = CursorParker(move_fn=cursor, foreground_fn=lambda: state["foreground"])
    return parker, cursor, state


def test_parks_the_cursor_once_for_the_same_move():
    parker, cursor, _ = make_parker()
    assert parker.park((3, 4), (100.4, 200.6, 40), enabled=True) is True
    assert parker.park((3, 4), (100.4, 200.6, 40), enabled=True) is False
    assert cursor.points == [(100.4, 200.6)]


def test_parks_again_when_the_ai_plays_a_different_move():
    parker, cursor, _ = make_parker()
    parker.park((3, 4), (100, 200, 40), enabled=True)
    parker.park((5, 5), (150, 250, 40), enabled=True)
    assert cursor.points == [(100, 200), (150, 250)]


def test_does_not_park_while_another_app_is_in_front_and_parks_when_it_comes_back():
    parker, cursor, state = make_parker(foreground=False)
    assert parker.park((3, 4), (100, 200, 40), enabled=True) is False
    assert cursor.points == []
    state["foreground"] = True
    assert parker.park((3, 4), (100, 200, 40), enabled=True) is True
    assert cursor.points == [(100, 200)]


def test_does_nothing_while_the_setting_is_off_and_parks_after_it_is_turned_on():
    parker, cursor, _ = make_parker()
    assert parker.park((3, 4), (100, 200, 40), enabled=False) is False
    assert cursor.points == []
    assert parker.park((3, 4), (100, 200, 40), enabled=True) is True
    assert cursor.points == [(100, 200)]


def test_forgets_the_move_once_the_app_has_caught_up():
    parker, cursor, _ = make_parker()
    parker.park((3, 4), (100, 200, 40), enabled=True)
    parker.park(None, None, enabled=True)  # ahead 解消
    parker.park((3, 4), (100, 200, 40), enabled=True)  # 同じ交点にもう一度打たれた
    assert cursor.points == [(100, 200), (100, 200)]


def test_does_not_park_before_the_board_rectangle_is_known():
    parker, cursor, _ = make_parker()
    assert parker.park((3, 4), None, enabled=True) is False  # screen_point がまだ None
    assert cursor.points == []
    parker.park((3, 4), (100, 200, 40), enabled=True)  # 盤矩形が確定した次の周で運ぶ
    assert cursor.points == [(100, 200)]


def test_foreground_matches_accepts_any_of_the_comma_separated_candidates():
    assert foreground_matches("BlueStacks,Puzzle Run", lambda: "Puzzle Run - Chrome") is True


def test_foreground_matches_ignores_case_like_find_window_rect():
    assert foreground_matches("BlueStacks", lambda: "bluestacks app player") is True


def test_foreground_matches_is_false_for_another_app():
    assert foreground_matches("BlueStacks", lambda: "KaTrain") is False


def test_foreground_matches_is_false_when_the_title_is_unknown():
    assert foreground_matches("BlueStacks", lambda: None) is False


def test_foreground_matches_is_false_without_a_configured_title():
    assert foreground_matches("", lambda: "BlueStacks") is False
