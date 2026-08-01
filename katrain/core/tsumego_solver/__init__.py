"""詰碁専用 死活ソルバ（設計: docs/superpowers/specs/2026-08-01-tsumego-solver-design.md）。

KataGo・Kivy 非依存の純 Python 参照実装。ネイティブ（Rust）実装が入るまでは
これが本実装を兼ねる。公開 API:

    from katrain.core.tsumego_solver import solve_problem, ResultClass, Goal
    solution = solve_problem(problem)
"""

from katrain.core.tsumego_solver.model import (
    BLACK,
    WHITE,
    EMPTY,
    Goal,
    ProblemType,
    Problem,
    ProblemError,
    ResultClass,
    SolutionValue,
    Solution,
    RESULT_ORDER,
    result_sort_key,
)
from katrain.core.tsumego_solver.reference import ReferenceSolver, SolverLimits, SolverTimeout, solve_problem

__all__ = [
    "BLACK",
    "WHITE",
    "EMPTY",
    "Goal",
    "ProblemType",
    "Problem",
    "ProblemError",
    "ResultClass",
    "SolutionValue",
    "Solution",
    "RESULT_ORDER",
    "result_sort_key",
    "ReferenceSolver",
    "SolverLimits",
    "SolverTimeout",
    "solve_problem",
]
