---
description: 各AI戦略の現在のパラメータ値リファレンス（ai.py編集時に参照。値を変更したらこのファイルも同時に更新すること）
paths:
  - "katrain/core/ai.py"
---

# AI戦略パラメータ リファレンス

詰碁（`ai:tsumego` / `ai:tsumego_solver`）のパラメータは `tsumego-parameters.md` へ分離した。

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

## 星打ち布石の強制（`force_star_opening` / `ai:human`）

| パラメータ | 既定 | 説明 |
|---|---|---|
| `force_star_opening` | false | true で序盤の星点を強制する（HumanStyle の**2連星**） |

実装は共有ヘルパー `_compute_star_opening_targets(board_size, stones, ai_player, n)`
（`ai.py:7776`）。`n=2` が HumanStyle の2連星、`n=3` が Jigo の三連星
（`jigo_force_sanrensei`・19路専用）で、**同じヘルパーを共用**している。

`n=2` の挙動: 隅4星のみを使う。自分の星が0個なら空いている隅星（相手が星を打っていれば
その**対角**）、1個なら**同じ辺**の星、を目標にする。強制不要・完成済み・盤面非対応なら
空集合を返して通常選択に戻る。

**確認**: ログの `[HumanStyleStrategy] force_star_opening:` 行（`ai.py:8117`）。

## エンジン設定（maxVisits）

**`extra_settings`（overrideSettings）に置いた `maxVisits` は効かない**。`request_analysis` は
top-level の `maxVisits` を `visits` 引数（既定 `config["max_visits"]`）から必ず入れ、KataGo は
top-level を優先する（実測 2026-08-06）。歴史的に各戦略の Stage1/Stage2 は dict に 800/600 を
書いていたが**すべて dead キーで、実効は常に GUI の `max_visits`（現在 1000）**だった。
2026-08-11 に dead キーを全戦略から除去（挙動不変・parity9 の 0ef0f32 と同じ扱い）。
悪手フィルタ等の閾値校正はこの実態（config visits）に対して行われてきたので、
**「文書上の 800/600 を効かせる」方向の修正は挙動変更＝再校正が要る。やらないこと**。

| 場所 | 実効値 | 役割 |
|---|---|---|
| Stage1（HumanStyle/Fighting/Siege/Hunt/Divergence・humanSL 着手選択） | config `max_visits`（1000） | humanPolicy + moveInfos。**事後分析と自動で同値**（同じ config キーを共有）＝「Stage1 と GUI を揃える」は構造的に常時成立 |
| Stage1（Jigo/Jigo9・humanPolicy 取得のみ） | **1**（`visits=1` を引数で明示・2026-08-11 修正） | humanPolicy のみ（root NN 出力＝visits 非依存）。旧実装は dead キーのため実際は 1000visits の humanSL 探索を毎手待っていた（実測 0.14〜0.27 秒/手）。**Stage2 失敗時のフォールバックは biased な Stage1 moveInfos → KataGo 最善手に変更**（1visit の moveInfos では代替不能。稀なエンジンエラー経路の failsafe 統一） |
| Stage2（クリーンスコア検証・wRN=0・全戦略） | config `max_visits`（1000） | scoreLead（「独立値 600」は dead キーの想定値で、実際に 600 で走ったことはない） |
| GUI `max_visits`（`~/.katrain/config.json`） | 1000 | 事後分析クエリ。Stage1/Stage2 も同じ値で走る |
| `katrain/KataGo/analysis_config.cfg`（**パッケージ側**。エンジンが実際に読むのはこちら。`~/.katrain/analysis_config.cfg` は参照されない） | 500 | `maxVisits` デフォルト値。個々のクエリは毎回 maxVisits を明示送信するため、cfg 側のデフォルトが効く場面は限定的 |

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

human/complex モードの悪手フィルタ閾値は **GUI 調整可能**（`fighting_max_loss` は無効＝scoreloss 専用）。盤面サイズ×フェーズで独立したキーを引く（`_fighting_loss_thresholds`）。

| パラメータ | デフォルト | 選択肢 | 適用 |
|---|---|---|---|
| fighting_human_opening_max_loss | 2.8 | 0.5〜6.0（0.5刻み＋2.8） | 13/19路・序盤 |
| fighting_human_max_loss | 5.6 | 1.0〜10.0（0.5刻み＋5.6） | 13/19路・中盤以降 |
| fighting_human_opening_max_loss_9 | 0.5 | 0.1〜2.0（0.1刻み） | 9路・序盤 |
| fighting_human_max_loss_9 | 3.3 | 0.5〜6.0（0.5刻み＋3.3） | 9路・中盤以降 |

序盤境界は `ceil(0.14 × 盤面マス数)`（19路=51 / 13路=24 / 9路=12）。安全弁は 4.0 固定なので、閾値を 4.0 超に**引き上げる**と最高重み候補が安全弁で最善手に巻き戻される（引き下げ用途では無害）。

### complexモード（複雑化）

接触戦の密度を最優先に盤面を複雑化する4つ目の `fighting_mode`。`human` モードのパイプライン（2段階クエリ・安全弁・タイブレーク）を再利用し、重み関数と悪手フィルタを差し替える。重み = 力戦重み（unsettled×proximity×contact_boost×invasion_bonus）× 切りボーナス。接触強調は既存 `fighting_contact_boost` を流用（complex時は 2.0〜3.0 推奨）。

悪手フィルタはリード適応: `loss < base閾値`(19路 NORMAL=5.6) は常に通過。`base ≤ loss < relaxed_cap` は「大差リード（current_lead ≥ complexity_lead_threshold）かつ 鋭い（scoreStdev ≥ complexity_sharpness_min）かつ 複雑（複雑さ重みが候補中最大の _COMPLEXITY_WEIGHT_FRAC 倍以上）」の3条件を満たす手のみ通過。`relaxed_cap` はリード差 `_COMPLEXITY_RAMP`(=10目) かけて base から complexity_max_loss まで線形上昇。complex時は安全弁閾値も relaxed_cap まで引き上げ、意図的な予算内損失を温存する。`complexity_base_max_loss`（既定5.6）でリードに関係なく常時このゲート付き帯を上限N目まで開ける。実効上限 = `max(complexity_base_max_loss, lead適応 relaxed_cap)` で動作する。`fighting_max_loss` は scoreloss 専用で complex には無効。

| パラメータ | デフォルト | 選択肢 | 備考 |
|---|---|---|---|
| complexity_cut_boost | 2.0 | 1.0/1.5/2.0/3.0/5.0 | 切り点（相手chain2つ以上隣接）の重みブースト |
| complexity_lead_threshold | 15.0 | 5/10/15/20/25/30 | この目数以上リードで損失緩和を解禁 |
| complexity_base_max_loss | 5.6 | 1.0〜10.0（0.5刻み＋5.6） | **13/19路専用**。互角〜劣勢でも開放するゲート付き帯の上限（目）。既定5.6=現状維持。効く上限=max(これ, relaxed_cap)。**無条件帯の上限（fighting_human_max_loss）と同じ値にすると互角時は上乗せなし**、それより高いと互角でも差分ぶんゲート付き帯が開く |
| complexity_max_loss | 10.0 | 1.0〜12.0（0.5刻み） | **13/19路専用**。緩和時の損失上限（`lead_threshold` 到達後、リード差10目かけて base→max へ線形上昇） |
| complexity_base_max_loss_9 | 3.3 | 0.5〜6.0（0.5刻み＋3.3） | 9路版。従来は盤面非依存だったため9路に13/19路向けの値が漏れていた |
| complexity_max_loss_9 | 6.0 | 1.0〜10.0（0.5刻み） | 9路版。同上 |

スライダー候補値は `_half_steps()`（`constants.py`）で生成する。**候補値に無い数値もテキストボックスに直接入力すれば保存される**が（`LabelledSelectionSlider.input_value` が `float(textbox.text)` を返す）、`SelectionSlider.set_from_pos` はクリック／ドラッグのたびに `on_change` を発火してテキストを最寄り候補値で上書きするため、そのスライダーを一度でも触ると入力値は失われる。**常用する値は候補値に入れること**。
| complexity_sharpness_min | 3.0 | 1/2/3/4/5/7/10 | 緩和バンド通過に必要な scoreStdev（要GUI校正） |

ハードコード定数: `_COMPLEXITY_WEIGHT_FRAC=0.5`（複雑さ重みフロア比）/ `_COMPLEXITY_RAMP=10.0`（relaxed_cap の上昇幅、目）。純関数（`_count_cut_adjacency` / `_apply_cut_boost` / `_complexity_relaxed_cap` / `_passes_complexity_gate` / `_complexity_loss_filter`）は `tests/test_fighting_complexity.py` でユニットテスト済み。検証は GUI 実戦（batch評価では複雑化は測れない）。Spec: docs/superpowers/specs/2026-05-30-fighting-complexity-design.md

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

## 狩猟一致率低減戦略（HuntDivergenceStrategy / `ai:hunt_diverge`）

`HuntStrategy` のサブクラスで、パラメータは狩猟戦略と共通（`hunt_max_loss` /
`hunt_min_group_size` / `hunt_proximity_stddev` / `hunt_instability_min` /
`hunt_invasion_*` / `hunt_endgame_move` / `hunt_pursue_enabled` /
`hunt_winning_suppress_enabled`）。**狩猟戦略にあって hunt_diverge に無いキー**は
`hunt_invasion_temperature` / `hunt_focus_stddev` / `hunt_dead_stone_avoid_enabled`
＝ `_select_final_move` を丸ごと上書きし、温度サンプリングを使わないため。

固有パラメータは Best-move dodge の2つだけ:

| パラメータ | パッケージ既定 | ローカル既定 | 説明 |
|---|---|---|---|
| `hunt_dodge_max_loss` | 1.0 | **0.5** | 差し替え先として許す損失の上限（目）。これを超える代替手は使わない |
| `hunt_dodge_top_n` | 3 | 3 | 差し替え先を探す **combined weight 上位N手**の範囲 |

（`hunt_winning_suppress_enabled` もローカルは **true**、パッケージ既定は false）

**Best-move dodge の動作**（`_select_final_move`）: 温度なしの weighted selection で
選ばれた手が KataGo 最善手だったときだけ発動し、「損失 <= `hunt_dodge_max_loss`」かつ
「combined weight 上位 `hunt_dodge_top_n` 位以内」の非最善手のうち**損失最小**の手へ差し替える。
該当が無ければ最善手のまま（ログ `Best-move dodge: no alternative`）。

**順位は必ず combined weight で取る**（`weight_by_gtp` = proximity/intensity 込み）。
生 humanPolicy で順位を付けると攻撃対象から遠い手に差し替わり棋風が崩れる
（CLAUDE.md「やってはいけないこと」参照）。

**確認**: ログの `[HuntDivergenceStrategy] Best-move dodge:` 行。
spec は `docs/superpowers/specs/2026-04-11-hunt-divergence-strategy-design.md`。

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

指定した目差範囲（0.5〜10目）で僅差勝ちを目指す戦略。人間らしくない大損失手・humanPolicy≒0 の手を除外して、サボタージュ的挙動を防ぐ。対応盤面: 19路・13路（9路は持碁（9路）戦略へ分離）。

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
| jigo_force_sanrensei | false | ON で19路盤序盤に星打ちを強制（黒=三連星/白=2連星）。13路・9路は無効。黒が2子置いたコミット済みラインの中辺星等を白が妨害した瞬間、別ラインへpivotせず強制を打ち切り通常jigoに戻る。Stage 1 直後に対象を計算し非空なら Stage 2 をスキップして即着手。Spec: docs/superpowers/specs/2026-05-30-jigo-force-sanrensei-design.md |
| jigo_endgame_humanstyle | false | ON でヨセ段階（下記手数以降）は target 追従をやめ、目差が target_score 以上になった手番から HumanStyle 9段（rank_9d）へ委譲する。**ヨセの手抜きは相手から見て露骨**（1手の目数がほぼ確定していて手順も一本道なので、大きい場所を放置する選択が明らかに不自然）なので、それを止めるためのオプション。判定は Stage1 発行前・目差は前手のキャッシュ（1手ラグ）。**劣勢のうちは jigo を継続**（`lead < target_score` の jigo は target 最接近手＝実質最善手なので手抜きは起きず、deception の挽回も取りこぼさない）。**比較対象はユーザー設定の target_score であって deception の eff_target ではない**（phase1/2 の eff_target は負なので、それと比べると「設計どおり劣勢に留まっている状態」を到達とみなして即委譲する）。一度委譲したら戻らない（sticky＝`game._jigo_endgame_handoff`。手番ごとに往復するとかえって不自然＋委譲後は `_jigo_last_current_lead` が更新されないのでどのみち古い値で判定し続ける）。委譲先は素の9段（`{"human_kyu_rank": -8, "modern_style": True}`＝`first_impression_*` 等は渡さない）。ai_thoughts に `[Jigo→9d yose]` が前置される。副作用: 相手が弱いとヨセで素直に稼ぐため最終目差は target を超えて広がりうる。Spec: docs/superpowers/specs/2026-08-05-jigo-endgame-humanstyle-design.md |
| jigo_endgame_move | 150 | [19路] ヨセ委譲を開始する手数（120〜200・10刻み）。既定は deception phase3 開始手数と同じ |
| jigo_endgame_move_13 | 85 | [13路] 同上（55〜90・5刻み）。既定は共通規約 ceil(0.5×169)=85（phase3 開始 83 は5刻みに乗らないため）。19/13/9路以外の盤は設定キーを持たず ceil(0.5×盤面マス数) にフォールバック |

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

### 持碁（9路）戦略（Jigo9Strategy）

9路盤専用の独立戦略（`ai:jigo9`）。`JigoStrategy` を継承し generate_move を流用。9路に無関係な上級設定は `FORCED_SETTINGS` で無効化（`human_profile`→rank_9d固定 / `jigo_dynamic_rank`→false / `jigo_large_lead_delta`→inf / `jigo_equivalent_epsilon`→0.0）。deception は generate_move の `board_size==9` 分岐で9路スライダーを読む（13路機構 `_jigo_resolve_path_overrides` を `key_prefix="jigo9"` で共有）。既存 `ai:jigo` は19/13路専用（9路コードは削除）。

| パラメータ | デフォルト | 選択肢 | 備考 |
|---|---|---|---|
| target_score | 0.5 | 既存流用 | 狙う目差 |
| target_score_max | 5.0 | 5/10/15 | 9路は10目で実質勝勢のため5.0既定 |
| max_loss_per_move | 3.3 | 3.0/3.3/4.0/5.6/7.0 | 9路 HumanStyle NORMAL=3.3 |
| min_human_policy | 0.02 | (0.005..0.05) | humanPolicy 最低閾値 |
| jigo_mode | natural | natural/maintain | |
| jigo_deception | false | bool | deception 有効化 |
| jigo9_phase1_start | 6 | 4/6/8/10 | phase0→1 境界手数 |
| jigo9_phase2_start | 16 | 12/16/20/24 | phase1→2 境界手数 |
| jigo9_phase3_start | 30 | 26/30/34/38 | phase2→3（挽回開始）。早いほど挽回が間に合う |
| jigo9_phase1_target | -1.5 | -1.0/-1.5/-2.0/-2.5 | target_max=target+1.0 自動 |
| jigo9_phase2_target | -0.5 | -0.5/-1.0/-1.5 | 同上 |
| jigo_endgame_humanstyle | false | bool | ON でヨセ段階は HumanStyle 9段へ委譲（19/13路と共通のキー・挙動は上表参照） |
| jigo9_endgame_move | 30 | 22/26/30/34/38 | ヨセ委譲を開始する手数。既定は deception phase3 開始手数と同じ |

検証は GUI 実戦のみ（deception は trajectory 形成型で batch 評価不可）。CLI: `python -m katrain_debug --sgf <9路SGF> --move N --strategy jigo9`。Spec: `docs/superpowers/specs/2026-06-04-jigo-9x9-dedicated-mode-design.md`


## Parity9Strategy（`ai:parity9` / 一致率追随（9路））

9路専用。**終局レポートの AI 最善手一致率を絶対目標まで下げつつ勝ちきる**。ヨセ以降は
KataGo 最善手固定。2026-08-08 に設計を大きく入れ替えた（下記「改修 2026-08-08」）。

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `parity9_target_rate` | 目標の最善手一致率（**絶対値のみ**。相手の一致率では動かさない） | 20/30/40/50/60% | 0.4 |
| `parity9_min_winrate` | 着手後の勝率フロア（打つ側視点）＝**唯一の安全ゲート** | 50/60/70/80/90% | 0.7 |
| `parity9_max_loss_per_move` | 1手あたり損失キャップ（目）。cap はこれのみ | 0.5〜3.0 / 4.0 / 5.0 | **5.0** |
| `parity9_cost_slack` | 最安の外し手からの許容上乗せ（目）。このバンド内で humanPolicy 最大 | 0.0 / 0.3 / 0.5 / 1.0 / 2.0 | 0.5 |
| `parity9_endgame_move` | ヨセ手数閾値 | 22 / 26 / 30 / 34 / 38 | 30 |
| `parity9_unsettled_max` | ヨセ判定の未確定点上限（\|ownership\| < 0.5 の点数） | 4 / 6 / 8 / 10 / 12 | 8 |
| `parity9_yose_max_loss` | ヨセで許す1手損失（目）。0 で従来の完全固定 | 0.0/0.05/0.1/0.2/0.3/0.5 | **0.1** |
| `parity9_min_human_policy` | 採用候補の humanPolicy 下限 | 0% / 0.5% / 1% / 2% | **0.005** |

モジュール定数 `PARITY9_UNSETTLED_ABS = 0.5` / `PARITY9_MIN_VISITS = 10`（スライダーにしない）。
**削除**: `parity9_match_margin`（`parity9_target_rate` が置き換え）／`parity9_keep_margin`
（勝率フロアと冗長・下記「改修 2026-08-08b」）。

### 改修 2026-08-08b: スコア予算の撤去（実戦ログ `game_20260808_221839` 由来）

**`scoreLead` は komi 込みなので「lead > 0」は「勝率 > 50%」と同義**。したがって
`budget = max(0, lead − keep_margin)` は**手番の色に依存する**: 9路 komi 7 では白は
序盤からわずかに正、**黒は負**（実測・黒番実戦の depth 0〜8 で lead −0.22〜−0.04）。
黒番では予算 0 で早期 return するため序盤5手が問答無用で最善手に固定され、しかも
**勝率フロアが一度も評価されないまま「no budget」とログに出ていた**。

安全判定を**着手後の勝率フロアただ1つ**に統一し、`cap = parity9_max_loss_per_move`
とした。`parity9_has_admissible`（新純関数）が hp を見ずに候補の有無を判定するので、
spec §4.1 の「外すと決まるまで humanSL を撃たない」順序は保たれる。

| SGF | | Top1 | Top5 | 実損失 | acc |
|---|---|---|---|---|---|
| 校正局（白+26） | 撤去前 | 42.1% | 68.4% | 13.52目 | 81.5 |
| 校正局（白+26） | 撤去後 | 42.1% | **73.7%** | **12.35目** | **82.9** |
| 実戦（黒+3〜4） | 撤去後 | 76.0% | 96.0% | 0.90目 | 99.0 |

**一致率は動かない**（撤去前後で外し11手が同数）。目的は黒白の非対称の除去とログの
是正であって、一致率のレバーではない。

**序盤を塞いでいるのは予算ではなく勝率フロアだった**: 予算ゲートを撤去した状態でも
黒番実戦の move 1〜9 は落ちる（lead −0.21〜−0.09 ＝勝率約48%。同じログの
lead +2.07 → wr 80.3% の対応から逆算）。**9路 komi 7 の黒は開始時点が 50% ちょうど
なので、勝率を1%も下げたくないなら序盤は原理的に外せない**。ここを開けるには
「序盤に限り 45% 程度まで許す」という別の緩和（＝勝ちを落とすリスクを取る判断）が要る。

### 一致率は局面の余裕に比例する（n=2 の実測）

| 対局 | 手番 | 目差 | 判断数 | 外し | Top1 | 実損失 |
|---|---|---|---|---|---|---|
| 校正局 | 白 | +26（圧勝） | 19 | 11 | 42.1% | 12.35目 |
| 実戦 | 黒 | +3〜4（接戦） | 25 | 6 | 76.0% | 0.90目 |

**接戦で一致率が高いのは設計どおりの正しい挙動**（勝ちを最優先しているため）。
一致率を対局によらず一定にすることは「必ず勝つ」と両立しない。

**実戦で見えたヨセの扱い**: `unsettled=0`（未確定点ゼロ）が depth 18 から続いていたのに
ヨセ判定は `depth>=30 AND unsettled<=8` の AND なので手数ゲートが効かず、depth 20〜26 で
5手外していた。ただし **`unsettled=0` を「終局」の信号に使ってはいけない** — その対局は
決着と出てから**さらに30手打たれている**。AND を OR にすると depth 18 でロックされ外しが
7手→2手（一致率 約92%）に激減するので、**AND のまま維持**する。`endgame_move=30` は
49手の対局の61%地点で、コードベースの慣習（9路 `ceil(0.5×81)=41`）よりすでに早い。

### 改修 2026-08-08（校正局1局・白19判断の実測で駆動）

| 段階 | Top1 | Top5 | 実損失合計 |
|---|---|---|---|
| 改修前 | 52.6% | 73.7% | 11.04目 |
| ①候補プールを通常解析へ | 57.9% | 73.7% | **5.82目** |
| ②レートゲート＋cap5.0＋hp0.5% | 52.6% | 63.2% | 11.07目 |
| ③勝率フロア＋keep 0.0 | 36.8% | 52.6% | 21.23目 |
| ④コスト最安バンド（確定） | **42.1%** | 68.4% | **13.52目** |

1. **候補プールを Stage2 から通常解析（`cn.candidate_moves`）へ**。Stage2 は scoreLead を
   クリーンに保つため `wideRootNoise=0` で撃っており、9路では非最善手を 69〜86visits でしか
   読まない＝損失が**一貫して 1.3〜1.8目楽観的**に出る（実測 move 14: Stage2 B4 +3.24 /
   通常解析 B4 +4.59）。改修前の低い一致率は損失の過小評価で買っていたもので、①は実損失を
   **11.04 → 5.82目**に半減させた（一致率は 1手ぶん悪化＝偽の外しが1つ消えたため）。
   `relativePointsLost` は `GameNode` 側で既に打つ側視点に符号済み＝`sign` を掛けない。
2. **一致数差ゲート → レートゲート**（`parity9_rate_gate`）。旧ゲートは 0-0 で必ず閉じるため
   白の初手を落としていたが、そこが**盤面で最も原資の多い局面**だった（0.5目以内に人間らしい
   代替7手、しかも最善手 F6 の hp 0.194 < D4 の hp 0.485＝9段の第一感は代替手のほう）。
   さらに相手が KataGo 最善手に一度も一致しない対局（実測: 校正局の人間は全手番 opp=0）では
   追随目標が原理的に達成不能。
3. **スコア予算 → 勝率フロア**。`lead - keep_margin` は互角局面で必ず 0 になる（実測 move 2:
   白の勝率 82% なのにリード 0.99目 < margin 1.0 で予算 0）。候補の `winrate` は探索値＝相手の
   最善応手込みなので、「逆転されない」の判定にはこちらが正しい。追加クエリ0本。
4. **選択規則を「予算内で humanPolicy 最大」→「最安バンド内で humanPolicy 最大」**へ。前者は
   毎回予算を使い切る（③で 12手 21.2目）。実測では**高価な外しほど humanPolicy も低い**
   （4〜5目の手は hp 1.5〜7.9%、1目未満の手は hp 37〜60%）ので、安さを第1基準にすると
   コストと不自然さが同時に下がる（21.2→13.5目・Top5 52.6→68.4%）。

**この時点で「否定した」と書いた案（後に撤回）**: 「損失0の同値手をどのフェーズでも拾う」は
校正局19局面で `loss <= 0.05` の代替手が0手、ヨセ4手の最安代替も +8.85 / なし / +3.25 / なし
だったため在庫なしと結論した。**これは n=1 の過剰一般化で、下記「改修 2026-08-08c」で
撤回している**（校正局は38手で終わりヨセが4手しかない＝本当のヨセに入る前に終局していた）。

**9路の構造的な床**: 19判断のうち**5手は最善手の humanPolicy が 0.97 以上**（8/22/26/34/38）で
代替手が存在しない＝9段も同じ手を打つ。ここで一致するのは不自然ではないので、一致率を
20%台まで下げることは「人間らしさ」と両立しない。

**既知のトレードオフ**（既定値で残っている）: `min_human_policy=0.005` は hp 0.7% の手を、
`max_loss_per_move=5.0` は 4.9目の手を通す（実測 move 30 / move 16）。前者を 0.01、後者を 4.0 に
すると 52.6% / 約6.6目 になる。ユーザーが 42% ラングを選択したため既定は緩い側。

**ヨセ判定は「手数閾値 AND 未確定点上限」だが、ownership が取れなければ手数閾値だけに落ちる**（`parity9_is_endgame`）。Stage2 の ownership が None のとき（クエリ失敗・`_enable_ownership=false` を明示 `ownership=True` でバイパスし損ねた等）は AND を評価できないので、AND のまま失敗側（ヨセに入らない）へ倒すと「測れない＝永遠にヨセに入らない＝外し続ける」という危険側になる。安全な方向（ヨセに入って外すのをやめる）に倒すため、この場合は手数閾値だけでヨセ入りと判定する。

**校正記録（2026-08-06・9路実戦1局 `calibration-data/parity9/parity9-vs-human-20260806-white.sgf`）**: `parity9_unsettled_max=8` は実測で妥当（中盤の未確定点は10〜64で揺れ、ヨセ突入時は5）。`parity9_max_loss_per_move` は当初「1.5 だと発火4手の損失が天井に張り付き6手が候補なしで落ちる」ため 3.0 へ緩和したが、損失基準修正（`0ef0f32`）後の再計測でこの根拠自体は否定された（外し率はむしろ 1.5 で 16/19→17/19 と上振れ、3.0 は 15/19 のまま不変）。それでも 1.5 と 3.0 の差は修正後のほうが広い（1手→2手）ため 3.0 を維持。残り6手のブロック要因は解決済み: Stage2 は `wideRootNoise=0.0` で撃つため探索が1点に集中し、多くの局面で `PARITY9_MIN_VISITS`（`ai.py` のモジュール定数、GUI設定ではない）を超えるのは最善手だけになり非最善の代替候補が存在しない——この場合の「外さない」は正しい挙動。詳細: `docs/superpowers/specs/2026-08-06-parity9-strategy-design.md` §5。

設計: `docs/superpowers/specs/2026-08-06-parity9-strategy-design.md`

### 改修 2026-08-08c: 相手レートのブレーキ撤去 + ヨセロックの置換

実戦2局（`game_20260808_224752` = parity9・**白番**・相手が43〜54%一致してくる接戦 /
`game_20260808_225507` = jigo9）を比較し、ユーザーが jigo9 のほうが理想に近いと判断した。
**交絡に注意**: parity9 局は AI +0.07〜5.9目の接戦、jigo9 局は +12〜15目の快勝で、
相手の強さが違う。それを除いても構造的な差が2つあった。

**A. 実効目標のブレーキは実装ミスだった。** `eff_target = max(target_rate, opp_rate)` の
根拠にしたユーザー要件は「相手が強すぎて**全体目標以下では勝てない場合**は相手と同率程度で
あれば超えてよい」で、条件は「勝てない場合」。それは安全ゲート（勝率フロア）が既に処理して
いるので二重適用だった。実測で **30判断中5回**、安全性と無関係にゲートを閉じていた。
`eff_target = target_rate` に修正（`opp` はログ用に残す）。

**B. ヨセのハードロックを撤回し `parity9_yose_max_loss`（既定 0.1目）に置換。**
この局ではヨセロックが **31判断中16手＝52%** を最善手に固定しており、一致率が下がらない
最大の原因だった。jigo9 はヨセ帯で損失 0.00〜0.26 の手を打ち続けている。ダメ詰めや1目ヨセは
**手順が入れ替わっても目数が動かない**ので、0.1目の手を打つことは「ヨセを間違える」ことでは
ない。`in_yose` では `cap = min(max_loss, yose_max_loss)` に絞るだけで、勝率フロアと hp 下限は
そのまま効く。`yose_max_loss = 0` で従来の完全固定に戻る。

| 接戦局（白番30判断） | Top1 | Top5 | 実損失 | 外し |
|---|---|---|---|---|
| 修正前（実戦・31判断） | 約77% | — | — | 7（ゲート閉5・ヨセロック16） |
| A+B 後 | **63.3%** | 93.3% | 3.29目 | **11**（ゲート閉0・ヨセロック0、うちヨセ3手） |

ヨセの外し3手の損失は −0.03 / −1.27 / +0.02 ＝**実質ゼロコスト**。

**ヨセ在庫の実測（AI側・15判断）**: 代替手が `≤0.1` で4局面 / `≤0.2` で5 / `≤0.3` で6、
**代替手が存在しないのが6局面**（最善手の hp 0.94〜1.00・探索された手が1つだけ）。
0.1 → 0.3 に上げても +2手・約0.5目なので、接戦では割に合わない＝**既定 0.1 を維持**。

**残る制約**: 30判断中19が `no safe deviation`。この局は AI のリードが 0.07〜5.9目の接戦なので
勝率フロア（60%）が正しく効いている。**接戦で一致率が上がるのは「必ず勝つ」の帰結**で仕様。

## Enigma9Strategy（`ai:enigma9` / 難解（9路））

9路専用。序盤〜中盤は損失上限と勝率フロアの内側で「**相手が正しく応じることが最も難しい手**」
へ積極的に外し、相手の研究した定跡・手筋を無効化する。ヨセは lead − target の余剰だけを
外し予算にし、余剰が無ければ最善手で **2目勝ち〜持碁**を確保する。劣勢時は最善手で粘るだけ
（勝てない碁は僅差の負けでよい、が要件）。設計: `2026-08-10-enigma9-strategy-design.md`。

**難解さの尺度（目数スケールで合算）**: 候補ごとに子局面をプローブ（クリーン500visits +
humanSL 9段 humanPolicy 8visits・全並列）し、
`net = E + reply_rare + own_rare − max(0, 検証済み損失)` の最大の手を打つ
（最善手も同じ尺度でスコアし、`enigma9_net_margin` 以上上回る挑戦者だけ外す）。

- **E（期待お仕置き）** = humanSL 9段の応手分布で重みづけた相手の期待損失
  （応手損失は子局面解析から応手側視点・基準は visits>=10 の最善応手・1応手 8.0 目 cap）
- **reply_rare** = 「損失 0.3 目以下の十分な応手のうち hp 最大」の意外さ（hp 0.25 以上で 0）
  ＝要件「相手の最善応手の humanPolicy が低い手」の実装（十分な別解の見落とし防止つき）
- **own_rare** = 自手の humanPolicy の意外さ＝要件「humanPolicy が低い高スコア手」の実装。
  **ヨセでは重み 0＝この項を使わない**（`enigma9_own_rarity_weight`・spec 追記6・2026-08-22）:
  ヨセは E も reply_rare も候補間で横並びに潰れるので own_rare が net の順位をそのまま決め、
  **予算内で最も humanPolicy の低い手が機械的に選ばれる**（実測 校正局 move 53・白 lead+5.6:
  最善 E9〈E 0.19・hp 95.7%〉を差し置いて J8〈E 0.32・hp **0.1%**・net の +0.996 が意外さ〉を
  0.27 目払って採用＝罠の価値は E 差 0.13 目しかない）。own_rare は「相手の**研究した定跡・
  手筋**を外す」ための項で、知識が残っている序盤〜中盤の道具＝ヨセでは「人間が打たない手」に
  しかならない（jigo の `jigo_endgame_humanstyle` と同じ理由）。ヨセの外しは E と
  reply_rare＝**本物の罠**だけで正当化する。**非ヨセ手番はビット同一**（重み 1.0 のまま）。
  修正後の実測: move 53 は J8 net 1.05→0.10 < E9 0.22 で**最善手に戻る**、move 35 は
  E=1.76・検証済み損失 −0.03 目の**本物の罠**なので従来どおり外す。設定キーは増やさない
  （固定挙動）。**E が高ければヨセでも hp の低い手は打ちうる**（move 35 の E4 は hp 3.7%）＝
  完全に塞ぐなら候補への humanPolicy 下限が次の一手（未実装）
- **攻め合い1手差の積極形成**は専用検出なし＝「相手の並みの応手が大損する」局面は E が
  構造的に高く、安全ゲート（cap + 勝率フロア、どちらも相手最善応手込みの探索値）が
  「間違えなければ勝てる場合のみ」を担保する

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `enigma9_max_loss` | 1手あたり損失上限（目）。**互角では候補値の天井 1.8＝2目以上の損失手を封じる** | 0.3〜1.8 | 1.0 |
| `enigma9_large_lead_max_loss` | **勝勢時の勝負手損失上限（目）**。budget = lead − target が max_loss を超える間だけ cap をここまで緩和し、net の損失項を cost_weight = max_loss/budget に割引（`enigma9_spending_plan`）。ヨセに入ると無効 | 2/3/4/5/6/8 | **5.0** |
| `enigma9_min_winrate` | 着手後の勝率フロア（打つ側視点） | 20〜50% | 0.3 |
| `enigma9_net_margin` | 外しに要求する難解さの差（0=同点でも外す） | 0.0/0.2/0.3/0.5/1.0 | **0.0** |
| `enigma9_target_score` | ヨセの目標差（目）。勝勢予算とヨセ予算の両方の基準 | 0/1/2/3 | 2.0 |
| `enigma9_aim_jigo` | **ON で狙いを「持碁〜2目以内の負け」に差し替え**（優先度 持碁 > 2目以内の負け > それ超。target_score は無視・内部 target=`ENIGMA9_JIGO_TARGET`(-1.0) 固定＝許容帯 [-2,0] の中心でパリティ非依存。勝率フロア無効化＝安全条件は「cap <= lead−target＝着手後も target を割らない」の1本（中盤は `enigma9_aim_cap`・ヨセは既存予算）。lead<=target は最善手で維持/挽回。勝勢の削りは既存消費モード流用＝大差でも露骨な大損失手は打たない。削り切れない大差は僅差勝ちで終わりうる。spec 追記5） | bool | **false** |
| `enigma9_endgame_move` | ヨセ切替手数（AND の片側・sticky） | 22/26/30/34/38 | 30 |
| `enigma9_unsettled_max` | ヨセ判定の未確定点上限（AND の片側） | 4/6/8/10/12 | 8 |
| `enigma9_locality_stddev` | own_rare を「相手の直前手／KataGo 最善手」の2アンカー max Gaussian（σ=この値）で減衰させ、net の同点帯では最もアンカーに近い手を採る。0=OFF＝採用判断・解析条件とも従来とビット同一。9路は既定 OFF・GUI/config の不変条件維持のために露出（9路は問題なしとの報告） | 0/1.5/2/2.5/3 | 0（OFF） |
| `enigma9_locality_slack` | 同点帯の幅（目相当）。stddev>0 のときだけ効く | 0/0.2/0.3/0.5/1.0 | 0.3 |
| `enigma9_opening_humanstyle_moves` | **序盤の HumanStyle 9段委譲（2026-09-04）**。対局の手数 `cn.depth` がこの値未満の手番は難解の選択パイプラインに入らず `HumanStyleStrategy(human_kyu_rank=-8, modern_style=True)`＝rank_9d としてそのまま打つ（純関数 `enigma9_opening_handoff`・jigo の `jigo_endgame_humanstyle` の鏡像・非 sticky＝手数だけで決まる。分岐は盤サイズゲートの直後で ponder はこの手番では起動しない）。手数以上の手番は解析条件・採用判断ともビット同一。9路は既定 OFF・キー集合の不変条件のために露出 | OFF/1〜30 | 0（OFF） |

**own_rare の「応手自明」減衰（2026-09-01・9/13/19路共通・spec 追記11）**: `enigma9_net_score` の own_rare 項は `enigma9_own_rare_find_gate(find_hp)` で減衰する＝find_hp <= `ENIGMA9_OWN_RARE_FIND_FADE`(0.85) は 1.0（**ビット同一**）、0.85→1.0 で線形に 0。実測 `game_20260901_180139` move 36（13路白番・aim_jigo 消費モード）: B10 は E=0.03・find_hp=0.983（9段の正解応手 A10 が 98.3%）なのに own_rare 0.99 だけでnet 0.39 > 最善 B5 の 0.18 となり、0.94 目払って「誰でも正答できる手」に外した＝ヨセ（追記6・w_own=0）と同じ own_rare 支配の中盤版。reply_rare は find >= 0.25 で 0 に張り付き「それ以上自明」を罰しないのでここが唯一の穴だった。E・reply_rare は不変＝find が高くても E で勝つ本物の罠（同 move 38 C11: E=0.84・find=0.715・own_rare 抜きでもnet 0.50 > 0.02）はそのまま採る。線形ランプなのは find_hp の run 間分散 ±0.05〜0.09 で崖だと境界の採否が反転するため。回帰: `tests/test_ai_enigma9.py::TestOwnRareFindGate`。

**勝勢時の消費モード（追記1・2026-08-10）**: 初戦の実戦ログ `game_20260810_193156`（白番）で、
リード +6〜+38 の中盤後半が **cap 1.2 で admissible=0 の連続＝強制最善手**になり「一致率が
異常に高い・2目以上の損失手ゼロ」というユーザー報告が出た。対処は lead 予算の cap 緩和＋
**損失項の予算比例割引**（cap を広げるだけでは `net = 難解さ − 損失` の等価コストで 3〜5目の
勝負手が必ず負けるため）。`net = E + rarities − (max_loss/budget)·vloss`、cap =
clamp(budget, max_loss, large_cap)。budget→max_loss で cost_weight は連続的に 1 へ戻り、毎手
消費すると lead は target+max_loss 近傍へ収束＝2目差勝ちへ向かって余剰を難解さに変換する。
実測（復元 SGF `calibration-data/enigma9/enigma9-vs-human-20260810-white.sgf`）: move 21
（lead +12.6）で admissible 1→15・**F3（vloss 2.16・E=1.38・応手発見率 5.9%・wr 99.8%）へ外し**、
move 15 では 3目の候補が「高くても難解でない」（E 0.06・find 0.92）と正しく却下され最善
（それ自体 E 2.23 の罠手）を維持。互角（parity9 校正局 move 2）は Spend 非発火で従来どおり。

モジュール定数: `ENIGMA9_SHORTLIST=8` / `ENIGMA9_CHILD_VISITS=500` /
`ENIGMA9_HP_CHILD_VISITS=8` / `ENIGMA9_HUMAN_PROFILE=rank_9d` /
`ENIGMA9_POOL_MIN_VISITS=1` / `ENIGMA9_TRUSTED_VISITS=10` /
`ENIGMA9_REPLY_REF_MIN_VISITS=10` / `ENIGMA9_REPLY_MIN_VISITS=2` /
`ENIGMA9_PUNISH_CAP=8.0` / `ENIGMA9_ADEQUATE_LOSS=0.3` / `ENIGMA9_HP_BOOK=0.25` /
`ENIGMA9_W_REPLY_RARE=1.0` / `ENIGMA9_W_OWN_RARE=1.0` / `ENIGMA9_OWN_RARE_FIND_FADE=0.85`（own_rare の「応手自明」減衰の開始 find_hp・下記） / `ENIGMA9_MIN_BUDGET=0.05` /
`ENIGMA9_FAST_YOSE_MARGIN=0.5`（監視モードのヨセで Probe を省ける余剰の余裕・目） /
`ENIGMA9_PONDER_REPLIES=5`（着手後の先読み応手数＝humanSL 順 top-K・0で無効） /
`ENIGMA9_PONDER_WAVE2=2`（子プローブ wave2 まで温める応手数） /
`ENIGMA9_PONDER_LANES=3`（先読みジョブの同時実行本数） /
`PRIORITY_ENIGMA_PONDER=-50`（constants.py）

**着手時間の短縮（2026-08-11・精度不変・9路/13路共通・spec 追記3）**:
(1) **親 humanSL クエリの 8visits 化＋バッチ統合**＝`_probe_children(parent_hp=True)` で
子局面プローブと同時発行（旧実装は既定 visits=config max_visits(1000) の humanSL 解析を
逐次で待っていた。humanPolicy は root NN の出力で visits に依らないが **run 間では
TensorRT バッチ非決定性で揺れる**〈別プロセス実測: 1000v 同士でも max|Δ|=0.086・
上位10手の順位入替。8v vs 1000v の差はそのレンジ内〉＝visits を落としても既存分散に
上乗せなし)。
(2) **着手後の先読み（ponder）**＝`_start_ponder`/`_ponder_worker`。着手を返す直前に
選択手の humanSL プローブ（相手の応手分布）から応手 top-5（`enigma9_ponder_order`＝humanSL 順。
**2026-08-27 追記9で KataGo 本命1+humanSL 2 から変更**、下記）を選び、使い捨て複製ゲームで
wave1: 応手後局面を GUI の通常解析と同条件（visits/ownership=config 解決）で解析 → wave2:
上位2手についてその top-8 候補（order 順）の子プローブ（clean 500v + humanSL 8v）を
`_probe_children` と同条件で発行。ジョブは `enigma9_ponder_jobs` の価値順（root#1, root#2,
wave2#1, root#3, wave2#2, root#4, root#5）を `PonderLanes` で同時3本ずつ流す。
**結果は全部捨てる＝判定影響ゼロ**。
発火は 自分=AI かつ 相手=人間 のときだけ（`_ponder_applies`。デバッグスタブ／バッチ評価／
AI 同士では発火しない）。残骸の掃除は2段: 主経路 `Game._cancel_enigma_ponder`（**相手の
着手が入った瞬間**に terminate。相手が消化前に応手すると実クエリが温めと GPU を取り合い
1.6→4.4 秒に伸びた実測への対処）＋保険 `_cancel_ponder`（generate 冒頭・GUI を経ない経路用）。
(3) **per-move 時間ログ** `[Enigma13Strategy] 着手決定に X.X 秒`（OUTPUT_INFO＝debug_level 0 でも
ゲームログに残る）。
実測（13路・校正13路局の白番・NN ウォーム）: generate 8局面×2run 平均 1.04→0.89 秒、
先読み**的中時**は次手番の 通常解析+generate 0.92〜1.09 → **0.35〜0.48 秒**
（プローブバッチ 0.45〜0.64 → 0.08〜0.09 秒）。外れた場合は従来どおり。

**盤面監視モードのヨセの即応（2026-08-23・精度不変・spec 追記7）**: 秒読みのある実戦
（`board_watch` で対局アプリを監視している間）向けに、ヨセの追加クエリを2方向で削る。
実測の内訳（`game_20260823_024656.log`・9路・監視モード）は ヨセ前 0.0〜0.4 秒に対しヨセ
0.7〜1.7 秒で、**支配項はヨセ判定クエリ（Probe＝2000visits・ownership=True・wRN=0）の 1.1 秒**。
応手先読み（`_maybe_board_watch_prefetch`・ownership なし）では ownerMap の有無が違って
別のキャッシュエントリになるため1秒も速くならない。
(1) **飽和帯では Probe を撃たない**（`enigma9_yose_probe_skippable` / `_fast_yose_lead` /
`ENIGMA9_FAST_YOSE_MARGIN`=0.5）＝cap は `min(max_loss, lead − target)` なので、余剰が
`max_loss + margin` 以上なら cap は lead の値によらず max_loss ＝ **採用判断はビット同一**の
まま追加クエリ 0 本にできる。lead は通常解析 root の scoreLead（wRN=0.04＝Probe の wRN=0 より
僅かに揺れるぶんが margin）。**接戦（余剰が `max_loss + margin` 未満＝lead がそのまま予算に
なる帯）は従来どおり Probe を撃つ**＝目差が予算を決める局面の精度は落とさない。適用は
ヨセ sticky 後だけ（ヨセ突入の判定には ownership が要る）× `game.board_watch_active` が
真のときだけ。実測ログのヨセ14手番は lead 5.77〜34.48・cap 14本とも 1.60＝全部が飽和側。
(2) **接戦で残る Probe は先読みで温める**＝戦略が撃った手番に `game.board_watch_probe_warm` を
立て、`_board_watch_prefetch_worker` が応手 top-K の子局面へ**同条件**（ownership=True・
wRN=0・visits 既定）のクエリを1本ずつ足す（結果は捨てる＝判定影響ゼロ・的中率 top-5 68.7%）。
監視 OFF では `_stop_board_watcher` が `board_watch_active` / `board_watch_prefetch_replies` /
`board_watch_probe_warm` を戻す。ログは `Endgame budget: lead~… (watch: probe skipped)`。

**盤面監視モードの先読みの再設計（2026-08-27・精度不変・9/13/19路共通・spec 追記9）**:
ユーザー要望「難解の監視対局（特に13路）の着手をさらに速く」。今日の13路監視対局
（`game_20260827_155133`・70手）は 1手の root 解析＋`着手決定` が中央値 **2.1 秒**（ヨセ前 1.85 /
ヨセ 2.2。先読み的中 0.2〜0.9・外れ 2.4〜3.0）。原因3つとも解析条件・採用判断はビット同一のまま直した。
(1) **監視フラグが新規対局で落ちるバグ**: `_do_new_game` は `Game` を作り直すので
`board_watch_active` / `board_watch_prefetch_replies` が初期値に戻るのに、監視スレッド（kind="game"）は
生き続ける。セッション2局目では追記7の Probe 省略が一度も発火せず（lead 16〜17 なのに `probe skipped`
0件＝ヨセ31手 × Probe 中央値 1.1 秒）、応手先読みも 0 本だった。`board_watch.apply_game_watch_flags` を
`_do_board_watch_start` と `_do_new_game`（kind=="game" のとき）の両方から呼ぶ。
(2) **温めの一本化**: 1局目は逆に ponder 3本＋応手先読み 5本＋自ノード解析＝2000visits の root 9本が
横並びで走り、アプリの約 2.8 秒（考慮時間の下限推定・中央値）では何も温まり切らず的中 28%。
`_maybe_board_watch_prefetch` は `_enigma_ponder_owner == node.move.player`（ponder がこの着手で
発火済み）なら撃たない。ponder が発火しない手番（早期 return）は従来どおり先読みが担当し、
`board_watch_probe_warm` の Probe 温めは ponder 側の root ジョブにも同条件で足した。
(3) **選手を humanSL 順に**: 監視対局3局 148局面をオフライン再解析（`ponder_pick_probe.py`）した
実際の応手の的中率は KataGo visits 順(500v) top-1/3/5/8 = 18.9/38.5/47.3/55.4%、2000v 順 top-5 42.6%、
humanSL 9d 全盤順 top-1/3/5/8 = **35.1/53.4/62.2/74.3%**、旧 K1+H2 = 50.0%（局別 48/20/71%）。
このアプリは KataGo の PV でなく humanSL 順で打つ。KataGo 本命は humanSL 6番手（+6pt）より
寄与が小さい（K1 単独 18.9% のうち humanSL 1位と重なるのが 15.5%）ので外した。
9路も同じ傾向（2026-08-27 追試・9路 Enigma9 監視対局5局 130局面）: KataGo visits順 top-1/3/5/8 = 23.8/40.8/53.8/69.2%、humanSL 9d 全盤順 top-1/3/5/8 = 60.8/**69.2**/76.9%、旧 K1+H2 = 56.2%（局別 84/48/83/21/52%＝アプリの局ごとの振れが大きい）。19路は監視対局のログが無く未計測（機構は共通・root 2000v が重いぶんレーン順の「上位から温まり切る」が効く側）。
(4) **自ノード解析を後回し**: 着手直後の自ノード 2000visits 解析（1.6〜2.1 秒）が温めと GPU を
分け合っていた（KataGo は priority で並べ替えるだけで同時実行を絞らない）。監視モードで ponder が
armed なら `Game.play` は fast（100v）だけ出し（`_enigma_ponder_defers_own_analysis`）、フルは
ponder の own ジョブが温めの後に発行（相手が先に打てば fast のまま＝表示だけの差）。温めを
1本も出せない手番はその場でフル解析（`issue_own_now`）。
GPU 予算の目安: 2000visits ≒ 1 本・4 本で飽和（1本 1250v/s・4本 2500v/s）、アプリ考慮時間の下限推定
中央値 2.8〜4.8 秒 ≒ 7〜12k visits ＝ root 5本（10k）がちょうど収まる規模。
回帰: `tests/test_ai_enigma9.py`（TestPonderOrder/Jobs/Lanes/Worker/WorkerFallback 14件）、
`tests/test_board_watch_prefetch.py`（prefetch の譲り・fast 解析・フラグ復元 9件）。
GUI 実戦での確認: 2局目以降のログに `(watch: probe skipped)` が出る／`Ponder: warming replies`
が5手／ponder が発火した手番に `board_watch prefetch:` が出ない／的中率は `ponder_pick_probe.py`
と同じ集計で測れる。

**終局帯では難解さの選択をしない（2026-08-28・9/13/19路共通・spec 追記10）**: area scoring
（chinese）では終局後も自陣埋めが 0 目損の候補として並ぶので KataGo の最善手が pass に
ならず、旧実装（`best_gtp == "pass"` のときだけパス）は「最も難解な 0 目損の埋め手」を
選び続けた（実測 `game_20260828_064054` move 57・白 AI・lead +5.65: pass は 3位・損失 0.07 目、
0 目損の候補 25 手 → H1 へ外し。`game_20260828_065952` move 82: pass 17位・損失 0.2 → A9）。
判定は **pass が KataGo 候補に居て損失 < `_AREA_PASS_MARGIN`(0.5)**（＝盤上に 0.5 目以上の
手が無い帯）のときだけ走り、その手番は難解さの採点（子プローブ）に入らない:
(1) 相手が直前にパス → pass の損失 < 0.5 ならパス（クエリ0本）、そうでなければ ownership を
1本撃ち（ヨセ Probe と同条件・2000v・wRN=0）**全点 |o| >= `ENIGMA9_SETTLED_ABS`(0.9) ならパス**
（`enigma9_board_settled`。pass が大損に出るのは chinese ルールが未取り込みの死石を生きと
数えるためで、終局すれば ownership どおりに数えられる＝実測 `065952` @82+4: pass 126 目損なのに
全81点 |o| >= 0.97。旧実装は白がパスし続ける中で死石を 25 手かけて1子ずつ取り込んだ）、
未決着点があれば最善手（外しはしない＝惑わす相手はもう居ない）、(2) humanSL 9d（プローブバッチの親 humanSL と
同条件の 8visits・`_probe_children([], ..., parent_hp=True)`）の最上位が pass → パス
（`enigma9_terminal_pass`＝他5戦略の `_area_scoring_should_pass` と同じ `_pass_preferred`）、
(3) 9d の最上位の盤上の手が KataGo 候補で損失 < 0.5 → その手（`enigma9_terminal_move`）、
(4) それ以外は最善手。**pass の損失が 0.5 以上の手番はビット同一**。
「PV に pass が現れたらパス」は却下: PV の偶数手目の pass は**相手の**パスで、実測
`065952` move 74/80 は PV `A5 pass A3 pass …` なのに自分の pass は 124〜126 目損
（chinese ルールでは死石の取り込みが残っている）。「pass の損失だけ」も却下（ダメが 13 個
残っていても 0.10 目＝2026-08-06）。「humanPolicy だけ」も却下（同 move 80 は 9d が H4
99.5% で pass 0.0%＝結果は正しいが、pass が大損の局面で目数の裏付けなしに 9d を信じることになる）。
実測（katrain_debug・改修後）: 064054@57 → **J3**（9d 36.1% > pass 19.9%・loss 0.03・
着手決定 0.0 秒）／065952@82 → **J8**（9d 52.8%・pass 0.0%・loss 0.18）／帯の外
（065952@80・065438@71・064054@55＝pass 損失 33〜126 目）は従来どおり最善手。
既知の柔らかい縁: pass 損失は run 間で ±0.2 動く（同一局面で 0.07/0.08、0.20/0.37）ので
0.5 近傍の手番は run によって帯の内外が入れ替わる＝外れた run は従来の外し（0 目損の
埋め手）に戻るだけで危険側には倒れない。盤面監視モードではアプリ側のパスは注入されない
（盤が変わらないので検出できない）ため (1) は効かず、(2)(3) が終局まで運ぶ。
終局まで自動進行させた実測（enigma9 が両者・`finish_game.py`）: 接戦 064054@57 は J6/A7/W pass/
A6/J3/B8/G7/B pass/W pass の9手（settled 規則を足した後は J6/A7/W pass/**B pass** の4手）で終局、
大差 065952@82 は J8→白 A1→G8→白 D1→F5→白 pass→**黒 pass**（settled 規則・1.1 秒）で終局＝旧実装は
白がパスし続ける中 25 手以上死石を取り込んだ。
回帰: `tests/test_ai_enigma9.py` `TestTerminalHelpers` / `TestTerminalEndToEnd`（21件）。

**二段の漏斗と同深さ検証**（2026-08-10 実測で確定）: 9路の通常解析は visits を 1〜3 手に
集中させるため、`visits>=10` のプールでは外し候補が 0〜1 手しか残らない（実測 move 8:
74手中2手）。プールは `visits>=1` まで広げ、**採否と net の損失は子局面プローブの検証値**
（最善手の子局面 root との scoreLead 差）で確定する。浅い候補の生 loss は打つ側に楽観的
＝「生 loss > cap ⇒ 真 loss > cap」なので事前足切りの向きは安全、偽に安い蜃気楼は検証
cap が落とす（実測 move 2: 生 0.15 → 検証 0.29）。**1visit の生 loss が悲観側に壊れて
足切りされる手は救えない**（全手プローブは 15〜20 秒/手で却下）＝既知の限界。

**検証（2026-08-10・校正局黒25判断のバッチ）**: Top1 56%（=44% 外し）・Top5 96%・
平均損失 **0.03目**（1局合計 ~0.75目）・acc 99.0。単一局面: move 2 で F7
（own_hp 10%・応手見つけやすさ 17%・検証損失 0.29）へ外し / move 8 は見合う手が無く最善 /
move 40（+4.4 リード）はヨセ予算内に候補なしで最善 / move 39（劣勢白）は即 securing。

## Enigma13Strategy（`ai:enigma13` / 難解（13路））

13路専用。**実装は Enigma9Strategy と共有**（`ai.py` の `Enigma13Strategy` は
`BOARD_LEN` / `KEY_PREFIX` / `LABEL` / `SETTING_DEFAULTS` を差し替えたサブクラスで、
`generate_move` はオーバーライドしない＝選択パイプライン・二段の漏斗・同深さ検証・
勝勢時の消費モード・ヨセ予算・フェイルセーフ・モジュール定数（`ENIGMA9_*`）は
すべて 9 路版と同一）。sticky ヨセフラグは `game._enigma13_endgame`、ログタグは
`[Enigma13Strategy]`。設計: `2026-08-10-enigma9-strategy-design.md` **追記2**。

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `enigma13_max_loss` | 1手あたり損失上限（目）。「2目以上打たない」は挽回が難しい9路の要件で、13路は悪手フィルタ比（3.3→5.6）に合わせ候補天井 3.0 | 0.5〜3.0 | **1.5** |
| `enigma13_large_lead_max_loss` | 勝勢時の勝負手損失上限（目）。jigo の 13/19 路既定と同値 | 3/4/5/6/8/10 | **8.0** |
| `enigma13_min_winrate` | 着手後の勝率フロア（打つ側視点） | 20〜50% | 0.3 |
| `enigma13_net_margin` | 外しに要求する難解さの差（0=同点でも外す） | 0.0/0.2/0.3/0.5/1.0 | 0.0 |
| `enigma13_target_score` | ヨセの目標差（目）。勝勢予算とヨセ予算の両方の基準 | 0/1/2/3/5 | 2.0 |
| `enigma13_aim_jigo` | ON で狙いを「持碁〜2目以内の負け」に差し替え（9路版 `enigma9_aim_jigo` と同一機構・spec 追記5） | bool | **false** |
| `enigma13_endgame_move` | ヨセ切替手数（AND の片側・sticky）。13路の対局長（〜120手）へスケール | 55/65/75/85/95 | **75** |
| `enigma13_unsettled_max` | ヨセ判定の未確定点上限（≒169点の10%） | 8/12/16/20/24 | **16** |
| `enigma13_locality_stddev` | **局所性（2026-08-25・spec `2026-08-25-enigma-locality-design.md`）**。own_rare（自手の意外さ）を「相手の直前手／KataGo 最善手」の2アンカー max Gaussian（σ=この値）で減衰させ、net の同点帯では最もアンカーに近い手を採る。0=OFF＝採用判断・解析条件とも従来とビット同一。実測 13路（白50手×3run平均）: dist(選択手, 直前の相手手)>=4 が off 18.67→σ3 14.00→σ4 13.67、dist(選択手, KataGo最善手)>=4 が off 25.33→σ3 18.00（−29%）→σ4 20.00（−21%）と一貫して減少。mean_ptloss は off 1.739→σ3 1.710（ノイズ内）→σ4 1.780（σ3比 +0.070 は実差でσ4が悪化）。point_loss 5.9〜7.4・チェビシェフ距離5〜10の遠い罠3手番はσ3 の ON でも `Band: 1`（帯に対抗馬なし）で全件そのまま選択され保持された | OFF/2/2.5/3/4/5 | **0（OFF）**・推奨 **3.0** |
| `enigma13_locality_slack` | 同点帯の幅（目相当）。stddev>0 のときだけ効く。帯の中で prox 最大の手を pick し、**pick 自身が最善 net + margin 以上**のときだけ外す。slack は net 単位。勝勢時の消費モードでは loss 項が cost_weight で割引されているので、0.3 net ≒ 0.3/cost_weight 目の生損失差まで帯に入る（cap で有界）。raw 目単位の帯にする案は 19路 3run 再測時の検討項目 | 0/0.2/0.3/0.5/1.0 | 0.3 |
| `enigma13_opening_humanstyle_moves` | **序盤の HumanStyle 9段委譲（2026-09-04・ユーザー報告「13/19路の序盤 15〜25 手で珍しすぎる手を打ちすぎる」が起点）**。対局の手数がこの値未満の手番は難解の選択に入らず rank_9d（modern_style）として打つ（機構は `enigma9_opening_humanstyle_moves` と同一・難解＋も `generate_move` 非オーバーライドなので同名キーで継承）。根拠は実測 2026-09-03（13路監視対局 29 局・KataGo 再解析）: 序盤（手数<20）は E がどの候補も ≈0 で own_rare だけが順位を決め、hp<0.025 の点へ外しても相手の直後応手の実損失は 0.17 目（1目以上の失着 1%）＝騙せていない。既定 20 はその手数帯をそのまま覆う値。手数以上の手番はビット同一 | OFF/1〜30 | **20** |

CLI: `python -m katrain_debug --sgf <13路SGF> --move N --strategy enigma13`（batch 可）。
**13路の実戦校正は未実施**（GUI 実戦ログ `[Enigma13Strategy]` と batch 3-run 平均で行う）。

## EnigmaPlusMixin＝難解＋（`ai:enigma9plus` / `ai:enigma13plus` / `ai:enigma19plus`）

9/13/19路それぞれ専用。**基底の難解に `EnigmaPlusMixin` を先置きしたサブクラス**（`Enigma9PlusStrategy` /
`Enigma13PlusStrategy` / `Enigma19PlusStrategy`。設定キー接頭辞 `enigma9plus_` / `enigma13plus_` / `enigma19plus_`、
sticky ヨセフラグ `game._enigma{9,13,19}plus_endgame`）で `generate_move` は非オーバーライド。差分は2つ。
(1) **罠探索の拡張** `_shortlist`＝プローブする挑戦者を安い順 7 手＋高い帯から等間隔に `probe_extra` 手
（追記12-2・先読み wave2 も同期）。(2) **ΔE 床** `_filter_challengers`＝スコアリング済みの挑戦者を選択関数に渡す前に
「E − 最善手の E >= `min_delta_e`」または「vloss <= `cheap_loss`」に絞る（純関数
`enigma9_delta_e_filter`・落とした候補は `DeltaE filter: dropped …` ログ）。既存の難解 9/13/19 路は
基底フックが no-op でビット同一。設計と実測: `2026-08-10-enigma9-strategy-design.md` **追記12**
（2026-09-02。13路7局154手番で E は較正済み〈実損失 ≈ 1.06×E〉、ΔE<0.2 の外し 20 手が 29.6 目を
払って realized gain −0.52＝rarity だけで払った外し。ログ再適用で 200 外し中 37 手が変わり、払う
vloss 210→180 目・予測 E 265→268）。sticky ヨセフラグは `game._enigma13plus_endgame`。

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `enigma13plus_min_delta_e` | 外しに要求する E の上積み（目）＝選択手の E − 最善手の E の下限。**0（OFF）で難解（13路）と同一挙動** | OFF/0.1/0.2/0.3/0.5 | **0.2** |
| `enigma13plus_cheap_loss` | この検証済み損失以下の外しは床を免除（序盤の定跡外し・最善手より良い手を残す）。大きくすると難解（13路）に近づく | 0/0.2/0.3/0.5/1.0 | **0.3** |
| `enigma13plus_probe_extra` | **罠探索の拡張**（spec 追記12-2）。子局面プローブの挑戦者を「安い順 7 手」＋「残りの admissible 候補から loss の範囲で等間隔にこの本数」にする（`_shortlist` → `enigma9_shortlist_spread`）。従来は cap 5 目の手番でも 2 目より高い手を調べておらず（118手番で最大 loss/cap 中央値 0.38）、E>=2 の罠は高い帯に多い（vloss<0.3 で 6%・4目超で 21%）。代金の上限は不変＝同じ予算でより大きい罠を net 比較に乗せる。**先読み wave2 も同じ規則で温める**（`_ponder_wave2_targets`・cap は予測局面の root lead から消費モードの式で近似）ので的中時の即着手は保たれる。コールド実測 **+0.8 秒/手**（katrain_debug 13路 1.2→2.0 秒。先読み的中時は乗らない）。重ければ 2。0 で従来の 8 手 | 0/2/4/6/8 | **4** |
| 他11項目（`enigma*plus_max_loss` 〜 `enigma*plus_opening_humanstyle_moves`） | 基底の難解（同じ盤）の同名項目と同じ意味・同じ候補値・同じ既定（テスト `test_base_options_are_shared_with_the_base_strategy` で固定）。ユーザーローカル config は基底の現在値を写してある（9路: max_loss 1.6・large 6.0・min_wr 0.25・target 0.2・aim_jigo true / 13路: max_loss 1.6・target 1.5 / 19路: max_loss 2.6・endgame 180・locality 3.0） | — | — |

**盤サイズ別の校正状況（追記12-3／12-4・2026-09-02）**: 13路は実対局 難解13局 vs 難解＋14局（後半 15 局は交互）で E 平均/手 1.66→1.84（z 0.7・有意でない）・**相手の実損失/手 2.25→3.23（+1.0・局平均 z 1.9・pooled z 2.4、交互 15 局だけなら z 2.6〜2.7）**・>=2目の失着 41%→54%・vloss/手 0.93→0.85（同じ代金で回収 2.4→3.8 倍）・着手中央 0.35→0.40 秒（spec 追記12-5・2026-09-03＝13路は校正済み扱い）。**9路は交互対局 難解6局 vs 難解＋5局で利点を確認できず**（E 1.74→1.84〈z 0.3〉・外し率 35%→33% 不変・vloss 0.60→0.36。実損失は測れる手番が 1局 3〜13 で崩壊局 1 局が平均を支配＝比較不能。spread 発火 3〜7 手番/局、ΔE 床は選ばれない候補しか落とさない）＝**9路の既定は難解のまま・校正は打ち止め**（spec 追記12-4）。**19路は 13路の値を流用で未校正**（ログなし・候補プールが最大なので spread の余地は構造上最大の見込み。probe 1本が重いぶん `probe_extra` 4 のコールド増分は 13路の +0.8 秒より大）。

モジュール定数: `ENIGMA9_MIN_DELTA_E=0.2` / `ENIGMA9_CHEAP_LOSS=0.3` / `ENIGMA9_PROBE_EXTRA=4`。
CLI: `python -m katrain_debug --sgf <SGF> --move N --strategy enigma9plus|enigma13plus|enigma19plus`。
**実対局での realized 再計測は未実施**（測り方は追記12 実測1＝ログの lead 差分・KataGo 不要）。

## Enigma19Strategy（`ai:enigma19` / 難解（19路））

19路専用。**実装は Enigma9Strategy と共有**（`ai.py` の `Enigma19Strategy` は
`BOARD_LEN`=19 / `KEY_PREFIX`="enigma19" / `LABEL`="Enigma19" / `SETTING_DEFAULTS` を
差し替えたサブクラスで、`generate_move` はオーバーライドしない＝選択パイプライン・
二段の漏斗・同深さ検証・勝勢時の消費モード・ヨセ予算・フェイルセーフ・モジュール定数
（`ENIGMA9_*`）はすべて 9/13 路版と同一）。sticky ヨセフラグは `game._enigma19_endgame`、
ログタグは `[Enigma19Strategy]`。設計: `2026-08-10-enigma9-strategy-design.md` **追記4**。

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `enigma19_max_loss` | 1手あたり損失上限（目）。悪手フィルタは13路と同じ NORMAL=5.6 だが、盤が広く挽回機会が多いので13路（1.5/天井3.0）から一段開ける。5.6 までは開けない＝「難解だが悪手ではない」帯 | 0.5〜4.0 | **2.0** |
| `enigma19_large_lead_max_loss` | 勝勢時の勝負手損失上限（目）。jigo の 13/19 路既定と同値 | 3/4/5/6/8/10 | **8.0** |
| `enigma19_min_winrate` | 着手後の勝率フロア（打つ側視点） | 20〜50% | 0.3 |
| `enigma19_net_margin` | 外しに要求する難解さの差（0=同点でも外す） | 0.0/0.2/0.3/0.5/1.0 | 0.0 |
| `enigma19_target_score` | ヨセの目標差（目）。勝勢予算とヨセ予算の両方の基準 | 0/1/2/3/5 | 2.0 |
| `enigma19_aim_jigo` | ON で狙いを「持碁〜2目以内の負け」に差し替え（9路版 `enigma9_aim_jigo` と同一機構・spec 追記5） | bool | **false** |
| `enigma19_endgame_move` | ヨセ切替手数（AND の片側・sticky）。jigo の19路ヨセ委譲既定・deception phase3 開始と同じ150 | 120/135/150/165/180 | **150** |
| `enigma19_unsettled_max` | ヨセ判定の未確定点上限（≒361点の10%） | 24/30/36/42/48 | **36** |
| `enigma19_locality_stddev` | 13路と同じ機構（own_rare の2アンカー減衰＋同点帯タイブレーク）。0=OFF＝採用判断・解析条件とも従来とビット同一。実測 19路（`tests/data/ogs.sgf` 白56手・**1run のみ**）: dist(選択手, 直前の相手手)>=4 が off 24→σ5 17 と減少方向だが `mean_ptloss` は 0.312→0.519（+0.207・run間ノイズ閾値±0.05を大きく超える）・`total_loss` も 17.45→29.08 とほぼ倍増。増加は終盤の数手番（move_num 94/100/108 付近）に集中しており、個別再現では3手番とも `Band: 1`（同点帯に対抗馬なし）で局所性タイブレーク自体は発火していない。**原因は未特定**（Band=1 は局所性が効かなかった証拠にならない＝own_rare減衰はBand=1でもnetを変える。単発runの+11.6目は想定ノイズの約4倍でOFFの2本目も未取得。3run再測=OFF最低2本まで結論しない）。**19路は方向確認のみ・未校正・要3run再測**（本タスクのスコープ外） | OFF/3/4/5/6/7 | **0（OFF）** |
| `enigma19_locality_slack` | 同上（13路と同じ意味）。slack は net 単位。勝勢時の消費モードでは loss 項が cost_weight で割引されているので、0.3 net ≒ 0.3/cost_weight 目の生損失差まで帯に入る（cap で有界）。raw 目単位の帯にする案は 19路 3run 再測時の検討項目 | 0/0.2/0.3/0.5/1.0 | 0.3 |
| `enigma19_opening_humanstyle_moves` | 13路と同じ機構（序盤 N 手を rank_9d で打つ・難解＋も継承）。19路は実戦ログ無し＝既定 20 はユーザーの体感（序盤 15〜25 手）に合わせた値で**未校正** | OFF/1〜30 | **20** |

CLI: `python -m katrain_debug --sgf <19路SGF> --move N --strategy enigma19`（batch 可）。
**19路の実戦校正は未実施**（GUI 実戦ログ `[Enigma19Strategy]` と batch 3-run 平均で行う）。

## Mimic13Strategy（`ai:mimic13` / 擬態（13路））

13路専用。**相手より低い AI 最善手一致率を保ったまま勝つ**。設計: `2026-09-17-mimic13-strategy-design.md`。
`Mimic13Strategy(Enigma13Strategy)` が `_generate_move` を上書き（プローブ条件・E・先読み・終局帯は難解と共有。
sticky ヨセフラグ `game._mimic13_endgame`・ログタグ `[Mimic13Strategy]`）。

`price = max(0, vloss) − (E − E_best)`。λ = lead < −1.0 → 0 ／ 余剰（lead − reserve）<= 0 → free_loss ／
余剰 > 0 → min(max_loss, max(free_loss, 余剰 × spend_rate))。資格（自然 or 罠）あり・price <= λ の最安、
`cost_slack` 以内の帯は hp 最大。ハード条件は vloss <= max_loss と着手後勝率 >= min_winrate（検証値）。

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `mimic13_max_loss` | 1手の損失上限（検証済み・目）＝λ の天井 | 0.5〜5.0 | 2.0 |
| `mimic13_reserve` | 確保するリード（目）。余剰 = lead − これ。ヨセの 9段委譲の条件にも使う | 0〜10 | 3.0 |
| `mimic13_spend_rate` | 1手で余剰の何割まで払うか | 0.1/0.25/0.5/1.0 | 0.25 |
| `mimic13_free_loss` | 余剰が無くても払う price（目） | 0〜0.5 | 0.3 |
| `mimic13_min_winrate` | 着手後勝率フロア | 30〜50% | 0.40 |
| `mimic13_dominant_hp` | 最善手の hp がこれ以上なら外さない（罠も不可・プローブ0本） | 60〜95% | 0.8 |
| `mimic13_min_human_policy` | 自然な外しの hp 下限（絶対値） | 1〜10% | 0.05 |
| `mimic13_natural_ratio` | 同（第一感トップ比） | 0.1/0.2/0.3/0.5 | 0.2 |
| `mimic13_trap_min_delta_e` | 罠とみなす ΔE（目）。99=OFF | 0.3/0.5/1.0/1.5/OFF | 0.5 |
| `mimic13_cost_slack` | price の同値帯（帯の中は hp 最大） | 0〜1.0 | 0.3 |
| `mimic13_probe_extra` | 罠探索で高い帯から足すプローブ数 | 0/2/4/6 | 4 |
| `mimic13_endgame_move` | ヨセ切替手数（AND の片側・sticky）。**85 未満は委譲先 HumanStyle が hp 重みのランダム選択** | 65〜105 | 85 |
| `mimic13_unsettled_max` | ヨセ判定の未確定点上限 | 8〜24 | 16 |

モジュール定数: `MIMIC_BEHIND_LIMIT=-1.0` / `MIMIC_TRAP_MIN_HP=0.005` / `MIMIC_SHORTLIST_NATURAL=4` /
`MIMIC_SHORTLIST_CHEAP=4`（プローブは最善手＋最大 12 手）。プローブ条件は `ENIGMA9_*` を共有。

**各スライダーを動かしたときの挙動**（上げる/下げるの両側）は GUI の AI 設定画面のヘルプ `aihelp:mimic13`（jp/en の
`.po`・13 スライダーぶん＋調整の目安）と、マニュアル `docs/manual/src/06d_ai_parity.html#ai-mimic13` の表に書いてある
（**スライダーを足す・意味を変えるときは3箇所とも更新する**: この表 / `aihelp:mimic13` / マニュアルの表）。調整の目安:
一致率をもっと下げたい → `reserve`↓・`spend_rate`↑・`max_loss`↑・`dominant_hp`↑・`endgame_move`↑（勝ちの安全度や自然さと引き換え）／
接戦を落とす → `reserve`↑・`min_winrate`↑・`free_loss`↓／外しがわざとらしい → `dominant_hp`↓・`max_loss`↓・`min_human_policy`↑・
`natural_ratio`↑・`trap_min_delta_e`↑ or OFF／1手が遅い → `probe_extra`↓・`dominant_hp`↓。

**確認**: ログの `Rate:`（一致率の推移）/ `Budget:`（lead・λ）/ `Dominant:` / `Natural:` / `Score …`（vloss・dE・price・hp・kind）/
`Deviate:` / `Yose:`。CLI: `python -m katrain_debug --sgf <13路SGF> --move N --strategy mimic13`。
**実戦校正は未実施**（成功基準は 勝ち かつ 終局レポートで自分の一致率 < 相手の一致率。一致率だけで判定せず
払った vloss 合計・罠の実現値と並べて読む）。

**単一局面の実測（2026-09-17・katrain_debug・config visits 2500・コールド）**:
`enigma13-vs-human-20260901-white.sgf` @11（白・lead −0.05・λ 0.30）→ **C9**（natural・hp 16.4%・vloss −0.07・price −0.06・1.1 秒）／
@21（lead +0.23・最善手 hp 78.7%）→ **B5**（trap・ΔE +0.63・vloss 0.53・price −0.09・hp 2.7%）／@31 → 支配ガード（最善手 hp 80.1%・0.0 秒）／
@30（黒・lead −0.48）→ 勝率フロア 40% で pool 空＝最善手。`jigo-speedup/katrain-13ro-20260401-game1.sgf` @45（白・lead +0.26）→ **G8**
（natural・hp 9.4%・ΔE +1.07・price −0.78）／@75（lead +40.5・λ 2.00）→ **H2**（natural・**hp 60.4% ＞ 最善手 G1 の 27.8%**＝9段の第一感へ外す形・
vloss 1.40・price 0.51・0.3 秒）／@67（λ 2.00）→ N5（trap・price 1.14。第一感 N9〈hp 60.5%〉は最善手自身が E 4.3 の罠で ΔE −1.60＝price 2.70 > λ）／
@88（黒・lead −60）→ `Endgame check: unsettled=15 -> yose` → lead < reserve で最善手。プローブ 8〜9 手で 1.1 秒・2〜3 手で 0.2〜0.3 秒。
