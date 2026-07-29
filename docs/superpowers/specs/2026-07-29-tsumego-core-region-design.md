# 詰碁キャプチャ: コアクラスタ検出とリージョン保証（枠退化の修正）設計書

日付: 2026-07-29
ステータス: 承認済み

## 目的

詰碁キャプチャで、詰碁本体から離れた無関係な箇所（空き地）の手が最善手と評価される問題を解消する。
枠（tsumego frame）が退化して解析リージョンが無効化されることが原因であり、
(1) 枠を正しく張れるようにし、(2) 枠が張れない場合でもリージョンを必ず有効に保つ。

## 再現ケース

13路。詰碁本体は右上（26子）、そこから離れた D10 / F11 / F9 / G6 の4子が同一図に含まれる。

```
13 - - - - - - - - - - - B -
12 - - - - - - - - - B B W W
11 - - - - - B - B B B W - -      F11 が離れ石
10 - - - B - - - W B W W - -      D10 が離れ石
 9 - - - - - W - W W B W - -      F9 が離れ石
 8 - - - - - - - - - B B W -
 7 - - - - - - - - - B W W -
 6 - - - - - - W - - B - - -      G6 が離れ石
 5 - - - - - - - - - - B B -
   A B C D E F G H J K L M N
```

正解は M10（白の眼形の急所）。実際には D8 が最善手として表示・自動着手され、不正解になる。
M10 着手後も最善手評価が D8 のまま変わらない。

## 原因（実測で確認済み）

### 原因1: コアクラスタのフォールバックが発火しない

`main_cluster` の `cluster_gap = 4`（Chebyshev距離4以内を同一クラスタ）では、
D10 → F9 → F11 → 本体、G6 → F9 と芋づるにつながり **主クラスタ = 全30石** になる。
`tsumego_frame.py:142` の `len(cluster) < len(ijs)` が成立せず、外れ石を落とす経路に入らない。

結果、bbox が「行13〜5・列D〜N」に広がり、+margin 4 が盤全体を覆うため
壁も充填も `put_stone` の盤外クランプで消え、**最下段の黒13子しか置かれない**。

```
region (i-range, j-range): ((0, 12), (0, 12))   ← 盤全体
frame stones added: 13
```

### 原因2: 絞り込み結果が flip 再帰で捨てられる（より深い原因）

`main_cluster` を gap=1 に差し替えて正しく26石に絞っても直らない。
`tsumego_frame_stones` は flip / 転置のたびに自分を再帰呼び出しし、
**各段で `problem_range` を全石から取り直す**。外れ石を落とすフォールバックは
最外段の条件（4辺すべてが退化）でしか発火しないため、絞り込みが1段目で失われる。

```
[L0] margin_in=4  ... main_cluster(gap=1): 26 / 30   ← 正しく絞れている
     ... fit_margin bbox=(i0..8, j7..12) -> 2
  [L1] ... fit_margin bbox=(i3..12, j0..8)           ← 全30石に戻る
    [L2] ... fit_margin bbox=(i3..12, j4..12)
      [L3] ... fit_margin bbox=(i4..12, j3..12)
    >>> put_border frame_range=[2, 14, 1, 14]
region: ((0, 10), (1, 12)) -> rows 13..3, cols B..N  ← D8 がリージョン内に残る
```

### 原因3: 盤全体リージョンは None に正規化される

`get_analysis_region` が四隅マークから盤全体を返すと、`game.py:569` の条件
`xmax - xmin + 1 >= szx and ymax - ymin + 1 >= szy` により `region_of_interest = None` になる。
リージョンが無効 = `engine.py:426-440` の `avoidMoves` が生成されず**全盤解析**になる。
全盤では左下の広大な空き地が死活より価値が高く、D8 が最善手になるのは KataGo として正しい判断。

M10 着手後も評価が変わらないのは、`region_of_interest` が None のまま
`Game.play()`（`game.py:549`）の2段解析分岐に入らず、以降ずっと全盤解析になるため。

## 制約: 占有点への配石はクラッシュする

`_validate_move_and_update_chains`（`game.py:164-165`）は占有点への配石を
`IllegalMoveException("Space occupied")` で弾き、`_init_chains`（`game.py:144-145`）が
`Exception("Unexpected illegal move ...")` に昇格させる。**同色でも落ちる**（実測）。

```
root ok, stones: ['F11', 'F9']
  AB[fc] on existing black: RAISED Exception: Unexpected illegal move (Space occupied)
  AW[fc] on existing black: RAISED Exception: Unexpected illegal move (Space occupied)
```

`put_border` は `put_stone` で無条件に上書きするため、壁が既存石を踏むとこれを踏む。
現状クラッシュしないのは**枠が退化して石をほとんど置かないから**であり、
手動の詰碁枠ポップアップでも密な局面ほど退化している:

```
ogs.sgf    move 20  (20 stones): OK  region=((7, 18), (0, 7))    ← 正常
ogs.sgf    move 60  (60 stones): OK  region=((0, 18), (0, 18))   ← 退化
ogs.sgf    move 100 (98 stones): OK  region=((0, 18), (0, 18))   ← 退化
panda1.sgf move 140 (142 stones): OK region=((0, 18), (0, 18))   ← 退化
```

したがって**退化を直すと占有点クラッシュが両フローで顕在化する**。重複除外のガードは必須。

## 外れ石の扱い: 枠矩形と外側面積の両立は不可能

枠矩形を margin ごとに動かし「境界線が外れ石を踏まないか」と「外側面積（枠バランス）」の
両立可否を実測した。needed = `(13*13 - |komi| - offence_to_win) / 2` = 78.5。

| margin | 壁の位置 | 踏む外れ石 | 外側面積 |
|---|---|---|---|
| 1 | G列 / 4行目 | G6 | 99 ✅ |
| 2 | F列 / 3行目 | F11, F9 | 81 ✅ |
| 3 | E列 / 2行目 | なし ✅ | 61 ❌ |
| 4 | D列 / 1行目 | D10 | 39 ❌ |

**両立する margin は存在しない。** margin 3 を選ぶと外側面積 61 < 78.5 となり、
`put_outside` が守り側に配りたい 78.5 に対して 61 しか無いため攻め側が **+17.5目** 得をした状態で始まる。
これは既知の「枠バランス飽和 → 勝率飽和 → 死活が結果に効かない」誤答要因そのもの。

「重なる枠石を placement から外して既存石を壁に流用する」案は却下した。
F11（黒）が白の壁に残ると、黒が G11 経由で H11 の本体へ連絡する脱出路になり、
**死活の答え自体が変わり得る**ため。

したがって**枠バランスを優先し、境界線上・枠外の非コア石は除去する**。今回の図では
F11 / F9 / D10 の3子が除去対象、G6 はリージョン内なので残る。

## アプローチ

採用: **コア検出の頑健化 + リージョン保証 + キャプチャ経路のみ局面再構築**。

不採用とした代替:

- **リージョン除外のみ（枠は直さない）**: 枠バランス飽和が残り、リージョン内でも勝率が飽和して
  死活が手の順位に効かない。
- **枠修正のみ（リージョン保証なし）**: 9路や本当に全盤へ散った図では枠が張れず、退化時に
  全盤解析へ戻る経路が残る。
- **両フローとも局面再構築に統一**: 手動ポップアップは進行中の棋譜の途中ノードに枠を張る機能であり、
  ルートを作り直すと棋譜が失われる。枠が子ノードなのはアンドゥで戻せるようにするための設計判断。

## 設計

### 1. コア検出の頑健化と flip 再帰への持ち回り

`tsumego_frame()` の入口で一度だけコアを決定し、石の dict に `tsumego_core: True` を立てる。
`flip_stones` は同じ dict オブジェクトを新しい配列へ移すだけなので、
**マークは転置・反転を越えて保持される**。`tsumego_frame_stones` の `problem_range` は
マーク付き石が存在すればそれだけを見る（無ければ全石 = 従来動作）。

コアの選び方はエスカレーション梯子:

```
for gap in cluster_gap..1:
    その gap での最大クラスタを取る
    bbox が、ある margin (1..margin_in) で「外側面積 >= needed」を満たすなら採用して break
どの gap でも満たせなければ gap=1 の最大クラスタを採用（best effort）
```

gap=4 で足りる問題（＝これまで正しく動いていたケース）は**採用クラスタが変わらず挙動が同じ**。
面積テストを通った時点で降下が止まるので、石が2路飛びに並ぶ大型詰碁を gap=1 で分断する事故は起きない。

副産物として以下を削除できる:

- `tsumego_frame_stones:137-143` の「4辺すべて退化したときだけ発火する」フォールバック分岐
- `main_cluster` の同サイズ時 `None` 返し（flip 再帰で別クラスタを選び直す無限再帰を避けるための措置。
  コア判定が再帰の外で1回だけ走るようになるため不要）。タイは bbox 面積が小さい方 →
  上・左が先、で決定的に解決する。

### 2. 解析リージョンの保証

`tsumego_frame()` が返すリージョンが falsy または盤全体の場合、
**コア bbox + pad にフォールバック**する。pad は 2 → 1 → 0 の順に試し（bbox は盤内へクランプする）、
`set_region_of_interest` に None 化されない（＝縦横どちらか一方でも盤より小さい）
最初のものを返す。すべて盤全体になる場合のみ None。

これにより、枠が張れない盤（9路・本当に全盤へ散った図）でも遠方の手が候補から消える下限を保証する。

### 3. 外れ石の除去と局面再構築（キャプチャ経路のみ）

`tsumego_frame_stones` に `drop_non_core` フラグを追加する。真のとき、frame_range 確定直後・
`put_border` の前に、**境界線上および外側にある非コア石を盤から消す**（`stones[i][j] = {}`）。

- 壁がコア石を踏むことは構造上ない（壁は core bbox ± margin にあり、margin >= 1）
- 除去を先に行うので `put_outside` の「既存石を残す」ガード（`tsumego_frame.py:250`）に
  引っかからず、充填が穴なしになる

キャプチャ経路は「元の局面 + 枠ノード」ではなく、
**枠適用後の完成局面を単一の AB/AW として SGF 化**し新規局にする。
SGF の `AE` は使えない（`engine.py:402-404` が `clear_placements` を含む経路の解析を拒否する）。

`_do_tsumego_capture_apply` の流れを次のように変える:

```
認識グリッド -> tsumego_frame_board(grid, komi, black_to_play_p=True, ko_p, margin, drop_non_core=True)
            -> (完成グリッド, region)
            -> grid_to_sgf(完成グリッド) -> _do_new_game(move_tree)
            -> set_region_of_interest(region) -> 2段解析（全盤fast -> リージョン限定）
```

`_do_tsumego_frame` の呼び出しは不要になる。リージョン設定と2段解析の発行は
`_do_tsumego_frame:574-596` と同じロジックを再利用する。

新設する公開関数:

- `tsumego_frame_board(bw_board, komi, black_to_play_p, ko_p, margin, drop_non_core) -> (bw_board, region)`
  盤グリッドを受け取り完成グリッドとリージョンを返す。Kivy 非依存で単体テスト可能。

`tsumego_frame_from_katrain_game`（手動フロー）は `drop_non_core=False` で従来どおり
枠石だけを AB/AW として子ノードに載せる。

### 4. 安全網: placement 重複の除外（手動フロー）

`tsumego_frame_from_katrain_game` で、既存石と座標が重なる枠石を AB/AW から除外する。
`drop_non_core=False` では壁が既存石を踏み得るため、これが無いと 1. の修正が
「Space occupied」クラッシュを顕在化させる。

加えて、面積条件（外側面積 >= needed）を満たす範囲内で**境界線が石を踏まない margin を優先**する。
踏まざるを得ない場合は穴を許容する（現状より悪化はしない）。

## 検証

### ユニットテスト（新規 `tests/test_tsumego_frame.py`）

再現ケースの盤面を固定データ化し:

- リージョンが D8 を除外し、M10 を含む
- 完成グリッドで占有点への二重配置が 0 件
- 外側面積 >= needed（枠バランスが成立している）
- 非コア石のうち G6 が残り、F11 / F9 / D10 が消えている
- gap=4 で足りる既存ケース（コンパクトな隅の詰碁）で採用クラスタが変わらない = 回帰なし

### 回帰テスト

`ogs.sgf` / `panda1.sgf` の複数手数で `tsumego_frame_from_katrain_game` を実行し:

- 例外が出ないこと（占有点クラッシュの防止）
- リージョンが盤全体に退化しないこと（現状は move 60 以降すべて退化しているため、前進の指標になる）

### 実機確認

F4 で同じ問題を取り込み:

- 最善手が M10 になること
- M10 着手後も評価がリージョン内に留まること（D8 に戻らないこと）
- 盤に描画される ROI 枠が詰碁本体を囲んでいること

## 影響範囲

- `katrain/core/tsumego_frame.py` — コア検出、リージョン保証、`drop_non_core`、新設 `tsumego_frame_board`
- `katrain/__main__.py` — `_do_tsumego_capture_apply` を完成局面の再構築方式へ
- `katrain/core/tsumego_capture.py` — `grid_to_sgf` を完成グリッドの受け口として再利用（変更は最小）
- `tests/test_tsumego_frame.py` — 新規

設定キーの追加・変更はない（`frame_margin` / `frame_ko` は現行のまま）。
