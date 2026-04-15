"""1局通しのバッチ戦略評価モジュール。

KataGoを1回だけ起動し、SGF全手を走査して戦略の選択手とAI最善手を比較する。
game_report() と同じ指標（ai_top_move, ai_top5_move, mean_ptloss, accuracy）を算出。
"""

import math
import os
import statistics
import sys
import time

from katrain.core.game import BaseGame, KaTrainSGF
from katrain.core.constants import (
    DATA_FOLDER,
    ADDITIONAL_MOVE_ORDER,
)
from katrain.core.ai import STRATEGY_REGISTRY
from katrain.core.engine import KataGoEngine
from katrain_debug.runner import STRATEGY_NAME_MAP, DebugGame
from katrain_debug.katrain_stub import KaTrainStub


def batch_evaluate(sgf_path, strategy_name, config_path=None,
                   settings_overrides=None, move_range=None, player_filter=None):
    """SGFの全局面で戦略を実行し、AI最善手との一致率を算出する。

    Args:
        sgf_path: SGFファイルパス
        strategy_name: CLIフレンドリー名（"hunt", "siege"等）
        config_path: config.jsonのパス（Noneで~/.katrain/config.json）
        settings_overrides: 戦略パラメータの上書きdict
        move_range: (start, end) タプル。Noneで全手。1-indexed。
        player_filter: "B" or "W" で片方の色のみ評価。Noneで両方。
    Returns:
        dict with keys: moves (per-move results), stats (aggregate stats), settings, player_filter
    """
    if config_path is None:
        config_path = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))

    if strategy_name not in STRATEGY_NAME_MAP:
        available = ", ".join(sorted(STRATEGY_NAME_MAP.keys()))
        raise KeyError(f"Unknown strategy '{strategy_name}'. Available: {available}")
    ai_mode = STRATEGY_NAME_MAP[strategy_name]

    # スタブ初期化（quiet=Trueでstderr出力を抑制）
    stub = KaTrainStub(config_path, debug_level=0, quiet=True)

    # SGF読み込み — 全ノードを収集
    root = KaTrainSGF.parse_file(sgf_path)
    all_nodes = []
    node = root
    while node.children:
        node = node.children[0]
        all_nodes.append(node)

    total_moves = len(all_nodes)
    if move_range:
        start, end = move_range
    else:
        start, end = 1, total_moves

    # 盤面サイズ取得
    bx, by = root.board_size
    board_area = bx * by
    opening_boundary = math.ceil(0.14 * board_area)
    endgame_boundary = math.ceil(0.5 * board_area)

    # エンジン起動（1回だけ）
    engine_config = stub.config("engine")
    engine = KataGoEngine(stub, engine_config)

    # AI設定を取得
    ai_settings = stub.config(f"ai/{ai_mode}") or {}
    if settings_overrides:
        ai_settings = {**ai_settings, **settings_overrides}

    try:
        # DebugGameを構築
        game = DebugGame(katrain=stub, engine=engine, move_tree=root)
        stub.game = game

        move_results = []
        progress_interval = max(1, (end - start + 1) // 20)  # 5%刻みで進捗表示

        for move_num in range(start, end + 1):
            if move_num > total_moves:
                break

            # 進捗表示
            idx = move_num - start
            if idx % progress_interval == 0 or move_num == end:
                pct = (idx + 1) / (end - start + 1) * 100
                print(f"\r  [{move_num}/{end}] {pct:.0f}%", end="", file=sys.stderr)

            # 対象ノード: move_num番目のノード（1-indexed → 0-indexed）
            target_node = all_nodes[move_num - 1]
            parent_node = target_node.parent
            if parent_node is None:
                continue

            player = parent_node.next_player  # この局面で打つプレイヤー
            actual_move = target_node.move  # 実際に打たれた手

            # プレイヤーフィルタ
            if player_filter and player != player_filter:
                continue

            # 親ノード（打つ前の局面）を解析
            game.set_current_node(parent_node)
            if not parent_node.analysis_complete:
                parent_node.analyze(engine)
                while not parent_node.analysis_complete:
                    time.sleep(0.02)
                    engine.check_alive(exception_if_dead=True)

            # AI候補手を取得
            cands = parent_node.candidate_moves
            if not cands:
                continue
            ai_top_move = cands[0]["move"]
            filtered_cands = [d for d in cands if d["order"] < ADDITIONAL_MOVE_ORDER and "prior" in d]
            ai_approved = [
                d["move"] for d in filtered_cands
                if d["order"] == 0 or (d["pointsLost"] < 0.5 and d["order"] < 5)
            ]

            # 戦略を実行
            strategy = STRATEGY_REGISTRY[ai_mode](game, ai_settings)
            selected_move, explanation = strategy.generate_move()
            selected_gtp = selected_move.gtp()

            # 選択手の損失を計算（クランプ済み: 既存ユーザー向け / 生: lambdago 用）
            selected_info = next((d for d in cands if d["move"] == selected_gtp), None)
            if selected_info is not None:
                point_loss_raw = selected_info["pointsLost"]
                point_loss = max(0.0, point_loss_raw)
            else:
                point_loss_raw = None
                point_loss = None

            # lambdago 用: 候補手の median 損失と 打つ側視点 winrate
            # parent_node.winrate は手を打つ前の root winrate（黒視点固定）
            cand_median_loss = _candidate_median_loss(cands)
            wr_black_root = parent_node.winrate
            winrate_player = (
                _winrate_for_player(wr_black_root, player)
                if wr_black_root is not None else None
            )

            # フェーズ判定
            if move_num <= opening_boundary:
                phase = "opening"
            elif move_num > endgame_boundary:
                phase = "endgame"
            else:
                phase = "middle"

            # Jigo 固有情報（他戦略では None）
            jigo_info = getattr(strategy, "last_decision_info", None)

            move_results.append({
                "move_num": move_num,
                "player": player,
                "phase": phase,
                "ai_top": ai_top_move,
                "selected": selected_gtp,
                "actual": actual_move.gtp() if actual_move else None,
                "match_top": selected_gtp == ai_top_move,
                "match_approved": selected_gtp in ai_approved,
                "point_loss": point_loss,
                "point_loss_raw": point_loss_raw,
                "cand_median_loss": cand_median_loss,
                "winrate_player": winrate_player,
                "choice_vs_median": (
                    point_loss_raw - cand_median_loss
                    if point_loss_raw is not None and cand_median_loss is not None
                    else None
                ),
                "explanation": explanation.split("\n")[0] if explanation else "",
                "rank_used": jigo_info.get("rank_used") if jigo_info else None,
                "selected_hp": jigo_info.get("selected_hp") if jigo_info else None,
                "selected_score": jigo_info.get("selected_score") if jigo_info else None,
                "filter_relaxed": jigo_info.get("filter_relaxed") if jigo_info else None,
                "score_lead": jigo_info.get("score_lead") if jigo_info else None,
                "score_lead_biased": jigo_info.get("score_lead_biased") if jigo_info else None,
            })

        print("", file=sys.stderr)  # 進捗表示の改行

        # 集計
        stats = _aggregate_stats(move_results)
        if strategy_name == "jigo":
            stats["jigo_metrics"] = _aggregate_jigo_metrics(
                move_results,
                target_score=ai_settings.get("target_score", 0.5),
                target_score_max=ai_settings.get("target_score_max", 10.0),
            )
        stats["lambdago_metrics"] = _aggregate_lambdago_metrics(move_results)
        return {
            "sgf": sgf_path,
            "total_moves": total_moves,
            "evaluated_range": (start, min(end, total_moves)),
            "strategy": strategy_name,
            "strategy_class": STRATEGY_REGISTRY[ai_mode].__name__,
            "player_filter": player_filter,
            "settings": ai_settings,
            "moves": move_results,
            "stats": stats,
        }
    finally:
        engine.shutdown(finish=False)


def _winrate_for_player(wr_black, player):
    """Convert KataGo's BLACK-perspective winrate to the given player's perspective.

    KataGo is configured with reportAnalysisWinratesAs=BLACK (engine.py:108),
    so all candidate winrates are from Black's viewpoint regardless of the player to move.
    """
    return wr_black if player == "B" else (1.0 - wr_black)


def _candidate_median_loss(cands):
    """Median pointsLost across visited candidates that have a policy prior assigned.

    Returns None if no eligible candidates. Does NOT clamp negative pointsLost
    (preserving the paper's signed effect ε(a) for Choice-vs-Median).
    """
    losses = [
        c["pointsLost"]
        for c in cands
        if c["order"] < ADDITIONAL_MOVE_ORDER and "prior" in c
    ]
    if not losses:
        return None
    return statistics.median(losses)


def _aggregate_jigo_metrics(move_results, target_score, target_score_max):
    """Jigo 戦略専用の集計指標を計算する。

    Args:
        move_results: batch_evaluate の move_results（Jigo 固有フィールド含む）
        target_score: Jigo の目標目差下限
        target_score_max: Jigo の目標目差上限

    Returns:
        Jigo 固有指標 dict、もしくは空 dict（有効行ゼロの場合）
    """
    # score_lead が None でない行のみ集計対象
    valid = [m for m in move_results if m.get("score_lead") is not None]
    if not valid:
        return {}

    n = len(valid)
    leads = [m["score_lead"] for m in valid]
    hps = [m["selected_hp"] for m in valid if m.get("selected_hp") is not None]

    mean_lead = sum(leads) / n
    max_lead = max(leads)
    in_target = sum(1 for l in leads if target_score <= l <= target_score_max)
    over_target = sum(1 for l in leads if l > target_score_max)

    # p10: 下位10%値（nearest-rank 方式: ceil(0.1 * n) 番目の値）
    sorted_hps = sorted(hps) if hps else []
    if sorted_hps:
        mean_hp = sum(sorted_hps) / len(sorted_hps)
        rank = max(1, math.ceil(0.1 * len(sorted_hps)))
        p10_hp = sorted_hps[rank - 1]
    else:
        mean_hp = None
        p10_hp = None

    relax_count = sum(1 for m in valid if m.get("filter_relaxed"))
    filter_relax_rate = relax_count / n

    biased_count = sum(1 for m in valid if m.get("score_lead_biased"))
    biased_lead_rate = biased_count / n

    rank_counts = {"rank_9d": 0, "rank_7d": 0, "rank_5d": 0}
    for m in valid:
        r = m.get("rank_used")
        if r in rank_counts:
            rank_counts[r] += 1

    return {
        "count": n,
        "mean_lead": mean_lead,
        "max_lead": max_lead,
        "in_target_ratio": in_target / n,
        "over_target_ratio": over_target / n,
        "mean_selected_hp": mean_hp,
        "p10_selected_hp": p10_hp,
        "filter_relax_rate": filter_relax_rate,
        "biased_lead_rate": biased_lead_rate,
        "rank_downgrade_counts": rank_counts,
    }


# Choice-vs-Median is unreliable in dominant positions: when the player already
# wins, KataGo's candidate median loss balloons (many "still wins but sloppier"
# alternatives exist), creating a structurally negative gap that is not an
# AI-like signal. Filter these out. Slack detection (98% threshold) is separate
# and not affected.
CVM_DOMINANT_WINRATE_THRESHOLD = 0.95

# Gap below this threshold counts toward negative_ratio (spec: "clearly AI-like" selections).
CVM_NEGATIVE_GAP_THRESHOLD = -0.5

# Winrate at or above which Post-98% Slack tracking begins.
SLACK_WINRATE_TRIGGER = 0.98

# Below this post-count, slack_delta is flagged low_sample=True.
SLACK_LOW_SAMPLE_THRESHOLD = 30


def _aggregate_lambdago_metrics(move_results):
    """Aggregate lambdago paper-derived metrics across move_results.

    Choice-vs-Median Gap (per overall/B/W):
        gap = point_loss_raw - cand_median_loss  (unclamped, stored as per-move
        "choice_vs_median" field in batch_evaluate output).
        Negative gap = AI-like (better than candidate median).
        Excludes moves where winrate_player > CVM_DOMINANT_WINRATE_THRESHOLD (0.95)
        to avoid the candidate-median inflation artifact in dominant positions.

    Post-98% Slack (per B/W):
        Detects if point_loss increases after the player's winrate first reaches 98%.
        pre_98_avg_loss: mean clamped point_loss before first_98_move
        post_98_avg_loss: mean clamped point_loss from first_98_move onward
        slack_delta: post - pre (positive = more mistakes after winning)
        low_sample: True if n_post < 30 (interpret with caution)

    Returns {} when no eligible rows are present.
    """
    if not move_results:
        return {}

    eligible = [
        m for m in move_results
        if m.get("choice_vs_median") is not None
        # winrate_player=None: included (no evidence of dominance; see M-3 comment below)
        and (m.get("winrate_player") is None
             or m["winrate_player"] <= CVM_DOMINANT_WINRATE_THRESHOLD)
    ]
    if not eligible:
        return {}

    def _summarize(rows):
        gaps = [m["choice_vs_median"] for m in rows]
        n = len(gaps)
        return {
            "count": n,
            "mean": sum(gaps) / n,
            "negative_ratio": sum(1 for g in gaps if g < CVM_NEGATIVE_GAP_THRESHOLD) / n,
        }

    cvm = {"overall": _summarize(eligible)}
    for bw in ("B", "W"):
        group = [m for m in eligible if m["player"] == bw]
        if group:
            cvm[bw] = _summarize(group)

    def _slack_for_player(player):
        rows = [m for m in move_results
                if m.get("player") == player
                # winrate_player=None: excluded here (can't determine 98% crossing; see
                # M-3: CVM is more lenient because None rows can still contribute to the
                # gap signal, whereas Slack specifically needs the winrate axis)
                and m.get("winrate_player") is not None
                and m.get("point_loss") is not None]
        if not rows:
            return None

        first_98 = None
        for m in rows:
            if m["winrate_player"] >= SLACK_WINRATE_TRIGGER:
                first_98 = m["move_num"]
                break
        if first_98 is None:
            return None

        pre = [m["point_loss"] for m in rows if m["move_num"] < first_98]
        post = [m["point_loss"] for m in rows if m["move_num"] >= first_98]
        if not pre or not post:
            return None

        pre_avg = sum(pre) / len(pre)
        post_avg = sum(post) / len(post)
        return {
            "first_98_move": first_98,
            "n_pre": len(pre),
            "n_post": len(post),
            "low_sample": len(post) < SLACK_LOW_SAMPLE_THRESHOLD,
            "pre_98_avg_loss": pre_avg,
            "post_98_avg_loss": post_avg,
            "slack_delta": post_avg - pre_avg,
        }

    return {
        "reference": {"human_amateur_loss": 0.65, "ai_suspect_loss": 0.25},
        "choice_vs_median": cvm,
        "post_98_slack": {
            "B": _slack_for_player("B"),
            "W": _slack_for_player("W"),
        },
    }


def _aggregate_stats(move_results):
    """手ごとの結果を集計してgame_report互換の統計を算出する。"""
    if not move_results:
        return {}

    stats = {}

    # 全体 + プレイヤー別 + フェーズ別
    groups = {"overall": move_results}
    for bw in ("B", "W"):
        group = [m for m in move_results if m["player"] == bw]
        if group:
            groups[bw] = group
    for phase in ("opening", "middle", "endgame"):
        group = [m for m in move_results if m["phase"] == phase]
        if group:
            groups[phase] = group

    for key, moves in groups.items():
        moves_with_loss = [m for m in moves if m["point_loss"] is not None]
        if not moves_with_loss:
            continue

        n = len(moves_with_loss)
        losses = [m["point_loss"] for m in moves_with_loss]
        top_matches = sum(1 for m in moves_with_loss if m["match_top"])
        approved_matches = sum(1 for m in moves_with_loss if m["match_approved"])

        mean_loss = sum(losses) / n
        # game_report互換のaccuracy: 100 * 0.75^weighted_loss
        # 簡易版: weighted_lossの代わりにmean_lossを使用
        accuracy = 100 * 0.75 ** mean_loss

        stats[key] = {
            "count": n,
            "ai_top_move": top_matches / n,
            "ai_top5_move": approved_matches / n,
            "mean_ptloss": mean_loss,
            "accuracy": accuracy,
        }

    return stats
