# CLAUDE.md

## 概要

KaTrain v1.17.1.1 修正版。囲碁AI学習ツール。

- 上流リポジトリ: https://github.com/sanderland/katrain
- ランタイム設定: `C:\Users\iwaki\.katrain\`
- 主な改修: Human-like AI（9段）モードの拡張。悪手フィルタ（スコアベースのフィルタリング）に加え、力戦派（Fighting）・攻城（Siege）・狩猟（Hunt）・狩猟一致率低減（HuntDivergence）・AI一致率低減（Divergence）・地合い勝ち（Jigo）等の戦略モードを追加・改修。力戦派には複雑化モード `complex`（切りボーナス＋リード適応の損失予算ゲートで盤面を紛れさせる）を追加。Jigo には序盤星打ち強制オプション `jigo_force_sanrensei`（19路のみ・黒=三連星/白=2連星）を追加。さらに Jigo には9路専用の独立戦略 `ai:jigo9`（持碁（9路））を追加（既存 `ai:jigo` は19/13路専用に整理）し、9路 deception の phase 境界・target を5スライダーで調整可能にした（phase3前倒しで挽回を間に合わせる）。星打ち布石ロジックは `ai.py` の共有ヘルパー `_compute_star_opening_targets` に集約し HumanStyle の2連星と共用。詰碁画面キャプチャ（tsumego_capture: グローバルホットキーでBlueStacks上の詰碁アプリ盤面を認識しKaTrainに反映+外枠自動適用（大型詰碁は適応marginで補償面積を確保）+黒番AIが正解手を自動着手し白番はユーザーが応手、auto_ai_black:falseで従来動作）を追加。詰碁の着手選択 `ai:tsumego` は ownership gain（集計対象は**リージョン内の石のみ**＝枠外の代償地帯は成否と逆相関する／同着はgain_epsilonで目数に委ね、目数もpoints_epsilon内で並ぶ同着バンドでは「コウ経路でない手 > visits最多」の順で採る＝コウでも勝てるとKataGoが読み切るとコウ殺しと無条件殺しがスコア同着になるため、バンド候補だけリージョン子局面解析の最善応手PVでコウ形を構造検出して格下げ（tie_ko_screen。親PVは守り方が枠へ手抜きするので使えない）し、残りはvisits最多のKataGo本命＝ノイズのコイン投げで解答樹に無い正しい別解を踏まない／min_visits未満の候補は除外／**gain で目数最善手を覆せるのは同程度に探索された候補だけ**＝gain_min_visit_ratio、覆す判断は子局面を同visitsで解析し直して絶対ownershipで検証＝gain_verify。gain 争いに参加できなかった候補（目数ガード外・深さゲート外）も gain が明確に上回るなら同深さ検証を経て救済＝gain_rescue_margin（トリガーと採用の両マージン。gain 降順トップ3を全員検証し検証値最良を採用＝ノイズ手が gain 1位でも本物が影に隠れない。visit比では本物と偽の gain が分離できず、分離できるのは同深さ検証だけ＝全誤答ケースで検証は一度も間違えていない）。gainは1本のroot探索のmovesOwnership由来なので浅い候補ほど片側ノイズが出る）に加え、コウは「コウダテがある前提」でコウ勝ち後の局面を評価（ko_win_assumption）。**詰碁の正解順序は 無条件に殺す（生きる） > コウ > セキ** で目数はクラス内のタイブレークにすぎないため、通常最善が既に成功している局面（ko_success_lead）ではコウを検査しない。枠はキャプチャ時に frame_ko の両方を張って root スコアがバランスの取れた方を自動採用（拮抗時は攻め方コウダテ側）。さらに**手番側（解く側）の本体石が開始時点で死と読まれる枠は詰碁自体を壊しているので捨て、その回だけ枠なしで出題する**（必ず正解手がある詰碁で開始時点から全滅はあり得ない。枠バランスはこの失敗に構造的に不感）

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
