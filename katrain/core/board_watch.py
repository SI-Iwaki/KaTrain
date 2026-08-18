"""対局アプリの盤面を監視して、相手の着手を KaTrain へ注入するためのロジック。

Kivy にも KataGo にも依存しない（テストから直接 import できるようにするため）。
設計は docs/superpowers/specs/2026-08-18-board-watch-design.md 参照。

座標系に注意: 認識グリッド grid[i][j] の i は**画面上origin**（tsumego_capture.py:100）、
KaTrain の Move.coords = (x, y) は **y が下origin**（sgf_parser.py:31-39）。
この変換漏れは実測済みのバグ源なので、変換は必ずこのモジュールの純関数を通す。
"""

EMPTY = "."
BLACK = "B"
WHITE = "W"


def stones_to_grid(stones, size):
    """(coords, player) の列（coords は KaTrain の下origin (x, y)）を上origin グリッドにする"""
    grid = [[EMPTY] * size for _ in range(size)]
    for coords, player in stones:
        if coords is None:  # パスは盤に石を置かない
            continue
        x, y = coords
        grid[size - 1 - y][x] = player
    return grid


def move_to_grid(coords, size):
    """KaTrain の Move.coords (x, y) → グリッド座標 (i, j)。パス（None）は None"""
    if coords is None:
        return None
    x, y = coords
    return (size - 1 - y, x)


def grid_to_move(i, j, size):
    """グリッド座標 (i, j) → KaTrain の Move.coords (x, y)"""
    return (j, size - 1 - i)


def _neighbours(i, j, size):
    for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ni, nj = i + di, j + dj
        if 0 <= ni < size and 0 <= nj < size:
            yield ni, nj


def _group_and_liberties(grid, i, j):
    """(i, j) の石と同色で連結した石の集合と、その呼吸点の集合を返す"""
    size = len(grid)
    color = grid[i][j]
    stack = [(i, j)]
    group = {(i, j)}
    liberties = set()
    while stack:
        ci, cj = stack.pop()
        for ni, nj in _neighbours(ci, cj, size):
            v = grid[ni][nj]
            if v == EMPTY:
                liberties.add((ni, nj))
            elif v == color and (ni, nj) not in group:
                group.add((ni, nj))
                stack.append((ni, nj))
    return group, liberties


def apply_move_to_grid(grid, i, j, color):
    """グリッドに1手打ち、取りを処理した新グリッドを返す。打てないときは None。

    コウは判定しない（グリッド1枚では履歴が無いため）。コウ違反はエンジン側が
    弾き、注入ガードのタイムアウトとして表面化する（spec §2.5b）。
    """
    size = len(grid)
    if not (0 <= i < size and 0 <= j < size) or grid[i][j] != EMPTY:
        return None
    opponent = WHITE if color == BLACK else BLACK
    new_grid = [row[:] for row in grid]
    new_grid[i][j] = color
    for ni, nj in _neighbours(i, j, size):
        if new_grid[ni][nj] == opponent:
            group, liberties = _group_and_liberties(new_grid, ni, nj)
            if not liberties:
                for gi, gj in group:
                    new_grid[gi][gj] = EMPTY
    _group, liberties = _group_and_liberties(new_grid, i, j)
    if not liberties:
        return None  # 自殺手（取りを処理した後でも呼吸点が無い）
    return new_grid
