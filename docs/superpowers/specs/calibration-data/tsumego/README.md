# 詰碁（ai:tsumego）の校正・回帰データ

## SGF

| ファイル | 内容 |
|---|---|
| `case-d-gain-region-20260730.sgf` | 枠外の代償地帯が gain の符号を反転させた誤答局面（13路左下、正解 A4／別解 B3、旧実装は C3 で失敗）。region = `0,8,0,8`、対象は 4手目 |
| `case-e-ko-margin-20260730.sgf` | コウ勝ち前提のマージンが小さすぎて無条件の正解を捨てた誤答局面（13路下辺、正解 K1、旧実装は L1 でコウにして失敗）。region = `3,12,0,8`、対象は 6手目 |
| `case-f-gain-visit-share-20260730.sgf` | 探索の浅い候補の gain ノイズが正解を上回った誤答局面（13路右上、正解 N8、旧実装は N7 を選び白が生きた）。region = `4,12,3,12`、対象は 2手目。`gain_min_visit_ratio`（深さゲート）と `gain_verify`（同深さ検証）の回帰対象 |
| `case-g-frame-role-20260730.sgf` | 枠が詰碁自体を消していた誤答局面（13路左上、正解は初手 A11 でコウ、旧実装は B13 で不正解）。region = `0,7,3,12`、対象は 1手目（初手）。`frame_destroys_problem` / `solver_core_points`（枠採否判定と枠なしフォールバック）の回帰対象 |
| `case-g2-frameless-guard-20260730.sgf` | case G の枠なしフォールバック後の盤で、目数ガードが正解を足切りした誤答局面（2手目、正解 C13、旧実装は B13）。region = `0,7,3,12`。枠なし盤では目数差が圧縮され C13 の pointsLost 1.56〜2.26 がガード帯（best+2.0）を挟んで揺れる。`gain_rescue_margin`（救済＝gain 争いに参加できなかった候補でも gain が明確に上回る手を同深さ検証にかける）の回帰対象 |
| `case-f2-rescue-shadow-20260730.sgf` | gain 1位に立った v10 のノイズ手が本物を検証から締め出した誤答局面（case F 枠なし盤の 5手目、正解 N11/M12、旧実装は J11）。region = `5,12,6,12`。ノイズ N9(g+6.77) > 本物 N11(g+5.41)/M12(g+5.30) の順で、トップ1検証では N9 却下で救済終了。検証は毎回正しく序列化する（N11 -17.1 / M12 -17.2 / J11 -19.4 / N9 -26.9）ので、救済のトップ3全員検証（`TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES`）の回帰対象 |
| `case-h-gate-cliff-20260730.sgf` | 深さゲートが目数ガード内の正解を足切りした誤答局面（13路右下・枠なし、5手目、正解 N4、旧実装は J7）。region = `5,12,0,6`。N4 は gain +4.4 断トツ・ガード内なのに visit比 0.46〜0.49 < 0.5 でゲート外、当時の救済（ガード外のみ）も届かず。救済対象の拡大（非 contenders 全体・visit比撤廃・採用マージン 1.0）の回帰対象。同深さ検証 N4 +13.2〜+14.2 vs 代替 +8.9〜+9.7 |

| `case-i-defender-ko-20260730.sgf` | **未対処の既知限界**: 守り側で「無条件の生き（捨て石あり）> コウ」を選べなかった誤答局面（13路右下・枠なし、初手、正解 N2、AI は J1 でコウ生きになり不正解）。region = `6,12,0,8`。原因は KataGo の探索崩壊（咎め W-N2 を 6000visits でも誤読）で、選択則・枠・深掘りのどれでも判別不能と実測済み（spec 追記13）。復帰はアンドゥで次候補（N2 が2位）。**エンジン更新時に再評価** |
| `case-j-points-tie-20260730.sgf` | gain も目数も 0.02 差で並んだ「正しい別解」を選んで不正解になった局面（13路右上・枠あり、11手目、正解 N10、旧実装は N11）。region = `6,12,1,12`。N11 も実際に白を殺せている（8000visits でも分離不能・同深さ検証も差 0.05 で無力）が、アプリの解答樹には N10 しか無い。目数同着バンド `points_epsilon` 内で visits 最多（KataGo の本命）を採るタイブレークの回帰対象（spec 追記14） |

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

### `points_tie_ab.py` — 目数同着タイブレーク（points_epsilon）の A/B 比較

```bash
python docs/superpowers/specs/calibration-data/tsumego/points_tie_ab.py <sgf> <moves_csv> <xmin,xmax,ymin,ymax> [repeats]
# 例: ... case-j-points-tie-20260730.sgf 0,2,4,6,8,10 6,12,1,12 3
```

gain_region_ab.py と同じく **1回の解析から旧（points_epsilon=0）/新（既定 0.25）の
両方の選択を計算する**。gain も目数もノイズ同着の局面（case J）で、旧則がコイン投げに
なるのに対し新則が visits 最多（KataGo の本命）へ寄ることを確認する。

### `generate_move_e2e.py` — 実 generate_move の E2E（検証・救済経路込み）

```bash
python docs/superpowers/specs/calibration-data/tsumego/generate_move_e2e.py <sgf> <moves_csv> <xmin,xmax,ymin,ymax> [repeats]
# 例: ... case-j-points-tie-20260730.sgf 0,10 6,12,1,12 3
```

select 単体の A/B は generate_move 後段（score_best 同深さ検証・救済）を通らないので、
そこで巻き戻される回帰を見逃す（実測 case J: select は N10 を選んだのに無条件の
score_best 検証が却下して N11 に巻き戻し、GUI で誤答が再発）。**選択則を変えたら
select レベルの A/B に加えて必ずこれも回すこと**。

### `ko_margin_ab.py` — コウ勝ち前提の採用判定を検証

```bash
python docs/superpowers/specs/calibration-data/tsumego/ko_margin_ab.py <sgf> <move_number> <xmin,xmax,ymin,ymax> <期待手> [repeats]
# 例: ... case-e-ko-margin-20260730.sgf 6 3,12,0,8 K1 3
```

現在の `ko_win_margin` で N 回走らせ、最後に `ko_win_margin=0.5`（旧既定）でも1回走らせて
新旧を比較する。コウ判定ログ（通常最善・コウ勝ち前提・差・閾値）だけを抜き出して表示する。

### `frame_validity_probe.py` — 枠が詰碁を壊していないか判定し、枠あり／枠なしを比較

```bash
python docs/superpowers/specs/calibration-data/tsumego/frame_validity_probe.py <sgf> <move_number> <xmin,xmax,ymin,ymax> <期待手csv> [trial_visits] [visits]
# 例: ... case-g-frame-role-20260730.sgf 0 0,7,3,12 A11
```

引数の SGF は**枠を張った後の盤**（保存SGFのroot）。そこから本体（コア）石を復元し
（4辺の壁の総当たり×攻め方×コウダテを再枠張りして元の盤に一致する組合せを採る）、
枠候補ごとに「手番側の本体石が生きているか」（`frame_destroys_problem`）を判定した上で、
**枠あり・枠なしそれぞれで `select_tsumego_move` が何を選ぶか**を出す。

誤答報告が来たら最初にこれを回す。枠が詰碁を消していれば `DESTROYS the problem` が出る
（＝選択則をいじっても無駄。実測 case G: 枠あり B13 NG / 枠なし A11 OK）。

## 注意

- SGF には必ず `RU[chinese]` を入れる。未指定だと engine 既定の japanese になり、
  面積計算前提の枠のスコアが 25目規模でずれる（spec の「落とし穴（要注意）」参照）
- 実測値は spec `docs/superpowers/specs/2026-07-29-tsumego-ownership-design.md` の追記に記録
