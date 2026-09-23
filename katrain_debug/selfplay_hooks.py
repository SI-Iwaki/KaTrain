"""自己対局ハーネスの追加の計器: hp 監査（spec §4）と影判定（spec §6 --shadow）。

どちらも play_game の hooks（before_ai / after_ai）で、所要時間（strategy_s）の集計には入らない。
"""

import os
import random
import time

os.environ.setdefault("KIVY_NO_ARGS", "1")

from katrain.core.ai import STRATEGY_REGISTRY, AnalysisDiscardedException  # noqa: E402
from katrain.core.constants import AI_DEFAULT, OUTPUT_ERROR  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.selfplay_game import jsonable  # noqa: E402
from katrain_debug.selfplay_opponent import GameAborted  # noqa: E402

# 戦略が game に載せる sticky な状態（影判定で A と B を入れ替える対象）。固定名＋接頭辞で拾う
SHADOW_FIXED_ATTRS = (
    "_veil_state",
    "_enigma_ponder",
    "_enigma_ponder_gen",
    "_enigma_ponder_owner",
    "board_watch_probe_warm",
)
SHADOW_ATTR_PREFIXES = ("_veil", "_enigma", "_mimic", "_parity9", "_jigo")
SHADOW_DEFAULTS = {"board_watch_probe_warm": False}  # Game.__init__ が持つ初期値（B の初回用）


def shadow_state_keys(names):
    return sorted({n for n in names if n in SHADOW_FIXED_ATTRS or n.startswith(SHADOW_ATTR_PREFIXES)})


def run_shadow(game, arm, store):
    """アーム B（arm）の戦略を同じ局面で実行し、選んだ手・そのコスト（通常解析の pointsLost）・判定情報だけ返す（打たない）。

    store は B 専用の影の状態（game._shadow_state[arm.name]・局をまたがない）。B の実行前に A の sticky 属性を
    退避して B の状態を載せ、実行後に B の状態を store へ書き戻してから A の属性とグローバル乱数を戻す。
    追加クエリ（_run_query / _probe_children）は結果をノードに書き戻さないので本譜の解析は汚れない。
    """
    names = list(vars(game))
    keys = shadow_state_keys(names + list(store))
    saved = {k: getattr(game, k) for k in keys if k in vars(game)}
    rng_state = random.getstate()
    for k in keys:
        if k in vars(game):
            delattr(game, k)
    for k, v in {**SHADOW_DEFAULTS, **store}.items():
        setattr(game, k, v)
    started = time.time()
    try:
        strategy_class = STRATEGY_REGISTRY.get(arm.mode) or STRATEGY_REGISTRY[AI_DEFAULT]
        strategy = strategy_class(game, arm.settings)
        move, _ = strategy.generate_move()
        cands = game.current_node.candidate_moves  # 打たないので current_node は A と同じ局面のまま
        result = {
            "arm": arm.name,
            "move": move.gtp(),
            "vloss": next((d["pointsLost"] for d in cands if d["move"] == move.gtp()), None),  # B の手のコスト
            "decision": jsonable(getattr(strategy, "last_decision_info", None)),
            "secs": time.time() - started,
        }
    except AnalysisDiscardedException as e:
        raise GameAborted(f"shadow {arm.name}: analysis discarded ({e})") from e
    except Exception as e:  # 影の失敗で本番の局を止めない（行の error とログに残し、ShadowHook が局ごとに数える）
        game.katrain.log(f"selfplay: shadow failed: {arm.name} at move {game.current_node.depth}: {e!r}", OUTPUT_ERROR)
        result = {"arm": arm.name, "move": None, "error": repr(e), "secs": time.time() - started}
    finally:
        after = shadow_state_keys(list(vars(game)))
        store.clear()
        store.update({k: getattr(game, k) for k in after})
        for k in after:
            delattr(game, k)
        for k, v in saved.items():
            setattr(game, k, v)
        random.setstate(rng_state)
    return result


class ShadowHook:
    """AI（アーム A）の各手番の前に、同じ局面でアーム B の戦略を走らせて記録する。

    errors は影の失敗の数（play_game がその局の分を games.jsonl の ERROR_FIELD に書く）。
    """

    ERROR_FIELD = "shadow_errors"

    def __init__(self, arm):
        self.arm = arm
        self.errors = 0

    def before_ai(self, game, cn, waiter):
        stores = game.__dict__.setdefault("_shadow_state", {})
        result = run_shadow(game, self.arm, stores.setdefault(self.arm.name, {}))
        if "error" in result:
            self.errors += 1
        return {"shadow": result}


class HpAuditHook:
    """AI の全着手の親局面に humanSL（既定 rank_9d）を 1visit で撃ち、選んだ手と最善手の hp・順位を記録する。

    humanSL が失敗した手番は値を None にしてログに出し、errors に数える（play_game がその局の分を games.jsonl の
    ERROR_FIELD に書く）。
    """

    ERROR_FIELD = "hp_audit_errors"

    def __init__(self, profile="rank_9d"):
        self.profile = profile
        self.errors = 0

    def after_ai(self, game, strategy, move, waiter):
        cands = strategy.cn.candidate_moves
        best = cands[0]["move"] if cands else None
        analysis = waiter.humansl(strategy.cn, self.profile, visits=1)
        if waiter.humansl_error is not None:
            self.errors += 1
            game.katrain.log(
                f"selfplay: hp-audit failed: {self.profile} at move {strategy.cn.depth}: {waiter.humansl_error}",
                OUTPUT_ERROR,
            )
            return {"hp_played": None, "hp_best": None, "hp_rank": None}
        return S.hp_audit_values(analysis["humanPolicy"], game.board_size[0], move.gtp(), best)


def make_hooks_factory(plan, arms):
    """execute_plan の hooks_builder。plan["shadow"]（アーム名）と plan["hp_audit"]（humanSL の段位）を読む。"""
    shadow_name = plan.get("shadow")
    profile = plan.get("hp_audit")

    def factory(arm_name):
        hooks = []
        if shadow_name and shadow_name != arm_name:
            hooks.append(ShadowHook(arms[shadow_name]))
        if profile:
            hooks.append(HpAuditHook(profile))
        return hooks

    return factory
