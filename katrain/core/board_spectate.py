"""観戦用の盤面反映モードの純ロジック（Kivy 非依存）。

アプリ側の盤（observed）が KaTrain の本譜の末尾（tip）からどれだけ進んだかを判定する。
"""

import re
from itertools import permutations
from typing import NamedTuple, Optional

from katrain.core.board_watch import BLACK, EMPTY, WHITE, apply_move_to_grid

# これを超える手数の差は並べ替えを試さず、走査順だけ試す
SPECTATE_MAX_PERMUTE = 6


class SpectateVerdict(NamedTuple):
    kind: str  # "in_sync" | "moves" | "behind" | "reimport"
    moves: tuple = ()  # ((i, j, color), ...) の着手順
    estimated: bool = False
    reason: str = ""


def _replay(grid, moves):
    for i, j, color in moves:
        grid = apply_move_to_grid(grid, i, j, color)
        if grid is None:
            return None
    return grid


def _interleave(blacks, whites, colors):
    """colors の色順に、各色の石を渡された順で取り出して着手列にする"""
    bi = iter(blacks)
    wi = iter(whites)
    return tuple((*next(bi), BLACK) if c == BLACK else (*next(wi), WHITE) for c in colors)


def spectate_sync(
    tip_grid,
    observed,
    to_play,
    last_mover=None,
    app_move_number=None,
    tip_move_number=None,
    ancestor_grids=(),
):
    if len(observed) != len(tip_grid) or any(len(r) != len(tip_grid) for r in observed):
        return SpectateVerdict("reimport", reason="盤サイズが違う")
    if observed == tip_grid:
        return SpectateVerdict("in_sync")
    if any(observed == a for a in ancestor_grids):
        return SpectateVerdict("behind", reason="本譜の過去の局面")

    size = len(tip_grid)
    added = [
        (i, j, observed[i][j])
        for i in range(size)
        for j in range(size)
        if tip_grid[i][j] == EMPTY and observed[i][j] != EMPTY
    ]
    n = len(added)
    if n == 0:
        return SpectateVerdict("reimport", reason="増えた石が無い")

    other = WHITE if to_play == BLACK else BLACK
    colors = [to_play if k % 2 == 0 else other for k in range(n)]
    blacks = [(i, j) for i, j, c in added if c == BLACK]
    whites = [(i, j) for i, j, c in added if c == WHITE]
    if len(blacks) != colors.count(BLACK) or len(whites) != colors.count(WHITE):
        return SpectateVerdict("reimport", reason="増えた石の色が交互の着手で説明できない")
    if last_mover is not None and colors[-1] != last_mover:
        return SpectateVerdict("reimport", reason="直前手の色と合わない")
    if app_move_number is not None and tip_move_number is not None and tip_move_number + n != app_move_number:
        return SpectateVerdict("reimport", reason="手数が合わない")

    estimated = n >= 2
    moves = _interleave(blacks, whites, colors)
    if _replay(tip_grid, moves) == observed:
        return SpectateVerdict("moves", moves, estimated)
    if n <= SPECTATE_MAX_PERMUTE:
        for bp in permutations(blacks):
            for wp in permutations(whites):
                moves = _interleave(bp, wp, colors)
                if _replay(tip_grid, moves) == observed:
                    return SpectateVerdict("moves", moves, estimated)
    return SpectateVerdict("reimport", reason="着手の並びで説明できない")


class SpectateInfo(NamedTuple):
    rules: Optional[str] = None
    komi: Optional[float] = None
    agehama_b: Optional[int] = None  # 黒が取った石の数
    agehama_w: Optional[int] = None  # 白が取った石の数
    next_player: Optional[str] = None
    app_move_number: Optional[int] = None


_RULES_WORDS = (("中国ルール", "chinese"), ("日本ルール", "japanese"), ("韓国ルール", "korean"))
# コミ表記 -> (エンジンに渡すコミ, ルール)。ルールが表記から決まらないものは None
_KOMI_TABLE = {"3又3/4子": (7.5, "chinese"), "6目半": (6.5, "japanese"), "7目半": (7.5, None)}
_TERRITORY_RULES = ("japanese", "korean")


def _squash(text):
    return re.sub(r"\s+", "", text)  # 全角空白（U+3000）も \s に含まれる


def parse_fox_title(title):
    """野狐の窓タイトルから（手数, ルール）を読む。読めない項目は None"""
    t = _squash(title)
    m = re.search(r"\[(\d+)手目\]", t)
    rules = next((r for word, r in _RULES_WORDS if word in t), None)
    return (int(m.group(1)) if m else None), rules


def parse_fox_panel(lines):
    """対局者パネルの OCR 行から（コミ, ルール, 黒のアゲハマ, 白のアゲハマ）を読む。

    アゲハマ行「L子アゲハマR子」は左が白、右が黒が取った数。コミは見出しの読み違いに備え、
    表のキーがどこかの行に含まれるかで拾う。表に無い表記（「又」「目半」を含むのに当たらない）は推測せず None
    """
    squashed = [_squash(x) for x in lines]
    komi = rules = None
    for key, (k, r) in _KOMI_TABLE.items():
        if any(key in x for x in squashed):
            komi, rules = k, r
            break
    agehama_b = agehama_w = None
    for x in squashed:
        m = re.search(r"(\d+)子アゲハマ(\d+)子", x)
        if m:
            agehama_w, agehama_b = int(m.group(1)), int(m.group(2))
            break
    return komi, rules, agehama_b, agehama_w


def engine_komi_offset(rules, agehama_b, agehama_w):
    """地を数えるルールでは取った石が点数に入らないので、アゲハマの差をコミで補う（中国ルールは 0）"""
    return float(agehama_w - agehama_b) if rules in _TERRITORY_RULES else 0.0


def agehama_base(entered, counted_since_import):
    """取り込み時点のアゲハマ基準値（入力値から、取り込み後に KaTrain が数えた分を引く）"""
    return max(0, entered - counted_since_import)


def next_player_from(last_mover, app_move_number):
    """次の手番。最後に打った色が分かればその逆、無ければ手数の偶奇（奇数手目＝黒が打った直後＝白番）"""
    if last_mover in ("B", "W"):
        return "W" if last_mover == "B" else "B"
    if app_move_number is not None:
        return "W" if app_move_number % 2 == 1 else "B"
    return None
