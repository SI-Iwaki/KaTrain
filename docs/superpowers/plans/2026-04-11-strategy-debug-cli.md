# 戦略デバッグCLI 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SGFファイルと手番を指定して任意のAI戦略クラスの意思決定過程をCLIから再現・可視化する開発支援ツールを構築する。

**Architecture:** `katrain_debug/`パッケージをプロジェクトルート直下に新設。KaTrainのスタブ（Kivy JsonStore回避）+ KataGoEngine直接利用 + 戦略コード直接実行のアプローチ。`katrain/`本体のコードは一切変更しない。

**Tech Stack:** Python 3.12, argparse, 既存のkatrain.core（ai.py, engine.py, game.py, sgf_parser.py）

---

## ファイル構成

| ファイル | 役割 |
|---------|------|
| `katrain_debug/__init__.py` | パッケージマーカー |
| `katrain_debug/__main__.py` | `python -m katrain_debug` のエントリポイント |
| `katrain_debug/katrain_stub.py` | KaTrainBase代替スタブ（log蓄積, config読み込み, controlsダミー） |
| `katrain_debug/runner.py` | 戦略実行ランナー（SGF→局面構築→戦略実行→ログ収集） |
| `katrain_debug/cli.py` | argparse引数解析 + text/JSON出力フォーマット |
| `tests/test_debug_stub.py` | KaTrainStubのユニットテスト |
| `tests/test_debug_runner.py` | ランナーの結合テスト（KataGo必要） |

---

### Task 1: KaTrainStub — 最小スタブの実装

`ai.py`の戦略コードが`game.katrain`経由でアクセスするインターフェースをスタブで提供する。Kivy依存を持つ`KaTrainBase`を継承せず、ダックタイピングで必要最小限を実装する。

**Files:**
- Create: `katrain_debug/__init__.py`
- Create: `katrain_debug/katrain_stub.py`
- Create: `tests/test_debug_stub.py`

**背景知識:**
- `game.katrain.log(message, level)` — 全戦略クラスがログ出力に使用。`level`は`OUTPUT_DEBUG=1`, `OUTPUT_INFO=0`, `OUTPUT_ERROR=-1`等。
- `game.katrain.config(setting, default)` — `"engine/max_visits"` のように`/`区切りでネスト設定を取得。config.jsonのトップレベルキー: `engine`, `ai`, `game`, `general`, `trainer`, `timer`, `contribute`, `ui_state`, `dist_models`。
- `game.katrain.players_info` — `{"B": Player("B"), "W": Player("W")}` の辞書。`Player`は`katrain.core.base_katrain`から import。
- `game.katrain.controls.set_status(...)` — `Game.set_current_node`等がGUI更新で呼ぶ。no-opで良い。
- `game.katrain.controls.move_tree.insert_node` / `.redraw()` — insert_mode関連。CLI では使わない。no-op。
- `engine.py:330` の `getattr(self.katrain, "update_state", None)` — 存在チェック付きなので不要だが、`pondering`属性は`game.py:571`で直接アクセスされる。
- config.json の `"ai"` セクションはKivy JsonStoreの構造上、`self._config["ai"]["ai:hunt"]` のようにネストしてアクセスする。標準 `json.load` では同じ辞書構造になる。

- [ ] **Step 1: パッケージ初期化ファイルを作成**

```python
# katrain_debug/__init__.py
```

空ファイル。

- [ ] **Step 2: テストファイルを作成し、KaTrainStubの基本テストを書く**

```python
# tests/test_debug_stub.py
import json
import os
import pytest
from katrain_debug.katrain_stub import KaTrainStub


class TestKaTrainStubLog:
    def test_log_accumulates_messages(self):
        stub = KaTrainStub.__new__(KaTrainStub)
        stub.debug_level = 1
        stub.logs = []
        stub.log("test message", 1)
        assert len(stub.logs) == 1
        assert stub.logs[0] == ("test message", 1)

    def test_log_accumulates_all_levels(self):
        stub = KaTrainStub.__new__(KaTrainStub)
        stub.debug_level = 1
        stub.logs = []
        stub.log("debug", 1)
        stub.log("info", 0)
        stub.log("error", -1)
        assert len(stub.logs) == 3

    def test_log_prints_when_level_sufficient(self, capsys):
        stub = KaTrainStub.__new__(KaTrainStub)
        stub.debug_level = 1
        stub.logs = []
        stub.log("visible", 1)
        captured = capsys.readouterr()
        assert "visible" in captured.out

    def test_log_suppresses_when_level_insufficient(self, capsys):
        stub = KaTrainStub.__new__(KaTrainStub)
        stub.debug_level = 0
        stub.logs = []
        stub.log("hidden", 1)
        captured = capsys.readouterr()
        assert "hidden" not in captured.out
        # but still accumulated
        assert len(stub.logs) == 1


class TestKaTrainStubConfig:
    def test_config_simple_key(self, tmp_path):
        config_data = {"engine": {"max_visits": 800}, "general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert stub.config("engine") == {"max_visits": 800}

    def test_config_slash_path(self, tmp_path):
        config_data = {"engine": {"max_visits": 800}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert stub.config("engine/max_visits") == 800

    def test_config_default_value(self, tmp_path):
        config_data = {"engine": {}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert stub.config("engine/missing_key", 42) == 42

    def test_config_missing_category(self, tmp_path):
        config_data = {"engine": {}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert stub.config("nonexistent/key", "default") == "default"


class TestKaTrainStubControls:
    def test_controls_set_status_is_noop(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        # Should not raise
        stub.controls.set_status("test", 0)

    def test_controls_move_tree_is_noop(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        # Should not raise
        stub.controls.move_tree.insert_node = None
        stub.controls.move_tree.redraw()
        stub.controls.move_tree.redraw_tree_trigger()

    def test_update_state_is_noop(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        stub.update_state()  # Should not raise


class TestKaTrainStubPlayersInfo:
    def test_players_info_has_both_colors(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        assert "B" in stub.players_info
        assert "W" in stub.players_info

    def test_players_info_are_player_objects(self, tmp_path):
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        from katrain.core.base_katrain import Player
        assert isinstance(stub.players_info["B"], Player)
        assert isinstance(stub.players_info["W"], Player)
```

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `pytest tests/test_debug_stub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'katrain_debug'`

- [ ] **Step 4: KaTrainStubを実装**

```python
# katrain_debug/katrain_stub.py
import json

from katrain.core.base_katrain import Player
from katrain.core.constants import OUTPUT_ERROR, OUTPUT_INFO, PLAYER_AI


class _NoOp:
    """Absorbs any attribute access or call without error."""
    def __getattr__(self, name):
        return _NoOp()

    def __call__(self, *args, **kwargs):
        return None

    def __setattr__(self, name, value):
        pass


class KaTrainStub:
    """KaTrainBaseの最小スタブ。Kivy依存なしでai.pyの戦略コードが動作する。

    ai.pyの戦略クラスは game.katrain 経由で以下にアクセスする:
      - .log(message, level)
      - .config(setting, default)
      - .players_info
      - .controls.set_status(...) / .controls.move_tree.*
    engine.pyは getattr(self.katrain, "update_state", None) でチェック後に呼ぶ。
    """

    def __init__(self, config_path, debug_level=1):
        with open(config_path, "r", encoding="utf-8") as f:
            self._config = json.load(f)
        self.debug_level = debug_level
        self.logs = []
        self.game = None
        self.pondering = False
        self.controls = _NoOp()
        self.players_info = {"B": Player("B"), "W": Player("W")}

    def log(self, message, level=OUTPUT_INFO):
        self.logs.append((message, level))
        if level == OUTPUT_ERROR:
            print(f"ERROR: {message}")
        elif self.debug_level >= level:
            print(message)

    def config(self, setting, default=None):
        if "/" in setting:
            cat, key = setting.split("/", 1)
            return self._config.get(cat, {}).get(key, default)
        return self._config.get(setting, default)

    def update_state(self, **kwargs):
        pass
```

- [ ] **Step 5: テストを実行して全パスを確認**

Run: `pytest tests/test_debug_stub.py -v`
Expected: All tests PASS

- [ ] **Step 6: コミット**

```bash
git add katrain_debug/__init__.py katrain_debug/katrain_stub.py tests/test_debug_stub.py
git commit -m "feat: KaTrainStubを実装（Kivy依存なしのスタブ）"
```

---

### Task 2: DebugGame — analyze_all_nodesをスキップするGameサブクラス

`Game.__init__`は`analyze_all_nodes`をスレッドで自動実行する。CLIでは不要なので、これをスキップするサブクラスを`runner.py`内に作成する。

**Files:**
- Create: `katrain_debug/runner.py`（DebugGameクラスのみ先行実装）
- Create: `tests/test_debug_runner.py`（DebugGameのユニットテスト）

**背景知識:**
- `Game.__init__`（`katrain/core/game.py:436-459`）は `super().__init__()` 呼び出し後に `threading.Thread(target=lambda: self.analyze_all_nodes(...)).start()` を実行する。
- `BaseGame.__init__`（`katrain/core/game.py:50-104`）で`move_tree`が渡されるとSGFツリーを設定し、`self.set_current_node(self.root)` を呼ぶ。`move_tree`がNoneの場合は`katrain.config("game/size")`等を呼んでデフォルト盤面を作る。
- `Game.play(move, analyze=True)`（`katrain/core/game.py:545`）は`analyze=True`だとエンジンに分析リクエストを送る。CLIでは`generate_ai_move`が`game.play(move)`を呼ぶが、戦略の着手結果の分析は不要。DebugGameで`analyze=False`をデフォルトにする。
- SGFファイルの読み込みは `KaTrainSGF.parse_file(filename)` で `GameNode` ツリーのrootを返す。`KaTrainSGF`は`katrain/core/game.py:41`で定義されている`SGF`サブクラス（`_NODE_CLASS = GameNode`）。

- [ ] **Step 1: DebugGameのテストを書く**

```python
# tests/test_debug_runner.py
import json
import pytest
from katrain_debug.katrain_stub import KaTrainStub
from katrain_debug.runner import DebugGame


class TestDebugGame:
    def test_init_does_not_start_analysis_thread(self, tmp_path):
        """DebugGameはanalyze_all_nodesスレッドを起動しない"""
        config_data = {
            "general": {"debug_level": 1},
            "game": {"size": 9, "komi": 6.5, "rules": "japanese", "handicap": 0},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        # engine=Noneでも初期化できる（分析スレッドが走らないため）
        # DebugGameはmove_treeなしではconfig参照でデフォルト盤面を作るので
        # bypass_configで回避
        game = DebugGame(katrain=stub, engine={}, bypass_config=True)
        assert game.engines == {}
        assert game.current_node is not None

    def test_init_with_sgf_tree(self, tmp_path):
        """SGF move_treeを渡してもanalyze_all_nodesが走らない"""
        config_data = {"general": {"debug_level": 1}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))

        from katrain.core.game import KaTrainSGF
        sgf_path = "tests/data/ogs.sgf"
        move_tree = KaTrainSGF.parse_file(sgf_path)
        game = DebugGame(katrain=stub, engine={}, move_tree=move_tree)
        assert game.root is move_tree
        assert game.current_node is not None

    def test_play_does_not_trigger_analysis(self, tmp_path):
        """DebugGame.playは分析リクエストを送らない"""
        config_data = {
            "general": {"debug_level": 1},
            "game": {"size": 9, "komi": 6.5, "rules": "japanese", "handicap": 0},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        stub = KaTrainStub(str(config_file))
        game = DebugGame(katrain=stub, engine={}, bypass_config=True)

        from katrain.core.sgf_parser import Move
        move = Move.from_gtp("D4", "B")
        played_node = game.play(move)
        assert played_node is not None
        assert game.current_node == played_node
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_debug_runner.py::TestDebugGame -v`
Expected: FAIL — `ImportError: cannot import name 'DebugGame' from 'katrain_debug.runner'`

- [ ] **Step 3: DebugGameを実装**

```python
# katrain_debug/runner.py
from katrain.core.game import BaseGame, Game, KaTrainSGF
from katrain.core.game_node import GameNode
from katrain.core.sgf_parser import Move


class DebugGame(Game):
    """analyze_all_nodesの自動実行をスキップするGameサブクラス。

    Game.__init__はスレッドでanalyze_all_nodesを起動するが、
    CLIデバッグではKataGoへの一括分析は不要（戦略コード内で個別にrequest_analysisする）。
    """

    def __init__(self, katrain, engine, move_tree=None, game_properties=None,
                 sgf_filename=None, bypass_config=False):
        # Game.__init__を呼ばず、BaseGame.__init__を直接呼ぶことでスレッド起動を回避
        BaseGame.__init__(
            self,
            katrain=katrain,
            move_tree=move_tree,
            game_properties=game_properties,
            sgf_filename=sgf_filename,
            bypass_config=bypass_config,
        )
        if not isinstance(engine, dict):
            engine = {"B": engine, "W": engine}
        self.engines = engine
        self.insert_mode = False
        self.insert_after = None
        self.region_of_interest = None

    def play(self, move, ignore_ko=False, analyze=False):
        """デフォルトでanalyze=Falseにして分析リクエストを送らない"""
        if analyze:
            return super().play(move, ignore_ko=ignore_ko, analyze=True)
        played_node = BaseGame.play(self, move, ignore_ko)
        return played_node
```

- [ ] **Step 4: テストを実行して全パスを確認**

Run: `pytest tests/test_debug_runner.py::TestDebugGame -v`
Expected: All tests PASS

- [ ] **Step 5: コミット**

```bash
git add katrain_debug/runner.py tests/test_debug_runner.py
git commit -m "feat: DebugGame（analyze_all_nodesスキップ版Game）を実装"
```

---

### Task 3: ランナーコア — SGF読み込みから戦略実行までのパイプライン

SGFファイルを読み込み、指定手番のノードまで進め、KataGoエンジンを起動し、戦略クラスを実行してログを収集する`run_strategy`関数を実装する。

**Files:**
- Modify: `katrain_debug/runner.py`（`run_strategy`関数を追加）
- Modify: `tests/test_debug_runner.py`（結合テスト追加）

**背景知識:**
- SGFファイルは `KaTrainSGF.parse_file(filename)` で読み込む。戻り値は`GameNode`のルートノード。
- ルートノードから `node.children[0]` を辿ることで手順通りにノードを進める。各ノードの`.depth`属性が手番（0=ルート, 1=1手目...）。
- `KataGoEngine(katrain, config)` でKataGoプロセスを起動。`config`は`katrain.config("engine")`で得られるdict。起動後、KataGoがstderrにready messageを出すまで少し待つ。
- 戦略クラスは `STRATEGY_REGISTRY[ai_mode](game, ai_settings)` でインスタンス化。`ai_mode`は`"ai:hunt"`等の文字列。`ai_settings`は`katrain.config(f"ai/{ai_mode}")`で得られるdict。
- `strategy.generate_move()`はブロッキング呼び出し。内部でKataGoへのクエリ送信→コールバック待ちを行う。戻り値は`(Move, str)`。
- 戦略名マッピング（CLIフレンドリー名 → 定数）: `human`→`ai:human`, `fighting`→`ai:p:fighting`, `siege`→`ai:siege`, `hunt`→`ai:hunt`, `hunt_diverge`→`ai:hunt_diverge`, `diverge`→`ai:diverge_move`

- [ ] **Step 1: ランナーのユニットテスト（モック版）を書く**

KataGoプロセスなしでテスト可能な部分のテスト。

```python
# tests/test_debug_runner.py に追加

class TestStrategyNameMapping:
    def test_known_strategies(self):
        from katrain_debug.runner import STRATEGY_NAME_MAP
        assert STRATEGY_NAME_MAP["hunt"] == "ai:hunt"
        assert STRATEGY_NAME_MAP["siege"] == "ai:siege"
        assert STRATEGY_NAME_MAP["human"] == "ai:human"
        assert STRATEGY_NAME_MAP["fighting"] == "ai:p:fighting"
        assert STRATEGY_NAME_MAP["hunt_diverge"] == "ai:hunt_diverge"
        assert STRATEGY_NAME_MAP["diverge"] == "ai:diverge_move"

    def test_unknown_strategy_raises(self):
        from katrain_debug.runner import STRATEGY_NAME_MAP
        assert "nonexistent" not in STRATEGY_NAME_MAP


class TestLoadSGFAndNavigate:
    def test_navigate_to_move(self, tmp_path):
        from katrain_debug.runner import load_sgf_to_move
        # ogs.sgf は実ゲームの棋譜
        game_node = load_sgf_to_move("tests/data/ogs.sgf", move_number=5)
        assert game_node.depth == 5

    def test_navigate_to_move_1(self):
        from katrain_debug.runner import load_sgf_to_move
        game_node = load_sgf_to_move("tests/data/ogs.sgf", move_number=1)
        assert game_node.depth == 1

    def test_move_number_exceeds_game_length(self):
        from katrain_debug.runner import load_sgf_to_move
        with pytest.raises(ValueError, match="exceeds"):
            load_sgf_to_move("tests/data/ogs.sgf", move_number=9999)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_debug_runner.py::TestStrategyNameMapping tests/test_debug_runner.py::TestLoadSGFAndNavigate -v`
Expected: FAIL — `ImportError: cannot import name 'STRATEGY_NAME_MAP'`

- [ ] **Step 3: `STRATEGY_NAME_MAP`と`load_sgf_to_move`を実装**

```python
# katrain_debug/runner.py に追加（ファイル先頭のimportにも追加）
from katrain.core.constants import (
    AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE,
    AI_FIGHTING, AI_DEFAULT, AI_HANDICAP, AI_SCORELOSS, AI_POLICY,
    AI_WEIGHTED, AI_PICK, AI_RANK, AI_INFLUENCE, AI_TERRITORY,
    AI_LOCAL, AI_TENUKI, AI_SIMPLE_OWNERSHIP, AI_SETTLE_STONES,
    AI_JIGO, AI_ANTIMIRROR,
)
from katrain.core.ai import STRATEGY_REGISTRY

# CLIフレンドリー名 → ai.pyの戦略定数
STRATEGY_NAME_MAP = {
    "default": AI_DEFAULT,
    "handicap": AI_HANDICAP,
    "scoreloss": AI_SCORELOSS,
    "policy": AI_POLICY,
    "weighted": AI_WEIGHTED,
    "pick": AI_PICK,
    "rank": AI_RANK,
    "influence": AI_INFLUENCE,
    "territory": AI_TERRITORY,
    "local": AI_LOCAL,
    "tenuki": AI_TENUKI,
    "fighting": AI_FIGHTING,
    "simple_ownership": AI_SIMPLE_OWNERSHIP,
    "settle_stones": AI_SETTLE_STONES,
    "jigo": AI_JIGO,
    "antimirror": AI_ANTIMIRROR,
    "human": AI_HUMAN,
    "pro": AI_PRO,
    "diverge": AI_DIVERGE,
    "siege": AI_SIEGE,
    "hunt": AI_HUNT,
    "hunt_diverge": AI_HUNT_DIVERGE,
}


def load_sgf_to_move(sgf_path, move_number):
    """SGFファイルを読み込み、指定手番のノードを返す。

    Args:
        sgf_path: SGFファイルパス
        move_number: 手番（1-indexed、1=最初の着手）
    Returns:
        指定手番のGameNode
    Raises:
        ValueError: move_numberがゲームの手数を超える場合
    """
    root = KaTrainSGF.parse_file(sgf_path)
    node = root
    for i in range(move_number):
        if not node.children:
            raise ValueError(
                f"Move number {move_number} exceeds game length ({i} moves)"
            )
        node = node.children[0]
    return node
```

- [ ] **Step 4: テストを実行して全パスを確認**

Run: `pytest tests/test_debug_runner.py::TestStrategyNameMapping tests/test_debug_runner.py::TestLoadSGFAndNavigate -v`
Expected: All tests PASS

- [ ] **Step 5: `run_strategy`関数を実装**

```python
# katrain_debug/runner.py に追加
from katrain.core.engine import KataGoEngine
from katrain_debug.katrain_stub import KaTrainStub


def run_strategy(sgf_path, move_number, strategy_name, config_path=None,
                 settings_overrides=None, debug_level=1):
    """SGFの指定局面で戦略を実行し、結果とログを返す。

    Args:
        sgf_path: SGFファイルパス
        move_number: 手番（1-indexed）
        strategy_name: CLIフレンドリー名（"hunt", "siege"等）
        config_path: config.jsonのパス（Noneで~/.katrain/config.json）
        settings_overrides: 戦略パラメータの上書きdict
        debug_level: ログ詳細度（1=通常, 2=全ログ）
    Returns:
        dict: {
            "move": str (GTP形式),
            "explanation": str,
            "player": str ("B" or "W"),
            "strategy": str,
            "strategy_class": str,
            "settings": dict,
            "logs": list of (message, level),
        }
    Raises:
        KeyError: 未知の戦略名
        ValueError: 不正なmove_number
    """
    import os
    from katrain.core.constants import DATA_FOLDER

    if config_path is None:
        config_path = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))

    # 1. スタブ初期化
    stub = KaTrainStub(config_path, debug_level=debug_level)

    # 2. 戦略名の解決
    if strategy_name not in STRATEGY_NAME_MAP:
        available = ", ".join(sorted(STRATEGY_NAME_MAP.keys()))
        raise KeyError(f"Unknown strategy '{strategy_name}'. Available: {available}")
    ai_mode = STRATEGY_NAME_MAP[strategy_name]

    # 3. SGF読み込み・ノード移動
    target_node = load_sgf_to_move(sgf_path, move_number)
    player = target_node.next_player

    # 4. KataGoエンジン起動
    engine_config = stub.config("engine")
    engine = KataGoEngine(stub, engine_config)

    try:
        # 5. DebugGameを構築（rootからtarget_nodeまでのツリーを使う）
        root = target_node
        while root.parent:
            root = root.parent
        game = DebugGame(katrain=stub, engine=engine, move_tree=root)
        game.set_current_node(target_node)
        stub.game = game

        # 6. 分析リクエストを送って完了を待つ（戦略コードのwait_for_analysisが必要とする）
        target_node.analyze(engine)
        while not target_node.analysis_complete:
            import time
            time.sleep(0.05)
            engine.check_alive(exception_if_dead=True)

        # 7. AI設定を取得し、上書きを適用
        ai_settings = stub.config(f"ai/{ai_mode}") or {}
        if settings_overrides:
            ai_settings = {**ai_settings, **settings_overrides}

        # 8. 戦略を実行
        strategy = STRATEGY_REGISTRY[ai_mode](game, ai_settings)
        move, explanation = strategy.generate_move()

        return {
            "move": move.gtp(),
            "explanation": explanation,
            "player": player,
            "strategy": strategy_name,
            "strategy_class": strategy.__class__.__name__,
            "settings": ai_settings,
            "logs": list(stub.logs),
        }
    finally:
        # 9. KataGoシャットダウン
        engine.shutdown(finish=False)
```

- [ ] **Step 6: コミット**

```bash
git add katrain_debug/runner.py tests/test_debug_runner.py
git commit -m "feat: run_strategy関数（SGF→局面構築→戦略実行パイプライン）を実装"
```

---

### Task 4: CLIエントリポイント — argparse + text/JSON出力

`python -m katrain_debug`で実行可能なCLIインターフェースを構築する。

**Files:**
- Create: `katrain_debug/__main__.py`
- Create: `katrain_debug/cli.py`

**背景知識:**
- `__main__.py`は`python -m katrain_debug`で自動実行される。`cli.py`の`main()`を呼ぶだけ。
- text出力は戦略名・SGF・手番・設定値・意思決定ログ・結果を人間向けに整形。
- json出力は`run_strategy`の戻り値をほぼそのまま`json.dumps`する。ログの`level`はintのまま。
- `--settings`引数は`key=value`形式のnargs="*"で受け取り、value部分を数値に変換する。

- [ ] **Step 1: `__main__.py`を作成**

```python
# katrain_debug/__main__.py
from katrain_debug.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: `cli.py`を実装**

```python
# katrain_debug/cli.py
import argparse
import json
import sys

from katrain_debug.runner import run_strategy, STRATEGY_NAME_MAP


def parse_settings(settings_list):
    """['key1=val1', 'key2=val2'] → {key1: val1, key2: val2} に変換。
    value部分を数値（float/int）に変換可能な場合は変換する。
    """
    if not settings_list:
        return None
    result = {}
    for item in settings_list:
        if "=" not in item:
            print(f"Warning: ignoring invalid setting '{item}' (expected key=value)", file=sys.stderr)
            continue
        key, value = item.split("=", 1)
        # 数値変換を試みる
        try:
            if "." in value:
                value = float(value)
            else:
                value = int(value)
        except ValueError:
            if value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False
        result[key] = value
    return result if result else None


def format_text_output(result, sgf_path, move_number):
    """text形式の出力を生成"""
    lines = []
    lines.append(f"=== Strategy Debug: {result['strategy_class']} ===")
    lines.append(f"SGF: {sgf_path} | Move: {move_number} | Player: {result['player']}")
    lines.append("")

    lines.append("--- Settings ---")
    for key, value in sorted(result["settings"].items()):
        lines.append(f"  {key}: {value}")
    lines.append("")

    lines.append("--- Decision Log ---")
    for message, level in result["logs"]:
        if level <= 1:  # OUTPUT_DEBUG and above
            lines.append(message)
    lines.append("")

    lines.append("--- Result ---")
    lines.append(f"Move: {result['move']}")
    lines.append(f"Explanation: {result['explanation']}")

    return "\n".join(lines)


def format_json_output(result, sgf_path, move_number):
    """json形式の出力を生成"""
    output = {
        "sgf": sgf_path,
        "move_number": move_number,
        "player": result["player"],
        "strategy": result["strategy"],
        "strategy_class": result["strategy_class"],
        "settings": result["settings"],
        "result": {
            "move": result["move"],
            "explanation": result["explanation"],
        },
        "logs": [
            {"message": msg, "level": level}
            for msg, level in result["logs"]
        ],
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(
        prog="katrain_debug",
        description="KaTrain AI戦略デバッグツール — SGFの指定局面で戦略の意思決定過程を再現・可視化",
    )
    parser.add_argument("--sgf", required=True, help="SGFファイルパス")
    parser.add_argument("--move", type=int, required=True, help="解析する手番（1-indexed）")
    parser.add_argument(
        "--strategy", required=True,
        choices=sorted(STRATEGY_NAME_MAP.keys()),
        help="戦略名",
    )
    parser.add_argument(
        "--settings", nargs="*", metavar="KEY=VALUE",
        help="戦略パラメータの上書き（例: hunt_max_loss=8.0）",
    )
    parser.add_argument("--config", default=None, help="config.jsonのパス（デフォルト: ~/.katrain/config.json）")
    parser.add_argument("--output", choices=["text", "json"], default="text", help="出力形式")
    parser.add_argument("--log-level", type=int, default=1, choices=[1, 2], help="ログ詳細度（1=通常, 2=全ログ）")

    args = parser.parse_args()

    settings_overrides = parse_settings(args.settings)

    try:
        result = run_strategy(
            sgf_path=args.sgf,
            move_number=args.move,
            strategy_name=args.strategy,
            config_path=args.config,
            settings_overrides=settings_overrides,
            debug_level=args.log_level,
        )
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output == "json":
        print(format_json_output(result, args.sgf, args.move))
    else:
        print(format_text_output(result, args.sgf, args.move))
```

- [ ] **Step 3: コミット**

```bash
git add katrain_debug/__main__.py katrain_debug/cli.py
git commit -m "feat: CLIエントリポイント（argparse + text/JSON出力）を実装"
```

---

### Task 5: 結合テスト — 実際のKataGoで動作確認

実際のKataGoプロセスを使って、既存のSGFファイルでHuntStrategy等を実行し、エンドツーエンドの動作を検証する。

**Files:**
- Modify: `tests/test_debug_runner.py`（結合テスト追加）

**背景知識:**
- KataGoバイナリは`C:\Users\iwaki\.katrain\katago.exe`に配置済み。
- humanSLモデルは`C:\Users\iwaki\.katrain\b18c384nbt-humanv0.bin.gz`に配置済み。
- config.jsonは`C:\Users\iwaki\.katrain\config.json`。
- TensorRTモデルの初回ロードに数十秒かかる。テストには`@pytest.mark.slow`タグを付ける。
- `tests/data/ogs.sgf`は実ゲームの棋譜で、テスト用に使える。

- [ ] **Step 1: 結合テストを書く**

```python
# tests/test_debug_runner.py に追加
import os

@pytest.mark.skipif(
    not os.path.exists(os.path.expanduser("~/.katrain/katago.exe")),
    reason="KataGo not installed"
)
class TestRunStrategyIntegration:
    """実際のKataGoプロセスを使う結合テスト"""

    def test_run_hunt_strategy(self):
        from katrain_debug.runner import run_strategy
        result = run_strategy(
            sgf_path="tests/data/ogs.sgf",
            move_number=30,
            strategy_name="hunt",
        )
        assert result["move"] is not None
        assert result["player"] in ("B", "W")
        assert result["strategy"] == "hunt"
        assert result["strategy_class"] == "HuntStrategy"
        assert len(result["logs"]) > 0

    def test_run_human_strategy(self):
        from katrain_debug.runner import run_strategy
        result = run_strategy(
            sgf_path="tests/data/ogs.sgf",
            move_number=10,
            strategy_name="human",
        )
        assert result["move"] is not None
        assert result["strategy_class"] == "HumanStyleStrategy"

    def test_settings_override(self):
        from katrain_debug.runner import run_strategy
        result = run_strategy(
            sgf_path="tests/data/ogs.sgf",
            move_number=30,
            strategy_name="hunt",
            settings_overrides={"hunt_max_loss": 3.0},
        )
        assert result["settings"]["hunt_max_loss"] == 3.0
        assert result["move"] is not None

    def test_invalid_strategy_raises(self):
        from katrain_debug.runner import run_strategy
        with pytest.raises(KeyError, match="Unknown strategy"):
            run_strategy(
                sgf_path="tests/data/ogs.sgf",
                move_number=10,
                strategy_name="nonexistent",
            )

    def test_json_output_is_valid(self):
        from katrain_debug.runner import run_strategy
        from katrain_debug.cli import format_json_output
        result = run_strategy(
            sgf_path="tests/data/ogs.sgf",
            move_number=10,
            strategy_name="human",
        )
        json_str = format_json_output(result, "tests/data/ogs.sgf", 10)
        parsed = json.loads(json_str)
        assert parsed["move_number"] == 10
        assert "result" in parsed
        assert "logs" in parsed
```

- [ ] **Step 2: ユニットテスト（KataGo不要）が引き続きパスすることを確認**

Run: `pytest tests/test_debug_stub.py tests/test_debug_runner.py::TestDebugGame tests/test_debug_runner.py::TestStrategyNameMapping tests/test_debug_runner.py::TestLoadSGFAndNavigate -v`
Expected: All tests PASS

- [ ] **Step 3: 結合テストを実行**

Run: `pytest tests/test_debug_runner.py::TestRunStrategyIntegration -v -s --timeout=120`
Expected: All tests PASS（KataGoの起動に時間がかかるため`--timeout=120`）

注意: テストがタイムアウトする場合はKataGoの起動問題を調査。stderrログを確認。

- [ ] **Step 4: CLI手動テストを実行**

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --output text
```

Expected: HuntStrategyの意思決定ログがtext形式で出力される。`Phase:`, `Focus:`, `Selected:` 等のログ行が含まれる。

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --output json
```

Expected: 同じ内容がJSON形式で出力される。`jq`等でパース可能。

- [ ] **Step 5: コミット**

```bash
git add tests/test_debug_runner.py
git commit -m "test: 戦略デバッグCLIの結合テストを追加"
```

---

### Task 6: 動作確認と微調整

実際のKataGoで様々な戦略を試し、出力の調整や問題の修正を行う。

**Files:**
- Modify: `katrain_debug/cli.py`（出力調整が必要な場合）
- Modify: `katrain_debug/runner.py`（問題修正が必要な場合）

- [ ] **Step 1: 各戦略で動作確認**

以下のコマンドを順に実行し、エラーなく結果が返ることを確認:

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 10 --strategy human
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy fighting
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy siege
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt_diverge
python -m katrain_debug --sgf tests/data/ogs.sgf --move 10 --strategy diverge
```

- [ ] **Step 2: パラメータ上書きの動作確認**

```bash
python -m katrain_debug --sgf tests/data/ogs.sgf --move 30 --strategy hunt --settings hunt_max_loss=3.0 hunt_focus_stddev=5.0 --output json
```

JSON出力の`settings`内に上書き値が反映されていることを確認。

- [ ] **Step 3: 問題があれば修正してコミット**

発見された問題を修正し、修正ごとにコミット。

- [ ] **Step 4: 最終コミット**

全テストをパスさせる:

```bash
pytest tests/test_debug_stub.py tests/test_debug_runner.py -v
```

問題がなければ完了。
