# 韜晦（13路）自己対局キャンペーン結果（2026-09-24）

計画 `docs/superpowers/plans/2026-09-23-veil-strategy.md` の Task 15・spec `2026-09-23-veil-strategy-design.md` §10。
**段階1（主比較）・1b（つまみの掃引）・2（投了なし）・3（接戦ストレス）・3b（接戦ストレスの追加）を実行した**。2026-09-24 にユーザーが段階1の結果を見て
測定をいったん打ち切り、仕上げの段階でユーザーの指示により段階3を1回実行した（同日）。同日夜にユーザーの指示（「未対応の校正作業を続けて」）で
段階1b・2 を実行し、1b で一致率を下げた2つの設定について段階3b を足した（2026-09-24 18:13〜2026-09-25 00:25）。

数値は `veil13-campaign/` に写した summary（段階1は `veil13-p1-default-vs-<アーム>-summary.{json,txt}`・段階1b は
`veil13-p1b-default-vs-<アーム>-summary.{json,txt}`・段階2 は `veil13-p2-default-vs-enigma-summary.{json,txt}`・段階3は
`veil13-p3-default-vs-enigma-summary.{json,txt}`・段階3b は信頼度 0.95 の `veil13-p3b-<アーム>-vs-enigma-conf95-summary.{json,txt}`）から取った。局平均と 95% 区間は
summary の局単位クラスタ bootstrap の値。`veil.*`（韜晦の判定情報）は games.jsonl の局ごとの値を合計・局平均にし、
罠の比（次の相手手の実損 / E）は moves.jsonl の罠の手をすべて合わせて出した。

## 実行条件

- コード: git HEAD `ac280c2a`（`ac280c2a9a9874c6f69b96381af6ec17e40ccd34`）・dirty false（スモーク・段階1の run.json とも）。
  `ai_file` は `katrain/core/ai.py`（リポジトリ相対＝このワークツリーのコード）
- エンジン（run.json の `engine`）: KataGo v1.18.2 CUDA・モデル `b10c384h6nbttflrs.bin.gz`・humanSL `b18c384nbt-humanv0.bin.gz`・
  max_visits 2500・fast_visits 200・max_time 8.0・wide_root_noise 0.04。13路・コミ 7.0・中国ルール。hp 監査 `rank_9d`
- ユーザー設定の `ai:veil13`（`~/.katrain/config.json`。run.json の default アームは `settings_source: user config`・
  fingerprint `337c824cce919a7d`）: spec §6.1 の 13路の既定値と同じ＝target_rate 0.3・reserve 5.0・min_winrate 0.85・
  free_loss 0.3・free_wr_drop 0.03・close_drift_cap 0（上限なし）・spend_rate 0.5・max_loss 4.5・yose_max_loss 1.5・
  dominant_hp 0.8・dominant_max_loss 2.0・min_human_policy 0.05・natural_ratio 0.2・cost_slack 0.3・trap_mode false・
  trap_min_delta_e 0.5
- アーム（段階1）: default=`veil13` / trap=`veil13:veil13_trap_mode=true` / attack=`veil13` ＋「攻め」プリセット
  （reserve 3.0・min_winrate 0.75・max_loss 6.0・spend_rate 1.0・dominant_max_loss 3.0・yose_max_loss 2.0＝**測定専用**）/
  enigma=`enigma13plus`（ユーザー設定のまま）/ human=`human:human_kyu_rank=-8,modern_style=true`（HumanStyle 9段）
- 相手プール: `opponent_pool_13.json`（2026-09-24 09:37 作成・`source_run` `experiments/selfplay/20260924_0822_calib13-len`）＝
  humanSL rank_1k / rank_1d / rank_3d・τ 1.0・悪手フィルタなし・投了モデル length（実戦 18局の手数 L 以降に AI が明らかに勝っていれば投了）
- 局の割り付け: seed 1000〜1019（全アームが同じ seed を打つ＝対の比較）。AI の色は黒白交互（10 / 10）、段位は rank_1k 8局・
  rank_1d 6局・rank_3d 6局（20 は 6 の倍数でないのでハーネスが不均衡の警告を出す。対の差は seed で揃うので偏らない＝`--pairs 20` を維持）

| 段階 | ラベル・出力ディレクトリ | 局数 | 所要 |
|---|---|---|---|
| スモーク | `veil13-smoke`（`experiments/selfplay/20260924_0949_veil13-smoke`） | 2（default・enigma × 1 seed） | 09:49〜09:51（約2分。計画の見込み約10分） |
| 段階1 | `veil13-p1`（`experiments/selfplay/20260924_0951_veil13-p1`） | 100（5 アーム × 20 seed）・aborted 0 | 09:51〜11:34（約1時間43分。見込み約4時間）。対局時間の合計は default 17.6分・trap 18.9分・attack 18.4分・enigma 27.9分・human 19.1分 |
| 段階1b | `veil13-p1b`（`experiments/selfplay/20260924_1813_veil13-p1b`） | 180（9 アーム × 20 seed）・aborted 0 | 18:13〜20:58（約2時間45分・ユーザーの指示で実行）。対局時間の合計は default 22.0分・user 19.9分・dom090 17.1分・domoff 16.7分・nat010 17.5分・free040 16.7分・drift1 16.7分・wide 18.1分・loose 18.8分 |
| 段階2 | `veil13-p2`（`experiments/selfplay/20260924_2059_veil13-p2`） | 40（2 アーム × 20 seed）・aborted 0 | 20:59〜22:55（約1時間56分）。対局時間の合計は default 47.7分・enigma 66.7分 |
| 段階3 | `veil13-p3`（`experiments/selfplay/20260924_1325_veil13-p3`） | 40（2 アーム × 20 seed）・aborted 0 | 13:25〜14:45（約1時間20分・仕上げの段階でユーザーの指示により実行）。対局時間の合計は default 33.0分・enigma 46.9分。実行条件は「段階3 接戦ストレス」 |
| 段階3b | `veil13-p3b`（`experiments/selfplay/20260924_2255_veil13-p3b`） | 60（3 アーム × 20 seed）・aborted 0 | 22:55〜翌 00:25（約1時間30分）。対局時間の合計は loose 25.4分・user 27.3分・enigma 36.7分。実行条件は「段階3b 接戦ストレス」 |

- Step 1 のフラグの読み替え: なし（計画のフラグ `--arm` `--size` `--pairs` `--opp-pool` `--hp-audit` `--label` `--no-resign`
  `--komi-shift` `--opponent` `--resume` はハーネスに同じ名前であった。ハーネスには他に `--resign-model`（既定の length を使った）・
  `--allow-mixed` などがある）
- 健全性: スモーク・段階1とも全アームで fallbacks 0・humansl_errors 0・hp_audit_errors 0・shadow_errors 0・aborted 0・visits_low 0。
  ledger_mismatch（外したつもりの手がレポートで一致になった数）はスモーク 0・段階1の韜晦のアーム（default・trap・attack）の合計 0
- スモーク: default（veil13）win（opp_resign・80手）own 45.0% / opp 20.0%・最終リード +87.5・flip 0・外した手の 9段 hp 中央値 26.9%
  （enigma 1.6%）。veil の tiers i 16 / ii 3 / iii 21・kinds free 6 / paid 12 / decided 4 / best 18・paid_vloss_sum 20.5。enigma の `veil` は null
- **ハーネスと実戦のずれ**（AI 側）: 段階1の enigma アームの自分の一致率 局平均 49.7% [45.9, 53.5] − 実戦の難解＋ 53.3% = **−3.6pt**
  （区間では −7.4〜+0.2pt）。相手プールの校正（`selfplay-calibration-results-20260924-length.md`・length の投了モデル）では −0.8pt。
  実戦の予測はこの差を引いて読む（実戦の一致率 ≈ ハーネスの値 + 0.8〜3.6pt）
- ハーネスの注意（相手の終盤）: プールの相手の終盤（85手以降）の一致率は校正で 13.4%（実戦 29.1%）。段階1でも相手の終盤は
  default 17.9%・enigma 18.8%・trap 14.3%・attack 30.2%・human 22.5%（手をまとめた値。終盤は相手の手の 1〜2 割）。
  終盤・ヨセの判断を読む比較では相手の忠実度の限界として読む

## 段階1 主比較

区間: 一致率の [95%] は局単位クラスタ bootstrap、勝ちは Wilson 95%。**default との差の区間の信頼度は `compare[0].conf` = 0.975**
（ハーネスの2回見る停止規則用。各比較の `veil13-p1-default-vs-<アーム>-summary.json`）。差はすべて default − アーム。

| アーム | 自分の一致率 WATCH 局平均 [95%] | 相手の一致率 局平均 [95%] | P(own <= 0.35) | P(own < 0.15) | 勝ち/局数 [Wilson 95%] | flip_moves/局 | 自分の mean_ptloss（目/手） | ≥6目の失着/局 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） | default との差（default − アーム・対の差の平均 [t 区間 / bootstrap 区間]・信頼度 0.975） |
|---|---|---|---|---|---|---|---|---|---|---|---|
| default（veil13 既定） | 53.1% [49.6, 56.5] | 26.3% [22.7, 30.1] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 0.05 | 0.24 | 0.00 | 27.8%（406） | 0.37 | — |
| trap（罠 ON） | 50.8% [47.2, 54.5] | 24.4% [19.9, 29.1] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 0.10 | 0.24 | 0.00 | 24.9%（412） | 0.65 | 自分の一致率 +2.3pt [-2.4, +6.9 / -1.7, +6.4]（判定 extend）・flip -0.05 [-0.26, +0.16 / -0.25, +0.15]・損失 +0.00 [-0.09, +0.10 / -0.08, +0.09] |
| attack（攻め・測定専用） | 42.2% [39.6, 44.9] | 26.7% [23.0, 30.6] | 15.0% | 0.0% | 20/20 [83.9, 100.0] | 0.05 | 0.33 | 0.00 | 28.5%（497） | 0.47 | 自分の一致率 +10.9pt [+5.5, +16.3 / +6.0, +15.5]（判定 higher）・flip +0.00 [-0.18, +0.18 / -0.15, +0.15]・損失 -0.09 [-0.21, +0.02 / -0.19, +0.01] |
| enigma（難解＋13路・基準） | 49.7% [45.9, 53.5] | 21.7% [17.6, 25.7] | 10.0% | 0.0% | 20/20 [83.9, 100.0] | 2.75 | 1.26 | 2.80 | 3.6%（436） | 2.18 | 自分の一致率 +3.3pt [-3.2, +9.8 / -2.5, +9.0]（判定 extend）・flip -2.70 [-3.57, -1.83 / -3.50, -1.95]・損失 -1.02 [-1.35, -0.69 / -1.32, -0.72] |
| human（HumanStyle 9段・参照） | 53.2% [49.8, 56.5] | 32.1% [27.7, 36.2] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 1.00 | 0.38 | 0.10 | 28.3%（392） | 0.55 | 自分の一致率 -0.2pt [-6.3, +5.9 / -5.5, +5.2]（判定 extend）・flip -0.95 [-1.75, -0.15 / -1.75, -0.30]・損失 -0.14 [-0.28, -0.01 / -0.27, -0.03] |

判定（±3pt）の `extend` は「20 seed では差が ±3pt の内か外か決まらない」。40 seed への自動延長はしない（Task 16 でユーザーに提示済み）。

対の差の全指標（default − アーム・信頼度 0.975）:

| 対の差 | 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p | 判定（±3pt） |
|---|---|---|---|---|---|---|
| default − trap | own_top1 | +2.3pt | -2.4 〜 +6.9 | -1.7 〜 +6.4 | 0.2364 | extend |
| default − trap | opp_top1 | +1.9pt | -4.6 〜 +8.5 | -4.0 〜 +7.8 | 0.6215 | extend |
| default − trap | own_minus_opp | +0.3pt | -8.6 〜 +9.2 | -7.3 〜 +8.7 | 1.0000 | extend |
| default − trap | flip_moves | -0.05 | -0.26 〜 +0.16 | -0.25 〜 +0.15 | 0.5637 | - |
| default − trap | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − trap | own_mean_ptloss | +0.00 | -0.09 〜 +0.10 | -0.08 〜 +0.09 | 0.9563 | - |
| default − trap | ge6 | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − attack | own_top1 | +10.9pt | +5.5 〜 +16.3 | +6.0 〜 +15.5 | 0.0009 | higher |
| default − attack | opp_top1 | -0.4pt | -7.1 〜 +6.3 | -6.0 〜 +5.8 | 0.6873 | extend |
| default − attack | own_minus_opp | +11.3pt | +2.3 〜 +20.2 | +2.7 〜 +18.7 | 0.0056 | extend |
| default − attack | flip_moves | +0.00 | -0.18 〜 +0.18 | -0.15 〜 +0.15 | 1.0000 | - |
| default − attack | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − attack | own_mean_ptloss | -0.09 | -0.21 〜 +0.02 | -0.19 〜 +0.01 | 0.1140 | - |
| default − attack | ge6 | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − enigma | own_top1 | +3.3pt | -3.2 〜 +9.8 | -2.5 〜 +9.0 | 0.2645 | extend |
| default − enigma | opp_top1 | +4.6pt | -1.5 〜 +10.8 | -1.0 〜 +10.2 | 0.0934 | extend |
| default − enigma | own_minus_opp | -1.3pt | -10.3 〜 +7.7 | -9.4 〜 +6.7 | 0.6226 | extend |
| default − enigma | flip_moves | -2.70 | -3.57 〜 -1.83 | -3.50 〜 -1.95 | 0.0002 | - |
| default − enigma | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − enigma | own_mean_ptloss | -1.02 | -1.35 〜 -0.69 | -1.32 〜 -0.72 | 0.0000 | - |
| default − enigma | ge6 | -2.80 | -4.10 〜 -1.50 | -4.05 〜 -1.70 | 0.0003 | - |
| default − human | own_top1 | -0.2pt | -6.3 〜 +5.9 | -5.5 〜 +5.2 | 0.9039 | extend |
| default − human | opp_top1 | -5.8pt | -12.8 〜 +1.3 | -11.9 〜 +0.7 | 0.0683 | extend |
| default − human | own_minus_opp | +5.6pt | -3.4 〜 +14.5 | -2.7 〜 +13.4 | 0.0973 | extend |
| default − human | flip_moves | -0.95 | -1.75 〜 -0.15 | -1.75 〜 -0.30 | 0.0101 | - |
| default − human | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − human | own_mean_ptloss | -0.14 | -0.28 〜 -0.01 | -0.27 〜 -0.03 | 0.0136 | - |
| default − human | ge6 | -0.10 | -0.27 〜 +0.07 | -0.25 〜 +0.00 | 0.1573 | - |

手数・リード・区間別:

| アーム | 手数の中央値 | 最終リードの中央値 [IQR] | 自分の一致率 全手まとめ（序盤 / 中盤 / 終盤＝手数 <24 / 24〜84 / >=85） | 終局の内訳 |
|---|---|---|---|---|
| default | 82.5 | +63.1 [43.5, 91.6] | 52.7%（53.9% / 51.8% / 54.5%） | opp_resign 20 |
| trap | 82 | +36.1 [22.6, 84.8] | 50.7%（54.3% / 49.0% / 51.2%） | double_pass 2・opp_resign 18 |
| attack | 82.5 | +25.6 [13.4, 51.8] | 42.1%（51.3% / 38.0% / 42.6%） | opp_resign 20 |
| enigma | 83 | +13.4 [7.2, 41.8] | 50.3%（43.5% / 49.6% / 68.9%） | double_pass 1・opp_resign 19 |
| human | 82.5 | +32.0 [16.4, 51.7] | 53.3%（49.1% / 53.7% / 62.7%） | double_pass 2・opp_resign 18 |

韜晦のアームの判定情報（`veil.*`・20局の合計。括弧は局平均）:

| アーム | tiers（i / ii / iii / terminal） | kinds（打った手の種類） | 払った vloss の合計（`paid_vloss_sum`） | 種類別 vloss（`vloss_by_kind`） | 種類別 レポートの損失（`report_loss_by_kind`） | lead < reserve での同値でない外し（`nonfree_below_reserve`） | 接戦中の同値外しの vloss（`close_free_vloss`） | ledger_mismatch |
|---|---|---|---|---|---|---|---|---|
| default | 371 / 27 / 458 / 2 | best 452・paid 189・free 130・decided 86・swap 1 | 276.5 目（13.82/局） | free 7.8・paid 268.7 | decided 4.4・free 11.3・paid 180.1 | 0（lead < 5.0 の外しは free 108 手だけ） | 6.81 目（0.34/局） | 0 |
| trap | 194 / 91 / 540 / 9 | best 422・free 123・paid 99・decided 93・trap 90・pass 5・swap 2 | 260.3 目（13.01/局） | free 6.9・paid 128.4・trap 125.0 | decided 2.5・free 9.8・paid 76.1・trap 94.8・pass 0.1 | 0（lead < 5.0 の外しは free 110 手だけ） | 6.52 目（0.33/局） | 0 |
| attack | 296 / 50 / 508 / 4 | best 361・paid 255・decided 124・free 115・swap 3 | 366.9 目（18.34/局） | free 7.0・paid 359.9 | decided 9.4・free 7.5・paid 251.0 | 0（lead < 3.0 の外しは free 88 手だけ） | 4.82 目（0.24/局） | 0 |

paid の「レポートの損失 − 判定時の vloss」（`curse_by_kind`）は default −88.6・trap −52.2・attack −109.0 目＝判定は辛め（勝者の呪いは出ていない）。
free は default +3.5・trap +2.8・attack +0.5 目（default は 130 手で 1手あたり約 0.03 目）。

## 段階1b つまみの掃引

2026-09-24 夜にユーザーの指示（「未対応の校正作業を続けて」）で実行した（18:13〜20:58・約2時間45分）。数値は `veil13-campaign/veil13-p1b-default-vs-<アーム>-summary.{json,txt}`（`summarize --compare default <アーム>`・既定の信頼度 0.975）と、実行ディレクトリの games.jsonl（`veil.*`）・moves.jsonl（`decision_why`）から取った。

- 実行: `python -m katrain_debug.selfplay run --size 13 --pairs 20 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json --hp-audit rank_9d --label veil13-p1b --arm default=veil13:<16キー> --arm user=veil13:<16キー> …`
  （`experiments/selfplay/20260924_1813_veil13-p1b`・コンソールの写し `experiments/selfplay/veil13-p1b.console.txt`・180局・aborted 0）
- コード: git HEAD `cec2ee95`（`cec2ee9509cc959e31566eeefdeeb3da7f2b52d4`）・dirty false（`veil13-p1b-run.json`）。エンジン・相手プール・hp 監査・投了モデル（length）・seed 1000〜1019・色と段位の割り付けは段階1と同じ
- **全アームで16キーをすべて上書きで渡した**: 同日 17:58 にユーザーが GUI で `~/.katrain/config.json` の `ai:veil13` を reserve 2.0・min_winrate 0.8・spend_rate 0.75・max_loss 6.0・trap_mode true に変えていた（他のキーは spec の既定値のまま）。ハーネスは上書きの無いキーをユーザー設定から取るので、上書きなしの `veil13` では spec の既定値にならない。default の設定の指紋は段階1と同じ `337c824cce919a7d`（spec の既定値を再現できている）
- アーム（spec の既定値からの違いだけを書く）:
  - default: 違いなし（spec §6.1 の 13路の既定値）
  - user: 2026-09-24 17:58 のユーザー設定＝reserve 2.0・min_winrate 0.8・spend_rate 0.75・max_loss 6.0・trap_mode true（**安全条件を緩めている**＝既定の候補ではなく、ユーザーが実戦で使っている設定の参考測定）
  - dom090: dominant_hp 0.9 / domoff: dominant_hp 1.01（OFF）/ nat010: natural_ratio 0.1 / free040: free_loss 0.4 / drift1: close_drift_cap 1.0（計画 Step 4 の5アーム）
  - wide: max_loss 6.0・spend_rate 1.0・dominant_max_loss 3.0・yose_max_loss 2.0（段階1の「攻め」プリセットから安全条件 reserve・min_winrate を除いた部分）
  - loose: wide＋dominant_hp 1.01＋natural_ratio 0.1＋free_loss 0.4（安全条件は据え置き、wide の4キーとこの3キーの計7キーをゆるめた組み合わせ。ほかのキーは default のまま）
  - user・wide・loose は計画に無いアーム。段階1の攻め（42.2%）の下げ幅のうち安全条件を緩めずに取れる分を切り分けるためと、ユーザーが使っている設定を測るために足した
- 健全性: 全アームで fallbacks 0・humansl_errors 0・hp_audit_errors 0・shadow_errors 0・aborted 0・visits_low 0・ledger_mismatch 0。
  最善手の判定（kind best）はすべてレポートでも一致、それ以外の手はすべて不一致だった（全アーム）＝一致率はそのまま「最善手しか打てなかった手番の割合」
- **同じ設定の再現性（A/A）**: default は段階1と同じ設定・同じ seed で 53.1% → 49.0%。seed ごとの差（段階1 − 段階1b）は平均 +4.1pt・標準偏差 10.4pt・95% t 区間 −0.8〜+9.0pt（KataGo の探索の非決定性で手順が分かれる）。
  **同じ run の中の対の差でも ±5pt 前後は区間に収まる**ので、20 seed では 5pt 未満の差は読めない。2 run の default を合わせた 40局の平均は 51.0%

| アーム | 自分の一致率 WATCH 局平均 [95%] | 相手の一致率 局平均 [95%] | P(own <= 0.35) | P(own < 0.15) | 勝ち/局数 [Wilson 95%] | flip_moves/局 | 自分の mean_ptloss（目/手） | ≥6目の失着/局 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） | default との差（default − アーム・対の差の平均 [t 区間 / bootstrap 区間]・信頼度 0.975） |
|---|---|---|---|---|---|---|---|---|---|---|---|
| default（spec の既定値） | 49.0% [45.7, 52.2] | 26.8% [22.8, 30.8] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 0.05 | 0.24 | 0.00 | 28.5%（441） | 0.51 | — |
| user（2026-09-24 のユーザー設定） | 43.3% [39.7, 47.1] | 25.2% [22.0, 28.3] | 15.0% | 0.0% | 20/20 [83.9, 100.0] | 0.10 | 0.41 | 0.05 | 23.7%（488） | 0.68 | 自分の一致率 +5.6pt [+0.1, +11.1 / +0.7, +10.6]（判定 extend）・flip -0.05 [-0.26, +0.16 / -0.25, +0.15]・損失 -0.16 [-0.26, -0.07 / -0.25, -0.08] |
| dom090（dominant_hp 0.9） | 51.8% [47.8, 56.1] | 24.2% [20.9, 27.4] | 5.0% | 0.0% | 20/20 [83.9, 100.0] | 0.10 | 0.24 | 0.00 | 31.8%（424） | 0.37 | 自分の一致率 -2.8pt [-8.1, +2.4 / -7.7, +1.8]（判定 extend）・flip -0.05 [-0.26, +0.16 / -0.25, +0.15]・損失 -0.00 [-0.11, +0.10 / -0.10, +0.09] |
| domoff（dominant_hp OFF） | 54.4% [50.9, 57.9] | 27.2% [22.2, 32.5] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 0.15 | 0.26 | 0.00 | 30.7%（394） | 0.38 | 自分の一致率 -5.4pt [-10.7, -0.1 / -10.0, -0.5]（判定 extend）・flip -0.10 [-0.34, +0.14 / -0.35, +0.10]・損失 -0.02 [-0.11, +0.07 / -0.10, +0.06] |
| nat010（natural_ratio 0.1） | 51.5% [47.2, 56.3] | 24.8% [20.8, 28.8] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 0.10 | 0.27 | 0.00 | 23.9%（427） | 0.45 | 自分の一致率 -2.5pt [-8.5, +3.4 / -8.0, +2.7]（判定 extend）・flip -0.05 [-0.26, +0.16 / -0.25, +0.15]・損失 -0.03 [-0.14, +0.09 / -0.13, +0.08] |
| free040（free_loss 0.4） | 52.7% [48.7, 57.0] | 26.0% [21.4, 30.9] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 0.10 | 0.35 | 0.05 | 27.4%（417） | 0.38 | 自分の一致率 -3.8pt [-10.0, +2.4 / -9.4, +1.6]（判定 extend）・flip -0.05 [-0.26, +0.16 / -0.25, +0.15]・損失 -0.11 [-0.19, -0.04 / -0.18, -0.04] |
| drift1（close_drift_cap 1.0） | 53.0% [47.2, 58.9] | 28.2% [23.8, 32.6] | 10.0% | 0.0% | 20/20 [83.9, 100.0] | 0.25 | 0.24 | 0.10 | 29.7%（415） | 0.35 | 自分の一致率 -4.0pt [-11.4, +3.3 / -10.5, +2.8]（判定 extend）・flip -0.20 [-0.53, +0.13 / -0.50, +0.05]・損失 -0.00 [-0.08, +0.07 / -0.07, +0.06] |
| wide（攻めの安全条件以外） | 46.4% [42.0, 50.6] | 26.7% [22.2, 31.3] | 5.0% | 0.0% | 20/20 [83.9, 100.0] | 0.15 | 0.35 | 0.05 | 29.6%（467） | 0.47 | 自分の一致率 +2.5pt [-3.5, +8.5 / -2.8, +7.9]（判定 extend）・flip -0.10 [-0.34, +0.14 / -0.30, +0.10]・損失 -0.11 [-0.21, -0.01 / -0.19, -0.02] |
| loose（wide＋domoff＋nat010＋free040） | 42.4% [40.2, 44.9] | 22.9% [19.4, 26.9] | 5.0% | 0.0% | 20/20 [83.9, 100.0] | 0.15 | 0.37 | 0.00 | 23.7%（492） | 0.50 | 自分の一致率 +6.5pt [+1.8, +11.3 / +2.5, +10.8]（判定 extend）・flip -0.10 [-0.34, +0.14 / -0.30, +0.10]・損失 -0.13 [-0.24, -0.02 / -0.23, -0.04] |

対の差の全指標（default − アーム・信頼度 0.975）:

| 対の差（default − アーム） | 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p | 判定（±3pt） |
|---|---|---|---|---|---|---|
| default − user | own_top1 | +5.6pt | +0.1 〜 +11.1 | +0.7 〜 +10.6 | 0.0304 | extend |
| default − user | opp_top1 | +1.6pt | -4.0 〜 +7.3 | -3.5 〜 +6.6 | 0.4459 | extend |
| default − user | own_minus_opp | +4.0pt | -3.0 〜 +11.0 | -2.1 〜 +10.6 | 0.3884 | extend |
| default − user | flip_moves | -0.05 | -0.26 〜 +0.16 | -0.25 〜 +0.15 | 0.5637 | - |
| default − user | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − user | own_mean_ptloss | -0.16 | -0.26 〜 -0.07 | -0.25 〜 -0.08 | 0.0010 | - |
| default − user | ge6 | -0.05 | -0.17 〜 +0.07 | -0.20 〜 +0.00 | 1.0000 | - |
| default − dom090 | own_top1 | -2.8pt | -8.1 〜 +2.4 | -7.7 〜 +1.8 | 0.2837 | extend |
| default − dom090 | opp_top1 | +2.7pt | -2.4 〜 +7.7 | -1.9 〜 +7.2 | 0.2065 | extend |
| default − dom090 | own_minus_opp | -5.5pt | -12.4 〜 +1.3 | -11.7 〜 +0.6 | 0.0728 | extend |
| default − dom090 | flip_moves | -0.05 | -0.26 〜 +0.16 | -0.25 〜 +0.15 | 0.5637 | - |
| default − dom090 | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − dom090 | own_mean_ptloss | -0.00 | -0.11 〜 +0.10 | -0.10 〜 +0.09 | 0.9854 | - |
| default − dom090 | ge6 | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − domoff | own_top1 | -5.4pt | -10.7 〜 -0.1 | -10.0 〜 -0.5 | 0.0328 | extend |
| default − domoff | opp_top1 | -0.4pt | -8.2 〜 +7.4 | -7.5 〜 +6.3 | 0.8248 | extend |
| default − domoff | own_minus_opp | -5.0pt | -13.5 〜 +3.5 | -12.9 〜 +2.4 | 0.2253 | extend |
| default − domoff | flip_moves | -0.10 | -0.34 〜 +0.14 | -0.35 〜 +0.10 | 0.3173 | - |
| default − domoff | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − domoff | own_mean_ptloss | -0.02 | -0.11 〜 +0.07 | -0.10 〜 +0.06 | 0.6477 | - |
| default − domoff | ge6 | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − nat010 | own_top1 | -2.5pt | -8.5 〜 +3.4 | -8.0 〜 +2.7 | 0.4071 | extend |
| default − nat010 | opp_top1 | +2.0pt | -4.5 〜 +8.6 | -3.7 〜 +7.9 | 0.5134 | extend |
| default − nat010 | own_minus_opp | -4.6pt | -11.8 〜 +2.6 | -11.0 〜 +2.0 | 0.1422 | extend |
| default − nat010 | flip_moves | -0.05 | -0.26 〜 +0.16 | -0.25 〜 +0.15 | 0.5637 | - |
| default − nat010 | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − nat010 | own_mean_ptloss | -0.03 | -0.14 〜 +0.09 | -0.13 〜 +0.08 | 0.5706 | - |
| default − nat010 | ge6 | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − free040 | own_top1 | -3.8pt | -10.0 〜 +2.4 | -9.4 〜 +1.6 | 0.2413 | extend |
| default − free040 | opp_top1 | +0.8pt | -5.2 〜 +6.8 | -4.7 〜 +6.1 | 0.5412 | extend |
| default − free040 | own_minus_opp | -4.6pt | -13.1 〜 +3.9 | -12.2 〜 +2.7 | 0.3118 | extend |
| default − free040 | flip_moves | -0.05 | -0.26 〜 +0.16 | -0.25 〜 +0.15 | 0.5637 | - |
| default − free040 | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − free040 | own_mean_ptloss | -0.11 | -0.19 〜 -0.04 | -0.18 〜 -0.04 | 0.0032 | - |
| default − free040 | ge6 | -0.05 | -0.17 〜 +0.07 | -0.20 〜 +0.00 | 1.0000 | - |
| default − drift1 | own_top1 | -4.0pt | -11.4 〜 +3.3 | -10.5 〜 +2.8 | 0.2095 | extend |
| default − drift1 | opp_top1 | -1.4pt | -7.4 〜 +4.7 | -6.8 〜 +4.0 | 0.5327 | extend |
| default − drift1 | own_minus_opp | -2.6pt | -10.8 〜 +5.5 | -10.0 〜 +4.6 | 0.4749 | extend |
| default − drift1 | flip_moves | -0.20 | -0.53 〜 +0.13 | -0.50 〜 +0.05 | 0.1573 | - |
| default − drift1 | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − drift1 | own_mean_ptloss | -0.00 | -0.08 〜 +0.07 | -0.07 〜 +0.06 | 0.8124 | - |
| default − drift1 | ge6 | -0.10 | -0.34 〜 +0.14 | -0.40 〜 +0.00 | 1.0000 | - |
| default − wide | own_top1 | +2.5pt | -3.5 〜 +8.5 | -2.8 〜 +7.9 | 0.3224 | extend |
| default − wide | opp_top1 | +0.1pt | -6.3 〜 +6.6 | -6.0 〜 +5.6 | 0.7403 | extend |
| default − wide | own_minus_opp | +2.4pt | -6.4 〜 +11.2 | -5.6 〜 +10.1 | 0.5958 | extend |
| default − wide | flip_moves | -0.10 | -0.34 〜 +0.14 | -0.30 〜 +0.10 | 0.3173 | - |
| default − wide | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − wide | own_mean_ptloss | -0.11 | -0.21 〜 -0.01 | -0.19 〜 -0.02 | 0.0192 | - |
| default − wide | ge6 | -0.05 | -0.17 〜 +0.07 | -0.20 〜 +0.00 | 1.0000 | - |
| default − loose | own_top1 | +6.5pt | +1.8 〜 +11.3 | +2.5 〜 +10.8 | 0.0045 | extend |
| default − loose | opp_top1 | +3.9pt | -1.5 〜 +9.3 | -1.2 〜 +8.6 | 0.0365 | extend |
| default − loose | own_minus_opp | +2.6pt | -4.0 〜 +9.2 | -3.2 〜 +8.6 | 0.4304 | extend |
| default − loose | flip_moves | -0.10 | -0.34 〜 +0.14 | -0.30 〜 +0.10 | 0.3173 | - |
| default − loose | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − loose | own_mean_ptloss | -0.13 | -0.24 〜 -0.02 | -0.23 〜 -0.04 | 0.0094 | - |
| default − loose | ge6 | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |

手数・リード・区間別:

| アーム | 手数の中央値 | 最終リードの中央値 [IQR] | 自分の一致率 全手まとめ（序盤 / 中盤 / 終盤＝cal 区間 <24 / 24〜84 / >=85） | 終局の内訳 |
|---|---|---|---|---|
| default | 82.5 | +47.9 [22.5, 69.4] | 48.6%（55.7% / 44.4% / 54.5%） | opp_resign 20 |
| user | 82.5 | +57.4 [27.4, 71.5] | 43.2%（47.4% / 41.1% / 44.6%） | opp_resign 20 |
| dom090 | 82.5 | +55.1 [24.5, 73.4] | 50.5%（55.2% / 48.4% / 51.0%） | double_pass 1・opp_resign 19 |
| domoff | 82.5 | +52.3 [31.3, 70.4] | 54.1%（61.3% / 50.5% / 56.4%） | opp_resign 20 |
| nat010 | 82.5 | +54.0 [37.2, 71.7] | 50.2%（57.8% / 46.9% / 50.5%） | opp_resign 20 |
| free040 | 82.5 | +43.4 [29.0, 77.2] | 51.4%（57.8% / 48.4% / 52.5%） | opp_resign 20 |
| drift1 | 82.5 | +50.2 [26.0, 71.2] | 51.6%（56.5% / 49.3% / 52.5%） | opp_resign 20 |
| wide | 82.5 | +44.7 [15.8, 73.3] | 45.6%（54.8% / 42.9% / 38.6%） | opp_resign 20 |
| loose | 82.5 | +43.5 [29.6, 72.7] | 42.7%（53.5% / 38.0% / 42.6%） | opp_resign 20 |

韜晦のアームの判定情報（20局の合計。括弧は局平均。「最善手を打った理由」は moves.jsonl の `decision_why` を AI の手番数で割った値）:

| アーム | tiers（i / ii / iii / terminal） | kinds（打った手の種類） | 払った vloss の合計（/局） | 最善手を打った理由（AI の手番に対する割合）: 許容内に代替なし `no_pool` / 自然な代替なし `no_natural` / 条件で不採用 `none_qualified` / その他（計） | lead < reserve での同値でない外し | 接戦中の同値外しの vloss（/局） | ledger_mismatch |
|---|---|---|---|---|---|---|---|
| default | 341 / 26 / 491 / 0 | best 417・paid 201・free 131・decided 109 | 281.9 目（14.09） | 21.6% / 18.2% / 8.3% / 0.6%（48.6%） | 0 | 6.55 目（0.33） | 0 |
| user | 214 / 87 / 558 / 0 | best 371・paid 165・trap 130・free 103・decided 90 | 415.0 目（20.75） | 15.4% / 9.5% / 17.7% / 0.6%（43.2%） | 0 | 5.10 目（0.25） | 0 |
| dom090 | 357 / 8 / 485 / 6 | best 432・paid 181・decided 122・free 118・swap 2・pass 1 | 249.3 目（12.46） | 20.0% / 20.4% / 8.2% / 1.9%（50.5%） | 0 | 6.01 目（0.30） | 0 |
| domoff | 394 / 0 / 464 / 0 | best 464・paid 215・free 94・decided 85 | 286.9 目（14.35） | 22.4% / 23.5% / 8.2% / 0.0%（54.1%） | 0 | 4.78 目（0.24） | 0 |
| nat010 | 350 / 26 / 482 / 0 | best 431・paid 215・free 123・decided 89 | 294.5 目（14.73） | 24.4% / 16.4% / 9.1% / 0.3%（50.2%） | 0 | 5.65 目（0.28） | 0 |
| free040 | 357 / 32 / 466 / 3 | best 441・paid 212・free 118・decided 85・swap 2 | 370.1 目（18.50） | 22.0% / 19.6% / 9.1% / 0.7%（51.4%） | 0 | 7.13 目（0.36） | 0 |
| drift1 | 372 / 37 / 449 / 0 | best 443・paid 219・free 114・decided 82 | 277.3 目（13.87） | 21.8% / 21.6% / 7.8% / 0.5%（51.6%） | 0 | 6.25 目（0.31） | 0 |
| wide | 313 / 33 / 504 / 8 | best 391・paid 254・free 149・decided 57・swap 7 | 438.0 目（21.90） | 17.4% / 19.0% / 8.2% / 1.0%（45.6%） | 0 | 6.21 目（0.31） | 0 |
| loose | 293 / 0 / 565 / 0 | best 366・paid 263・free 130・decided 99 | 426.6 目（21.33） | 18.6% / 15.5% / 8.5% / 0.0%（42.7%） | 0 | 7.62 目（0.38） | 0 |

読み方:
- **安全条件を変えずに一致率を下げたのは loose だけ**（42.4%・同じ run の default との差 −6.5pt [t 区間 −11.3〜−1.8]・Wilcoxon p 0.0045）。段階1の攻め（42.2%・安全条件も緩めている）と同じ水準。
  最善手を打った理由のうち、許容内に代替なし（no_pool）が 21.6% → 18.6%、自然な代替なし（no_natural）が 18.2% → 15.5% に減った（条件で不採用 none_qualified は 8.3% → 8.5% で変わらない）
- wide（攻めの安全条件以外）は 46.4%（差 −2.5pt・区間は 0 をまたぐ）。攻めの下げ幅のうち安全条件を緩めずに取れる分は、wide 単独では確かめられない
- 単独のつまみ（dom090・domoff・nat010・free040・drift1）はどれも一致率を下げなかった（51.5〜54.4%）。domoff は逆に上がった（+5.4pt [+0.1〜+10.7]）＝dominant の段（ii）が無くなった手番が「許容内に代替なし」「自然な代替なし」で最善手になる（tiers i 341 → 394・no_natural 18.2% → 23.5%）。
  ただし default がこの run で低めに出ている（段階1より 4.1pt 低い）ので、単独のつまみの +2.5〜+4.0pt はその分を割り引いて読む
- 勝ちは全アーム 20/20、flip は 0.05〜0.25/局、≥6目の失着は 0〜0.10/局（通常層では差が出ない）。自分の損失は loose 0.37・wide 0.35・user 0.41 目/手（default 0.24）
- 人間らしさ（外した手の 9段 hp 中央値）: loose 23.7%・user 23.7%・nat010 23.9%（default 28.5%）。どれも採否の基準 5% を大きく上回る
- user（ユーザー設定・安全条件を緩めている）は 43.3%（差 −5.6pt）。許容内の代替は増えた（no_pool 15.4%・no_natural 9.5%）が、候補があっても採れない手番（none_qualified）が 17.7% と多い
  （152手番・うち dominant の段 ii が 42・その手番の lead 中央値 4.6目・A_t 中央値 0.98目＝候補の値段が予算に収まらない）。外した手の 130 は罠（trap）。この設定の接戦での安全は段階3b で測った

## 段階2 投了なし

段階1b に続けて実行した（2026-09-24 20:59〜22:55・約1時間56分）。数値は `veil13-p2-default-vs-enigma-summary.{json,txt}`（既定の信頼度 0.975）と games.jsonl・moves.jsonl から取った。

- 実行: `python -m katrain_debug.selfplay run --size 13 --pairs 20 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json --hp-audit rank_9d --no-resign --label veil13-p2 --arm default=veil13:<16キー> --arm enigma=enigma13plus`
  （`experiments/selfplay/20260924_2059_veil13-p2`・コンソールの写し `experiments/selfplay/veil13-p2.console.txt`・40局・aborted 0）
- コード: git HEAD `cec2ee95`・dirty false（`veil13-p2-run.json`）。default は段階1b と同じく16キーを上書きで渡した（指紋 `337c824cce919a7d`＝spec の既定値）。enigma はユーザー設定のまま
- 健全性: 両アームとも fallbacks 0・humansl_errors 0・hp_audit_errors 0・shadow_errors 0・visits_low 0。default の ledger_mismatch 0
- **手数の上限（250手）で止まった局が多い**: default 10/20・enigma 7/20（`end_reason` = `move_cap`）。相手（humanSL の1手サンプラー）は大差で負けていてもパスせず、AI の地の中に打ち続ける（上限で止まった局の最終リードの中央値は default +185.9・enigma +140.7 目）。
  このため終盤（85手以降）の手には、実戦では起きない「死んだ石の取り上げ」が多く混じる。上限まで行った局と2連続パスで終わった局を分けても、自分の一致率はほぼ同じ（default 48.7% / 46.1%・enigma 51.4% / 51.9%・局平均）

| アーム | 自分の一致率 WATCH 局平均 [95%] | 相手の一致率 局平均 [95%] | P(own <= 0.35) | P(own < 0.15) | 勝ち/局数 [Wilson 95%] | flip_moves/局 | 自分の mean_ptloss（目/手） | ≥6目の失着/局 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） | default との差（default − アーム・対の差の平均 [t 区間 / bootstrap 区間]・信頼度 0.975） |
|---|---|---|---|---|---|---|---|---|---|---|---|
| default（spec の既定値） | 47.4% [44.3, 50.7] | 18.6% [15.5, 21.7] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 0.05 | 0.18 | 0.00 | 26.7%（1048） | 0.52 | — |
| enigma（難解＋13路・基準） | 51.7% [49.2, 54.0] | 17.3% [14.8, 19.8] | 0.0% | 0.0% | 20/20 [83.9, 100.0] | 2.35 | 0.92 | 4.80 | 3.5%（947） | 2.16 | 自分の一致率 -4.3pt [-9.4, +0.9 / -8.9, +0.5]（判定 extend）・flip -2.30 [-3.43, -1.17 / -3.35, -1.35]・損失 -0.74 [-0.95, -0.53 / -0.95, -0.56] |

対の差の全指標（default − enigma・信頼度 0.975）:

| 対の差（default − アーム） | 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p | 判定（±3pt） |
|---|---|---|---|---|---|---|
| default − enigma | own_top1 | -4.3pt | -9.4 〜 +0.9 | -8.9 〜 +0.5 | 0.0546 | extend |
| default − enigma | opp_top1 | +1.3pt | -4.3 〜 +6.9 | -3.5 〜 +6.5 | 0.8983 | extend |
| default − enigma | own_minus_opp | -5.6pt | -13.3 〜 +2.2 | -12.2 〜 +1.6 | 0.1054 | extend |
| default − enigma | flip_moves | -2.30 | -3.43 〜 -1.17 | -3.35 〜 -1.35 | 0.0002 | - |
| default − enigma | win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - | - |
| default − enigma | own_mean_ptloss | -0.74 | -0.95 〜 -0.53 | -0.95 〜 -0.56 | 0.0000 | - |
| default − enigma | ge6 | -4.80 | -6.71 〜 -2.89 | -6.60 〜 -3.15 | 0.0001 | - |

手数・リード・区間別:

| アーム | 手数の中央値 | 最終リードの中央値 [IQR] | 自分の一致率 全手まとめ（序盤 / 中盤 / 終盤＝cal 区間 <24 / 24〜84 / >=85） | 終局の内訳 |
|---|---|---|---|---|
| default | 228 | +136.0 [70.4, 181.7] | 47.8%（59.6% / 47.9% / 45.5%） | double_pass 10・move_cap 10 |
| enigma | 176 | +39.1 [16.1, 111.5] | 51.7%（45.2% / 45.1% / 56.7%） | double_pass 13・move_cap 7 |

韜晦（default）の判定情報（20局の合計。括弧は局平均）:

| アーム | tiers（i / ii / iii / terminal） | kinds（打った手の種類） | 払った vloss の合計（/局） | 最善手を打った理由（AI の手番に対する割合）: 許容内に代替なし `no_pool` / 自然な代替なし `no_natural` / 条件で不採用 `none_qualified` / その他（計） | lead < reserve での同値でない外し | 接戦中の同値外しの vloss（/局） | ledger_mismatch |
|---|---|---|---|---|---|---|---|
| default | 741 / 57 / 1070 / 136 | best 956・paid 499・decided 363・free 135・swap 43・pass 8 | 466.2 目（23.31） | 18.7% / 17.4% / 6.2% / 5.4%（47.7%） | 0 | 5.86 目（0.29） | 0 |

読み方:
- **投了がなくても韜晦の一致率は上がらない**: default 47.4%（投了ありの段階1 53.1%・段階1b 49.0%）。終盤（85手以降）の自分の一致率は 45.5%（投了ありの段階1b 54.5%）で、ヨセが長くなっても最善手が増えない。
  終局帯の判定（tiers terminal 136・kinds swap 43）が働いている
- 難解＋は終盤で一致率が上がる（56.7%・序盤 45.2% / 中盤 45.1%）。全体では default − enigma = −4.3pt [−9.4, +0.9]（Wilcoxon p 0.055）
- 失着は投了ありと同じ傾向: flip 0.05 vs 2.35/局（対の差 −2.30 [−3.43, −1.17]）・≥6目の失着 0.00 vs 4.80/局・自分の損失 0.18 vs 0.92 目/手
- ハーネスの注意: 相手の一致率（default 18.6%・enigma 17.3%）は投了ありより低い。大差の局面での相手の手が多いため

## 段階3 接戦ストレス

仕上げの段階（2026-09-24）でユーザーの指示により1回だけ実行した（13:25〜14:45）。数値は `veil13-p3-default-vs-enigma-summary.{json,txt}`
（`summarize --compare default enigma --conf 0.95` の写し）と、実行ディレクトリの games.jsonl（`veil.*`）・moves.jsonl（flip と敗局の手の内訳）から取った。

- 実行: `python -m katrain_debug.selfplay run --size 13 --pairs 20 --komi-shift 4 --opponent strategy:human:human_kyu_rank=-8,modern_style=true --hp-audit rank_9d --label veil13-p3 --arm default=veil13 --arm enigma=enigma13plus`
  （`experiments/selfplay/20260924_1325_veil13-p3`・コンソールの写し `experiments/selfplay/veil13-p3.console.txt`）
- コード: git HEAD `2b9635cf`（`2b9635cf3f48b50972db5118dacbfb578606ed53`＝master へのマージ後）・dirty false（`veil13-p3-run.json`）。
  エンジン・13路・コミ 7.0・中国ルール・hp 監査 `rank_9d`・投了モデル length は段階1と同じ
- **相手 HumanStyle 9段**（`human_kyu_rank=-8`・`modern_style=true`。run.json の `opponent` が `"kind": "strategy"`・`"strategy": "human"`・
  `"override_items": ["human_kyu_rank=-8", "modern_style=true"]` であることを確認済み）
- AI 不利に 4 目（`--komi-shift 4`＝AI が黒ならコミ 11・白ならコミ 3。AI の最初の手番のリードは黒 −4.4 前後・白 −3.4 前後）
- アーム: default=`veil13`（ユーザー設定・fingerprint `337c824cce919a7d`＝段階1と同じ既定値）/ enigma=`enigma13plus`（ユーザー設定のまま）。
  trap は足していない（段階1で足す条件を満たさなかった）。**攻めプリセットは接戦で測っていない**＝(a) の結論は既定の設定だけのもの
- 局の割り付け: seed 1000〜1019（両アームが同じ seed を打つ＝対の比較）・AI の色は黒白交互（10 / 10）
- **区間の信頼度 0.95**（spec §10.4。summary の `compare[0].conf` = 0.95）。ハーネス既定の 0.975 の区間はコンソールの写しにある
  （flip_moves の対の差 t −3.04〜−1.26 / bootstrap −2.95〜−1.35＝保守側でも上限 −1.26）
- 健全性: 両アームとも aborted 0・fallbacks 0・humansl_errors 0・hp_audit_errors 0・shadow_errors 0・visits_low 0。default の ledger_mismatch 0
- 接戦になったか: default の AI の手 845 のうち 498（58.9%）を lead < reserve（5 目）で、300（35.5%）をリードで負けている局面で打った。
  最終リードの中央値は +9.4 目（段階1 は +63.1 目）

| アーム | 勝ち/局数 [Wilson 95%] | 敗局の SGF | flip_moves/局 | flip_moves の対の差（veil − enigma）の 95% 上限 | lead < reserve での同値でない外し（`veil.nonfree_below_reserve`） | 接戦中の同値外しの vloss 合計/局（`veil.close_free_vloss`） |
|---|---|---|---|---|---|---|
| default（veil13 既定） | 20/20 [83.9, 100.0] | なし | 0.20（4 手・すべて seed 1019） | **−1.39**（対の差の平均 −2.15。t −2.91〜−1.39 / bootstrap −2.85〜−1.45 の上限の大きい方・Wilcoxon p 0.0004） | 0（lead < 5.0 の外し 106 手＝free 103・終局帯の pass 2・swap 1。終局帯の手は数えない） | 3.54 目（0.18/局） |
| enigma（難解＋13路・基準） | 17/20・持碁 1 [64.0, 94.8] | 2 局（下の所見） | 2.35 | — | —（判定情報なし） | — |

- default の flip 4 手（seed 1019・AI 白）: 44・46・48 手目は最善手（kind best）、50 手目は同値外し（損失 0.05 目・勝率 50.1% → 49.1%）。
  4 手ともリード ±0.3 目以内の互角の局面で勝率が 50% の線をまたいだだけで、この局も勝ち（opp_resign・最終リード +7.3 目）
- enigma の敗局と持碁（moves.jsonl の手ごとの損失で見た所見）:
  - `enigma_1008_B.sgf`（黒・133 手・−4.1 目で負け）: 63〜73 手目に自分の 5.9〜10.8 目の損が 4 手重なって +10 目前後のリードを失った（73 手目で +5.3 → −5.5 目）
  - `enigma_1010_B.sgf`（黒・158 手・−13.5 目で負け）: 39 手目の 6.3 目の損でリード +6.6 → +0.3 目、41 手目（2.4 目）で −2.2 目に逆転し、そのまま離された
  - 持碁 `enigma_1009_W.sgf`（白・124 手）: 56・68・76 手目にそれぞれ 5.6・4.8・8.2 目を損し（どれも +7〜8 目のリードから）、76 手目で +8.5 → +0.3 目

| アーム | 自分の一致率 WATCH 局平均 [95%] | 相手の一致率 局平均 [95%] | P(own <= 0.35) | P(own < 0.15) | 自分の mean_ptloss（目/手） | ≥6目の失着/局 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） | 手数の中央値 | 最終リードの中央値 [IQR] | 自分の一致率 全手まとめ（序盤 / 中盤 / 終盤） | 終局の内訳 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | 70.5% [67.1, 74.0] | 43.1% [39.5, 46.7] | 0.0% | 0.0% | 0.12 | 0.00 | 28.7%（262） | 0.60 | 82.5 | +9.4 [6.9, 16.2] | 69.2%（77.0% / 68.9% / 49.4%） | opp_resign 18・double_pass 2 |
| enigma | 72.6% [69.5, 75.7] | 41.9% [38.4, 45.6] | 0.0% | 0.0% | 0.54 | 1.30 | 5.7%（286） | 2.86 | 104.5 | +4.5 [2.6, 8.0] | 73.1%（70.0% / 70.8% / 81.9%） | opp_resign 15・double_pass 5 |

対の差の全指標（default − enigma・信頼度 0.95）:

| 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p | 判定（±3pt） |
|---|---|---|---|---|---|
| own_top1 | -2.1pt | -8.0 〜 +3.8 | -7.6 〜 +3.1 | 0.7381 | extend |
| opp_top1 | +1.3pt | -4.2 〜 +6.8 | -3.9 〜 +6.3 | 0.5412 | extend |
| own_minus_opp | -3.4pt | -9.5 〜 +2.8 | -8.9 〜 +2.3 | 0.3118 | extend |
| flip_moves | -2.15 | -2.91 〜 -1.39 | -2.85 〜 -1.45 | 0.0004 | - |
| win | +0.15 | -0.02 〜 +0.32 | +0.00 〜 +0.30 | 0.0833 | - |
| own_mean_ptloss | -0.42 | -0.60 〜 -0.24 | -0.58 〜 -0.26 | 0.0002 | - |
| ge6 | -1.30 | -1.89 〜 -0.71 | -1.85 〜 -0.80 | 0.0008 | - |

- 自分の一致率は有意差なし（−2.1pt）。flip・損失・≥6目の失着は default が有意に少ない。勝ちの差 +0.15 は区間が 0 をまたぐ（持碁は勝ちに数えない）
- default の判定情報（`veil.*`・20局の合計）: tiers i 457 / ii 15 / iii 369 / terminal 4・kinds best 583・free 133・paid 88・decided 37・pass 3・swap 1・
  払った vloss の合計 108.8 目（5.44/局。段階1 は 13.82/局）・種類別 vloss free 5.4・paid 103.4・curse（レポートの損失 − 判定時の vloss）paid −35.4・free +2.1 目
- 接戦では lead < reserve の手番で損をする外しをしない（paid 88 手・段階1 は 189 手）ので、自分の一致率は局平均 70.5%（段階1 は 53.1%）に上がる

## 段階3b 接戦ストレス（loose・ユーザー設定）

段階2 に続けて実行した（2026-09-24 22:55〜2026-09-25 00:25・約1時間30分）。段階1b で一致率を下げた2つの設定が接戦で勝ちを落とさないかを、段階3 と同じ条件で測った（計画に無い段階＝私の判断で追加）。
数値は `veil13-p3b-<アーム>-vs-enigma-conf95-summary.{json,txt}`（`summarize --compare <アーム> enigma --conf 0.95`）と games.jsonl・moves.jsonl から取った。

- 実行: `python -m katrain_debug.selfplay run --size 13 --pairs 20 --komi-shift 4 --opponent strategy:human:human_kyu_rank=-8,modern_style=true --hp-audit rank_9d --label veil13-p3b --arm loose=veil13:<16キー> --arm user=veil13:<16キー> --arm enigma=enigma13plus`
  （`experiments/selfplay/20260924_2255_veil13-p3b`・コンソールの写し `experiments/selfplay/veil13-p3b.console.txt`・60局・aborted 0）
- コード: git HEAD `cec2ee95`・dirty false（`veil13-p3b-run.json`）。相手は HumanStyle 9段（run.json の `opponent` が `"kind": "strategy"`・`"strategy": "human"`・
  `"override_items": ["human_kyu_rank=-8", "modern_style=true"]` であることを確認済み）・AI 不利に 4 目（`komi_shift` 4.0）・seed 1000〜1019・色は黒白交互。
  アームの設定の指紋は段階1b と同じ（loose `8b6350f7d5743bc0`・user `1629b7d0a2f6ab8a`）、enigma は段階1〜3 と同じ `0df30552dca4ec6e`
- **区間の信頼度 0.95**（spec §10.4）
- 健全性: 3アームとも aborted 0・fallbacks 0・humansl_errors 0・hp_audit_errors 0・shadow_errors 0・visits_low 0。loose・user の ledger_mismatch 0
- 接戦になったか: loose の AI の手 872 のうち 496（56.9%）を lead < reserve（5 目）で、302（34.6%）をリードで負けている局面で打った。
  user（reserve 2）は 876 のうち 400（45.7%）を lead < 2 で、310（35.4%）を負けている局面で打った（876 には判定情報に lead の無い終局帯のパス 3 手を含む。どれも lead +3.8 目前後）。最終リードの中央値は loose +8.9・user +6.6 目

| アーム | 勝ち/局数 [Wilson 95%] | 敗局 | flip_moves/局 | flip_moves の対の差（アーム − enigma）平均 [t 区間 / bootstrap 区間]・95% 上限（大きい方） | lead < reserve での同値でない外し（`veil.nonfree_below_reserve`） | 接戦中の同値外しの vloss 合計/局（`veil.close_free_vloss`） |
|---|---|---|---|---|---|---|
| loose | 20/20 [83.9, 100.0] | なし | 0.05 | -1.90 [-2.70, -1.10 / -2.65, -1.20]・**-1.10**（Wilcoxon p 0.0009） | 0 | 4.68 目（0.23） |
| user | 20/20 [83.9, 100.0] | なし | 0.20 | -1.75 [-2.59, -0.91 / -2.55, -1.00]・**-0.91**（Wilcoxon p 0.0012） | 0 | 1.66 目（0.08） |
| enigma | 19/20 [76.4, 99.1] | `enigma_1008_B.sgf`（loss・最終リード -17.1） | 1.95 | — | —（判定情報なし） | — |

| アーム | 自分の一致率 WATCH 局平均 [95%] | 相手の一致率 局平均 [95%] | P(own <= 0.35) | 自分の mean_ptloss（目/手） | ≥6目の失着/局 | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） | 手数の中央値 | 最終リードの中央値 [IQR] | 自分の一致率 全手まとめ（序盤 / 中盤 / 終盤） | 終局の内訳 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| loose | 65.4% [61.9, 69.4] | 43.2% [38.5, 47.5] | 0.0% | 0.20 | 0.15 | 26.3%（306） | 0.57 | 82.5 | +8.9 [7.0, 11.5] | 64.9%（72.2% / 63.4% / 56.4%） | opp_resign 20 |
| user | 63.4% [58.3, 68.6] | 42.3% [39.0, 45.8] | 0.0% | 0.23 | 0.05 | 28.9%（332） | 0.97 | 82.5 | +6.6 [5.2, 16.4] | 62.2%（73.5% / 60.3% / 47.7%） | opp_resign 17・double_pass 3 |
| enigma | 69.1% [64.3, 73.9] | 38.5% [33.7, 43.5] | 0.0% | 0.60 | 1.65 | 5.6%（300） | 2.25 | 92.5 | +4.5 [2.5, 6.0] | 70.5%（70.0% / 65.1% / 84.0%） | opp_resign 16・double_pass 4 |

対の差（アーム − enigma・信頼度 0.95）:

| 対の差 | 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p |
|---|---|---|---|---|---|
| loose − enigma | own_top1 | -3.7pt | -9.6 〜 +2.2 | -9.1 〜 +1.8 | 0.1893 |
| loose − enigma | opp_top1 | +4.6pt | -3.2 〜 +12.4 | -3.1 〜 +11.0 | 0.0637 |
| loose − enigma | own_minus_opp | -8.3pt | -17.2 〜 +0.6 | -15.9 〜 +0.2 | 0.0181 |
| loose − enigma | flip_moves | -1.90 | -2.70 〜 -1.10 | -2.65 〜 -1.20 | 0.0009 |
| loose − enigma | win | +0.05 | -0.05 〜 +0.15 | +0.00 〜 +0.15 | 1.0000 |
| loose − enigma | own_mean_ptloss | -0.40 | -0.59 〜 -0.22 | -0.57 〜 -0.24 | 0.0002 |
| loose − enigma | ge6 | -1.50 | -2.08 〜 -0.92 | -2.05 〜 -0.95 | 0.0005 |
| user − enigma | own_top1 | -5.6pt | -13.2 〜 +2.0 | -12.5 〜 +1.3 | 0.0799 |
| user − enigma | opp_top1 | +3.8pt | -1.8 〜 +9.3 | -1.5 〜 +8.8 | 0.2024 |
| user − enigma | own_minus_opp | -9.4pt | -17.7 〜 -1.1 | -16.9 〜 -1.9 | 0.0230 |
| user − enigma | flip_moves | -1.75 | -2.59 〜 -0.91 | -2.55 〜 -1.00 | 0.0012 |
| user − enigma | win | +0.05 | -0.05 〜 +0.15 | +0.00 〜 +0.15 | 1.0000 |
| user − enigma | own_mean_ptloss | -0.37 | -0.55 〜 -0.19 | -0.53 〜 -0.21 | 0.0003 |
| user − enigma | ge6 | -1.60 | -2.21 〜 -0.99 | -2.15 〜 -1.05 | 0.0005 |

- 敗局は enigma の1局だけ（`enigma_1008_B.sgf`・黒・−17.1 目。段階3 でも同じ seed を落としている）: 57・59・77・81 手目に 3.6〜8.6 目の損が4手あり
  （どれも +6〜8 目のリードから。59 手目の後は一度 −1 目前後まで落ち、66 手目の相手の 6.2 目の損で +4.8 目に戻った）、81 手目の 8.6 目で +6.5 → −2.1 目に逆転、117 手目の 4.5 目で −12.8 → −17.3 目
- loose・user とも lead < reserve での同値でない外しは 0（lead < reserve の外しは同値外しだけ＝loose 122 手・user 84 手）
- 韜晦の2アームの判定情報（20局の合計。括弧は局平均）:

| アーム | tiers（i / ii / iii / terminal） | kinds（打った手の種類） | 払った vloss の合計（/局） | 最善手を打った理由（AI の手番に対する割合）: 許容内に代替なし `no_pool` / 自然な代替なし `no_natural` / 条件で不採用 `none_qualified` / その他（計） | lead < reserve での同値でない外し | 接戦中の同値外しの vloss（/局） | ledger_mismatch |
|---|---|---|---|---|---|---|---|
| loose | 412 / 0 / 460 / 0 | best 566・free 165・paid 91・decided 50 | 156.6 目（7.83） | 32.1% / 15.1% / 17.7% / 0.0%（64.9%） | 0 | 4.68 目（0.23） | 0 |
| user | 226 / 72 / 575 / 3 | best 544・free 134・paid 78・trap 59・decided 58・pass 2・swap 1 | 140.9 目（7.05） | 15.2% / 10.3% / 36.3% / 0.3%（62.1%） | 0 | 1.66 目（0.08） | 0 |

- 接戦では、自分の一致率は loose 65.4%・user 63.4%（段階3 の default 70.5%）に上がる。lead < reserve の手番では損をする外しをしないため（通常層と同じ理由）

## 失着の層（spec §13）の計測（2026-09-25）

spec §13.4 の手順どおり、影（記録のみ）→ ON（通常の相手）→ ON（接戦ストレス）の順に測った。コードは worktree `.claude/worktrees/veil-blunder`
（影は HEAD `c23977b8`・ON の2本は既定値を loose にした後の `fe9979c3`。どれも dirty false）。失着の設定は spec §13.2 の 13路の既定
（blunder_max_loss 10・blunder_per_game 1・blunder_hp_ratio 0.7）、`VEIL_BLUNDER_PROB` 0.5。3本とも fallbacks 0・humansl_errors 0・hp_audit_errors 0・
shadow_errors 0・visits_low 0・aborted 0・ledger_mismatch 0。

### 影（blunder_mode 1＝条件を満たす手を探して記録するだけ）

- 実行: `--label blunder13-shadow`（`experiments/selfplay/20260925_0034_blunder13-shadow`・通常の相手プール・20 seed・60局・00:34〜02:14）。
  アームは段階1b の default / loose / user に `blunder_mode 1` と失着の3キーを足したもの（全20キーを上書き）
- 写し: `blunder13-shadow-run.json`・`blunder13-shadow-sh_default-vs-sh_loose-summary.{json,txt}`

| アーム（元の設定） | 条件を満たした手番/局（手番数） | 1回以上あった局 | 検証済み損失 中央値（範囲） | 失着の手の hp / 最善手の hp（中央値） | 失着の手の hp が最善手より高い | hp が最善手の 0.7〜1.43 倍（/局） | 着手前のリードの中央値 | 手番の結末（gate / no_cand / rejected / shadow / 記録なし） | 戦略時間 p95 / 最大（秒） |
|---|---|---|---|---|---|---|---|---|---|
| sh_default（spec の既定値） | 1.45（29） | 14/20 | 7.4 目（4.9〜9.7） | 36% / 8% | 27/29 | 0.25（5） | 42.4 目 | 542 / 277 / 10 / 29 / 0 | 1.00 / 2.29 |
| sh_loose（loose） | 0.45（9） | 6/20 | 7.2 目（6.2〜9.9） | 27% / 12% | 9/9 | 0.05（1） | 29.8 目 | 595 / 238 / 5 / 9 / 7 | 0.85 / 2.53 |
| sh_user（ユーザー設定） | 0.55（11） | 7/20 | 7.8 目（6.8〜9.7） | 35% / 10% | 10/11 | 0.10（2） | 46.0 目 | 480 / 343 / 14 / 11 / 5 | 1.28 / 3.31 |

- 条件を満たす手番は spec の既定値（支払い上限 4.5 目）で 1.45 回/局、loose（上限 6 目）で 0.45 回/局。上限が高いほど「上限を超える損失」の帯が狭いので少ない
- 失着の手の 9段 hp は、ほとんどの手番で最善手の hp より高い（loose 9/9・既定 27/29）＝9段なら失着の手のほうを選びやすい局面。
  hp が最善手の 0.7〜1.43 倍（「ほぼ同じ」）の手番は loose で 0.05 回/局。**ユーザーの決定（2026-09-25）: 条件は下限（0.7 倍以上）だけのまま**
- 影なので打つ手は変わらない＝この run は既定と loose の再測定にもなる: 自分の一致率 sh_default 52.4% / sh_loose 45.8%・
  対の差（sh_default − sh_loose）+6.7pt [t −0.0, +13.4]（信頼度 0.975・Wilcoxon p 0.044）＝段階1b の −6.5pt と同じ向き・同じ大きさ
- 影の run の ≥6目の失着（打った手はすべて通常の層の手＝判定の読み違い）は sh_default 0.00・sh_loose 0.25・sh_user 0.25 回/局（summary の `ge6_per_game`）

### ON（blunder_mode 2・通常の相手）

- 実行: `--label blunder13-on`（`experiments/selfplay/20260925_0215_blunder13-on`・40局・02:15〜02:54）。アーム loose（失着 OFF）/ on_loose（loose ＋ 失着 ON）
- 写し: `blunder13-on-run.json`・`blunder13-on-loose-vs-on_loose-summary.{json,txt}`（信頼度 0.975）

| アーム | 自分の一致率 局平均 [95%] | 相手の一致率 局平均 | 勝ち/局数 [Wilson 95%] | flip_moves/局 | 自分の mean_ptloss（目/手） | ≥6目の失着/局（レポート） | 外した手の 9段 hp 中央値（手数） | 戦略時間 p95（秒） | 最終リードの中央値 |
|---|---|---|---|---|---|---|---|---|---|
| loose | 47.4% [43.3, 51.7] | 23.4% | 20/20 [83.9, 100.0] | 0.15 | 0.42 | 0.10 | 26.6%（452） | 0.53 | +64.9 |
| on_loose | 47.9% [44.3, 51.3] | 27.6% | 20/20 [83.9, 100.0] | 0.20 | 0.36 | 0.10 | 25.6%（450） | 0.55 | +56.0 |

対の差（loose − on_loose・信頼度 0.975）:

| 指標 | 平均 | t 区間 | bootstrap 区間 | Wilcoxon p |
|---|---|---|---|---|
| own_top1 | -0.5pt | -6.3 〜 +5.3 | -5.0 〜 +5.2 | 0.2446 |
| opp_top1 | -4.3pt | -11.7 〜 +3.2 | -10.6 〜 +2.6 | 0.1084 |
| own_minus_opp | +3.7pt | -6.3 〜 +13.8 | -5.5 〜 +12.5 | 0.2579 |
| flip_moves | -0.05 | -0.17 〜 +0.07 | -0.20 〜 +0.00 | 1.0000 |
| win | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - |
| own_mean_ptloss | +0.06 | -0.05 〜 +0.16 | -0.04 〜 +0.15 | 0.2305 |
| ge6 | +0.00 | +0.00 〜 +0.00 | +0.00 〜 +0.00 | - |

打った失着（on_loose・20局）:

手番の結末（on_loose）: gate 618・no_cand 211・skipped 12・rejected 9・played 4・記録なし 1

| seed（AI の色） | 手数 | 打った失着 | 検証済み損失（深い読み） | 終局レポートの損失 | 失着の手の hp / 最善手の hp | 着手前のリード | 着手後の勝率（深い読み） | その局の結果・最終リード |
|---|---|---|---|---|---|---|---|---|
| 1006（B） | 71 | A3 | 9.8 目 | 8.7 目 | 70% / 2% | +68.7 目 | 100.0% | win・+163.3 目 |
| 1011（W） | 94 | G13 | 8.0 目 | 4.9 目 | 44% / 28% | +71.2 目 | 99.9% | win・+143.9 目 |
| 1012（B） | 53 | H5 | 6.8 目 | 4.9 目 | 17% / 2% | +27.5 目 | 99.6% | win・+56.3 目 |
| 1016（B） | 59 | M6 | 7.9 目 | 7.1 目 | 55% / 41% | +19.5 目 | 99.8% | win・+38.9 目 |

- 失着は 4/20 局で1回ずつ＝**0.20 回/局**。深い読みの損失 6.8〜9.8 目、終局レポートの損失 4.9〜8.7 目（レポートで ≥6目に数えたのは2手）。
  4手とも着手前のリード +19.5 目以上・着手後の勝率 99.6% 以上で、4局とも勝ち
- 勝ち・flip・一致率に差は無い（一致率 47.9% vs 47.4%＝失着1回は外し1手と同じなので一致率はほぼ変わらない）。≥6目の失着/局はどちらも 0.10（loose の 0.10 は失着以外の手）
- loose（失着 OFF）の自分の一致率はこの run で 47.4%（段階1b 42.4%・影 45.8%）＝同じ設定の run 間のずれが 5pt ある。3 run の平均は loose 45.2%（段階1b・影・ON の OFF 側）・既定 51.5%（段階1・1b・影）

### ON（接戦ストレス）

- 実行: `--label blunder13-on-p3`（`experiments/selfplay/20260925_0254_blunder13-on-p3`・40局・02:54〜03:41）。段階3 と同じ条件（AI 不利 4 目・
  相手 HumanStyle 9段〈`human_kyu_rank=-8`・`modern_style=true`＝run.json で確認済み〉・seed 1000〜1019）。アーム on_loose / enigma
- 写し: `blunder13-on-p3-run.json`・`blunder13-on-p3-on_loose-vs-enigma-conf95-summary.{json,txt}`（信頼度 0.95）

| アーム | 勝ち-負け-持碁 / 局数 [勝ちの Wilson 95%] | 勝ちでない局 | flip_moves/局 | flip_moves の対の差（on_loose − enigma）平均 [t / bootstrap]・95% 上限 | ≥6目の失着/局（レポート） | 自分の一致率 局平均 | 自分の mean_ptloss | 外した手の 9段 hp 中央値 | 最終リードの中央値 |
|---|---|---|---|---|---|---|---|---|---|
| on_loose | 19-0-1 / 20 [76.4, 99.1] | `on_loose_1010_B.sgf`（jigo・-0.0） | 0.35 | -1.80 [-2.79, -0.81 / -2.70, -0.90]・**-0.81**（Wilcoxon p 0.0033） | 0.05 | 64.6% | 0.25 | 26.1% | +8.7 |
| enigma | 17-2-1 / 20 [64.0, 94.8] | `enigma_1008_B.sgf`（loss・-5.8）, `enigma_1010_B.sgf`（jigo・+0.0）, `enigma_1014_B.sgf`（loss・-5.8） | 2.15 | — | 0.75 | 70.5% | 0.49 | 6.2% | +5.1 |

打った失着（on_loose・接戦ストレス）:

手番の結末（on_loose）: gate 849・no_cand 50・rejected 6・played 1・記録なし 1

| seed（AI の色） | 手数 | 打った失着 | 検証済み損失（深い読み） | 終局レポートの損失 | 失着の手の hp / 最善手の hp | 着手前のリード | 着手後の勝率（深い読み） | その局の結果・最終リード |
|---|---|---|---|---|---|---|---|---|
| 1010（B） | 57 | H12 | 8.4 目 | 4.8 目 | 27% / 11% | +23.6 目 | 95.2% | jigo・-0.0 目 |

- 失着は1回だけ（seed 1010 の 57 手目・リード +23.6 目の局面）。ほかの手番は関門で止まるか（849）、候補なし（50）・資格なし（6）で打たなかった＝接戦ではほぼ出ない
- spec §10.4 (a): flip_moves の対の差の 95% 上限 **−0.81** <= 0.1・敗局 0 vs 難解＋ 2 → **可**
- **持碁の1局（seed 1010）の直接の原因は 83 手目の決着局面の即決（S13）の読み落とし。57 手目の失着も重なった**: 83 手目 F2 は親局面の解析（2523 visits）で生の loss 0.36 目
  （F_eff 0.4 以下・9段 hp 5.0%＝loose の自然さの床 0.05 ちょうど）だったので、S13 がプローブなしで打った。実際には 16.3 目の損（リード +15.8 → −0.5 目・
  勝率 99.1% → 30.9%）で、そのまま持碁。リードの流れ（moves.jsonl の `lead_before_ai` / `points_lost`・AI 視点）: 56 手目の相手の
  7.4 目の損で +23.6 目、57 手目の失着（レポート 4.8 目）で +18.7 目、77 手目の直前に +24.4 目まで戻り、79 手目の支払い 3.7 目などで
  83 手目の直前は +15.8 目。57 手目の失着が無ければ 83 手目の時点のリードは約 +20.6 目で、同じ読み落としでも約 +4 目残って
  勝っていた計算＝失着も重なった。
  全 run の即決 約2,200手のうち 5 目以上の損は3手（16.3・6.9・6.0 目）＝まれだが勝ちを落としうる → **S13 を「打つ前に best と候補の2手をプローブで確かめる」に直した**
  （spec §4 S13 の 2026-09-25 追記・`veil_decided_verified_ok`）。直した後の接戦ストレスは流していない（この1局の形＝生の loss は小さいがプローブでは大損、はプローブで止まる＝`tests/test_ai_veil.py` の回帰テストで固定）。直したコードでこの局面（83 手目の直前・loose ＋ 失着 ON）を debug CLI と KataGo で再生すると、解析のゆらぎで F2 は候補に出ず、自然な候補 E3・F4 は子局面のプローブで 13.2・18.6 目の損（勝率 64.0%・31.8%）と判定されて最善手 D2 を打った＝読み落としの起きやすい急所の局面

## 罠 A/B（段階1 trap vs default）

| 指標 | default | trap | 対の差（default − trap・信頼度 0.975） |
|---|---|---|---|
| 自分の一致率 局平均 | 53.1% [49.6, 56.5] | 50.8% [47.2, 54.5] | +2.3pt [t -2.4, +6.9 / bootstrap -1.7, +6.4]・Wilcoxon p 0.24・判定 extend |
| 相手の一致率 局平均 | 26.3% [22.7, 30.1] | 24.4% [19.9, 29.1] | +1.9pt [-4.6, +8.5 / -4.0, +7.8] |
| 勝ち | 20/20 | 20/20 | 0 |
| flip_moves/局 | 0.05 | 0.10 | -0.05 [-0.26, +0.16 / -0.25, +0.15] |
| 自分の mean_ptloss（目/手） | 0.24 | 0.24 | +0.00 [-0.09, +0.10 / -0.08, +0.09] |
| 払った vloss の合計（`veil.paid_vloss_sum`） | 276.5 目（13.82/局） | 260.3 目（13.01/局） | — |
| 種類別 vloss（`veil.vloss_by_kind`） | free 7.8・paid 268.7 | free 6.9・paid 128.4・trap 125.0 | — |
| 罠の次の相手手の実損 / E（`veil.trap_next_loss_over_E`） | — | **0.77**（罠 90 手の次の相手手の損失 215.8 目 / E 281.5 目。局ごとの値は平均 0.83・中央値 0.65・19局） | — |
| 選んだ手の 9段 hp 中央値（全着手 / 外した手） | 49.6% / 27.8% | 43.9% / 24.9% | — |

- trap は一致率を 2.3pt 下げたが有意でなく（20 seed では ±3pt の判定がつかない）、勝ち・flip・損失に差は無い
- 罠の次の相手手の実損 / E は 0.77 で、想定の 1.06 から大きく外れる（ハーネスの相手は E が見込むほど罠に掛からない）→ **罠の効果の結論は保留**。
  相手の終盤の忠実度の限界（実行条件の注意）もあり、罠の評価は実戦に回す
- 段階3に trap アームを足す条件（trap が一致率を 3pt 以上下げる）は満たさなかった（段階3は default と enigma の2アームで実行）

## 一致率の下限の内訳

段階1の moves.jsonl の判定情報（`decision_kind` / `decision_why` / `decision_A_t` / `decision_lead` ほか）を数え直した。default の
AI の手は 858（すべて判定情報つき・すべてレポートの分母に入る）。割合の分母はすべて 858。

- default で最善手を打った手（kind = best）は 452 = **52.7%**（why の付いた手＝終局帯の swap 1手も含めると 453 = 52.8%）。
  **レポートの一致（全手まとめ 452/858 = 52.7%）はちょうどこの 452 手**（最善手を打った手はすべて一致し、外した手は1手も一致しない）。
  一致率は「最善手を打つしかなかった手番」の割合そのもの

| 最善手の理由（why） | 手数 | 割合 | その手番の様子 |
|---|---|---|---|
| no_pool（候補が最善手だけ） | 227 | 26.5% | 通常解析の候補に raw_cap（= max(F, A_t) + 0.3）以内の別の手が無い。A_t が上限（ヨセ前 4.5・ヨセ中 1.5）に達していた手番が 121（うち A_t = 4.5 が 96）＝予算を満額使えても候補が無い（A_t = 0 の 67 手番のうち 64 は余剰 S <= 0＝lead が reserve 以下）。KataGo の最善手の policy prior の中央値 0.89・0.8 以上が 61% ＝一本道の手 |
| no_natural（自然な別の手が無い） | 144 | 16.8% | raw_cap 以内に候補はあるが 9段 humanPolicy が自然さの床未満。85 手番は明らかな一手（最善手の hp >= 0.8）・最善手の hp 中央値 0.89 |
| none_qualified（安全条件を満たす外しが無い） | 76 | 8.9% | lead の中央値 2.2 目・52 手番（68%）が lead < reserve（接戦）＝同値外ししか許されず、プローブで同値の条件（vloss・勝率の低下）を満たす手が無い |
| dominant_closed（明らかな一手・一致率が目標以下） | 4 | 0.5% | — |
| terminal（終局帯） | 1 | 0.1% | — |

割合は個別に四捨五入（足すと 52.8%。手数の合計は 452/858 = 52.7%）。

- 外した手: paid 189（22.0%）・free 130（15.2%）・decided 86（10.0%）・swap 1（0.1%）
- 予算は余っている: 最終リードの中央値 +63.1 目・自分の損失 0.24 目/手。**一致率の下限は予算ではなく構造**＝ユーザー自身の
  要件5(i)「候補が最善手しか無い → 最善手」＋自然さの床＋接戦の安全条件（spec §12 の「律速は予算ではなく在庫と接戦の安全条件」と合う）
- attack でも kind = best は 361/858 = 42.1%（swap 3手を含めると 364 = 42.4%）: no_natural 18.4%・no_pool 15.5%・none_qualified 6.8%・
  dominant_closed 0.7%・pass 0.6%・terminal 0.1%。安全条件を緩めても下限は 40% 台に残る
- trap の kind = best は 422/834 = 50.6%（none_qualified 25.4%・no_pool 13.3%・no_natural 9.6%・dominant_closed 1.7% ほか）
- 段階1b の loose（安全条件は据え置き・支払いの上限など7キーをゆるめた設定）でも kind = best は 366/858 = 42.7%（no_pool 18.6%・no_natural 15.5%・none_qualified 8.5%）。user（ユーザー設定・安全条件を緩めている）は 371/859 = 43.2%（none_qualified 17.7%・no_pool 15.4%・no_natural 9.5%・dominant_closed 0.6%）。どの設定でもレポートの一致はちょうど kind = best の手番で、下限は 40% 台前半に残る

## 採否（spec §10.4）

- (a) 勝ちの安全: **可**（段階3＝接戦ストレス・2026-09-24。既定の設定だけ）。flip_moves の対の差 default − enigma −2.15/局の 95% 上限は
  t −1.39 / bootstrap −1.45 の大きい方（保守側）で **−1.39 <= 0.1**、かつ敗局は default 0・enigma 2（default が enigma より 2 局を超えて多くない）。
  flip_moves は default 0.20/局（4 手・すべて seed 1019 の互角の局面）・enigma 2.35/局、≥6目の失着は 0.00 vs 1.30/局。
  範囲: AI 不利 4 目・相手 HumanStyle 9段・20 対のハーネス測定で、攻めプリセットと罠 ON は接戦で測っていない。実戦校正は未実施。
  段階1（通常層）の材料（記述のみ）: default 20/20 勝ち [Wilson 83.9, 100]・flip_moves 0.05/局（enigma 2.75/局）・対の差 default − enigma
  −2.70/局 [t −3.57, −1.83 / bootstrap −3.50, −1.95]（信頼度 0.975・Wilcoxon p 0.0002＝有意に少ない）・lead < reserve での同値でない外し 0。
  通常層の勝敗は記述にとどめる（全勝に近いので検出力がない）
  段階3b（2026-09-24〜25・同じ条件）: **loose も可**＝20-0・flip_moves 0.05/局（難解＋ 1.95/局）・対の差 −1.90 の 95% 上限 **−1.10** <= 0.1・敗局 0 vs 難解＋ 1。**user（ユーザー設定 reserve 2・min_winrate 0.8）も可**＝20-0・flip_moves 0.20/局・対の差 −1.75 の 95% 上限 **−0.91** <= 0.1・敗局 0 vs 1。どちらも lead < reserve での同値でない外し 0
- (b) 人間らしさ: **可**。default の外した手の 9段 hp 中央値 27.8%（406手）>= 5%（trap 24.9%・attack 28.5%。基準の enigma は 3.6%）。段階1b では loose 23.7%・user 23.7%・wide 29.6%（default 28.5%）で、どれも可
- (c) 一致率: default の P(own <= 0.35) = **0%**（0/20）・P(own < 0.15) = 0%。局平均 53.1% で目標 30% に遠い（attack でも
  P(own <= 0.35) = 15%＝3/20・局平均 42.2%）。下限は構造的（上の「一致率の下限の内訳」）。接戦（段階3）では局平均 70.5%・
  P(own <= 0.35) = 0%（lead < reserve の手番では損をする外しをしない）
  段階1b: P(own <= 0.35) は user 15%（3/20）・drift1 10%・loose / wide / dom090 5%（1/20）・default ほか 0%。P(own < 0.15) はすべて 0%。接戦（段階3b）では loose 65.4%・user 63.4%・P(own <= 0.35) = 0%

## 境界線と推奨

段階1（5アーム）と段階1b（9アーム）の通常層の結果を、自分の一致率の低い順に並べた（どちらも同じ相手プール・同じ seed 1000〜1019。
default は両方の run にあり 53.1% / 49.0%＝同じ設定の再実行で 4.1pt ずれる。run をまたぐ比較はこのずれを含めて読む）。接戦の列は段階3・3b。

| アーム（段階） | 安全条件（reserve / min_winrate） | 自分の一致率 局平均 | 勝ち | flip_moves/局 | 外した手の 9段 hp 中央値 | P(own <= 0.35) | 接戦（段階3・3b） | 備考 |
|---|---|---|---|---|---|---|---|---|
| attack（1） | 3.0 / 0.75（緩めた） | 42.2% | 20/20 | 0.05 | 28.5% | 15.0% | 未測定 | 参考。**既定にするには要件1の再決定が要る** |
| loose（1b） | 5.0 / 0.85（据え置き） | 42.4% | 20/20 | 0.15 | 23.7% | 5.0% | **可**（20-0・flip 0.05/局） | 同じ run の default との差 −6.5pt [t −11.3, −1.8]・損失 0.37 目/手 |
| user（1b） | 2.0 / 0.80（緩めた） | 43.3% | 20/20 | 0.10 | 23.7% | 15.0% | **可**（20-0・flip 0.20/局） | ユーザーが使っている設定（spend 0.75・max_loss 6・罠 ON）。損失 0.41 目/手 |
| wide（1b） | 5.0 / 0.85（据え置き） | 46.4% | 20/20 | 0.15 | 29.6% | 5.0% | 未測定 | 差 −2.5pt（区間は 0 をまたぐ） |
| default（1b） | 5.0 / 0.85（据え置き） | 49.0% | 20/20 | 0.05 | 28.5% | 0.0% | **可**（段階3: 20-0・flip 0.20/局） | spec §6.1 の既定値（段階1 では 53.1%） |
| enigma（1） | —（難解＋） | 49.7% | 20/20 | 2.75 | 3.6% | 10.0% | 17-2-1・flip 2.35/局（段階3） | 基準（(b) を満たさない） |
| trap（1） | 5.0 / 0.85（据え置き） | 50.8% | 20/20 | 0.10 | 24.9% | 0.0% | 未測定 | 罠の比 0.77 で結論保留 |
| nat010（1b） | 5.0 / 0.85（据え置き） | 51.5% | 20/20 | 0.10 | 23.9% | 0.0% | 未測定 | 単独では下がらない |
| dom090（1b） | 5.0 / 0.85（据え置き） | 51.8% | 20/20 | 0.10 | 31.8% | 5.0% | 未測定 | 単独では下がらない |
| free040（1b） | 5.0 / 0.85（据え置き） | 52.7% | 20/20 | 0.10 | 27.4% | 0.0% | 未測定 | 単独では下がらない |
| drift1（1b） | 5.0 / 0.85（据え置き） | 53.0% | 20/20 | 0.25 | 29.7% | 10.0% | 未測定 | 接戦の累計上限（通常層では効かない） |
| human（1） | —（HumanStyle 9段） | 53.2% | 20/20 | 1.00 | 28.3% | 0.0% | — | 参照 |
| domoff（1b） | 5.0 / 0.85（据え置き） | 54.4% | 20/20 | 0.15 | 30.7% | 0.0% | 未測定 | 逆に上がる（+5.4pt [+0.1, +10.7]） |

推奨: 安全条件を変えずに (a)(b) を満たす韜晦の設定のうち、一致率が最も低いのは **loose**（spec の既定値から max_loss 6.0・spend_rate 1.0・
dominant_max_loss 3.0・yose_max_loss 2.0・dominant_hp OFF（1.01）・natural_ratio 0.1・free_loss 0.4 に変えたもの）。
同じ run の default より 6.5pt 低く（42.4%）、接戦（段階3b）でも 20-0・flip 0.05/局で (a) は可。代わりに自分の損失は 0.24 → 0.37 目/手、
外した手の 9段 hp 中央値は 28.5% → 23.7%（基準 5% は大きく上回る）。→ **13路の既定を loose にすることを推奨する**（2026-09-25 にユーザーが loose を選んだ＝下の「ユーザーの決定（2026-09-25）」）。
それでも目標の 30% には届かない（下限は構造的＝上の「一致率の下限の内訳」）。20 seed・1 run の測定で、run 間のずれ（A/A 4.1pt）程度の不確かさがある。
user（ユーザー設定）は安全条件を緩めているので既定の候補ではない（要件1の再決定が要る）が、ユーザーが使う設定として接戦ストレスでも勝ちを落とさなかった。
追記（2026-09-25）: 失着の層の計測（下）で loose と既定をさらに測り直した。自分の一致率は loose 42.4% / 45.8% / 47.4%（3 run 平均 45.2%）・既定 53.1% / 49.0% / 52.4%（平均 51.5%）で、同じ run の中の差は −6.5pt / −6.7pt と揃う。水準は「loose で 45% 前後」と読む

## ユーザーの決定（2026-09-24）

- 進み方: 据え置いて実戦確認へ進む（段階1の後で測定を打ち切り）
- 変える項目と値: なし（13路は spec §6.1 の既定値のまま）
- 9路・19路: 据え置き（未校正）
- 要件1（安全条件 reserve / min_winrate）: 据え置き（攻めプリセットは測定専用のまま。GUI のスライダーで個別に試せる）
- 採否の基準で満たさなかった項目とその扱い: (c) P(own <= 0.35) が既定で 0%（一致率の下限は構造的＝上の内訳）。(a) は段階3を行わなかったため未評価＝実戦で確認する
- 追記（2026-09-24・仕上げの段階）: ユーザーの指示で段階3（接戦ストレス）を1回だけ実行し、(a) 勝ちの安全は既定の設定で**可**
  （20-0・flip_moves の対の差の 95% 上限 −1.39 <= 0.1・敗局 0 vs 難解＋ 2。上の「段階3 接戦ストレス」と「採否」）。
  上の (a) の「未評価」はこれで解消。既定値は変えていない。段階1b・2 は未実施のまま
- 追記（2026-09-25）: ユーザーの指示（2026-09-24 夜「未対応の校正作業を続けて」）で段階1b・2 を実行し、段階3b を足した（上の各節）。既定値はまだ変えていない＝**loose を 13路の既定にするかはユーザーの選択待ち**（上の「境界線と推奨」）

## 最善手しか無い手番の外し（spec §14）の見積もり（2026-09-25）

記録は `experiments/selfplay/relax-spike-20260925/`（gitignore）。数値は下のとおり＝そこの `workflow_summary.md` の reconcile の最終表から写した値。書き換えない。

- 方法: 実戦3局（119手）・ハーネスの通常の相手 60局（p1b loose・blunder13-shadow sh_loose・blunder13-on loose）・接戦ストレス 20局（p3b loose）の強制手番 1790 手で、2500v の親解析・humanSL（9段・5段・3段・1段）・候補最大 8 手の 500v プローブを集め、条件ごとに1手ずつの反実仮想（先の外しの損は lead から引く一次近似）。評価は独立の3実装で全値一致。
- 表1（同じ局面を humanSL の確率どおりに打つ人の一致率）: 通常 9段 48.3%・5段 46.3%・3段 44.4%・1段 41.7%／接戦ストレス 48.4・46.0・43.9・41.1%／実戦 51.9・49.6・47.3・44.7%。
- 表2（主な条件・1局ごとの平均の一致率。範囲は素朴〜悲観）: 今（loose）通常 45.2%・実戦 53.6%・ストレス 65.4%／① 安全は今のまま・強制手番だけ上限 10目: 40.2〜42.2%・49.0%・63.0〜66.2%／② リード +2・勝率 70%・上限 6目: 38.4〜43.7%・46.4〜48.4%・59.5〜64.2%／③ 同・上限 10目: 36.3〜42.2%・43.5〜45.4%・59.5〜65.4%／④ 同・上限なし: 34.6〜41.4%・41.8〜48.4%・59.5〜65.4%。最終リードが負になる局（一次近似・ストレス 20局）: ①② 0・③④ 1。
- 要点: 9段らしさの床を守る限り、安全条件をすべて外しても下限は通常 23.9%・実戦 27.8%（最善手の 9段 hp >= 0.95 の手番は 390 手中 0 しか開かない）。効くのは大差での1手の損の上限。1局の勝率の予算は終盤の勝率の飽和で効かず（B05 はストレスで 2/20 局の最終リードが負）、弱い段位の humanSL を基準にする案は +0.3〜1.1pt だけ。新しく外す手の 9段 hp の中央値は 0.23〜0.25（既存の外しは 0.26）。

## 最善手しか無い手番の外し（spec §14）の計測（2026-09-25）

spec §14.4 の手順どおり、`cur`（loose＋失着 ON＝いまのユーザーのローカル設定）と `new`（`cur`＋`veil13_forced_mode` 2・forced のほかの値は
§14.2 の 13路の既定＝forced_min_lead 2・forced_min_winrate 0.70・forced_max_loss 10）を、通常の相手と接戦ストレスで比べた。コードは worktree
`.claude/worktrees/veil-forced` の HEAD `f46a8003`（2本とも dirty false）。アームは 24 キーを明示（`experiments/selfplay/sdd-records/forced/arms.py`）。
2本とも aborted 0・errors 0・hp_audit_errors 0・shadow_errors 0・visits_low 0・ledger_mismatch 0。数値は `veil13-campaign/` に写した
`veil13-forced-cur-vs-new-summary.{json,txt}`・`veil13-forced-p3-cur-vs-new-summary.{json,txt}` と、この層の結末を moves.jsonl から数えた
`veil13-forced-tables.txt`（`sdd-records/forced/forced_tables.py` の出力）から取った。

| 実行 | ラベル・出力ディレクトリ | 局数 | 所要 |
|---|---|---|---|
| 通常の相手 | `veil13-forced`（`experiments/selfplay/20260925_1934_veil13-forced`） | 40（2 アーム × 20 seed）・aborted 0 | 19:34〜20:44（約1時間10分） |
| 接戦ストレス | `veil13-forced-p3`（`experiments/selfplay/20260925_2044_veil13-forced-p3`） | 80（2 アーム × 40 seed）・aborted 0 | 20:44〜22:51（約2時間7分） |

- 実行: `python -m katrain_debug.selfplay run --size 13 --pairs 20 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json --hp-audit rank_9d --label veil13-forced --arm cur=veil13:<24キー> --arm new=veil13:<24キー>`・
  `python -m katrain_debug.selfplay run --size 13 --pairs 40 --komi-shift 4 --opponent strategy:human:human_kyu_rank=-8,modern_style=true --hp-audit rank_9d --label veil13-forced-p3 --arm cur=… --arm new=…`

| 相手 | アーム | 勝-負-持碁 | 自分の一致率（局平均 [95% 区間]） | 相手の一致率 | この層の手/局 | 失着/局 | ≥6目/局 | 自分の平均損失 | 外した手の 9段 hp 中央値 | 戦略時間 p95 | 最終リード 中央値 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 通常 | cur | 20-0-0 | 44.1% [40.5, 47.9] | 29.0% | — | 0.30 | 0.35 | 0.44 | 23.6% | 0.99 秒 | +35.9 |
| 通常 | new | 20-0-0 | **38.5%** [35.3, 41.9] | 28.2% | 5.65 | 0.30 | 0.75 | 0.61 | 27.1% | 1.06 秒 | +40.3 |
| 接戦ストレス | cur | 40-0-0 | 66.1% [62.6, 69.4] | 39.3% | — | 0.03 | 0.075 | 0.18 | 26.1% | 0.76 秒 | +7.0 |
| 接戦ストレス | new | 40-0-0 | 62.6% [58.8, 66.6] | 41.4% | 3.67 | 0.00 | 0.275 | 0.29 | 28.2% | 0.74 秒 | +6.5 |

- 同じ seed の対の差（cur − new・信頼度 0.975）: 通常 自分の一致率 **+5.5pt**（t −0.2〜+11.2・bootstrap +0.4〜+10.8・Wilcoxon p 0.036）・
  勝ち 0・flip 0（どちらも 0.05/局）。接戦ストレス +3.4pt（t −2.0〜+8.8・bootstrap −1.6〜+8.6・p 0.17）・勝ち 0・flip 0.20 → 0.10/局。
- この層の手番（`new`）:
  - 通常: 結末は no_cand 204・played 113・gate 105・rejected 21（この層に来ない手番 415）。来た手番の元の出口は no_pool 203・no_natural 147・
    none_qualified 93、打った手は none_qualified 48・no_pool 40・no_natural 25。打った手 113 手（中央値 5 手/局・最大 16）のうちリード 5 目未満で 32 手。
    cost 中央値 2.49 目（最大 9.62・6 目超 15 手）、終局レポートの損失 中央値 1.61 目（≥6目 11 手・最大 11.97）、9段 hp 中央値 0.275（p10 0.097）。
    検証済みの着手後勝率の最小 0.756・着手後リードの最小 2.04・root リード − cost の最小 2.04。1局の cost の合計 中央値 13.7 目（最大 51.4）。
    戦略時間 p95 はこの層が読んだ手番 1.27 秒・ほか 0.99 秒。
  - 接戦ストレス: 結末は gate 623・no_cand 314・played 147・rejected 58（来ない手番 486）。打った手 147 手（中央値 2 手/局・最大 16）のうちリード 5 目未満で 74 手。
    cost 中央値 1.40 目（最大 9.25・6 目超 9 手）、レポートの損失 中央値 0.96 目（≥6目 8 手・最大 9.66）、9段 hp 中央値 0.325（p10 0.106）。
    着手後勝率の最小 0.712・着手後リードの最小 2.04・root リード − cost の最小 2.01。1局の cost の合計 中央値 5.4 目（最大 26.2）。
    負けは 0 局（接戦ストレスは初めからコミで約 4.5 目不利なので、cur・new とも全局で序盤の AI の勝率が 0.03〜0.09 まで下がり、全局を逆転して勝った）。
    ただし最終リードの最小は new +2.0 目（cur +3.0）で、+3 目未満で終わった局が new は 6/40（cur 1/40）＝この層が forced_min_lead（2 目）まで
    リードを使う局がある。
- ハーネスの警報 `nonfree_below_reserve`（lead < reserve での同値でない外し）は `new` で 32（通常）・74（接戦ストレス）。**kind 別に数えると
  すべてこの層の手**で、この層以外の手は cur・new とも 0（最終レビューの I2。この層はリードが forced_min_lead 以上残る範囲で、reserve 未満でも打つ設計）。
- 見積もり（前節の③: 通常 36.3〜42.2%）との比較: 実測 38.5% は幅の中（素朴な計算と悲観的な計算の間）。

### 採否（spec §14.4）

- (a) 通常の相手: `new` の自分の一致率 38.5% <= 42%・負け 0/20 → **可**
- (b) 接戦ストレス: `new` の負け 0/40（持碁 0）→ **可**
- (c) この層の手の 9段 hp の中央値 0.275（接戦ストレス 0.325）>= 0.15 → **可**。≥6目の手は 0.75 回/局（cur 0.35）・接戦ストレス 0.275 回/局（cur 0.075）
- (d) 1手の戦略時間の p95 1.06 秒（この層が読んだ手番だけでも 1.27 秒）<= 2 秒 → **可**

→ 4つとも可。

## ユーザーの決定（2026-09-25）

- 進み方: 変える（13路の既定を段階1b の loose にする）
- 変える項目と値（13路）: free_loss 0.3 → 0.4・spend_rate 0.5 → 1.0・max_loss 4.5 → 6.0・yose_max_loss 1.5 → 2.0・dominant_hp 0.8 → 1.01（OFF）・
  dominant_max_loss 2.0 → 3.0・natural_ratio 0.2 → 0.1（ほかの9キーは spec §6.1 のまま）
- 9路・19路: 据え置き（未校正）
- 要件1（安全条件 reserve / min_winrate）: 据え置き（5.0 / 0.85）
- ローカル設定（`~/.katrain/config.json` の `ai:veil13`）も loose に揃える（それまでの値＝reserve 2・min_winrate 0.8・spend_rate 0.75・max_loss 6・trap_mode ON は上書き。編集前の写しを残す）
- 失着の層（spec §13）: 条件は下限（失着の手の hp が最善手の 0.7 倍以上）だけのまま・既定は OFF（GUI の LOG／ON で使う）
- 採否の基準で満たさなかった項目: (c) P(own <= 0.35) は loose でも 5%（1/20）。一致率の下限は構造的で目標 30% に届かない（loose の3 run 平均 45.2%）
- あわせて直したこと: 決着局面の即決（S13）を打つ前に2手だけプローブで確かめる（上の「失着の層の計測」の接戦ストレスの持碁・spec §4 S13 の追記）
- 最善手しか無い手番の外し（spec §14）: 20局に1局ほどの負けを許して一致率を平均 30〜45% に下げる。条件は ③（着手後リード +2目・着手後勝率 70%・1手の損の上限 10目・ヨセは yose_max_loss）。コードの既定は OFF、校正に合格したらローカル設定で ON。
