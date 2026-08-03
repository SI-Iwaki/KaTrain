# 詰碁・段階3: root 部分結果からの前倒し投機（検証バッチ本体の温め）設計

日付: 2026-08-03
親スペック: `2026-08-03-tsumego-latency-overlap-design.md`（§6 で「段階1+2の計測後に判断」とした段階3の独立起票。前提数値・用語は親スペックと追記1・2を参照）
対象: `katrain/core/ai.py`（TsumegoOwnershipStrategy のみ）

## 1. 背景と残った問題

段階1+2（手番内投機）で generate 中央値 2.55→2.0秒・温めヒット時の実クエリ 0.0〜0.2秒を達成
したが、**コールド1手目の合計（root待ち＋着手決定）は重経路4点で 4.6〜7.7秒と目標 3〜3.5秒に
未達**（親スペック追記2）。残りの内訳:

1. **root 待ち 1.4〜2.0秒** — 校正済み 1800visits の床。縮められない
2. **検証バッチ本体のコールド 1.5〜1.8秒** — 段階1+2 は救済・コウ検査だけを温めており、
   score_best 検証バッチ（incumbent＋挑戦者、最大4本×800v）は温めていない
3. **温めの発火が root 完了後** — 段階1+2 の温めは実クエリ（検証バッチ）と同時スタートに
   なるため、初回手番では並走による部分短縮しか得られない（救済・コウ検査など
   「検証バッチより後の段」でだけフルヒットする）

段階3はこの (2)(3) を突く: **root 解析の部分結果から温め集合を前倒しで計算・発行**し、
検証バッチ実クエリが走る頃には子局面が温まっている状態を作る。

## 2. 目標 / 非目標

**目標**: 重経路ケースのコールド1手目合計を 3〜3.5秒級へ（root 待ち ≈1.4〜2.0秒＋
着手決定 ≈1.0〜1.5秒）。E2E フル回帰の正答不変が必須ゲート（親と同じ）。

**非目標**:
- 実クエリ・判定ロジック・visits の変更（親スペックの絶対制約を引き継ぐ）
- root 待ちそのものの短縮
- アイドル先読み（ponder_replies）の改善

## 3. 設計

### 3.1 発火タイミングと場所（2026-08-03 プラン作成時に訂正）

**発火は Game 側のウォッチャスレッドで行う**。当初案の「戦略の待ちループ差し替え」は
実装棚卸しで不成立と判明した: 戦略の `wait_for_analysis`（`ai.py` の
`while not self.cn.analysis_complete`）は実質 no-op で、**root 待ちは戦略の外にある** —
GUI はノードの解析完了を見てから generate を呼び、CLI ハーネス（`generate_move_e2e.py`）も
`analyse()` が region 完了までブロックしてから generate を呼ぶ。戦略内のフックでは
前倒しにならない。

そこで `Game.play()` の region 分岐が新ノードの解析を発行した直後、**次番が AI
（strategy が `ai:tsumego`）** ならウォッチャスレッドを起動する（`_maybe_region_prefetch`
の鏡像＝あちらは次番が人間のとき）。部分結果は region クエリの callback が
`GameNode.set_analysis(partial_result=True)` で `node.analysis` に反映済み
（`moves`（per-move ownership 込み）と `ownership` は部分でも更新される。`root` は
fast クエリ由来で約0.3秒で揃う＝`candidate_moves` の pointsLost 計算は成立する）。
ウォッチャは 50ms 間隔で `node.analysis["moves"]` の visits 合計を確認し、
**visits 合計 ≥ `TSUMEGO_EARLY_SPECULATION_ROOT_FRACTION`(0.55) × region_analysis_visits**
（1800v なら約990v）に一度だけ達したところで温め集合を計算・発行する。
region 完了・ノード切替・リージョン解除・期限（30秒）で発火せず終了する。

**訂正（2026-08-03、追記1の実測を根拠）**: 当初案の 0.67（≈1200v）は、追記1実測（PARTIAL は
毎回1本のみ・visits 1160〜1182）だと2run とも僅かに届かず構造的に発火しない。0.55（≈990v）
なら1本目の PARTIAL で確実に発火するため、この値に変更した。

### 3.2 前倒しで温める集合

部分結果のスナップショット（candidate_moves・ownership）に対して**既存の純関数をそのまま**
適用し、仮の選択手を計算する:

1. `select_tsumego_move` → 仮 chosen、`tsumego_score_best` → 仮 score_best
2. `tsumego_score_best_challengers` → 仮挑戦者列（検証バッチ本体の集合）
3. `tsumego_speculation_plan` → 段階1+2 の温め集合（救済スーパーセット＋コウ検査）

温め集合 = **(2) の検証バッチ本体（incumbent＋挑戦者＋仮 chosen、untilDepth=1・wRN=0.04・
ownership=True＝実検証と同一条件）** ＋ (3)。発行は Game 側に `_maybe_region_prefetch` /
`_region_prefetch_worker` / `_cancel_region_prefetch` と同型の3点セット
（`_maybe_early_speculation` / `_early_speculation_worker` / `_cancel_early_speculation`）を
設け、使い捨て sim（`_region_prefetch_sim` を再利用）＋優先度 `PRIORITY_TSUMEGO_SPECULATION`
(500) で撃つ。掃除は次の `Game.play()` 冒頭（prefetch と同じ位置）。戦略設定は
`katrain.config("ai/ai:tsumego")` から読み、仮選択の計算は ai.py の既存純関数を
**ウォッチャ内の遅延 import** で使う（game→ai のモジュール循環を避けるため）。
温め集合の組み立て自体は ai.py 側の新純関数 `tsumego_early_speculation_items` に置き、
単体テスト可能にする。

最終 1800visits で候補セットがずれた分は従来どおりミス（捨てるだけ）。root 完了後の
既存発火点（段階1+2）はそのまま残す＝前倒しでヒット済みならエンジン側で即返るだけ。

### 3.3 判定の不変性

判定は従来どおり**最終 1800visits の root の値のみ**を使う。部分結果は温め集合の計算に
しか使わない（読み取り専用・純関数）。仮 chosen がどうであれ、実クエリの内容・発行順・
待ち合わせ・タイブレークは1バイトも変わらない。

## 4. 実装上の検証点（実装時に最初に確認）

1. **部分結果の payload に ownership / movesOwnership が含まれるか**。含まれない場合、
   `select_tsumego_move` / gain 系純関数は部分結果に適用できない。fallback: 温め集合を
   「目数順上位＋visits 上位」の簡易プロキシで採る（ミス率が上がるだけで安全性は同じ）。
   切り分けは実ログの partial payload を1本ダンプすれば足りる
2. **ウォッチャがスレッド・クエリをリークしないか**（期限30秒・`current_node` 切替 /
   リージョン解除 / `region_completed` での bail、`play()` 冒頭での terminate。
   §3.1 の訂正により「戦略の待ちセマンティクス保存」の論点は消滅＝戦略コードは触らない）
3. **GPU 競合**: 実効 `numAnalysisThreads=12`（親スペック追記2）なのでスロット枯渇は
   ないが、root 探索末期と温め4〜8本が GPU 計算を分け合う。**root ウォールの非劣化
   （+0.3秒以内）を採用ゲート**にする（発火閾値 0.55 で競合窓は約1秒）

## 5. 検証・成功基準

- E2E フル回帰（`e2e_suite.py --full`）正答不変（必須ゲート）。K@0 等ナイフエッジ帯の
  裁定方法論は親スペック追記1〜2（A/B は worktree＋`PYTHONPATH` 明示）を再利用
- 時間計測: 重経路4点（M@4 / O@0 / V2@0 / V2@2）を**別プロセス3run**、コールド run1 の
  「root待ち＋着手決定」合計で before/after。root ウォール非劣化の確認を含む
- 成功基準: コールド1手目合計 3〜3.5秒級（V2@0 のような最重ケースは 4秒台まで許容）

## 6. リスクと対策

| リスク | 対策 |
|---|---|
| 部分結果に ownership が無く仮選択が計算できない | §4-1 の簡易プロキシ fallback（安全性は不変） |
| root 探索末期の GPU 競合で root が遅くなる | 発火閾値 0.55＋root ウォール非劣化を採用ゲートに |
| 部分結果と最終結果で候補セットがずれ温めが外れる | ミスは捨てるだけ（従来コールドと同じ）。ヒット率は計測で報告 |
| 待ちループ差し替えで待ちセマンティクスが変わる | §4-2 を実装プランの最初のタスクにし、既存挙動の単体テストを先に固定する |

## 追記1（実測）: 部分結果の payload

§4-1 の検証点をプローブで実測（`docs/superpowers/specs/calibration-data/tsumego/partial_payload_probe.py`）。
`generate_move_e2e.py` の局面構築（KaTrainStub＋engine起動）を流用し、region 解析クエリを
`engine.request_analysis` で直接発行して callback だけ差し替え（`node.analyze` は callback を
`self.set_analysis` に固定しているため）。本番条件どおり visits=1800・ownership=True・
`extra_settings=region_analysis_extra_settings(1800, 0.04)`・`region_of_interest`・
`report_every=1`（`reportDuringSearchEvery=1`）。対象はケース V
（`case-v-declass-no-kill-20260731.sgf`、region `4,12,4,12`、0手目＝初期局面）。

実測（別プロセス2run、フォアグラウンド）:

```
run1:
PARTIAL visits=1182 n_moves=47 has_root_ownership=True first_move_has_ownership=True
FINAL   visits=1806 n_moves=47 has_root_ownership=True first_move_has_ownership=True
summary: PARTIAL=1 FINAL_SEEN=True

run2:
PARTIAL visits=1160 n_moves=31 has_root_ownership=True first_move_has_ownership=True
FINAL   visits=1807 n_moves=47 has_root_ownership=True first_move_has_ownership=True
summary: PARTIAL=1 FINAL_SEEN=True
```

**結論: (a) 純関数がそのまま使える**。2 run とも `has_root_ownership=True` /
`first_move_has_ownership=True` で、root ownership と per-move ownership の両方が
部分結果（`isDuringSearch=True`）に既に乗っている。§3.2 の「既存の純関数をそのまま適用」
という前提は成立し、Task 2 の簡易プロキシ差し替え（目数順上位＋visits上位の和集合）は不要。

ただし2点、当初想定とのズレを記録する:

- **PARTIAL は毎回1本だけ**（brief の期待「2本以上」を満たさず）。ケース V の region クエリは
  1800visits が約1.2〜1.5秒で完了するため、`reportDuringSearchEvery=1`（1秒間隔）の窓が
  1回しか開かない。§3.1 の発火閾値（visits合計 ≥ 0.67×1800≈1200）は run1 の PARTIAL
  （visits=1182）だと僅かに届かず、run2（visits=1160）はさらに届かない＝**ケース V だけで見ると
  唯一の PARTIAL が発火直前で終わるケースが有り得る**。より重い（探索が長引く）ケースでは
  複数 PARTIAL が届く可能性が高いが、軽いケースでは前倒しの実効窓がほぼ無いことを示す実測。
  実装時は発火閾値と「クエリ自体の想定所要時間」の関係を重経路ケース（M/O/V2 等）でも確認すること
- **`n_moves`（moveInfos の候補数）が PARTIAL と FINAL で異なる**（run1: 47→47 で一致、
  run2: 31→47 で PARTIAL のほうが少ない）。前倒し温め集合の計算対象（gain/score_best 系）は
  「その時点で探索された候補」に限られるため、最終候補セットとのズレは§3.2の「最終
  1800visits で候補セットがずれた分は従来どおりミス」の想定どおりの挙動として扱ってよい
