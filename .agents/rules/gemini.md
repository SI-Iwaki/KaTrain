---
trigger: always_on
glob: 
description: KaTrainプロジェクト設定とコーディング規約
---
## 概要

KaTrain v1.17.1.1 修正版。囲碁AI学習ツール。

- 上流リポジトリ: https://github.com/sanderland/katrain
- ランタイム設定: `C:\Users\iwaki\.katrain\`
- 主な改修: Human-like AI（9段）モードに悪手フィルタを追加。KataGoの`moveInfos`でスコアベースのフィルタリングを行い、大悪手を除外してからhumanPolicy重みで選択する

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
    ai.py             -- AI着手生成（HumanStyleStrategy = 主な改修箇所）
    constants.py      -- 定数、AI設定ウィジェット定義（AI_OPTION_VALUES）
    engine.py         -- KataGoエンジン管理
    game.py           -- ゲーム状態管理
    game_node.py      -- 棋譜ノード
    sgf_parser.py     -- SGFパーサ
  gui/                -- Kivy GUIウィジェット
  config.json         -- パッケージ同梱のデフォルト設定
  i18n/               -- 多言語リソース
tests/                -- テスト
```

**ランタイム設定ファイル**（`C:\Users\iwaki\.katrain\`）:
- `config.json` — KaTrain全体の設定（エンジンパス、モデルパス、AI設定等）
- `analysis_config.cfg` — KataGo解析エンジン用設定
- `katago.exe` — KataGoエンジン本体

## 起動・デバッグ

```bash
cd C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1
python -m katrain
```

デバッグ: `C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `1` に変更して起動。確認後 `0` に戻す。

## コーディング規約

- コミットメッセージは**日本語**で書く
- Conventional Commits形式を使用（`feat:`, `fix:`, `refactor:` 等）
- 改修はほぼ `katrain/core/ai.py` の `HumanStyleStrategy` / `FightingStrategy` クラスに集中

## やってはいけないこと

- **ログファイルをReadで全読みしない** — 数百KB〜1MB超あるため、必ずGrepで必要行だけ抽出する
- **Stage 1（humanSLProfile付き）の`scoreLead`をフィルタ判定に使わない** — バイアスされているため、必ずStage 2のクリーンクエリの値を使う
- **パッケージ`config.json`だけ更新して終わらない** — ユーザーのローカル設定`C:\Users\iwaki\.katrain\config.json`にもキーを追加しないとGUIに表示されない
- **`analysis_config.cfg`や`katago.exe`を直接編集しない** — ランタイムエンジン設定は手動管理

## GUI拡張時の注意事項（ルール）

AI等に新しいパラメータやGUI設定を追加する際は、以下の問題が発生しやすいため必ず対策案を履行すること。

**問題1（設定がUIに表示されない）:**
KaTrainの設定画面は、「現在のローカル設定ファイル（`C:\Users\iwaki\.katrain\config.json`）」に存在するキーのみを動的に読み込んでUIを生成する仕様になっている。そのため、ソースコード上のパッケージ設定（`katrain/config.json`）だけにデフォルト値を追記しても、ユーザーの既存環境のUI画面には表示されない。
**対策:**
設定キー・パラメータを新設した際は、ソースコードの更新に加え、**アクティブなローカル設定ファイル（`C:\Users\iwaki\.katrain\config.json`）にもそのキーと初期値を直接パッチして追記する**か、ユーザーに「UIからデフォルトに戻すボタンを押すこと」を案内する。

**問題2（GridLayoutの要素上限によるクラッシュ）:**
AI設定パネルなどを構成する `GridLayout` には、表示できる行数上限（`max_options`）が固定で設定されている場合がある。設定項目を追加しすぎてこれが上限を超えると、`GridLayoutException ('Too many children...')` が発生しGUIがクラッシュする。
**対策:**
設定項目（キー）を追加する際は、必ず描画先となる Popup クラス（`katrain/gui/popups.py` 内の `ConfigAIPopup` など）の `max_options = NumericProperty(N)` の数値を、追加する項目数に合わせて十分な値に引き上げること。

## 変更の検証方法

1. `C:\Users\iwaki\.katrain\config.json` の `"debug_level": 0` → `1` に変更
2. `python -m katrain` で起動し、対局を実施
3. ログで確認:
   - 着手結果: `Played move|First-impression deviation: played`
   - フィルター効果: `moves pass score filter out of`
   - 設定値: `Initializing HumanStyleStrategy with settings`
4. 確認後、`debug_level` を `0` に戻す

## 現在のパラメータ値

### 悪手フィルタ閾値

| パラメータ | 19路・13路 | 9路盤 |
|---|---|---|
| OPENING_THRESHOLD | 2.8 | 0.5 |
| NORMAL_THRESHOLD | 5.6 | 3.3 |

### 第一感ぶれ（全盤面）

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| first_impression_deviation | false | ONで第一感上位3位中の損失0.5〜上限目の手のうち最も損失の少ない手を確定選択（9路=1.5目、13路・19路=2.0目） |
| first_impression_deviation_opening | false | ON（+deviation ON）で序盤でも第一感ぶれを適用する（デフォルトOFF=序盤は無効） |
| first_impression_green_blend | false | ON（+deviation ON）で第一感1位が緑(loss<0.5)かつ非最善の場合、第一感1位と上位3位中の最小損失手(0.5〜上限)をgreen_ratioで選択 |
| green_blend_green_ratio | 0.5 | green_blend時の緑手選択確率（0.4=dev寄り40/60・0.5=均等50/50・0.6=緑寄り60/40） |

### エンジン設定（maxVisits）

Stage1とGUI/analysis_configの3箇所を同じ値に揃える。Stage2は独立値。

| 場所 | 現在値 | 役割 |
|---|---|---|
| ai.py `override_settings["maxVisits"]` | 800 | Stage1: HumanSL着手選択 |
| ai.py `clean_override_settings["maxVisits"]` | 600 | Stage2: クリーンスコア検証（独立値） |
| GUI `max_visits` / `analysis_config.cfg` | 800 | 事後分析クエリ（Stage1と揃える） |

### 力戦派モード（FightingStrategy）

| パラメータ | デフォルト値 | 備考 |
|---|---|---|
| fighting_mode | "classic" | "classic" / "scoreloss" / "human" |
| fighting_max_loss | 3.0 | scorelossモード専用の悪手フィルタ閾値（目数） |
| force_tengen_opening | false | ONで黒番初手のみ天元に打つ |
| fighting_invasion_bonus | 1.0 | 相手地への侵入手の重みボーナス（全モード共通） |
| fighting_contact_boost | 1.0 | 相手石への接触手（距離1）の重みブースト（全モード共通） |
| fighting_chaos_relax | 0.0 | humanモード: 相手地への接触手の悪手閾値を緩和する目数 |
| unsettled_power | 2.0 | 未確定地への重み指数（大きいほど未確定地に集中） |
| proximity_stddev | 3.0 | 相手石への近接重みの標準偏差（小さいほど近距離に集中） |

humanモードの悪手フィルタ閾値はHumanStyleStrategyと同じBAD_MOVE_THRESHOLD（19路 NORMAL=5.6 / OPENING=2.8、9路 NORMAL=3.3 / OPENING=0.5）を使用。`fighting_max_loss`は無効。
