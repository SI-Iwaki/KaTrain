# 自己対局ハーネスの校正データ（`calibration-data/selfplay/`）

spec `2026-09-23-selfplay-harness-design.md`（§3 校正・§10 移設）。設計セッションの一時フォルダから移設した
（元は `%TEMP%/claude/.../scratchpad/`）。スクリプトはこのディレクトリの `recon/` を相対パスで読む。
ハーネス本体は `python -m katrain_debug.selfplay`（`katrain_debug/selfplay*.py`）。

| ファイル | 中身 |
|---|---|
| `recon/game_*.sgf` | 実戦 13路 18局（2026-09-14〜18 の監視対局ログから復元。難解＋16局・擬態2局。AI の色は PB/PW） |
| `recon/report_game_*.json` / `report_all.json` | 18局の事後 2500v 再解析。1手1行（depth・player・move・top・match・ptloss・score・alt_min_loss・top_prior…） |
| `recon/summary.json` | ログ側の手番の分類（`recon_logs.py` の出力） |
| `recon_logs.py` | `~/.katrain/logs/game_*.log` → `recon/*.sgf` と `summary.json` |
| `offline_report.py` | `recon/*.sgf` を KataGo で事後解析して `recon/report_*.json` を書く（KataGo を起動する） |
| `calib_targets.py` | 校正目標（相手の一致率・損失・区間 <24 / 24〜84 / >=85 の形）を `recon/` から出す＝spec §3 の表 |
| `join_turns.py` / `inventory2.py` | ログ側の分類と事後解析の突き合わせ・擬態の資格の在庫（設計時の調査） |
| `proto_selfplay.py` | ハーネスの試作（本物の `generate_ai_move`・1visit humanSL の相手） |
| `bench_pipeline.py` / `bench_size.py` | 戦略なしの流れの所要時間（spec §7。KataGo を起動する） |
| `cf_absolute.py` / `cf_absolute2.py` / `cf_veil.py` / `veil_cf.py` / `judge/unified_cf.py` | 韜晦の反実仮想（KataGo 不要。韜晦 spec §2.4） |
| `opponent_pool_13.json` | 相手ボットの 3段位プール（`calibrate --write-pool` の出力。`run` の既定の相手） |
| `selfplay-calibration-results-*.md` | 校正の結果（段位ごとの表・プールの候補・ハーネスと実戦のずれ） |

確認: `python docs/superpowers/specs/calibration-data/selfplay/calib_targets.py` が
`opp all n= 715 match=0.218 loss=1.74`（相手 18局・全手まとめ）と `median 78.5`（手数）を出す。
