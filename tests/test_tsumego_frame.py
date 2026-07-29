import pytest

from katrain.core.game import BaseGame, KaTrainSGF
from katrain.core.tsumego_frame import tsumego_frame, tsumego_frame_from_katrain_game


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
    # 全石bbox(j 0..5)ではクランプ後margin 2でも外側9目のみ（必要34.5目）で勝率が飽和する。
    # 孤立した (7,5) を落として 10/11 に絞ると bbox(j 0..3)+margin1 で外側36目を確保できる
    assert region == ((0, 8), (0, 4))
    # 壁が盤内（j=4列）に置かれ、枠として機能する
    assert any(j == 4 for _i, j in blacks + whites)


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


def test_scattered_outliers_narrow_to_core_cluster():
    # 回帰テスト: 詰碁本体（右上26子）から離れた D10/F11/F9/G6 が cluster_gap=4 で
    # 芋づるに連結し主クラスタ=全30石になるため、枠が最下段13子だけに退化していた実例。
    # 結果リージョンが盤全体→None正規化→全盤解析となり、空き地の D8 が最善手になった。
    # gap を段階的に縮めて 26/30 に絞り、枠とリージョンが成立することを確認する
    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    board = _board(
        stones=[(ord(p[1]) - 97, ord(p[0]) - 97, "B") for p in ab]
        + [(ord(p[1]) - 97, ord(p[0]) - 97, "W") for p in aw]
    )
    blacks, whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # コア bbox(i 0..8, j 7..12) + 適応margin(4→2) → 壁は F列(j=5) と 3行目(i=10)
    assert region == ((0, 10), (5, 12))
    assert any(j == 5 for _i, j in blacks + whites)
    # 不正解手 D8 = (i=5, j=3) はリージョン外、正解手 M10 = (i=3, j=11) はリージョン内
    (i0, i1), (j0, j1) = region
    assert not (i0 <= 5 <= i1 and j0 <= 3 <= j1)
    assert i0 <= 3 <= i1 and j0 <= 11 <= j1
    # 枠が退化していない（修正前は最下段13子のみだった）
    assert len(blacks) + len(whites) > 40


def test_region_falls_back_to_core_bbox_when_frame_covers_board():
    # 横方向に全幅、縦は中央付近に収まる詰碁では、どのmarginでも外側面積が足りず
    # fit_margin が縮められないため枠矩形が盤全体に膨らみ、リージョンが全盤になる
    # （→ set_region_of_interest が None 正規化 → 全盤解析）。コアbbox+padで下限を保証する
    board = _board(stones=[(3, 0, "B"), (3, 12, "W"), (9, 0, "W"), (9, 12, "B"), (6, 6, "B")])
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # コアbbox(i 3..9, j 0..12) + pad2 → i 1..11 に縮み、縦が盤より小さいので全盤にならない
    assert region == ((1, 11), (0, 12))


def test_region_fallback_declines_when_problem_reaches_edges():
    # 端に届く詰碁では snap により bbox が全盤になるため、フォールバックは働かず
    # 全盤リージョンのまま返す（端の手を候補から外すのは危険なため）
    board = _board(stones=[(1, 1, "B"), (1, 11, "W"), (11, 1, "W"), (11, 11, "B")])
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    assert region == ((0, 12), (0, 12))


class _StubKatrain:
    def log(self, *_args, **_kwargs):
        pass

    def config(self, *_args, **_kwargs):
        return None


@pytest.mark.parametrize("target", [20, 60, 100])
def test_manual_frame_never_places_on_occupied_point(target):
    # 回帰テスト: put_border は既存石をチェックせず上書きするため、壁が石を踏むと
    # 占有点への AB/AW になり _init_chains が "Space occupied" で落ちる（同色でも落ちる）。
    # 従来は枠が退化して石をほとんど置かないため顕在化していなかったが、
    # コア検出の修正で枠が張れるようになると実戦の密な局面で踏む
    root = KaTrainSGF.parse_file("tests/data/ogs.sgf")
    game = BaseGame(_StubKatrain(), move_tree=root)
    for _ in range(target):
        if not game.current_node.children:
            break
        game.set_current_node(game.current_node.children[0])
    occupied = {s.coords for s in game.stones}
    node, _region = tsumego_frame_from_katrain_game(game, 6.5, True, ko_p=False, margin=4)
    placed = [m.coords for m in node.placements]
    assert not (set(placed) & occupied), "枠石が既存石と重なっている"
    assert len(placed) == len(set(placed)), "枠石に重複座標がある"
    game.set_current_node(node)  # ここで例外が出なければ配置が正当
