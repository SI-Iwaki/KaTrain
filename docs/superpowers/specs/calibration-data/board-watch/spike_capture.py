"""対局アプリの盤面が既存の認識器で読めるかを確かめるスパイク。

使い方（BlueStacks で対局アプリを開き、盤面が画面に見えている状態で）:
    python docs/superpowers/specs/calibration-data/board-watch/spike_capture.py --save tests/data/board_watch_before.png

出力は ASCII のみ（cp932 端末対策）。
"""
import argparse
import os
import sys

os.environ["KIVY_NO_ARGS"] = "1"  # 慣例（本スクリプトは Kivy 非 import）

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from katrain.core.tsumego_capture import (  # noqa: E402
    CaptureError,
    capture_screen_rect,
    detect_board,
    detect_size_and_classify,
    find_window_rect,
)


def main():
    parser = argparse.ArgumentParser(description="board_watch spike: recognize the game app board")
    parser.add_argument("--title", default="BlueStacks", help="window title substring")
    parser.add_argument("--save", help="save the captured screenshot to this path")
    parser.add_argument("--sizes", default="9,13,19", help="candidate board sizes")
    args = parser.parse_args()

    rect = find_window_rect(args.title)
    print(f"window rect: {rect}")
    img = capture_screen_rect(rect)
    if args.save:
        img.save(args.save)
        print(f"saved: {args.save}")
    try:
        board_rect = detect_board(img)
    except CaptureError as e:
        print(f"ERROR detect_board: {e}")
        raise SystemExit(1)
    print(f"board rect: {board_rect}")
    sizes = [int(s) for s in args.sizes.split(",")]
    try:
        size, grid = detect_size_and_classify(img, board_rect, sizes)
    except CaptureError as e:
        print(f"ERROR detect_size_and_classify: {e}")
        raise SystemExit(1)
    print(f"board size: {size}")
    for row in grid:
        print(" ".join(row))
    counts = {"B": 0, "W": 0, ".": 0}
    for row in grid:
        for v in row:
            counts[v] += 1
    print(f"counts: B={counts['B']} W={counts['W']} empty={counts['.']}")


if __name__ == "__main__":
    main()
