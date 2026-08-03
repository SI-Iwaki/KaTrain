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

## 追記2（実測）: 発火経路の確認（Task 4a、2026-08-03）

段階3のウォッチャ（`_maybe_early_speculation`）は `Game.play()` の region 分岐からしか起動
しない。既存 E2E ハーネス `generate_move_e2e.py` の `analyse()` は `node.analyze()` を
**直接**呼んでおり `Game.play()` を一切通らないため、**既存ハーネスでは段階3は構造的に
一度も発火しない**（発火有無・効果のどちらも検証できない）。これを検証するため GUI と同じ
経路（`Game.play()` 経由）を再現する専用ハーネス
`docs/superpowers/specs/calibration-data/tsumego/early_speculation_e2e.py` を新設した。

### ハーネスの構造

1. `game.region_of_interest` / `region_analysis_visits`(1800) / `region_analysis_wide_root_noise`
   (0.04) を**最初の着手より前に**設定
2. `katrain.players_info` を「黒=AI（`player_type=PLAYER_AI`, `player_subtype=AI_TSUMEGO`）／
   白=人間（`PLAYER_HUMAN`）」に設定（`Player.strategy` は `ai` なら `player_subtype` を返す
   ため、この2値だけで `_maybe_early_speculation` の起動条件を満たす）
3. 目標 ply の直前までは `game.play(move, analyze=False)`（`DebugGame.play` の既定＝
   `BaseGame.play` 直呼び、`Game.play` の region 分岐を通らない）で高速に再生し、**直前の
   白の手だけ** `game.play(move, analyze=True)`（＝ `Game.play()` 経由）で打つ
4. `node.analysis["region_completed"]` を待ってから `STRATEGY_REGISTRY[AI_TSUMEGO]
   (game, settings).generate_move()` を呼ぶ
5. `KaTrainStub.log()` は `quiet=True` でも `self.logs` に全ログを積むため、`debug_level` に
   関係なく「前倒し投機」を含むログ行の有無で発火を判定できる

**ハーネス側で追加対応が必要だった2点**（本体コードは変更していない）:

- **`DebugGame.__init__` は `Game.__init__` をバイパスする**（`analyze_all_nodes` の自動起動
  スレッドを避けるため `BaseGame.__init__` を直接呼ぶ）。そのため `Game.__init__` が本来
  初期化する `region_analysis_visits` / `region_analysis_wide_root_noise` /
  `region_prefetch_replies` / `_region_prefetch_nodes` / `_early_speculation_nodes` が
  DebugGame インスタンスに一切存在せず、`Game.play(analyze=True)` が無条件に呼ぶ
  `_cancel_region_prefetch()` / `_cancel_early_speculation()` / `_maybe_region_prefetch()`
  で `AttributeError` になる。ハーネスの `build_game()` で `game.play()` を呼ぶ前にこれらを
  明示的に初期化して対処した（GUI の `Game` はコンストラクタで必ず初期化されるので本体側の
  バグではない）
- **エンジンのモデルロード費用を warmup で分離する**。`KataGoEngine` は初回クエリで
  TensorRT のモデルロードを行うため、warmup なしだと REPEATS の run1 が
  「モデルロード＋着手決定」の合算になり 36〜38 秒かかる（3ケース共通）。ウォッチャの
  `_early_speculation_worker` は固定 30 秒デッドラインを持つため、run1 はこの一度きりの
  ロード費用だけでデッドラインを超過し、閾値に届く前にウォッチャが自壊する（詳細は下表）。
  GUI 実戦ではキャプチャ時点で（起動直後の最初の1問を除き）既にエンジンが温まっているため、
  この「モデルロードを含む cold run1」は GUI の通常の1手を代表しない。判定対象と**別局面**
  （root）に低 visits の使い捨てクエリを撃って結果を破棄する `warmup_engine()` を repeats
  ループの前に追加し、以降は「エンジンは温かいが、この局面は未キャッシュ」という GUI の
  典型的な1手を測れるようにした（NN キャッシュは局面ごとに効くため、別局面での warmup は
  判定対象のキャッシュを汚染しない）。

### 構造的制約: ply0（キャプチャ直後の初手）には効かない

ウォッチャは `Game.play()` の region 分岐からしか起動しないため、**盤の初期状態
（キャプチャ直後、まだ誰も着手していない局面の黒番）には前倒し投機が構造的に発火しない**。
GUI で最初に `region_of_interest` が張られた直後の1手目は、この意味で温め機会が無い。
本ハーネスも ply0 を受け付けない（`ply must be even and >= 2` で弾く）。

### 発火実測

対象: M@4（`generate_move_e2e.py` の line 上 ply4）・O@2（ply2）・V2@2（ply2）。いずれも
「直前に白の手がある黒番」（`_maybe_early_speculation` が判定対象にする局面）。各ケース
3run・別プロセス（`--repeats` は使わずケースごとに新規プロセス起動、プロセス内では
REPEATS=3 で run1=cold position/run2-3=NN cache hit の構図を意図的に作って両方の非発火経路を
観測した）。

**構成A（warmup なし。run1 はモデルロード込み）**:

| ケース | run1 (cold, モデルロード込み) | run2 (NN cache hit) | run3 (NN cache hit) |
|---|---|---|---|
| V2@2 | analyse=38.01s, max_visits=1478, **NOT FIRED** | analyse=0.36s, max_visits=304, NOT FIRED | analyse=0.32s, max_visits=305, NOT FIRED |
| M@4 | analyse=36.34s, max_visits=679, **NOT FIRED** | analyse=0.46s, max_visits=306, NOT FIRED | analyse=0.15s, max_visits=306, NOT FIRED |
| O@2 | analyse=37.61s, max_visits=1431, **NOT FIRED** | analyse=0.52s, max_visits=304, NOT FIRED | analyse=0.20s, max_visits=306, NOT FIRED |

9/9 NOT FIRED。V2@2 と O@2 の run1 は `max_visits`（ハーネス側の独立ポーリングで観測した
`moves` visits 合計の最大値）が閾値 990v を上回っているにも関わらず発火していない —
`_early_speculation_worker` の `deadline = time.time() + 30.0` はスレッド起動時刻基準で、
モデルロードが数十秒かかる run1 では region クエリ自体が完了する頃には既に30秒を超過して
おり、ウォッチャは「閾値に届いたか」を確認する前に `time.time() > deadline` で自壊している
（`region_completed` が立つより先にタイムアウトする）。M@4 の run1 は `max_visits=679` で
そもそも閾値未到達（別の非発火要因）。run2/3 は NN キャッシュヒットで analyse が
0.15〜0.52秒と、`reportDuringSearchEvery`(=`REPORT_DT`=1秒) の最初の報告点にすら届く前に
クエリが完了しており、部分結果 (`moves`) が閾値に届く機会が構造的に無い。

**構成B（warmup あり。「エンジンは温かいが局面は未キャッシュ」という GUI の通常の1手を再現）**:

| ケース | run1 (engine warm / position cold) | run2 (NN cache hit) | run3 (NN cache hit) |
|---|---|---|---|
| V2@2 | analyse=2.07s, max_visits=708, NOT FIRED | analyse=0.41s, max_visits=306, NOT FIRED | analyse=0.31s, max_visits=306, NOT FIRED |
| M@4  | analyse=1.81s, max_visits=903, NOT FIRED | analyse=0.36s, max_visits=305, NOT FIRED | analyse=0.21s, max_visits=305, NOT FIRED |
| O@2  | analyse=2.32s, max_visits=1577, **FIRED** | analyse=0.36s, max_visits=305, NOT FIRED | analyse=0.41s, max_visits=305, NOT FIRED |

warmup 自体は 35.0〜35.6秒（3ケース共通・別局面なので判定対象のキャッシュを汚染しない）。
O@2 run1 で実際に発火を確認した:

```
run1 case=O@2 (white played C10): move=C13 analyse=2.32s generate=0.05s
max_visits_seen_during_wait=1577
speculation=FIRED moves=['C13', 'C13'] threshold=990v verify_visits=800
```

`C13` が2回現れるのは検証バッチ本体（`until_depth=None, wide_root_noise=None`）とコウ経路
検査（`until_depth=TSUMEGO_KO_REGION_UNTIL_DEPTH, wide_root_noise=0`）の両方の設定で同じ手を
温めているため（`tsumego_early_speculation_items` の重複排除キーは `(move, until_depth,
wide_root_noise)` の組で、同じ手でも設定が違えば別エントリとして残る＝設計どおり）。
`verify_visits=800` は `TSUMEGO_GAIN_VERIFY_VISITS` と一致。

構成Bでは 1/9 run が発火。V2@2 は run1 で `max_visits=708`（990v の 39%）、M@4 は
`max_visits=903`（50%）と、どちらも唯一の PARTIAL 報告点（`reportDuringSearchEvery=1秒`）で
閾値に届かなかった。O@2 だけ `max_visits=1577`（88%）と大きく上回って発火した。

### 結論

1. **既存 E2E ハーネスでは段階3は一切発火しない**（構造的。`node.analyze()` 直呼びが
   `Game.play()` の region 分岐を通らないため）。本タスクの新ハーネスは GUI と同じ
   `Game.play()` 経路を再現し、実際に発火することを O@2 で確認した＝機構自体は実装どおり
   到達可能で正しく動く（`_maybe_early_speculation` の起動条件・`_early_speculation_worker`
   のロジックにバグは見つからなかった）
2. **ply0（キャプチャ直後の初手）には構造的に効かない**（ウォッチャの起動点が
   `Game.play()` のみのため）。これは設計どおりの制約であり本体側のバグではない
3. **発火は現状かなり限定的**: 実測 9 run 中 1 run のみ発火。非発火の内訳は主に2種類の
   構造的レース: (a) NN キャッシュヒットで解析が 0.15〜0.52秒と `reportDuringSearchEvery`
   =1秒の最初の報告点より先に完了し、部分結果が届く前にクエリが終わる（6/9 run で観測）、
   (b) エンジンのモデルロードを含む真の cold run では `_early_speculation_worker` の固定
   30秒デッドラインをロード費用だけで超過しうる（構成A で観測。GUI の通常プレイでは
   起動直後の最初の1問を除き該当しない見込み）、(c) 唯一の PARTIAL 報告点での visits が
   閾値 990v（55%）にたまたま届かない（V2@2 39%・M@4 50%、構成B）。(c) は追記1の
   「PARTIAL は毎回1本だけ」という制約と合わせ、**その1本がどれだけ visits を稼げているかは
   局面ごとの探索速度に左右され、閾値をまたぐかどうかは position-dependent で保証がない**
   ことを示す実測。これは本体のバグではなく §3.1 で自認済みのリスク（「クエリ自体の想定
   所要時間との関係を重経路ケースでも確認すること」）が実際に顕在化した結果であり、
   閾値・報告間隔のチューニング余地として次段（Task 4b 等）に引き継ぐ
4. 判定: **BLOCKED ではない**（例外・AttributeError・ロジック矛盾は無く、機構は設計どおり
   動作して実際に発火も確認できた）。ただし発火率が低く体感できる高速化効果は限定的な
   可能性がある、という懸念は残る（DONE_WITH_CONCERNS）
