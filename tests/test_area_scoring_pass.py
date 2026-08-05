# tests/test_area_scoring_pass.py
"""area scoring（中国ルール等）のパス判定のユニットテスト。

実測の背景（2026-08-06・13路・中国ルール・実戦ログ game_20260806_011214）:
ダメが13個残っている局面で pass_loss=0.10 目しかない（area scoring では
ダメ詰めが score-neutral なので「ダメが残る局面」と「本当の終局」が
どちらも 0 目差に見える）。同じ局面の humanPolicy(pass)=0.0000、ダメを
詰め切った後は 0.37〜0.75 で、人間モデルだけが両者を区別できる。
"""
import pytest

from katrain.core.ai import _AREA_PASS_MARGIN, _area_scoring_should_pass
from katrain.core.sgf_parser import Move


def _pass(w):
    return (Move(None, player="B"), w)


def _pt(gtp, w):
    return (Move.from_gtp(gtp, player="B"), w)


class TestAreaScoringShouldPass:
    def test_dame_remaining_does_not_pass(self):
        """実測の失敗局面: pass の humanPolicy が 0 なのでパスしない。"""
        moves = [_pt("N3", 0.4090), _pt("C1", 0.3287), _pt("C3", 0.1119), _pass(0.0)]
        assert _area_scoring_should_pass(moves, pass_loss=0.10) is False

    def test_game_over_passes(self):
        """実測の終局局面: humanPolicy がパスを最上位に置くのでパスする。"""
        moves = [_pt("N8", 0.0039), _pt("A9", 0.0010), _pass(0.7491)]
        assert _area_scoring_should_pass(moves, pass_loss=0.05) is True

    def test_costly_pass_never_passes_even_if_human_prefers_it(self):
        """目数条件は残す: パスが明確に損なら humanPolicy が推しても打つ。"""
        moves = [_pt("K13", 0.10), _pass(0.90)]
        assert _area_scoring_should_pass(moves, pass_loss=20.65) is False

    def test_loss_exactly_at_margin_does_not_pass(self):
        moves = [_pt("K13", 0.10), _pass(0.90)]
        assert _area_scoring_should_pass(moves, pass_loss=_AREA_PASS_MARGIN) is False

    def test_unknown_pass_loss_does_not_pass(self):
        """KataGo が pass を評価していない場合は従来どおり打つ（保守側）。"""
        moves = [_pt("K13", 0.10), _pass(0.90)]
        assert _area_scoring_should_pass(moves, pass_loss=None) is False

    def test_no_pass_candidate_does_not_pass(self):
        moves = [_pt("N3", 0.41), _pt("C1", 0.33)]
        assert _area_scoring_should_pass(moves, pass_loss=0.10) is False

    def test_pass_only_candidate_passes(self):
        moves = [_pass(0.02)]
        assert _area_scoring_should_pass(moves, pass_loss=0.10) is True

    def test_tie_between_pass_and_best_point_passes(self):
        """同着はパス側に倒す（打ち続けて無限対局になるより安全）。"""
        moves = [_pt("N3", 0.30), _pass(0.30)]
        assert _area_scoring_should_pass(moves, pass_loss=0.10) is True

    def test_pass_slightly_below_best_point_does_not_pass(self):
        moves = [_pt("N3", 0.31), _pass(0.30)]
        assert _area_scoring_should_pass(moves, pass_loss=0.10) is False

    def test_empty_moves_does_not_pass(self):
        assert _area_scoring_should_pass([], pass_loss=0.10) is False
