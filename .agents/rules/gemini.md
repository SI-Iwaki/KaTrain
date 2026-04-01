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
- 改修はほぼ `katrain/core/ai.py` の `HumanStyleStrategy` クラスに集中
