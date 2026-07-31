import pytest

from katrain.core.game import BaseGame, KaTrainSGF
from katrain.core.tsumego_frame import (
    dense_core_bbox,
    frame_destroys_problem,
    frameless_region,
    solver_core_points,
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


def _case_s_core():
    # 実キャプチャ 2026-07-31 case S の認識盤（13路右上。黒が M10 から白を無条件に殺す詰碁で、
    # 黒＝攻め方）。左端の列 H に H11(白) と H10(黒) が縦に並んでおり、「左辺の極値」を
    # どちらの石で代表させるかで guess_black_to_attack の符号が反転する:
    #   H11(白) を採る … -1  → black_to_attack=False（誤。実キャプチャはこちらを引いた）
    #   H10(黒) を採る … +42 → black_to_attack=True （正）
    # 極値線の石を全部足せば +21 で、タイの崩し方に依存しなくなる
    gtp = lambda p: (13 - int(p[1:]), "ABCDEFGHJKLMN".index(p[0]))  # noqa: E731
    black = "M13 K12 L12 K11 H10 K10 J9 J8 J7 K7 L7 M6 L5".split()
    white = "M12 N12 H11 L11 L10 K8 L8 M8 M7".split()
    return _board(stones=[(*gtp(p), "B") for p in black] + [(*gtp(p), "W") for p in white])


def test_extremum_tie_does_not_decide_the_attacker():
    # 回帰テスト（case S）: 極値線に同座標の石が複数あるとき、min_by は「その時点の配列順
    # ＝row-major 順で最初の1子」を代表にする。case S の左辺は H11(白) が H10(黒) より先に
    # 来るため白が代表になり、判定が -1 という紙一重の差で反転していた。
    # 反転した枠は攻め方(黒)に代償地帯を渡すので黒が +21目リードし、死活がスコアから
    # 切り離されて詰碁と無関係な H12 が選ばれた（枠なし盤なら正解 M10 を選べていた）
    board = _case_s_core()
    out, region = tsumego_frame_board(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    (i0, i1), (j0, j1) = region

    wall = {out[i][j0] for i in range(i0, i1 + 1)}
    assert wall == {"B"}, f"壁は攻め側の黒であるべき: {wall}"

    isize, jsize = len(out), len(out[0])
    outside = [
        out[i][j] for i in range(isize) for j in range(jsize) if not (i0 <= i <= i1 and j0 <= j <= j1)
    ]
    assert outside.count("W") > outside.count("B"), (
        f"枠外の代償地帯は守り側の白が多いはず: black={outside.count('B')} white={outside.count('W')}"
    )


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


def test_dense_core_bbox_rejects_monochrome_cluster():
    # 回帰テスト: 黒12子の密な塊(75%)がgap=1で単独クラスタ化して閾値を満たすが、
    # 単色なので却下されるべき。却下せずに採用すると、攻められている側である
    # 白の目標石4子（黒塊からChebyshev距離3）が丸ごとリージョン外に落ち、
    # 詰碁の対象そのものが解析候補から消える（この場合はgap=3で両色が併合されて
    # 復帰する）。frameless_region経由で白石が範囲内に収まることを確認する
    board = _board(
        stones=[(i, j, "B") for i in range(4, 7) for j in range(2, 6)]
        + [(i, j, "W") for i in range(5, 7) for j in range(8, 10)]
    )
    region = frameless_region(board, 1)
    assert region is not None, "リージョンが盤全体に退化している"
    (i0, i1), (j0, j1) = region
    white_target = [(i, j) for i in range(5, 7) for j in range(8, 10)]
    for i, j in white_target:
        assert i0 <= i <= i1 and j0 <= j <= j1, f"白の目標石 ({i},{j}) がリージョン外: region={region}"


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


def test_frame_balance_distance():
    # 枠は「攻め方成功 = offence_to_win(5) 目勝ち」に調整する設計。|lead| が 5 から離れるほど枠が壊れている
    from katrain.core.tsumego_frame import frame_balance_distance

    assert frame_balance_distance(5.0) == pytest.approx(0.0)
    assert frame_balance_distance(-5.0) == pytest.approx(0.0)  # 攻め方の色に依存しない
    assert frame_balance_distance(-23.3) == pytest.approx(18.3)
    assert frame_balance_distance(0.0) == pytest.approx(5.0)


def test_pick_balanced_frame_prefers_the_workable_frame():
    # 実測値（2026-07-29, 400visits）。コウが正解の問題では ko_p=False で守り側にコウダテが
    # 渡り白が無条件生き（-24.0）、ko_p=True で +1.9。コウでない問題は逆に ko_p=True が過剰
    from katrain.core.tsumego_frame import pick_balanced_frame

    ko_case = [(False, "boardA", "regA", -24.02), (True, "boardB", "regB", 1.92)]
    assert pick_balanced_frame(ko_case)[0] is True
    non_ko_case = [(False, "boardA", "regA", 2.82), (True, "boardB", "regB", 14.80)]
    assert pick_balanced_frame(non_ko_case)[0] is False


def test_pick_balanced_frame_ignores_failed_analyses():
    # 解析が取れなかった枠（lead=None）は候補から外す。全滅なら None（呼び出し側が設定値へ戻す）
    from katrain.core.tsumego_frame import pick_balanced_frame

    assert pick_balanced_frame([(False, "a", "r", None), (True, "b", "r", 1.92)])[0] is True
    assert pick_balanced_frame([(False, "a", "r", None), (True, "b", "r", None)]) is None
    assert pick_balanced_frame([]) is None


def test_pick_balanced_frame_prefers_attacker_ko_threats_on_a_tie():
    # バランスが拮抗しているときは攻め方にコウダテを渡す枠（ko_p=True）を採る。
    # 詰碁はコウダテがある前提で正解が決まり、守り側にコウダテが渡るとコウ手が無価値になるため
    # （実測 2026-07-30: 距離 12.36 vs 11.61 の僅差でコイン投げになり、外れると誤答した）
    from katrain.core.tsumego_frame import pick_balanced_frame

    assert pick_balanced_frame([(False, "a", "r", 5.0), (True, "b", "r", -5.0)])[0] is True
    assert pick_balanced_frame([(False, "a", "r", -17.36), (True, "b", "r", -16.61)])[0] is True


def test_pick_balanced_frame_keeps_the_better_balance_beyond_the_tie_margin():
    # 差が大きいときはバランス優先（コウでない問題に攻め方コウダテを渡すと得をさせすぎる）
    from katrain.core.tsumego_frame import pick_balanced_frame

    assert pick_balanced_frame([(False, "a", "r", 2.82), (True, "b", "r", 14.80)])[0] is False


def test_frame_destroys_problem_uses_the_solver_stones_average():
    # 実測 2026-07-30、枠採用時（trial 400visits、リージョン内の本体石のみ、手番=黒）:
    #   case D  +8.00/8   (+1.00/子) 正常 → 枠を使う
    #   case E +21.98/22  (+1.00/子) 正常 → 枠を使う
    #   case F -10.33/11  (-0.94/子) 壊れ → 枠を捨てる（枠なしでも正解 N8）
    #   case G -10.86/11  (-0.99/子) 壊れ → 枠を捨てる（枠ありは誤答 B13、枠なしで正解 A11）
    assert frame_destroys_problem(-10.86, 11) is True
    assert frame_destroys_problem(-10.33, 11) is True
    assert frame_destroys_problem(8.00, 8) is False
    assert frame_destroys_problem(21.98, 22) is False


def test_frame_destroys_problem_rejects_stones_that_are_merely_not_dead():
    # case F の ko=False 枠は -0.98/11 = -0.09/子 で 0 付近。閾値を 0 にすると run ごとに
    # 符号が反転して枠採否がコイン投げになるため、「明確に生きている（+0.5/子）」を要求する。
    # 実測の正常枠は両ケースとも +1.00/子 なので上下 0.5 の余裕がある
    assert frame_destroys_problem(-0.98, 11) is True
    assert frame_destroys_problem(0.09 * 11, 11) is True
    assert frame_destroys_problem(0.6 * 11, 11) is False


def test_frame_destroys_problem_is_silent_without_stones():
    # 手番側の石がまだ無い問題（相手の石だけの図）では判定できないので枠を捨てない
    assert frame_destroys_problem(0.0, 0) is False


def test_frame_solver_verdict_lets_the_deeper_reading_overrule_the_shallow_one():
    # 実測 2026-07-30 case N（13路・生き問題・手番側コア10子）: trial 400visits では
    # -8.01/10 (-0.80/子) で死と読まれるが、読み直し（1800visits・wideRootNoise=0）では
    # +9.70/10 (+0.97/子) で生き。
    # 浅い読みだけで枠を捨てると枠なし盤（lead -75目・コア -0.79/子）に落ちて詰碁自体が消える
    from katrain.core.tsumego_frame import frame_solver_verdict

    assert frame_solver_verdict([(400, -8.01), (1800, 9.70)], 10) == (False, 1800, 9.70)


def test_frame_solver_verdict_confirms_a_genuinely_broken_frame():
    # 実測 2026-07-30: 本当に壊れている枠は深く読むと**より明確に**死ぬ
    #   case F ko=False -0.20/子(400) → -0.72/子(読み直し) ／ case G ko=False -0.98 のまま
    from katrain.core.tsumego_frame import frame_solver_verdict

    assert frame_solver_verdict([(400, -2.20), (1800, -7.92)], 11) == (True, 1800, -7.92)
    assert frame_solver_verdict([(400, -10.72), (1800, -10.78)], 11) == (True, 1800, -10.78)


def test_frame_solver_verdict_keeps_the_shallow_verdict_when_the_deep_read_fails():
    # 深い読みが取れなかった（エンジン停止・タイムアウト）場合に枠を生かすと、壊れた枠を
    # 掴んだまま出題してしまう。読めた中で最も深い読みで裁定する＝現行動作（枠を捨てる）を保つ
    from katrain.core.tsumego_frame import frame_solver_verdict

    assert frame_solver_verdict([(400, -8.01), (1800, None)], 10) == (True, 400, -8.01)
    assert frame_solver_verdict([(400, None), (1800, None)], 10) == (False, None, None)


def test_frame_solver_verdict_with_a_single_reading_matches_frame_destroys_problem():
    # 浅い読みで生きていれば読み直さない（読み直しは死と出た枠だけのコスト）
    from katrain.core.tsumego_frame import frame_solver_verdict

    assert frame_solver_verdict([(400, 8.00)], 8) == (False, 400, 8.00)
    assert frame_solver_verdict([(400, -10.86)], 11) == (True, 400, -10.86)
    assert frame_solver_verdict([], 11) == (False, None, None)
    assert frame_solver_verdict([(400, 0.0)], 0) == (False, 400, 0.0)  # 手番側の石が無い図


def _reader(by_visits, calls):
    """(visits -> (lead, solver_ownership, stone_count)) を返す read。呼ばれた深さを calls に積む"""

    def read(candidate, visits):
        calls.append((candidate[0], visits))
        return by_visits[visits]

    return read


def test_frame_validity_verdicts_rereads_before_dropping_a_frame():
    # case N（生き問題）の実測: 400visits では両枠とも死（-0.80/-0.99 per stone）だが、
    # ko=False は読み直し（1800visits・wRN=0）で +0.97/子 に反転して有効。
    # 読み直さないと枠なしに落ちて誤答した
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    candidates = [(False, "boardF", "regF"), (True, "boardT", "regT")]
    readers = {
        "boardF": _reader({400: (-6.20, -8.01, 10), 1800: (-0.44, 9.70, 10)}, calls),
        "boardT": _reader({400: (2.77, -9.88, 10), 1800: (2.55, -9.92, 10)}, calls),
    }
    verdicts = frame_validity_verdicts(candidates, lambda c, v: readers[c[1]](c, v), 400, 1800)
    assert [(v.ko_p, v.destroys, v.visits) for v in verdicts] == [(False, False, 1800), (True, True, 400)]
    # バランス判定に使う lead も深い読みの値に差し替わる（-6.20 → -0.44）
    assert verdicts[0].lead == pytest.approx(-0.44)
    # 浅い読みは両枠とも先に測るが、深い読みは「生きに近い ko=False」だけで打ち切る
    # （有効な枠が1つ出れば残りを深く読んでも出題する枠は変わらない。1本 3〜4 秒かかる）
    assert calls == [(False, 400), (True, 400), (False, 1800)]


def test_frame_validity_verdicts_rereads_every_frame_when_none_survives():
    # case F/G のように全枠が壊れている場合は全部読み直してから枠なしに落ちる
    # （frame_over_frameless の比較材料として、捨てる枠の深い読みが要る）
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    candidates = [(False, "boardF", "regF"), (True, "boardT", "regT")]
    readers = {
        "boardF": _reader({400: (-31.9, -2.20, 11), 1800: (-40.9, -7.92, 11)}, calls),
        "boardT": _reader({400: (-26.3, -10.01, 11), 1800: (-25.4, -10.56, 11)}, calls),
    }
    verdicts = frame_validity_verdicts(candidates, lambda c, v: readers[c[1]](c, v), 400, 1800)
    assert all(v.destroys and v.visits == 1800 for v in verdicts)
    assert calls == [(False, 400), (True, 400), (False, 1800), (True, 1800)]  # 浅い読みが良い順


def test_frame_validity_verdicts_does_not_reread_a_living_frame():
    # 追加コストを払うのは捨てる寸前の枠だけ（毎回の深い読みはキャプチャの待ち時間になる）
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    read = _reader({400: (5.0, 8.0, 8), 1800: (5.0, 8.0, 8)}, calls)
    verdicts = frame_validity_verdicts([(False, "board", "region")], read, 400, 1800)
    assert (verdicts[0].destroys, verdicts[0].visits) == (False, 400)
    assert calls == [(False, 400)]


def test_frame_validity_verdicts_confirms_a_borderline_living_frame():
    # 回帰テスト（case S）: 読み直しは「浅い読みで死と出た枠」にしか課しておらず、浅い読みの
    # 「生」はそのまま採用していた。ところが浅い読みは死側にも生側にも振れる。case S の実測は
    # 同じ枠・同じ 400visits で +0.4977/子（死と出て読み直し→枠なし→正解）と +0.65/子
    # （生と出てそのまま出題→誤答）の両方を引いており、1800visits では +0.46/子 で壊れ判定。
    # 閾値近傍の「生」は採用する前に確かめる（＝安全網を両側で対称にする）
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    read = _reader({400: (24.64, 8.45, 13), 1800: (21.77, 6.01, 13)}, calls)
    verdicts = frame_validity_verdicts([(False, "board", "region")], read, 400, 1800)
    assert (verdicts[0].destroys, verdicts[0].visits) == (True, 1800)
    assert calls == [(False, 400), (False, 1800)]


def test_frame_validity_verdicts_keeps_a_confirmed_borderline_frame():
    # 生きる詰碁では手番側の石そのものが戦いの対象なので、正しい枠でも +1.00/子 にはならない
    # （実測 case M の正しい役割の枠: 400/1800visits とも +0.72/子）。帯に入るので確認の
    # 読み直しは走るが、確認できたら従来どおり枠を使う
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    read = _reader({400: (-19.64, 5.04, 7), 1800: (-19.46, 5.05, 7)}, calls)
    verdicts = frame_validity_verdicts([(False, "board", "region")], read, 400, 1800)
    assert (verdicts[0].destroys, verdicts[0].visits) == (False, 1800)
    assert calls == [(False, 400), (False, 1800)]


def test_frame_validity_verdicts_confirms_a_borderline_frame_even_beside_a_living_one():
    # 打ち切りは「死と出た枠の**救済**は要らない」という意味しか持たせない。閾値近傍で生と
    # 出た枠を確かめずに残すと、それが pick_balanced_frame の候補として残り、バランス次第で
    # **確かめていない枠が出題される**（case S で誤答したのと同じ状態）
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    candidates = [(False, "boardF", "regF"), (True, "boardT", "regT")]
    readers = {
        "boardF": _reader({400: (5.0, 9.5, 10), 1800: (5.0, 9.5, 10)}, calls),  # +0.95/子 = 自明に生き
        "boardT": _reader({400: (4.0, 6.0, 10), 1800: (4.0, 4.2, 10)}, calls),  # +0.60 → +0.42 で壊れ
    }
    verdicts = frame_validity_verdicts(candidates, lambda c, v: readers[c[1]](c, v), 400, 1800)
    assert [(v.ko_p, v.destroys, v.visits) for v in verdicts] == [(False, False, 400), (True, True, 1800)]
    assert calls == [(False, 400), (True, 400), (True, 1800)]


def test_frame_validity_verdicts_skips_the_rescue_of_a_dead_frame():
    # 逆に「死と出た枠」は、使える枠が確定していれば読み直さない（救済の必要が無い）
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    candidates = [(False, "boardF", "regF"), (True, "boardT", "regT")]
    readers = {
        "boardF": _reader({400: (5.0, 9.5, 10), 1800: (5.0, 9.5, 10)}, calls),
        "boardT": _reader({400: (-9.0, -8.0, 10), 1800: (-9.0, -8.0, 10)}, calls),
    }
    verdicts = frame_validity_verdicts(candidates, lambda c, v: readers[c[1]](c, v), 400, 1800)
    assert [(v.ko_p, v.destroys, v.visits) for v in verdicts] == [(False, False, 400), (True, True, 400)]
    assert calls == [(False, 400), (True, 400)]


def test_frame_validity_verdicts_does_not_reread_what_it_cannot_measure():
    # 手番側の本体石が無い図（相手の石だけ）は 1子平均が計算できない。確認の読み直しは
    # 「閾値近傍かどうか」で決めるので、測れない枠に読み直しを課しても結論は変わらない
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    read = _reader({400: (5.0, 0.0, 0), 1800: (5.0, 0.0, 0)}, calls)
    verdicts = frame_validity_verdicts([(False, "board", "region")], read, 400, 1800)
    assert (verdicts[0].destroys, verdicts[0].visits) == (False, 400)
    assert calls == [(False, 400)]


def test_frame_validity_verdicts_skips_the_reread_when_it_would_not_be_deeper():
    # frame_validity_visits <= frame_ko_trial_visits（無効化を含む）なら読み直さず現行動作のまま
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    read = _reader({400: (-12.08, -10.72, 11)}, calls)
    verdicts = frame_validity_verdicts([(False, "board", "region")], read, 400, validity_visits=0)
    assert (verdicts[0].destroys, verdicts[0].visits) == (True, 400)
    assert calls == [(False, 400)]


def test_frame_validity_verdicts_keeps_dropping_genuinely_broken_frames():
    # case G の実測: 深く読んでも -0.98/子 のまま → 枠を捨てて枠なしで出題（正解 A11）
    from katrain.core.tsumego_frame import frame_validity_verdicts

    calls = []
    read = _reader({400: (-12.08, -10.72, 11), 1800: (-12.07, -10.78, 11)}, calls)
    verdicts = frame_validity_verdicts([(False, "board", "region")], read, 400, 1800)
    assert verdicts[0].destroys is True
    assert verdicts[0].ownership == pytest.approx(-10.78)


def _verdict(ko_p, ownership, stone_count, destroys=True, visits=1800):
    from katrain.core.tsumego_frame import FrameVerdict

    return FrameVerdict(ko_p, "board", "region", 0.0, destroys, visits, ownership, stone_count, [])


def test_frame_over_frameless_keeps_a_frame_that_beats_the_fallback():
    # case N の実測（手番側コア10子）: 枠 ko=False は 1800visits では +0.42/子 まで落ちる run が
    # あったが、枠なしは -0.75/子 で安定。閾値 0.5 を割った読みでも枠なしよりはるかに生きている
    # ので枠を使う（読み直しを wideRootNoise=0 にした現在は +0.96〜+0.98 で usable 側に安定する）
    from katrain.core.tsumego_frame import frame_over_frameless

    verdicts = [_verdict(False, 4.17, 10), _verdict(True, -9.87, 10)]
    assert frame_over_frameless(verdicts, -7.52, 10).ko_p is False


def test_frame_over_frameless_falls_back_when_the_frameless_board_is_healthier():
    # case F の実測（読み直し）: 枠 -0.72/-0.96 に対し枠なし -0.70 → 従来どおり枠なしで出題する
    # （case G も枠 -0.98/-0.99 に対し枠なし -0.68 で同じ結論）
    from katrain.core.tsumego_frame import frame_over_frameless

    verdicts = [_verdict(False, -7.92, 11), _verdict(True, -10.56, 11)]
    assert frame_over_frameless(verdicts, -7.70, 11) is None
    assert frame_over_frameless(verdicts, 11.0, 11) is None


def test_frame_over_frameless_needs_a_clear_margin_not_just_a_better_reading():
    # 1読みの run 間分散は 0.2〜0.5 あるので、僅差で勝っているだけの枠は残さない
    # （case F は枠と枠なしの差が -0.26〜-0.32 で、僅差なら run ごとに符号が入れ替わりうる）
    from katrain.core.tsumego_frame import frame_over_frameless

    verdicts = [_verdict(False, -0.65 * 11, 11)]
    assert frame_over_frameless(verdicts, -0.83 * 11, 11) is None  # 差 +0.18 では足りない
    assert frame_over_frameless(verdicts, -1.00 * 11, 11) is None  # 差 +0.35 でも足りない
    assert frame_over_frameless([_verdict(False, 0.10 * 11, 11)], -0.75 * 11, 11).ko_p is False  # 差 +0.85 は残す



def test_frame_over_frameless_needs_a_measurable_fallback():
    # 枠なしを読めなければ比較できない。従来動作（枠を捨てる）に落とす
    from katrain.core.tsumego_frame import frame_over_frameless

    assert frame_over_frameless([_verdict(False, 4.17, 10)], None, 10) is None
    assert frame_over_frameless([_verdict(False, None, 10)], -7.52, 10) is None
    assert frame_over_frameless([], -7.52, 10) is None


def test_solver_core_points_skips_wall_fill_and_dropped_stones():
    # 判定対象は「問題本体の手番側の石」だけ。枠の壁石は自明に生きているので混ぜると判定が
    # 埋もれる（実測 case D: 壁込みだと +25.00/25 で常に正常判定、本体だけなら +8.00/8）
    recognized = _board(stones=[(5, 5, "B"), (5, 6, "W"), (6, 6, "B")])
    framed = _board(
        stones=[
            (5, 5, "B"),  # 本体の手番側の石 → 対象
            (5, 6, "W"),  # 相手の石 → 対象外
            (4, 4, "B"),  # 壁（リージョン内だが認識盤に無い） → 対象外
            (11, 11, "B"),  # 枠外の充填 → 対象外
        ]
    )
    # (6,6) は認識されていたが drop_non_core で枠から落ちた石 → 対象外
    assert solver_core_points(recognized, framed, ((3, 7), (3, 7))) == [(5, 7)]


def test_solver_core_points_ignores_stones_outside_the_region():
    recognized = _board(stones=[(5, 5, "B"), (1, 1, "B")])
    framed = _board(stones=[(5, 5, "B"), (1, 1, "B")])
    assert solver_core_points(recognized, framed, ((3, 7), (3, 7))) == [(5, 7)]


def test_solver_core_points_without_region_covers_the_board():
    recognized = _board(stones=[(0, 0, "B"), (12, 12, "B")])
    framed = _board(stones=[(0, 0, "B"), (12, 12, "B")])
    assert solver_core_points(recognized, framed, None) == [(0, 12), (12, 0)]
