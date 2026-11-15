"""観戦用の盤面反映モードの純ロジック（Kivy 非依存）。

アプリ側の盤（observed）が KaTrain の本譜の末尾（tip）からどれだけ進んだかを判定する。
"""

from itertools import permutations
from typing import NamedTuple

from katrain.core.board_watch import BLACK, EMPTY, WHITE, apply_move_to_grid

# これを超える手数の差は並べ替えを試さず、走査順だけ試す
SPECTATE_MAX_PERMUTE = 6


class SpectateVerdict(NamedTuple):
    kind: str  # "in_sync" | "moves" | "behind" | "reimport"
    moves: tuple = ()  # ((i, j, color), ...) の着手順
    estimated: bool = False
    reason: str = ""


def _replay(grid, moves):
    for i, j, color in moves:
        grid = apply_move_to_grid(grid, i, j, color)
        if grid is None:
            return None
    return grid


def _interleave(blacks, whites, colors):
    """colors の色順に、各色の石を渡された順で取り出して着手列にする"""
    bi = iter(blacks)
    wi = iter(whites)
    return tuple((*next(bi), BLACK) if c == BLACK else (*next(wi), WHITE) for c in colors)


def spectate_sync(
    tip_grid,
    observed,
    to_play,
    last_mover=None,
    app_move_number=None,
    tip_move_number=None,
    ancestor_grids=(),
):
    if len(observed) != len(tip_grid) or any(len(r) != len(tip_grid) for r in observed):
        return SpectateVerdict("reimport", reason="盤サイズが違う")
    if observed == tip_grid:
        return SpectateVerdict("in_sync")
    if any(observed == a for a in ancestor_grids):
        return SpectateVerdict("behind", reason="本譜の過去の局面")

    size = len(tip_grid)
    added = [
        (i, j, observed[i][j])
        for i in range(size)
        for j in range(size)
        if tip_grid[i][j] == EMPTY and observed[i][j] != EMPTY
    ]
    n = len(added)
    if n == 0:
        return SpectateVerdict("reimport", reason="増えた石が無い")

    other = WHITE if to_play == BLACK else BLACK
    colors = [to_play if k % 2 == 0 else other for k in range(n)]
    blacks = [(i, j) for i, j, c in added if c == BLACK]
    whites = [(i, j) for i, j, c in added if c == WHITE]
    if len(blacks) != colors.count(BLACK) or len(whites) != colors.count(WHITE):
        return SpectateVerdict("reimport", reason="増えた石の色が交互の着手で説明できない")
    if last_mover is not None and colors[-1] != last_mover:
        return SpectateVerdict("reimport", reason="直前手の色と合わない")
    if app_move_number is not None and tip_move_number is not None and tip_move_number + n != app_move_number:
        return SpectateVerdict("reimport", reason="手数が合わない")

    estimated = n >= 2
    moves = _interleave(blacks, whites, colors)
    if _replay(tip_grid, moves) == observed:
        return SpectateVerdict("moves", moves, estimated)
    if n <= SPECTATE_MAX_PERMUTE:
        for bp in permutations(blacks):
            for wp in permutations(whites):
                moves = _interleave(bp, wp, colors)
                if _replay(tip_grid, moves) == observed:
                    return SpectateVerdict("moves", moves, estimated)
    return SpectateVerdict("reimport", reason="着手の並びで説明できない")
