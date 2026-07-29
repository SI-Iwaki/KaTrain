# 詰碁キャプチャ 枠なしモード 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 詰碁キャプチャで枠を張るのをやめ、認識盤面をそのまま使い、解析リージョンを詰碁本体に密着させることで盤全体の手が最善手になるのを防ぐ。

**Architecture:** 認識グリッドをそのまま SGF 化して新規局にし、解析リージョンだけを新関数 `dense_core_bbox`（枠の成否ではなく石の密度を基準にコアクラスタを選ぶ）＋ pad から作る。枠モードは `use_frame: true` で残す。既存の枠ロジック（`tsumego_frame_board` 等）は一切変更しない。

**Tech Stack:** Python 3.12 / pytest。`katrain/core/tsumego_frame.py` は Kivy 非依存で単体テスト可能。

## Global Constraints

- 設計書: `docs/superpowers/specs/2026-07-29-tsumego-frameless-design.md`
- コミットメッセージは**日本語**、Conventional Commits 形式（`feat:`, `fix:`, `refactor:`, `test:`）
- `black` を既存ファイル全体に走らせない（コードベースが未整形のため巨大差分になる）。line-length=120 に手で合わせる
- コメントは日本語（周囲のスタイルに合わせる）
- **既存の枠ロジックを変更しない** — `mark_core_stones` / `build_frame` / `tsumego_frame` / `tsumego_frame_board` / `fit_margin` / `drop_non_core_stones` はそのまま。枠なしモードは並列の別経路として足す
- 既存テストの期待値を1つも変更しない（現在 296 tests pass）
- テスト実行は `python -m pytest tests/test_tsumego_frame.py tests/test_tsumego_capture.py -v`（humanSL モデル不要）
- `C:\Users\iwaki\.katrain\config.json`（ユーザーのローカル設定）はサブエージェントに編集させない。Task 3 で担当者が直接行う

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `katrain/core/tsumego_frame.py` | 枠生成に加え、枠なしモードのコア検出とリージョン算出 | 追記のみ |
| `katrain/__main__.py` | キャプチャ適用フローの枠あり／なし分岐 | 修正 |
| `katrain/config.json` | `use_frame` / `region_pad` の既定値 | 追記 |
| `C:\Users\iwaki\.katrain\config.json` | 同上（GUI に出すため必須） | 追記 |
| `tests/test_tsumego_frame.py` | 枠なしモードのコア検出・リージョンのテスト | 追記 |

---

### Task 1: `dense_core_bbox` と `frameless_region`

**Files:**
- Modify: `katrain/core/tsumego_frame.py`（末尾のユーティリティ群の前に追記）
- Test: `tests/test_tsumego_frame.py`

**Interfaces:**
- Consumes（すべて `tsumego_frame.py` に既存）:
  - `cluster_gap = 4`、`CORE_MIN_FRACTION = 0.6`、`BLACK = "B"`、`WHITE = "W"`
  - `ij_sizes(stones) -> (isize, jsize)`
  - `snapped_bbox(entries, sizes) -> (imin, jmin, imax, jmax)` — entries は `e[0]`=i, `e[1]`=j であればよい
  - `bbox_area(entries) -> int`
  - `covers_board_p(region, sizes) -> bool` — region は `((i0, i1), (j0, j1))`
- Produces:
  - `dense_core_bbox(bw_board) -> (imin, jmin, imax, jmax) | None`
  - `frameless_region(bw_board, pad) -> ((imin, imax), (jmin, jmax)) | None`

**注意:** `frameless_region` の戻り値は `((imin, imax), (jmin, jmax))` の**行レンジ・列レンジ**の順。
`_apply_tsumego_region`（Task 2 で使う既存メソッド）がこの形を期待している。
`dense_core_bbox` の戻り値は `(imin, jmin, imax, jmax)` で順序が違うので取り違えないこと
（`snapped_bbox` の慣習に合わせている）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_tsumego_frame.py` の import 行に `dense_core_bbox, frameless_region` を追加し、末尾に追記:

```python
def _m10_board():
    # 実機キャプチャの13路詰碁。右上26子が詰碁本体、D10/F11/F9/G6 が離れた石
    ab = "la jb kb fc hc ic jc dd id je jf kf jg jh ki li".split()
    aw = "lb mb kc hd jd kd fe he ie ke lf kg lg gh".split()
    return _board(
        stones=[(ord(p[1]) - 97, ord(p[0]) - 97, "B") for p in ab]
        + [(ord(p[1]) - 97, ord(p[0]) - 97, "W") for p in aw]
    )


def test_dense_core_bbox_drops_distant_stones():
    # 枠なしモードのコア検出: gap=1 で本体26子(87%)を保持できるので離れた石が落ちる。
    # mark_core_stones は「枠が張れないときだけ絞る」ため枠なし経路では使えない
    assert dense_core_bbox(_m10_board()) == (0, 7, 8, 12)


def test_dense_core_bbox_keeps_loose_shape_together():
    # 2路飛びに並ぶ緩い形は gap=1 だと4つに分断され最大クラスタが25%まで落ちるので
    # CORE_MIN_FRACTION に届かず gap=2 へ上がり、1塊としてまとまる
    board = _board(stones=[(5, 5, "B"), (5, 7, "W"), (7, 5, "W"), (7, 7, "B")])
    assert dense_core_bbox(board) == (5, 5, 7, 7)


def test_dense_core_bbox_empty_board():
    assert dense_core_bbox(_board()) is None


def test_frameless_region_pad1_contains_answer_and_excludes_open_area():
    # コアbbox(0,7,8,12) + pad1 → 行0..9・列6..12。実測でこの範囲なら正解手 M10 が
    # 1位（1113 visits）になり、pad2 だと空き地の J3 が競合して負ける
    region = frameless_region(_m10_board(), 1)
    assert region == ((0, 9), (6, 12))
    (i0, i1), (j0, j1) = region
    assert i0 <= 3 <= i1 and j0 <= 11 <= j1, "正解手 M10 (i3,j11) がリージョン外"
    assert not (i0 <= 10 <= i1 and j0 <= 8 <= j1), "空き地の J3 (i10,j8) がリージョン内"


def test_frameless_region_does_not_mutate_board():
    # 枠なしモードの要は「盤面がアプリと完全に同一」であること
    board = _m10_board()
    before = [row[:] for row in board]
    frameless_region(board, 1)
    assert board == before


def test_frameless_region_none_when_covering_whole_board():
    # 盤全体に広がる詰碁では set_region_of_interest が None 正規化するのと同じ扱いにする
    board = _board(stones=[(0, 0, "B"), (0, 12, "W"), (12, 0, "W"), (12, 12, "B")])
    assert frameless_region(board, 1) is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -k "dense_core or frameless" -v`
Expected: FAIL — `ImportError: cannot import name 'dense_core_bbox' from 'katrain.core.tsumego_frame'`

- [ ] **Step 3: `dense_core_bbox` を実装する**

`katrain/core/tsumego_frame.py` の `fallback_region` の直後に追記:

```python
def dense_core_bbox(bw_board):
    """枠なしモード用: 詰碁本体（密なクラスタ）の snap 済み bbox を返す。石が無ければ None。

    mark_core_stones は「枠が張れないときだけ絞る」判定なので、枠を張らない経路では
    基準として機能しない（実例: 全石 bbox のままだとリージョンが空き地まで広がり、
    空き地の手が正解手と競合して勝ってしまう）。ここでは枠の成否ではなく密度を基準にし、
    CORE_MIN_FRACTION 以上の石を保持できる最小の gap の最大クラスタを採る。
    石が2路飛びに並ぶ緩い形は gap=1 で分断されて割合を割るため gap が上がり1塊にまとまる。
    """
    sizes = ij_sizes(bw_board)
    entries = [(i, j) for i, row in enumerate(bw_board) for j, v in enumerate(row) if v in (BLACK, WHITE)]
    if not entries:
        return None
    n = len(entries)
    edges = [[] for _ in range(cluster_gap + 1)]
    for a in range(n):
        ia, ja = entries[a]
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
        if len(cand) >= n * CORE_MIN_FRACTION:
            return snapped_bbox(cand, sizes)
    return snapped_bbox(entries, sizes)


def frameless_region(bw_board, pad):
    """枠なしモードの解析リージョン ((imin, imax), (jmin, jmax)) を返す。盤全体になるなら None。

    盤面には一切触れない（枠なしモードの要はアプリと完全に同一の盤面を使うこと）。
    """
    core = dense_core_bbox(bw_board)
    if core is None:
        return None
    isize, jsize = ij_sizes(bw_board)
    imin, jmin, imax, jmax = core
    i0, i1 = max(0, imin - pad), min(isize - 1, imax + pad)
    j0, j1 = max(0, jmin - pad), min(jsize - 1, jmax + pad)
    if i0 >= i1 or j0 >= j1:
        return None  # 1線に退化した範囲は get_analysis_region と同じく使わない
    if covers_board_p(((i0, i1), (j0, j1)), (isize, jsize)):
        return None
    return ((i0, i1), (j0, j1))
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_tsumego_frame.py -v`
Expected: 25 passed（既存19 + 新規6）。既存テストの失敗があれば実装が誤り。期待値を書き換えて通してはならない

- [ ] **Step 5: コミット**

```bash
git add katrain/core/tsumego_frame.py tests/test_tsumego_frame.py
git commit -m "feat(tsumego_frame): 枠なしモード用の密度ベースのコア検出とリージョンを追加

mark_core_stones は枠が張れないときだけ絞る判定なので枠なし経路では機能しない。
枠の成否ではなく密度を基準に、CORE_MIN_FRACTION 以上を保持できる最小の gap の
最大クラスタを採る dense_core_bbox と、それに pad を足す frameless_region を新設。
盤面には一切触れない（枠なしモードの要はアプリと同一の盤面を使うこと）。"
```

---

### Task 2: キャプチャ適用フローの分岐と既定設定

**Files:**
- Modify: `katrain/__main__.py`（`_do_tsumego_capture_apply`）
- Modify: `katrain/config.json`（`tsumego_capture` に2キー追加）

**Interfaces:**
- Consumes:
  - `frameless_region(bw_board, pad) -> ((imin, imax), (jmin, jmax)) | None`（Task 1）
  - `tsumego_frame_board(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core=True) -> (board, region)`（既存）
  - `self._apply_tsumego_region(analysis_region, board_size)`（既存。`((imin, imax), (jmin, jmax))` を受け、上origin i → 下origin y の変換を内部で行う）
  - `grid_to_sgf(grid, komi)`（既存。`"B"`/`"W"` 以外のセルは空点として扱うので `"."` のままでよい）
- Produces: なし

- [ ] **Step 1: `katrain/config.json` に既定値を追加**

`tsumego_capture` オブジェクトに2キー追加（`analysis_visits` の後）:

```json
    "use_frame": false,
    "region_pad": 1
```

追加後の `tsumego_capture` は以下の通り:

```json
  "tsumego_capture": {
    "enabled": true,
    "hotkey": "f4",
    "window_title": "BlueStacks",
    "board_sizes": [9, 13, 19],
    "frame_margin": 4,
    "frame_ko": false,
    "maximize_on_capture": true,
    "auto_ai_black": true,
    "analysis_visits": 1800,
    "use_frame": false,
    "region_pad": 1
  }
```

**既存の `board_sizes` の整形（1行か複数行か）は変えないこと。** 2キーを足すだけにする。

- [ ] **Step 2: JSON が壊れていないことを確認**

Run: `python -c "import json,io; d=json.load(io.open('katrain/config.json',encoding='utf-8')); print(d['tsumego_capture'])"`
Expected: `use_frame` が `False`、`region_pad` が `1` を含む dict が表示される

- [ ] **Step 3: `_do_tsumego_capture_apply` に分岐を入れる**

`katrain/__main__.py` の `_do_tsumego_capture_apply` の冒頭（`from katrain.core.tsumego_capture import ...` から
`self._do_new_game(move_tree=move_tree)` の直前まで）を置き換え:

```python
    def _do_tsumego_capture_apply(self, grid, ko, margin):
        # メッセージループスレッドで実行。既定は枠なし: 認識盤面をそのまま新規局にし、
        # 解析リージョンだけを詰碁本体に密着させる。枠は盤面を約80子書き換えるため
        # 攻守判定・充填バランス・壁・非コア石削除と故障箇所が多く、死活そのものを
        # 変えてしまう疑いがある（実測: 枠ありで KataGo が正解手を勝率4%と評価した例）。
        # 空き地の手を候補から外す目的はリージョンだけで達成できる（実測で確認）。
        # use_frame: true で従来の枠モードに戻せる。
        # new-game と解析発行は同一メッセージ内で行う
        # （分割すると new-game で game_id が変わり後続メッセージが破棄されるため）
        from katrain.core.tsumego_capture import CaptureError, grid_to_sgf
        from katrain.core.tsumego_frame import frameless_region, tsumego_frame_board

        settings = self._config.get("tsumego_capture") or {}
        komi = self.config("game/komi", 6.5)
        if settings.get("use_frame", False):
            board, analysis_region = tsumego_frame_board(grid, komi, True, ko_p=ko, margin=margin)
        else:
            board = grid  # 認識結果そのまま。1子も書き換えない
            try:
                pad = int(settings.get("region_pad", 1))
            except (TypeError, ValueError):
                pad = 1
            analysis_region = frameless_region(grid, pad)
        try:
            move_tree = KaTrainSGF.parse_sgf(grid_to_sgf(board, komi=komi))
        except ParseError as e:
            self.log(f"詰碁キャプチャSGF解析失敗: {e}", OUTPUT_ERROR)
            return
        except CaptureError as e:
            # 石が1つも無い等、grid_to_sgf自体が弾くケース。self.log(OUTPUT_ERROR)は
            # 本クラスのlog()内でステータスバーにも転送されるため、_tsumego_capture_failed同様
            # ユーザーに認識できる（メッセージループスレッドなのでClock経由のGUI操作は不要）
            self.log(f"詰碁キャプチャ失敗: {e}", OUTPUT_ERROR)
            return
```

続く既存コードはそのまま残す。ただし `settings = self._config.get("tsumego_capture") or {}` が
`self._do_new_game(move_tree=move_tree)` の直後にもう1回あるので、**そちらの重複行を削除**する
（上に移動済みのため）。`deep_visits` 以降・`_apply_tsumego_region` 呼び出し・`maximize` /
`auto_ai` / `finish_gui` は一切変更しない。

- [ ] **Step 4: 変更箇所を目視確認**

Run: `git diff katrain/__main__.py`
Expected: `_do_tsumego_capture_apply` のみが変わっている。`_apply_tsumego_region` と
`_do_tsumego_frame` は差分に出ない。`settings = self._config.get("tsumego_capture") or {}` が
関数内に1回だけ残っている

- [ ] **Step 5: 構文と import を確認**

Run: `python -c "import ast,io; ast.parse(io.open('katrain/__main__.py',encoding='utf-8').read()); print('syntax ok')"`
Expected: `syntax ok`

Run: `python -m pytest tests/ --ignore=tests/test_ai.py -q 2>&1 | tail -3`
Expected: 302 passed（296 + Task 1 の6件）

- [ ] **Step 6: コミット**

```bash
git add katrain/__main__.py katrain/config.json
git commit -m "feat(tsumego_capture): 枠なしモードを既定にしリージョンだけで空き地の手を除外

認識盤面をそのまま新規局にし、解析リージョンを dense_core_bbox + pad で
詰碁本体に密着させる。枠は盤面を約80子書き換えて死活そのものを変える疑いがあり
（枠ありで KataGo が正解手を勝率4%と評価した実例）、空き地の手を外す目的は
リージョンだけで達成できることを実測で確認した。use_frame: true で従来動作に戻せる。"
```

---

### Task 3: ユーザーのローカル設定に追加（メインセッションで実施）

**Files:**
- Modify: `C:\Users\iwaki\.katrain\config.json`

**Interfaces:**
- Consumes: Task 2 で追加した `use_frame` / `region_pad` のキー名と既定値
- Produces: なし

**このタスクはサブエージェントに委任しないこと。** サブエージェントが成功を報告しても
実際に反映されないことがある既知の問題があるため、担当者が直接 Edit する。

- [ ] **Step 1: KaTrain が起動していないことを確認**

Run (PowerShell): `Get-Process | Where-Object { $_.MainWindowTitle -like "*KaTrain*" } | Select-Object Id, MainWindowTitle`
Expected: 出力なし（KaTrain のウィンドウが存在しない）

**起動中に編集すると KaTrain 終了時に設定ごと上書きされて消える。**
出力があった場合はユーザーに終了を依頼し、再確認してから次へ進む。

- [ ] **Step 2: 現在の値を確認**

Run: `python -c "import json,io; d=json.load(io.open(r'C:\Users\iwaki\.katrain\config.json',encoding='utf-8')); print(json.dumps(d['tsumego_capture'],indent=2,ensure_ascii=False))"`
Expected: `use_frame` と `region_pad` がまだ無い

- [ ] **Step 3: 2キーを追加**

`C:\Users\iwaki\.katrain\config.json` の `tsumego_capture` オブジェクトに、
`"analysis_visits": 1800` の直後へ追記（Edit ツールで直接編集する）:

```json
    "use_frame": false,
    "region_pad": 1
```

- [ ] **Step 4: JSON が壊れていないことと値を確認**

Run: `python -c "import json,io; d=json.load(io.open(r'C:\Users\iwaki\.katrain\config.json',encoding='utf-8')); t=d['tsumego_capture']; print(t['use_frame'], t['region_pad'], t['analysis_visits'])"`
Expected: `False 1 1800`

- [ ] **Step 5: 実機で確認**

1. `python -m katrain` で起動
2. BlueStacks で詰碁を表示して F4
3. 確認項目:
   - **盤面に詰め物の石が一切出ない**（アプリの図とまったく同じ）
   - ROI 枠が詰碁の石群にぴったり寄っている
   - AI が打つ手が詰碁の急所になっている
4. 既知の失敗ケース（case A の L1、case B の B4）を含め、複数問題で正解率を枠ありと比較する

判定は設計書の「詰碁の正解判定ルール」に従う。AI が正解手と違う手を打っても、
**アプリが正解と判定すれば正解**（コウ・セキに持ち込む別解も正解）。

- [ ] **Step 6: 結果を記録**

正解／不正解を問題ごとに記録し、枠あり（`use_frame: true`）との比較材料にする。
不正解のケースは SGF を残す（切り分けに使う）。

---

## 完了条件

- `python -m pytest tests/ --ignore=tests/test_ai.py` が全て PASS（302件）
- 既存テストの期待値変更がゼロ
- 実機で盤面がアプリの図と完全に一致し、ROI が詰碁本体に密着している
- 複数問題での正解率が枠ありモードと比較できている

## この計画に含めないこと

- **枠ロジックの削除** — `use_frame: true` の経路として残す。A/B 比較で枠なしの優位が
  確認できてから別途削除を検討する
- **ownership ベースの着手選択** — 設計書「将来の方向性」に記載。A/B の結果を見てから判断する
- **距離マスク方式のリージョン** — pad=1 の矩形で実測上足りているため YAGNI。
  検証で空き地の手が競合するようなら次の手として残す
