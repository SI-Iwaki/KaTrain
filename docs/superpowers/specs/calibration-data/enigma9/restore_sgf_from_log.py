"""実戦ログ（debug_level 1）のクエリ JSON から SGF を復元する。

priority が PRIORITY_DEFAULT 帯（1000..1999＝実ノードの通常解析。engine 側で +N される。
実測 2026-08-28: 1038/1039）のクエリだけを見る＝追加 AI クエリ（10000+N）・ponder／先読み
（負）は温める応手を末尾に足した仮想局面なので混ぜてはいけない。復元した AI 色の着手列の
**末尾4手**が `Move generation complete` の末尾4手と一致することを assert して、AI の手番
（depth の偶奇）を取り違えないようにする（先頭比較だとログ先頭に前の対局が混ざると外れる）。
`--ai` を省くと W→B の順に検算して合う側を採る。
用法: python restore_sgf_from_log.py <log> <out.sgf> [--ai W|B]
"""

import json
import re
import sys

REAL_PRIORITY_RANGE = (1000, 2000)  # PRIORITY_DEFAULT 帯
COLS = "ABCDEFGHJKLMNOPQRST"
SGF = "abcdefghijklmnopqrs"


def main():
    log, out = sys.argv[1], sys.argv[2]
    ai_arg = sys.argv[sys.argv.index("--ai") + 1] if "--ai" in sys.argv else None
    txt = open(log, encoding="utf-8", errors="replace").read()
    best = None
    for m in re.finditer(r"Sending query QUERY:\d+: (\{.*\})", txt):
        try:
            q = json.loads(m.group(1))
        except Exception:
            continue
        if not (REAL_PRIORITY_RANGE[0] <= q.get("priority", -1) < REAL_PRIORITY_RANGE[1]):
            continue
        if best is None or len(q["moves"]) > len(best["moves"]):
            best = q
    assert best is not None, "no real-node query found (debug_level 1 required)"
    plays = re.findall(r"Move generation complete: (\S+)", txt)

    def matches(col):
        mv = [g for c, g in best["moves"] if c == col]
        n = min(len(plays), len(mv), 4)
        return n > 0 and mv[-n:] == plays[-n:]

    ai = ai_arg or next((c for c in "WB" if matches(c)), None)
    assert ai and matches(ai), f"AI colour mismatch: W {[g for c, g in best['moves'] if c == 'W'][-4:]} / " \
        f"B {[g for c, g in best['moves'] if c == 'B'][-4:]} vs generated {plays[-4:]}"
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
