"""KaTrain の対局ログ（監視対局）から実戦を SGF に戻し、AI の手番を分類する。

    python recon_logs.py                                 # 13路 18局 → recon/（2026-09-18 の元の実行）
    python recon_logs.py --size 9 --log-dir <DIR> --out <DIR>/recon_9   # 9路（ログは experiments/selfplay/realgames-9x9-logs/）
    python recon_logs.py --size 9 --strategy Veil9Strategy --log-dir <DIR> --out <DIR>/recon_9_veil   # 一致率ひかえめ9路

出力: <out>/<game>.sgf・<out>/summary.json（局ごとの AI の色・手数・置き石・局の設定・直したこと・AI の手番の分類）と表。
9路では EXCLUDE_9 の局を除き、ログに出ない相手のパスを挟み、root の置き石になった相手の初手を初手に戻す（spec
2026-09-23-veil-strategy-design.md §16.2 手順1）。9路の既定は難解＋の局だけ（DEFAULT_STRATEGY）で、同じ置き場に退避した
一致率ひかえめ9路の局は --strategy Veil9Strategy で別の出力先（recon_9_veil/）に出す（recon_9 の投了の手数と校正の目標に混ぜない）。**コミット済みの recon/ を上書きしない**よう、13路を走らせ直すなら --out を別にする。
"""

import argparse
import ast
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.expanduser("~/.katrain/logs")

GAMES_13 = [
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
# 9路で除く局（ID で書く・spec §16.2 手順1）
EXCLUDE_9 = {"game_20260919_224212": "持碁9路（初手だけ難解＋）"}
# 盤サイズ → 既定で復元する局の戦略クラス（ログの最初の Generating move using の戦略。無い盤は絞らない）
DEFAULT_STRATEGY = {9: "Enigma9PlusStrategy"}
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
RE_SETTINGS = re.compile(r"^Initializing (\w+) with settings: (\{.*\})\s*$")
RE_SCORE = re.compile(
    r"\] Score ([A-T][0-9]+|pass): vloss=(-?[0-9.]+) \(raw (-?[0-9.]+)\) wr=([0-9.]+)% E=(-?[0-9.]+) .*?own_hp=([0-9.]+)"
)
RE_DEV_E = re.compile(r"\] (Deviate|Gamble): played ([A-T][0-9]+|pass) \((.*?)\) instead of ([A-T][0-9]+|pass)")
RE_MIMIC_SCORE = re.compile(r"\] Score ([A-T][0-9]+|pass): (.*)$")
RE_LEAD = re.compile(r"(?:Spend|Endgame budget|Budget): lead=(-?[0-9.]+)")
RE_KV = re.compile(r"([A-Za-z_]+)=(-?[0-9.]+)")
RE_INIT = re.compile(r'"initialStones": (\[\[.*?\]\]|\[\]), .*?"initialPlayer": "([BW])"')
RE_STONE = re.compile(r'\["([BW])", "([A-T][0-9]+)"\]')
RE_KOMI = re.compile(r'"komi": (-?[0-9.]+)')
OPP_PASSED = "opponent passed"  # 相手のパスの後の AI の手番の理由文（Enigma9Plus: opponent passed but the board is not settled ...）


def insert_opponent_passes(events):
    """ログの「相手の着手」の行に出ない相手のパスを挟む（監視を止めて再開した間のパス）。

    AI の手番の理由文に「opponent passed」があり、その直前が AI の手（またはまだ何も無い）なら、そこに相手のパスを足す。
    -> (直した events, 足した位置〈1 始まりの手数〉のリスト)
    """
    out, inserted = [], []
    for ev in events:
        who, _mv, info = ev
        if who == "ai" and OPP_PASSED in (info or {}).get("reason", "") and (not out or out[-1][0] == "ai"):
            out.append(("opp", "pass", None))
            inserted.append(len(out))
        out.append(ev)
    return out, inserted


def setup_as_first_move(init_stones, first_player):
    """root の置き石が「相手の初手」1子だけ（色が initialPlayer の反対）なら、その手を初手に戻す。

    監視対局で相手の初手の後に局面を取り込むと、その石は root の置き石になる（board_watch の「2子以内なので石数から確定」）。
    -> (置き石, 最初の手番, 初手に戻した手 (色, 座標) か None)
    """
    if len(init_stones) == 1 and init_stones[0][0] != first_player:
        return [], init_stones[0][0], init_stones[0]
    return init_stones, first_player, None


def parse(game, log_dir, size):
    path = os.path.join(log_dir, game + ".log")
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    events = []  # (who, move, info)
    turns = []
    cur = None
    strategy = None
    init_stones = []
    first_player = "B"
    komi = None
    init_seen = False
    settings = {}  # 戦略クラス → 最初の Initializing の設定
    last_settings = {}  # 戦略クラス → 最後の Initializing の設定
    settings_changed = []  # 局の途中で設定が変わった戦略クラス
    for ln in lines:
        if not init_seen and ln.startswith("Sending query"):
            m = RE_INIT.search(ln)
            if m:
                init_stones = RE_STONE.findall(m.group(1))
                first_player = m.group(2)
                mk = RE_KOMI.search(ln)
                komi = float(mk.group(1)) if mk else None
                init_seen = True
        m = RE_SETTINGS.match(ln)
        if m:
            cfg = ast.literal_eval(m.group(2))
            if m.group(1) not in settings:
                settings[m.group(1)] = cfg
            elif cfg != settings[m.group(1)] and m.group(1) not in settings_changed:
                settings_changed.append(m.group(1))
            last_settings[m.group(1)] = cfg
            continue
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
        for line in t["lines"]:
            ms = RE_SCORE.search(line)
            if ms:
                scores[ms.group(1)] = dict(
                    vloss=float(ms.group(2)), wr=float(ms.group(4)), E=float(ms.group(5)), own_hp=float(ms.group(6))
                )
                if first_score is None:
                    first_score = ms.group(1)
            else:
                mm = RE_MIMIC_SCORE.search(line)
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
    inserted = []
    setup_move = None
    if size == 9:  # spec §16.2 手順1: 相手の初手が root の置き石の局・監視の外の相手のパス
        init_stones, first_player, setup_move = setup_as_first_move(init_stones, first_player)
        if setup_move is not None:
            events.insert(0, ("opp", setup_move[1], None))
        events, inserted = insert_opponent_passes(events)
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
    sgf = "(;GM[1]FF[4]SZ[%d]KM[%s]RU[chinese]PB[%s]PW[%s]C[recon from %s]" % (
        size,
        "7" if komi is None or komi == 7.0 else "%g" % komi,
        ("AI:" + strategy) if ai == "B" else "app",
        ("AI:" + strategy) if ai == "W" else "app",
        game,
    )
    for col in "BW":
        pts = [gtp_to_sgf(mv, size) for c, mv in init_stones if c == col]
        if pts:
            sgf += "A%s%s" % (col, "".join("[%s]" % p for p in pts))
    sgf += "PL[%s]" % first_player
    for color, mv in moves:
        sgf += ";%s[%s]" % (color, gtp_to_sgf(mv, size))
    sgf += ")"
    return sgf, {
        "game": game,
        "strategy": strategy,
        "ai": ai,
        "board_size": size,
        "komi": komi,
        "n_moves": len(moves),
        "n_ai_turns": len(turns),
        "init_stones": init_stones,
        "first_player": first_player,
        "setup_as_first_move": list(setup_move) if setup_move else None,
        "inserted_opponent_passes": inserted,
        "settings": settings.get(strategy),
        "settings_last": last_settings.get(strategy),
        "settings_changed": settings_changed,
        "problems": problems,
        "turns": [{k: v for k, v in t.items() if k != "lines"} for t in turns],
    }


def default_games(args):
    if args.games:
        return args.games
    if args.size == 13:
        return GAMES_13
    names = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(args.log_dir, "game_*.log")))
    return [g for g in names if g not in EXCLUDE_9]


def main(argv=None):
    ap = argparse.ArgumentParser(description="KaTrain の監視対局のログ → SGF と AI の手番の分類")
    ap.add_argument(
        "games",
        nargs="*",
        help="ログの名前（game_YYYYMMDD_HHMMSS。既定: 13路は GAMES_13・9路は log-dir の全部 − EXCLUDE_9）",
    )
    ap.add_argument("--log-dir", default=LOGDIR, help="ログのディレクトリ（既定 ~/.katrain/logs）")
    ap.add_argument("--out", default=os.path.join(HERE, "recon"), help="出力先（既定: recon/＝コミット済みの 13路）")
    ap.add_argument("--size", type=int, default=13, choices=(9, 13, 19), help="盤サイズ")
    ap.add_argument(
        "--strategy",
        default=None,
        help="この戦略クラスの局だけ（既定: 9路は Enigma9PlusStrategy・13路は絞らない。一致率ひかえめ9路は Veil9Strategy）",
    )
    args = ap.parse_args(argv)
    only = args.strategy or DEFAULT_STRATEGY.get(args.size)
    os.makedirs(args.out, exist_ok=True)
    all_summ = []
    print(
        "game                 strat        ai init moves turns dev gamble dominant best noadm handoff ? | sum_vloss(dev) dev_hp<.05 dev_bestHP>=.8 | last lead"
    )
    for g in default_games(args):
        parsed = parse(g, args.log_dir, args.size)
        if not parsed:
            print(g, "no events")
            continue
        sgf, s = parsed
        if g in EXCLUDE_9 and args.size == 9:
            print(g, "excluded:", EXCLUDE_9[g])
            continue
        if only and s["strategy"] != only:
            print(g, "skipped: strategy", s["strategy"], "is not", only)
            continue
        with open(os.path.join(args.out, g + ".sgf"), "w", encoding="utf-8") as f:
            f.write(sgf)
        all_summ.append(s)
        T = s["turns"]
        kinds = [t["kind"] for t in T]
        c = lambda k: sum(1 for x in kinds if x == k)  # noqa: E731
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
        if s["setup_as_first_move"]:
            print("   setup stone -> first move:", s["setup_as_first_move"])
        if s["inserted_opponent_passes"]:
            print("   inserted opponent pass at move(s):", s["inserted_opponent_passes"])
        if s["settings_changed"]:
            print("   settings changed during the game:", s["settings_changed"])
        if s["problems"]:
            print("   !!", s["problems"][:3])
        for x in sorted(set(k for k in kinds if k.startswith("?"))):
            print("   ?", x)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(all_summ, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
