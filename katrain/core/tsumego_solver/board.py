"""ソルバ用の盤面機構: 着手・取り・自殺手判定・連/呼吸点・Benson pass-alive。

参照実装なので速度より読みやすさ・正しさを優先する（flood fill を都度計算）。
点はインデックス p = y * width + x で持つ。
"""

from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from katrain.core.tsumego_solver.model import BLACK, EMPTY, WHITE, opponent


class Undo:
    __slots__ = ("point", "color", "captured", "captured_color")

    def __init__(self, point, color, captured, captured_color):
        self.point = point
        self.color = color
        self.captured = captured  # List[int]
        self.captured_color = captured_color


class Board:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.stones: List[str] = [EMPTY] * (width * height)
        self.neighbors: List[Tuple[int, ...]] = []
        for p in range(width * height):
            x, y = p % width, p // width
            ns = []
            if x > 0:
                ns.append(p - 1)
            if x < width - 1:
                ns.append(p + 1)
            if y > 0:
                ns.append(p - width)
            if y < height - 1:
                ns.append(p + width)
            self.neighbors.append(tuple(ns))

    def index(self, point: Tuple[int, int]) -> int:
        return point[1] * self.width + point[0]

    def point(self, p: int) -> Tuple[int, int]:
        return (p % self.width, p // self.width)

    def set_stone(self, p: int, color: str):
        self.stones[p] = color

    def chain(self, p: int) -> Tuple[List[int], Set[int]]:
        """p の石が属する連の (石リスト, 呼吸点集合)。"""
        color = self.stones[p]
        assert color != EMPTY
        seen = {p}
        stack = [p]
        stones = []
        libs: Set[int] = set()
        while stack:
            q = stack.pop()
            stones.append(q)
            for n in self.neighbors[q]:
                v = self.stones[n]
                if v == EMPTY:
                    libs.add(n)
                elif v == color and n not in seen:
                    seen.add(n)
                    stack.append(n)
        return stones, libs

    def chain_liberties(self, p: int) -> int:
        return len(self.chain(p)[1])

    def all_chains(self, color: Optional[str] = None) -> List[Tuple[List[int], Set[int]]]:
        seen: Set[int] = set()
        chains = []
        for p in range(len(self.stones)):
            v = self.stones[p]
            if v == EMPTY or p in seen or (color is not None and v != color):
                continue
            stones, libs = self.chain(p)
            seen.update(stones)
            chains.append((stones, libs))
        return chains

    def try_play(self, p: int, color: str) -> Optional[Undo]:
        """p に color を着手する。自殺手なら盤面を触らず None。コウ禁は呼び出し側が判定する。"""
        if self.stones[p] != EMPTY:
            return None
        opp = opponent(color)
        self.stones[p] = color
        captured: List[int] = []
        for n in self.neighbors[p]:
            if self.stones[n] == opp:
                stones, libs = self.chain(n)
                if not libs:
                    for q in stones:
                        if self.stones[q] == opp:  # 同一連を二度取らない
                            self.stones[q] = EMPTY
                            captured.append(q)
        if not captured:
            _, libs = self.chain(p)
            if not libs:
                self.stones[p] = EMPTY
                return None  # 自殺手
        return Undo(p, color, captured, opp)

    def undo(self, u: Undo):
        for q in u.captured:
            self.stones[q] = u.captured_color
        self.stones[u.point] = EMPTY

    def position_key(self) -> bytes:
        return "".join(self.stones).encode()

    # ---- Benson pass-alive（§6.3）----

    def benson_pass_alive(self, color: str) -> Set[int]:
        """color の石のうち pass-alive な連に属する点の集合（Benson 1976）。"""
        chains = self.all_chains(color)
        if not chains:
            return set()
        chain_id: Dict[int, int] = {}
        for i, (stones, _libs) in enumerate(chains):
            for p in stones:
                chain_id[p] = i
        # color 以外の点（空点+敵石）の連結成分 = 囲まれた小領域の候補
        regions: List[Tuple[List[int], Set[int], Set[int]]] = []  # (points, empties, adjacent_chain_ids)
        seen: Set[int] = set()
        for p in range(len(self.stones)):
            if self.stones[p] == color or p in seen:
                continue
            comp = [p]
            seen.add(p)
            stack = [p]
            empties: Set[int] = set()
            adj: Set[int] = set()
            while stack:
                q = stack.pop()
                if self.stones[q] == EMPTY:
                    empties.add(q)
                for n in self.neighbors[q]:
                    if self.stones[n] == color:
                        adj.add(chain_id[n])
                    elif n not in seen:
                        seen.add(n)
                        comp.append(n)
                        stack.append(n)
            regions.append((comp, empties, adj))
        # region r が chain c に vital ⇔ r の空点がすべて c の呼吸点
        chain_libs = [libs for _stones, libs in chains]
        alive_chains = set(range(len(chains)))
        alive_regions = set(range(len(regions)))
        changed = True
        while changed:
            changed = False
            for ci in list(alive_chains):
                vital = 0
                for ri in alive_regions:
                    _comp, empties, adj = regions[ri]
                    if ci in adj and empties and empties <= chain_libs[ci]:
                        vital += 1
                if vital < 2:
                    alive_chains.discard(ci)
                    changed = True
            for ri in list(alive_regions):
                _comp, _empties, adj = regions[ri]
                if not adj <= alive_chains:
                    alive_regions.discard(ri)
                    changed = True
        result: Set[int] = set()
        for ci in alive_chains:
            result.update(chains[ci][0])
        return result


def board_from_stones(size: Tuple[int, int], black: Iterable[Tuple[int, int]], white: Iterable[Tuple[int, int]]) -> Board:
    board = Board(size[0], size[1])
    for pt in black:
        board.set_stone(board.index(pt), BLACK)
    for pt in white:
        board.set_stone(board.index(pt), WHITE)
    return board
