# -*- coding: utf-8 -*-
"""難解＋13路「劣勢演出の罠」の発動回数を、実装そのものを復元 SGF 18 局の窓の中の全 AI 手番に掛けて数える。

    python docs/superpowers/specs/calibration-data/enigma-underdog/underdog_batch_fire.py [--until 50] [--probes 6] [--tag k6]
    python docs/superpowers/specs/calibration-data/enigma-underdog/underdog_batch_fire.py --report underdog-fire-rows-k6.json

1 局ごとに `python -m katrain_debug --batch --player <AI> --move-range 1-<until>` を起動し（KataGo あり・
1 局約 1 分＝18 局で約 17 分）、各手番の ai_thoughts（explanation）から発動を拾う。設定はユーザーの
ローカル config の `ai:enigma13plus` ＋ `underdog_until_move` / `underdog_probes` の上書き。各手番は
実戦の棋譜の局面を独立に撃つ（発動後の局面は辿らない）ので、発動が次の手番の在庫に与える影響は入らない。
実戦中の KaTrain と同時に走らせない。標準出力は ASCII のみ。
"""

import argparse
import json
import os
import re
import statistics as st
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
RECON = os.path.join(HERE, "..", "enigma-overdraft", "recon")
RE_TRAP = re.compile(
    r"underdog trap (\S+) \(verified loss (-?[\d.]+), lead ([+-][\d.]+) if answered correctly, "
    r"([+-][\d.]+) if the\s+opponent falls for it, reply findability ([\d.]+)%\)"
)

ap = argparse.ArgumentParser()
ap.add_argument("--until", type=int, default=50)
ap.add_argument("--probes", type=int, default=6)
ap.add_argument("--tag", default="k6")
ap.add_argument("--report", default=None)
args = ap.parse_args()


def kind(expl):
    if "underdog trap" in expl:
        return "underdog"
    if "gamble trap" in expl:
        return "gamble"
    if "overdraft trap" in expl:
        return "overdraft"
    if "deviated to" in expl:
        return "deviate"
    if "9d opening" in expl:
        return "opening"
    return "best"


def report(rows):
    games = sorted({r["game"] for r in rows})
    ng = len(games)
    fired = [r for r in rows if r["kind"] == "underdog"]
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    per_game = [sum(1 for r in fired if r["game"] == g) for g in games]
    print("games=%d turns=%d (%.1f/game) kinds=%s" % (ng, len(rows), len(rows) / ng, kinds))
    print(
        "underdog fired: %d (%.2f/game) | games with >=1: %d/%d | per game %s"
        % (len(fired), len(fired) / ng, sum(1 for n in per_game if n), ng, per_game)
    )
    if fired:
        print(
            "  vloss med %.2f (min %.2f max %.2f) | answered med %+.2f (min %+.2f) | fooled med %+.2f | find med %.1f%%"
            % (
                st.median(r["vloss"] for r in fired),
                min(r["vloss"] for r in fired),
                max(r["vloss"] for r in fired),
                st.median(r["answered"] for r in fired),
                min(r["answered"] for r in fired),
                st.median(r["fooled"] for r in fired),
                st.median(r["find"] for r in fired),
            )
        )
        for lo, hi in ((0, 20), (20, 30), (30, 40), (40, 50), (50, 999)):
            n = sum(1 for r in fired if lo <= r["move_num"] - 1 < hi)
            if n:
                print("  depth [%d,%d): %d" % (lo, hi, n))
        for r in fired:
            print(
                "   %s d=%-3d %-4s vloss=%5.2f answered=%+5.2f fooled=%+5.2f find=%4.1f%% (best %s)"
                % (
                    r["game"][5:],
                    r["move_num"] - 1,
                    r["selected"],
                    r["vloss"],
                    r["answered"],
                    r["fooled"],
                    r["find"],
                    r["ai_top"],
                )
            )


if args.report:
    path = args.report if os.path.isabs(args.report) else os.path.join(HERE, args.report)
    report(json.load(open(path, encoding="utf-8")))
    sys.exit(0)

games = json.load(open(os.path.join(RECON, "games.json"), encoding="utf-8"))
rows = []
env = dict(os.environ, PYTHONIOENCODING="utf-8")
for g in games:
    sgf = os.path.join(RECON, g["game"] + ".sgf")
    cmd = [
        sys.executable,
        "-m",
        "katrain_debug",
        "--sgf",
        sgf,
        "--strategy",
        "enigma13plus",
        "--batch",
        "--player",
        g["ai"],
        "--move-range",
        "1-%d" % args.until,
        "--output",
        "json",
        "--settings",
        "enigma13plus_underdog_until_move=%d" % args.until,
        "enigma13plus_underdog_probes=%d" % args.probes,
    ]
    res = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True)
    try:
        data = json.loads(res.stdout.decode("utf-8", "replace"))
    except ValueError:
        print("FAILED %s (exit %s)" % (g["game"], res.returncode))
        continue
    n_fire = 0
    for m in data["moves"]:
        expl = m.get("explanation") or ""
        row = {
            "game": g["game"],
            "ai": g["ai"],
            "move_num": m["move_num"],
            "kind": kind(expl),
            "selected": m.get("selected"),
            "ai_top": m.get("ai_top"),
            "point_loss": m.get("point_loss"),
            "winrate_player": m.get("winrate_player"),
        }
        t = RE_TRAP.search(expl)
        if t:
            row.update(
                vloss=float(t.group(2)), answered=float(t.group(3)), fooled=float(t.group(4)), find=float(t.group(5))
            )
            n_fire += 1
        elif row["kind"] == "underdog":
            row["kind"] = "underdog_unparsed"
        rows.append(row)
    print("%s ai=%s turns=%d underdog=%d" % (g["game"], g["ai"], len(data["moves"]), n_fire))
    sys.stdout.flush()

out = os.path.join(HERE, "underdog-fire-rows-%s.json" % args.tag)
json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=True, indent=0)
print("saved", out)
report(rows)
