# CLAUDE.md

## 概要

KaTrain v1.17.1.1 修正版。囲碁AI学習ツール。

- 上流リポジトリ: https://github.com/sanderland/katrain
- ランタイム設定: `C:\Users\iwaki\.katrain\`
- 主な改修: Human-like AI（9段）モードの拡張。悪手フィルタ（スコアベースのフィルタリング）に加え、力戦派（Fighting）・攻城（Siege）・狩猟（Hunt）・狩猟一致率低減（HuntDivergence）・AI一致率低減（Divergence）等の戦略モードを追加

## 技術スタック

- **言語**: Python 3.12
- **GUI**: Kivy
- **AIエンジン**: KataGo v1.16.4（TensorRT版）
- **GPU**: NVIDIA GeForce RTX 3080
- **ビルド**: hatchling / uv

## ディレクトリ構造

```
katrain/
  core/               -- コアロジック
    ai.py             -- AI着手生成（HumanStyleStrategy, FightingStrategy, SiegeStrategy, HuntStrategy, HuntDivergenceStrategy, DivergenceStrategy = 主な改修箇所）
    constants.py      -- 定数、AI設定ウィジェット定義（AI_OPTION_VALUES）
    engine.py         -- KataGoエンジン管理
    game.py           -- ゲーム状態管理
    game_node.py      -- 棋譜ノード
    sgf_parser.py     -- SGFパーサ
  gui/                -- Kivy GUIウィジェット
  config.json         -- パッケージ同梱のデフォルト設定
  i18n/               -- 多言語リソース
tests/                -- テスト
katrain_debug/        -- 戦略デバッグCLIツール（KaTrain本体と独立）
```

**ランタイム設定ファイル**（`C:\Users\iwaki\.katrain\`）:
- `config.json` — KaTrain全体の設定（エンジンパス、モデルパス、AI設定等）
- `analysis_config.cfg` — KataGo解析エンジン用設定
- `katago.exe` — KataGoエンジン本体
- `b18c384nbt-humanv0.bin.gz` — humanSLモデル（`config.json`の`humanlike_model`が空だとhumanSLProfile系の全戦略が動作しない）

## 起動・デバッグ

```bash
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
python -m katrain
```

テスト: `pytest`（SGFパーサ、盤面ロジック、AI着手生成のユニットテスト）。AI系テスト（`test_ai.py`）はhumanSLモデルが必要なため、モデル未配置の環境では `pytest --ignore=tests/test_ai.py` で除外する

デバッグ: `C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `1` に変更して起動。確認後 `0` に戻す。

**戦略デバッグCLI**: 対局不要で任意の局面の戦略意思決定を再現・確認（KataGo起動あり、約30秒）:
```bash
python -m katrain_debug --sgf FILE --move N --strategy hunt [--settings key=val ...] [--output text|json]
```
対応戦略: `human`, `pro`, `fighting`, `siege`, `hunt`, `hunt_diverge`, `diverge` 等22種。`--output json` でパース可能な構造化出力。

## コーディング規約

- コミットメッセージは**日本語**で書く
- Conventional Commits形式を使用（`feat:`, `fix:`, `refactor:` 等）
- 改修はほぼ `katrain/core/ai.py` の `HumanStyleStrategy` / `FightingStrategy` / `SiegeStrategy` / `HuntStrategy` / `HuntDivergenceStrategy` クラスに集中

## やってはいけないこと

- **ログファイルをReadで全読みしない** — 数百KB〜1MB超あるため、必ずGrepで必要行だけ抽出する
- **Stage 1（humanSLProfile付き）の`scoreLead`をフィルタ判定に使わない** — バイアスされているため、必ずStage 2のクリーンクエリの値を使う
- **パッケージ`config.json`だけ更新して終わらない** — ユーザーのローカル設定`C:\Users\iwaki\.katrain\config.json`にもキーを追加しないとGUIに表示されない
- **`analysis_config.cfg`や`katago.exe`を直接編集しない** — ランタイムエンジン設定は手動管理
- **i18nの`.po`ファイルだけ編集して終わらない** — `python tools/compile_mo.py` で`.mo`にコンパイルしないと翻訳が反映されない
- **偏差/dodgeメカニズムで生humanPolicyを順位判定に使わない** — proximity/intensity込みのcombined weightを使わないと、攻撃対象から遠い手に差し替わり棋風が崩壊する
- **空間的に離れた2点の座標平均をフォーカス/ターゲット中心に使わない** — 盤の反対側にある2点の平均は「どちらにも近くない幻影中心」になり、実際の戦闘エリアの手がペナルティを受ける。代わりに独立したGaussianのmaxを取る（2アンカーmax方式）
- **Kivyモジュールをimportするスクリプトでargparseを使う場合、`os.environ["KIVY_NO_ARGS"] = "1"` を先頭で設定する** — KivyのConfigが`--help`等のCLI引数を横取りする

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

1. `C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `1` に変更
2. `python -m katrain` で起動し、対局を実施
3. ログをGrepで確認（`log-analysis.md` のパターン参照）:
   - 着手結果（共通）: `Selected:|Safety valve.*forced|Tiebreak|Endgame: played`
   - フィルター効果: `moves pass score filter out of`
   - 重み付け効果: `Safety v2: top weighted move`（loss値で最善手からの乖離度を確認）
   - 設定値: `Initializing.*Strategy with settings`
   - フェーズ確認: `Phase:`（SiegeStrategy / HuntStrategy）/ `Mode:`（FightingStrategy）
   - dodge効果: `Best-move dodge:`（HuntDivergenceStrategy）/ `Post-temp safety:`（HuntStrategy温度選択後安全チェック）
   - フォーカス効果: `Focus: anchors=`（HuntStrategy注意フォーカスのアンカー座標とstddev）
4. 確認後、`debug_level` を `0` に戻す

**CLI検証（対局不要）**: 特定局面でのAI戦略の挙動を即座に確認:
```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --output text
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --output json 2>/dev/null | python -c "import sys,json; print(json.dumps(json.loads(sys.stdin.read()), indent=2))"
```

## 現在のパラメータ値

`.claude/rules/ai-parameters.md` に全戦略のパラメータテーブルを格納（`ai.py` 編集時に自動ロード）。
