# 自己対局ハーネス katrain_debug.selfplay 設計

日付: 2026-09-23
対象: `katrain_debug/selfplay.py`（新規）・`katrain_debug/selfplay_stats.py`（新規・純関数）
状態: 設計（未実装）。最初の用途は韜晦（spec `2026-09-23-veil-strategy-design.md`）の校正と A/B

## 0. 目的

戦略を**人間を模したボット**と無人で N 局打たせ、**両者の終局レポートの一致率**・勝敗・最終目差を
集計する。既存の `--batch`（batch_eval.py）は固定 SGF の再生なので、リードの軌跡・相手の反応・
勝敗・相手の一致率が測れない＝リード連動の戦略（難解・擬態・韜晦）の評価に使えない。

## 1. 要件

1. 一致率は **KaTrain の終局レポートと完全に同じ数字**（本物の `game_report` を呼ぶ・再実装しない）。
2. 戦略は GUI と同じ経路で動かす（本物の `Game`・`Game.play` の通常解析・`generate_ai_move` と同じ手順）。
3. 相手ボットは実戦の相手（囲碁クエストの 13路）の統計に校正できる。
4. A/B は seed で開始条件を対にし、統計的に比べられる。null 実験（両アームが同じ設定）を検出して止める。
5. 途中で落ちても再開できる。実戦中の KaTrain とは同時に走らせない。

## 2. 構成

**プロセスとエンジン**
- `python -m katrain_debug.selfplay <subcommand>`。先頭で `os.environ["KIVY_NO_ARGS"]="1"`。
- `KaTrainStub(~/.katrain/config.json)`（katrain_debug/katrain_stub.py:20-50）を1つ、`KataGoEngine` を1本起動して全局で共有
  （起動 6.4〜7.9秒）。
- 両プレイヤーは stub 上 PLAYER_HUMAN のまま＝難解系の ponder は発火しない（`_ponder_applies` ai.py:3138-3158）。
  `game.board_watch_active` は既定 False（`--watch-flags` で True にして監視専用の分岐も通せる）。
- 待ちループはすべて `engine.check_alive()` を見る。エンジンが落ちたら再起動し、その局を `aborted` にして続行。

**対局**
- 毎局、本物の `Game(stub, engine, game_properties={"SZ", "KM", "RU"})` を作る。`DebugGame`（runner.py:82-113）は
  `Game.__init__` を飛ばし `play` に `expected_node` も無いので使わない。
- 戦略の sticky 状態（`game._veil_state` 等）は Game に載るので、局ごとに自動でリセットされる。

**AI の手番**
1. 経路上の全ノードの解析完了を待つ（実戦では相手の考慮時間の間に完了している＝戦略が見るデータを実戦と揃える）。
2. 相手の投了判定（§3）。
3. `generate_ai_move`（ai.py:11678-11704）と同じ手順を行ごとに写した `_ai_turn()`:
   `STRATEGY_REGISTRY.get(mode)` → `cls(game, settings)` → `generate_move()`（`AnalysisDiscardedException` を捕捉）→
   `game.play(move, expected_node=strategy.cn)` → `ai_thoughts` を付ける。写す理由は戦略オブジェクトを手元に残して
   判定情報を読むため（batch_eval.py:160 と同じ）。**テストで `generate_ai_move` との一致を固定する**。
4. 戦略の所要時間（解析待ちを除く）と判定情報を記録する。判定情報は `getattr(strategy, "last_decision_info", None)` で読む。
   これを持つのは持碁系と韜晦だけ（難解・擬態には無い）ので、無い戦略では判定情報の列を空にし、判定情報に依存する指標
   （段の数・外しの種類・意図とレポートの食い違い）は韜晦のアームでだけ出す。

**相手の手番**: `HumanSLOpponent.select(game)`（§3）で1手選び `game.play()`。新しいノードの通常解析は
`Game.play` が自動で始める（次の AI 親局面の解析と重なる＝実戦と同じ）。

**終局**: 相手の投了、2連続パス、手数上限（9路 120・13路 250・19路 400。上限では最終 scoreLead で勝敗）、
AI の例外（`aborted`）。AI は投了しない。

**集計**
- 全ノードの解析完了を待ってから（1〜3秒）、本物の `game_report(game, thresholds, depth_filter=f)`（ai.py:345-407）を
  両色ぶん呼ぶ。f は次の2組:
  - GUI のタブと同じ None / (0, 0.14) / (0.14, 0.4) / (0.4, 10)（popups.kv:1230-1248。13路の区切りは 24 / 68 手）。
  - 校正用の区間（実戦の校正目標と同じ区切り）: 手数 <24 / 24〜84 / >=85 ＝ 13路で (0, 24/169) / (24/169, 85/169) /
    (85/169, 10)。9・19路は盤面積で比例させる。
- 木は2通り: **WATCH（主指標）**＝末尾のパスノードを除いたもの（監視モードはパスを扱わないので実戦の木は最後の石で終わる）。
  **STRICT**＝全体。`game_report` は `game.current_node` から `nodes_from_root`（親をたどる）で集め、その後 `children[0]` を
  たどる（ai.py:346-350）ので、WATCH は `watch_prune`（コンテキストマネージャ）が `game._lock` の下で
  (1) 最後の石のノードの children を一時的に外し、(2) `game.current_node` を属性の直接代入でそのノードへ付け替えて
  （`set_current_node` は使わない＝`_calculate_groups` を走らせない）計算し、finally で children と current_node の両方を戻す。
- SGF は `Game.write_sgf(path, trainer_config)`（game.py:429-451。`trainer_config["eval_thresholds"]` が必須・
  `save_analysis` を真にする）で KT 解析つきで保存する（KT は `analysis_complete` のノードにだけ書かれる＝
  game_node.py:125-139）。GUI で開けば同じレポートが出ることを1回手で確かめる。

**レポートの定義（呼ぶだけで再実装しない）**: 一致＝`parent.analysis_complete` かつ
`parent.candidate_moves[0]["move"] == move.gtp()`。分母はそのプレイヤーの `points_lost` が None でないノード。
パスも数える。相手は切り揃えない（切り揃えるのは `parity9_match_tally` だけ）。
戦略は `wait_for_analysis` 後にレポートが後で読むのと同じ解析を見る（子の書き戻しは order を変えない）。
「外した手」はすべてレポート基準（`move != parent.candidate_moves[0]["move"]`）で数える。

## 3. 相手ボット（`HumanSLOpponent`・ハーネス内のクラス・戦略登録はしない）

- 毎手、humanSL を 1visit で1本（約 0.03秒。`request_analysis(visits=1, include_policy=True, ownership=False,
  extra_settings={"humanSLProfile": profile, "ignorePreRootHistory": False})`＝visits は引数で渡す）。
- 局ごとに seed を固定した `random.Random` で hp^(1/τ) に比例してサンプル。非合法手（コウ・自殺手）は捨てて引き直す。
- **パス**: サンプルでパスが出たら、現局面（`game.current_node`）の通常解析の完了を待ち、`candidate_moves` のパスの
  pointsLost を pass_loss として `_area_scoring_should_pass(moves, pass_loss)`（ai.py:786。humanPolicy がパスを最上位に
  置いているかも中で見る）に渡す。真ならパス。偽、またはパスが候補に無い（pass_loss が None）なら、パスを外して引き直す
  （中国ルールでダメを詰めてから両者パスで終わる）。
- 任意の `max_loss`（既定 OFF）: 通常解析からの悪手フィルタ（強め・慎重な相手の層）。使うときは毎手、現局面の通常解析の
  完了を待つ。
- `ai:human`（HumanStyle）を相手にしない理由: 悪手フィルタ（13路 2.8 / 5.6目）で ≥5目の失着の尾（実戦 10%）を再現できず、
  1手 +1.5秒かかる。`--opponent strategy:human` で「強い・フィルタつき」の層としてだけ使える。

**校正目標**（13路の実戦・事後 2500v。区間は手数 <24 / 24〜84 / >=85）

| 対象 | 局平均 | 全手まとめ |
|---|---|---|
| 相手の一致率（難解＋16局＝校正の主目標） | 23.1%（局間 SD 6.5pt） | 23.2% |
| 相手の一致率（18局） | 22.2%（SD 6.8pt） | 21.8% |
| 相手の損失/手（18局） | 1.77目 | 1.74目（中央値 0.58・≥2目 28%・≥5目 10%） |
| 相手の区間別（18局・まとめ） | — | 序盤 26.7% / 0.56目・中盤 18.2% / 2.43目・終盤 29.1% / 0.96目 |
| AI 側の一致率（難解＋16局） | 53.3% | 54.2% |
| 手数 | 中央値 78.5（31〜128） | — |

ハーネスの主指標は局単位なので、**校正は局平均に合わせる**（相手 23.1%・SD 6.5pt）。校正の戦略は難解＋なので、
AI 側の比較も難解＋16局の値を使う（擬態2局を混ぜない）。

**校正手順（`calibrate`）**
1. 難解＋13路（ユーザーのローカル設定）を rank_8k / 5k / 3k / 1k / 1d / 3d と各8局（色は交互）。
2. 段位ごとに一致率・損失・校正用区間の形・≥2 / ≥5 の割合を出す。
3. 局平均の相手一致率（23.1%）と局間 SD（6.5pt）、平均損失に合うように、弱・中・強の3点プールを選ぶ。
4. 区間の形が合わないときだけ温度 τ（0.8〜1.2）を調整する。
5. プールに対する AI 側の一致率と、実戦の難解＋の局平均 53.3% との差を「ハーネスと実戦のずれ」として記録し、実戦の予測に使う。
6. 結果を `docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json` に保存。

段位ラベルはつまみにすぎない（humanSL は主に19路のデータで、囲碁クエストの段級とは対応しない）。
設計時の試作（n=1）: 擬態 vs rank_3k で相手 22.5% / 1.71目、難解＋ vs rank_1d で 24.2% / 1.74目＝rank_3k〜1d が実戦の平均を挟む。

**投了モデル**: 局ごとに、実戦の投了局の最終リードからブートストラップで閾値 R を引く（`--resign-lead lo:hi` で指定も可）。
判定の開始手数（13路 40・9路 19・19路 85＝13路の 40 を盤面積で比例）以降に、AI 視点で lead >= R かつ AI 勝率 >= 0.95 が
AI の2手番続いたら相手が投了する。投了がヨセの手数（＝一致率）を左右するので、**`--no-resign` を必須の感度アームにする**。

**9路**: 相手の一致率の実測が無いので、先に保持中の難解＋9路ログ17局を SGF に戻して事後解析し、目標を作ってから同じ手順で校正する。
**19路**: 13路のプールを流用し、数局のスモークだけ。

**seed**: 局ごとの seed で AI の色（交互）・相手の段位（層別に同数）・相手の乱数列・投了閾値・戦略側の Python 乱数を固定する。
KataGo の探索は非決定的なので数手で分岐する＝seed は「開始条件の対」を作るだけで、再現ではない。

## 4. hp 監査（`--hp-audit rank_9d`）

戦略に依存しない人間らしさの計器。AI の全着手の親局面に humanSL（既定 rank_9d）を 1visit で1本撃ち、選んだ手と
最善手の hp・hp の順位を記録する。結果はノードに書き戻さない（`_run_query` と同じくコールバックで受ける）。
所要時間の集計からは除く。韜晦の採否基準「外した手の 9段 hp の中央値 >= 5%」は、この監査の値で全アーム共通に測る。

## 5. 出力（`experiments/selfplay/<YYYYMMDD_HHMM>_<label>/`・gitignore 済み）

- `run.json`: 各アームの解決済み設定（ユーザー config + 上書き）とハッシュ・戦略クラス、エンジン設定、
  `katrain.core.ai.__file__`・git HEAD と dirty（worktree の HEAD 取り違え対策）、相手プール・投了モデル・seed・コマンドライン。
- `games.jsonl`（1局1行・終わるたびに追記して flush＝`--resume` 可）:
  - seed・色・相手の段位・終局理由・勝敗・最終目差・リードの最小/最大・AI 勝率の最小
  - 両者の report（WATCH / STRICT × 全体・GUI の3区間・校正用の3区間: top1・top5・mean_ptloss・n）
  - own_minus_opp・own_lt_opp、**own_le_target_plus5**（自分 <= T + 0.05。T は盤サイズ別の目標）・**own_lt_floor**（自分 < 0.15）
  - AI の失着の尾（≥1 / ≥2 / ≥3 / ≥6目）、**flip_moves**（AI の着手で勝率が 50% 以上から未満に落ちた手＝自滅）
  - hp 監査: 外した手（レポート基準）の 9段 hp の中央値・5% 未満の割合
  - 韜晦のアームだけ: 段(i)(ii)(iii)の数、外しの種類別の数、reserve 未満での同値でない外し、接戦中の同値外しの vloss 合計、
    払った vloss の合計（paid_vloss_sum）、罠の次の相手手の実損 / E（trap_next_loss_over_E）、
    **意図とレポートの食い違い**（ledger で外したつもりの手がレポートで一致になった数＝期待値 0）
  - 所要時間（戦略 p50 / p95 / max・解析待ち・壁時計）、visits_check（root visits が max_visits の 0.9 倍未満のノード数）
- `moves.jsonl`（1手1行）: 手数・区間・手番・着手・最善手・一致・points_lost・着手前の lead と勝率・親の visits・
  最善手の prior・実行中の集計・hp 監査・判定情報を平らにしたもの・戦略時間。
- `sgf/`（KT 解析つき）、`logs/`（stub が拾った戦略の DEBUG 行＝`Rate:` / `Decision:`）。
- `summary.txt`（cp932 対策で ASCII のみ）と `summary.json`: アーム × 相手の段位 × 色ごとに、局数・勝敗（Wilson 区間）、
  自分と相手の top1（局の平均と手のプール・局単位クラスタ bootstrap の 95% 区間）、自分−相手とその区間、P(自分<相手)、
  P(own <= T+0.05)、P(own < 0.15)、両者の mean_ptloss、1局あたりの ≥6目の失着と flip_moves、最終目差の中央値と IQR、
  手数の中央値、区間別の自分の top1、外した手の hp 中央値、戦略時間の p95、アーム間の差の表。

## 6. 実験の組み合わせと A/B の手順

**組み合わせ**（13路・既定は各 20 seed。1局あたり 投了あり 2.5分・投了なし 4.5分・ストレス層 3分で見積もり）

| 段階 | アーム | 層 | 局数 | 所要 |
|---|---|---|---|---|
| 0 校正 | 難解＋ | 6段位 × 8局 | 48 | 約2時間 |
| 1 主比較 | 韜晦 既定 / 罠 ON / 攻め（測定専用）/ 難解＋ / HumanStyle 9段 | 通常・投了あり | 5 × 20 = 100 | 約4時間 |
| 2 投了なし | 韜晦 既定 / 難解＋ | 通常・`--no-resign` | 2 × 20 = 40 | 約3時間 |
| 3 接戦ストレス | 韜晦 既定 / 難解＋ | `--komi-shift 4`・強めの相手 | 2 × 20 = 40 | 約2時間 |

合計 約11時間（2〜3晩）。段階1で罠 ON が有望なら、段階3に罠 ON を足す。

**A/B の手順**
- 同じ seed で色・相手・乱数列・投了閾値をそろえ、10 seed ごとのブロックで ABBA の順に回す。
- 一致率の主指標: 局ごとのレポート一致率（WATCH）。seed 対の差の t 区間・Wilcoxon・局単位 bootstrap（1万回）。
- 層別は処置前の因子（相手の段位・色）だけ。**最終目差は処置後の媒介変数**なので記述にだけ使う。
- **停止規則**: 20 ペアで一度だけ判定し、差の 95% 区間が ±3pt の判定線をまたぐときだけ 40 ペアまで延長する
  （見る回数が2回なので各回 α = 0.025 で判定＝Bonferroni）。延長の有無にかかわらず、**安全の最低局数**（接戦ストレス層で
  各アーム 20局）に達するまでは結論を出さない。検出力は 20 ペアで約 7pt。
- **勝ちの安全の判定**（韜晦 spec §10）: 接戦ストレス層の flip_moves の対の差の 95% 上限が 0.1/局以下、かつ敗局数が基準アームより
  2局を超えて多くない。敗局は SGF を列挙して1局ずつ見る。通常層の勝敗は全勝に近く検出力がないので記述にとどめる。
- **null ガード**: 開始前に各アームの解決済み設定を突き合わせ、同一なら中止する（CLAUDE.md の「両アームが本当に違う設定で走るか」）。
- **接戦ストレス層**: `--komi-shift`（AI 不利に 3〜6目）と強めの相手（rank_5d / 9d に `--opp-max-loss 2`、または
  `--opponent strategy:human`）の組み合わせ。見るもの: AI の敗局、flip_moves、lead < reserve のときの同値外しの vloss 合計、
  外しの種類ごとの「判定時の vloss」と「レポートの points_lost」の差（勝者の呪いの検出）。
- **影判定**（`--shadow B`）: アーム A の各手番で B の戦略を同じ局面に対して実行し、選んだ手と判定情報だけ記録して打たない。
  追加クエリはノードに書き戻されない。B の sticky 状態は **B 専用の影の dict**（`game._shadow_state[arm]`）に持ち続け、
  B の実行前にゲームの属性（`_veil_state`・`_enigma_ponder_*`・`board_watch_probe_warm`）を退避して B の影の状態を載せ、
  実行後に B の状態を影へ書き戻してから A の属性を戻す。同じ局面での外し率とコストを対で比べられる（分散が小さい）。
  時間は約 1.3〜1.5 倍。

## 7. 所要時間（RTX 3080・KataGo v1.18.2 CUDA・b10c384・max_visits 2500・maxTime 8秒・設計時に実測）

- 戦略なしの流れ（AI は最善手・相手は 1visit）: 13路 0.93秒/手、9路 0.70秒/手、19路 0.91秒/手。
- 13路の実戦略: 擬態 vs rank_3k 160手で 260秒、難解＋ vs rank_1d 124手で 164秒。
- 1局: 13路は投了ありで約 2〜2.5分・打ち切りなしで 3.5〜5分、9路 約1分、19路 10〜20分（スモークのみ）。
- 並列: 3プロセスでもスループットは +27% で、AI 手番の解析待ちが最大 6.8秒と maxTime 8秒に迫る＝既定 `--jobs 1`。
- **実戦中の KaTrain と同時に走らせない**（実戦の AI が遅くなり maxTime に当たる）。

## 8. CLI

```
python -m katrain_debug.selfplay run --arm A=veil13 --arm B=veil13:veil13_trap_mode=true \
    --size 13 --pairs 20 --opp-pool docs/superpowers/specs/calibration-data/selfplay/opponent_pool_13.json \
    [--komi-shift 4] [--no-resign] [--shadow B] [--hp-audit rank_9d] [--label trap-ab] [--resume DIR]
python -m katrain_debug.selfplay calibrate --size 13 --strategy enigma13plus --ranks rank_8k,rank_5k,rank_3k,rank_1k,rank_1d,rank_3d --games 8
python -m katrain_debug.selfplay summarize DIR [--compare A B]
python -m katrain_debug.selfplay report-sgf FILE.sgf     # 実戦の保存 SGF から両者のレポート一致率を出す
```

パスはリポジトリのルートからの相対。アームの書式は `<名前>=<runner の戦略名>[:key=val,...]`
（`katrain_debug/cli.py:13-36` の `parse_settings` を流用）。

## 9. 純関数（`selfplay_stats.py`）とテスト

- `selfplay_schedule`（seed → 色・段位・投了閾値・ABBA 順）、`selfplay_opponent_pick`（hp^(1/τ) のサンプルと非合法手の引き直し・
  パスの引き直し）、`selfplay_should_resign`（盤サイズ別の開始手数）、`selfplay_outcome`、`watch_prune`（コンテキストマネージャ・
  children と current_node を必ず戻す）、`selfplay_game_summary`、`selfplay_arm_summary`（Wilson 区間・クラスタ bootstrap・対の差・
  P(自分<相手)・P(own <= T+0.05)・P(own < 0.15)）、`arms_null_guard`。
- `tests/test_selfplay_stats.py`: 上の純関数。seed の決定性、null ガード、WATCH 刈り込みの復元、
  **current_node が末尾パスの状態でも WATCH にパスが入らない**。
- `tests/test_selfplay_runner.py`: 偽エンジンでの短い対局、`_ai_turn` と `generate_ai_move` の一致、相手のパス規則
  （pass_loss が None ならパスしない）、影判定で A の状態が変わらない。

## 10. データの移設（最初にやる）

校正の目標データとスクリプトはリポジトリ外の一時フォルダにしかない（消える）。移設元は2か所:
1. `%TEMP%/claude/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/d4ae766f-520f-4142-b31e-a59d28c60c07/scratchpad/`
   の `recon/`（実戦 13路 18局の SGF と `report_game_*.json`・約 0.9MB）、`offline_report.py`、`recon_logs.py`、
   `join_turns.py`、`inventory2.py`。
2. `%TEMP%/claude/C--Users-iwaki--katrain/819b933e-8892-42ff-9c0a-7d2186f48b8c/scratchpad/design/` の `calib_targets.py`
   （校正目標と区間の定義）、`proto_selfplay.py`（試作）、`bench_pipeline.py` / `bench_size.py`（計測）、`cf_absolute.py` /
   `cf_absolute2.py` / `cf_veil.py` / `veil_cf.py` / `judge/unified_cf.py`（韜晦の反実仮想）。

移設先は `docs/superpowers/specs/calibration-data/selfplay/`。移した後、スクリプト内に直書きされた `recon` のパスを
リポジトリ内の相対パスへ書き換える。

## 11. リスク

- **相手の忠実度**: 1visit の humanSL は読まない・時間に追われない・投了の仕方も違う。周辺統計（一致率・損失・区間の形・手数）
  でしか校正できず、罠への掛かりやすさは違いうる（相手の実損 / E が実戦の 1.06 に近いかで確かめる）。
- **ハーネスと実戦のずれ**: 実戦の目標値は事後再解析の数字で、対局中のレポートとは数 pt ずれる（擬態の Rate 行 41〜42% vs 再解析 45〜46%）。
  難解＋のアームでずれを測ってから絶対値を読む。
- **リードの交絡**: 一致率はリードでほぼ決まり、アームはリードの軌跡・投了時期・ヨセの割合を変える。`--no-resign` を必ず併記する。
- **KataGo の非決定性**: 1〜3局で結論しない。比較は最低 20 ペア。
- **GPU の競合と maxTime**: 並列実行や実戦中の実行で visits が打ち切られ、レポートの基準が変わる。visits_check で検出する。
- **写した `generate_ai_move` のずれ**: 上流の変更で黙って食い違いうる＝テストで固定する。
- **設定の取り違え**: 綴り間違いの上書きや、ユーザー config に無いモードは黙ってコードの既定値で走る。解決済み設定の突き合わせと
  `ai.__file__`・git ハッシュの記録で防ぐ。
- **過学習**: ハーネスの相手の癖に合わせて既定値を調整しすぎる恐れ＝最終的な既定値は実戦の交互 A/B で確かめる。
