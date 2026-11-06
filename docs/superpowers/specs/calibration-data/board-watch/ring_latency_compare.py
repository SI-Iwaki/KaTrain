"""ring_difficulty_latency_probe.py の ABBA を局面ごとに対にして比べる（board-watch spec 追記11 の採用ゲート）。

    python ring_latency_compare.py runs/ring9-off-1.jsonl runs/ring9-on-1.jsonl runs/ring9-on-2.jsonl runs/ring9-off-2.jsonl

ゲート: 局面ごとの比 ON/OFF の平均の 95% 区間（局面のブートストラップ）の上限 < 1.03 かつ ON の ready 率 >= 0.95。
出力は ASCII のみ（cp932 の端末で落ちない）。
"""

import json
import random
import statistics
import sys

GATE_RATIO = 1.03
GATE_READY = 0.95


def quantile(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else float("nan")


def main(paths):
    rows = [json.loads(line) for p in paths for line in open(p, encoding="utf-8") if line.strip()]
    rows = [r for r in rows if not r.get("warmup") and r.get("complete", True)]
    by = {}
    for r in rows:
        by.setdefault((r["sgf"], r["depth"]), {"on": [], "off": []})[r["arm"]].append(r["t_analysis"])
    ratios = [statistics.mean(v["on"]) / statistics.mean(v["off"]) for v in by.values() if v["on"] and v["off"]]
    rng = random.Random(20261106)
    boots = sorted(statistics.mean(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
    lo, hi = boots[249], boots[9749]
    on = [r for r in rows if r["arm"] == "on"]
    off = [r for r in rows if r["arm"] == "off"]
    ready = sum(r["hp_ready"] for r in on) / len(on)
    print(
        f"positions={len(ratios)} off_median={statistics.median(r['t_analysis'] for r in off):.3f}s "
        f"on_median={statistics.median(r['t_analysis'] for r in on):.3f}s"
    )
    print(
        f"ratio on/off mean={statistics.mean(ratios):.4f} median={statistics.median(ratios):.4f} 95%CI=[{lo:.4f},{hi:.4f}]"
    )
    print(f"hp_ready={ready:.3f} ({sum(r['hp_ready'] for r in on)}/{len(on)})")
    for key in ("kind_hp", "kind_kata"):
        counts = {}
        for r in on:
            counts[str(r.get(key))] = counts.get(str(r.get(key)), 0) + 1
        print(f"{key} (chosen=best): " + " ".join(f"{k}={v / len(on):.0%}" for k, v in sorted(counts.items())))
    for key in ("E_hp", "E_kata"):
        xs = [r[key] for r in on if r.get(key) is not None]
        print(
            f"{key} p50={quantile(xs, 0.5):.2f} p77={quantile(xs, 0.77):.2f} p80={quantile(xs, 0.8):.2f} "
            f">=1.5:{sum(x >= 1.5 for x in xs) / max(1, len(xs)):.0%}"
        )
    gate = hi < GATE_RATIO and ready >= GATE_READY
    print("GATE", "PASS" if gate else "FAIL")
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
