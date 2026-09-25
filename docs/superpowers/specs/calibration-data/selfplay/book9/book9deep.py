import sys
sys.argv = [sys.argv[0]]
import importlib.util
spec = importlib.util.spec_from_file_location("b", "book9.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)  # __main__ guard prevents running
root = b.fetch("root/root.html")
def own(node, m):
    return -m["ssM"] if node["npla"] == 1 else m["ssM"]
def walk(first_idx_xy, label, maxply=90):
    node = root
    first = [m for m in root["moves"] if first_idx_xy in m["xy"]][0]
    x, y = first_idx_xy
    rel = node["links"].get(y * 9 + x)
    rows = []
    ply = 2
    while rel and ply <= maxply:
        rel = rel.replace("../", "")
        try:
            node = b.fetch(rel)
        except Exception as e:
            rows.append((ply, "ERR")); break
        mv = [m for m in node["moves"] if m["ssM"] is not None and (m["xy"] or m["pass"])]
        if not mv:
            break
        best = max(own(node, m) for m in mv)
        n02 = sum(1 for m in mv if best - own(node, m) <= 0.2)
        n05 = sum(1 for m in mv if best - own(node, m) <= 0.5)
        n10 = sum(1 for m in mv if best - own(node, m) <= 1.0)
        top = [m for m in node["moves"] if m["xy"] or m["pass"]][0]
        rows.append((ply, node["npla"], len(mv), n02, n05, n10, round(top["p"], 2), round(best, 2)))
        if top["pass"]:
            break
        tx, ty = top["xy"][0]
        rel = node["links"].get(ty * 9 + tx)
        ply += 1
    print(label, "book ends after ply", ply - 1 if rel is None else ply, "(last page with data ply %d)" % rows[-1][0])
    print(" ply side listed n<=0.2 n<=0.5 n<=1.0 topPrior bestOwnScore")
    for r in rows:
        print("  ", r)
for xy, lab in [((3, 3), "4-4"), ((4, 4), "tengen"), ((4, 3), "4-5"), ((4, 2), "3-5")]:
    walk(xy, lab)
