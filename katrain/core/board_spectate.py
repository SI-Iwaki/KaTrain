"""観戦用の盤面反映モードの純ロジック（Kivy 非依存）。

アプリ側の盤（observed）が KaTrain の本譜の末尾（tip）からどれだけ進んだかを判定する。
"""

import re
from itertools import permutations
import threading
import time
from typing import NamedTuple, Optional

from katrain.core.board_watch import (
    BLACK,
    EMPTY,
    STATUS_WATCHING,
    WATCHING_TEXT,
    WHITE,
    BoardWatcher,
    PermanentCaptureError,
    apply_move_to_grid,
    watch_settings_from_config,
)

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


def _ocr_count(text):
    """OCR は数字の 0 を「ロ」「〇」「O」と読むことがある（実測 2026-11-15: 実スクショ 2 枚とも「ロ子アゲハマロ子」）"""
    return int(text.translate(str.maketrans("ロ〇Oo", "0000")))


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
        m = re.search(r"([0-9ロ〇Oo]+)子アゲ.{0,3}マ([0-9ロ〇Oo]+)子", x)
        if m:
            agehama_w, agehama_b = _ocr_count(m.group(1)), _ocr_count(m.group(2))
            break
    return komi, rules, agehama_b, agehama_w


def engine_komi_offset(rules, agehama_b, agehama_w):
    """地を数えるルールでは取った石が点数に入らないので、アゲハマの差をコミで補う（中国ルールは 0）"""
    return float(agehama_w - agehama_b) if rules in _TERRITORY_RULES else 0.0


def agehama_base(entered, counted_since_import):
    """取り込み時点のアゲハマ基準値（入力値から、取り込み後に KaTrain が数えた分を引く）"""
    return max(0, entered - counted_since_import)


# 野狐の対局者パネル（コミとアゲハマの行がある）の切り出し。盤矩形の幅 bw・高さ bh に対する割合:
# (x の左端＝盤の右端からの距離, y の上端, x の右端＝窓の右端からの余白, y の下端)。
# 右のサイドバー（棋譜鑑賞・絶芸…）を入れてはいけない＝実測 2026-11-15: 窓の右端まで切ると 1 枚目でコミの行が消えた
FOX_PANEL_BOX = (0.07, 0.04, 0.10, 0.35)


def _fox_panel_crop(reader):
    img, board_rect = reader.last_image(), getattr(reader, "_board_rect", None)
    if img is None or board_rect is None:
        return None
    bx0, by0, bx1, by1 = board_rect
    bw, bh = bx1 - bx0, by1 - by0
    left, top, right_margin, bottom = FOX_PANEL_BOX
    box = (round(bx1 + left * bw), round(top * bh), round(img.size[0] - right_margin * bw), round(bottom * bh))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return img.crop(box)


def read_spectate_info(reader, ocr=None):
    """観戦の取り込みに使う対局情報。野狐以外は直前手の色から手番だけ、野狐は窓タイトル→パネル OCR の順に埋める。

    OCR は遅い（1〜2 秒）ので開始時と再取り込みのときだけ、GUI スレッド以外から呼ぶこと。
    読めない項目は None のまま（呼び出し側が入力欄の値を使う）。ルールは窓タイトル優先
    """
    last_mover = reader.last_mover_color()
    if reader.profile_name() != "fox":
        return SpectateInfo(next_player=next_player_from(last_mover, None))
    if ocr is None:
        from katrain.core import screen_ocr

        ocr = screen_ocr.ocr_lines
    move_number = rules = None
    title = reader.window_title_text()
    if title:
        move_number, rules = parse_fox_title(title)
    komi = agehama_b = agehama_w = None
    panel = _fox_panel_crop(reader)
    lines = ocr(panel) if panel is not None else None
    if lines:
        komi, panel_rules, agehama_b, agehama_w = parse_fox_panel(lines)
        rules = rules or panel_rules
    return SpectateInfo(rules, komi, agehama_b, agehama_w, next_player_from(last_mover, move_number), move_number)


def next_player_from(last_mover, app_move_number):
    """次の手番。最後に打った色が分かればその逆、無ければ手数の偶奇（奇数手目＝黒が打った直後＝白番）"""
    if last_mover in ("B", "W"):
        return "W" if last_mover == "B" else "B"
    if app_move_number is not None:
        return "W" if app_move_number % 2 == 1 else "B"
    return None


BEHIND_TEXT = "アプリが過去の局面を表示中のため反映を待っています"


class SpectateState(NamedTuple):
    tip_grid: list
    to_play: str
    tip_move_number: Optional[int]
    tip_depth: int
    board_size: int
    ancestor_grids: tuple = ()


def spectate_watch_settings(cfg):
    """観戦用の監視設定。周期は spectate_poll_ms、自動停止は無し、他は対局監視と同じ"""
    d = cfg or {}
    base = watch_settings_from_config(d)
    return base._replace(poll_interval_ms=int(d.get("spectate_poll_ms", 1000)), auto_stop_sec=0)


def _key(grid):
    return tuple("".join(row) for row in grid)


class SpectateWatcher(BoardWatcher):
    """観戦用の監視ループ。アプリ盤が本譜の末尾から進んだ分を on_moves / on_reimport で知らせる"""

    def __init__(
        self, capture_fn, get_state_fn, on_moves, on_reimport, on_status, settings, hints_fn=None, clock=time.monotonic
    ):
        super().__init__(
            capture_fn,
            get_state_fn,
            None,
            on_status,
            settings,
            clock=clock,
            active_kinds=(),
            on_idle_stop=None,
            player_color_fn=None,
            on_new_game=None,
        )
        self.on_moves = on_moves
        self.on_reimport = on_reimport
        self.hints_fn = hints_fn
        self._cand = None  # 確認中の判定の鍵
        self._cand_count = 0
        self._fired = None  # 発火済みの鍵（状態か観測盤が変わるまで投げ直さない）
        self._mode = None  # 直近の状態表示 ("in_sync" / "behind")
        self._lock = threading.RLock()  # step（監視スレッド）と step_once（別スレッド）の排他

    def _warn(self, message):
        self._mode = None  # 警告のあとの in_sync / behind は表示の復帰として必ず出し直す
        super()._warn(message)

    def _hints(self):
        if self.hints_fn is None:
            return None, None
        try:
            last_mover, number = self.hints_fn()
            return last_mover, number
        except Exception:
            return None, None

    def _verdict(self, observed, state):
        last_mover, number = self._hints()
        return spectate_sync(
            state.tip_grid,
            observed,
            state.to_play,
            last_mover=last_mover,
            app_move_number=number,
            tip_move_number=state.tip_move_number,
            ancestor_grids=state.ancestor_grids,
        )

    @staticmethod
    def _verdict_key(verdict, observed, state):
        if verdict.kind == "moves":
            return ("moves", verdict.moves, state.tip_depth, _key(observed))
        return ("reimport", _key(observed), _key(state.tip_grid))

    def _fire(self, verdict, observed, state):
        if verdict.kind == "moves":
            self.on_moves(verdict.moves, state.tip_depth, verdict.estimated)
        else:
            self.on_reimport([row[:] for row in observed], verdict.reason)

    def _reset_confirmation(self):
        self._cand = None
        self._cand_count = 0

    def step(self):
        with self._lock:
            self._step()

    def _step(self):
        try:
            observed = self.capture_fn()
        except Exception as e:
            self._on_capture_failure(str(e), permanent=isinstance(e, PermanentCaptureError))
            return
        self._on_capture_success()
        state = self.get_state_fn()
        if state is None:
            return
        verdict = self._verdict(observed, state)
        if verdict.kind in ("in_sync", "behind"):
            self._reset_confirmation()
            self._fired = None
            if self._mode != verdict.kind:
                self._mode = verdict.kind
                self.on_status(STATUS_WATCHING, WATCHING_TEXT if verdict.kind == "in_sync" else BEHIND_TEXT)
            return
        self._mode = None
        key = self._verdict_key(verdict, observed, state)
        if key == self._fired:
            self._reset_confirmation()  # 確定は連続した周だけで数える
            return
        if verdict.kind == "moves":
            self._active()  # 確定待ちは速く回す（reimport は通常周期のまま）
        if key == self._cand:
            self._cand_count += 1
        else:
            self._cand = key
            self._cand_count = 1
        if self._cand_count < self.settings.stable_frames:
            return
        self._reset_confirmation()
        self._fired = key
        self._fire(verdict, observed, state)

    def step_once(self):
        """確定待ちをせず 1 回だけ判定して即コールバックする（「今すぐ反映」用）"""
        with self._lock:
            return self._step_once()

    def _step_once(self):
        try:
            observed = self.capture_fn()
        except Exception as e:
            self._on_capture_failure(str(e), permanent=isinstance(e, PermanentCaptureError))
            return None
        self._on_capture_success()
        try:
            state = self.get_state_fn()
            if state is None:
                return None
            verdict = self._verdict(observed, state)
        except Exception as e:
            self._warn(f"観戦の判定でエラーが発生しました: {e}")
            return None
        if verdict.kind in ("moves", "reimport"):
            self._reset_confirmation()
            self._fired = self._verdict_key(verdict, observed, state)
            self._fire(verdict, observed, state)
        return verdict
