"""盤面監視モードの応手先読み（NN キャッシュ温め）の回帰テスト。

守っているのは4点:
1. **クエリ条件が実クエリと同一** — 通常対局の実クエリは `node.analyze(engine)` の既定
   （visits=None＝config の max_visits、ownership=None＝engine の既定、リージョンなし）。
   条件がずれると NN キャッシュが温まらない（詰碁で ownership を揃えなかったときの実測:
   先読み直後の実クエリ 2.70 秒＝コールドと同一）。
2. 先読みクエリは**複製ゲームの子ノード**に紐づく＝terminate が先読みだけに当たる。
3. 相手（アプリ側＝KaTrain 上の人間）の手番でだけ発火する。AI の手番＝相手は考えていない。
4. 相手の着手が入った瞬間に未消化分を打ち切る。**これを怠ると実クエリと GPU を取り合って
   逆に遅くなる**（難解戦略で 1.6→4.4 秒に悪化した実測がある既知の罠）。

実測の payoff（2026-08-22・9路 2000visits・別プロセス2回）: 相手の着手が入った局面の解析が
先読みなし 1029ms → 的中時 108/113ms。的中率は実対局134局面で top-3 58.2% / top-5 68.7%。
"""

from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN, PRIORITY_BOARD_WATCH_PREFETCH
from katrain.core.game import BaseGame, Game, GameNode
from katrain.core.sgf_parser import Move


class FakeEngine:
    def __init__(self):
        self.requests = []
        self.terminated = []

    def request_analysis(self, node, **kwargs):
        self.requests.append((node, kwargs))

    def terminate_queries(self, only_for_node=None, lock=True):
        self.terminated.append(only_for_node)


class FakeInfo:
    def __init__(self, player_type):
        self.player_type = player_type


class FakeKatrain:
    def __init__(self):
        self.players_info = {"B": FakeInfo(PLAYER_AI), "W": FakeInfo(PLAYER_HUMAN)}
        self.logs = []

    def log(self, msg, *args, **kwargs):
        self.logs.append(msg)


def _watch_game(replies=5, candidates=("E3", "C5", "G5", "F7", "B2", "H8")):
    """KaTrain の AI（黒）が着手し終わり、相手（白＝アプリ）の手番になった直後の局面"""
    katrain = FakeKatrain()
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": 9, "RU": "chinese", "KM": 7.0}))
    base.play(Move.from_gtp("E5", player="B"), ignore_ko=True)
    node = base.current_node
    node.analysis["root"] = {"scoreLead": 0.0, "winrate": 0.5, "visits": 2000}
    node.analysis["moves"] = {
        gtp: {"move": gtp, "order": i, "scoreLead": 0.0, "winrate": 0.5, "visits": 500 - i * 10, "pv": [gtp]}
        for i, gtp in enumerate(candidates)
    }
    node.analysis["completed"] = True

    engine = FakeEngine()
    game = Game.__new__(Game)  # エンジン起動・解析スレッドを伴わない素の Game
    game.katrain = katrain
    game.engines = {"B": engine, "W": engine}
    game.root = base.root
    game.current_node = node
    game.region_of_interest = None
    game.board_watch_prefetch_replies = replies
    game.board_watch_probe_warm = False
    game._board_watch_prefetch_nodes = []
    return game, node, engine


def test_prefetch_fires_top_k_children_with_same_settings_as_the_real_query():
    game, node, engine = _watch_game(replies=5)
    game._board_watch_prefetch_worker(node, 5)
    assert len(engine.requests) == 5  # K=5 で打ち切る（限界効率が落ちるため。spec 追記4）
    for child, kwargs in engine.requests:
        # 実クエリ（node.analyze(engine) の既定）と同条件でなければ NN キャッシュが温まらない
        assert kwargs["visits"] is None          # = config の max_visits
        assert kwargs["ownership"] is None       # = engine の既定（_enable_ownership）
        assert kwargs["region_of_interest"] is None
        assert kwargs["priority"] == PRIORITY_BOARD_WATCH_PREFETCH
        # 本譜のノードではなく複製ゲームの子ノードに撃つ（terminate の的を分離するため）
        assert child is not node
        assert child.parent is not node
    assert {child.move.gtp() for child, _ in engine.requests} == {"E3", "C5", "G5", "F7", "B2"}


def test_probe_warm_is_off_unless_the_strategy_asks_for_it():
    # 既定は通常解析の温めだけ＝序盤〜中盤に ownership 付きクエリを増やさない
    game, node, engine = _watch_game(replies=2)
    game._board_watch_prefetch_worker(node, 2)
    assert len(engine.requests) == 2
    assert all(kwargs["ownership"] is None for _, kwargs in engine.requests)


def test_probe_warm_matches_the_enigma_yose_probe_query():
    """難解モードがヨセで撃つ判定クエリ（Probe）も同条件で温める。

    通常解析（ownership なし）とは ownerMap の有無が違う＝別のキャッシュエントリなので、
    上の応手先読みでは1秒も速くならない（実測 2026-08-23: ヨセの Probe に 1.1 秒）。
    条件は `Enigma9Strategy._generate_move` の `_run_query("Probe", ...)` と揃える。
    """
    game, node, engine = _watch_game(replies=2)
    game.board_watch_probe_warm = True
    game._board_watch_prefetch_worker(node, 2)

    assert len(engine.requests) == 4  # 応手2手 × (通常解析 + Probe)
    probes = [(child, kw) for child, kw in engine.requests if kw["ownership"] is True]
    assert len(probes) == 2
    for child, kwargs in probes:
        assert kwargs["include_policy"] is False
        assert kwargs["extra_settings"] == {"ignorePreRootHistory": False, "wideRootNoise": 0.0}
        # visits は渡さない＝実クエリ（_run_query("Probe", ...) も未指定）と同じ
        # config の max_visits に解決される。ずれると別の探索深さ＝温まらない
        assert kwargs.get("visits") is None
        assert kwargs["priority"] == PRIORITY_BOARD_WATCH_PREFETCH
    # 温めるのは通常解析と同じ子ノード＝cancel が両方まとめて terminate できる
    normal = [child for child, kw in engine.requests if kw["ownership"] is None]
    assert [child for child, _ in probes] == normal
    assert game._board_watch_prefetch_nodes == normal


def test_prefetch_children_are_played_by_the_opponent_color():
    game, node, engine = _watch_game(replies=2)
    game._board_watch_prefetch_worker(node, 2)
    assert {child.move.player for child, _ in engine.requests} == {"W"}


def test_prefetch_respects_the_reply_cap():
    game, node, engine = _watch_game(replies=2)
    game._board_watch_prefetch_worker(node, 2)
    assert {child.move.gtp() for child, _ in engine.requests} == {"E3", "C5"}  # visits 降順 top-2


def test_prefetch_skips_pass():
    game, node, engine = _watch_game(replies=3, candidates=("E3", "pass", "C5", "G5"))
    game._board_watch_prefetch_worker(node, 3)
    assert "pass" not in {child.move.gtp() for child, _ in engine.requests}


def test_cancel_terminates_exactly_the_prefetch_nodes():
    game, node, engine = _watch_game(replies=2)
    game._board_watch_prefetch_worker(node, 2)
    prefetch_nodes = [child for child, _ in engine.requests]
    assert game._board_watch_prefetch_nodes == prefetch_nodes
    game._cancel_board_watch_prefetch()
    assert engine.terminated == prefetch_nodes  # 本譜ノードは terminate されない
    assert game._board_watch_prefetch_nodes == []
    game._cancel_board_watch_prefetch()
    assert engine.terminated == prefetch_nodes  # 二重 cancel は no-op


def test_prefetch_skips_when_next_player_is_ai():
    """相手の着手が入った直後（次番＝KaTrain の AI）は相手が考えていないので温めない"""
    game, node, engine = _watch_game()
    game.katrain.players_info = {"B": FakeInfo(PLAYER_AI), "W": FakeInfo(PLAYER_AI)}
    game._maybe_board_watch_prefetch(node)
    assert engine.requests == []


def test_prefetch_disabled_by_zero_replies():
    game, node, engine = _watch_game(replies=0)
    game._maybe_board_watch_prefetch(node)
    assert engine.requests == []


def test_prefetch_skips_without_players_info():
    game, node, engine = _watch_game()
    game.katrain.players_info = None  # デバッグスタブ相当
    game._maybe_board_watch_prefetch(node)
    assert engine.requests == []


def test_prefetch_skips_when_a_region_is_active():
    """詰碁経路（リージョンあり）は既存の _maybe_region_prefetch の担当。二重発火させない"""
    game, node, engine = _watch_game()
    game.region_of_interest = [2, 6, 2, 6]
    game._maybe_board_watch_prefetch(node)
    assert engine.requests == []


def test_worker_bails_when_opponent_already_moved():
    game, node, engine = _watch_game(replies=3)
    game.current_node = GameNode()  # 先読みを組み立てる前に局面が進んだ
    game._board_watch_prefetch_worker(node, 3)
    assert engine.requests == []


# ---- 難解の ponder との一本化・自ノード解析の後回し・監視フラグの復元（2026-08-27 enigma spec 追記9） ----
import ast  # noqa: E402
import os  # noqa: E402
import types  # noqa: E402

from katrain.core import game as game_module  # noqa: E402
from katrain.core.board_watch import apply_game_watch_flags  # noqa: E402


def _no_thread(monkeypatch):
    started = []

    def fake_thread(*args, **kwargs):
        started.append(kwargs.get("target"))
        return types.SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(game_module.threading, "Thread", fake_thread)
    return started


def test_prefetch_yields_to_the_enigma_ponder_armed_for_the_same_move(monkeypatch):
    """難解の ponder がこの着手で発火済み（owner＝着手側の色）なら応手先読みは撃たない＝二重温めの解消。
    実測 2026-08-27（game_20260827_154802・13路）: 両方が発火すると 2000visits の root が 9 本同時に走り、
    アプリの約 2.8 秒では何も温まり切らず的中 28%"""
    game, node, engine = _watch_game()
    game._enigma_ponder_owner = node.move.player
    started = _no_thread(monkeypatch)
    game._maybe_board_watch_prefetch(node)
    assert started == []


def test_prefetch_fires_when_no_ponder_is_armed(monkeypatch):
    game, node, engine = _watch_game()
    game._enigma_ponder_owner = None  # 難解が早期 return した手番（プローブ無し）や他の戦略
    started = _no_thread(monkeypatch)
    game._maybe_board_watch_prefetch(node)
    assert started == [game._board_watch_prefetch_worker]


def _playable_watch_game(watch=True, owner="B"):
    """Game.play() を実際に通せる素の Game（エンジン起動・解析スレッドなし）"""
    katrain = FakeKatrain()
    base = BaseGame(katrain, move_tree=GameNode(properties={"SZ": 9, "RU": "chinese", "KM": 7.0}))
    engine = FakeEngine()
    game = Game.__new__(Game)
    game.__dict__.update(base.__dict__)
    game.engines = {"B": engine, "W": engine}
    game.region_of_interest = None
    game.board_watch_active = watch
    game.board_watch_prefetch_replies = 0
    game.board_watch_probe_warm = False
    game._board_watch_prefetch_nodes = []
    game._region_prefetch_nodes = []
    game._early_speculation_nodes = []
    game._enigma_ponder_owner = owner
    return game, engine


def test_play_requests_only_a_fast_analysis_when_the_ponder_is_armed_in_watch_mode():
    """自ノードの 2000visits 解析は温めと GPU を取り合う（実測 1.6〜2.1 秒）。監視モードで ponder が
    この着手を温めるなら、即時は fast（100visits）だけにし、フル解析は ponder が wave1 の後に発行する"""
    game, engine = _playable_watch_game(watch=True, owner="B")
    game.play(Move.from_gtp("E5", player="B"))
    assert [r[1].get("analyze_fast") for r in engine.requests] == [True]


def test_play_keeps_the_full_analysis_outside_watch_mode():
    game, engine = _playable_watch_game(watch=False, owner="B")
    game.play(Move.from_gtp("E5", player="B"))
    assert [bool(r[1].get("analyze_fast")) for r in engine.requests] == [False]


def test_play_keeps_the_full_analysis_when_no_ponder_is_armed():
    game, engine = _playable_watch_game(watch=True, owner=None)
    game.play(Move.from_gtp("E5", player="B"))
    assert [bool(r[1].get("analyze_fast")) for r in engine.requests] == [False]


def test_apply_game_watch_flags_sets_active_and_prefetch_from_config():
    game = types.SimpleNamespace(board_watch_active=False, board_watch_prefetch_replies=0)
    assert apply_game_watch_flags(game, {"prefetch_replies": 4}) == 4
    assert game.board_watch_active is True
    assert game.board_watch_prefetch_replies == 4


def test_apply_game_watch_flags_defaults_when_config_is_missing():
    game = types.SimpleNamespace()
    assert apply_game_watch_flags(game, None) == 5
    assert game.board_watch_active is True and game.board_watch_prefetch_replies == 5


def test_new_game_reapplies_the_watch_flags_while_the_game_watcher_runs():
    """静的検査: `_do_new_game` は Game を作り直す（＝フラグが初期値に戻る）が監視スレッド（kind="game"）は
    生き続けるので、`_do_board_watch_start` と同じ `apply_game_watch_flags` で張り直さなければならない。
    実測 2026-08-27（game_20260827_155133・セッション2局目）: フラグが落ちたままヨセ31手すべてが
    省けるはずの Probe（中央値 1.1 秒）を払い、応手先読みも 0 本だった"""
    main_path = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
    with open(main_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("_do_new_game", "_do_board_watch_start"):
        calls = [
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None)
            for n in ast.walk(funcs[name])
            if isinstance(n, ast.Call)
        ]
        assert "apply_game_watch_flags" in calls, f"{name} が apply_game_watch_flags を呼んでいない"


def test_ai_move_highlight_is_wired_through_main():
    """静的検査（追記6）: AI 着手の強調表示は (1) `_do_ai_move` が着手と同時に `_board_watch_ahead` を呼び、
    (2) `_do_board_watch_start` が BoardWatcher に `on_ahead` を渡し、(3) 監視を止める2経路
    （`_stop_board_watcher` / `_board_watch_trigger`）が `_board_watch_marker_close` で輪を消す"""
    main_path = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")
    with open(main_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def calls(name):
        return [
            n for n in ast.walk(funcs[name]) if isinstance(n, ast.Call)
        ]

    def callee(call):
        return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", None)

    assert "_board_watch_ahead" in [callee(c) for c in calls("_do_ai_move")]
    watcher_calls = [c for c in calls("_do_board_watch_start") if callee(c) == "BoardWatcher"]
    assert watcher_calls and any(kw.arg == "on_ahead" for kw in watcher_calls[0].keywords)
    for name in ("_stop_board_watcher", "_board_watch_trigger"):
        assert "_board_watch_marker_close" in [callee(c) for c in calls(name)], name


def test_highlight_settings_are_exposed_in_the_config_popup():
    """静的検査（追記6）: 強調表示の ON/OFF と色は設定画面（popups.kv の general 節）の**1つの**ドロップダウン
    （「表示しない」＋色）から変えられ、保存時に走っている監視へ `_board_watch_highlight_refresh` で即反映される。
    `_board_watch_ahead` が毎回 config を読む（監視の再起動は不要）。チェックボックスを別行にすると一般設定欄が
    7行になり既存ラベルが重なる（実測 2026-08-28）ので、行を増やしていないことも固定する"""
    from katrain.core.screen_marker import highlight_choices

    root = os.path.join(os.path.dirname(__file__), "..", "katrain")
    kv = open(os.path.join(root, "popups.kv"), encoding="utf-8").read()
    assert "highlight_ai_move" not in kv  # ON/OFF は色の「表示しない」に統合＝行数を増やさない
    assert 'input_property: "board_watch/highlight_color"' in kv
    assert 'i18n_prefix: "board_watch:highlight_color:"' in kv
    popups = open(os.path.join(root, "gui", "popups.py"), encoding="utf-8").read()
    assert "_board_watch_highlight_refresh" in popups and "fill_highlight_colors" in popups
    main = open(os.path.join(root, "__main__.py"), encoding="utf-8").read()
    ahead = main.split("def _board_watch_ahead(")[1].split("\n    def ")[0]
    assert '"highlight_color"' in ahead and "highlight_ai_move" not in ahead
    for locale in ("en", "jp"):
        po = open(os.path.join(root, "i18n", "locales", locale, "LC_MESSAGES", "katrain.po"), encoding="utf-8").read()
        for name in highlight_choices():
            assert f'msgid "board_watch:highlight_color:{name}"' in po, (locale, name)
