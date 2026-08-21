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
from katrain.core.tsumego_solver.reference import ReferenceSolver, SolverLimits, SolverTimeout, ladder_steps

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
    # 第1段階（分類）がこれより遅かったら第2段階（plies/material 最適化）を省く
    # （SolverLimits.opt_skip_after_ms 参照。難問では opt が予算3秒を燃やして成果ゼロだった）
    "solver_opt_skip_after_ms": 5000,
    # 出題前の検算（problem_is_hopeless）に使う時間予算[ms]。0 以下で検算しない。
    # 壊れた抽出の FAILED は探索するものが無いぶん速く証明される（実測 case AD 0.01s /
    # case F 0.19s / case F2 0.10s）ので、最遅 0.19s の約5倍を取る。予算切れは「間違いとは
    # 言えない」＝従来どおり出題なので、外し方は現状維持。解ける問題（D/E/K/O/Q/V/V2）は
    # 予算内に終わらないためこの秒数がキャプチャに乗る＝上げるほど遅くなる
    "solver_verdict_ms": 1000,
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
        opt_skip_after_ms=float(get("solver_opt_skip_after_ms")),
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
        # 再抽出用の関心領域。出題時の region の外接矩形を既定にする（GUI 経路は
        # build_session_from_game が game.region_of_interest で上書きする）。
        # None のまま再抽出すると「石で閉じない盤」の矩形 region モード（追記1-9）が使えず、
        # 途中局面では閉包がデタラメな小領域に「成功」して別の問題を解いてしまう（実測 2026-08-01
        # case 1: ply8 の hint なし再抽出が target={K2,K4,K5}/region10点 を作り SEKI/L1 と誤答）
        self.region_hint = self._problem_hint(problem)
        self._needs_reextract = False  # 着手が region の外に出た（§9.1 → 問題を再抽出）
        # 再抽出後の problem は現局面の石を含む（=applied_moves の一部が焼き込まれる）。
        # カーネル再生成時の二重適用と巻き戻し時の盤復元のために基点を持つ
        self._original_problem = problem
        self._root_black = frozenset(problem.black - problem.fill_black)
        self._root_white = frozenset(problem.white - problem.fill_white)
        self._baked_moves = 0
        self.last_gate = None  # 前回 solve の証明コンテキスト（証明ストア即答のキー。§6.6）
        self._gave_up = False  # 予算内に解けないと判明した問題（以後は即フォールバック）
        # root スキャンの順序ヒント（§6.2・ソルバ設計スペック追記5）: KataGo policy の上位から
        # 評価すると正解が早く incumbent になり floor 刈りが効く。provider はキャプチャ経路が
        # 渡す「今すぐ取れる候補列を返す/まだ無ければ None」の非ブロッキング関数
        self.policy_hint_provider: Optional[Callable[[], Optional[List[Point]]]] = None
        self._policy_hint: Optional[List[Point]] = None
        import threading

        self._lock = threading.Lock()  # 投機 solve（キャプチャ直後）と手番の solve の直列化

    @staticmethod
    def _problem_hint(problem):
        """problem.region の外接矩形 [xmin, xmax, ymin, ymax]（再抽出のフォールバック用）。"""
        if not problem.region:
            return None
        xs = [p[0] for p in problem.region]
        ys = [p[1] for p in problem.region]
        return [min(xs), max(xs), min(ys), max(ys)]

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
            self.last_gate = None
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

    # 投機実行が KataGo の順序ヒント（クイック解析 300visits・実測 0.4〜1.0 秒で到着）を
    # 待つ上限。ヒント無しの solve を始めてしまうと静的順序で急所を後回しにしたぶんが
    # 丸ごと無駄になる（実測 2026-08-02: region22 のコウ詰碁で 17.3 vs 12.1 秒）ので、
    # 短い待ちのほうが期待値で得。上限を超えたら従来どおりヒント無しで解き始める
    HINT_WAIT_S = 1.5

    def presolve(self):
        """キャプチャ直後の投機実行（§8.3-7）: GUI 描画と並行して root を解き、
        証明ストア（カーネルの TT）を温めておく。結果は捨ててよい（手番の solve が速くなる）。"""
        try:
            provider = self.policy_hint_provider
            if provider is not None:
                deadline = time.time() + self.HINT_WAIT_S
                while time.time() < deadline:
                    try:
                        hint = provider()
                    except Exception:
                        break
                    if hint:
                        self._policy_hint = list(hint)
                        break
                    time.sleep(0.05)
            with self._lock:
                self._generate_locked()
        except Exception as e:
            self.log(f"tsumego_solver: 投機実行でエラー（{e}）。手番で解き直します", "info")

    def generate(self) -> Tuple[Optional[Point], str]:
        with self._lock:
            return self._generate_locked()

    def _root_order_hint(self) -> Optional[List[Point]]:
        """root スキャンの順序ヒント（KataGo の読み順。無ければ None＝従来の静的順序）。

        手番の solve では戦略が渡す move_visits（現局面のリージョン解析の visits）を降順で使う。
        投機実行（キャプチャ直後＝着手ゼロの root 局面）だけは capture 側 provider のクイック
        解析候補を使う（途中局面では盤が違うので流用しない）。ヒントは順序だけを変え、
        候補の集合・評価・採否は変えない（reference.solve() の root_order_hint 参照）。
        """
        visits_map = getattr(self, "move_visits", None)
        if visits_map:
            try:
                pts = [pt for pt, _v in sorted(visits_map.items(), key=lambda kv: -kv[1])]
                if pts:
                    return pts
            except Exception:
                pass
        if self._policy_hint and not self.applied_moves:
            return list(self._policy_hint)
        return None

    # 永続キャッシュの版数。答えの決まり方が変わったら上げて旧エントリを無効化する。
    # 2: 証明ストア即答にクラス格上げ確認を追加（case AB）。旧版は KO gate の決め手を
    #    そのまま保存しており、上位クラスが成立する局面の誤答（N11）が焼き付いている
    # 3: 同格別解リスト（alternatives）を保存し、ヒット時に現セッションの KataGo 本命順で
    #    並べ替える（fresh solve と同じ §6.5.1-3 タイブレークの遅延適用）。旧版は
    #    **KataGo ランキング無しのセッション**（キャプチャ時の投機実行など）が最初に証明
    #    できた手を1手だけ焼き付け、以後の全セッションがタイブレークを素通りしていた
    #    （実測 2026-08-15 回答帳 13333f79df: E2/C3/D2 が同格の無条件殺しで、投機実行が
    #    E2 を保存 → 本番は KataGo 本命 D2(v1145) vs E2(v155) なのに E2 を即答して誤答）
    CACHE_VERSION = 3

    def _cache_path(self):
        import hashlib
        import os

        payload = repr(
            (
                self.CACHE_VERSION,
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

        blk, wht = self.current_stones()
        # 再抽出（§9.1）はキャッシュ照会より先に済ませる。キャッシュのキーは「実際に解く問題」で
        # 引かないと、再抽出後の解が元問題のキーで保存され、以後のセッションが別問題の答えを
        # 即答してしまう（実測 2026-08-01 case 1: SEKI/L1 の汚染エントリ）
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
                # サニティガード: 元問題の target のうち今も盤上に生きている石を、再抽出後の
                # region が全て覆っていること。途中局面の閉包は乱れた盤で「別の小さな問題」に
                # 成功しうる（実測 case 1 ply8: target={K2,K4,K5}/region10点 → SEKI/L1 と誤答）。
                # 覆えていない再抽出は信用せずフォールバックする
                orig = self._original_problem
                alive_targets = {
                    pt for pt in orig.target if self.board.stones[self.board.index(pt)] == orig.target_color
                }
                missing = alive_targets - set(new_problem.region)
                if missing:
                    self.log(
                        f"tsumego_solver: 再抽出の region が生存 target を覆っていません"
                        f"（{[gtp_coord(p) for p in sorted(missing)][:5]}）。フォールバックします",
                        "info",
                    )
                    return None, "FALLBACK: 再抽出が対象を見失った"
                self.log(
                    f"tsumego_solver: 再抽出 type={new_problem.problem_type.value}"
                    f" target={len(new_problem.target)}子 region={len(new_problem.region)}点",
                    "info",
                )
                self.problem = new_problem
                self._baked_moves = len(self.applied_moves)  # 現局面の石は problem に焼き込み済み
                self._drop_kernel()  # region/target が変わったので証明ストアは作り直し
                self._needs_reextract = False
                self.last_gate = None
                self._gave_up = False  # 問題が変わった（小さくなったかもしれない）ので解き直す
            except ProblemError as e:
                self.log(f"tsumego_solver: 再抽出に失敗（{e}）。フォールバックします", "info")
                return None, f"FALLBACK: 再抽出失敗 {e}"
        use_cache = bool(self.settings.get("solver_cache", DEFAULT_SETTINGS["solver_cache"]))
        cache_path = self._cache_path() if use_cache else None
        if cache_path and os.path.exists(cache_path):
            try:
                data = json.load(open(cache_path, encoding="utf-8"))
                coords = tuple(data["move"]) if data.get("move") else None
                # 同格別解のタイブレークはヒット時に現セッションの KataGo 順で適用する
                # （fresh solve の §6.5.1-3 並べ替えの遅延版。保存時のランキングは投機実行
                # など解析の無いセッションだと存在せず、決め手を1手だけ信じると
                # アプリの解答樹の本手（KataGo 本命と一致しやすい）から外れる）
                alts = [tuple(a) for a in (data.get("alternatives") or [])]
                ranker = getattr(self, "move_ranker", None)
                if coords is not None and ranker is not None and len(alts) >= 2:
                    try:
                        for pt in sorted(alts, key=lambda p: ranker(p)):
                            if pt == self.ban_point or self.board.stones[self.board.index(pt)] != EMPTY:
                                continue
                            if pt != coords:
                                self.log(
                                    f"tsumego_solver: キャッシュの同格別解 "
                                    f"{[gtp_coord(a) for a in alts]} を KataGo policy で並べ替え"
                                    f" → {gtp_coord(pt)}（保存時の決め手 {gtp_coord(coords)}）",
                                    "info",
                                )
                            coords = pt
                            break
                    except Exception:
                        pass  # 並べ替えは最適化であって正しさの条件ではない
                if coords != self.ban_point or coords is None:
                    self.log(f"tsumego_solver: 永続キャッシュにヒット（{data.get('summary', '')}）", "info")
                    return coords, f"キャッシュ: {data.get('summary', '')}"
            except Exception:
                pass  # 壊れたキャッシュは無視して解き直す
        # 一度「この問題は予算内に解けない」と分かったら以後は即フォールバック
        # （毎手 solver_time_limit_ms を燃やしてからフォールバックすると現行より遅くなる）
        if getattr(self, "_gave_up", False):
            return None, "FALLBACK: この問題は予算内に解けない（既知）"
        # 証明ストア即答（§6.6 応答フロー / G4）: 前回の solve が確定させたコンテキストで
        # 現局面が証明済みなら、解析ゼロで決め手を返す（< 10ms）。ミスなら通常の solve へ。
        # ただし gate は「そのクラスで解ける」証明にすぎない。相手が最強防御を外すと上位クラスが
        # 成立しうる（実測 2026-08-02 case AB・13路右上: root は W L12 の最強防御でコウ殺しのみ
        # ＝class=KO が正しいが、白が N12 と受けた局面には無条件殺し M13 がある。KO gate の
        # probe は同格の決め手 N11＝コウ手を返し、詰碁の順序 無条件 > コウ で誤答）。
        # 現 gate が型の最上位クラスでないときは上位ゲートを先に照会し、ヒットすれば格上げ、
        # ミスなら通常の solve で再分類する。再分類が打ち切られたときだけ従来の即答へ退避する
        # （_gave_up にはしない＝クラス確定済みの問題を手放さない）
        last_gate = getattr(self, "last_gate", None)
        probe_fallback = None  # (gate, coords): 格上げ確認の solve 打ち切り時に返す従来の即答
        if last_gate is not None and self.kernel is not None:
            try:
                hit = self.kernel.probe(last_gate)
            except Exception:
                hit = None  # 旧 DLL 等で probe 未対応でも通常経路で動く
            if hit is not None:
                better = self._better_gates(last_gate)
                answer_gate = last_gate if not better else None
                for gate_up in better:
                    try:
                        hit_up = self.kernel.probe(gate_up)
                    except Exception:
                        answer_gate = last_gate  # probe 不能: 格上げ確認は諦めて従来動作
                        break
                    if hit_up is not None:
                        answer_gate, hit = gate_up, hit_up
                        self.last_gate = gate_up
                        self.log(f"tsumego_solver: 証明ストアでクラス格上げ（gate={gate_up}）", "info")
                        break
                if answer_gate is not None:
                    coords = hit[1]
                    if coords is None:
                        self.log("tsumego_solver: 証明ストア即答（パスが本手）", "info")
                        return None, "証明ストア即答: パスが本手"
                    if coords != self.ban_point:
                        # 証明ストアの決め手は df-pn が「最初に証明できた手」で、同格の別解が
                        # 複数ある局面ではアプリの解答樹の本手と限らない（実測 2026-08-01 case 2:
                        # J13/K13/M13 が全部同格で J13 を即答 → アプリは K13 のみ正解）。
                        # KataGo の本命が同じ gate を証明するならそちらを採る（§6.5.1-3 の深いノード版）
                        coords = self._prefer_ranked_gate_move(coords, answer_gate)
                        self.log(f"tsumego_solver: 証明ストア即答 {gtp_coord(coords)}（解析ゼロ）", "info")
                        self._cache_store(cache_path, coords, f"証明ストア即答 {gtp_coord(coords)}")
                        return coords, f"証明ストア即答: {gtp_coord(coords)}"
                    # コウ禁止に当たる場合は通常の solve で別手を探す
                else:
                    # 上位ゲートが証明ストアに無い＝今の局面で上位が成立するかは未知。
                    # 通常の solve で再分類し、打ち切られたらこの即答へ退避する
                    probe_fallback = (last_gate, hit[1])
        problem_now = problem_with_stones(self.problem, blk, wht)
        kernel = self._get_kernel()
        t0 = time.time()
        try:
            if kernel is not None:
                solver = NativeSolver(problem_now, self.limits, kernel=kernel)
            else:
                solver = ReferenceSolver(problem_now, self.limits)
            hint = self._root_order_hint()
            if hint:
                solver.root_order_hint = hint
            solution = solver.solve()
        except SolverTimeout:
            if probe_fallback is not None:
                # 格上げ確認のための再分類だけが打ち切られた（現クラスの証明は生きている）。
                # 従来の即答へ退避する。退避解は格上げ未確認なので永続キャッシュには入れない
                # （次に速く解けたセッションが正しい答えで埋める）
                gate_fb, coords_fb = probe_fallback
                self.log(
                    f"tsumego_solver: 格上げ確認の再分類が打ち切り [{time.time() - t0:.1f}s]。"
                    "現クラスの証明ストア即答へ退避します",
                    "info",
                )
                if coords_fb is None:
                    return None, "証明ストア即答: パスが本手（格上げ確認は打ち切り）"
                if coords_fb != self.ban_point:
                    coords_fb = self._prefer_ranked_gate_move(coords_fb, gate_fb)
                    return coords_fb, f"証明ストア即答: {gtp_coord(coords_fb)}（格上げ確認は打ち切り）"
                # 退避先がコウ禁止に当たる場合だけ従来どおり未解決扱い
            self._gave_up = True  # 以後の手番は即フォールバック（局面が進んでも region 規模は同じ）
            self.log(
                f"tsumego_solver: 未解決（時間/ノード制限）。以後この問題は現行経路へフォールバックします "
                f"[{time.time() - t0:.1f}s]",
                "info",
            )
            return None, "FALLBACK: ソルバ未解決（打ち切り）"
        except Exception as e:  # ネイティブ側の想定外エラーでも対局を止めない（G5）
            self.log(f"tsumego_solver: ソルバ実行エラー {e}。フォールバックします", "error")
            return None, f"FALLBACK: ソルバ実行エラー {e}"
        self.last_solution = solution
        self.last_gate = solution.gate if solution.value.result != ResultClass.FAILED else None
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
        # 同格の別解が複数あり optimize でも順位が付かなかったときの最終タイブレーク:
        # KataGo policy（§6.5.1-3 / §12。呼び出し側が move_ranker を渡したときだけ。
        # アプリの解答樹の本線は KataGo の本命と一致しやすい＝現行 points_epsilon の知見）
        root_moves = list(solution.root_moves)
        ranker = getattr(self, "move_ranker", None)
        if ranker is not None and len(root_moves) > 1 and solution.value.plies == 0:
            try:
                ranked = sorted(root_moves, key=lambda m: ranker(m))
                if ranked != root_moves:
                    self.log(
                        f"tsumego_solver: 同格の別解 {[gtp_coord(m) for m in root_moves]} を"
                        f" KataGo policy で並べ替え → {[gtp_coord(m) for m in ranked]}",
                        "info",
                    )
                root_moves = ranked
            except Exception:
                pass
        # 同格タイ（optimize でも順位が付かなかった複数の本手）はキャッシュにも保存し、
        # ヒット時に現セッションの KataGo 順で並べ替えられるようにする（CACHE_VERSION 3）。
        # このセッションに move_ranker が無くても（投機実行など）、別解の存在自体は
        # ソルバの証明で確定しているので保存してよい
        tie_alts = (
            [m for m in root_moves if m is not None]
            if len(root_moves) > 1 and solution.value.plies == 0
            else None
        )
        # 実対局のコウ禁止に当たる手は打たない（§9.1）
        for move in root_moves:
            if move is None:
                self._cache_store(cache_path, None, summary)
                return None, f"パスが本手（{summary}）"
            if move == self.ban_point:
                self.log(f"tsumego_solver: 本手 {gtp_coord(move)} は実対局のコウ禁止。コウ待ちします", "info")
                continue
            self._cache_store(cache_path, move, summary, alternatives=tie_alts)
            return move, f"{summary} 手順={[gtp_coord(m) for m in solution.principal_line[:8]]}"
        # 同格の手が全部コウ禁止（実用上ほぼ来ない）→ パスでコウ待ち
        self.log("tsumego_solver: 同格の本手が全てコウ禁止のためパスします（コウ待ち）", "info")
        return None, f"コウ待ちのパス（{summary}）"

    def _better_gates(self, gate):
        """現 gate より上位クラスのゲート列（良い順。gate が最上位なら空）。

        型別ラダー（reference.ladder_steps）は best→worst 順なので、gate に一致する step より
        前の step が上位クラス。一致は (pred, komaster, want) で取る（gate の budget には KO 細分の
        n* が入るので比較に使わない）。上位ゲートの budget は None＝分類時と同じ無限 budget
        （証明ストアのエントリは分類の solve が budget=None で書いている）。
        """
        try:
            steps = ladder_steps(self.problem)
        except Exception:
            return []
        better = []
        for _result, _sub, pred, komaster, want in steps:
            if (pred, komaster, want) == (gate[0], gate[1], gate[3]):
                return better
            better.append((pred, komaster, None, want))
        return []  # gate がラダーに無い（想定外）→ 格上げ確認なし＝従来動作

    # KataGo 本命の同格差し替えで検証する候補数と1手あたりの予算。検証は温まった証明ストア上の
    # solve なので実測ミリ秒級（case 2 の K13 はコールドでも 1461 ノード）。タイムアウトは
    # 「証明できなかった」と同じ扱い＝差し替えず決め手を維持（安全側）
    RANK_OVERRIDE_MAX_CANDIDATES = 3
    RANK_OVERRIDE_TIME_MS = 5000
    RANK_OVERRIDE_NODE_LIMIT = 2_000_000
    # 差し替えの決定性ゲート: KataGo 本命の visits が決め手の visits のこの倍以上のときだけ
    # 差し替える。拮抗（実測 case 2 ply4: K13 v874 vs 正解 M13 v779 = 1.1倍）で差し替えると
    # 同格の別解間で手順が入れ替わりアプリの解答樹から外れうる。発火すべき実測は 57 倍
    # （case 2 P6: K13 v1670 vs J13 v29）で、3.0 は両側から十分に離れた位置
    RANK_OVERRIDE_MIN_VISITS_RATIO = 3.0

    def _prefer_ranked_gate_move(self, chosen: Point, gate) -> Point:
        """同格の別解から KataGo の本命を選び直す（§6.5.1-3 の深いノード版）。

        証明ストアの決め手（df-pn が最初に証明した手）より KataGo が**決定的に**上位に読む
        region 内の合法手（visits 比 >= RANK_OVERRIDE_MIN_VISITS_RATIO）が、同じ gate
        （クラスを成立させた solve のコンテキスト）を証明するなら差し替える。
        アプリの解答樹の本線は KataGo の本命と一致しやすい（現行 points_epsilon の知見）。
        move_ranker / move_visits / kernel が無ければ何もしない。
        """
        ranker = getattr(self, "move_ranker", None)
        visits_map = getattr(self, "move_visits", None)
        if ranker is None or visits_map is None or self.kernel is None or gate is None:
            return chosen
        try:
            chosen_rank = ranker(chosen)
            chosen_visits = max(1, int(visits_map.get(chosen, 0)))
            cands = []
            for pt in self.problem.region:
                if pt == chosen or pt == self.ban_point:
                    continue
                if self.board.stones[self.board.index(pt)] != EMPTY:
                    continue
                rank = ranker(pt)
                if rank >= chosen_rank:
                    continue
                if int(visits_map.get(pt, 0)) < chosen_visits * self.RANK_OVERRIDE_MIN_VISITS_RATIO:
                    continue  # 拮抗している別解は入れ替えない（決定的な本命だけ）
                cands.append((rank, pt))
            cands.sort()
            pred, komaster, budget, want = gate
            for _rank, pt in cands[: self.RANK_OVERRIDE_MAX_CANDIDATES]:
                result = self.kernel.call(
                    dict(
                        op="solve",
                        pred=pred,
                        komaster=komaster,
                        budget=-1 if budget is None else budget,
                        first_move=[pt[0], pt[1]],
                        node_limit=self.RANK_OVERRIDE_NODE_LIMIT,
                        time_limit_ms=self.RANK_OVERRIDE_TIME_MS,
                    )
                )
                if result.get("timeout"):
                    continue
                if bool(result.get("value")) == want:
                    self.log(
                        f"tsumego_solver: 決め手 {gtp_coord(chosen)}(v{visits_map.get(chosen, 0)}) より"
                        f" KataGo 本命 {gtp_coord(pt)}(v{visits_map.get(pt, 0)}) が同格に成立するため"
                        f" 差し替えます（gate={gate}）",
                        "info",
                    )
                    return pt
        except Exception:
            pass  # 差し替えは最適化であって正しさの条件ではない。失敗したら決め手のまま
        return chosen

    def _cache_store(self, cache_path, move, summary, alternatives=None):
        """root Solution の永続キャッシュ（§6.6。同じ詰碁の再出題で 0 秒）。

        `alternatives` は同格タイの本手リスト（証明済み・順不同）。ヒット時に現セッションの
        KataGo 順で並べ替えるために保存する。単独の本手・証明ストア即答では None。
        """
        if not cache_path:
            return
        import json
        import os

        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            payload = {"move": list(move) if move else None, "summary": summary}
            if alternatives and len(alternatives) >= 2:
                payload["alternatives"] = [list(m) for m in alternatives]
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception:
            pass  # キャッシュ書き込み失敗は無害


def problem_is_hopeless(problem, settings: dict, logger=None) -> bool:
    """抽出した問題が「手番側は勝てない（FAILED）」と**証明できた**とき True。

    詰碁は手番側に正解手がある問題なので、FAILED はその抽出が元の詰碁と別物である証拠になる
    （枠の採否判定 `frame_destroys_problem` が使っているのと同じ前提）。出題してしまうと
    `analysis_region` が誤った小さい箱に固定され、戦略が FAILED でフォールバックしても
    KataGo は箱の外の正解手を打てない＝救済不能になるので、**出題前に**捨てる。

    実測 2026-08-04 case AD（13路左下）: 抽出は黒6子を D〜G × 5〜7 の 10 点の箱に閉じ込めた
    `type=defend region=10点` を返したが、箱の空点 G5/G6/G7 は全部白の壁石に接していて眼に
    ならず黒は1眼しか作れない（FAILED・0.01s/194nodes）。本当の争点は白 {C6,C7,D5,D6}
    （呼吸点3 = B6/B7/C5）で、正解手順は C5 から始まる＝抽出器が「取れる白」を壁と仮定していた。

    **予算内に決まらなければ False**（＝従来どおり出題する）。判定は「間違いだと証明できたか」で
    あって「正しいと確認できたか」ではないので、分からないときは現状維持に倒す。予算
    `solver_verdict_ms` を短く取れるのは、壊れた抽出の FAILED は探索するものが無いぶん速く
    証明されるため（実測 case AD 0.01s / case F@2 0.1s に対し、解ける問題の solve は 0.0〜12s）。
    解けた場合は永続キャッシュに載るので、その後の投機実行と初手の solve が速くなる。
    """
    budget = float(settings.get("solver_verdict_ms", DEFAULT_SETTINGS["solver_verdict_ms"]))
    if budget <= 0:
        return False
    probe_settings = dict(settings)
    probe_settings["solver_time_limit_ms"] = budget
    try:
        session = TsumegoSolverSession(problem, probe_settings, logger)
        session.presolve()
        solution = getattr(session, "last_solution", None)
    except Exception:
        return False  # 検算そのものが失敗したら従来どおり出題する（G5）
    return solution is not None and solution.value.result == ResultClass.FAILED


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
    # 再抽出用の関心領域は GUI の region_of_interest を優先（無ければ __init__ の
    # region 外接矩形＝`_problem_hint` のまま）。
    #
    # **この分岐は呼ばれた時点で ROI が入っているかに依存する**（挙動の分岐であって
    # 設定ではない）。キャプチャ経路では投機 presolve のスレッド起動（__main__.py:1551）が
    # `_apply_tsumego_region`（同 :1572）より**前**にあるため、presolve が先に読んだ run では
    # ROI=None ＝閉包 bbox の hint でセッションが作られ、そのセッションを ai.py:4960 が
    # 全手番で再利用する。一方オフラインのハーネス（answer_book_replay.py の build_game・
    # generate_move_e2e.py）は先に ROI を設定してから戦略に作らせるので必ず ROI 側になる
    # ＝**本番とハーネスで hint の出所が食い違いうる**。どちらの hint が正しいかは未測定
    # （狭い既定 hint は :95-99 のとおり意図的な安全策で、広げると `_open_rect_problem`
    # 経由で region が膨らむ向きの力も同時に入る）なので、まず出所を観測可能にする。
    # 再抽出は `_needs_reextract`（着手が region の外）のときだけ走るので、この行が
    # 効いてくるのは詰碁ログの中でも稀な手番に限られる
    roi = getattr(game, "region_of_interest", None)
    hint_source = "GUI ROI" if roi else "閉包 bbox（ROI 未設定）"
    if roi:
        session.region_hint = list(roi)
    if logger:
        logger(
            f"tsumego_solver: 問題を抽出 type={problem.problem_type.value} target={len(problem.target)}子"
            f" region={len(problem.region)}点 target_color={problem.target_color}"
            f" 再抽出hint={session.region_hint}（{hint_source}）",
            "info",
        )
    return session


def moves_from_node(node) -> List[Tuple[Optional[Point], str]]:
    """指定ノードから root までを遡った着手列（root→node の順に返す）。"""
    nodes = []
    while node is not None and node.parent is not None:
        if node.move is not None:
            nodes.append((node.move.coords, node.move.player))
        node = node.parent
    return list(reversed(nodes))


def moves_from_game(game) -> List[Tuple[Optional[Point], str]]:
    """root から現局面までの着手列。"""
    return moves_from_node(game.current_node)
