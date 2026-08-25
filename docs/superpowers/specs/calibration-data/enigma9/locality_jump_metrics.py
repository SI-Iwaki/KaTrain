"""katrain_debug --batch --output json の出力から「飛び飛び」指標を出す。

外した手（selected != ai_top）ごとに、相手の直前手（SGF の move_num-1）と KataGo 最善手
（ai_top）からのチェビシェフ距離を取り、分布・外し率・point_loss 合計を ASCII で出す。
用法: python locality_jump_metrics.py <batch.json> <sgf> [--player W]
"""

import json
import re
import sys
from collections import Counter

COLS = "ABCDEFGHJKLMNOPQRST"
SGF = "abcdefghijklmnopqrs"


def gtp_xy(g):
    return COLS.index(g[0]), int(g[1:])


def sgf_moves(path):
    txt = open(path, encoding="utf-8").read()
    size = int(re.search(r"SZ\[(\d+)\]", txt).group(1))
    out = []
    for c, v in re.findall(r";([BW])\[([a-s]{0,2})\]", txt):
        out.append(None if not v else (COLS[SGF.index(v[0])] + str(size - SGF.index(v[1]))))
    return out


def cheb(a, b):
    (x1, y1), (x2, y2) = gtp_xy(a), gtp_xy(b)
    return max(abs(x1 - x2), abs(y1 - y2))


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    moves = sgf_moves(sys.argv[2])
    player = sys.argv[sys.argv.index("--player") + 1] if "--player" in sys.argv else None
    rows = [m for m in data["moves"] if (player is None or m["player"] == player)]
    dev = [m for m in rows if not m["match_top"] and m["selected"] != "pass" and m["ai_top"] != "pass"]
    d_last, d_best = Counter(), Counter()
    for m in dev:
        prev = moves[m["move_num"] - 2] if m["move_num"] >= 2 else None  # move_num は1始まり
        if prev:
            d_last[cheb(m["selected"], prev)] += 1
        d_best[cheb(m["selected"], m["ai_top"])] += 1
    loss = sum((m["point_loss"] or 0.0) for m in rows)
    print(f"moves={len(rows)} deviations={len(dev)} ({len(dev) / max(1, len(rows)):.0%}) total_loss={loss:.2f}")
    print(
        "cheb(selected, opp_last):", dict(sorted(d_last.items())), " >=4:", sum(v for k, v in d_last.items() if k >= 4)
    )
    print(
        "cheb(selected, ai_top):  ", dict(sorted(d_best.items())), " >=4:", sum(v for k, v in d_best.items() if k >= 4)
    )


if __name__ == "__main__":
    main()
