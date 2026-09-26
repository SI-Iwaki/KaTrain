# 一致率ひかえめ（韜晦）9路と序盤の研究外しの自己対局キャンペーン（2026-09-26）

計画 `docs/superpowers/plans/2026-09-26-selfplay-9x9.md` の C1〜C9・spec `../../2026-09-23-veil-strategy-design.md` §16（9路の校正と研究外しの効果の計測。
研究外しの層そのものは §15）。13路の段階（13-1〜13-4）は `veil13-campaign.md` の「序盤の研究外し（spec §15・§16.4）の計測（2026-09-26）」。
2026-09-26 にユーザーが「全部を順に走らせる」を選んだので、9路の中間報告の後もそのまま 13路まで走らせた（08:12〜15:57）。

数値は `veil9-campaign/` に写した各段の要約（`veil9-<段>-summary.{json,txt}`・`veil9-<段>-summary-vs-*.{json,txt}`）・窓の指標
（`veil9-<段>-window_stats.json`）と、実行ディレクトリの games.jsonl（`veil.*`・勝敗）・moves.jsonl（手ごとの損失とリード）から取った。
写しの中身: 9-1 は `summary-vs-spec`＝run の要約（先頭のアーム spec と各アームの差）・`summary`＝`summarize --compare open layers`。
9-2 は `summary-vs-layers`＝9-2 だけの run の要約・`summary`＝9-1 と 9-2 を合わせた `--compare open layers`（48 対）・`window_stats`＝9-1 と 9-2 を合わせたもの。
9-3〜9-5 は `summary-vs-layers`＝run の要約・`summary`＝`--compare open layers`。各段の `run.json` も `veil9-<段>-run.json` に写した（段の名前は calib9・smoke・p1・p2・p1-nores・p3book・p4strong・p5stress。
calib9 は `calibration.{json,md}` も）。実戦の窓の指標は `veil9-recon-window_stats.json`（`window_stats.py --recon` の JSON）。区間は、一致率の [95%] が局単位クラスタ bootstrap、勝ちが Wilson 95%、
対の差は信頼度 0.975（ハーネスの既定）。対の差の「判定（±3pt）」はハーネスの2回見る停止規則の目安（extend＝±3pt の内か外か決まらない）。

## 実行条件

- コード: 相手の校正（calib9）は git HEAD `e39e3e93`（`e39e3e93ea750209fab40835ad391ff08845fe14`）、スモーク以降のすべての run は `0a6f0bfe`
  （`0a6f0bfed27bf655acb7fbe8fbb6def3f20e8e0d`＝相手の校正のコミットの後）。どれも dirty false（run.json の `git`）。`ai_file` は `katrain/core/ai.py`・Python 3.12.10
- エンジン（run.json の `engine`）: KataGo v1.18.2 CUDA（`katago-v1.18.2-cuda/katago.exe`）・モデル `b10c384h6nbttflrs.bin.gz`・humanSL `b18c384nbt-humanv0.bin.gz`・
  `katrain/KataGo/analysis_config.cfg`・max_visits 2500・fast_visits 200・max_time 8.0・wide_root_noise 0.04。9路・コミ 7.0・中国ルール・hp 監査 `rank_9d`（外した手の 9段 hp）
- **設定の写し** `experiments/selfplay/veil-open-config.json`（2026-09-26 08:00 に `~/.katrain/config.json` を写したもの・sha256 `8075cd05628176faaeee53158f7dc189a9147e43947ddc10142df459136775d6`）を
  すべての run・calibrate・事後解析に `--config` で渡した。各 run の `config-snapshot.json` と run.json の `config_sha256` はすべてこの値（段の間で設定は変わっていない）。
  写しの `ai:veil9` は spec アームと同じ値（spec §6.1 の 9路の列・層は OFF＝ユーザーの今の 9路の設定）
- 研究外しの任せる先と `enigma` アーム＝写しの `ai:enigma9plus`（ユーザー設定・指紋 `90e4adbeb5877e1a`。`open` アームの run.json の `delegate` と `enigma` アームの fingerprint が同じ）:

```json
{"enigma9plus_max_loss": 1.8, "enigma9plus_large_lead_max_loss": 8.0, "enigma9plus_min_winrate": 0.3, "enigma9plus_net_margin": 0.0, "enigma9plus_target_score": 1.0, "enigma9plus_aim_jigo": false, "enigma9plus_endgame_move": 30, "enigma9plus_unsettled_max": 8, "enigma9plus_locality_stddev": 0.0, "enigma9plus_locality_slack": 0.3, "enigma9plus_min_delta_e": 0.2, "enigma9plus_cheap_loss": 0.3, "enigma9plus_probe_extra": 6.0, "enigma9plus_opening_humanstyle_moves": 0, "enigma9plus_gamble_until_move": 12.0, "enigma9plus_gamble_min_winrate": 0.3, "enigma9plus_gamble_min_delta_e": 0.5, "enigma9plus_overdraft_deficit": 1.0, "enigma9plus_overdraft_answered_max": 99.0, "enigma9plus_overdraft_min_fooled_lead": 1.0, "enigma9plus_overdraft_probes": 8.0}
```

- 相手プール（9-1〜9-3）: `opponent_pool_9.json`（2026-09-26 08:39:47 作成・`source_run` `experiments/selfplay/20260926_0812_calib9`）＝humanSL rank_1d / rank_3d / rank_9d・τ 1.0・
  悪手フィルタなし（下の「準備」）。9-3 はこれを定跡を知る相手で包んだ（`--book-moves 24`・`--book-loss` 既定 0.3）。9-4・9-5 は HumanStyle 9段
  （`strategy:human:human_kyu_rank=-8,modern_style=true`。run.json の `opponent` が `"kind": "strategy"`・`"override_items": ["human_kyu_rank=-8", "modern_style=true"]`）
- 投了モデル: length（`recon_9/` の実戦 16 局の手数 28〜100・中央値 48 から局ごとに投了の手数を引く）。投了なしの run だけ `--no-resign`（手数の上限 120）
- 局の割り付け: 9-1・9-3 は seed 1000〜1023、9-2 は 1024〜1047（`--seed-base 1024`）、投了なしは 1000〜1009、9-4・9-5 は 1000〜1019。
  全アームが同じ seed を打つ（対の比較）。AI の色は黒白交互、プールの段位は 6 seed ごとに rank_1d・rank_3d・rank_9d を2局ずつ（24 対で各 8 局）
- アーム（計画 C1 Step 5 の `experiments/selfplay/veil-open-arms.sh`。韜晦のアームは 25 キーをすべて明示・`enigma` は上書きなしで写しの節を読む）:

```bash
SPEC9='spec=veil9:veil9_target_rate=0.4,veil9_reserve=3.0,veil9_min_winrate=0.85,veil9_free_loss=0.2,veil9_free_wr_drop=0.03,veil9_close_drift_cap=0.0,veil9_spend_rate=0.5,veil9_max_loss=3.0,veil9_yose_max_loss=1.0,veil9_dominant_hp=0.8,veil9_dominant_max_loss=1.5,veil9_min_human_policy=0.05,veil9_natural_ratio=0.2,veil9_cost_slack=0.3,veil9_trap_mode=false,veil9_trap_min_delta_e=0.5,veil9_blunder_mode=0,veil9_blunder_max_loss=6.0,veil9_blunder_per_game=1,veil9_blunder_hp_ratio=0.7,veil9_forced_mode=0,veil9_forced_min_lead=1.0,veil9_forced_min_winrate=0.7,veil9_forced_max_loss=5.0,veil9_open_moves=0'
LOOSE9='loose9=veil9:veil9_target_rate=0.4,veil9_reserve=3.0,veil9_min_winrate=0.85,veil9_free_loss=0.3,veil9_free_wr_drop=0.03,veil9_close_drift_cap=0.0,veil9_spend_rate=1.0,veil9_max_loss=4.0,veil9_yose_max_loss=1.5,veil9_dominant_hp=1.01,veil9_dominant_max_loss=2.0,veil9_min_human_policy=0.05,veil9_natural_ratio=0.1,veil9_cost_slack=0.3,veil9_trap_mode=false,veil9_trap_min_delta_e=0.5,veil9_blunder_mode=0,veil9_blunder_max_loss=6.0,veil9_blunder_per_game=1,veil9_blunder_hp_ratio=0.7,veil9_forced_mode=0,veil9_forced_min_lead=1.0,veil9_forced_min_winrate=0.7,veil9_forced_max_loss=5.0,veil9_open_moves=0'
LAYERS9='layers=veil9:veil9_target_rate=0.4,veil9_reserve=3.0,veil9_min_winrate=0.85,veil9_free_loss=0.3,veil9_free_wr_drop=0.03,veil9_close_drift_cap=0.0,veil9_spend_rate=1.0,veil9_max_loss=4.0,veil9_yose_max_loss=1.5,veil9_dominant_hp=1.01,veil9_dominant_max_loss=2.0,veil9_min_human_policy=0.05,veil9_natural_ratio=0.1,veil9_cost_slack=0.3,veil9_trap_mode=false,veil9_trap_min_delta_e=0.5,veil9_blunder_mode=2,veil9_blunder_max_loss=6.0,veil9_blunder_per_game=1,veil9_blunder_hp_ratio=0.7,veil9_forced_mode=2,veil9_forced_min_lead=1.0,veil9_forced_min_winrate=0.7,veil9_forced_max_loss=5.0,veil9_open_moves=0'
OPEN9='open=veil9:veil9_target_rate=0.4,veil9_reserve=3.0,veil9_min_winrate=0.85,veil9_free_loss=0.3,veil9_free_wr_drop=0.03,veil9_close_drift_cap=0.0,veil9_spend_rate=1.0,veil9_max_loss=4.0,veil9_yose_max_loss=1.5,veil9_dominant_hp=1.01,veil9_dominant_max_loss=2.0,veil9_min_human_policy=0.05,veil9_natural_ratio=0.1,veil9_cost_slack=0.3,veil9_trap_mode=false,veil9_trap_min_delta_e=0.5,veil9_blunder_mode=2,veil9_blunder_max_loss=6.0,veil9_blunder_per_game=1,veil9_blunder_hp_ratio=0.7,veil9_forced_mode=2,veil9_forced_min_lead=1.0,veil9_forced_min_winrate=0.7,veil9_forced_max_loss=5.0,veil9_open_moves=12'
ENIGMA9='enigma=enigma9plus'
HUMAN9='human=human:human_kyu_rank=-8,modern_style=true'
```

  設定の指紋（run.json）: spec `b07e0c46488b0bbc`・loose9 `9b60a3dd0b3fe986`・layers `6b2d487160cead57`・open `8296fcbc694a283b`・enigma `90e4adbeb5877e1a`・human `6ba8aa2354d6faac`（段をまたいで同じ）

| 段 | ラベル・出力ディレクトリ | 局数 | 所要（開始は run.json の `created`、終了は games.jsonl の最終更新。コンソールに時刻が無いため） |
|---|---|---|---|
| 相手の校正 | `calib9`（`experiments/selfplay/20260926_0812_calib9`） | 40（5 段位 × 8）・aborted 0 | 08:12〜08:39（約27分）。対局時間の合計 26.8分 |
| スモーク | `veil9-smoke`（`experiments/selfplay/20260926_0840_veil9-smoke`） | 4（layers・open × 2 seed）・aborted 0 | 08:40〜08:43（約3分） |
| 9-1 校正 | `veil9-p1`（`experiments/selfplay/20260926_0843_veil9-p1`） | 144（6 アーム × 24 seed）・aborted 0 | 08:43〜09:48（約1時間5分・見込み約2時間）。対局時間の合計は spec 10.0分・loose9 9.0分・layers 9.1分・open 10.9分・enigma 13.9分・human 11.5分 |
| 9-2 研究外しの効果 | `veil9-p2`（`experiments/selfplay/20260926_0949_veil9-p2`） | 48（2 アーム × 24 seed）・aborted 0 | 09:49〜10:12（約23分）。layers 11.3分・open 11.5分 |
| 投了なし | `veil9-p1-nores`（`experiments/selfplay/20260926_1013_veil9-p1-nores`） | 20（2 アーム × 10 seed）・aborted 0 | 10:13〜10:29（約16分）。layers 7.2分・open 9.1分 |
| 9-3 定跡を知る相手 | `veil9-p3book`（`experiments/selfplay/20260926_1030_veil9-p3book`） | 72（3 アーム × 24 seed）・aborted 0 | 10:30〜10:57（約27分）。layers 7.5分・open 8.3分・enigma 11.1分 |
| 9-4 強い相手 | `veil9-p4strong`（`experiments/selfplay/20260926_1057_veil9-p4strong`） | 60（3 アーム × 20 seed）・aborted 0 | 10:57〜11:24（約27分）。layers 7.8分・open 9.1分・enigma 9.6分 |
| 9-5 接戦ストレス | `veil9-p5stress`（`experiments/selfplay/20260926_1125_veil9-p5stress`） | 60（3 アーム × 20 seed）・aborted 0 | 11:25〜11:49（約24分）。layers 8.5分・open 7.7分・enigma 7.4分 |

9路は相手の校正からまとめて約3時間36分（見込みは準備を含めて約7.8時間）。コンソールは `experiments/selfplay/<ラベル>.console.txt`、集計の出力は
`experiments/selfplay/veil9-p1-open-vs-layers.txt`・`veil9-p1-window.txt`・`veil9-p12-open-vs-layers.txt`・`veil9-p12-window.txt`・`veil9-p1-nores-vs-p1.txt`・
`veil9-p3book-*.txt`・`veil9-p4strong-*.txt`・`veil9-p5stress-*.txt`（どれも本体のチェックアウトの `experiments/selfplay/` に移した・gitignore）。

- 実行（例。`source experiments/selfplay/veil-open-arms.sh` の後）:
  - 9-1: `python -m katrain_debug.selfplay run --size 9 --pairs 24 --config "$CFG" --hp-audit rank_9d --label veil9-p1 --arm "$SPEC9" --arm "$LOOSE9" --arm "$LAYERS9" --arm "$OPEN9" --arm "$ENIGMA9" --arm "$HUMAN9"`
  - 9-2: 同じ形で `--seed-base 1024 --label veil9-p2 --arm "$LAYERS9" --arm "$OPEN9"`／投了なし: `--pairs 10 --no-resign --label veil9-p1-nores --arm "$LAYERS9" --arm "$OPEN9"`
  - 9-3: `--book-moves 24 --label veil9-p3book --arm "$LAYERS9" --arm "$OPEN9" --arm "$ENIGMA9"`／9-4: `--pairs 20 --opponent "$STRONG" --label veil9-p4strong …`／
    9-5: `--pairs 20 --komi-shift 2 --opponent "$STRONG" --label veil9-p5stress …`（9-1〜9-3 はプールが既定＝`opponent_pool_9.json`）
- 健全性: 全段で aborted 0・コンソールに `WARN integrity` の行なし・fallbacks 0・humansl_errors 0・hp_audit_errors 0・shadow_errors 0・visits_low 0・
  韜晦のアームの ledger_mismatch 0。コンソールの警告は、段位 × 色の数が 6 の倍数でない投了なし（10 seed＝4/4/2 局）とスモーク（2 seed）の偏りの警告だけ
  （計画の「spec のあいまいさ」10）。lead < reserve での同値でない外し（`veil.nonfree_below_reserve`）は layers・open で 3〜22/段あるが、
  moves.jsonl の kind で数えると**すべて forced の層の手**（forced はリードが forced_min_lead 以上残る範囲で reserve 未満でも打つ設計）で、ほかの層の手は 0
- 研究外しの窓の確かめ（`window_stats.json` の `open`）: open アームは全段で窓の手がすべて `played`（9-1 144・9-2 144・投了なし 60・9-3 144・9-4 120・9-5 120 手番）・
  `games_with_open` が全局・`open_missing_inside` 0・`open_outside` 0。`veil.opening` の gate 0・invariant 0・errors 0・not_in_cands 0（任せた手はすべて通常解析の候補の中）
- スモーク（2 対）: layers 2-0（own 58.8% / 51.9%）・open 2-0（48.8% / 63.0%）。open の窓の手は 12 手番すべて `played`・run.json に `delegate`（`ai:enigma9plus`・user config）

## 準備

### 実戦の復元と事後解析（C2）

- `recon_logs.py --size 9 --log-dir experiments/selfplay/realgames-9x9-logs --out recon_9`（コンソール `experiments/selfplay/recon9.console.txt`）: 難解＋9路の実戦 **16 局**。
  持碁9路 `game_20260919_224212`（初手だけ難解＋）を除いた。直したこと: 相手の初手が root の置き石になっていた 4 局（`213546`・`215145`・`223517`・`201809`）は
  その手を初手として戻し、`223015` は監視の外の相手のパスを 28 手目に挟んだ（`opponent passed but the board is not settled` の行）。`!!` の行 0
- 同じ置き場から一致率ひかえめ9路の実戦 8 局を `--strategy Veil9Strategy` で `recon_9_veil/` に分けて復元した（下の「実戦」。置き石の初手 2 局を直した）
- 事後解析: `offline_report.py --dir recon_9 --config experiments/selfplay/veil-open-config.json`（2500v・コンソール `offline9.console.txt`）。16 局すべて `report_game_*.json`・
  `TIMEOUT` なし（1局 14〜43 秒・合わせて約6分）。`recon_9_veil` も同じ（8 局・約2.5分・`offline9veil.console.txt`）
- 実戦 16 局の結果（事後解析の最終リード・AI 視点）: 14 局は勝ち、`213928` は −2.0 目（負け）、`223517` は 0.0 目（持碁）＝**14-1-1**。手数 28〜100・中央値 48
- **データの注意**:
  - recon の summary の `settings` は局の最初の `Initializing` 行のまま。`214631`・`222543` は途中で `overdraft_answered_max` が 99→0 に変わり、`100100` は `aim_jigo`・
    `gamble_until_move` が変わった（`recon9.console.txt` の `settings changed during the game:` の 3 行）。C4 の多数決の上書きはこの最初の設定で計算した。
    `095719`・`095858`・`100100` の最初の設定は `aim_jigo` true（除く局には挙げていない。相手側の目標と投了の手数には入れたまま・AI 側の目標は多数派の 7 局なので影響しない）
  - 自分・相手の一致率（top1）と `window_stats.py --recon` の `opp_streak` は完全一致でしか数えない。盤がほぼ空の序盤（1〜3 手目・§16.1 の 4-4 / 4-5 / 天元 / 3-5 のような
    0.12目以内の同格の初手）では、対称で同格な手を打っても不一致に数える（過小評価の方向。下の「実戦」の比較にも同じ注意）

### 校正の目標 `CALIB_TARGETS_9`（C3）

`calib_targets.py recon_9 --size 9 --ai-where enigma9plus_max_loss=1.6,enigma9plus_target_score=0.2,enigma9plus_gamble_until_move=20`（`experiments/selfplay/calib-targets-9.txt`）の最後の3行:

```
games 16 / ai_mean over 7 (enigma9plus_max_loss=1.6,enigma9plus_target_score=0.2,enigma9plus_gamble_until_move=20)
CALIB_TARGET_GAMES 7/16
CALIB_TARGETS {"opp_mean": 0.308, "opp_sd": 0.166, "opp_loss": 1.88, "opp_ge2": 0.23, "opp_ge5": 0.1, "ai_mean": 0.628, "moves_median": 48.0, "bins": {"cal_opening": {"opp_top1": 0.233, "opp_loss": 0.77}, "cal_middle": {"opp_top1": 0.332, "opp_loss": 2.4}, "cal_endgame": {"opp_top1": 0.355, "opp_loss": 0.78}}}
```

相手側は 16 局、AI 側（`ai_mean` 62.8%）は実戦の多数派の設定の 7 局。9路の区間は 13路と同じ割合（24/169・85/169）で 12 / 41 手（序盤 <12・中盤 12〜40・終盤 >=41）。

### 相手の校正（C4）

`calibrate --size 9 --strategy enigma9plus:<多数派の 7 局の設定と写しの違い 7 キー> --ranks rank_1d,rank_3d,rank_5d,rank_7d,rank_9d --games 8 --config experiments/selfplay/veil-open-config.json --label calib9 --write-pool opponent_pool_9.json`
（上書き: gamble_min_winrate 0.25・gamble_until_move 20・large_lead_max_loss 6.0・max_loss 1.6・overdraft_deficit 2.0・overdraft_probes 6・target_score 0.2）。
結果の全文は `selfplay-calibration-results-20260926-9x9.md`。

| 段位 | 局数 | 相手 一致率 局平均 | 局間 SD | 損失/手 | 中盤 一致 / 損失 | AI 一致率 | 手数中央値 |
|---|---|---|---|---|---|---|---|
| rank_1d | 8 | 25.4% | 13.3pt | 1.62 | 28.0% / 2.33 | 62.4% | 53 |
| rank_3d | 8 | 30.9% | 15.3pt | 1.19 | 35.5% / 1.51 | 67.1% | 50 |
| rank_5d | 8 | 31.2% | 8.9pt | 1.37 | 35.7% / 1.44 | 63.3% | 56 |
| rank_7d | 8 | 34.7% | 11.9pt | 1.00 | 37.7% / 1.20 | 68.3% | 56 |
| rank_9d | 8 | 38.0% | 16.9pt | 1.46 | 44.8% / 1.54 | 67.5% | 56 |
| **実戦（目標）** | 7/16 | 30.8% | 16.6pt | 1.88 | 33.2% / 2.40 | 62.8% | 48.0 |

- 選んだプール: **rank_1d・rank_3d・rank_9d**（スコア 3.83・1位。2位は rank_1d・rank_5d・rank_9d の 4.32）＝相手の一致率 31.4%（目標 30.8%）・局間 SD 16.1pt（16.6pt）・
  損失 1.42 目/手（1.88。どのプールも目標より小さい）・中盤 36.1% / 1.79 目
- ハーネスと実戦のずれ（AI 側）: 選んだプールでの AI の一致率 65.7% − 実戦 62.8% = **+2.9pt**（実戦の予測はこの差を引いて読む）。手数の中央値 55.0（実戦 48）
- 校正の 40 局の AI（難解＋・多数派の設定）の結果は 37-2-1（持碁 seed 1016・負け 1024 −2.0 目・1038 −1.1 目）

## 9-1 校正

6 アーム × 24 対。数値は `veil9-p1-summary-vs-spec.{json,txt}`（対の差は spec − アーム）。

| アーム | 勝-負-持碁 [勝ちの Wilson 95%] | 自分の一致率 局平均 [95%] | 相手の一致率 局平均 | 自分 / 相手の損失（目/手） | ≥6目/局 | flip/局 | 最終リードの中央値 | 手数の中央値 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） |
|---|---|---|---|---|---|---|---|---|---|---|
| spec | 24-0-0 [86.2, 100.0] | 62.6% [58.3, 66.9] | 30.7% | 0.19 / 1.32 | 0.12 | 0.04 | +27.7 | 52 | 27.9%（243） | 0.27 |
| loose9 | 24-0-0 [86.2, 100.0] | 61.5% [55.5, 67.2] | 35.2% | 0.20 / 1.15 | 0.00 | 0.04 | +24.2 | 51.5 | 28.3%（251） | 0.29 |
| layers | 24-0-0 [86.2, 100.0] | 52.8% [47.4, 58.4] | 38.8% | 0.27 / 1.09 | 0.04 | 0.08 | +19.0 | 51.5 | 28.5%（304） | 0.37 |
| open | 24-0-0 [86.2, 100.0] | 57.3% [53.4, 61.5] | 32.2% | 0.42 / 1.42 | 0.08 | 1.04 | +22.2 | 51 | 19.3%（259） | 0.91 |
| enigma | 24-0-0 [86.2, 100.0] | 59.5% [54.2, 64.5] | 28.7% | 0.82 / 1.34 | 0.83 | 1.71 | +11.4 | 51 | 2.2%（246） | 1.74 |
| human | 23-0-1 [79.8, 99.3] | 67.9% [63.8, 72.2] | 33.1% | 0.43 / 1.34 | 0.42 | 0.67 | +22.9 | 51.5 | 32.5%（213） | 0.48 |

spec との差（spec − アーム・信頼度 0.975）:

| 対の差 | 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p | 判定（±3pt） |
|---|---|---|---|---|---|---|
| spec − loose9 | own_top1 | +1.1pt | -5.2 〜 +7.3 | -4.6 〜 +6.8 | 0.7943 | extend |
| spec − loose9 | opp_top1 | -4.5pt | -13.1 〜 +4.2 | -12.5 〜 +3.4 | 0.2455 | extend |
| spec − loose9 | flip_moves | +0.00 | -0.14 〜 +0.14 | -0.12 〜 +0.12 | 1.0000 | - |
| spec − loose9 | own_mean_ptloss | -0.01 | -0.11 〜 +0.10 | -0.11 〜 +0.09 | 0.5838 | - |
| spec − loose9 | ge6 | +0.12 | -0.09 〜 +0.34 | +0.00 〜 +0.38 | 0.5000 | - |
| spec − layers | own_top1 | +9.8pt | +2.6 〜 +17.0 | +2.8 〜 +16.1 | 0.0047 | extend |
| spec − layers | opp_top1 | -8.1pt | -14.9 〜 -1.3 | -14.6 〜 -2.1 | 0.0096 | extend |
| spec − layers | flip_moves | -0.04 | -0.22 〜 +0.13 | -0.21 〜 +0.12 | 0.5637 | - |
| spec − layers | own_mean_ptloss | -0.07 | -0.18 〜 +0.04 | -0.17 〜 +0.02 | 0.0951 | - |
| spec − layers | ge6 | +0.08 | -0.16 〜 +0.33 | -0.12 〜 +0.33 | 0.4142 | - |
| spec − open | own_top1 | +5.3pt | -0.0 〜 +10.6 | +0.4 〜 +10.3 | 0.0403 | extend |
| spec − open | opp_top1 | -1.4pt | -9.8 〜 +6.9 | -8.8 〜 +6.1 | 0.6813 | extend |
| spec − open | flip_moves | -1.00 | -1.46 〜 -0.54 | -1.42 〜 -0.58 | 0.0004 | - |
| spec − open | own_mean_ptloss | -0.23 | -0.36 〜 -0.09 | -0.34 〜 -0.09 | 0.0010 | - |
| spec − open | ge6 | +0.04 | -0.23 〜 +0.31 | -0.17 〜 +0.29 | 0.7055 | - |
| spec − enigma | own_top1 | +3.1pt | -4.5 〜 +10.7 | -3.7 〜 +10.3 | 0.4114 | extend |
| spec − enigma | opp_top1 | +2.0pt | -5.1 〜 +9.1 | -4.4 〜 +8.6 | 0.4978 | extend |
| spec − enigma | flip_moves | -1.67 | -2.44 〜 -0.89 | -2.42 〜 -1.00 | 0.0003 | - |
| spec − enigma | own_mean_ptloss | -0.63 | -0.87 〜 -0.39 | -0.85 〜 -0.41 | 0.0000 | - |
| spec − enigma | ge6 | -0.71 | -1.15 〜 -0.26 | -1.12 〜 -0.33 | 0.0021 | - |
| spec − human | own_top1 | -5.4pt | -12.0 〜 +1.2 | -11.6 〜 +0.6 | 0.1207 | extend |
| spec − human | opp_top1 | -2.3pt | -11.9 〜 +7.2 | -10.6 〜 +6.8 | 0.3457 | extend |
| spec − human | flip_moves | -0.62 | -1.27 〜 +0.02 | -1.29 〜 -0.12 | 0.0160 | - |
| spec − human | own_mean_ptloss | -0.23 | -0.52 〜 +0.06 | -0.55 〜 -0.05 | 0.0039 | - |
| spec − human | ge6 | -0.29 | -0.84 〜 +0.26 | -0.88 〜 +0.08 | 0.1975 | - |

リード・区間別・終局:

| アーム | 最終リードの中央値 [IQR] | 自分の一致率 全手まとめ（序盤 / 中盤 / 終盤＝cal 区間 <12 / 12〜40 / >=41） | 終局の内訳 |
|---|---|---|---|
| spec | +27.7 [+21.0, +49.8] | 62.8%（65.2% / 61.6% / 63.1%） | double_pass 2・opp_resign 22 |
| loose9 | +24.2 [+5.8, +41.3] | 59.8%（61.4% / 63.1% / 51.6%） | double_pass 3・opp_resign 21 |
| layers | +19.0 [+5.8, +38.1] | 51.5%（56.1% / 50.3% / 50.3%） | double_pass 5・opp_resign 19 |
| open | +22.2 [+8.1, +42.6] | 56.9%（41.7% / 61.1% / 61.6%） | double_pass 4・opp_resign 20 |
| enigma | +11.4 [+5.2, +17.8] | 59.7%（46.2% / 59.5% / 73.2%） | double_pass 3・opp_resign 21 |
| human | +22.9 [+6.0, +46.0] | 67.2%（63.6% / 70.5% / 63.7%） | double_pass 3・opp_resign 21 |

韜晦のアームの判定情報（`veil.*`・24 局の合計。括弧は局平均）:

| アーム | 局 | tiers（i / ii / iii / forced / blunder / opening / terminal） | kinds（打った手の種類） | 払った vloss の合計（/局） | 窓の手（任せた手番・kind opening・レポートの損失の合計・≥2目 / ≥6目） | lead < reserve での同値でない外し（すべて forced の層） | ledger_mismatch |
|---|---|---|---|---|---|---|---|
| spec | 24 | 342 / 22 / 267 / 0 / 0 / 0 / 18 | best 406・paid 102・free 80・decided 51・swap 8・pass 2 | 74.2 目（3.09） | — | 0 | 0 |
| loose9 | 24 | 307 / 0 / 285 / 0 / 0 / 0 / 36 | best 377・paid 80・free 92・decided 52・swap 25・pass 2 | 94.5 目（3.94） | — | 0 | 0 |
| layers | 24 | 272 / 0 / 275 / 56 / 0 / 0 / 23 | best 322・paid 63・free 111・forced 56・decided 55・swap 15・pass 4 | 146.1 目（6.09） | — | 20 | 0 |
| open | 24 | 250 / 0 / 157 / 34 / 1 / 144 / 14 | best 341・opening 82・paid 57・free 29・forced 34・decided 48・blunder 1・swap 6・pass 2 | 129.6 目（5.40） | 144・82・55.6 目・3 / 0 | 8 | 0 |

読み方:
- **loose9（13路の loose を縮めた暫定の案）は spec と差がない**（61.5% vs 62.6%・spec − loose9 +1.1pt [t −5.2, +7.3]）。13路では loose が一致率を約 6.5pt 下げたが、9路では下がらなかった
- **下げたのは層（layers＝loose9 ＋ 失着 ＋ forced）**: 52.8%・spec − layers +9.8pt [t +2.6, +17.0]（Wilcoxon p 0.0047）。9-1 の layers で失着の層の手は 0（tiers blunder 0）で、
  forced の層が 56 手（2.33 回/局）＝下げ幅はほぼ forced の層。勝ち・flip・≥6目は spec と変わらない（24-0・flip 0.08/局・≥6目 0.04/局）
- open（layers ＋ 研究外し 12）は 57.3%＝layers より高い（9-1 だけで open − layers +4.5pt [t −3.4, +12.4]・`veil9-p1-summary.txt`）。flip は 1.04/局（layers 0.08・spec − open −1.00 [−1.46, −0.54]）で、
  ほぼすべて窓の中（下の「研究外しの効果」の flip 窓の中 / 後）。外した手の 9段 hp 中央値は 19.3%（窓の難解＋の手を含む。layers 28.5%・enigma 2.2%）
- enigma（難解＋9路・今のユーザー設定）は 59.5%・flip 1.71/局・≥6目 0.83/局・損失 0.82 目/手。human（HumanStyle 9段）は 67.9%（持碁 1＝seed 1004）
- 全アームで勝ちは 24/24（human だけ 23-0-1）＝通常の相手では勝敗の差は出ない

## 研究外しの効果（9-1＋9-2・48 対）

9-2（`layers`・`open` × 24 対・seed 1024〜1047）を 9-1 の同じ2アームと合わせた（`summarize` の合算は git HEAD の一致を見る＝9-1 と 9-2 の間はコミットしていない）。
9-2 だけでは layers 57.0% [53.1, 61.1]・open 58.0% [53.6, 62.2]（layers − open −1.0pt [t −8.3, +6.4]・flip −1.17 [−1.82, −0.51]・どちらも 24-0-0・`veil9-p2-summary-vs-layers.txt`）。

| アーム | 勝-負-持碁 [勝ちの Wilson 95%] | 自分の一致率 局平均 [95%] | 相手の一致率 局平均 | 自分 / 相手の損失（目/手） | ≥6目/局 | flip/局 | 最終リードの中央値 | 手数の中央値 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） |
|---|---|---|---|---|---|---|---|---|---|---|
| layers | 48-0-0 [92.6, 100.0] | 54.9% [51.5, 58.3] | 35.5% | 0.31 / 1.13 | 0.06 | 0.06 | +19.6 | 52 | 26.9%（595） | 0.39 |
| open | 48-0-0 [92.6, 100.0] | 57.6% [54.7, 60.6] | 32.7% | 0.37 / 1.28 | 0.08 | 1.12 | +17.8 | 51.5 | 19.2%（536） | 0.90 |

対の差（open − layers・48 対・信頼度 0.975・`veil9-p2-summary.{json,txt}`）:

| 対の差 | 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p | 判定（±3pt） |
|---|---|---|---|---|---|---|
| open − layers | own_top1 | +2.7pt | -2.5 〜 +7.9 | -2.4 〜 +7.5 | 0.1524 | extend |
| open − layers | opp_top1 | -2.8pt | -8.8 〜 +3.2 | -8.4 〜 +2.9 | 0.2536 | extend |
| open − layers | own_minus_opp | +5.5pt | -2.0 〜 +13.0 | -1.7 〜 +12.6 | 0.1073 | extend |
| open − layers | flip_moves | +1.06 | +0.68 〜 +1.45 | +0.71 〜 +1.46 | 0.0000 | - |
| open − layers | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| open − layers | own_mean_ptloss | +0.06 | -0.04 〜 +0.16 | -0.04 〜 +0.16 | 0.2036 | - |
| open − layers | ge6 | +0.02 | -0.11 〜 +0.15 | -0.10 〜 +0.15 | 0.7055 | - |

窓の指標（W 12＝手数 12 以下が窓の中。`veil9-p2-window_stats.json`。layers・open は 48 局、ほかのアームは 9-1 の 24 局）:

| アーム | 局 | 自分 窓の中 / 後 | 相手 窓の中 / 後 | 自分の損失 窓の中 / 後（目/手） | 相手の損失 窓の中 / 後 | 窓の中の ≥2目 / ≥6目（/局） | W 手目のリード 中央値 [IQR]・最小・負の局 | flip 窓の中 / 後（/局） | 窓の後の u の平均 | 窓の後の paid/局 |
|---|---|---|---|---|---|---|---|---|---|---|
| spec | 24 | 66.7% / 61.6% | 33.3% / 30.0% | 0.10 / 0.25 | 0.64 / 1.57 | 0.00 / 0.00 | +3.6 [+2.4, +4.7]・+0.4・0/24 | 0.04 / 0.00 | 0.97 | 4.25 |
| loose9 | 24 | 61.1% / 62.2% | 36.8% / 34.6% | 0.12 / 0.22 | 0.71 / 1.21 | 0.04 / 0.00 | +3.9 [+2.9, +4.7]・-0.0・1/24 | 0.04 / 0.00 | 0.89 | 3.29 |
| layers | 48 | 58.0% / 54.0% | 36.8% / 34.7% | 0.20 / 0.32 | 0.71 / 1.22 | 0.12 / 0.00 | +3.4 [+2.1, +4.1]・-0.0・1/48 | 0.06 / 0.00 | 0.86 | 3.08 |
| open | 48 | 44.8% / 62.0% | 27.4% / 34.3% | 0.39 / 0.37 | 0.69 / 1.48 | 0.15 / 0.00 | +1.2 [+0.3, +2.8]・-2.6・9/48 | 1.10 / 0.02 | 0.86 | 2.56 |
| enigma | 24 | 47.2% / 63.8% | 27.8% / 28.6% | 0.55 / 0.85 | 0.90 / 1.43 | 0.50 / 0.08 | +2.6 [-0.1, +3.3]・-1.7・7/24 | 0.96 / 0.75 | — | 0.00 |
| human | 24 | 65.3% / 68.0% | 38.2% / 32.2% | 0.13 / 0.57 | 0.58 / 1.63 | 0.00 / 0.00 | +2.7 [+0.5, +5.0]・-1.3・4/24 | 0.38 / 0.29 | — | 0.00 |

| 対の差（open − layers・48 対・信頼度 0.975） | 平均 | t 区間 | Wilcoxon p |
|---|---|---|---|
| own_in | -13.2pt | -24.0 〜 -2.4 | 0.0194 |
| own_out | +8.1pt | +2.1 〜 +14.1 | 0.0038 |
| opp_in | -9.4pt | -18.0 〜 -0.8 | 0.0459 |
| opp_out | -0.4pt | -7.0 〜 +6.2 | 0.8564 |
| lead_at_w（目） | -1.51 | -2.61 〜 -0.41 | 0.0006 |

（9-1 だけの 24 対: own_in −11.8pt [t −25.3, +1.7]・own_out +10.1pt [+0.6, +19.7]（Wilcoxon p 0.017）・opp_in −11.8pt・lead_at_w −1.19 目・`veil9-p1-window_stats.json`）

窓の手の中身（open・48 局・`veil.opening`）: 任せた手番 288（1局 6 手番）のうち best と違う手（kind opening）159、レポートの損失の合計 111.1 目（1手番 0.39 目）・≥2目の手 7・≥6目の手 0。
判定情報の合計（48 局）: layers は tiers i 592 / iii 556 / forced 98 / blunder 1 / terminal 57・kinds best 709・free 186・paid 153・decided 119・forced 98、
open は tiers i 532 / iii 336 / forced 61 / blunder 3 / opening 288 / terminal 45・kinds best 729・opening 159・paid 123・free 76・decided 85・forced 61。

窓の後（手数 13 以降）の AI の手番の内訳（moves.jsonl の `decision_lead` < `decision_reserve`（3 目）と `decision_kind` を数えた。9-1＋9-2）:

| アーム | 窓の後の AI の手番 | lead < reserve の手番 | 最善手（kind best） | paid | free | forced |
|---|---|---|---|---|---|---|
| layers | 1016 | 10.6% | 53.3% | 14.6% | 9.3% | 7.5% |
| open | 977 | 21.3% | 61.4% | 12.6% | 7.8% | 6.2% |

読み方:
- **局全体の自分の一致率は下がらない**: open − layers +2.7pt [t −2.5, +7.9]（48 対）。窓の中は −13.2pt（有意）と下がるが、窓の後で +8.1pt（p 0.004）上がり、打ち消し以上になる
- 仕組み: 窓の中の難解＋の外し（1手番 0.39 目）で W 手目のリードが 1.5 目小さくなり（中央値 +3.4 → +1.2 目・負の局 1 → 9）、窓の後は lead < reserve（3 目）の手番が
  10.6% → 21.3% に増える。lead < reserve では同値外ししかできないので、窓の後の最善手が 53.3% → 61.4% に増え、支払う外し（paid）は 3.08 → 2.56 回/局に減る。
  窓の後の u の平均は同じ（0.86）
- 相手の一致率は窓の中で −9.4pt（36.8% → 27.4%）下がるが、窓の後は変わらない（−0.4pt）
- 安全: 勝ちは 48-0 どうし。flip は +1.06/局だが、ほぼ窓の中（open 1.10 / 0.02）。窓の中の ≥6目の手は 0、≥2目は 0.15/局（layers 0.12）

## 投了なし（9-1 の 10 対）

`--no-resign`（手数の上限 120）で layers・open を seed 1000〜1009 の 10 対だけ打った（ハーネス spec §3）。数値は `veil9-p1-nores-summary.{json,txt}`（run の要約＝layers − open）と
`experiments/selfplay/veil9-p1-nores-vs-p1.txt`（同じ seed の投了ありの局＝9-1 との比較）。

| アーム | 勝-負-持碁 [勝ちの Wilson 95%] | 自分の一致率 局平均 [95%] | 相手の一致率 局平均 | 自分 / 相手の損失（目/手） | ≥6目/局 | flip/局 | 最終リードの中央値 | 手数の中央値 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） |
|---|---|---|---|---|---|---|---|---|---|---|
| layers | 10-0-0 [72.2, 100.0] | 58.8% [52.7, 65.4] | 33.4% | 0.24 / 0.83 | 0.10 | 0.10 | +28.5 | 81 | 29.8%（177） | 0.35 |
| open | 10-0-0 [72.2, 100.0] | 47.6% [43.4, 51.8] | 23.6% | 0.36 / 1.32 | 0.10 | 1.10 | +65.4 | 97.5 | 26.8%（248） | 0.73 |

- 対の差 layers − open: own_top1 **+11.2pt** [t +0.4, +21.9 / bootstrap +2.5, +19.5]（Wilcoxon p 0.0195）・opp_top1 +9.8pt [−4.6, +24.2]・flip −1.00 [−2.27, +0.27]・勝ち 0・≥6目 0
- 同じ seed の投了あり（9-1）との比較: layers 51.9%（手数の中央値 50.5）→ 投了なし 58.8%（81）＝+6.9pt、open 58.4%（50.5）→ 47.6%（97.5）＝**−10.8pt**
- 終局: どちらも double_pass 7・手数の上限 3（上限の局の最終リード +42.6〜+99.9 目）。区間別の自分の一致率は layers 58.9%（56.4% / 60.0% / 58.7%）・open 47.6%（47.3% / 49.7% / 46.6%）
- **向きが逆になる**: 投了ありの 48 対では open が高い（+2.7pt）が、投了なしの 10 対では open が 11.2pt 低い（layers 58.8% vs open 47.6%）。投了なしでは局が 81〜98 手（中央値）まで
  長くなり、open は大差のまま長い終盤を打つ（最終リードの中央値 +65.4 目）。実戦は 48 手前後（`recon_9/` の中央値）で投了されるので、**投了ありの run を基準にする**

## 9-3 定跡を知る相手

プールの相手を `--book-moves 24`（`--book-loss` 0.3）で包んだ（相手の手番の手数が 24 未満で、それまでの AI の手がすべて損失 0.3 目以下の間は KataGo の最善手を打ち、AI が
一度でも 0.3 目を超える手を打ったらその局の残りは humanSL）。ユーザーの仮説（こちらが定跡どおりだと高段の BOT が最善手を続ける）のモデル。数値は `veil9-p3book-summary-vs-layers.*`・
`veil9-p3book-summary.*`（open − layers）・`veil9-p3book-window_stats.json`。

定跡の出口（games.jsonl の `opponent_stats`・`window_stats` の `book_exit`）:

| アーム | 出口の手数 中央値（最小） | 出口の理由（AI の損失 `ai_loss` / 上限 24 `limit`） | 相手が定跡で打った手/局 | 出口の手が実は最善手だった数（雑音の出口） | 出口の手の損失 中央値 / 平均 |
|---|---|---|---|---|---|
| layers | 24（5） | 11 / 13 | 9.0 | 2/11 | 0.64 / 0.83 目 |
| open | 4（3） | 14 / 10 | 6.1 | 0/14 | 0.80 / 0.87 目 |
| enigma | 4（3） | 21 / 3 | 4.5 | 1/21 | 0.67 / 0.75 目 |

| アーム | 勝-負-持碁 [勝ちの Wilson 95%] | 自分の一致率 局平均 [95%] | 相手の一致率 局平均 | 自分 / 相手の損失（目/手） | ≥6目/局 | flip/局 | 最終リードの中央値 | 手数の中央値 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） |
|---|---|---|---|---|---|---|---|---|---|---|
| layers | 21-0-3 [69.0, 95.7] | 58.2% [54.6, 61.9] | 64.2% | 0.15 / 0.75 | 0.04 | 0.12 | +4.9 | 53 | 26.7%（263） | 0.38 |
| open | 20-0-4 [64.1, 93.3] | 64.4% [59.7, 69.2] | 53.8% | 0.30 / 0.88 | 0.21 | 1.17 | +8.2 | 51 | 20.8%（219） | 0.45 |
| enigma | 18-0-6 [55.1, 88.0] | 65.8% [60.6, 71.1] | 44.1% | 0.51 / 1.03 | 0.62 | 1.42 | +7.7 | 51.5 | 6.6%（217） | 1.39 |

| 対の差 | 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p | 判定（±3pt） |
|---|---|---|---|---|---|---|
| open − layers | own_top1 | +6.2pt | -2.2 〜 +14.7 | -1.8 〜 +13.8 | 0.1140 | extend |
| open − layers | opp_top1 | -10.4pt | -22.5 〜 +1.8 | -21.4 〜 +0.9 | 0.0698 | extend |
| open − layers | own_minus_opp | +16.6pt | +6.0 〜 +27.2 | +7.2 〜 +26.5 | 0.0007 | higher |
| open − layers | flip_moves | +1.04 | +0.49 〜 +1.59 | +0.54 〜 +1.54 | 0.0008 | - |
| open − layers | win | -0.04 | -0.22 〜 +0.13 | -0.21 〜 +0.12 | 0.5637 | - |
| open − layers | own_mean_ptloss | +0.15 | -0.16 〜 +0.46 | -0.06 〜 +0.50 | 0.3596 | - |
| open − layers | ge6 | +0.17 | -0.23 〜 +0.57 | +0.00 〜 +0.67 | 1.0000 | - |
| layers − enigma | own_top1 | -7.6pt | -16.7 〜 +1.5 | -15.7 〜 +0.9 | 0.0564 | extend |
| layers − enigma | opp_top1 | +20.0pt | +8.3 〜 +31.8 | +9.5 〜 +31.1 | 0.0010 | higher |
| layers − enigma | flip_moves | -1.29 | -2.08 〜 -0.51 | -2.04 〜 -0.62 | 0.0009 | - |
| layers − enigma | win | +0.12 | -0.17 〜 +0.42 | -0.17 〜 +0.42 | 0.3173 | - |
| layers − enigma | ge6 | -0.58 | -1.04 〜 -0.13 | -1.04 〜 -0.21 | 0.0079 | - |

| アーム | 局 | 自分 窓の中 / 後 | 相手 窓の中 / 後 | 自分の損失 窓の中 / 後（目/手） | 相手の損失 窓の中 / 後 | 窓の中の ≥2目 / ≥6目（/局） | W 手目のリード 中央値 [IQR]・最小・負の局 | flip 窓の中 / 後（/局） | 窓の後の u の平均 | 窓の後の paid/局 |
|---|---|---|---|---|---|---|---|---|---|---|
| layers | 24 | 43.8% / 62.7% | 95.1% / 54.7% | 0.07 / 0.17 | 0.09 / 0.94 | 0.00 / 0.00 | +0.2 [-0.3, +0.3]・-1.1・10/24 | 0.00 / 0.12 | 0.89 | 1.04 |
| open | 24 | 56.9% / 66.9% | 72.2% / 47.4% | 0.26 / 0.36 | 0.36 / 1.17 | 0.08 / 0.00 | +0.0 [-0.2, +1.2]・-3.8・11/24 | 0.92 / 0.25 | 0.92 | 1.62 |
| enigma | 24 | 52.1% / 70.0% | 65.3% / 37.3% | 0.36 / 0.54 | 0.44 / 1.23 | 0.29 / 0.04 | -0.2 [-0.6, +1.2]・-1.8・13/24 | 0.83 / 0.58 | — | 0.00 |

窓の対の差（open − layers）: own_in +13.2pt [t +0.9, +25.5]（p 0.028）・own_out +4.2pt [−5.0, +13.4]・**opp_in −22.9pt** [−37.3, −8.5]（p 0.0024）・opp_out −7.3pt [−19.6, +5.1]・lead_at_w +0.60 目 [−0.49, +1.69]。

勝ちでない局（すべて持碁・double_pass）: layers 3（seed 1017 W・1022 B・1023 W）・open 4（1006 B・1010 B・1022 B・1023 W）・enigma 6（1000 B・1005 W・1006 B・1012 B・1016 B・1018 B）。負けは 0。

読み方:
- **ユーザーの仮説どおりの形は layers に出る**: layers は窓の中で相手が最善手を打ち続け（相手の一致率 95.1%・出口の手数の中央値 24＝13/24 局で上限まで定跡）、W 手目のリードは +0.2 目（互角）。
  open は窓の中の難解＋の手で定跡を外し（出口の手数の中央値 4）、窓の中の相手の一致率は 72.2%（−22.9pt）
- ただし自分の一致率は open のほうが高い（64.4% vs 58.2%）。定跡の相手には layers の窓の中の一致率が低い（43.8%＝窓の中の 144 手番のうち同値外し free 81・最善手 63。互角のまま進むので同値外しが多い）
- 持碁が全アームで出る（互角のまま終わる局が多い＝最終リードの中央値 +4.9〜+8.2 目）。勝ち以外は layers 3・open 4・enigma 6（open は enigma 以下）

## 9-4 強い相手

相手 HumanStyle 9段・コミ互角・20 対。数値は `veil9-p4strong-summary-vs-layers.*`・`veil9-p4strong-summary.*`・`veil9-p4strong-window_stats.json`。

| アーム | 勝-負-持碁 [勝ちの Wilson 95%] | 自分の一致率 局平均 [95%] | 相手の一致率 局平均 | 自分 / 相手の損失（目/手） | ≥6目/局 | flip/局 | 最終リードの中央値 | 手数の中央値 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） |
|---|---|---|---|---|---|---|---|---|---|---|
| layers | 18-0-2 [69.9, 97.2] | 58.8% [53.7, 64.1] | 57.0% | 0.19 / 0.38 | 0.05 | 0.10 | +3.8 | 50.5 | 29.9%（205） | 0.38 |
| open | 14-3-3 [48.1, 85.5] | 66.7% [61.6, 71.8] | 55.2% | 0.22 / 0.29 | 0.05 | 0.90 | +2.0 | 57 | 19.9%（188） | 0.47 |
| enigma | 13-4-3 [43.3, 81.9] | 73.0% [69.2, 77.1] | 51.4% | 0.30 / 0.42 | 0.05 | 1.45 | +2.3 | 51 | 6.8%（150） | 1.13 |

| アーム | 局 | 自分 窓の中 / 後 | 相手 窓の中 / 後 | 自分の損失 窓の中 / 後（目/手） | 相手の損失 窓の中 / 後 | 窓の中の ≥2目 / ≥6目（/局） | W 手目のリード 中央値 [IQR]・最小・負の局 | flip 窓の中 / 後（/局） | 窓の後の u の平均 | 窓の後の paid/局 |
|---|---|---|---|---|---|---|---|---|---|---|
| layers | 20 | 58.3% / 58.2% | 55.0% / 58.3% | 0.07 / 0.24 | 0.19 / 0.45 | 0.00 / 0.00 | +0.8 [+0.1, +1.6]・-1.8・5/20 | 0.00 / 0.10 | 0.92 | 1.55 |
| open | 20 | 53.3% / 70.0% | 55.8% / 54.6% | 0.23 / 0.22 | 0.13 / 0.33 | 0.05 / 0.00 | -0.7 [-1.5, -0.3]・-3.7・17/20 | 0.75 / 0.15 | 0.97 | 0.20 |
| enigma | 20 | 55.8% / 78.4% | 59.2% / 49.3% | 0.22 / 0.30 | 0.12 / 0.46 | 0.00 / 0.00 | -0.9 [-1.2, -0.3]・-2.8・18/20 | 0.75 / 0.70 | — | 0.00 |

- 対の差（open − layers）: own_top1 +7.9pt [t −2.4, +18.1]・flip +0.80 [+0.25, +1.35]・win −0.20 [−0.48, +0.08]・≥6目 0。窓: own_in −5.0pt [−19.4, +9.4]・own_out +11.8pt [−0.3, +23.9]（p 0.035）・
  opp_in +0.8pt・opp_out −3.8pt・**lead_at_w −1.85 目** [−2.72, −0.98]（p 0.0002）
- 対の差（layers − enigma）: own_top1 −14.2pt [−23.9, −4.4]（p 0.0023）・flip −1.35 [−2.20, −0.50]・win +0.25 [−0.05, +0.55]
- 窓の中の大きな損: ≥2目の手は open 0.05/局（1 手）・layers と enigma 0、≥6目の手はどのアームも 0。窓の手の中身（open・20 局）: 任せた手番 120・kind opening 56・レポートの損失の合計 28.1 目
- W 手目のリードの分布: layers は中央値 +0.8 目・負の局 5/20、open は −0.7 目・17/20、enigma は −0.9 目・18/20（コミ互角の HumanStyle 9段には窓の中の難解＋の外しがそのまま不利になる）
- 勝ちでない局（すべて double_pass）:
  - layers 2: 持碁 seed 1002（B）・1016（B）
  - open 6: 負け 1005（W・−2.1 目）・1018（B・−40.5 目）・1019（W・−5.8 目）、持碁 1006（B）・1007（W）・1016（B）。**負けの 3 局はどれも窓の中の難解＋の外し
    （1 手 0.6〜1.2 目・例 1005 の 4 手目 1.2 目で +0.4 → −0.8 目）でリードが負になり、その後一度も前に出ていない**（games.jsonl の `lead_max` は +0.2〜+0.4 目＝どれも窓の中）。
    同じ seed の layers は 3 局とも勝ち（`lead_max` +5.3〜+16.4 目）
  - enigma 7: 負け 1003（W・−2.1）・1009（W・−1.9）・1012（B・−1.9）・1016（B・−13.7）、持碁 1001（W）・1006（B）・1007（W）
- 勝ち以外の数は open 6 ≤ enigma 7（layers 2）

## 9-5 接戦ストレス

相手 HumanStyle 9段・`--komi-shift 2`（AI に 2 目不利＝AI が黒ならコミ 9・白なら 5）・20 対。窓の中の難解＋は勝率フロアでほぼ最善手を打つ＝窓の後の安全を見る段（spec §16.3）。
数値は `veil9-p5stress-summary-vs-layers.*`・`veil9-p5stress-summary.*`・`veil9-p5stress-window_stats.json`。

| アーム | 勝-負-持碁 [勝ちの Wilson 95%] | 自分の一致率 局平均 [95%] | 相手の一致率 局平均 | 自分 / 相手の損失（目/手） | ≥6目/局 | flip/局 | 最終リードの中央値 | 手数の中央値 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） |
|---|---|---|---|---|---|---|---|---|---|---|
| layers | 16-0-4 [58.4, 91.9] | 66.6% [62.7, 70.5] | 56.1% | 0.13 / 0.33 | 0.00 | 0.00 | +2.0 | 56.5 | 25.9%（201） | 0.35 |
| open | 16-4-0 [58.4, 91.9] | 80.6% [76.4, 85.0] | 55.5% | 0.21 / 0.40 | 0.05 | 0.15 | +2.6 | 56.5 | 28.2%（116） | 0.24 |
| enigma | 11-5-4 [34.2, 74.2] | 92.7% [89.5, 95.7] | 61.2% | 0.33 / 0.51 | 0.20 | 0.50 | +1.9 | 65 | 13.9%（56） | 0.33 |

| アーム | 局 | 自分 窓の中 / 後 | 相手 窓の中 / 後 | 自分の損失 窓の中 / 後（目/手） | 相手の損失 窓の中 / 後 | 窓の中の ≥2目 / ≥6目（/局） | W 手目のリード 中央値 [IQR]・最小・負の局 | flip 窓の中 / 後（/局） | 窓の後の u の平均 | 窓の後の paid/局 |
|---|---|---|---|---|---|---|---|---|---|---|
| layers | 20 | 60.0% / 68.0% | 63.3% / 54.1% | 0.10 / 0.14 | 0.07 / 0.39 | 0.00 / 0.00 | -2.5 [-3.6, -1.6]・-5.0・20/20 | 0.00 / 0.00 | 0.99 | 0.75 |
| open | 20 | 100.0% / 74.7% | 66.7% / 52.2% | 0.21 / 0.21 | 0.08 / 0.46 | 0.05 / 0.00 | -3.5 [-4.6, -2.4]・-5.3・20/20 | 0.00 / 0.15 | 1.00 | 0.60 |
| enigma | 20 | 100.0% / 90.8% | 60.0% / 61.8% | 0.15 / 0.38 | 0.10 / 0.58 | 0.00 / 0.00 | -3.2 [-4.1, -2.4]・-5.1・19/20 | 0.00 / 0.50 | — | 0.00 |

- **勝-負-持碁**: layers 16-0-4・open 16-4-0・enigma 11-5-4。勝ち以外は layers 4・open 4・enigma 9
- flip/局: layers 0.00・open 0.15（すべて窓の後）・enigma 0.50。対の差（open − layers）: own_top1 +14.0pt [t +5.8, +22.2]（p 0.0007）・flip +0.15 [−0.05, +0.35]・win 0 [−0.35, +0.35]。
  窓: own_in +40.0pt（open の窓の手はすべて最善手＝kind opening 0/120）・own_out +6.7pt [−2.7, +16.1]・lead_at_w −0.79 目 [−1.69, +0.12]
- 勝ちでない局（すべて double_pass）:
  - layers 4: 持碁 seed 1005（W）・1013（W）・1018（B）・1019（W）
  - open 4: 負け 1004（B・−22.1 目）・1008（B・−1.8）・1016（B・−5.9）・1017（W・−23.7）。4 局とも一度も前に出ていない（games.jsonl の `lead_max` −1.6〜−2.1 目）。
    同じ seed の layers は 4 局とも勝ち（`lead_max` +5.1〜+10.7 目）
  - enigma 9: 負け 1009（W）・1010（B）・1016（B）・1017（W）・1018（B）、持碁 1000（B）・1011（W）・1013（W）・1015（W）
- 読み方: AI が不利な局面では窓の中の難解＋は最善手だけを打つ（open・enigma とも窓の中の自分の一致率 100%）。それでも open は layers と違う局になり、
  負けが 4 局出た（layers は持碁 4）。勝ち以外の数は layers と同じ 4 で、enigma の 9 より少ない

## 実戦（spec §16.5）

ユーザーが打った一致率ひかえめ9路の実戦 8 局（2026-09-26 00:16〜01:02 に始めた監視対局。今の設定＝spec §6.1 の 9路の列・層も研究外しも OFF＝`recon_9_veil/summary.json` の `settings`）と、
難解＋9路の実戦 16 局（`recon_9/`）を、事後 2500v の解析で比べた（`window_stats.py --recon recon_9_veil recon_9`・W 12・`experiments/selfplay/recon9-veil-vs-enigma-window.txt` と
`veil9-campaign/veil9-recon-window_stats.json`）。「こちらが定跡どおりに打つと高段の BOT が最善手を続けるか」を見る材料（C10 の実戦の比較と同じ手順を、実戦の局がすでにあるので先に行った）。

一致率ひかえめ9路（8 局）:

| 局 | AI | 手数 | 最終リード（AI 視点） | 自分 窓の中 / 後 | 相手 窓の中 / 後 | 相手が初手から最善手を続けた手数 | 自分 / 相手 全手 |
|---|---|---|---|---|---|---|---|
| `20260926_001643` | W | 32 | +23.2 | 83.3% / 70.0% | 66.7% / 10.0% | 0 | 75.0% / 31.2% |
| `20260926_001912` | B | 33 | +20.1 | 83.3% / 54.5% | 50.0% / 40.0% | 0 | 64.7% / 43.8% |
| `20260926_002128` | W | 46 | +5.6 | 66.7% / 88.2% | 33.3% / 35.3% | 0 | 82.6% / 34.8% |
| `20260926_002344` | B | 21 | +16.0 | 33.3% / 80.0% | 66.7% / 0.0% | 1 | 54.5% / 40.0% |
| `20260926_005258` | B | 47 | +35.7 | 50.0% / 66.7% | 16.7% / 5.9% | 1 | 62.5% / 8.7% |
| `20260926_005657` | W | 48 | +37.6 | 66.7% / 50.0% | 33.3% / 33.3% | 0 | 54.2% / 33.3% |
| `20260926_010014` | B | 35 | +20.0 | 66.7% / 75.0% | 16.7% / 36.4% | 1 | 72.2% / 29.4% |
| `20260926_010213` | W | 40 | +39.9 | 66.7% / 64.3% | 33.3% / 21.4% | 1 | 65.0% / 25.0% |
| **8 局の平均** | | 中央値 37.5 | 8-0-0 | **64.6% / 68.6%** | **39.6% / 22.8%** | 中央値 0.5（平均 0.50・最大 1） | 66.3% / 30.8% |

難解＋9路（16 局）:

| 局 | AI | 手数 | 最終リード（AI 視点） | 自分 窓の中 / 後 | 相手 窓の中 / 後 | 相手が初手から最善手を続けた手数 | 自分 / 相手 全手 |
|---|---|---|---|---|---|---|---|
| `20260919_095719` | B | 33 | +73.3 | 50.0% / 36.4% | 33.3% / 0.0% | 0 | 41.2% / 12.5% |
| `20260919_095858` | W | 34 | +34.7 | 0.0% / 81.8% | 0.0% / 18.2% | 0 | 52.9% / 11.8% |
| `20260919_100100` | B | 53 | +58.0 | 33.3% / 85.7% | 16.7% / 25.0% | 0 | 74.1% / 23.1% |
| `20260919_100745` | W | 54 | +33.1 | 0.0% / 52.4% | 0.0% / 9.5% | 0 | 40.7% / 7.4% |
| `20260919_184750` | B | 47 | +9.8 | 83.3% / 55.6% | 50.0% / 41.2% | 1 | 62.5% / 43.5% |
| `20260919_213546` | W | 28 | +20.3 | 16.7% / 87.5% | 16.7% / 37.5% | 0 | 57.1% / 28.6% |
| `20260919_213928` | B | 53 | **−2.0（負け）** | 66.7% / 52.4% | 50.0% / 75.0% | 1 | 55.6% / 69.2% |
| `20260919_214631` | B | 39 | +30.9 | 66.7% / 71.4% | 50.0% / 53.8% | 1 | 70.0% / 52.6% |
| `20260919_215145` | W | 100 | +54.5 | 16.7% / 72.7% | 33.3% / 25.0% | 0 | 66.0% / 26.0% |
| `20260919_222543` | B | 33 | +14.9 | 16.7% / 45.5% | 0.0% / 20.0% | 0 | 35.3% / 12.5% |
| `20260919_223015` | B | 29 | +13.5 | 66.7% / 66.7% | 50.0% / 25.0% | 1 | 66.7% / 35.7% |
| `20260919_223517` | W | 50 | **0.0（持碁）** | 66.7% / 73.7% | 16.7% / 63.2% | 0 | 72.0% / 52.0% |
| `20260921_171019` | B | 83 | +9.5 | 33.3% / 80.6% | 16.7% / 40.0% | 0 | 73.8% / 36.6% |
| `20260922_201408` | B | 37 | +29.0 | 50.0% / 76.9% | 33.3% / 25.0% | 0 | 68.4% / 27.8% |
| `20260922_201809` | W | 62 | +5.7 | 50.0% / 72.0% | 16.7% / 36.0% | 1 | 67.7% / 32.3% |
| `20260922_202223` | B | 49 | +2.2 | 50.0% / 73.7% | 16.7% / 22.2% | 0 | 68.0% / 20.8% |
| **16 局の平均** | | 中央値 48 | 14-1-1 | **41.7% / 67.8%** | **25.0% / 32.3%** | 中央値 0（平均 0.31・最大 1） | 60.8% / 30.8% |

（「全手」は `report_all.json` の局ごとの mine / opp の一致率とその局平均。窓の中・後と streak は `window_stats.py --recon` の出力。平均の行の streak は中央値＝ツールの出力のまま）

読み方:
- 一致率ひかえめ9路（今の設定＝互角の序盤はほぼ最善手）の窓の中（12 手まで）では、相手の一致率が 39.6%（難解＋の局 25.0%）と高い。窓の中の自分の一致率も 64.6%（41.7%）
- ただし窓の後の相手の一致率は 22.8%（難解＋の局 32.3%）と低く、相手が初手から最善手を続けた手数は最大 1 手（どちらも）。局全体の相手の一致率は 30.8% どうし。
  「こちらが定跡どおりに打つと相手が終局近くまで最善手を続ける」形は、この 8 局では見えない（8 局・今の相手たちの範囲）
- 結果は一致率ひかえめ9路 8-0-0（最終リード +5.6〜+39.9 目・手数の中央値 37.5）、難解＋9路 14-1-1（負け `213928` −2.0 目・持碁 `223517`）
- **注意**: 一致率と streak は完全一致でしか数えないので、序盤（1〜3 手目）の対称で同格な初手（§16.1 の 4-4 / 4-5 / 天元 / 3-5・0.12目以内）を打った手は不一致に数える
  （過小評価の方向。特に streak は相手の初手が不一致に数えられると 0 になる）。窓の中の相手の手は 1局 6 手なので、1 手の違いで 16.7pt 動く

## 見るものと決め方（spec §16.5）

spec §16.5 の目安（局全体の自分の一致率の対の差 `open` − `layers` の 97.5% 区間が 0 をまたがずに下がり、9-3・9-4 で `open` の勝ち以外の数が同じ相手の `enigma` 以下なら、
研究外しを採る候補にする。持碁も勝ち以外に数える）に照らすと、**9路は1つ目を満たさない**: 48 対の差は +2.7pt [t −2.5, +7.9]（0 をまたぎ、向きも上がる方向）。
窓の中では −13.2pt 下がるが、W 手目のリードが 1.5 目小さくなる分、窓の後は lead < reserve の手番が増えて最善手が増え（+8.1pt）、打ち消し以上になる（投了なしの 10 対では
逆に −11.2pt だが、実戦は 48 手前後で投了されるので投了ありを基準にする）。2つ目（安全）は満たす: 勝ち以外は 9-3 で open 4（持碁 4）≤ enigma 6、9-4 で open 6（負け 3・持碁 3）≤
enigma 7（負け 4・持碁 3）。ただし layers はそれぞれ 3・2 で、9-4 の open の負け 3 局はどれも窓の中の外しでリードを失った局。9-5 の勝ち以外は layers・open とも 4（enigma 9）。
→ 9路では研究外しは目安の上で採る候補にならない。9路の既定では loose9 が spec と差がなく（+1.1pt）、下げたのは forced を含む層（spec − layers +9.8pt）。
13路（`veil13-campaign.md` の節）は 13-1 の差 `local_open` − `local` が −5.0pt [t −9.8, −0.3] で 0 をまたがずに下がり、13-2・13-3 の勝ち以外は local_open 0 で enigma（0・5）以下＝目安を満たす
（ただし 13-3 の強い相手では +3.2pt・13-4 の接戦ストレスでは −0.4pt で下がらない）。どれを採るかは C10 でユーザーが決める。

## ユーザーの決定（2026-09-26）

- **9路のローカル設定を layers にする**（`ai:veil9`: loose9 の 7 キー＝free_loss 0.3・spend_rate 1.0・max_loss 4.0・yose_max_loss 1.5・
  dominant_hp 1.01・dominant_max_loss 2.0・natural_ratio 0.1、失着の層 ON〈blunder_mode 2〉・forced の層 ON〈forced_mode 2〉、研究外し OFF〈open_moves 0〉。
  安全条件 reserve 3.0・min_winrate 0.85 と層のほかのキーは 9路の既定のまま）。コードの既定値は変えない。
- **9路の研究外しは OFF のまま**（局全体の一致率が下がらず、強い相手で負けが増えたため）。
- ブランチ `veil-opening` を master にマージする（層の既定は OFF）。
- 次は実戦で確かめる（各 10 局以上・ログの `Rate:` / `Decision:`・実戦の直後にログを `experiments/selfplay/realgames-9x9-logs/` に退避）。

## 実戦（layers・2026-09-26 夕方）

ユーザーが打った一致率ひかえめ9路の実戦 9 局（2026-09-26 17:03〜18:03 に始めた監視対局・9 局ともローカル設定の layers＝上の「ユーザーの決定」の値・研究外し OFF。
ログの `veil9_*` で確かめた）。`recon_logs.py --size 9 --strategy Veil9Strategy`（9 局を名前で指定・置き石の初手 2 局を直した・`experiments/selfplay/recon9veil-layers.console.txt`）→
`recon_9_veil_layers/`、`offline_report.py --dir recon_9_veil_layers --config experiments/selfplay/veil-open-config.json`（2500v・1局 17〜34 秒・`TIMEOUT` なし・
`offline9veil-layers.console.txt`）、`window_stats.py --recon recon_9_veil_layers recon_9_veil recon_9`（`experiments/selfplay/recon9-layers-vs-veil-vs-enigma-window.txt`・
`veil9-campaign/veil9-recon-layers-window_stats.json`）。手番の種類（ログの `Decision:` の kind）と事後の一致の突き合わせは `veil9-campaign/veil9-recon-layers-kinds.txt`。

| 局 | AI | 手数 | 最終リード（AI 視点） | 自分 窓の中 / 後 | 相手 窓の中 / 後 | 相手が初手から最善手を続けた手数 | 自分 / 相手 全手 |
|---|---|---|---|---|---|---|---|
| `20260926_170341` | B | 51 | +25.2 | 33.3% / 80.0% | 33.3% / 68.4% | 0 | 69.2% / 60.0% |
| `20260926_170944` | W | 52 | +25.9 | 50.0% / 60.0% | 50.0% / 65.0% | 1 | 57.7% / 61.5% |
| `20260926_171529` | B | 45 | +15.5 | 33.3% / 88.2% | 83.3% / 31.2% | 5 | 73.9% / 45.5% |
| `20260926_172435` | W | 74 | +59.0 | 83.3% / 64.5% | 50.0% / 29.0% | 0 | 67.6% / 32.4% |
| `20260926_173801` | B | 37 | +12.1 | 50.0% / 84.6% | 100.0% / 16.7% | 6 | 73.7% / 44.4% |
| `20260926_174630` | B | 73 | +41.8 | 83.3% / 61.3% | 50.0% / 13.3% | 0 | 64.9% / 19.4% |
| `20260926_175530` | W | 50 | +39.7 | 83.3% / 73.7% | 66.7% / 47.4% | 0 | 76.0% / 52.0% |
| `20260926_175844` | W | 84 | +7.4 | 33.3% / 75.0% | 16.7% / 50.0% | 0 | 69.0% / 45.2% |
| `20260926_180330` | B | 29 | +22.4 | 50.0% / 66.7% | 33.3% / 0.0% | 0 | 60.0% / 14.3% |
| **9 局の平均** | | 中央値 51 | 9-0-0 | **55.6% / 72.7%** | **53.7% / 35.7%** | 中央値 0（平均 1.33・最大 6） | **68.0% / 41.6%** |

前の設定（spec §6.1 の 9路の列・上の「実戦」の 8 局）との比較（事後 2500v）:

| | layers 9 局 | 前の設定 8 局 | 難解＋9路 16 局 |
|---|---|---|---|
| 自分の一致率（局平均 / 手の合計） | 68.0% / 170/250 = 68.0% | 66.3% / 102/153 = 66.7% | 60.8% / 248/397 = 62.5% |
| 自分の損失（目/手・局平均） | 0.27 | 0.16 | 0.76 |
| 相手の一致率（局平均） | 41.6% | 30.8% | 30.8% |
| 手数の中央値 | 51 | 37.5 | 48 |
| 自分の手番のうちヨセ（`in_yose`） | 105/250 = 42% | 30/153 = 20% | − |
| 対局中の `Rate:`（最後の行の mine） | 150/241 = 62.2% | 99/145 = 68.3% | − |

- 局平均の差 layers − 前の設定は +1.7pt（Welch の 95% 区間 [−7.2, +10.5]・9 局と 8 局）。ハーネスの予想（9-1 の spec − layers +9.8pt＝layers で約 10pt 下がる）は
  この区間の外で、**実戦では layers で自分の一致率が下がらなかった**（局数が少ないので「下がっても数 pt」までしか言えない）
- 手番の種類と事後の一致（`veil9-recon-layers-kinds.txt`）:

  | kind | layers: 手番 / 事後に一致 | 前の設定: 手番 / 事後に一致 |
  |---|---|---|
  | best | 155 / 152（98.1%） | 102 / 98（96.1%） |
  | free | 36 / 9（25.0%） | 22 / 2（9.1%） |
  | paid | 24 / 1（4.2%） | 21 / 0 |
  | decided | 18 / 7（38.9%） | 8 / 2（25.0%） |
  | forced | 16 / 0 | − |
  | swap | 1 / 1 | − |

  外した手番は layers 95 / 250（38%）・前の設定 51 / 153（33%）で layers の方が多い。ただし layers の外しの 18 手（free 9・decided 7・paid 1・swap 1）は
  事後 2500v では最善手だった（対局中の解析とは別の探索で、0.3 目以内の同格の手の順位が入れ替わる）。対局中の `Rate:` の 62.2% と事後の 68.0% の差はほぼこれ。
  free_loss を 0.2→0.3 に広げた分、事後に最善手と数えられる「外し」が増えた（free の事後一致 9.1%→25.0%）
- forced の層は 16 手（1.8 回/局・ハーネス 9-1＋9-2 の layers 2.0 回/局）で、事後もすべて不一致（損失の平均 1.17 目）。層のうち効いているのはこれ
- 失着の層は 9 局で 0 手（ハーネスでも 48 局で 1 手）。関門で止まった手番は root 勝率 < 0.95 が 103・ヨセ 104・lead < reserve＋5＋cap（12 目）が 28。
  関門を通った 14 手番は候補なし 13・却下 1（ほかに判定まで行かなかった手番が 1＝terminal）。9路では勝率 0.95 以上でヨセ前の手番がほとんど無い
- 相手が前の 8 局より強い（相手の一致率 41.6%・窓の中 53.7%）。`171529` と `173801` では相手が初手から 5 手・6 手続けて最善手を打った
  （自分の窓の中は 33.3%・50.0%＝こちらが定跡どおりに打ったからではない）。局が長く（中央値 51 手）、ヨセの手番（事後一致 71.4%）が多い
- ハーネスの一致率（`selfplay_move_rows`）は、対局中に AI が判断に使ったのと同じ解析の `candidate_moves[0]` と比べるので、0.3 目以内の外しは必ず不一致に数える。
  実戦の事後解析は別の探索なので、その一部が一致に数えられる。ハーネスの layers の下げ幅（free 186・decided 119 手番を含む）は、この分だけ大きく出ている可能性がある
- 結果は 9-0-0（最終リード +7.4〜+59.0 目）
