# 擬態（13路）戦略 ai:mimic13 設計

日付: 2026-09-17
対象: `katrain/core/ai.py`（mimic 純関数群 + `Mimic13Strategy`）
状態: 実装済み（2026-09-17）・実戦校正は未実施

## 1. 要件（ユーザー要求の写し）

1. **AI 側の AI 最善手一致率が相手より低い状態を保ったまま勝つ**。低ければ低いほど理想。
2. **わざと外しているとバレない**＝人間らしい手を打つ。humanPolicy が圧倒的で有力候補が
   1つしかない局面で最善手を外すと露骨なので、そこは最善手を打つ。ただし**相手を騙す手
   （難解戦略のような罠）は人間らしさの条件を免除**する。
3. **ヨセは意図的に外さない**。Human-like 9段でよい（9段でも間違えうる手は打つが、高段者なら
   間違えない意図的な外しはしない）。
4. 持碁モードの「最善手ではないが有力かつ人間らしい手を選ぶ」ロジックが参考になる。
   今回は僅差である必要はない。
5. 接戦では外しの原資が無い。**相手に大きな悪手を打たせて予算を作る**＝難解戦略の
   ロジック（相手を騙す）を使う。
6. ヨセでは外せないので、**序盤〜中盤で不一致の手数を稼ぐ**。
7. 13路専用（9路・19路は今回のスコープ外。動けば後で展開する）。

### 優先順位（確認済みの前提）

**勝ち > 一致率**（parity9 と同じ）。強い相手との接戦では一致率は高く残ってよい。
一致率は安全条件の内側で常に下げ続ける（相手より十分低くなっても止めない）。
ブレーキはリードの余剰と着手後勝率フロアだけ。

### 一致率の定義

KaTrain の終局レポートと同一式＝親局面の `candidate_moves[0]["move"]` と着手の一致
（`parity9_match_tally` がそのまま使える）。

## 2. 実測（設計の根拠・2026-09-17・ログのみ）

13路 難解/難解＋の監視対局ログ 18 局（`game_20260911_*`〜`game_20260916_*`）の `Score` 行
（プローブ済み候補の vloss / E / own_hp）を集計。ヨセ前・Score 行のある 443 手番。
**プローブ済み候補（安い順 7 手＋spread）しか hp が出ていないので在庫は下限**。
スクリプト: scratchpad `natural_inventory.py`（ログ→手番分割→集計・KataGo 不要）。

| 指標（中盤 443 手番） | 割合 |
|---|---|
| 難解が実際に外した | 60.5% |
| 最善手の hp >= 0.8（外すとバレる手番） | 21.7% |
| 自然な非最善手（hp >= max(0.05, 0.2×最大hp)）が居る | 66.8% |
| 　うち vloss <= 0.3 / 0.5 / 1.0 / 1.5 | 26.0 / 31.2 / 41.1 / 47.2% |
| 　うち price（= vloss − ΔE）<= 0 / 0.3 / 1.0 | 19.2 / 29.6 / 44.5% |
| 期待値プラスの罠（ΔE >= 0.5 かつ vloss <= ΔE） | 20.5% |
| タダ同然（自然かつ vloss <= 0.3）または期待値プラスの罠 | 38.8% |
| 自然な手 または 罠 | 71.3% |

hp 閾値の感度は小さい（(0.03, 0.15)〜(0.10, 0.25) で「自然な手が居る」64.6〜76.5%）。

**リードは潤沢**: 同ログの `Spend:` 行の lead は典型 +3〜+35（中盤の 6〜8 割の手番で
余剰 > 1.6 目）。このアプリの相手に対しては**律速は予算ではなく「自然な代替手の在庫」**。

含意:
- 予算ゼロ（接戦）でも中盤の約 4 割は外せる。予算があれば 5〜7 割。
- 22% の手番は構造的に一致する（9段も同じ手を打つ）。
- ヨセは 9段委譲なので一致率は高め（未実測・60〜75% 見込み）。全体は 40% 前後が目安で、
  相手より低くなるかは相手の一致率次第（**相手の一致率は未実測**）。

## 3. 設計の骨格

### 3.1 「不一致 1 回の値段」price

候補 c（非最善手）を子局面プローブ（難解と同一条件: クリーン 500visits ＋ humanSL 9d 8visits）で測り、

- `vloss(c)` = 最善手の子局面 root との scoreLead 差（検証済み損失・`enigma9_verified_metrics`）
- `E(c)` = humanSL 9d の応手分布で重みづけた相手の期待損失（`enigma9_expected_punish`。
  実戦で較正済み＝実損失 ≈ 1.06×E・enigma spec 追記12）
- **`price(c) = max(0, vloss(c)) − (E(c) − E(best))`**（検証値の負の vloss は ±0.3 のノイズなので 0 にクランプ）

price は「この手で不一致を1つ買うと、最善手を打つより期待値で何目損か」。負なら罠として
**期待値プラス＝予算を作る手**（要件5）、正なら余剰リードから払う代金（要件1）。
難解の `net = E + rarity − vloss` から rarity（自手の珍しさ own_rare・応手の見つけにくさ
reply_rare）を外したものと同値（`price = net(best) − net(c)`）。

rarity を使わない理由: own_rare は「humanPolicy の低い手ほど加点」＝要件2（人間らしさ）と
逆向き。reply_rare は E を与件にすると実損失への寄与ゼロ（実測 t=−0.4・enigma spec 追記12）。

### 3.2 支払い上限 λ（リード連動）

`lead` = 通常解析 root の scoreLead（打つ側視点・クエリ0本）。`surplus = lead − reserve`。

```
lead < MIMIC_BEHIND_LIMIT(-1.0)   → λ = 0          （期待値プラスの手だけ）
surplus <= 0                       → λ = free_loss  （タダ同然の外しだけ・既定 0.3）
surplus > 0                        → λ = min(max_loss, max(free_loss, surplus × spend_rate))
```

- `reserve`（既定 3.0 目）＝ヨセを 9段に任せても勝ち切るための確保リード。
- `spend_rate`（既定 0.25）＝1手で余剰の 1/4 まで。余剰 4 目で 1.0、8 目で 2.0（=max_loss）。
- 難解の消費モード（cost_weight による損失割引）は使わない: 目的は「不一致の**回数**」なので
  1手に大きく払うより、毎手最安の不一致を買い続けるほうが合う。
- `lead < −1.0` を閾値にするのは、13路 komi 込みで黒の開始時 lead がわずかに負になる
  黒白非対称（parity9 の教訓）を序盤で踏まないため。

ハード条件（λ と独立に常時）: `vloss <= max_loss`（既定 2.0）かつ 着手後勝率 `>= min_winrate`
（既定 0.40。どちらも子局面プローブの検証値＝相手の最善応手込み。勝率が取れない候補には
勝率条件を課さない＝難解の基底と同じ扱い）。

### 3.3 資格（人間らしさ or 罠）

親局面の humanSL 9d humanPolicy（8visits・1本）から:

- **支配ガード**: `hp(best) >= dominant_hp`（既定 0.8）→ 最善手（プローブ0本・要件2）。
  罠も打たない（ユーザー要求の文言どおり）。
- **自然**: `hp(c) >= max(min_human_policy(0.05), natural_ratio(0.2) × hp_top)`。
  `hp_top` は盤上全点の最大 hp（pass 除く）。
- **罠**: `E(c) − E(best) >= trap_min_delta_e`（既定 0.5）かつ `hp(c) >= MIMIC_TRAP_MIN_HP`(0.005)。
  人間らしさは免除するが、NN 下限に張り付いた「人間が絶対打たない手」だけは除く
  （jigo の `MIN_HP_HARD_FLOOR` と同値）。
- 資格 = 自然 OR 罠。

### 3.4 選択

資格あり・ハード条件OK・`price <= λ` の候補のうち **price 最小**。最小から `cost_slack`
（既定 0.3）以内に並ぶ候補があれば **hp 最大**（同着は price 小）。該当なしは最善手。
（parity9 の「最安バンド内 humanPolicy 最大」と同型。実測で高価な外しほど hp も低いので、
安さ第1・人間らしさ第2が両方を同時に満たす。）

### 3.5 プローブの shortlist（最大 12 手＋最善手）

hp が先に要るので親 humanSL は**逐次で先に1本**撃つ（8visits・実測 0.05〜0.27 秒。難解の
「バッチ統合」は使わない＝支配ガードでプローブを丸ごと省けるほうが得）。

プール = `enigma9_admissible(parity9_build_candidates(cands, min_visits=1), best, cap=max_loss, min_wr)`
（難解と同じ二段の漏斗・生 loss の足切りは安全側）。そこから:

1. 自然な候補を hp 降順に `MIMIC_SHORTLIST_NATURAL`(4) 手
2. 残りから `enigma9_shortlist_spread(rest, MIMIC_SHORTLIST_CHEAP(4), probe_extra(4))`
   ＝安い順 4 手＋高い帯から等間隔 4 手（罠探索・難解＋と同じ規則）

### 3.6 1手の流れ

```
0. _cancel_ponder / wait_for_analysis / 盤サイズゲート（13路以外は最善手）
1. 候補なし・最善手が pass → 最善手
2. 終局帯（pass 損失 < 0.5 / 相手の直前パス）→ 難解と共通の終局処理
   （基底から `_terminal_band_move` として抽出して共有）
3. lead 取得（通常解析 root）。取れなければ最善手
4. ヨセ判定（難解13と同じ: 手数 >= endgame_move AND 未確定点 <= unsettled_max・sticky
   `game._mimic13_endgame`）。sticky 前だけ ownership Probe を1本撃つ
   → ヨセなら: lead >= reserve → HumanStyle 9段へ委譲 / lead < reserve → 最善手
5. 一致率ログ（parity9_match_tally・判定には使わない）
6. 親 humanSL（8visits）→ 支配ガード
7. λ 計算 → プール → shortlist → 子局面プローブ（1バッチ並列）
8. price / 資格 / ハード条件 → 選択
9. 着手後の先読み（難解の `_start_ponder` をそのまま起動）
```

### 3.7 ヨセ（要件3・ユーザー選択: HumanStyle 9段へ丸ごと委譲）

- 委譲先は持碁と同じ素の 9段 `HumanStyleStrategy(game, {"human_kyu_rank": -8, "modern_style": True})`。
  ai_thoughts に `[Mimic13→9d yose]` を前置。
- **安全弁**: その手番の `lead < reserve` なら最善手（勝ち優先）。フェーズ（ヨセ）は sticky だが、
  9段/最善手の切替は手番ごと（lead は通常解析 root＝クエリ0本）。
- `endgame_move` 既定 **85**＝HumanStyle 自身の終局閾値 `ceil(0.5×169)`。85 手以降の HumanStyle は
  「humanPolicy 最上位手」を決定的に打つ。**85 未満に下げると、その間の HumanStyle は hp 重みの
  ランダム選択（損失 5.6 目未満）になる**点に注意（持碁の13路ヨセ委譲既定が 85 なのと同じ理由）。
- ヨセに入る前の Probe（ownership=True・wRN=0・config visits）は `depth >= endgame_move` から
  sticky になるまでの手番だけ。sticky 後は追加クエリなし（HumanStyle の2本のみ）。

### 3.8 フェイルセーフ

全分岐が「KataGo 最善手を打つ」に倒れる: lead 不明 / humanSL 失敗 / 最善手プローブ失敗 /
プール空 / 資格者なし / price > λ / Probe 失敗（ownership None は `parity9_is_endgame` が
手数だけでヨセ入りに倒す＝外さない側）。

## 4. 設定項目（`ai:mimic13`・接頭辞 `mimic13_`）

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `mimic13_max_loss` | 1手の損失上限（検証済み・目）＝λ の天井 | 0.5/1.0/1.5/2.0/2.5/3.0/4.0/5.0 | 2.0 |
| `mimic13_reserve` | 確保するリード（目）。余剰 = lead − これ。ヨセの 9段委譲の条件にも使う | 0/1/2/3/4/5/7/10 | 3.0 |
| `mimic13_spend_rate` | 1手で余剰の何割まで払うか | 0.1/0.25/0.5/1.0 | 0.25 |
| `mimic13_free_loss` | 余剰が無くても払う「タダ同然」の price（目） | 0/0.1/0.2/0.3/0.5 | 0.3 |
| `mimic13_min_winrate` | 着手後勝率フロア（打つ側視点） | 30/35/40/45/50% | 0.40 |
| `mimic13_dominant_hp` | 最善手の hp がこれ以上なら外さない | 60/70/80/90/95% | 0.8 |
| `mimic13_min_human_policy` | 自然な外しの hp 下限 | 1/2/3/5/10% | 0.05 |
| `mimic13_natural_ratio` | 自然な外しの hp 下限（第一感トップ比） | 0.1/0.2/0.3/0.5 | 0.2 |
| `mimic13_trap_min_delta_e` | 罠とみなす E の上積み（目）。OFF で罠の免除なし | OFF(99)/0.3/0.5/1.0/1.5 | 0.5 |
| `mimic13_cost_slack` | 同値帯の幅（目）。帯の中は hp 最大 | 0/0.2/0.3/0.5/1.0 | 0.3 |
| `mimic13_probe_extra` | 罠探索で高い帯から足すプローブ数 | 0/2/4/6 | 4 |
| `mimic13_endgame_move` | ヨセ切替手数（AND の片側・sticky） | 65/75/85/95/105 | 85 |
| `mimic13_unsettled_max` | ヨセ判定の未確定点上限 | 8/12/16/20/24 | 16 |

モジュール定数（スライダーにしない）: `MIMIC_BEHIND_LIMIT=-1.0` / `MIMIC_TRAP_MIN_HP=0.005` /
`MIMIC_SHORTLIST_NATURAL=4` / `MIMIC_SHORTLIST_CHEAP=4`。プローブ条件は `ENIGMA9_*` を共有。

## 5. 実装構成

- **`Mimic13Strategy(Enigma13Strategy)`**: `BOARD_LEN=13` / `KEY_PREFIX="mimic13"` / `LABEL="Mimic13"` /
  `SETTING_DEFAULTS` 差し替え。**`_generate_move` を上書き**し、基底のヘルパー
  （`_probe_children` / `_run_query` / `_best_move` / `_cancel_ponder` / `_start_ponder` /
  `_setting` / `_log`・`generate_move` の時間ログ）を再利用する。フックを 7 個足して基底の
  monolith に分岐を増やす案は、既存 6 戦略の「ビット同一」保証を危険にするので採らない。
- **基底の変更は1点だけ**: `Enigma9Strategy._generate_move` の終局帯ブロック（ゲート1b）を
  `_terminal_band_move(cands, player) -> Optional[Tuple[Move, str]]` に**機械的に抽出**
  （挙動不変・既存 `TestTerminalHelpers` / `TestTerminalEndToEnd` 21 件が回帰）。
- **純関数**（KataGo/Kivy 非依存・ユニットテスト対象）:
  - `mimic_price_cap(lead, reserve, spend_rate, free_loss, max_loss, behind_limit)` → λ | None
  - `mimic_natural_floor(hp_top, min_hp, ratio)` → float
  - `mimic_hp_top(human_policy, board_size)` → 盤上全点の最大 hp
  - `mimic_shortlist(pool, hp_of, floor, k_natural, k_cheap, extra)` → 候補リスト
  - `mimic_qualifies(hp, delta_e, floor, trap_min_delta_e, trap_min_hp)` → "natural" | "trap" | None
  - `mimic_choose(scored, best_gtp, lam, slack)` → 選択 | None
  - `mimic_yose_delegates(lead, reserve)` → bool
- **先読み**: game 側はフラグ駆動（`_enigma_ponder_owner` / `_enigma_ponder_gen`）で戦略名に
  依存しないのでそのまま動く。wave2 の温め対象は基底の「visits 上位 8 手」のまま
  （mimic の shortlist は hp 上位が混ざるので的中は部分的＝v1 は許容）。
- **登録**: `constants.py`（`AI_MIMIC_13 = "ai:mimic13"`・`AI_STRATEGIES_ENGINE`・
  `AI_STRATEGIES_RECOMMENDED_ORDER`・`AI_STRENGTH`・`AI_OPTION_VALUES`・`AI_OPTION_ORDER`）、
  両方の `config.json`、i18n（jp「擬態（13路）」/ en "Mimic (13x13)"・`aihelp:mimic13`・
  各スライダーのラベル → `compile_mo.py`）、`katrain_debug/runner.py`（`--strategy mimic13`）。

### ログ（`[Mimic13Strategy]`・OUTPUT_DEBUG）

```
Rate: mine=a/n (x%) opp=b/n (y%)
Budget: lead=… reserve=… surplus=… lambda=…
Dominant: best F6 hp=0.91 >= 0.80 -> best move
Natural: floor=0.072 (hp_top=0.36) naturals=[…]
Score G7: vloss=… wr=… E=… dE=… price=… hp=… kind=natural|trap|-
Deviate: played G7 (price=…, vloss=…, dE=…, hp=…, kind=…) instead of F6
Yose: lead=… >= reserve=… -> HumanStyle rank_9d / Yose: lead … < reserve … -> best move
```

実戦の検証はこのログだけで回せるようにする（手番ごとの price・λ・kind・一致率の推移）。

## 6. 検証計画

1. **ユニットテスト** `tests/test_ai_mimic13.py`: 純関数 7 本の境界（λ の3区間と連続性・
   支配ガード・資格の自然/罠/どちらでもない・選択の最安と hp タイブレーク・λ 超過で None・
   ヨセ安全弁）、登録と設定キー集合の整合（constants / package config / SETTING_DEFAULTS）、
   スタブエンジンでの `_generate_move` 通し（支配ガードでプローブ0本・ヨセ委譲・フェイルセーフ）。
2. **既存回帰**: `tests/test_ai_enigma9.py` / `test_ai_enigma_plus.py` / `test_ai_enigma_opening.py`
   全パス（基底の抽出リファクタが挙動不変であること）。
3. **CLI**: `python -m katrain_debug --sgf <13路SGF> --move N --strategy mimic13` で単一局面の
   判定ログ確認、`--batch` 3run 平均で Top1 一致率・平均損失・Top5（**一致率だけで判定しない**＝
   実損失・mean_ptloss と並べて読む）。
4. **実戦（監視対局）**: 成功基準は (a) 勝ち、(b) 終局レポートで自分の一致率 < 相手の一致率。
   ログの `Rate:` 行の推移と、フェーズ別（序盤/中盤/ヨセ）の一致率・払った vloss 合計・
   罠の実現値（enigma spec 追記12 と同じ lead 差分法）を記録する。

## 7. 既知のリスクと校正項目

- **E は本の手（own_hp >= 0.25）で過大**（実測 E 2.14 → 実損失 0.43・n=16）。自然な候補は hp が
  高いので price が楽観的に出うる。予算は毎手の実 lead から測り直すので自己補正されるが、
  払いすぎが見えたら自然な候補の ΔE に割引係数を入れる（v1 では入れない）。
- **ヨセの一致率が高い**（9段委譲＝第一感トップ）。全体の一致率が相手を下回らない場合の次の一手は
  「ヨセの同値手入れ替え（損失 <= 0.1・parity9 の `yose_max_loss` と同型）」だが、ユーザー要件3に
  触れるので v1 では入れない。
- **相手の一致率が未実測**。最初の実戦数局で `Rate:` 行から把握し、`reserve` / `spend_rate` /
  `max_loss` / `dominant_hp` を校正する。
- **1手あたり時間**: 親 humanSL 逐次 1 本（〜0.1 秒）＋プローブ 13 手（難解＋と同規模・コールド
  〜2 秒、先読み的中時 0.4 秒前後）。支配ガードの手番（約 2 割）は 0.1 秒。ヨセは HumanStyle の
  フルクエリ2本（1〜2 秒）。
- **1手先の地平線**: E は相手の次の1手の期待損失しか測れない（難解と同じ構造限界）。

## 8. やらないこと（v1）

- 一致率による λ の増減（相手より十分低い/高いで払いを変える）— ログだけ取り、必要になってから。
- 9路・19路版。
- 難解の rarity 項・消費モード・aim_jigo・局所性・序盤 9段委譲の移植（序盤は自然な外しの
  在庫が最も多い帯で、own_rare を使わないので「珍しすぎる序盤」は構造的に起きない）。
- 先読み wave2 の mimic 専用化。
