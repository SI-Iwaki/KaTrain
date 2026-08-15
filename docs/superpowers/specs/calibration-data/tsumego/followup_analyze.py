"""followup_concentration_probe.py の結果集計（ペア比較＋符号検定）。

読み方:
  - 別解ペア（group=alt）で「want のほうが follow-up が収束する」が 50% を大きく超えるなら
    ユーザー仮説は作意の実信号（選択則に使える可能性）。
  - control で同じ規則が want を裏切る率が同程度なら、シャッフル（採用不可）。

usage: python followup_analyze.py [--in PATH] [--metric fu_v2_v1|...]
ASCII output only.
"""
import argparse
import json
import math
import os


def sign_test(wins, losses):
    """両側二項検定の近似 p 値（正規近似・n>=10 で十分）。"""
    n = wins + losses
    if n == 0:
        return 1.0
    if n < 10:
        # 正確二項（小標本）
        from math import comb

        k = max(wins, losses)
        p = sum(comb(n, i) for i in range(k, n + 1)) / (2 ** n) * 2
        return min(1.0, p)
    z = (abs(wins - losses) - 1) / math.sqrt(n)
    # 2-sided normal tail
    return math.erfc(z / math.sqrt(2))


def get(row, side, path):
    d = row.get(f"{side}_{path[0]}")
    for k in path[1:]:
        if d is None:
            return None
        d = d.get(k)
    return d


def pair_stats(rows, extractor, higher_is_concentrated):
    wins = losses = ties = miss = 0
    for r in rows:
        a = extractor(r, "want")
        b = extractor(r, "rival")
        if a is None or b is None:
            miss += 1
            continue
        if a == b:
            ties += 1
        elif (a > b) == higher_is_concentrated:
            wins += 1
        else:
            losses += 1
    n = wins + losses
    return {
        "want_wins": wins,
        "rival_wins": losses,
        "ties": ties,
        "missing": miss,
        "p_want": round(wins / n, 3) if n else None,
        "p_sign": round(sign_test(wins, losses), 4) if n else None,
    }


METRICS = [
    # (label, extractor(row, side), higher_is_concentrated)
    ("fu_dominant", lambda r, s: (None if get(r, s, ("followup", "dominant")) is None else int(get(r, s, ("followup", "dominant")))), True),
    ("fu_v2_v1", lambda r, s: get(r, s, ("followup", "v2_v1")), False),
    ("fu_v1_share", lambda r, s: get(r, s, ("followup", "v1_share")), True),
    ("fu_pl_gap", lambda r, s: get(r, s, ("followup", "pl_gap")), True),
    ("fu_prior2_prior1", lambda r, s: get(r, s, ("followup", "prior2_prior1")), False),
    ("reply_v2_v1", lambda r, s: get(r, s, ("reply", "v2_v1")), False),
    ("reply_v1_share", lambda r, s: get(r, s, ("reply", "v1_share")), True),
    ("hp", lambda r, s: r.get(f"hp_{'want' if s == 'want' else 'rival'}"), True),
]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(here, "followup-probe-results.jsonl"))
    args = ap.parse_args()

    rows = []
    errors = 0
    for raw in open(args.inp, encoding="utf-8"):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if "error" in d:
            errors += 1
            continue
        rows.append(d)
    print(f"rows: {len(rows)} (errors skipped: {errors})")

    groups = sorted(set(r["group"] for r in rows))
    for g in groups:
        sub = [r for r in rows if r["group"] == g]
        print(f"\n=== group={g} (n={len(sub)}) ===")
        for label, ex, hic in METRICS:
            st = pair_stats(sub, ex, hic)
            print(f"  {label:18s} want_wins={st['want_wins']:3d} rival_wins={st['rival_wins']:3d}"
                  f" ties={st['ties']:3d} miss={st['missing']:3d}"
                  f" P(want)={st['p_want']} p={st['p_sign']}")
        # 層別: 親局面が ambiguous だったケースだけ（ユーザー体感の帯）
        amb = [r for r in sub if r.get("parent_ambiguous")]
        if amb and len(amb) != len(sub):
            print(f"  -- parent_ambiguous only (n={len(amb)}):")
            for label, ex, hic in METRICS[:4] + [METRICS[-1]]:
                st = pair_stats(amb, ex, hic)
                print(f"  {label:18s} want_wins={st['want_wins']:3d} rival_wins={st['rival_wins']:3d}"
                      f" ties={st['ties']:3d} P(want)={st['p_want']} p={st['p_sign']}")
        # depth 0（初手）だけ
        d0 = [r for r in sub if r.get("depth") == 0]
        if d0 and len(d0) != len(sub):
            print(f"  -- depth==0 only (n={len(d0)}):")
            for label, ex, hic in METRICS[:4] + [METRICS[-1]]:
                st = pair_stats(d0, ex, hic)
                print(f"  {label:18s} want_wins={st['want_wins']:3d} rival_wins={st['rival_wins']:3d}"
                      f" ties={st['ties']:3d} P(want)={st['p_want']} p={st['p_sign']}")


if __name__ == "__main__":
    main()
