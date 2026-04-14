# katrain_debug/cli.py
import os
os.environ.setdefault("KIVY_NO_ARGS", "1")

import argparse
import json
import sys

from katrain_debug.runner import run_strategy, STRATEGY_NAME_MAP
from katrain_debug.batch_eval import batch_evaluate


def parse_settings(settings_list):
    """['key1=val1', 'key2=val2'] -> {key1: val1, key2: val2} に変換。
    value部分を数値（float/int）に変換可能な場合は変換する。
    """
    if not settings_list:
        return None
    result = {}
    for item in settings_list:
        if "=" not in item:
            print(f"Warning: ignoring invalid setting '{item}' (expected key=value)", file=sys.stderr)
            continue
        key, value = item.split("=", 1)
        try:
            if "." in value:
                value = float(value)
            else:
                value = int(value)
        except ValueError:
            if value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False
        result[key] = value
    return result if result else None


def format_text_output(result, sgf_path, move_number):
    """text形式の出力を生成"""
    lines = []
    lines.append(f"=== Strategy Debug: {result['strategy_class']} ===")
    lines.append(f"SGF: {sgf_path} | Move: {move_number} | Player: {result['player']}")
    lines.append("")

    lines.append("--- Settings ---")
    for key, value in sorted(result["settings"].items()):
        lines.append(f"  {key}: {value}")
    lines.append("")

    lines.append("--- Decision Log ---")
    for message, level in result["logs"]:
        if level <= 1:  # OUTPUT_DEBUG and above
            lines.append(message)
    lines.append("")

    lines.append("--- Result ---")
    lines.append(f"Move: {result['move']}")
    lines.append(f"Explanation: {result['explanation']}")

    return "\n".join(lines)


def format_json_output(result, sgf_path, move_number):
    """json形式の出力を生成"""
    output = {
        "sgf": sgf_path,
        "move_number": move_number,
        "player": result["player"],
        "strategy": result["strategy"],
        "strategy_class": result["strategy_class"],
        "settings": result["settings"],
        "result": {
            "move": result["move"],
            "explanation": result["explanation"],
        },
        "logs": [
            {"message": msg, "level": level}
            for msg, level in result["logs"]
        ],
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


def format_batch_text(result):
    """バッチ評価結果のテキスト出力を生成"""
    lines = []
    s_range = result["evaluated_range"]
    pf = result.get("player_filter")
    player_label = {"B": "Black", "W": "White"}.get(pf, "Both (B/W)")

    lines.append(f"=== Batch Evaluation: {result['strategy_class']} ===")
    lines.append(f"SGF: {result['sgf']} ({result['total_moves']} moves)")
    lines.append(f"Evaluated: move {s_range[0]}-{s_range[1]} | Strategy: {result['strategy']} | Player: {player_label}")
    lines.append("")

    # 設定（パラメータ名と数値を明示）
    lines.append("--- Settings ---")
    for key, value in sorted(result["settings"].items()):
        lines.append(f"  {key} = {value}")
    lines.append("")

    # 集計テーブル
    stats = result["stats"]
    lines.append("--- Aggregate Stats ---")
    header = f"  {'':16s} {'Count':>6s} {'Top1':>8s} {'Top5':>8s} {'MeanLoss':>9s} {'Accuracy':>9s}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    row_order = ["overall", "B", "W", "opening", "middle", "endgame"]
    row_labels = {
        "overall": "Overall",
        "B": "Black",
        "W": "White",
        "opening": "Opening",
        "middle": "Middle",
        "endgame": "Endgame",
    }
    for key in row_order:
        if key not in stats:
            continue
        s = stats[key]
        label = row_labels.get(key, key)
        lines.append(
            f"  {label:16s} {s['count']:6d} {s['ai_top_move']:7.1%} {s['ai_top5_move']:7.1%}"
            f" {s['mean_ptloss']:9.2f} {s['accuracy']:8.1f}"
        )
    lines.append("")

    # 不一致手のハイライト（損失 >= 2.0 のみ表示）
    bad_moves = [m for m in result["moves"] if m["point_loss"] is not None and m["point_loss"] >= 2.0]
    if bad_moves:
        lines.append(f"--- Notable Divergences (loss >= 2.0, {len(bad_moves)} moves) ---")
        for m in bad_moves[:20]:  # 上位20件
            mark = "OK" if m["match_top"] else "**"
            lines.append(
                f"  Move {m['move_num']:3d} ({m['player']}): "
                f"AI={m['ai_top']:4s} Strategy={m['selected']:4s} "
                f"loss={m['point_loss']:.1f} {mark}"
            )
        if len(bad_moves) > 20:
            lines.append(f"  ... and {len(bad_moves) - 20} more")
        lines.append("")

    # Jigo Metrics ブロック（strategy == "jigo" 時のみ）
    jigo_metrics = stats.get("jigo_metrics")
    if jigo_metrics:
        lines.append("--- Jigo Metrics ---")
        lines.append(f"  Count:              {jigo_metrics['count']}")
        lines.append(f"  Mean Lead:          {jigo_metrics['mean_lead']:.2f}")
        lines.append(f"  Max Lead:           {jigo_metrics['max_lead']:.2f}")
        lines.append(f"  In-Target Ratio:    {jigo_metrics['in_target_ratio']:.1%}")
        lines.append(f"  Over-Target Ratio:  {jigo_metrics['over_target_ratio']:.1%}")
        if jigo_metrics['mean_selected_hp'] is not None:
            lines.append(f"  Mean Selected HP:   {jigo_metrics['mean_selected_hp']:.4f}")
            lines.append(f"  P10 Selected HP:    {jigo_metrics['p10_selected_hp']:.4f}")
        lines.append(f"  Filter Relax Rate:  {jigo_metrics['filter_relax_rate']:.1%}")
        lines.append(f"  Biased Lead Rate:   {jigo_metrics['biased_lead_rate']:.1%}")
        lines.append(f"  Rank Downgrades:    {jigo_metrics['rank_downgrade_counts']}")
        lines.append("")

    # Lambdago Metrics ブロック（全戦略で常に表示）
    lambdago_metrics = stats.get("lambdago_metrics")
    if lambdago_metrics:
        lines.append("--- Lambdago Metrics (paper-derived) ---")
        ref = lambdago_metrics["reference"]
        lines.append(
            f"  Reference: human amateur ~ -{ref['human_amateur_loss']} mean loss; "
            f"AI suspect ~ -{ref['ai_suspect_loss']}"
        )
        lines.append("")

        lines.append("  Choice-vs-Median Gap (lower = more AI-like; excludes moves with winrate>95%):")
        cvm = lambdago_metrics["choice_vs_median"]
        for key in ("overall", "B", "W"):
            if key not in cvm:
                continue
            block = cvm[key]
            label = {"overall": "Overall", "B": "Black  ", "W": "White  "}[key]
            lines.append(
                f"    {label}: {block['mean']:+.2f}  "
                f"(n={block['count']}, neg_ratio={block['negative_ratio']:.0%})"
            )
        lines.append("")

        lines.append("  Post-98% Slack (positive delta = sloppy after winning):")
        slack = lambdago_metrics["post_98_slack"]
        for player in ("B", "W"):
            label = {"B": "Black", "W": "White"}[player]
            block = slack.get(player)
            if block is None:
                lines.append(f"    {label}: not reached")
                continue
            sample_marker = " (low N)" if block["low_sample"] else ""
            lines.append(
                f"    {label}: pre={block['pre_98_avg_loss']:.2f}  "
                f"post={block['post_98_avg_loss']:.2f}  "
                f"delta={block['slack_delta']:+.2f}"
            )
            lines.append(
                f"           reached at move {block['first_98_move']} "
                f"(n_pre={block['n_pre']}, n_post={block['n_post']}{sample_marker})"
            )
        lines.append("")

    return "\n".join(lines)


def format_batch_json(result):
    """バッチ評価結果のJSON出力を生成"""
    return json.dumps(result, indent=2, ensure_ascii=False)


def parse_move_range(value):
    """'10-50' -> (10, 50), '30' -> (30, 30)"""
    if "-" in value:
        parts = value.split("-", 1)
        return int(parts[0]), int(parts[1])
    n = int(value)
    return n, n


def main():
    parser = argparse.ArgumentParser(
        prog="katrain_debug",
        description="KaTrain AI戦略デバッグツール - SGFの指定局面で戦略の意思決定過程を再現・可視化",
    )
    parser.add_argument("--sgf", required=True, help="SGFファイルパス")
    parser.add_argument("--move", type=int, default=None, help="解析する手番（1-indexed、--batch時は不要）")
    parser.add_argument(
        "--strategy", required=True,
        choices=sorted(STRATEGY_NAME_MAP.keys()),
        help="戦略名",
    )
    parser.add_argument(
        "--settings", nargs="*", metavar="KEY=VALUE",
        help="戦略パラメータの上書き（例: hunt_max_loss=8.0）",
    )
    parser.add_argument("--config", default=None, help="config.jsonのパス（デフォルト: ~/.katrain/config.json）")
    parser.add_argument("--output", choices=["text", "json"], default="text", help="出力形式")
    parser.add_argument("--log-level", type=int, default=1, choices=[1, 2], help="ログ詳細度（1=通常, 2=全ログ）")
    parser.add_argument("--batch", action="store_true", help="1局通しのバッチ評価モード")
    parser.add_argument("--move-range", type=str, default=None, help="バッチ評価の手数範囲（例: 1-100, 50-200）")
    parser.add_argument("--player", choices=["B", "W"], default=None, help="バッチ評価で戦略AIの手番を指定（B=黒, W=白）")

    args = parser.parse_args()

    if args.batch:
        _run_batch(args)
    else:
        if args.move is None:
            parser.error("--move is required (or use --batch for full-game evaluation)")
        _run_single(args)


def _run_single(args):
    """単一局面のデバッグ実行"""
    settings_overrides = parse_settings(args.settings)

    try:
        result = run_strategy(
            sgf_path=args.sgf,
            move_number=args.move,
            strategy_name=args.strategy,
            config_path=args.config,
            settings_overrides=settings_overrides,
            debug_level=args.log_level,
            quiet=(args.output == "json"),
        )
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output == "json":
        print(format_json_output(result, args.sgf, args.move))
    else:
        print(format_text_output(result, args.sgf, args.move))


def _run_batch(args):
    """1局通しのバッチ評価実行"""
    settings_overrides = parse_settings(args.settings)
    move_range = parse_move_range(args.move_range) if args.move_range else None

    try:
        result = batch_evaluate(
            sgf_path=args.sgf,
            strategy_name=args.strategy,
            config_path=args.config,
            settings_overrides=settings_overrides,
            move_range=move_range,
            player_filter=args.player,
        )
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    if args.output == "json":
        print(format_batch_json(result))
    else:
        print(format_batch_text(result))
