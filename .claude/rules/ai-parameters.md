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

### complexモード（複雑化）

接触戦の密度を最優先に盤面を複雑化する4つ目の `fighting_mode`。`human` モードのパイプライン（2段階クエリ・安全弁・タイブレーク）を再利用し、重み関数と悪手フィルタを差し替える。重み = 力戦重み（unsettled×proximity×contact_boost×invasion_bonus）× 切りボーナス。接触強調は既存 `fighting_contact_boost` を流用（complex時は 2.0〜3.0 推奨）。

悪手フィルタはリード適応: `loss < base閾値`(19路 NORMAL=5.6) は常に通過。`base ≤ loss < relaxed_cap` は「大差リード（current_lead ≥ complexity_lead_threshold）かつ 鋭い（scoreStdev ≥ complexity_sharpness_min）かつ 複雑（複雑さ重みが候補中最大の _COMPLEXITY_WEIGHT_FRAC 倍以上）」の3条件を満たす手のみ通過。`relaxed_cap` はリード差 `_COMPLEXITY_RAMP`(=10目) かけて base から complexity_max_loss まで線形上昇。complex時は安全弁閾値も relaxed_cap まで引き上げ、意図的な予算内損失を温存する。`complexity_base_max_loss`（既定5.6）でリードに関係なく常時このゲート付き帯を上限N目まで開ける。実効上限 = `max(complexity_base_max_loss, lead適応 relaxed_cap)` で動作する。`fighting_max_loss` は scoreloss 専用で complex には無効。

| パラメータ | デフォルト | 選択肢 | 備考 |
|---|---|---|---|
| complexity_cut_boost | 2.0 | 1.0/1.5/2.0/3.0/5.0 | 切り点（相手chain2つ以上隣接）の重みブースト |
| complexity_lead_threshold | 15.0 | 5/10/15/20/25/30 | この目数以上リードで損失緩和を解禁 |
| complexity_base_max_loss | 5.6 | 5.6/6/7/8/9/10 | 互角〜劣勢でも開放するゲート付き帯の上限（目）。既定5.6=現状維持。効く上限=max(これ, relaxed_cap)。無条件パス帯は不変なので、ここを上げてもただの悪手は鋭さ＋複雑さゲートで弾く |
| complexity_max_loss | 10.0 | 6/7/8/9/10/12 | 緩和時の損失上限（リード比例で base→max を10目かけて上昇） |
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
| tie_ko_screen | true | **コウ経路検査（クラスの裁定）**: 選択パイプライン（同着バンド → score_best 同深さ検証 → 救済）が手を決めた**後**に1回だけ走る。**子局面解析は歩く深さぶんリージョン外を禁じて撃つ**（`TSUMEGO_KO_REGION_UNTIL_DEPTH` = `TSUMEGO_TIE_KO_PLIES` = 6。既定のリージョン解析 `untilDepth=1` は root の着手選択しか縛らず、**PV は ply2 以降で枠へ手抜きして肝心のコウが現れない**＝実測 case P: 検出 1/4 → untilDepth=6 で 4/4、無条件の正解はどちらでも 4/4 clean）。選択手が目数ガード内のとき（`tsumego_class_screen_applies`。**対抗馬が0手でも走る** — 旧 `len(pool)>=2` は「選択手がガード外＝検査しない（case F2）」と「対抗馬が居ない＝むしろコウ脱出のトリガー」を混同していて、root が1手に visits を集中させると機構が丸ごと no-op になった＝実測 case T）、ガード内の対抗馬（visits 降順・選択手込み計4手=`TSUMEGO_TIE_KO_MAX_CANDIDATES`）を対象に、各候補を1手進めてリージョン限定 gain_verify_visits で解析し、**[候補手自身]＋守り方の拮抗応手（visits比 0.5=`TSUMEGO_KO_REPLY_RATIO` 以上・最大3本=`TSUMEGO_KO_REPLY_MAX`）の PV** がリージョン内のコウ形（1子取り・取った石が呼吸点1・取り返しがコウ禁止）に到達する候補をコウ経路と判定する（`tsumego_candidate_reaches_region_ko`。候補自身がコウ形なら解析クエリ不要で確定。PV深さ6=`TSUMEGO_TIE_KO_PLIES`）。**判定はもう1本ある**: 歩きの途中で**守り方がコウ取りを「打てる状態」になった**ら、PV がそれを打たなくてもコウ経路（`tsumego_defender_ko_points`、深さ `TSUMEGO_KO_AVAIL_PLIES`=5）。リージョン解析は `untilDepth` で守り方からコウダテを取り上げるので、コウを仕掛けることが守り方の純損になり、**コウが争点の局面ほどエンジンはそのコウを打たない**＝PV を証拠にする判定が肝心なときに黙る（実測 case U 2026-07-31: コウを作る白 C1 は visits比 **0.01**・PV にコウ手 E1 が無く、比 0.00 まで全応手を歩いても検出 0/5 run。「打てる状態か」で見れば **5/5 run で ply5** に立ち、正解 C1 は 5/5 clean）。**候補手より前から打てたコウは数えない**（局面の性質であって候補の性質ではなく、数えると全候補が一律コウ経路になる。実測 case T の L1 / case F2 の N9 / case Q の M13 は着手前から打てるコウで、いずれも従来判定が別途拾っている）。**深さを 5 で切るのは、この証拠が PV より弱いぶん偶発コウを拾いやすいから** — 実測の両側は 検出すべき U ply5・L ply3・P ply3・F ply3/5・R(D8) ply5 に対し、clean のままにすべき **G2 の正解 C13 と R の C8 が ply7**（`ko_available_probe.py` で両側を測ってから動かすこと）。選択手がコウ経路で clean な対抗馬がいれば visits 最多の clean へ格下げ（`tsumego_class_screen_pool` / `tsumego_declass_choice`）＝詰碁の順序 無条件 > コウ の適用。**格下げ先は目数同着バンド（`points_epsilon`）内に限る**＝クラス裁定は同着の裁定であって実測の目数差を覆す権限は無い。**「無条件」は「攻めないので何も起きず自明に clean」でも成立する**ため、答えがコウの詰碁では格下げ先が正解を押しのける（実測 case R 2026-07-31・枠なし: 正解 G13=コウ pt+0.03 を、無関係な D8=clean pt+0.55 に差し替えて誤答）。ownership での検算は効かない（同深さ800visits の全リージョン石で正解 G13 +0.86/+0.97 < 誤答 D8 +1.32/+2.34、相手石は全候補 −0.55〜−0.72＝答えがコウなら ply1 に成否が出ない）。符号が一貫するのは目数だけで、格下げが正しい4ケースは格下げ先が必ず優る（K −0.05 / L −0.11 / M −0.57 / P −0.03）のに case R は +0.52 劣る＝0.25 で両側 0.26 以上の余裕。**ただし目数バンドで塞げるのは「非解が目数で劣る」形だけ**で、**非解が目数でむしろ優る**局面は素通りする（実測 case V 2026-07-31・13路右上・枠あり: 正解 L12=コウ/最終セキ pt−0.29 を、白が無条件で生きる K10=clean pt−0.33（0.04 良い＝バンド内）に差し替えて誤答）。そこで**役割が読めるなら格下げ先が本当に解いているかを確かめてから差し替える**（`tsumego_declass_confirmed`＝格下げ先の子局面を同深さ `gain_verify_visits` で解析し、**役割石**の1子平均 >= `ko_success_ownership`(0.5)。case R の「効かない検算」は全リージョン石を**両者の比較**に使ったもので、こちらは**格下げ先だけの絶対判定**）。実測の分離は 格下げが正しい4ケース（K C13 +0.99 / L J6 +0.99 / M K1 +0.98（守り方・自石）/ P J1 +0.99）と case V の K10 **−1.00** の間に約 2.0 の空白。答えがコウの詰碁では正解も ply1 では成立しない（case V の L12 も −1.00）が、判定を格下げ先にしか課さないので「格下げしない＝コウを維持」に倒れる。****枠なしで役割が読めなくてもこの確認は走る**（尺度は `tsumego_success_ownership` と同じ「自石・相手石の1子平均の**小さいほう**」＝実測 case W 2026-08-01・13路右下枠なし・黒は守り方: 正解 H1＝コウで黒生き pt+2.20 を、黒が無条件死する J1＝clean pt**+1.94＝目数最善**、に格下げして誤答＝バンドは構造的に無力。同深さ800visits の自石7子 H1 +0.51/+0.35 vs J1 −0.22/−0.21。外し方が「格下げしない＝コウを維持」に倒れるので枠なしでも安全側）。測れなかった場合だけ従来どおり**（バンドのみ）。解析は格下げが起きようとしている手番でのみ1本増える。**裁定には格上げ方向もある**（`tsumego_result_class` / `_ko_promotion_choice`）＝詰碁の順序で最下位なのは「相手が無条件で生きる／自石が無条件で死ぬ」＝**失敗**なので、**選択手が clean かつ役割石の絶対判定で失敗しているなら、コウ経路の手のほうが上位**。root policy 上位（`ko_escape_candidates` 本・`ko_escape_min_prior` 以上）を同深さで測り、無条件で成立する手 > コウ経路の手 の順で採る（実測 case V2 2026-07-31: 正解 N13＝コウ pt+7.97・v17・prior 3位 が目数ガードの外に居て、選択手 K10 も対抗馬 L11 も L13 も **全部 -1.00/子＝白が生きる**。分離できるのはクラスだけ）。**コウ経路は「成立している」と読めてもコウのまま**（コウ手の値は「コウに勝った前提」で高く出るので繰り上げると格下げが無意味になる）。**通常の手番では解析0本**＝root の movesOwnership で先に振るい、成立していれば即スキップする（実測: 枠あり8ケースの正解手は全部 +0.98〜+1.00）。役割が読めない枠なしでは走らない。選択手が clean なら検査1本で終わる。**旧設計（同着バンド内だけ検査）は case M で破れた**: コウで殺す手の gain は「コウに勝つ前提」で相手石を取り切る実信号（+1.9 で単独首位）になりバンドから抜け出し、同深さ検証も +1.29 でコウ側を追認する＝gain・目数・検証値のスコア系メトリックはクラスを分離できず、分離できるのは構造検出だけ。**ガード外の救済採用手は検査しない**（実測 case F2: 枠なし盤ではガード内の clean 手が「スコアだけ良い失敗手」でありえ、正解 N11 が偶発コウ形で J10 に差し替わった）。**応手は拮抗分を全部歩く**（実測 case M: コウ仕掛け K1 v144 と穏健 M4 v103 が拮抗し、top 1本では 3run 中 2 でコウを見逃した）。**検査の子局面解析は wideRootNoise=0 で撃つ**（`TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`）— root の Dirichlet ノイズは run ごとに引き直され応手の visits 比を揺らす（visits を増やしても消えない）。実測 case M の M2 子局面: wRN=0.04 で K1 の比 0.44〜0.88（本番フロー 3/6 で 0.5 を割り検出漏れ）→ **wRN=0 で 0.15 が 4/4 不動**（M4 v663/K1 v100/残り v1）。旧 0.5 ゲートは「ノイズが本物のコウ応手を水増ししてくれた時だけ当たる」偶然の産物だった。**選択手だけ敏感な比 `TSUMEGO_KO_REPLY_RATIO_CHOSEN`(0.05) で検査する**＝選択手のコウを見逃すとクラス裁定が丸ごと no-op になりコウ手がそのまま打たれる唯一の経路だから。格下げ先候補は保守側 0.5 のまま（過検出は全員コウ→脱出の誤爆に化ける）。**単一閾値では分離できない**実測: 検出すべき最小 0.09（K A12）＜ clean のままにすべき最大 0.16（R J13）で逆転している。実測のコウ形: case K=応手 A11→B11 / case L=候補 L5 自身の1子取り / case M=応手 K1 の PV の B M4。E2E 回帰は generate_move_e2e.py（**V: L12 3/3**（格下げ先の成立確認を入れる前は K10 3/3）/ **V2: N13 3/3**（クラス格上げを入れる前は K10 3/3）/ **M: K1 8/8**（wRN=0 化の前は 1〜3/6）/ K: C13 3/3 / L: J6 3/3 / P: J1 3/3 / O: A11 3/3 / J: N10 3/3 / F2: N11・M12 コイン投げ / **U: C1 3/3**（旧実装は A3）/ **F: N8 3/3**（脱出の成立判定を入れる前は J11/J10/N11 に飛んでいた）/ R: G13 3/3 / G2: C13 2/2 / H: N4 2/2 / E: K1 2/2 / D: A4 3/3）。**case R の救済経路は `TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO`(0.15) で塞いだ**（救済トリガーが消え、格下げバンドが設計どおり働く）。残る揺れは**リージョン root 解析（1800visits・wRN=0.04＝着手選択のクエリなので変えられない）の visit 配分の分散**で、稀に J13/C8 が select 段階で選ばれる。答えがコウの詰碁は ply1 の ownership も目数も成否を運ばないため、**case I / case Q と同じエンジン側の限界枠**（spec 追記26）|
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
| ko_escape_tolerance | 0.5 | **採用条件の許容幅。不等号の向きに注意** — 「incumbent を上回る」ではなく「tolerance 超えて**下回らない**」（`tsumego_ko_escape_accepts`）。**ただしこの相対条件だけでは採用しない**: 先に「その手で詰碁が成立しているか」を役割石の**1子平均 ownership >= `ko_success_ownership`(0.5)** で絶対判定する（`tsumego_ko_escape_succeeds`）。相対条件は incumbent 自身が失敗している局面で退化し、全候補が横並びになってノイズ幅で1手が「最良」に選ばれる（実測 case F 2026-07-31: 選択手 N8 −9.72 に対し policy 上位 J11 −9.82 / J10 −9.86 / N11 −9.90 / M12 −9.89 が全部 tolerance 内に並び、**0.08 差**で J11 が採用されて N8 が捨てられた。1子平均は全員 −0.97〜−0.99＝どれも解いていない）。分離幅は桁違いで、採るべき手（O の正解 A11 +0.99/子・T の正解 L1＝セキ +1.00/子）と落とすべき手（O の失敗 clean C13/B13 −1.00/子・F の全候補 −0.97〜−0.99）の間に約 1.9 の空白がある。コウ手のスコアは「コウに勝った前提」で出るので無条件の正解より**むしろ高い**（実測 同深さ800visits・リージョン内42子: コウの B12 +41.95 > 正解 A11 +41.85）。既存の覆し `tsumego_override_confirmed`（gain_verify_margin 0.3 超えで上回ること）を使うと正解が却下される。順序を決めるのはクラスであってスコアではなく、スコアは「その手で本当に詰碁が成立しているか」の確認にだけ使う。失敗する clean 手は同じ尺度で +18.5〜+18.8（−23）まで落ちるので 0.5 で十分に分離できる。**この非対称性が安全弁**: 答えが本当にコウの詰碁では clean 候補が ownership 検査を通らず、脱出は何もせずコウを維持する |

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

検証は GUI 実戦のみ（deception は trajectory 形成型で batch 評価不可）。CLI: `python -m katrain_debug --sgf <9路SGF> --move N --strategy jigo9`。Spec: `docs/superpowers/specs/2026-06-04-jigo-9x9-dedicated-mode-design.md`


## 詰碁ソルバ戦略（TsumegoSolverStrategy / ai:tsumego_solver）

死活を KataGo なしで厳密に解く戦略（スペック `2026-08-01-tsumego-solver-design.md`）。キャプチャで問題抽出に成功すると枠を張らずこの戦略が設定され、解けない盤・打ち切り・FAILED 裁定は `ai:tsumego` に自動フォールバックする。設定はすべて `tsumego_capture` セクション（§9.3）:

| パラメータ | デフォルト | 備考 |
|---|---|---|
| solver_enabled | true | ソルバモードの有効化（false で常に現行経路） |
| solver_time_limit_ms | 30000 | 1手の solve 時間上限。超過は現行経路へフォールバック（スペック §9.3 の 3000 は P4 完了後に再検討） |
| solver_node_limit | 20000000 | ノード上限 |
| solver_ko_refine | true | コウの細分 n*（§4.4） |
| solver_ko_budget_max | 2 | n* の探索上限（超えたら ko_level=3=ヨセコウ深い扱い） |
| solver_optimize_line | true | 第2段階（plies/material 最小化）。native は1手あたり 3 秒であきらめて第1段階の解を使う |
| solver_max_alternatives | 8 | 別解リストの上限（§6.5.1） |
| solver_max_region_points | 72 | region 上限（超えたら門前払い→フォールバック。§8.4） |
| solver_cache | true | root Solution の永続キャッシュ（~/.katrain/tsumego_cache/） |
| solver_fallback | true | フォールバックの有効化（false だと未解決時パス） |
