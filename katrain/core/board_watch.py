"""対局アプリの盤面を監視して、相手の着手を KaTrain へ注入するためのロジック。

Kivy にも KataGo にも依存しない（テストから直接 import できるようにするため）。
設計は docs/superpowers/specs/2026-08-18-board-watch-design.md 参照。

座標系に注意: 認識グリッド grid[i][j] の i は**画面上origin**（tsumego_capture.py:100）、
KaTrain の Move.coords = (x, y) は **y が下origin**（sgf_parser.py:31-39）。
この変換漏れは実測済みのバグ源なので、変換は必ずこのモジュールの純関数を通す。
"""

from typing import NamedTuple, Optional, Tuple

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


class WatchState(NamedTuple):
    """KaTrain 側の局面スナップショット（__main__ が作り、判定はここでだけ行う）"""

    current_grid: list
    last_move: Optional[Tuple[int, int, str]]  # (i, j, color)。root とパスは None
    to_play: str
    to_play_is_human: bool
    ai_can_respond: bool
    move_number: int
    board_size: int


class Verdict(NamedTuple):
    kind: str  # "in_sync" | "waiting" | "ahead" | "move" | "mismatch"
    move: Optional[Tuple[int, int]] = None
    reason: str = ""


def reconcile(state, observed):
    """観測グリッドが「現局面＋打つ側の1手」で説明できるかを判定する。

    表は**上から評価する優先順位**（spec §2.3）。特に「AI の手番なら絶対に注入しない」
    （waiting）を Move 判定より前に置くのが安全弁の要 — 色の割り当てが逆だと相手の石が
    常に to_play と同色になり、Move 判定が成立してしまう。
    """
    if len(observed) != state.board_size:
        return Verdict(
            "mismatch",
            reason=f"盤サイズが違います（アプリ {len(observed)}路 / KaTrain {state.board_size}路）",
        )
    if not state.ai_can_respond:
        return Verdict("mismatch", reason="AI が応手できない局面です（分岐・終局・解析モード・リージョン）")
    if not state.to_play_is_human:
        # KaTrain の AI が考えている最中。正常状態なので無音（数秒続くため警告にしてはいけない）。
        # 色の割り当てが逆でここから永久に出られないケースは BoardWatcher のウォッチドッグが拾う
        return Verdict("waiting")
    if observed == state.current_grid:
        return Verdict("in_sync")
    if state.last_move is not None:
        li, lj, lcolor = state.last_move
        if apply_move_to_grid(observed, li, lj, lcolor) == state.current_grid:
            return Verdict("ahead")
    matches = []
    for i in range(state.board_size):
        for j in range(state.board_size):
            if observed[i][j] == state.to_play and state.current_grid[i][j] == EMPTY:
                if apply_move_to_grid(state.current_grid, i, j, state.to_play) == observed:
                    matches.append((i, j))
    if len(matches) == 1:
        return Verdict("move", move=matches[0])
    return Verdict("mismatch", reason="盤面の差が1手で説明できません")
