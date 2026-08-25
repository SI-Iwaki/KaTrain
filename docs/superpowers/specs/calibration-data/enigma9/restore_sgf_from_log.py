"""実戦ログ（debug_level 1）のクエリ JSON から SGF を復元する。

priority 1011（実ノードの通常解析）のクエリだけを見る＝ponder（-39）は温める応手を
末尾に足した仮想局面なので混ぜてはいけない。復元した W 列が `Playing move` の列と
一致することを assert して、AI の手番（depth の偶奇）を取り違えないようにする。
用法: python restore_sgf_from_log.py <log> <out.sgf> [--ai W|B]
"""

import json
import re
import sys

REAL_PRIORITY = 1011
COLS = "ABCDEFGHJKLMNOPQRST"
SGF = "abcdefghijklmnopqrs"


def main():
    log, out = sys.argv[1], sys.argv[2]
    ai = sys.argv[sys.argv.index("--ai") + 1] if "--ai" in sys.argv else "W"
    txt = open(log, encoding="utf-8", errors="replace").read()
    best = None
    for m in re.finditer(r"Sending query QUERY:\d+: (\{.*\})", txt):
        try:
            q = json.loads(m.group(1))
        except Exception:
            continue
        if q.get("priority") != REAL_PRIORITY:
            continue
        if best is None or len(q["moves"]) > len(best["moves"]):
            best = q
    assert best is not None, "no real-node query found (debug_level 1 required)"
    plays = re.findall(r"Playing move (\S+) and creating game node", txt)
    ai_moves = [g for c, g in best["moves"] if c == ai]
    n = min(len(plays), len(ai_moves))
    assert ai_moves[:n] == plays[:n], f"AI colour mismatch: {ai_moves[:5]} vs {plays[:5]}"
    size = best["boardXSize"]

    def sgf_coord(gtp):
        if gtp == "pass":
            return ""
        return SGF[COLS.index(gtp[0])] + SGF[size - int(gtp[1:])]

    nodes = "".join(f";{c}[{sgf_coord(g)}]" for c, g in best["moves"])
    pb, pw = ("human", "enigma") if ai == "W" else ("enigma", "human")
    sgf = f"(;GM[1]FF[4]SZ[{size}]KM[{best['komi']}]RU[{best['rules']}]PB[{pb}]PW[{pw}]{nodes})"
    open(out, "w", encoding="utf-8").write(sgf)
    print(f"{len(best['moves'])} moves, size {size}, komi {best['komi']}, AI={ai} -> {out}")


if __name__ == "__main__":
    main()
