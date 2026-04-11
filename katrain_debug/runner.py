from katrain.core.game import BaseGame, Game, KaTrainSGF
from katrain.core.game_node import GameNode
from katrain.core.sgf_parser import Move


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
