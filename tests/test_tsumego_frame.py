import pytest

from katrain.core.game import BaseGame, KaTrainSGF
from katrain.core.tsumego_frame import (
    dense_core_bbox,
    frameless_region,
    tsumego_frame,
    tsumego_frame_board,
    tsumego_frame_from_katrain_game,
)


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


def test_9x9_small_board_guard_keeps_isolated_stone_intact():
    # 回帰テスト: build_frame の `min(sizes) <= 9` ガードが drop_non_core を強制Falseにしている
    # おかげで、9路以下では非コア石削除が発火しない。ガードが無いと孤立石(7,5)は本体クラスタから
    # Chebyshev距離が離れすぎて非コア判定され、drop_non_core_stonesで消去された後、
    # put_outsideの充填で反対色"B"として再充填されてしまう（盤面が別問題にすり替わる）。
    # tsumego_frame_board（既定 drop_non_core=True）で呼び、(7,5)がWのまま残り、
    # 全11石が無傷（変色も消失もしない）であることを確認する
    board = _board(
        size=9,
        stones=[
            (2, 2, "W"), (3, 1, "W"), (4, 0, "B"), (4, 1, "B"), (4, 2, "W"),
            (5, 1, "B"), (5, 3, "W"), (6, 2, "B"), (7, 1, "W"), (7, 5, "W"), (8, 1, "B"),
        ],
    )
    original = {
        (2, 2): "W", (3, 1): "W", (4, 0): "B", (4, 1): "B", (4, 2): "W",
        (5, 1): "B", (5, 3): "W", (6, 2): "B", (7, 1): "W", (7, 5): "W", (8, 1): "B",
    }
    out, _region = tsumego_frame_board(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    assert out[7][5] == "W", "孤立石(7,5)がガード無効時はdrop_non_coreで消され反対色Bに再充填される"
    for (i, j), color in original.items():
        assert out[i][j] == color, f"元の石({i},{j})が変色/消失している: expected {color}, got {out[i][j]}"


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


# target=60は除外: 60手目は全石bboxがsnapで全盤化しfit_marginがNoneを返す上、
# CORE_MIN_FRACTIONとfit_margin双方を満たす候補クラスタも無く、コア石0・枠石0のno-opになる
@pytest.mark.parametrize("target", [20, 100])
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
    # 枠石が1個も生成されないと上の2アサーションは空集合同士の比較で無条件に通ってしまい、
    # 「重ならない」を何も検証しないまま緑になる。枠が実際に張られたことを保証する
    assert placed, "枠石が1個も生成されていない（このケースは何も検証していない）"
    assert not (set(placed) & occupied), "枠石が既存石と重なっている"
    assert len(placed) == len(set(placed)), "枠石に重複座標がある"
    game.set_current_node(node)  # ここで例外が出なければ配置が正当


def _scattered_outlier_board():
    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    return _board(
        stones=[(ord(p[1]) - 97, ord(p[0]) - 97, "B") for p in ab]
        + [(ord(p[1]) - 97, ord(p[0]) - 97, "W") for p in aw]
    )


def test_drop_non_core_stones_clears_boundary_and_outside():
    # drop_non_core_stones の単体確認: 枠矩形の境界線上と外側の非コア石だけを消す
    from katrain.core.tsumego_frame import drop_non_core_stones

    stones = [[{} for _ in range(13)] for _ in range(13)]
    core = {"stone": True, "black": True, "tsumego_core": True}
    stones[6][8] = dict(core)  # コア石（枠内）
    stones[6][5] = {"stone": True, "black": True}  # 境界線上(j=5)の非コア石
    stones[6][2] = {"stone": True, "black": False}  # 枠外の非コア石
    stones[6][7] = {"stone": True, "black": False}  # 枠内の非コア石
    drop_non_core_stones(stones, (13, 13), [0, 10, 5, 12])
    assert stones[6][5] == {}, "境界線上の非コア石が残っている"
    assert stones[6][2] == {}, "枠外の非コア石が残っている"
    assert stones[6][7].get("stone"), "枠内の非コア石まで消している"
    assert stones[6][8].get("stone"), "コア石を消している"


def test_frame_board_drops_non_core_stones_outside_frame():
    # 枠線上・枠外の非コア石を除去する。壁が石を踏まなくなり充填も穴なしになる。
    # 枠内に残る非コア石（G6）はそのまま。除去にAEは使えない（engine.pyがAEを含む
    # 経路の解析を拒否する）ため、完成局面を単一のAB/AWとして作り直す前提
    board = _scattered_outlier_board()
    out, region = tsumego_frame_board(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    assert region == ((0, 10), (5, 12))
    # F11(2,5) と F9(4,5) は壁(F列)の上 → 除去され、攻め側の色で揃った壁になる
    assert board[2][5] == "B" and board[4][5] == "W"
    wall = {out[i][5] for i in range(0, 11)}
    assert wall in ({"B"}, {"W"}), f"壁が単色で揃っていない: {wall}"
    # D10(3,3) は壁より外側の非コア石。put_border は壁マスを無条件上書きするため wall の
    # チェックだけでは drop_non_core_stones が no-op でも見分けがつかない（それでも単色になる）。
    # ここが drop 有効/無効を区別できる唯一のセル: 無効時は "B" のまま残るのに対し
    # （test_frame_board_keeps_stones_when_drop_disabled 参照）、有効時はここで消去された上で
    # put_outside の市松模様の非充填マスに該当し空点 "-" になる
    assert out[3][3] == "-", "D10が消えていない（drop_non_core_stonesがno-opだと検出できない）"
    # G6(7,6) は枠内なのでそのまま残る
    assert out[7][6] == "W"
    # コア石は一切変わらない
    for i, j in [(0, 11), (1, 9), (3, 8), (4, 9), (8, 10), (8, 11)]:
        assert out[i][j] == board[i][j]


def test_frame_board_keeps_stones_when_drop_disabled():
    board = _scattered_outlier_board()
    out, _region = tsumego_frame_board(
        board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4, drop_non_core=False
    )
    # 除去しない場合、枠外の D10 は put_outside のガードで残る
    assert out[3][3] == "B"


def test_fit_margin_prefers_boundary_without_stones():
    from katrain.core.tsumego_frame import fit_margin

    sizes = (13, 13)
    bbox = (0, 7, 8, 12)  # imin, jmin, imax, jmax
    # 石を渡さなければ従来どおり最大の margin
    assert fit_margin(sizes, 7.0, 4, *bbox) == 2
    # margin 2 の壁(j=5, i=10)上に石があるなら、面積条件を満たす他の margin を選ぶ
    occupied = {(2, 5), (4, 5)}
    assert fit_margin(sizes, 7.0, 4, *bbox, occupied=occupied) == 1


def test_correct_attacker_for_real_capture_fixture():
    # 回帰テスト: 実キャプチャの詰碁（黒が右上のコア塊で白の隅の石を攻めている）で
    # guess_black_to_attack の判定が反転すると、put_border が守り側(白)の色で壁を張り、
    # put_outside が攻め側(黒)に代償地帯を渡してしまう。結果、死活が枠ゲームとして
    # 決定的にならず（黒はどうせ得なので）、正解の攻め合いより空き地の手が最善に
    # 化けてしまう。正しくは壁=黒(攻め側)、枠外の代償地帯は白(守り側)が多くなる。
    board = _scattered_outlier_board()
    out, region = tsumego_frame_board(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    (i0, i1), (j0, j1) = region

    wall = {out[i][j0] for i in range(i0, i1 + 1)}
    assert wall == {"B"}, f"壁は攻め側の黒であるべき: {wall}"

    isize, jsize = len(out), len(out[0])
    black_out = sum(
        1 for i in range(isize) for j in range(jsize) if not (i0 <= i <= i1 and j0 <= j <= j1) and out[i][j] == "B"
    )
    white_out = sum(
        1 for i in range(isize) for j in range(jsize) if not (i0 <= i <= i1 and j0 <= j <= j1) and out[i][j] == "W"
    )
    assert white_out > black_out, f"枠外の代償地帯は守り側の白が多いはず: black={black_out} white={white_out}"


def test_wall_colour_invariant_under_transpose():
    # 不変条件テスト: guess_black_to_attack が height2（転置・反転不変）で重み付けされる以上、
    # 「どちらが攻め側か」は盤の向き（転置）に依存してはいけない。バグ修正前は
    # tsumego_frame_stones が反転・転置後の向きで extrema を再計算しており、min_by の
    # タイ崩れ（同座標の石が複数あるとき、その時点の配列順＝現在の向きの row-major順で
    # 勝者が決まる）が向きごとに異なる石を選んでしまい、判定が反転しうるバグだった。
    # 盤を転置(i/j入替)しても壁の色が変わらないことを確認する。
    board = _scattered_outlier_board()
    size = len(board)
    transposed = [[board[j][i] for j in range(size)] for i in range(size)]

    out1, region1 = tsumego_frame_board(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    out2, region2 = tsumego_frame_board(transposed, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)

    (i0, i1), (j0, j1) = region1
    (ti0, ti1), (tj0, tj1) = region2
    wall1 = {out1[i][j0] for i in range(i0, i1 + 1)}
    # 転置盤では壁の向きも転置され、元の列方向の壁が行方向の壁になる
    wall2 = {out2[ti0][j] for j in range(tj0, tj1 + 1)}
    assert wall1 == wall2, f"転置で壁の色が変わった: {wall1} vs {wall2}"


def _m10_board():
    # 実機キャプチャの13路詰碁。右上26子が詰碁本体、D10/F11/F9/G6 が離れた石
    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    return _board(
        stones=[(ord(p[1]) - 97, ord(p[0]) - 97, "B") for p in ab]
        + [(ord(p[1]) - 97, ord(p[0]) - 97, "W") for p in aw]
    )


def test_dense_core_bbox_drops_distant_stones():
    # 枠なしモードのコア検出: gap=1 で本体26子(87%)を保持できるので離れた石が落ちる。
    # mark_core_stones は「枠が張れないときだけ絞る」ため枠なし経路では使えない
    assert dense_core_bbox(_m10_board()) == (0, 7, 8, 12)


def test_dense_core_bbox_keeps_loose_shape_together():
    # 2路飛びに並ぶ緩い形は gap=1 だと4つに分断され最大クラスタが25%まで落ちるので
    # CORE_MIN_FRACTION に届かず gap=2 へ上がり、1塊としてまとまる
    board = _board(stones=[(5, 5, "B"), (5, 7, "W"), (7, 5, "W"), (7, 7, "B")])
    assert dense_core_bbox(board) == (5, 5, 7, 7)


def test_dense_core_bbox_empty_board():
    assert dense_core_bbox(_board()) is None


def test_frameless_region_pad1_contains_answer_and_excludes_open_area():
    # コアbbox(0,7,8,12) + pad1 → 行0..9・列6..12。実測でこの範囲なら正解手 M10 が
    # 1位（1113 visits）になり、pad2 だと空き地の J3 が競合して負ける
    region = frameless_region(_m10_board(), 1)
    assert region == ((0, 9), (6, 12))
    (i0, i1), (j0, j1) = region
    assert i0 <= 3 <= i1 and j0 <= 11 <= j1, "正解手 M10 (i3,j11) がリージョン外"
    assert not (i0 <= 10 <= i1 and j0 <= 8 <= j1), "空き地の J3 (i10,j8) がリージョン内"


def test_frameless_region_does_not_mutate_board():
    # 枠なしモードの要は「盤面がアプリと完全に同一」であること
    board = _m10_board()
    before = [row[:] for row in board]
    frameless_region(board, 1)
    assert board == before


def test_frameless_region_none_when_covering_whole_board():
    # 盤全体に広がる詰碁では set_region_of_interest が None 正規化するのと同じ扱いにする
    board = _board(stones=[(0, 0, "B"), (0, 12, "W"), (12, 0, "W"), (12, 12, "B")])
    assert frameless_region(board, 1) is None
