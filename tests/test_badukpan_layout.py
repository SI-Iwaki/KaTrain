"""BadukPanWidget（盤の描画）のレイアウト回帰テスト。

詰碁の自動ループで盤の上のバナー（TsumegoBookBanner）が出たり消えたりすると、盤が
バナーに重なることがあった（実測 2026-08-24・窓を半分にした状態）。

`draw_board` は格子座標 `gridpos` を「最初の格子点の **x** が動いたか」でしか作り直して
いなかったため、ウィジェットの高さだけが変わる（バナー 0→30dp で盤の高さが縮む）と、
幅が律速の窓では grid_size も x も変わらず、縦の余白だけが変わる＝古い `gridpos_y` の
まま描かれて盤が上へはみ出す。横幅が律速でない（高さが律速の）窓では grid_size が
変わって x も動くので偶然直っていた＝「重ならないこともある」の正体。
"""

import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import pytest


class _Game:
    board_size = (9, 9)
    insert_mode = False


class _KaTrain:
    game = _Game()


@pytest.fixture(scope="module")
def make_widget():
    pytest.importorskip("kivy")
    pytest.importorskip("kivymd")
    from kivy.lang import Builder
    from kivy.properties import ObjectProperty, StringProperty
    from kivy.uix.widget import Widget
    from kivymd.app import MDApp

    import katrain.gui.badukpan as badukpan

    badukpan.cached_texture = lambda *_a, **_k: None  # 盤画像は読まない（座標だけ検証する）

    # 同じ pytest プロセスで先に gui.kv が読まれていると <BadukPanWidget> の kv ルール
    # （size: self.parent.height / katrain: app.gui / app.language への bind）が適用されるので、
    # 親と実行中アプリを用意しておく（テスト順序に依存させない）
    class _App(MDApp):
        language = StringProperty("en")
        gui = ObjectProperty(None, allownone=True)

    app = MDApp.get_running_app() or _App()
    if not hasattr(app, "gui"):  # 別テストが先に作ったアプリでも katrain: app.gui を評価できるようにする
        app.gui = None

    def _make(pos, size):
        parent = Widget(size=(size[0] + pos[0], size[1] + pos[1]))
        # kv が子を組み立てるのと同じ順序（生成→親に追加→ルール適用）にしないと、__init__ 時点で
        # parent が None のまま size: self.parent.height が評価されて落ちる
        w = badukpan.BadukPanWidget(__no_builder=True)
        parent.add_widget(w)
        Builder.apply(w)
        w.katrain = _KaTrain()
        w.pos = pos
        w.size = size
        return w

    return _make


def _grid_inside(widget):
    ys = [row[0][1] for row in widget.gridpos]
    xs = [p[0] for p in widget.gridpos[0]]
    return (
        widget.y <= min(ys) - widget.grid_size / 2
        and max(ys) + widget.grid_size / 2 <= widget.top
        and widget.x <= min(xs) - widget.grid_size / 2
        and max(xs) + widget.grid_size / 2 <= widget.right
    )


def test_height_only_shrink_recomputes_grid_y(make_widget):
    """幅が律速の窓で高さだけ縮む（バナー出現）と gridpos_y が作り直される。"""
    w = make_widget((0, 60), (400, 700))  # 幅が律速（400/10.25 < 700/10.25）
    w.draw_board()
    grid_before = w.grid_size
    ys_before = [row[0][1] for row in w.gridpos]
    assert _grid_inside(w)

    w.size = (400, 670)  # バナー 30px ぶん高さだけ縮む。grid_size は不変
    w.draw_board()
    assert w.grid_size == grid_before
    ys_after = [row[0][1] for row in w.gridpos]
    assert ys_after != ys_before, "高さだけの変化で gridpos_y が作り直されていない"
    assert _grid_inside(w), "盤がウィジェットの外（バナー側）へはみ出している"


def test_pos_y_only_move_recomputes_grid_y(make_widget):
    """ウィジェットが縦に平行移動しただけでも gridpos_y が追随する。"""
    w = make_widget((0, 60), (400, 700))
    w.draw_board()
    ys_before = [row[0][1] for row in w.gridpos]

    w.pos = (0, 30)
    w.draw_board()
    ys_after = [row[0][1] for row in w.gridpos]
    assert [b - a for a, b in zip(ys_before, ys_after)] == pytest.approx([-30] * len(ys_before))
