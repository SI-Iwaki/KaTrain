# 韜晦（9/13/19路）戦略 ai:veil9 / ai:veil13 / ai:veil19 設計

日付: 2026-09-23
対象: `katrain/core/ai.py`（veil 純関数群 + `Veil9Strategy` / `Veil13Strategy` / `Veil19Strategy`）
状態: 実装済み（2026-09-24）・13路は自己対局ハーネスで測定し、spec の初期値を据え置いた（`calibration-data/selfplay/veil13-campaign.md`。段階1＝既定の自分の一致率 局平均 53.1%・20/20 勝ちで目標 30% に届かず、下限は構造的＝最善手を打つしかない手番 52.7%。段階3＝接戦ストレス〈AI 不利 4 目・HumanStyle 9段・20 対〉で §10.4 (a) 勝ちの安全は既定の設定で可＝20-0・flip 0.20/局 vs 難解＋ 2.35/局・難解＋は 2 敗。段階1b・2 は未実施）・実戦校正は未実施

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

**S13 決着局面の即決（プローブ0本）**: root 勝率 >= `VEIL_DECIDED_WR`(0.97) かつ
lead >= reserve + `VEIL_DECIDED_MARGIN`(3) かつ dominant でないとき、自然な候補のうち生の loss <= F_eff かつ
visits >= trusted_visits の手があれば、生の loss を cost として S18 と同じ帯の規則で打つ（同点は hp → 生の loss → gtp）。
接戦ではこの経路を使わない（生の ≤0.3目の手のうち検証後の勝率低下 ≤3% を満たすのは 44% しかない）。

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
| 段(ii) 閉・自然な候補なし・決着局面の即決 | humanSL 1本 | 0.05〜0.27秒 |
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
  段(i) クエリ0本、段(ii) 閉で1本、決着局面の即決（プローブなし）、reserve と勝率フロアでの拒否、
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
  `AI_STRATEGIES_RECOMMENDED_ORDER`（擬態の後）、`AI_STRENGTH`（nan）、`AI_OPTION_VALUES` / `AI_OPTION_ORDER`（16キー×3盤。
  target_rate の値域は 0.15〜0.50）。
- `katrain/gui/ai_help.py`: `_VEIL_FAMILY = re.compile(r"^(veil(?:9|13|19))_(.+)$")` で `aiopt:veil*_<suffix>` を3盤共有。
- `katrain/config.json`（パッケージ）と `C:\Users\iwaki\.katrain\config.json`（ユーザー）: ai:veil9 / ai:veil13 / ai:veil19。
  **ユーザー側はメインセッションで、KaTrain を止めてから**編集する。
- jp / en の `katrain.po`（ai:veilN・aihelp:veilN・`aiopt:veil*_<suffix>` 16件）→ `python tools/compile_mo.py`。
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

「9段でも間違えうる難しい局面で、人間らしい大きな失着をまれに打つ」層（ユーザー提案・2026-09-24）。韜晦は1手あたりの支払いを
`max_loss`（13路 4.5目）で切っているので、6目以上の失着が一度も出ない。ハーネスの実測（1局あたりの ≥6目の失着）:

| 打ち手 | ≥6目/局 |
|---|---|
| ハーネスの相手（humanSL rank_1k / 1d / 3d・悪手フィルタなし） | 2.75 / 2.00 / 1.97 |
| HumanStyle 9段（悪手フィルタ 3.6・段階3 の接戦ストレスの相手） | 0.65 |
| HumanStyle 9段（段階1 の AI アーム・通常の相手） | 0.10 |
| 韜晦（段階1・1b・2 の韜晦のアームすべて） | 0 〜 0.10 |

**一致率を下げる手段ではない**: 失着1回は一致率の計算上は外し1手と同じ（13路で1局40手なら最大 2.5pt）。損失の分布の裾を人間に
近づけるための層。勝ちの安全条件（reserve・min_winrate）は緩めない＝要件1は変えない。

### 13.2 設定（4キー × 3盤）

| 接尾辞 | 意味 | 9路 | 13路 | 19路 | スライダー |
|---|---|---|---|---|---|
| `blunder_mode` | 0 = OFF・1 = 記録のみ（影＝条件を満たす手を探して `Decision:` に書くが打たない）・2 = ON | 0 | 0 | 0 | OFF / LOG / ON |
| `blunder_max_loss` | 失着の上限（検証済み損失・目） | 6.0 | 10.0 | 15.0 | 9路 4/5/6/8・13路 6/8/10/12/15・19路 8/10/12/15/20 |
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
   lead >= reserve + `VEIL_BLUNDER_MARGIN` + cap（cap＝その局面の支払い上限 `max_loss`。失着は cap を超える損失なので、
   最小の失着でも lead_after >= reserve + margin が残る局面だけ）・ON なら今局の失着数 < `blunder_per_game`。
   通らなければ `blunder = "gate"` を記録して通常の流れへ。
3. 親局面の humanSL（9段・8 visits）を1本撃つ（S11 と共有＝同じ手番で2回撃たない）。
4. **候補**（純関数 `veil_blunder_candidates`・クエリ 0 本）: 通常解析の候補（`candidate_moves`）のうち best・pass 以外で、
   hp >= max(`VEIL_BLUNDER_MIN_HP`, `blunder_hp_ratio` × best の hp) かつ cap < 生の loss <= `blunder_max_loss` + `VEIL_BLUNDER_RAW_MARGIN`。
   hp の高い順に `VEIL_BLUNDER_PROBES` 手まで。無ければ `blunder = "no_cand"` で通常の流れへ。
   hp が最善手の 0.7 倍以上＝9段 humanSL 自身が迷う局面なので、「難しい局面」の条件はこれで兼ねる（best が明らかな一手なら
   0.7 × 0.8 = 0.56 以上の手は hp の合計から存在しえない）。
5. **深い検証**: best と候補を `VEIL_BLUNDER_VISITS` のクリーン解析で1バッチ（1 + k 本）。vloss = best の lead_after − 候補の lead_after。
6. **資格**（純関数 `veil_blunder_ok`）: cap < vloss <= `blunder_max_loss`・lead_after >= reserve + `VEIL_BLUNDER_MARGIN`・
   wr_after >= `VEIL_BLUNDER_MIN_WR`。資格のある手のうち hp 最大（`veil_blunder_pick`）。無ければ `blunder = "rejected"`。
7. **影（mode 1）**: `blunder = "shadow"` と候補の値（`blunder_gtp` `blunder_vloss` `blunder_hp` `blunder_best_hp`
   `blunder_wr` `blunder_lead_after`）を記録して通常の流れへ（打たない）。今局の上限は数えない（頻度を測るため）。
8. **ON（mode 2）**: 乱数 >= `VEIL_BLUNDER_PROB` なら `blunder = "skipped"` を記録して通常の流れへ。打つなら不変条件
   （`veil_invariant_ok` の kind `blunder`: 候補が通常解析の候補に含まれ best・pass でない、vloss <= blunder_max_loss、
   lead − vloss >= reserve + margin、wr_after >= MIN_WR）を確かめ、今局の失着数を1つ増やして tier `blunder`・kind `blunder` で打つ。
   違反なら ERROR ログ＋最善手（他の kind と同じ）。
9. どの分岐の例外も S0 のフェイルセーフ（最善手）に落ちる。

失着の後の手番は、下がった lead からふつうに予算を計算し直す（S = lead − reserve）ので、後の支払いは自動で減る。

### 13.4 測り方と採否

1. **影の計測**: 通常の相手・20 seed・`--arm shadow=veil13:<16キー>,veil13_blunder_mode=1`。1局あたりの `blunder = "shadow"` の手番数、
   その vloss・hp の分布、失着の検証で増えた戦略時間（p95）。
2. **ON の計測**: 通常の相手（default と ON のアーム）で ≥6目の失着/局・flip・勝ち・一致率。接戦ストレス（段階3 の条件）でも
   ON のアームを流し、関門で止まる（失着 0）ことと敗局が増えないことを確かめる。
3. 既定は OFF のまま。ON にするか・頻度（`blunder_per_game`・`VEIL_BLUNDER_PROB`）はユーザーが結果を見て決める。
