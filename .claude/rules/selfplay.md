---
description: 自己対局ハーネス katrain_debug.selfplay の全コマンド例・投了モデル・校正・再開の検査・出力の読み方
paths:
  - "katrain_debug/selfplay*.py"
  - "tests/test_selfplay*.py"
  - "tests/selfplay_fakes.py"
  - "docs/superpowers/specs/calibration-data/selfplay/**"
  - "experiments/selfplay/**"
---

# 自己対局ハーネス

自己対局ハーネスを走らせる／触る前に読む。spec は `docs/superpowers/specs/2026-09-23-selfplay-harness-design.md`。2026-11-15 に CLAUDE.md から文言を変えずに移した。

**自己対局ハーネス**（`python -m katrain_debug.selfplay`・spec `2026-09-23-selfplay-harness-design.md`）: 戦略 vs humanSL ボット（実戦の相手に校正）を無人で N 局打たせ、本物の `game_report` で両者の一致率・勝敗・目差を集計する。**実戦中の KaTrain と同時に走らせない**（起動中の katago.exe があれば止まる。GPU を取り合うと実戦の AI が maxTime に当たる）。
```bash
# A/B（全アームが同じ seed＝色・相手・投了の条件を対にする。10 seed ごとに ABBA）。相手は既定で calibration-data/selfplay/opponent_pool_13.json
# 今のプール（2026-09-24 08:22 の校正）は length の投了モデルで合わせたもの（手数中央値 81 vs 実戦 78.5・AI 側のずれ -0.8pt。結果 calibration-data/selfplay/selfplay-calibration-results-20260924-length.md）。終盤（85手以降）の相手の一致率は実戦より約 15pt 低い
# --pairs 20 は3段位のプールで層が 8/6/6 局になり unbalanced の警告が出る（想定内＝停止規則の 20/40 ペア。層を揃えるなら 18 / 24）
python -m katrain_debug.selfplay run --arm A=enigma13plus --arm B=enigma13plus:enigma13plus_max_loss=2.0 --size 13 --pairs 20 --label maxloss-ab
# 投了は既定で length モデル（実戦 13路 18局の手数から局ごとに L を引き、L 以降に AI 勝率 >= 0.90 かつリード >= 2.5目が AI の2手番続けば投了）。
# 以前のリード R のモデルは --resign-model lead（--resign-lead LO:HI はこのときだけ）。投了モデルの違う実行は summarize で合わせない
# 投了なし（必須の感度アーム）・接戦ストレス層（AI 不利のコミ＋強めの相手）
python -m katrain_debug.selfplay run --arm A=enigma13plus --size 13 --pairs 20 --no-resign --label nores
python -m katrain_debug.selfplay run --arm A=enigma13plus --size 13 --pairs 20 --komi-shift 4 --ranks rank_5d,rank_9d --opp-max-loss 2 --label stress
# 集計し直し・対の差（既定 97.5% 区間＝2回見る停止規則。2アームの run は終了時にも出す）・落ちた実行の再開
python -m katrain_debug.selfplay summarize experiments/selfplay/<dir> --compare A B
python -m katrain_debug.selfplay run --resume experiments/selfplay/<dir>   # --retry-aborted で aborted の局も打ち直す。--allow-mixed は下の計測の基準の違いを許す
# 停止規則の延長（差の区間が ±3pt の線をまたぐとき 40 ペアへ）: seed をずらした 20 ペアを足し、2本を合わせて集計
python -m katrain_debug.selfplay run --arm A=enigma13plus --arm B=enigma13plus:enigma13plus_max_loss=2.0 --size 13 --seed-base 1020 --pairs 20 --label maxloss-ab-ext
python -m katrain_debug.selfplay summarize experiments/selfplay/<dir> experiments/selfplay/<ext の dir> --compare A B
# 相手ボットの校正（13路 6段位×8局・約2時間。計測の健全性の数が 0 でなければ --write-pool は上書きせず <path>.suspect に書く＝--force-pool で上書き）・実戦の保存 SGF の両者のレポート
python -m katrain_debug.selfplay calibrate --size 13 --strategy enigma13plus --games 8 --write-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json
# 9路（spec 韜晦 §16）: 投了の手数は recon_9/（難解＋9路の実戦・縮めない）。calibrate --strategy NAME:key=v,... で AI の設定を上書きする
python -m katrain_debug.selfplay calibrate --size 9 --strategy enigma9plus:enigma9plus_max_loss=1.6,enigma9plus_target_score=0.2,enigma9plus_gamble_until_move=20 --ranks rank_1d,rank_3d,rank_5d,rank_7d,rank_9d --games 8 --write-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_9.json
# 定跡を知る相手（手数 < B の間、AI の手がすべて X 目以下なら KataGo の最善手・既定 X 0.3）と序盤の窓の指標
python -m katrain_debug.selfplay run --arm A=veil9:veil9_open_moves=0 --arm B=veil9:veil9_open_moves=12 --size 9 --pairs 24 --book-moves 24 --label book
python docs/superpowers/specs/calibration-data/selfplay/window_stats.py experiments/selfplay/<dir> --compare B A
python -m katrain_debug.selfplay report-sgf FILE.sgf
```
出力は `experiments/selfplay/<YYYYMMDD_HHMM>_<label>/`（`run.json`＝解決済み設定とハッシュ・ai.py の場所・git HEAD、`games.jsonl`＝1局1行、`moves.jsonl`＝1手1行、`sgf/`＝KT 解析つき、`logs/`＝戦略自身の `[XxxStrategy]` 行（`Rate:` / `Decision:` / 着手時間）とエラー、`summary.txt`（ASCII）/ `summary.json`）。主指標は **WATCH 木（末尾のパスを除く＝監視対局の木と同じ）の局ごとの一致率**。アームの書式は `<名前>=<runner の戦略名>[:key=val,...]`（綴り間違いのキーと、戦略が実際に使う設定（コードの既定値＋ユーザー config＋上書き。6 と 6.0 は同じ）が同一のアーム＝null 実験は開始前に止まる。戦略の節がユーザー config に無い＝コードの既定値で走るアームは計画時に `note: ... settings_source = code defaults ...` を出す）。`--shadow B` は他アームの各手番で B の判断を同じ局面で記録（打たない）、`--hp-audit rank_9d` は外した手の 9段 hp を測る。summary.txt とコンソールは、相手が humanSL の失敗や `--opp-max-loss` で候補切れのため KataGo の最善手にフォールバックした回数や hp 監査・影判定の失敗があれば `WARN integrity: arm <名前>: ...` を出す（`--opp-max-loss` 使用時は `fallbacks` だけの WARN は想定内）。再開（`--resume`）と複数の実行の `summarize` は、計測の基準＝エンジン設定（katago・model・humanlike_model・max_visits・max_time・wide_root_noise）とコードの版（git HEAD・ai.py の場所）が run.json と違えば違いを出して止まる（`--allow-mixed` で続行）。`--ranks` / `--hp-audit` の段位は `rank_<N>k|d`・`preaz_<N>k|d`・`proyear_<YYYY>` の形でなければエンジンを起こす前に止まる。1局 13路 約1〜6分（投了あり。手数で大きく変わる＝実測 83秒/49手・319秒/157手）。seed の数は 2 × 相手の段位数 の倍数にする（層の局数が揃わないと警告）。KataGo の探索は非決定的＝seed は開始条件の対で再現ではない（最低 20 ペアで比べる）。run / calibrate は使った config の写し `config-snapshot.json` を出力ディレクトリに置き、`--resume` はその写しを読む（中身が run.json の sha256 と違えば止まる）。`<prefix>_open_moves` > 0 の韜晦のアームは、窓を任せる難解＋の節（戦略キー・設定・指紋）を run.json の `delegate` に持ち、再開と `summarize` の合算で違えば止まる（アームの上書きは任せる先に効かない＝難解＋の節はユーザー config のまま。計画時に `note: ... opening window delegated to ...` を出す）。
