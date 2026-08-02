"""tsumego_answer_book のユニットテスト（KataGo/Kivy/humanSL モデル不要）。"""
import pytest

from katrain.core.tsumego_answer_book import (
    AnswerBook,
    canonicalize,
    gtp_to_point,
    inverse_transform,
    moves_to_canonical,
    next_move,
    point_to_gtp,
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
            key, _ = canonicalize(
                _transform_set(REF_BLACK, t, SIZE), _transform_set(REF_WHITE, t, SIZE), SIZE, "B"
            )
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
