"""自己対局ハーネスの実行計画・出力ディレクトリ・再開・要約（spec §5・§6）。

run.json（計画＋実行環境）を最初に書き、1局ごとに games.jsonl / moves.jsonl に追記して flush する。
--resume は run.json の計画をそのまま使い、games.jsonl にある (arm, seed) を飛ばす（--retry-aborted なら aborted の局は
打ち直す）。要約は複数の実行（停止規則の延長 --seed-base 1020 など）を合わせて出せる。
"""

import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

os.environ.setdefault("KIVY_NO_ARGS", "1")

from katrain.core import ai as ai_module  # noqa: E402
from katrain_debug import selfplay_stats as S  # noqa: E402
from katrain_debug.selfplay_game import (  # noqa: E402
    ENGINE_STALL_S,
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
# 盤サイズ → 投了モデル（length の手数 L）の元データ。無い盤は 13路の recon/ を盤面積で縮めて使う（spec §16.2 手順5）
RECON_DIRS = {9: os.path.join(SELFPLAY_DATA, "recon_9")}
DEFAULT_OUT_ROOT = os.path.join(REPO_ROOT, "experiments", "selfplay")
COMPARE_METRICS = ("own_top1", "opp_top1", "own_minus_opp", "flip_moves", "win", "own_mean_ptloss", "ge6")
CONFIG_SNAPSHOT = "config-snapshot.json"  # run / calibrate が出力ディレクトリに置く config の写し（spec §16.2 手順9）


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def delegate_fingerprint(arm):
    """アーム（run.json の dict か Arm）の序盤の研究外しの任せる先の指紋（任せない・古い run.json は None）。"""
    delegate = arm.get("delegate") if isinstance(arm, dict) else arm.delegate
    return (delegate or {}).get("fingerprint")


def default_pool_path(size):
    return os.path.join(SELFPLAY_DATA, f"opponent_pool_{size}.json")


def repo_relpath(path):
    """記録に残すパス: リポジトリの中ならリポジトリ相対（スラッシュ区切り）、外なら絶対パス（スラッシュ区切り）。

    コミットする成果物（プールの source_run・校正の md）に作業ツリーやマシンの絶対パスを埋め込まないため。
    """
    if path is None:
        return None
    full = os.path.abspath(path)
    try:
        rel = os.path.relpath(full, REPO_ROOT)
    except ValueError:  # Windows で別ドライブ
        rel = None
    if rel is None or rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return full.replace(os.sep, "/")
    return rel.replace(os.sep, "/")


def _recon_summaries(recon_dir):
    summaries = []
    for path in sorted(glob.glob(os.path.join(recon_dir, "report_game_*.json"))):
        with open(path, encoding="utf-8") as f:
            summaries.append(json.load(f)["summary"])
    return summaries


def recon_dir_for(size):
    """盤サイズの実戦の復元と事後解析のディレクトリ（9路は recon_9/＝難解＋9路・それ以外は recon/＝13路）。"""
    return RECON_DIRS.get(size, RECON_DIR)


def load_resign_pool(size, recon_dir=None):
    """lead モデルの投了閾値 R の標本（実戦の投了局の最終リード）。"""
    return S.resign_pool_from_summaries(_recon_summaries(recon_dir or recon_dir_for(size)), size)


def load_resign_lengths(size, recon_dir=None):
    """length モデルの目標の手数 L の標本（9路は recon_9 の手数そのまま・19路は 13路 18局を盤面積で比例）。"""
    return S.resign_lengths_from_summaries(_recon_summaries(recon_dir or recon_dir_for(size)), size)


def git_info(path):
    def git(*args):
        try:
            r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    status = git("status", "--porcelain", "--untracked-files=no")  # 追跡外のファイル（計画のメモ等）は dirty にしない
    return {"head": git("rev-parse", "HEAD"), "dirty": None if status is None else bool(status)}


def run_meta(stub):
    """run.json の実行環境: エンジン設定・ai.py の場所（リポジトリ相対）・git HEAD と dirty（worktree の取り違え対策）。"""
    ai_dir = os.path.dirname(os.path.abspath(ai_module.__file__))
    return {
        "engine": dict(stub.config("engine") or {}),
        "ai_file": repo_relpath(ai_module.__file__),
        "git": git_info(ai_dir),
        "python": sys.version.split()[0],
    }


# 計測の基準（spec §5・§11 設定の取り違え）: 再開と複数の実行の要約で run.json どうし・run.json と今の環境を突き合わせる
BASELINE_ENGINE_KEYS = ("katago", "model", "humanlike_model", "max_visits", "max_time", "wide_root_noise")


def measurement_baseline(meta):
    """run.json（か run_meta）の計測の基準: エンジン設定の6項目・git HEAD・ai.py の場所（数値は 6 == 6.0 に正規化）。"""
    engine = meta.get("engine") or {}
    return {
        **{f"engine.{k}": S.normalize_setting(engine.get(k)) for k in BASELINE_ENGINE_KEYS},
        "git.head": (meta.get("git") or {}).get("head"),
        "ai_file": repo_relpath(meta["ai_file"]) if meta.get("ai_file") else None,
    }


def baseline_differences(recorded, current):
    """違う項目を `key: 記録 vs 今` の文字列のリストで返す（同じなら空）。"""
    a, b = measurement_baseline(recorded), measurement_baseline(current)
    return [f"{k}: {a[k]!r} vs {b[k]!r}" for k in a if a[k] != b[k]]


def check_baseline(recorded, current, where, allow_mixed=False, log=print):
    """計測の基準が違えば止まる（allow_mixed なら WARN を出して続ける）。違いの中身をそのまま出す。"""
    diffs = baseline_differences(recorded, current)
    if not diffs:
        return
    text = f"measurement baseline differs ({where}): " + "; ".join(diffs)
    if not allow_mixed:
        raise SystemExit(f"{text}. Start a new run, or pass --allow-mixed to mix them anyway.")
    log(f"WARN {text} (--allow-mixed)")


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
        "command": [repo_relpath(sys.argv[0])] + sys.argv[1:] if sys.argv and sys.argv[0] else list(sys.argv),
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

    def snapshot_config(self, config_path):
        """使った config の写し（CONFIG_SNAPSHOT）を置き、run.json に足す {config_snapshot, config_sha256} を返す。"""
        shutil.copyfile(config_path, self.file(CONFIG_SNAPSHOT))
        return {"config_snapshot": CONFIG_SNAPSHOT, "config_sha256": file_sha256(self.file(CONFIG_SNAPSHOT))}

    def pinned_config(self, plan):
        """再開で読む config: 写し（中身が run.json の sha256 と違えば止まる）。写しの無い古い実行は plan の config_path。"""
        name = plan.get("config_snapshot")
        if not name:
            return plan["config_path"]
        path = self.file(name)
        if not os.path.exists(path):
            raise SystemExit(f"{path}: the config snapshot named in run.json is missing")
        if file_sha256(path) != plan.get("config_sha256"):
            raise SystemExit(f"{path}: the config snapshot was edited after the run started (sha256 differs)")
        return path

    def _jsonl(self, name, log=print):
        """jsonl の (行の文字列, dict) のリスト。最後の行だけが壊れている（書いている途中で止まった）なら捨てて warning を
        log に出す。途中の行が壊れていれば止まる（手で直す）。"""
        return self._read_jsonl(name, log)[0]

    def _read_jsonl(self, name, log=print):
        """-> (rows, 手を入れるべきか)。手を入れるべき＝書きかけの最後の行を捨てたか、最後の行に改行が無い。"""
        path = self.file(name)
        if not os.path.exists(path):
            return [], False
        with open(path, encoding="utf-8") as f:
            text = f.read()
        lines = [line for line in text.split("\n") if line.strip()]
        rows = []
        for i, line in enumerate(lines, 1):
            try:
                rows.append((line, json.loads(line)))
            except json.JSONDecodeError as e:
                if i < len(lines):
                    raise SystemExit(f"{path}: {name} line {i} is broken ({e}); only a torn last line is skipped")
                log(f"warning: {repo_relpath(path)}: skipped a torn last line ({len(line)} chars, {e.msg})")
        return rows, len(rows) < len(lines) or bool(text) and not text.endswith("\n")

    def _rewrite(self, name, lines):
        """一時ファイルに書いてから os.replace で置き換える（途中で止まっても元のファイルは無傷）。"""
        path = self.file(name)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(line if line.endswith("\n") else line + "\n" for line in lines)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def records(self, log=print):
        return [row for _, row in self._jsonl("games.jsonl", log)]

    def done_keys(self):
        return {(r["arm"], r["seed"]) for r in self.records()}

    def repair_torn_tails(self, log=print):
        """再開の前に: games.jsonl / moves.jsonl の書きかけの最後の行（改行の無い行を含む）を取り除く。

        そのまま追記すると書きかけの行に次の行がつながり、途中の壊れた行になる。取り除いた行は warning で log に出す。
        """
        for name in ("games.jsonl", "moves.jsonl"):
            rows, needs_repair = self._read_jsonl(name, log)
            if needs_repair:
                self._rewrite(name, [line for line, _ in rows])

    def drop_aborted(self):
        """--retry-aborted: games.jsonl から aborted の行を aborted.jsonl へ移す（次の再開で打ち直す）。移した数を返す。"""
        rows = self._jsonl("games.jsonl")
        aborted = [r for _, r in rows if r.get("result") == "aborted"]
        if not aborted:
            return 0
        with open(self.file("aborted.jsonl"), "a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in aborted)
        self._rewrite("games.jsonl", [line for line, r in rows if r.get("result") != "aborted"])
        return len(aborted)

    def prune_moves(self, done):
        """再開時: games.jsonl に無い局（落ちた局の書きかけ）の moves.jsonl の行を捨てる。"""
        if not os.path.exists(self.file("moves.jsonl")):
            return
        rows = self._jsonl("moves.jsonl")
        self._rewrite("moves.jsonl", [line for line, r in rows if (r["arm"], r["seed"]) in done])

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
    allow_mixed=False,
    log=print,
):
    """計画の未完了の局を順に打つ。アームの解決済み設定が計画時と違えば中止（config を途中で変えた）。

    plan が run.json（再開: 実行環境の engine / git / ai_file を含む）なら、計測の基準（エンジン設定・コードの版）を
    今の config とコードと突き合わせ、違えば1局も打たずに止まる（allow_mixed なら WARN を出して続ける）。
    各局の前にエンジンの死活を見て、落ちていれば再起動する（spec §2: 落ちた局だけ aborted にして続行）。
    hooks_builder(plan, arms) -> factory(arm_name) -> [hook]（hp 監査・影判定。selfplay_hooks.make_hooks_factory）。
    retry_aborted: 再開のとき aborted の局も打ち直す（OutputDir.drop_aborted）。
    """
    if "engine" in plan:
        check_baseline(plan, run_meta(stub), f"resume {repo_relpath(out.path)}", allow_mixed, log)
    arms = {}
    for entry in plan["arms"]:
        arm = resolve_arm(stub, entry["name"], entry["strategy"], entry["override_items"])
        if arm.fingerprint != entry["fingerprint"]:
            raise SystemExit(
                f"arm {entry['name']}: resolved settings differ from run.json (config edited?). Start a new run."
            )
        if delegate_fingerprint(arm) != delegate_fingerprint(entry):  # 序盤の研究外しの任せる先（難解＋の節）
            raise SystemExit(
                f"arm {entry['name']}: the delegate of the opening window differs from run.json (config edited?). "
                "Start a new run."
            )
        arms[arm.name] = arm
    opponent_arm = None
    if plan["opponent"]["kind"] == "strategy":
        o = plan["opponent"]
        opponent_arm = resolve_arm(stub, "opponent", o["strategy"], o["override_items"])
    hooks_for = hooks_builder(plan, arms) if hooks_builder else (lambda name: [])
    out.repair_torn_tails(log)  # 前の実行が行の途中で止まっていたら、その行を捨ててから追記する
    if retry_aborted:
        n = out.drop_aborted()
        if n:
            log(f"retry: {n} aborted game(s) moved to aborted.jsonl and replayed")
    done = out.done_keys()
    out.prune_moves(done)
    engine = engine_factory(stub)
    watchdog = None
    if watchdog_interval:  # 返事の無い KataGo の検出は、待ちの上限（--timeout）と 180 秒の長い方
        stall_timeout = max(ENGINE_STALL_S, plan["timeout"])
        watchdog = EngineWatchdog(engine, watchdog_interval, stall_timeout=stall_timeout).start()
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


def _integrity_warning_line(label, integrity):
    """`integrity`（fallbacks・humansl_errors・hp_audit_errors・shadow_errors の4つの合計）に1つでも 0 でない
    ものがあれば `WARN integrity: <label>: ...` の行を返す（無ければ None）。summary（run）と calibrate の
    calibration.md の両方がこれで同じ文言を出す。"""
    bad = " ".join(f"{k}={v}" for k, v in integrity.items() if v)
    return f"WARN integrity: {label}: {bad}" if bad else None


def integrity_warnings(summary):
    """アームごとの計測の健全性の数（相手が最善手で打った回数・humanSL の失敗・hp 監査と影判定の失敗）が 0 でなければ
    `WARN integrity:` の行を返す（数字を信じる前に logs/ を見る）。"""
    lines = []
    for name, s in summary["arms"].items():
        line = _integrity_warning_line(f"arm {name}", s["integrity"])
        if line:
            lines.append(line)
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
                f"wilcoxon_p={fmt_num(d['wilcoxon_p'], '.4f')} verdict(+-3pt)={d['verdict'] or '-'}"
            )
    if len(summary.get("sources") or []) > 1:
        lines += ["", "## sources"] + summary["sources"]
    text = "\n".join(lines) + "\n"
    return text.encode("ascii", "replace").decode("ascii")


def resign_model_of_plan(resign):
    """計画の投了モデル（length / lead / none）。model の無い古い run.json は lead か none（--no-resign）。"""
    if resign.get("model"):
        return resign["model"]
    return "none" if resign.get("no_resign") else "lead"


def plan_conditions(plan):
    """対局条件（別々の実行の games.jsonl を合わせて集計してよいかの判定）。アームの設定は指紋で別に見る。"""
    opp = plan.get("opponent") or {}
    resign = plan.get("resign") or {}
    return {
        **{k: plan.get(k) for k in ("size", "komi", "komi_shift", "rules", "max_moves", "watch_flags", "target")},
        "opponent": {
            k: opp.get(k)
            for k in ("kind", "ranks", "tau", "max_loss", "strategy", "override_items", "book_moves", "book_loss")
        },
        "resign": {"model": resign_model_of_plan(resign), **{k: resign.get(k) for k in ("no_resign", "range")}},
    }


def load_records(outs, allow_mixed=False, log=print):
    """複数の実行の games.jsonl を合わせる（spec §6 停止規則の延長: 20 ペアの後の --seed-base 1020 の実行など）。

    同じ (arm, seed) が2回現れる・同じ名前のアームの設定の指紋が違う・対局条件が違うときは止まる。計測の基準
    （エンジン設定・コードの版）が最初の実行と違うときも止まる（allow_mixed なら WARN を出して合わせる）。
    run.json の無いディレクトリは突き合わせを飛ばす。
    """
    records, seen, prints, delegates, conditions, first = [], {}, {}, {}, None, None
    for out in outs:
        if os.path.exists(out.file("run.json")):
            plan = out.read_json("run.json")
            for arm in plan["arms"]:
                if prints.setdefault(arm["name"], arm["fingerprint"]) != arm["fingerprint"]:
                    raise SystemExit(f"arm {arm['name']}: settings differ between the run directories ({out.path})")
                if delegates.setdefault(arm["name"], delegate_fingerprint(arm)) != delegate_fingerprint(arm):
                    raise SystemExit(
                        f"arm {arm['name']}: the delegate of the opening window differs between the run directories "
                        f"({out.path})"
                    )
            cond = plan_conditions(plan)
            if conditions is not None and cond != conditions:
                raise SystemExit(f"game conditions differ between the run directories ({out.path})")
            conditions = cond
            if first is None:
                first = (out, plan)
            else:
                where = f"{repo_relpath(first[0].path)} vs {repo_relpath(out.path)}"
                check_baseline(first[1], plan, where, allow_mixed, log)
        for r in out.records(log):
            key = (r["arm"], r["seed"])
            if key in seen:
                raise SystemExit(f"arm {r['arm']} seed {r['seed']} appears in both {seen[key]} and {out.path}")
            seen[key] = out.path
            records.append(r)
    return records


def summarize_dir(outs, n_boot=10000, compare=None, conf=0.975, dest=None, allow_mixed=False, log=print):
    """summary.txt（ASCII）/ summary.json を dest（既定: 最初の実行）に書く。

    outs は OutputDir かそのリスト（複数なら load_records で合わせる。allow_mixed は計測の基準の違いを許す）。
    compare は (A, B) か [(A, B), ...]（同じ seed の対の差 A - B。既定の区間 97.5%＝2回見る停止規則）。
    """
    outs = list(outs) if isinstance(outs, (list, tuple)) else [outs]
    dest = dest or outs[0]
    records = load_records(outs, allow_mixed, log)
    summary = S.selfplay_summarize(records, n_boot)
    summary["sources"] = [repo_relpath(o.path) for o in outs]
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
    targets = S.calib_targets_for(plan["size"])  # 目標の無い盤（19路）はプールを選ばない
    choices = S.selfplay_pool_choice(per_rank, targets) if targets is not None and len(per_rank) >= 3 else []
    best = choices[0] if choices else None
    # 計測の健全性: calibrate も run と同じ4つの合計を出す（全アーム＝全局分）。集計式は selfplay_arm_summary と
    # 共有（S.integrity_totals）。
    integrity = S.integrity_totals(records)
    arm_name = plan["arms"][0].get("name", "calib")
    return {
        "run_dir": repo_relpath(out.path),  # プールの source_run と md に入る＝作業ツリーの絶対パスを埋め込まない
        "strategy": plan["arms"][0]["strategy"],
        "strategy_overrides": list(plan["arms"][0].get("override_items") or []),  # calibrate --strategy NAME:k=v,...
        "size": plan["size"],
        "tau": plan["opponent"]["tau"],
        "resign_model": resign_model_of_plan(plan.get("resign") or {}),
        "targets": targets,
        "targets_games": S.CALIB_TARGET_GAMES.get(plan["size"]),
        "per_rank": per_rank,
        "choices": choices[:5],
        "best": best,
        "harness_drift_ai": (
            None if best is None or best["own_mean"] is None else best["own_mean"] - targets["ai_mean"]
        ),
        "integrity": integrity,
        "integrity_warning": _integrity_warning_line(f"arm {arm_name}", integrity),
    }


def pool_file_content(cal):
    """opponent_pool_<size>.json の中身（run の --opp-pool が ranks と tau を読む）。"""
    best = cal["best"]
    return {
        "board_size": cal["size"],
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_run": cal["run_dir"],
        "strategy": cal["strategy"],
        "strategy_overrides": cal.get("strategy_overrides") or [],
        "ranks": best["ranks"],
        "tau": cal["tau"],
        "resign_model": cal.get("resign_model"),
        "fit": best,
        "targets": cal["targets"],
        "per_rank": cal["per_rank"],
        "harness_drift_ai": cal["harness_drift_ai"],
    }


def format_calibration_md(cal):
    t = cal["targets"]
    overrides = cal.get("strategy_overrides") or []
    strategy = cal["strategy"] + (f"（上書き {', '.join(overrides)}）" if overrides else "")
    lines = [
        f"# 自己対局ハーネスの相手ボット校正（{cal['size']}路・{strategy}・tau {cal['tau']}）",
        "",
    ]
    if cal.get("integrity_warning"):
        lines += [cal["integrity_warning"], ""]
    lines += [
        f"実行: `{cal['run_dir']}`（投了モデル: {cal.get('resign_model') or '-'}）",
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
    if t is not None:  # 目標の無い盤（19路）は行を出さない
        b = t["bins"]
        lines.append(
            f"| **実戦（目標）** | {cal.get('targets_games') or '-'} | {fmt_pct(t['opp_mean'])} | {100 * t['opp_sd']:.1f}pt | "
            f"{t['opp_loss']:.2f} | {fmt_pct(t['opp_ge2'])} | {fmt_pct(t['opp_ge5'])} | "
            + " | ".join(
                f"{fmt_pct(b[n]['opp_top1'])} / {b[n]['opp_loss']:.2f}"
                for n in ("cal_opening", "cal_middle", "cal_endgame")
            )
            + f" | {fmt_pct(t['ai_mean'])} | {t['moves_median']} |"
        )
    lines += [
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
        f"選んだプールでの AI 一致率 - 実戦の難解＋ 局平均 {fmt_pct(t['ai_mean'] if t else None)} = "
        f"{'-' if drift is None else f'{100 * drift:+.1f}pt'}（実戦の予測はこの差を引いて読む）",
        "",
    ]
    return "\n".join(lines)
