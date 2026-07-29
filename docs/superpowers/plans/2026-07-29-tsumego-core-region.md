# 詰碁コアクラスタ検出とリージョン保証 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 詰碁キャプチャで、詰碁本体から離れた無関係な箇所の手が最善手と評価される問題を解消する。

**Architecture:** 枠退化の根本原因は (1) `cluster_gap=4` の芋づる連結でコア絞り込みが発火しない (2) 発火しても flip 再帰が全石から範囲を取り直して絞り込みを捨てる、の2段。コア石を石 dict に `tsumego_core` としてマークし（`flip_stones` は同じ dict を移すだけなのでマークは転置・反転を越えて保持される）、再帰の全段でそれを使う。加えて、リージョンが盤全体に退化した場合のフォールバックと、占有点への配石を防ぐガードを入れる。キャプチャ経路のみ枠適用後の完成局面を単一 AB/AW として作り直す。

**Tech Stack:** Python 3.12 / pytest。`katrain/core/tsumego_frame.py` は Kivy 非依存で単体テスト可能。

## Global Constraints

- 設計書: `docs/superpowers/specs/2026-07-29-tsumego-core-region-design.md`
- コミットメッセージは**日本語**、Conventional Commits 形式（`feat:`, `fix:`, `refactor:`, `test:`）
- `black` を既存ファイル全体に走らせない（コードベースが未整形のため巨大差分になる）。line-length=120 に手で合わせる
- SGF の `AE`（clear_placements）は使用禁止 — `engine.py:402-404` が AE を含む経路の解析を拒否する
- 占有点への `AB`/`AW` は同色でも `Exception("Unexpected illegal move (Space occupied)")` になる（`game.py:144-145, 164-165`）
- テスト実行は `python -m pytest tests/test_tsumego_frame.py tests/test_tsumego_capture.py -v`（humanSL モデル不要）
- 既存の 7 本の枠テストのうち **`test_9x9_margin_clamped_so_frame_fits` だけが期待値変更を伴う**。他の 6 本は不変でなければならない

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `katrain/core/tsumego_frame.py` | 枠生成・コア検出・リージョン算出（Kivy 非依存） | 修正 |
| `katrain/core/tsumego_capture.py` | 画面認識 → グリッド → SGF | 修正（グリッド公開のみ） |
| `katrain/__main__.py` | キャプチャ適用フローの配線 | 修正 |
| `tests/test_tsumego_frame.py` | 枠・コア検出・リージョンのテスト | 追記 + 1件期待値更新 |
| `tests/test_tsumego_capture.py` | 認識・リージョン解析のテスト | 追記 |

---

### Task 1: コア検出の頑健化と flip 再帰への持ち回り

**Files:**
- Modify: `katrain/core/tsumego_frame.py:47-62`（`fit_margin` が失敗時 `None` を返すよう変更）
- Modify: `katrain/core/tsumego_frame.py:65-93`（`main_cluster` を削除し `mark_core_stones` を新設）
- Modify: `katrain/core/tsumego_frame.py:109-170`（`tsumego_frame_stones` がコアマークを使う）
- Modify: `katrain/core/tsumego_frame.py:33-44`（`tsumego_frame` が `mark_core_stones` を呼ぶ）
- Test: `tests/test_tsumego_frame.py`

**Interfaces:**
- Produces:
  - `fit_margin(sizes, komi, margin, imin, jmin, imax, jmax) -> int | None` — 確保できる margin、無ければ `None`（従来は失敗時に引数の margin をそのまま返していた）
  - `mark_core_stones(stones, komi, margin) -> tuple[int, int, int, int]` — 石 dict に `tsumego_core` を立て、採用した範囲の **snap 済み** bbox `(imin, jmin, imax, jmax)` を返す。絞らなかった場合は全石の snap 済み bbox を返しマークは付けない
  - `CORE_MIN_FRACTION = 0.6` — 絞り込みで残す最小割合
- Consumes: なし

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_frame.py` の末尾に追記:

```python
def test_scattered_outliers_narrow_to_core_cluster():
    # 回帰テスト: 詰碁本体（右上26子）から離れた D10/F11/F9/G6 が cluster_gap=4 で
    # 芋づるに連結し主クラスタ=全30石になるため、枠が最下段13子だけに退化していた実例。
    # 結果リージョンが盤全体→None正規化→全盤解析となり、空き地の D8 が最善手になった。
    # gap を段階的に縮めて 26/30 に絞り、枠とリージョンが成立することを確認する
    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    board = _board(
        stones=[(ord(p[1]) - 97, ord(p[0]) - 97, "B") for p in ab]
        + [(ord(p[1]) - 97, ord(p[0]) - 97, "W") for p in aw]
    )
    blacks, whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # コア bbox(i 0..8, j 7..12) + 適応margin(4→2) → 壁は F列(j=5) と 3行目(i=10)
    assert region == ((0, 10), (5, 12))
    assert any(j == 5 for _i, j in blacks + whites)
    # 不正解手 D8 = (i=5, j=3) はリージョン外、正解手 M10 = (i=3, j=11) はリージョン内
    (i0, i1), (j0, j1) = region
    assert not (i0 <= 5 <= i1 and j0 <= 3 <= j1)
    assert i0 <= 3 <= i1 and j0 <= 11 <= j1
    # 枠が退化していない（修正前は最下段13子のみだった）
    assert len(blacks) + len(whites) > 40
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_frame.py::test_scattered_outliers_narrow_to_core_cluster -v`
Expected: FAIL — `assert ((0, 12), (0, 12)) == ((0, 10), (5, 12))`

- [ ] **Step 3: `fit_margin` が失敗時 `None` を返すようにする**

`katrain/core/tsumego_frame.py:47-62` を置き換え:

```python
def fit_margin(sizes, komi, margin, imin, jmin, imax, jmax):
    """外側（枠矩形の外）に守り側の代償地帯 defense_area 相当が確保できる最大の margin を返す。

    put_outside は外側セルを守り側に defense_area（約 (盤面積-コミ-5)/2 ）だけ配分する設計
    だが、外側がそれ未満だと配分しきれず枠ゲームが一方的になる。確保できる margin がない
    場合は None を返す（呼び出し側が元の margin にフォールバックする）。
    """
    isize, jsize = sizes
    needed = (isize * jsize - abs(komi) - offence_to_win) / 2
    for m in range(margin, 0, -1):
        i0, i1 = max(0, imin - m), min(isize - 1, imax + m)
        j0, j1 = max(0, jmin - m), min(jsize - 1, jmax + m)
        outside = isize * jsize - (i1 - i0 + 1) * (j1 - j0 + 1)
        if outside >= needed:
            return m
    return None
```

- [ ] **Step 4: `main_cluster` を `mark_core_stones` に置き換える**

`katrain/core/tsumego_frame.py:65-93` の `main_cluster` 全体を次で置き換え:

```python
def snapped_bbox(entries, sizes):
    """(i, j, ...) の列から、端スナップ済みの bbox (imin, jmin, imax, jmax) を返す"""
    isize, jsize = sizes
    return (
        snap0(min(e[0] for e in entries)),
        snap0(min(e[1] for e in entries)),
        snapS(max(e[0] for e in entries), isize),
        snapS(max(e[1] for e in entries), jsize),
    )


def mark_core_stones(stones, komi, margin):
    """詰碁本体（コア）の石に tsumego_core を立て、採用範囲の snap 済み bbox を返す。

    全石の bbox で枠が成立する（fit_margin が margin を返す）なら絞らない＝従来動作。
    成立しないときだけ、近接クラスタの gap を段階的に縮めて本体を切り出す。

    gap を小さくすると最大クラスタは縮み bbox も縮むので外側面積は増える＝面積テストは
    gap に対して単調。よって「降順で最初に通る gap」＝「通る中で最大の gap」であり、
    石対の距離を1回だけ走査して gap 昇順に増分 union すれば O(n^2) 1パスで求まる。

    マークは石の dict に付ける。flip_stones は同じ dict オブジェクトを新しい配列へ移すだけ
    なので、マークは転置・反転を越えて tsumego_frame_stones の再帰の全段で保持される。
    """
    sizes = ij_sizes(stones)
    entries = [(i, j, h) for i, row in enumerate(stones) for j, h in enumerate(row) if h.get("stone")]
    if not entries:
        return (0, 0, 0, 0)
    all_bbox = snapped_bbox(entries, sizes)
    if fit_margin(sizes, komi, margin, *all_bbox) is not None:
        return all_bbox

    n = len(entries)
    edges = [[] for _ in range(cluster_gap + 1)]
    for a in range(n):
        ia, ja, _h = entries[a]
        for b in range(a + 1, n):
            d = max(abs(ia - entries[b][0]), abs(ja - entries[b][1]))
            if d <= cluster_gap:
                edges[d].append((a, b))
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    best = None
    for gap in range(1, cluster_gap + 1):
        for a, b in edges[gap]:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
        groups = {}
        for a in range(n):
            groups.setdefault(find(a), []).append(entries[a])
        # 同数クラスタのタイは bbox が小さい方 → 上 → 左 の順で決定的に選ぶ
        cand = max(groups.values(), key=lambda g: (len(g), -bbox_area(g), -g[0][0], -g[0][1]))
        if len(cand) < n * CORE_MIN_FRACTION:
            continue  # 本体を切り捨てすぎ。全盤に広がる詰碁を1子まで削る事故を防ぐ
        if fit_margin(sizes, komi, margin, *snapped_bbox(cand, sizes)) is not None:
            best = cand  # gap 昇順ループなので、最後に通ったものが「通る中で最大の gap」

    if best is None or len(best) == n:
        return all_bbox
    for _i, _j, h in best:
        h["tsumego_core"] = True
    return snapped_bbox(best, sizes)


def bbox_area(entries):
    i = [e[0] for e in entries]
    j = [e[1] for e in entries]
    return (max(i) - min(i) + 1) * (max(j) - min(j) + 1)
```

`katrain/core/tsumego_frame.py:9` の定数群に追記:

```python
cluster_gap = 4  # 主クラスタ判定: この距離(Chebyshev)以内の石を同一クラスタとみなす
CORE_MIN_FRACTION = 0.6  # コア絞り込みで残す最小割合。本体を削りすぎる縮小を却下する
```

- [ ] **Step 5: `tsumego_frame_stones` がコアマークを使うようにする**

`katrain/core/tsumego_frame.py:112-149`（`ijs = [...]` から `margin = fit_margin(...)` まで）を置き換え:

```python
    all_ijs = [
        {"i": i, "j": j, "black": h.get("black"), "core": h.get("tsumego_core")}
        for i, row in enumerate(stones)
        for j, h in enumerate(row)
        if h.get("stone")
    ]

    if len(all_ijs) == 0:
        return []

    # コア石がマークされていればそれだけで範囲を取る。マークは石の dict に付いており
    # flip_stones は同じ dict を移すだけなので、転置・反転を越えて再帰の全段で保持される
    # （これが無いと絞り込みが1段目で失われ、枠が全石の bbox に戻って退化する）
    ijs = [z for z in all_ijs if z["core"]] or all_ijs

    def problem_range(zs):
        top = min_by(zs, "i", +1)
        left = min_by(zs, "j", +1)
        bottom = min_by(zs, "i", -1)
        right = min_by(zs, "j", -1)
        return (
            [top, bottom, left, right],
            snap0(top["i"]),
            snap0(left["j"]),
            snapS(bottom["i"], isize),
            snapS(right["j"], jsize),
        )

    # find range of problem
    extrema, imin, jmin, imax, jmax = problem_range(ijs)
    top, bottom, left, right = extrema
    # 適応margin: bbox+margin で外側（守り側の代償地帯）が必要面積を下回る大型詰碁では、
    # 枠ゲームが一方的（±100点級）になり勝率が飽和し、死活より空き地・小さい得が優先される。
    # 外側が確保できるまで margin を縮める。どの margin でも確保できない盤（9路など）は
    # 従来値を維持する（縮めても焼け石に水で、既存挙動を変えないため）
    margin = fit_margin(sizes, komi, margin, imin, jmin, imax, jmax) or margin
```

- [ ] **Step 6: `tsumego_frame` から `mark_core_stones` を呼ぶ**

`katrain/core/tsumego_frame.py:33-44` の `tsumego_frame` を置き換え:

```python
def tsumego_frame(bw_board, komi, black_to_play_p, ko_p, margin):
    # 9路以下では margin=4（13/19路向け）だと枠矩形が盤外にはみ出して壁・充填が置けず、
    # 解析リージョンも全盤（→None正規化→全盤解析）に退化するため、収まる値にクランプする
    if min(ij_sizes(bw_board)) <= 9:
        margin = min(margin, 2)
    stones = stones_from_bw_board(bw_board)
    mark_core_stones(stones, komi, margin)
    filled_stones = tsumego_frame_stones(stones, komi, black_to_play_p, ko_p, margin)
    region_pos = pick_all(filled_stones, "tsumego_frame_region_mark")
    bw = pick_all(filled_stones, "tsumego_frame")
    blacks = [(i, j) for i, j, black in bw if black]
    whites = [(i, j) for i, j, black in bw if not black]
    return (blacks, whites, get_analysis_region(region_pos))
```

- [ ] **Step 7: 新しいテストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_frame.py::test_scattered_outliers_narrow_to_core_cluster -v`
Expected: PASS

- [ ] **Step 8: 既存テストを実行し、9路テストだけが落ちることを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -v`
Expected: 7 passed, 1 failed — `test_9x9_margin_clamped_so_frame_fits` が
`assert ((0, 8), (0, 4)) == ((0, 8), (0, 7))` で失敗。他は全て PASS。

**他のテストも落ちた場合は実装が間違っている。期待値を書き換えて通してはならない。**

- [ ] **Step 9: 9路テストの期待値を更新する**

この1件は意図した改善。9路の全石 bbox(i 0..8, j 0..5) は margin 2 でも外側 9目しか残らず
（必要 34.5目）勝率が飽和していた。コアを 10/11 に絞ると bbox(j 0..3) + margin 1 で
外側 36目 ≥ 34.5目 となり枠バランスが成立する。テストの本来の意図
（リージョンが全盤にならない・壁が盤内に置かれる）は保たれる。

`tests/test_tsumego_frame.py:35-50` の `test_9x9_margin_clamped_so_frame_fits` を置き換え:

```python
def test_9x9_margin_clamped_so_frame_fits():
    # 回帰テスト: 9路でmargin=4は枠矩形が全方向で盤外にはみ出し、壁・充填が一切置けず
    # リージョンも全盤（→None正規化→全盤解析）になっていた。9路以下はmarginを2に
    # クランプして壁+リージョンが成立するようにする（左半分を占める詰碁の実例形）
    board = _board(
        size=9,
        stones=[
            (2, 2, "W"), (3, 1, "W"), (4, 0, "B"), (4, 1, "B"), (4, 2, "W"),
            (5, 1, "B"), (5, 3, "W"), (6, 2, "B"), (7, 1, "W"), (7, 5, "W"), (8, 1, "B"),
        ],
    )
    blacks, whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # 全石bbox(j 0..5)ではクランプ後margin 2でも外側9目のみ（必要34.5目）で勝率が飽和する。
    # 孤立した (7,5) を落として 10/11 に絞ると bbox(j 0..3)+margin1 で外側36目を確保できる
    assert region == ((0, 8), (0, 4))
    # 壁が盤内（j=4列）に置かれ、枠として機能する
    assert any(j == 4 for _i, j in blacks + whites)
```

- [ ] **Step 10: 枠テスト全体が通ることを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -v`
Expected: 8 passed

- [ ] **Step 11: コミット**

```bash
git add katrain/core/tsumego_frame.py tests/test_tsumego_frame.py
git commit -m "fix(tsumego_frame): コア検出をflip再帰に持ち回り枠退化を解消

cluster_gap=4では離れ石が芋づるに連結して主クラスタ=全石になり絞り込みが
発火しない。発火してもtsumego_frame_stonesはflip再帰の各段でproblem_rangeを
全石から取り直すため絞り込みが1段目で失われていた。コア石をdictにマークし
（flip_stonesは同じdictを移すのでマークは転置を越えて保持される）再帰の全段で
使う。gapは面積テストが通らないときだけ段階的に縮める（増分unionでO(n^2)1パス）。

9路テストの期待値を更新: 全石bboxは外側9目（必要34.5目）で飽和していたが
コアを10/11に絞ると外側36目を確保でき、枠バランスが成立する。"
```

---

### Task 2: リージョンが盤全体に退化したときのフォールバック

**Files:**
- Modify: `katrain/core/tsumego_frame.py`（`tsumego_frame` と新規ヘルパー）
- Test: `tests/test_tsumego_frame.py`

**Interfaces:**
- Consumes: `mark_core_stones(stones, komi, margin) -> (imin, jmin, imax, jmax)`（Task 1）
- Produces: `fallback_region(core_bbox, sizes) -> ((i0, i1), (j0, j1)) | None`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_frame.py` の末尾に追記:

```python
def test_region_falls_back_to_core_bbox_when_frame_covers_board():
    # 横方向に全幅、縦は中央付近に収まる詰碁では、どのmarginでも外側面積が足りず
    # fit_margin が縮められないため枠矩形が盤全体に膨らみ、リージョンが全盤になる
    # （→ set_region_of_interest が None 正規化 → 全盤解析）。コアbbox+padで下限を保証する
    board = _board(stones=[(3, 0, "B"), (3, 12, "W"), (9, 0, "W"), (9, 12, "B"), (6, 6, "B")])
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    # コアbbox(i 3..9, j 0..12) + pad2 → i 1..11 に縮み、縦が盤より小さいので全盤にならない
    assert region == ((1, 11), (0, 12))


def test_region_fallback_declines_when_problem_reaches_edges():
    # 端に届く詰碁では snap により bbox が全盤になるため、フォールバックは働かず
    # 全盤リージョンのまま返す（端の手を候補から外すのは危険なため）
    board = _board(stones=[(1, 1, "B"), (1, 11, "W"), (11, 1, "W"), (11, 11, "B")])
    _blacks, _whites, region = tsumego_frame(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    assert region == ((0, 12), (0, 12))
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -k fallback -v`
Expected: `test_region_falls_back_to_core_bbox_when_frame_covers_board` が FAIL
（`assert ((0, 12), (0, 12)) == ((1, 11), (0, 12))`）、
`test_region_fallback_declines_when_problem_reaches_edges` は PASS

- [ ] **Step 3: `fallback_region` を実装する**

`katrain/core/tsumego_frame.py` の `get_analysis_region` の直後に追記:

```python
def covers_board_p(region, sizes):
    (i0, i1), (j0, j1) = region
    isize, jsize = sizes
    # game.set_region_of_interest が None 正規化する条件と同じ（縦横とも盤以上）
    return i1 - i0 + 1 >= isize and j1 - j0 + 1 >= jsize


def fallback_region(core_bbox, sizes):
    """枠由来のリージョンが盤全体に退化したときの下限。コア bbox + pad を縮めながら試す。

    bbox は snap 済みなので、端に届く詰碁では全 pad が盤全体になり None を返す
    （端の手を候補から外すと正解手を落としかねないため、その場合は全盤解析に委ねる）。
    """
    isize, jsize = sizes
    imin, jmin, imax, jmax = core_bbox
    for pad in (2, 1, 0):
        i0, i1 = max(0, imin - pad), min(isize - 1, imax + pad)
        j0, j1 = max(0, jmin - pad), min(jsize - 1, jmax + pad)
        if i0 >= i1 or j0 >= j1:
            continue  # get_analysis_region と同じく1線に退化した範囲は使わない
        if not covers_board_p(((i0, i1), (j0, j1)), sizes):
            return ((i0, i1), (j0, j1))
    return None
```

- [ ] **Step 4: `tsumego_frame` から呼ぶ**

`tsumego_frame` の末尾3行を置き換え（Task 1 Step 6 で書いた形が前提）:

```python
    stones = stones_from_bw_board(bw_board)
    core_bbox = mark_core_stones(stones, komi, margin)
    filled_stones = tsumego_frame_stones(stones, komi, black_to_play_p, ko_p, margin)
    region_pos = pick_all(filled_stones, "tsumego_frame_region_mark")
    bw = pick_all(filled_stones, "tsumego_frame")
    blacks = [(i, j) for i, j, black in bw if black]
    whites = [(i, j) for i, j, black in bw if not black]
    sizes = ij_sizes(bw_board)
    region = get_analysis_region(region_pos)
    if not region or covers_board_p(region, sizes):
        region = fallback_region(core_bbox, sizes) or region
    return (blacks, whites, region)
```

- [ ] **Step 5: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -v`
Expected: 10 passed

- [ ] **Step 6: コミット**

```bash
git add katrain/core/tsumego_frame.py tests/test_tsumego_frame.py
git commit -m "feat(tsumego_frame): リージョン退化時にコアbboxへフォールバック

どのmarginでも外側面積を確保できない詰碁では枠矩形が盤全体に膨らみ、
リージョンが全盤→None正規化→全盤解析になる。コアbbox+pad(2/1/0)で
盤より小さい範囲を探し、遠方の手が候補から消える下限を保証する。
bboxはsnap済みなので端に届く詰碁ではフォールバックせず全盤解析に委ねる。"
```

---

### Task 3: 占有点への配石を防ぐガード（手動フロー）

**Files:**
- Modify: `katrain/core/tsumego_frame.py:15-26`（`tsumego_frame_from_katrain_game`）
- Test: `tests/test_tsumego_frame.py`

**Interfaces:**
- Consumes: `tsumego_frame(bw_board, komi, black_to_play_p, ko_p, margin) -> (blacks, whites, region)`
- Produces: なし（既存シグネチャ不変）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_frame.py` の先頭の import に追記:

```python
from katrain.core.game import BaseGame, KaTrainSGF
from katrain.core.tsumego_frame import tsumego_frame, tsumego_frame_from_katrain_game
```

末尾に追記:

```python
class _StubKatrain:
    def log(self, *_args, **_kwargs):
        pass

    def config(self, *_args, **_kwargs):
        return None


@pytest.mark.parametrize("target", [20, 60, 100])
def test_manual_frame_never_places_on_occupied_point(target):
    # 回帰テスト: put_border は既存石をチェックせず上書きするため、壁が石を踏むと
    # 占有点への AB/AW になり _init_chains が "Space occupied" で落ちる（同色でも落ちる）。
    # 従来は枠が退化して石をほとんど置かないため顕在化していなかったが、
    # コア検出の修正で枠が張れるようになると実戦の密な局面で踏む
    root = KaTrainSGF.parse_file("tests/data/ogs.sgf")
    game = BaseGame(_StubKatrain(), move_tree=root)
    for _ in range(target):
        if not game.current_node.children:
            break
        game.set_current_node(game.current_node.children[0])
    occupied = {s.coords for s in game.stones}
    node, _region = tsumego_frame_from_katrain_game(game, 6.5, True, ko_p=False, margin=4)
    placed = [m.coords for m in node.placements]
    assert not (set(placed) & occupied), "枠石が既存石と重なっている"
    assert len(placed) == len(set(placed)), "枠石に重複座標がある"
    game.set_current_node(node)  # ここで例外が出なければ配置が正当
```

**リージョンについては何も assert しないこと。** 実戦の密な局面では全石が1つの塊で
コア絞り込みが働かず（`CORE_MIN_FRACTION` に届かない）、`fallback_region` も
snap 済み bbox が盤全体になるため、リージョンは全盤のまま＝退化したままになる。
これは手動フローの枠が実戦局面では原理的に張れないことの反映であり、このタスクの
対象外。ここで「退化しないこと」を要求すると実装が誤った方向へ進む。

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -k occupied -v`
Expected: 少なくとも1つの `target` で FAIL（`枠石が既存石と重なっている` または
`Exception: Unexpected illegal move (Space occupied)`）

- [ ] **Step 3: 重複を除外する**

`katrain/core/tsumego_frame.py:15-26` の `tsumego_frame_from_katrain_game` を置き換え:

```python
def tsumego_frame_from_katrain_game(game, komi, black_to_play_p, ko_p, margin):
    current_node = game.current_node
    bw_board = [[game.chains[c][0].player if c >= 0 else "-" for c in line] for line in game.board]
    isize, jsize = ij_sizes(bw_board)
    blacks, whites, analysis_region = tsumego_frame(bw_board, komi, black_to_play_p, ko_p, margin)

    # 既存石と重なる枠石は配置しない。占有点への AB/AW は同色でも
    # _validate_move_and_update_chains が "Space occupied" で弾き、
    # _init_chains が Exception に昇格させてゲームが壊れる
    occupied = {(i, j) for i, row in enumerate(bw_board) for j, v in enumerate(row) if v != "-"}
    blacks = [ij for ij in blacks if ij not in occupied]
    whites = [ij for ij in whites if ij not in occupied]

    sgf_blacks = katrain_sgf_from_ijs(blacks, isize, jsize, "B")
    sgf_whites = katrain_sgf_from_ijs(whites, isize, jsize, "W")

    played_node = GameNode(parent=current_node, properties={"AB": sgf_blacks, "AW": sgf_whites})  # this inserts

    katrain_region = analysis_region and (analysis_region[1], analysis_region[0])
    return (played_node, katrain_region)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -v`
Expected: 13 passed

- [ ] **Step 5: コミット**

```bash
git add katrain/core/tsumego_frame.py tests/test_tsumego_frame.py
git commit -m "fix(tsumego_frame): 既存石と重なる枠石を配置しない

put_borderは既存石をチェックせず上書きするため、壁が石を踏むと占有点への
AB/AWになり同色でも Space occupied で落ちる。従来は枠が退化して石を
ほとんど置かず顕在化しなかったが、コア検出修正で枠が張れるようになると
実戦の密な局面で踏む。重なる枠石をplacementから除外する。"
```

---

### Task 4: 非コア石の除去と盤面 API

**Files:**
- Modify: `katrain/core/tsumego_frame.py`（`tsumego_frame_stones` に `drop_non_core`、`tsumego_frame_board` 新設）
- Test: `tests/test_tsumego_frame.py`

**Interfaces:**
- Consumes: `mark_core_stones`, `fallback_region`, `covers_board_p`（Task 1-2）
- Produces:
  - `tsumego_frame_board(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core=True) -> (bw_board, region)`
    完成した盤グリッド（`"B"`/`"W"`/`"-"`）と region を返す
  - `strictly_inside_p(i, j, region) -> bool`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_frame.py` の import に `tsumego_frame_board` を追加し、末尾に追記:

```python
def _scattered_outlier_board():
    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    return _board(
        stones=[(ord(p[1]) - 97, ord(p[0]) - 97, "B") for p in ab]
        + [(ord(p[1]) - 97, ord(p[0]) - 97, "W") for p in aw]
    )


def test_drop_non_core_stones_clears_boundary_and_outside():
    # drop_non_core_stones の単体確認: 枠矩形の境界線上と外側の非コア石だけを消す
    from katrain.core.tsumego_frame import drop_non_core_stones

    stones = [[{} for _ in range(13)] for _ in range(13)]
    core = {"stone": True, "black": True, "tsumego_core": True}
    stones[6][8] = dict(core)  # コア石（枠内）
    stones[6][5] = {"stone": True, "black": True}  # 境界線上(j=5)の非コア石
    stones[6][2] = {"stone": True, "black": False}  # 枠外の非コア石
    stones[6][7] = {"stone": True, "black": False}  # 枠内の非コア石
    drop_non_core_stones(stones, (13, 13), [0, 10, 5, 12])
    assert stones[6][5] == {}, "境界線上の非コア石が残っている"
    assert stones[6][2] == {}, "枠外の非コア石が残っている"
    assert stones[6][7].get("stone"), "枠内の非コア石まで消している"
    assert stones[6][8].get("stone"), "コア石を消している"


def test_frame_board_drops_non_core_stones_outside_frame():
    # 枠線上・枠外の非コア石を除去する。壁が石を踏まなくなり充填も穴なしになる。
    # 枠内に残る非コア石（G6）はそのまま。除去にAEは使えない（engine.pyがAEを含む
    # 経路の解析を拒否する）ため、完成局面を単一のAB/AWとして作り直す前提
    board = _scattered_outlier_board()
    out, region = tsumego_frame_board(board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4)
    assert region == ((0, 10), (5, 12))
    # F11(2,5) と F9(4,5) は壁(F列)の上 → 除去され、攻め側の色で揃った壁になる
    assert board[2][5] == "B" and board[4][5] == "W"
    wall = {out[i][5] for i in range(0, 11)}
    assert wall in ({"B"}, {"W"}), f"壁が単色で揃っていない: {wall}"
    # G6(7,6) は枠内なのでそのまま残る
    assert out[7][6] == "W"
    # コア石は一切変わらない
    for i, j in [(0, 11), (1, 9), (3, 8), (4, 9), (8, 10), (8, 11)]:
        assert out[i][j] == board[i][j]


def test_frame_board_keeps_stones_when_drop_disabled():
    board = _scattered_outlier_board()
    out, _region = tsumego_frame_board(
        board, komi=7.0, black_to_play_p=True, ko_p=False, margin=4, drop_non_core=False
    )
    # 除去しない場合、枠外の D10 は put_outside のガードで残る
    assert out[3][3] == "B"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -k frame_board -v`
Expected: FAIL — `ImportError: cannot import name 'tsumego_frame_board'`

- [ ] **Step 3: `drop_non_core` を `tsumego_frame_stones` に通す**

`katrain/core/tsumego_frame.py` の `tsumego_frame_stones` のシグネチャと再帰・終端部を修正:

```python
def tsumego_frame_stones(stones, komi, black_to_play_p, ko_p, margin, drop_non_core=False):
```

再帰呼び出し（`filed = tsumego_frame_stones(flipped, ...)` の行）を:

```python
    if True in flip_spec:
        flipped = flip_stones(stones, flip_spec)
        filled = tsumego_frame_stones(flipped, komi, black_to_play_p, ko_p, margin, drop_non_core)
        return flip_stones(filled, flip_spec)
```

終端部の `put_border` の直前に追記:

```python
    black_to_attack_p = guess_black_to_attack([top, bottom, left, right], sizes)
    if drop_non_core:
        drop_non_core_stones(stones, sizes, frame_range)
    put_border(stones, sizes, frame_range, black_to_attack_p)
```

`inside_p` の直後に追記:

```python
def strictly_inside_p(i, j, region):
    i0, i1, j0, j1 = region
    return i0 < i and i < i1 and j0 < j and j < j1


def drop_non_core_stones(stones, sizes, frame_range):
    """枠矩形の境界線上および外側にある非コア石を盤から除く。

    put_border より先に呼ぶことで壁が既存石を踏まなくなり（占有点クラッシュの構造的解消）、
    put_outside の「既存石を残す」ガードにも引っかからないので充填が穴なしになる。
    壁はコア bbox から margin>=1 離れているので、コア石が消えることはない。
    """
    isize, jsize = sizes
    for i in range(isize):
        for j in range(jsize):
            h = stones[i][j]
            if h.get("stone") and not h.get("tsumego_core") and not strictly_inside_p(i, j, frame_range):
                stones[i][j] = {}
```

- [ ] **Step 4: `tsumego_frame` と `tsumego_frame_board` を共通化して実装する**

`tsumego_frame` を次の2関数に置き換え（`tsumego_frame` のシグネチャと戻り値は不変）:

```python
def build_frame(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core):
    """枠を張って (完成した石配列, region) を返す。tsumego_frame / tsumego_frame_board の共通部"""
    sizes = ij_sizes(bw_board)
    # 9路以下では margin=4（13/19路向け）だと枠矩形が盤外にはみ出して壁・充填が置けず、
    # 解析リージョンも全盤（→None正規化→全盤解析）に退化するため、収まる値にクランプする
    if min(sizes) <= 9:
        margin = min(margin, 2)
    stones = stones_from_bw_board(bw_board)
    core_bbox = mark_core_stones(stones, komi, margin)
    filled_stones = tsumego_frame_stones(stones, komi, black_to_play_p, ko_p, margin, drop_non_core)
    region = get_analysis_region(pick_all(filled_stones, "tsumego_frame_region_mark"))
    if not region or covers_board_p(region, sizes):
        region = fallback_region(core_bbox, sizes) or region
    return (filled_stones, region)


def tsumego_frame(bw_board, komi, black_to_play_p, ko_p, margin):
    filled_stones, region = build_frame(bw_board, komi, black_to_play_p, ko_p, margin, False)
    bw = pick_all(filled_stones, "tsumego_frame")
    blacks = [(i, j) for i, j, black in bw if black]
    whites = [(i, j) for i, j, black in bw if not black]
    return (blacks, whites, region)


def tsumego_frame_board(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core=True):
    """枠適用後の完成した盤グリッド ("B"/"W"/"-") と region を返す。

    キャプチャ経路はこれを単一の AB/AW として SGF 化し新規局にする。既存局面に枠ノードを
    足す方式と違い、非コア石の除去ができ（SGF の AE は engine.py が解析を拒否するため使えない）、
    占有点への重複配置も構造的に起きない。
    """
    filled_stones, region = build_frame(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core)
    board = [
        [(BLACK if h.get("black") else WHITE) if h.get("stone") else "-" for h in row] for row in filled_stones
    ]
    return (board, region)
```

- [ ] **Step 5: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -v`
Expected: 15 passed

- [ ] **Step 6: 完成盤に不整合がないことを目視確認**

Run:
```bash
python -c "
from katrain.core.tsumego_frame import tsumego_frame_board
ab='la jb kb fc hc ic jc dd id je jf kf jg jh ki li'.split()
aw='lb mb kc hd jd kd fe he ie ke lf kg lg gh'.split()
b=[['-']*13 for _ in range(13)]
for p in ab: b[ord(p[1])-97][ord(p[0])-97]='B'
for p in aw: b[ord(p[1])-97][ord(p[0])-97]='W'
out,region=tsumego_frame_board(b,7.0,True,False,4)
for r in out: print(' '.join(r))
print('region',region)
"
```
Expected: 13行の盤が表示され、A〜E列と1〜2行目が充填石で埋まり、F列と3行目に壁が立ち、
`region ((0, 10), (5, 12))` が出る。右上の詰碁本体（コア石）が入力と一致している。

- [ ] **Step 7: コミット**

```bash
git add katrain/core/tsumego_frame.py tests/test_tsumego_frame.py
git commit -m "feat(tsumego_frame): 非コア石の除去と完成盤を返す tsumego_frame_board を追加

枠線上・枠外の非コア石を put_border より先に除去する。壁が既存石を踏まなくなり
占有点クラッシュが構造的に消え、put_outside の充填も穴なしになる。
完成局面を単一のAB/AWとして作り直すための盤グリッドAPIを追加（SGFのAEは
engine.pyがAEを含む経路の解析を拒否するため除去に使えない）。"
```

---

### Task 5: キャプチャ適用フローを完成局面の再構築方式にする

**Files:**
- Modify: `katrain/core/tsumego_capture.py:195-202`（`capture_tsumego_sgf` → `capture_tsumego_grid`）
- Modify: `katrain/__main__.py:698-725`（`_tsumego_capture_trigger` がグリッドを渡す）
- Modify: `katrain/__main__.py:732-763`（`_do_tsumego_capture_apply` が完成局面を作る）
- Test: `tests/test_tsumego_capture.py`

**Interfaces:**
- Consumes: `tsumego_frame_board(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core=True) -> (board, region)`（Task 4）
- Produces: `capture_tsumego_grid(settings) -> list[list[str]]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_capture.py` の末尾に追記:

```python
def test_capture_tsumego_grid_returns_recognized_grid(monkeypatch):
    # キャプチャ経路は枠適用にグリッドが必要なので、認識までを返す関数に置き換える
    # （SGF文字列を経由すると枠適用前に局面が確定してしまい、非コア石を除去できない）
    from katrain.core import tsumego_capture as tc

    grid = [["." for _ in range(9)] for _ in range(9)]
    grid[4][4] = "B"
    monkeypatch.setattr(tc, "find_window_rect", lambda _t: (0, 0, 100, 100))
    monkeypatch.setattr(tc, "capture_screen_rect", lambda _r: None)
    monkeypatch.setattr(tc, "detect_board", lambda _i: (0, 0, 99, 99))
    monkeypatch.setattr(tc, "detect_size_and_classify", lambda _i, _r, _s: (9, grid))

    assert tc.capture_tsumego_grid({"window_title": "X"}) == grid


def test_framed_grid_round_trips_through_sgf():
    # キャプチャ経路: 認識グリッド → 枠適用 → 完成グリッド → 単一AB/AWのSGF → KaTrainで読める
    # （占有点への重複配置がないことを、実際にゲームを構築して確認する）
    from katrain.core.game import BaseGame, KaTrainSGF
    from katrain.core.tsumego_frame import tsumego_frame_board

    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    grid = [["." for _ in range(13)] for _ in range(13)]
    for p in ab:
        grid[ord(p[1]) - 97][ord(p[0]) - 97] = "B"
    for p in aw:
        grid[ord(p[1]) - 97][ord(p[0]) - 97] = "W"

    framed, region = tsumego_frame_board(grid, 7.0, True, False, 4)
    assert region == ((0, 10), (5, 12))

    class _Stub:
        def log(self, *_a, **_k):
            pass

        def config(self, *_a, **_k):
            return None

    root = KaTrainSGF.parse_sgf(grid_to_sgf(framed, komi=7.0))
    game = BaseGame(_Stub(), move_tree=root)  # 重複配置があればここで例外
    expected = sum(1 for row in framed for v in row if v in ("B", "W"))
    assert len(game.stones) == expected
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_capture.py -k "capture_tsumego_grid or round_trips" -v`
Expected: `test_capture_tsumego_grid_returns_recognized_grid` が FAIL
（`AttributeError: module 'katrain.core.tsumego_capture' has no attribute 'capture_tsumego_grid'`）。
`test_framed_grid_round_trips_through_sgf` は Task 4 完了済みなら PASS する
（キャプチャ側の配線が依存する契約を固定するテストのため）

- [ ] **Step 3: `capture_tsumego_sgf` を `capture_tsumego_grid` に置き換える**

`katrain/core/tsumego_capture.py:195-202` を置き換え:

```python
def capture_tsumego_grid(settings):
    """ウィンドウ検出→キャプチャ→認識を行い、認識グリッドを返す。失敗は CaptureError。

    SGF ではなくグリッドを返すのは、呼び出し側が枠適用（非コア石の除去を含む）を
    してから局面を確定する必要があるため。
    """
    rect = find_window_rect(settings.get("window_title", DEFAULT_WINDOW_TITLE))
    img = capture_screen_rect(rect)
    board_rect = detect_board(img)
    sizes = [int(s) for s in (settings.get("board_sizes") or DEFAULT_BOARD_SIZES)]
    _size, grid = detect_size_and_classify(img, board_rect, sizes)
    return grid
```

`capture_tsumego_sgf` は削除する（唯一の呼び出し元だった `__main__.py:713` が
`capture_tsumego_grid` に移り、CLI の `main()` は `detect_size_and_classify` と
`grid_to_sgf` を直接呼んでいるため未使用になる）。

Run: `grep -rn "capture_tsumego_sgf" --include=*.py .`
Expected: 出力なし（残っていたらその呼び出し元も直すこと）

- [ ] **Step 4: ホットキー経路がグリッドを渡すようにする**

`katrain/__main__.py:701` の import を差し替え:

```python
        from katrain.core.tsumego_capture import CaptureError, capture_tsumego_grid
```

`katrain/__main__.py:711-723` の try ブロックを置き換え:

```python
            settings = self._config.get("tsumego_capture") or {}
            try:
                grid = capture_tsumego_grid(settings)
            except CaptureError as e:
                self._tsumego_capture_failed(f"詰碁キャプチャ失敗: {e}")
                return
            except Exception as e:
                self._tsumego_capture_failed(f"詰碁キャプチャで予期しないエラー: {e}")
                return
            self("tsumego-capture-apply", grid, ko, margin)
```

（`ko` / `margin` を settings から読む既存行はそのまま残す。`komi=self.config(...)` の
引数は `capture_tsumego_grid` では不要になるため削除する）

- [ ] **Step 5: `_do_tsumego_capture_apply` を完成局面の再構築にする**

`katrain/__main__.py:732-749`（`def _do_tsumego_capture_apply` から `self._do_tsumego_frame(...)` まで）を置き換え:

```python
    def _do_tsumego_capture_apply(self, grid, ko, margin):
        # メッセージループスレッドで実行。認識グリッドに枠を適用した「完成局面」を単一の
        # AB/AW として新規局にする（枠ノードを足す方式と違い、枠外の無関係な石を除去でき、
        # 占有点への重複配置も起きない）。new-game と解析発行は同一メッセージ内で行う
        # （分割すると new-game で game_id が変わり後続メッセージが破棄されるため）
        from katrain.core.tsumego_capture import grid_to_sgf
        from katrain.core.tsumego_frame import tsumego_frame_board

        komi = self.config("game/komi", 6.5)
        framed, analysis_region = tsumego_frame_board(grid, komi, True, ko_p=ko, margin=margin)
        try:
            move_tree = KaTrainSGF.parse_sgf(grid_to_sgf(framed, komi=komi))
        except ParseError as e:
            self.log(f"詰碁キャプチャSGF解析失敗: {e}", OUTPUT_ERROR)
            return
        self._do_new_game(move_tree=move_tree)
        settings = self._config.get("tsumego_capture") or {}
        try:
            # 詰碁の正解手判定用に、初期解析＋以降の毎手のリージョン解析を深掘り専用クエリ
            # （visits指定・時間無制限・wideRootNoise=0）にする。0以下で既定解析にフォールバック
            deep_visits = int(settings.get("analysis_visits", 1800))
            self.game.region_analysis_visits = deep_visits if deep_visits > 0 else None
        except (TypeError, ValueError):
            self.game.region_analysis_visits = None
        self._apply_tsumego_region(analysis_region)
```

`_do_tsumego_frame` の直後に、リージョン設定と2段解析だけを行うヘルパーを追加:

```python
    def _apply_tsumego_region(self, analysis_region):
        """リージョンを設定し、全盤fast → リージョン限定の2段解析を発行する"""
        node = self.game.current_node
        if self.play_mode.mode == MODE_PLAY:
            self.play_mode.switch_ui_mode()  # go to analysis mode
        if analysis_region:
            self.game.set_region_of_interest(
                [analysis_region[1][0], analysis_region[1][1], analysis_region[0][0], analysis_region[0][1]]
            )
        engine = self.game.engines[node.next_player]
        if self.game.region_of_interest:
            # Game.play() と同じ2段構え: 全盤の高速解析で root 勝率を得てから、リージョン限定で本解析
            # （これがないと初期解析が全盤対象になり、枠外の詰め物エリアの手が最善手として表示される）
            deep_visits = self.game.region_analysis_visits
            node.analyze(engine, analyze_fast=True)
            node.analyze(
                engine,
                region_of_interest=self.game.region_of_interest,
                visits=deep_visits,
                time_limit=deep_visits is None,
                extra_settings={"wideRootNoise": 0.0} if deep_visits else None,
            )
        else:
            node.analyze(engine)
        self.update_state(redraw_board=True)
```

**注意:** `tsumego_frame_board` の region は `(i範囲, j範囲)` = `(行, 列)` 順。
`set_region_of_interest` は `[xmin, xmax, ymin, ymax]` = `[列, 列, 行, 行]` 順なので、
上記のとおり j → i の順に並べ替える（既存の `_do_tsumego_frame:574-581` が
`(analysis_region[1], analysis_region[0])` で転置していたのと同じ変換）。

- [ ] **Step 6: 全テストを実行**

Run: `python -m pytest tests/ --ignore=tests/test_ai.py -v`
Expected: 全て PASS（humanSL モデル依存の `test_ai.py` のみ除外）

- [ ] **Step 7: 実機で確認**

1. `C:\Users\iwaki\.katrain\config.json` の `"debug_level"` を `1` にする
2. `python -m katrain` で起動
3. BlueStacks で問題の詰碁を表示し F4
4. 確認項目:
   - 盤に描画される ROI 枠が右上の詰碁本体を囲んでいる（左下の空き地を含まない）
   - 最善手が **M10** になっている（D8 ではない）
   - M10 着手後も候補手がリージョン内に留まる
   - 反映までの体感時間（設計書の見込みは現状比 +1秒前後）
5. `"debug_level"` を `0` に戻す

**KaTrain 起動中にローカル config を編集すると終了時に上書きで消える。編集は必ず終了後に行う。**

- [ ] **Step 8: コミット**

```bash
git add katrain/core/tsumego_capture.py katrain/__main__.py tests/test_tsumego_capture.py
git commit -m "feat(tsumego_capture): 完成局面の再構築方式に変更し枠外の手を除外

認識グリッドに枠を適用した完成局面を単一のAB/AWとして新規局にする。
枠ノードを足す従来方式と違い、詰碁本体から離れた無関係な石を除去でき
（SGFのAEはengine.pyが解析を拒否するため使えない）、占有点への重複配置も
起きない。リージョン設定と2段解析を _apply_tsumego_region に切り出した。"
```

---

### Task 6: 壁が石を踏まない margin を優先する（手動フローの品質改善・任意）

設計書 §4 後段の要件。Task 3 は重なる枠石を除外して**クラッシュを防ぐ**が、壁に穴が空く。
面積条件を満たす margin が複数あるとき、境界線に石が乗らないものを選べば穴を減らせる。

**この Task は最後に単独で行うこと。** 既存テストの期待値を1つでも動かしたら
**採用せず revert する**（本体の修正を壊すリスクの方が大きい）。

**Files:**
- Modify: `katrain/core/tsumego_frame.py`（`fit_margin` に境界線の石を避ける選好を追加）
- Test: `tests/test_tsumego_frame.py`

**Interfaces:**
- Consumes: `fit_margin(sizes, komi, margin, imin, jmin, imax, jmax) -> int | None`（Task 1）
- Produces: `fit_margin(..., occupied=None)` — `occupied` は `{(i, j), ...}`。省略時は現行動作

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_fit_margin_prefers_boundary_without_stones():
    from katrain.core.tsumego_frame import fit_margin

    sizes = (13, 13)
    bbox = (0, 7, 8, 12)  # imin, jmin, imax, jmax
    # 石を渡さなければ従来どおり最大の margin
    assert fit_margin(sizes, 7.0, 4, *bbox) == 2
    # margin 2 の壁(j=5, i=10)上に石があるなら、面積条件を満たす他の margin を選ぶ
    occupied = {(2, 5), (4, 5)}
    assert fit_margin(sizes, 7.0, 4, *bbox, occupied=occupied) == 1
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -k fit_margin_prefers -v`
Expected: FAIL — `TypeError: fit_margin() got an unexpected keyword argument 'occupied'`

- [ ] **Step 3: 実装する**

`fit_margin` を置き換え:

```python
def fit_margin(sizes, komi, margin, imin, jmin, imax, jmax, occupied=None):
    """外側（枠矩形の外）に守り側の代償地帯 defense_area 相当が確保できる最大の margin を返す。

    put_outside は外側セルを守り側に defense_area（約 (盤面積-コミ-5)/2 ）だけ配分する設計
    だが、外側がそれ未満だと配分しきれず枠ゲームが一方的になる。確保できる margin がない
    場合は None を返す（呼び出し側が元の margin にフォールバックする）。

    occupied を渡すと、面積条件を満たす margin のうち境界線に石が乗らないものを優先する
    （壁が既存石を踏むと placement から除外されて壁に穴が空くため）。
    どれも踏む場合は面積条件を満たす最大の margin を返す。
    """
    isize, jsize = sizes
    needed = (isize * jsize - abs(komi) - offence_to_win) / 2
    fits = []
    for m in range(margin, 0, -1):
        i0, i1 = max(0, imin - m), min(isize - 1, imax + m)
        j0, j1 = max(0, jmin - m), min(jsize - 1, jmax + m)
        outside = isize * jsize - (i1 - i0 + 1) * (j1 - j0 + 1)
        if outside >= needed:
            fits.append((m, (i0, i1, j0, j1)))
    if not fits:
        return None
    if occupied:
        for m, (i0, i1, j0, j1) in fits:
            border = {(i, j) for i in (i0, i1) for j in range(j0, j1 + 1)}
            border |= {(i, j) for j in (j0, j1) for i in range(i0, i1 + 1)}
            if not (border & occupied):
                return m
    return fits[0][0]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -k fit_margin_prefers -v`
Expected: PASS

- [ ] **Step 5: 手動フローで `occupied` を渡す**

`tsumego_frame_stones` の `fit_margin` 呼び出しは `drop_non_core=False` のときだけ
`occupied` を渡す（除去する場合は壁が石を踏まないので不要）:

```python
    occupied = None if drop_non_core else {(z["i"], z["j"]) for z in all_ijs if not z["core"]}
    margin = fit_margin(sizes, komi, margin, imin, jmin, imax, jmax, occupied=occupied) or margin
```

- [ ] **Step 6: 既存テストが1つも動いていないことを確認**

Run: `python -m pytest tests/ --ignore=tests/test_ai.py -v`
Expected: 全て PASS

**1つでも既存の期待値が変わったら、この Task を revert して完了とする:**

```bash
git checkout -- katrain/core/tsumego_frame.py tests/test_tsumego_frame.py
```

- [ ] **Step 7: コミット（Step 6 が全 PASS の場合のみ）**

```bash
git add katrain/core/tsumego_frame.py tests/test_tsumego_frame.py
git commit -m "feat(tsumego_frame): 壁が既存石を踏まない margin を優先する

面積条件を満たす margin が複数あるとき、境界線に石が乗らないものを選ぶ。
重なる枠石は placement から除外されるため、踏むと壁に穴が空いて
守り側の脱出路になりうる。除去する経路(drop_non_core)では不要なので渡さない。"
```

---

## 完了条件

- `python -m pytest tests/ --ignore=tests/test_ai.py` が全て PASS
- 既存の枠テスト6本が期待値変更なしで PASS（`test_9x9_margin_clamped_so_frame_fits` のみ
  Task 1 Step 9 の理由で更新）
- 実機の F4 キャプチャで、再現ケースの最善手が M10 になる
