"""tsumego_answer_book のユニットテスト（KataGo/Kivy/humanSL モデル不要）。"""
import pytest

from katrain.core.tsumego_answer_book import (
    canonicalize,
    gtp_to_point,
    inverse_transform,
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
