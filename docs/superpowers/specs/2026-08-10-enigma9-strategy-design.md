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
