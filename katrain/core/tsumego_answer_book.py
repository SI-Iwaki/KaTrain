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
BLACK_WHITE = ("B", "W")


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


def line_status(entry: dict, transforms: Sequence[int], moves: List[Tuple[Optional[Point], str]], size: int) -> str:
    """記録手順に対する現在の局面の位置づけ。GUI 表示用（着手判定には使わない）。

    "playing" = まだ記録の途中（次手が記録にある）/ "done" = 記録手順を打ち切った /
    "off" = どの line とも前方一致しない（白が記録から逸脱した等）。
    """
    lines = entry.get("lines") or []
    done = False
    for t in transforms:
        canon = moves_to_canonical(moves, t, size)
        n = len(canon)
        for line in lines:
            if line[:n] != canon:  # 長さが足りない line もここで落ちる
                continue
            if len(line) > n:
                return "playing"
            done = True
    return "done" if done else "off"


def should_record_line(entry, transforms, moves, size) -> bool:
    """正解した手順を回答帳へ自動記録すべきか（自動ループの正解時に使う）。

    回答帳の記録どおりに解答した問題（"playing"=記録の途中でアプリが正解を出した /
    "done"=記録手順を打ち切った）は再記録しない。エントリが無い問題と、白が記録から
    逸脱して通常パイプラインで解いた手順（"off"）は新しい情報なので記録する。
    """
    if not entry or not transforms:
        return True
    return line_status(entry, transforms, moves, size) == "off"


def frame_added_points(grid: Sequence[Sequence[str]], framed: Sequence[Sequence[str]]) -> Set[Point]:
    """枠が盤に**足した**石の点（壁・充填・コウダテ形）を盤の向きの (x, y) で返す。

    grid / framed は `grid[i][j]`・i は上からの行（`grid_to_stones` と同じ向き）。"B" / "W" 以外は
    空点として扱う（認識グリッドは "-" や "." を使う）。枠が**消した**非コア石の点は含めない
    （そこは元の盤でも石なので記録手順が打つことはない）。
    """
    size = len(grid)
    added: Set[Point] = set()
    for i in range(size):
        for j in range(size):
            if grid[i][j] not in (BLACK_WHITE) and framed[i][j] in BLACK_WHITE:
                added.add((j, size - 1 - i))
    return added


def line_frame_collisions(
    entry: Optional[dict], transforms: Sequence[int], size: int, blocked: Set[Point]
) -> List[Tuple[int, str, str]]:
    """回答帳の記録手順のうち blocked（枠が足した石の点・盤の向き）に乗る手を返す。

    返り値は (手順上の index, "B"/"W", 盤の向きの GTP) を index 順。**黒白どちらの手も**対象＝
    白の応手が壁に乗れば再生は注入の "Space occupied" で止まり、以後の黒手も打てない
    （実測 2026-11-07 回答帳キー 452e79c7de…: 白 17手目 B4 / 19手目 A4 が黒の壁石で、黒が
    記録どおり 9 手打ったあと白の注入が止まって誤答。2026-08-24 にも同一の失敗）。
    対称な配置で変換がタイのときは全有効変換で試し、どれかで乗れば衝突とする（安全側）。
    """
    if not entry or not transforms or not blocked:
        return []
    to_play = entry.get("to_play", "B")
    other = "W" if to_play == "B" else "B"
    hits: dict = {}
    for t in transforms:
        inv = inverse_transform(t)
        for line in entry.get("lines") or []:
            for n, mv in enumerate(line):
                p = gtp_to_point(mv)
                if p is None:
                    continue
                q = transform_point(p, inv, size)
                if q in blocked:
                    hits.setdefault((n, point_to_gtp(q)), to_play if n % 2 == 0 else other)
    return sorted((n, player, gtp) for (n, gtp), player in hits.items())


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
