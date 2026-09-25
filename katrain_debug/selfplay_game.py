"""自己対局ハーネスの1局（本物の Game・generate_ai_move の写し・本物の game_report）。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §2
"""

import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import contextlib  # noqa: E402
import dataclasses  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from katrain.core.ai import (  # noqa: E402
    STRATEGY_REGISTRY,
    VEIL_OPEN_DELEGATES,
    AnalysisDiscardedException,
    game_report,
)
from katrain.core.constants import AI_DEFAULT, OUTPUT_DEBUG, OUTPUT_ERROR  # noqa: E402
from katrain.core.engine import KataGoEngine  # noqa: E402
from katrain.core.game import Game, KaTrainSGF  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.cli import parse_settings  # noqa: E402
from katrain_debug.runner import STRATEGY_NAME_MAP  # noqa: E402
from katrain_debug.selfplay_opponent import BookOpponent, GameAborted, HumanSLOpponent, Waiter  # noqa: E402

# stub.logs から残す行（戦略自身の [XxxStrategy] 行・判定ログと時間ログ・エラー）。エンジンのクエリ送受信は捨てる
KEEP_LOG_MARKERS = ("Rate:", "Decision:", "着手決定に", "Generating move using", "Move generation complete")
STRATEGY_LOG_RE = re.compile(r"^\[\w+Strategy\] ")  # 戦略自身の行（_log・盤サイズ不一致の INFO など）


def start_engine(stub):
    """KataGo を1本起動する。allow_recovery=False: スタブは呼び出し不可なので、エンジン死亡時の
    復旧ポップアップ（engine.py:163-166 の self.katrain(...)）で読み取りスレッドが TypeError で落ちるのを防ぐ。"""
    return KataGoEngine(stub, {**stub.config("engine"), "allow_recovery": False})


ENGINE_STALL_S = 180.0  # 待ちの問い合わせがあるのに KataGo の返事がこの秒数ないなら、生きていても再起動する


class EngineWatchdog:
    """エンジンの死活を見張り、落ちていたら再起動する。生きているのに返事をしない（止まった）ときも再起動する。

    戦略の待ちループは check_alive の戻り値を見ずに回り続ける（ai.py:584-591）ので、エンジンが死ぬと
    query_generation を進める restart でしか抜けられない（raise_if_discarded → AnalysisDiscardedException）。
    ハーネスの待ちループ（Waiter）は restarts の変化を見てその局を aborted にする。execute_plan は各局の前にも
    ensure_alive を呼ぶ（落ちたエンジンのまま次の局を始めると、残りの局が全部すぐ aborted になる）。

    止まった KataGo（check_alive は True のまま）は Waiter のタイムアウトが効かない戦略自身の待ちループを永遠に
    止めるので、engine.queries（待ちの問い合わせ）が空でないのに、そのどれにも返事が来ない（どれも queries から
    消えない）状態が stall_timeout 秒を超えたら再起動する。控えめな判定: 何も待っていない・どれか1つでも返事が
    来た・待ち始めた、のどれかで時計を戻す。queries を持たないエンジン（テストの偽物）と stall_timeout 0 は見ない。
    """

    def __init__(self, engine, interval=2.0, stall_timeout=ENGINE_STALL_S):
        self.engine = engine
        self.interval = interval
        self.stall_timeout = stall_timeout
        self.restarts = 0
        self.stalls = 0
        self._pending = set()
        self._progress_at = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _pending_queries(self):
        queries = getattr(self.engine, "queries", None)
        if queries is None:
            return None
        with getattr(self.engine, "thread_lock", None) or contextlib.nullcontext():
            return set(queries)

    def stalled(self, now=None):
        """待ちの問い合わせに stall_timeout 秒を超えて1つも返事が来ていないか（呼ぶたびに観測を更新する）。"""
        if not self.stall_timeout:
            return False
        pending = self._pending_queries()
        if pending is None:
            return False
        now = time.monotonic() if now is None else now
        if not pending or not self._pending or (self._pending - pending) or self._progress_at is None:
            self._progress_at = now
        self._pending = pending
        return bool(pending) and now - self._progress_at > self.stall_timeout

    def _restart(self):
        self.engine.restart()
        self.restarts += 1
        self._pending, self._progress_at = set(), None

    def ensure_alive(self):
        """落ちているか止まっていれば再起動する（見張りのスレッドと execute_plan の局の間の両方から呼ぶ＝ロックで1回だけ）。"""
        with self._lock:
            if not self.engine.check_alive():
                self._restart()
            elif self.stalled():
                self.stalls += 1
                katrain = getattr(self.engine, "katrain", None)
                if katrain is not None:
                    katrain.log(
                        f"selfplay: KataGo stalled ({len(self._pending)} queries pending, no reply for "
                        f"{self.stall_timeout:.0f}s): restarting the engine",
                        OUTPUT_ERROR,
                    )
                self._restart()

    def _run(self):
        while not self._stop.wait(self.interval):
            self.ensure_alive()

    def stop(self):
        self._stop.set()


@dataclasses.dataclass
class Arm:
    """アーム＝戦略と解決済み設定（ユーザー config の節 + 上書き）。

    effective_settings は戦略が実際に使う設定（コードの既定値に settings を重ねて数値を正規化・null ガード用）。
    fingerprint は settings の指紋のまま（run.json の再開・複数の実行の突き合わせと互換）。
    delegate は序盤の研究外し（`<KEY_PREFIX>_open_moves` > 0）の韜晦のアームだけ: 窓の中を任せる難解＋の戦略キー・設定・
    指紋（open_delegate）。再開と合算の突き合わせに入る（spec 2026-09-23-veil-strategy-design.md §16.2 手順9）。
    """

    name: str
    strategy: str
    mode: str
    settings: dict
    override_items: list
    strategy_class: str
    settings_source: str
    effective_settings: dict = None
    delegate: dict = None

    @property
    def fingerprint(self):
        return S.settings_fingerprint(self.mode, self.settings)

    def as_dict(self):
        return {**dataclasses.asdict(self), "fingerprint": self.fingerprint}


def open_delegate(stub, cls, effective):
    """序盤の研究外しの任せる先（spec §15.3 手順5・§16.2 手順9）。`<KEY_PREFIX>_open_moves` > 0 の韜晦だけ dict、ほかは None。

    韜晦は窓の中を同じ盤サイズの難解＋（VEIL_OPEN_DELEGATES）に、ユーザー config の節（`ai/<戦略キー>`）のまま任せる
    ＝アームの上書きでは変わらない。指紋はその節の中身（節が無ければ {}＝難解＋のコードの既定値）。
    """
    prefix = getattr(cls, "KEY_PREFIX", None)
    size = getattr(cls, "BOARD_LEN", None)
    raw_open_moves = (effective or {}).get(f"{prefix}_open_moves") if prefix else None
    open_moves = int(raw_open_moves or 0)  # ai.py の veil_open_window と同じ丸め（(0, 1) の値は OFF）
    if size not in VEIL_OPEN_DELEGATES or open_moves <= 0:
        return None
    key = VEIL_OPEN_DELEGATES[size]
    section = stub.config(f"ai/{key}")
    settings = dict(section or {})
    return {
        "strategy_key": key,
        "settings": settings,
        "settings_source": (
            "user config" if section is not None else "code defaults (mode missing from the user config)"
        ),
        "fingerprint": S.settings_fingerprint(key, settings),
    }


def resolve_arm(stub, name, strategy, override_items):
    """`<名前>=<runner の戦略名>[:key=val,...]` を解決する。綴り間違いの上書きキーは ValueError。"""
    if strategy not in STRATEGY_NAME_MAP:
        raise KeyError(f"Unknown strategy '{strategy}'. Available: {', '.join(sorted(STRATEGY_NAME_MAP))}")
    mode = STRATEGY_NAME_MAP[strategy]
    user = stub.config(f"ai/{mode}")
    overrides = parse_settings(list(override_items)) or {}
    cls = STRATEGY_REGISTRY.get(mode)
    known = set()
    prefix = defaults = None
    if cls is not None and hasattr(cls, "KEY_PREFIX") and hasattr(cls, "SETTING_DEFAULTS"):
        prefix, defaults = cls.KEY_PREFIX, cls.SETTING_DEFAULTS
        known = {f"{prefix}_{k}" for k in defaults}
    unknown = S.unknown_override_keys(overrides, user, known)
    if unknown:
        raise ValueError(
            f"arm {name}: unknown setting keys {unknown} (not in the user config nor the strategy defaults)"
        )
    settings = {**(user or {}), **overrides}
    effective = S.effective_settings(settings, prefix, defaults)
    return Arm(
        name=name,
        strategy=strategy,
        mode=mode,
        settings=settings,
        override_items=list(override_items),
        strategy_class=cls.__name__ if cls is not None else None,
        settings_source="user config" if user is not None else "code defaults (mode missing from the user config)",
        effective_settings=effective,
        delegate=open_delegate(stub, cls, effective),
    )


def _ai_turn(game, ai_mode, ai_settings):
    """generate_ai_move（ai.py:11678-11704）の行ごとの写し。違いは戦略オブジェクトも返すことだけ
    （判定情報 last_decision_info を読むため）。tests/test_selfplay_runner.py が AST で本体の一致を固定する。"""
    strategy_class = STRATEGY_REGISTRY.get(ai_mode)
    if strategy_class is None:
        game.katrain.log(f"AI strategy '{ai_mode}' not found, falling back to '{AI_DEFAULT}'", OUTPUT_ERROR)
        strategy_class = STRATEGY_REGISTRY[AI_DEFAULT]
    strategy = strategy_class(game, ai_settings)

    game.katrain.log(f"Generating move using {strategy.__class__.__name__} (mode {ai_mode})", OUTPUT_DEBUG)
    try:
        move, ai_thoughts = strategy.generate_move()
    except AnalysisDiscardedException as e:
        game.katrain.log(f"Discarding AI move: {e}", OUTPUT_DEBUG)
        return None, None, strategy

    played_node = game.play(move, expected_node=strategy.cn)
    if played_node is None:
        game.katrain.log(f"Discarding AI move {move.gtp()}: position changed", OUTPUT_DEBUG)
        return move, None, strategy
    played_node.ai_thoughts = ai_thoughts
    game.katrain.log(f"Move generation complete: {move.gtp()} -- {ai_thoughts}", OUTPUT_DEBUG)
    return move, played_node, strategy


class StrategyOpponent:
    """`--opponent strategy:<名前>[:k=v,...]`: 登録済み戦略を相手にする（例: 強い・フィルタつきの HumanStyle）。"""

    def __init__(self, arm):
        self.arm = arm
        self.stats = {"moves": 0}

    @property
    def label(self):
        return f"strategy:{self.arm.strategy}"

    def play(self, game, waiter):
        waiter.nodes(game.current_node.nodes_from_root, "path analysis before the opponent strategy")
        move, played, _ = _ai_turn(game, self.arm.mode, self.arm.settings)
        if played is None:
            raise GameAborted(f"opponent strategy {self.arm.strategy} discarded its move")
        self.stats["moves"] += 1
        return played


def make_opponent(opponent_plan, spec, opponent_arm=None):
    if opponent_plan["kind"] == "strategy":
        return StrategyOpponent(opponent_arm)
    opponent = HumanSLOpponent(
        spec["rank"], tau=opponent_plan.get("tau", 1.0), seed=spec["opp_seed"], max_loss=opponent_plan.get("max_loss")
    )
    if opponent_plan.get("book_moves"):  # 定跡を知る相手（spec §16.2 手順6）: プールの humanSL を包む
        loss = opponent_plan.get("book_loss")
        return BookOpponent(opponent, opponent_plan["book_moves"], S.BOOK_LOSS if loss is None else loss)
    return opponent


def drain_logs(stub):
    """stub.logs を空にして、残す行だけ返す（stub は全レベルを溜め続ける＝長時間の実行で膨らむ）。"""
    logs, stub.logs = stub.logs, []
    return [
        str(msg)
        for msg, level in logs
        if level == OUTPUT_ERROR or STRATEGY_LOG_RE.match(str(msg)) or any(m in str(msg) for m in KEEP_LOG_MARKERS)
    ]


def jsonable(obj):
    return None if obj is None else json.loads(json.dumps(obj, default=str))


def main_line(root):
    nodes = [root]
    while nodes[-1].children:
        nodes.append(nodes[-1].children[0])
    return nodes


def compute_reports(game, thresholds, ai_color):
    """両者の report（WATCH / STRICT × 全体・GUI の3区間・校正用の3区間）。本物の game_report を呼ぶだけ。"""
    opp_color = "W" if ai_color == "B" else "B"
    out = {}
    for tree in ("WATCH", "STRICT"):
        out[tree] = {}
        for name, depth_filter in S.REPORT_BINS:
            if tree == "WATCH":
                with S.watch_prune(game):
                    sum_stats, _, ptloss = game_report(game, thresholds, depth_filter=depth_filter)
            else:
                sum_stats, _, ptloss = game_report(game, thresholds, depth_filter=depth_filter)
            out[tree][name] = {
                "ai": S.report_block(sum_stats, ptloss, ai_color),
                "opp": S.report_block(sum_stats, ptloss, opp_color),
            }
    return out


class Harness:
    """1プロセス・1エンジンで局を回す（spec §2）。盤の条件と待ちの設定を持つ。"""

    def __init__(self, stub, engine, size, komi=7.0, rules="chinese", watchdog=None, timeout=180.0, watch_flags=False):
        if stub.config("game/handicap"):
            raise SystemExit(
                "selfplay assumes even games: config game/handicap is non-zero "
                "(BaseGame places config handicap stones even with game_properties)"
            )
        self.stub = stub
        self.engine = engine
        self.size = size
        self.komi = komi
        self.rules = rules
        self.watchdog = watchdog
        self.timeout = timeout
        self.watch_flags = watch_flags
        self.thresholds = stub.config("trainer/eval_thresholds")
        self.trainer_config = {**(stub.config("trainer") or {}), "save_analysis": True}
        self.max_visits = (stub.config("engine") or {}).get("max_visits")

    def waiter(self):
        return Waiter(self.engine, self.timeout, self.watchdog)


@dataclasses.dataclass
class GameResult:
    record: dict
    rows: list
    logs: list
    game: object


def _veil_extras(arm, game):
    """韜晦のアームだけ: reserve（設定）と ledger（game._veil_state[KEY_PREFIX]["ledger"]）。他の戦略は (None, None)。"""
    cls = STRATEGY_REGISTRY.get(arm.mode)
    prefix = getattr(cls, "KEY_PREFIX", None)
    defaults = getattr(cls, "SETTING_DEFAULTS", None) or {}
    reserve = arm.settings.get(f"{prefix}_reserve", defaults.get("reserve")) if prefix else None
    ledger = ((getattr(game, "_veil_state", None) or {}).get(prefix) or {}).get("ledger") if prefix else None
    return reserve, ledger


@contextlib.contextmanager
def _abort_on_exception(what):
    """with の中の予期しない例外をこの局の aborted（GameAborted）に変える＝実行全体は止めない。GameAborted はそのまま通す。"""
    try:
        yield
    except GameAborted:
        raise
    except Exception as e:
        raise GameAborted(f"{what} exception: {e!r}") from e


def play_game(h, arm, spec, opponent, *, komi_shift=0.0, max_moves=None, hooks=(), target=None):
    """1局打って GameResult を返す。例外で落ちない（エンジン停止・タイムアウト・AI と相手とフックの例外は aborted）。

    hooks: before_ai(game, cn, waiter) -> dict（AI の着手前・同じ局面）/ after_ai(game, strategy, move, waiter) -> dict
    （着手後）を持つオブジェクト。戻り値の dict はその手番の記録に足す（所要時間の集計には入らない）。
    ERROR_FIELD（games.jsonl の列名）と errors（失敗の数）を持つフックは、この局の間に増えた分をその列に書く
    （S.INTEGRITY_HOOK_ERRORS の列はフックが無くても 0 で書く）。
    """
    size = h.size
    ai = spec["ai_color"]
    opp_color = "W" if ai == "B" else "B"
    komi = h.komi + (komi_shift if ai == "B" else -komi_shift)  # komi_shift は AI 不利の向き
    random.seed(spec["strategy_seed"])  # 戦略側の Python 乱数（ai.py はグローバルの random を使う）
    waiter = h.waiter()
    h.engine.on_new_game()  # GUI の新規対局（__main__._do_new_game）と同じく前局の残りのクエリを捨てる
    game = Game(h.stub, h.engine, game_properties={"SZ": size, "KM": komi, "RU": h.rules})
    h.stub.game = game
    h.stub.players_info[ai].name = f"AI {arm.name} ({arm.strategy})"
    h.stub.players_info[opp_color].name = opponent.label
    if h.watch_flags:
        game.board_watch_active = True
    cap = max_moves or S.move_cap(size)
    turns, logs = [], []
    streak, end_reason, error = 0, None, None
    hook_errors_at_start = [getattr(hook, "errors", 0) for hook in hooks]
    started = time.time()
    try:
        while True:
            cn = game.current_node
            if cn.is_pass and cn.parent is not None and cn.parent.is_pass:
                end_reason = "double_pass"
                break
            if cn.depth >= cap:
                end_reason = "move_cap"
                break
            if cn.next_player == ai:
                t0 = time.time()
                waiter.nodes(cn.nodes_from_root, "path analysis before the AI move")
                wait_s = time.time() - t0
                lead, wr = S.ai_view_lead(cn.score, ai), S.ai_view_winrate(cn.winrate, ai)
                resign, streak = S.selfplay_resign_check(spec, cn.depth, lead, wr, streak, size)
                if resign:
                    end_reason = "opp_resign"
                    break
                extra = {}
                for hook in hooks:
                    if hasattr(hook, "before_ai"):
                        with _abort_on_exception(f"hook {type(hook).__name__}.before_ai"):
                            extra.update(hook.before_ai(game, cn, waiter))
                t1 = time.time()
                with _abort_on_exception("AI"):
                    move, played, strategy = _ai_turn(game, arm.mode, arm.settings)
                strategy_s = time.time() - t1
                if played is None:
                    raise GameAborted("AI move discarded (analysis discarded or position changed)")
                cands = strategy.cn.candidate_moves
                turn = {
                    "depth": played.depth,
                    "wait_s": wait_s,
                    "strategy_s": strategy_s,
                    "best_at_decision": cands[0]["move"] if cands else None,
                    "played": move.gtp(),
                    "decision": jsonable(getattr(strategy, "last_decision_info", None)),
                    **extra,
                }
                for hook in hooks:
                    if hasattr(hook, "after_ai"):
                        with _abort_on_exception(f"hook {type(hook).__name__}.after_ai"):
                            turn.update(hook.after_ai(game, strategy, move, waiter))
                turns.append(turn)
            else:
                with _abort_on_exception("opponent"):  # 相手の戦略のバグでも実行全体を止めない（その局だけ aborted）
                    opponent.play(game, waiter)
            logs.extend(drain_logs(h.stub))
    except GameAborted as e:
        end_reason, error = "aborted", str(e)
    logs.extend(drain_logs(h.stub))
    wall_s = time.time() - started
    nodes = main_line(game.root)
    if end_reason != "aborted":
        try:
            waiter.nodes(nodes, "final analysis of all nodes")
        except GameAborted as e:
            end_reason, error = "aborted", str(e)
    if end_reason == "opp_resign":
        game.current_node.end_state = f"{ai}+R"
    reports = compute_reports(game, h.thresholds, ai) if end_reason != "aborted" else {}
    rows = S.merge_turns(S.selfplay_move_rows(nodes[1:], ai, size, h.max_visits), turns)
    hook_errors = dict.fromkeys(S.INTEGRITY_HOOK_ERRORS, 0)
    for hook, at_start in zip(hooks, hook_errors_at_start):
        field = getattr(hook, "ERROR_FIELD", None)
        if field:
            hook_errors[field] = hook_errors.get(field, 0) + getattr(hook, "errors", 0) - at_start
    meta = {
        "arm": arm.name,
        "strategy": arm.strategy,
        "seed": spec["seed"],
        "index": spec["index"],
        "ai_color": ai,
        "rank": spec["rank"],
        "opponent": opponent.label,
        "opponent_stats": dict(getattr(opponent, "stats", {})),
        **hook_errors,
        "komi": komi,
        "size": size,
        "resign_model": S.resign_model_of(spec),
        "resign_lead": spec.get("resign_lead"),
        "resign_len": spec.get("resign_len"),
        "end_reason": end_reason,
        "error": error,
    }
    reserve, ledger = _veil_extras(arm, game)
    goal = S.TARGET_RATE.get(size, 0.30) if target is None else target
    record = S.selfplay_game_summary(meta, reports, rows, goal, reserve=reserve, ledger=ledger, wall_s=wall_s)
    return GameResult(record=record, rows=rows, logs=logs, game=game)


def report_sgf(stub, engine, path, timeout=1200.0):
    """実戦の保存 SGF（KT 解析つきならそれを使う＝GUI で開いたのと同じ）から両者のレポートを出す。

    本譜（children[0]）の全ノードの解析完了を待ち、compute_reports を黒＝"ai"・白＝"opp" で呼ぶ。
    """
    root = KaTrainSGF.parse_file(path)
    game = Game(stub, engine, move_tree=root)
    stub.game = game
    nodes = main_line(root)
    Waiter(engine, timeout).nodes(nodes, "analysis of the SGF main line")
    return {
        "file": path,
        "moves": len(nodes) - 1,
        "reports": compute_reports(game, stub.config("trainer/eval_thresholds"), "B"),
    }
