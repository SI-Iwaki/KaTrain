import os
import subprocess
import sys

import pytest
from PIL import Image

from katrain.core.tsumego_capture import (
    CaptureError,
    classify_intersections,
    detect_board,
    detect_size_and_classify,
    grid_to_sgf,
)

SAMPLE = os.path.join(os.path.dirname(__file__), "data", "tsumego_app_sample.png")
SAMPLE_9X9 = os.path.join(os.path.dirname(__file__), "data", "tsumego_app_sample_9x9.png")
SAMPLE_SPARSE13 = os.path.join(os.path.dirname(__file__), "data", "tsumego_app_sample_sparse13.png")

EXPECTED_WHITE = {(0, 0), (0, 2), (0, 3), (1, 0), (1, 3), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3)}
EXPECTED_BLACK = {(1, 2), (1, 4), (2, 0), (2, 1), (2, 4), (3, 4), (4, 0), (4, 1), (4, 2), (4, 3), (4, 4)}

EXPECTED_BLACK_9X9 = {(5, j) for j in range(9)} | {(6, 2), (6, 6), (7, 2), (7, 6), (8, 4)}
EXPECTED_WHITE_9X9 = {(6, 0), (6, 1), (6, 4), (6, 7), (6, 8), (7, 1), (7, 7), (8, 0), (8, 2), (8, 3), (8, 5), (8, 6), (8, 8)}


def test_detect_board_returns_square_bbox():
    img = Image.open(SAMPLE)
    x0, y0, x1, y1 = detect_board(img)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    assert min(w, h) >= 300
    assert 0.9 < w / h < 1.1
    # 盤は画像の中央下寄り: bbox が画像内に収まっている
    assert 0 <= x0 < x1 < img.width
    assert 0 <= y0 < y1 < img.height


def test_detect_board_fails_without_board():
    img = Image.new("RGB", (800, 600), (20, 40, 120))  # 青一色
    with pytest.raises(CaptureError):
        detect_board(img)


def test_classify_sample_image():
    img = Image.open(SAMPLE)
    grid = classify_intersections(img, detect_board(img), 13)
    assert len(grid) == 13 and all(len(row) == 13 for row in grid)
    black = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "B"}
    white = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "W"}
    assert black == EXPECTED_BLACK
    assert white == EXPECTED_WHITE


def test_auto_size_13_sample():
    img = Image.open(SAMPLE)
    size, grid = detect_size_and_classify(img, detect_board(img))
    assert size == 13
    black = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "B"}
    assert black == EXPECTED_BLACK


def test_auto_size_9x9_sample():
    img = Image.open(SAMPLE_9X9)
    size, grid = detect_size_and_classify(img, detect_board(img))
    assert size == 9
    black = {(i, j) for i in range(9) for j in range(9) if grid[i][j] == "B"}
    white = {(i, j) for i in range(9) for j in range(9) if grid[i][j] == "W"}
    assert black == EXPECTED_BLACK_9X9
    assert white == EXPECTED_WHITE_9X9


def test_auto_size_sparse13_sample():
    # 石が少ない13路盤の9路誤認識の回帰テスト: サンプル点が偶然境界を踏まないと
    # 曖昧エラーが出ず9路として誤成立するため、格子線検出でサイズを判定すること
    img = Image.open(SAMPLE_SPARSE13)
    size, grid = detect_size_and_classify(img, detect_board(img))
    assert size == 13
    black = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "B"}
    white = {(i, j) for i in range(13) for j in range(13) if grid[i][j] == "W"}
    assert black == {(1, 11), (2, 10), (3, 10), (3, 11)}
    assert white == {(1, 9), (2, 7), (2, 9), (3, 9), (4, 10), (4, 11), (5, 10)}


def test_cross_size_rejection():
    # 誤ったサイズでのサンプリングは曖昧エラーで拒否される（自動サイズ判定の前提）
    img13 = Image.open(SAMPLE)
    rect13 = detect_board(img13)
    img9 = Image.open(SAMPLE_9X9)
    rect9 = detect_board(img9)
    for wrong_size in (9, 19):
        with pytest.raises(CaptureError):
            classify_intersections(img13, rect13, wrong_size)
    for wrong_size in (13, 19):
        with pytest.raises(CaptureError):
            classify_intersections(img9, rect9, wrong_size)


def _empty_grid(size=13):
    return [["." for _ in range(size)] for _ in range(size)]


def test_grid_to_sgf():
    grid = _empty_grid()
    grid[0][1] = "B"  # i=0(上端行), j=1(左から2列目) → SGF座標 "ba"（列j→1文字目, 行i→2文字目）
    grid[12][12] = "W"  # 右下隅 → "mm"
    sgf = grid_to_sgf(grid, komi=6.5)
    assert sgf == "(;GM[1]FF[4]CA[UTF-8]SZ[13]KM[6.5]PL[B]AB[ba]AW[mm])"


def test_grid_to_sgf_empty_board_raises():
    with pytest.raises(CaptureError):
        grid_to_sgf(_empty_grid())


def test_grid_to_sgf_parses_in_katrain():
    # KaTrain 本体のパーサで読めて黒番になることを保証する結合テスト
    from katrain.core.sgf_parser import SGF

    grid = _empty_grid()
    grid[2][3] = "B"
    grid[5][6] = "W"
    root = SGF.parse_sgf(grid_to_sgf(grid))
    assert root.get_property("SZ") == "13"
    assert root.initial_player == "B"
    assert root.get_list_property("AB") == ["dc"]
    assert root.get_list_property("AW") == ["gf"]


def _fake_analysis(moves_visits):
    return {
        "moveInfos": [
            {"move": gtp, "visits": v, "order": i, "scoreLead": 0.0, "winrate": 0.5, "pv": [gtp]}
            for i, (gtp, v) in enumerate(moves_visits)
        ],
        "rootInfo": {"visits": sum(v for _, v in moves_visits), "winrate": 0.5, "scoreLead": 0.0},
    }


def test_region_analysis_prunes_outside_moves():
    # 全盤fast解析→リージョン限定解析の2段構えで、枠外の候補手が残らないこと
    # （詰碁キャプチャで枠外の手が最善手として表示される不具合の回帰テスト）
    from katrain.core.game_node import GameNode

    node = GameNode(properties={"SZ": "13"})
    node.set_analysis(_fake_analysis([("B4", 38), ("A12", 20)]))  # 全盤fast: 枠外B4が最善
    assert "B4" in node.analysis["moves"]
    # リージョン x=0..10, y=4..12（B4 は y=3 で枠外、A12/B11 は枠内）
    node.set_analysis(_fake_analysis([("A12", 335), ("B11", 342)]), region_of_interest=[0, 10, 4, 12])
    assert "B4" not in node.analysis["moves"]
    assert set(node.analysis["moves"]) == {"A12", "B11"}


def test_late_fullboard_result_does_not_pollute_region_analysis():
    # 回帰テスト: 2段解析の全盤fastクエリの最終結果がリージョン限定クエリの最終結果より
    # 後に届くと（並列探索でまれに逆転）、既存候補を全降格して浅い全盤順位を上書きし、
    # 「値はリージョン解析・順位は全盤fast」の汚染状態でAIが次善手を打っていた。
    # リージョン確定後の全盤解析は moves を汚染させず、root（勝率）更新のみ許可する
    from katrain.core.game_node import GameNode

    node = GameNode(properties={"SZ": "13"})
    node.set_analysis(_fake_analysis([("B4", 38), ("A12", 20)]))  # 全盤fast（先着）
    node.set_analysis(_fake_analysis([("A12", 813), ("B11", 673)]), region_of_interest=[0, 10, 4, 12])
    # 全盤fastの最終結果が遅れて再着（もしくは順序逆転で後着）
    node.set_analysis(_fake_analysis([("B4", 38), ("A12", 20)]))
    assert "B4" not in node.analysis["moves"]  # 枠外候補が再注入されない
    assert node.candidate_moves[0]["move"] == "A12"  # リージョン解析の順位が維持される
    assert node.analysis["root"]["visits"] == 58  # root（勝率表示用）は全盤解析で更新されてよい


def test_region_flags_cleared_on_clear():
    # リージョン解除後は全盤解析を再び受け付ける（clear_region_flags でフラグを戻す）
    from katrain.core.game_node import GameNode

    node = GameNode(properties={"SZ": "13"})
    node.set_analysis(_fake_analysis([("A12", 335), ("B11", 342)]), region_of_interest=[0, 10, 4, 12])
    assert node.analysis.get("region_completed")
    node.clear_region_flags()
    assert not node.analysis.get("region_completed")
    assert not node.analysis.get("region_requested")
    node.set_analysis(_fake_analysis([("B4", 38), ("A12", 20)]))  # 全盤解析が通常どおり反映される
    assert "B4" in node.analysis["moves"]


def test_analyze_passes_deep_region_settings():
    # 詰碁のリージョン解析はvisits指定・時間無制限・wideRootNoise=0の専用クエリを使えること
    # （既定の1500visits・8秒上限・ノイズ0.04では難しい詰碁で正解手を外すため）
    from katrain.core.game_node import GameNode

    class FakeEngine:
        def request_analysis(self, node, **kwargs):
            self.requested = kwargs

    node = GameNode(properties={"SZ": "13"})
    engine = FakeEngine()
    node.analyze(
        engine,
        region_of_interest=[0, 10, 4, 12],
        visits=4000,
        time_limit=False,
        extra_settings={"wideRootNoise": 0.0},
    )
    assert engine.requested["visits"] == 4000
    assert engine.requested["time_limit"] is False
    assert engine.requested["extra_settings"] == {"wideRootNoise": 0.0}


def test_region_analysis_extra_settings():
    # 深掘り指定があるときだけ wideRootNoise を上書きし、無ければ既定解析（engine 設定）に委ねる。
    # 0 にすると root の探索が1手に集中し正解手が切り捨てられるため既定は 0.04
    # （実測 2026-07-29: wRN 0 は 8 trial 中 3 回しか正解手を発見できず、0.04 で 7/8）
    from katrain.core.game import REGION_ANALYSIS_WIDE_ROOT_NOISE, region_analysis_extra_settings

    assert REGION_ANALYSIS_WIDE_ROOT_NOISE == 0.04
    assert region_analysis_extra_settings(1800, 0.04) == {"wideRootNoise": 0.04}
    assert region_analysis_extra_settings(None, 0.04) is None


def test_analyze_passes_ownership_flag():
    # ownership は詰碁のリージョン解析でだけ要る。エンジン設定 _enable_ownership を全体で有効に
    # すると通常の対局・検討の全クエリに includeMovesOwnership（候補手ごとに盤面全点）が
    # 乗ってしまうため、クエリ単位で指定できるようにする
    from katrain.core.game_node import GameNode

    class FakeEngine:
        def request_analysis(self, node, **kwargs):
            self.requested = kwargs

    node = GameNode(properties={"SZ": "13"})
    engine = FakeEngine()
    node.analyze(engine, region_of_interest=[0, 10, 4, 12], ownership=True)
    assert engine.requested["ownership"] is True


def test_analyze_defaults_ownership_to_none():
    # 指定しなければ None を渡し、engine 側の既定（_enable_ownership）に委ねる
    from katrain.core.game_node import GameNode

    class FakeEngine:
        def request_analysis(self, node, **kwargs):
            self.requested = kwargs

    node = GameNode(properties={"SZ": "13"})
    engine = FakeEngine()
    node.analyze(engine)
    assert engine.requested["ownership"] is None


def test_cli_image_mode():
    result = subprocess.run(
        [sys.executable, "-m", "katrain.core.tsumego_capture", "--image", SAMPLE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "SZ[13]" in result.stdout
    assert "PL[B]" in result.stdout
    # ASCII盤面が13行出力される
    board_lines = [ln for ln in result.stdout.splitlines() if ln and all(c in "BW. " for c in ln)]
    assert len(board_lines) == 13


def test_region_completed_flag_gates_fast_analysis():
    # AI自動着手ゲートの回帰テスト: 全盤fast解析の完了時点では region_completed は立たず、
    # リージョン限定解析の最終結果で立つ（これがないとAIが刈り取り前の枠外・浅読み候補を打つ）
    from katrain.core.game_node import GameNode

    node = GameNode(properties={"SZ": "13"})
    node.set_analysis(_fake_analysis([("B4", 38)]))  # 全盤fast: region指定なし
    assert node.analysis_complete
    assert not node.analysis.get("region_completed")
    # 部分結果（ストリーミング途中）でも立たない
    node.set_analysis(_fake_analysis([("A12", 100)]), region_of_interest=[0, 10, 4, 12], partial_result=True)
    assert not node.analysis.get("region_completed")
    # リージョン限定解析の最終結果で立つ
    node.set_analysis(_fake_analysis([("A12", 335)]), region_of_interest=[0, 10, 4, 12])
    assert node.analysis.get("region_completed")


def test_analyze_marks_region_requested():
    # update_state 側の自己回復（未発行なら一度だけ発行）が二重発行しないためのフラグ
    from katrain.core.game_node import GameNode

    class FakeEngine:
        def request_analysis(self, node, **kwargs):
            self.requested = kwargs

    node = GameNode(properties={"SZ": "13"})
    engine = FakeEngine()
    assert not node.analysis.get("region_requested")
    node.analyze(engine, region_of_interest=[0, 10, 4, 12])
    assert node.analysis.get("region_requested")
    assert engine.requested["region_of_interest"] == [0, 10, 4, 12]


def test_capture_tsumego_grid_returns_recognized_grid(monkeypatch):
    # キャプチャ経路は枠適用にグリッドが必要なので、認識までを返す関数に置き換える
    # （SGF文字列を経由すると枠適用前に局面が確定してしまい、非コア石を除去できない）
    from katrain.core import tsumego_capture as tc

    grid = [["." for _ in range(9)] for _ in range(9)]
    grid[4][4] = "B"
    monkeypatch.setattr(tc, "find_window_rect", lambda _t: (0, 0, 100, 100))
    monkeypatch.setattr(tc, "capture_screen_rect", lambda _r: None)
    monkeypatch.setattr(tc, "detect_board", lambda _i: (0, 0, 99, 99))
    monkeypatch.setattr(tc, "detect_size_and_classify", lambda _i, _r, _s: (9, grid))

    assert tc.capture_tsumego_grid({"window_title": "X"}) == grid


def test_framed_grid_round_trips_through_sgf():
    # キャプチャ経路: 認識グリッド → 枠適用 → 完成グリッド → 単一AB/AWのSGF → KaTrainで読める
    # （占有点への重複配置がないことを、実際にゲームを構築して確認する）
    from katrain.core.game import BaseGame, KaTrainSGF
    from katrain.core.tsumego_frame import tsumego_frame_board

    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    grid = [["." for _ in range(13)] for _ in range(13)]
    for p in ab:
        grid[ord(p[1]) - 97][ord(p[0]) - 97] = "B"
    for p in aw:
        grid[ord(p[1]) - 97][ord(p[0]) - 97] = "W"

    framed, region = tsumego_frame_board(grid, 7.0, True, False, 4)
    assert region == ((0, 10), (5, 12))

    class _Stub:
        def log(self, *_a, **_k):
            pass

        def config(self, *_a, **_k):
            return None

    root = KaTrainSGF.parse_sgf(grid_to_sgf(framed, komi=7.0))
    game = BaseGame(_Stub(), move_tree=root)  # 重複配置があればここで例外
    expected = sum(1 for row in framed for v in row if v in ("B", "W"))
    assert len(game.stones) == expected


def test_frameless_grid_round_trips_through_sgf_exactly():
    # 枠なしモード（既定）: 認識グリッドを一切書き換えずそのままSGF化するので、KaTrainで
    # 読み込んだ後の石が認識グリッドと完全一致すること（増減も変色もない）。
    # 枠モードの test_framed_grid_round_trips_through_sgf に対応する枠なし版
    from katrain.core.game import BaseGame, KaTrainSGF

    size = 13
    grid = [["." for _ in range(size)] for _ in range(size)]
    expected = {}
    for i, j, c in [
        (4, 2, "B"), (4, 3, "B"), (5, 3, "B"), (6, 4, "B"),  # 詰碁本体（黒）
        (5, 8, "W"), (5, 9, "W"), (6, 9, "W"),  # 詰碁本体（白）
        (0, 0, "W"),  # 本体から離れたお邪魔石
    ]:
        grid[i][j] = c
        expected[(i, j)] = c

    class _Stub:
        def log(self, *_a, **_k):
            pass

        def config(self, *_a, **_k):
            return None

    root = KaTrainSGF.parse_sgf(grid_to_sgf(grid, komi=7.0))
    game = BaseGame(_Stub(), move_tree=root)  # 重複配置があればここで例外

    # game.stones の座標系は下origin(y = size-1-i)。認識グリッドと同じ上origin(i,j)に戻して比較
    actual = {}
    for s in game.stones:
        x, y = s.coords
        actual[(size - 1 - y, x)] = s.player

    assert actual == expected, f"石が一致しない: expected={expected} actual={actual}"
    assert len(game.stones) == len(expected)


def test_capture_region_brackets_stones_in_move_coords():
    # 回帰テスト: tsumego_frame_board が返す region は認識グリッド
    # （tsumego_capture.classify_intersections）準拠の上origin i（画面上でcyが下に
    # 増える向きに合わせて上から数えた行）。一方 KaTrain の Move.coords / BaseGame.stones
    # の y は下origin（sgf_parser.Move.from_sgf: y = board_size - sgf_row_index - 1 と同じ）。
    # この変換を怠ると縦方向が反転したリージョンになり、詰碁本体の一部がリージョン外に
    # 落ちる（katrain/__main__.py の _apply_tsumego_region で実際に発生していたバグ）。
    # __main__.py は Kivy 依存でここから import できないため、本番と同じ変換式
    # （y = board_size - 1 - i）だけをここに複製する。本番側を変更したらここも同期すること。
    from katrain.core.game import BaseGame, KaTrainSGF
    from katrain.core.tsumego_frame import tsumego_frame_board

    # test_framed_grid_round_trips_through_sgf と同じ13路の再現フィクスチャ
    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    size = 13
    grid = [["." for _ in range(size)] for _ in range(size)]
    original = {}  # (i, j) [認識グリッド=上origin] -> 元の色
    for p in ab:
        i, j = ord(p[1]) - 97, ord(p[0]) - 97
        grid[i][j] = "B"
        original[(i, j)] = "B"
    for p in aw:
        i, j = ord(p[1]) - 97, ord(p[0]) - 97
        grid[i][j] = "W"
        original[(i, j)] = "W"

    komi = 7.0
    framed, region = tsumego_frame_board(grid, komi, True, False, 4)
    assert region == ((0, 10), (5, 12))  # test_framed_grid_round_trips_through_sgf と同じ既知値

    class _Stub:
        def log(self, *_a, **_k):
            pass

        def config(self, *_a, **_k):
            return None

    root = KaTrainSGF.parse_sgf(grid_to_sgf(framed, komi=komi))
    game = BaseGame(_Stub(), move_tree=root)
    stone_coords = {s.coords for s in game.stones}

    # 本番の変換（katrain/__main__.py: _apply_tsumego_region 参照）
    (imin, imax), (jmin, jmax) = region
    xmin, xmax = jmin, jmax
    ymin, ymax = size - 1 - imax, size - 1 - imin  # 上origin i → 下origin y

    # drop_non_core で消去/壁色に上書きされた石は「元の詰碁石」として盤上に残っていない
    # ので対象から除く。それ以外（大半）は元の色のまま盤上に残っているはず
    survived = [(i, j) for (i, j), color in original.items() if framed[i][j] == color]
    assert len(survived) >= 20, "生存石が少なすぎる（枠適用が退化していないかの前提チェック）"

    for i, j in survived:
        x, y = j, size - 1 - i  # Move.coords への変換（sgf_parser.Move.from_sgf と同じ式）
        assert (x, y) in stone_coords, f"石 (i={i},j={j}) が game.stones に見つからない"
        assert xmin <= x <= xmax and ymin <= y <= ymax, (
            f"石 (i={i},j={j}) → Move({x},{y}) がリージョン外: x[{xmin},{xmax}] y[{ymin},{ymax}]"
        )


def test_solver_mode_analysis_region_is_the_frameless_one_not_the_problem_bbox():
    """ソルバモードの解析リージョンは抽出 region の外接矩形にしない（case AF）。

    実測 2026-08-05 の GUI 誤答（13路左上・ログ tsumego_20260805_002009）。抽出は
    アタリの黒 {A11,A12,A13}（白ターゲットと石でしか接しておらず閉包に現れない）を
    黙って境界に使い、`region=18点`＝**A列が丸ごと外**の別問題を返した。ソルバは自前の
    problem.region で解くのでこの矩形を必要としないが、KataGo 側（フォールバックの
    ai:tsumego と、セッション再抽出の hint）はこれに縛られるため、白 A10 で戦いが箱の外へ
    出たあと、正解 A12 が候補にすら入らず F10（pointsLost +19.53）になった。

    generate_move_e2e 実測（同一局面・3run）: 抽出 bbox(25点) → **F10 3/3**（GUI の誤答
    そのもの）／枠なし経路と同じリージョン(63点) → **A12 3/3**（記録された正解手）。

    __main__.py は Kivy 依存でここから import できないため、本番と同じ選び方
    （`_tsumego_frameless_board` → `frameless_region(grid, region_pad)`）と同じ変換式
    （y = board_size - 1 - i）だけをここに複製する。本番側を変更したらここも同期すること。
    """
    from katrain.core.tsumego_frame import frameless_region
    from katrain.core.tsumego_problem import extract_problem

    size = 13
    cols = "ABCDEFGHJKLMN"

    def to_ij(gtp):  # 認識グリッドの (i=上origin行, j=列)
        return size - int(gtp[1:]), cols.index(gtp[0])

    b_stones = "A11 A12 A13 B10 B9 C8 C9 D13 D8 E10 E8 F11 F9 G11 G12 G13 G9 H10".split()
    w_stones = "B11 B12 B13 C10 D10 D9 E11 E12 E9 F12 F13".split()
    grid = [["." for _ in range(size)] for _ in range(size)]
    for gtp in b_stones:
        i, j = to_ij(gtp)
        grid[i][j] = "B"
    for gtp in w_stones:
        i, j = to_ij(gtp)
        grid[i][j] = "W"

    problem = extract_problem(grid=grid, to_play="B")
    # 旧実装が使っていた「抽出 region の外接矩形」。正解手 A12 を含まない
    xs = [p[0] for p in problem.region]
    ys = [p[1] for p in problem.region]
    old = (min(xs), max(xs), min(ys), max(ys))

    region = frameless_region(grid, 1)  # 本番の region_pad 既定値
    assert region is not None, "枠なし経路のリージョンが全盤に退化している（前提チェック）"
    (imin, imax), (jmin, jmax) = region
    new = (jmin, jmax, size - 1 - imax, size - 1 - imin)  # __main__._apply_tsumego_region と同じ変換

    ax, ay = cols.index("A"), 12 - 1  # A12 の Move.coords（y は下origin: 行12 → y=11）
    assert not (old[0] <= ax <= old[1] and old[2] <= ay <= old[3]), "前提: 旧リージョンは A12 を含まない"
    assert new[0] <= ax <= new[1] and new[2] <= ay <= new[3], (
        f"ソルバモードの解析リージョンが正解手 A12 を含んでいない: x[{new[0]},{new[1]}] y[{new[2]},{new[3]}]"
    )


# ---- 枠なしキャプチャ（ホットキー指定・case AG） ----------------------------------


def test_frame_mode_settings_untouched_when_not_frameless():
    """枠なし指定が無いキャプチャは設定オブジェクトをそのまま返す（既存経路を一切変えない）"""
    from katrain.core.tsumego_capture import capture_settings_for_frame_mode

    settings = {"use_frame": True, "region_pad": 1, "noframe_region_pad": 3}
    assert capture_settings_for_frame_mode(settings, False) is settings


@pytest.mark.parametrize(
    "settings,expected_pad",
    [
        ({"use_frame": True, "region_pad": 1}, 3),  # 既定
        ({"use_frame": True, "region_pad": 1, "noframe_region_pad": 2}, 2),
        ({"use_frame": True, "region_pad": 1, "noframe_region_pad": "x"}, 3),  # 壊れた値は既定へ
        ({"use_frame": True, "region_pad": 1, "noframe_region_pad": -5}, 0),  # 負値はクランプ
    ],
)
def test_frame_mode_settings_disables_frame_and_widens_region(settings, expected_pad):
    """枠なし指定のキャプチャは use_frame を落とし、リージョンを noframe_region_pad で取る"""
    from katrain.core.tsumego_capture import capture_settings_for_frame_mode

    applied = capture_settings_for_frame_mode(settings, True)
    assert applied is not settings, "元の設定 dict を破壊してはいけない"
    assert applied["use_frame"] is False
    assert applied["region_pad"] == expected_pad
    assert settings.get("region_pad") == 1, "呼び出し側の設定が書き換わっている"


def test_frameless_capture_reaches_answer_outside_the_frame_wall():
    """枠の壁が正解手順を切る盤で、枠なしキャプチャなら正解手 M4 が打てる（case AG）。

    実測 2026-08-05（13路・ログ tsumego_20260805_015813）。認識石の bbox は 8行×7列で、
    `fit_margin` は「枠外に守り側の代償地帯 (169-7-5)/2 = 78.5 点」を確保できる最大の
    margin を返すため 4 → **2** に縮む（margin 3 は枠外 59 点で不足）。結果、壁は
    認識石のわずか2線外＝row 4 に来る。この問題の正解手順は白が L8→M7→M6→L5 と下辺へ
    走るので、次の白 **M4 が黒の壁石**になり打てない。

    枠を広げる方向では直せない（枠の内側は設計上「盤の約半分」が上限）。また「対象が
    囲われていない」シグナルは実測30キャプチャ中25件で発火し、自動で枠を切り替えると
    正常な問題まで枠なしに落ちる。よって枠なしはユーザーの明示指定（ホットキー）とし、
    そのときのリージョンは `noframe_region_pad`(3) で取って黒も壁の外まで追えるようにする。
    """
    from katrain.core.tsumego_capture import capture_settings_for_frame_mode
    from katrain.core.tsumego_frame import frameless_region, tsumego_frame_board

    size = 13
    cols = "ABCDEFGHJKLMN"

    def to_ij(gtp):
        return size - int(gtp[1:]), cols.index(gtp[0])

    b_stones = "G12 G8 H10 H11 H7 H9 J12 J13 J6 J9 K7 L7 L9 M8 N8".split()
    w_stones = "J10 J11 J8 K12 K8 K9 M10 M12".split()
    grid = [["." for _ in range(size)] for _ in range(size)]
    for gtp in b_stones:
        i, j = to_ij(gtp)
        grid[i][j] = "B"
    for gtp in w_stones:
        i, j = to_ij(gtp)
        grid[i][j] = "W"

    mi, mj = to_ij("M4")
    framed, _region = tsumego_frame_board(grid, 7.0, True, False, 4, drop_non_core=True, black_to_attack_p=True)
    assert grid[mi][mj] == ".", "前提: 認識盤では M4 は空点"
    assert framed[mi][mj] == "B", "前提: 枠ありでは M4 が黒の壁石になる（これが打てない原因）"

    pad = capture_settings_for_frame_mode({"use_frame": True, "region_pad": 1}, True)["region_pad"]
    region = frameless_region(grid, pad)
    assert region is not None, "枠なしのリージョンが全盤に退化している"
    (imin, imax), (jmin, jmax) = region
    assert imin <= mi <= imax and jmin <= mj <= jmax, (
        f"枠なしキャプチャの解析リージョンが M4 を含んでいない: i[{imin},{imax}] j[{jmin},{jmax}]"
    )


# ============================================================
# Web 盤面認識（格子線＋座標ラベル方式）の回帰テスト
# 実スクリーンショット2枚（PlayGo.gg）での実測検証は
# docs/superpowers/specs/calibration-data/tsumego-web/ を参照。ここでは合成盤で
# 「全体表示→web_full」「部分表示→web_partial＋絶対座標復元」「従来盤→app 経路不変」を固定する
# ============================================================


def _draw_web_board(visible_rows, visible_cols, size, stones, label_sides, cell=48):
    """Web サイト風の盤面画像を合成する。visible_rows は上から下へ降順（例 [9,8,...,2]）、
    visible_cols は左から右へ昇順の列番号（1=A）。label_sides の辺に 1 セル幅のラベル帯を作り、
    座標ラベルは埋め込みグリフテンプレート自身を 1:1 で描画する（フォント再現不要でOCRを回帰できる）"""
    from PIL import ImageDraw

    from katrain.core.tsumego_capture import COL_LETTERS
    from katrain.core.tsumego_capture_glyphs import GLYPH_TEMPLATES

    yellow, line_col, glyph_col = (229, 195, 109), (100, 88, 60), (51, 51, 51)
    n_r, n_c = len(visible_rows), len(visible_cols)
    margin = {s: cell if s in label_sides else int(cell * 0.3) for s in ("left", "right", "top", "bottom")}
    bw = margin["left"] + (n_c - 1) * cell + margin["right"]
    bh = margin["top"] + (n_r - 1) * cell + margin["bottom"]
    pad = 60
    img = Image.new("RGB", (bw + 2 * pad, bh + 2 * pad), (25, 25, 25))
    draw = ImageDraw.Draw(img)
    bx, by = pad, pad
    draw.rectangle((bx, by, bx + bw - 1, by + bh - 1), fill=yellow)
    xs = [bx + margin["left"] + k * cell for k in range(n_c)]
    ys = [by + margin["top"] + k * cell for k in range(n_r)]
    # 格子線: 見えている端（ラベルあり）は最外線で止め、切れている端は盤領域の縁まで伸ばす
    x_lo = xs[0] if "left" in label_sides else bx
    x_hi = xs[-1] if "right" in label_sides else bx + bw - 1
    y_lo = ys[0] if "top" in label_sides else by
    y_hi = ys[-1] if "bottom" in label_sides else by + bh - 1
    for x in xs:
        draw.rectangle((x, y_lo, x + 1, y_hi), fill=line_col)
    for y in ys:
        draw.rectangle((x_lo, y, x_hi, y + 1), fill=line_col)

    def draw_glyphs(text, cx, cy):
        w_total = len(text) * 10 + (len(text) - 1) * 2
        gx = int(cx - w_total / 2)
        gy = int(cy - 7)
        for ch in text:
            bmp = GLYPH_TEMPLATES[ch][0].split("/")
            for r, row in enumerate(bmp):
                for c, v in enumerate(row):
                    if v == "#":
                        img.putpixel((gx + c, gy + r), glyph_col)
            gx += 12

    # ラベルは実サイト同様に外縁寄りへ描く（帯の内側境界=最外線から0.55セルの内側だと
    # 境界接触フィルタに落ちる）
    for side in label_sides:
        if side in ("left", "right"):
            cx = bx + margin["left"] // 4 if side == "left" else bx + bw - margin["right"] // 4
            for y, row in zip(ys, visible_rows):
                draw_glyphs(str(row), cx, y)
        else:
            cy = by + margin["top"] // 4 if side == "top" else by + bh - margin["bottom"] // 4
            for x, col in zip(xs, visible_cols):
                draw_glyphs(COL_LETTERS[col - 1], x, cy)
    rad = int(cell * 0.45)
    for (row, col), color in stones.items():
        i, j = visible_rows.index(row), visible_cols.index(col)
        fill = (45, 45, 45) if color == "B" else (242, 242, 242)
        draw.ellipse((xs[j] - rad, ys[i] - rad, xs[j] + rad, ys[i] + rad), fill=fill)
    return img


def test_web_full_view_recognized_as_fullboard():
    from katrain.core.tsumego_capture import recognize_board

    stones = {(9, 3): "W", (8, 4): "B", (5, 5): "B", (1, 9): "W"}
    img = _draw_web_board(list(range(9, 0, -1)), list(range(1, 10)), 9, stones,
                          label_sides=("left", "right", "top", "bottom"))
    view = recognize_board(img)
    assert view.kind == "web_full"
    assert view.cropped_sides == ()
    assert not view.size_fallback
    assert len(view.grid) == 9
    assert view.grid[0][2] == "W"  # C9
    assert view.grid[1][3] == "B"  # D8
    assert view.grid[4][4] == "B"  # E5
    assert view.grid[8][8] == "W"  # J1
    assert sum(v != "." for row in view.grid for v in row) == 4


def test_web_partial_view_maps_absolute_coordinates():
    # 実スクショ1（PlayGo 9路ボス問題）と同じ構図: 上端・左端だけ見えていて右端(J列)と下端(1の線)が
    # 画面外。盤サイズは最上行のラベル「9」から確定し、石は 9x9 の絶対座標に配置される
    from katrain.core.tsumego_capture import recognize_board

    stones = {(9, 6): "B", (8, 4): "B", (8, 6): "B", (9, 3): "W", (8, 3): "W", (8, 5): "W"}
    img = _draw_web_board(list(range(9, 1, -1)), list(range(1, 9)), 9, stones, label_sides=("left", "top"))
    view = recognize_board(img)
    assert view.kind == "web_partial"
    assert set(view.cropped_sides) == {"right", "bottom"}
    assert not view.size_fallback
    assert len(view.grid) == 9
    assert view.grid[0][5] == "B"  # F9
    assert view.grid[1][3] == "B"  # D8
    assert view.grid[0][2] == "W"  # C9
    assert view.grid[1][4] == "W"  # E8
    assert all(v == "." for v in view.grid[8])  # 画面外の 1 の線は空点のまま
    assert all(row[8] == "." for row in view.grid)  # 画面外の J 列も空点のまま


def test_app_sample_still_uses_app_path():
    # BlueStacks 型の全面盤は従来方式が先に成立するので Web 認識に入らない（既存経路の不変性）
    from katrain.core.tsumego_capture import recognize_board

    view = recognize_board(Image.open(SAMPLE))
    assert view.kind == "app"
    assert len(view.grid) == 13


def test_find_window_rect_multi_title_prefers_first():
    # カンマ区切りの window_title は先に書いた候補を優先する（BlueStacks 優先の従来挙動を保つ）
    import katrain.core.tsumego_capture as tc

    assert [t.strip() for t in "BlueStacks,Puzzle Run,PlayGo".split(",")][0] == "BlueStacks"
