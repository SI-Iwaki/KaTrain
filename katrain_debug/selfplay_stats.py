"""自己対局ハーネスの純関数（KataGo・Kivy・katrain 本体に依存しない）。

設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md
対局の実行は selfplay_game.py、CLI は selfplay.py。ここはテストで数値を固定できるものだけを置く。
"""

import hashlib
import itertools
import json
import math
import random
import re
import statistics
from collections import Counter
from contextlib import contextmanager

# ---- 盤サイズ別の定数（spec §2 終局・§3 投了・§5 出力）----
MOVE_CAP = {9: 120, 13: 250, 19: 400}  # 手数上限（上限では最終 scoreLead で勝敗）
TARGET_RATE = {9: 0.40, 13: 0.30, 19: 0.30}  # 韜晦の一致率目標 T（own_le_target_plus5 の T）
RATE_FLOOR = 0.15  # own_lt_floor の床
TARGET_SLACK = 0.05  # own_le_target_plus5 の +0.05
RESIGN_START_13 = 40  # 投了判定の開始手数（13路。他の盤は盤面積で比例）
RESIGN_MIN_WINRATE = 0.95  # 投了の AI 勝率条件（lead モデル）
RESIGN_STREAK = 2  # AI の手番で何回続いたら投了するか
RESIGN_LEN_MIN_WINRATE = 0.90  # length モデル: 目標の手数 L 以降に「AI の明らかな勝ち」とみなす AI 勝率
RESIGN_LEN_MIN_LEAD = 2.5  # length モデル: 同じく AI 視点のリード（目）
VISITS_CHECK_RATIO = 0.9  # root visits が max_visits のこの倍率未満なら visits_low
BLUNDER_TAILS = (1.0, 2.0, 3.0, 6.0)  # AI の失着の尾（目）
HP_AUDIT_LOW = 0.05  # 外した手の 9段 hp がこれ未満の割合を出す
# 計測の健全性（要約の WARN integrity）: 相手ボットの stats の数と、計器（フック）の失敗の数（games.jsonl の列）
INTEGRITY_OPPONENT_STATS = ("fallbacks", "humansl_errors")
INTEGRITY_HOOK_ERRORS = ("hp_audit_errors", "shadow_errors")
GTP_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

# game_report の depth_filter（盤面積の割合。game_report が ceil(frac * x * y) で手数に直す）
GUI_BINS = (("all", None), ("gui_opening", (0, 0.14)), ("gui_middle", (0.14, 0.4)), ("gui_endgame", (0.4, 10)))
CALIB_BINS = (
    ("cal_opening", (0, 24 / 169)),
    ("cal_middle", (24 / 169, 85 / 169)),
    ("cal_endgame", (85 / 169, 10)),
)
REPORT_BINS = GUI_BINS + CALIB_BINS

# 校正目標（13路の実戦・事後 2500v。spec §3 の表）
CALIB_TARGETS_13 = {
    "opp_mean": 0.231,
    "opp_sd": 0.065,
    "opp_loss": 1.77,
    "opp_ge2": 0.28,
    "opp_ge5": 0.10,
    "ai_mean": 0.533,
    "moves_median": 78.5,
    "bins": {
        "cal_opening": {"opp_top1": 0.267, "opp_loss": 0.56},
        "cal_middle": {"opp_top1": 0.182, "opp_loss": 2.43},
        "cal_endgame": {"opp_top1": 0.291, "opp_loss": 0.96},
    },
}
POOL_TOLERANCE = {"opp_mean": 0.01, "opp_sd": 0.02, "opp_loss": 0.25}  # プール選択のスコアの尺度


# ---- 盤サイズ ----
def move_cap(size):
    return MOVE_CAP.get(size, round(250 * size * size / 169))


def scale_moves_13(moves, size):
    """13路の手数を盤面積で比例させる（9路 ×81/169・19路 ×361/169）。"""
    return round(moves * size * size / 169)


def resign_start_move(size):
    """13路 40 を盤面積で比例（9路 19・19路 85）。"""
    return scale_moves_13(RESIGN_START_13, size)


def depth_bin(depth, size, bins=CALIB_BINS):
    """手数 depth が入る区間名（game_report と同じ ceil(frac * x * y) の半開区間）。"""
    for name, rng in bins:
        if rng is None:
            continue
        lo, hi = (math.ceil(f * size * size) for f in rng)
        if lo <= depth < hi:
            return name
    return None


# ---- 座標 ----
def gtp_to_key(gtp):
    """'D4' -> (3, 3)・'pass' -> 'pass'（Move.from_gtp と同じ座標）。"""
    if gtp.lower() == "pass":
        return "pass"
    return (GTP_LETTERS.index(gtp[0].upper()), int(gtp[1:]) - 1)


def key_to_gtp(key):
    if key == "pass":
        return "pass"
    x, y = key
    return f"{GTP_LETTERS[x]}{y + 1}"


def hp_index(key, size):
    """humanPolicy のフラット配列の添字（ai.py enigma9_hp_lookup と同じ。pass は末尾）。"""
    if key == "pass":
        return size * size
    x, y = key
    return (size - 1 - y) * size + x


def hp_to_cands(human_policy, size):
    """humanPolicy -> [(key, p)]（p > 0 のみ。非合法点の -1 と 0 は落とす）。"""
    cands = []
    for i, p in enumerate(human_policy[: size * size]):
        if p > 0:
            cands.append(((i % size, size - 1 - i // size), p))
    if len(human_policy) > size * size and human_policy[size * size] > 0:
        cands.append(("pass", human_policy[size * size]))
    return cands


def hp_audit_values(human_policy, size, played_gtp, best_gtp):
    """hp 監査の1手分: 選んだ手と最善手の hp、選んだ手の hp 順位（1 始まり・pass 込み）。"""

    def hp_of(gtp):
        if gtp is None:
            return None
        idx = hp_index(gtp_to_key(gtp), size)
        return max(0.0, human_policy[idx]) if idx < len(human_policy) else 0.0

    hp_played = hp_of(played_gtp)
    rank = None
    if hp_played is not None:
        rank = 1 + sum(1 for p in human_policy[: size * size + 1] if p > hp_played)
    return {"hp_played": hp_played, "hp_best": hp_of(best_gtp), "hp_rank": rank}


# ---- 日程（seed → 色・段位・投了閾値・乱数の種）----
def selfplay_schedule(
    n_seeds, ranks, seed_base=1000, resign_leads=None, resign_range=None, no_resign=False, resign_lens=None
):
    """局ごとの開始条件。seed が同じなら全アームで同じ条件（A/B の対）。

    色は seed の偶奇で交互、段位は2局（黒白1局ずつ）ごとに ranks を巡回＝段位と色が交絡しない。
    投了は2つのモデルのどちらか（no_resign ならどちらも None）:
    - length（`resign_lens` を渡したとき）: 目標の手数 L を実戦の手数（`resign_lens`）から復元抽出（resign_len）。
    - lead: 閾値 R を `resign_range` (lo, hi) の一様か、`resign_leads`（実戦の投了局の最終リード）の復元抽出（resign_lead）。
    相手の乱数列と戦略の乱数の種は投了のモデルによらず seed だけで決まる（モデルを変えても局の対は同じ）。
    """
    if not ranks:
        raise ValueError("ranks is empty")
    out = []
    for i in range(n_seeds):
        seed = seed_base + i
        rng = random.Random(seed)
        opp_seed = rng.randrange(2**31)
        strategy_seed = rng.randrange(2**31)
        resign_lead = resign_len = None
        if no_resign:
            pass
        elif resign_lens:
            resign_len = rng.choice(list(resign_lens))
        elif resign_range is not None:
            resign_lead = rng.uniform(resign_range[0], resign_range[1])
        elif resign_leads:
            resign_lead = rng.choice(list(resign_leads))
        out.append(
            {
                "index": i,
                "seed": seed,
                "ai_color": "B" if i % 2 == 0 else "W",
                "rank": ranks[(i // 2) % len(ranks)],
                "opp_seed": opp_seed,
                "strategy_seed": strategy_seed,
                "resign_lead": resign_lead,
                "resign_len": resign_len,
            }
        )
    return out


def schedule_balance_warning(schedule, ranks):
    """段位 × 色の層の局数が揃わないときの警告文（spec §3: 相手の段位は層別に同数）。揃っていれば None。

    段位は2局ごとに巡回するので、seed の数が 2 × 段位数 の倍数でないと層の局数がずれる（例 20 seed × 3段位 = 8/6/6局）。
    """
    cells = Counter((s["rank"], s["ai_color"]) for s in schedule)
    wanted = [(r, c) for r in dict.fromkeys(ranks) for c in ("B", "W")]
    if len({cells.get(k, 0) for k in wanted}) <= 1:
        return None
    per_rank = Counter(s["rank"] for s in schedule)
    counts = "/".join(str(per_rank.get(r, 0)) for r in dict.fromkeys(ranks))
    return (
        f"warning: {len(schedule)} seeds over {len(set(ranks))} ranks x 2 colours is unbalanced ({counts} games); "
        f"use a number of seeds that is a multiple of {2 * len(set(ranks))}"
    )


def abba_order(arm_names, n_seeds, block=10):
    """[(arm, index)]。block 個の seed ごとにアームの順を反転（2アームなら A B B A …）。"""
    order = []
    for b in range(math.ceil(n_seeds / block)):
        idxs = range(b * block, min((b + 1) * block, n_seeds))
        arms = list(arm_names) if b % 2 == 0 else list(reversed(arm_names))
        for arm in arms:
            order.extend((arm, i) for i in idxs)
    return order


# ---- 相手ボットの1手 ----
def selfplay_opponent_pick(cands, rng, tau, try_move, pass_ok):
    """hp^(1/τ) に比例して1手引き、打てなければ捨てて引き直す。

    cands: [(key, p)]（hp_to_cands の出力。key は (x, y) か "pass"）。
    try_move(key) -> 打てたら None 以外（呼んだ時点で盤に打たれる）・非合法なら None。
    pass_ok() -> パスしてよいか（パスが引かれたときだけ最大1回呼ぶ）。偽ならパスを外して引き直す。
    返り値 (key, try_move の戻り値)。候補が尽きたら (None, None)。
    """
    pool = list(cands)
    pass_allowed = None
    while pool:
        weights = [p ** (1.0 / tau) for _, p in pool]
        r = rng.random() * sum(weights)
        k = len(pool) - 1
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if acc >= r:
                k = i
                break
        key = pool[k][0]
        if key == "pass":
            if pass_allowed is None:
                pass_allowed = bool(pass_ok())
            if not pass_allowed:
                pool.pop(k)
                continue
        result = try_move(key)
        if result is not None:
            return key, result
        pool.pop(k)
    return None, None


# ---- 投了・勝敗 ----
def ai_view_lead(score_black, ai_color):
    return None if score_black is None else score_black * (1 if ai_color == "B" else -1)


def ai_view_winrate(wr_black, ai_color):
    return None if wr_black is None else (wr_black if ai_color == "B" else 1.0 - wr_black)


def _confirm_resign(qualifies, streak):
    """2手番の確認: 条件を満たす AI の手番が RESIGN_STREAK 回続いたら投了。返り値 (投了するか, 新しい連続回数)。"""
    streak = streak + 1 if qualifies else 0
    return streak >= RESIGN_STREAK, streak


def selfplay_should_resign(depth, lead_ai, wr_ai, streak, threshold, size):
    """相手の投了判定・lead モデル（AI の手番ごとに呼ぶ）。返り値 (投了するか, 新しい連続回数)。

    開始手数以降に AI 視点で lead >= threshold かつ AI 勝率 >= 0.95 が AI の2手番続いたら投了。
    threshold None（--no-resign）なら投了しない。
    """
    if threshold is None or lead_ai is None or wr_ai is None or depth < resign_start_move(size):
        return False, 0
    return _confirm_resign(lead_ai >= threshold and wr_ai >= RESIGN_MIN_WINRATE, streak)


def selfplay_should_resign_at_length(depth, lead_ai, wr_ai, streak, target_len):
    """相手の投了判定・length モデル（AI の手番ごとに呼ぶ）。返り値 (投了するか, 新しい連続回数)。

    手数 depth >= 目標の手数 L（target_len）の AI の手番で、AI が明らかに勝っている（AI 勝率 >= 0.90 かつ
    AI 視点のリード >= 2.5 目）状態が AI の2手番続いたら投了する。L の時点で明らかな勝ちでなければ、その後の
    AI の手番でも見続ける（2連続パスか手数上限で終わることもある）。target_len None なら投了しない。
    """
    if target_len is None or lead_ai is None or wr_ai is None or depth < target_len:
        return False, 0
    return _confirm_resign(wr_ai >= RESIGN_LEN_MIN_WINRATE and lead_ai >= RESIGN_LEN_MIN_LEAD, streak)


def resign_model_of(spec):
    """日程の1局（または games.jsonl の1行）の投了モデル: length / lead / none。"""
    if spec.get("resign_len") is not None:
        return "length"
    if spec.get("resign_lead") is not None:
        return "lead"
    return "none"


def selfplay_resign_check(spec, depth, lead_ai, wr_ai, streak, size):
    """日程の1局のモデル（resign_len があれば length・無ければ resign_lead の lead）で投了を判定する。"""
    if spec.get("resign_len") is not None:
        return selfplay_should_resign_at_length(depth, lead_ai, wr_ai, streak, spec["resign_len"])
    return selfplay_should_resign(depth, lead_ai, wr_ai, streak, spec.get("resign_lead"), size)


def resign_pool_from_summaries(summaries, size):
    """実戦の report_game_*.json の summary 群 → 投了局の最終リード（AI 視点）の標本（lead モデル）。

    実戦の監視対局はパスで終わらない（相手の投了で終わる）ので全局を投了局とみなす。投了判定の開始手数
    （13路 40）未満で終わった局は除く。13路以外の盤は盤面積で比例させる（9路 ×81/169・19路 ×361/169）。
    """
    scale = size * size / 169
    out = []
    for s in summaries:
        if s.get("final_score") is None or s.get("n_moves", 0) < RESIGN_START_13:
            continue
        lead = s["final_score"] * (1 if s["ai"] == "B" else -1)
        out.append(round(lead * scale, 2))
    return out


def resign_lengths_from_summaries(summaries, size):
    """実戦の report_game_*.json の summary 群 → 局の手数（summary.n_moves）の標本（length モデル）。

    実戦の手数の分布そのもの（13路 18局・中央値 78.5）なので短い局も除かない。13路以外の盤は開始手数と同じく
    盤面積で比例させる（scale_moves_13）。
    """
    return [scale_moves_13(s["n_moves"], size) for s in summaries if s.get("n_moves")]


def selfplay_outcome(end_reason, final_lead_ai):
    """終局理由と最終 scoreLead（AI 視点）から AI の勝敗（win / loss / jigo / aborted / unknown）。"""
    if end_reason == "aborted":
        return "aborted"
    if end_reason == "opp_resign":
        return "win"
    if final_lead_ai is None:
        return "unknown"
    rounded = round(2 * final_lead_ai) / 2  # manual_score と同じ半目丸め
    if rounded > 0:
        return "win"
    if rounded < 0:
        return "loss"
    return "jigo"


# ---- WATCH 木（末尾のパスを除いた木）----
def main_line_end(node):
    while node.children:
        node = node.children[0]
    return node


@contextmanager
def watch_prune(game):
    """game_report を「最後の石で終わる木」で呼ぶためのコンテキスト（spec §2 WATCH）。

    game._lock の下で (1) 最後の石のノードの children を一時的に外し、(2) game.current_node を
    属性の直接代入でそのノードへ付け替える（set_current_node は _calculate_groups を走らせるので使わない）。
    finally で children と current_node の両方を必ず戻す。
    """
    with game._lock:
        original_current = game.current_node
        last = main_line_end(original_current)
        while last.parent is not None and last.is_pass:
            last = last.parent
        saved_children = last.children
        last.children = []
        game.current_node = last
        try:
            yield last
        finally:
            last.children = saved_children
            game.current_node = original_current


def report_block(sum_stats, player_ptloss, bw):
    """game_report の1色分を {top1, top5, mean_ptloss, n} に。手が無ければ値は None・n は 0。"""
    s = sum_stats.get(bw) or {}
    return {
        "top1": s.get("ai_top_move"),
        "top5": s.get("ai_top5_move"),
        "mean_ptloss": s.get("mean_ptloss"),
        "n": len(player_ptloss.get(bw) or []),
    }


# ---- 1手1行 ----
def selfplay_move_rows(nodes, ai_color, size, max_visits=None):
    """本譜の着手ノード（root を除く・時系列）を1手1行にする。一致・分母はレポートと同じ定義。

    match = 親の解析が完了していて candidate_moves[0] と着手が同じ。points_lost が None の手は
    レポートの分母に入らない（run_*_rate も同じ）。trailing_pass は最後の石より後のパス。
    """
    opp_color = "W" if ai_color == "B" else "B"
    last_stone = max((i for i, n in enumerate(nodes) if not n.is_pass), default=-1)
    tally = {"B": [0, 0], "W": [0, 0]}
    rows = []
    for i, n in enumerate(nodes):
        parent = n.parent
        cands = parent.candidate_moves if parent.analysis_complete else []
        best = cands[0]["move"] if cands else None
        gtp = n.move.gtp()
        match = best is not None and best == gtp
        pl = n.points_lost
        if pl is not None:
            tally[n.player][1] += 1
            tally[n.player][0] += int(match)
        visits = parent.root_visits
        rows.append(
            {
                "depth": n.depth,
                "player": n.player,
                "is_ai": n.player == ai_color,
                "move": gtp,
                "best": best,
                "match": match,
                "points_lost": pl,
                "loss": None if pl is None else max(0.0, pl),
                "lead_before_ai": ai_view_lead(parent.score, ai_color),
                "lead_after_ai": ai_view_lead(n.score, ai_color),
                "wr_before_ai": ai_view_winrate(parent.winrate, ai_color),
                "wr_after_ai": ai_view_winrate(n.winrate, ai_color),
                "parent_visits": visits,
                "visits_low": bool(max_visits) and visits < VISITS_CHECK_RATIO * max_visits,
                "best_prior": cands[0].get("prior") if cands else None,
                "bin": depth_bin(n.depth, size),
                "trailing_pass": i > last_stone,
                "run_own_rate": tally[ai_color][0] / tally[ai_color][1] if tally[ai_color][1] else None,
                "run_opp_rate": tally[opp_color][0] / tally[opp_color][1] if tally[opp_color][1] else None,
            }
        )
    return rows


def merge_turns(rows, turns):
    """AI 手番の記録（depth = AI の着手ノードの手数）を同じ depth の行に足す。"""
    by_depth = {t["depth"]: t for t in turns}
    for row in rows:
        turn = by_depth.get(row["depth"])
        if row["is_ai"] and turn is not None:
            row.update({k: v for k, v in turn.items() if k != "depth"})
    return rows


def flat_row(row):
    """moves.jsonl の1行: 判定情報（decision）と影判定（shadow）の dict を decision_* / shadow_* の列に平らにする。"""
    out = {k: v for k, v in row.items() if k not in ("decision", "shadow")}
    for prefix in ("decision", "shadow"):
        for k, v in (row.get(prefix) or {}).items():
            out[f"{prefix}_{k}"] = v
    return out


# ---- 1局の要約 ----
def percentile(values, q):
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# 韜晦の終局帯の手（tier "terminal"）。生の loss の上限（0.05〜0.10 目）で守る別枠で、支払う外しではない
VEIL_TERMINAL_KINDS = ("pass", "swap", "finish")


def _veil_unpaid(d):
    """支払う外しでない手（free・終局帯の手・序盤の研究外しの窓の手＝reserve を見ない設計の手。韜晦 spec §15.4）。"""
    return d.get("kind") == "free" or d.get("tier") in ("terminal", "opening") or d.get("kind") in VEIL_TERMINAL_KINDS


def _opening_metrics(decs):
    """序盤の研究外し（韜晦 spec §15.4）の窓の手番の要約。窓の記録（open / open_index）が1つも無ければ None。

    turns = 難解＋に任せた手番（open が played か invariant）・opening = そのうち best と違う手を打った手番（kind
    opening）・report_loss = 任せて打った手（open played）のレポートの損失の合計・ge2 / ge6 = その手のうち損失 2目 /
    6目以上の数・not_in_cands = 通常解析の候補に無い手を打った数（open_in_cands が偽）・gate = 関門で任せなかった手番・
    invariant = 任せた手が None / pass で最善手にした手番・errors = 窓の中の例外の手番（why exception）。
    """
    opened = [r for r in decs if "open" in r["decision"] or "open_index" in r["decision"]]
    if not opened:
        return None
    played = [r for r in opened if r["decision"].get("open") == "played"]
    losses = [r["loss"] for r in played if r["loss"] is not None]
    return {
        "turns": sum(1 for r in opened if r["decision"].get("open") in ("played", "invariant")),
        "opening": sum(1 for r in played if r["decision"].get("kind") == "opening"),
        "report_loss": sum(losses),
        "ge2": sum(1 for x in losses if x >= 2.0),
        "ge6": sum(1 for x in losses if x >= 6.0),
        "not_in_cands": sum(1 for r in played if r["decision"].get("open_in_cands") is False),
        "gate": sum(1 for r in opened if r["decision"].get("open") == "gate"),
        "invariant": sum(1 for r in opened if r["decision"].get("open") == "invariant"),
        "errors": sum(1 for r in opened if r["decision"].get("why") == "exception"),
    }


def _decision_metrics(ai_rows, rows, reserve, ledger):
    """判定情報（last_decision_info）を持つ戦略（韜晦）だけの指標。持たない戦略では None。

    期待するキー（韜晦の計画 plans/2026-09-23-veil-strategy.md の「共有インターフェース」）: tier / kind（free・paid・
    trap ほか）/ best / chosen / vloss / lead / E / close（無ければ lead < reserve で代用）。
    curse_by_kind = 外しの種類ごとの「レポートの損失 − 判定時の vloss」（spec §6 勝者の呪いの検出。正なら判定が甘い）。
    nonfree_below_reserve = lead < reserve で打った free でない外しの数（安全の警報）。終局帯の手（tier terminal か
    kind pass / swap / finish）と序盤の研究外しの窓の手（tier opening）は数えない。窓の手は opening（`_opening_metrics`）。
    vloss を持たない kind opening の vloss_by_kind・curse_by_kind は 0 ではなく None（ほかの kind は vloss が無くても 0）。
    """
    decs = [r for r in ai_rows if isinstance(r.get("decision"), dict) and r["decision"]]
    if not decs:
        return None

    def vl(d):
        v = d.get("vloss")
        return max(0.0, v) if _num(v) else 0.0

    infos = [r["decision"] for r in decs]
    dev_rows = [
        r
        for r in decs
        if r["decision"].get("chosen") is not None and r["decision"]["chosen"] != r["decision"].get("best")
    ]
    deviated = [r["decision"] for r in dev_rows]
    kinds = Counter(str(d.get("kind")) for d in infos)
    # vloss を持たない kind（序盤の研究外しの opening）は 0 ではなく None（韜晦 spec §15.4。ほかの kind は今と同じ値）
    with_vloss = {str(d.get("kind")) for d in infos if _num(d.get("vloss"))}
    vloss_by_kind = {
        k: None if k == "opening" and k not in with_vloss else sum(vl(d) for d in deviated if str(d.get("kind")) == k)
        for k in sorted(kinds)
    }
    report_loss_by_kind = {
        k: sum(r["loss"] or 0.0 for r in dev_rows if str(r["decision"].get("kind")) == k) for k in sorted(kinds)
    }
    out = {
        "tiers": dict(Counter(str(d.get("tier")) for d in infos)),
        "kinds": dict(kinds),
        "paid_vloss_sum": sum(vl(d) for d in deviated),
        "vloss_by_kind": vloss_by_kind,
        "report_loss_by_kind": report_loss_by_kind,
        "curse_by_kind": {
            k: None if vloss_by_kind[k] is None else report_loss_by_kind[k] - vloss_by_kind[k] for k in sorted(kinds)
        },
        "nonfree_below_reserve": None,
        "close_free_vloss": None,
        "trap_next_loss_over_E": None,
        "ledger_mismatch": None,
        "opening": _opening_metrics(decs),
    }
    if reserve is not None:
        below = [d for d in deviated if _num(d.get("lead")) and d["lead"] < reserve]
        out["nonfree_below_reserve"] = sum(1 for d in below if not _veil_unpaid(d))
        out["close_free_vloss"] = sum(
            vl(d)
            for d in deviated
            if d.get("kind") == "free" and d.get("close", _num(d.get("lead")) and d["lead"] < reserve)
        )
    by_depth = {r["depth"]: r for r in rows}
    loss_sum = e_sum = 0.0
    for r in decs:
        d = r["decision"]
        nxt = by_depth.get(r["depth"] + 1)
        if d.get("kind") == "trap" and _num(d.get("E")) and d["E"] > 0 and nxt is not None and nxt["loss"] is not None:
            loss_sum += nxt["loss"]
            e_sum += d["E"]
    if e_sum > 0:
        out["trap_next_loss_over_E"] = loss_sum / e_sum
    if ledger is not None:
        ai_by_depth = {r["depth"]: r for r in ai_rows}
        mism = 0
        for entry in ledger:
            depth, best_gtp, played = entry[0], entry[1], entry[2]
            row = ai_by_depth.get(depth + 1)
            if row is not None and played != best_gtp and row["match"]:
                mism += 1
        out["ledger_mismatch"] = mism
    return out


def _shadow_metrics(ai_rows):
    """影判定（spec §6 --shadow）: 同じ局面での B の外し率とコスト（B の手の pointsLost）を、打った A の手と対で出す。"""
    sh = [r for r in ai_rows if isinstance(r.get("shadow"), dict) and r["shadow"].get("move")]
    if not sh:
        return None
    with_best = [r for r in sh if r["best"] is not None]
    return {
        "arm": sh[0]["shadow"].get("arm"),
        "n": len(sh),
        "dev_rate": (
            sum(1 for r in with_best if r["shadow"]["move"] != r["best"]) / len(with_best) if with_best else None
        ),
        "same_as_played": sum(1 for r in sh if r["shadow"]["move"] == r["move"]) / len(sh),
        "vloss_mean": _fmean([r["shadow"].get("vloss") for r in sh]),
        "played_loss_mean": _fmean([r["loss"] for r in sh]),
        "secs_p95": percentile([r["shadow"].get("secs") for r in sh], 0.95),
    }


def selfplay_game_summary(meta, reports, rows, target, reserve=None, ledger=None, wall_s=None):
    """games.jsonl の1行（spec §5）。meta は seed・arm・色・段位・komi・end_reason などの開始条件と終局理由。

    主指標は WATCH（末尾のパスを除いた木）の全体の一致率。own = AI・opp = 相手。
    """
    ai_rows = [r for r in rows if r["is_ai"]]
    opp_rows = [r for r in rows if not r["is_ai"]]
    watch_all = (reports.get("WATCH") or {}).get("all") or {}
    own = watch_all.get("ai") or {}
    opp = watch_all.get("opp") or {}
    own_top1, opp_top1 = own.get("top1"), opp.get("top1")
    leads = [r["lead_after_ai"] for r in rows if r["lead_after_ai"] is not None]
    wrs = [r["wr_after_ai"] for r in rows if r["wr_after_ai"] is not None]
    final_lead = leads[-1] if leads else None
    opp_losses = [r["loss"] for r in opp_rows if r["loss"] is not None]
    dev_hp = [
        r["hp_played"]
        for r in ai_rows
        if r.get("hp_played") is not None and r["best"] is not None and not r["match"] and r["points_lost"] is not None
    ]
    times = [r["strategy_s"] for r in ai_rows if r.get("strategy_s") is not None]
    rec = dict(meta)
    rec.update(
        {
            "result": selfplay_outcome(meta.get("end_reason"), final_lead),
            "n_moves": rows[-1]["depth"] if rows else 0,
            "final_lead": final_lead,
            "lead_min": min(leads) if leads else None,
            "lead_max": max(leads) if leads else None,
            "ai_wr_min": min(wrs) if wrs else None,
            "reports": reports,
            "own_top1": own_top1,
            "opp_top1": opp_top1,
            "own_top5": own.get("top5"),
            "opp_top5": opp.get("top5"),
            "own_n": own.get("n", 0),
            "opp_n": opp.get("n", 0),
            "own_mean_ptloss": own.get("mean_ptloss"),
            "opp_mean_ptloss": opp.get("mean_ptloss"),
            "own_minus_opp": None if own_top1 is None or opp_top1 is None else own_top1 - opp_top1,
            "own_lt_opp": None if own_top1 is None or opp_top1 is None else own_top1 < opp_top1,
            "own_le_target_plus5": None if own_top1 is None else own_top1 <= target + TARGET_SLACK,
            "own_lt_floor": None if own_top1 is None else own_top1 < RATE_FLOOR,
            "ai_tail": {
                f"ge{int(t)}": sum(1 for r in ai_rows if r["loss"] is not None and r["loss"] >= t)
                for t in BLUNDER_TAILS
            },
            "opp_tail": {
                "n": len(opp_losses),
                "ge2": sum(1 for x in opp_losses if x >= 2.0),
                "ge5": sum(1 for x in opp_losses if x >= 5.0),
            },
            "flip_moves": sum(
                1
                for r in ai_rows
                if r["wr_before_ai"] is not None
                and r["wr_after_ai"] is not None
                and r["wr_before_ai"] >= 0.5
                and r["wr_after_ai"] < 0.5
            ),
            "hp_dev_list": [round(x, 4) for x in dev_hp],
            "hp_dev_median": statistics.median(dev_hp) if dev_hp else None,
            "hp_dev_lt5": sum(1 for x in dev_hp if x < HP_AUDIT_LOW) / len(dev_hp) if dev_hp else None,
            "intent_report_mismatch": sum(
                1
                for r in ai_rows
                if r.get("best_at_decision") is not None
                and r.get("played") is not None
                and r["played"] != r["best_at_decision"]
                and r["match"]
            ),
            "veil": _decision_metrics(ai_rows, rows, reserve, ledger),
            "shadow": _shadow_metrics(ai_rows),
            "strategy_times": [round(t, 3) for t in times],
            "strategy_p50": percentile(times, 0.5),
            "strategy_p95": percentile(times, 0.95),
            "strategy_max": max(times) if times else None,
            "wait_s": sum(r.get("wait_s") or 0.0 for r in ai_rows),
            "wall_s": wall_s,
            "visits_low": sum(1 for r in rows if r["visits_low"]),
        }
    )
    return rec


# ---- 統計 ----
def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, center - half), min(1.0, center + half))


def cluster_bootstrap(clusters, stat, n_boot=10000, seed=0, conf=0.95):
    """局（クラスタ）を復元抽出して stat(標本) の percentile 区間。stat が None を返した標本は捨てる。"""
    if not clusters:
        return (None, None)
    rng = random.Random(seed)
    k = len(clusters)
    vals = []
    for _ in range(n_boot):
        v = stat([clusters[rng.randrange(k)] for _ in range(k)])
        if v is not None:
            vals.append(v)
    a = (1 - conf) / 2
    return (percentile(vals, a), percentile(vals, 1 - a))


def _betacf(a, b, x):
    """不完全ベータ関数の連分数（Numerical Recipes 6.4）。"""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-14:
            break
    return h


def _betainc(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    tail = 0.5 * _betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t >= 0 else tail


def t_ppf(p, df):
    lo, hi = -1e4, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def t_interval(values, conf=0.95):
    n = len(values)
    if n < 2:
        return (None, None)
    m = statistics.fmean(values)
    half = t_ppf(0.5 + conf / 2, n - 1) * statistics.stdev(values) / math.sqrt(n)
    return (m - half, m + half)


def wilcoxon_signed_rank(diffs):
    """両側 p 値。0 の差は捨てる（Wilcoxon 法）。同順位が無く n <= 50 なら正確分布、それ以外は正規近似。"""
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n == 0:
        return None
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    tie_sizes = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        if j > i:
            tie_sizes.append(j - i + 1)
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    if not tie_sizes and n <= 50:
        total = n * (n + 1) // 2
        counts = [0] * (total + 1)
        counts[0] = 1
        for k in range(1, n + 1):
            for s in range(total, k - 1, -1):
                counts[s] += counts[s - k]
        w = int(round(w_plus))
        tail = min(sum(counts[: w + 1]), sum(counts[w:]))
        return min(1.0, 2 * tail / 2**n)
    mean = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24 - sum(t**3 - t for t in tie_sizes) / 48
    if var <= 0:
        return None
    z = (w_plus - mean) / math.sqrt(var)
    return min(1.0, 2 * (1 - statistics.NormalDist().cdf(abs(z))))


def selfplay_stop_rule(lo, hi, margin=0.03):
    """停止規則（spec §6）: 差の区間が ±margin の判定線をまたぐなら extend。"""
    if lo is None or hi is None:
        return "insufficient"
    if lo < -margin < hi or lo < margin < hi:
        return "extend"
    if lo >= margin:
        return "higher"
    if hi <= -margin:
        return "lower"
    return "within"


# ---- アームの要約 ----
def metric_value(rec, metric):
    if metric == "win":
        if rec.get("result") in ("aborted", "unknown", None):
            return None
        return 1.0 if rec["result"] == "win" else 0.0
    if metric == "ge6":
        return (rec.get("ai_tail") or {}).get("ge6")
    v = rec.get(metric)
    if isinstance(v, bool):
        return float(v)
    return v


def _mean_rate(pairs):
    return statistics.fmean(v for v, _ in pairs) if pairs else None


def _pooled_rate(pairs):
    total = sum(n for _, n in pairs)
    return sum(v * n for v, n in pairs) / total if total else None


def _frac(recs, key):
    vals = [r.get(key) for r in recs if r.get(key) is not None]
    return sum(1 for v in vals if v) / len(vals) if vals else None


def _fmean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def integrity_totals(records):
    """計測の健全性の4つの合計（fallbacks・humansl_errors・hp_audit_errors・shadow_errors）を records から数える。
    aborted の局も含めて全ての records から数える（列の無い古い games.jsonl の行は 0）。
    `selfplay_arm_summary`（run の要約）と `calibration_result`（calibrate）の両方がこれを使う。"""
    return {
        **{k: sum((r.get("opponent_stats") or {}).get(k) or 0 for r in records) for k in INTEGRITY_OPPONENT_STATS},
        **{k: sum(r.get(k) or 0 for r in records) for k in INTEGRITY_HOOK_ERRORS},
    }


def selfplay_arm_summary(records, n_boot=10000, seed=0):
    """1群（アーム、またはアーム × 段位 × 色）の要約（spec §5 summary）。aborted の局は数えるだけ。"""
    ok = [r for r in records if r.get("result") != "aborted"]
    wins = sum(1 for r in ok if r["result"] == "win")
    out = {
        "games": len(records),
        "aborted": len(records) - len(ok),
        "wins": wins,
        "losses": sum(1 for r in ok if r["result"] == "loss"),
        "jigo": sum(1 for r in ok if r["result"] == "jigo"),
        "win_ci": list(wilson(wins, len(ok))),
    }
    for side in ("own", "opp"):
        pairs = [(r[f"{side}_top1"], r[f"{side}_n"]) for r in ok if r.get(f"{side}_top1") is not None]
        out[f"{side}_top1_mean"] = _mean_rate(pairs)
        out[f"{side}_top1_mean_ci"] = list(cluster_bootstrap(pairs, _mean_rate, n_boot, seed))
        out[f"{side}_top1_pooled"] = _pooled_rate(pairs)
        out[f"{side}_top1_pooled_ci"] = list(cluster_bootstrap(pairs, _pooled_rate, n_boot, seed))
        out[f"{side}_mean_ptloss"] = _fmean([r.get(f"{side}_mean_ptloss") for r in ok])
    diffs = [r["own_minus_opp"] for r in ok if r.get("own_minus_opp") is not None]
    out["own_minus_opp_mean"] = statistics.fmean(diffs) if diffs else None
    out["own_minus_opp_ci"] = list(cluster_bootstrap(diffs, lambda s: statistics.fmean(s), n_boot, seed))
    out["p_own_lt_opp"] = _frac(ok, "own_lt_opp")
    out["p_own_le_target_plus5"] = _frac(ok, "own_le_target_plus5")
    out["p_own_lt_floor"] = _frac(ok, "own_lt_floor")
    out["ge6_per_game"] = _fmean([(r.get("ai_tail") or {}).get("ge6") for r in ok])
    out["flip_per_game"] = _fmean([r.get("flip_moves") for r in ok])
    leads = [r["final_lead"] for r in ok if r.get("final_lead") is not None]
    out["final_lead_median"] = percentile(leads, 0.5)
    out["final_lead_iqr"] = [percentile(leads, 0.25), percentile(leads, 0.75)]
    out["moves_median"] = percentile([r.get("n_moves") for r in ok], 0.5)
    bins = {}
    for name, _ in REPORT_BINS:
        pairs = []
        for r in ok:
            block = (((r.get("reports") or {}).get("WATCH") or {}).get(name) or {}).get("ai") or {}
            if block.get("top1") is not None:
                pairs.append((block["top1"], block["n"]))
        bins[name] = _pooled_rate(pairs)
    out["own_top1_by_bin"] = bins
    hp = [x for r in ok for x in (r.get("hp_dev_list") or [])]
    out["hp_dev_median"] = statistics.median(hp) if hp else None
    out["hp_dev_n"] = len(hp)
    out["strategy_p95"] = percentile([t for r in ok for t in (r.get("strategy_times") or [])], 0.95)
    out["visits_low"] = sum(r.get("visits_low") or 0 for r in ok)
    out["shadow_dev_rate"] = _fmean([(r.get("shadow") or {}).get("dev_rate") for r in ok])
    out["shadow_same_as_played"] = _fmean([(r.get("shadow") or {}).get("same_as_played") for r in ok])
    out["shadow_vloss_mean"] = _fmean([(r.get("shadow") or {}).get("vloss_mean") for r in ok])
    out["shadow_played_loss_mean"] = _fmean([(r.get("shadow") or {}).get("played_loss_mean") for r in ok])
    out["integrity"] = integrity_totals(records)
    return out


def selfplay_summarize(records, n_boot=10000, seed=0):
    """アームごと と アーム × 段位 × 色ごと の要約。"""
    arms, strata = {}, {}
    for r in records:
        arms.setdefault(r["arm"], []).append(r)
        strata.setdefault(f"{r['arm']}|{r['rank']}|{r['ai_color']}", []).append(r)
    return {
        "arms": {k: selfplay_arm_summary(v, n_boot, seed) for k, v in sorted(arms.items())},
        "strata": {k: selfplay_arm_summary(v, n_boot, seed) for k, v in sorted(strata.items())},
    }


RATE_METRICS = ("own_top1", "opp_top1", "own_minus_opp")  # 停止規則の ±3pt が意味を持つ一致率の指標


def selfplay_paired_diff(recs_a, recs_b, metric, n_boot=10000, seed=0, conf=0.975, margin=0.03):
    """同じ seed の対の差 a − b（spec §6）。conf 既定 0.975＝2回見る停止規則の Bonferroni。

    verdict（±margin の停止規則）は一致率の指標（RATE_METRICS）だけ。局あたりの回数・目・勝率には None。
    """
    fa = {r["seed"]: metric_value(r, metric) for r in recs_a if r.get("result") != "aborted"}
    fb = {r["seed"]: metric_value(r, metric) for r in recs_b if r.get("result") != "aborted"}
    seeds = sorted(s for s in fa if s in fb and fa[s] is not None and fb[s] is not None)
    diffs = [fa[s] - fb[s] for s in seeds]
    t_lo, t_hi = t_interval(diffs, conf)
    return {
        "metric": metric,
        "n": len(diffs),
        "mean": statistics.fmean(diffs) if diffs else None,
        "t_ci": [t_lo, t_hi],
        "wilcoxon_p": wilcoxon_signed_rank(diffs),
        "boot_ci": list(cluster_bootstrap(diffs, lambda s: statistics.fmean(s), n_boot, seed, conf)),
        "conf": conf,
        "verdict": selfplay_stop_rule(t_lo, t_hi, margin) if metric in RATE_METRICS else None,
    }


# ---- 設定の突き合わせ ----
def settings_fingerprint(mode, settings):
    blob = json.dumps({"mode": mode, "settings": settings}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def normalize_setting(value):
    """数値の型の違いを消す（6 == 6.0）。bool は数値にしない（True と 1.0 は別の設定として残す）。"""
    if isinstance(value, bool):
        return value
    return float(value) if isinstance(value, int) else value


def effective_settings(settings, key_prefix=None, setting_defaults=None):
    """戦略が実際に使う設定: コードの既定値 {f"{key_prefix}_{k}": v} → settings（ユーザー config + 上書き）の順に重ね、
    数値を正規化する。

    KEY_PREFIX / SETTING_DEFAULTS を持つ戦略は settings.get(f"{KEY_PREFIX}_{k}", SETTING_DEFAULTS[k]) で読む
    （ai.py の _setting）ので、既定値と同じ値の上書きは違いにならない。持たない戦略は settings だけを正規化する。
    """
    base = {f"{key_prefix}_{k}": v for k, v in (setting_defaults or {}).items()} if key_prefix else {}
    return {k: normalize_setting(v) for k, v in {**base, **(settings or {})}.items()}


def arms_null_guard(arms):
    """戦略が実際に使う設定が同一のアームの組 [(name, name)]。空でなければ null 実験＝中止する。

    アームの dict の effective_settings（resolve_arm がコードの既定値から解決したもの。無ければ settings）を
    正規化して比べる＝型だけの違い（6 と 6.0）や既定値と同じ上書きは「同じ設定」。
    """

    def effective_fingerprint(arm):
        eff = arm.get("effective_settings")
        return settings_fingerprint(arm["mode"], effective_settings(arm["settings"] if eff is None else eff))

    pairs = []
    for a, b in itertools.combinations(arms, 2):
        if effective_fingerprint(a) == effective_fingerprint(b):
            pairs.append((a["name"], b["name"]))
    return pairs


def unknown_override_keys(overrides, user_section, known_keys):
    """ユーザー config の節にも戦略の既定値にも無い上書きキー（綴り間違いの検出）。"""
    return sorted(k for k in (overrides or {}) if k not in (user_section or {}) and k not in known_keys)


def parse_arm(text):
    """'A=veil13:veil13_trap_mode=true,veil13_reserve=4.0' -> ('A', 'veil13', ['veil13_trap_mode=true', ...])"""
    if "=" not in text:
        raise ValueError(f"arm must be NAME=STRATEGY[:key=val,...]: {text!r}")
    name, rest = text.split("=", 1)
    strategy, _, tail = rest.partition(":")
    name, strategy = name.strip(), strategy.strip()
    if not name or not strategy:
        raise ValueError(f"arm must be NAME=STRATEGY[:key=val,...]: {text!r}")
    return name, strategy, [s.strip() for s in tail.split(",") if s.strip()]


HUMANSL_PROFILE_RE = re.compile(r"(rank|preaz)_\d{1,2}[kd]|proyear_\d{4}")  # KataGo の humanSLProfile の形


def parse_profiles(text):
    """'rank_3k, rank_1d' -> ['rank_3k', 'rank_1d']（前後の空白と空の要素を落とす）。"""
    return [p.strip() for p in text.split(",") if p.strip()]


def invalid_humansl_profiles(profiles):
    """humanSL の段位の形（rank_<N>k|d・preaz_<N>k|d・proyear_<YYYY>）でないもの。KataGo はエラーを返すだけなので、
    そのまま走らせると相手の全手が最善手へのフォールバックになる＝エンジンを起こす前に止める。"""
    return [p for p in profiles if not HUMANSL_PROFILE_RE.fullmatch(p)]


def parse_range(text):
    """'8:40' -> (8.0, 40.0)"""
    lo, hi = text.split(":", 1)
    lo, hi = float(lo), float(hi)
    if lo > hi:
        raise ValueError(f"range lo > hi: {text!r}")
    return lo, hi


# ---- 校正（spec §3 calibrate）----
def calibration_rank_stats(records):
    """段位ごとの相手の統計（局平均・局間 SD・損失・≥2/≥5 の割合・校正用区間の形）と AI 側の一致率。"""
    by_rank = {}
    for r in records:
        if r.get("result") != "aborted" and r.get("opp_top1") is not None:
            by_rank.setdefault(r["rank"], []).append(r)
    out = {}
    for rank, recs in by_rank.items():
        opp = [r["opp_top1"] for r in recs]
        tails = [r.get("opp_tail") or {} for r in recs]
        n_loss = sum(t.get("n", 0) for t in tails)
        bins = {}
        for name, _ in CALIB_BINS:
            blocks = [(((r["reports"].get("WATCH") or {}).get(name) or {}).get("opp") or {}) for r in recs]
            blocks = [b for b in blocks if b.get("top1") is not None and b.get("n")]
            n_bin = sum(b["n"] for b in blocks)
            bins[name] = {
                "opp_top1": sum(b["top1"] * b["n"] for b in blocks) / n_bin if n_bin else None,
                "opp_loss": sum(b["mean_ptloss"] * b["n"] for b in blocks) / n_bin if n_bin else None,
                "n": n_bin,
            }
        out[rank] = {
            "games": len(recs),
            "opp_mean": statistics.fmean(opp),
            "opp_sd": statistics.pstdev(opp),
            "opp_pooled": _pooled_rate([(r["opp_top1"], r["opp_n"]) for r in recs]),
            "opp_loss": _fmean([r.get("opp_mean_ptloss") for r in recs]),
            "opp_ge2": sum(t.get("ge2", 0) for t in tails) / n_loss if n_loss else None,
            "opp_ge5": sum(t.get("ge5", 0) for t in tails) / n_loss if n_loss else None,
            "own_mean": _fmean([r.get("own_top1") for r in recs]),
            "moves_median": percentile([r.get("n_moves") for r in recs], 0.5),
            "bins": bins,
        }
    return out


def selfplay_pool_choice(rank_stats, targets=CALIB_TARGETS_13, k=3, tolerance=POOL_TOLERANCE):
    """k 段位の組（層は同数）の局平均・局間 SD・損失を目標と比べ、スコアの小さい順に返す。

    局間 SD は全分散の公式（層内分散の平均 + 層平均の分散。どちらも母分散）。
    """
    choices = []
    for combo in itertools.combinations(list(rank_stats), k):
        st = [rank_stats[r] for r in combo]
        means = [s["opp_mean"] for s in st]
        mean = statistics.fmean(means)
        sd = math.sqrt(statistics.fmean([s["opp_sd"] ** 2 for s in st]) + statistics.pvariance(means))
        loss = _fmean([s["opp_loss"] for s in st])
        score = ((mean - targets["opp_mean"]) / tolerance["opp_mean"]) ** 2 + (
            (sd - targets["opp_sd"]) / tolerance["opp_sd"]
        ) ** 2
        if loss is not None:
            score += ((loss - targets["opp_loss"]) / tolerance["opp_loss"]) ** 2
        choices.append(
            {
                "ranks": list(combo),
                "opp_mean": mean,
                "opp_sd": sd,
                "opp_loss": loss,
                "own_mean": _fmean([s["own_mean"] for s in st]),
                "bins": {
                    name: {
                        "opp_top1": _fmean([s["bins"][name]["opp_top1"] for s in st]),
                        "opp_loss": _fmean([s["bins"][name]["opp_loss"] for s in st]),
                    }
                    for name, _ in CALIB_BINS
                },
                "score": score,
            }
        )
    return sorted(choices, key=lambda c: c["score"])
