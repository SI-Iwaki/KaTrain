# 難解の「捨て身の罠」オプション 設計

日付: 2026-09-18
対象: `ai:enigma9` / `ai:enigma13` / `ai:enigma19` と難解＋ `ai:enigma{9,13,19}plus`
（`Enigma9Strategy._generate_move` を共有する 6 戦略。`Mimic13Strategy` は `_generate_move` を上書きしているので対象外）
親 spec: `2026-08-10-enigma9-strategy-design.md`（追記1=消費モード）／姉妹: `2026-09-17-enigma-gamble-design.md`（序盤の賭け罠）
実測の記録: `calibration-data/enigma-overdraft/enigma-overdraft-results-20260918.md`

（GUI の表示名は「捨て身の罠」。コード上の名前は overdraft＝リードの予算 `lead − target` を超えて払う、の意）

## 1. 要望

リードしている碁で、ちゃんとした罠の手があり、「相手が難解な最善手で正しく応じたらこちらが 2〜3 目程度の劣勢になるが、
罠に引っかかればこちらが勝勢のまま」であれば、そのリスクを取って積極的に打つオプションが欲しい（ヨセ以外）。
正しく応じられたら素直に負ける、という演出をしたい。

現行の難解は勝勢時の消費モードで余剰リード `lead − target` までしか払わない（着手後も target 以上が残る）ので、
この種の手は候補にすら入らない。

## 2. 実測（2026-09-18・13 路 18 局の反実仮想）

復元 SGF の AI 手番 293（手数 10〜84・リード 0〜10 目）で、通常上限の外〜「リード + 4.5 目」の候補を 12 手ずつ
子局面プローブで検証した（方法と全表は実測の記録を参照）。

- **在庫はある。ただしリード 3.5 目以下には無い**（126 手番で 0 件）。文字どおりの罠（応じられたら −1〜−3 目・
  正しい応手が 9 段の第一感に無い・引っかかれば +2 目以上）は 14 手番＝0.78 回/局で、全部が消費モードの手番。
- 消費モード手番（10.1/局）での期待発動回数（最大ビハインド 2.5 目）:

  | 応じられた後のリード | 引っかかった後 | プローブ 4 手 | 6 手 | 8 手 | 12 手 |
  |---|---|---|---|---|---|
  | 必ずマイナス `[−2.5, 0)` | >= +2 | 0.59 回/局（42% の局で 1 回以上） | **0.82（55%）** | 1.01（64%） | 1.28（78%） |
  | 同上 | >= +3 | 0.39（28%） | 0.54（36%） | 0.66（43%） | 0.83（50%） |
  | 穏やかな手も含む `[−2.5, target)` | >= +2 | 1.44（67%） | 1.98（75%） | 2.39（80%） | 3.00（83%） |
  | 同上 | >= +3 | 0.77（47%） | 1.08（59%） | 1.31（67%） | 1.67（78%） |

- 選ばれる手（必ずマイナス・>= +2）の典型: リード 7.3 から 8.4 目（四分位 5.9〜10.1）を払い、応じられたら −0.48
  （勝率 41%・最悪 30%）、引っかかれば +3.3。**モデル自身の見積もりで毎回 3〜4 目の期待値の損**。
  「罠が成功すれば払った分が戻る」手は 0.06〜0.33 回/局＝ほぼ存在しない。
- 資格のある手は hit 手番の約 7 割で 1 手だけ。プローブ前に罠を見分ける特徴（own_hp・visits・生 loss）は無く、
  発動回数はプローブ数にほぼ比例する。
- 9 路はログの代理集計でリード 8 目未満に大きい罠が 0%＝ほぼ発動しない見込み。19 路は未計測。

過去の類似案との違い: 2026-09-03「接戦の中盤で cap を 1〜2 目緩める」・2026-09-17「序盤の賭け罠の文字どおり版」は
どちらも在庫なしだった（大きい罠は勝勢の局面にしか現れない）。本案は**その勝勢の局面で予算の外まで払う**ので在庫がある。

## 3. 決定事項（ブレストの結論・2026-09-18 ユーザー承認）

1. 既定 OFF。OFF なら解析条件・採用判断とも従来とビット同一。
2. 発動は ヨセ前 × 勝勢時の消費モード（`cost_weight < 1`）の手番だけ。序盤の賭け罠（`cost_weight >= 1` の手番）とは排他。
3. 資格のある罠があれば net 比較を飛ばして打つ（賭け罠と同じ「資格つき先取り」）。無ければ従来の選択へ。
4. 「応じられた後のリード」の帯の上限をスライダーにする（必ずマイナス／−1 目未満／目標差未満＝穏やかな手も含む）。
5. 回数上限は付けない（応じられたら劣勢になって消費モードが切れる＝自然に止まる）。
6. 期待値の損は承知のうえ（演出用）。「引っかかれば現リードを維持」は資格にしない（在庫なし）。

## 4. 仕様

### 4.1 設定キー（接頭辞 `<prefix>` = enigma9 / enigma13 / enigma19 / 各 plus・計 24 キー）

| キー | 意味 | 候補値 | 既定 |
|---|---|---|---|
| `<prefix>_overdraft_deficit` | **最大ビハインド D（目）**。正しく応じられた後のリード（子局面プローブの検証値）が `−D` 以上の手だけ資格がある。0 = OFF | OFF/1/1.5/2/2.5/3/4/5 | **0（OFF）**・推奨 2.5 |
| `<prefix>_overdraft_answered_max` | **応じられた後のリードの上限（目）**。帯は `[−D, min(target, これ))`。0 = 必ずマイナスになる手だけ／−1 = 1 目以上の劣勢になる手だけ／MAX(99) = 目標差未満＝応じられても少しプラスで済む穏やかな手も含む | −1 / 0 / MAX | **0** |
| `<prefix>_overdraft_min_fooled_lead` | **引っかかった場合に残るリードの下限 W（目）**。`着手後リード + E_fooled >= W` | 1/2/3/5/8 | **2.0** |
| `<prefix>_overdraft_probes` | 追加プローブ数 k。発動回数はほぼこれに比例し、1 手あたりコールド約 +0.2 秒 | 4/6/8/12 | **6** |

既定値（ON にした場合）の 13 路の見込み: 0.8 回/局・55% の局で 1 回以上。

モジュール定数（スライダーにしない）:

- `ENIGMA9_OVERDRAFT_MAX_FIND = ENIGMA9_HP_BOOK`（0.25）: 十分な応手（損失 0.3 目以下）のうち最も見つけやすい手の
  humanPolicy がこれ以下＝「正しい応手が 9 段の本の手ではない」（賭け罠と同じ基準）
- `ENIGMA9_OVERDRAFT_CEILING_FACTOR = 1.5`: 1 手の損失の天井 = これ × `large_lead_max_loss`（13 路の既定 8 → 12 目）。
  リード +20 から 22 目捨てるような手を構造的に塞ぐ（実測の資格手 23 手中 21 手は 12 目以下）
- `ENIGMA9_OVERDRAFT_RAW_MARGIN = 1.5`: プローブ候補を選ぶ生 loss の帯の余裕（目）。生 loss は楽観側にも悲観側にも
  外れる（候補の 8 割が 1 visit）ので帯を両側へ広げる＝実測と同じ選び方

### 4.2 発動条件（全部 AND・純関数 `enigma9_overdraft_window`）

- `overdraft_deficit > 0`
- ヨセ sticky 前（その手番でヨセ入りした場合も不可）
- 消費モード（`enigma9_spending_plan` の `cost_weight < 1.0`＝余剰リード `lead − target > max_loss`）
- `over_cap = min(lead + D, ceiling) > cap`（`ceiling = max(cap, 1.5 × large_lead_max_loss)`）

返り値は `(over_cap, ceiling)` か None。序盤委譲・終局帯・`pool` が空・humanSL 不在などの早期 return は従来どおり先に効く。

### 4.3 資格と選択（純関数 `enigma9_overdraft_pick`）

対象は「検証済み損失が通常上限 cap を超えた」候補だけ（cap 以内の手は従来どおり `scored` で net 比較に参加する）。資格は全部 AND:

- `vloss <= ceiling`
- `−D <= lead_after < min(target, answered_max)`（`lead_after` は子局面 root の検証値・打つ側視点）
- `find <= ENIGMA9_OVERDRAFT_MAX_FIND`
- `lead_after + e_fooled >= min_fooled_lead`

`e_fooled` は新しい純関数 `enigma9_fooled_punish(replies, hp_of)` が返す「十分でない応手（損失 > `ENIGMA9_ADEQUATE_LOSS`）の
humanSL 9 段重みつき平均損失（1 応手 `ENIGMA9_PUNISH_CAP` 目で cap）」。同時に `p_fooled`（その hp 質量の割合）も返すが
資格には使わずログに出すだけ（find_hp < 0.2 帯のモデル値は過大＝予測 0.94 → 実現 0.60〜0.72）。

資格のある手が 1 手でもあれば、**net 比較・`net_margin`・局所性の同点帯・難解＋の ΔE 床・勝率フロアを通さず**、
`lead_after + E`（相手の応手分布で見た期待リード）最大の手を打つ（同点は `lead_after` 大）。無ければ従来の選択に
そのまま進む。境界は inclusive（`lead_after` の上端だけ exclusive）。

### 4.4 プローブ（純関数 `enigma9_overdraft_probe_picks`）

発動条件を満たす手番だけ、候補プール（`parity9_build_candidates`・visits >= 1）のうち

- 最善手・pass・通常の shortlist に入っている手を除き、
- 生 loss が `(cap − RAW_MARGIN, over_cap + RAW_MARGIN]` の手から、
- 信頼できる候補（visits >= `ENIGMA9_TRUSTED_VISITS`）を loss 昇順で等間隔に k 手（`_enigma9_spread_picks`）、
  足りなければ浅い候補を visits 多い順で埋める（`enigma9_shortlist_spread` の追加分と同じ規則）

を通常のプローブと同じバッチ（`_probe_children`）に足す。勝率フロアは見ない。先読み wave2 は同期しない（賭け罠と同じ既知のコスト）。

### 4.5 `_generate_move` への接続

1. 消費モードの計算の直後に `enigma9_overdraft_window` で窓を判定。
2. `shortlist` 確定後に `over_picks` を作り、`probe_items = [最善手] + shortlist + over_picks`。
3. スコアリングループで `vloss > cap` の候補は、窓が開いていて `vloss <= ceiling` なら破棄せず `over_scored` へ回す
   （勝率フロアは見ない。E・find・`e_fooled` を計算して `Over <gtp>: …` をログ）。shortlist 由来で上限超えだった手も同じ扱い。
   `over_picks` 由来で `vloss <= cap` に収まった手は通常どおり `scored` に入る（ON のときだけ増える候補＝賭け罠の spread と同じ）。
4. スコアリング後に `enigma9_overdraft_pick`。資格ありなら `_start_ponder` して着手。無ければ従来のフローへ。

### 4.6 他オプションとの関係

- 序盤の賭け罠: 消費モードの有無で排他（同じ手番で両方は発動しない）。
- `aim_jigo`: target = −1 になり帯は `[−D, min(−1, answered_max))`。D <= 1 なら帯が空＝発動しない。
- 局所性・難解＋の ΔE 床: 捨て身の罠には適用しない（E と find と `e_fooled` で資格を切っている＝rarity 単独の外しは入らない）。
- 応じられた後: 特別な処理はしない。劣勢では消費モードが切れ、勝率フロアが外しを止めるので実質最善手で打つ。
  相手の失着でリードが戻れば再び発動しうる。

### 4.7 ログ・表示

- `Overdraft: window lead=<L> cap=<cap> over_cap=<..> ceiling=<..> probes +<n> [(gtp, raw loss), ...]`
- `Over <gtp>: vloss=.. (raw ..) la=.. wr=.. E=.. Ef=.. p_fooled=.. find_hp=..`
- `Overdraft: qualifiers=[(gtp, la, fooled), ...]` ／ `Overdraft: played <gtp> (answered .., fooled .., vloss .., find_hp ..) instead of <best>`
- ai_thoughts: `<LABEL>: overdraft trap <gtp> (...)`

## 5. 却下した案

- **cap を `lead + D` まで広げて従来の net 比較に任せる**: 消費モードの `cost_weight` 割引と rarity 項の組合せで
  「珍しいだけの手に大損を払う」（親 spec 追記12 の失敗モード）を増幅し、本物の罠があっても打つ保証がない。
- **`target_score` を負にする／`aim_jigo` で代用**: 罠に限らず難解な手全般で削ってしまい、引っかかった後の勝勢も担保しない。
- **「引っかかれば現リードを維持」を資格にする**: 在庫 0.06〜0.33 回/局。
- **リードが小さい手番（消費モード外）でも発動**: リード 3.5 目以下は 126 手番で在庫 0＝プローブ時間だけ増える。
- **回数上限**: 自然に止まるので不要（§3-5）。
- **プローブ前の特徴で候補を絞る**: own_hp・visits・生 loss のどれも資格を予測しない。

## 6. 変更ファイル

- `katrain/core/ai.py`: 定数 3・純関数 4（`enigma9_fooled_punish` / `enigma9_overdraft_window` /
  `enigma9_overdraft_probe_picks` / `enigma9_overdraft_pick`）・`SETTING_DEFAULTS` 3 クラス・`_generate_move` の 4 箇所
- `katrain/core/constants.py`: `AI_OPTION_VALUES` / `AI_OPTION_ORDER` に 6 接頭辞 × 4 キー
- `katrain/config.json` と `~/.katrain/config.json`: 同 24 キー（既定値。ローカルはメインセッションで直接編集・KaTrain 停止中に）
- `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po`: ラベル 24×2・`aihelp:*` 6×2 → `python tools/compile_mo.py`
- `tests/test_ai_enigma_overdraft.py`（新規）
- `.claude/rules/ai-parameters.md` / `ai-strategies.md`・`docs/manual/src/06f_ai_enigma.html`（→ `tools/build_manual.py`）・`INDEX.md`

## 7. テストと検証

- 純関数: `enigma9_fooled_punish`（十分な応手だけ／混在／hp 質量 0）・窓（OFF・ヨセ・非消費モード・天井で潰れる場合）・
  プローブ選択（帯の境界・shortlist との重複除外・trusted 優先）・資格（帯の両端・find・W・ceiling の境界と順位づけ）
- 接続（`_probe_children` をスタブした `_generate_move`）: ON で上限超えの罠を打つ／OFF は従来の手でプローブも増えない／
  非消費モード・ヨセでは発動しない／資格なしなら従来の選択／難解＋が継承する／`aim_jigo` の帯
- 既存の不変条件テスト（SETTING_DEFAULTS ↔ GUI 候補値 ↔ パッケージ config ↔ i18n）が新キーを検査する
- 実局面: `calibration-data/enigma-overdraft/recon/` の `game_20260918_004112` d=50・`game_20260917_233314` d=41 を
  `katrain_debug --strategy enigma13plus --settings enigma13plus_overdraft_deficit=2.5 enigma13plus_overdraft_probes=12` で撃ち、
  `Overdraft:` 行と選択手を確認（E・hp・spread の標本は run 間で揺れるので 3 run）。OFF で従来の手に戻ることも確認

## 8. 既知の限界

- E・`e_fooled` は 1 手先の期待損失＝数手がかりの罠は測れない（親 spec の地平線）。
- 実測は 13 路のみ・静的な反実仮想（罠を打った後の局面変化は入っていない）。9 路はほぼ発動しない見込み、19 路は未計測。
- 相手が対局アプリの局面でしか測っていない＝「応じられた後に本当に負けるか」は未確認。
- 発動回数はプローブ数に比例＝時間とのトレードオフ（k=12 で対象手番に約 +2.4 秒）。先読みでは温まらない。
- 実戦校正は未実施。成功基準は「発動回数/局・応じられた割合・発動後の lead 推移（ログの lead 差分）・勝敗」を
  OFF の対局と並べて読むこと。
