import pytest

from katrain.core.tsumego_frame import tsumego_frame


def _board(size=13, stones=()):
    board = [["-" for _ in range(size)] for _ in range(size)]
    for i, j, color in stones:
        board[i][j] = color
    return board


def test_partial_board_tsumego_region():
    # 通常ケース: 盤の一部に収まる詰碁 → 枠矩形（bbox+margin）がそのままリージョンになる
    board = _board(
        stones=[(3, 3, "B"), (3, 5, "W"), (5, 3, "W"), (5, 5, "B")]
    )
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=2)
    assert region == ((1, 7), (1, 7))


def test_full_height_tsumego_region_not_degenerate():
    # 回帰テスト: 縦方向ほぼ全域に広がる詰碁（右端寄り）では枠矩形+marginが上下とも盤外に
    # はみ出し、境界マークが縦1線に退化して get_analysis_region が False を返していた
    # （→リージョンなし＝全盤解析になり、AIゲート・枠外刈り取りが全て不活性化する）
    board = _board(
        stones=[(1, 10, "B"), (3, 8, "W"), (5, 12, "B"), (10, 9, "W")]
    )
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # i(行)は端スナップで 0..12 全域。j(列)は適応marginにより 4 → 1 に縮み（margin 4 では
    # 外側52目 < 必要78.5目で枠ゲームが一方的になる）、8-1=7 から右端まで
    assert region == ((0, 12), (7, 12))


def test_9x9_margin_clamped_so_frame_fits():
    # 回帰テスト: 9路でmargin=4は枠矩形が全方向で盤外にはみ出し、壁・充填が一切置けず
    # リージョンも全盤（→None正規化→全盤解析）になっていた。9路以下はmarginを2に
    # クランプして壁+リージョンが成立するようにする（左半分を占める詰碁の実例形）
    board = _board(
        size=9,
        stones=[
            (2, 2, "W"), (3, 1, "W"), (4, 0, "B"), (4, 1, "B"), (4, 2, "W"),
            (5, 1, "B"), (5, 3, "W"), (6, 2, "B"), (7, 1, "W"), (7, 5, "W"), (8, 1, "B"),
        ],
    )
    blacks, whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # 縦は端スナップで全域、横は bbox(0..5)+クランプ後margin(2) = 0..7 → 全盤にならずリージョン成立
    assert region == ((0, 8), (0, 7))
    # 壁が盤内（j=7列）に置かれ、枠として機能する
    assert any(j == 7 for _i, j in blacks + whites)


def test_outlier_stone_falls_back_to_main_cluster():
    # 回帰テスト: 詰碁本体（上辺側）から遠く離れた無関係の石が1つ混ざると、全石のbbox+margin
    # が盤全体を覆い、壁・充填・リージョンが一切生成されず全盤解析に退化していた
    # （13路詰碁でD4相当の石によりK4が最善手として評価された実例）。
    # 最大クラスタ＝詰碁本体だけで枠範囲を取り直し、クラスタ外の石は上書きせず盤上に残す
    board = _board(
        stones=[
            # 詰碁本体（i=9..11 の上辺側クラスタ、実例の左上詰碁を転記）
            (11, 0, "W"), (11, 1, "W"), (11, 2, "W"), (11, 3, "W"), (11, 5, "W"),
            (11, 6, "B"), (11, 7, "B"),
            (10, 1, "B"), (10, 2, "W"), (10, 3, "B"), (10, 10, "W"),
            (9, 1, "B"), (9, 2, "B"), (9, 3, "B"), (9, 5, "B"), (9, 6, "B"), (9, 8, "B"),
            (3, 3, "B"),  # 離れた無関係の石（D4相当）
        ]
    )
    blacks, whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # クラスタbbox(i 9..12, j 0..12) + 適応margin(4→2) → 壁はi=7の1本、リージョンは上側のみ
    # （全盤にならない。適応margin導入前は壁i=5だった）
    assert region == ((7, 12), (0, 12))
    # 壁・充填が生成される（修正前は枠石0個だった）
    assert any(i == 7 for i, _j in blacks + whites)
    # クラスタ外の石は枠石で上書きされない（AB/AWが既存石と衝突するとIllegalMoveException）
    assert (3, 3) not in blacks and (3, 3) not in whites


def test_adaptive_margin_large_top_problem():
    # 適応marginの回帰テスト: 上辺4行×全幅の大型詰碁は margin=4 だと外側が65目しか残らず
    # （必要78.5目）、枠ゲームが黒+36の一方的な勝負になり正解手と別解がスコアノイズで並ぶ。
    # margin を 2 に縮めて外側91目を確保する（K12/H13誤答の実例形）
    board = _board(
        stones=[(12, 0, "B"), (12, 11, "W"), (9, 1, "B"), (9, 11, "B")]
    )
    blacks, whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # bbox(i 9..12, j 0..12) + margin2 → 壁は i=7 の1本、外側は i 0..6 の91目
    assert region == ((7, 12), (0, 12))
    assert any(i == 7 for i, _j in blacks + whites)


def test_adaptive_margin_bottom_right_problem():
    # 適応marginの回帰テスト: 右下寄りだが左(j=4)と上(i=7)に伸びた詰碁は margin=4 だと
    # 外側13目のみで黒+130に飽和し、死活（正解N2）より空き地の手(D2)が選ばれていた実例形。
    # margin を 1 に縮めて外側79目を確保する
    board = _board(
        stones=[
            (7, 11, "B"), (5, 9, "B"), (5, 10, "B"), (5, 11, "B"), (4, 8, "B"),
            (3, 9, "B"), (2, 8, "B"), (2, 9, "B"), (1, 9, "B"), (0, 9, "B"),
            (4, 10, "W"), (4, 11, "W"), (2, 4, "W"), (2, 7, "W"), (2, 10, "W"),
            (1, 7, "W"), (1, 8, "W"), (1, 10, "W"), (0, 11, "W"),
        ]
    )
    blacks, whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # bbox(i 0..7, j 4..12) + margin1 → 壁は j=3 と i=8、リージョンは右下に密着
    assert region == ((0, 8), (3, 12))
    assert any(j == 3 for _i, j in blacks + whites)


def test_full_board_tsumego_region_covers_board():
    # 詰碁+marginが盤全体を覆う極端ケース: 全盤リージョンを返す
    # （set_region_of_interest 側が全盤リージョンを None に正規化するので実害なし）
    board = _board(
        stones=[(1, 1, "B"), (1, 11, "W"), (11, 1, "W"), (11, 11, "B")]
    )
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    assert region == ((0, 12), (0, 12))
