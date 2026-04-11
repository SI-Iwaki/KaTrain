# katrain_debug/cli.py
import os
os.environ.setdefault("KIVY_NO_ARGS", "1")

import argparse
import json
import sys

from katrain_debug.runner import run_strategy, STRATEGY_NAME_MAP


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


def main():
    parser = argparse.ArgumentParser(
        prog="katrain_debug",
        description="KaTrain AI戦略デバッグツール - SGFの指定局面で戦略の意思決定過程を再現・可視化",
    )
    parser.add_argument("--sgf", required=True, help="SGFファイルパス")
    parser.add_argument("--move", type=int, required=True, help="解析する手番（1-indexed）")
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

    args = parser.parse_args()

    settings_overrides = parse_settings(args.settings)

    try:
        result = run_strategy(
            sgf_path=args.sgf,
            move_number=args.move,
            strategy_name=args.strategy,
            config_path=args.config,
            settings_overrides=settings_overrides,
            debug_level=args.log_level,
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
