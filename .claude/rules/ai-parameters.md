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
| ai.py `override_settings["maxVisits"]` (HumanStyle/Fighting/Siege/Hunt) | 800 | Stage1: HumanSL着手選択 |
| ai.py `stage1_override["maxVisits"]` (Jigo) | 1 | Stage1: humanPolicy 取得のみ（humanSL NN の root policy 出力で visits 不変） |
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

## 持碁戦略（JigoStrategy）

指定した目差範囲（0.5〜10目）で僅差勝ちを目指す戦略。人間らしくない大損失手・humanPolicy≒0 の手を除外して、サボタージュ的挙動を防ぐ。対応盤面: 全盤面（19路・13路・9路）。

**着手選択**: HumanStyle と同じ2段階クエリ方式（Stage1 humanSL 9段固定 / Stage2 クリーンスコア）。フィルタ = `loss ≤ max_loss_per_move AND humanPolicy ≥ min_human_policy`。候補ゼロ時は段階緩和（hp×0.5 → hp×0.25 → loss×1.5 → KataGo 最善手）。

**選択ロジック**:
- `current_lead < target_score`: target 最接近手（最善近辺）
- `target_score ≤ lead ≤ target_score_max` & Mode=natural: humanPolicy 重み付き（HumanStyle 相当）
- Mode=maintain または `lead > target_score_max`: target 最接近手

**target-closest 同点扱いバンド（2026-04-19 追加）**: `lead < target_score` と `in_range & mode=maintain` の分岐で、argmin(|score-target|) の結果を「min_diff + jigo_equivalent_epsilon 以内の候補」に拡張し、その中から humanPolicy 重みで1手を選択する（`_pick_target_closest_with_epsilon`）。定石一本道局面では候補1個のみバンドに入り現行挙動と一致。バンド内 hp 全ゼロ時は argmin にフォールバック。`in_range & natural` と `lead > target_max` 分岐は変更なし。Spec: `docs/superpowers/specs/2026-04-19-jigo-epsilon-tiebreak-design.md`

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| target_score | 0.5 | 狙う目差（既存流用） |
| target_score_max | 10.0 | 許容上限。これ以下なら Natural モードは普通に打つ |
| max_loss_per_move | 5.6 | 1手あたり許容損失（HumanStyle NORMAL_THRESHOLD と同値） |
| min_human_policy | 0.02 | humanPolicy 最低閾値（1%） |
| jigo_mode | "natural" | "natural"=範囲内は最善手 / "maintain"=常にtargetに寄せる |
| human_profile | "rank_9d" | humanSL 段位（rank_5d / rank_7d / rank_9d）。Stage 1 クエリで使用 |
| jigo_dynamic_rank | false | ON でリード差（`current_lead - target_score_max`）に応じて rank を自動降格（delta > 5 で1段下、> 15 で rank_5d まで） |
| jigo_large_lead_delta | 5.0 | 圧勝発動目数差。`current_lead ≥ target_score_max + delta` で `max_loss_per_move` を一時的に緩和（Δ=3.0/5.0/7.0/10.0） |
| jigo_large_lead_max_loss | 8.0 | 圧勝時の許容損失（目）。9路盤は内部で 5.0 にキャップ。値の選択肢: 6.0/7.0/8.0/9.0/10.0 |
| jigo_equivalent_epsilon | 0.5 | target-closest からの同点扱い許容幅（目）。分岐1(lead<target)と分岐3(in_range&maintain)でのみ適用、0.0/0.3/0.5/1.0 から選択。0 で完全現行動作 |
| jigo_deception | false | 油断誘発 Phase 機構を有効化。Phase 0 (1-29 手) は通常 Jigo、Phase 1 (30-79 手) で target=-3.0/-2.0、Phase 2 (80-149 手) で target=-1.5/-0.5、Phase 3 (150 手-) で user 設定復帰。安全弁 ±5 目で Phase 3 強制ジャンプ。13/9 路は手数比例スケール。Spec: `docs/superpowers/specs/2026-05-16-jigo-deception-phase-design.md` |
| jigo_deception_13_phase1_start | 17 | 13路盤のみ。Phase 0→1 境界手数。値: 10/17/25/35 |
| jigo_deception_13_phase2_start | 44 | 13路盤のみ。Phase 1→2 境界手数。値: 30/44/55/70 |
| jigo_deception_13_phase3_start | 83 | 13路盤のみ。Phase 2→3 境界手数。値: 70/83/95/110 |
| jigo_deception_13_phase1_target | -2.0 | 13路盤のみ。Phase 1 の eff_target（target_max は +1.0 自動）。値: -1.0/-2.0/-3.0/-4.0 |
| jigo_deception_13_phase2_target | -1.0 | 13路盤のみ。Phase 2 の eff_target（target_max は +1.0 自動）。値: -0.5/-1.0/-1.5/-2.0 |
| jigo_force_sanrensei | false | ON で19路盤序盤に星打ちを強制（黒=三連星/白=2連星）。13路・9路は無効。Stage 1 直後に対象を計算し非空なら Stage 2 をスキップして即着手。Spec: docs/superpowers/specs/2026-05-30-jigo-force-sanrensei-design.md |

**設計上の限界**: 相手が毎手 6 目以上の大損失手を連続で打つような極端な棋力差の対局では、1 手あたり損失上限 `max_loss_per_move (5.6)` を AI 側が超えられず、target 範囲への収束が保証されない。ただし人間らしい着手は維持されるため「バレないこと」という主目的は達成される。相手の棋力が持碁モード（humanSL 9段相当）と釣り合うときのみ目差収束を期待する設計。

**弱相手対応（2026-04-13 追加）**: 以下の機構で改善:
- **鋭手除外**: 圧勝時（`current_lead > target_score_max`）、`score > current_lead + 0.5` の候補を選択肢から除外（`_jigo_exclude_sharp_moves`）。全滅時は元の候補リストを返す安全弁あり
- **humanPolicy ハードフロア**: 段階緩和の hp 閾値が **0.005（0.5%）未満に落ちない**（`MIN_HP_HARD_FLOOR`）。ユーザが `min_human_policy` を下げても「人間なら打たない手」までは到達しない
- **動的 rank 切替（opt-in）**: `jigo_dynamic_rank=true` で、前ターンの `current_lead` をキャッシュし、`delta = current_lead - target_score_max` に応じて Stage 1 の rank を降格:
  - `delta ≤ 5`: base_profile そのまま
  - `5 < delta ≤ 15`: chain で1段下（rank_9d → rank_7d, rank_7d → rank_5d）
  - `delta > 15`: 一気に rank_5d まで下げる
  - chain: `["rank_5d", "rank_7d", "rank_9d"]`
  - 初手（キャッシュなし）や chain 外プロファイルは base_profile を使用

**圧勝時 max_loss 動的緩和（2026-04-13 追加）**: `current_lead ≥ target_score_max + jigo_large_lead_delta` のとき `max_loss_per_move` を `jigo_large_lead_max_loss (デフォルト 8.0)` に動的緩和。選択ロジック・鋭手除外は完全現行維持で hp 重み選択により target 方向の中 loss 手が候補入りやすくなる。9路盤は 5.0 上限。なお `jigo_large_lead_max_loss < max_loss_per_move` の場合は base 値を維持する（緩和方向のみに作用、tightening しない）。

**校正履歴**: 動的 rank 降格閾値は 2026-04-13 に 3段 vs Jigo 白番 SGF でバッチ評価したが、差が誤差範囲のため現行値 `delta_1=5, delta_2=15` を維持（`docs/superpowers/specs/calibration-data/jigo-dynamic-rank-results-20260413.md` 参照）。
