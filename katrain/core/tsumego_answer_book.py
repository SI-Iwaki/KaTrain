"""詰碁回答帳: 誤答問題の正解手順を保存し、盤の8対称で一致する再出題に即答する。

スペック: docs/superpowers/specs/2026-08-02-tsumego-answer-book-design.md
Kivy / KataGo 非依存（tsumego_problem.py と同じ層）。座標は (x, y)・y は下origin。
"""
import datetime
import hashlib
import json
import os
from typing import List, Optional, Sequence, Set, Tuple

Point = Tuple[int, int]

BOOK_VERSION = 1
PASS = "pass"

_GTP_COLS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"  # KataGo GTP 準拠（I を飛ばす）


def transform_point(p: Point, t: int, size: int) -> Point:
    """盤の8対称（t=0..7）。t&4 で鏡映（x 反転）、t&3 で90度回転の回数。"""
    x, y = p
    if t & 4:
        x = size - 1 - x
    for _ in range(t & 3):
        x, y = y, size - 1 - x
    return (x, y)


def inverse_transform(t: int) -> int:
    """transform_point(transform_point(p, t), 逆) == p となる変換ID。

    8つしかないので、軌道が8点に割れる代表点の総当たりで求める（対称軸上に
    ない点の固定部分群は自明なので1点で一意に決まるが、念のため2点で確認）。
    """
    probes = [(1, 2), (0, 5)]
    for u in range(8):
        if all(transform_point(transform_point(p, t, 9), u, 9) == p for p in probes):
            return u
    raise ValueError(f"no inverse for transform {t}")


def point_to_gtp(p: Optional[Point]) -> str:
    if p is None:
        return PASS
    return f"{_GTP_COLS[p[0]]}{p[1] + 1}"


def gtp_to_point(s: str) -> Optional[Point]:
    if s == PASS:
        return None
    return (_GTP_COLS.index(s[0].upper()), int(s[1:]) - 1)


def _serialized(black: Set[Point], white: Set[Point], t: int, size: int) -> str:
    tb = sorted(transform_point(p, t, size) for p in black)
    tw = sorted(transform_point(p, t, size) for p in white)
    return repr((tb, tw))


def canonicalize(black: Set[Point], white: Set[Point], size: int, to_play: str) -> Tuple[str, List[int]]:
    """(キー, 盤→標準形の有効変換IDリスト) を返す。

    標準形は8対称のうちシリアライズが辞書順最小のもの。対称な配置では複数の
    変換がタイになる（照合時は全部試す＝スペック§3）。
    """
    forms = {t: _serialized(black, white, t, size) for t in range(8)}
    best = min(forms.values())
    transforms = [t for t in range(8) if forms[t] == best]
    payload = repr((BOOK_VERSION, size, to_play, best)).encode()
    return hashlib.sha1(payload).hexdigest(), transforms


def moves_to_canonical(moves: List[Tuple[Optional[Point], str]], t: int, size: int) -> List[str]:
    """Root からの (coords, player) 列を標準形向きの GTP 文字列列にする。パスは "pass"。"""
    return [point_to_gtp(None if c is None else transform_point(c, t, size)) for c, _p in moves]


def next_move(entry: dict, transforms: Sequence[int], moves: List[Tuple[Optional[Point], str]], size: int) -> Tuple[bool, Optional[Point]]:
    """前方一致する line の次手を盤の向きで返す。(ヒット, coords)。次手パスは (True, None)。

    対称な配置では変換がタイになるため全有効変換で試し、実際に打たれた手列が
    前方一致する変換を採用する（スペック§3「対称局面の曖昧性」）。
    """
    lines = entry.get("lines") or []
    for t in transforms:
        canon = moves_to_canonical(moves, t, size)
        n = len(canon)
        inv = inverse_transform(t)
        for line in lines:
            if len(line) > n and line[:n] == canon:
                p = gtp_to_point(line[n])
                return True, (None if p is None else transform_point(p, inv, size))
    return False, None


DEFAULT_PATH = os.path.expanduser("~/.katrain/tsumego_answers.json")


class AnswerBook:
    """回答帳の永続ストア（スペック§4）。破損・欠損は空として続行する。"""

    def __init__(self, path: Optional[str] = None, logger=None):
        self.path = path or DEFAULT_PATH
        self.log = logger or (lambda msg: None)
        self._data = None

    def _load(self):
        if self._data is not None:
            return
        self._data = {"version": BOOK_VERSION, "entries": {}}
        try:
            if os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw.get("entries"), dict):
                    self._data["entries"] = raw["entries"]
        except Exception as e:
            self.log(f"tsumego_answer_book: 回答帳の読み込みに失敗（{e}）。空として続行します")

    def lookup(self, key: str) -> Optional[dict]:
        self._load()
        return self._data["entries"].get(key)

    def add_line(self, key, size, to_play, canonical_black, canonical_white, line) -> bool:
        """手順を追加して保存する。既存エントリには line 追加（重複は無視）。追加できたら True。"""
        self._load()
        entry = self._data["entries"].setdefault(
            key,
            {
                "size": size,
                "to_play": to_play,
                "canonical_black": canonical_black,
                "canonical_white": canonical_white,
                "lines": [],
                "created": datetime.date.today().isoformat(),
            },
        )
        if line in entry["lines"]:
            return False
        entry["lines"].append(line)
        self._save()
        return True

    def _save(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


_default_book = None


def get_book(logger=None) -> AnswerBook:
    global _default_book
    if _default_book is None:
        _default_book = AnswerBook(logger=logger)
    elif logger is not None:
        _default_book.log = logger
    return _default_book
