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
    OPT_TIME_MS = 3000.0  # 第2段階（plies/material 最適化）の時間上限。超えたら第1段階の解のまま（§4.2.2）

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
