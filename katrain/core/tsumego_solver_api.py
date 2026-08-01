"""死活ソルバの呼び出しラッパ + フォールバック判断（スペック §9）。

戦略（ai:tsumego_solver）と KaTrain 本体の間に立つ薄い層:
- 問題コンテキスト（Problem・型・確定クラス）は出題時に確定し、以後の手番で引き継ぐ（§9.1）
- 実対局のコウ禁止に当たる手は絶対に打たない（§9.1。別手かパスに退避し「コウ待ち」をログ）
- 解けない/打ち切り/FAILED は None を返し、呼び出し側が現行経路へフォールバック（§9.2）

Kivy 非依存。ログは logger コールバック（str, level）で受ける。
"""

import time
from typing import Callable, List, Optional, Tuple

from katrain.core.tsumego_problem import extract_problem
from katrain.core.tsumego_solver.board import Board, board_from_stones
from katrain.core.tsumego_solver.model import (
    BLACK,
    EMPTY,
    WHITE,
    Point,
    Problem,
    ProblemError,
    ResultClass,
    Solution,
    gtp_coord,
    opponent,
    problem_with_stones,
)
from katrain.core.tsumego_solver.reference import ReferenceSolver, SolverLimits, SolverTimeout

try:
    from katrain.core.tsumego_solver.native import NativeSolver, native_available
except Exception:  # DLL ロード失敗等はネイティブ無しとして扱う
    NativeSolver = None

    def native_available():
        return False


DEFAULT_SETTINGS = {
    # §9.3 の設定キー（tsumego_capture セクション）
    "solver_enabled": True,
    "solver_time_limit_ms": 3000,
    "solver_node_limit": 20000000,
    "solver_ko_refine": True,
    "solver_ko_budget_max": 2,
    "solver_optimize_line": True,
    "solver_max_alternatives": 8,
    "solver_max_region_points": 72,
    "solver_cache": True,
    "solver_fallback": True,
}


def solver_limits_from_settings(settings: dict) -> SolverLimits:
    get = lambda k: settings.get(k, DEFAULT_SETTINGS[k])  # noqa: E731
    return SolverLimits(
        node_limit=int(get("solver_node_limit")),
        time_limit_ms=float(get("solver_time_limit_ms")),
        optimize_line=bool(get("solver_optimize_line")),
        ko_refine=bool(get("solver_ko_refine")),
        ko_budget_max=int(get("solver_ko_budget_max")),
        max_alternatives=int(get("solver_max_alternatives")),
    )


class TsumegoSolverSession:
    """1つの詰碁（キャプチャ1回）に対応するソルバセッション。

    出題時に確定した Problem を保持し、手番ごとに現局面へ差し替えて解く。
    盤面の同期は自前の Board で行い、実対局のコウ禁止点も自前で追跡する。
    """

    def __init__(self, problem: Problem, settings: dict, logger: Optional[Callable] = None):
        self.problem = problem
        self.settings = dict(settings or {})
        self.log = logger or (lambda msg, level=None: None)
        self.limits = solver_limits_from_settings(self.settings)
        self.board = board_from_stones(problem.size, problem.black - problem.fill_black, problem.white - problem.fill_white)
        self.applied_moves: List[Tuple[Optional[Point], str]] = []
        self.ban_point: Optional[Point] = None  # 直前の着手が作った実対局のコウ禁止点
        self.last_solution: Optional[Solution] = None
        self.kernel = None  # ネイティブの証明ストア（TT）を手番をまたいで温存する（§6.6 / G4）
        self._kernel_failed = False
        self.region_hint = None  # 再抽出用（build_session_from_game が設定）
        self._needs_reextract = False  # 着手が region の外に出た（§9.1 → 問題を再抽出）
        # 再抽出後の problem は現局面の石を含む（=applied_moves の一部が焼き込まれる）。
        # カーネル再生成時の二重適用と巻き戻し時の盤復元のために基点を持つ
        self._original_problem = problem
        self._root_black = frozenset(problem.black - problem.fill_black)
        self._root_white = frozenset(problem.white - problem.fill_white)
        self._baked_moves = 0
        import threading

        self._lock = threading.Lock()  # 投機 solve（キャプチャ直後）と手番の solve の直列化

    def _get_kernel(self):
        if self._kernel_failed or NativeSolver is None or not native_available():
            return None
        if self.kernel is None:
            try:
                from katrain.core.tsumego_solver.native import NativeKernel

                kernel = NativeKernel(self.problem)
                # 遅延生成でも局面を追いつかせる（再抽出後の problem には _baked_moves 手ぶんの
                # 石が焼き込まれているので、その先だけを適用する）
                for coords, player in self.applied_moves[self._baked_moves :]:
                    kernel.play(coords, player)
                self.kernel = kernel
            except Exception as e:
                self.log(f"tsumego_solver: ネイティブカーネル初期化に失敗（{e}）。参照実装を使います", "info")
                self._kernel_failed = True
                return None
        return self.kernel

    def _drop_kernel(self):
        if self.kernel is not None:
            try:
                self.kernel.close()
            except Exception:
                pass
            self.kernel = None

    # ---- 盤面同期 ----

    def sync_moves(self, moves: List[Tuple[Optional[Point], str]]):
        """root からの着手列（(coords, player) のリスト。coords=None はパス）に同期する。"""
        if moves[: len(self.applied_moves)] != self.applied_moves:
            # 待ったなどで手順が巻き戻った → 元の問題・盤・カーネルへ戻して全適用
            self.problem = self._original_problem
            self.board = board_from_stones(self.problem.size, self._root_black, self._root_white)
            self.applied_moves = []
            self.ban_point = None
            self._baked_moves = 0
            self._needs_reextract = False
            self._drop_kernel()
        for coords, player in moves[len(self.applied_moves) :]:
            self._apply(coords, player)

    def _apply(self, coords: Optional[Point], player: str):
        self.ban_point = None
        legal = True
        if coords is not None and coords not in self.problem.region:
            # 着手が region の外＝問題の想定より戦いが広い → 次の solve 前に再抽出（§9.1）
            self._needs_reextract = True
            self.log(f"tsumego_solver: 着手 {gtp_coord(coords)} が region の外。問題を再抽出します", "info")
        if coords is not None:
            u = self.board.try_play(self.board.index(coords), player)
            if u is None:
                legal = False
                self.log(f"tsumego_solver: 同期中の非合法手 {coords} を無視します", "info")
            elif len(u.captured) == 1:
                stones, libs = self.board.chain(self.board.index(coords))
                if len(stones) == 1 and len(libs) == 1 and next(iter(libs)) == u.captured[0]:
                    self.ban_point = self.board.point(u.captured[0])
        if legal and self.kernel is not None:
            try:
                if not self.kernel.play(coords, player):
                    self._drop_kernel()  # カーネル側で非合法 = 盤面がずれた → 作り直し
            except Exception:
                self._drop_kernel()
        self.applied_moves.append((coords, player))

    def current_stones(self):
        blk = {self.board.point(p) for p in range(len(self.board.stones)) if self.board.stones[p] == BLACK}
        wht = {self.board.point(p) for p in range(len(self.board.stones)) if self.board.stones[p] == WHITE}
        return blk, wht

    # ---- 着手生成 ----

    def presolve(self):
        """キャプチャ直後の投機実行（§8.3-7）: GUI 描画と並行して root を解き、
        証明ストア（カーネルの TT）を温めておく。結果は捨ててよい（手番の solve が速くなる）。"""
        try:
            with self._lock:
                self._generate_locked()
        except Exception as e:
            self.log(f"tsumego_solver: 投機実行でエラー（{e}）。手番で解き直します", "info")

    def generate(self) -> Tuple[Optional[Point], str]:
        with self._lock:
            return self._generate_locked()

    def _cache_path(self):
        import hashlib
        import os

        payload = repr(
            (
                self.problem.size,
                sorted(self.problem.black),
                sorted(self.problem.white),
                sorted(self.problem.region),
                sorted(self.problem.target),
                self.problem.to_play,
                self.problem.problem_type.value,
                self.applied_moves,
            )
        ).encode()
        digest = hashlib.sha1(payload).hexdigest()
        folder = os.path.expanduser("~/.katrain/tsumego_cache")
        return os.path.join(folder, f"{digest}.json")

    def _generate_locked(self) -> Tuple[Optional[Point], str]:
        """現局面の解答を返す。(coords, 説明)。解けなければ (None, 理由) …パスとの区別は
        説明文字列が 'FALLBACK:' で始まるかで行う。"""
        import json
        import os

        use_cache = bool(self.settings.get("solver_cache", DEFAULT_SETTINGS["solver_cache"]))
        cache_path = self._cache_path() if use_cache else None
        if cache_path and os.path.exists(cache_path):
            try:
                data = json.load(open(cache_path, encoding="utf-8"))
                coords = tuple(data["move"]) if data.get("move") else None
                if coords != self.ban_point or coords is None:
                    self.log(f"tsumego_solver: 永続キャッシュにヒット（{data.get('summary', '')}）", "info")
                    return coords, f"キャッシュ: {data.get('summary', '')}"
            except Exception:
                pass  # 壊れたキャッシュは無視して解き直す
        blk, wht = self.current_stones()
        if self._needs_reextract:
            try:
                new_problem = extract_problem(
                    stones=(blk, wht),
                    board_size=self.problem.size,
                    to_play=self.problem.to_play,
                    region_hint=self.region_hint,
                    max_region_points=int(
                        self.settings.get("solver_max_region_points", DEFAULT_SETTINGS["solver_max_region_points"])
                    ),
                )
                self.log(
                    f"tsumego_solver: 再抽出 type={new_problem.problem_type.value}"
                    f" target={len(new_problem.target)}子 region={len(new_problem.region)}点",
                    "info",
                )
                self.problem = new_problem
                self._baked_moves = len(self.applied_moves)  # 現局面の石は problem に焼き込み済み
                self._drop_kernel()  # region/target が変わったので証明ストアは作り直し
                self._needs_reextract = False
            except ProblemError as e:
                self.log(f"tsumego_solver: 再抽出に失敗（{e}）。フォールバックします", "info")
                return None, f"FALLBACK: 再抽出失敗 {e}"
        problem_now = problem_with_stones(self.problem, blk, wht)
        kernel = self._get_kernel()
        t0 = time.time()
        try:
            if kernel is not None:
                solution = NativeSolver(problem_now, self.limits, kernel=kernel).solve()
            else:
                solution = ReferenceSolver(problem_now, self.limits).solve()
        except SolverTimeout:
            self.log(
                f"tsumego_solver: 未解決（時間/ノード制限）。現行経路へフォールバックします "
                f"[{time.time() - t0:.1f}s]",
                "info",
            )
            return None, "FALLBACK: ソルバ未解決（打ち切り）"
        except Exception as e:  # ネイティブ側の想定外エラーでも対局を止めない（G5）
            self.log(f"tsumego_solver: ソルバ実行エラー {e}。フォールバックします", "error")
            return None, f"FALLBACK: ソルバ実行エラー {e}"
        self.last_solution = solution
        elapsed = time.time() - t0
        backend = "native" if kernel is not None else "reference"
        summary = (
            f"class={solution.value.result.name} ko_level={solution.value.ko_level}"
            f" plies={solution.value.plies} mat={solution.value.material}"
            f" komaster={solution.komaster} taint={solution.cycle_tainted}"
            f" nodes={solution.nodes} [{elapsed:.1f}s {backend}]"
        )
        self.log(
            f"tsumego_solver: {summary} 本手={[gtp_coord(m) for m in solution.root_moves]}"
            f" 手順={[gtp_coord(m) for m in solution.principal_line[:8]]}",
            "info",
        )
        if solution.value.result == ResultClass.FAILED:
            # この詰碁は（この型・target では）解けない ＝ 詰碁側/認識側の問題（§9.2）
            self.log("tsumego_solver: ソルバは FAILED（解無し）と裁定。現行経路へフォールバックします", "info")
            return None, "FALLBACK: ソルバ裁定 FAILED"
        # 実対局のコウ禁止に当たる手は打たない（§9.1）
        for move in solution.root_moves:
            if move is None:
                self._cache_store(cache_path, None, summary)
                return None, f"パスが本手（{summary}）"
            if move == self.ban_point:
                self.log(f"tsumego_solver: 本手 {gtp_coord(move)} は実対局のコウ禁止。コウ待ちします", "info")
                continue
            self._cache_store(cache_path, move, summary)
            return move, f"{summary} 手順={[gtp_coord(m) for m in solution.principal_line[:8]]}"
        # 同格の手が全部コウ禁止（実用上ほぼ来ない）→ パスでコウ待ち
        self.log("tsumego_solver: 同格の本手が全てコウ禁止のためパスします（コウ待ち）", "info")
        return None, f"コウ待ちのパス（{summary}）"

    def _cache_store(self, cache_path, move, summary):
        """root Solution の永続キャッシュ（§6.6。同じ詰碁の再出題で 0 秒）。"""
        if not cache_path:
            return
        import json
        import os

        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"move": list(move) if move else None, "summary": summary}, f, ensure_ascii=False)
        except Exception:
            pass  # キャッシュ書き込み失敗は無害


def build_session_from_game(game, settings: dict, logger=None) -> Optional[TsumegoSolverSession]:
    """ゲームの初期配置（root の placements）から Problem を抽出してセッションを作る。

    キャプチャ経路が事前に抽出済みの Problem を game.tsumego_solver_problem に
    置いていればそれを使う。失敗は None（→ フォールバック）。
    """
    problem = getattr(game, "tsumego_solver_problem", None)
    if problem is None:
        try:
            root = game.root
            black = {m.coords for m in root.placements if m.player == "B" and m.coords}
            white = {m.coords for m in root.placements if m.player == "W" and m.coords}
            hint = game.region_of_interest if getattr(game, "region_of_interest", None) else None
            problem = extract_problem(
                stones=(black, white),
                board_size=game.board_size,
                to_play="B",
                region_hint=hint,
                max_region_points=int(
                    (settings or {}).get("solver_max_region_points", DEFAULT_SETTINGS["solver_max_region_points"])
                ),
            )
        except ProblemError as e:
            if logger:
                logger(f"tsumego_solver: 問題を抽出できません（{e}）。現行経路へフォールバックします", "info")
            return None
    session = TsumegoSolverSession(problem, settings, logger)
    if logger:
        logger(
            f"tsumego_solver: 問題を抽出 type={problem.problem_type.value} target={len(problem.target)}子"
            f" region={len(problem.region)}点 target_color={problem.target_color}",
            "info",
        )
    return session


def moves_from_game(game) -> List[Tuple[Optional[Point], str]]:
    """root から現局面までの着手列。"""
    nodes = []
    node = game.current_node
    while node is not None and node.parent is not None:
        if node.move is not None:
            nodes.append((node.move.coords, node.move.player))
        node = node.parent
    return list(reversed(nodes))
