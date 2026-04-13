# docs/superpowers/specs/calibration-data/aggregate.py
"""Jigo 動的 rank 校正の 3-run 集計スクリプト。

runs/ 配下の {config_id}_run{1,2,3}.json を読み、config ごとに
平均・標準偏差・convergence_score を算出して markdown テーブル + JSON を出力。
"""
import json
import math
import sys
from pathlib import Path

RUNS_DIR = Path(__file__).parent / "runs"
CONFIGS = ["off", "5-15", "3-10", "5-10", "3-15"]

METRICS = [
    "mean_lead", "max_lead",
    "in_target_ratio", "over_target_ratio",
    "mean_selected_hp", "p10_selected_hp",
    "filter_relax_rate",
]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def std(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def convergence_score(m):
    """convergence_score = in_target_ratio - 0.5*over_target_ratio - 0.02*mean_lead"""
    return (
        m["in_target_ratio"]
        - 0.5 * m["over_target_ratio"]
        - 0.02 * m["mean_lead"]
    )


def load_runs(config_id):
    runs = []
    for i in (1, 2, 3):
        path = RUNS_DIR / f"{config_id}_run{i}.json"
        if not path.exists():
            print(f"MISSING: {path}", file=sys.stderr)
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        jm = data["stats"].get("jigo_metrics")
        if jm is None:
            print(f"No jigo_metrics in {path}", file=sys.stderr)
            continue
        runs.append(jm)
    return runs


def aggregate_config(config_id):
    runs = load_runs(config_id)
    if not runs:
        return None
    agg = {"config_id": config_id, "n_runs": len(runs)}
    for metric in METRICS:
        vals = [r.get(metric) for r in runs]
        agg[f"{metric}_mean"] = mean(vals)
        agg[f"{metric}_std"] = std(vals)
    # convergence_score per run (run ごとに計算して平均・std)
    conv_scores = [convergence_score(r) for r in runs]
    agg["conv_score_mean"] = mean(conv_scores)
    agg["conv_score_std"] = std(conv_scores)
    # rank_downgrade_counts は最後の run のみ参考表示（3run 平均は意味薄）
    agg["rank_downgrade_counts_last"] = runs[-1].get("rank_downgrade_counts")
    return agg


def format_markdown_table(aggs):
    lines = []
    header = ("| config | n | conv_score | in_target | over_target | mean_lead | max_lead "
              "| mean_hp | p10_hp | relax_rate |")
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)
    for a in aggs:
        if a is None:
            continue
        row = (
            f"| {a['config_id']} | {a['n_runs']} "
            f"| {a['conv_score_mean']:.3f}±{a['conv_score_std']:.3f} "
            f"| {a['in_target_ratio_mean']:.1%}±{a['in_target_ratio_std']:.1%} "
            f"| {a['over_target_ratio_mean']:.1%}±{a['over_target_ratio_std']:.1%} "
            f"| {a['mean_lead_mean']:.2f}±{a['mean_lead_std']:.2f} "
            f"| {a['max_lead_mean']:.1f}±{a['max_lead_std']:.1f} "
            f"| {a['mean_selected_hp_mean']:.3f}±{a['mean_selected_hp_std']:.3f} "
            f"| {a['p10_selected_hp_mean']:.3f}±{a['p10_selected_hp_std']:.3f} "
            f"| {a['filter_relax_rate_mean']:.1%}±{a['filter_relax_rate_std']:.1%} |"
        )
        lines.append(row)
    return "\n".join(lines)


def apply_gates(aggs):
    """人間らしさ gate: 5-15 基準と比較して pass/fail を判定。"""
    baseline = next((a for a in aggs if a and a["config_id"] == "5-15"), None)
    if baseline is None:
        print("WARN: no baseline 5-15 found, skipping gate check", file=sys.stderr)
        return {}
    gates = {}
    for a in aggs:
        if a is None:
            continue
        cid = a["config_id"]
        if cid == "5-15":
            gates[cid] = "baseline"
            continue
        checks = []
        if baseline["mean_selected_hp_mean"] is not None and a["mean_selected_hp_mean"] is not None:
            checks.append(("mean_hp", a["mean_selected_hp_mean"] >= 0.9 * baseline["mean_selected_hp_mean"]))
        if baseline["p10_selected_hp_mean"] is not None and a["p10_selected_hp_mean"] is not None:
            checks.append(("p10_hp", a["p10_selected_hp_mean"] >= 0.8 * baseline["p10_selected_hp_mean"]))
        checks.append(("relax_rate", a["filter_relax_rate_mean"] <= 1.2 * max(baseline["filter_relax_rate_mean"], 0.01)))
        passed = all(ok for _, ok in checks)
        failing = [name for name, ok in checks if not ok]
        gates[cid] = "pass" if passed else f"fail({','.join(failing)})"
    return gates


def main():
    aggs = [aggregate_config(c) for c in CONFIGS]
    print("# Jigo Dynamic Rank Calibration Aggregate\n")
    print("## Aggregate Table (3-run mean ± std)\n")
    print(format_markdown_table(aggs))
    print()

    gates = apply_gates(aggs)
    print("## Gates\n")
    for cid, status in gates.items():
        print(f"- `{cid}`: {status}")
    print()

    # 採用判定候補
    valid = [a for a in aggs if a and a["config_id"] != "off" and gates.get(a["config_id"]) in ("pass", "baseline")]
    if valid:
        best = max(valid, key=lambda a: a["conv_score_mean"])
        baseline = next((a for a in aggs if a and a["config_id"] == "5-15"), None)
        print("## Decision Candidate\n")
        print(f"- Best conv_score config: `{best['config_id']}` "
              f"(score={best['conv_score_mean']:.3f}±{best['conv_score_std']:.3f})")
        if baseline and best["config_id"] != "5-15":
            diff = best["conv_score_mean"] - baseline["conv_score_mean"]
            threshold = max(0.05, best["conv_score_std"])
            adopt = diff >= threshold
            print(f"- Diff vs baseline 5-15: {diff:+.3f} "
                  f"(threshold=max(0.05, conv_score_std={best['conv_score_std']:.3f}))")
            print(f"- **Adopt:** {'YES' if adopt else 'NO (保守的バイアスで現行維持)'}")
        elif best["config_id"] == "5-15":
            print("- Best is baseline itself → 現行維持")

    print()
    # 最後に rank downgrade counts（デバッグ用）
    print("## Rank Downgrade Counts (last run)\n")
    for a in aggs:
        if a is None:
            continue
        print(f"- `{a['config_id']}`: {a['rank_downgrade_counts_last']}")


if __name__ == "__main__":
    main()
