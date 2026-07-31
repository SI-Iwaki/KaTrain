# CLAUDE.md

## 概要

KaTrain v1.17.1.1 修正版。囲碁AI学習ツール。

- 上流リポジトリ: https://github.com/sanderland/katrain
- ランタイム設定: `C:\Users\iwaki\.katrain\`
- 主な改修: Human-like AI（9段）モードの拡張。悪手フィルタ（スコアベースのフィルタリング）に加え、力戦派（Fighting）・攻城（Siege）・狩猟（Hunt）・狩猟一致率低減（HuntDivergence）・AI一致率低減（Divergence）・地合い勝ち（Jigo）等の戦略モードを追加・改修。力戦派には複雑化モード `complex`（切りボーナス＋リード適応の損失予算ゲートで盤面を紛れさせる）を追加。Jigo には序盤星打ち強制オプション `jigo_force_sanrensei`（19路のみ・黒=三連星/白=2連星）を追加。さらに Jigo には9路専用の独立戦略 `ai:jigo9`（持碁（9路））を追加（既存 `ai:jigo` は19/13路専用に整理）し、9路 deception の phase 境界・target を5スライダーで調整可能にした（phase3前倒しで挽回を間に合わせる）。星打ち布石ロジックは `ai.py` の共有ヘルパー `_compute_star_opening_targets` に集約し HumanStyle の2連星と共用。詰碁画面キャプチャ（tsumego_capture: グローバルホットキーでBlueStacks上の詰碁アプリ盤面を認識しKaTrainに反映+外枠自動適用（大型詰碁は適応marginで補償面積を確保）+黒番AIが正解手を自動着手し白番はユーザーが応手、auto_ai_black:falseで従来動作）を追加。詰碁の着手選択 `ai:tsumego` は ownership gain（集計対象は**リージョン内の石のみ**＝枠外の代償地帯は成否と逆相関する／同着はgain_epsilonで目数に委ね、目数もpoints_epsilon内で並ぶ同着バンドではvisits最多のKataGo本命を採る＝ノイズのコイン投げで解答樹に無い正しい別解を踏まない／min_visits未満の候補は除外／**gain で目数最善手を覆せるのは同程度に探索された候補だけ**＝gain_min_visit_ratio、覆す判断は子局面を同visitsで解析し直して絶対ownershipで検証＝gain_verify。gain 争いに参加できなかった候補（目数ガード外・深さゲート外）も gain が明確に上回るなら同深さ検証を経て救済＝gain_rescue_margin（トリガーと採用の両マージン。gain 降順トップ3を全員検証し検証値最良を採用＝ノイズ手が gain 1位でも本物が影に隠れない。visit比では本物と偽の gain が分離できず、スコアの真偽を分離できるのは同深さ検証だけ。ただし**検証もクラス（無条件>コウ）は分離できない**＝コウ勝ち前提のownershipは実信号になる）。選択パイプライン（バンド→検証→救済）の**最後にコウ経路検査**＝選択手が目数ガード内なら、ガード内の対抗馬とともに「候補手自身＋リージョン子局面解析の最善応手PV」でコウ形を構造検出し（**この子局面解析は歩く深さぶん枠外を禁じて撃つ**＝`untilDepth=1` は root の着手選択しか縛らず ply2 以降の PV が枠へ手抜きしてコウが消える）、選択手がコウ経路でcleanな対抗馬がいれば**目数同着バンド（points_epsilon）内の**visits最多のcleanへ格下げ（tie_ko_screen。**格下げ先をバンド内に限るのは「無条件」が「攻めないので何も起きず自明にclean」でも成立するから**＝答えがコウの詰碁では正解が無関係な手に差し替わる＝case R。旧実装は同着バンド内だけ検査していたが、コウ殺しのgainは相手石を取り切る実信号でバンドから抜け出す＝case M。親PVは守り方が枠へ手抜きするので使えず、候補自身の1子取りコウは守り方が取り返せないので応手PVにも現れない。ガード外の救済採用手は検査しない＝枠なし盤ではガード内のclean手がスコアだけ良い失敗手でありうる）。**その検査で対抗馬も全部コウ経路だったら、詰碁の順序上それは「正解が候補プールの外にいる」信号**（目数で劣るcleanが居て格下げを断っただけの場合は前提が偽なので脱出しない）なので、root policy の上位（未検査分）を同深さで測り直して無条件の手を探す＝ko_escape_candidates（root の value が壊れている手は PUCT が二度と訪れないので深さでは届かない＝実測 case O の正解は 1800visits でも 12000visits でも v1。value が壊れていても policy は候補を挙げているので探す先は policy。**採用条件は「incumbent を上回る」ではなく「tolerance 超えて下回らない」**＝コウ手のスコアは「コウに勝った前提」なので無条件の正解よりむしろ高く出る）。gainは1本のroot探索のmovesOwnership由来なので浅い候補ほど片側ノイズが出る）に加え、コウは「コウダテがある前提」でコウ勝ち後の局面を評価（ko_win_assumption）。**詰碁の正解順序は 無条件に殺す（生きる） > コウ > セキ** で目数はクラス内のタイブレークにすぎないため、通常最善が既に成功している局面ではコウを検査しない。ただし**成功判定は目数（ko_success_lead）と ownership（ko_success_ownership）の AND** — 枠の代償地帯が未決着だとスコアが詰碁から切り離され、既存16ケース横断の実測で H/Q の2件が「相手石は生きているのに目数は成功」と出た。枠はキャプチャ時に frame_ko の両方を張って root スコアがバランスの取れた方を自動採用（拮抗時は攻め方コウダテ側）。さらに**手番側（解く側）の本体石が開始時点で死と読まれる枠は詰碁自体を壊しているので捨て、その回だけ枠なしで出題する**（必ず正解手がある詰碁で開始時点から全滅はあり得ない。枠バランスはこの失敗に構造的に不感）。ただし**この読みを浅い trial visits で確定させない**＝生き問題では手番側の石そのものが戦いの対象なので「エンジンがその詰碁を解けたか」を聞くのと同じになり有効な枠まで死と出る。捨てる前に `frame_validity_visits`(1800) を **`wideRootNoise=0`** で読み直し（wRN は着手選択で候補を広げる設定で、生死の裁定では探索が critical line に集中せず読みが二峰性になる＝これが正体。壊れた枠は設定を変えても死のまま）、それでも死なら**捨てる先の枠なし盤も測って比較する**（`frame_over_frameless`。枠なしはリージョン外が丸ごと相手の地になるので安全側のフォールバックではない）

## 技術スタック

- **言語**: Python 3.12
- **GUI**: Kivy
- **AIエンジン**: KataGo v1.16.4（TensorRT版）
- **GPU**: NVIDIA GeForce RTX 3080
- **ビルド**: hatchling / uv

## KataGo 解析結果の扱い（必読）

- **winrate は常に黒視点**: `engine.py:108` で `reportAnalysisWinratesAs = "BLACK"` ハードコード。打つ側視点にするには `wr if player=="B" else (1-wr)` で変換
- **`parent_node.winrate` と `cands[0]["winrate"]` は別物**: 前者は `analysis["root"]["winrate"]`（手を打つ前の勝率）、後者は最善手を打った後の勝率。「現在の局面の勝率」を取るなら前者
- **`pointsLost` は符号あり**: 負値 = KataGo 予想より良い手。ユーザー向けには `max(0, pointsLost)` でクランプ、メトリック計算には生の値を使う

## ディレクトリ構造

```
katrain/
  core/               -- コアロジック（主要ファイルのみ記載）
    ai.py             -- AI着手生成（HumanStyleStrategy, FightingStrategy, SiegeStrategy, HuntStrategy, HuntDivergenceStrategy, DivergenceStrategy, JigoStrategy = 主な改修箇所）
    constants.py      -- 定数、AI設定ウィジェット定義（AI_OPTION_VALUES）
    engine.py         -- KataGoエンジン管理
    game.py           -- ゲーム状態管理
    game_node.py      -- 棋譜ノード
    sgf_parser.py     -- SGFパーサ
    base_katrain.py   -- 設定管理・アプリベース
    tsumego_capture.py   -- 詰碁アプリ画面キャプチャ→盤面認識→SGF化（Kivy非依存、CLI: python -m katrain.core.tsumego_capture）
    ...               -- utils.py, lang.py, contribute_engine.py, tsumego_frame.py 等
  gui/                -- Kivy GUIウィジェット
  config.json         -- パッケージ同梱のデフォルト設定
  i18n/               -- 多言語リソース
tests/                -- テスト
katrain_debug/        -- 戦略デバッグCLIツール（KaTrain本体と独立）
  cli.py              -- argparseエントリポイント
  runner.py           -- SGF→局面構築→戦略実行パイプライン（単一局面）
  batch_eval.py       -- 1局通しバッチ評価（AI一致率・損失算出）
  katrain_stub.py     -- Kivy依存なしのKaTrainスタブ
```

**校正・ベースラインデータ**: `docs/superpowers/specs/calibration-data/<機能名>/` のサブディレクトリに機能別で格納。命名規則: `<モード>-vs-<相手>-<YYYYMMDD>[-<色>].sgf`、結果は `<機能>-results-<YYYYMMDD>.md`。既存 SGF は `clean_sgf_main_line.py` で main-line 化してから使う

**ランタイム設定ファイル**（`C:\Users\iwaki\.katrain\`）:
- `config.json` — KaTrain全体の設定（エンジンパス、モデルパス、AI設定等）
- `analysis_config.cfg` — KataGo解析エンジン用設定
- `katago.exe` — KataGoエンジン本体
- `b18c384nbt-humanv0.bin.gz` — humanSLモデル（`config.json`の`humanlike_model`が空だとhumanSLProfile系の全戦略が動作しない）

## 起動・デバッグ

```bash
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
uv sync          # 依存パッケージのインストール
python -m katrain
```

テスト: `pytest`（SGFパーサ、盤面ロジック、AI着手生成のユニットテスト）。AI系テスト（`test_ai.py`）はhumanSLモデルが必要なため、モデル未配置の環境では `pytest --ignore=tests/test_ai.py` で除外する

フォーマッタ: `black katrain/`（line-length=120、設定は`pyproject.toml`）

デバッグ: `C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `1` に変更して起動。確認後 `0` に戻す。

**戦略デバッグCLI**: 対局不要で任意の局面の戦略意思決定を再現・確認（KataGo起動あり、約30秒）:
```bash
python -m katrain_debug --sgf FILE --move N --strategy hunt [--settings key=val ...] [--output text|json]
```
対応戦略: `human`, `pro`, `fighting`, `siege`, `hunt`, `hunt_diverge`, `diverge` 等22種。`--output json` でパース可能な構造化出力。

**バッチ評価モード（`--batch`）**: 1局通しでAI最善手一致率・平均損失・正確度を算出。パラメータ調整に使用:
```bash
# 全手・両色で評価
python -m katrain_debug --sgf FILE --strategy hunt --batch
# 白番のみ評価
python -m katrain_debug --sgf FILE --strategy hunt --batch --player W
# 手数範囲を指定（中盤のみ）
python -m katrain_debug --sgf FILE --strategy hunt --batch --move-range 51-180
# パラメータを変えて比較
python -m katrain_debug --sgf FILE --strategy hunt --batch --settings hunt_max_loss=4.0 hunt_focus_stddev=5.0
```
出力: Settings（パラメータ値）、Aggregate Stats（Overall/B/W/Opening/Middle/Endgame別の Top1一致率・Top5一致率・平均損失・正確度）、Notable Divergences（損失2.0超の手一覧）。`--output json` で全手の詳細をJSON出力（batch は top-level `stats.overall.ai_top_move` 等、単一局面 `--move N` は `result.explanation` / `result.move` にネスト）。KataGoは1回だけ起動し、205手の局で約10分。
追加メトリック（全戦略）: Lambdago Metrics ブロックに **Choice-vs-Median Gap**（選択手 vs 候補手中央値の損失差、負ほど AI 寄り、勝率 95% 超の手は除外）と **Post-98% Slack**（勝率 98% 到達後の平均損失変化、正なら勝勢で手が緩むサイン）を表示。lambdago 論文 (arXiv:2009.01606) 由来の診断指標で、jigo モードの人間らしさ評価に使用。詳細は `docs/superpowers/specs/2026-04-14-lambdago-cheat-metrics-design.md`。

**`--batch` はログ要約モード**: per-move `[StrategyName]` debug ログ（`Fallback triggered` / `Safety valve` / `Filter: N → M passed` 等）は抑制される。フィルタ動作やフォールバック発動率を確認したい場合は `--move N` で個別実行すること。

**戦略別 runtime の差**: `jigo` は温度サンプリングを使わず argmax 選択のみのため戦略側は決定的。120-220 手の SGF で **約 2-3 分/run**。ただし **KataGo 事後解析の並列探索非決定性により実測 3-run stdev は ai_top_move で ~0.03、mean_ptloss で ~0.05 程度**発生し、同一コードでも手選択が 10-30% run 間で変動する。パラメータ比較時は必ず 3-run 平均を取ること（hunt/fighting 等は温度サンプリング込みで ~10 分/run）。

## コーディング規約

- コミットメッセージは**日本語**で書く
- Conventional Commits形式を使用（`feat:`, `fix:`, `refactor:` 等）
- 改修はほぼ `katrain/core/ai.py` の `HumanStyleStrategy` / `FightingStrategy` / `SiegeStrategy` / `HuntStrategy` / `HuntDivergenceStrategy` / `DivergenceStrategy` / `JigoStrategy` クラスに集中

## やってはいけないこと

- **ログファイルをReadで全読みしない** — 数百KB〜1MB超あるため、必ずGrepで必要行だけ抽出する
- **Stage 1（humanSLProfile付き）の`scoreLead`をフィルタ判定に使わない** — バイアスされているため、必ずStage 2のクリーンクエリの値を使う
- **パッケージ`config.json`だけ更新して終わらない** — ユーザーのローカル設定`C:\Users\iwaki\.katrain\config.json`にもキーを追加しないとGUIに表示されない
- **ユーザーローカル`config.json`（`C:\Users\iwaki\.katrain\config.json`）の編集をサブエージェントに委任しない** — サブエージェントが成功を報告しても実際に反映されないことがある。このファイルは必ずメインセッションで直接Editする
- **`analysis_config.cfg`や`katago.exe`を直接編集しない** — ランタイムエンジン設定は手動管理
- **i18nの`.po`ファイルだけ編集して終わらない** — `python tools/compile_mo.py` で`.mo`にコンパイルしないと翻訳が反映されない
- **詰碁の ownership 集計にリージョン外の石を混ぜない** — 枠は `put_outside` で枠外を「守り側の代償地帯＋攻め方の地」に配る設計なので、枠外の石の ownership は詰碁の成否と**逆相関する**。全石で合計すると符号が反転し、守り側が生きる手が選ばれる（実測: 枠内 −9.65 vs 枠外 +11.6）
- **枠バランス（`frame_balance_distance`）で枠の妥当性を判定しない** — 枠は「想定した攻め方が成功したら5目勝ち」に代償地帯を調整するので、攻め方の推定が反転していても想定攻め方が実際に成功する＝バランスは完璧に見える（実測 2026-07-30 case G: 距離 2.06 で過去最良なのに黒の攻め石は全滅、19路に置き直しても 5.42）。枠が生きているかは**手番側の本体石が生きているか**で見る（`frame_destroys_problem`）
- **KataGo の run 間分散を同一プロセスの再クエリで測らない** — 探索木が再利用されて 0.2 秒で返るため独立サンプルにならない（実測 2026-07-30 case N: 1プロセス内では +0.57/+0.76/+0.71 と安定して見えるが、engine 起動を挟むと同一局面・同一 visits で −0.95〜+0.95 の二峰性だった）。分散を根拠に閾値を決めるなら必ずプロセスを分けて測る
- **詰碁で「root に読まれなかった手」を visits で救おうとしない** — root の value 推定が壊れている手は PUCT が二度と訪れないので、深さを積んでも visit 配分は変わらない（実測 2026-07-31 case O: 正解 A11 は root 1800visits でも **12000visits でも v1 のまま**。1visit の評価は「+28.74目損・相手は生き」だが、同じ子局面を独立に 1800visits で解析すると「+11.53目・相手10子すべて全滅」で **value が約29目ずれている**）。value が壊れていても **policy は候補を正しく挙げている**（A11 は prior 5位で 2/2 run 固定、下限手との間に10倍の崖）ので、漏れた正解を探す先は visits ではなく policy。**候補の pointsLost・gain・ownership が「その手が悪い」根拠になるのは、その手に visits が付いているときだけ**（切り分けは `child_depth_probe.py`）
- **詰碁で「成功しているか」をスコアだけで判定しない** — 枠は「攻め方が成功したら5目勝ち」に代償地帯を調整する設計だが、その代償地帯が未確定のまま残るとスコアが詰碁の成否から切り離される（実測 2026-07-31 case Q: 相手石12子すべて生存＝−0.99/子 なのに手番側 +10.45目。**全盤 20000visits の最善手が詰碁と無関係な枠の充填部 B9 v17448** だった）。枠なし盤ではさらに露骨で case H は +27.69目・相手石 −0.15/子、スコアの絶対値は ±60〜80 まで暴れる。既存16ケース横断では成功局面が +0.94〜+1.00・失敗局面が −0.15〜−1.00 で、**ownership なら 1.09 の空白で分離できる**（`ko_success_ownership`）。なお**どちらの詰碁か（殺す/生きる）は選択則に渡ってきていない**ので、自石・相手石の両方を測って厳しいほうを採る
- **詰碁のクラス裁定（無条件 > コウ）に目数差を覆させない** — 「無条件」は「攻めないので何も起きず自明に clean」でも成立するので、**答えがコウの詰碁では格下げが正解を無関係な手に差し替える**（実測 2026-07-31 case R・13路上辺枠なし: 正解 G13=コウ pt+0.03 v1345 を、詰碁と無関係な D8=clean pt+0.55 v288 に格下げして誤答。コウ経路の**検出自体は正しかった**）。`_ko_escape_choice` と同じ ownership 検算を格下げにも課す案は**効かない** — 答えがコウなら ply1 で成否が決着しないので、同深さ800visits の全リージョン石で正解 G13 +0.86/+0.97 < 誤答 D8 +1.32/+2.34 と**誤答のほうが高く**出る（相手石は全候補 −0.55〜−0.72＝どの手でも相手は生きている）。符号が一貫していたのは目数だけで、格下げが正しい4ケースは格下げ先が必ず優る（K −0.05 / L −0.11 / M −0.57 / P −0.03）のに case R は +0.52 劣る（切り分けは `class_screen_probe.py`）
- **詰碁の誤答を選択則のせいにする前に「対抗馬が居たか」を見る** — gain・同深さ検証・救済・コウ経路検査・コウ脱出はすべて「目数ガード内の候補を比べる」機構なので、`min_visits` を通った候補が**1手だけ**になると揃って不発になり、戦略は KataGo の最善手をそのまま返しているだけになる（実測 2026-07-31 case Q: 1800visits 中 1764 が H13 に集中し eligible は H13 のみ。`Final decision: … 候補37手` は37手から選んだように読めるが実際は無選択だった）。debug ログの `対抗馬なし:` 行と `候補N手（うち対抗馬M手）` で判別する
- **同深さ検証の差を「解析条件を変えても残るか」で検算する** — untilDepth や visits を変えると向きが変わる差は実信号ではない（実測 case Q: 正解候補 N9 と誤答 H13 の相手石 ownership 差は untilDepth=1/1800visits で 2.2、8000visits で 1.26、`_region_child_verdict` と同じ untilDepth=6 では 0.2 の誤差内に消えた）。**準備手（それ単体では何も起きず価値が数手先に出る手）が正解の詰碁は、KataGo の value がその手を「負け」と読むため（case Q: 全盤 20000visits で N9 は winrate 0.450・v3）policy 上位を測り直しても浮かばず、選択則・枠・深掘りのどれでも救えない**（case I と同じ未対処の既知限界。エンジン更新時に再評価）
- **コウ脱出（および今後のクラス裁定）の採用条件を「incumbent を上回ること」にしない** — コウで殺す手のスコアは「コウに勝った前提」で出るので無条件の正解より**むしろ高い**（実測 case O 同深さ800visits: コウ B12 +41.95 > 正解 A11 +41.85）。既存の `tsumego_override_confirmed`（margin 超えで上回る）を流用すると正解が落ちる。順序を決めるのはクラス（無条件 > コウ）で、スコアは「詰碁が成立しているか」の確認にだけ使う（失敗手は +18.5 まで落ちるので 23 点差で分離できる）
- **PV の内容を証拠に使う解析を `untilDepth=1` のまま撃たない** — リージョン解析の `avoidMoves untilDepth=1` が縛るのは root の着手選択だけで、**ply2 以降の PV は枠の外へ自由に出ていける**。詰碁を読み切った KataGo にとって「負けている側の局所の抵抗」は枠の一点と同値なので、守り方の PV は肝心のコウを打たずに枠へ手抜きし、構造検出の証拠そのものが消える（実測 2026-07-31 case P: 黒 H1 の子局面で白の最善応手 J1 は v59〜99 で単独首位と安定しているのに、その PV が `J1,L2,`**`J12`** と ply3 で枠外へ。コウ検出はプロセスを分けた 4 trial 中 **1回**だけで、実戦はその外れを引いて誤答した）。**PV を証拠にするなら歩く深さぶん枠に縛る**（`TSUMEGO_KO_REGION_UNTIL_DEPTH` = `TSUMEGO_TIE_KO_PLIES`。同 4 trial で 4/4 検出・無条件の正解は 4/4 clean のまま）。同じ失敗は「親局面の PV は枠へ手抜きするので使えない」（case K）で一度踏んでおり、子局面へ移しても**深さ1の強制では ply1 しか局所化できていなかった**
- **応手の並びを証拠に使う検査にも `wideRootNoise` を効かせない** — 上の死活裁定と同じ罠。root の Dirichlet ノイズは run ごとに引き直され、しかも1回の探索の間ずっと乗るので **visits を増やしても消えない**揺れを「守り方の応手にどう visits が配られるか」に作る（実測 2026-07-31 case M・コウ経路検査の子局面: wRN=0.04 で コウ仕掛け K1 の比が 0.44〜0.88 とばらつき本番フロー 3/6 で検出漏れ → **wRN=0 で 0.15 が 4/4 不動**、M4 v663/K1 v100/残り全部 v1）。旧 0.5 ゲートは「ノイズが本物のコウ応手の取り分を水増ししてくれた時だけ当たる」偶然の産物で、visits を増やすほど真値に収束して外れやすくなる。**閾値を動かす前に全ケースで両側を測る**（実測: 検出すべき最小 0.09 ＜ clean のままにすべき最大 0.16 で逆転＝単一閾値では分離できない。選択手だけ敏感側 0.05、格下げ先は保守側 0.5 で分ける。切り分けは `ko_reply_ratio_probe.py`）
- **死活の裁定クエリに `wideRootNoise` を効かせない** — wRN は着手選択で候補リストを広げるための設定で、「この石は生きているか」を聞く裁定では root の探索が critical line に集中できず ownership が決着しない（実測 case N: wRN=0.04 だと 1800visits で +0.95〜−0.95 の二峰性・6000visits でようやく安定＝1本 4.8〜8.4秒、wRN=0 なら 1800visits で +0.96〜+0.97 に安定＝1本 1.7秒）。**深さで殴る前に、その問いに不要なノイズが入っていないか疑う**
- **枠の採否判定（`frame_destroys_problem`）を trial visits の読みで確定させない** — 生き問題は「解けたら生き」なので浅い読みでは必ず死側に倒れる（実測 case N の有効な枠: 400 で −0.69〜−0.98/子）。捨てた先の枠なし盤は root −75目・手番側コア −0.75/子 で**枠より激しく詰碁が消えている**（gain も目数も「相手の外側の石を攻める手」を評価し、正解は選択則のどの経路でも救えない）
- **枠の妥当性判定に壁石を混ぜない** — 壁は自明に生きているので判定が埋もれる（実測 case D: 壁込み +25.00/25 で常に正常判定、本体石だけなら +8.00/8）
- **偏差/dodgeメカニズムで生humanPolicyを順位判定に使わない** — proximity/intensity込みのcombined weightを使わないと、攻撃対象から遠い手に差し替わり棋風が崩壊する
- **空間的に離れた2点の座標平均をフォーカス/ターゲット中心に使わない** — 盤の反対側にある2点の平均は「どちらにも近くない幻影中心」になり、実際の戦闘エリアの手がペナルティを受ける。代わりに独立したGaussianのmaxを取る（2アンカーmax方式）
- **Kivyモジュールをimportするスクリプトでargparseを使う場合、`os.environ["KIVY_NO_ARGS"] = "1"` を先頭で設定する** — KivyのConfigが`--help`等のCLI引数を横取りする
- **KaTrainのコンソール出力を grep する時は `grep -a` を付ける** — ログ内の `→` 等の非ASCII文字で grep がバイナリ扱いになり `Binary file (standard input) matches` 表示で出力抑制される
- **SGF の構造保存 round-trip で `root.sgf()` / `GameNode.sgf()` を使わない** — `GameNode.sgf_properties` が root の `C/CA/AP/KTV` を自動書換えるため元プロパティが失われる。保存的に出力したいなら `node.properties` を直接シリアライズする（例: `docs/superpowers/specs/calibration-data/clean_sgf_main_line.py`）
- **KaTrain 保存 SGF は variation 多数で `node.children[0]` traversal が main line に届かない** — 短い分岐に落ち込んで数手で打ち切られる。batch_eval 等で実戦全手を評価するには `clean_sgf_main_line.py` で最長パスに前処理する
- **Python スクリプトで `±`・`≈`・日本語等を扱う時は Windows cp932 対応を考慮する** — ファイル書き出し時（`>`）は `PYTHONIOENCODING=utf-8` で壊れバイト化を防ぐ。CLI 出力（print）は cp932 端末で `UnicodeEncodeError` クラッシュするため、ユーザー向け出力は **ASCII のみ推奨**（例: `≈` → `~`）
- **`tasklist` の出力ヘッダーは cp932 環境で文字化けする** — 日本語 Windows では「イメージ名/PID/…」部分が読めないが、データ行の ASCII 値（PID・プロセス名・メモリ）は正常。grep や値抽出は問題なく使える

## 開発ワークフロー

- 詳細な実装ガイド・チェックリストは `.claude/rules/` に格納。対象ファイル編集時に自動ロードされる:
  - `katrain/core/ai.py` 編集時 → `ai-humanstyle.md`（フィルタ実装詳細、パラメータチェックリスト）、`ai-parameters.md`（全戦略パラメータ値）
  - `katrain/core/constants.py` / `katrain/config.json` 編集時 → `ai-settings-gui.md`（AI設定追加手順）
  - `katrain/core/base_katrain.py` 編集時 → `base-katrain-config.md`（JsonStore構造・起動時リセットパターン）
  - `**/*.log` 分析時 → `log-analysis.md`（Grepパターン、サブエージェントテンプレート）
- **i18n変更時は `.po` 編集後に `python tools/compile_mo.py` で `.mo` を再コンパイルすること**
- **パラメータ変更時は `.claude/rules/ai-parameters.md` のテーブルも同時に更新すること**
- **`.claude/rules/` 配下のファイル編集時の注意**: `settings.local.json` で `Edit(.claude/rules/*)` を許可していても、`dontAsk` モードでEditが拒否されることがある（既知の問題）。拒否された場合は **サブエージェント（Agent tool）経由で編集・コミット** すること

## 変更の検証方法

1. デバッグモードを有効化（「起動・デバッグ」セクションの debug_level 切り替え参照）
2. `python -m katrain` で起動し、対局を実施
3. ログをGrepで確認（`log-analysis.md` のパターン参照）:
   - 着手結果（共通）: `Selected:|Safety valve.*forced|Tiebreak|Endgame: played`
   - フィルター効果: `moves pass score filter out of`
   - 重み付け効果: `Safety v2: top weighted move`（loss値で最善手からの乖離度を確認）
   - 設定値: `Initializing.*Strategy with settings`
   - フェーズ確認: `Phase:`（SiegeStrategy / HuntStrategy）/ `Mode:`（FightingStrategy）
   - dodge効果: `Best-move dodge:`（HuntDivergenceStrategy）/ `Post-temp safety:`（HuntStrategy温度選択後安全チェック）
   - フォーカス効果: `Focus: anchors=`（HuntStrategy注意フォーカスのアンカー座標とstddev）
   - 追撃効果: `Pursue:`（HuntStrategy攻め合い追撃の発動/スキップ）
4. 確認後、`debug_level` を `0` に戻す

**CLI検証（対局不要）**: 特定局面でのAI戦略の挙動を即座に確認:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --output text
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --output json 2>/dev/null | python -c "import sys,json; print(json.dumps(json.loads(sys.stdin.read()), indent=2))"
```

**バッチ評価（1局通し）**: 戦略のAI一致率・損失を一括計測してパラメータ調整:
```bash
python -m katrain_debug --sgf tests/data/panda1.sgf --strategy hunt --batch --player W
```

## 現在のパラメータ値

`.claude/rules/ai-parameters.md` に全戦略のパラメータテーブルを格納（`ai.py` 編集時に自動ロード）。
