import re, urllib.request, sys, json
BASE = "https://katagobooks.org/book9x9tt/"
COLS = "ABCDEFGHJ"
cache = {}
def fetch(rel):
    if rel in cache: return cache[rel]
    url = BASE + rel
    import subprocess; html = subprocess.run(["curl", "-s", "-m", "30", url], capture_output=True).stdout.decode("utf-8")
    npla = int(re.search(r"const nextPla = (\d)", html).group(1))
    board = [int(x) for x in re.search(r"const board = \[([^\]]*)\]", html).group(1).split(",") if x.strip()]
    links = dict((int(k), v) for k, v in re.findall(r"(\d+):'([^']+)'", re.search(r"const links = \{(.*?)\};", html, re.S).group(1)))
    mv_src = re.search(r"const moves = \[(.*?)\];", html, re.S).group(1)
    moves = []
    for m in re.finditer(r"\{(.*?)\},(?=\{|$)", mv_src, re.S):
        body = m.group(1)
        d = {}
        xy = re.search(r"'xy':\[(.*?)\],'", body)
        d["xy"] = [tuple(map(int, p)) for p in re.findall(r"\[(\d+),(\d+)\]", xy.group(1))] if xy else []
        d["pass"] = "'move':'pass'" in body
        for k in ["p", "wl", "ssM"]:
            mm = re.search(r"'%s':(-?[\d.]+)" % k, body)
            d[k] = float(mm.group(1)) if mm else None
        moves.append(d)
    r = dict(npla=npla, board=board, links=links, moves=moves, stones=sum(1 for b in board if b))
    cache[rel] = r
    return r
def name(xy):
    x, y = xy
    return COLS[x] + str(9 - y)
def summarize(node, label):
    npla = node["npla"]
    sgn = 1 if npla == 1 else -1  # black to move: lower ssM better
    mv = [m for m in node["moves"] if m["ssM"] is not None and (m["xy"] or m["pass"])]
    # mover's score = -ssM for black, +ssM for white
    for m in mv:
        m["own"] = -m["ssM"] if npla == 1 else m["ssM"]
        m["ownwin"] = 0.5 * (1 - m["wl"]) if npla == 1 else 0.5 * (1 + m["wl"])
    best = max(m["own"] for m in mv)
    bestwin = max(m["ownwin"] for m in mv)
    out = []
    for th in (0.1, 0.2, 0.5, 1.0):
        g = [m for m in mv if best - m["own"] <= th]
        out.append((th, len(g), sum(max(1, len(m["xy"])) for m in g)))
    wth = [m for m in mv if bestwin - m["ownwin"] <= 0.03]
    print(f"{label}: {'B' if npla==1 else 'W'} to play, stones={node['stones']}, book moves listed={len(mv)} groups; best own score={best:+.2f} bestwin={bestwin*100:.1f}%")
    print("   within (pts: distinct groups / incl. symmetric):", ", ".join(f"<={t}: {a}/{b}" for t, a, b in out), f"| win% within 3pp: {len(wth)} groups")
    for m in sorted(mv, key=lambda m: -m["own"])[:10]:
        nm = "pass" if m["pass"] else name(m["xy"][0]) + (f"(x{len(m['xy'])})" if len(m["xy"]) > 1 else "")
        print(f"     {nm:10s} own_score={m['own']:+.2f} loss={best-m['own']:.2f} ownWin={m['ownwin']*100:.1f}% prior={m['p']*100:.1f}%")
    return mv
def child(node, m):
    x, y = m["xy"][0]
    return node["links"][y * 9 + x].replace("../", "")
if __name__ == "__main__":
    root = fetch("root/root.html")
    mv = summarize(root, "ply1 root")
    # for each optimal first-move class, go down the book's preferred line (moves[0]) for 5 more plies
    for first in sorted(mv, key=lambda m: -m["own"])[:4]:
        rel = child(root, first)
        label = name(first["xy"][0])
        node = fetch(rel)
        path = [label]
        for ply in range(2, 7):
            ms = summarize(node, f"  after {' '.join(path)} (ply{ply})")
            nxt = [m for m in node["moves"] if m["xy"] or m["pass"]][0]
            if nxt.get("pass") or not nxt["xy"]:
                break
            path.append(name(nxt["xy"][0]))
            try:
                node = fetch(child(node, nxt))
            except Exception as e:
                print("   stop:", e); break
        print()
