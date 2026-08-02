# 詰碁回答帳（answer book）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 誤答した詰碁の正解手順をユーザーが手動記録し、盤の8対称で一致する再出題に0秒で自動解答する「回答帳」を実装する。

**Architecture:** 新規モジュール `katrain/core/tsumego_answer_book.py`（Kivy/KataGo 非依存の純ロジック＋JSONストア）を核に、キャプチャ成功処理（`__main__.py`）で正規化キーを計算・照合してゲームに紐づけ、両詰碁戦略（`ai.py`）の先頭で前方一致再生する。記録は `BadukPanControls`（下部ナビ＝tsumego_view でも可視）のトグルボタン。

**Tech Stack:** Python 3.12 / Kivy（GUIボタンのみ）/ pytest / gettext i18n

**Spec:** `docs/superpowers/specs/2026-08-02-tsumego-answer-book-design.md`

## Global Constraints

- 新しい設定キーは追加しない（回答帳が空なら全経路の挙動は**完全に従来どおり**）
- 照合・再生に KataGo 解析クエリを1本も使わない
- `tsumego_answer_book.py` は Kivy/KataGo に依存しない（`tsumego_problem.py` と同じ層）
- 座標は `Move.coords` の (x, y)・y は下origin。盤の変化は**8対称のみ**（平行移動・色反転なし＝ユーザー確認済み）
- 保存先は `~/.katrain/tsumego_answers.json`（可読・手編集可能）
- コミットメッセージは日本語・Conventional Commits（`feat:`/`fix:`/`docs:` 等）
- i18n は `.po` 編集後 `python tools/compile_mo.py` を必ず実行（CLAUDE.md）
- テストは `pytest tests/test_tsumego_answer_book.py -v`（KataGo/Kivy/humanSLモデル不要）
- pytest の出力で日本語 assert メッセージは避ける（Windows cp932 端末）

## 参照データ（ユーザー提供の13路実問題）

SGF: `AB[ai][bi][ci][di][ei][ej][ck][ek][bl][el][em] AW[bj][cj][dj][bk][dk][dl][dm]`、
正解手順 `B[aj] W[al] B[bm] W[ak] B[cl]`（左下の問題）。

(x, y)＝下origin に変換した値（SGF の `col,row上から` → `(col, 12-row)`）:

- 黒: (0,4) (1,4) (2,4) (3,4) (4,4) (4,3) (2,2) (4,2) (1,1) (4,1) (4,0)
- 白: (1,3) (2,3) (3,3) (1,2) (3,2) (3,1) (3,0)
- 正解手順: B(0,3) W(0,1) B(1,0) W(0,2) B(2,1)

---

### Task 1: 8対称変換と正規化キー（`tsumego_answer_book.py` の土台）

**Files:**
- Create: `katrain/core/tsumego_answer_book.py`
- Test: `tests/test_tsumego_answer_book.py`

**Interfaces:**
- Produces: `transform_point(p: Point, t: int, size: int) -> Point`（t=0..7）、
  `inverse_transform(t: int) -> int`、
  `canonicalize(black: Set[Point], white: Set[Point], size: int, to_play: str) -> Tuple[str, List[int]]`
  （返り値 = (SHA1キー, 盤→標準形の有効変換IDリスト)）、
  `point_to_gtp(p: Optional[Point]) -> str` / `gtp_to_point(s: str) -> Optional[Point]`（パスは `"pass"`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_answer_book.py` を新規作成:

```python
"""tsumego_answer_book のユニットテスト（KataGo/Kivy/humanSL モデル不要）。"""
import pytest

from katrain.core.tsumego_answer_book import (
    canonicalize,
    gtp_to_point,
    inverse_transform,
    point_to_gtp,
    transform_point,
)

# ユーザー提供の13路実問題（左下）。座標は (x, y)・y は下origin
REF_BLACK = {(0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (4, 3), (2, 2), (4, 2), (1, 1), (4, 1), (4, 0)}
REF_WHITE = {(1, 3), (2, 3), (3, 3), (1, 2), (3, 2), (3, 1), (3, 0)}
REF_LINE = [(0, 3), (0, 1), (1, 0), (0, 2), (2, 1)]  # B W B W B
SIZE = 13


def _transform_set(points, t, size):
    return {transform_point(p, t, size) for p in points}


class TestTransforms:
    def test_identity(self):
        assert transform_point((3, 7), 0, SIZE) == (3, 7)

    def test_rotate_180_hand_computed(self):
        # t=2 は180度回転: (x, y) -> (12-x, 12-y)
        assert transform_point((0, 4), 2, SIZE) == (12, 8)
        assert transform_point((12, 12), 2, SIZE) == (0, 0)

    def test_mirror_hand_computed(self):
        # t=4 は x 反転のみ
        assert transform_point((0, 4), 4, SIZE) == (12, 4)

    def test_all_transforms_roundtrip(self):
        probes = [(0, 0), (1, 2), (5, 5), (12, 0), (3, 11)]
        for t in range(8):
            inv = inverse_transform(t)
            for p in probes:
                assert transform_point(transform_point(p, t, SIZE), inv, SIZE) == p

    def test_transforms_are_permutations(self):
        # 各変換は盤上の全点の置換（重複なし・盤内に収まる）
        all_points = [(x, y) for x in range(SIZE) for y in range(SIZE)]
        for t in range(8):
            images = {transform_point(p, t, SIZE) for p in all_points}
            assert len(images) == SIZE * SIZE
            assert all(0 <= x < SIZE and 0 <= y < SIZE for x, y in images)


class TestGtp:
    def test_roundtrip(self):
        for p in [(0, 0), (8, 12), (12, 0), None]:
            assert gtp_to_point(point_to_gtp(p)) == p

    def test_skips_i_column(self):
        assert point_to_gtp((8, 0)) == "J1"  # 8列目は I を飛ばして J

    def test_pass(self):
        assert point_to_gtp(None) == "pass"
        assert gtp_to_point("pass") is None


class TestCanonicalize:
    def test_same_key_for_all_8_orientations(self):
        base_key, _ = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        for t in range(1, 8):
            key, _ = canonicalize(
                _transform_set(REF_BLACK, t, SIZE), _transform_set(REF_WHITE, t, SIZE), SIZE, "B"
            )
            assert key == base_key, f"transform {t} gave different key"

    def test_different_problem_different_key(self):
        key1, _ = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        key2, _ = canonicalize(REF_BLACK | {(6, 6)}, REF_WHITE, SIZE, "B")
        assert key1 != key2

    def test_to_play_and_size_in_key(self):
        key_b, _ = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        key_w, _ = canonicalize(REF_BLACK, REF_WHITE, SIZE, "W")
        assert key_b != key_w

    def test_asymmetric_problem_single_transform(self):
        _, transforms = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        assert len(transforms) == 1

    def test_symmetric_problem_multiple_transforms(self):
        # 対角線対称の配置は複数の変換がタイになる
        black = {(0, 0), (2, 2)}
        white = {(1, 0), (0, 1)}
        _, transforms = canonicalize(black, white, 9, "B")
        assert len(transforms) >= 2

    def test_transforms_map_board_to_canonical(self):
        # 別の向きに置いた盤も、有効変換で写すと同じ標準形になること
        key, transforms = canonicalize(REF_BLACK, REF_WHITE, SIZE, "B")
        rot_black = _transform_set(REF_BLACK, 3, SIZE)
        rot_white = _transform_set(REF_WHITE, 3, SIZE)
        key2, transforms2 = canonicalize(rot_black, rot_white, SIZE, "B")
        assert key2 == key
        t = transforms2[0]
        assert _transform_set(rot_black, t, SIZE) == _transform_set(REF_BLACK, transforms[0], SIZE)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_tsumego_answer_book.py -v`
Expected: FAIL（`ModuleNotFoundError: katrain.core.tsumego_answer_book`）

- [ ] **Step 3: 実装**

`katrain/core/tsumego_answer_book.py` を新規作成:

```python
"""詰碁回答帳: 誤答問題の正解手順を保存し、盤の8対称で一致する再出題に即答する。

スペック: docs/superpowers/specs/2026-08-02-tsumego-answer-book-design.md
Kivy / KataGo 非依存（tsumego_problem.py と同じ層）。座標は (x, y)・y は下origin。
"""
import hashlib
from typing import List, Optional, Set, Tuple

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
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_tsumego_answer_book.py -v`
Expected: 全 PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/tsumego_answer_book.py tests/test_tsumego_answer_book.py
git commit -m "feat(tsumego): 回答帳の8対称変換と正規化キー（スペック§3）"
```

---

### Task 2: 手順の正規化と前方一致再生

**Files:**
- Modify: `katrain/core/tsumego_answer_book.py`（末尾に追記）
- Test: `tests/test_tsumego_answer_book.py`（クラス追加）

**Interfaces:**
- Consumes: Task 1 の `transform_point` / `inverse_transform` / `point_to_gtp` / `gtp_to_point`
- Produces: `moves_to_canonical(moves: List[Tuple[Optional[Point], str]], t: int, size: int) -> List[str]`
  （moves は `tsumego_solver_api.moves_from_game` の返り値形式＝(coords, player) の列。返り値は標準形向き GTP 文字列列）、
  `next_move(entry: dict, transforms: Sequence[int], moves, size: int) -> Tuple[bool, Optional[Point]]`
  （(ヒットしたか, 盤の向きの次手coords)。次手がパスなら (True, None)、一致なしは (False, None)）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_answer_book.py` の import に `moves_to_canonical, next_move` を追加し、クラスを追記:

```python
from katrain.core.tsumego_answer_book import moves_to_canonical, next_move


def _entry_for(black, white, line_moves, size):
    """テスト用エントリ: 盤の向きの手順を transforms[0] で標準形向きに変換して格納。"""
    key, transforms = canonicalize(black, white, size, "B")
    players = ["B", "W"] * ((len(line_moves) + 1) // 2)
    moves = list(zip(line_moves, players))
    line = moves_to_canonical(moves, transforms[0], size)
    return key, transforms, {"lines": [line]}


class TestNextMove:
    def test_first_move_and_full_line(self):
        key, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = []
        for expect in [REF_LINE[0], REF_LINE[2], REF_LINE[4]]:  # 黒番のみ照会
            found, coords = next_move(entry, transforms, played, SIZE)
            assert found and coords == expect
            played.append((coords, "B"))
            i = len(played)
            if i < len(REF_LINE):
                played.append((REF_LINE[i], "W"))  # 白は記録どおり応手

    def test_white_deviation_misses(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        played = [(REF_LINE[0], "B"), ((6, 6), "W")]  # 白が記録に無い応手
        found, coords = next_move(entry, transforms, played, SIZE)
        assert not found and coords is None

    def test_line_exhausted_misses(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        players = ["B", "W"] * 3
        played = list(zip(REF_LINE, players))
        found, _ = next_move(entry, transforms, played, SIZE)
        assert not found

    def test_multiple_lines_branch(self):
        # 白の別応手 (0,2) の枝を2本目の line として持つエントリ
        key, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        alt_moves = [(REF_LINE[0], "B"), ((0, 2), "W"), ((2, 1), "B")]
        entry["lines"].append(moves_to_canonical(alt_moves, transforms[0], SIZE))
        played = [(REF_LINE[0], "B"), ((0, 2), "W")]
        found, coords = next_move(entry, transforms, played, SIZE)
        assert found and coords == (2, 1)

    def test_rotated_board_plays_transformed_moves(self):
        # 左下で記録した手順が、180度回転（右上）で出題された盤では回転した座標で出ること
        _, transforms0, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        rot_black = _transform_set(REF_BLACK, 2, SIZE)
        rot_white = _transform_set(REF_WHITE, 2, SIZE)
        key2, transforms2 = canonicalize(rot_black, rot_white, SIZE, "B")
        found, coords = next_move(entry, transforms2, [], SIZE)
        assert found and coords == transform_point(REF_LINE[0], 2, SIZE) == (12, 9)

    def test_pass_in_line(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        moves = [(REF_LINE[0], "B"), (None, "W"), (REF_LINE[2], "B")]
        entry["lines"] = [moves_to_canonical(moves, transforms[0], SIZE)]
        played = [(REF_LINE[0], "B"), (None, "W")]
        found, coords = next_move(entry, transforms, played, SIZE)
        assert found and coords == REF_LINE[2]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_tsumego_answer_book.py -v`
Expected: 新クラスが FAIL（`ImportError: moves_to_canonical`）、Task 1 分は PASS のまま

- [ ] **Step 3: 実装**

`tsumego_answer_book.py` 末尾に追記:

```python
def moves_to_canonical(moves, t: int, size: int) -> List[str]:
    """root からの (coords, player) 列を標準形向きの GTP 文字列列にする。パスは "pass"。"""
    return [point_to_gtp(None if c is None else transform_point(c, t, size)) for c, _p in moves]


def next_move(entry, transforms, moves, size: int) -> Tuple[bool, Optional[Point]]:
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
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_tsumego_answer_book.py -v`
Expected: 全 PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/tsumego_answer_book.py tests/test_tsumego_answer_book.py
git commit -m "feat(tsumego): 回答帳の手順正規化と前方一致再生（スペック§7）"
```

---

### Task 3: AnswerBook ストア（JSON の load / add_line / lookup）

**Files:**
- Modify: `katrain/core/tsumego_answer_book.py`（末尾に追記）
- Test: `tests/test_tsumego_answer_book.py`（クラス追加）

**Interfaces:**
- Produces: `class AnswerBook`（`__init__(path=None, logger=None)` / `lookup(key) -> Optional[dict]` /
  `add_line(key, size, to_play, canonical_black, canonical_white, line) -> bool`）、
  `get_book(logger=None) -> AnswerBook`（既定パス `~/.katrain/tsumego_answers.json` のシングルトン）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_answer_book.py` に追記（import に `AnswerBook` を追加）:

```python
from katrain.core.tsumego_answer_book import AnswerBook


class TestAnswerBook:
    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / "book.json")
        book = AnswerBook(path=path)
        assert book.lookup("k1") is None
        assert book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4", "A2", "B1"])
        book2 = AnswerBook(path=path)  # 別インスタンス＝ファイルから再ロード
        entry = book2.lookup("k1")
        assert entry is not None and entry["lines"] == [["A4", "A2", "B1"]]
        assert entry["size"] == 13 and entry["to_play"] == "B"

    def test_duplicate_line_ignored(self, tmp_path):
        book = AnswerBook(path=str(tmp_path / "book.json"))
        assert book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4"])
        assert not book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4"])
        assert len(book.lookup("k1")["lines"]) == 1

    def test_second_line_appended(self, tmp_path):
        book = AnswerBook(path=str(tmp_path / "book.json"))
        book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4", "A2"])
        book.add_line("k1", 13, "B", ["A5"], ["B4"], ["A4", "A3", "B2"])
        assert len(book.lookup("k1")["lines"]) == 2

    def test_corrupt_file_treated_as_empty(self, tmp_path):
        path = tmp_path / "book.json"
        path.write_text("{ broken json", encoding="utf-8")
        logs = []
        book = AnswerBook(path=str(path), logger=logs.append)
        assert book.lookup("k1") is None
        assert logs  # 破損はログに出す
        assert book.add_line("k1", 13, "B", [], [], ["A4"])  # 破損後も保存できる

    def test_missing_file_ok(self, tmp_path):
        book = AnswerBook(path=str(tmp_path / "none" / "book.json"))
        assert book.lookup("k1") is None
        assert book.add_line("k1", 9, "B", [], [], ["A4"])  # 親ディレクトリも作る
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_tsumego_answer_book.py::TestAnswerBook -v`
Expected: FAIL（`ImportError: AnswerBook`）

- [ ] **Step 3: 実装**

`tsumego_answer_book.py` の import に `import datetime` / `import json` / `import os` を追加し、末尾に追記:

```python
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
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_tsumego_answer_book.py -v`
Expected: 全 PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/tsumego_answer_book.py tests/test_tsumego_answer_book.py
git commit -m "feat(tsumego): 回答帳の永続ストア（~/.katrain/tsumego_answers.json）"
```

---

### Task 4: 再生ヘルパーと両詰碁戦略の先頭分岐（`ai.py`）

**Files:**
- Modify: `katrain/core/ai.py`（ヘルパー追加＋`TsumegoSolverStrategy._generate_move` / `TsumegoOwnershipStrategy.generate_move` の先頭）
- Test: `tests/test_tsumego_answer_book.py`（クラス追加）

**Interfaces:**
- Consumes: Task 2 の `next_move`、Task 1 の `canonicalize`、`tsumego_solver_api.moves_from_game(game)`
  （root→現局面の `[(coords, player), ...]`）、game 属性 `tsumego_book_entry` / `tsumego_book_transforms`
  （Task 5 が設定。テストではフェイク game に直接設定）
- Produces: `tsumego_book_next_move(game) -> Tuple[bool, Optional[Point]]`（ai.py モジュール関数）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_answer_book.py` に追記。フェイク game は `moves_from_game`（`current_node.parent` チェーン）と
`game.stones`（`.coords` を持つ石リスト）と `game.board_size` だけ満たせばよい:

```python
from types import SimpleNamespace

from katrain.core.ai import tsumego_book_next_move


def _fake_game(black, white, line_moves_played, size, entry, transforms):
    """current_node チェーンと石リストを持つ最小の game。"""
    node = SimpleNamespace(move=None, parent=None)  # root
    stones = [SimpleNamespace(coords=p) for p in black | white]
    for i, coords in enumerate(line_moves_played):
        player = "BW"[i % 2]
        node = SimpleNamespace(move=SimpleNamespace(coords=coords, player=player), parent=node)
        if coords is not None:
            stones.append(SimpleNamespace(coords=coords))  # 取りは無視（占有チェック用の近似で十分）
    return SimpleNamespace(
        current_node=node,
        stones=stones,
        board_size=(size, size),
        tsumego_book_entry=entry,
        tsumego_book_transforms=transforms,
    )


class TestBookNextMove:
    def test_returns_recorded_move(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        game = _fake_game(REF_BLACK, REF_WHITE, [], SIZE, entry, transforms)
        found, coords = tsumego_book_next_move(game)
        assert found and coords == REF_LINE[0]

    def test_no_entry_returns_miss(self):
        game = _fake_game(REF_BLACK, REF_WHITE, [], SIZE, None, None)
        assert tsumego_book_next_move(game) == (False, None)

    def test_occupied_point_returns_miss(self):
        # 認識ずれ等で記録手の点が占有済みなら再生しない（スペック§8）
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        game = _fake_game(REF_BLACK | {REF_LINE[0]}, REF_WHITE, [], SIZE, entry, transforms)
        assert tsumego_book_next_move(game) == (False, None)

    def test_deviation_returns_miss(self):
        _, transforms, entry = _entry_for(REF_BLACK, REF_WHITE, REF_LINE, SIZE)
        game = _fake_game(REF_BLACK, REF_WHITE, [REF_LINE[0], (6, 6)], SIZE, entry, transforms)
        assert tsumego_book_next_move(game) == (False, None)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_tsumego_answer_book.py::TestBookNextMove -v`
Expected: FAIL（`ImportError: tsumego_book_next_move`）

- [ ] **Step 3: ヘルパーを実装**

`katrain/core/ai.py` の `TsumegoSolverStrategy` クラス定義の直前（`@register_strategy(AI_TSUMEGO_SOLVER)` の手前）に追加:

```python
def tsumego_book_next_move(game):
    """回答帳の次手 (ヒットしたか, coords)。パスが記録されていれば (True, None)。

    白の応手が全 line から逸脱した／記録手の点が占有済み（認識ずれ）なら
    (False, None) ＝ 呼び出し側は従来パイプラインへ。毎手呼び直すので、白が
    記録の枝に戻れば再ヒットする（回答帳スペック§7）。解析クエリは使わない。
    """
    entry = getattr(game, "tsumego_book_entry", None)
    transforms = getattr(game, "tsumego_book_transforms", None)
    if not entry or not transforms:
        return False, None
    try:
        from katrain.core import tsumego_answer_book as answer_book
        from katrain.core.tsumego_solver_api import moves_from_game

        size = game.board_size
        if not isinstance(size, int):
            size = size[0]
        found, coords = answer_book.next_move(entry, transforms, moves_from_game(game), size)
        if not found:
            return False, None
        if coords is not None and any(m.coords == coords for m in game.stones):
            return False, None  # 認識ずれ等で占有点になっている＝記録が現盤に合わない
        return True, coords
    except Exception:
        return False, None
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_tsumego_answer_book.py -v`
Expected: 全 PASS

- [ ] **Step 5: 両戦略の先頭に分岐を追加**

`TsumegoSolverStrategy._generate_move`（ai.py:2955 付近）の
`settings = self._solver_settings()` の**直前**（`katrain = self.game.katrain` と logger 定義の後）に挿入:

```python
        book_hit, book_coords = tsumego_book_next_move(self.game)
        if book_hit:
            katrain.log(f"[{self.strategy_name}] 回答帳の記録手順から着手します", OUTPUT_INFO)
            return Move(book_coords, player=self.cn.next_player), "回答帳: 記録された正解手順"
```

`TsumegoOwnershipStrategy.generate_move`（ai.py:3004 付近）の `started = time.time()` の**直後**に挿入:

```python
        book_hit, book_coords = tsumego_book_next_move(self.game)
        if book_hit:
            self.game.katrain.log(f"[{self.strategy_name}] 回答帳の記録手順から着手します", OUTPUT_INFO)
            return Move(book_coords, player=self.cn.next_player), "回答帳: 記録された正解手順"
```

注意: `Move(None, player=...)` はパス（記録にパスがあった場合もこの1行で正しく打てる）。

- [ ] **Step 6: 回帰確認（既存テスト＋構文）**

Run: `pytest tests/test_tsumego_answer_book.py -v` → 全 PASS
Run: `pytest tests/test_tsumego_solver.py tests/test_tsumego_solver_strategy.py -q` → 従来どおり PASS
（book 属性の無い game では `getattr` が None を返し即 (False, None) ＝挙動不変）

- [ ] **Step 7: コミット**

```bash
git add katrain/core/ai.py tests/test_tsumego_answer_book.py
git commit -m "feat(tsumego): 両詰碁戦略の先頭に回答帳の再生分岐を追加"
```

---

### Task 5: キャプチャ時の照合とゲームへの紐づけ（`__main__.py`）

**Files:**
- Modify: `katrain/__main__.py`（`_do_tsumego_capture_apply`、ai.py:1258-1261 付近のブロック）

**Interfaces:**
- Consumes: Task 1 の `canonicalize`、Task 3 の `get_book`、`tsumego_problem.grid_to_stones(grid)`
  （認識グリッド → `(黒点集合, 白点集合, (size, size))`・座標は (x, 下origin y)）
- Produces: game 属性 `tsumego_book_key: str` / `tsumego_book_transforms: List[int]` /
  `tsumego_book_stones: Tuple[Set[Point], Set[Point], int]` / `tsumego_book_entry: Optional[dict]`
  （Task 4 の再生と Task 6 の記録が消費）

- [ ] **Step 1: 照合ブロックを挿入**

`_do_tsumego_capture_apply` 内、`self._do_new_game(move_tree=move_tree)`（1258行）直後の
`self.game.tsumego_solver_problem = solver_problem`（1261行）の**直後**に挿入:

```python
        # 回答帳（スペック 2026-08-02-tsumego-answer-book-design.md）: 枠を張る前の認識石で
        # 正規化キーを計算して照合。ヒットしたら戦略が記録手順を0秒で再生する。
        # 枠張り・ソルバゲートの判断は従来どおり（スペック§5）
        try:
            from katrain.core import tsumego_answer_book as answer_book
            from katrain.core.tsumego_problem import grid_to_stones

            bk_black, bk_white, (bk_size, _) = grid_to_stones(grid)
            key, transforms = answer_book.canonicalize(bk_black, bk_white, bk_size, "B")
            self.game.tsumego_book_key = key
            self.game.tsumego_book_transforms = transforms
            self.game.tsumego_book_stones = (bk_black, bk_white, bk_size)
            entry = answer_book.get_book(lambda msg: self.log(msg, OUTPUT_INFO)).lookup(key)
            self.game.tsumego_book_entry = entry
            if entry is not None:
                self.log(
                    f"tsumego_capture: 回答帳にヒット（記録 {len(entry['lines'])} 手順）。"
                    f"黒は記録どおりに打ちます",
                    OUTPUT_INFO,
                )
            Clock.schedule_once(lambda _dt: setattr(self, "tsumego_book_ready", True), 0)
        except Exception as e:
            self.log(f"tsumego_capture: 回答帳の照合に失敗（{e}）", OUTPUT_INFO)
```

注意1（スレッド）: `_do_tsumego_capture_apply` は**メッセージループスレッド**で走る。
`tsumego_book_ready` は kv バインディング（ボタンの opacity/text）に繋がる Kivy プロパティ
なので、既存の `finish_gui` と同じ理由（「kvバインディングがグラフィックス命令に触るため、
プロパティ変更はメインスレッドで行う」＝ `__main__.py:1340` のコメント）で **Clock 経由で
メインスレッドから設定する**。`Clock` は `__main__.py` で import 済み。

注意2（順序）: `self.tsumego_book_ready` は Task 6 で定義する Kivy プロパティ。Task 5 の
時点ではまだ存在しないため、プロパティ定義（1行）だけ先取りして入れる:
`__main__.py:125` の `tsumego_view = BooleanProperty(False)` の直後に
`tsumego_book_ready = BooleanProperty(False)` を追加する。

- [ ] **Step 2: 構文チェックと手動確認**

Run: `python -m py_compile katrain/__main__.py`
Expected: エラーなし

GUI 手動確認（KataGo 起動あり）: `python -m katrain` → F4 で任意の詰碁をキャプチャ →
ログ（debug_level 1）に `回答帳` の照合行が出ること・従来どおり出題されること。
確認後 debug_level を 0 に戻す。

- [ ] **Step 3: コミット**

```bash
git add katrain/__main__.py
git commit -m "feat(tsumego): キャプチャ時に回答帳を照合しゲームへ紐づけ（スペック§5）"
```

---

### Task 6: 記録UX（トグルボタン・記録モード・i18n）

**Files:**
- Modify: `katrain/__main__.py`（プロパティ2つ＋`_do_tsumego_record_toggle`＋`_do_new_game` のリセット）
- Modify: `katrain/gui.kv`（`<BadukPanControls>` にボタン追加、216-291行）
- Modify: `katrain/i18n/locales/en/LC_MESSAGES/katrain.po` / `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`

**Interfaces:**
- Consumes: Task 5 の game 属性（`tsumego_book_key` / `tsumego_book_stones` / `tsumego_book_transforms`）、
  Task 2 の `moves_to_canonical`、Task 3 の `get_book`、`tsumego_solver_api.moves_from_game`
- Produces: KaTrainGui の `tsumego_book_ready` / `tsumego_recording`（BooleanProperty）、
  アクション `"tsumego-record-toggle"`

- [ ] **Step 1: Kivy プロパティと new-game リセット**

`katrain/__main__.py:125` の `tsumego_view = BooleanProperty(False)` の直後に追加
（Task 5 で先取り済みなら `tsumego_recording` のみ）:

```python
    tsumego_book_ready = BooleanProperty(False)  # 詰碁キャプチャ出題中（回答帳の記録ボタンを出す）
    tsumego_recording = BooleanProperty(False)  # 回答帳の記録モード中（ボタンは「この手順を保存」）
```

`_do_new_game`（371行）の `self.game = Game(...)` 文の直後に追加
（キャプチャ経路は new-game の後で ready を立て直すので、非詰碁の新規対局でだけボタンが消える。
`_do_new_game` もメッセージループスレッドで走るため Clock 経由＝Task 5 の注意1と同じ。
capture 経路の True 設定も Clock 経由なので、スケジュール順＝実行順で False → True が保たれる）:

```python
        def _reset_book_props(_dt):
            self.tsumego_book_ready = False
            self.tsumego_recording = False

        Clock.schedule_once(_reset_book_props, 0)
```

- [ ] **Step 2: 記録トグルのハンドラを実装**

`_do_tsumego_record_toggle` を `_do_resign`（437行付近）の後に追加:

```python
    def _do_tsumego_record_toggle(self):
        """回答帳: 「正解手順を記録」/「この手順を保存」ボタン（回答帳スペック§6）。"""
        from katrain.core import tsumego_answer_book as answer_book
        from katrain.core.tsumego_solver_api import moves_from_game

        game = self.game
        key = getattr(game, "tsumego_book_key", None)
        if not key:
            self.controls.set_status("詰碁キャプチャの出題中のみ記録できます", STATUS_INFO)
            return
        if not self.tsumego_recording:
            # 記録モード開始: root に巻き戻し、黒を人間にして黒白両方を手入力できるようにする
            self._tsumego_record_prev_black = (
                self.players_info["B"].player_type,
                self.players_info["B"].player_subtype,
            )
            self.board_gui.animating_pv = None
            game.undo(9999)
            self.update_player("B", player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL)
            Clock.schedule_once(lambda _dt: setattr(self, "tsumego_recording", True), 0)
            self.controls.set_status(
                "記録モード: アプリの正解どおりに黒白両方を打ち、終わったら「この手順を保存」",
                STATUS_INFO,
            )
            return
        # 保存
        moves = moves_from_game(game)
        Clock.schedule_once(lambda _dt: setattr(self, "tsumego_recording", False), 0)
        prev = getattr(self, "_tsumego_record_prev_black", None)
        if prev:
            self.update_player("B", player_type=prev[0], player_subtype=prev[1])
        if not moves or moves[0][1] != "B":
            self.controls.set_status("手順が空か黒番から始まっていないため記録を破棄しました", STATUS_INFO)
            return
        bk_black, bk_white, bk_size = game.tsumego_book_stones
        t0 = game.tsumego_book_transforms[0]
        line = answer_book.moves_to_canonical(moves, t0, bk_size)
        canonical_black = sorted(
            answer_book.point_to_gtp(answer_book.transform_point(p, t0, bk_size)) for p in bk_black
        )
        canonical_white = sorted(
            answer_book.point_to_gtp(answer_book.transform_point(p, t0, bk_size)) for p in bk_white
        )
        book = answer_book.get_book(lambda msg: self.log(msg, OUTPUT_INFO))
        added = book.add_line(key, bk_size, "B", canonical_black, canonical_white, line)
        game.tsumego_book_entry = book.lookup(key)  # 保存直後から再生可能（root に戻して検証できる）
        self.controls.set_status(
            f"正解手順を記録しました（{len(line)}手）" if added else "同じ手順が記録済みです",
            STATUS_INFO,
        )
```

注意:
- `PLAYER_HUMAN` / `PLAYING_NORMAL` / `STATUS_INFO` は `__main__.py` で import 済み（既存の
  capture 処理が使用）。未 import なら constants から追加する。
- 保存後に黒 AI へ戻した時点で手番が黒なら AI が着手する（記録の末尾局面）。記録は通常
  黒の最終手で終わるため次は白番＝自動着手は起きない。白で終えた場合に1手打たれるのは許容
  （スペック§6 の検証用途と同じ挙動）。

- [ ] **Step 3: gui.kv にボタンを追加**

`<BadukPanControls>`（gui.kv:216）の最後の子（`ClickableLabel` エンジン状態表示、278行〜）の
**前**に追加:

```yaml
    AutoSizedRoundedRectangleButton:
        text: i18n._('tsumego:save') if root.katrain and root.katrain.tsumego_recording else i18n._('tsumego:record')
        size_hint: None, 0.5
        pos_hint: {'center_x': 0.93, 'center_y': 0.5}
        opacity: 1 if root.katrain and root.katrain.tsumego_book_ready else 0
        disabled: not (root.katrain and root.katrain.tsumego_book_ready)
        on_left_release: root.katrain("tsumego-record-toggle")
```

エンジン状態サークル（center_x 0.85）と重なる場合は center_x を 0.94〜0.95 に調整する。
`BadukPanControls` は下部ナビで `tsumego_view`（盤面拡大）でも表示される（gui.kv:1163-1167 は
zen でのみ非表示）＝詰碁中に必ず押せる。

- [ ] **Step 4: i18n キーを追加してコンパイル**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の末尾に追加:

```po
msgid "tsumego:record"
msgstr "正解手順を記録"

msgid "tsumego:save"
msgstr "この手順を保存"
```

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po` の末尾に追加:

```po
msgid "tsumego:record"
msgstr "Record solution"

msgid "tsumego:save"
msgstr "Save solution"
```

Run: `python tools/compile_mo.py`
Expected: 全ロケールのコンパイルが成功（en/jp 以外は未翻訳キー＝キー名表示になるが、
ユーザーは jp 利用のため許容）

- [ ] **Step 5: 構文チェックと GUI 手動確認**

Run: `python -m py_compile katrain/__main__.py`
Expected: エラーなし

GUI 手動確認: `python -m katrain` →
1. 通常対局ではボタンが見えない
2. F4 で詰碁キャプチャ → ボタン「正解手順を記録」が下部ナビに出る（盤面拡大でも見える）
3. 押す → root に巻き戻り、黒白両方を手入力できる。ボタンが「この手順を保存」になる
4. 数手打って保存 → ステータス「正解手順を記録しました（N手）」、
   `~/.katrain/tsumego_answers.json` にエントリが書かれている
5. `undo` で root に戻る → 黒 AI が記録の initial 手を即打つ（ログ
   `回答帳の記録手順から着手します`）

- [ ] **Step 6: コミット**

```bash
git add katrain/__main__.py katrain/gui.kv katrain/i18n
git commit -m "feat(tsumego): 回答帳の記録ボタン（記録モード・保存・i18n）"
```

---

### Task 7: 統合検証・回帰・ドキュメント

**Files:**
- Modify: `CLAUDE.md`（概要の詰碁段落に1文追記）
- Test: 全スイート＋GUI 実機

**Interfaces:**
- Consumes: Task 1-6 の全成果物

- [ ] **Step 1: ユニットテスト全体**

Run: `pytest tests/test_tsumego_answer_book.py -v`
Expected: 全 PASS

Run: `pytest --ignore=tests/test_ai.py -q`
Expected: 従来どおり PASS（回答帳が空のとき既存経路は不変）

- [ ] **Step 2: GUI 実機の一巡（本機能の受け入れ確認）**

`python -m katrain`（debug_level 1）で:

1. 詰碁アプリの問題をキャプチャし、AI の解答を確認（従来どおり）
2. 「正解手順を記録」→ アプリの正解手順を黒白両方入力 → 保存
3. **同じ問題を別の隅で出題**させて再キャプチャ →
   ログ `tsumego_capture: 回答帳にヒット` が出て、黒が対称変換された記録手順を
   **即座に（解析待ちなしで）** 打つこと
4. 白番でわざと記録に無い応手を打つ → ログにフォールバックが出て従来パイプライン
   （ソルバ/ai:tsumego）が動くこと。記録の枝に戻したら再ヒットすること
5. 確認後 debug_level を 0 に戻す

Expected: 3 が成功（回答帳の中核価値）。1-2 と 4 の従来動作も正常。

- [ ] **Step 3: CLAUDE.md に追記**

CLAUDE.md 概要の詰碁段落（tsumego_capture の説明の末尾）に追記:

```
さらに**回答帳** `tsumego_answer_book`（誤答した問題の正解手順を画面ボタンで手動記録し、盤の8対称の正規化キーで一致する再出題に解析なし0秒で自動再生。白の応手が記録から逸脱したら従来パイプラインへ毎手フォールバック。保存先 `~/.katrain/tsumego_answers.json`、スペック `docs/superpowers/specs/2026-08-02-tsumego-answer-book-design.md`）を追加
```

- [ ] **Step 4: コミット**

```bash
git add CLAUDE.md
git commit -m "docs(tsumego): 回答帳を CLAUDE.md 概要に追記"
```
