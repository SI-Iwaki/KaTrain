"""自己対局ハーネスの CLI（戦略 vs humanSL ボットを無人で N 局打たせ、両者の終局レポートの一致率を集計する）。

    python -m katrain_debug.selfplay run --arm A=enigma13plus --arm B=enigma13plus:enigma13plus_max_loss=2.0
        --size 13 --pairs 20 [--opp-pool FILE | --ranks rank_3k,rank_1k,rank_1d] [--komi-shift 4]
        [--resign-model length|lead | --no-resign] [--label NAME] [--resume DIR]
    python -m katrain_debug.selfplay calibrate --size 13 --strategy enigma13plus
        --ranks rank_8k,rank_5k,rank_3k,rank_1k,rank_1d,rank_3d --games 8 [--write-pool FILE]
    python -m katrain_debug.selfplay summarize DIR [DIR ...] [--compare A B]
    python -m katrain_debug.selfplay report-sgf FILE.sgf

（実際のコマンドは1行で打つ。）設計: docs/superpowers/specs/2026-09-23-selfplay-harness-design.md。
**実戦中の KaTrain と同時に走らせない**（§7）。出力は experiments/selfplay/<YYYYMMDD_HHMM>_<label>/（gitignore 済み）。
"""

import os

os.environ["KIVY_NO_ARGS"] = "1"

import argparse  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402

from katrain.core.constants import DATA_FOLDER  # noqa: E402
from katrain_debug import selfplay_run as R  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.katrain_stub import KaTrainStub  # noqa: E402
from katrain_debug.selfplay_game import report_sgf, resolve_arm, start_engine  # noqa: E402
from katrain_debug.selfplay_hooks import make_hooks_factory  # noqa: E402

DEFAULT_CALIB_RANKS = "rank_8k,rank_5k,rank_3k,rank_1k,rank_1d,rank_3d"


def safe_print(text):
    """cp932 の端末でも落ちないよう ASCII に落として出す（戦略の例外文などに日本語が混ざりうる）。"""
    print(str(text).encode("ascii", "replace").decode("ascii"), flush=True)


def katago_processes():
    """起動中の katago.exe（KaTrain の実戦など）の tasklist の行。tasklist が無い環境では空。"""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq katago.exe", "/NH"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line for line in (r.stdout or "").splitlines() if "katago.exe" in line.lower()]


def ensure_no_katago(args):
    """実戦中の KaTrain と GPU を取り合わない（spec §7: 実戦の AI が遅くなり maxTime に当たる）。"""
    if getattr(args, "allow_concurrent", False):
        return
    if katago_processes():
        raise SystemExit(
            "KataGo is already running (KaTrain in a live game?). Stop it first, or pass --allow-concurrent."
        )


@contextlib.contextmanager
def setup_errors():
    """設定の解決（--arm・--opponent・--resign-lead・プール）の KeyError / ValueError だけを `error: ...` で止める。

    対局中の例外は traceback のまま上げる（実行時のバグを利用者向けの1行に丸めない）。
    """
    try:
        yield
    except (KeyError, ValueError) as e:
        raise SystemExit(f"error: {e}") from e


def default_config_path():
    return os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))


def make_stub(config_path):
    return KaTrainStub(config_path or default_config_path(), debug_level=0, quiet=True)


def opponent_plan(args, size):
    """相手の設定。humansl は --ranks か --opp-pool（無ければ calibration-data/selfplay/opponent_pool_<size>.json）。"""
    if args.opponent != "humansl":
        if not args.opponent.startswith("strategy:"):
            raise SystemExit(f"--opponent must be humansl or strategy:NAME[:k=v,...]: {args.opponent!r}")
        _, strategy, items = S.parse_arm("opponent=" + args.opponent[len("strategy:") :])
        return {"kind": "strategy", "strategy": strategy, "override_items": items, "ranks": [f"strategy:{strategy}"]}
    pool_file = args.opp_pool
    if pool_file is None and not args.ranks and os.path.exists(R.default_pool_path(size)):
        pool_file = R.default_pool_path(size)
    pool = None
    if pool_file:
        if not os.path.exists(pool_file):
            raise SystemExit(f"opponent pool not found: {pool_file}")
        with open(pool_file, encoding="utf-8") as f:
            pool = json.load(f)
    ranks = args.ranks.split(",") if args.ranks else (pool or {}).get("ranks")
    if not ranks:
        raise SystemExit("no opponent ranks: pass --ranks or --opp-pool (or run calibrate --write-pool first)")
    tau = args.tau if args.tau is not None else (pool or {}).get("tau", 1.0)
    return {
        "kind": "humansl",
        "ranks": ranks,
        "tau": tau,
        "max_loss": args.opp_max_loss,
        "pool_file": R.repo_relpath(pool_file),
        "pool": pool,
    }


def resign_plan(args, size):
    """投了モデル（--resign-model）:
    - length（既定）: 局ごとに目標の手数 L を実戦 13路 18局の手数から引き、L 以降に AI が明らかに勝っていれば投了。
    - lead: 局ごとに閾値 R を実戦の投了局の最終リード（または --resign-lead LO:HI の一様）から引く。
    --no-resign ならどちらでもなく投了しない（model "none"）。
    """
    start = S.resign_start_move(size)
    common = {"no_resign": False, "range": None, "pool": [], "lengths": [], "start_move": None, "source": None}
    if args.no_resign:
        return {**common, "model": "none", "no_resign": True, "start_move": start}
    if args.resign_lead and args.resign_model != "lead":
        raise SystemExit("--resign-lead LO:HI applies only to --resign-model lead")
    source = R.repo_relpath(R.RECON_DIR)
    if args.resign_model == "length":
        lengths = R.load_resign_lengths(size)
        if not lengths:
            raise SystemExit(
                f"no game lengths in {source}: pass --resign-model lead --resign-lead LO:HI or --no-resign"
            )
        return {**common, "model": "length", "lengths": lengths, "source": source}
    if args.resign_lead:
        return {
            **common,
            "model": "lead",
            "range": list(S.parse_range(args.resign_lead)),
            "start_move": start,
            "source": "--resign-lead",
        }
    pool = R.load_resign_pool(size)
    if not pool:
        raise SystemExit(f"no resign data in {source}: pass --resign-lead LO:HI or --no-resign")
    return {**common, "model": "lead", "pool": pool, "start_move": start, "source": source}


def _schedule(n_seeds, ranks, args, resign):
    return S.selfplay_schedule(
        n_seeds,
        ranks,
        args.seed_base,
        resign_leads=resign["pool"],
        resign_range=resign["range"],
        no_resign=resign["no_resign"],
        resign_lens=resign["lengths"],
    )


def _warn_if_unbalanced(plan):
    warning = S.schedule_balance_warning(plan["schedule"], plan["opponent"]["ranks"])
    if warning:
        safe_print(warning)
    for arm in plan["arms"]:  # spec §11: 戦略の節がユーザー config に無いと、GUI と違うコードの既定値で走る
        if arm["settings_source"] != "user config":
            safe_print(f"note: arm {arm['name']} ({arm['strategy']}): settings_source = {arm['settings_source']}")


def _new_output(args, stub, plan, label):
    out = R.OutputDir.create(args.out_root, label)
    out.write_json("run.json", {**plan, **R.run_meta(stub)})
    safe_print(f"output: {out.path}")
    return out


def _resume(args):
    out = R.OutputDir(args.resume)
    plan = out.read_json("run.json")
    safe_print(f"resume: {out.path}")
    return out, plan, make_stub(plan["config_path"])


def _plan_run(args):
    """run の新しい計画（アームの解決・null ガード・相手・投了・日程）。-> (stub, plan)"""
    if not args.arm:
        raise SystemExit("run needs at least one --arm NAME=STRATEGY[:key=val,...] (or --resume DIR)")
    stub = make_stub(args.config)
    arms = [resolve_arm(stub, *S.parse_arm(text)) for text in args.arm]
    if len({a.name for a in arms}) != len(arms):
        raise SystemExit("arm names must be unique")
    same = S.arms_null_guard([a.as_dict() for a in arms])
    if same:
        raise SystemExit(f"null experiment: arms {same} resolve to identical settings")
    if args.shadow is not None and args.shadow not in {a.name for a in arms}:
        raise SystemExit(f"--shadow {args.shadow}: not one of the --arm names")
    opponent = opponent_plan(args, args.size)
    if opponent["kind"] == "strategy":  # 相手の戦略名と上書きキーの綴りも開始前に確かめる
        resolve_arm(stub, "opponent", opponent["strategy"], opponent["override_items"])
    resign = resign_plan(args, args.size)
    plan = R.make_plan(
        "run",
        arms,
        _schedule(args.pairs, opponent["ranks"], args, resign),
        size=args.size,
        komi=args.komi if args.komi is not None else float(stub.config("game/komi")),
        rules=args.rules or stub.config("game/rules"),
        komi_shift=args.komi_shift,
        max_moves=args.max_moves,
        opponent=opponent,
        resign=resign,
        watch_flags=args.watch_flags,
        timeout=args.timeout,
        extra={
            "config_path": args.config or default_config_path(),
            "shadow": args.shadow,
            "hp_audit": args.hp_audit,
        },
    )
    return stub, plan


def cmd_run(args):
    if args.resume:
        out, plan, stub = _resume(args)
    else:
        with setup_errors():
            stub, plan = _plan_run(args)
        _warn_if_unbalanced(plan)
        out = _new_output(args, stub, plan, args.label or "run")
    R.execute_plan(
        plan,
        out,
        stub,
        engine_factory=start_engine,
        hooks_builder=make_hooks_factory,
        retry_aborted=args.retry_aborted,
        allow_mixed=args.allow_mixed,
        log=safe_print,
    )
    names = [a["name"] for a in plan["arms"]]
    _, text = R.summarize_dir(out, args.boot, compare=[(names[0], n) for n in names[1:]])  # アーム間の差（spec §5）
    safe_print(text)


def _plan_calibrate(args):
    """calibrate の計画（1アーム × 段位ごとに --games 局・色は交互）。-> (stub, plan)"""
    stub = make_stub(args.config)
    arm = resolve_arm(stub, "calib", args.strategy, [])
    ranks = args.ranks.split(",")
    resign = resign_plan(args, args.size)
    opponent = {
        "kind": "humansl",
        "ranks": ranks,
        "tau": 1.0 if args.tau is None else args.tau,
        "max_loss": args.opp_max_loss,
    }
    plan = R.make_plan(
        "calibrate",
        [arm],
        _schedule(args.games * len(ranks), ranks, args, resign),
        size=args.size,
        komi=args.komi if args.komi is not None else float(stub.config("game/komi")),
        rules=args.rules or stub.config("game/rules"),
        max_moves=args.max_moves,
        opponent=opponent,
        resign=resign,
        timeout=args.timeout,
        extra={"config_path": args.config or default_config_path(), "write_pool": args.write_pool},
    )
    return stub, plan


def cmd_calibrate(args):
    if args.resume:
        out, plan, stub = _resume(args)
    else:
        with setup_errors():
            stub, plan = _plan_calibrate(args)
        _warn_if_unbalanced(plan)
        out = _new_output(args, stub, plan, args.label or f"calib-{args.strategy}")
    R.execute_plan(
        plan,
        out,
        stub,
        engine_factory=start_engine,
        retry_aborted=args.retry_aborted,
        allow_mixed=args.allow_mixed,
        log=safe_print,
    )
    summary, _ = R.summarize_dir(out, args.boot)
    for line in R.integrity_warnings(summary):  # review finding on Task 6fix: calibrate must warn too, not just run
        safe_print(line)
    cal = R.calibration_result(out, plan)
    out.write_json("calibration.json", cal)
    with open(out.file("calibration.md"), "w", encoding="utf-8") as f:
        f.write(R.format_calibration_md(cal))
    for rank, s in cal["per_rank"].items():
        safe_print(
            f"{rank}: games={s['games']} opp mean={R.fmt_pct(s['opp_mean'])} sd={R.fmt_num(100 * s['opp_sd'], '.1f')}pt "
            f"loss={R.fmt_num(s['opp_loss'], '.2f')} >=2={R.fmt_pct(s['opp_ge2'])} >=5={R.fmt_pct(s['opp_ge5'])} "
            f"own={R.fmt_pct(s['own_mean'])} moves={R.fmt_num(s['moves_median'], '.0f')}"
        )
    best = cal["best"]
    if best is not None:
        safe_print(
            f"best pool: {best['ranks']} mean={R.fmt_pct(best['opp_mean'])} sd={R.fmt_num(100 * best['opp_sd'], '.1f')}pt "
            f"loss={R.fmt_num(best['opp_loss'], '.2f')} drift_ai={R.fmt_num(cal['harness_drift_ai'], '+.3f')}"
        )
    if plan.get("write_pool") and best is not None:
        with open(plan["write_pool"], "w", encoding="utf-8") as f:
            json.dump(R.pool_file_content(cal), f, ensure_ascii=False, indent=1)
        safe_print(f"pool written: {plan['write_pool']}")
        if cal["integrity"].get("humansl_errors"):
            safe_print("WARN integrity: pool written from games with humanSL errors")
    safe_print(f"calibration: {out.file('calibration.md')}")


def cmd_summarize(args):
    """1つ以上の実行を合わせて集計する（停止規則の延長＝--seed-base をずらした実行を後ろに並べる）。"""
    for d in args.dirs:
        if not os.path.exists(os.path.join(d, "games.jsonl")):
            raise SystemExit(f"{d}: games.jsonl not found")
    outs = [R.OutputDir(d) for d in args.dirs]
    dest = R.OutputDir(args.out) if args.out else None
    compare = tuple(args.compare) if args.compare else None
    _, text = R.summarize_dir(
        outs, args.boot, compare, args.conf, dest=dest, allow_mixed=args.allow_mixed, log=safe_print
    )
    safe_print(text)


def format_report_sgf(result):
    lines = [f"{result['file']}: {result['moves']} moves  (top1 / top5 / mean_ptloss / n)"]
    for tree in ("WATCH", "STRICT"):
        lines.append(f"## {tree}")
        for name, _ in S.REPORT_BINS:
            block = result["reports"][tree][name]
            cells = []
            for label, key in (("B", "ai"), ("W", "opp")):
                b = block[key]
                cells.append(
                    f"{label} {R.fmt_pct(b['top1'])} / {R.fmt_pct(b['top5'])} / {R.fmt_num(b['mean_ptloss'], '.2f')} / {b['n']}"
                )
            lines.append(f"{name:<12} " + "   ".join(cells))
    return "\n".join(lines)


def cmd_report_sgf(args):
    stub = make_stub(args.config)
    engine = start_engine(stub)
    try:
        result = report_sgf(stub, engine, args.file, timeout=args.timeout)
    finally:
        engine.shutdown(finish=False)
    if args.json:
        safe_print(json.dumps(result, indent=1))
    else:
        safe_print(format_report_sgf(result))


def _add_common(p):
    p.add_argument("--size", type=int, default=13, help="盤サイズ（9/13/19）")
    p.add_argument("--seed-base", type=int, default=1000, help="seed の起点（局 i の seed = seed-base + i）")
    p.add_argument("--komi", type=float, default=None, help="コミ（既定: config の game/komi）")
    p.add_argument("--rules", default=None, help="ルール（既定: config の game/rules）")
    p.add_argument("--no-resign", action="store_true", help="相手は投了しない（必須の感度アーム）")
    p.add_argument(
        "--resign-model",
        choices=("length", "lead"),
        default="length",
        help="相手の投了モデル。length（既定）: 実戦の手数 L 以降に AI が明らかに勝っていれば投了"
        "（勝率 >= 0.90・リード >= 2.5目が AI の2手番続く）/ lead: 実戦の最終リード R 以上で投了",
    )
    p.add_argument(
        "--resign-lead",
        default=None,
        metavar="LO:HI",
        help="lead モデルの閾値 R を一様分布で引く（--resign-model lead のときだけ。既定: 実戦の分布）",
    )
    p.add_argument("--tau", type=float, default=None, help="相手の温度 τ（hp^(1/τ)。既定: プールの値か 1.0）")
    p.add_argument("--opp-max-loss", type=float, default=None, help="相手の悪手フィルタ（目。既定 OFF）")
    p.add_argument("--max-moves", type=int, default=None, help="手数上限（既定: 9路 120・13路 250・19路 400）")
    p.add_argument("--timeout", type=float, default=180.0, help="1回の待ちの上限秒（超えたらその局を aborted）")
    p.add_argument("--label", default=None, help="出力ディレクトリ名の末尾")
    p.add_argument("--out-root", default=R.DEFAULT_OUT_ROOT, help="出力の親ディレクトリ")
    p.add_argument("--config", default=None, help="config.json（既定: ~/.katrain/config.json）")
    p.add_argument("--resume", default=None, metavar="DIR", help="落ちた実行を run.json の計画のまま再開")
    p.add_argument(
        "--retry-aborted", action="store_true", help="--resume で aborted の局も打ち直す（行は aborted.jsonl へ移す）"
    )
    p.add_argument(
        "--allow-mixed",
        action="store_true",
        help="--resume でエンジン設定（katago・model・humanlike_model・max_visits・max_time・wide_root_noise）や"
        "コードの版（git HEAD・ai.py の場所）が run.json と違っても続ける（既定は止まる）",
    )
    p.add_argument("--boot", type=int, default=10000, help="bootstrap の回数")
    p.add_argument("--allow-concurrent", action="store_true", help="他の KataGo が動いていても走らせる（非推奨）")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="katrain_debug.selfplay", description="自己対局ハーネス（戦略 vs humanSL ボット）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="アームごとに N 局打って集計する")
    run.add_argument("--arm", action="append", default=[], metavar="NAME=STRATEGY[:key=val,...]")
    run.add_argument("--pairs", type=int, default=20, help="seed の数（全アームが同じ seed を打つ）")
    run.add_argument("--opp-pool", default=None, help="相手の段位プール（calibrate --write-pool の出力）")
    run.add_argument("--ranks", default=None, help="相手の段位（カンマ区切り。プールより優先）")
    run.add_argument("--opponent", default="humansl", help="humansl か strategy:NAME[:key=val,...]")
    run.add_argument("--komi-shift", type=float, default=0.0, help="AI 不利にずらすコミ（接戦ストレス層）")
    run.add_argument("--watch-flags", action="store_true", help="game.board_watch_active を立てる（監視専用の分岐）")
    run.add_argument("--shadow", default=None, metavar="ARM", help="他のアームの各手番でこのアームの判断も記録する")
    run.add_argument("--hp-audit", default=None, metavar="PROFILE", help="hp 監査の humanSL（例 rank_9d）")
    _add_common(run)
    cal = sub.add_parser("calibrate", help="相手ボットの段位ごとの統計を取り、3段位プールを選ぶ")
    cal.add_argument("--strategy", default="enigma13plus", help="校正に使う戦略（runner の戦略名）")
    cal.add_argument("--ranks", default=DEFAULT_CALIB_RANKS)
    cal.add_argument("--games", type=int, default=8, help="段位ごとの局数（色は交互）")
    cal.add_argument("--write-pool", default=None, help="選んだプールを書き出すパス（opponent_pool_13.json）")
    _add_common(cal)
    summ = sub.add_parser("summarize", help="games.jsonl を集計し直す（複数の実行を合わせられる）")
    summ.add_argument("dirs", nargs="+", metavar="DIR", help="実行ディレクトリ（延長の実行を後ろに並べる）")
    summ.add_argument("--out", default=None, metavar="DIR", help="summary.* の書き先（既定: 最初の DIR）")
    summ.add_argument("--compare", nargs=2, metavar=("A", "B"), help="同じ seed の対の差 A - B")
    summ.add_argument("--boot", type=int, default=10000)
    summ.add_argument("--conf", type=float, default=0.975, help="対の差の区間の信頼度（2回見る停止規則で 0.975）")
    summ.add_argument(
        "--allow-mixed",
        action="store_true",
        help="エンジン設定やコードの版（git HEAD・ai.py の場所）が違う実行も合わせる（既定は止まる）",
    )
    rep = sub.add_parser("report-sgf", help="保存 SGF から両者のレポート一致率を出す")
    rep.add_argument("file")
    rep.add_argument("--timeout", type=float, default=1200.0)
    rep.add_argument("--config", default=None)
    rep.add_argument("--json", action="store_true")
    rep.add_argument("--allow-concurrent", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd in ("run", "calibrate", "report-sgf"):
        ensure_no_katago(args)
    handlers = {"run": cmd_run, "calibrate": cmd_calibrate, "summarize": cmd_summarize, "report-sgf": cmd_report_sgf}
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
