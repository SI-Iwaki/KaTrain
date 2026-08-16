"""ネイティブ（Rust）ソルバカーネルの ctypes ラッパと NativeSolver。

分類ラダー・root 全手評価・コウ細分の編成は ReferenceSolver（Python）のまま、
重い solve_after / optimize_after だけを Rust カーネルへ差し替える。
DLL が無い環境では ReferenceSolver がそのまま使われる（G5: 参照実装で動く）。

ビルド: cd native/tsumego && cargo build --release --target x86_64-pc-windows-gnu
       → katrain/core/tsumego_solver/katrain_tsumego.dll へコピー
"""

import ctypes
import json
import os
import time
from typing import Optional, Tuple

from katrain.core.tsumego_solver.model import Problem, ProblemType
from katrain.core.tsumego_solver.reference import ReferenceSolver, SolverLimits, SolverTimeout

_DLL_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "katrain_tsumego.dll"),
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        *[".."] * 3,
        "native",
        "tsumego",
        "target",
        "x86_64-pc-windows-gnu",
        "release",
        "katrain_tsumego.dll",
    ),
]

_lib = None

# 第2段階（plies/material 最適化）の時間上限を決める純関数（NativeSolver.OPT_TIME_MS の実体）。
OPT_TIME_MIN_MS = 3000.0
OPT_TIME_MAX_MS = 30000.0
# 「全体予算の10%（3〜30秒）」の下限 3000ms は**短い予算では下限として効きすぎる**:
# GUI 実効の 5000ms 予算では opt 1本に 3000ms＝予算の60% を渡していた。opt はクラス・本手を
# 変えない劣化可能な段階（§4.2.2）なので、予算に対する取り分に上限を掛ける。
OPT_TIME_BUDGET_FRACTION = 0.3


def opt_time_budget_ms(time_limit_ms: float) -> float:
    """opt 1本に渡す時間上限[ms]。

    `min(現行式, FRACTION * 予算)` ＝**締める側にしか動かない**ので、予算 10000ms 以上
    （P1 スイートの 300000ms・テストの 60000ms 等）では現行と同一式になる＝校正ランと
    既存テストの挙動は変わらない。効くのは GUI の 5000ms と出題前検算の 1000ms だけ。

    実測 2026-08-16（ソルバ経路の実問題 134 問・5000ms 予算・native・コールド／
    `calibration-data/tsumego/opt_budget_probe.py`）:
      - 現行は総所要 452.6 秒のうち **opt が 247.9 秒＝55%**、opt 108 回のうち **90 回が
        タイムアウト**、解けた 114 問のうち **103 問が plies=0**（＝opt の成果ゼロ）
      - opt が**成功した**のは 12 問だけで所要は **最大 989ms・中央値 19ms** ＝ 上限
        1000ms 以上なら成功 opt を1つも切らない
      - FRACTION=0.3（＝1500ms・成功 opt に 1.5 倍の余裕）で総所要 452.6 → **335.7 秒**
        （−26%・1問あたり 3.38 → 2.51 秒）、**134問すべてでクラス・`root_moves` の全リスト・
        plies・material が完全一致**（差はログ用 `principal_line` のみ）
      - 同条件の2本目（base2）は 134問すべて差分ゼロ＝この A/B に run 間ノイズは無い
    参考: `solver_opt_skip_after_ms`（第1段階が遅かったら opt を省くゲート）は同じ実測で
    −3.8% しか効かない。燃えているのは stage1 が**速い**問題（実測 0dffe0bd: stage1 140ms →
    opt 3005ms タイムアウト → plies=0）で、stage1 の遅さを見るゲートでは原理的に捕まらない。
    """
    base = min(OPT_TIME_MAX_MS, max(OPT_TIME_MIN_MS, time_limit_ms * 0.1))
    return min(base, OPT_TIME_BUDGET_FRACTION * time_limit_ms)


def load_native():
    """DLL をロードして ctypes ライブラリを返す。無ければ None。"""
    global _lib
    if _lib is not None:
        return _lib
    for path in _DLL_CANDIDATES:
        path = os.path.normpath(path)
        if not os.path.exists(path):
            continue
        try:
            lib = ctypes.CDLL(path)
        except OSError:
            continue
        lib.ts_new.argtypes = [ctypes.c_char_p]
        lib.ts_new.restype = ctypes.c_uint64
        lib.ts_call.argtypes = [ctypes.c_uint64, ctypes.c_char_p]
        lib.ts_call.restype = ctypes.c_void_p
        lib.ts_free_str.argtypes = [ctypes.c_void_p]
        lib.ts_free_str.restype = None
        lib.ts_drop.argtypes = [ctypes.c_uint64]
        lib.ts_drop.restype = None
        _lib = lib
        return lib
    return None


def native_available() -> bool:
    return load_native() is not None


class NativeKernel:
    def __init__(self, problem: Problem):
        lib = load_native()
        if lib is None:
            raise RuntimeError("native solver DLL not found")
        self.lib = lib
        payload = dict(
            width=problem.size[0],
            height=problem.size[1],
            black=sorted(problem.black),
            white=sorted(problem.white),
            region=sorted(problem.region),
            to_play=problem.to_play,
            target=sorted(problem.target),
            own_target=sorted(problem.own_target),
            target_color=problem.target_color,
        )
        self.handle = lib.ts_new(json.dumps(payload).encode())
        if not self.handle:
            raise RuntimeError("native solver init failed")

    def call(self, request: dict) -> dict:
        raw = self.lib.ts_call(self.handle, json.dumps(request).encode())
        try:
            text = ctypes.string_at(raw).decode()
        finally:
            self.lib.ts_free_str(raw)
        result = json.loads(text)
        if "error" in result:
            raise RuntimeError(f"native solver error: {result['error']}")
        return result

    def play(self, coords, player: str) -> bool:
        """root を1手進める（TT 温存。§6.6 証明ストア → 2手目以降の高速化）。"""
        result = self.call(dict(op="play", first_move="pass" if coords is None else list(coords), color=player))
        return bool(result.get("ok"))

    def probe(self, gate):
        """証明ストア照会（§6.6 応答フロー）。ミスは None、ヒットは ("hit", 座標|None=パス)。"""
        pred, komaster, budget, want = gate
        result = self.call(
            dict(op="probe", pred=pred, komaster=komaster, budget=-1 if budget is None else budget, want=want)
        )
        if not result.get("hit"):
            return None
        move = result.get("move")
        return ("hit", None if move in (None, "pass") else tuple(move))

    def close(self):
        if self.handle:
            self.lib.ts_drop(self.handle)
            self.handle = 0

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class NativeSolver(ReferenceSolver):
    """solve_after / optimize_after をネイティブに差し替えた ReferenceSolver。"""

    OPT_NODE_LIMIT_NATIVE = 4_000_000
    # 第2段階（plies/material 最適化）の時間上限。超えたら第1段階の解のまま（§4.2.2）。
    # 全体予算の10%（3〜30秒、ただし予算の 30% まで）: 短い予算では早々に諦め、長予算の
    # 校正ランでは同格タイ（別解の順位づけ）まで解き切る。実体と実測は `opt_time_budget_ms`

    @property
    def OPT_TIME_MS(self):
        return opt_time_budget_ms(self.limits.time_limit_ms)

    def __init__(self, problem: Problem, limits: Optional[SolverLimits] = None, kernel: Optional[NativeKernel] = None):
        super().__init__(problem, limits)
        # kernel を渡すと既存の証明ストア（TT）ごと使い回す（§6.6。呼び出し側が
        # kernel.play で盤面を同じ局面まで進めておく責任を持つ）
        self.kernel = kernel if kernel is not None else NativeKernel(problem)
        self.native_nodes = 0

    def _remaining_ms(self) -> Optional[float]:
        if self.deadline is None:
            return None
        return max(1.0, (self.deadline - time.time()) * 1000.0)

    def _fm(self, move):
        if move is None:
            return "pass"
        x, y = self.board.point(move)
        return [x, y]

    def _solve_after_move(self, move, pred, komaster, budget) -> Tuple[bool, bool]:
        req = dict(
            op="solve",
            pred=pred,
            komaster=komaster,
            budget=-1 if budget is None else budget,
            first_move=self._fm(move),
            node_limit=self.limits.node_limit,
        )
        remaining = self._remaining_ms()
        if remaining is not None:
            req["time_limit_ms"] = int(remaining)
        result = self.kernel.call(req)
        if result.get("timeout"):
            raise SolverTimeout("native solve timeout")
        self.native_nodes += result.get("nodes", 0)
        self.nodes = self.native_nodes
        if result.get("taint"):
            self.taint_any = True
        return bool(result["value"]), bool(result.get("taint"))

    def _optimize_after(self, move, info):
        pred, komaster, want = info["pred"], info["komaster"], info["want"]
        budget = info["ko_level"] if info["result"].name == "KO" else None
        if budget is not None and budget > self.limits.ko_budget_max:
            budget = None
        req = dict(
            op="optimize",
            pred=pred,
            komaster=komaster,
            budget=-1 if budget is None else budget,
            want=want,
            first_move=self._fm(move),
            node_limit=self.limits.node_limit,
            opt_node_limit=self.OPT_NODE_LIMIT_NATIVE,
        )
        remaining = self._remaining_ms()
        req["time_limit_ms"] = int(min(self.OPT_TIME_MS, remaining) if remaining is not None else self.OPT_TIME_MS)
        result = self.kernel.call(req)
        if result.get("timeout"):
            raise SolverTimeout("native optimize timeout")
        line = [None if pt is None else self.board.index(tuple(pt)) for pt in result["line"]]
        return result["plies"], result["material"], line
