# 輪の難易度の先回り（humanSL 9段 8visits）の速度ゲート — 2026-11-06

board-watch spec 追記11 の採用ゲート。相手の手を `Game.play` に入れてから、親局面（AI が打つ局面）の
通常解析が終わるまでの秒数を、先回り ON/OFF で比べた（AI の着手生成は解析の完了を待ってから始まるので、
先回りが着手を遅らせうるのはこの区間の GPU の取り合いだけ）。

- プローブ: `ring_difficulty_latency_probe.py`（1プロセス1アーム・ウォームアップ2局面は除外）
- 比較: `ring_latency_compare.py`（局面ごとに ON/OFF の平均の比をとり、局面のブートストラップで 95% 区間）
- 局面: 9路 `experiments/selfplay/20260926_0843_veil9-p1/sgf/` 先頭6局・13路 `experiments/selfplay/20260924_0951_veil13-p1/sgf/` 先頭6局から、9手目以降 8手おきに1局あたり最大6局面
- 順序: サイズごとに OFF → ON → ON → OFF（別プロセス）。エンジンは本番構成（KataGo v1.18.2 CUDA・b10c384・humanSL b18c384nbt-humanv0・max_visits 2500）
- 生データ: `ring-latency-runs/ring{9,13}-{off,on}-{1,2}.jsonl`
- ゲート（事前に決めた値）: 比の平均の 95% 区間の上限 < 1.03 かつ ON の ready 率 >= 0.95

## 結果

```
== 9x9
positions=31 off_median=1.304s on_median=1.280s
ratio on/off mean=1.0093 median=1.0125 95%CI=[0.9897,1.0295]
hp_ready=1.000 (62/62)
kind_hp (chosen=best): hard=31% normal=53% obvious=16%
kind_kata (chosen=best): hard=40% normal=42% obvious=18%
E_hp p50=1.05 p77=1.92 p80=2.06 >=1.5:31%
E_kata p50=0.98 p77=2.37 p80=2.57 >=1.5:40%
GATE PASS
== 13x13
positions=36 off_median=1.654s on_median=1.665s
ratio on/off mean=1.0139 median=1.0039 95%CI=[0.9998,1.0301]
hp_ready=1.000 (72/72)
kind_hp (chosen=best): hard=21% normal=61% obvious=18%
kind_kata (chosen=best): hard=22% normal=67% obvious=11%
E_hp p50=0.42 p77=1.36 p80=1.51 >=1.5:21%
E_kata p50=0.72 p77=1.48 p80=1.64 >=1.5:22%
GATE FAIL
```

## 判定

- 9路 PASS、13路は区間の上限 1.0301 で**ゲートを 0.0001 だけ超えた**（FAIL）。平均 +1.4%（13路の解析 1.65 秒に対して約 0.02 秒）、中央値 +0.4%。
- humanPolicy は全局面（134/134）で解析の完了より前に届いた＝輪を出す時点で必ず揃っている。
- **ユーザーの判断で案A（humanPolicy の先回り）を採用**（2026-11-06: 「0.02 秒なら体感できないレベルなので問題ない」）。
- 判定の分布（最善手を打った場合・humanPolicy）: 9路 明らか 16%・難解 31%、13路 明らか 18%・難解 21%（spec の想定の各約 2 割と整合。9路の難解がやや多い）。KataGo の policy で代用した場合（案B）は 13路の明らかが 11% に落ちる。
