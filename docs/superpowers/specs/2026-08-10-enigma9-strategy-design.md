# 難解（9路）戦略 ai:enigma9 設計

日付: 2026-08-10
対象: `katrain/core/ai.py`（enigma9 純関数群 + `Enigma9Strategy`）

## 1. 要件（ユーザー要求の写し）

1. **序盤〜中盤**: 相手の研究した定跡・手筋を打たせないよう、外した手を積極的に打つ
   （応手の最善手が非常に難解になることで相手を悩ませる）。ただし明らかな悪手や
   **2目以上の損失手は打たない**（9路では挽回が難しい）。案として
   (a) humanPolicy が低くスコアが一番高い手、
   (b) 次の相手の最善手が humanPolicy のより低い手になる手
   （人間が考えつかない手が最善応手になる＝それだけ悩ませられる）。
2. **最終目標**: 2目差で勝利、勝利が難しければ持碁でよい。序盤〜中盤の外しで少し
   損をするので、相手がほとんど最善で応じてきた場合は勝てなくてもよい。
3. **攻め合い**: 1手差となる僅差のせめぎ合いを積極的に作る
   （**間違えなければ勝てる場合のみ**）。これも相手を悩ませることが目的。

補足: 9路 komi 7（中国ルール）の終局差は 0（持碁）, ±2, ±4, … と2目刻みなので、
「2目差の勝ち」は最小の勝ち、持碁はその次＝要件2は「最小の勝ちで十分・引き分け許容・
負けも許容」という成功基準であって、大差を2目に削る要求ではない。

## 2. 設計の骨格

### 難解さの尺度（3項の合算・すべて目数スケール）

候補手 m を1手進めた子局面を独立解析（500visits・クリーン）+ humanSL 9段
humanPolicy 取得（8visits）し、次を計算する:

- **E（期待お仕置き）** `enigma9_expected_punish` = Σ hp(r)·min(loss_r, 8.0) / Σ hp(r)。
  相手が 9d 人間の直感分布どおりに応手したときに落とす目数の期待値。応手の損失
  loss_r は子局面解析の scoreLead から**応手側視点**で計算（基準＝visits>=10 の
  最善応手。浅い応手を基準に混ぜると全応手の損失がかさ上げされるので基準からは
  除外、E への算入は visits>=2 まで許す＝浅い応手の損失は過小評価側なので保守的）。
- **reply_rare（十分な応手の見つけにくさ）** `enigma9_reply_findability` +
  `enigma9_rarity` = 1 − min(1, findability/0.25)。findability は
  **損失 0.3 目以下の応手のうち humanPolicy 最大**の値。要件 (b) の実装だが、
  「最善応手の hp」ではなく「十分な応手のどれかを人間が見つけられるか」を測る
  （hp の高い十分な別解がある局面を難解と誤認しないため）。
- **own_rare（自手の意外さ）** = 1 − min(1, own_hp/0.25)。要件 (a) の実装。
  hp 0.25 以上は「本に載っている手」＝ボーナス 0。

**net = E + 1.0·reply_rare + 1.0·own_rare − max(0, 検証済み損失)**

最善手自身も同じパイプラインでスコアし、挑戦者の net が最善手の net + margin
（`enigma9_net_margin`、既定 0）以上のときだけ外す。margin=0 は「同点なら外す」＝
要件の「積極的に」側に倒した既定。

### 攻め合い要件（3）の実装

専用の攻め合い検出は持たない。1手差の攻め合いを作る手は「相手の並みの応手が
攻め合いに負けて大損する」局面そのものなので E が構造的に高く出る。
「間違えなければ勝てる場合のみ」は安全ゲートがそのまま担保する:
候補の検証済み損失 <= cap かつ着手後勝率 >= フロア（どちらも**相手の最善応手込み**の
探索値）＝この手を打って正しく打ち続ければ形勢は保たれている。

### 二段の漏斗と同深さ検証（実測に基づく設計変更）

9路の通常解析（1000visits・wRN=0.04）は visits を 1〜3 手に集中させるため、
visits>=10 の候補だけではプールが 0〜1 手しか残らない（実測・校正局 move 8:
moveInfos 74手のうち visits>=10 は 2手、visits>=2 でも 3手）。そこで:

- プールは **visits>=1（KataGo が一瞥した全手）**まで広げる（`ENIGMA9_POOL_MIN_VISITS`）。
- 事前足切りは生 loss <= cap と生 wr >= floor（浅い候補の生 loss は打つ側に楽観的＝
  過小評価なので「生 loss > cap ⇒ 真 loss > cap」＝除外の向きは安全）。
- プローブ枠 `ENIGMA9_SHORTLIST`(8) は二段で埋める: 第1段 visits>=10 を loss 昇順、
  第2段 浅い候補を visits 降順（浅い候補の生 loss は順位づけに使えない）。
- **採否と net の損失は子局面プローブの検証値で確定**する
  （`enigma9_verified_metrics`）: 候補同士は同 visits の独立解析なので、最善手の
  子局面 root との scoreLead 差＝検証済み損失（系統誤差が差分で相殺）。着手後勝率も
  子局面 root から取る。1visit の蜃気楼（生 loss が偽に安い手）はここで落ちる。
  実測 move 2: 生 0.15 → 検証 0.29 / 生 0.05 → 0.11 と楽観分が実際に補正された。

ai:tsumego の「スコアの真偽を分離できるのは同深さ検証だけ」と同じ形
（あちらは gain、こちらは loss/勝率）。

### フェーズと終盤（要件2）

- **ヨセ判定**: parity9 と同一の `parity9_is_endgame`（depth >= `enigma9_endgame_move`(30)
  **AND** 盤上の未確定点（|ownership|<0.5）<= `enigma9_unsettled_max`(8)）・sticky
  （`game._enigma9_endgame`）。ownership は depth が閾値に達してから Probe
  （wRN=0・ownership=True 明示）で取る＝序盤〜中盤はこのクエリを撃たない。
- **ヨセの外し予算**: budget = lead − `enigma9_target_score`(2.0)。cap = min(max_loss,
  budget)。budget <= 0.05 なら即最善手（2目勝ち〜持碁の確保）。lead は Probe root の
  scoreLead（wRN=0 の root は精度用。**この moveInfos を候補の損失に使ってはいけない**
  — プールは通常解析から作る）。
- **劣勢**: 特別な分岐なし＝勝率フロアが外しを止め、最善手で粘るだけ。
  「勝てない碁は僅差で負ければよい」の実装は**無理をしないこと**そのもの。

### フェイルセーフ

すべての分岐（9路以外 / 候補なし / 最善=pass / Probe 失敗 / humanSL 失敗 /
最善手プローブ失敗 / プール空 / net で最善が勝つ）が「KataGo 最善手を打つ」に倒れる。

## 3. クエリプラン（1手あたり）

| フェーズ | クエリ | 条件 |
|---|---|---|
| 通常解析 | 1本（既存） | 常時 |
| Probe（ownership+lead, wRN=0） | 1本 | depth >= endgame_move または sticky ヨセ |
| 親 humanSL（own_hp 用） | 1本 | プール非空のとき |
| 子局面プローブ | 候補×2本（クリーン500v + humanSL 8v）最大16本 | 同上・**全部並列発行してから待つ** |

実測（RTX 3080・9路）: 子クエリは 0.0〜0.3 秒/本（並列）。外し判定のある手番で
体感 +1〜3 秒。ヨセの securing 分岐は Probe 1本だけで返る。
**追記3（2026-08-11）で改訂**: 親 humanSL は 8visits・子局面プローブと同一バッチ化、
さらに着手後の先読み（相手考慮時間中の NN キャッシュ温め）を追加。

## 4. パラメータ

GUI スライダー（`ai:enigma9`）:

| キー | 既定 | 意味 |
|---|---|---|
| enigma9_max_loss | 1.0 | 1手あたり損失上限（目）。候補値は 0.3〜**1.8** — 2目以上の損失手は候補値レベルで封じる |
| enigma9_min_winrate | 0.3 | 着手後の勝率フロア（打つ側視点・相手最善応手込み） |
| enigma9_net_margin | 0.0 | 外しに要求する難解さの差（0=同点でも外す） |
| enigma9_target_score | 2.0 | ヨセの目標差。これを超える余剰リードだけ外しに使える |
| enigma9_endgame_move | 30 | ヨセ切替手数（AND 条件の片側） |
| enigma9_unsettled_max | 8 | ヨセ判定の未確定点上限（AND 条件の片側） |

コード定数（`ai.py`）: SHORTLIST=8 / CHILD_VISITS=500 / HP_CHILD_VISITS=8 /
HUMAN_PROFILE=rank_9d / POOL_MIN_VISITS=1 / TRUSTED_VISITS=10 /
REPLY_REF_MIN_VISITS=10 / REPLY_MIN_VISITS=2 / PUNISH_CAP=8.0 / ADEQUATE_LOSS=0.3 /
HP_BOOK=0.25 / W_REPLY_RARE=1.0 / W_OWN_RARE=1.0 / MIN_BUDGET=0.05

## 5. 検証（2026-08-10・校正局 parity9-vs-human-20260808-black.sgf）

- 純関数: `tests/test_ai_enigma9.py` 38件（hp lookup / admissible / 二段 shortlist /
  応手テーブルの基準防御 / E / findability / rarity / net / choose / verified metrics /
  レジストリ登録）。
- **move 2（序盤・黒）**: プール 8手（trusted 6）。F7 を選択（net 0.87: E 0.24 +
  reply_rare(find 16.7%) + own_rare(hp 10.1%) − vloss 0.29、wr 39.5%）。最善 C6
  (net 0.67) を上回った＝要件 (a)(b) どおりの外し。
- **move 8（中盤・黒）**: 唯一の挑戦者 F7 が net −0.13 < F6 0.26 → 最善 F6。
  予算内に見合う難解手が無ければ外さない、が機能。
- **move 40（ヨセ・黒 lead +4.38）**: yose 判定 → budget 2.38 → cap 1.0 →
  admissible 0 → 最善 J9（勝ち確保）。
- **move 39（ヨセ・白 lead −3.80）**: budget 負 → 子クエリ0本で即最善 A4（securing）。

## 6. 既知の限界・却下した案

- **1visit の生 loss が壊れて悲観側に出る手は救えない**（tsumego case O の逆向き）:
  生 loss > cap で足切りされ、プローブされない。全 74 手をプローブすれば拾えるが
  1手 15〜20 秒級になるため却下。開いた盤面で value がそこまで壊れるのは稀
  （case O は詰碁の病理）。エンジン更新時に再評価。
- **E は 1手先の期待値**: 数手先で効いてくる紛れ（相手の悪手を誘う長期的な罠）は
  測れない。`project_per_move_planning_wall`（多手先計画は1手ごとの重み付けで
  強要できない）と同じ構造的壁で、v1 では扱わない。
- **candidate プールを visits>=10 に限る案（parity9 と同一のプール）**: 実測で
  外し候補が 0〜1 手に痩せ、序盤以外で外しがほぼ発生しない → 却下（§2 二段の漏斗）。
- **生 loss だけで採否を決める案**: 浅い候補の楽観バイアスで cap（<2目の保証）が
  形骸化する → 却下。検証値で確定する現行設計に。
- **coverage（humanSL 質量の探索カバー率）で E を減衰する案**: カバー外の質量は
  「自然に見えるが読む価値がない手」＝むしろ罠が効いている状況が多く、減衰は
  逆向き。renormalize + reply_rare 項で拾う現行設計に。実測 cov 0.85〜1.00 で
  実害も未観測。

## 7. 運用メモ

- ログ確認: `[Enigma9Strategy] (Spend|Pool|Score|Drop|Deviate|Best move|Endgame)`。
  `Score <gtp>: vloss=…(raw …) wr=… E=… cov=… find_hp=… own_hp=… reply=… net=…`
  が候補ごとの全成分。
- CLI: `python -m katrain_debug --sgf FILE --move N --strategy enigma9`（batch 可）。
- 9路以外では常に最善手（INFO ログを出して DefaultStrategy 相当）。

## 追記1（2026-08-10）: 勝勢時の消費モード `enigma9_large_lead_max_loss`

### 実戦ログ分析（`game_20260810_193156`・enigma9 白番・**AI の手番は depth の偶奇＝奇数で判定**）

初版の実戦初戦で「相手が損失手を多発しているのに最終一致率が高すぎ、2目以上の
損失手が1手も無い＝AI色が強すぎる」というユーザー報告。ログの実測:

- 序盤〜互角帯（depth 1〜13）は設計どおり外していた（G6/C6/C7/E2 の4回。E2 は
  E=1.26・find_hp 2.0% の罠手）。
- **リードが +6〜+38 に膨らんだ depth 15〜39 は `admissible=0` がほぼ連続**
  （of 46〜66 の候補が全部 cap 1.2 超え）＝強制最善手で、一致率の高さと +38 の
  過剰な勝ち幅はここで作られた。cap 落ちのニアミスも記録されている
  （D8 verified 1.96 / E5 1.24 / F3(初版) 1.24）。
- 勝勢の鋭い局面ほど最善手が支配的になり代替手の損失が跳ね上がるので、
  **固定 cap では勝てば勝つほど AI 化する**構造だった。

### 設計: 予算比例のコスト割引（ユーザー提案＋選択則側の補完）

ユーザー提案は「勝勢時（2目差まで縮まらないとき）はヨセまで lead−2.0 を予算に
損失上限を緩和（上限は設定可・既定5.0）」。**cap を広げるだけでは帯は使われない**
— 選択則 `net = 難解さ − 損失` は損失を等価で引くので、E が典型 0.2〜2 目の中で
3〜5目の勝負手は net で必ず負ける。そこで損失項の重みを予算に反比例させた:

```
budget = lead − target_score            （lead は通常解析 root・クエリ0本）
budget > max_loss のとき（勝勢）:
    cap         = clamp(budget, max_loss, enigma9_large_lead_max_loss)
    cost_weight = max_loss / budget     （≦1・budget→max_loss で連続的に 1 へ）
net = E + reply_rare + own_rare − cost_weight × 検証済み損失
```

- 「余剰リードは安く使える」の直接表現。予算が大きいほど勝負手の実効単価が下がり、
  毎手消費すると lead は target + max_loss 近傍へ単調収束（＝2目差勝ちへ向かって
  余剰を難解さに変換）。境界で cost_weight=1 に連続接続するためモード切替の段差なし。
- 安全は不変: 検証済み損失 ≦ cap（1手で目標差を割らない）＋着手後勝率フロア。
- **ヨセに入ると無効**（ユーザー指定「ヨセの手数になるまでは」）。ヨセは従来どおり
  `cap = min(max_loss, budget)`・cost_weight=1。
- 純関数 `enigma9_spending_plan`（テスト8件）。

### 検証（復元 SGF `calibration-data/enigma9/enigma9-vs-human-20260810-white.sgf`）

ログのクエリから復元（**復元 SGF の初手の色を AI と読まない** — 本局は初手 D4 が
人間の黒、AI は白。戦略ログの depth 奇数と整合）。

- **move 21（lead +12.6）**: `Spend: budget=10.59 cap=5.00 cost_weight=0.11`、
  admissible **1→15** に開き、**F3（検証損失 2.16・E=1.38・応手発見率 5.9%・
  wr 99.8%）へ外し**。H8/G4 は検証損失 5.1/5.5 > cap 5.0 で正しく落ちる。
- **move 15（lead +6.1）**: cap 4.14・cw 0.29 で 3.04目の B5 が漏斗に入るが
  E=0.06・find 0.917（見え見え）で却下 → 最善 C3 自体が E=2.23・find 2.1% の
  罠手であり最善を維持＝高くても難解でない手は買わない。
- **回帰（互角）**: parity9 校正局 move 2 は Spend 非発火・従来と同じ F7 外し。

### 却下した代替案

- **cap 緩和のみ（cost_weight なし）**: net の損失項が等価のままでは E>3〜5 が
  必要になり帯が実質使われない（上記のとおり）。
- **parity9 型の一致率ゲート**: 一致率を直接目標にする戦略は ai:parity9 が既にあり、
  こちらの目的（難解さの最大化）と混ぜると「良い罠があるのにレート達成済みだから
  打たない」が起きる。リード予算のほうが「勝ちの余剰を使う」という意味に一致。
- **勝勢時に λ=0（コスト無視で難解さ最大）**: E 差 0.01 のために 4 目余計に払う
  退化があるため、予算比例の割引に。

## 追記2（2026-08-10）: 13路版 `ai:enigma13`（難解（13路））

ユーザー要望「難解の13路盤も追加」。jigo → jigo9 と同じ盤サイズ別の独立戦略として
`AI_ENIGMA_13 = "ai:enigma13"` を追加した（GUI スライダーも 13路独立）。

### 実装: Enigma9Strategy のクラス属性パラメータ化 + サブクラス

パイプライン（二段の漏斗 / 子局面プローブの同深さ検証 / net 比較 / 勝勢時の消費モード /
ヨセの余剰予算 / フェイルセーフ）は盤サイズ非依存なので、`Enigma9Strategy` を
クラス属性でパラメータ化し、13路版は差し替えのみ:

- `BOARD_LEN`（対応盤ゲート）/ `KEY_PREFIX`（設定キー接頭辞）/ `LABEL`
  （ai_thoughts 表示名）/ `SETTING_DEFAULTS`（既定値）
- sticky ヨセフラグは `game._{KEY_PREFIX}_endgame`＝9路と13路で独立
- ログタグはクラス名（`[Enigma13Strategy]`）
- 純関数・モジュール定数（`ENIGMA9_*`）は盤サイズ非依存でそのまま共有
  （`enigma9_hp_lookup` は board_size 引数を最初から持つ）
- `generate_move` はオーバーライドしない（テストで固定＝解析条件・判定順序は
  9路版とビット単位で同一。変わるのは設定値と盤だけ）

### 13路の既定値（9路との差分と根拠）

| キー | 9路 | 13路 | 根拠 |
|---|---|---|---|
| max_loss | 1.0（候補天井 1.8） | **1.5**（候補天井 3.0） | 「2目以上の損失手は打たない」は挽回が難しい9路の要件（§1）。13路は悪手フィルタの盤サイズ比（NORMAL 3.3→5.6 ≒ ×1.7）でスケール |
| large_lead_max_loss | 5.0 | **8.0** | jigo の 13/19路既定 `jigo_large_lead_max_loss` と同値 |
| min_winrate | 0.3 | 0.3 | 勝率は盤サイズ非依存 |
| net_margin | 0.0 | 0.0 | 同 |
| target_score | 2.0 | 2.0（候補に 5.0 を追加） | 「最小の勝ちで十分」は共通の成功基準 |
| endgame_move | 30（候補 22–38） | **75**（候補 55–95） | 13路の対局長（〜120手）へのスケール。9路の 30 は慣習 ceil(0.5×81)=41 より早め（×0.73）で、その比の13路換算 62 と `jigo_endgame_move_13`=85 の中間。判定は手数 AND 未確定点なので手数側が早めでも未確定点条件が早すぎる切替を防ぐ |
| unsettled_max | 8（≒81点の10%） | **16**（候補 8–24） | 169点の10% ≒ 17 → 16 |

### クエリコスト

モジュール定数は共有のまま（SHORTLIST=8 / CHILD_VISITS=500 / HP_CHILD_VISITS=8）。
13路の子局面クリーン解析（500visits）は9路より1本あたり重いが、発行は同じ全並列
（numAnalysisThreads=12）。体感が重い場合に絞るなら SHORTLIST / CHILD_VISITS を
クラス属性へ昇格して13路だけ変える（現状は未実施＝共有）。

### 変更ファイル

| ファイル | 変更 |
|---|---|
| `katrain/core/ai.py` | Enigma9Strategy をクラス属性パラメータ化（挙動不変）、`Enigma13Strategy` 追加 |
| `katrain/core/constants.py` | `AI_ENIGMA_13`・戦略リスト2つ・`AI_STRENGTH`・`AI_OPTION_VALUES`/`AI_OPTION_ORDER` 各7件 |
| `katrain/config.json` + `~/.katrain/config.json` | `ai:enigma13` ブロック（7キー） |
| `katrain/i18n/locales/{en,jp}/.../katrain.po` + `.mo` | `ai:enigma13` / `aihelp:enigma13` / ラベル7件 |
| `katrain_debug/runner.py` | `STRATEGY_NAME_MAP["enigma13"]` |
| `tests/test_ai_enigma9.py` | 13路の登録・属性・GUI/config 整合の6件を追加（計54件） |

### 検証（2026-08-10）

- `pytest tests/test_ai_enigma9.py` 54 passed（新規6件: 登録 / クラス属性 /
  設定キー集合の一致 / `generate_move` 非オーバーライド / SETTING_DEFAULTS と
  AI_OPTION_VALUES 候補値・パッケージ config.json の整合×2戦略）。
- **13路の実戦校正は未実施**。次のステップは 9路と同じく GUI 実戦（ログの
  `[Enigma13Strategy] (Spend|Pool|Score|Drop|Deviate|Endgame)`）と
  `python -m katrain_debug --sgf <13路SGF> --strategy enigma13 --batch` での
  一致率・実損失の確認。パラメータを動かすときは 3-run 平均（run 間分散）を守ること。

## 追記3（2026-08-11）: 着手時間の短縮（精度不変・9路/13路共通）

ユーザー要望「難解13路の1手の着手時間を、精度を落とさずできる限り短く」。
13路実測（jigo-speedup 校正13路局 `katrain-13ro-20260401-game1.sgf`・プールが立つ
白番8局面 mv41/43/45/49/53/61/77/79・**条件ごとに別プロセス**×2run）で内訳を
測ってから削った。ハーネスは `calibration-data/enigma9/` の
`enigma13_timing_harness.py`（フェーズ別計時） / `enigma13_ponder_harness.py`
（先読み ON/OFF・GUI の実フロー＝通常解析完了→generate→着手→考慮8秒→応手を再現） /
`hp_invariance_probe.py`（humanPolicy の別プロセス比較）。

### 実測の内訳（改修前・NN ウォーム）

| フェーズ | 実測 |
|---|---|
| 通常解析（root 1000v・GUI 側の待ち） | 0.56〜0.75 秒 |
| 親 humanSL（旧: 既定 visits=config max_visits=1000） | **0.05〜0.27 秒** |
| ヨセ Probe（1000v wRN=0） | 0.19〜0.23 秒 |
| 子局面プローブ ×8（clean 500v + hp 8v・全並列） | **1.22〜1.44 秒＝支配項** |

当初仮説「1000v の humanSL 解析が1〜2秒の無駄」は**外れ**（直前の通常解析と
NN キャッシュを共有するためほぼ無料）。**測ってから削る**の実例として残す。

### 第1弾: 親 humanSL の 8visits 化＋プローブバッチ統合

`_probe_children(parent_hp=True)` で親局面の humanSL クエリ（own_hp 用）を子局面
プローブと同一バッチで並列発行し、逐次の壁時間を畳んだ。visits は
`ENIGMA9_HP_CHILD_VISITS`(8)。

**humanPolicy の非決定性（このとき判明）**: humanPolicy は root NN の出力で visits に
依存しない——は正しいが、**別プロセス間では同一クエリでも揺れる**。実測
（13路 move 45 / 77・各条件フレッシュプロセス）:

| 比較 | max\|Δ\| | 上位10手の順位 |
|---|---|---|
| 1000v vs 1000v（別プロセス） | 0.086 / 0.000 | 入替あり / 同一 |
| 8v vs 8v（同） | 0.054 / 0.068 | 入替あり |
| 1000v vs 8v（同） | 0.086 / 0.014 | 入替あり / 同一 |

＝TensorRT のバッチ非決定性による run 間固有分散で、**8visits 化はそのレンジに
何も上乗せしない＝精度中立**（同一プロセス内の比較は NN キャッシュが同値を返す
ため、この分散は見えないことに注意）。なお Jigo Stage1 の `extra_settings`
`maxVisits: 1` は top-level の visits 引数に負けて実際は config visits で走っていた
（既知の「extra_settings の maxVisits は無視される」の実例）→ **同日の fix(jigo) で
`visits=1` を引数化して修正済み**（全戦略の dead な maxVisits キーも除去。詳細は
ai-parameters.md「エンジン設定（maxVisits）」）。

A/B（8局面×2run 平均・別プロセス）: **generate 1.04 → 0.89 秒/手**。着手は
baseline 自身の run 間分散（mv53/77/79 は baseline 同士でも入替）の範囲内で一致。

### 第2弾: 着手後の先読み（相手考慮時間中の NN キャッシュ温め）

tsumego `_maybe_region_prefetch` の enigma 版。着手を返す直前（Deviate と
「最善手が最難解」の2出口）に `_start_ponder` → デーモンスレッド `_ponder_worker`:

1. 選択手の clean プローブの moveInfos から相手の応手 top-`ENIGMA9_PONDER_REPLIES`(3)
   を選ぶ（**KataGo 本命＝visits 最多 1 手＋humanSL 直感順**＝強い相手と人間らしい
   相手の両方の外れ方をカバー）
2. 使い捨て複製ゲーム（`tsumego_simulation_game`）に選択手＋各応手を進め、
   **wave1**: 応手後局面を GUI の通常解析と同条件（visits/ownership とも config 解決）で
   解析
3. **wave2**（wave1 のコールバックから）: その解析の top-`ENIGMA9_SHORTLIST`(8) 候補
   （order 順＝次手番 shortlist の近似）の子プローブ（clean 500v + hp 8v）を
   `_probe_children` と同条件で発行

**結果は全部捨てる＝判定影響ゼロ**。優先度 `PRIORITY_ENIGMA_PONDER`(-50) は実クエリ・
新規ノード解析より必ず下。発火ゲート `_ponder_applies`＝**自分が AI かつ相手が人間**
（デバッグスタブ／バッチ評価は両者 human・AI 同士対局では発火しない）。

**残骸の掃除は gen（世代カウンタ）方式の2段**:

- 主経路 `Game._cancel_enigma_ponder`（game.py の play() フック）: **相手の着手が
  入った瞬間**に gen を進めて発行済みを terminate。発行者の色は `_start_ponder` が
  **メインスレッドで同期的に** `_enigma_ponder_owner` へ記録する（自分の着手では
  打ち切らない判定に使う）。gen も同期部で捕獲してワーカーへ渡す＝**terminate だけ
  ではワーカーの sim 構築（約0.1秒）より速い応手に空振りする**が、gen 不一致なら
  ワーカー・在庫 wave2 コールバックが自己回収する
- 保険 `_cancel_ponder`（generate 冒頭）: GUI（Game.play）を経ない経路用

この掃除を入れる前の実測: 相手が先読み消化前に応手すると実クエリ（root 解析＋
プローブバッチ）が最大51本（wave1 3 + wave2 48）の温めクエリと GPU を取り合い、
**1.6〜1.7 → 2.9〜4.4 秒**に伸びた。terminate 単独版でも sim 構築レースで残り
（an1 2.8〜2.9 秒）、gen 方式で解消（0.73〜0.75 秒＝OFF と同水準。人工的な
「即応手」ケースのみ +0.5 秒の残余で有界）。

**実測（ponder ON/OFF・別プロセス×2run・応手は「着手後局面の通常解析の visits
最多手」で両条件共通・考慮時間 8 秒）**——次手番の 通常解析 an2 + generate gen2:

| 局面 | OFF | ON・的中 | ON・外れ |
|---|---|---|---|
| mv45 継続 | 0.92〜1.09 秒（gen2 0.45〜0.64） | **0.31〜0.48 秒**（gen2 0.08〜0.11） | — |
| mv77 継続 | 0.88〜1.05 秒 | **0.44〜0.45 秒** | OFF と同水準 |

的中率はハーネスの機械的応手で 5/6（外れ1は選択手が run 間で入れ替わった局面）。
実対局の的中率は相手次第だが、外れのコストは遊んでいた GPU 時間だけ。

### 併せて per-move 時間ログを追加

`generate_move` を計時ラッパー化し `[Enigma13Strategy] 着手決定に X.X 秒`
（OUTPUT_INFO・tsumego と同形式＝debug_level 0 でもゲームログに残る）。GUI 実戦の
体感時間はこれに直前の通常解析（0.6〜0.75 秒）が乗る。

### 変更ファイル（追記3）

| ファイル | 変更 |
|---|---|
| `katrain/core/ai.py` | `_probe_children(parent_hp=)`・`_start_ponder`/`_ponder_worker`/`_cancel_ponder`/`_ponder_applies`・generate 計時ラッパー・`ENIGMA9_PONDER_REPLIES` |
| `katrain/core/constants.py` | `PRIORITY_ENIGMA_PONDER`(-50) |
| `katrain/core/game.py` | `Game.play()` に `_cancel_enigma_ponder(move)` フック |
| `tests/test_ai_enigma9.py` | ゲーティング・掃除の7件追加（計61件） |

### 検証（追記3）

- `pytest tests/test_ai_enigma9.py` 61 passed／エンジン不要スイート全体も PASS
- 判定ロジック・判定に使うクエリの内容は全経路で不変（先読みは結果を捨てる、
  親 humanSL は上記の精度中立の実測）。着手の A/B は baseline 自身の run 間分散が
  支配的なため「同一分布」を確認（改修前後で同一局面の選択が同じ集合内で揺れる）
- **GUI 実戦での確認ポイント**: ゲームログに `着手決定に X.X 秒`（毎手）と
  `Ponder: warming replies [...]`（debug_level 1）が出る。相手の考慮が短い連打でも
  `着手決定` が伸びないこと

## 追記4（2026-08-12）: 19路版 `ai:enigma19`（難解（19路））

ユーザー要望「難解の19路盤も追加」。追記2（13路版）とまったく同じ方式＝
`Enigma9Strategy` のクラス属性差し替えサブクラス `Enigma19Strategy` を追加した
（`AI_ENIGMA_19 = "ai:enigma19"`・GUI スライダーも 19路独立）。`generate_move` は
非オーバーライド＝選択パイプライン・二段の漏斗・同深さ検証・勝勢時の消費モード・
ヨセ予算・フェイルセーフ・先読み（追記3）・per-move 時間ログはすべて共有。
sticky ヨセフラグは `game._enigma19_endgame`、ログタグは `[Enigma19Strategy]`。

### 19路の既定値（13路との差分と根拠）

| キー | 13路 | 19路 | 根拠 |
|---|---|---|---|
| max_loss | 1.5（候補天井 3.0） | **2.0**（候補天井 4.0） | 悪手フィルタは13路と同じ NORMAL=5.6 だが、盤が広く対局も長い（〜250手）ぶん1手の損失の挽回機会が多いので一段だけ開ける。5.6（悪手フィルタ相当）までは開けない＝「難解だが悪手ではない」帯に留める |
| large_lead_max_loss | 8.0 | 8.0 | jigo の 13/19路共通既定 `jigo_large_lead_max_loss` と同値 |
| min_winrate / net_margin | 0.3 / 0.0 | 0.3 / 0.0 | 盤サイズ非依存 |
| target_score | 2.0（候補 0–5） | 2.0（候補 0–5） | 「最小の勝ちで十分」は共通の成功基準 |
| endgame_move | 75（候補 55–95） | **150**（候補 120–180） | 19路の対局長へのスケール。150 は `jigo_endgame_move`（19路ヨセ委譲既定）・deception phase3 開始と同じ手数で、13路 75 の盤点数比（361/169 ≒ 2.1）換算 160 とも近い。判定は手数 AND 未確定点なので手数側が早めでも未確定点条件が早すぎる切替を防ぐ |
| unsettled_max | 16（≒169点の10%） | **36**（候補 24–48） | 361点の10% ≒ 36 |

### クエリコスト

モジュール定数は共有のまま（SHORTLIST=8 / CHILD_VISITS=500 / HP_CHILD_VISITS=8）。
19路の子局面クリーン解析（500visits）は13路よりさらに重いが、発行は同じ全並列＋
追記3 の先読みが載る。体感が重い場合に絞るなら SHORTLIST / CHILD_VISITS を
クラス属性へ昇格して19路だけ変える（現状は未実施＝共有）。

### 変更ファイル（追記4）

| ファイル | 変更 |
|---|---|
| `katrain/core/ai.py` | `Enigma19Strategy` 追加（サブクラスのみ・共有コード不変） |
| `katrain/core/constants.py` | `AI_ENIGMA_19`・戦略リスト2つ・`AI_STRENGTH`・`AI_OPTION_VALUES`/`AI_OPTION_ORDER` 各7件 |
| `katrain/config.json` + `~/.katrain/config.json` | `ai:enigma19` ブロック（7キー） |
| `katrain/i18n/locales/{en,jp}/.../katrain.po` + `.mo` | `ai:enigma19` / `aihelp:enigma19` / ラベル7件 |
| `katrain_debug/runner.py` | `STRATEGY_NAME_MAP["enigma19"]` |
| `tests/test_ai_enigma9.py` | 19路の登録・属性・GUI/config 整合を追加 |

### 検証（追記4）

- `pytest tests/test_ai_enigma9.py`（19路分を含めて PASS）
- `python -m katrain_debug --sgf <19路SGF> --move N --strategy enigma19` で
  盤サイズゲート通過・パイプライン動作を確認
- **19路の実戦校正は未実施**。次のステップは GUI 実戦（ログの
  `[Enigma19Strategy] (Spend|Pool|Score|Drop|Deviate|Endgame)`）と
  `--batch` 3-run 平均での一致率・実損失の確認

## 追記5（2026-08-14）: `aim_jigo` オプション＝持碁〜2目以内の負けを狙う（9/13/19路共通）

ユーザー要望「持碁もしくは2.0目以内で負けることを目指すオプション。優先度は
持碁 > 2.0目以内の負け > 2.0目を超える負け。ただし大差で勝っている場合に
わざと明らかな大損失手を打たない（わざと悪手を打っているとバレないように）」。

### 設計

チェックボックス `enigma{9,13,19}_aim_jigo`（既定 OFF）。ON のとき:

1. **target を `ENIGMA9_JIGO_TARGET`(-1.0) に固定**（`target_score` は無視）。
   -1.0 は許容帯 [-2, 0] の中心＝**唯一パリティに依存しない狙い点**: 9路 area
   scoring の整数コミ（komi 7 ⇒ 最終目差は偶数 0/±2/…）では両隣の到達点 0 と -2 が
   どちらも許容帯、半目コミ（±0.5/±1.5）でも両隣が帯の内側。0 を狙うと収束ノイズ
   （検証済み損失の ±0.3 程度）の上振れがそのまま「勝ち」＝帯の外に出る。
2. **勝率フロアを無効化**（`min_wr = 0.0`）し、安全条件を
   「**検証済み損失 <= cap <= lead − target**＝着手後も target を割らない」に一本化。
   意図して勝率 50% を割りに行くモードでは勝率で安全を測れない — ヨセで lead が
   僅かに負（＝設計どおりの局面）ほど探索値の勝率が急落し、正当な外しを全部
   ブロックする（parity9 改修 2026-08-08 の「予算 → 勝率フロア」のちょうど逆向き）。
3. **中盤 cap をヨセ予算と同じ式で頭打ち**＝新純関数 `enigma9_aim_cap(lead, target,
   cap) = min(cap, max(0, lead − target))`。通常モードの中盤 cap は lead と無関係
   （max_loss / 勝勢時は spending_plan が緩和）だが、aim では lead <= target で 0
   ＝**最善手で維持/挽回**。これが優先度の「2目超の負けを避ける（挽回）」と
   「持碁へ寄せる（下から 0 に近づく）」を同じ1本で実装する。lead が None
   （root 解析なし）はフェイルセーフ＝最善手。
4. **勝勢の削りは既存の消費モードをそのまま流用**（budget = lead − (-1)）。1手の
   損失は `large_lead_max_loss` で頭打ち・選択は難解さ net 最大＝「一番もっともらしく
   見える紛れ手」から順に削るので、**大差でも露骨な大損失手は打たない**（要件の
   バレ対策は通常の難解モードと同じ機構が担保）。そのぶん**削り切れないほどの
   大差は僅差勝ちで終わりうる**（仕様として明記・ヘルプにも記載）。
5. ヨセは既存コードのまま（budget = lead − target が target=-1 で動くだけ）。
   sticky・手数 AND 未確定点の判定も不変。

**変更が発火しない場合のビット同一性**: OFF のとき新コードは `aim_jigo` の bool 読取
だけで、cap・min_wr・target とも従来値＝解析条件も採用判断も不変（シャッフルなし）。

### 変更ファイル（追記5）

| ファイル | 変更 |
|---|---|
| `katrain/core/ai.py` | `ENIGMA9_JIGO_TARGET`・純関数 `enigma9_aim_cap`・`_generate_move` の aim 分岐・3クラスの `SETTING_DEFAULTS` に `aim_jigo: False` |
| `katrain/core/constants.py` | `AI_OPTION_VALUES`（"bool"）・`AI_OPTION_ORDER` 各3件 |
| `katrain/config.json` + `~/.katrain/config.json` | `enigma{9,13,19}_aim_jigo: false` |
| `katrain/i18n/locales/{en,jp}/.../katrain.po` + `.mo` | ラベル3件＋ `aihelp:enigma{9,13,19}` 追記 |
| `tests/test_ai_enigma9.py` | `TestAimCap`（4件）＋ GUI 整合テストの bool 分岐対応 |

### 検証（追記5）

- `pytest tests/test_ai_enigma9.py` 67 passed
- CLI 単一局面（`--settings enigma9_aim_jigo=true`）: リード +12 の勝勢局面で
  Spend（budget = lead+1）→ 難解手への削りを確認（校正 SGF move 21）
- **実戦校正は未実施**。GUI 実戦での確認観点: (a) 終局目差が 0〜-2 に入るか、
  (b) `AimJigo: lead ... -> best move` が劣勢で出るか、(c) ヨセの
  `Endgame budget` が target=-1.0 で出るか

## 追記6（2026-08-22）: ヨセでは「自手の意外さ」を net から外す（9/13/19路共通）

### 症状（ユーザー報告）

「終盤のヨセでも humanPolicy の低い（普通の人間では打たない）手を打つことがある」。

### 原因（実測で再現・校正局 parity9-vs-human-20260808-parity9b・9路・ユーザー設定
max_loss 1.6 / target_score 0.2 / aim_jigo ON）

`--move 53`（白番・lead +5.60・ヨセ・budget → cap 1.60）:

```
Score E9: vloss=0.00 E=0.19 find_hp=0.891 own_hp=0.957 net=0.19   ← KataGo 最善
Score J8: vloss=0.27 E=0.32 find_hp=0.828 own_hp=0.001 net=1.05   ← 採用（誤り）
Deviate: played J8 instead of E9
```

net = E + reply_rare + **own_rare** − loss のうち、J8 の net を作っているのは
own_rare の **+0.996**（hp 0.1%）だけ。E 差は 0.13 目・応手は 82.8% で見つかる
＝**罠になっていないのに 0.27 目払っている**。ヨセは E も応手の見つけにくさも
候補間で横並びに潰れる（実測 E 0.19 vs 0.32）ので、**own_rare が net の順位を
そのまま決める＝予算内で最も humanPolicy の低い手が機械的に選ばれる**という構造。

own_rare は要件1「相手の**研究した定跡・手筋**を外す」ための項で、外す対象の
知識が残っている序盤〜中盤の道具。ヨセは1手の目数がほぼ確定していて手順も
一本道なので、意外さだけを買った手は相手から見て「人間が打たない手」にしか
ならない（jigo が `jigo_endgame_humanstyle` でヨセを9段へ委譲したのと同じ理由）。

### 修正

純関数 `enigma9_own_rarity_weight(in_yose)`（ヨセ 0.0 / それ以外
`ENIGMA9_W_OWN_RARE`=1.0）を追加し、`_generate_move` がヨセ判定の直後に
`w_own` を解決して `enigma9_net_score(..., w_own=w_own)` へ渡す。ヨセの外しは
**E（相手が実際に間違える期待損失）と応手の見つけにくさ＝本物の罠**だけで
正当化される。ログの Score 行に `(w_own=…)` を出して事後に追える。

- 適用は**ヨセのみ**（sticky ヨセ判定が立った手番）。序盤〜中盤・勝勢の消費モードは
  重み 1.0 のまま＝**非ヨセ手番の解析条件も採用判断もビット同一**（`in_yose` が
  False の経路は定数が同値に解決されるだけ）。
- 設定キーは増やさない（固定挙動）。

### 検証

- 単体: `tests/test_ai_enigma9.py` に `TestOwnRarityWeight` 4件を追加（71 passed）。
  `tests` 全体（test_ai.py 除く）930 passed。
- E2E（CLI・同一設定・同一局面）:
  - `--move 53`: J8 net 1.05 → **0.10 < 最善 E9 0.22** ＝ `Best move wins the
    confusion race` で **E9**（自然な最善手）に戻った。
  - `--move 35`: 依然 E4 へ外すが理由が変わった＝**E=1.76 の本物の罠**で
    検証済み損失 **−0.03 目（実質タダ）**。意外さ項なしでも最善 F2（net 0.22）に
    勝つ。「ヨセでも罠が実在するなら外す」は設計どおり。

### 既知の残り

E が高ければヨセでも hp の低い手は打ちうる（move 35 の E4 は own_hp 3.7%）。
「ヨセでは hp の低い手を一切打たない」まで要るなら、外し候補に humanPolicy の
下限（絶対値または最善手比）を課す案が次の一手（今回は未実装＝ユーザー選択で
「意外さ項の無効化のみ」を採用）。

---

## 追記7（2026-08-23）: 盤面監視モードのヨセの即応（精度不変・9/13/19路共通）

### 症状と実測

「難解モードのヨセが遅い（秒読みでつらい）」というユーザー報告。直前のコミット
`d8059bb`（ヨセの own_rare 無効化）を疑ったが、**あの変更は net の重みだけで
クエリを1本も増やしていない**（採否の順位が変わるだけ）。ヨセが遅いのは元からの構造。

実測（`~/.katrain/logs/game_20260823_024656.log`・9路・盤面監視モードで進行した実戦）:

| 手番 | `着手決定に X 秒` | 内訳 |
|---|---|---|
| ヨセ前 | 0.0〜0.4 | 子局面プローブのみ（ponder で温まっている） |
| ヨセ | 0.7〜1.7 | **Probe 1.1 秒** + プローブバッチ 0.2 秒 |

`depth=52` の手番を1本ずつ追うと `QUERY:15635`（`includeOwnership=true` /
`wideRootNoise=0` / 2000visits）が **1.1 秒**、続く子局面バッチ（500v×2 + 8v×3）が
0.2 秒。**支配項はヨセ判定クエリ（Probe）**で、しかもこれは既存の応手先読み
（`_maybe_board_watch_prefetch`・`node.analyze()` の既定＝ownership なし）では
**1秒も速くならない** — KataGo の NN キャッシュは ownerMap の有無を区別するため
（CLAUDE.md「KataGo 解析結果の扱い」・詰碁 spec の実測 2.70秒 vs 0.10秒 と同じ罠）。

### 設計

Probe が sticky 後に運んでいる情報は**外し予算の lead だけ**（未確定点の数え直しは
sticky なので不要）。そこで2方向から削る。**どちらも解析条件を変えないので
「シャッフル」は起きない**（CLAUDE.md の A/B 心得）。

**(1) 飽和帯では Probe を撃たない**（採用判断はビット同一）

ヨセの cap は `min(max_loss, lead − target)`。余剰 `lead − target` が `max_loss` を
十分上回っていれば cap は **lead の値によらず max_loss** なので、lead をどの精度で
測っても結果が変わらない。この帯だけ通常解析 root の `scoreLead`（クエリ0本）で
判定して Probe を省く:

```python
def enigma9_yose_probe_skippable(lead, target, max_loss, margin=ENIGMA9_FAST_YOSE_MARGIN):
    if lead is None:
        return False
    return (lead - target) >= max_loss + margin
```

- `margin = ENIGMA9_FAST_YOSE_MARGIN`(0.5 目) は、通常解析 root が
  **wideRootNoise=0.04**（候補を広げるノイズ）で撃たれているぶんの揺れの吸収。
- 適用は **ヨセ sticky 後** × **`game.board_watch_active`** の AND
  （`_fast_yose_lead`）。ヨセ突入の判定には ownership が要るので初回は従来どおり、
  監視していない経路（通常対局・バッチ評価・CLI）は1行も変わらない。
- **接戦（余剰が `max_loss + margin` 未満）は従来どおり Probe を撃つ**＝lead が
  そのまま予算になる帯＝目差の精度が要る局面では何も落とさない。ユーザーの
  懸念（「目差を正確に計算する必要がある段階で劣化するのでは」）はここで閉じる。
- `cap <= ENIGMA9_MIN_BUDGET`(0.05) の早期 return は飽和帯では構造的に起きない
  （余剰 >= max_loss + 0.5）ので、省略しても分岐の意味は変わらない。

実測ログのヨセ14手番は lead **5.77〜34.48**・cap は14本とも **1.60**＝**全部が飽和側**
なので、この対局なら判定は1手も変わらずに 1.1 秒が消える。

**(2) 接戦で残る Probe は応手先読みで温める**（値は同一・速くなるだけ）

戦略が Probe を撃った手番に `game.board_watch_probe_warm` を立て、
`Game._board_watch_prefetch_worker` が応手 top-K の子局面へ**同条件**
（`ownership=True` / `extra_settings={"ignorePreRootHistory": False, "wideRootNoise": 0.0}` /
`include_policy=False` / visits 未指定＝config の max_visits）のクエリを1本ずつ足す。
結果は捨てる＝判定影響ゼロ、priority は既存の `PRIORITY_BOARD_WATCH_PREFETCH`(-50)、
掃除は既存の `_cancel_board_watch_prefetch`（同じ子ノードに紐づくので追加の後始末は不要）。
的中率は実測 top-5 68.7%（追記4 の応手先読みと同じ母数）。

先読み側に置いたのは、**難解モードの ponder（`_start_ponder`）が早期 return 経路では
発火しない**ため。接戦のヨセは `cap <= MIN_BUDGET` で `_best_move` に倒れる手番が多く、
そこで ponder は動かない＝ちょうど温めが要る手番を取りこぼす。`Game.play()` から
駆動される監視モードの先読みなら全経路を覆う。

### 実装

- `ai.py`: `ENIGMA9_FAST_YOSE_MARGIN` / `enigma9_yose_probe_skippable`（純関数） /
  `Enigma9Strategy._fast_yose_lead` / ゲート2 の分岐（`board_watch_probe_warm` の設定つき）。
  13/19路は `_generate_move` 共有なのでそのまま効く。
- `game.py`: `Game.board_watch_active` / `board_watch_probe_warm` の初期化と、
  `_board_watch_prefetch_worker` の温め1本。
- `__main__.py`: `_do_board_watch_start` で `board_watch_active = True`、
  `_stop_board_watcher`（kind=`"game"`）で `board_watch_active` /
  `board_watch_prefetch_replies` / `board_watch_probe_warm` を戻す
  （**既存の取りこぼしの修正**＝従来は監視 OFF 後も応手先読みが回り続けていた。
  game.py の「__main__ が監視 ON で設定し OFF で 0 に戻す」というコメントの意図どおりに揃えた）。
- ログ: 省いた手番は `Endgame budget: lead~<値> target=… cap=… (watch: probe skipped)`。

### 検証

- `pytest`: 941 passed（新規11件＝`TestYoseProbeSkippable` 5 / `TestFastYoseLead` 4 /
  先読みの温め 2）。温めのテストは**実クエリと同条件であること**を kwargs 単位で固定する
  （条件がずれると NN キャッシュが温まらない、が過去に何度も踏んでいる罠）。
- 期待効果: ヨセの `着手決定` 1.3 秒 → 約 0.2 秒（残りは温まっている子局面プローブ）。
  応手検出→着手までの往復は 1.6 秒 → 約 0.5 秒。接戦では Probe が残るが、先読み的中時は
  1.1 秒 → 0.1 秒級。

---

## 追記8（2026-08-25）: 13/19路の局所性オプション（設計）

13路・19路で着手が盤の各所へ飛び飛びになる（実測: 外した手の 69% が最善手から
チェビシェフ距離 4 以上、序盤は own_rare だけで別の隅へ飛ぶ）問題への調整版。
own_rare を「相手の直前手／KataGo 最善手」の近傍で減衰させ、net の同点帯では最も近い
手を採るオプション（`enigma{13,19}_locality_stddev` / `_locality_slack`・既定 OFF）。
設計・実測・検証計画は別 spec `2026-08-25-enigma-locality-design.md`。

---

## 追記9（2026-08-27）: 盤面監視モードの先読みの再設計（精度不変・9/13/19路共通）

ユーザー要望「難解の盤面監視モード中の着手をさらに速く（特に13路）」。追記3の先読みと
追記7のヨセ即応が載った状態で、今日の13路監視対局を実測してから3つの原因を直した。
**解析条件・採用判断はどれもビット同一**（変えたのは温めるもの・温める順番・フラグ・
自ノードの表示用解析の出し方だけ）。

### 実測（改修前）

`~/.katrain/logs/game_20260827_155133.log`（13路・AI 黒・70手・監視モード・セッション2局目）:

| 項目 | 値 |
|---|---|
| 1手の所要（相手の着手後の root 解析＋`着手決定`） | 中央値 **2.1 秒**（ヨセ前 1.85 / ヨセ 2.2） |
| 先読み的中時 / 外れ時 | 0.2〜0.9 秒 / 2.4〜3.0 秒 |
| 先読み的中率（K1+H2） | 44%（1局目 `154802` は 28%、`0823_051702` は 70%） |
| ヨセ判定 Probe（2000v・ownership・wRN=0） | 中央値 **1.1 秒** × ヨセ31手（lead 16〜17 なのに1手も省かれていない） |
| 子局面プローブ 500v | 中央値 1.0 秒（外れ時） |
| アプリの考慮時間（クエリ完了連鎖からの下限推定） | 中央値 2.8 / 4.5 / 4.8 秒（3局） |

**原因1（バグ）**: `_do_new_game` は `Game` を作り直すので `board_watch_active` /
`board_watch_prefetch_replies` が初期値（False / 0）に戻るが、監視スレッド（kind="game"）は
`_stop_board_watcher(kinds=("tsumego",))` で生き残る。2局目では追記7の Probe 省略が一度も
発火せず（`probe skipped` 0 件）、応手先読み（board-watch spec 追記4）も 0 本だった。

**原因2（二重温め）**: フラグが生きている1局目（`154802`）は逆に、enigma の ponder（root 3本）
＋応手先読み（root 5本）＋自ノード解析（2000v）＝**2000visits の root が 9 本横並び**で走り、
アプリの約 2.8 秒では 1 本も温まり切らず的中 28%。KataGo の analysis engine は priority で
並べ替えるだけで同時実行本数を絞らない（numAnalysisThreads=12 まで全部走り GPU を分け合う）
ので、有力な応手から順に温まり切る、にはこちらで本数を絞るしかない。

**原因3（選手）**: 監視対局3局・148局面をオフラインで再解析し（`calibration-data/enigma9/ponder_pick_probe.py`。
着手後局面に clean 500v＝プローブ相当・humanSL 8v・2000v を撃ち、実際の応手の順位を測る）:

| 上位K | KataGo visits順(500v) | KataGo visits順(2000v) | humanSL 9d 順（clean候補内） | humanSL 9d 順（全盤） | 旧 K1+H2 |
|---|---|---|---|---|---|
| 1 | 18.9% | — | 35.8% | **35.1%** | — |
| 3 | 38.5% | 32.4% | 52.0% | **53.4%** | 50.0% |
| 5 | 47.3% | 42.6% | 60.1% | **62.2%** | — |
| 8 | 55.4% | 54.7% | 68.2% | **74.3%** | — |

このアプリは KataGo の PV ではなく humanSL 順で打つ。KataGo 本命（K1 18.9%）は humanSL 1位と
15.5% 重なり、単独の寄与は humanSL 6番手（+6pt）より小さいので選手から外した。
局別（K1 / K3 / K5 / 旧）: `155133` 17/35/42/48%、`154802` 3/13/20/20%、`0823_051702` 31/59/71/71%。

9路も同じ傾向（2026-08-27 追試・9路 Enigma9 監視対局5局 130局面）: KataGo visits順 top-1/3/5/8 = 23.8/40.8/53.8/69.2%、humanSL 9d 全盤順 top-1/3/5/8 = 60.8/**69.2**/76.9%、旧 K1+H2 = 56.2%（局別 84/48/83/21/52%＝アプリの局ごとの振れが大きい）。19路は監視対局のログが無く未計測（機構は共通・root 2000v が重いぶんレーン順の「上位から温まり切る」が効く側）。

### 設計

1. **監視フラグの復元** — `board_watch.apply_game_watch_flags(game, cfg)` を新設し、
   `_do_board_watch_start` と `_do_new_game`（`_board_watch_kind == "game"` のとき）の両方から呼ぶ。
   → 2局目以降もヨセの Probe 省略（追記7）と応手先読みが生きる。
2. **温めの一本化** — `_maybe_board_watch_prefetch` は `_enigma_ponder_owner == node.move.player`
   （ponder がこの着手で発火済み）なら撃たない。ponder が発火しない手番（早期 return＝プローブ無し）
   は従来どおり応手先読みが担当。追記7 (2) の `board_watch_probe_warm`（接戦ヨセの Probe 温め）は
   ponder 側の root ジョブにも同条件で足した（ponder が発火する手番でも失わない）。
3. **選手と順序** — `enigma9_ponder_order`（humanSL 全盤順・非合法/pass 除外）top-`ENIGMA9_PONDER_REPLIES`(5)。
   ジョブは `enigma9_ponder_jobs` の価値順 `root#1, root#2, wave2#1, root#3, wave2#2, root#4, root#5`
   （wave2＝子プローブ 8本×(500v+8v) は root の約2倍の visits を食うので上位 `ENIGMA9_PONDER_WAVE2`(2)
   手だけ）を `PonderLanes`（同時 `ENIGMA9_PONDER_LANES`(3) 本）で流す。wave2 は自分の root が
   返るまでレーンを持って待つ。GPU 予算の目安: 1本 1250v/s・4本で 2500v/s に飽和、アプリの
   考慮時間 2.8〜4.8 秒 ≒ 7〜12k visits ＝ root 5本（10k）がちょうど収まる規模。
4. **自ノード解析の後回し** — 監視モードで ponder が armed（`_enigma_ponder_owner == move.player`）なら
   `Game.play` は自ノードに fast（100v）解析だけを出し（`_enigma_ponder_defers_own_analysis`）、
   config visits のフル解析は ponder の own ジョブ（末尾）が温めの後に発行する。相手が先に打てば
   fast のまま＝**表示（勝率グラフの AI 手の精度）だけの差**で、判定はこのノードの解析を読まない。
   温めを 1 本も出せない手番（humanPolicy 無し・複製ゲーム不可・合法な応手無し）はその場で
   フル解析を出す（`issue_own_now`）。監視モード外は従来どおり即時にフル解析。

掃除は従来どおり gen 方式（`Game._cancel_enigma_ponder` が相手の着手で gen を進め、発行済みは
`_enigma_ponder` のノード単位で terminate。own のフル解析を出した後は本譜ノードもそのリストに入る）。

### 実測（改修後・実エンジン E2E `calibration-data/enigma9/ponder_e2e_watch.py`・13路校正局・考慮 5 秒）

| 局面 | 選手（humanSL 順） | 応手 | 次手番: root 解析 + generate |
|---|---|---|---|
| mv45 的中 | L9 F9 J10 G7 D11 | L9 | **0.36 + 0.52 = 0.88 秒** |
| mv77 的中 | J1 K1 D11 H12 E6 | J1 | **0.22 + 0.38 = 0.59 秒** |
| mv45 外れ | L9 F9 K9 J10 G7 | K10（KataGo 本命） | 0.42 + 0.31 = 0.73 秒（本命は選択手の 500v プローブが部分的に温めている） |
| mv77 外れ | J1 H1 H3 F1 D11 | G11 | 1.28 + 1.88 = 3.16 秒（従来の外れと同水準） |

期待効果（今日の対局に当てはめると）: ヨセ 2.2 → 約 1.1 秒（Probe 省略が生きる）、ヨセ前は
的中率 50 → 62% で中央値 1.85 → 約 1.3 秒。外れた手番は従来どおり。

### 変更ファイル

| ファイル | 変更 |
|---|---|
| `katrain/core/ai.py` | `enigma9_ponder_order` / `enigma9_ponder_jobs` / `PonderLanes`、`_ponder_worker` の再実装（humanSL 選手・レーン・probe_warm・own ジョブ・`issue_own_now`）、`_start_ponder` の発火条件を hp 有りに、定数 `ENIGMA9_PONDER_REPLIES` 3→5・`ENIGMA9_PONDER_WAVE2`・`ENIGMA9_PONDER_LANES` |
| `katrain/core/game.py` | `Game.play` の自ノード解析を `analyze_fast=_enigma_ponder_defers_own_analysis(move)` に、`_maybe_board_watch_prefetch` の ponder への譲り |
| `katrain/core/board_watch.py` | `apply_game_watch_flags` / `PREFETCH_REPLIES_DEFAULT` |
| `katrain/__main__.py` | `_do_board_watch_start` / `_do_new_game` から `apply_game_watch_flags` |
| `tests/test_ai_enigma9.py` | TestPonderOrder / Jobs / Lanes / Worker / WorkerFallback（14件） |
| `tests/test_board_watch_prefetch.py` | prefetch の譲り・fast 解析・フラグ復元（静的検査含む 9件） |

### 検証

- `pytest --ignore=tests/test_ai.py`: 1100 passed（`test_collapsable_panel.py` の 6 件は既知の順序依存フレーク＝単体では 6 passed）。
- 実エンジン E2E（上表）: 例外なし・選手が humanSL 順・own のフル解析が温めの後に出る（考慮 5 秒では
  wave2 の後なので fast のまま終わることが多い＝設計どおり表示だけの差）。
- **GUI 実戦での確認ポイント**: 2局目以降のログに `Endgame budget: … (watch: probe skipped)` が出る／
  `Ponder: warming replies […]` が 5 手／ponder が発火した手番に `board_watch prefetch:` が出ない／
  的中率は `ponder_pick_probe.py` と同じ集計（`Ponder:` 行と `相手の着手` 行の突き合わせ）で測れる。
- 既知: E2E ハーネスの終了時に `_write_stdin_thread` の `AttributeError`（engine.shutdown 後に
  温めクエリが 1 本流れる）が出るが、デーモンスレッド内で無害。GUI は監視 OFF/新規対局で
  `_cancel_enigma_ponder` / `on_new_game` が先に走る。
