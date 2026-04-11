import os
import time

from katrain.core.game import BaseGame, Game, KaTrainSGF
from katrain.core.constants import (
    DATA_FOLDER,
    AI_HUMAN, AI_PRO, AI_DIVERGE, AI_SIEGE, AI_HUNT, AI_HUNT_DIVERGE,
    AI_FIGHTING, AI_DEFAULT, AI_HANDICAP, AI_SCORELOSS, AI_POLICY,
    AI_WEIGHTED, AI_PICK, AI_RANK, AI_INFLUENCE, AI_TERRITORY,
    AI_LOCAL, AI_TENUKI, AI_SIMPLE_OWNERSHIP, AI_SETTLE_STONES,
    AI_JIGO, AI_ANTIMIRROR,
)
from katrain.core.ai import STRATEGY_REGISTRY
from katrain.core.engine import KataGoEngine
from katrain_debug.katrain_stub import KaTrainStub


# --- 戦略名マッピング（CLIフレンドリー名 → ai.pyの内部キー） ---

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


# --- SGF読み込み・ノード移動 ---

def load_sgf_to_move(sgf_path, move_number):
    """SGFファイルを読み込み、指定手番のノードを返す。

    Args:
        sgf_path: SGFファイルパス
        move_number: 手番（1-indexed。1=最初の着手, 2=2手目, ...。0でルートノード）
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


# --- DebugGame ---

class DebugGame(Game):
    """analyze_all_nodesの自動実行をスキップするGameサブクラス。

    CLIデバッグ用途で、__init__時のanalyze_all_nodesスレッド起動を抑制し、
    play()もデフォルトでanalyze=Falseにする。
    """

    def __init__(self, katrain, engine, move_tree=None, game_properties=None,
                 sgf_filename=None, bypass_config=False):
        # Game.__init__をバイパスしてBaseGame.__init__を直接呼び出す
        # （Game.__init__はanalyze_all_nodesスレッドを起動するため）
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
        """デフォルトでanalyze=Falseにして分析リクエストを送らない。"""
        if analyze:
            return super().play(move, ignore_ko=ignore_ko, analyze=True)
        played_node = BaseGame.play(self, move, ignore_ko)
        return played_node


# --- run_strategy パイプライン ---

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
        dict with keys: move, explanation, player, strategy, strategy_class, settings, logs
    Raises:
        KeyError: 未知の戦略名
        ValueError: 不正なmove_number
    """
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
        # 5. DebugGameを構築
        root = target_node
        while root.parent:
            root = root.parent
        game = DebugGame(katrain=stub, engine=engine, move_tree=root)
        game.set_current_node(target_node)
        stub.game = game

        # 6. 分析リクエストを送って完了を待つ
        target_node.analyze(engine)
        while not target_node.analysis_complete:
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
