# 自己対局ハーネスの校正データ（`calibration-data/selfplay/`）

spec `2026-09-23-selfplay-harness-design.md`（§3 校正・§10 移設）。設計セッションの一時フォルダから移設した
（元は `%TEMP%/claude/.../scratchpad/`）。スクリプトはこのディレクトリの `recon/` を相対パスで読む。
ハーネス本体は `python -m katrain_debug.selfplay`（`katrain_debug/selfplay*.py`）。

| ファイル | 中身 |
|---|---|
| `recon/game_*.sgf` | 実戦 13路 18局（2026-09-14〜18 の監視対局ログから復元。難解＋16局・擬態2局。AI の色は PB/PW） |
| `recon/report_game_*.json` | 18局の事後 2500v 再解析。`summary`（ai・n_moves・final_score…）と1手1行（depth・player・move・top・match・ptloss・score・alt_min_loss・top_prior…）。ハーネスの投了モデル（length の手数 L・lead の最終リード R）はここの `summary` を読む |
| `recon/report_all.json` | `offline_report.py` の最後の実行が書いた `summary` のリスト。**4局分だけの部分リスト**（18局の一覧ではない。ハーネスは読まない） |
| `recon/summary.json` | ログ側の手番の分類（`recon_logs.py` の出力） |
| `recon_9/` | 難解＋9路の実戦 16 局（2026-09-19〜22 の監視対局ログ・`experiments/selfplay/realgames-9x9-logs/` から `recon_logs.py --size 9`。持碁9路 `game_20260919_224212` を除く・置き石の初手 4 局と監視の外の相手のパス 1 局を直した）と事後 2500v（`offline_report.py --dir recon_9`）。summary に局の難解＋の設定。9路の投了の手数（length モデル）と `CALIB_TARGETS_9` の元 |
| `recon_9_veil/` | 一致率ひかえめ9路（今の設定＝spec §6.1 の 9路の列）の実戦 8 局（2026-09-26 の監視対局ログ・同じ置き場から `recon_logs.py --size 9 --strategy Veil9Strategy`。置き石の初手 2 局を直した）と事後 2500v。spec §16.5 の「実戦」（`window_stats.py --recon`）の元。投了の手数と校正の目標には使わない |
| `recon_logs.py` | `~/.katrain/logs/game_*.log` → `recon/*.sgf` と `summary.json`。`--log-dir`・`--out`・`--size`・`--strategy`。9路は難解＋の局だけ（一致率ひかえめ9路は `--strategy Veil9Strategy` で `recon_9_veil/`）・除く局（`EXCLUDE_9`）・監視の外の相手のパス・root の置き石になった相手の初手を直す（spec 韜晦 §16.2 手順1） |
| `offline_report.py` | `recon/*.sgf` を KataGo で事後解析して `recon/report_*.json` を書く（KataGo を起動する）。`--dir`（9路は `recon_9`）・`--config`。区間は盤別（13路 85・9路 41 手）で summary に `board_size` と局の設定 |
| `calib_targets.py` | 校正目標（相手の一致率・損失・区間 <24 / 24〜84 / >=85 の形）を `recon/` から出す＝spec §3 の表。`--size 9`（区間 12 / 41）・`--where` / `--ai-where k=v,...`（局の設定で絞る）。最後の行 `CALIB_TARGETS {...}` は `selfplay_stats.CALIB_TARGETS_<size>` の形 |
| `join_turns.py` / `inventory2.py` | ログ側の分類と事後解析の突き合わせ・擬態の資格の在庫（設計時の調査） |
| `proto_selfplay.py` | ハーネスの試作（本物の `generate_ai_move`・1visit humanSL の相手） |
| `bench_pipeline.py` / `bench_size.py` | 戦略なしの流れの所要時間（spec §7。KataGo を起動する） |
| `cf_absolute.py` / `cf_absolute2.py` / `cf_veil.py` / `veil_cf.py` / `judge/unified_cf.py` | 韜晦の反実仮想（KataGo 不要。韜晦 spec §2.4） |
| `opponent_pool_13.json` | 相手ボットの 3段位プール（`calibrate --write-pool` の出力。`run` の既定の相手）。今のプール（2026-09-24 08:22）は length の投了モデルで合わせたもの（手数中央値 81 vs 実戦 78.5・結果 `selfplay-calibration-results-20260924-length.md`） |
| `opponent_pool_9.json` | 9路の相手ボットの 3段位プール（`calibrate --size 9 --strategy enigma9plus:<実戦の多数派の 7 局の設定> --ranks rank_1d,rank_3d,rank_5d,rank_7d,rank_9d --games 8`・結果 `selfplay-calibration-results-<YYYYMMDD>-9x9.md`） |
| `selfplay-calibration-results-*.md` | 校正の結果（段位ごとの表・プールの候補・ハーネスと実戦のずれ）。`-20260924.md` は lead の投了モデルでの最初の校正＝`-20260924-length.md` に置き換え済み |
| `veil13-campaign.md` / `veil13-campaign/` | 韜晦（13路）の自己対局キャンペーン結果（計画 `2026-09-23-veil-strategy.md` の Task 15・16）。段階1（5アーム × 20局）だけ実施＝段階1b・2・3 は未実施。主比較・罠 A/B・一致率の下限の内訳・採否・ユーザーの決定（13路の既定値は据え置き）。`veil13-campaign/` は段階1の `veil13-p1-run.json` と default 対各アームの summary（`veil13-p1-default-vs-<アーム>-summary.{json,txt}`）の写し |
| `window_stats.py` | 序盤の窓の指標（spec 韜晦 §16.2 手順7）: 実行ディレクトリの moves.jsonl から窓の中（手数 <= W・9路 12・13路 30）と後の一致率・損失・大きな損・W 手目のリード・flip・窓の後の u と paid・定跡を知る相手の出口・`decision_open` の確かめ・同じ seed の対の差（`--compare A B`）。`--recon DIR ...` は実戦の事後解析（`recon_9/`・`recon_9_veil/`）の自分と相手の窓の中・後の一致率と相手が最善手を続けた手数（spec 韜晦 §16.5 の「実戦」） |
| `enigma9_log_stats.py` | 難解＋9路の実戦ログ（`experiments/selfplay/realgames-9x9-logs/`・gitignore）の集計: ログの理由文の自分の一致率・勝率勾配・安い代わりの手（spec 韜晦 §16.1）。最初の手番が難解＋9路でないログは数えない。KataGo 不要 |
| `opp_bot_match9.py` | 9路の相手 BOT の手と clean 最善手・humanSL 9段の1位の一致（`../enigma9/ponder_pick_probe.json`・spec 韜晦 §16.1） |
| `book9/` | KataGo の 9路の本（katagobooks.org `book9x9tt`）を読んだコード（`book9.py`・`book9deep.py`。curl で web から取る＝テストでは走らせない・取ったデータはコミットしない。`book9deep.py` は `book9/` を cwd にして走らせる） |

確認: `python docs/superpowers/specs/calibration-data/selfplay/calib_targets.py` が
`opp all n= 715 match=0.218 loss=1.74`（相手 18局・全手まとめ）と `median 78.5`（手数）を出す。

**注意: `offline_report.py` と `recon_logs.py` はコミット済みの `recon/` を上書きする**（`recon/report_game_*.json`・
`report_all.json`・`*.sgf`・`summary.json`）。ここはハーネスの投了モデル（`load_resign_lengths` / `load_resign_pool`）と
校正目標（`calib_targets.py`）が読む元データなので、走らせるなら出力先を別にするか、走らせた後に `git diff` で確かめる。

## 動作確認（2026-09-24・13路 難解＋ vs rank_3k・投了あり／19路 1局）

- seed 1000（AI 黒）: win（double_pass）157 手・own 0.410 / opp 0.130・strategy_p95 3.47 秒・wall 319 秒
- seed 1001（AI 白）: win（opp_resign）49 手・own 0.333 / opp 0.200・strategy_p95 3.23 秒・wall 83 秒
- 保存 SGF を `report-sgf` で読み直した一致率は WATCH / STRICT × 7区間で記録と完全一致。GUI の終局レポートとの一致: 確認済み（黒 40.5% / 白 14.1%＝STRICT all と一致）
- `--shadow B --hp-audit rank_9d`（難解＋ / 擬態・40手）: 影判定 20/20 手番（B の手の pointsLost 平均 0.23）、hp 監査 40/40 手
- 19路（`enigma19plus` vs rank_3k・120手まで）: win（move_cap）120 手・own 0.483 / opp 0.183・wall 200 秒・report-sgf と完全一致
