"""tsumego_answer_book のユニットテスト（KataGo/Kivy/humanSL モデル不要）。"""

from types import SimpleNamespace

import pytest

from katrain.core.ai import tsumego_book_next_move, tsumego_book_status
from katrain.core.tsumego_answer_book import (
    AnswerBook,
    canonicalize,
    frame_added_points,
    gtp_to_point,
    line_frame_collisions,
    inverse_transform,
    line_status,
    moves_to_canonical,
    next_move,
    point_to_gtp,
    should_record_line,
    transform_point,
)

# ユーザー提供の13路実問題（左下）。座標は (x, y)・y は下origin
REF_BLACK = {(0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (4, 3), (2, 2), (4, 2), (1, 1), (4, 1), (4, 0)}
REF_WHITE = {(1, 3), (2, 3), (3, 3), (1, 2), (3, 2), (3, 1), (3, 0)}
REF_LINE = [(0, 3), (0, 1), (1, 0), (0, 2), (2, 1)]  # B W B W B
SIZE = 13


def _transform_set(points, t, size):
    return {transform_point(p, t, size) for p in points}


class TestTransforms:
    def test_identity(self):
        assert transform_point((3, 7), 0, SIZE) == (3, 7)

    def test_rotate_180_hand_computed(self):
        # t=2 は180度回転: (x, y) -> (12-x, 12-y)
        assert transform_point((0, 4), 2, SIZE) == (12, 8)
        assert transform_point((12, 12), 2, SIZE) == (0, 0)

    def test_mirror_hand_computed(self):
        # t=4 は x 反転のみ
        assert transform_point((0, 4), 4, SIZE) == (12, 4)

    def test_all_transforms_roundtrip(self):
        probes = [(0, 0), (1, 2), (5, 5), (12, 0), (3, 11)]
        for t in range(8):
            inv = inverse_transform(t)
            for p in probes:
                assert transform_point(transform_point(p, t, SIZE), inv, SIZE) == p

    def test_transforms_are_permutations(self):
        # 各変換は盤上の全点の置換（重複なし・盤内に収まる）
        all_points = [(x, y) for x in range(SIZE) for y in range(SIZE)]
        for t in range(8):
            images = {transform_point(p, t, SIZE) for p in all_points}
            assert len(images) == SIZE * SIZE
            assert all(0 <= x < SIZE and 0 <= y < SIZE for x, y in images)


class TestGtp:
    def test_roundtrip(self):
        for p in [(0, 0), (8, 12), (12, 0), None]:
            assert gtp_to_point(point_to_gtp(p)) == p

    def test_skips_i_column(self):
        assert point_to_gtp((8, 0)) == "J1"  # 8列目は I を飛ばして J

    def test_pass(self):
        assert point_to_gtp(None) == "pass"
        assert gtp_to_point("pass") is None


class TestCanonicalize:
    def test_same_key_for_all_8_orientations(self):
        base_key, _ = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        for t in range(1, 8):
            key, _ = canonicalize(_transform_set(REF_BLACK, t, SIZE), _transform_set(REF_WHITE, t, SIZE), SIZE, "B")
            assert key == base_key, f"transform {t} gave different key"

    def test_different_problem_different_key(self):
        key1, _ = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        key2, _ = canonicalize(REF_BLACK | {(6, 6)}, REF_WHITE, SIZE, "B")
        assert key1 != key2

    def test_to_play_and_size_in_key(self):
        key_b, _ = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        key_w, _ = canonicalize(REF_BLACK, REF_WHITE, SIZE, "W")
        assert key_b != key_w

    def test_asymmetric_problem_single_transform(self):
        _, transforms = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        assert len(transforms) == 1

    def test_symmetric_problem_multiple_transforms(self):
        # 対角線対称の配置は複数の変換がタイになる
        black = {(0, 0), (2, 2)}
        white = {(1, 0), (0, 1)}
        _, transforms = canonicalize(black, white, 9, "B")
        assert len(transforms) >= 2

    def test_transforms_map_board_to_canonical(self):
        # 別の向きに置いた盤も、有効変換で写すと同じ標準形になること
        key, transforms = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        rot_black = _transform_set(REF_BLACK, 3, SIZE)
        rot_white = _transform_set(REF_WHITE, 3, SIZE)
        key2, transforms2 = canonicalize(rot_black, rot_white, SIZE, "B")
        assert key2 == key
        t = transforms2[0]
        assert _transform_set(rot_black, t, SIZE) == _transform_set(REF_BLACK, transforms[0], SIZE)


def _entry_for(black, white, line_moves, size):
    """Test helper: convert moves in board orientation to canonical and store in entry."""
    key, transforms = canonicalize(black, white, size, "B")
    players = ["B", "W"] * ((len(line_moves) + 1) // 2)
    moves = list(zip(line_moves, players))
    line = moves_to_canonical(moves, transforms[0], size)
    return key, transforms, {"lines": [line]}


class TestNextMove:
    def test_first_move_and_full_line(self):
        key, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = []
        for expect in [REF_LINE[0], REF_LINE[2], REF_LINE[4]]:  # Black moves only
            found, coords = next_move(entry, transforms, played, SIZE)
            assert found and coords == expect
            played.append((coords, "B"))
            i = len(played)
            if i < len(REF_LINE):
                played.append((REF_LINE[i], "W"))  # White plays recorded response

    def test_white_deviation_misses(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = [(REF_LINE[0], "B"), ((6, 6), "W")]  # White deviates
        found, coords = next_move(entry, transforms, played, SIZE)
        assert not found and coords is None

    def test_line_exhausted_misses(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        players = ["B", "W"] * 3
        played = list(zip(REF_LINE, players))
        found, _ = next_move(entry, transforms, played, SIZE)
        assert not found

    def test_multiple_lines_branch(self):
        # Entry with alt branch: white plays (0,2) instead of (0,1)
        key, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        alt_moves = [(REF_LINE[0], "B"), ((0, 2), "W"), ((2, 1), "B")]
        entry["lines"].append(moves_to_canonical(alt_moves, transforms[0], SIZE))
        played = [(REF_LINE[0], "B"), ((0, 2), "W")]
        found, coords = next_move(entry, transforms, played, SIZE)
        assert found and coords == (2, 1)

    def test_rotated_board_plays_transformed_moves(self):
        # Board recorded in lower-left, re-presented rotated 180 (upper-right)
        _, transforms0, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        rot_black = _transform_set(REF_BLACK, 2, SIZE)
        rot_white = _transform_set(REF_WHITE, 2, SIZE)
        key2, transforms2 = canonicalize(rot_black, rot_white, SIZE, "B")
        found, coords = next_move(entry, transforms2, [], SIZE)
        assert found and coords == transform_point(REF_LINE[0], 2, SIZE) == (12, 9)

    def test_pass_in_line(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        moves = [(REF_LINE[0], "B"), (None, "W"), (REF_LINE[2], "B")]
        entry["lines"] = [moves_to_canonical(moves, transforms[0], SIZE)]
        played = [(REF_LINE[0], "B"), (None, "W")]
        found, coords = next_move(entry, transforms, played, SIZE)
        assert found and coords == REF_LINE[2]


class TestAnswerBook:
    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / "book.json")
        book = AnswerBook(path=path)
        assert book.lookup("k1") is None
        assert book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4", "A2", "B1"])
        book2 = AnswerBook(path=path)  # 別インスタンス=ファイルから再ロード
        entry = book2.lookup("k1")
        assert entry is not None and entry["lines"] == [["A4", "A2", "B1"]]
        assert entry["size"] == 13 and entry["to_play"] == "B"

    def test_duplicate_line_ignored(self, tmp_path):
        book = AnswerBook(path=str(tmp_path / "book.json"))
        assert book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4"])
        assert not book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4"])
        assert len(book.lookup("k1")["lines"]) == 1

    def test_second_line_appended(self, tmp_path):
        book = AnswerBook(path=str(tmp_path / "book.json"))
        book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4", "A2"])
        book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4", "A3", "B2"])
        assert len(book.lookup("k1")["lines"]) == 2

    def test_corrupt_file_treated_as_empty(self, tmp_path):
        path = tmp_path / "book.json"
        path.write_text("{ broken json", encoding="utf-8")
        logs = []
        book = AnswerBook(path=str(path), logger=logs.append)
        assert book.lookup("k1") is None
        assert logs  # 破損はログに出す
        assert book.add_line("k1", 13, "B", [], [], ["A4"])  # 破損後も保存できる

    def test_missing_file_ok(self, tmp_path):
        book = AnswerBook(path=str(tmp_path / "none" / "book.json"))
        assert book.lookup("k1") is None
        assert book.add_line("k1", 9, "B", [], [], ["A4"])  # 親ディレクトリも作る


def _fake_game(black, white, line_moves_played, size, entry, transforms):
    """current_node チェーンと石リストを持つ最小の game。"""
    node = SimpleNamespace(move=None, parent=None)  # root
    stones = [SimpleNamespace(coords=p) for p in black | white]
    for i, coords in enumerate(line_moves_played):
        player = "BW"[i % 2]
        node = SimpleNamespace(move=SimpleNamespace(coords=coords, player=player), parent=node)
        if coords is not None:
            stones.append(SimpleNamespace(coords=coords))  # 取りは無視（占有チェック用の近似で十分）
    return SimpleNamespace(
        current_node=node,
        stones=stones,
        board_size=(size, size),
        tsumego_book_entry=entry,
        tsumego_book_transforms=transforms,
    )


class TestBookNextMove:
    def test_returns_recorded_move(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        game = _fake_game(REF_BLACK, REF_WHITE, [], SIZE, entry, transforms)
        found, coords = tsumego_book_next_move(game)
        assert found and coords == REF_LINE[0]

    def test_no_entry_returns_miss(self):
        game = _fake_game(REF_BLACK, REF_WHITE, [], SIZE, None, None)
        assert tsumego_book_next_move(game) == (False, None)

    def test_occupied_point_returns_miss(self):
        # 認識ずれ等で記録手の点が占有済みなら再生しない（スペック§8）
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        game = _fake_game(REF_BLACK | {REF_LINE[0]}, REF_WHITE, [], SIZE, entry, transforms)
        assert tsumego_book_next_move(game) == (False, None)

    def test_deviation_returns_miss(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        game = _fake_game(REF_BLACK, REF_WHITE, [REF_LINE[0], (6, 6)], SIZE, entry, transforms)
        assert tsumego_book_next_move(game) == (False, None)


class TestLineStatus:
    """GUI バナー用の状況判定（着手には使わない）。"""

    def test_playing_at_start_and_mid_line(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        players = ["B", "W"] * 3
        for n in range(len(REF_LINE)):  # 0手目〜最終手の1つ手前まで全部「再生中」
            played = list(zip(REF_LINE[:n], players[:n]))
            assert line_status(entry, transforms, played, SIZE) == "playing"

    def test_done_when_line_exhausted(self):
        # 記録を打ち切った局面は「逸脱」ではない（next_move は同じく miss を返す）
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = list(zip(REF_LINE, ["B", "W"] * 3))
        assert line_status(entry, transforms, played, SIZE) == "done"
        assert not next_move(entry, transforms, played, SIZE)[0]

    def test_off_when_white_deviates(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = [(REF_LINE[0], "B"), ((6, 6), "W")]
        assert line_status(entry, transforms, played, SIZE) == "off"

    def test_longer_line_wins_over_exhausted_one(self):
        # 短い line を打ち切っていても、続きのある line と前方一致するなら「再生中」
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE[:3], SIZE)
        entry["lines"].append(moves_to_canonical(list(zip(REF_LINE, ["B", "W"] * 3)), transforms[0], SIZE))
        played = list(zip(REF_LINE[:3], ["B", "W", "B"]))
        assert line_status(entry, transforms, played, SIZE) == "playing"


class TestShouldRecordLine:
    """正解した手順の自動記録（自動ループ）: 回答帳どおりに解答した問題は再記録しない。"""

    def test_records_when_not_in_book(self):
        played = list(zip(REF_LINE, ["B", "W"] * 3))
        assert should_record_line(None, None, played, SIZE) is True

    def test_skips_fully_replayed_line(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = list(zip(REF_LINE, ["B", "W"] * 3))
        assert should_record_line(entry, transforms, played, SIZE) is False

    def test_skips_prefix_of_recorded_line(self):
        # アプリが記録手順の途中で正解を出した＝回答帳が解いた問題。再記録しない
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = list(zip(REF_LINE[:3], ["B", "W", "B"]))
        assert should_record_line(entry, transforms, played, SIZE) is False

    def test_records_new_line_after_white_deviation(self):
        # 白が記録から逸脱して通常パイプラインで正解した手順は新しい line として記録する
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = [(REF_LINE[0], "B"), ((6, 6), "W"), ((2, 1), "B")]
        assert should_record_line(entry, transforms, played, SIZE) is True


class TestBookStatusFromGame:
    def test_no_entry_is_empty(self):
        game = _fake_game(REF_BLACK, REF_WHITE, [], SIZE, None, None)
        assert tsumego_book_status(game) == ""

    def test_playing(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        game = _fake_game(REF_BLACK, REF_WHITE, [], SIZE, entry, transforms)
        assert tsumego_book_status(game) == "playing"

    def test_occupied_point_reports_off(self):
        # 認識ずれで再生できない局面を「解答中」と表示しない（戦略の判定と一致させる）
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        game = _fake_game(REF_BLACK | {REF_LINE[0]}, REF_WHITE, [], SIZE, entry, transforms)
        assert tsumego_book_status(game) == "off"

    def test_done_and_off(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        assert tsumego_book_status(_fake_game(REF_BLACK, REF_WHITE, REF_LINE, SIZE, entry, transforms)) == "done"
        deviated = _fake_game(REF_BLACK, REF_WHITE, [REF_LINE[0], (6, 6)], SIZE, entry, transforms)
        assert tsumego_book_status(deviated) == "off"


class TestFrameCollisions:
    """回答帳の記録手順が枠の足した石に乗る問題（2026-11-07 実測・回答帳キー 452e79c7de…）。

    13路・黒が攻め方。認識石の bbox が 8行×7列で `fit_margin` が margin 4→2 に縮め、黒の壁が
    row 4 に来る。記録手順（21手）の白 17手目 B4・19手目 A4 はその壁の上なので、再生は
    黒 9手を打ったあと白 B4 の注入が "Space occupied" で止まり、以後の黒手が打てず誤答になる
    （ログ tsumego_20261107_014749 / 2026-08-24 にも同一の失敗）。
    """

    SIZE = 13
    BLACK = "A8 B8 C7 C9 D7 E12 E13 E6 E9 F10 F11 F7 F9 G12 G8".split()
    WHITE = "B10 B12 D12 D8 D9 E10 E11 E8".split()
    # 回答帳に入っている標準形向きの手順（盤の向きでは C11 C12 B11 C10 A10 D11 A11 A12 A9 C8 B9
    # B7 D10 B6 B5 C5 C6 **B4** A5 **A4** C10）
    LINE = "C3 B3 C2 D3 D1 C4 C1 B1 E1 F3 E2 G2 D4 H2 J2 J3 H3 K2 J1 K1 D3".split()

    def _grid(self):
        g = [["-"] * self.SIZE for _ in range(self.SIZE)]
        for stones, c in ((self.BLACK, "B"), (self.WHITE, "W")):
            for gtp in stones:
                x, y = gtp_to_point(gtp)
                g[self.SIZE - 1 - y][x] = c
        return g

    def _entry_and_transforms(self):
        from katrain.core.tsumego_problem import grid_to_stones

        black, white, (size, _) = grid_to_stones(self._grid())
        _key, transforms = canonicalize(black, white, size, "B")
        entry = {"size": size, "to_play": "B", "lines": [list(self.LINE)]}
        return entry, transforms

    def _framed(self):
        from katrain.core.tsumego_frame import tsumego_frame_board

        board, _region = tsumego_frame_board(self._grid(), 7.0, True, ko_p=False, margin=4)
        return board

    def test_frame_added_points_are_wall_and_fill_only(self):
        grid = self._grid()
        added = frame_added_points(grid, self._framed())
        assert added, "枠が1子も足していない"
        for x, y in added:
            assert grid[self.SIZE - 1 - y][x] == "-", "認識石の点を『枠が足した』と数えている"
        assert gtp_to_point("B4") in added and gtp_to_point("A4") in added, "前提: 壁が row 4 に来る"

    def test_recorded_white_replies_land_on_the_wall(self):
        entry, transforms = self._entry_and_transforms()
        hits = line_frame_collisions(entry, transforms, self.SIZE, frame_added_points(self._grid(), self._framed()))
        assert hits == [(17, "W", "B4"), (19, "W", "A4")]

    def test_no_collision_when_line_stays_inside(self):
        entry, transforms = self._entry_and_transforms()
        entry["lines"] = [list(self.LINE[:16])]  # B4 の手前まで
        blocked = frame_added_points(self._grid(), self._framed())
        assert line_frame_collisions(entry, transforms, self.SIZE, blocked) == []

    def test_no_entry_or_no_blocked_points(self):
        entry, transforms = self._entry_and_transforms()
        assert line_frame_collisions(None, transforms, self.SIZE, {(0, 0)}) == []
        assert line_frame_collisions(entry, transforms, self.SIZE, set()) == []
        assert line_frame_collisions(entry, [], self.SIZE, {(0, 0)}) == []

    def test_symmetric_position_tries_every_transform(self):
        # 対称な配置では盤→標準形の変換がタイになる。どの変換で読んでも枠に乗る手を見落とさない
        black = {(4, 4)}  # 9路の天元＝8対称すべてで不変
        white = set()
        _key, transforms = canonicalize(black, white, 9, "B")
        assert len(transforms) == 8
        entry = {"size": 9, "to_play": "B", "lines": [["A1"]]}
        # A1 の軌道は4隅。どれか1つだけ枠石でも衝突として拾う
        hits = line_frame_collisions(entry, transforms, 9, {(8, 8)})
        assert hits == [(0, "B", "J9")]
