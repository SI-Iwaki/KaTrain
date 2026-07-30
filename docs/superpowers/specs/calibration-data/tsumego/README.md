# 詰碁（ai:tsumego）の校正・回帰データ

## SGF

| ファイル | 内容 |
|---|---|
| `case-d-gain-region-20260730.sgf` | 枠外の代償地帯が gain の符号を反転させた誤答局面（13路左下、正解 A4／別解 B3、旧実装は C3 で失敗）。region = `0,8,0,8`、対象は 4手目 |
| `case-e-ko-margin-20260730.sgf` | コウ勝ち前提のマージンが小さすぎて無条件の正解を捨てた誤答局面（13路下辺、正解 K1、旧実装は L1 でコウにして失敗）。region = `3,12,0,8`、対象は 6手目 |
| `case-f-gain-visit-share-20260730.sgf` | 探索の浅い候補の gain ノイズが正解を上回った誤答局面（13路右上、正解 N8、旧実装は N7 を選び白が生きた）。region = `4,12,3,12`、対象は 2手目。`gain_min_visit_ratio`（深さゲート）と `gain_verify`（同深さ検証）の回帰対象 |

## 診断スクリプト

KaTrain 本体とは独立。KataGo を起動するのでプロジェクトルートから実行する。
`REGION` は各スクリプト先頭の定数で、SGF ごとに合わせる（本番のリージョンは
`__main__.py` の `_apply_tsumego_region` / `_do_tsumego_frame` が設定する値。
KaTrain のログの `avoidMoves` から読み取れる）。

### `gain_probe.py` — 候補手ごとの gain 内訳を出す

```bash
python docs/superpowers/specs/calibration-data/tsumego/gain_probe.py <sgf> <move_number> [visits]
```

候補手を `gain(全石)` / `gain(リージョン内)` / `gain(リージョン内の相手石)` の3通りで並べ、
注目手については石ごとの ownership 変化（枠内 `in` / 枠外 `OUT` の区別つき）を出す。
**枠外の石が大きく動いていたら counterweight が効いている**サイン。

### `gain_region_ab.py` — 選択則の A/B 比較

```bash
python docs/superpowers/specs/calibration-data/tsumego/gain_region_ab.py <sgf> <moves_csv> [repeats]
# 例: ... case-d-gain-region-20260730.sgf 0,2,4 4
```

**1回の解析から旧（全石）/新（リージョン内）の両方の選択を計算する**ので、
KataGo の並列探索の run 間分散が交絡しない。選択則を変えるときはこの形で比較すること
（別 run で比べると分散に埋もれる → memory `feedback_batch_eval_variance` と同じ罠）。

### `ko_margin_ab.py` — コウ勝ち前提の採用判定を検証

```bash
python docs/superpowers/specs/calibration-data/tsumego/ko_margin_ab.py <sgf> <move_number> <xmin,xmax,ymin,ymax> <期待手> [repeats]
# 例: ... case-e-ko-margin-20260730.sgf 6 3,12,0,8 K1 3
```

現在の `ko_win_margin` で N 回走らせ、最後に `ko_win_margin=0.5`（旧既定）でも1回走らせて
新旧を比較する。コウ判定ログ（通常最善・コウ勝ち前提・差・閾値）だけを抜き出して表示する。

## 注意

- SGF には必ず `RU[chinese]` を入れる。未指定だと engine 既定の japanese になり、
  面積計算前提の枠のスコアが 25目規模でずれる（spec の「落とし穴（要注意）」参照）
- 実測値は spec `docs/superpowers/specs/2026-07-29-tsumego-ownership-design.md` の追記に記録
