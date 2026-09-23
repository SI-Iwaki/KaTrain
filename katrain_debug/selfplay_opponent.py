"""自己対局ハーネスの相手ボット（humanSL 1visit のサンプラー）と待ちループ。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md §2（待ちループ）・§3（相手ボット）
"""

import os

os.environ.setdefault("KIVY_NO_ARGS", "1")

import random  # noqa: E402
import time  # noqa: E402

from katrain.core.ai import _area_scoring_should_pass  # noqa: E402
from katrain.core.constants import OUTPUT_ERROR, PRIORITY_EXTRA_AI_QUERY  # noqa: E402
from katrain.core.game import IllegalMoveException  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402


class GameAborted(Exception):
    """この局を aborted にする（エンジン停止・再起動・待ちのタイムアウト・AI の例外）。"""


class Waiter:
    """待ちループの共通部分（1局に1つ）。毎回 engine.check_alive() と watchdog の再起動回数を見る。

    KataGoEngine.check_alive() は死んでいても例外を投げず False を返すだけ（engine.py:242-259）なので、
    戻り値を見ないと死んだエンジンを永遠に待つ。
    """

    def __init__(self, engine, timeout=180.0, watchdog=None):
        self.engine = engine
        self.timeout = timeout
        self.watchdog = watchdog
        self.generation = watchdog.restarts if watchdog is not None else None
        self.humansl_error = None  # 直前の humansl() の失敗の理由（成功なら None）

    def until(self, pred, what, poll=0.01):
        started = time.time()
        while not pred():
            if not self.engine.check_alive():
                raise GameAborted(f"engine died while waiting for {what}")
            if self.watchdog is not None and self.watchdog.restarts != self.generation:
                raise GameAborted(f"engine restarted while waiting for {what}")
            if time.time() - started > self.timeout:
                raise GameAborted(f"timeout ({self.timeout:.0f}s) while waiting for {what}")
            time.sleep(poll)

    def nodes(self, nodes, what="node analysis"):
        self.until(lambda: all(n.analysis_complete for n in nodes), what)

    def humansl(self, node, profile, visits=1):
        """humanSL を1本撃って結果（KataGo の JSON）を返す。ノードには書き戻さない（コールバックで受けるだけ）。

        失敗（KataGo のエラー応答＝None を返す・humanPolicy の無い応答）の理由は self.humansl_error に残す（成功なら None）。
        数えてログに出すのは呼び出し側（相手ボット・hp 監査）。until() が例外を投げても前回の値が残らないよう、
        待ち始める前にリセットする。
        """
        self.humansl_error = None
        out = {}

        def on_result(analysis, partial_result):
            if not partial_result:
                out["a"] = analysis

        def on_error(analysis):
            out["err"] = analysis

        self.engine.request_analysis(
            node,
            callback=on_result,
            error_callback=on_error,
            visits=visits,
            priority=PRIORITY_EXTRA_AI_QUERY,
            ownership=False,
            include_policy=True,
            time_limit=False,
            extra_settings={"humanSLProfile": profile, "ignorePreRootHistory": False},
        )
        self.until(lambda: "a" in out or "err" in out, f"humanSL {profile}")
        analysis = out.get("a")
        if "err" in out:
            err = out["err"]
            self.humansl_error = str(err.get("error", err)) if isinstance(err, dict) else str(err)
        elif not (analysis or {}).get("humanPolicy"):
            self.humansl_error = "no humanPolicy"
        else:
            self.humansl_error = None
        return analysis


class HumanSLOpponent:
    """実戦の相手を模したボット（spec §3・戦略登録はしない）。

    毎手 humanSL を visits 本（既定 1）で1本撃ち、局ごとに seed を固定した random.Random で hp^(1/τ) に比例して
    引く。非合法手は捨てて引き直す。パスが引かれたら現局面の通常解析を待ち、候補のパスの pointsLost を
    _area_scoring_should_pass に渡して真ならパス、偽かパスが候補に無ければパスを外して引き直す。
    max_loss（既定 None＝OFF）は通常解析で pointsLost <= max_loss の手だけを残す（強め・慎重な相手の層）。
    humanSL が失敗したら（エラー応答・humanPolicy なし）局は止めずに KataGo の最善手で打つが、stats の humansl_errors に
    数えて OUTPUT_ERROR でログに出す（最善手で打った手は相手の一致率を上げる＝要約が WARN を出す）。fallbacks は最善手で
    打った回数（humanSL の失敗と、max_loss で候補が空になった場合の両方）。
    """

    def __init__(self, profile, tau=1.0, seed=0, max_loss=None, visits=1):
        self.profile = profile
        self.tau = tau
        self.rng = random.Random(seed)
        self.max_loss = max_loss
        self.visits = visits
        self.stats = {"moves": 0, "pass_redraws": 0, "illegal_redraws": 0, "fallbacks": 0, "humansl_errors": 0}

    @property
    def label(self):
        return f"humanSL:{self.profile}"

    def play(self, game, waiter):
        cn = game.current_node
        player = cn.next_player
        size = game.board_size[0]
        analysis = waiter.humansl(cn, self.profile, self.visits)
        if waiter.humansl_error is not None:
            self.stats["humansl_errors"] += 1
            game.katrain.log(
                f"selfplay: opponent humanSL failed: {self.profile} at move {cn.depth}: {waiter.humansl_error}",
                OUTPUT_ERROR,
            )
        cands = S.hp_to_cands((analysis or {}).get("humanPolicy") or [], size)
        if self.max_loss is not None and cands:
            waiter.nodes([cn], "opponent max_loss filter")
            allowed = {d["move"] for d in cn.candidate_moves if d["pointsLost"] <= self.max_loss}
            cands = [(k, p) for k, p in cands if S.key_to_gtp(k) in allowed]
        if not cands:
            self.stats["fallbacks"] += 1
            waiter.nodes([cn], "opponent fallback")
            best = cn.candidate_moves[0]["move"] if cn.candidate_moves else "pass"
            cands = [(S.gtp_to_key(best), 1.0)]

        def to_move(key):
            return Move(None, player=player) if key == "pass" else Move(key, player=player)

        def try_move(key):
            try:
                return game.play(to_move(key))
            except IllegalMoveException:
                self.stats["illegal_redraws"] += 1
                return None

        def pass_ok():
            waiter.nodes([cn], "opponent pass check")
            pass_d = next((d for d in cn.candidate_moves if d["move"] == "pass"), None)
            pass_loss = None if pass_d is None else pass_d["pointsLost"]
            ok = _area_scoring_should_pass([(to_move(k), p) for k, p in cands], pass_loss)
            if not ok:
                self.stats["pass_redraws"] += 1
            return ok

        _, node = S.selfplay_opponent_pick(cands, self.rng, self.tau, try_move, pass_ok)
        if node is None:
            node = game.play(Move(None, player=player))
        self.stats["moves"] += 1
        return node
