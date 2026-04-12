---
description: 各AI戦略の現在のパラメータ値リファレンス（ai.py編集時に参照。値を変更したらこのファイルも同時に更新すること）
paths:
  - "katrain/core/ai.py"
---

# AI戦略パラメータ リファレンス

## 悪手フィルタ閾値

| パラメータ | 19路・13路 | 9路盤 |
|---|---|---|
| OPENING_THRESHOLD | 2.8 | 0.5 |
| NORMAL_THRESHOLD | 5.6 | 3.3 |

## 第一感ぶれ（全盤面）

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| first_impression_deviation | false | ONで第一感上位3位中のhumanPolicy≥5%かつ損失0.5〜上限目の手のうち最も損失の少ない手を確定選択（9路=1.5目、13路・19路=2.0目） |
| first_impression_deviation_opening | false | ON（+deviation ON）で序盤でも第一感ぶれを適用する（デフォルトOFF=序盤は無効） |
| first_impression_green_blend | false | ON（+deviation ON）で第一感1位が緑(loss<0.5)かつ非最善の場合、第一感1位と上位3位中の最小損失手(0.5〜上限)をgreen_ratioで選択 |
| green_blend_green_ratio | 0.5 | green_blend時の緑手選択確率（0.4=dev寄り40/60・0.5=均等50/50・0.6=緑寄り60/40） |

## エンジン設定（maxVisits）

Stage1とGUI/analysis_configの3箇所を同じ値に揃える。Stage2は独立値。

| 場所 | 現在値 | 役割 |
|---|---|---|
| ai.py `override_settings["maxVisits"]` | 800 | Stage1: HumanSL着手選択 |
| ai.py `clean_override_settings["maxVisits"]` | 600 | Stage2: クリーンスコア検証（独立値） |
| GUI `max_visits` / `analysis_config.cfg` | 800 | 事後分析クエリ（Stage1と揃える） |

## 力戦派モード（FightingStrategy）

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| fighting_mode | "classic" | "classic" / "scoreloss" / "human" |
| fighting_max_loss | 3.0 | scorelossモード専用の悪手フィルタ閾値（目数） |
| force_tengen_opening | false | ONで黒番初手のみ天元に打つ |
| fighting_invasion_bonus | 1.0 | 相手地への侵入手の重みボーナス（全モード共通、最大5.0） |
| fighting_contact_boost | 1.0 | 相手石への接触手（距離1）の重みブースト（全モード共通、最大5.0） |
| fighting_chaos_relax | 0.0 | humanモード: 相手地への接触手の悪手閾値を緩和する目数（最大3.0） |
| unsettled_power | 2.0 | 未確定地への重み指数（大きいほど未確定地に集中） |
| proximity_stddev | 3.0 | 相手石への近接重みの標準偏差（小さいほど近距離に集中、最小2.0） |

humanモードの悪手フィルタ閾値はHumanStyleStrategyと同じBAD_MOVE_THRESHOLD（19路 NORMAL=5.6 / OPENING=2.8、9路 NORMAL=3.3 / OPENING=0.5）を使用。`fighting_max_loss`は無効。

## 狩猟戦略（HuntStrategy）

独立した戦略（`ai:hunt`）。序盤から相手の勢力圏に積極的に侵入し、弱い石群を集中攻撃する攻撃型モード。ownershipベースの侵入対象と石グループターゲットを統合して常に攻め続ける。対応盤面: 19路・13路（9路は非対応）。

**着手選択**: 2段階クエリ方式（humanSL 9段固定）。重み = `humanPolicy × proximity × intensity × territory_avoid × focus_penalty`（侵入/攻撃時）/ `humanPolicy × territory_avoid`（対象なし時）。proximity のstddevは侵入対象と石グループで別パラメータ。intensityは侵入対象ならopp_strength、石グループならinstability。territory_avoidは自陣回避ペナルティ（`max(0.1, 1.0 - max(0.0, own_ownership))`、自分の確定地で重み90%減）。安全弁・タイブレーク・エンドゲーム処理あり。

**フェーズ**: Invade（侵入対象のみ）→ Hunt（侵入+石グループ）→ Endgame。石グループターゲットの有無で自動切替。

**ターゲット検出**: 石グループは `find_targets()`（SiegeStrategyと共有）で毎手再評価。侵入対象はownershipグリッドから毎手抽出（`hunt_invasion_min` 〜 `hunt_invasion_max` の範囲）。

| パラメータ | デフォルト(19路) | デフォルト(13路) | 備考 |
|---|---|---|---|
| hunt_max_loss | 6.0 | 4.0 | 石群攻撃時の許容最大損失（目） |
| hunt_min_group_size | 5 | 4 | ターゲット最小グループサイズ |
| hunt_proximity_stddev | 3.0 | 2.5 | 石群攻撃の近接重みの標準偏差 |
| hunt_instability_min | 0.3 | 0.3 | ターゲット判定の最小不安定度 |
| hunt_invasion_max_loss | 8.0 | 6.0 | 侵入時の許容最大損失（目） |
| hunt_invasion_min | 0.2 | 0.2 | 侵入対象ownership強度の下限 |
| hunt_invasion_max | 0.7 | 0.7 | 侵入対象ownership強度の上限 |
| hunt_invasion_proximity_stddev | 3.0 | 3.0 | 侵入用の近接重みの標準偏差 |
| hunt_invasion_temperature | 1.5 | 1.5 | 侵入フェーズの選択温度（1.0/1.5/2.0、高い＝分散） |
| hunt_focus_stddev | 7.0 | 5.0 | 注意フォーカスの広がり（Gaussian標準偏差）。直前手と最も不安定なターゲットの重心を中心に、遠い手をペナルティする。小さい＝集中、大きい＝緩やか。floor=0.05 |
| hunt_endgame_move | 200 | — | 19路盤でヨセモードに切り替える手数（19路盤のみ。13路以下は `ceil(0.5×盤面マス数)` 固定） |
| hunt_pursue_enabled | true | true | 攻め合い追撃。相手が勝負手を打った場合、手抜きせず詰め手を継続する（GUI: チェックボックス） |
| hunt_pursue_proximity | 2 | 2 | 勝負手判定の近接距離（Chebyshev距離、路）。config.json手動編集のみ |
| hunt_pursue_min_liberties | 3 | 3 | この数以上のリバティなら無条件追撃。config.json手動編集のみ |
| hunt_pursue_ownership_threshold | 0.85 | 0.85 | ownership確信度の閾値（石群サイズ≥10で+0.05、≥15で+0.10）。config.json手動編集のみ |
| hunt_winning_suppress_enabled | false | false | 勝勢時の最善手weight抑制。15目以上リードでKataGo最善手のweight×0.3（GUI: チェックボックス） |
| hunt_dead_stone_avoid_enabled | true | true | 死石周辺の無駄手抑制。ownership × player_sign < -0.85 の自石または4近傍で loss > 0.5 の候補手を weight × 0.05 に減衰（GUI: チェックボックス） |

**スコア適応型損失制御（ハードコード）**: 劣勢時（`score_lead < -6.0`）は `hunt_max_loss` と `hunt_invasion_max_loss` を `min(設定値, 4.0)` にキャップ。段階的緩和も4.0でキャップされ、候補がなければ即failsafe（最善手選択）。

## AI一致率低減モード（DivergenceStrategy）

評価レポートの AI 最善手一致率≤30%・上位5手一致率≤40%・平均損失<1.00 を目標とする新戦略モード。

**目標値**: `ai_top_move ≤ 30%`, `ai_top5_move ≤ 40%`, `mean_ptloss < 1.00`

**アルゴリズム**: `divergence_score = humanPolicy × (order+1)^divergence_power`
（order: KataGo の探索順位、0=最善手。大きいほど AI 下位手をブースト）

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| human_kyu_rank | -8（9段） | humanSLプロファイルのベース段位 |
| divergence_power | 0.5 | AI一致率低減強度（0.3〜1.5）。大きいほど AI 下位手をブースト |
| diverge_score_filter | 2.5 | 許容する最大損失（目数）（1.0〜5.0） |

**注意**: `divergence_power` のデフォルト値は実戦テストで調整が必要。目標値に届かない場合は 0.3 刻みで引き上げる。

## 攻城戦略（SiegeStrategy）

序盤は相手に地を譲り、中盤以降に不安定な大石群を攻めて逆転を狙う「背水の陣」モード。対応盤面: 19路・13路。

**着手選択**: HumanStyleStrategy/FightingStrategy (human) と同じ2段階クエリ方式。Stage 1でhumanPolicy（9段固定）を取得し、Stage 2のクリーンスコアでフィルタ。重み = `humanPolicy × 戦略重み`（concedeはconcede_score、attackはproximity × instability）。安全弁・タイブレーク・エンドゲーム処理あり。エンドゲーム閾値: `ceil(0.5 × 盤面マス数)`（19路=181手目）。

**フェーズ**: 序盤（Concede）→ 攻撃（Attack）。手数条件 + ターゲット存在で切替。60%経過で強制移行。

| パラメータ | デフォルト値(19路) | デフォルト値(13路) | 備考 |
|---|---|---|---|
| siege_transition_move | 40 | 25 | 攻撃フェーズ移行の最小手数 |
| siege_min_group_size | 5 | 4 | ターゲット最小グループサイズ |
| concede_max_loss | 4.5 | 3.0 | 序盤の許容最大損失（目） |
| siege_max_loss | 6.0 | 4.0 | 攻撃時の許容最大損失（目） |
| siege_proximity_stddev | 3.0 | 2.5 | ターゲット近接重みの標準偏差 |
| siege_instability_min | 0.3 | 0.3 | ターゲット判定の最小不安定度 |
