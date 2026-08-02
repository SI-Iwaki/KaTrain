"""死活ソルバの Python 参照実装（スペック §4/§6）。

正しさ優先の boolean AND/OR 探索（負号なし minimax + 置換表）。
- 2値分解（§4.5）: solve(ALIVE) / solve(SEKI 以上) の2述語 × komaster 2通り
- komaster / ko_budget（§4.3/§4.4）: komaster はコウ禁止の無視1回につき budget を1消費
- 同形反復（§4.6）: 基本則「生かす側の勝ち」+ 両コウの閉形式裁定（§4.6.1）+ taint 伝播
- セキ（§4.7）: 連続パス終端の評価から自動的に出る（静的認識器なし）
- GHI 対策: 反復裁定に依存した値は「どの祖先 ply まで依存したか」を返し、
  パス非依存の値だけ置換表（＝証明ストア §6.6）へ書く

実装メモ（スペックからの具体化。理由は spec 追記に記録）:
- 反復検出キーは（盤 + 手番 + コウ禁止点 + パス数）。コウ禁止点を含めないと
  komaster の取り返し直後に偽の同形反復が発生し、単劫が §4.6 の基本則で誤裁定される。
  komaster / budget 残量は含めない（含めるとサイクルが検出できない。§4.6）
"""

import sys
import time
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from katrain.core.tsumego_solver.board import Board, board_from_stones
from katrain.core.tsumego_solver.model import (
    BLACK,
    EMPTY,
    WHITE,
    Goal,
    Problem,
    ProblemType,
    RESULT_ORDER,
    ResultClass,
    Solution,
    SolutionValue,
    gtp_coord,
    opponent,
)

# 述語（§4.5）
PRED_ALIVE = "alive"  # target が2眼で生きる
PRED_SEKI = "seki"  # target がセキ以上（取られずに残る）
PRED_SEM_WIN = "sem_win"  # 攻め合い勝ち: 相手 target KILL ∧ 自 target LIVE
PRED_SEM_SEKI = "sem_seki"  # 自 target がセキ以上

INF_DEP = 1 << 30
PASS = None


class SolverTimeout(Exception):
    """ノード/時間制限に到達（→ 呼び出し側はフォールバック。G5）。"""


class SolverLimits:
    def __init__(
        self,
        node_limit: int = 20_000_000,
        time_limit_ms: float = 300_000.0,
        optimize_line: bool = True,
        ko_refine: bool = True,
        ko_budget_max: int = 2,
        max_alternatives: int = 8,
        opt_skip_after_ms: float = 5000.0,
    ):
        self.node_limit = node_limit
        self.time_limit_ms = time_limit_ms
        self.optimize_line = optimize_line
        self.ko_refine = ko_refine
        self.ko_budget_max = ko_budget_max
        self.max_alternatives = max_alternatives
        # 第1段階（分類）がこの時間を超えたら第2段階（plies/material 最適化）を省く。
        # 難問では opt が予算いっぱい（native 3秒）燃やしてタイムアウトし成果ゼロになる
        # （実測 2026-08-02: region22/KO と region24/SEKI の実戦2件とも plies=0 mat=0）。
        # plies==0 の同格タイは GUI 側の KataGo タイブレーク（§6.5.1-3）が並べ替えるので、
        # 遅い solve では省いて着手までの時間を縮める（クラス・本手は不変。§4.2.2 の
        # 「opt はクラス正のまま劣化してよい」の適用）。負値や 0 で常にスキップ
        self.opt_skip_after_ms = opt_skip_after_ms


class _Worse:
    """root 候補の振るい落とし結果（incumbent に届かない。§6.5.1）。"""

    def __repr__(self):
        return "WORSE"


WORSE = _Worse()


def ladder_steps(problem: Problem):
    """分類ラダー（§4.3.2.1 の完全対応表を評価順に並べたもの）。

    (ResultClass, sub_demotion, pred, komaster, want) を best→worst 順で返す。
    どの型でも「相手が komaster ＝ 自分にとって最悪の仮定」を先に解く並びなので、
    無条件が答えの問題は solve 1回で確定する（§4.3.3）。
    ReferenceSolver._ladder_steps と TsumegoSolverSession._better_gates
    （証明ストア即答のクラス格上げ確認。case AB）が共用する。
    """
    att, deff = opponent(problem.target_color), problem.target_color
    pt = problem.problem_type
    if pt == ProblemType.DEFEND:
        return [
            (ResultClass.UNCONDITIONAL, 0, PRED_ALIVE, att, True),  # A
            (ResultClass.SEKI, 0, PRED_SEKI, att, True),  # S
            (ResultClass.KO, 0, PRED_ALIVE, deff, True),  # A'
            (ResultClass.KO, 1, PRED_SEKI, deff, True),  # S'（コウでセキ）
        ]
    if pt == ProblemType.ATTACK:
        return [
            (ResultClass.UNCONDITIONAL, 0, PRED_SEKI, deff, False),  # ¬S'
            (ResultClass.KO, 0, PRED_SEKI, att, False),  # ¬S
            (ResultClass.SEKI, 0, PRED_ALIVE, att, False),  # ¬A（細目は A' で判別）
        ]
    own, opp = problem.to_play, opponent(problem.to_play)
    return [
        (ResultClass.UNCONDITIONAL, 0, PRED_SEM_WIN, opp, True),
        (ResultClass.KO, 0, PRED_SEM_WIN, own, True),
        (ResultClass.SEKI, 0, PRED_SEM_SEKI, opp, True),
        (ResultClass.KO, 1, PRED_SEM_SEKI, own, True),
    ]


class ReferenceSolver:
    def __init__(self, problem: Problem, limits: Optional[SolverLimits] = None):
        self.problem = problem
        self.limits = limits or SolverLimits()
        self.board = board_from_stones(problem.size, problem.black, problem.white)
        b = self.board
        self.region: Set[int] = {b.index(pt) for pt in problem.region}
        self.region_list = sorted(self.region)
        self.target_color = problem.target_color
        self.attacker_color = opponent(problem.target_color)
        self.own_color = problem.to_play
        # 局面が進んで target の元石が既に取られている場合は live-origin から落とす（§9.1）
        target_origin = sorted(
            b.index(pt) for pt in problem.target if self.board.stones[b.index(pt)] == problem.target_color
        )
        own_origin = sorted(
            b.index(pt) for pt in problem.own_target if self.board.stones[b.index(pt)] == problem.to_play
        )
        self._t_bit = {p: 1 << i for i, p in enumerate(target_origin)}
        self._o_bit = {p: 1 << i for i, p in enumerate(own_origin)}
        self.live_target: Set[int] = set(target_origin)
        self.live_own: Set[int] = set(own_origin)
        self.live_t_mask = (1 << len(target_origin)) - 1
        self.live_o_mask = (1 << len(own_origin)) - 1
        self.tt: Dict[tuple, Tuple[bool, bool]] = {}
        self.nodes = 0
        self.deadline: Optional[float] = None
        self.history: Dict[tuple, int] = {}
        self.path_moves: List[Tuple[Optional[int], Tuple[int, ...]]] = []
        self.benson_cache: Dict[Tuple[bytes, str], Set[int]] = {}
        self._history_order: Dict[Tuple[str, int], int] = {}  # (color, point) -> cutoff 回数
        self.taint_any = False  # このソルバ実行のどこかでサイクル裁定を使った
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))

    # ---------- 基本要素 ----------

    def _beneficiary(self, pred: str) -> str:
        """述語が True になってほしい側（＝maximizer）。"""
        if pred in (PRED_ALIVE, PRED_SEKI):
            return self.target_color
        return self.own_color

    def _pass_alive(self, color: str) -> Set[int]:
        key = (bytes("".join(self.board.stones), "ascii"), color)
        hit = self.benson_cache.get(key)
        if hit is None:
            hit = self.board.benson_pass_alive(color)
            if len(self.benson_cache) > 200_000:
                self.benson_cache.clear()
            self.benson_cache[key] = hit
        return hit

    def _early_eval(self, pred: str) -> Optional[bool]:
        """厳密な早期打ち切り（§6.3）。None なら未確定。"""
        if pred in (PRED_ALIVE, PRED_SEKI):
            if not self.live_target:
                return False  # 取られ確定
            pa = self._pass_alive(self.target_color)
            if any(p in pa for p in self.live_target):
                return True  # Benson: 以後何をされても取られない
            return None
        # 攻め合い
        if not self.live_own:
            return False
        if pred == PRED_SEM_WIN:
            if self.live_target:
                pa_t = self._pass_alive(self.target_color)
                if any(p in pa_t for p in self.live_target):
                    return False  # 相手 target が pass-alive ＝ もう殺せない
                return None
            pa_o = self._pass_alive(self.own_color)
            if any(p in pa_o for p in self.live_own):
                return True  # KILL 済み ∧ 自 target 生き
            return None
        # PRED_SEM_SEKI
        pa_o = self._pass_alive(self.own_color)
        if any(p in pa_o for p in self.live_own):
            return True
        return None

    def _two_pass_eval(self, pred: str) -> bool:
        """連続パス終端（§4.7。これが唯一の真の終端）。"""
        if pred == PRED_ALIVE:
            pa = self._pass_alive(self.target_color)
            return any(p in pa for p in self.live_target)
        if pred == PRED_SEKI:
            return bool(self.live_target)
        if pred == PRED_SEM_WIN:
            if self.live_target:
                return False
            pa_o = self._pass_alive(self.own_color)
            return any(p in pa_o for p in self.live_own)
        return bool(self.live_own)  # PRED_SEM_SEKI

    # ---------- 同形反復（§4.6）----------

    def _real_eyes(self, color: str) -> Set[int]:
        """保守的な実眼判定: 隣接がすべて color、斜め隣接の敵石が基準未満。"""
        b = self.board
        eyes = set()
        for p in range(len(b.stones)):
            if b.stones[p] != EMPTY:
                continue
            if any(b.stones[n] != color for n in b.neighbors[p]):
                continue
            x, y = p % b.width, p // b.width
            diags = [
                (x + dx, y + dy)
                for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1))
                if 0 <= x + dx < b.width and 0 <= y + dy < b.height
            ]
            bad = sum(1 for d in diags if b.stones[d[1] * b.width + d[0]] == opponent(color))
            limit = 2 if len(diags) == 4 else 1
            if bad < limit:
                eyes.add(p)
        return eyes

    def _adjudicate_cycle(self, pred: str, since_ply: int) -> bool:
        """反復終端の裁定（§4.6 基本則 + §4.6.1 両コウ閉形式）。"""
        self.taint_any = True
        moves = self.path_moves[since_ply:]
        if len(moves) >= 4 and all(pt is not None and len(caps) == 1 for pt, caps in moves):
            pairs = {frozenset((pt, caps[0])) for pt, caps in moves}
            if len(pairs) == 2:
                # 両コウ: 閉形式裁定（実眼の数）
                b = self.board
                t_eyes = self._real_eyes(self.target_color)
                target_chains: Set[int] = set()
                for p in self.live_target:
                    target_chains.update(self.board.chain(p)[0])
                t_eye_count = sum(1 for e in t_eyes if any(n in target_chains for n in b.neighbors[e]))
                ko_points = set()
                for pair in pairs:
                    ko_points.update(pair)
                a_color = self.attacker_color
                a_eyes = self._real_eyes(a_color)
                a_near: Set[int] = set()
                for kp in ko_points:
                    for n in b.neighbors[kp]:
                        if b.stones[n] == a_color:
                            a_near.update(b.chain(n)[0])
                a_eye_count = sum(1 for e in a_eyes if any(n in a_near for n in b.neighbors[e]))
                if t_eye_count >= 1 and a_eye_count >= 1:
                    verdict = "SEKI"
                elif t_eye_count >= 1:
                    verdict = "ALIVE"
                else:
                    verdict = "DEAD"
                if pred == PRED_ALIVE:
                    return verdict == "ALIVE"
                if pred == PRED_SEKI:
                    return verdict in ("ALIVE", "SEKI")
                if pred == PRED_SEM_WIN:
                    return verdict == "DEAD" and bool(self.live_own)
                return bool(self.live_own)
        # 基本則: 反復は「攻め手が詰まった」＝生かす側の勝ち
        if pred in (PRED_ALIVE, PRED_SEKI):
            return True
        if pred == PRED_SEM_WIN:
            return False  # 殺し未達
        return bool(self.live_own)

    # ---------- 探索本体 ----------

    def _check_limits(self):
        if self.nodes > self.limits.node_limit:
            raise SolverTimeout("node limit")
        if self.deadline is not None and self.nodes % 2048 == 0 and time.time() > self.deadline:
            raise SolverTimeout("time limit")

    def _position_key(self, to_play: str, ban: Optional[int], pass_count: int) -> tuple:
        return ("".join(self.board.stones), to_play, ban, min(pass_count, 1), self.live_t_mask, self.live_o_mask)

    def _ordered_moves(self, to_play: str) -> List[int]:
        """着手順序（§6.2。厳密性に影響しない。取り/逃げ > 呼吸点2 > 接触 > その他）。"""
        b = self.board
        chain_info: Dict[int, Tuple[int, int]] = {}  # 石の点 -> (連の石数, 呼吸点数)
        for stones, libs in b.all_chains():
            for q in stones:
                chain_info[q] = (len(stones), len(libs))
        scored = []
        hist = self._history_order
        for p in self.region_list:
            if b.stones[p] != EMPTY:
                continue
            score = hist.get((to_play, p), 0)
            near_stone = False
            for n in b.neighbors[p]:
                v = b.stones[n]
                if v == EMPTY:
                    continue
                near_stone = True
                n_stones, n_libs = chain_info[n]
                if n_libs == 1:
                    score += (1000 + 10 * n_stones) if v != to_play else 500
                elif n_libs == 2:
                    score += 50
            if near_stone:
                score += 10
            scored.append((score, p))
        scored.sort(key=lambda sp: -sp[0])
        return [p for _score, p in scored]

    def _play(self, p: int, color: str):
        """着手して (undo, new_ban, removed_t, removed_o) を返す。非合法（自殺手）は None。"""
        b = self.board
        u = b.try_play(p, color)
        if u is None:
            return None
        new_ban = None
        if len(u.captured) == 1:
            stones, libs = b.chain(p)
            if len(stones) == 1 and len(libs) == 1 and next(iter(libs)) == u.captured[0]:
                new_ban = u.captured[0]
        removed_t = [q for q in u.captured if q in self.live_target]
        removed_o = [q for q in u.captured if q in self.live_own]
        for q in removed_t:
            self.live_target.discard(q)
            self.live_t_mask &= ~self._t_bit[q]
        for q in removed_o:
            self.live_own.discard(q)
            self.live_o_mask &= ~self._o_bit[q]
        return u, new_ban, removed_t, removed_o

    def _unplay(self, u, removed_t, removed_o):
        for q in removed_t:
            self.live_target.add(q)
            self.live_t_mask |= self._t_bit[q]
        for q in removed_o:
            self.live_own.add(q)
            self.live_o_mask |= self._o_bit[q]
        self.board.undo(u)

    def _search(
        self,
        pred: str,
        komaster: Optional[str],
        budget: Optional[int],
        to_play: str,
        ban: Optional[int],
        pass_count: int,
        ply: int,
    ) -> Tuple[bool, bool, int]:
        """(value, cycle_taint, path_dependency_ply) を返す。"""
        self.nodes += 1
        self._check_limits()
        ev = self._early_eval(pred)
        if ev is not None:
            return ev, False, INF_DEP
        if pass_count >= 2:
            return self._two_pass_eval(pred), False, INF_DEP
        key = self._position_key(to_play, ban, pass_count)
        seen_ply = self.history.get(key)
        if seen_ply is not None:
            return self._adjudicate_cycle(pred, seen_ply), True, seen_ply
        tt_key = (key, pred, komaster, budget)
        hit = self.tt.get(tt_key)
        if hit is not None:
            return hit[0], hit[1], INF_DEP
        self.history[key] = ply
        maximizer = to_play == self._beneficiary(pred)
        value = not maximizer  # 子が全滅したときの値
        taint_acc = False
        dep_acc = INF_DEP
        decided = False
        try:
            for p in self._ordered_moves(to_play):
                child_budget = budget
                if p == ban:
                    if komaster == to_play and budget != 0:
                        child_budget = None if budget is None else budget - 1
                    else:
                        continue  # コウ禁止
                played = self._play(p, to_play)
                if played is None:
                    continue
                u, new_ban, removed_t, removed_o = played
                self.path_moves.append((p, tuple(u.captured)))
                try:
                    res, taint, dep = self._search(
                        pred, komaster, child_budget, opponent(to_play), new_ban, 0, ply + 1
                    )
                finally:
                    self.path_moves.pop()
                    self._unplay(u, removed_t, removed_o)
                if res == maximizer:
                    value, taint_acc, dep_acc, decided = res, taint, dep, True
                    hkey = (to_play, p)
                    self._history_order[hkey] = self._history_order.get(hkey, 0) + 1
                    break
                taint_acc |= taint
                dep_acc = min(dep_acc, dep)
            if not decided:
                # パス（§4.8。両者の合法手として常に持つ）
                self.path_moves.append((PASS, ()))
                try:
                    res, taint, dep = self._search(pred, komaster, budget, opponent(to_play), None, pass_count + 1, ply + 1)
                finally:
                    self.path_moves.pop()
                if res == maximizer:
                    value, taint_acc, dep_acc = res, taint, dep
                else:
                    taint_acc |= taint
                    dep_acc = min(dep_acc, dep)
        finally:
            del self.history[key]
        if dep_acc >= ply:  # パス（経路）非依存の値だけ証明ストアへ（GHI 対策）
            self.tt[tt_key] = (value, taint_acc)
        return value, taint_acc, dep_acc

    # ---------- solve のエントリ ----------

    def _solve_from_root(self, pred: str, komaster: Optional[str], budget: Optional[int]) -> Tuple[bool, bool]:
        self.history.clear()
        self.path_moves = []
        value, taint, _dep = self._search(pred, komaster, budget, self.problem.to_play, None, 0, 0)
        return value, taint

    def _solve_after_move(
        self, move: Optional[int], pred: str, komaster: Optional[str], budget: Optional[int]
    ) -> Tuple[bool, bool]:
        """root で move を1手打ってから解く（root 全手評価用。§6.5.1）。"""
        self.history.clear()
        self.path_moves = []
        to_play = self.problem.to_play
        if move is None:
            self.path_moves.append((PASS, ()))
            value, taint, _dep = self._search(pred, komaster, budget, opponent(to_play), None, 1, 1)
            self.path_moves.pop()
            return value, taint
        played = self._play(move, to_play)
        if played is None:
            raise ValueError(f"illegal root move {gtp_coord(self.board.point(move))}")  # 候補は事前に合法性で振るう
        u, new_ban, removed_t, removed_o = played
        self.path_moves.append((move, tuple(u.captured)))
        try:
            value, taint, _dep = self._search(pred, komaster, budget, opponent(to_play), new_ban, 0, 1)
        finally:
            self.path_moves.pop()
            self._unplay(u, removed_t, removed_o)
        return value, taint

    # ---------- 分類ラダー（§4.3.2.1 の完全対応表を評価順に並べたもの）----------

    def _ladder_steps(self):
        """(ResultClass, sub_demotion, pred, komaster, want) を best→worst 順で返す。"""
        return ladder_steps(self.problem)

    def _classify_after(self, move: Optional[int], floor_key=None):
        """move を打った後に解く側が保証できるクラス。floor_key（incumbent の
        (class_idx, sub, ko_level)）に届き得なくなったら WORSE（§6.5.1 の閾値テスト）。"""
        order = RESULT_ORDER[self.problem.problem_type]
        for result, sub, pred, komaster, want in self._ladder_steps():
            step_key = (order.index(result), sub, 0)
            if floor_key is not None and step_key > floor_key:
                return WORSE
            value, taint = self._solve_after_move(move, pred, komaster, None)
            if value != want:
                continue
            ko_level = 0
            if result == ResultClass.KO and self.limits.ko_refine:
                ko_level = self._refine_ko_after(move, pred, komaster, want, floor_key, step_key)
                if ko_level is WORSE:
                    return WORSE
            if self.problem.problem_type == ProblemType.ATTACK and result == ResultClass.SEKI:
                # 対応表 row2「コウでセキ」（A' ✓）は row3 の確定セキより下位（§4.3.2.1）
                a2, _t = self._solve_after_move(move, PRED_ALIVE, self.target_color, None)
                sub = 1 if a2 else 0
            final_key = (order.index(result), sub, ko_level)
            if floor_key is not None and final_key > floor_key:
                return WORSE
            return dict(
                result=result, sub=sub, ko_level=ko_level, pred=pred, komaster=komaster, want=want, taint=taint
            )
        step_key = (order.index(ResultClass.FAILED), 0, 0)
        if floor_key is not None and step_key > floor_key:
            return WORSE
        return dict(result=ResultClass.FAILED, sub=0, ko_level=0, pred=None, komaster=None, want=None, taint=False)

    def _refine_ko_after(self, move, pred, komaster, want, floor_key, step_key):
        """コウの細分 n*（結果が成立する最小 ko_budget。§4.4）。"""
        max_n = self.limits.ko_budget_max
        capped = False
        if floor_key is not None and floor_key[:2] == step_key[:2]:
            max_n = min(max_n, floor_key[2])  # incumbent と同段: floor の n* 以下だけ意味がある
            capped = max_n < self.limits.ko_budget_max
        for n in range(0, max_n + 1):
            try:
                value, _taint = self._solve_after_move(move, pred, komaster, n)
            except SolverTimeout:
                return self.limits.ko_budget_max + 1  # 細分を諦めクラスのみ（劣化。§4.4）
            if value == want:
                return n
        if capped:
            return WORSE
        return self.limits.ko_budget_max + 1  # 実用上の頭打ち（ヨセコウ深い）

    # ---------- 第2段階: クラス維持の下で (plies, material) を最小化（§4.2.2）----------

    OPT_NODE_LIMIT = 400_000
    _BIG = 10**6

    def _opt_gate(self, pred, komaster, budget, to_play, ban) -> bool:
        """現局面（board/live はセット済み）を独立局面として解く（証明ストアは共有）。"""
        saved_hist, saved_moves = self.history, self.path_moves
        self.history, self.path_moves = {}, []
        try:
            value, _taint, _dep = self._search(pred, komaster, budget, to_play, ban, 0, 0)
        finally:
            self.history, self.path_moves = saved_hist, saved_moves
        return value

    def _optimize_after(self, move: Optional[int], info) -> Tuple[int, int, List[Optional[int]]]:
        """root の move 後の本手順を (解く側の手数, 犠打) 最小で確定する。"""
        pred, komaster, want = info["pred"], info["komaster"], info["want"]
        budget = info["ko_level"] if info["result"] == ResultClass.KO else None
        if budget is not None and budget > self.limits.ko_budget_max:
            budget = None  # 細分できなかったコウは無限 budget のまま最適化
        self._opt_nodes = 0
        self._opt_memo: Dict[tuple, Tuple[int, int, tuple]] = {}
        to_play = self.problem.to_play
        if move is None:
            plies, mat, line, _clean = self._opt(pred, komaster, budget, want, opponent(to_play), None, 1, {})
            return plies, mat, list(line)
        played = self._play(move, to_play)
        u, new_ban, removed_t, removed_o = played
        try:
            plies, mat, line, _clean = self._opt(pred, komaster, budget, want, opponent(to_play), new_ban, 0, {})
        finally:
            self._unplay(u, removed_t, removed_o)
        return plies, mat, list(line)

    def _opt(self, pred, komaster, budget, want, to_play, ban, pass_count, history):
        self._opt_nodes += 1
        if self._opt_nodes > self.OPT_NODE_LIMIT:
            raise SolverTimeout("optimize node limit")
        self._check_limits()
        ev = self._early_eval(pred)
        if ev is not None:
            return (0, 0, (), True) if ev == want else (self._BIG, self._BIG, (), True)
        if pass_count >= 2:
            return (0, 0, (), True) if self._two_pass_eval(pred) == want else (self._BIG, self._BIG, (), True)
        key = self._position_key(to_play, ban, pass_count)
        if key in history:
            return 0, 0, (), False  # 反復＝クラスは裁定済み（経路依存なので memo しない）
        memo_key = (key, pred, komaster, budget, want)
        hit = self._opt_memo.get(memo_key)
        if hit is not None:
            return hit[0], hit[1], hit[2], True
        history[key] = True
        solver_side = self.problem.to_play
        best = None
        clean_acc = True
        try:
            moves = self._ordered_moves(to_play)
            if to_play == solver_side:
                for p in moves:
                    child_budget = budget
                    if p == ban:
                        if komaster == to_play and budget != 0:
                            child_budget = None if budget is None else budget - 1
                        else:
                            continue
                    played = self._play(p, to_play)
                    if played is None:
                        continue
                    u, new_ban, removed_t, removed_o = played
                    try:
                        if self._opt_gate(pred, komaster, child_budget, opponent(to_play), new_ban) == want:
                            plies, mat, line, clean = self._opt(
                                pred, komaster, child_budget, want, opponent(to_play), new_ban, 0, history
                            )
                            cand = (plies + 1, mat, (p,) + line)
                            clean_acc &= clean
                            if best is None or cand[:2] < best[:2]:
                                best = cand
                    finally:
                        self._unplay(u, removed_t, removed_o)
                if self._opt_gate(pred, komaster, budget, opponent(to_play), None) == want:
                    plies, mat, line, clean = self._opt(
                        pred, komaster, budget, want, opponent(to_play), None, pass_count + 1, history
                    )
                    cand = (plies, mat, (PASS,) + line)
                    clean_acc &= clean
                    if best is None or cand[:2] < best[:2]:
                        best = cand
            else:
                # 相手は (plies, material) を最大化＝最強の抵抗。盤上に合法手がある限りパスしない（§4.2.1）
                for p in moves:
                    child_budget = budget
                    if p == ban:
                        if komaster == to_play and budget != 0:
                            child_budget = None if budget is None else budget - 1
                        else:
                            continue
                    played = self._play(p, to_play)
                    if played is None:
                        continue
                    u, new_ban, removed_t, removed_o = played
                    mat_edge = sum(1 for q in u.captured if u.captured_color == solver_color_of(self))
                    try:
                        plies, mat, line, clean = self._opt(
                            pred, komaster, child_budget, want, opponent(to_play), new_ban, 0, history
                        )
                        cand = (plies, mat + mat_edge, (p,) + line)
                        clean_acc &= clean
                        if best is None or cand[:2] > best[:2]:
                            best = cand
                    finally:
                        self._unplay(u, removed_t, removed_o)
                if best is None:  # 合法手なし → パス
                    plies, mat, line, clean = self._opt(
                        pred, komaster, budget, want, opponent(to_play), None, pass_count + 1, history
                    )
                    clean_acc &= clean
                    best = (plies, mat, (PASS,) + line)
        finally:
            del history[key]
        if best is None:
            best = (self._BIG, self._BIG, ())
        if clean_acc:
            self._opt_memo[memo_key] = (best[0], best[1], best[2])
        return best[0], best[1], best[2], clean_acc

    # ---------- root 全手評価と Solution の組み立て（§6.5）----------

    def solve(self) -> Solution:
        t0 = time.time()
        self.deadline = t0 + self.limits.time_limit_ms / 1000.0
        to_play = self.problem.to_play
        order = RESULT_ORDER[self.problem.problem_type]
        scan_order = self._ordered_moves(to_play)
        # root スキャンの順序ヒント（座標タプルの列。§6.2: 順序は厳密性に影響しない）。
        # 呼び出し側が KataGo policy の上位を渡すと、正解が早く incumbent になり floor 刈りが
        # 効いて後続候補のラダー後段が省ける（実測 2026-08-02・region22 のコウ詰碁: 静的順序は
        # 急所 C11 の前に A9/B12/B9 のフルラダーで約8.5秒を浪費、C11 先頭で 17.3 → 12.1 秒・
        # nodes 1.6M → 1.0M）。全候補を評価し切る点は不変なので、クラス・本手は変わらない。
        # 石の上・盤外・重複が混ざっていても黙って捨てる（提供側は KataGo 候補をそのまま渡せる）
        hint = getattr(self, "root_order_hint", None)
        if hint:
            b = self.board
            hint_idx = []
            for pt in hint:
                try:
                    p = b.index(tuple(pt))
                except Exception:
                    continue
                if p in self.region and b.stones[p] == EMPTY and p not in hint_idx:
                    hint_idx.append(p)
            hinted = set(hint_idx)
            scan_order = hint_idx + [p for p in scan_order if p not in hinted]
        candidates: List[Optional[int]] = []
        for p in scan_order:
            played = self._play(p, to_play)
            if played is None:
                continue
            self._unplay(played[0], played[2], played[3])
            candidates.append(p)
        candidates.append(PASS)
        best_key = None
        classified: Dict[Optional[int], tuple] = {}
        for move in candidates:
            info = self._classify_after(move, floor_key=best_key)
            if info is WORSE:
                continue
            key = (order.index(info["result"]), info["sub"], info["ko_level"])
            classified[move] = (key, info)
            if best_key is None or key < best_key:
                best_key = key
        tie = [(m, info) for m, (key, info) in classified.items() if key == best_key]
        # 第1段階が遅かったら opt（plies/material 最小化）を省く。難問では opt が予算いっぱい
        # 燃やしてタイムアウトし成果ゼロ（実測 2026-08-02: 実戦2件とも plies=0 mat=0 で3秒浪費）。
        # クラス・本手は第1段階で確定済みなので正しさは不変（SolverLimits.opt_skip_after_ms 参照）
        stage1_ms = (time.time() - t0) * 1000.0
        allow_opt = self.limits.optimize_line and stage1_ms <= self.limits.opt_skip_after_ms
        final: List[Tuple[tuple, Optional[int], SolutionValue, dict, List[Optional[int]]]] = []
        for m, info in tie:
            plies, mat = 0, 0
            line: List[Optional[int]] = [m]
            if allow_opt and info["result"] != ResultClass.FAILED:
                try:
                    o_plies, o_mat, sub_line = self._optimize_after(m, info)
                    if o_plies < self._BIG:
                        plies = o_plies + (0 if m is None else 1)
                        mat = o_mat
                        line = [m] + list(sub_line)
                except SolverTimeout:
                    # 第1段階の解をそのまま（クラスは正しいまま劣化。§4.2.2）。さらに残りの
                    # タイの opt も打ち切る: タイムアウトしたタイは plies=0 のまま sort_key の
                    # 最上位に並ぶので、以後の opt は最終選択を変えられない（成功しても同格タイ
                    # から外れるだけ）。同格6手 × 3秒 = 18秒の初手を 3秒に縮める（実測 2026-08-02）
                    allow_opt = False
            value = SolutionValue(
                result=info["result"], ko_level=info["ko_level"], plies=plies, material=mat, sub_demotion=info["sub"]
            )
            final.append((value.sort_key(self.problem.problem_type), m, value, info, line))
        final.sort(key=lambda item: item[0])
        best_sort, best_move, best_value, best_info, best_line = final[0]
        same = [item for item in final if item[0] == best_sort][: self.limits.max_alternatives]
        root_moves = [None if item[1] is None else self.board.point(item[1]) for item in same]
        principal = [None if q is None else self.board.point(q) for q in best_line]
        move_values = {}
        for m, (_key, info) in classified.items():
            gtp = "pass" if m is None else gtp_coord(self.board.point(m))
            move_values[gtp] = SolutionValue(
                result=info["result"], ko_level=info["ko_level"], plies=0, material=0, sub_demotion=info["sub"]
            )
        beneficiary_won = best_info["want"] is True and best_info["pred"] in (PRED_ALIVE, PRED_SEKI)
        gate = None
        if best_info["pred"] is not None:
            gate_budget = best_info["ko_level"] if best_info["result"] == ResultClass.KO else None
            if gate_budget is not None and gate_budget > self.limits.ko_budget_max:
                gate_budget = None
            gate = (best_info["pred"], best_info["komaster"], gate_budget, best_info["want"])
        return Solution(
            value=best_value,
            komaster=best_info["komaster"],
            alive_by_repetition=bool(best_info["taint"] and beneficiary_won),
            cycle_tainted=bool(best_info["taint"]),
            root_moves=root_moves,
            principal_line=principal,
            nodes=self.nodes,
            elapsed_ms=(time.time() - t0) * 1000.0,
            problem_type=self.problem.problem_type,
            move_values=move_values,
            gate=gate,
        )


def solver_color_of(solver: "ReferenceSolver") -> str:
    return solver.problem.to_play


def solve_problem(problem: Problem, limits: Optional[SolverLimits] = None) -> Solution:
    return ReferenceSolver(problem, limits).solve()
