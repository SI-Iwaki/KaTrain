# 戦略デバッグCLI設計書

## 概要

SGFファイルと手番を指定して、任意のAI戦略クラス（HuntStrategy, SiegeStrategy等）の意思決定過程をCLIから再現・可視化する開発支援ツール。

### 背景

現在の開発フローでは、戦略コードのデバッグに「debug_level=1に変更 → KaTrain起動 → 対局実施 → ログGrep → 確認」という30分以上のサイクルが必要。特に、特定の局面での戦略の挙動を確認するには対局を再現する必要があり、非効率だった。

### 目的

- 対局不要で任意の局面に対する戦略の意思決定過程を確認する
- CLIツールとして、Claude CodeがBash経由で直接実行できるようにする
- フィルタリング、重み付け、dodge、フォーカス等の全ステップのログを構造化して出力する

## アーキテクチャ

### ディレクトリ構成

```
katrain_debug/
  __init__.py
  cli.py              -- CLIエントリポイント（argparse、出力フォーマット）
  runner.py           -- 戦略実行ランナー（SGF読み込み→局面構築→戦略実行→ログ収集）
  katrain_stub.py     -- KaTrainの最小スタブ（ログ収集、config読み込み、controlsダミー）
```

プロジェクトルート直下に配置。`katrain/`本体のコードをimportして使う（`sgf_parser.py`、`game.py`、`game_node.py`、`engine.py`、`ai.py`）。新規コードはスタブとランナーのみ。

### 処理フロー

```
[CLI] --sgf/--move/--strategy
  → [runner.py]
    → KaTrainStub(config.json)     ← 標準json.loadでKivy JsonStore回避
    → KataGoEngine(stub, config)   ← 独立プロセスでKataGo起動
    → SGF読み込み → GameNode構築
    → Game(stub, engine)           ← analyze_all_nodesをスキップ
    → STRATEGY_REGISTRY[name](game, settings)
    → strategy.generate_move()     ← 実際の戦略コードがそのまま動く
    → stub.logsから全意思決定ログを収集
  → [CLI] text or JSON出力
  → KataGoシャットダウン
```

### KaTrain本体との関係

- `katrain/`パッケージの`ai.py`、`engine.py`、`game.py`、`sgf_parser.py`をimportして使用
- `katrain_debug/`から`katrain/`への依存は一方向のみ
- `katrain/`のコードは一切変更しない

## コンポーネント詳細

### katrain_stub.py — KaTrainスタブ

`ai.py`の戦略クラスは`game.katrain`経由でログ出力・設定読み込み・プレイヤー情報にアクセスする。`KaTrainBase`はKivy `JsonStore`と`kivy.Config`に依存しているため、これを直接使わず、ダックタイピングで最小インターフェースを実装する。

**実装するインターフェース**:

| メソッド/属性 | 用途 | 実装 |
|-------------|------|------|
| `log(message, level)` | デバッグログ出力 | 全ログを`self.logs`リストに蓄積 + stdout出力 |
| `config(setting, default)` | 設定値の読み取り | `~/.katrain/config.json`を標準`json.load`で読み込み、`/`区切りでパス分解して返す |
| `players_info` | プレイヤー情報 | AI設定付き`Player`オブジェクトを生成 |
| `controls` | GUI操作（game.pyが参照） | ダミーのno-opオブジェクト |
| `update_state()` | GUI更新（engine.pyが呼び出し） | no-op |

**方針**:
- `KaTrainBase`を継承しない（Kivy `JsonStore`/`Config.set`の実行を回避）
- Kivy自体はインストール済みが前提（`engine.py`のimportで`kivy.utils.platform`が必要）

### runner.py — 戦略実行ランナー

**処理ステップ**:

1. `KaTrainStub`を初期化（config.json読み込み、ログ収集準備）
2. `KataGoEngine(stub, engine_config)`でKataGoプロセスを起動
3. SGFファイルを読み込み、`GameNode`ツリーを構築
4. 指定手番のノードまで進む
5. `Game(katrain=stub, engine=engine)`を構築（`analyze_all_nodes`の自動実行をスキップ）
6. `STRATEGY_REGISTRY`から戦略クラスを取得
7. `strategy = StrategyClass(game, ai_settings)`でインスタンス化
8. `move, explanation = strategy.generate_move()`を実行
9. `stub.logs`から全ログを収集・構造化して返す
10. KataGoプロセスをシャットダウン

**Gameクラスの扱い**:
`Game.__init__`は`analyze_all_nodes`をスレッドで自動実行する。CLIではこれは不要なので、`Game`のサブクラスで自動分析をスキップするか、`BaseGame`ベースで手動構築する。

### cli.py — CLIエントリポイント

**実行方法**:
```bash
python -m katrain_debug --sgf game.sgf --move 42 --strategy hunt
```

**引数**:

| 引数 | 必須 | 説明 |
|------|------|------|
| `--sgf FILE` | Yes | SGFファイルパス |
| `--move N` | Yes | 解析する手番（1-indexed） |
| `--strategy NAME` | Yes | 戦略名（`human`, `fighting`, `siege`, `hunt`, `hunt_diverge`, `diverge`等） |
| `--settings K=V` | No | 戦略パラメータの上書き（例: `--settings hunt_max_loss=8.0 hunt_focus_stddev=5.0`） |
| `--config PATH` | No | config.jsonのパス（デフォルト: `~/.katrain/config.json`） |
| `--output FORMAT` | No | `text`（デフォルト）/ `json`（構造化） |
| `--log-level N` | No | `1`=通常デバッグ（デフォルト）、`2`=全ログ |

**text出力**:
```
=== Strategy Debug: HuntStrategy ===
SGF: game.sgf | Move: 42 | Player: B

--- Settings ---
hunt_max_loss: 6.0, hunt_min_group_size: 5, ...

--- Decision Log ---
[HuntStrategy] Phase: Hunt (3 targets)
[HuntStrategy] Focus: anchors=[(3,3),(15,15)] stddev=7.0
moves pass score filter 18 out of 24
Safety v2: top weighted move D4 (loss=0.8)
Selected: D4

--- Result ---
Move: D4
Explanation: ...
```

**json出力**:
```json
{
  "sgf": "game.sgf",
  "move_number": 42,
  "player": "B",
  "strategy": "hunt",
  "settings": {"hunt_max_loss": 6.0, "...": "..."},
  "result": {"move": "D4", "explanation": "..."},
  "logs": [
    {"message": "Phase: Hunt (3 targets)", "level": 1},
    {"message": "Focus: anchors=[(3,3),(15,15)]", "level": 1}
  ]
}
```

## Kivy依存の回避策

| 依存箇所 | ファイル | 回避方法 |
|---------|---------|---------|
| `kivy.storage.jsonstore.JsonStore` | `base_katrain.py` | スタブでは標準`json.load`を使用。`base_katrain.py`はimportしない |
| `kivy.Config` | `base_katrain.py` | 同上 |
| `kivy.utils.platform` | `engine.py` | Kivyインストール済みのため問題なし。`"win"`を返すだけ |
| `katrain.controls`アクセス | `game.py` | スタブに`controls`属性を追加（ダミーno-opオブジェクト） |

## スコープ

### 含む
- 戦略実行と意思決定ログの表示
- パラメータ上書き（`--settings`）
- text / JSON出力形式

### 含まない（必要になった時点で拡張）
- 棋譜全体の走査（find_mistakes相当）
- 常駐モード（KataGoプロセスの使い回し）
- MCP化

## 制約

- Kivyインストール済みが前提（`engine.py`のimportで必要）
- KataGoのコールドスタートに数十秒かかる（TensorRTモデル読み込み）
- `~/.katrain/`にKataGoバイナリ（`katago.exe`）、メインモデル、humanSLモデル（`b18c384nbt-humanv0.bin.gz`）、`analysis_config.cfg`が配置済みであること
- GPU（RTX 3080）が利用可能であること

## 実装順

1. `katrain_stub.py` — 最小スタブ（log, config, players_info, controls）
2. `runner.py` — KataGo起動 + SGF読み込み + 戦略実行 + ログ収集
3. `cli.py` — 引数解析 + 出力フォーマット + `__main__.py`
4. 動作確認 — 既存のSGFファイルでHuntStrategy等を実行して検証
