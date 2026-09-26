# 韜晦（9/13/19路）戦略 ai:veil9 / ai:veil13 / ai:veil19 設計

日付: 2026-09-23
対象: `katrain/core/ai.py`（veil 純関数群 + `Veil9Strategy` / `Veil13Strategy` / `Veil19Strategy`）
状態: 実装済み（2026-09-24）・13路は自己対局ハーネスで測定し、2026-09-25 のユーザーの決定で既定を段階1b の loose に変えた（値は §6.1 の表の直後の段落。安全条件は据え置き。自分の一致率は loose の 3 run 平均 45.2%・spec の初期値 51.5% で目標 30% に届かず、下限は構造的。接戦ストレス〈AI 不利 4 目・HumanStyle 9段・20 対〉で §10.4 (a) 勝ちの安全は初期値・loose とも 20-0 で可）・失着の層（§13・2026-09-25）は既定 OFF・決着局面の即決（§4 S13）は打つ前に best と候補の2手をプローブで確かめる（2026-09-25）・最善手しか無い手番の外し（§14・2026-09-25）は既定 OFF で、ON にしたときだけ要件1を「20局に1局ほどの負けは許す」に緩める（13路のハーネスで一致率 44.1% → 38.5%・通常 20-0・接戦ストレス 40-0 で合格＝§14.5）・9路・19路は未校正・実戦校正は未実施（詳細は `calibration-data/selfplay/veil13-campaign.md`）・画面の名前はユーザーの決定（2026-09-25）で「一致率ひかえめ（9路／13路／19路）」に変えた（英語は Veil のまま・設定キー `veil*_` と戦略キー `ai:veil*` は変えない）・序盤の研究外し（§15・2026-09-26・実装済み〈計画 `2026-09-26-veil-opening.md`〉）は既定 OFF で、ON にしたときだけ序盤の窓の手番を同じ盤サイズの難解＋にユーザー設定のまま任せる（窓の中は要件1・5・7の代わりに難解＋のユーザー設定の挙動）・9路の校正と研究外しの効果の計測は §16（計測済み〈2026-09-26〉・結果 §16.6）

## 0. 一言で

勝ちを最優先にしたまま、**自分の AI 最善手一致率（終局レポートの値）を絶対目標（13路 30%）まで下げる**戦略。
ほぼタダの外し（同値外し）は常に行い、損をする外しは「一致率が目標を超えているとき」に限って
リードの余剰から払う。擬態（`ai:mimic13`）の後継だが、擬態は変更しない（別クラス・別キー）。

## 1. 要件（ユーザー確認済み・2026-09-23）

1. **勝ちが最優先**（小差でも大差でも勝てばよい）。外しで勝ちを負けに変えない。安全条件は緩めない
   （既定は安全側：13路でリード5目を残す・着手後勝率 85% 以上）。
2. **一致率は KaTrain の終局レポートの値**（自分・相手とも）。避ける最善手はレポートと同じ定義
   ＝親局面の通常解析の `candidate_moves[0]`。
3. **目標は絶対値**（13/19路 30%・9路 40%。スライダー）。「相手より低い」は目標にしない
   （相手の一致率はログに出すだけ）。理想帯は 15〜35%。15% 未満へ無駄に払わない。
4. **1手の損失上限を広げる**（勝勢で 13路 4.5目まで）。勝勢の「緩み」が見えやすくなるのは承知。
5. 手番の3段:
   - (i) 候補が最善手しか無い → 最善手（常に）
   - (ii) 候補はあるが最善手の humanPolicy が圧倒的（既定 0.8 以上）→ **一致率が目標を超えているときだけ**外す
   - (iii) それ以外 → 許容損失の範囲で外す。**ほぼ損失ゼロの外しは常に**（互角の序盤・ヨセも含む）。
     損をする外しは一致率が目標を超えているときだけ
6. 「候補」＝最善手から許容損失以内 かつ 人間が打ちそうな手（humanPolicy が床以上）。許容損失は
   互角で約 0.3目、勝勢はリードの余剰に連動して広げる。
7. 人間らしい手を選ぶ（難解＋のような hp 2% 級の珍手は打たない）。予算が外す**回数**に変わること
   （擬態は「最安の1手」を選ぶので予算 5目が余っても回数が増えなかった）。
8. 罠（難解型の E/ΔE）は**切り替えオプション**にし、素直な外しとどちらが一致率を下げるかを A/B で測る。
   罠の手は難解と同じく「相手を騙す手」なので自然さの床を免除する（hp >= 0.02。擬態の罠資格と同じ考え方）。
   A/B の「罠 ON」はこの免除込みの1パッケージとして測る。
9. 9・13・19路すべて（難解と同じく盤サイズ別の独立戦略）。既定値は 13路で校正、9/19路は未校正で出す。
10. 検証は自己対局ハーネス（新規）→ 実戦の順。

## 2. 実測（設計の根拠）

### 2.1 既存戦略の実戦（13路・事後 2500v 再解析・18局・2026-09-18）

| 戦略 | 局数 | 自分の一致率 | 相手の一致率 | 自分<相手 | 損失/手（自分） |
|---|---|---|---|---|---|
| 難解＋13路 | 16 | 54.2%（局ごと 43〜63%） | 23.2%（11〜32%） | 0/16 | 0.96 |
| 擬態13路 | 2 | 44.7% | 13.6% | 0/2 | 0.50 |

- 相手の一致率は 18局で 局平均 22.2%（SD 6.8pt）・全手まとめ 21.8%、損失 1.74目/手（≥2目 28%・≥5目 10%）。
  難解＋16局だけなら 自分 局平均 53.3%・相手 局平均 23.1%（SD 6.5pt）。全局 AI 勝ち。
- HumanStyle 9段の一致率は旧フィルタ（閾値 1.5・二段階フィルタ導入前）で 13路 42.5%、閾値 1.0 で 73.3%
  （`ai-humanstyle.md:97-106`。現行 1.2 は未測定＝ハーネスの参照アームで測る）＝強い打ち手は自然に一致率が高い。

### 2.2 擬態が 45% に留まった内訳（103手番）

| 区分 | 手番 | 一致 |
|---|---|---|
| 支配ガード（最善手 hp>=0.8 は無条件で最善手） | 23% | 全部 |
| 代替なし・資格なし | 9% | 全部 |
| ヨセの 9段委譲 | 21% | 41% |
| 外した（事後で一致扱い約 8%） | 47% | — |

支払い上限 λ は 5.00 に張り付いていた＝**予算は余っていた**。律速は「外してよい手番の在庫」と
「最安1手を選ぶ規則」。

### 2.3 代替手の在庫（難解＋ 626手番・visits>=10・生の relativePointsLost）

| 最安の代替手 | ≤0.1 | ≤0.3 | ≤0.5 | ≤1.0 | ≤2.5 |
|---|---|---|---|---|---|
| 全体 | 29% | 38% | 45% | 56% | 72% |
| 序盤 <30手 | 37% | 52% | 63% | 73% | — |
| 中盤 30〜84手 | 21% | 25% | 31% | 43% | — |

- 最善手の prior >= 0.8 は 26〜27%。visits>=10 の代替が無い手番 12%。
- 生の損失は検証すると悪化しうる（生 ≤0.1 / 0.1〜0.2 / 0.2〜0.3 の帯で、検証後 0.3目超が 12 / 25 / 44%）。
- 13路の互角付近の勝率勾配は約 19%/目（`enigma-gamble` spec）＝0.3目の同値外しでも勝率が約 6% 動く。

### 2.4 本設計の見込み（反実仮想・KataGo 不要）

スクリプト: scratchpad `cf_absolute.py` / `cf_absolute2.py`（設計時の一時置き場。ハーネス spec §10 の
移設対象）。18局の行データに**本設計を近似した規則**を当てはめ、リード軌跡を補正（実際の AI の支出を戻し、
本設計の支出を引く）。近似の中身: 同値外しは |lead| < 3 で 0.16目まで（互角付近の勝率勾配 19%/目で
1手の勝率低下 3% に相当）・ヨセで lead < reserve なら 0.05目まで、明らかな一手は KataGo の prior >= 0.8 で代用、
自然な代替である確率 q=0.85（明らかな一手 0.6）、接戦の累計上限なし（§6.1 の既定どおり）。

| 近似モデルの設定（勝ちの安全条件は維持） | 自分の一致率（平均） | 下位10%の局 | 15〜35% の局 |
|---|---|---|---|
| 1手 2.5目まで（審査時の既定） | 約 50% | 38% | 6% |
| **本設計の既定（1手 4.5目・ヨセ 1.5目・目標 30%）** | **約 46%** | **33%** | **13%** |
| 1手 6目まで | 約 45% | 32% | 14% |
| 参考: 安全条件をすべて外す | 約 32% | 27% | 67% |

一致したまま残る手番の内訳（本設計の既定・q=1）: 許容損失より高い代替しか無い 15%・代替なし 12%・
リード 5目未満でほぼタダ以外は不可 10%。**支払う損失は平均 0.3目/手で、予算は律速ではない**。

**この見込みは粗い**（最安の1手しか見ていない・visits>=10 の行だけ・誤差 ±10pt）。本設計は読みの浅い
自然な候補も子局面で検証するので在庫は多めに出うる。本当の値はハーネスで測り、境界線（一致率 vs
勝率・損失）を見てから既定値を決める（§10）。

## 3. 構成

```
Enigma9Strategy（ai.py:2894。子局面プローブ・終局帯・ログ・フェイルセーフの土台）
  └ Veil9Strategy     @register_strategy(AI_VEIL_9)   BOARD_LEN=9  KEY_PREFIX="veil9"
      ├ Veil13Strategy @register_strategy(AI_VEIL_13) BOARD_LEN=13 KEY_PREFIX="veil13"
      └ Veil19Strategy @register_strategy(AI_VEIL_19) BOARD_LEN=19 KEY_PREFIX="veil19"
```

- 13/19路はクラス属性（`BOARD_LEN` / `KEY_PREFIX` / `LABEL` / `SETTING_DEFAULTS` / `VEIL_BOARD`）だけ差し替える
  （Enigma13Strategy ai.py:3888・Enigma19Strategy ai.py:4021 と同じ形）。
- `_generate_move` を上書きする（Mimic13 ai.py:4238-4407 と同じ形）。難解・難解＋・擬態はビット同一。
- **継承して使うもの**: `generate_move`（所要時間ログ ai.py:3443-3452）、`_setting`（2950）、`_log`（2968）、
  `_best_move`（2971）、`_run_query`（2994）、`_probe_children`（3022-3102）、`_cancel_ponder`（3121）、
  `_terminal_band_move`（3355）。
- **再利用する純関数**: `parity9_is_endgame`（1613）、`parity9_build_candidates`（1634）、
  `parity9_match_tally`（1544・比較用）、`enigma9_hp_lookup`（2177）、`enigma9_shortlist_spread`（2250）、
  `enigma9_verified_metrics`（2317）、`enigma9_reply_table`（2335）、`enigma9_expected_punish`（2370）、
  `enigma9_reply_findability`（2386）、`enigma9_pass_loss` / `enigma9_human_top`（2572。盤上最上位の gtp・hp と
  pass の hp）/ `enigma9_terminal_pass` / `enigma9_terminal_move`（2560-2631）、`mimic_hp_top`（4108）、
  `mimic_natural_floor`（4114）、`_AREA_PASS_MARGIN`（783）、`ENIGMA9_TRUSTED_VISITS`（2026）。
- **使わないもの**: HumanStyle への委譲（擬態のヨセ委譲・難解の序盤委譲）、rarity / net / 消費モード、
  ΔE 床、`mimic_choose`、Stage2（wRN=0）の損失、**ponder（先読み）**。

### 3.1 ponder を使わない理由（v1）

難解系の ponder は監視モードで自ノードのフル解析を後回しにする（`_enigma_ponder_defers_own_analysis`、
game.py:620-660）。相手が温め完了前に応じると、**相手の手がレポートで 200v の最善手と比べられる**
＝相手のレポート一致率の基準が揺れる。本戦略は ponder を起動しないので、この経路に入らない。
遅延は 1手約 1〜2 秒（13路）を見込む。遅いと判明したら v2 で「自ノード解析を後回しにしない」
フックつきで足す。

## 4. 1手の決定フロー（`Veil9Strategy._generate_move`）

**S0 ラッパー**: 本体を try/except で包む。`AnalysisDiscardedException`（ai.py:505-507）は再送出、
それ以外は OUTPUT_ERROR をログして `_best_move`（実装時の改訂 2026-09-24: ほかの出口と同じく `Decision:` 行〈tier failsafe・kind best・why `exception`〉と ledger も残す。記録に失敗しても最善手は打つ）。

**S1 前処理（クエリ0本）**
- `self._cancel_ponder()`（前に動いていた難解の ponder の後始末。走っていなければ何もしない）。
- `self.game.board_watch_probe_warm = False`（難解が立てたままだと監視の先読みが Probe の温めを続ける）。
- `self.wait_for_analysis()`（ai.py:584-591）。
- `self.last_decision_info = {}`。
- sticky な状態は `game._veil_state[KEY_PREFIX]` の dict 1個に置く: `endgame`（ヨセフラグ）、`close_drift`
  （接戦中の同値外しの累計。`close_drift_cap` が 0 なら使わない）、`ledger`（手ごとの (depth, best_gtp, played, kind)。
  ハーネスが「意図とレポートの食い違い」を数えるのに使う）。`Game` は対局ごとに作り直されるので自動でリセットされる。

**S2 盤サイズ**: `max(board_size) != BOARD_LEN` なら INFO ログを出して最善手。

**S3 最善手**: `cands = cn.candidate_moves`。空なら最善手。`best_gtp = cands[0]["move"]`
（レポートと同じ。子局面の書き戻しは order を変えない＝game_node.py:237-252）。best が pass なら pass。

**S4 一致率（クエリ0本）**: `veil_tally`（§5）で自分の一致数 mine / 分母 n、相手の一致数（全手・
切り揃えなし）を数え、`p_match = (mine+1)/(n+1)`（この手も一致させた場合の率）と緊急度 u を出す。
`Rate:` 行をログに出す。

**S5 リード**: `lead = cn.analysis["root"]["scoreLead"] × sign`（打つ側視点）、root の勝率も打つ側視点。
lead が None なら最善手。

**S6 ヨセ判定（sticky・クエリ0本）**: `depth >= endgame_move` のとき
`parity9_is_endgame(depth, cn.analysis.get("ownership"), …)`。ownership が無ければ手数だけで判定。
Probe は撃たない。

**S7 相手の直前パス**: `cn.move` がパスなら、**pass_loss の値に関係なく** `super()._terminal_band_move(cands, player)`
を呼び、None 以外ならそれを返す（従来の難解と同じ。pass_loss < 0.5 なら即パス、そうでなければ ownership の
Probe を1本撃ち `enigma9_board_settled` ならパス・未決着なら最善手＝中国ルールで死石が残って pass が
大損に出る終局でも外しに進まない。game_20260828_065952 の回帰を再発させない）。

**S8 終局帯**（`enigma9_pass_loss(cands) < _AREA_PASS_MARGIN` かつ相手が直前にパスしていない）
- (a) 親局面の humanSL を1本撃つ（S11 と同じクエリ）。`enigma9_human_top` で (top_gtp, top_hp, pass_hp)、
  `enigma9_hp_lookup` で best_hp、`mimic_hp_top` で hp_top を出し、自然さの床と dominant を S12 と同じ定義で決める。
- (b) `enigma9_terminal_pass(pass_loss, pass_hp, top_hp)` が真ならパス。
- (c) `veil_terminal_swap`: 最善手でも pass でもなく、visits >= `VEIL_TERMINAL_MIN_VISITS`(10)、生の loss <=
  `VEIL_TERMINAL_MAX`(0.10)（|lead| < `VEIL_TERMINAL_CLOSE_LEAD`(3) なら `VEIL_TERMINAL_CLOSE_MAX`(0.05)）、hp >= 床、
  の手のうち hp 最大（ダメ詰めの順番入れ替え＝レポート上の不一致）。dominant かつ u == 0 なら不可。
  `close_drift_cap` > 0 かつ |lead| < 3 なら、生の loss を累計に足して上限を確かめる。
- (d) `enigma9_terminal_move(top_gtp, cands)` の手。best でなければ、その1手だけを (c) と同じ `veil_terminal_swap` に通す
  （自然さの床は 0.0＝9段の最上位は定義上自然）＝(c) と同じ安全条件（dominant かつ u == 0 なら不可・visits >=
  `VEIL_TERMINAL_MIN_VISITS`・生の loss 上限 0.10 / 0.05・`close_drift_cap`〈効くかは `veil_terminal_capped`〉）を満たすときだけ
  打ち、打つ前に (c) と共通の確定（`_veil_terminal_commit`＝不変条件・接戦の累計への加算）をする。通らなければ
  why = `terminal_finish_rejected` で (e)（実装時の改訂 2026-09-24・コミット d92cd71 / 5336664）。
- (e) 最善手。

**S9 予算**: §6 の式で F_eff（同値の閾値）・S（余剰）・A_t（支払い枠）・cap_phase（ヨセ前 max_loss／ヨセ中 yose_max_loss）を出す。

**S10 生の候補プール（クエリ0本）**: `pool0 = parity9_build_candidates(cands, player, min_visits=1)` から best と pass を除く。
- 自然用: 生の loss <= `raw_cap = max(F_eff, A_t) + VEIL_RAW_MARGIN(0.3)`。生の損失はノイズが大きく検証で救える手があるので
  足切りに余裕を持たせる。
- 罠用（罠 ON のときだけ）: 生の loss <= raw_cap + `VEIL_TRAP_RAW_EXTRA`(1.0)。hp の条件は S12 の後で掛ける。
- 両方とも空なら段(i)＝最善手（クエリ0本）。

**S11 親局面の humanSL（1本）**: `_run_query("parent hp", include_policy=True, ownership=False,
visits=ENIGMA9_HP_CHILD_VISITS, extra_settings={"humanSLProfile": ENIGMA9_HUMAN_PROFILE, "ignorePreRootHistory": False})`
（擬態 ai.py:4305-4316 と同形）。`enigma9_hp_lookup` と `mimic_hp_top` で best_hp と hp_top。失敗なら最善手。

**S12 段の判定と自然さ**
- `dominant = best_hp >= dominant_hp`。dominant かつ u == 0 → 段(ii) 閉＝最善手（プローブ0本）。
- dominant なら許容損失を絞る: `A_t' = min(A_t, dominant_max_loss)`、自然用の raw_cap を
  `max(F_eff, A_t') + VEIL_RAW_MARGIN` で掛け直す。dominant でなければ `A_t' = A_t`。
  **`dominant_max_loss` は上限を絞るだけで、広げることはない**。
- 自然さの床 `veil_natural_floor`: dominant なら `min_human_policy`、それ以外は
  `max(min_human_policy, natural_ratio × hp_top)`（`mimic_natural_floor` と同じ）。hp >= 床の手を自然な候補とする。
- 罠用の候補: 罠プールのうち hp >= `VEIL_TRAP_MIN_HP`(0.02) の手（自然さの床は免除＝要件8）。
- 自然な候補も罠用の候補も無ければ段(i)＝最善手。

**S13 決着局面の即決（best と候補の2手だけプローブ）**: root 勝率 >= `VEIL_DECIDED_WR`(0.97) かつ
lead >= reserve + `VEIL_DECIDED_MARGIN`(3) かつ dominant でないとき、自然な候補のうち生の loss <= F_eff かつ
visits >= trusted_visits の手があれば、生の loss を cost として S18 と同じ帯の規則で打つ（同点は hp → 生の loss → gtp）。
接戦ではこの経路を使わない（生の ≤0.3目の手のうち検証後の勝率低下 ≤3% を満たすのは 44% しかない）。
打つ前に best と候補の子局面をクリーン 500v＋hp でプローブし、`veil_decided_verified_ok`（vloss <= F_eff + 0.3・
lead − vloss >= reserve・着手後勝率 >= min_winrate）を満たさなければ打たずに S14 へ進む（2026-09-25 追記:
生の loss だけで打っていたため、生 0.36 目 → 実損 16.3 目の手で勝ちを持碁にした＝接戦ストレス blunder13-on-p3
seed 1010）。

**S14 検証する候補（`veil_shortlist`）**
- 自然枠: その手番で合格しうる帯（u > 0 かつ S > 0 なら raw_cap 以内、それ以外は F_eff + VEIL_RAW_MARGIN 以内）の
  自然な候補から hp 降順に `probe_hp` 手、残りの自然な候補から生の loss が安い順に `probe_cheap` 手
  （`VEIL_BOARD`: 9/13路 3+2、19路 3+1）。
- 罠枠（罠 ON のときだけ）: 罠用の候補のうち自然枠に入らなかった手から、`enigma9_shortlist_spread` で
  loss の範囲に等間隔に `VEIL_TRAP_PROBES`(3) 手（trusted_visits は `ENIGMA9_TRUSTED_VISITS`）。

**S15 プローブ**: `_probe_children([best]+shortlist, player)`（候補1手ごとに clean 500v と humanSL 8v を1バッチで並列発行）。
best の検証値が欠けたら最善手。候補ごとに:
- `enigma9_verified_metrics` の lead_after / wr_after、`vloss = best_lead_after − lead_after`、
  `wr_drop = wr_best_after − wr_after`
- `cons = veil_cons_loss(vloss, raw, visits, trusted_visits)`＝`max(vloss, raw)`（raw は visits >= trusted のときだけ）。
  **帯の計算・予算との比較・累計には `max(0, cons)` / `max(0, vloss)` を使う**（500v のノイズで負になりうるため）。
- E・ΔE・find_hp（`enigma9_reply_table` / `enigma9_expected_punish` / `enigma9_reply_findability`）。
  **罠 OFF でも計算してログに残す**（追加クエリ0本）。ただし罠 OFF で数えられる「使えたはずの罠」は、
  プローブした自然な候補の中のものだけ（罠枠の手はプローブしていない）。

**S16 分類（`veil_classify`）**（c = max(0, cons)。接戦 close = lead < reserve または wr_best_after < `VEIL_CLOSE_WR`(0.9)）

| 種類 | 条件 |
|---|---|
| free（同値外し） | 自然な候補 かつ c <= F_eff かつ (wr_drop <= free_wr_drop または wr_after >= VEIL_DECIDED_WR) かつ ヨセでは (lead_after >= reserve または wr_drop <= `VEIL_YOSE_FREE_WR_DROP`(0.01)) かつ (`close_drift_cap` > 0 で close なら close_drift + max(0, vloss) <= close_drift_cap) |
| paid（支払う外し） | 自然な候補 かつ u > 0 かつ S > 0 かつ c <= A_t' かつ lead − c >= reserve かつ wr_after >= min_winrate |
| trap（罠 ON のときだけ） | §7 |

dominant の手番は S12 で u > 0 が保証されている（u == 0 ならここに来ない）。互角付近では free の勝率条件が
実質「1手 0.16目程度まで」に効く（勾配 19%/目 × 0.16目 ≈ 3%）＝接戦の同値外しは「勝率で見てほぼ損失なし」の手に限られる。

**S17 罠の合流**: 罠 ON なら `veil_merge_trap`（§7）。

**S18 選択（`veil_choose`）**: free ∪ paid のうち c の最小値 c0 から `cost_slack`(0.3) 以内の帯で **hp 最大**（決定的）。
hp の差が `VEIL_HP_TIE`(0.02) 以内なら、S > 0 のとき wr_after が高い手を優先。それでも同点なら c 昇順 → gtp 昇順。

**S19 不変条件（`veil_invariant_ok`）**: 選んだ手が cands に含まれ、best でも pass でもなく、種類ごとの上限を満たすこと
（free: c <= F_eff。paid: c <= A_t' かつ lead − c >= reserve。trap: price <= 許容額 かつ max(0, vloss) <= cap_phase
（dominant なら dominant_max_loss も）かつ lead − max(0, vloss) >= reserve。終局帯の入れ替え: 生の loss <= 0.10 / 0.05）。
満たさなければ ERROR ログ＋最善手。

**S20 記録**: `close_drift_cap` > 0 で close の free なら close_drift に max(0, vloss) を足す。`last_decision_info`
（tier / kind / best / chosen / raw / vloss / cons / hp / best_hp / ΔE / find_hp / lead / S / A_t / T / u / mine / n / opp /
opp_trunc / queries / secs）を埋め、`Decision: {json}` 行と `Rate:` 行を出し、ledger に足す。ponder は起動しない。

**フェイルセーフ（すべて `_best_move`）**: 盤サイズ不一致・候補なし・lead なし・humanSL 失敗・
best プローブ欠落・全候補不合格・例外・不変条件違反。

### 4.1 クエリ数と所要時間の見込み（13路・通常解析の後の追加分）

| 手番 | 追加クエリ | 時間 |
|---|---|---|
| 段(i)（候補なし） | 0本 | 約 0.0秒 |
| 相手の直前パス（pass_loss < 0.5 → 即パス／それ以外 → ownership Probe 1本） | 0〜1本 | 0〜約 1.1秒 |
| 終局帯（パスでない） | humanSL 1本 | 0.05〜0.27秒 |
| 段(ii) 閉・自然な候補なし | humanSL 1本 | 0.05〜0.27秒 |
| 決着局面の即決（best と候補の2手だけプローブ。検証で退けた手番は下の「プローブあり」を足す） | humanSL 1本 + 1バッチ（4本） | プローブありの行以下（4本を1バッチで並列） |
| プローブあり（best + 最大5手。19路は最大4手） | humanSL 1本 + 1バッチ（2×手数 本） | 約 0.5〜0.8秒 |
| 罠 ON のプローブ（上に最大3手を追加） | humanSL 1本 + 1バッチ（最大 2×9 本） | 約 0.6〜1.0秒 |

## 5. 一致率の集計と制御

**`veil_tally(nodes, ai_player) -> (mine, n_mine, opp, n_opp)`**（レポートと同じ定義）
- nodes は `cn.nodes_from_root` のうち着手があり root でないもの。
- 分母: `n.points_lost is not None` のノード（`game_report` ai.py:361-364）。
- 一致: `n.parent.analysis_complete and n.parent.candidate_moves[0]["move"] == n.move.gtp()`（ai.py:380-381）。
- 相手は切り揃えない（レポートと同じ）。比較用に `parity9_match_tally` の切り揃えた数も `Rate:` 行へ。
- 毎手、最初から数え直す（ノード数は高々数百）。
- テストで、合成した木に対して `game_report(...)` の `ai_top_move` と完全一致することを確かめる。

**目標と緊急度**
- `T = target_rate`（スライダー。値域 0.15〜0.50）。
- `u = clamp((p_match − T) / VEIL_URGENCY_WIDTH(0.10), 0, 1)`。ただし `p_match <= VEIL_TARGET_FLOOR(0.15)` なら u = 0。
  u > 0 を「ゲートが開いている」とする。
- u == 0: 支払う外しは 0、段(ii) は最善手、**同値外しは続ける**（要件5）。
- `p_match <= VEIL_TARGET_FLOOR(0.15)`: さらに F_eff を `VEIL_STRICT_FREE`(0.1) に下げ、罠のゲート閉時経路も止める
  （15% 未満へ無駄に払わない）。

## 6. 予算

- `F_eff = free_loss`。ただし lead < `VEIL_BEHIND_LIMIT`(−1) または p_match <= 0.15 なら `VEIL_STRICT_FREE`(0.1)。
- `S = lead − reserve`。
- `A_t = 0`（u == 0 または S <= 0）。それ以外は
  `A_lead = max(F_eff, min(cap_phase, spend_rate × S))`、`A_t = min(S, F_eff + u × (A_lead − F_eff))`。
  cap_phase はヨセ前 `max_loss`・ヨセ中 `yose_max_loss`（`max(F_eff, …)` を先に取るので、cap_phase < F_eff に
  設定しても A_t は u について減らない）。
- A_t <= S なので、支払う外しだけで reserve を割ることはない。1回の支出は、S >= 2 × F_eff のとき余剰の半分まで
  （S が小さいときは F_eff か S の小さいほう）。
- 13路の A_t の目安（u = 1）:
  - ヨセ前（cap 4.5）: lead +5 以下は 0（同値 0.3 のみ）、+7 で 1.0、+10 で 2.5、+14 以上で 4.5。
  - ヨセ中（cap 1.5）: +5 以下は 0、+6.5 で 0.75、+8 以上で 1.5。

### 6.1 盤サイズ別の既定値

| キー（`<prefix>_`） | 9路 | 13路 | 19路 | 意味 |
|---|---|---|---|---|
| target_rate | 0.40 | **0.30** | 0.30 | 目標一致率（値域 0.15〜0.50。9路は下限 35〜45% が実測済みのため） |
| reserve | 3.0 | **5.0** | 7.0 | 支払う外しの後にも残すリード |
| min_winrate | 0.85 | **0.85** | 0.85 | 支払う外しと罠の着手後勝率フロア |
| free_loss | 0.2 | **0.3** | 0.3 | 同値外しの閾値 |
| free_wr_drop | 0.03 | **0.03** | 0.03 | 同値外しで許す1手の勝率低下 |
| close_drift_cap | 0 | **0** | 0 | 接戦中の同値外し vloss の1局あたり累計上限。**0 で上限なし（既定）** |
| spend_rate | 0.5 | **0.5** | 0.5 | 余剰のうち1回に使う割合 |
| max_loss | 3.0 | **4.5** | 6.0 | 支払い上限（ヨセ前）。罠の vloss のハード上限も兼ねる |
| yose_max_loss | 1.0 | **1.5** | 2.0 | ヨセ中の支払い上限（罠も同じ）。0 で同値のみ |
| dominant_hp | 0.8 | **0.8** | 0.8 | 「明らかな一手」の閾値。1.01 で OFF |
| dominant_max_loss | 1.5 | **2.0** | 3.0 | 明らかな一手で許す損失（上限を絞るだけ） |
| min_human_policy | 0.05 | **0.05** | 0.05 | 自然さの絶対床 |
| natural_ratio | 0.2 | **0.2** | 0.2 | 自然さの相対床（第一感比） |
| cost_slack | 0.3 | **0.3** | 0.3 | 最安帯の幅 |
| trap_mode | false | **false** | false | 罠の上乗せ層（A/B 用） |
| trap_min_delta_e | 0.5 | **0.5** | 0.7 | 罠とみなす ΔE |

**13路の既定は 2026-09-25 に段階1b の loose に変えた**（ユーザーの決定。free_loss 0.4・spend_rate 1.0・max_loss 6.0・yose_max_loss 2.0・dominant_hp 1.01〈OFF〉・dominant_max_loss 3.0・natural_ratio 0.1 の7キー。安全条件 reserve 5.0・min_winrate 0.85 とほかのキー、9路・19路は表のまま）。表の 13路の列（と §6 の A_t の目安）は設計時の初期値で、`tests/test_ai_veil.py` の `SPEC_DEFAULTS` が凍結している。根拠は `calibration-data/selfplay/veil13-campaign.md` の「境界線と推奨」「ユーザーの決定（2026-09-25）」。

`close_drift_cap` を既定 0 にするのは要件5（ほぼ損失ゼロの外しは互角の序盤も含めて常に）のため。1局あたりの
累計上限は互角の序盤だけで使い切り、その後の接戦で同値外しを止めてしまう。接戦の安全は1手ごとの勝率条件
（free_wr_drop・ヨセの 0.01）で守り、累計の影響はハーネスの接戦ストレス層で測る（悪ければこのスライダーで上限を掛ける）。

**クラス属性 `VEIL_BOARD`（スライダーにしない）**: endgame_move 30 / 85 / 150、unsettled_max 8 / 16 / 36、
trusted_visits 100 / 50 / 50、probe_hp 3 / 3 / 3、probe_cheap 2 / 2 / 1。

**モジュール定数**: `VEIL_TARGET_FLOOR=0.15`、`VEIL_URGENCY_WIDTH=0.10`、`VEIL_STRICT_FREE=0.1`、
`VEIL_BEHIND_LIMIT=-1.0`、`VEIL_YOSE_FREE_WR_DROP=0.01`、`VEIL_CLOSE_WR=0.9`、`VEIL_DECIDED_WR=0.97`、
`VEIL_DECIDED_MARGIN=3.0`、`VEIL_TERMINAL_MAX=0.10`、`VEIL_TERMINAL_CLOSE_MAX=0.05`、`VEIL_TERMINAL_CLOSE_LEAD=3.0`、
`VEIL_TERMINAL_MIN_VISITS=10`、`VEIL_RAW_MARGIN=0.3`、`VEIL_TRAP_CREDIT=0.5`、`VEIL_TRAP_MIN_HP=0.02`、`VEIL_TRAP_PROBES=3`、
`VEIL_TRAP_RAW_EXTRA=1.0`、`VEIL_TRAP_SWAP_MARGIN=0.3`、`VEIL_HP_TIE=0.02`。

**「攻め」プリセット（測定専用）**: reserve 3、min_winrate 0.75、max_loss 6、spend_rate 1.0、dominant_max_loss 3、
yose_max_loss 2。ハーネスで「安全条件を緩めたら一致率がどこまで下がるか」の境界線を描くためのアームで、
**既定にするには要件1（安全条件は緩めない）の再決定が要る**。

## 7. 罠オプション（`<prefix>_trap_mode`・既定 OFF）

罠 ON は、OFF のプローブに加えて罠枠の `VEIL_TRAP_PROBES` 手を検証する（それ以外のクエリ列は同一）。ON で加わるもの:

1. **資格**: ΔE >= trap_min_delta_e、find_hp <= `ENIGMA9_GAMBLE_MAX_FIND`(0.25)（正しい応手が本の手でない＝
   本の手では E が過大）、hp >= `VEIL_TRAP_MIN_HP`(0.02)（自然さの床は免除）。
2. **安全（vloss で判定）**: max(0, vloss) <= cap_phase（ヨセ前 max_loss・ヨセ中 yose_max_loss。dominant なら
   dominant_max_loss でも頭打ち）、lead − max(0, vloss) >= reserve、wr_after >= min_winrate。
3. **値段**: `price = max(0, vloss) − VEIL_TRAP_CREDIT(0.5) × ΔE`（E は集計でしか較正されていない＝
   実損 ≈ 1.06×E・R²=0.18 なので半分だけ信用する）。許容額はゲートが開いていれば A_t'、閉じていれば
   price <= 0 かつ max(0, vloss) <= F_eff かつ p_match > 0.15。値段で割り引いても、2 の安全条件（vloss の上限）は割り引かない。
4. **合流（`veil_merge_trap`）**: 素の外し P があれば P。ただし罠 Q の price が P の c より `VEIL_TRAP_SWAP_MARGIN`(0.3) 以上
   安ければ Q。P が無く Q があれば Q（外しが1回増える）。P があれば戻り値は必ず非 None。
5. ΔE が負でも素の手は減点しない（擬態の @67 N9＝vloss≈0 の自然な手が ΔE で落ちた失敗の再発防止）。

A/B で見るもの: 自分と相手の一致率・勝率・mean_ptloss・払った vloss の合計、罠の次の相手手の実損と E の比
（1.06 から大きく外れたら、ハーネスの相手が罠に掛かりやすすぎると判断して結論を保留）、選んだ手の hp 中央値。

## 8. 純関数（すべて ai.py の Mimic13Strategy の後に置く）

| 関数 | 役割 |
|---|---|
| `veil_tally(nodes, ai_player)` | レポートと同じ定義で両者を集計 |
| `veil_urgency(mine, n, target, width, floor)` | p_match と u |
| `veil_free_limit(free_loss, lead, p_match)` | F_eff |
| `veil_allowance(lead, reserve, spend_rate, free, cap, u)` | (A_t, S) |
| `veil_natural_floor(hp_top, min_hp, ratio, dominant)` | 自然さの床 |
| `veil_prefilter(pool0, raw_cap)` / `veil_shortlist(...)` | 足切りと検証候補 |
| `veil_cons_loss(vloss, raw, visits, trusted)` | cons |
| `veil_near_free_ok(...)` / `veil_paid_ok(...)` / `veil_close_drift_ok(...)` | 安全条件 |
| `veil_classify(c, ctx)` | (kind, cost)。ctx は dataclass |
| `veil_choose(scored, slack, prefer_safe)` | 選択 |
| `veil_trap_price` / `veil_trap_ok` / `veil_merge_trap` | 罠 |
| `veil_terminal_swap(...)` | 終局帯の入れ替え |
| `veil_invariant_ok(chosen, best, cand_gtps, kind, bounds)` | 不変条件 |
| `veil_decision_record(**f)` | Decision 行の JSON |

## 9. テスト（`tests/test_ai_veil.py`）

- 純関数の境界値。特に **`veil_tally` と `game_report` の完全一致**（未完了の親・パス・白番で相手が1手多い）。
- `veil_allowance` が §6 の目安どおり（ヨセ前・ヨセ中・cap_phase < F_eff）。
- 3盤ぶんの登録・既定値・両 config・`AI_OPTION_VALUES` / `AI_OPTION_ORDER` の整合。
- 擬態の `_Harness` パターン（tests/test_ai_mimic13.py:242-358）で `_generate_move` を通しで:
  段(i) クエリ0本、段(ii) 閉で1本、決着局面の即決（best と候補の2手だけプローブ＝4本・検証で退けた手は打たずに
  通常の流れ）、reserve と勝率フロアでの拒否、
  ヨセの 0.01 ガード、`close_drift_cap` の ON/OFF、**相手の直前パスで pass_loss >= 0.5 のとき外しに進まない**、
  終局帯入れ替えの 0.05 / 0.10、終局帯 (d) の損失上限、罠 ON/OFF で罠枠以外のクエリ列が同一、素の外しが罠で消えない、
  **ヨセの罠が yose_max_loss を超えない**、dominant の罠が dominant_max_loss を超えない、全フェイルセーフと
  不変条件違反で最善手、`_start_ponder` が一度も呼ばれない、`board_watch_probe_warm` が False に戻る。
- 難解・擬態の既存テストが無変更で通る。
- `tests/test_ai_help_text.py` のファミリー正規表現に `veil(?:9|13|19)` を足す。

## 10. 校正と採否の手順

1. ハーネス（別 spec）で相手ボットを実戦の相手に合わせ、難解＋のアームで「ハーネスと実戦のずれ」を測る。
2. アーム: Veil 既定 / 罠 ON / 攻め（測定専用）/ 難解＋13路（基準）/ HumanStyle 9段（参照）。接戦ストレス層と投了なしを含める
   （組み合わせと所要時間はハーネス spec §6）。
3. 境界線（自分の一致率 vs 勝率・損失/手・外した手の hp）を見て、安全条件以外のつまみの既定値を決める（ユーザーが選ぶ）。
4. 採否の基準:
   - **勝ちの安全（非劣性）**: 接戦ストレス層で、局ごとの flip_moves（自分の着手で勝率が 50% 以上から未満に落ちた手）の
     Veil − 難解＋ の対の差の 95% 上限が 0.1/局以下、かつ敗局数が難解＋より 2局を超えて多くない（敗局は SGF を1局ずつ見る）。
     通常層の勝敗は記述にとどめる（全勝に近いので検出力がない）。
   - **人間らしさ**: 外した手（レポート基準＝`move != parent.candidate_moves[0]`）の 9段 hp の中央値が 5% 以上。
   - **一致率**: 盤サイズ別の目標 T に対して `P(own <= T + 0.05)` と `P(own < 0.15)` を出す（前者が高く後者が低いほど良い）。
5. 実戦で確認（各10局以上。ログの `Rate:` / `Decision:` 行を集計ツールで読む）。

## 11. 登録・触るファイル

- `katrain/core/ai.py`（CRLF。python パッチスクリプトで編集＝black フック回避。plan
  `2026-09-17-mimic13-strategy.md:47-72` の手順）: import に AI_VEIL_9/13/19、VEIL_* 定数・veil_* 純関数・3クラス。
- `katrain/core/constants.py`: `AI_VEIL_9/13/19`、`AI_STRATEGIES_ENGINE`、`AI_STRATEGIES`、
  `AI_STRATEGIES_RECOMMENDED_ORDER`（擬態の後）、`AI_STRENGTH`（nan）、`AI_OPTION_VALUES` / `AI_OPTION_ORDER`（25キー×3盤＝当初の16キー＋§13.2 の失着の4キー＋§14.2 の4キー＋§15.2 の1キー。
  target_rate の値域は 0.15〜0.50）。
- `katrain/gui/ai_help.py`: `_VEIL_FAMILY = re.compile(r"^(veil(?:9|13|19))_(.+)$")` で `aiopt:veil*_<suffix>` を3盤共有。
- `katrain/config.json`（パッケージ）と `C:\Users\iwaki\.katrain\config.json`（ユーザー）: ai:veil9 / ai:veil13 / ai:veil19。
  **ユーザー側はメインセッションで、KaTrain を止めてから**編集する。
- jp / en の `katrain.po`（ai:veilN・aihelp:veilN・`aiopt:veil*_<suffix>` 25件＝当初の16件＋§13.2 の4件＋§14.2 の4件＋§15.2 の1件）→ `python tools/compile_mo.py`。
- `katrain_debug/runner.py`: `STRATEGY_NAME_MAP` に veil9 / veil13 / veil19。
- ドキュメント: `.claude/rules/ai-strategies.md`（Veil の段落）、`.claude/rules/ai-parameters.md`（パラメータ表）、
  `CLAUDE.md`（戦略一覧）、`docs/manual/src/`（AI 概要と一致率の節）→ `python tools/build_manual.py`、
  `docs/superpowers/specs/INDEX.md`。

## 12. 未決事項とリスク

- **目標に届かない可能性が高い**（§2.4: 平均約 46%・15〜35% は 13% の局）。律速は予算ではなく在庫と接戦の安全条件。
  ハーネスの境界線を見て、**安全条件以外のつまみ**（dominant_hp・natural_ratio・free_loss・close_drift_cap）の既定値を選ぶ。
  安全条件（reserve・min_winrate）を緩めるのは要件1の再決定が要る。
- 接戦の同値外しは1手ごとの勝率条件だけで守る（累計上限は既定 OFF）。序盤から累計で何目払うかはハーネスで測る
  （`Decision:` 行の free の vloss 合計と接戦フラグ）。
- 500v プローブのノイズ（±0.2〜0.3目）と humanPolicy の非決定性（±0.05〜0.09）で、閾値 0.3・0.8 付近の判定が揺れる。
- komi 7 の中国ルールで「+1目が持碁」になる落とし穴: ヨセの 0.01 ガード・終局帯入れ替えの 0.05・reserve で守るが残りうる。
- 監視モードで盤を取り込み直す・新規対局になると `_veil_state` がリセットされる。
- ponder なしの遅延（13路 1〜2秒・19路 2〜3秒）が持ち時間に効くか。
- 盤サイズが合わない戦略を選ぶと毎手最善手（一致率 100%）。自動切替は範囲外。
- 19路は未校正、9路は相手の一致率の実測が無い。

## 13. 失着オプション（`<prefix>_blunder_mode`・既定 OFF）— 2026-09-24 追記

### 13.1 ねらいと根拠

「9段でも間違えうる難しい局面で、人間らしい大きな失着をまれに打つ」層（ユーザー提案・2026-09-24）。韜晦の通常の層は1手の支払いを
`max_loss`（13路の既定は loose で 6.0 目）で切るので、6目以上の損は判定の読み違い（判定時の損失は上限の内だが、終局レポートでは
6目以上）のときだけ（ハーネスで 0〜0.25 回/局。失着の層で打った手は除く）。ハーネスの実測（1局あたりの ≥6目の失着）:

| 打ち手 | ≥6目/局 |
|---|---|
| ハーネスの相手（humanSL rank_1k / 1d / 3d・悪手フィルタなし） | 2.75 / 2.00 / 1.97 |
| HumanStyle 9段（悪手フィルタ 3.6・段階3 の接戦ストレスの相手） | 0.65 |
| HumanStyle 9段（段階1 の AI アーム・通常の相手） | 0.10 |
| 韜晦（段階1・1b・2 の韜晦のアームすべて。どれも判定の読み違いの手） | 0 〜 0.10 |

**一致率を下げる手段ではない**: 失着1回は一致率の計算上は外し1手と同じ（13路で1局40手なら最大 2.5pt）。損失の分布の裾を人間に
近づけるための層。勝ちの安全条件（reserve・min_winrate）は緩めない＝要件1は変えない。

### 13.2 設定（4キー × 3盤）

| 接尾辞 | 意味 | 9路 | 13路 | 19路 | スライダー |
|---|---|---|---|---|---|
| `blunder_mode` | 0 = OFF・1 = 記録のみ（影＝条件を満たす手を探して `Decision:` に書くが打たない）・2 = ON | 0 | 0 | 0 | OFF / LOG / ON |
| `blunder_max_loss` | 失着の上限（検証済み損失・目） | 6.0 | 10.0 | 15.0 | 9路 4/5/6/8・13路 8/10/12/15・19路 8/10/12/15/20 |
| `blunder_per_game` | 1局で打つ失着の上限（ON のとき） | 1 | 1 | 1 | 1 / 2 / 3 |
| `blunder_hp_ratio` | 失着の手の hp ÷ 最善手の hp の下限（9段 humanSL） | 0.7 | 0.7 | 0.7 | 0.5 / 0.7 / 0.8 / 1.0 |

スライダーにしない定数（ai.py）:

| 定数 | 値 | 意味 |
|---|---|---|
| `VEIL_BLUNDER_MIN_HP` | 0.15 | 失着の手に要る hp の絶対床（第一感に近い手だけ） |
| `VEIL_BLUNDER_MIN_WR` | 0.95 | 着手前の root 勝率と、失着を打った後の検証済み勝率の両方の床（min_winrate 0.85 より厳しい） |
| `VEIL_BLUNDER_MARGIN` | 5.0 | 失着を打った後の検証済みリードに要る reserve の上積み（目）＝lead_after >= reserve + 5 |
| `VEIL_BLUNDER_VISITS` | 1500 | 失着の検証プローブの visits（通常の子局面プローブ 500 より深い。難しい局面ほど浅い読みの損失は外れる） |
| `VEIL_BLUNDER_PROBES` | 2 | 深く検証する失着候補の数（hp の高い順） |
| `VEIL_BLUNDER_RAW_MARGIN` | 2.0 | 生の loss の上の足切りに持たせる余裕（目） |
| `VEIL_BLUNDER_PROB` | 0.5 | ON で条件を満たした手番に実際に打つ確率（打つ手番を読めなくする。影の計測の後に見直す） |

### 13.3 流れ（S9b＝S9 予算の直後・S10 の前）

1. `blunder_mode` が 0 なら何もしない（クエリ 0 本・記録も足さない）。
2. **関門**（クエリ 0 本）: ヨセでない（`in_yose` が偽）・root 勝率 >= `VEIL_BLUNDER_MIN_WR`・
   lead >= reserve + `VEIL_BLUNDER_MARGIN` + cap（cap＝その局面の支払い上限 `max_loss`。関門は必要条件: 失着は cap を超える損失なので、
   lead < reserve + margin + cap なら手順6 の root リードの条件 lead − vloss >= reserve + margin を満たす手は無い）・
   `blunder_max_loss` > cap（以下なら手順6 の cap < vloss <= `blunder_max_loss` を満たす手は定義上無い）・ON なら今局の失着数 < `blunder_per_game`。
   通らなければ `blunder = "gate"` を記録して通常の流れへ。
3. 親局面の humanSL（9段・8 visits）を1本撃つ（S11 と共有＝同じ手番で2回撃たない）。
4. **候補**（純関数 `veil_blunder_candidates`・クエリ 0 本）: 通常解析の候補（`candidate_moves`）のうち best・pass 以外で、
   hp >= max(`VEIL_BLUNDER_MIN_HP`, `blunder_hp_ratio` × best の hp) かつ cap < 生の loss <= `blunder_max_loss` + `VEIL_BLUNDER_RAW_MARGIN`。
   hp の高い順に `VEIL_BLUNDER_PROBES` 手まで。無ければ `blunder = "no_cand"` で通常の流れへ。
   hp が最善手の 0.7 倍以上＝9段 humanSL 自身が迷う局面なので、「難しい局面」の条件はこれで兼ねる（best が明らかな一手なら
   0.7 × 0.8 = 0.56 以上の手は hp の合計から存在しえない）。
5. **深い検証**: best と候補を `VEIL_BLUNDER_VISITS` のクリーン解析で1バッチ（1 + k 本）。vloss = best の lead_after − 候補の lead_after。
6. **資格**（純関数 `veil_blunder_ok`）: cap < vloss <= `blunder_max_loss`・lead_after >= reserve + `VEIL_BLUNDER_MARGIN`・
   lead − vloss >= reserve + `VEIL_BLUNDER_MARGIN`（root リード基準・不変条件と同じ式）・
   wr_after >= `VEIL_BLUNDER_MIN_WR`。lead_after（深い読み）と root リードの両方で reserve + margin が残る手だけ
   （root リードが深い読みより小さい探索のゆれで、資格を通った手が不変条件の ERROR＋最善手にならないように）。
   資格のある手のうち hp 最大（`veil_blunder_pick`）。無ければ `blunder = "rejected"`。
7. **影（mode 1）**: `blunder = "shadow"` と候補の値（`blunder_gtp` `blunder_vloss` `blunder_hp` `blunder_best_hp`
   `blunder_wr` `blunder_lead_after`）を記録して通常の流れへ（打たない）。今局の上限は数えない（頻度を測るため）。
8. **ON（mode 2）**: 乱数 >= `VEIL_BLUNDER_PROB` なら `blunder = "skipped"` を記録して通常の流れへ。打つなら不変条件
   （`veil_invariant_ok` の kind `blunder`: 候補が通常解析の候補に含まれ best・pass でない、vloss <= blunder_max_loss、
   lead − vloss >= reserve + margin、wr_after >= MIN_WR）を確かめ、今局の失着数を1つ増やして tier `blunder`・kind `blunder` で打つ。
   違反なら ERROR ログ＋最善手（他の kind と同じ）。
9. どの分岐の例外も S0 のフェイルセーフ（最善手）に落ちる。

失着の後の手番は、下がった lead からふつうに予算を計算し直す（S = lead − reserve）ので、後の支払いは自動で減る。

### 13.4 測り方と採否

1. **影の計測**: 通常の相手・20 seed・`--arm shadow=veil13:<20キー>`（16キー＋`veil13_blunder_mode=1`＋失着の3キー）。1局あたりの `blunder = "shadow"` の手番数、
   その vloss・hp の分布、失着の検証で増えた戦略時間（p95）。
2. **ON の計測**: 通常の相手（default と ON のアーム）で ≥6目の失着/局・flip・勝ち・一致率。接戦ストレス（段階3 の条件）でも
   ON のアームを流し、関門で止まる（失着 0）ことと敗局が増えないことを確かめる。
3. 既定は OFF のまま。ON にするか・頻度（`blunder_per_game`・`VEIL_BLUNDER_PROB`）はユーザーが結果を見て決める。

### 13.5 計測の結果とユーザーの決定（2026-09-25）

13路で §13.4 の順に測った（§13.2 の 13路の既定・`VEIL_BLUNDER_PROB` 0.5。詳細は `calibration-data/selfplay/veil13-campaign.md` の
「失着の層（spec §13）の計測（2026-09-25）」と「ユーザーの決定（2026-09-25）」）。

- 影（mode 1・通常の相手・20 seed）: 条件を満たす手番は loose で 0.45 回/局、spec の初期値で 1.45 回/局（支払い上限 cap が高いほど
  「cap を超える損失」の帯が狭い）。失着の手の 9段 hp はほとんどの手番で最善手の hp より高い（loose 9/9・初期値 27/29）。
- ON（mode 2・loose・通常の相手・20局）: 0.20 回/局（4/20 局）・深い読みの損失 6.8〜9.8 目・4局とも勝ち。勝ち・flip・
  自分の一致率は失着 OFF と差が無い。
- ON（接戦ストレス＝段階3 の条件・20局）: 失着は1回だけ（ほかの手番は関門で止まるか〈849〉、候補なし〈50〉・資格なし〈6〉で
  打たなかった）・19-0-1。持碁の1局の直接の原因は 83 手目の S13 の即決の読み落とし（生 0.36 目 → 実損 16.3 目）。57 手目の失着
  （レポート 4.8 目・+23.6 → +18.7 目）が無ければ 83 手目の時点のリードは約 +20.6 目で、同じ読み落としでも約 +4 目残って勝っていた
  計算＝失着も重なった。S13 は打つ前に2手だけプローブで確かめる形に直した（§4 S13 の 2026-09-25 追記）。
- ユーザーの決定: 失着の条件は下限（失着の手の hp が最善手の 0.7 倍以上）だけのまま（上限〈1.43 倍以下＝ほぼ同じ〉も足すと
  loose で 0.05 回/局）・既定は OFF（GUI の LOG／ON で使う）。

## 14. 最善手しか無い手番の外し（`<prefix>_forced_mode`・既定 OFF）— 2026-09-25 追記

### 14.1 要件の再決定とねらい

- **ユーザーの決定（2026-09-25）**: 13路で「20局に1局ほどなら負けてもよい」代わりに、自分の一致率を平均 30〜45% に下げたい。
  ユーザー案は「最善手しか打てない手番でも、外しても逆転されて劣勢にならない範囲で、人間らしい手があれば打つ（無理に打たない）」。
  - **この層を ON にしたときだけ**、要件1（勝ち最優先・安全条件を緩めない）をこの許容に緩める。OFF なら要件1のまま。
  - 要件5 (i)「候補が最善手しか無い → 最善手（常に）」の例外になる。通常の層の候補（予算と床）では最善手しか無くても、
    §14.3 の条件を満たす人間らしい手があれば打つ。9段らしさの床（§6 の自然さの床）は変えない＝人間らしくない手は打たない。
- **根拠**: 実戦3局とハーネス80局の強制手番（通常の層が最善手を打った手番）1790 手を KataGo で読み直した、1手ずつの反実仮想の見積もり
  （記録は `experiments/selfplay/relax-spike-20260925/`・要約は `calibration-data/selfplay/veil13-campaign.md`）。
  - 同じ局面を humanSL の確率どおりに打つ人の一致率（全手番の最善手の hp の平均）:

    | 局面 | 9段 | 3段 | 1段 |
    |---|---|---|---|
    | ハーネス（通常の相手・60局） | 48.3% | 44.4% | 41.7% |
    | 実戦（2026-09-25 の3局） | 51.9% | 47.3% | 44.7% |

  - 9段らしさの床を守る限り、安全条件をすべて外しても下限はハーネス 23.9%・実戦 27.8%。最善手の 9段 hp >= 0.95 の手番は、
    ハーネスの 390 手番で1度も開かない。
  - 見込み（範囲は、その手番だけを変えた計算 〜 後の通常の層の外しが減る分を入れた悲観的な計算）:

    | 条件 | ハーネス（通常） | 実戦（3局） | 接戦ストレス | 最終リードが負になる局（一次近似） |
    |---|---|---|---|---|
    | 今（loose） | 45.2% | 53.6% | 65.4% | 0/20 |
    | ① 安全は今のまま・強制手番だけ上限 10目 | 40.2〜42.2% | 49.0% | 63.0〜66.2% | 0/20 |
    | ② 着手後リード +2・勝率 70%・上限 6目 | 38.4〜43.7% | 46.4〜48.4% | 59.5〜64.2% | 0/20 |
    | **③ 着手後リード +2・勝率 70%・上限 10目** | **36.3〜42.2%** | **43.5〜45.4%** | 59.5〜65.4% | 1/20 |
    | ④ 着手後リード +2・勝率 70%・上限なし | 34.6〜41.4% | 41.8〜48.4% | 59.5〜65.4% | 1/20 |

  - 効くのは「大差のとき1手で許す損の上限」。接戦（lead < 5）で外す分は数 pt で、負けの危険はここから来る。
  - **採らなかった案**:
    - 1局の勝率の予算（外しで減らした勝率の合計に上限）。終盤の大差では勝率が飽和し、9〜15目の損でも勝率の低下がほぼ 0 と
      数えられて効かない。逆に KataGo の勝率は、対 BOT の負けの危険を大きく見積もる（既存の外しで1局 0.10〜0.12 使っても 83局全勝）。
      安全は、1手ごとのリードと勝率の床、損の上限で持つ。
    - 大差のとき人間らしさの基準を弱い段位（3段・1段）の humanSL にする案。下がるのは 0.3〜1.1pt だけ（3段・1段の人も
      明らかな手は同じように打つ）。
- **ユーザーが選んだ組み合わせ（2026-09-25）**: ③。着手後リード +2目以上・着手後勝率 70% 以上・1手の損の上限 10目
  （ヨセは通常の層と同じ `yose_max_loss`）。上限はスライダーで変えられる。

### 14.2 設定（4キー × 3盤）

| 接尾辞 | 意味 | 9路 | 13路 | 19路 | スライダー |
|---|---|---|---|---|---|
| `forced_mode` | 0 = OFF・1 = 記録のみ（影＝打つ手を探して `Decision:` に書くが、最善手を打つ）・2 = ON | 0 | 0 | 0 | OFF / LOG / ON |
| `forced_min_lead` | 打った後に残すリード（目。root リード基準と検証済みリードの両方） | 1.0 | 2.0 | 3.0 | 9路 0.5/1/2/3・13路 1/2/3/5・19路 2/3/5/8 |
| `forced_min_winrate` | 打った後の検証済み勝率の下限 | 0.70 | 0.70 | 0.70 | 60% / 70% / 75% / 80% / 85% |
| `forced_max_loss` | 1手の損の上限（検証済み損失・目。ヨセは `yose_max_loss`） | 5.0 | 10.0 | 15.0 | 9路 3/4/5/6/8・13路 6/8/10/12/15・19路 8/10/15/20 |

スライダーにしない定数（ai.py）:

| 定数 | 値 | 意味 |
|---|---|---|
| `VEIL_FORCED_PROBES` | 4 | 検証する候補の数（hp の高い順） |

9路・19路の値は校正していない（13路の比で置いた）。コードの既定は3盤とも OFF。

### 14.3 流れ（通常の流れが最善手で終わる出口の直前）

1. **入口**: 通常の流れが最善手で終わる4つの出口（S10 `no_pool`・S12 `no_natural`・S14 `no_shortlist`・S17 `none_qualified`）で、
   `finish` の前に `_veil_forced` を呼ぶ。`forced_mode` が 0 なら何もしない（クエリ 0 本・記録も足さない）。
   終局帯（S7/S8）・フェイルセーフ・`dominant_closed`（u <= 0 のときだけ起きる）では呼ばない。
2. **関門**（クエリ 0 本）: u > 0（一致率が目標を超えている）・root 勝率 >= `forced_min_winrate`（root 勝率が無ければ止める）・
   cap_f = min(上限, lead − `forced_min_lead`) > 0（上限はヨセなら `yose_max_loss`、それ以外は `forced_max_loss`）。
   通らなければ `forced = "gate"`。
3. **親局面の humanSL**（9段・8 visits）: S9b か S11 で撃っていればそれを使う（同じ手番で2回撃たない）。S10 の出口ではまだ無いので
   1本撃つ。取れなければ `forced = "no_hp"`。
4. **候補**（純関数 `veil_forced_candidates`・クエリ 0 本）: 通常解析の候補（`_veil_candidates`）のうち best・pass 以外で、
   生の loss <= cap_f + `VEIL_RAW_MARGIN`、かつ hp >= 床（`_veil_floor(human_policy, dominant=False)`＝通常の層と同じ 9段らしさの床）。
   hp の高い順に `VEIL_FORCED_PROBES` 手まで。無ければ `forced = "no_cand"`。
5. **検証**: best と候補を、S15 と同じ `_probe_children`（500 visits のクリーン解析）で1バッチ。S15 で同じ手を読んでいればその結果を
   使う。vloss = best の lead_after − 候補の lead_after、cons = `veil_cons_loss(vloss, 生の loss, visits, trusted_visits)`、
   cost = max(0, cons)。
6. **資格**（純関数 `veil_forced_ok`）: cost <= 上限・lead_after >= `forced_min_lead`・lead − cost >= `forced_min_lead`・
   wr_after >= `forced_min_winrate`（None は不可）。資格のある手のうち hp 最大、同じなら cost の小さい手（`veil_forced_pick`）。
   無ければ `forced = "rejected"`。
7. **影（mode 1）**: `forced = "shadow"` と候補の値を記録して、最善手を打つ（元の why のまま）。
8. **ON（mode 2）**: 不変条件（`veil_invariant_ok` の kind `forced`: 候補が通常解析の候補に含まれ best・pass でない・cost <= 上限・
   lead − cost >= `forced_min_lead`・wr_after >= `forced_min_winrate`）を確かめ、tier `forced`・kind `forced` で打つ。
   今局の数（`_veil_state` の `forced`）を1つ増やす。違反なら ERROR ログ＋最善手（他の kind と同じ）。
9. **記録**: `Decision:` に `forced`（gate / no_hp / no_cand / no_probe / rejected / shadow / invariant / played）・`forced_from`（元の why）・`forced_gtp`・
   `forced_cost`・`forced_vloss`・`forced_hp`・`forced_wr`・`forced_lead_after` を残す。どの分岐の例外も S0 のフェイルセーフ（最善手）に落ちる。

- 外した後の手番は、下がった lead から予算を計算し直す（S = lead − reserve）ので、後の支払いは自動で減る。
  1局の回数の上限・勝率の予算は置かない（§14.1）。多すぎれば実測の後に足す。
- 失着の層（S9b）は今のまま先に動く。両方 ON でよい。失着の層と両方 ON のときは、失着の層が見送った手（抽選で skipped・1局の上限に達した・失着の安全条件で rejected）も、この層の条件（cost <= forced_max_loss・lead − cost >= forced_min_lead・wr_after >= forced_min_winrate）を満たせば、同じ手番にこの層が打つ。13路は forced_max_loss（10）が blunder_max_loss（10）と同じなので、大きめの外しの上限は失着の層ではなくこの層の設定で決まる（失着の層の blunder_per_game・確率・安全条件はこの層の手には効かない）。
- 追加のクエリは強制手番だけで、親の hp 1本（S10 の出口のみ）と、プローブ (1 + k) 手分（1手あたりクリーン＋hp の2本・k <= 4）。
  1手の決定時間は 1〜2 秒増えうる。
- この層は1手の上限を u で縮めない（u > 0 なら上限いっぱいまで）。13路は目標 30% に対して一致率が構造的に約 45% なので u はほぼ 1 で差が出ないが、9路・19路の校正で見直す。

### 14.4 測り方と合格の条件

- **アーム**（24キーをすべて明示）:
  - `cur` = loose の 20キー＋`veil13_blunder_mode=2`（いまのユーザーのローカル設定と同じ）
  - `new` = `cur`＋`veil13_forced_mode=2`（ほかの forced キーは §14.2 の 13路の既定）
- **通常の相手**: 20 対（seed 1000〜1019）。段階1b と同じ humanSL の相手（`opponent_pool_13.json`）。
- **接戦ストレス**: 40 対。段階3b と同じ条件（`--komi-shift 4 --opponent strategy:human:human_kyu_rank=-8,modern_style=true`）。
- **合格の条件**:
  - (a) 通常の相手: `new` の自分の一致率（1局ごとの平均）が 42% 以下。`new` の負けは 20 局中 1 以下。
  - (b) 接戦ストレス: `new` の負けは 40 局中 2 以下（約 20 局に 1 局以下）。持碁は負けに数える。
  - (c) 人間らしさ: この層で打った手の 9段 hp の中央値が 0.15 以上。1局あたりの ≥6目の手の数を出す。
  - (d) 1手の戦略時間の p95 が 2 秒以下。
- (b) を満たさなければ、`forced_min_lead` 3・`forced_min_winrate` 0.75 にして接戦ストレスだけやり直す。それでも満たさなければ、
  結果をユーザーに見せて決めてもらう。(a) だけ満たさないときも、結果を見せて決めてもらう。
- 合格したら、ユーザーのローカル設定の `veil13_forced_mode` を 2 にする（メインセッションで、KaTrain を止めてから）。
  コードの既定は OFF のまま。9路・19路は未校正。
- その後の実戦（各10局以上）で、ログの `Rate:` と `Decision:`（`forced`）から一致率・この層の手・勝敗を集計する。

### 14.5 計測の結果（2026-09-25）

§14.4 のとおり 13路で測った（詳細は `calibration-data/selfplay/veil13-campaign.md` の「最善手しか無い手番の外し（spec §14）の計測（2026-09-25）」）。

- 通常の相手（20 対）: 自分の一致率 `cur`（loose＋失着 ON）44.1% → `new`（＋この層 ON）38.5%（同じ seed の差 −5.5pt・Wilcoxon p 0.036）・
  どちらも 20-0。この層の手は 5.65 回/局（9段 hp 中央値 0.275）・≥6目の手は 0.35 → 0.75 回/局。
- 接戦ストレス（40 対）: 66.1% → 62.6%・どちらも 40-0（持碁 0）。この層の手 3.67 回/局のうちリード 5 目未満の手番が約半分。
- §14.4 の合格の条件 (a)〜(d) をすべて満たした（戦略時間 p95 1.06 秒）。
- ユーザーの決定（2026-09-25）: 結果を見て、ユーザーのローカル設定の 13路でこの層を ON にした（値は §14.2 の 13路の既定・失着の層も ON）。
  コードの既定は OFF のまま・9路／19路は未校正。次は実戦（各10局以上）でログの `Rate:` と `Decision:` を集計する。

## 15. 序盤の研究外し（`<prefix>_open_moves`・既定 OFF）— 2026-09-26 追記・実装済み（2026-09-26）

### 15.1 要件の再決定とねらい

- **ユーザーの提案（2026-09-26）**: 9路は序盤の何手かを定跡どおりに打つと、高段の BOT に終局近くまで最善手で応じられかねない
  （9路の定跡は終局近くまで覚えられるものが多い）。そうなると接戦のまま、こちらの一致率も高くなる。序盤は難解（`ai:enigma9`）と
  同じく研究外しの手を打ち、相手に定跡を打たせない。効果があれば 13路にも使う。
- **ユーザーの決定（2026-09-26）**:
  - 序盤の窓の中は **難解と同じ挙動でよい**。根拠はユーザーの実戦の経験: 難解は相手が最善手で応じにくい手を選ぶので、実戦で
    正しく応じられることは稀で、対 BOT で 100 戦近くほぼ全勝。
  - → **この層を ON にしたときだけ**、窓の中の手番は要件1（勝ち最優先・安全条件を緩めない）・要件5（手番の3段）・
    要件7（人間らしさ）の代わりに、**難解＋のユーザー設定の挙動**に従う（§15.3 の「窓の中で効く上限」）。窓の後の手番は
    通常の一致率ひかえめ（要件1〜10）に戻る。OFF なら今と同じ。
  - 方式は **案1: 窓の中は同じ盤サイズの難解＋に、ユーザー設定のまま任せる**。採らなかった案:
    - 案2（難解の選び方＝E＋見つけにくさ＋自手の意外さ−損失を韜晦の中に作り直す）: 細かく調整できるが、難解とは別物になり
      実戦の実績が使えない。
    - 案3（定石本で裏付けた 1〜2 手目の安い外しだけ）: 安全だが「相手に定跡を打たせない」は 2 手目までしか効かない。
  - 9路の相手 BOT は主に高段。
- 任せる先は難解＋だけ（難解は選べない）。ユーザー設定の `ai:enigma9`（難解9路）は持碁狙い（`enigma9_aim_jigo` true・勝率フロア 0）で、
  勝ち最優先の一致率ひかえめの窓には使えないため。
- 調査で分かっていること（§16.1）は、効果を確かめる材料であって採否の根拠ではない。効果は §16 のハーネスの比較と実戦で確かめる。

### 15.2 設定（1キー × 3盤）

| 接尾辞 | 意味 | 9路 | 13路 | 19路 | スライダー |
|---|---|---|---|---|---|
| `open_moves` | 序盤の窓の手数。打つ手の番号（両者の通算）がこの値以下の手番を難解＋に任せる。0 = OFF | 0 | 0 | 0 | 9路 0/6/8/10/12/16/20・13路 0/12/20/24/30/40・19路 0/20/30/40/50/60 |

- 窓の手数は両者の通算。9路 12 なら各色 6 手（黒は 1・3…11 手目、白は 2・4…12 手目）、13路 30 なら各色 15 手。
- ON にするときの想定の値（§16 で測る）: 9路 12（難解＋9路のユーザー設定の賭け罠の窓 `enigma9plus_gamble_until_move` 12 と同じ）・
  13路 30（難解＋13路のユーザー設定の賭け罠の窓と同じ）。
- **13路の窓の最初の 11 手は研究外しではない**: 難解＋13路のユーザー設定 `enigma13plus_opening_humanstyle_moves` 11 により、
  難解＋はどの分岐より先に HumanStyle 9段（ほぼ定跡どおりの手）に任せる（ai.py の `enigma9_opening_handoff`）。13路で
  研究外しが始まるのは 12 手目から（黒は HumanStyle 6 手・難解＋ 9 手、白は HumanStyle 5 手・難解＋ 10 手）。これも「難解と同じ」の一部。
- 任せる先の設定は **ユーザー設定（`config.json` の `ai:enigma9plus` / `ai:enigma13plus` / `ai:enigma19plus`）をそのまま読む**
  （`game.katrain.config("ai/<戦略キー>") or {}`。節やキーが無ければ難解＋の既定値）。韜晦の側に難解の設定の写しを持たない＝
  難解＋の設定を GUI で変えれば、この層の手も変わる。
- キーは失着（`AI_OPTION_ORDER` の 16-19）・forced（20-23）の後の 24 に足す。コードの既定は3盤とも 0（OFF）。

### 15.3 流れ（S4b＝S4 一致率の直後・S5 の前）

1. `open_moves` が 0 なら何もしない（クエリ 0 本・root に触れない・`Decision:` と `_veil_state` にキーを足さない＝今とビット同一）。
2. **窓の判定**（純関数 `veil_open_index(depth, n_setup)`・`veil_open_window(index, open_moves)`）: index = `cn.depth` ＋ root の
   置き石の数（`game.root.placements` の数）。打つ手の番号は index ＋ 1 で、index < `open_moves` なら窓の中。
   - board_watch が相手の初手を root の置き石として取り込んだ局でも手数がずれない。局の途中で盤を取り込み直すと盤上の石はすべて
     root の置き石になる＝index が大きく窓の外になる（途中から研究外しを始めない）。
   - 難解＋の中の窓（賭け罠・HumanStyle への委譲）は `cn.depth` だけで数えるので、置き石がある局では難解＋の中の窓が 1 手ずれる
     （難解＋を単独で使うときと同じ）。
   - 窓の外の手番は何も記録しない（通常の流れ）。
3. **関門**（クエリ 0 本）: 相手の直前の手がパスでない（パスなら通常の流れの S7 の終局処理へ）・p_match > `VEIL_TARGET_FLOOR`（0.15。
   15% 未満へ無駄に外さない＝要件3）。通らなければ `open = "gate"` を記録して通常の流れへ。
   - 窓は u（緊急度）を見ない（要件5の代わり＝難解＋のまま）。床の関門は、9路の `open_moves` 12 では各色 6 手なので
     p_match >= 1/6 > 0.15 で閉じない。長い窓（9路 16 以上・13路）でだけ効く守り。
4. **窓のリードの記録**（クエリ 0 本）: S5 と同じ計算で root の lead と勝率（打つ側視点）を info に入れる（None でも任せる）。
5. **任せる**: 同じ盤サイズの難解＋（9路 `Enigma9PlusStrategy`・13路 `Enigma13PlusStrategy`・19路 `Enigma19PlusStrategy`）の
   **派生クラス**を、ユーザー設定の難解＋の設定を渡して作り、`generate_move()` を呼ぶ。
   - 派生クラス（例 `VeilOpenEnigma9PlusStrategy`）: 名前は `Strategy` で終わる（ハーネスのログの正規表現 `^\[\w+Strategy\] ` が難解＋の
     Pool / Score / Deviate / Gamble / Overdraft の行を拾えるように）。`_ponder_applies` を常に False にするだけで、`KEY_PREFIX`・
     `SETTING_DEFAULTS` は上書きしない（ユーザー設定のキーと sticky フラグ `_enigma9plus_endgame` の名前を保つ）。
     `@register_strategy` は付けない。難解のコードは変えない。
   - 作る処理は差し替えられるメソッド（`_veil_open_delegate()` が (戦略, 戦略キー) を返す）に置く（テストでスタブにする）。
   - 作った直後に `delegate.cn = self.cn`・`delegate.query_generations = self.query_generations` にする（韜晦が待った局面と世代を
     そのまま使う。作る間に局面が動いても別の局面を読まない）。
   - 難解＋の中の分岐（序盤の HumanStyle 9段委譲・賭け罠・捨て身の罠・消費モード・終局帯・フェイルセーフ）はすべて難解＋のまま動く。
   - 戻った後に `game.board_watch_probe_warm = False` に戻す。
   - ponder を止める理由は §3.1 と同じ（監視対局で自ノードのフル解析が後回しになり、相手の手がレポートで 200v の最善手と
     比べられる＝相手の一致率の基準がぶれる）。止めても手の選び方は変わらない（ponder は次の局面の温めだけ）。
6. **確認**（純関数 `veil_open_ok(chosen)`）: 手が None でも pass でもないこと。通らなければ ERROR ログ＋最善手（`open = "invariant"`）。
   通常解析の候補（`candidate_moves`）に無い手も打つ（13路の HumanStyle 9段は自分のクリーン解析の moveInfos から選ぶので、まれに
   候補外の手を返す。「難解と同じ」を崩さない）。候補に含まれるかは `open_in_cands` として記録だけする。
7. **記録**: tier `opening`。
   - kind は手が best と違えば `opening`（why `opening`）、同じなら `best`（why `opening_best`）。
   - `Decision:` に `open`（gate / invariant / played）・`open_index`・`open_src`（任せた戦略キー）・`open_in_cands`・`open_secs`
     （難解＋の所要時間）・`open_thoughts`（難解＋の説明文の先頭 200 字）と、手順4 の `lead`・`root_wr` を足す。`Rate:` 行は S4 のまま。
   - ledger に (depth, best, 手, kind)。
   - `_veil_state` の `opening` は、`open = "played"` かつ kind `opening`（best と違う手を打った）手番の数。打ったときだけキーを作る
     （forced と同じ＝OFF と窓の外ではキーが無い）。
8. どの分岐の例外も S0 のフェイルセーフ（最善手）に落ちる（`AnalysisDiscardedException` は再送出）。`_veil_error` の記録には
   窓の中だったかどうか（`open_index`）を足す。

- **窓の中で効く上限（2026-09-26 のユーザー設定。難解＋の設定を変えれば変わる）**:

  | 仕組み（難解＋） | 9路 | 13路 |
  |---|---|---|
  | 通常の外し: 1手の損の上限（`max_loss`）・着手後勝率の下限（`min_winrate`） | 1.8目・0.30 | 3.0目・0.25 |
  | 消費モード（リード > target＋max_loss。9路 2.8目・13路 5.0目）: 1手の損の上限（`large_lead_max_loss`） | 8目 | 10目 |
  | 捨て身の罠（消費モードでだけ開く・勝率フロアを見ない）: 1手の損の天井（1.5 × `large_lead_max_loss`）・応じられた後に狙うリード | 12目・[−1, +1) | 15目・[−2, +2) |
  | 賭け罠（手数 < 12 / 30）: 正しく応じられた後の勝率の下限 | 0.30 | 0.25 |
  | 13路の手数 11 未満: HumanStyle 9段の悪手フィルタ（勝率フロアなし） | — | 2.8目 |

  難解＋の外しの損失は子局面の 500 visits の検証値で、9路の序盤では深い咎めを見落とすことがある（§16.1 の 3-4点の例）。
- 窓の中では韜晦の他の層（失着・forced・即決・罠・終局帯の入れ替え）は動かない＝手は難解＋が決める。窓の後の手番は通常どおり
  （その時点の p_match と lead から u・予算を計算し直す）。
- 追加のクエリは難解＋と同じ（子局面プローブ。9路は1手 1〜2 秒程度）。先読みを止めるので、監視対局の体感は難解＋より遅くなりうる。
- 終局レポートの一致率の定義は変わらない（最善手 = 親局面の `candidate_moves[0]`）。

### 15.4 ハーネスの集計（`katrain_debug/selfplay_stats.py` の韜晦の要約）

- `nonfree_below_reserve`（lead < reserve で打った free でない外し）から tier `opening` を除く（窓の中は reserve を見ない設計）。
- 窓の手は別の項目 `opening` に出す: 任せた手番の数・kind `opening` の数・レポートの損失の合計・≥2目 / ≥6目の手の数・`open_in_cands` が偽の数。
- vloss を持たない kind（opening）の `vloss_by_kind` と `curse_by_kind` は 0 ではなく None にする。

### 15.5 テスト（`tests/test_ai_veil.py`・`tests/test_selfplay_*.py`）

- 純関数: 窓（index 0・`open_moves` − 1・`open_moves`・置き石あり・`open_moves` 0）、`veil_open_ok`（None・pass は False、候補外の手は True）。
- 通しテスト（`_Harness` に `root=SimpleNamespace(placements=[...])` と `katrain.config` を足す。窓の手番は depth を明示する＝既定 depth 12 は
  9路の窓 12 の外。任せる先は `_veil_open_delegate` をスタブにする）:
  (a) `open_moves` 0 でクエリ列・`Decision:`・`_veil_state` が今とビット同一で、root に触れない、
  (b) 窓の中で難解＋の手をそのまま返す・kind opening / best・ledger・`Decision:` のキー（lead・root_wr を含む）・`_veil_state["opening"]`、
  (c) 窓の外は通常の流れ、(d) 相手の直前パス・p_match <= 0.15（合成の集計で作る）で任せない（`open = "gate"`）、
  (e) None / pass で ERROR＋最善手（`open = "invariant"`）、候補外の手はそのまま打つ（`open_in_cands` 偽）、
  (f) 難解＋の側で例外が出たら最善手（`_veil_error` の記録に `open_index`）、
  (g) 任せた難解＋の ponder が起動しない（`players_info` を {自分: AI, 相手: HUMAN} にして、スレッドが起動しないことと
      `_enigma_ponder_owner` が None のままであることを確かめる）、
  (h) 9/13/19路で任せる先のクラスと設定の節（`ai:enigma9plus` など）が切り替わる・節が無い（None）ときは既定値で動く、
  (i) root の置き石で index がずれる、(j) 戻った後に `board_watch_probe_warm` が False、
  (k) 任せた戦略の `cn` と `query_generations` が韜晦のものと同じ。
- ハーネスの集計: §15.4 の3点（tier opening が `nonfree_below_reserve` に入らない・`opening` の項目・vloss の無い kind は None）。
- 登録: 3盤の1キー・既定値（0）・両 config・`AI_OPTION_VALUES` / `AI_OPTION_ORDER`（24）・jp / en の aiopt・en の aihelp の箇条の数
  （`tests/test_ai_veil.py` の箇条数のテスト）・マニュアルの表。§11 の「24キー」「aiopt 24件」は 25 に直す。
- 難解・擬態・既存の韜晦のテストが無変更で通る。

## 16. 9路の校正と、序盤の研究外しの効果の計測（2026-09-26 追記・✅ 計測済み〈2026-09-26〉）

### 16.1 調査の要点（2026-09-26・コードもエンジンも動かさない読み取りだけ）

集計のスクリプトは §16.2 の手順8 でリポジトリに置く。

- **9路の定跡**（KataGo の 9路の本 katagobooks.org `book9x9tt`・Tromp-Taylor・komi 7・2026-02-26 版）:
  - 黒の初手は 4-4・4-5・天元・3-5 の4系統（13点）が 0.12目以内に並び、次は 3-4 の約 2目損。
  - 3手目以降は一択の手番が多い（天元の本線は 5〜18 手目がほぼ一本道）。損失は「0〜0.5目（引き分けを保つ）」か「1.3〜2目以上
    （負けに落ちる）」の二極。本の本線の深さは 23〜30 手。
  - → 9路で一致率が上がる原因は、相手の記憶より盤の性質（引き分けを保つ手が1つしかない手番の多さ）が大きいと見る。本を持たない
    強い BOT も同じ手を打つ。
- **9路の勝率勾配**: 難解＋9路の実戦ログ 17 局の `Score` 行（子局面の 500 visits の検証値・最善の勝率 30〜70% の局面）で 26.0%/目
  （vloss 0.2〜2.0・n 236）・24.0%/目（0.5〜2.0・n 125）。13路は 19%/目。
- **安い代わりの手の割合**（同じ 17 局・検証した候補だけ）: 手数 1〜2 で 0.3目以内 94%・3〜6 で 65%・7〜12 で 27%・13〜20 で 24%。
- **500 visits の検証は深い咎めを見落とす**: 3-4点の初手が 0.23目（n 2）と出たが、本では 1.95目。
- **相手 BOT**（8月の監視対局の 130 局面・`calibration-data/enigma9/ponder_pick_probe.json`）: clean 約 520 visits の最善手（`k` 列）との一致
  23.8%（31/130。こちらの手が 11 手目までの局面は 6/25）・humanSL 9段の1位（`h_all` 列）との一致 35.4%。段位は不明・こちらが外した後の局面。
- **9路の実戦**: ログは難解＋9路 16局と持碁9路 1局（`experiments/selfplay/realgames-9x9-logs/` に退避済み。KaTrain は対局ログを
  新しい 40 本しか残さない）。韜晦9路の実戦は 0 局。
  - 難解＋16局の自分の一致率は 65.7%（261/397。ログの `Move generation complete` の理由文が最善手の手を一致とした数で、2500v の
    事後解析ではない。AI の 1〜5 手番目 43.8% → 16 手番目以降 75.9%〈手数では約 31 手目以降〉）。手数の中央値 48（持碁9路を含めると 49）。
  - 局ごとの難解＋の設定はばらばら（`gamble_until_move` 0 / 12 / 16 / 20・`target_score` 0.2 / 2.0・`max_loss` 1.6 / 1.8）で、
    今のユーザー設定（12・1.0・1.8・捨て身の罠 1.0）と同じ局は無い。
  - 最終リードが −2.5目の局（0919_213928）と +0.03目の局（0919_223517）が1局ずつある（勝敗はログに無い）。
- **13路のハーネス**（veil13-p1 の同じ seed の対）: 序盤（24手未満）の自分の一致率 韜晦 53.9%・難解＋ 43.5%、24手目以降は 52.2%・
  52.7%。13〜23 手目は 韜晦 77〜87%・難解＋ 50〜56%。同じ seed の対の差の SD は 8.5〜11.9pt で、「窓の後に波及しない」は
  このデータからは結論できない（区間が広い）。ハーネスの相手は定跡を覚えていない。
- **ハーネスの 9路**: 仕組みは通るが実エンジンで打った run は 0。9路の相手プール・校正の目標・投了の手数（13路の面積比の縮小で、
  9路の実戦の手数と合わない）が無い。相手の hp は記録されない。定跡を知る相手は無い。

### 16.2 ハーネスの 9路対応と、定跡を知る相手（コードの変更）

1. **実戦ログの復元**（`calibration-data/selfplay/recon_logs.py`）: `--log-dir`・`--out`・`--size` を足す。
   - 9路の出力先は `recon_9/`（難解＋9路 16 局・`0919_223015` は監視の外の相手のパスを挟んで直せた）。除く局は ID で書く: 持碁9路 `0919_224212`（初手だけ難解＋）。
   - `0919_223015` は相手のパスが「相手の着手」の行に出ない（`opponent passed but the board is not settled` の行でパスを挟む）。
     直せなければ除く。
   - 相手の初手が root の置き石の局（`213546`・`215145`・`223517`・`201809`）は、その手を初手として SGF に戻す。
   - 局ごとの難解＋の設定（`Initializing` 行）を summary に残す。
   - 一致率ひかえめ9路の実戦は別の出力先 `recon_9_veil/`（投了の手数と校正の目標に混ぜない）。
   - 実戦の直後にログを `experiments/selfplay/realgames-9x9-logs/` に退避する（KaTrain は新しい 40 本しかログを残さない）。
2. **事後解析**（`offline_report.py`・2500v）: 出力先と区間を盤サイズで分ける。
3. **区間**: `CALIB_BINS` を盤サイズ別にする（割合は 13路と同じ 24/169・85/169＝9路は 12 / 41 手。`game_report` の区間と一致）。
   `calib_targets.py` の直書きの 24/85 もこれに揃える。`depth_bin` と校正の関数に盤サイズを渡し、13路の値が変わらないことをテストで固定する。
4. **校正の目標とプール**: `CALIB_TARGETS_9`（`recon_9` から）。`selfplay_run.py` のプールの選択・目標・`harness_drift_ai`・
   calibration.md の直書き（「16/18」）を盤サイズで分ける。calibrate に AI の設定の上書き（`--strategy enigma9plus:key=v,...`）を足し、
   実戦の多数派の設定（`max_loss` 1.6・`target_score` 0.2・`gamble_until_move` 20 の 7 局）で校正する。`harness_drift_ai` はその 7 局と比べる（参考値）。
   コマンド: `calibrate --size 9 --strategy enigma9plus:<上書き> --ranks rank_1d,rank_3d,rank_5d,rank_7d,rank_9d --games 8 --write-pool
   docs/superpowers/specs/calibration-data/selfplay/opponent_pool_9.json`。calibrate の手数の中央値を実戦の 48 と比べる。
5. **投了の手数**: 読み先を盤サイズで選び（`recon_9/`）、9路の標本は縮めない（summary に `board_size` を持たせる）。lead モデルは 9路では使わない。
6. **定跡を知る相手**（`--book-moves B`・`--book-loss X`・既定 0＝OFF）: 通常の相手（プールの humanSL）を包む。手数 < B で、
   それまでの AI の手がすべて `points_lost` <= X（既定 0.3目＝引き分けを保つ帯）の間は、KataGo の最善手（`candidate_moves[0]`）を打つ。
   AI が一度でも X を超える手を打ったら、その局の残りは包んだ humanSL で打つ。ユーザーの仮説（こちらが定跡どおりだと高段の BOT が
   最善手を続ける）のモデル。本より浅い読み（2500v）の最善手である点と、「定跡の中」を AI の損失で決めるのはモデルの仮定である点に注意。
   run.json と相手のキー（run の突き合わせ）に B・X を入れる。
7. **窓の指標**（`calibration-data/selfplay/window_stats.py`）: moves.jsonl（中断した局は games.jsonl と突き合わせて除く）から、アームごとに
   窓の中（`depth <= W`・moves.jsonl の `depth` は打った手のノード）と外の、自分・相手の一致率と損失・≥2目 / ≥6目の手、W 手目のリード
   （`depth <= W` の最後の行の `lead_after_ai`）、flip、窓の後の `decision_u` と支払った外し（paid）の数（窓で下げた分を後で打ち消していないか）、
   定跡を知る相手が定跡を外れた手数。W は 9路 12・13路 30。韜晦のアームは `decision_open` でも窓を確かめる。
8. **調査のスクリプトの置き場**: §16.1 の勾配・安い代わりの手・相手 BOT の一致・実戦の一致率の集計を `calibration-data/selfplay/` に置く。
9. **設定の固定**: §16 の実行はすべて、ユーザー設定の写し（`experiments/selfplay/<run>/config-snapshot.json`）を `--config` で渡す。
   任せる先の設定が実行の途中で変わらない。加えて、`open_moves` > 0 のアームは任せる先（戦略キー・設定・指紋）を `resolve_arm` で
   持たせ、再開と合算の突き合わせに入れる（違えば止める）。`enigma` のアームは上書きなし（任せる先と同じ節を読む）＝
   「すべてのキーを明示する」の例外。

### 16.3 9路の段階（`--size 9`・韜晦のアームはすべてのキーを明示する）

アーム:
- `spec` = 9路の既定（§6.1 の 9路の列・層は OFF）
- `loose9` = 13路の loose を 9路に縮めた 7 キー（**暫定の案**: free_loss 0.3・spend_rate 1.0・max_loss 4.0・yose_max_loss 1.5・
  dominant_hp 1.01・dominant_max_loss 2.0・natural_ratio 0.1。安全条件 reserve 3.0・min_winrate 0.85 は据え置き）
- `layers` = `loose9` ＋ `blunder_mode` 2 ＋ `forced_mode` 2（13路のローカル設定に相当。値は §13.2・§14.2 の 9路の既定）
- `open` = `layers` ＋ `open_moves` 12
- `enigma` = 難解＋9路（上書きなし）
- `human` = HumanStyle 9段（参照）

| 段 | 相手 | アーム | 対 | 見るもの |
|---|---|---|---|---|
| 9-0 スモーク | プール | `layers`・`open` | 2 | 動くこと・記録 |
| 9-1 校正 | プール（3段位） | 6 アームすべて | 24 | 9路の既定値を決める材料 |
| 9-2 研究外しの効果 | プール | `layers`・`open`（`--seed-base 1024`） | 24（9-1 と合わせて 48） | 局全体と窓の後の一致率 |
| 9-3 定跡を知る相手 | プール＋`--book-moves 24` | `layers`・`open`・`enigma` | 24 | ユーザーの仮説 |
| 9-4 強い相手 | HumanStyle 9段（コミ互角） | `layers`・`open`・`enigma` | 20 | 窓の中の安全 |
| 9-5 接戦ストレス | HumanStyle 9段・`--komi-shift 2` | `layers`・`open`・`enigma` | 20 | 窓の後の安全 |

- 対の数はプールの 3 段位 × 2 色の倍数（24・48）にする（20 だと段位が 8/6/6 に偏る）。
- 投了ありが既定。`--no-resign` の比較を 9-1 の `layers`・`open` で 10 対だけ足す（ハーネス spec §3）。
- 9-5 は AI が不利なので、窓の中の難解＋は勝率フロアでほぼ最善手を打つ＝窓の後の部分だけを測る。窓の中の安全は 9-4 で見る。

### 16.4 13路の段階（`--size 13`）

アーム: `local`（ユーザーのローカル設定と同じ＝loose ＋ `blunder_mode` 2 ＋ `forced_mode` 2）・`local_open`（＋ `open_moves` 30）・
`enigma`（難解＋13路・上書きなし）。

| 段 | 相手 | アーム | 対 |
|---|---|---|---|
| 13-1 効果 | プール（`opponent_pool_13.json`） | `local`・`local_open` | 24 |
| 13-2 定跡を知る相手 | プール＋`--book-moves 40` | `local`・`local_open`・`enigma` | 24 |
| 13-3 強い相手 | HumanStyle 9段（コミ互角） | `local`・`local_open`・`enigma` | 20 |
| 13-4 接戦ストレス | 段階3b と同じ（`--komi-shift 4`・HumanStyle 9段） | `local`・`local_open` | 20 |

- 13路の窓の最初の 11 手は HumanStyle 9段の手（§15.2）。1 手目からの研究外しも比べたくなったら、`enigma13plus_opening_humanstyle_moves` を
  0 にした設定の写しで別の実行を足す（ライブの設定は変えない）。

### 16.5 見るものと決め方

- **効果**（`summarize --compare <A> <B> --conf 0.975` の同じ seed の対の差と、`window_stats.py`）:
  - 局全体の自分の一致率（9路は 9-1 と 9-2 を合わせた 48 対で読む）。
  - 窓の中の自分の一致率（窓の手を難解＋の手に置き換えた分の、ほぼ機械的な下げ）と、窓の後の自分の一致率（広がるか・打ち消されるか。
    窓の後の u と paid の数も見る）。
  - 相手の一致率と損失（窓の中・外）、W 手目のリード、定跡を知る相手が定跡を外れた手数。
- **安全**: 勝ち以外（負け＋持碁）の数と内訳（勝・負・持碁）、flip_moves、窓の中の ≥2目 / ≥6目の手の数、W 手目のリードの分布。
  9路・中国ルール・整数のコミでは持碁が起こるので、持碁も勝ち以外に数える（要件1）。
- **決め方**: ユーザーが結果を見て決める。
  - 9路の既定値（`loose9` を既定にするか・層の既定）と、ローカル設定（層・研究外しを ON にするか）。9路の既定を後で変えたら、
    研究外しの差（`open` − `layers`）は測り直す（`layers` と `open` は `loose9` の上に乗っている）。
  - 13路のローカル設定に研究外しを足すか。
  - 目安: 局全体の自分の一致率の対の差（`open` − `layers`）の 97.5% 区間が 0 をまたがずに下がり、9-3・9-4（13路は 13-2・13-3）で `open` の
    勝ち以外の数が同じ相手の `enigma` 以下なら、研究外しを採る候補にする（ユーザーは難解並みの危険を受け入れている）。
- **所要の見積もり**（13路の実測の 1 局の時間から換算。9路は 1 手が 13路の 0.75 倍・手数 48）: 準備（事後解析・calibrate 40 局）約 1 時間、
  9-1 約 2 時間、9-2 約 0.7 時間、9-3 約 1 時間、9-4 約 1.3 時間、9-5 約 1.4 時間、13路 13-1〜13-4 合わせて約 6 時間。
  どれも KaTrain を止めている間だけ走らせる（`ensure_no_katago`）。
- **実戦**:
  - ユーザーが打つ一致率ひかえめ9路（今の設定＝互角の序盤はほぼ最善手＝定跡どおり）の数局で、「こちらが定跡どおりに打つと高段の BOT が
    最善手を続けるか」を見る（`recon_9_veil/` の 2500v の事後解析で、相手の最善手との一致率・序盤で相手が最善手を続けた手数・窓の後の
    相手の一致率。比べる先は難解＋9路の 16 局）。
  - 研究外しを ON にした実戦（各 10 局以上）は、この計測の後。

### 16.6 計測の結果（2026-09-26）

§16.2〜16.4 のとおり測った（詳細は `calibration-data/selfplay/veil9-campaign.md`、13路は `calibration-data/selfplay/veil13-campaign.md` の
「序盤の研究外し（spec §15・§16.4）の計測（2026-09-26）」）。コードは HEAD `0a6f0bfe`（dirty false）・設定の写しは全実行で同じ・aborted 0。

- 準備: 難解＋9路の実戦 16 局（`recon_9/`・14-1-1）から `CALIB_TARGETS_9`（相手の一致率 30.8%・局間 SD 16.6pt・損失 1.88 目/手・AI 62.8%〈多数派の設定の 7 局〉）。
  相手プールは humanSL rank_1d / rank_3d / rank_9d（31.4%・16.1pt・1.42 目/手。ハーネスと実戦のずれ +2.9pt・手数の中央値 55 vs 48）。
- 9-1（6 アーム × 24 対）: 自分の一致率 spec 62.6%・loose9 61.5%・layers 52.8%・open 57.3%・enigma 59.5%・human 67.9%。loose9 は spec と差がなく（+1.1pt）、
  下げたのは forced を含む層（spec − layers +9.8pt [t +2.6, +17.0]）。勝ちは全アーム 24/24（human は 23-0-1）。
- 研究外しの効果（9-1＋9-2・48 対・`open` − `layers`）: 局全体 +2.7pt [t −2.5, +7.9]（下がらない）。窓の中 −13.2pt・窓の後 +8.1pt（W 12 手目のリード −1.5 目で、
  窓の後は lead < reserve の手番が増えて最善手が増える）・flip +1.06/局（ほぼ窓の中）・どちらも 48-0。
- 投了なし（10 対）: layers 58.8%・open 47.6%（手数の中央値 81 / 98）で向きが逆になる。実戦は 48 手前後で投了されるので投了ありの run を基準にする。
- 9-3（定跡を知る相手・`--book-moves 24`）: 勝-負-持碁 layers 21-0-3・open 20-0-4・enigma 18-0-6。窓の中の相手の一致率 layers 95.1% → open 72.2%（−22.9pt）。
- 9-4（HumanStyle 9段）: layers 18-0-2・open 14-3-3・enigma 13-4-3。W 手目で負けている局 open 17/20・layers 5/20（リードの差 −1.85 目）。open の負け 3 局はどれも窓の中の外しでリードを失った。
- 9-5（接戦ストレス・`--komi-shift 2`）: layers 16-0-4・open 16-4-0・enigma 11-5-4（窓の中は open・enigma とも最善手だけ）。
- 実戦（一致率ひかえめ9路の今の設定 8 局 vs 難解＋9路 16 局・W 12）: 窓の中の相手の一致率 39.6% vs 25.0%・窓の後 22.8% vs 32.3%・相手が初手から最善手を続けた手数は最大 1 手（どちらも）。
  結果 8-0-0・14-1-1。序盤の対称で同格な初手は完全一致でしか数えない（過小評価の向き）。
- 13路（`local_open` − `local`）: 自分の一致率 13-1 −5.0pt [t −9.8, −0.3]・13-2（定跡を知る相手）−7.2pt・13-3（HumanStyle 9段）+3.2pt（n.s.）・13-4（接戦ストレス）−0.4pt。
  勝ち以外は両アーム同じ（13-1〜13-3 は 0・13-4 は 18-2-0 どうし）、enigma は 13-3 で 5。
- §16.5 の目安: 9路は局全体の差が下がらないので満たさない（9-3・9-4 の勝ち以外が enigma 以下という安全の条件は満たす）。13路は 13-1 の差が 0 をまたがずに下がり、
  13-2・13-3 の勝ち以外が enigma 以下なので満たす。決定はユーザー（計画 C10）。
- ユーザーの決定（2026-09-26）: 9路のローカル設定を layers（研究外し OFF）に、13路のローカル設定で研究外しを ON（30 手）にし、ブランチを master にマージする。
  コードの既定値はどの盤も変えない。次は実戦（各 10 局以上）で確かめる。
