"""難解＋9路の実戦ログの集計（spec 2026-09-23-veil-strategy-design.md §16.1。ログを読むだけ・KataGo 不要）。

    python enigma9_log_stats.py [--log-dir DIR]   # 既定: <リポジトリ>/experiments/selfplay/realgames-9x9-logs

1. 自分の一致率（ログの `Move generation complete` の理由文が最善手の手を一致とした数。2500v の事後解析ではない）:
   局ごと・全体・AI の 1〜5 手番目・16 手番目以降。持碁9路の局（EXCLUDE）は数えない。
2. 勝率勾配: `Score` 行（子局面 500 visits の検証値）の最善手（vloss 0）の勝率が 30〜70% の局面で、
   (最善手の勝率 − 候補の勝率) / vloss の中央値（vloss 0.2〜2.0 と 0.5〜2.0）。
3. 安い代わりの手: 検証した候補（最善手以外）の最小 vloss が閾値以下の手番の割合（打つ手の手数の帯ごと）。
2・3 は `Score` 行のある難解＋の手番すべて（持碁9路の局の初手の1手番も含む＝§16.1 の「17 局」）。
最初の `Generating move using` が難解＋9路でないログ（同じ置き場に退避した一致率ひかえめ9路の局など）は 1〜3 のどれにも数えない。
2026-09-26 の値: 一致率 65.7%（261/397）・1〜5 手番目 43.8%・16 手番目以降 75.9%、勾配 26.0%/目（n 236）・24.0%/目
（0.5〜2.0・n 125）、0.3目以内の代わりの手 1〜2手 94%・3〜6手 65%・7〜12手 27%・13〜20手 24%。
"""

import argparse
import glob
import json
import os
import re
import statistics
from collections import Counter

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
LOG_DIR = os.path.join(REPO, "experiments", "selfplay", "realgames-9x9-logs")
EXCLUDE = {"game_20260919_224212"}  # 持碁9路（初手だけ難解＋）＝recon_logs.EXCLUDE_9 と同じ

RE_DONE = re.compile(r"^Move generation complete: (\S+) -- (.*)$")
RE_GEN = re.compile(r"^Generating move using Enigma9PlusStrategy")
RE_FIRST = re.compile(r"^Generating move using (\w+)")
RE_SCORE = re.compile(
    r"\[Enigma9PlusStrategy\] Score (\S+): vloss=([-\d.]+) \(raw ([-\d.]+)\) wr=([\d.]+)% E=([-\d.]+).*?own_hp=([\d.]+)"
)
RE_PROBE = re.compile(r'"analyzeTurns": \[(\d+)\], "maxVisits": 500')
TURN_BANDS = ((1, 2), (3, 6), (7, 12), (13, 20), (21, 999))
CHEAP = (0.1, 0.2, 0.3, 0.5, 1.0)


def turn_kind(reason):
    """AI の手番の理由文 → best（最善手を打った）/ dev / jigo / other（罠・終局の手など）。"""
    if "playing best move" in reason or "most confusing in budget" in reason or "best move is pass" in reason:
        return "best"
    if "deviated to" in reason:
        return "dev"
    if reason.startswith("Jigo"):
        return "jigo"
    return "other"


def first_strategy(path):
    """ログの最初の `Generating move using` の戦略クラス（無ければ None）。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RE_FIRST.match(line)
            if m:
                return m.group(1)
    return None


def own_turns(path):
    """1局の AI の手番の種類（時系列）。"""
    kinds = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RE_DONE.match(line)
            if m:
                kinds.append(turn_kind(m.group(2)))
    return kinds


def probed_decisions(path):
    """1局の難解＋の手番のうち Score 行のあるもの: {"turn": 打つ手の手数, "scores": [{mv, vloss, wr}]}（最初が最善手）。"""
    out, cur = [], None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if RE_GEN.match(line):
                if cur and cur["scores"]:
                    out.append(cur)
                cur = {"turn": None, "scores": []}
                continue
            if cur is None:
                continue
            if cur["turn"] is None and RE_PROBE.search(line):
                query = json.loads(line.split(": ", 1)[1])
                cur["turn"] = len(query.get("initialStones", [])) + len(query.get("moves", []))
            m = RE_SCORE.search(line)
            if m:
                cur["scores"].append({"mv": m.group(1), "vloss": float(m.group(2)), "wr": float(m.group(4))})
    if cur and cur["scores"]:
        out.append(cur)
    return out


def match_rates(logs):
    rows, first5, late = [], [0, 0], [0, 0]
    for path in logs:
        name = os.path.basename(path)[:-4]
        if name in EXCLUDE:
            continue
        kinds = [k for k in own_turns(path) if k != "jigo"]
        best = sum(1 for k in kinds if k == "best")
        rows.append((name, best, len(kinds)))
        for i, k in enumerate(kinds, 1):
            bucket = first5 if i <= 5 else late if i >= 16 else None
            if bucket is not None:
                bucket[0] += k == "best"
                bucket[1] += 1
    return rows, first5, late


def gradient(decisions, lo=0.2, hi=2.0):
    values = []
    for d in decisions:
        best = [s for s in d["scores"] if s["vloss"] == 0.0]
        if d["turn"] is None or not best or not 30 <= best[0]["wr"] <= 70:
            continue
        values += [(best[0]["wr"] - s["wr"]) / s["vloss"] for s in d["scores"] if lo <= s["vloss"] <= hi]
    return values


def cheap_alternatives(decisions):
    bands = {band: [] for band in TURN_BANDS}
    for d in decisions:
        if d["turn"] is None:
            continue
        band = next(b for b in TURN_BANDS if b[0] <= d["turn"] <= b[1])
        bands[band].append(min((s["vloss"] for s in d["scores"][1:]), default=None))
    return bands


def main(argv=None):
    ap = argparse.ArgumentParser(description="難解＋9路の実戦ログの集計（spec §16.1）")
    ap.add_argument(
        "--log-dir", default=LOG_DIR, help="ログのディレクトリ（既定: experiments/selfplay/realgames-9x9-logs）"
    )
    args = ap.parse_args(argv)
    logs = sorted(glob.glob(os.path.join(args.log_dir, "game_*.log")))
    logs = [p for p in logs if first_strategy(p) == "Enigma9PlusStrategy"]  # 難解＋9路の局だけ
    rows, first5, late = match_rates(logs)
    print("## own match rate (log reasons; best / AI turns without Jigo)")
    for name, best, n in rows:
        print(f"{name} {best}/{n} {100 * best / n:.1f}%")
    total = sum(b for _, b, _ in rows), sum(n for _, _, n in rows)
    print(f"all {total[0]}/{total[1]} {100 * total[0] / total[1]:.1f}% ({len(rows)} games)")
    print(f"AI turns 1-5 {first5[0]}/{first5[1]} {100 * first5[0] / first5[1]:.1f}%")
    print(f"AI turns 16+ {late[0]}/{late[1]} {100 * late[0] / late[1]:.1f}%")
    decisions = [d for path in logs for d in probed_decisions(path)]
    games = Counter(os.path.basename(p) for p in logs for _ in probed_decisions(p)[:1])
    print(f"\n## probed decisions: {len(decisions)} in {len(games)} games")
    for label, lo in (("vloss 0.2-2.0", 0.2), ("vloss 0.5-2.0", 0.5 + 1e-9)):
        g = gradient(decisions, lo)
        print(f"winrate gradient {label}: n={len(g)} median={statistics.median(g):.1f}%/pt")
    print("\n## cheapest verified alternative (share of turns with an alternative within the loss)")
    for (lo, hi), mins in cheap_alternatives(decisions).items():
        n = len(mins)
        cells = " ".join(f"<={t}:{100 * sum(1 for x in mins if x is not None and x <= t) / n:.0f}%" for t in CHEAP)
        print(f"moves {lo}-{hi if hi < 999 else '':<3} n={n:>3} {cells}")


if __name__ == "__main__":
    main()
