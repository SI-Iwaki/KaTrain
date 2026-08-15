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

## 詰碁戦略（TsumegoOwnershipStrategy）

詰碁キャプチャ専用の独立戦略（`ai:tsumego`）。GUI の戦略一覧には出さず、キャプチャ経路がプログラムから設定する（`AI_OPTION_VALUES` への登録は不要。設定は両方の `config.json` の `ai/ai:tsumego` に直接置く）。

**着手選択**: リージョン限定解析（ownership 付き）の候補手に対し、(1) 目数ガード `pointsLost <= min(pointsLost) + max_points_behind` を通し、(2) **リージョン内**の石の ownership 変化量の合計（gain）が最大の手を選ぶ。(3) gain 差が `gain_epsilon` 以内の手は同着とみなし pointsLost で決め、(4) pointsLost も `points_epsilon` 以内で並ぶ同着バンドでは visits 最多（KataGo の本命）を採る。(5) 選択パイプライン（バンド → score_best 同深さ検証 → 救済）の**最後に**、目数ガード内の選択手はコウ経路検査（`tie_ko_screen` 参照）でクラス裁定し、コウ経路で clean な対抗馬がいれば格下げする。(6) その検査で**対抗馬も全部コウ経路**だったときは、それを「正解が候補プールの外にいる」信号とみなし、root policy の上位（未検査分）を同深さで測り直して無条件の手を探す（`ko_escape_candidates` 参照）。

**手番側の役割（攻め方 / 守り方）**（`tsumego_solver_attacks`。設定キーではなく盤から読む）: **詰碁の正解順序は役割で逆転する** — 攻め方（殺す）は 無条件死 > コウ > セキ、守り方（生きる）は 無条件生き > **セキ > コウ**（コウはコウダテという盤外条件に依存するので、確実に助かるセキより下）。役割は**リージョン境界線の壁の色**から読む（`tsumego_frame.put_border` が壁を攻め方の色で敷き、`mark_region_corners` が同じ frame_range をリージョンにする）。実測19ケース: 枠ありは全部が単色100%・占有率100%（case T: W7/7・W11/11 ／ case O: B10/10・B9/9）、枠なしは0〜1子（case R は13点中1子＝0.08）なので `TSUMEGO_WALL_MIN_OCCUPANCY`(0.7) と `TSUMEGO_WALL_MIN_PURITY`(0.9) の二重ゲートで分離できる。**枠なしは None＝従来の役割非依存の挙動**（G2/F2/H/I/N/R は不変）。役割が分かると「成否を担っている石」が決まり（攻め方＝相手石／守り方＝自石。`tsumego_role_stones`）、それが `ko_success_ownership` の成功判定とコウ脱出の採否に効く。**「自石・相手石の厳しいほう」の従来ヘッジは守り方では使えない**（セキでは相手が生きるのが正常なので必ず失敗側に落ち、セキより下のコウを持ち上げる＝実測 case T）。反転枠（case F/G/S の保存 SGF）では判定も反転側を返すが、それは盤に書かれた役割どおりで正しい（役割の是正は `extremum_stones` 側の仕事）

**gain の集計範囲はリージョン内の石のみ**（`tsumego_gain_stones`）。枠は `put_outside` でリージョン外を「守り側の代償地帯＋攻め方の地」に配る設計で、その境目の石の ownership は詰碁の成否と**逆相関する counterweight** になる。全石で集計すると符号が反転し、守り側が生きる手が選ばれる（実測 2026-07-30: 枠内 −9.65 に対し枠外 +11.6 で合計 +2.90 になり誤答手が4/4で選ばれた）。リージョンが無い枠なしモードでは従来どおり全石。

| パラメータ | デフォルト | 備考 |
|---|---|---|
| max_points_behind | 2.0 | 最善手からの許容損失（目）。小さいと正解手を弾き、大きいと大損の手が入る |
| gain_epsilon | 0.3 | gain の同着幅。root で死活が既に決着している局面では全候補の gain が ±0.03 のノイズに潰れ、選択がコイン投げになるため目数で決める。case B/C の実信号は 1.16 / 3.20 なので 0.3 では潰れない |
| points_epsilon | 0.25 | **目数同着バンド**: gain 同着（gain_epsilon 内）の目数タイブレークで、この幅以内の目数差は同着とみなし visits 最多の手（KataGo の本命）を採る。実測 case J (2026-07-30): 正解 N10(v1175 pt-0.05) と別解 N11(v616 pt-0.07) が gain・目数とも 0.02 差で並び、ノイズのコイン投げで解答樹に無い別解を打って不正解（N11 も殺しは成立＝8000visits でも分離不能、同深さ検証も差 0.05 で無力）。解答樹の本線は KataGo の principal variation と一致しやすい（case J の正解10手は全て visits 最多手）。0.25 はノイズ（〜0.07）と目数タイブレークが守るべき最小の実信号（2026-07-29 の C12/D12 = 0.64 目差）の中間。0 で旧動作（目数最良のみ・同着バンドなし）。A/B 回帰は points_tie_ab.py。バンド内の選択は score_best 同深さ検証の対象外（`tsumego_needs_score_best_verify`。等価な手は検証 margin 0.3 で分離できず必ず却下→目数最善へ巻き戻り、タイブレークが無効化されるため。GUI 実測で再発）。実 generate_move の E2E は generate_move_e2e.py |
| tie_ko_screen | true | **コウ経路検査（クラスの裁定）**: 選択パイプライン（同着バンド → score_best 同深さ検証 → 救済）が手を決めた**後**に1回だけ走る。**子局面解析は歩く深さぶんリージョン外を禁じて撃つ**（`TSUMEGO_KO_REGION_UNTIL_DEPTH` = `TSUMEGO_TIE_KO_PLIES` = 6。既定のリージョン解析 `untilDepth=1` は root の着手選択しか縛らず、**PV は ply2 以降で枠へ手抜きして肝心のコウが現れない**＝実測 case P: 検出 1/4 → untilDepth=6 で 4/4、無条件の正解はどちらでも 4/4 clean）。選択手が目数ガード内のとき（`tsumego_class_screen_applies`。**対抗馬が0手でも走る** — 旧 `len(pool)>=2` は「選択手がガード外＝検査しない（case F2）」と「対抗馬が居ない＝むしろコウ脱出のトリガー」を混同していて、root が1手に visits を集中させると機構が丸ごと no-op になった＝実測 case T）、ガード内の対抗馬（visits 降順・選択手込み計4手=`TSUMEGO_TIE_KO_MAX_CANDIDATES`）を対象に、各候補を1手進めてリージョン限定 gain_verify_visits で解析し、**[候補手自身]＋守り方の拮抗応手（visits比 0.5=`TSUMEGO_KO_REPLY_RATIO` 以上・最大3本=`TSUMEGO_KO_REPLY_MAX`）の PV** がリージョン内のコウ形（1子取り・取った石が呼吸点1・取り返しがコウ禁止）に到達する候補をコウ経路と判定する（`tsumego_candidate_reaches_region_ko`。候補自身がコウ形なら解析クエリ不要で確定。PV深さ6=`TSUMEGO_TIE_KO_PLIES`）。**判定はもう1本ある**: 歩きの途中で**守り方がコウ取りを「打てる状態」になった**ら、PV がそれを打たなくてもコウ経路（`tsumego_defender_ko_points`、深さ `TSUMEGO_KO_AVAIL_PLIES`=5）。リージョン解析は `untilDepth` で守り方からコウダテを取り上げるので、コウを仕掛けることが守り方の純損になり、**コウが争点の局面ほどエンジンはそのコウを打たない**＝PV を証拠にする判定が肝心なときに黙る（実測 case U 2026-07-31: コウを作る白 C1 は visits比 **0.01**・PV にコウ手 E1 が無く、比 0.00 まで全応手を歩いても検出 0/5 run。「打てる状態か」で見れば **5/5 run で ply5** に立ち、正解 C1 は 5/5 clean）。**候補手より前から打てたコウは数えない**（局面の性質であって候補の性質ではなく、数えると全候補が一律コウ経路になる。実測 case T の L1 / case F2 の N9 / case Q の M13 は着手前から打てるコウで、いずれも従来判定が別途拾っている）。**深さを 5 で切るのは、この証拠が PV より弱いぶん偶発コウを拾いやすいから** — 実測の両側は 検出すべき U ply5・L ply3・P ply3・F ply3/5・R(D8) ply5 に対し、clean のままにすべき **G2 の正解 C13 と R の C8 が ply7**（`ko_available_probe.py` で両側を測ってから動かすこと）。選択手がコウ経路で clean な対抗馬がいれば visits 最多の clean へ格下げ（`tsumego_class_screen_pool` / `tsumego_declass_choice`）＝詰碁の順序 無条件 > コウ の適用。**格下げ先は目数同着バンド（`points_epsilon`）内に限る**＝クラス裁定は同着の裁定であって実測の目数差を覆す権限は無い。**「無条件」は「攻めないので何も起きず自明に clean」でも成立する**ため、答えがコウの詰碁では格下げ先が正解を押しのける（実測 case R 2026-07-31・枠なし: 正解 G13=コウ pt+0.03 を、無関係な D8=clean pt+0.55 に差し替えて誤答）。ownership での検算は効かない（同深さ800visits の全リージョン石で正解 G13 +0.86/+0.97 < 誤答 D8 +1.32/+2.34、相手石は全候補 −0.55〜−0.72＝答えがコウなら ply1 に成否が出ない）。符号が一貫するのは目数だけで、格下げが正しい4ケースは格下げ先が必ず優る（K −0.05 / L −0.11 / M −0.57 / P −0.03）のに case R は +0.52 劣る＝0.25 で両側 0.26 以上の余裕。**ただし目数バンドで塞げるのは「非解が目数で劣る」形だけ**で、**非解が目数でむしろ優る**局面は素通りする（実測 case V 2026-07-31・13路右上・枠あり: 正解 L12=コウ/最終セキ pt−0.29 を、白が無条件で生きる K10=clean pt−0.33（0.04 良い＝バンド内）に差し替えて誤答）。そこで**役割が読めるなら格下げ先が本当に解いているかを確かめてから差し替える**（`tsumego_declass_confirmed`＝格下げ先の子局面を同深さ `gain_verify_visits` で解析し、**役割石**の1子平均 >= `ko_success_ownership`(0.5)。case R の「効かない検算」は全リージョン石を**両者の比較**に使ったもので、こちらは**格下げ先だけの絶対判定**）。**この判定用の子局面解析だけ `untilDepth` を分ける**＝`TSUMEGO_VERDICT_UNTIL_DEPTH`(12)。コウ検出と同じ 6 だと拘束が局所の攻防より先に切れ、**守り方が ply7 で枠外へ手抜きした（＝その群を捨てた）局面が評価されて失敗手が「相手は死んだ」と読まれる**（実測 case Y 2026-08-02・13路左下枠あり: 失敗手 A4 の白6子が ud6 で +0.71〜+0.78・**6000visits では +0.96**〈深くするほど確信が強まる〉なのに ud10/12/16 で -0.93〜-0.97。この白は ply7 の A1＝コウ取りで2眼を作る形で、地平線がちょうど正着を切っていた。格下げとコウ脱出の**両経路**が同じ判定を共有しているので誤答も両方から出た）。校正済み8判定は ud6/10/12/16 で不変（発火側 K C13/L J6/M K1/P J1/O A11/T L1 が +0.97〜+1.00、非発火側 V K10 -0.93〜-1.00・W J1 -0.24〜-0.76）。**コウ検出（`_ko_route_screen`）は 6 のまま**＝あちらは PV を 6 手しか歩かないので深くすると偶発コウを拾う側のリスクだけ増える。実測の分離は 格下げが正しい4ケース（K C13 +0.99 / L J6 +0.99 / M K1 +0.98（守り方・自石）/ P J1 +0.99）と case V の K10 **−1.00** の間に約 2.0 の空白。答えがコウの詰碁では正解も ply1 では成立しない（case V の L12 も −1.00）が、判定を格下げ先にしか課さないので「格下げしない＝コウを維持」に倒れる。****枠なしで役割が読めなくてもこの確認は走る**（尺度は `tsumego_success_ownership` と同じ「自石・相手石の1子平均の**小さいほう**」＝実測 case W 2026-08-01・13路右下枠なし・黒は守り方: 正解 H1＝コウで黒生き pt+2.20 を、黒が無条件死する J1＝clean pt**+1.94＝目数最善**、に格下げして誤答＝バンドは構造的に無力。同深さ800visits の自石7子 H1 +0.51/+0.35 vs J1 −0.22/−0.21。外し方が「格下げしない＝コウを維持」に倒れるので枠なしでも安全側）。測れなかった場合だけ従来どおり**（バンドのみ）。解析は格下げが起きようとしている手番でのみ1本増える。**裁定には格上げ方向もある**（`tsumego_result_class` / `_ko_promotion_choice`）＝詰碁の順序で最下位なのは「相手が無条件で生きる／自石が無条件で死ぬ」＝**失敗**なので、**選択手が clean かつ役割石の絶対判定で失敗しているなら、コウ経路の手のほうが上位**。root policy 上位（`ko_escape_candidates` 本・`ko_escape_min_prior` 以上）を同深さで測り、無条件で成立する手 > コウ経路の手 の順で採る（実測 case V2 2026-07-31: 正解 N13＝コウ pt+7.97・v17・prior 3位 が目数ガードの外に居て、選択手 K10 も対抗馬 L11 も L13 も **全部 -1.00/子＝白が生きる**。分離できるのはクラスだけ）。**コウ経路は「成立している」と読めてもコウのまま**（コウ手の値は「コウに勝った前提」で高く出るので繰り上げると格下げが無意味になる）。**通常の手番では解析0本**＝root の movesOwnership で先に振るい、成立していれば即スキップする（実測: 枠あり8ケースの正解手は全部 +0.98〜+1.00）。役割が読めない枠なしでは走らない。選択手が clean なら検査1本で終わる。**旧設計（同着バンド内だけ検査）は case M で破れた**: コウで殺す手の gain は「コウに勝つ前提」で相手石を取り切る実信号（+1.9 で単独首位）になりバンドから抜け出し、同深さ検証も +1.29 でコウ側を追認する＝gain・目数・検証値のスコア系メトリックはクラスを分離できず、分離できるのは構造検出だけ。**ガード外の救済採用手は検査しない**（実測 case F2: 枠なし盤ではガード内の clean 手が「スコアだけ良い失敗手」でありえ、正解 N11 が偶発コウ形で J10 に差し替わった）。**応手は拮抗分を全部歩く**（実測 case M: コウ仕掛け K1 v144 と穏健 M4 v103 が拮抗し、top 1本では 3run 中 2 でコウを見逃した）。**検査の子局面解析は wideRootNoise=0 で撃つ**（`TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`）— root の Dirichlet ノイズは run ごとに引き直され応手の visits 比を揺らす（visits を増やしても消えない）。実測 case M の M2 子局面: wRN=0.04 で K1 の比 0.44〜0.88（本番フロー 3/6 で 0.5 を割り検出漏れ）→ **wRN=0 で 0.15 が 4/4 不動**（M4 v663/K1 v100/残り v1）。旧 0.5 ゲートは「ノイズが本物のコウ応手を水増ししてくれた時だけ当たる」偶然の産物だった。**選択手だけ敏感な比 `TSUMEGO_KO_REPLY_RATIO_CHOSEN`(0.05) で検査する**＝選択手のコウを見逃すとクラス裁定が丸ごと no-op になりコウ手がそのまま打たれる唯一の経路だから。格下げ先候補は保守側 0.5 のまま（過検出は全員コウ→脱出の誤爆に化ける）。**単一閾値では分離できない**実測: 検出すべき最小 0.09（K A12）＜ clean のままにすべき最大 0.16（R J13）で逆転している。実測のコウ形: case K=応手 A11→B11 / case L=候補 L5 自身の1子取り / case M=応手 K1 の PV の B M4。E2E 回帰は generate_move_e2e.py（**V: L12 3/3**（格下げ先の成立確認を入れる前は K10 3/3）/ **V2: N13 3/3**（クラス格上げを入れる前は K10 3/3）/ **M: K1 8/8**（wRN=0 化の前は 1〜3/6）/ K: C13 3/3 / L: J6 3/3 / P: J1 3/3 / O: A11 3/3 / J: N10 3/3 / F2: N11・M12 コイン投げ / **U: C1 3/3**（旧実装は A3）/ **F: N8 3/3**（脱出の成立判定を入れる前は J11/J10/N11 に飛んでいた）/ R: G13 3/3 / G2: C13 2/2 / H: N4 2/2 / E: K1 2/2 / D: A4 3/3 / **Y: B1 3/3**（判定用 untilDepth を分ける前は A4 3/3））。**case R の救済経路は `TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO`(0.15) で塞いだ**（救済トリガーが消え、格下げバンドが設計どおり働く）。残る揺れは**リージョン root 解析（1800visits・wRN=0.04＝着手選択のクエリなので変えられない）の visit 配分の分散**で、稀に J13/C8 が select 段階で選ばれる。答えがコウの詰碁は ply1 の ownership も目数も成否を運ばないため、**case I / case Q と同じエンジン側の限界枠**（spec 追記26）|
| gain_min_visit_ratio | 0.5 | **深さゲート**: gain で目数最善手を覆せるのは、その手の visits の この割合以上探索された候補だけ。gain は1本の root 探索の movesOwnership から取るので候補ごとに探索深さが違い、root が飽和した局面では浅い手ほど ownership が 0 方向へドリフトして片側ノイズになる（実測 case F: 同じ N7 が 214-307visits で +2.70〜+9.10、637visits で +0.06 に消える）。実測比は誤答 0.31/0.11 に対し case D の正解 1.00。0 でゲート無効 |
| gain_verify | true | **同深さ検証**: gain が目数最善手を覆すとき、両者の子局面を同 visits で解析し直して対象石 ownership を絶対値で比較する（別クエリ同士は root 基準が揃わないので gain 差分は使えない）。実測 case F: N8 −26.60 > N7 −26.91 で正解が残る |
| gain_verify_visits | 800 | 同深さ検証の visits。覆す判断が出たときだけ2本走るので +1〜2秒 |
| gain_verify_margin | 0.3 | 覆すのに要求する ownership 差。同深さでも ±0.3 程度は動く（実測 N6 −26.84 / M7 −26.89）。case B / C の実信号 1.16 / 3.20 はこれを余裕で超える |
| gain_rescue_margin | 1.0 | **救済**: gain 争いに参加できなかった候補（目数ガード外＋深さゲート外＝非 contenders）のうち、gain が選択手をこの値超えて上回る手を **gain 降順トップ3**（`TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES`、コード定数）まで同深さ検証にかけ、**検証も同じマージンで上回った中の検証値最良**を採用する（トリガーと採用の両方に使う。採用側が通常の覆し 0.3 より厳しいのは、深さゲートを迂回するため偽 gain の候補も検証まで来るから）。visit比では**順位づけ**しない — 本物の比 0.21〜0.49 と偽の比 0.24〜0.36 は重なっていて比では分離できず、分離できるのは同深さ検証だけ。ただし**桁の切り捨てとして床はかける**（`TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO`=0.15、root 最多手比。コード定数）: 実測の本物は G2 C13 0.90 / H N4 0.52 / F2 N11・M12 0.33・0.30 なのに対し、case R の誤答 J13 は **0.036〜0.05 と1桁下**で、同深さ検証の差が margin をまたいで揺れる（−1.05〜+1.31、**wRN=0 にしても収まらない**＝答えがコウの詰碁では ply1 の ownership が成否を運ばないため）。床は本物の最小 0.30 と R の最大 0.05 の中間。トップ1でなく複数なのは case F2 対策（v10 のノイズ手が gain 1位に立ち、その却下で救済が終わって本物 N11/M12 が機会を失った。検証は毎回正しく序列化する: N11 -17.1 / M12 -17.2 / J11 -19.4 / N9 -26.9）。実測 case G2・H・F2 を救済し、偽トリガー（G1 の C13/G13、F の N6）は検証が全run却下（E2E 24/24）。`gain_verify=false` なら救済ごと停止 |
| min_visits | 10 | この visits 未満の候補を除外（目数ガードより前）。1visit の手の ownership/スコアは NN の生評価1回で gain が10〜100倍のノイズになり、実測で −16.5目の手を選ばせた。全候補が未満ならフィルタしない |
| ko_win_assumption | true | ON でコウになる候補手を「攻め方がコウに勝った局面」のスコアで評価する（詰碁はコウダテがある前提で正解が決まるため）。**通常最善が失敗しているときだけ**適用し、さらに通常最善を `ko_win_margin` 超えて上回るときだけ採用。実測: 正解のコウ手が通常 −21.7目 → コウ勝ち前提 +3.1目 |
| ko_win_visits | 800 | コウ勝ち局面の解析 visits。コウが見つかった候補だけ解析するので +1秒程度 |
| ko_success_lead | 0.0 | この目数を超えて通常最善が勝っていれば「既に成功」と見なす（**`ko_success_ownership` との AND**）。**詰碁の正解順序は 無条件に殺す（生きる） > コウ > セキ で、目数はクラス内のタイブレークにすぎない**。枠は成功側が offence_to_win(5)目勝つ設計なので符号が成否になり、player_sign 込みで攻め・守りの両方に効く。コウ解析より前に判定するので成功局面では解析1本ぶん速い |
| ko_success_ownership | 0.5 | **成功判定の ownership 側の条件**（1子平均）。目数だけでは成否を判定できない: 枠の代償地帯が未決着だとスコアが詰碁から切り離される（実測 2026-07-31 case Q: 相手石12子すべて生存 −0.99/子 なのに +10.45目。全盤 20000visits の最善手が枠の充填部 B9 v17448 だった。枠なし盤ではさらに露骨で case H は +27.69目・相手石 −0.15/子）。既存16ケース横断の実測では、成功局面（D/E/J/K/L/M/O/P）が +0.94〜+1.00、失敗局面（F/G/G2/H/F2/I/N/Q）が −0.15〜−1.00 で、境界に 1.09 の空白がある。値は `tsumego_frame.FRAME_SOLVER_ALIVE_OWNERSHIP` と同じ「その石群は生きているか」の閾値。**尺度は自石・相手石の 1子平均の小さいほう**（`tsumego_success_ownership`）— 殺す詰碁か生きる詰碁かは戦略に渡ってきていない（枠生成の `black_to_attack_p` は伝わらない）ので両方測って厳しいほうを採る。生きる詰碁では攻め方の石が生きたままで負に出るため誤ってスキップしない側に倒れるが、それが安全側（保険は `ko_win_margin`）。判定を厳しくする方向にしか動かず、実測でも SKIP→run に変わる H/M/Q の3ケースは全て答えが 6/6 で不変。ownership が取れない経路では None＝この条件を課さない。-2.0 等にすると旧挙動（目数だけ） |
| ko_win_margin | 5.0 | コウ勝ち前提が通常最善を上回ったと見なす目数差（`ko_success_lead` を通った局面向けの保険）。コウ勝ちノードは攻め方が1手多く相手石を1子取った局面なので比較が構造的にコウ側へ数目偏る。実測の分離幅: 誤答 +1.06目 / 正解がコウ +15.5目。旧既定 0.5 かつ成功ゲート無しでは 1visit・−34目の手が +1.06目差で採用された |

| ko_escape_candidates | 4 | **コウ一色バンドからの脱出**（トリガーは `tsumego_ko_escape_applies`: 全部コウ経路、**または役割が読める**＝clean な対抗馬が目数同着バンドの外に居ても走る。「clean なのに目数で劣る手は詰碁を解いていない」は攻め方の推論で、守り方のセキは clean のまま目数で必ず劣るため＝実測 case T。誤爆しないのは採否が役割ごとの石の同深さ ownership で決まるから: case T 自石12子で正解 L1 +11.97 vs 失敗する clean 手 -11.93 の 24 の空白。case R がこれを使えなかったのは枠なしで役割が読めなかったため）: 選択手も目数ガード内の対抗馬も**全部**コウ経路だったとき、詰碁の順序（無条件 > コウ）からするとそれは「正解が候補プールの外にいる」という信号なので、root policy の上位（未検査分）をこの本数まで同深さ `gain_verify_visits` で測り直す（`_ko_escape_choice` / `tsumego_ko_escape_candidates`）。**探す先が policy なのは、value が壊れているから正解が漏れているため**。実測 case O (2026-07-31): 正解 A11 は root 1800visits でも **12000visits でも v1 のまま**（root の value が約29目ずれ PUCT が二度と訪れない＝深さでは原理的に届かない）で、その 1visit 評価 pt+28.74 で min_visits・目数ガード・gain・救済・コウ検査プールの全部から締め出されていた。prior は `B12 .68 / C10 .20 / B13 .043 / C13 .011 / A11 .0076〜.0091 / A8 .0008 / 残り42手すべて .0001(NN下限)` で正解は 2/2 run とも5位固定。0 で機構を停止。回帰は generate_move_e2e.py（O: A11 3/3。K/L/M/J/F2/I は脱出が発動せず不変） |
| ko_escape_min_prior | 0.001 | 脱出候補に要求する root policy の下限。NN 下限（.0001）に張り付いた手を除くための崖の位置。case O では A11(.0091) と A8(.00089) の間に10倍の崖がある |
| ko_escape_tolerance | 0.5 | **採用条件の許容幅。不等号の向きに注意**。**採用の成立バーはコード定数 `TSUMEGO_KO_ESCAPE_ADOPT_CONFIRM`(0.9)**（2026-08-15）＝`ko_success_ownership`(0.5) ちょうどだと閾値すれすれのノイズ成立が「答えがコウの詰碁では脱出は何もしない」の安全弁を素通りする（実測 回答帳 92ef635c45 d2: アプリの正解 A6＝コウ経路を E1 +0.51/子 が紙一重で通って差し替え誤答→バー0.9で 3run 消滅）。校正済みの正しい採用は O +0.99 / T +1.00＝全部バーの上、0.5〜0.9 帯に校正ケースなし。 — 「incumbent を上回る」ではなく「tolerance 超えて**下回らない**」（`tsumego_ko_escape_accepts`）。**ただしこの相対条件だけでは採用しない**: 先に「その手で詰碁が成立しているか」を役割石の**1子平均 ownership >= `ko_success_ownership`(0.5)** で絶対判定する（`tsumego_ko_escape_succeeds`）。相対条件は incumbent 自身が失敗している局面で退化し、全候補が横並びになってノイズ幅で1手が「最良」に選ばれる（実測 case F 2026-07-31: 選択手 N8 −9.72 に対し policy 上位 J11 −9.82 / J10 −9.86 / N11 −9.90 / M12 −9.89 が全部 tolerance 内に並び、**0.08 差**で J11 が採用されて N8 が捨てられた。1子平均は全員 −0.97〜−0.99＝どれも解いていない）。分離幅は桁違いで、採るべき手（O の正解 A11 +0.99/子・T の正解 L1＝セキ +1.00/子）と落とすべき手（O の失敗 clean C13/B13 −1.00/子・F の全候補 −0.97〜−0.99）の間に約 1.9 の空白がある。コウ手のスコアは「コウに勝った前提」で出るので無条件の正解より**むしろ高い**（実測 同深さ800visits・リージョン内42子: コウの B12 +41.95 > 正解 A11 +41.85）。既存の覆し `tsumego_override_confirmed`（gain_verify_margin 0.3 超えで上回ること）を使うと正解が却下される。順序を決めるのはクラスであってスコアではなく、スコアは「その手で本当に詰碁が成立しているか」の確認にだけ使う。失敗する clean 手は同じ尺度で +18.5〜+18.8（−23）まで落ちるので 0.5 で十分に分離できる。**この非対称性が安全弁**: 答えが本当にコウの詰碁では clean 候補が ownership 検査を通らず、脱出は何もせずコウを維持する |

| promotion_dominant_requires_success | true | **KataGo が1手に確信している手番では、成立していない手へクラス格上げしない**（`_ko_promotion_choice`）。`tsumego_result_class` はコウ経路を `succeeds` と無関係に KO クラスへ置く（それ自体は正しい＝コウ手の ownership は「コウに勝った前提」で高く出るので成立の読みでクラスを繰り上げてはいけない）が、**incumbent も shortlist も全員が閾値未満**の局面では ownership が「どの手が解くか」を一切表現しておらず、順位を決めているのはコウ検出の二値だけになる。実測 2026-08-10（spec `2026-08-10-tsumego-ambiguity-analysis.md`）: dominant 帯の格上げ採用は **リプレイ 6/6・実GUIログ 3/3 が全部この状態（採用手 −1.00〜+0.17/子）で全部誤答**、一方 正答した2件は採用手が **+0.94/+0.99＝成立していた**＝閾値0.5で完全に分離する。dominant 判定は `tsumego_decision_is_ambiguous` の否定で**追加クエリ0本**（検証バッチは既に発行済みで、変わるのは採用判断だけ）。**校正ケース case V2 は v2/v1=0.63・目数差0.01 で ambiguous 帯なので構造的に影響を受けない**。false で従来動作。**格上げの root movesOwnership 事前ふるいの省略バーはコード定数 `TSUMEGO_PROMOTION_ROOT_CONFIRM`(0.9)**（2026-08-15）＝軽量シグナルの閾値近傍（+0.37〜+0.5）は run ごとに flip するので、threshold(0.5) ちょうどで省略すると子局面 verdict なら毎回正しく測れる手番が run 依存で素通りする（実測 回答帳 4d3f678f77: root +0.37〜+0.5 で格上げ不発の run あり、子局面 verdict は別プロセス6/6で D5 +0.08〜+0.21=不成立 / 正解 B5 +0.95〜+0.98=成立）。0.5〜0.9 の帯は incumbent の子局面 verdict で確かめてから省略＝増えるのは閾値近傍の手番の解析1本。**確認帯から入った格上げは「成立している対抗馬」への差し替えに限る**（`require_success` を dominant ゲートと共有。フルスイープ A/B で確認帯のコウ経路差し替えが誤答を作った＝4e7d6932f4: 正解 D10〈−0.97/子=ply1不成立〉を B9〈コウ経路・−0.95/子〉へ。締め後は B9 誤格上げ 3run 消滅・4d3f678f77 の B5 回復〈+0.95〜0.98=成立〉は 3/3 維持）。校正済み正解手（+0.98〜+1.00）は従来どおり解析0本 |

**リージョン解析クエリ側**（`tsumego_capture` セクション。戦略ではなく解析の設定）:

| パラメータ | デフォルト | 備考 |
|---|---|---|
| analysis_visits | 1800 | リージョン限定解析の visits。0以下で既定解析にフォールバック |
| region_wide_root_noise | 0.04 | root の探索の広げ方。0.0 だと探索が1手に集中し、正解手が 12〜29 visits で切り捨てられて「+14〜+21目損」と誤評価される（実測 8 trial 中 5 回）。0.04 で 7/8 が正解 |
| frame_ko | false | コウダテ形を攻め方に与えるか（true=攻め方 / false=守り方）。問題の答えがコウかどうかで正解が変わる |
| frame_ko_auto | true | ON でキャプチャ時に frame_ko の両方の枠を張り、root スコアが設計目標（攻め方成功=5目勝ち）に近い方を自動採用。正解がコウ止まりの問題は false 側だと守り側にコウダテが渡り白の無条件生きになる（実測 −23.0 vs +0.68）。バランス距離が `FRAME_BALANCE_TIE_MARGIN`(2.0目) 以内で拮抗する場合は攻め方コウダテ側(ko_p=True)を優先（僅差だとキャプチャごとに枠が入れ替わり誤答していた） |
| frame_ko_trial_visits | 400 | 自動選択の試算 visits。400 で判別可能（実測 2本で約1.2秒）。この試算の ownership を枠採否判定にも流用する（下記） |
| frame_validity_visits | 1800 | 上の試算で「詰碁を壊している」と出た枠を**捨てる前に読み直す** visits。読み直しは **`FRAME_VALIDITY_WIDE_ROOT_NOISE`=0** で撃つ（下記）。生き問題では手番側の石そのものが戦いの対象なので浅い・散らした読みでは死と出る（実測 case N の有効な枠: 400/wRN0.04 で −0.69〜−0.98/子、1800/wRN0.04 は +0.95〜−0.95 の二峰性、**1800/wRN0 で +0.96〜+0.97 に収束**）。壊れた枠はどの設定でも死のまま（case F −0.72、case G −0.98）。`frame_ko_trial_visits` 以下にすると読み直しを無効化 |
| ponder_replies | 3 | **先読み（NN キャッシュ温め・2026-07-31）**: AI 黒番の着手後、そのノードのリージョン解析が完了したら人間（白）の有力応手 top-K の子局面を**実クエリと完全同条件**（同 visits・同リージョン・同 wRN・**同 ownership=True**）・低優先度（`PRIORITY_REGION_PREFETCH`=-50）で先読みする。**ownership を揃えるのは必須** — KataGo の NN キャッシュは ownerMap の有無を区別するため、ownership なしの先読みは実クエリを1秒も速くしない（実測 2026-08-01 `prefetch_cache_probe.py`: ownership なし先読み直後の実クエリ 2.70 秒＝コールド 2.69 秒と同一。ownership 付きで温めた後は **0.10〜0.28 秒**）。`request_analysis` は `next_move` 指定だと includeOwnership を強制 OFF にするので、**使い捨ての複製ゲームで応手を1手進めた子ノードを作って撃つ**（`_region_prefetch_sim`。この子ノードに紐づくクエリだけを terminate できる＝本譜ノードのクエリや GUI の追加解析を巻き込まない、という副次効果つき）。**結果は使わず捨てる**（本物のクエリが従来どおり走る）ので着手判定への影響はゼロ。未消化分は次の `Game.play()` 冒頭で terminate（リージョン解除後の着手でも掃除する）。次番が人間のときだけ発火（`players_info` が無いデバッグ環境では発火しない）。0 で無効 |

**高速化（2026-07-31・精度不変）**: 選択則の独立な子局面クエリ（同深さ検証・コウ経路検査の
pool・クラス格上げ／コウ脱出の shortlist・コウ勝ち評価）は `_start_region_root` +
`_wait_region_roots` で**全員分を発行してからまとめて待つ**（KataGo は `numAnalysisThreads=4`
で並列処理。クエリ内容・評価順序・タイブレークは直列版と同一、E2E 全ケース回帰で不変を確認）。
選択手のコウ経路検査は ownership 付きで撃って生解析を memo し、同条件（同 visits・untilDepth・
wRN=0）のクラス格上げ incumbent 検証だけが再利用する（wRN=0.04 の脱出・格下げ確認は対象外＝
校正条件を混ぜない）。枠採否判定も `frame_validity_verdicts(read_batch=...)` で並列化（採否の
意味論は直列版と同一: 直列版が読まなかった読み直しの結果は**破棄**、健全枠＋死枠の混在では
余計な読み直しを発行しない）。実測: 重経路ケース（M/O/V2）の generate コールド 6.1〜6.5 秒 →
4.7〜5.4 秒。`[TsumegoOwnershipStrategy] 着手決定に X 秒` ログで per-move 時間を常時確認可能。

**高速化第2弾（2026-08-02・精度不変）**: コウ「権利」検出 `tsumego_defender_ko_points` が
リージョン内の**全空点（約100点）を試し打ち**しており、`play`/`set_current_node` の全盤再計算
（1回≈1.2ms）× 最大3回/点 × 87呼び出し/手 ＝ **11.7秒/手（着手決定の約8割）** を占めていた
（cProfile 実測・コウ詰碁 case Z）。KaTrain の Ko 例外は「直前の手がちょうど1子取り」でしか
発火しないので、候補点を**攻め方のアタリ1子連の唯一の呼吸点**（chains 走査・典型0〜3点）に
事前フィルタし、生き残りだけ従来どおり実打ちで検証する＝**返る集合は総当たりと同一**
（`tests/test_tsumego_ko.py` の総当たり参照実装との等価性テスト＋プローブ数テストで担保）。
実測: 10秒級だった手が 15.0→3.0 秒（プロファイラ込み・残りはほぼエンジン待ち）、コウ詰碁
4手の generate がコールド 1.6〜4.0 秒・NN ウォーム 0.3〜1.5 秒。**エンジン待ちより先に
Python の盤面プローブを疑うこと**（クエリ実測 0.1〜1.0 秒 vs 着手決定 4.3〜10.0 秒の乖離が
入口だった）。詳細は spec 追記39。

**高速化第3弾（2026-08-03・精度不変）**: **手番内投機（in-turn speculation）**。
`select_tsumego_move` が選択手を返した直後（`score_best = tsumego_score_best(eligible)` の直後・
検証バッチの発行前）に、この後の段（救済・コウ経路検査）が撃つことになりそうな子局面を
同一条件・低優先度で先回り発行し、結果は捨てて NN キャッシュだけ温める（`tsumego_speculation_plan`
/ `_fire_speculation`）。温め集合は2種: (1) 救済スーパーセット＝gain 降順トップ
`TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES`(3) ＋ visit比フロア `TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO`
(0.15) ＋ min_visits を通る非 contender（条件は実救済呼び出しと同一: 800visits・ownership=True・
untilDepth=1・wRN=0.04。`rescue_margin` も実呼び出しと同じ式 `(settings).get("gain_rescue_margin",
TSUMEGO_GAIN_RESCUE_MARGIN)` で伝播）、(2) コウ検査対象＝選択手＋目数最善（同一なら1手。条件は
実コウ経路検査と同一: 800visits・ownership=True・untilDepth=6・wRN=0）。**ただし温めが効く
コウ経路検査クエリは選択手（chosen）の `want_ownership=True` の1本のみ**（`_ko_route_screen`）
＝格下げ先候補（`pool[1:]`）の検査は `_ko_route_screen(pool[1:])` が ownership なしで撃つため、
温めても cache hit しない（score_best が pool[1:] 側に回るケースも同様）＝意図的なトレードオフ。
優先度は新定数
`PRIORITY_TSUMEGO_SPECULATION`=500（実クエリ 10010・通常ノード解析 1010 より下、アイドル
先読み `ponder_replies` の -40/-50 より上＝実クエリのスロットを奪わない）。未消化分は
`generate_move` の `finally` でノード単位 terminate（次の解析とGPUを取り合わない）。実測: 条件が
完全一致した実クエリは 0.0〜0.2 秒で返る（コールドな初回クエリ群は 2.5〜3.0 秒）。ただし
発火から実クエリまでの間隔が短い経路（コウ脱出等で即座に後続クエリが飛ぶ場合）は投機と実クエリが
ほぼ並列実行され、恩恵が部分的（0.6〜1.2秒）に留まることもある。E2E `--full` は 66/69 PASS
（手順差分2件は既知分散・K@0 は PYTHONPATH 未設定で base 側が誤って HEAD コードを実行していた
ラベル誤りを裁定し直し base(真) 3/3 C13・HEAD 全サンプル 13/15 C13＝既知ナイフエッジ分散で
正答不変ゲート PASS 確定）。全体では generate_move() 秒の中央値が 2.55→2.0 秒（M/O/V2 の4点・
簡略法=1プロセス3rep・全12サンプル）。**`numAnalysisThreads` の実効値はパッケージ同梱
`katrain/KataGo/analysis_config.cfg` の 12**（`~/.katrain/analysis_config.cfg` はエンジンに
参照されない。実測 2026-08-03: ユーザーが後者を 4→8 に編集しても no-op だった。詳細は
CLAUDE.md「ランタイム設定ファイル」節）。詳細は
`docs/superpowers/specs/2026-08-03-tsumego-latency-overlap-design.md`（追記1・追記2）。

**高速化第4弾（2026-08-03・精度不変）**: **段階3（root 部分結果からの前倒し投機）**。段階1+2（手番内投機）は選択手確定後＝検証バッチ実クエリと同時発火のため、初回手番では並走による部分短縮しか得られないという残課題への対応。当初案「戦略の待ちループ差し替え」は実装棚卸しで不成立と判明した: 戦略の `wait_for_analysis`（`ai.py` の `while not self.cn.analysis_complete`）は実質 no-op で、**root 待ちは戦略の外**にある（GUI はノードの解析完了を見てから generate を呼び、CLI ハーネスも `analyse()` が region 完了までブロックしてから generate を呼ぶため、戦略内のフックでは前倒しにならない）。

そこで発火場所は**Game 側のウォッチャスレッド**（`_maybe_early_speculation` / `_early_speculation_worker` / `_cancel_early_speculation`。`Game.play()` の region 分岐が新ノードの解析を発行した直後、次番が `ai:tsumego` ならウォッチャを起動する＝アイドル先読み `_maybe_region_prefetch` の**鏡像**。掃除は次の `Game.play()` 冒頭で prefetch と同じ位置）。**戦略コード（`ai.py` の判定ロジック）は不変**——ウォッチャは 50ms 間隔で `node.analysis["moves"]` の visits 合計を確認し、`TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION` × region_analysis_visits に達した時点で一度だけ温め集合を計算・発行する（region 完了・ノード切替・リージョン解除・期限30秒で bail）。

温め集合は新純関数 `tsumego_early_speculation_items`（ai.py）が計算する**検証バッチ本体（incumbent＋挑戦者＋仮 chosen。`tsumego_score_best_challengers` 相当、untilDepth=1・wRN=0.04・ownership=True＝実検証と同一条件）＋段階1+2 の温め集合（救済スーパーセット＋コウ経路検査）**の和。判定は従来どおり最終1800visitsのroot値のみを使い、部分結果は温め集合の計算にしか使わない読み取り専用（仮 chosen がどうであれ実クエリの内容・発行順・待ち合わせ・タイブレークは変わらない）。仮選択の計算に使う ai.py の純関数はウォッチャ内で**遅延 import**する（`game.py`→`ai.py` のモジュール循環を避けるため）。

閾値定数 `TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION` は実測で3段階変更した: 当初案 0.67（部分結果の PARTIAL 報告は毎回1本のみで、実測 visits 1160〜1182 と構造的に僅かに未達）→ 0.55 でも重経路ケース（M@4・V2@2）で独立試行1/3しか発火せず → **0.35（1800v なら630v）で3/3安定発火**（M@4 はn=6拡張確認で6/6）、これを採用。**構造的制約**: ウォッチャは `Game.play()` からしか起動しないため、**キャプチャ直後の初手（ply0）には効かない**。効くのは白が応手した後の黒番（ply2以降）のみ。

**実測**（GUI 経路を再現した専用ハーネス `early_speculation_e2e.py`。既存 CLI E2E ハーネス `generate_move_e2e.py` は `node.analyze()` を直接呼び `Game.play()` を通らないため段階3は構造的に一切発火せず、**効果検証にはこの専用ハーネスが要る**）: 1手あたりの正味秒（analyse+generate、体感時間）で3ケースとも改善——M@4 5.36→4.79秒(-0.57)／O@2 2.59→2.26秒(-0.33)／V2@2 6.07→5.27秒(-0.80)。root ウォール（analyse秒）は O@2・V2@2 で改善、M@4 のみ n=6平均で+0.20秒（同時発行される投機クエリ増でGPUを分け合うため）だが採用ゲート（+0.3秒超で不可）には抵触せず、generate短縮が上回るため正味は改善。回帰は `e2e_suite.py --full` 66/69（差分3件 AA@6・E@2・Z@2 はKataGoのrun間分散・既知）——**ただし CLI E2E では段階3のコードが1行も実行されないため、この回帰結果は段階3の正答不変を検証していない**（新規発火経路が既存判定に触れないことは `tests/test_tsumego_early_speculation.py` の単体テストと、上記専用ハーネスの発火ログ確認で別途担保）。詳細は
`docs/superpowers/specs/2026-08-03-tsumego-stage3-early-speculation-design.md`。

**枠の採否判定**（設定キーではなくコード定数。`tsumego_frame.py` / `__main__._choose_tsumego_frame`）:

| 定数 | 値 | 備考 |
|---|---|---|
| FRAME_SOLVER_ALIVE_OWNERSHIP | 0.5 | 手番側の**本体石**（壁・充填を除く）の ownership 1子平均がこれ未満の枠は「詰碁を壊している」と判定する（`frame_destroys_problem`）。**この読みは `frame_validity_visits` で読み直してから確定させる**（下記。浅い読みの判定だけで枠を捨てると生き問題で偽陽性）。全候補が落ちたらその回だけ枠なしで出題。必ず正解手がある詰碁で開始時点から解く側が全滅はあり得ない、が根拠。実測: 正常枠 +1.00/子、壊れた枠 −0.09〜−0.99/子（case F/G）。0 だと −0.09 の枠が run ごとに採否反転するので 0.5。**枠バランス距離では検出できない**（攻め方推定が反転していても想定攻め方が成功するのでバランスは完璧に見える。case G: 距離 2.06 で過去最良なのに黒の攻め石全滅）。**役割反転の検出にも使えない**: 反転枠では手番側が「攻め方」になって壁と連絡するので、生きる詰碁では誤った役割のほうが高く出る（実測 case M: 誤 +0.99 vs 正 +0.72）。手番側が攻め方の詰碁では反転しても本体石が生きたままで閾値近傍を滑り込む（case S +0.46〜+0.65）＝この判定は**手番側が守り方のときにしか役割反転を捕まえられない**。役割そのものは `guess_black_to_attack` の推定を直す（`extremum_stones`＝極値線の石を全部足す。代表点1つだと同座標のタイをリスト順で崩して判定が反転する。case S: -1(誤) → +21(正)） |
| FRAME_SOLVER_CONFIRM_OWNERSHIP | 0.9 | **浅い読みの「生」をそのまま信じてよい下限**（1子平均）。これ未満で `FRAME_SOLVER_ALIVE_OWNERSHIP` 以上＝閾値近傍の「生」は、採用する前に `frame_validity_visits` で確かめる。「死と出たら読み直す／生と出たら即採用」は安全網として非対称で、浅い読みは**生側にも振れる**（実測 2026-07-31 case S: 同じ枠・同じ 400visits が +0.4977/子 と +0.65/子 の両方を出し、1800visits では +0.46/子 で壊れ。+0.65 を引いた run はそのまま出題されて誤答した）。0.9 の位置は「自明に生きている枠」（手番側が攻め方で壁と連絡＝+0.96〜+1.00）と「戦いの対象として生きている枠」（生きる詰碁の正しい枠 case M +0.72）／「閾値近傍の偽陽性」（case S +0.65）の間。前者には追加コストが乗らず、後者は読み直し1本（1.5〜1.9秒）増える |
| FRAME_VALIDITY_VISITS | 1800 | 上記 `frame_validity_visits` の既定値（`frame_solver_verdict` は**読めた中で最も深い読みだけ**で裁定する。浅い読みを混ぜると平均でノイズが戻る。読み直しが取れなければ浅い判定＝枠を捨てる） |
| FRAME_VALIDITY_WIDE_ROOT_NOISE | 0.0 | 読み直しの wideRootNoise。**二峰性の正体はこれ**で、着手選択で候補を広げるための設定が「手番側が生きているか」の裁定では探索を critical line に集中させない。0 にすると 1800visits で分離が桁違いに明確（case N +0.96 vs case F −0.72 / case G −0.98）。深さで殴る（6000visits/wRN0.04）と1本 4.8〜8.4秒かかりキャプチャが 16 秒になる。読み直しは**浅い読みが生きに近い枠から順に、有効な枠が1つ出た時点で打ち切る**。実測の枠採否判定: 健全な枠 1.1秒 / 枠を救う 2.9秒 / 全枠が死 5.5〜5.7秒 |
| FRAME_OVER_FRAMELESS_MARGIN | 0.5 | 全枠が壊れ判定でも、捨てる先の枠なし盤より手番側コアが1子平均でこれ以上生きている枠は残す（`frame_over_frameless`）。**枠なしは安全側のフォールバックではない**（リージョン外が丸ごと相手の地になる）。実測の差は残すべき側 +1.17 以上／落とすべき側 −0.05〜−0.35 で、1読みの run 間分散（0.2〜0.5）を吸収できる中間値 |
| FRAME_BALANCE_WARN_DISTANCE | 8.0 | 採用した枠のバランス距離がこれを超えたら警告ログ（絶対スコア判定が信用できない域）。判定には使わない |

Spec: `docs/superpowers/specs/2026-07-29-tsumego-ownership-design.md`（誤答実測と ε・wRN 変更の経緯は「追記（2026-07-29）」、枠採否判定は「追記9（2026-07-30）」）

**回答帳フルリプレイ由来の安全弁4件（2026-08-13・設定キーなし＝コード内挙動。spec
`2026-08-13-tsumego-answer-book-fixes.md`）**: どれも「解析条件は変えない」（シャッフル回避）。
(A) **ソルバ cross-check の実測値をフォールバックへ引き継ぐ**（`_cross_check_measured`）＝
却下後の ai:tsumego が「**積極的失敗**（役割石 ≤ −ko_success_ownership）」と実測済みの手を
選び直したら、成立を実測済みの本命へ差し替える。**閾値未満（< 0.5）で発火させてはいけない**
— 未決着帯（−0.05〜+0.20）は答えがコウ等で ply1 が成否を運ばず、A/B で正解2件を壊した。
(B) **コウ勝ち採用の直前に通常最善の子局面検証**（`_pick_ko_win_move` 末尾）＝役割石 1子平均 >=
ko_success_ownership なら不採用（root スコアは枠の代償地帯で汚れて負に出ることがある＝
実測 b5553318 守り方: root lead −5.78 なのに子局面 +0.99/子）。役割不明の盤では走らない。
(C) **クラス格上げの shortlist は prior 上位 ∪ visits 上位**（visits>=10・min_prior は同じ床）＝
prior 上位だけだと visits 2位・prior 6位の正解手を測り落とす（実測 15fafed5）。
(D) **同深さ検証（score_best 覆し・救済）の役割石両側ゲート**（`_verified_choice` の
`role_context`）＝incumbent が役割石で成立・挑戦者が不成立のときだけ覆しをブロック
（**新しい覆しを許可することは決してない**。挑戦者側だけの成立要求は追記36 で却下済み＝別物。
実測 62a94083: A7 +0.99/子 を合計スケール +5.33 差の B4 −0.56/子 が置換していた）。
検証: E2E 29/29 PASS・フルスイープ A/B で真の誤答 9→3（回復6・修正起因の破損0）。

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


## 詰碁ソルバ戦略（TsumegoSolverStrategy / ai:tsumego_solver）

死活を KataGo なしで厳密に解く戦略（スペック `2026-08-01-tsumego-solver-design.md`）。キャプチャで問題抽出に成功すると枠を張らずこの戦略が設定され、解けない盤・打ち切り・FAILED 裁定は `ai:tsumego` に自動フォールバックする。

**セッション側の挙動（2026-08-01 追記3 の修正。設定キーではなくコード定数）**:

- **root 順序ヒント**（`root_order_hint`、追記5・2026-08-02）: root 候補のスキャン順を KataGo の
  読み順に並べ替える（§6.2「順序は厳密性に影響しない」＝候補の集合・評価・採否は不変で、
  正解が早く incumbent になり floor 刈りが効く）。手番の solve は戦略が渡す `move_visits`
  （現局面）、投機実行はキャプチャ側 provider のクイック解析候補（`HINT_WAIT_S`=1.5 秒まで
  到着を待つ。実測 0.4〜1.0 秒で届く）。実測 2026-08-02（region22 のコウ詰碁・ゲート内なのに
  19.0s native）: 静的順序が急所 C11 を A9/B12/B9 の後に回しフルラダー約 8.5 秒を浪費して
  いた → C11 先頭で 14.3 → **9.5 秒**（2番手 11.6 / 3番手 12.9 と劣化は緩やか、答えは全変種
  KO/ko0・C11 で不変）。P1 スイートはヒント無し＝従来の静的順序のまま

- **証明ストア即答の同格差し替え**（`_prefer_ranked_gate_move`）: 即答の決め手は df-pn が「最初に証明できた手」で、同格別解が複数ある局面では本手と限らない。KataGo の本命が同じ gate を証明し、かつ visits が決め手の `RANK_OVERRIDE_MIN_VISITS_RATIO`(3.0) 倍以上（決定性ゲート）のときだけ差し替える。拮抗別解（実測 1.1 倍）を入れ替えると正解が別解に化けるので比で守る（発火すべき実測は 57 倍）。戦略は `move_ranker` に加え `move_visits` を渡す。検証予算は `RANK_OVERRIDE_MAX_CANDIDATES`(3) × `RANK_OVERRIDE_TIME_MS`(5000)
- **途中再抽出の hint**: `region_hint` は出題時 region の外接矩形を既定にし、GUI は `game.region_of_interest` で上書き。hint なし再抽出は乱れた盤で「デタラメな小問題」に成功しうる（実測: target={K2,K4,K5}/region10点 → SEKI/L1 誤答）
- **再抽出のサニティガード**: 元問題の生存 target 石を新 region が覆わない再抽出は捨ててフォールバック
- **永続キャッシュ**: 再抽出を照会より先に行い、キーを「実際に解いた問題」に揃えた（旧キャッシュは `~/.katrain/tsumego_cache_backup_20260801/` に退避済み）。証明ストア即答もキャッシュに書く
- **永続キャッシュの同格別解並べ替え（CACHE_VERSION 3・2026-08-15）**: 同格タイ
  （root_moves 複数・plies=0）は**別解リストごと保存**し、**ヒット時に現セッションの
  move_ranker（KataGo 本命順）で並べ替える**＝fresh solve の §6.5.1-3 タイブレークの
  遅延適用。旧版は KataGo ランキングを持たないセッション（キャプチャ時の投機実行・
  出題前検算）が最初に証明できた手を1手だけ焼き付け、以後の全セッションがタイブレークを
  素通りしていた（実測 2026-08-15 回答帳 13333f79df: E2/C3/D2 が同格の無条件殺しで
  E2 が焼き付き、本番は D2 v1145 vs E2 v155 なのに E2 を即答して誤答。**cross-check は
  E2 が本当に殺せる別解なので設計どおり無言で通す**＝ここでは捕まらない）。版数繰り上げで
  旧エントリを一掃（既知問題の初回再 solve 1回が代償）。ソルバ経路 A/B（120手順）で
  **回復9 / 破損0**。回帰: `test_cache_hit_reranks_equal_alternatives_with_katago_order`

設定はすべて `tsumego_capture` セクション（§9.3）:

| パラメータ | デフォルト | 備考 |
|---|---|---|
| solver_enabled | true | ソルバモードの有効化（false で常に現行経路） |
| solver_time_limit_ms | **5000** | 1手の solve 時間上限。超過は現行経路へフォールバック。**旧既定 30000 は「1手で1問20秒の予算を丸ごと超えられる」値**で、白が証明ストアに無い分岐へ入ると 30 秒フル探索してから ai:tsumego に落ちていた（実測 2026-08-09: 1問 67〜79 秒が2件）。ソルバ経路90手順の A/B: 30000→5000 で **>20秒が 2件→0件（最大 67.7s→17.4s）・合計 758s→637s・correct 66→65（ノイズ水準 3/90 の内側）**。スペック §9.3 の初期案 3000 に近い値へ戻したことになる |
| solver_node_limit | 20000000 | ノード上限 |
| solver_ko_refine | true | コウの細分 n*（§4.4） |
| solver_ko_budget_max | 2 | n* の探索上限（超えたら ko_level=3=ヨセコウ深い扱い） |
| solver_optimize_line | true | 第2段階（plies/material 最小化）。native は1手あたり 3 秒であきらめて第1段階の解を使う |
| solver_max_alternatives | 8 | 別解リストの上限（§6.5.1） |
| solver_max_region_points | 72 | region 上限（超えたら門前払い→フォールバック。§8.4） |
| solver_cache | true | root Solution の永続キャッシュ（~/.katrain/tsumego_cache/） |
| solver_opt_skip_after_ms | 5000 | 第1段階（分類）がこれより遅かったら第2段階（plies/material 最適化）を省く（追記5）。難問では opt が予算3秒を燃やしてタイムアウトし成果ゼロだった（実測 2026-08-02: 実戦2件とも plies=0 mat=0）。plies==0 の同格タイは既存の KataGo タイブレーク（§6.5.1-3）が GUI で並べ替えるので実害なし。0 以下で常にスキップ |
| solver_fallback | true | フォールバックの有効化（false だと未解決時パス） |
| solver_capture_max_region | 23 | キャプチャ時のソルバモード採用ゲート（region 点数）。P1 実測で**速く**解けたのは region<=23（最大 Q@0 の 11.1 秒）。旧値 26 のマージン帯（24〜26）は実測 29〜59 秒で、初手が df-pn の求解をそのまま待つ＝1問20秒の予算をこの1手で壊す（実測 2026-08-02: region24/空点12 が 29.0s native・着手決定 26.2 秒。spec 追記4）。超過は最初から現行経路（枠張り。1〜3秒/手）＝挙動が完全に従来のまま |
| solver_capture_max_empties | 12 | 同・空点数ゲート（解けたのは空点<=12、空点23+は1800秒でも未達）。旧値 14 は封筒外のマージンだった |
| solver_cross_check | true | **ソルバの答えを KataGo と突き合わせる安全網**（`_solver_answer_rejected`）。「厳密解」は**その抽出した問題の**厳密解でしかなく、抽出が画面の詰碁と別問題でも*解けてしまう*ので出題前検算 `problem_is_hopeless`（FAILED を弾く）はすり抜ける＝ここでしか捕まえられない。判定は**役割石の同深さ ownership の絶対値**（`tsumego_success_ownership` >= `ko_success_ownership`、`gain_verify_visits` で撃つ）。**2段構え**: 第1段はソルバ手だけ測り成立していれば解析1本で抜ける、成立していない手番だけ第2段で KataGo の visits 上位 `TSUMEGO_SOLVER_CROSS_CHECK_CANDIDATES`(2) 手を測る。**却下には「対抗馬が実際に成立していること」を要求する**（片側だけの絶対判定＝`tsumego_declass_confirmed` と同じ非対称性）。答えがコウ/セキで ply1 に成否が出ない局面では両方 <閾値 になり却下しない＝ソルバの答えを残す側に倒れる。**却下は sticky**（`game.tsumego_solver_session = False`）＝却下の意味は「抽出が別問題」で手ではなく問題の性質だから、以降その問題ではソルバを使わない（毎手 solve を繰り返すと 30 秒タイムアウトを何度も踏む）。実測 2026-08-09（回答帳リプレイ・spec `2026-08-09-tsumego-answer-book-replay-design.md`）: 曖昧さのない誤答13件は**全件がソルバ経路**で13件すべて記録手が KataGo の visits 順位0か1だった。ソルバ経路90手順の A/B で **correct 56 → 64（62.2%→71.1%）・改善9件/退行1件（退行は3run中2回正解＝run間変動）・合計時間 986s → 755s**（sticky が 30 秒タイムアウトを消すので**速くなる**）。false で従来動作 |
| solver_verdict_ms | 1000 | **出題前の検算**（`problem_is_hopeless`）の時間予算[ms]。0 以下で検算しない。root を1回解いて **FAILED（手番側は勝てない）と証明されたら抽出が別物**なので solver モードを使わず枠張り経路へ落とす（詰碁は手番側に正解手がある問題＝`frame_destroys_problem` と同じ前提）。**予算内に決まらなければ従来どおり出題**（判定は「間違いだと証明できたか」であって「正しいと確認できたか」ではない＝外し方は現状維持）。1秒で足りるのは壊れた抽出の FAILED は探索するものが無いぶん速く証明されるから（実測 case AD 0.01s / F 0.17s / F2 0.10s＝最遅の約5倍のマージン）。解ける問題（D/E/K/O/Q/V/V2）は予算内に終わらないのでこの秒数がキャプチャに乗る＝上げるほど遅くなる。解けた場合（M 0.07s / Z 0.40s）は永続キャッシュに載り初手が速くなる。実測 2026-08-04 case AD: 出題後に FAILED でフォールバックしても `analysis_region`（4×3の箱）は変えられず正解 C5 を打てなかった＝**出題前でしか救えない**。spec 追記10 |

規模の上限だけでなく**下限**もある（設定キーではなくコード定数。`tsumego_problem.py`）:

| 定数 | 値 | 備考 |
|---|---|---|
| MIN_TARGET_SPACE | 3 | target が使える空間 `space = len(region) - len(target)`（空点 + 眼空間の中の相手の石。ナカデの捨て石も眼空間なので数える＝**空点だけを数えてはいけない**）がこれ未満の抽出は受理しない（`predetermined_reason` → ProblemError → 枠張りへフォールバック）。詰碁は「打つ手で結果が変わる」問題で、space 0〜1＝取るだけ・2＝隣接なら死/離れていれば既に生き＝どちらも手番と無関係、3（直三・ナカデ）が初手で生死が入れ替わる最小の形。実測 2026-08-04 case AC: 開いた中盤の競り合いで実際の戦いの閉包が全部却下され、**呼吸点1の白1子だけ**が閉じて `region 2点/target 1子`（space=1）を出題→ソルバが 0.0s・nodes=1 で「取る」と答えて誤答。正当側の下限は実キャプチャ21ケースで space 6・教科書的な最小題材で 3。全抽出300件の A/B 差分は case I@2 の2件のみでいずれも改善（変更前は正解手が region 外）。spec 追記9 |
| （`_captured_in_one`） | — | **space ゲートの穴を塞ぐ第2の判定**（定数なし）。攻め方の手番で target の全連が呼吸点1かつ唯一の呼吸点が同じ1点なら、region の広さに関係なく1手で取り切れる＝詰碁ではないので受理しない。space は「眼を作れる余地」の代理でしかなく **target の眼空間でない点まで数える**（実測 2026-08-04 case AE: 中身は case AC と同じ「アタリの白1子を取るだけ」なのに、閉包が黒 D8 とその呼吸点 D7 を巻き込んで space ちょうど 3 で素通り→誤答）。全抽出300件の A/B で差分0件＝既存ケースには該当する形が無く、今回の誤りだけを外科的に落とす。spec 追記12 |

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
- **own_rare** = 自手の humanPolicy の意外さ＝要件「humanPolicy が低い高スコア手」の実装
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
`ENIGMA9_W_REPLY_RARE=1.0` / `ENIGMA9_W_OWN_RARE=1.0` / `ENIGMA9_MIN_BUDGET=0.05` /
`ENIGMA9_PONDER_REPLIES=3`（着手後の先読み応手数・0で無効） /
`PRIORITY_ENIGMA_PONDER=-50`（constants.py）

**着手時間の短縮（2026-08-11・精度不変・9路/13路共通・spec 追記3）**:
(1) **親 humanSL クエリの 8visits 化＋バッチ統合**＝`_probe_children(parent_hp=True)` で
子局面プローブと同時発行（旧実装は既定 visits=config max_visits(1000) の humanSL 解析を
逐次で待っていた。humanPolicy は root NN の出力で visits に依らないが **run 間では
TensorRT バッチ非決定性で揺れる**〈別プロセス実測: 1000v 同士でも max|Δ|=0.086・
上位10手の順位入替。8v vs 1000v の差はそのレンジ内〉＝visits を落としても既存分散に
上乗せなし)。
(2) **着手後の先読み（ponder）**＝`_start_ponder`/`_ponder_worker`。着手を返す直前に
選択手の clean プローブから相手の応手 top-3（KataGo 本命 visits 最多 1 手＋humanSL 直感順）を
選び、使い捨て複製ゲームで wave1: 応手後局面を GUI の通常解析と同条件（visits/ownership=
config 解決）で解析 → wave2: その top-8 候補（order 順）の子プローブ（clean 500v +
humanSL 8v）を `_probe_children` と同条件で発行。**結果は全部捨てる＝判定影響ゼロ**。
発火は 自分=AI かつ 相手=人間 のときだけ（`_ponder_applies`。デバッグスタブ／バッチ評価／
AI 同士では発火しない）。残骸の掃除は2段: 主経路 `Game._cancel_enigma_ponder`（**相手の
着手が入った瞬間**に terminate。相手が消化前に応手すると実クエリが温めと GPU を取り合い
1.6→4.4 秒に伸びた実測への対処）＋保険 `_cancel_ponder`（generate 冒頭・GUI を経ない経路用）。
(3) **per-move 時間ログ** `[Enigma13Strategy] 着手決定に X.X 秒`（OUTPUT_INFO＝debug_level 0 でも
ゲームログに残る）。
実測（13路・校正13路局の白番・NN ウォーム）: generate 8局面×2run 平均 1.04→0.89 秒、
先読み**的中時**は次手番の 通常解析+generate 0.92〜1.09 → **0.35〜0.48 秒**
（プローブバッチ 0.45〜0.64 → 0.08〜0.09 秒）。外れた場合は従来どおり。

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

CLI: `python -m katrain_debug --sgf <13路SGF> --move N --strategy enigma13`（batch 可）。
**13路の実戦校正は未実施**（GUI 実戦ログ `[Enigma13Strategy]` と batch 3-run 平均で行う）。

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

CLI: `python -m katrain_debug --sgf <19路SGF> --move N --strategy enigma19`（batch 可）。
**19路の実戦校正は未実施**（GUI 実戦ログ `[Enigma19Strategy]` と batch 3-run 平均で行う）。
