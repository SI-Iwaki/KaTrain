"""対局盤面監視の野狐囲碁（淡い黄の盤）対応のテスト（spec 2026-08-18-board-watch-design.md 追記12）。

tests/data/board_watch_fox19_*.png はユーザー提供の実スクショ4枚（盤だけの切り抜き・19路）。
1 = 直前手の三角印つきの黒石＋空点の白い四角カーソル、2 = 三角印つきの白石＋黒い四角カーソル、
3・4 = 直前手の白石の上に残り秒数「1」＋黒い四角カーソル。期待値は分類結果を画像と目視で照合した石の並び。
"""

import os

import pytest

import katrain.core.board_watch as bw
from katrain.core.board_watch import EMPTY

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_FOX = [os.path.join(_DATA_DIR, f"board_watch_fox19_{n}.png") for n in (1, 2, 3, 4)]
_YELLOW = [
    os.path.join(_DATA_DIR, name)
    for name in (
        "board_watch_before.png",
        "board_watch_after.png",
        "board_watch_start_black.png",
        "board_watch_start_white.png",
        "tsumego_app_sample.png",
        "tsumego_app_sample_9x9.png",
        "tsumego_app_sample_dense9.png",
        "tsumego_app_sample_sparse13.png",
    )
]
_MISSING = not all(os.path.exists(p) for p in _FOX + _YELLOW)
pytestmark = pytest.mark.skipif(_MISSING, reason="スクショが未取得")

_TOP_1 = [
    "................W..",
    "..............B.BW.",
    "...W...B.......BW..",
    "....W.....W....BW..",
    "..B.WB.B.......BW..",
    "....W.....B...WWBW.",
    "..B.............BW.",
    "...BWW........B.B..",  # (7, 14) は直前手の三角印つきの黒石
    "....B..............",
    "...................",
    "...................",
    "...................",  # (11, 6) は白い四角カーソル＝石ではない
    "...................",
]
_TOP_2 = [
    "................W..",
    "..............BW.W.",  # (1, 15) は直前手の三角印つきの白石
    "...W...B.......BW..",
    "....W.....W..W.BW..",
    "..B.WB.B.....WBBW..",
    "....W.....B.WBWWBW.",
    "..B..........B..BW.",
    "...BWW........B.B..",
    "....B..............",  # (8, 11) は黒い四角カーソル＝石ではない
    "...................",
    "...................",
    "...................",
    "...................",
]
_TOP_3 = [
    "................W..",
    "..............BW.W.",
    ".B.W...B.W...WBBW..",
    "....W.....W..W.BW..",
    "..B.WB.B.BW..WBBW..",
    "....W...WWB.WBWWBW.",
    "..B....B.BB..B..BW.",
    "..BBWW........B.B..",
    "..WWB..............",
    "....B..............",
    "...W...............",  # (10, 3) は残り秒数つきの白石、(10, 9) は黒い四角カーソル＝石ではない
    "...................",
    "...................",
]
_BOTTOM = [
    "..B................",
    "...................",
    "...W...........B...",
    ".....W.............",
    "...................",
    "...................",
]
_EXPECTED = [_TOP_1 + _BOTTOM, _TOP_2 + _BOTTOM, _TOP_3 + _BOTTOM, _TOP_3 + _BOTTOM]


def _open(path):
    from PIL import Image

    return Image.open(path).convert("RGB")


def _rows(grid):
    return ["".join(row) for row in grid]


def _recognize(img):
    from katrain.core.tsumego_capture import classify_wood_intersections, detect_wood_board, detect_wood_grid

    size, xs, ys = detect_wood_grid(img, detect_wood_board(img))
    return size, classify_wood_intersections(img, xs, ys), xs, ys


def test_fox_board_is_pale_and_quest_board_is_not():
    """経路の判別の固定: 野狐の盤は黄盤検出も通るが「淡い黄」、囲碁クエスト系の黄盤は淡くない"""
    from katrain.core.tsumego_capture import detect_board, is_pale_wood_board

    for path in _FOX:
        img = _open(path)
        assert is_pale_wood_board(img, detect_board(img)), path
    for path in _YELLOW:
        img = _open(path)
        assert not is_pale_wood_board(img, detect_board(img)), path


def test_fox_screenshots_recognized_grids():
    """直前手の三角印・残り秒数つきの石は石のまま、空点の四角カーソルは石にしない"""
    for path, expected in zip(_FOX, _EXPECTED):
        size, grid, _xs, _ys = _recognize(_open(path))
        assert size == 19, path
        assert _rows(grid) == expected, path


@pytest.mark.parametrize("color", [(0, 0, 0), (255, 255, 255)])
def test_cursor_square_on_any_empty_point_is_not_a_stone(color):
    """カーソルは盤のどこにでも出る（カーソルを運ぶ設定では AI の着手点の真上）。辺・隅・星でも石にしない"""
    from PIL import ImageDraw

    img = _open(_FOX[0])
    _size, _grid, xs, ys = _recognize(img)
    half = round((xs[1] - xs[0]) * 0.245)  # 実測の四角は一辺 18px（セル 37px）
    points = [(18, 0), (18, 18), (9, 9), (12, 12), (17, 9), (9, 0)]
    draw = ImageDraw.Draw(img)
    for i, j in points:
        cx, cy = round(xs[j]), round(ys[i])
        draw.rectangle((cx - half, cy - half, cx + half, cy + half), fill=color)
    _size, grid, _xs, _ys = _recognize(img)
    for i, j in points:
        assert grid[i][j] == EMPTY, (i, j)
    assert _rows(grid) == _EXPECTED[0]


def _reader_on(monkeypatch, img):
    from katrain.core.tsumego_capture import detect_board, detect_size_and_classify

    monkeypatch.setattr(
        bw,
        "_capture_api",
        lambda: (
            lambda _t: (100, 200, 100 + img.size[0], 200 + img.size[1]),
            lambda _r: img,
            detect_board,
            detect_size_and_classify,
        ),
    )
    return bw.AppBoardReader("対局室", [9, 13, 19])


def test_reader_reads_fox_board_through_line_detection(monkeypatch):
    """野狐の盤は黄盤検出が通っても格子線検出の経路で読む。囲碁クエスト用の対局者アイコン読みは動かさない"""
    for path, expected in zip(_FOX, _EXPECTED):
        reader = _reader_on(monkeypatch, _open(path))
        assert _rows(reader.read()) == expected, path
        assert reader._profile == "wood"
        assert reader.size == 19
        assert reader.player_icon_colors() == (None, None)
        assert reader.near_player_color() is None
        _size, _grid, xs, ys = _recognize(_open(path))
        x, y, cell = reader.screen_point(3, 15)
        assert (x, y) == pytest.approx((100 + xs[15], 200 + ys[3]))
        assert cell == pytest.approx(xs[1] - xs[0], abs=0.5)


def test_quest_board_still_reads_through_quest_profile(monkeypatch):
    """囲碁クエスト系の黄盤は従来どおり quest 経路（木目盤経路の関数に触れない）"""

    def no_wood_api():
        raise AssertionError("黄盤なのに格子線検出の経路が呼ばれた")

    monkeypatch.setattr(bw, "_wood_api", no_wood_api)
    reader = _reader_on(monkeypatch, _open(os.path.join(_DATA_DIR, "board_watch_before.png")))
    reader.read()
    assert reader._profile == "quest"


def test_pale_board_never_falls_back_to_quest_path(monkeypatch):
    """淡い黄の盤で格子線が取れない周は失敗させる（黄盤経路で読み直すと経路がフレームごとに入れ替わる）"""
    from katrain.core.tsumego_capture import CaptureError, detect_wood_board

    def failing_grid(_img, _rect, _sizes):
        raise CaptureError("木目盤の格子線を検出できません")

    reader = _reader_on(monkeypatch, _open(_FOX[0]))
    monkeypatch.setattr(bw, "_wood_api", lambda: (detect_wood_board, failing_grid, None))
    with pytest.raises(CaptureError, match="格子線"):
        reader.read()
    assert reader._profile is None


@pytest.mark.parametrize("text", ["8", "15", "28", "30", "60"])
@pytest.mark.parametrize("font_size", [16, 20, 22])
def test_countdown_digits_on_last_stone_keep_stone_color(text, font_size):
    """直前手の石の上の残り秒数（実物は白石の上の「1」しか無いので合成）。2 桁は石の中心を広く覆い、
    中心パッチだけだと "?" や逆の色になる＝石の縁の色で決める。実測の数字は高さ約 17px（セル 37px）"""
    from PIL import ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except OSError:
        pytest.skip("太字フォントが無い")
    img = _open(_FOX[2])
    _size, _grid, xs, ys = _recognize(img)
    draw = ImageDraw.Draw(img)
    stones = [
        (13, 2, "white"),
        (15, 15, "white"),
        (2, 1, "white"),
        (16, 5, "black"),
        (0, 16, "black"),
        (15, 3, "black"),
    ]
    for i, j, fill in stones:  # 黒石には白い数字、白石には黒い数字
        draw.text((round(xs[j]), round(ys[i])), text, fill=fill, font=font, anchor="mm")
    _size, grid, _xs, _ys = _recognize(img)
    assert _rows(grid) == _EXPECTED[2]


@pytest.mark.parametrize("scale", [0.6, 0.85, 1.4, 1.7])
def test_fox_board_recognized_at_other_window_sizes(scale):
    """窓の大きさが変わっても（セル 22〜63px）同じ石の並びになる＝四角カーソルの検算はセル比で効く"""
    from PIL import Image

    for path, expected in zip(_FOX[:3], _EXPECTED[:3]):
        img = _open(path)
        img = img.resize((round(img.size[0] * scale), round(img.size[1] * scale)), Image.LANCZOS)
        size, grid, _xs, _ys = _recognize(img)
        assert size == 19
        assert _rows(grid) == expected, (path, scale)


def test_packaged_config_is_ascii_and_matches_fox_window_title():
    """同梱 config.json は ASCII だけで書く（非 ASCII は JSON のエスケープ）。

    Kivy の JsonStore は encoding を指定せずに開く＝日本語 Windows では cp932 で読むので、UTF-8 の生の
    日本語は化けたまま保存し直される（実測: 窓タイトルの候補が化けて「ウィンドウが見つかりません」）
    """
    import json

    path = os.path.join(os.path.dirname(_DATA_DIR), "..", "katrain", "config.json")
    with open(path, "rb") as f:
        raw = f.read()
    assert all(b < 128 for b in raw)
    candidates = json.loads(raw.decode("ascii"))["board_watch"]["window_title"].split(",")
    fox_title = "> [高級対局室1] > 46113号対局室　観戦中 [29手目] - レーティング"
    assert any(c.strip() and c.strip().lower() in fox_title.lower() for c in candidates)
    assert candidates[0] == "BlueStacks"  # BlueStacks が開いていれば従来どおりそちらが優先


# ============================================================
# 自分の色（ユーザー一覧の自分の行＝名前・石アイコン・赤いピン。spec 追記13）
# ============================================================

_GAME = [os.path.join(_DATA_DIR, f"board_watch_fox_game_white{n}.png") for n in (1, 2)]  # 自分が白の対局中の窓全体
_GAME_STONES = [
    {(3, 3): "B", (3, 15): "B", (15, 3): "W"},  # (15, 15) は白い四角カーソル＝石ではない
    {
        (2, 15): "B",
        (2, 16): "W",
        (3, 3): "B",
        (3, 15): "B",
        (3, 16): "W",
        (4, 15): "B",
        (4, 16): "W",
        (5, 16): "B",  # 直前手の印つき
        (13, 2): "B",
        (15, 3): "W",
        (15, 15): "W",
    },
]
_GAME_MISSING = not all(os.path.exists(p) for p in _GAME)


def _own_pin(img, board_rect):
    """石アイコンつきの赤いピンの外接矩形（テストの合成用）"""
    boxes = [
        box
        for box in bw._fox_pin_clusters(img, board_rect[2] + bw.FOX_PIN_SEARCH_GAP)
        if bw._fox_stone_left_of(img, box) is not None
    ]
    assert len(boxes) == 1
    return boxes[0]


@pytest.mark.skipif(_GAME_MISSING, reason="野狐の対局中のスクショが未取得")
def test_fox_own_color_is_read_from_user_list_pin(monkeypatch):
    """対局中の窓全体: 盤が読め、自分の色（白）が (自分, 逆の色) で返る＝開始時に KaTrain の AI を白へ移せる"""
    for path, stones in zip(_GAME, _GAME_STONES):
        reader = _reader_on(monkeypatch, _open(path))
        grid = reader.read()
        assert {(i, j): v for i, row in enumerate(grid) for j, v in enumerate(row) if v != EMPTY} == stones, path
        assert reader.player_icon_colors() == ("W", "B"), path
        assert reader.near_player_color() == "W", path


@pytest.mark.skipif(_GAME_MISSING, reason="野狐の対局中のスクショが未取得")
def test_fox_own_color_black_and_spectator(monkeypatch):
    """自分が黒（石アイコンを黒く塗った合成）は B、自分の行に石アイコンが無い（観戦）・ピンが無いは None"""
    from PIL import ImageDraw

    from katrain.core.tsumego_capture import detect_board

    base = _open(_GAME[0])
    rect = detect_board(base)
    x0, y0, _x1, _y1 = _own_pin(base, rect)
    stone = (x0 - bw.FOX_PIN_STONE_GAP - bw.FOX_PIN_STONE_SIZE, y0, x0 - bw.FOX_PIN_STONE_GAP - 1, y0 + 13)

    black = base.copy()
    ImageDraw.Draw(black).ellipse(stone, fill=(20, 20, 20))
    assert bw.fox_self_color(black, rect) == "B"

    spectator = base.copy()  # 石アイコンを一覧の地の色で消す＝観戦中の自分の行
    ImageDraw.Draw(spectator).rectangle(stone, fill=(236, 236, 236))
    assert bw.fox_self_color(spectator, rect) is None

    no_pin = base.copy()
    ImageDraw.Draw(no_pin).rectangle((x0 - 1, y0 - 1, x0 + 13, y0 + 16), fill=(236, 236, 236))
    assert bw.fox_self_color(no_pin, rect) is None

    reader = _reader_on(monkeypatch, black)
    reader.read()
    assert reader.player_icon_colors() == ("B", "W")


# ============================================================
# 取り込み時の手番（直前手の印＝最後に打った色。spec 追記14）
# ============================================================


def test_last_mover_is_read_from_last_move_mark(monkeypatch):
    """三角の印・残り秒数つきの石が直前手。印の無い交点は1つも拾わない（ちょうど1つのときだけ確定）"""
    for path, expected in zip(_FOX, ["B", "W", "W", "W"]):
        reader = _reader_on(monkeypatch, _open(path))
        reader.read()
        assert reader.last_mover_color() == expected, path


@pytest.mark.skipif(_GAME_MISSING, reason="野狐の対局中のスクショが未取得")
def test_import_turn_follows_last_move_mark(monkeypatch):
    """3子以上の盤でも、直前手が黒なら白番で取り込む（従来は人間側の色に固定＝自分の手番でも AI が動かない）"""
    from katrain.core.board_watch import import_next_player

    reader = _reader_on(monkeypatch, _open(_GAME[1]))  # 11手目・直前手は黒・自分は白
    grid = reader.read()
    assert reader.last_mover_color() == "B"
    assert import_next_player(grid, "B", reader.last_mover_color()) == ("W", "直前手の印から確定")
    assert import_next_player(grid, "B", None) == ("B", "人間側に固定")  # 印が読めなければ従来どおり


def test_last_mover_is_none_without_exactly_one_mark(monkeypatch):
    """印が無い・2つある盤は判定しない"""
    from PIL import ImageDraw

    img = _open(_FOX[0])
    _size, _grid, xs, ys = _recognize(img)
    draw = ImageDraw.Draw(img)
    draw.polygon(  # 2つ目の印を別の黒石 (4, 2) の上に描く
        [(xs[2], ys[4]), (xs[2] + 9, ys[4]), (xs[2], ys[4] + 9)], fill=(255, 255, 255)
    )
    reader = _reader_on(monkeypatch, img)
    reader.read()
    assert reader.last_mover_color() is None


def test_quest_last_mover_is_read_from_red_square(monkeypatch):
    """囲碁クエストの直前手の印（石の中心の赤い四角）。印の無い詰碁アプリの画面は None"""
    from katrain.core.board_watch import import_next_player

    for name, expected in [
        ("board_watch_before.png", "B"),
        ("board_watch_after.png", "B"),
        ("board_watch_start_black.png", "W"),
        ("board_watch_start_white.png", "B"),
        ("tsumego_app_sample.png", None),
        ("tsumego_app_sample_dense9.png", None),
    ]:
        reader = _reader_on(monkeypatch, _open(os.path.join(_DATA_DIR, name)))
        grid = reader.read()
        assert reader._profile == "quest"
        assert reader.last_mover_color() == expected, name
    # 22 子の対局中（直前手は黒）: 自分が白でも白番で取り込む
    reader = _reader_on(monkeypatch, _open(os.path.join(_DATA_DIR, "board_watch_start_white.png")))
    grid = reader.read()
    assert import_next_player(grid, "B", reader.last_mover_color())[0] == "W"


def test_wood_app_last_mover_is_read_from_ring(monkeypatch):
    """木目盤アプリの直前手の印（石の上の輪）。19路の1手差ペアは 黒 → 白（G17）と入れ替わる"""
    for name, expected in [
        ("board_watch_wood19_before.png", "B"),
        ("board_watch_wood19_after.png", "W"),
        ("board_watch_wood13.png", "W"),
        ("board_watch_wood9.png", "W"),
    ]:
        path = os.path.join(_DATA_DIR, name)
        if not os.path.exists(path):
            pytest.skip("木目盤アプリのスクショが未取得")
        reader = _reader_on(monkeypatch, _open(path))
        reader.read()
        assert reader._profile == "wood" and not reader._pale
        assert reader.last_mover_color() == expected, name


SPECTATE1 = os.path.join(_DATA_DIR, "board_watch_fox_spectate1.png")
SPECTATE2 = os.path.join(_DATA_DIR, "board_watch_fox_spectate2.png")
# 実スクショのパネルを Windows OCR で読んだ行（0 は「ロ」と読まれる）。OCR 自体は実 OCR テスト側で通す
FAKE_LINES = {
    SPECTATE1: ["黒 コ ミ 3 又 3 / 4 子", "30 分", "九 段 ・ 一 一 七 段 王 澤 錦", "ロ 子 ア ゲ ハ マ ロ 子"],
    SPECTATE2: ["黒 コ ミ 3 又 3 / 4 子", "1 分", "9 段 の い ・ 9 段", "ロ 子 ア ゲ ハ マ 3 子"],
}


def _count(grid, color):
    return sum(row.count(color) for row in grid)


def test_spectate_screenshots_read_board_and_info(monkeypatch):
    """観戦中の野狐の実スクショ2枚（盤の石数・プロファイル・窓タイトルの手数と手番・パネルのコミ）"""
    from katrain.core.board_spectate import read_spectate_info

    for path, title, counts, info in [
        (SPECTATE1, "> [高級対局室1] > 46453号大会対局室　観戦中 [85手目] - 大会", (43, 42), (85, "W")),
        (SPECTATE2, "> [高級対局室1] > 46372号対局室　観戦中 [98手目] - レーティング - 中国ルール", (49, 46), (98, "B")),
    ]:
        reader = _reader_on(monkeypatch, _open(path))
        grid = reader.read()
        assert (_count(grid, "B"), _count(grid, "W")) == counts and reader.profile_name() == "fox"
        monkeypatch.setattr(reader, "window_title_text", lambda t=title: t)
        got = read_spectate_info(reader, ocr=lambda img, p=path: FAKE_LINES[p])
        assert (got.app_move_number, got.next_player) == info and got.komi == 7.5


def test_non_fox_reader_gives_only_next_player(monkeypatch):
    from katrain.core.board_spectate import read_spectate_info

    reader = _reader_on(monkeypatch, _open(_YELLOW[0]))
    reader.read()
    assert reader.profile_name() == "quest"
    got = read_spectate_info(reader, ocr=lambda img: pytest.fail("OCR must not run for non-fox"))
    assert got.komi is None and got.rules is None and got.app_move_number is None
