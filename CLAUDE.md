# CLAUDE.md

## 概要

KaTrain v1.17.1.1 修正版。囲碁AI学習ツール。

- 上流リポジトリ: https://github.com/sanderland/katrain
- ランタイム設定: `C:\Users\iwaki\.katrain\`

主な改修は3系統。**着手する前に該当 rules を Read すること**（`.claude/rules/` は自動ロードされない＝「開発ワークフロー」節参照）:

| 系統 | 内容 | 触る前に読む |
|---|---|---|
| Human-like AI 戦略 | 悪手フィルタに加え、力戦派 / 攻城 / 狩猟 / 一致率低減 / 持碁 / 一致率追随（9路）/ 難解（9・13・19路） | `.claude/rules/ai-strategies.md`（設計と実測）<br>`.claude/rules/ai-parameters.md`（全パラメータ値）<br>`.claude/rules/ai-humanstyle.md`（フィルタ実装） |
| 詰碁 | 画面キャプチャ→盤面認識→枠→着手選択 `ai:tsumego`→死活ソルバ（Rust df-pn）→回答帳 | `.claude/rules/tsumego.md`（設計と落とし穴）<br>`.claude/rules/tsumego-parameters.md`（パラメータ値） |
| 盤面監視 | `board_watch.py`: BlueStacks 上の対局アプリの着手を検出して人間側の手として片方向注入（トグル `ctrl+alt+d`） | `docs/superpowers/specs/2026-08-18-board-watch-design.md` |

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
    ai.py             -- AI着手生成（改修クラス: HumanStyle / Fighting / Siege / Hunt / HuntDivergence / Divergence /
                         Jigo / Jigo9 / Parity9 / Enigma9 / Enigma13 / Enigma19 / TsumegoOwnership / TsumegoSolver）
    constants.py      -- 定数、AI設定ウィジェット定義（AI_OPTION_VALUES）
    engine.py         -- KataGoエンジン管理
    game.py           -- ゲーム状態管理
    game_node.py      -- 棋譜ノード
    sgf_parser.py     -- SGFパーサ
    base_katrain.py   -- 設定管理・アプリベース
    board_watch.py    -- 対局盤面の監視モード（アプリ側の着手を検出し人間側の手として注入。トグル ctrl+alt+d）
    tsumego_capture.py   -- 詰碁アプリ画面キャプチャ→盤面認識→SGF化（Kivy非依存、CLI: python -m katrain.core.tsumego_capture）
    tsumego_problem.py   -- 死活ソルバの問題抽出（region閉包・型判定。KataGo/Kivy非依存）
    tsumego_solver/      -- 死活ソルバ本体（model/board/reference=Python参照実装、native=Rustカーネルctypesラッパ+DLL）
    tsumego_solver_api.py -- ソルバセッション（§9.1照会プロトコル・コウ禁回避・再抽出・投機・永続キャッシュ）
    tsumego_answer_book.py -- 回答帳（正解手順の記録と、盤の8対称キーで一致する再出題の0秒再生）
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

**設計・実測の一次記録**: `docs/superpowers/specs/` に全53本。索引は `docs/superpowers/specs/INDEX.md`（実装済み／REJECT／未実装の別つき）。**大きい spec は全読みせず Grep で該当節だけ引く**（最大は詰碁の ownership 199KB / solver 150KB）

**校正・ベースラインデータ**: `docs/superpowers/specs/calibration-data/<機能名>/` のサブディレクトリに機能別で格納。命名規則: `<モード>-vs-<相手>-<YYYYMMDD>[-<色>].sgf`、結果は `<機能>-results-<YYYYMMDD>.md`。既存 SGF は `clean_sgf_main_line.py` で main-line 化してから使う

**ランタイム設定ファイル**（`C:\Users\iwaki\.katrain\`）:
- `config.json` — KaTrain全体の設定（エンジンパス、モデルパス、AI設定等）
- `analysis_config.cfg` — **エンジンには参照されていない**（実測 2026-08-03）。`engine.py:140` の `cfg = find_package_resource(config["config"])` は `config.json` の `engine.config`（値=`"katrain/KataGo/analysis_config.cfg"`）をパッケージ相対パスとして解決するため、実際にエンジンへ渡されるのは**パッケージ同梱** `katrain/KataGo/analysis_config.cfg`（git管理・実効 `numAnalysisThreads=12`）。`-override-config` で上書きされるのは `homeDataDir` キーのみ。このファイルを編集しても効果がない
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

**ログファイル**（`C:\Users\iwaki\.katrain\logs\`）: 詰碁は**1問1ファイル**（`tsumego_<日付>_<時刻>.log`）。キャプチャの先頭で開くので、認識盤面（黒/白の GTP 座標）・抽出・出題前の検算・枠の採否・各手の判定が1ファイルに揃う＝**不具合報告はこのファイルを見れば再現できる**（ターミナルからコピーする必要はない）。`debug_level` 0 でも作られる（0 は INFO 行のみ、1 でエンジンのクエリまで）。対局は従来どおり `game_<日付>_<時刻>.log`（20手未満は無効試合として削除）。保持数は種別ごとに独立（詰碁30本・対局10本＝`base_katrain.KaTrainBase.LOG_KINDS`）で古い順に自動削除。ただし**回答帳に記録した問題のログは保護されて自動削除されない**（`keep_current_log`＝`<ログ名>.log.keep` マーカーを隣に置き、ローテーションは保護済みを本数からも除外する。回答帳には誤答した問題だけでなく「解析が長かったので次から即答させたい正解済みの問題」も入るので、保護は正解／誤答で区別せず記録した全問に掛かる）。ログ側には**回答帳キー**（`tsumego_capture: 回答帳キー <sha1>`）と komi/ko/margin/black_to_attack/枠なし指定が出るので、`~/.katrain/tsumego_answers.json` の entry（`canonical_black`/`canonical_white`/`lines`）と join して「回答帳なしで出題し直し、記録手順と突き合わせる」オフライン検証ができる。spec 追記11・回答帳 spec 追記3

保護ログは捨てられない（どれも詰碁モードの改善に使う）ので、**30日より古い詰碁ログは `logs/archive/tsumego_YYYYMM.zip` へ自動で畳まれる**（`katrain/core/log_archive.py`。起動後の最初のログ生成時に1セッション1回・別スレッド。`.keep` も同じ zip に入り、zip に入ったことを確かめてからでないと元を消さない）。畳んだあとは Grep ツールで直接引けないので、検索は `python tools/grep_tsumego_logs.py "<正規表現>"`（平文とアーカイブを横断・出力は `<場所>:<行番号>:<行>`）。`--extract <名前>` で平文に戻し、`--archive-now --days N` で手動実行できる。放置時の増加率は実測 2026-08-21 で 11日599本・130MB＝年 4GB

**戦略デバッグCLI**: 対局不要で任意の局面の戦略意思決定を再現・確認（KataGo起動あり、約30秒）:
```bash
python -m katrain_debug --sgf FILE --move N --strategy hunt [--settings key=val ...] [--output text|json]
```
対応戦略: `human`, `pro`, `fighting`, `siege`, `hunt`, `hunt_diverge`, `diverge` 等26種。`--output json` でパース可能な構造化出力。

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
- 改修はほぼ `katrain/core/ai.py` の戦略クラスに集中（`HumanStyleStrategy` / `FightingStrategy` / `SiegeStrategy` / `HuntStrategy` / `HuntDivergenceStrategy` / `DivergenceStrategy` / `JigoStrategy` / `Jigo9Strategy` / `Parity9Strategy` / `Enigma9Strategy`（+13/19） / `TsumegoOwnershipStrategy` / `TsumegoSolverStrategy`）

## やってはいけないこと

- **改修の効果を「以前失敗していたケース」だけで測らない** — それは**結果で選別した標本**で、手を入れ替える変更なら何であれ一定割合が「回復」する。必ず**以前成功していた側の破損率**も測り、差引で判断すること（実測 2026-08-10: 詰碁で「拮抗手番の読みを 1800→5000visits に深くする」案は、誤答手順145本のうち**22本＝15.2%が回復**したので採用しかけたが、**正解手順60本に同じ設定を掛けると9本＝15.0%が壊れた**＝ただのシャッフル。420手順に外挿して 回復+27.5 / 破損−35.9 ＝ **差引 −8.3手順**、しかも所要時間は倍。run 間ノイズ 3.3% と比べて「4倍だから本物」という推論は**回復側にしか適用していなかった**のが誤り）。**解析条件を変える改修は特にこれを踏みやすい**（手の入れ替えが盤面全体に及ぶ）。逆に、解析を一切変えず採用判断だけを狭める改修（例 `promotion_dominant_requires_success`）は、発火しない手番がビット単位で同一なのでこのシャッフルが構造的に起きない
- **A/B を設計したら、着手する前に「両アームが本当に違う設定で走るか」を確かめる** — 計測ハーネスが既に片方の設定で走っていると、A/B は**両アーム同一の null 実験**になり、出た答えが「差分なし」でも「効果あり」でもどちらも情報量ゼロになる（実測 2026-08-16・spec §0.8）。踏んだ例が2つある。(1) **presolve の ROI 競合**（`__main__.py:1551` のスレッド起動が `:1572` の ROI 設定より前）を直す A/B を計画したが、`answer_book_replay.py` の `build_game`〈`:219` で ROI を設定しセッションは入れない〉も `generate_move_e2e.py:62` も戦略に `build_session_from_game` を呼ばせるので**すでに修正後の hint=ROI 側**で走っていた＝本番だけが hint=閉包 bbox になりうる。(2) **`--no-solver-cache` が部分 no-op**（`:486-487` がローカル settings dict しか書かず、`_solver_settings`〈`ai.py:4803-4810`〉は `katrain.config("tsumego_capture")` を引き直す）で、**出題前検算しか cold にならず手番ごとの solve は永続キャッシュ1673件を引いたまま**だった＝「cold で測った」と記録した過去の実験は手番側が warm。**フラグが効いていることを、フラグを読む側のコードで確認してから測ること**（同じ取りこぼしは `--capture-settings` 側で 2026-08-09 に一度直っていたのに、フラグ側に適用されていなかった＝片方だけ直す修正は再発する）
- **診断（ログ・計装）を足す前に、(a) 既存データが同じ問いに答えていないか (b) 答えが分かって初めて取れる行動があるか、を見る** — 両方 No なら実装しない。実測 2026-08-16: 「Rust カーネルの Err 種別（deadline/node/ply）を Python 側ログへ」（spec §0.6-2）は、**`opt-budget.jsonl`〈938行・コミット済み〉が既に答えていた** — cap を 500/1000/1500/3000ms と**6倍振った因果操作**で optimize の中央値経過が 507/1008/1506/3003ms と cap を 1:1 で追い、**Err は deadline** で確定（問題レベル status は7 arm すべて不変＝変化 0/134）。しかも種別が判った後に取れる唯一の行動（`OPT_TIME_MIN_MS` / `solver_time_limit_ms` を緩める）は `fac1edb` が**逆方向に締めて −26%** を取ったばかりで衝突する。**「未追跡だから調べる」は理由にならない**（spec に「未追跡」と書いてあっても、翌日のコミットが決着させていることがある＝起票前に直後のコミットを見る）。なお本環境は `cargo` が WDAC でブロック（`os error 4551`）＝ **DLL を再ビルドできない**ので、`native/tsumego/src/` だけ変更すると git 追跡済み DLL と乖離したままコミットされる
- **ログファイルをReadで全読みしない** — 数百KB〜1MB超あるため、必ずGrepで必要行だけ抽出する
- **中国ルール（area scoring）のパス判定を目数だけで決めない** — area scoring では**ダメを詰めても点数が動かない**（交互に詰める限り差し引きゼロ）ので、「ダメが残っている局面」と「本当の終局」が**どちらも0目差に見える**。実測 2026-08-06（13路・実戦ログ `game_20260806_011214`・手数119）: ダメが13個残り打てる手が41手あるのに `pass_loss=0.10` 目だったため `_AREA_PASS_MARGIN`(0.5) の目数ゲートが強制パスし、`# 終局時はhumanPolicy最上位手を選択（9段はヨセを間違えない）` の分岐へ到達する前に `return` していた。**区別できるのは humanPolicy だけ**（同局面で `humanPolicy(pass)=0.0000`、ダメを詰め切った後は 0.37〜0.75）。目数条件に **humanPolicy がパスを最上位に置いているか**を AND する（`_area_scoring_should_pass`）。自己対局の実測で ply0〜12 にダメを13個すべて詰めてから ply28 で両者パス＝**正常終局する**（humanPolicy に委ねても無限対局にならない）。同じ目数ゲートが HumanStyle / Fighting:human / Siege×2 / Hunt の**5箇所にコピー**されていたので共通純関数に集約済み。**「スコアが動かない＝打つ価値がない」は area scoring では成り立たない**
- **Stage 1（humanSLProfile付き）の`scoreLead`をフィルタ判定に使わない** — バイアスされているため、必ずStage 2のクリーンクエリの値を使う
- **`wideRootNoise=0` で撃ったクエリの moveInfos を「候補の損失」の判定に使わない** — wRN=0 は root の探索を1点に集中させるので、非最善手が浅い visits でしか読まれず**相手の最善応手が見つかっていないぶん打つ側に楽観的**な `scoreLead` を返す（実測 2026-08-08・9路 1000visits: Stage2 は非最善手を 69〜86visits でしか読まず、通常解析〈wRN=0.04・同 visits で 130〜163visits〉と比べて損失が一貫して **1.3〜1.8目小さく**出た。move 14 の F3 は Stage2 で +2.54目→実際は +4.03目）。`PARITY9_MIN_VISITS`(10) のような visit floor は 1visit の蜃気楼しか止められず、**同じ現象が10〜90visits の帯でも起きる**。損失を測るなら候補が広く探索されているクエリ（通常解析 = `cn.candidate_moves`）を使う。そこには `relativePointsLost`（最善手基準・**打つ側視点に符号済み**＝`sign` を掛けてはいけない）・`winrate`・`visits` が揃っており、追加クエリも不要。**root の `scoreLead` の精度が要るクエリと、候補の序列が要るクエリは別物**なので、同じ1本で兼ねようとしない
- **実戦ログから復元した SGF の「最初の着手の色」を AI の手番と読まない** — AI の手番は戦略ログの `depth` の偶奇で決まる（`[Parity9Strategy] Endgame: depth=1,3,5…` の奇数＝1手打たれたあとに着手＝**白番**）。実測 2026-08-08 で2回踏んだ: `--batch --player B` で人間側を評価して「一致率100%・外しゼロ」という無意味な結果を出し、在庫プローブも `range(1,61,2)` で相手側を測って**誤った在庫**（「ヨセ15判断のうち13手に0.5目以内の代替」＝正しくは ≤0.1 で4手）を報告した。ログ→SGF 復元のときは AI の手番を判定して記録すること
- **「その局面クラスに在庫が無い」を n=1 の対局から一般化しない** — 実測 2026-08-08: 校正局（38手で終局）のヨセ4手に安い代替手が無かったことから「9路のヨセに無料の在庫は存在しない」と結論したが、**その碁は本当のヨセに入る前に終わっていた**。60手の実戦で測り直すとヨセ帯に同値手が実在し、ヨセを丸ごとロックしていた設計が一致率の最大のボトルネックだった（31判断中16手＝52%を最善手に固定）。局面クラスの在庫を否定するなら、**そのクラスが十分な手数ある対局**で測る
- **「一致率を下げる」施策の良し悪しを一致率だけで判定しない** — 一致率は**損失を過小評価するほど下がる**ので、壊れた測り方は良いスコアに見える（実測 2026-08-08: 候補プールを通常解析に直したら `ai_top_move` は 52.6%→57.9% と**悪化**したが、実損失は 11.04→5.82目と半減した＝消えた外し1手は「2.54目のつもりで 4.03目払っていた」偽の外しだった）。必ず **実損失合計 / `mean_ptloss` / Top5 一致率**と並べて読む
- **パッケージ`config.json`だけ更新して終わらない** — ユーザーのローカル設定`C:\Users\iwaki\.katrain\config.json`にもキーを追加しないとGUIに表示されない
- **ユーザーローカル`config.json`（`C:\Users\iwaki\.katrain\config.json`）の編集をサブエージェントに委任しない** — サブエージェントが成功を報告しても実際に反映されないことがある。このファイルは必ずメインセッションで直接Editする
- **`analysis_config.cfg`や`katago.exe`を直接編集しない** — ランタイムエンジン設定は手動管理
- **i18nの`.po`ファイルだけ編集して終わらない** — `python tools/compile_mo.py` で`.mo`にコンパイルしないと翻訳が反映されない
- **偏差/dodgeメカニズムで生humanPolicyを順位判定に使わない** — proximity/intensity込みのcombined weightを使わないと、攻撃対象から遠い手に差し替わり棋風が崩壊する
- **空間的に離れた2点の座標平均をフォーカス/ターゲット中心に使わない** — 盤の反対側にある2点の平均は「どちらにも近くない幻影中心」になり、実際の戦闘エリアの手がペナルティを受ける。代わりに独立したGaussianのmaxを取る（2アンカーmax方式）
- **Kivyモジュールをimportするスクリプトでargparseを使う場合、`os.environ["KIVY_NO_ARGS"] = "1"` を先頭で設定する** — KivyのConfigが`--help`等のCLI引数を横取りする
- **KaTrainのコンソール出力を grep する時は `grep -a` を付ける** — ログ内の `→` 等の非ASCII文字で grep がバイナリ扱いになり `Binary file (standard input) matches` 表示で出力抑制される
- **SGF の構造保存 round-trip で `root.sgf()` / `GameNode.sgf()` を使わない** — `GameNode.sgf_properties` が root の `C/CA/AP/KTV` を自動書換えるため元プロパティが失われる。保存的に出力したいなら `node.properties` を直接シリアライズする（例: `docs/superpowers/specs/calibration-data/clean_sgf_main_line.py`）
- **KaTrain 保存 SGF は variation 多数で `node.children[0]` traversal が main line に届かない** — 短い分岐に落ち込んで数手で打ち切られる。batch_eval 等で実戦全手を評価するには `clean_sgf_main_line.py` で最長パスに前処理する
- **Python スクリプトで `±`・`≈`・日本語等を扱う時は Windows cp932 対応を考慮する** — ファイル書き出し時（`>`）は `PYTHONIOENCODING=utf-8` で壊れバイト化を防ぐ。CLI 出力（print）は cp932 端末で `UnicodeEncodeError` クラッシュするため、ユーザー向け出力は **ASCII のみ推奨**（例: `≈` → `~`）
- **`tasklist` の出力ヘッダーは cp932 環境で文字化けする** — 日本語 Windows では「イメージ名/PID/…」部分が読めないが、データ行の ASCII 値（PID・プロセス名・メモリ）は正常。grep や値抽出は問題なく使える
- **worktree で KaTrain のコードを実行するときは `PYTHONPATH=<worktreeルート>` を明示する** — site-packages の `_katrain.pth` が HEAD チェックアウトを無条件登録しており、worktree の cwd から実行しても import は HEAD に解決される（実測 2026-08-03: A/B の base 側が黙って HEAD コードを実行しラベル誤りを起こした）。分離の検算は import 先の `__file__` とフック有無で行う
- **エンジン設定を変えるときに `C:\Users\iwaki\.katrain\analysis_config.cfg` を編集しない** — エンジンが読むのは config.json の engine.config が解決するパッケージ側 `katrain/KataGo/analysis_config.cfg`（実測 2026-08-03: ~/.katrain 側の numAnalysisThreads 4→8 編集は no-op だった）。編集前に実効ファイルを engine.config → find_package_resource の解決で確認する
- **`extra_settings={"maxVisits": N}` で解析の visits を変えられると思わない** — `engine.request_analysis` は `maxVisits` を**クエリのトップレベル**に `visits` 引数（既定 `config["max_visits"]`）から入れ、`extra_settings` は `overrideSettings` にしか入らない。KataGo はトップレベルを優先するので override 側は無視される（実測 2026-08-06: top-level 1000 / override 600 のクエリが 1006 visits を返した）。visits を変えたいなら `request_analysis(..., visits=N)` を渡す

**詰碁固有の44項目は `.claude/rules/tsumego.md` へ移した**（枠の採否と役割・コウのクラス裁定・ownership 検証・救済経路・ソルバ・問題抽出）。詰碁を触るなら必ずそちらを読むこと。

## 開発ワークフロー

- 詳細な実装ガイド・チェックリストは `.claude/rules/` に格納。**これらは自動ではコンテキストに入らない**（`.claude/rules/` は Claude Code の組み込み機能ではない。`.claude/settings.json` の PostToolUse フック `.claude/hooks/rules_reminder.py` が触った時点で**読めと促すだけ**で、中身は入らない）。**対象を触る前に自分で Read すること**:

  | 触る対象 | 読む rules |
  |---|---|
  | `katrain/core/ai.py`（戦略全般） | `ai-strategies.md`（設計と実測）, `ai-parameters.md`（全パラメータ値）, `ai-humanstyle.md`（フィルタ実装・チェックリスト） |
  | 詰碁全般（`tsumego_*.py` / `tsumego_solver/` / `native/tsumego/` / `select_tsumego_move`） | `tsumego.md`（設計と落とし穴）, `tsumego-parameters.md`（パラメータ値） |
  | `katrain/core/constants.py` / `katrain/config.json` | `ai-settings-gui.md`（AI設定追加手順） |
  | `katrain/core/base_katrain.py` | `base-katrain-config.md`（JsonStore構造・起動時リセットパターン） |
  | `**/*.log` の分析 | `log-analysis.md`（Grepパターン、サブエージェントテンプレート） |
- **i18n変更時は `.po` 編集後に `python tools/compile_mo.py` で `.mo` を再コンパイルすること**
- **パラメータ変更時はテーブルも同時に更新すること**: 戦略は `.claude/rules/ai-parameters.md`、詰碁は `.claude/rules/tsumego-parameters.md`
- **独立した追加解析クエリは1本ずつ待たない**: KataGo はパッケージ同梱 `katrain/KataGo/analysis_config.cfg`（実効値。`~/.katrain/analysis_config.cfg` はエンジンに参照されない＝「ランタイム設定ファイル」節参照）の `numAnalysisThreads=12` で複数クエリを並列処理できる。詰碁の子局面解析は `_start_region_root` / `_wait_region_roots`（`ai.py`）で全部発行してからまとめて待つ形になっているので、解析を追加するときもこの形に合わせる（1本ずつ `_analyze_region_root` を呼ぶループに戻さない）
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

**詰碁の回帰（ソルバ単体・E2E）**: 手順・ケース表・注意点は `.claude/rules/tsumego.md` の「回帰テスト」節を参照。

## 現在のパラメータ値

戦略は `.claude/rules/ai-parameters.md`、詰碁は `.claude/rules/tsumego-parameters.md`。**自動ロードされないので `ai.py` を触る前に Read すること**。
