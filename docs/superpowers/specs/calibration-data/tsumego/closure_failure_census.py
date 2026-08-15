"""抽出失敗398問（「領域が閉じていない」）の失敗理由の全数調査（挙動変更なし・CPUのみ）。

抽出器拡張プロジェクト（次セッション以降）の設計材料。extract() が anchors を作れない
のは候補連ごとに (a) 単独閉包が None（空点が盤の広域へ抜ける＝FILL_CAP 超え）か
(b) 閉包はできるが _reaches_safety（自色の壁/地に裏打ち＝種にしない）のどちらかなので、
盤ごとに全候補の内訳と「逃げ出す空間の規模」を測る。

逃げ空間の規模が設計の分水嶺:
  - 90〜200点程度に集中 → 「石の外接矩形から距離kの仮想境界を攻め方安全と仮定して閉じる」
    （枠の df-pn 版）が届く可能性
  - 盤の空点ほぼ全部 → 部分盤の切り出しそのものが必要

usage: python closure_failure_census.py
ASCII output only.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", ".."))

from katrain.core.tsumego_answer_book import gtp_to_point  # noqa: E402
from katrain.core.tsumego_problem import _Extractor, FRONTIER_LIBERTIES, ProblemError  # noqa: E402
from katrain.core.tsumego_solver.board import board_from_stones  # noqa: E402
from katrain.core.tsumego_solver.model import EMPTY  # noqa: E402


def escape_size(board, chain_stones, cap=400):
    """連の呼吸点から空点だけを BFS したときの到達空点数（cap で打ち切り）。"""
    seen = set()
    stack = []
    for p in chain_stones:
        for n in board.neighbors[p]:
            if board.stones[n] == EMPTY and n not in seen:
                seen.add(n)
                stack.append(n)
    while stack:
        p = stack.pop()
        if len(seen) > cap:
            return cap + 1
        for n in board.neighbors[p]:
            if board.stones[n] == EMPTY and n not in seen:
                seen.add(n)
                stack.append(n)
    return len(seen)


def main():
    book = json.load(open(os.path.expanduser("~/.katrain/tsumego_answers.json"), encoding="utf-8"))["entries"]
    board_bucket = collections.Counter()
    escape_hist = collections.Counter()
    rows = []
    for key, e in book.items():
        size = e["size"]
        black = {gtp_to_point(s) for s in e["canonical_black"]}
        white = {gtp_to_point(s) for s in e["canonical_white"]}
        board = board_from_stones((size, size), black, white)
        ex = _Extractor(board, "B", None, 72)
        try:
            ex.extract()
            continue  # 抽出成功はこの調査の対象外
        except ProblemError as err:
            if "閉じ" not in str(err):
                board_bucket["other_error"] += 1
                continue
        candidates = [
            ci
            for ci in range(len(ex.chains))
            if ex.chains[ci][0][0] not in ex.pass_alive
            and not all(p in ex.pass_alive for p in ex.chains[ci][0])
        ]
        n_none = n_safe = 0
        min_escape = None
        for ci in candidates:
            single = ex._closure({ci}, FRONTIER_LIBERTIES)
            if single is None:
                n_none += 1
                esc = escape_size(board, ex.chains[ci][0])
                min_escape = esc if min_escape is None else min(min_escape, esc)
            elif ex._reaches_safety(ci, single[3], single[4]):
                n_safe += 1
        n_empty_total = sum(1 for v in board.stones if v == EMPTY)
        if not candidates:
            kind = "no_candidates"
        elif n_none and not n_safe:
            kind = "all_open"
        elif n_safe and not n_none:
            kind = "all_reach_safety"
        else:
            kind = "mixed_open_and_safe"
        board_bucket[kind] += 1
        if min_escape is not None:
            b = min(min_escape // 20 * 20, 400)
            escape_hist[b] += 1
        rows.append(
            {
                "key": key[:10],
                "size": size,
                "kind": kind,
                "n_candidates": len(candidates),
                "n_closure_none": n_none,
                "n_reach_safety": n_safe,
                "min_escape": min_escape,
                "board_empties": n_empty_total,
            }
        )
    print("boards analyzed:", len(rows))
    print("board buckets:", dict(sorted(board_bucket.items(), key=lambda x: -x[1])))
    print("min escape-size histogram (20-point bins, cap 400):")
    for b in sorted(escape_hist):
        label = f">{400}" if b >= 400 else f"{b}-{b + 19}"
        print(f"  {label:>8s}: {escape_hist[b]}")
    out = os.path.join(HERE, "closure-failure-census.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
