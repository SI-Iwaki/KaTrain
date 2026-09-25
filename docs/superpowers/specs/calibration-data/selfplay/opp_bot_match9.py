"""9路の相手 BOT の一致（spec 2026-09-23-veil-strategy-design.md §16.1。JSON を読むだけ・KataGo 不要）。

    python opp_bot_match9.py [JSON]   # 既定: calibration-data/enigma9/ponder_pick_probe.json（8月の監視対局の 130 局面）

各行はこちらの手の直後（相手の手番）の局面。実際の相手の手（reply）が clean 約 520 visits の最善手（k[0]）と、humanSL 9段の
1位（h_all[0]）と同じだった割合。idx はこちらの手の手数 − 1（idx <= 10 ＝ こちらの手が 11 手目まで）。
2026-09-26 の値: 最善手 23.8%（31/130。11 手目まで 6/25）・humanSL 9段の1位 35.4%（46/130）。段位は不明・こちらが外した後の局面。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "..", "enigma9", "ponder_pick_probe.json")


def share(rows, key):
    hits = sum(1 for r in rows if r[key] and r[key][0] == r["reply"])
    return hits, len(rows)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    with open(argv[0] if argv else PROBE, encoding="utf-8") as f:
        rows = json.load(f)
    early = [r for r in rows if r["idx"] <= 10]
    for label, key in (("clean best (k[0])", "k"), ("humanSL 9d top (h_all[0])", "h_all")):
        hits, n = share(rows, key)
        e_hits, e_n = share(early, key)
        print(f"{label}: {hits}/{n} {100 * hits / n:.1f}%  (our move <= 11: {e_hits}/{e_n})")


if __name__ == "__main__":
    main()
