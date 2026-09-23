"""自己対局ハーネスのテスト用の偽エンジンとスタブ（KataGo 不要）。test_ で始まらないので pytest は収集しない。"""

import json
import time

from katrain.core.game import Game
from katrain.core.sgf_parser import Move
from katrain_debug.katrain_stub import KaTrainStub

CONFIG = {
    "engine": {
        "max_visits": 100,
        "fast_visits": 10,
        "max_time": 8.0,
        "wide_root_noise": 0.04,
        "_enable_ownership": False,
    },
    "game": {"size": "9", "komi": 7.0, "rules": "chinese", "handicap": 0},
    "trainer": {
        "eval_thresholds": [12, 6, 3, 1.5, 0.5, 0],
        "save_feedback": [True, True, True, True, False, False],
        "eval_show_ai": True,
        "save_analysis": False,
        "save_marks": False,
    },
    "ai": {"ai:default": {}},
}


def make_stub(tmp_path, **ai_sections):
    """一時 config.json を書いて本物の KaTrainStub を作る。ai_sections は {"ai:mode": {...}}。"""
    cfg = json.loads(json.dumps(CONFIG))
    cfg["ai"].update(ai_sections)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return KaTrainStub(str(path), debug_level=0, quiet=True)


def empties_of(node):
    """node の局面の空点（左下から x→y の順）。取りは起きない前提の簡易版。"""
    size = node.board_size[0]
    occupied = {m.coords for n in node.nodes_from_root for m in n.moves if m.coords is not None}
    return [(x, y) for y in range(size) for x in range(size) if (x, y) not in occupied]


def hp_array(size, weights):
    """{(x, y) | "pass": hp} -> humanPolicy のフラット配列（末尾 pass）。"""
    arr = [0.0] * (size * size + 1)
    for key, v in weights.items():
        if key == "pass":
            arr[-1] = v
        else:
            x, y = key
            arr[(size - 1 - y) * size + x] = v
    return arr


def top_right_hp(node, empties):
    """既定の humanSL: 右上の空点2つ（左下から埋める AI とぶつからない）。"""
    size = node.board_size[0]
    return hp_array(size, {empties[-1]: 0.7, empties[-2]: 0.3})


class FakeEngine:
    """同期で答える偽 KataGo（呼んだスレッドでそのままコールバックする）。

    通常解析: 候補は空点を左下から走査した先頭3点（order 順・[0] が最善手）。勝率は全ノード winrate（黒視点）。黒視点 scoreLead は
    root = lead、候補 i = lead - sign * 0.5 * i（打つ側から見て i 番目ほど 0.5 目ずつ悪い）。
    include_pass なら pass を pointsLost = pass_loss で候補の末尾に足す。
    humanSL（extra_settings に humanSLProfile）: hp_fn(node, empties) の humanPolicy を返す。
    """

    def __init__(self, hp_fn=top_right_hp, include_pass=False, pass_loss=0.0, lead=0.5, winrate=0.6, visits=100):
        self.hp_fn = hp_fn
        self.winrate = winrate
        self.include_pass = include_pass
        self.pass_loss = pass_loss
        self.lead = lead
        self.visits = visits
        self.requests = []
        self.alive = True
        self.restarts = 0
        self.shutdowns = 0
        self.new_games = 0

    def request_analysis(self, node, callback, error_callback=None, **kwargs):
        self.requests.append((node, kwargs))
        empties = empties_of(node)
        extra = kwargs.get("extra_settings") or {}
        if "humanSLProfile" in extra:
            hp = self.hp_fn(node, empties)
            callback(
                {"rootInfo": {"scoreLead": 0.0, "winrate": 0.5, "visits": 1}, "moveInfos": [], "humanPolicy": hp}, False
            )
            return
        sign = 1 if node.next_player == "B" else -1
        infos = []
        for i, c in enumerate(empties[:3]):
            gtp = Move(c).gtp()
            infos.append(
                {
                    "move": gtp,
                    "order": i,
                    "visits": self.visits - 10 * i,
                    "scoreLead": self.lead - sign * 0.5 * i,
                    "winrate": self.winrate,
                    "prior": 0.5 / (i + 1),
                    "pv": [gtp],
                }
            )
        if self.include_pass:
            infos.append(
                {
                    "move": "pass",
                    "order": len(infos),
                    "visits": 5,
                    "scoreLead": self.lead - sign * self.pass_loss,
                    "winrate": self.winrate,
                    "prior": 0.01,
                    "pv": ["pass"],
                }
            )
        root = {"scoreLead": self.lead, "winrate": self.winrate, "visits": self.visits}
        callback({"rootInfo": root, "moveInfos": infos}, False)

    def terminate_queries(self, only_for_node=None, lock=True):
        pass

    def on_new_game(self):
        self.new_games += 1

    def check_alive(self, *args, **kwargs):
        return self.alive

    def restart(self):
        self.restarts += 1
        self.alive = True

    def shutdown(self, finish=False):
        self.shutdowns += 1


def new_game(stub, engine, size=9):
    """本物の Game（root の解析はデーモンスレッドで偽エンジンが即答する）。"""
    game = Game(stub, engine, game_properties={"SZ": size, "KM": 7.0, "RU": "chinese"})
    stub.game = game
    started = time.time()
    while not game.root.analysis_complete:
        assert time.time() - started < 5, "root analysis never completed"
        time.sleep(0.005)
    return game
