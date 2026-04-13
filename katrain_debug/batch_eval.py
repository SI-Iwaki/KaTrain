"""1局通しのバッチ戦略評価モジュール。

KataGoを1回だけ起動し、SGF全手を走査して戦略の選択手とAI最善手を比較する。
game_report() と同じ指標（ai_top_move, ai_top5_move, mean_ptloss, accuracy）を算出。
"""

import math
import os
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

            # 選択手の損失を計算
            selected_info = next((d for d in cands if d["move"] == selected_gtp), None)
            point_loss = max(0.0, selected_info["pointsLost"]) if selected_info else None

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
