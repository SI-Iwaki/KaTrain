"""自己対局ハーネスの実行計画・出力ディレクトリ・再開・要約（spec §5・§6）。

run.json（計画＋実行環境）を最初に書き、1局ごとに games.jsonl / moves.jsonl に追記して flush する。
--resume は run.json の計画をそのまま使い、games.jsonl にある (arm, seed) を飛ばす（--retry-aborted なら aborted の局は
打ち直す）。要約は複数の実行（停止規則の延長 --seed-base 1020 など）を合わせて出せる。
"""

import datetime
import glob
import json
import os
import subprocess
import sys

os.environ.setdefault("KIVY_NO_ARGS", "1")

from katrain.core import ai as ai_module  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.selfplay_game import (  # noqa: E402
    EngineWatchdog,
    Harness,
    make_opponent,
    play_game,
    resolve_arm,
    start_engine,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELFPLAY_DATA = os.path.join(REPO_ROOT, "docs", "superpowers", "specs", "calibration-data", "selfplay")
RECON_DIR = os.path.join(SELFPLAY_DATA, "recon")
DEFAULT_OUT_ROOT = os.path.join(REPO_ROOT, "experiments", "selfplay")
COMPARE_METRICS = ("own_top1", "opp_top1", "own_minus_opp", "flip_moves", "win", "own_mean_ptloss", "ge6")


def default_pool_path(size):
    return os.path.join(SELFPLAY_DATA, f"opponent_pool_{size}.json")


def load_resign_pool(size, recon_dir=RECON_DIR):
    summaries = []
    for path in sorted(glob.glob(os.path.join(recon_dir, "report_game_*.json"))):
        with open(path, encoding="utf-8") as f:
            summaries.append(json.load(f)["summary"])
    return S.resign_pool_from_summaries(summaries, size)


def git_info(path):
    def git(*args):
        try:
            r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    status = git("status", "--porcelain")
    return {"head": git("rev-parse", "HEAD"), "dirty": None if status is None else bool(status)}


def run_meta(stub):
    """run.json の実行環境: エンジン設定・ai.py の場所・git HEAD と dirty（worktree の取り違え対策）。"""
    ai_dir = os.path.dirname(os.path.abspath(ai_module.__file__))
    return {
        "engine": dict(stub.config("engine") or {}),
        "ai_file": os.path.abspath(ai_module.__file__),
        "git": git_info(ai_dir),
        "python": sys.version.split()[0],
    }


def make_plan(
    subcommand,
    arms,
    schedule,
    *,
    size,
    komi,
    rules="chinese",
    komi_shift=0.0,
    max_moves=None,
    opponent=None,
    resign=None,
    watch_flags=False,
    timeout=180.0,
    target=None,
    extra=None,
):
    """実行計画（run.json の本体）。order は ABBA（10 seed ごとにアームの順を反転）。"""
    return {
        "subcommand": subcommand,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "command": list(sys.argv),
        "size": size,
        "komi": komi,
        "rules": rules,
        "komi_shift": komi_shift,
        "max_moves": max_moves,
        "watch_flags": watch_flags,
        "timeout": timeout,
        "target": S.TARGET_RATE.get(size, 0.30) if target is None else target,
        "arms": [a.as_dict() for a in arms],
        "schedule": schedule,
        "order": [list(x) for x in S.abba_order([a.name for a in arms], len(schedule))],
        "opponent": opponent or {"kind": "humansl", "ranks": sorted({s["rank"] for s in schedule}), "tau": 1.0},
        "resign": resign or {},
        **(extra or {}),
    }


class OutputDir:
    """experiments/selfplay/<YYYYMMDD_HHMM>_<label>/（gitignore 済み）。"""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        for sub in ("sgf", "logs"):
            os.makedirs(os.path.join(self.path, sub), exist_ok=True)

    @classmethod
    def create(cls, root, label):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        path = os.path.join(root, f"{stamp}_{label}")
        if os.path.exists(path):  # 同じ分に同じ label で始めると前の games.jsonl と混ざる
            raise SystemExit(f"{path} already exists: use another --label, or --resume {path}")
        return cls(path)

    def file(self, *parts):
        return os.path.join(self.path, *parts)

    def write_json(self, name, obj):
        with open(self.file(name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)

    def read_json(self, name):
        with open(self.file(name), encoding="utf-8") as f:
            return json.load(f)

    def records(self):
        path = self.file("games.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def done_keys(self):
        return {(r["arm"], r["seed"]) for r in self.records()}

    def drop_aborted(self):
        """--retry-aborted: games.jsonl から aborted の行を aborted.jsonl へ移す（次の再開で打ち直す）。移した数を返す。"""
        records = self.records()
        aborted = [r for r in records if r.get("result") == "aborted"]
        if not aborted:
            return 0
        with open(self.file("aborted.jsonl"), "a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in aborted)
        with open(self.file("games.jsonl"), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in records if r not in aborted)
        return len(aborted)

    def prune_moves(self, done):
        """再開時: games.jsonl に無い局（落ちた局の書きかけ）の moves.jsonl の行を捨てる。"""
        path = self.file("moves.jsonl")
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            keep = [line for line in f if line.strip() and tuple(json.loads(line)[k] for k in ("arm", "seed")) in done]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(keep)

    def write_game(self, result, trainer_config):
        """SGF（KT 解析つき）・ログ・moves.jsonl・games.jsonl の順に書く（games.jsonl の行が完了の印）。"""
        rec = result.record
        key = f"{rec['arm']}_{rec['seed']}_{rec['ai_color']}"
        sgf_path = self.file("sgf", key + ".sgf")
        try:
            result.game.write_sgf(sgf_path, trainer_config=trainer_config)
            rec["sgf"] = os.path.relpath(sgf_path, self.path)
        except Exception as e:  # SGF が書けなくても集計は残す
            rec["sgf"] = None
            rec["sgf_error"] = repr(e)
        with open(self.file("logs", key + ".log"), "w", encoding="utf-8") as f:
            f.write("\n".join(result.logs) + "\n")
        with open(self.file("moves.jsonl"), "a", encoding="utf-8") as f:
            for row in result.rows:
                line = {"arm": rec["arm"], "seed": rec["seed"], **S.flat_row(row)}
                f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
            f.flush()
        with open(self.file("games.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            f.flush()


def fmt_num(v, spec=".3f"):
    return "-" if v is None else format(v, spec)


def progress_line(rec, done, total):
    return (
        f"[{done}/{total}] {rec['arm']} seed={rec['seed']} ai={rec['ai_color']} vs {rec['rank']}: "
        f"{rec['result']} ({rec['end_reason']}) moves={rec['n_moves']} own={fmt_num(rec['own_top1'])} "
        f"opp={fmt_num(rec['opp_top1'])} lead={fmt_num(rec['final_lead'], '+.1f')} {fmt_num(rec['wall_s'], '.0f')}s"
        + (f" error={rec['error']}" if rec.get("error") else "")
    )


def execute_plan(
    plan,
    out,
    stub,
    *,
    engine_factory=start_engine,
    watchdog_interval=2.0,
    hooks_builder=None,
    retry_aborted=False,
    log=print,
):
    """計画の未完了の局を順に打つ。アームの解決済み設定が計画時と違えば中止（config を途中で変えた）。

    各局の前にエンジンの死活を見て、落ちていれば再起動する（spec §2: 落ちた局だけ aborted にして続行）。
    hooks_builder(plan, arms) -> factory(arm_name) -> [hook]（hp 監査・影判定。selfplay_hooks.make_hooks_factory）。
    retry_aborted: 再開のとき aborted の局も打ち直す（OutputDir.drop_aborted）。
    """
    arms = {}
    for entry in plan["arms"]:
        arm = resolve_arm(stub, entry["name"], entry["strategy"], entry["override_items"])
        if arm.fingerprint != entry["fingerprint"]:
            raise SystemExit(
                f"arm {entry['name']}: resolved settings differ from run.json (config edited?). Start a new run."
            )
        arms[arm.name] = arm
    opponent_arm = None
    if plan["opponent"]["kind"] == "strategy":
        o = plan["opponent"]
        opponent_arm = resolve_arm(stub, "opponent", o["strategy"], o["override_items"])
    hooks_for = hooks_builder(plan, arms) if hooks_builder else (lambda name: [])
    if retry_aborted:
        n = out.drop_aborted()
        if n:
            log(f"retry: {n} aborted game(s) moved to aborted.jsonl and replayed")
    done = out.done_keys()
    out.prune_moves(done)
    engine = engine_factory(stub)
    watchdog = EngineWatchdog(engine, watchdog_interval).start() if watchdog_interval else None
    h = Harness(stub, engine, plan["size"], plan["komi"], plan["rules"], watchdog, plan["timeout"], plan["watch_flags"])
    try:
        for arm_name, idx in plan["order"]:
            spec = plan["schedule"][idx]
            if (arm_name, spec["seed"]) in done:
                continue
            if watchdog is not None:  # 前の局でエンジンが落ちていたら、次の局の前に起こす
                watchdog.ensure_alive()
            elif not engine.check_alive():
                engine.restart()
            result = play_game(
                h,
                arms[arm_name],
                spec,
                make_opponent(plan["opponent"], spec, opponent_arm),
                komi_shift=plan["komi_shift"],
                max_moves=plan["max_moves"],
                hooks=hooks_for(arm_name),
                target=plan["target"],
            )
            out.write_game(result, h.trainer_config)
            done.add((arm_name, spec["seed"]))
            log(progress_line(result.record, len(done), len(plan["order"])))
    finally:
        if watchdog is not None:
            watchdog.stop()
        engine.shutdown(finish=False)


# ---- 要約（summary.txt は cp932 の端末でも読めるよう ASCII のみ）----
def fmt_pct(v):
    return "-" if v is None else f"{100 * v:.1f}%"


def _ci(ci):
    return "-" if not ci or ci[0] is None else f"[{100 * ci[0]:.1f},{100 * ci[1]:.1f}]"


def integrity_warnings(summary):
    """アームごとの計測の健全性の数（相手が最善手で打った回数・humanSL の失敗・hp 監査と影判定の失敗）が 0 でなければ
    `WARN integrity:` の行を返す（数字を信じる前に logs/ を見る）。"""
    lines = []
    for name, s in summary["arms"].items():
        bad = " ".join(f"{k}={v}" for k, v in s["integrity"].items() if v)
        if bad:
            lines.append(f"WARN integrity: arm {name}: {bad}")
    return lines


def format_summary_text(summary):
    lines = [
        "# selfplay summary (own = strategy, opp = opponent; WATCH tree; rates in %)",
        *integrity_warnings(summary),
        "",
    ]
    header = (
        f"{'group':<32} {'n':>3} {'W-L-J':>8} {'win CI':>13} {'own mean':>8} {'own CI':>13} {'opp mean':>8} "
        f"{'own-opp':>7} {'P(o<p)':>6} {'P<=T+5':>6} {'P<15':>6} {'loss o/p':>9} {'>=6':>4} {'flip':>4} "
        f"{'lead med':>8} {'moves':>5} {'hp dev':>6} {'p95 s':>5}"
    )
    for title, groups in (("arms", summary["arms"]), ("arm|rank|color", summary["strata"])):
        lines += [f"## {title}", header]
        for name, s in groups.items():
            played = s["games"] - s["aborted"]
            lines.append(
                f"{name[:32]:<32} {played:>3} {s['wins']:>2}-{s['losses']}-{s['jigo']:<3} {_ci(s['win_ci']):>13} "
                f"{fmt_pct(s['own_top1_mean']):>8} {_ci(s['own_top1_mean_ci']):>13} {fmt_pct(s['opp_top1_mean']):>8} "
                f"{fmt_pct(s['own_minus_opp_mean']):>7} {fmt_pct(s['p_own_lt_opp']):>6} {fmt_pct(s['p_own_le_target_plus5']):>6} "
                f"{fmt_pct(s['p_own_lt_floor']):>6} "
                f"{fmt_num(s['own_mean_ptloss'], '.2f')}/{fmt_num(s['opp_mean_ptloss'], '.2f'):>4} "
                f"{fmt_num(s['ge6_per_game'], '.2f'):>4} {fmt_num(s['flip_per_game'], '.2f'):>4} "
                f"{fmt_num(s['final_lead_median'], '+.1f'):>8} {fmt_num(s['moves_median'], '.0f'):>5} "
                f"{fmt_pct(s['hp_dev_median']):>6} {fmt_num(s['strategy_p95'], '.2f'):>5}"
            )
        lines.append("")
    lines.append("## own top1 by bin (pooled)")
    for name, s in summary["arms"].items():
        bins = " ".join(f"{b}={fmt_pct(v)}" for b, v in s["own_top1_by_bin"].items())
        lines.append(f"{name}: {bins}")
    for compare in summary.get("compare") or []:
        lines += ["", f"## paired diff {compare['a']} - {compare['b']} (same seed; conf {compare['conf']})"]
        for m, d in compare["diffs"].items():
            lines.append(
                f"{m:<16} n={d['n']:>3} mean={fmt_num(d['mean'], '+.4f')} t={fmt_num(d['t_ci'][0], '+.4f')}.."
                f"{fmt_num(d['t_ci'][1], '+.4f')} boot={fmt_num(d['boot_ci'][0], '+.4f')}..{fmt_num(d['boot_ci'][1], '+.4f')} "
                f"wilcoxon_p={fmt_num(d['wilcoxon_p'], '.4f')} verdict(+-3pt)={d['verdict']}"
            )
    if len(summary.get("sources") or []) > 1:
        lines += ["", "## sources"] + summary["sources"]
    text = "\n".join(lines) + "\n"
    return text.encode("ascii", "replace").decode("ascii")


def plan_conditions(plan):
    """対局条件（別々の実行の games.jsonl を合わせて集計してよいかの判定）。アームの設定は指紋で別に見る。"""
    opp = plan.get("opponent") or {}
    resign = plan.get("resign") or {}
    return {
        **{k: plan.get(k) for k in ("size", "komi", "komi_shift", "rules", "max_moves", "watch_flags", "target")},
        "opponent": {k: opp.get(k) for k in ("kind", "ranks", "tau", "max_loss", "strategy", "override_items")},
        "resign": {k: resign.get(k) for k in ("no_resign", "range")},
    }


def load_records(outs):
    """複数の実行の games.jsonl を合わせる（spec §6 停止規則の延長: 20 ペアの後の --seed-base 1020 の実行など）。

    同じ (arm, seed) が2回現れる・同じ名前のアームの設定の指紋が違う・対局条件が違うときは止まる（run.json の無い
    ディレクトリは指紋と条件の突き合わせを飛ばす）。
    """
    records, seen, prints, conditions = [], {}, {}, None
    for out in outs:
        if os.path.exists(out.file("run.json")):
            plan = out.read_json("run.json")
            for arm in plan["arms"]:
                if prints.setdefault(arm["name"], arm["fingerprint"]) != arm["fingerprint"]:
                    raise SystemExit(f"arm {arm['name']}: settings differ between the run directories ({out.path})")
            cond = plan_conditions(plan)
            if conditions is not None and cond != conditions:
                raise SystemExit(f"game conditions differ between the run directories ({out.path})")
            conditions = cond
        for r in out.records():
            key = (r["arm"], r["seed"])
            if key in seen:
                raise SystemExit(f"arm {r['arm']} seed {r['seed']} appears in both {seen[key]} and {out.path}")
            seen[key] = out.path
            records.append(r)
    return records


def summarize_dir(outs, n_boot=10000, compare=None, conf=0.975, dest=None):
    """summary.txt（ASCII）/ summary.json を dest（既定: 最初の実行）に書く。

    outs は OutputDir かそのリスト（複数なら load_records で合わせる）。compare は (A, B) か [(A, B), ...]
    （同じ seed の対の差 A - B。既定の区間 97.5%＝2回見る停止規則）。
    """
    outs = list(outs) if isinstance(outs, (list, tuple)) else [outs]
    dest = dest or outs[0]
    records = load_records(outs)
    summary = S.selfplay_summarize(records, n_boot)
    summary["sources"] = [o.path for o in outs]
    pairs = [tuple(compare)] if compare and isinstance(compare[0], str) else [tuple(c) for c in compare or []]
    if pairs:
        summary["compare"] = []
        for a, b in pairs:
            ra = [r for r in records if r["arm"] == a]
            rb = [r for r in records if r["arm"] == b]
            diffs = {m: S.selfplay_paired_diff(ra, rb, m, n_boot, conf=conf) for m in COMPARE_METRICS}
            summary["compare"].append({"a": a, "b": b, "conf": conf, "diffs": diffs})
    dest.write_json("summary.json", summary)
    text = format_summary_text(summary)
    with open(dest.file("summary.txt"), "w", encoding="ascii", errors="replace") as f:
        f.write(text)
    return summary, text


# ---- 校正（spec §3 calibrate）----
def calibration_result(out, plan):
    records = out.records()
    per_rank = S.calibration_rank_stats(records)
    choices = S.selfplay_pool_choice(per_rank) if plan["size"] == 13 and len(per_rank) >= 3 else []
    best = choices[0] if choices else None
    return {
        "run_dir": out.path,
        "strategy": plan["arms"][0]["strategy"],
        "size": plan["size"],
        "tau": plan["opponent"]["tau"],
        "targets": S.CALIB_TARGETS_13,
        "per_rank": per_rank,
        "choices": choices[:5],
        "best": best,
        "harness_drift_ai": (
            None if best is None or best["own_mean"] is None else best["own_mean"] - S.CALIB_TARGETS_13["ai_mean"]
        ),
    }


def pool_file_content(cal):
    """opponent_pool_<size>.json の中身（run の --opp-pool が ranks と tau を読む）。"""
    best = cal["best"]
    return {
        "board_size": cal["size"],
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_run": cal["run_dir"],
        "strategy": cal["strategy"],
        "ranks": best["ranks"],
        "tau": cal["tau"],
        "fit": best,
        "targets": cal["targets"],
        "per_rank": cal["per_rank"],
        "harness_drift_ai": cal["harness_drift_ai"],
    }


def format_calibration_md(cal):
    t = cal["targets"]
    lines = [
        f"# 自己対局ハーネスの相手ボット校正（{cal['size']}路・{cal['strategy']}・tau {cal['tau']}）",
        "",
        f"実行: `{cal['run_dir']}`",
        "",
        "## 段位ごと（相手＝humanSL・WATCH 木・局単位）",
        "",
        "| 段位 | 局数 | 相手 一致率 局平均 | 局間 SD | 損失/手 | >=2目 | >=5目 | 序盤 一致/損失 | 中盤 | 終盤 | AI 一致率 | 手数中央値 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, s in cal["per_rank"].items():
        b = s["bins"]
        cells = [
            f"{fmt_pct(b[n]['opp_top1'])} / {fmt_num(b[n]['opp_loss'], '.2f')}"
            for n in ("cal_opening", "cal_middle", "cal_endgame")
        ]
        lines.append(
            f"| {rank} | {s['games']} | {fmt_pct(s['opp_mean'])} | {fmt_num(100 * s['opp_sd'], '.1f')}pt | "
            f"{fmt_num(s['opp_loss'], '.2f')} | {fmt_pct(s['opp_ge2'])} | {fmt_pct(s['opp_ge5'])} | {cells[0]} | {cells[1]} | "
            f"{cells[2]} | {fmt_pct(s['own_mean'])} | {fmt_num(s['moves_median'], '.0f')} |"
        )
    b = t["bins"]
    lines += [
        f"| **実戦（目標）** | 16/18 | {fmt_pct(t['opp_mean'])} | {100 * t['opp_sd']:.1f}pt | {t['opp_loss']:.2f} | "
        f"{fmt_pct(t['opp_ge2'])} | {fmt_pct(t['opp_ge5'])} | "
        + " | ".join(
            f"{fmt_pct(b[n]['opp_top1'])} / {b[n]['opp_loss']:.2f}"
            for n in ("cal_opening", "cal_middle", "cal_endgame")
        )
        + f" | {fmt_pct(t['ai_mean'])} | {t['moves_median']} |",
        "",
        "## 3段位プールの候補（スコア = 局平均・局間 SD・損失の目標からのずれの二乗和。小さいほど良い）",
        "",
        "| 順位 | 段位 | 局平均 | 局間 SD | 損失/手 | 中盤 一致/損失 | AI 一致率 | スコア |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(cal["choices"], 1):
        mid = c["bins"]["cal_middle"]
        lines.append(
            f"| {i} | {', '.join(c['ranks'])} | {fmt_pct(c['opp_mean'])} | {fmt_num(100 * c['opp_sd'], '.1f')}pt | "
            f"{fmt_num(c['opp_loss'], '.2f')} | {fmt_pct(mid['opp_top1'])} / {fmt_num(mid['opp_loss'], '.2f')} | "
            f"{fmt_pct(c['own_mean'])} | {c['score']:.2f} |"
        )
    drift = cal["harness_drift_ai"]
    lines += [
        "",
        "## ハーネスと実戦のずれ（AI 側）",
        "",
        f"選んだプールでの AI 一致率 - 実戦の難解＋ 局平均 {fmt_pct(t['ai_mean'])} = "
        f"{'-' if drift is None else f'{100 * drift:+.1f}pt'}（実戦の予測はこの差を引いて読む）",
        "",
    ]
    return "\n".join(lines)
