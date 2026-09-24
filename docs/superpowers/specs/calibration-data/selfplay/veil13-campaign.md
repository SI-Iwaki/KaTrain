# 韜晦（13路）自己対局キャンペーン結果（2026-09-24）

計画 `docs/superpowers/plans/2026-09-23-veil-strategy.md` の Task 15・spec `2026-09-23-veil-strategy-design.md` §10。
**段階1（主比較）だけを実行した**。2026-09-24 にユーザーが段階1の結果を見て測定を打ち切った（段階1b・2・3 は未実施）。

数値は `veil13-campaign/` に写した summary（`veil13-p1-default-vs-<アーム>-summary.{json,txt}`）から取った。局平均と 95% 区間は
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
| 段階1b・2・3 | — | — | 未実施（2026-09-24 ユーザー判断で段階1の後に打ち切り） |

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

未実施（2026-09-24 ユーザー判断で段階1の後に打ち切り）

## 段階2 投了なし

未実施（2026-09-24 ユーザー判断で段階1の後に打ち切り）

## 段階3 接戦ストレス

未実施（2026-09-24 ユーザー判断で段階1の後に打ち切り）

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
- 段階3に trap アームを足す条件（trap が一致率を 3pt 以上下げる）は満たさなかった（段階3は未実施）

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

- 外した手: paid 189（22.0%）・free 130（15.2%）・decided 86（10.0%）・swap 1（0.1%）
- 予算は余っている: 最終リードの中央値 +63.1 目・自分の損失 0.24 目/手。**一致率の下限は予算ではなく構造**＝ユーザー自身の
  要件5(i)「候補が最善手しか無い → 最善手」＋自然さの床＋接戦の安全条件（spec §12 の「律速は予算ではなく在庫と接戦の安全条件」と合う）
- attack でも kind = best は 361/858 = 42.1%（swap 3手を含めると 364 = 42.4%）: no_natural 18.4%・no_pool 15.5%・none_qualified 6.8%・
  dominant_closed 0.7%・pass 0.6%・terminal 0.1%。安全条件を緩めても下限は 40% 台に残る
- trap の kind = best は 422/834 = 50.6%（none_qualified 25.4%・no_pool 13.3%・no_natural 9.6%・dominant_closed 1.7% ほか）

## 採否（spec §10.4）

- (a) 勝ちの安全: **評価できなかった**（段階3＝接戦ストレスを行わなかった。flip_moves の対の差の 95% 上限と敗局数は段階3で測る基準）。
  段階1（通常層）だけの材料: default 20/20 勝ち [Wilson 83.9, 100]・flip_moves 0.05/局（enigma 2.75/局）・対の差 default − enigma
  −2.70/局 [t −3.57, −1.83 / bootstrap −3.50, −1.95]（信頼度 0.975・Wilcoxon p 0.0002＝有意に少ない）・lead < reserve での同値でない外し 0。
  通常層の勝敗は記述にとどめる（全勝に近いので検出力がない）→ 実戦で確認する
- (b) 人間らしさ: **可**。default の外した手の 9段 hp 中央値 27.8%（406手）>= 5%（trap 24.9%・attack 28.5%。基準の enigma は 3.6%）
- (c) 一致率: default の P(own <= 0.35) = **0%**（0/20）・P(own < 0.15) = 0%。局平均 53.1% で目標 30% に遠い（attack でも
  P(own <= 0.35) = 15%＝3/20・局平均 42.2%）。下限は構造的（上の「一致率の下限の内訳」）

## 境界線と推奨

段階1b（安全条件以外のつまみの掃引）を行わなかったので、境界線は段階1の5点だけ（自分の一致率の低い順）。

| アーム | 安全条件（reserve / min_winrate） | 自分の一致率 局平均 | 勝ち | flip_moves/局 | 外した手の 9段 hp 中央値 | P(own <= 0.35) | 備考 |
|---|---|---|---|---|---|---|---|
| attack | 3.0 / 0.75（緩めた） | 42.2% | 20/20 | 0.05 | 28.5% | 15.0% | 参考。**既定にするには要件1の再決定が要る** |
| enigma | —（難解＋） | 49.7% | 20/20 | 2.75 | 3.6% | 10.0% | 基準（(b) を満たさない） |
| trap | 5.0 / 0.85（据え置き） | 50.8% | 20/20 | 0.10 | 24.9% | 0.0% | 罠の比 0.77 で結論保留 |
| default | 5.0 / 0.85（据え置き） | 53.1% | 20/20 | 0.05 | 27.8% | 0.0% | spec §6.1 の既定値 |
| human | —（HumanStyle 9段） | 53.2% | 20/20 | 1.00 | 28.3% | 0.0% | 参照 |

推奨: 安全条件を変えずに (b) を満たす韜晦のアームは default と trap（(a) は段階3を行わなかったので未評価）で、P(own <= 0.35) はどちらも 0% の同率 →
**default（spec §6.1 の既定値のまま・trap_mode OFF）**。trap は一致率の差が有意でなく罠の比 0.77 で保留、attack は要件1の再決定が要るので参考に並べるだけ。
