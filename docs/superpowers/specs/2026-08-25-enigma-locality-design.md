# 難解（13路・19路）の局所性オプション 設計

日付: 2026-08-25
対象: `ai:enigma13` / `ai:enigma19`（`Enigma9Strategy` のサブクラス。`_generate_move` は共有）
親 spec: `2026-08-10-enigma9-strategy-design.md`（追記2=13路・追記4=19路・追記6=ヨセの own_rare）

## 1. 症状（ユーザー報告）

13路・19路の難解戦略は「右上で打ち込んだのに次の手では左下、その次は左上」のように
着手が盤の各所へ飛び飛びになり、実際には手抜きではないのに相手からは手抜きの連発に
見える＝人間らしくない。9路では起きない。飛び飛びには「相手を罠にはめやすい」利点も
あるので、**現行の挙動は残したまま、調整版をオプションで追加する**。

## 2. 実測（`~/.katrain/logs/game_20260823_051702.log`・enigma13 白番・唯一の13路実戦ログ）

設定: max_loss 1.5 / large_lead 8.0 / min_wr 0.3 / margin 0 / target 1.5 / **aim_jigo ON** /
endgame 75 / unsettled 16。

- 自分の手番 50 手のうち **35 手で外し**（70%）。
- 外した手と KataGo 最善手のチェビシェフ距離: `{1:2, 2:5, 3:4, 4:5, 5:7, 6:8, 7:1, 10:1, 11:2}`
  ＝ **4 以上が 24/35（69%）・5 以上が 19/35**。最善手は目の前の戦いにあり、選んだ手は
  別の場所、が多数派。
- **序盤（最初の約8外し）は E が 0.01〜0.35 でほぼゼロ**。net を作っているのは own_rare
  だけ。例（初手）: 最善 D4（own_hp 0.450・E 0.00・net 0.07）に対し **K3（own_hp 0.015・
  E 0.06・find_hp 0.265→reply_rare 0・net 0.94）** を採用＝罠は無く「人間が打たない手だから」
  だけで別の隅へ飛んでいる。追記6 がヨセから外した「own_rare が順位をそのまま決める」
  構造が、13路では**序盤にも**起きている（9路は「遠く」が最大 8 路なので手抜きに見えな
  かっただけ）。
- 中盤は E 1〜6 の本物の罠で外しているが、それでも最善から 4〜6 離れた手が多い
  （例: 最善 L10 に対し G5 E=2.88 / J7 E=3.10 / G9 E=2.87 / K7 E=2.17）。

飛び飛びの源は2つ: **(1) 罠なし・意外さだけの外し（序盤）**、**(2) 遠くにある本物の罠
（中盤）**。ユーザーが残したい長所は (2) の性質。

## 3. 決定事項（ブレストの結論）

1. 序盤の「定跡外し」（意外さだけの外し）は**一定量残す**＝own_rare は切らない。
2. 残し方は**場所で残す**: 意外さは**戦いの近く**でだけ満額買い、遠いほど減衰させる
   （「定跡外し＝いまの局面の定石・手筋を外す手」。別の隅の意外なだけの手は消える）。
3. 中盤の遠い本物の罠は**同点帯タイブレーク**で扱う: 明確に優る遠い罠は残し、僅差なら
   近い罠を選ぶ（距離ペナルティを net 全体に掛ける案は校正コストが高いので採らない）。
4. 近さのアンカーは **相手の直前手 と KataGo 最善手 の2アンカー max**（Hunt の Focus と
   同形。平均は「どちらにも近くない幻影中心」になるので取らない）。自分の前手は第3
   アンカー候補として保留＝(a)+(b) で実測して「打ち込みの次の手」の症状が残るなら足す。
5. **enigma13/19 のオプション**（既定 OFF）として実装。新戦略にするとスライダー9本の複製
   になり既定値の保守が2倍になる。9路は対象外（問題なし、との報告）。

## 4. 設計

### 4.1 近さ `enigma9_locality(coords, anchors, stddev)`（純関数）

```
prox(m) = max_{a in anchors} exp(-|m - a|^2 / (2 σ^2))
```

- `coords` / `anchors` は盤座標 `(x, y)`。距離はユークリッド（Hunt の proximity と同じ
  `min_dist_sq` 形）。
- `anchors` が空、または `stddev <= 0` なら **1.0**（＝局所性なし）。
- σ=3 の目安: d=3 → 0.61、d=6 → 0.14、d=9 → 0.01。σ=5（19路）: d=5 → 0.61、d=10 → 0.14。

アンカーの組み立て（`_generate_move` 内・クエリ0本）:
- 相手の直前手 `self.cn.move.coords`（None / pass なら省く）
- KataGo 最善手 `Move.from_gtp(best_gtp).coords`（常に入る。pass が最善なら省く）

### 4.2 own_rare の局所化

```
net = E + w_reply·reply_rare + w_own·prox(m)·own_rare − cost_weight·max(0, loss)
```

`enigma9_net_score` に引数 `locality=1.0` を足し、`w_own * locality * rarity(own_hp)` にする。
最善手はアンカー自身なので prox=1（従来どおりの own_rare が付く）。ヨセは追記6 の
`w_own=0` がそのまま効く（局所性と直交）。**σ=0 のとき prox は全候補 1.0 に解決し、式は
従来とビット同一**。

### 4.3 同点帯タイブレーク `enigma9_choose_local(scored, best_gtp, margin, slack)`（純関数）

1. 挑戦者（最善手以外）の net 最大 `top` を取る（従来と同じキー `(net, -loss)`）。
2. 帯 `band = {c | c.net >= top.net − slack}`。
3. `pick = max(band, key=(prox, net, -loss))`＝**最もアンカーに近い手**。
4. **`pick.net >= best.net + margin` のときだけ外す**（帯の最大 net では代理しない＝打つ手
   そのものが最善手に勝っていること）。満たさなければ None＝最善手。

`slack <= 0` または `stddev <= 0` のときは従来の `enigma9_choose` をそのまま呼ぶ
（**OFF は採用判断・解析条件ともビット同一**。slack=0 でも「net が完全同値の挑戦者」が
あれば prox で並べ替わりうるので、分岐で明示的に従来関数へ倒す）。

### 4.4 変わらないもの

プール・shortlist・子局面プローブ（本数・visits・条件）・検証 cap・勝率フロア・消費モード
（cost_weight）・ヨセ予算・aim_jigo・ponder・フェイルセーフ。増えるのは座標計算だけなので
着手時間は不変。

### 4.5 ログ

- `Score` 行に `prox=0.xx` を追加。
- 局所性が有効な手番で `Locality: anchors=[last(X), best(Y)] stddev=σ slack=s`、選択時に
  `Band: n candidates within slack → nearest Z (prox p, net n)`。
- `Deviate` 行は従来どおり（`prox` を1項追加）。

## 5. 設定

| キー | 候補値 | 既定 | 意味 |
|---|---|---|---|
| `enigma9_locality_stddev` | 0 / 1.5 / 2 / 2.5 / 3 | **0**（OFF） | 9路（既定 OFF・不変条件維持のため露出） |
| `enigma9_locality_slack` | 0 / 0.2 / 0.3 / 0.5 / 1.0 | 0.3 | 同上 |
| `enigma13_locality_stddev` | 0 / 2 / 2.5 / 3 / 4 / 5 | **0**（OFF） | 近さの σ。0 で現行とビット同一 |
| `enigma13_locality_slack` | 0 / 0.2 / 0.3 / 0.5 / 1.0 | 0.3 | 同点帯の幅（目相当）。stddev>0 のときだけ効く |
| `enigma19_locality_stddev` | 0 / 3 / 4 / 5 / 6 / 7 | **0**（OFF） | 同上（Hunt の focus_stddev 13路 5.0 / 19路 7.0 の約半分を初期目安に） |
| `enigma19_locality_slack` | 0 / 0.2 / 0.3 / 0.5 / 1.0 | 0.3 | 同上 |

- **9路にも同じ2キーを既定 OFF で出す**（`enigma9_locality_stddev` 候補 0/1.5/2/2.5/3・
  `enigma9_locality_slack` 同）。当初案は「9路には出さない」だったが、既存テスト
  `TestGuiConfigConsistency`（`tests/test_ai_enigma9.py`）が **SETTING_DEFAULTS のキー集合 ＝
  パッケージ config.json ＝ `AI_OPTION_VALUES`/`AI_OPTION_ORDER`** を3クラスすべてに要求し、
  `test_same_setting_suffixes` が3クラスのキー集合一致を要求している（「片方にだけ設定を
  足すと GUI と SETTING_DEFAULTS がずれる」）ため、この不変条件を壊さない側に倒した
  （実装時の裁定 2026-08-25）。9路は既定 OFF なので挙動は不変。
- GUI 表示には **パッケージ `katrain/config.json` とユーザー `~/.katrain/config.json` の
  両方**へキー追加が要る（ユーザー側はメインセッションで直接 Edit・KaTrain 終了を確認して
  から）。

## 6. 変更ファイル

- `katrain/core/ai.py`: `enigma9_locality` / `enigma9_choose_local`（純関数）、
  `enigma9_net_score(..., locality=1.0)`、`Enigma9Strategy._generate_move` のアンカー組立・
  スコア・選択分岐・ログ、`Enigma13Strategy` / `Enigma19Strategy` / `Enigma9Strategy` の
  `SETTING_DEFAULTS`。
- `katrain/core/constants.py`: `AI_OPTION_VALUES` / `AI_OPTION_ORDER` に6キー（9/13/19路 × 2）。
- `katrain/config.json` / `C:\Users\iwaki\.katrain\config.json`: `ai:enigma9` / `ai:enigma13` /
  `ai:enigma19` に各2キー。
- `katrain/i18n/locales/{en,jp}/LC_MESSAGES/katrain.po`: 短ラベル6本＋`aihelp:enigma9` /
  `aihelp:enigma13` / `aihelp:enigma19` 本文に動作説明 → `python tools/compile_mo.py`。
- `.claude/rules/ai-parameters.md`（Enigma13/19 の表に2行ずつ）・`.claude/rules/ai-strategies.md`
  （難解の段落に1文）・`docs/superpowers/specs/INDEX.md`（本 spec の行）・親 spec に追記8
  として本ファイルへのポインタ。
- `tests/test_ai_enigma9.py`: 純関数の単体テスト。
- `docs/superpowers/specs/calibration-data/enigma9/`: 13路実戦の復元 SGF と結果 md。

## 7. 検証

1. **単体**: `enigma9_locality`（アンカー無し・σ=0 → 1.0、1アンカー・2アンカー max、pass
   の除外）、`enigma9_net_score(locality=…)`（σ=0 相当 locality=1.0 で従来値と同値）、
   `enigma9_choose_local`（slack=0/σ=0 で `enigma9_choose` と同一の返り値、帯内は prox 優先、
   pick 自身が margin を満たさなければ None、最善手が唯一なら None）。
2. **13路実局面**: `game_20260823_051702.log` のクエリ JSON（`"moves": [...]`）から 13路 SGF
   を復元（AI=白＝depth 奇数。`calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf`）
   し、当時の設定（`--settings enigma13_aim_jigo=true enigma13_target_score=1.5`）で
   `python -m katrain_debug --sgf … --strategy enigma13 --batch --player W` を
   **OFF / σ=3 / σ=4（slack 0.3）で各3run**。指標:
   - (a) 外した手の「相手の直前手」「KataGo 最善手」からのチェビシェフ距離分布
   - (b) 外し率（`ai_top_move` の補数）
   - (c) `mean_ptloss`・実損失合計（**損失を過小評価する壊れ方は一致率だけでは見えない**）
   - (d) 外した手の E 分布（遠い本物の罠を失っていないか＝E≥1 の外しが何本残るか）
   - OFF アームは HEAD と同一コードパスであることを単体テスト（σ=0 の同値性）で担保した上で
     走らせる。run 間ノイズは既知（ai_top_move ±0.03 / mean_ptloss ±0.05）。
3. **19路**: 実戦ログが無いので `tests/data/ogs.sgf` 等で OFF / σ=5 の同バッチを回し、距離
   分布と損失の**方向**だけ確認。19路の校正は実戦待ち（rules に「未校正」と明記）。
4. **既存回帰**: `pytest tests/test_ai_enigma9.py` と `tests`（`test_ai.py` 除く）。

**期待する結果**: 序盤の own_rare 単独外し（K3 型）は近傍の意外な手に置き換わるか最善手に
戻る。中盤の E≥1 の罠は帯の外なら残る。損失は不変〜微減。

**採用判断**: 「改修の効果を以前失敗していたケースだけで測らない」（CLAUDE.md）に従い、
距離分布の改善だけでなく (c)(d) の破損側も並べて判断する。σ の既定は OFF のまま＝校正値は
rules の表に「推奨値」として書き、既定値は変えない。

## 8. 却下・保留した案

- **距離ペナルティを net 全体に掛ける**（net −= w·(1−prox)）: 連続的に効くが重みと σ の2軸
  校正が要り、13/19 で別々。同点帯タイブレークなら slack 1軸で「明確に優る遠い罠は残す」
  が構造的に保証される。
- **own_rare の重みを一律に下げる／罠なし外しを N 手に1回に絞る**（量で残す）: 飛びの頻度が
  減るだけで「別の隅へ飛ぶ」こと自体は残る。
- **プールの半径ゲート**（最善手から R 以内だけ admissible）: 遠い本物の罠を全部捨てる＝
  長所を失う。
- **own_rare を E に条件づける**（E < 閾値なら w_own=0）: 序盤の定跡外しを丸ごと失う（残す、が
  ユーザー決定）。
- **第3アンカー＝自分の前手**: 保留。(a)+(b) の実測で「打ち込みの次の手が別の場所」が残る
  なら追加する。
- **新戦略 `ai:enigma13_local`**: スライダー複製と既定値の二重保守。
