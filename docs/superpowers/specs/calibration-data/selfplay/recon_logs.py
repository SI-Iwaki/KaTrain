"""Reconstruct 13x13 monitored games from KaTrain game logs and classify each AI turn.

Output: recon/<game>.sgf + recon/summary.json + a printed table.
Throwaway spike script (2026-09-18). v2: carries initial stones / initialPlayer from the first engine query.
"""

import json
import os
import re
import sys

LOGDIR = os.path.expanduser("~/.katrain/logs")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon")
os.makedirs(OUT, exist_ok=True)

GAMES = sys.argv[1:] or [
    "game_20260918_004112",
    "game_20260918_002440",
    "game_20260917_233314",
    "game_20260917_232627",
    "game_20260917_225754",
    "game_20260916_225351",
    "game_20260916_221750",
    "game_20260915_010117",
    "game_20260915_004532",
    "game_20260915_003547",
    "game_20260915_003117",
    "game_20260915_001944",
    "game_20260914_221230",
    "game_20260914_213601",
    "game_20260914_212801",
    "game_20260914_211800",
    "game_20260917_214325",
    "game_20260917_215328",
]
COLS = "ABCDEFGHJKLMNOPQRST"


def gtp_to_sgf(gtp, size=13):
    if gtp.lower() == "pass":
        return ""
    col = COLS.index(gtp[0].upper())
    row = int(gtp[1:])
    return chr(ord("a") + col) + chr(ord("a") + (size - row))


RE_OPP = re.compile(r"^board_watch: 相手の着手 ([A-T][0-9]+|pass) を反映しました")
RE_GEN = re.compile(r"^Generating move using (\w+) \(mode ([^)]+)\)")
RE_DONE = re.compile(r"^Move generation complete: ([A-T][0-9]+|pass) -- (.*)$")
RE_SCORE = re.compile(
    r"\] Score ([A-T][0-9]+|pass): vloss=(-?[0-9.]+) \(raw (-?[0-9.]+)\) wr=([0-9.]+)% E=(-?[0-9.]+) .*?own_hp=([0-9.]+)"
)
RE_DEV_E = re.compile(r"\] (Deviate|Gamble): played ([A-T][0-9]+|pass) \((.*?)\) instead of ([A-T][0-9]+|pass)")
RE_MIMIC_SCORE = re.compile(r"\] Score ([A-T][0-9]+|pass): (.*)$")
RE_LEAD = re.compile(r"(?:Spend|Endgame budget|Budget): lead=(-?[0-9.]+)")
RE_KV = re.compile(r"([A-Za-z_]+)=(-?[0-9.]+)")
RE_INIT = re.compile(r'"initialStones": (\[\[.*?\]\]|\[\]), .*?"initialPlayer": "([BW])"')
RE_STONE = re.compile(r'\["([BW])", "([A-T][0-9]+)"\]')


def parse(game):
    path = os.path.join(LOGDIR, game + ".log")
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    events = []  # (who, move, info)
    turns = []
    cur = None
    strategy = None
    init_stones = []
    first_player = "B"
    init_seen = False
    for ln in lines:
        if not init_seen and ln.startswith("Sending query"):
            m = RE_INIT.search(ln)
            if m:
                init_stones = RE_STONE.findall(m.group(1))
                first_player = m.group(2)
                init_seen = True
        m = RE_OPP.match(ln)
        if m:
            events.append(("opp", m.group(1), None))
            continue
        m = RE_GEN.match(ln)
        if m:
            strategy = strategy or m.group(1)
            cur = {"strategy": m.group(1), "lines": []}
            continue
        if cur is not None:
            if "QUERY" in ln or ln.startswith("Sending query"):
                continue
            cur["lines"].append(ln)
            m = RE_DONE.match(ln)
            if m:
                cur["move"] = m.group(1)
                cur["reason"] = m.group(2)
                turns.append(cur)
                events.append(("ai", m.group(1), cur))
                cur = None
    for t in turns:
        txt = "\n".join(t["lines"])
        r = t["reason"]
        t["kind"] = "?"
        t["best"] = None
        t["vloss"] = None
        t["E"] = None
        t["best_hp"] = None
        t["own_hp"] = None
        t["lead"] = None
        m = RE_LEAD.search(txt)
        if m:
            t["lead"] = float(m.group(1))
        scores = {}
        first_score = None
        for l in t["lines"]:
            ms = RE_SCORE.search(l)
            if ms:
                scores[ms.group(1)] = dict(
                    vloss=float(ms.group(2)), wr=float(ms.group(4)), E=float(ms.group(5)), own_hp=float(ms.group(6))
                )
                if first_score is None:
                    first_score = ms.group(1)
            else:
                mm = RE_MIMIC_SCORE.search(l)
                if mm and "price" in mm.group(2):
                    kv = dict((k, float(v)) for k, v in RE_KV.findall(mm.group(2)))
                    scores[mm.group(1)] = dict(
                        vloss=kv.get("vloss"),
                        E=kv.get("E"),
                        own_hp=kv.get("hp"),
                        price=kv.get("price"),
                        dE=kv.get("dE"),
                    )
                    if first_score is None:
                        first_score = mm.group(1)
        md = RE_DEV_E.search(txt)
        if "9d" in r and "[" in r:
            t["kind"] = "handoff"
        elif md:
            t["kind"] = "deviate" if md.group(1) == "Deviate" else "gamble"
            t["best"] = md.group(4)
            kv = dict((k, float(v)) for k, v in RE_KV.findall(md.group(3)))
            t["vloss"] = kv.get("vloss")
            t["E"] = kv.get("E", kv.get("dE"))
            t["dE"] = kv.get("dE")
            t["price"] = kv.get("price")
            t["own_hp"] = kv.get("hp", scores.get(md.group(2), {}).get("own_hp"))
            t["best_hp"] = scores.get(md.group(4), {}).get("own_hp")
            mk = re.search(r"kind=(\w+)", md.group(3))
            t["dev_kind"] = mk.group(1) if mk else None
        elif "obvious human move" in r or "Dominant:" in txt:
            t["kind"] = "dominant"
            mh = re.search(r"Dominant: best ([A-T][0-9]+|pass) hp=([0-9.]+)", txt)
            if mh:
                t["best_hp"] = float(mh.group(2))
        elif "playing best move" in r or "playing it" in r or "no natural or trap" in r:
            t["kind"] = "best"
            t["best_hp"] = scores.get(first_score, {}).get("own_hp") if first_score else None
            if "no admissible" in r or "no natural" in r:
                t["kind"] = "best_noadm"
        else:
            t["kind"] = "?:" + r[:60]
        t["best_move_logged"] = first_score
    if not events:
        return None
    other = {"B": "W", "W": "B"}
    ai = first_player if events[0][0] == "ai" else other[first_player]
    moves = []
    prev = None
    problems = []
    for who, mv, info in events:
        color = ai if who == "ai" else other[ai]
        if prev == color:
            problems.append(f"same color twice at move {len(moves)+1} ({who} {mv})")
        prev = color
        moves.append((color, mv))
    if moves and moves[0][0] != first_player:
        problems.append(f"first mover {moves[0][0]} != initialPlayer {first_player}")
    sgf = "(;GM[1]FF[4]SZ[13]KM[7]RU[chinese]PB[%s]PW[%s]C[recon from %s]" % (
        ("AI:" + strategy) if ai == "B" else "app",
        ("AI:" + strategy) if ai == "W" else "app",
        game,
    )
    for col in "BW":
        pts = [gtp_to_sgf(mv) for c, mv in init_stones if c == col]
        if pts:
            sgf += "A%s%s" % (col, "".join("[%s]" % p for p in pts))
    sgf += "PL[%s]" % first_player
    for color, mv in moves:
        sgf += ";%s[%s]" % (color, gtp_to_sgf(mv))
    sgf += ")"
    open(os.path.join(OUT, game + ".sgf"), "w", encoding="utf-8").write(sgf)
    summary = {
        "game": game,
        "strategy": strategy,
        "ai": ai,
        "n_moves": len(moves),
        "n_ai_turns": len(turns),
        "init_stones": init_stones,
        "first_player": first_player,
        "problems": problems,
        "turns": [{k: v for k, v in t.items() if k != "lines"} for t in turns],
    }
    return summary


def main():
    all_summ = []
    print(
        "game                 strat        ai init moves turns dev gamble dominant best noadm handoff ? | sum_vloss(dev) dev_hp<.05 dev_bestHP>=.8 | last lead"
    )
    for g in GAMES:
        s = parse(g)
        if not s:
            print(g, "no events")
            continue
        all_summ.append(s)
        T = s["turns"]
        kinds = [t["kind"] for t in T]
        c = lambda k: sum(1 for x in kinds if x == k)
        devs = [t for t in T if t["kind"] in ("deviate", "gamble")]
        sum_vloss = sum(max(0.0, t["vloss"] or 0.0) for t in devs)
        unnat = sum(1 for t in devs if t["own_hp"] is not None and t["own_hp"] < 0.05)
        domdev = sum(1 for t in devs if t["best_hp"] is not None and t["best_hp"] >= 0.8)
        unk = sum(1 for x in kinds if x.startswith("?"))
        leads = [t["lead"] for t in T if t["lead"] is not None]
        print(
            "%-20s %-12s %s %4s %5d %5d %3d %6d %8d %4d %5d %7d %d | %6.1f %6d %8d | %s"
            % (
                g,
                s["strategy"][:12],
                s["ai"],
                "".join(c + m for c, m in s["init_stones"]) or "-",
                s["n_moves"],
                len(T),
                c("deviate"),
                c("gamble"),
                c("dominant"),
                c("best"),
                c("best_noadm"),
                c("handoff"),
                unk,
                sum_vloss,
                unnat,
                domdev,
                ("%.1f" % leads[-1]) if leads else "-",
            )
        )
        if s["problems"]:
            print("   !!", s["problems"][:3])
        for x in sorted(set(k for k in kinds if k.startswith("?"))):
            print("   ?", x)
    json.dump(all_summ, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
