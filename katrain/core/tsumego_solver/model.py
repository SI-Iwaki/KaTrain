"""ソルバのデータモデル（スペック §4）。KataGo・Kivy 非依存。

座標は KaTrain の Move と同じ (x, y)＝(列, 下からの行) の 0-based タプル。
"""

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import FrozenSet, List, Optional, Tuple

Point = Tuple[int, int]

BLACK = "B"
WHITE = "W"
EMPTY = "."


def opponent(color: str) -> str:
    return WHITE if color == BLACK else BLACK


class Goal(Enum):
    LIVE = "live"  # target を生かす（解く側＝target の色）
    KILL = "kill"  # target を殺す（解く側＝target の敵）
    SEMEAI = "semeai"  # 攻め合い: 相手 target の KILL ∧ 自 target の LIVE（§4.3.2.1）


class ProblemType(Enum):
    DEFEND = "defend"  # 守り（生き）
    ATTACK = "attack"  # 攻め（殺し）
    SEMEAI = "semeai"  # 攻め合い


class ResultClass(IntEnum):
    """小さいほど「解く側にとって上位」…ではない。順序は RESULT_ORDER[type] を通す（§4.2）。"""

    UNCONDITIONAL = 0  # 無条件に目的達成（生き / 死 / 攻め合い勝ち）
    SEKI = 1
    KO = 2
    FAILED = 3


# 型ごとの順序表（§4.2 / §5.2.2）。先頭ほど「解く側にとって上位」。
# 守り方: 無条件生き > セキ > コウ > 死
# 攻め方: 無条件死 > コウ > セキ > 相手の生き
# 攻め合い: 勝ち > コウ > セキ > 負け（負ける＝自石が死ぬので攻めと同順）
RESULT_ORDER = {
    ProblemType.DEFEND: (ResultClass.UNCONDITIONAL, ResultClass.SEKI, ResultClass.KO, ResultClass.FAILED),
    ProblemType.ATTACK: (ResultClass.UNCONDITIONAL, ResultClass.KO, ResultClass.SEKI, ResultClass.FAILED),
    ProblemType.SEMEAI: (ResultClass.UNCONDITIONAL, ResultClass.KO, ResultClass.SEKI, ResultClass.FAILED),
}


@dataclass(frozen=True)
class SolutionValue:
    """解の値（§4.2.1）。比較は sort_key(problem_type) を通す辞書順。

    dataclass(order=True) の素の辞書順は result を IntEnum の生値で比べるので使わない
    （攻め方は コウ > セキ で順序が逆転する）。
    """

    result: ResultClass
    ko_level: int = 0  # コウの深さ n*（§4.4）。非コウは 0
    plies: int = 0  # 決着までの解く側の着手数（§4.2.1。パスは数えない）
    material: int = 0  # 最終盤面で失う自石数（犠打）
    # 同クラス内の下位細目（§4.3.2.1 の「コウでセキ」等）。0=なし、1=下位細目
    sub_demotion: int = 0

    def sort_key(self, problem_type: ProblemType):
        return (
            RESULT_ORDER[problem_type].index(self.result),
            self.sub_demotion,
            self.ko_level,
            self.plies,
            self.material,
        )


@dataclass(frozen=True)
class Problem:
    """ソルバへの入力（§4.1）。region の外は両者とも着手禁止。

    region は点の集合（初期に石がある点も含む）。着手可能 = region 内 かつ 現在空点。
    target は「危険な石」の元の座標の集合（連ではなく点集合。§5.2.3）。
    """

    size: Tuple[int, int]
    black: FrozenSet[Point]
    white: FrozenSet[Point]
    region: FrozenSet[Point]
    to_play: str  # BLACK / WHITE
    target: FrozenSet[Point]
    goal: Goal
    problem_type: ProblemType
    target_color: str  # target の石の色
    # 攻め合い（goal=SEMEAI）のときだけ: 自分側 target（target は相手側=殺す対象）
    own_target: FrozenSet[Point] = frozenset()
    komaster: Optional[str] = None  # 分類時は両方試すので通常 None
    ko_budget: Optional[int] = None
    # 抽出時に「所有者の地」として埋めた点（black/white に含まれている。§5.1 の遠地帯）。
    # 局面差し替え（§9.1）のとき埋め直すために保持する。GUI 表示には使わない
    fill_black: FrozenSet[Point] = frozenset()
    fill_white: FrozenSet[Point] = frozenset()


def problem_with_stones(problem: Problem, black, white) -> Problem:
    """同じ問題コンテキスト（region / target / 型 / 埋め地）のまま局面だけ差し替える（§9.1）。

    相手の着手で局面が進んでも、問題の型・target・region は出題時に確定したものを使う。
    取られた target の元石はソルバ側の live-origin 初期化で自然に落ちる。
    """
    from dataclasses import replace

    return replace(
        problem,
        black=frozenset(black) | problem.fill_black,
        white=frozenset(white) | problem.fill_white,
    )


class ProblemError(Exception):
    """問題抽出の失敗（§5.3）。呼び出し側はこれを見てフォールバックする。"""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason + (f": {detail}" if detail else ""))
        self.reason = reason
        self.detail = detail


@dataclass
class Solution:
    """ソルバの出力（§6.5）。"""

    value: SolutionValue
    komaster: Optional[str]  # どの仮定で成立したか
    alive_by_repetition: bool
    cycle_tainted: bool  # 結論がサイクル裁定に依存（§4.6.1 → 検算対象）
    root_moves: List[Optional[Point]]  # root の同格手すべて（先頭が本手。None=パス）
    principal_line: List[Optional[Point]]  # 本手順（表示・ログ用）
    nodes: int
    elapsed_ms: float
    problem_type: ProblemType = ProblemType.DEFEND
    # 参考情報: root 全手の分類（gtp 座標 -> SolutionValue）。デバッグ・別解確認用
    move_values: dict = field(default_factory=dict)


def result_sort_key(value: SolutionValue, problem_type: ProblemType):
    return value.sort_key(problem_type)


def gtp_coord(point: Optional[Point]) -> str:
    """(x, y) -> GTP 座標（表示・ログ用。I 列は飛ばす）。None はパス。"""
    if point is None:
        return "pass"
    letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
    return letters[point[0]] + str(point[1] + 1)


def from_gtp_coord(gtp: str) -> Optional[Point]:
    gtp = gtp.strip().upper()
    if gtp in ("PASS", ""):
        return None
    letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
    return (letters.index(gtp[0]), int(gtp[1:]) - 1)
