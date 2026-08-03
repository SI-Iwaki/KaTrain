"""詰碁の問題抽出（スペック §5）— 枠の後継。KataGo を一切使わない純静的解析。

盤面（認識グリッド or 石座標）から
  - region（必要十分な点集合。§5.1 呼吸点の推移閉包 + 空点連結の閉包）
  - 問題の型（守り / 攻め / 攻め合い。§5.2.2）
  - target（危険な石の元座標の点集合。§5.2.3）
を決めて Problem を返す。閉じていない・対象が無い等は ProblemError（→ フォールバック。G5）。

実装メモ（スペックからの具体化）:
- region_hint（E2E/GUI の関心領域矩形）があるときは、hint の外に石がはみ出す連を
  無条件に壁として扱う（枠張り盤では壁の外側が代償地帯で埋まっており、呼吸点数の
  基準だけでは壁を吸収して region が爆発する）
- 同色の危険な連が両方に居るとき、片方が「相手の危険な連だけに囲われている」なら
  それは捨て石の材料（ナカデの中の石など）であって独立の戦いではない＝攻め合いに
  分類しない。双方が互いに囲い合っている（または どちらも外へ開く）ときだけ攻め合い
"""

from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from katrain.core.tsumego_solver.board import Board, board_from_stones
from katrain.core.tsumego_solver.model import (
    BLACK,
    EMPTY,
    WHITE,
    Goal,
    Point,
    Problem,
    ProblemError,
    ProblemType,
    opponent,
)

FRONTIER_LIBERTIES = 3  # 壁の判定: region 外の呼吸点がこれ以上なら壁（§5.1）
FRONTIER_RETRY_MAX = 5  # 閉じなければここまで上げて再構成
DEFAULT_MAX_REGION_POINTS = 72  # §8.4 solver_max_region_points（P1 の実測で調整。仮に緩め）
OPEN_RECT_MAX_POINTS = 84  # 矩形 region モード（枠なし・開いた盤）の上限。閉包モードより広くなる
MIN_TARGET_SPACE = 3  # target が眼を作れる余地（region − target の点数）の下限


def predetermined_reason(problem: Problem) -> Optional[str]:
    """開始時点で結果が決まっている（＝解くべき詰碁ではない）なら理由を返す。

    詰碁は「打つ手で結果が変わる」問題。target が使える空間 = region から target 自身の
    石を除いた点数（空点 + 眼空間の中の相手の石。ナカデの捨て石も眼空間なので数える）が
    2 以下だと、1手も打たないうちに結果が決まっている:
      0〜1 点 → 取るだけ（相手はもう何もできない）
      2 点   → 隣接なら二眼にならず死・離れていれば既に二眼で生き（どちらも手番と無関係）
    3 点（直三）が「初手で結果が変わる」最小の形なので、そこを下限にする。

    実測 2026-08-04 の GUI 誤答（13路・中央の開いた競り合い）: 盤の大半は広い空き地へ
    抜けて閉包が全部失敗し、黒に完全包囲された**呼吸点1の白1子 G8** だけが閉じた領域を
    作れた。抽出は「region 2点・target 1子の攻め」を返し、ソルバは正しく「G7 で取る」と
    答えたが、それは画面の詰碁ではない。実キャプチャ 21 ケースの空間は最小 6 点
    （Z 11−5）で、教科書的な最小形（直三・ナカデ）でも 3 点なので 2 以下だけを弾く。
    """
    space = len(problem.region) - len(problem.target)
    if space < MIN_TARGET_SPACE:
        return f"target が使える空間が {space} 点（初手より前に結果が決まっている）"
    if problem.problem_type == ProblemType.ATTACK and _captured_in_one(problem):
        # space は「眼を作れる余地」の代理でしかなく、target の眼空間ではない点（相手の石や
        # その呼吸点）まで数える。実測 2026-08-04 case AE（13路左上）: 中身は case AC と同じ
        # 「呼吸点1の白1子を取るだけ」なのに、閉包が黒 D8（呼吸点1・壁に裏打ち）とその呼吸点 D7 を
        # 巻き込んで region={D7,D8,E7,E8}／target={E8} ＝ space ちょうど 3 で素通りした。
        # 攻め方の手番で丸ごとアタリなら、region の広さに関係なく1手で取って終わり
        return "攻め方の手番で target が丸ごとアタリ（取るだけで終わる）"
    return None


def _captured_in_one(problem: Problem) -> bool:
    """target 全部を1手で取れる（＝target の全連がアタリで、唯一の呼吸点が同じ1点）か。"""
    board = board_from_stones(problem.size, problem.black, problem.white)
    shared: Optional[int] = None
    for stones, libs in board.all_chains():
        if board.point(stones[0]) not in problem.target:
            continue
        if len(libs) != 1:
            return False
        lib = next(iter(libs))
        if shared is not None and shared != lib:
            return False  # 別々の呼吸点＝1手では取り切れない
        shared = lib
    return shared is not None


def grid_to_stones(grid: Sequence[Sequence[str]]) -> Tuple[Set[Point], Set[Point], Tuple[int, int]]:
    """認識グリッド（grid[i][j]、i=上からの行）→ (黒石, 白石, 盤サイズ)。座標は (x, 下からの y)。"""
    size = len(grid)
    black, white = set(), set()
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            if v == "B":
                black.add((j, size - 1 - i))
            elif v == "W":
                white.add((j, size - 1 - i))
    return black, white, (size, size)


class _Extractor:
    def __init__(
        self,
        board: Board,
        to_play: str,
        region_hint: Optional[Sequence[int]],
        max_region_points: int,
    ):
        self.board = board
        self.to_play = to_play
        self.hint = region_hint  # [xmin, xmax, ymin, ymax]（両端含む）または None
        self.max_region_points = max_region_points
        self.chains: List[Tuple[List[int], Set[int]]] = board.all_chains()
        self.chain_of: Dict[int, int] = {}
        for ci, (stones, _libs) in enumerate(self.chains):
            for p in stones:
                self.chain_of[p] = ci
        self.pass_alive = board.benson_pass_alive(BLACK) | board.benson_pass_alive(WHITE)

    def _in_hint(self, p: int) -> bool:
        if self.hint is None:
            return True
        x, y = self.board.point(p)
        xmin, xmax, ymin, ymax = self.hint
        return xmin <= x <= xmax and ymin <= y <= ymax

    def _chain_in_hint(self, ci: int) -> bool:
        return all(self._in_hint(p) for p in self.chains[ci][0])

    NEAR_DEPTH = 2  # 吸収連からの空点 BFS 深さ（呼吸点=1、眼空間の内部点=2 まで）
    SMALL_COMPONENT = 12  # この大きさ以下の空点成分は丸ごと region に入れる（眼空間）
    FILL_CAP = 80  # 遠地帯をこの点数まで所有者の石で埋める。超えたら閉じていない扱い

    def _closure(self, seed_ids: Set[int], frontier: int):
        """§5.1 の構成規則。(region_stones, region_empty, absorbed_ids, wall_ids, fill) か、
        閉じなければ None。fill = {点: 色} — 吸収連から遠い空点成分（枠のチャンバー等）を
        境界が単色のときだけその色の地として埋め、region から外す（壁の生存仮定と同種）。"""
        b = self.board
        absorbed: Set[int] = set()
        walls: Set[int] = set()
        r_empty: Set[int] = set()
        pending = list(seed_ids)
        fill: Dict[int, str] = {}
        while True:
            while pending:
                while pending:
                    ci = pending.pop()
                    if ci in absorbed:
                        continue
                    absorbed.add(ci)
                    walls.discard(ci)
                # 空点の閉包: 吸収連の呼吸点 + 近傍 BFS（NEAR_DEPTH）+ 小さい成分（眼空間）は丸ごと
                r_empty = self._near_empties(absorbed)
                # region の空点に隣接する連を吸収するか壁とするか
                for p in list(r_empty):
                    for n in b.neighbors[p]:
                        if b.stones[n] == EMPTY:
                            continue
                        ci = self.chain_of[n]
                        if ci in absorbed:
                            continue
                        if not self._chain_in_hint(ci):
                            walls.add(ci)  # hint の外へはみ出す連は無条件に壁
                            continue
                        outside = {q for q in self.chains[ci][1] if q not in r_empty}
                        if len(outside) >= frontier:
                            walls.add(ci)  # 外部と十分に連絡している＝壁（呼吸点は入れない）
                        elif ci not in pending:
                            pending.append(ci)
            # 遠地帯の処理: region の空点と空点連結でまだ region に無い部分。
            # 境界が単色ならその色の地として埋める。hint 内の非壁連が境界に居るなら
            # それは同じチャンバー内の fight の続き＝吸収して繰り返す（散在する連の発見）
            fill = {}
            discovered: Set[int] = set()
            seen: Set[int] = set(r_empty)
            failed = False
            for start in list(r_empty):
                for n in b.neighbors[start]:
                    if b.stones[n] != EMPTY or n in seen:
                        continue
                    comp = [n]
                    seen.add(n)
                    stack = [n]
                    colors: Set[str] = set()
                    boundary: Set[int] = set()
                    overflow = False
                    while stack:
                        p = stack.pop()
                        for q in b.neighbors[p]:
                            v = b.stones[q]
                            if v == EMPTY:
                                if q not in seen and q not in r_empty:
                                    seen.add(q)
                                    comp.append(q)
                                    stack.append(q)
                            else:
                                colors.add(v)
                                boundary.add(self.chain_of[q])
                        if len(comp) > self.FILL_CAP:
                            overflow = True
                            break
                    inner = {
                        ci
                        for ci in boundary
                        if ci not in absorbed and ci not in walls and self._chain_in_hint(ci)
                    }
                    if overflow:
                        if inner:
                            discovered |= inner  # まず fight の続きを取り込んでから再判定
                        else:
                            return None  # 盤の広域へ抜けた＝閉じていない（§5.1）
                    elif len(colors) == 1:
                        owner = next(iter(colors))  # 境界が単色 → その色の地（内側連も同色の壁）
                        for p in comp:
                            fill[p] = owner
                    elif inner:
                        discovered |= inner  # 混色 + hint 内の非壁連 = 同じチャンバー内の fight の続き
                    else:
                        failed = True  # 壁の色が混在する遠地帯は埋められない
            if discovered:
                pending.extend(discovered)
                continue
            if failed:
                return None
            break
        # 壁は「不可侵の境界＝生きている」という仮定そのものなので、取れる連を壁にした閉包は
        # 元の詰碁と別問題になる。frontier（region 外の呼吸点数）は「外と連絡している」の
        # 代理でしかなく、外の呼吸点が行き止まり（眼空間や単独の空点）でも壁に化ける。
        # 実測 2026-08-02 の GUI 誤答（13路右下・黒が白の大群を殺す問題）: 隅でアタリの
        # 黒3子を種にした閉包が、その黒を殺している**白15子（呼吸点4・行き止まりの
        # J3/J4・K1・N3 だけ）を壁**にして「5点の中で黒が生きられるか」に化けさせた。
        # 白15子を種にすれば戦い全体（約40点）を正しく吸収するが、盤の空き地 82点が
        # FILL_CAP を超えて閉じないため候補から落ち、不健全な小問題だけが残っていた。
        # 呼吸点数では分離できない（既存の正しい壁も最小 libs4 = この誤答の壁と同値）ので、
        # anchors の判定と同じ「自色の壁/地に裏打ちされているか」で測る。
        for ci in walls:
            if not self._reaches_safety(ci, walls, fill):
                return None
        r_stones: Set[int] = set()
        for ci in absorbed:
            r_stones.update(self.chains[ci][0])
        if len(r_stones) + len(r_empty) > self.max_region_points:
            return None
        return r_stones, r_empty, absorbed, walls, fill

    def _near_empties(self, absorbed: Set[int]) -> Set[int]:
        """吸収連の呼吸点 + 深さ NEAR_DEPTH の空点 BFS + 小成分の丸ごと吸収。"""
        b = self.board
        frontier: Set[int] = set()
        for ci in absorbed:
            frontier |= self.chains[ci][1]
        result = set(frontier)
        depth = 1
        while depth < self.NEAR_DEPTH and frontier:
            nxt: Set[int] = set()
            for p in frontier:
                for n in b.neighbors[p]:
                    if b.stones[n] == EMPTY and n not in result:
                        nxt.add(n)
            result |= nxt
            frontier = nxt
            depth += 1
        # 小さい空点成分（眼空間）は丸ごと入れる: result の点を含む成分のサイズを測る
        comp_seen: Set[int] = set()
        for start in list(result):
            if start in comp_seen:
                continue
            comp = [start]
            comp_seen.add(start)
            stack = [start]
            while stack and len(comp) <= self.SMALL_COMPONENT:
                p = stack.pop()
                for n in b.neighbors[p]:
                    if b.stones[n] == EMPTY and n not in comp_seen:
                        comp_seen.add(n)
                        comp.append(n)
                        stack.append(n)
            if len(comp) <= self.SMALL_COMPONENT:
                result.update(comp)
        return result

    def _closes(self, result, target_color: str) -> Optional[str]:
        """封鎖検査（§5.1）。閉じていなければ理由文字列。"""
        if result is None:
            return "領域が閉じていない（空点が盤の広域へ抜ける）"
        _r_stones, r_empty, _absorbed, walls, _fill = result
        b = self.board
        # target 側の色の壁が region の空点に隣接 → 打てば外へ連絡できる＝逃げ出せる
        for ci in walls:
            color = b.stones[self.chains[ci][0][0]]
            if color != target_color:
                continue
            if any(any(n in r_empty for n in b.neighbors[p]) for p in self.chains[ci][0]):
                return "target が region 外へ連絡できる（閉じていない）"
        return None

    def _enclosed_only_by(self, chain_ids: Set[int], boundary_stones: Set[int], region_all: Set[int]) -> bool:
        """chain_ids の石が boundary_stones（相手の危険な連の石）**だけ**を境界として
        囲われているか。壁や region 外に触れたら False（捨て石の内包判定）。"""
        b = self.board
        start: Set[int] = set()
        color = None
        for ci in chain_ids:
            start.update(self.chains[ci][0])
            color = b.stones[self.chains[ci][0][0]]
        seen = set(start)
        stack = list(start)
        while stack:
            p = stack.pop()
            for n in b.neighbors[p]:
                if n in seen:
                    continue
                v = b.stones[n]
                if v == EMPTY or v == color:
                    if n not in region_all:
                        return False  # region の外へ届く＝内包ではない
                    seen.add(n)
                    stack.append(n)
                elif n not in boundary_stones:
                    return False  # 相手 target 以外（壁など）に触れた
        return True

    def extract(self) -> Problem:
        b = self.board
        candidates = [
            ci
            for ci in range(len(self.chains))
            if self._chain_in_hint(ci) and self.chains[ci][0][0] not in self.pass_alive
        ]
        candidates = [ci for ci in candidates if not all(p in self.pass_alive for p in self.chains[ci][0])]
        if not candidates:
            raise ProblemError("対象群が無い", "危険な石が見つからない")
        last_kind, last_reason = "領域が閉じていない", ""
        for frontier in range(FRONTIER_LIBERTIES, FRONTIER_RETRY_MAX + 1):
            # 種 = 単独で閉じ、かつその閉包の中で自色の壁/地へ到達できない連（＝本当に危険な連）。
            # 到達できる連は地に裏打ちされた壁側の石で、種にすると region が膨張する
            anchors: Set[int] = set()
            for ci in candidates:
                single = self._closure({ci}, frontier)
                if single is None:
                    continue
                if self._reaches_safety(ci, single[3], single[4]):
                    continue
                anchors.add(ci)
            if not anchors:
                last_kind, last_reason = "領域が閉じていない", "どの連からも閉じた領域が作れない"
                continue
            result = self._closure(anchors, frontier)
            if result is None:
                last_kind, last_reason = "領域が閉じていない", "領域が閉じない/大きすぎる"
                continue
            problem = self._decide(result)
            reason = self._closes(result, problem.target_color)
            if reason is not None:
                last_kind, last_reason = "領域が閉じていない", reason
                continue
            # 閉じていても「開始時点で結果が決まっている」形は詰碁ではない（ただの石取り）
            reason = predetermined_reason(problem)
            if reason is None:
                return problem
            last_kind, last_reason = "詰碁として成立していない", reason
        if self.hint is not None:
            problem = self._open_rect_problem()  # 枠なし・開いた盤: 矩形 region モード
            reason = predetermined_reason(problem)
            if reason is not None:
                raise ProblemError("詰碁として成立していない", reason)
            return problem
        raise ProblemError(last_kind, last_reason)

    # ---- 矩形 region モード（枠なしキャプチャの後継。現行の region_of_interest 相当）----

    def _open_boundary_ring(self) -> Set[int]:
        """hint 矩形の辺のうち盤端でない側の、矩形内側の縁の点集合。"""
        b = self.board
        xmin, xmax, ymin, ymax = self.hint
        ring: Set[int] = set()
        for x in range(xmin, xmax + 1):
            if ymin > 0:
                ring.add(ymin * b.width + x)
            if ymax < b.height - 1:
                ring.add(ymax * b.width + x)
        for y in range(ymin, ymax + 1):
            if xmin > 0:
                ring.add(y * b.width + xmin)
            if xmax < b.width - 1:
                ring.add(y * b.width + xmax)
        return ring

    def _open_rect_problem(self) -> Problem:
        """石で region が閉じない枠なし盤は hint 矩形そのものを region にする。

        - 矩形の外・開いた境界の縁に呼吸点を持つ連は「外の石」＝ target にしない
          （矩形外の呼吸点は詰められないので実質不死。縁の連は外へ逃げ出せる側）
        - 両色が内部に残るときは極値線の石の多数決で攻め方を推定（現行 extremum_stones の移植）
        """
        b = self.board
        xmin, xmax, ymin, ymax = self.hint
        rect = {y * b.width + x for x in range(xmin, xmax + 1) for y in range(ymin, ymax + 1)}
        if len(rect) > max(self.max_region_points, OPEN_RECT_MAX_POINTS):
            raise ProblemError("領域が大きすぎる", f"矩形 region {len(rect)} 点")
        ring = self._open_boundary_ring()
        interior: Dict[str, Set[int]] = {BLACK: set(), WHITE: set()}  # 色 -> chain ids
        for ci, (stones, libs) in enumerate(self.chains):
            if not all(p in rect for p in stones):
                continue
            if stones[0] in self.pass_alive:
                continue
            if any(q not in rect or q in ring for q in libs):
                continue  # 開いた境界に接する＝外の石
            interior[b.stones[stones[0]]].add(ci)
        me, opp = self.to_play, opponent(self.to_play)
        if interior[me] and interior[opp]:
            attacker = self._extremum_attacker(rect)
            if attacker is None:
                raise ProblemError("対象群が決まらない", "極値線の石が拮抗（攻め方を推定できない）")
            defender = opponent(attacker)
            target_ids = interior[defender]
            target_color = defender
            if not target_ids:
                raise ProblemError("対象群が無い", "守り方の内部連が無い")
        elif interior[me]:
            target_ids, target_color = interior[me], me
        elif interior[opp]:
            target_ids, target_color = interior[opp], opp
        else:
            raise ProblemError("対象群が無い", "矩形の内部に危険な連が無い")
        problem_type = ProblemType.DEFEND if target_color == self.to_play else ProblemType.ATTACK
        goal = Goal.LIVE if problem_type == ProblemType.DEFEND else Goal.KILL
        to_pt = b.point
        target = frozenset(to_pt(p) for ci in target_ids for p in self.chains[ci][0])
        black = frozenset(to_pt(p) for p in range(len(b.stones)) if b.stones[p] == BLACK)
        white = frozenset(to_pt(p) for p in range(len(b.stones)) if b.stones[p] == WHITE)
        return Problem(
            size=(b.width, b.height),
            black=black,
            white=white,
            region=frozenset(to_pt(p) for p in rect),
            to_play=self.to_play,
            target=target,
            goal=goal,
            problem_type=problem_type,
            target_color=target_color,
        )

    def _extremum_attacker(self, rect: Set[int]) -> Optional[str]:
        """矩形内の石の極値線（x/y の最小・最大の線）に乗る石の多数決で攻め方の色を返す。"""
        b = self.board
        pts = [p for p in rect if b.stones[p] != EMPTY]
        if not pts:
            return None
        xs = [p % b.width for p in pts]
        ys = [p // b.width for p in pts]
        extremum: Set[int] = set()
        for p in pts:
            x, y = p % b.width, p // b.width
            if x in (min(xs), max(xs)) or y in (min(ys), max(ys)):
                extremum.add(p)
        counts = {BLACK: 0, WHITE: 0}
        for p in extremum:
            counts[b.stones[p]] += 1
        if counts[BLACK] == counts[WHITE]:
            # 極値線が拮抗 → 矩形内の総石数で決める（囲う側=攻め方は石数が多い）
            totals = {BLACK: 0, WHITE: 0}
            for p in pts:
                totals[b.stones[p]] += 1
            if totals[BLACK] == totals[WHITE]:
                return None
            return BLACK if totals[BLACK] > totals[WHITE] else WHITE
        return BLACK if counts[BLACK] > counts[WHITE] else WHITE

    SAFE_LIBERTIES = 7  # これ以上の呼吸点を持つ連は詰碁の対象ではない（外周の壁など）

    def _reaches_safety(self, ci: int, walls: Set[int], fill: Dict[int, str]) -> bool:
        """連 ci が空点・自色石経由で「同色の壁」か「同色の埋め地」に到達できるか。
        到達できる連は地に裏打ちされた攻め方の石であって「危険な石」ではない。"""
        b = self.board
        if len(self.chains[ci][1]) >= self.SAFE_LIBERTIES:
            return True  # 呼吸点が十分に多い＝取られる心配のない囲い側
        color = b.stones[self.chains[ci][0][0]]
        wall_stones = {p for wi in walls for p in self.chains[wi][0] if b.stones[self.chains[wi][0][0]] == color}
        fill_pts = {p for p, c in fill.items() if c == color}
        seen = set(self.chains[ci][0])
        stack = list(seen)
        while stack:
            p = stack.pop()
            for n in b.neighbors[p]:
                if n in seen:
                    continue
                if n in wall_stones or n in fill_pts:
                    return True
                if n in fill:
                    continue  # 相手色の埋め地は石として塞ぐ
                v = b.stones[n]
                if v == EMPTY or v == color:
                    seen.add(n)
                    stack.append(n)
        return False

    def _decide(self, closure_result) -> Problem:
        """§5.2: at_risk → 型 → target → Problem。"""
        b = self.board
        r_stones, r_empty, absorbed, walls, fill = closure_result
        region_all = r_stones | r_empty
        at_risk: Dict[str, Set[int]] = {BLACK: set(), WHITE: set()}  # 色 -> chain ids
        for ci in absorbed:
            stones = self.chains[ci][0]
            if all(p in self.pass_alive for p in stones):
                continue  # 既に2眼で生きている石は除外（§5.2.1）
            if self._reaches_safety(ci, walls, fill):
                continue  # 同色の壁/地に連絡できる＝攻め方の裏打ちされた石
            at_risk[b.stones[stones[0]]].add(ci)
        me, opp = self.to_play, opponent(self.to_play)
        my_risk, opp_risk = at_risk[me], at_risk[opp]
        if my_risk and opp_risk:
            # 捨て石の内包判定: 片方が相手 target だけに囲われているなら独立の危険ではない
            my_stones = {p for ci in my_risk for p in self.chains[ci][0]}
            opp_stones = {p for ci in opp_risk for p in self.chains[ci][0]}
            mine_inside = self._enclosed_only_by(my_risk, opp_stones, region_all)
            opp_inside = self._enclosed_only_by(opp_risk, my_stones, region_all)
            if mine_inside and not opp_inside:
                my_risk = set()
            elif opp_inside and not mine_inside:
                opp_risk = set()
            else:
                # 両者が「内包」または「非内包」= 攻め合いは共有ダメを争う関係のときだけ。
                # 共有呼吸点が無ければ内外の関係（外側=壁側）で、呼吸点の少ない側が target
                my_libs = {q for ci in my_risk for q in self.chains[ci][1]}
                opp_libs = {q for ci in opp_risk for q in self.chains[ci][1]}
                if not (my_libs & opp_libs):
                    if len(my_libs) < len(opp_libs):
                        opp_risk = set()
                    elif len(opp_libs) < len(my_libs):
                        my_risk = set()
        to_pt = b.point
        if my_risk and opp_risk:
            problem_type, goal = ProblemType.SEMEAI, Goal.SEMEAI
            target_color = opp
            target = frozenset(to_pt(p) for ci in opp_risk for p in self.chains[ci][0])
            own_target = frozenset(to_pt(p) for ci in my_risk for p in self.chains[ci][0])
        elif my_risk:
            problem_type, goal = ProblemType.DEFEND, Goal.LIVE
            target_color = me
            target = frozenset(to_pt(p) for ci in my_risk for p in self.chains[ci][0])
            own_target = frozenset()
        elif opp_risk:
            problem_type, goal = ProblemType.ATTACK, Goal.KILL
            target_color = opp
            target = frozenset(to_pt(p) for ci in opp_risk for p in self.chains[ci][0])
            own_target = frozenset()
        else:
            raise ProblemError("対象群が無い", "at_risk が空（すべて壁か生き）")
        # 遠地帯は所有者の石で埋める（ソルバ入力のみ。GUI 表示は実盤面のまま）
        fill_black = frozenset(to_pt(p) for p, c in fill.items() if c == BLACK)
        fill_white = frozenset(to_pt(p) for p, c in fill.items() if c == WHITE)
        black = frozenset({to_pt(p) for p in range(len(b.stones)) if b.stones[p] == BLACK} | fill_black)
        white = frozenset({to_pt(p) for p in range(len(b.stones)) if b.stones[p] == WHITE} | fill_white)
        return Problem(
            size=(b.width, b.height),
            black=black,
            white=white,
            region=frozenset(to_pt(p) for p in region_all),
            to_play=self.to_play,
            target=target,
            goal=goal,
            problem_type=problem_type,
            target_color=target_color,
            own_target=own_target,
            fill_black=fill_black,
            fill_white=fill_white,
        )


def extract_problem(
    grid=None,
    *,
    board_size: Optional[Tuple[int, int]] = None,
    stones: Optional[Tuple[Iterable[Point], Iterable[Point]]] = None,
    to_play: str = BLACK,
    region_hint: Optional[Sequence[int]] = None,
    max_region_points: int = DEFAULT_MAX_REGION_POINTS,
) -> Problem:
    """盤面から Problem を抽出する（§5.3）。失敗は ProblemError。

    grid: tsumego_capture の認識グリッド（"B"/"W"/"."）。または stones=(黒点集合, 白点集合)
    と board_size を渡す。region_hint は [xmin, xmax, ymin, ymax]（両端含む）。
    """
    if grid is not None:
        black, white, size = grid_to_stones(grid)
    else:
        if stones is None or board_size is None:
            raise ValueError("grid か (stones, board_size) のどちらかが必要")
        black, white = set(stones[0]), set(stones[1])
        size = board_size
    if not black and not white:
        raise ProblemError("対象群が無い", "石が1つも無い")
    board = board_from_stones(size, black, white)
    return _Extractor(board, to_play, region_hint, max_region_points).extract()
