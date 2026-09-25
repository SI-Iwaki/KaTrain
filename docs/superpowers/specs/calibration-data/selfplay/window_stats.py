"""序盤の窓の指標（spec 2026-09-23-veil-strategy-design.md §16.2 手順7・§16.5）: 自己対局ハーネスの実行ディレクトリの
moves.jsonl / games.jsonl から、アームごとに窓の中（手数 <= W）と窓の後の一致率・損失・大きな損、W 手目のリード、flip、
窓の後の緊急度 u と支払った外し（paid）、定跡を知る相手が定跡を外れた手数を出す。

    python window_stats.py DIR [DIR ...] [--window W] [--compare A B] [--conf 0.975] [--out DIR]
    python window_stats.py --recon RECON [RECON ...] [--window W] [--out DIR]   # 実戦の事後解析（spec §16.5 の「実戦」）

- W の既定は run.json の盤サイズ（9路 12・13路 30）。複数の DIR（例 9-1 と 9-2）は合わせて読む: アームの指紋・任せる先の指紋・
  対局条件・計測の基準が違えば katrain_debug.selfplay_run.load_records と同じ SystemExit で止まる（final-fix finding 1）。
- 中断した局（games.jsonl の result aborted）は除く。一致率はレポートと同じ定義（points_lost の無い手と、最後の石より後の
  パスを除く）。手数は moves.jsonl の depth（打った手のノードの手数）。
- 韜晦のアームは decision_open でも窓を確かめる（窓の外に decision_open がある手・窓の中の AI の手で decision_open が無い手を数える）。
  「open なアーム」は run.json のアームの effective_settings の `*_open_moves` > 0 を優先し、無ければそのアームのどれかの局に
  decision_open があるかで決める（局ごとに決めると、研究外しが一度も発動しなかった局が missing を 0 にしてしまう。finding 2）。
  games_with_open（decision_open が実際に出た局の数）も出す。
- 定跡を知る相手が ai_loss で外れた局は、外れた手（moves.jsonl の depth == book_exit_depth の AI の手）が最善手だったか
  （噪音駆動の外し）と、その手の points_lost の中央値・平均も出す（finding 3）。
- --compare A B: 同じ seed の対の差 A − B（窓の中・後の自分と相手の一致率・W 手目のリード）。t 区間（--conf）と Wilcoxon の p。
- --recon: DIR は実戦の復元と事後解析のディレクトリ（recon_9/・recon_9_veil/ の report_game_*.json）。局ごとと全体の、自分と相手の
  窓の中・後の一致率（2500v の最善手との一致）と、相手の最初の手から最善手が続いた手数（opp_streak）。DIR ごとに別の表（合わせない）。
  json は --out を渡したときだけ <out>/window_stats_recon.json に書く（コミット済みの recon に書かない）。
出力は表（ASCII）と <out>/window_stats.json（既定の out は最初の DIR）。KataGo は使わない。
"""

import argparse
import glob
import json
import os
import statistics
import sys
from collections import Counter

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)

from katrain_debug import selfplay_run as R  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402

WINDOW = {9: 12, 13: 30}  # spec §15.2 の想定の窓（9路 12・13路 30）
SIDES = (("own", True), ("opp", False))


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_runs(dirs):
    """-> (size, records, moves, arm_open)。中断した局は records・moves の両方から除く。

    複数の DIR は katrain_debug.selfplay_run.load_records で突き合わせる（アームの指紋・任せる先の指紋・対局条件・
    計測の基準が違えば SystemExit・同じ (arm, seed) が2回現れても SystemExit。final-fix finding 1）。
    arm_open: アーム名 -> run.json のそのアームの effective_settings に `*_open_moves` > 0 があるか。run.json に
    アームが無ければ (dirs に旧い run.json しか無ければ) キーそのものが無く、per_game が moves.jsonl の decision_open
    列で決める（finding 2）。
    """
    outs = [R.OutputDir(d) for d in dirs]
    sizes, arm_open, moves = set(), {}, []
    for out, d in zip(outs, dirs):
        with open(os.path.join(d, "run.json"), encoding="utf-8") as f:
            plan = json.load(f)
        sizes.add(plan["size"])
        for arm in plan.get("arms") or []:
            eff = arm.get("effective_settings") or {}
            arm_open[arm["name"]] = any(k.endswith("_open_moves") and (v or 0) > 0 for k, v in eff.items())
        moves.extend(read_jsonl(os.path.join(d, "moves.jsonl")))
    if len(sizes) != 1:
        raise SystemExit(f"runs of different board sizes: {sorted(sizes)}")
    # finding 1: 複数 DIR の突き合わせ（アームの指紋・任せる先の指紋・対局条件・計測の基準）は selfplay_run.load_records に
    # 任せる。1 DIR だけならその必要が無い（旧い/簡略な run.json でも読める）ので自分で読む。
    records = R.load_records(outs) if len(outs) > 1 else outs[0].records()
    ok = {(r["arm"], r["seed"]) for r in records if r.get("result") != "aborted"}
    return (
        sizes.pop(),
        [r for r in records if (r["arm"], r["seed"]) in ok],
        [m for m in moves if (m["arm"], m["seed"]) in ok],
        arm_open,
    )


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def game_window_stats(rows, window, arm_is_open=False):
    """1局分の moves の行 → 窓の中（in）と後（out）の自分・相手の数・W 手目のリード・flip・窓の後の u と paid。

    arm_is_open: このアームが研究外し（open_moves > 0）を持つか（per_game がアーム全体で決める。finding 2）。
    open_missing_inside はこれが True の局でだけ数える（局ごとに decision_open の有無で決めると、研究外しが一度も
    発動しなかった局が missing を 0 にしてしまう）。
    """
    out = {}
    counted = [r for r in rows if r.get("points_lost") is not None and not r.get("trailing_pass")]
    for side, is_ai in SIDES:
        for part in ("in", "out"):
            sel = [r for r in counted if r["is_ai"] == is_ai and (r["depth"] <= window) == (part == "in")]
            losses = [max(0.0, r["points_lost"]) for r in sel]
            out[f"{side}_{part}"] = {
                "n": len(sel),
                "match": sum(1 for r in sel if r["match"]),
                "loss": sum(losses),
                "ge2": sum(1 for x in losses if x >= 2.0),
                "ge6": sum(1 for x in losses if x >= 6.0),
            }
    inside = [r for r in rows if r["depth"] <= window]
    out["lead_at_w"] = inside[-1].get("lead_after_ai") if inside else None
    ai_rows = [r for r in rows if r["is_ai"]]
    for part in ("in", "out"):
        out[f"flip_{part}"] = sum(
            1
            for r in ai_rows
            if (r["depth"] <= window) == (part == "in")
            and r.get("wr_before_ai") is not None
            and r.get("wr_after_ai") is not None
            and r["wr_before_ai"] >= 0.5
            and r["wr_after_ai"] < 0.5
        )
    after = [r for r in ai_rows if r["depth"] > window]
    out["u_after"] = [r["decision_u"] for r in after if isinstance(r.get("decision_u"), (int, float))]
    out["paid_after"] = sum(1 for r in after if r.get("decision_kind") == "paid")
    opened = [r for r in ai_rows if r.get("decision_open") is not None]
    out["open"] = dict(Counter(r["decision_open"] for r in opened))
    out["open_outside"] = sum(1 for r in opened if r["depth"] > window)
    out["open_engaged"] = bool(opened)
    out["open_missing_inside"] = (
        sum(1 for r in ai_rows if r["depth"] <= window and r.get("decision_open") is None) if arm_is_open else 0
    )
    return out


def rate(block):
    return block["match"] / block["n"] if block["n"] else None


def per_game(records, moves, window, arm_open=None):
    """(arm, seed) → 1局の指標（game_window_stats ＋ 定跡を知る相手の book_exit_depth / book_exit_reason / book_played /
    book_exit_move）。

    arm_open: load_runs の run.json 由来の「open なアーム」（アーム名 → bool）。run.json に無いアームは、そのアームの
    どれかの局に decision_open があるか（moves.jsonl のフォールバック・全局分の OR）で決める（finding 2）。
    """
    rows_of = {}
    for m in moves:
        rows_of.setdefault((m["arm"], m["seed"]), []).append(m)
    arm_open = dict(arm_open or {})
    fallback = {}
    for (arm, _), rows in rows_of.items():
        engaged = any(row.get("is_ai") and row.get("decision_open") is not None for row in rows)
        fallback[arm] = fallback.get(arm, False) or engaged
    for arm, engaged in fallback.items():
        arm_open.setdefault(arm, engaged)
    out = {}
    for r in records:
        key = (r["arm"], r["seed"])
        rows = sorted(rows_of.get(key, []), key=lambda m: m["depth"])
        st = game_window_stats(rows, window, arm_open.get(r["arm"], False))
        opp = r.get("opponent_stats") or {}
        st["book_exit_depth"] = opp.get("book_exit_depth")
        st["book_exit_reason"] = opp.get("book_exit_reason")
        st["book_played"] = opp.get("book_played")
        st["book_exit_move"] = None
        if st["book_exit_reason"] == "ai_loss" and st["book_exit_depth"] is not None:
            move = next((m for m in rows if m.get("is_ai") and m["depth"] == st["book_exit_depth"]), None)
            if move is not None:
                st["book_exit_move"] = {"match": move.get("match"), "points_lost": move.get("points_lost")}
        out[key] = st
    return out


def arm_summary(games):
    """1アームの局の指標のリスト → 要約（一致率は手をまとめた値と局平均・損失/手・大きな損/局・リードの分布ほか）。

    book_exit はこのアームの games だけから作る（定跡を知る相手の書物の外し方はアームごとに変わりうるので、書物の出口の
    深さと理由をアーム間で混ぜずに見えるようにする）。
    """
    s = {"games": len(games)}
    for side, _ in SIDES:
        for part in ("in", "out"):
            blocks = [g[f"{side}_{part}"] for g in games]
            n = sum(b["n"] for b in blocks)
            s[f"{side}_{part}"] = {
                "n": n,
                "rate_pooled": sum(b["match"] for b in blocks) / n if n else None,
                "rate_mean": _mean([rate(b) for b in blocks]),
                "loss_per_move": sum(b["loss"] for b in blocks) / n if n else None,
                "ge2_per_game": _mean([b["ge2"] for b in blocks]),
                "ge6_per_game": _mean([b["ge6"] for b in blocks]),
            }
    leads = [g["lead_at_w"] for g in games if g["lead_at_w"] is not None]
    s["lead_at_w"] = {
        "n": len(leads),
        "median": S.percentile(leads, 0.5),
        "p25": S.percentile(leads, 0.25),
        "p75": S.percentile(leads, 0.75),
        "min": min(leads) if leads else None,
        "negative": sum(1 for x in leads if x < 0),
    }
    s["flip_in_per_game"] = _mean([g["flip_in"] for g in games])
    s["flip_out_per_game"] = _mean([g["flip_out"] for g in games])
    s["u_after_mean"] = _mean([u for g in games for u in g["u_after"]])
    s["paid_after_per_game"] = _mean([g["paid_after"] for g in games])
    opened = Counter()
    for g in games:
        opened.update(g["open"])
    s["open"] = dict(opened)
    s["open_outside"] = sum(g["open_outside"] for g in games)
    s["open_missing_inside"] = sum(g["open_missing_inside"] for g in games)
    s["games_with_open"] = sum(1 for g in games if g["open_engaged"])
    exits = [g["book_exit_depth"] for g in games if g["book_exit_depth"] is not None]
    noise_moves = [g["book_exit_move"] for g in games if g["book_exit_reason"] == "ai_loss" and g["book_exit_move"]]
    noise_losses = [m["points_lost"] for m in noise_moves if m.get("points_lost") is not None]
    s["book_exit"] = {
        "games": len(exits),
        "median": S.percentile(exits, 0.5),
        "min": min(exits) if exits else None,
        "reasons": dict(Counter(g["book_exit_reason"] for g in games if g["book_exit_reason"])),
        "noise": {
            "n": len(noise_moves),
            "on_best_move": sum(1 for m in noise_moves if m.get("match")),
            "loss_median": S.percentile(noise_losses, 0.5),
            "loss_mean": _mean(noise_losses),
        },
    }
    played = [g["book_played"] for g in games if g.get("book_played") is not None]
    s["book_played_per_game"] = _mean(played)
    return s


PAIRED = (
    ("own_in", lambda g: rate(g["own_in"])),
    ("own_out", lambda g: rate(g["own_out"])),
    ("opp_in", lambda g: rate(g["opp_in"])),
    ("opp_out", lambda g: rate(g["opp_out"])),
    ("lead_at_w", lambda g: g["lead_at_w"]),
)


def paired_diffs(stats, a, b, conf=0.975):
    """同じ seed の対の差 a − b（窓の中・後の一致率と W 手目のリード）。"""
    seeds = sorted({s for arm, s in stats if arm == a} & {s for arm, s in stats if arm == b})
    out = {}
    for name, fn in PAIRED:
        diffs = []
        for seed in seeds:
            va, vb = fn(stats[a, seed]), fn(stats[b, seed])
            if va is not None and vb is not None:
                diffs.append(va - vb)
        lo, hi = S.t_interval(diffs, conf)
        out[name] = {
            "n": len(diffs),
            "mean": statistics.fmean(diffs) if diffs else None,
            "t_ci": [lo, hi],
            "wilcoxon_p": S.wilcoxon_signed_rank(diffs),
        }
    return out


def fmt(v, spec=".3f"):
    return "-" if v is None else format(v, spec)


def pct(v):
    return "-" if v is None else f"{100 * v:.1f}%"


def format_text(result):
    w = result["window"]
    lines = [
        f"# window stats (W = {w}: in = depth <= {w}, out = depth > {w}; aborted games excluded)",
        "",
        f"{'arm':<12} {'n':>3} {'own in':>7} {'own out':>7} {'opp in':>7} {'opp out':>7} {'loss o in/out':>13} "
        f"{'loss p in/out':>13} {'>=2 in':>6} {'>=6 in':>6} {'lead@W med':>10} {'<0':>3} {'flip i/o':>9} {'u out':>5} "
        f"{'paid out':>8} {'book exit':>9}",
    ]
    for arm, s in result["arms"].items():
        lines.append(
            f"{arm[:12]:<12} {s['games']:>3} {pct(s['own_in']['rate_mean']):>7} {pct(s['own_out']['rate_mean']):>7} "
            f"{pct(s['opp_in']['rate_mean']):>7} {pct(s['opp_out']['rate_mean']):>7} "
            f"{fmt(s['own_in']['loss_per_move'], '.2f'):>6}/{fmt(s['own_out']['loss_per_move'], '.2f'):<6} "
            f"{fmt(s['opp_in']['loss_per_move'], '.2f'):>6}/{fmt(s['opp_out']['loss_per_move'], '.2f'):<6} "
            f"{fmt(s['own_in']['ge2_per_game'], '.2f'):>6} {fmt(s['own_in']['ge6_per_game'], '.2f'):>6} "
            f"{fmt(s['lead_at_w']['median'], '+.1f'):>10} {s['lead_at_w']['negative']:>3} "
            f"{fmt(s['flip_in_per_game'], '.2f'):>4}/{fmt(s['flip_out_per_game'], '.2f'):<4} "
            f"{fmt(s['u_after_mean'], '.2f'):>5} {fmt(s['paid_after_per_game'], '.2f'):>8} "
            f"{fmt(s['book_exit']['median'], '.0f'):>9}"
        )
    for arm, s in result["arms"].items():
        if s["open"] or s["games_with_open"]:
            lines.append(
                f"open {arm}: {s['open']} outside_window={s['open_outside']} missing_inside={s['open_missing_inside']} "
                f"games_with_open={s['games_with_open']}/{s['games']}"
            )
        if s["book_exit"]["reasons"] or s.get("book_played_per_game") is not None:
            noise = s["book_exit"]["noise"]
            lines.append(
                f"book {arm}: exit reasons {s['book_exit']['reasons']} (games {s['book_exit']['games']}) "
                f"played/game={fmt(s.get('book_played_per_game'), '.1f')} noise {noise['on_best_move']}/{noise['n']} "
                f"loss_median={fmt(noise['loss_median'], '.2f')} loss_mean={fmt(noise['loss_mean'], '.2f')}"
            )
    for c in result.get("compare") or []:
        lines += ["", f"## paired diff {c['a']} - {c['b']} (same seed; conf {c['conf']})"]
        for name, d in c["diffs"].items():
            lines.append(
                f"{name:<10} n={d['n']:>3} mean={fmt(d['mean'], '+.4f')} t={fmt(d['t_ci'][0], '+.4f')}.."
                f"{fmt(d['t_ci'][1], '+.4f')} wilcoxon_p={fmt(d['wilcoxon_p'], '.4f')}"
            )
    return "\n".join(lines) + "\n"


def window_stats(dirs, window=None, compare=None, conf=0.975):
    size, records, moves, arm_open = load_runs(dirs)
    window = window or WINDOW.get(size)
    if window is None:
        raise SystemExit(f"no default window for {size}x{size}: pass --window W")
    stats = per_game(records, moves, window, arm_open)
    arms = sorted({arm for arm, _ in stats})
    result = {
        "sources": list(dirs),
        "size": size,
        "window": window,
        "arms": {arm: arm_summary([g for (a, _), g in sorted(stats.items()) if a == arm]) for arm in arms},
    }
    if compare:
        a, b = compare
        result["compare"] = [{"a": a, "b": b, "conf": conf, "diffs": paired_diffs(stats, a, b, conf)}]
    return result


def recon_game_stats(rows, ai, window):
    """実戦の事後解析の1局（report の rows: depth・player・match・ptloss）→ 窓の中（手数 <= W）と後の自分・相手の手の数と
    最善手との一致の数（ptloss の無い手は除く＝offline_report と同じ）と、相手の最初の手から最善手が続いた相手の手の数（opp_streak）。"""
    out = {}
    counted = [r for r in rows if r.get("ptloss") is not None]
    for side, mine in SIDES:
        for part in ("in", "out"):
            sel = [r for r in counted if (r["player"] == ai) == mine and (r["depth"] <= window) == (part == "in")]
            out[f"{side}_{part}"] = {"n": len(sel), "match": sum(1 for r in sel if r["match"])}
    streak = 0
    for r in rows:
        if r["player"] == ai:
            continue
        if not r["match"]:
            break
        streak += 1
    out["opp_streak"] = streak
    return out


def recon_window_stats(recon_dir, window=None):
    """recon の report_game_*.json → {"source", "size", "window", "games": [...], "summary": {...}}（spec §16.5 の「実戦」）。"""
    reports = []
    for path in sorted(glob.glob(os.path.join(recon_dir, "report_game_*.json"))):
        with open(path, encoding="utf-8") as f:
            reports.append(json.load(f))
    if not reports:
        raise SystemExit(f"{recon_dir}: no report_game_*.json")
    sizes = {r["summary"].get("board_size", 13) for r in reports}
    if len(sizes) != 1:
        raise SystemExit(f"{recon_dir}: games of different board sizes: {sorted(sizes)}")
    size = sizes.pop()
    window = window or WINDOW.get(size)
    if window is None:
        raise SystemExit(f"no default window for {size}x{size}: pass --window W")
    games = [{"game": r["summary"]["game"], **recon_game_stats(r["rows"], r["summary"]["ai"], window)} for r in reports]
    summary = {}
    for side, _ in SIDES:
        for part in ("in", "out"):
            key = f"{side}_{part}"
            n = sum(g[key]["n"] for g in games)
            summary[key] = {
                "n": n,
                "rate_pooled": sum(g[key]["match"] for g in games) / n if n else None,
                "rate_mean": _mean([rate(g[key]) for g in games]),
            }
    streaks = [g["opp_streak"] for g in games]
    summary["opp_streak"] = {"median": S.percentile(streaks, 0.5), "min": min(streaks), "max": max(streaks)}
    return {"source": recon_dir, "size": size, "window": window, "games": games, "summary": summary}


def format_recon_text(result):
    w = result["window"]
    lines = [
        f"# real games {result['source']} (W = {w}: in = depth <= {w}; streak = opponent best moves from its first move)",
        f"{'game':<24} {'own in':>7} {'own out':>7} {'opp in':>7} {'opp out':>7} {'streak':>6}",
    ]
    for g in result["games"]:
        lines.append(
            f"{g['game'][:24]:<24} {pct(rate(g['own_in'])):>7} {pct(rate(g['own_out'])):>7} "
            f"{pct(rate(g['opp_in'])):>7} {pct(rate(g['opp_out'])):>7} {g['opp_streak']:>6}"
        )
    s = result["summary"]
    lines.append(
        f"{'mean of %d games' % len(result['games']):<24} {pct(s['own_in']['rate_mean']):>7} "
        f"{pct(s['own_out']['rate_mean']):>7} {pct(s['opp_in']['rate_mean']):>7} {pct(s['opp_out']['rate_mean']):>7} "
        f"{fmt(s['opp_streak']['median'], '.1f'):>6}"
    )
    return "\n".join(lines) + "\n\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="序盤の窓の指標（spec §16.2 手順7）")
    ap.add_argument("dirs", nargs="+", metavar="DIR", help="自己対局の実行ディレクトリ（合わせて読む）")
    ap.add_argument("--window", type=int, default=None, help="窓の手数 W（既定: 9路 12・13路 30）")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help="同じ seed の対の差 A - B")
    ap.add_argument("--conf", type=float, default=0.975, help="対の差の t 区間の信頼度")
    ap.add_argument("--out", default=None, metavar="DIR", help="window_stats.json の書き先（既定: 最初の DIR）")
    ap.add_argument(
        "--recon",
        action="store_true",
        help="DIR は実戦の復元と事後解析（report_game_*.json）＝実戦の相手の一致率（spec §16.5）",
    )
    args = ap.parse_args(argv)
    if args.recon:
        results = [recon_window_stats(d, args.window) for d in args.dirs]
        if args.out:
            with open(os.path.join(args.out, "window_stats_recon.json"), "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=1)
        text = "".join(format_recon_text(r) for r in results)
        print(text.encode("ascii", "replace").decode("ascii"), end="")
        return results
    result = window_stats(args.dirs, args.window, args.compare, args.conf)
    with open(os.path.join(args.out or args.dirs[0], "window_stats.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    text = format_text(result)
    print(text.encode("ascii", "replace").decode("ascii"), end="")
    return result


if __name__ == "__main__":
    main()
