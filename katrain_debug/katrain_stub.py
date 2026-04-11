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
    """KaTrainBaseの最小スタブ。Kivy依存なしでai.pyの戦略コードが動作する。"""

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
