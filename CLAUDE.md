# CLAUDE.md

## 概要

KaTrain v1.17.1.1 修正版。囲碁AI学習ツール。

- 上流リポジトリ: https://github.com/sanderland/katrain
- ランタイム設定: `C:\Users\iwaki\.katrain\`
- 主な改修: Human-like AI（9段）モードの拡張。悪手フィルタ（スコアベースのフィルタリング）に加え、力戦派（Fighting）・攻城（Siege）・狩猟（Hunt）・狩猟一致率低減（HuntDivergence）・AI一致率低減（Divergence）・地合い勝ち（Jigo）等の戦略モードを追加・改修。力戦派には複雑化モード `complex`（切りボーナス＋リード適応の損失予算ゲートで盤面を紛れさせる）を追加。Jigo には序盤星打ち強制オプション `jigo_force_sanrensei`（19路のみ・黒=三連星/白=2連星）を追加。さらに Jigo には9路専用の独立戦略 `ai:jigo9`（持碁（9路））を追加（既存 `ai:jigo` は19/13路専用に整理）し、9路 deception の phase 境界・target を5スライダーで調整可能にした（phase3前倒しで挽回を間に合わせる）。星打ち布石ロジックは `ai.py` の共有ヘルパー `_compute_star_opening_targets` に集約し HumanStyle の2連星と共用。詰碁画面キャプチャ（tsumego_capture: グローバルホットキーでBlueStacks上の詰碁アプリ盤面を認識しKaTrainに反映+外枠自動適用（大型詰碁は適応marginで補償面積を確保。**役割指定ホットキー** `hotkey_attack`=shift+f4（黒が攻め方=殺す問題）/`hotkey_defend`=ctrl+f4（黒が守り方=生きる問題）で枠の攻め方を明示できる＝極値票の役割反転（case X）対策。F4=自動推定は従来どおり）+黒番AIが正解手を自動着手し白番はユーザーが応手、auto_ai_black:falseで従来動作）を追加。詰碁の着手選択 `ai:tsumego` は ownership gain（集計対象は**リージョン内の石のみ**＝枠外の代償地帯は成否と逆相関する／同着はgain_epsilonで目数に委ね、目数もpoints_epsilon内で並ぶ同着バンドではvisits最多のKataGo本命を採る＝ノイズのコイン投げで解答樹に無い正しい別解を踏まない／min_visits未満の候補は除外／**gain で目数最善手を覆せるのは同程度に探索された候補だけ**＝gain_min_visit_ratio、覆す判断は子局面を同visitsで解析し直して絶対ownershipで検証＝gain_verify。gain 争いに参加できなかった候補（目数ガード外・深さゲート外）も gain が明確に上回るなら同深さ検証を経て救済＝gain_rescue_margin（トリガーと採用の両マージン。gain 降順トップ3を全員検証し検証値最良を採用＝ノイズ手が gain 1位でも本物が影に隠れない。visit比では本物と偽の gain が分離できず、スコアの真偽を分離できるのは同深さ検証だけ。ただし**検証もクラス（無条件>コウ）は分離できない**＝コウ勝ち前提のownershipは実信号になる）。選択パイプライン（バンド→検証→救済）の**最後にコウ経路検査**＝選択手が目数ガード内なら、ガード内の対抗馬とともに「候補手自身＋リージョン子局面解析の最善応手PV」でコウ形を構造検出し（**この子局面解析は歩く深さぶん枠外を禁じて撃つ**＝`untilDepth=1` は root の着手選択しか縛らず ply2 以降の PV が枠へ手抜きしてコウが消える）、**さらに「守り方がコウ取りを打てる状態になったか」も見る**＝PV がそのコウを打たなくてもコウ経路（`tsumego_defender_ko_points`／深さ `TSUMEGO_KO_AVAIL_PLIES`=5。リージョン解析は守り方からコウダテを取り上げるので、コウを仕掛けるのが守り方の純損になり**コウが争点の局面ほどエンジンはそのコウを打たない**＝PV を証拠にする判定が肝心なときに黙る。ただし候補手より前から打てたコウは局面の性質なので数えない）。選択手がコウ経路でcleanな対抗馬がいれば**目数同着バンド（points_epsilon）内の**visits最多のcleanへ格下げ（tie_ko_screen。**格下げ先をバンド内に限るのは「無条件」が「攻めないので何も起きず自明にclean」でも成立するから**＝答えがコウの詰碁では正解が無関係な手に差し替わる＝case R。**さらに格下げ先が本当に解いているかを確かめてから差し替える**＝tsumego_declass_confirmed（格下げ先の子局面を同深さで解析し1子平均 >= ko_success_ownership。尺度は tsumego_success_ownership と同じで、役割が読めれば役割石だけ・**読めない枠なしでも自石と相手石の厳しいほう**で測る。バンドで塞げるのは「非解が目数で劣る」形だけで、**非解が目数でむしろ優る**局面は素通りする＝case V（枠あり）・case W（**枠なし・格下げ先が目数最善**）。case R の「効かない検算」は全リージョン石の**両者比較**で、こちらは**格下げ先だけの絶対判定**。答えがコウなら正解もply1では成立しないが、判定を格下げ先にしか課さないので「格下げしない＝コウ維持」に倒れる＝枠なしのヘッジも同じ理由で安全側）。**裁定には格上げ方向もある**＝tsumego_result_class / _ko_promotion_choice（詰碁の順序で最下位は「相手が無条件で生きる／自石が死ぬ」＝失敗なので、選択手が clean でも役割石で失敗していればコウ経路のほうが上位。root policy 上位を同深さで測り 無条件 > コウ の順に格上げする＝case V2。コウ経路は成立と読めてもコウのまま。通常の手番は root movesOwnership で振るわれ解析0本）。旧実装は同着バンド内だけ検査していたが、コウ殺しのgainは相手石を取り切る実信号でバンドから抜け出す＝case M。親PVは守り方が枠へ手抜きするので使えず、候補自身の1子取りコウは守り方が取り返せないので応手PVにも現れない。ガード外の救済採用手は検査しない＝枠なし盤ではガード内のclean手がスコアだけ良い失敗手でありうる）。**その検査で対抗馬も全部コウ経路だったら、詰碁の順序上それは「正解が候補プールの外にいる」信号**（目数で劣るcleanが居て格下げを断っただけの場合は前提が偽なので脱出しない）なので、root policy の上位（未検査分）を同深さで測り直して無条件の手を探す＝ko_escape_candidates（root の value が壊れている手は PUCT が二度と訪れないので深さでは届かない＝実測 case O の正解は 1800visits でも 12000visits でも v1。value が壊れていても policy は候補を挙げているので探す先は policy。**採用条件は「incumbent を上回る」ではなく「tolerance 超えて下回らない」**＝コウ手のスコアは「コウに勝った前提」なので無条件の正解よりむしろ高く出る）。gainは1本のroot探索のmovesOwnership由来なので浅い候補ほど片側ノイズが出る）に加え、コウは「コウダテがある前提」でコウ勝ち後の局面を評価（ko_win_assumption）。**詰碁の正解順序は結果のクラスで決まり、その順序は解く側の役割で逆転する**（攻め方＝殺す: 無条件死 > コウ > セキ ／ 守り方＝生きる: 無条件生き > **セキ > コウ**。セキが守り方でコウより上なのはコウダテという盤外の条件に頼らないから）。目数はクラス内のタイブレークにすぎないため、通常最善が既に成功している局面ではコウを検査しない。**役割はリージョン境界線の壁の色から読む**（`tsumego_solver_attacks`＝`put_border` は壁を攻め方の色で敷き、リージョンは同じ frame_range。枠ありは実測19ケース全部が単色100%・占有率100%、枠なしは0〜1子なので二重ゲートで分離できる。枠なしは None＝従来の役割非依存の挙動）。役割が分かると「何を見れば成否か」が決まり（攻め方＝相手石が死んだか／守り方＝自石が生きたか＝`tsumego_role_stones`）、成功判定と脱出の採否がそれで動く。**「両方測って厳しいほう」の従来ヘッジは守り方では使えない**＝セキでは相手が生きるのが正常なので必ず失敗側に落ちる（case T: 目数もgainも全リージョン石の検証値も全部コウ>セキと出て、正しい順序が出るのは自石だけ）。ただし**成功判定は目数（ko_success_lead）と ownership（ko_success_ownership）の AND** — 枠の代償地帯が未決着だとスコアが詰碁から切り離され、既存16ケース横断の実測で H/Q の2件が「相手石は生きているのに目数は成功」と出た。枠はキャプチャ時に frame_ko の両方を張って root スコアがバランスの取れた方を自動採用（拮抗時は攻め方コウダテ側）。さらに**手番側（解く側）の本体石が開始時点で死と読まれる枠は詰碁自体を壊しているので捨て、その回だけ枠なしで出題する**（必ず正解手がある詰碁で開始時点から全滅はあり得ない。枠バランスはこの失敗に構造的に不感）。ただし**この読みを浅い trial visits で確定させない**＝生き問題では手番側の石そのものが戦いの対象なので「エンジンがその詰碁を解けたか」を聞くのと同じになり有効な枠まで死と出る。捨てる前に `frame_validity_visits`(1800) を **`wideRootNoise=0`** で読み直し（wRN は着手選択で候補を広げる設定で、生死の裁定では探索が critical line に集中せず読みが二峰性になる＝これが正体。壊れた枠は設定を変えても死のまま）、それでも死なら**捨てる先の枠なし盤も測って比較する**（`frame_over_frameless`。枠なしはリージョン外が丸ごと相手の地になるので安全側のフォールバックではない）。ただし**この安全網は手番側が守り方のときしか役割反転を捕まえられない**（手番側が攻め方なら反転しても本体石が壁と連絡して生きたまま）ので、攻め方推定そのものを極値線に乗る石**全部**で取る（`extremum_stones`。代表点1つだと同座標のタイをリスト順で崩して判定が反転する）。さらに浅い読みの「生」も閾値近傍なら採用前に読み直す（`FRAME_SOLVER_CONFIRM_OWNERSHIP`=0.9。浅い読みは死側にも生側にも振れるので安全網は両側で対称にする）。解析は**精度不変のまま高速化**済み（2026-07-31）: 選択則の独立子局面クエリと枠採否判定クエリは並列発行（KataGo `numAnalysisThreads=4`、クエリ内容・判定順序は直列と同一）、AI黒番の着手後は白の有力応手 top-K（`ponder_replies`=3）の子局面を**実クエリと完全同条件（ownership=True 込み）**で先読みして NN キャッシュを温める（結果は捨てるだけ＝判定影響ゼロ、的中時は次の1800visits解析が0.1〜0.3秒で返る。**ownership なしの先読みは1秒も速くしない**＝KataGo の NN キャッシュは ownerMap の有無を区別する、実測 2026-08-01）。E2E全ケース回帰で正答不変を確認済み）。さらに死活ソルバモード `ai:tsumego_solver`（KataGo 非依存の厳密解＝Rust df-pn。解ける規模のときだけ枠なし出題、解けない/未解決は現行経路へフォールバック）を追加。**証明ストア即答の決め手は df-pn が最初に証明した手＝同格別解の一つに過ぎない**ため、KataGo 本命が同じ gate を証明し visits 比3倍以上（決定性ゲート）のときだけ差し替える。途中の再抽出は region 外接矩形の hint 必須＋「生存 target を region が覆う」サニティガード付き（hint なし閉包は乱れた盤でデタラメな小問題に「成功」して誤答する）。永続キャッシュのキーは再抽出後の実際に解いた問題で引く（2026-08-01 GUI 誤答2件の修正＝spec 追記3）

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
- **`request_analysis` に `next_move` を渡すと ownership が強制 OFF になる**: `engine.py` の `ownership = ... and not next_move` / `"includeOwnership": ownership and not next_move` で、呼び出し側が明示的に `ownership=True` を渡しても無効化される。ownership が要る子局面は、使い捨ての複製ゲームで実ノードを作って撃つ（`ai.tsumego_simulation_game` / `Game._region_prefetch_sim`）
- **KataGo の NN キャッシュは ownerMap の有無を区別する**: ownership なしで温めたエントリは ownership 付きクエリで全ミスになる（実測 2026-08-01: ownership なしで先読みした直後の実クエリ 2.70秒＝コールド 2.69秒と同一、ownership を揃えると 0.10秒）。キャッシュ温め目的のクエリは実クエリと ownership を必ず揃えること

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
    tsumego_problem.py   -- 死活ソルバの問題抽出（region閉包・型判定。KataGo/Kivy非依存）
    tsumego_solver/      -- 死活ソルバ本体（model/board/reference=Python参照実装、native=Rustカーネルctypesラッパ+DLL）
    tsumego_solver_api.py -- ソルバセッション（§9.1照会プロトコル・コウ禁回避・再抽出・投機・永続キャッシュ）
    ...               -- utils.py, lang.py, contribute_engine.py, tsumego_frame.py 等
  gui/                -- Kivy GUIウィジェット
native/tsumego/       -- 死活ソルバの Rust カーネル（DFS+df-pn。ビルド: cargo build --release --target x86_64-pc-windows-gnu → katrain/core/tsumego_solver/katrain_tsumego.dll へコピー）
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
- **KataGo の run 間分散を同一プロセスの再クエリで測らない** — 探索木が再利用されて 0.2 秒で返るため独立サンプルにならない（実測 2026-07-30 case N: 1プロセス内では +0.57/+0.76/+0.71 と安定して見えるが、engine 起動を挟むと同一局面・同一 visits で −0.95〜+0.95 の二峰性だった）。分散を根拠に閾値を決めるなら必ずプロセスを分けて測る。**所要時間の A/B も同じ**（E2E の run1 はエンジン起動〜37秒込み、run2 以降は NN キャッシュが効いて 0.2 秒級なので、run1 と run2/3 を並べて比べない）
- **詰碁で「root に読まれなかった手」を visits で救おうとしない** — root の value 推定が壊れている手は PUCT が二度と訪れないので、深さを積んでも visit 配分は変わらない（実測 2026-07-31 case O: 正解 A11 は root 1800visits でも **12000visits でも v1 のまま**。1visit の評価は「+28.74目損・相手は生き」だが、同じ子局面を独立に 1800visits で解析すると「+11.53目・相手10子すべて全滅」で **value が約29目ずれている**）。value が壊れていても **policy は候補を正しく挙げている**（A11 は prior 5位で 2/2 run 固定、下限手との間に10倍の崖）ので、漏れた正解を探す先は visits ではなく policy。**候補の pointsLost・gain・ownership が「その手が悪い」根拠になるのは、その手に visits が付いているときだけ**（切り分けは `child_depth_probe.py`）
- **詰碁で「成功しているか」をスコアだけで判定しない** — 枠は「攻め方が成功したら5目勝ち」に代償地帯を調整する設計だが、その代償地帯が未確定のまま残るとスコアが詰碁の成否から切り離される（実測 2026-07-31 case Q: 相手石12子すべて生存＝−0.99/子 なのに手番側 +10.45目。**全盤 20000visits の最善手が詰碁と無関係な枠の充填部 B9 v17448** だった）。枠なし盤ではさらに露骨で case H は +27.69目・相手石 −0.15/子、スコアの絶対値は ±60〜80 まで暴れる。既存16ケース横断では成功局面が +0.94〜+1.00・失敗局面が −0.15〜−1.00 で、**ownership なら 1.09 の空白で分離できる**（`ko_success_ownership`）。なお**どちらの詰碁か（殺す/生きる）は選択則に渡ってきていない**ので、自石・相手石の両方を測って厳しいほうを採る
- **詰碁のクラス裁定（無条件 > コウ）に目数差を覆させない** — 「無条件」は「攻めないので何も起きず自明に clean」でも成立するので、**答えがコウの詰碁では格下げが正解を無関係な手に差し替える**（実測 2026-07-31 case R・13路上辺枠なし: 正解 G13=コウ pt+0.03 v1345 を、詰碁と無関係な D8=clean pt+0.55 v288 に格下げして誤答。コウ経路の**検出自体は正しかった**）。`_ko_escape_choice` と同じ ownership 検算を格下げにも課す案は**効かない** — 答えがコウなら ply1 で成否が決着しないので、同深さ800visits の全リージョン石で正解 G13 +0.86/+0.97 < 誤答 D8 +1.32/+2.34 と**誤答のほうが高く**出る（相手石は全候補 −0.55〜−0.72＝どの手でも相手は生きている）。符号が一貫していたのは目数だけで、格下げが正しい4ケースは格下げ先が必ず優る（K −0.05 / L −0.11 / M −0.57 / P −0.03）のに case R は +0.52 劣る（切り分けは `class_screen_probe.py`）
- **その目数バンドで「非解への格下げ」を全部塞げたと思わない** — バンドが止められるのは**非解が目数で劣る**形（case R）だけで、**非解が目数でむしろ優る**局面は素通りする（実測 2026-07-31 case V・13路右上枠あり・黒は攻め方: 正解 L12=コウ/最終セキ pt−0.29 を、白が無条件で生きる K10=clean pt**−0.33**＝0.04 良い＝バンド内、に格下げして誤答。枠・選択則・コウ検出はどれも正しく、`select_tsumego_move` 単体は L12 を選んでいた）。**格下げ先だけを絶対判定する**（`tsumego_declass_confirmed`＝1子平均 >= `ko_success_ownership`。case R の失敗は全リージョン石を**両者の比較**に使ったことで、格下げ先の成否だけを見る絶対判定なら K C13 +0.99 / L J6 +0.99 / M K1 +0.98 / P J1 +0.99 と case V の K10 −1.00 が約 2.0 空いて分離できる）。答えがコウの詰碁では正解も ply1 では成立しない（case V の L12 も −1.00）が、判定を格下げ先にしか課さないので「格下げしない＝コウを維持する」に倒れて安全側に働く
- **役割不明（枠なし）を「確かめられないから確かめない」に倒してはいけない** — 上の格下げ確認は当初 `solver_attacks is None` で丸ごとスキップしていた（case R は全リージョン石の**両者比較**で分離できなかったので、役割不明では判定材料が無いと考えた）。**両者比較が効かないことは、格下げ先だけの絶対判定も効かないことを意味しない**（実測 2026-08-01 case W・13路右下**枠なし**・黒は守り方: 正解 H1=コウ→白G1→黒K1 で黒生き pt+2.20 を、黒が無条件死する J1=clean pt**+1.94＝目数最善**、に格下げして誤答＝バンドは構造的に無力。同深さ800visits の自石7子は H1 **+0.51/+0.35** vs J1 **−0.22/−0.21**、相手石9子は −0.83 vs −0.92）。役割不明時の尺度は既存の `tsumego_success_ownership`（自石・相手石の1子平均の**小さいほう**）で、外し方が「格下げしない＝コウを維持」に倒れるので枠なしでも安全側に働く。同じ理由で**格上げ側（`_ko_promotion_choice`）は今も枠なしで no-op** ＝ 枠なし盤で「選択手が clean かつ失敗、正解がコウ」の局面は未対処（case V2 の枠なし版が出たらここ）
- **クラス裁定を格下げ方向だけで考えない** — 詰碁の順序で最下位なのは「相手が無条件で生きる／自石が無条件で死ぬ」＝**失敗**で、成立していない clean 手はコウ手の**下**にいる。格下げ（コウ→無条件）しか無いと、選択手が clean で失敗している局面で機構が丸ごと沈黙する（実測 2026-07-31 case V2・case V の続き: 選択手 K10 も対抗馬 L11 も L13 も同深さ800visits で **-0.94〜-1.00/子＝白が生きる**のに、正解 N13＝コウは pt+7.97・v17 で目数ガード（best+2.0）の外。目数・gain・ownership のどれも正解を指さず、分離できるのはクラスだけ＝N13 だけが「応手 L11 の PV がコウ形に到達」2/2）。**選択手が clean かつ役割石の絶対判定で失敗しているなら root policy 上位を測って格上げする**（`_ko_promotion_choice`。prior は K10 .196 / **N13 .0133** / 残り .00009＝NN下限なので policy には出ている）。誤爆しないのは、枠あり8ケースの正解 clean 手が全部 ply1・800visits で成立している（+0.98〜+1.00）から＝それらの手番では root movesOwnership で振るわれて解析0本
- **詰碁のクラス順序を「無条件 > コウ > セキ」で固定しない** — それは**攻め方の順序**で、守り方は 無条件生き > **セキ > コウ**（コウはコウダテという盤外条件に依存するので、確実に助かるセキより下）。守り方のセキは「地0目・相手も生きる」なので、選択則が使うスカラー（pointsLost・gain・同深さ検証値）は**全部**コウ勝ちを上に並べる（実測 2026-07-31 case T・13路下辺: 正解 L1=セキ vs 誤答 J2=コウ生きで root 目数 +4.30 vs -0.34／gain -3.83 vs +0.20／全リージョン石の同深さ検証 -19.79 vs -16.66 と**三つとも逆**。正しく出るのは**自石だけ**の +1.00 vs +0.99/子）。**目数ではクラスの順序を表現できない**ので、役割を読んで「成否を担っている石」だけで測る（`tsumego_solver_attacks` / `tsumego_role_stones`）。役割が読めない枠なし盤は従来どおり役割非依存で動かす
- **クラス裁定を「pool が2手以上か」で走らせない** — それは別々の2状況を混同する。(a) 選択手が目数ガード外（救済採用）＝検査しない（case F2）と、(b) 選択手はガード内だが対抗馬が0手＝**検査すべき**（「到達できる手が全部コウ」が最も純粋に成立する形で、コウ脱出のトリガーそのもの）。旧実装は両方落としていたため、root が1手に visits を集中させて eligible が1手に潰れるとクラス裁定も脱出も丸ごと no-op になっていた（実測 case T: eligible=[J2] のみ。コウ検出自体は `ko_route_probe.py` 1/1 で正しく J2=KO / 正解 L1=clean と出ていたのに、機構が走らなかっただけ）。判定は `tsumego_class_screen_applies`（選択手がガード内か）
- **「clean な対抗馬が目数で優る＝答えはコウ」を役割不明のまま適用しない** — これも攻め方の推論（成功＝相手を殺す＝目数が増える、が前提）。守り方の正解がセキなら clean のまま目数で必ず劣るので、正解を「詰碁と無関係な手」と誤認して脱出を止める（実測 case T: 対抗馬 N4 がコウ検出の揺れで clean と読まれた run だけこの分岐に落ち、4run 中1回だけ誤答が残った）。**役割が読めるなら脱出を走らせてよい**（`tsumego_ko_escape_applies`）＝採否が役割ごとの石の同深さ ownership で決まり、答えが本当にコウなら clean 候補は検証で落ちる（case T 自石12子: 正解 +11.97 vs 失敗する clean 手 -11.93）。case R がこの安全弁を使えなかったのは枠なしで役割が読めなかったため
- **gain 覆しの同深さ検証を「選択手1手だけ」で走らせない** — gain 1位がノイズ手だった run で2位以下の本物が検証の機会を失い、incumbent の目数最善に巻き戻る（実測 2026-08-01 case W・GUI 実戦で再現: 浅い L1(v95) の visit比が深さゲート境界 0.5 を run ごとにまたぎ〈0.43〜0.58〉、通った run では gain 首位が正解 H1 から L1 に入れ替わり、L1 却下 → **H1 は一度も測られず** J1 で誤答。H1 の検証値 -10.4〜-11.2 は J1 -12.5 を margin 0.3 超えて上回るので、測られてさえいれば必ず採る）。**救済側が case F2 で学んだのとまったく同じ構図**（`TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES`=3）で、score_best 検証側だけがトップ1指名で残っていた＝`tsumego_score_best_challengers`（選択手＋gain 降順の contenders 最大3手）
- **同深さ検証を「筋の通った測り方」だけを根拠に枠内へ縛らない（`untilDepth`）** — `_verified_choice` は既定の `untilDepth=1` で撃つので ply2 以降が枠外へ出て、局所の死活が決着しないまま ownership が返る（実測 case W 初手の子局面: untilDepth=1 で 非解 N4 **-8.9** > 正解 H1 -9.0〜-11.1 と**逆**、untilDepth=6 なら H1 **-3.9〜-5.2** > N4 -9.9 と正しい）。case P の PV の罠の ownership 版で理屈は正しいが、**実装すると別のところが壊れる**（実測 2026-08-01 の全ケース 3run: W@0 は H1 3/3 に直るが **W@2 が K1 3/3 → 1/3**。近接候補 L1 の検証値が幅 2.1 でばらつき K1〈幅 0.3〉を抜く）。同深さ検証は D/E/F/G2/H/F2/J/M の校正が全部乗っており margin(0.3/1.0) も untilDepth=1 のスケールで決めてあるので、やるなら margin から再校正が要る＝**REJECT**（spec 追記35）
- **救済経路の誤答を閾値で塞ごうとしない（5案すべて実測で却下済み）** — 実測 2026-08-01 case W（枠なし・正解 H1＝コウで黒生き）で救済が N4（自石 −0.21/子＝黒が死ぬ）を採用する残余が残っており、(1)成立ゲート／(2)`untilDepth=6`／(3)visit比の床／(4)目数の到達幅／(5)検証 visits 増 のどれも**正解側と誤答側のレンジが重なって**分離できない（各案の数値は spec 追記36）。特に (5) は「incumbent のノイズが原因」説を否定する: visits 800→2400 で H1 の値の幅は 3.3 → 0.8 に縮むが **収束先が -11.0 で N4 の -8.9 より下のまま**＝ノイズではなく尺度が逆。(2)+(5) の組合せは case W **初手なら正解が次点と 6.0 差で安定**するのに、**同じ盤の3手目では別の手(J1 -8.5)が正解(K1 -10.3)を上回る**＝全リージョン石の絶対 ownership は「どの手が詰碁を解くか」を表現していない（追記28 の「目数ではクラスの順序を表現できない」と同型）。case I / Q / R と同じ限界枠として扱う
- **救済（`gain_rescue_margin`）の採用に「詰碁が成立しているか」のゲートを掛けない** — 誤答が救済経路から出ていると、成立判定（`ko_success_ownership`）で塞ぎたくなるが、**救済が正しく効くのは「ply1 では成否が決着しない局面」だけ**なので正解のほうが低く出る（実測 2026-08-01、同深さ800visits・各2run のヘッジ値〈自石・相手石の1子平均の小さいほう〉: **採るべき** G2 C13 −0.82 / H N4 **+0.21** / F2 N11 −0.94 / F2 M12 −0.93 ＜ **落とすべき** R@2 D8 −0.50 / W N4 −0.92 ＝レンジが完全に重なる。自石だけでも分離しない＝誤答 D8 の +0.74 が正解4件中3件より高い）。トリガー側の閾値（visit比の床 `TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO`=0.15 / 深さゲート `gain_min_visit_ratio`=0.5）も root 解析の分散がまたぐので分離できない＝**救済経路の誤答は case I / Q と同じエンジン側の限界枠**（実測: case R の3手目 D8 1/4・case W の初手 N4 2/12）
- **詰碁の誤答を選択則のせいにする前に「対抗馬が居たか」を見る** — gain・同深さ検証・救済・コウ経路検査・コウ脱出はすべて「目数ガード内の候補を比べる」機構なので、`min_visits` を通った候補が**1手だけ**になると揃って不発になり、戦略は KataGo の最善手をそのまま返しているだけになる（実測 2026-07-31 case Q: 1800visits 中 1764 が H13 に集中し eligible は H13 のみ。`Final decision: … 候補37手` は37手から選んだように読めるが実際は無選択だった）。debug ログの `対抗馬なし:` 行と `候補N手（うち対抗馬M手）` で判別する
- **同深さ検証の差を「解析条件を変えても残るか」で検算する** — untilDepth や visits を変えると向きが変わる差は実信号ではない（実測 case Q: 正解候補 N9 と誤答 H13 の相手石 ownership 差は untilDepth=1/1800visits で 2.2、8000visits で 1.26、`_region_child_verdict` と同じ untilDepth=6 では 0.2 の誤差内に消えた）。**準備手（それ単体では何も起きず価値が数手先に出る手）が正解の詰碁は、KataGo の value がその手を「負け」と読むため（case Q: 全盤 20000visits で N9 は winrate 0.450・v3）policy 上位を測り直しても浮かばず、選択則・枠・深掘りのどれでも救えない**（case I と同じ未対処の既知限界。エンジン更新時に再評価）
- **コウ脱出の採否を incumbent との相対比較だけで決めない** — 相対条件（tolerance 超えて下回らない）は **incumbent 自身が失敗している局面で退化する**。全候補が同じくらい失敗していれば全員が合格になり、ノイズ幅の差で1手が「最良」に選ばれて選択手が捨てられる（実測 2026-07-31 case F: 選択手 N8 −9.72 に対し policy 上位 J11 −9.82 / J10 −9.86 / N11 −9.90 / M12 −9.89 が全部 tolerance 0.5 の内側に並び、**0.08 差**で J11 が採用された。同深さ800visits の1子平均は全員 **−0.97〜−0.99＝どれも詰碁を解いていない**、目数も −30目）。脱出は「無条件で成立する手を探す」機構なので、**先に「その手で詰碁が成立しているか」を役割石の1子平均 ownership で絶対判定する**（`tsumego_ko_escape_succeeds`、閾値は成功判定と同じ `ko_success_ownership`=0.5）。実測の分離は桁違い（採るべき +0.94〜+1.00/子 vs 落とすべき −0.97〜−1.00/子 で約 1.9 の空白）
- **詰碁の誤答調査で「その盤がそもそも成立しているか」を先に確かめる** — case F は `frame_destroys_problem`（追記18）導入前に保存された**壊れた枠の盤**で、黒は守り方（自石10子）なのに開始時点から自石 −0.97/子・相手石 −1.00/子・−30目＝**どの手を打っても解けない**。README の「正解 N8」は当時の選択則（gain 深さゲート／同深さ検証）の回帰値であって、解ける問題の正解ではない。`class_screen_probe.py` の 自石/相手石 1子平均を見れば1本で分かる
- **コウ脱出（および今後のクラス裁定）の採用条件を「incumbent を上回ること」にしない** — コウで殺す手のスコアは「コウに勝った前提」で出るので無条件の正解より**むしろ高い**（実測 case O 同深さ800visits: コウ B12 +41.95 > 正解 A11 +41.85）。既存の `tsumego_override_confirmed`（margin 超えで上回る）を流用すると正解が落ちる。順序を決めるのはクラス（無条件 > コウ）で、スコアは「詰碁が成立しているか」の確認にだけ使う（失敗手は +18.5 まで落ちるので 23 点差で分離できる）
- **コウの検出を「PV がそのコウを打つか」だけに頼らない** — リージョン解析は `untilDepth` で両者を枠内に縛るので**守り方はコウダテを打てない**。するとコウを仕掛けることは守り方の純損になり、KataGo はそれを正しく「打つ価値なし」と読む。ところが詰碁の裁定は逆で、攻め方の「コウで殺す」は「無条件に殺す」より下のクラスに落ちる＝**コウが問題になる局面ほどエンジンはそのコウを打たず、証拠が消える**（実測 2026-07-31 case U: 黒 A3 に対し白 C1 でコウを作れるのに、C1 は visits比 **0.01**（v7/617）で lead も黒+8.99＝白の損と評価され、C1 自身の PV `C1,A4,D6,E6,D7` にコウ手 E1 が無い。**応手を比 0.00 まで全部歩いても検出 0/5 run**）。「守り方がコウ取りを**打てる状態**になったか」で見れば探索の好みに依存せず 5/5 run で立つ（`tsumego_defender_ko_points`）。ただし**その証拠は PV より弱いので歩く深さを短く切る**（`TSUMEGO_KO_AVAIL_PLIES`=5。ply7 まで数えると case G2 の正解 C13・case R の C8 の偶発コウを拾って正解を格下げ・脱出に流す）。**候補手より前から打てたコウは数えない**（局面の性質であって候補の性質ではない＝全候補が一律コウ経路になり裁定が候補を区別できなくなる。case T の L1 / F2 の N9 / Q の M13 がこれで、従来判定が別途拾っている）
- **詰碁の誤答を「その手の後の応手」で直そうとする前に、手順前後を疑う** — 実測 case U は白 C1 の時点で黒 D1 が既にアタリ（呼吸点は E1 のみ）で、**そこから先は黒が何を打ってもコウを避けられない**。3手目の候補 A1 が「clean」と出るのは PV を歩いただけの偽陰性で、正解 C1 を初手に打って D1 を {C1,D1} の2子連結にしておく（＝白 E1 が2子取りになりコウにならない）以外に道が無い。**誤答局面を1手ずつ遡って「まだ正解が残っているか」を測る**（`ko_route_probe.py` の相手石 ownership とクラスを両方見る）
- **PV の内容を証拠に使う解析を `untilDepth=1` のまま撃たない** — リージョン解析の `avoidMoves untilDepth=1` が縛るのは root の着手選択だけで、**ply2 以降の PV は枠の外へ自由に出ていける**。詰碁を読み切った KataGo にとって「負けている側の局所の抵抗」は枠の一点と同値なので、守り方の PV は肝心のコウを打たずに枠へ手抜きし、構造検出の証拠そのものが消える（実測 2026-07-31 case P: 黒 H1 の子局面で白の最善応手 J1 は v59〜99 で単独首位と安定しているのに、その PV が `J1,L2,`**`J12`** と ply3 で枠外へ。コウ検出はプロセスを分けた 4 trial 中 **1回**だけで、実戦はその外れを引いて誤答した）。**PV を証拠にするなら歩く深さぶん枠に縛る**（`TSUMEGO_KO_REGION_UNTIL_DEPTH` = `TSUMEGO_TIE_KO_PLIES`。同 4 trial で 4/4 検出・無条件の正解は 4/4 clean のまま）。同じ失敗は「親局面の PV は枠へ手抜きするので使えない」（case K）で一度踏んでおり、子局面へ移しても**深さ1の強制では ply1 しか局所化できていなかった**
- **応手の並びを証拠に使う検査にも `wideRootNoise` を効かせない** — 上の死活裁定と同じ罠。root の Dirichlet ノイズは run ごとに引き直され、しかも1回の探索の間ずっと乗るので **visits を増やしても消えない**揺れを「守り方の応手にどう visits が配られるか」に作る（実測 2026-07-31 case M・コウ経路検査の子局面: wRN=0.04 で コウ仕掛け K1 の比が 0.44〜0.88 とばらつき本番フロー 3/6 で検出漏れ → **wRN=0 で 0.15 が 4/4 不動**、M4 v663/K1 v100/残り全部 v1）。旧 0.5 ゲートは「ノイズが本物のコウ応手の取り分を水増ししてくれた時だけ当たる」偶然の産物で、visits を増やすほど真値に収束して外れやすくなる。**閾値を動かす前に全ケースで両側を測る**（実測: 検出すべき最小 0.09 ＜ clean のままにすべき最大 0.16 で逆転＝単一閾値では分離できない。選択手だけ敏感側 0.05、格下げ先は保守側 0.5 で分ける。切り分けは `ko_reply_ratio_probe.py`）
- **死活の裁定クエリに `wideRootNoise` を効かせない** — wRN は着手選択で候補リストを広げるための設定で、「この石は生きているか」を聞く裁定では root の探索が critical line に集中できず ownership が決着しない（実測 case N: wRN=0.04 だと 1800visits で +0.95〜−0.95 の二峰性・6000visits でようやく安定＝1本 4.8〜8.4秒、wRN=0 なら 1800visits で +0.96〜+0.97 に安定＝1本 1.7秒）。**深さで殴る前に、その問いに不要なノイズが入っていないか疑う**
- **枠の採否判定（`frame_destroys_problem`）を trial visits の読みで確定させない** — 生き問題は「解けたら生き」なので浅い読みでは必ず死側に倒れる（実測 case N の有効な枠: 400 で −0.69〜−0.98/子）。捨てた先の枠なし盤は root −75目・手番側コア −0.75/子 で**枠より激しく詰碁が消えている**（gain も目数も「相手の外側の石を攻める手」を評価し、正解は選択則のどの経路でも救えない）
- **枠の妥当性判定に壁石を混ぜない** — 壁は自明に生きているので判定が埋もれる（実測 case D: 壁込み +25.00/25 で常に正常判定、本体石だけなら +8.00/8）
- **枠の攻め方推定（`guess_black_to_attack`）の当否を `frame_destroys_problem` で確かめない** — この判定は「手番側の本体石が生きているか」なので、**手番側が攻め方だと役割が反転しても石が壁と連絡して生きたまま**になり安全網に掛からない（実測 2026-07-31 case S: 反転枠の手番側コアは 400visits で +0.4977〜+0.65/子 と閾値 0.5 をまたぎ、生と出た run はそのまま出題されて詰碁と無関係な H12 で誤答。反転枠は代償地帯を攻め方に渡すので手番側が +21目リードし、目数も gain も詰碁を測らなくなる）。逆向き（「solver_core が最大の枠を採る」）も不可で、**生きる詰碁では誤った役割のほうが高く出る**（case M: 誤 +0.99 vs 正 +0.72）。バランス距離も S/M とも誤った役割が最良を出す（2.5 / 2.7）＝**役割は測って選べないので推定そのものを正す**（`extremum_stones`＝極値線の石を全部足す。代表点1つだと同座標のタイを row-major 順で崩し、両色が並ぶ辺で判定が反転する。case S の左辺は H11(白)/H10(黒) で -1(誤) vs +42(正)）。切り分けは `frame_role_ab.py`
- **極値票の役割反転を「集計の改良」や「測定」で直そうとしない** — 極値票の前提「外側の色＝攻め方」は、**殺される側が2線を這って盤端の極値線を占める辺の詰碁で構造的に偽**になる（実測 2026-08-01 case X・13路左辺: B列の白5子で -97、原問題の白い外郭石 C10/F3 が残り2辺も取り**票 -68 で確定的に反転**＝case S のタイ崩れ±1と違い集計では救えない。反転枠は守り方判定→「既に成功」で全機構が素通り→C2 誤答、正解 A4 は候補にも入らない）。測定で選ぶ案は**3測定族すべて実測却下**（spec 追記37）: (1) 生盤 ownership は殺す問題の白が死なない（X 白+0.47。生盤は「外側は攻め方の勢力圏」という詰碁の約束事を表現しない。case G は黒-0.67/白+0.92 で**逆を確信**）、(2) 枠あり測定は追記27 のとおり、(3) 手番フリップは**誤役割の枠でも delta +1.8〜2.0**（枠の壁に挟まれた群はどれも手番依存になる＝手番依存性は枠の性質であって問題の性質ではない。正役割で flat の例もある: V +0.00/Q +0.02）。役割は問題の**意図**で、確実に知っているのは問題文を読んでいるユーザーだけ＝**役割指定ホットキー**（`hotkey_attack`/`hotkey_defend`→`black_to_attack_p` 貫通）で明示してもらう。切り分けは `raw_role_probe.py` / `flip_role_probe.py`
- **浅い読み（`frame_ko_trial_visits`）の結論を片側だけで確定させない** — 浅い読みは死側にも生側にも振れる。「死と出たら読み直す／生と出たら即採用」は非対称で、閾値近傍の偽陽性がそのまま出題される（実測 case S: 同じ枠・同じ 400visits が +0.4977/子 と +0.65/子 の両方を出し、1800visits では +0.46/子 で壊れ＝run ごとに枠の採否が入れ替わっていた）。閾値近傍の「生」は `FRAME_SOLVER_CONFIRM_OWNERSHIP`(0.9) 未満として確認の読み直しにかける（自明に生きている枠は +0.96〜+1.00 に張り付くので追加コストは乗らない）
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
- **独立した追加解析クエリは1本ずつ待たない**: KataGo は `analysis_config.cfg` の `numAnalysisThreads=4` で4クエリを並列処理できる。詰碁の子局面解析は `_start_region_root` / `_wait_region_roots`（`ai.py`）で全部発行してからまとめて待つ形になっているので、解析を追加するときもこの形に合わせる（1本ずつ `_analyze_region_root` を呼ぶループに戻さない）
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

**詰碁ソルバの回帰（KataGo 不要・数分）**: ソルバ・問題抽出を触ったら回す。単体は `pytest tests/test_tsumego_solver.py tests/test_tsumego_solver_strategy.py`、実ケースは
```bash
python docs/superpowers/specs/calibration-data/tsumego/solver_p1_suite.py --native            # 全ケース
python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py --solver W I Q            # 同じ入口から
```
Rust カーネルを触ったらビルド→DLLコピー→`diff_native`系の差分（Reference と同一結果）を確認。設計と実装の記録は `docs/superpowers/specs/2026-08-01-tsumego-solver-design.md`（追記1）。

**詰碁の回帰（E2E）**: 選択則・枠判定・解析まわりを触ったら必ず回す（`select_tsumego_move` 単体の A/B では後段の検証・救済・クラス裁定を通らない）:
```bash
python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py            # 回帰点だけ（既定・約20分）
python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py --full     # 正解手順の全黒番
python docs/superpowers/specs/calibration-data/tsumego/e2e_suite.py V V2 W     # ケースを絞る
```
ケース表（SGF・region・**正解手順 `line`**・**回帰点 `expect`**）は `e2e_suite.py` の `CASES` が持ち、各ケースを**別プロセスで**回す（同一プロセスの再クエリは NN キャッシュで独立サンプルにならない）。**SGF の本譜は「実際に打たれた手順」＝誤答を含む線**で、正解が分岐（variation）側にしかないケースがある（D/F/L/O/T/U）ので、局面は `generate_move_e2e.py --line=<正解手順>` で root から打ち直す。単発で回すときは `generate_move_e2e.py <sgf> <moves_csv> <region> 3 [--line=...] [--debug]`（`--debug` で戦略の判定ログが出る＝**外れた run でどの経路が分岐したかはこれが無いと分からない**）。バックグラウンド実行してその間に他の作業を進める

## 現在のパラメータ値

`.claude/rules/ai-parameters.md` に全戦略のパラメータテーブルを格納（`ai.py` 編集時に自動ロード）。
