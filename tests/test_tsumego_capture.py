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
